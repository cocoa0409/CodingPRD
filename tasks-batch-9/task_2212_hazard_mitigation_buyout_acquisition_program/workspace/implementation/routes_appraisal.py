"""Appraisal authoring / review and duplication-of-benefits records."""
from flask import Blueprint, g

import calc
import lookups
import store
import web
from core import fail, parse_date
from web import endpoint

bp = Blueprint("appraisals", __name__)


@bp.post("/parcels/<parcel_id>/appraisals")
@endpoint("StaffAppraiser", "ReviewAppraiser")
def create_appraisal(parcel_id):
    parcel = lookups.get_parcel(parcel_id)
    body = web.get_body()
    appraisal_type = web.req_enum(body, "appraisal_type", store.APPRAISAL_TYPES)
    if appraisal_type == "INITIAL" and g.role != "StaffAppraiser":
        fail("ERR_UNAUTHORIZED")
    if appraisal_type == "REVIEW" and g.role != "ReviewAppraiser":
        fail("ERR_UNAUTHORIZED")
    valuation_basis = web.req_enum(body, "valuation_basis", store.VALUATION_BASES)
    license_no = web.req_string(body, "appraiser_license_no")
    effective_date = web.req_date(body, "effective_date")
    value = web.int_field(body, "indicated_value_cents", minimum=1)
    reviewed_id = web.opt_id(body, "reviewed_appraisal_id")
    if appraisal_type == "INITIAL" and reviewed_id is not None:
        fail("ERR_INVALID_REQUEST",
             "Field 'reviewed_appraisal_id' must be null when appraisal_type is INITIAL.")

    reviewed = lookups.get_appraisal(reviewed_id) if reviewed_id is not None else None
    if reviewed is not None and reviewed["parcel_id"] != parcel_id:
        fail("ERR_PARCEL_PROJECT_MISMATCH")
    project = lookups.project_of_parcel(parcel)
    if project is None or project["status"] != "APPROVED":
        fail("ERR_PROJECT_NOT_APPROVED")
    if appraisal_type == "REVIEW":
        if reviewed is None or reviewed["appraisal_type"] != "INITIAL":
            fail("ERR_REVIEW_APPRAISAL_REQUIRED")

    record = store.new_record("Appraisal", {
        "parcel_id": parcel_id,
        "reviewed_appraisal_id": reviewed_id,
        "appraisal_type": appraisal_type,
        "valuation_basis": valuation_basis,
        "appraiser_user_id": g.uid,
        "appraiser_license_no": license_no,
        "effective_date": body["effective_date"],
        "validity_end_date": None,
        "indicated_value_cents": value,
        "revision_count": 0,
        "status": "DRAFT",
    })
    store.appraisals[record["id"]] = record

    if (appraisal_type == "INITIAL"
            and parcel["acquisition_status"] == "NOT_STARTED"
            and parcel["participation_status"] in ("INTERESTED", "VOLUNTARY_CONFIRMED")):
        parcel["acquisition_status"] = "APPRAISAL_IN_PROGRESS"
        store.touch(parcel)
    return web.respond_object(record, 201)


@bp.get("/appraisals")
@endpoint("ProgramAdministrator", "SubrecipientCoordinator", "StaffAppraiser",
          "ReviewAppraiser", "ComplianceMonitor")
def list_appraisals():
    parcel_id = web.query_str("parcel_id")
    reviewed_id = web.query_str("reviewed_appraisal_id")
    appraisal_type = web.query_enum("appraisal_type", store.APPRAISAL_TYPES)
    status = web.query_enum("status", store.APPRAISAL_STATUSES)
    rows = list(store.appraisals.values())
    if parcel_id is not None:
        rows = [r for r in rows if r["parcel_id"] == parcel_id]
    if reviewed_id is not None:
        rows = [r for r in rows if r["reviewed_appraisal_id"] == reviewed_id]
    if appraisal_type is not None:
        rows = [r for r in rows if r["appraisal_type"] == appraisal_type]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return web.list_response(rows)


@bp.get("/appraisals/<appraisal_id>")
@endpoint("ProgramAdministrator", "SubrecipientCoordinator", "StaffAppraiser",
          "ReviewAppraiser", "ComplianceMonitor")
def read_appraisal(appraisal_id):
    return web.respond_object(lookups.get_appraisal(appraisal_id))


@bp.post("/appraisals/<appraisal_id>/submit")
@endpoint("StaffAppraiser", "ReviewAppraiser")
def submit_appraisal(appraisal_id):
    appraisal = lookups.get_appraisal(appraisal_id)
    if g.uid != appraisal["appraiser_user_id"]:
        fail("ERR_UNAUTHORIZED")
    body = web.get_body()
    new_effective = web.opt_date(body, "effective_date")
    new_value = web.int_field(body, "indicated_value_cents", required=False, minimum=1)
    if appraisal["status"] not in ("DRAFT", "RETURNED_FOR_REVISION"):
        fail("ERR_INVALID_APPRAISAL_STATE")

    effective = new_effective or parse_date(appraisal["effective_date"])
    end_date = calc.validity_end(effective)
    if appraisal["appraisal_type"] == "INITIAL":
        if calc.appraisal_window_overlap(appraisal, effective, parse_date(end_date)):
            fail("ERR_APPRAISAL_WINDOW_OVERLAP")
    if (appraisal["status"] == "RETURNED_FOR_REVISION"
            and int(appraisal["revision_count"]) > store.MAX_APPRAISAL_REVISIONS):
        fail("ERR_APPRAISAL_REVISION_LIMIT")

    if new_effective is not None:
        appraisal["effective_date"] = body["effective_date"]
    if new_value is not None:
        appraisal["indicated_value_cents"] = new_value
    appraisal["validity_end_date"] = end_date
    appraisal["status"] = "SUBMITTED"
    store.touch(appraisal)
    return web.respond_object(appraisal)


