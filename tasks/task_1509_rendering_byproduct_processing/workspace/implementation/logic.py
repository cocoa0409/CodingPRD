"""Cross-entity business logic: posture gate, cascades, calculations."""
from decimal import Decimal

import db
from common import fail, touch, rhu, view, parse_dt

# ---------------- constants (SCAFFOLD Table 1.3) ----------------

FAT_COEFF = {
    "BOVINE": Decimal("0.16"), "PORCINE": Decimal("0.14"), "POULTRY": Decimal("0.10"),
    "OVINE": Decimal("0.15"), "MIXED": Decimal("0.12"),
}
MEAL_COEFF = {
    "BOVINE": Decimal("0.24"), "PORCINE": Decimal("0.22"), "POULTRY": Decimal("0.30"),
    "OVINE": Decimal("0.23"), "MIXED": Decimal("0.25"),
}
YIELD_TOLERANCE_PCT = 25.0
TRANSPORT_COST_PER_MILE_CENTS = 150
FREIGHT_FLAT_CENTS = 12500
GRADE_MULT = {"PREMIUM": Decimal("1.05"), "STANDARD": Decimal("1.00"), "FEED_GRADE": Decimal("0.85")}
SEVERITY_PENALTY = {"LOW": 50, "MEDIUM": 100, "HIGH": 150}
RESTRICTED_THRESHOLD = 600
RECOVERY_THRESHOLD = 700
RECOVERY_PER_PERIOD = 50
SCORE_CAP = 1000
TIER1_LIMIT = 500
TIER1_RATE = 4200
TIER2_RATE = 3800

RECIPE_SPECIES = {
    "RUMINANT_RENDER": {"BOVINE", "OVINE"},
    "PORCINE_RENDER": {"PORCINE"},
    "POULTRY_RENDER": {"POULTRY"},
    "MIXED_RENDER": {"BOVINE", "OVINE", "PORCINE"},
}
RECIPE_LOT_TYPES = {
    "RUMINANT_RENDER": ("TALLOW", "PROTEIN_MEAL"),
    "PORCINE_RENDER": ("TALLOW", "PROTEIN_MEAL"),
    "MIXED_RENDER": ("TALLOW", "PROTEIN_MEAL"),
    "POULTRY_RENDER": ("YELLOW_GREASE", "FEATHER_MEAL"),
}
FAT_TYPES = {"TALLOW", "YELLOW_GREASE"}
MEAL_TYPES = {"PROTEIN_MEAL", "FEATHER_MEAL"}

ROUTE_NONTERMINAL = ("PLANNED", "DISPATCHED", "IN_PROGRESS")
STOP_TERMINAL = ("DELIVERED", "REJECTED_AT_SITE", "MISSED", "CANCELLED", "VOIDED")


# ---------------- posture gate (priority 5) ----------------

def posture_gate(plant, kind):
    """kind: 'op' (operational mutation), 'dispatch', 'cook_start', 'admin'."""
    p = plant["posture"]
    if p == "DECOMMISSIONED":
        fail("ERR_PLANT_DECOMMISSIONED", 409, "Plant is DECOMMISSIONED; all mutations are rejected")
    if p == "SUSPENDED" and kind in ("op", "dispatch", "cook_start"):
        fail("ERR_PLANT_SUSPENDED", 409, "Plant posture is SUSPENDED")
    if p == "RESTRICTED" and kind in ("dispatch", "cook_start"):
        fail("ERR_PLANT_RESTRICTED", 409, "Plant posture is RESTRICTED")


# ---------------- lookups ----------------

def current_settlement(plant):
    for s in db.STORES["settlements"].values():
        if s["plant_id"] == plant["id"] and s["period_index"] == plant["current_period_index"]:
            return s
    return None


def active_permit(plant_id):
    for p in db.STORES["permits"].values():
        if p["plant_id"] == plant_id and p["status"] == "ACTIVE":
            return p
    return None


def batch_for_stop(stop_id):
    for b in db.STORES["batches"].values():
        if b.get("route_stop_id") == stop_id:
            return b
    return None


def stops_of_route(route_id):
    return [s for s in db.STORES["stops"].values() if s["route_id"] == route_id]


def remaining_lbs(batch):
    return batch["weight_lbs"] - batch["reserved_lbs"] - batch["consumed_lbs"]


