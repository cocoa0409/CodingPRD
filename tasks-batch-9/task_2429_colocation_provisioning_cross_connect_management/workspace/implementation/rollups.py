"""Derived quantities and cascades.

Implements circuit_allocated_kw, row_capacity_and_posture and
contract_provisioning_rollup, plus the inside-out cascade discipline of
PRD §2.8: circuit → cabinet → row → row-posture-affected entities → contract,
every touched entity having updated_at refreshed and version incremented.
"""

from errors import ApiError
from store import (
    COOLING_ALERT_RATIO,
    MEASURED_WINDOW_DAYS,
    OCCUPYING_CABINET_STATUSES,
    REDUNDANT_COOLING_FACTOR,
    now,
    store,
    touch,
)
from util import days_ago, dec, dsum, q1, q2, q3


# --------------------------------------------------------------------------
# Collection helpers
# --------------------------------------------------------------------------

def cabinets_of_row(row_id):
    return [c for c in store.cabinets.values() if c["row_id"] == row_id]


def circuits_of_cabinet(cabinet_id):
    return [c for c in store.circuits.values() if c["cabinet_id"] == cabinet_id]


def circuits_of_row(row_id):
    ids = set(c["id"] for c in cabinets_of_row(row_id))
    return [c for c in store.circuits.values() if c["cabinet_id"] in ids]


def cabinets_of_contract(contract_id):
    return [c for c in store.cabinets.values() if c.get("contract_id") == contract_id]


def circuits_of_contract(contract_id):
    ids = set(c["id"] for c in cabinets_of_contract(contract_id))
    return [c for c in store.circuits.values() if c["cabinet_id"] in ids]


def lines_of_contract(contract_id):
    return [l for l in store.invoice_lines.values() if l["contract_id"] == contract_id]


def orders_of_contract(contract_id):
    return [o for o in store.cc_orders.values() if o["contract_id"] == contract_id]


def ports_of_order(order_id):
    return [p for p in store.ports.values() if p.get("assigned_order_id") == order_id]


def cabinet_of(circuit):
    return store.cabinets.get(circuit["cabinet_id"])


def row_of(cabinet):
    return store.rows.get(cabinet["row_id"])


def contract_of(cabinet):
    if cabinet is None or not cabinet.get("contract_id"):
        return None
    return store.contracts.get(cabinet["contract_id"])


# --------------------------------------------------------------------------
# circuit_allocated_kw
# --------------------------------------------------------------------------

def derated_kw(breaker_amps, volts, phase):
    factor = dec("1.0") if phase == "SINGLE" else dec("1.732")
    raw = dec(breaker_amps) * dec(volts) * factor / dec("1000") * dec("0.80")
    return q3(raw)


def energized_power(circuit, cabinet):
    """(allocated_kw, cooling_contribution_kw) as though the circuit were
    ENERGIZED. The cabinet nameplate clamp is applied to the already-rounded
    derated figure; heat is never clamped."""
    derated = dec(circuit["derated_kw"])
    if circuit["redundancy_role"] == "PRIMARY":
        rated = dec(cabinet["rated_power_kw"])
        allocated = derated if derated <= rated else rated
        return q3(allocated), q3(derated)
    return 0.0, q3(derated * dec(REDUNDANT_COOLING_FACTOR))


def set_energized_power(circuit, cabinet):
    allocated, cooling = energized_power(circuit, cabinet)
    circuit["allocated_kw"] = allocated
    circuit["cooling_contribution_kw"] = cooling


def zero_power(circuit):
    circuit["allocated_kw"] = 0.0
    circuit["cooling_contribution_kw"] = 0.0


# --------------------------------------------------------------------------
# Cabinet rollups (PRD §3.3)
# --------------------------------------------------------------------------

def recompute_cabinet(cabinet, force=False):
    circuits = circuits_of_cabinet(cabinet["id"])
    energized = [c for c in circuits if c["status"] == "ENERGIZED"]
    allocated = q3(dsum(c["allocated_kw"] for c in energized))
    cooling = q3(dsum(c["cooling_contribution_kw"] for c in energized))
    primary = len([c for c in energized if c["redundancy_role"] == "PRIMARY"])

    changed = (
        allocated != cabinet["allocated_power_kw"]
        or cooling != cabinet["cooling_load_kw"]
        or primary != cabinet["energized_primary_circuit_count"]
    )
    cabinet["allocated_power_kw"] = allocated
    cabinet["cooling_load_kw"] = cooling
    cabinet["energized_primary_circuit_count"] = primary

    # Power drives the ACTIVE posture; a client never requests it.
    if cabinet["status"] == "INSTALLED" and primary > 0:
        cabinet["status"] = "ACTIVE"
        changed = True
    elif cabinet["status"] == "ACTIVE" and primary == 0:
        cabinet["status"] = "INSTALLED"
        changed = True

    if changed or force:
        touch(cabinet)
    return changed


# --------------------------------------------------------------------------
# row_capacity_and_posture (PRD §3.2)
# --------------------------------------------------------------------------

def measured_peak(row_id):
    cutoff = days_ago(now(), MEASURED_WINDOW_DAYS)
    peaks = []
    for circuit in circuits_of_row(row_id):
        for interval in circuit.get("meter_intervals", []):
            if interval["interval_start"] >= cutoff:
                peaks.append(dec(interval["peak_kw"]))
    if not peaks:
        return 0.0
    return q3(max(peaks))


