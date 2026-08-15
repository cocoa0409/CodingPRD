"""Domain logic for the Physician Call Schedule & Locum Coverage API.

Implements the scaffold calculation rules (slot_generation_plan,
rotation_auto_assignment, fairness_points, moonlight_rolling_hours, call_pay,
program_payroll_total, coverage_compliance) and the cascade machinery shared by
the state machines (§1.2). All "now" references read the logical clock (§2.5).
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

import db
from db import store
from errors import ApiError

CALL_HOURS = 24
ROLLING_WINDOW_DAYS = 28  # closed date window [D-27, D]
ACTIVATION_GRACE = timedelta(hours=2)

PROSPECTIVE_STATUSES = ("SCHEDULED", "ACTIVATED", "SERVED")
ACTUAL_STATUSES = ("SERVED",)
NON_TERMINAL_SWAP_STATUSES = ("POSTED", "CLAIMED", "APPROVED")
ACTIVE_REQUISITION_STATUSES = ("OPEN", "SOURCED", "CREDENTIALING")

CREDENTIAL_ITEMS = [
    "license_verification",
    "malpractice_verification",
    "privileges_granting",
    "health_screening",
    "orientation",
]


# ---------------------------------------------------------------------------
# Calendar helpers (PRD §2.6)
# ---------------------------------------------------------------------------

def parse_date(s):
    return datetime.strptime(s, "%Y-%m-%d").date()


def fmt_date(d):
    return d.strftime("%Y-%m-%d")


def date_type_of(program, date_str):
    """HOLIDAY > WEEKEND > WEEKDAY precedence (pinned)."""
    if date_str in (program.get("holiday_dates") or []):
        return "HOLIDAY"
    if parse_date(date_str).weekday() >= 5:  # Saturday=5, Sunday=6
        return "WEEKEND"
    return "WEEKDAY"


def window_start_of(date_str):
    d = parse_date(date_str)
    return datetime(d.year, d.month, d.day, 7, 0, 0, tzinfo=timezone.utc)


def window_end_of(date_str):
    return window_start_of(date_str) + timedelta(hours=CALL_HOURS)


def period_dates(program):
    """Closed interval [period_start, period_end], ascending."""
    d = parse_date(program["period_start"])
    end = parse_date(program["period_end"])
    out = []
    while d <= end:
        out.append(fmt_date(d))
        d += timedelta(days=1)
    return out


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------

def slot_of(assignment):
    return store.slots.get(assignment["slot_id"])


def program_of_assignment(assignment):
    return store.programs.get(assignment["program_id"])


def assignments_of_physician(physician_id, statuses=None):
    rows = [a for a in store.assignments.values() if a["physician_id"] == physician_id]
    if statuses is not None:
        rows = [a for a in rows if a["status"] in statuses]
    return rows


def assignments_of_program(program_id):
    return [a for a in store.assignments.values() if a["program_id"] == program_id]


def slots_of_program(program_id):
    return [s for s in store.slots.values() if s["program_id"] == program_id]


# ---------------------------------------------------------------------------
# Eligibility predicates (PRD §2.6/§2.9, scaffold §1.3)
# ---------------------------------------------------------------------------

def windows_half_open_overlap(a_start, a_end, b_start, b_end):
    """Half-open overlap: merely touching at 07:00Z does not conflict."""
    return a_start < b_end and b_start < a_end


def has_overlapping_assignment(physician_id, slot):
    """Half-open window overlap against {SCHEDULED, ACTIVATED, SERVED} assignments."""
    for a in assignments_of_physician(physician_id, PROSPECTIVE_STATUSES):
        s = slot_of(a)
        if s is None:
            continue
        if windows_half_open_overlap(s["window_start"], s["window_end"],
                                     slot["window_start"], slot["window_end"]):
            return True
    return False


def has_approved_window_covering(physician_id, date_str):
    """Closed containment: start_date <= date <= end_date."""
    d = parse_date(date_str)
    for w in store.windows.values():
        if w["physician_id"] != physician_id or w["status"] != "APPROVED":
            continue
        if parse_date(w["start_date"]) <= d <= parse_date(w["end_date"]):
            return True
    return False


def rolling_hours(physician_id, slot_date_str, statuses, through_previous_day=False):
    """call_hours sum over assignments in `statuses` with slot date in the closed
    window [D-27, D] (projected variant / cap check), or [D-27, D-1] when
    through_previous_day is set (premium tier: strictly before D)."""
    d = parse_date(slot_date_str)
    lo = d - timedelta(days=ROLLING_WINDOW_DAYS - 1)
    hi = d - timedelta(days=1) if through_previous_day else d
    total = 0
    for a in assignments_of_physician(physician_id, statuses):
        s = slot_of(a)
        if s is None:
            continue
        sd = parse_date(s["date"])
        if lo <= sd <= hi:
            total += a["call_hours"]
    return total


def check_moonlight_cap(physician, slot_date_str):
    """Projected hours + 24 <= moonlight_cap_hours (equality allowed). STAFF only."""
    if physician["employment_type"] != "STAFF":
        return
    projected = rolling_hours(physician["id"], slot_date_str, PROSPECTIVE_STATUSES)
    if projected + CALL_HOURS > physician["moonlight_cap_hours"]:
        raise ApiError("ERR_MOONLIGHT_CAP_EXCEEDED", 409,
                       "Projected rolling 28-day hours plus 24 exceed moonlight_cap_hours")


def premium_reached(program, physician, slot_date_str, variant):
    """Premium tier (STAFF only; >= semantics). variant: 'projected' evaluates the
    SCHEDULED/ACTIVATED/SERVED hour set; 'served' evaluates SERVED hours only —
    both over dates strictly before the slot date (PRD §2.9)."""
    if physician["employment_type"] != "STAFF":
        return False
    statuses = PROSPECTIVE_STATUSES if variant == "projected" else ACTUAL_STATUSES
    hours = rolling_hours(physician["id"], slot_date_str, statuses,
                          through_previous_day=True)
    return hours >= int(program["moonlight_premium_threshold_hours"])


# ---------------------------------------------------------------------------
# Fairness points (scaffold fairness_points; PRD §2.8)
# ---------------------------------------------------------------------------

def slot_points(program, slot):
    """Per-slot points, rounded half-up to 2 decimals PER SLOT (pinned order)."""
    base = {
        "WEEKDAY": program["weekday_call_points"],
        "WEEKEND": program["weekend_call_points"],
        "HOLIDAY": program["holiday_call_points"],
    }[slot["date_type"]]
    mult = program["backup_point_multiplier"] if slot["call_type"] == "BACKUP" else Decimal("1")
    return (Decimal(base) * Decimal(mult)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def program_point_totals(program):
    """physician_id -> [prospective, actual, undesirable_prospective] (Decimals)."""
    table = {}
    for a in store.assignments.values():
        if a["program_id"] != program["id"]:
            continue
        s = slot_of(a)
        if s is None:
            continue
        sp = slot_points(program, s)
        entry = table.setdefault(a["physician_id"], [Decimal("0"), Decimal("0"), Decimal("0")])
        if a["status"] in PROSPECTIVE_STATUSES:
            entry[0] += sp
            if s["date_type"] in ("WEEKEND", "HOLIDAY"):
                entry[2] += sp
        if a["status"] in ACTUAL_STATUSES:
            entry[1] += sp
    return table


def two_dp(x):
    return Decimal(x).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# Pay variants (scaffold call_pay; PRD §3.3) and payroll totals (§2.7)
# ---------------------------------------------------------------------------

def date_multiplier(program, slot):
    if slot["date_type"] == "HOLIDAY":
        return Decimal(program["holiday_multiplier"])
    if slot["date_type"] == "WEEKEND":
        return Decimal(program["weekend_multiplier"])
    return Decimal("1")


def base_rate_for(program, slot):
    return int(program["primary_rate_cents"] if slot["call_type"] == "PRIMARY"
               else program["backup_rate_cents"])


def compute_projected_pay(program, slot, physician):
    """Projected variant: activation assumed false; premium from projected hours.
    Exactly one round-half-up step to whole cents after all multipliers."""
    base = base_rate_for(program, slot)
    prem = Decimal(program["moonlight_premium_multiplier"]) \
        if premium_reached(program, physician, slot["date"], "projected") else Decimal("1")
    amount = (Decimal(base) * date_multiplier(program, slot) * Decimal("1") * prem)
    return int(amount.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def compute_actual_pay(program, slot, physician, was_activated):
    """Actual variant at mark-served: true activation flag, served-only premium hours."""
    base = base_rate_for(program, slot)
    act = Decimal(program["backup_activation_multiplier"]) if was_activated else Decimal("1")
    prem_hit = premium_reached(program, physician, slot["date"], "served")
    prem = Decimal(program["moonlight_premium_multiplier"]) if prem_hit else Decimal("1")
    amount = (Decimal(base) * date_multiplier(program, slot) * act * prem)
    return int(amount.quantize(Decimal("1"), rounding=ROUND_HALF_UP)), prem_hit


def sync_program_totals(program):
    """payroll_reserved_cents = SUM projected over {SCHEDULED, ACTIVATED};
    payroll_accrued_cents = SUM amount over PayEntries {ACCRUED, FINALIZED}
    (per-entry rounding pinned; totals sum already-rounded integers)."""
    reserved = sum(int(a["projected_pay_cents"]) for a in store.assignments.values()
                   if a["program_id"] == program["id"] and a["status"] in ("SCHEDULED", "ACTIVATED"))
    accrued = sum(int(p["amount_cents"]) for p in store.pay_entries.values()
                  if p["program_id"] == program["id"] and p["status"] in ("ACCRUED", "FINALIZED"))
    if program["payroll_reserved_cents"] != reserved or program["payroll_accrued_cents"] != accrued:
        program["payroll_reserved_cents"] = reserved
        program["payroll_accrued_cents"] = accrued
        program["updated_at"] = db.wall_now()


def check_payroll_budget(program, new_projected_pay_cents):
    """Fiscal gate (priority 11): reserve + new projected <= budget (equality allowed)."""
    if int(program["payroll_reserved_cents"]) + int(new_projected_pay_cents) \
            > int(program["payroll_budget_cents"]):
        raise ApiError("ERR_PAYROLL_BUDGET_EXCEEDED", 402,
                       "payroll_reserved_cents plus new projected pay exceeds payroll_budget_cents")


# ---------------------------------------------------------------------------
# Assignment creation / cancellation cascades (scaffold §1.2 CallSlot hops)
# ---------------------------------------------------------------------------

def resolve_gap_for_slot(slot, assignment):
    """Hop 2 of assignment creation: an OPEN or REQUISITIONED gap for the slot
    becomes RESOLVED; a live requisition attached to it is CANCELLED (hop 3)
    along with its active credentialing case."""
    for gap in store.gaps.values():
        if gap["slot_id"] != slot["id"] or gap["status"] not in ("OPEN", "REQUISITIONED"):
            continue
        was_requisitioned = gap["status"] == "REQUISITIONED"
        gap["status"] = "RESOLVED"
        gap["resolved_by_assignment_id"] = assignment["id"]
        db.touch(gap)
        if was_requisitioned:
            for req in store.requisitions.values():
                if req["gap_id"] == gap["id"] and req["status"] in ACTIVE_REQUISITION_STATUSES:
                    req["status"] = "CANCELLED"
                    req["candidate_physician_id"] = None
                    db.touch(req)
                    for case in store.cases.values():
                        if case["requisition_id"] == req["id"] \
                                and case["status"] in ("INITIATED", "IN_PROGRESS"):
                            case["status"] = "CANCELLED"
                            db.touch(case)


def create_assignment(program, slot, physician, origin, source_swap_id=None,
                      source_requisition_id=None):
    """Shared assignment-creation cascade: projected pay (projected variant),
    slot OPEN -> ASSIGNED, active gap resolution, reserve increase."""
    projected = compute_projected_pay(program, slot, physician)
    assignment = db.new_common({
        "slot_id": slot["id"],
        "physician_id": physician["id"],
        "program_id": program["id"],
        "origin": origin,
        "source_swap_id": source_swap_id,
        "source_requisition_id": source_requisition_id,
        "call_hours": CALL_HOURS,
        "projected_pay_cents": projected,
        "status": "SCHEDULED",
        "activated_at": None,
        "served_at": None,
    })
    store.assignments[assignment["id"]] = assignment
    slot["status"] = "ASSIGNED"
    db.touch(slot)
    resolve_gap_for_slot(slot, assignment)
    sync_program_totals(program)
    return assignment


def cancel_non_terminal_swaps_for_assignment(assignment_id):
    for sw in store.swaps.values():
        if sw["assignment_id"] == assignment_id and sw["status"] in NON_TERMINAL_SWAP_STATUSES:
            sw["status"] = "CANCELLED"
            db.touch(sw)


def open_gap(program, slot, reason):
    gap = db.new_common({
        "program_id": program["id"],
        "slot_id": slot["id"],
        "reason": reason,
        "detected_at": db.now_logical(),
        "resolved_by_assignment_id": None,
        "status": "OPEN",
    })
    store.gaps[gap["id"]] = gap
    return gap


def cancel_assignment_cascade(assignment, reason):
    """SCHEDULED -> CANCELLED with slot reopen, gap opening, reserve release,
    and non-terminal swap cancellation (hops 1-2 of §1.2).

    Gap semantics: cancelling an assignment that had itself resolved a coverage
    gap re-opens THAT gap (status OPEN, resolved_by cleared, reason re-stamped);
    otherwise a fresh gap is opened. This keeps one live gap record per slot
    across OPEN -> ASSIGNED -> OPEN cycles (PRD §3.3: "a slot may cycle any
    number of times before it is finally COVERED")."""
    program = program_of_assignment(assignment)
    slot = slot_of(assignment)
    assignment["status"] = "CANCELLED"
    db.touch(assignment)
    if slot is not None and slot["status"] == "ASSIGNED":
        slot["status"] = "OPEN"
        db.touch(slot)
    if slot is not None:
        reopened = False
        for g in store.gaps.values():
            if g["slot_id"] == slot["id"] and g["status"] == "RESOLVED" \
                    and g.get("resolved_by_assignment_id") == assignment["id"]:
                g["status"] = "OPEN"
                g["resolved_by_assignment_id"] = None
                g["reason"] = reason
                g["detected_at"] = db.now_logical()
                db.touch(g)
                reopened = True
                break
        if not reopened:
            open_gap(program, slot, reason)
    cancel_non_terminal_swaps_for_assignment(assignment["id"])
    sync_program_totals(program)
    return program


# ---------------------------------------------------------------------------
# Slot generation + rotation auto-assignment (scaffold slot_generation_plan /
# rotation_auto_assignment; PRD §3.1)
# ---------------------------------------------------------------------------

def generate_slots(program):
    """Create CallSlots for every date in the closed period per the six required
    counts; HOLIDAY > WEEKEND > WEEKDAY date_type precedence; 1-based
    position_index within each same-date same-call_type group."""
    created = []
    for date_str in period_dates(program):
        dt = date_type_of(program, date_str)
        plan = (("PRIMARY", int(program["%s_primary_required" % dt.lower()])),
                ("BACKUP", int(program["%s_backup_required" % dt.lower()])))
        for call_type, count in plan:
            for i in range(1, count + 1):
                slot = db.new_common({
                    "program_id": program["id"],
                    "date": date_str,
                    "call_type": call_type,
                    "position_index": i,
                    "date_type": dt,
                    "window_start": window_start_of(date_str),
                    "window_end": window_end_of(date_str),
                    "status": "OPEN",
                })
                store.slots[slot["id"]] = slot
                created.append(slot)
    return created


def _eligible_pool(program, slot):
    pool = []
    for p in store.physicians.values():
        if p["employment_type"] != "STAFF" or p["status"] != "ACTIVE":
            continue
        if p["specialty"] != program["service_line"]:
            continue
        if has_approved_window_covering(p["id"], slot["date"]):
            continue
        if has_overlapping_assignment(p["id"], slot):
            continue
        projected = rolling_hours(p["id"], slot["date"], PROSPECTIVE_STATUSES)
        if projected + CALL_HOURS > p["moonlight_cap_hours"]:
            continue
        pool.append(p)
    return pool


def rotation_auto_assignment(program, slots):
    """PRIMARY slots in (date ASC, position_index ASC), then BACKUP likewise.
    Ranking: lowest prospective total points (incl. tentative), then lowest
    prospective undesirable points, then earliest physician created_at.
    Empty pool -> slot stays OPEN + CoverageGap(GENERATION_SHORTFALL)."""
    ordered = sorted((s for s in slots if s["call_type"] == "PRIMARY"),
                     key=lambda s: (s["date"], s["position_index"])) \
        + sorted((s for s in slots if s["call_type"] == "BACKUP"),
                 key=lambda s: (s["date"], s["position_index"]))
    for slot in ordered:
        pool = _eligible_pool(program, slot)
        if not pool:
            open_gap(program, slot, "GENERATION_SHORTFALL")
            continue
        totals = program_point_totals(program)

        def rank(p):
            entry = totals.get(p["id"], [Decimal("0"), Decimal("0"), Decimal("0")])
            return (entry[0], entry[2], p["created_at"], p.get("_seq", 0))

        winner = min(pool, key=rank)
        create_assignment(program, slot, winner, "GENERATED")


# ---------------------------------------------------------------------------
# Reports (scaffold coverage_compliance; PRD §3.6)
# ---------------------------------------------------------------------------

def fairness_report(program):
    totals = program_point_totals(program)
    population = []
    for pid, (prosp, actual, _und) in totals.items():
        # Population: physicians with >= 1 assignment in {SCHEDULED, ACTIVATED, SERVED}.
        has_prospective = any(
            a["program_id"] == program["id"] and a["physician_id"] == pid
            and a["status"] in PROSPECTIVE_STATUSES
            for a in store.assignments.values())
        if has_prospective:
            population.append((pid, prosp, actual))
    population.sort(key=lambda row: (store.physicians[row[0]]["created_at"]
                                     if row[0] in store.physicians else "",
                                     store.physicians[row[0]].get("_seq", 0)
                                     if row[0] in store.physicians else 0))
    total_prosp = sum((r[1] for r in population), Decimal("0"))
    total_actual = sum((r[2] for r in population), Decimal("0"))
    size = len(population)
    mean_prosp = two_dp(total_prosp / size) if size else Decimal("0.00")
    mean_actual = two_dp(total_actual / size) if size else Decimal("0.00")
    entries = [{
        "physician_id": pid,
        "full_name": store.physicians[pid]["full_name"] if pid in store.physicians else None,
        "prospective_points": prosp,
        "actual_points": actual,
    } for pid, prosp, actual in population]
    return {
        "program_id": program["id"],
        "population_size": size,
        "total_prospective_points": two_dp(total_prosp),
        "total_actual_points": two_dp(total_actual),
        "mean_prospective_points": mean_prosp,
        "mean_actual_points": mean_actual,
        "equity_band_points": program["equity_band_points"],
        "entries": entries,
    }


def coverage_report(program):
    dates = []
    compliant = 0
    noncompliant = 0
    for date_str in period_dates(program):
        dt = date_type_of(program, date_str)
        req_primary = int(program["%s_primary_required" % dt.lower()])
        req_backup = int(program["%s_backup_required" % dt.lower()])
        day_slots = [s for s in store.slots.values()
                     if s["program_id"] == program["id"] and s["date"] == date_str]
        cov_primary = sum(1 for s in day_slots if s["call_type"] == "PRIMARY"
                          and s["status"] in ("ASSIGNED", "COVERED"))
        cov_backup = sum(1 for s in day_slots if s["call_type"] == "BACKUP"
                         and s["status"] in ("ASSIGNED", "COVERED"))
        is_compliant = cov_primary >= req_primary and cov_backup >= req_backup
        if is_compliant:
            compliant += 1
        else:
            noncompliant += 1
        dates.append({
            "date": date_str,
            "date_type": dt,
            "required_primary": req_primary,
            "covered_primary": cov_primary,
            "shortfall_primary": max(0, req_primary - cov_primary),
            "required_backup": req_backup,
            "covered_backup": cov_backup,
            "shortfall_backup": max(0, req_backup - cov_backup),
            "compliant": is_compliant,
        })
    open_gaps = sum(1 for g in store.gaps.values()
                    if g["program_id"] == program["id"] and g["status"] in ("OPEN", "REQUISITIONED"))
    return {
        "program_id": program["id"],
        "compliant_date_count": compliant,
        "noncompliant_date_count": noncompliant,
        "open_gap_count": open_gaps,
        "dates": dates,
    }
