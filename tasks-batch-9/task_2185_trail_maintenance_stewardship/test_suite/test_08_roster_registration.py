"""Putting volunteers on a roster: waivers, certifications, intervals, capacity."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_extra_party,
    assert_volunteer_shift,
    create_party,
    party_version,
    read_party,
    read_volunteer,
    register_volunteer_on_party,
    setup_briefed_party,
    setup_issued_permit,
    setup_party_with_sawyer,
    setup_second_adopted_segment,
    setup_started_party,
    make_volunteer_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

COORD = TEST_USERS["coordinator_headers"]


def _two_segment_day():
    """Milo booked 09:00-15:00 on Alder Creek and 15:00-19:00 on Bear Hollow."""
    world = setup_issued_permit()
    party_a = create_party(
        world["plan_id"], world["seg_id"], world["lead_id"], world["permit_id"]
    )
    world["pa_id"] = party_a["id"]
    register_volunteer_on_party(
        party_a["id"], world["lead_id"], world["saw_id"], role_on_crew="SAWYER"
    )

    setup_second_adopted_segment(world)
    for key, start_at, end_at in (
        ("pb", "2026-09-05T15:00:00.000Z", "2026-09-05T19:00:00.000Z"),
        ("pc", "2026-09-05T14:00:00.000Z", "2026-09-05T18:00:00.000Z"),
        ("pd", "2026-09-05T19:00:00.000Z", "2026-09-05T20:30:00.000Z"),
    ):
        add_extra_party(
            world,
            key=key,
            start_at=start_at,
            end_at=end_at,
            plan_id=world["plan2_id"],
            segment_id=world["seg2_id"],
            permit_id=world["permit2_id"],
            brief=False,
            work_type="BRUSHING",
            travel_allowance_minutes=0,
        )
    return world


def test_touching_intervals_and_an_exactly_ten_hour_day_are_admitted(api):
    """PRD 3.7: "The registration conflicts when the new party's interval and an existing party's interval satisfy both conditions: the new party's `start_at` is strictly earlier than the other party's `end_at`, and the other party's `start_at` is strictly earlier than the new party's `end_at`."
    PRD 3.7: "A new party starting at the exact instant an existing one ends is therefore accepted. A genuine conflict is refused with `ERR_VOLUNTEER_DOUBLE_BOOKED`."
    PRD 3.7: "The comparison is inclusive, so a total landing on exactly 10.0 hours is accepted; anything above it is refused with `ERR_VOLUNTEER_DAILY_HOURS_EXCEEDED`."
    PRD 3.7: "The shift is created in `REGISTERED`, the party's `version` advances by 1, `registered_count` and `first_aid_capable_count` are recomputed, and the volunteer's `active_registration_count` rises by 1."

    Design: Difficulty/resource_temporal_overlap/volunteer_double_booking_uses_zero_buffer_closed_intervals_plus_daily_cap
    """
    world = _two_segment_day()

    shift_b = validate_success(
        api.register_shift(
            world["pb_id"],
            {
                "volunteer_id": world["saw_id"],
                "expected_work_party_version": party_version(world["pb_id"]),
                "role_on_crew": "CREW_MEMBER",
            },
            world["lead_headers"],
        ),
        201,
    )
    assert_volunteer_shift(shift_b)
    assert shift_b["status"] == "REGISTERED"
    assert read_volunteer(world["saw_id"])["active_registration_count"] == 2


def test_overlapping_interval_and_daily_ceiling_raise_their_own_distinct_errors(api):
    """PRD 3.7: "A volunteer's commitments are treated as closed intervals with **zero** buffer, so touching endpoints are allowed."
    PRD 3.7: "A new party starting at the exact instant an existing one ends is therefore accepted. A genuine conflict is refused with `ERR_VOLUNTEER_DOUBLE_BOOKED`."
    PRD 3.7: "Take the scheduled duration — `end_at` minus `start_at` — of every shift that volunteer holds in `REGISTERED`, `CHECKED_IN` or `CHECKED_OUT` on **other** work parties whose party `start_at` falls on the same UTC calendar day as the new party's `start_at`, add the new party's own duration, and the total must not exceed ten hours."
    PRD 3.7: "The comparison is inclusive, so a total landing on exactly 10.0 hours is accepted; anything above it is refused with `ERR_VOLUNTEER_DAILY_HOURS_EXCEEDED`."

    Design: Difficulty/resource_temporal_overlap/volunteer_double_booking_uses_zero_buffer_closed_intervals_plus_daily_cap
    """
    world = _two_segment_day()
    validate_success(
        api.register_shift(
            world["pb_id"],
            {
                "volunteer_id": world["saw_id"],
                "expected_work_party_version": party_version(world["pb_id"]),
                "role_on_crew": "CREW_MEMBER",
            },
            world["lead_headers"],
        ),
        201,
    )

    overlap = api.register_shift(
        world["pc_id"],
        {
            "volunteer_id": world["saw_id"],
            "expected_work_party_version": party_version(world["pc_id"]),
            "role_on_crew": "CREW_MEMBER",
        },
        world["lead_headers"],
    )
    validate_error(overlap, ApiErrorId.ERR_VOLUNTEER_DOUBLE_BOOKED.value, 409)

    over_cap = api.register_shift(
        world["pd_id"],
        {
            "volunteer_id": world["saw_id"],
            "expected_work_party_version": party_version(world["pd_id"]),
            "role_on_crew": "CREW_MEMBER",
        },
        world["lead_headers"],
    )
    error_data = validate_error(
        over_cap, ApiErrorId.ERR_VOLUNTEER_DAILY_HOURS_EXCEEDED.value, 422
    )
    assert error_data["error_id"] != ApiErrorId.ERR_VOLUNTEER_DOUBLE_BOOKED.value

    assert read_party(world["pc_id"])["registered_count"] == 0
    assert read_party(world["pd_id"])["registered_count"] == 0


def test_a_full_roster_refuses_the_next_registration(api):
    """PRD 3.7: "The party's `registered_count` must be strictly below its `roster_capacity`, which as described above is the smaller of `max_participants` and the issued permit's `max_party_size` when a permit is referenced and simply `max_participants` otherwise; a full roster is refused with `ERR_ROSTER_FULL`."

    Design: Corner/validations/roster_full_rejects_the_next_registration
    """
    world = setup_party_with_sawyer(party_overrides={"max_participants": 1})

    response = api.register_shift(
        world["party_id"],
        {
            "volunteer_id": world["gen_id"],
            "expected_work_party_version": party_version(world["party_id"]),
            "role_on_crew": "CREW_MEMBER",
        },
        world["lead_headers"],
    )
    validate_error(response, ApiErrorId.ERR_ROSTER_FULL.value, 409)

    party = read_party(world["party_id"])
    assert party["roster_capacity"] == 1
    assert party["registered_count"] == 1
    assert read_volunteer(world["gen_id"])["active_registration_count"] == 0


def test_repeat_registration_on_the_same_party_is_a_duplicate_not_a_double_booking(api):
    """PRD 3.7: "And no existing shift may already pair the same `work_party_id` and `volunteer_id` in any status other than `WITHDRAWN` or `NO_SHOW`; a repeat is refused with `ERR_DUPLICATE_REGISTRATION`."
    PRD 3.7: "The comparison ranges over that volunteer's shifts in `REGISTERED`, `CHECKED_IN` or `CHECKED_OUT` that belong to a **different** `work_party_id`; shifts on the party being registered for are excluded on purpose, so that a repeat registration surfaces as a duplicate rather than as a self-overlap."

    Design: Corner/validations/repeat_registration_on_same_party_is_duplicate_not_double_booking
    """
    world = setup_party_with_sawyer()

    response = api.register_shift(
        world["party_id"],
        {
            "volunteer_id": world["saw_id"],
            "expected_work_party_version": party_version(world["party_id"]),
            "role_on_crew": "SAWYER",
        },
        world["lead_headers"],
    )
    error_data = validate_error(
        response, ApiErrorId.ERR_DUPLICATE_REGISTRATION.value, 409
    )
    assert error_data["error_id"] != ApiErrorId.ERR_VOLUNTEER_DOUBLE_BOOKED.value
    assert error_data["error_id"] != ApiErrorId.ERR_VOLUNTEER_DAILY_HOURS_EXCEEDED.value
    assert read_party(world["party_id"])["registered_count"] == 1


def test_registration_without_the_required_certification_is_refused(api):
    """PRD 3.7: "Then certifications: the volunteer must hold every certification listed in the party's `required_certifications`, otherwise `ERR_CERTIFICATION_MISSING`."
    PRD 2.7: "Certification cover (`ERR_CERTIFICATION_MISSING`), on volunteer registration and work-party confirmation."

    Design: Corner/validations/registration_without_required_certification_is_rejected
    """
    world = setup_briefed_party(
        party_overrides={
            "work_type": "CHAINSAW",
            "travel_allowance_minutes": 0,
            "required_certifications": ["CERT_SAWYER_B"],
        }
    )

    refused = api.register_shift(
        world["party_id"],
        {
            "volunteer_id": world["gen_id"],
            "expected_work_party_version": party_version(world["party_id"]),
            "role_on_crew": "CREW_MEMBER",
        },
        world["lead_headers"],
    )
    validate_error(refused, ApiErrorId.ERR_CERTIFICATION_MISSING.value, 422)

    admitted = validate_success(
        api.register_shift(
            world["party_id"],
            {
                "volunteer_id": world["saw_id"],
                "expected_work_party_version": party_version(world["party_id"]),
                "role_on_crew": "SAWYER",
            },
            world["lead_headers"],
        ),
        201,
    )
    assert admitted["status"] == "REGISTERED"
    assert read_party(world["party_id"])["registered_count"] == 1


def test_registration_without_a_signed_waiver_is_refused(api):
    """PRD 3.7: "The volunteer's own paperwork comes first: `waiver_signed_on` must be non-null and `waiver_expires_on` must be on or after the logical clock date, otherwise `ERR_WAIVER_NOT_SIGNED`."
    PRD 3.1: "Liability paperwork is captured as `waiver_signed_on`, a `YYYY-MM-DD` date that is null when the volunteer has never signed; from it the server derives `waiver_expires_on` as the day exactly 365 days after `waiver_signed_on`, likewise formatted `YYYY-MM-DD` and likewise null when nothing has been signed."

    Design: Corner/validations/registration_without_a_signed_waiver_is_rejected
    """
    world = setup_briefed_party()
    unsigned = validate_success(
        api.create_volunteer(
            {"full_name": "Owen Blake", "email": "owen@example.org"}, COORD
        ),
        201,
    )
    assert unsigned["waiver_expires_on"] is None

    response = api.register_shift(
        world["party_id"],
        {
            "volunteer_id": unsigned["id"],
            "expected_work_party_version": party_version(world["party_id"]),
            "role_on_crew": "CREW_MEMBER",
        },
        world["lead_headers"],
    )
    validate_error(response, ApiErrorId.ERR_WAIVER_NOT_SIGNED.value, 422)
    assert read_party(world["party_id"])["registered_count"] == 0


def test_checking_a_shift_in_twice_is_refused(api):
    """PRD 3.7: "A shift moves `REGISTERED → CHECKED_IN` while the party's `schedule_status` is `IN_PROGRESS`, performed either by a `CrewLeader` or by the volunteer themselves — a `Volunteer` may only check in their own shift, meaning the acting `X-User-ID` equals the shift's `volunteer_id`."
    PRD 3.7: "Check-in stamps `checked_in_at` with the logical clock and raises the party's `checked_in_count` by 1."
    PRD 2.7: "State legality — the target resource currently sits in a state from which the requested transition is declared, terminal states included, otherwise `ERR_INVALID_STATE` (HTTP 409)."

    Design: Corner/state_machines/shift_check_in_twice_is_rejected
    """
    world = setup_started_party()

    first = validate_success(
        api.check_in_shift(world["shift_saw_id"], world["lead_headers"])
    )
    assert first["status"] == "CHECKED_IN"
    assert first["checked_in_at"] == "2026-09-05T09:00:00.000Z"

    second = api.check_in_shift(world["shift_saw_id"], world["lead_headers"])
    validate_error(second, ApiErrorId.ERR_INVALID_STATE.value, 409)

    assert read_party(world["party_id"])["checked_in_count"] == 1


def test_withdrawal_reconciles_every_denormalised_roster_counter(api):
    """PRD 3.7: "A registration may also be abandoned: a `Volunteer` acting on their own shift, or a `CrewLeader`, may move a shift `REGISTERED → WITHDRAWN` with an optional `reason` at any time before the party reaches `COMPLETED`, which drops both the party's `registered_count` and the volunteer's `active_registration_count` by 1 and recomputes `first_aid_capable_count`."

    Design: Corner/cross_cutting_complexity_layers/roster_counters_reconcile_after_a_withdrawal
    """
    world = setup_party_with_sawyer()
    register_volunteer_on_party(
        world["party_id"], world["lead_id"], world["gen_id"], role_on_crew="CREW_MEMBER"
    )

    before = read_party(world["party_id"])
    assert before["registered_count"] == 2
    assert before["first_aid_capable_count"] == 1

    withdrawn = validate_success(
        api.withdraw_shift(
            world["shift_saw_id"],
            make_volunteer_headers(world["saw_id"]),
            {"reason": "Family emergency."},
        )
    )
    assert withdrawn["status"] == "WITHDRAWN"

    after = read_party(world["party_id"])
    assert after["registered_count"] == 1
    assert after["first_aid_capable_count"] == 0
    assert read_volunteer(world["saw_id"])["active_registration_count"] == 0
    assert read_volunteer(world["gen_id"])["active_registration_count"] == 1


def test_shift_listing_is_filterable_by_volunteer_and_by_work_party(api):
    """PRD 3.7: "Shift listings may be narrowed by `work_party_id`, by `volunteer_id` and by `status`."
    PRD 2.2: "The `response_type` is either "object" for a single resource or "array" for a list of resources."

    Design: Corner/endpoints/shifts_filtered_list_is_the_reverse_reachability_channel_for_volunteer
    """
    world = setup_party_with_sawyer()
    register_volunteer_on_party(
        world["party_id"], world["lead_id"], world["gen_id"], role_on_crew="CREW_MEMBER"
    )

    by_volunteer_response = api.list_shifts(
        COORD, params={"volunteer_id": world["saw_id"]}
    )
    by_volunteer, _ = validate_paginated(by_volunteer_response)
    assert len(by_volunteer) == 1
    assert by_volunteer[0]["id"] == world["shift_saw_id"]
    assert by_volunteer_response.json()["response_type"] == "array"

    roster_response = api.list_shifts(
        COORD, params={"work_party_id": world["party_id"], "limit": 10, "offset": 0}
    )
    roster, meta = validate_paginated(roster_response)
    assert len(roster) == 2
    assert meta["total_count"] == 2
    assert meta["has_more"] is False
    assert roster_response.json()["response_type"] == "array"
