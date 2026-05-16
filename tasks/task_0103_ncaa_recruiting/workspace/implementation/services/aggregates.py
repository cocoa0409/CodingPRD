"""Program aggregate recompute + athlete NIL lifetime recompute."""

from datetime import timedelta

from core.clock import CLOCK, parse_iso
from core.models import mark_mutated
from core.store import STORE
from services.money import round_two_dp


# --- scholarship_slot_usage ------------------------------------------------

def recompute_program_aggregates(program_id: str):
    """Recompute total_equivalencies_used, active_roster_count for program.

    Bumps program updated_at + version IF any value actually changes.
    """
    prog = STORE.programs.get(program_id)
    if not prog:
        return

    total = 0.0
    for s in STORE.scholarship_slots.values():
        if s.get("program_id") != program_id:
            continue
        if s.get("status") in ("SIGNED", "ACTIVE"):
            total += float(s.get("fractional_equivalency", 0))
    total_rounded = round_two_dp(total)

    count = 0
    for a in STORE.athletes.values():
        if a.get("status") == "ENROLLED" and a.get("current_program_id") == program_id:
            count += 1

    changed = False
    if prog.get("total_equivalencies_used") != total_rounded:
        prog["total_equivalencies_used"] = total_rounded
        changed = True
    if prog.get("active_roster_count") != count:
        prog["active_roster_count"] = count
        changed = True

    if changed:
        mark_mutated(prog)


# --- program_compliance_posture ---------------------------------------------

def recompute_program_compliance(program_id: str):
    """Recompute penalty_points_total + compliance_status for a program."""
    prog = STORE.programs.get(program_id)
    if not prog:
        return

    now = CLOCK.now()
    window_start = now - timedelta(days=730)
    total_points = 0
    for v in STORE.compliance_violations.values():
        if v.get("program_id") != program_id:
            continue
        if v.get("outcome") != "SUSTAINED":
            continue
        v_created = parse_iso(v["created_at"])
        if v_created < window_start:
            continue
        total_points += int(v.get("penalty_points", 0))

    if total_points >= 20:
        status = "RED"
    elif total_points >= 10:
        status = "YELLOW"
    else:
        status = "GREEN"

    changed = False
    if prog.get("penalty_points_total") != total_points:
        prog["penalty_points_total"] = total_points
        changed = True
    if prog.get("compliance_status") != status:
        prog["compliance_status"] = status
        changed = True
    if changed:
        mark_mutated(prog)


# --- Athlete NIL lifetime ---------------------------------------------------

def recompute_athlete_nil_lifetime(athlete_id: str):
    """Recompute athlete.nil_deal_lifetime_value_cents (sum of APPROVED deal approved_value_cents)."""
    a = STORE.athletes.get(athlete_id)
    if not a:
        return
    total = 0
    for d in STORE.nil_deals.values():
        if d.get("athlete_id") != athlete_id:
            continue
        if d.get("status") != "APPROVED":
            continue
        if d.get("approved_value_cents") is None:
            continue
        total += int(d["approved_value_cents"])
    if a.get("nil_deal_lifetime_value_cents") != total:
        a["nil_deal_lifetime_value_cents"] = total
        mark_mutated(a)
