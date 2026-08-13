"""Core business logic: posture evaluation, cost accounting, float selection,
week ledgers, incentive budget ledger, and the cross-entity cascades.

All formulas, constants, and rounding orders come from PRD sections 2.8-2.11
and 3.x / SCAFFOLD section 1.3.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

import db


# ---------------------------------------------------------------------------
# Domain constants (SCAFFOLD 1.3)
# ---------------------------------------------------------------------------

UNIT_TYPES = ("ICU", "STEP_DOWN", "MED_SURG", "TELEMETRY", "EMERGENCY")
ACUITY_LEVELS = ("LOW", "MODERATE", "HIGH", "CRITICAL")
SHIFT_CODES = ("DAY", "NIGHT")
EMPLOYMENT_TYPES = ("CORE", "FLOAT_POOL")

MIN_REQUIRED_NURSES = 2
CHARGE_MIN_REQUIRED = 2
OT_WEEKLY_THRESHOLD = Decimal("40")
OT_MULTIPLIER = Decimal("1.5")
MISSED_BREAK_PENALTY_CENTS = 5000
REFERENCE_RATE_CENTS = 6000
MAX_WEEK_PROJECTED_HOURS = 60.0
SCHEDULED_HOURS = 12.0

LIVE_ASSIGNMENT_STATUSES = ("PROPOSED", "ACCEPTED", "CONFIRMED")
COUNTED_ASSIGNMENT_STATUSES = ("ACCEPTED", "CONFIRMED")
TERMINAL_ASSIGNMENT_STATUSES = ("COMPLETED", "DECLINED", "CANCELLED")


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------

def pub(entity: dict) -> dict:
    """Public view: strip internal (underscore-prefixed) bookkeeping fields."""
    return {k: v for k, v in entity.items() if not k.startswith("_")}


def unit_view(unit: dict) -> dict:
    d = pub(unit)
    d["incentive_reserved_cents"] = incentive_reserved_cents(unit["id"])
    d["incentive_spent_cents"] = incentive_spent_cents(unit["id"])
    return d


# ---------------------------------------------------------------------------
# Week helpers (PRD 2.9: ISO week, Monday 00:00Z through Sunday)
# ---------------------------------------------------------------------------

def week_monday_of(shift_date_str: str) -> date:
    d = date.fromisoformat(shift_date_str)
    return d - timedelta(days=d.weekday())


def shift_of(assignment: dict) -> dict:
    return db.shifts[assignment["shift_id"]]


def assignments_of_nurse(nurse_id: str) -> list[dict]:
    return [a for a in db.assignments.values() if a["nurse_id"] == nurse_id]


def assignments_of_shift(shift_id: str) -> list[dict]:
    return [a for a in db.assignments.values() if a["shift_id"] == shift_id]


def live_assignments_of_nurse(nurse_id: str) -> list[dict]:
    return [a for a in assignments_of_nurse(nurse_id)
            if a["status"] in LIVE_ASSIGNMENT_STATUSES]


def projected_hours(nurse_id: str, monday: date) -> float:
    """12.0 x count of live (PROPOSED/ACCEPTED/CONFIRMED) assignments whose
    shift_date falls inside the ISO week starting `monday`."""
    count = 0
    for a in live_assignments_of_nurse(nurse_id):
        if week_monday_of(shift_of(a)["shift_date"]) == monday:
            count += 1
    return SCHEDULED_HOURS * count


def completed_hours(nurse_id: str, monday: date) -> float:
    """Sum of actual_hours_worked over COMPLETED assignments in the week."""
    total = 0.0
    for a in assignments_of_nurse(nurse_id):
        if a["status"] != "COMPLETED":
            continue
        if week_monday_of(shift_of(a)["shift_date"]) == monday:
            total += float(a.get("actual_hours_worked") or 0.0)
    return total


# ---------------------------------------------------------------------------
# Shift clock times (PRD 2.9)
# ---------------------------------------------------------------------------

def shift_window(shift_date_str: str, shift_code: str) -> tuple[datetime, datetime]:
    d = date.fromisoformat(shift_date_str)
    if shift_code == "DAY":
        start = datetime(d.year, d.month, d.day, 7, 0, tzinfo=timezone.utc)
        end = datetime(d.year, d.month, d.day, 19, 0, tzinfo=timezone.utc)
    else:  # NIGHT
        start = datetime(d.year, d.month, d.day, 19, 0, tzinfo=timezone.utc)
        nd = d + timedelta(days=1)
        end = datetime(nd.year, nd.month, nd.day, 7, 0, tzinfo=timezone.utc)
    return start, end


# ---------------------------------------------------------------------------
# Half-open interval overlap (PRD 2.11)
# ---------------------------------------------------------------------------

def intervals_overlap(a_start: datetime, a_end: datetime,
                      b_start: datetime, b_end: datetime) -> bool:
    """Half-open overlap: touching endpoints do NOT overlap."""
    return a_start < b_end and b_start < a_end


def nurse_has_overlap(nurse_id: str, new_start: datetime, new_end: datetime) -> bool:
    for a in live_assignments_of_nurse(nurse_id):
        s = shift_of(a)
        if intervals_overlap(s["_start_dt"], s["_end_dt"], new_start, new_end):
            return True
    return False


# ---------------------------------------------------------------------------
# Acuity -> required nurses (SCAFFOLD required_nurses_from_acuity)
# ---------------------------------------------------------------------------

def matrix_rule_for(unit_type: str, acuity_level: str) -> dict | None:
    for r in db.matrix_rules.values():
        if r["unit_type"] == unit_type and r["acuity_level"] == acuity_level:
            return r
    return None


def matrix_complete(unit_type: str) -> bool:
    return all(matrix_rule_for(unit_type, level) is not None for level in ACUITY_LEVELS)


def required_nurses_from_acuity(unit_type: str, census: dict) -> int:
    """ceil per acuity level, then sum, then floor at MIN_REQUIRED_NURSES.
    Per-level rounding-up is pinned to happen before summation."""
    total = 0
    for level, field in (("LOW", "census_low"), ("MODERATE", "census_moderate"),
                         ("HIGH", "census_high"), ("CRITICAL", "census_critical")):
        rule = matrix_rule_for(unit_type, level)
        ratio = rule["patients_per_nurse"]
        c = census[field]
        if c > 0:
            total += -(-c // ratio)  # ceil division
    return max(MIN_REQUIRED_NURSES, total)


# ---------------------------------------------------------------------------
# Staffing posture (SCAFFOLD staffing_posture_evaluation)
# ---------------------------------------------------------------------------

def evaluate_posture(effective: int, required: int, charge_covered: bool) -> str:
    if effective >= required and (required < CHARGE_MIN_REQUIRED or charge_covered):
        return "ADEQUATE"
    if effective >= required - 1:
        return "UNDERSTAFFED"
    return "CRITICAL"


def refresh_shift(shift: dict) -> bool:
    """Recompute the shift's derived fields from live data. Returns True when
    any field changed. Does NOT bump version/timestamp — callers own that so
    a multi-field cascade event costs exactly one version increment.

    counted_assignments / sitter_diversion_count / effective_assignments /
    charge_covered always track current state. staffing_posture and the
    OPEN<->STAFFED reconciliation only run while the shift is not LOCKED
    (posture freezes at lock).
    """
    assignments = assignments_of_shift(shift["id"])
    counted = sum(1 for a in assignments if a["status"] in COUNTED_ASSIGNMENT_STATUSES)
    assignment_ids = {a["id"] for a in assignments}
    diversion = sum(
        1 for s in db.sitter_requests.values()
        if s["status"] == "FILLED" and s.get("covering_assignment_id") in assignment_ids
    )
    charge_covered = any(
        a["status"] in COUNTED_ASSIGNMENT_STATUSES and a.get("is_charge")
        for a in assignments
    )

    changed = False
    for field, value in (
        ("counted_assignments", counted),
        ("sitter_diversion_count", diversion),
        ("effective_assignments", counted - diversion),
        ("charge_covered", charge_covered),
    ):
        if shift.get(field) != value:
            shift[field] = value
            changed = True

    if shift["status"] != "LOCKED":
        posture = evaluate_posture(counted - diversion, shift["required_nurses"], charge_covered)
        if shift["staffing_posture"] != posture:
            shift["staffing_posture"] = posture
            changed = True
        new_status = "STAFFED" if posture == "ADEQUATE" else "OPEN"
        if shift["status"] != new_status:
            shift["status"] = new_status
            changed = True

    return changed


def refresh_shift_and_touch(shift: dict) -> None:
    """Refresh derived fields; bump version once if anything changed."""
    if refresh_shift(shift):
        db.touch(shift)


# ---------------------------------------------------------------------------
# Assignment economics (SCAFFOLD provisional_assignment_cost /
# final_assignment_cost)
# ---------------------------------------------------------------------------

def provisional_economics(nurse: dict, shift: dict,
                          premium_multiplier, flat_bonus_cents: int) -> tuple[int, float]:
    """Forward-looking estimate stamped at assignment creation / offer claim.

    Single round-half-up to whole cents at the end of the formula.
    """
    monday = week_monday_of(shift["shift_date"])
    nid = nurse["id"]
    prior = Decimal(str(completed_hours(nid, monday)))
    prior += Decimal("12") * sum(
        1 for a in live_assignments_of_nurse(nid)
        if week_monday_of(shift_of(a)["shift_date"]) == monday
    )
    projected_ot = min(Decimal("12"), max(Decimal("0"), prior + Decimal("12") - OT_WEEKLY_THRESHOLD))
    rate = Decimal(nurse["base_hourly_rate_cents"])
    mult = Decimal(str(premium_multiplier))
    total = (
        (Decimal("12") - projected_ot) * rate * mult
        + projected_ot * rate * mult * OT_MULTIPLIER
        + Decimal(flat_bonus_cents)
    )
    cost = int(total.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    return cost, float(projected_ot)


def final_economics(nurse: dict, assignment: dict,
                    actual_hours_worked, missed_breaks: int) -> tuple[int, float]:
    """Settled cost at completion. Chronological completion-order OT
    accumulation; each component rounded half-up to whole cents BEFORE
    summation (pinned rounding order, PRD 2.8 / 3.8)."""
    shift = shift_of(assignment)
    monday = week_monday_of(shift["shift_date"])
    running = Decimal(str(completed_hours(nurse["id"], monday)))
    actual = Decimal(str(actual_hours_worked))
    final_ot = min(actual, max(Decimal("0"), running + actual - OT_WEEKLY_THRESHOLD))
    normal = actual - final_ot
    rate = Decimal(nurse["base_hourly_rate_cents"])
    mult = Decimal(str(assignment["premium_multiplier"]))
    normal_cost = (normal * rate * mult).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    ot_cost = (final_ot * rate * mult * OT_MULTIPLIER).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    final_cost = (
        int(normal_cost)
        + int(ot_cost)
        + MISSED_BREAK_PENALTY_CENTS * missed_breaks
        + assignment["flat_bonus_cents"]
    )
    return final_cost, float(final_ot)


# ---------------------------------------------------------------------------
# Assignment factory
# ---------------------------------------------------------------------------

def create_assignment(shift: dict, nurse: dict, source: str, status: str,
                      is_charge: bool = False, premium_multiplier=1.0,
                      flat_bonus_cents: int = 0) -> dict:
    cost, projected_ot = provisional_economics(nurse, shift, premium_multiplier, flat_bonus_cents)
    assignment = {
        "shift_id": shift["id"],
        "nurse_id": nurse["id"],
        "is_charge": bool(is_charge),
        "source": source,
        "status": status,
        "scheduled_hours": SCHEDULED_HOURS,
        "premium_multiplier": premium_multiplier,
        "flat_bonus_cents": flat_bonus_cents,
        "provisional_cost_cents": cost,
        "projected_ot_hours": projected_ot,
        "actual_hours_worked": None,
        "missed_breaks": None,
        "final_cost_cents": None,
        "final_ot_hours": None,
    }
    db.stamp_new(assignment)
    db.assignments[assignment["id"]] = assignment
    return assignment


# ---------------------------------------------------------------------------
# Incentive budget ledger (PRD 2.10) — computed on read
# ---------------------------------------------------------------------------

def _offers_of_unit(unit_id: str) -> list[dict]:
    out = []
    for o in db.offers.values():
        shift = db.shifts.get(o["shift_id"])
        if shift is not None and shift["unit_id"] == unit_id:
            out.append(o)
    return out


def incentive_reserved_cents(unit_id: str) -> int:
    return sum(o["premium_reserve_cents"] for o in _offers_of_unit(unit_id)
               if o["status"] in ("OFFERED", "CLAIMED"))


def incentive_spent_cents(unit_id: str) -> int:
    return sum(o["premium_reserve_cents"] for o in _offers_of_unit(unit_id)
               if o["status"] == "SETTLED")


def premium_reserve(premium_multiplier, flat_bonus_cents: int) -> int:
    """flat_bonus + round_half_up(12 * REFERENCE_RATE_CENTS * (multiplier - 1))."""
    mult = Decimal(str(premium_multiplier))
    prem = (Decimal("12") * Decimal(REFERENCE_RATE_CENTS) * (mult - Decimal("1"))).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP
    )
    return int(flat_bonus_cents) + int(prem)


def create_offer(shift: dict, premium_multiplier, flat_bonus_cents: int, origin: str) -> dict:
    offer = {
        "shift_id": shift["id"],
        "premium_multiplier": premium_multiplier,
        "flat_bonus_cents": flat_bonus_cents,
        "origin": origin,
        "premium_reserve_cents": premium_reserve(premium_multiplier, flat_bonus_cents),
        "status": "OFFERED",
        "claimed_nurse_id": None,
        "claimed_assignment_id": None,
    }
    db.stamp_new(offer)
    db.offers[offer["id"]] = offer
    return offer


def offered_offer_for_shift(shift_id: str) -> dict | None:
    for o in db.offers.values():
        if o["shift_id"] == shift_id and o["status"] == "OFFERED":
            return o
    return None


def maybe_auto_incentive_offer(shift: dict, posture_before: str, posture_after: str) -> None:
    """PRD 3.6: a confirmed-staff cancellation that flips posture from
    ADEQUATE to UNDERSTAFFED/CRITICAL arms an AUTO offer when the unit has
    auto_incentive_multiplier set, no OFFERED offer exists for the shift, and
    the reserve fits the remaining budget (silently skipped otherwise)."""
    if posture_before != "ADEQUATE" or posture_after not in ("UNDERSTAFFED", "CRITICAL"):
        return
    unit = db.units.get(shift["unit_id"])
    if unit is None:
        return
    mult = unit.get("auto_incentive_multiplier")
    if mult is None:
        return
    if offered_offer_for_shift(shift["id"]) is not None:
        return
    reserve = premium_reserve(mult, 0)
    if incentive_reserved_cents(unit["id"]) + reserve > unit["incentive_budget_cents"]:
        return  # silently skipped
    create_offer(shift, mult, 0, origin="AUTO")


# ---------------------------------------------------------------------------
# Float pool deployment (SCAFFOLD float_candidate_selection)
# ---------------------------------------------------------------------------

def select_float_candidate(shift: dict) -> dict | None:
    """Deterministic selector: FLOAT_POOL nurses with the unit's competency,
    no half-open overlap, and weekly headroom (projected + 12 <= 60); ranked
    by projected week hours ascending, ties broken by nurse.created_at
    ascending (never by id)."""
    unit = db.units.get(shift["unit_id"])
    if unit is None:
        return None
    monday = week_monday_of(shift["shift_date"])
    best = None
    best_key = None
    for nurse in db.nurses.values():
        if nurse["employment_type"] != "FLOAT_POOL":
            continue
        if unit["unit_type"] not in nurse["competencies"]:
            continue
        if nurse_has_overlap(nurse["id"], shift["_start_dt"], shift["_end_dt"]):
            continue
        ph = projected_hours(nurse["id"], monday)
        if ph + SCHEDULED_HOURS > MAX_WEEK_PROJECTED_HOURS:
            continue
        key = (ph, nurse["created_at"])
        if best_key is None or key < best_key:
            best_key = key
            best = nurse
    return best


def create_float_request(shift: dict, origin: str) -> dict:
    """Create a float request and run deployment synchronously (PRD 3.5)."""
    fr = {
        "shift_id": shift["id"],
        "origin": origin,
        "status": None,
        "deployed_nurse_id": None,
        "assignment_id": None,
    }
    db.stamp_new(fr)
    nurse = select_float_candidate(shift)
    if nurse is None:
        fr["status"] = "UNFULFILLED"
    else:
        assignment = create_assignment(shift, nurse, source="FLOAT", status="PROPOSED")
        fr["status"] = "DEPLOYED"
        fr["deployed_nurse_id"] = nurse["id"]
        fr["assignment_id"] = assignment["id"]
    db.float_requests[fr["id"]] = fr
    return fr


def float_request_for_assignment(assignment_id: str) -> dict | None:
    for fr in db.float_requests.values():
        if fr.get("assignment_id") == assignment_id:
            return fr
    return None


# ---------------------------------------------------------------------------
# Acuity governance + supersede cascade (PRD 3.2)
# ---------------------------------------------------------------------------

def governing_snapshot_for(unit_id: str, shift_date: str, shift_code: str) -> dict | None:
    """Latest non-SUPERSEDED snapshot for the slot."""
    for s in db.snapshots.values():
        if (
            s["unit_id"] == unit_id
            and s["shift_date"] == shift_date
            and s["shift_code"] == shift_code
            and s["status"] != "SUPERSEDED"
        ):
            return s
    return None


def shift_for_slot(unit_id: str, shift_date: str, shift_code: str) -> dict | None:
    for s in db.shifts.values():
        if (
            s["unit_id"] == unit_id
            and s["shift_date"] == shift_date
            and s["shift_code"] == shift_code
        ):
            return s
    return None


def supersede_cascade(new_snapshot: dict) -> None:
    """Fire the supersede cascade into the matching shift, if one exists.

    The shift's governing snapshot is re-pointed, required_nurses recomputed,
    and the shift version advances by exactly one for the cascade event; the
    posture re-evaluation and OPEN<->STAFFED reconciliation ride the same
    bump. While the shift is not LOCKED, a resulting CRITICAL posture with no
    DEPLOYED float request arms an AUTO_ACUITY float request with synchronous
    deployment.
    """
    shift = shift_for_slot(
        new_snapshot["unit_id"], new_snapshot["shift_date"], new_snapshot["shift_code"]
    )
    if shift is None:
        return
    shift["governing_snapshot_id"] = new_snapshot["id"]
    shift["required_nurses"] = new_snapshot["required_nurses"]
    if shift["status"] != "LOCKED":
        refresh_shift(shift)
    db.touch(shift)  # the single pinned +1 for the cascade
    if shift["status"] == "LOCKED":
        return  # posture frozen at lock; no reconciliation, no auto float
    if shift["staffing_posture"] == "CRITICAL":
        has_deployed = any(
            fr["shift_id"] == shift["id"] and fr["status"] == "DEPLOYED"
            for fr in db.float_requests.values()
        )
        if not has_deployed:
            create_float_request(shift, origin="AUTO_ACUITY")


# ---------------------------------------------------------------------------
# Shift lock cascade (PRD 3.3)
# ---------------------------------------------------------------------------

def lock_shift(shift: dict) -> None:
    shift["posture_at_lock"] = shift["staffing_posture"]
    shift["counted_at_lock"] = shift["counted_assignments"]
    shift["status"] = "LOCKED"
    db.touch(shift)

    # Every still-PROPOSED assignment is cancelled with its projected-hours
    # release; a DEPLOYED float request behind such an assignment is released.
    for a in assignments_of_shift(shift["id"]):
        if a["status"] != "PROPOSED":
            continue
        a["status"] = "CANCELLED"
        db.touch(a)
        if a["source"] == "FLOAT":
            fr = float_request_for_assignment(a["id"])
            if fr is not None and fr["status"] == "DEPLOYED":
                fr["status"] = "RELEASED"
                db.touch(fr)

    # Every OFFERED incentive offer on the shift expires (reserve released).
    for o in db.offers.values():
        if o["shift_id"] == shift["id"] and o["status"] == "OFFERED":
            o["status"] = "EXPIRED"
            db.touch(o)


# ---------------------------------------------------------------------------
# Sitter helpers (PRD 3.7)
# ---------------------------------------------------------------------------

def assignment_covers_filled_sitter(assignment_id: str) -> bool:
    return any(
        s["status"] == "FILLED" and s.get("covering_assignment_id") == assignment_id
        for s in db.sitter_requests.values()
    )


def find_covering_assignment(nurse_id: str, unit_id: str,
                             window_start: datetime, window_end: datetime) -> dict | None:
    """A CONFIRMED assignment of the nurse on the unit whose shift interval
    fully contains the sitter window and which does not already cover a
    FILLED sitter request."""
    candidates = []
    for a in assignments_of_nurse(nurse_id):
        if a["status"] != "CONFIRMED":
            continue
        shift = shift_of(a)
        if shift["unit_id"] != unit_id:
            continue
        if shift["_start_dt"] <= window_start and shift["_end_dt"] >= window_end:
            if assignment_covers_filled_sitter(a["id"]):
                continue
            candidates.append(a)
    if not candidates:
        return None
    candidates.sort(key=lambda a: a["created_at"])
    return candidates[0]


# ---------------------------------------------------------------------------
# Compliance reporting (SCAFFOLD compliance_fill_rates)
# ---------------------------------------------------------------------------

def compute_report_figures(report_date: str) -> dict:
    included = [
        s for s in db.shifts.values()
        if s["shift_date"] == report_date and s["status"] == "LOCKED"
    ]
    included.sort(key=lambda s: s["created_at"])

    ratios: list[Decimal] = []
    censuses: list[int] = []
    understaffed = 0
    for s in included:
        required = s["required_nurses"]
        counted = s["counted_at_lock"] if s["counted_at_lock"] is not None else 0
        ratio = Decimal(counted) / Decimal(required)
        if ratio > Decimal("1"):
            ratio = Decimal("1")
        ratios.append(ratio)
        snapshot = db.snapshots.get(s["governing_snapshot_id"] or "")
        censuses.append(snapshot["total_census"] if snapshot is not None else 0)
        if counted < required:
            understaffed += 1

    n = len(included)
    shift_weighted = (Decimal("100") * sum(ratios) / Decimal(n)).quantize(
        Decimal("0.1"), rounding=ROUND_HALF_UP
    )
    total_census = sum(censuses)
    if total_census == 0:
        census_weighted = shift_weighted
    else:
        weighted_sum = sum(r * Decimal(c) for r, c in zip(ratios, censuses))
        census_weighted = (Decimal("100") * weighted_sum / Decimal(total_census)).quantize(
            Decimal("0.1"), rounding=ROUND_HALF_UP
        )

    return {
        "shifts_included_count": n,
        "understaffed_shift_count": understaffed,
        "fill_rate_shift_weighted_pct": float(shift_weighted),
        "fill_rate_census_weighted_pct": float(census_weighted),
    }
