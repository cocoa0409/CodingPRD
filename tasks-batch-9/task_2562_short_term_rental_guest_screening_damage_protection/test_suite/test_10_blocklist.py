"""Bans: the dispute loop's two exits, and safety outranking the calendar."""

from test_helpers import (
    ApiErrorId,
    assertions,
    constants,
    factories,
    fixtures,
    validate_error,
    validate_success,
)
from test_helpers.test_users import SECOND_COMPLIANCE_OFFICER


def _property_ban_mid_stay(api, guest_name, guest_email, **incident_overrides):
    """A PROPERTY ban written by the host over one acknowledged incident."""
    cast = fixtures.setup_waiver_listing(
        api, guest_name=guest_name, guest_email=guest_email
    )
    reservation = fixtures.book_stay(api, cast)
    fixtures.confirm_stay(api, cast, reservation["id"])
    fixtures.check_in_stay(api, cast, reservation["id"])
    fixtures.set_clock(api, constants.IN_STAY_CLOCK_UTC)
    fixtures.file_incident(api, cast, reservation["id"], **incident_overrides)
    assertions.assert_fields(
        fixtures.read_guest(api, cast), "guest", substantiated_incident_count=1
    )
    entry = fixtures.block_guest(
        api,
        cast,
        "PROPERTY",
        "SUBSTANTIATED_INCIDENT",
        property_id=cast.property_id,
    )
    assertions.assert_fields(
        entry,
        "blocklist_entry",
        entry_state="ACTIVE",
        dispute_window_state="OPEN",
        scope="PROPERTY",
        created_by_role="Host",
        created_by_user_id=cast.host_id,
        auto_generated=False,
        version=1,
    )
    return cast, reservation, entry


def _rebooking_attempt(api, cast):
    """A fresh future-dated request on the banned listing, clear of every calendar."""
    return api.create_reservation(
        cast.guest_headers,
        **factories.reservation_payload(
            cast.guest_id,
            cast.property_id,
            fixtures.read_property(api, cast)["version"],
            check_in="2026-08-20",
            check_out="2026-08-22",
        )
    )


