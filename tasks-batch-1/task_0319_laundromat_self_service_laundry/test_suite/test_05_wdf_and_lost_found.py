"""Wash-dry-fold pipeline and lost-and-found lifecycle tests."""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    TEST_USERS,
    make_member_headers,
    make_attendant_headers,
    create_member,
    create_plan,
    set_clock,
    intake_wdf_order,
    setup_ready_wdf_order,
    setup_paid_wdf_order,
    log_lost_found,
    pay_wdf_order_payload,
    claim_lost_found_payload,
    create_wdf_order_payload,
)

MANAGER = TEST_USERS["manager_headers"]
ATTENDANT = TEST_USERS["attendant_headers"]


def test_wdf_pay_from_dropped_rejected(api):
    """PRD §3.5: "Settlement happens at pickup: a member or an attendant pays a
    `READY` order".
    PRD §2.10: "State validity is sixth: the target resource must be in a state
    that admits the requested transition, or `ERR_INVALID_STATE` (HTTP 409)."

    Design: Corner/state_machines/wdf_pay_from_dropped_returns_invalid_state
    """
    set_clock("2026-06-01T10:00:00Z")
    create_plan()
    attendant = create_member(full_name="A One", phone="555-0100", card_token="tok-a1")
    order = intake_wdf_order(attendant["id"], 20)
    resp = api.pay_wdf_order(
        order["id"], pay_wdf_order_payload("CASH"), make_attendant_headers(attendant["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    order_now = validate_success(api.get_wdf_order(order["id"], MANAGER), 200)
    assert order_now["status"] == "DROPPED"


def test_wdf_cancel_from_paid_terminal_lockdown(api):
    """PRD §3.5: "At any point before payment — while the order is `DROPPED`,
    `WASHING`, or `READY`, but never once `PAID` — a member or attendant may
    cancel it ... Both `PAID` and `CANCELLED` are terminal."

    Design: Corner/state_machines/wdf_cancel_from_paid_terminal_lockdown
    """
    plan, attendant_id, member, order = setup_paid_wdf_order(weight_lb=20, member_principal_cents=5000)
    assert order["status"] == "PAID"
    resp = api.cancel_wdf_order(order["id"], make_member_headers(member["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    order_now = validate_success(api.get_wdf_order(order["id"], MANAGER), 200)
    assert order_now["status"] == "PAID"


def test_lost_found_claim_sets_claimed_by(api):
    """PRD §3.8: "An attendant may mark a `LOGGED` item claimed by supplying the
    `claimed_by_id` of the member claiming it, which moves it
    `LOGGED → CLAIMED` and records that member."

    Design: Corner/state_machines/lostfound_claim_sets_claimed_by_side_effect
    """
    attendant = create_member(full_name="A One", phone="555-0100", card_token="tok-a1")
    member = create_member(full_name="M One", phone="555-0001", card_token="tok-m1")
    item = log_lost_found(attendant["id"], description="blue sock")
    resp = api.claim_lost_found(
        item["id"], claim_lost_found_payload(member["id"]),
        make_attendant_headers(attendant["id"]))
    claimed = validate_success(resp, 200)
    assert claimed["status"] == "CLAIMED"
    assert claimed["claimed_by_id"] == member["id"]


def test_dispose_before_hold_window_rejected(api):
    """PRD §3.8: "disposal is permitted only when the difference between the
    current capture clock and the item's `found_at` is at least the
    disposal-hold window, and an attempt before that window elapses is rejected
    with `ERR_DISPOSAL_HOLD_ACTIVE` (HTTP 409)."

    Design: Corner/validations/dispose_before_hold_window_returns_409
    """
    set_clock("2026-06-01T10:00:00Z")
    attendant = create_member(full_name="A One", phone="555-0100", card_token="tok-a1")
    item = log_lost_found(attendant["id"], description="red glove")
    # No time elapsed since found_at -> hold window cannot have passed.
    resp = api.dispose_lost_found(item["id"], make_attendant_headers(attendant["id"]))
    validate_error(resp, ApiErrorId.ERR_DISPOSAL_HOLD_ACTIVE.value)
    item_now = validate_success(api.get_lost_found(item["id"], MANAGER), 200)
    assert item_now["status"] == "LOGGED"
