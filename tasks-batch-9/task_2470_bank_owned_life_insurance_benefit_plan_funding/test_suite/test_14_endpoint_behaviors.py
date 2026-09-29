"""Read-only projections, operator-driven recomputes, successor issuance and branch-only actions."""
import pytest
from test_helpers import validate_error, validate_success
from test_helpers.fixtures import (
    ANALYST,
    RISK,
    TREASURY,
    add_liability,
    authorize_carrier,
    authorized_carrier_with_product,
    create_analysis,
    create_plan,
    current_carrier_version,
    diligence_cleared_request,
    execute_consent,
    in_force_policy,
    insured_employee,
    onboard_carrier,
    register_employee,
    reserved_capacity_request,
)


WILLOW = {
    "legal_name": "Willow Life",
    "naic_code": "71023",
    "am_best_rating": "A_PLUS",
    "statutory_surplus_usd": 400_000_000.00,
    "domicile_state": "OK",
}
XENON = {
    "legal_name": "Xenon Life",
    "naic_code": "71024",
    "am_best_rating": "A_PLUS",
    "statutory_surplus_usd": 400_000_000.00,
    "domicile_state": "MD",
}
YARROW = {
    "legal_name": "Yarrow Life",
    "naic_code": "71025",
    "am_best_rating": "A_PLUS",
    "statutory_surplus_usd": 400_000_000.00,
    "domicile_state": "DE",
}
ZEPHYR = {
    "legal_name": "Zephyr Life",
    "naic_code": "71026",
    "am_best_rating": "A_PLUS",
    "statutory_surplus_usd": 400_000_000.00,
    "domicile_state": "RI",
}

COSTA = {
    "full_name": "Ines Costa",
    "employee_number": "E-8901",
    "annual_salary_usd": 600_000.00,
    "officer_flag": False,
}


class TestCapacityProjection:
    def test_the_what_if_read_shows_the_whole_working_and_moves_nothing(self, api):
        """The projection is the reservation's arithmetic without the reservation.

        "A `RiskOfficer` or a `TreasuryController` can run the whole computation
        read-only as a what-if projection against any request, without reserving
        anything and without mutating any resource. The projection returns
        `tier1_capital_usd`, `base_limit_usd`, `committed_usd`, `prospective_usd`,
        `base_ratio_bps`, `effective_limit_pct`, `aggregate_limit_usd`,
        `headroom_usd`, `carrier_concentration_bps` and `single_carrier_limit_bps`
        — the complete working of the calculation". On an empty book the 20,000,000
        premium is the only commitment, because "the request's premium is always
        included even though the request is not yet reserved".

        Design: Corner/endpoints/capacity_projection_reads_the_headroom_without_reserving_anything
        """
        context = authorized_carrier_with_product(
            api,
            carrier_overrides=WILLOW,
            product_overrides={"product_name": "Willow GA BOLI"},
        )
        insured = insured_employee(
            api,
            employee_overrides={
                "full_name": "Nadia Abbas",
                "employee_number": "E-8701",
                "annual_salary_usd": 600_000.00,
            },
            consent_overrides={
                "coverage_start_date": "2026-08-01T00:00:00Z",
                "coverage_end_date": "2027-07-31T00:00:00Z",
                "consent_form_reference": "CF-8701",
            },
        )
        request = diligence_cleared_request(
            api,
            context["carrier_id"],
            context["product_type_id"],
            insured["employee_id"],
            single_premium_usd=20_000_000.00,
            face_amount_usd=60_000_000.00,
            requested_effective_date="2026-08-15T00:00:00Z",
        )
        version_before = current_carrier_version(api, context["carrier_id"])

        response = api.get_capacity_projection(request["id"], TREASURY)
        assert response.status_code == 200
        projection = validate_success(response)

        assert projection["tier1_capital_usd"] == pytest.approx(1_000_000_000.00, abs=0.01)
        assert projection["base_limit_usd"] == pytest.approx(250_000_000.00, abs=0.01)
        assert projection["committed_usd"] == pytest.approx(0.00, abs=0.01)
        assert projection["prospective_usd"] == pytest.approx(20_000_000.00, abs=0.01)
        assert projection["base_ratio_bps"] == 800
        assert projection["effective_limit_pct"] == pytest.approx(0.25, abs=0.0001)
        assert projection["aggregate_limit_usd"] == pytest.approx(250_000_000.00, abs=0.01)
        assert projection["headroom_usd"] == pytest.approx(230_000_000.00, abs=0.01)
        assert projection["carrier_concentration_bps"] == 200
        assert projection["single_carrier_limit_bps"] == 1500

        carrier = validate_success(api.get_carrier(context["carrier_id"], TREASURY))
        assert carrier["reserved_premium_usd"] == pytest.approx(0.00, abs=0.01)
        assert carrier["version"] == version_before, "a read-only projection bumps nothing"

        unchanged = validate_success(api.get_purchase_request(request["id"], TREASURY))
        assert unchanged["status"] == "DILIGENCE_CLEARED"
        assert unchanged["reserved_premium_usd"] == pytest.approx(0.00, abs=0.01)


