"""The construction shift lifecycle: scheduling windows, opening, locking, completion."""

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import api_errors as E
from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as X
from test_helpers.test_users import ADMIN, CREW_LEAD, make_applicant_headers, make_volunteer_headers


def test_a_completed_shift_credits_the_partner_who_showed_and_strikes_the_one_who_did_not(api):
    """One completion, two forks, both running in the same request.

    "Completion forks, and both branches run. Every seat in `CHECKED_IN` status
    becomes `COMPLETED`, and each such seat whose `role` is `HOMEOWNER_PARTNER`
    mints the shift-synthesized sweat equity entry described in §3.4. Every seat
    still in `CONFIRMED` status — confirmed but never checked in — becomes
    `NO_SHOW` and raises its volunteer's `no_show_strikes` by 1."

    The partner seat was checked in and the community seat was not, so a single
    `complete` call must move one seat forward and the other sideways.

    Design: Difficulty/non_linear_state_machine/shift_completion_fork_partner_credit_versus_no_show_strike
    """
    program = X.setup_program(api)
    site = X.setup_ready_site(api, program["id"])
    built = X.setup_selected_household(api, program["id"])
    household, member = built["household"], built["members"][0]
    X.setup_draft_application(api, household["id"], site["id"])

    volunteer = X.setup_volunteer(api, program["id"])
    shift = X.setup_open_shift(
        api,
        site["id"],
        start_at="2026-08-10T08:00:00.000Z",
        end_at="2026-08-10T12:00:00.000Z",
        volunteer_slots=1,
    )
    general_seat = X.reserve_volunteer_seat(api, shift["id"], volunteer["id"])
    X.confirm_seat(api, general_seat["id"], headers=make_volunteer_headers(volunteer["id"]))
    partner_seat = X.reserve_partner_seat(api, shift["id"], member["id"])
    X.confirm_seat(api, partner_seat["id"], headers=make_applicant_headers(household["id"]))
    locked = X.lock_shift(api, shift["id"])
    assert locked["duration_hours"] == 4.0

    X.advance_clock(api, "2026-08-10T08:00:00.000Z")
    X.check_in_seat(api, partner_seat["id"])
    X.advance_clock(api, "2026-08-10T12:00:00.000Z")

    completed = validate_success(api.complete_shift(shift["id"], F.completion_payload(), headers=CREW_LEAD))
    assert completed["status"] == C.SHIFT_COMPLETED

    partner_after = validate_success(api.get_assignment(partner_seat["id"], headers=CREW_LEAD))
    assert partner_after["status"] == C.ASSIGNMENT_COMPLETED
    general_after = validate_success(api.get_assignment(general_seat["id"], headers=CREW_LEAD))
    assert general_after["status"] == C.ASSIGNMENT_NO_SHOW

    volunteer_after = validate_success(api.get_volunteer(volunteer["id"], headers=CREW_LEAD))
    assert volunteer_after["no_show_strikes"] == 1
    # One strike is far short of the three that suspend a profile.
    assert volunteer_after["status"] == C.VOLUNTEER_ACTIVE


def test_the_synthesized_partner_entry_arrives_verified_but_not_yet_credited(api):
    """The minted entry lands pre-verified by the crew lead and awaits a credit.

    Completion "mints the shift-synthesized sweat equity entry described in §3.4",
    and that section pins its shape: the entry is created directly in `VERIFIED`
    status with the crew lead recorded as the verifier, which is why the ledger
    still reads zero credited hours until a coordinator posts the credit.

    Design: Difficulty/non_linear_state_machine/shift_completion_fork_partner_credit_versus_no_show_strike
    """
    program = X.setup_program(api)
    site = X.setup_ready_site(api, program["id"])
    built = X.setup_selected_household(api, program["id"])
    household, member = built["household"], built["members"][0]
    X.setup_draft_application(api, household["id"], site["id"])

    volunteer = X.setup_volunteer(api, program["id"])
    shift = X.setup_open_shift(
        api,
        site["id"],
        start_at="2026-08-10T08:00:00.000Z",
        end_at="2026-08-10T12:00:00.000Z",
        volunteer_slots=1,
    )
    general_seat = X.reserve_volunteer_seat(api, shift["id"], volunteer["id"])
    X.confirm_seat(api, general_seat["id"], headers=make_volunteer_headers(volunteer["id"]))
    partner_seat = X.reserve_partner_seat(api, shift["id"], member["id"])
    X.confirm_seat(api, partner_seat["id"], headers=make_applicant_headers(household["id"]))
    X.lock_shift(api, shift["id"])

    X.advance_clock(api, "2026-08-10T08:00:00.000Z")
    X.check_in_seat(api, partner_seat["id"])
    X.advance_clock(api, "2026-08-10T12:00:00.000Z")
    X.complete_shift(api, shift["id"])

    entries, meta = validate_paginated(
        api.list_entries({"shift_assignment_id": partner_seat["id"]}, headers=ADMIN)
    )
    assert meta["total_count"] == 1
    entry = entries[0]
    assert entry["shift_assignment_id"] == partner_seat["id"]
    assert entry["member_id"] == member["id"]
    assert entry["category"] == C.CATEGORY_CONSTRUCTION
    assert entry["hours_claimed"] == 4.0
    assert entry["status"] == C.ENTRY_VERIFIED
    assert entry["verified_by_user_id"] == "cm-1"

    household_after = validate_success(api.get_household(household["id"], headers=ADMIN))
    # Verified is not credited: the hour ledger has not moved.
    assert household_after["sweat_equity_credited_hours"] == 0.0


