"""Shared lookups, ledgers, selectors and the five multi-hop cascades."""

from decimal import Decimal

import calc
from auth import actor
from errors import ApiError
from store import add_days, clock, clock_str, db, new_row, parse_dt, sort_rows, touch

D = Decimal
ZERO = D("0.00")


# --------------------------------------------------------------------------
# lookups (ladder rules 4 and 8)
# --------------------------------------------------------------------------
def find(collection, row_id, error_id):
    row = collection.get(row_id) if isinstance(row_id, str) else None
    if row is None:
        raise ApiError(error_id)
    return row


def plant_or_404(plant_id):
    return find(db.plants, plant_id, "ERR_PLANT_NOT_FOUND")


def pit_or_404(pit_id):
    return find(db.clay_pits, pit_id, "ERR_CLAY_PIT_NOT_FOUND")


def formulation_or_404(fid):
    return find(db.formulations, fid, "ERR_FORMULATION_NOT_FOUND")


def kiln_or_404(kid):
    return find(db.kilns, kid, "ERR_KILN_NOT_FOUND")


def car_or_404(cid):
    return find(db.kiln_cars, cid, "ERR_KILN_CAR_NOT_FOUND")


def run_or_404(rid):
    return find(db.production_runs, rid, "ERR_PRODUCTION_RUN_NOT_FOUND")


def kiln_run_or_404(rid):
    return find(db.kiln_runs, rid, "ERR_KILN_RUN_NOT_FOUND")


def lot_or_404(lid):
    return find(db.fired_lots, lid, "ERR_FIRED_LOT_NOT_FOUND")


def order_or_404(oid):
    return find(db.orders, oid, "ERR_ORDER_NOT_FOUND")


def blend_or_404(bid):
    return find(db.blends, bid, "ERR_BLEND_NOT_FOUND")


def panel_or_404(pid):
    return find(db.sample_panels, pid, "ERR_SAMPLE_PANEL_NOT_FOUND")


# --------------------------------------------------------------------------
# code uniqueness (ladder rule 34)
# --------------------------------------------------------------------------
def require_unique(collection, field, value, scope_field=None, scope_value=None):
    for row in collection.values():
        if row.get(field) != value:
            continue
        if scope_field is not None and row.get(scope_field) != scope_value:
            continue
        raise ApiError("ERR_DUPLICATE_CODE", "%s '%s' is already in use." % (field, value))


# --------------------------------------------------------------------------
# plant status (ladder rule 10)
# --------------------------------------------------------------------------
def require_plant_active(plant):
    if plant is None or plant.get("status") != "ACTIVE":
        raise ApiError("ERR_PLANT_IDLED", "The owning plant is IDLED.")


def plant_of_kiln(kiln):
    return db.plants.get(kiln["plant_id"])


def plant_of_kiln_run(kiln_run):
    kiln = db.kilns.get(kiln_run["kiln_id"])
    return db.plants.get(kiln["plant_id"]) if kiln else None


def plant_id_of_kiln_run(kiln_run):
    kiln = db.kilns.get(kiln_run["kiln_id"])
    return kiln["plant_id"] if kiln else None


# --------------------------------------------------------------------------
# collection scans
# --------------------------------------------------------------------------
def pits_of_plant(plant_id):
    return sort_rows([p for p in db.clay_pits.values() if p["plant_id"] == plant_id])


def formulations_of_plant(plant_id):
    return sort_rows([f for f in db.formulations.values() if f["plant_id"] == plant_id])


def kilns_of_plant(plant_id):
    return sort_rows([k for k in db.kilns.values() if k["plant_id"] == plant_id])


def cars_of_plant(plant_id):
    return sort_rows([c for c in db.kiln_cars.values() if c["plant_id"] == plant_id])


def runs_of_kiln_run(kiln_run_id):
    return sort_rows(
        [r for r in db.production_runs.values() if r.get("kiln_run_id") == kiln_run_id]
    )


def components_of_blend(blend_id):
    return sort_rows([c for c in db.blend_components.values() if c["blend_id"] == blend_id])


