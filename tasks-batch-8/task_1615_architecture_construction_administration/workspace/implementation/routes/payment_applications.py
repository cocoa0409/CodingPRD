"""PaymentApplication endpoints."""

from flask import Blueprint, request

import db
from errors import (
    ApiError,
    ERR_PAYMENT_APPLICATION_INVALID_STATE,
    ERR_LATER_CERTIFIED_APPLICATION_EXISTS,
    ERR_PAY_APP_PERIOD_NOT_AFTER_PREVIOUS,
    ERR_VERIFICATION_VISIT_INVALID,
    ERR_UNKNOWN_SOV_LINE_CODE,
    ERR_SOV_LINE_OVERRUN,
    ERR_SOD_CERTIFIER_IS_VERIFIER,
    ERR_NONCONFORMANCE_NOT_CLEARED,
    ERR_CERTIFICATION_EXCEEDS_CONTRACT_BALANCE,
)
from middleware import get_user_context, require_role, get_body
from response import success_object, success_list
from services import calcs
from services.helpers import (
    base_entity, touch, paginate, get_project, get_payment_application,
    get_site_visit, req_str, req_date, req_field, invalid,
)
from services.lifecycle import require_project_active, check_counterparty
from routes.field_reports import _field_report_for_visit

bp = Blueprint("payment_applications", __name__)

ALL_ROLES = ("FirmAdmin", "ArchitectCA", "Contractor", "Owner")


def _validate_lines_shape(lines):
    """Body-shape validation for the lines array (stage 3)."""
    if not isinstance(lines, list) or len(lines) == 0:
        invalid("lines must be a non-empty array")
    seen = set()
    for entry in lines:
        if not isinstance(entry, dict):
            invalid("each lines entry must be an object")
        code = entry.get("sov_line_code")
        work = entry.get("work_completed_this_period_cents")
        stored = entry.get("stored_materials_cents")
        if not isinstance(code, str) or not code:
            invalid("each lines entry requires a string sov_line_code")
        if code in seen:
            invalid("sov_line_code values must be unique per application")
        seen.add(code)
        if not (isinstance(work, int) and not isinstance(work, bool)) or work < 0:
            invalid("work_completed_this_period_cents must be an integer >= 0")
        if not (isinstance(stored, int) and not isinstance(stored, bool)) or stored < 0:
            invalid("stored_materials_cents must be an integer >= 0")
    return [
        {
            "sov_line_code": e["sov_line_code"],
            "work_completed_this_period_cents": e["work_completed_this_period_cents"],
            "stored_materials_cents": e["stored_materials_cents"],
        }
        for e in lines
    ]


def _validate_period_ordering(project_id: str, period_ending_date: str, exclude_id: str | None = None):
    """period_ending_date must be strictly greater than every SUBMITTED or
    CERTIFIED application's period_ending_date on the project."""
    for app in db.payment_applications.values():
        if (
            app["project_id"] == project_id
            and app["id"] != exclude_id
            and app["status"] in ("SUBMITTED", "CERTIFIED")
            and period_ending_date <= app["period_ending_date"]
        ):
            raise ApiError(
                ERR_PAY_APP_PERIOD_NOT_AFTER_PREVIOUS,
                "period_ending_date is not strictly after every SUBMITTED/CERTIFIED "
                "application's period_ending_date on the project",
                409,
            )


def _validate_verification_visit(visit, project_id: str, period_ending_date: str):
    """PAYMENT_VERIFICATION visit in REPORT_ISSUED whose visit_date falls inside
    the application's period window."""
    if visit["project_id"] != project_id:
        raise ApiError(
            ERR_VERIFICATION_VISIT_INVALID,
            "verification visit belongs to a different project",
            422,
        )
    if visit["purpose"] != "PAYMENT_VERIFICATION" or visit["status"] != "REPORT_ISSUED":
        raise ApiError(
            ERR_VERIFICATION_VISIT_INVALID,
            "verification_visit_id is not a PAYMENT_VERIFICATION visit in REPORT_ISSUED",
            422,
        )
    # Period window: strictly after the previous CERTIFIED application's
    # period_ending_date (no lower bound for the first), at or before this
    # application's period_ending_date.
    prev = calcs.find_previous_application(project_id, period_ending_date)
    lower = prev["period_ending_date"] if prev else None
    vd = visit["visit_date"]
    if lower is not None and vd <= lower:
        raise ApiError(
            ERR_VERIFICATION_VISIT_INVALID,
            "verification visit_date is not after the previous certified period_ending_date",
            422,
        )
    if vd > period_ending_date:
        raise ApiError(
            ERR_VERIFICATION_VISIT_INVALID,
            "verification visit_date is after the application's period_ending_date",
            422,
        )


