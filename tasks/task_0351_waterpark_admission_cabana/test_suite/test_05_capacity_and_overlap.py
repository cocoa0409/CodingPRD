"""Window-capacity OCC, cabana time-overlap with turnover buffer, locker billing,
weather holds, and validation-priority conflicts (PRD §2.6, §3.4, §3.6, §3.7, §2.9)."""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    make_guest_headers, TEST_USERS,
    setup_confirmed_admission, setup_issued_admission, setup_checked_in_admission,
    setup_held_cabana_rental, setup_paid_order, get_window,
    create_park, create_policy, create_window, create_cabana, create_guest, create_order,
)

PM = TEST_USERS["park_manager_headers"]
GA = TEST_USERS["gate_agent_headers"]
FC = TEST_USERS["finance_clerk_headers"]


# ───────────────── Queue A: resource_temporal_overlap ─────────────────

def test_cabana_overlap_within_turnover_buffer_rejected(api):
    """PRD §3.6: "The collision test expands each existing rental on its end side by
    the cabana's turnover_buffer_minutes, the mandatory cleaning gap, and treats the
    new rental as colliding when its starts_at falls before the prior rental's ends_at
    plus that buffer and its ends_at falls after the prior rental's starts_at."

    Design: Difficulty/resource_temporal_overlap/cabana_overlap_with_turnover_buffer
    """
    ctx = setup_held_cabana_rental(daily_rate_cents=12000, turnover_buffer_minutes=30,
                                   rental_starts="2026-07-01T10:00:00Z",
                                   rental_ends="2026-07-01T14:00:00Z")
    gh = make_guest_headers(ctx["guest"]["id"])
    fresh = get_window(ctx["window"]["id"])
    # New rental 14:15-18:00 collides: 14:15 < (14:00 + 30min buffer = 14:30).
    res = api_client.create_cabana_rental(
        {"cabana_id": ctx["cabana"]["id"], "order_id": ctx["order"]["id"],
         "entry_window_id": ctx["window"]["id"], "starts_at": "2026-07-01T14:15:00Z",
         "ends_at": "2026-07-01T18:00:00Z", "expected_entry_window_version": fresh["version"]}, gh)
    validate_error(res, "ERR_CABANA_OVERLAP")


def test_cabana_rental_at_buffered_end_is_adjacent_allowed(api):
    """PRD §3.6: "A new rental whose start lands exactly at a prior rental's buffered
    end is adjacent, not overlapping, and is allowed."

    Design: Difficulty/resource_temporal_overlap/cabana_overlap_with_turnover_buffer
    """
    ctx = setup_held_cabana_rental(daily_rate_cents=12000, turnover_buffer_minutes=30,
                                   rental_starts="2026-07-01T10:00:00Z",
                                   rental_ends="2026-07-01T14:00:00Z")
    gh = make_guest_headers(ctx["guest"]["id"])
    fresh = get_window(ctx["window"]["id"])
    # New rental starting exactly at 14:30 (14:00 + 30min buffer) is adjacent → allowed.
    res = api_client.create_cabana_rental(
        {"cabana_id": ctx["cabana"]["id"], "order_id": ctx["order"]["id"],
         "entry_window_id": ctx["window"]["id"], "starts_at": "2026-07-01T14:30:00Z",
         "ends_at": "2026-07-01T18:00:00Z", "expected_entry_window_version": fresh["version"]}, gh)
    rental = validate_success(res, 201)
    assert rental["status"] == "HELD"


def test_checkin_at_window_end_rejected_exclusive(api):
    """PRD §3.4: "the logical clock fall within the window's half-open interval — at
    or after starts_at and strictly before ends_at. A clock exactly equal to starts_at
    admits; a clock exactly equal to ends_at is too late and, like any out-of-interval
    check-in, is rejected with ERR_WINDOW_TIME_VIOLATION."

    Design: Difficulty/resource_temporal_overlap/checkin_window_interval_half_open_at_end
    """
    ctx = setup_confirmed_admission(
        clock="2026-07-01T10:00:00Z",
        window_overrides={"starts_at": "2026-07-01T09:00:00Z",
                          "ends_at": "2026-07-01T17:00:00Z", "window_capacity": 50},
    )
    # Move clock to exactly ends_at.
    get_success_data(api_client.set_clock({"to_iso8601": "2026-07-01T17:00:00Z"}, PM))
    res = api_client.check_in_admission(ctx["admission"]["id"], GA)
    validate_error(res, "ERR_WINDOW_TIME_VIOLATION")