def allocated_components(blend_id):
    return [c for c in components_of_blend(blend_id) if c["status"] == "ALLOCATED"]


def panels_of_order(order_id):
    return sort_rows([p for p in db.sample_panels.values() if p["order_id"] == order_id])


def blends_of_order(order_id):
    return sort_rows([b for b in db.blends.values() if b["order_id"] == order_id])


def live_blend_of_order(order_id):
    """The order's shipped blend: the newest one that is not VOID."""
    rows = [b for b in blends_of_order(order_id) if b["status"] != "VOID"]
    return rows[-1] if rows else None


def any_blend_of_order(order_id):
    rows = blends_of_order(order_id)
    return rows[-1] if rows else None


# --------------------------------------------------------------------------
# clay reserve ledger (PRD 2.9, 3.3)
# --------------------------------------------------------------------------
def clay_split_for(formulation, green_units_set):
    total = calc.clay_total_tons(green_units_set, formulation["clay_tons_per_thousand_units"])
    amounts = calc.clay_split(total, formulation.get("components") or [])
    return total, amounts


def clay_commit(amounts):
    """Check every contributing pit before writing any (PRD 2.9)."""
    for pit_id, tons in amounts:
        pit = db.clay_pits.get(pit_id)
        if pit is None or D(pit["available_tons"]) < D(tons):
            raise ApiError(
                "ERR_CLAY_RESERVE_INSUFFICIENT",
                "A contributing clay pit cannot fund its share of the commitment.",
            )
    for pit_id, tons in amounts:
        pit = db.clay_pits[pit_id]
        pit["available_tons"] = calc.rh(D(pit["available_tons"]) - D(tons), 2)
        pit["committed_tons"] = calc.rh(D(pit["committed_tons"]) + D(tons), 2)
        if pit["available_tons"] == ZERO and pit["status"] == "OPEN":
            pit["status"] = "DEPLETED"
        touch(pit)


def clay_consume(amounts):
    for pit_id, tons in amounts:
        pit = db.clay_pits.get(pit_id)
        if pit is None:
            continue
        pit["committed_tons"] = calc.rh(D(pit["committed_tons"]) - D(tons), 2)
        pit["consumed_tons"] = calc.rh(D(pit["consumed_tons"]) + D(tons), 2)
        touch(pit)


def clay_release(amounts):
    for pit_id, tons in amounts:
        pit = db.clay_pits.get(pit_id)
        if pit is None:
            continue
        pit["committed_tons"] = calc.rh(D(pit["committed_tons"]) - D(tons), 2)
        pit["available_tons"] = calc.rh(D(pit["available_tons"]) + D(tons), 2)
        if pit["status"] == "DEPLETED" and pit["available_tons"] > ZERO:
            pit["status"] = "SUSPENDED"
        touch(pit)


def run_amounts(run):
    return [(pit_id, D(tons)) for pit_id, tons in (run.get("_pit_amounts") or [])]


# --------------------------------------------------------------------------
# fired unit ledger (PRD 2.9)
# --------------------------------------------------------------------------
def lot_reserve(lot, units):
    lot["available_units"] = int(lot["available_units"]) - int(units)
    lot["reserved_units"] = int(lot["reserved_units"]) + int(units)
    if lot["reserved_units"] > 0 and lot["status"] == "AVAILABLE":
        lot["status"] = "RESERVED"
    touch(lot)


def lot_release(lot, units):
    lot["reserved_units"] = int(lot["reserved_units"]) - int(units)
    lot["available_units"] = int(lot["available_units"]) + int(units)
    if lot["reserved_units"] == 0 and lot["status"] == "RESERVED":
        lot["status"] = "AVAILABLE"
    touch(lot)


def lot_consume(lot, units):
    lot["reserved_units"] = int(lot["reserved_units"]) - int(units)
    lot["consumed_units"] = int(lot["consumed_units"]) + int(units)
    if lot["reserved_units"] == 0 and lot["status"] == "RESERVED":
        lot["status"] = "CONSUMED"
    touch(lot)


