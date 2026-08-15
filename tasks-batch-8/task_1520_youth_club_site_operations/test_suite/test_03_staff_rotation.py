"""Staff credentials, program-area rotation, capacity and ratio gates."""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    check_in_assignment,
    close_day,
    create_active_member,
    create_area,
    create_credentialed_staff,
    create_credential_payload,
    create_rotation_payload,
    create_staff_payload,
    director_headers,
    get_club_day,
    open_club_day,
    schedule_staff_assignment,
    schedule_youth_assignment,
    setup_site_with_director,
    setup_site_with_director_and_frontline,
    sign_in_member,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]


def test_staff_activation_requires_both_credentials(api):
    """PRD 3.1: "New hires start in `HIRED` status with `compliance_status`
    `INCOMPLETE`" and "When a posting leaves a `HIRED` staff member with both
    credentials present and unexpired, the system promotes them to `ACTIVE`
    automatically". PRD 3.1: "`INCOMPLETE` when either credential expiry is
    null".

    Design: Corner/state_machines/c_staff_activation_requires_both_credentials
    """
    from test_helpers import FAR_FUTURE_EXPIRY, create_site

    site = create_site(clock="2026-08-01T09:00:00Z")
    staff = validate_success(
        api.create_staff(create_staff_payload(site["id"], "Flo One", "FRONTLINE"),
                         ADMIN),
        201,
    )
    assert staff["status"] == "HIRED"
    assert staff["compliance_status"] == "INCOMPLETE"

    after_one = validate_success(
        api.post_staff_credential(
            staff["id"],
            create_credential_payload("BACKGROUND_CHECK", FAR_FUTURE_EXPIRY),
            ADMIN,
        ),
        200,
    )
    assert after_one["status"] == "HIRED"
    assert after_one["compliance_status"] == "INCOMPLETE"

    after_two = validate_success(
        api.post_staff_credential(
            staff["id"], create_credential_payload("TRAINING", FAR_FUTURE_EXPIRY),
            ADMIN,
        ),
        200,
    )
    assert after_two["status"] == "ACTIVE"
    assert after_two["compliance_status"] == "COMPLIANT"


def test_rotation_polymorphic_kind_field_validation(api):
    """PRD 3.6: "a `kind` of `YOUTH` requires `member_id` and forbids
    `staff_id`, while a `kind` of `STAFF` requires `staff_id` and forbids
    `member_id`, with any inconsistency rejected as `ERR_VALIDATION` (400)."
    PRD 3.6: "The operating day is divided into three blocks: `BLOCK_A`,
    `BLOCK_B`, and `BLOCK_C`."

    Design: Corner/entities/c_rotation_polymorphic_kind_field_validation
    """
    site, director = setup_site_with_director(clock="2026-08-03T09:00:00Z")
    day = open_club_day(site["id"], director["id"], "2026-08-03")
    area = create_area(site["id"], "Gym", 30)
    member = create_active_member(site["id"], director["id"], legal_name="Kid A")
    hdrs = director_headers(director)

    res = api.create_rotation_assignment(
        create_rotation_payload(day["id"], area["id"], "BLOCK_A", "YOUTH",
                                staff_id=director["id"]),
        hdrs,
    )
    validate_error(res, ApiErrorId.ERR_VALIDATION, expected_status=400)

    res = api.create_rotation_assignment(
        create_rotation_payload(day["id"], area["id"], "BLOCK_Z", "YOUTH",
                                member_id=member["id"]),
        hdrs,
    )
    validate_error(res, ApiErrorId.ERR_VALIDATION, expected_status=400)


def test_staff_assignment_requires_compliance_when_hired(api):
    """PRD 3.6: "A staff assignment requires the staffer to be `ACTIVE` with
    `compliance_status` `COMPLIANT` or `EXPIRING`; scheduling or checking in
    with an `INCOMPLETE` or `LAPSED` staffer is rejected with
    `ERR_STAFF_NOT_COMPLIANT` (422)."

    Design: Corner/validations/c_staff_assignment_requires_compliance_when_hired
    """
    site, director = setup_site_with_director(clock="2026-08-03T09:00:00Z")
    # second staffer hired but never credentialed: HIRED / INCOMPLETE
    rookie = validate_success(
        api.create_staff(create_staff_payload(site["id"], "Flo New", "FRONTLINE"),
                         ADMIN),
        201,
    )
    assert rookie["status"] == "HIRED"
    assert rookie["compliance_status"] == "INCOMPLETE"

    day = open_club_day(site["id"], director["id"], "2026-08-03")
    area = create_area(site["id"], "Gym", 30)
    res = api.create_rotation_assignment(
        create_rotation_payload(day["id"], area["id"], "BLOCK_A", "STAFF",
                                staff_id=rookie["id"]),
        director_headers(director),
    )
    validate_error(res, ApiErrorId.ERR_STAFF_NOT_COMPLIANT, expected_status=422)
    data, meta = validate_paginated(
        api.list_staff_rotation_assignments(rookie["id"], ADMIN)
    )
    assert meta["total_count"] == 0


