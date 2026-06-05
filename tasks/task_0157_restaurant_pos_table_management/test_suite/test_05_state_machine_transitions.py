"""Initial state, invalid/idempotent transitions, terminal lockdown, guarded
reopen, the void-check 86 cascade, and payment-void compensation.
"""
from test_helpers import (
    get_success_data, validate_success, validate_error, ApiErrorId,
    TEST_USERS, make_server_headers,
    create_restaurant_payload, set_clock_payload, create_menu_item_payload,
    create_table_payload, create_staff_member_payload, create_seating_payload,
    create_check_payload, create_course_payload, create_order_item_payload,
    create_waitlist_payload, create_payment_payload,
    setup_seated_restaurant, setup_fired_single_item,
)

MANAGER = TEST_USERS["manager_headers"]
HOST = TEST_USERS["host_headers"]


def test_new_check_initial_state_open(api):
    """PRD §3.4: "A new check's status is OPEN with all monetary fields at zero."

    Design: Corner/state_machines/check_initial_state_open_on_create
    """
    ctx = setup_seated_restaurant(clock_iso="2026-06-02T10:00:00Z", name="R", tax_rate_bps=0)
    data = validate_success(api.create_check(create_check_payload(
        ctx["restaurant"]["id"], ctx["seating"]["id"], ctx["staff"]["id"], party_size=2),
        ctx["server_headers"]), expected_status=201)
    assert data["status"] == "OPEN"
    assert data["provisional_subtotal_cents"] == 0


def test_close_open_check_without_present_invalid_state(api):
    """PRD §3.7: "Closing is a Server action legal only when the check is PRESENTED
    and fully tendered".

    Design: Corner/state_machines/close_open_check_without_present_invalid_state
    """
    ctx = setup_fired_single_item(
        base_price_cents=1000, happy_hour_price_cents=1000, quantity=1,
        clock_iso="2026-06-02T10:00:00Z", name="R", tax_rate_bps=0)
    validate_error(api.close_check(ctx["check"]["id"], ctx["server_headers"]),
                   ApiErrorId.ERR_INVALID_STATE.value)


def test_fire_already_fired_course_invalid_state(api):
    """PRD §3.4: "Firing a course sends it to the kitchen and is legal only when
    the course's status is BUILDING".

    Design: Corner/state_machines/fire_already_fired_course_idempotency_invalid_state
    """
    ctx = setup_fired_single_item(
        base_price_cents=1000, happy_hour_price_cents=1000, quantity=1,
        clock_iso="2026-06-02T10:00:00Z", name="R", tax_rate_bps=0)
    validate_error(api.fire_course(ctx["course"]["id"], ctx["server_headers"]),
                   ApiErrorId.ERR_INVALID_STATE.value)


def test_reopen_after_settled_payment_invalid_state(api):
    """PRD §3.7: "a Server may reopen a presented check, but only while its
    amount_paid_cents is zero — that is, before any settled payment exists ... An
    illegal present or reopen is rejected with ERR_INVALID_STATE."

    Design: Corner/state_machines/reopen_after_payment_blocked_invalid_state
    """
    ctx = setup_fired_single_item(
        base_price_cents=1000, happy_hour_price_cents=1000, quantity=1,
        clock_iso="2026-06-02T10:00:00Z", name="R", tax_rate_bps=0)
    sh = ctx["server_headers"]
    api.present_check(ctx["check"]["id"], sh)
    api.create_payment(create_payment_payload(
        ctx["restaurant"]["id"], ctx["check"]["id"], amount_cents=500,
        tip_cents=0, method="CASH"), sh)
    validate_error(api.reopen_check(ctx["check"]["id"], sh),
                   ApiErrorId.ERR_INVALID_STATE.value)


def test_cancel_already_cancelled_waitlist_invalid_state(api):
    """PRD §3.2: "Cancellation is legal only from WAITING; attempting it from any
    other state is rejected with ERR_INVALID_STATE."

    Design: Corner/state_machines/cancel_already_cancelled_waitlist_invalid_state
    """
    r = get_success_data(api.create_restaurant(create_restaurant_payload(
        name="R", tax_rate_bps=0), MANAGER))
    wl = get_success_data(api.create_waitlist_entry(create_waitlist_payload(
        r["id"], party_name="Lee", party_size=2), HOST))
    api.cancel_waitlist_entry(wl["id"], HOST)
    validate_error(api.cancel_waitlist_entry(wl["id"], HOST),
                   ApiErrorId.ERR_INVALID_STATE.value)


def test_void_check_restores_all_item_counts(api):
    """PRD §3.7: "Voiding moves the check to VOID and, as a cascade, voids every
    order item on the check that is not already voided, restoring each affected
    menu item's available_count by the voided quantity — the same compensating
    restore that a single item void performs."

    Design: Corner/state_machines/void_check_restores_all_items_86_counts_cascade_down
    """
    ctx = setup_fired_single_item(
        base_price_cents=1000, happy_hour_price_cents=1000, quantity=1,
        initial_available_count=5, clock_iso="2026-06-02T10:00:00Z",
        name="R", tax_rate_bps=0)
    # Add a second item of the same menu item to the same (already fired) check via
    # a second course so that count is 5 → 3 after fires.
    r = ctx["restaurant"]
    sh = ctx["server_headers"]
    crs2 = get_success_data(api.create_course(create_course_payload(
        r["id"], ctx["check"]["id"], course_number=2), sh))
    api.create_order_item(create_order_item_payload(
        r["id"], crs2["id"], ctx["menu_item"]["id"], quantity=1), sh)
    api.fire_course(crs2["id"], sh)
    mi_mid = get_success_data(api.get_menu_item(ctx["menu_item"]["id"], MANAGER))
    assert mi_mid["available_count"] == 3, "two fired qty-1 items → 5-2=3"
    voided = validate_success(api.void_check(ctx["check"]["id"], MANAGER))
    assert voided["status"] == "VOID"
    mi = get_success_data(api.get_menu_item(ctx["menu_item"]["id"], MANAGER))
    assert mi["available_count"] == 5, f"all items restored, got {mi['available_count']}"


def test_void_payment_drops_amount_and_tip_from_check(api):
    """PRD §3.7: "A Manager may void a settled payment, but only while the owning
    check is OPEN or PRESENTED — never on a closed check; voiding moves the payment
    from SETTLED to VOIDED and recomputes the check's amount_paid_cents and
    tip_cents so the reversed payment drops out."

    Design: Corner/state_machines/void_payment_recomputes_check_amount_paid_compensation
    """
    ctx = setup_fired_single_item(
        base_price_cents=1000, happy_hour_price_cents=1000, quantity=1,
        clock_iso="2026-06-02T10:00:00Z", name="R", tax_rate_bps=0)
    sh = ctx["server_headers"]
    api.present_check(ctx["check"]["id"], sh)
    pay = get_success_data(api.create_payment(create_payment_payload(
        ctx["restaurant"]["id"], ctx["check"]["id"], amount_cents=1000,
        tip_cents=200, method="CARD"), sh))
    voided = validate_success(api.void_payment(pay["id"], MANAGER))
    assert voided["status"] == "VOIDED"
    chk = get_success_data(api.get_check(ctx["check"]["id"], sh))
    assert chk["amount_paid_cents"] == 0
    assert chk["tip_cents"] == 0
