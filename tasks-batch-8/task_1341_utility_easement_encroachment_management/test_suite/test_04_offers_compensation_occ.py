"""Acquisition offers: compensation ledger, title gate, and optimistic
concurrency on case-sensitive writes."""
from test_helpers import (
    ROW_AGENT,
    ROW_AGENT_CREATOR,
    ApiErrorId,
    add_document,
    add_encroachment,
    add_offer,
    api_client,
    assert_acquisition_offer,
    assert_compensation_invariant,
    begin_mapping,
    complete_title_search,
    counter_offer,
    create_active_case,
    create_case,
    get_case,
    get_case_version,
    get_offer,
    get_success_data,
    order_title_search,
    record_document,
    tender_offer,
    validate_error,
    validate_success,
)


class TestOfferComputation:

    def test_computed_fields_input_ignored_on_offer_create(self):
        """PRD section 3.5: "At creation the system computes
        `base_compensation_cents` as the `offered_area_sqft` multiplied by the
        case's `fair_market_value_per_sqft` and by 100, rounded half-up to
        whole cents; initializes `negotiated_compensation_cents` to that base;
        computes `total_compensation_cents` as the negotiated amount plus
        `severance_damages_cents`; initializes `negotiation_round` to 0; and
        derives `requires_director_approval`, which is true exactly when
        `total_compensation_cents` reaches or exceeds the configured
        `DIRECTOR_APPROVAL_THRESHOLD_CENTS`."

        100 sqft at FMV 10 -> 100 * 10 * 100 = 100000 cents, regardless of the
        client-supplied base_compensation_cents.

        Design: Corner/entities/computed_fields_input_ignored_on_offer_create
        """
        case, _doc = create_active_case(case_code="ESM-C06", parcel_id="P-C06")
        payload = {
            "landowner_name": "X",
            "landowner_contact": "x@example.com",
            "offered_area_sqft": 100,
            "severance_damages_cents": 0,
            "base_compensation_cents": 999999,
        }
        resp = api_client.create_offer(case["id"], payload, ROW_AGENT_CREATOR)
        data = validate_success(resp, expected_status=201)
        assert_acquisition_offer(data)
        assert data["base_compensation_cents"] == 100000, (
            f"computed base must be 100000, got {data['base_compensation_cents']}"
        )
        assert data["negotiated_compensation_cents"] == 100000
        assert data["total_compensation_cents"] == 100000

    def test_base_compensation_rounding(self):
        """PRD section 2.6: "Wherever a monetary calculation produces a
        fractional cent — notably the base compensation computation, which
        multiplies square footage by a per-square-foot value and by 100 — the
        result is rounded half-up to the nearest whole cent."

        333.33 sqft at FMV 3.33 -> 333.33 * 3.33 * 100 = 110998.89 ->
        round-half-up to 110999 cents.

        Design: Corner/calculations/base_compensation_rounding
        """
        case, _doc = create_active_case(
            case_code="ESM-CAL2", parcel_id="P-CAL2",
            fair_market_value_per_sqft=3.33, acquisition_budget_cents=100000000,
        )
        offer = add_offer(case["id"], landowner_name="R", offered_area_sqft=333.33,
                          severance_damages_cents=0)
        assert offer["base_compensation_cents"] == 110999, (
            f"half-up rounding must yield 110999, got {offer['base_compensation_cents']}"
        )