def test_a_safety_hold_cancels_the_shift_its_seat_and_the_committed_hours(api):
    """One posture change walks three hops down the construction tree.

    "It then cascades three hops: every shift of that site in `SCHEDULED`, `OPEN`,
    or `LOCKED` status is cancelled; every assignment of each of those shifts in
    `RESERVED`, `CONFIRMED`, or `CHECKED_IN` status is cancelled; and each
    cancelled assignment lowers its volunteer's `assigned_hours_committed` by that
    shift's `duration_hours`. No strikes are recorded — a safety hold is the
    affiliate's fault, not the volunteer's."

    Design: Difficulty/transitive_cascade/safety_hold_cascade_shifts_to_assignments_to_volunteer_hours
    """
    program = X.setup_program(api)
    site = X.setup_ready_site(api, program["id"])
    volunteer = X.setup_volunteer(api, program["id"])
    shift = X.setup_open_shift(
        api,
        site["id"],
        start_at="2026-08-10T08:00:00.000Z",
        end_at="2026-08-10T16:00:00.000Z",
        volunteer_slots=1,
    )
    assert shift["duration_hours"] == 8.0
    seat = X.reserve_volunteer_seat(api, shift["id"], volunteer["id"])
    assert seat["status"] == C.ASSIGNMENT_RESERVED
    before = validate_success(api.get_volunteer(volunteer["id"], headers=CREW_LEAD))
    assert before["assigned_hours_committed"] == 8.0

    held = validate_success(
        api.set_safety_posture(site["id"], F.safety_posture_payload(C.POSTURE_HOLD), headers=CREW_LEAD)
    )
    assert held["readiness_status"] == C.SITE_SAFETY_HOLD
    assert held["safety_posture"] == C.POSTURE_HOLD
    assert held["pre_hold_readiness_status"] == C.SITE_READY_TO_BUILD

    shift_after = validate_success(api.get_shift(shift["id"], headers=CREW_LEAD))
    assert shift_after["status"] == C.SHIFT_CANCELLED
    seat_after = validate_success(api.get_assignment(seat["id"], headers=CREW_LEAD))
    assert seat_after["status"] == C.ASSIGNMENT_CANCELLED

    volunteer_after = validate_success(api.get_volunteer(volunteer["id"], headers=CREW_LEAD))
    assert volunteer_after["assigned_hours_committed"] == 0.0
    assert volunteer_after["no_show_strikes"] == 0
    assert volunteer_after["status"] == C.VOLUNTEER_ACTIVE


