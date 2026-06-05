"""Calculations and derived-field recomputation (SCAFFOLD §1.3 / PRD §2.7, §3).

Every function here is pure with respect to its inputs except the recompute_*
helpers, which mutate-and-touch the resource that owns the derived field
(PRD §2.4: recomputation counts as a mutation -> updated_at + version bump).
"""
from datetime import timedelta

import db
from helpers import round_half_up_2

# --- Constant weight/rank tables (SCAFFOLD §1.3) ---------------------------
CRIT_WEIGHTS = {"LOW": 1, "MEDIUM": 2, "HIGH": 4, "CRITICAL": 8}
SEV_WEIGHTS = {"ROUTINE": 1, "MAJOR": 3, "OVERHAUL": 5}
SEV_RANK = {"ROUTINE": 1, "MAJOR": 2, "OVERHAUL": 3}
SKILL_RANK = {"JUNIOR": 1, "SENIOR": 2, "MASTER": 3}
OVERRUN_FLOOR = 1.0
OVERRUN_CEIL = 3.0
CORRECTIVE_BUMP = 10
FAILURE_CODES = {"MECHANICAL_FAILURE", "ELECTRICAL_FAILURE"}


# ---------------------------------------------------------------------------
# calc_pm_next_due (SCAFFOLD §1.3, PRD §3.3) — DUAL VARIANT by trigger_type.
# Mutates the schedule's next_due_meter / next_due_date in place. The caller
# decides whether this constitutes a mutation worth touch()-ing (on create the
# record is being built; on rebase the caller touches it).
# ---------------------------------------------------------------------------
def compute_next_due(schedule):
    if schedule["trigger_type"] == "METER":
        schedule["next_due_meter"] = schedule["anchor_meter"] + schedule["meter_interval"]
        schedule["next_due_date"] = None
    else:  # CALENDAR
        anchor = db.parse_stored_dt(schedule["anchor_date"])
        due = anchor + timedelta(days=schedule["calendar_interval_days"])
        schedule["next_due_date"] = db.iso(due)
        schedule["next_due_meter"] = None


def is_due(schedule, asset):
    """Boundary inclusive (>=) per PRD §3.3."""
    if not schedule.get("active", True):
        return False
    if schedule["trigger_type"] == "METER":
        return asset["meter_reading"] >= schedule["next_due_meter"]
    else:  # CALENDAR
        now = db.logical_now()
        due = db.parse_stored_dt(schedule["next_due_date"])
        return now >= due


# ---------------------------------------------------------------------------
# calc_priority_score (SCAFFOLD §1.3, PRD §3.4) — computed once, frozen.
# ---------------------------------------------------------------------------
def priority_score(asset, work_order, pm_schedule):
    crit_weight = CRIT_WEIGHTS[asset["criticality"]]
    sev_weight = SEV_WEIGHTS[work_order["severity"]]
    overrun = 1.0
    if (work_order["wo_type"] == "PREVENTIVE"
            and pm_schedule is not None
            and pm_schedule["trigger_type"] == "METER"):
        denom = pm_schedule["next_due_meter"]
        if denom is None or denom < 1:
            denom = 1
        raw = asset["meter_reading"] / denom
        overrun = min(max(raw, OVERRUN_FLOOR), OVERRUN_CEIL)
    base = crit_weight * sev_weight * overrun
    bump = CORRECTIVE_BUMP if work_order["wo_type"] == "CORRECTIVE" else 0
    return round_half_up_2(base + bump)


# ---------------------------------------------------------------------------
# calc_skill_gate (SCAFFOLD §1.3, PRD §3.5).
# ---------------------------------------------------------------------------
def skill_eligible(technician, work_order):
    return SKILL_RANK[technician["skill_level"]] >= SEV_RANK[work_order["severity"]]


# ---------------------------------------------------------------------------
# calc_warranty_payable (SCAFFOLD §1.3, PRD §3.9) — basis FIRST, then cap.
# ---------------------------------------------------------------------------
def warranty_payable(claim, asset, work_order):
    if claim["claim_type"] == "REPLACEMENT":
        claimed = asset["acquisition_cost_cents"]
    else:  # REPAIR
        claimed = work_order["actual_cost_cents"]
    cap = asset["warranty_cost_cap_cents"]
    if cap is None:
        payable = claimed
    else:
        payable = min(claimed, cap)
    return claimed, payable