class TestExplicitRevaluation:
    def test_an_operator_revaluation_recomputes_and_freezes_a_critical_plan(self, api):
        """The explicit recompute is the one that also moves the plan.

        "An explicit revaluation recomputes `accrual_liability_usd`,
        `pbo_liability_usd`, `matched_cash_value_usd`, `funded_ratio_bps` and
        `funding_posture`, drives the plan `ACTIVE → FROZEN` when the recomputed
        accrual-basis posture is `CRITICAL`, and increments the plan's `version` by
        1." Creating the liability had already left the posture at `CRITICAL`
        without freezing anything, since a create only "recomputes the plan's
        totals and accrual-basis posture".

        Design: Corner/endpoints/revalue_recomputes_plan_totals_and_freezes_a_critical_plan
        """
        plan = create_plan(
            api, plan_name="Revalue SERP", plan_type="SERP", discount_rate_bps=500
        )
        larsen = register_employee(
            api,
            full_name="Tom Larsen",
            employee_number="E-8801",
            annual_salary_usd=700_000.00,
        )
        liability = add_liability(
            api,
            plan["id"],
            larsen["id"],
            accrued_to_date_usd=600_000.00,
            projected_benefit_usd=800_000.00,
            years_to_payout=5,
        )

        before = validate_success(api.get_nqdc_plan(plan["id"], TREASURY))
        assert before["status"] == "ACTIVE", "the liability create leaves the plan open"
        assert before["funding_posture"] == "CRITICAL"
        version_before = before["version"]

        response = api.revalue_nqdc_plan(plan["id"], TREASURY)
        assert response.status_code == 200
        revalued = validate_success(response)

        assert revalued["status"] == "FROZEN"
        assert revalued["accrual_liability_usd"] == pytest.approx(600_000.00, abs=0.01)
        assert revalued["pbo_liability_usd"] == pytest.approx(626_820.93, abs=0.01)
        assert revalued["matched_cash_value_usd"] == pytest.approx(0.00, abs=0.01)
        assert revalued["funded_ratio_bps"] == 0
        assert revalued["funding_posture"] == "CRITICAL"
        assert revalued["version"] == version_before + 1

        untouched = validate_success(api.get_nqdc_liability(liability["id"], TREASURY))
        assert untouched["status"] == "ACTIVE", "freezing the plan settles no participant"


