"""Audio description: nested gap-coverage rounding, the inclusive band edges,
per-segment fit, closed-interval studio geometry, and the BUNDLE coverage
bubble-up (PRD §3.2, §3.5)."""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_same_instant,
    conform_track,
    create_ad_track,
    create_track,
    finalize_qc,
    get_success_data,
    make_ad_producer_headers,
    make_editor_headers,
    make_qc_headers,
    set_clock,
    setup_ad_track_in_recording,
    setup_in_production_order,
    track_submit_and_enqueue,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import EDITOR, OPS

MONDAY = "2026-08-03T10:00:00Z"


class TestGapCoverageNestedRounding:
    """Difficulty: per-gap-first rounding is pinned; 34.85/34.95/34.95 per-gap
    utilizations mean to 35.0 (PASS at the inclusive lower band edge)."""

    def _ad_order(self, api):
        set_clock(MONDAY)
        return setup_in_production_order(compliance_standard="INTERNAL",
                                         service_type="AUDIO_DESCRIPTION",
                                         frame_rate="FPS_25")

    def test_per_gap_first_rounding_passes_at_lower_edge(self, api):
        """PRD §3.5: "Coverage is measured per gap first: for each placed
        segment, its `duration_ms` is divided by the length of its gap in
        milliseconds, the quotient multiplied by one hundred, and that per-gap
        utilization rounded half-up to one decimal place. The track's
        `gap_coverage_pct` is then the mean of those per-gap utilizations,
        itself rounded half-up to one decimal place."
        PRD §3.5: "Submission is rejected with `ERR_GAP_COVERAGE_OUT_OF_BAND`
        (HTTP 422) unless the coverage lands between 35.0 and 85.0 inclusive."

        Design: Difficulty/combinatorial_formula/ad_gap_coverage_nested_rounding
        """
        ctx = self._ad_order(api)
        ad = create_ad_track(
            ctx["work_order"]["id"],
            gaps=[{"start_ms": 5000, "end_ms": 105000},
                  {"start_ms": 200000, "end_ms": 300000},
                  {"start_ms": 400000, "end_ms": 500000}],
            segments=[{"gap_index": 0, "duration_ms": 34850, "text": "seg-A"},
                      {"gap_index": 1, "duration_ms": 34950, "text": "seg-B"},
                      {"gap_index": 2, "duration_ms": 34950, "text": "seg-C"}],
        )
        submitted = validate_success(
            api.submit_script(ad["id"], make_ad_producer_headers("ad-1")))
        # Per-gap: 34.85->34.9, 34.95->35.0, 34.95->35.0; mean -> 35.0.
        assert float(submitted["gap_coverage_pct"]) == pytest.approx(35.0, abs=1e-9)
        assert submitted["ad_status"] == "SCRIPT_REVIEW"

    def test_just_below_lower_band_edge_rejected(self, api):
        """PRD §3.5: "Submission is rejected with `ERR_GAP_COVERAGE_OUT_OF_BAND`
        (HTTP 422) unless the coverage lands between 35.0 and 85.0 inclusive."

        Design: Difficulty/combinatorial_formula/ad_gap_coverage_nested_rounding
        """
        ctx = self._ad_order(api)
        ad = create_ad_track(
            ctx["work_order"]["id"],
            gaps=[{"start_ms": 1000, "end_ms": 101000}],
            segments=[{"gap_index": 0, "duration_ms": 34900, "text": "short"}],
        )
        resp = api.submit_script(ad["id"], make_ad_producer_headers("ad-1"))
        validate_error(resp, ApiErrorId.ERR_GAP_COVERAGE_OUT_OF_BAND)
        after = validate_success(api.get_ad_track(ad["id"], OPS))
        assert after["ad_status"] == "SCRIPTING"


