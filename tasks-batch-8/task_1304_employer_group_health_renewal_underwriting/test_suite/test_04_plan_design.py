"""Benefit plan design: actuarial modeling, relativity, lifecycle gates."""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    api_client,
    create_broker,
    create_case,
    create_case_in_rating,
    create_case_in_census_received,
    add_modeled_plan,
    create_plan_design_payload,
    create_buydown_plan_payload,
    create_proposed_quote,
    TEST_USERS,
)

UW = TEST_USERS["underwriter_headers"]


class TestActuarialModeling:
    def test_actuarial_value_multi_factor_clamp_reference_plan(self):
        """PRD section 3.4: "A plan whose `is_reference_plan` flag is true always
        has `relativity_factor` of exactly 1.0 — it is the anchor."
        PRD section 3.4: "The result is clamped so it never falls below 0.50
        and never exceeds 1.00, then rounded half-up to four decimal places and
        stored as `actuarial_value`."

        Design: Difficulty/combinatorial_formula/actuarial_value_multi_factor_clamp
        """
        broker = create_broker()
        case, _ = create_case_in_rating(broker["id"])
        ref = add_modeled_plan(case["id"])
        assert ref["status"] == "MODELED"
        assert ref["actuarial_value"] == pytest.approx(1.0, abs=1e-9)
        assert ref["relativity_factor"] == pytest.approx(1.0, abs=1e-9)

    def test_actuarial_value_multi_factor_clamp_buydown_plan(self):
        """PRD section 3.4: "the individual deductible subtracts 0.02 of AV
        for every 50,000 cents ($500) of deductible — that is, the deductible in
        cents divided by 50,000, times 0.02."
        PRD section 3.4: "The whole intermediate value is then multiplied by
        0.60 plus 0.40 times the `coinsurance_pct`, so richer plan-paid
        coinsurance preserves more value."
        PRD section 3.4: "Out-of-pocket exposure above 200,000 cents ($2,000)
        individual subtracts a further 0.005 of AV per 100,000 cents ($1,000) of
        excess — the excess measured as the amount by which `oop_max_individual`
        exceeds 200,000 cents, floored at zero, divided by 100,000, times
        0.005."
        PRD section 3.4: "Copays shave value too: the sum of `copay_primary` and
        `copay_specialist`, divided by 100,000, times 0.01 is subtracted."
        PRD section 3.4: "the relativity is this plan's `actuarial_value` divided
        by the reference plan's `actuarial_value`, rounded half-up to four
        decimal places."

        Design: Difficulty/combinatorial_formula/actuarial_value_multi_factor_clamp
        """
        broker = create_broker()
        case, _ = create_case_in_rating(broker["id"])
        ref = add_modeled_plan(case["id"])
        resp = api_client.create_plan_design(
            case["id"], create_buydown_plan_payload(), UW
        )
        buydown = get_success_data(resp)
        buydown = validate_success(api_client.model_plan(buydown["id"], UW))
        assert buydown["status"] == "MODELED"
        assert buydown["actuarial_value"] == pytest.approx(0.8123, abs=1e-9)
        assert buydown["relativity_factor"] == pytest.approx(0.8123, abs=1e-9)
        ref = get_success_data(api_client.get_plan_design(ref["id"], UW))
        assert ref["actuarial_value"] == pytest.approx(1.0, abs=1e-9)


class TestPlanLifecycleGates:
    def test_model_plan_before_census_received_fails(self):
        """PRD section 3.4: "Modeling requires the plan to be `DRAFT` (else
        `ERR_PLAN_NOT_DRAFT`) and the parent case to have reached
        `CENSUS_RECEIVED` or any later state (else
        `ERR_CASE_NOT_READY_FOR_MODELING`)."

        Design: Corner/validations/model_plan_before_census_received_fails
        """
        broker = create_broker()
        case = create_case(broker["id"])
        resp = api_client.create_plan_design(
            case["id"], create_plan_design_payload(), UW
        )
        plan = get_success_data(resp)
        resp = api_client.model_plan(plan["id"], UW)
        validate_error(resp, ApiErrorId.ERR_CASE_NOT_READY_FOR_MODELING)
        plan = get_success_data(api_client.get_plan_design(plan["id"], UW))
        assert plan["status"] == "DRAFT"

    def test_model_plan_twice_fails(self):
        """PRD section 3.4: "Modeling requires the plan to be `DRAFT` (else
        `ERR_PLAN_NOT_DRAFT`)".

        Design: Corner/validations/model_plan_twice_fails
        """
        broker = create_broker()
        case, _ = create_case_in_census_received(broker["id"])
        plan = add_modeled_plan(case["id"])
        assert plan["status"] == "MODELED"
        resp = api_client.model_plan(plan["id"], UW)
        validate_error(resp, ApiErrorId.ERR_PLAN_NOT_DRAFT)
        plan = get_success_data(api_client.get_plan_design(plan["id"], UW))
        assert plan["status"] == "MODELED"
        assert plan["actuarial_value"] == pytest.approx(1.0, abs=1e-9)

    def test_reject_plan_with_active_quote_fails(self):
        """PRD section 3.4: "An underwriter may reject a design from `DRAFT`
        unconditionally, or from `MODELED` provided no quote in `PROPOSED` or
        `COUNTERED` status references it — attempting to reject a plan with such
        live quotes is refused with `ERR_PLAN_HAS_ACTIVE_QUOTES`."

        Design: Corner/state_machines/reject_plan_with_active_quote_fails
        """
        broker = create_broker()
        case, _ = create_case_in_rating(broker["id"])
        plan = add_modeled_plan(case["id"])
        quote = create_proposed_quote(case["id"], plan["id"])
        resp = api_client.reject_plan(plan["id"], UW)
        validate_error(resp, ApiErrorId.ERR_PLAN_HAS_ACTIVE_QUOTES)
        plan = get_success_data(api_client.get_plan_design(plan["id"], UW))
        assert plan["status"] == "MODELED"