def test_a_confirmed_dispute_returns_the_ban_to_active_with_its_right_spent(api):
    """The entry runs ACTIVE to DISPUTED and back, but the window only runs forward.

    Two dimensions move on one entity and only one of them is a loop: the enforcement
    dimension returns to ACTIVE while the window advances one way to RESOLVED, which
    is what makes the loop untraversable a second time. The guest's enforcing count
    reads 1 at every step, because DISPUTED never leaves the enforcing set.

    PRD: "A successful dispute moves `entry_state` from `ACTIVE` to `DISPUTED` and, in the same request, moves `dispute_window_state` from `OPEN` to `DISPUTED`, records the `dispute_statement_code`, and increases the entry's `version` by 1."
    PRD: "A `dispute_reason_code` of `GROUNDS_CONFIRMED` returns `entry_state` from `DISPUTED` to `ACTIVE`; the ban is enforceable again, its dispute right is spent, and the guest's `active_blocklist_scope_count` is unchanged because the entry never left the enforcing set."
    PRD: "Both outcomes set `dispute_decided_by_user_id` to the acting officer's `X-User-ID`, move `dispute_window_state` from `DISPUTED` to `RESOLVED` so that no second dispute is admissible, and increase the entry's `version` by 1."
    PRD: "Two gates apply: `dispute_window_state` must read `OPEN`, and the logical clock must be at or before `dispute_due_at`; a window that is already `DISPUTED`, `RESOLVED` or `EXPIRED`, or a clock past the deadline, is refused with `ERR_DISPUTE_WINDOW_CLOSED`."
    PRD: "A successful creation starts the entry at `entry_state` `ACTIVE` and `dispute_window_state` `OPEN`, sets `dispute_due_at` to the entry's `created_at` plus 336 hours, records `created_by_role` and `created_by_user_id` from the request headers, leaves `auto_generated` false, and sets `version` to 1."
    PRD: "Narrower `PROPERTY` and `HOST` entries cancel nothing; they take effect at the next confirmation attempt."

    Design: Difficulty/non_linear_state_machine/blocklist_dispute_cycle_returns_entry_to_active_with_window_spent
    """
    cast, reservation, entry = _property_ban_mid_stay(
        api,
        "Rex Calder",
        "rex@guest.test",
        detected_at="2026-08-11T01:30:00Z",
        description="Balcony railing bent out of shape.",
    )
    assert entry["dispute_due_at"].startswith("2026-08-25T02:00:00"), (
        "the dispute window closes 336 hours after the entry was written, "
        "not at some other deadline: {0}".format(entry["dispute_due_at"])
    )
    assertions.assert_fields(
        fixtures.read_guest(api, cast), "guest", active_blocklist_scope_count=1
    )

    disputed = validate_success(
        api.dispute_blocklist_entry(
            entry["id"], cast.guest_headers, dispute_statement_code="FACTS_DISPUTED"
        )
    )
    assertions.assert_fields(
        disputed,
        "blocklist_entry",
        entry_state="DISPUTED",
        dispute_window_state="DISPUTED",
        dispute_statement_code="FACTS_DISPUTED",
        version=2,
    )
    assertions.assert_fields(
        fixtures.read_guest(api, cast), "guest", active_blocklist_scope_count=1
    )

    ruled = validate_success(
        api.decide_blocklist_dispute(
            entry["id"],
            SECOND_COMPLIANCE_OFFICER,
            dispute_reason_code="GROUNDS_CONFIRMED",
        )
    )
    assertions.assert_fields(
        ruled,
        "blocklist_entry",
        entry_state="ACTIVE",
        dispute_window_state="RESOLVED",
        dispute_reason_code="GROUNDS_CONFIRMED",
        dispute_decided_by_user_id="co-2",
        dispute_statement_code="FACTS_DISPUTED",
        created_by_user_id=cast.host_id,
        auto_generated=False,
        version=3,
    )
    assert ruled["dispute_due_at"] == entry["dispute_due_at"], (
        "ruling on the dispute does not move the deadline"
    )

    validate_error(
        api.dispute_blocklist_entry(
            entry["id"], cast.guest_headers, dispute_statement_code="REMEDIED"
        ),
        ApiErrorId.ERR_DISPUTE_WINDOW_CLOSED,
        expected_status=409,
    )
    still_active = validate_success(
        api.get_blocklist_entry(entry["id"], SECOND_COMPLIANCE_OFFICER)
    )
    assertions.assert_fields(
        still_active,
        "blocklist_entry",
        entry_state="ACTIVE",
        dispute_window_state="RESOLVED",
        dispute_statement_code="FACTS_DISPUTED",
        version=3,
    )
    assertions.assert_fields(
        fixtures.read_guest(api, cast), "guest", active_blocklist_scope_count=1
    )
    assertions.assert_fields(
        validate_success(api.get_reservation(reservation["id"], cast.host_headers)),
        "reservation",
        stay_state="IN_STAY",
    )


