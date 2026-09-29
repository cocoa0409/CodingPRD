"""AMC dispute case filing, relay and resolution."""

from flask import Blueprint

import db
import response
import validate as V
from errors import fail
from middleware import (ROLE_AMC_COORDINATOR, ROLE_APPRAISER, ROLE_CHIEF_APPRAISER,
                        ROLE_COMPLIANCE, ROLE_DESK_REVIEWER, require_owner,
                        require_roles)
from routes.common import PREFIX, body_fk, filter_equals, find_dispute
from services import constants as C
from services import escalation as esc_svc
from services import panel as panel_svc
from services import revision as revision_svc

bp = Blueprint("disputes", __name__)


@bp.post(PREFIX + "/dispute-cases")
def file_dispute():
    require_roles(ROLE_DESK_REVIEWER, ROLE_CHIEF_APPRAISER)
    data = V.body()
    appraisal = body_fk(data, "appraisal_id", db.appraisals, "ERR_APPRAISAL_NOT_FOUND")
    amc = body_fk(data, "amc_id", db.amcs, "ERR_AMC_NOT_FOUND")
    appraiser = body_fk(data, "appraiser_id", db.appraisers, "ERR_APPRAISER_NOT_FOUND")
    V.req_str(data, "appraisal_id")
    V.req_str(data, "amc_id")
    V.req_str(data, "appraiser_id")
    basis = V.req_enum(data, "dispute_basis", C.DISPUTE_BASES)
    has_start = V.present(data, "review_slot_start")
    has_end = V.present(data, "review_slot_end")
    if not has_start and not has_end:
        fail("ERR_INVALID_REQUEST", "A review slot is required.")
    slot_start = V.opt_dt(data, "review_slot_start")
    slot_end = V.opt_dt(data, "review_slot_end")

    if amc["panel_status"] == "SUSPENDED":
        fail("ERR_AMC_NOT_ELIGIBLE")

    if appraisal["amc_id"] != amc["id"] or appraisal["appraiser_id"] != appraiser["id"]:
        fail("ERR_DISPUTE_PARTY_MISMATCH")

    if slot_start is None or slot_end is None or slot_start >= slot_end:
        fail("ERR_INVALID_WINDOW")

    overlaps = esc_svc.overlapping_dispute_slots(amc["id"], slot_start, slot_end)
    if overlaps >= amc["concurrent_dispute_capacity"]:
        fail("ERR_DISPUTE_SLOT_CAPACITY_EXCEEDED")

    for case in db.dispute_cases.values():
        if (case["appraisal_id"] == appraisal["id"]
                and case["dispute_basis"] == basis
                and case["status"] not in C.DISPUTE_RESOLVED_STATUSES):
            fail("ERR_DUPLICATE_DISPUTE_BASIS")

    record = db.make_record({
        "appraisal_id": appraisal["id"],
        "amc_id": amc["id"],
        "appraiser_id": appraiser["id"],
        "dispute_basis": basis,
        "review_slot_start": slot_start,
        "review_slot_end": slot_end,
        "response_deadline_at": None,
        "appraiser_position": None,
        "response_summary": None,
        "appraiser_responded_at": None,
        "responded_late": False,
        "status": "OPEN",
        "resolution": None,
        "resolved_value_cents": None,
        "resolution_note": None,
    })
    record["response_deadline_at"] = db.hours_after(record["created_at"],
                                                    amc["sla_response_hours"])
    db.dispute_cases[record["id"]] = record
    panel_svc.refresh_amc_counters(amc)
    return response.created(record)


@bp.get(PREFIX + "/dispute-cases/<case_id>")
def get_dispute(case_id):
    require_roles(ROLE_DESK_REVIEWER, ROLE_CHIEF_APPRAISER, ROLE_COMPLIANCE,
                  ROLE_AMC_COORDINATOR, ROLE_APPRAISER)
    return response.ok(find_dispute(case_id))


@bp.get(PREFIX + "/dispute-cases")
def list_disputes():
    require_roles(ROLE_DESK_REVIEWER, ROLE_CHIEF_APPRAISER, ROLE_COMPLIANCE,
                  ROLE_AMC_COORDINATOR)
    rows = db.ordered(db.dispute_cases)
    rows = filter_equals(rows, "appraisal_id")
    rows = filter_equals(rows, "amc_id")
    rows = filter_equals(rows, "appraiser_id")
    rows = filter_equals(rows, "status")
    return response.page(rows)


