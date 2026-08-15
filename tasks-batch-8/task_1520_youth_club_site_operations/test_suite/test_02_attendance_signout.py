"""Club-day sign-in gates, sign-out authorization, and attendance tallies."""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_attendance_tally,
    assign_ride,
    close_day,
    create_active_member,
    create_guardian,
    create_route,
    director_headers,
    get_club_day,
    get_member,
    open_club_day,
    set_logical_clock,
    setup_site_with_director,
    sign_in_member,
    suspend_member_now,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]


def _site_with_active_members(api, names, walker_ok=False):
    site, director = setup_site_with_director(clock="2026-08-03T09:00:00Z")
    members = [
        create_active_member(site["id"], director["id"], legal_name=n,
                             walker_ok=walker_ok)
        for n in names
    ]
    return site, director, members


def test_signin_suspended_member_rejected(api):
    """PRD 3.4: "the member must be `ACTIVE`, which is how suspensions
    physically bar entry (`ERR_MEMBER_NOT_ACTIVE`)".

    Design: Corner/validations/c_signin_suspended_member_rejected
    """
    site, director = setup_site_with_director(clock="2026-08-03T09:00:00Z")
    member = create_active_member(site["id"], director["id"], legal_name="Kid A")
    day = open_club_day(site["id"], director["id"], "2026-08-03")
    suspend_member_now(member["id"], director["id"], "2026-08-03",
                       suspension_days=1, category="LEVEL_1")
    assert get_member(member["id"])["status"] == "SUSPENDED"
    res = api.create_attendance_record(
        {"club_day_id": day["id"], "member_id": member["id"]},
        director_headers(director),
    )
    validate_error(res, ApiErrorId.ERR_MEMBER_NOT_ACTIVE, expected_status=409)
    data, meta = validate_paginated(api.list_day_attendance(day["id"], ADMIN))
    assert meta["total_count"] == 0


def test_signin_on_closed_day_rejected(api):
    """PRD 3.4: "the day must be `OPEN` (`ERR_CLUB_DAY_NOT_OPEN`)".

    Design: Corner/validations/c_signin_on_closed_day_rejected
    """
    site, director = setup_site_with_director(clock="2026-08-03T09:00:00Z")
    member = create_active_member(site["id"], director["id"], legal_name="Kid A")
    day = open_club_day(site["id"], director["id"], "2026-08-03")
    close_day(day["id"], director["id"])
    res = api.create_attendance_record(
        {"club_day_id": day["id"], "member_id": member["id"]},
        director_headers(director),
    )
    validate_error(res, ApiErrorId.ERR_CLUB_DAY_NOT_OPEN, expected_status=409)


def test_signin_wrong_day_rejected(api):
    """PRD 3.4: "the day's date must equal logical today (`ERR_DAY_NOT_TODAY`)".

    Design: Corner/validations/c_signin_wrong_day_rejected
    """
    site, director = setup_site_with_director(clock="2026-08-03T09:00:00Z")
    member = create_active_member(site["id"], director["id"], legal_name="Kid A")
    day = open_club_day(site["id"], director["id"], "2026-08-03")
    set_logical_clock("2026-08-04T09:00:00Z")
    res = api.create_attendance_record(
        {"club_day_id": day["id"], "member_id": member["id"]},
        director_headers(director),
    )
    validate_error(res, ApiErrorId.ERR_DAY_NOT_TODAY, expected_status=409)
    assert get_club_day(day["id"])["status"] == "OPEN"


def test_duplicate_club_day_rejected(api):
    """PRD 3.4: "the site may have only one club day per date
    (`ERR_DUPLICATE_CLUB_DAY`, 409)".

    Design: Corner/validations/c_duplicate_club_day_rejected
    """
    site, director = setup_site_with_director(clock="2026-08-03T09:00:00Z")
    open_club_day(site["id"], director["id"], "2026-08-03")
    res = api.create_club_day(
        {"site_id": site["id"], "date": "2026-08-03"},
        director_headers(director),
    )
    validate_error(res, ApiErrorId.ERR_DUPLICATE_CLUB_DAY, expected_status=409)


def test_duplicate_attendance_rejected(api):
    """PRD 3.4: "the member must not already have an attendance record on this
    day (`ERR_DUPLICATE_ATTENDANCE`)".

    Design: Corner/validations/c_duplicate_attendance_rejected
    """
    site, director, members = _site_with_active_members(api, ["Kid A"])
    day = open_club_day(site["id"], director["id"], "2026-08-03")
    sign_in_member(day["id"], members[0]["id"], director["id"])
    res = api.create_attendance_record(
        {"club_day_id": day["id"], "member_id": members[0]["id"]},
        director_headers(director),
    )
    validate_error(res, ApiErrorId.ERR_DUPLICATE_ATTENDANCE, expected_status=409)
    assert get_club_day(day["id"])["present_count"] == 1