class TestGapCoverageBandEdges:
    def test_upper_band_edge_inclusive(self, api):
        """PRD §3.5: "Submission is rejected with `ERR_GAP_COVERAGE_OUT_OF_BAND`
        (HTTP 422) unless the coverage lands between 35.0 and 85.0 inclusive."

        Design: Corner/calculations/ad_coverage_upper_band_edge
        """
        set_clock(MONDAY)
        ctx = setup_in_production_order(compliance_standard="INTERNAL",
                                        service_type="AUDIO_DESCRIPTION",
                                        frame_rate="FPS_25")
        ad_1 = create_ad_track(
            ctx["work_order"]["id"],
            gaps=[{"start_ms": 1000, "end_ms": 11000}],
            segments=[{"gap_index": 0, "duration_ms": 8500, "text": "edge-pass"}],
        )
        submitted = validate_success(
            api.submit_script(ad_1["id"], make_ad_producer_headers("ad-1")))
        assert float(submitted["gap_coverage_pct"]) == pytest.approx(85.0, abs=1e-9)
        assert submitted["ad_status"] == "SCRIPT_REVIEW"

        ad_2 = create_ad_track(
            ctx["work_order"]["id"],
            gaps=[{"start_ms": 1000, "end_ms": 11000}],
            segments=[{"gap_index": 0, "duration_ms": 8600, "text": "edge-fail"}],
        )
        resp = api.submit_script(ad_2["id"], make_ad_producer_headers("ad-1"))
        validate_error(resp, ApiErrorId.ERR_GAP_COVERAGE_OUT_OF_BAND)
        after = validate_success(api.get_ad_track(ad_2["id"], OPS))
        assert after["ad_status"] == "SCRIPTING"

    def test_segment_exceeds_gap_rejected(self, api):
        """PRD §3.5: "The `segments` array places descriptions into those
        windows; each entry names a `gap_index`, a `duration_ms` that is greater
        than zero and no longer than the referenced gap's length, and the `text`
        to be spoken."
        PRD §2.4: "then request shape and field constraints (`ERR_VALIDATION`)".

        Design: Corner/validations/ad_segment_exceeds_gap_rejected
        """
        set_clock(MONDAY)
        ctx = setup_in_production_order(compliance_standard="INTERNAL",
                                        service_type="AUDIO_DESCRIPTION",
                                        frame_rate="FPS_25")
        resp = api.create_ad_track(
            ctx["work_order"]["id"],
            {"language": "en-US", "narrator_name": "N1",
             "gaps": [{"start_ms": 1000, "end_ms": 11000}],
             "segments": [{"gap_index": 0, "duration_ms": 12000, "text": "too long"}]},
            make_ad_producer_headers("ad-1"))
        validate_error(resp, ApiErrorId.ERR_VALIDATION)


class TestStudioBookingWindow:
    """Difficulty: closed intervals with a 30-minute minimum gap — exactly 30
    admitted, 29 rejected."""

    def _two_recording_tracks(self, api):
        set_clock(MONDAY)
        ctx1 = setup_ad_track_in_recording(author="ad-1",
                                           gaps=[{"start_ms": 1000, "end_ms": 20000}],
                                           segments=[{"gap_index": 0, "duration_ms": 10000, "text": "d1"}])
        ctx2 = setup_ad_track_in_recording(author="ad-2", client_name="Second",
                                           gaps=[{"start_ms": 1000, "end_ms": 20000}],
                                           segments=[{"gap_index": 0, "duration_ms": 10000, "text": "d2"}])
        get_success_data(api.book_studio(
            ctx1["ad_track"]["id"],
            {"studio_id": "ST-A", "record_start_at": "2026-08-12T14:00:00Z",
             "record_end_at": "2026-08-12T15:00:00Z"},
            make_ad_producer_headers("ad-1")))
        return ctx1, ctx2

    def test_exactly_thirty_minute_gap_admitted(self, api):
        """PRD §3.5: "bookings on the same `studio_id`, across other AD tracks
        in `RECORDING` or `MIX_QC` with a booking present, conflict unless at
        least thirty minutes separate them — back-to-back is permitted only when
        the candidate's end plus thirty minutes is at or before the existing
        booking's start, or the candidate's start is at or after the existing
        booking's end plus thirty minutes".

        Design: Difficulty/resource_temporal_overlap/studio_closed_interval_min_gap
        """
        _, ctx2 = self._two_recording_tracks(api)
        booked = validate_success(api.book_studio(
            ctx2["ad_track"]["id"],
            {"studio_id": "ST-A", "record_start_at": "2026-08-12T15:30:00Z",
             "record_end_at": "2026-08-12T16:00:00Z"},
            make_ad_producer_headers("ad-2")))
        assert booked["studio_id"] == "ST-A"
        assert booked["record_start_at"] is not None

    def test_twenty_nine_minute_gap_rejected(self, api):
        """PRD §3.5: "a gap of twenty-nine minutes is a conflict and is rejected
        with `ERR_STUDIO_TURNOVER_VIOLATION` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/studio_closed_interval_min_gap
        """
        _, ctx2 = self._two_recording_tracks(api)
        get_success_data(api.book_studio(
            ctx2["ad_track"]["id"],
            {"studio_id": "ST-A", "record_start_at": "2026-08-12T15:30:00Z",
             "record_end_at": "2026-08-12T16:00:00Z"},
            make_ad_producer_headers("ad-2")))
        resp = api.book_studio(
            ctx2["ad_track"]["id"],
            {"studio_id": "ST-A", "record_start_at": "2026-08-12T15:29:00Z",
             "record_end_at": "2026-08-12T16:00:00Z"},
            make_ad_producer_headers("ad-2"))
        validate_error(resp, ApiErrorId.ERR_STUDIO_TURNOVER_VIOLATION)
        after = validate_success(api.get_ad_track(ctx2["ad_track"]["id"], OPS))
        assert after["record_start_at"] is not None, (
            "the failed re-booking must leave the prior booking stored"
        )
        assert_same_instant(after["record_start_at"], "2026-08-12T15:30:00Z")


