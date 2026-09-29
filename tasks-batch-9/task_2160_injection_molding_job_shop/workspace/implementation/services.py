"""Gates, selectors, ledgers, cascades and the recomputation engine."""
import calcs
from common import DB, fail, order_key, public, touch

JOB_ACTIVE = ("SCHEDULED", "RUNNING")


# ------------------------------------------------------------ collections ----
def jobs_of_mold(mold_id):
    return sorted([j for j in DB.jobs.values() if j["mold_id"] == mold_id], key=order_key)


def jobs_of_press(press_id):
    return sorted([j for j in DB.jobs.values() if j["press_id"] == press_id], key=order_key)


def reports_of_job(job_id, live_only=True):
    rows = [r for r in DB.reports.values() if r["job_id"] == job_id]
    if live_only:
        rows = [r for r in rows if not r["is_reversed"]]
    return sorted(rows, key=order_key)


def quals_of_mold(mold_id):
    return sorted([q for q in DB.qualifications.values() if q["mold_id"] == mold_id],
                  key=order_key)


def qualification_for(mold_id, press_id):
    for q in DB.qualifications.values():
        if q["mold_id"] == mold_id and q["press_id"] == press_id:
            return q
    return None


def duration_minutes(job):
    return calcs.minutes_between(job["_start_dt"], job["_end_dt"])


# ------------------------------------------------------------------ gates ----
def mold_lifecycle_gate(mold, required_statuses):
    """Ladder step 11. The specific lifecycle errors outrank the generic one."""
    status = mold["status"]
    if status in required_statuses:
        return
    if status == "QUARANTINED":
        fail("ERR_MOLD_QUARANTINED", "The tool is quarantined.")
    if status == "RETIRED":
        fail("ERR_MOLD_RETIRED", "The tool is retired.")
    if status == "TRANSFERRED":
        fail("ERR_MOLD_TRANSFERRED", "The tool has been transferred.")
    fail("ERR_MOLD_NOT_PPAP_APPROVED",
         "The tool is in status %s, which this operation does not allow." % status)


def service_gate(mold):
    """Ladder step 13."""
    if mold["service_state"] != "SERVICEABLE":
        fail("ERR_PM_OVERDUE", "The tool is not serviceable.")


def transfer_gate(mold):
    """Ladder step 14."""
    if mold.get("active_transfer_id"):
        fail("ERR_MOLD_TRANSFER_IN_PROGRESS", "A tool transfer is in flight on this tool.")


def press_physical_gate(mold, press):
    if press["status"] != "AVAILABLE":
        fail("ERR_PRESS_OFFLINE", "The press is offline.")
    if not (mold["required_min_tonnage"] <= press["tonnage"] <= mold["required_max_tonnage"]):
        fail("ERR_PRESS_TONNAGE_MISMATCH", "The press tonnage is outside the tool's band.")
    if press["shot_size_grams_max"] < mold["shot_weight_grams"]:
        fail("ERR_PRESS_SHOT_SIZE_EXCEEDED", "The press cannot deliver the tool's shot.")


def press_is_adequate(mold, press):
    return (press["status"] == "AVAILABLE"
            and mold["required_min_tonnage"] <= press["tonnage"] <= mold["required_max_tonnage"]
            and press["shot_size_grams_max"] >= mold["shot_weight_grams"])


def rank_presses(candidates):
    return sorted(candidates,
                  key=lambda p: (p["tonnage"], p["hourly_rate_cents"], order_key(p)))


def select_rate_press(mold):
    """quote_press_rate_selection — no qualification row is required here."""
    candidates = [p for p in DB.presses.values() if press_is_adequate(mold, p)]
    if not candidates:
        fail("ERR_NO_ELIGIBLE_PRESS", "No adequate press exists for this tool.")
    return rank_presses(candidates)[0]


def select_routing_press(mold, start, end):
    """press_routing_selection — strictly narrower than the rate selector."""
    candidates = []
    for press in DB.presses.values():
        if not press_is_adequate(mold, press):
            continue
        qual = qualification_for(mold["id"], press["id"])
        if qual is None or qual["status"] != "QUALIFIED":
            continue
        if press_window_conflict(press["id"], start, end, None):
            continue
        candidates.append(press)
    if not candidates:
        fail("ERR_NO_ELIGIBLE_PRESS", "No eligible press exists for this window.")
    return rank_presses(candidates)[0]


# -------------------------------------------------------------- intervals ----
def press_window_conflict(press_id, start, end, exclude_job_id):
    for job in jobs_of_press(press_id):
        if job["id"] == exclude_job_id:
            continue
        if job["run_status"] not in JOB_ACTIVE:
            continue
        if calcs.press_collides(start, end, job["_start_dt"], job["_end_dt"]):
            return True
    return False


