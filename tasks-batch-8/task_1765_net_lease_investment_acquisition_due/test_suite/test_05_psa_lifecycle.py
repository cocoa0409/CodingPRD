"""Purchase agreement drafting, execution side effects, field ranges,
earnest-money floor, the amendment loop, and terminal-state lockdown."""
from test_helpers import (
    ApiErrorId,
    amend_psa_payload,
    assert_ts_prefix,
    create_psa,
    create_psa_payload,
    get_deal,
    setup_psa_executed,
    setup_psa_pending,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    validate_success,
)


class TestPsaExecutionSideEffects:
    def test_psa_execute_side_effects_create_eight_milestones(
            self, api, analyst_headers, dd_officer_headers):
        """PRD §3.4: "In the same atomic step, the system auto-creates eight
        diligence milestones — one per `milestone_type`: `TITLE_REVIEW`,
        `SURVEY_REVIEW`, `ENVIRONMENTAL`, `PCA`, `ESTOPPEL_COLLECTION`,
        `SNDA_COLLECTION`, `FINANCING_COMMITMENT`, and `FINAL_WALKTHROUGH` —
        each in `PENDING` with its `due_date` set to the deal's
        `dd_period_end`."
        PRD §3.4: "On execution the agreement's `executed_at` is stamped with
        the logical clock's current instant, the deal's `dd_period_end` is
        computed as `executed_at` plus `dd_period_days`, and the deal's
        `financing_contingency_end` is `executed_at` plus
        `financing_contingency_days`."

        Design: Corner/endpoints/psa_execute_side_effects_create_eight_milestones
        """
        ctx = setup_psa_pending(deal_name="SEDeal")
        deal_id = ctx["deal"]["id"]
        version_before = get_deal(deal_id)["version"]
        psa = create_psa(deal_id, dd_period_days=30,
                         financing_contingency_days=20)

        executed = validate_success(
            api.execute_purchase_agreement(deal_id, psa["id"],
                                           analyst_headers))
        assert executed["status"] == "EXECUTED"
        assert_ts_prefix(executed["executed_at"], "2026-08-01T00:00:00")

        milestones, _meta = validate_paginated(
            api.list_milestones(deal_id, dd_officer_headers,
                                params={"limit": 100}))
        assert len(milestones) == 8, (
            f"Exactly 8 milestones auto-created, got {len(milestones)}")
        types = sorted(m["milestone_type"] for m in milestones)
        assert types == sorted(
            ["TITLE_REVIEW", "SURVEY_REVIEW", "ENVIRONMENTAL", "PCA",
             "ESTOPPEL_COLLECTION", "SNDA_COLLECTION", "FINANCING_COMMITMENT",
             "FINAL_WALKTHROUGH"])
        for m in milestones:
            assert m["status"] == "PENDING"
            assert_ts_prefix(m["due_date"], "2026-08-31T00:00:00")

        deal = get_deal(deal_id)
        assert_ts_prefix(deal["dd_period_end"], "2026-08-31T00:00:00")
        assert_ts_prefix(deal["financing_contingency_end"],
                         "2026-08-21T00:00:00")
        assert deal["pinned_underwriting_model_id"] == ctx["model"]["id"]
        assert deal["version"] == version_before + 1, (
            "PSA execution increments the deal's version by one")
        assert deal["posture"] == "DD_OPEN"
        assert deal["status"] == "PSA_EXECUTED"

    def test_immediate_consistency_cascade_visible_in_same_request(
            self, api, analyst_headers, dd_officer_headers):
        """PRD §3.4: "On execution the agreement's `executed_at` is stamped
        with the logical clock's current instant, the deal's `dd_period_end`
        is computed as `executed_at` plus `dd_period_days`, and the deal's
        `financing_contingency_end` is `executed_at` plus
        `financing_contingency_days`."
        PRD §3.4: "The deal's `pinned_underwriting_model_id` is set to the
        latest approved model per §2.11, the deal moves to `PSA_EXECUTED`,
        its posture becomes `DD_OPEN`, and its `version` increments."
        PRD §3.4: "In the same atomic step, the system auto-creates eight
        diligence milestones"

        Design: Corner/consistency_model/immediate_consistency_cascade_visible_in_same_request
        """
        ctx = setup_psa_pending(deal_name="ImmDeal")
        deal_id = ctx["deal"]["id"]
        psa = create_psa(deal_id, dd_period_days=30,
                         financing_contingency_days=20)

        # The execute response itself already reflects the cascade.
        executed = validate_success(
            api.execute_purchase_agreement(deal_id, psa["id"],
                                           analyst_headers))
        assert executed["status"] == "EXECUTED"
        assert_ts_prefix(executed["executed_at"], "2026-08-01T00:00:00")

        # An immediate read observes deal status and milestones — no lag.
        deal = validate_success(api.get_deal(deal_id, analyst_headers))
        assert deal["status"] == "PSA_EXECUTED"
        milestones, meta = validate_paginated(
            api.list_milestones(deal_id, dd_officer_headers,
                                params={"limit": 100}))
        assert meta["total_count"] == 8
        assert all(m["status"] == "PENDING" for m in milestones)


