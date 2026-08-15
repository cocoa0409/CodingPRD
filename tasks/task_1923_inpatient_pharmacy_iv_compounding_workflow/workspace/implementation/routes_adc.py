"""ADC stations, pockets, the inventory ledger, and dispensing (Section 3.6)."""

from flask import Blueprint, request

import db
import validate as V
import calc
import ops
from auth import authenticate, ALL_ROLES
from errors import (
    err_not_found, err_stale_version, err_invalid_state, err_order_terminal,
    err_invalid_request, err_invalid_quantity, err_pocket_capacity,
    err_insufficient_stock, err_drug_mismatch, err_pocket_quarantined,
    err_witness_required, err_witness_self, err_order_not_verified,
    err_prep_not_qa, err_bud_expired,
)
from response import ok, ok_list, serialize, paginate

bp = Blueprint("adc", __name__)

DISCREPANCY_THRESHOLD = {"C_II": 2}
DEFAULT_DISCREPANCY_THRESHOLD = 5


# ---------------------------------------------------------------------------
# Stations & pockets
# ---------------------------------------------------------------------------

@bp.post("/pharmacy/adc-stations")
def create_station():
    authenticate(["PharmacyAdmin"])
    d = V.body()
    station = db.base_fields()
    station.update({
        "name": V.req_str(d, "name"),
        "zone": V.req_str(d, "zone"),
    })
    db.stations[station["id"]] = station
    return ok(serialize(station), 201)


@bp.get("/pharmacy/adc-stations/<sid>")
def get_station(sid):
    authenticate(ALL_ROLES)
    s = db.stations.get(sid)
    if s is None:
        raise err_not_found("ADC station not found")
    return ok(serialize(s))


@bp.get("/pharmacy/adc-stations")
def list_stations():
    authenticate(ALL_ROLES)
    items = list(db.stations.values())
    zone = request.args.get("zone")
    if zone is not None:
        items = [s for s in items if s["zone"] == zone]
    page, meta = paginate(items, request.args)
    return ok_list(page, meta)


@bp.post("/pharmacy/adc-stations/<sid>/pockets")
def create_pocket(sid):
    authenticate(["PharmacyAdmin"])
    d = V.body()
    drug_product_id = V.req_str(d, "drug_product_id")
    max_units = V.req_int(d, "max_units")
    station = db.stations.get(sid)
    if station is None:
        raise err_not_found("ADC station not found")
    if drug_product_id not in db.drugs:
        raise err_not_found("Drug product not found")
    if max_units < 1:
        raise err_invalid_quantity("max_units must be at least 1")
    pocket = db.base_fields()
    pocket.update({
        "station_id": sid,
        "drug_product_id": drug_product_id,
        "max_units": max_units,
        "on_hand_units": 0,
        "status": "ACTIVE",
        "pick_blocked": False,
    })
    db.pockets[pocket["id"]] = pocket
    return ok(serialize(pocket), 201)


@bp.get("/pharmacy/adc-stations/<sid>/pockets")
def list_station_pockets(sid):
    authenticate(ALL_ROLES)
    if sid not in db.stations:
        raise err_not_found("ADC station not found")
    items = [p for p in db.pockets.values() if p["station_id"] == sid]
    page, meta = paginate(items, request.args)
    return ok_list(page, meta)


def _get_pocket(pid):
    p = db.pockets.get(pid)
    if p is None:
        raise err_not_found("ADC pocket not found")
    return p


@bp.get("/pharmacy/adc-pockets/<pid>")
def get_pocket(pid):
    authenticate(ALL_ROLES)
    return ok(serialize(_get_pocket(pid)))


@bp.get("/pharmacy/adc-pockets")
def list_pockets():
    authenticate(ALL_ROLES)
    items = list(db.pockets.values())
    drug = request.args.get("drug_product_id")
    if drug is not None:
        items = [p for p in items if p["drug_product_id"] == drug]
    status = request.args.get("status")
    if status is not None:
        items = [p for p in items if p["status"] == status]
    page, meta = paginate(items, request.args)
    return ok_list(page, meta)


# ---------------------------------------------------------------------------
# Ledger mutations
# ---------------------------------------------------------------------------

