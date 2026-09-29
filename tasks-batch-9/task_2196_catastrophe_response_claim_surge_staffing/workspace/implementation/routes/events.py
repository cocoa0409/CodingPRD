"""CatastropheEvent endpoints and lifecycle."""
from flask import Blueprint, request

import derive
import ops
import store
import validate
from envelope import created, ok
from errors import fail
from routes.common import begin, listing
from store import clock_now, touch

bp = Blueprint("events", __name__)

PERIL_TYPES = ("HURRICANE", "WILDFIRE", "HAIL", "FLOOD", "WINTER_STORM", "EARTHQUAKE")


@bp.post("/catastrophe-events")
def create_event():
    begin()
    payload = validate.body()
    # Position 15 - schema.
    cat_code = validate.req_string(payload, "cat_code", min_len=3, max_len=24)
    peril_type = validate.req_enum(payload, "peril_type", PERIL_TYPES)
    jurisdiction_state = validate.req_state(payload, "jurisdiction_state")
    event_start = validate.req_datetime(payload, "event_start_utc")
    exposure_count = validate.req_int(payload, "exposure_count", minimum=0)
    avg_insured_value = validate.req_number(payload, "avg_insured_value", minimum=0)
    severity_index = validate.req_number(payload, "expected_severity_index",
                                         minimum=0, maximum=1)
    # Position 31 - uniqueness.
    for other in store.events.values():
        if other["cat_code"] == cat_code:
            fail("ERR_CAT_CODE_TAKEN")

    rec = store.base_record()
    rec.update({
        "cat_code": cat_code,
        "peril_type": peril_type,
        "jurisdiction_state": jurisdiction_state,
        "event_start_utc": event_start,
        "exposure_count": exposure_count,
        "avg_insured_value": avg_insured_value,
        "expected_severity_index": severity_index,
        "status": "MONITORING",
        "declared_at_utc": None,
    })
    store.events[rec["id"]] = rec
    return created(derive.event_out(rec))


@bp.get("/catastrophe-events")
def list_events():
    begin()
    rows = list(store.events.values())
    for param, field in (("status", "status"), ("peril_type", "peril_type"),
                         ("jurisdiction_state", "jurisdiction_state")):
        value = request.args.get(param)
        if value is not None:
            rows = [r for r in rows if r.get(field) == value]
    posture = request.args.get("posture")
    if posture is not None:
        rows = [r for r in rows if derive.event_posture(r) == posture]
    return listing(rows, derive.event_out)


@bp.get("/catastrophe-events/<event_id>")
def read_event(event_id):
    begin()
    rec = validate.event(event_id)
    return ok(derive.event_out(rec))


@bp.post("/catastrophe-events/<event_id>/declare")
def declare_event(event_id):
    begin()
    rec = validate.event(event_id)
    if rec["status"] != "MONITORING":
        fail("ERR_EVENT_NOT_MONITORING")
    for other in store.events.values():
        if other["id"] != rec["id"] and other["cat_code"] == rec["cat_code"]:
            fail("ERR_CAT_CODE_TAKEN")
    rec["status"] = "DECLARED"
    rec["declared_at_utc"] = clock_now()
    touch(rec)
    return ok(derive.event_out(rec))


@bp.post("/catastrophe-events/<event_id>/activate-surge")
def activate_surge(event_id):
    begin()
    rec = validate.event(event_id)
    if rec["status"] != "DECLARED":
        fail("ERR_EVENT_NOT_DECLARED")
    active_housing = [b for b in store.housing_blocks.values()
                      if b["event_id"] == rec["id"] and b["status"] == "ACTIVE"]
    if not active_housing:
        fail("ERR_NO_ACTIVE_HOUSING")
    fresh = [s for s in store.loss_estimates.values()
             if s["event_id"] == rec["id"] and not derive.snapshot_stale(s)]
    if not fresh:
        fail("ERR_LOSS_ESTIMATE_STALE")
    rec["status"] = "SURGE_ACTIVE"
    touch(rec)
    return ok(derive.event_out(rec))


@bp.post("/catastrophe-events/<event_id>/demobilize")
def demobilize_event(event_id):
    begin()
    rec = validate.event(event_id)
    if rec["status"] != "SURGE_ACTIVE":
        fail("ERR_EVENT_NOT_SURGE_ACTIVE")
    if derive.event_moratorium_active(rec["id"]):
        fail("ERR_MORATORIUM_ACTIVE")
    untriaged = [c for c in store.claims.values()
                 if c["event_id"] == rec["id"]
                 and c["handling_status"] in ("INTAKE", "TRIAGED")]
    if untriaged:
        fail("ERR_UNTRIAGED_CLAIMS_REMAIN")
    rec["status"] = "DEMOBILIZING"
    touch(rec)
    # Requested deployments never drew rooms, so occupancy is untouched.
    for d in store.deployments.values():
        if d["event_id"] == rec["id"] and d["status"] == "REQUESTED":
            d["status"] = "CANCELLED"
            touch(d)
    return ok(derive.event_out(rec))


@bp.post("/catastrophe-events/<event_id>/close")
def close_event(event_id):
    begin()
    rec = validate.event(event_id)
    if rec["status"] == "DEMOBILIZING":
        open_deployments = [d for d in store.deployments.values()
                            if d["event_id"] == rec["id"]
                            and d["status"] in ("REQUESTED", "CONFIRMED", "ON_SITE")]
        if open_deployments:
            fail("ERR_DEPLOYMENTS_STILL_OPEN")
        open_claims = [c for c in store.claims.values()
                       if c["event_id"] == rec["id"]
                       and c["handling_status"] not in ("CLOSED", "TRANSFERRED")]
        if open_claims:
            fail("ERR_CLAIMS_STILL_OPEN")
        pending_batches = [b for b in store.batches.values()
                           if b["event_id"] == rec["id"] and b["status"] != "ACCEPTED"]
        if pending_batches:
            fail("ERR_TRANSFER_BATCH_UNACCEPTED")
        rec["status"] = "CLOSED"
        touch(rec)
        ops.release_event_housing(rec["id"], ("PENDING", "ACTIVE", "EXHAUSTED"))
        ops.deactivate_event_vendors(rec["id"])
        return ok(derive.event_out(rec))

    if rec["status"] == "DECLARED":
        # Stand-down branch: strictly smaller side-effect set.
        if derive.event_open_claim_count(rec["id"]) != 0 \
                or derive.event_surge_adjuster_count(rec["id"]) != 0:
            fail("ERR_EVENT_NOT_STANDDOWN_ELIGIBLE")
        rec["status"] = "CLOSED"
        touch(rec)
        ops.release_event_housing(rec["id"], ("PENDING", "ACTIVE"))
        return ok(derive.event_out(rec))

    fail("ERR_EVENT_NOT_DEMOBILIZING")
