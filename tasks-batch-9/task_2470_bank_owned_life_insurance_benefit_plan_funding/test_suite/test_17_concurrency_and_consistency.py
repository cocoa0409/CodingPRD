"""The two optimistic-concurrency guards, and the immediacy of a cascaded recompute."""
import pytest
from test_helpers import validate_error, validate_paginated, validate_success
from test_helpers.fixtures import (
    TREASURY,
    add_liability,
    authorize_carrier,
    authorized_carrier_with_product,
    create_plan,
    current_carrier_version,
    current_policy_version,
    diligence_cleared_request,
    funding_summary,
    in_force_policy,
    insured_employee,
    onboard_carrier,
    register_employee,
)


IRONWOOD = {
    "legal_name": "Ironwood Life",
    "naic_code": "71035",
    "am_best_rating": "A_PLUS",
    "statutory_surplus_usd": 400_000_000.00,
    "domicile_state": "PA",
}
JUNIPER = {
    "legal_name": "Juniper Life",
    "naic_code": "71036",
    "am_best_rating": "A_PLUS",
    "statutory_surplus_usd": 400_000_000.00,
    "domicile_state": "CT",
}
KESTREL = {
    "legal_name": "Kestrel Life",
    "naic_code": "71037",
    "am_best_rating": "A_PLUS",
    "statutory_surplus_usd": 400_000_000.00,
    "domicile_state": "VA",
}

JAKES = {
    "full_name": "Mona Jakes",
    "employee_number": "E-9501",
    "annual_salary_usd": 600_000.00,
    "officer_flag": False,
}
LUND = {
    "full_name": "Erik Lund",
    "employee_number": "E-9601",
    "annual_salary_usd": 600_000.00,
    "officer_flag": False,
}


class TestCarrierVersionGuardOnReservation:
    def test_a_version_one_behind_is_refused_and_the_current_one_is_accepted(self, api):
        """The reservation forces the controller to work from a fresh carrier read.

        "Reserving capacity for a purchase request requires the non-optional
        input field `expected_carrier_version`, carrying the `version` value the
        client last observed on the carrier the request names. If that value does
        not equal the carrier's current `version`, the reservation is rejected
        with `ERR_STALE_CARRIER_VERSION` (HTTP 412)." Because "A request that is
        rejected changes nothing and bumps nothing", the retry with the current
        version succeeds and "advances the request `DILIGENCE_CLEARED →
        CAPACITY_RESERVED`".

        Design: Corner/cross_cutting_complexity_layers/stale_expected_carrier_version_on_reserve_capacity_is_rejected
        """
        context = authorized_carrier_with_product(
            api,
            carrier_overrides=IRONWOOD,
            product_overrides={"product_name": "Ironwood GA BOLI"},
        )
        insured = insured_employee(
            api,
            employee_overrides=JAKES,
            consent_overrides={"consent_form_reference": "CF-9501"},
        )
        request = diligence_cleared_request(
            api,
            context["carrier_id"],
            context["product_type_id"],
            insured["employee_id"],
            single_premium_usd=1_000_000.00,
            face_amount_usd=3_000_000.00,
        )
        version = current_carrier_version(api, context["carrier_id"])

        validate_error(
            api.reserve_purchase_request_capacity(
                request["id"], {"expected_carrier_version": version - 1}, TREASURY
            ),
            "ERR_STALE_CARRIER_VERSION",
            412,
        )

        carrier_after_refusal = validate_success(
            api.get_carrier(context["carrier_id"], TREASURY)
        )
        assert carrier_after_refusal["version"] == version
        assert carrier_after_refusal["reserved_premium_usd"] == pytest.approx(0.00, abs=0.01)

        request_after_refusal = validate_success(
            api.get_purchase_request(request["id"], TREASURY)
        )
        assert request_after_refusal["status"] == "DILIGENCE_CLEARED"
        assert request_after_refusal["reserved_premium_usd"] == pytest.approx(0.00, abs=0.01)

        reserved = validate_success(
            api.reserve_purchase_request_capacity(
                request["id"], {"expected_carrier_version": version}, TREASURY
            )
        )
        assert reserved["status"] == "CAPACITY_RESERVED"
        assert reserved["reserved_premium_usd"] == pytest.approx(1_000_000.00, abs=0.01)
        assert reserved["notice_required"] is False

        carrier_after = validate_success(api.get_carrier(context["carrier_id"], TREASURY))
        assert carrier_after["version"] == version + 1
        assert carrier_after["reserved_premium_usd"] == pytest.approx(1_000_000.00, abs=0.01)


