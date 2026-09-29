"""LossEstimateSnapshot endpoints.  Optimistic concurrency on the event version."""
from flask import Blueprint, request

import calc
import derive
import store
import validate
from envelope import created, ok
from errors import fail
from routes.common import begin, listing
from store import clock_now, touch

bp = Blueprint("loss_estimates", __name__)

METHODS = ("EXPOSURE_BASED", "INCURRED_DEVELOPMENT")


def _reported_claim_count(event_id):
    """Distinct claims among the event's INITIAL_CASE ledger entries."""
    seen = set()
    for entry in store.reserve_entries.values():
        if entry["event_id"] == event_id and entry["entry_type"] == "INITIAL_CASE":
            seen.add(entry["claim_id"])
    return len(seen)


@bp.post("/loss-estimates")
def create_snapshot():
    begin()
    soft = validate.soft_body()
    raw_event = validate.raw_ref(soft, "event_id")
    event = validate.event(raw_event) if raw_event is not None else None
    payload = validate.body()
    if event is None:
        validate.req_string(payload, "event_id")
    method = validate.req_enum(payload, "method", METHODS)
    expected = validate.req_int(payload, "expected_event_version")
    # Position 18 - optimistic concurrency on the event's version.
    if expected != event["version"]:
        fail("ERR_STALE_EVENT_VERSION")

    reported_component = derive.event_incurred_total(event["id"])
    reported, ibnr, gross = calc.event_loss_estimate(
        event, method, reported_component, _reported_claim_count(event["id"]))

    rec = store.base_record(with_common=False)
    rec.update({
        "event_id": event["id"],
        "method": method,
        "gross_estimate": gross,
        "ibnr_component": ibnr,
        "reported_component": reported,
        "input_reserve_sequence_high_water": derive.sequence_high_water(event["id"]),
        "computed_at_utc": clock_now(),
    })
    store.loss_estimates[rec["id"]] = rec
    # Minting refreshes gross_loss_estimate and recomputes posture (both derived).
    touch(event)
    return created(derive.loss_estimate_out(rec))


@bp.get("/loss-estimates")
def list_snapshots():
    begin()
    rows = list(store.loss_estimates.values())
    for param, field in (("event_id", "event_id"), ("method", "method")):
        value = request.args.get(param)
        if value is not None:
            rows = [r for r in rows if r.get(field) == value]
    stale = validate.query_bool("stale")
    if stale is not None:
        rows = [r for r in rows if derive.snapshot_stale(r) is stale]
    return listing(rows, derive.loss_estimate_out, sort_key="computed_at_utc")


@bp.get("/loss-estimates/<snapshot_id>")
def read_snapshot(snapshot_id):
    begin()
    return ok(derive.loss_estimate_out(validate.loss_estimate(snapshot_id)))