def test_a_withdrawn_dispute_leaves_the_loop_by_its_terminal_door(api):
    """The other ruling ends the entry instead of returning it, and ends it once.

    The same loop has a second exit: withdrawn grounds move the entry to the terminal
    LIFTED rather than back to ACTIVE, dropping the guest's enforcing count to zero
    and letting the guest book the listing again. The window still spends itself on
    the way, so the ruling is as unrepeatable as the confirmed one.

    PRD: "The guest's `active_blocklist_scope_count` does not move, because `DISPUTED` remains inside the enforcing set — filing a dispute does not suspend the ban, and the entry keeps blocking confirmations while the dispute is pending."
    PRD: "A `dispute_reason_code` of `GROUNDS_WITHDRAWN` or `IDENTITY_ERROR` moves `entry_state` from `DISPUTED` to `LIFTED`; the guest's `active_blocklist_scope_count` is recomputed and falls by 1, the guest's `version` increases by 1, and that guest becomes confirmable again at the lifted breadth."
    PRD: "`entry_state` runs `ACTIVE`, `DISPUTED` and `LIFTED`, with `LIFTED` terminal."
    PRD: "If any blocklist entry whose `entry_state` is `ACTIVE` or `DISPUTED` covers this guest for this listing, the booking is refused with `ERR_GUEST_BLOCKLISTED`."

    Design: Difficulty/non_linear_state_machine/blocklist_dispute_cycle_returns_entry_to_active_with_window_spent
    """
    cast, _reservation, entry = _property_ban_mid_stay(
        api,
        "Rex Calder",
        "rex@guest.test",
        detected_at="2026-08-11T01:30:00Z",
        description="Balcony railing bent out of shape.",
    )
    validate_error(
        _rebooking_attempt(api, cast),
        ApiErrorId.ERR_GUEST_BLOCKLISTED,
        expected_status=409,
    )

    disputed = validate_success(
        api.dispute_blocklist_entry(
            entry["id"], cast.guest_headers, dispute_statement_code="REMEDIED"
        )
    )
    assertions.assert_fields(
        disputed,
        "blocklist_entry",
        entry_state="DISPUTED",
        dispute_window_state="DISPUTED",
        dispute_statement_code="REMEDIED",
    )
    assertions.assert_fields(
        fixtures.read_guest(api, cast), "guest", active_blocklist_scope_count=1
    )
    validate_error(
        _rebooking_attempt(api, cast),
        ApiErrorId.ERR_GUEST_BLOCKLISTED,
        expected_status=409,
    )

    lifted = validate_success(
        api.decide_blocklist_dispute(
            entry["id"],
            SECOND_COMPLIANCE_OFFICER,
            dispute_reason_code="GROUNDS_WITHDRAWN",
        )
    )
    assertions.assert_fields(
        lifted,
        "blocklist_entry",
        entry_state="LIFTED",
        dispute_window_state="RESOLVED",
        dispute_reason_code="GROUNDS_WITHDRAWN",
        dispute_decided_by_user_id="co-2",
        version=3,
    )
    assertions.assert_fields(
        fixtures.read_guest(api, cast), "guest", active_blocklist_scope_count=0
    )

    rebooked = validate_success(_rebooking_attempt(api, cast), expected_status=201)
    assertions.assert_fields(
        rebooked,
        "reservation",
        stay_state="REQUESTED",
        property_id=cast.property_id,
        guest_id=cast.guest_id,
        nights=2,
    )
    validate_error(
        api.dispute_blocklist_entry(
            entry["id"], cast.guest_headers, dispute_statement_code="FACTS_DISPUTED"
        ),
        ApiErrorId.ERR_DISPUTE_WINDOW_CLOSED,
        expected_status=409,
    )
    assertions.assert_fields(
        validate_success(api.get_blocklist_entry(entry["id"], SECOND_COMPLIANCE_OFFICER)),
        "blocklist_entry",
        entry_state="LIFTED",
        dispute_window_state="RESOLVED",
        version=3,
    )
    assertions.assert_page(
        api.list_blocklist_entries(
            SECOND_COMPLIANCE_OFFICER, guest_id=cast.guest_id, entry_state="ACTIVE"
        ),
        total_count=0,
    )


def _ban_over_a_live_stay(api):
    """A banned guest who is also mid-stay on the listing she is banned from."""
    cast = fixtures.setup_waiver_listing(
        api, guest_name="Nora Vance", guest_email="nora@guest.test"
    )
    reservation = fixtures.book_stay(api, cast)
    fixtures.confirm_stay(api, cast, reservation["id"])
    fixtures.check_in_stay(api, cast, reservation["id"])
    fixtures.file_incident(
        api,
        cast,
        reservation["id"],
        incident_type="NOISE_VIOLATION",
        source="NEIGHBOR_COMPLAINT",
        detected_at="2026-08-10T15:40:00Z",
        decibel_reading=82.0,
        description="Amplified music, two neighbour calls.",
    )
    entry = fixtures.block_guest(
        api, cast, "PROPERTY", "SUBSTANTIATED_INCIDENT", property_id=cast.property_id
    )
    return cast, reservation, entry


def _overlapping_request(api, cast):
    """A request that collides with the live stay on both calendars at once."""
    return api.create_reservation(
        cast.guest_headers,
        **factories.reservation_payload(
            cast.guest_id,
            cast.property_id,
            fixtures.read_property(api, cast)["version"],
            check_in="2026-08-11",
            check_out="2026-08-14",
        )
    )


