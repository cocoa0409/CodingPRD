"""Lookups, derived projections, the two conserved ledgers and the cascades."""

import constants as C
from errors import ApiError
from services import calc
from store import db, now_iso, ordered, touch


# ------------------------------------------------------------------ lookups
def _find(table, resource_id, error_id):
    if not isinstance(resource_id, str):
        raise ApiError(error_id)
    row = table.get(resource_id)
    if row is None:
        raise ApiError(error_id)
    return row


def get_jurisdiction(resource_id):
    return _find(db.jurisdictions, resource_id, "ERR_JURISDICTION_NOT_FOUND")


def get_builder(resource_id):
    return _find(db.builders, resource_id, "ERR_BUILDER_NOT_FOUND")


def get_configuration(resource_id):
    return _find(db.configurations, resource_id, "ERR_CONFIGURATION_NOT_FOUND")


def get_quote(resource_id):
    return _find(db.quotes, resource_id, "ERR_QUOTE_NOT_FOUND")


def get_design(resource_id):
    return _find(db.designs, resource_id, "ERR_DESIGN_NOT_FOUND")


def get_drawing_package(resource_id):
    return _find(db.drawing_packages, resource_id, "ERR_DRAWING_PACKAGE_NOT_FOUND")


def get_order(resource_id):
    return _find(db.orders, resource_id, "ERR_ORDER_NOT_FOUND")


def get_production_line(resource_id):
    return _find(db.production_lines, resource_id, "ERR_LINE_NOT_FOUND")


def get_production_lot(resource_id):
    return _find(db.production_lots, resource_id, "ERR_LOT_NOT_FOUND")


def get_shipment_load(resource_id):
    return _find(db.shipment_loads, resource_id, "ERR_LOAD_NOT_FOUND")


# --------------------------------------------------------------- collections
def kits_of_configuration(configuration_id):
    return ordered(db.accessory_kits, lambda k: k["configuration_id"] == configuration_id)


def components_of_design(design_id):
    return ordered(db.components, lambda c: c["design_id"] == design_id)


def designs_of_configuration(configuration_id):
    return ordered(db.designs, lambda d: d["configuration_id"] == configuration_id)


def packages_of_design(design_id):
    return ordered(db.drawing_packages, lambda p: p["design_id"] == design_id)


def orders_of_builder(builder_id):
    return ordered(db.orders, lambda o: o["builder_id"] == builder_id)


def lots_of_order(order_id):
    return ordered(db.production_lots, lambda l: l["order_id"] == order_id)


def loads_of_order(order_id):
    return ordered(db.shipment_loads, lambda l: l["order_id"] == order_id)


def lots_of_line(line_id):
    return ordered(db.production_lots, lambda l: l["line_id"] == line_id)


# ----------------------------------------------------- builder credit ledger
def credit_available(builder):
    return builder["credit_limit_cents"] - builder["credit_used_cents"]


def move_credit(builder, delta_cents):
    builder["credit_used_cents"] = builder["credit_used_cents"] + int(delta_cents)


# --------------------------------------------- order shippable-pounds ledger
def recompute_weight_ledger(order):
    assigned = calc.D(0)
    for load in loads_of_order(order["id"]):
        if load["status"] in C.ACTIVE_LOAD_STATUSES:
            assigned += calc.D(load["gross_weight_lbs"])
    assigned = calc.rhu(assigned, 2)
    order["assigned_weight_lbs"] = assigned
    order["unassigned_weight_lbs"] = calc.rhu(
        calc.D(order["total_shippable_weight_lbs"]) - assigned, 2
    )


# ------------------------------------------------- production status rollup
def production_status_rollup(order):
    """PRD 3.8 -- branches evaluated top to bottom, first match wins."""
    if order["released_at"] is None:
        order["production_status"] = "PROD_NOT_RELEASED"
        return
    if order["permit_hold"] or order["commercial_hold"]:
        order["production_status"] = "PROD_HOLD"
        return
    active = [l for l in lots_of_order(order["id"]) if l["status"] in C.ACTIVE_LOT_STATUSES]
    if not active:
        order["production_status"] = "PROD_RELEASED"
        return
    all_complete = all(l["status"] == "COMPLETE" for l in active)
    lot_types = set(l["lot_type"] for l in active)
    if all_complete and lot_types == set(C.REQUIRED_LOT_TYPES):
        order["production_status"] = "PROD_COMPLETE"
        return
    order["production_status"] = "PROD_IN_FABRICATION"