def test_releasing_the_hold_restores_the_readiness_but_never_the_cancelled_shift(api):
    """The cascade is one-way: the posture heals, the roster does not.

    "Releasing the hold with a `posture` of `CLEAR` restores `readiness_status`
    from `pre_hold_readiness_status` ... then clears `pre_hold_readiness_status` to
    null and sets `safety_posture` back to `CLEAR`. Cancelled shifts are **not**
    restored; the crew must schedule new ones."

    Design: Difficulty/transitive_cascade/safety_hold_cascade_shifts_to_assignments_to_volunteer_hours
    """
    program = X.setup_program(api)
    site = X.setup_ready_site(api, program["id"])
    volunteer = X.setup_volunteer(api, program["id"])
    shift = X.setup_open_shift(
        api,
        site["id"],
        start_at="2026-08-10T08:00:00.000Z",
        end_at="2026-08-10T16:00:00.000Z",
        volunteer_slots=1,
    )
    seat = X.reserve_volunteer_seat(api, shift["id"], volunteer["id"])
    validate_success(
        api.set_safety_posture(site["id"], F.safety_posture_payload(C.POSTURE_HOLD), headers=CREW_LEAD)
    )

    released = validate_success(
        api.set_safety_posture(site["id"], F.safety_posture_payload(C.POSTURE_CLEAR), headers=CREW_LEAD)
    )
    assert released["readiness_status"] == C.SITE_READY_TO_BUILD
    assert released["safety_posture"] == C.POSTURE_CLEAR
    assert released["pre_hold_readiness_status"] is None

    assert validate_success(api.get_shift(shift["id"], headers=CREW_LEAD))["status"] == C.SHIFT_CANCELLED
    assert (
        validate_success(api.get_assignment(seat["id"], headers=CREW_LEAD))["status"]
        == C.ASSIGNMENT_CANCELLED
    )
    assert validate_success(api.get_volunteer(volunteer["id"], headers=CREW_LEAD))["assigned_hours_committed"] == 0.0


def test_a_second_shift_may_not_start_fifty_nine_minutes_after_the_first_ends(api):
    """The closed cleanup buffer bites one minute short of the hour.

    "Each shift holds its site for its own window extended by a 60-minute cleanup
    buffer on each end, and the interval is closed on both sides. A candidate
    window collides with an existing shift when the candidate's start is strictly
    before that shift's end plus 60 minutes *and* that shift's start is strictly
    before the candidate's end plus 60 minutes; a collision is refused with
    `ERR_SITE_SHIFT_BUFFER_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/overlap_site_closed_60min_cleanup_buffer_exact_abutment
    """
    program = X.setup_program(api)
    site = X.setup_ready_site(api, program["id"])
    X.setup_shift(
        api,
        site["id"],
        start_at="2026-08-10T08:00:00.000Z",
        end_at="2026-08-10T12:00:00.000Z",
        volunteer_slots=6,
        required_trade_slots=0,
    )

    validate_error(
        api.create_shift(
            F.shift_payload(
                site["id"],
                start_at="2026-08-10T12:59:00.000Z",
                end_at="2026-08-10T16:59:00.000Z",
                volunteer_slots=6,
                required_trade_slots=0,
            ),
            headers=CREW_LEAD,
        ),
        E.ERR_SITE_SHIFT_BUFFER_CONFLICT,
        409,
    )

    _, meta = validate_paginated(api.list_shifts({"build_site_id": site["id"]}, headers=CREW_LEAD))
    assert meta["total_count"] == 1


def test_a_second_shift_starting_exactly_sixty_minutes_later_abuts_legally(api):
    """Exact abutment clears, because both comparisons are strict.

    "Because both comparisons are strict, a candidate beginning exactly 60 minutes
    after an existing shift ends is accepted, while one beginning 59 minutes after
    it is rejected."

    Design: Difficulty/resource_temporal_overlap/overlap_site_closed_60min_cleanup_buffer_exact_abutment
    """
    program = X.setup_program(api)
    site = X.setup_ready_site(api, program["id"])
    X.setup_shift(
        api,
        site["id"],
        start_at="2026-08-10T08:00:00.000Z",
        end_at="2026-08-10T12:00:00.000Z",
        volunteer_slots=6,
        required_trade_slots=0,
    )

    accepted = validate_success(
        api.create_shift(
            F.shift_payload(
                site["id"],
                start_at="2026-08-10T13:00:00.000Z",
                end_at="2026-08-10T17:00:00.000Z",
                volunteer_slots=6,
                required_trade_slots=0,
            ),
            headers=CREW_LEAD,
        ),
        201,
    )
    assert accepted["status"] == C.SHIFT_SCHEDULED
    assert accepted["duration_hours"] == 4.0

    _, meta = validate_paginated(api.list_shifts({"build_site_id": site["id"]}, headers=CREW_LEAD))
    assert meta["total_count"] == 2

    site_after = validate_success(api.get_build_site(site["id"], headers=ADMIN))
    assert site_after["readiness_status"] == C.SITE_READY_TO_BUILD
    assert site_after["safety_posture"] == C.POSTURE_CLEAR