# --------------------------------------------------------------------------
# body chemistry recompute (PRD 3.2)
# --------------------------------------------------------------------------
def recompute_chemistry(formulation):
    result = calc.body_chemistry(
        formulation.get("components") or [], lambda pit_id: db.clay_pits.get(pit_id)
    )
    formulation["component_share_total_pct"] = result["component_share_total_pct"]
    formulation["blend_iron_oxide_pct"] = result["blend_iron_oxide_pct"]
    formulation["blend_lime_pct"] = result["blend_lime_pct"]
    formulation["shale_share_pct"] = result["shale_share_pct"]
    formulation["absorption_index"] = result["absorption_index"]
    formulation["computed_durability_grade"] = result["computed_durability_grade"]
    return formulation


# --------------------------------------------------------------------------
# blend colour profile (PRD 3.7)
# --------------------------------------------------------------------------
def blend_profile(blend):
    comps = allocated_components(blend["id"])
    allocated = sum(int(c["units"]) for c in comps)
    if not comps or allocated <= 0:
        return {
            "allocated_units": allocated,
            "weighted_color_index": None,
            "color_range_span": None,
            "dye_lot_count": 0,
        }
    acc = D("0")
    indices = []
    codes = set()
    for comp in comps:
        lot = db.fired_lots.get(comp["fired_lot_id"])
        if lot is None:
            continue
        index = D(lot["color_index"])
        acc += index * D(int(comp["units"]))
        indices.append(index)
        codes.add(lot.get("dye_lot_code"))
    return {
        "allocated_units": allocated,
        "weighted_color_index": calc.rh(acc / D(allocated), 2),
        "color_range_span": calc.rh(max(indices) - min(indices), 2),
        "dye_lot_count": len(codes),
    }


def recompute_allocated_units(blend):
    blend["allocated_units"] = sum(int(c["units"]) for c in allocated_components(blend["id"]))
    return blend["allocated_units"]


def plant_of_lot(lot):
    run = db.production_runs.get(lot.get("production_run_id"))
    return run["plant_id"] if run else None


# --------------------------------------------------------------------------
# auto-fill waterfall (PRD 3.7)
# --------------------------------------------------------------------------
def autofill_candidates(blend, order):
    required_rank = calc.rank(order["durability_grade"])
    low = D(blend["target_color_index_min"])
    high = D(blend["target_color_index_max"])
    out = []
    for lot in db.fired_lots.values():
        if lot["status"] not in ("AVAILABLE", "RESERVED"):
            continue
        if int(lot["available_units"]) <= 0:
            continue
        if lot["grade"] != "ON_COLOR":
            continue
        if lot["color_family"] != order["color_family"]:
            continue
        if lot["texture"] != order["texture"]:
            continue
        if calc.rank(lot["durability_grade"]) < required_rank:
            continue
        if plant_of_lot(lot) != order.get("plant_id"):
            continue
        index = D(lot["color_index"])
        if index < low or index > high:
            continue
        out.append(lot)
    midpoint = D(blend["target_color_index_midpoint"])
    out.sort(
        key=lambda l: (
            calc.rh(abs(D(l["color_index"]) - midpoint), 2),
            -int(l["available_units"]),
            l["created_at"],
            l["_seq"],
        )
    )
    return out


def new_component(blend, lot, units, source):
    comp = new_row(
        blend_id=blend["id"],
        fired_lot_id=lot["id"],
        units=int(units),
        color_index_at_allocation=D(lot["color_index"]),
        contribution_index=calc.rh(D(lot["color_index"]) * D(int(units)), 2),
        source=source,
        status="ALLOCATED",
    )
    db.blend_components[comp["id"]] = comp
    lot_reserve(lot, units)
    return comp


