"""
Cross-cutting behaviour: optimistic concurrency on the two parent aggregates
that demand an expected version, the monotonic version counter under writes
from different actors, and the immediate visibility of a cascade.
"""

from test_helpers import (
    ApiErrorId,
    acknowledge_disclosures,
    add_verified_buyer,
    assert_cash_buyer,
    assert_earnest_money_deposit,
    assert_pagination_meta,
    assert_purchase_contract,
    assert_seller_lead,
    build_draft_contract,
    build_signed_contract,
    elect,
    factories,
    make_seller_headers,
    make_cash_buyer_headers,
    make_wholesaler_headers,
    read_buyer,
    read_contract,
    read_lead,
    record_lead,
    register_wholesaler,
    screen_lead,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
    TITLE_AGENT_1,
)


class TestStaleContractVersionOnOfferCreate:
    """A bid measured against a version the contract has already left."""

    def test_offer_carrying_the_pre_election_version_is_rejected(self, api):
        """
        "Creating an `AssignmentOffer` requires the non-optional field
        `expected_purchase_contract_version`, carrying the client's last
        observed `version` of the target `PurchaseContract`. If that value does
        not equal the contract's current `version`, the create is rejected with
        `ERR_STALE_CONTRACT_VERSION` (HTTP 412) and no side effects whatsoever
        are applied — no offer row, no deposit encumbrance, no
        assignment-status change."

        "A contract's `version` advances on every write that alters the contract
        or its offer set: a signature, a structure election, a counter, an
        acceptance, a superseding offer, or a cascade."

        Design: Corner/cross_cutting_layers/stale_expected_purchase_contract_version_on_offer_create_returns_conflict
        """
        scenario = build_signed_contract(
            api,
            clock="2026-08-06T00:00:00Z",
            contract_kwargs={
                "purchase_price_cents": 18000000,
                "earnest_money_cents": 500000,
            },
        )
        stale_version = elect(
            api, scenario.pc_id, scenario.w_id, "ASSIGNMENT_ELECTED"
        )["version"]
        current_version = elect(
            api, scenario.pc_id, scenario.w_id, "DOUBLE_CLOSE_ELECTED"
        )["version"]
        assert current_version > stale_version, (
            "the re-election must have advanced the counter, making the first "
            f"reading stale: {stale_version} then {current_version}"
        )
        add_verified_buyer(scenario)

        body = factories.assignment_offer_payload(
            scenario.pc_id,
            scenario.buyer_id,
            18500000,
            stale_version,
            buyer_deposit_cents=1000000,
        )
        response = api.create_assignment_offer(
            body, make_cash_buyer_headers(scenario.buyer_id)
        )
        validate_error(response, ApiErrorId.STALE_CONTRACT_VERSION, 412)

        _, meta = validate_paginated(
            api.list_assignment_offers(
                make_wholesaler_headers(scenario.w_id),
                {"purchase_contract_id": scenario.pc_id},
            )
        )
        assert_pagination_meta(meta, total_count=0)
        assert_cash_buyer(
            read_buyer(api, scenario.buyer_id, scenario.w_id),
            committed_deposit_cents=0,
            available_funds_cents=25500000,
            active_offer_count=0,
        )
        assert_purchase_contract(
            read_contract(api, scenario.pc_id, scenario.w_id),
            assignment_status="NOT_MARKETED",
            version=current_version,
        )

        body["expected_purchase_contract_version"] = current_version
        validate_success(
            api.create_assignment_offer(
                body, make_cash_buyer_headers(scenario.buyer_id)
            ),
            201,
        )


class TestStaleLeadVersionOnAnalysisCreate:
    """An analysis built on an equity picture the re-screen replaced."""

    def test_analysis_carrying_the_pre_rescreen_version_is_rejected(self, api):
        """
        "Creating a `DealAnalysis` requires the non-optional field
        `expected_seller_lead_version`, carrying the client's last observed
        `version` of the target `SellerLead`. If that value does not equal the
        lead's current `version`, the create is rejected with
        `ERR_STALE_LEAD_VERSION` (HTTP 412) with no side effects."

        "A lead's `version` advances on every protection screen and on every
        change to its contract-driven status, so an analyst who underwrote a
        lead before it was re-screened onto a different protection tier cannot
        build an analysis on a stale equity picture."

        Design: Corner/cross_cutting_layers/stale_expected_seller_lead_version_on_analysis_create_returns_conflict
        """
        set_clock(api, "2026-08-04T00:00:00Z")
        wholesaler = register_wholesaler(api)
        w_id = wholesaler["id"]
        lead = record_lead(
            api,
            w_id,
            junior_lien_cents=1500000,
            delinquent_property_tax_cents=400000,
        )
        stale_version = screen_lead(api, lead["id"], w_id, "STATUTORY")["version"]

        set_clock(api, "2026-08-05T00:00:00Z")
        current = screen_lead(api, lead["id"], w_id, "EFFECTIVE")
        assert current["version"] > stale_version, (
            "the re-screen is a versioned write: "
            f"{stale_version} then {current['version']}"
        )

        response = api.create_deal_analysis(
            factories.deal_analysis_payload(lead["id"], stale_version),
            make_wholesaler_headers(w_id),
        )
        validate_error(response, ApiErrorId.STALE_LEAD_VERSION, 412)

        _, meta = validate_paginated(
            api.list_deal_analyses(
                make_wholesaler_headers(w_id), {"seller_lead_id": lead["id"]}
            )
        )
        assert_pagination_meta(meta, total_count=0)
        assert_seller_lead(
            read_lead(api, lead["id"], w_id),
            version=current["version"],
            screening_variant="EFFECTIVE",
            screened_at="2026-08-05T00:00:00Z",
        )


