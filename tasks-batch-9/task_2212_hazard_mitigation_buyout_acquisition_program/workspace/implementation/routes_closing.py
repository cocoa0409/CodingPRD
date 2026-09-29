"""Closing records, deed recording and demolition contractor registry."""
from flask import Blueprint, g

import calc
import lookups
import store
import web
from core import clock_date, clock_now, fail, fmt_date, fmt_dt, parse_date
from web import endpoint

bp = Blueprint("closings", __name__)


@bp.post("/parcels/<parcel_id>/closing-records")
@endpoint("SubrecipientCoordinator")
def create_closing(parcel_id):
    parcel = lookups.get_parcel(parcel_id)
    web.scope_project(parcel["project_id"])
    body = web.get_body()
    offer_id = web.req_string(body, "accepted_offer_id")
    scheduled = web.req_date(body, "scheduled_closing_date")
    settlement = web.int_field(body, "settlement_cost_cents", required=False, default=0, minimum=0)
    offer = lookups.get_offer(offer_id)
    if offer["parcel_id"] != parcel_id:
        fail("ERR_PARCEL_PROJECT_MISMATCH")
    if offer["status"] != "ACCEPTED":
        fail("ERR_INVALID_OFFER_STATE")

    record = store.new_record("ClosingRecord", {
        "parcel_id": parcel_id,
        "accepted_offer_id": offer_id,
        "scheduled_closing_date": fmt_date(scheduled),
        "purchase_price_cents": int(offer["net_offer_cents"]),
        "settlement_cost_cents": settlement,
        "funded_at": None,
        "funded_by_user_id": None,
        "recording_reference": None,
        "recorded_at": None,
        "status": "SCHEDULED",
    })
    store.closings[record["id"]] = record
    return web.respond_object(record, 201)


