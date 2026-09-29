"""Lot receipt / quality holds and customer-site silos (PRD §3.5 - §3.7)."""
from datetime import timedelta

from flask import Blueprint

import calc
import domain
import envelope
import serialize
import store
import validate as v
from auth import authenticate
from common import fk_lookup, path_lookup, unique_or_fail
from errors import fail

bp = Blueprint("inventory", __name__)

LOT_STATES = ("AVAILABLE", "QUARANTINED", "DISPOSED", "EXPIRED", "DEPLETED")
LOT_READ_ROLES = ("WarehouseOperator", "QualityManager", "LogisticsPlanner",
                  "PricingController", "PlatformAdmin")
SILO_READ_ROLES = ("WarehouseOperator", "LogisticsPlanner", "CustomerBuyer", "PlatformAdmin")


# ---------------------------------------------------------------- lots ----
@bp.post("/lots")
def create_lot():
    authenticate(("WarehouseOperator",))
    body = v.body()
    lot_code = v.string(body, "lot_code", min_len=4, max_len=32)
    product_id = v.string(body, "product_id", min_len=1)
    zone_id = v.string(body, "zone_id", min_len=1)
    manufactured_on = v.date(body, "manufactured_on")
    quantity = v.number(body, "quantity_received_lb", exclusive_min=0)
    product = fk_lookup("products", product_id)
    zone = fk_lookup("zones", zone_id)
    if zone["allergen_class"] != product["allergen_class"]:
        fail("ERR_ALLERGEN_ZONE_MISMATCH",
             "Zone allergen class %s does not match product allergen class %s"
             % (zone["allergen_class"], product["allergen_class"]))
    if domain.zone_in_lockout(zone):
        fail("ERR_ZONE_LOCKOUT_CONFLICT",
             "The destination zone is inside its sanitation lockout window")
    unique_or_fail("lots", "lot_code", lot_code)
    rec = store.base_record()
    rec.update({
        "lot_code": lot_code,
        "product_id": product_id,
        "zone_id": zone_id,
        "manufactured_on": manufactured_on,
        "expires_on": manufactured_on + timedelta(days=product["shelf_life_days"]),
        "quantity_received_lb": store.lb(quantity),
        "quantity_on_hand_lb": store.lb(quantity),
        "quantity_reserved_lb": store.D("0.00"),
        "quantity_consumed_lb": store.D("0.00"),
        "status": "AVAILABLE",
        "quarantine_reason": None,
    })
    store.insert("lots", rec)
    calc.recompute_zone_on_hand(zone)
    return envelope.created(serialize.lot(rec))


@bp.get("/lots")
def list_lots():
    authenticate(LOT_READ_ROLES)
    limit, offset = v.pagination()
    product_id = v.q_str("product_id")
    zone_id = v.q_str("zone_id")
    status = v.q_enum("status", LOT_STATES)
    rows = [l for l in store.all_of("lots")
            if (product_id is None or l["product_id"] == product_id)
            and (zone_id is None or l["zone_id"] == zone_id)
            and (status is None or l["status"] == status)]
    rows.sort(key=lambda l: (l["expires_on"], l["created_at"], l["_seq"]))
    data, total = v.page(rows, limit, offset, serialize.lot)
    return envelope.listing(data, limit, offset, total)


@bp.get("/lots/<lid>")
def read_lot(lid):
    authenticate(LOT_READ_ROLES)
    return envelope.ok(serialize.lot(path_lookup("lots", lid)))


@bp.post("/lots/<lid>/quarantine")
def quarantine_lot(lid):
    authenticate(("QualityManager",))
    body = v.body()
    reason = v.string(body, "quarantine_reason", min_len=1, max_len=200)
    lot = path_lookup("lots", lid)
    if lot["status"] != "AVAILABLE":
        fail("ERR_INVALID_STATE_TRANSITION",
             "A lot in %s cannot be quarantined" % lot["status"])
    domain.lot_release_cascade(lot)
    lot["status"] = "QUARANTINED"
    lot["quarantine_reason"] = reason
    store.bump(lot)
    calc.recompute_zone_on_hand(store.get("zones", lot["zone_id"]))
    return envelope.ok(serialize.lot(lot))