class TestOfferTenderAndNegotiationLedger:

    def test_offer_ledger_after_tender_and_counter(self):
        """PRD section 3.5: "On success the tender commits funds:
        `compensation_committed_cents` increases by the offer's
        `total_compensation_cents`, `compensation_balance_cents` is recomputed,
        and `negotiation_deadline` is set to the tender instant plus the
        configured `NEGOTIATION_WINDOW_DAYS`."
        PRD section 3.5: "A counter increments `negotiation_round` by 1,
        overwrites `negotiated_compensation_cents` with the counter amount,
        recomputes `total_compensation_cents`, adjusts
        `compensation_committed_cents` by the delta between the new and old
        totals, and recomputes `requires_director_approval`."

        1000 sqft at FMV 10 -> base 1000000; severance 500000 -> tendered total
        1500000; counter to 1200000 -> total 1700000 on a 50000000 budget.

        Design: Difficulty/dual_variant_calc/offer_provisional_vs_final_compensation
        """
        case, _doc = create_active_case(case_code="ESM-001", parcel_id="P-001")
        offer = add_offer(case["id"], offered_area_sqft=1000, severance_damages_cents=500000)
        assert offer["base_compensation_cents"] == 1000000

        tender_offer(case["id"], offer["id"])
        counter_offer(case["id"], offer["id"], 1200000)

        offer_after = get_offer(case["id"], offer["id"])
        assert offer_after["base_compensation_cents"] == 1000000
        assert offer_after["negotiated_compensation_cents"] == 1200000
        assert offer_after["total_compensation_cents"] == 1700000
        assert offer_after["status"] == "COUNTERED"

        case_after = get_case(case["id"])
        assert case_after["compensation_committed_cents"] == 1700000
        assert case_after["compensation_balance_cents"] == 48300000

    def test_provisional_committed_view_during_negotiation(self):
        """PRD section 3.5: "`compensation_committed_cents` is always the sum
        of `total_compensation_cents` over exactly the offers in `TENDERED`,
        `COUNTERED`, or `ACCEPTED` status, and `compensation_balance_cents` is
        `acquisition_budget_cents` minus that sum."
        PRD section 3.5: "During negotiation the view is provisional — a
        tendered or countered offer's current negotiated total encumbers the
        budget — and rejected, withdrawn, or expired offers release their
        commitment back to the balance, while accepted offers remain committed
        until the case closes."

        After tender the provisional commitment is 1500000; the counter moves
        it to 1700000 by the delta.

        Design: Difficulty/dual_variant_calc/offer_provisional_vs_final_compensation
        """
        case, _doc = create_active_case(case_code="ESM-001b", parcel_id="P-001b")
        offer = add_offer(case["id"], offered_area_sqft=1000, severance_damages_cents=500000)
        tender_offer(case["id"], offer["id"])

        mid = get_case(case["id"])
        assert mid["compensation_committed_cents"] == 1500000, (
            f"tendered total 1000000 + 500000 must encumber 1500000, "
            f"got {mid['compensation_committed_cents']}"
        )
        assert mid["compensation_balance_cents"] == 48500000
        assert_compensation_invariant(mid)

        counter_offer(case["id"], offer["id"], 1200000)
        after = get_case(case["id"])
        assert after["compensation_committed_cents"] == 1700000
        assert_compensation_invariant(after)

    def test_compensation_balance_restored_after_tender_then_reject(self):
        """PRD section 3.5: "A landowner's refusal moves the offer from
        `TENDERED` or `COUNTERED` to `REJECTED_BY_OWNER` and subtracts its
        `total_compensation_cents` from `compensation_committed_cents`."
        PRD section 3.5: "During negotiation the view is provisional — a
        tendered or countered offer's current negotiated total encumbers the
        budget — and rejected, withdrawn, or expired offers release their
        commitment back to the balance, while accepted offers remain committed
        until the case closes."

        Design: Difficulty/compensating_invariant/compensation_balance_invariant_across_tender_reject
        """
        case, _doc = create_active_case(case_code="ESM-017", parcel_id="P-017")
        offer = add_offer(case["id"], offered_area_sqft=1000, severance_damages_cents=500000)
        tender_offer(case["id"], offer["id"])
        assert get_case(case["id"])["compensation_committed_cents"] == 1500000

        get_success_data(api_client.reject_offer(case["id"], offer["id"], ROW_AGENT))

        after = get_case(case["id"])
        assert after["compensation_committed_cents"] == 0
        assert after["compensation_balance_cents"] == 50000000
        assert_compensation_invariant(after)
        assert get_offer(case["id"], offer["id"])["status"] == "REJECTED_BY_OWNER"

    def test_compensation_invariant_holds_at_every_step(self):
        """PRD section 3.5: "`compensation_committed_cents` is always the sum
        of `total_compensation_cents` over exactly the offers in `TENDERED`,
        `COUNTERED`, or `ACCEPTED` status, and `compensation_balance_cents` is
        `acquisition_budget_cents` minus that sum."

        The invariant is checked after creation, after tender, and after
        rejection of the same offer.

        Design: Difficulty/compensating_invariant/compensation_balance_invariant_across_tender_reject
        """
        case, _doc = create_active_case(case_code="ESM-017b", parcel_id="P-017b")
        assert_compensation_invariant(get_case(case["id"]))
        offer = add_offer(case["id"], offered_area_sqft=1000, severance_damages_cents=500000)
        assert_compensation_invariant(get_case(case["id"]))
        tender_offer(case["id"], offer["id"])
        assert_compensation_invariant(get_case(case["id"]))
        get_success_data(api_client.reject_offer(case["id"], offer["id"], ROW_AGENT))
        final = get_case(case["id"])
        assert_compensation_invariant(final)
        assert final["compensation_committed_cents"] == 0
        assert final["compensation_balance_cents"] == 50000000


