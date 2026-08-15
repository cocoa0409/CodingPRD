"""UI rate intake: experience-rate bracket math, new-employer fallback and
prohibition, supersession, kind fitness, and OCC on the Registration version."""
from test_helpers import (
    SPECIALIST,
    ApiErrorId,
    apply_vc,
    approve_vc,
    create_effective_ui_rate,
    create_ui_rate_payload,
    propose_vc,
    remit_vc,
    get_obligations,
    get_success_data,
    setup_ui_rate_effective,
    setup_ui_registration_active,
    setup_withholding_registration_active,
    validate_error,
    validate_success,
)


class TestStandardVsBuyDownVariants:
    def test_ui_rate_standard_variant_final_rate_390(self, api):
        """PRD §3.7: "The ratio selects a bracket: a ratio of at least 1500 yields 50;
        1000 through 1499 yields 120; 500 through 999 yields 240; 100 through 499
        yields 360; 0 through 99 yields 480; negative 499 through negative 1 yields
        600; negative 999 through negative 500 yields 750; and negative 1000 or below
        yields 900. `final_rate_bp` is the bracket value plus the agency's
        `solvency_surcharge_bp`, then clamped to never fall below the floor of 50 nor
        exceed the ceiling of 900."
        PRD §3.7: "the standard variant, when no voluntary contribution has been
        applied, excludes them from the ratio"

        Design: Difficulty/dual_variant_calc/ui_rate_standard_vs_buydown_diverge
        """
        out = setup_ui_rate_effective(account_number="PA-UI-0001")
        rate = out["ui_rate"]
        assert rate["reserve_ratio_bp"] == 400, (
            "round_half_up(10000 * (600,000 - 200,000) / 10,000,000) == 400"
        )
        assert rate["final_rate_bp"] == 390, "bracket 360 + surcharge 30"
        assert rate["status"] == "EFFECTIVE"

    def test_ui_rate_buydown_variant_drops_to_270(self, api, ui_specialist_headers,
                                                  tax_director_headers):
        """PRD §3.7: "the buy-down variant adds applied contributions, raising the
        ratio and potentially dropping the bracket — identical base data then yields a
        lower `final_rate_bp`."
        PRD §3.7: "the proposed amount is added to the rate's
        `voluntary_contribution_applied_cents`, `reserve_ratio_bp` and `final_rate_bp`
        recompute under the buy-down variant"

        Design: Difficulty/dual_variant_calc/ui_rate_standard_vs_buydown_diverge
        """
        out = setup_ui_rate_effective(account_number="PA-UI-0001")
        rate = out["ui_rate"]
        assert rate["final_rate_bp"] == 390
        vc = propose_vc(rate["id"], proposed_amount_cents=100_000)
        approve_vc(vc["id"])
        remit_vc(vc["id"])
        apply_vc(vc["id"])
        after = get_success_data(api.get_ui_rate(rate["id"], tax_director_headers))
        assert after["voluntary_contribution_applied_cents"] == 100_000
        assert after["reserve_ratio_bp"] == 500
        assert after["final_rate_bp"] == 270, (
            "reserve 500bp -> bracket 240 + surcharge 30; buy-down diverges from 390"
        )


