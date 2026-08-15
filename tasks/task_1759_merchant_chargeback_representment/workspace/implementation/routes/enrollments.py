"""ProgramEnrollment endpoints (PRD 3.9) — manual enrollment, exit review,
remediation-plan reverse lookup."""

from flask import Blueprint, g, request

from db import db
from errors import ApiError
from middleware import is_merchant_user
from records import new_program_enrollment, touch
from response import ok_object
from routes.common import ALL_ROLES, authenticate, get_or_404, hide_if_cross_merchant, json_body, list_response
from serializers import serialize_program_enrollment, serialize_remediation_plan
from services.sweeps import THRESHOLD_BPS, create_education_cascade, enrollment_month_ranges_overlap
from util import Body, ENROLLMENT_STATUSES, NETWORKS, PROGRAM_CODES, filter_enum

bp = Blueprint("enrollments", __name__)


@bp.post("/acquirer/program-enrollments")
def create_enrollment():
    authenticate(("RiskOfficer",))
    b = Body(json_body())
    merchant_id = b.req_str("merchant_id")
    network = b.req_enum("network", NETWORKS)
    program_code = b.req_enum("program_code", PROGRAM_CODES)
    enrolled_month = b.req_month("enrolled_month")

    merchant = None
    if merchant_id is not None:
        merchant = get_or_404(db.merchants, merchant_id, "Merchant")

    # Priority 7: CLOSED month ranges per (merchant, network, program_code) must not
    # overlap — re-enrollment in the prior exit month itself conflicts.
    if merchant is not None and network is not None and program_code is not None and enrolled_month is not None:
        for en in db.program_enrollments.values():
            if (en["merchant_id"] == merchant["id"] and en["network"] == network
                    and en["program_code"] == program_code):
                if enrollment_month_ranges_overlap(enrolled_month, None, en["enrolled_month"], en["exited_month"]):
                    raise ApiError(409, "ERR_ENROLLMENT_WINDOW_OVERLAP",
                                   "Enrollment month range overlaps an existing enrollment")
    b.raise_pending()

    en = new_program_enrollment(merchant["id"], network, program_code, enrolled_month)
    db.program_enrollments[en["id"]] = en
    create_education_cascade(en)
    return ok_object(serialize_program_enrollment(en), status=201)


@bp.get("/acquirer/program-enrollments")
def list_enrollments():
    authenticate(ALL_ROLES)
    merchant_id = request.args.get("merchant_id")
    status = filter_enum(request.args, "status", ENROLLMENT_STATUSES)
    records = list(db.program_enrollments.values())
    if is_merchant_user():
        records = [e for e in records if e["merchant_id"] == g.uid]
    elif merchant_id is not None:
        records = [e for e in records if e["merchant_id"] == merchant_id]
    if status is not None:
        records = [e for e in records if e["status"] == status]
    return list_response(records, serialize_program_enrollment)


@bp.get("/acquirer/program-enrollments/<eid>")
def get_enrollment(eid):
    authenticate(ALL_ROLES)
    en = get_or_404(db.program_enrollments, eid, "ProgramEnrollment")
    hide_if_cross_merchant(en["merchant_id"])
    return ok_object(serialize_program_enrollment(en))


@bp.post("/acquirer/program-enrollments/<eid>/exit-review")
def exit_review(eid):
    authenticate(("RiskOfficer",))
    en = get_or_404(db.program_enrollments, eid, "ProgramEnrollment")
    # Priority 5: only ACTIVE / REMEDIATION enrollments may be exit-reviewed.
    if en["status"] == "EXITED":
        raise ApiError(409, "ERR_INVALID_ENROLLMENT_STATE", "Enrollment is already EXITED")
    # Exit criteria (both must hold): an APPROVED plan, and the 3 most recent POSTED
    # snapshots for (merchant, network) all strictly below the program threshold.
    approved = any(p for p in db.remediation_plans.values()
                   if p["enrollment_id"] == en["id"] and p["status"] == "APPROVED")
    snaps = [s for s in db.ratio_snapshots.values()
             if s["merchant_id"] == en["merchant_id"] and s["network"] == en["network"]]
    snaps.sort(key=lambda s: (s["period_month"], s["computed_at"], s["created_at"]))
    recent = snaps[-3:]
    threshold = THRESHOLD_BPS[en["program_code"]]
    if not approved or len(snaps) < 3 or any(s["count_ratio_bps"] >= threshold for s in recent):
        raise ApiError(409, "ERR_EXIT_CRITERIA_NOT_MET", "Exit criteria are not met")

    b = Body(json_body())
    exited_month = b.req_month("exited_month")
    b.raise_pending()

    en["status"] = "EXITED"
    en["exited_month"] = exited_month
    touch(en)
    return ok_object(serialize_program_enrollment(en))


@bp.get("/acquirer/program-enrollments/<eid>/remediation-plans")
def list_enrollment_plans(eid):
    authenticate(ALL_ROLES)
    en = get_or_404(db.program_enrollments, eid, "ProgramEnrollment")
    hide_if_cross_merchant(en["merchant_id"])
    records = [p for p in db.remediation_plans.values() if p["enrollment_id"] == en["id"]]
    return list_response(records, serialize_remediation_plan)
