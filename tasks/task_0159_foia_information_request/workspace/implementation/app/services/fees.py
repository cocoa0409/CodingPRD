"""Fee calculation rules (SCAFFOLD §1.3 / PRD §2.9 / §3.3 / §3.8).

All arithmetic is in integer cents.  ``estimated_search_hours`` and
``estimated_review_hours`` are stored as floats (one-decimal-place values
in the spec, but the code does not assume strict integer multiples).

Two entry points:

  * :func:`calc_fee_estimate`  — DRAFT → ESTIMATED.
  * :func:`calc_fee_final`     — SEARCH → DETERMINATION_PENDING.
"""

from __future__ import annotations

from typing import Iterable

# Constants (all in integer cents / integer multipliers)
SEARCH_RATE_CENTS_PER_HOUR = 4500
REVIEW_RATE_CENTS_PER_HOUR = 6000
COPY_RATE_CENTS_PER_PAGE = 10
FREE_PAGES = 100
FREE_SEARCH_HOURS = 2
FREE_THRESHOLD_CENTS = 1400
FINAL_CAP_MULTIPLIER_TIMES_100 = 125


def _cents_for_hours(hours: float, rate_cents_per_hour: int) -> int:
    """Multiply hours by integer-cent rate.

    The PRD stores hours at one decimal place; to avoid float drift we scale
    by ten, do integer arithmetic, and round any residual sub-tenth-of-an-hour
    fragment toward zero.  In practice tests feed integer or .5/.1 values.
    """

    if hours <= 0:
        return 0
    # Scale by 10 to keep the tenth-of-an-hour granularity in integers.
    scaled = int(round(hours * 10))
    # cents = (scaled tenths) * rate / 10 — use integer-division semantics.
    return (scaled * rate_cents_per_hour) // 10


def _per_tier_chargeable(
    tier: str, search_hours: float, review_hours: float, pages: int
):
    if tier == "COMMERCIAL":
        chargeable_search = float(search_hours)
        chargeable_review = float(review_hours)
        chargeable_pages = max(0, int(pages))
    elif tier == "EDUCATIONAL_NONCOMMERCIAL":
        chargeable_search = 0.0
        chargeable_review = 0.0
        chargeable_pages = max(0, int(pages) - FREE_PAGES)
    elif tier == "PUBLIC_INTEREST":
        chargeable_search = max(0.0, float(search_hours) - FREE_SEARCH_HOURS)
        chargeable_review = 0.0
        chargeable_pages = max(0, int(pages) - FREE_PAGES)
    else:  # pragma: no cover — caller validates tier
        raise ValueError(f"Unknown tier: {tier}")
    return chargeable_search, chargeable_review, chargeable_pages


def _subtotal_cents(
    chargeable_search: float, chargeable_review: float, chargeable_pages: int
) -> int:
    return (
        _cents_for_hours(chargeable_search, SEARCH_RATE_CENTS_PER_HOUR)
        + _cents_for_hours(chargeable_review, REVIEW_RATE_CENTS_PER_HOUR)
        + chargeable_pages * COPY_RATE_CENTS_PER_PAGE
    )


def calc_fee_estimate(
    *, tier: str, estimated_pages: int, estimated_search_hours: float, estimated_review_hours: float
) -> int:
    s, r, p = _per_tier_chargeable(
        tier, estimated_search_hours, estimated_review_hours, estimated_pages
    )
    subtotal = _subtotal_cents(s, r, p)
    if subtotal < FREE_THRESHOLD_CENTS:
        return 0
    return subtotal


def calc_fee_final(
    *,
    tier: str,
    actual_pages: int,
    estimated_search_hours: float,
    estimated_review_hours: float,
    estimate_total_cents: int,
) -> int:
    """Recompute the final fee using actuals + cap rule (PRD §3.8)."""

    s, r, p = _per_tier_chargeable(
        tier, estimated_search_hours, estimated_review_hours, actual_pages
    )
    subtotal = _subtotal_cents(s, r, p)
    # Free-threshold collapse first.
    if subtotal < FREE_THRESHOLD_CENTS:
        return 0
    # Cap rule.
    if estimate_total_cents == 0:
        cap = FREE_THRESHOLD_CENTS - 1  # 1399 cents
    else:
        scaled = (estimate_total_cents * FINAL_CAP_MULTIPLIER_TIMES_100) // 100
        cap = max(estimate_total_cents, scaled)
    return min(subtotal, cap)


def sum_chargeable_pages(records: Iterable[dict]) -> int:
    """Sum page_count of records eligible for final-fee chargeable pages.

    Records with disposition in {RELEASED_FULL, RELEASED_REDACTED} count;
    WITHHELD_FULL records do not contribute, per PRD §3.8.  Records are
    aggregated in ``created_at`` ascending order for determinism (immaterial
    to the sum, but pinned by the spec).
    """

    eligible = [
        r
        for r in records
        if r.get("disposition") in ("RELEASED_FULL", "RELEASED_REDACTED")
    ]
    eligible.sort(key=lambda r: r["created_at"])
    return sum(int(r["page_count"]) for r in eligible)