def check_press_window(press_id, start, end, exclude_job_id):
    """Ladder step 16."""
    if press_window_conflict(press_id, start, end, exclude_job_id):
        fail("ERR_PRESS_WINDOW_CONFLICT", "The press window collides with existing work.")


def check_mold_window(mold_id, start, end, exclude_job_id):
    """Ladder step 17."""
    for order in DB.maintenance_orders.values():
        if order["mold_id"] != mold_id or order["status"] != "OPEN":
            continue
        if calcs.mold_collides(start, end, order["_start_dt"], order["_end_dt"]):
            fail("ERR_MOLD_WINDOW_CONFLICT", "The tool is in the toolroom for that window.")
    for job in jobs_of_mold(mold_id):
        if job["id"] == exclude_job_id:
            continue
        if job["run_status"] not in JOB_ACTIVE:
            continue
        if calcs.mold_collides(start, end, job["_start_dt"], job["_end_dt"]):
            fail("ERR_MOLD_WINDOW_CONFLICT", "The tool is already occupied in that window.")


def check_daily_capacity(press_id, candidate_job):
    """Ladder step 21."""
    day = candidate_job["_start_dt"].date()
    total = 0
    for job in jobs_of_press(press_id):
        if job["id"] == candidate_job["id"]:
            continue
        if job["run_status"] not in JOB_ACTIVE:
            continue
        if job["_start_dt"].date() == day:
            total += duration_minutes(job)
    if total + duration_minutes(candidate_job) > calcs.PRESS_DAILY_CAPACITY_MINUTES:
        fail("ERR_PRESS_DAILY_CAPACITY_EXCEEDED",
             "The press would exceed its daily committed capacity.")


# ---------------------------------------------------------- press ledger ----
def reserve_minutes(job):
    press = DB.presses.get(job["press_id"])
    if press is None:
        return
    press["committed_minutes_scheduled"] += duration_minutes(job)
    touch(press)


def release_minutes(job):
    press = DB.presses.get(job["press_id"])
    if press is None:
        return
    press["committed_minutes_scheduled"] -= duration_minutes(job)
    touch(press)


def unstage(job):
    if job["material_status"] == "STAGED":
        job["material_status"] = "UNSTAGED"
        job["staged_resin_lot_id"] = None


# ------------------------------------------------------------- cascades ----
def block_scheduled_jobs(mold, reason):
    """A mold reaching PM_DUE or QUARANTINED blocks its SCHEDULED jobs; each
    job's arrival at BLOCKED then de-stages material and releases press minutes."""
    for job in jobs_of_mold(mold["id"]):
        if job["run_status"] != "SCHEDULED":
            continue
        job["run_status"] = "BLOCKED"
        job["block_reason"] = reason
        unstage(job)
        release_minutes(job)
        touch(job)


def cancel_job(job, block_reason):
    previous = job["run_status"]
    job["run_status"] = "CANCELLED"
    job["block_reason"] = block_reason
    if previous in ("SCHEDULED", "RUNNING"):
        release_minutes(job)
    unstage(job)
    touch(job)


def revoke_qualifications(mold):
    """A mold reaching TRANSFERRED or RETIRED revokes its QUALIFIED rows; each
    revocation cancels that pairing's unfinished jobs."""
    for qual in quals_of_mold(mold["id"]):
        if qual["status"] != "QUALIFIED":
            continue
        qual["status"] = "REVOKED"
        touch(qual)
        for job in jobs_of_mold(mold["id"]):
            if job["press_id"] != qual["press_id"]:
                continue
            if job["run_status"] not in ("DRAFT", "SCHEDULED", "BLOCKED"):
                continue
            cancel_job(job, "QUALIFICATION_REVOKED")


