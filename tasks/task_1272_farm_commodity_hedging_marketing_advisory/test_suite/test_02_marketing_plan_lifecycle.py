"""Marketing plan lifecycle: baseline states, activation gates, suspend/resume
cycle, close preconditions, and optimistic concurrency."""
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    make_grower_headers,
    assert_marketing_plan,
    create_operation,
    create_baseline_for,
    certify_baseline,
    create_agreement_for,
    activate_agreement,
    create_active_agreement,
    create_plan_for,
    create_active_plan,
    create_approved_buyer,
    setup_operation_with_active_plan,
    setup_active_plan_with_buyer,
    create_flat_contract,
)

ADVISOR = TEST_USERS["advisor_headers"]
COMPLIANCE = TEST_USERS["compliance_headers"]


class TestBaselineStates:
    def test_baseline_initial_state_provisional(self, api):
        """PRD §3.1: "A baseline starts `PROVISIONAL`."

        Design: Corner/state_machines/baseline_initial_state_provisional
        """
        op = create_operation(
            name="Init Farm", primary_commodity="CORN", crop_year=2026, risk_profile="BALANCED"
        )
        baseline = create_baseline_for(op, planted_acres=100, aph_yield_bushels=200, trend_yield_bushels=205)
        assert baseline["status"] == "PROVISIONAL", (
            f"new baseline must start PROVISIONAL, got {baseline['status']}"
        )

    def test_superseded_baseline_certify_returns_409(self, api):
        """PRD §3.1: "Creating a new baseline for an operation automatically
        supersedes that operation's existing non-`SUPERSEDED` baseline, whether
        that prior baseline is `PROVISIONAL` or `CERTIFIED`."
        PRD §2.6: "Sixth, the target resource must be in a from-state that
        permits the requested transition, producing `ERR_INVALID_STATE`."

        Design: Corner/state_machines/superseded_baseline_certify_returns_409
        """
        op = create_operation(
            name="Term Farm", primary_commodity="CORN", crop_year=2026, risk_profile="BALANCED"
        )
        b1 = create_baseline_for(op, planted_acres=100, aph_yield_bushels=200, trend_yield_bushels=205)
        b2 = create_baseline_for(op, planted_acres=110, aph_yield_bushels=200, trend_yield_bushels=205)
        first = get_success_data(api.get_baseline(b1["id"], ADVISOR))
        assert first["status"] == "SUPERSEDED", "creation of B2 must supersede B1"
        assert b2["status"] == "PROVISIONAL"
        resp = api.certify_baseline(b1["id"], make_grower_headers(op["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        after = get_success_data(api.get_baseline(b1["id"], ADVISOR))
        assert after["status"] == "SUPERSEDED", "SUPERSEDED is terminal — no status change"


class TestActivationGates:
    def test_activate_plan_without_active_agreement_rejected(self, api):
        """PRD §3.3: "the operation must have a governing `AdvisoryAgreement`
        in `ACTIVE` status (otherwise `ERR_AGREEMENT_NOT_ACTIVE`)".

        Design: Corner/validations/activate_plan_without_active_agreement_rejected
        """
        op = create_operation(
            name="NoAg Farm", primary_commodity="CORN", crop_year=2026, risk_profile="BALANCED"
        )
        baseline = create_baseline_for(op, planted_acres=100, aph_yield_bushels=200, trend_yield_bushels=205)
        certify_baseline(baseline, op["id"])
        agreement = create_agreement_for(op["id"], fee_type="FLAT_ANNUAL", flat_annual_fee=1000)
        get_success_data(api.submit_agreement(agreement["id"], ADVISOR))  # never signed
        plan = get_success_data(
            api.create_plan(
                {"operation_id": op["id"], "baseline_id": baseline["id"], "max_priced_pct": 0.80},
                ADVISOR,
            )
        )
        resp = api.activate_plan(plan["id"], ADVISOR)
        validate_error(resp, ApiErrorId.ERR_AGREEMENT_NOT_ACTIVE)
        after = get_success_data(api.get_plan(plan["id"], ADVISOR))
        assert after["status"] == "DRAFT", "plan must stay DRAFT when the agreement gate fails"

    def test_activate_plan_with_uncertified_baseline_rejected(self, api):
        """PRD §3.3: "the plan's `baseline_id` must reference a `CERTIFIED`
        baseline (otherwise `ERR_BASELINE_NOT_CERTIFIED`)".

        Design: Corner/validations/activate_plan_with_uncertified_baseline_rejected
        """
        op = create_operation(
            name="NoCert Farm", primary_commodity="CORN", crop_year=2026, risk_profile="BALANCED"
        )
        baseline = create_baseline_for(op, planted_acres=100, aph_yield_bushels=200, trend_yield_bushels=205)
        # baseline left PROVISIONAL
        create_active_agreement(op["id"], fee_type="FLAT_ANNUAL", flat_annual_fee=1000)
        plan = get_success_data(
            api.create_plan(
                {"operation_id": op["id"], "baseline_id": baseline["id"], "max_priced_pct": 0.80},
                ADVISOR,
            )
        )
        resp = api.activate_plan(plan["id"], ADVISOR)
        validate_error(resp, ApiErrorId.ERR_BASELINE_NOT_CERTIFIED)
        after = get_success_data(api.get_plan(plan["id"], ADVISOR))
        assert after["status"] == "DRAFT", "plan must stay DRAFT when the baseline gate fails"


class TestSuspendResumeCycle:
    def test_suspended_plan_rejects_contract_creation(self, api):
        """PRD §3.3: "While a plan is `SUSPENDED`, price-target triggers are
        skipped for that plan, and both sales-contract creation and
        recommendation acceptance against the plan are rejected with
        `ERR_INVALID_STATE`."

        Design: Difficulty/non_linear_state_machine/marketing_plan_suspend_resume_cycle
        """
        ctx = setup_active_plan_with_buyer(
            name="Cycle Farm", risk_profile="AGGRESSIVE", max_priced_pct=1.00
        )
        plan_id = ctx["plan"]["id"]
        suspended = get_success_data(api.suspend_plan(plan_id, ADVISOR))
        assert suspended["status"] == "SUSPENDED"
        resp = api.create_contract(
            {
                "operation_id": ctx["operation"]["id"],
                "plan_id": plan_id,
                "buyer_id": ctx["buyer"]["id"],
                "contract_type": "FLAT_PRICE",
                "bushels": 1000,
                "fixed_price": 4.50,
                "delivery_window_start": "2026-10-01",
                "delivery_window_end": "2026-11-01",
            },
            ADVISOR,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_cycle_traversed_twice_and_plan_not_degraded(self, api):
        """PRD §3.3: "The cycle `ACTIVE` → `SUSPENDED` → `ACTIVE` is permitted
        without limit." and "From `ACTIVE`, a plan may be suspended by either a
        `CommodityAdvisor` or a `ComplianceOfficer`, moving to `SUSPENDED`."

        Design: Difficulty/non_linear_state_machine/marketing_plan_suspend_resume_cycle
        """
        ctx = setup_active_plan_with_buyer(
            name="Cycle Farm", risk_profile="AGGRESSIVE", max_priced_pct=1.00
        )
        plan_id = ctx["plan"]["id"]
        assert ctx["plan"]["status"] == "ACTIVE"
        assert get_success_data(api.suspend_plan(plan_id, ADVISOR))["status"] == "SUSPENDED"
        assert get_success_data(api.resume_plan(plan_id, ADVISOR))["status"] == "ACTIVE"
        # Second leg: a ComplianceOfficer may also suspend.
        assert get_success_data(api.suspend_plan(plan_id, COMPLIANCE))["status"] == "SUSPENDED"
        assert get_success_data(api.resume_plan(plan_id, ADVISOR))["status"] == "ACTIVE"
        # The plan still accepts business after two full cycles.
        contract = create_flat_contract(ctx, bushels=1000, fixed_price=4.50)
        assert_marketing_plan(get_success_data(api.get_plan(plan_id, ADVISOR)))
        assert contract["fulfillment_status"] == "OPEN"

    def test_plan_close_blocked_with_open_contract(self, api):
        """PRD §3.3: "Closing is an advisor action from either `ACTIVE` or
        `SUSPENDED` to the terminal `CLOSED` state, permitted only when no
        `OPEN` or `PARTIALLY_DELIVERED` sales contract and no `OPEN` brokerage
        position remains for the plan."
        PRD §2.6: "Sixth, the target resource must be in a from-state that
        permits the requested transition, producing `ERR_INVALID_STATE`."

        Design: Corner/state_machines/plan_close_blocked_with_open_contract
        """
        ctx = setup_active_plan_with_buyer(
            name="CloseBlock Farm", risk_profile="AGGRESSIVE", max_priced_pct=1.00
        )
        create_flat_contract(ctx, bushels=5000, fixed_price=4.50)
        resp = api.close_plan(ctx["plan"]["id"], ADVISOR)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        plan = get_success_data(api.get_plan(ctx["plan"]["id"], ADVISOR))
        assert plan["status"] == "ACTIVE", "plan must remain ACTIVE while an OPEN contract exists"


class TestOptimisticConcurrency:
    def test_plan_amend_stale_version_rejected_occ(self, api):
        """PRD §2.5: "A request to amend a `MarketingPlan` must carry
        `expected_marketing_plan_version`, a non-optional field carrying the
        client's last observed `version` of the plan. If another amendment has
        advanced the plan's `version` since the client last read it — for
        example, a lowered `max_priced_pct` that the stale write would
        otherwise restore — the request is rejected with `ERR_STALE_VERSION`
        (HTTP 412), preventing the client from overwriting a change it has not
        observed."

        Design: Corner/cross_cutting_complexity_layers/plan_amend_stale_version_rejected_occ
        """
        op = create_operation(
            name="OCC Farm 1", primary_commodity="CORN", crop_year=2026, risk_profile="BALANCED"
        )
        baseline = create_baseline_for(op, planted_acres=100, aph_yield_bushels=200, trend_yield_bushels=205)
        plan = get_success_data(
            api.create_plan(
                {"operation_id": op["id"], "baseline_id": baseline["id"], "max_priced_pct": 0.80},
                ADVISOR,
            )
        )
        first = api.amend_plan(
            plan["id"],
            {"expected_marketing_plan_version": plan["version"], "max_priced_pct": 0.75},
            ADVISOR,
        )
        amended = validate_success(first, expected_status=200)
        assert amended["version"] == plan["version"] + 1, "amend must increment the plan version by 1"
        assert amended["max_priced_pct"] == 0.75
        replay = api.amend_plan(
            plan["id"],
            {"expected_marketing_plan_version": plan["version"], "max_priced_pct": 0.70},
            ADVISOR,
        )
        validate_error(replay, ApiErrorId.ERR_STALE_VERSION)
        after = get_success_data(api.get_plan(plan["id"], ADVISOR))
        assert after["max_priced_pct"] == 0.75, "stale write must not overwrite the intervening amendment"

    def test_baseline_create_stale_operation_rejected_occ(self, api):
        """PRD §2.5: "Because a successful baseline creation supersedes the
        operation's existing non-superseded baseline, the create request must
        carry `expected_operation_version` matching the target
        `GrowerOperation`'s current `version`. If the operation's version has
        advanced since the client last observed it, the create is rejected with
        `ERR_STALE_VERSION` (HTTP 412): the client's premise about which
        baseline it would supersede is stale."

        Design: Corner/cross_cutting_complexity_layers/baseline_create_stale_operation_rejected_occ
        """
        op = create_operation(
            name="OCC Farm 2", primary_commodity="CORN", crop_year=2026, risk_profile="BALANCED"
        )
        b1 = create_baseline_for(op, planted_acres=100, aph_yield_bushels=200, trend_yield_bushels=205)
        fresh = get_success_data(api.get_operation(op["id"], ADVISOR))
        assert fresh["version"] == op["version"] + 1, "baseline create must bump the operation version"
        stale = api.create_baseline(
            {
                "operation_id": op["id"],
                "planted_acres": 110,
                "aph_yield_bushels": 200,
                "trend_yield_bushels": 205,
                "expected_operation_version": op["version"],  # pre-supersede version
            },
            ADVISOR,
        )
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION)
        still = get_success_data(api.get_baseline(b1["id"], ADVISOR))
        assert still["status"] == "PROVISIONAL", "a stale create must not supersede anything"
        retry = api.create_baseline(
            {
                "operation_id": op["id"],
                "planted_acres": 110,
                "aph_yield_bushels": 200,
                "trend_yield_bushels": 205,
                "expected_operation_version": fresh["version"],
            },
            ADVISOR,
        )
        b2 = validate_success(retry, expected_status=201)
        assert b2["status"] == "PROVISIONAL"
        superseded = get_success_data(api.get_baseline(b1["id"], ADVISOR))
        assert superseded["status"] == "SUPERSEDED", (
            "retry with the fresh version succeeds and supersedes the prior baseline"
        )

    def test_version_increments_on_each_mutation(self, api):
        """PRD §2.4: "The `version` field is an integer that increments with
        every mutation to the resource and provides the basis for optimistic
        concurrency control."
        PRD §3.3: "A successful amendment recomputes `coverage_cap_bushels` and
        increments the plan's `version` by one; a stale version is rejected
        with `ERR_STALE_VERSION`."

        Design: Corner/cross_cutting_complexity_layers/version_increments_on_each_mutation
        """
        # Fresh operation with the full activation chain met (certified
        # baseline + ACTIVE acknowledged agreement), then a fresh DRAFT plan so
        # create -> amend -> activate -> suspend -> resume is observable from
        # version 1.
        ctx = setup_operation_with_active_plan(
            name="Ver Farm", risk_profile="AGGRESSIVE", max_priced_pct=1.00
        )
        plan2 = get_success_data(
            api.create_plan(
                {
                    "operation_id": ctx["operation"]["id"],
                    "baseline_id": ctx["baseline"]["id"],
                    "max_priced_pct": 1.00,
                },
                ADVISOR,
            )
        )
        v1 = plan2["version"]
        assert v1 == 1, f"create must start at version 1, got {v1}"
        amended = get_success_data(
            api.amend_plan(plan2["id"], {"expected_marketing_plan_version": v1, "max_priced_pct": 0.95}, ADVISOR)
        )
        assert amended["version"] == 2, "amend: 1 -> 2"
        activated = get_success_data(api.activate_plan(plan2["id"], ADVISOR))
        assert activated["version"] == 3, "activate: 2 -> 3"
        suspended = get_success_data(api.suspend_plan(plan2["id"], ADVISOR))
        assert suspended["version"] == 4, "suspend: 3 -> 4"
        resumed = get_success_data(api.resume_plan(plan2["id"], ADVISOR))
        assert resumed["version"] == 5, "resume: 4 -> 5"
