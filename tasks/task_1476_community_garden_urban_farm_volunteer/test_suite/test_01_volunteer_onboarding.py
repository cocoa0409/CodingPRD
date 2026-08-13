"""Volunteer registration, orientation/waiver/standing dimensions, and the
suspension cascade (PRD §3.1, §2.8)."""
from test_helpers import (
    ApiErrorId,
    assert_shift_signup,
    assert_volunteer,
    create_volunteer_payload,
    make_admin_headers,
    make_confirmed_signup,
    make_open_slot,
    make_participating_volunteer,
    make_signup_request,
    make_volunteer_headers,
    setup_full_slot_with_waitlist,
    setup_season_open,
    validate_error,
    validate_success,
)


def test_volunteer_registration_defaults_and_computed_minor_flag(api):
    """PRD §3.1: "Every new volunteer begins with `orientation_status` `PENDING`,
    `waiver_status` `UNSIGNED`, `waiver_signed_at` null, and `standing` `GOOD`."
    PRD §3.1: "At registration the server derives `is_minor` from `date_of_birth`
    against the current logical clock: the flag is true while the volunteer's age
    is under eighteen and flips to false on the eighteenth birthday."

    Design: Corner/entities/creation_applies_defaults_and_computed_minor_flag
    """
    admin = make_admin_headers()
    adult = validate_success(
        api.create_volunteer(
            create_volunteer_payload(
                full_name="Adult", email="a@x.com", date_of_birth="1990-05-20"
            ),
            admin,
        ),
        expected_status=201,
    )
    assert_volunteer(adult)
    assert adult["orientation_status"] == "PENDING"
    assert adult["waiver_status"] == "UNSIGNED"
    assert adult["waiver_signed_at"] is None
    assert adult["standing"] == "GOOD"
    assert adult["is_minor"] is False, "age 36 at the 2026-08-01 clock is an adult"
    assert adult["total_service_minutes"] == 0
    assert adult["no_show_count"] == 0
    assert adult["held_key_count"] == 0

    teen = validate_success(
        api.create_volunteer(
            create_volunteer_payload(
                full_name="Teen", email="t@x.com", date_of_birth="2012-03-01"
            ),
            admin,
        ),
        expected_status=201,
    )
    assert teen["is_minor"] is True, "age 14 at the 2026-08-01 clock is a minor"


def test_minor_flag_flips_on_eighteenth_birthday(api):
    """PRD §3.1: "At registration the server derives `is_minor` from `date_of_birth`
    against the current logical clock: the flag is true while the volunteer's age
    is under eighteen and flips to false on the eighteenth birthday."

    Design: Corner/entities/minor_flag_flips_on_eighteenth_birthday
    """
    admin = make_admin_headers()
    validate_success(api.set_clock({"to_iso8601": "2026-08-13T00:00:00Z"}, admin))
    vol = validate_success(
        api.create_volunteer(
            create_volunteer_payload(
                full_name="Bday", email="b@x.com", date_of_birth="2008-08-14"
            ),
            admin,
        ),
        expected_status=201,
    )
    assert vol["is_minor"] is True, "17y364d at 2026-08-13 is still a minor"
    validate_success(api.set_clock({"to_iso8601": "2026-08-14T00:00:00Z"}, admin))
    reread = validate_success(api.get_volunteer(vol["id"], admin))
    assert_volunteer(reread)
    assert reread["is_minor"] is False, "the flag flips to false on the 18th birthday"


def test_volunteer_dimensions_initially_independent(api):
    """PRD §3.1: "Every new volunteer begins with `orientation_status` `PENDING`,
    `waiver_status` `UNSIGNED`, `waiver_signed_at` null, and `standing` `GOOD`."
    PRD §3.1: "A `GardenAdmin` or `Coordinator` marks orientation completed, moving
    `orientation_status` from `PENDING` to `ORIENTED`".

    Design: Difficulty/non_linear_state_machine/volunteer_three_parallel_dimensions
    """
    admin = make_admin_headers()
    vol = validate_success(
        api.create_volunteer(
            create_volunteer_payload(
                full_name="Teen", email="teen@x.com", date_of_birth="2012-03-01"
            ),
            admin,
        ),
        expected_status=201,
    )
    assert vol["is_minor"] is True
    assert vol["orientation_status"] == "PENDING"
    assert vol["waiver_status"] == "UNSIGNED"
    assert vol["standing"] == "GOOD"

    validate_success(api.complete_orientation(vol["id"], admin))
    mid = validate_success(api.get_volunteer(vol["id"], admin))
    assert mid["orientation_status"] == "ORIENTED"
    assert mid["waiver_status"] == "UNSIGNED", "orientation must not touch the waiver dimension"
    assert mid["standing"] == "GOOD", "orientation must not touch the standing dimension"


