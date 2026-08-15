"""Course segments, role catalog entries, and shifts (PRD §3.2):
half-open mile ranges, role lifecycle, shift creation rules.
"""
import pytest

from test_helpers import (
    api_client, ApiErrorId, C, TEST_USERS,
    validate_success, validate_error, validate_paginated,
    create_event, add_segment, add_role, add_shift, add_group,
    create_event_payload, create_course_segment_payload,
    create_role_catalog_entry_payload, create_shift_payload,
    setup_event_with_shift, register_eligible_volunteer,
    create_confirmed_signup, request_signup,
    make_volunteer_headers,
    assert_course_segment, assert_role_catalog_entry, assert_shift,
)

DIRECTOR = TEST_USERS["director_headers"]
COORDINATOR = TEST_USERS["coordinator_headers"]


def test_segment_invalid_terrain_enum_rejected(api):
    """PRD §3.2: "Each segment carries its `event_id`, a `segment_code`
    unique within that event (for example, `MILE-05-WATER`), a half-open mile
    range from `mile_start` (inclusive) to `mile_end` (exclusive), and a
    `terrain_type` of `ROAD`, `TRAIL`, `BRIDGE`, or `TRACK`."

    Design: Corner/entities/segment_invalid_terrain_enum_rejected
    """
    event = create_event(clock=None)
    resp = api_client.create_course_segment(
        create_course_segment_payload(event["id"], segment_code="SEG-X",
                                      mile_start=1, mile_end=2,
                                      terrain_type="DESERT"),
        COORDINATOR)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_shift_inverted_times_rejected(api):
    """PRD §3.2: "All three references must belong to the same event, and the
    shift's window must sit inside the event's bounds: `start_at` no earlier
    than `event_start_at`, `end_at` no later than `event_end_at`, and `end_at`
    strictly after `start_at`. Violations are rejected with
    `ERR_INVALID_REQUEST`"

    Design: Corner/entities/shift_inverted_times_rejected
    """
    ctx = setup_event_with_shift(publish=False)
    resp = api_client.create_shift(
        create_shift_payload(ctx["event"]["id"], ctx["role"]["id"],
                             ctx["segment"]["id"],
                             start_at="2026-10-04T11:00:00Z",
                             end_at="2026-10-04T07:00:00Z",
                             required_headcount=1),
        COORDINATOR)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
    listed, meta = validate_paginated(api_client.list_shifts(
        COORDINATOR, params={"event_id": ctx["event"]["id"]}))
    assert [s["id"] for s in listed] == [ctx["shift"]["id"]], \
        "the rejected inverted shift must not be persisted"


def test_get_missing_shift_returns_not_found(api):
    """PRD §2.7: "When an endpoint path contains resource identifiers, the
    server validates them sequentially, left to right, and rejects the request
    with the not-found error of the first identifier that does not resolve to
    an existing resource."

    Design: Corner/entities/get_missing_shift_returns_not_found
    """
    resp = api_client.get_shift(C.MISSING_UUID, COORDINATOR)
    err = validate_error(resp, ApiErrorId.ERR_SHIFT_NOT_FOUND)
    assert isinstance(err.get("message"), str) and err["message"]
    assert resp.json().get("response_type") == "error"


# ---------------------------------------------------------------------------
# Half-open mile ranges (PRD §3.2)
# ---------------------------------------------------------------------------

def test_segment_mile_half_open_adjacency_legal(api):
    """PRD §3.2: "The ranges are half-open, so exact adjacency — one segment's
    `mile_end` equal to another's `mile_start` — is legal."

    Design: Difficulty/resource_temporal_overlap/segment_mile_half_open_adjacency
    """
    event = create_event(clock=None)
    seg_a = add_segment(event["id"], segment_code="SEG-A", mile_start=5, mile_end=10)
    resp_b = api_client.create_course_segment(
        create_course_segment_payload(event["id"], segment_code="SEG-B",
                                      mile_start=10, mile_end=14,
                                      terrain_type="TRAIL"),
        COORDINATOR)
    seg_b = validate_success(resp_b, expected_status=201)
    assert_course_segment(seg_b)
    assert seg_b["mile_start"] == 10
    resp_c = api_client.create_course_segment(
        create_course_segment_payload(event["id"], segment_code="SEG-C",
                                      mile_start=3, mile_end=5),
        COORDINATOR)
    seg_c = validate_success(resp_c, expected_status=201)
    assert seg_c["mile_end"] == 5


def test_segment_mile_interior_overlap_rejected(api):
    """PRD §3.2: "A new segment conflicts with an existing segment of the same
    event when the new `mile_start` is less than the existing segment's
    `mile_end` and the existing segment's `mile_start` is less than the new
    `mile_end`; the conflict is rejected with `ERR_SEGMENT_MILE_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/segment_mile_half_open_adjacency
    """
    event = create_event(clock=None)
    add_segment(event["id"], segment_code="SEG-A", mile_start=5, mile_end=10)
    resp = api_client.create_course_segment(
        create_course_segment_payload(event["id"], segment_code="SEG-D",
                                      mile_start=9.5, mile_end=11),
        COORDINATOR)
    validate_error(resp, ApiErrorId.ERR_SEGMENT_MILE_OVERLAP)


# ---------------------------------------------------------------------------
# Role catalog lifecycle (PRD §3.2)
# ---------------------------------------------------------------------------

