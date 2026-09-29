"""VendorFirm endpoints.  Network lifecycle plus the capacity-hold axis."""
from flask import Blueprint, request

import derive
import ops
import store
import validate
from envelope import created, ok
from errors import fail
from routes.common import begin, listing
from store import touch

bp = Blueprint("vendor_firms", __name__)

VENDOR_TYPES = ("MITIGATION", "TARP", "TREE_REMOVAL", "CONTRACTOR")


@bp.post("/vendor-firms")
def create_firm():
    begin()
    payload = validate.body()
    firm_name = validate.req_string(payload, "firm_name")
    vendor_type = validate.req_enum(payload, "vendor_type", VENDOR_TYPES)
    service_states = validate.req_state_array(payload, "service_states")
    max_jobs = validate.req_int(payload, "max_concurrent_jobs", minimum=1, maximum=200)
    score = validate.req_number(payload, "performance_score", minimum=0, maximum=100)
    # Position 31 - firm_name uniqueness.
    for other in store.vendor_firms.values():
        if other["firm_name"] == firm_name:
            fail("ERR_VENDOR_NAME_TAKEN")

    rec = store.base_record()
    rec.update({
        "firm_name": firm_name,
        "vendor_type": vendor_type,
        "service_states": service_states,
        "status": "NETWORK_INACTIVE",
        "activated_for_event_id": None,
        "max_concurrent_jobs": max_jobs,
        "performance_score": score,
    })
    store.vendor_firms[rec["id"]] = rec
    return created(derive.vendor_firm_out(rec))


@bp.get("/vendor-firms")
def list_firms():
    begin()
    rows = list(store.vendor_firms.values())
    for param, field in (("activated_for_event_id", "activated_for_event_id"),
                         ("vendor_type", "vendor_type"), ("status", "status")):
        value = request.args.get(param)
        if value is not None:
            rows = [r for r in rows if r.get(field) == value]
    service_state = request.args.get("service_state")
    if service_state is not None:
        rows = [r for r in rows if service_state in r["service_states"]]
    return listing(rows, derive.vendor_firm_out)


@bp.get("/vendor-firms/<vendor_firm_id>")
def read_firm(vendor_firm_id):
    begin()
    return ok(derive.vendor_firm_out(validate.vendor_firm(vendor_firm_id)))


@bp.post("/vendor-firms/<vendor_firm_id>/activate")
def activate_firm(vendor_firm_id):
    begin()
    # Position 4 (event) precedes position 11 (vendor firm).
    soft = validate.soft_body()
    raw_event = validate.raw_ref(soft, "event_id")
    event = validate.event(raw_event) if raw_event is not None else None
    rec = validate.vendor_firm(vendor_firm_id)
    payload = validate.body()
    if event is None:
        validate.req_string(payload, "event_id")

    if rec["status"] != "NETWORK_INACTIVE":
        fail("ERR_VENDOR_NOT_INACTIVE")
    if event["status"] not in ("DECLARED", "SURGE_ACTIVE"):
        fail("ERR_EVENT_NOT_DECLARED")
    # Position 28 - the firm must serve the event's jurisdiction.
    if event["jurisdiction_state"] not in rec["service_states"]:
        fail("ERR_VENDOR_NOT_LICENSED_IN_STATE")

    rec["status"] = "ACTIVATED"
    rec["activated_for_event_id"] = event["id"]
    touch(rec)
    return ok(derive.vendor_firm_out(rec))


@bp.post("/vendor-firms/<vendor_firm_id>/suspend")
def suspend_firm(vendor_firm_id):
    begin()
    rec = validate.vendor_firm(vendor_firm_id)
    if rec["status"] not in ("NETWORK_INACTIVE", "ACTIVATED", "CAPACITY_HOLD"):
        fail("ERR_VENDOR_NOT_SUSPENDABLE")
    rec["status"] = "SUSPENDED"
    rec["activated_for_event_id"] = None
    touch(rec)
    # Every not-yet-accepted job is cancelled; accepted work is left to finish.
    for job in list(store.vendor_assignments.values()):
        if job["vendor_firm_id"] == rec["id"] and job["status"] == "DISPATCHED":
            job["status"] = "CANCELLED"
            touch(job)
    return ok(derive.vendor_firm_out(rec))
