"""Participation fee assessment (PRD 3.10)."""
import math
from decimal import Decimal

from db import parse_iso
from errors import ApiError
from services import repo
from services.precision import cents, dec, out, rhu

TIER_1_CAP = 24750
TIER_2_CAP = 99750
TIER_1_RATE_CENTS = Decimal("1.75")
TIER_2_RATE_CENTS = Decimal("1.25")
TIER_3_RATE_CENTS = Decimal("0.65")
BASE_PLATFORM_FEE_CENTS = 250000
QUALITY_MULTIPLIER = {
    "A": Decimal("0.95"),
    "B": Decimal("1.00"),
    "C": Decimal("1.08"),
    "D": Decimal("1.20"),
    "UNGRADED": Decimal("1.00"),
}
RECONCILED_FEED_STATUSES = ("MONITORED", "DEGRADED")


def tier_units(volume):
    units_1 = min(volume, TIER_1_CAP)
    units_2 = min(max(volume - TIER_1_CAP, 0), TIER_2_CAP - TIER_1_CAP)
    units_3 = max(volume - TIER_2_CAP, 0)
    return units_1, units_2, units_3


def tier_for(units_1, units_2, units_3):
    if units_3 > 0:
        return "TIER_3"
    if units_2 > 0:
        return "TIER_2"
    return "TIER_1"


def assess(volume, quality_grade, multiplier_override=None):
    """Each tier charge is rounded to whole cents on its own, then summed."""
    units_1, units_2, units_3 = tier_units(volume)
    charge_1 = cents(Decimal(units_1) * TIER_1_RATE_CENTS)
    charge_2 = cents(Decimal(units_2) * TIER_2_RATE_CENTS)
    charge_3 = cents(Decimal(units_3) * TIER_3_RATE_CENTS)
    volume_fee = charge_1 + charge_2 + charge_3
    if multiplier_override is not None:
        multiplier = multiplier_override
    else:
        multiplier = QUALITY_MULTIPLIER[quality_grade or "UNGRADED"]
    total = cents((Decimal(BASE_PLATFORM_FEE_CENTS) + Decimal(volume_fee)) * multiplier)
    return {
        "billable_volume_units": volume,
        "tier_charge_breakdown": {
            "TIER_1": charge_1,
            "TIER_2": charge_2,
            "TIER_3": charge_3,
        },
        "volume_fee_cents": volume_fee,
        "base_platform_fee_cents": BASE_PLATFORM_FEE_CENTS,
        "fee_tier": tier_for(units_1, units_2, units_3),
        "quality_grade_snapshot": quality_grade,
        "quality_multiplier": out(multiplier),
        "total_cents": total,
    }


def provisional_volume(participant):
    declared = int(participant["declared_annual_patient_volume"] or 0)
    return int(math.ceil(declared / 12.0))


def provisional(participant):
    """The multiplier is forced to 1.00 for every provisional assessment."""
    return assess(
        provisional_volume(participant),
        participant.get("quality_grade") or "UNGRADED",
        multiplier_override=Decimal("1.00"),
    )


def reconciliation_samples(participant_id, period_start, period_end):
    """Samples wholly contained in the billing period on a qualifying feed."""
    feed_ids = set()
    for feed in repo.participant_feeds(participant_id):
        if feed["status"] in RECONCILED_FEED_STATUSES:
            feed_ids.add(feed["id"])
    matched = []
    for feed_id in feed_ids:
        for sample in repo.feed_samples(feed_id):
            start = parse_iso(sample["period_start"])
            end = parse_iso(sample["period_end"])
            if start is None or end is None:
                continue
            if start >= period_start and end <= period_end:
                matched.append(sample)
    return matched


def reconciled(participant, period_start, period_end):
    samples = reconciliation_samples(participant["id"], period_start, period_end)
    if not samples:
        raise ApiError("ERR_NO_RECONCILIATION_BASIS")
    volume = sum(int(s["messages_received"] or 0) for s in samples)
    grade = participant.get("quality_grade") or "UNGRADED"
    return assess(volume, grade)
