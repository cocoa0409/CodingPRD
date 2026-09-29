"""Load-plan payload, index and centre-of-gravity engine (PRD §3.6).

Every entry point computes figures *without* touching stored rows so a caller can
run the envelope verdict first and abandon the whole operation with nothing
persisted, as PRD §3.6 requires.
"""
import calc
import db
from calc import D, ZERO, r2
from errors import ERR_COMPARTMENT_OVERLOAD, ERR_RUNNING_LOAD_EXCEEDED, fail

# Numeric balance fields zeroed when a COMPUTED plan is invalidated (PRD §3.3).
BALANCE_NUMERIC_FIELDS = (
    "base_payload_kg",
    "frozen_underload_kg",
    "planned_payload_kg",
    "zero_fuel_weight_kg",
    "index_zfw",
    "mac_zfw_pct",
    "takeoff_weight_kg",
    "index_tow",
    "mac_tow_pct",
    "taxi_weight_kg",
    "landing_weight_kg",
    "underload_kg",
)

PLAN_ACTIVE_STATUSES = ("DRAFT", "COMPUTED", "RESTRICTED", "SHEET_ISSUED")
FREEZING_SHEET_STATUSES = ("ISSUED", "ACCEPTED", "AMENDED")
LIVE_CARGO_STATUSES = ("ACCEPTED", "LOADED")


# --------------------------------------------------------------- navigation
def plan_context(plan):
    flight = db.flights[plan["flight_id"]]
    aircraft = db.aircraft[flight["aircraft_id"]]
    program = db.weight_programs[flight["weight_program_id"]]
    return flight, aircraft, program


def active_plans(flight_id):
    return [p for p in db.flight_plans(flight_id) if p["status"] in PLAN_ACTIVE_STATUSES]


def sheets_freeze_plan(plan_id):
    return any(s["status"] in FREEZING_SHEET_STATUSES for s in db.plan_sheets(plan_id))


# ------------------------------------------------------------- collections
def counted_cargo(flight_id, exclude_ids=()):
    """Collection (c) of calculate_base_payload: stowed, live, non-gate-bag cargo."""
    rows = []
    for item in db.flight_cargo(flight_id):
        if item["id"] in exclude_ids:
            continue
        if (
            item["status"] in LIVE_CARGO_STATUSES
            and item.get("assigned_compartment_id")
            and item["item_kind"] != "GATE_BAG"
        ):
            rows.append(item)
    return rows


def accepted_gate_bag_kg(flight_id):
    total = ZERO
    for item in db.flight_cargo(flight_id):
        if item["item_kind"] == "GATE_BAG" and item["status"] in LIVE_CARGO_STATUSES:
            total += D(item["weight_kg"])
    return total


def live_gate_bags(flight_id, exclude_ids=()):
    """Gate bags whose mass is in the live payload and which sit in a hold.

    Their mass reaches ``zero_fuel_weight_kg`` through ``planned_payload_kg``
    (PRD §3.6 step two), so — being assigned — they contribute index too
    ("Unassigned consignments contribute no index, for the same reason they
    contribute no payload").
    """
    rows = []
    for item in db.flight_cargo(flight_id):
        if item["id"] in exclude_ids:
            continue
        if (
            item["item_kind"] == "GATE_BAG"
            and item["status"] in LIVE_CARGO_STATUSES
            and item.get("assigned_compartment_id")
        ):
            rows.append(item)
    return rows


def offloaded_counted_kg(plan, extra_offloaded_ids=()):
    """Weight of rows counted at compute time that have since left the payload."""
    total = ZERO
    for cargo_id in plan.get("_counted_cargo_ids", []):
        item = db.cargo_items.get(cargo_id)
        if item is None:
            continue
        if item["status"] == "OFFLOADED" or cargo_id in extra_offloaded_ids:
            total += D(item["weight_kg"])
    return total


