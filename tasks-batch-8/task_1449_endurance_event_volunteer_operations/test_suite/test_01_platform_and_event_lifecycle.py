"""Platform contract (identity, envelope, not-found family) and the event
lifecycle from DRAFT through CLOSED / CANCELLED (PRD §2, §3.1, §3.9).
"""
import pytest

from test_helpers import (
    api_client, ApiErrorId, C,
    TEST_USERS, make_volunteer_headers,
    validate_success, validate_error, validate_paginated,
    is_valid_uuid, is_iso8601_timestamp,
    create_event_payload,
    create_event, add_segment, add_role, add_shift, publish_event,
    register_eligible_volunteer, create_confirmed_signup,
    lock_and_start_race_day, set_clock, check_in_signup, check_out_signup,
    fetch_hour_log_for_signup, verify_log, complete_and_open_debrief,
    setup_event_with_shift, request_signup, approve_signup,
    setup_race_day_with_confirmed, add_inventory,
    assert_event, assert_shift, assert_signup,
)

DIRECTOR = TEST_USERS["director_headers"]
COORDINATOR = TEST_USERS["coordinator_headers"]


# ---------------------------------------------------------------------------
# Platform contract
# ---------------------------------------------------------------------------

def test_event_create_applies_defaults_and_system_fields(api):
    """PRD §3.1: "A new event is born in `DRAFT` status with `version` 1."
    PRD §2.6: "`version` (integer): starts at 1 on creation and increments by
    one on every mutation of the resource, including system-initiated
    transitions and cascade-driven changes."

    Design: Corner/entities/event_create_applies_defaults_and_system_fields
    """
    resp = api_client.create_event(create_event_payload(), DIRECTOR)
    body = resp.json()
    assert body.get("response_type") == "object"
    assert isinstance(body.get("meta", {}).get("api_request_id"), str)
    data = validate_success(resp, expected_status=201)
    assert_event(data)
    assert data["status"] == "DRAFT"
    assert data["version"] == 1
    assert data["created_at"] == data["updated_at"]
    assert data["name"] == "City Marathon"
    assert data["event_start_at"] == C.EVENT_START
    assert data["event_end_at"] == C.EVENT_END
    assert data["early_access_opens_at"] == C.EARLY_ACCESS_OPENS
    assert data["signup_opens_at"] == C.SIGNUP_OPENS
    assert data["signup_closes_at"] == C.SIGNUP_CLOSES


def test_missing_auth_headers_rejected(api):
    """PRD §2.1: "A request missing either header, or whose role value does
    not name a declared role, is rejected with
    `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`."
    PRD §2.10: "1. Authentication context: both headers present and the role
    declared (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`)."

    Design: Corner/validations/request_missing_auth_headers_unauthenticated
    """
    resp = api_client.get_event(C.MISSING_UUID, headers={})
    validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)


