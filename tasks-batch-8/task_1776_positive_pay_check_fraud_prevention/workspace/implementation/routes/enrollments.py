"""Enrollment lifecycle, config patch (OCC), tier change, reports (PRD §3.1)."""
from flask import Blueprint, request

import store
from auth import ALL_ROLES, authenticate, authorize, check_ownership
from errors import (
    ERR_ENROLLMENT_NOT_ACTIVATABLE,
    ERR_ENROLLMENT_NOT_ACTIVE,
    ERR_ENROLLMENT_NOT_SETTLED,
    ERR_INVALID_REQUEST,
    ERR_STALE_VERSION,
    ERR_TIER_CHANGE_NOT_ALLOWED,
    raise_err,
)
from services import (
    DEFAULT_DECISIONS,
    TIERS,
    adoption_report,
    enrollment_out,
    fee_statement,
    guard_enrollment_mutable,
    open_exception_count,
    trailing_90d_issued_volume,
)
from util import (
    body_json,
    bump,
    get_or_404,
    new_record,
    opt_int,
    opt_nullable_int,
    req_enum,
    req_str,
    success_object,
    valid_year_month,
)

bp = Blueprint("enrollments", __name__)

REPORT_ROLES = ["BankTreasuryManager", "BankOps", "CustomerAdmin", "CustomerManager", "CustomerViewer"]


def _ranged(value, key, lo, hi):
    if value < lo or (hi is not None and value > hi):
        raise_err(ERR_INVALID_REQUEST, "%s must be between %s and %s" % (key, lo, hi))
    return value


def _patch_int(body, key, lo, hi):
    """Optional non-nullable integer knob on PATCH: absent -> skip; explicit
    null or wrong type or out of range -> shape error."""
    if key not in body:
        return None, False
    v = body.get(key)
    if not isinstance(v, int) or isinstance(v, bool):
        raise_err(ERR_INVALID_REQUEST, "%s must be an integer" % key)
    return _ranged(v, key, lo, hi), True


@bp.route("/treasury/enrollments", methods=["POST"])
def create_enrollment():
    _, role, _user = authenticate()
    authorize(role, _user, ["BankTreasuryManager"])
    body = body_json()
    business_name = req_str(body, "business_name")
    tier = req_enum(body, "tier", TIERS)
    default_decision = req_enum(body, "default_decision", DEFAULT_DECISIONS)
    deadline_mode = body.get("deadline_mode", "SAME_DAY_CUTOFF")
    if deadline_mode not in ("SAME_DAY_CUTOFF", "ROLLING_HOURS"):
        raise_err(ERR_INVALID_REQUEST, "deadline_mode must be SAME_DAY_CUTOFF or ROLLING_HOURS")
    decision_window_hours = _ranged(opt_int(body, "decision_window_hours", 24), "decision_window_hours", 1, 72)
    amount_tolerance_cents = _ranged(opt_int(body, "amount_tolerance_cents", 0), "amount_tolerance_cents", 0, None)
    payee_score_threshold = _ranged(opt_int(body, "payee_score_threshold", 85), "payee_score_threshold", 0, 100)
    stale_days = _ranged(opt_int(body, "stale_days", 180), "stale_days", 0, None)
    loss_present, loss_threshold = opt_nullable_int(body, "loss_suspension_threshold_cents")
    if loss_present and loss_threshold is not None and loss_threshold < 0:
        raise_err(ERR_INVALID_REQUEST, "loss_suspension_threshold_cents must be non-negative or null")

    rec = new_record()
    rec.update({
        "business_name": business_name,
        "tier": tier,
        "default_decision": default_decision,
        "deadline_mode": deadline_mode,
        "decision_window_hours": decision_window_hours,
        "amount_tolerance_cents": amount_tolerance_cents,
        "payee_score_threshold": payee_score_threshold,
        "stale_days": stale_days,
        "loss_suspension_threshold_cents": loss_threshold if loss_present else None,
        "status": "PENDING_ACTIVATION",
    })
    store.enrollments[rec["id"]] = rec
    return success_object(enrollment_out(rec), 201)