# --------------------------------------------------- calculate_balance_chain
def balance_chain(plan, flight, aircraft, planned_payload, index_rows):
    ref_arm = aircraft["ref_arm_m"]
    index_c = aircraft["index_c"]
    dry_index = D(flight["dry_operating_index"])

    accumulated = dry_index
    if plan.get("rounding_mode") == "SUM_THEN_ROUND":
        for weight, arm in index_rows:
            accumulated += calc.raw_index(weight, arm, ref_arm, index_c)
    else:  # PER_LINE_THEN_SUM — the contract default
        for weight, arm in index_rows:
            accumulated += calc.index_delta(weight, arm, ref_arm, index_c)
    index_zfw = r2(accumulated)

    planned_payload = D(planned_payload)
    zero_fuel_weight = r2(D(flight["dry_operating_weight_kg"]) + planned_payload)
    takeoff_fuel = D(flight["ramp_fuel_kg"]) - D(flight["taxi_fuel_kg"])
    takeoff_weight = r2(zero_fuel_weight + takeoff_fuel)
    taxi_weight = r2(zero_fuel_weight + D(flight["ramp_fuel_kg"]))
    landing_weight = r2(takeoff_weight - D(flight["trip_fuel_kg"]))
    fuel_index = calc.index_delta(takeoff_fuel, aircraft["fuel_arm_m"], ref_arm, index_c)
    index_tow = r2(index_zfw + fuel_index)

    mac_zfw = calc.pct_mac(index_zfw, zero_fuel_weight, aircraft)
    mac_tow = calc.pct_mac(index_tow, takeoff_weight, aircraft)

    aft_tow_effective = D(aircraft["tow_aft_limit_pct_mac"])
    if takeoff_weight > D(aircraft["tow_knee_weight_kg"]):
        aft_tow_effective += D(aircraft["tow_aft_knee_adjust_pct_mac"])

    envelope_ok = (
        D(aircraft["zfw_fwd_limit_pct_mac"]) <= mac_zfw <= D(aircraft["zfw_aft_limit_pct_mac"])
        and D(aircraft["tow_fwd_limit_pct_mac"]) <= mac_tow <= aft_tow_effective
    )

    return {
        "zero_fuel_weight_kg": float(zero_fuel_weight),
        "index_zfw": float(index_zfw),
        "mac_zfw_pct": float(mac_zfw),
        "takeoff_weight_kg": float(takeoff_weight),
        "index_tow": float(index_tow),
        "mac_tow_pct": float(mac_tow),
        "taxi_weight_kg": float(taxi_weight),
        "landing_weight_kg": float(landing_weight),
        "envelope_ok": bool(envelope_ok),
    }


# --------------------------------------------------------- fresh computation
def compute_figures(plan, flight, aircraft, program):
    """Full compute (PRD §3.6). Returns pending row updates plus every figure."""
    ref_arm = aircraft["ref_arm_m"]
    index_c = aircraft["index_c"]
    row_updates = []
    index_rows = []
    base = ZERO
    counted_ids = []

    for line in db.plan_pax_lines(plan["id"]):
        compartment = db.compartments[line["compartment_id"]]
        weight = calc.pax_line_weight(line, program)
        delta = calc.index_delta(weight, compartment["arm_m"], ref_arm, index_c)
        row_updates.append((line, {"line_weight_kg": float(weight), "index_delta": float(delta)}))
        index_rows.append((weight, compartment["arm_m"]))
        base += weight

    for allocation in db.plan_bag_allocations(plan["id"]):
        compartment = db.compartments[allocation["compartment_id"]]
        weight = calc.bag_effective_weight(allocation, program)
        delta = calc.index_delta(weight, compartment["arm_m"], ref_arm, index_c)
        row_updates.append(
            (allocation, {"effective_weight_kg": float(weight), "index_delta": float(delta)})
        )
        index_rows.append((weight, compartment["arm_m"]))
        base += weight

    for item in counted_cargo(flight["id"]):
        compartment = db.compartments[item["assigned_compartment_id"]]
        index_rows.append((D(item["weight_kg"]), compartment["arm_m"]))
        base += D(item["weight_kg"])
        counted_ids.append(item["id"])

    for item in live_gate_bags(flight["id"]):
        compartment = db.compartments[item["assigned_compartment_id"]]
        index_rows.append((D(item["weight_kg"]), compartment["arm_m"]))

    base = r2(base)
    frozen_underload = r2(D(flight["allowed_payload_kg"]) - base)
    planned = r2(base + accepted_gate_bag_kg(flight["id"]))
    underload = r2(D(flight["allowed_payload_kg"]) - planned)
    chain = balance_chain(plan, flight, aircraft, planned, index_rows)
    return {
        "row_updates": row_updates,
        "counted_cargo_ids": counted_ids,
        "base_payload_kg": float(base),
        "frozen_underload_kg": float(frozen_underload),
        "restriction_status": "WEIGHT_RESTRICTED" if frozen_underload < 0 else "UNRESTRICTED",
        "planned_payload_kg": float(planned),
        "underload_kg": float(underload),
        "chain": chain,
    }


