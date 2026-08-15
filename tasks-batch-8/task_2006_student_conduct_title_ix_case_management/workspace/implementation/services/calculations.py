"""Calculation rules (PRD 2.7, 2.9, 3.8): severity scoring, the sanctioning
matrix, restitution pinned evaluation order, and annual statistics."""
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from db import db
from services.core import (
    category_base, alltime_substantiated_count, STAT_HIERARCHY_PRIORITY,
)
from util import parse_datetime

SEVERITY_PRIOR_POINTS = 15
SEVERITY_AGGRAVATING_POINTS = 10
SEVERITY_MITIGATING_POINTS = 5
SEVERITY_NCD_POINTS = 10

TIER_BANDS = {"TIER_1": (0, 24), "TIER_2": (25, 49), "TIER_3": (50, 74), "TIER_4": (75, None)}

# final_tier -> { sanction_type: (min_days, max_days) | None (duration-less) }
TIER_MATRIX = {
    "TIER_1": {
        "WARNING": None,
        "EDUCATIONAL_PROGRAM": (1, 30),
        "PROBATION": (1, 90),
    },
    "TIER_2": {
        "EDUCATIONAL_PROGRAM": (1, 60),
        "PROBATION": (30, 180),
        "SUSPENSION": (1, 90),
        "NO_CONTACT_CONTINUATION": (1, 180),
    },
    "TIER_3": {
        "PROBATION": (91, 365),
        "SUSPENSION": (91, 365),
        "RESTITUTION": None,
        "NO_CONTACT_CONTINUATION": (1, 365),
    },
    "TIER_4": {
        "SUSPENSION": (180, 730),
        "EXPULSION": None,
        "RESTITUTION": None,
        "NO_CONTACT_CONTINUATION": (1, 730),
    },
}

RESTITUTION_CAP_CENTS = {"TIER_1": 0, "TIER_2": 0, "TIER_3": 50000, "TIER_4": 250000}
RESTITUTION_POINT_UNIT_CENTS = 100

DURATION_TYPES = {"PROBATION", "SUSPENSION", "EDUCATIONAL_PROGRAM", "NO_CONTACT_CONTINUATION"}
DURATION_LESS_TYPES = {"WARNING", "EXPULSION", "RESTITUTION"}


def matrix_score(case, det, variant):
    """calc_sanction_severity_score. PROVISIONAL excludes mitigating; FINAL includes."""
    score = category_base(case)
    score += SEVERITY_PRIOR_POINTS * det.get("prior_responsible_findings", 0)
    score += SEVERITY_AGGRAVATING_POINTS * det.get("aggravating_factor_count", 0)
    mitigating = det.get("mitigating_factor_count", 0) if variant == "FINAL" else 0
    score -= SEVERITY_MITIGATING_POINTS * mitigating
    score += SEVERITY_NCD_POINTS * alltime_substantiated_count(case["id"])
    return score


def tier_of(score):
    """Tier bands with inclusive lower bounds (PRD 2.9)."""
    if score >= 75:
        return "TIER_4"
    if score >= 50:
        return "TIER_3"
    if score >= 25:
        return "TIER_2"
    return "TIER_1"


def item_cents(amount_dollars) -> int:
    """Per-item round_half_up(amount * 100) BEFORE any summing (PRD 2.9 step 2)."""
    cents = Decimal(str(amount_dollars)) * 100
    return int(cents.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def restitution_applied_cents(items, cap_tier):
    """Steps 2-4: per-item round, sum, clamp to the cap-tier cap."""
    summed = sum(item_cents(it.get("amount_dollars")) for it in items)
    return min(summed, RESTITUTION_CAP_CENTS[cap_tier])


def restitution_points(applied_cents) -> int:
    """Step 5: floor(applied_cents / 100)."""
    return applied_cents // RESTITUTION_POINT_UNIT_CENTS


# ---------------------------------------------------------------------------
# Annual statistics (PRD 3.8)
# ---------------------------------------------------------------------------

def compute_annual_statistics(year: int) -> dict:
    start = datetime(year, 1, 1, tzinfo=timezone.utc)
    end = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
    included = [
        c for c in db["cases"].values()
        if start <= parse_datetime(c["received_at"]) < end
    ]
    included_ids = {c["id"] for c in included}

    reports_received = len(included)
    formal_complaints_filed = sum(1 for c in included if c.get("formal_complaint_signed"))
    dismissed = sum(1 for c in included if c["status"] == "DISMISSED")
    referred = sum(1 for c in included if c["status"] == "REFERRED_TO_CONDUCT")
    informal_resolved = sum(1 for c in included if c["status"] == "RESOLVED_INFORMAL")
    hearings_completed = sum(
        1 for h in db["hearings"].values()
        if h["status"] == "COMPLETED" and h["case_id"] in included_ids
    )

    # Responsible-determination rule: latest determination per case by
    # issued_at ASC (tie: created_at ASC); counted when that latest one is
    # RESPONSIBLE with status in {ISSUED, FINAL, SUPERSEDED}.
    determinations_responsible = 0
    for c in included:
        dets = [
            d for d in db["determinations"].values()
            if d["case_id"] == c["id"] and d.get("issued_at") is not None
        ]
        if not dets:
            continue
        latest = max(dets, key=lambda d: (parse_datetime(d["issued_at"]), d["created_at"], d["_seq"]))
        if latest["responsibility_finding"] == "RESPONSIBLE" \
                and latest["status"] in ("ISSUED", "FINAL", "SUPERSEDED"):
            determinations_responsible += 1

    # Hierarchy rule: each case counted in exactly one bucket (highest priority).
    per_category = {}
    for c in included:
        assigned = max(c["categories"], key=lambda cat: STAT_HIERARCHY_PRIORITY[cat])
        per_category[assigned] = per_category.get(assigned, 0) + 1

    # avg_resolution_days: floor per case, exact mean, single round_half_up last.
    resolved = [
        c for c in included
        if c.get("closed_at") is not None and parse_datetime(c["closed_at"]) < end
    ]
    if not resolved:
        avg_resolution_days = None
    else:
        day_counts = [
            int((parse_datetime(c["closed_at"]) - parse_datetime(c["received_at"])).total_seconds() // 86400)
            for c in resolved
        ]
        mean = Decimal(sum(day_counts)) / Decimal(len(day_counts))
        avg_resolution_days = float(mean.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))

    return {
        "reports_received": reports_received,
        "formal_complaints_filed": formal_complaints_filed,
        "dismissed": dismissed,
        "referred": referred,
        "hearings_completed": hearings_completed,
        "informal_resolved": informal_resolved,
        "determinations_responsible": determinations_responsible,
        "per_category": per_category,
        "avg_resolution_days": avg_resolution_days,
    }
