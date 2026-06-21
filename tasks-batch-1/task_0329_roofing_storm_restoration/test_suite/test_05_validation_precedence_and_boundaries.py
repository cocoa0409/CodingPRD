"""Validation-ordering precedence pairs and numeric / interval boundary
precision.

Queue A: priority_pair_validation_conflict, boundary_precision_check.

PRD §2.9 fixes a total order over validation classes and states that "A check
earlier in this order always masks one later in the order", so each precedence
pair below has a uniquely-determined winning error.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data, TEST_USERS, ApiErrorId,
    setup_contracted_job, setup_in_production_job, setup_in_production_with_draw,
    create_crew, create_draw_payload, create_crew_assignment_payload,
    create_inspection_payload,
)

PM = TEST_USERS["production_manager_headers"]
FA = TEST_USERS["field_adjuster_headers"]

SHINGLE_10 = [{"trade": "SHINGLE", "squares": 10, "unit_price_cents": 10000, "waste_factor_pct": 0.10}]


class TestValidationPrecedence:
    def test_cross_entity_state_masks_fiscal_on_draw(self, api):
        """PRD §2.9: "(8) cross-entity state preconditions; (9) temporal-overlap
        rules; (10) fiscal rules; and finally (11) optimistic-concurrency
        version checks."
        PRD §2.9: "A check earlier in this order always masks one later in the
        order, so — for example — an authorization failure surfaces before a
        stale-version failure even when both conditions hold."

        Design: Difficulty/priority_pair_validation_conflict/state_before_fiscal_on_draw
        """
        # CONTRACTED (not IN_PRODUCTION) job. A draw with cumulative_pct just
        # above 0 is both non-increasing (billed_pct is 0, needs strict >) AND
        # blocked because the job is not IN_PRODUCTION. The state precondition
        # (8) masks the fiscal one (10): ERR_JOB_NOT_IN_PRODUCTION wins.
        job_id, _ = setup_contracted_job(line_items=SHINGLE_10)
        jv = get_success_data(api.get_job(job_id, PM))["version"]
        validate_error(
            api.create_draw(create_draw_payload(
                job_id=job_id, cumulative_pct=0.000001, expected_job_version=jv), PM),
            ApiErrorId.ERR_JOB_NOT_IN_PRODUCTION.value)

    def test_cross_entity_state_masks_fiscal_with_increasing_pct(self, api):
        """PRD §2.9: "(8) cross-entity state preconditions; (9) temporal-overlap
        rules; (10) fiscal rules; and finally (11) optimistic-concurrency
        version checks."
        PRD §3.7: "The parent job must be `IN_PRODUCTION`, else
        `ERR_JOB_NOT_IN_PRODUCTION`."

        Design: Difficulty/priority_pair_validation_conflict/state_before_fiscal_on_draw
        """
        # CONTRACTED job, cumulative_pct 0.5 IS strictly increasing over the
        # billed_pct of 0 (so the fiscal check would pass), yet the not-in-
        # production state precondition (8) still blocks the draw -- isolating
        # that the state class, not the fiscal class, governs.
        job_id, _ = setup_contracted_job(line_items=SHINGLE_10)
        jv = get_success_data(api.get_job(job_id, PM))["version"]
        validate_error(
            api.create_draw(create_draw_payload(
                job_id=job_id, cumulative_pct=0.5, expected_job_version=jv), PM),
            ApiErrorId.ERR_JOB_NOT_IN_PRODUCTION.value)

    def test_fk_resolution_masks_temporal_overlap_on_crew_booking(self, api):
        """PRD §2.8: "Path-identifier existence always takes precedence over body
        foreign-key resolution."
        PRD §2.9: "(4) body foreign-key resolution, else `ERR_FK_NOT_FOUND`; (5)
        presence and typing of required body fields ... (9) temporal-overlap
        rules; (10) fiscal rules ..."

        Design: Difficulty/priority_pair_validation_conflict/existence_before_temporal_on_crew_assignment
        """
        # IN_PRODUCTION job with crew Alpha booked 08:00..16:00. A second booking
        # references a non-existent crew_id AND an overlapping window. FK
        # resolution (4) masks temporal overlap (9): ERR_FK_NOT_FOUND wins.
        job_id, _ = setup_in_production_job(line_items=SHINGLE_10)
        crew = create_crew(name="Crew Alpha")
        validate_success(api.create_crew_assignment(create_crew_assignment_payload(
            job_id=job_id, crew_id=crew["id"],
            window_start="2026-07-01T08:00:00Z", window_end="2026-07-01T16:00:00Z"), PM),
            expected_status=201)
        validate_error(
            api.create_crew_assignment(create_crew_assignment_payload(
                job_id=job_id, crew_id="00000000-0000-4000-8000-000000000000",
                window_start="2026-07-01T10:00:00Z", window_end="2026-07-01T14:00:00Z"), PM),
            ApiErrorId.ERR_FK_NOT_FOUND.value)

    def test_fk_resolution_fires_for_nonexistent_crew_even_without_overlap(self, api):
        """PRD §2.8: "for create operations and for the contract operation, it
        confirms that every foreign key in the body resolves — `job_id`,
        `crew_id`, `estimate_id`, `permit_id`, `assigned_estimator_id`, and the
        `estimate_id` named when contracting — rejecting with `ERR_FK_NOT_FOUND`
        (HTTP 404) when any referenced record is missing."

        Design: Difficulty/priority_pair_validation_conflict/existence_before_temporal_on_crew_assignment
        """
        # Same masking error class is the FK-resolution stage (4): a booking with
        # a non-existent crew_id is rejected ERR_FK_NOT_FOUND regardless of any
        # window-overlap consideration.
        job_id, _ = setup_in_production_job(line_items=SHINGLE_10)
        validate_error(
            api.create_crew_assignment(create_crew_assignment_payload(
                job_id=job_id, crew_id="00000000-0000-4000-8000-000000000000",
                window_start="2026-09-01T08:00:00Z", window_end="2026-09-01T16:00:00Z"), PM),
            ApiErrorId.ERR_FK_NOT_FOUND.value)


class TestBoundaryPrecision:
    def test_draw_pct_equal_to_watermark_is_rejected(self, api):
        """PRD §3.7: "The claimed `cumulative_pct` must strictly exceed the job's
        current `billed_pct` — the billing watermark — else
        `ERR_PCT_NOT_INCREASING`; this is what forbids billing the same progress
        twice."

        Design: Difficulty/boundary_precision_check/draw_pct_strictly_increasing_boundary
        """
        # First draw at 0.5 sets billed_pct = 0.5. A second draw at exactly 0.5
        # fails the strict `>` boundary.
        job_id, info = setup_in_production_with_draw(cumulative_pct=0.5, line_items=SHINGLE_10)
        validate_error(
            api.create_draw(create_draw_payload(
                job_id=job_id, cumulative_pct=0.5,
                expected_job_version=info["job_version"]), PM),
            ApiErrorId.ERR_PCT_NOT_INCREASING.value)
        job = get_success_data(api.get_job(job_id, PM))
        assert job["billed_pct"] == 0.5

    def test_draw_pct_just_above_watermark_succeeds(self, api):
        """PRD §3.7: "The claimed `cumulative_pct` must strictly exceed the job's
        current `billed_pct` — the billing watermark — else
        `ERR_PCT_NOT_INCREASING`; this is what forbids billing the same progress
        twice."

        Design: Difficulty/boundary_precision_check/draw_pct_strictly_increasing_boundary
        """
        # X+1 side of the boundary: 0.5000001 strictly exceeds 0.5 -> disburses.
        job_id, info = setup_in_production_with_draw(cumulative_pct=0.5, line_items=SHINGLE_10)
        data = validate_success(api.create_draw(create_draw_payload(
            job_id=job_id, cumulative_pct=0.5000001,
            expected_job_version=info["job_version"]), PM), expected_status=201)
        assert data["status"] == "DISBURSED"

    def test_permit_final_buffer_exactly_24h_apart_allowed(self, api):
        """PRD §3.5: "A gap of exactly 24 hours is allowed (the boundary is
        inclusive)."

        Design: Difficulty/boundary_precision_check/permit_inspection_buffer_exact_24h_allowed
        """
        job_id, info = setup_in_production_job(line_items=SHINGLE_10)
        permit_id = info["permit"]["id"]
        # First PERMIT_FINAL: 2026-07-10 08:00..12:00.
        get_success_data(api.create_inspection(create_inspection_payload(
            job_id=job_id, kind="PERMIT_FINAL", permit_id=permit_id,
            scheduled_start="2026-07-10T08:00:00Z", scheduled_end="2026-07-10T12:00:00Z"), FA))
        # Second starts exactly 24h after the first ends -> gap == 24, allowed.
        data = validate_success(api.create_inspection(create_inspection_payload(
            job_id=job_id, kind="PERMIT_FINAL", permit_id=permit_id,
            scheduled_start="2026-07-11T12:00:00Z", scheduled_end="2026-07-11T14:00:00Z"), FA),
            expected_status=201)
        assert data["status"] == "SCHEDULED"

    def test_first_permit_final_with_no_candidates_succeeds(self, api):
        """PRD §3.5: "The candidates considered are the existing permit-final
        inspections for that job whose status is `SCHEDULED` or `PASSED`."

        Design: Difficulty/boundary_precision_check/permit_inspection_buffer_exact_24h_allowed
        """
        # Empty-set edge: with no prior PERMIT_FINAL candidates for the job, the
        # buffer rule has nothing to conflict against, so the first one succeeds.
        job_id, info = setup_in_production_job(line_items=SHINGLE_10)
        data = validate_success(api.create_inspection(create_inspection_payload(
            job_id=job_id, kind="PERMIT_FINAL", permit_id=info["permit"]["id"],
            scheduled_start="2026-07-10T08:00:00Z", scheduled_end="2026-07-10T12:00:00Z"), FA),
            expected_status=201)
        assert data["status"] == "SCHEDULED"