def _validate_sov_lines(project: dict, lines: list):
    codes = {entry["line_code"]: entry["scheduled_value_cents"] for entry in project["sov_lines"]}
    for line in lines:
        if line["sov_line_code"] not in codes:
            raise ApiError(
                ERR_UNKNOWN_SOV_LINE_CODE,
                "A line's sov_line_code does not exist in the project's schedule of values",
                422,
            )
    # Per-line cap: prior certified work on the same SOV line plus this line's
    # work must be <= the line's scheduled value.
    prior_by_code = {}
    for app in db.payment_applications.values():
        if app["project_id"] == project["id"] and app["status"] == "CERTIFIED":
            for line2 in app["lines"]:
                prior_by_code[line2["sov_line_code"]] = (
                    prior_by_code.get(line2["sov_line_code"], 0) + line2["work_completed_this_period_cents"]
                )
    for line in lines:
        cap = codes[line["sov_line_code"]]
        if prior_by_code.get(line["sov_line_code"], 0) + line["work_completed_this_period_cents"] > cap:
            raise ApiError(
                ERR_SOV_LINE_OVERRUN,
                "A line's cumulative work would exceed its scheduled value",
                422,
            )


def _provisional_compute(project: dict, app: dict):
    result = calcs.payment_certification_compute(project, app)
    app["previous_application_id"] = result["previous_application_id"]
    app["gross_work_completed_cents"] = result["gross_work_completed_cents"]
    app["earned_work_this_period_cents"] = result["earned_work_this_period_cents"]
    app["retainage_work_cents"] = result["retainage_work_cents"]
    app["retainage_stored_cents"] = result["retainage_stored_cents"]
    app["provisional_current_due_cents"] = result["current_due_cents"]


@bp.post("/ca/payment-applications")
def create_payment_application():
    user_id, role = get_user_context()
    require_role(role, ("Contractor",))
    body = get_body(required=True)
    project_id = req_str(body, "project_id")
    period_ending_date = req_date(body, "period_ending_date")
    verification_visit_id = req_str(body, "verification_visit_id")
    lines = _validate_lines_shape(req_field(body, "lines"))

    project = get_project(project_id)
    visit = get_site_visit(verification_visit_id)
    check_counterparty(role, user_id, project)
    require_project_active(project)

    # Domain checks in order: period ordering, verification-visit validity,
    # SOV line membership, per-line schedule cap.
    _validate_period_ordering(project_id, period_ending_date)
    _validate_verification_visit(visit, project_id, period_ending_date)
    _validate_sov_lines(project, lines)

    app = base_entity()
    app.update({
        "project_id": project_id,
        "period_ending_date": period_ending_date,
        "verification_visit_id": verification_visit_id,
        "previous_application_id": None,
        "revision_number": 1,
        "lines": lines,
        "gross_work_completed_cents": 0,
        "earned_work_this_period_cents": 0,
        "retainage_work_cents": 0,
        "retainage_stored_cents": 0,
        "provisional_current_due_cents": 0,
        "certified_current_due_cents": None,
        "rejection_reason": None,
        "certified_at": None,
        "certified_by_user_id": None,
        "status": "SUBMITTED",
    })
    db.payment_applications[app["id"]] = app
    _provisional_compute(project, app)
    return success_object(app, 201)


@bp.get("/ca/payment-applications")
def list_payment_applications():
    _, role = get_user_context()
    require_role(role, ALL_ROLES)
    items = list(db.payment_applications.values())
    project_id = request.args.get("project_id")
    if project_id is not None:
        items = [a for a in items if a["project_id"] == project_id]
    status = request.args.get("status")
    if status is not None:
        items = [a for a in items if a["status"] == status]
    vv = request.args.get("verification_visit_id")
    if vv is not None:
        items = [a for a in items if a["verification_visit_id"] == vv]
    prev = request.args.get("previous_application_id")
    if prev is not None:
        items = [a for a in items if a["previous_application_id"] == prev]
    page, limit, offset, total = paginate(items)
    return success_list(page, limit, offset, total)


@bp.get("/ca/payment-applications/<aid>")
def get_one_payment_application(aid):
    _, role = get_user_context()
    require_role(role, ALL_ROLES)
    return success_object(get_payment_application(aid))


