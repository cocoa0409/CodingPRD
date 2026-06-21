"""Gate admission and access sessions: space single-occupancy, void side effects,
terminal lockdown, gate-mode policy, time-range validation, transient-in-permit-zone,
and the event-window half-open overlap rule on publish.

PRD §3.5 governs admission/exit/void; §3.2 event-window well-formedness.
"""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    TEST_USERS,
    setup_transient_facility,
    setup_open_transient_session,
    setup_garage_with_zone,
    create_garage,
    create_event_window,
    publish_event_window,
    create_space,
    set_clock,
    open_session,
    get_space,
    get_garage,
    create_session_payload,
)

ADMIN = TEST_USERS["facility_admin_headers"]


def test_space_single_occupant_overlap_rejected(api):
    """PRD §3.5: "if no `AVAILABLE` and unoccupied space remains in an eligible zone
    — that is, the stall the gate would assign is already held by a time-overlapping
    `OPEN` occupation — the entry is rejected with `ERR_SPACE_OCCUPIED`."

    Single-space zone already has one OPEN session → second entry rejected.

    Design: Difficulty/resource_temporal_overlap/space_single_occupant_overlap_on_entry
    """
    ctx = setup_open_transient_session(plate="OCC111", entry_at_utc="2026-06-01T10:00:00Z",
                                       num_spaces=1, hourly_cents=500, daily_cap_cents=4000,
                                       monthly_permit_cents=9000, grace_minutes=15)
    resp = api.create_session(
        create_session_payload(ctx["garage"]["id"], "OCC222", "2026-06-01T10:05:00Z"), ADMIN
    )
    validate_error(resp, ApiErrorId.ERR_SPACE_OCCUPIED.value)


