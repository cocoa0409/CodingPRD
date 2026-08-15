"""Events, venues, and RSVPs: creation gates, half-open venue overlap,
parallel status dimensions, participation metrics, impact points, waitlist
promotion, timing gates, and event OCC."""
import pytest

from test_helpers import (
    ApiErrorId,
    advance_clock,
    check_in,
    create_active_group,
    create_event,
    create_funding_request,
    create_group_draft,
    create_leader_term,
    create_open_program,
    create_rsvp_payload,
    create_sponsor,
    create_venue,
    lock_allocation,
    make_employee_headers,
    make_group_leader_headers,
    publish_event,
    reschedule_event_payload,
    rsvp,
    rsvp_many,
    setup_active_group_with_leader,
    setup_approved_request,
    setup_locked_group_with_leader,
    setup_published_event,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import DEI_HEADERS, add_members, assign_sponsor_to_group

EVENT_START = "2026-08-10T10:00:00Z"
EVENT_END = "2026-08-10T12:00:00Z"


def _active_group_with_event(api, sponsor_employee_id, creator_id, event_capacity=40,
                             event_category="WORKSHOP", venue_capacity=100,
                             group_name="Group", venue_name="Main Hall",
                             funding_request_id=None):
    """Program OPEN + ACTIVE group (10 members) + venue + PUBLISHED event."""
    program = create_open_program(100000)
    sponsor = create_sponsor(sponsor_employee_id, max_groups=3, max_mentees=2)
    group = create_active_group(program["id"], sponsor["id"], group_name, "AFFINITY",
                                creator_id)
    venue = create_venue(venue_name, venue_capacity)
    event = setup_published_event(
        group["id"], venue["id"], title="Kickoff", category=event_category,
        starts_at=EVENT_START, ends_at=EVENT_END, capacity=event_capacity,
        funding_request_id=funding_request_id,
    )
    return program, sponsor, group, venue, event


class TestEventCreationGates:
    def test_event_create_requires_active_group_draft(self, api):
        """PRD §3.7: "An `ACTIVE` group plans events through its current `ACTIVE`-term leader or a `DeiAdmin` (any other caller is `ERR_NOT_GROUP_LEADER`; a non-active group is `ERR_GROUP_NOT_ACTIVE`)."

        Design: Difficulty/cross_entity_state_dependency/event_create_requires_active_group
        """
        program = create_open_program(100000)
        sponsor = create_sponsor("emp_sp14", max_groups=3, max_mentees=2)
        # Group never leaves CHARTER_DRAFT (charter never submitted).
        group = create_group_draft(program["id"], "Draft Group", "AFFINITY", "emp_l14")
        add_members(group["id"], [f"emp_f{i:02d}" for i in range(1, 11)])
        assign_sponsor_to_group(group, sponsor["id"])
        venue = create_venue("Annex", 40)

        resp = api.create_event(
            {
                "group_id": group["id"], "venue_id": venue["id"], "title": "Premature",
                "category": "SOCIAL", "starts_at": EVENT_START, "ends_at": EVENT_END,
                "capacity": 20,
            },
            DEI_HEADERS,
        )
        validate_error(resp, ApiErrorId.ERR_GROUP_NOT_ACTIVE.value, 409)

    def test_event_create_requires_active_group_suspended(self, api):
        """PRD §3.7: "An `ACTIVE` group plans events through its current `ACTIVE`-term leader or a `DeiAdmin` (any other caller is `ERR_NOT_GROUP_LEADER`; a non-active group is `ERR_GROUP_NOT_ACTIVE`)."

        Design: Difficulty/cross_entity_state_dependency/event_create_requires_active_group
        """
        program = create_open_program(100000)
        sponsor = create_sponsor("emp_sp14", max_groups=3, max_mentees=2)
        group = create_active_group(
            program["id"], sponsor["id"], "Draft Group", "AFFINITY", "emp_l14"
        )
        venue = create_venue("Annex", 40)
        validate_success(
            api.set_group_status(group["id"], {"to_status": "SUSPENDED"}, DEI_HEADERS), 200
        )
        resp = api.create_event(
            {
                "group_id": group["id"], "venue_id": venue["id"], "title": "Premature",
                "category": "SOCIAL", "starts_at": EVENT_START, "ends_at": EVENT_END,
                "capacity": 20,
            },
            DEI_HEADERS,
        )
        validate_error(resp, ApiErrorId.ERR_GROUP_NOT_ACTIVE.value, 409)

    def test_event_venue_capacity_and_cross_group_funding_rejected(self, api):
        """PRD §3.7: "The plan carries the `group_id`, a `venue_id`, a `title`, a `category` of `WORKSHOP`, `SOCIAL`, `RECRUITING`, or `COMMUNITY`, a `starts_at` that must be strictly after the current logical time and an `ends_at` strictly after `starts_at` (violations are `ERR_INVALID_REQUEST`), and a `capacity` that must be strictly positive and no greater than the venue's `capacity` (`ERR_VENUE_CAPACITY_EXCEEDED`)."
        PRD §3.7: "Optionally the plan links a `funding_request_id`; when supplied, that request must belong to the same group (`ERR_FUNDING_REQUEST_WRONG_GROUP`) and must be in `APPROVED` status (`ERR_FUNDING_REQUEST_NOT_APPROVED`)."

        Design: Corner/validations/event_venue_capacity_and_cross_group_funding_rejected
        """
        program = create_open_program(500000)
        sponsor = create_sponsor("emp_sp37", max_groups=3, max_mentees=2)
        group_a = create_active_group(
            program["id"], sponsor["id"], "Cross A", "AFFINITY", "emp_l54"
        )
        group_b = create_active_group(
            program["id"], sponsor["id"], "Cross B", "AFFINITY", "emp_l55",
            member_ids=[f"emp_g{i:02d}" for i in range(1, 11)],
        )
        advance_clock("2026-11-01T00:00:00Z")
        create_leader_term(group_a["id"], "emp_f01")
        create_leader_term(group_b["id"], "emp_g01")
        lock_allocation(program["id"])
        request_b = setup_approved_request(
            group_b["id"], sponsor["id"], "emp_g01",
            category="EVENT", purpose="B's money", requested_cents=100000,
            external_matching_cents=0,
        )
        venue = create_venue("Tiny", 10)

        # Capacity ceiling: 50 seats in a 10-seat venue.
        resp = api.create_event(
            {
                "group_id": group_a["id"], "venue_id": venue["id"], "title": "Too Big",
                "category": "SOCIAL", "starts_at": "2026-11-10T10:00:00Z",
                "ends_at": "2026-11-10T12:00:00Z", "capacity": 50,
            },
            DEI_HEADERS,
        )
        validate_error(resp, ApiErrorId.ERR_VENUE_CAPACITY_EXCEEDED.value, 409)

        # Cross-group funding link: B's APPROVED request cannot fund A's event.
        resp = api.create_event(
            {
                "group_id": group_a["id"], "venue_id": venue["id"], "title": "Wrong Money",
                "category": "SOCIAL", "starts_at": "2026-11-10T10:00:00Z",
                "ends_at": "2026-11-10T12:00:00Z", "capacity": 5,
                "funding_request_id": request_b["id"],
            },
            DEI_HEADERS,
        )
        validate_error(resp, ApiErrorId.ERR_FUNDING_REQUEST_WRONG_GROUP.value, 409)

    def test_referential_beats_temporal_on_event_create(self, api):
        """PRD §2.6: "Every request passes through the same ordered validation pipeline, and when several checks could fail the earliest one determines the error surfaced."
        PRD §2.6: "7. **Cross-referential integrity** — sponsor assignment matches, charter has a sponsor, event funding request belongs to the same group and is `APPROVED`, predecessor chain integrity (409 family)."
        PRD §2.6: "8. **Temporal rules** — venue overlap, mentoring buffered windows, survey response windows, check-in and completion gates, single active term (409 family)."

        Design: Difficulty/priority_pair_validation_conflict/referential_beats_temporal_on_event_create
        """
        program = create_open_program(100000)
        sponsor = create_sponsor("emp_sp12", max_groups=3, max_mentees=2)
        group, term = setup_active_group_with_leader(
            program["id"], sponsor["id"], "Prio Two", "AFFINITY", "emp_l12", "emp_f01"
        )
        request = create_funding_request(
            group["id"], "emp_f01", "EVENT", "Will be declined", 50000, 0
        )
        validate_success(
            api.funding_dei_decision(request["id"], {"decision": "DECLINE"}, DEI_HEADERS), 200
        )
        venue = create_venue("Hall V", 100)
        # Existing booking 10:00-12:00 makes the trigger slot a venue overlap too.
        create_event(group["id"], venue["id"], "Existing", "SOCIAL",
                     "2026-11-10T10:00:00Z", "2026-11-10T12:00:00Z", 20)

        resp = api.create_event(
            {
                "group_id": group["id"], "venue_id": venue["id"], "title": "Conflicting",
                "category": "WORKSHOP", "starts_at": "2026-11-10T11:00:00Z",
                "ends_at": "2026-11-10T13:00:00Z", "capacity": 20,
                "funding_request_id": request["id"],
            },
            DEI_HEADERS,
        )
        error_data = validate_error(resp, ApiErrorId.ERR_FUNDING_REQUEST_NOT_APPROVED.value, 409)
        assert error_data["error_id"] != ApiErrorId.ERR_VENUE_DOUBLE_BOOKED.value

    def test_not_approved_funding_rejected_without_venue_conflict(self, api):
        """PRD §3.7: "Optionally the plan links a `funding_request_id`; when supplied, that request must belong to the same group (`ERR_FUNDING_REQUEST_WRONG_GROUP`) and must be in `APPROVED` status (`ERR_FUNDING_REQUEST_NOT_APPROVED`)."

        Design: Difficulty/priority_pair_validation_conflict/referential_beats_temporal_on_event_create
        """
        program = create_open_program(100000)
        sponsor = create_sponsor("emp_sp12", max_groups=3, max_mentees=2)
        group, term = setup_active_group_with_leader(
            program["id"], sponsor["id"], "Prio Two", "AFFINITY", "emp_l12", "emp_f01"
        )
        request = create_funding_request(
            group["id"], "emp_f01", "EVENT", "Will be declined", 50000, 0
        )
        validate_success(
            api.funding_dei_decision(request["id"], {"decision": "DECLINE"}, DEI_HEADERS), 200
        )
        venue = create_venue("Hall V", 100)
        create_event(group["id"], venue["id"], "Existing", "SOCIAL",
                     "2026-11-10T10:00:00Z", "2026-11-10T12:00:00Z", 20)

        # Isolation: a non-overlapping slot still fails the funding-state gate.
        resp = api.create_event(
            {
                "group_id": group["id"], "venue_id": venue["id"], "title": "Clean Slot",
                "category": "WORKSHOP", "starts_at": "2026-11-12T10:00:00Z",
                "ends_at": "2026-11-12T12:00:00Z", "capacity": 20,
                "funding_request_id": request["id"],
            },
            DEI_HEADERS,
        )
        validate_error(resp, ApiErrorId.ERR_FUNDING_REQUEST_NOT_APPROVED.value, 409)


class TestVenueOverlap:
    def test_touching_endpoints_do_not_conflict(self, api):
        """PRD §3.7: "Venue exclusivity uses half-open interval semantics: the venue must have no other event in `PLANNED` or `PUBLISHED` status whose time range overlaps the new event's, where two events conflict exactly when the new event starts before the existing one ends and the existing one starts before the new one ends; touching endpoints — one event ending exactly when the other starts — do not conflict."

        Design: Difficulty/resource_temporal_overlap/venue_half_open_adjacency
        """
        program = create_open_program(100000)
        sponsor = create_sponsor("emp_sp16", max_groups=3, max_mentees=2)
        group = create_active_group(
            program["id"], sponsor["id"], "Schedulers", "AFFINITY", "emp_l16"
        )
        venue = create_venue("Hall H", 100)
        create_event(group["id"], venue["id"], "Morning Slot", "WORKSHOP",
                     EVENT_START, EVENT_END, 20)

        # Adjacent: starts exactly when the existing event ends.
        resp = api.create_event(
            {
                "group_id": group["id"], "venue_id": venue["id"], "title": "Adjacent Slot",
                "category": "SOCIAL", "starts_at": "2026-08-10T12:00:00Z",
                "ends_at": "2026-08-10T14:00:00Z", "capacity": 20,
            },
            DEI_HEADERS,
        )
        data = validate_success(resp, 201)
        assert data["id"]

    def test_overlapping_event_rejected(self, api):
        """PRD §3.7: "An overlap is rejected with `ERR_VENUE_DOUBLE_BOOKED`."

        Design: Difficulty/resource_temporal_overlap/venue_half_open_adjacency
        """
        program = create_open_program(100000)
        sponsor = create_sponsor("emp_sp16", max_groups=3, max_mentees=2)
        group = create_active_group(
            program["id"], sponsor["id"], "Schedulers", "AFFINITY", "emp_l16"
        )
        venue = create_venue("Hall H", 100)
        create_event(group["id"], venue["id"], "Morning Slot", "WORKSHOP",
                     EVENT_START, EVENT_END, 20)

        # 11:00-13:00 overlaps the existing 10:00-12:00 booking by an hour.
        resp = api.create_event(
            {
                "group_id": group["id"], "venue_id": venue["id"], "title": "Overlapping Slot",
                "category": "SOCIAL", "starts_at": "2026-08-10T11:00:00Z",
                "ends_at": "2026-08-10T13:00:00Z", "capacity": 20,
            },
            DEI_HEADERS,
        )
        validate_error(resp, ApiErrorId.ERR_VENUE_DOUBLE_BOOKED.value, 409)


class TestEventLifecycleGates:
    def test_publish_on_cancelled_event_rejected(self, api):
        """PRD §3.7: "Publishing moves an event `PLANNED` → `PUBLISHED` and re-checks that the group is still `ACTIVE` (`ERR_GROUP_NOT_ACTIVE`), incrementing the event's `version` by 1."
        PRD §3.7: "Cancellation — by the leader, a `DeiAdmin`, or the system cascade from suspension or dissolution — moves an event from `PLANNED` or `PUBLISHED` to the terminal `CANCELLED` state."

        Design: Corner/state_machines/publish_on_cancelled_event_rejected
        """
        program, sponsor, group, venue, event = _active_group_with_event(
            api, "emp_sp21", "emp_l27", event_capacity=10, event_category="SOCIAL",
            venue_capacity=30, group_name="Cancel Publish", venue_name="Room Q"
        )
        validate_success(api.cancel_event(event["id"], DEI_HEADERS), 200)
        resp = api.publish_event(event["id"], DEI_HEADERS)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION.value, 409)

    def test_occ_stale_event_version_on_reschedule(self, api):
        """PRD §2.7: "Event rescheduling requires a non-optional `expected_event_version` carrying the client's last observed `version` of that `ErgEvent`. If the event's version has advanced since the client last read it, the reschedule is rejected with `ERR_STALE_EVENT_VERSION` (HTTP 412)."
        PRD §2.7: "A reschedule legitimately supersedes the prior schedule while the event is `PLANNED` or `PUBLISHED`, so again the guard is purely a version check: a second reschedule carrying the previously observed version must fail."

        Design: Corner/cross_cutting_layers/occ_stale_event_version_on_reschedule
        """
        program = create_open_program(100000)
        sponsor = create_sponsor("emp_sp41", max_groups=3, max_mentees=2)
        group = create_active_group(
            program["id"], sponsor["id"], "OCC Events", "AFFINITY", "emp_l62"
        )
        venue = create_venue("OCC Hall", 30)
        event = create_event(group["id"], venue["id"], "Slide Me", "SOCIAL",
                             EVENT_START, EVENT_END, 10)
        observed_version = event["version"]

        resp = api.reschedule_event(
            event["id"],
            reschedule_event_payload("2026-08-11T10:00:00Z", "2026-08-11T12:00:00Z",
                                     observed_version),
            DEI_HEADERS,
        )
        data = validate_success(resp, 200)
        assert data["version"] == observed_version + 1
        assert data["starts_at"].startswith("2026-08-11T10:00:00")

        resp = api.reschedule_event(
            event["id"],
            reschedule_event_payload("2026-08-12T10:00:00Z", "2026-08-12T12:00:00Z",
                                     observed_version),
            DEI_HEADERS,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_EVENT_VERSION.value, 412)


