"""Visitor routes: registration, age attestation, GPC signal stream,
consent preview."""
from flask import Blueprint, request

from db import store, new_id, now_iso, touch
from clock import get_now
from errors import ApiError
from response import ok, ok_list
from services.consent import (
    PURPOSE_CATEGORIES,
    parse_dt,
    check_role,
    check_read_role,
    check_ownership,
    pagination_args,
    sort_created,
    get_visitor_or_404,
    applicable_policy,
    recompute_expiries,
    adjust_granted_count,
    effective_decision,
)
from services.expiry import evaluate_time_based_effects

bp = Blueprint("visitors", __name__)
blueprint = bp


def _body():
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


def _require_str(value, field):
    if not isinstance(value, str) or not value:
        raise ApiError(
            "ERR_INVALID_REQUEST", "Field %s is required and must be a string" % field, 400
        )
    return value


# ---------------------------------------------------------------------------
# POST /v1/visitors — register a visitor (Anonymous only)
# ---------------------------------------------------------------------------


@bp.post("/v1/visitors")
def create_visitor():
    check_role("Anonymous")
    body = _body()
    property_id = _require_str(body.get("property_id"), "property_id")
    external_ref = _require_str(body.get("external_ref"), "external_ref")
    jurisdiction_code = _require_str(body.get("jurisdiction_code"), "jurisdiction_code")
    attested = body.get("attested_birthdate")
    if attested is not None:
        if not isinstance(attested, str) or parse_dt(attested) is None:
            raise ApiError(
                "ERR_INVALID_REQUEST", "attested_birthdate must be an ISO8601 datetime", 400
            )
    if property_id not in store["properties"]:
        raise ApiError("ERR_PROPERTY_NOT_FOUND", "Property not found", 404)

    now = now_iso()
    visitor = {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "property_id": property_id,
        "external_ref": external_ref,
        "jurisdiction_code": jurisdiction_code,
        # stored but NOT evaluated: age gate runs only at explicit attestation
        "attested_birthdate": attested,
        "age_status": "UNVERIFIED",
        "gpc_effective": "UNSET",
        "gpc_updated_at": None,
        "sale_share_opted_out": False,
    }
    store["visitors"][visitor["id"]] = visitor
    return ok(visitor, status=201)


# ---------------------------------------------------------------------------
# GET /v1/visitors — list (property_id filter)
# ---------------------------------------------------------------------------


@bp.get("/v1/visitors")
def list_visitors():
    check_read_role()
    limit, offset = pagination_args()
    items = list(store["visitors"].values())
    property_id = request.args.get("property_id")
    if property_id is not None:
        items = [v for v in items if v.get("property_id") == property_id]
    items = sort_created(items)
    total = len(items)
    return ok_list(items[offset : offset + limit], total, limit, offset)


# ---------------------------------------------------------------------------
# GET /v1/visitors/{id}
# ---------------------------------------------------------------------------


@bp.get("/v1/visitors/<visitor_id>")
def get_visitor(visitor_id):
    check_read_role()
    visitor = get_visitor_or_404(visitor_id)
    return ok(visitor)


# ---------------------------------------------------------------------------
# POST /v1/visitors/{id}/age-attestation — Visitor, ownership
# ---------------------------------------------------------------------------


