"""Tour on-sale lifecycle driven by the logical clock, and the confirm-time
OCC gate (PRD §2.8, §3.4, §3.6).
"""
from test_helpers import (
    api_client, validate_success, validate_error,
    create_staged_tour, create_show_with_accepted_hold, confirm_show,
    confirm_show_payload, get_tour, set_clock,
    ApiErrorId, TEST_USERS,
)

TM = TEST_USERS["tour_manager_headers"]


class TestOpenOnSalePreconditions:
    def test_open_on_sale_without_confirmed_shows_rejected(self, api):
        """PRD §3.6: "Once at least one show is `CONFIRMED` and the tour's
        posture is `OPEN`, the manager opens the on-sale across the tour,
        moving it from `ROUTING` to `ON_SALE`. With no confirmed shows the open
        is rejected with `ERR_NO_CONFIRMED_SHOWS`; a restricted or frozen
        posture is rejected with `ERR_POSTURE_NOT_OPEN`."

        Design: Corner/state_machines/tour_open_on_sale_precondition_no_confirmed
        """
        staged = create_staged_tour(start_clock="2026-05-01T00:00:00Z")
        tid = staged["tour"]["id"]
        assert staged["tour"]["status"] == "ROUTING"
        res = api.open_on_sale(tid, TM)
        validate_error(res, ApiErrorId.ERR_NO_CONFIRMED_SHOWS.value)


class TestClockDrivesTourInProgress:
    def test_tour_auto_transitions_when_clock_reaches_on_sale(self, api):
        """PRD §3.6: "when the logical clock reaches the earliest `on_sale_at`
        among `CONFIRMED` shows, the tour moves automatically from `ON_SALE` to
        `IN_PROGRESS`, and every confirmed show whose on-sale moment has
        arrived re-projects its economics under the post-on-sale variant
        described in §3.8."

        Design: Corner/cross_cutting_complexity_layers/scheduled_action_clock_drives_tour_in_progress
        """
        staged = create_staged_tour(
            start_clock="2026-06-01T00:00:00Z",
            venue_overrides={"capacity": 100, "available_dates": ["2026-08-01"]})
        tid = staged["tour"]["id"]
        show, _ = create_show_with_accepted_hold(
            tid, staged["market"]["id"], staged["venue"]["id"],
            show_date="2026-08-01", on_sale_at="2026-07-01T00:00:00Z",
            avg_ticket_price_cents=5000,
            hold_overrides={"guarantee_cents": 100000, "versus_pct": 70})
        confirm_show(tid, show["id"])

        opened = validate_success(api.open_on_sale(tid, TM), 200)
        assert opened["status"] == "ON_SALE"

        # Just before the earliest on_sale_at: still ON_SALE.
        set_clock("2026-06-30T23:59:59Z")
        assert get_tour(tid)["status"] == "ON_SALE"

        # Once the clock has reached it: automatic transition, no manual call.
        set_clock("2026-07-01T00:00:01Z")
        assert get_tour(tid)["status"] == "IN_PROGRESS"


class TestStaleTourVersionOnConfirm:
    def test_confirm_with_stale_tour_version_rejected(self, api):
        """PRD §2.8: "**Show confirmation** requires `expected_tour_version`,
        carrying the client's last observed `version` of the tour. If the
        tour's `version` has advanced since the client read it — for example
        because another show was just confirmed, which mutates the tour's
        posture, its projected totals, and the venue's booked calendar by
        cascade — the request is rejected with `ERR_STALE_TOUR_VERSION`
        (HTTP 412)."

        Design: Corner/validations/stale_tour_version_on_confirm
        """
        staged = create_staged_tour(
            start_clock="2026-06-01T00:00:00Z",
            venue_overrides={"capacity": 100,
                             "available_dates": ["2026-08-01", "2026-08-02"]})
        tid = staged["tour"]["id"]
        mid = staged["market"]["id"]
        vid = staged["venue"]["id"]
        sa, _ = create_show_with_accepted_hold(
            tid, mid, vid, show_date="2026-08-01",
            on_sale_at="2026-07-01T00:00:00Z", avg_ticket_price_cents=5000,
            hold_overrides={"guarantee_cents": 100000, "versus_pct": 70})
        sb, _ = create_show_with_accepted_hold(
            tid, mid, vid, show_date="2026-08-02",
            on_sale_at="2026-07-01T00:00:00Z", avg_ticket_price_cents=5000,
            hold_overrides={"guarantee_cents": 100000, "versus_pct": 70})

        observed_version = get_tour(tid)["version"]

        # Confirming show A advances the tour version past the observed one.
        confirmed = validate_success(
            api.confirm_show(tid, sa["id"],
                             confirm_show_payload(observed_version), TM), 200)
        assert confirmed["status"] == "CONFIRMED"
        assert get_tour(tid)["version"] != observed_version

        # Confirming show B with the stale version is rejected.
        res = api.confirm_show(tid, sb["id"],
                               confirm_show_payload(observed_version), TM)
        validate_error(res, ApiErrorId.ERR_STALE_TOUR_VERSION.value)