class TestExperienceRateBracketMath:
    def test_ui_rate_negative_reserve_ratio_computed(self, api):
        """PRD §3.7: "Otherwise `reserve_ratio_bp` is ten thousand times the net
        reserve — contributions paid plus `voluntary_contribution_applied_cents` (the
        running total of applied voluntary contributions against this rate year,
        starting at zero) minus benefits charged — divided by
        `taxable_payroll_3yr_cents`, rounded half up; the ratio may be negative."

        Design: Difficulty/combinatorial_formula/ui_experience_rate_multi_input_bracket
        """
        out = setup_ui_rate_effective(
            account_number="PA-UI-0002",
            employee_wages=(6_000_000,),
            rate_overrides={
                "assigned_rate_bp": 700,
                "contributions_paid_3yr_cents": 100_000,
                "benefits_charged_3yr_cents": 500_000,
                "taxable_payroll_3yr_cents": 10_000_000,
            },
        )
        rate = out["ui_rate"]
        assert rate["reserve_ratio_bp"] == -400, (
            "round_half_up(10000 * (100,000 - 500,000) / 10,000,000) == -400"
        )

    def test_ui_rate_bracket_plus_surcharge_final_630(self, api):
        """PRD §3.7: "The ratio selects a bracket: a ratio of at least 1500 yields 50;
        1000 through 1499 yields 120; 500 through 999 yields 240; 100 through 499
        yields 360; 0 through 99 yields 480; negative 499 through negative 1 yields
        600; negative 999 through negative 500 yields 750; and negative 1000 or below
        yields 900. `final_rate_bp` is the bracket value plus the agency's
        `solvency_surcharge_bp`, then clamped to never fall below the floor of 50 nor
        exceed the ceiling of 900."

        Design: Difficulty/combinatorial_formula/ui_experience_rate_multi_input_bracket
        """
        out = setup_ui_rate_effective(
            account_number="PA-UI-0002",
            employee_wages=(6_000_000,),
            rate_overrides={
                "assigned_rate_bp": 700,
                "contributions_paid_3yr_cents": 100_000,
                "benefits_charged_3yr_cents": 500_000,
                "taxable_payroll_3yr_cents": 10_000_000,
            },
        )
        rate = out["ui_rate"]
        assert rate["reserve_ratio_bp"] == -400
        assert rate["final_rate_bp"] == 630, (
            "reserve -400 -> bracket 600, + 30 solvency surcharge, within [50, 900]"
        )


class TestNewEmployerRate:
    def test_new_employer_rate_flat_and_reserve_null(self, api):
        """PRD §3.7: "For a new-employer account — `experience_rated` false —
        `reserve_ratio_bp` is null and `final_rate_bp` is simply the agency's
        `new_employer_rate_bp`, full stop"

        Design: Corner/validations/vc_new_employer_rate_prohibited
        """
        out = setup_ui_registration_active(
            account_number="PA-UI-0008", employee_wages=(3_000_000,),
        )
        rate = create_effective_ui_rate(
            out["registration"]["id"], out["registration_version"],
            experience_rated=False, assigned_rate_bp=270,
            contributions_paid_3yr_cents=0, benefits_charged_3yr_cents=0,
            taxable_payroll_3yr_cents=1,
        )
        assert rate["final_rate_bp"] == 270
        assert rate["reserve_ratio_bp"] is None

    def test_vc_against_new_employer_rate_prohibited(self, api):
        """PRD §3.7: "voluntary contributions against such a rate are rejected with
        `ERR_VC_NOT_ALLOWED_NEW_EMPLOYER`."

        Design: Corner/validations/vc_new_employer_rate_prohibited
        """
        out = setup_ui_registration_active(
            account_number="PA-UI-0008", employee_wages=(3_000_000,),
        )
        rate = create_effective_ui_rate(
            out["registration"]["id"], out["registration_version"],
            experience_rated=False, assigned_rate_bp=270,
            contributions_paid_3yr_cents=0, benefits_charged_3yr_cents=0,
            taxable_payroll_3yr_cents=1,
        )
        res = api.create_voluntary_contribution(
            {
                "ui_rate_id": rate["id"],
                "proposed_amount_cents": 100_000,
                "decision_deadline": "2026-12-01T00:00:00Z",
            },
            SPECIALIST,
        )
        validate_error(res, ApiErrorId.ERR_VC_NOT_ALLOWED_NEW_EMPLOYER)


class TestNewEmployerObligationFallback:
    def test_ui_contribution_uses_new_employer_rate_without_effective_rate(self, api):
        """PRD §3.8: "The effective rate is the registration's `EFFECTIVE` UIRate whose
        `rate_year` matches the year of the quarter's start, falling back to the
        agency's `new_employer_rate_bp` when no such rate exists."

        Design: Corner/calculations/ui_contribution_new_employer_rate_fallback
        """
        out = setup_ui_registration_active(
            account_number="PA-UI-0007", employee_wages=(6_000_000,),
        )
        contributions = get_obligations(
            out["registration"]["id"], obligation_kind="UI_CONTRIBUTION",
        )
        assert len(contributions) == 1, "one UI_CONTRIBUTION row for Q3 2026"
        assert contributions[0]["amount_due_cents"] == 27_074, (
            "ytd_wages(2026-09-30) = round_half_up(6,000,000 * 61 / 365) = 1,002,740 "
            "(under the 5,000,000-cent wage base); line = round_half_up(1,002,740 * "
            "270 / 10,000) = 27,074 at the 270bp new-employer fallback rate"
        )

    def test_state_ui_registration_forced_quarterly(self, api):
        """PRD §3.4: "A `STATE_UI` registration always files `QUARTERLY`."

        Design: Corner/calculations/ui_contribution_new_employer_rate_fallback
        """
        out = setup_ui_registration_active(
            account_number="PA-UI-0007", employee_wages=(6_000_000,),
            projected=0,
        )
        assert out["registration"]["filing_frequency"] == "QUARTERLY"
        assert out["registration"]["registration_kind"] == "STATE_UI"