@bp.post("/appraisals/<appraisal_id>/review-decision")
@endpoint("ReviewAppraiser")
def review_appraisal(appraisal_id):
    appraisal = lookups.get_appraisal(appraisal_id)
    # SoD-1 precedes structural validation (PRD 2.9 step 3).
    if g.uid == appraisal["appraiser_user_id"]:
        fail("ERR_SEGREGATION_OF_DUTIES")
    reviewed = None
    if appraisal["appraisal_type"] == "REVIEW" and appraisal.get("reviewed_appraisal_id"):
        reviewed = store.appraisals.get(appraisal["reviewed_appraisal_id"])
        if reviewed is not None and g.uid == reviewed["appraiser_user_id"]:
            fail("ERR_SEGREGATION_OF_DUTIES")

    body = web.get_body()
    decision = web.req_enum(body, "decision", ["ACCEPT", "RETURN", "REJECT"])
    web.opt_string(body, "review_note")

    if decision == "RETURN":
        if appraisal["status"] != "SUBMITTED":
            fail("ERR_INVALID_APPRAISAL_STATE")
        appraisal["status"] = "RETURNED_FOR_REVISION"
        appraisal["revision_count"] = int(appraisal["revision_count"]) + 1
        store.touch(appraisal)
        return web.respond_object(appraisal)

    if decision == "REJECT":
        if appraisal["status"] not in ("SUBMITTED", "RETURNED_FOR_REVISION"):
            fail("ERR_INVALID_APPRAISAL_STATE")
        appraisal["status"] = "REJECTED"
        store.touch(appraisal)
        return web.respond_object(appraisal)

    if appraisal["status"] != "SUBMITTED":
        fail("ERR_INVALID_APPRAISAL_STATE")
    if appraisal["appraisal_type"] == "REVIEW":
        if (reviewed is None or reviewed["appraisal_type"] != "INITIAL"
                or reviewed["status"] != "ACCEPTED"):
            fail("ERR_REVIEW_APPRAISAL_REQUIRED")
    appraisal["status"] = "ACCEPTED"
    store.touch(appraisal)
    if appraisal["appraisal_type"] == "REVIEW":
        parcel = store.parcels.get(appraisal["parcel_id"])
        if parcel is not None and parcel["acquisition_status"] == "APPRAISAL_IN_PROGRESS":
            parcel["acquisition_status"] = "VALUE_ESTABLISHED"
            store.touch(parcel)
    return web.respond_object(appraisal)


# --------------------------------------------------------------------------
# Duplication-of-benefits records
# --------------------------------------------------------------------------

@bp.post("/parcels/<parcel_id>/dob-records")
@endpoint("SubrecipientCoordinator")
def create_dob_record(parcel_id):
    parcel = lookups.get_parcel(parcel_id)
    web.scope_project(parcel["project_id"])
    body = web.get_body()
    source = web.req_enum(body, "benefit_source", store.BENEFIT_SOURCES)
    amount = web.int_field(body, "amount_cents", minimum=1)
    repaired = web.int_field(body, "repair_documented_cents", required=False, default=0, minimum=0)
    received_on = web.req_date(body, "received_on")
    project = lookups.project_of_parcel(parcel)
    if project is None or project["status"] != "APPROVED":
        fail("ERR_PROJECT_NOT_APPROVED")

    record = store.new_record("DuplicationOfBenefitsRecord", {
        "parcel_id": parcel_id,
        "benefit_source": source,
        "amount_cents": amount,
        "repair_documented_cents": repaired,
        "deductible_cents": 0,
        "received_on": body["received_on"],
        "status": "ACTIVE",
        "reversal_reason": None,
    })
    store.dob_records[record["id"]] = record
    calc.recompute_dob_total(parcel)
    store.touch(parcel)
    return web.respond_object(record, 201)


@bp.get("/dob-records")
@endpoint("ProgramAdministrator", "SubrecipientCoordinator", "ComplianceMonitor")
def list_dob_records():
    parcel_id = web.query_str("parcel_id")
    source = web.query_enum("benefit_source", store.BENEFIT_SOURCES)
    status = web.query_enum("status", store.DOB_STATUSES)
    rows = list(store.dob_records.values())
    if parcel_id is not None:
        rows = [r for r in rows if r["parcel_id"] == parcel_id]
    if source is not None:
        rows = [r for r in rows if r["benefit_source"] == source]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return web.list_response(rows)


@bp.get("/dob-records/<dob_record_id>")
@endpoint("ProgramAdministrator", "SubrecipientCoordinator", "ComplianceMonitor")
def read_dob_record(dob_record_id):
    return web.respond_object(lookups.get_dob_record(dob_record_id))


@bp.post("/dob-records/<dob_record_id>/reverse")
@endpoint("ProgramAdministrator")
def reverse_dob_record(dob_record_id):
    record = lookups.get_dob_record(dob_record_id)
    body = web.get_body()
    reason = web.req_string(body, "reversal_reason")
    if record["status"] != "ACTIVE":
        fail("ERR_ALREADY_REVERSED")
    record["status"] = "REVERSED"
    record["reversal_reason"] = reason
    store.touch(record)
    parcel = store.parcels.get(record["parcel_id"])
    if parcel is not None:
        calc.recompute_dob_total(parcel)
        store.touch(parcel)
    return web.respond_object(record)
