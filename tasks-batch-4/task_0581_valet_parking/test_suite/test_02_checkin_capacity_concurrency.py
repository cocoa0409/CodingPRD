"""Vehicle check-in: computed fields, event-active gate, key-tag uniqueness, lot capacity
boundary, optimistic-concurrency guard, and occupancy conservation."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId, TEST_USERS,
    create_ticket_payload, make_attendant_headers,
)
from test_helpers.fixtures import (
    create_venue, create_event, create_lot, create_attendant,
    setup_active_event_env, setup_checked_in_ticket, setup_overflow_scene,
    check_in, checkout, current_lot_version,
)

SUP = TEST_USERS["supervisor_headers"]


def test_checkin_initializes_computed_fields(api):
    """PRD §3.5: "On a successful check-in the ticket's `park_status` is initialized `PARKED`
    and its `settlement_status` is initialized `UNSETTLED`, its `checkout_at`,
    `final_fee_cents`, and `net_charge_cents` are left null, and the system computes the
    forward-looking **quoted fee** into `quoted_fee_cents`."
    PRD §3.5: "Otherwise the number of billable hours is the duration in minutes divided by 60
    and rounded up to the next whole hour; the metered component is the lesser of those hours
    multiplied by `hourly_rate_cents` and the event's `daily_max_cents` cap; the event's flat
    `event_surcharge_cents` is then added on top of the capped metered component; and finally,
    if the ticket is in overflow, the event's `overflow_surcharge_cents` is added as well."

    Design: Corner/entities/ticket_computed_fields_ignore_client_input
    """
    env = setup_active_event_env()
    a_id = env["attendant"]["id"]
    payload = create_ticket_payload(
        env["event"]["id"], env["lot"]["id"], a_id, env["lot"]["version"],
        park_status="CLOSED", settlement_status="SETTLED", quoted_fee_cents=999)
    ticket = validate_success(api.create_ticket(payload, make_attendant_headers(a_id)), 201)
    assert ticket["park_status"] == "PARKED"
    assert ticket["settlement_status"] == "UNSETTLED"
    assert ticket["quoted_fee_cents"] == 2100


def test_checkin_on_scheduled_event_rejected(api):
    """PRD §3.5: "Check-in is permitted only while the event is `ACTIVE`; a check-in against
    an event in any other status is rejected with `ERR_EVENT_NOT_ACTIVE`."

    Design: Corner/state_machines/checkin_on_scheduled_event_returns_event_not_active
    """
    venue = create_venue()
    event = create_event(venue["id"])  # remains SCHEDULED
    lot = create_lot(venue["id"], capacity=5)
    attendant = create_attendant(venue["id"])
    payload = create_ticket_payload(event["id"], lot["id"], attendant["id"], lot["version"])
    res = api.create_ticket(payload, make_attendant_headers(attendant["id"]))
    validate_error(res, ApiErrorId.ERR_EVENT_NOT_ACTIVE)


def test_duplicate_key_tag_rejected(api):
    """PRD §3.5: "The `key_tag` must be unique among the non-`CLOSED` tickets of the same
    event; reusing a tag still held by an open ticket is rejected with `ERR_KEY_TAG_IN_USE`."

    Design: Corner/validations/checkin_duplicate_key_tag_in_use
    """
    env = setup_checked_in_ticket(key_tag="K1")
    a_id = env["attendant"]["id"]
    version = current_lot_version(env["lot"]["id"])
    payload = create_ticket_payload(
        env["event"]["id"], env["lot"]["id"], a_id, version,
        key_tag="K1", license_plate="X2", checkin_at="2026-06-01T10:05:00Z")
    res = api.create_ticket(payload, make_attendant_headers(a_id))
    validate_error(res, ApiErrorId.ERR_KEY_TAG_IN_USE)


def test_first_checkin_below_capacity_admitted(api):
    """PRD §3.2: "Capacity is enforced at check-in. A lot has room when its `occupied_count`
    is strictly less than its `capacity`."
    PRD §2.8: "A lot's `occupied_count` is kept equal to the number of that lot's tickets whose
    `park_status` is `PARKED` or `RETRIEVED`; it rises by one at check-in and falls by one at
    checkout and is never negative."

    Design: Difficulty/boundary_precision_check/lot_capacity_ge_boundary_on_checkin
    """
    env = setup_active_event_env(lot_capacity=1)
    a_id = env["attendant"]["id"]
    payload = create_ticket_payload(
        env["event"]["id"], env["lot"]["id"], a_id, env["lot"]["version"], key_tag="K1")
    validate_success(api.create_ticket(payload, make_attendant_headers(a_id)), 201)
    lot = validate_success(api.get_lot(env["lot"]["id"], SUP), 200)
    assert lot["occupied_count"] == 1


def test_checkin_at_capacity_rejected(api):
    """PRD §3.2: "If the primary lot is full and no overflow lot is configured, the check-in
    is rejected with `ERR_LOT_AT_CAPACITY`."
    PRD §3.2: "A lot has room when its `occupied_count` is strictly less than its `capacity`."

    Design: Difficulty/boundary_precision_check/lot_capacity_ge_boundary_on_checkin
    """
    env = setup_active_event_env(lot_capacity=1)
    a_id = env["attendant"]["id"]
    check_in(env["event"]["id"], env["lot"]["id"], a_id,
             expected_lot_version=env["lot"]["version"], key_tag="K1")
    lot = validate_success(api.get_lot(env["lot"]["id"], SUP), 200)
    assert lot["occupied_count"] == 1
    version = current_lot_version(env["lot"]["id"])
    payload = create_ticket_payload(
        env["event"]["id"], env["lot"]["id"], a_id, version,
        key_tag="K2", license_plate="X2", checkin_at="2026-06-01T10:05:00Z")
    res = api.create_ticket(payload, make_attendant_headers(a_id))
    validate_error(res, ApiErrorId.ERR_LOT_AT_CAPACITY)


def test_stale_lot_version_rejected(api):
    """PRD §2.6: "If that value does not match the primary lot's current `version` at the
    moment the server processes the check-in — meaning another check-in has advanced the lot's
    version since the client last read it — the create is rejected with `ERR_STALE_LOT_VERSION`
    and HTTP 412, so the writer cannot claim capacity it has not actually observed."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_lot_version_returns_412
    """
    env = setup_active_event_env(lot_capacity=5)
    a_id = env["attendant"]["id"]
    stale_version = env["lot"]["version"]
    check_in(env["event"]["id"], env["lot"]["id"], a_id,
             expected_lot_version=stale_version, key_tag="K1")
    payload = create_ticket_payload(
        env["event"]["id"], env["lot"]["id"], a_id, stale_version,
        key_tag="K2", license_plate="X2", checkin_at="2026-06-01T10:05:00Z")
    res = api.create_ticket(payload, make_attendant_headers(a_id))
    validate_error(res, ApiErrorId.ERR_STALE_LOT_VERSION)


def test_checkin_increments_lot_version(api):
    """PRD §2.6: "A successful check-in increments the primary lot's `version` by one; this
    holds even when the vehicle spills into an overflow lot, because the space claim is
    evaluated and version-guarded against the primary lot."
    PRD §2.8: "A lot's `occupied_count` ... rises by one at check-in and falls by one at
    checkout and is never negative."

    Design: Corner/cross_cutting_complexity_layers/lot_version_increments_on_checkin
    """
    env = setup_active_event_env(lot_capacity=5)
    a_id = env["attendant"]["id"]
    before = env["lot"]["version"]
    check_in(env["event"]["id"], env["lot"]["id"], a_id,
             expected_lot_version=before, key_tag="K1")
    lot = validate_success(api.get_lot(env["lot"]["id"], SUP), 200)
    assert lot["version"] == before + 1
    assert lot["occupied_count"] == 1


def test_checkin_side_effects_visible_immediately(api):
    """PRD §2.8: "each such reconciliation is an atomic part of the triggering request — there
    is no eventual consistency, and all cascades complete before the response is returned."
    PRD §2.8: "A lot's `occupied_count` ... rises by one at check-in and falls by one at
    checkout and is never negative."

    Design: Corner/consistency_model/checkin_side_effects_visible_same_response
    """
    env = setup_checked_in_ticket()
    assert env["ticket"]["quoted_fee_cents"] == 2100
    lot = validate_success(api.get_lot(env["lot"]["id"], SUP), 200)
    assert lot["occupied_count"] == 1


def test_occupancy_returns_to_zero_after_checkin_checkout(api):
    """PRD §2.8: "A lot's `occupied_count` is kept equal to the number of that lot's tickets
    whose `park_status` is `PARKED` or `RETRIEVED`; it rises by one at check-in and falls by
    one at checkout and is never negative."
    PRD §3.7: "On success the checkout advances `park_status` to `CLOSED` ... decrements the
    `occupied_count` of the ticket's `lot_id` by one".

    Design: Difficulty/compensating_invariant/lot_occupancy_conserved_checkin_checkout
    """
    env = setup_checked_in_ticket(lot_capacity=5)
    ticket = checkout(env["ticket"]["id"], checkout_at="2026-06-01T11:00:00Z")
    assert ticket["park_status"] == "CLOSED"
    lot = validate_success(api.get_lot(env["lot"]["id"], SUP), 200)
    assert lot["occupied_count"] == 0


def test_occupancy_increments_then_decrements(api):
    """PRD §2.8: "A lot's `occupied_count` is kept equal to the number of that lot's tickets
    whose `park_status` is `PARKED` or `RETRIEVED`; it rises by one at check-in and falls by
    one at checkout and is never negative."

    Design: Difficulty/compensating_invariant/lot_occupancy_conserved_checkin_checkout
    """
    env = setup_checked_in_ticket(lot_capacity=5)
    lot_mid = validate_success(api.get_lot(env["lot"]["id"], SUP), 200)
    assert lot_mid["occupied_count"] == 1
    checkout(env["ticket"]["id"], checkout_at="2026-06-01T11:00:00Z")
    lot_end = validate_success(api.get_lot(env["lot"]["id"], SUP), 200)
    assert lot_end["occupied_count"] == 0


def test_checkin_outside_window_beats_capacity(api):
    """PRD §2.7: "the check-in timestamp falling inside the event window, failing with
    `ERR_CHECKIN_OUTSIDE_EVENT_WINDOW`; ... (11) lot capacity, failing with
    `ERR_LOT_AT_CAPACITY`; ... the earlier-numbered check is decided before the later one."
    PRD §3.5: "The `checkin_at` must fall inside the event's operating window — at or after
    `window_start` and strictly before `window_end` — or the check-in is rejected with
    `ERR_CHECKIN_OUTSIDE_EVENT_WINDOW`."

    Design: Difficulty/priority_pair_validation_conflict/checkin_outside_window_beats_lot_full
    """
    env = setup_active_event_env(lot_capacity=1)
    a_id = env["attendant"]["id"]
    check_in(env["event"]["id"], env["lot"]["id"], a_id,
             expected_lot_version=env["lot"]["version"], key_tag="K1")
    version = current_lot_version(env["lot"]["id"])
    # Pre-window check-in (07:00 < window_start 08:00) into the now-full lot.
    payload = create_ticket_payload(
        env["event"]["id"], env["lot"]["id"], a_id, version,
        key_tag="K2", license_plate="P2", checkin_at="2026-06-01T07:00:00Z")
    res = api.create_ticket(payload, make_attendant_headers(a_id))
    validate_error(res, ApiErrorId.ERR_CHECKIN_OUTSIDE_EVENT_WINDOW)


def test_capacity_error_surfaces_when_window_ok(api):
    """PRD §3.2: "If the primary lot is full and no overflow lot is configured, the check-in
    is rejected with `ERR_LOT_AT_CAPACITY`."
    PRD §2.7: "Where a single endpoint is subject to multiple of these ... the earlier-numbered
    check is decided before the later one."

    Design: Difficulty/priority_pair_validation_conflict/checkin_outside_window_beats_lot_full
    """
    env = setup_active_event_env(lot_capacity=1)
    a_id = env["attendant"]["id"]
    check_in(env["event"]["id"], env["lot"]["id"], a_id,
             expected_lot_version=env["lot"]["version"], key_tag="K1")
    version = current_lot_version(env["lot"]["id"])
    # In-window check-in (10:05 inside [08:00,23:00)) into the full lot: the window check
    # passes, so the later capacity check surfaces.
    payload = create_ticket_payload(
        env["event"]["id"], env["lot"]["id"], a_id, version,
        key_tag="K2", license_plate="P2", checkin_at="2026-06-01T10:05:00Z")
    res = api.create_ticket(payload, make_attendant_headers(a_id))
    validate_error(res, ApiErrorId.ERR_LOT_AT_CAPACITY)


def test_overflow_ticket_checkout_empties_overflow_lot(api):
    """PRD §3.2: "if an overflow lot is configured, the vehicle is placed there instead, the
    ticket's `lot_id` is set to the overflow lot, the ticket's `in_overflow` flag is set to
    true, and the primary lot's `overflow_active` is set to true."
    PRD §3.7: "decrements the `occupied_count` of the ticket's `lot_id` by one".

    Design: Difficulty/transitive_cascade/overflow_checkout_releases_primary_overflow_flag
    """
    scene = setup_overflow_scene()
    assert scene["t2"]["in_overflow"] is True
    assert scene["t2"]["lot_id"] == scene["lo"]["id"]
    checkout(scene["t2"]["id"], checkout_at="2026-06-01T11:00:00Z")
    lo = validate_success(api.get_lot(scene["lo"]["id"], SUP), 200)
    assert lo["occupied_count"] == 0


def test_primary_overflow_active_cleared_on_release(api):
    """PRD §3.7: "when the ticket was in overflow and that overflow lot's `occupied_count` has
    fallen to zero — clears the primary lot's `overflow_active` back to false."
    PRD §2.8: "A lot's `overflow_active` flag is true while at least one ticket that spilled
    from that primary lot still occupies its overflow lot."

    Design: Difficulty/transitive_cascade/overflow_checkout_releases_primary_overflow_flag
    """
    scene = setup_overflow_scene()
    checkout(scene["t2"]["id"], checkout_at="2026-06-01T11:00:00Z")
    lp = validate_success(api.get_lot(scene["lp"]["id"], SUP), 200)
    assert lp["overflow_active"] is False