def autofill_plan(blend, order):
    """Plan the waterfall without mutating anything.

    Returns (plan, shortfall_remaining) where plan is [(lot, units)] in
    waterfall order. A rejected composition must persist nothing at all, so the
    plan is only applied once every composition condition has passed.
    """
    shortfall = int(blend["requested_units"]) - int(blend["allocated_units"])
    plan = []
    if shortfall <= 0:
        return plan, 0
    for lot in autofill_candidates(blend, order):
        if shortfall <= 0:
            break
        take = min(shortfall, int(lot["available_units"]))
        if take <= 0:
            continue
        plan.append((lot, take))
        shortfall -= take
    return plan, shortfall


def apply_autofill(blend, plan):
    for lot, units in plan:
        new_component(blend, lot, units, "AUTO_FILL")
    recompute_allocated_units(blend)


# --------------------------------------------------------------------------
# freight-sensitive plant selection and quoting (PRD 3.5, 3.8)
# --------------------------------------------------------------------------
def plant_has_body(plant, order):
    required_rank = calc.rank(order["durability_grade"])
    for f in db.formulations.values():
        if f["plant_id"] != plant["id"]:
            continue
        if f["status"] != "QUALIFIED":
            continue
        if f["target_color_family"] != order["color_family"]:
            continue
        if calc.rank(f.get("computed_durability_grade")) < required_rank:
            continue
        return True
    return False


def select_plant(order):
    tons = calc.estimated_billable_tons(order["requested_units"])
    pool = []
    for plant in db.plants.values():
        if plant["status"] != "ACTIVE":
            continue
        distance = calc.rectilinear(
            plant["grid_x"], plant["grid_y"], order["jobsite_grid_x"], order["jobsite_grid_y"]
        )
        if distance > int(plant["market_radius_miles"]):
            continue
        if order["unloading_equipment_required"] not in (
            plant.get("unloading_equipment_available") or []
        ):
            continue
        if not plant_has_body(plant, order):
            continue
        base, surcharge, total = calc.freight(
            distance, plant["freight_rate_cents_per_ton_mile"], tons
        )
        pool.append((total, distance, plant["created_at"], plant["_seq"], plant, base, surcharge))
    if not pool:
        raise ApiError(
            "ERR_NO_PLANT_IN_MARKET_RADIUS",
            "No eligible plant serves the jobsite inside its market radius.",
        )
    pool.sort(key=lambda row: (row[0], row[1], row[2], row[3]))
    total, distance, _created, _seq, plant, base, surcharge = pool[0]
    return {
        "plant": plant,
        "distance_miles": distance,
        "estimated_billable_tons": tons,
        "estimated_base_freight_cents": base,
        "estimated_fuel_surcharge_cents": surcharge,
        "estimated_freight_cents": total,
    }


# --------------------------------------------------------------------------
# dye-lot equivalence class (PRD 3.6)
# --------------------------------------------------------------------------
def equivalence_class(formulation_id):
    seen = []
    seen_set = set()
    current = formulation_id
    hops = 0
    while current is not None and hops <= calc.DYE_LOT_CLOSURE_MAX_HOPS:
        if current in seen_set:
            break
        seen.append(current)
        seen_set.add(current)
        formulation = db.formulations.get(current)
        if formulation is None:
            break
        current = formulation.get("supersedes_formulation_id")
        hops += 1
    return seen_set