def test_not_found_errors_for_every_collection(api):
    """PRD §2.7: "The mapping is fixed: `eventId` to `ERR_EVENT_NOT_FOUND`,
    `segmentId` to `ERR_SEGMENT_NOT_FOUND`, `roleEntryId` to
    `ERR_ROLE_ENTRY_NOT_FOUND`, `shiftId` to `ERR_SHIFT_NOT_FOUND`, `groupId`
    to `ERR_GROUP_NOT_FOUND`, `volunteerId` to `ERR_VOLUNTEER_NOT_FOUND`,
    `trainingRecordId` to `ERR_TRAINING_RECORD_NOT_FOUND`, `signupId` to
    `ERR_SIGNUP_NOT_FOUND`, `inventoryId` to `ERR_INVENTORY_NOT_FOUND`,
    `distributionId` to `ERR_DISTRIBUTION_NOT_FOUND`, `hourLogId` to
    `ERR_HOUR_LOG_NOT_FOUND`, `debriefId` to `ERR_DEBRIEF_NOT_FOUND`, and
    `adjustmentId` to `ERR_ADJUSTMENT_NOT_FOUND`. All of these carry HTTP
    status 404."

    Design: Corner/errors/not_found_errors_for_every_collection
    """
    missing = C.MISSING_UUID
    cases = [
        (api_client.get_event(missing, DIRECTOR), ApiErrorId.ERR_EVENT_NOT_FOUND),
        (api_client.get_fundraising_group(missing, DIRECTOR), ApiErrorId.ERR_GROUP_NOT_FOUND),
        (api_client.get_volunteer(missing, COORDINATOR), ApiErrorId.ERR_VOLUNTEER_NOT_FOUND),
        (api_client.get_hour_log(missing, COORDINATOR), ApiErrorId.ERR_HOUR_LOG_NOT_FOUND),
        (api_client.get_role_adjustment(missing, COORDINATOR), ApiErrorId.ERR_ADJUSTMENT_NOT_FOUND),
        (api_client.get_course_segment(missing, COORDINATOR), ApiErrorId.ERR_SEGMENT_NOT_FOUND),
        (api_client.get_role_catalog_entry(missing, COORDINATOR), ApiErrorId.ERR_ROLE_ENTRY_NOT_FOUND),
        (api_client.get_signup(missing, COORDINATOR), ApiErrorId.ERR_SIGNUP_NOT_FOUND),
        (api_client.get_supply_inventory(missing, COORDINATOR), ApiErrorId.ERR_INVENTORY_NOT_FOUND),
        (api_client.get_distribution_record(missing, COORDINATOR), ApiErrorId.ERR_DISTRIBUTION_NOT_FOUND),
        (api_client.get_training_record(missing, COORDINATOR), ApiErrorId.ERR_TRAINING_RECORD_NOT_FOUND),
        (api_client.get_debrief_report(missing, COORDINATOR), ApiErrorId.ERR_DEBRIEF_NOT_FOUND),
    ]
    for resp, expected in cases:
        err = validate_error(resp, expected)
        assert isinstance(err.get("message"), str) and err["message"], \
            f"error envelope for {expected} must carry a human-readable message"


def test_occ_event_patch_stale_rejected(api):
    """PRD §2.9: "Updating an event's configuration requires the request to
    carry `expected_event_version`, holding the client's last observed
    `version` of the event. If the event's current `version` has advanced
    beyond that observed value, the update is rejected with `ERR_STALE_VERSION`
    (HTTP 412), and the client must re-read the event before retrying."

    Design: Corner/complexity_layers/occ_event_patch_stale_rejected
    """
    event = create_event(clock=None)
    observed_version = event["version"]
    first = api_client.patch_event(
        event["id"], {"name": "City Marathon Renamed",
                      "expected_event_version": observed_version}, DIRECTOR)
    data = validate_success(first, expected_status=200)
    assert data["name"] == "City Marathon Renamed"
    assert data["version"] == observed_version + 1
    replay = api_client.patch_event(
        event["id"], {"name": "City Marathon Third",
                      "expected_event_version": observed_version}, DIRECTOR)
    validate_error(replay, ApiErrorId.ERR_STALE_VERSION)
    stored = validate_success(api_client.get_event(event["id"], DIRECTOR))
    assert stored["name"] == "City Marathon Renamed"
    assert stored["version"] == observed_version + 1


# ---------------------------------------------------------------------------
# Event lifecycle gates (PRD §3.1)
# ---------------------------------------------------------------------------

def test_publish_without_readiness_rejected(api):
    """PRD §3.1: "Publishing moves the event from `DRAFT` to `PUBLISHED` and
    gates on a readiness invariant: at least one role catalog entry in `ACTIVE`
    status, at least one course segment, and at least one shift must exist for
    the event. Any shortfall is rejected with `ERR_EVENT_READINESS_INCOMPLETE`."

    Design: Corner/state_machines/publish_without_readiness_rejected
    """
    event = create_event(clock=None)
    seg = add_segment(event["id"])
    role = add_role(event["id"])
    first = api_client.publish_event(event["id"], DIRECTOR)
    validate_error(first, ApiErrorId.ERR_EVENT_READINESS_INCOMPLETE)
    add_shift(event["id"], role["id"], seg["id"])
    second = api_client.publish_event(event["id"], DIRECTOR)
    data = validate_success(second, expected_status=200)
    assert data["status"] == "PUBLISHED"