# ---------------------------------------------------------------------------
# calc_mtbf (SCAFFOLD §1.3, PRD §3.8) — mean of consecutive start-to-start gaps
# over FAILURE-class downtime (open OR resolved), ordered by started_at ASC,
# tie-break created_at ASC. 0 when fewer than 2 failures.
# ---------------------------------------------------------------------------
def recompute_mtbf(asset):
    failures = [
        d for d in db.downtime_events.values()
        if d["asset_id"] == asset["id"] and d["reason_code"] in FAILURE_CODES
    ]
    failures.sort(key=lambda d: (db.parse_stored_dt(d["started_at"]), d["_seq"]))
    if len(failures) < 2:
        new_val = 0
    else:
        gaps = []
        for i in range(1, len(failures)):
            a = db.parse_stored_dt(failures[i - 1]["started_at"])
            b = db.parse_stored_dt(failures[i]["started_at"])
            gaps.append((b - a).total_seconds() / 3600.0)
        new_val = round_half_up_2(sum(gaps) / len(gaps))
    if asset["mtbf_hours"] != new_val:
        asset["mtbf_hours"] = new_val
        db.touch(asset)
    else:
        asset["mtbf_hours"] = new_val


# ---------------------------------------------------------------------------
# calc_mttr (SCAFFOLD §1.3, PRD §3.8) — mean duration_hours over RESOLVED
# FAILURE-class downtime. 0 when none.
# ---------------------------------------------------------------------------
def recompute_mttr(asset):
    repaired = [
        d for d in db.downtime_events.values()
        if d["asset_id"] == asset["id"]
        and d["status"] == "RESOLVED"
        and d["reason_code"] in FAILURE_CODES
    ]
    if not repaired:
        new_val = 0
    else:
        new_val = round_half_up_2(
            sum(d["duration_hours"] for d in repaired) / len(repaired))
    if asset["mttr_hours"] != new_val:
        asset["mttr_hours"] = new_val
        db.touch(asset)
    else:
        asset["mttr_hours"] = new_val


# ---------------------------------------------------------------------------
# Derived-field reconciliation helpers.
# ---------------------------------------------------------------------------
def recompute_reserved_qty(part):
    """SparePart.reserved_qty = sum qty over reservations RESERVED or COMMITTED
    (PRD §3.1). Counts as a mutation of the part (PRD §2.4)."""
    total = sum(
        r["qty"] for r in db.part_reservations.values()
        if r["spare_part_id"] == part["id"] and r["status"] in ("RESERVED", "COMMITTED")
    )
    part["reserved_qty"] = total
    db.touch(part)


def recompute_backlog(technician):
    """Technician.backlog_hours = sum estimated_labor_hours over WOs assigned to
    this tech with execution_status in {ASSIGNED, IN_PROGRESS, ON_HOLD}
    (PRD §3.1). Counts as a mutation of the technician (PRD §2.4)."""
    total = 0
    for wo in db.work_orders.values():
        if (wo["assigned_technician_id"] == technician["id"]
                and wo["execution_status"] in ("ASSIGNED", "IN_PROGRESS", "ON_HOLD")):
            total += wo["estimated_labor_hours"]
    technician["backlog_hours"] = total
    db.touch(technician)


def recompute_meter_reading(asset):
    """Asset.meter_reading = value of the latest MeterReading by reading_at
    (tie-break created_at ASC), else 0 (PRD §3.2)."""
    readings = [r for r in db.meter_readings.values() if r["asset_id"] == asset["id"]]
    if not readings:
        asset["meter_reading"] = 0
        return
    readings.sort(key=lambda r: (db.parse_stored_dt(r["reading_at"]), r["_seq"]))
    asset["meter_reading"] = readings[-1]["value"]


def recompute_site_budget(site):
    """Site.budget_spent_cents = sum actual_cost_cents over CLOSED work orders
    whose asset belongs to this site AND whose cost was NOT covered by an
    APPROVED warranty claim (PRD §3.1). Counts as a mutation (PRD §2.4)."""
    total = 0
    for wo in db.work_orders.values():
        if wo["execution_status"] != "CLOSED":
            continue
        asset = db.assets.get(wo["asset_id"])
        if asset is None or asset["site_id"] != site["id"]:
            continue
        if wo.get("warranty_claim_id"):
            claim = db.warranty_claims.get(wo["warranty_claim_id"])
            if claim is not None and claim["status"] == "APPROVED":
                continue
        total += wo["actual_cost_cents"]
    site["budget_spent_cents"] = total
    db.touch(site)