class TestBundleCoverageBubbleUp:
    def test_bundle_ready_gate_is_conjunctive(self, api):
        """PRD §3.2: "The order then advances `IN_PRODUCTION` →
        `READY_FOR_DELIVERY` automatically when its required coverage is
        complete: for `CAPTIONS`, a current caption track (one not in
        `SUPERSEDED`, `ARCHIVED`, or `QC_FAILED_PERMANENT`) exists and is
        `CONFORMED`; for `AUDIO_DESCRIPTION`, an AD track is `CONFORMED`; for
        `BUNDLE`, both conditions hold."
        PRD §3.5: "Mix approval by a `QCSpecialist` (again not the author) moves
        `MIX_QC` → `CONFORMED` and triggers the same work-order coverage
        recompute as caption conform."

        Design: Corner/cross_cutting_layers/derived_bubbleup_ready_gate
        """
        set_clock(MONDAY)
        ctx = setup_in_production_order(compliance_standard="INTERNAL",
                                        service_type="BUNDLE", frame_rate="FPS_25")
        wo_id = ctx["work_order"]["id"]
        # Caption leg to CONFORMED.
        t_1 = create_track(wo_id, author="editor-1")
        track_submit_and_enqueue(t_1["id"], author="editor-1")
        finalize_qc(t_1["id"], minor_errors=100)
        conform_track(t_1["id"], author="editor-1")
        # AD leg to MIX_QC.
        ad = create_ad_track(wo_id, author="ad-1",
                             gaps=[{"start_ms": 1000, "end_ms": 21000}],
                             segments=[{"gap_index": 0, "duration_ms": 10000, "text": "d"}])
        get_success_data(api.submit_script(ad["id"], make_ad_producer_headers("ad-1")))
        get_success_data(api.approve_script(ad["id"], make_qc_headers("qc-1")))
        get_success_data(api.book_studio(
            ad["id"], {"studio_id": "ST-A",
                       "record_start_at": "2026-08-04T14:00:00Z",
                       "record_end_at": "2026-08-04T15:00:00Z"},
            make_ad_producer_headers("ad-1")))
        set_clock("2026-08-04T15:00:00Z")
        get_success_data(api.submit_mix(ad["id"], make_ad_producer_headers("ad-1")))

        mid = validate_success(api.get_work_order(wo_id, OPS))
        assert mid["order_status"] == "IN_PRODUCTION", (
            "caption-only coverage must not bubble a BUNDLE order"
        )
        get_success_data(api.approve_mix(ad["id"], make_qc_headers("qc-1")))
        end = validate_success(api.get_work_order(wo_id, OPS))
        assert end["order_status"] == "READY_FOR_DELIVERY"
        ad_after = validate_success(api.get_ad_track(ad["id"], OPS))
        assert ad_after["ad_status"] == "CONFORMED"
