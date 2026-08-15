"""Operator staffing, group bookings, deposits, capacity, no-show throttle,
resignation guard."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_certification,
    create_completed_event,
    create_confirmed_event,
    create_event,
    create_group_booking,
    create_member,
    create_member_with_paid_dues,
    create_operator_assignment_payload,
    create_reserved_loan,
    create_scheduled_event,
    create_telescope,
    create_tier,
    get_success_data,
    invite_and_accept_operator,
    make_member_headers,
    set_clock,
    setup_member_with_cert_and_scope,
    validate_error,
    validate_success,
    create_checked_out_loan,
)

COORDINATOR = TEST_USERS["event_coordinator_headers"]
OFFICER = TEST_USERS["club_officer_headers"]
CHAIR = TEST_USERS["equipment_chair_headers"]


class TestOperatorOverlapClosedTouch:
    def test_touching_event_windows_conflict_on_accept(self, api):
        """PRD: "When a member accepts an operator assignment, the host
        event's window is compared against the windows of that member's
        other confirmed assignments using **closed-interval** semantics: a
        touch at exactly `window_end == window_start` counts as an overlap,
        because operators need teardown time between events. A conflicting
        acceptance is rejected with `ERR_OPERATOR_OVERLAP` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/operator_overlap_closed_touch
        """
        member, d1, _cert = setup_member_with_cert_and_scope(
            equipment_class="DOBSONIAN", member_name="Touching Tim")
        d2 = create_telescope(name="Dob 2", equipment_class="DOBSONIAN")
        e1 = create_event(title="E1", event_kind="MEMBER_NIGHT",
                          window_start="2026-08-15T01:00:00Z",
                          window_end="2026-08-15T05:00:00Z",
                          moon_illumination_pct=90)
        e2 = create_event(title="E2", event_kind="MEMBER_NIGHT",
                          window_start="2026-08-15T05:00:00Z",
                          window_end="2026-08-15T09:00:00Z",
                          moon_illumination_pct=90)
        invite_and_accept_operator(e1["id"], member, d1)
        a2 = get_success_data(api.create_operator_assignment(
            create_operator_assignment_payload(e2["id"], member["id"], d2["id"]),
            COORDINATOR))

        resp = api.accept_assignment(a2["id"], make_member_headers(member["id"]))
        validate_error(resp, ApiErrorId.ERR_OPERATOR_OVERLAP)
        assert resp.status_code == 409, (
            "E2.window_start == E1.window_end: closed-touch semantics "
            "counts this as overlap, unlike loans")

        after = validate_success(api.get_operator_assignment(a2["id"], COORDINATOR))
        assert after["status"] == "INVITED"

    def test_non_touching_event_windows_accept(self, api):
        """PRD: "a touch at exactly `window_end == window_start` counts as
        an overlap, because operators need teardown time between events"
        PRD: "Accepting moves `INVITED → CONFIRMED`"

        Design: Difficulty/resource_temporal_overlap/operator_overlap_closed_touch
        """
        member, d1, _cert = setup_member_with_cert_and_scope(
            equipment_class="DOBSONIAN", member_name="Gap Gus")
        d2 = create_telescope(name="Gap Dob 2", equipment_class="DOBSONIAN")
        e1 = create_event(title="G1", event_kind="MEMBER_NIGHT",
                          window_start="2026-08-15T01:00:00Z",
                          window_end="2026-08-15T05:00:00Z",
                          moon_illumination_pct=90)
        # One-hour teardown gap: 06:00 start > 05:00 end — no touch.
        e2 = create_event(title="G2", event_kind="MEMBER_NIGHT",
                          window_start="2026-08-15T06:00:00Z",
                          window_end="2026-08-15T09:00:00Z",
                          moon_illumination_pct=90)
        invite_and_accept_operator(e1["id"], member, d1)
        a2 = get_success_data(api.create_operator_assignment(
            create_operator_assignment_payload(e2["id"], member["id"], d2["id"]),
            COORDINATOR))

        accepted = validate_success(
            api.accept_assignment(a2["id"], make_member_headers(member["id"])))
        assert accepted["status"] == "CONFIRMED", (
            "A window that starts strictly after the prior end does not "
            "touch, so the accept succeeds")


class TestGroupDepositMarginalTiers:
    def test_party_of_31_pays_marginal_tiers(self, api):
        """PRD: "The deposit is tiered by party size with **marginal**
        allocation across tiers: the first 10 attendees are free (0 cents
        each); attendees 11 through 30 are charged 1000 cents each; every
        attendee beyond 30 is charged 2000 cents each. Marginal means a
        party of 31 pays 0 for the first ten plus 20000 for the next twenty
        plus 2000 for the thirty-first, totaling 22000 cents — not 62000
        cents as a flat-rate misreading would produce."

        Design: Difficulty/combinatorial_formula/group_deposit_marginal_tiers
        """
        member, _tier, _inv, _pay = create_member_with_paid_dues(
            tier=create_tier(code="FAMILY", annual_dues_cents=180000,
                             observatory_access_level=2, loan_privilege=True,
                             max_concurrent_loans=3),
            full_name="Group Lead", pay_amount=180000)
        event = create_scheduled_event(
            title="PN", window_start="2026-08-15T01:00:00Z",
            window_end="2026-08-15T05:00:00Z", moon_illumination_pct=15)
        booking = create_group_booking(event["id"], member, party_size=31,
                                       group_name="Lincoln Middle")
        assert booking["deposit_cents"] == 22000, (
            "Marginal allocation: 0*10 + 1000*20 + 2000*1 = 22000, not 62000")

    def test_party_of_10_pays_zero_deposit(self, api):
        """PRD: "the first 10 attendees are free (0 cents each)"

        Design: Difficulty/combinatorial_formula/group_deposit_marginal_tiers
        """
        member, _tier, _inv, _pay = create_member_with_paid_dues(
            tier=create_tier(code="FAMILY", annual_dues_cents=180000,
                             observatory_access_level=2, loan_privilege=True,
                             max_concurrent_loans=3),
            full_name="Free Fran", pay_amount=180000)
        event = create_scheduled_event(
            title="PN10", window_start="2026-08-16T01:00:00Z",
            window_end="2026-08-16T05:00:00Z", moon_illumination_pct=15)
        booking = create_group_booking(event["id"], member, party_size=10,
                                       group_name="Free Ten")
        assert booking["deposit_cents"] == 0, (
            "Tier 1 covers the first 10 attendees at 0 cents each")


class TestGroupCapacityBoundary:
    def test_group_capacity_exact_fill(self, api):
        """PRD: "the sum of `party_size` across the event's already-
        `CONFIRMED` bookings plus this booking's `party_size` must not
        exceed 60 attendees per event; exceeding it is rejected with
        `ERR_EVENT_GROUP_CAPACITY` (HTTP 422)."

        Design: Difficulty/boundary_precision_check/group_capacity_exact_fill
        """
        tier = create_tier(code="FAMILY", annual_dues_cents=180000,
                           observatory_access_level=2, loan_privilege=True,
                           max_concurrent_loans=3)
        m1 = create_member(tier["id"], full_name="Cap One")
        m2 = create_member(tier["id"], full_name="Cap Two")
        m3 = create_member(tier["id"], full_name="Cap Three")
        event = create_scheduled_event(
            title="PN Cap", window_start="2026-08-22T01:00:00Z",
            window_end="2026-08-22T05:00:00Z", moon_illumination_pct=5)
        b1 = create_group_booking(event["id"], m1, party_size=40, group_name="G40")
        b2 = create_group_booking(event["id"], m2, party_size=20, group_name="G20")
        b3 = create_group_booking(event["id"], m3, party_size=1, group_name="G1")
        get_success_data(api.confirm_group_booking(b1["id"], COORDINATOR))

        confirmed = validate_success(
            api.confirm_group_booking(b2["id"], COORDINATOR))
        assert confirmed["status"] == "CONFIRMED", (
            "Aggregate exactly 60 == GROUP_CAPACITY_PER_EVENT passes (<=)")

        resp = api.confirm_group_booking(b3["id"], COORDINATOR)
        validate_error(resp, ApiErrorId.ERR_EVENT_GROUP_CAPACITY)
        assert resp.status_code == 422, "61 exceeds 60: boundary is inclusive-pass at exactly 60"

    def test_group_capacity_single_booking_at_limit(self, api):
        """PRD: "the sum of `party_size` across the event's already-
        `CONFIRMED` bookings plus this booking's `party_size` must not
        exceed 60 attendees per event"

        Design: Difficulty/boundary_precision_check/group_capacity_exact_fill
        """
        tier = create_tier(code="FAMILY", annual_dues_cents=180000,
                           observatory_access_level=2, loan_privilege=True,
                           max_concurrent_loans=3)
        m1 = create_member(tier["id"], full_name="Solo Cap")
        event = create_scheduled_event(
            title="PN Solo", window_start="2026-08-23T01:00:00Z",
            window_end="2026-08-23T05:00:00Z", moon_illumination_pct=5)
        booking = create_group_booking(event["id"], m1, party_size=60,
                                       group_name="Full House")
        confirmed = validate_success(
            api.confirm_group_booking(booking["id"], COORDINATOR))
        assert confirmed["status"] == "CONFIRMED", (
            "A single booking at exactly 60 confirms")


class TestBookingConfirmEventStateDependency:
    def test_confirm_booking_after_event_completed_rejected(self, api):
        """PRD: "The `EventCoordinator` confirms it, moving `PENDING →
        CONFIRMED`, only while the host event is `SCHEDULED` or `CONFIRMED`"
        PRD: "state-machine legality — the target resource is in a state
        from which the requested transition exists, otherwise
        `ERR_INVALID_STATE`"

        Design: Difficulty/cross_entity_state_dependency/booking_confirm_depends_on_event_state
        """
        event, _asg, op, _scope = create_confirmed_event(
            title="PN XE", window_start="2026-08-12T01:00:00Z",
            window_end="2026-08-12T05:00:00Z", moon_illumination_pct=12)
        booking = create_group_booking(event["id"], op, party_size=5,
                                       group_name="Late Bookers")
        set_clock("2026-08-12T06:00:00Z")
        get_success_data(api.complete_event(event["id"], COORDINATOR))

        resp = api.confirm_group_booking(booking["id"], COORDINATOR)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert resp.status_code == 409, (
            "Host event COMPLETED — neither SCHEDULED nor CONFIRMED")

        after = validate_success(api.get_group_visit_booking(booking["id"], COORDINATOR))
        assert after["status"] == "PENDING", (
            "The rejected confirm leaves the booking PENDING")

    def test_confirm_booking_while_event_confirmed_succeeds(self, api):
        """PRD: "The `EventCoordinator` confirms it, moving `PENDING →
        CONFIRMED`, only while the host event is `SCHEDULED` or `CONFIRMED`"

        Design: Difficulty/cross_entity_state_dependency/booking_confirm_depends_on_event_state
        """
        event, _asg, op, _scope = create_confirmed_event(
            title="PN OK", window_start="2026-08-18T01:00:00Z",
            window_end="2026-08-18T05:00:00Z", moon_illumination_pct=12)
        booking = create_group_booking(event["id"], op, party_size=5,
                                       group_name="On Time")
        confirmed = validate_success(
            api.confirm_group_booking(booking["id"], COORDINATOR))
        assert confirmed["status"] == "CONFIRMED", (
            "Host CONFIRMED satisfies the event-state precondition")


class TestNoShowThrottle:
    def test_no_show_strikes_throttle(self, api):
        """PRD: "Second the no-show throttle: a contact member whose
        `no_show_strikes` has reached 2 within the rolling 365-day window
        may not create further bookings — the attempt is rejected with
        `ERR_NO_SHOW_THROTTLED` (HTTP 422)."
        PRD: "the member's no-show marks — from operator assignments marked
        `NO_SHOW` and from group bookings marked `NO_SHOW`"

        Design: Corner/calculations/no_show_strikes_throttle
        """
        member, scope, _cert = setup_member_with_cert_and_scope(
            equipment_class="DOBSONIAN", member_name="Flake Fred")

        # Strike 1: operator NO_SHOW on completed event E1.
        e1, a1, _op, _sc = create_completed_event(
            operator_member=member, operator_scope=scope,
            window_start="2026-08-03T01:00:00Z",
            window_end="2026-08-03T05:00:00Z",
            after_clock="2026-08-03T06:00:00Z",
            moon_illumination_pct=10, title="N1")
        get_success_data(api.mark_assignment_no_show(a1["id"], COORDINATOR))

        # Strike 2: operator NO_SHOW on a second completed event. (Booking
        # NO_SHOW is unreachable per PRD: completion cascades every
        # CONFIRMED booking to COMPLETED, while booking mark-no-show
        # requires a CONFIRMED booking on a COMPLETED host. Operator
        # assignments explicitly "remain CONFIRMED at completion", so the
        # assignment no-show path is the PRD-reachable strike source.)
        e2, a2, _op2, _sc2 = create_completed_event(
            operator_member=member, operator_scope=scope,
            window_start="2026-08-05T01:00:00Z",
            window_end="2026-08-05T05:00:00Z",
            after_clock="2026-08-05T06:00:00Z",
            moon_illumination_pct=10, title="N2")
        get_success_data(api.mark_assignment_no_show(a2["id"], COORDINATOR))

        strikes = validate_success(api.get_member(member["id"], OFFICER))
        assert strikes["no_show_strikes"] == 2, (
            "Two operator NO_SHOW marks inside the rolling 365-day window")

        e4 = create_scheduled_event(
            title="N3", window_start="2026-08-06T01:00:00Z",
            window_end="2026-08-06T05:00:00Z", moon_illumination_pct=10)
        resp = api.create_group_visit_booking(
            {"event_id": e4["id"], "group_name": "Blocked Group",
             "party_size": 3, "contact_member_id": member["id"]},
            make_member_headers(member["id"]))
        validate_error(resp, ApiErrorId.ERR_NO_SHOW_THROTTLED)
        assert resp.status_code == 422


class TestResignationGuard:
    def test_resignation_blocked_by_outstanding_loan(self, api):
        """PRD: "Resignation is blocked while the member holds any loan in
        `CHECKED_OUT` or `OVERDUE` status — the attempt is rejected with
        `ERR_LOANS_OUTSTANDING` (HTTP 422)."
        PRD: "A member (or a `ClubOfficer` on their behalf) may resign from
        either `ACTIVE` or `SUSPENDED`, moving to the terminal `RESIGNED`
        state."

        Design: Corner/state_machines/resignation_blocked_by_outstanding_loan
        """
        member, scope, _cert = setup_member_with_cert_and_scope(
            member_name="Resign Rex")
        loan = create_checked_out_loan(
            member, scope, "2026-08-01T00:00:00Z", "2026-08-06T00:00:00Z",
            checkout_clock="2026-08-02T12:00:00Z")

        resp = api.resign_member(member["id"], make_member_headers(member["id"]))
        validate_error(resp, ApiErrorId.ERR_LOANS_OUTSTANDING)
        assert resp.status_code == 422

        get_success_data(api.return_loan(loan["id"], CHAIR,
                                         damage_reported=False))
        resigned = validate_success(
            api.resign_member(member["id"], make_member_headers(member["id"])))
        assert resigned["status"] == "RESIGNED", (
            "After the outstanding loan is returned, resignation succeeds")