class TestExchangeExecution:
    def test_the_successor_policy_points_back_at_the_contract_it_replaced(self, api):
        """One request retires a contract at one carrier and opens one at another.

        "The successor is created with `exchanged_from_policy_id` pointing at the
        predecessor, `single_premium_usd` and `cash_surrender_value_usd` both equal
        to the analysis's `net_proceeds_usd` — the net transferred cash value —
        `cost_basis_usd` carried over from the predecessor **unchanged**, which is
        exactly what makes the exchange tax deferred rather than tax free,
        `policy_year` reset to 1, and status `IN_FORCE`." Meanwhile "the
        predecessor's premium and cash value are removed from the old carrier's
        `in_force_premium_usd` and `in_force_cash_value_usd`, the successor's
        figures are added to the replacement carrier's totals".

        Design: Corner/endpoints/execute_exchange_issues_a_successor_policy_linked_to_its_predecessor
        """
        context = in_force_policy(
            api,
            carrier_overrides=XENON,
            product_overrides={"product_name": "Xenon GA BOLI"},
            employee_overrides=COSTA,
            consent_overrides={"consent_form_reference": "CF-8901"},
            request_overrides={
                "single_premium_usd": 1_000_000.00,
                "face_amount_usd": 3_000_000.00,
            },
            policy_overrides={"policy_number": "XN-0001"},
        )
        replacement = onboard_carrier(api, **YARROW)
        authorize_carrier(api, replacement["id"], review_year=2026)

        analysis = create_analysis(
            api,
            context["policy_id"],
            disposition_type="EXCHANGE_1035",
            replacement_carrier_id=replacement["id"],
        )
        assert analysis["cost_recovery_method"] == "FIFO_BASIS_FIRST", (
            "the product is NON_MEC, so basis is recovered first"
        )
        assert analysis["taxable_gain_usd"] == pytest.approx(0.00, abs=0.01)
        assert analysis["surrender_charge_usd"] == pytest.approx(60_000.00, abs=0.01)
        assert analysis["tax_liability_usd"] == pytest.approx(0.00, abs=0.01)
        assert analysis["net_proceeds_usd"] == pytest.approx(940_000.00, abs=0.01)

        validate_success(api.review_exchange_analysis(analysis["id"], RISK))
        validate_success(api.commit_exchange_analysis(analysis["id"], TREASURY))
        assert (
            validate_success(api.get_policy(context["policy_id"], TREASURY))["status"]
            == "PENDING_EXCHANGE"
        )

        successor = validate_success(
            api.execute_exchange(
                analysis["id"],
                {"policy_number": "YR-0001", "issue_date": "2026-08-20T00:00:00Z"},
                TREASURY,
            ),
            201,
        )
        assert successor["exchanged_from_policy_id"] == context["policy_id"]
        assert successor["carrier_id"] == replacement["id"]
        assert successor["policy_number"] == "YR-0001"
        assert successor["issue_date"].startswith("2026-08-20")
        assert successor["single_premium_usd"] == pytest.approx(940_000.00, abs=0.01)
        assert successor["cash_surrender_value_usd"] == pytest.approx(940_000.00, abs=0.01)
        assert successor["cost_basis_usd"] == pytest.approx(1_000_000.00, abs=0.01), (
            "the basis crosses over unchanged, which is what defers the tax"
        )
        assert successor["policy_year"] == 1
        assert successor["status"] == "IN_FORCE"

        predecessor = validate_success(api.get_policy(context["policy_id"], TREASURY))
        assert predecessor["status"] == "EXCHANGED"

        executed = validate_success(api.get_exchange_analysis(analysis["id"], TREASURY))
        assert executed["status"] == "EXECUTED"
        assert executed["resulting_policy_id"] == successor["id"]

        old_carrier = validate_success(api.get_carrier(context["carrier_id"], TREASURY))
        assert old_carrier["in_force_premium_usd"] == pytest.approx(0.00, abs=0.01)
        assert old_carrier["in_force_cash_value_usd"] == pytest.approx(0.00, abs=0.01)
        assert old_carrier["concentration_bps"] == 0

        new_carrier = validate_success(api.get_carrier(replacement["id"], TREASURY))
        assert new_carrier["in_force_premium_usd"] == pytest.approx(940_000.00, abs=0.01)
        assert new_carrier["in_force_cash_value_usd"] == pytest.approx(940_000.00, abs=0.01)
        assert new_carrier["concentration_bps"] == 9


