"""Business logic: state machines, calculations, cascades."""

from decimal import Decimal, ROUND_HALF_EVEN

import db


# ---------------------------------------------------------------------------
# §1.3 nil_value_classification
# ---------------------------------------------------------------------------
DE_MINIMIS_CUTOFF_CENTS = 60000
STANDARD_CUTOFF_CENTS = 500000


def compute_nil_net_and_tier(gross_value_cents: int, agent_fee_pct: float):
    """Pinned order: compute net via banker rounding, THEN compare to tiers.

    Returns (net_value_cents: int, tier: str).
    """
    gross = Decimal(int(gross_value_cents))
    # `agent_fee_pct` is a decimal fraction in [0.0, 0.30]. Use Decimal(str())
    # to avoid binary-float artifacts.
    fee = Decimal(str(agent_fee_pct))
    multiplier = Decimal("1") - fee
    raw = gross * multiplier
    net = int(raw.to_integral_value(rounding=ROUND_HALF_EVEN))
    if net < DE_MINIMIS_CUTOFF_CENTS:
        tier = "DE_MINIMIS"
    elif net < STANDARD_CUTOFF_CENTS:
        tier = "STANDARD"
    else:
        tier = "HIGH_VALUE"
    return net, tier


# ---------------------------------------------------------------------------
# §1.3 program_penalty_tier — severity weight + cumulative tier
# ---------------------------------------------------------------------------
def severity_weight_for(alleged_value_cents: int) -> int:
    v = int(alleged_value_cents)
    if v < 50000:
        return 1
    if v < 500000:
        return 3
    if v < 2500000:
        return 7
    return 15


def compute_program_penalty_tier(program_id: str) -> str:
    total = 0
    for inc in db.booster_incidents.values():
        if inc["program_id"] == program_id and inc["status"] == "SUSTAINED":
            total += int(inc.get("severity_weight", 0))
    if total == 0:
        return "NONE"
    if total < 5:
        return "LEVEL_I"
    if total < 15:
        return "LEVEL_II"
    return "POSTSEASON_BAN"


# ---------------------------------------------------------------------------
# §1.3 scholarship_slot_utilization
# ---------------------------------------------------------------------------
def compute_slots_committed(program_id: str) -> int:
    """base variant — counts SENT + ACCEPTED."""
    n = 0
    for o in db.scholarship_offers.values():
        if o["program_id"] == program_id and o["status"] in ("SENT", "ACCEPTED"):
            n += 1
    return n


def compute_slots_projected(program_id: str) -> int:
    """projected variant — counts DRAFT + SENT + ACCEPTED, minus those whose
    athlete already has a DENIED EligibilityCertification.
    """
    # Build set of athlete ids with at least one DENIED certification
    denied_athletes = set()
    for cert in db.eligibility_certifications.values():
        if cert["status"] == "DENIED":
            denied_athletes.add(cert["student_athlete_id"])
    n = 0
    for o in db.scholarship_offers.values():
        if o["program_id"] != program_id:
            continue
        if o["status"] not in ("DRAFT", "SENT", "ACCEPTED"):
            continue
        if o["student_athlete_id"] in denied_athletes:
            continue
        n += 1
    return n


def refresh_program_counts(program: dict) -> None:
    """Recompute slots_committed and slots_projected on a program.
    Caller is responsible for stamping update (version/updated_at) if any
    field changed."""
    program["slots_committed"] = compute_slots_committed(program["id"])
    program["slots_projected"] = compute_slots_projected(program["id"])


# ---------------------------------------------------------------------------
# Cascade helpers
# ---------------------------------------------------------------------------
def _ordered_offers_for_program(program_id: str, statuses: set):
    """Return offers matching program_id and status, sorted by created_at ASC."""
    rows = [
        o for o in db.scholarship_offers.values()
        if o["program_id"] == program_id and o["status"] in statuses
    ]
    rows.sort(key=lambda r: (r.get("created_at", ""), r.get("id", "")))
    return rows


def _ordered_offers_for_athlete(student_athlete_id: str, statuses: set):
    rows = [
        o for o in db.scholarship_offers.values()
        if o["student_athlete_id"] == student_athlete_id and o["status"] in statuses
    ]
    rows.sort(key=lambda r: (r.get("created_at", ""), r.get("id", "")))
    return rows


def cascade_eligibility_denial(athlete_id: str) -> None:
    """On EligibilityCertification PENDING->DENIED:
    Every ScholarshipOffer for this athlete with status IN {DRAFT, SENT}
    auto-WITHDRAWN. SENT cases also decrement Program.slots_committed.
    """
    affected_offers = _ordered_offers_for_athlete(
        athlete_id, {"DRAFT", "SENT"}
    )
    for offer in affected_offers:
        prior = offer["status"]
        offer["status"] = "WITHDRAWN"
        db.stamp_update(offer)
        if prior == "SENT":
            program = db.programs.get(offer["program_id"])
            if program is not None:
                # Slot release — recompute committed and projected together
                # for internal consistency, plus bump program version.
                refresh_program_counts(program)
                db.stamp_update(program)
        else:
            # DRAFT cascade — projected count may shift (athlete now has
            # DENIED certification, so the offer is excluded from projected).
            program = db.programs.get(offer["program_id"])
            if program is not None:
                old_projected = program.get("slots_projected", 0)
                refresh_program_counts(program)
                # base count unaffected; projected may have changed.
                if program.get("slots_projected", 0) != old_projected:
                    db.stamp_update(program)


def cascade_postseason_ban(program_id: str) -> None:
    """On Program.penalty_tier becoming POSTSEASON_BAN:
    Auto-WITHDRAW every ScholarshipOffer where program_id == this AND
    status == SENT. Each decrements slots_committed.
    """
    program = db.programs.get(program_id)
    if program is None:
        return
    affected = _ordered_offers_for_program(program_id, {"SENT"})
    for offer in affected:
        offer["status"] = "WITHDRAWN"
        db.stamp_update(offer)
    if affected:
        refresh_program_counts(program)
        db.stamp_update(program)


def recompute_and_apply_penalty(program_id: str) -> None:
    """Recompute Program.penalty_tier; if it transitions to POSTSEASON_BAN,
    trigger the SENT-offer cascade. Always bump version if tier changed.
    """
    program = db.programs.get(program_id)
    if program is None:
        return
    old_tier = program.get("penalty_tier", "NONE")
    new_tier = compute_program_penalty_tier(program_id)
    program["penalty_tier"] = new_tier
    if new_tier != old_tier:
        db.stamp_update(program)
    if new_tier == "POSTSEASON_BAN":
        cascade_postseason_ban(program_id)
