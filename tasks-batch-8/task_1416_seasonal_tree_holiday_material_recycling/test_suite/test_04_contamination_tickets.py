"""Contamination pipeline: ticket source rules, duplicates, adjudication
branches, strike/bar cascade, appeal deadline, posture flip, immediacy."""
import pytest

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_booking,
    assert_household,
    assert_same_instant,
    assert_ticket,
    adjudicate,
    create_active_program,
    create_confirmed_booking,
    get_booking,
    get_household,
    get_program,
    get_ticket,
    get_zone,
    list_notifications,
    make_program_admin_headers,
    make_resident_headers,
    make_site_supervisor_headers,
    register_household,
    report_ticket,
    set_clock,
    validate_error,
    validate_success,
)

TICKET_CLOCK = "2027-01-05T10:00:00Z"
APPEAL_DEADLINE = "2027-01-08T10:00:00Z"  # adjudicated_at + 72h


class TestTicketCreationRules:

    def test_ticket_source_xor_enforced(self):
        """PRD section 3.4: "Supplying both, neither, or a source that does
        not belong to the named program is rejected with
        `ERR_TICKET_SOURCE_INVALID`."

        Design: Corner/validations/ticket_source_xor_enforced
        """
        ctx = create_active_program(clock=TICKET_CLOCK)
        program, site, zone = ctx["program"], ctx["site"], ctx["zone"]
        household = register_household(program["id"], zone["id"])
        booking = create_confirmed_booking(household, zone["id"])
        reporter = make_site_supervisor_headers("sup-1")

        both = api_client.create_contamination_ticket(
            {"program_id": program["id"], "booking_id": booking["id"],
             "site_id": site["id"], "category": "OTHER"}, reporter)
        validate_error(both, ApiErrorId.ERR_TICKET_SOURCE_INVALID)

        neither = api_client.create_contamination_ticket(
            {"program_id": program["id"], "category": "OTHER"}, reporter)
        validate_error(neither, ApiErrorId.ERR_TICKET_SOURCE_INVALID)

        assert get_program(program["id"])["open_ticket_count"] == 0, \
            "rejected tickets must not be persisted"

    def test_duplicate_open_ticket_rejected(self):
        """PRD section 3.4: "the system refuses to open a second `OPEN` ticket
        against the same booking or the same site with
        `ERR_DUPLICATE_TICKET`."

        Design: Corner/validations/duplicate_open_ticket_rejected
        """
        ctx = create_active_program(clock=TICKET_CLOCK)
        program, zone = ctx["program"], ctx["zone"]
        household = register_household(program["id"], zone["id"])
        booking = create_confirmed_booking(household, zone["id"])

        t1 = report_ticket(program["id"], booking_id=booking["id"],
                           category="OTHER")
        dup = api_client.create_contamination_ticket(
            {"program_id": program["id"], "booking_id": booking["id"],
             "category": "DECORATIONS"},
            make_site_supervisor_headers("sup-2"))
        validate_error(dup, ApiErrorId.ERR_DUPLICATE_TICKET)

        adjudicate(t1["id"], "DISMISSED",
                   make_program_admin_headers("admin-1"))
        t2 = report_ticket(program["id"], booking_id=booking["id"],
                           category="DECORATIONS",
                           reporter_headers=make_site_supervisor_headers(
                               "sup-2"))
        assert t2["status"] == "OPEN"
        assert get_program(program["id"])["open_ticket_count"] == 1

    def test_appeal_dismissed_ticket_returns_invalid_state(self):
        """PRD section 3.4: "The resident of the ticket's household may appeal
        an `UPHELD` ticket, moving it `UPHELD → APPEALED`."
        PRD section 3.4: "`DISMISSED`, `UPHELD_FINAL`, and `OVERTURNED` are
        the ticket's terminal states."
        PRD section 2.7: "Fifth, state legality: the target resource must be
        in a state from which the requested transition is declared, including
        terminal-state lockdown; violations surface as `ERR_INVALID_STATE`."

        Design: Corner/state_machines/appeal_dismissed_ticket_returns_invalid_state
        """
        ctx = create_active_program(clock=TICKET_CLOCK)
        program, zone = ctx["program"], ctx["zone"]
        household = register_household(program["id"], zone["id"])
        booking = create_confirmed_booking(household, zone["id"])
        t1 = report_ticket(program["id"], booking_id=booking["id"],
                           category="OTHER")
        adjudicate(t1["id"], "DISMISSED",
                   make_program_admin_headers("admin-1"))

        resp = api_client.appeal_ticket(
            t1["id"], make_resident_headers(household["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert get_ticket(t1["id"])["status"] == "DISMISSED"


class TestPostureGate:

    def test_posture_restricted_blocks_and_recovers(self):
        """PRD section 2.9: "The posture is `NORMAL` while fewer than three
        contamination tickets for the program are in `OPEN` status, and flips
        to `RESTRICTED` the moment the count of open tickets rises to three or
        more; while `RESTRICTED`, new curbside bookings and new intake events
        are rejected with `ERR_PROGRAM_RESTRICTED`. When adjudications and
        appeal resolutions bring the open-ticket count back below three, the
        posture returns to `NORMAL`."

        Design: Corner/state_machines/posture_restricted_blocks_and_recovers
        """
        ctx = create_active_program(zone_overrides={"daily_tree_capacity": 10},
                                    clock=TICKET_CLOCK)
        program, zone = ctx["program"], ctx["zone"]
        household = register_household(program["id"], zone["id"])
        b1 = create_confirmed_booking(household, zone["id"])
        b2 = create_confirmed_booking(household, zone["id"])
        b3 = create_confirmed_booking(household, zone["id"])
        reporter = make_site_supervisor_headers("sup-1")
        report_ticket(program["id"], booking_id=b1["id"],
                      category="DECORATIONS", reporter_headers=reporter)
        t2 = report_ticket(program["id"], booking_id=b2["id"],
                           category="DECORATIONS", reporter_headers=reporter)
        report_ticket(program["id"], booking_id=b3["id"],
                      category="FLOCKED_TREE", reporter_headers=reporter)

        program_after = get_program(program["id"])
        assert program_after["open_ticket_count"] == 3
        assert program_after["posture"] == "RESTRICTED"

        blocked = api_client.create_booking(
            {"household_id": household["id"], "zone_id": zone["id"],
             "tree_count": 1, "size_class": "SMALL", "prep_attestation": True},
            make_resident_headers(household["id"]))
        validate_error(blocked, ApiErrorId.ERR_PROGRAM_RESTRICTED)

        adjudicate(t2["id"], "DISMISSED",
                   make_program_admin_headers("admin-1"))
        program_recovered = get_program(program["id"])
        assert program_recovered["open_ticket_count"] == 2
        assert program_recovered["posture"] == "NORMAL"

        b4 = create_confirmed_booking(household, zone["id"])
        assert b4["status"] == "CONFIRMED"


class TestAdjudicationBranches:

    def _setup_two_tickets(self):
        """ACTIVE program; one household with bookings b1 (2 trees) and b2
        (1 tree), both CONFIRMED; OPEN tickets t1 (on b1) and t2 (on b2),
        both reported by the same supervisor; clock pinned."""
        ctx = create_active_program(zone_overrides={"daily_tree_capacity": 10},
                                    clock=TICKET_CLOCK)
        program, zone = ctx["program"], ctx["zone"]
        household = register_household(program["id"], zone["id"])
        b1 = create_confirmed_booking(household, zone["id"], tree_count=2,
                                      size_class="LARGE")
        b2 = create_confirmed_booking(household, zone["id"], tree_count=1,
                                      size_class="SMALL")
        reporter = make_site_supervisor_headers("sup-1")
        t1 = report_ticket(program["id"], booking_id=b1["id"],
                           category="STAND_ATTACHED",
                           reporter_headers=reporter)
        t2 = report_ticket(program["id"], booking_id=b2["id"],
                           category="DECORATIONS", reporter_headers=reporter)
        return ctx, household, b1, b2, t1, t2

    def test_upheld_branch_fires_strike_and_rejection(self):
        """PRD section 3.4: "A `verdict` of `UPHELD` moves the ticket `OPEN →
        UPHELD` and fires the system's deepest cascade, in order. The count
        decrement and posture recompute come first. Then the linked booking,
        if any: one still `CONFIRMED` transitions to `REJECTED_CONTAMINATED`
        and releases its route capacity by subtracting its `tree_count` from
        the zone's `reserved_trees`... Next the strike: the booking's
        household gains one strike on its `strike_count`... Finally the ticket
        records `adjudicated_by` and `adjudicated_at` from the acting user and
        the logical clock, and sets its `appeal_deadline` to seventy-two hours
        after `adjudicated_at`."

        Design: Difficulty/non_linear_state_machine/ticket_appeal_branching_divergent_effects
        """
        ctx, household, b1, b2, t1, t2 = self._setup_two_tickets()
        upheld = adjudicate(t1["id"], "UPHELD",
                            make_program_admin_headers("admin-1"))
        assert_ticket(upheld)
        assert upheld["status"] == "UPHELD"
        assert upheld["adjudicated_by"] == "admin-1"
        assert upheld["appeal_deadline"] is not None
        assert upheld["appeal_deadline"].startswith("2027-01-08T10:00"), (
            "appeal_deadline must be adjudicated_at (logical clock "
            "2027-01-05T10:00:00Z) + 72h")

        booking_after = get_booking(b1["id"])
        assert booking_after["status"] == "REJECTED_CONTAMINATED"
        household_after = get_household(household["id"])
        assert household_after["strike_count"] == 1
        assert household_after["curbside_eligible"] is True
        assert get_zone(ctx["zone"]["id"])["reserved_trees"] == 1, \
            "the rejected booking's 2 trees come off the reservation (3 - 2)"

    def test_overturned_compensation_and_dismissed_divergence(self):
        """PRD section 3.4: "A resolution of `OVERTURNED` runs the
        compensation path: the household's `strike_count` drops by one and its
        `curbside_eligible` is recomputed, but bookings auto-cancelled by the
        bar cascade are not resurrected — they stay `CANCELLED`. The one
        restoration is the directly linked booking: if it sits in
        `REJECTED_CONTAMINATED`, it returns to `CONFIRMED`, its `tree_count`
        is re-added to the zone's `reserved_trees` unconditionally — a
        documented exception to the capacity check, deliberately re-reserving
        even when the route has since filled — and its `service_date` is set
        to the zone's current `collection_date`."
        PRD section 3.4: "A `verdict` of `DISMISSED` moves the ticket `OPEN →
        DISMISSED`, subtracts one from `open_ticket_count` with the posture
        recomputed, and nothing else happens — no strike, no booking change."

        Design: Difficulty/non_linear_state_machine/ticket_appeal_branching_divergent_effects
        """
        ctx, household, b1, b2, t1, t2 = self._setup_two_tickets()
        zone = ctx["zone"]
        adjudicate(t1["id"], "UPHELD", make_program_admin_headers("admin-1"))
        assert get_booking(b1["id"])["status"] == "REJECTED_CONTAMINATED"

        appeal = api_client.appeal_ticket(
            t1["id"], make_resident_headers(household["id"]))
        assert validate_success(appeal, 200)["status"] == "APPEALED"

        # Resolver must differ from the adjudicator (admin-1).
        resp = api_client.resolve_appeal(
            t1["id"], {"resolution": "OVERTURNED"},
            make_program_admin_headers("admin-2"))
        resolved = validate_success(resp, 200)
        assert resolved["status"] == "OVERTURNED"

        household_after = get_household(household["id"])
        assert household_after["strike_count"] == 0
        assert household_after["curbside_eligible"] is True
        restored = get_booking(b1["id"])
        assert restored["status"] == "CONFIRMED"
        assert_same_instant(restored["service_date"], "2027-01-09T00:00:00Z")
        assert get_zone(zone["id"])["reserved_trees"] == 3, \
            "restoration re-reserves the 2 trees unconditionally (1 + 2)"

        # The divergent DISMISSED branch fires nothing beyond the decrement.
        dismissed = adjudicate(t2["id"], "DISMISSED",
                               make_program_admin_headers("admin-1"))
        assert dismissed["status"] == "DISMISSED"
        assert get_booking(b2["id"])["status"] == "CONFIRMED"
        assert get_household(household["id"])["strike_count"] == 0


class TestBarCascade:

    def _setup_three_bookings_two_tickets(self):
        """One household with bookings b_a (2), b_b (1), b_c (1) — all
        CONFIRMED, reserved 4 — and OPEN tickets on b_a and b_c."""
        ctx = create_active_program(zone_overrides={"daily_tree_capacity": 10},
                                    clock=TICKET_CLOCK)
        program, zone = ctx["program"], ctx["zone"]
        household = register_household(program["id"], zone["id"])
        b_a = create_confirmed_booking(household, zone["id"], tree_count=2,
                                       size_class="LARGE")
        b_b = create_confirmed_booking(household, zone["id"], tree_count=1,
                                       size_class="SMALL")
        b_c = create_confirmed_booking(household, zone["id"], tree_count=1,
                                       size_class="MEDIUM")
        reporter = make_site_supervisor_headers("sup-1")
        t1 = report_ticket(program["id"], booking_id=b_a["id"],
                           category="FLOCKED_TREE", reporter_headers=reporter)
        t2 = report_ticket(program["id"], booking_id=b_c["id"],
                           category="DECORATIONS", reporter_headers=reporter)
        return ctx, household, b_a, b_b, b_c, t1, t2

    def test_second_strike_bars_household_and_cancels_bookings(self):
        """PRD section 3.4: "At the moment the count reaches two,
        `curbside_eligible` flips to false — exactly two strikes is already
        barred — and the bar cascades: every other `CONFIRMED` booking
        belonging to the household is automatically cancelled (`CONFIRMED →
        CANCELLED`, releasing its reserved capacity as any cancellation would)
        and one `BOOKING_AUTO_CANCELLED` notification is written per cancelled
        booking."

        Design: Difficulty/transitive_cascade/adjudication_bar_cascade
        """
        (ctx, household, b_a, b_b, b_c, t1, t2) = \
            self._setup_three_bookings_two_tickets()
        admin = make_program_admin_headers("admin-1")
        adjudicate(t1["id"], "UPHELD", admin)
        adjudicate(t2["id"], "UPHELD", admin)

        household_after = get_household(household["id"])
        assert_household(household_after)
        assert household_after["strike_count"] == 2
        assert household_after["curbside_eligible"] is False

        assert get_booking(b_a["id"])["status"] == "REJECTED_CONTAMINATED"
        assert get_booking(b_c["id"])["status"] == "REJECTED_CONTAMINATED"
        b_b_after = get_booking(b_b["id"])
        assert_booking(b_b_after)
        assert b_b_after["status"] == "CANCELLED", \
            "the never-ticketed booking must be auto-cancelled by the bar"

        zone_after = get_zone(ctx["zone"]["id"])
        assert zone_after["reserved_trees"] == 0, "all 4 trees released"

        entries = list_notifications(
            ctx["program"]["id"],
            params={"kind": "BOOKING_AUTO_CANCELLED"})
        if isinstance(entries, dict) and "data" in entries:
            entries = entries["data"]
        matching = [e for e in entries
                    if e["kind"] == "BOOKING_AUTO_CANCELLED"
                    and e.get("household_id") == household["id"]]
        assert len(matching) >= 1, \
            "one BOOKING_AUTO_CANCELLED notice per cancelled booking"

    def test_barred_household_new_booking_rejected(self):
        """PRD section 3.2: "the household must still be curbside-eligible
        (`ERR_HOUSEHOLD_BARRED` once barred)".

        Design: Difficulty/transitive_cascade/adjudication_bar_cascade
        """
        (ctx, household, b_a, b_b, b_c, t1, t2) = \
            self._setup_three_bookings_two_tickets()
        admin = make_program_admin_headers("admin-1")
        adjudicate(t1["id"], "UPHELD", admin)
        adjudicate(t2["id"], "UPHELD", admin)
        assert get_household(household["id"])["curbside_eligible"] is False

        resp = api_client.create_booking(
            {"household_id": household["id"], "zone_id": ctx["zone"]["id"],
             "tree_count": 1, "size_class": "SMALL", "prep_attestation": True},
            make_resident_headers(household["id"]))
        validate_error(resp, ApiErrorId.ERR_HOUSEHOLD_BARRED)


class TestAppealDeadlineBoundary:

    def _setup_two_upheld_tickets(self):
        """Household with two bookings, both tickets UPHELD at the pinned
        clock (2027-01-05T10:00:00Z), so the appeal deadline is
        2027-01-08T10:00:00Z for each."""
        ctx = create_active_program(zone_overrides={"daily_tree_capacity": 10},
                                    clock=TICKET_CLOCK)
        program, zone = ctx["program"], ctx["zone"]
        household = register_household(program["id"], zone["id"])
        b1 = create_confirmed_booking(household, zone["id"], tree_count=1,
                                      size_class="SMALL")
        b2 = create_confirmed_booking(household, zone["id"], tree_count=1,
                                      size_class="MEDIUM")
        reporter = make_site_supervisor_headers("sup-1")
        t1 = report_ticket(program["id"], booking_id=b1["id"],
                           category="DECORATIONS", reporter_headers=reporter)
        t2 = report_ticket(program["id"], booking_id=b2["id"],
                           category="FLOCKED_TREE", reporter_headers=reporter)
        admin = make_program_admin_headers("admin-1")
        adjudicate(t1["id"], "UPHELD", admin)
        adjudicate(t2["id"], "UPHELD", admin)
        return ctx, household, t1, t2

    def test_appeal_at_exactly_72h_deadline_admitted(self):
        """PRD section 3.4: "only while the clock has not passed the
        `appeal_deadline`; the boundary is inclusive, and a later appeal is
        rejected with `ERR_APPEAL_WINDOW_EXPIRED`."
        PRD section 3.4: "sets its `appeal_deadline` to seventy-two hours
        after `adjudicated_at`".

        Design: Difficulty/boundary_precision_check/appeal_deadline_exact_72h
        """
        ctx, household, t1, t2 = self._setup_two_upheld_tickets()
        assert get_ticket(t1["id"])["appeal_deadline"].startswith(
            "2027-01-08T10:00"), "deadline is adjudicated_at + 72h"

        set_clock(APPEAL_DEADLINE)
        resp = api_client.appeal_ticket(
            t1["id"], make_resident_headers(household["id"]))
        appealed = validate_success(resp, 200)
        assert appealed["status"] == "APPEALED", \
            "an appeal at exactly adjudicated_at + 72h is inclusive-admitted"

    def test_appeal_one_second_past_deadline_rejected(self):
        """PRD section 3.4: "only while the clock has not passed the
        `appeal_deadline`; the boundary is inclusive, and a later appeal is
        rejected with `ERR_APPEAL_WINDOW_EXPIRED`."

        Design: Difficulty/boundary_precision_check/appeal_deadline_exact_72h
        """
        ctx, household, t1, t2 = self._setup_two_upheld_tickets()

        set_clock("2027-01-08T10:00:01Z")  # one second past the deadline
        resp = api_client.appeal_ticket(
            t2["id"], make_resident_headers(household["id"]))
        validate_error(resp, ApiErrorId.ERR_APPEAL_WINDOW_EXPIRED)
        assert get_ticket(t2["id"])["status"] == "UPHELD"


class TestImmediateConsistency:

    def test_immediate_visibility_of_adjudication_cascade(self):
        """PRD section 2.9: "Many fields in this system are computed rather
        than stored from input, and consistency is immediate: whenever an
        event changes the inputs to a derived field, the derived value is
        recomputed as part of the same operation."

        Design: Corner/consistency_model/immediate_visibility_of_adjudication_cascade
        """
        ctx = create_active_program(zone_overrides={"daily_tree_capacity": 5},
                                    clock=TICKET_CLOCK)
        program, zone = ctx["program"], ctx["zone"]
        household = register_household(program["id"], zone["id"])
        booking = create_confirmed_booking(household, zone["id"],
                                           tree_count=2, size_class="MEDIUM")
        t1 = report_ticket(program["id"], booking_id=booking["id"],
                           category="DECORATIONS")

        adjudicate(t1["id"], "UPHELD", make_program_admin_headers("admin-1"))

        # The very next reads reflect every hop of the cascade.
        assert get_booking(booking["id"])["status"] == \
            "REJECTED_CONTAMINATED"
        household_after = get_household(household["id"])
        assert household_after["strike_count"] == 1
        assert household_after["curbside_eligible"] is True  # 1 < 2
        program_after = get_program(program["id"])
        assert program_after["open_ticket_count"] == 0
        assert program_after["posture"] == "NORMAL"
