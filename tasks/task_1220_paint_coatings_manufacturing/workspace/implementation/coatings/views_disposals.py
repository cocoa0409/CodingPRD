"""Disposal request endpoints: create, manifest, complete, cancel."""
from decimal import Decimal

from flask import Blueprint

from .domain import (
    DISPOSAL_REASONS,
    MANIFEST_FEE_CENTS,
    PAIL_RECOVERY_CENTS,
    QUANTITY_TOLERANCE_PCT,
    RATE_HAZMAT_CENTS_PER_KG,
    RATE_NONHAZMAT_CENTS_PER_KG,
    RECOVERY_CAP_PCT,
    batch_is_hazmat,
    ser_disposal_request,
)
from .errors import bad_request, conflict, invalid_state, not_found, unprocessable
from .store import store
from .util import D, auth, body, new_record, round0, success, touch, v_arr, v_enum, v_num, v_str

bp = Blueprint("disposals", __name__)

ALL = ("PlantManager", "LabTechnician", "ProductionOperator", "QCInspector", "RegulatoryClerk", "Dealer")

CONTAINER_DISPOSABLE = ("OBSOLETE", "RETURNED", "REJECTED")


@bp.post("/coatings/disposal-requests")
def create_disposal():
    auth(("RegulatoryClerk",))
    b = body()
    reason = v_enum(b, "reason", DISPOSAL_REASONS)
    container_ids = v_arr(b, "container_ids")
    batch_ids = v_arr(b, "batch_ids", required=False) or []
    for i, v in enumerate(container_ids):
        if not isinstance(v, str):
            raise bad_request("container_ids[%d] must be a string" % i)
    for i, v in enumerate(batch_ids):
        if not isinstance(v, str):
            raise bad_request("batch_ids[%d] must be a string" % i)
    if len(container_ids) == 0 and len(batch_ids) == 0:
        raise bad_request("Disposal request must reference at least one container or batch")
    # gate 4: existence, containers first then batches
    containers = []
    for cid in container_ids:
        c = store.containers.get(cid)
        if c is None:
            raise not_found()
        containers.append(c)
    batches = []
    for bid in batch_ids:
        bt = store.batches.get(bid)
        if bt is None:
            raise not_found()
        batches.append(bt)
    # gate 6: state preconditions
    for c in containers:
        if c["status"] not in CONTAINER_DISPOSABLE:
            raise invalid_state("Container %s is not disposable from %s" % (c["id"], c["status"]))
    for bt in batches:
        if bt["status"] != "DISPOSAL_PENDING":
            raise invalid_state("Batch %s is not DISPOSAL_PENDING" % bt["id"])
    # side effects: containers move to DISPOSAL_PENDING with pre-state stored
    rec = new_record()
    rec.update({
        "reason": reason,
        "container_ids": list(container_ids),
        "batch_ids": list(batch_ids),
        "hazmat_class": "NON_HAZARDOUS",
        "manifest_no": None,
        "expected_destroyed_kg": Decimal("0"),
        "actual_destroyed_kg": None,
        "gross_cost_cents": None,
        "recovery_credit_cents": None,
        "net_cost_cents": None,
        "status": "REQUESTED",
    })
    hazmat = False
    expected = Decimal("0")
    for c in containers:
        c["pre_disposal_status"] = c["status"]
        c["status"] = "DISPOSAL_PENDING"
        c["disposal_request_id"] = rec["id"]
        touch(c)
        expected += c["net_weight_kg"]
        batch = store.batches.get(c["batch_id"])
        if batch is not None and batch_is_hazmat(batch):
            hazmat = True
    rec["hazmat_class"] = "HAZARDOUS" if hazmat else "NON_HAZARDOUS"
    rec["expected_destroyed_kg"] = expected
    store.disposal_requests[rec["id"]] = rec
    return success(ser_disposal_request(rec), 201)


@bp.get("/coatings/disposal-requests/<rid>")
def get_disposal(rid):
    auth(ALL)
    rec = store.disposal_requests.get(rid)
    if rec is None:
        raise not_found()
    return success(ser_disposal_request(rec), 200)


