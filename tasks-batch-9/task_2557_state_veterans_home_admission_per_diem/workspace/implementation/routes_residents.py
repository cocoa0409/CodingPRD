"""Residents, care plans, level-of-care transfers, bed holds and discharge."""
from datetime import timedelta

from flask import Blueprint

import calc
import services
from calc import CARE_LEVELS, CARE_PLAN_REVIEW_DAYS, BED_HOLD_MAX_DAYS, care_plan_out, resident_out
from common import (
    f_date,
    f_enum,
    f_id,
    f_str,
    fail,
    guard,
    json_body,
    object_response,
    pagination,
    paginate,
    q_str,
)
from store import (
    clock_date,
    format_date,
    new_record,
    now_iso,
    order_key,
    parse_date,
    store,
    touch_once,
)

bp = Blueprint("residents", __name__)

ADL_SUPPORT_LEVELS = ("LOW", "MODERATE", "HIGH")
DISCHARGE_REASONS = ("DEATH", "TRANSFER_OUT", "VOLUNTARY", "ADMINISTRATIVE", "BED_HOLD_EXPIRED")
GOVERNING_PLAN_STATUSES = ("ACTIVE", "REVIEW_DUE")


def find_resident(resident_id):
    resident = store.residents.get(resident_id)
    if resident is None:
        fail("ERR_RESIDENT_NOT_FOUND", "No resident with id %s." % resident_id)
    return resident


def find_plan(plan_id):
    plan = store.care_plans.get(plan_id)
    if plan is None:
        fail("ERR_CARE_PLAN_NOT_FOUND", "No care plan with id %s." % plan_id)
    return plan


def own_resident(user_id, role, resident_id):
    """Ladder rung 6: entity-backed identity for a ResidentRepresentative."""
    if role == "ResidentRepresentative" and user_id != resident_id:
        fail(
            "ERR_NOT_RESOURCE_OWNER",
            "A ResidentRepresentative may only address its own resident record.",
        )


# ------------------------------------------------------------------ reads ----
@bp.get("/residents/<resident_id>")
def get_resident(resident_id):
    user_id, role = guard(
        "StateProgramAdmin",
        "AdmissionsCoordinator",
        "ClinicalAssessor",
        "BusinessOfficeManager",
        "FederalPerDiemAuditor",
        "ResidentRepresentative",
    )
    resident = find_resident(resident_id)
    own_resident(user_id, role, resident["id"])
    return object_response(resident_out(resident))


@bp.get("/residents")
def list_residents():
    guard(
        "StateProgramAdmin",
        "AdmissionsCoordinator",
        "ClinicalAssessor",
        "BusinessOfficeManager",
        "FederalPerDiemAuditor",
    )
    limit, offset = pagination()
    applicant_id = q_str("applicant_id")
    care_unit_id = q_str("care_unit_id")
    occupancy_status = q_str("occupancy_status")
    billing_status = q_str("billing_status")
    rows = list(store.residents.values())
    if applicant_id is not None:
        rows = [r for r in rows if r["applicant_id"] == applicant_id]
    if care_unit_id is not None:
        rows = [r for r in rows if r["care_unit_id"] == care_unit_id]
    if occupancy_status is not None:
        rows = [r for r in rows if r["occupancy_status"] == occupancy_status]
    if billing_status is not None:
        rows = [r for r in rows if r["billing_status"] == billing_status]
    rows = sorted(rows, key=lambda r: (r["admission_date"], r["created_at"], r["_seq"]))
    return paginate(rows, limit, offset, resident_out)


@bp.get("/care-plans/<plan_id>")
def get_plan(plan_id):
    user_id, role = guard(
        "StateProgramAdmin",
        "ClinicalAssessor",
        "AdmissionsCoordinator",
        "BusinessOfficeManager",
        "ResidentRepresentative",
    )
    plan = find_plan(plan_id)
    own_resident(user_id, role, plan["resident_id"])
    return object_response(care_plan_out(plan))