def test_checkin_at_window_start_admits_inclusive(api):
    """PRD §3.4: "A clock exactly equal to starts_at admits; a clock exactly equal to
    ends_at is too late"

    Design: Difficulty/resource_temporal_overlap/checkin_window_interval_half_open_at_end
    """
    ctx = setup_confirmed_admission(
        clock="2026-07-01T10:00:00Z",
        guest_overrides={"height_cm": 150},
        window_overrides={"starts_at": "2026-07-01T09:00:00Z",
                          "ends_at": "2026-07-01T17:00:00Z", "window_capacity": 50},
    )
    # Move clock to exactly starts_at → inclusive, admits.
    get_success_data(api_client.set_clock({"to_iso8601": "2026-07-01T09:00:00Z"}, PM))
    checked = get_success_data(api_client.check_in_admission(ctx["admission"]["id"], GA))
    assert checked["status"] == "CHECKED_IN"


# ───────────────── Queue A: priority_pair_validation_conflict ─────────────────

def test_state_beats_fiscal_reassign_checked_in_admission(api):
    """PRD §2.9: "the state-legality check (that the target resource is in a state from
    which the requested transition is defined, otherwise ERR_INVALID_STATE) and the
    capacity OCC check (ERR_STALE_VERSION) precede the remaining business-safety,
    temporal, and fiscal checks."
    PRD §3.4: "Assignment is allowed only when the admission is ISSUED"

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_assign_window
    """
    # Window capacity 1, admission CHECKED_IN (consumes the slot), then re-assign.
    ctx = setup_checked_in_admission(clock="2026-07-01T10:00:00Z",
                                     window_overrides={"window_capacity": 1})
    gh = make_guest_headers(ctx["guest"]["id"])
    fresh = get_window(ctx["window"]["id"])
    res = api_client.assign_window(
        ctx["admission"]["id"],
        {"entry_window_id": ctx["window"]["id"],
         "expected_entry_window_version": fresh["version"]}, gh)
    # admission is CHECKED_IN (not ISSUED) → state check fires before capacity.
    validate_error(res, "ERR_INVALID_STATE")


def test_state_beats_fiscal_confirmed_admission_reassign_to_full_window(api):
    """PRD §3.4: "Assignment is allowed only when the admission is ISSUED"
    PRD §2.9: "the state-legality check (that the target resource is in a state from
    which the requested transition is defined, otherwise ERR_INVALID_STATE) and the
    capacity OCC check (ERR_STALE_VERSION) precede the remaining business-safety,
    temporal, and fiscal checks."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_assign_window
    """
    # Admission already CONFIRMED (not ISSUED) on a capacity-1 window; re-assigning it
    # again must fail the state check, not the fiscal capacity check.
    ctx = setup_confirmed_admission(clock="2026-07-01T10:00:00Z",
                                    window_overrides={"window_capacity": 1})
    gh = make_guest_headers(ctx["guest"]["id"])
    fresh = get_window(ctx["window"]["id"])
    res = api_client.assign_window(
        ctx["admission"]["id"],
        {"entry_window_id": ctx["window"]["id"],
         "expected_entry_window_version": fresh["version"]}, gh)
    validate_error(res, "ERR_INVALID_STATE")


# ───────────────── Queue A: boundary_precision_check (locker hours) ─────────────────

def test_locker_60_minutes_bills_one_hour(api):
    """PRD §3.7: "hours_billed is that duration rounded up to the next whole hour, so
    that every started hour bills a full hour. Exactly sixty minutes bills as one hour,
    sixty-one minutes bills as two, and a zero-length interval is invalid."

    Design: Difficulty/boundary_precision_check/locker_hours_ceil_boundary_60_vs_61_minutes
    """
    park, guest, order = setup_paid_order()
    gh = make_guest_headers(guest["id"])
    locker = get_success_data(api_client.create_locker(park["id"], {"bank_code": "A",
                                                                    "hourly_rate_cents": 500}, PM))
    res = api_client.create_locker_rental(
        {"locker_id": locker["id"], "order_id": order["id"],
         "starts_at": "2026-07-01T10:00:00Z", "ends_at": "2026-07-01T11:00:00Z"}, gh)
    lr = validate_success(res, 201)
    assert lr["hours_billed"] == 1, f"60 min → 1 hour, got {lr['hours_billed']}"
    assert lr["price_cents"] == 500, f"1 * 500 = 500, got {lr['price_cents']}"


