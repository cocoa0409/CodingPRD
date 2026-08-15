"""Clock, landlord, jurisdiction-rule, criteria, applicant routes."""

from flask import Blueprint, request

from db import store
from errors import (
    ApiError,
    ERR_INVALID_REQUEST,
    ERR_NOT_FOUND,
    ERR_STALE_VERSION,
    ERR_INVALID_CRITERIA_STATE,
    ERR_CRITERIA_WINDOW_OVERLAP,
)
from middleware import get_context, require_role, check_landlord_ownership
from response import success_object, success_list
from services.core import (
    check_rule_window_overlap,
    covering_published_criteria,
    application_report,
    withdraw_cleanup,
)
from util import (
    clock, fmt_dt, parse_dt, get_body,
    req_string, opt_string, req_int, opt_int, req_number, req_bool, req_enum,
    pagination_params, paginate, stamp_new, touch, serialize,
)

bp = Blueprint("setup", __name__)


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------

@bp.route("/api/_clock/set_current_utc", methods=["POST"])
def set_clock():
    user_id, role = get_context()
    require_role(role, ["ComplianceAdmin"])
    body = get_body()
    raw = body.get("to_iso8601")
    if raw is None:
        raise ApiError(ERR_INVALID_REQUEST, "Missing required field: to_iso8601", 400)
    store.clock = parse_dt(raw, "to_iso8601")
    return success_object({"current_utc": fmt_dt(store.clock)})


# ---------------------------------------------------------------------------
# Landlords
# ---------------------------------------------------------------------------

@bp.route("/api/landlords", methods=["POST"])
def create_landlord():
    user_id, role = get_context()
    require_role(role, ["ComplianceAdmin"])
    body = get_body()
    landlord = stamp_new({
        "name": req_string(body, "name"),
        "contact_email": req_string(body, "contact_email"),
        "status": "ACTIVE",
        "fee_balance_cents": 0,
        "suspended_at": None,
    })
    store.landlords[landlord["id"]] = landlord
    return success_object(serialize(landlord), 201)


@bp.route("/api/landlords/<lid>", methods=["GET"])
def get_landlord(lid):
    user_id, role = get_context()
    require_role(role, ["ComplianceAdmin", "Screener", "Landlord", "Applicant"])
    landlord = store.landlords.get(lid)
    if landlord is None:
        raise ApiError(ERR_NOT_FOUND, "Landlord not found", 404)
    check_landlord_ownership(user_id, role, landlord["id"])
    return success_object(serialize(landlord))


@bp.route("/api/landlords/<lid>/suspend", methods=["POST"])
def suspend_landlord(lid):
    user_id, role = get_context()
    require_role(role, ["ComplianceAdmin"])
    landlord = store.landlords.get(lid)
    if landlord is None:
        raise ApiError(ERR_NOT_FOUND, "Landlord not found", 404)
    if landlord["status"] != "SUSPENDED":
        landlord["status"] = "SUSPENDED"
        landlord["suspended_at"] = clock()
        touch(landlord)
        # Cascade: every non-terminal application -> CANCELLED
        for app in store.applications.values():
            if app["landlord_id"] != lid:
                continue
            if app["status"] in ("DRAFT", "SUBMITTED", "SCREENING", "SCORED"):
                app["status"] = "CANCELLED"
                touch(app)
                withdraw_cleanup(app, landlord)
    return success_object(serialize(landlord))


# ---------------------------------------------------------------------------
# Jurisdiction rules
# ---------------------------------------------------------------------------

@bp.route("/api/jurisdiction-rules", methods=["POST"])
def create_rule():
    user_id, role = get_context()
    require_role(role, ["ComplianceAdmin"])
    body = get_body()
    state_code = req_string(body, "state_code")
    criminal_lookback = req_int(body, "criminal_lookback_years")
    eviction_lookback = req_int(body, "eviction_lookback_years")
    if criminal_lookback < 0:
        raise ApiError(ERR_INVALID_REQUEST, "Field 'criminal_lookback_years' must be >= 0", 400)
    if eviction_lookback < 0:
        raise ApiError(ERR_INVALID_REQUEST, "Field 'eviction_lookback_years' must be >= 0", 400)
    soi_protected = req_bool(body, "source_of_income_protected")
    portable_required = req_bool(body, "portable_report_acceptance_required")
    max_fee = opt_int(body, "max_screening_fee_cents", None)
    effective_from_raw = body.get("effective_from")
    if effective_from_raw is None:
        raise ApiError(ERR_INVALID_REQUEST, "Missing required field: effective_from", 400)
    effective_from = parse_dt(effective_from_raw, "effective_from")
    effective_to = None
    if body.get("effective_to") is not None:
        effective_to = parse_dt(body["effective_to"], "effective_to")

    check_rule_window_overlap(state_code, effective_from, effective_to)

    rule = stamp_new({
        "state_code": state_code,
        "criminal_lookback_years": criminal_lookback,
        "eviction_lookback_years": eviction_lookback,
        "source_of_income_protected": soi_protected,
        "portable_report_acceptance_required": portable_required,
        "max_screening_fee_cents": max_fee,
        "effective_from": effective_from,
        "effective_to": effective_to,
    })
    store.jurisdiction_rules[rule["id"]] = rule
    return success_object(serialize(rule), 201)


