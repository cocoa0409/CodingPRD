"""Income eligibility and benefit-award calculations (PRD §3.2, §3.4)."""
import pytest

from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    new_funding_pool, new_household, new_draft_application, submit_app,
    add_verified_income, setup_approved_application,
    make_applicant_headers, TEST_USERS,
    create_application_payload,
)

CW = TEST_USERS["caseworker_headers"]


class TestProvisionalVsFinalBenefit:
    def test_submit_computes_provisional_benefit_from_self_reported_income(self, api):
        """PRD §3.2: "On a successful submit the server computes `fpl_pct` from the
        household's self-reported income (the income-eligibility calculation of §3.4),
        sets `income_eligible` to true, computes the provisional `benefit_tier` and
        `benefit_amount_cents` from the benefit calculation using that same
        self-reported income, sets `benefit_variant` to `PROVISIONAL`, and stamps
        `submitted_at` with the current logical-clock time."

        Design: Difficulty/dual_variant_calc/application_provisional_vs_final_benefit
        """
        new_funding_pool(api, program_component="HEATING")
        hh = new_household(api, primary_applicant_name="Ada Vale", household_size=3,
                           annual_income_cents=1_800_000, heating_source="NATURAL_GAS",
                           has_elderly_or_disabled=True)
        app = new_draft_application(api, hh["id"])
        resp = api.submit_application(app["id"], make_applicant_headers(hh["id"]))
        data = validate_success(resp)
        assert data["benefit_tier"] == "TIER_1"
        assert data["benefit_amount_cents"] == 112900
        assert data["benefit_variant"] == "PROVISIONAL"

    def test_approve_recomputes_final_benefit_from_verified_income(self, api):
        """PRD §3.4: "The server recomputes `fpl_pct`, `benefit_tier`, and
        `benefit_amount_cents` from that verified income, sets `benefit_variant` to
        `FINAL`, and moves the application from `SUBMITTED` to `APPROVED`."

        Design: Difficulty/dual_variant_calc/application_provisional_vs_final_benefit
        """
        new_funding_pool(api, program_component="HEATING")
        hh = new_household(api, primary_applicant_name="Ada Vale", household_size=3,
                           annual_income_cents=1_800_000, heating_source="NATURAL_GAS",
                           has_elderly_or_disabled=True)
        app = new_draft_application(api, hh["id"])
        submit_app(api, app["id"], hh["id"])
        add_verified_income(api, app["id"], reported_income_cents=2_600_000,
                            verified_income_cents=2_600_000)
        data = validate_success(api.approve_application(app["id"], CW))
        assert data["benefit_tier"] == "TIER_2"
        assert data["benefit_amount_cents"] == 88200
        assert data["benefit_variant"] == "FINAL"


class TestBenefitTierMatrixAndClamp:
    def test_large_household_award_is_clamped_to_ceiling(self, api):
        """PRD §3.4: "The summed figure is finally clamped to lie between a floor of
        10,000 cents and a ceiling of 150,000 cents — any raw sum below the floor is
        raised to 10,000, and any above the ceiling is lowered to 150,000 — and the
        clamped result is `benefit_amount_cents`."

        Design: Difficulty/combinatorial_formula/benefit_tier_matrix_nonlinear_cap
        """
        new_funding_pool(api, program_component="HEATING")
        hh = new_household(api, primary_applicant_name="Cara Diaz", household_size=8,
                           annual_income_cents=2_000_000, heating_source="NATURAL_GAS",
                           has_elderly_or_disabled=True)
        app = new_draft_application(api, hh["id"])
        data = validate_success(api.submit_application(app["id"], make_applicant_headers(hh["id"])))
        assert data["benefit_tier"] == "TIER_1"
        assert data["benefit_amount_cents"] == 150000

    def test_clamped_award_persists_on_fetch(self, api):
        """PRD §3.4: "The `benefit_tier` follows directly from `fpl_pct`: `TIER_1` when
        `fpl_pct` is at or below 75, otherwise `TIER_2` when it is at or below 110,
        otherwise `TIER_3` when it is at or below 150, otherwise `INELIGIBLE` above 150."

        Design: Difficulty/combinatorial_formula/benefit_tier_matrix_nonlinear_cap
        """
        new_funding_pool(api, program_component="HEATING")
        hh = new_household(api, primary_applicant_name="Cara Diaz", household_size=8,
                           annual_income_cents=2_000_000, heating_source="NATURAL_GAS",
                           has_elderly_or_disabled=True)
        app = new_draft_application(api, hh["id"])
        submit_app(api, app["id"], hh["id"])
        data = validate_success(api.get_application(app["id"], CW))
        assert data["benefit_tier"] == "TIER_1"
        assert data["benefit_amount_cents"] == 150000


