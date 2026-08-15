"""Revenue ingestion, month-end recognition, withholding, and chargebacks."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_revenue_event,
    create_channel,
    create_verified_channel,
    get_channel,
    get_revenue_event,
    ingest_revenue_event,
    make_creator_headers,
    open_payout,
    revenue_event_payload,
    run_ops,
    set_clock,
    setup_channel_with_cleared_events,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]


class TestRevenueEventLedgerShape:
    def test_revenue_event_immutable_no_version_field(self, api):
        """PRD §2.4: "A `RevenueEvent` is an append-only ledger entry: it
        carries only `id` and `created_at` from the common set, its business
        content is immutable once ingested, and it has neither `updated_at`
        nor `version`."
        PRD §3.2: "The `settlement_month` is derived from `occurred_at` as
        its `YYYY-MM` label, and that label drives month-end settlement."

        Design: Corner/entities/revenue_event_immutable_no_version_field
        """
        channel = create_channel(handle="corner_imm", home_platform="YOUTUBE")
        set_clock("2026-08-05T00:00:00Z")

        event = validate_success(api.ingest_revenue_event(
            channel["id"],
            revenue_event_payload(kind="TIP", gross_cents=7777,
                                  platform_fee_bps=500,
                                  occurred_at="2026-08-05T01:00:00Z"),
            ADMIN), 201)
        assert_revenue_event(event)  # enforces: no updated_at, no version
        assert event["recognition_status"] == "PENDING"
        # Provisional net: round_half_up(7777 * (10000 - 500) / 10000) = 7388.
        assert event["net_cents"] == 7388
        assert event["settlement_month"] == "2026-08"


class TestMonthEndRecognition:
    def test_rebate_cliff_boundary_not_crossed_vs_crossed(self, api):
        """PRD §3.2: "When the month gross reaches at least 5,000,000 cents
        (fifty thousand dollars), every event settled in that month enjoys a
        **volume rebate** of 250 basis points, so its effective fee is its
        `platform_fee_bps` reduced by 250; below the cliff the effective fee
        is simply `platform_fee_bps`."

        Design: Corner/calculations/rebate_cliff_boundary_not_crossed_vs_crossed
        """
        channel_a = create_channel(handle="calc_ca", home_platform="TWITCH")
        channel_b = create_channel(handle="calc_cb", home_platform="YOUTUBE")
        set_clock("2026-08-10T00:00:00Z")
        ev_a = ingest_revenue_event(
            channel_a["id"], kind="TIP", gross_cents=4_999_999,
            platform_fee_bps=0, occurred_at="2026-08-10T01:00:00Z")
        ev_b = ingest_revenue_event(
            channel_b["id"], kind="SPONSORSHIP", gross_cents=5_000_000,
            platform_fee_bps=1000, occurred_at="2026-08-10T01:00:00Z")
        assert ev_a["net_cents"] == 4_999_999, "provisional net, no rebate"
        assert ev_b["net_cents"] == 4_500_000, "provisional net at plain fee"

        set_clock("2026-09-01T00:00:00Z")
        run_ops()

        final_a = get_revenue_event(ev_a["id"])
        final_b = get_revenue_event(ev_b["id"])
        assert final_a["recognition_status"] == "CLEARED"
        assert final_b["recognition_status"] == "CLEARED"
        assert final_a["net_cents"] == 4_999_999, (
            "month gross 4,999,999 is below the cliff: final == provisional")
        # 5,000,000 crosses the inclusive cliff: fee 1000 -> 750 bps.
        assert final_b["net_cents"] == 4_625_000, (
            "final net = 5000000 * (10000 - 750) / 10000 with the rebate")

    def test_revenue_provisional_nets_at_ingestion(self, api):
        """PRD §3.2: "**At ingestion** a non-chargeback event is born
        `PENDING` with a *provisional* `net_cents`: the event's
        `platform_fee_bps` is subtracted from ten thousand to obtain the
        creator's share in basis points, `gross_cents` is multiplied by that
        share and divided by ten thousand, and the result is rounded half up
        to whole cents. The provisional figure never applies the volume
        rebate, and the event's net is added to the channel's
        `balance_pending_cents`."

        Design: Difficulty/dual_variant_calc/revenue_provisional_vs_final_rebate_cliff
        """
        channel, _form = create_verified_channel("dv_rev")
        set_clock("2026-08-01T00:00:00Z")
        ev_sub = ingest_revenue_event(
            channel["id"], kind="SUBSCRIPTION", gross_cents=50000,
            platform_fee_bps=4000, occurred_at="2026-08-05T00:00:00Z")
        ev_tip = ingest_revenue_event(
            channel["id"], kind="TIP", gross_cents=10000,
            platform_fee_bps=500, occurred_at="2026-08-06T00:00:00Z")
        ev_spo = ingest_revenue_event(
            channel["id"], kind="SPONSORSHIP", gross_cents=6000000,
            platform_fee_bps=1000, occurred_at="2026-08-07T00:00:00Z")

        assert ev_sub["net_cents"] == 30000 and ev_sub["recognition_status"] == "PENDING"
        assert ev_tip["net_cents"] == 9500
        assert ev_spo["net_cents"] == 5400000
        channel_now = get_channel(channel["id"])
        assert channel_now["balance_pending_cents"] == 5_439_500, (
            "30000 + 9500 + 5400000 provisional nets")
        assert channel_now["balance_payable_cents"] == 0

    def test_revenue_final_nets_after_month_settlement(self, api):
        """PRD §3.2: "When the month gross reaches at least 5,000,000 cents
        (fifty thousand dollars), every event settled in that month enjoys a
        **volume rebate** of 250 basis points, so its effective fee is its
        `platform_fee_bps` reduced by 250; below the cliff the effective fee
        is simply `platform_fee_bps`."
        PRD §3.2: "Settlement moves money between balances in the same breath:
        the provisional net leaves `balance_pending_cents` and the final net
        lands in `balance_payable_cents`."

        Design: Difficulty/dual_variant_calc/revenue_provisional_vs_final_rebate_cliff
        """
        _channel, _form, events = setup_channel_with_cleared_events(
            "dv_rev2",
            [{"kind": "SUBSCRIPTION", "gross_cents": 50000,
              "platform_fee_bps": 4000, "occurred_at": "2026-08-05T00:00:00Z"},
             {"kind": "TIP", "gross_cents": 10000,
              "platform_fee_bps": 500, "occurred_at": "2026-08-06T00:00:00Z"},
             {"kind": "SPONSORSHIP", "gross_cents": 6000000,
              "platform_fee_bps": 1000, "occurred_at": "2026-08-07T00:00:00Z"}],
            ingest_clock="2026-08-01T00:00:00Z")
        ev_sub, ev_tip, ev_spo = events

        # Month gross 6,060,000 crosses the cliff: every fee drops 250 bps.
        assert get_revenue_event(ev_sub["id"])["net_cents"] == 31250
        assert get_revenue_event(ev_tip["id"])["net_cents"] == 9750
        assert get_revenue_event(ev_spo["id"])["net_cents"] == 5_550_000
        channel_after = get_channel(_channel["id"])
        assert channel_after["balance_payable_cents"] == 5_591_000, (
            "final sum 31250 + 9750 + 5550000, not the provisional 5439500")
        assert channel_after["balance_pending_cents"] == 0


class TestPayoutWithholdingAndFee:
    def _w8_channel_with_standard_events(self, handle):
        """W8BEN-verified channel with the three standard August events
        settled CLEARED (final nets 31250 / 9750 / 5550000)."""
        channel, _form, _events = setup_channel_with_cleared_events(
            handle,
            [{"kind": "SUBSCRIPTION", "gross_cents": 50000,
              "platform_fee_bps": 4000, "occurred_at": "2026-08-05T00:00:00Z"},
             {"kind": "TIP", "gross_cents": 10000,
              "platform_fee_bps": 500, "occurred_at": "2026-08-06T00:00:00Z"},
             {"kind": "SPONSORSHIP", "gross_cents": 6000000,
              "platform_fee_bps": 1000, "occurred_at": "2026-08-07T00:00:00Z"}],
            form_type="W8BEN", ingest_clock="2026-08-01T00:00:00Z")
        return channel

    def test_payout_withholding_w8_per_event_amounts(self, api):
        """PRD §3.3: "First, withholding is computed over the swept events:
        when the channel's current tax form's `form_type` is `W8BEN` or
        `W8BENE`, each swept event contributes thirty percent — 3,000 basis
        points — of its `net_cents`, rounded half up to whole cents *per
        event*; for a `W9` channel every event contributes zero."
        PRD §3.3: "Second, the **snapshot** is taken: the channel's
        `balance_payable_cents` minus the payout's `withholding_cents`."

        Design: Difficulty/dual_variant_calc/payout_fee_tier_provisional_vs_final_context
        """
        channel = self._w8_channel_with_standard_events("dv_w8")
        payout = open_payout(channel["id"])

        assert payout["withholding_cents"] == 1_677_300, (
            "9375 + 2925 + 1665000, each event rounded before the sum")
        assert payout["amount_cents"] == 3_913_700, (
            "snapshot = 5591000 payable - 1677300 withholding")
        assert payout["settled_event_count"] == 3

    def test_payout_fee_and_net_transfer_w8(self, api):
        """PRD §3.3: "Third, the transfer-fee tier is selected on that pre-fee
        snapshot — never on the post-fee remainder: a snapshot of at least
        1,000,000 cents (ten thousand dollars) is charged 25 basis points, a
        snapshot of at least 100,000 cents (one thousand dollars) is charged
        50 basis points, and anything smaller is charged 100 basis points.
        Fourth, `amount_cents` is set equal to the snapshot, `fee_cents` is
        the snapshot multiplied by the tier's basis points and divided by ten
        thousand with round-half-up to whole cents, and `net_transfer_cents`
        is `amount_cents` minus `fee_cents`."

        Design: Difficulty/dual_variant_calc/payout_fee_tier_provisional_vs_final_context
        """
        channel = self._w8_channel_with_standard_events("dv_w8b")
        payout = open_payout(channel["id"])

        assert payout["fee_cents"] == 9784, (
            "snapshot 3913700 >= 1000000 selects 25bps; "
            "round_half_up(3913700 * 25 / 10000) = round_half_up(9784.25)")
        assert payout["net_transfer_cents"] == 3_903_916

    def test_withholding_rounded_per_event_then_summed(self, api):
        """PRD §2.6: "Where a rule aggregates a per-event figure, the rounding
        order is pinned: each event's figure is rounded first, and the rounded
        figures are then summed. The alternative order — summing raw figures
        and rounding once — can differ by cents and is never used."
        PRD §3.3: "The payout's `withholding_cents` is the sum of those
        per-event amounts, and per §2.6 the per-event rounding happens before
        the summation."

        Design: Difficulty/combinatorial_formula/withholding_round_per_event_then_sum
        """
        channel, _form, _events = setup_channel_with_cleared_events(
            "cf_round",
            [{"kind": "TIP", "gross_cents": 1111, "platform_fee_bps": 0,
              "occurred_at": "2026-08-10T01:00:00Z"},
             {"kind": "TIP", "gross_cents": 1111, "platform_fee_bps": 0,
              "occurred_at": "2026-08-10T02:00:00Z"},
             {"kind": "TIP", "gross_cents": 1111, "platform_fee_bps": 0,
              "occurred_at": "2026-08-10T03:00:00Z"}],
            form_type="W8BEN", payout_threshold_cents=1000,
            ingest_clock="2026-08-10T00:00:00Z")
        payout = open_payout(channel["id"])

        assert payout["withholding_cents"] == 999, (
            "3 x round_half_up(1111 * 0.30) = 3 x 333; "
            "sum-then-round would give 1000")
        assert payout["amount_cents"] == 2334, "3333 cleared net - 999 withheld"

    def test_withholding_fee_and_net_after_per_event_rounding(self, api):
        """PRD §2.6: "Where a rule aggregates a per-event figure, the rounding
        order is pinned: each event's figure is rounded first, and the rounded
        figures are then summed. The alternative order — summing raw figures
        and rounding once — can differ by cents and is never used."
        PRD §3.3: "a snapshot of at least 1,000,000 cents (ten thousand
        dollars) is charged 25 basis points, a snapshot of at least 100,000
        cents (one thousand dollars) is charged 50 basis points, and anything
        smaller is charged 100 basis points."

        Design: Difficulty/combinatorial_formula/withholding_round_per_event_then_sum
        """
        channel, _form, _events = setup_channel_with_cleared_events(
            "cf_round2",
            [{"kind": "TIP", "gross_cents": 1111, "platform_fee_bps": 0,
              "occurred_at": "2026-08-10T01:00:00Z"},
             {"kind": "TIP", "gross_cents": 1111, "platform_fee_bps": 0,
              "occurred_at": "2026-08-10T02:00:00Z"},
             {"kind": "TIP", "gross_cents": 1111, "platform_fee_bps": 0,
              "occurred_at": "2026-08-10T03:00:00Z"}],
            form_type="W8BEN", payout_threshold_cents=1000,
            ingest_clock="2026-08-10T00:00:00Z")
        payout = open_payout(channel["id"])

        assert payout["fee_cents"] == 23, (
            "snapshot 2334 < 100000 selects 100bps; round_half_up(23.34)")
        assert payout["net_transfer_cents"] == 2311, "2334 - 23"

    def test_fee_tier_keyed_on_prefee_snapshot_amount(self, api):
        """PRD §3.3: "Third, the transfer-fee tier is selected on that pre-fee
        snapshot — never on the post-fee remainder: a snapshot of at least
        1,000,000 cents (ten thousand dollars) is charged 25 basis points, a
        snapshot of at least 100,000 cents (one thousand dollars) is charged
        50 basis points, and anything smaller is charged 100 basis points."

        Design: Difficulty/combinatorial_formula/payout_fee_tier_evaluation_order
        """
        channel = self._w8_channel_with_standard_events("cf_order")
        payout = open_payout(channel["id"])

        assert payout["amount_cents"] == 3_913_700, (
            "amount_cents is set equal to the pre-fee post-withholding "
            "snapshot")
        assert payout["fee_cents"] == 9784, (
            "25bps selected on the 3913700 snapshot, not on the post-fee "
            "remainder")

    def test_fee_tier_evaluation_order_pins_net_transfer(self, api):
        """PRD §3.3: "Opening a payout performs a fixed sequence of
        computations, and the order is pinned to remove any circularity."
        PRD §3.3: "Fourth, `amount_cents` is set equal to the snapshot,
        `fee_cents` is the snapshot multiplied by the tier's basis points and
        divided by ten thousand with round-half-up to whole cents, and
        `net_transfer_cents` is `amount_cents` minus `fee_cents`."

        Design: Difficulty/combinatorial_formula/payout_fee_tier_evaluation_order
        """
        channel = self._w8_channel_with_standard_events("cf_order2")
        payout = open_payout(channel["id"])

        assert payout["fee_cents"] == 9784
        assert payout["net_transfer_cents"] == 3_903_916, (
            "3913700 - 9784; the pinned order makes the fee tier independent "
            "of the post-fee remainder")


class TestChargebacks:
    def test_chargeback_reversal_math(self, api):
        """PRD §3.2: "A valid reversal flips the original from `CLEARED` to
        `REVERSED` — a terminal state — and creates a new `CHARGEBACK` event
        whose `gross_cents` is the negation of the original's gross, whose
        `recognition_status` is `CLEARED`, and whose `reverses_event_id` names
        the original. The original's net leaves the channel's
        `balance_payable_cents`, which the subtraction may legitimately drive
        negative."

        Design: Corner/calculations/chargeback_reversal_math
        """
        channel, _form, events = setup_channel_with_cleared_events(
            "calc_cb2",
            [{"kind": "TIP", "gross_cents": 10000, "platform_fee_bps": 500,
              "occurred_at": "2026-08-05T01:00:00Z"}],
            ingest_clock="2026-08-05T00:00:00Z")
        original = events[0]
        assert get_channel(channel["id"])["balance_payable_cents"] == 9500

        chargeback = validate_success(api.reverse_revenue_event(
            original["id"], {"reason": "chargeback"}, ADMIN), 201)
        assert_revenue_event(chargeback)
        assert chargeback["kind"] == "CHARGEBACK"
        assert chargeback["gross_cents"] == -10000
        assert chargeback["recognition_status"] == "CLEARED"
        assert chargeback["reverses_event_id"] == original["id"]

        assert get_revenue_event(original["id"])["recognition_status"] == "REVERSED"
        # NOTE: the exact post-reversal `balance_payable_cents` is NOT
        # asserted. PRD §3.2 says "The original's net leaves the channel's
        # `balance_payable_cents`" (=> 0), while PRD §2.6 defines
        # `balance_payable_cents` as "the sum of final net over the channel's
        # `CLEARED` events — with `CHARGEBACK` nets contributing negative
        # amounts" (=> -9500 once the original is REVERSED and only the
        # chargeback remains CLEARED; the reversal paragraph also never pins
        # the chargeback's platform_fee_bps, making even that value
        # non-unique). Two faithful PRD-only readings diverge, so the value
        # is not uniquely derivable and the assertion was removed.

    def test_reverse_pending_event_rejected(self, api):
        """PRD §3.2: "Reversal of an ordinary event is a `PlatformAdmin`
        capability with a `reason` recorded on the request, and it is guarded
        by three conditions, all enforced with `ERR_CHARGEABILITY_VIOLATION`
        (HTTP 409): the target's `kind` must not be `CHARGEBACK`, its
        `recognition_status` must be `CLEARED`, and no existing `CHARGEBACK`
        event may already point at it through `reverses_event_id`."

        Design: Corner/errors/reverse_pending_event_rejected
        """
        channel, _form, events = setup_channel_with_cleared_events(
            "err_rev",
            [{"kind": "TIP", "gross_cents": 10000, "platform_fee_bps": 500,
              "occurred_at": "2026-08-05T01:00:00Z"}],
            ingest_clock="2026-08-05T00:00:00Z")
        chargeback = validate_success(api.reverse_revenue_event(
            events[0]["id"], {"reason": "cb"}, ADMIN), 201)
        pending = ingest_revenue_event(
            channel["id"], kind="TIP", gross_cents=5000, platform_fee_bps=500,
            occurred_at="2026-09-01T01:00:00Z")
        assert pending["recognition_status"] == "PENDING"

        resp_pending = api.reverse_revenue_event(
            pending["id"], {"reason": "too early"}, ADMIN)
        validate_error(resp_pending, ApiErrorId.ERR_CHARGEABILITY_VIOLATION)

        resp_chargeback = api.reverse_revenue_event(
            chargeback["id"], {"reason": "reverse the reversal"}, ADMIN)
        validate_error(resp_chargeback, ApiErrorId.ERR_CHARGEABILITY_VIOLATION)


class TestIngestionRbacAndOpsSummary:
    def test_creator_cannot_ingest_revenue_rejected(self, api):
        """PRD §2.1: "A caller whose role is not listed on the endpoint — or,
        on the transition-style endpoints, whose role is not permitted for the
        specific `action` requested — is rejected with `ERR_UNAUTHORIZED`
        (HTTP 403)."
        PRD §4: revenue ingestion is listed with authorized role
        PlatformAdmin only.

        Design: Corner/rbac/creator_cannot_ingest_revenue_rejected
        """
        channel = create_channel(handle="rb_ing", home_platform="YOUTUBE")
        resp = api.ingest_revenue_event(
            channel["id"],
            revenue_event_payload(kind="TIP", gross_cents=1000,
                                  platform_fee_bps=0,
                                  occurred_at="2026-08-01T01:00:00Z"),
            make_creator_headers(channel["id"]))
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)

        events, meta = validate_paginated(
            api.list_revenue_events(ADMIN, params={"channel_id": channel["id"]}))
        assert meta["total_count"] == 0, "no event may be persisted"

    def test_ops_run_summary_output_shape(self, api):
        """PRD §2.5: "A run also increments `ops_run_index`, which starts at
        0, and its response reports the counters `ops_run_index`,
        `events_cleared`, `strikes_expired`, `tax_forms_expired`,
        `grants_expired`, `streams_no_show`, `deliverables_missed`,
        `perks_expired`, `subscriptions_renewed`, `subscriptions_expired`,
        `deals_completed`, and `payouts_released` — the last of these counting
        held payouts released back to `SCHEDULED` by the posture
        recomputations the run triggered."

        Design: Corner/endpoints/ops_run_summary_output_shape
        """
        channel = create_channel(handle="ep_ops", home_platform="YOUTUBE")
        set_clock("2026-08-05T00:00:00Z")
        ingest_revenue_event(channel["id"], kind="TIP", gross_cents=5000,
                             platform_fee_bps=500,
                             occurred_at="2026-08-05T01:00:00Z")
        set_clock("2026-09-01T00:00:00Z")

        summary = validate_success(api.ops_run(ADMIN), 200)
        assert summary["ops_run_index"] == 1, "first run increments from 0"
        assert summary["events_cleared"] == 1
        for counter in ("strikes_expired", "tax_forms_expired", "grants_expired",
                        "streams_no_show", "deliverables_missed", "perks_expired",
                        "subscriptions_renewed", "subscriptions_expired",
                        "deals_completed", "payouts_released"):
            assert summary[counter] == 0, f"{counter} must be 0 for this run"

        assert get_channel(channel["id"])["balance_payable_cents"] == 4750, (
            "5000 * (10000 - 500) / 10000, no rebate below the cliff")