@bp.post("/v1/visitors/<visitor_id>/age-attestation")
def age_attestation(visitor_id):
    check_role("Visitor")
    check_ownership(visitor_id)
    visitor = get_visitor_or_404(visitor_id)
    body = _body()
    attested = body.get("attested_birthdate")
    if not isinstance(attested, str) or parse_dt(attested) is None:
        raise ApiError(
            "ERR_INVALID_REQUEST", "attested_birthdate must be an ISO8601 datetime", 400
        )
    policy = applicable_policy(visitor)
    if policy is None:
        raise ApiError(
            "ERR_NO_ACTIVE_POLICY",
            "No ACTIVE JurisdictionPolicy for the visitor's jurisdiction",
            409,
        )
    min_age = int(policy.get("min_consent_age", 0))
    birth = parse_dt(attested).date()
    try:
        qualifying = birth.replace(year=birth.year + min_age)
    except ValueError:
        # Feb 29 birthdate: qualifying birthday observed on Feb 28
        qualifying = birth.replace(year=birth.year + min_age, day=28)
    today = get_now().date()
    # ADULT iff birthdate + min_consent_age years <= current clock date
    # (exact birthday qualifies)
    visitor["attested_birthdate"] = attested
    visitor["age_status"] = "ADULT" if qualifying <= today else "CHILD"
    touch(visitor)
    return ok(visitor)


# ---------------------------------------------------------------------------
# GPC signals
# ---------------------------------------------------------------------------


@bp.post("/v1/visitors/<visitor_id>/gpc-signals")
def create_gpc_signal(visitor_id):
    check_role("Visitor")
    check_ownership(visitor_id)
    visitor = get_visitor_or_404(visitor_id)
    body = _body()
    signal = body.get("signal")
    if signal not in ("ON", "OFF"):
        raise ApiError("ERR_INVALID_REQUEST", "signal must be ON or OFF", 400)

    # settle any pending retention expiries before the cascade inspects GRANTED
    evaluate_time_based_effects()

    now = now_iso()
    event = {
        "id": new_id(),
        "created_at": now,
        "visitor_id": visitor_id,
        "signal": signal,
    }
    store["gpc_events"][event["id"]] = event

    visitor["gpc_effective"] = signal
    visitor["gpc_updated_at"] = now
    if signal == "ON":
        policy = applicable_policy(visitor)
        if policy is not None and policy.get("gpc_honored"):
            visitor["sale_share_opted_out"] = True
            # honoring cascade: GRANTED SALE_SHARE records -> WITHDRAWN
            targets = [
                r
                for r in store["consent_records"].values()
                if r.get("visitor_id") == visitor_id
                and r.get("purpose_category") == "SALE_SHARE"
                and r.get("status") == "GRANTED"
            ]
            targets.sort(key=lambda r: r.get("created_at") or "")
            for record in targets:
                record["status"] = "WITHDRAWN"
                record["source_of_decision"] = "AUTO_GPC_WITHDRAW"
                record["last_changed_at"] = now
                recompute_expiries(record)
                touch(record)
                adjust_granted_count(record.get("property_id"), -1)
    else:
        # OFF clears the flag but never resurrects cascaded withdrawals
        visitor["sale_share_opted_out"] = False
    touch(visitor)
    return ok(event, status=201)


@bp.get("/v1/visitors/<visitor_id>/gpc-signals")
def list_gpc_signals(visitor_id):
    check_read_role()
    get_visitor_or_404(visitor_id)
    limit, offset = pagination_args()
    items = [
        e for e in store["gpc_events"].values() if e.get("visitor_id") == visitor_id
    ]
    items = sort_created(items)
    total = len(items)
    return ok_list(items[offset : offset + limit], total, limit, offset)


# ---------------------------------------------------------------------------
# GET /v1/visitors/{id}/consent-preview?purpose_category=X — computed read,
# evaluates the waterfall WITHOUT persisting anything.
# ---------------------------------------------------------------------------


@bp.get("/v1/visitors/<visitor_id>/consent-preview")
def consent_preview(visitor_id):
    check_read_role()
    visitor = get_visitor_or_404(visitor_id)
    purpose = request.args.get("purpose_category")
    if purpose not in PURPOSE_CATEGORIES:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "purpose_category must be one of NECESSARY, ANALYTICS, ADVERTISING, SALE_SHARE",
            400,
        )
    # EXPIRED records are treated as absent — settle lazy expiry first
    evaluate_time_based_effects()
    return ok({"decision": effective_decision(visitor, purpose)})
