"""Discipline cases: referral, classify (OCC), sanction (OCC), notice, confirm,
close, expulsion referral (PRD §3.2-§3.4, §3.5, §3.8)."""
from datetime import timedelta

from flask import Blueprint, request

from db import db, stamp, touch, serialize, clock
from errors import (
    raise_err,
    ERR_INVALID_REQUEST,
    ERR_NOT_FOUND,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_STALE_VERSION,
    ERR_INVALID_STATE,
    ERR_MDR_INCOMPLETE,
    ERR_NOTICE_WINDOW_PASSED,
    ERR_CONFERENCE_WINDOW_OPEN,
    ERR_APPEAL_WINDOW_OPEN,
    ERR_REENTRY_OPEN,
    ERR_BAND_NOT_DEFINED,
    ERR_SANCTION_EXCEEDS_CAP,
    ERR_SANCTION_OUT_OF_RANGE,
    ERR_OFFENSE_NOT_EXPELLABLE,
)
from middleware import endpoint
from response import success
from routes.common import get_or_404, guardian_owns, render_list
from services.calc import (
    BAND_CAP_INDEX,
    SUSPENSION_CAP_DAYS,
    compute_occurrence,
    create_mdr,
    current_issued_notice,
    find_band,
    open_mdr_exists,
    recompute_ledger,
)
from util import is_int, parse_dt

bp = Blueprint("cases", __name__)

CASE_STATUSES = {
    "SUBMITTED",
    "CLASSIFIED",
    "SANCTION_PROPOSED",
    "NOTICE_ISSUED",
    "CONFIRMED",
    "EXPULSION_REFERRED",
    "EXPULSION_ACTIVE",
    "CLOSED",
    "EXPUNGED",
}


def _case_of(cid):
    return get_or_404(db.cases, cid, "case")


@bp.post("/cases")
@endpoint("SchoolAdministrator")
def create_case(ctx):
    b = ctx.body
    student_id = b.get("student_id")
    # Body-carried FK existence (rung 5) precedes remaining schema checks (rung 6)
    if isinstance(student_id, str) and student_id not in db.students:
        raise_err(ERR_NOT_FOUND, f"student not found: {student_id}")
    if not isinstance(student_id, str):
        raise_err(ERR_INVALID_REQUEST, "student_id is required")
    incident_date = parse_dt(b.get("incident_date"))
    if incident_date is None:
        raise_err(ERR_INVALID_REQUEST, "incident_date must be a valid ISO 8601 timestamp")
    description = b.get("description")
    if not isinstance(description, str):
        raise_err(ERR_INVALID_REQUEST, "description is required")

    case = stamp(
        {
            "student_id": student_id,
            "incident_date": incident_date,
            "description": description,
            "referrer_id": ctx.user_id,
            "offense_code_id": None,
            "classified_by": None,
            "occurrence_index": None,
            "occurrence_index_ay": None,
            "proposed_sanction_days": None,
            "proposed_sanction_type": None,
            "sanction_override": False,
            "override_justification": None,
            "proposed_at": None,
            "mdr_required": False,
            "sanction_days_final": None,
            "confirmed_at": None,
            "referred_to_expulsion_at": None,
            "closed_at": None,
            "status": "SUBMITTED",
        }
    )
    db.cases[case["id"]] = case
    return success(serialize(case), 201)


@bp.get("/cases/<cid>")
@endpoint(
    "DistrictAdmin",
    "SchoolAdministrator",
    "StudentServicesDirector",
    "HearingOfficer",
    "ParentGuardian",
)
def get_case(ctx, cid):
    case = _case_of(cid)
    if ctx.role == "ParentGuardian":
        guardian_owns(ctx, db.students[case["student_id"]])
    return success(serialize(case))


@bp.get("/cases")
@endpoint("DistrictAdmin", "SchoolAdministrator", "StudentServicesDirector")
def list_cases(ctx):
    student_id = request.args.get("student_id")
    offense_code_id = request.args.get("offense_code_id")
    status = request.args.get("status")
    if status is not None and status not in CASE_STATUSES:
        raise_err(ERR_INVALID_REQUEST, "status filter is not a declared value")
    return render_list(
        db.cases,
        {"student_id": student_id, "offense_code_id": offense_code_id, "status": status},
    )


