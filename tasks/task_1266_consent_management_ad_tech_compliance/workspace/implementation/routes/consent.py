"""Consent record routes: grant, list/get, withdraw, regrant."""
from flask import Blueprint, request

from db import store, new_id, now_iso, touch
from clock import get_now
from errors import ApiError
from response import ok, ok_list
from services.consent import (
    PURPOSE_CATEGORIES,
    check_role,
    check_read_role,
    check_ownership,
    pagination_args,
    sort_created,
    get_visitor_or_404,
    active_policies,
    policy_in_window,
    published_config,
    property_frozen,
    find_live_record,
    recompute_expiries,
    recompute_rolling,
    adjust_granted_count,
    parse_dt,
    fmt_dt,
    add_days,
)
from services.expiry import evaluate_time_based_effects

bp = Blueprint("consent", __name__)
blueprint = bp


def _body():
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


def _get_record_or_404(record_id):
    record = store["consent_records"].get(record_id)
    if record is None:
        raise ApiError("ERR_CONSENT_RECORD_NOT_FOUND", "ConsentRecord not found", 404)
    return record


def _apply_grant_gates(visitor, purpose_category):
    """Shared grant/regrant ladder rungs 5-11 (posture, age, child, policy,
    window). Posture is checked by the caller before transition preconditions
    where the ladder demands it; this helper covers rungs 7/8/9/11 and
    returns the covering ACTIVE policy."""
    if visitor.get("age_status") == "UNVERIFIED":
        raise ApiError(
            "ERR_AGE_UNVERIFIED",
            "Consent grant requires a completed age attestation",
            409,
        )
    if visitor.get("age_status") == "CHILD" and purpose_category != "NECESSARY":
        raise ApiError(
            "ERR_CHILD_CONSENT_FORBIDDEN",
            "CHILD visitor may only be granted the NECESSARY purpose",
            403,
        )
    pols = active_policies(visitor.get("property_id"), visitor.get("jurisdiction_code"))
    if not pols:
        raise ApiError(
            "ERR_NO_ACTIVE_POLICY",
            "No ACTIVE JurisdictionPolicy for the visitor's jurisdiction",
            409,
        )
    now = get_now()
    covering = None
    for p in pols:
        if policy_in_window(p, now):
            covering = p
            break
    if covering is None:
        raise ApiError(
            "ERR_POLICY_OUTSIDE_COVERAGE_WINDOW",
            "Current clock is outside the ACTIVE policy's coverage window",
            409,
        )
    return covering


def _stamp_grant(record, visitor, policy):
    """Transition into GRANTED: snapshot retention, bind the PUBLISHED banner
    config of the visitor's jurisdiction, stamp timestamps, compute expiries."""
    now = now_iso()
    cfg = published_config(visitor.get("property_id"), visitor.get("jurisdiction_code"))
    record["banner_config_id"] = cfg.get("id") if cfg is not None else None
    record["policy_snapshot_retention_days"] = int(policy.get("retention_days", 0))
    record["last_changed_at"] = now
    record["source_of_decision"] = "EXPLICIT_GRANT"
    record["expires_at_pinned"] = fmt_dt(
        add_days(parse_dt(now), record["policy_snapshot_retention_days"])
    )
    record["expires_at_rolling"] = record["expires_at_pinned"]
    recompute_rolling(record)


# ---------------------------------------------------------------------------
# POST /v1/visitors/{id}/consent-records — grant consent (Visitor, ownership)
# ---------------------------------------------------------------------------


@bp.post("/v1/visitors/<visitor_id>/consent-records")
def create_consent_record(visitor_id):
    check_role("Visitor")
    check_ownership(visitor_id)
    visitor = get_visitor_or_404(visitor_id)
    body = _body()
    purpose = body.get("purpose_category")
    if purpose not in PURPOSE_CATEGORIES:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "purpose_category must be one of NECESSARY, ANALYTICS, ADVERTISING, SALE_SHARE",
            400,
        )

    # settle lazy expiry so EXPIRED records release the uniqueness gate
    evaluate_time_based_effects()

    prop = store["properties"].get(visitor.get("property_id"))
    if property_frozen(prop):
        raise ApiError("ERR_PROPERTY_FROZEN", "Property posture FROZEN blocks the mutation", 409)
    policy = _apply_grant_gates(visitor, purpose)

    if find_live_record(visitor_id, purpose) is not None:
        raise ApiError(
            "ERR_DUPLICATE_CONSENT_PURPOSE",
            "A GRANTED or WITHDRAWN ConsentRecord already exists for this visitor and purpose",
            409,
        )

    now = now_iso()
    record = {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "visitor_id": visitor_id,
        "property_id": visitor.get("property_id"),
        "purpose_category": purpose,
        "status": "GRANTED",
        "banner_config_id": None,
        "policy_snapshot_retention_days": None,
        "last_changed_at": None,
        "expires_at_pinned": None,
        "expires_at_rolling": None,
        "source_of_decision": None,
    }
    _stamp_grant(record, visitor, policy)
    store["consent_records"][record["id"]] = record
    adjust_granted_count(record["property_id"], +1)
    return ok(record, status=201)