@bp.post(PREFIX + "/dispute-cases/<case_id>/amc-response")
def relay_response(case_id):
    user_id, _ = require_roles(ROLE_AMC_COORDINATOR)
    case = find_dispute(case_id)
    require_owner(case["amc_id"], user_id)
    data = V.body()
    position = V.req_enum(data, "appraiser_position", C.APPRAISER_POSITIONS)
    summary = V.req_str(data, "response_summary")

    if case["status"] in C.DISPUTE_RESOLVED_STATUSES:
        fail("ERR_DISPUTE_ALREADY_RESOLVED")
    if case["status"] != "OPEN":
        fail("ERR_INVALID_STATE")

    instant = db.now()
    deadline = case["response_deadline_at"]
    late = bool(deadline is not None and instant > deadline)

    case["status"] = "APPRAISER_RESPONDED"
    case["appraiser_position"] = position
    case["response_summary"] = summary
    case["appraiser_responded_at"] = instant
    case["responded_late"] = late
    db.bump(case)

    amc = db.amcs.get(case["amc_id"])
    appraiser = db.appraisers.get(case["appraiser_id"])
    if late and appraiser is not None:
        appraiser["sla_miss_count"] += 1
        panel_svc.recompute_performance(appraiser)
    if amc is not None:
        panel_svc.refresh_amc_counters(amc)
        if late:
            panel_svc.apply_amc_cascade(amc)
    return response.ok(case)


@bp.post(PREFIX + "/dispute-cases/<case_id>/resolve")
def resolve_dispute(case_id):
    require_roles(ROLE_CHIEF_APPRAISER)
    case = find_dispute(case_id)
    data = V.body()
    resolution = V.req_enum(data, "resolution", C.DISPUTE_RESOLUTIONS)
    resolved_value = V.opt_int(data, "resolved_value_cents", positive=True)
    resolution_note = V.opt_str(data, "resolution_note")
    if resolution == "OVERTURNED" and resolved_value is None:
        fail("ERR_INVALID_REQUEST", "resolved_value_cents is required when overturning.")

    if case["status"] in C.DISPUTE_RESOLVED_STATUSES:
        fail("ERR_DISPUTE_ALREADY_RESOLVED")
    if case["status"] not in ("OPEN", "APPRAISER_RESPONDED"):
        fail("ERR_INVALID_STATE")
    if resolution == "BY_DEFAULT" and case["status"] != "OPEN":
        fail("ERR_INVALID_STATE")

    if resolution == "BY_DEFAULT":
        deadline = case["response_deadline_at"]
        if deadline is not None and db.now() < deadline:
            fail("ERR_DISPUTE_DEADLINE_NOT_REACHED")

    appraisal = db.appraisals.get(case["appraisal_id"])
    loan = db.loan_files.get(appraisal["loan_file_id"]) if appraisal else None

    if resolution == "OVERTURNED":
        if appraisal is not None and revision_svc.exceeds_cap(appraisal, resolved_value):
            fail("ERR_REVISION_EXCEEDS_CAP")

    case["resolution"] = resolution
    case["resolution_note"] = resolution_note
    if resolution == "UPHELD":
        case["status"] = "RESOLVED_UPHELD"
    elif resolution == "OVERTURNED":
        case["status"] = "RESOLVED_OVERTURNED"
        case["resolved_value_cents"] = resolved_value
    else:
        case["status"] = "RESOLVED_BY_DEFAULT"
    db.bump(case)

    if resolution == "OVERTURNED" and appraisal is not None:
        if loan is not None and loan["value_of_record_appraisal_id"] is None:
            loan["value_of_record_appraisal_id"] = appraisal["id"]
            db.touch(loan)
        revision_svc.write_revision(appraisal, loan, "DISPUTE", case["id"],
                                    resolved_value, resolution_note,
                                    is_compensating=True)

    amc = db.amcs.get(case["amc_id"])
    if amc is not None:
        panel_svc.refresh_amc_counters(amc)
        if resolution == "BY_DEFAULT":
            panel_svc.apply_amc_cascade(amc)
    return response.ok(case)