def test_locking_releases_the_unconfirmed_seat_and_starts_the_build(api):
    """One lock fires three side effects and drags the parent site along.

    "Locking sets `safety_briefing_completed` to true, releases every seat still
    in `RESERVED` status by cancelling it and lowering that volunteer's
    `assigned_hours_committed` by the shift's `duration_hours`, and cascades the
    site `READY_TO_BUILD → UNDER_CONSTRUCTION` when the site had not yet started."

    Design: Corner/state_machines/shift_lock_cancels_reserved_seats_and_starts_construction
    """
    program = X.setup_program(api)
    site = X.setup_ready_site(api, program["id"])
    vol_a = X.setup_volunteer(api, program["id"], full_name="Dana Reyes", birth_date="1990-04-10T00:00:00.000Z")
    vol_b = X.setup_volunteer(api, program["id"], full_name="Eli Brooks", birth_date="1988-02-19T00:00:00.000Z")
    vol_c = X.setup_volunteer(api, program["id"], full_name="Faye Ortiz", birth_date="1992-06-30T00:00:00.000Z")
    shift = X.setup_open_shift(api, site["id"], volunteer_slots=3)

    seat_a = X.reserve_volunteer_seat(api, shift["id"], vol_a["id"])
    X.confirm_seat(api, seat_a["id"], headers=make_volunteer_headers(vol_a["id"]))
    seat_b = X.reserve_volunteer_seat(api, shift["id"], vol_b["id"])
    X.confirm_seat(api, seat_b["id"], headers=make_volunteer_headers(vol_b["id"]))
    seat_c = X.reserve_volunteer_seat(api, shift["id"], vol_c["id"])

    locked = validate_success(api.lock_shift(shift["id"], F.lock_payload("SB-2026-08-05-A"), headers=CREW_LEAD))
    assert locked["status"] == C.SHIFT_LOCKED
    assert locked["safety_briefing_completed"] is True
    assert locked["confirmed_general_count"] == 2
    assert locked["fill_ratio"] == 0.6667

    assert (
        validate_success(api.get_assignment(seat_c["id"], headers=CREW_LEAD))["status"]
        == C.ASSIGNMENT_CANCELLED
    )
    assert (
        validate_success(api.get_assignment(seat_a["id"], headers=CREW_LEAD))["status"]
        == C.ASSIGNMENT_CONFIRMED
    )

    released_volunteer = validate_success(api.get_volunteer(vol_c["id"], headers=CREW_LEAD))
    assert released_volunteer["assigned_hours_committed"] == 0
    assert released_volunteer["no_show_strikes"] == 0
    kept_volunteer = validate_success(api.get_volunteer(vol_a["id"], headers=CREW_LEAD))
    assert kept_volunteer["assigned_hours_committed"] == 4.0

    site_after = validate_success(api.get_build_site(site["id"], headers=ADMIN))
    assert site_after["readiness_status"] == C.SITE_UNDER_CONSTRUCTION
    assert site_after["safety_posture"] == C.POSTURE_CLEAR
    assert site_after["title_cleared"] is True
    assert site_after["environmental_cleared"] is True
    assert site_after["utilities_cleared"] is True


