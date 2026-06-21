"""Renewal-cycle calculation engine and derived-state machine.

Implements (PRD §3.5/§3.6, SCAFFOLD §1.3):
  - credit_tally            (provisional + final earned hours)
  - requirement_satisfaction (waterfall allocation, MET test)
  - carryover_computation    (per-category round -> sum -> cap)
  - deadline_reminder        (NOT_DUE / DUE / OVERDUE against the live clock)

And the cycle status bubble-up / revert logic driven by recomputes.

Precision (PRD §2.5): credit hours carry one decimal place, round-half-up; sums
are accumulated exactly and rounded once at the end, EXCEPT carryover which pins
round-per-category-first.
"""

from datetime import timedelta
from decimal import Decimal

import clock
from db import db
from util import round_half_up_1, as_decimal

CATEGORIES = ("ETHICS", "SUBSTANCE", "GENERAL")


# ─── helpers ──────────────────────────────────────────────────────────

def _board(cycle):
    return db.license_boards[cycle["board_id"]]


def _requirements_for_board(board_id):
    return [
        r for r in db.credit_requirements.values() if r["board_id"] == board_id
    ]


def _category_min(board_id, category):
    for r in db.credit_requirements.values():
        if r["board_id"] == board_id and r["category"] == category:
            return as_decimal(r["min_hours"])
    return None


def _completions_for_cycle(cycle_id):
    return [c for c in db.completions.values() if c["cycle_id"] == cycle_id]


def _approved_reciprocity_for_cycle(cycle_id):
    return [
        g for g in db.reciprocity_grants.values()
        if g["target_cycle_id"] == cycle_id and g["status"] == "APPROVED"
    ]


# ─── credit_tally (PRD §3.5) ──────────────────────────────────────────

def recompute_credit_tally(cycle):
    """Recompute provisional_earned_hours and final_earned_hours in place.

    base = carryover_in_hours + reciprocity_hours
    provisional = base + sum(awarded_hours where status in {PENDING_VERIFICATION, VERIFIED})
    final       = base + sum(awarded_hours where status == VERIFIED)
    Each sum accumulated exactly, rounded half-up to 1 dp once at the end.
    """
    base = as_decimal(cycle["carryover_in_hours"]) + as_decimal(cycle["reciprocity_hours"])

    prov = base
    fin = base
    for c in _completions_for_cycle(cycle["id"]):
        if c["status"] in ("PENDING_VERIFICATION", "VERIFIED"):
            prov += as_decimal(c["awarded_hours"])
        if c["status"] == "VERIFIED":
            fin += as_decimal(c["awarded_hours"])

    cycle["provisional_earned_hours"] = round_half_up_1(prov)
    cycle["final_earned_hours"] = round_half_up_1(fin)


# ─── per-category verified hours decomposition (PRD §3.6) ─────────────

def _verified_hours_by_category(cycle):
    """Per-category hours = VERIFIED completion hours + carryover_in + approved
    reciprocity hours tagged to that category.

    carryover_in_hours has no category tag of its own; per the requirement-test
    and carryover narratives, the cycle's carryover-in and the *generic* tally
    base contribute through reciprocity (categorized) and verified completions
    (categorized). Carryover-in is treated as GENERAL-category surplus carried
    forward, matching the cycle base which is otherwise category-agnostic.
    """
    hours = {cat: Decimal("0") for cat in CATEGORIES}

    for c in _completions_for_cycle(cycle["id"]):
        if c["status"] == "VERIFIED":
            hours[c["category"]] += as_decimal(c["awarded_hours"])

    for g in _approved_reciprocity_for_cycle(cycle["id"]):
        hours[g["category"]] += as_decimal(g["credit_hours"])

    # carryover_in is categorized as GENERAL (it is undifferentiated surplus
    # rolled forward into the cycle's general pool).
    hours["GENERAL"] += as_decimal(cycle["carryover_in_hours"])

    return hours


def _general_required(cycle):
    board = _board(cycle)
    total = as_decimal(board["total_required_hours"])
    non_general_min_sum = Decimal("0")
    for r in _requirements_for_board(board["id"]):
        if r["category"] != "GENERAL":
            non_general_min_sum += as_decimal(r["min_hours"])
    return total - non_general_min_sum


# ─── requirement_satisfaction (PRD §3.6) ──────────────────────────────

