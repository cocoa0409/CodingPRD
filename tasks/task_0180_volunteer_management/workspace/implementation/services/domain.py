"""Domain logic: cascades, bubble-up, recomputes, lazy expiry, seat management
(PRD §2.5, §3.2-§3.7).

Every cascade is immediate and atomic in the triggering request. Each derived
recompute that mutates an owning entity bumps that entity's version and
updated_at via common.touch().
"""
from db import store
from timeutil import now_iso, parse_dt, add_seconds
from services import calc
from services.common import touch

# Signup statuses that occupy a seat on the shift (PRD §2.5).
SEAT_HOLDING = {"RESERVED", "CONFIRMED", "ATTENDED", "HOURS_LOGGED", "HOURS_VERIFIED"}


# ---- bg-check tier + lazy expiry -----------------------------------------
def apply_bg_expiry(volunteer):
    """Lazily expire any CLEARED background check of this volunteer whose
    valid_until is strictly before the current clock, then recompute the
    volunteer's bg_check_tier. Each expiry that fires bumps the volunteer's
    version (PRD §3.2). Returns True if anything changed."""
    now = store.now()
    changed = False
    for chk in store.background_checks.values():
        if chk["volunteer_id"] != volunteer["id"]:
            continue
        if chk["status"] == "CLEARED" and chk.get("valid_until"):
            valid_until = parse_dt(chk["valid_until"])
            if now > valid_until:
                chk["status"] = "EXPIRED"
                touch(chk)
                changed = True
    if changed:
        recompute_bg_tier(volunteer)
    return changed


def recompute_bg_tier(volunteer):
    """bg_check_tier = MAX rank among this volunteer's CLEARED, non-expired
    checks; NONE if none (PRD §3.2 calc bg_check_tier). Bumps volunteer.version."""
    now = store.now()
    best_rank = 0
    best_tier = "NONE"
    for chk in store.background_checks.values():
        if chk["volunteer_id"] != volunteer["id"]:
            continue
        if chk["status"] != "CLEARED":
            continue
        if chk.get("valid_until"):
            if now > parse_dt(chk["valid_until"]):
                continue
        rank = calc.BG_TIER_RANK[chk["requested_tier"]]
        if rank > best_rank:
            best_rank = rank
            best_tier = chk["requested_tier"]
    volunteer["bg_check_tier"] = best_tier
    touch(volunteer)


# ---- reliability + recognition recomputes --------------------------------
def _verified_signups(volunteer_id):
    return [s for s in store.signups.values()
            if s["volunteer_id"] == volunteer_id and s["status"] == "HOURS_VERIFIED"]


def recompute_no_show_count(volunteer):
    """lifetime_no_show_count = count of this volunteer's signups in NO_SHOW."""
    volunteer["lifetime_no_show_count"] = sum(
        1 for s in store.signups.values()
        if s["volunteer_id"] == volunteer["id"] and s["status"] == "NO_SHOW"
    )


def recompute_reliability(volunteer):
    """reliability_score from kept (HOURS_VERIFIED) and broken (NO_SHOW) counts."""
    verified = len(_verified_signups(volunteer["id"]))
    no_show = volunteer["lifetime_no_show_count"]
    volunteer["reliability_score"] = calc.reliability_score(verified, no_show)


def recompute_total_verified_hours(volunteer):
    """total_verified_hours per calc milestone_total_hours: per-line round then
    sum then round, in signup created_at ASC order."""
    verified = _verified_signups(volunteer["id"])
    verified.sort(key=lambda s: s["_seq"])
    values = [s["verified_hours"] for s in verified if s["verified_hours"] is not None]
    volunteer["total_verified_hours"] = calc.total_verified_hours(values)


def recompute_milestone(volunteer):
    """milestone_tier monotonic non-decreasing from total_verified_hours."""
    volunteer["milestone_tier"] = calc.milestone_tier(
        volunteer["milestone_tier"], volunteer["total_verified_hours"]
    )


def maybe_suspend(volunteer, org):
    """If reliability_score < org.reliability_suspension_threshold OR
    lifetime_no_show_count >= org.no_show_strike_limit, suspend the volunteer
    (PRD §3.5). Only an ACTIVE volunteer is transitioned."""
    if volunteer["status"] != "ACTIVE":
        return
    if (volunteer["reliability_score"] < org["reliability_suspension_threshold"]
            or volunteer["lifetime_no_show_count"] >= org["no_show_strike_limit"]):
        volunteer["status"] = "SUSPENDED"


