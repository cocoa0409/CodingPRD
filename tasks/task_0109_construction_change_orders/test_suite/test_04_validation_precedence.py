"""Validation-precedence and boundary-precision tests (Difficulty queue:
priority_pair_validation_conflict, boundary_precision_check)."""
import pytest

from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    OWNER, CONTRACTOR, ARCHITECT,
    JAN,
    make_architect_headers,
    create_project, create_sov_line,
    setup_project_with_one_sov_line, setup_project_with_two_sov_lines,
    create_pay_application, add_pay_app_line, submit_pay_application,
    get_project_version,
)
from test_helpers import fixtures as fx


# ===========================================================================
# Rule: priority_pair_validation_conflict
# ===========================================================================
class TestStateBeatsSegregationOnCertify:
    """Design: Difficulty/priority_pair_validation_conflict/state_beats_segregation_on_certify"""

    def _draft_app_owned_by_gc(self, api):
        # PayApplication created with one line but NEVER submitted -> still DRAFT,
        # and no submitted_by_user_id captured yet.
        project, sov1 = setup_project_with_one_sov_line()
        app = create_pay_application(project["id"], 1, JAN, project["version"])
        add_pay_app_line(app["id"], sov1["id"], 100_000)
        return app

    def test_certify_draft_returns_invalid_state_not_segregation(self, api):
        """PRD §2.10: "Only after those four gates does the system evaluate state-machine
        legality (ERR_INVALID_STATE), followed by the segregation-of-duties control
        (ERR_SEGREGATION_OF_DUTIES)".

        Design: Difficulty/priority_pair_validation_conflict/state_beats_segregation_on_certify
        """
        app = self._draft_app_owned_by_gc(api)
        # Certifying architect carries gc-1 (the would-be submitter id); state still wins.
        resp = api.certify_pay_application(app["id"], make_architect_headers("gc-1"))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)

    def test_draft_app_unchanged_after_blocked_certify(self, api):
        """PRD §3.4: "An architect certifying a submitted application must satisfy three
        preconditions: the application is SUBMITTED (else ERR_INVALID_STATE)".

        Design: Difficulty/priority_pair_validation_conflict/state_beats_segregation_on_certify
        """
        app = self._draft_app_owned_by_gc(api)
        api.certify_pay_application(app["id"], make_architect_headers("gc-1"))
        data = validate_success(api.get_pay_application(app["id"], OWNER), 200)
        assert data["status"] == "DRAFT"


class TestOverbillingOnSubmitPath:
    """Design: Difficulty/priority_pair_validation_conflict/overbilling_beats_balance_unrelated_pair"""

    def test_submit_with_overbilling_line_returns_overbilling(self, api):
        """PRD §3.4: "A line that exceeds its scheduled value is rejected with `ERR_OVERBILLING`
        (HTTP 422)".

        Design: Difficulty/priority_pair_validation_conflict/overbilling_beats_balance_unrelated_pair
        """
        project, sov1 = setup_project_with_one_sov_line(sov1_value=600_000)
        app = create_pay_application(project["id"], 1, JAN, project["version"])
        add_pay_app_line(app["id"], sov1["id"], 600_001, 0)
        resp = api.submit_pay_application(app["id"], CONTRACTOR)
        validate_error(resp, ApiErrorId.ERR_OVERBILLING.value, 422)

    def test_overbilling_block_leaves_application_in_draft(self, api):
        """PRD §3.4: "When the Contractor submits a pay application it advances DRAFT →
        SUBMITTED, permitted only when it is DRAFT, at least one pay-app line exists for it,
        and no line overbills".

        Design: Difficulty/priority_pair_validation_conflict/overbilling_beats_balance_unrelated_pair
        """
        project, sov1 = setup_project_with_one_sov_line(sov1_value=600_000)
        app = create_pay_application(project["id"], 1, JAN, project["version"])
        add_pay_app_line(app["id"], sov1["id"], 600_001, 0)
        api.submit_pay_application(app["id"], CONTRACTOR)
        data = validate_success(api.get_pay_application(app["id"], OWNER), 200)
        assert data["status"] == "DRAFT"