# ---------------------------------------------------------------------------
# Lists and single-record reads
# ---------------------------------------------------------------------------


@bp.get("/v1/visitors/<visitor_id>/consent-records")
def list_visitor_consent_records(visitor_id):
    check_read_role()
    get_visitor_or_404(visitor_id)
    evaluate_time_based_effects()
    limit, offset = pagination_args()
    items = [
        r for r in store["consent_records"].values() if r.get("visitor_id") == visitor_id
    ]
    status = request.args.get("status")
    if status is not None:
        items = [r for r in items if r.get("status") == status]
    purpose = request.args.get("purpose_category")
    if purpose is not None:
        items = [r for r in items if r.get("purpose_category") == purpose]
    items = sort_created(items)
    for r in items:
        recompute_rolling(r)
    total = len(items)
    return ok_list(items[offset : offset + limit], total, limit, offset)


@bp.get("/v1/consent-records")
def list_consent_records():
    check_read_role()
    evaluate_time_based_effects()
    limit, offset = pagination_args()
    items = list(store["consent_records"].values())
    property_id = request.args.get("property_id")
    if property_id is not None:
        items = [r for r in items if r.get("property_id") == property_id]
    status = request.args.get("status")
    if status is not None:
        items = [r for r in items if r.get("status") == status]
    purpose = request.args.get("purpose_category")
    if purpose is not None:
        items = [r for r in items if r.get("purpose_category") == purpose]
    items = sort_created(items)
    for r in items:
        recompute_rolling(r)
    total = len(items)
    return ok_list(items[offset : offset + limit], total, limit, offset)


@bp.get("/v1/consent-records/<record_id>")
def get_consent_record(record_id):
    check_read_role()
    evaluate_time_based_effects()
    record = _get_record_or_404(record_id)
    recompute_rolling(record)
    return ok(record)


# ---------------------------------------------------------------------------
# POST /v1/consent-records/{id}/withdraw — allowed even when FROZEN
# ---------------------------------------------------------------------------


@bp.post("/v1/consent-records/<record_id>/withdraw")
def withdraw_consent_record(record_id):
    check_role("Visitor")
    record = _get_record_or_404(record_id)
    check_ownership(record.get("visitor_id"))
    evaluate_time_based_effects()
    if record.get("status") != "GRANTED":
        raise ApiError(
            "ERR_CONSENT_INVALID_TRANSITION",
            "Withdraw requires the record to be GRANTED",
            409,
        )
    record["status"] = "WITHDRAWN"
    record["last_changed_at"] = now_iso()
    record["source_of_decision"] = "EXPLICIT_WITHDRAW"
    recompute_expiries(record)
    touch(record)
    adjust_granted_count(record.get("property_id"), -1)
    return ok(record)


# ---------------------------------------------------------------------------
# POST /v1/consent-records/{id}/regrant — WITHDRAWN -> GRANTED, gates re-applied
# ---------------------------------------------------------------------------


@bp.post("/v1/consent-records/<record_id>/regrant")
def regrant_consent_record(record_id):
    check_role("Visitor")
    record = _get_record_or_404(record_id)
    check_ownership(record.get("visitor_id"))
    evaluate_time_based_effects()
    prop = store["properties"].get(record.get("property_id"))
    if property_frozen(prop):
        raise ApiError("ERR_PROPERTY_FROZEN", "Property posture FROZEN blocks the mutation", 409)
    if record.get("status") != "WITHDRAWN":
        raise ApiError(
            "ERR_CONSENT_INVALID_TRANSITION",
            "Regrant requires the record to be WITHDRAWN",
            409,
        )
    visitor = get_visitor_or_404(record.get("visitor_id"))
    policy = _apply_grant_gates(visitor, record.get("purpose_category"))
    record["status"] = "GRANTED"
    _stamp_grant(record, visitor, policy)
    touch(record)
    adjust_granted_count(record.get("property_id"), +1)
    return ok(record)