def _setup_lapsed_frontline(api):
    """Frontline staffer promoted to ACTIVE, then background check moved into
    the past so compliance becomes LAPSED. Returns (site, director, frontline,
    day, area)."""
    site, director, frontline = setup_site_with_director_and_frontline(
        clock="2026-08-03T09:00:00Z"
    )
    day = open_club_day(site["id"], director["id"], "2026-08-03")
    area = create_area(site["id"], "Gym", 30)
    lapsed = validate_success(
        api.post_staff_credential(
            frontline["id"],
            create_credential_payload("BACKGROUND_CHECK", "2026-07-01T00:00:00Z"),
            ADMIN,
        ),
        200,
    )
    return site, director, frontline, day, area, lapsed


def test_staff_assignment_blocked_by_lapsed_compliance(api):
    """PRD 3.6: "scheduling or checking in with an `INCOMPLETE` or `LAPSED`
    staffer is rejected with `ERR_STAFF_NOT_COMPLIANT` (422)." PRD 3.1:
    "otherwise `LAPSED` when either expiry is before now".

    Design: Difficulty/cross_entity_state_dependency/staff_assignment_blocked_by_lapsed_staff_compliance
    """
    site, director, frontline, day, area, lapsed = _setup_lapsed_frontline(api)
    assert lapsed["compliance_status"] == "LAPSED"
    res = api.create_rotation_assignment(
        create_rotation_payload(day["id"], area["id"], "BLOCK_A", "STAFF",
                                staff_id=frontline["id"]),
        director_headers(director),
    )
    validate_error(res, ApiErrorId.ERR_STAFF_NOT_COMPLIANT, expected_status=422)


def test_lapsed_staff_gate_creates_no_assignment(api):
    """PRD 3.6: "A staff assignment requires the staffer to be `ACTIVE` with
    `compliance_status` `COMPLIANT` or `EXPIRING`" — a rejected schedule call
    leaves no rotation assignment behind.

    Design: Difficulty/cross_entity_state_dependency/staff_assignment_blocked_by_lapsed_staff_compliance
    """
    site, director, frontline, day, area, lapsed = _setup_lapsed_frontline(api)
    api.create_rotation_assignment(
        create_rotation_payload(day["id"], area["id"], "BLOCK_A", "STAFF",
                                staff_id=frontline["id"]),
        director_headers(director),
    )
    data, meta = validate_paginated(
        api.list_staff_rotation_assignments(frontline["id"], ADMIN)
    )
    assert meta["total_count"] == 0
    staff_after = validate_success(api.get_staff(frontline["id"], ADMIN), 200)
    assert staff_after["compliance_status"] == "LAPSED"
    assert staff_after["status"] == "ACTIVE", (
        "the lapse recomputes compliance but does not demote status (PRD 3.1: "
        "'later postings leave the status `ACTIVE` unchanged')"
    )


def _setup_ratio_boundary_day(api):
    """standard_ratio 2 site; one frontline staffer checked in on BLOCK_A of a
    capacity-100 STANDARD area; three ACTIVE members signed in with YOUTH
    assignments SCHEDULED on BLOCK_A. Returns (director, ra_ids)."""
    site, director, frontline = setup_site_with_director_and_frontline(
        clock="2026-08-03T09:00:00Z", standard_ratio=2
    )
    day = open_club_day(site["id"], director["id"], "2026-08-03")
    area = create_area(site["id"], "Gym", 100, risk_tier="STANDARD")
    ra_staff = schedule_staff_assignment(day["id"], area["id"], frontline["id"],
                                         director["id"])
    check_in_assignment(ra_staff["id"], director["id"])
    ras = []
    for name in ("Kid One", "Kid Two", "Kid Three"):
        m = create_active_member(site["id"], director["id"], legal_name=name)
        sign_in_member(day["id"], m["id"], director["id"])
        ras.append(
            schedule_youth_assignment(day["id"], area["id"], m["id"],
                                      director["id"])
        )
    return director, ras


