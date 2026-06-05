"""Resource temporal-overlap arithmetic: the buffered SYNC rights-window cooldown
versus the plain half-open statement-period overlap (PRD §3.2, §3.6).
"""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    TEST_USERS,
    create_rights_window_payload,
    create_statement_payload,
    setup_sync_catalog,
    create_rightsholder,
)

ADMIN = TEST_USERS["administrator_headers"]
OPERATOR = TEST_USERS["operator_headers"]


# =============================================================================
# Difficulty queue A — resource_temporal_overlap
# =============================================================================

class TestRightsWindowSyncCooldown:
    def test_sync_window_touching_boundary_rejected(self, api):
        """PRD §3.2: "For SYNC windows, a strict one-day cooldown buffer of 86400 seconds
        is required between windows: the new window's term_start must be at or after the
        existing window's term_end plus 86400 seconds, or else the new window's term_end
        plus 86400 seconds must be at or before the existing window's term_start."

        Design: Difficulty/resource_temporal_overlap/rights_window_sync_cooldown_buffer
        """
        # Existing ACTIVE SYNC window [2026-01-01, 2026-02-01); a second SYNC window
        # starting exactly at 2026-02-01 (touching, no 1-day gap) violates the buffer.
        ctx = setup_sync_catalog(
            clock="2026-01-01T00:00:00.000Z",
            window_start="2026-01-01T00:00:00.000Z",
            window_end="2026-02-01T00:00:00.000Z",
            grant_sync_window=True,
        )
        resp = api.create_rights_window(
            create_rights_window_payload(
                recording_id=ctx["recording"]["id"], territory="US", rights_type="SYNC",
                term_start="2026-02-01T00:00:00.000Z", term_end="2026-03-01T00:00:00.000Z"),
            ADMIN)
        validate_error(resp, ApiErrorId.ERR_WINDOW_OVERLAP)

    def test_sync_window_with_full_cooldown_buffer_allowed(self, api):
        """PRD §3.2: "For SYNC windows, a strict one-day cooldown buffer of 86400 seconds
        is required between windows: the new window's term_start must be at or after the
        existing window's term_end plus 86400 seconds, or else the new window's term_end
        plus 86400 seconds must be at or before the existing window's term_start."

        Design: Difficulty/resource_temporal_overlap/rights_window_sync_cooldown_buffer
        """
        # Existing [2026-01-01, 2026-02-01); a new SYNC window starting at 2026-02-02
        # (== term_end + 86400s) exactly satisfies the buffer and is accepted.
        ctx = setup_sync_catalog(
            clock="2026-01-01T00:00:00.000Z",
            window_start="2026-01-01T00:00:00.000Z",
            window_end="2026-02-01T00:00:00.000Z",
            grant_sync_window=True,
        )
        created = validate_success(api.create_rights_window(
            create_rights_window_payload(
                recording_id=ctx["recording"]["id"], territory="US", rights_type="SYNC",
                term_start="2026-02-02T00:00:00.000Z", term_end="2026-03-01T00:00:00.000Z"),
            ADMIN), expected_status=201)
        assert created["status"] == "ACTIVE", "full 1-day buffer satisfied -> window granted"


class TestStatementPeriodPlainHalfOpenOverlap:
    def test_touching_period_allowed(self, api):
        """PRD §3.6: "this uses plain half-open overlap with no buffer, so two periods
        that merely touch at a boundary — where the new period_start equals an existing
        period_end — are allowed, while any interior overlap is rejected with
        ERR_STATEMENT_PERIOD_OVERLAP."

        Design: Difficulty/resource_temporal_overlap/statement_period_plain_half_open_overlap
        """
        holder = create_rightsholder(legal_name="R6", party_type="WRITER")
        first = validate_success(api.create_statement(
            create_statement_payload(rightsholder_id=holder["id"],
                                     period_start="2026-01-01T00:00:00.000Z",
                                     period_end="2026-02-01T00:00:00.000Z"), OPERATOR), expected_status=201)
        assert first["status"] == "DRAFT"
        # A touching period [2026-02-01, 2026-03-01) (period_start == prior period_end).
        touching = validate_success(api.create_statement(
            create_statement_payload(rightsholder_id=holder["id"],
                                     period_start="2026-02-01T00:00:00.000Z",
                                     period_end="2026-03-01T00:00:00.000Z"), OPERATOR), expected_status=201)
        assert touching["status"] == "DRAFT", "touching boundaries allowed — no buffer"

    def test_interior_overlap_rejected(self, api):
        """PRD §3.6: "this uses plain half-open overlap with no buffer, so two periods
        that merely touch at a boundary — where the new period_start equals an existing
        period_end — are allowed, while any interior overlap is rejected with
        ERR_STATEMENT_PERIOD_OVERLAP."

        Design: Difficulty/resource_temporal_overlap/statement_period_plain_half_open_overlap
        """
        holder = create_rightsholder(legal_name="R6b", party_type="WRITER")
        validate_success(api.create_statement(
            create_statement_payload(rightsholder_id=holder["id"],
                                     period_start="2026-01-01T00:00:00.000Z",
                                     period_end="2026-02-01T00:00:00.000Z"), OPERATOR), expected_status=201)
        # Interior overlap [2026-01-15, 2026-02-15) overlaps the first.
        resp = api.create_statement(
            create_statement_payload(rightsholder_id=holder["id"],
                                     period_start="2026-01-15T00:00:00.000Z",
                                     period_end="2026-02-15T00:00:00.000Z"), OPERATOR)
        validate_error(resp, ApiErrorId.ERR_STATEMENT_PERIOD_OVERLAP)