@bp.get("/care-plans")
def list_plans():
    guard(
        "StateProgramAdmin",
        "ClinicalAssessor",
        "AdmissionsCoordinator",
        "BusinessOfficeManager",
    )
    limit, offset = pagination()
    resident_id = q_str("resident_id")
    supersedes = q_str("supersedes_care_plan_id")
    status = q_str("status")
    rows = list(store.care_plans.values())
    if resident_id is not None:
        rows = [p for p in rows if p["resident_id"] == resident_id]
    if supersedes is not None:
        rows = [p for p in rows if p["supersedes_care_plan_id"] == supersedes]
    if status is not None:
        rows = [p for p in rows if p["status"] == status]
    rows = sorted(
        rows,
        key=lambda p: (p["plan_date"], p["revision_number"], p["created_at"], p["_seq"]),
    )
    return paginate(rows, limit, offset, care_plan_out)


# ------------------------------------------------------------ care plans ----
@bp.post("/residents/<resident_id>/care-plans")
def author_plan(resident_id):
    user_id, _role = guard("ClinicalAssessor")
    body = json_body()
    care_level = f_enum(body, "care_level", CARE_LEVELS)
    adl_support_level = f_enum(body, "adl_support_level", ADL_SUPPORT_LEVELS)
    plan_date = f_date(body, "plan_date")
    supersedes_id = f_id(body, "supersedes_care_plan_id", required=False)

    resident = find_resident(resident_id)
    superseded = None
    if supersedes_id is not None:
        superseded = store.care_plans.get(supersedes_id)
        if superseded is None:
            fail("ERR_CARE_PLAN_NOT_FOUND", "No care plan with id %s." % supersedes_id)

    if resident["occupancy_status"] == "DISCHARGED":
        fail("ERR_RESIDENT_STATE_INVALID", "A discharged resident accepts no new care plan.")
    if superseded is not None and superseded["status"] not in GOVERNING_PLAN_STATUSES:
        fail(
            "ERR_CARE_PLAN_STATE_INVALID",
            "supersedes_care_plan_id must name an ACTIVE or REVIEW_DUE plan.",
        )
    if parse_date(plan_date) > clock_date():
        fail("ERR_DATE_OUT_OF_RANGE", "plan_date may not lie in the future.")

    plan = new_record()
    plan.update(
        {
            "resident_id": resident["id"],
            "supersedes_care_plan_id": supersedes_id,
            "care_level": care_level,
            "adl_support_level": adl_support_level,
            "plan_date": plan_date,
            "status": "DRAFT",
            "review_due_date": None,
            "authored_by_user_id": user_id,
            "activated_at": None,
            "revision_number": (superseded["revision_number"] + 1) if superseded else 1,
        }
    )
    store.care_plans[plan["id"]] = plan
    touch_once(resident)
    return object_response(care_plan_out(plan), 201)


@bp.post("/care-plans/<plan_id>/activate")
def activate_plan(plan_id):
    guard("ClinicalAssessor")
    json_body()
    plan = find_plan(plan_id)
    if plan["status"] not in ("DRAFT", "REVIEW_DUE"):
        fail("ERR_CARE_PLAN_STATE_INVALID", "Only a DRAFT or REVIEW_DUE plan may be activated.")
    resident = store.residents.get(plan["resident_id"])
    if resident is None or resident["occupancy_status"] == "DISCHARGED":
        fail("ERR_RESIDENT_STATE_INVALID", "A discharged resident's plan may not be activated.")

    reactivation = plan["status"] == "REVIEW_DUE"
    superseded = None
    if not reactivation:
        if plan["supersedes_care_plan_id"] is not None:
            superseded = store.care_plans.get(plan["supersedes_care_plan_id"])
            if (
                superseded is None
                or superseded["resident_id"] != resident["id"]
                or superseded["status"] not in GOVERNING_PLAN_STATUSES
            ):
                fail(
                    "ERR_CARE_PLAN_STATE_INVALID",
                    "The superseded plan must belong to this resident and be ACTIVE or REVIEW_DUE.",
                )
        else:
            if services.governing_plans(resident["id"]):
                fail(
                    "ERR_CARE_PLAN_STATE_INVALID",
                    "The resident already holds a governing care plan.",
                )

    plan["status"] = "ACTIVE"
    plan["activated_at"] = now_iso()
    if reactivation:
        plan["review_due_date"] = format_date(clock_date() + timedelta(days=CARE_PLAN_REVIEW_DAYS))
    else:
        plan["review_due_date"] = format_date(
            parse_date(plan["plan_date"]) + timedelta(days=CARE_PLAN_REVIEW_DAYS)
        )
        plan["revision_number"] = (superseded["revision_number"] + 1) if superseded else 1
    touch_once(plan)
    if superseded is not None:
        superseded["status"] = "SUPERSEDED"
        touch_once(superseded)
    resident["current_care_level"] = plan["care_level"]
    touch_once(resident)
    return object_response(care_plan_out(plan))