@bp.post("/cases/<cid>/classify")
@endpoint("SchoolAdministrator")
def classify_case(ctx, cid):
    case = _case_of(cid)
    # Segregation of duties (rung 4) before body-FK existence (rung 5)
    if ctx.user_id == case["referrer_id"]:
        raise_err(ERR_SEGREGATION_OF_DUTIES, "referrer may not classify the case")
    b = ctx.body
    ocid = b.get("offense_code_id")
    if isinstance(ocid, str) and ocid not in db.offense_codes:
        raise_err(ERR_NOT_FOUND, f"offense code not found: {ocid}")
    if not isinstance(ocid, str):
        raise_err(ERR_INVALID_REQUEST, "offense_code_id is required")
    expected = b.get("expected_case_version")
    if not is_int(expected):
        raise_err(ERR_INVALID_REQUEST, "expected_case_version is required")
    # OCC (rung 7) before state guard (rung 8)
    if expected != case["version"]:
        raise_err(ERR_STALE_VERSION, "expected_case_version does not match case version")
    if case["status"] not in ("SUBMITTED", "CLASSIFIED"):
        raise_err(ERR_INVALID_STATE, "case is not classifiable in its current state")

    offense = db.offense_codes[ocid]
    rolling, ay = compute_occurrence(case, offense)
    case["offense_code_id"] = ocid
    case["classified_by"] = ctx.user_id
    case["occurrence_index"] = rolling
    case["occurrence_index_ay"] = ay
    case["status"] = "CLASSIFIED"
    touch(case)
    return success(serialize(case))


@bp.post("/cases/<cid>/sanction")
@endpoint("SchoolAdministrator")
def sanction_case(ctx, cid):
    case = _case_of(cid)
    b = ctx.body
    days = b.get("sanction_days")
    stype = b.get("sanction_type")
    expected = b.get("expected_case_version")
    justification = b.get("override_justification")

    if not is_int(days):
        raise_err(ERR_INVALID_REQUEST, "sanction_days must be an integer")
    if stype not in ("IN_SCHOOL", "OUT_OF_SCHOOL"):
        raise_err(ERR_INVALID_REQUEST, "sanction_type must be IN_SCHOOL or OUT_OF_SCHOOL")
    if not is_int(expected):
        raise_err(ERR_INVALID_REQUEST, "expected_case_version is required")
    if justification is not None and not isinstance(justification, str):
        raise_err(ERR_INVALID_REQUEST, "override_justification must be a string")
    if expected != case["version"]:
        raise_err(ERR_STALE_VERSION, "expected_case_version does not match case version")
    if case["status"] not in ("CLASSIFIED", "SANCTION_PROPOSED"):
        raise_err(ERR_INVALID_STATE, "case is not sanctionable in its current state")

    # sanction_determination (§3.3): band lookup -> absolute cap -> band range
    idx = min(case["occurrence_index"], BAND_CAP_INDEX)
    band = find_band(case["offense_code_id"], idx)
    if band is None:
        raise_err(ERR_BAND_NOT_DEFINED, "no sanction band for the lookup occurrence index")
    if days > SUSPENSION_CAP_DAYS:
        raise_err(ERR_SANCTION_EXCEEDS_CAP, "sanction exceeds the 10-day absolute cap")
    if days < band["min_days"] or days > band["max_days"]:
        if not justification:
            raise_err(ERR_SANCTION_OUT_OF_RANGE, "days outside band range without justification")
        override = True
    else:
        override = False

    student = db.students[case["student_id"]]
    mdr_required = (
        student["disability_status"] in ("IEP", "SECTION_504")
        and student["cumulative_suspension_days"] + days > 10
    )

    case["proposed_sanction_days"] = days
    case["proposed_sanction_type"] = stype
    case["sanction_override"] = override
    case["override_justification"] = justification if override else None
    case["proposed_at"] = clock()
    case["mdr_required"] = mdr_required
    case["status"] = "SANCTION_PROPOSED"
    if mdr_required and not open_mdr_exists(case["id"]):
        create_mdr(case["id"], "AUTO_THRESHOLD")
    touch(case)
    return success(serialize(case))


@bp.post("/cases/<cid>/notices")
@endpoint("SchoolAdministrator")
def issue_notice(ctx, cid):
    case = _case_of(cid)
    delivery = ctx.body.get("delivery_method")
    if delivery not in ("EMAIL", "CERTIFIED_MAIL", "IN_PORTAL"):
        raise_err(ERR_INVALID_REQUEST, "delivery_method must be EMAIL, CERTIFIED_MAIL, or IN_PORTAL")
    if case["status"] != "SANCTION_PROPOSED":
        raise_err(ERR_INVALID_STATE, "case must be SANCTION_PROPOSED to issue a notice")
    # IDEA/504 safety gate (rung 9) before the clock window (rung 10)
    if open_mdr_exists(cid):
        raise_err(ERR_MDR_INCOMPLETE, "an open manifestation determination blocks notice issuance")
    if case["proposed_at"] is None:
        raise_err(ERR_INVALID_STATE, "case has no active sanction proposal")
    if clock() > case["proposed_at"] + timedelta(days=1):
        raise_err(ERR_NOTICE_WINDOW_PASSED, "notice window (1 day from proposal) has passed")

    issued = clock()
    notice = stamp(
        {
            "case_id": cid,
            "delivery_method": delivery,
            "issued_at": issued,
            "appeal_deadline": issued + timedelta(days=5),
            "conference_deadline": issued + timedelta(days=3),
            "status": "ISSUED",
        }
    )
    db.notices[notice["id"]] = notice
    case["status"] = "NOTICE_ISSUED"
    touch(case)
    return success(serialize(notice), 201)