def test_role_entry_create_applies_defaults(api):
    """PRD §3.2: "The `required_skill` is one of `NONE`, `MEDICAL`,
    `BIKE_MARSHAL`, `TIMING_TECH`, or `COURSE_MARSHAL`, defaulting to `NONE`.
    The `required_training_module` is one of `NONE`, `SAFETY_BRIEFING`,
    `MEDICAL_RESPONSE`, or `CAPTAIN_COURSE`, defaulting to `NONE`, which means
    the role carries no training gate. The `credit_weight` is the
    fundraising-credit hour multiplier for the role: greater than zero, at
    most three, and defaulting to 1.0."
    PRD §3.2: "A new entry starts `ACTIVE`"

    Design: Corner/entities/role_entry_create_applies_defaults
    """
    event = create_event(clock=None)
    resp = api_client.create_role_catalog_entry(
        create_role_catalog_entry_payload(event["id"]), COORDINATOR)
    data = validate_success(resp, expected_status=201)
    assert_role_catalog_entry(data)
    assert data["required_skill"] == "NONE"
    assert data["required_training_module"] == "NONE"
    assert data["credit_weight"] == 1.0
    assert data["status"] == "ACTIVE"


def test_role_suspend_blocks_signup_then_reactivate_restores(api):
    """PRD §3.2: "New signups against shifts of a suspended role are rejected
    with `ERR_ROLE_ENTRY_NOT_ACTIVE`."
    PRD §3.2: "Violations are rejected with `ERR_INVALID_REQUEST`, and a
    referenced role that is not `ACTIVE` rejects the creation with
    `ERR_ROLE_ENTRY_NOT_ACTIVE`."

    Design: Corner/state_machines/role_suspend_blocks_signup_then_reactivate_restores
    """
    ctx = setup_event_with_shift(publish=True,
                                 shift_overrides={"required_headcount": 2})
    ev = ctx["event"]["id"]
    vol = register_eligible_volunteer(ev, full_name="V One", date_of_birth="2000-01-01")
    suspended = validate_success(api_client.suspend_role_entry(ctx["role"]["id"], COORDINATOR))
    assert suspended["status"] == "SUSPENDED"
    blocked_signup = api_client.create_signup(
        {"volunteer_id": vol["id"], "shift_id": ctx["shift"]["id"]}, COORDINATOR)
    validate_error(blocked_signup, ApiErrorId.ERR_ROLE_ENTRY_NOT_ACTIVE)
    blocked_shift = api_client.create_shift(
        create_shift_payload(ev, ctx["role"]["id"], ctx["segment"]["id"],
                             start_at="2026-10-04T12:00:00Z",
                             end_at="2026-10-04T14:00:00Z",
                             required_headcount=1),
        COORDINATOR)
    validate_error(blocked_shift, ApiErrorId.ERR_ROLE_ENTRY_NOT_ACTIVE)
    reactivated = validate_success(api_client.reactivate_role_entry(ctx["role"]["id"], COORDINATOR))
    assert reactivated["status"] == "ACTIVE"
    sg = validate_success(api_client.create_signup(
        {"volunteer_id": vol["id"], "shift_id": ctx["shift"]["id"]}, COORDINATOR),
        expected_status=201)
    assert sg["status"] == "REQUESTED"


def test_role_retire_with_active_signups_rejected(api):
    """PRD §3.2: "Retirement — invoked directly by a coordinator, or
    indirectly when an applied role adjustment carries `proposed_retire`
    (§3.9) — is permitted from `ACTIVE` or `SUSPENDED` and requires zero
    signups in `REQUESTED`, `WAITLISTED`, `APPROVED`, `CONFIRMED`, or
    `CHECKED_IN` status across all shifts of that role (`ERR_ROLE_IN_USE`)."

    Design: Corner/validations/role_retire_with_active_signups_rejected
    """
    ctx = setup_event_with_shift(publish=True)
    ev = ctx["event"]["id"]
    vol = register_eligible_volunteer(ev, full_name="V One", date_of_birth="2000-01-01")
    sg = create_confirmed_signup(vol["id"], ctx["shift"]["id"])
    blocked = api_client.retire_role_entry(ctx["role"]["id"], COORDINATOR)
    validate_error(blocked, ApiErrorId.ERR_ROLE_IN_USE)
    validate_success(api_client.cancel_signup(sg["id"], make_volunteer_headers(vol["id"])))
    retired = validate_success(api_client.retire_role_entry(ctx["role"]["id"], COORDINATOR))
    assert retired["status"] == "RETIRED"


def test_group_and_role_state_guards_rejected(api):
    """PRD §3.3: "Suspending a group (`ACTIVE` to `SUSPENDED`; from any other
    state, `ERR_GROUP_INVALID_STATE`) blocks new affiliations while existing
    members keep their affiliation"
    PRD §3.2: "An `ACTIVE` entry can be suspended, and a `SUSPENDED` entry
    reactivated; attempting either transition from the wrong state is rejected
    with `ERR_ROLE_ENTRY_INVALID_STATE`."

    Design: Corner/errors/group_and_role_state_guards_rejected
    """
    event = create_event(clock=None)
    grp = add_group(event["id"])
    validate_success(api_client.suspend_group(grp["id"], DIRECTOR))
    double_suspend = api_client.suspend_group(grp["id"], DIRECTOR)
    validate_error(double_suspend, ApiErrorId.ERR_GROUP_INVALID_STATE)
    role = add_role(event["id"])
    reactivate_active = api_client.reactivate_role_entry(role["id"], COORDINATOR)
    validate_error(reactivate_active, ApiErrorId.ERR_ROLE_ENTRY_INVALID_STATE)