@bp.route("/treasury/enrollments/<eid>", methods=["GET"])
def get_enrollment(eid):
    _, role, user = authenticate()
    authorize(role, user, ALL_ROLES)
    rec = get_or_404(store.enrollments, eid, "TreasuryEnrollment")
    check_ownership(user, rec["id"])
    return success_object(enrollment_out(rec), 200)


@bp.route("/treasury/enrollments/<eid>", methods=["PATCH"])
def patch_enrollment(eid):
    _, role, user = authenticate()
    authorize(role, user, ["BankTreasuryManager", "CustomerAdmin"])
    rec = store.enrollments.get(eid)
    if rec is not None:
        check_ownership(user, rec["id"])
    body = body_json()
    expected = body.get("expected_enrollment_version")
    if not isinstance(expected, int) or isinstance(expected, bool):
        raise_err(ERR_INVALID_REQUEST, "expected_enrollment_version is required and must be an integer")
    # shape-validate supplied config fields before existence/OCC (p4 < p5 < p6)
    patch = {}
    if "default_decision" in body:
        patch["default_decision"] = req_enum(body, "default_decision", DEFAULT_DECISIONS)
    for key, lo, hi in (
        ("decision_window_hours", 1, 72),
        ("amount_tolerance_cents", 0, None),
        ("payee_score_threshold", 0, 100),
        ("stale_days", 0, None),
    ):
        value, present = _patch_int(body, key, lo, hi)
        if present:
            patch[key] = value
    if "loss_suspension_threshold_cents" in body:
        _present, v = opt_nullable_int(body, "loss_suspension_threshold_cents")
        if v is not None and v < 0:
            raise_err(ERR_INVALID_REQUEST, "loss_suspension_threshold_cents must be non-negative or null")
        patch["loss_suspension_threshold_cents"] = v

    if rec is None:
        get_or_404(store.enrollments, eid, "TreasuryEnrollment")
    # OCC (p6) is evaluated before any state preconditions (p7)
    if expected != rec["version"]:
        raise_err(ERR_STALE_VERSION, "expected_enrollment_version is stale")
    guard_enrollment_mutable(rec)
    if user is not None and rec["status"] != "ACTIVE":
        # customer-side write while not ACTIVE
        raise_err(ERR_ENROLLMENT_NOT_ACTIVE, "Enrollment is not ACTIVE")
    for k, v in patch.items():
        rec[k] = v
    bump(rec)
    return success_object(enrollment_out(rec), 200)


@bp.route("/treasury/enrollments/<eid>/activate", methods=["POST"])
def activate_enrollment(eid):
    _, role, _user = authenticate()
    authorize(role, _user, ["BankTreasuryManager"])
    body_json()
    rec = get_or_404(store.enrollments, eid, "TreasuryEnrollment")
    guard_enrollment_mutable(rec)
    if rec["status"] == "PENDING_ACTIVATION":
        completed = any(
            s["enrollment_id"] == rec["id"] and s["status"] == "COMPLETED"
            for s in store.sessions.values()
        )
        if not completed:
            raise_err(
                ERR_ENROLLMENT_NOT_ACTIVATABLE,
                "Initial activation requires at least one COMPLETED training session",
            )
    elif rec["status"] == "SUSPENDED":
        pass  # re-activation does NOT re-check the training gate (PRD §3.1)
    else:
        raise_err(ERR_ENROLLMENT_NOT_ACTIVATABLE, "Enrollment cannot be activated from %s" % rec["status"])
    rec["status"] = "ACTIVE"
    bump(rec)
    return success_object(enrollment_out(rec), 200)