@bp.post("/lots/<lid>/release")
def release_lot(lid):
    authenticate(("QualityManager",))
    v.body()
    lot = path_lookup("lots", lid)
    if lot["status"] != "QUARANTINED":
        fail("ERR_INVALID_STATE_TRANSITION",
             "A lot in %s cannot be released" % lot["status"])
    zone = store.get("zones", lot["zone_id"])
    if zone is not None and domain.zone_in_lockout(zone):
        fail("ERR_ZONE_LOCKOUT_CONFLICT",
             "The storage zone is inside its sanitation lockout window")
    if zone is None or zone["status"] != "OPEN":
        fail("ERR_RELATED_ENTITY_STATE_INVALID", "The storage zone is not OPEN")
    if not (store.day_of(lot["expires_on"]) > store.clock_date()):
        fail("ERR_INVALID_STATE_TRANSITION",
             "An expired lot cannot be returned to the pick face")
    lot["status"] = "AVAILABLE"
    lot["quarantine_reason"] = None
    store.bump(lot)
    calc.recompute_zone_on_hand(zone)
    return envelope.ok(serialize.lot(lot))


@bp.post("/lots/<lid>/dispose")
def dispose_lot(lid):
    authenticate(("QualityManager",))
    body = v.body()
    v.string(body, "disposal_note", required=False)
    lot = path_lookup("lots", lid)
    if lot["status"] != "QUARANTINED":
        fail("ERR_INVALID_STATE_TRANSITION",
             "A lot in %s cannot be disposed" % lot["status"])
    if store.lb(lot["quantity_reserved_lb"]) != 0:
        fail("ERR_INVALID_STATE_TRANSITION",
             "A lot with reserved pounds cannot be written off")
    lot["quantity_consumed_lb"] = store.lb(
        store.D(lot["quantity_consumed_lb"]) + store.D(lot["quantity_on_hand_lb"]))
    lot["quantity_on_hand_lb"] = store.D("0.00")
    lot["status"] = "DISPOSED"
    store.bump(lot)
    calc.recompute_zone_on_hand(store.get("zones", lot["zone_id"]))
    return envelope.ok(serialize.lot(lot))


# --------------------------------------------------------------- silos ----
@bp.post("/silos")
def create_silo():
    authenticate(("WarehouseOperator",))
    body = v.body()
    silo_code = v.string(body, "silo_code", min_len=2, max_len=16)
    customer_id = v.string(body, "customer_id", min_len=1)
    product_id = v.string(body, "product_id", min_len=1)
    capacity = v.number(body, "capacity_lb", minimum=1000)
    min_fill = v.number(body, "min_fill_lb", required=False, minimum=0,
                        default=store.D("2000"))
    fk_lookup("customers", customer_id)
    product = fk_lookup("products", product_id)
    unique_or_fail("silos", "silo_code", silo_code)
    if calc.find_silo(customer_id, product_id) is not None:
        fail("ERR_DUPLICATE_RESOURCE",
             "A silo for this bakery and SKU already exists")
    if not product["bulk_capable"]:
        fail("ERR_PRODUCT_NOT_BULK_CAPABLE",
             "A silo may only be dedicated to a bulk-capable SKU")
    rec = store.base_record()
    rec.update({
        "silo_code": silo_code,
        "customer_id": customer_id,
        "product_id": product_id,
        "capacity_lb": store.lb(capacity),
        "residual_lb": store.D("0.00"),
        "min_fill_lb": store.lb(min_fill),
        "last_fill_window_start_at": None,
        "last_fill_window_end_at": None,
    })
    store.insert("silos", rec)
    return envelope.created(serialize.silo(rec))


@bp.get("/silos")
def list_silos():
    authenticate(SILO_READ_ROLES)
    limit, offset = v.pagination()
    customer_id = v.q_str("customer_id")
    product_id = v.q_str("product_id")
    rows = [s for s in store.all_of("silos")
            if (customer_id is None or s["customer_id"] == customer_id)
            and (product_id is None or s["product_id"] == product_id)]
    rows = store.sort_created(rows)
    data, total = v.page(rows, limit, offset, serialize.silo)
    return envelope.listing(data, limit, offset, total)


@bp.get("/silos/<sid>")
def read_silo(sid):
    authenticate(SILO_READ_ROLES)
    return envelope.ok(serialize.silo(path_lookup("silos", sid)))


@bp.post("/silos/<sid>/residual-readings")
def silo_reading(sid):
    authenticate(("WarehouseOperator", "CustomerBuyer"))
    body = v.body()
    measured = v.number(body, "measured_residual_lb", minimum=0)
    silo = path_lookup("silos", sid)
    if measured > store.D(silo["capacity_lb"]):
        v.bad("measured_residual_lb must be <= the silo capacity")
    silo["residual_lb"] = store.lb(measured)
    store.bump(silo)
    return envelope.ok(serialize.silo(silo))
