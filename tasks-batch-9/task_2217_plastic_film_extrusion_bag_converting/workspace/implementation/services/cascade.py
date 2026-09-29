"""Forward-only cascades: line freeze, run block, roll quarantine, plate wear,
deferred supersession and the five-level dossier revocation chain."""

import config as C
from num import D, f, r
from services import calc, refs
from store import store


# ------------------------------------------------------------ recipe pin ----
def release_recipe_pin(recipe):
    """Recompute pinned_run_count and fire a deferred supersede when it hits 0."""
    if recipe is None:
        return
    calc.recompute_pinned_run_count(recipe)
    if (
        recipe.get("supersede_pending")
        and recipe["status"] == "APPROVED"
        and recipe["pinned_run_count"] == 0
    ):
        recipe["status"] = "SUPERSEDED"
        recipe["supersede_pending"] = False
    store.touch(recipe)


def repin_recipe(recipe):
    """Recompute pinned_run_count after a new pin (schedule)."""
    if recipe is None:
        return
    calc.recompute_pinned_run_count(recipe)
    store.touch(recipe)


# ------------------------------------------------- system-driven transitions -
def block_run(run, reason):
    run["status"] = "BLOCKED"
    run["recipe_pin_released"] = True
    store.touch(run)
    release_recipe_pin(refs.recipe_of_run(run))


def quarantine_roll(roll, reason):
    roll["status"] = "QUARANTINED"
    roll["release_blocked_reason"] = reason
    store.touch(roll)


def block_print_job(job, reason):
    job["status"] = "BLOCKED"
    job["blocked_reason"] = reason
    store.touch(job)


def block_plate_setup_jobs(plate, reason):
    """A worn plate blocks every SETUP job on it, releasing their cylinders."""
    for job in refs.jobs_of_plate(plate):
        if job["status"] == "SETUP":
            block_print_job(job, reason)


# ------------------------------------------------------------ line posture --
def rederive_line_posture(
    line, reason="Producing line posture became FROZEN.", incapable_delta=0, revoked_delta=0
):
    """Apply counter deltas, re-derive posture with a single mutation, cascade."""
    if line is None:
        return None
    before_posture = line["posture"]
    before_holds = line["active_hold_count"]
    if incapable_delta:
        line["incapable_run_count"] = int(line["incapable_run_count"]) + incapable_delta
    if revoked_delta:
        line["revoked_dossier_count"] = int(line["revoked_dossier_count"]) + revoked_delta
    posture = calc.derive_posture(line)
    line["posture"] = posture
    if (
        incapable_delta
        or revoked_delta
        or posture != before_posture
        or line["active_hold_count"] != before_holds
    ):
        store.touch(line)
    if posture == "FROZEN":
        freeze_cascade(line, reason)
    return posture


def freeze_cascade(line, reason):
    """Idempotent: SCHEDULED runs -> BLOCKED, WOUND rolls -> QUARANTINED."""
    for run in refs.runs_of_line(line):
        if run["status"] == "SCHEDULED":
            block_run(run, reason)
    for roll in refs.rolls_of_line(line):
        if roll["status"] == "WOUND":
            quarantine_roll(roll, reason)


# ------------------------------------------------- as-built propagation -----
def propagate_recycled_content(run):
    """Copy the run's as-built figure onto its rolls (and any lot fed by them)."""
    value = run.get("actual_recycled_content_pct")
    roll_ids = set()
    for roll in refs.rolls_of_run(run):
        roll_ids.add(roll["id"])
        if roll.get("actual_recycled_content_pct") != value:
            roll["actual_recycled_content_pct"] = value
            store.touch(roll)
    if not roll_ids:
        return
    for lot in store.sorted_values(store.bag_lots):
        job = refs.job_of_lot(lot)
        if job is None or job["film_roll_id"] not in roll_ids:
            continue
        if lot.get("actual_recycled_content_pct") != value:
            lot["actual_recycled_content_pct"] = value
            store.touch(lot)


# --------------------------------------------------- regrind ledger rows ----
def book_transaction(
    pool,
    direction,
    origin_kind,
    kg,
    pcr_kg,
    extrusion_run_id=None,
    origin_ref_id=None,
    reverses_transaction_id=None,
    reversal_reason=None,
):
    """Create one immutable ledger row, re-derive the pool and bump its version."""
    row = store.new_common(ledger_row=True)
    row.update(
        {
            "pool_id": pool["id"],
            "extrusion_run_id": extrusion_run_id,
            "reverses_transaction_id": reverses_transaction_id,
            "direction": direction,
            "origin_kind": origin_kind,
            "origin_ref_id": origin_ref_id,
            "kg": f(r(D(kg), 3)),
            "pcr_kg": f(r(D(pcr_kg), 3)),
            "pool_available_kg_after": None,
            "reversal_reason": reversal_reason,
            "recorded_at": store.clock_iso(),
        }
    )
    store.regrind_transactions[row["id"]] = row
    available = calc.recompute_pool(pool)
    row["pool_available_kg_after"] = f(available)
    store.touch(pool)
    return row


# ------------------------------------------- cascade root B: revocation -----
def revoke_dossier_cascade(dossier, lot):
    reason = "Compliance dossier %s was revoked: %s" % (
        dossier["dossier_code"],
        dossier.get("revocation_reason") or "no reason supplied",
    )

    if lot is None:
        return

    # depth 2 — the documented lot is quarantined and its packout unwound
    if lot["status"] in ("QUALIFIED", "CONDITIONAL", "PACKED", "RELEASED"):
        lot["status"] = "QUARANTINED"
        lot["quarantine_reason"] = reason
        lot["packed_bag_count"] = 0
        lot["packed_case_count"] = 0
        lot["partial_case_bag_count"] = 0
        lot["pallet_count"] = 0
        lot["bag_count_unpacked"] = lot["bag_count_produced"] - lot["bag_count_scrapped"]
        store.touch(lot)

    job, roll, run, line, recipe, plate = refs.lot_chain(lot)

    # depth 3 / 4 — the plate set accrues a nonconformance and may wear out
    if plate is not None:
        plate["nonconformance_count"] = int(plate["nonconformance_count"]) + 1
        worn = (
            plate["nonconformance_count"] >= C.PLATE_NONCONFORMANCE_LIMIT
            and plate["status"] == "MOUNTED"
        )
        if worn:
            plate["status"] = "WORN"
            plate["mounted_press_id"] = None
        store.touch(plate)
        if worn:
            block_plate_setup_jobs(plate, reason)

    # the roll traceable to the revoked dossier is quarantined
    if roll is not None and roll["status"] == "WOUND":
        quarantine_roll(roll, reason)

    # depth 5 — the producing line is frozen and fires the freeze cascade
    if line is not None:
        rederive_line_posture(line, reason, revoked_delta=1)
