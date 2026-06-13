"""Workflows, cascades, and state transitions: shift-complete no-show suspension,
group approval preconditions, invalid transitions, time-gated preconditions, the
shift-cancel and opportunity-close cascades, staffing bubble-up, immediate
consistency, and corporate-group lifecycle.

Queue A (Difficulty): transitive_cascade, cross_entity_state_dependency.
Queue B (Corner): state_machines, calculations (staffing), errors, consistency_model.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId,
    create_corporate_group_payload,
)
from test_helpers.fixtures import (
    create_organization, create_volunteer, create_opportunity, create_shift,
    publish_opportunity, set_clock, get_shift, get_signup, get_volunteer,
    create_signup, create_confirmed_signup, create_reserved_signup,
    setup_signup_ready, setup_approved_corporate_group, SPONSOR,
)
from test_helpers.test_users import TEST_USERS, make_volunteer_headers

COORD = TEST_USERS["shift_coordinator_headers"]


# ─── Transitive cascade: complete -> no-show -> suspend ────────────────────

def test_shift_complete_no_show_suspends_volunteer(api):
    """PRD §3.3: "every signup still in `CONFIRMED` with no attendance decision is moved
    to `NO_SHOW`, and each such transition runs the per-signup no-show reliability
    cascade described in §3.5."
    PRD §3.5: "If, after the recompute, the volunteer's `reliability_score` is strictly
    below the organization's `reliability_suspension_threshold`, or the volunteer's
    `lifetime_no_show_count` is greater than or equal to the organization's
    `no_show_strike_limit`, the volunteer's `status` is transitioned to `SUSPENDED`."

    Design: Difficulty/transitive_cascade/shift_complete_no_show_suspends_volunteer_depth3
    """
    org = create_organization(headers=COORD, reliability_suspension_threshold=40, no_show_strike_limit=9)
    set_clock("2026-06-15T00:00:00Z", headers=COORD)
    vol = create_volunteer(org["id"], headers=COORD)
    opp = create_opportunity(org["id"], headers=COORD)
    shift = create_shift(opp["id"], "2026-07-01T09:00:00Z", "2026-07-01T12:00:00Z", 1, headers=COORD)
    publish_opportunity(opp["id"], headers=COORD)
    su = create_confirmed_signup(shift, vol["id"])

    set_clock("2026-07-01T12:30:00Z", headers=COORD)
    validate_success(api.complete_shift(shift["id"], COORD))

    su_after = get_signup(su["id"], headers=COORD)
    assert su_after["status"] == "NO_SHOW", f"expected NO_SHOW, got {su_after['status']}"
    vol_after = get_volunteer(vol["id"], headers=COORD)
    # 0 kept, 1 broken -> raw = 0 - 8 = -8 -> clamp 0; 0 < 40 -> SUSPENDED.
    assert vol_after["reliability_score"] == 0, \
        f"expected reliability 0, got {vol_after['reliability_score']}"
    assert vol_after["status"] == "SUSPENDED", \
        f"reliability 0 < threshold 40 must suspend, got {vol_after['status']}"


def test_shift_complete_no_show_releases_seat(api):
    """PRD §3.5: "the seat is released, decrementing the parent shift's `reserved_count`
    by one and returning the shift from `FULL` to `OPEN` (with the staffing bubble-up)
    if it now sits below capacity."

    Design: Difficulty/transitive_cascade/shift_complete_no_show_suspends_volunteer_depth3
    """
    org = create_organization(headers=COORD, reliability_suspension_threshold=40, no_show_strike_limit=9)
    set_clock("2026-06-15T00:00:00Z", headers=COORD)
    vol = create_volunteer(org["id"], headers=COORD)
    opp = create_opportunity(org["id"], headers=COORD)
    shift = create_shift(opp["id"], "2026-07-01T09:00:00Z", "2026-07-01T12:00:00Z", 1, headers=COORD)
    publish_opportunity(opp["id"], headers=COORD)
    su = create_confirmed_signup(shift, vol["id"])
    full = get_shift(shift["id"], headers=COORD)
    assert full["reserved_count"] == 1 and full["status"] == "FULL"

    set_clock("2026-07-01T12:30:00Z", headers=COORD)
    validate_success(api.complete_shift(shift["id"], COORD))

    su_after = get_signup(su["id"], headers=COORD)
    assert su_after["status"] == "NO_SHOW", f"expected NO_SHOW, got {su_after['status']}"
    sh_after = get_shift(shift["id"], headers=COORD)
    assert sh_after["reserved_count"] == 0, \
        f"no-show cascade must release the seat; expected reserved_count 0, got {sh_after['reserved_count']}"


def test_group_approve_requires_published_group_event(api):
    """PRD §3.7: "Approval moves it from `PROPOSED` to `APPROVED` and requires three
    things: the group must currently be `PROPOSED` (else `ERR_GROUP_NOT_PROPOSED`), the
    parent opportunity must have `is_group_event` set to true (else
    `ERR_OPPORTUNITY_NOT_GROUP_EVENT`), and the parent opportunity's
    `publication_status` must be `PUBLISHED` (else `ERR_OPPORTUNITY_NOT_PUBLISHED`)."

    Design: Difficulty/cross_entity_state_dependency/group_approve_requires_opportunity_published_and_group_event
    """
    org = create_organization(headers=COORD)
    set_clock("2026-06-15T00:00:00Z", headers=COORD)
    # DRAFT (not published) group-event opportunity with a shift and a PROPOSED group.
    opp = create_opportunity(org["id"], headers=COORD, is_group_event=True)
    shift = create_shift(opp["id"], "2026-07-01T09:00:00Z", "2026-07-01T12:00:00Z", 10, headers=COORD)
    grp = validate_success(
        api.create_corporate_group(
            create_corporate_group_payload(opp["id"], shift["id"], 4), SPONSOR),
        expected_status=201)

    resp = api.approve_corporate_group(grp["id"], COORD)
    validate_error(resp, ApiErrorId.ERR_OPPORTUNITY_NOT_PUBLISHED.value)


def test_group_approve_requires_group_event_opportunity(api):
    """PRD §3.7: "the parent opportunity must have `is_group_event` set to true (else
    `ERR_OPPORTUNITY_NOT_GROUP_EVENT`)."

    Design: Difficulty/cross_entity_state_dependency/group_approve_requires_opportunity_published_and_group_event
    """
    org = create_organization(headers=COORD)
    set_clock("2026-06-15T00:00:00Z", headers=COORD)
    # PUBLISHED opportunity but is_group_event defaults to false.
    opp = create_opportunity(org["id"], headers=COORD)
    shift = create_shift(opp["id"], "2026-07-01T09:00:00Z", "2026-07-01T12:00:00Z", 10, headers=COORD)
    publish_opportunity(opp["id"], headers=COORD)
    grp = validate_success(
        api.create_corporate_group(
            create_corporate_group_payload(opp["id"], shift["id"], 2), SPONSOR),
        expected_status=201)

    resp = api.approve_corporate_group(grp["id"], COORD)
    validate_error(resp, ApiErrorId.ERR_OPPORTUNITY_NOT_GROUP_EVENT.value)


# ─── Corner: invalid transitions & terminal lockdown ───────────────────────

def test_confirm_already_confirmed_signup_rejected(api):
    """PRD §3.4: "confirmation requires the signup to currently be `RESERVED` (else
    `ERR_SIGNUP_NOT_RESERVED`)."

    Design: Corner/state_machines/confirm_already_confirmed_signup_rejected
    """
    org, vol, opp, shift = setup_signup_ready(capacity=2)
    su = create_confirmed_signup(shift, vol["id"])
    resp = api.confirm_signup(su["id"], make_volunteer_headers(vol["id"]))
    validate_error(resp, ApiErrorId.ERR_SIGNUP_NOT_RESERVED.value)


def test_cancel_cancelled_signup_terminal_lockdown(api):
    """PRD §3.4: "A volunteer may cancel a signup while it is `RESERVED` or `CONFIRMED`
    (else `ERR_SIGNUP_NOT_CANCELLABLE`), again only on a signup they own."

    Design: Corner/state_machines/cancel_cancelled_signup_terminal_lockdown
    """
    org, vol, opp, shift = setup_signup_ready(capacity=2)
    su, _ = create_reserved_signup(shift, vol["id"])
    validate_success(api.cancel_signup(su["id"], make_volunteer_headers(vol["id"])))
    resp = api.cancel_signup(su["id"], make_volunteer_headers(vol["id"]))
    validate_error(resp, ApiErrorId.ERR_SIGNUP_NOT_CANCELLABLE.value)


def test_publish_opportunity_without_shifts_rejected(api):
    """PRD §3.3: "this requires the opportunity to currently be `DRAFT` (else
    `ERR_OPPORTUNITY_NOT_DRAFT`) and to have at least one child shift (else
    `ERR_OPPORTUNITY_HAS_NO_SHIFTS`)."

    Design: Corner/state_machines/publish_opportunity_without_shifts_rejected
    """
    org = create_organization(headers=COORD)
    opp = create_opportunity(org["id"], headers=COORD)
    resp = api.publish_opportunity(opp["id"], COORD)
    validate_error(resp, ApiErrorId.ERR_OPPORTUNITY_HAS_NO_SHIFTS.value)


def test_complete_shift_before_ends_at_rejected(api):
    """PRD §3.3: "Completing a shift is permitted only while it is `OPEN` or `FULL`
    (else `ERR_SHIFT_NOT_COMPLETABLE`) and only once the current clock has reached or
    passed the shift's `ends_at` (else `ERR_SHIFT_NOT_ENDED`)."

    Design: Corner/state_machines/complete_shift_before_ends_at_rejected
    """
    org = create_organization(headers=COORD)
    set_clock("2026-06-15T00:00:00Z", headers=COORD)
    opp = create_opportunity(org["id"], headers=COORD)
    shift = create_shift(opp["id"], "2026-07-01T09:00:00Z", "2026-07-01T12:00:00Z", 2, headers=COORD)
    publish_opportunity(opp["id"], headers=COORD)
    # Clock (2026-06-15) is before ends_at (2026-07-01T12:00).
    resp = api.complete_shift(shift["id"], COORD)
    validate_error(resp, ApiErrorId.ERR_SHIFT_NOT_ENDED.value)


def test_check_in_before_shift_start_rejected(api):
    """PRD §3.5: "Check-in requires the signup to currently be `CONFIRMED` (else
    `ERR_SIGNUP_NOT_CONFIRMED`) and the current clock to have reached or passed the
    parent shift's `starts_at` (else `ERR_SHIFT_NOT_STARTED`)."

    Design: Corner/state_machines/check_in_before_shift_start_rejected
    """
    org, vol, opp, shift = setup_signup_ready(capacity=2)
    su = create_confirmed_signup(shift, vol["id"])
    # Clock still at base (2026-06-15), before shift starts_at (2026-07-01T09:00).
    resp = api.check_in_signup(su["id"], COORD)
    validate_error(resp, ApiErrorId.ERR_SHIFT_NOT_STARTED.value)


def test_log_hours_exceeding_shift_duration_rejected(api):
    """PRD §3.6: "The reported hours must be greater than zero (else
    `ERR_INVALID_HOURS`) and must not exceed the shift's scheduled duration in hours
    (else `ERR_HOURS_EXCEED_SHIFT`, returned at HTTP 422)."

    Design: Corner/state_machines/log_hours_exceeding_shift_duration_rejected
    """
    org, vol, opp, shift = setup_signup_ready(
        capacity=2, starts_at="2026-07-01T09:00:00Z", ends_at="2026-07-01T12:00:00Z")
    su = create_confirmed_signup(shift, vol["id"])
    set_clock("2026-07-01T12:30:00Z", headers=COORD)
    validate_success(api.check_in_signup(su["id"], COORD))
    # 4.0 > scheduled 3.0h.
    resp = api.log_hours_signup(su["id"], {"logged_hours": 4.0}, make_volunteer_headers(vol["id"]))
    validate_error(resp, ApiErrorId.ERR_HOURS_EXCEED_SHIFT.value)


# ─── Corner: side-effect cascades ──────────────────────────────────────────

def test_shift_cancel_cascades_signup_to_cancelled(api):
    """PRD §3.3: "every seat-holding signup in `RESERVED` or `CONFIRMED` is moved to
    `CANCELLED` and its seat released, with no reliability penalty applied to the
    volunteer."

    Design: Corner/state_machines/shift_cancel_cascades_signup_to_cancelled
    """
    org, vol, opp, shift = setup_signup_ready(capacity=2)
    su, _ = create_reserved_signup(shift, vol["id"])
    cancelled = validate_success(api.cancel_shift(shift["id"], COORD))
    assert cancelled["status"] == "CANCELLED", f"shift expected CANCELLED, got {cancelled['status']}"
    su_after = get_signup(su["id"], headers=COORD)
    assert su_after["status"] == "CANCELLED", \
        f"seat-holding signup must cascade to CANCELLED, got {su_after['status']}"


def test_corporate_group_allocate_creates_group_signups(api):
    """PRD §3.7: "On success the server creates `requested_seats` group-placeholder
    signups on the target shift, each in `RESERVED` with `corporate_group_id` set to
    this group, each occupying a seat; it raises the shift's `reserved_count` and its
    `group_reserved_seats` by `requested_seats`; it sets the group's
    `allocated_seat_count` to `requested_seats`."

    Design: Corner/state_machines/corporate_group_allocate_creates_group_signups
    """
    org, opp, shift, grp = setup_approved_corporate_group(requested_seats=3, capacity=10)
    sh = get_shift(shift["id"], headers=COORD)
    allocated = validate_success(
        api.allocate_corporate_group(grp["id"], {"expected_shift_version": sh["version"]}, COORD))
    assert allocated["status"] == "ALLOCATED", f"expected ALLOCATED, got {allocated['status']}"
    assert allocated["allocated_seat_count"] == 3, \
        f"expected allocated_seat_count 3, got {allocated['allocated_seat_count']}"

    sh_after = get_shift(shift["id"], headers=COORD)
    assert sh_after["reserved_count"] == 3, \
        f"expected reserved_count 3, got {sh_after['reserved_count']}"
    body, meta = validate_paginated(
        api.list_signups(COORD, params={"corporate_group_id": grp["id"]}))
    assert meta["total_count"] == 3, f"expected 3 group signups, got {meta['total_count']}"
    assert all(s["status"] == "RESERVED" for s in body), "all group signups should be RESERVED"


def test_staffing_status_fully_staffed_when_all_shifts_full(api):
    """PRD §3.4: "if that occupancy brings `reserved_count` to `capacity`, the shift
    moves from `OPEN` to `FULL` and the parent opportunity's `staffing_status` is
    re-evaluated."
    PRD §3.3: "If every shift in the considered set is `FULL` or `COMPLETED`, the
    opportunity is `FULLY_STAFFED`."

    Design: Corner/state_machines/staffing_status_fully_staffed_when_all_shifts_full
    """
    org, vol, opp, shift = setup_signup_ready(capacity=1)
    before = validate_success(api.get_opportunity(opp["id"], COORD))
    assert before["staffing_status"] == "UNDERSTAFFED", \
        f"before signup expected UNDERSTAFFED, got {before['staffing_status']}"

    sh = get_shift(shift["id"], headers=COORD)
    create_signup(sh["id"], vol["id"], sh["version"])
    after = validate_success(api.get_opportunity(opp["id"], COORD))
    assert after["staffing_status"] == "FULLY_STAFFED", \
        f"after the only seat fills expected FULLY_STAFFED, got {after['staffing_status']}"


def test_staffing_status_empty_set_is_understaffed(api):
    """PRD §3.3: "If that considered set is empty, the opportunity is `UNDERSTAFFED`."
    PRD §3.3: "An opportunity with no non-cancelled shifts is therefore `UNDERSTAFFED`,
    never `FULLY_STAFFED`."

    Design: Corner/calculations/staffing_status_empty_set_is_understaffed
    """
    org = create_organization(headers=COORD)
    set_clock("2026-06-15T00:00:00Z", headers=COORD)
    opp = create_opportunity(org["id"], headers=COORD)
    shift = create_shift(opp["id"], "2026-07-01T09:00:00Z", "2026-07-01T12:00:00Z", 1, headers=COORD)
    publish_opportunity(opp["id"], headers=COORD)
    validate_success(api.cancel_shift(shift["id"], COORD))
    opp_after = validate_success(api.get_opportunity(opp["id"], COORD))
    assert opp_after["staffing_status"] == "UNDERSTAFFED", \
        f"only shift CANCELLED -> empty considered set -> UNDERSTAFFED, got {opp_after['staffing_status']}"


def test_close_opportunity_cascade_visible_immediately(api):
    """PRD §3.3: "Closing cascades downward: every child shift currently in `OPEN` or
    `FULL` is moved to `CANCELLED`."
    PRD §2.5: "every cascade triggered by a request completes inside that same request,
    never deferred."

    Design: Corner/consistency_model/cascade_visible_in_same_request_immediate
    """
    org = create_organization(headers=COORD)
    set_clock("2026-06-15T00:00:00Z", headers=COORD)
    opp = create_opportunity(org["id"], headers=COORD)
    shift = create_shift(opp["id"], "2026-07-01T09:00:00Z", "2026-07-01T12:00:00Z", 2, headers=COORD)
    publish_opportunity(opp["id"], headers=COORD)

    closed = validate_success(api.close_opportunity(opp["id"], COORD))
    assert closed["publication_status"] == "CLOSED", \
        f"expected CLOSED, got {closed['publication_status']}"
    sh_after = get_shift(shift["id"], headers=COORD)
    assert sh_after["status"] == "CANCELLED", \
        f"child shift must be CANCELLED immediately after close, got {sh_after['status']}"


# ─── Corner: corporate-group errors ────────────────────────────────────────

def test_group_allocate_insufficient_capacity_rejected(api):
    """PRD §3.7: "the shift's remaining capacity — its `capacity` minus its
    `reserved_count` — must be at least the `requested_seats` (else
    `ERR_INSUFFICIENT_SHIFT_CAPACITY`)."

    Design: Corner/errors/group_allocate_insufficient_capacity_rejected
    """
    org, opp, shift, grp = setup_approved_corporate_group(requested_seats=5, capacity=3)
    sh = get_shift(shift["id"], headers=COORD)
    resp = api.allocate_corporate_group(grp["id"], {"expected_shift_version": sh["version"]}, COORD)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_SHIFT_CAPACITY.value)


def test_group_cancel_after_allocated_rejected(api):
    """PRD §3.7: "A sponsor may cancel a group while it is `PROPOSED` or `APPROVED`
    (else `ERR_GROUP_NOT_CANCELLABLE`), moving it to `CANCELLED`."

    Design: Corner/errors/group_cancel_after_allocated_rejected
    """
    org, opp, shift, grp = setup_approved_corporate_group(requested_seats=2, capacity=10)
    sh = get_shift(shift["id"], headers=COORD)
    validate_success(
        api.allocate_corporate_group(grp["id"], {"expected_shift_version": sh["version"]}, COORD))
    resp = api.cancel_corporate_group(grp["id"], SPONSOR)
    validate_error(resp, ApiErrorId.ERR_GROUP_NOT_CANCELLABLE.value)