def live_figures(
    plan,
    flight,
    aircraft,
    exclude_cargo_ids=(),
    extra_gate_bag_kg=0,
    extra_gate_bag_arm_m=None,
):
    """Refresh only the live payload and the balance chain; frozen fields untouched."""
    index_rows = []
    for line in db.plan_pax_lines(plan["id"]):
        compartment = db.compartments[line["compartment_id"]]
        index_rows.append((D(line["line_weight_kg"]), compartment["arm_m"]))
    for allocation in db.plan_bag_allocations(plan["id"]):
        compartment = db.compartments[allocation["compartment_id"]]
        index_rows.append((D(allocation["effective_weight_kg"]), compartment["arm_m"]))
    for item in counted_cargo(flight["id"], exclude_cargo_ids):
        compartment = db.compartments[item["assigned_compartment_id"]]
        index_rows.append((D(item["weight_kg"]), compartment["arm_m"]))
    for item in live_gate_bags(flight["id"], exclude_cargo_ids):
        compartment = db.compartments[item["assigned_compartment_id"]]
        index_rows.append((D(item["weight_kg"]), compartment["arm_m"]))
    if extra_gate_bag_arm_m is not None:
        index_rows.append((D(extra_gate_bag_kg), extra_gate_bag_arm_m))

    base = D(plan["base_payload_kg"])
    gate = accepted_gate_bag_kg(flight["id"]) + D(extra_gate_bag_kg)
    offloaded = offloaded_counted_kg(plan, exclude_cargo_ids)
    planned = r2(base + gate - offloaded)
    underload = r2(D(flight["allowed_payload_kg"]) - planned)
    chain = balance_chain(plan, flight, aircraft, planned, index_rows)
    return {
        "planned_payload_kg": float(planned),
        "underload_kg": float(underload),
        "chain": chain,
    }


def apply_row_updates(row_updates):
    for row, values in row_updates:
        changed = any(float(row.get(k, 0) or 0) != float(v) for k, v in values.items())
        row.update(values)
        if changed:
            db.touch(row)


# ------------------------------------------------ calculate_offload_selection
def offload_selection(plan, flight):
    frozen = D(plan["frozen_underload_kg"])
    excess = -frozen if frozen < 0 else ZERO
    candidates = [
        item
        for item in db.flight_cargo(flight["id"])
        if item["status"] == "ACCEPTED"
        and item.get("assigned_compartment_id")
        and item["item_kind"] != "GATE_BAG"
    ]
    if plan.get("offload_strategy") == "FEWEST_PIECES":
        candidates.sort(
            key=lambda c: (-D(c["weight_kg"]), int(c["offload_priority_rank"]), c["_seq"])
        )
    else:  # PRIORITY_FIRST
        candidates.sort(
            key=lambda c: (int(c["offload_priority_rank"]), -D(c["weight_kg"]), c["_seq"])
        )

    selected = []
    running = ZERO
    for candidate in candidates:
        if running >= excess:
            break
        selected.append(candidate)
        running += D(candidate["weight_kg"])
    return excess, selected, r2(running)