@bp.post("/coatings/disposal-requests/<rid>/manifest")
def manifest_disposal(rid):
    auth(("RegulatoryClerk",))
    b = body()
    manifest_no = v_str(b, "manifest_no")
    rec = store.disposal_requests.get(rid)
    if rec is None:
        raise not_found()
    if rec["status"] != "REQUESTED":
        raise invalid_state("Disposal request is not REQUESTED")
    for other in store.disposal_requests.values():
        if other["id"] != rid and other["status"] != "CANCELLED" and other["manifest_no"] == manifest_no:
            raise conflict("ERR_DUPLICATE_CODE", "manifest_no already used by a non-CANCELLED request")
    rec["manifest_no"] = manifest_no
    rec["status"] = "MANIFESTED"
    touch(rec)
    return success(ser_disposal_request(rec), 200)


@bp.post("/coatings/disposal-requests/<rid>/complete")
def complete_disposal(rid):
    auth(("PlantManager",))
    b = body()
    actual_destroyed_kg = v_num(b, "actual_destroyed_kg", minv=0)
    rec = store.disposal_requests.get(rid)
    if rec is None:
        raise not_found()
    if rec["status"] == "MANIFESTED":
        pass
    elif rec["status"] == "REQUESTED":
        if rec["hazmat_class"] != "NON_HAZARDOUS":
            raise invalid_state("HAZARDOUS requests must pass through MANIFESTED first")
    else:
        raise invalid_state("Disposal request cannot be completed from %s" % rec["status"])
    expected = rec["expected_destroyed_kg"]
    if expected == 0:
        if D(actual_destroyed_kg) != 0:
            raise unprocessable("ERR_DISPOSAL_QUANTITY_MISMATCH", "Nothing was expected to be destroyed")
    else:
        deviation = abs(D(actual_destroyed_kg) - expected) / expected * Decimal("100")
        if deviation > D(QUANTITY_TOLERANCE_PCT):
            raise unprocessable("ERR_DISPOSAL_QUANTITY_MISMATCH", "Destroyed quantity deviates by more than 2%")
    # side effects: containers and batches disposed; batch mill reservations released
    touched_mills = set()
    for cid in rec["container_ids"]:
        c = store.containers.get(cid)
        if c is not None and c["status"] == "DISPOSAL_PENDING":
            c["status"] = "DISPOSED"
            touch(c)
    for bid in rec["batch_ids"]:
        bt = store.batches.get(bid)
        if bt is not None and bt["status"] == "DISPOSAL_PENDING":
            bt["status"] = "DISPOSED"
            touch(bt)
            if bt["mill_id"] not in touched_mills:
                touched_mills.add(bt["mill_id"])
                mill = store.mills.get(bt["mill_id"])
                if mill is not None:
                    touch(mill)  # reservation released
    rate = RATE_HAZMAT_CENTS_PER_KG if rec["hazmat_class"] == "HAZARDOUS" else RATE_NONHAZMAT_CENTS_PER_KG
    gross = round0(D(rate) * expected) + MANIFEST_FEE_CENTS
    pails = 0
    for cid in rec["container_ids"]:
        c = store.containers.get(cid)
        if c is not None and c["size_code"] == "FIVE_GALLON":
            pails += 1
    recovery = min(PAIL_RECOVERY_CENTS * pails, round0(RECOVERY_CAP_PCT * D(gross)))
    rec["actual_destroyed_kg"] = actual_destroyed_kg
    rec["gross_cost_cents"] = gross
    rec["recovery_credit_cents"] = recovery
    rec["net_cost_cents"] = gross - recovery
    rec["status"] = "DISPOSED"
    touch(rec)
    return success(ser_disposal_request(rec), 200)


@bp.post("/coatings/disposal-requests/<rid>/cancel")
def cancel_disposal(rid):
    auth(("RegulatoryClerk",))
    rec = store.disposal_requests.get(rid)
    if rec is None:
        raise not_found()
    if rec["status"] != "REQUESTED":
        raise invalid_state("Only a REQUESTED disposal can be cancelled")
    for cid in rec["container_ids"]:
        c = store.containers.get(cid)
        if c is not None and c["status"] == "DISPOSAL_PENDING" and c.get("disposal_request_id") == rid:
            c["status"] = c["pre_disposal_status"]
            c["pre_disposal_status"] = None
            c["disposal_request_id"] = None
            touch(c)
    rec["status"] = "CANCELLED"
    touch(rec)
    return success(ser_disposal_request(rec), 200)