# ---- staffing bubble-up ---------------------------------------------------
def recompute_staffing(opportunity):
    """staffing_status from child shifts (PRD §3.3 calc staffing_status).
    considered = shifts in {OPEN, FULL, COMPLETED}; empty -> UNDERSTAFFED;
    all FULL/COMPLETED -> FULLY_STAFFED; else UNDERSTAFFED. Bumps version only
    when the value actually changes."""
    considered = [s for s in store.shifts.values()
                  if s["opportunity_id"] == opportunity["id"]
                  and s["status"] in ("OPEN", "FULL", "COMPLETED")]
    if not considered:
        new_status = "UNDERSTAFFED"
    elif all(s["status"] in ("FULL", "COMPLETED") for s in considered):
        new_status = "FULLY_STAFFED"
    else:
        new_status = "UNDERSTAFFED"
    if opportunity["staffing_status"] != new_status:
        opportunity["staffing_status"] = new_status
        touch(opportunity)


# ---- shift seat / FULL-OPEN oscillation ----------------------------------
def recompute_reserved_count(shift):
    return sum(1 for s in store.signups.values()
               if s["shift_id"] == shift["id"] and s["status"] in SEAT_HOLDING)


def sync_shift_full_state(shift):
    """After reserved_count changes, oscillate OPEN<->FULL and bubble up to the
    parent opportunity. Does NOT touch CANCELLED/COMPLETED shifts."""
    if shift["status"] in ("CANCELLED", "COMPLETED"):
        return
    if shift["reserved_count"] >= shift["capacity"]:
        if shift["status"] != "FULL":
            shift["status"] = "FULL"
    else:
        if shift["status"] != "OPEN":
            shift["status"] = "OPEN"
    opp = store.opportunities.get(shift["opportunity_id"])
    if opp is not None:
        recompute_staffing(opp)


def occupy_seat(shift):
    """A new signup occupies a seat: reserved_count += 1, then sync FULL state.
    Caller bumps shift.version separately per PRD."""
    shift["reserved_count"] += 1
    sync_shift_full_state(shift)


def release_seat(shift):
    """A seat is released: reserved_count -= 1, then sync FULL->OPEN + bubble up.
    Caller bumps shift.version separately per PRD."""
    shift["reserved_count"] = max(0, shift["reserved_count"] - 1)
    sync_shift_full_state(shift)


# ---- no-show reliability cascade -----------------------------------------
def no_show_cascade(signup):
    """Run the per-signup no-show reliability cascade (PRD §3.5). The caller has
    already set signup.status = NO_SHOW. Releases the seat, recomputes the
    volunteer's standing, possibly suspends, and bumps shift+volunteer versions."""
    shift = store.shifts.get(signup["shift_id"])
    volunteer = store.volunteers.get(signup["volunteer_id"])
    if shift is not None:
        release_seat(shift)
        touch(shift)
    if volunteer is not None:
        recompute_no_show_count(volunteer)
        recompute_reliability(volunteer)
        org = store.organizations.get(volunteer["organization_id"])
        if org is not None:
            maybe_suspend(volunteer, org)
        touch(volunteer)


# ---- verify-hours recognition cascade ------------------------------------
def verify_hours_cascade(volunteer):
    """Recompute total_verified_hours, reliability_score, milestone_tier, and
    bump the volunteer's version once (PRD §3.6)."""
    recompute_total_verified_hours(volunteer)
    recompute_reliability(volunteer)
    recompute_milestone(volunteer)
    touch(volunteer)


# ---- shift cancel cascade -------------------------------------------------
def cancel_shift_cascade(shift):
    """Cancel a shift and run its three effects (PRD §3.3):
      - every seat-holding signup in RESERVED/CONFIRMED -> CANCELLED, seat
        released, no reliability penalty;
      - any ALLOCATED corporate group targeting this shift -> CANCELLED;
      - parent opportunity staffing_status re-evaluated.
    The caller sets shift.status = CANCELLED before invoking (or this sets it).
    """
    shift["status"] = "CANCELLED"
    for s in store.signups.values():
        if s["shift_id"] == shift["id"] and s["status"] in ("RESERVED", "CONFIRMED"):
            s["status"] = "CANCELLED"
            touch(s)
            shift["reserved_count"] = max(0, shift["reserved_count"] - 1)
    for grp in store.corporate_groups.values():
        if grp["target_shift_id"] == shift["id"] and grp["status"] == "ALLOCATED":
            grp["status"] = "CANCELLED"
            touch(grp)
    opp = store.opportunities.get(shift["opportunity_id"])
    if opp is not None:
        recompute_staffing(opp)


def complete_shift_cascade(shift):
    """Complete a shift (PRD §3.3): every CONFIRMED signup with no attendance
    decision -> NO_SHOW, each running the no-show reliability cascade. Bumps
    shift.version by 1 (caller-facing) — done by caller. Sets status COMPLETED."""
    shift["status"] = "COMPLETED"
    confirmed = [s for s in store.signups.values()
                 if s["shift_id"] == shift["id"] and s["status"] == "CONFIRMED"]
    confirmed.sort(key=lambda s: s["_seq"])
    for s in confirmed:
        s["status"] = "NO_SHOW"
        touch(s)
        no_show_cascade(s)
    opp = store.opportunities.get(shift["opportunity_id"])
    if opp is not None:
        recompute_staffing(opp)
