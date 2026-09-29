"""Derived fields and the multi-hop cascades of PRD 2.10.

Derived values are always recomputed from scratch, never incrementally patched.
"""

import calc
import store


# ---------------------------------------------------------------------------
# Lookup helpers
# ---------------------------------------------------------------------------
def rows(collection, **filters):
    out = []
    for row in collection.values():
        for key, value in filters.items():
            if row.get(key) != value:
                break
        else:
            out.append(row)
    return store.by_seq(out)


def design_of(row):
    return store.designs.get(row.get("design_id"))


def program_of_design(design):
    return store.programs.get(design["program_id"]) if design else None


def program_of_run(run):
    return program_of_design(design_of(run))


def submissions_of_program(program_id):
    return rows(store.submissions, program_id=program_id)


def newest_submission(program_id, design_id):
    return store.newest([s for s in store.submissions.values()
                         if s["program_id"] == program_id
                         and s["design_id"] == design_id])


def newest_tooling(design_id):
    return store.newest([t for t in store.tooling_assets.values()
                         if t["design_id"] == design_id])


def characteristics_of(design_id):
    return rows(store.characteristics, design_id=design_id)


def records_of_run(run_id):
    return rows(store.inspection_records, run_id=run_id)


def lots_of_run(run_id):
    return rows(store.lots, run_id=run_id)


def batches_of_run(run_id):
    return rows(store.batches, run_id=run_id)


# ---------------------------------------------------------------------------
# CustomerProgram.delivery_posture (PRD 3.1)
# ---------------------------------------------------------------------------
def derive_posture(program):
    program_id = program["id"]
    approved = any(s["submission_status"] in ("APPROVED", "INTERIM_APPROVED")
                   for s in store.submissions.values()
                   if s["program_id"] == program_id)
    if not approved:
        return "BLOCKED"
    design_ids = set(d["id"] for d in store.designs.values()
                     if d["program_id"] == program_id)
    hold = any(r["quality_status"] == "SPC_HOLD"
               for r in store.runs.values() if r["design_id"] in design_ids)
    if program["quarantined_lot_count"] >= 1 or hold:
        return "AT_RISK"
    return "ON_TRACK"


def refresh_posture(program):
    if program is None:
        return
    posture = derive_posture(program)
    if program["delivery_posture"] != posture:
        program["delivery_posture"] = posture
        store.touch_program(program)


def refresh_posture_of_design(design):
    refresh_posture(program_of_design(design))


# ---------------------------------------------------------------------------
# CoilingMachine.active_setup_id (PRD 2.10)
# ---------------------------------------------------------------------------
def derive_active_setup_id(machine_id):
    for setup in store.setups.values():
        if setup["machine_id"] == machine_id and setup["setup_status"] == "ACTIVE":
            return setup["id"]
    return None


def refresh_active_setup(machine):
    machine["active_setup_id"] = derive_active_setup_id(machine["id"])


# ---------------------------------------------------------------------------
# StressReliefOven.scheduled_load_kg (PRD 3.9)
# ---------------------------------------------------------------------------
def derive_oven_load(oven_id):
    loads = [b["load_kg"] for b in store.batches.values()
             if b["oven_id"] == oven_id
             and b["batch_status"] in ("SCHEDULED", "RUNNING")]
    return calc.kg_sum(*loads) if loads else 0.0


def refresh_oven_load(oven):
    oven["scheduled_load_kg"] = derive_oven_load(oven["id"])
    store.touch(oven)


# ---------------------------------------------------------------------------
# ProductionRun.heat_treat_state (PRD 3.9)
# ---------------------------------------------------------------------------
def derive_heat_treat_state(run_id):
    statuses = [b["batch_status"] for b in store.batches.values()
                if b["run_id"] == run_id]
    if "COMPLETE" in statuses:
        return "COMPLETE"
    if "RUNNING" in statuses:
        return "IN_PROCESS"
    return "NOT_STARTED"


# ---------------------------------------------------------------------------
# ProductionRun capability minima (PRD 3.8)
# ---------------------------------------------------------------------------
def refresh_run_capability(run):
    cpks = []
    ppks = []
    for record in store.inspection_records.values():
        if record["run_id"] != run["id"]:
            continue
        if record["cpk_value"] is not None:
            cpks.append(record["cpk_value"])
        if record["record_kind"] == "SPC" and record["ppk_value"] is not None:
            characteristic = store.characteristics.get(record["characteristic_id"])
            if characteristic and characteristic.get("is_safety_critical"):
                ppks.append(record["ppk_value"])
    run["min_cpk_observed"] = min(cpks) if cpks else None
    run["min_ppk_observed"] = min(ppks) if ppks else None


# ---------------------------------------------------------------------------
# Wire ledger postings (PRD 2.9)
# ---------------------------------------------------------------------------
def reserve_wire(lot, amount_kg):
    lot["on_hand_kg"] = calc.kg_sum(lot["on_hand_kg"], -amount_kg)
    lot["reserved_kg"] = calc.kg_sum(lot["reserved_kg"], amount_kg)
    store.touch(lot)


def release_reservation(run):
    """Return the run's stored reservation verbatim to the rack."""
    lot = store.wire_lots.get(run["wire_lot_id"])
    if lot is None:
        return
    amount = run["wire_reserved_kg"]
    lot["reserved_kg"] = calc.kg_sum(lot["reserved_kg"], -amount)
    lot["on_hand_kg"] = calc.kg_sum(lot["on_hand_kg"], amount)
    store.touch(lot)