def test_posture_over_capacity_blocks_signin(api):
    """PRD 3.4: "If `present_count` has reached the site's `youth_capacity`,
    the `posture` is `OVER_CAPACITY`. Otherwise, if the staffing count
    multiplied by the site's `standard_ratio` is strictly less than
    `present_count`, the posture is `RATIO_STRAINED`." and "the day's current
    `posture` must not be `OVER_CAPACITY`, evaluated before the new record is
    created (`ERR_OVER_CAPACITY`)".

    Design: Corner/calculations/c_posture_over_capacity_blocks_signin
    """
    site, director = setup_site_with_director(
        clock="2026-08-03T09:00:00Z", youth_capacity=2
    )
    members = [
        create_active_member(site["id"], director["id"], legal_name=n)
        for n in ("Kid A", "Kid B", "Kid C")
    ]
    day = open_club_day(site["id"], director["id"], "2026-08-03")
    hdrs = director_headers(director)
    sign_in_member(day["id"], members[0]["id"], director["id"])
    after_one = get_club_day(day["id"])
    assert after_one["posture"] == "RATIO_STRAINED", (
        "0 checked-in staff x ratio 15 = 0 < present_count 1"
    )
    sign_in_member(day["id"], members[1]["id"], director["id"])
    after_two = get_club_day(day["id"])
    assert after_two["present_count"] == 2
    assert after_two["posture"] == "OVER_CAPACITY", (
        "present_count 2 >= youth_capacity 2 (inclusive threshold)"
    )
    res = api.create_attendance_record(
        {"club_day_id": day["id"], "member_id": members[2]["id"]}, hdrs
    )
    validate_error(res, ApiErrorId.ERR_OVER_CAPACITY, expected_status=409)
    assert get_club_day(day["id"])["present_count"] == 2


def test_signout_pickup_unauthorized_and_revoked(api):
    """PRD 3.5: "`AUTHORIZED_PICKUP` requires a `pickup_name` that
    case-sensitively equals the `full_name` of an `ACTIVE` guardian of the
    member; any mismatch — including a revoked guardian or a differently cased
    spelling — is rejected with `ERR_PICKUP_NOT_AUTHORIZED` (422)."

    Design: Corner/validations/c_signout_pickup_unauthorized_and_revoked
    """
    site, director, members = _site_with_active_members(api, ["Kid A"])
    guardian = create_guardian(members[0]["id"], director["id"],
                               full_name="Jane Doe")
    day = open_club_day(site["id"], director["id"], "2026-08-03")
    record = sign_in_member(day["id"], members[0]["id"], director["id"])
    hdrs = director_headers(director)

    res = api.sign_out_attendance(
        record["id"], {"sign_out_type": "AUTHORIZED_PICKUP",
                       "pickup_name": "Jane Do"}, hdrs
    )
    validate_error(res, ApiErrorId.ERR_PICKUP_NOT_AUTHORIZED, expected_status=422)

    validate_success(api.revoke_guardian(guardian["id"], hdrs), 200)
    res = api.sign_out_attendance(
        record["id"], {"sign_out_type": "AUTHORIZED_PICKUP",
                       "pickup_name": "Jane Doe"}, hdrs
    )
    validate_error(res, ApiErrorId.ERR_PICKUP_NOT_AUTHORIZED, expected_status=422)

    data, _ = validate_paginated(api.list_day_attendance(day["id"], ADMIN))
    assert data[0]["status"] == "ON_SITE", (
        "both rejected attempts leave the record ON_SITE"
    )


def test_signout_walker_denied(api):
    """PRD 3.5: "`WALKER` requires the member's `walker_ok` flag to be true,
    otherwise `ERR_WALKER_NOT_PERMITTED` (422)."

    Design: Corner/validations/c_signout_walker_denied
    """
    site, director, members = _site_with_active_members(api, ["Kid A"])
    day = open_club_day(site["id"], director["id"], "2026-08-03")
    record = sign_in_member(day["id"], members[0]["id"], director["id"])
    res = api.sign_out_attendance(
        record["id"], {"sign_out_type": "WALKER"}, director_headers(director)
    )
    validate_error(res, ApiErrorId.ERR_WALKER_NOT_PERMITTED, expected_status=422)
    data, _ = validate_paginated(api.list_day_attendance(day["id"], ADMIN))
    assert data[0]["status"] == "ON_SITE"