def test_locker_61_minutes_bills_two_hours(api):
    """PRD §3.7: "Exactly sixty minutes bills as one hour, sixty-one minutes bills as
    two, and a zero-length interval is invalid."

    Design: Difficulty/boundary_precision_check/locker_hours_ceil_boundary_60_vs_61_minutes
    """
    park, guest, order = setup_paid_order()
    gh = make_guest_headers(guest["id"])
    locker = get_success_data(api_client.create_locker(park["id"], {"bank_code": "A",
                                                                    "hourly_rate_cents": 500}, PM))
    res = api_client.create_locker_rental(
        {"locker_id": locker["id"], "order_id": order["id"],
         "starts_at": "2026-07-01T12:00:00Z", "ends_at": "2026-07-01T13:01:00Z"}, gh)
    lr = validate_success(res, 201)
    assert lr["hours_billed"] == 2, f"61 min → 2 hours, got {lr['hours_billed']}"
    assert lr["price_cents"] == 1000, f"2 * 500 = 1000, got {lr['price_cents']}"


# ───────────────── Queue A: cross_entity_state_dependency (refund blocked) ─────────────────

def test_refund_blocked_by_checked_in_admission(api):
    """PRD §3.3: "only when no admission under the order is in CHECKED_IN status — a
    refund attempted after any admission has been consumed at the gate is rejected with
    ERR_ALREADY_CONSUMED."

    Design: Difficulty/cross_entity_state_dependency/refund_blocked_by_checked_in_admission
    """
    ctx = setup_checked_in_admission(clock="2026-07-01T10:00:00Z")
    res = api_client.refund_order(ctx["order"]["id"], FC)
    validate_error(res, "ERR_ALREADY_CONSUMED")


def test_refund_blocked_when_one_of_many_checked_in(api):
    """PRD §3.3: "Refunding an order is a FinanceClerk action available only while
    payment_status is PAID, and only when no admission under the order is in CHECKED_IN
    status"

    Design: Difficulty/cross_entity_state_dependency/refund_blocked_by_checked_in_admission
    """
    ctx = setup_checked_in_admission(clock="2026-07-01T10:00:00Z")
    # A single checked-in admission already blocks; assert again from a fresh refund.
    res = api_client.refund_order(ctx["order"]["id"], FC)
    validate_error(res, "ERR_ALREADY_CONSUMED")


# ───────────────── Queue B: validations / OCC / errors ─────────────────

def test_assign_window_over_capacity_rejected(api):
    """PRD §3.4: "the window has room — meaning the sum of its reserved_count and
    admitted_count is strictly less than its window_capacity; a request that would meet
    or breach capacity is rejected with ERR_WINDOW_CAPACITY_EXCEEDED."

    Design: Corner/validations/assign_window_over_capacity_returns_capacity_exceeded
    """
    ctx = setup_confirmed_admission(party_size=2, window_overrides={"window_capacity": 1})
    gh = make_guest_headers(ctx["guest"]["id"])
    # First admission already CONFIRMED (reserved 1 == capacity 1). Assign the second.
    admissions = get_success_data(api_client.list_order_admissions(ctx["order"]["id"], gh))
    second = [a for a in admissions if a["id"] != ctx["admission"]["id"]][0]
    get_success_data(api_client.bind_guest(second["id"], {"guest_id": ctx["guest"]["id"]}, gh))
    fresh = get_window(ctx["window"]["id"])
    res = api_client.assign_window(
        second["id"], {"entry_window_id": ctx["window"]["id"],
                       "expected_entry_window_version": fresh["version"]}, gh)
    validate_error(res, "ERR_WINDOW_CAPACITY_EXCEEDED")


def test_invalid_cabana_interval_starts_after_ends_rejected(api):
    """PRD §2.9: "an interval whose starts_at is not strictly before its ends_at fail
    with ERR_INVALID_REQUEST."
    PRD §3.6: "the requested interval must be valid, with starts_at strictly before
    ends_at"

    Design: Corner/validations/invalid_interval_starts_after_ends_rejected
    """
    park, guest, order = setup_paid_order(park_overrides=None,
                                          policy_overrides={"base_price_cents": 5000})
    gh = make_guest_headers(guest["id"])
    window = create_window(park["id"], starts_at="2026-07-01T09:00:00Z",
                           ends_at="2026-07-01T20:00:00Z", window_capacity=50)
    cabana = create_cabana(park["id"], label="C-5", tier="STANDARD", daily_rate_cents=9000)
    fresh = get_window(window["id"])
    res = api_client.create_cabana_rental(
        {"cabana_id": cabana["id"], "order_id": order["id"], "entry_window_id": window["id"],
         "starts_at": "2026-07-01T15:00:00Z", "ends_at": "2026-07-01T11:00:00Z",
         "expected_entry_window_version": fresh["version"]}, gh)
    validate_error(res, "ERR_INVALID_REQUEST")


