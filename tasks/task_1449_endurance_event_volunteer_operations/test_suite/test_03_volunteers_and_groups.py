"""Volunteer registration, screening, profile updates, and fundraising
groups (PRD §3.3), plus list behavior (PRD §2.3).
"""
import pytest

from test_helpers import (
    api_client, ApiErrorId, C, TEST_USERS,
    make_volunteer_headers, make_group_leader_headers,
    validate_success, validate_error, validate_paginated,
    create_event, add_group,
    create_volunteer_payload, create_fundraising_group_payload,
    register_volunteer, screen_volunteer, register_eligible_volunteer,
    setup_event_with_shift,
    assert_volunteer, assert_fundraising_group,
)

DIRECTOR = TEST_USERS["director_headers"]
COORDINATOR = TEST_USERS["coordinator_headers"]
ANONYMOUS = TEST_USERS["anonymous_headers"]


def test_anonymous_can_register_and_read(api):
    """PRD §3.3: "Registration is per-event and self-service. An `Anonymous`
    caller — or a `VolunteerCoordinator` acting on someone's behalf —
    registers by supplying `event_id`, `full_name`, `date_of_birth` as an ISO
    `YYYY-MM-DD` date, and optionally `skill_tags`, `group_id`, `float_opt_in`,
    and `is_returning`."
    PRD §3.3: "A new volunteer starts `REGISTERED` with `no_show_strikes` at
    zero"

    Design: Corner/rbac/anonymous_can_register_and_read
    """
    event = create_event(clock=None)
    resp = api_client.create_volunteer(
        create_volunteer_payload(event["id"], full_name="V Walkin",
                                 date_of_birth="2001-01-01"),
        ANONYMOUS)
    data = validate_success(resp, expected_status=201)
    assert_volunteer(data)
    assert data["status"] == "REGISTERED"
    read = api_client.get_volunteer(data["id"], ANONYMOUS)
    fetched = validate_success(read, expected_status=200)
    assert fetched["id"] == data["id"]


# ---------------------------------------------------------------------------
# Age boundary (PRD §3.3)
# ---------------------------------------------------------------------------

def _setup_age_boundary(api):
    """Role min_age 18; one volunteer born exactly on race day, one one day
    later. Clock sits inside the general signup window."""
    ctx = setup_event_with_shift(
        publish=True, role_overrides={"min_age_years": 18},
        shift_overrides={"required_headcount": 2})
    ev = ctx["event"]["id"]
    v_exact = register_volunteer(ev, full_name="V Exact", date_of_birth="2008-10-04")
    v_short = register_volunteer(ev, full_name="V Short", date_of_birth="2008-10-05")
    return ctx, v_exact, v_short


def test_age_boundary_exact_birthday_on_event_date_passes(api):
    """PRD §3.3: "At registration the system derives `age_years_on_event`,
    and it reuses that derivation at screening, signup creation, and approval:
    the whole years between `date_of_birth` and the calendar date of the
    event's `event_start_at` in UTC — the event year minus the birth year,
    reduced by one when the event date's month-and-day falls earlier in the
    calendar year than the birthday's month-and-day. A birthday falling
    exactly on the event date counts as reached."

    Design: Difficulty/boundary_precision_check/age_boundary_exact_vs_one_day_short
    """
    ctx, v_exact, _ = _setup_age_boundary(api)
    assert v_exact["age_years_on_event"] == 18, \
        f"birthday on the event date counts as reached; got {v_exact['age_years_on_event']}"
    screen_volunteer(v_exact["id"])
    resp = api_client.create_signup(
        {"volunteer_id": v_exact["id"], "shift_id": ctx["shift"]["id"]}, COORDINATOR)
    sg = validate_success(resp, expected_status=201)
    assert sg["status"] == "REQUESTED"


