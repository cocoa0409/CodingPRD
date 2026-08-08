"""Dispatch-event scheduling, notification, temporal windows, and overlaps.

Queue A: curtailment_requires_event_active, override_state_conflict_beats_temporal,
event_window_buffer_conflict, reading_interval_overlap_adjacency_ok,
season_cap_nth_allowed_nplus1_rejected.
Queue B: start_before_window_rejected, notify_lead_not_met_rejected,
notify_no_eligible_enrollments_rejected, override_window_closed_rejected.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS,
    make_aggregator_headers, make_customer_headers,
    create_dispatch_event_payload, create_meter_reading_payload,
    onboard_aggregator, onboard_customer, create_program, register_device,
    enroll_active, create_event, set_clock, setup_notified_event,
)
from test_helpers.api_client import api_client

OP = TEST_USERS["program_operator_headers"]


# --------------------------------------------------------------------------- #
# cross_entity_state_dependency / curtailment_requires_event_active
# --------------------------------------------------------------------------- #
def test_start_curtailment_rejected_while_event_notified(api):
    """PRD §3.5: "This step requires the parent event to be in ACTIVE status
    specifically; otherwise the call is refused with ERR_INVALID_STATE."

    Design: Difficulty/cross_entity_state_dependency/curtailment_requires_event_active
    """
    ctx = setup_notified_event(committed_kw=5, device_type="BATTERY")
    agg_h = make_aggregator_headers(ctx["agg_id"])
    get_success_data(api.acknowledge_dispatch(ctx["disp_id"], agg_h))  # PENDING -> ACKNOWLEDGED
    resp = api.start_curtailment(ctx["disp_id"], agg_h)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_start_curtailment_rejection_leaves_dispatch_acknowledged(api):
    """PRD §3.5: "Once the event is live, the owning aggregator starts curtailment
    on an ACKNOWLEDGED dispatch, moving it to CURTAILING and incrementing version
    by 1, again subject to the aggregator-ownership check."

    Design: Difficulty/cross_entity_state_dependency/curtailment_requires_event_active
    """
    ctx = setup_notified_event(committed_kw=5, device_type="BATTERY")
    agg_h = make_aggregator_headers(ctx["agg_id"])
    ack = get_success_data(api.acknowledge_dispatch(ctx["disp_id"], agg_h))
    assert ack["status"] == "ACKNOWLEDGED"
    api.start_curtailment(ctx["disp_id"], agg_h)  # rejected: event still NOTIFIED
    still = validate_success(api.get_dispatch(ctx["disp_id"], OP))
    assert still["status"] == "ACKNOWLEDGED", "rejected curtailment must not advance the dispatch"


# --------------------------------------------------------------------------- #
# priority_pair_validation_conflict / override_state_conflict_beats_temporal
# --------------------------------------------------------------------------- #
def test_override_on_terminal_dispatch_past_window_returns_invalid_state(api):
    """PRD §2.8: "(8) the target resource is in a state from which the requested
    transition is allowed, else ERR_INVALID_STATE (HTTP 409). Checks beyond these
    eight are business rules specific to individual workflows and are described
    where those workflows live; when such a rule shares an endpoint with the
    generic checks above, it is evaluated after the eight generic checks unless a
    workflow narrative says otherwise."

    Design: Difficulty/priority_pair_validation_conflict/override_state_conflict_beats_temporal
    """
    ctx = setup_notified_event(committed_kw=3, device_type="THERMOSTAT", target_reduction_kw=3)
    cust_h = make_customer_headers(ctx["cust_id"])
    set_clock("2026-06-01T12:30:00Z")  # window still open
    get_success_data(api.override_dispatch(ctx["disp_id"], cust_h))  # -> OVERRIDDEN (terminal)
    set_clock("2026-06-01T17:00:00Z")  # past window_end 16:00
    resp = api.override_dispatch(ctx["disp_id"], cust_h)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_override_state_conflict_does_not_return_window_closed(api):
    """PRD §3.5: "Override is available from PENDING, ACKNOWLEDGED, or CURTAILING
    status and moves the dispatch to the terminal OVERRIDDEN status, incrementing
    version by 1."

    Design: Difficulty/priority_pair_validation_conflict/override_state_conflict_beats_temporal
    """
    ctx = setup_notified_event(committed_kw=3, device_type="THERMOSTAT", target_reduction_kw=3)
    cust_h = make_customer_headers(ctx["cust_id"])
    set_clock("2026-06-01T12:30:00Z")
    get_success_data(api.override_dispatch(ctx["disp_id"], cust_h))
    set_clock("2026-06-01T17:00:00Z")
    resp = api.override_dispatch(ctx["disp_id"], cust_h)
    body = resp.json()["data"]
    assert body["error_id"] != ApiErrorId.ERR_OVERRIDE_WINDOW_CLOSED.value, \
        "state check must pre-empt the temporal window check"


# --------------------------------------------------------------------------- #
# resource_temporal_overlap / event_window_buffer_conflict
# --------------------------------------------------------------------------- #
def test_event_60min_after_end_conflicts_within_buffer(api):
    """PRD §3.4: "concretely, a conflict exists when the new event's window_start
    is earlier than an existing event's window_end plus 120 minutes and the new
    event's window_end plus 120 minutes is later than that existing event's
    window_start."

    Design: Difficulty/resource_temporal_overlap/event_window_buffer_conflict
    """
    prog = create_program(active=True)
    get_success_data(api.create_dispatch_event(
        create_dispatch_event_payload(prog["id"], "2026-06-01T14:00:00Z", "2026-06-01T16:00:00Z", 5), OP))
    resp = api.create_dispatch_event(
        create_dispatch_event_payload(prog["id"], "2026-06-01T17:00:00Z", "2026-06-01T18:00:00Z", 5), OP)
    validate_error(resp, ApiErrorId.ERR_EVENT_WINDOW_CONFLICT.value)


def test_event_exactly_120min_after_end_is_accepted(api):
    """PRD §3.4: "Each event's window is padded by a buffer of two hours (120
    minutes) on each side, and the new event's padded window must not collide with
    the window of any non-cancelled event of the same program".

    Design: Difficulty/resource_temporal_overlap/event_window_buffer_conflict
    """
    prog = create_program(active=True)
    get_success_data(api.create_dispatch_event(
        create_dispatch_event_payload(prog["id"], "2026-06-01T14:00:00Z", "2026-06-01T16:00:00Z", 5), OP))
    resp = api.create_dispatch_event(
        create_dispatch_event_payload(prog["id"], "2026-06-01T18:00:00Z", "2026-06-01T19:00:00Z", 5), OP)
    validate_success(resp, expected_status=201)


# --------------------------------------------------------------------------- #
# resource_temporal_overlap / reading_interval_overlap_adjacency_ok
# --------------------------------------------------------------------------- #
def test_adjacent_meter_reading_accepted(api):
    """PRD §3.2: "two intervals overlap unless one ends at or before the other
    begins, so exact adjacency (one interval's end equal to the next interval's
    start) is permitted, but any true overlap is rejected with
    ERR_READING_INTERVAL_OVERLAP."

    Design: Difficulty/resource_temporal_overlap/reading_interval_overlap_adjacency_ok
    """
    agg = onboard_aggregator()
    cust = onboard_customer()
    dev = register_device(agg["id"], cust["id"], capacity_kwh=20)
    agg_h = make_aggregator_headers(agg["id"])
    get_success_data(api.create_meter_reading(dev["id"], create_meter_reading_payload(
        "2026-05-20T10:00:00Z", "2026-05-20T11:00:00Z", 7, "BASELINE_WINDOW"), agg_h))
    resp = api.create_meter_reading(dev["id"], create_meter_reading_payload(
        "2026-05-20T11:00:00Z", "2026-05-20T12:00:00Z", 6, "BASELINE_WINDOW"), agg_h)
    validate_success(resp, expected_status=201)


def test_overlapping_meter_reading_rejected(api):
    """PRD §3.2: "A new reading must not overlap an existing reading of the same
    device that shares the same reading_type; two intervals overlap unless one
    ends at or before the other begins, so exact adjacency (one interval's end
    equal to the next interval's start) is permitted, but any true overlap is
    rejected with ERR_READING_INTERVAL_OVERLAP."

    Design: Difficulty/resource_temporal_overlap/reading_interval_overlap_adjacency_ok
    """
    agg = onboard_aggregator()
    cust = onboard_customer()
    dev = register_device(agg["id"], cust["id"], capacity_kwh=20)
    agg_h = make_aggregator_headers(agg["id"])
    get_success_data(api.create_meter_reading(dev["id"], create_meter_reading_payload(
        "2026-05-20T10:00:00Z", "2026-05-20T11:00:00Z", 7, "BASELINE_WINDOW"), agg_h))
    resp = api.create_meter_reading(dev["id"], create_meter_reading_payload(
        "2026-05-20T10:30:00Z", "2026-05-20T11:30:00Z", 8, "BASELINE_WINDOW"), agg_h)
    validate_error(resp, ApiErrorId.ERR_READING_INTERVAL_OVERLAP.value)


# --------------------------------------------------------------------------- #
# boundary_precision_check / season_cap_nth_allowed_nplus1_rejected
# --------------------------------------------------------------------------- #
def test_season_cap_nth_event_allowed(api):
    """PRD §3.4: "First, the program may not exceed its max_events_per_season: if
    the count of the program's non-cancelled dispatch events is already at or above
    max_events_per_season, the new event is refused with
    ERR_SEASON_EVENT_CAP_EXCEEDED."

    Design: Difficulty/boundary_precision_check/season_cap_nth_allowed_nplus1_rejected
    """
    prog = create_program(active=True, max_events_per_season=2)
    get_success_data(api.create_dispatch_event(
        create_dispatch_event_payload(prog["id"], "2026-06-01T14:00:00Z", "2026-06-01T16:00:00Z", 5), OP))
    resp2 = api.create_dispatch_event(
        create_dispatch_event_payload(prog["id"], "2026-06-08T14:00:00Z", "2026-06-08T16:00:00Z", 5), OP)
    validate_success(resp2, expected_status=201)  # the cap value itself is allowed


def test_season_cap_nplus1_event_rejected(api):
    """PRD §3.1: "max_events_per_season caps the number of non-cancelled dispatch
    events the program may hold; it defaults to 3 and must be at least 0."

    Design: Difficulty/boundary_precision_check/season_cap_nth_allowed_nplus1_rejected
    """
    prog = create_program(active=True, max_events_per_season=2)
    get_success_data(api.create_dispatch_event(
        create_dispatch_event_payload(prog["id"], "2026-06-01T14:00:00Z", "2026-06-01T16:00:00Z", 5), OP))
    get_success_data(api.create_dispatch_event(
        create_dispatch_event_payload(prog["id"], "2026-06-08T14:00:00Z", "2026-06-08T16:00:00Z", 5), OP))
    resp3 = api.create_dispatch_event(
        create_dispatch_event_payload(prog["id"], "2026-06-15T14:00:00Z", "2026-06-15T16:00:00Z", 5), OP)
    validate_error(resp3, ApiErrorId.ERR_SEASON_EVENT_CAP_EXCEEDED.value)


# --------------------------------------------------------------------------- #
# Corner: state_machines / start_before_window_rejected
# --------------------------------------------------------------------------- #
def test_start_event_before_window_rejected(api):
    """PRD §3.4: "Starting requires the current instant to be at or after
    window_start, else ERR_EVENT_NOT_STARTED."

    Design: Corner/state_machines/start_before_window_rejected
    """
    ctx = setup_notified_event(committed_kw=5, device_type="BATTERY")
    set_clock("2026-06-01T13:00:00Z")  # before window_start 14:00
    resp = api.start_dispatch_event(ctx["evt_id"], OP)
    validate_error(resp, ApiErrorId.ERR_EVENT_NOT_STARTED.value)


# --------------------------------------------------------------------------- #
# Corner: state_machines / notify_lead_not_met_rejected
# --------------------------------------------------------------------------- #
def test_notify_too_close_to_window_rejected(api):
    """PRD §3.4: "Notification must occur early enough: the current logical-clock
    instant must be at or before window_start minus the program's
    notification_lead_minutes — equivalently, the notice must lead the window
    start by at least the configured lead time — else ERR_NOTIFY_LEAD_NOT_MET."

    Design: Corner/state_machines/notify_lead_not_met_rejected
    """
    agg = onboard_aggregator()
    cust = onboard_customer()
    prog = create_program(active=True, notification_lead_minutes=60)
    dev = register_device(agg["id"], cust["id"], capacity_kwh=20)
    enroll_active(dev["id"], prog["id"], agg["id"], committed_kw=5)
    evt = create_event(prog["id"], "2026-06-01T14:00:00Z", "2026-06-01T16:00:00Z", 5)
    set_clock("2026-06-01T13:30:00Z")  # only 30 min before window_start
    resp = api.notify_dispatch_event(evt["id"], OP)
    validate_error(resp, ApiErrorId.ERR_NOTIFY_LEAD_NOT_MET.value)


# --------------------------------------------------------------------------- #
# Corner: state_machines / notify_no_eligible_enrollments_rejected
# --------------------------------------------------------------------------- #
def test_notify_with_no_active_enrollments_rejected(api):
    """PRD §3.4: "Notification also requires that at least one enrollment of the
    program is currently ACTIVE; if the program has zero ACTIVE enrollments the
    call is refused with ERR_NO_ELIGIBLE_ENROLLMENTS."

    Design: Corner/state_machines/notify_no_eligible_enrollments_rejected
    """
    prog = create_program(active=True, notification_lead_minutes=60)
    evt = create_event(prog["id"], "2026-06-01T14:00:00Z", "2026-06-01T16:00:00Z", 5)
    set_clock("2026-06-01T12:00:00Z")
    resp = api.notify_dispatch_event(evt["id"], OP)
    validate_error(resp, ApiErrorId.ERR_NO_ELIGIBLE_ENROLLMENTS.value)


# --------------------------------------------------------------------------- #
# Corner: state_machines / override_window_closed_rejected
# --------------------------------------------------------------------------- #
def test_override_after_window_closed_rejected(api):
    """PRD §3.5: "Override is permitted only while the override window is still
    open — the current instant must be strictly before the event's window_end —
    otherwise the call is refused with ERR_OVERRIDE_WINDOW_CLOSED."

    Design: Corner/state_machines/override_window_closed_rejected
    """
    ctx = setup_notified_event(committed_kw=5, device_type="BATTERY")
    set_clock("2026-06-01T17:00:00Z")  # past window_end 16:00, dispatch still PENDING
    resp = api.override_dispatch(ctx["disp_id"], make_customer_headers(ctx["cust_id"]))
    validate_error(resp, ApiErrorId.ERR_OVERRIDE_WINDOW_CLOSED.value)