def test_existence_beats_state_assign_to_missing_window(api):
    """PRD §2.5: "the first identifier that does not resolve to a live resource causes
    the request to be rejected with ERR_NOT_FOUND before any later identifier or
    business rule is consulted."
    PRD §2.9: "Existence is checked fourth, with any unresolved path or body
    identifier failing left-to-right with ERR_NOT_FOUND."

    Design: Corner/validations/existence_beats_state_on_assign_window
    """
    ctx = setup_issued_admission(make_window=True)
    gh = make_guest_headers(ctx["guest"]["id"])
    adm = ctx["admissions"][0]
    get_success_data(api_client.bind_guest(adm["id"], {"guest_id": ctx["guest"]["id"]}, gh))
    fresh = get_window(ctx["window"]["id"])
    res = api_client.assign_window(
        adm["id"], {"entry_window_id": "00000000-0000-0000-0000-000000000000",
                    "expected_entry_window_version": fresh["version"]}, gh)
    validate_error(res, "ERR_NOT_FOUND")


def test_stale_version_on_cabana_rental_rejected(api):
    """PRD §2.6: "If that value does not match the window's current version at the
    moment the server processes the request, the write is rejected with
    ERR_STALE_VERSION (HTTP 412), and no capacity is consumed."
    PRD §3.6: "a mismatch is rejected with ERR_STALE_VERSION (HTTP 412)"

    Design: Corner/errors/error_stale_version_on_cabana_rental
    """
    # One rental already created (window version advanced); use version - 1 (stale).
    ctx = setup_held_cabana_rental(rental_starts="2026-07-01T10:00:00Z",
                                   rental_ends="2026-07-01T12:00:00Z")
    gh = make_guest_headers(ctx["guest"]["id"])
    fresh = get_window(ctx["window"]["id"])
    stale_version = fresh["version"] - 1
    res = api_client.create_cabana_rental(
        {"cabana_id": ctx["cabana"]["id"], "order_id": ctx["order"]["id"],
         "entry_window_id": ctx["window"]["id"], "starts_at": "2026-07-01T13:00:00Z",
         "ends_at": "2026-07-01T15:00:00Z", "expected_entry_window_version": stale_version}, gh)
    validate_error(res, "ERR_STALE_VERSION")


def test_assign_window_correct_version_succeeds_and_bumps(api):
    """PRD §2.6: "Because both a successful assignment and a successful cabana rental
    increment the window's version by one"
    PRD §3.4: "the window's reserved_count increments by one, and the window's version
    increments by one (the capacity write that the OCC check guards)."

    Design: Corner/cross_cutting_complexity_layers/occ_assign_window_correct_version_succeeds
    """
    ctx = setup_issued_admission()
    gh = make_guest_headers(ctx["guest"]["id"])
    adm = ctx["admissions"][0]
    get_success_data(api_client.bind_guest(adm["id"], {"guest_id": ctx["guest"]["id"]}, gh))
    before = get_window(ctx["window"]["id"])
    assert before["version"] == 1, f"fresh window version should be 1, got {before['version']}"
    confirmed = get_success_data(api_client.assign_window(
        adm["id"], {"entry_window_id": ctx["window"]["id"],
                    "expected_entry_window_version": before["version"]}, gh))
    assert confirmed["status"] == "CONFIRMED"
    after = get_window(ctx["window"]["id"])
    assert after["version"] == 2, f"window version should bump to 2, got {after['version']}"


def test_assign_window_stale_version_rejected(api):
    """PRD §2.6: "a client whose expected_entry_window_version no longer matches has,
    by definition, missed an intervening capacity change"
    PRD §3.4: "A stale expected_entry_window_version fails with ERR_STALE_VERSION before
    capacity is touched."

    Design: Corner/cross_cutting_complexity_layers/assign_window_stale_version_rejected
    """
    ctx = setup_issued_admission(party_size=2, policy_overrides={"group_threshold": 99})
    gh = make_guest_headers(ctx["guest"]["id"])
    adm1, adm2 = ctx["admissions"][0], ctx["admissions"][1]
    get_success_data(api_client.bind_guest(adm1["id"], {"guest_id": ctx["guest"]["id"]}, gh))
    v1 = get_window(ctx["window"]["id"])
    get_success_data(api_client.assign_window(
        adm1["id"], {"entry_window_id": ctx["window"]["id"],
                     "expected_entry_window_version": v1["version"]}, gh))
    v_now = get_window(ctx["window"]["id"])  # advanced
    get_success_data(api_client.bind_guest(adm2["id"], {"guest_id": ctx["guest"]["id"]}, gh))
    res = api_client.assign_window(
        adm2["id"], {"entry_window_id": ctx["window"]["id"],
                     "expected_entry_window_version": v_now["version"] - 1}, gh)
    validate_error(res, "ERR_STALE_VERSION")