def test_ratio_checkin_allows_exact_capacity(api):
    """PRD 3.6: "The boundary is inclusive: a youth count exactly equal to the
    checked-in staff count multiplied by the effective ratio is allowed; one
    youth more is rejected."

    Design: Difficulty/boundary_precision_check/ratio_checkin_allows_exact_capacity_denies_one_over
    """
    director, ras = _setup_ratio_boundary_day(api)
    # 1 staff x ratio 2 == 2 youth allowed: both of the first two check in
    first = check_in_assignment(ras[0]["id"], director["id"])
    second = check_in_assignment(ras[1]["id"], director["id"])
    assert first["status"] == "CHECKED_IN"
    assert second["status"] == "CHECKED_IN"


def test_ratio_checkin_denies_one_over(api):
    """PRD 3.6: "then ratio — the required staffing, computed as the
    after-check-in youth count divided by the area's effective ratio and
    rounded up to a whole number, may not exceed the number of staff currently
    checked in to that same area and block, or the check-in is rejected with
    `ERR_RATIO_VIOLATION` (422)."

    Design: Difficulty/boundary_precision_check/ratio_checkin_allows_exact_capacity_denies_one_over
    """
    director, ras = _setup_ratio_boundary_day(api)
    check_in_assignment(ras[0]["id"], director["id"])
    check_in_assignment(ras[1]["id"], director["id"])
    # third youth: ceil(3 / 2) = 2 > 1 checked-in staff
    res = api.check_in_rotation_assignment(ras[2]["id"],
                                           director_headers(director))
    validate_error(res, ApiErrorId.ERR_RATIO_VIOLATION, expected_status=422)
    data, _ = validate_paginated(
        api.list_day_rotation_assignments(ras[2]["club_day_id"], ADMIN,
                                          params={"status": "SCHEDULED"})
    )
    assert [r["id"] for r in data] == [ras[2]["id"]], (
        "the rejected third assignment remains SCHEDULED"
    )


def test_area_capacity_checked_before_ratio(api):
    """PRD 3.6: "Youth check-ins face two gates, evaluated in this order:
    first capacity — the number of checked-in youth in that area and block
    after this check-in may not exceed the area's `capacity`, or the check-in
    is rejected with `ERR_AREA_CAPACITY_EXCEEDED` (422); then ratio".

    Design: Corner/validations/c_area_capacity_checked_before_ratio
    """
    site, director, frontline = setup_site_with_director_and_frontline(
        clock="2026-08-03T09:00:00Z"
    )
    day = open_club_day(site["id"], director["id"], "2026-08-03")
    # capacity 1 but a ratio_override of 100: ratio can never fail first
    area = create_area(site["id"], "Nook", 1, ratio_override=100)
    ra_staff = schedule_staff_assignment(day["id"], area["id"], frontline["id"],
                                         director["id"])
    check_in_assignment(ra_staff["id"], director["id"])
    m1 = create_active_member(site["id"], director["id"], legal_name="Kid A")
    m2 = create_active_member(site["id"], director["id"], legal_name="Kid B")
    sign_in_member(day["id"], m1["id"], director["id"])
    sign_in_member(day["id"], m2["id"], director["id"])
    ra1 = schedule_youth_assignment(day["id"], area["id"], m1["id"],
                                    director["id"])
    check_in_assignment(ra1["id"], director["id"])
    ra2 = schedule_youth_assignment(day["id"], area["id"], m2["id"],
                                    director["id"])

    res = api.check_in_rotation_assignment(ra2["id"], director_headers(director))
    validate_error(res, ApiErrorId.ERR_AREA_CAPACITY_EXCEEDED,
                   expected_status=422)
    assert res.json()["data"]["error_id"] != "ERR_RATIO_VIOLATION", (
        "capacity is checked before ratio (ceil(2/100) = 1 <= 1 staff would pass)"
    )