# -------------------------------------------------------- recomputation ----
def recompute_job_rollups(job):
    """job_yield_accounting + job_cost_roll + the cumulative regrind ratio, all
    defined purely as functions of the job's non-reversed reports."""
    mold = DB.molds.get(job["mold_id"])
    cavity_count = mold["cavity_count"] if mold else 0
    rows = reports_of_job(job["id"])

    job["total_shots"] = sum(r["shots"] for r in rows)
    job["parts_molded_total"] = sum(r["shots"] * cavity_count for r in rows)
    job["good_parts_total"] = sum(r["good_parts"] for r in rows)
    job["scrap_parts_total"] = sum(r["scrap_parts"] for r in rows)
    job["short_shot_shots_total"] = sum(r["short_shot_shots"] for r in rows)
    job["total_run_minutes"] = sum(r["run_minutes"] for r in rows)

    if job["parts_molded_total"] == 0:
        job["first_pass_yield_bp"] = 10000
    else:
        job["first_pass_yield_bp"] = calcs.floor_div(
            job["good_parts_total"] * 10000, job["parts_molded_total"])

    if job["total_shots"] == 0:
        job["actual_cycle_time_sec"] = None
    else:
        job["actual_cycle_time_sec"] = calcs.round_half_up(
            job["total_run_minutes"] * 60, job["total_shots"])

    cum_regrind = sum(r["regrind_grams"] for r in rows)
    cum_total = sum(r["virgin_grams"] + r["regrind_grams"] for r in rows)
    job["cumulative_regrind_bp"] = (0 if cum_total == 0
                                    else calcs.round_half_up(cum_regrind * 10000, cum_total))

    direct = sum(r["report_direct_cost_cents"] for r in rows)
    job["job_direct_cost_cents"] = direct
    overhead_bp = calcs.overhead_tier(direct)
    job["job_overhead_cents"] = calcs.round_half_up(direct * overhead_bp, 10000)
    job["job_total_cost_cents"] = direct + job["job_overhead_cents"]


def recompute_lot(lot):
    """resin_lot_mass_balance — a conserved quantity, never a running subtraction."""
    before = dict(public(lot))
    consumed = sum(r["virgin_grams"] for r in DB.reports.values()
                   if r.get("resin_lot_id") == lot["id"] and not r["is_reversed"])
    lot["qty_grams_remaining"] = lot["qty_kg_received"] * 1000 - consumed
    if lot["qty_grams_remaining"] == 0 and lot["status"] == "RELEASED":
        lot["status"] = "DEPLETED"
    if public(lot) != before:
        touch(lot)


def last_pm_reset_key(mold):
    resets = [o for o in DB.maintenance_orders.values()
              if o["mold_id"] == mold["id"] and o["status"] == "CLOSED" and o["shots_reset"]]
    if not resets:
        return order_key(mold)
    return order_key(sorted(resets, key=order_key)[-1])


def recompute_mold_counters(mold):
    """mold_shot_counter_and_pm — recomputed, never incremented in place."""
    before = dict(public(mold))
    rows = []
    for report in DB.reports.values():
        if report["is_reversed"]:
            continue
        job = DB.jobs.get(report["job_id"])
        if job is None or job["mold_id"] != mold["id"]:
            continue
        rows.append(report)

    mold["total_shot_count"] = sum(r["shots"] for r in rows)
    reset_key = last_pm_reset_key(mold)
    mold["shots_since_pm"] = sum(r["shots"] for r in rows if order_key(r) >= reset_key)

    pm_fired = False
    interim_fired = False
    # THRESHOLD GATE A — preventive maintenance, evaluated first.
    if (mold["shots_since_pm"] >= mold["pm_interval_shots"]
            and mold["service_state"] == "SERVICEABLE"):
        mold["service_state"] = "PM_DUE"
        pm_fired = True
    elif (mold["service_state"] == "PM_DUE"
          and mold["shots_since_pm"] < mold["pm_interval_shots"]):
        # a reversal that drops the counter back below the interval
        mold["service_state"] = "SERVICEABLE"
    # THRESHOLD GATE B — interim PPAP lapse, evaluated second.
    if (mold.get("interim_expiry_shots") is not None
            and mold["total_shot_count"] >= mold["interim_expiry_shots"]
            and mold["status"] == "INTERIM_APPROVED"):
        mold["status"] = "QUARANTINED"
        interim_fired = True

    if public(mold) != before:
        touch(mold)
    if pm_fired:
        block_scheduled_jobs(mold, "MOLD_PM_DUE")
    if interim_fired:
        block_scheduled_jobs(mold, "INTERIM_PPAP_EXPIRED")


def as_run_price(job):
    """quote_piece_price, variant as_run_actual."""
    quote = DB.quotes.get(job["quote_id"])
    mold = DB.molds.get(job["mold_id"])
    press = DB.presses.get(job["press_id"])
    if quote is None or mold is None or press is None:
        return
    _margin, _lot, piece = calcs.piece_price(
        cavitation=quote["cavitation"],
        cycle_time_sec=job["actual_cycle_time_sec"] or 0,
        hourly_rate_cents=press["hourly_rate_cents"],
        part_weight_grams=quote["part_weight_grams"],
        resin_price_cents_per_kg=quote["resin_price_cents_per_kg"],
        ownership=mold["ownership"],
        tooling_cost_cents=mold["tooling_cost_cents"],
        annual_volume=quote["annual_volume"],
        yield_bp=job["first_pass_yield_bp"],
    )
    job["as_run_piece_price_cents"] = piece
    quoted = quote.get("quoted_piece_price_cents")
    job["price_variance_cents"] = piece - quoted if quoted is not None else None
