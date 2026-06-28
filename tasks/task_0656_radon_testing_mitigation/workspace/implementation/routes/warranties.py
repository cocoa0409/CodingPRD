"""Warranty endpoints: get, list, refresh, cancel (OCC), open-claim
(PRD §3.6). coverage_status and claim_status are parallel dimensions."""

from flask import Blueprint, request

from db import store
import errors
from errors import ApiError
from middleware import get_user_context, require_role, get_json_body, parse_pagination
from response import object_response, array_response
from services import validate
from services import calc
from services.domain import public, touch, now_clock, append_payment, recompute_job_payments
from services.listing import paginate

bp = Blueprint("warranties", __name__)

GET_ROLES = {"PlatformAdmin", "ComplianceOfficer", "ClientContact", "MitigationDesigner"}


def _elapsed_days(warranty):
    """Whole days from started_at_utc to the current logical clock (floor)."""
    delta = now_clock() - warranty["_started_dt"]
    return int(delta.total_seconds() // 86400)


def _end_retest_schedules(warranty):
    """Cascade: set parent RetestSchedule(s) to ENDED when coverage leaves ACTIVE."""
    for s in store.retest_schedules.values():
        if s["warranty_id"] == warranty["id"] and s["status"] != "ENDED":
            s["status"] = "ENDED"
            touch(s)


@bp.route("/warranties/<warranty_id>", methods=["GET"])
def get_warranty(warranty_id):
    _, role = get_user_context()
    require_role(role, GET_ROLES)
    w = store.warranties.get(warranty_id)
    if w is None:
        raise ApiError(errors.ERR_NOT_FOUND, 404, "Warranty not found.")
    return object_response(public(w), 200)


@bp.route("/warranties", methods=["GET"])
def list_warranties():
    _, role = get_user_context()
    require_role(role, GET_ROLES)
    limit, offset = parse_pagination()
    filters = {
        "mitigation_job_id": request.args.get("mitigation_job_id"),
        "property_id": request.args.get("property_id"),
        "coverage_status": request.args.get("coverage_status"),
    }
    items, total = paginate(store.warranties, filters, limit, offset)
    return array_response(items, limit, offset, total, 200)


@bp.route("/warranties/<warranty_id>/refresh", methods=["POST"])
def refresh_warranty(warranty_id):
    _, role = get_user_context()
    require_role(role, {"ComplianceOfficer", "PlatformAdmin"})
    w = store.warranties.get(warranty_id)
    if w is None:
        raise ApiError(errors.ERR_NOT_FOUND, 404, "Warranty not found.")

    # state (priority 5): refresh re-evaluates ACTIVE coverage.
    if w["coverage_status"] != "ACTIVE":
        raise ApiError(errors.ERR_INVALID_STATE, 409, "Warranty coverage is not ACTIVE.")

    # ACTIVE -> EXPIRED when clock >= started_at_utc + term_days days.
    from services.domain import add_days

    expiry = add_days(w["_started_dt"], w["term_days"])
    if now_clock() >= expiry:
        w["coverage_status"] = "EXPIRED"
        touch(w)
        _end_retest_schedules(w)
    # If not yet past term, refresh is a no-op transition that still returns 200.
    return object_response(public(w), 200)


@bp.route("/warranties/<warranty_id>/cancel", methods=["POST"])
def cancel_warranty(warranty_id):
    _, role = get_user_context()
    require_role(role, {"ClientContact", "PlatformAdmin"})
    w = store.warranties.get(warranty_id)
    if w is None:
        raise ApiError(errors.ERR_NOT_FOUND, 404, "Warranty not found.")
    body = get_json_body()
    expected_version = validate.require_int(body, "expected_warranty_version")

    # state (priority 5): coverage must be ACTIVE to cancel.
    if w["coverage_status"] != "ACTIVE":
        raise ApiError(errors.ERR_INVALID_STATE, 409, "Warranty coverage is not ACTIVE.")

    # OCC on the warranty itself (priority 6).
    if expected_version != w["version"]:
        raise ApiError(
            errors.ERR_STALE_WARRANTY_VERSION,
            412,
            "expected_warranty_version does not match the live warranty version.",
        )

    # cannot cancel mid-claim (priority 18).
    if w["claim_status"] == "CLAIM_OPEN":
        raise ApiError(errors.ERR_CLAIM_IN_PROGRESS, 409, "Cannot cancel a warranty mid-claim.")

    # compute prorated refund.
    elapsed = _elapsed_days(w)
    refund = calc.warranty_refund(
        w["refund_method"], w["covered_system_price_cents"], w["term_days"], elapsed
    )
    w["refund_paid_cents"] = refund
    w["coverage_status"] = "CANCELLED"
    touch(w)

    # append REFUND PaymentRecord of -refund on the mitigation job.
    job = store.mitigation_jobs.get(w["mitigation_job_id"])
    if job is not None:
        append_payment(job, "REFUND", -refund)
        recompute_job_payments(job)

    # cascade RetestSchedule -> ENDED.
    _end_retest_schedules(w)

    return object_response(public(w), 200)


@bp.route("/warranties/<warranty_id>/open-claim", methods=["POST"])
def open_claim(warranty_id):
    _, role = get_user_context()
    require_role(role, {"ClientContact"})
    w = store.warranties.get(warranty_id)
    if w is None:
        raise ApiError(errors.ERR_NOT_FOUND, 404, "Warranty not found.")

    # state (priority 5): coverage ACTIVE and claim NONE.
    if w["coverage_status"] != "ACTIVE" or w["claim_status"] != "NONE":
        raise ApiError(
            errors.ERR_INVALID_STATE,
            409,
            "Open-claim requires ACTIVE coverage and a NONE claim status.",
        )

    # qualifying high retest: property latest_result >= guarantee_ceiling (priority 19).
    prop = store.properties.get(w["property_id"])
    latest = prop.get("latest_result_pci_l") if prop else None
    if latest is None or latest < w["guarantee_ceiling_pci_l"]:
        raise ApiError(
            errors.ERR_NO_QUALIFYING_RETEST,
            409,
            "No qualifying high retest at or above the guarantee ceiling.",
        )

    w["claim_status"] = "CLAIM_OPEN"
    touch(w)

    # parent MitigationJob -> REWORK (guarantee triggers free re-mitigation).
    job = store.mitigation_jobs.get(w["mitigation_job_id"])
    if job is not None:
        job["status"] = "REWORK"
        touch(job)
        if prop is not None:
            from services.domain import recompute_property_derived

            recompute_property_derived(prop)

    return object_response(public(w), 200)
