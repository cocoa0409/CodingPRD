"""Run-creation business checks: piece geometry, run-number uniqueness, and
the service-date window."""
import pytest

from test_helpers import (
    ApiErrorId,
    create_period,
    create_run_piece,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.test_users import TEST_USERS

SO = TEST_USERS["scheduling_officer_headers"]


class TestRunPieceGeometry:
    def test_overlapping_pieces_rejected(self, api):
        """PRD §3.2: "First, piece geometry: within each piece the
        `release_minutes` must be later than the `report_minutes`, and across
        the list the pieces must be non-overlapping and ascending — any
        overlap, inversion, or equal report-release pair is rejected with
        `ERR_INVALID_RUN_PIECES`."

        Design: Difficulty/resource_temporal_overlap/run_pieces_overlap_rejection
        """
        period = create_period(name="Ov")
        resp = api.create_run(
            period["id"],
            {
                "run_number": "RO",
                "service_date": "2026-09-07",
                # piece2.report 450 < piece1.release 500 -> overlap
                "pieces": [create_run_piece(300, 500, 200),
                           create_run_piece(450, 700, 250)],
            },
            SO,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_RUN_PIECES)

    def test_overlapping_pieces_persist_nothing(self, api):
        """PRD §3.2: "First, piece geometry: within each piece the
        `release_minutes` must be later than the `report_minutes`, and across
        the list the pieces must be non-overlapping and ascending — any
        overlap, inversion, or equal report-release pair is rejected with
        `ERR_INVALID_RUN_PIECES`."

        Design: Difficulty/resource_temporal_overlap/run_pieces_overlap_rejection
        """
        period = create_period(name="Ov2")
        resp = api.create_run(
            period["id"],
            {
                "run_number": "RO",
                "service_date": "2026-09-07",
                "pieces": [create_run_piece(300, 500, 200),
                           create_run_piece(450, 700, 250)],
            },
            SO,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_RUN_PIECES)
        data, meta = validate_paginated(api.list_runs(period["id"], SO))
        assert data == [], f"no run should be persisted, got {data}"
        assert meta["total_count"] == 0


class TestRunNumberUniqueness:
    def test_duplicate_run_number_rejected(self, api):
        """PRD §3.2: "Second, the `run_number` must be unique within the
        combination of period and schedule revision — a duplicate is rejected
        with `ERR_DUPLICATE_RUN_NUMBER`."

        Design: Corner/validations/duplicate_run_number_rejected
        """
        period = create_period(name="DP")
        validate_success(api.create_run(
            period["id"],
            {"run_number": "R1", "service_date": "2026-09-07",
             "pieces": [create_run_piece(300, 700, 400)]},
            SO,
        ), expected_status=201)
        resp = api.create_run(
            period["id"],
            {"run_number": "R1", "service_date": "2026-09-08",
             "pieces": [create_run_piece(300, 700, 400)]},
            SO,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_RUN_NUMBER)


class TestRunDateWindow:
    def test_service_date_outside_window_rejected(self, api):
        """PRD §3.2: "Third, the `service_date` must fall within the period's
        effective window from `effective_start_date` through
        `effective_end_date` — a date outside that window is rejected with
        `ERR_DATE_OUT_OF_RANGE`."

        Design: Corner/validations/run_date_out_of_range_rejected
        """
        period = create_period(name="DR")  # window 2026-09-01..2026-11-30
        resp = api.create_run(
            period["id"],
            {"run_number": "R1", "service_date": "2027-01-15",
             "pieces": [create_run_piece(300, 700, 400)]},
            SO,
        )
        validate_error(resp, ApiErrorId.ERR_DATE_OUT_OF_RANGE)