class TestUIRateKindAndSupersede:
    def test_uirate_on_withholding_registration_kind_mismatch(self, api, ui_specialist_headers):
        """PRD §3.7: "a `UISpecialist` intakes it as a UIRate against an `ACTIVE`
        `STATE_UI` registration (a registration of any other kind is rejected with
        `ERR_AGENCY_KIND_MISMATCH`)."

        Design: Corner/validations/uirate_on_withholding_registration_kind_mismatch
        """
        out = setup_withholding_registration_active(
            projected=200_000, account_number="OR-00000017",
            employee_wages=(3_000_000,),
        )
        registration = out["registration"]
        res = api.create_ui_rate(
            create_ui_rate_payload(registration["id"], registration["version"]),
            ui_specialist_headers,
        )
        validate_error(res, ApiErrorId.ERR_AGENCY_KIND_MISMATCH)

    def test_occ_uirate_create_stale_registration(self, api, ui_specialist_headers):
        """PRD §2.8: "Intaking a UIRate (`POST /etax/ui-rates`) requires
        `expected_registration_version` matching the Registration's current `version`,
        since intake legitimately supersedes the current rate for the same registration
        and rate year."
        PRD §2.8: "if that value does not match the parent entity's current `version`,
        the write is rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_layers/occ_uirate_create_stale_registration
        """
        out = setup_ui_registration_active(
            account_number="PA-UI-0012", employee_wages=(3_000_000,),
        )
        registration = out["registration"]
        observed_version = registration["version"]
        first = api.create_ui_rate(
            create_ui_rate_payload(registration["id"], observed_version),
            ui_specialist_headers,
        )
        validate_success(first, 201)
        fresh = get_success_data(
            api.get_registration(registration["id"], ui_specialist_headers)
        )
        assert fresh["version"] == observed_version + 1, (
            "PRD §3.7: 'intake increments the registration's `version`'"
        )
        stale = api.create_ui_rate(
            create_ui_rate_payload(
                registration["id"], observed_version,
                assigned_rate_bp=400, contributions_paid_3yr_cents=650_000,
            ),
            ui_specialist_headers,
        )
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION)

    def test_vc_apply_on_superseded_rate_rejected(self, api, ui_specialist_headers):
        """PRD §3.7: "Intaking a rate for a registration and `rate_year` that already
        has one supersedes the existing rate — whether it is `RECEIVED`,
        `UNDER_REVIEW`, `CONTESTED`, or `EFFECTIVE`, each moves to `SUPERSEDED`;
        voluntary contributions still `PROPOSED`, `APPROVED`, or `REMITTED` against the
        superseded rate remain on the books, but applying them is blocked with
        `ERR_RATE_SUPERSEDED`."

        Design: Corner/validations/vc_apply_on_superseded_rate_rejected
        """
        out = setup_ui_rate_effective(account_number="PA-UI-0009")
        rate_a = out["ui_rate"]
        vc = propose_vc(rate_a["id"], proposed_amount_cents=100_000)
        approve_vc(vc["id"])
        remit_vc(vc["id"])
        registration = get_success_data(
            api.get_registration(out["registration"]["id"], ui_specialist_headers)
        )
        rate_b = validate_success(
            api.create_ui_rate(
                create_ui_rate_payload(
                    out["registration"]["id"], registration["version"],
                    assigned_rate_bp=400, contributions_paid_3yr_cents=650_000,
                ),
                ui_specialist_headers,
            ),
            201,
        )
        assert rate_b["id"] != rate_a["id"]
        rate_a_after = get_success_data(api.get_ui_rate(rate_a["id"], ui_specialist_headers))
        assert rate_a_after["status"] == "SUPERSEDED"
        res = api.apply_voluntary_contribution(vc["id"], ui_specialist_headers)
        validate_error(res, ApiErrorId.ERR_RATE_SUPERSEDED)
