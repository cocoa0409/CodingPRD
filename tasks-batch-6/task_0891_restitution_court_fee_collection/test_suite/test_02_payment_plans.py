"""Payment plans: ability-to-pay computation, activation, and OCC on case version."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    clerk_headers, supervisor_headers,
    make_case, make_obligation, make_payment_plan, get_case_version,
    setup_case_with_obligation, post_payment,
    api_client,
)


class TestAbilityToPayNetDisposable:
    def test_net_disposable_installment_is_ten_percent_of_disposable(self, api):
        """PRD §3.2: "When ability_to_pay_method is NET_DISPOSABLE, the basis is the
        obligor's disposable income: the greater of zero and (monthly_income_cents
        minus monthly_expenses_cents). ... The system multiplies the basis by an
        ability-to-pay rate of 10 percent and rounds the product half up to whole cents."

        Design: Difficulty/dual_variant_calc/ability_to_pay_net_disposable_installment
        """
        case = make_case(case_number="C-ATP-NET")
        make_obligation(case["id"], "COURT_FEE", 500000)
        plan = make_payment_plan(case["id"], 400000, 250000, "NET_DISPOSABLE")
        assert plan["monthly_amount_cents"] == 15000
        assert plan["status"] == "PROPOSED"

    def test_net_disposable_ignores_income_above_expenses_only(self, api):
        """PRD §3.2: "the basis is the obligor's disposable income: the greater of zero
        and (monthly_income_cents minus monthly_expenses_cents)."

        Design: Difficulty/dual_variant_calc/ability_to_pay_net_disposable_installment
        """
        case = make_case(case_number="C-ATP-NET2")
        make_obligation(case["id"], "COURT_FEE", 500000)
        plan = make_payment_plan(case["id"], 500000, 300000, "NET_DISPOSABLE")
        assert plan["monthly_amount_cents"] == 20000, "disposable 200000 * 0.10 = 20000"


class TestAbilityToPayGrossIncome:
    def test_gross_income_installment_uses_full_income(self, api):
        """PRD §3.2: "When it is GROSS_INCOME, the basis is simply monthly_income_cents,
        ignoring expenses ... The system multiplies the basis by an ability-to-pay rate
        of 10 percent and rounds the product half up to whole cents; it then raises that
        figure to a minimum installment floor of 2,500 cents ... and finally it caps the
        installment at the case's current balance_cents."

        Design: Difficulty/combinatorial_formula/ability_to_pay_gross_nested_min_max
        """
        case = make_case(case_number="C-ATP-GROSS")
        make_obligation(case["id"], "COURT_FEE", 500000)
        plan = make_payment_plan(case["id"], 400000, 250000, "GROSS_INCOME")
        assert plan["monthly_amount_cents"] == 40000

    def test_gross_income_disregards_expenses_entirely(self, api):
        """PRD §3.2: "When it is GROSS_INCOME, the basis is simply monthly_income_cents,
        ignoring expenses — so for identical inputs the gross method yields a larger
        installment than the net method."

        Design: Difficulty/combinatorial_formula/ability_to_pay_gross_nested_min_max
        """
        case = make_case(case_number="C-ATP-GROSS2")
        make_obligation(case["id"], "COURT_FEE", 500000)
        plan = make_payment_plan(case["id"], 400000, 900000, "GROSS_INCOME")
        assert plan["monthly_amount_cents"] == 40000, "expenses ignored: 400000 * 0.10 = 40000"


def test_ability_to_pay_floor_hits_min_installment(api):
    """PRD §3.2: "it then raises that figure to a minimum installment floor of 2,500
    cents (25 dollars) if it fell below it."

    Design: Corner/calculations/ability_to_pay_floor_hits_min_installment
    """
    case = make_case(case_number="C-ATPFLOOR")
    make_obligation(case["id"], "COURT_FEE", 500000)
    plan = make_payment_plan(case["id"], 300000, 290000, "NET_DISPOSABLE")
    assert plan["monthly_amount_cents"] == 2500, "disposable 10000 * 0.10 = 1000 -> floored up to 2500"


class TestPlanActivationRequiresOpenCase:
    def test_activate_rejected_when_case_satisfied(self, api):
        """PRD §3.2: "Activation requires that the case status be OPEN (otherwise
        ERR_CASE_NOT_OPEN) and that no other plan on the case is already ACTIVE."

        Design: Difficulty/cross_entity_state_dependency/plan_activate_requires_case_open
        """
        case, obl = setup_case_with_obligation(case_number="C-NOTOPEN", assessed_amount_cents=10000)
        post_payment(case["id"], 10000, "STATUTORY_PRIORITY")  # case -> SATISFIED
        plan = make_payment_plan(case["id"], 400000, 250000, "NET_DISPOSABLE")

        resp = api.activate_payment_plan(plan["id"], supervisor_headers())
        validate_error(resp, ApiErrorId.ERR_CASE_NOT_OPEN.value)

        case_after = validate_success(api.get_case(case["id"], clerk_headers()))
        assert case_after["status"] == "SATISFIED"

    def test_activate_succeeds_when_case_open(self, api):
        """PRD §3.2: "A CollectionsSupervisor activates a proposal, transitioning it
        from PROPOSED to ACTIVE. Activation requires that the case status be OPEN."

        Design: Difficulty/cross_entity_state_dependency/plan_activate_requires_case_open
        """
        case, obl = setup_case_with_obligation(case_number="C-OPENACT", assessed_amount_cents=100000)
        plan = make_payment_plan(case["id"], 400000, 250000, "NET_DISPOSABLE")

        activated = validate_success(api.activate_payment_plan(plan["id"], supervisor_headers()))
        assert activated["status"] == "ACTIVE"


def test_activate_second_plan_rejected_when_active_plan_exists(api):
    """PRD §3.2: "Activation requires that the case status be OPEN ... and that no other
    plan on the case is already ACTIVE (otherwise ERR_ACTIVE_PLAN_EXISTS)."

    Design: Corner/errors/activate_second_plan_returns_active_plan_exists
    """
    case, obl = setup_case_with_obligation(case_number="C-TWOPLAN", assessed_amount_cents=100000)
    plan1 = make_payment_plan(case["id"], 400000, 250000, "NET_DISPOSABLE")
    validate_success(api.activate_payment_plan(plan1["id"], supervisor_headers()))
    plan2 = make_payment_plan(case["id"], 400000, 250000, "NET_DISPOSABLE")

    resp = api.activate_payment_plan(plan2["id"], supervisor_headers())
    validate_error(resp, ApiErrorId.ERR_ACTIVE_PLAN_EXISTS.value)


def test_occ_stale_case_version_rejected(api):
    """PRD §2.9: "If expected_case_version does not match the case's current version at
    the time of the request, the create is rejected with ERR_STALE_CASE_VERSION (HTTP 412)."

    Design: Corner/cross_cutting/occ_stale_case_version_rejected
    """
    case = make_case(case_number="C-OCC")
    stale_version = case["version"]  # version 1, before the obligation bumps it
    make_obligation(case["id"], "COURT_FEE", 10000)

    resp = api.create_payment_plan(
        {
            "case_id": case["id"], "monthly_income_cents": 400000,
            "monthly_expenses_cents": 250000, "ability_to_pay_method": "NET_DISPOSABLE",
            "expected_case_version": stale_version,
        },
        clerk_headers(),
    )
    validate_error(resp, ApiErrorId.ERR_STALE_CASE_VERSION.value, expected_status=412)


def test_case_version_increments_on_obligation_add(api):
    """PRD §2.4: "creating an obligation, posting or reversing a payment, or otherwise
    changing a case's aggregates increments that case's version."

    Design: Corner/cross_cutting/case_version_increments_on_obligation_add
    """
    case = make_case(case_number="C-VERBUMP")
    assert case["version"] == 1
    make_obligation(case["id"], "COURT_FEE", 10000)

    version_after = get_case_version(case["id"])
    assert version_after >= 2, f"obligation add must bump case version, got {version_after}"
