"""Engineering reviews: safety-factor boundary, structural vs automation
variants, segregation of duties, revision loop."""
import pytest

from test_helpers import (
    ENGINEER,
    EST,
    FOREMAN,
    FOREMAN_9,
    ApiErrorId,
    assert_engineering_review,
    create_engineering_review_payload,
    get_success_data,
    make_client_pm_headers,
    make_shop_foreman_headers,
    make_staff_engineer_headers,
    setup_accepted_production,
    setup_in_build_production,
    validate_error,
    validate_success,
)


class TestSafetyFactorBoundary:
    def test_sf_exactly_one_five_passes(self, api):
        """PRD §3.4: "the static factor must be at least 1.50 (a value of
        exactly 1.50 passes) ... failing with `ERR_SAFETY_FACTOR_INSUFFICIENT`
        (HTTP 422)."

        Design: Difficulty/boundary_precision_check/safety_factor_exactly_one_five_passes
        """
        _, _, _, _, production = setup_accepted_production()
        rev = get_success_data(api.create_engineering_review(
            {"production_id": production["id"], "scope": "STRUCTURAL",
             "design_load_lb": 4000, "member_capacity_lb": 6000},
            FOREMAN,
        ))
        assert rev["sf_static"] == pytest.approx(1.5, abs=0.001)
        resp = api.approve_engineering_review(rev["id"], ENGINEER)
        approved = validate_success(resp)
        assert approved["status"] == "APPROVED"

    def test_sf_rounds_to_two_decimals_half_up(self, api):
        """PRD §3.4: "Two safety factors are computed at creation and at every
        resubmission, each rounded half-up to two decimal places. `sf_static`
        is `member_capacity_lb` divided by `design_load_lb`."

        Design: Corner/calculations/safety_factor_rounds_to_two_decimals_half_up
        """
        _, _, _, _, production = setup_accepted_production()
        rev = get_success_data(api.create_engineering_review(
            {"production_id": production["id"], "scope": "STRUCTURAL",
             "design_load_lb": 3000, "member_capacity_lb": 10000},
            FOREMAN,
        ))
        # round_half_up(10000/3000, 2) = 3.33
        assert rev["sf_static"] == pytest.approx(3.33, abs=0.001)
        resp = api.approve_engineering_review(rev["id"], ENGINEER)
        approved = validate_success(resp)
        assert approved["status"] == "APPROVED"


class TestStructuralVsAutomation:
    def test_structural_passes_where_automation_fails(self, api):
        """PRD §3.4: "For `AUTOMATION` reviews, the load is amplified before
        division: the effective load is `design_load_lb` multiplied by
        `impact_factor_bp`, divided by 10000, rounded half-up to two decimals,
        and `sf_dynamic` is `member_capacity_lb` divided by that effective
        load, again rounded half-up to two decimals. ... Identical numbers
        that pass a `STRUCTURAL` review can fail an `AUTOMATION` one."

        Design: Difficulty/dual_variant_calc/safety_factor_structural_vs_automation_same_members
        """
        _, _, _, _, production = setup_accepted_production(has_automation_scope=True)
        rev_s = get_success_data(api.create_engineering_review(
            {"production_id": production["id"], "scope": "STRUCTURAL",
             "design_load_lb": 4000, "member_capacity_lb": 6000},
            FOREMAN,
        ))
        rev_a = get_success_data(api.create_engineering_review(
            {"production_id": production["id"], "scope": "AUTOMATION",
             "design_load_lb": 4000, "member_capacity_lb": 6000,
             "impact_factor_bp": 15000},
            FOREMAN,
        ))
        # sf_dynamic = 6000 / (4000*1.5) = 6000/6000 = 1.00 < 2.00
        assert rev_a["sf_dynamic"] == pytest.approx(1.0, abs=0.001)
        # STRUCTURAL approve succeeds
        resp_s = api.approve_engineering_review(rev_s["id"], ENGINEER)
        assert validate_success(resp_s)["status"] == "APPROVED"
        # AUTOMATION approve rejected
        resp_a = api.approve_engineering_review(rev_a["id"], ENGINEER)
        validate_error(resp_a, ApiErrorId.ERR_SAFETY_FACTOR_INSUFFICIENT, 422)
        after = get_success_data(api.get_engineering_review(rev_a["id"], ENGINEER))
        assert after["status"] == "PENDING"

    def test_automation_sf_dynamic_boundary(self, api):
        """PRD §3.4: "for `AUTOMATION`, the dynamic factor must be at least
        2.00 (exactly 2.00 passes)."

        Design: Difficulty/dual_variant_calc/safety_factor_structural_vs_automation_same_members
        """
        _, _, _, _, production = setup_accepted_production(has_automation_scope=True)
        # sf_dynamic exactly 2.00: capacity / (load * factor) = 2.00
        # e.g. load 4000, factor 10000 -> effective 4000; capacity 8000 -> 2.00
        rev = get_success_data(api.create_engineering_review(
            {"production_id": production["id"], "scope": "AUTOMATION",
             "design_load_lb": 4000, "member_capacity_lb": 8000,
             "impact_factor_bp": 10000},
            FOREMAN,
        ))
        assert rev["sf_dynamic"] == pytest.approx(2.0, abs=0.001)
        resp = api.approve_engineering_review(rev["id"], ENGINEER)
        assert validate_success(resp)["status"] == "APPROVED"


