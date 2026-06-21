"""Calculation rules: expirable_band, posture, readiness_score, tally,
recredentialing_due_date, enrollment_effective_date, sanction_score."""
from decimal import ROUND_HALF_UP, Decimal

from db import store
from services.common import add_days_iso, days_remaining

SANCTION_UNIT_PENALTY = 5
SANCTION_PENALTY_CAP = 40
RECRED_DUE_PENALTY = 15
CHAIR_TIE_MULTIPLIER = 2


# ---------------------------------------------------------------------------
# expirable_band (§2.8)
# ---------------------------------------------------------------------------
def compute_expirable_band(item, org):
    dr = days_remaining(item["expiration_date"], org["current_utc"])
    if dr < 0:
        return "LAPSED"
    if dr <= org["expiring_soon_window_days"]:
        return "EXPIRING_SOON"
    return "VALID"


# ---------------------------------------------------------------------------
# sanction_score (§3.4)
# ---------------------------------------------------------------------------
def compute_sanction_score(provider):
    total = 0
    for sc in store.sanctions_screenings.values():
        if sc["provider_id"] != provider["id"]:
            continue
        if sc["result"] == "HIT" and sc["status"] == "OPEN":
            src = store.sanctions_sources.get(sc["sanctions_source_id"])
            if src is not None:
                total += src["severity_weight"]
    return total


# ---------------------------------------------------------------------------
# credentialing_posture (§3.7 / 1.3)
# ---------------------------------------------------------------------------
def _provider_items(provider):
    return [ci for ci in store.credential_items.values()
            if ci["provider_id"] == provider["id"]]


def _latest_file(provider):
    files = [f for f in store.credentialing_files.values()
             if f["provider_id"] == provider["id"]]
    if not files:
        return None
    return max(files, key=lambda f: f["_seq"])


def compute_posture(provider):
    """First-match-wins evaluation order. sanction_score must already be set
    on the provider record before calling (recompute it first)."""
    items = _provider_items(provider)

    if provider["sanction_score"] > 0:
        return "EXCLUDED"
    if any(ci["verification_state"] == "REJECTED" for ci in items):
        return "CONDITIONAL"
    if any(ci["expirable_band"] == "LAPSED" for ci in items):
        return "CONDITIONAL"
    if provider["recred_state"] == "RECRED_DUE":
        return "CONDITIONAL"
    latest = _latest_file(provider)
    if (latest is not None and latest["review_status"] == "APPROVED"
            and len(items) > 0
            and all(ci["verification_state"] == "VERIFIED" for ci in items)):
        return "CLEARED"
    return "PENDING"


# ---------------------------------------------------------------------------
# credentialing_readiness_score (§3.7 / 1.3)
# ---------------------------------------------------------------------------
def _round2(value):
    return float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def compute_readiness_score(provider):
    items = _provider_items(provider)
    T = len(items)
    if T == 0:
        # T >= 1 by submit precondition, but guard anyway.
        return 0.0
    V = sum(1 for ci in items
            if ci["verification_state"] == "VERIFIED"
            and ci["expirable_band"] == "VALID")
    psv_ratio = V / T
    sanction_penalty = min(SANCTION_PENALTY_CAP,
                           provider["sanction_score"] * SANCTION_UNIT_PENALTY)
    recred_penalty = RECRED_DUE_PENALTY if provider["recred_state"] == "RECRED_DUE" else 0
    # base = round(100 * psv_ratio, 2) FIRST
    base = Decimal(str(100 * psv_ratio)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    # THEN subtract integer penalties
    post = base - Decimal(sanction_penalty) - Decimal(recred_penalty)
    # round half up to 2 dp (already integer subtraction, but keep precision)
    post = post.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    # THEN clamp at 0
    if post < 0:
        post = Decimal("0.00")
    return float(post)


# ---------------------------------------------------------------------------
# peer_review_tally (§3.5 / 1.3)
# ---------------------------------------------------------------------------
def compute_tally(file):
    chair = file.get("chair_user_id")
    votes = [v for v in store.peer_review_votes.values()
             if v["credentialing_file_id"] == file["id"]]

    base_yes = 0
    base_no = 0
    chair_vote = None
    for v in votes:
        reviewer = store.peer_reviewers.get(v["reviewer_id"])
        weight = reviewer["vote_weight"] if reviewer else 0
        is_chair = chair is not None and v["voter_user_id"] == chair
        if is_chair:
            # Track the chair's ballot; applied only in STEP 2.
            chair_vote = (v["ballot"], weight)
            continue
        if v["ballot"] == "YES":
            base_yes += weight
        elif v["ballot"] == "NO":
            base_no += weight
        # ABSTAIN contributes 0

    tally_yes = base_yes
    tally_no = base_no

    if chair_vote is not None:
        ballot, chair_weight = chair_vote
        if ballot in ("YES", "NO"):
            multiplier = CHAIR_TIE_MULTIPLIER if base_yes == base_no else 1
            contribution = chair_weight * multiplier
            if ballot == "YES":
                tally_yes += contribution
            else:
                tally_no += contribution
        # chair ABSTAIN contributes 0

    if tally_yes > tally_no:
        outcome = "YES"
    elif tally_no > tally_yes:
        outcome = "NO"
    else:
        outcome = "NO"  # deadlock denies
    return tally_yes, tally_no, outcome


# ---------------------------------------------------------------------------
# recredentialing_due_date (§3.7 / 1.3) — dual variant
# ---------------------------------------------------------------------------
def compute_recred_due_date(provider, org, anniversary):
    """anniversary=False -> ROLLING_FROM_COMPLETION (base = this clearing's
    completed date). anniversary=True -> ANNIVERSARY_FROM_FIRST_CLEARING
    (base = original first completed date; due is next multiple of cycle after
    current_utc measured from the original anchor)."""
    cycle = org["recred_cycle_days"]
    if not anniversary:
        base = provider["credentialing_completed_date"]
        return add_days_iso(base, cycle)
    # Fixed-anniversary: project from original anchor in cycle-day steps until
    # strictly after current_utc.
    from services.common import parse_iso8601, to_epoch_ms, MS_PER_DAY, iso_from_dt
    from datetime import datetime, timezone

    anchor = provider.get("original_completed_date") or provider["credentialing_completed_date"]
    anchor_ms = to_epoch_ms(parse_iso8601(anchor))
    cur_ms = to_epoch_ms(parse_iso8601(org["current_utc"]))
    step_ms = cycle * MS_PER_DAY
    due_ms = anchor_ms + step_ms
    # advance to the next multiple strictly after current_utc
    while due_ms <= cur_ms:
        due_ms += step_ms
    out = datetime.fromtimestamp(due_ms / 1000, tz=timezone.utc)
    return iso_from_dt(out)


# ---------------------------------------------------------------------------
# enrollment_effective_date (§3.6 / 1.3) — dual variant
# ---------------------------------------------------------------------------
def compute_effective_date(provider, payer, org):
    if payer["retroactive_allowed"]:
        return provider["credentialing_completed_date"]
    return org["current_utc"]