@bp.post("/pharmacy/adc-pockets/<pid>/restock")
def restock_pocket(pid):
    uid, _, _ = authenticate(["PharmacyTechnician"])
    d = V.body()
    units = V.req_int(d, "units")
    expected_pocket_version = V.occ_field(d, "expected_pocket_version", required=True)
    pocket = _get_pocket(pid)
    if expected_pocket_version != pocket["version"]:
        raise err_stale_version("expected_pocket_version does not match the pocket version")
    if units < 1:
        raise err_invalid_quantity("units must be at least 1")
    if pocket["on_hand_units"] + units > pocket["max_units"]:
        raise err_pocket_capacity()
    ops.append_event(pocket, "RESTOCK", units, uid)
    db.touch(pocket)
    return ok(serialize(pocket))


@bp.post("/pharmacy/adc-pockets/<pid>/dispense")
def dispense_pocket(pid):
    uid, _, _ = authenticate(["Nurse"])
    d = V.body()
    order_id = V.req_str(d, "order_id")
    units = V.req_int(d, "units")
    pocket = _get_pocket(pid)
    order = db.orders.get(order_id)
    if order is None:
        raise err_not_found("Medication order not found")
    # Expiry sweeps are evaluated before any dispense is processed.
    ops.run_expiry_sweeps(uid)
    if ops.order_is_terminal(order):
        raise err_order_terminal()
    if units < 1:
        raise err_invalid_quantity("units must be at least 1")
    if pocket["on_hand_units"] < units:
        raise err_insufficient_stock()
    if pocket["drug_product_id"] != order["drug_product_id"]:
        raise err_drug_mismatch()
    if order["verification_status"] != "VERIFIED":
        raise err_order_not_verified()
    linked_prep = None
    if order["route"] == "IV":
        candidates = [
            p for p in calc.batch_preparations_by_order(order["id"])
            if p["status"] == "QA_PASSED"
        ]
        if not candidates:
            raise err_prep_not_qa()
        linked_prep = candidates[0]
        if not (db.now() < linked_prep["bud_expiry"]):
            raise err_bud_expired()
    if pocket["status"] != "ACTIVE":
        raise err_pocket_quarantined()
    if order["fulfillment_status"] != "READY":
        raise err_invalid_state("Order fulfillment_status is not READY")

    ops.append_event(pocket, "DISPENSE", -units, uid, order_id=order["id"])
    db.touch(pocket)
    order["fulfillment_status"] = "DISPENSED"
    db.touch(order)
    if linked_prep is not None:
        linked_prep["status"] = "DISPENSED"
        db.touch(linked_prep)
        batch = db.batches.get(linked_prep["batch_id"])
        if batch is not None:
            ops.recompute_batch_derived(batch)
            db.touch(batch)
    return ok(serialize(pocket))


@bp.post("/pharmacy/adc-pockets/<pid>/return")
def return_pocket(pid):
    uid, _, _ = authenticate(["Nurse"])
    d = V.body()
    units = V.req_int(d, "units")
    order_id = V.opt_str(d, "order_id")
    pocket = _get_pocket(pid)
    order = None
    if order_id is not None:
        order = db.orders.get(order_id)
        if order is None:
            raise err_not_found("Medication order not found")
    if units < 1:
        raise err_invalid_quantity("units must be at least 1")
    if order is not None and pocket["drug_product_id"] != order["drug_product_id"]:
        raise err_drug_mismatch()
    ops.append_event(pocket, "RETURN", units, uid,
                     order_id=order["id"] if order else None)
    db.touch(pocket)
    return ok(serialize(pocket))


@bp.post("/pharmacy/adc-pockets/<pid>/waste")
def waste_pocket(pid):
    uid, _, _ = authenticate(["PharmacyTechnician", "Pharmacist"])
    d = V.body()
    units = V.req_int(d, "units")
    witness_staff_id = V.opt_str(d, "witness_staff_id")
    pocket = _get_pocket(pid)
    if witness_staff_id is not None and witness_staff_id not in db.staff:
        raise err_not_found("Witness staff member not found")
    drug = db.drugs[pocket["drug_product_id"]]
    # Safety tier: witness presence (13) before self-witness (14).
    if drug["schedule"] == "C_II" and witness_staff_id is None:
        raise err_witness_required()
    if witness_staff_id is not None and witness_staff_id == uid:
        raise err_witness_self()
    if units < 1:
        raise err_invalid_quantity("units must be at least 1")
    if pocket["on_hand_units"] < units:
        raise err_insufficient_stock()
    ops.append_event(pocket, "WASTE", -units, uid, witness_staff_id=witness_staff_id)
    ops.append_waste_record(
        recorded_by=uid, reason="ADC_WASTE",
        pocket_id=pocket["id"], units=units, witness_staff_id=witness_staff_id,
    )
    db.touch(pocket)
    return ok(serialize(pocket))


