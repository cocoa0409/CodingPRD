"""Community complaints, inspection assignment / completion and program evaluation."""
from datetime import date
from decimal import Decimal

from flask import Blueprint

import constants as C
import serialize
from db import db, new_row, ordered, touch
from errors import ApiError, bad_request
from middleware import authenticate
from response import list_response, object_response, paginate
from services import calc, cascade, repo
from validators import (body_json, f_date, f_enum, f_lang, f_str, q_date,
                        q_enum, q_pagination, q_str)

bp = Blueprint("complaints", __name__)

DEFAULT_PERIOD_START = date(1970, 1, 1)
DEFAULT_PERIOD_END = date(9999, 12, 31)


# ---------------------------------------------------------------------- complaints
@bp.post("/ej/community-complaints")
def create_complaint():
    authenticate((C.ROLE_PUBLIC_COMMENTER, C.ROLE_COMMUNITY_LIAISON))
    body = body_json()
    screening_area_id = f_str(body, "screening_area_id")
    facility_id = f_str(body, "facility_id", required=False)
    complaint_type = f_enum(body, "complaint_type", C.COMPLAINT_TYPES)
    severity = f_enum(body, "severity", C.SEVERITIES)
    description = f_str(body, "description", min_len=1, max_len=2000)
    submitter_language = f_lang(body, "submitter_language", required=False,
                                default="en")

    area = repo.get_area(screening_area_id)
    if facility_id is not None:
        repo.get_facility(facility_id)

    row = new_row()
    row.update(
        {
            "screening_area_id": area["id"],
            "facility_id": facility_id,
            "complaint_type": complaint_type,
            "severity": severity,
            "description": description,
            "submitter_language": submitter_language,
            "repeat_count_180d": 0,
            "priority_score": C.D("0.00"),
            "priority_tier": "TIER_3",
            "reopen_count": 0,
            "status": "RECEIVED",
        }
    )
    db.community_complaints[row["id"]] = row

    cascade.rescore_complaint(row, area)
    area["open_complaint_count"] = area["open_complaint_count"] + 1
    touch(area)
    return object_response(serialize.community_complaint(row), 201)


@bp.get("/ej/community-complaints/<complaint_id>")
def read_complaint(complaint_id):
    authenticate(C.READ_NO_APPLICANT)
    complaint = repo.get_complaint(complaint_id)
    return object_response(serialize.community_complaint(complaint))


