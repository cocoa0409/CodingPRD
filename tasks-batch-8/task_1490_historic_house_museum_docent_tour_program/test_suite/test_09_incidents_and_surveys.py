"""The CRITICAL-incident closure cascade and the visitor-survey loop."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    assert_visitor_survey,
    confirm_booking,
    create_general_booking,
    create_safety_incident_payload,
    create_survey_payload,
    get_booking,
    get_slot,
    setup_completed_slot_with_bookings,
    setup_open_slot,
    validate_success,
)

ADMIN = TEST_USERS["museum_admin_headers"]
CURATOR = TEST_USERS["curator_headers"]
COORDINATOR = TEST_USERS["docent_coordinator_headers"]
FRONT_DESK = TEST_USERS["front_desk_staff_headers"]


class TestCriticalIncidentCascade:
    """CRITICAL report -> room closure -> slot cancellations -> booking and
    shift cancellations with full refunds."""

    def _setup_incident_scenario(self):
        """OPEN slot starting 34 hours after the startup clock with a
        CONFIRMED booking (paid 2000) and a CONFIRMED LEAD shift."""
        ctx = setup_open_slot(start_at="2026-08-02T10:00:00Z")
        booking = create_general_booking(ctx["slot_id"], 2)
        confirm_booking(booking["id"], 2000)
        ctx["booking"] = booking
        return ctx

    def test_critical_incident_closes_room_and_cancels_slot(self):
        """PRD section 3.7: "Hop one: the room moves from `OPEN` to
        `CLOSED_RESTORATION`. Hop two: every slot whose route contains that
        room, sitting in `SCHEDULED`, `OPEN`, or `FULL`, and whose `start_at`
        is still after the logical clock, is cancelled."

        Design: Difficulty/transitive_cascade/critical_incident_cascade
        """
        ctx = self._setup_incident_scenario()
        resp = api_client.create_safety_incident(
            create_safety_incident_payload(
                ctx["rooms"][0]["id"], severity="CRITICAL",
                description="Water leak over the parquet"),
            CURATOR)
        validate_success(resp, expected_status=201)

        room = validate_success(
            api_client.get_room(ctx["rooms"][0]["id"], ADMIN))
        assert room["status"] == "CLOSED_RESTORATION", (
            f"hop 1: room must close for restoration, got {room['status']}"
        )
        slot = get_slot(ctx["slot_id"])
        assert slot["status"] == "CANCELLED", (
            f"hop 2: the future slot on the closed room must be CANCELLED, "
            f"got {slot['status']}"
        )

    def test_critical_incident_refunds_booking_in_full_and_cancels_shift(self):
        """PRD section 3.7: "Hop three: for each such slot, its bookings in
        `RESERVED` or `CONFIRMED` are cancelled — confirmed bookings refunded
        in full, bypassing the time tiers — and its shift assignments in
        `ASSIGNED` or `CONFIRMED` are cancelled, with staffing recomputed."
        PRD section 3.6: "Cancellations forced by the incident cascade of
        §3.7 bypass the tiers entirely and refund the full total."

        Design: Difficulty/transitive_cascade/critical_incident_cascade
        """
        ctx = self._setup_incident_scenario()
        resp = api_client.create_safety_incident(
            create_safety_incident_payload(
                ctx["rooms"][0]["id"], severity="CRITICAL",
                description="Water leak over the parquet"),
            CURATOR)
        validate_success(resp, expected_status=201)

        booking = get_booking(ctx["booking"]["id"])
        assert booking["status"] == "CANCELLED"
        # 34 hours before start a manual cancel would refund only 50%
        # (1000); the cascade bypasses the tiers and refunds in full.
        assert booking["refund_cents"] == 2000, (
            f"hop 3: cascade refund must be the full 2000, "
            f"got {booking['refund_cents']}"
        )
        shifts = validate_success(
            api_client.list_docent_shifts(ctx["docent_id"], COORDINATOR))
        by_id = {s["id"]: s for s in shifts}
        assert by_id[ctx["shift"]["id"]]["status"] == "CANCELLED", (
            f"hop 3: the slot's CONFIRMED shift must be CANCELLED, "
            f"got {by_id[ctx['shift']['id']]['status']}"
        )


class TestSurveyImmutability:

    def test_visitor_survey_immutable_no_version_field(self):
        """PRD section 2.4: "One exception exists: a visitor survey carries
        only `id` and `created_at`. Both `updated_at` and `version` are
        absent from surveys, because a survey never changes after submission
        except for a single review mark."
        PRD section 3.8: "New surveys sit in `SUBMITTED`, and per §2.4 a
        survey carries only `id` and `created_at` — no `updated_at`, no
        `version`."

        Design: Corner/entities/visitor_survey_immutable_no_version_field
        """
        ctx = setup_completed_slot_with_bookings(num_bookings=1)
        booking = ctx["bookings"][0]
        resp = api_client.submit_survey(
            booking["id"], create_survey_payload(), FRONT_DESK)
        data = validate_success(resp, expected_status=201)
        assert_visitor_survey(data)
        assert data["status"] == "SUBMITTED"
        assert data["booking_id"] == booking["id"]
        assert data["slot_id"] == ctx["slot_id"]


class TestRouteSurveySummary:

    def test_route_survey_summary_aggregation(self):
        """PRD section 3.8: "The survey summary for a route counts every
        survey whose slot belongs to that route, in either `SUBMITTED` or
        `REVIEWED` status, and reports `survey_count` alongside
        `avg_overall_rating` and `avg_interpretation_clarity` — the
        arithmetic means of the two rating fields, each rounded half-up to
        two decimal places."

        Design: Corner/endpoints/route_survey_summary_aggregation
        """
        ctx = setup_completed_slot_with_bookings(num_bookings=2)
        bk1, bk2 = ctx["bookings"]
        resp = api_client.submit_survey(
            bk1["id"],
            create_survey_payload(overall_rating=5, interpretation_clarity=4,
                                  would_recommend=True),
            FRONT_DESK)
        validate_success(resp, expected_status=201)
        resp = api_client.submit_survey(
            bk2["id"],
            create_survey_payload(overall_rating=3, interpretation_clarity=5,
                                  would_recommend=False),
            FRONT_DESK)
        validate_success(resp, expected_status=201)

        summary = validate_success(
            api_client.get_route_survey_summary(ctx["route_id"], CURATOR))
        assert summary["survey_count"] == 2
        assert summary["avg_overall_rating"] == pytest.approx(4.0), (
            f"mean of 5 and 3 must be 4.0, "
            f"got {summary['avg_overall_rating']}"
        )
        assert summary["avg_interpretation_clarity"] == pytest.approx(4.5), (
            f"mean of 4 and 5 must be 4.5, "
            f"got {summary['avg_interpretation_clarity']}"
        )

    def test_route_survey_summary_empty_zero(self):
        """PRD section 3.8: "When a route has no surveys at all, the count is
        0 and both averages are 0.0."

        Design: Corner/endpoints/route_survey_summary_empty_zero
        """
        from test_helpers import create_room, create_route
        room = create_room()
        route = create_route([room["id"]])
        summary = validate_success(
            api_client.get_route_survey_summary(route["id"], CURATOR))
        assert summary["survey_count"] == 0
        assert summary["avg_overall_rating"] == pytest.approx(0.0)
        assert summary["avg_interpretation_clarity"] == pytest.approx(0.0)