def test_event_timing_guards_rejected(api):
    """PRD §3.1: "Starting race day moves the event from `LOCKED` to
    `RACE_DAY` and requires the logical clock to have reached `event_start_at`;
    an early attempt is rejected with `ERR_EVENT_NOT_YET_STARTED`."
    PRD §3.1: "Completing the event moves it from `RACE_DAY` to `COMPLETED`
    and carries two gates: the clock must be at or past `event_end_at`
    (`ERR_EVENT_NOT_YET_ENDED`)"

    Design: Corner/errors/event_timing_guards_rejected
    """
    ctx = setup_event_with_shift(publish=True)
    ev = ctx["event"]["id"]
    get_ok = validate_success(api_client.lock_signups(ev, DIRECTOR))
    assert get_ok["status"] == "LOCKED"
    set_clock("2026-10-03T23:00:00Z")
    early = api_client.start_race_day(ev, DIRECTOR)
    validate_error(early, ApiErrorId.ERR_EVENT_NOT_YET_STARTED)
    set_clock(C.EVENT_START)
    started = validate_success(api_client.start_race_day(ev, DIRECTOR))
    assert started["status"] == "RACE_DAY"
    set_clock("2026-10-04T21:00:00Z")
    early_complete = api_client.complete_event(ev, DIRECTOR)
    validate_error(early_complete, ApiErrorId.ERR_EVENT_NOT_YET_ENDED)


def test_complete_with_checked_in_signup_rejected(api):
    """PRD §3.1: "Completing the event moves it from `RACE_DAY` to `COMPLETED`
    and carries two gates: the clock must be at or past `event_end_at`
    (`ERR_EVENT_NOT_YET_ENDED`), and zero signups of the event may remain in
    `CHECKED_IN` status — no one may still be on the course —
    (`ERR_SIGNUPS_STILL_ON_COURSE`)."

    Design: Corner/state_machines/complete_with_checked_in_signup_rejected
    """
    ctx = setup_race_day_with_confirmed(
        [{"full_name": "V One", "date_of_birth": "2000-01-01"}],
        shift_overrides={"start_at": "2026-10-04T06:00:00Z",
                         "end_at": "2026-10-04T14:00:00Z",
                         "required_headcount": 1},
        checkin_at="2026-10-04T06:00:00Z")
    sg = ctx["signups"][0]
    check_in_signup(sg["id"])
    set_clock(C.EVENT_END)
    blocked = api_client.complete_event(ctx["event"]["id"], DIRECTOR)
    validate_error(blocked, ApiErrorId.ERR_SIGNUPS_STILL_ON_COURSE)
    check_out_signup(sg["id"], C.EVENT_END)
    done = validate_success(api_client.complete_event(ctx["event"]["id"], DIRECTOR))
    assert done["status"] == "COMPLETED"


# ---------------------------------------------------------------------------
# Close-out (PRD §3.9)
# ---------------------------------------------------------------------------

def _drive_to_debrief_open_with_resolved_log(api):
    """Full happy path: one signup worked 06:00-10:00, log VERIFIED, event in
    DEBRIEF_OPEN with the shift still IN_PROGRESS. Returns (ctx, hour_log)."""
    ctx = setup_race_day_with_confirmed(
        [{"full_name": "V One", "date_of_birth": "2000-01-01"}],
        shift_overrides={"start_at": "2026-10-04T06:00:00Z",
                         "end_at": "2026-10-04T10:00:00Z",
                         "required_headcount": 1},
        checkin_at="2026-10-04T06:00:00Z")
    sg = ctx["signups"][0]
    check_in_signup(sg["id"])
    check_out_signup(sg["id"], "2026-10-04T10:00:00Z")
    log = fetch_hour_log_for_signup(sg["id"])
    complete_and_open_debrief(ctx["event"]["id"])
    return ctx, log