def requirement_met(cycle):
    """Return True iff the cycle's VERIFIED hours satisfy every category
    requirement (waterfall: per-category fill, overflow spills to a shared
    general pool). Comparisons inclusive (exactly-the-minimum is met)."""
    hours = _verified_hours_by_category(cycle)
    general_required = _general_required(cycle)

    general_pool = hours["GENERAL"]
    deficits_clear = True

    for cat in ("ETHICS", "SUBSTANCE"):
        m = _category_min(cycle["board_id"], cat)
        if m is None:
            m = Decimal("0")
        h = hours[cat]
        # round to 1dp for the comparison precision (round_half_up)
        h_r = as_decimal(round_half_up_1(h))
        m_r = as_decimal(round_half_up_1(m))
        alloc = min(h_r, m_r)
        overflow = h_r - alloc
        if overflow < 0:
            overflow = Decimal("0")
        deficit = m_r - h_r
        if deficit > 0:
            deficits_clear = False
        general_pool += overflow

    gen_req_r = as_decimal(round_half_up_1(general_required))
    gen_pool_r = as_decimal(round_half_up_1(general_pool))
    general_deficit = gen_req_r - gen_pool_r
    if general_deficit < 0:
        general_deficit = Decimal("0")

    return deficits_clear and general_deficit == 0


# ─── carryover_computation (PRD §3.6) ─────────────────────────────────

def compute_carryover_out(cycle):
    """Per-category surplus, rounded per category FIRST, then summed, then capped.

    Carryover does NOT pool ethics/substance overflow into general — each
    category keeps only its own excess over its own requirement.
    """
    board = _board(cycle)
    hours = _verified_hours_by_category(cycle)
    general_required = _general_required(cycle)

    surplus_total = Decimal("0")
    for cat in CATEGORIES:
        if cat == "GENERAL":
            required = general_required
        else:
            m = _category_min(cycle["board_id"], cat)
            required = m if m is not None else Decimal("0")
        raw_surplus = hours[cat] - required
        if raw_surplus < 0:
            raw_surplus = Decimal("0")
        # ROUND PER CATEGORY to 1dp first.
        surplus_total += as_decimal(round_half_up_1(raw_surplus))

    capped = min(surplus_total, as_decimal(board["carryover_cap_hours"]))
    return round_half_up_1(capped)


# ─── deadline_reminder (PRD §3.3) ─────────────────────────────────────

def compute_reminder_status(cycle):
    """Re-derive reminder_status against the current clock. Day-granular.

    remind_at = cycle_end - reminder_lead_days
      now <  remind_at         -> NOT_DUE
      remind_at <= now < end   -> DUE   (exactly remind_at is DUE)
      now >= cycle_end         -> OVERDUE (exactly cycle_end is OVERDUE)
    """
    board = _board(cycle)
    cycle_end = cycle["cycle_end"]
    remind_at = cycle_end - timedelta(days=board["reminder_lead_days"])
    now = clock.now()

    if now < remind_at:
        return "NOT_DUE"
    if now < cycle_end:
        return "DUE"
    return "OVERDUE"


# ─── cycle status bubble-up / revert (PRD §3.4/§3.6/§3.7) ─────────────

def reconcile_after_recompute(cycle, bump_fn):
    """After a credit_tally recompute, flip OPEN<->REQUIREMENTS_MET based on the
    VERIFIED-hours requirement test, and (re)compute or reset carryover_out.

    Only the OPEN<->REQUIREMENTS_MET pair is auto-toggled here. AUDIT_HOLD,
    RENEWED, and LAPSED cycles are not auto-transitioned by a tally recompute.

    `bump_fn(record)` advances updated_at and version on a record; the caller
    supplies it so timestamps/versions stay consistent.
    """
    status = cycle["status"]
    if status == "OPEN":
        if requirement_met(cycle):
            cycle["status"] = "REQUIREMENTS_MET"
            cycle["carryover_out_hours"] = compute_carryover_out(cycle)
            bump_fn(cycle)
    elif status == "REQUIREMENTS_MET":
        if not requirement_met(cycle):
            cycle["status"] = "OPEN"
            cycle["carryover_out_hours"] = 0
            bump_fn(cycle)
        else:
            # Stay REQUIREMENTS_MET; keep carryover_out current.
            new_carry = compute_carryover_out(cycle)
            if new_carry != cycle["carryover_out_hours"]:
                cycle["carryover_out_hours"] = new_carry
                bump_fn(cycle)
