"""Cross-entity state dependencies (start-production needs delivered materials +
issued permit; crew check-in needs job IN_PRODUCTION) and resource temporal
overlap (crew half-open back-to-back allowed; permit-final 24h buffer conflict).

Queue A: cross_entity_state_dependency, resource_temporal_overlap.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data, TEST_USERS, ApiErrorId,
    setup_contracted_job, setup_in_production_job, create_crew,
    create_material_order_payload, create_permit_payload, issue_permit_payload,
    create_crew_assignment_payload, create_inspection_payload,
)

PM = TEST_USERS["production_manager_headers"]
FA = TEST_USERS["field_adjuster_headers"]

SHINGLE_10 = [{"trade": "SHINGLE", "squares": 10, "unit_price_cents": 10000, "waste_factor_pct": 0.10}]


class TestCrossEntityStateDependency:
    def test_start_production_blocked_when_materials_not_delivered(self, api):
        """PRD §3.6: "A missing delivery is rejected with
        `ERR_MATERIALS_NOT_DELIVERED`; a missing issued permit with
        `ERR_PERMIT_NOT_ISSUED`."

        Design: Difficulty/cross_entity_state_dependency/start_production_requires_materials_and_permit
        """
        # CONTRACTED job: material order placed but NOT delivered; permit ISSUED.
        job_id, _ = setup_contracted_job(line_items=SHINGLE_10)
        get_success_data(api.create_material_order(
            create_material_order_payload(job_id=job_id), PM))  # stays ORDERED
        permit = get_success_data(api.create_permit(
            create_permit_payload(job_id=job_id), PM))
        api.issue_permit(permit["id"], issue_permit_payload(permit_number="P-2001"), PM)
        validate_error(api.start_production(job_id, PM),
                       ApiErrorId.ERR_MATERIALS_NOT_DELIVERED.value)

    def test_start_production_blocked_when_permit_not_issued(self, api):
        """PRD §3.6: "A missing delivery is rejected with
        `ERR_MATERIALS_NOT_DELIVERED`; a missing issued permit with
        `ERR_PERMIT_NOT_ISSUED`."

        Design: Difficulty/cross_entity_state_dependency/start_production_requires_materials_and_permit
        """
        # Materials DELIVERED but no permit ISSUED (left APPLIED).
        job_id, _ = setup_contracted_job(line_items=SHINGLE_10)
        mo = get_success_data(api.create_material_order(
            create_material_order_payload(job_id=job_id), PM))
        api.deliver_material_order(mo["id"], {}, PM)
        get_success_data(api.create_permit(create_permit_payload(job_id=job_id), PM))  # APPLIED
        validate_error(api.start_production(job_id, PM),
                       ApiErrorId.ERR_PERMIT_NOT_ISSUED.value)

    def test_crew_checkin_requires_job_in_production(self, api):
        """PRD §3.6: "Check-in has two preconditions: the parent job must be
        `IN_PRODUCTION`, otherwise `ERR_JOB_NOT_IN_PRODUCTION`, and the booked
        **Crew** must have its `active` flag true, otherwise `ERR_CREW_INACTIVE`."

        Design: Difficulty/cross_entity_state_dependency/crew_checkin_requires_job_in_production
        """
        # Crew booked while the job is still CONTRACTED (not IN_PRODUCTION).
        job_id, _ = setup_contracted_job(line_items=SHINGLE_10)
        crew = create_crew(name="Crew Beta")
        ca = get_success_data(api.create_crew_assignment(create_crew_assignment_payload(
            job_id=job_id, crew_id=crew["id"],
            window_start="2026-08-01T08:00:00Z", window_end="2026-08-01T16:00:00Z"), PM))
        validate_error(api.check_in_crew_assignment(ca["id"], PM),
                       ApiErrorId.ERR_JOB_NOT_IN_PRODUCTION.value)

    def test_crew_checkin_succeeds_once_job_in_production(self, api):
        """PRD §3.6: "A `ProductionManager` checks a booked crew in, moving the
        assignment from `BOOKED` to `CHECKED_IN`."

        Design: Difficulty/cross_entity_state_dependency/crew_checkin_requires_job_in_production
        """
        # Positive side of the cross-entity dependency: when the parent job IS
        # IN_PRODUCTION (and the crew is active), the booked crew checks in.
        job_id, _ = setup_in_production_job(line_items=SHINGLE_10)
        crew = create_crew(name="Crew Active")
        ca = get_success_data(api.create_crew_assignment(create_crew_assignment_payload(
            job_id=job_id, crew_id=crew["id"],
            window_start="2026-08-01T08:00:00Z", window_end="2026-08-01T16:00:00Z"), PM))
        data = validate_success(api.check_in_crew_assignment(ca["id"], PM))
        assert data["status"] == "CHECKED_IN"


class TestResourceTemporalOverlap:
    def test_crew_half_open_back_to_back_window_allowed(self, api):
        """PRD §3.6: "Because the intervals are half-open, two windows that
        merely touch — the new window starting exactly when an existing one ends
        — do not conflict and are allowed."

        Design: Difficulty/resource_temporal_overlap/crew_half_open_back_to_back_allowed
        """
        job_id, _ = setup_in_production_job(line_items=SHINGLE_10)
        crew = create_crew(name="Crew Gamma")
        validate_success(api.create_crew_assignment(create_crew_assignment_payload(
            job_id=job_id, crew_id=crew["id"],
            window_start="2026-07-01T08:00:00Z", window_end="2026-07-01T16:00:00Z"), PM),
            expected_status=201)
        # Second window starts exactly when the first ends (16:00) -> allowed.
        data = validate_success(api.create_crew_assignment(create_crew_assignment_payload(
            job_id=job_id, crew_id=crew["id"],
            window_start="2026-07-01T16:00:00Z", window_end="2026-07-01T20:00:00Z"), PM),
            expected_status=201)
        assert data["status"] == "BOOKED"

    def test_crew_truly_overlapping_window_rejected(self, api):
        """PRD §3.6: "Two half-open windows conflict when the new window's start
        is earlier than the existing window's end and the existing window's start
        is earlier than the new window's end; if that holds against any existing
        assignment for the crew, the booking is rejected with
        `ERR_CREW_DOUBLE_BOOKED`."

        Design: Difficulty/resource_temporal_overlap/crew_half_open_back_to_back_allowed
        """
        # Contrasting negative: a window that genuinely overlaps (not merely
        # touches) the existing one is double-booked, distinguishing the
        # half-open touch boundary from a real overlap.
        job_id, _ = setup_in_production_job(line_items=SHINGLE_10)
        crew = create_crew(name="Crew Overlap")
        validate_success(api.create_crew_assignment(create_crew_assignment_payload(
            job_id=job_id, crew_id=crew["id"],
            window_start="2026-07-01T08:00:00Z", window_end="2026-07-01T16:00:00Z"), PM),
            expected_status=201)
        validate_error(api.create_crew_assignment(create_crew_assignment_payload(
            job_id=job_id, crew_id=crew["id"],
            window_start="2026-07-01T12:00:00Z", window_end="2026-07-01T18:00:00Z"), PM),
            ApiErrorId.ERR_CREW_DOUBLE_BOOKED.value)

    def test_permit_final_within_buffer_conflicts(self, api):
        """PRD §3.5: "order the two by start time and measure the gap in whole
        hours from the earlier window's end to the later window's start; if that
        gap is less than 24 hours the two conflict."
        PRD §3.5: "Any conflict against any existing permit-final window for the
        job rejects the new inspection with `ERR_INSPECTION_BUFFER_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/permit_final_buffer_within_window_conflicts
        """
        job_id, info = setup_in_production_job(line_items=SHINGLE_10)
        permit_id = info["permit"]["id"]
        # First PERMIT_FINAL 08:00..12:00; second starts 17:00 same day -> 5h gap.
        get_success_data(api.create_inspection(create_inspection_payload(
            job_id=job_id, kind="PERMIT_FINAL", permit_id=permit_id,
            scheduled_start="2026-07-10T08:00:00Z", scheduled_end="2026-07-10T12:00:00Z"), FA))
        validate_error(api.create_inspection(create_inspection_payload(
            job_id=job_id, kind="PERMIT_FINAL", permit_id=permit_id,
            scheduled_start="2026-07-10T17:00:00Z", scheduled_end="2026-07-10T19:00:00Z"), FA),
            ApiErrorId.ERR_INSPECTION_BUFFER_CONFLICT.value)

    def test_permit_final_just_past_buffer_allowed(self, api):
        """PRD §3.5: "if that gap is less than 24 hours the two conflict — and
        because a negative gap means the windows actually overlap, true overlaps
        are caught by the same test."

        Design: Difficulty/resource_temporal_overlap/permit_final_buffer_within_window_conflicts
        """
        # Contrasting positive: a gap of 25 hours (>= the 24h buffer) does not
        # conflict, isolating the closed-interval + buffer geometry.
        job_id, info = setup_in_production_job(line_items=SHINGLE_10)
        permit_id = info["permit"]["id"]
        get_success_data(api.create_inspection(create_inspection_payload(
            job_id=job_id, kind="PERMIT_FINAL", permit_id=permit_id,
            scheduled_start="2026-07-10T08:00:00Z", scheduled_end="2026-07-10T12:00:00Z"), FA))
        # Second starts 2026-07-11T13:00 -> gap from 12:00 prev day is 25h.
        data = validate_success(api.create_inspection(create_inspection_payload(
            job_id=job_id, kind="PERMIT_FINAL", permit_id=permit_id,
            scheduled_start="2026-07-11T13:00:00Z", scheduled_end="2026-07-11T15:00:00Z"), FA),
            expected_status=201)
        assert data["status"] == "SCHEDULED"