def test_event_close_happy_then_terminal_lockdown(api):
    """PRD §3.9: "Closing the event — `DEBRIEF_OPEN` to terminal `CLOSED` —
    then demands four conditions, each enforced as `ERR_EVENT_CLOSE_BLOCKED`:
    zero hour logs of the event in `PENDING_VERIFICATION` or `DISPUTED` status;
    zero debrief reports still `SUBMITTED`; zero role adjustments in `PROPOSED`
    or `APPROVED` status; and every shift of the event in `RECONCILED` or
    `CANCELLED` status."
    PRD §3.1: "Cancellation is available from `DRAFT`, `PUBLISHED`, `LOCKED`,
    `RACE_DAY`, and `COMPLETED`, always landing in terminal `CANCELLED`"

    Design: Corner/state_machines/event_close_happy_then_terminal_lockdown
    """
    ctx, log = _drive_to_debrief_open_with_resolved_log(api)
    verify_log(log["id"])
    reconciled = validate_success(api_client.reconcile_shift(ctx["shift"]["id"], COORDINATOR))
    assert reconciled["status"] == "RECONCILED"
    closed = validate_success(api_client.close_event(ctx["event"]["id"], DIRECTOR))
    assert closed["status"] == "CLOSED"
    late_cancel = api_client.cancel_event(ctx["event"]["id"], DIRECTOR)
    validate_error(late_cancel, ApiErrorId.ERR_INVALID_EVENT_STATE)


def test_event_close_blocked_by_pending_hourlog(api):
    """PRD §3.9: "Closing the event — `DEBRIEF_OPEN` to terminal `CLOSED` —
    then demands four conditions, each enforced as `ERR_EVENT_CLOSE_BLOCKED`:
    zero hour logs of the event in `PENDING_VERIFICATION` or `DISPUTED`
    status; zero debrief reports still `SUBMITTED`; zero role adjustments in
    `PROPOSED` or `APPROVED` status; and every shift of the event in
    `RECONCILED` or `CANCELLED` status."

    Design: Corner/state_machines/event_close_blocked_by_pending_hourlog
    """
    ctx, log = _drive_to_debrief_open_with_resolved_log(api)
    # The log stays PENDING_VERIFICATION; the shift itself can be reconciled
    # because its signup is COMPLETED (not CONFIRMED / CHECKED_IN).
    reconciled = validate_success(api_client.reconcile_shift(ctx["shift"]["id"], COORDINATOR))
    assert reconciled["status"] == "RECONCILED"
    blocked = api_client.close_event(ctx["event"]["id"], DIRECTOR)
    validate_error(blocked, ApiErrorId.ERR_EVENT_CLOSE_BLOCKED)
    still = validate_success(api_client.get_event(ctx["event"]["id"], DIRECTOR))
    assert still["status"] == "DEBRIEF_OPEN"


# ---------------------------------------------------------------------------
# Cancellation cascades (PRD §3.1)
# ---------------------------------------------------------------------------

def _setup_race_day_cancel_scenario(api):
    """RACE_DAY; shift headcount 2; sg1 CHECKED_IN holding one credential and
    one SAFETY_VEST (inventory total 1); sg2 CONFIRMED."""
    ctx = setup_race_day_with_confirmed(
        [{"full_name": "V One", "date_of_birth": "2000-01-01"},
         {"full_name": "V Two", "date_of_birth": "2000-01-02"}],
        shift_overrides={"start_at": "2026-10-04T06:00:00Z",
                         "end_at": "2026-10-04T14:00:00Z",
                         "required_headcount": 2},
        checkin_at="2026-10-04T06:00:00Z")
    inv = add_inventory(ctx["event"]["id"], quantity_total=1)
    sg1, sg2 = ctx["signups"]
    check_in_signup(sg1["id"])
    dist = validate_success(api_client.create_distribution_record(
        {"signup_id": sg1["id"], "kind": "SUPPLY_ITEM", "inventory_id": inv["id"]},
        COORDINATOR), expected_status=201)
    ctx["inventory"] = inv
    ctx["supply_record"] = dist
    return ctx


