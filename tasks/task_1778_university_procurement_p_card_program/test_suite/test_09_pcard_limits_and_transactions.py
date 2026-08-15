"""P-cards: limit boundaries, elevation windows, MCC gates, close lockdown."""
from test_helpers import (
    ApiErrorId,
    assert_card_credit_invariant,
    assert_pcard,
    create_department,
    create_elevation_payload,
    create_pcard,
    create_pcard_with_debit,
    create_transaction_payload,
    get_success_data,
    make_cardholder_headers,
    post_debit,
    reconcile_txn,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import ADMIN, SURPLUS_MANAGER

ADMIN_H = ADMIN


class TestSingleTxnLimitBoundary:
    def test_debit_at_single_limit_posts(self, api):
        """PRD §3.7: "the amount may not exceed the effective single-transaction
        limit (otherwise `ERR_SINGLE_TXN_LIMIT_EXCEEDED`), and the current
        `utilization_cents` plus the new amount may not exceed
        `monthly_limit_cents` — equality is allowed on both".

        Design: Difficulty/boundary_precision_check/pcard_single_txn_limit_boundary
        """
        dept = create_department(name="Bursar")
        card = create_pcard(department_id=dept["id"], cardholder_name="Lee")
        txn = post_debit(card["id"], 100000, mcc_code="5943", merchant="Staples")
        assert txn["status"] == "POSTED"
        live = get_success_data(api.get_pcard(card["id"], ADMIN_H))
        assert live["utilization_cents"] == 100000
        assert live["available_credit_cents"] == 400000
        assert_card_credit_invariant(live)

    def test_debit_one_cent_over_single_limit_rejected(self, api):
        """PRD §3.7: "the amount may not exceed the effective single-transaction
        limit (otherwise `ERR_SINGLE_TXN_LIMIT_EXCEEDED`)".

        Design: Difficulty/boundary_precision_check/pcard_single_txn_limit_boundary
        """
        dept = create_department(name="Bursar")
        card = create_pcard(department_id=dept["id"], cardholder_name="Lee")
        post_debit(card["id"], 100000, mcc_code="5943")
        over = api.create_pcard_transaction(
            card["id"],
            create_transaction_payload(
                amount_cents=100001, merchant_name="Staples", mcc_code="5943"
            ),
            make_cardholder_headers(card["id"]),
        )
        validate_error(over, ApiErrorId.ERR_SINGLE_TXN_LIMIT_EXCEEDED, 422)
        live = get_success_data(api.get_pcard(card["id"], ADMIN_H))
        assert live["utilization_cents"] == 100000, (
            "the rejected debit must not persist into utilization"
        )


class TestElevationWindowEffectiveness:
    def test_elevation_window_start_inclusive_end_exclusive(self, api):
        """PRD §3.7: "A debit timestamped exactly at `window_start` already
        enjoys the elevated limit; one timestamped exactly at `window_end` falls
        back to the base limit."
        PRD §3.7: "the current `utilization_cents` plus the new amount may not
        exceed `monthly_limit_cents` — equality is allowed on both (otherwise
        `ERR_MONTHLY_LIMIT_EXCEEDED`)".

        Design: Corner/calculations/elevation_window_start_inclusive_end_exclusive
        """
        set_clock("2026-08-09T00:00:00Z")
        dept = create_department(name="Events")
        card = create_pcard(
            department_id=dept["id"], cardholder_name="Eve",
            single_txn_limit_cents=100000, monthly_limit_cents=260000,
        )
        cid = card["id"]
        get_success_data(
            api.create_elevation(
                cid,
                create_elevation_payload(
                    elevated_single_txn_limit_cents=200000,
                    window_start="2026-08-10T00:00:00Z",
                    window_end="2026-08-12T00:00:00Z",
                ),
                ADMIN_H,
            )
        )

        set_clock("2026-08-10T00:00:00Z")  # window_start, inclusive
        first = post_debit(cid, 150000, mcc_code="7299", merchant="TentRental")
        assert first["status"] == "POSTED"

        monthly = api.create_pcard_transaction(
            cid,
            create_transaction_payload(
                amount_cents=150000, merchant_name="TentRental", mcc_code="7299"
            ),
            make_cardholder_headers(cid),
        )
        # 150,000 + 150,000 = 300,000 > 260,000 monthly — the elevation never
        # relaxes the monthly ceiling.
        validate_error(monthly, ApiErrorId.ERR_MONTHLY_LIMIT_EXCEEDED, 422)

        set_clock("2026-08-12T00:00:00Z")  # window_end, exclusive
        after = api.create_pcard_transaction(
            cid,
            create_transaction_payload(
                amount_cents=110000, merchant_name="TentRental", mcc_code="7299"
            ),
            make_cardholder_headers(cid),
        )
        validate_error(after, ApiErrorId.ERR_SINGLE_TXN_LIMIT_EXCEEDED, 422)


class TestElevationGapBuffer:
    def _card_with_e1(self, api):
        dept = create_department(name="Housing")
        card = create_pcard(department_id=dept["id"], cardholder_name="Kim")
        e1 = get_success_data(
            api.create_elevation(
                card["id"],
                create_elevation_payload(
                    window_start="2026-08-10T00:00:00Z",
                    window_end="2026-08-12T00:00:00Z",
                ),
                ADMIN_H,
            )
        )
        return card, e1

    def test_overlapping_and_short_gap_elevations_rejected(self, api):
        """PRD §3.8: "Windows on the same card may never overlap an existing
        `SCHEDULED` elevation (`ERR_ELEVATION_OVERLAP`) and must keep at least a
        seven-day gap from any adjacent `SCHEDULED` one
        (`ERR_ELEVATION_GAP_VIOLATION`)."

        Design: Difficulty/resource_temporal_overlap/elevation_window_gap_buffer
        """
        card, _ = self._card_with_e1(api)
        overlap = api.create_elevation(
            card["id"],
            create_elevation_payload(
                window_start="2026-08-11T00:00:00Z",
                window_end="2026-08-13T00:00:00Z",
            ),
            ADMIN_H,
        )
        validate_error(overlap, ApiErrorId.ERR_ELEVATION_OVERLAP, 409)

        short_gap = api.create_elevation(
            card["id"],
            create_elevation_payload(
                window_start="2026-08-15T00:00:00Z",
                window_end="2026-08-16T00:00:00Z",
            ),
            ADMIN_H,
        )
        # 2026-08-12 -> 2026-08-15 is a 3-day gap, below the 7-day buffer.
        validate_error(short_gap, ApiErrorId.ERR_ELEVATION_GAP_VIOLATION, 409)

    def test_exactly_seven_day_gap_elevation_created(self, api):
        """PRD §3.8: "must keep at least a seven-day gap from any adjacent
        `SCHEDULED` one (`ERR_ELEVATION_GAP_VIOLATION`)" — a gap of exactly
        seven days satisfies the buffer.
        PRD §3.8: "An elevation is born `SCHEDULED`".

        Design: Difficulty/resource_temporal_overlap/elevation_window_gap_buffer
        """
        card, _ = self._card_with_e1(api)
        created = get_success_data(
            api.create_elevation(
                card["id"],
                create_elevation_payload(
                    window_start="2026-08-19T00:00:00Z",
                    window_end="2026-08-20T00:00:00Z",
                ),
                ADMIN_H,
            )
        )
        assert created["status"] == "SCHEDULED"


class TestMccRestriction:
    def test_mcc_restriction_conditional_on_card_config(self, api):
        """PRD §3.7: "When the card's `allowed_mccs` is non-empty, a code outside
        it is rejected with `ERR_MCC_NOT_ALLOWED`." and "an empty array means the
        card is unrestricted by merchant category".

        Design: Corner/validations/mcc_restriction_conditional_on_card_config
        """
        dept = create_department(name="Procure")
        card_a = create_pcard(
            department_id=dept["id"], cardholder_name="Max",
            allowed_mccs=["5942"],
        )
        card_b = create_pcard(
            department_id=dept["id"], cardholder_name="Nia", allowed_mccs=[],
        )
        blocked = api.create_pcard_transaction(
            card_a["id"],
            create_transaction_payload(
                amount_cents=5000, merchant_name="Hotel", mcc_code="7011"
            ),
            make_cardholder_headers(card_a["id"]),
        )
        validate_error(blocked, ApiErrorId.ERR_MCC_NOT_ALLOWED, 422)

        ok = post_debit(card_a["id"], 5000, mcc_code="5942", merchant="Books")
        assert ok["status"] == "POSTED"

        unrestricted = api.create_pcard_transaction(
            card_b["id"],
            create_transaction_payload(
                amount_cents=5000, merchant_name="Hotel", mcc_code="7011"
            ),
            make_cardholder_headers(card_b["id"]),
        )
        assert validate_success(unrestricted, 201)["status"] == "POSTED"


class TestCardCloseGating:
    def test_pcard_close_gating_and_closed_lockdown(self, api):
        """PRD §3.8: "Closing additionally requires that no transaction remain in
        `POSTED` or `DISPUTED` (otherwise `ERR_CARD_HAS_OPEN_TRANSACTIONS`), and
        `CLOSED` is terminal: every card mutation and every reconcile or dispute
        on a closed card is refused with `ERR_CARD_CLOSED`."
        PRD §3.7: "Posting requires the card to be `ACTIVE`: a suspended card
        rejects with `ERR_CARD_NOT_ACTIVE`, and a closed one with
        `ERR_CARD_CLOSED`."

        Design: Corner/state_machines/pcard_close_open_txn_and_closed_post_rejected
        """
        dept = create_department(name="Parking")
        card, txn = create_pcard_with_debit(
            amount_cents=40000, department_id=dept["id"], cardholder_name="Rue",
        )
        cid = card["id"]
        early = api.close_pcard(cid, ADMIN_H)
        validate_error(early, ApiErrorId.ERR_CARD_HAS_OPEN_TRANSACTIONS, 409)

        reconcile_txn(txn["id"], cid, receipt_reference="rcpt-9")
        closed = get_success_data(api.close_pcard(cid, ADMIN_H))
        assert closed["status"] == "CLOSED"

        post_after = api.create_pcard_transaction(
            cid,
            create_transaction_payload(amount_cents=10000, mcc_code="5541"),
            make_cardholder_headers(cid),
        )
        validate_error(post_after, ApiErrorId.ERR_CARD_CLOSED, 409)


class TestDisputeRequiresCardNotClosed:
    def _closed_card_with_reconciled_txn(self, api):
        dept = create_department(name="Alumni")
        card = create_pcard(department_id=dept["id"], cardholder_name="Sam")
        txn = post_debit(card["id"], 50000, mcc_code="7011", merchant="Hotel")
        reconcile_txn(txn["id"], card["id"], receipt_reference="rcpt-1")
        get_success_data(api.close_pcard(card["id"], ADMIN_H))
        return card, txn

    def test_dispute_rejected_on_closed_card(self, api):
        """PRD §3.8: "a closed card blocks the operation with `ERR_CARD_CLOSED`".

        Design: Difficulty/cross_entity_state_dependency/dispute_requires_card_not_closed
        """
        card, txn = self._closed_card_with_reconciled_txn(api)
        resp = api.dispute_transaction(
            txn["id"], {"reason": "duplicate charge"},
            make_cardholder_headers(card["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_CARD_CLOSED, 409)
        live = get_success_data(api.get_pcard_transaction(txn["id"], ADMIN_H))
        assert live["status"] == "RECONCILED", "no partial mutation"

    def test_dispute_allowed_before_close(self, api):
        """PRD §3.8: "The cardholder may dispute a transaction in `POSTED` or
        `RECONCILED`" and "The transaction becomes `DISPUTED` and remembers where
        it came from in `pre_dispute_status` (`POSTED` or `RECONCILED`)".

        Design: Difficulty/cross_entity_state_dependency/dispute_requires_card_not_closed
        """
        dept = create_department(name="Alumni")
        card = create_pcard(department_id=dept["id"], cardholder_name="Sam")
        txn = post_debit(card["id"], 50000, mcc_code="7011", merchant="Hotel")
        reconcile_txn(txn["id"], card["id"], receipt_reference="rcpt-1")
        disputed = get_success_data(
            api.dispute_transaction(
                txn["id"], {"reason": "duplicate charge"},
                make_cardholder_headers(card["id"]),
            )
        )
        assert disputed["status"] == "DISPUTED"
        assert disputed["pre_dispute_status"] == "RECONCILED"


class TestCardholderOwnership:
    def test_cardholder_ownership_across_cards(self, api):
        """PRD §2.1: "When `X-User-Role` is `Cardholder`, `X-User-ID` is the `id`
        of the acting `PCard`; ownership checks on any resource that references a
        `PCard` compare the resource's `pcard_id` field to `X-User-ID`."
        PRD §3.7: "any cardholder operation on another card is refused with
        `ERR_NOT_RESOURCE_OWNER`".

        Design: Corner/rbac/cardholder_ownership_across_cards
        """
        dept = create_department(name="RBAC2")
        card_a = create_pcard(department_id=dept["id"], cardholder_name="A")
        card_b = create_pcard(department_id=dept["id"], cardholder_name="B")
        txn_b = post_debit(card_b["id"], 7000)

        cross_post = api.create_pcard_transaction(
            card_b["id"],
            create_transaction_payload(amount_cents=1000),
            make_cardholder_headers(card_a["id"]),
        )
        validate_error(cross_post, ApiErrorId.ERR_NOT_RESOURCE_OWNER, 403)

        cross_reconcile = api.reconcile_transaction(
            txn_b["id"],
            {"receipt_reference": "rcpt-x", "allocation_type": "GENERAL"},
            make_cardholder_headers(card_a["id"]),
        )
        validate_error(cross_reconcile, ApiErrorId.ERR_NOT_RESOURCE_OWNER, 403)
        live = get_success_data(api.get_pcard_transaction(txn_b["id"], ADMIN_H))
        assert live["status"] == "POSTED"