class TestSegregationOfDuties:
    def test_approve_by_preparer_fails(self, api):
        """PRD §3.4: "the approver must not be the user recorded as
        `prepared_by_user_id` — segregation of duties, failing with
        `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

        Design: Corner/validations/review_approve_segregation_of_duties
        """
        _, _, _, _, production = setup_accepted_production()
        rev = get_success_data(api.create_engineering_review(
            {"production_id": production["id"], "scope": "STRUCTURAL",
             "design_load_lb": 4000, "member_capacity_lb": 6000},
            make_staff_engineer_headers("eng_1"),
        ))
        resp = api.approve_engineering_review(
            rev["id"], make_staff_engineer_headers("eng_1"),
        )
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, 403)

    def test_approve_by_different_engineer_succeeds(self, api):
        """PRD §3.4: "the approver must not be the user recorded as
        `prepared_by_user_id`."

        Design: Corner/validations/review_approve_segregation_of_duties
        """
        _, _, _, _, production = setup_accepted_production()
        rev = get_success_data(api.create_engineering_review(
            {"production_id": production["id"], "scope": "STRUCTURAL",
             "design_load_lb": 4000, "member_capacity_lb": 6000},
            make_staff_engineer_headers("eng_1"),
        ))
        resp = api.approve_engineering_review(
            rev["id"], make_staff_engineer_headers("eng_2"),
        )
        assert validate_success(resp)["status"] == "APPROVED"


class TestResubmitPreparerOnly:
    def test_resubmit_by_non_preparer_returns_403(self, api):
        """PRD §3.4: "The preparer alone resubmits: a `ShopForeman` or
        `StaffEngineer` whose `X-User-ID` equals `prepared_by_user_id`
        (otherwise `ERR_NOT_OWN_RESOURCE`)."

        Design: Corner/validations/review_resubmit_by_non_preparer_returns_403
        """
        _, _, _, _, production = setup_accepted_production()
        rev = get_success_data(api.create_engineering_review(
            {"production_id": production["id"], "scope": "STRUCTURAL",
             "design_load_lb": 5000, "member_capacity_lb": 6000},
            make_shop_foreman_headers("foreman_1"),
        ))
        api.request_revision_engineering_review(
            rev["id"], {"revision_note": "Recheck"}, ENGINEER,
        )
        # Wrong user attempts resubmit
        resp = api.resubmit_engineering_review(
            rev["id"],
            {"design_load_lb": 4000, "member_capacity_lb": 6000},
            make_shop_foreman_headers("foreman_9"),
        )
        validate_error(resp, ApiErrorId.ERR_NOT_OWN_RESOURCE, 403)

    def test_resubmit_by_preparer_succeeds_and_bumps_round(self, api):
        """PRD §3.4: "the review returns `REVISION_REQUIRED → PENDING`, both
        safety factors are recomputed, and `round_no` increments by 1."

        Design: Corner/validations/review_resubmit_by_non_preparer_returns_403
        """
        _, _, _, _, production = setup_accepted_production()
        rev = get_success_data(api.create_engineering_review(
            {"production_id": production["id"], "scope": "STRUCTURAL",
             "design_load_lb": 5000, "member_capacity_lb": 6000},
            make_shop_foreman_headers("foreman_1"),
        ))
        api.request_revision_engineering_review(
            rev["id"], {"revision_note": "Recheck"}, ENGINEER,
        )
        resp = api.resubmit_engineering_review(
            rev["id"],
            {"design_load_lb": 4000, "member_capacity_lb": 6000},
            make_shop_foreman_headers("foreman_1"),
        )
        after = validate_success(resp)
        assert after["status"] == "PENDING"
        assert after["round_no"] == 2