def available_lbs(lot):
    return lot["quantity_lbs"] - lot["allocated_lbs"]


# ---------------- specialized views (computed fields) ----------------

def settlement_view(s):
    d = view(s)
    gm = (s["product_revenue_cents"] + s["pickup_fees_accrued_cents"]
          - s["energy_costs_cents"] - s["transport_costs_cents"])
    d["gross_margin_cents"] = gm
    denom = s["product_revenue_cents"] + s["pickup_fees_accrued_cents"]
    d["margin_pct"] = float(rhu(Decimal(gm) / Decimal(denom) * 100, 2)) if denom != 0 else None
    return d


def batch_view(b):
    d = view(b)
    d["remaining_lbs"] = remaining_lbs(b)
    return d


def lot_view(lot):
    d = view(lot)
    d["available_lbs"] = available_lbs(lot)
    return d


# ---------------- cascades ----------------

def void_stop_system(stop):
    """System-driven void (plant suspension/decommission cascade): reverse fee
    and transport accrual from the current-period settlement, reject batch."""
    plant = db.STORES["plants"].get(stop["plant_id"])
    fee = stop.get("final_fee_cents") or 0
    miles = stop.get("actual_distance_miles") or 0
    if plant is not None:
        st = current_settlement(plant)
        if st is not None:
            st["pickup_fees_accrued_cents"] -= fee
            st["transport_costs_cents"] -= miles * TRANSPORT_COST_PER_MILE_CENTS
            touch(st)
    sup = db.STORES["suppliers"].get(stop["supplier_id"])
    if sup is not None:
        sup["outstanding_service_fees_cents"] -= fee
        touch(sup)
    batch = batch_for_stop(stop["id"])
    if batch is not None and batch["status"] != "REJECTED":
        batch["status"] = "REJECTED"
        touch(batch)
    stop["status"] = "VOIDED"
    touch(stop)


def cancel_stop_system(stop):
    stop["status"] = "CANCELLED"
    touch(stop)


def cancel_route_system(route):
    for stop in stops_of_route(route["id"]):
        if stop["status"] in ("SCHEDULED", "ARRIVED"):
            cancel_stop_system(stop)
        elif stop["status"] == "COLLECTED":
            void_stop_system(stop)
    route["status"] = "CANCELLED"
    touch(route)


def plant_suspend(plant):
    """OPERATING/RESTRICTED -> SUSPENDED with route/stop/batch/fee cascade."""
    if plant["posture"] not in ("OPERATING", "RESTRICTED"):
        return
    plant["posture"] = "SUSPENDED"
    touch(plant)
    for route in db.STORES["routes"].values():
        if route["plant_id"] == plant["id"] and route["status"] in ROUTE_NONTERMINAL:
            cancel_route_system(route)


def release_order_allocations(order):
    for alloc in order.get("allocations") or []:
        lot = db.STORES["lots"].get(alloc["lot_id"])
        if lot is not None:
            lot["allocated_lbs"] -= alloc["quantity_lbs"]
            touch(lot)
    order["allocations"] = []


def plant_decommission_cascade(plant):
    for route in db.STORES["routes"].values():
        if route["plant_id"] == plant["id"] and route["status"] in ROUTE_NONTERMINAL:
            cancel_route_system(route)
    for order in db.STORES["orders"].values():
        if order["plant_id"] == plant["id"] and order["status"] not in ("INVOICED", "CANCELLED"):
            if order["status"] == "CONFIRMED":
                release_order_allocations(order)
            order["status"] = "CANCELLED"
            touch(order)


def cancel_supplier_open_stops(supplier_id):
    for stop in db.STORES["stops"].values():
        if stop["supplier_id"] == supplier_id and stop["status"] in ("SCHEDULED", "ARRIVED"):
            cancel_stop_system(stop)


def supplier_suspend_cascade(supplier):
    supplier["status"] = "SUSPENDED"
    touch(supplier)
    for ag in db.STORES["agreements"].values():
        if ag["supplier_id"] == supplier["id"] and ag["status"] == "ACTIVE":
            ag["status"] = "SUSPENDED"
            touch(ag)
    cancel_supplier_open_stops(supplier["id"])