# --------------------------------------------------------------------------
# CASCADE: idling a plant (PRD 3.9) — hops 1, 2, 3, 4, 3b, 4b
# --------------------------------------------------------------------------
def idle_plant_cascade(plant):
    plant["status"] = "IDLED"
    plant["idled_at"] = clock_str()
    touch(plant)

    for kiln in kilns_of_plant(plant["id"]):
        kiln["status"] = "MAINTENANCE"
        touch(kiln)
    for car in cars_of_plant(plant["id"]):
        car["status"] = "OUT_OF_SERVICE"
        car["current_production_run_id"] = None
        touch(car)

    # Hop 1 — pits.
    suspended = set()
    for pit in pits_of_plant(plant["id"]):
        if pit["status"] == "OPEN":
            pit["status"] = "SUSPENDED"
            suspended.add(pit["id"])
            touch(pit)

    # Hop 2 — recipes, caused by hop 1.
    dequalified = set()
    for formulation in formulations_of_plant(plant["id"]):
        if formulation["status"] != "QUALIFIED":
            continue
        pit_ids = {c["pit_id"] for c in (formulation.get("components") or [])}
        if not (pit_ids & suspended):
            continue
        formulation["status"] = "DRAFT"
        formulation["qualified_at"] = None
        formulation["dequalified_count"] = int(formulation["dequalified_count"]) + 1
        dequalified.add(formulation["id"])
        touch(formulation)

    # Hop 3 — in-flight extrusion, caused by hop 2.
    scrapped = []
    for run in sort_rows(list(db.production_runs.values())):
        if run["status"] == "SETTING" and run["formulation_id"] in dequalified:
            run["status"] = "SCRAPPED"
            scrapped.append(run)
            touch(run)

    # Hop 4 — tonnage release, caused by hop 3.
    for run in scrapped:
        clay_release(run_amounts(run))
        car = db.kiln_cars.get(run["kiln_car_id"])
        if car is not None:
            car["status"] = "OUT_OF_SERVICE"
            car["current_production_run_id"] = None
            touch(car)

    # Hop 3b — firings, caused by hop 1 through the kiln branch, after hop 4.
    kiln_ids = {k["id"] for k in kilns_of_plant(plant["id"])}
    aborted = set()
    for kiln_run in sort_rows(list(db.kiln_runs.values())):
        if kiln_run["kiln_id"] in kiln_ids and kiln_run["status"] in ("SCHEDULED", "FIRING"):
            kiln_run["status"] = "ABORTED"
            aborted.add(kiln_run["id"])
            touch(kiln_run)

    # Hop 4b — loaded cars, caused by hop 3b.
    for run in sort_rows(list(db.production_runs.values())):
        if run.get("kiln_run_id") in aborted and run["status"] == "LOADED":
            run["status"] = "SET"
            run["kiln_run_id"] = None
            run["kiln_position"] = None
            touch(run)
            car = db.kiln_cars.get(run["kiln_car_id"])
            if car is not None:
                car["status"] = "OUT_OF_SERVICE"
                car["current_production_run_id"] = None
                touch(car)
    return plant


# --------------------------------------------------------------------------
# CASCADE: grading a kiln run (PRD 3.4)
# --------------------------------------------------------------------------
def grade_cascade(kiln_run, kiln, formulation, actual_peak_temp_c, actual_soak_hours):
    kiln_run["actual_peak_temp_c"] = int(actual_peak_temp_c)
    kiln_run["actual_soak_hours"] = actual_soak_hours
    base = calc.base_cdi(actual_peak_temp_c, actual_soak_hours)
    kiln_run["base_cdi"] = base
    kiln_run["firing_curve_deviation"] = calc.firing_curve_deviation(
        actual_peak_temp_c,
        kiln["setpoint_peak_c"],
        actual_soak_hours,
        formulation["target_soak_hours"],
    )
    kiln_run["graded_by_user_id"] = actor()

    loaded = [r for r in runs_of_kiln_run(kiln_run["id"]) if r["status"] == "LOADED"]
    target_cdi = D(formulation["target_cdi"])
    minted = []

    # Hop 1 — mint one fired lot per loaded production run; the run moves to FIRED.
    for run in loaded:
        position = int(run["kiln_position"])
        delta = calc.position_temp_delta_c(position, kiln["position_count"])
        pos_cdi = calc.position_cdi(base, delta)
        grade = calc.firing_grade(pos_cdi, target_cdi)
        lot = new_row(
            production_run_id=run["id"],
            lot_code="%s-P%d" % (run["run_code"], position),
            kiln_position=position,
            fired_units=int(run["net_green_units"]),
            grade=grade,
            position_cdi=pos_cdi,
            color_index=calc.lot_color_index(pos_cdi, target_cdi),
            color_family=formulation["target_color_family"],
            texture=run["texture"],
            durability_grade=formulation["computed_durability_grade"],
            dye_lot_code="%s-%s-P%d"
            % (formulation["formulation_code"], kiln_run["run_code"], position),
            source_formulation_id=formulation["id"],
            reserved_units=0,
            consumed_units=0,
            available_units=int(run["net_green_units"]),
            quarantine_reason=None,
            status="SCRAP" if grade in ("OVERFIRE_SCRAP", "UNDERFIRE_SCRAP") else "AVAILABLE",
        )
        db.fired_lots[lot["id"]] = lot
        run["status"] = "FIRED"
        touch(run)
        minted.append((run, lot))

    # Hop 2 — caused by hop 1: a scrap-graded lot writes scrap_units and the
    # plant's running fired_scrap_units total.
    for run, lot in minted:
        if lot["status"] != "SCRAP":
            continue
        run["scrap_units"] = int(lot["fired_units"])
        touch(run)
        plant = db.plants.get(run["plant_id"])
        if plant is not None:
            plant["fired_scrap_units"] = int(plant["fired_scrap_units"]) + int(lot["fired_units"])
            touch(plant)

    # Hop 3 — caused by hop 1: every affected kiln car returns to IDLE.
    for run, _lot in minted:
        car = db.kiln_cars.get(run["kiln_car_id"])
        if car is not None and car["status"] == "IN_KILN":
            car["status"] = "IDLE"
            car["current_production_run_id"] = None
            touch(car)

    # Hop 4 — the kiln run itself.
    kiln_run["status"] = "GRADED"
    touch(kiln_run)
    return kiln_run


