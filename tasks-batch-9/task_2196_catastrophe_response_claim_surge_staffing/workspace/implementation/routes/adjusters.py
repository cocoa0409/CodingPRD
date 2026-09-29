"""Adjuster endpoints.  Two independent axes: deployment_status, credential_status."""
from flask import Blueprint, request

import derive
import store
import sync
import validate
from envelope import created, ok
from errors import fail
from routes.common import begin, listing
from store import touch

bp = Blueprint("adjusters", __name__)

EMPLOYMENT_TYPES = ("STAFF", "INDEPENDENT")


@bp.post("/adjusters")
def create_adjuster():
    begin()
    payload = validate.body()
    full_name = validate.req_string(payload, "full_name")
    employment_type = validate.req_enum(payload, "employment_type", EMPLOYMENT_TYPES)
    home_state = validate.req_state(payload, "home_state")
    licensed_states = validate.req_state_array(payload, "licensed_states")
    expiry = validate.req_datetime(payload, "license_expiry_utc")
    max_open = validate.req_int(payload, "max_open_claims", minimum=1, maximum=60)
    daily_rate = validate.req_number(payload, "daily_rate", exclusive_min=0)
    per_diem = validate.req_number(payload, "per_diem_rate", minimum=0)
    desk = validate.opt_bool(payload, "desk_certified", False)
    aerial = validate.opt_bool(payload, "aerial_certified", False)

    rec = store.base_record()
    rec.update({
        "full_name": full_name,
        "employment_type": employment_type,
        "home_state": home_state,
        "licensed_states": licensed_states,
        "license_expiry_utc": expiry,
        "credential_status": "VALID",
        "deployment_status": "AVAILABLE",
        "desk_certified": desk,
        "aerial_certified": aerial,
        "max_open_claims": max_open,
        "daily_rate": daily_rate,
        "per_diem_rate": per_diem,
        "last_demobilized_at_utc": None,
        "waiver_event_id": None,
    })
    # The credential axis is stamped from the logical clock at creation time.
    rec["credential_status"] = sync.derived_credential(rec)
    store.adjusters[rec["id"]] = rec
    return created(derive.adjuster_out(rec))


@bp.get("/adjusters")
def list_adjusters():
    begin()
    rows = list(store.adjusters.values())
    for param, field in (("deployment_status", "deployment_status"),
                         ("credential_status", "credential_status"),
                         ("employment_type", "employment_type")):
        value = request.args.get(param)
        if value is not None:
            rows = [r for r in rows if r.get(field) == value]
    licensed_state = request.args.get("licensed_state")
    if licensed_state is not None:
        rows = [r for r in rows if licensed_state in r["licensed_states"]]
    return listing(rows, derive.adjuster_out)


@bp.get("/adjusters/<adjuster_id>")
def read_adjuster(adjuster_id):
    begin()
    return ok(derive.adjuster_out(validate.adjuster(adjuster_id)))


@bp.post("/adjusters/<adjuster_id>/set-unavailable")
def set_unavailable(adjuster_id):
    begin()
    rec = validate.adjuster(adjuster_id)
    if rec["deployment_status"] != "AVAILABLE":
        fail("ERR_ADJUSTER_NOT_AVAILABLE")
    rec["deployment_status"] = "UNAVAILABLE"
    touch(rec)
    return ok(derive.adjuster_out(rec))


@bp.post("/adjusters/<adjuster_id>/set-available")
def set_available(adjuster_id):
    begin()
    rec = validate.adjuster(adjuster_id)
    if rec["deployment_status"] != "UNAVAILABLE":
        fail("ERR_ADJUSTER_NOT_UNAVAILABLE")
    rec["deployment_status"] = "AVAILABLE"
    touch(rec)
    return ok(derive.adjuster_out(rec))


@bp.post("/adjusters/<adjuster_id>/apply-license-waiver")
def apply_license_waiver(adjuster_id):
    begin()
    # Position 4 (event) precedes position 6 (adjuster) in the global ladder.
    soft = validate.soft_body()
    raw_event = validate.raw_ref(soft, "event_id")
    event = validate.event(raw_event) if raw_event is not None else None
    rec = validate.adjuster(adjuster_id)
    payload = validate.body()
    if event is None:
        validate.req_string(payload, "event_id")

    if rec["credential_status"] != "EXPIRED":
        fail("ERR_CREDENTIAL_NOT_EXPIRED")
    probe = dict(rec)
    probe["waiver_event_id"] = event["id"]
    if not sync.waiver_in_force(probe):
        fail("ERR_NO_LICENSE_WAIVER_IN_FORCE")
    if rec["employment_type"] != "INDEPENDENT":
        fail("ERR_WAIVER_NOT_ELIGIBLE")

    rec["credential_status"] = "WAIVED"
    rec["waiver_event_id"] = event["id"]
    touch(rec)
    return ok(derive.adjuster_out(rec))