class TestEmploymentStatusWrite:
    def test_a_termination_is_recorded_without_disturbing_insurable_interest(self, api):
        """Employment posture and insurable interest are independent fields.

        "The analyst can also record a later change of employment posture by
        supplying a new `employment_status` value drawn from `ACTIVE`, `TERMINATED`
        and `DECEASED`; that write sets the field and increments the employee's
        `version` by 1." Interest is derived from other data entirely: "the
        employee's `annual_salary_usd` is at least 250,000.00, **or** the
        employee's `officer_flag` is true. If either holds, the derived value is
        `ESTABLISHED`".

        Design: Corner/endpoints/employment_status_endpoint_records_a_termination
        """
        boone = register_employee(
            api,
            full_name="Gail Boone",
            employee_number="E-9001",
            annual_salary_usd=600_000.00,
        )
        consent = execute_consent(
            api,
            boone["id"],
            coverage_start_date="2026-08-01T00:00:00Z",
            coverage_end_date="2027-07-31T00:00:00Z",
            consent_form_reference="CF-9001",
        )

        before = validate_success(api.get_employee(boone["id"], ANALYST))
        assert before["employment_status"] == "ACTIVE"
        assert before["insurable_interest_status"] == "ESTABLISHED"
        version_before = before["version"]

        response = api.set_employment_status(
            boone["id"], {"employment_status": "TERMINATED"}, ANALYST
        )
        assert response.status_code == 200
        terminated = validate_success(response)

        assert terminated["employment_status"] == "TERMINATED"
        assert terminated["insurable_interest_status"] == "ESTABLISHED", (
            "the salary test is unaffected by leaving the payroll"
        )
        assert terminated["version"] == version_before + 1

        consent_after = validate_success(api.get_consent_record(consent["id"], ANALYST))
        assert consent_after["status"] == "EXECUTED", (
            "an employment change revokes no signed consent"
        )


class TestNoticeBranchGuard:
    def test_the_notice_action_is_closed_to_a_request_below_the_threshold(self, api):
        """Which fork a reserved request may take was fixed at submission.

        "A request whose `notice_required` is true must have its regulatory
        notification filed before anything else happens", and "the action is
        available only when `notice_required` is true, and attempting it on a
        request that does not require notification is refused as
        `ERR_INVALID_STATE_TRANSITION`". The other fork is open instead: "A
        `BenefitsAnalyst` asks the risk function for concurrence directly from
        `CAPACITY_RESERVED`", a path that "deliberately does **not** touch the
        carrier's `regulatory_notice_count` at all".

        Design: Corner/endpoints/file_notice_is_available_only_when_the_premium_required_a_notice
        """
        context = authorized_carrier_with_product(
            api,
            carrier_overrides=ZEPHYR,
            product_overrides={"product_name": "Zephyr GA BOLI"},
        )
        insured = insured_employee(
            api,
            employee_overrides={
                "full_name": "Luis Duarte",
                "employee_number": "E-9101",
                "annual_salary_usd": 600_000.00,
            },
            consent_overrides={
                "coverage_start_date": "2026-08-01T00:00:00Z",
                "coverage_end_date": "2027-07-31T00:00:00Z",
                "consent_form_reference": "CF-9101",
            },
        )
        request = diligence_cleared_request(
            api,
            context["carrier_id"],
            context["product_type_id"],
            insured["employee_id"],
            single_premium_usd=1_000_000.00,
            face_amount_usd=3_000_000.00,
            requested_effective_date="2026-08-15T00:00:00Z",
        )
        reserved = reserved_capacity_request(api, request["id"], context["carrier_id"])
        assert reserved["notice_required"] is False, "1,000,000.00 is below the threshold"
        assert reserved["notice_filed_at"] is None
        assert reserved["notice_waiting_ends_at"] is None

        validate_error(
            api.file_purchase_request_notice(request["id"], TREASURY),
            "ERR_INVALID_STATE_TRANSITION",
            409,
        )
        assert (
            validate_success(api.get_purchase_request(request["id"], TREASURY))["status"]
            == "CAPACITY_RESERVED"
        )
        assert (
            validate_success(api.get_carrier(context["carrier_id"], TREASURY))[
                "regulatory_notice_count"
            ]
            == 0
        ), "the refused filing tallies no notice against the carrier"

        response = api.request_purchase_request_concurrence(request["id"], ANALYST)
        assert response.status_code == 200
        pending = validate_success(response)
        assert pending["status"] == "CONCURRENCE_PENDING"
        assert pending["notice_filed_at"] is None
        assert pending["concurrence_requested_at"].startswith("2026-08-01T00:00:00")

        carrier = validate_success(api.get_carrier(context["carrier_id"], TREASURY))
        assert carrier["reserved_premium_usd"] == pytest.approx(1_000_000.00, abs=0.01)
        assert carrier["regulatory_notice_count"] == 0
