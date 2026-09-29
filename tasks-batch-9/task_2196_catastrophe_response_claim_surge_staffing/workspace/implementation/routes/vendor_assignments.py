"""VendorAssignment endpoints.  Dispatch, acceptance and completion."""
from flask import Blueprint, request

import derive
import ops
import store
import validate
from envelope import created, ok
from errors import fail
from routes.common import begin, listing, require_open_posture
from store import clock_now, touch

bp = Blueprint("vendor_assignments", __name__)

VENDOR_TYPES = ("MITIGATION", "TARP", "TREE_REMOVAL", "CONTRACTOR")


@bp.post("/vendor-assignments")
def create_job():
    begin()
    soft = validate.soft_body()
    # Existence: claim (5) precedes vendor firm (11).
    raw_claim = validate.raw_ref(soft, "claim_id")
    claim = validate.claim(raw_claim) if raw_claim is not None else None
    raw_firm = validate.raw_ref(soft, "vendor_firm_id")
    firm = validate.vendor_firm(raw_firm) if raw_firm is not None else None

    payload = validate.body()
    if claim is None:
        validate.req_string(payload, "claim_id")
    scope_amount = validate.req_number(payload, "scope_amount", exclusive_min=0)
    required_type = validate.req_enum(payload, "required_vendor_type", VENDOR_TYPES)

    event = store.events.get(claim["event_id"])
    # Position 20.
    if event is not None:
        require_open_posture(event)

    explicit = firm is not None
    if explicit:
        # Position 28 - the firm must serve the claim's loss state.
        if claim["loss_state"] not in firm["service_states"]:
            fail("ERR_VENDOR_NOT_LICENSED_IN_STATE")
        # Position 33 - concurrent-job ceiling.
        if derive.firm_open_job_count(firm["id"]) >= firm["max_concurrent_jobs"]:
            fail("ERR_VENDOR_CAPACITY_EXCEEDED")
    else:
        # Position 35 - the ranked pool must not be empty.
        firm = ops.select_vendor(claim, required_type)

    rec = store.base_record()
    rec.update({
        "claim_id": claim["id"],
        "vendor_firm_id": firm["id"],
        "scope_amount": scope_amount,
        "required_vendor_type": required_type,
        "status": "DISPATCHED",
        "dispatched_at_utc": clock_now(),
        "selection_reason": "EXPLICIT_VENDOR" if explicit else "SELECTOR_RANKED",
    })
    store.vendor_assignments[rec["id"]] = rec
    touch(claim)
    return created(derive.vendor_assignment_out(rec))


@bp.get("/vendor-assignments")
def list_jobs():
    begin()
    rows = list(store.vendor_assignments.values())
    for param, field in (("claim_id", "claim_id"),
                         ("vendor_firm_id", "vendor_firm_id"),
                         ("status", "status"),
                         ("required_vendor_type", "required_vendor_type")):
        value = request.args.get(param)
        if value is not None:
            rows = [r for r in rows if r.get(field) == value]
    return listing(rows, derive.vendor_assignment_out)


@bp.get("/vendor-assignments/<vendor_assignment_id>")
def read_job(vendor_assignment_id):
    begin()
    return ok(derive.vendor_assignment_out(
        validate.vendor_assignment(vendor_assignment_id)))


def _require_owner(rec, user_id):
    """Ladder position 17 - entity-backed VendorCoordinator identity."""
    if user_id != rec["vendor_firm_id"]:
        fail("ERR_NOT_ASSIGNED_VENDOR")


@bp.post("/vendor-assignments/<vendor_assignment_id>/accept")
def accept_job(vendor_assignment_id):
    user_id, _role = begin()
    rec = validate.vendor_assignment(vendor_assignment_id)
    _require_owner(rec, user_id)
    if rec["status"] != "DISPATCHED":
        fail("ERR_VENDOR_ASSIGNMENT_NOT_DISPATCHED")
    firm = store.vendor_firms.get(rec["vendor_firm_id"])
    if firm is not None and firm["status"] != "ACTIVATED":
        fail("ERR_VENDOR_NOT_ACTIVATED")
    # Position 33 - re-checked at acceptance time. The job being accepted is already
    # in the open population, so the ceiling is measured against the firm's OTHER
    # open jobs; otherwise an acceptance could never "drive open_job_count to exactly
    # max_concurrent_jobs" and take the firm ACTIVATED -> CAPACITY_HOLD (PRD 3.9).
    if firm is not None \
            and (derive.firm_open_job_count(firm["id"]) - 1) >= firm["max_concurrent_jobs"]:
        fail("ERR_VENDOR_CAPACITY_EXCEEDED")

    rec["status"] = "ACCEPTED"
    touch(rec)
    ops.sync_firm_capacity(firm)
    return ok(derive.vendor_assignment_out(rec))


@bp.post("/vendor-assignments/<vendor_assignment_id>/decline")
def decline_job(vendor_assignment_id):
    user_id, _role = begin()
    rec = validate.vendor_assignment(vendor_assignment_id)
    _require_owner(rec, user_id)
    if rec["status"] != "DISPATCHED":
        fail("ERR_VENDOR_ASSIGNMENT_NOT_DISPATCHED")
    rec["status"] = "DECLINED"
    touch(rec)
    ops.sync_firm_capacity(store.vendor_firms.get(rec["vendor_firm_id"]))
    return ok(derive.vendor_assignment_out(rec))


@bp.post("/vendor-assignments/<vendor_assignment_id>/complete")
def complete_job(vendor_assignment_id):
    user_id, _role = begin()
    rec = validate.vendor_assignment(vendor_assignment_id)
    _require_owner(rec, user_id)
    if rec["status"] != "ACCEPTED":
        fail("ERR_VENDOR_ASSIGNMENT_NOT_ACCEPTED")
    rec["status"] = "COMPLETED"
    touch(rec)
    ops.sync_firm_capacity(store.vendor_firms.get(rec["vendor_firm_id"]))
    return ok(derive.vendor_assignment_out(rec))


@bp.post("/vendor-assignments/<vendor_assignment_id>/cancel")
def cancel_job(vendor_assignment_id):
    begin()
    rec = validate.vendor_assignment(vendor_assignment_id)
    if rec["status"] not in ("DISPATCHED", "ACCEPTED"):
        fail("ERR_VENDOR_ASSIGNMENT_NOT_CANCELLABLE")
    rec["status"] = "CANCELLED"
    touch(rec)
    ops.sync_firm_capacity(store.vendor_firms.get(rec["vendor_firm_id"]))
    return ok(derive.vendor_assignment_out(rec))