@bp.post("/ca/payment-applications/<aid>/certify")
def certify_payment_application(aid):
    user_id, role = get_user_context()
    require_role(role, ("ArchitectCA",))
    app = get_payment_application(aid)

    # Stage 8: state gate precedes the segregation gate (stage 9).
    if app["status"] != "SUBMITTED":
        raise ApiError(
            ERR_PAYMENT_APPLICATION_INVALID_STATE,
            "pay-app certify requires SUBMITTED",
            409,
        )

    visit = db.site_visits[app["verification_visit_id"]]
    if user_id == visit["performed_by_user_id"]:
        raise ApiError(
            ERR_SOD_CERTIFIER_IS_VERIFIER,
            "Pay-app certifier X-User-ID equals the verification visit's performed_by_user_id",
            422,
        )

    report = _field_report_for_visit(visit["id"])
    if report is not None and report["nonconforming_work_flag"] and report["nonconformance_status"] != "CLEARED":
        raise ApiError(
            ERR_NONCONFORMANCE_NOT_CLEARED,
            "Certification blocked: verification visit's field report flags nonconforming "
            "work that is not CLEARED",
            409,
        )

    project = db.projects[app["project_id"]]
    # Final variant: identical formula re-run at certify time.
    result = calcs.payment_certification_compute(project, app)

    # Fiscal gate (stage 13).
    if result["gross_work_completed_cents"] > project["adjusted_contract_sum_cents"]:
        raise ApiError(
            ERR_CERTIFICATION_EXCEEDS_CONTRACT_BALANCE,
            "Recomputed gross work would exceed adjusted_contract_sum_cents at certification",
            402,
        )

    app["previous_application_id"] = result["previous_application_id"]
    app["gross_work_completed_cents"] = result["gross_work_completed_cents"]
    app["earned_work_this_period_cents"] = result["earned_work_this_period_cents"]
    app["retainage_work_cents"] = result["retainage_work_cents"]
    app["retainage_stored_cents"] = result["retainage_stored_cents"]
    app["certified_current_due_cents"] = result["current_due_cents"]
    app["certified_at"] = db.now_iso()
    app["certified_by_user_id"] = user_id
    app["status"] = "CERTIFIED"
    touch(app)

    calcs.recompute_contract_position(project)
    touch(project)
    return success_object(app)


@bp.post("/ca/payment-applications/<aid>/reject")
def reject_payment_application(aid):
    _, role = get_user_context()
    require_role(role, ("ArchitectCA",))
    body = get_body(required=True)
    reason = req_str(body, "reason")
    app = get_payment_application(aid)
    if app["status"] != "SUBMITTED":
        raise ApiError(
            ERR_PAYMENT_APPLICATION_INVALID_STATE,
            "pay-app reject requires SUBMITTED",
            409,
        )
    app["rejection_reason"] = reason
    app["status"] = "REJECTED"
    touch(app)
    return success_object(app)


@bp.post("/ca/payment-applications/<aid>/resubmit")
def resubmit_payment_application(aid):
    user_id, role = get_user_context()
    require_role(role, ("Contractor",))
    body = get_body(required=True)
    period_ending_date = req_date(body, "period_ending_date")
    verification_visit_id = req_str(body, "verification_visit_id")
    lines = _validate_lines_shape(req_field(body, "lines"))

    app = get_payment_application(aid)
    project = db.projects[app["project_id"]]
    visit = get_site_visit(verification_visit_id)
    check_counterparty(role, user_id, project)

    if app["status"] != "REJECTED":
        raise ApiError(
            ERR_PAYMENT_APPLICATION_INVALID_STATE,
            "pay-app resubmit requires REJECTED",
            409,
        )

    # Replacement values re-validated exactly as on creation.
    _validate_period_ordering(project["id"], period_ending_date, exclude_id=app["id"])
    _validate_verification_visit(visit, project["id"], period_ending_date)
    _validate_sov_lines(project, lines)

    app["period_ending_date"] = period_ending_date
    app["verification_visit_id"] = verification_visit_id
    app["lines"] = lines
    app["revision_number"] += 1
    app["rejection_reason"] = None
    app["status"] = "SUBMITTED"
    _provisional_compute(project, app)
    touch(app)
    return success_object(app)


@bp.post("/ca/payment-applications/<aid>/void")
def void_payment_application(aid):
    _, role = get_user_context()
    require_role(role, ("FirmAdmin",))
    app = get_payment_application(aid)
    if app["status"] != "CERTIFIED":
        raise ApiError(
            ERR_PAYMENT_APPLICATION_INVALID_STATE,
            "pay-app void requires CERTIFIED",
            409,
        )
    # The certified chain is only unwrapped from the tip.
    later_exists = any(
        other["project_id"] == app["project_id"]
        and other["id"] != app["id"]
        and other["status"] == "CERTIFIED"
        and other["period_ending_date"] > app["period_ending_date"]
        for other in db.payment_applications.values()
    )
    if later_exists:
        raise ApiError(
            ERR_LATER_CERTIFIED_APPLICATION_EXISTS,
            "Void blocked because a CERTIFIED application with a later period_ending_date exists",
            409,
        )
    app["status"] = "VOIDED"
    touch(app)

    project = db.projects[app["project_id"]]
    calcs.recompute_contract_position(project)
    touch(project)
    return success_object(app)