def settle_consumption(run, consumed_kg):
    lot = store.wire_lots.get(run["wire_lot_id"])
    if lot is None:
        return
    reserved = run["wire_reserved_kg"]
    lot["reserved_kg"] = calc.kg_sum(lot["reserved_kg"], -reserved)
    lot["consumed_kg"] = calc.kg_sum(lot["consumed_kg"], consumed_kg)
    lot["on_hand_kg"] = calc.kg_sum(lot["on_hand_kg"],
                                    calc.kg_sum(reserved, -consumed_kg))
    store.touch(lot)


# ---------------------------------------------------------------------------
# Setup / machine transitions
# ---------------------------------------------------------------------------
def free_machine(machine):
    """PRODUCTION or SETUP -> IDLE, active pointer re-derived."""
    machine["machine_state"] = "IDLE"
    refresh_active_setup(machine)
    store.touch(machine)


def abort_setup(setup):
    """Abort a setup; frees the coiler and bumps its version only when the
    setup was ACTIVE (PRD 3.6)."""
    was_active = setup["setup_status"] == "ACTIVE"
    setup["setup_status"] = "ABORTED"
    setup["superseded_by_setup_id"] = None
    store.touch(setup)
    if was_active:
        machine = store.machines.get(setup["machine_id"])
        if machine is not None:
            machine["machine_state"] = "IDLE"
            machine["active_setup_id"] = None
            store.touch(machine)
    return was_active


def release_setup(setup):
    """ACTIVE -> RELEASED when the run completes; coiler returns to IDLE."""
    setup["setup_status"] = "RELEASED"
    store.touch(setup)
    machine = store.machines.get(setup["machine_id"])
    if machine is not None:
        machine["machine_state"] = "IDLE"
        machine["active_setup_id"] = None
        store.touch(machine)


# ---------------------------------------------------------------------------
# Lot quarantine cascade (PRD 3.7 / 3.8 / 3.9)
# ---------------------------------------------------------------------------
def quarantine_lot(lot, reason, keep_packaging=True):
    lot["lot_status"] = "QUARANTINED"
    lot["quarantine_reason"] = reason
    if not keep_packaging:
        lot["packaging_method"] = None
    store.touch(lot)
    program = store.programs.get(lot["program_id"])
    if program is not None:
        program["quarantined_lot_count"] += 1
        program["allocated_pieces"] -= lot["piece_count"]
        program["open_commitment_pieces"] += lot["piece_count"]
        store.touch_program(program)
    return program


def quarantine_lots_of_run(run, reason="SPC_HOLD_CASCADE"):
    """Every ALLOCATED or PACKED lot of the run goes to QUARANTINED, with the
    owning program's counters moved and its posture re-derived."""
    affected = []
    for lot in lots_of_run(run["id"]):
        if lot["lot_status"] in ("ALLOCATED", "PACKED"):
            program = quarantine_lot(lot, reason)
            if program is not None and program["id"] not in [p["id"] for p in affected]:
                affected.append(program)
    for program in affected:
        refresh_posture(program)
    return affected


def spc_hold(run):
    """Drive the run onto a quality hold and fire the lot cascade."""
    run["quality_status"] = "SPC_HOLD"
    store.touch(run)
    quarantine_lots_of_run(run)
    refresh_posture(program_of_run(run))


def refresh_posture_for_lots_of_run(run):
    seen = set()
    for lot in lots_of_run(run["id"]):
        if lot["program_id"] in seen:
            continue
        seen.add(lot["program_id"])
        refresh_posture(store.programs.get(lot["program_id"]))
    program = program_of_run(run)
    if program is not None and program["id"] not in seen:
        refresh_posture(program)


# ---------------------------------------------------------------------------
# Run cancellation (PRD 3.7)
# ---------------------------------------------------------------------------
def cancel_run(run, quarantine=True):
    """CANCELLED: reservation released verbatim, setup aborted, coiler freed."""
    run["process_status"] = "CANCELLED"
    store.touch(run)
    release_reservation(run)
    setup = store.setups.get(run["setup_id"])
    if setup is not None and setup["setup_status"] == "ACTIVE":
        abort_setup(setup)
    if quarantine:
        quarantine_lots_of_run(run)
    refresh_posture(program_of_run(run))


# ---------------------------------------------------------------------------
# Tooling ledger cascades (PRD 3.4)
# ---------------------------------------------------------------------------
def arm_tooling(design):
    """Fired when a design reaches PRODUCTION_RELEASED."""
    program = program_of_design(design)
    if program is None:
        return
    basis = program["committed_pieces"]
    for tooling in rows(store.tooling_assets, design_id=design["id"]):
        if tooling["amortization_status"] != "PENDING":
            continue
        tooling["amortization_status"] = "AMORTIZING"
        tooling["amortization_basis_pieces"] = basis
        tooling["amort_per_piece_cents"] = calc.amort_per_piece(
            tooling["original_cost_cents"], basis)
        store.touch(tooling)


def write_off_tooling(design):
    for tooling in rows(store.tooling_assets, design_id=design["id"]):
        if tooling["amortization_status"] in ("PENDING", "AMORTIZING"):
            tooling["amortization_status"] = "WRITTEN_OFF"
            store.touch(tooling)


def abort_scheduled_setups(design, free_coiler):
    """Used by the revision cascade (frees the coiler) and by retirement."""
    for setup in rows(store.setups, design_id=design["id"]):
        if setup["setup_status"] != "SCHEDULED":
            continue
        setup["setup_status"] = "ABORTED"
        store.touch(setup)
        if not free_coiler:
            continue
        machine = store.machines.get(setup["machine_id"])
        if machine is None:
            continue
        if machine["machine_state"] != "IDLE" or machine["active_setup_id"] is not None:
            machine["machine_state"] = "IDLE"
            machine["active_setup_id"] = None
            store.touch(machine, bump_version=False)