class TestComponentRoundingOrder:
    def test_round_then_sum_yields_exact_award(self, api):
        """PRD §3.4: "The three components are combined by rounding each of the size and
        heating components to the nearest whole dollar — the nearest multiple of 100
        cents, round-half-up — and then summing the two rounded figures together with
        the vulnerability component."

        Design: Difficulty/combinatorial_formula/benefit_component_rounding_order
        """
        new_funding_pool(api, program_component="HEATING")
        hh = new_household(api, primary_applicant_name="Dan Ely", household_size=3,
                           annual_income_cents=1_800_000, heating_source="NATURAL_GAS",
                           has_elderly_or_disabled=True)
        app = new_draft_application(api, hh["id"])
        data = validate_success(api.submit_application(app["id"], make_applicant_headers(hh["id"])))
        assert data["benefit_amount_cents"] == 112900, "round-then-sum; sum-then-round 112800 is wrong"

    def test_round_then_sum_award_persists(self, api):
        """PRD §3.4: "This is a round-then-sum order: each component is rounded
        individually first, and only then are they added; summing first and rounding
        once is the wrong interpretation and will yield different awards at the
        boundaries."

        Design: Difficulty/combinatorial_formula/benefit_component_rounding_order
        """
        new_funding_pool(api, program_component="HEATING")
        hh = new_household(api, primary_applicant_name="Dan Ely", household_size=3,
                           annual_income_cents=1_800_000, heating_source="NATURAL_GAS",
                           has_elderly_or_disabled=True)
        app = new_draft_application(api, hh["id"])
        submit_app(api, app["id"], hh["id"])
        data = validate_success(api.get_application(app["id"], CW))
        assert data["benefit_tier"] == "TIER_1"
        assert data["benefit_amount_cents"] == 112900


class TestIncomeEligibilityBoundary:
    def test_fpl_exactly_150_is_eligible_and_submits(self, api):
        """PRD §3.4: "A household is `income_eligible` — and clears the eligibility gate
        — when `fpl_pct` is at or below 150.00 inclusive; above that it is ineligible."

        Design: Difficulty/boundary_precision_check/income_eligibility_at_150_fpl_boundary
        """
        new_funding_pool(api, program_component="HEATING")
        hh = new_household(api, primary_applicant_name="Mae Noor", household_size=4,
                           annual_income_cents=4_680_000, heating_source="ELECTRICITY")
        app = new_draft_application(api, hh["id"])
        data = validate_success(api.submit_application(app["id"], make_applicant_headers(hh["id"])))
        assert data["fpl_pct"] == pytest.approx(150.00, abs=0.001)
        assert data["income_eligible"] is True
        assert data["status"] == "SUBMITTED"

    def test_fpl_just_over_150_is_rejected(self, api):
        """PRD §3.2: "Third, the applicant's provisional income eligibility must pass:
        using the household's self-reported `annual_income_cents`, the computed
        `fpl_pct` must be at or below 150.00, and if it exceeds that ceiling the submit
        is rejected with `ERR_INCOME_INELIGIBLE`."

        Design: Difficulty/boundary_precision_check/income_eligibility_at_150_fpl_boundary
        """
        new_funding_pool(api, program_component="HEATING")
        hh = new_household(api, primary_applicant_name="Ned Ono", household_size=4,
                           annual_income_cents=4_695_000, heating_source="ELECTRICITY")
        app = new_draft_application(api, hh["id"])
        resp = api.submit_application(app["id"], make_applicant_headers(hh["id"]))
        validate_error(resp, ApiErrorId.ERR_INCOME_INELIGIBLE.value)
        after = validate_success(api.get_application(app["id"], CW))
        assert after["status"] == "DRAFT"


class TestSubmitTemporalBeatsConstraint:
    def test_closed_season_beats_income_ineligibility(self, api):
        """PRD §3.2: "First, a matching funding pool must exist for the application's
        `season_year` and `program_component` and must not be closed; if the matching
        pool's status is `CLOSED`, the submit is rejected with `ERR_SEASON_CLOSED`."

        Design: Difficulty/priority_pair_validation_conflict/submit_temporal_beats_constraint
        """
        pool = new_funding_pool(api, program_component="HEATING")
        api.close_funding_pool(pool["id"], TEST_USERS["programadmin_headers"])
        hh = new_household(api, primary_applicant_name="Lou Mora", household_size=4,
                           annual_income_cents=4_695_000, heating_source="ELECTRICITY")
        app = new_draft_application(api, hh["id"])
        resp = api.submit_application(app["id"], make_applicant_headers(hh["id"]))
        validate_error(resp, ApiErrorId.ERR_SEASON_CLOSED.value)

    def test_submit_rejection_leaves_application_in_draft(self, api):
        """PRD §3.2: "Submitting an application moves it from `DRAFT` to `SUBMITTED`
        (and, as described in §3.3, is also how a returned application moves from
        `INFO_REQUESTED` back to `SUBMITTED`)."

        Design: Difficulty/priority_pair_validation_conflict/submit_temporal_beats_constraint
        """
        pool = new_funding_pool(api, program_component="HEATING")
        api.close_funding_pool(pool["id"], TEST_USERS["programadmin_headers"])
        hh = new_household(api, primary_applicant_name="Lou Mora", household_size=4,
                           annual_income_cents=4_695_000, heating_source="ELECTRICITY")
        app = new_draft_application(api, hh["id"])
        api.submit_application(app["id"], make_applicant_headers(hh["id"]))
        after = validate_success(api.get_application(app["id"], CW))
        assert after["status"] == "DRAFT"


def test_create_application_missing_season_year_rejected(api):
    """PRD §2.9: "A malformed body — a missing required field, a null where a value is
    required, a wrong type, or an invalid enum member — is caught by `ERR_VALIDATION`
    (HTTP 400)."

    Design: Corner/entities/create_application_missing_required_field_rejected
    """
    hh = new_household(api, primary_applicant_name="Cy Dole", household_size=1,
                       annual_income_cents=900_000, heating_source="PROPANE")
    payload = create_application_payload(hh["id"])
    payload.pop("season_year")
    resp = api.create_application(payload, CW)
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value)