class TestVersionCounterAcrossActors:
    """One counter, three writes, three different principals or dimensions."""

    def test_create_then_sign_then_elect_yields_one_two_three(self, api):
        """
        "Almost every record additionally carries an `updated_at` timestamp with
        the same format and an integer `version` that starts at 1 and increments
        by one on every mutation of that record, whether the mutation was
        requested directly by a client or applied as a cascade from another
        aggregate's write."

        "The contract's `version` increments." "Every election increments the
        contract's `version`."

        Design: Corner/cross_cutting_layers/version_increments_on_every_write_to_purchase_contract
        """
        scenario = build_draft_contract(
            api,
            clock="2026-08-06T00:00:00Z",
            contract_kwargs={
                "purchase_price_cents": 18000000,
                "earnest_money_cents": 500000,
            },
        )
        assert_purchase_contract(scenario.contract, version=1)
        acknowledge_disclosures(api, scenario.pc_id, scenario.lead_id)

        signed = validate_success(
            api.sign_purchase_contract(
                scenario.pc_id, make_seller_headers(scenario.lead_id)
            ),
            200,
        )
        assert_purchase_contract(signed, contract_status="SIGNED", version=2)

        elected = validate_success(
            api.elect_structure(
                scenario.pc_id,
                factories.elect_structure_payload("ASSIGNMENT_ELECTED"),
                make_wholesaler_headers(scenario.w_id),
            ),
            200,
        )
        assert_purchase_contract(
            elected, structure_election="ASSIGNMENT_ELECTED", version=3
        )
        assert_purchase_contract(
            read_contract(api, scenario.pc_id, scenario.w_id), version=3
        )


class TestImmediateVisibilityOfTheSigningCascade:
    """The write's own response already carries every derived value."""

    def test_signing_response_and_the_next_read_agree_with_no_settling(self, api):
        """
        "It stamps `signed_at` with the current logical instant. It derives
        `inspection_deadline_at` as `signed_at` plus `inspection_period_days`
        twenty-four-hour days — a half-open window, so cancellation by the
        wholesaler remains available at every instant strictly before that
        deadline and forfeiture becomes available at exactly that deadline."

        "Because the topology is flat, child records are discovered through
        their parent's identifier on a filtered list rather than through nested
        URLs. The earnest money deposit created by the signing cascade, for
        instance, is never returned by the signing call itself; it is found by
        listing deposits filtered on `purchase_contract_id`."

        Design: Corner/consistency_model/contract_sign_effects_are_visible_in_the_same_response
        """
        scenario = build_draft_contract(
            api,
            clock="2026-08-06T00:00:00Z",
            contract_kwargs={
                "purchase_price_cents": 18000000,
                "earnest_money_cents": 500000,
                "inspection_period_days": 7,
            },
        )
        acknowledge_disclosures(api, scenario.pc_id, scenario.lead_id)

        response = api.sign_purchase_contract(
            scenario.pc_id, make_seller_headers(scenario.lead_id)
        )
        signed = validate_success(response, 200)

        assert_purchase_contract(
            signed,
            contract_status="SIGNED",
            signed_at="2026-08-06T00:00:00Z",
            inspection_deadline_at="2026-08-13T00:00:00Z",
            version=2,
        )
        assert read_contract(api, scenario.pc_id, scenario.w_id) == signed, (
            "the immediately following read must agree with the write's own "
            "response, with no settling delay"
        )

        deposits, meta = validate_paginated(
            api.list_earnest_money_deposits(
                TITLE_AGENT_1, {"purchase_contract_id": scenario.pc_id}
            )
        )
        assert_pagination_meta(meta, total_count=1)
        assert_earnest_money_deposit(
            deposits[0], status="HELD", amount_cents=500000, held_cents=500000
        )
        assert_seller_lead(
            read_lead(api, scenario.lead_id, scenario.w_id), status="UNDER_CONTRACT"
        )