# --------------------------------------------------------------------------
# CASCADE: rejecting a blend (PRD 3.7) — four hops
# --------------------------------------------------------------------------
def void_components_and_release(blend):
    for comp in allocated_components(blend["id"]):
        comp["status"] = "VOIDED"
        touch(comp)
        lot = db.fired_lots.get(comp["fired_lot_id"])
        if lot is not None:
            lot_release(lot, int(comp["units"]))
    blend["allocated_units"] = 0


def reject_cascade(blend, reason):
    blend["status"] = "DRAFT"
    blend["rejection_reason"] = reason
    blend["rejection_count"] = int(blend["rejection_count"]) + 1
    blend["weighted_color_index"] = None
    blend["color_range_span"] = None
    blend["dye_lot_count"] = 0
    blend["composed_by_user_id"] = None
    void_components_and_release(blend)
    touch(blend)
    return blend


# --------------------------------------------------------------------------
# CASCADE: delivering an order (PRD 3.8)
# --------------------------------------------------------------------------
def deliver_cascade(order, blend):
    order["delivered_at"] = clock_str()
    order["invoiced_at"] = clock_str()
    order["fulfillment_status"] = "DELIVERED"
    order["freight_status"] = "INVOICED"
    touch(order)
    if blend is not None:
        blend["status"] = "RELEASED"
        touch(blend)
        for comp in allocated_components(blend["id"]):
            comp["status"] = "CONSUMED"
            touch(comp)
            lot = db.fired_lots.get(comp["fired_lot_id"])
            if lot is not None:
                lot_consume(lot, int(comp["units"]))
    return order


# --------------------------------------------------------------------------
# CASCADE: cancelling an order (PRD 3.8)
# --------------------------------------------------------------------------
def cancel_cascade(order, reason):
    order["fulfillment_status"] = "CANCELLED"
    order["cancellation_reason"] = reason
    if order["freight_status"] in ("UNQUOTED", "ESTIMATED", "FINALIZED"):
        order["freight_status"] = "WAIVED"
    touch(order)

    for blend in blends_of_order(order["id"]):
        if blend["status"] not in ("DRAFT", "COMPOSED", "CERTIFIED"):
            continue
        blend["status"] = "VOID"
        void_components_and_release(blend)
        touch(blend)

    for panel in panels_of_order(order["id"]):
        if panel["status"] in ("DRAFT", "SUBMITTED", "REVISION_REQUESTED"):
            panel["status"] = "WITHDRAWN"
            touch(panel)
    return order
