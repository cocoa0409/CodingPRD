"""Progress-conference claims: plan-approval gating, half-open overlap
geometry, and window validity."""
from test_helpers import (
    ApiErrorId,
    create_curriculum_plan_payload,
    create_progress_conference_payload,
    get_success_data,
    make_family_headers,
    make_guide_headers,
    validate_error,
    validate_success,
    TEST_USERS,
)
from test_helpers.fixtures import (
    set_clock,
    setup_enrolled_seat,
    setup_pod_active,
)

ADMIN = TEST_USERS["platform_admin_headers"]
OPERATOR = TEST_USERS["pod_operator_headers"]
REGISTRAR = TEST_USERS["registrar_headers"]

BASE_START = "2026-09-01T15:00:00Z"
BASE_END = "2026-09-01T15:30:00Z"


def _active_context(api):
    """ACTIVE pod + ENROLLED seat + APPROVED plan. Returns
    (pod, family, seat, plan, guide)."""
    pod, site, policy, plan, det, guide, assignment = setup_pod_active()
    family, student, seat = setup_enrolled_seat(pod)
    return pod, family, seat, plan, guide


class TestPlanApprovalGate:
    def test_conference_rejected_when_plan_only_submitted(self, api):
        """PRD 3.8: "The referenced plan must be `APPROVED` and belong to
        the same pod — otherwise `ERR_PLAN_NOT_APPROVED` (HTTP 422)."

        Design: Difficulty/cross_entity_state_dependency/progress_conference_requires_approved_plan
        """
        set_clock("2026-08-15T00:00:00Z")
        pod, family, seat, plan, guide = _active_context(api)
        # A second plan left in SUBMITTED (never approved).
        plan2 = get_success_data(api.create_curriculum_plan(
            pod["id"], create_curriculum_plan_payload(plan_name="Pending Plan"),
            OPERATOR,
        ))
        plan2 = get_success_data(
            api.submit_curriculum_plan(pod["id"], plan2["id"], OPERATOR)
        )
        assert plan2["plan_status"] == "SUBMITTED"
        resp = api.create_progress_conference(
            pod["id"],
            create_progress_conference_payload(seat["id"], plan2["id"]),
            make_family_headers(family["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_PLAN_NOT_APPROVED,
                       expected_status=422)
        # Nothing persisted for that request. The pod-scoped conference
        # listing is authorized for PodOperator (PRD section 4), not
        # Registrar.
        from test_helpers import validate_paginated
        listed, _meta = validate_paginated(
            api.list_progress_conferences_for_pod(
                pod["id"], OPERATOR, params={"seat_id": seat["id"]}
            )
        )
        assert listed == []

    def test_conference_rejected_when_plan_draft(self, api):
        """PRD 3.8: "The referenced plan must be `APPROVED` and belong to
        the same pod — otherwise `ERR_PLAN_NOT_APPROVED` (HTTP 422)."
        PRD 3.2: "Only `APPROVED` plans may anchor a progress conference."

        Design: Difficulty/cross_entity_state_dependency/progress_conference_requires_approved_plan
        """
        set_clock("2026-08-15T00:00:00Z")
        pod, family, seat, plan, guide = _active_context(api)
        plan2 = get_success_data(api.create_curriculum_plan(
            pod["id"], create_curriculum_plan_payload(plan_name="Draft Plan"),
            OPERATOR,
        ))
        assert plan2["plan_status"] == "DRAFT"
        resp = api.create_progress_conference(
            pod["id"],
            create_progress_conference_payload(seat["id"], plan2["id"]),
            make_family_headers(family["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_PLAN_NOT_APPROVED,
                       expected_status=422)


class TestConferenceOverlap:
    def _first_scheduled_conference(self, api, pod, family, seat, plan, guide):
        conf = get_success_data(api.create_progress_conference(
            pod["id"],
            create_progress_conference_payload(
                seat["id"], plan["id"],
                scheduled_start=BASE_START, scheduled_end=BASE_END,
            ),
            make_family_headers(family["id"]),
        ))
        return get_success_data(
            api.schedule_progress_conference(
                pod["id"], conf["id"], make_guide_headers(guide["id"])
            )
        )

    def test_start_at_existing_end_does_not_overlap(self, api):
        """PRD 3.8: "And the guide's calendar must be clear: no other
        conference in `REQUESTED`, `SCHEDULED`, or `RESCHEDULED` status for
        the same guide may overlap the half-open window from
        `scheduled_start` up to but not including `scheduled_end` —
        otherwise `ERR_CONFERENCE_OVERLAP` (HTTP 422)."

        Design: Difficulty/resource_temporal_overlap/progress_conference_half_open_overlap
        """
        set_clock("2026-08-15T00:00:00Z")
        pod, family, seat, plan, guide = _active_context(api)
        self._first_scheduled_conference(api, pod, family, seat, plan, guide)
        # New window starts exactly at the existing window's end: half-open
        # semantics means no overlap.
        data = validate_success(
            api.create_progress_conference(
                pod["id"],
                create_progress_conference_payload(
                    seat["id"], plan["id"],
                    scheduled_start="2026-09-01T15:30:00Z",
                    scheduled_end="2026-09-01T16:00:00Z",
                ),
                make_guide_headers(guide["id"]),
            ),
            expected_status=201,
        )
        assert data["conference_status"] == "REQUESTED"

    def test_one_minute_before_existing_end_overlaps(self, api):
        """PRD 3.8: "And the guide's calendar must be clear: no other
        conference in `REQUESTED`, `SCHEDULED`, or `RESCHEDULED` status for
        the same guide may overlap the half-open window from
        `scheduled_start` up to but not including `scheduled_end` —
        otherwise `ERR_CONFERENCE_OVERLAP` (HTTP 422)."

        Design: Difficulty/resource_temporal_overlap/progress_conference_half_open_overlap
        """
        set_clock("2026-08-15T00:00:00Z")
        pod, family, seat, plan, guide = _active_context(api)
        self._first_scheduled_conference(api, pod, family, seat, plan, guide)
        resp = api.create_progress_conference(
            pod["id"],
            create_progress_conference_payload(
                seat["id"], plan["id"],
                scheduled_start="2026-09-01T15:29:00Z",
                scheduled_end="2026-09-01T16:00:00Z",
            ),
            make_guide_headers(guide["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_CONFERENCE_OVERLAP,
                       expected_status=422)


class TestConferenceWindowValidity:
    def test_err_invalid_conference_window_triggerable(self, api):
        """PRD 3.8: "The window must open strictly before it closes and both
        endpoints must lie in the future relative to the logical clock —
        otherwise `ERR_INVALID_CONFERENCE_WINDOW` (HTTP 422)."

        Design: Corner/errors/err_invalid_conference_window_triggerable
        """
        set_clock("2026-08-15T00:00:00Z")
        pod, family, seat, plan, guide = _active_context(api)
        resp = api.create_progress_conference(
            pod["id"],
            create_progress_conference_payload(
                seat["id"], plan["id"],
                scheduled_start="2026-09-01T16:00:00Z",
                scheduled_end="2026-09-01T15:00:00Z",
            ),
            make_family_headers(family["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_CONFERENCE_WINDOW,
                       expected_status=422)