class TestOfferTitleGate:

    def _case_with_defective_title(self, case_code, parcel_id):
        """Case in MAPPING with a RECORDED document but a latest title search
        completed WITH_DEFECTS (title_cleared stays false)."""
        case = create_case(case_code=case_code, parcel_id=parcel_id)
        doc = add_document(case["id"])
        begin_mapping(case["id"])
        task = order_title_search(case["id"])
        complete_title_search(case["id"], task["id"], liens_found=0, defects_found=1)
        record_document(case["id"], doc["id"])
        return case, doc

    def test_activate_and_tender_both_blocked_when_title_not_cleared(self):
        """PRD section 3.1: "Activating monitoring moves `MAPPING →
        ACTIVE_MONITORING` and is the first enforcement of the title gate: it
        requires at least one `RECORDED` document (else
        `ERR_NO_RECORDED_DOCUMENT`) and a cleared title per the derivation
        above (else `ERR_TITLE_NOT_CLEARED`); on success it recomputes
        `title_cleared` and sets the case to `ACTIVE_MONITORING`."
        PRD section 3.5: "The substantive gates run in the pipeline order of
        §2.8: the case must be in `MAPPING`, `ACTIVE_MONITORING`, or
        `RESOLUTION_PENDING`; `title_cleared` must be true (else
        `ERR_TITLE_NOT_CLEARED`); segregation of duties forbids the user who
        created the offer from tendering it when `requires_director_approval`
        is true (else `ERR_NEGOTIATOR_CANNOT_APPROVE_OWN_OFFER`, 403); and the
        offer's `total_compensation_cents` must not exceed the case's current
        `compensation_balance_cents` (else `ERR_COMPENSATION_EXCEEDS_BUDGET`,
        402)."

        Design: Difficulty/cross_entity_state_dependency/offer_tender_requires_title_cleared
        """
        case, _doc = self._case_with_defective_title("ESM-013", "P-013")
        activate_resp = api_client.activate_monitoring(case["id"], ROW_AGENT)
        validate_error(activate_resp, ApiErrorId.ERR_TITLE_NOT_CLEARED, expected_status=409)

        offer = add_offer(case["id"], landowner_name="Z", offered_area_sqft=100,
                          severance_damages_cents=0)
        version = get_case_version(case["id"])
        tender_resp = api_client.tender_offer(
            case["id"], offer["id"], {"expected_case_version": version}, ROW_AGENT
        )
        validate_error(tender_resp, ApiErrorId.ERR_TITLE_NOT_CLEARED, expected_status=409)
        assert get_offer(case["id"], offer["id"])["status"] == "DRAFT"

    def test_tender_rejected_with_title_defects(self):
        """PRD section 3.1: "Completing a search with defects forces
        `title_cleared` to false and blocks any offer still in `DRAFT` on that
        case from being tendered until a clean search completes."

        Design: Difficulty/cross_entity_state_dependency/offer_tender_requires_title_cleared
        """
        case, _doc = self._case_with_defective_title("ESM-013b", "P-013b")
        assert get_case(case["id"])["title_cleared"] is False
        offer = add_offer(case["id"], landowner_name="Z", offered_area_sqft=100,
                          severance_damages_cents=0)
        version = get_case_version(case["id"])
        tender_resp = api_client.tender_offer(
            case["id"], offer["id"], {"expected_case_version": version}, ROW_AGENT
        )
        validate_error(tender_resp, ApiErrorId.ERR_TITLE_NOT_CLEARED, expected_status=409)
        assert get_offer(case["id"], offer["id"])["status"] == "DRAFT"