def test_duplicate_member_block_assignment_rejected(api):
    """PRD 3.6: "a member may hold at most one non-terminal assignment —
    `SCHEDULED` or `CHECKED_IN` — for the same club day and block
    (`ERR_ASSIGNMENT_CONFLICT`, 409)."

    Design: Corner/validations/c_duplicate_member_block_assignment_rejected
    """
    site, director = setup_site_with_director(clock="2026-08-03T09:00:00Z")
    day = open_club_day(site["id"], director["id"], "2026-08-03")
    area = create_area(site["id"], "Gym", 30)
    member = create_active_member(site["id"], director["id"], legal_name="Kid A")
    schedule_youth_assignment(day["id"], area["id"], member["id"], director["id"])
    res = api.create_rotation_assignment(
        create_rotation_payload(day["id"], area["id"], "BLOCK_A", "YOUTH",
                                member_id=member["id"]),
        director_headers(director),
    )
    validate_error(res, ApiErrorId.ERR_ASSIGNMENT_CONFLICT, expected_status=409)
    data, meta = validate_paginated(
        api.list_member_rotation_assignments(member["id"], ADMIN)
    )
    assert meta["total_count"] == 1


def test_checkin_cancelled_assignment_returns_not_checkable(api):
    """PRD 3.6: "The assignment must be `SCHEDULED`
    (`ERR_ASSIGNMENT_NOT_CHECKABLE`, 409)". PRD 3.2: "every `SCHEDULED`
    rotation assignment of the member on a club day dated today or later is
    `CANCELLED`" by withdrawal.

    Design: Corner/state_machines/c_checkin_cancelled_assignment_returns_not_checkable
    """
    site, director = setup_site_with_director(clock="2026-08-03T09:00:00Z")
    day = open_club_day(site["id"], director["id"], "2026-08-03")
    area = create_area(site["id"], "Gym", 30)
    member = create_active_member(site["id"], director["id"], legal_name="Kid A")
    sign_in_member(day["id"], member["id"], director["id"])
    ra = schedule_youth_assignment(day["id"], area["id"], member["id"],
                                   director["id"])
    validate_success(api.withdraw_member(member["id"], director_headers(director)),
                     200)
    data, _ = validate_paginated(
        api.list_member_rotation_assignments(member["id"], ADMIN)
    )
    assert data[0]["status"] == "CANCELLED"
    res = api.check_in_rotation_assignment(ra["id"], director_headers(director))
    validate_error(res, ApiErrorId.ERR_ASSIGNMENT_NOT_CHECKABLE,
                   expected_status=409)


def test_move_from_scheduled_returns_not_movable(api):
    """PRD 3.6: "Moving requires the assignment `CHECKED_IN`
    (`ERR_ASSIGNMENT_NOT_MOVABLE`)".

    Design: Corner/state_machines/c_move_from_scheduled_returns_not_movable
    """
    site, director = setup_site_with_director(clock="2026-08-03T09:00:00Z")
    day = open_club_day(site["id"], director["id"], "2026-08-03")
    area_a = create_area(site["id"], "Gym", 30)
    area_b = create_area(site["id"], "Art", 30)
    member = create_active_member(site["id"], director["id"], legal_name="Kid A")
    sign_in_member(day["id"], member["id"], director["id"])
    ra = schedule_youth_assignment(day["id"], area_a["id"], member["id"],
                                   director["id"])
    res = api.move_rotation_assignment(ra["id"], {"new_area_id": area_b["id"]},
                                       director_headers(director))
    validate_error(res, ApiErrorId.ERR_ASSIGNMENT_NOT_MOVABLE, expected_status=409)
    data, _ = validate_paginated(
        api.list_member_rotation_assignments(member["id"], ADMIN)
    )
    assert data[0]["status"] == "SCHEDULED"