@bp.get("/ej/community-complaints")
def list_complaints():
    authenticate(C.READ_NO_APPLICANT)
    limit, offset = q_pagination()
    screening_area_id = q_str("screening_area_id")
    facility_id = q_str("facility_id")
    status = q_enum("status", C.COMPLAINT_STATUSES)
    priority_tier = q_enum("priority_tier", C.PRIORITY_TIERS)

    rows = ordered(list(db.community_complaints.values()))
    if screening_area_id is not None:
        rows = [r for r in rows if r["screening_area_id"] == screening_area_id]
    if facility_id is not None:
        rows = [r for r in rows if r["facility_id"] == facility_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if priority_tier is not None:
        rows = [r for r in rows if r["priority_tier"] == priority_tier]
    page, total = paginate(rows, limit, offset)
    return list_response(serialize.many(serialize.community_complaint, page),
                         limit, offset, total)


@bp.post("/ej/community-complaints/<complaint_id>/triage")
def triage_complaint(complaint_id):
    authenticate((C.ROLE_EJ_ANALYST,))
    body = body_json()
    outcome = f_enum(body, "outcome", C.TRIAGE_OUTCOMES)
    dismissal_reason = f_str(body, "dismissal_reason", required=False)
    if outcome == "DISMISS" and dismissal_reason is None:
        raise bad_request("Field 'dismissal_reason' is required when outcome is DISMISS.")

    complaint = repo.get_complaint(complaint_id)
    if complaint["status"] != "RECEIVED":
        raise ApiError("ERR_INVALID_COMPLAINT_STATE")
    area = db.screening_areas[complaint["screening_area_id"]]

    if outcome == "ACCEPT":
        complaint["status"] = "TRIAGED"
        cascade.rescore_complaint(complaint, area)
        touch(complaint)
    else:
        complaint["status"] = "DISMISSED"
        touch(complaint)
        area["open_complaint_count"] = area["open_complaint_count"] - 1
        touch(area)
    return object_response(serialize.community_complaint(complaint))


@bp.post("/ej/community-complaints/<complaint_id>/reopen")
def reopen_complaint(complaint_id):
    authenticate((C.ROLE_COMMUNITY_LIAISON,))
    body = body_json()
    f_str(body, "reason", min_len=1)

    complaint = repo.get_complaint(complaint_id)
    if complaint["status"] != "RESOLVED":
        raise ApiError("ERR_INVALID_COMPLAINT_STATE")
    area = db.screening_areas[complaint["screening_area_id"]]

    complaint["status"] = "TRIAGED"
    complaint["reopen_count"] = complaint["reopen_count"] + 1
    cascade.rescore_complaint(complaint, area)
    touch(complaint)
    area["open_complaint_count"] = area["open_complaint_count"] + 1
    touch(area)
    return object_response(serialize.community_complaint(complaint))


@bp.post("/ej/community-complaints/<complaint_id>/resolve")
def resolve_complaint(complaint_id):
    authenticate((C.ROLE_EJ_ANALYST,))
    body = body_json()
    resolution = f_enum(body, "resolution", C.RESOLUTIONS)
    f_str(body, "note", required=False)

    complaint = repo.get_complaint(complaint_id)
    if complaint["status"] != "INSPECTED":
        raise ApiError("ERR_INVALID_COMPLAINT_STATE")

    if resolution == "REFERRED_ENFORCEMENT":
        completed = [r for r in repo.inspections_of_complaint(complaint["id"])
                     if r["status"] == "COMPLETED"]
        latest = completed[-1] if completed else None
        if latest is None or latest["finding"] != "VIOLATION_CONFIRMED":
            raise ApiError("ERR_REFERRAL_UNSUPPORTED")

    complaint["status"] = resolution
    touch(complaint)
    area = db.screening_areas[complaint["screening_area_id"]]
    area["open_complaint_count"] = area["open_complaint_count"] - 1
    touch(area)
    return object_response(serialize.community_complaint(complaint))


# --------------------------------------------------------------------- inspections
def _inspectable(complaint):
    if complaint["status"] != "TRIAGED":
        return False
    if complaint["facility_id"] is None:
        return False
    for inspection in repo.inspections_of_complaint(complaint["id"]):
        if inspection["status"] == "SCHEDULED":
            return False
    return True


@bp.post("/ej/inspections/assign-next")
def assign_next_inspection():
    authenticate((C.ROLE_EJ_ANALYST,))
    body = body_json()
    inspector_user_id = f_str(body, "inspector_user_id", min_len=1)
    scheduled_date = f_date(body, "scheduled_date")
    screening_area_id = f_str(body, "screening_area_id", required=False)

    area = None
    if screening_area_id is not None:
        area = repo.get_area(screening_area_id)

    if area is not None:
        narrowed = repo.complaints_in_area(area["id"])
        if len(narrowed) == 1 and not _inspectable(narrowed[0]):
            raise ApiError("ERR_COMPLAINT_NOT_INSPECTABLE")

    same_day = 0
    for inspection in db.inspections.values():
        if (inspection["inspector_user_id"] == inspector_user_id
                and inspection["status"] == "SCHEDULED"
                and inspection["scheduled_date"] == scheduled_date):
            same_day += 1
    if same_day >= C.MAX_INSPECTIONS_PER_INSPECTOR_PER_DAY:
        raise ApiError("ERR_INSPECTOR_DAY_CAPACITY_EXCEEDED")

    pool = (repo.complaints_in_area(area["id"]) if area is not None
            else ordered(list(db.community_complaints.values())))
    candidates = [c for c in pool if _inspectable(c)]
    if not candidates:
        raise ApiError("ERR_NO_ELIGIBLE_COMPLAINT")

    candidates.sort(key=lambda r: (-r["priority_score"], r["created_at"],
                                   r["version"], r["_seq"]))
    winner = candidates[0]

    row = new_row()
    row.update(
        {
            "community_complaint_id": winner["id"],
            "facility_id": winner["facility_id"],
            "inspector_user_id": inspector_user_id,
            "scheduled_date": scheduled_date,
            "priority_score_at_assignment": winner["priority_score"],
            "finding": None,
            "status": "SCHEDULED",
        }
    )
    db.inspections[row["id"]] = row

    winner["status"] = "INSPECTION_ASSIGNED"
    touch(winner)
    return object_response(serialize.inspection(row), 201)


@bp.post("/ej/inspections/<inspection_id>/complete")
def complete_inspection(inspection_id):
    user_id, _ = authenticate((C.ROLE_INSPECTOR,))
    body = body_json()
    finding = f_enum(body, "finding", C.FINDINGS)
    f_str(body, "notes", required=False)

    inspection = repo.get_inspection(inspection_id)
    if inspection["inspector_user_id"] != user_id:
        raise ApiError("ERR_NOT_ASSIGNED_INSPECTOR")
    if inspection["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_INSPECTION_STATE")

    inspection["status"] = "COMPLETED"
    inspection["finding"] = finding
    touch(inspection)

    complaint = db.community_complaints[inspection["community_complaint_id"]]
    complaint["status"] = "INSPECTED"
    touch(complaint)

    if finding == "VIOLATION_CONFIRMED":
        facility = db.facilities[inspection["facility_id"]]
        facility["compliance_status"] = "VIOLATION_ON_RECORD"
        facility["confirmed_violation_count"] = facility["confirmed_violation_count"] + 1
        touch(facility)

        area = repo.area_of_facility(facility)
        area["enforcement_burden_points"] = (
            area["enforcement_burden_points"] + C.ENFORCEMENT_POINTS_PER_VIOLATION
        )
        area["data_status"] = "STALE"
        cascade.rescore_area(area)
        cascade.stale_data_cascade(area)

    return object_response(serialize.inspection(inspection))


@bp.get("/ej/community-complaints/<complaint_id>/inspections")
def list_complaint_inspections(complaint_id):
    authenticate(C.READ_NO_APPLICANT)
    limit, offset = q_pagination()
    complaint = repo.get_complaint(complaint_id)
    rows = repo.inspections_of_complaint(complaint["id"])
    page, total = paginate(rows, limit, offset)
    return list_response(serialize.many(serialize.inspection, page),
                         limit, offset, total)


@bp.get("/ej/facilities/<facility_id>/inspections")
def list_facility_inspections(facility_id):
    authenticate(C.READ_NO_APPLICANT)
    limit, offset = q_pagination()
    status = q_enum("status", C.INSPECTION_STATUSES)
    facility = repo.get_facility(facility_id)
    rows = repo.inspections_of_facility(facility["id"])
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, total = paginate(rows, limit, offset)
    return list_response(serialize.many(serialize.inspection, page),
                         limit, offset, total)


# --------------------------------------------------------------- program evaluation
def _created_date(row):
    return date.fromisoformat(row["created_at"][:10])


@bp.get("/ej/program-evaluation")
def program_evaluation():
    authenticate((C.ROLE_PROGRAM_ADMIN, C.ROLE_EJ_ANALYST))
    basis = q_enum("basis", C.EVALUATION_BASES) or "DECISION_DATE"
    period_start = q_date("period_start") or DEFAULT_PERIOD_START
    period_end = q_date("period_end") or DEFAULT_PERIOD_END
    designation = q_enum("designation", C.DESIGNATIONS)
    wanted = ((designation,) if designation is not None
              else ("OVERBURDENED", "SEVERELY_OVERBURDENED"))

    selected = []
    for application in ordered(list(db.permit_applications.values())):
        if application["status"] not in ("ISSUED", "DENIED"):
            continue
        area = repo.area_of_application(application)
        if area["designation"] not in wanted:
            continue
        governing = None
        for decision in repo.decisions_of(application["id"]):
            if decision["status"] in ("ISSUED", "DENIED"):
                governing = decision
                break
        if governing is None:
            continue
        anchor = (_created_date(governing) if basis == "DECISION_DATE"
                  else _created_date(application))
        if anchor < period_start or anchor > period_end:
            continue
        selected.append((application, governing))

    total_decided = len(selected)
    issued_count = sum(1 for a, _ in selected if a["status"] == "ISSUED")
    denied_count = sum(1 for a, _ in selected if a["status"] == "DENIED")

    if total_decided:
        denial_rate = calc.rnd(Decimal(denied_count) / Decimal(total_decided), 4)
        mean_residual = calc.rnd(
            sum((a["residual_impact_index"] for a, _ in selected), Decimal(0))
            / Decimal(total_decided),
            2,
        )
    else:
        denial_rate = Decimal("0.0000")
        mean_residual = Decimal("0.00")

    total_credit = calc.rnd(
        sum((a["total_mitigation_credit_tpy"] for a, _ in selected), Decimal(0)), 2
    )
    total_benefit = calc.rnd(
        sum(
            (d["community_benefit_total_usd"] for _, d in selected
             if d["status"] == "ISSUED"),
            Decimal(0),
        ),
        2,
    )

    enhanced = [a for a, _ in selected if a["review_track"] == "ENHANCED"]
    if enhanced:
        running = Decimal(0)
        for application in enhanced:
            plan = repo.live_plan_of(application["id"])
            if plan is not None:
                running += Decimal(
                    plan["required_comment_days"] + plan["granted_extension_days"]
                )
        mean_comment_days = calc.rnd(running / Decimal(len(enhanced)), 2)
    else:
        mean_comment_days = Decimal("0.00")

    return object_response(
        {
            "basis": basis,
            "total_decided": total_decided,
            "issued_count": issued_count,
            "denied_count": denied_count,
            "denial_rate": serialize.num(denial_rate),
            "mean_residual_index": serialize.num(mean_residual),
            "total_mitigation_credit_tpy": serialize.num(total_credit),
            "total_community_benefit_usd": serialize.num(total_benefit),
            "mean_comment_days": serialize.num(mean_comment_days),
        }
    )
