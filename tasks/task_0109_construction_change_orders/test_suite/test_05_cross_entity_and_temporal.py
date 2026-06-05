"""Cross-entity state-dependency and temporal-overlap tests (Difficulty queue:
cross_entity_state_dependency, resource_temporal_overlap)."""
import pytest

from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    OWNER, CONTRACTOR, ARCHITECT,
    JAN,
    create_project,
    setup_project_with_one_sov_line, setup_project_with_two_sov_lines,
    create_pay_application, add_pay_app_line, submit_pay_application,
    certify_pay_application, get_project_version, create_retention_release,
    create_subcontractor_commitment,
)
from test_helpers import fixtures as fx


# ===========================================================================
# Rule: cross_entity_state_dependency
# ===========================================================================
class TestPayAppCertifyBlockedByOpenArchitectRfi:
    """Design: Difficulty/cross_entity_state_dependency/payapp_certify_blocked_by_open_architect_rfi"""

    def _submitted_app_with_open_rfi(self, api):
        project, sov1, pay_app = fx.setup_submitted_pay_app_one_line()
        rfi = validate_success(
            api.create_rfi(
                {"project_id": project["id"], "subject": "Slab detail",
                 "question": "Which rebar size?"},
                CONTRACTOR,
            ),
            201,
        )
        return project, sov1, pay_app, rfi

    def test_certify_blocked_while_architect_court_rfi_open(self, api):
        """PRD §3.4: "no RFI on the project is OPEN with its ball_in_court resting on
        ARCHITECT — the architect must clear its own court before certifying, and an open
        architect-court RFI blocks certification with ERR_INVALID_STATE."

        Design: Difficulty/cross_entity_state_dependency/payapp_certify_blocked_by_open_architect_rfi
        """
        project, sov1, pay_app, rfi = self._submitted_app_with_open_rfi(api)
        resp = api.certify_pay_application(pay_app["id"], ARCHITECT)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)

    def test_application_stays_submitted_after_blocked_certify(self, api):
        """PRD §3.4: "On success the application moves SUBMITTED → CERTIFIED, records the
        certifying operator as certified_by_user_id".

        Design: Difficulty/cross_entity_state_dependency/payapp_certify_blocked_by_open_architect_rfi
        """
        project, sov1, pay_app, rfi = self._submitted_app_with_open_rfi(api)
        api.certify_pay_application(pay_app["id"], ARCHITECT)
        data = validate_success(api.get_pay_application(pay_app["id"], OWNER), 200)
        assert data["status"] == "SUBMITTED"


class TestProjectCloseBlockedByOpenSubcommitment:
    """Design: Difficulty/cross_entity_state_dependency/project_close_blocked_by_open_subcommitment"""

    def _substantially_complete_with_open_commitment(self, api):
        # Certified two-line project + an OPEN commitment; release all retainage;
        # mark substantially complete. Commitment remains OPEN (never invoiced).
        project, sov1, sov2 = setup_project_with_two_sov_lines()
        create_subcontractor_commitment(project["id"], "Acme Steel", 100_000)
        pv1 = project["version"]
        app1 = create_pay_application(project["id"], 1, JAN, pv1)
        add_pay_app_line(app1["id"], sov1["id"], 300_000, 0)
        add_pay_app_line(app1["id"], sov2["id"], 100_000, 50_000)
        submit_pay_application(app1["id"])
        certify_pay_application(app1["id"])
        pv2 = get_project_version(project["id"])
        release = create_retention_release(project["id"], 45_000, pv2)
        pv3 = get_project_version(project["id"])
        validate_success(
            api.approve_retention_release(
                release["id"], {"expected_project_version": pv3}, OWNER
            ),
            200,
        )
        validate_success(api.substantial_completion_project(project["id"], ARCHITECT), 200)
        return project

    def test_close_blocked_by_open_commitment(self, api):
        """PRD §3.7: "the Owner closes the project, advancing SUBSTANTIALLY_COMPLETE →
        CLOSED, only when the project's retainage_held_cents is zero (all retention released)
        and every subcontractor commitment on the project is CLOSED; otherwise ERR_INVALID_STATE."

        Design: Difficulty/cross_entity_state_dependency/project_close_blocked_by_open_subcommitment
        """
        project = self._substantially_complete_with_open_commitment(api)
        resp = api.close_project(project["id"], OWNER)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)

    def test_project_stays_substantially_complete_after_blocked_close(self, api):
        """PRD §3.7: "The Architect marks a project substantially complete, advancing
        ACTIVE → SUBSTANTIALLY_COMPLETE".

        Design: Difficulty/cross_entity_state_dependency/project_close_blocked_by_open_subcommitment
        """
        project = self._substantially_complete_with_open_commitment(api)
        api.close_project(project["id"], OWNER)
        data = validate_success(api.get_project(project["id"], OWNER), 200)
        assert data["status"] == "SUBSTANTIALLY_COMPLETE"