class TestRevisionLoopBubblesProduction:
    def test_request_revision_holds_in_build_production(self, api):
        """PRD §3.4: "When a `StaffEngineer` requests a revision, supplying a
        `revision_note`, the review moves `PENDING → REVISION_REQUIRED`, the
        note is recorded, and if the production is currently `IN_BUILD` it
        transitions to `ON_HOLD`."

        Design: Difficulty/non_linear_state_machine/engineering_review_revision_loop_bubbles_production_hold
        """
        shop, client, pkg, bid, production, rev_1, res = setup_in_build_production()
        # Production now IN_BUILD; create second review and kick it back
        rev_2 = get_success_data(api.create_engineering_review(
            {"production_id": production["id"], "scope": "STRUCTURAL",
             "design_load_lb": 5000, "member_capacity_lb": 6000},
            FOREMAN,
        ))
        api.request_revision_engineering_review(
            rev_2["id"], {"revision_note": "Recheck connection loads"}, ENGINEER,
        )
        prod_after = get_success_data(api.get_production(production["id"], EST))
        assert prod_after["status"] == "ON_HOLD"
        rev_after = get_success_data(api.get_engineering_review(rev_2["id"], ENGINEER))
        assert rev_after["status"] == "REVISION_REQUIRED"
        assert rev_after["revision_note"] == "Recheck connection loads"

    def test_final_approve_bubbles_production_back_to_in_build(self, api):
        """PRD §3.4: "When an approval lands and the production is `ON_HOLD`
        and every engineering review of the production is now `APPROVED`, the
        production automatically returns `ON_HOLD → IN_BUILD`."

        Design: Difficulty/non_linear_state_machine/engineering_review_revision_loop_bubbles_production_hold
        """
        shop, client, pkg, bid, production, rev_1, res = setup_in_build_production()
        rev_2 = get_success_data(api.create_engineering_review(
            {"production_id": production["id"], "scope": "STRUCTURAL",
             "design_load_lb": 5000, "member_capacity_lb": 6000},
            FOREMAN,
        ))
        api.request_revision_engineering_review(
            rev_2["id"], {"revision_note": "Recheck"}, ENGINEER,
        )
        api.resubmit_engineering_review(
            rev_2["id"],
            {"design_load_lb": 4000, "member_capacity_lb": 6000},
            FOREMAN,
        )
        rev_mid = get_success_data(api.get_engineering_review(rev_2["id"], ENGINEER))
        assert rev_mid["status"] == "PENDING"
        assert rev_mid["round_no"] == 2
        api.approve_engineering_review(rev_2["id"], ENGINEER)
        prod_after = get_success_data(api.get_production(production["id"], EST))
        assert prod_after["status"] == "IN_BUILD"
        rev_after = get_success_data(api.get_engineering_review(rev_2["id"], ENGINEER))
        assert rev_after["status"] == "APPROVED"


class TestStartBuildGate:
    def test_start_build_fails_without_approved_review(self, api):
        """PRD §3.4: "for every scope in the production's
        `required_review_scopes` there must exist an `APPROVED` engineering
        review for this production with that scope — otherwise the start is
        rejected with `ERR_ENGINEERING_NOT_APPROVED` (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/start_build_requires_engineering_approved
        """
        _, _, _, _, production = setup_accepted_production()
        # Reserve bay so only engineering gate can fail
        get_success_data(api.create_bay_reservation(
            {"production_id": production["id"], "bay_slot": 1,
             "window_start": "2026-09-01T00:00:00Z",
             "window_end": "2026-09-26T00:00:00Z"},
            FOREMAN,
        ))
        resp = api.start_build(production["id"], FOREMAN)
        validate_error(resp, ApiErrorId.ERR_ENGINEERING_NOT_APPROVED, 409)

    def test_start_build_succeeds_after_review_approved(self, api):
        """PRD §3.4: "On success the production moves `SCHEDULED → IN_BUILD`."

        Design: Difficulty/cross_entity_state_dependency/start_build_requires_engineering_approved
        """
        _, _, _, _, production = setup_accepted_production()
        rev = get_success_data(api.create_engineering_review(
            {"production_id": production["id"], "scope": "STRUCTURAL",
             "design_load_lb": 4000, "member_capacity_lb": 6000},
            FOREMAN,
        ))
        api.approve_engineering_review(rev["id"], ENGINEER)
        get_success_data(api.create_bay_reservation(
            {"production_id": production["id"], "bay_slot": 1,
             "window_start": "2026-09-01T00:00:00Z",
             "window_end": "2026-09-26T00:00:00Z"},
            FOREMAN,
        ))
        resp = api.start_build(production["id"], FOREMAN)
        assert validate_success(resp)["status"] == "IN_BUILD"