def test_event_cancel_deep_cascade_statuses(api):
    """PRD §3.1: "Cancellation is available from `DRAFT`, `PUBLISHED`,
    `LOCKED`, `RACE_DAY`, and `COMPLETED`, always landing in terminal
    `CANCELLED`, and always running the same three-link cascade. Link one:
    every shift of the event in `OPEN`, `FULL`, `LOCKED`, or `IN_PROGRESS`
    status becomes `CANCELLED`. Link two: every signup on those shifts in
    `REQUESTED`, `WAITLISTED`, `APPROVED`, `CONFIRMED`, or `CHECKED_IN` status
    becomes `CANCELLED`"

    Design: Difficulty/transitive_cascade/event_cancel_deep_cascade
    """
    ctx = _setup_race_day_cancel_scenario(api)
    cancelled = validate_success(api_client.cancel_event(ctx["event"]["id"], DIRECTOR))
    assert cancelled["status"] == "CANCELLED"
    shift = validate_success(api_client.get_shift(ctx["shift"]["id"], COORDINATOR))
    assert shift["status"] == "CANCELLED", "IN_PROGRESS shift must cascade to CANCELLED"
    sg1 = validate_success(api_client.get_signup(ctx["signups"][0]["id"], COORDINATOR))
    sg2 = validate_success(api_client.get_signup(ctx["signups"][1]["id"], COORDINATOR))
    assert sg1["status"] == "CANCELLED", "CHECKED_IN signup must cascade to CANCELLED"
    assert sg2["status"] == "CANCELLED", "CONFIRMED signup must cascade to CANCELLED"


def test_event_cancel_deep_cascade_revokes_distributions(api):
    """PRD §3.1: "Link three: every distribution record on a cancelled signup
    still in `ISSUED` status becomes `REVOKED`, and revoked records of `kind`
    `SUPPLY_ITEM` decrement the owning inventory's `quantity_issued`, returning
    those units to stock."

    Design: Difficulty/transitive_cascade/event_cancel_deep_cascade
    """
    ctx = _setup_race_day_cancel_scenario(api)
    before = validate_success(api_client.get_supply_inventory(ctx["inventory"]["id"], COORDINATOR))
    assert before["quantity_issued"] == 1
    validate_success(api_client.cancel_event(ctx["event"]["id"], DIRECTOR))
    creds, meta = validate_paginated(api_client.list_distribution_records(
        COORDINATOR, params={"signup_id": ctx["signups"][0]["id"], "kind": "CREDENTIAL"}))
    assert len(creds) == 1
    assert creds[0]["status"] == "REVOKED", "auto-issued credential must be revoked"
    supply = validate_success(api_client.get_distribution_record(
        ctx["supply_record"]["id"], COORDINATOR))
    assert supply["status"] == "REVOKED"
    after = validate_success(api_client.get_supply_inventory(ctx["inventory"]["id"], COORDINATOR))
    assert after["quantity_issued"] == 0, "supply revoke must restore stock to pre-issue level"


def test_cascades_skip_terminal_children(api):
    """PRD §3.1: "Link two: every signup on those shifts in `REQUESTED`,
    `WAITLISTED`, `APPROVED`, `CONFIRMED`, or `CHECKED_IN` status becomes
    `CANCELLED`"

    Design: Corner/complexity_layers/cascades_skip_terminal_children
    """
    ctx = setup_event_with_shift(publish=True,
                                 shift_overrides={"required_headcount": 2})
    ev = ctx["event"]["id"]
    v1 = register_eligible_volunteer(ev, full_name="V One", date_of_birth="2000-01-01")
    v2 = register_eligible_volunteer(ev, full_name="V Two", date_of_birth="2000-01-02")
    sg1 = request_signup(v1["id"], ctx["shift"]["id"])
    sg2 = request_signup(v2["id"], ctx["shift"]["id"])
    validate_success(api_client.cancel_signup(sg2["id"], make_volunteer_headers(v2["id"])))
    cancelled = validate_success(api_client.cancel_event(ev, DIRECTOR))
    assert cancelled["status"] == "CANCELLED"
    s1 = validate_success(api_client.get_signup(sg1["id"], COORDINATOR))
    s2 = validate_success(api_client.get_signup(sg2["id"], COORDINATOR))
    assert s1["status"] == "CANCELLED", "REQUESTED signup must be cancelled by the cascade"
    assert s2["status"] == "CANCELLED", "already-CANCELLED signup must be left untouched"