class TestPsaFieldRanges:
    def test_psa_dd_period_days_out_of_range(self, api, analyst_headers):
        """PRD §3.4: "The diligence period must be at least 15 and at most
        120 days; the financing contingency must be at least 0 and at most
        the diligence period plus 30 days; range violations are
        `ERR_FIELD_CONSTRAINT_VIOLATION`."

        Design: Corner/validations/psa_dd_period_days_out_of_range
        """
        ctx = setup_psa_pending(deal_name="DDRangeDeal")
        deal_id = ctx["deal"]["id"]

        low = api.create_purchase_agreement(
            deal_id, create_psa_payload(dd_period_days=10), analyst_headers)
        validate_error(low, ApiErrorId.ERR_FIELD_CONSTRAINT_VIOLATION)

        high = api.create_purchase_agreement(
            deal_id, create_psa_payload(dd_period_days=121), analyst_headers)
        validate_error(high, ApiErrorId.ERR_FIELD_CONSTRAINT_VIOLATION)

        floor = api.create_purchase_agreement(
            deal_id, create_psa_payload(dd_period_days=15), analyst_headers)
        psa = validate_success(floor, 201)
        assert psa["dd_period_days"] == 15, (
            "The 15-day floor is inclusive")

    def test_financing_contingency_days_capped_by_dd_period(
            self, api, analyst_headers):
        """PRD §3.4: "the financing contingency must be at least 0 and at
        most the diligence period plus 30 days; range violations are
        `ERR_FIELD_CONSTRAINT_VIOLATION`."

        Design: Corner/validations/financing_contingency_days_capped_by_dd_period
        """
        ctx = setup_psa_pending(deal_name="FCDaysDeal")
        deal_id = ctx["deal"]["id"]

        over = api.create_purchase_agreement(
            deal_id,
            create_psa_payload(dd_period_days=30,
                               financing_contingency_days=61),
            analyst_headers)
        validate_error(over, ApiErrorId.ERR_FIELD_CONSTRAINT_VIOLATION)

        at_cap = api.create_purchase_agreement(
            deal_id,
            create_psa_payload(dd_period_days=30,
                               financing_contingency_days=60),
            analyst_headers)
        psa = validate_success(at_cap, 201)
        assert psa["financing_contingency_days"] == 60, (
            "dd_period_days + 30 is the inclusive cap")


