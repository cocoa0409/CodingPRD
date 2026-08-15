"""Manure planning and land application: the plan revision cycle, plan-year
exclusivity, lagoon/nutrient fiscal gates, the regulated season window, and
record/void budget conservation.
"""
from test_helpers import (
    ApiErrorId,
    assert_manure_application,
    get_success_data,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import (
    ADMIN,
    ENVMGR,
    create_site,
    get_plan,
    record_application,
    set_clock,
    setup_approved_manure_plan,
    setup_manure_plan,
)
from test_helpers.factories import create_manure_plan_payload
from test_helpers.test_users import make_envmgr_headers


class TestPlanLifecycle:
    def test_manure_plan_revision_cycle(self, api):
        """PRD §3.9: "Rejection is not the end: the `EnvironmentalManager` may
        revise, moving the plan `REJECTED` → `DRAFT`, and the loop from
        `SUBMITTED` through `REJECTED` back to `DRAFT` and on to `SUBMITTED`
        may repeat as often as needed."
        PRD §3.9: "Submission moves a plan `DRAFT` → `SUBMITTED`, stamping
        `submitted_by`".

        Design: Corner/state_machines/manure_plan_revision_cycle
        """
        _site, plan = setup_manure_plan()
        get_success_data(
            api.submit_manure_plan(plan["id"], make_envmgr_headers("em_1"))
        )
        rejected = validate_success(api.reject_manure_plan(plan["id"], ADMIN), 200)
        assert rejected["plan_status"] == "REJECTED"

        revised = validate_success(api.revise_manure_plan(plan["id"], ENVMGR), 200)
        assert revised["plan_status"] == "DRAFT"

        resubmitted = validate_success(
            api.submit_manure_plan(plan["id"], make_envmgr_headers("em_2")), 200
        )
        assert resubmitted["plan_status"] == "SUBMITTED"
        assert resubmitted["submitted_by"] == "em_2"

    def test_plan_year_overlap_rejected(self, api):
        """PRD §3.9: "Submission moves a plan `DRAFT` → `SUBMITTED`, stamping
        `submitted_by`, and is permitted only while no other plan for the same
        site and `plan_year` sits in `SUBMITTED` or `APPROVED`
        (`ERR_PLAN_YEAR_OVERLAP`)."

        Design: Corner/errors/plan_year_overlap_rejected
        """
        site, plan_a = setup_manure_plan()
        get_success_data(api.submit_manure_plan(plan_a["id"], ENVMGR))

        plan_b = validate_success(
            api.create_manure_plan(
                create_manure_plan_payload(
                    site["id"], lagoon_start_gal=900000, n_budget_lbs=45000,
                    p_budget_lbs=35000,
                ),
                ENVMGR,
            ),
            201,
        )
        res = api.submit_manure_plan(plan_b["id"], ENVMGR)
        validate_error(res, ApiErrorId.ERR_PLAN_YEAR_OVERLAP, expected_status=409)
        assert get_plan(plan_b["id"])["plan_status"] == "DRAFT"


class TestFiscalGates:
    def test_lagoon_over_capacity_rejected(self, api):
        """PRD §3.9: "The starting volume must not exceed the lagoon's capacity
        — a plan whose `lagoon_start_gal` tops its `lagoon_capacity_gal` is
        rejected with `ERR_LAGOON_OVER_CAPACITY`."

        Design: Corner/errors/lagoon_over_capacity_rejected
        """
        site = create_site()
        res = api.create_manure_plan(
            create_manure_plan_payload(
                site["id"], lagoon_capacity_gal=2000000,
                lagoon_start_gal=2000001,
            ),
            ENVMGR,
        )
        validate_error(res, ApiErrorId.ERR_LAGOON_OVER_CAPACITY,
                       expected_status=409)

    def test_nutrient_budget_and_lagoon_draw_rejected(self, api):
        """PRD §3.9: "Three budget gates guard creation, evaluated in a fixed
        order. First nitrogen: if the plan's `n_applied_lbs` plus the new
        `n_lbs` would exceed `n_budget_lbs`, the application is rejected with
        `ERR_NUTRIENT_BUDGET_EXCEEDED`. Then phosphorus, symmetrically:
        `p_applied_lbs` plus `p_lbs` against `p_budget_lbs`, same error. Then
        lagoon volume: if the new `gallons` exceeds the plan's
        `lagoon_available_gal`, the application is rejected with
        `ERR_LAGOON_INSUFFICIENT`."

        Design: Corner/errors/nutrient_budget_and_lagoon_draw_rejected
        """
        _site, plan = setup_approved_manure_plan(n_budget_lbs=5000,
                                                 p_budget_lbs=4000)

        res = api.create_manure_application(
            {
                "plan_id": plan["id"], "field_code": "F-1",
                "applied_at": "2026-07-15T10:00:00Z", "gallons": 1000,
                "n_lbs": 6000, "p_lbs": 10,
            },
            ENVMGR,
        )
        validate_error(res, ApiErrorId.ERR_NUTRIENT_BUDGET_EXCEEDED,
                       expected_status=409)

        # N and P inside budgets; the lagoon draw alone fires.
        res = api.create_manure_application(
            {
                "plan_id": plan["id"], "field_code": "F-1",
                "applied_at": "2026-07-15T10:00:00Z", "gallons": 1000001,
                "n_lbs": 0, "p_lbs": 0,
            },
            ENVMGR,
        )
        validate_error(res, ApiErrorId.ERR_LAGOON_INSUFFICIENT,
                       expected_status=409)

        plan_after = get_plan(plan["id"])
        assert plan_after["n_applied_lbs"] == 0
        assert plan_after["p_applied_lbs"] == 0
        assert plan_after["lagoon_available_gal"] == 1000000

    def test_application_on_unapproved_plan_rejected(self, api):
        """PRD §3.9: "An `EnvironmentalManager` records an application against
        an `APPROVED` plan — applying against a plan in any other status fails
        with `ERR_PLAN_NOT_APPROVED`".

        Design: Corner/errors/application_on_unapproved_plan_rejected
        """
        _site, plan = setup_manure_plan()  # DRAFT
        res = api.create_manure_application(
            {
                "plan_id": plan["id"], "field_code": "F-1",
                "applied_at": "2026-07-15T10:00:00Z", "gallons": 1000,
                "n_lbs": 40, "p_lbs": 30,
            },
            ENVMGR,
        )
        validate_error(res, ApiErrorId.ERR_PLAN_NOT_APPROVED, expected_status=409)


class TestSeasonWindow:
    def test_manure_application_december_window_rejected(self, api):
        """PRD §3.9: "The application season is regulated: `applied_at` must
        fall within the plan year's window from March 1 through November 30,
        inclusive, and must not lie in the future
        (`ERR_APPLICATION_OUTSIDE_WINDOW`)."

        2026-12-10 is outside the 2026 season even with budgets available.

        Design: Corner/validations/manure_application_december_window_rejected
        """
        _site, plan = setup_approved_manure_plan()
        set_clock("2026-12-15T00:00:00Z")
        res = api.create_manure_application(
            {
                "plan_id": plan["id"], "field_code": "F-1",
                "applied_at": "2026-12-10T10:00:00Z", "gallons": 1000,
                "n_lbs": 40, "p_lbs": 30,
            },
            ENVMGR,
        )
        validate_error(res, ApiErrorId.ERR_APPLICATION_OUTSIDE_WINDOW,
                       expected_status=409)
        plan_after = get_plan(plan["id"])
        assert plan_after["lagoon_available_gal"] == 1000000
        assert plan_after["n_applied_lbs"] == 0


class TestRecordVoidConservation:
    def test_manure_budget_record_void_conserved(self, api):
        """PRD §3.9: "The tracked totals aggregate applications in `RECORDED`
        or `CONFIRMED` status only: `n_applied_lbs` and `p_applied_lbs` sum the
        corresponding nutrient loads, and `lagoon_available_gal` is the
        `lagoon_start_gal` minus the summed gallons of that same set."
        PRD §3.9: "An application is later confirmed — `RECORDED` → `CONFIRMED`
        — or voided; voiding from either `RECORDED` or `CONFIRMED` moves it to
        the terminal `VOIDED`, removes it from every aggregate, and credits the
        plan back, subtracting its nutrients from `n_applied_lbs` and
        `p_applied_lbs` and returning its gallons to `lagoon_available_gal`."

        Record (50000 gal / 2000 N / 1500 P) then void restores all three pools
        exactly.

        Design: Difficulty/compensating_invariant/manure_budget_record_void_conserved
        """
        _site, plan = setup_approved_manure_plan()
        assert plan["lagoon_available_gal"] == 1000000
        assert plan["n_applied_lbs"] == 0
        assert plan["p_applied_lbs"] == 0

        app = record_application(
            plan["id"], applied_at="2026-07-15T10:00:00Z", gallons=50000,
            n_lbs=2000, p_lbs=1500,
        )
        assert_manure_application(app)
        mid = get_plan(plan["id"])
        assert mid["lagoon_available_gal"] == 950000
        assert mid["n_applied_lbs"] == 2000
        assert mid["p_applied_lbs"] == 1500

        voided = validate_success(api.void_manure_application(app["id"], ENVMGR), 200)
        assert voided["application_status"] == "VOIDED"
        end = get_plan(plan["id"])
        assert end["lagoon_available_gal"] == 1000000
        assert end["n_applied_lbs"] == 0
        assert end["p_applied_lbs"] == 0

    def test_confirm_then_void_also_restores_budgets(self, api):
        """PRD §3.9: "voiding from either `RECORDED` or `CONFIRMED` moves it to
        the terminal `VOIDED`, removes it from every aggregate, and credits the
        plan back, subtracting its nutrients from `n_applied_lbs` and
        `p_applied_lbs` and returning its gallons to `lagoon_available_gal`."

        The compensating path from CONFIRMED restores the pools exactly as the
        path from RECORDED does.

        Design: Difficulty/compensating_invariant/manure_budget_record_void_conserved
        """
        _site, plan = setup_approved_manure_plan()
        app = record_application(
            plan["id"], applied_at="2026-07-15T10:00:00Z", gallons=50000,
            n_lbs=2000, p_lbs=1500,
        )
        confirmed = validate_success(
            api.confirm_manure_application(app["id"], ENVMGR), 200
        )
        assert confirmed["application_status"] == "CONFIRMED"
        mid = get_plan(plan["id"])
        assert mid["lagoon_available_gal"] == 950000
        assert mid["n_applied_lbs"] == 2000

        voided = validate_success(api.void_manure_application(app["id"], ENVMGR), 200)
        assert voided["application_status"] == "VOIDED"
        end = get_plan(plan["id"])
        assert end["lagoon_available_gal"] == 1000000
        assert end["n_applied_lbs"] == 0
        assert end["p_applied_lbs"] == 0