def test_move_happy_path_returns_checked_in_successor(api):
    """PRD 3.6: "The original record becomes `MOVED`, a successor assignment is
    created already `CHECKED_IN` with the same club day, block, kind, and
    participant but the new `area_id`, and the response returns the successor".

    Design: Corner/state_machines/c_move_happy_path_returns_checked_in_successor
    """
    site, director = setup_site_with_director(
        clock="2026-08-03T09:00:00Z", standard_ratio=2
    )
    flo1 = create_credentialed_staff(site["id"], "Flo One", "FRONTLINE")
    flo2 = create_credentialed_staff(site["id"], "Flo Two", "FRONTLINE")
    day = open_club_day(site["id"], director["id"], "2026-08-03")
    area_a = create_area(site["id"], "Gym", 30)
    area_b = create_area(site["id"], "Art", 30)
    # staff coverage in both areas so both check-in and move ratio checks pass
    ra_s1 = schedule_staff_assignment(day["id"], area_a["id"], flo1["id"],
                                      director["id"])
    check_in_assignment(ra_s1["id"], director["id"])
    ra_s2 = schedule_staff_assignment(day["id"], area_b["id"], flo2["id"],
                                      director["id"])
    check_in_assignment(ra_s2["id"], director["id"])
    member = create_active_member(site["id"], director["id"], legal_name="Kid A")
    sign_in_member(day["id"], member["id"], director["id"])
    ra = schedule_youth_assignment(day["id"], area_a["id"], member["id"],
                                   director["id"])
    check_in_assignment(ra["id"], director["id"])

    successor = validate_success(
        api.move_rotation_assignment(ra["id"], {"new_area_id": area_b["id"]},
                                     director_headers(director)),
        200,
    )
    assert successor["id"] != ra["id"], "a new successor record is returned"
    assert successor["status"] == "CHECKED_IN"
    assert successor["area_id"] == area_b["id"]
    assert successor["block"] == "BLOCK_A"
    assert successor["kind"] == "YOUTH"
    assert successor["member_id"] == member["id"]

    data, _ = validate_paginated(
        api.list_member_rotation_assignments(member["id"], ADMIN)
    )
    by_id = {r["id"]: r for r in data}
    assert by_id[ra["id"]]["status"] == "MOVED"


def _setup_checked_in_staff_day(api):
    """standard_ratio 2; two members on site; one frontline staffer CHECKED_IN
    on BLOCK_A so posture is NORMAL. Returns (site, director, frontline, day,
    ra_staff)."""
    site, director, frontline = setup_site_with_director_and_frontline(
        clock="2026-08-03T09:00:00Z", standard_ratio=2
    )
    day = open_club_day(site["id"], director["id"], "2026-08-03")
    area = create_area(site["id"], "Gym", 30, risk_tier="STANDARD")
    for name in ("Kid One", "Kid Two"):
        m = create_active_member(site["id"], director["id"], legal_name=name)
        sign_in_member(day["id"], m["id"], director["id"])
    ra_staff = schedule_staff_assignment(day["id"], area["id"], frontline["id"],
                                         director["id"])
    check_in_assignment(ra_staff["id"], director["id"])
    return site, director, frontline, day, ra_staff


def test_credential_lapse_cancels_assignment(api):
    """PRD 3.1: "If a credential posting — or the passage of the logical clock
    surfaced by a club-day opening sweep (Section 3.4) — leaves a staff member
    `LAPSED`, the system cancels that staffer's `SCHEDULED` and `CHECKED_IN`
    rotation assignments on club days dated today or later".

    Design: Difficulty/transitive_cascade/credential_lapse_cancels_staff_assignment_flips_day_posture
    """
    site, director, frontline, day, ra_staff = _setup_checked_in_staff_day(api)
    lapsed = validate_success(
        api.post_staff_credential(
            frontline["id"],
            create_credential_payload("BACKGROUND_CHECK", "2026-07-01T00:00:00Z"),
            ADMIN,
        ),
        200,
    )
    assert lapsed["compliance_status"] == "LAPSED"
    data, _ = validate_paginated(
        api.list_staff_rotation_assignments(frontline["id"], ADMIN)
    )
    assert data[0]["id"] == ra_staff["id"]
    assert data[0]["status"] == "CANCELLED", (
        "the lapse cascade cancels the CHECKED_IN assignment"
    )


def test_credential_lapse_flips_day_posture(api):
    """PRD 3.1: "recomputes the `posture` of every affected day; a cancellation
    that removes the last checked-in staff member from a day can flip that day
    straight to `RATIO_STRAINED`." PRD 3.4: "if the staffing count multiplied
    by the site's `standard_ratio` is strictly less than `present_count`, the
    posture is `RATIO_STRAINED`."

    Design: Difficulty/transitive_cascade/credential_lapse_cancels_staff_assignment_flips_day_posture
    """
    site, director, frontline, day, ra_staff = _setup_checked_in_staff_day(api)
    assert get_club_day(day["id"])["posture"] == "NORMAL", (
        "1 staff x standard_ratio 2 covers present_count 2"
    )
    validate_success(
        api.post_staff_credential(
            frontline["id"],
            create_credential_payload("BACKGROUND_CHECK", "2026-07-01T00:00:00Z"),
            ADMIN,
        ),
        200,
    )
    assert get_club_day(day["id"])["posture"] == "RATIO_STRAINED", (
        "0 staff x 2 = 0 < present_count 2 after the cascade"
    )