# --------------------------------------------------------- hold ceilings
def hold_occupancy(flight_id, compartment_id, exclude_cargo_id=None, exclude_allocation_id=None):
    """Cargo plus checked-bag mass already committed to one hold (PRD §3.3)."""
    total = ZERO
    for item in db.flight_cargo(flight_id):
        if item["id"] == exclude_cargo_id:
            continue
        if (
            item.get("assigned_compartment_id") == compartment_id
            and item["status"] in LIVE_CARGO_STATUSES
        ):
            total += D(item["weight_kg"])
    plan_ids = {p["id"] for p in active_plans(flight_id)}
    for allocation in db.bag_allocations.values():
        if allocation["id"] == exclude_allocation_id:
            continue
        if allocation["compartment_id"] == compartment_id and allocation["load_plan_id"] in plan_ids:
            total += D(allocation["effective_weight_kg"])
    return total


def check_hold_ceilings(compartment, total_weight):
    total = D(total_weight)
    if total > D(compartment["max_weight_kg"]):
        fail(ERR_COMPARTMENT_OVERLOAD)
    length = D(compartment["length_m"])
    if length > 0 and total / length > D(compartment["running_load_limit_kg_per_m"]):
        fail(ERR_RUNNING_LOAD_EXCEEDED)


# ------------------------------------------------------- plan state helpers
def revert_to_draft(plan, flight):
    """COMPUTED -> DRAFT with the balance fields reset (PRD §3.3)."""
    plan["status"] = "DRAFT"
    for field in BALANCE_NUMERIC_FIELDS:
        plan[field] = 0
    plan["envelope_ok"] = False
    plan["_counted_cargo_ids"] = []
    db.touch(plan)
    if flight["status"] == "LOAD_CONTROLLED":
        flight["status"] = "PLANNING"
        db.touch(flight)


def invalidate_computation(flight, plan):
    """Shared tail of pax-line / bag-allocation / stowage writes."""
    if plan["status"] == "COMPUTED":
        revert_to_draft(plan, flight)


# ------------------------------------------------------------- LMC totals
def refresh_sheet_totals(sheet):
    plan = db.load_plans[sheet["load_plan_id"]]
    _flight, aircraft, _program = plan_context(plan)
    net = ZERO
    absolute = ZERO
    index_sum = ZERO
    for change in db.sheet_changes(sheet["id"]):
        if change["status"] != "APPLIED":
            continue
        delta = D(change["weight_delta_kg"])
        net += delta
        absolute += abs(delta)
        index_sum += D(change["index_delta"])
    net = r2(net)
    sheet["lmc_net_weight_delta_kg"] = float(net)
    sheet["lmc_absolute_weight_delta_kg"] = float(r2(absolute))
    final_tow = r2(D(sheet["issued_takeoff_weight_kg"]) + net)
    final_index = r2(D(sheet["issued_index_tow"]) + r2(index_sum))
    sheet["final_takeoff_weight_kg"] = float(final_tow)
    sheet["final_index_tow"] = float(final_index)
    sheet["final_mac_tow_pct"] = float(calc.pct_mac(final_index, final_tow, aircraft))
    sheet["final_payload_kg"] = float(r2(D(sheet["issued_payload_kg"]) + net))


# --------------------------------------------------- audit documented figures
def audit_reference_plan(flight_id):
    """The plan a load audit documents against (PRD §3.9)."""
    candidates = [
        p for p in db.flight_plans(flight_id) if p["status"] in ("SHEET_ISSUED", "COMPUTED")
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda p: int(p["revision_no"]))


def documented_figures(flight_id, plan):
    pax = ZERO
    bag = ZERO
    cargo = ZERO
    if plan is not None:
        for line in db.plan_pax_lines(plan["id"]):
            pax += D(line["line_weight_kg"])
        for allocation in db.plan_bag_allocations(plan["id"]):
            bag += D(allocation["effective_weight_kg"])
    for item in db.flight_cargo(flight_id):
        if item["status"] == "LOADED":
            cargo += D(item["weight_kg"])
    return r2(pax), r2(bag), r2(cargo)


def accepted_sheet_of(plan):
    if plan is None:
        return None
    for sheet in db.plan_sheets(plan["id"]):
        if sheet["status"] in ("ACCEPTED", "AMENDED"):
            return sheet
    return None


def lmc_class_sum(sheet, kinds):
    total = ZERO
    if sheet is None:
        return total
    for change in db.sheet_changes(sheet["id"]):
        if change["status"] == "APPLIED" and change["change_kind"] in kinds:
            total += D(change["weight_delta_kg"])
    return total
