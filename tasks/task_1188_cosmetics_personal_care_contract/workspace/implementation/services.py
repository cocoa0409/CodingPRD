"""Business logic: serializers, calculation rules (PRD section 3), state-machine
cascades, and cross-aggregate helpers. Monetary math uses Decimal with
ROUND_HALF_UP; per-line rounding is pinned before summation where specified."""
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from core import new_entity, touch
from store import db, parse_dt

# ---------------------------------------------------------------------------
# Constants from SCAFFOLD calculations
# ---------------------------------------------------------------------------
LAB_REFERENCE_KG = 50
SCALE_UP_APPROVAL_THRESHOLD = 10
MAX_IPC_FAILURES = 3
TIGHTENING_PER_FAILURE = Decimal("0.10")
TIGHTENING_FLOOR = Decimal("0.5")

FEE_TIER1_MAX_UNITS = 5000
FEE_TIER1_RATE_CENTS = 50
FEE_TIER2_MAX_UNITS = 20000
FEE_TIER2_RATE_CENTS = 40
FEE_TIER3_RATE_CENTS = 30
PRESTIGE_RATE_DISCOUNT_CENTS = 5

SURCHARGE_BRACKET_CENTS = 1000000
SURCHARGE_LOW = Decimal("0.02")
SURCHARGE_HIGH = Decimal("0.05")

SAME_FORMULA_MINUTES = 0
SAME_CLASS_MINUTES = 15
DIFFERENT_CLASS_MINUTES = 45
ALLERGEN_CROSS_MINUTES = 120
FRAGRANCE_CARRYOVER_MINUTES = 30
MAX_CHANGEOVER_MINUTES = 180

RAW_KINDS = {"RAW_MATERIAL", "BULK_FRAGRANCE", "COLORANT"}

REQUIRED_INTERVALS = {
    "PRESERVATIVE_EFFICACY": [28],
    "ACCELERATED": [30, 60, 90],
    "REAL_TIME": [90, 180, 365],
}


# ---------------------------------------------------------------------------
# Numeric helpers
# ---------------------------------------------------------------------------


def D(value):
    """Exact Decimal from an int/float/str input."""
    return Decimal(str(value))


def cents_round(d):
    """Round-half-up to integer cents."""
    return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def num(value):
    """Serialize a stored numeric as int when integral else float."""
    d = D(value)
    if d == d.to_integral_value():
        return int(d)
    return float(d)