def recompute_row(row, force=False, cascade=True):
    cabinets = cabinets_of_row(row["id"])
    occupied = len([c for c in cabinets if c["status"] in OCCUPYING_CABINET_STATUSES])
    energized_cabinets = len([c for c in cabinets if c["status"] == "ACTIVE"])
    energized = [c for c in circuits_of_row(row["id"]) if c["status"] == "ENERGIZED"]
    allocated = q3(dsum(c["allocated_kw"] for c in energized))
    cooling = q3(dsum(c["cooling_contribution_kw"] for c in energized))
    density = q3(dec(row["design_density_kw_per_cabinet"]) * dec(occupied))
    effective = q3(min(dec(row["max_row_power_kw"]), dec(density), dec(row["cooling_capacity_kw"])))
    peak = measured_peak(row["id"])
    stranded_nameplate = q3(dec(effective) - dec(allocated))
    stranded_measured = q3(dec(effective) - dec(peak))

    # Ordered posture cascade — the first matching branch wins.
    if row["decommission_flag"]:
        status = "DECOMMISSIONING"
    elif dec(cooling) >= dec(row["cooling_capacity_kw"]) * dec(COOLING_ALERT_RATIO):
        status = "COOLING_CONSTRAINED"
    elif occupied > 0 and dec(allocated) >= dec(density):
        status = "DENSITY_CAPPED"
    else:
        status = "OPEN"

    updates = {
        "occupied_slot_count": occupied,
        "energized_cabinet_count": energized_cabinets,
        "allocated_power_kw": allocated,
        "cooling_load_kw": cooling,
        "density_ceiling_kw": density,
        "effective_ceiling_kw": effective,
        "measured_peak_kw": peak,
        "stranded_nameplate_kw": stranded_nameplate,
        "stranded_measured_kw": stranded_measured,
        "row_status": status,
    }
    changed = any(row.get(k) != v for k, v in updates.items())
    row.update(updates)
    if changed or force:
        touch(row)
    if cascade:
        posture_cascade(row)
    return changed


def posture_cascade(row):
    """A DENSITY_CAPPED row holds its RESERVED cabinets and blocks their
    DESIGNED circuits; a return to OPEN lifts both holds. COOLING_CONSTRAINED
    holds nothing."""
    status = row["row_status"]
    if status == "DENSITY_CAPPED":
        for cabinet in cabinets_of_row(row["id"]):
            if cabinet["status"] != "RESERVED":
                continue
            cabinet["status"] = "CAPACITY_HELD"
            touch(cabinet)
            for circuit in circuits_of_cabinet(cabinet["id"]):
                if circuit["status"] == "DESIGNED":
                    circuit["status"] = "BLOCKED"
                    touch(circuit)
    elif status == "OPEN":
        for cabinet in cabinets_of_row(row["id"]):
            if cabinet["status"] != "CAPACITY_HELD":
                continue
            cabinet["status"] = "RESERVED"
            touch(cabinet)
            for circuit in circuits_of_cabinet(cabinet["id"]):
                if circuit["status"] == "BLOCKED":
                    circuit["status"] = "DESIGNED"
                    touch(circuit)


# --------------------------------------------------------------------------
# contract_provisioning_rollup (PRD §3.4)
# --------------------------------------------------------------------------

def recompute_contract(contract, force=False):
    if contract is None:
        return False
    primary = [
        c
        for c in circuits_of_contract(contract["id"])
        if c["status"] == "ENERGIZED" and c["redundancy_role"] == "PRIMARY"
    ]
    provisioned = q3(dsum(c["allocated_kw"] for c in primary))
    commit = dec(contract["power_commit_kw"])
    remaining = commit - dec(provisioned)
    stranded = q3(remaining if remaining > 0 else dec("0"))
    if commit > 0:
        pct = q1(dec(provisioned) / commit * dec("100"))
    else:
        pct = 0.0
    active = len([o for o in orders_of_contract(contract["id"]) if o["status"] == "ACTIVE"])
    lines = lines_of_contract(contract["id"])
    billed = q2(dsum(l["amount_usd"] for l in lines))
    cc_billed = q2(
        dsum(
            l["amount_usd"]
            for l in lines
            if l["line_type"] in ("CROSS_CONNECT_MRC", "CROSS_CONNECT_SURCHARGE")
        )
    )
    updates = {
        "provisioned_power_kw": provisioned,
        "stranded_commit_kw": stranded,
        "commit_utilization_pct": pct,
        "active_cross_connect_count": active,
        "billed_total_usd": billed,
        "cross_connect_billed_usd": cc_billed,
    }
    changed = any(contract.get(k) != v for k, v in updates.items())
    contract.update(updates)
    if changed or force:
        touch(contract)
    return changed


# --------------------------------------------------------------------------
# Composite cascades
# --------------------------------------------------------------------------

def cascade_power_change(cabinet, force=True):
    """Inside-out: cabinet rollups, then the row and its posture-driven holds,
    then the owning contract's provisioning rollups."""
    recompute_cabinet(cabinet, force=force)
    row = row_of(cabinet)
    if row is not None:
        recompute_row(row, force=force)
    recompute_contract(contract_of(cabinet))


def de_energize(circuit, cabinet):
    circuit["status"] = "DE_ENERGIZED"
    zero_power(circuit)
    touch(circuit)


def resolve_path(collection, key, error_id):
    row = collection.get(key)
    if row is None:
        raise ApiError(error_id, "%s does not resolve to a stored row" % key)
    return row
