"""Shared business cascades (PRD §2.8, §3.5, §3.7, §2.5 sweeps).

All cascades apply immediately and recompute derived balances in the same
request/response cycle (PRD §2.4).
"""
from decimal import ROUND_HALF_UP, Decimal

from db import DB
from services.common import stamp_new, touch

DAILY_CAP = 100  # activity_points_conversion constant (scaffold §1.3)


def enrollments_of_program(program_id):
    return [e for e in DB.enrollments.values() if e["program_id"] == program_id]


def ledger_of_enrollment(enrollment_id):
    return [le for le in DB.ledger.values() if le["enrollment_id"] == enrollment_id]


def participations_of_enrollment(enrollment_id):
    return [p for p in DB.participations.values() if p["enrollment_id"] == enrollment_id]


def referrals_of_enrollment(enrollment_id):
    return [r for r in DB.referrals.values() if r["enrollment_id"] == enrollment_id]


def recompute_balances(enrollment):
    """PRD §2.8: settled = POSTED only; provisional = PROVISIONAL + POSTED.
    Every recompute touches the enrollment (updated_at/version)."""
    entries = ledger_of_enrollment(enrollment["id"])
    settled = sum(le["points_delta"] for le in entries if le["status"] == "POSTED")
    provisional = sum(
        le["points_delta"] for le in entries if le["status"] in ("PROVISIONAL", "POSTED")
    )
    enrollment["points_balance_settled"] = settled
    enrollment["points_balance_provisional"] = provisional
    touch(enrollment)


def make_ledger_entry(enrollment, kind, delta, reason=None, source_event_id=None,
                      status="PROVISIONAL"):
    entry = {
        "enrollment_id": enrollment["id"],
        "kind": kind,
        "points_delta": delta,
        "source_activity_event_id": source_event_id,
        "reason": reason,
        "status": status,
    }
    stamp_new(entry, common=True)
    DB.ledger[entry["id"]] = entry
    return entry


def participation_progress(participation, challenge):
    """challenge_progress (scaffold §1.3): sum quantity of accepted events of
    the enrollment matching activity_type inside the half-open window."""
    total = 0
    for ev in DB.events.values():
        if ev["enrollment_id"] != participation["enrollment_id"]:
            continue
        if ev["activity_type"] != challenge["activity_type"]:
            continue
        if ev["_occurred"] >= challenge["_starts"] and ev["_occurred"] < challenge["_ends"]:
            total += ev["quantity"]
    return total


def complete_participation(participation, challenge):
    """JOINED -> COMPLETED with the full BONUS cascade (PRD §3.5)."""
    participation["status"] = "COMPLETED"
    touch(participation)
    enrollment = DB.enrollments[participation["enrollment_id"]]
    make_ledger_entry(enrollment, "BONUS", challenge["points_reward"],
                      reason=None, status="PROVISIONAL")
    recompute_balances(enrollment)
    challenge["completed_count"] += 1
    touch(challenge)


def fail_participation(participation):
    participation["status"] = "FAILED"
    touch(participation)


def resolve_joined_participations(challenge):
    """At challenge completion: >= goal completes (bonus cascade), else fails."""
    for p in DB.participations.values():
        if p["challenge_id"] != challenge["id"] or p["status"] != "JOINED":
            continue
        p["progress_quantity"] = participation_progress(p, challenge)
        if p["progress_quantity"] >= challenge["goal_quantity"]:
            complete_participation(p, challenge)
        else:
            fail_participation(p)


def complete_challenge(challenge):
    if challenge["status"] not in ("PUBLISHED", "ACTIVE"):
        return
    challenge["status"] = "COMPLETED"
    touch(challenge)
    resolve_joined_participations(challenge)


def sweep_clock(now):
    """PRD §2.5 time sweep on clock advance: PUBLISHED challenges with
    starts_at <= now -> ACTIVE; ACTIVE with ends_at < now -> COMPLETED;
    SCHEDULED screenings with slot_end < now -> NO_SHOW."""
    for ch in DB.challenges.values():
        if ch["status"] == "PUBLISHED" and ch["_starts"] <= now:
            ch["status"] = "ACTIVE"
            touch(ch)
        if ch["status"] == "ACTIVE" and ch["_ends"] < now:
            complete_challenge(ch)
    for sc in DB.screenings.values():
        if sc["status"] == "SCHEDULED" and sc["_slot_end"] < now:
            sc["status"] = "NO_SHOW"
            touch(sc)