class TestParallelStatusDimensions:
    def test_cancel_moves_status_and_funding_status_independently(self, api):
        """PRD §3.7: "A new event starts in `PLANNED` status with `funding_status` `RESERVED` when an approved funding request was linked, otherwise `UNFUNDED`, and with `registered_count` and `checked_in_count` both zero."
        PRD §3.7: "Every RSVP of the event in `REGISTERED`, `WAITLISTED`, or `CHECKED_IN` flips to `CANCELLED` with no waitlist promotion, and a `RESERVED` `funding_status` flips to `RELEASED` (`UNFUNDED` is unchanged)."

        Design: Difficulty/non_linear_state_machine/event_parallel_status_dimensions
        """
        program = create_open_program(500000)
        sponsor = create_sponsor("emp_sp8", max_groups=3, max_mentees=2)
        group, term = setup_locked_group_with_leader(
            program["id"], sponsor["id"], "Parallel Events", "AFFINITY", "emp_l8", "emp_f01"
        )
        request = setup_approved_request(
            group["id"], sponsor["id"], "emp_f01",
            category="EVENT", purpose="Funded social", requested_cents=300000,
            external_matching_cents=0,
        )
        venue = create_venue("Loft", 50)
        event = create_event(group["id"], venue["id"], "Funded Social", "SOCIAL",
                             "2026-11-10T10:00:00Z", "2026-11-10T12:00:00Z", 30,
                             funding_request_id=request["id"])
        assert event["funding_status"] == "RESERVED", "linked APPROVED request reserves at creation"

        data = validate_success(api.cancel_event(event["id"], DEI_HEADERS), 200)
        assert data["status"] == "CANCELLED"
        assert data["funding_status"] == "RELEASED", "both axes moved by the cancel"

    def test_event_cancel_leaves_funding_reservation_intact(self, api):
        """PRD §2.10: "Four operations move money between these buckets and are detailed in §3.4 and §3.5: approval moves funds from available to reserved; disbursement moves them from reserved to spent; reconciliation refunds the unspent remainder by reducing spent and allocated and returning the refund to the program's `unallocated_pool_cents`; dissolution of a group with `APPROVED`-but-undisbursed requests releases the reserve back to available-in-name-only by subtracting `approved_cents` from `reserved_cents`."

        Design: Difficulty/non_linear_state_machine/event_parallel_status_dimensions
        """
        program = create_open_program(500000)
        sponsor = create_sponsor("emp_sp8", max_groups=3, max_mentees=2)
        group, term = setup_locked_group_with_leader(
            program["id"], sponsor["id"], "Parallel Events", "AFFINITY", "emp_l8", "emp_f01"
        )
        request = setup_approved_request(
            group["id"], sponsor["id"], "emp_f01",
            category="EVENT", purpose="Funded social", requested_cents=300000,
            external_matching_cents=0,
        )
        venue = create_venue("Loft", 50)
        event = create_event(group["id"], venue["id"], "Funded Social", "SOCIAL",
                             "2026-11-10T10:00:00Z", "2026-11-10T12:00:00Z", 30,
                             funding_request_id=request["id"])
        validate_success(api.cancel_event(event["id"], DEI_HEADERS), 200)

        request_data = validate_success(
            api.get_funding_request(request["id"], DEI_HEADERS), 200
        )
        assert request_data["status"] == "APPROVED", "event cancel does not touch the request"
        group_data = validate_success(api.get_group(group["id"], DEI_HEADERS), 200)
        assert group_data["reserved_cents"] == 300000, (
            "reservation survives event cancellation (no ledger operation ran)"
        )


