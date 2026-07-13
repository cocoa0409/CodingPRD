"""A/B variant allocation, the winner sample gate and winner ranking."""
from test_helpers import (
    PLATFORM,
    ApiErrorId,
    click_send,
    deliver,
    open_send,
    read_campaign,
    read_send,
    setup_ab_sent_campaign,
    setup_dispatched_campaign,
    setup_sent_campaign,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestVariantAllocation:
    def test_variant_split_uses_floor_over_the_snapshot_order(self, api):
        """PRD §3.7: "When `ab_test_enabled` is true, `variant_label` is assigned over the snapshot
        order: multiply the recipient count by `variant_split_pct`, divide by 100, discard any
        fraction, and the first that many positions take label `A` while every remaining position
        takes label `B`. When the campaign is not an A/B test, `variant_label` is null on every
        send."
        PRD §3.6: "Sort what remains by `created_at` ascending, breaking ties by `email` ascending —
        the subscriber's `id` never participates in the ordering — and store the resulting ids, in
        that order, into `recipient_snapshot_ids`."

        Design: Corner/calculations/ab_split_allocation_uses_floor_over_created_at_order
        """
        env = setup_dispatched_campaign(
            num_subscribers=5,
            ab_test_enabled=True,
            variant_split_pct=50,
            variant_b_subject="B",
            name="AB",
        )
        assert len(env.sends) == 5

        label_a, _ = validate_paginated(
            api.list_sends(PLATFORM, {"campaign_id": env.campaign_id, "variant_label": "A"})
        )
        label_b, _ = validate_paginated(
            api.list_sends(PLATFORM, {"campaign_id": env.campaign_id, "variant_label": "B"})
        )
        assert len(label_a) == 2, "floor(5 * 50 / 100) == 2 — floor, not round"
        assert len(label_b) == 3

        labels = [s["variant_label"] for s in env.sends]
        assert labels == ["A", "A", "B", "B", "B"], "the first a_count snapshot positions take A"


class TestWinnerSampleGate:
    def test_winner_selection_is_refused_when_nothing_was_ever_opened(self, api):
        """PRD §3.9: "The sample gate then demands at least 2 delivered sends for label `A`, at
        least 2 for label `B`, and at least 1 open across the two labels combined; a campaign that
        fails any part of that gate is refused with `ERR_INSUFFICIENT_AB_SAMPLE` and no winner is
        recorded."

        Design: Difficulty/boundary_precision_check/ab_winner_zero_total_opens_sample_gate
        """
        env = setup_ab_sent_campaign(num_subscribers=4, variant_split_pct=50)
        assert read_campaign(env.campaign_id)["status"] == "SENT"

        resp = api.select_winner(env.campaign_id, env.tenant.author_headers)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_AB_SAMPLE.value)

    def test_a_failed_sample_gate_records_no_winner(self, api):
        """PRD §3.9: "The sample gate then demands at least 2 delivered sends for label `A`, at
        least 2 for label `B`, and at least 1 open across the two labels combined; a campaign that
        fails any part of that gate is refused with `ERR_INSUFFICIENT_AB_SAMPLE` and no winner is
        recorded."
        PRD §3.7: "When `ab_test_enabled` is true, `variant_label` is assigned over the snapshot
        order: multiply the recipient count by `variant_split_pct`, divide by 100, discard any
        fraction, and the first that many positions take label `A` while every remaining position
        takes label `B`. When the campaign is not an A/B test, `variant_label` is null on every
        send."

        Design: Difficulty/boundary_precision_check/ab_winner_zero_total_opens_sample_gate
        """
        env = setup_ab_sent_campaign(num_subscribers=4, variant_split_pct=50)

        validate_error(
            api.select_winner(env.campaign_id, env.tenant.author_headers),
            ApiErrorId.ERR_INSUFFICIENT_AB_SAMPLE.value,
        )

        after = read_campaign(env.campaign_id)
        assert after["status"] == "SENT"
        assert after["winning_variant"] is None
        assert after["winner_selected_at"] is None

        # Both variants cleared the per-variant floor of 2 delivered sends; only the
        # combined-opens clause failed.
        assert read_send(env.send_ids[0])["variant_label"] == "A"
        assert read_send(env.send_ids[1])["variant_label"] == "A"
        assert read_send(env.send_ids[2])["variant_label"] == "B"
        assert read_send(env.send_ids[3])["variant_label"] == "B"

    def test_select_winner_on_a_non_ab_campaign_is_refused(self, api):
        """PRD §3.9: "Once an A/B campaign has reached `SENT`, its author asks the system to name
        the winner. The campaign must be `SENT` and must not already carry a `winning_variant` —
        otherwise the request is refused with `ERR_INVALID_STATE` — and its `ab_test_enabled` must
        be true, or the request is refused with `ERR_AB_NOT_ENABLED`."

        Design: Corner/validations/select_winner_on_non_ab_campaign_rejected
        """
        env = setup_sent_campaign(num_subscribers=1)
        open_send(env.send_ids[0])

        resp = api.select_winner(env.campaign_id, env.tenant.author_headers)
        validate_error(resp, ApiErrorId.ERR_AB_NOT_ENABLED.value)
        assert read_campaign(env.campaign_id)["winning_variant"] is None


class TestWinnerRanking:
    def test_the_higher_click_rate_wins_outright(self, api):
        """PRD §3.9: "The winner is the label whose click rate — its click count divided by its
        delivered-send count — is strictly higher; the comparison is made on the exact rational
        values, with no rounding beforehand."
        PRD §3.9: "The chosen label is written to `winning_variant` and `winner_selected_at` is
        stamped with the clock."

        Design: Corner/calculations/ab_winner_ranked_by_click_rate_selects_b
        """
        env = setup_dispatched_campaign(
            num_subscribers=4,
            ab_test_enabled=True,
            variant_split_pct=50,
            variant_b_subject="B",
            name="AB",
        )
        for send_id in env.send_ids:
            deliver(send_id)

        open_send(env.send_ids[0])  # variant A: 1 open, 0 clicks
        open_send(env.send_ids[2])  # variant B
        click_send(env.send_ids[2])  # variant B: 1 click
        open_send(env.send_ids[3])  # variant B

        winner = validate_success(api.select_winner(env.campaign_id, env.tenant.author_headers))

        assert winner["winning_variant"] == "B", "click_rate B = 1/2 = 0.5 > A = 0/2 = 0.0"
        assert winner["winner_selected_at"] == "2026-05-02T10:00:00.000Z"
        assert winner["status"] == "SENT"