class TestOfferStateGate:

    def test_accept_draft_offer_rejected_despite_budget_pressure(self):
        """PRD section 3.5: "Operations that require the offer to be
        `TENDERED` or `COUNTERED` reject other states with
        `ERR_OFFER_NOT_TENDERED`."
        PRD section 2.8: "The system evaluates checks in the following fixed
        sequence, returning the first failure encountered"

        The DRAFT offer also would exceed the remaining balance if tendered,
        but the state check precedes fiscal adequacy in the pipeline, so the
        state error is the one returned.

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_fiscal_on_offer_tender
        """
        case, _doc = create_active_case(
            case_code="ESM-009", parcel_id="P-009", acquisition_budget_cents=1000000,
        )
        offer1 = add_offer(case["id"], landowner_name="A", offered_area_sqft=900,
                           severance_damages_cents=0)
        offer2 = add_offer(case["id"], landowner_name="B", offered_area_sqft=900,
                           severance_damages_cents=0)
        tender_offer(case["id"], offer1["id"])
        # Budget remaining is now 100000 while offer2's total is 900000, and
        # offer2 is DRAFT: the state error must be the one reported.
        resp = api_client.accept_offer(case["id"], offer2["id"], ROW_AGENT)
        validate_error(resp, ApiErrorId.ERR_OFFER_NOT_TENDERED, expected_status=409)

    def test_accept_draft_offer_rejected(self):
        """PRD section 3.5: "Operations that require the offer to be
        `TENDERED` or `COUNTERED` reject other states with
        `ERR_OFFER_NOT_TENDERED`."

        Isolated single-failure form: a DRAFT offer under no budget pressure.

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_fiscal_on_offer_tender
        """
        case, _doc = create_active_case(case_code="ESM-009b", parcel_id="P-009b")
        offer = add_offer(case["id"], landowner_name="A", offered_area_sqft=100,
                          severance_damages_cents=0)
        assert offer["status"] == "DRAFT"
        resp = api_client.accept_offer(case["id"], offer["id"], ROW_AGENT)
        validate_error(resp, ApiErrorId.ERR_OFFER_NOT_TENDERED, expected_status=409)