def test_volunteer_reorientation_rejected_and_dimensions_move_independently(api):
    """PRD §3.1: "Orientation is a one-way door. A `GardenAdmin` or `Coordinator`
    marks orientation completed, moving `orientation_status` from `PENDING` to
    `ORIENTED`; invoking the completion on a volunteer who is already `ORIENTED`
    is rejected with `ERR_INVALID_VOLUNTEER_STATE`."
    PRD §3.1: "A volunteer in `GOOD` standing may be moved to `PROBATION` or
    directly to `SUSPENDED`".

    Design: Difficulty/non_linear_state_machine/volunteer_three_parallel_dimensions
    """
    admin = make_admin_headers()
    vol = make_participating_volunteer()

    err = validate_error(
        api.complete_orientation(vol["id"], admin), ApiErrorId.ERR_INVALID_VOLUNTEER_STATE
    )
    assert err["error_id"] == "ERR_INVALID_VOLUNTEER_STATE"

    validate_success(api.set_standing(vol["id"], {"to_state": "PROBATION"}, admin))
    final = validate_success(api.get_volunteer(vol["id"], admin))
    assert final["orientation_status"] == "ORIENTED"
    assert final["waiver_status"] == "SIGNED"
    assert final["standing"] == "PROBATION"


def test_waiver_expiry_blocks_signup_until_renewed(api):
    """PRD §3.1: "A waiver does not last forever: once the logical clock passes
    `waiver_signed_at` by more than 365 days, the next scheduler epoch run moves
    `waiver_status` from `SIGNED` to `EXPIRED`, and the volunteer must renew before
    participating again."
    PRD §2.8: "then `waiver_status` must be `SIGNED` (otherwise `ERR_WAIVER_REQUIRED`,
    which covers both `UNSIGNED` and `EXPIRED`)".

    Design: Corner/state_machines/waiver_expiry_blocks_signup_until_renewed
    """
    admin = make_admin_headers()
    vol = make_participating_volunteer()
    assert vol["waiver_status"] == "SIGNED", "signed at the 2026-08-01 default clock"

    season, _bed = setup_season_open(
        name="2026-27 Extended",
        signup_closes_at="2027-08-10T00:00:00Z",
        season_ends_at="2027-11-30T00:00:00Z",
    )
    slot = make_open_slot(
        season["id"],
        capacity_total=3,
        capacity_youth=1,
        starts_at="2027-08-20T09:00:00Z",
        ends_at="2027-08-20T12:00:00Z",
    )

    # More than 365 days past the 2026-08-01 signature: the epoch expires the waiver.
    validate_success(api.set_clock({"to_iso8601": "2027-08-05T00:00:00Z"}, admin))
    validate_success(api.run_epoch(admin))
    expired = validate_success(api.get_volunteer(vol["id"], admin))
    assert expired["waiver_status"] == "EXPIRED"

    err = validate_error(
        api.create_shift_signup(
            {"slot_id": slot["id"], "volunteer_id": vol["id"]},
            make_volunteer_headers(vol["id"]),
        ),
        ApiErrorId.ERR_WAIVER_REQUIRED,
    )
    assert err["error_id"] == "ERR_WAIVER_REQUIRED"

    # Renewal: the same signing action serves EXPIRED -> SIGNED.
    renewed = validate_success(api.sign_waiver(vol["id"], make_volunteer_headers(vol["id"])))
    assert renewed["waiver_status"] == "SIGNED"
    signup = validate_success(
        api.create_shift_signup(
            {"slot_id": slot["id"], "volunteer_id": vol["id"]},
            make_volunteer_headers(vol["id"]),
        ),
        expected_status=201,
    )
    assert_shift_signup(signup)
    assert signup["status"] == "REQUESTED"


