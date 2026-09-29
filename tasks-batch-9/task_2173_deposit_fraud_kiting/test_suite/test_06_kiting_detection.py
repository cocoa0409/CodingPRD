"""Kiting detection across the on-us circulation graph."""

from test_helpers import (
    create_active_account,
    read_account,
    read_case,
    settle_item,
    setup_two_account_kiting_ring,
    take_deposit,
    validate_paginated,
    validate_success,
)

WINDOW = {"window_start_at": "2026-07-01T00:00:00Z", "window_end_at": "2026-09-01T00:00:00Z"}


def _ring_with_one_cleared_item():
    """Four on-us CHECK items circulating between two accounts, the last cleared."""
    ring = setup_two_account_kiting_ring(item_amount_cents=30000, item_count=4)
    settle_item(ring["items"][3]["id"], "CLEARED")
    return ring


# ===========================================================================
# STRICT versus INCLUSIVE qualifying statuses
# ===========================================================================
def test_strict_mode_counts_only_pending_items_and_falls_short_of_the_threshold(
    api, analyst_headers
):
    """PRD §3.6: "The qualifying-status set is the *entire* difference between the
    two modes: `STRICT` admits only items still in `PENDING`, the same-day float
    view; `INCLUSIVE` admits items in `PENDING`, `CLEARED`, and `RETURNED` alike,
    the historical-pattern view used for case building. On identical data the two
    modes produce different scores and can land on opposite sides of the detection
    threshold."
    PRD §3.6: "The raw score adds three terms. The first is a base for the cycle's
    size: 40 points for a two-account cycle, 55 for a three-account cycle, 60 for a
    four-account cycle, and nothing at all when no cycle was found. The second is a
    velocity term of 6 points for each qualifying item on the chosen cycle. The
    third is an uncollected-funds term equal to 30 multiplied by
    `uncollected_ratio_bps`, divided by 10,000, and rounded half up to a whole point
    — so a fully uncollected cycle contributes the full 30 points and a
    half-uncollected one contributes 15. `kiting_score` is the raw total capped at
    100, and `detected` is true exactly when `kiting_score` is 70 or more."
    PRD §3.6: "When `detected` is false, nothing else happens: no case is created,
    no account is transitioned, and `fraud_case_id` comes back null."

    Design: Difficulty/dual_variant_calc/kiting_strict_versus_inclusive_qualifying_statuses_on_circulation_graph
    """
    ring = _ring_with_one_cleared_item()

    scan = validate_success(
        api.run_kiting_scan(ring["account_a_id"], {"mode": "STRICT", **WINDOW}, analyst_headers)
    )

    assert scan["cycle_length"] == 2
    assert scan["qualifying_item_count"] == 3, "The cleared item leaves the STRICT edge set"
    assert scan["deposited_cents"] == 90000
    assert scan["uncollected_cents"] == 22500
    assert scan["uncollected_ratio_bps"] == 2500, "floor(10000 * 22500 / 90000)"
    # 40 + 6 * 3 + round_half_up(30 * 2500 / 10000) = 40 + 18 + 8.
    assert scan["kiting_score"] == 66, f"Expected 40 + 18 + 8 = 66, got {scan['kiting_score']}"
    assert scan["detected"] is False, "66 is below the detection threshold of 70"
    assert scan["fraud_case_id"] is None

    account = read_account(ring["account_a_id"], analyst_headers)
    assert account["lifecycle_status"] == "ACTIVE", "A non-detecting scan transitions nothing"

    _rows, meta = validate_paginated(
        api.list_account_fraud_cases(ring["account_a_id"], analyst_headers)
    )
    assert meta["total_count"] == 0


def test_inclusive_mode_reaches_the_threshold_and_cascades_a_kiting_case_open(
    api, analyst_headers
):
    """PRD §3.6: "The qualifying-status set is the *entire* difference between the
    two modes: `STRICT` admits only items still in `PENDING`, the same-day float
    view; `INCLUSIVE` admits items in `PENDING`, `CLEARED`, and `RETURNED` alike,
    the historical-pattern view used for case building."
    PRD §3.6: "`uncollected_cents` is the sum of `held_amount_cents` over every
    check hold in `ACTIVE` status whose parent item belongs to any account in
    `cycle_account_ids`, and it is taken from `ACTIVE` holds regardless of mode —
    so a cleared item drops out of `deposited_cents` *and* takes its hold out of
    `uncollected_cents` under `STRICT`, but under `INCLUSIVE` it stays in
    `deposited_cents` while its hold still drops out."
    PRD §3.6: "When `detected` is true, the server opens a fraud case with
    `case_type` `KITING`, `detection_source` `KITING_SCAN`, and `status` `OPENED`,
    copying the scan's `kiting_score`, the requested mode into `scan_mode`, and the
    chosen `cycle_account_ids` onto the case, and returns the new case's identifier
    as `fraud_case_id`. The scanned account then transitions `ACTIVE → RESTRICTED`;
    an account already `RESTRICTED` simply stays `RESTRICTED`, with no error."

    Design: Difficulty/dual_variant_calc/kiting_strict_versus_inclusive_qualifying_statuses_on_circulation_graph
    """
    ring = _ring_with_one_cleared_item()

    scan = validate_success(
        api.run_kiting_scan(ring["account_a_id"], {"mode": "INCLUSIVE", **WINDOW}, analyst_headers)
    )

    assert scan["cycle_length"] == 2
    assert scan["qualifying_item_count"] == 4, "INCLUSIVE keeps the cleared item as an edge"
    assert scan["deposited_cents"] == 120000
    assert scan["uncollected_cents"] == 22500, (
        "The cleared item's hold left ACTIVE, so it drops out under either mode"
    )
    assert scan["uncollected_ratio_bps"] == 1875, "floor(10000 * 22500 / 120000)"
    # 40 + 6 * 4 + round_half_up(30 * 1875 / 10000) = 40 + 24 + 6.
    assert scan["kiting_score"] == 70, f"Expected 40 + 24 + 6 = 70, got {scan['kiting_score']}"
    assert scan["detected"] is True, "70 meets the detection threshold exactly"
    assert scan["fraud_case_id"] is not None

    case = read_case(scan["fraud_case_id"], analyst_headers)
    assert case["case_type"] == "KITING"
    assert case["detection_source"] == "KITING_SCAN"
    assert case["scan_mode"] == "INCLUSIVE"
    assert case["kiting_score"] == 70
    assert case["status"] == "OPENED"

    account = read_account(ring["account_a_id"], analyst_headers)
    assert account["lifecycle_status"] == "RESTRICTED"