def supplier_terminate_cascade(supplier):
    supplier["status"] = "TERMINATED"
    touch(supplier)
    for ag in db.STORES["agreements"].values():
        if ag["supplier_id"] == supplier["id"] and ag["status"] != "TERMINATED":
            ag["status"] = "TERMINATED"
            touch(ag)
    cancel_supplier_open_stops(supplier["id"])


def agreement_stop_cascade(agreement):
    for stop in db.STORES["stops"].values():
        if stop["agreement_id"] == agreement["id"] and stop["status"] in ("SCHEDULED", "ARRIVED"):
            cancel_stop_system(stop)


def recompute_posture_after_permit_fix(plant):
    plant["posture"] = "OPERATING" if plant["odor_score"] >= RECOVERY_THRESHOLD else "RESTRICTED"
    touch(plant)


# ---------------- calculations ----------------

def provisional_fee(agreement, est_weight, est_miles, is_dead_stock):
    fee = (agreement["pickup_base_fee_cents"]
           + est_weight * agreement["per_lb_fee_cents"]
           + est_miles * agreement["mileage_rate_cents"])
    if is_dead_stock:
        fee += agreement["dead_stock_surcharge_cents"]
    return fee


def final_fee(agreement, stop, act_weight, act_miles, plant):
    subtotal = (agreement["pickup_base_fee_cents"]
                + act_weight * agreement["per_lb_fee_cents"]
                + act_miles * agreement["mileage_rate_cents"])
    if stop["is_dead_stock"]:
        subtotal += agreement["dead_stock_surcharge_cents"]
    discount = 0
    minv = agreement["minimum_volume_lbs"]
    if minv > 0:
        volume = act_weight
        for s in db.STORES["stops"].values():
            if (s["supplier_id"] == stop["supplier_id"]
                    and s["status"] in ("COLLECTED", "DELIVERED")
                    and s.get("_collected_period") == plant["current_period_index"]):
                volume += s["actual_weight_lbs"] or 0
        if volume >= minv:
            discount = int(rhu(Decimal(subtotal) * Decimal(str(agreement["volume_discount_pct"]))))
    return subtotal - discount


def theoretical_yields(input_pairs):
    """input_pairs: list of (species, weight). Per-line round-half-up, then sum."""
    fat = 0
    meal = 0
    for species, w in input_pairs:
        fat += int(rhu(Decimal(w) * FAT_COEFF[species]))
        meal += int(rhu(Decimal(w) * MEAL_COEFF[species]))
    return fat, meal


def compute_grade(product_type, moisture, ffa, protein):
    m = Decimal(str(moisture))
    if product_type in FAT_TYPES:
        f = Decimal(str(ffa))
        if m <= Decimal("0.3") and f <= Decimal("2.0"):
            return "PREMIUM"
        if m <= Decimal("0.5") and f <= Decimal("4.0"):
            return "STANDARD"
        if m <= Decimal("1.0") and f <= Decimal("8.0"):
            return "FEED_GRADE"
        return "OFF_SPEC"
    p = Decimal(str(protein))
    if p >= Decimal("65") and m <= Decimal("8"):
        return "PREMIUM"
    if p >= Decimal("60") and m <= Decimal("10"):
        return "STANDARD"
    if p >= Decimal("55") and m <= Decimal("12"):
        return "FEED_GRADE"
    return "OFF_SPEC"


def lot_meets_spec(lot, contract):
    if lot["status"] != "RELEASED":
        return False
    if lot["product_type"] != contract["product_type"]:
        return False
    if lot["grade"] in (None, "OFF_SPEC", "UNGRADED"):
        return False
    if lot["lab_moisture_pct"] is None:
        return False
    if Decimal(str(lot["lab_moisture_pct"])) > Decimal(str(contract["spec_max_moisture_pct"])):
        return False
    if contract["product_type"] in FAT_TYPES:
        if lot["lab_ffa_pct"] is None:
            return False
        if Decimal(str(lot["lab_ffa_pct"])) > Decimal(str(contract["spec_max_ffa_pct"])):
            return False
    else:
        if lot["lab_protein_pct"] is None:
            return False
        if Decimal(str(lot["lab_protein_pct"])) < Decimal(str(contract["spec_min_protein_pct"])):
            return False
    return True


def windows_overlap(a_start, a_end, b_start, b_end):
    """Half-open [start, end) overlap: touching endpoints do not overlap."""
    return a_start < b_end and b_start < a_end