def test_volunteer_suspension_cancels_signup_and_promotes_waitlist(api):
    """PRD §3.1: "Moving a volunteer to `SUSPENDED` cancels every one of their
    shift signups currently in `REQUESTED` or `CONFIRMED`. For each cancelled
    signup that had been `CONFIRMED`, the freed spot triggers the waitlist
    promotion selection on that slot (§3.5): the earliest-positioned `WAITLISTED`
    signup that fits both occupancy pools is promoted to `CONFIRMED`, and a `FULL`
    slot that yields no eligible candidate reopens to `OPEN` — flipping back to
    `FULL` if a promotion fills the freed spot."

    Design: Difficulty/transitive_cascade/volunteer_suspend_cancels_signup_promotes_waitlist
    """
    admin = make_admin_headers()
    ctx = setup_full_slot_with_waitlist(capacity_total=2, capacity_youth=1)
    slot = ctx["slot"]
    s1, s2 = ctx["confirmed"]
    s3 = ctx["waitlisted"]
    assert s3["status"] == "WAITLISTED" and s3["waitlist_position"] == 1
    assert slot["status"] == "FULL" and slot["confirmed_count"] == 2

    suspended = validate_success(
        api.set_standing(s1["volunteer_id"], {"to_state": "SUSPENDED"}, admin)
    )
    assert suspended["standing"] == "SUSPENDED"

    cancelled = validate_success(api.get_shift_signup(s1["id"], admin))
    assert cancelled["status"] == "CANCELLED", "link 1: the suspended volunteer's CONFIRMED signup cancels"

    promoted = validate_success(api.get_shift_signup(s3["id"], admin))
    assert promoted["status"] == "CONFIRMED", "link 2: the freed spot promotes the waitlisted signup"
    assert promoted["waitlist_position"] is None

    untouched = validate_success(api.get_shift_signup(s2["id"], admin))
    assert untouched["status"] == "CONFIRMED", "the other volunteer's signup is unaffected"

    slot_after = validate_success(api.get_shift_slot(slot["id"], admin))
    assert slot_after["confirmed_count"] == 2
    assert slot_after["status"] == "FULL", "the promotion refilled the freed spot"


def test_volunteer_suspension_cancels_requested_signup_without_penalty(api):
    """PRD §3.1: "Moving a volunteer to `SUSPENDED` cancels every one of their
    shift signups currently in `REQUESTED` or `CONFIRMED`."
    PRD §3.1: "Signups cancelled by this cascade carry no no-show penalty."
    PRD §3.1: "For each cancelled signup that had been `CONFIRMED`, the freed spot
    triggers the waitlist promotion selection on that slot (§3.5)".

    Design: Difficulty/transitive_cascade/volunteer_suspend_cancels_signup_promotes_waitlist
    """
    admin = make_admin_headers()
    season, _bed = setup_season_open()
    slot = make_open_slot(season["id"], capacity_total=3, capacity_youth=1)
    v1 = make_participating_volunteer()
    v2 = make_participating_volunteer()
    s1 = make_signup_request(slot["id"], v1["id"])  # REQUESTED occupies no spot
    s2 = make_confirmed_signup(slot["id"], v2["id"])

    validate_success(api.set_standing(v1["id"], {"to_state": "SUSPENDED"}, admin))

    s1_after = validate_success(api.get_shift_signup(s1["id"], admin))
    assert s1_after["status"] == "CANCELLED", "REQUESTED signups cancel too"
    s2_after = validate_success(api.get_shift_signup(s2["id"], admin))
    assert s2_after["status"] == "CONFIRMED", "another volunteer is untouched"
    slot_after = validate_success(api.get_shift_slot(slot["id"], admin))
    assert slot_after["confirmed_count"] == 1, "a REQUESTED signup freed nothing"
    assert slot_after["status"] == "OPEN"
    v1_after = validate_success(api.get_volunteer(v1["id"], admin))
    assert v1_after["no_show_count"] == 0, "the cascade carries no no-show penalty"
