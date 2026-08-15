"""Timely-filing expiry sweep and its three-hop cascade (PRD §2.4, §3.5)."""
from test_helpers import (
    get_denial,
    get_scorecard,
    make_queued_denial,
    make_scorecard,
    set_clock,
    setup_catalog,
    validate_paginated,
    validate_success,
)

SWEEP_CITE = (
    'PRD §3.5: "Advancing the logical clock (§2.4) sweeps every denial for lapsed filing '
    'rights, processing candidates in `created_at` ascending order. A denial in `QUEUED` '
    'whose `next_appeal_deadline` now lies before today expires: `QUEUED` → '
    '`CLOSED_EXPIRED`."'
)


def test_clock_sweep_expires_denial_and_autocreates_writeoff(api, specialist_headers):
    """PRD §3.5: "Hop one moves the denial to `CLOSED_EXPIRED`, clears its
    `next_appeal_deadline` to null, and appends an `EXPIRED` event. Hop two auto-creates a
    write-off request for the full `open_balance_cents` with `reason_code`
    `TIMELY_FILING_EXPIRED` and `requested_by_user_id` set to the literal string `system`,
    deriving the request's tier and initial status through the standard write-off computation
    of §3.6, and appends a `WRITE_OFF_REQUESTED` event."

    Design: Difficulty/transitive_cascade/clock_sweep_expiry_cascade
    """
    catalog = setup_catalog(levels=(1,))
    make_scorecard(period_end_date="2026-12-31")
    denial = make_queued_denial(
        catalog["payer"]["id"], catalog["code"]["id"], claim_number="CLM-601",
    )
    assert denial["next_appeal_deadline"] == "2026-09-30"
    clock = set_clock("2026-10-01T00:00:00Z")
    assert denial["id"] in clock["expired_denial_ids"]
    denial = get_denial(denial["id"])
    assert denial["status"] == "CLOSED_EXPIRED"
    assert denial["next_appeal_deadline"] is None
    rows, meta = validate_paginated(
        api.list_write_off_requests(
            specialist_headers, params={"denial_case_id": denial["id"]},
        )
    )
    assert meta["total_count"] == 1, "exactly one write-off request is auto-created"
    request = rows[0]
    assert request["requested_amount_cents"] == 250000
    assert request["reason_code"] == "TIMELY_FILING_EXPIRED"
    assert request["requested_by_user_id"] == "system"
    assert request["approval_tier"] == "STANDARD"
    assert request["status"] == "PENDING_MANAGER"


def test_clock_sweep_scorecard_counters_and_queue_eviction(api, specialist_headers):
    """PRD §3.5: "Hop three increments `expired_denial_count` and
    `auto_writeoff_request_count` on the `OPEN` scorecard for the denial's
    `root_cause_department` whose period contains the new clock date."
    PRD §2.10: "Only denials in `QUEUED` or `IN_APPEAL` are workable; a denial in any other
    status has a `priority_score` of exactly 0.00 and a `queue_bucket` of `LOW`, and never
    appears in the queue."

    Design: Difficulty/transitive_cascade/clock_sweep_expiry_cascade
    """
    catalog = setup_catalog(levels=(1,))
    scorecard = make_scorecard(period_end_date="2026-12-31")
    denial = make_queued_denial(
        catalog["payer"]["id"], catalog["code"]["id"], claim_number="CLM-601",
    )
    set_clock("2026-10-01T00:00:00Z")
    sc = get_scorecard(scorecard["id"])
    assert sc["expired_denial_count"] == 1
    assert sc["auto_writeoff_request_count"] == 1
    rows, meta = validate_paginated(api.get_work_queue(specialist_headers))
    assert all(row["id"] != denial["id"] for row in rows)
    assert meta["total_count"] == 0