@bp.get("/closing-records")
@endpoint("ProgramAdministrator", "SubrecipientCoordinator", "ComplianceMonitor")
def list_closings():
    parcel_id = web.query_str("parcel_id")
    offer_id = web.query_str("accepted_offer_id")
    status = web.query_enum("status", store.CLOSING_STATUSES)
    rows = list(store.closings.values())
    if parcel_id is not None:
        rows = [r for r in rows if r["parcel_id"] == parcel_id]
    if offer_id is not None:
        rows = [r for r in rows if r["accepted_offer_id"] == offer_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return web.list_response(rows)


@bp.get("/closing-records/<closing_id>")
@endpoint("ProgramAdministrator", "SubrecipientCoordinator", "ComplianceMonitor")
def read_closing(closing_id):
    return web.respond_object(lookups.get_closing(closing_id))


@bp.post("/closing-records/<closing_id>/fund")
@endpoint("ProgramAdministrator")
def fund_closing(closing_id):
    closing = lookups.get_closing(closing_id)
    parcel = store.parcels.get(closing["parcel_id"])
    project = lookups.project_of_parcel(parcel) if parcel else None
    if closing["status"] != "SCHEDULED":
        fail("ERR_INVALID_CLOSING_STATE")
    if parcel is None or parcel["acquisition_status"] != "OFFER_ACCEPTED":
        fail("ERR_INVALID_CLOSING_STATE")
    scheduled = parse_date(closing["scheduled_closing_date"])
    pop_end = parse_date(project["period_of_performance_end_date"])
    if scheduled is not None and pop_end is not None and scheduled > pop_end:
        fail("ERR_PERIOD_OF_PERFORMANCE_EXPIRED")
    item = calc.federal_item(closing["settlement_cost_cents"], project["cost_share_federal_pct"])
    if int(project["federal_obligated_cents"]) + item > int(project["total_federal_share_cap_cents"]):
        fail("ERR_FEDERAL_SHARE_CAP_EXCEEDED")
    for case in calc.parcel_cases(parcel["id"]):
        if case["status"] not in ("CLAIM_PAID", "CLAIM_DENIED_FINAL"):
            fail("ERR_RELOCATION_NOT_SETTLED")

    closing["status"] = "FUNDED"
    closing["funded_at"] = fmt_dt(clock_now())
    closing["funded_by_user_id"] = g.uid
    store.touch(closing)
    parcel["acquisition_status"] = "CLOSED"
    store.touch(parcel)
    calc.recompute_federal_obligated(project)
    calc.recompute_components(project)
    calc.recompute_ratio(project)
    store.touch(project)
    return web.respond_object(closing)


@bp.post("/closing-records/<closing_id>/record")
@endpoint("SubrecipientCoordinator")
def record_closing(closing_id):
    closing = lookups.get_closing(closing_id)
    parcel = store.parcels.get(closing["parcel_id"])
    web.scope_parcel(parcel)
    project = lookups.project_of_parcel(parcel) if parcel else None
    body = web.get_body()
    reference = web.req_string(body, "recording_reference")
    party = web.req_string(body, "maintenance_responsible_party")
    if closing["status"] != "FUNDED":
        fail("ERR_INVALID_CLOSING_STATE")
    if parcel is None or parcel["acquisition_status"] != "DEMOLISHED":
        fail("ERR_DEMOLITION_NOT_COMPLETE")

    now = clock_now()
    recorded_on = clock_date()
    closing["status"] = "RECORDED"
    closing["recording_reference"] = reference
    closing["recorded_at"] = fmt_dt(now)
    store.touch(closing)

    restriction = store.new_record("DeedRestriction", {
        "parcel_id": parcel["id"],
        "closing_record_id": closing["id"],
        "restriction_type": "OPEN_SPACE_PERPETUAL",
        "prohibited_uses": list(store.PROHIBITED_USE_CODES),
        "recorded_on": fmt_date(recorded_on),
        "monitoring_interval_months": store.MONITORING_INTERVAL_MONTHS,
        "next_monitoring_due_date": calc.next_monitoring_due(recorded_on),
        "corrective_deadline_date": None,
        "open_violation_code": None,
        "violation_reported_by_user_id": None,
        "cured_on": None,
        "maintenance_responsible_party": party,
        "termination_authorization_reference": None,
        "status": "RECORDED",
    })
    store.restrictions[restriction["id"]] = restriction

    parcel["acquisition_status"] = "OPEN_SPACE_RECORDED"
    store.touch(parcel)
    calc.recompute_protected_acres(project)
    store.touch(project)
    return web.respond_object(closing)


# --------------------------------------------------------------------------
# Demolition contractors
# --------------------------------------------------------------------------

@bp.post("/demolition-contractors")
@endpoint("ProgramAdministrator")
def create_contractor():
    body = web.get_body()
    name = web.req_string(body, "name")
    license_no = web.req_string(body, "license_no")
    certified = web.opt_bool(body, "asbestos_certified", False)
    concurrent = web.int_field(body, "max_concurrent_work_orders", required=False, default=1,
                               minimum=1, maximum=10)
    for existing in store.contractors.values():
        if existing["name"] == name:
            fail("ERR_INVALID_REQUEST", "Field 'name' must be unique across contractors.")

    record = store.new_record("DemolitionContractor", {
        "name": name,
        "license_no": license_no,
        "asbestos_certified": certified,
        "max_concurrent_work_orders": concurrent,
        "status": "ACTIVE",
        "active_work_order_count": 0,
    })
    store.contractors[record["id"]] = record
    return web.respond_object(record, 201)


@bp.get("/demolition-contractors")
@endpoint("ProgramAdministrator", "SubrecipientCoordinator", "ComplianceMonitor")
def list_contractors():
    status = web.query_enum("status", store.CONTRACTOR_STATUSES)
    certified = web.query_bool("asbestos_certified")
    rows = list(store.contractors.values())
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if certified is not None:
        rows = [r for r in rows if r["asbestos_certified"] == certified]
    return web.list_response(rows)


@bp.get("/demolition-contractors/<contractor_id>")
@endpoint("ProgramAdministrator", "SubrecipientCoordinator", "ComplianceMonitor")
def read_contractor(contractor_id):
    return web.respond_object(lookups.get_contractor(contractor_id))


@bp.post("/demolition-contractors/<contractor_id>/status")
@endpoint("ProgramAdministrator")
def set_contractor_status(contractor_id):
    contractor = lookups.get_contractor(contractor_id)
    body = web.get_body()
    status = web.req_enum(body, "status", store.CONTRACTOR_STATUSES)
    web.opt_string(body, "status_reason")
    if contractor["status"] == status:
        fail("ERR_INVALID_CONTRACTOR_STATE")
    contractor["status"] = status
    store.touch(contractor)
    return web.respond_object(contractor)
