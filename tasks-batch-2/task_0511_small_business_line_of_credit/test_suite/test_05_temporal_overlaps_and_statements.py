"""Remittance-window and statement-window temporal overlap rules, plus statement finalization.

Covers difficulty instances (resource_temporal_overlap) and corner instances (calculations,
validations).
"""
import pytest
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    validate_paginated,
    create_active_credit_line,
    take_draw,
    schedule_remittance,
    set_clock,
    create_remittance_payload,
    create_statement_payload,
    SV1,
)


class TestDailyRemittanceOverlap:
    def test_daily_adjacency_allowed_but_same_day_collides(self, api):
        """On a DAILY line, exact one-day adjacency is allowed but a same-day window collides.

        PRD §3.5: "On a DAILY line, two remittance windows must be separated by at least one
        calendar day, and the comparison is half-open so that exact adjacency is allowed."

        Design: Difficulty/resource_temporal_overlap/daily_remittance_gap_half_open_adjacency_allowed
        """
        set_clock("2026-05-18T00:00:00Z")
        _, _, _, line = create_active_credit_line(
            cadence="DAILY", feed_overrides={"pulled_at": "2026-05-17T00:00:00Z"}
        )
        take_draw(line["id"], 100_000)
        schedule_remittance(line["id"], "2026-05-21T00:00:00Z")
        # Adjacent next-day window is allowed.
        adj = schedule_remittance(line["id"], "2026-05-22T00:00:00Z")
        assert adj["status"] == "SCHEDULED"
        # A second window on the SAME day collides.
        res = api.create_remittance(line["id"], create_remittance_payload("2026-05-21T00:00:00Z"), SV1)
        validate_error(res, "ERR_REMITTANCE_OVERLAP")
        _, meta = validate_paginated(
            api.list_remittances(line["id"], SV1, params={"status": "SCHEDULED"})
        )
        assert meta["total_count"] == 2


class TestStatementWindowOverlap:
    def test_overlapping_statement_window_rejected(self, api):
        """A statement window overlapping an existing window is rejected (closed-containment).

        PRD §3.8: "The overlap test is closed-containment: two windows collide when the new
        start is before the existing end and the existing start is before the new end"

        Design: Difficulty/resource_temporal_overlap/statement_window_closed_containment_overlap_rejected
        """
        _, _, _, line = create_active_credit_line(cadence="WEEKLY")
        st1 = validate_success(
            api.create_statement(
                line["id"], create_statement_payload("2026-05-01T00:00:00Z", "2026-06-01T00:00:00Z"), SV1
            ),
            201,
        )
        assert st1["status"] == "OPEN"
        res = api.create_statement(
            line["id"], create_statement_payload("2026-05-15T00:00:00Z", "2026-06-15T00:00:00Z"), SV1
        )
        validate_error(res, "ERR_STATEMENT_OVERLAP")
        _, meta = validate_paginated(api.list_statements(line["id"], SV1))
        assert meta["total_count"] == 1


class TestStatementFinalize:
    def test_statement_period_end_before_start_returns_validation(self, api):
        """Opening a statement with period_end <= period_start returns ERR_VALIDATION (422).

        PRD §3.8: "A window whose period_end is not strictly after its period_start is a
        semantic error rejected with ERR_VALIDATION."

        Design: Corner/validations/statement_period_end_before_start_returns_validation
        """
        _, _, _, line = create_active_credit_line(cadence="DAILY")
        res = api.create_statement(
            line["id"], create_statement_payload("2026-06-01T00:00:00Z", "2026-05-01T00:00:00Z"), SV1
        )
        validate_error(res, "ERR_VALIDATION", expected_status=422)

    def test_finalize_computes_window_totals(self, api):
        """Finalizing reconstructs window totals from ledger entries and in-window draws.

        PRD §3.8: "The draws total is the sum of the principal of all draws whose drawn_at falls
        in the half-open window from period_start up to but not including period_end, and the
        fees assessed is the analogous sum of those draws' fees."
        PRD §3.8: "The closing principal is the balance_after_cents of the latest ledger entry
        created strictly before period_end, or the opening principal if no entry falls in the
        window."

        Design: Corner/calculations/statement_finalize_window_totals
        """
        set_clock("2026-05-10T00:00:00Z")
        _, _, _, line = create_active_credit_line(
            cadence="DAILY", feed_overrides={"pulled_at": "2026-05-09T00:00:00Z"}
        )
        take_draw(line["id"], 200_000)  # fee 16000, drawn at 2026-05-10 (in window)
        st = validate_success(
            api.create_statement(
                line["id"], create_statement_payload("2026-05-01T00:00:00Z", "2026-06-01T00:00:00Z"), SV1
            ),
            201,
        )
        set_clock("2026-06-02T00:00:00Z")
        finalized = validate_success(api.finalize_statement(st["id"], SV1), 200)
        assert finalized["status"] == "FINALIZED"
        assert finalized["opening_principal_cents"] == 0
        assert finalized["draws_total_cents"] == 200_000
        assert finalized["fees_assessed_cents"] == 16000
        assert finalized["closing_principal_cents"] == 200_000