@bp.post("/pharmacy/adc-pockets/<pid>/count")
def count_pocket(pid):
    uid, _, _ = authenticate(["Pharmacist"])
    d = V.body()
    physical_count_units = V.req_int(d, "physical_count_units")
    pocket = _get_pocket(pid)
    if physical_count_units < 0:
        raise err_invalid_quantity("physical_count_units must be non-negative")
    expected = ops.replay_on_hand(pocket["id"])
    ev = ops.append_event(
        pocket, "COUNT", 0, uid, observed_count_units=physical_count_units
    )
    variance = physical_count_units - expected
    threshold = DISCREPANCY_THRESHOLD.get(
        db.drugs[pocket["drug_product_id"]]["schedule"],
        DEFAULT_DISCREPANCY_THRESHOLD,
    )
    case_id = None
    if abs(variance) >= threshold:
        case = db.base_fields()
        case.update({
            "pocket_id": pocket["id"],
            "variance_units": variance,
            "status": "OPEN",
            "resolution": None,
            "adjustment_units": None,
            "resolved_by_staff_id": None,
        })
        db.discrepancies[case["id"]] = case
        case_id = case["id"]
    return ok({
        "variance_units": variance,
        "expected_on_hand_units": expected,
        "discrepancy_case_id": case_id,
        "event_id": ev["id"],
    })


@bp.post("/pharmacy/adc-pockets/<pid>/quarantine")
def quarantine_pocket(pid):
    authenticate(["Pharmacist"])
    V.body()
    pocket = _get_pocket(pid)
    if pocket["status"] != "ACTIVE":
        raise err_invalid_state("Pocket is not ACTIVE")
    pocket["status"] = "QUARANTINED"
    db.touch(pocket)
    return ok(serialize(pocket))


@bp.post("/pharmacy/adc-pockets/<pid>/release-quarantine")
def release_quarantine_pocket(pid):
    authenticate(["Pharmacist"])
    V.body()
    pocket = _get_pocket(pid)
    if pocket["status"] != "QUARANTINED":
        raise err_invalid_state("Pocket is not QUARANTINED")
    pocket["status"] = "ACTIVE"
    db.touch(pocket)
    return ok(serialize(pocket))


# ---------------------------------------------------------------------------
# Ledger & per-pocket case reads
# ---------------------------------------------------------------------------

@bp.get("/pharmacy/adc-pockets/<pid>/events")
def list_pocket_events(pid):
    authenticate(ALL_ROLES)
    pocket = _get_pocket(pid)
    items = [e for e in db.events.values() if e["pocket_id"] == pocket["id"]]
    page, meta = paginate(items, request.args)
    return ok_list(page, meta)


@bp.get("/pharmacy/adc-pockets/<pid>/discrepancy-cases")
def list_pocket_discrepancies(pid):
    authenticate(ALL_ROLES)
    pocket = _get_pocket(pid)
    items = [c for c in db.discrepancies.values() if c["pocket_id"] == pocket["id"]]
    page, meta = paginate(items, request.args)
    return ok_list(page, meta)


@bp.get("/pharmacy/inventory-events/<eid>")
def get_event(eid):
    authenticate(ALL_ROLES)
    ev = db.events.get(eid)
    if ev is None:
        raise err_not_found("Inventory event not found")
    return ok(serialize(ev))


@bp.get("/pharmacy/inventory-events")
def list_events():
    authenticate(ALL_ROLES)
    items = list(db.events.values())
    for param in ("order_id", "recorded_by_staff_id", "witness_staff_id", "event_type"):
        v = request.args.get(param)
        if v is not None:
            items = [e for e in items if e[param] == v]
    page, meta = paginate(items, request.args)
    return ok_list(page, meta)