class TestOfferOptimisticConcurrency:

    def test_occ_stale_case_version_on_offer_tender(self):
        """PRD section 2.7: "On any of these three, if the supplied
        `expected_case_version` does not match the case's current `version` —
        because another writer has since recorded a document, reported an
        encroachment, or otherwise advanced the case — the request is rejected
        with `ERR_STALE_CASE_VERSION` (HTTP 412)."
        PRD section 2.5: "Because recomputation of a derived field is a
        mutation, an event such as an encroachment being reported against a
        case advances the case's `version` even though the client never wrote
        to the case directly."

        Design: Corner/cross_cutting_complexity_layers/occ_stale_case_version_on_offer_tender
        """
        case, doc = create_active_case(case_code="ESM-X01", parcel_id="P-X01")
        offer = add_offer(case["id"], landowner_name="O", offered_area_sqft=100,
                          severance_damages_cents=0)
        stale_version = get_case_version(case["id"])
        # Reporting an encroachment reconciles derived case state and advances
        # the case version, making the captured version stale.
        add_encroachment(case["id"], doc["id"], discovered_via="AERIAL_SURVEY",
                         encroachment_type="FENCE", encroachment_area_sqft=10,
                         depth_into_easement_ft=1, estimated_removal_cost_cents=10)
        resp = api_client.tender_offer(
            case["id"], offer["id"], {"expected_case_version": stale_version}, ROW_AGENT
        )
        validate_error(resp, ApiErrorId.ERR_STALE_CASE_VERSION, expected_status=412)

    def test_occ_correct_version_succeeds(self):
        """PRD section 2.7: "Each of these three operations requires a
        non-optional `expected_case_version` field in its request body,
        carrying the `version` of the parent case as the client last observed
        it"
        PRD section 3.5: "Tendering moves `DRAFT → TENDERED` and is the third
        case-sensitive write of §2.7: `expected_case_version` must match the
        case's current `version` or the tender is rejected with
        `ERR_STALE_CASE_VERSION` (412), and a successful tender increments the
        case's `version` by 1."

        Design: Corner/cross_cutting_complexity_layers/occ_correct_version_succeeds
        """
        case, _doc = create_active_case(case_code="ESM-X02", parcel_id="P-X02")
        offer = add_offer(case["id"], landowner_name="O", offered_area_sqft=100,
                          severance_damages_cents=0)
        version = get_case_version(case["id"])
        resp = api_client.tender_offer(
            case["id"], offer["id"], {"expected_case_version": version}, ROW_AGENT
        )
        data = validate_success(resp)
        assert data["status"] == "TENDERED"

    def test_scheduled_action_negotiation_deadline(self):
        """PRD section 3.5: "On success the tender commits funds:
        `compensation_committed_cents` increases by the offer's
        `total_compensation_cents`, `compensation_balance_cents` is recomputed,
        and `negotiation_deadline` is set to the tender instant plus the
        configured `NEGOTIATION_WINDOW_DAYS`."

        The deadline is the tender instant plus a positive window, so it must
        read strictly after the offer's created_at.

        Design: Corner/cross_cutting_complexity_layers/scheduled_action_negotiation_deadline
        """
        case, _doc = create_active_case(case_code="ESM-X04", parcel_id="P-X04")
        offer = add_offer(case["id"], landowner_name="O", offered_area_sqft=100,
                          severance_damages_cents=0)
        tender_offer(case["id"], offer["id"])
        after = get_offer(case["id"], offer["id"])
        assert after["negotiation_deadline"] is not None
        assert after["negotiation_deadline"] > after["created_at"], (
            f"negotiation_deadline {after['negotiation_deadline']} must be after "
            f"created_at {after['created_at']}"
        )

    def test_immediate_consistency_after_tender(self):
        """PRD section 2.4: "Whenever a child event changes one of these
        inputs, the server recomputes the derived value immediately, and each
        such recomputation is a mutation of the case: it refreshes the case's
        `updated_at` and increments its `version`."
        PRD section 3.5: "On success the tender commits funds:
        `compensation_committed_cents` increases by the offer's
        `total_compensation_cents`, `compensation_balance_cents` is recomputed,
        and `negotiation_deadline` is set to the tender instant plus the
        configured `NEGOTIATION_WINDOW_DAYS`."

        1000 sqft at FMV 10 -> total 1000000 committed against a 50000000
        budget, visible on the very next read.

        Design: Corner/consistency_model/immediate_consistency_after_tender
        """
        case, _doc = create_active_case(case_code="ESM-CM1", parcel_id="P-CM1")
        offer = add_offer(case["id"], landowner_name="I", offered_area_sqft=1000,
                          severance_damages_cents=0)
        tender_offer(case["id"], offer["id"])
        after = get_case(case["id"])
        assert after["compensation_committed_cents"] == 1000000
        assert after["compensation_balance_cents"] == 49000000