class TestRsvpAndWaitlist:
    def test_rsvp_requires_published_and_no_duplicates(self, api):
        """PRD §3.7: "Employees RSVP to a `PUBLISHED` event (any other status is `ERR_EVENT_NOT_PUBLISHED`) with a payload naming the `event_id`; the server records the caller's `X-User-ID` as the RSVP's `employee_id`."
        PRD §3.7: "One live RSVP per (event, employee) pair is allowed: an existing RSVP in `REGISTERED`, `WAITLISTED`, or `CHECKED_IN` blocks a new one with `ERR_ALREADY_RSVPED`."

        Design: Corner/validations/rsvp_requires_published_and_no_duplicates
        """
        program = create_open_program(100000)
        sponsor = create_sponsor("emp_sp33", max_groups=3, max_mentees=2)
        group = create_active_group(
            program["id"], sponsor["id"], "RSVP Gates", "AFFINITY", "emp_l50"
        )
        venue = create_venue("RSVP Hall", 20)
        event = create_event(group["id"], venue["id"], "Gated", "SOCIAL",
                             EVENT_START, EVENT_END, 5)

        resp = api.create_rsvp(create_rsvp_payload(event["id"]), make_employee_headers("emp_e1"))
        validate_error(resp, ApiErrorId.ERR_EVENT_NOT_PUBLISHED.value, 409)

        publish_event(event["id"])
        resp = api.create_rsvp(create_rsvp_payload(event["id"]), make_employee_headers("emp_e1"))
        data = validate_success(resp, 201)
        assert data["status"] == "REGISTERED"

        resp = api.create_rsvp(create_rsvp_payload(event["id"]), make_employee_headers("emp_e1"))
        validate_error(resp, ApiErrorId.ERR_ALREADY_RSVPED.value, 409)

    def test_full_event_waitlists_with_positions(self, api):
        """PRD §3.7: "When the event's `registered_count` is strictly below its `capacity` the new RSVP lands `REGISTERED` and `registered_count` rises by 1; when `registered_count` has reached `capacity` — the boundary is inclusive, a full event waitlists — the RSVP lands `WAITLISTED` and receives a `waitlist_position` equal to 1 plus the highest existing `waitlist_position` on the event (or 1 when none exists)."

        Design: Difficulty/compensating_invariant/rsvp_cancel_promotes_waitlist_head
        """
        program, sponsor, group, venue, event = _active_group_with_event(
            api, "emp_sp18", "emp_l19", event_capacity=1, event_category="WORKSHOP",
            venue_capacity=10, group_name="Promoters", venue_name="Studio"
        )
        r_a = rsvp(event["id"], "emp_a")
        r_b = rsvp(event["id"], "emp_b")
        r_c = rsvp(event["id"], "emp_c")
        assert r_a["status"] == "REGISTERED", "first RSVP takes the single seat"
        assert r_b["status"] == "WAITLISTED" and r_b["waitlist_position"] == 1
        assert r_c["status"] == "WAITLISTED" and r_c["waitlist_position"] == 2

    def test_cancel_promotes_waitlist_head_and_conserves_seats(self, api):
        """PRD §3.7: "Cancelling a `REGISTERED` row manually decrements `registered_count` by 1 and immediately promotes the waitlist: the `WAITLISTED` RSVP with the lowest `waitlist_position` flips to `REGISTERED` and `registered_count` rises back by 1, leaving the count unchanged overall; if no one is waiting, the seat simply stays free."

        Design: Difficulty/compensating_invariant/rsvp_cancel_promotes_waitlist_head
        """
        program, sponsor, group, venue, event = _active_group_with_event(
            api, "emp_sp18", "emp_l19", event_capacity=1, event_category="WORKSHOP",
            venue_capacity=10, group_name="Promoters", venue_name="Studio"
        )
        r_a = rsvp(event["id"], "emp_a")
        r_b = rsvp(event["id"], "emp_b")
        r_c = rsvp(event["id"], "emp_c")

        validate_success(api.cancel_rsvp(r_a["id"], make_employee_headers("emp_a")), 200)

        data_b = validate_success(api.get_rsvp(r_b["id"], DEI_HEADERS), 200)
        assert data_b["status"] == "REGISTERED", "waitlist head promoted"
        data_c = validate_success(api.get_rsvp(r_c["id"], DEI_HEADERS), 200)
        assert data_c["status"] == "WAITLISTED"
        event_data = validate_success(api.get_event(event["id"], DEI_HEADERS), 200)
        assert event_data["registered_count"] == 1, "seat conserved: -1 cancel, +1 promote"

    def test_cancel_with_empty_waitlist_frees_seat(self, api):
        """PRD §3.7: "Cancelling a `REGISTERED` row manually decrements `registered_count` by 1 and immediately promotes the waitlist: the `WAITLISTED` RSVP with the lowest `waitlist_position` flips to `REGISTERED` and `registered_count` rises back by 1, leaving the count unchanged overall; if no one is waiting, the seat simply stays free."

        Design: Corner/calculations/waitlist_empty_pool_no_promotion
        """
        program, sponsor, group, venue, event = _active_group_with_event(
            api, "emp_sp26", "emp_l36", event_capacity=2, event_category="SOCIAL",
            venue_capacity=50, group_name="Empty Pool", venue_name="Wide Room"
        )
        r_solo = rsvp(event["id"], "emp_solo")
        validate_success(api.cancel_rsvp(r_solo["id"], make_employee_headers("emp_solo")), 200)
        event_data = validate_success(api.get_event(event["id"], DEI_HEADERS), 200)
        assert event_data["registered_count"] == 0, "no waitlist head to promote; seat stays free"