def test_reopening_clears_the_briefing_and_the_cycle_is_traversable_twice(api):
    """`LOCKED → OPEN` is the one backward edge, and it is not a replay.

    "The same action also reopens a locked shift — `LOCKED → OPEN` — but only
    before the shift begins and only while no seat has been checked in; reopening
    resets `safety_briefing_completed` to false. The `OPEN ↔ LOCKED` cycle exists
    to let a crew lead add capacity after locking too early."

    Nothing walks the site back, and the confirmed seat keeps its committed hours.

    Design: Corner/state_machines/shift_relock_cycle_toggles_the_safety_briefing_flag
    """
    program = X.setup_program(api)
    site = X.setup_ready_site(api, program["id"])
    volunteer = X.setup_volunteer(api, program["id"], full_name="Dana Reyes")
    shift = X.setup_open_shift(api, site["id"], volunteer_slots=1)
    seat = X.reserve_volunteer_seat(api, shift["id"], volunteer["id"])
    X.confirm_seat(api, seat["id"], headers=make_volunteer_headers(volunteer["id"]))
    X.lock_shift(api, shift["id"], safety_briefing_reference="SB-2026-08-05-A")

    validate_error(
        api.lock_shift(shift["id"], F.lock_payload("SB-2026-08-05-A-REPLAY"), headers=CREW_LEAD),
        E.ERR_TRANSITION_NOT_ALLOWED,
        409,
    )

    reopened = validate_success(api.open_shift(shift["id"], headers=CREW_LEAD))
    assert reopened["status"] == C.SHIFT_OPEN
    assert reopened["safety_briefing_completed"] is False
    assert reopened["confirmed_general_count"] == 1
    assert reopened["fill_ratio"] == 1.0

    assert validate_success(api.get_volunteer(volunteer["id"], headers=CREW_LEAD))["assigned_hours_committed"] == 4.0
    site_after = validate_success(api.get_build_site(site["id"], headers=ADMIN))
    assert site_after["readiness_status"] == C.SITE_UNDER_CONSTRUCTION

    relocked = validate_success(api.lock_shift(shift["id"], F.lock_payload("SB-2026-08-05-B"), headers=CREW_LEAD))
    assert relocked["status"] == C.SHIFT_LOCKED
    assert relocked["safety_briefing_completed"] is True


def test_cancelling_a_shift_refunds_every_seated_volunteer_without_a_strike(api):
    """A shift cancellation is a pure compensation, unlike a no-show.

    "Cancelling a shift outright — from `SCHEDULED`, `OPEN`, or `LOCKED`, with a
    `cancellation_reason` — cancels every one of its seats in `RESERVED`,
    `CONFIRMED`, or `CHECKED_IN` status, lowering each affected volunteer's
    `assigned_hours_committed` by the shift's `duration_hours`, and records no
    strike against anybody."

    Design: Corner/state_machines/shift_cancellation_refunds_every_seated_volunteer
    """
    program = X.setup_program(api)
    site = X.setup_ready_site(api, program["id"])
    vol_a = X.setup_volunteer(api, program["id"], full_name="Dana Reyes")
    vol_b = X.setup_volunteer(api, program["id"], full_name="Eli Brooks", birth_date="1988-02-19T00:00:00.000Z")
    shift = X.setup_open_shift(api, site["id"], volunteer_slots=2)
    seat_a = X.reserve_volunteer_seat(api, shift["id"], vol_a["id"])
    X.confirm_seat(api, seat_a["id"], headers=make_volunteer_headers(vol_a["id"]))
    X.reserve_volunteer_seat(api, shift["id"], vol_b["id"])

    cancelled = validate_success(
        api.cancel_shift(
            shift["id"],
            F.cancellation_payload(cancellation_reason="Severe weather forecast for the build day"),
            headers=CREW_LEAD,
        )
    )
    assert cancelled["status"] == C.SHIFT_CANCELLED
    assert cancelled["confirmed_general_count"] == 0
    assert cancelled["fill_ratio"] == 0

    seats, meta = validate_paginated(api.list_assignments({"shift_id": shift["id"]}, headers=CREW_LEAD))
    assert meta["total_count"] == 2
    assert [s["status"] for s in seats] == [C.ASSIGNMENT_CANCELLED, C.ASSIGNMENT_CANCELLED]

    for volunteer in (vol_a, vol_b):
        reread = validate_success(api.get_volunteer(volunteer["id"], headers=CREW_LEAD))
        assert reread["assigned_hours_committed"] == 0
        assert reread["no_show_strikes"] == 0
        assert reread["status"] == C.VOLUNTEER_ACTIVE

    site_after = validate_success(api.get_build_site(site["id"], headers=ADMIN))
    assert site_after["readiness_status"] == C.SITE_READY_TO_BUILD
    assert site_after["safety_posture"] == C.POSTURE_CLEAR


