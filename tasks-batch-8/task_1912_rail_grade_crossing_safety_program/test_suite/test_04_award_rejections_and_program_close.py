"""Award rejection rules and program close guard (PRD §2.9, §3.4)."""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    create_crossing,
    create_eligible_project,
    create_locality,
    create_program,
    create_project,
    get_success_data,
    validate_error,
)

ADMIN = TEST_USERS["admin_headers"]
OFFICER = TEST_USERS["officer_headers"]


def _crossing(locality_id, dot, bus=6):
    return create_crossing(
        locality_id,
        dot_crossing_number=dot,
        annual_train_count=365,
        train_speed_max_mph=25,
        aadt=5000,
        school_bus_count=bus,
        sight_distance_rating=3,
        warning_device_class="GATES",
    )


class TestAwardValidationConflicts:
    def test_award_on_proposed_project_reports_state_error_over_fiscal(
        self, api, admin_headers
    ):
        """PRD §2.9: "4. **State eligibility** — the target entity must be in a
        from-state the requested transition or action allows, else
        `ERR_INVALID_STATE_TRANSITION`; cross-entity state gates live here too ...
        and `ERR_PROJECT_NOT_SELECTED` when an award targets a project that is
        neither `ELIGIBLE` nor `SELECTED`."
        PRD §2.9: "10. **Fiscal rules** — `ERR_INSUFFICIENT_FUNDS` on awards, and
        the incentive cap (`ERR_INCENTIVE_CAP_EXCEEDED`) and counter-direction
        (`ERR_INCENTIVE_REGRESSION`) rules on closure counters." The ordering is
        observable (state step 4 outranks fiscal step 10).

        Design: Difficulty/priority_pair_validation_conflict/award_state_check_beats_fiscal_check
        """
        locality = create_locality(locality_name="Priority City")
        cx = _crossing(locality["id"], "DOT-500001")
        prog = create_program(
            fiscal_year=2031,
            apportionment_cents=100_000,
            allocation_method="WATERFALL_BY_RANK",
        )
        pj = create_project(cx["id"], prog["id"], estimated_cost_cents=600_000)
        assert pj["status"] == "PROPOSED"

        # Both violations hold: project PROPOSED (state) and pool 100000 < 600000
        # (fiscal). The state error must win.
        resp = api.award_upgrade_project(
            pj["id"],
            {"expected_funding_program_version": prog["version"]},
            admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_PROJECT_NOT_SELECTED, expected_status=409)

    def test_award_on_proposed_project_rejected_even_with_ample_pool(
        self, api, admin_headers
    ):
        """PRD §3.4: "The project must be `ELIGIBLE` or `SELECTED` (else
        `ERR_PROJECT_NOT_SELECTED`)".

        Design: Difficulty/priority_pair_validation_conflict/award_state_check_beats_fiscal_check
        """
        locality = create_locality(locality_name="Priority City")
        cx = _crossing(locality["id"], "DOT-500002")
        prog = create_program(
            fiscal_year=2035,
            apportionment_cents=10_000_000,
            allocation_method="WATERFALL_BY_RANK",
        )
        pj = create_project(cx["id"], prog["id"], estimated_cost_cents=600_000)

        resp = api.award_upgrade_project(
            pj["id"],
            {"expected_funding_program_version": prog["version"]},
            admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_PROJECT_NOT_SELECTED, expected_status=409)
        pj_after = get_success_data(api.get_upgrade_project(pj["id"], admin_headers))
        assert pj_after["status"] == "PROPOSED"
        prog_after = get_success_data(api.get_funding_program(prog["id"], admin_headers))
        assert prog_after["available_cents"] == 10_000_000


