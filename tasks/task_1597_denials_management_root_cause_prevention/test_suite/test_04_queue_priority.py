"""Work-queue priority scoring, bucket boundaries, and ranking (PRD §2.10)."""
from test_helpers import (
    get_denial,
    make_appeal,
    make_queued_denial,
    make_submitted_appeal,
    record_outcome,
    set_clock,
    setup_catalog,
    validate_paginated,
    validate_success,
)

PRIORITY_FORMULA_CITE = (
    'PRD §2.10: "**Dollar component.** The denial\'s `open_balance_cents` divided by 10000, '
    'capped at 50 points."\n'
    'PRD §2.10: "**Deadline component.** Let the days remaining be the number of whole days '
    'from today\'s logical date to `next_appeal_deadline`, never less than zero. When more '
    'than 30 days remain, the component is zero; otherwise it is 45 minus 1.5 points per '
    'day remaining, never below zero."\n'
    'PRD §2.10: "**Level boost.** 5 points per appeal level reached, counting at most 2 '
    'levels — so a denial at `current_appeal_level` 1 gains 5 points, and one at level 2 '
    'or 3 gains 10."'
)


def test_priority_score_components_before_appeal(api, specialist_headers):
    """PRD §2.10: "**Dollar component.** The denial's `open_balance_cents` divided by 10000,
    capped at 50 points."
    PRD §2.10: "**Deadline component.** Let the days remaining be the number of whole days
    from today's logical date to `next_appeal_deadline`, never less than zero. When more than
    30 days remain, the component is zero; otherwise it is 45 minus 1.5 points per day
    remaining, never below zero."
    PRD §2.10: "The `queue_bucket` derives from the score with inclusive lower boundaries:
    `CRITICAL` at 70.00 or higher, `HIGH` at 50.00 or higher, `MEDIUM` at 25.00 or higher,
    and `LOW` below 25.00."

    Design: Difficulty/combinatorial_formula/queue_priority_multifactor_scoring
    """
    catalog = setup_catalog(levels=(1,))
    denial = make_queued_denial(
        catalog["payer"]["id"], catalog["code"]["id"],
        claim_number="CLM-301", denied_amount_cents=250000,
    )
    assert denial["next_appeal_deadline"] == "2026-09-30"
    set_clock("2026-09-16T00:00:00Z")  # 14 days remaining
    denial = get_denial(denial["id"])
    # min(250000/10000, 50) = 25; max(0, 45 - 1.5*14) = 24; level boost 0
    assert denial["priority_score"] == 49.00
    assert denial["queue_bucket"] == "MEDIUM"


def test_priority_level_boost_after_appeal_create(api, specialist_headers):
    """PRD §2.10: "**Level boost.** 5 points per appeal level reached, counting at most 2
    levels — so a denial at `current_appeal_level` 1 gains 5 points, and one at level 2 or 3
    gains 10."
    PRD §3.4: "The first appeal moves its denial `QUEUED` → `IN_APPEAL`, setting
    `current_appeal_level` to 1 while leaving `next_appeal_deadline` unchanged — it already
    holds the level-1 deadline."

    Design: Difficulty/combinatorial_formula/queue_priority_multifactor_scoring
    """
    catalog = setup_catalog(levels=(1,))
    denial = make_queued_denial(
        catalog["payer"]["id"], catalog["code"]["id"],
        claim_number="CLM-301", denied_amount_cents=250000,
    )
    set_clock("2026-09-16T00:00:00Z")
    appeal = make_appeal(denial["id"])
    assert appeal["level_number"] == 1
    denial = get_denial(denial["id"])
    assert denial["current_appeal_level"] == 1
    # 25 + 24 + 5*min(1,2) = 54.00
    assert denial["priority_score"] == 54.00
    assert denial["queue_bucket"] == "HIGH"


def test_queue_bucket_exact_boundary(api, specialist_headers):
    """PRD §2.10: "The `queue_bucket` derives from the score with inclusive lower boundaries:
    `CRITICAL` at 70.00 or higher, `HIGH` at 50.00 or higher, `MEDIUM` at 25.00 or higher,
    and `LOW` below 25.00."

    Design: Corner/calculations/queue_bucket_exact_boundary
    """
    catalog = setup_catalog(levels=(1,))
    denial = make_queued_denial(
        catalog["payer"]["id"], catalog["code"]["id"],
        claim_number="CLM-2203", denied_amount_cents=200000, billed_amount_cents=220000,
    )
    set_clock("2026-09-20T00:00:00Z")  # 10 days remaining to 2026-09-30
    denial = get_denial(denial["id"])
    # min(200000/10000, 50) = 20; max(0, 45 - 1.5*10) = 30; total exactly 50.00
    assert denial["priority_score"] == 50.00
    assert denial["queue_bucket"] == "HIGH", "the >= 50.00 boundary is inclusive"


def test_priority_zero_for_terminal_denial(api, specialist_headers):
    """PRD §2.10: "Only denials in `QUEUED` or `IN_APPEAL` are workable; a denial in any
    other status has a `priority_score` of exactly 0.00 and a `queue_bucket` of `LOW`, and
    never appears in the queue."

    Design: Corner/calculations/priority_zero_for_terminal_denial
    """
    catalog = setup_catalog(levels=(1,))
    denial_id, appeal = None, None
    denial = make_queued_denial(
        catalog["payer"]["id"], catalog["code"]["id"],
        claim_number="CLM-2204", denied_amount_cents=100000, billed_amount_cents=120000,
    )
    denial_id = denial["id"]
    appeal = make_submitted_appeal(denial_id)
    record_outcome(appeal["id"], "OVERTURNED", 100000)
    denial = get_denial(denial_id)
    assert denial["status"] == "RESOLVED_PAID"
    assert denial["priority_score"] == 0.00
    assert denial["queue_bucket"] == "LOW"
    rows, meta = validate_paginated(api.get_work_queue(specialist_headers))
    assert rows == [] and meta["total_count"] == 0


def test_work_queue_ranking_deterministic(api, specialist_headers):
    """PRD §2.10: "The ranked work queue available to `DenialsSpecialist` and
    `DenialsManager` contains exactly the workable denials, ordered by `priority_score`
    descending; ties break to the earlier `next_appeal_deadline`, and remaining ties break to
    the earlier `created_at`. Resource ids are never used for ranking."

    Design: Corner/endpoints/work_queue_ranking_deterministic
    """
    catalog = setup_catalog(levels=(1,))
    low = make_queued_denial(
        catalog["payer"]["id"], catalog["code"]["id"],
        claim_number="CLM-2403", denied_amount_cents=250000,
    )
    high = make_queued_denial(
        catalog["payer"]["id"], catalog["code"]["id"],
        claim_number="CLM-2404", denied_amount_cents=1000000, billed_amount_cents=1100000,
    )
    set_clock("2026-09-16T00:00:00Z")  # 14 days remaining to 2026-09-30
    rows, meta = validate_paginated(api.get_work_queue(specialist_headers))
    assert meta["total_count"] == 2 and len(rows) == 2
    # CLM-2404: min(100, 50) = 50 + 24 deadline = 74.00 CRITICAL; CLM-2403: 25 + 24 = 49.00 MEDIUM
    assert rows[0]["id"] == high["id"]
    assert rows[0]["priority_score"] == 74.00
    assert rows[0]["queue_bucket"] == "CRITICAL"
    assert rows[1]["id"] == low["id"]
    assert rows[1]["priority_score"] == 49.00
    assert rows[1]["queue_bucket"] == "MEDIUM"