def test_the_fill_gate_takes_the_ceiling_of_sixty_percent_of_five_slots(api):
    """Three of five confirmed locks a shift; two do not.

    "`confirmed_general_count` must reach at least sixty percent of
    `volunteer_slots`, rounded **up** to a whole volunteer, or the lock is refused
    with `ERR_SHIFT_FILL_INSUFFICIENT`; on a five-slot shift the minimum is 3
    confirmed general volunteers, so three confirmations lock and two do not."

    Design: Corner/calculations/shift_fill_gate_uses_the_ceiling_of_sixty_percent_of_slots
    """
    program = X.setup_program(api)
    site = X.setup_ready_site(api, program["id"])
    vol_a = X.setup_volunteer(api, program["id"], full_name="Dana Reyes")
    vol_b = X.setup_volunteer(api, program["id"], full_name="Eli Brooks", birth_date="1988-02-19T00:00:00.000Z")
    vol_c = X.setup_volunteer(api, program["id"], full_name="Faye Ortiz", birth_date="1992-06-30T00:00:00.000Z")
    shift = X.setup_open_shift(api, site["id"], volunteer_slots=5)

    seat_a = X.reserve_volunteer_seat(api, shift["id"], vol_a["id"])
    X.confirm_seat(api, seat_a["id"], headers=make_volunteer_headers(vol_a["id"]))
    seat_b = X.reserve_volunteer_seat(api, shift["id"], vol_b["id"])
    X.confirm_seat(api, seat_b["id"], headers=make_volunteer_headers(vol_b["id"]))
    seat_c = X.reserve_volunteer_seat(api, shift["id"], vol_c["id"])

    two_of_five = validate_success(api.get_shift(shift["id"], headers=CREW_LEAD))
    assert two_of_five["confirmed_general_count"] == 2
    assert two_of_five["confirmed_trade_count"] == 0
    assert two_of_five["fill_ratio"] == 0.4

    validate_error(
        api.lock_shift(shift["id"], F.lock_payload("SB-2026-08-05-EARLY"), headers=CREW_LEAD),
        E.ERR_SHIFT_FILL_INSUFFICIENT,
        409,
    )

    third = validate_success(
        api.confirm_assignment(seat_c["id"], headers=make_volunteer_headers(vol_c["id"]))
    )
    assert third["status"] == C.ASSIGNMENT_CONFIRMED

    locked = validate_success(api.lock_shift(shift["id"], F.lock_payload(), headers=CREW_LEAD))
    assert locked["status"] == C.SHIFT_LOCKED
    assert locked["confirmed_general_count"] == 3
    assert locked["fill_ratio"] == 0.6
    assert locked["safety_briefing_completed"] is True


def test_a_lock_is_refused_while_the_named_trade_seat_is_empty(api):
    """Trade coverage is an independent gate from general fill.

    "`confirmed_trade_count` must be at least `required_trade_slots`, or the lock
    is refused with `ERR_TRADE_COVERAGE_INSUFFICIENT` — a shift that needs an
    electrician does not proceed without one."

    Two confirmed general seats already clear the ceiling of sixty percent of
    three slots, so the only thing missing is the plumber.

    Design: Corner/validations/a_lock_is_refused_while_trade_coverage_is_short
    """
    program = X.setup_program(api)
    site = X.setup_ready_site(api, program["id"])
    vol_1 = X.setup_volunteer(api, program["id"], full_name="Dana Reyes")
    vol_2 = X.setup_volunteer(api, program["id"], full_name="Omar Vance", birth_date="1991-02-02T00:00:00.000Z")
    vol_p = X.setup_volunteer(
        api,
        program["id"],
        full_name="Pilar Sosa",
        birth_date="1987-07-07T00:00:00.000Z",
        trade_certifications=[F.certification(C.TRADE_PLUMBING)],
    )
    shift = X.setup_open_shift(
        api, site["id"], volunteer_slots=3, required_trade_slots=1, required_trade=C.TRADE_PLUMBING
    )

    seat_1 = X.reserve_volunteer_seat(api, shift["id"], vol_1["id"])
    X.confirm_seat(api, seat_1["id"], headers=make_volunteer_headers(vol_1["id"]))
    seat_2 = X.reserve_volunteer_seat(api, shift["id"], vol_2["id"])
    X.confirm_seat(api, seat_2["id"], headers=make_volunteer_headers(vol_2["id"]))

    validate_error(
        api.lock_shift(shift["id"], F.lock_payload(), headers=CREW_LEAD),
        E.ERR_TRADE_COVERAGE_INSUFFICIENT,
        409,
    )
    refused = validate_success(api.get_shift(shift["id"], headers=CREW_LEAD))
    assert refused["status"] == C.SHIFT_OPEN
    assert refused["safety_briefing_completed"] is False

    trade_seat = X.reserve_volunteer_seat(api, shift["id"], vol_p["id"], role=C.SEAT_SKILLED_TRADE)
    confirmed = validate_success(api.confirm_assignment(trade_seat["id"], headers=make_volunteer_headers(vol_p["id"])))
    assert confirmed["role"] == C.SEAT_SKILLED_TRADE
    assert confirmed["status"] == C.ASSIGNMENT_CONFIRMED

    locked = validate_success(api.lock_shift(shift["id"], F.lock_payload(), headers=CREW_LEAD))
    assert locked["status"] == C.SHIFT_LOCKED
    assert locked["safety_briefing_completed"] is True

    site_after = validate_success(api.get_build_site(site["id"], headers=CREW_LEAD))
    assert site_after["readiness_status"] == C.SITE_UNDER_CONSTRUCTION