def floor_div(a, b):
    """floor(a / b) computed exactly."""
    return int(D(a) // D(b))


# ---------------------------------------------------------------------------
# Entity lookup helpers (404 on miss)
# ---------------------------------------------------------------------------


def must_get(table, entity_id, label="Resource"):
    from core import ApiError
    ent = table.get(entity_id) if isinstance(entity_id, str) else None
    if ent is None:
        raise ApiError("ERR_NOT_FOUND", 404, f"{label} not found: {entity_id}")
    return ent


def lot_unexpired(lot):
    exp = parse_dt(lot["expires_at"])
    return exp is not None and exp > db.clock


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------


def serialize_customer(c):
    return {
        "id": c["id"],
        "name": c["name"],
        "tier": c["tier"],
        "minimum_run_units": c["minimum_run_units"],
        "credit_limit_cents": c["credit_limit_cents"],
        "outstanding_balance_cents": c["outstanding_balance_cents"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def serialize_component(c):
    return {
        "id": c["id"],
        "name": c["name"],
        "kind": c["kind"],
        "supply_mode": c["supply_mode"],
        "customer_id": c["customer_id"],
        "standard_cost_per_kg_cents": num(c["standard_cost_per_kg_cents"]),
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def serialize_lot(lot):
    return {
        "id": lot["id"],
        "component_id": lot["component_id"],
        "lot_code": lot["lot_code"],
        "quantity_received": num(lot["quantity_received"]),
        "quantity_available": num(lot["quantity_available"]),
        "quantity_reserved": num(lot["quantity_reserved"]),
        "quantity_consumed": num(lot["quantity_consumed"]),
        "unit_cost_per_kg_cents": (None if lot["unit_cost_per_kg_cents"] is None
                                   else num(lot["unit_cost_per_kg_cents"])),
        "expires_at": lot["expires_at"],
        "sensorial_profile": lot["sensorial_profile"],
        "variant_waiver": lot["variant_waiver"],
        "status": lot["status"],
        "created_at": lot["created_at"],
        "updated_at": lot["updated_at"],
        "version": lot["version"],
    }


def cost_estimate(formula, variant):
    """formula_cost_estimate: sum over ingredients of pct/100 * unit_cost,
    rounded half-up to integer cents per kg (PRD section 3.2)."""
    total = Decimal("0")
    for ing in formula["ingredients"]:
        cid = ing.get("component_id")
        if not cid:
            continue
        comp = db.components.get(cid)
        if comp is None:
            continue
        if variant == "standard":
            unit = D(comp["standard_cost_per_kg_cents"])
        else:
            numerator = Decimal("0")
            denominator = Decimal("0")
            for lot in db.lots.values():
                if lot["component_id"] != cid or lot["status"] != "AVAILABLE":
                    continue
                if lot["unit_cost_per_kg_cents"] is None:
                    continue
                weight = D(lot["quantity_available"])
                numerator += weight * D(lot["unit_cost_per_kg_cents"])
                denominator += weight
            unit = (numerator / denominator) if denominator > 0 else D(comp["standard_cost_per_kg_cents"])
        total += D(ing["percentage"]) / Decimal("100") * unit
    return cents_round(total)


def serialize_formula(f):
    return {
        "id": f["id"],
        "customer_id": f["customer_id"],
        "base_formula_id": f["base_formula_id"],
        "name": f["name"],
        "version_seq": f["version_seq"],
        "ownership": f["ownership"],
        "confidentiality": f["confidentiality"],
        "product_class": f["product_class"],
        "allergen_flag": f["allergen_flag"],
        "bulk_mass_per_unit_kg": num(f["bulk_mass_per_unit_kg"]),
        "viscosity_target_cps": f["viscosity_target_cps"],
        "viscosity_tolerance_pct": num(f["viscosity_tolerance_pct"]),
        "ph_target": num(f["ph_target"]),
        "ph_tolerance": num(f["ph_tolerance"]),
        "ingredients": f["ingredients"],
        "required_components": f["required_components"],
        "status": f["status"],
        "cost_estimate_standard_per_kg_cents": cost_estimate(f, "standard"),
        "cost_estimate_current_lot_per_kg_cents": cost_estimate(f, "current_lot"),
        "created_at": f["created_at"],
        "updated_at": f["updated_at"],
        "version": f["version"],
    }


def serialize_review(r):
    return {
        "id": r["id"],
        "formula_id": r["formula_id"],
        "review_scope": r["review_scope"],
        "status": r["status"],
        "reviewer_user_id": r["reviewer_user_id"],
        "comment": r["comment"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def fulfillable_units(order):
    """fulfillable_units calculation (PRD section 3.5)."""
    formula = db.formulas.get(order["formula_id"])
    reqs = formula["required_components"] if formula else []
    if not reqs:
        return order["requested_units"], order["requested_units"]
    cons_result = None
    opt_result = None
    for entry in reqs:
        comp = db.components.get(entry.get("component_id") or "")
        need = D(entry.get("units_per_product", 0))
        if need <= 0:
            units_c = units_o = 0
            cons_result = units_c if cons_result is None else min(cons_result, units_c)
            opt_result = units_o if opt_result is None else min(opt_result, units_o)
            continue
        cons_pool = Decimal("0")
        opt_extra = Decimal("0")
        eligible = (
            comp is not None
            and comp["supply_mode"] == "CUSTOMER_SUPPLIED"
            and comp.get("customer_id") == order["customer_id"]
        )
        if eligible:
            for lot in db.lots.values():
                if lot["component_id"] != comp["id"]:
                    continue
                if lot["status"] != "AVAILABLE" or not lot_unexpired(lot):
                    continue
                if lot["sensorial_profile"] == "WITHIN_SPEC" or lot["variant_waiver"] == "WAIVED":
                    cons_pool += D(lot["quantity_available"])
                elif lot["sensorial_profile"] == "MINOR_VARIANT" and lot["variant_waiver"] == "PENDING":
                    opt_extra += D(lot["quantity_available"])
            # Add back this order's own RESERVED allocations on eligible lots
            for a in db.allocations.values():
                if a["production_order_id"] != order["id"] or a["status"] != "RESERVED":
                    continue
                lot = db.lots.get(a["lot_id"])
                if lot is None or lot["component_id"] != comp["id"]:
                    continue
                if lot["status"] != "AVAILABLE" or not lot_unexpired(lot):
                    continue
                if lot["sensorial_profile"] == "WITHIN_SPEC" or lot["variant_waiver"] == "WAIVED":
                    cons_pool += D(a["quantity"])
        units_c = floor_div(cons_pool, need)
        units_o = floor_div(cons_pool + opt_extra, need)
        cons_result = units_c if cons_result is None else min(cons_result, units_c)
        opt_result = units_o if opt_result is None else min(opt_result, units_o)
    return cons_result, opt_result


def serialize_order(o):
    cons, opt = fulfillable_units(o)
    return {
        "id": o["id"],
        "customer_id": o["customer_id"],
        "formula_id": o["formula_id"],
        "formula_version_seq": o["formula_version_seq"],
        "requested_units": o["requested_units"],
        "forfeited_units": o["forfeited_units"],
        "filled_units": o["filled_units"],
        "open_units": o["requested_units"] - o["filled_units"],
        "status": o["status"],
        "hold_return_status": o["hold_return_status"],
        "quote_total_cents": o["quote_total_cents"],
        "fulfillable_units_conservative": cons,
        "fulfillable_units_optimistic": opt,
        "created_at": o["created_at"],
        "updated_at": o["updated_at"],
        "version": o["version"],
    }


def serialize_batch(b):
    return {
        "id": b["id"],
        "production_order_id": b["production_order_id"],
        "batch_size_kg": num(b["batch_size_kg"]),
        "scale_up_factor": num(b["scale_up_factor"]),
        "scale_up_approved": b["scale_up_approved"],
        "status": b["status"],
        "failed_check_count": b["failed_check_count"],
        "round_viscosity_result": b["round_viscosity_result"],
        "round_ph_result": b["round_ph_result"],
        "last_ipc_recorded_by_user_id": b["last_ipc_recorded_by_user_id"],
        "batch_charge_cents": b["batch_charge_cents"],
        "batch_charge_standard_cents": b["batch_charge_standard_cents"],
        "created_at": b["created_at"],
        "updated_at": b["updated_at"],
        "version": b["version"],
    }


def serialize_ipc(c):
    return {
        "id": c["id"],
        "batch_id": c["batch_id"],
        "check_type": c["check_type"],
        "measured_value": num(c["measured_value"]),
        "round_index": c["round_index"],
        "effective_tolerance": num(c["effective_tolerance"]),
        "result": c["result"],
        "recorded_by_user_id": c["recorded_by_user_id"],
        "created_at": c["created_at"],
    }


def serialize_allocation(a):
    return {
        "id": a["id"],
        "production_order_id": a["production_order_id"],
        "batch_id": a["batch_id"],
        "lot_id": a["lot_id"],
        "quantity": num(a["quantity"]),
        "status": a["status"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


def serialize_shortfall(s):
    return {
        "id": s["id"],
        "production_order_id": s["production_order_id"],
        "component_id": s["component_id"],
        "required_quantity": num(s["required_quantity"]),
        "allocatable_quantity": num(s["allocatable_quantity"]),
        "shortfall_quantity": num(s["shortfall_quantity"]),
        "status": s["status"],
        "committed_by_date": s["committed_by_date"],
        "resolution": s["resolution"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


def serialize_line(l):
    return {
        "id": l["id"],
        "line_code": l["line_code"],
        "status": l["status"],
        "current_run_id": l["current_run_id"],
        "created_at": l["created_at"],
        "updated_at": l["updated_at"],
        "version": l["version"],
    }


def serialize_run(r):
    return {
        "id": r["id"],
        "production_order_id": r["production_order_id"],
        "line_id": r["line_id"],
        "batch_id": r["batch_id"],
        "scheduled_start": r["scheduled_start"],
        "scheduled_end": r["scheduled_end"],
        "planned_units": r["planned_units"],
        "filled_units": r["filled_units"],
        "rejected_units": r["rejected_units"],
        "changeover_minutes_required": r["changeover_minutes_required"],
        "status": r["status"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def serialize_chamber(c):
    return {
        "id": c["id"],
        "chamber_code": c["chamber_code"],
        "capacity_studies": c["capacity_studies"],
        "active_study_count": c["active_study_count"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def serialize_study(s):
    return {
        "id": s["id"],
        "formula_id": s["formula_id"],
        "chamber_id": s["chamber_id"],
        "study_type": s["study_type"],
        "required_intervals": s["required_intervals"],
        "recorded_interval_count": s["recorded_interval_count"],
        "status": s["status"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


def serialize_reading(r):
    return {
        "id": r["id"],
        "study_id": r["study_id"],
        "interval_index": r["interval_index"],
        "result": r["result"],
        "recorded_by_user_id": r["recorded_by_user_id"],
        "created_at": r["created_at"],
    }


# ---------------------------------------------------------------------------
# Calculation: order_quote_total (PRD section 3.4) — per-line round_half_up,
# then sum; tiered filling fee with PRESTIGE discount floored at 0.
# ---------------------------------------------------------------------------


def compute_quote(formula, customer, requested_units):
    materials = 0
    for ing in formula["ingredients"]:
        cid = ing.get("component_id")
        if not cid:
            continue
        comp = db.components.get(cid)
        if comp is None:
            continue
        kg = (D(ing["percentage"]) / Decimal("100")) * D(formula["bulk_mass_per_unit_kg"]) * D(requested_units)
        materials += cents_round(kg * D(comp["standard_cost_per_kg_cents"]))
    if requested_units <= FEE_TIER1_MAX_UNITS:
        rate = FEE_TIER1_RATE_CENTS
    elif requested_units <= FEE_TIER2_MAX_UNITS:
        rate = FEE_TIER2_RATE_CENTS
    else:
        rate = FEE_TIER3_RATE_CENTS
    if customer["tier"] == "PRESTIGE":
        rate = max(0, rate - PRESTIGE_RATE_DISCOUNT_CENTS)
    return materials + requested_units * rate


# ---------------------------------------------------------------------------
# Calculation: ipc_evaluation (PRD section 3.6) — tolerance tightening
# ---------------------------------------------------------------------------


def ipc_band(formula, check_type, failures):
    tighten = max(TIGHTENING_FLOOR, Decimal("1") - TIGHTENING_PER_FAILURE * D(failures))
    if check_type == "VISCOSITY":
        return D(formula["viscosity_target_cps"]) * (D(formula["viscosity_tolerance_pct"]) / Decimal("100")) * tighten
    return D(formula["ph_tolerance"]) * tighten


# ---------------------------------------------------------------------------
# Lot quantity mutations
# ---------------------------------------------------------------------------


def reserve_on_lot(lot, qty):
    lot["quantity_available"] = float(D(lot["quantity_available"]) - D(qty))
    lot["quantity_reserved"] = float(D(lot["quantity_reserved"]) + D(qty))
    if D(lot["quantity_available"]) == 0 and lot["status"] == "AVAILABLE":
        lot["status"] = "DEPLETED"
    touch(lot)


def release_allocation(a):
    if a["status"] != "RESERVED":
        return
    a["status"] = "RELEASED"
    touch(a)
    lot = db.lots.get(a["lot_id"])
    if lot is not None:
        lot["quantity_reserved"] = float(D(lot["quantity_reserved"]) - D(a["quantity"]))
        lot["quantity_available"] = float(D(lot["quantity_available"]) + D(a["quantity"]))
        if lot["status"] == "DEPLETED" and D(lot["quantity_available"]) > 0:
            lot["status"] = "AVAILABLE"
        touch(lot)


def consume_allocation(a):
    if a["status"] != "RESERVED":
        return
    a["status"] = "CONSUMED"
    touch(a)
    lot = db.lots.get(a["lot_id"])
    if lot is not None:
        lot["quantity_reserved"] = float(D(lot["quantity_reserved"]) - D(a["quantity"]))
        lot["quantity_consumed"] = float(D(lot["quantity_consumed"]) + D(a["quantity"]))
        touch(lot)


# ---------------------------------------------------------------------------
# Calculation: batch_closure_charge (PRD section 3.6) — pinned evaluation order
# ---------------------------------------------------------------------------


def compute_closure_charges(batch):
    materials_actual = 0
    materials_standard = 0
    for a in db.allocations.values():
        if a.get("batch_id") != batch["id"] or a["status"] != "CONSUMED":
            continue
        lot = db.lots.get(a["lot_id"])
        comp = db.components.get(lot["component_id"]) if lot else None
        if comp is None:
            continue
        qty = D(a["quantity"])
        if lot is not None and lot["unit_cost_per_kg_cents"] is not None:
            effective = D(lot["unit_cost_per_kg_cents"])
        else:
            effective = D(comp["standard_cost_per_kg_cents"])
        materials_actual += cents_round(qty * effective)
        materials_standard += cents_round(qty * D(comp["standard_cost_per_kg_cents"]))

    def with_surcharge(materials):
        rate = SURCHARGE_LOW if materials < SURCHARGE_BRACKET_CENTS else SURCHARGE_HIGH
        return materials + cents_round(D(materials) * rate)

    batch["batch_charge_cents"] = with_surcharge(materials_actual)
    batch["batch_charge_standard_cents"] = with_surcharge(materials_standard)


def consume_batch_allocations(batch):
    for a in db.allocations.values():
        if a.get("batch_id") == batch["id"] and a["status"] == "RESERVED":
            consume_allocation(a)
    compute_closure_charges(batch)


# ---------------------------------------------------------------------------
# ProductionOrder cascades
# ---------------------------------------------------------------------------


def cancel_order_cascade(order):
    prior = order["status"]
    order["status"] = "CANCELLED"
    order["hold_return_status"] = None
    touch(order)
    for a in db.allocations.values():
        if a["production_order_id"] == order["id"] and a["status"] == "RESERVED":
            release_allocation(a)
    for r in db.runs.values():
        if r["production_order_id"] == order["id"] and r["status"] == "SCHEDULED":
            r["status"] = "ABORTED"
            touch(r)
    for s in db.shortfalls.values():
        if s["production_order_id"] == order["id"] and s["status"] in ("OPEN", "COMMITMENT_RECEIVED"):
            s["status"] = "CLOSED_VOID"
            touch(s)
    if prior != "DRAFT":
        customer = db.customers.get(order["customer_id"])
        if customer is not None:
            customer["outstanding_balance_cents"] = customer["outstanding_balance_cents"] - order["quote_total_cents"]
            touch(customer)


def formula_hold_cascade(formula):
    """Formula -> CHANGES_REQUESTED: in-flight orders go ON_HOLD; their
    SCHEDULED runs are ABORTED (PRD section 3.3)."""
    for o in db.orders.values():
        if o["formula_id"] != formula["id"]:
            continue
        if o["status"] not in ("CONFIRMED", "IN_PRODUCTION", "FILLING"):
            continue
        o["hold_return_status"] = o["status"]
        o["status"] = "ON_HOLD"
        touch(o)
        for r in db.runs.values():
            if r["production_order_id"] == o["id"] and r["status"] == "SCHEDULED":
                r["status"] = "ABORTED"
                touch(r)


# ---------------------------------------------------------------------------
# Calculation: shortfall_proration (PRD section 3.5) — waterfall on lot receipt
# ---------------------------------------------------------------------------


def run_proration(lot):
    comp = db.components.get(lot["component_id"])
    if comp is None or comp["supply_mode"] != "CUSTOMER_SUPPLIED":
        return
    owner = comp.get("customer_id")
    cases = []
    for s in db.shortfalls.values():
        if s["component_id"] != comp["id"] or s["status"] not in ("OPEN", "COMMITMENT_RECEIVED"):
            continue
        order = db.orders.get(s["production_order_id"])
        if order is None or order["customer_id"] != owner:
            continue
        cases.append((s, order))
    # Oldest shortfall first; ties broken by parent order creation time
    cases.sort(key=lambda pair: (pair[0]["created_at"], pair[1]["created_at"], pair[0]["_seq"]))
    remaining = D(lot["quantity_available"])
    for s, _order in cases:
        if remaining <= 0:
            break
        covered = D(s.get("covered_quantity", 0))
        need = D(s["shortfall_quantity"]) - covered
        if need <= 0:
            continue
        grant = min(need, remaining)
        alloc = new_entity()
        alloc.update({
            "production_order_id": s["production_order_id"],
            "batch_id": None,
            "lot_id": lot["id"],
            "quantity": float(grant),
            "status": "RESERVED",
        })
        db.allocations[alloc["id"]] = alloc
        reserve_on_lot(lot, grant)
        s["covered_quantity"] = float(covered + grant)
        remaining -= grant
        if D(s["covered_quantity"]) >= D(s["shortfall_quantity"]):
            s["status"] = "CLOSED_RESOLVED"
            touch(s)


# ---------------------------------------------------------------------------
# Calculation: changeover_minutes (PRD section 3.8)
# ---------------------------------------------------------------------------


def previous_run_on_line(line_id, new_start_dt):
    prev = None
    for r in db.runs.values():
        if r["line_id"] != line_id:
            continue
        if r["status"] not in ("SCHEDULED", "IN_PROGRESS", "COMPLETED"):
            continue
        end = r.get("_end_dt")
        if end is None or end > new_start_dt:
            continue
        if (prev is None or end > prev["_end_dt"]
                or (end == prev["_end_dt"] and r["_seq"] < prev["_seq"])):
            prev = r
    return prev


def compute_changeover_minutes(new_order, line_id, new_start_dt):
    prev = previous_run_on_line(line_id, new_start_dt)
    if prev is None:
        return 0
    prev_order = db.orders.get(prev["production_order_id"])
    prev_formula = db.formulas.get(prev_order["formula_id"]) if prev_order else None
    new_formula = db.formulas.get(new_order["formula_id"])
    if prev_formula is None or new_formula is None:
        return 0
    if prev_formula["id"] == new_formula["id"]:
        base = SAME_FORMULA_MINUTES
    elif prev_formula["allergen_flag"] or new_formula["allergen_flag"]:
        base = ALLERGEN_CROSS_MINUTES
    elif prev_formula["product_class"] == new_formula["product_class"]:
        base = SAME_CLASS_MINUTES
    else:
        base = DIFFERENT_CLASS_MINUTES
    carryover = 0
    if prev_formula["id"] != new_formula["id"]:
        for ing in prev_formula["ingredients"]:
            comp = db.components.get(ing.get("component_id") or "")
            if comp is not None and comp["kind"] == "BULK_FRAGRANCE":
                carryover = FRAGRANCE_CARRYOVER_MINUTES
                break
    return min(base + carryover, MAX_CHANGEOVER_MINUTES)


def latest_review(formula_id, scope):
    latest = None
    for r in db.reviews.values():
        if r["formula_id"] == formula_id and r["review_scope"] == scope:
            if latest is None or r["_seq"] > latest["_seq"]:
                latest = r
    return latest


def line_window_overlaps(line_id, start_dt, end_dt):
    """Half-open [start, end) intersection against SCHEDULED/IN_PROGRESS runs;
    touching endpoints are allowed."""
    for r in db.runs.values():
        if r["line_id"] != line_id or r["status"] not in ("SCHEDULED", "IN_PROGRESS"):
            continue
        if start_dt < r["_end_dt"] and r["_start_dt"] < end_dt:
            return True
    return False
