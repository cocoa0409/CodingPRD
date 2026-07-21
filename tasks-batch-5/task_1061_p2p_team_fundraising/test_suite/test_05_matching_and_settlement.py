"""Sponsor matching, settlement credit, receipts and the two gift dimensions."""

from test_helpers import (
    ApiErrorId,
    assert_pool_cents_conserved,
    assert_receipt,
    assert_receipt_number_format,
    create_donor,
    create_gift,
    create_match_pool,
    create_match_pool_payload,
    create_settled_gift,
    make_platform_admin_headers,
    receipt_for_gift,
    set_clock,
    settle_gift,
    setup_participant_at_credit,
    setup_participant_at_credit_with_match,
    setup_published_campaign,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_a_gift_settles_while_its_match_dimension_lands_not_eligible(api):
    """PRD §3.5: "A pool is a candidate when all four of these hold: its status is
    `ACTIVE`; the current logical-clock instant is at or after its `starts_at` and
    strictly before its `ends_at`; its `remaining_cents` is greater than 0; and the
    gift's `amount_cents` is greater than or equal to the pool's `min_donation_cents`."
    PRD §3.5: "If the candidate set was empty, or the computed match came out below 1
    cent, the match dimension moves `UNMATCHED → NOT_ELIGIBLE`, `matched_amount_cents`
    stays 0 and no pool is attached — this is not an error and no rejection is raised."

    Design: Difficulty/non_linear_state_machine/donation_payment_and_match_dimensions_evolve_independently
    """
    ctx = setup_published_campaign(api=api)
    create_match_pool(
        ctx["campaign_id"], ctx["cm_headers"], api=api,
        pool_amount_cents=50000, match_ratio=0.5, per_donation_cap_cents=5000,
        min_donation_cents=2500,
    )
    donor = create_donor(api=api)
    gift = create_gift(
        ctx["campaign_id"], donor["id"], "CAMPAIGN", ctx["campaign_id"], 2000, api=api
    )

    settled = validate_success(
        api.settle_donation(gift["id"], {"outcome": "SETTLED"}, _admin())
    )

    assert settled["payment_status"] == "SETTLED"
    assert settled["match_status"] == "NOT_ELIGIBLE", "Below the pool's minimum"
    assert settled["matched_amount_cents"] == 0
    assert settled["match_pool_id"] is None


def test_the_untouched_pool_keeps_its_full_balance_after_that_settlement(api):
    """PRD §3.4: "These two dimensions are genuinely independent: `payment_status`
    walks `PENDING`, `SETTLED`, `REFUNDED`, `FAILED` while `match_status` walks
    `UNMATCHED`, `MATCHED`, `NOT_ELIGIBLE`, `REVERSED` on the same row."
    PRD §2.11: "A sponsor pool's `remaining_cents` is its `pool_amount_cents` less its
    `allocated_cents`, and never goes below zero."

    Design: Difficulty/non_linear_state_machine/donation_payment_and_match_dimensions_evolve_independently
    """
    ctx = setup_published_campaign(api=api)
    pool = create_match_pool(
        ctx["campaign_id"], ctx["cm_headers"], api=api,
        pool_amount_cents=50000, match_ratio=0.5, per_donation_cap_cents=5000,
        min_donation_cents=2500,
    )
    donor = create_donor(api=api)
    gift = create_gift(
        ctx["campaign_id"], donor["id"], "CAMPAIGN", ctx["campaign_id"], 2000, api=api
    )
    settle_gift(gift["id"], api=api)

    refreshed = validate_success(api.get_match_pool(pool["id"], ctx["cm_headers"]))

    assert refreshed["remaining_cents"] == 50000
    assert refreshed["status"] == "ACTIVE"
    assert_pool_cents_conserved(refreshed)


def test_final_credit_counts_only_the_settled_gift(api, anonymous_headers):
    """PRD §3.6: "A fundraiser's `credited_cents` is the sum, across gifts whose
    `designation_type` is `PARTICIPANT`, whose `designation_id` names that fundraiser,
    and whose payment dimension reads `SETTLED`, of the gift's `amount_cents` added to
    its `matched_amount_cents`."

    Design: Difficulty/dual_variant_calc/participant_credit_final_vs_provisional_diverge
    """
    ctx = setup_participant_at_credit(10000, api=api, fundraising_minimum_cents=15000)
    create_gift(
        ctx["campaign_id"], ctx["donor_id"], "PARTICIPANT", ctx["participant_id"],
        6000, api=api,
    )

    page = validate_success(api.get_participant(ctx["participant_id"], anonymous_headers))

    assert page["credited_cents"] == 10000, "The pending 6000-cent gift is excluded"
    assert page["minimum_met"] is False


def test_projected_credit_also_counts_the_pending_gift(api, anonymous_headers):
    """PRD §3.6: "`projected_cents` is computed the same way but over gifts whose
    payment dimension is `PENDING` **or** `SETTLED`."
    PRD §3.6: "On identical data, `projected_cents` therefore exceeds `credited_cents`
    whenever any pending gift is outstanding."

    Design: Difficulty/dual_variant_calc/participant_credit_final_vs_provisional_diverge
    """
    ctx = setup_participant_at_credit(10000, api=api, fundraising_minimum_cents=15000)
    create_gift(
        ctx["campaign_id"], ctx["donor_id"], "PARTICIPANT", ctx["participant_id"],
        6000, api=api,
    )

    page = validate_success(api.get_participant(ctx["participant_id"], anonymous_headers))

    assert page["projected_cents"] == 16000, "10000 settled plus 6000 pending, no pool"
    assert page["projected_cents"] > page["credited_cents"]


def test_a_pool_starting_where_another_ends_is_accepted(api):
    """PRD §3.5: "Because the windows are half-open, a pool that begins at exactly the
    instant another pool ends is accepted."
    PRD §3.5: "The window is **half-open**: the start instant is inclusive and the end
    instant is exclusive, and the end must be strictly after the start."

    Design: Difficulty/resource_temporal_overlap/match_pool_half_open_window_adjacent_ok_overlap_rejected
    """
    ctx = setup_published_campaign(api=api)
    first = create_match_pool(
        ctx["campaign_id"], ctx["cm_headers"], api=api,
        starts_at="2026-07-01T00:00:00Z", ends_at="2026-08-01T00:00:00Z",
    )

    response = api.create_match_pool(
        create_match_pool_payload(
            ctx["campaign_id"], sponsor_name="Harbor Mutual", pool_amount_cents=20000,
            match_ratio=1.0, per_donation_cap_cents=4000,
            starts_at="2026-08-01T00:00:00Z", ends_at="2026-09-01T00:00:00Z",
        ),
        ctx["cm_headers"],
    )

    adjacent = validate_success(response, expected_status=201)
    assert adjacent["status"] == "ACTIVE"
    assert adjacent["starts_at"][:19] == first["ends_at"][:19], (
        "The adjacent pool begins exactly where the first one ends"
    )


def test_a_pool_overlapping_a_live_window_is_rejected(api):
    """PRD §3.5: "A new pool whose half-open window overlaps that of any existing pool
    of the campaign in `ACTIVE` or `EXHAUSTED` is rejected with
    `ERR_MATCH_WINDOW_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/match_pool_half_open_window_adjacent_ok_overlap_rejected
    """
    ctx = setup_published_campaign(api=api)
    create_match_pool(
        ctx["campaign_id"], ctx["cm_headers"], api=api,
        starts_at="2026-07-01T00:00:00Z", ends_at="2026-08-01T00:00:00Z",
    )
    create_match_pool(
        ctx["campaign_id"], ctx["cm_headers"], api=api, sponsor_name="Harbor Mutual",
        pool_amount_cents=20000, match_ratio=1.0, per_donation_cap_cents=4000,
        starts_at="2026-08-01T00:00:00Z", ends_at="2026-09-01T00:00:00Z",
    )

    response = api.create_match_pool(
        create_match_pool_payload(
            ctx["campaign_id"], sponsor_name="Cedar Trust", pool_amount_cents=30000,
            match_ratio=0.5, per_donation_cap_cents=3000,
            starts_at="2026-07-15T00:00:00Z", ends_at="2026-08-15T00:00:00Z",
        ),
        ctx["cm_headers"],
    )

    validate_error(
        response, ApiErrorId.ERR_MATCH_WINDOW_OVERLAP.value, expected_status=409
    )
    _rows, meta = validate_paginated(
        api.list_match_pools(ctx["cm_headers"], params={"campaign_id": ctx["campaign_id"]})
    )
    assert meta["total_count"] == 2, "The rejected pool must not be persisted"


def test_matching_skips_the_pool_whose_window_has_just_closed(api):
    """PRD §3.5: "A pool is a candidate when all four of these hold: its status is
    `ACTIVE`; the current logical-clock instant is at or after its `starts_at` and
    strictly before its `ends_at`; its `remaining_cents` is greater than 0; and the
    gift's `amount_cents` is greater than or equal to the pool's `min_donation_cents`."

    Design: Corner/calculations/match_allocation_input_set_excludes_expired_window_pool
    """
    ctx = setup_published_campaign(api=api)
    expired = create_match_pool(
        ctx["campaign_id"], ctx["cm_headers"], api=api, match_ratio=0.5,
        starts_at="2026-07-01T00:00:00Z", ends_at="2026-08-01T00:00:00Z",
    )
    live = create_match_pool(
        ctx["campaign_id"], ctx["cm_headers"], api=api, sponsor_name="Harbor Mutual",
        match_ratio=0.2, starts_at="2026-08-01T00:00:00Z", ends_at="2026-09-01T00:00:00Z",
    )
    donor = create_donor(api=api)
    gift = create_gift(
        ctx["campaign_id"], donor["id"], "CAMPAIGN", ctx["campaign_id"], 10000, api=api
    )
    set_clock("2026-08-01T00:00:00Z", api=api)

    settled = validate_success(
        api.settle_donation(gift["id"], {"outcome": "SETTLED"}, _admin())
    )

    assert settled["match_pool_id"] == live["id"], "Only the open window is a candidate"
    assert settled["matched_amount_cents"] == 2000, "10000 at ratio 0.2"
    untouched = validate_success(api.get_match_pool(expired["id"], ctx["cm_headers"]))
    assert untouched["remaining_cents"] == 50000
    drawn = validate_success(api.get_match_pool(live["id"], ctx["cm_headers"]))
    assert drawn["remaining_cents"] == 48000
    assert drawn["allocated_cents"] == 2000


def test_the_per_gift_cap_binds_the_three_way_minimum(api, anonymous_headers):
    """PRD §3.5: "The stored `matched_amount_cents` is then the smallest of three
    figures: that rounded raw match, the pool's `per_donation_cap_cents`, and the
    pool's `remaining_cents`."

    Design: Corner/calculations/match_allocation_capped_by_per_donation_cap
    """
    ctx = setup_participant_at_credit_with_match(
        api=api, fundraising_minimum_cents=0, gift_cents=10000,
        pool_amount_cents=50000, match_ratio=1.0, per_donation_cap_cents=4000,
        with_event=False,
    )

    gift = validate_success(api.get_donation(ctx["donation_id"], anonymous_headers))

    assert gift["matched_amount_cents"] == 4000, "Raw 10000 truncated to the 4000 cap"
    assert gift["match_status"] == "MATCHED"
    pool = validate_success(api.get_match_pool(ctx["pool_id"], ctx["cm_headers"]))
    assert pool["remaining_cents"] == 46000
    page = validate_success(api.get_participant(ctx["participant_id"], anonymous_headers))
    assert page["credited_cents"] == 14000


def test_a_settled_gift_mints_a_receipt_net_of_the_benefit_value(api):
    """PRD §3.6: "The receipt records the `donation_id` it documents and the
    `campaign_id` it belongs to, carries a `deductible_amount_cents` equal to the
    gift's `amount_cents` reduced by its `benefit_value_cents` and floored at 0 (never
    negative), and a `tax_year` equal to the UTC calendar year of the gift's
    `settled_at`."
    PRD §3.6: "the first receipt of a campaign is therefore `RCPT-000001`"

    Design: Corner/calculations/receipt_deductible_amount_subtracts_benefit_value
    """
    ctx = setup_published_campaign(api=api)
    donor = create_donor(api=api)
    gift = create_settled_gift(
        ctx["campaign_id"], donor["id"], "CAMPAIGN", ctx["campaign_id"], 10000,
        api=api, benefit_value_cents=2500,
    )

    rows, meta = validate_paginated(
        api.list_receipts(ctx["cm_headers"], params={"donation_id": gift["id"]})
    )

    assert meta["total_count"] == 1
    receipt = rows[0]
    assert_receipt(receipt)
    assert receipt["deductible_amount_cents"] == 7500, "10000 less a 2500 benefit"
    assert receipt["tax_year"] == 2026
    assert_receipt_number_format(receipt["receipt_number"], 1)
    assert receipt["status"] == "ISSUED"


def test_settling_an_already_settled_gift_is_rejected(api):
    """PRD §3.6: "Either way the gift must still be `PENDING` in its payment
    dimension; anything else is rejected with `ERR_INVALID_STATE`."
    PRD §3.6: "The gift's campaign holds a per-campaign counter, `receipt_seq`, which
    begins at 0 and is increased by exactly 1 for each settlement."

    Design: Corner/state_machines/donation_settle_twice_rejected_idempotency_guard
    """
    ctx = setup_published_campaign(api=api)
    donor = create_donor(api=api)
    gift = create_settled_gift(
        ctx["campaign_id"], donor["id"], "CAMPAIGN", ctx["campaign_id"], 10000, api=api
    )

    response = api.settle_donation(gift["id"], {"outcome": "SETTLED"}, _admin())

    validate_error(response, ApiErrorId.ERR_INVALID_STATE.value, expected_status=409)
    _rows, meta = validate_paginated(
        api.list_receipts(ctx["cm_headers"], params={"donation_id": gift["id"]})
    )
    assert meta["total_count"] == 1, "No second receipt may be minted"
    campaign = validate_success(api.get_campaign(ctx["campaign_id"], ctx["cm_headers"]))
    assert campaign["receipt_seq"] == 1


def test_a_reissued_receipt_keeps_its_original_number(api):
    """PRD §3.6: "A voided receipt may be re-issued, moving it `VOIDED → ISSUED`,
    provided the underlying gift's payment dimension still reads `SETTLED`; a reissue
    increases `reissue_count` by 1, refreshes `issued_at`, clears `voided_at`, and
    keeps the **original** `receipt_number` unchanged."

    Design: Corner/state_machines/receipt_void_then_reissue_keeps_receipt_number_and_bumps_reissue_count
    """
    ctx = setup_published_campaign(api=api)
    donor = create_donor(api=api)
    gift = create_settled_gift(
        ctx["campaign_id"], donor["id"], "CAMPAIGN", ctx["campaign_id"], 10000, api=api
    )
    receipt = receipt_for_gift(gift["id"], ctx["cm_headers"], api=api)
    original_number = receipt["receipt_number"]
    assert_receipt_number_format(original_number, 1)

    voided = validate_success(api.void_receipt(receipt["id"], ctx["cm_headers"]))
    assert voided["status"] == "VOIDED"
    reissued = validate_success(api.reissue_receipt(receipt["id"], ctx["cm_headers"]))

    assert reissued["status"] == "ISSUED"
    assert reissued["reissue_count"] == 1
    assert reissued["voided_at"] is None
    assert reissued["receipt_number"] == original_number
    assert reissued["deductible_amount_cents"] == 10000


def test_the_read_after_settlement_already_shows_credit_and_receipt(api, anonymous_headers):
    """PRD §3.6: "Third, the credited totals of the designation target are recomputed:
    the designated fundraiser's `credited_cents`, the relevant team's `credited_cents`,
    and the campaign's `raised_credited_cents`."
    PRD §3.8: "Progress is reported in basis points: `percent_bp` is the credited total
    multiplied by 10000, divided by the campaign's `goal_amount_cents`, and floored to
    a whole number; the reported value is then capped at 20000 basis points, so a
    campaign at triple its goal still displays 20000."

    Design: Corner/consistency_model/settle_response_immediately_reflects_credit_and_receipt
    """
    ctx = setup_participant_at_credit_with_match(
        api=api, fundraising_minimum_cents=0, with_event=False
    )

    assert ctx["donation"]["matched_amount_cents"] == 5000, (
        "The settle response itself carries the applied match"
    )
    page = validate_success(api.get_participant(ctx["participant_id"], anonymous_headers))
    assert page["credited_cents"] == 15000
    thermometer = validate_success(
        api.get_thermometer(ctx["campaign_id"], anonymous_headers)
    )
    assert thermometer["raised_credited_cents"] == 15000
    assert thermometer["percent_bp"] == 150
    assert thermometer["donor_count"] == 1
    receipt = receipt_for_gift(ctx["donation_id"], ctx["cm_headers"], api=api)
    assert receipt["status"] == "ISSUED"


def test_gifts_can_be_listed_by_the_pool_that_funded_them(api):
    """PRD §3.5: "If the result is at least 1 cent, the gift's `match_pool_id` is set
    to the chosen pool and its match dimension moves `UNMATCHED → MATCHED`; the pool's
    `allocated_cents` rises by the matched amount and its `remaining_cents` becomes
    `pool_amount_cents` less `allocated_cents`; and if `remaining_cents` has reached
    exactly 0 the pool transitions `ACTIVE → EXHAUSTED` and leaves the candidate set."
    PRD §3.5: "A closed pool permanently leaves the candidate set and its
    `remaining_cents` is frozen at its current value."

    Design: Corner/endpoints/donations_filtered_list_by_match_pool_id
    """
    ctx = setup_published_campaign(api=api)
    pool = create_match_pool(ctx["campaign_id"], ctx["cm_headers"], api=api)
    donor = create_donor(api=api)
    matched = create_settled_gift(
        ctx["campaign_id"], donor["id"], "CAMPAIGN", ctx["campaign_id"], 10000, api=api
    )
    validate_success(api.close_match_pool(pool["id"], ctx["cm_headers"]))
    unmatched = create_settled_gift(
        ctx["campaign_id"], donor["id"], "CAMPAIGN", ctx["campaign_id"], 2000, api=api
    )

    rows, meta = validate_paginated(
        api.list_donations(ctx["cm_headers"], params={"match_pool_id": pool["id"]})
    )

    assert meta["total_count"] == 1
    assert rows[0]["id"] == matched["id"]
    assert rows[0]["matched_amount_cents"] == 5000
    assert unmatched["match_status"] == "NOT_ELIGIBLE"
    closed = validate_success(api.get_match_pool(pool["id"], ctx["cm_headers"]))
    assert closed["status"] == "CLOSED"


def _admin():
    """Headers for the platform operator, whose id is opaque."""
    return make_platform_admin_headers()