# --------------------------------------------------- occupancy movements ----
@bp.post("/residents/<resident_id>/transfer")
def transfer(resident_id):
    guard("AdmissionsCoordinator")
    body = json_body()
    target_id = f_id(body, "target_care_unit_id")
    effective_date = f_date(body, "effective_date")
    f_str(body, "transfer_note", required=False)

    resident = find_resident(resident_id)
    target = store.care_units.get(target_id)
    if target is None:
        fail("ERR_CARE_UNIT_NOT_FOUND", "No care unit with id %s." % target_id)

    if resident["occupancy_status"] != "ADMITTED":
        fail("ERR_RESIDENT_STATE_INVALID", "Only an ADMITTED resident may be transferred.")
    if target["certification_status"] != "CERTIFIED":
        fail("ERR_UNIT_NOT_CERTIFIED", "The target unit must be CERTIFIED.")
    if calc.operational_posture(target) == "FROZEN":
        fail("ERR_UNIT_POSTURE_BLOCKED", "The target unit's operational posture is FROZEN.")
    plan = services.active_plan(resident["id"])
    if plan is not None and plan["care_level"] != target["care_level"]:
        fail(
            "ERR_CARE_LEVEL_MISMATCH",
            "The resident's ACTIVE care plan does not prescribe the target unit's care_level.",
        )
    if plan is None:
        fail("ERR_NO_ACTIVE_CARE_PLAN", "A transfer requires an ACTIVE care plan.")
    source = store.care_units.get(resident["care_unit_id"])
    if target["id"] == resident["care_unit_id"] or (
        source is not None and target["veterans_home_id"] != source["veterans_home_id"]
    ):
        fail(
            "ERR_INVALID_TRANSFER_TARGET",
            "The target unit must differ from the current unit and belong to the same home.",
        )
    if parse_date(effective_date) > clock_date():
        fail("ERR_DATE_OUT_OF_RANGE", "effective_date may not lie in the future.")
    if calc.available_bed_count(target) < 1:
        fail("ERR_NO_AVAILABLE_BED", "The target unit has no free bed.")

    resident["care_unit_id"] = target["id"]
    resident["current_care_level"] = target["care_level"]
    touch_once(resident)
    services.sync_unit(source)
    services.sync_unit(target)
    return object_response(resident_out(resident))


@bp.post("/residents/<resident_id>/hospitalization")
def hospitalization(resident_id):
    guard("AdmissionsCoordinator", "ClinicalAssessor")
    body = json_body()
    start_date = f_date(body, "hospitalization_start_date")
    f_str(body, "facility_note", required=False)

    resident = find_resident(resident_id)
    if resident["occupancy_status"] != "ADMITTED":
        fail("ERR_RESIDENT_STATE_INVALID", "Only an ADMITTED resident may open a bed hold.")
    if parse_date(start_date) < parse_date(resident["admission_date"]):
        fail("ERR_DATE_OUT_OF_RANGE", "hospitalization_start_date precedes the admission date.")
    prior_end = resident["last_hospitalization_end_date"]
    if prior_end is not None and parse_date(start_date) <= parse_date(prior_end):
        fail(
            "ERR_BED_HOLD_OVERLAP",
            "hospitalization_start_date must fall strictly after the prior readmission date.",
        )
    if resident["bed_hold_days_used"] >= BED_HOLD_MAX_DAYS:
        fail("ERR_BED_HOLD_EXHAUSTED", "The thirty-day bed-hold allowance is exhausted.")

    resident["occupancy_status"] = "HOSPITALIZED"
    resident["bed_hold_started_on"] = start_date
    resident["hospitalization_count"] += 1
    touch_once(resident)
    services.sync_unit(store.care_units.get(resident["care_unit_id"]))
    return object_response(resident_out(resident))