def test_a_held_site_refuses_a_new_shift_until_the_posture_clears(api):
    """The gate is the parent site's field, not anything in the request.

    "While a site is on hold, its `safety_posture` of `HOLD` blocks six
    construction operations — scheduling a shift, opening one, locking one,
    reserving a seat, confirming a seat, and checking a seat in — each with
    `ERR_SITE_UNDER_SAFETY_HOLD`."

    Design: Corner/validations/a_safety_hold_bars_new_shifts_until_the_posture_clears
    """
    program = X.setup_program(api)
    site = X.setup_ready_site(api, program["id"])
    validate_success(
        api.set_safety_posture(
            site["id"],
            F.safety_posture_payload(
                C.POSTURE_HOLD, incident_note="Trench wall collapse, site closed pending inspection"
            ),
            headers=CREW_LEAD,
        )
    )

    payload = F.shift_payload(site["id"], volunteer_slots=3)
    validate_error(api.create_shift(payload, headers=CREW_LEAD), E.ERR_SITE_UNDER_SAFETY_HOLD, 409)

    _, meta = validate_paginated(api.list_shifts({"build_site_id": site["id"]}, headers=CREW_LEAD))
    assert meta["total_count"] == 0

    released = validate_success(
        api.set_safety_posture(
            site["id"],
            F.safety_posture_payload(C.POSTURE_CLEAR, incident_note="Inspection passed, trench reshored"),
            headers=CREW_LEAD,
        )
    )
    assert released["readiness_status"] == C.SITE_READY_TO_BUILD
    assert released["safety_posture"] == C.POSTURE_CLEAR
    assert released["pre_hold_readiness_status"] is None

    accepted = validate_success(api.create_shift(payload, headers=CREW_LEAD), 201)
    assert accepted["status"] == C.SHIFT_SCHEDULED
    assert accepted["duration_hours"] == 4.0


def test_the_readiness_gate_binds_at_opening_not_at_scheduling(api):
    """A shift schedules on an ENV_CLEARED site but will not open on one.

    "Opening a shift moves it `SCHEDULED → OPEN` and makes it visible for
    sign-ups. The site must be in `READY_TO_BUILD` or `UNDER_CONSTRUCTION`
    readiness, or the request is refused with `ERR_SITE_NOT_READY_TO_BUILD`."

    Design: Corner/validations/a_shift_cannot_open_on_a_site_short_of_utilities_clearance
    """
    program = X.setup_program(api)
    site = X.setup_env_cleared_site(api, program["id"])
    shift = X.setup_shift(api, site["id"], volunteer_slots=3)
    assert shift["status"] == C.SHIFT_SCHEDULED
    created_version = shift["version"]

    validate_error(api.open_shift(shift["id"], headers=CREW_LEAD), E.ERR_SITE_NOT_READY_TO_BUILD, 409)

    unchanged = validate_success(api.get_shift(shift["id"], headers=CREW_LEAD))
    assert unchanged["status"] == C.SHIFT_SCHEDULED
    assert unchanged["version"] == created_version

    advanced = validate_success(
        api.advance_readiness(site["id"], F.readiness_payload(C.STEP_UTILITIES), headers=ADMIN)
    )
    assert advanced["readiness_status"] == C.SITE_READY_TO_BUILD
    assert advanced["utilities_cleared"] is True

    opened = validate_success(api.open_shift(shift["id"], headers=CREW_LEAD))
    assert opened["status"] == C.SHIFT_OPEN