def close_program_cascade(program):
    """PRD §3.2 close cascade, pinned order: challenge sweep FIRST (completion
    BONUS entries are created PROVISIONAL), ledger expiry SECOND (expiring the
    bonuses just created), screening no-show THIRD."""
    # 1. challenge sweep
    for ch in DB.challenges.values():
        if ch["program_id"] == program["id"] and ch["status"] in ("PUBLISHED", "ACTIVE"):
            complete_challenge(ch)
    # 2. ledger expiry sweep (per enrollment, entries in created order)
    for enr in enrollments_of_program(program["id"]):
        entries = sorted(ledger_of_enrollment(enr["id"]), key=lambda le: le["created_at"])
        changed = False
        for le in entries:
            if le["status"] == "PROVISIONAL":
                le["status"] = "EXPIRED"
                touch(le)
                changed = True
        if changed:
            recompute_balances(enr)
    # 3. screening no-show sweep
    enr_ids = {e["id"] for e in enrollments_of_program(program["id"])}
    for sc in DB.screenings.values():
        if sc["enrollment_id"] in enr_ids and sc["status"] == "SCHEDULED":
            sc["status"] = "NO_SHOW"
            touch(sc)


# --- award computation (PRD §3.7, calculations tier_attainment / premium_differential) ---

def _round_half_up_cents(value):
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def compute_tier(program, enrollment):
    P = enrollment["points_balance_settled"]
    H = 1 if any(h["enrollment_id"] == enrollment["id"] for h in DB.hras.values()) else 0
    B = 0
    for sc in DB.screenings.values():
        if sc["enrollment_id"] == enrollment["id"] and sc["status"] == "RESULTED":
            if sc["targets_met"] is not None and sc["targets_met"] > B:
                B = sc["targets_met"]
    if P >= program["gold_threshold"] and H == 1 and B >= 3:
        return "GOLD"
    if P >= program["silver_threshold"] and H == 1:
        return "SILVER"
    if P >= program["bronze_threshold"]:
        return "BRONZE"
    return "NONE"


def compute_award_amounts(program, enrollment):
    """Returns dict with tier, standard_award_cents, award_cents,
    applied_variant, surcharge_cents, net_annual_differential_cents."""
    employer = DB.employers[program["employer_id"]]
    employee = DB.employees[enrollment["employee_id"]]
    tier = compute_tier(program, enrollment)
    cap_cents = _round_half_up_cents(
        Decimal(str(program["premium_cap_pct"]))
        * Decimal(employer["annual_self_only_premium_cents"])
    )
    tier_value = {
        "GOLD": program["gold_award_cents"],
        "SILVER": program["silver_award_cents"],
        "BRONZE": program["bronze_award_cents"],
        "NONE": 0,
    }[tier]
    standard_award_cents = min(tier_value, cap_cents)

    referrals = referrals_of_enrollment(enrollment["id"])
    ra_available = enrollment["ra_eligible"] and any(
        r["status"] == "DISCHARGED"
        and r.get("outcome") == "GOALS_MET"
        and not r.get("_ever_declined", False)
        for r in referrals
    )
    if ra_available:
        applied_variant = "REASONABLE_ALTERNATIVE"
        award_cents = min(program["gold_award_cents"], cap_cents)
    else:
        applied_variant = "STANDARD"
        award_cents = standard_award_cents

    cessation_done = any(
        r["reason"] == "TOBACCO_CESSATION"
        and r["status"] == "DISCHARGED"
        and r.get("outcome") == "GOALS_MET"
        for r in referrals
    )
    if employee["tobacco_attested"] and not cessation_done:
        surcharge_cents = employer["tobacco_surcharge_cents"]
    else:
        surcharge_cents = 0

    return {
        "tier": tier,
        "standard_award_cents": standard_award_cents,
        "award_cents": award_cents,
        "applied_variant": applied_variant,
        "surcharge_cents": surcharge_cents,
        "net_annual_differential_cents": surcharge_cents - award_cents,
    }


def apply_award_amounts(award, amounts):
    for k, v in amounts.items():
        award[k] = v
    award["_computed_seq"] = DB.next_seq()
    touch(award)


def recompute_projected_award_for_enrollment(program, enrollment):
    """RA recompute cascade on coaching discharge (PRD §3.6): recompute the
    enrollment's PROJECTED IncentiveAward under the current variant rules."""
    award = next(
        (a for a in DB.awards.values()
         if a["enrollment_id"] == enrollment["id"] and a["status"] == "PROJECTED"),
        None,
    )
    if award is None:
        return
    amounts = compute_award_amounts(program, enrollment)
    apply_award_amounts(award, amounts)
