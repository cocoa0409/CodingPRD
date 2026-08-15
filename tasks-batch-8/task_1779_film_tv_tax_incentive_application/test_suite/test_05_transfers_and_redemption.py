"""Transfer market negotiation/settlement, certificate redemption, and the
certificate OCC guard."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    accept_transfer_by_buyer,
    accept_transfer_by_seller,
    counter_transfer_by_buyer,
    counter_transfer_by_seller,
    create_transfer_payload,
    get_certificate,
    get_transfer,
    make_buyer_headers,
    make_producer_headers,
    open_clawback_case,
    propose_transfer,
    register_buyer,
    set_logical_clock,
    settle_transfer,
    setup_approved_application,
    setup_issued_certificate,
    validate_error,
    validate_paginated,
    validate_success,
    run_accepted_audit,
)

ADMIN = TEST_USERS["admin_headers"]
REVIEWER1 = TEST_USERS["reviewer1_headers"]


class TestRedemption:
    def test_partial_redeem_keeps_issued_status(self, api):
        """PRD §3.7: "Redemption reduces `remaining_amount_cents` and increases
        `redeemed_total_cents` by the redeemed amount. Redeeming the full
        remaining balance — from `ISSUED` or from `PARTIALLY_TRANSFERRED` —
        closes the certificate as `REDEEMED`; a partial redemption leaves the
        status unchanged."

        Design: Corner/state_machines/partial_redeem_keeps_issued_status
        """
        scenario = setup_issued_certificate()
        certificate = scenario.certificate
        producer = make_producer_headers(scenario.company["id"])

        first = validate_success(api.redeem_certificate(
            certificate["id"], 20_000_000, producer), 200)
        assert first["status"] == "ISSUED"
        assert first["remaining_amount_cents"] == 40_750_000
        assert first["redeemed_total_cents"] == 20_000_000

        second = validate_success(api.redeem_certificate(
            certificate["id"], 40_750_000, producer), 200)
        assert second["status"] == "REDEEMED"
        assert second["remaining_amount_cents"] == 0
        assert second["redeemed_total_cents"] == 60_750_000

    def test_redeem_after_certificate_expiry_rejected(self, api):
        """PRD §3.6: "an `issued_at` stamped with the logical clock, and an
        `expires_at` set to the issuance instant plus the program's
        `credit_validity_days` days"
        PRD §3.7: "The owning producer redeems against a certificate standing
        `ISSUED` or `PARTIALLY_TRANSFERRED` with a `redeem_amount_cents` that
        must be positive and must not exceed `remaining_amount_cents`
        (`ERR_AMOUNT_EXCEEDS_REMAINING`), before the certificate's expiry
        (`ERR_CERTIFICATE_EXPIRED`), and only as the owner of the certificate's
        production company (`ERR_NOT_OWNER`)."

        Design: Corner/validations/redeem_after_certificate_expiry_rejected
        """
        scenario = setup_issued_certificate(
            attested_atl=0, attested_btl=20_000_000,
            estimated_qualified_spend_cents=20_000_000,
            total_budget_cents=100_000_000,
            program_overrides={"program_name": "GA Short-Validity Credit",
                               "credit_validity_days": 30})
        certificate = scenario.certificate
        assert certificate["issued_amount_cents"] == 5_000_000
        assert certificate["expires_at"].startswith("2026-08-31"), (
            "issued at the 2026-08-01 default clock plus 30 validity days")

        set_logical_clock("2026-09-15T00:00:00Z")
        resp = api.redeem_certificate(
            certificate["id"], 1_000_000,
            make_producer_headers(scenario.company["id"]))
        validate_error(resp, ApiErrorId.ERR_CERTIFICATE_EXPIRED)
        current = get_certificate(certificate)
        assert current["remaining_amount_cents"] == 5_000_000

    def test_buyer_cannot_redeem_certificate_forbidden(self, api):
        """PRD §2.1: "A request whose role is not on the target endpoint's
        authorized list is rejected with `ERR_FORBIDDEN_FOR_ROLE`."
        PRD §4: "| POST | `/api/certificates/{certificateId}/redeem` | Redeem
        credit with the state; redeeming the full remaining balance closes the
        certificate | Producer |"

        Design: Corner/rbac/buyer_cannot_redeem_certificate_forbidden
        """
        scenario = setup_issued_certificate()
        buyer = register_buyer()
        resp = api.redeem_certificate(
            scenario.certificate["id"], 1_000_000,
            make_buyer_headers(buyer["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)
        assert get_certificate(scenario.certificate)[
            "remaining_amount_cents"] == 60_750_000


class TestTransferCreate:
    def test_transfer_price_exact_floor_accepted(self, api):
        """PRD §3.7: "And the price must clear the floor: `price_cents` must be
        at least the program's `transfer_price_floor_pct` multiplied by
        `amount_cents` and rounded down to whole cents — the exact floor is
        allowed — with the program resolved through the certificate's
        application (`ERR_TRANSFER_PRICE_BELOW_FLOOR`)."

        Design: Difficulty/boundary_precision_check/transfer_price_exact_floor
        """
        scenario = setup_issued_certificate()
        buyer = register_buyer()
        transfer = propose_transfer(
            scenario.certificate, buyer, scenario.company,
            amount_cents=10_000_001, price_cents=9_000_000,
            expected_certificate_version=scenario.certificate["version"])
        assert transfer["status"] == "PROPOSED", (
            "price 9000000 == floor(0.90 * 10000001): the exact floor is "
            "allowed even though 9000000/10000001 < 0.90 as a raw ratio")

    def test_transfer_price_one_cent_below_floor_rejected(self, api):
        """PRD §3.7: "And the price must clear the floor: `price_cents` must be
        at least the program's `transfer_price_floor_pct` multiplied by
        `amount_cents` and rounded down to whole cents — the exact floor is
        allowed — with the program resolved through the certificate's
        application (`ERR_TRANSFER_PRICE_BELOW_FLOOR`)."

        Design: Difficulty/boundary_precision_check/transfer_price_exact_floor
        """
        scenario = setup_issued_certificate()
        buyer = register_buyer()
        resp = api.create_transfer(
            create_transfer_payload(
                scenario.certificate["id"], buyer["id"],
                scenario.certificate["version"],
                amount_cents=10_000_001, price_cents=8_999_999),
            make_producer_headers(scenario.company["id"]))
        validate_error(resp, ApiErrorId.ERR_TRANSFER_PRICE_BELOW_FLOOR)
        data, _ = validate_paginated(api.list_transfers(
            ADMIN, params={"certificate_id": scenario.certificate["id"]}))
        assert data == [], "no transfer is persisted below the floor"

    def test_transfer_amount_exceeds_remaining_rejected(self, api):
        """PRD §3.7: "The face amount must not exceed the certificate's
        `remaining_amount_cents` (`ERR_AMOUNT_EXCEEDS_REMAINING`)."

        Design: Corner/validations/transfer_amount_exceeds_remaining_rejected
        """
        scenario = setup_issued_certificate()
        buyer = register_buyer()
        resp = api.create_transfer(
            create_transfer_payload(
                scenario.certificate["id"], buyer["id"],
                scenario.certificate["version"],
                amount_cents=70_000_000, price_cents=63_000_000),
            make_producer_headers(scenario.company["id"]))
        validate_error(resp, ApiErrorId.ERR_AMOUNT_EXCEEDS_REMAINING)
        assert get_certificate(scenario.certificate)[
            "remaining_amount_cents"] == 60_750_000

    def test_occ_transfer_create_stale_certificate(self, api):
        """PRD §2.8: "Proposing a credit transfer requires the request to carry
        `expected_certificate_version` equal to the certificate's current
        `version`; multiple open proposals against one certificate are
        legitimate product behavior, so if the certificate's version has advanced
        since the client last read it — because another proposal was created
        against it, for example — the create is rejected with
        `ERR_STALE_CERTIFICATE_VERSION` (HTTP 412), forcing the seller to re-read
        `remaining_amount_cents` and the outstanding proposals before proposing
        again."
        PRD §3.7: "Creating a proposal increments the certificate's `version` by
        one, which is what arms the optimistic-concurrency guard for the next
        proposer; multiple open proposals against one certificate are
        legitimate."

        Design: Corner/cross_cutting_layers/occ_transfer_create_stale_certificate
        """
        scenario = setup_issued_certificate()
        buyer = register_buyer()
        producer = make_producer_headers(scenario.company["id"])
        stale_version = scenario.certificate["version"]

        first = propose_transfer(
            scenario.certificate, buyer, scenario.company,
            amount_cents=5_000_000, price_cents=4_500_000,
            expected_certificate_version=stale_version)
        assert first["status"] == "PROPOSED"

        stale = api.create_transfer(
            create_transfer_payload(
                scenario.certificate["id"], buyer["id"], stale_version,
                amount_cents=6_000_000, price_cents=5_400_000),
            producer)
        validate_error(stale, ApiErrorId.ERR_STALE_CERTIFICATE_VERSION)

        fresh_version = get_certificate(scenario.certificate)["version"]
        assert fresh_version == stale_version + 1
        third = validate_success(api.create_transfer(
            create_transfer_payload(
                scenario.certificate["id"], buyer["id"], fresh_version,
                amount_cents=6_000_000, price_cents=5_400_000),
            producer), 201)
        assert third["status"] == "PROPOSED", (
            "staleness, not the second proposal itself, caused the rejection")


class TestNegotiationLoop:
    def _setup_counter_loop(self, api):
        scenario = setup_issued_certificate()
        buyer = register_buyer()
        transfer = propose_transfer(
            scenario.certificate, buyer, scenario.company,
            amount_cents=10_000_000, price_cents=9_500_000,
            expected_certificate_version=scenario.certificate["version"])
        return scenario, buyer, transfer

    def test_transfer_negotiation_counter_loop_status_sequence(self, api):
        """PRD §3.7: "While the transfer stands `PROPOSED`, the seller's offer is
        on the table and the buyer counters with a `new_price_cents`, moving the
        transfer to `COUNTERED`. While it stands `COUNTERED`, the buyer's offer
        is on the table and the seller — the producer owning
        `seller_production_company_id` — counters back with its own
        `new_price_cents`, returning the transfer to `PROPOSED`."
        PRD §3.7: "each counter sets `current_price_cents` to the new price and
        increments `round_count` by one. The loop is unbounded."

        Design: Difficulty/non_linear_state_machine/transfer_negotiation_counter_loop
        """
        scenario, buyer, transfer = self._setup_counter_loop(api)
        c1 = counter_transfer_by_buyer(transfer, buyer, 9_100_000)
        assert c1["status"] == "COUNTERED"
        c2 = counter_transfer_by_seller(c1, scenario.company, 9_400_000)
        assert c2["status"] == "PROPOSED"
        c3 = counter_transfer_by_buyer(c2, buyer, 9_200_000)
        assert c3["status"] == "COUNTERED"
        accepted = accept_transfer_by_seller(c3, scenario.company)
        assert accepted["status"] == "ACCEPTED"
        assert accepted["round_count"] == 3
        assert accepted["current_price_cents"] == 9_200_000

    def test_transfer_negotiation_settle_debits_certificate_by_face(self, api):
        """PRD §3.7: "Settlement pays the standing `current_price_cents`, moves
        the transfer to the terminal `SETTLED` state, stamps `settled_at` — null
        until this moment — and debits the certificate: `remaining_amount_cents`
        falls by the face amount and `transferred_total_cents` rises by it."
        PRD §3.7: "The certificate moves from `ISSUED` to
        `PARTIALLY_TRANSFERRED` when a slice remains, or to `FULLY_TRANSFERRED`
        when the settled amount consumes the remainder exactly — whether directly
        from `ISSUED` or from `PARTIALLY_TRANSFERRED`."

        Design: Difficulty/non_linear_state_machine/transfer_negotiation_counter_loop
        """
        scenario, buyer, transfer = self._setup_counter_loop(api)
        transfer = counter_transfer_by_buyer(transfer, buyer, 9_100_000)
        transfer = counter_transfer_by_seller(transfer, scenario.company, 9_400_000)
        transfer = counter_transfer_by_buyer(transfer, buyer, 9_200_000)
        transfer = accept_transfer_by_seller(transfer, scenario.company)
        settled = settle_transfer(transfer)
        assert settled["status"] == "SETTLED"
        assert settled["settled_at"] is not None

        certificate = get_certificate(scenario.certificate)
        assert certificate["remaining_amount_cents"] == 50_750_000, (
            "the certificate is debited by the 10000000 face amount")
        assert certificate["transferred_total_cents"] == 10_000_000
        assert certificate["status"] == "PARTIALLY_TRANSFERRED"

    def test_settled_transfer_terminal_lockdown(self, api):
        """PRD §3.7: "Settlement pays the standing `current_price_cents`, moves
        the transfer to the terminal `SETTLED` state, stamps `settled_at` — null
        until this moment — and debits the certificate"
        PRD §3.3: "Any action attempted from a state where that transition is
        not declared — submitting an application that is not in `DRAFT`, for
        instance — is rejected with `ERR_INVALID_STATE_TRANSITION`."

        Design: Corner/state_machines/settled_transfer_terminal_lockdown
        """
        scenario = setup_issued_certificate()
        buyer = register_buyer()
        transfer = propose_transfer(
            scenario.certificate, buyer, scenario.company,
            amount_cents=5_000_000, price_cents=4_500_000,
            expected_certificate_version=scenario.certificate["version"])
        transfer = accept_transfer_by_buyer(transfer, buyer)
        settled = settle_transfer(transfer)
        assert settled["status"] == "SETTLED"

        counter = api.counter_transfer(
            transfer["id"], 4_600_000, make_buyer_headers(buyer["id"]))
        validate_error(counter, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
        cancel = api.cancel_transfer(
            transfer["id"], make_producer_headers(scenario.company["id"]))
        validate_error(cancel, ApiErrorId.ERR_INVALID_STATE_TRANSITION)

        current = get_transfer(transfer)
        assert current["status"] == "SETTLED"
        assert current["round_count"] == 0

    def test_transfer_accept_after_proposal_expiry_rejected(self, api):
        """PRD §3.7: "A created transfer stands `PROPOSED` with `proposed_at`
        stamped, an `expires_at` of the proposal instant plus the program's
        `transfer_proposal_validity_days` days"
        PRD §3.7: "Acceptance mirrors the split: the buyer accepts while the
        transfer stands `PROPOSED`, and the seller accepts while it stands
        `COUNTERED`, each moving the transfer to `ACCEPTED` subject to the same
        expiry check."

        Design: Corner/validations/transfer_accept_after_proposal_expiry_rejected
        """
        scenario = setup_issued_certificate()
        buyer = register_buyer()
        transfer = propose_transfer(
            scenario.certificate, buyer, scenario.company,
            amount_cents=5_000_000, price_cents=4_500_000,
            expected_certificate_version=scenario.certificate["version"])
        assert transfer["expires_at"].startswith("2026-08-15"), (
            "proposed at the 2026-08-01 default clock plus 14 validity days")

        set_logical_clock("2026-08-16T00:00:00Z")
        resp = api.accept_transfer(transfer["id"], make_buyer_headers(buyer["id"]))
        validate_error(resp, ApiErrorId.ERR_TRANSFER_EXPIRED)
        assert get_transfer(transfer)["status"] == "PROPOSED"


class TestSettlementSweep:
    def _setup_three_proposals(self, api):
        scenario = setup_issued_certificate()
        buyer = register_buyer()
        t1 = propose_transfer(
            scenario.certificate, buyer, scenario.company,
            amount_cents=30_000_000, price_cents=27_000_000,
            expected_certificate_version=scenario.certificate["version"])
        t1 = accept_transfer_by_buyer(t1, buyer)
        t2 = propose_transfer(
            scenario.certificate, buyer, scenario.company,
            amount_cents=40_000_000, price_cents=36_000_000)
        t3 = propose_transfer(
            scenario.certificate, buyer, scenario.company,
            amount_cents=20_000_000, price_cents=18_000_000)
        return scenario, buyer, t1, t2, t3

    def test_settle_cancels_oversized_sibling_transfers(self, api):
        """PRD §3.7: "Settlement then sweeps the order book: every other transfer
        of the same certificate still standing `PROPOSED` or `COUNTERED` whose
        face amount now exceeds the reduced remainder is cancelled with
        `cancellation_reason` `INSUFFICIENT_REMAINING`."

        Design: Difficulty/transitive_cascade/settle_cancels_oversized_sibling_transfers
        """
        _scenario, _buyer, t1, t2, t3 = self._setup_three_proposals(api)
        settle_transfer(t1)

        t2_now = get_transfer(t2)
        assert t2_now["status"] == "CANCELLED"
        assert t2_now["cancellation_reason"] == "INSUFFICIENT_REMAINING", (
            "40000000 exceeds the reduced remainder 30750000")
        t3_now = get_transfer(t3)
        assert t3_now["status"] == "PROPOSED", (
            "20000000 still fits the reduced remainder and survives the sweep")

    def test_settle_debits_certificate_and_moves_status(self, api):
        """PRD §3.7: "Settlement pays the standing `current_price_cents`, moves
        the transfer to the terminal `SETTLED` state, stamps `settled_at` — null
        until this moment — and debits the certificate: `remaining_amount_cents`
        falls by the face amount and `transferred_total_cents` rises by it."
        PRD §3.7: "The certificate moves from `ISSUED` to
        `PARTIALLY_TRANSFERRED` when a slice remains"

        Design: Difficulty/transitive_cascade/settle_cancels_oversized_sibling_transfers
        """
        scenario, _buyer, t1, _t2, _t3 = self._setup_three_proposals(api)
        settled = settle_transfer(t1)
        assert settled["status"] == "SETTLED"
        assert settled["settled_at"] is not None

        certificate = get_certificate(scenario.certificate)
        assert certificate["remaining_amount_cents"] == 30_750_000
        assert certificate["transferred_total_cents"] == 30_000_000
        assert certificate["status"] == "PARTIALLY_TRANSFERRED"


class TestClawbackCaseGating:
    def test_clawback_create_requires_credit_issued(self, api):
        """PRD §3.8: "A `FilmOfficeAdmin` opens one manually against an
        application standing `CREDIT_ISSUED` — any other status is rejected with
        `ERR_INVALID_STATE_TRANSITION`"

        Design: Difficulty/cross_entity_state_dependency/clawback_requires_credit_issued
        """
        scenario = setup_approved_application()
        run_accepted_audit(scenario.application, 40_000_000, 162_500_000)

        resp = api.create_clawback_case(
            {"application_id": scenario.application["id"],
             "trigger_reason": "MISREPRESENTATION", "penalty_mode": "SIMPLE",
             "shortfall_amount_cents": 1_000_000},
            ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
        data, _ = validate_paginated(api.list_clawback_cases(
            ADMIN, params={"application_id": scenario.application["id"]}))
        assert data == []

    def test_clawback_create_after_issuance_derives_certificate(self, api):
        """PRD §3.8: "The case opens in `OPENED` with its `certificate_id`
        derived from the application's certificate."

        Design: Difficulty/cross_entity_state_dependency/clawback_requires_credit_issued
        """
        scenario = setup_issued_certificate()
        case = open_clawback_case(scenario.application,
                                  trigger_reason="MISREPRESENTATION",
                                  penalty_mode="SIMPLE",
                                  shortfall_amount_cents=1_000_000)
        assert case["status"] == "OPENED"
        assert case["certificate_id"] == scenario.certificate["id"], (
            "the certificate reference is derived, not supplied")
        data, _ = validate_paginated(api.list_clawback_cases(
            ADMIN, params={"application_id": scenario.application["id"]}))
        assert len(data) == 1
