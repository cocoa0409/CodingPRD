"""Advance packet workflow: section RBAC, packet OCC, advance completeness,
and the day-sheet computed read (PRD §2.8, §3.5).
"""
from test_helpers import (
    api_client, validate_success, validate_error,
    create_staged_tour, create_show, create_show_with_accepted_hold,
    create_confirmed_show, approve_all_sections, submit_and_approve_section,
    create_budget_line_payload, get_packet, get_show,
    approve_section_payload, assert_advance_packet,
    ApiErrorId, TEST_USERS,
)

TM = TEST_USERS["tour_manager_headers"]
VENUE_REP = TEST_USERS["venue_rep_headers"]


def _stage_confirmed_show(api, capacity=100):
    staged = create_staged_tour(
        start_clock="2026-06-01T00:00:00Z",
        venue_overrides={"capacity": capacity, "available_dates": ["2026-08-01"]})
    tid = staged["tour"]["id"]
    show, hold = create_confirmed_show(
        tid, staged["market"]["id"], staged["venue"]["id"],
        show_date="2026-08-01", on_sale_at="2026-07-01T00:00:00Z",
        avg_ticket_price_cents=5000,
        hold_overrides={"guarantee_cents": 100000, "versus_pct": 70})
    return tid, show


class TestAdvancePacketRbac:
    def test_venue_rep_cannot_submit_section(self, api):
        """PRD §2.1: "A `VenueRep` approves or rejects individual
        advance-packet sections." — submission belongs to the TourManager, and
        "An attempt to perform an operation outside the caller's role is
        rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."

        Design: Corner/validations/rbac_venuerep_cannot_submit_advance
        """
        staged = create_staged_tour(start_clock="2026-05-01T00:00:00Z")
        tid = staged["tour"]["id"]
        show = create_show(tid, staged["market"]["id"], staged["venue"]["id"],
                           show_date="2026-08-01",
                           on_sale_at="2026-07-01T00:00:00Z",
                           avg_ticket_price_cents=5000)
        res = api.submit_packet_section(tid, show["id"], "tech_rider", VENUE_REP)
        validate_error(res, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS.value)

    def test_tour_manager_cannot_approve_section(self, api):
        """PRD §2.1: "A `VenueRep` approves or rejects individual
        advance-packet sections." — approval is exclusive to VenueRep, and
        "An attempt to perform an operation outside the caller's role is
        rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."

        Design: Corner/rbac/rbac_tour_manager_cannot_approve_advance
        """
        staged = create_staged_tour(start_clock="2026-06-01T00:00:00Z")
        tid = staged["tour"]["id"]
        show = create_show(tid, staged["market"]["id"], staged["venue"]["id"],
                           show_date="2026-08-01",
                           on_sale_at="2026-07-01T00:00:00Z",
                           avg_ticket_price_cents=5000)
        validate_success(
            api.submit_packet_section(tid, show["id"], "tech_rider", TM), 200)
        packet = get_packet(tid, show["id"])
        res = api.approve_packet_section(
            tid, show["id"], "tech_rider",
            approve_section_payload(packet["packet_revision"]), TM)
        validate_error(res, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS.value)


class TestAdvancePacketOcc:
    def test_stale_packet_revision_on_approve(self, api):
        """PRD §2.8: "**Approving an advance-packet section** requires
        `expected_packet_revision`, the client's last observed
        `packet_revision` of the packet. Because every section transition bumps
        `packet_revision`, a parallel approval or rejection on another section
        invalidates the client's view, and the approval is rejected with
        `ERR_STALE_PACKET_REVISION` (HTTP 412)."

        Design: Corner/cross_cutting_complexity_layers/occ_stale_packet_revision_on_approve
        """
        staged = create_staged_tour(start_clock="2026-06-01T00:00:00Z")
        tid = staged["tour"]["id"]
        show = create_show(tid, staged["market"]["id"], staged["venue"]["id"],
                           show_date="2026-08-01",
                           on_sale_at="2026-07-01T00:00:00Z",
                           avg_ticket_price_cents=5000)
        validate_success(
            api.submit_packet_section(tid, show["id"], "tech_rider", TM), 200)
        validate_success(
            api.submit_packet_section(tid, show["id"], "hospitality", TM), 200)

        packet_obs = get_packet(tid, show["id"])
        stale_revision = packet_obs["packet_revision"]

        # A parallel approval on another section bumps packet_revision.
        validate_success(
            api.approve_packet_section(tid, show["id"], "hospitality",
                                       approve_section_payload(stale_revision),
                                       VENUE_REP), 200)

        # The client's view is now stale.
        res = api.approve_packet_section(tid, show["id"], "tech_rider",
                                         approve_section_payload(stale_revision),
                                         VENUE_REP)
        validate_error(res, ApiErrorId.ERR_STALE_PACKET_REVISION.value)


class TestAdvanceCompleteness:
    def test_advance_with_section_pending_rejected(self, api):
        """PRD §3.5: "Advancing the show — the `CONFIRMED` to `ADVANCED`
        transition — requires every section `APPROVED` (or immigration
        `NOT_REQUIRED`); anything short is rejected with
        `ERR_ADVANCE_INCOMPLETE`."

        Design: Corner/errors/err_advance_incomplete_when_section_pending
        """
        tid, show = _stage_confirmed_show(api)
        # Only tech_rider moves forward; hospitality and immigration stay PENDING.
        submit_and_approve_section(tid, show["id"], "tech_rider")

        res = api.advance_show(tid, show["id"], TM)
        validate_error(res, ApiErrorId.ERR_ADVANCE_INCOMPLETE.value)


class TestDaySheet:
    def test_day_sheet_after_advance(self, api):
        """PRD §3.5: "The day sheet is exposed as a computed read over the
        show, returning its `show_id`, the `daysheet_issued` flag, the current
        `packet_revision`, and `budget_total_cents`, a rollup totaling the
        show's committed estimated costs." And: "Advancing flips the packet's
        `daysheet_issued` to true — the flag is true exactly when all three
        sections are approved (or immigration not required) **and** the show is
        `ADVANCED`".

        Design: Corner/endpoints/day_sheet_rollup_read
        """
        tid, show = _stage_confirmed_show(api)
        # A budget line created while the show is CONFIRMED is committed
        # (PRD §3.7: is_committed "becomes true once the show is `CONFIRMED`").
        line = validate_success(
            api.create_budget_line(tid, show["id"],
                                   create_budget_line_payload(estimated_cents=123000),
                                   TM), 201)
        assert line["is_committed"] is True

        packet = approve_all_sections(tid, show["id"])
        assert_advance_packet(packet)

        advanced = validate_success(api.advance_show(tid, show["id"], TM), 200)
        assert advanced["status"] == "ADVANCED"

        day_sheet = validate_success(api.get_day_sheet(tid, show["id"], TM), 200)
        assert day_sheet["show_id"] == show["id"]
        assert day_sheet["daysheet_issued"] is True, (
            "daysheet_issued once all sections are approved and the show is ADVANCED")
        assert isinstance(day_sheet["packet_revision"], int)
        assert day_sheet["budget_total_cents"] == 123000, (
            "rollup totaling the show's committed estimated costs")