def test_signout_bus_requires_covering_ride(api):
    """PRD 3.5: "`BUS` requires the member to hold an `ACTIVE` ride assignment
    whose half-open effective window covers the club day's date, otherwise
    `ERR_NO_RIDE_FOR_DATE` (422)."

    Design: Corner/validations/c_signout_bus_requires_covering_ride
    """
    site, director, members = _site_with_active_members(api, ["Kid A"])
    route = create_route(site["id"])
    day = open_club_day(site["id"], director["id"], "2026-08-03")
    record = sign_in_member(day["id"], members[0]["id"], director["id"])
    hdrs = director_headers(director)

    res = api.sign_out_attendance(record["id"], {"sign_out_type": "BUS"}, hdrs)
    validate_error(res, ApiErrorId.ERR_NO_RIDE_FOR_DATE, expected_status=422)

    assign_ride(route["id"], members[0]["id"], director["id"], "2026-08-03")
    signed_out = validate_success(
        api.sign_out_attendance(record["id"], {"sign_out_type": "BUS"}, hdrs), 200
    )
    assert signed_out["status"] == "SIGNED_OUT"
    assert signed_out["sign_out_type"] == "BUS"


def test_signout_missing_signout_returns_attendance_final(api):
    """PRD 3.5: "one swept to `MISSING_SIGNOUT` by the day close is rejected
    with `ERR_ATTENDANCE_FINAL`". PRD 3.9: "every attendance record still
    `ON_SITE` flips to `MISSING_SIGNOUT`".

    Design: Corner/state_machines/c_signout_missing_signout_returns_attendance_final
    """
    site, director, members = _site_with_active_members(api, ["Kid A"],
                                                        walker_ok=True)
    day = open_club_day(site["id"], director["id"], "2026-08-03")
    record = sign_in_member(day["id"], members[0]["id"], director["id"])
    close_day(day["id"], director["id"])
    data, _ = validate_paginated(api.list_day_attendance(day["id"], ADMIN))
    assert data[0]["status"] == "MISSING_SIGNOUT"
    res = api.sign_out_attendance(
        record["id"], {"sign_out_type": "WALKER"}, director_headers(director)
    )
    validate_error(res, ApiErrorId.ERR_ATTENDANCE_FINAL, expected_status=409)


def _setup_signed_out_via_pickup(api):
    """Member signed in then signed out via AUTHORIZED_PICKUP 'Jane Doe'."""
    site, director, members = _site_with_active_members(api, ["Kid Z"])
    create_guardian(members[0]["id"], director["id"], full_name="Jane Doe")
    day = open_club_day(site["id"], director["id"], "2026-08-03")
    record = sign_in_member(day["id"], members[0]["id"], director["id"])
    hdrs = director_headers(director)
    signed_out = validate_success(
        api.sign_out_attendance(
            record["id"],
            {"sign_out_type": "AUTHORIZED_PICKUP", "pickup_name": "Jane Doe"},
            hdrs,
        ),
        200,
    )
    return site, director, record, signed_out


def test_signout_already_signed_out_state_beats_pickup_safety(api):
    """PRD 2.8: "Every request is validated against a fixed, ten-stage
    pipeline, and the first failing stage determines the error returned." —
    target-resource state (stage 5, `ERR_ALREADY_SIGNED_OUT`) precedes
    youth-safety gates (stage 6, `ERR_PICKUP_NOT_AUTHORIZED`).

    Design: Difficulty/priority_pair_validation_conflict/signout_already_signed_out_state_beats_pickup_safety
    """
    site, director, record, signed_out = _setup_signed_out_via_pickup(api)
    res = api.sign_out_attendance(
        record["id"],
        {"sign_out_type": "AUTHORIZED_PICKUP", "pickup_name": "Nobody Here"},
        director_headers(director),
    )
    validate_error(res, ApiErrorId.ERR_ALREADY_SIGNED_OUT, expected_status=409)
    assert res.json()["data"]["error_id"] != "ERR_PICKUP_NOT_AUTHORIZED", (
        "the state error must win even though the pickup name is unauthorized"
    )


def test_signout_state_beats_safety_record_unchanged(api):
    """PRD 3.5: "The attendance record must still be `ON_SITE`: one already
    `SIGNED_OUT` is rejected with `ERR_ALREADY_SIGNED_OUT`". The rejected
    second sign-out must not mutate the record.

    Design: Difficulty/priority_pair_validation_conflict/signout_already_signed_out_state_beats_pickup_safety
    """
    site, director, record, signed_out = _setup_signed_out_via_pickup(api)
    api.sign_out_attendance(
        record["id"],
        {"sign_out_type": "AUTHORIZED_PICKUP", "pickup_name": "Nobody Here"},
        director_headers(director),
    )
    data, _ = validate_paginated(
        api.list_day_attendance(record["club_day_id"], ADMIN)
    )
    assert data[0]["status"] == "SIGNED_OUT"
    assert data[0]["sign_out_at"] == signed_out["sign_out_at"]


