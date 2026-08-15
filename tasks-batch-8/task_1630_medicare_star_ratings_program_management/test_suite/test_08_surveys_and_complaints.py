"""Survey wave windows, lanes, vendor capacity, response-rate scoring, and the
complaint resolution branches with the 30-day timeliness rule."""
import pytest

from test_helpers import (
    ApiErrorId,
    file_complaint,
    get_performance,
    plan_wave,
    resolve_complaint,
    set_clock,
    setup_complaints_measure_scenario,
    setup_survey_lane,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestSurveyLaneOverlap:
    def test_overlapping_wave_in_same_lane_rejected(self, api,
                                                   survey_coordinator_headers):
        """PRD §3.6: "Within the same cycle and survey type, the new wave's window
        must not intersect the window of any existing non-terminal wave (that is,
        one still in `PLANNED`, `FIELDING`, or `CLOSED_FIELD`)."
        PRD §3.6: "A true intersection is rejected with
        `ERR_SURVEY_WINDOW_OVERLAP`."

        A wave starting 2026-09-30 intersects the existing [2026-09-01,
        2026-10-01) window.

        Design: Difficulty/resource_temporal_overlap/survey_lane_halfopen_adjacency_allowed
        """
        sc = setup_survey_lane()
        resp = api.create_survey_wave(
            {"rating_cycle_id": sc["cycle"]["id"], "survey_type": "CAHPS",
             "vendor_id": sc["vendor"]["id"],
             "window_start": "2026-09-30T00:00:00Z",
             "window_end": "2026-10-30T00:00:00Z", "sample_size": 100},
            survey_coordinator_headers,
        )
        validate_error(resp, ApiErrorId.ERR_SURVEY_WINDOW_OVERLAP)

    def test_adjacent_wave_in_same_lane_accepted(self, api, survey_coordinator_headers):
        """PRD §3.6: "Adjacency is allowed — a new wave whose `window_start` equals
        an existing wave's `window_end`, or whose `window_end` equals an existing
        wave's `window_start`, does not count as an intersection."

        A wave starting exactly at the predecessor's window_end (2026-10-01) is
        accepted under the half-open [start, end) semantics.

        Design: Difficulty/resource_temporal_overlap/survey_lane_halfopen_adjacency_allowed
        """
        sc = setup_survey_lane()
        resp = api.create_survey_wave(
            {"rating_cycle_id": sc["cycle"]["id"], "survey_type": "CAHPS",
             "vendor_id": sc["vendor"]["id"],
             "window_start": "2026-10-01T00:00:00Z",
             "window_end": "2026-11-01T00:00:00Z", "sample_size": 100},
            survey_coordinator_headers,
        )
        wave = validate_success(resp, 201)
        assert wave["status"] == "PLANNED", "Adjacent wave is accepted as PLANNED"


class TestVendorCapacity:
    def test_vendor_at_capacity_rejects_overlapping_wave(
            self, api, survey_coordinator_headers):
        """PRD §3.6: "Counting the vendor's existing non-terminal waves whose
        windows intersect the new window under the same any-intersection test
        (adjacency excluded), that count must remain strictly below the vendor's
        `max_concurrent_waves`; reaching the cap is rejected with
        `ERR_VENDOR_CAPACITY_EXCEEDED`."

        With capacity 1 the vendor's PLANNED CAHPS wave counts 1 against an
        overlapping HOS wave — the HOS wave passes its own (different-type) lane
        but hits the aggregate vendor cap.

        Design: Difficulty/resource_temporal_overlap/vendor_capacity_aggregate_intersection
        """
        sc = setup_survey_lane(max_concurrent_waves=1)
        resp = api.create_survey_wave(
            {"rating_cycle_id": sc["cycle"]["id"], "survey_type": "HOS",
             "vendor_id": sc["vendor"]["id"],
             "window_start": "2026-09-15T00:00:00Z",
             "window_end": "2026-10-15T00:00:00Z", "sample_size": 80},
            survey_coordinator_headers,
        )
        validate_error(resp, ApiErrorId.ERR_VENDOR_CAPACITY_EXCEEDED)

    def test_adjacent_wave_does_not_count_against_capacity(
            self, api, survey_coordinator_headers):
        """PRD §3.6: "Counting the vendor's existing non-terminal waves whose
        windows intersect the new window under the same any-intersection test
        (adjacency excluded), that count must remain strictly below the vendor's
        `max_concurrent_waves`; reaching the cap is rejected with
        `ERR_VENDOR_CAPACITY_EXCEEDED`."

        An adjacent HOS wave intersects zero existing windows, so it counts 0
        against the capacity-1 vendor and is accepted.

        Design: Difficulty/resource_temporal_overlap/vendor_capacity_aggregate_intersection
        """
        sc = setup_survey_lane(max_concurrent_waves=1)
        resp = api.create_survey_wave(
            {"rating_cycle_id": sc["cycle"]["id"], "survey_type": "HOS",
             "vendor_id": sc["vendor"]["id"],
             "window_start": "2026-10-01T00:00:00Z",
             "window_end": "2026-11-01T00:00:00Z", "sample_size": 80},
            survey_coordinator_headers,
        )
        wave = validate_success(resp, 201)
        assert wave["status"] == "PLANNED"


class TestWaveWindowValidationOrder:
    def test_inverted_window_reports_invalid_window_before_overlap(
            self, api, survey_coordinator_headers):
        """PRD §3.6: "The window must be well-formed — `window_start` strictly
        before `window_end`, else `ERR_INVALID_WINDOW` (HTTP 400)."
        PRD §2.11: "When a request fails more than one rule, the first applicable
        rule in the following priority order determines the rejection, so earlier
        failures mask later ones:"
        PRD §2.11: "9. **Cross-field sanity** — `ERR_INVALID_WINDOW`,
        `ERR_CUTPOINTS_NON_MONOTONIC`, and `ERR_INTERVENTION_GAP_TYPE_MISMATCH`
        (all HTTP 400)."
        PRD §2.11: "10. **Temporal overlap and capacity** —
        `ERR_SURVEY_WINDOW_OVERLAP` and `ERR_VENDOR_CAPACITY_EXCEEDED` (both HTTP
        409)."

        The inverted window [2026-09-20, 2026-09-10) also intersects the existing
        wave's raw bounds, but the priority-9 sanity check masks the priority-10
        overlap check.

        Design: Difficulty/priority_pair_validation_conflict/constraint_beats_temporal_on_wave_create
        """
        sc = setup_survey_lane()
        resp = api.create_survey_wave(
            {"rating_cycle_id": sc["cycle"]["id"], "survey_type": "CAHPS",
             "vendor_id": sc["vendor"]["id"],
             "window_start": "2026-09-20T00:00:00Z",
             "window_end": "2026-09-10T00:00:00Z", "sample_size": 100},
            survey_coordinator_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_WINDOW)

    def test_inverted_window_creates_no_wave(self, api, survey_coordinator_headers):
        """PRD §3.6: "The window must be well-formed — `window_start` strictly
        before `window_end`, else `ERR_INVALID_WINDOW` (HTTP 400)."

        The rejected planning request persists no wave: only the pre-existing
        wave remains listed.

        Design: Difficulty/priority_pair_validation_conflict/constraint_beats_temporal_on_wave_create
        """
        sc = setup_survey_lane()
        resp = api.create_survey_wave(
            {"rating_cycle_id": sc["cycle"]["id"], "survey_type": "CAHPS",
             "vendor_id": sc["vendor"]["id"],
             "window_start": "2026-09-20T00:00:00Z",
             "window_end": "2026-09-10T00:00:00Z", "sample_size": 100},
            survey_coordinator_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_WINDOW)
        _waves, meta = validate_paginated(api.list_survey_waves(
            survey_coordinator_headers,
            params={"rating_cycle_id": sc["cycle"]["id"]}))
        assert meta["total_count"] == 1, "The rejected wave is not persisted"


class TestSurveyScoring:
    def test_survey_response_rate_boundary_sufficient(
            self, api, survey_coordinator_headers):
        """PRD §2.4: "At server startup the logical clock reads exactly
        `2026-08-01T00:00:00Z`."
        PRD §3.6: "Fielding is gated on the logical clock: moving a `PLANNED` wave
        to `FIELDING` requires the current logical time to fall at or after
        `window_start` and strictly before `window_end`, and moving a `FIELDING`
        wave to `CLOSED_FIELD` requires the logical time to be at or after
        `window_end`; either check failing is `ERR_WAVE_OUTSIDE_WINDOW`, and a wave
        in the wrong from-state for the requested move is
        `ERR_INVALID_STATE_TRANSITION`."
        PRD §3.6: "At that moment the `response_rate` is computed as
        `response_count` divided by `sample_size`, rounded half up to 4 decimal
        places, and `sufficient` is set to true exactly when the rounded rate is at
        least 0.40 — a rate of exactly 0.40 is sufficient."

        120 / 300 = exactly 0.40, which meets the sufficiency constant.

        Design: Corner/calculations/survey_response_rate_boundary_sufficient
        """
        sc = setup_survey_lane(sample_size=300)
        wave_id = sc["wave"]["id"]

        # The startup clock (2026-08-01) is before window_start 2026-09-01.
        resp = api.transition_survey_wave(wave_id, "FIELDING", survey_coordinator_headers)
        validate_error(resp, ApiErrorId.ERR_WAVE_OUTSIDE_WINDOW)

        set_clock("2026-09-15T00:00:00Z")
        fielding = validate_success(api.transition_survey_wave(
            wave_id, "FIELDING", survey_coordinator_headers))
        assert fielding["status"] == "FIELDING"

        set_clock("2026-10-02T00:00:00Z")
        closed = validate_success(api.transition_survey_wave(
            wave_id, "CLOSED_FIELD", survey_coordinator_headers))
        assert closed["status"] == "CLOSED_FIELD"

        scored = validate_success(api.transition_survey_wave(
            wave_id, "SCORED", survey_coordinator_headers, response_count=120))
        assert scored["status"] == "SCORED"
        assert scored["response_rate"] == pytest.approx(0.4), (
            f"120/300 rounds to exactly 0.40, got {scored['response_rate']}"
        )
        assert scored["sufficient"] is True, "Exactly 0.40 is sufficient"


class TestComplaintResolutionBranches:
    def test_resolved_valid_increments_complaints_numerator(
            self, api, complaints_auditor_headers):
        """PRD §3.8: "Moving the case to `RESOLVED_VALID` credits the complaints
        measure: the cycle's performance whose measure has `data_source` equal to
        `COMPLAINTS` — provided that performance is not `LOCKED` — has its
        `numerator` increased by 1, with `raw_value`, `published_star`, and
        `draft_star` recomputed and the cycle's `live_weighted_stars` refreshed; if
        that performance is `LOCKED`, its numerator is left unchanged."

        The numerator moves 9 -> 10 and raw_value recomputes to 0.50.

        Design: Difficulty/non_linear_state_machine/complaint_resolution_branching_divergence
        """
        sc = setup_complaints_measure_scenario(
            9, 20, complaints=[("BILLING", "2026-08-05T00:00:00Z")])
        case = sc["cases"][0]

        resolved = resolve_complaint(case["id"], "RESOLVED_VALID")
        assert resolved["status"] == "RESOLVED_VALID"

        perf = validate_success(api.get_measure_performance(
            sc["performance"]["id"], complaints_auditor_headers))
        assert perf["numerator"] == 10
        assert perf["raw_value"] == pytest.approx(0.5)

    def test_resolved_invalid_leaves_numerator_unchanged(
            self, api, complaints_auditor_headers):
        """PRD §3.8: "Moving the case to `RESOLVED_INVALID` records the same
        `resolved_at` and computes `late_resolution` by the same strict 30-day
        rule, but changes no measure numerator."

        Design: Difficulty/non_linear_state_machine/complaint_resolution_branching_divergence
        """
        sc = setup_complaints_measure_scenario(
            9, 20, complaints=[("ENROLLMENT", "2026-08-06T00:00:00Z")])
        case = sc["cases"][0]

        resolved = resolve_complaint(case["id"], "RESOLVED_INVALID")
        assert resolved["status"] == "RESOLVED_INVALID"

        perf = validate_success(api.get_measure_performance(
            sc["performance"]["id"], complaints_auditor_headers))
        assert perf["numerator"] == 9, (
            "The INVALID branch changes no measure numerator"
        )
        assert perf["raw_value"] == pytest.approx(0.45)


class TestComplaintTimeliness:
    def test_complaint_late_resolution_threshold(self, api, complaints_auditor_headers):
        """PRD §3.8: "The case's `resolved_at` is stamped from the logical clock,
        and `late_resolution` is computed as true exactly when the elapsed time
        from `filed_at` to `resolved_at` is strictly greater than 30 days — a
        resolution at exactly 30 days is not late."
        PRD §3.8: "When `late_resolution` is true and the cycle's complaints-source
        performance exists, that performance's `timeliness_alert` is set to true
        and stays set permanently."

        Filed 2026-08-01T00:00:00Z: resolving at 2026-08-31T00:00:00Z is exactly
        30 days (not late); resolving at 2026-08-31T00:00:01Z is late.

        Design: Corner/calculations/complaint_late_resolution_threshold
        """
        sc = setup_complaints_measure_scenario(
            0, 100,
            complaints=[("BILLING", "2026-08-01T00:00:00Z"),
                        ("ENROLLMENT", "2026-08-01T00:00:00Z")])
        c1, c2 = sc["cases"]

        set_clock("2026-08-31T00:00:00Z")
        resolved1 = resolve_complaint(c1["id"], "RESOLVED_VALID")
        assert resolved1["late_resolution"] is False, (
            "Exactly 30 days is not late (strictly-greater rule)"
        )

        set_clock("2026-08-31T00:00:01Z")
        resolved2 = resolve_complaint(c2["id"], "RESOLVED_VALID")
        assert resolved2["late_resolution"] is True, (
            "30 days plus one second is late"
        )

        perf = validate_success(api.get_measure_performance(
            sc["performance"]["id"], complaints_auditor_headers))
        assert perf["numerator"] == 2, (
            "Both RESOLVED_VALID resolutions credit the complaints measure"
        )
        assert perf["timeliness_alert"] is True, (
            "The late resolution raises timeliness_alert permanently"
        )