def test_event_window_half_open_overlap_on_publish_rejected(api):
    """PRD §3.2: "Publishing is rejected with `ERR_EVENT_WINDOW_OVERLAP` if the
    window's half-open interval overlaps that of any other already-`PUBLISHED`
    window for the same garage."

    PUBLISHED [09:00,12:00); publishing [11:00,14:00) overlaps → rejected, stays DRAFT.

    Design: Difficulty/resource_temporal_overlap/event_window_half_open_overlap_on_publish
    """
    garage = create_garage(name="G")
    e1 = create_event_window(garage["id"], "2026-06-01T09:00:00Z", "2026-06-01T12:00:00Z",
                             flat_surcharge_cents=1000, name="E1")
    publish_event_window(e1["id"])
    e2 = create_event_window(garage["id"], "2026-06-01T11:00:00Z", "2026-06-01T14:00:00Z",
                             flat_surcharge_cents=500, name="E2")
    resp = api.publish_event_pricing(e2["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_EVENT_WINDOW_OVERLAP.value)
    assert validate_success(api.get_event_pricing(e2["id"], ADMIN))["status"] == "DRAFT"


def test_void_open_session_frees_space_and_decrements_garage(api):
    """PRD §3.5: "A `FacilityAdmin` may instead void an `OPEN` session — a gate-error
    correction — moving it from `OPEN` to `VOIDED` (rejecting with
    `ERR_INVALID_STATE` if it is not `OPEN`); voiding likewise frees the space and
    decrements the garage's `occupied_count` but computes no charges."

    Design: Corner/state_machines/void_open_session_frees_space
    """
    ctx = setup_open_transient_session(plate="VOI111", entry_at_utc="2026-06-01T10:00:00Z",
                                       num_spaces=1, hourly_cents=500, daily_cap_cents=4000,
                                       monthly_permit_cents=9000, grace_minutes=15)
    space = ctx["spaces"][0]
    voided = validate_success(api.void_session(ctx["session"]["id"], ADMIN))
    assert voided["status"] == "VOIDED"
    assert get_space(space["id"])["is_occupied"] is False
    assert get_garage(ctx["garage"]["id"])["occupied_count"] == 0


def test_re_exit_closed_session_returns_invalid_state(api):
    """PRD §3.5: "Exit requires the session to be `OPEN`, rejecting otherwise with
    `ERR_INVALID_STATE`".

    Design: Corner/state_machines/exit_terminal_closed_session_returns_invalid_state
    """
    ctx = setup_open_transient_session(plate="TRM111", entry_at_utc="2026-06-01T10:00:00Z",
                                       num_spaces=1, hourly_cents=500, daily_cap_cents=4000,
                                       monthly_permit_cents=9000, grace_minutes=15)
    validate_success(api.exit_session(ctx["session"]["id"], {"exit_at_utc": "2026-06-01T11:00:00Z"}, ADMIN))
    resp = api.exit_session(ctx["session"]["id"], {"exit_at_utc": "2026-06-01T12:00:00Z"}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_exit_at_equal_to_entry_returns_invalid_time_range(api):
    """PRD §3.5: "requires `exit_at_utc` to fall strictly after the session's
    `entry_at_utc`, rejecting otherwise with `ERR_INVALID_TIME_RANGE`."

    Design: Corner/validations/exit_with_invalid_time_range_returns_invalid_time_range
    """
    ctx = setup_open_transient_session(plate="TIM111", entry_at_utc="2026-06-01T10:00:00Z",
                                       num_spaces=1, hourly_cents=500, daily_cap_cents=4000,
                                       monthly_permit_cents=9000, grace_minutes=15)
    resp = api.exit_session(ctx["session"]["id"], {"exit_at_utc": "2026-06-01T10:00:00Z"}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_TIME_RANGE.value)


def test_gate_closed_rejects_entry(api):
    """PRD §3.5: "when the garage's `gate_mode` is `CLOSED`, every entry is rejected
    with `ERR_GATE_CLOSED`".

    Design: Corner/validations/gate_closed_rejects_entry
    """
    garage = create_garage(name="G", gate_mode="CLOSED")
    rate_plan = validate_success(api.create_rate_plan(
        {"name": "RP", "hourly_cents": 500, "daily_cap_cents": 4000,
         "monthly_permit_cents": 9000, "grace_minutes": 15}, ADMIN), 201)
    zone = validate_success(api.create_zone(
        {"garage_id": garage["id"], "code": "Z", "zone_type": "TRANSIENT",
         "permit_capacity": 0, "rate_plan_id": rate_plan["id"]}, ADMIN), 201)
    create_space(zone["id"], label="S1")
    set_clock("2026-06-01T10:00:00Z")
    resp = api.create_session(
        create_session_payload(garage["id"], "GTC111", "2026-06-01T10:00:00Z"), ADMIN)
    validate_error(resp, ApiErrorId.ERR_GATE_CLOSED.value)


def test_gate_permit_only_rejects_unpermitted_plate(api):
    """PRD §3.5: "when it is `PERMIT_ONLY`, an entry whose plate has no valid
    `ACTIVE` permit is likewise rejected with `ERR_GATE_CLOSED`."

    Design: Corner/validations/gate_permit_only_rejects_unpermitted_plate
    """
    garage = create_garage(name="G", gate_mode="PERMIT_ONLY")
    rate_plan = validate_success(api.create_rate_plan(
        {"name": "RP", "hourly_cents": 500, "daily_cap_cents": 4000,
         "monthly_permit_cents": 9000, "grace_minutes": 15}, ADMIN), 201)
    zone = validate_success(api.create_zone(
        {"garage_id": garage["id"], "code": "Z", "zone_type": "MIXED",
         "permit_capacity": 5, "rate_plan_id": rate_plan["id"]}, ADMIN), 201)
    create_space(zone["id"], label="S1")
    set_clock("2026-06-01T10:00:00Z")
    resp = api.create_session(
        create_session_payload(garage["id"], "POG111", "2026-06-01T10:00:00Z"), ADMIN)
    validate_error(resp, ApiErrorId.ERR_GATE_CLOSED.value)


def test_transient_in_permit_only_zone_returns_zone_type_forbidden(api):
    """PRD §3.5: "a transient session may only park in a zone whose `zone_type` is
    `TRANSIENT` or `MIXED`, and an attempt to admit a transient parker into a
    permit-only zone is rejected with `ERR_ZONE_TYPE_FORBIDDEN`."

    Design: Corner/validations/transient_session_in_permit_only_zone_returns_zone_type_forbidden
    """
    facility = setup_garage_with_zone(zone_type="PERMIT", permit_capacity=5, num_spaces=1)
    set_clock("2026-06-01T10:00:00Z")
    resp = api.create_session(
        create_session_payload(facility["garage"]["id"], "ZTF111", "2026-06-01T10:00:00Z"), ADMIN)
    validate_error(resp, ApiErrorId.ERR_ZONE_TYPE_FORBIDDEN.value)


def test_garage_occupied_count_after_entry(api):
    """PRD §3.5: "On successful entry, the chosen space's `is_occupied` becomes true
    and the garage's `occupied_count` is recomputed upward by one."

    Design: Corner/entities/garage_computed_occupied_count_after_entry
    """
    ctx = setup_open_transient_session(plate="CMP111", entry_at_utc="2026-06-01T10:00:00Z",
                                       num_spaces=1, hourly_cents=500, daily_cap_cents=4000,
                                       monthly_permit_cents=9000, grace_minutes=15)
    assert get_garage(ctx["garage"]["id"])["occupied_count"] == 1
    assert get_space(ctx["spaces"][0]["id"])["is_occupied"] is True
