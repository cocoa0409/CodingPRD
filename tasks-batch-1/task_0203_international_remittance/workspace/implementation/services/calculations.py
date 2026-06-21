"""Algorithmic rules (SCAFFOLD §1.3, PRD §3). All amounts are integer minor
units; FX rates are integer micro-units. Rounding direction is pinned per
calculation: pricing floors per-component-then-sums; the sanctions name
component rounds half-up at its points step. No floats for money paths.
"""
from decimal import Decimal, ROUND_HALF_UP

SCALE_MICRO = 1000000

# Sanctions thresholds (SCAFFOLD §1.3 sanctions_score constants).
SANCTIONS_CLEAR_THRESHOLD = 60      # score >= 60 -> HELD; < 60 -> auto CLEARED
SANCTIONS_ESCALATE_THRESHOLD = 85   # escalation requires score >= 85

# KYC-tier per-transfer ceilings (SCAFFOLD §1.3 corridor_limit_check constants).
KYC_CEILINGS = {
    "TIER0": 50000,
    "TIER1": 300000,
    "TIER2": 1500000,
}

REFUND_GRACE_SECONDS = 3600
MAX_PAYOUT_ATTEMPTS = 2

# High-risk countries gate the strict sanctions name-matching variant
# (PRD §3.5: strict when the party's country is on the high-risk list).
HIGH_RISK_COUNTRIES = {"RU", "IR", "KP", "SY", "CU"}


# ---------------------------------------------------------------------------
# quote_fee (SCAFFOLD §1.3): floor each component independently, then sum.
# ---------------------------------------------------------------------------
def quote_fee(send_principal_minor, corridor):
    if send_principal_minor >= corridor["fee_tier_threshold_minor"]:
        pct_bps = corridor["fee_pct_tier2_bps"]
    else:
        pct_bps = corridor["fee_pct_bps"]
    pct_component = (send_principal_minor * pct_bps) // 10000   # floor
    flat_component = corridor["fee_flat_minor"]
    return pct_component + flat_component


# ---------------------------------------------------------------------------
# recipient_amount / locked rate (SCAFFOLD §1.3): margin-first-then-convert.
# Apply margin to the mid-rate and floor to whole micro-units FIRST, then
# multiply by principal and floor to whole receive minor units.
# ---------------------------------------------------------------------------
def locked_rate(mid_rate_micro, corridor):
    return (mid_rate_micro * (10000 - corridor["fx_margin_bps"])) // 10000  # floor


def recipient_amount(send_principal_minor, locked_rate_micro):
    return (send_principal_minor * locked_rate_micro) // SCALE_MICRO  # floor


# ---------------------------------------------------------------------------
# sanctions_score (SCAFFOLD §1.3, PRD §3.5): weighted name+country match.
# ---------------------------------------------------------------------------
def _round_half_up(value):
    """Round a Decimal/number half-up to the nearest integer."""
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _name_overlap(subject_tokens, listed_tokens, strict):
    """Count how many listed tokens are matched by the subject's tokens.

    base variant: exact token equality.
    strict variant: prefix-containment — a listed token counts as overlapping
    when it is a prefix of one of the subject's tokens.
    """
    overlap = 0
    for lt in listed_tokens:
        if strict:
            if any(st.startswith(lt) for st in subject_tokens):
                overlap += 1
        else:
            if lt in subject_tokens:
                overlap += 1
    return overlap


def pairwise_score(subject_name, subject_country, entry):
    """Score one (party, list_entry) pair on a 0..100 scale."""
    subject_tokens = subject_name.lower().split()
    listed_tokens = entry["listed_name"].lower().split()
    strict = subject_country in HIGH_RISK_COUNTRIES

    overlap = _name_overlap(subject_tokens, listed_tokens, strict)
    denom = max(1, len(listed_tokens))
    name_ratio = Decimal(overlap) / Decimal(denom)
    name_pts = _round_half_up(name_ratio * entry["weight_name_bps"] / 100)

    if subject_country == entry["listed_country"]:
        country_pts = entry["weight_country_bps"] / 100
    else:
        country_pts = 0
    # weight_country_bps is whole-hundreds in practice; keep as int.
    country_pts = int(country_pts)
    return name_pts + country_pts


def screen_subjects(subjects, entries):
    """Compute the transfer sanctions_score over all (subject, entry) pairs.

    subjects: list of (subject_kind, subject_id, full_name, country).
    entries: list of SanctionsListEntry records.
    Returns (best_score, hits) where hits is the list of (subject_kind,
    subject_id, entry, score) pairs scoring >= SANCTIONS_CLEAR_THRESHOLD.
    The opening hit (top score, earliest list entry) is hits[0] when present.
    """
    best = 0
    hits = []
    for (kind, sid, name, country) in subjects:
        for entry in entries:
            sc = pairwise_score(name, country, entry)
            if sc > best:
                best = sc
            if sc >= SANCTIONS_CLEAR_THRESHOLD:
                hits.append((kind, sid, entry, sc))
    # Order hits by score desc, then list-entry created_at asc (earliest listed
    # entry is the opening hit) for a deterministic top-scoring hit.
    hits.sort(key=lambda h: (-h[3], h[2]["created_at"], h[2]["_seq"]))
    return best, hits


# ---------------------------------------------------------------------------
# corridor_limit_check (SCAFFOLD §1.3, PRD §3.4): three inclusive ceilings.
# ---------------------------------------------------------------------------
def kyc_ceiling(kyc_tier):
    return KYC_CEILINGS.get(kyc_tier, KYC_CEILINGS["TIER0"])


# ---------------------------------------------------------------------------
# refund_amount (SCAFFOLD §1.3, PRD §3.7): principal always fully refunded once
# funded; fee variant diverges by reason and (for SENDER_CANCEL) grace window.
# ---------------------------------------------------------------------------
def refund_amount(transfer, reason, funded_at_seconds_ago):
    """Return (principal_refunded, fee_refunded, total_refunded).

    funded_at_seconds_ago: clock-now minus the SENDER_DEBIT created_at, in
    seconds; only consulted for the SENDER_CANCEL grace-window branch.
    """
    funded = transfer["funding_status"] == "FUNDED"
    principal_refunded = transfer["send_principal_minor"] if funded else 0

    if reason == "SENDER_CANCEL":
        if not funded:
            fee_refunded = 0
        elif funded_at_seconds_ago <= REFUND_GRACE_SECONDS:
            fee_refunded = transfer["fee_minor"]
        else:
            fee_refunded = 0
    elif reason in ("COMPLIANCE_REJECT", "DELIVERY_FAILED"):
        fee_refunded = transfer["fee_minor"] if funded else 0
    else:
        fee_refunded = 0

    total = principal_refunded + fee_refunded
    return principal_refunded, fee_refunded, total