# ------------------------------------------------------- erection sequence
def erection_sequence(order):
    loads = [l for l in loads_of_order(order["id"]) if l["status"] in C.ACTIVE_LOAD_STATUSES]
    loads.sort(key=lambda l: (l["stage_sequence"], l["_seq"]))
    planned = [l for l in loads if l["status"] == "PLANNED"]
    dispatched = [l for l in loads if l["status"] == "DISPATCHED"]
    next_stage = "NONE"
    for load in loads:
        if load["status"] == "PLANNED":
            next_stage = load["erection_stage"]
            break
    blocked = 0
    if planned:
        smallest = min(l["stage_sequence"] for l in planned)
        blocked = len([l for l in planned if l["stage_sequence"] > smallest])
    return {
        "order_id": order["id"],
        "sequence": ">".join(l["erection_stage"] for l in loads),
        "next_dispatchable_stage": next_stage,
        "planned_load_count": len(planned),
        "dispatched_load_count": len(dispatched),
        "blocked_load_count": blocked,
    }


# ------------------------------------------------------------------ cascades
def void_design_chain(design):
    """Hops 2..5 of PRD 2.10 chain one, entered from a design that must be voided."""
    design["status"] = "VOIDED"
    touch(design)
    for package in packages_of_design(design["id"]):
        if package["status"] not in ("PENDING", "SEALED"):
            continue
        package["status"] = "VOIDED"
        touch(package)
        for order in ordered(db.orders, lambda o: o["drawing_package_id"] == package["id"]):
            order["permit_hold"] = True
            order["engineering_status"] = "ENG_REWORK"
            for lot in lots_of_order(order["id"]):
                if lot["status"] == "SCHEDULED":
                    lot["status"] = "CANCELLED"
                    touch(lot)
            production_status_rollup(order)
            touch(order)


def cascade_criteria_revision(jurisdiction):
    """PRD 2.10 chain one -- five hops, one request."""
    revision = jurisdiction["criteria_revision"]
    for config in ordered(db.configurations, lambda c: c["jurisdiction_id"] == jurisdiction["id"]):
        if config["status"] != "LOCKED":
            continue
        if config["criteria_revision_at_lock"] is None:
            continue
        if config["criteria_revision_at_lock"] >= revision:
            continue
        config["status"] = "CRITERIA_STALE"
        touch(config)
        for design in designs_of_configuration(config["id"]):
            if design["status"] in C.DESIGN_NON_TERMINAL:
                void_design_chain(design)


def cascade_builder_suspension(builder):
    """PRD 2.10 chain two -- three hops, one request."""
    for order in orders_of_builder(builder["id"]):
        if order["production_status"] not in (
            "PROD_NOT_RELEASED",
            "PROD_RELEASED",
            "PROD_IN_FABRICATION",
        ):
            continue
        order["commercial_hold"] = True
        for load in loads_of_order(order["id"]):
            if load["status"] == "PLANNED":
                load["status"] = "CANCELLED"
                touch(load)
        # PRD 3.8: "Separately, the system itself cancels a SCHEDULED lot when
        # its order enters permit_hold or commercial_hold."
        for lot in lots_of_order(order["id"]):
            if lot["status"] == "SCHEDULED":
                lot["status"] = "CANCELLED"
                touch(lot)
        recompute_weight_ledger(order)
        production_status_rollup(order)
        touch(order)


def cascade_builder_reauthorization(builder):
    """PRD 2.10 -- clears commercial_hold; cancelled loads are NOT resurrected."""
    for order in orders_of_builder(builder["id"]):
        if not order["commercial_hold"]:
            continue
        order["commercial_hold"] = False
        production_status_rollup(order)
        touch(order)


# ------------------------------------------------------------------ helpers
def stamp_logical_clock():
    return now_iso()