class TestEarnestMoneyFloor:
    def test_error_earnest_money_insufficient_triggerable(
            self, api, analyst_headers):
        """PRD §3.4: "the `earnest_money_cents` must be at least one percent
        of the PSA price (else `ERR_EARNEST_MONEY_INSUFFICIENT`, HTTP 422)"

        Design: Corner/errors/error_earnest_money_insufficient_triggerable
        """
        ctx = setup_psa_pending(deal_name="EMDeal")
        deal_id = ctx["deal"]["id"]
        # 1% of 15,000,000 is 150,000; 149,999 is below the floor.
        psa_low = create_psa(deal_id, earnest_money_cents=149999)
        blocked = api.execute_purchase_agreement(deal_id, psa_low["id"],
                                                 analyst_headers)
        validate_error(blocked, ApiErrorId.ERR_EARNEST_MONEY_INSUFFICIENT)

        # Exactly one percent passes the floor (inclusive).
        psa_exact = create_psa(deal_id, earnest_money_cents=150000)
        executed = validate_success(api.execute_purchase_agreement(
            deal_id, psa_exact["id"], analyst_headers))
        assert executed["status"] == "EXECUTED"


class TestPsaAmendmentLoop:
    def _setup_amend_loop(self):
        ctx = setup_psa_executed(
            deal_name="AmendLoopDeal", purchase_price_cents=25000000,
            earnest_money_cents=500000, lease_rent_cents=1500000,
            lease_expiration="2037-01-01T00:00:00Z",
            dd_period_days=60, financing_contingency_days=45,
            property_overrides={"address": "5 Amend Blvd",
                                "property_type": "INDUSTRIAL",
                                "rentable_sqft": 40000, "year_built": 2018},
            tenant_overrides={"legal_name": "AmendTenant"})
        return ctx

    def test_amend_retrades_price_and_cascades_ltv_withdrawal(
            self, api, analyst_headers, capital_markets_headers):
        """PRD §3.4: "An amendment increments `amendment_count`, updates the
        deal's `purchase_price_cents` atomically to the new price, and
        increments the agreement's `version`."
        PRD §3.4: "If the new price pushes a `SUBMITTED` financing
        application's loan above sixty-five percent of that price, the
        application cascades to `WITHDRAWN` in the same request"

        Design: Difficulty/non_linear_state_machine/deal_psa_branching_with_amend_loop_on_purchase_agreement_entity
        """
        ctx = self._setup_amend_loop()
        deal_id = ctx["deal"]["id"]
        psa = ctx["psa"]

        app = validate_success(api.create_financing_application(
            deal_id,
            {"loan_type": "NEW_LOAN", "loan_amount_cents": 15000000,
             "interest_rate_bps": 600, "amortization_months": 0},
            capital_markets_headers), 201)
        get_success = validate_success(api.submit_financing_application(
            deal_id, app["id"], capital_markets_headers))
        assert get_success["status"] == "SUBMITTED"

        psa_now = validate_success(
            api.get_purchase_agreement(deal_id, psa["id"], analyst_headers))
        amended = validate_success(api.amend_purchase_agreement(
            deal_id, psa["id"],
            amend_psa_payload(psa_now["version"], 22000000, 500000),
            analyst_headers))
        assert amended["status"] == "AMENDED"
        assert amended["amendment_count"] == 1

        deal = get_deal(deal_id)
        assert deal["purchase_price_cents"] == 22000000, (
            "The retrade updates the deal price atomically")

        app_after = validate_success(api.get_financing_application(
            deal_id, app["id"], capital_markets_headers))
        # 15,000,000 > 65% of 22,000,000 (= 14,300,000): cascade fires.
        assert app_after["status"] == "WITHDRAWN"

    def test_amend_with_stale_psa_version_rejected(self, api,
                                                   analyst_headers):
        """PRD §2.9: "Amending a purchase agreement likewise requires
        `expected_psa_version` matching the purchase agreement's current
        `version`; a mismatch is rejected with `ERR_STALE_PSA_VERSION`
        (HTTP 412)"

        Design: Difficulty/non_linear_state_machine/deal_psa_branching_with_amend_loop_on_purchase_agreement_entity
        """
        ctx = self._setup_amend_loop()
        deal_id = ctx["deal"]["id"]
        psa_id = ctx["psa"]["id"]

        psa_now = validate_success(
            api.get_purchase_agreement(deal_id, psa_id, analyst_headers))
        stale_version = psa_now["version"]
        first = validate_success(api.amend_purchase_agreement(
            deal_id, psa_id,
            amend_psa_payload(stale_version, 24000000, 500000),
            analyst_headers))
        assert first["status"] == "AMENDED"
        assert first["amendment_count"] == 1

        # The first amendment bumped the PSA version; reusing the captured
        # version is a stale write.
        second = api.amend_purchase_agreement(
            deal_id, psa_id,
            amend_psa_payload(stale_version, 23000000, 500000),
            analyst_headers)
        validate_error(second, ApiErrorId.ERR_STALE_PSA_VERSION)

    def test_occ_stale_psa_version_on_amend(self, api, analyst_headers):
        """PRD §2.9: "Amending a purchase agreement likewise requires
        `expected_psa_version` matching the purchase agreement's current
        `version`; a mismatch is rejected with `ERR_STALE_PSA_VERSION`
        (HTTP 412), so a writer never amends terms on a stale view of the
        price."

        Design: Corner/cross_cutting_layers/occ_stale_psa_version_on_amend
        """
        ctx = setup_psa_executed(deal_name="OCCDeal2")
        deal_id = ctx["deal"]["id"]
        psa_id = ctx["psa"]["id"]

        psa_now = validate_success(
            api.get_purchase_agreement(deal_id, psa_id, analyst_headers))
        pv = psa_now["version"]
        first = validate_success(api.amend_purchase_agreement(
            deal_id, psa_id, amend_psa_payload(pv, 14500000, 250000),
            analyst_headers))
        assert first["status"] == "AMENDED"
        assert first["amendment_count"] == 1
        assert get_deal(deal_id)["purchase_price_cents"] == 14500000

        stale = api.amend_purchase_agreement(
            deal_id, psa_id, amend_psa_payload(pv, 14000000, 250000),
            analyst_headers)
        validate_error(stale, ApiErrorId.ERR_STALE_PSA_VERSION)