class TestEventTiming:
    def test_event_timing_gates(self, api):
        """PRD §3.7: "The event must still be `PUBLISHED` and the current logical time must be at or after the event's `starts_at` (early check-in is `ERR_CHECKIN_TOO_EARLY`); checking in a non-`REGISTERED` RSVP is `ERR_INVALID_STATE_TRANSITION`."
        PRD §3.7: "Once the current logical time reaches the event's `ends_at` (completing earlier is `ERR_EVENT_NOT_ENDED`), the leader or a `DeiAdmin` completes the event, moving `PUBLISHED` → `COMPLETED`."

        Design: Corner/validations/event_timing_gates
        """
        program, sponsor, group, venue, event = _active_group_with_event(
            api, "emp_sp32", "emp_l49", event_capacity=5, event_category="SOCIAL",
            venue_capacity=20, group_name="Timing", venue_name="Timing Hall"
        )
        r1 = rsvp(event["id"], "emp_e1")

        # Default clock 2026-08-01 is before the 2026-08-10T10:00 start.
        resp = api.check_in_rsvp(r1["id"], DEI_HEADERS)
        validate_error(resp, ApiErrorId.ERR_CHECKIN_TOO_EARLY.value, 409)

        advance_clock("2026-08-10T10:30:00Z")
        data = validate_success(api.check_in_rsvp(r1["id"], DEI_HEADERS), 200)
        assert data["status"] == "CHECKED_IN"

        # 10:30 is before the 12:00 end: completion is rejected.
        resp = api.complete_event(event["id"], DEI_HEADERS)
        validate_error(resp, ApiErrorId.ERR_EVENT_NOT_ENDED.value, 409)

        # At exactly ends_at the clock has reached the end: completion succeeds.
        advance_clock(EVENT_END)
        data = validate_success(api.complete_event(event["id"], DEI_HEADERS), 200)
        assert data["status"] == "COMPLETED"