# ===========================================================================
# Empty qualifying sets score zero rather than dividing by zero
# ===========================================================================
def _two_accounts_joined_by_one_acyclic_edge():
    drawer = create_active_account(legal_name="Odile Fairweather", tin_last4="1212")
    depositor = create_active_account(legal_name="Odile Fairweather II", tin_last4="1213")
    take_deposit(
        depositor["account_id"],
        item_type="CHECK",
        amount_cents=40000,
        drawee_account_id=drawer["account_id"],
    )
    return drawer, depositor


def test_an_acyclic_edge_set_scores_zero_with_a_zero_uncollected_ratio(api, analyst_headers):
    """PRD §3.6: "**Choosing the cycle.** The detector looks for directed cycles in
    that edge set which pass through the scanned account and contain at most four
    distinct accounts. If there are none, `cycle_length` is 0 and
    `cycle_account_ids` is empty."
    PRD §3.6: "`qualifying_item_count` is the number of qualifying items whose
    drawn-on-to-depositing pair is an edge of the chosen cycle, and
    `deposited_cents` is the sum of `amount_cents` over exactly those items; both
    are 0 when no cycle was found."
    PRD §3.6: "`uncollected_ratio_bps` is 0 when `deposited_cents` is 0; otherwise
    it is `uncollected_cents` multiplied by 10,000, divided by `deposited_cents`,
    and floored to whole basis points."
    PRD §3.6: "When `detected` is false, nothing else happens: no case is created,
    no account is transitioned, and `fraud_case_id` comes back null."

    Design: Difficulty/boundary_precision_check/kiting_scan_on_empty_qualifying_set_scores_zero_without_division_error
    """
    drawer, _depositor = _two_accounts_joined_by_one_acyclic_edge()

    scan = validate_success(
        api.run_kiting_scan(drawer["account_id"], {"mode": "STRICT", **WINDOW}, analyst_headers)
    )

    assert scan["cycle_length"] == 0
    assert scan["cycle_account_ids"] == []
    assert scan["qualifying_item_count"] == 0
    assert scan["deposited_cents"] == 0
    assert scan["uncollected_cents"] == 0
    assert scan["uncollected_ratio_bps"] == 0, (
        "A zero denominator yields a zero ratio, not a division fault"
    )
    assert scan["kiting_score"] == 0
    assert scan["detected"] is False
    assert scan["fraud_case_id"] is None

    _rows, meta = validate_paginated(
        api.list_account_fraud_cases(drawer["account_id"], analyst_headers)
    )
    assert meta["total_count"] == 0
    assert read_account(drawer["account_id"], analyst_headers)["lifecycle_status"] == "ACTIVE"


def test_a_window_containing_no_items_at_all_scores_zero(api, analyst_headers):
    """PRD §3.6: "**Building the graph.** Only deposited items qualify as edges,
    and only those whose `item_type` is `CHECK`, whose `drawee_account_id` is not
    null, whose `deposit_at` falls at or after `window_start_at` and strictly before
    `window_end_at`, and whose `status` is in the mode's qualifying set."
    PRD §3.6: "`uncollected_ratio_bps` is 0 when `deposited_cents` is 0; otherwise
    it is `uncollected_cents` multiplied by 10,000, divided by `deposited_cents`,
    and floored to whole basis points."
    PRD §3.6: "The scan always returns every intermediate figure — `kiting_score`,
    `cycle_length`, `cycle_account_ids`, `qualifying_item_count`, `deposited_cents`,
    `uncollected_cents`, `uncollected_ratio_bps`, `detected`, and `fraud_case_id` —
    so the analyst can see the arithmetic."

    Design: Difficulty/boundary_precision_check/kiting_scan_on_empty_qualifying_set_scores_zero_without_division_error
    """
    drawer, _depositor = _two_accounts_joined_by_one_acyclic_edge()

    scan = validate_success(
        api.run_kiting_scan(
            drawer["account_id"],
            {
                "mode": "INCLUSIVE",
                "window_start_at": "2026-06-01T00:00:00Z",
                "window_end_at": "2026-07-01T00:00:00Z",
            },
            analyst_headers,
        )
    )

    assert scan["qualifying_item_count"] == 0, "The only item was deposited outside this window"
    assert scan["deposited_cents"] == 0
    assert scan["uncollected_ratio_bps"] == 0
    assert scan["kiting_score"] == 0
    assert scan["detected"] is False
    assert scan["fraud_case_id"] is None
    assert scan["cycle_length"] == 0
    assert scan["cycle_account_ids"] == []
    assert scan["uncollected_cents"] == 0