@bp.get("/cases/<cid>/notices")
@endpoint("DistrictAdmin", "SchoolAdministrator", "ParentGuardian")
def list_notices(ctx, cid):
    case = _case_of(cid)
    if ctx.role == "ParentGuardian":
        guardian_owns(ctx, db.students[case["student_id"]])
    notices = {k: v for k, v in db.notices.items() if v["case_id"] == cid}
    return render_list(notices)


@bp.post("/cases/<cid>/confirm")
@endpoint("SchoolAdministrator")
def confirm_case(ctx, cid):
    case = _case_of(cid)
    if case["status"] != "NOTICE_ISSUED":
        raise_err(ERR_INVALID_STATE, "case must be NOTICE_ISSUED to confirm")
    notice = current_issued_notice(cid)
    if notice is None:
        raise_err(ERR_INVALID_STATE, "case has no issued notice")

    # Gates in pinned order: conference first, appeal second (PRD §2.9 rung 10)
    confs = [c for c in db.conferences.values() if c["case_id"] == cid]
    if not (
        any(c["status"] in ("HELD", "WAIVED") for c in confs)
        or clock() > notice["conference_deadline"]
    ):
        raise_err(ERR_CONFERENCE_WINDOW_OPEN, "conference gate not satisfied")

    appeals = [a for a in db.appeals.values() if a["case_id"] == cid]
    if any(a["status"] == "FILED" for a in appeals) or not (
        clock() > notice["appeal_deadline"]
        or any(a["status"] in ("UPHELD", "REVERSED", "REMANDED") for a in appeals)
    ):
        raise_err(ERR_APPEAL_WINDOW_OPEN, "appeal gate not satisfied")

    case["sanction_days_final"] = case["proposed_sanction_days"]
    case["confirmed_at"] = clock()
    case["status"] = "CONFIRMED"
    touch(case)
    student = db.students[case["student_id"]]
    recompute_ledger(student)
    touch(student)
    return success(serialize(case))


@bp.post("/cases/<cid>/close")
@endpoint("SchoolAdministrator")
def close_case(ctx, cid):
    case = _case_of(cid)
    if case["status"] == "CONFIRMED":
        ready = case["confirmed_at"] + timedelta(days=case["sanction_days_final"])
        if clock() < ready:
            raise_err(ERR_INVALID_STATE, "sanction days not yet served")
    elif case["status"] == "EXPULSION_ACTIVE":
        placements = [p for p in db.placements.values() if p["case_id"] == cid]
        if any(p["status"] not in ("COMPLETED", "EXITED_EARLY") for p in placements):
            raise_err(ERR_INVALID_STATE, "case has placements not yet completed")
        for p in placements:
            plans = sorted(
                (r for r in db.reentry_plans.values() if r["placement_id"] == p["id"]),
                key=lambda r: (r["created_at"], r["_seq"]),
            )
            if plans and plans[-1]["status"] != "COMPLETED":
                raise_err(ERR_REENTRY_OPEN, "latest re-entry plan is not COMPLETED")
    else:
        raise_err(ERR_INVALID_STATE, "case is not closable in its current state")

    case["closed_at"] = clock()
    case["status"] = "CLOSED"
    touch(case)
    student = db.students[case["student_id"]]
    if student["last_case_closed_at"] is None or case["closed_at"] > student["last_case_closed_at"]:
        student["last_case_closed_at"] = case["closed_at"]
    touch(student)
    return success(serialize(case))


@bp.post("/cases/<cid>/refer-expulsion")
@endpoint("SchoolAdministrator")
def refer_expulsion(ctx, cid):
    case = _case_of(cid)
    if case["status"] != "CLASSIFIED":
        raise_err(ERR_INVALID_STATE, "case must be CLASSIFIED to refer to expulsion")
    offense = db.offense_codes.get(case["offense_code_id"])
    if offense is None or not offense["expellable"]:
        raise_err(ERR_OFFENSE_NOT_EXPELLABLE, "offense code is not expellable")
    case["referred_to_expulsion_at"] = clock()
    case["status"] = "EXPULSION_REFERRED"
    touch(case)
    return success(serialize(case))