class TestDealTerminalStateLockdown:
    def test_deal_terminal_state_lockdown(self, api, analyst_headers,
                                          escrow_headers):
        """PRD §3.10: "Termination by the analyst is available from
        `DUE_DILIGENCE` or `CLEAR_TO_CLOSE` (and from `PSA_EXECUTED`); from
        any other state it is `ERR_DEAL_INVALID_STATE`."
        PRD §3.10: "When the `termination_reason` is `BUYER_DEFAULT`,
        `earnest_money_released` is set true — the deposit is forfeited to
        the seller."
        PRD §3.10: "Closing itself is performed by the `EscrowOfficer` and
        requires the posture to be `CLEAR_TO_CLOSE` (else
        `ERR_NOT_CLEAR_TO_CLOSE`, HTTP 422)"

        Design: Corner/state_machines/deal_terminal_state_lockdown
        """
        ctx = setup_psa_executed(deal_name="TermDeal")
        deal_id = ctx["deal"]["id"]

        terminated = validate_success(api.terminate_deal(
            deal_id, "BUYER_DEFAULT", analyst_headers))
        assert terminated["status"] == "TERMINATED"
        deal = get_deal(deal_id)
        assert deal["earnest_money_released"] is True, (
            "BUYER_DEFAULT forfeits the deposit to the seller")
        assert deal["posture"] == "TERMINATED"

        again = api.terminate_deal(deal_id, "DD_FAILURE", analyst_headers)
        validate_error(again, ApiErrorId.ERR_DEAL_INVALID_STATE)

        close = api.close_deal(deal_id, escrow_headers)
        assert close.status_code in (409, 422)
        validate_error_is_one_of(
            close, [ApiErrorId.ERR_DEAL_INVALID_STATE,
                    ApiErrorId.ERR_NOT_CLEAR_TO_CLOSE])
