"""Difficulty: resource_temporal_overlap (appetite half-open windows vs
report closed periods). Two instances x two tests each."""
import pytest

from test_helpers import (
    api_client,
    validate_success, validate_error,
    ApiErrorId,
    create_category, create_appetite, approve_appetite,
    create_approved_appetite,
    create_report, finalize_report, get_report,
    make_risk_manager_headers, make_board_reporter_headers,
    USER_RISK_MANAGER, USER_RISK_MANAGER_2, USER_BOARD_REPORTER,
)


class TestAppetiteHalfOpenWindowOverlap:
    """Difficulty instance: half-open [from, to) semantics — overlap rejected,
    exact adjacency accepted."""

    def test_overlapping_window_rejected(self):
        """PRD §3.1: "Among `APPROVED` statements of the same category these
        half-open windows must never overlap, a rule enforced both when a
        statement is created and again when it is approved... An overlap is
        rejected with `ERR_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/appetite_half_open_window_overlap
        """
        cat = create_category(name="CW")
        create_approved_appetite(
            cat["id"], tolerance_score=10, acceptance_cap_score=20,
            effective_from="2026-01-01T00:00:00Z",
            effective_to="2027-01-01T00:00:00Z",
        )
        # Overlapping window: starts inside APPROVED window
        res = api_client.create_appetite_statement(
            {
                "category_id": cat["id"],
                "tolerance_score": 12, "acceptance_cap_score": 22,
                "effective_from": "2026-06-01T00:00:00Z",
                "effective_to": "2027-06-01T00:00:00Z",
            },
            make_risk_manager_headers(USER_RISK_MANAGER),
        )
        validate_error(res, ApiErrorId.ERR_WINDOW_OVERLAP.value)

    def test_adjacent_window_accepted(self):
        """PRD §3.1: "adjacency, where one window's `effective_from` equals
        another's `effective_to`, is permitted."

        Design: Difficulty/resource_temporal_overlap/appetite_half_open_window_overlap
        """
        cat = create_category(name="CW")
        create_approved_appetite(
            cat["id"], tolerance_score=10, acceptance_cap_score=20,
            effective_from="2026-01-01T00:00:00Z",
            effective_to="2027-01-01T00:00:00Z",
        )
        # Adjacent: starts exactly at the prior window's end (exclusive)
        res = api_client.create_appetite_statement(
            {
                "category_id": cat["id"],
                "tolerance_score": 12, "acceptance_cap_score": 22,
                "effective_from": "2027-01-01T00:00:00Z",
                "effective_to": "2028-01-01T00:00:00Z",
            },
            make_risk_manager_headers(USER_RISK_MANAGER),
        )
        new_stmt = validate_success(res, 201)
        assert new_stmt["status"] == "DRAFT"
        # Approval is also allowed (window-overlap re-check at approve)
        approve_res = api_client.approve_appetite_statement(
            new_stmt["id"], make_risk_manager_headers(USER_RISK_MANAGER_2),
        )
        assert validate_success(approve_res, 200)["status"] == "APPROVED"


class TestReportClosedPeriodSharedBoundary:
    """Difficulty instance: closed [start, end] — shared boundary date IS an
    overlap; only a strictly-later start passes."""

    def test_shared_boundary_finalize_rejected(self):
        """PRD §3.8: "Finalization, likewise a `BoardReporter` act, moves
        `DRAFT` → `FINALIZED` and is rejected with
        `ERR_REPORT_PERIOD_OVERLAP` when any other `FINALIZED` report's
        closed period overlaps this report's closed period, again counting
        a shared boundary date as overlap."

        Design: Difficulty/resource_temporal_overlap/report_closed_period_shared_boundary_overlap
        """
        rep1 = create_report(
            period_start="2026-01-01T00:00:00Z",
            period_end="2026-03-31T00:00:00Z",
            variant="FINAL",
        )
        finalize_report(rep1["id"])
        # Shared boundary: rep2 starts on the day rep1 ends
        rep2 = create_report(
            period_start="2026-03-31T00:00:00Z",
            period_end="2026-06-30T00:00:00Z",
            variant="FINAL",
        )
        res = api_client.finalize_report(
            rep2["id"], make_board_reporter_headers(USER_BOARD_REPORTER),
        )
        validate_error(res, ApiErrorId.ERR_REPORT_PERIOD_OVERLAP.value)
        # rep2 stays DRAFT after failed finalize
        got = validate_success(
            api_client.get_report(
                rep2["id"], make_board_reporter_headers(USER_BOARD_REPORTER),
            ), 200,
        )
        assert got["status"] == "DRAFT"

    def test_strictly_later_start_finalize_succeeds(self):
        """PRD §3.8: "Finalization, likewise a `BoardReporter` act, moves
        `DRAFT` → `FINALIZED`".

        Design: Difficulty/resource_temporal_overlap/report_closed_period_shared_boundary_overlap
        """
        rep1 = create_report(
            period_start="2026-01-01T00:00:00Z",
            period_end="2026-03-31T00:00:00Z",
            variant="FINAL",
        )
        finalize_report(rep1["id"])
        # Strictly later start: no shared boundary
        rep3 = create_report(
            period_start="2026-04-01T00:00:00Z",
            period_end="2026-06-30T00:00:00Z",
            variant="FINAL",
        )
        res = api_client.finalize_report(
            rep3["id"], make_board_reporter_headers(USER_BOARD_REPORTER),
        )
        assert validate_success(res, 200)["status"] == "FINALIZED"