@bp.route("/treasury/enrollments/<eid>/suspend", methods=["POST"])
def suspend_enrollment(eid):
    _, role, _user = authenticate()
    authorize(role, _user, ["BankTreasuryManager"])
    body_json()
    rec = get_or_404(store.enrollments, eid, "TreasuryEnrollment")
    guard_enrollment_mutable(rec)
    if rec["status"] != "ACTIVE":
        raise_err(ERR_ENROLLMENT_NOT_ACTIVE, "Only an ACTIVE enrollment can be suspended")
    rec["status"] = "SUSPENDED"
    bump(rec)
    return success_object(enrollment_out(rec), 200)


@bp.route("/treasury/enrollments/<eid>/terminate", methods=["POST"])
def terminate_enrollment(eid):
    _, role, _user = authenticate()
    authorize(role, _user, ["BankTreasuryManager"])
    body_json()
    rec = get_or_404(store.enrollments, eid, "TreasuryEnrollment")
    guard_enrollment_mutable(rec)
    if rec["status"] not in ("ACTIVE", "SUSPENDED"):
        raise_err(ERR_ENROLLMENT_NOT_SETTLED, "Enrollment cannot be terminated from %s" % rec["status"])
    accounts_open = any(
        a["enrollment_id"] == rec["id"] and a["status"] != "CLOSED"
        for a in store.accounts.values()
    )
    if accounts_open or open_exception_count(rec["id"]) > 0:
        raise_err(
            ERR_ENROLLMENT_NOT_SETTLED,
            "All accounts must be CLOSED and no exception may be OPEN",
        )
    rec["status"] = "TERMINATED"
    bump(rec)
    return success_object(enrollment_out(rec), 200)


@bp.route("/treasury/enrollments/<eid>/change-tier", methods=["POST"])
def change_tier(eid):
    _, role, _user = authenticate()
    authorize(role, _user, ["BankTreasuryManager"])
    rec = store.enrollments.get(eid)
    body = body_json()
    new_tier = req_enum(body, "new_tier", TIERS)
    expected = body.get("expected_enrollment_version")
    if not isinstance(expected, int) or isinstance(expected, bool):
        raise_err(ERR_INVALID_REQUEST, "expected_enrollment_version is required and must be an integer")
    if rec is None:
        get_or_404(store.enrollments, eid, "TreasuryEnrollment")
    if expected != rec["version"]:
        raise_err(ERR_STALE_VERSION, "expected_enrollment_version is stale")
    guard_enrollment_mutable(rec)
    if open_exception_count(rec["id"]) > 0:
        raise_err(ERR_TIER_CHANGE_NOT_ALLOWED, "Open exceptions block tier migration")
    if new_tier == "REVERSE_POSITIVE_PAY":
        if trailing_90d_issued_volume(rec["id"]) > 75:
            raise_err(
                ERR_TIER_CHANGE_NOT_ALLOWED,
                "Trailing-90-day issued volume exceeds 75 for REVERSE_POSITIVE_PAY",
            )
    rec["tier"] = new_tier
    bump(rec)
    return success_object(enrollment_out(rec), 200)


@bp.route("/treasury/enrollments/<eid>/adoption-report", methods=["GET"])
def get_adoption_report(eid):
    _, role, user = authenticate()
    authorize(role, user, REPORT_ROLES)
    rec = get_or_404(store.enrollments, eid, "TreasuryEnrollment")
    check_ownership(user, rec["id"])
    return success_object(adoption_report(rec), 200)


@bp.route("/treasury/enrollments/<eid>/fee-statement", methods=["GET"])
def get_fee_statement(eid):
    _, role, user = authenticate()
    authorize(role, user, REPORT_ROLES)
    rec = get_or_404(store.enrollments, eid, "TreasuryEnrollment")
    check_ownership(user, rec["id"])
    period = request.args.get("period")
    if not valid_year_month(period):
        raise_err(ERR_INVALID_REQUEST, "period query parameter must be YYYY-MM")
    return success_object(fee_statement(rec["id"], period), 200)