class TestCompletionMetrics:
    def test_completion_freezes_dual_participation_metrics(self, api):
        """PRD §3.7: "Completion freezes the participation metrics: `capacity_utilization_pct` is the percentage of checked-in attendees against the event's `capacity`, and `member_engagement_pct` is the percentage of checked-in attendees against the group's `active_member_count` at completion time, both rounded half-up to 2 decimal places."

        Design: Difficulty/dual_variant_calc/event_participation_dual_metric
        """
        program, sponsor, group, venue, event = _active_group_with_event(
            api, "emp_sp1", "emp_lead1", event_capacity=40, event_category="WORKSHOP",
            venue_capacity=100, group_name="Women In Eng", venue_name="Main Hall"
        )
        attendees = rsvp_many(event["id"], [f"emp_e{i}" for i in range(1, 9)])
        advance_clock(EVENT_START)
        for row in attendees:
            check_in(row["id"])
        advance_clock(EVENT_END)

        data = validate_success(api.complete_event(event["id"], DEI_HEADERS), 200)
        assert data["status"] == "COMPLETED"
        assert data["capacity_utilization_pct"] == pytest.approx(20.00), (
            "8 of 40 seats against event.capacity"
        )
        assert data["member_engagement_pct"] == pytest.approx(80.00), (
            "same 8 check-ins against the group's 10 active members"
        )

    def test_low_utilization_drives_tier_and_flag(self, api):
        """PRD §3.8: "The base points depend on category — 20 for `WORKSHOP`, 10 for `SOCIAL`, 80 for `RECRUITING`, 40 for `COMMUNITY` — and are scaled by a utilization tier: half when `capacity_utilization_pct` is below 25, full when it is at least 25 and below 75, and one-and-a-half when it is at least 75."
        PRD §3.7: "`impact_points` are computed as described in §3.8, `low_attendance_flag` is set true when `capacity_utilization_pct` is below 25.00, and a `RESERVED` `funding_status` flips to `SPENT`."

        Design: Difficulty/dual_variant_calc/event_participation_dual_metric
        """
        program, sponsor, group, venue, event = _active_group_with_event(
            api, "emp_sp1", "emp_lead1", event_capacity=40, event_category="WORKSHOP",
            venue_capacity=100, group_name="Women In Eng", venue_name="Main Hall"
        )
        attendees = rsvp_many(event["id"], [f"emp_e{i}" for i in range(1, 9)])
        advance_clock(EVENT_START)
        for row in attendees:
            check_in(row["id"])
        advance_clock(EVENT_END)

        data = validate_success(api.complete_event(event["id"], DEI_HEADERS), 200)
        assert data["impact_points"] == 10, "WORKSHOP base 20 x 0.5 tier, no sponsor bonus"
        assert data["low_attendance_flag"] is True, "20.00 < 25.00"

    def test_impact_points_capped_at_100(self, api):
        """PRD §3.8: "A sponsor bonus of 10 points is added when any RSVP of the event is `CHECKED_IN` with an `employee_id` matching the assigned sponsor's `employee_id`. The total is capped at 100, and the result is an integer."

        Design: Difficulty/combinatorial_formula/event_impact_points_tiered_cap
        """
        program = create_open_program(100000)
        sponsor = create_sponsor("emp_sp4", max_groups=3, max_mentees=2)
        group = create_active_group(
            program["id"], sponsor["id"], "Recruit Squad", "PROFESSIONAL", "emp_l4"
        )
        venue = create_venue("Expo Room", 100)
        event = setup_published_event(
            group["id"], venue["id"], title="Career Fair", category="RECRUITING",
            starts_at=EVENT_START, ends_at=EVENT_END, capacity=10,
        )
        attendees = rsvp_many(event["id"], [f"emp_e{i}" for i in range(1, 8)] + ["emp_sp4"])
        advance_clock(EVENT_START)
        for row in attendees:
            check_in(row["id"])
        advance_clock(EVENT_END)

        data = validate_success(api.complete_event(event["id"], DEI_HEADERS), 200)
        assert data["capacity_utilization_pct"] == pytest.approx(80.00), "8 of 10"
        # 80 * 1.5 + 10 sponsor bonus = 130, capped at the 100-point ceiling.
        assert data["impact_points"] == 100

    def test_high_utilization_clears_low_attendance_flag(self, api):
        """PRD §3.7: "`impact_points` are computed as described in §3.8, `low_attendance_flag` is set true when `capacity_utilization_pct` is below 25.00, and a `RESERVED` `funding_status` flips to `SPENT`."

        Design: Difficulty/combinatorial_formula/event_impact_points_tiered_cap
        """
        program = create_open_program(100000)
        sponsor = create_sponsor("emp_sp4", max_groups=3, max_mentees=2)
        group = create_active_group(
            program["id"], sponsor["id"], "Recruit Squad", "PROFESSIONAL", "emp_l4"
        )
        venue = create_venue("Expo Room", 100)
        event = setup_published_event(
            group["id"], venue["id"], title="Career Fair", category="RECRUITING",
            starts_at=EVENT_START, ends_at=EVENT_END, capacity=10,
        )
        attendees = rsvp_many(event["id"], [f"emp_e{i}" for i in range(1, 8)] + ["emp_sp4"])
        advance_clock(EVENT_START)
        for row in attendees:
            check_in(row["id"])
        advance_clock(EVENT_END)

        data = validate_success(api.complete_event(event["id"], DEI_HEADERS), 200)
        assert data["capacity_utilization_pct"] == pytest.approx(80.00)
        assert data["low_attendance_flag"] is False, "80.00 >= 25.00"


