"""Race events and entries: event-cancel cascade, lane half-open overlap,
cross-entity check-in gate, safety-vs-temporal priority, and corner
validations (windows, capacity, duplicate, lane range)."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId,
    create_race_entry_payload,
    make_customer, make_open_event, make_running_event, register_entry, set_clock,
    TEST_USERS,
)

STAFF = TEST_USERS["staff_headers"]


# ---------------------------------------------------------------------------
# tc_event_cancel_depth2_entry_customer_points
# ---------------------------------------------------------------------------
def test_event_cancel_withdraws_entries(api):
    """PRD 3.6: "Cancelling an event withdraws every `REGISTERED` or
    `CHECKED_IN` entry (L1) and, through each entry's own withdrawal, debits
    that racer's points (L2)."

    Design: Difficulty/transitive_cascade/tc_event_cancel_depth2_entry_customer_points
    """
    cust = make_customer(api)
    ev = make_open_event(api, entry_fee_cents=2000, capacity=8, lane_count=4)
    entry = register_entry(api, ev["id"], cust["id"], race_class="STOCK", lane_no=1)
    validate_success(api.transition_race_event(ev["id"], {"action": "CANCEL"}, STAFF))
    entry_after = get_success_data(api.get_race_entry(entry["id"], STAFF))
    assert entry_after["status"] == "WITHDRAWN"


def test_event_cancel_debits_racer_entry_points(api):
    """PRD 3.6: "withdrawal debits the racer's `loyalty_points_balance` by the
    same `entry_points_awarded` that registration credited, keeping points
    conserved relative to registration."
    PRD 3.6: "Its `entry_points_awarded` is the floor of the event's
    `entry_fee_cents` divided by 100, and that many points are credited to the
    racer's `loyalty_points_balance` at registration".

    Design: Difficulty/transitive_cascade/tc_event_cancel_depth2_entry_customer_points
    """
    cust = make_customer(api)
    ev = make_open_event(api, entry_fee_cents=2000, capacity=8, lane_count=4)
    register_entry(api, ev["id"], cust["id"], race_class="STOCK", lane_no=1)
    credited = get_success_data(api.get_customer(cust["id"], STAFF))
    assert credited["loyalty_points_balance"] == 20  # floor(2000/100)
    validate_success(api.transition_race_event(ev["id"], {"action": "CANCEL"}, STAFF))
    after = get_success_data(api.get_customer(cust["id"], STAFF))
    assert after["loyalty_points_balance"] == 0


# ---------------------------------------------------------------------------
# rt_race_lane_halfopen_overlap
# ---------------------------------------------------------------------------
def test_overlapping_lane_heat_rejected(api):
    """PRD 2.8: "a race entry's heat interval from `heat_start` (inclusive) to
    `heat_end` (exclusive) must not overlap another entry sharing the same event
    and `lane_no`; two intervals that merely touch, where one ends exactly as
    the next begins, are allowed, but any true overlap is rejected with
    `ERR_LANE_CONFLICT` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/rt_race_lane_halfopen_overlap
    """
    cust_a = make_customer(api)
    cust_b = make_customer(api)
    ev = make_open_event(api, capacity=8, lane_count=4)
    register_entry(api, ev["id"], cust_a["id"], lane_no=1,
                   heat_start="2026-07-15T10:00:00Z", heat_end="2026-07-15T10:10:00Z")
    resp = api.create_race_entry(ev["id"], create_race_entry_payload(
        customer_id=cust_b["id"], race_class="STOCK", lane_no=1,
        heat_start="2026-07-15T10:05:00Z", heat_end="2026-07-15T10:15:00Z"), STAFF)
    validate_error(resp, ApiErrorId.ERR_LANE_CONFLICT.value)


def test_adjacent_lane_heat_allowed(api):
    """PRD 2.8: "two intervals that merely touch, where one ends exactly as the
    next begins, are allowed".

    Design: Difficulty/resource_temporal_overlap/rt_race_lane_halfopen_overlap
    """
    cust_a = make_customer(api)
    cust_b = make_customer(api)
    ev = make_open_event(api, capacity=8, lane_count=4)
    register_entry(api, ev["id"], cust_a["id"], lane_no=1,
                   heat_start="2026-07-15T10:00:00Z", heat_end="2026-07-15T10:10:00Z")
    # Next interval begins exactly when the first ends -> adjacency allowed.
    entry_b = register_entry(api, ev["id"], cust_b["id"], lane_no=1,
                             heat_start="2026-07-15T10:10:00Z", heat_end="2026-07-15T10:20:00Z")
    assert entry_b["status"] == "REGISTERED"


# ---------------------------------------------------------------------------
# ce_checkin_requires_event_running
# ---------------------------------------------------------------------------
def test_checkin_requires_event_running(api):
    """PRD 3.6: "Checking in advances an entry `REGISTERED → CHECKED_IN` and is
    the safety-critical gate: it requires that the parent event is `RUNNING` (a
    cross-entity state dependency, else invalid-state)".

    Design: Difficulty/cross_entity_state_dependency/ce_checkin_requires_event_running
    """
    cust = make_customer(api, ack=True)
    ev = make_open_event(api, capacity=8, lane_count=4)  # OPEN, not RUNNING
    entry = register_entry(api, ev["id"], cust["id"], lane_no=1,
                           heat_start="2026-07-15T10:00:00Z", heat_end="2026-07-15T10:10:00Z")
    set_clock(api, "2026-07-15T10:00:00Z")  # inside heat window
    resp = api.transition_race_entry(entry["id"], {"action": "CHECK_IN"}, STAFF)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_checkin_on_non_running_event_leaves_entry_registered(api):
    """PRD 3.6: "it requires that the parent event is `RUNNING` (a cross-entity
    state dependency, else invalid-state)".

    Design: Difficulty/cross_entity_state_dependency/ce_checkin_requires_event_running
    """
    cust = make_customer(api, ack=True)
    ev = make_open_event(api, capacity=8, lane_count=4)
    entry = register_entry(api, ev["id"], cust["id"], lane_no=1,
                           heat_start="2026-07-15T10:00:00Z", heat_end="2026-07-15T10:10:00Z")
    set_clock(api, "2026-07-15T10:00:00Z")
    api.transition_race_entry(entry["id"], {"action": "CHECK_IN"}, STAFF)
    after = get_success_data(api.get_race_entry(entry["id"], STAFF))
    assert after["status"] == "REGISTERED"


# ---------------------------------------------------------------------------
# pc_safety_beats_temporal_on_checkin
# ---------------------------------------------------------------------------
def test_checkin_safety_error_beats_temporal(api):
    """PRD 2.7: "a racer may only check in to a race if their `hazmat_safety_ack`
    is true, reflecting a trackside battery inspection; a check-in by a member
    who has not acknowledged is rejected with `ERR_SAFETY_INSPECTION_REQUIRED`
    (HTTP 409)."
    PRD 2.9: "The battery/hazmat safety gates are sixth, yielding
    `ERR_HAZMAT_ACK_REQUIRED` or `ERR_SAFETY_INSPECTION_REQUIRED`. Temporal-window
    checks are seventh".

    Design: Difficulty/priority_pair_validation_conflict/pc_safety_beats_temporal_on_checkin
    """
    cust = make_customer(api, ack=False)  # no safety-ack
    ev = make_open_event(api, capacity=8, lane_count=4)
    entry = register_entry(api, ev["id"], cust["id"], race_class="PRO", lane_no=2,
                           heat_start="2026-07-15T10:00:00Z", heat_end="2026-07-15T10:10:00Z")
    validate_success(api.transition_race_event(ev["id"], {"action": "RUN"}, STAFF))
    # Clock still at default 2026-07-01, far before the heat window.
    resp = api.transition_race_entry(entry["id"], {"action": "CHECK_IN"}, STAFF)
    validate_error(resp, ApiErrorId.ERR_SAFETY_INSPECTION_REQUIRED.value)


def test_checkin_without_ack_leaves_entry_registered(api):
    """PRD 2.7: "a check-in by a member who has not acknowledged is rejected with
    `ERR_SAFETY_INSPECTION_REQUIRED` (HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/pc_safety_beats_temporal_on_checkin
    """
    cust = make_customer(api, ack=False)
    ev = make_open_event(api, capacity=8, lane_count=4)
    entry = register_entry(api, ev["id"], cust["id"], race_class="PRO", lane_no=2,
                           heat_start="2026-07-15T10:00:00Z", heat_end="2026-07-15T10:10:00Z")
    validate_success(api.transition_race_event(ev["id"], {"action": "RUN"}, STAFF))
    api.transition_race_entry(entry["id"], {"action": "CHECK_IN"}, STAFF)
    after = get_success_data(api.get_race_entry(entry["id"], STAFF))
    assert after["status"] == "REGISTERED"


# ---------------------------------------------------------------------------
# cn_register_window_closed_returns_409
# ---------------------------------------------------------------------------
def test_register_before_window_open_rejected(api):
    """PRD 2.8: "Race registrations may only be created while the current
    logical time is at or after an event's `registration_open_at` and strictly
    before its `registration_close_at`; outside that span the registration is
    rejected with the same `ERR_WINDOW_CLOSED`."

    Design: Corner/validations/cn_register_window_closed_returns_409
    """
    cust = make_customer(api)
    # Window opens 2026-08-01; clock at default 2026-07-01.
    ev = make_open_event(api, capacity=8, lane_count=4,
                         event_date="2026-09-01T10:00:00Z",
                         registration_open_at="2026-08-01T00:00:00Z",
                         registration_close_at="2026-08-20T00:00:00Z")
    resp = api.create_race_entry(ev["id"], create_race_entry_payload(
        customer_id=cust["id"], race_class="STOCK", lane_no=1,
        heat_start="2026-09-01T10:00:00Z", heat_end="2026-09-01T10:10:00Z"), STAFF)
    validate_error(resp, ApiErrorId.ERR_WINDOW_CLOSED.value)


# ---------------------------------------------------------------------------
# cn_checkin_window_closed_returns_409
# ---------------------------------------------------------------------------
def test_checkin_before_window_rejected(api):
    """PRD 2.8: "a check-in whose logical time is before `heat_start` minus that
    lead or at/after `heat_end` is rejected with `ERR_CHECKIN_WINDOW_CLOSED`
    (HTTP 409)."

    Design: Corner/validations/cn_checkin_window_closed_returns_409
    """
    cust = make_customer(api, ack=True)  # safety satisfied, so only temporal fails
    ev = make_open_event(api, capacity=8, lane_count=4)
    entry = register_entry(api, ev["id"], cust["id"], lane_no=1,
                           heat_start="2026-07-15T10:00:00Z", heat_end="2026-07-15T10:10:00Z")
    validate_success(api.transition_race_event(ev["id"], {"action": "RUN"}, STAFF))
    # Clock stays at default 2026-07-01, weeks before the heat window.
    resp = api.transition_race_entry(entry["id"], {"action": "CHECK_IN"}, STAFF)
    validate_error(resp, ApiErrorId.ERR_CHECKIN_WINDOW_CLOSED.value)


# ---------------------------------------------------------------------------
# cn_event_full_returns_409
# ---------------------------------------------------------------------------
def test_register_into_full_event_rejected(api):
    """PRD 3.6: "The event must not already be at capacity — its `entry_count`
    must be below `capacity`, else `ERR_EVENT_FULL`".

    Design: Corner/validations/cn_event_full_returns_409
    """
    cust_a = make_customer(api)
    cust_b = make_customer(api)
    ev = make_open_event(api, capacity=1, lane_count=4)
    register_entry(api, ev["id"], cust_a["id"], lane_no=1,
                   heat_start="2026-07-15T10:00:00Z", heat_end="2026-07-15T10:10:00Z")
    resp = api.create_race_entry(ev["id"], create_race_entry_payload(
        customer_id=cust_b["id"], race_class="STOCK", lane_no=2,
        heat_start="2026-07-15T10:00:00Z", heat_end="2026-07-15T10:10:00Z"), STAFF)
    validate_error(resp, ApiErrorId.ERR_EVENT_FULL.value)


# ---------------------------------------------------------------------------
# cn_duplicate_entry_returns_409
# ---------------------------------------------------------------------------
def test_duplicate_non_terminal_entry_rejected(api):
    """PRD 3.6: "the same member may not hold two non-terminal entries in one
    event, else `ERR_DUPLICATE_ENTRY`."

    Design: Corner/validations/cn_duplicate_entry_returns_409
    """
    cust = make_customer(api)
    ev = make_open_event(api, capacity=8, lane_count=4)
    register_entry(api, ev["id"], cust["id"], race_class="STOCK", lane_no=1,
                   heat_start="2026-07-15T10:00:00Z", heat_end="2026-07-15T10:10:00Z")
    resp = api.create_race_entry(ev["id"], create_race_entry_payload(
        customer_id=cust["id"], race_class="PRO", lane_no=2,
        heat_start="2026-07-15T11:00:00Z", heat_end="2026-07-15T11:10:00Z"), STAFF)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_ENTRY.value)


# ---------------------------------------------------------------------------
# cn_lane_out_of_range_returns_400
# ---------------------------------------------------------------------------
def test_lane_number_out_of_range_rejected(api):
    """PRD 3.6: "The `lane_no` must lie between 1 and the event's `lane_count`
    inclusive, and a lane outside that range is rejected with
    `ERR_LANE_OUT_OF_RANGE` (HTTP 400)."

    Design: Corner/validations/cn_lane_out_of_range_returns_400
    """
    cust = make_customer(api)
    ev = make_open_event(api, capacity=8, lane_count=2)
    resp = api.create_race_entry(ev["id"], create_race_entry_payload(
        customer_id=cust["id"], race_class="STOCK", lane_no=5,
        heat_start="2026-07-15T10:00:00Z", heat_end="2026-07-15T10:10:00Z"), STAFF)
    validate_error(resp, ApiErrorId.ERR_LANE_OUT_OF_RANGE.value)