def test_age_boundary_one_day_short_rejected(api):
    """PRD §3.5: "the volunteer's `age_years_on_event` must be at least the
    role's `min_age_years` (`ERR_MIN_AGE_NOT_MET`)"
    PRD §3.3: "the whole years between `date_of_birth` and the calendar date
    of the event's `event_start_at` in UTC — the event year minus the birth
    year, reduced by one when the event date's month-and-day falls earlier in
    the calendar year than the birthday's month-and-day."

    Design: Difficulty/boundary_precision_check/age_boundary_exact_vs_one_day_short
    """
    ctx, _, v_short = _setup_age_boundary(api)
    assert v_short["age_years_on_event"] == 17
    screen_volunteer(v_short["id"])
    resp = api_client.create_signup(
        {"volunteer_id": v_short["id"], "shift_id": ctx["shift"]["id"]}, COORDINATOR)
    validate_error(resp, ApiErrorId.ERR_MIN_AGE_NOT_MET)


# ---------------------------------------------------------------------------
# Volunteer state guards (PRD §3.3)
# ---------------------------------------------------------------------------

def test_volunteer_state_guards_rejected(api):
    """PRD §3.3: "A coordinator screens a `REGISTERED` volunteer — from any
    other status the request is rejected with `ERR_VOLUNTEER_NOT_SCREENABLE`"
    PRD §3.3: "A coordinator can reinstate a `SUSPENDED` volunteer — from any
    other status the request is rejected with `ERR_VOLUNTEER_NOT_SUSPENDED`"
    PRD §3.5: "the volunteer must be `ELIGIBLE` (`ERR_VOLUNTEER_NOT_ELIGIBLE`)"

    Design: Corner/errors/volunteer_state_guards_rejected
    """
    ctx = setup_event_with_shift(publish=True,
                                 shift_overrides={"required_headcount": 2})
    ev = ctx["event"]["id"]
    v1 = register_volunteer(ev, full_name="V One", date_of_birth="2000-01-01")
    v2 = register_eligible_volunteer(ev, full_name="V Two", date_of_birth="2000-01-02")
    double_screen = api_client.screen_volunteer(v2["id"], COORDINATOR)
    validate_error(double_screen, ApiErrorId.ERR_VOLUNTEER_NOT_SCREENABLE)
    reinstate_eligible = api_client.reinstate_volunteer(v2["id"], COORDINATOR)
    validate_error(reinstate_eligible, ApiErrorId.ERR_VOLUNTEER_NOT_SUSPENDED)
    unscreened_signup = api_client.create_signup(
        {"volunteer_id": v1["id"], "shift_id": ctx["shift"]["id"]}, COORDINATOR)
    validate_error(unscreened_signup, ApiErrorId.ERR_VOLUNTEER_NOT_ELIGIBLE)


# ---------------------------------------------------------------------------
# Fundraising group affiliation (PRD §3.3)
# ---------------------------------------------------------------------------

def test_group_suspended_blocks_new_affiliation(api):
    """PRD §3.3: "A volunteer may affiliate only with an `ACTIVE` group, both
    at registration and on later profile updates; referencing a suspended
    group is rejected with `ERR_GROUP_SUSPENDED`."
    PRD §3.3: "A group change into a `SUSPENDED` group fails with
    `ERR_GROUP_SUSPENDED`."

    Design: Corner/validations/group_suspended_blocks_new_affiliation
    """
    event = create_event(clock=None)
    grp = add_group(event["id"], name="Club Two", charity_code="CHARITY-TWO")
    validate_success(api_client.suspend_group(grp["id"], DIRECTOR))
    vol = register_volunteer(event["id"], full_name="V One", date_of_birth="2000-01-01")
    observed_version = vol["version"]
    resp = api_client.patch_volunteer(
        vol["id"], {"group_id": grp["id"],
                    "expected_volunteer_version": observed_version},
        COORDINATOR)
    validate_error(resp, ApiErrorId.ERR_GROUP_SUSPENDED)
    after = validate_success(api_client.get_volunteer(vol["id"], COORDINATOR))
    assert after["group_id"] is None
    assert after["version"] == observed_version, \
        "a rejected profile update must not advance the volunteer's version"


# ---------------------------------------------------------------------------
# Listing and pagination (PRD §2.3)
# ---------------------------------------------------------------------------