def test_the_standing_ban_is_the_only_error_a_triply_bad_request_reports(api):
    """One request breaks the ban clause and both calendar clauses; safety answers.

    The guest is banned from this listing and is simultaneously mid-stay on it, so
    the requested dates collide with the listing's own live booking and with the
    guest's own. The ban is the earlier gate, so it is the single reported error —
    a handler that runs its interval scan first would answer with a calendar clash.

    PRD: "After the header, shape, existence, ownership and stale-version checks of §2.8 have passed, booking applies its own rules in this sequence:"
    PRD: "If any blocklist entry whose `entry_state` is `ACTIVE` or `DISPUTED` covers this guest for this listing, the booking is refused with `ERR_GUEST_BLOCKLISTED`."
    PRD: "No conflict with the listing's own live bookings, refused with `ERR_PROPERTY_CALENDAR_CONFLICT`."
    PRD: "No conflict with the guest's own live bookings anywhere on the platform, refused with `ERR_GUEST_STAY_OVERLAP`."

    Design: Difficulty/priority_pair_validation_conflict/blocklist_safety_beats_calendar_conflict_on_reservation_create
    """
    cast, reservation, entry = _ban_over_a_live_stay(api)
    refusal = validate_error(
        _overlapping_request(api, cast),
        ApiErrorId.ERR_GUEST_BLOCKLISTED,
        expected_status=409,
    )
    assert refusal["error_id"] not in (
        "ERR_PROPERTY_CALENDAR_CONFLICT",
        "ERR_GUEST_STAY_OVERLAP",
    ), "the temporal clauses must stay behind the safety clause"

    assertions.assert_fields(
        validate_success(api.get_blocklist_entry(entry["id"], SECOND_COMPLIANCE_OFFICER)),
        "blocklist_entry",
        entry_state="ACTIVE",
        scope="PROPERTY",
        property_id=cast.property_id,
    )
    assertions.assert_page(
        api.list_reservations(cast.host_headers, guest_id=cast.guest_id),
        total_count=1,
    )
    assertions.assert_fields(
        validate_success(api.get_reservation(reservation["id"], cast.host_headers)),
        "reservation",
        stay_state="IN_STAY",
    )
    assertions.assert_fields(
        fixtures.read_property(api, cast), "property", listing_state="ACTIVE"
    )


def test_lifting_the_ban_reveals_the_calendar_clash_it_was_masking(api):
    """The very same request answers ERR_PROPERTY_CALENDAR_CONFLICT once safety clears.

    Nothing about the dates changes: the ban is simply lifted outright, which takes
    the entry out of the enforcing set and lets the request fall through to the
    temporal clauses. The listing calendar is the earlier of the two, so that is the
    error — proving both were live underneath the ban all along.

    PRD: "`LIFTED` entries never block."
    PRD: "No conflict with the listing's own live bookings, refused with `ERR_PROPERTY_CALENDAR_CONFLICT`."
    PRD: "A `ComplianceOfficer` may also lift an `ACTIVE` entry outright, without any dispute."
    PRD: "Both consider only reservations whose `stay_state` is `REQUESTED`, `CONFIRMED` or `IN_STAY`; rows already `CANCELLED` or `COMPLETED` never conflict with anything."

    Design: Difficulty/priority_pair_validation_conflict/blocklist_safety_beats_calendar_conflict_on_reservation_create
    """
    cast, reservation, entry = _ban_over_a_live_stay(api)
    validate_error(
        _overlapping_request(api, cast),
        ApiErrorId.ERR_GUEST_BLOCKLISTED,
        expected_status=409,
    )

    lifted = validate_success(
        api.lift_blocklist_entry(entry["id"], SECOND_COMPLIANCE_OFFICER)
    )
    assertions.assert_fields(lifted, "blocklist_entry", entry_state="LIFTED")
    assertions.assert_fields(
        fixtures.read_guest(api, cast), "guest", active_blocklist_scope_count=0
    )

    unmasked = validate_error(
        _overlapping_request(api, cast),
        ApiErrorId.ERR_PROPERTY_CALENDAR_CONFLICT,
        expected_status=409,
    )
    assert unmasked["error_id"] != "ERR_GUEST_BLOCKLISTED", (
        "a lifted entry cannot go on refusing the booking"
    )
    assertions.assert_page(
        api.list_reservations(cast.host_headers, guest_id=cast.guest_id),
        total_count=1,
    )
    assertions.assert_fields(
        validate_success(api.get_reservation(reservation["id"], cast.host_headers)),
        "reservation",
        stay_state="IN_STAY",
    )