# ===========================================================================
# Rule: resource_temporal_overlap
# ===========================================================================
class TestPayAppBillingWindowHalfOpenOverlapRejected:
    """Design: Difficulty/resource_temporal_overlap/payapp_billing_window_half_open_overlap_rejected"""

    def _certified_app_jan_window(self, api):
        project, sov1 = setup_project_with_one_sov_line()
        pv1 = project["version"]
        app1 = create_pay_application(project["id"], 1, JAN, pv1)
        add_pay_app_line(app1["id"], sov1["id"], 100_000, 0)
        submit_pay_application(app1["id"])
        certify_pay_application(app1["id"])
        return project

    def test_interior_overlapping_window_rejected(self, api):
        """PRD §3.3: "the billing window is the half-open interval running from period_from
        up to but not including period_to, and it must not overlap the window of any
        non-rejected application on the same project."

        Design: Difficulty/resource_temporal_overlap/payapp_billing_window_half_open_overlap_rejected
        """
        project = self._certified_app_jan_window(api)
        pv_cur = get_project_version(project["id"])
        # New window [2026-01-15, 2026-02-15) overlaps prior [2026-01-01, 2026-01-31).
        resp = api.create_pay_application(
            {"project_id": project["id"], "application_number": 2,
             "period_from": "2026-01-15T00:00:00.000Z",
             "period_to": "2026-02-15T00:00:00.000Z",
             "expected_project_version": pv_cur},
            CONTRACTOR,
        )
        validate_error(resp, ApiErrorId.ERR_BILLING_PERIOD_OVERLAP.value, 409)

    def test_adjacent_window_is_allowed(self, api):
        """PRD §3.3: "an exact touch where a new application's period_from equals a prior
        application's period_to is adjacency, not overlap, and is permitted."

        Design: Difficulty/resource_temporal_overlap/payapp_billing_window_half_open_overlap_rejected
        """
        project = self._certified_app_jan_window(api)
        pv_cur = get_project_version(project["id"])
        # New window starts exactly at prior period_to 2026-01-31 -> adjacency, allowed.
        resp = api.create_pay_application(
            {"project_id": project["id"], "application_number": 2,
             "period_from": "2026-01-31T00:00:00.000Z",
             "period_to": "2026-02-28T00:00:00.000Z",
             "expected_project_version": pv_cur},
            CONTRACTOR,
        )
        data = validate_success(resp, 201)
        assert data["status"] == "DRAFT"


class TestInspectionWindowClosedIntervalBufferConflict:
    """Design: Difficulty/resource_temporal_overlap/inspection_window_closed_interval_buffer_conflict_rejected"""

    def _project_with_booked_slot(self, api):
        project = create_project(500_000, name="InspP")
        validate_success(
            api.create_inspection_window(
                {"project_id": project["id"], "inspector_name": "City A",
                 "scheduled_start": "2026-03-01T10:00:00.000Z",
                 "scheduled_end": "2026-03-01T11:00:00.000Z", "buffer_minutes": 30},
                CONTRACTOR,
            ),
            201,
        )
        return project

    def test_slot_within_buffer_rejected(self, api):
        """PRD §3.7: "two slots conflict when the gap between their closed intervals is
        strictly less than buffer_minutes, so a back-to-back booking with a zero gap is a
        conflict and is rejected with ERR_INSPECTION_BUFFER_CONFLICT (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/inspection_window_closed_interval_buffer_conflict_rejected
        """
        project = self._project_with_booked_slot(api)
        # New slot [11:15, 12:00]; 15-min gap from prior [10:00, 11:00] < 30-min buffer.
        resp = api.create_inspection_window(
            {"project_id": project["id"], "inspector_name": "City B",
             "scheduled_start": "2026-03-01T11:15:00.000Z",
             "scheduled_end": "2026-03-01T12:00:00.000Z", "buffer_minutes": 30},
            CONTRACTOR,
        )
        validate_error(resp, ApiErrorId.ERR_INSPECTION_BUFFER_CONFLICT.value, 409)

    def test_slot_clearing_buffer_is_booked(self, api):
        """PRD §3.7: "A booking must clear every non-cancelled inspection window on the same
        project by at least its buffer_minutes".

        Design: Difficulty/resource_temporal_overlap/inspection_window_closed_interval_buffer_conflict_rejected
        """
        project = self._project_with_booked_slot(api)
        # New slot [11:31, 12:00]; 31-min gap from prior end 11:00 >= 30-min buffer.
        resp = api.create_inspection_window(
            {"project_id": project["id"], "inspector_name": "City C",
             "scheduled_start": "2026-03-01T11:31:00.000Z",
             "scheduled_end": "2026-03-01T12:00:00.000Z", "buffer_minutes": 30},
            CONTRACTOR,
        )
        data = validate_success(resp, 201)
        assert data["status"] == "BOOKED"