def _setup_three_signed_in(api):
    """Three walker members signed in on day 2026-08-03; member 1 signed out.
    Returns (site, director, day, records)."""
    site, director, members = _site_with_active_members(
        api, ["Kid One", "Kid Two", "Kid Three"], walker_ok=True
    )
    day = open_club_day(site["id"], director["id"], "2026-08-03")
    records = [sign_in_member(day["id"], m["id"], director["id"]) for m in members]
    return site, director, day, records


def test_attendance_tally_through_signin_signout(api):
    """PRD 3.4: "A successful sign-in ... raises the day's `present_count` by
    one". PRD 3.5: "A successful sign-out ... shifts one unit from the day's
    `present_count` to its `signed_out_count`".

    Design: Difficulty/compensating_invariant/attendance_tally_conservation_through_signin_signout_close
    """
    site, director, day, records = _setup_three_signed_in(api)
    after_signins = get_club_day(day["id"])
    assert after_signins["present_count"] == 3
    assert after_signins["signed_out_count"] == 0
    assert after_signins["missing_signout_count"] == 0
    assert_attendance_tally(after_signins, 3)

    hdrs = director_headers(director)
    validate_success(
        api.sign_out_attendance(records[0]["id"], {"sign_out_type": "WALKER"},
                                hdrs),
        200,
    )
    after_signout = get_club_day(day["id"])
    assert after_signout["present_count"] == 2
    assert after_signout["signed_out_count"] == 1
    assert after_signout["missing_signout_count"] == 0
    assert_attendance_tally(after_signout, 3)


def test_attendance_tally_conservation_at_close(api):
    """PRD 3.9: "every attendance record still `ON_SITE` flips to
    `MISSING_SIGNOUT`, with `present_count` falling and `missing_signout_count`
    rising by the same amount".

    Design: Difficulty/compensating_invariant/attendance_tally_conservation_through_signin_signout_close
    """
    site, director, day, records = _setup_three_signed_in(api)
    hdrs = director_headers(director)
    validate_success(
        api.sign_out_attendance(records[0]["id"], {"sign_out_type": "WALKER"},
                                hdrs),
        200,
    )
    closed = close_day(day["id"], director["id"])
    assert closed["status"] == "CLOSED"
    assert closed["present_count"] == 0
    assert closed["signed_out_count"] == 1
    assert closed["missing_signout_count"] == 2
    assert_attendance_tally(closed, 3)

    data, meta = validate_paginated(api.list_day_attendance(day["id"], ADMIN))
    assert meta["total_count"] == 3, "no record drift through the close sweep"
    statuses = sorted(r["status"] for r in data)
    assert statuses == ["MISSING_SIGNOUT", "MISSING_SIGNOUT", "SIGNED_OUT"]


def test_envelope_shape_on_success_and_error(api, platform_admin_headers):
    """PRD 2.2: "All successful API responses (those with 2xx status codes)
    follow this standard envelope format" with meta.api_request_id,
    meta.api_request_timestamp, response_type and data; and "All error API
    responses (4xx status codes) follow this standard envelope format" with
    response_type "error" and data.error_id plus data.message.

    Design: Corner/endpoints/c_envelope_shape_on_success_and_error
    """
    from test_helpers import NON_EXISTENT_UUID, create_site_payload

    created = validate_success(
        api.create_site(create_site_payload(name="Club S"),
                        platform_admin_headers),
        201,
    )
    ok = api.get_site(created["id"], platform_admin_headers)
    body = ok.json()
    assert ok.status_code == 200
    assert body["response_type"] == "object"
    assert isinstance(body["meta"]["api_request_id"], str)
    assert isinstance(body["meta"]["api_request_timestamp"], str)
    assert body["data"]["id"] == created["id"]

    err = api.get_site(NON_EXISTENT_UUID, platform_admin_headers)
    ebody = err.json()
    assert err.status_code == 404
    assert ebody["response_type"] == "error"
    assert ebody["data"]["error_id"] == "ERR_NOT_FOUND"
    assert isinstance(ebody["data"]["message"], str) and ebody["data"]["message"]
    assert "api_request_id" in ebody["meta"]