@bp.route("/api/jurisdiction-rules", methods=["GET"])
def list_rules():
    user_id, role = get_context()
    require_role(role, ["ComplianceAdmin", "Screener", "Landlord", "Applicant"])
    state_code = request.args.get("state_code")
    items = sorted(store.jurisdiction_rules.values(), key=lambda r: r["created_at"])
    if state_code is not None:
        items = [r for r in items if r["state_code"] == state_code]
    limit, offset = pagination_params()
    page, total = paginate(items, limit, offset)
    return success_list([serialize(r) for r in page], limit, offset, total)


# ---------------------------------------------------------------------------
# Screening criteria
# ---------------------------------------------------------------------------

@bp.route("/api/criteria", methods=["POST"])
def create_criteria():
    user_id, role = get_context()
    require_role(role, ["Landlord"])
    body = get_body()
    landlord = store.landlords.get(user_id)
    if landlord is None:
        raise ApiError(ERR_NOT_FOUND, "Acting landlord not found", 404)

    name = req_string(body, "name")
    disclosure_summary = req_string(body, "disclosure_summary")
    min_credit_score = req_int(body, "min_credit_score")
    income_multiplier = req_number(body, "income_multiplier")
    guarantor_policy = req_enum(body, "guarantor_policy", ("INDEPENDENT_ONLY", "COMBINED_ALLOWED"))
    guarantor_income_multiplier = req_number(body, "guarantor_income_multiplier")
    accepts_portable = req_bool(body, "accepts_portable_reports")
    accepts_voucher = req_bool(body, "accepts_voucher_income")
    effective_from_raw = body.get("effective_from")
    if effective_from_raw is None:
        raise ApiError(ERR_INVALID_REQUEST, "Missing required field: effective_from", 400)
    effective_from = parse_dt(effective_from_raw, "effective_from")
    effective_to = None
    if body.get("effective_to") is not None:
        effective_to = parse_dt(body["effective_to"], "effective_to")

    criteria = stamp_new({
        "landlord_id": user_id,
        "name": name,
        "disclosure_summary": disclosure_summary,
        "min_credit_score": min_credit_score,
        "income_multiplier": income_multiplier,
        "guarantor_policy": guarantor_policy,
        "guarantor_income_multiplier": guarantor_income_multiplier,
        "accepts_portable_reports": accepts_portable,
        "accepts_voucher_income": accepts_voucher,
        "effective_from": effective_from,
        "effective_to": effective_to,
        "status": "DRAFT",
        "published_at": None,
    })
    store.criteria[criteria["id"]] = criteria
    return success_object(serialize(criteria), 201)


@bp.route("/api/criteria", methods=["GET"])
def list_criteria():
    user_id, role = get_context()
    require_role(role, ["ComplianceAdmin", "Screener", "Landlord", "Applicant"])
    items = sorted(store.criteria.values(), key=lambda c: c["created_at"])
    landlord_id = request.args.get("landlord_id")
    status = request.args.get("status")
    if role == "Landlord":
        items = [c for c in items if c["landlord_id"] == user_id]
    if landlord_id is not None:
        items = [c for c in items if c["landlord_id"] == landlord_id]
    if status is not None:
        items = [c for c in items if c["status"] == status]
    limit, offset = pagination_params()
    page, total = paginate(items, limit, offset)
    return success_list([serialize(c) for c in page], limit, offset, total)