class TestPolicyVersionGuardOnAnalysisCreate:
    def test_an_analysis_author_working_from_a_stale_policy_read_is_refused(self, api):
        """The second guard watches a different entity through a different field.

        "Creating a disposition analysis requires the non-optional input field
        `expected_policy_version`, carrying the `version` value the client last
        observed on the policy the analysis addresses. A mismatch against the
        policy's current `version` is rejected with `ERR_STALE_POLICY_VERSION`
        (HTTP 412)." Accepted, "The create responds with HTTP 201, opens the new
        analysis in `DRAFT` with `resulting_policy_id` unset, and increments the
        policy's `version` by 1", and "For an `EXCHANGE_1035` the gross amount is
        likewise the whole cash value, but the `taxable_gain_usd` is 0.00".

        Design: Corner/cross_cutting_complexity_layers/stale_expected_policy_version_on_analysis_create_is_rejected
        """
        context = in_force_policy(
            api,
            carrier_overrides=JUNIPER,
            product_overrides={"product_name": "Juniper GA BOLI"},
            employee_overrides=LUND,
            consent_overrides={"consent_form_reference": "CF-9601"},
            request_overrides={
                "single_premium_usd": 1_000_000.00,
                "face_amount_usd": 3_000_000.00,
            },
            policy_overrides={"policy_number": "JN-0001"},
        )
        replacement = onboard_carrier(api, **KESTREL)
        authorize_carrier(api, replacement["id"], review_year=2026)

        version = current_policy_version(api, context["policy_id"])
        payload = {
            "policy_id": context["policy_id"],
            "disposition_type": "EXCHANGE_1035",
            "replacement_carrier_id": replacement["id"],
            "expected_policy_version": version - 1,
        }
        validate_error(
            api.create_exchange_analysis(payload, TREASURY), "ERR_STALE_POLICY_VERSION", 412
        )

        _items, meta = validate_paginated(
            api.list_exchange_analyses(TREASURY, params={"policy_id": context["policy_id"]})
        )
        assert meta["total_count"] == 0, "the refused create writes no analysis"

        untouched = validate_success(api.get_policy(context["policy_id"], TREASURY))
        assert untouched["status"] == "IN_FORCE"
        assert untouched["version"] == version

        analysis = validate_success(
            api.create_exchange_analysis(
                dict(payload, expected_policy_version=version), TREASURY
            ),
            201,
        )
        assert analysis["status"] == "DRAFT"
        assert analysis["resulting_policy_id"] is None
        assert analysis["taxable_gain_usd"] == pytest.approx(0.00, abs=0.01)
        assert analysis["surrender_charge_usd"] == pytest.approx(60_000.00, abs=0.01)
        assert analysis["net_proceeds_usd"] == pytest.approx(940_000.00, abs=0.01)

        after = validate_success(api.get_policy(context["policy_id"], TREASURY))
        assert after["version"] == version + 1, "the accepted create bumps the policy once"
        assert after["status"] == "IN_FORCE", "only the commit moves the policy"

        untouched_carrier = validate_success(api.get_carrier(replacement["id"], TREASURY))
        assert untouched_carrier["in_force_premium_usd"] == pytest.approx(0.00, abs=0.01), (
            "the replacement carrier takes on nothing until the exchange executes"
        )


class TestPlanTotalsAreImmediatelyConsistent:
    def test_adding_a_participant_is_visible_in_the_plan_on_the_next_read(self, api):
        """The cascaded recompute is part of the create, not a later job.

        "The plan's stored totals are recomputed whenever the underlying
        population changes: when a participant liability is created, when a
        liability is settled, when the controller explicitly asks for a
        revaluation, and as the cascaded recompute inside a distributed death
        claim or an executed surrender." No revaluation call is needed for the
        plan read and the funding summary to agree with the liability that was
        just created.

        Design: Corner/consistency_model/liability_create_is_immediately_visible_in_the_plan_totals
        """
        plan = create_plan(
            api, plan_name="Immediate SERP", plan_type="SERP", discount_rate_bps=500
        )
        employee = register_employee(
            api,
            full_name="Sara Nowak",
            employee_number="E-9701",
            annual_salary_usd=900_000.00,
            officer_flag=False,
        )

        before = validate_success(api.get_nqdc_plan(plan["id"], TREASURY))
        assert before["accrual_liability_usd"] == pytest.approx(0.00, abs=0.01)
        assert before["pbo_liability_usd"] == pytest.approx(0.00, abs=0.01)
        assert before["funded_ratio_bps"] == 10000
        assert before["funding_posture"] == "FUNDED"
        version_before = before["version"]

        liability = add_liability(
            api,
            plan["id"],
            employee["id"],
            accrued_to_date_usd=1_000_000.00,
            projected_benefit_usd=1_200_000.00,
            years_to_payout=5,
        )
        assert liability["discounted_benefit_usd"] == pytest.approx(940_231.40, abs=0.01)
        assert liability["status"] == "ACTIVE"

        after = validate_success(api.get_nqdc_plan(plan["id"], TREASURY))
        assert after["accrual_liability_usd"] == pytest.approx(1_000_000.00, abs=0.01)
        assert after["pbo_liability_usd"] == pytest.approx(940_231.40, abs=0.01)
        assert after["matched_cash_value_usd"] == pytest.approx(0.00, abs=0.01)
        assert after["funded_ratio_bps"] == 0
        assert after["funding_posture"] == "CRITICAL"
        assert after["version"] == version_before + 1
        assert after["status"] == "ACTIVE", "creating a liability never freezes the plan"

        summary = funding_summary(api, plan["id"], basis="PBO")
        assert summary["basis"] == "PBO"
        assert summary["basis_liability_usd"] == pytest.approx(940_231.40, abs=0.01)
        assert summary["funded_ratio_bps"] == 0
        assert summary["funding_posture"] == "CRITICAL"
        assert summary["participant_count"] == 1
