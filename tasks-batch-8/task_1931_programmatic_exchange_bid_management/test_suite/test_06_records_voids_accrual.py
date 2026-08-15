"""Auction record shape, billing confirmation, voids, and the spend and
accrual conservation laws."""
from test_helpers import (
    ApiErrorId,
    assert_auction_record,
    assert_outcome,
    approve_batch,
    confirm_record,
    create_batch,
    fill_auction,
    get_deal,
    get_partner,
    get_publisher,
    is_iso8601_timestamp,
    is_valid_uuid,
    list_records,
    release_batch,
    run_auction,
    setup_active_deal,
    submit_batch,
    validate_error,
    validate_paginated,
    validate_success,
    void_record,
    make_bid,
)
from test_helpers import TEST_USERS

ADMIN = TEST_USERS["exchange_admin_headers"]
DEMAND = TEST_USERS["demand_side_headers"]


class TestRecordShape:
    def test_auction_record_is_append_only_without_version(self, api):
        """PRD §2.6: "Two ledger-style resources are deliberately thinner: a
        supply-chain node and an auction record each carry only `id` and
        `created_at`; both `updated_at` and `version` are absent from them,
        because neither is ever modified after creation."
        PRD §2.4: "Before any operator sets it, the logical clock reads exactly
        2026-08-01T00:00:00Z."

        Design: Corner/entities/auction_record_is_append_only_without_version
        """
        sc = setup_active_deal()
        record = fill_auction(sc["pub"]["id"])
        fetched = validate_success(api.get_auction_record(record["id"], ADMIN))
        assert_auction_record(fetched)
        assert is_valid_uuid(fetched["id"])
        assert is_iso8601_timestamp(fetched["created_at"])
        assert fetched["created_at"].startswith("2026-08-01T00:00:00"), (
            "created_at is stamped from the logical clock's default")
        assert fetched["voided"] is False
        assert fetched["dsp_confirmed_at"] is None
        assert fetched["voided_at"] is None


class TestOneShotMutations:
    def test_double_confirm_and_double_void_rejected(self, api):
        """PRD §3.6: "confirming a record that is already confirmed is rejected
        with `ERR_ALREADY_CONFIRMED`."
        PRD §3.6: "voiding an already-voided record is rejected with
        `ERR_ALREADY_VOIDED`."

        Design: Corner/validations/double_confirm_and_double_void_rejected
        """
        sc = setup_active_deal()
        r1 = fill_auction(sc["pub"]["id"])
        r2 = fill_auction(sc["pub"]["id"])

        confirm_record(r1["id"])
        resp = api.confirm_billing(r1["id"], DEMAND)
        validate_error(resp, ApiErrorId.ERR_ALREADY_CONFIRMED)

        void_record(r2["id"])
        resp = api.void_auction_record(r2["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_ALREADY_VOIDED)

        partner = get_partner(sc["partner"]["id"])
        assert partner["lifetime_spend_micros"] == 1000000, (
            "Exactly one void applied to R2; R1's gross 1,000,000 stands")
        assert validate_success(
            api.get_auction_record(r1["id"], ADMIN))["voided"] is False


class TestVoidConservation:
    def test_fill_moves_partner_spend_counters(self, api):
        """PRD §3.5: "The partner's `current_second_auction_count` increments by
        one, and its `spend_today_micros` and `lifetime_spend_micros` each grow
        by the record's `gross_micros`."
        PRD §2.10: "for each partner: `lifetime_spend_micros` always equals the
        sum of `gross_micros` over that partner's non-voided auction records"

        Design: Difficulty/compensating_invariant/auction_void_restores_partner_spend_conservation
        """
        sc = setup_active_deal()
        record = fill_auction(sc["pub"]["id"])
        partner = get_partner(sc["partner"]["id"])
        assert partner["lifetime_spend_micros"] == 1000000
        assert partner["spend_today_micros"] == 1000000
        assert get_deal(sc["deal"]["id"])["delivered_impressions"] == 1000
        assert record["gross_micros"] == 1000000

    def test_void_restores_partner_spend_and_deal_delivery(self, api):
        """PRD §2.10: "creating a record adds its gross, voiding it subtracts
        the same gross, and a create-then-void pair leaves lifetime spend
        unchanged; `spend_today_micros` obeys the same law restricted to records
        created on the current UTC date."
        PRD §3.6: "the void reverses everything the fill created: ... the deal's
        `delivered_impressions` shrinks with the guaranteed remainder
        recomputed"

        Design: Difficulty/compensating_invariant/auction_void_restores_partner_spend_conservation
        """
        sc = setup_active_deal()
        record = fill_auction(sc["pub"]["id"])
        voided = void_record(record["id"])
        assert voided["voided"] is True
        assert voided["voided_at"] is not None

        partner = get_partner(sc["partner"]["id"])
        assert partner["lifetime_spend_micros"] == 0, (
            "create+void nets to zero on the all-time law")
        assert partner["spend_today_micros"] == 0, (
            "The record was created on the current UTC date, so today's spend "
            "shrinks too")
        assert get_deal(sc["deal"]["id"])["delivered_impressions"] == 0


class TestRecordRetrieval:
    def test_auction_records_filtered_by_foreign_keys(self, api):
        """PRD §3.6: "Auction records can be listed filtered by `deal_id`,
        `publisher_id`, `demand_partner_id`, or `voided`."
        PRD §3.8: "A per-deal records listing gives the reverse reachability
        from a deal to its auction history."

        Design: Corner/endpoints/auction_records_filtered_by_foreign_keys
        """
        sc = setup_active_deal()
        r1 = fill_auction(sc["pub"]["id"])
        r2 = fill_auction(sc["pub"]["id"])
        void_record(r2["id"])

        all_recs, meta_all = list_records(deal_id=sc["deal"]["id"])
        assert meta_all["total_count"] == 2, (
            "Voided records remain queryable under the unfiltered deal view")
        assert {r["id"] for r in all_recs} == {r1["id"], r2["id"]}

        voided_recs, meta_voided = list_records(deal_id=sc["deal"]["id"],
                                                voided="true")
        assert meta_voided["total_count"] == 1
        assert voided_recs[0]["id"] == r2["id"]
        assert voided_recs[0]["voided"] is True

        sub, meta_sub = validate_paginated(
            api.list_deal_records(sc["deal"]["id"], ADMIN))
        assert meta_sub["total_count"] == 2, (
            "The per-deal sub-resource reaches the same auction history")


class TestVoidAfterSettlement:
    def test_void_rejected_after_batch_settlement(self, api):
        """PRD §3.6: "The one hard wall is settled money: if the record's
        creation UTC date falls inside the period of a `SETTLED` payout batch,
        the void is rejected with `ERR_VOID_AFTER_SETTLEMENT`, because that
        money has already flowed."

        Design: Corner/cross_cutting/void_rejected_after_batch_settlement
        """
        sc = setup_active_deal()  # GUARANTEED publisher
        record = fill_auction(sc["pub"]["id"])
        batch = create_batch()
        submit_batch(batch["id"])
        approve_batch(batch["id"])
        settled = release_batch(batch["id"])
        assert settled["status"] == "SETTLED"

        resp = api.void_auction_record(record["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_VOID_AFTER_SETTLEMENT)
        after = validate_success(api.get_auction_record(record["id"], ADMIN))
        assert after["voided"] is False
        publisher = get_publisher(sc["pub"]["id"])
        assert publisher["paid_out_micros"] == 850000, (
            "Settlement is final: the paid amount is untouched by the rejected "
            "void")