def test_a_shift_needs_a_seat_and_a_named_trade_to_be_scheduled_at_all(api):
    """Two declaration rules stop a shift nobody can work.

    "Two declaration rules apply at scheduling and again at opening: the shift
    must offer at least one seat in total across general and trade capacity, and
    `required_trade_slots` may not exceed `volunteer_slots` — either failure is
    `ERR_SHIFT_HAS_NO_SLOTS`. And the trade declaration must be coherent: one or
    more trade slots with no `required_trade` named, or a `required_trade` named
    alongside zero trade slots, is `ERR_REQUIRED_TRADE_MISSING`."

    Design: Corner/validations/shift_seat_shape_rejects_zero_seats_and_an_unnamed_trade
    """
    program = X.setup_program(api)
    site = X.setup_ready_site(api, program["id"])

    validate_error(
        api.create_shift(
            F.shift_payload(site["id"], volunteer_slots=0, required_trade_slots=0), headers=CREW_LEAD
        ),
        E.ERR_SHIFT_HAS_NO_SLOTS,
        422,
    )
    validate_error(
        api.create_shift(
            F.shift_payload(site["id"], volunteer_slots=4, required_trade_slots=2), headers=CREW_LEAD
        ),
        E.ERR_REQUIRED_TRADE_MISSING,
        422,
    )

    accepted = validate_success(
        api.create_shift(
            F.shift_payload(
                site["id"], volunteer_slots=4, required_trade_slots=2, required_trade=C.TRADE_PLUMBING
            ),
            headers=CREW_LEAD,
        ),
        201,
    )
    assert accepted["status"] == C.SHIFT_SCHEDULED
    assert accepted["volunteer_slots"] == 4
    assert accepted["required_trade_slots"] == 2
    assert accepted["required_trade"] == C.TRADE_PLUMBING

    _, meta = validate_paginated(api.list_shifts({"build_site_id": site["id"]}, headers=CREW_LEAD))
    assert meta["total_count"] == 1


def test_check_in_and_completion_both_wait_on_the_logical_clock(api):
    """Neither the seat nor the shift may run ahead of the clock.

    "The parent shift must be `LOCKED` with `safety_briefing_completed` true, the
    site's posture must be `CLEAR`, and the clock must sit at or after 30 minutes
    before `start_at` and strictly before `end_at`; outside that window the
    check-in is refused with `ERR_CHECK_IN_WINDOW_CLOSED`." Completion in turn
    "requires the logical clock to have reached `end_at` — equality completes, and
    anything earlier is refused with `ERR_SHIFT_NOT_ENDED`."

    Design: Corner/validations/check_in_before_the_window_and_completion_before_the_end_are_refused
    """
    program = X.setup_program(api)
    site = X.setup_ready_site(api, program["id"])
    volunteer = X.setup_volunteer(api, program["id"], full_name="Dana Reyes")
    shift = X.setup_open_shift(api, site["id"], volunteer_slots=1)
    seat = X.reserve_volunteer_seat(api, shift["id"], volunteer["id"])
    X.confirm_seat(api, seat["id"], headers=make_volunteer_headers(volunteer["id"]))
    X.lock_shift(api, shift["id"])

    validate_error(
        api.check_in_assignment(seat["id"], headers=CREW_LEAD), E.ERR_CHECK_IN_WINDOW_CLOSED, 409
    )
    validate_error(
        api.complete_shift(
            shift["id"], F.completion_payload(completion_note="Premature close attempt"), headers=CREW_LEAD
        ),
        E.ERR_SHIFT_NOT_ENDED,
        409,
    )
    still_confirmed = validate_success(api.get_assignment(seat["id"], headers=CREW_LEAD))
    assert still_confirmed["status"] == C.ASSIGNMENT_CONFIRMED
    assert still_confirmed["checked_in_at"] is None

    X.advance_clock(api, "2026-08-05T08:00:00.000Z")
    checked_in = validate_success(api.check_in_assignment(seat["id"], headers=CREW_LEAD))
    assert checked_in["status"] == C.ASSIGNMENT_CHECKED_IN
    assert checked_in["checked_in_at"] == "2026-08-05T08:00:00.000Z"

    X.advance_clock(api, "2026-08-05T12:00:00.000Z")
    completed = validate_success(
        api.complete_shift(
            shift["id"], F.completion_payload(completion_note="Shift finished on schedule"), headers=CREW_LEAD
        )
    )
    assert completed["status"] == C.SHIFT_COMPLETED
    assert validate_success(api.get_assignment(seat["id"], headers=CREW_LEAD))["status"] == C.ASSIGNMENT_COMPLETED
