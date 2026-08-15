"""Monetary calculations (PRD 2.7, 3.7, 3.8; scaffold calculations
letter_fee_estimate / credit_band / assessment_validity /
retainer_required_amount)."""

from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

import db

MONTHS_MULTIPLIER = {"PRIME": 1, "STANDARD": 2, "SUBPRIME": 3}
RETAINER_MIN_CENTS = 50000
RETAINER_MAX_CENTS = 10000000
ASSESSMENT_VALID_DAYS = 90
PRIME_MIN = 740
STANDARD_MIN = 670


def fee_estimate_cents(fee_lines):
    """round_half_up(hours * rate_cents) PER LINE, then sum (order pinned)."""
    total = 0
    for line in fee_lines:
        product = Decimal(str(line["hours"])) * Decimal(int(line["rate_cents"]))
        total += int(product.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    return total


def credit_band(score):
    """Inclusive lower bounds: 740 PRIME, 670..739 STANDARD, <670 SUBPRIME."""
    if score >= PRIME_MIN:
        return "PRIME"
    if score >= STANDARD_MIN:
        return "STANDARD"
    return "SUBPRIME"


def assessment_valid(assessment, at=None):
    """Valid iff T <= assessed_at + 90 days (staleness is strict: exactly
    90 days old is still valid)."""
    at = at if at is not None else db.now()
    assessed_at = db.parse_ts(assessment["assessed_at"])
    return at <= assessed_at + timedelta(days=ASSESSMENT_VALID_DAYS)


def _latest_assessment(assessments):
    """Latest assessed_at; tie on assessed_at broken by later created_at
    (insertion order as final stable tiebreak)."""
    best = None
    best_key = None
    for a in assessments:
        key = (db.parse_ts(a["assessed_at"]), a["created_at"])
        if best is None or key >= best_key:
            best = a
            best_key = key
    return best


def latest_letter_for_fee(matter_id):
    """Latest-created EngagementLetter of the matter in {DRAFT, ISSUED}."""
    letters = [
        l for l in db.store.engagement_letters.values()
        if l["matter_id"] == matter_id and l["status"] in ("DRAFT", "ISSUED")
    ]
    if not letters:
        return None
    return max(letters, key=lambda l: l["created_at"])


def retainer_required_amount(matter_id, at=None):
    """V_RECENT pinned: band of the latest-assessed VALID assessment
    (SUBPRIME default when none valid) x fee of latest DRAFT/ISSUED letter,
    clamped to [50000, 10000000]."""
    at = at if at is not None else db.now()
    assessments = [
        a for a in db.store.credit_assessments.values()
        if a["matter_id"] == matter_id
    ]
    valid = [a for a in assessments if assessment_valid(a, at)]
    if valid:
        band = _latest_assessment(valid)["band"]
    else:
        band = "SUBPRIME"
    letter = latest_letter_for_fee(matter_id)
    fee = letter["fee_estimate_cents"] if letter else 0
    raw = fee * MONTHS_MULTIPLIER[band]
    return min(max(raw, RETAINER_MIN_CENTS), RETAINER_MAX_CENTS)


def derive_deposit_status(deposit):
    """PENDING (received==0) | PARTIALLY_FUNDED (0<received<required) |
    FUNDED (received>=required; equality counts)."""
    received = deposit["received_cents"]
    if received == 0:
        return "PENDING"
    if received < deposit["required_cents"]:
        return "PARTIALLY_FUNDED"
    return "FUNDED"


def refresh_deposit(deposit, at=None):
    """Recompute required_cents, received_cents and re-derive status after a
    deposit-affecting event (letter ISSUE, new CreditAssessment). Bumps the
    deposit version only when a stored value actually changes."""
    at = at if at is not None else db.now()
    changed = False
    required = retainer_required_amount(deposit["matter_id"], at)
    if required != deposit["required_cents"]:
        deposit["required_cents"] = required
        changed = True
    received = deposit["funded_total_cents"] - deposit["refunded_total_cents"]
    if received != deposit["received_cents"]:
        deposit["received_cents"] = received
        changed = True
    status = derive_deposit_status(deposit)
    if status != deposit["status"]:
        deposit["status"] = status
        changed = True
    if changed:
        db.bump(deposit)
    return deposit


def deposit_for_matter(matter_id):
    """At most one deposit ever exists per matter."""
    for d in db.store.retainer_deposits.values():
        if d["matter_id"] == matter_id:
            return d
    return None
