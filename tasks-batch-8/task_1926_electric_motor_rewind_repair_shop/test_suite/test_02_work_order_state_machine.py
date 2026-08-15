"""Work-order lifecycle state claims (PRD §3.2–§3.5): initial state, invalid
transitions, terminal lockdown, and decline/release side effects."""
from test_helpers import (
    TEST_USERS,
    assert_work_order,
    create_diagnosis_payload,
    create_work_order_payload,
    get_success_data,
    get_work_order,
    make_customer_headers,
    record_incoming_test,
    setup_approved_work_order,
    setup_awaiting_approval,
    setup_balancing_work_order,
    setup_shop_customer_motor,
    setup_work_order_intake,
    validate_error,
    validate_success,
)

MANAGER = TEST_USERS["service_manager_headers"]
TECH = TEST_USERS["technician_headers"]
WINDING = TEST_USERS["winding_technician_headers"]


def test_work_order_starts_in_intake(api):
    """PRD §3.2: "on success the motor's custody flips to `IN_SHOP`, the work
    order opens in `INTAKE` status, and its `invoice_total_cents` initializes
    to zero."

    Design: Corner/state_machines/work_order_starts_in_intake
    """
    bundle = setup_shop_customer_motor()
    shop_id = bundle["shop"]["id"]
    res = api.create_work_order(
        shop_id,
        create_work_order_payload(bundle["customer"]["id"], bundle["motor"]["id"], priority="STANDARD"),
        TECH,
    )
    wo = validate_success(res, 201)
    assert_work_order(wo)
    assert wo["status"] == "INTAKE"
    assert wo["invoice_total_cents"] == 0

    motor = validate_success(api.get_motor(shop_id, bundle["motor"]["id"], MANAGER), 200)
    assert motor["custody"] == "IN_SHOP"


def test_diagnose_from_intake_returns_invalid_state(api):
    """PRD §3.2: "At least one `INCOMING` test record must exist for the work
    order before diagnosis is accepted."
    PRD §2.11: "then whether the target entity sits in a valid from-state for
    the requested transition, rejected with `ERR_INVALID_STATE` (HTTP 409)".

    Design: Corner/state_machines/diagnose_from_intake_returns_invalid_state
    """
    bundle = setup_work_order_intake()
    res = api.diagnose_work_order(
        bundle["shop"]["id"], bundle["work_order"]["id"], create_diagnosis_payload(), TECH
    )
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_terminal_work_order_accepts_no_transitions(api):
    """PRD §3.2: "the status becomes the terminal `SCRAPPED`, the motor's
    custody returns to `WITH_CUSTOMER`, and any quote still in `ISSUED` state
    is moved to `SUPERSEDED`."
    PRD §2.11: "then whether the target entity sits in a valid from-state for
    the requested transition, rejected with `ERR_INVALID_STATE` (HTTP 409)".

    Design: Corner/state_machines/terminal_work_order_accepts_no_transitions
    """
    bundle = setup_work_order_intake()
    shop_id, wo_id = bundle["shop"]["id"], bundle["work_order"]["id"]
    scrapped = validate_success(api.scrap_work_order(shop_id, wo_id, MANAGER), 200)
    assert scrapped["status"] == "SCRAPPED"

    motor = validate_success(api.get_motor(shop_id, bundle["motor"]["id"], MANAGER), 200)
    assert motor["custody"] == "WITH_CUSTOMER"

    res1 = api.start_rewind(shop_id, wo_id, WINDING)
    validate_error(res1, "ERR_INVALID_STATE", expected_status=409)
    res2 = api.close_work_order(shop_id, wo_id, MANAGER)
    validate_error(res2, "ERR_INVALID_STATE", expected_status=409)


def test_quote_decline_side_effects_release_motor(api):
    """PRD §3.3: "The customer declines: the quote moves to `DECLINED`, the
    work order to the terminal `DECLINED`, and the motor's custody returns to
    `WITH_CUSTOMER`."

    Design: Corner/state_machines/quote_decline_side_effects_release_motor
    """
    bundle = setup_awaiting_approval()
    shop_id, wo_id = bundle["shop"]["id"], bundle["work_order"]["id"]
    quote_id = bundle["quote"]["id"]

    quote = validate_success(
        api.decline_quote(shop_id, wo_id, quote_id, make_customer_headers(bundle["customer"]["id"])),
        200,
    )
    assert quote["status"] == "DECLINED"

    wo = validate_success(api.get_work_order(shop_id, wo_id, MANAGER), 200)
    assert wo["status"] == "DECLINED"

    motor = validate_success(api.get_motor(shop_id, bundle["motor"]["id"], MANAGER), 200)
    assert motor["custody"] == "WITH_CUSTOMER"


def test_second_accept_on_accepted_quote_is_invalid_state(api):
    """PRD §3.3: "All four of `ACCEPTED`, `DECLINED`, `SUPERSEDED`, and
    `EXPIRED` are terminal states for a quote; `ISSUED` is the only state from
    which a quote can still move, and `DRAFT` exists only transiently inside
    issuance."

    Design: Corner/state_machines/second_accept_on_accepted_quote_is_invalid_state
    """
    bundle = setup_approved_work_order()
    shop_id, wo_id = bundle["shop"]["id"], bundle["work_order"]["id"]
    assert bundle["work_order"]["status"] == "APPROVED"

    res = api.accept_quote(
        shop_id, wo_id, bundle["quote"]["id"], make_customer_headers(bundle["customer"]["id"])
    )
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_release_from_balancing_returns_invalid_state(api):
    """PRD §3.5: "A successful release computes the invoice total, creates the
    invoice in `OPEN` status, and moves the work order from `FINAL_TEST` to
    `READY_FOR_PICKUP`."
    PRD §2.11: "then whether the target entity sits in a valid from-state for
    the requested transition, rejected with `ERR_INVALID_STATE` (HTTP 409)".

    Design: Corner/state_machines/release_requires_final_pass_precondition_enforcement
    """
    bundle = setup_balancing_work_order()
    assert bundle["work_order"]["status"] == "BALANCING"

    res = api.release_work_order(bundle["shop"]["id"], bundle["work_order"]["id"], MANAGER)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)