@bp.post("/residents/<resident_id>/readmission")
def readmission(resident_id):
    guard("AdmissionsCoordinator", "ClinicalAssessor")
    body = json_body()
    readmission_date = f_date(body, "readmission_date")

    resident = find_resident(resident_id)
    if resident["occupancy_status"] != "HOSPITALIZED":
        fail("ERR_RESIDENT_STATE_INVALID", "Only a HOSPITALIZED resident may be readmitted.")
    unit = store.care_units.get(resident["care_unit_id"])
    if unit is not None and unit["certification_status"] == "DECERTIFIED":
        fail("ERR_UNIT_NOT_CERTIFIED", "A decertified unit may not take a resident back.")
    hold_start = resident["bed_hold_started_on"]
    if hold_start is None or parse_date(readmission_date) <= parse_date(hold_start):
        fail("ERR_DATE_OUT_OF_RANGE", "readmission_date must fall strictly after bed_hold_started_on.")
    span = (parse_date(readmission_date) - parse_date(hold_start)).days
    if resident["bed_hold_days_used"] + span > BED_HOLD_MAX_DAYS:
        fail("ERR_BED_HOLD_EXHAUSTED", "The closed interval would exceed the bed-hold allowance.")

    resident["occupancy_status"] = "ADMITTED"
    resident["last_hospitalization_end_date"] = readmission_date
    resident["bed_hold_days_used"] += span
    resident["readmission_count"] += 1
    touch_once(resident)
    services.sync_unit(unit)
    return object_response(resident_out(resident))


@bp.post("/residents/<resident_id>/discharge")
def discharge(resident_id):
    guard("AdmissionsCoordinator")
    body = json_body()
    discharge_date = f_date(body, "discharge_date")
    discharge_reason = f_enum(body, "discharge_reason", DISCHARGE_REASONS)

    resident = find_resident(resident_id)
    previous = resident["occupancy_status"]
    if previous == "DISCHARGED":
        fail("ERR_RESIDENT_STATE_INVALID", "The resident is already discharged.")
    if previous == "ADMITTED" and discharge_reason == "BED_HOLD_EXPIRED":
        fail(
            "ERR_RESIDENT_STATE_INVALID",
            "BED_HOLD_EXPIRED is reserved for a hospitalized resident.",
        )
    if previous == "HOSPITALIZED":
        anchor = resident["bed_hold_started_on"] or resident["admission_date"]
        if parse_date(discharge_date) < parse_date(anchor):
            fail("ERR_DATE_OUT_OF_RANGE", "discharge_date precedes bed_hold_started_on.")
    else:
        if parse_date(discharge_date) < parse_date(resident["admission_date"]):
            fail("ERR_DATE_OUT_OF_RANGE", "discharge_date precedes the admission date.")

    resident["occupancy_status"] = "DISCHARGED"
    resident["billing_status"] = "CLOSED"
    resident["discharge_date"] = discharge_date
    resident["discharge_reason"] = discharge_reason
    touch_once(resident)

    for plan in sorted(services.resident_plans(resident["id"]), key=order_key):
        if plan["status"] == "DRAFT":
            plan["status"] = "VOID"
            touch_once(plan)
        elif plan["status"] in GOVERNING_PLAN_STATUSES:
            plan["status"] = "SUPERSEDED"
            touch_once(plan)

    unit = store.care_units.get(resident["care_unit_id"])
    services.sync_unit(unit)
    home = calc.home_of_resident(resident)
    if home is not None:
        touch_once(home)
    return object_response(resident_out(resident))
