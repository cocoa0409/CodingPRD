"""Booking confirmation: closed-interval engagement overlap, immediate
consistency, and Taft-Hartley filing access (PRD sections 2.1, 2.2, 3.9)."""
from test_helpers import (
    ApiErrorId,
    book_talent_on_new_role,
    create_production,
    create_talent,
    set_clock,
    setup_pending_booking,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS

DIRECTOR = TEST_USERS["director_headers"]
ASSOCIATE = TEST_USERS["associate_headers"]
COORDINATOR = TEST_USERS["coordinator_headers"]


class TestEngagementOverlap:
    def test_shared_boundary_day_is_overlap(self, api):
        """PRD section 3.9: "Overlap uses **closed** day-intervals, the opposite
        convention from sessions and holds: another `CONFIRMED` booking belonging
        to the same talent (via its submission) overlaps when the existing
        engagement's `engagement_start` falls on or before this memo's
        `engagement_end` and this memo's `engagement_start` falls on or before the
        existing engagement's `engagement_end` — a shared boundary day counts as
        overlap. A clash is rejected with `ERR_ENGAGEMENT_OVERLAP` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/engagement_overlap_closed_interval_booking_semantics
        """
        set_clock("2026-08-03T00:00:00Z")
        production = create_production(production_type="TV_SERIES")
        talent = create_talent()
        # Confirmed engagement 2026-08-10..2026-08-12.
        book_talent_on_new_role(
            production["id"], talent, "ER1", "2026-08-10", "2026-08-12",
            session_date="2026-08-04", is_union_covered=False,
        )
        # New engagement 2026-08-12..2026-08-14 shares the boundary day 08-12.
        second = book_talent_on_new_role(
            production["id"], talent, "ER2", "2026-08-12", "2026-08-14",
            session_date="2026-08-05", is_union_covered=False, confirm=False,
        )
        resp = api.confirm_booking(second["booking"]["id"], COORDINATOR)
        validate_error(resp, ApiErrorId.ERR_ENGAGEMENT_OVERLAP)
        after = validate_success(api.get_booking(second["booking"]["id"], COORDINATOR))
        assert after["status"] == "PENDING", "rejected confirm leaves the booking PENDING"

    def test_disjoint_adjacent_engagement_confirms(self, api):
        """PRD section 3.9: "Overlap uses **closed** day-intervals, the opposite
        convention from sessions and holds: another `CONFIRMED` booking belonging
        to the same talent (via its submission) overlaps when the existing
        engagement's `engagement_start` falls on or before this memo's
        `engagement_end` and this memo's `engagement_start` falls on or before the
        existing engagement's `engagement_end` — a shared boundary day counts as
        overlap."
        PRD section 3.9: "On success the server stamps `confirmed_at` with the
        current logical clock, recomputes the talent's
        `union_engagement_count_365d`, auto-creates a `PENDING` Taft-Hartley
        report under the same three-condition test (union-signatory production,
        union-covered role, `NON_UNION` talent) with its `filing_deadline` set to
        fifteen calendar days after `confirmed_at`, and increments the booking's
        `version`."

        Design: Difficulty/resource_temporal_overlap/engagement_overlap_closed_interval_booking_semantics
        """
        set_clock("2026-08-03T00:00:00Z")
        production = create_production(production_type="TV_SERIES")
        talent = create_talent()
        book_talent_on_new_role(
            production["id"], talent, "ER1", "2026-08-10", "2026-08-12",
            session_date="2026-08-04", is_union_covered=False,
        )
        # 2026-08-13..2026-08-14 starts after the existing engagement's last day.
        second = book_talent_on_new_role(
            production["id"], talent, "ER2", "2026-08-13", "2026-08-14",
            session_date="2026-08-05", is_union_covered=False, confirm=False,
        )
        resp = api.confirm_booking(second["booking"]["id"], COORDINATOR)
        booking = validate_success(resp)
        assert booking["status"] == "CONFIRMED", "no shared day means no overlap under closed-interval semantics"


class TestConfirmVisibility:
    def test_confirm_effects_visible_immediately(self, api):
        """PRD section 3.9: "On success the server stamps `confirmed_at` with the
        current logical clock, recomputes the talent's
        `union_engagement_count_365d`, auto-creates a `PENDING` Taft-Hartley
        report under the same three-condition test (union-signatory production,
        union-covered role, `NON_UNION` talent) with its `filing_deadline` set to
        fifteen calendar days after `confirmed_at`, and increments the booking's
        `version`."
        PRD section 2.2: "Unless otherwise noted, operations that create or modify
        a resource will return the created or updated resource object in the data
        field."

        Design: Corner/consistency_model/booking_confirm_immediate_visibility
        """
        ctx = setup_pending_booking(
            production_overrides={"production_type": "TV_SERIES", "union_signatory": True},
            role_overrides={
                "is_union_covered": True,
                "engagement_start": "2026-08-10T00:00:00Z",
                "engagement_end": "2026-08-11T00:00:00Z",
            },
            accept_overrides={
                "engagement_start": "2026-08-10T00:00:00Z",
                "engagement_end": "2026-08-11T00:00:00Z",
                "proration_mode": "CALENDAR_SPAN",
            },
        )
        resp = api.confirm_booking(ctx["booking"]["id"], COORDINATOR)
        booking = validate_success(resp)
        assert booking["status"] == "CONFIRMED", "CONFIRMED visible in the confirm response itself"
        assert booking.get("confirmed_at") is not None, "confirmed_at stamped atomically with the transition"
        reread = validate_success(api.get_booking(ctx["booking"]["id"], COORDINATOR))
        assert reread["status"] == "CONFIRMED", "immediate re-read is consistent, no asynchronous lag"


class TestTaftHartleyFilingAccess:
    def test_associate_cannot_file_taft_hartley(self, api):
        """PRD section 4: "| POST | `/casting/taft-hartley/{id}/file` | File a
        report (on-time from PENDING, or late from LATE) | ProductionCoordinator |".
        PRD section 2.1: "A request whose role is recognized but not permitted for
        the target endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
        PRD section 3.9: "On success the server stamps `confirmed_at` with the
        current logical clock, recomputes the talent's
        `union_engagement_count_365d`, auto-creates a `PENDING` Taft-Hartley
        report under the same three-condition test (union-signatory production,
        union-covered role, `NON_UNION` talent) with its `filing_deadline` set to
        fifteen calendar days after `confirmed_at`, and increments the booking's
        `version`."

        Design: Corner/rbac/associate_cannot_file_taft_hartley
        """
        set_clock("2026-08-03T00:00:00Z")
        production = create_production(title="RB2", production_type="TV_SERIES", union_signatory=True)
        talent = create_talent(union_status="NON_UNION")
        book_talent_on_new_role(
            production["id"], talent, "R", "2026-08-10", "2026-08-11",
            session_date="2026-08-04", is_union_covered=True,
        )
        data = validate_success(api.list_production_taft_hartley(production["id"], COORDINATOR))
        # validate_success on a list endpoint returns the data array.
        assert len(data) >= 1, "a PENDING report was auto-created by the confirmed union-covered non-union booking"
        report_id = data[0]["id"]
        resp = api.file_taft_hartley(report_id, ASSOCIATE)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)
