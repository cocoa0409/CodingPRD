"""Corner (calculations) — boundary-precise variants not covered by the
difficulty-rule pairings."""
from test_helpers import (
    validate_error,
    get_success_data,
    set_clock,
    setup_active_contract_with_item,
    file_claim,
    assess_claim,
    dispatch_claim,
    resolve_claim,
    get_dispatch_for_claim,
    start_dispatch,
    complete_dispatch,
    make_customer_headers,
    make_dispatcher_headers,
    assess_claim_payload,
)


_DISPATCHER = make_dispatcher_headers()


class TestProvisionalCopayUnderCap:

    def test_assess_under_cap_provisional_equals_service_fee(self, api):
        """PRD §3.7: "The provisional co-pay always assumes the Trip Charge will
        apply, because at assessment time the return-visit evaluation has not yet
        happened; it therefore reads `service_fee_cents` directly from the package."
        PRD §3.7: "Subtract the package's `copay_cap_cents` from the repair amount.
        If the difference is zero or negative, the excess above the cap is zero;
        otherwise the excess equals that difference."

        Design: Corner/calculations/provisional_copay_under_cap_equals_service_fee_only
        """
        package, customer, contract, item = setup_active_contract_with_item()
        claim = file_claim(contract, customer, item, issue="Under cap")
        # R = 20000 <= C = 25000 → excess 0 → above_cap = 0; provisional = SF = 7500.
        result = assess_claim(claim, 20_000)
        assert result["provisional_copay_cents"] == 7500


class TestFinalCopayReturnVisitUnderCap:

    def test_return_visit_under_cap_final_copay_is_zero(self, api):
        """PRD §3.7: "Return visit, under cap. When `is_return_visit` is true and
        the actual repair amount is at most `copay_cap_cents`, the final co-pay is
        zero: the Trip Charge is waived and there is no excess to share."

        Design: Corner/calculations/final_copay_return_visit_under_cap_equals_zero
        """
        package, customer, contract, item = setup_active_contract_with_item(
            activate_at="2026-01-01T00:00:00Z",
        )
        # First claim, resolved → stamps last_dispatch_completed_utc on item.
        c1 = file_claim(contract, customer, item, issue="First")
        assess_claim(c1, 18_000)
        set_clock("2026-02-01T08:00:00Z")
        dispatch_claim(c1, "tech-A", "2026-02-01T09:00:00Z")
        d1 = get_dispatch_for_claim(c1["id"])
        set_clock("2026-02-01T09:30:00Z")
        start_dispatch(d1)
        set_clock("2026-02-01T10:00:00Z")
        complete_dispatch(d1)
        resolve_claim(c1, 18_000)
        # Second claim inside the 30-day return-visit window with R=18000 < C=25000.
        set_clock("2026-02-10T12:00:00Z")
        c2 = file_claim(contract, customer, item, issue="Within window")
        assess_claim(c2, 18_000)
        dispatch_claim(c2, "tech-B", "2026-02-10T15:00:00Z")
        d2 = get_dispatch_for_claim(c2["id"])
        set_clock("2026-02-10T15:30:00Z")
        start_dispatch(d2)
        complete_dispatch(d2)
        resolved = resolve_claim(c2, 18_000)
        assert resolved["final_copay_cents"] == 0


class TestIsReturnVisitNoPriorCompletion:

    def test_first_visit_returns_false_with_full_service_fee_pinned(self, api):
        """PRD §3.5: "When `last_dispatch_completed_utc` is null — i.e., there has
        never been a completed dispatch on this item — the result is unconditionally
        false: this is a first visit."
        PRD §3.5: "when it is false, `service_fee_charged_cents` is set to the
        package's `service_fee_cents`."

        Design: Corner/calculations/is_return_visit_no_prior_completion_returns_false
        """
        package, customer, contract, item = setup_active_contract_with_item(
            activate_at="2026-01-01T00:00:00Z",
            category="DRYER",
        )
        claim = file_claim(contract, customer, item, issue="First ever")
        assess_claim(claim, 30_000)
        # Dispatch — clock anywhere is fine because scheduled_utc is forward.
        dispatched = dispatch_claim(claim, "tech-N", "2030-01-01T10:00:00Z")
        # No prior completion → is_return_visit must be false.
        assert dispatched["is_return_visit"] is False
        # SF pinned to package.service_fee_cents = 7500 (the default).
        assert dispatched["service_fee_charged_cents"] == 7500


class TestPreExistingExcludedOnAssess:

    def test_assess_against_pre_existing_item_returns_error(self, api):
        """PRD §3.3: "A covered item whose `pre_existing_flag` is true cannot be
        assessed for repair: a claim filed against such an item can be submitted
        but, at the assessment step, will be rejected with `ERR_PRE_EXISTING_EXCLUDED`."

        Design: Corner/calculations/error_pre_existing_excluded_on_assess
        """
        package, customer, contract, item = setup_active_contract_with_item(
            activate_at="2026-01-01T00:00:00Z",
            category="REFRIGERATOR",
            pre_existing_flag=True,
        )
        claim = file_claim(contract, customer, item, issue="Was already broken")
        res = api.assess_claim(claim["id"], assess_claim_payload(10_000), _DISPATCHER)
        validate_error(res, "ERR_PRE_EXISTING_EXCLUDED")