class TestAwardFiscalAndBounds:
    def test_rolling_award_above_available_pool_rejected(self, api, admin_headers):
        """PRD §3.4: "it must lie between 1 and the `estimated_cost_cents`
        inclusive (else `ERR_AWARD_AMOUNT_INVALID`) and must not exceed the
        program's `available_cents` (else `ERR_INSUFFICIENT_FUNDS`, HTTP 402)."

        Design: Corner/validations/insufficient_funds_on_rolling_award
        """
        locality = create_locality(locality_name="Broke City")
        cx = _crossing(locality["id"], "DOT-040041")
        prog = create_program(
            fiscal_year=2043,
            apportionment_cents=100_000,
            allocation_method="WATERFALL_BY_RANK",
        )
        # ELIGIBLE rolling award defaults to estimated_cost_cents (600000) > pool.
        pj = create_eligible_project(cx["id"], prog["id"], estimated_cost_cents=600_000)

        resp = api.award_upgrade_project(
            pj["id"],
            {"expected_funding_program_version": prog["version"]},
            admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_FUNDS, expected_status=402)

        pj_after = get_success_data(api.get_upgrade_project(pj["id"], admin_headers))
        assert pj_after["status"] == "ELIGIBLE"
        assert pj_after["awarded_cents"] is None
        prog_after = get_success_data(api.get_funding_program(prog["id"], admin_headers))
        assert prog_after["available_cents"] == 100_000

    @pytest.mark.parametrize("bad_amount", [0, 300_001])
    def test_award_amount_outside_bounds_rejected(self, api, admin_headers, bad_amount):
        """PRD §3.4: "it must lie between 1 and the `estimated_cost_cents`
        inclusive (else `ERR_AWARD_AMOUNT_INVALID`)".

        Design: Corner/validations/award_amount_bounds
        """
        locality = create_locality(locality_name="Bounds City")
        cx = _crossing(locality["id"], "DOT-040051")
        prog = create_program(
            fiscal_year=2044,
            apportionment_cents=1_000_000,
            allocation_method="WATERFALL_BY_RANK",
        )
        pj = create_eligible_project(cx["id"], prog["id"], estimated_cost_cents=300_000)

        resp = api.award_upgrade_project(
            pj["id"],
            {
                "expected_funding_program_version": prog["version"],
                "award_cents": bad_amount,
            },
            admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_AWARD_AMOUNT_INVALID, expected_status=422)

        pj_after = get_success_data(api.get_upgrade_project(pj["id"], admin_headers))
        assert pj_after["status"] == "ELIGIBLE"
        # A rejected attempt does not bump the program version (PRD §2.6:
        # version moves only on lock/award/rescind).
        prog_after = get_success_data(api.get_funding_program(prog["id"], admin_headers))
        assert prog_after["version"] == prog["version"]
        assert prog_after["available_cents"] == 1_000_000


class TestProgramCloseGuard:
    def test_close_with_selected_project_rejected(self, api, admin_headers):
        """PRD §3.4: "a `ProgramAdministrator` may close an `ALLOCATION_LOCKED`
        program, but only when none of its projects remain in `SELECTED`,
        `AWARDED`, or `IN_PROGRESS` — open commitments block the close with
        `ERR_PROGRAM_HAS_OPEN_PROJECTS`."

        Design: Corner/validations/program_close_with_open_projects_rejected
        """
        locality = create_locality(locality_name="Close Guard City")
        cx = _crossing(locality["id"], "DOT-040131")
        prog = create_program(
            fiscal_year=2046,
            apportionment_cents=1_000_000,
            allocation_method="WATERFALL_BY_RANK",
        )
        pj = create_eligible_project(cx["id"], prog["id"], estimated_cost_cents=300_000)
        get_success_data(
            api.transition_funding_program(
                prog["id"], {"to_status": "ALLOCATION_LOCKED"}, admin_headers
            )
        )
        pj_mid = get_success_data(api.get_upgrade_project(pj["id"], admin_headers))
        assert pj_mid["status"] == "SELECTED"

        resp = api.transition_funding_program(
            prog["id"], {"to_status": "CLOSED"}, admin_headers
        )
        validate_error(resp, ApiErrorId.ERR_PROGRAM_HAS_OPEN_PROJECTS, expected_status=409)

        prog_after = get_success_data(api.get_funding_program(prog["id"], admin_headers))
        assert prog_after["status"] == "ALLOCATION_LOCKED"