class TestSuspendCascade:
    def test_suspend_cancels_published_event(self, api):
        """PRD §3.5: "Suspension moves `ACTIVE` → `SUSPENDED`; reinstatement moves `SUSPENDED` → `ACTIVE`; dissolution moves either `ACTIVE` or `SUSPENDED` → `DISSOLVED`, which is terminal."
        PRD §3.5: "Suspension cascades. Every event of the group in `PLANNED` or `PUBLISHED` status is cancelled, and each such cancellation fires the event's own cancellation side effects in turn: the event's RSVPs in `REGISTERED`, `WAITLISTED`, or `CHECKED_IN` flip to `CANCELLED` with no waitlist promotion, and an event whose `funding_status` was `RESERVED` flips to `RELEASED`."

        Design: Difficulty/transitive_cascade/group_suspend_cancels_events_and_rsvps
        """
        program = create_open_program(100000)
        sponsor = create_sponsor("emp_sp10", max_groups=3, max_mentees=2)
        group = create_active_group(
            program["id"], sponsor["id"], "Suspend Me", "AFFINITY", "emp_l10"
        )
        venue = create_venue("Cafe", 20)
        event = setup_published_event(
            group["id"], venue["id"], title="Mixer", category="SOCIAL",
            starts_at=EVENT_START, ends_at=EVENT_END, capacity=5,
        )
        rsvp_many(event["id"], ["emp_e1", "emp_e2"])

        data = validate_success(
            api.set_group_status(group["id"], {"to_status": "SUSPENDED",
                                               "reason": "Conduct review"}, DEI_HEADERS),
            200,
        )
        assert data["status"] == "SUSPENDED"

        event_data = validate_success(api.get_event(event["id"], DEI_HEADERS), 200)
        assert event_data["status"] == "CANCELLED", (
            "link 1: group suspension cancels non-terminal events"
        )

    def test_suspended_event_cancels_its_rsvps(self, api):
        """PRD §3.5: "Suspension cascades. Every event of the group in `PLANNED` or `PUBLISHED` status is cancelled, and each such cancellation fires the event's own cancellation side effects in turn: the event's RSVPs in `REGISTERED`, `WAITLISTED`, or `CHECKED_IN` flip to `CANCELLED` with no waitlist promotion, and an event whose `funding_status` was `RESERVED` flips to `RELEASED`."

        Design: Difficulty/transitive_cascade/group_suspend_cancels_events_and_rsvps
        """
        program = create_open_program(100000)
        sponsor = create_sponsor("emp_sp10", max_groups=3, max_mentees=2)
        group = create_active_group(
            program["id"], sponsor["id"], "Suspend Me", "AFFINITY", "emp_l10"
        )
        venue = create_venue("Cafe", 20)
        event = setup_published_event(
            group["id"], venue["id"], title="Mixer", category="SOCIAL",
            starts_at=EVENT_START, ends_at=EVENT_END, capacity=5,
        )
        attendees = rsvp_many(event["id"], ["emp_e1", "emp_e2"])

        validate_success(
            api.set_group_status(group["id"], {"to_status": "SUSPENDED",
                                               "reason": "Conduct review"}, DEI_HEADERS),
            200,
        )

        for row in attendees:
            rsvp_data = validate_success(api.get_rsvp(row["id"], DEI_HEADERS), 200)
            assert rsvp_data["status"] == "CANCELLED", (
                "link 2: event cancellation cancels its RSVPs"
            )