@bp.route("/api/criteria/<cid>", methods=["GET"])
def get_criteria(cid):
    user_id, role = get_context()
    require_role(role, ["ComplianceAdmin", "Screener", "Landlord", "Applicant"])
    criteria = store.criteria.get(cid)
    if criteria is None:
        raise ApiError(ERR_NOT_FOUND, "Criteria not found", 404)
    check_landlord_ownership(user_id, role, criteria["landlord_id"])
    return success_object(serialize(criteria))


@bp.route("/api/criteria/<cid>/publish", methods=["POST"])
def publish_criteria(cid):
    user_id, role = get_context()
    require_role(role, ["Landlord"])
    criteria = store.criteria.get(cid)
    if criteria is None:
        raise ApiError(ERR_NOT_FOUND, "Criteria not found", 404)
    check_landlord_ownership(user_id, role, criteria["landlord_id"])
    landlord = store.landlords[criteria["landlord_id"]]

    body = get_body()
    expected = body.get("expected_landlord_version")
    if expected is None:
        raise ApiError(ERR_INVALID_REQUEST, "Missing required field: expected_landlord_version", 400)
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise ApiError(ERR_INVALID_REQUEST, "Field 'expected_landlord_version' must be an integer", 400)
    # OCC (stage 5)
    if expected != landlord["version"]:
        raise ApiError(
            ERR_STALE_VERSION,
            "expected_landlord_version does not match the landlord's current version",
            412,
        )
    # From-state (stage 6)
    if criteria["status"] != "DRAFT":
        raise ApiError(
            ERR_INVALID_CRITERIA_STATE,
            "Criteria not in DRAFT",
            409,
        )
    # Closed-window overlap with other PUBLISHED criteria of the same landlord.
    # Both endpoints inclusive -> touching endpoints conflict.
    for other in store.criteria.values():
        if other["id"] == criteria["id"]:
            continue
        if other["landlord_id"] != criteria["landlord_id"] or other["status"] != "PUBLISHED":
            continue
        a_from, a_to = criteria["effective_from"], criteria["effective_to"]
        b_from, b_to = other["effective_from"], other["effective_to"]
        # Closed windows overlap iff a_from <= b_to AND b_from <= a_to (None end = +inf)
        cond1 = True if b_to is None else a_from <= b_to
        cond2 = True if a_to is None else b_from <= a_to
        if cond1 and cond2:
            raise ApiError(
                ERR_CRITERIA_WINDOW_OVERLAP,
                "Closed effective window overlaps another PUBLISHED criteria of the same landlord",
                409,
            )

    criteria["status"] = "PUBLISHED"
    criteria["published_at"] = clock()
    touch(criteria)
    landlord["version"] += 1
    landlord["updated_at"] = clock()
    return success_object(serialize(criteria))


@bp.route("/api/criteria/<cid>/archive", methods=["POST"])
def archive_criteria(cid):
    user_id, role = get_context()
    require_role(role, ["Landlord"])
    criteria = store.criteria.get(cid)
    if criteria is None:
        raise ApiError(ERR_NOT_FOUND, "Criteria not found", 404)
    check_landlord_ownership(user_id, role, criteria["landlord_id"])
    if criteria["status"] not in ("DRAFT", "PUBLISHED"):
        raise ApiError(ERR_INVALID_CRITERIA_STATE, "Criteria not in DRAFT or PUBLISHED", 409)
    criteria["status"] = "ARCHIVED"
    touch(criteria)
    return success_object(serialize(criteria))


# ---------------------------------------------------------------------------
# Applicants
# ---------------------------------------------------------------------------

@bp.route("/api/applicants", methods=["POST"])
def create_applicant():
    user_id, role = get_context()
    require_role(role, ["Screener"])
    body = get_body()
    full_name = req_string(body, "full_name")
    dob_raw = body.get("dob")
    if dob_raw is None:
        raise ApiError(ERR_INVALID_REQUEST, "Missing required field: dob", 400)
    dob = parse_dt(dob_raw, "dob")
    email = req_string(body, "email")
    ssn_last4 = req_string(body, "ssn_last4")
    if len(ssn_last4) != 4 or not ssn_last4.isdigit():
        raise ApiError(ERR_INVALID_REQUEST, "Field 'ssn_last4' must be exactly 4 digits", 400)
    residence_state = req_string(body, "residence_state")

    applicant = stamp_new({
        "full_name": full_name,
        "dob": dob,
        "email": email,
        "ssn_last4": ssn_last4,
        "residence_state": residence_state,
    })
    store.applicants[applicant["id"]] = applicant
    return success_object(serialize(applicant), 201)