# ===========================================================================
# Rule: boundary_precision_check
# ===========================================================================
class TestOverbillingBoundaryEqualOkPlusOneFails:
    """Design: Difficulty/boundary_precision_check/overbilling_boundary_equal_ok_plus_one_fails"""

    def test_billed_equal_to_scheduled_value_submits(self, api):
        """PRD §3.4: "for every line, the sum of work_completed_previous_cents,
        work_completed_this_period_cents, and materials_stored_cents is at most the linked
        schedule-of-values line's scheduled_value_cents."

        Design: Difficulty/boundary_precision_check/overbilling_boundary_equal_ok_plus_one_fails
        """
        project, sov1 = setup_project_with_one_sov_line(sov1_value=600_000)
        app = create_pay_application(project["id"], 1, JAN, project["version"])
        add_pay_app_line(app["id"], sov1["id"], 600_000, 0)  # exactly == scheduled.
        resp = api.submit_pay_application(app["id"], CONTRACTOR)
        data = validate_success(resp, 200)
        assert data["status"] == "SUBMITTED"
        assert data["total_completed_and_stored_cents"] == 600000

    def test_billed_one_over_scheduled_value_rejected(self, api):
        """PRD §3.4: "A line that exceeds its scheduled value is rejected with `ERR_OVERBILLING`
        (HTTP 422)".

        Design: Difficulty/boundary_precision_check/overbilling_boundary_equal_ok_plus_one_fails
        """
        project, sov1 = setup_project_with_one_sov_line(sov1_value=600_000)
        app = create_pay_application(project["id"], 1, JAN, project["version"])
        add_pay_app_line(app["id"], sov1["id"], 600_001, 0)  # scheduled + 1.
        resp = api.submit_pay_application(app["id"], CONTRACTOR)
        validate_error(resp, ApiErrorId.ERR_OVERBILLING.value, 422)


class TestRetentionReleaseBoundaryEqualHeldOk:
    """Design: Difficulty/boundary_precision_check/retention_release_boundary_equal_held_ok"""

    def test_release_equal_to_held_approves_and_zeroes_held(self, api):
        """PRD §3.8: "the requested `amount_cents` is at most the project's current
        `retainage_held_cents` (else `ERR_RELEASE_EXCEEDS_HELD`, HTTP 422)".

        Design: Difficulty/boundary_precision_check/retention_release_boundary_equal_held_ok
        """
        project, sov1, sov2, pay_app, release = fx.setup_release_requested(45_000)
        pv_cur = get_project_version(project["id"])
        resp = api.approve_retention_release(
            release["id"], {"expected_project_version": pv_cur}, OWNER
        )
        data = validate_success(resp, 200)
        assert data["status"] == "APPROVED"
        proj = validate_success(api.get_project(project["id"], OWNER), 200)
        assert proj["retainage_held_cents"] == 0

    def test_full_release_zeroes_every_sov_line_retainage(self, api):
        """PRD §3.8: "a full release equal to the held total zeroes every line's retainage
        and brings retainage_held_cents to zero".

        Design: Difficulty/boundary_precision_check/retention_release_boundary_equal_held_ok
        """
        project, sov1, sov2, pay_app, release = fx.setup_release_requested(45_000)
        pv_cur = get_project_version(project["id"])
        validate_success(
            api.approve_retention_release(
                release["id"], {"expected_project_version": pv_cur}, OWNER
            ),
            200,
        )
        s1 = validate_success(api.get_sov_line(sov1["id"], OWNER), 200)
        s2 = validate_success(api.get_sov_line(sov2["id"], OWNER), 200)
        assert s1["retainage_withheld_to_date_cents"] == 0
        assert s2["retainage_withheld_to_date_cents"] == 0