def test_volunteer_list_filtered_by_group(api):
    """PRD §2.3: "Beyond pagination, list endpoints accept resource-specific
    filters as query parameters: events, course segments, role catalog
    entries, fundraising groups, and supply inventories filter by `event_id`;
    shifts filter by `event_id`, `role_entry_id`, or `segment_id`; volunteers
    filter by `event_id` or `group_id`"

    Design: Corner/entities/volunteer_list_filtered_by_group
    """
    event = create_event(clock=None)
    grp = add_group(event["id"])
    v1 = register_volunteer(event["id"], full_name="V One",
                            date_of_birth="2000-01-01", group_id=grp["id"])
    v2 = register_volunteer(event["id"], full_name="V Two",
                            date_of_birth="2000-01-02", group_id=grp["id"])
    v3 = register_volunteer(event["id"], full_name="V Three",
                            date_of_birth="2000-01-03")
    data, meta = validate_paginated(api_client.list_volunteers(
        COORDINATOR, params={"group_id": grp["id"]}))
    ids = {v["id"] for v in data}
    assert ids == {v1["id"], v2["id"]}, f"expected exactly the affiliated pair, got {ids}"
    assert v3["id"] not in ids
    assert meta["total_count"] == 2


def test_list_pagination_defaults_and_envelope(api):
    """PRD §2.3: "The `limit` parameter caps the number of items returned: it
    defaults to 10, with a minimum of 1 and a maximum of 100. The `offset`
    parameter skips a number of items and defaults to 0."
    PRD §2.3: "The `meta` object of a list response carries the pagination
    fields `limit`, `offset`, `total_count`, and `has_more`."

    Design: Corner/endpoints/list_pagination_defaults_and_envelope
    """
    event = create_event(clock=None)
    created = [register_volunteer(event["id"], full_name=f"V {i}",
                                  date_of_birth=f"2000-01-0{i}")
               for i in (1, 2, 3)]
    data, meta = validate_paginated(api_client.list_volunteers(
        COORDINATOR, params={"event_id": event["id"]}))
    assert meta["limit"] == 10 and meta["offset"] == 0
    assert meta["total_count"] == 3 and meta["has_more"] is False
    assert {v["id"] for v in data} == {v["id"] for v in created}
    page, meta2 = validate_paginated(api_client.list_volunteers(
        COORDINATOR, params={"event_id": event["id"], "limit": 2, "offset": 2}))
    assert len(page) == 1
    assert meta2["total_count"] == 3 and meta2["has_more"] is False
    assert meta2["limit"] == 2 and meta2["offset"] == 2


# ---------------------------------------------------------------------------
# Profile optimistic concurrency (PRD §2.9)
# ---------------------------------------------------------------------------

def test_occ_volunteer_patch_stale_rejected(api):
    """PRD §2.9: "Updating a volunteer's mutable profile fields requires
    `expected_volunteer_version`, holding the client's last observed `version`
    of the volunteer. A mismatch with the volunteer's current `version` is
    rejected with `ERR_STALE_VERSION` (HTTP 412) — for example, when a
    coordinator edits skills after the volunteer's record has already been
    advanced by another write."

    Design: Corner/complexity_layers/occ_volunteer_patch_stale_rejected
    """
    event = create_event(clock=None)
    vol = register_volunteer(event["id"], full_name="V One", date_of_birth="2000-01-01")
    observed = vol["version"]
    first = api_client.patch_volunteer(
        vol["id"], {"skill_tags": ["MEDICAL"], "expected_volunteer_version": observed},
        COORDINATOR)
    data = validate_success(first, expected_status=200)
    assert data["version"] == observed + 1
    stale = api_client.patch_volunteer(
        vol["id"], {"float_opt_in": True, "expected_volunteer_version": observed},
        make_volunteer_headers(vol["id"]))
    validate_error(stale, ApiErrorId.ERR_STALE_VERSION)
    after = validate_success(api_client.get_volunteer(vol["id"], COORDINATOR))
    assert after["float_opt_in"] is False, "the stale write must not partially apply"
    assert after["skill_tags"] == ["MEDICAL"]