class TestSuspendCascadeVisibility:
    def test_suspend_cascade_is_immediately_visible(self, api):
        """PRD §3.5: "Suspension cascades. Every event of the group in `PLANNED` or `PUBLISHED` status is cancelled, and each such cancellation fires the event's own cancellation side effects in turn: the event's RSVPs in `REGISTERED`, `WAITLISTED`, or `CHECKED_IN` flip to `CANCELLED` with no waitlist promotion, and an event whose `funding_status` was `RESERVED` flips to `RELEASED`."
        PRD §3.5: "Each of these transitions increments the group's `version` by 1."

        Design: Corner/cross_cutting_layers/cascading_suspend_is_atomic_and_visible
        """
        program = create_open_program(100000)
        sponsor = create_sponsor("emp_sp42", max_groups=3, max_mentees=2)
        group = create_active_group(
            program["id"], sponsor["id"], "Atomic Cascade", "AFFINITY", "emp_l63"
        )
        venue = create_venue("Cascade Room", 20)
        event = setup_published_event(
            group["id"], venue["id"], title="Cascaded", category="SOCIAL",
            starts_at=EVENT_START, ends_at=EVENT_END, capacity=5,
        )
        r1 = rsvp(event["id"], "emp_e1")

        resp = api.set_group_status(group["id"], {"to_status": "SUSPENDED"}, DEI_HEADERS)
        data = validate_success(resp, 200)
        assert data["status"] == "SUSPENDED"
        assert data["version"] == group["version"] + 1, "suspend increments group version by 1"

        rsvp_data = validate_success(api.get_rsvp(r1["id"], DEI_HEADERS), 200)
        assert rsvp_data["status"] == "CANCELLED", (
            "cascade visible on the immediate subsequent read"
        )
