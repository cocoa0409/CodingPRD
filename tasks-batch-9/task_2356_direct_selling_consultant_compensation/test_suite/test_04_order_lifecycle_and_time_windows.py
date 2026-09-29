"""Orders: two parallel status dimensions, the period coupling on payment and the clock windows."""

from test_helpers import (
    assert_instant,
    constants as k,
    factories as f,
    fixtures as fx,
    make_consultant_headers,
    TEST_USERS,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]


def _pending_serum_order(api, consultant_email="quinn@example.com", quantity=5):
    """A root consultant with one unpaid BUSINESS_SUPPLY order posted to 2026-08."""
    env = fx.setup_environment(api)
    consultant = fx.enroll_root(api, env, consultant_email, "Quinn Root")
    order = fx.place_order(
        api, env, consultant, [("SERUM", quantity)], order_type="BUSINESS_SUPPLY"
    )
    return env, consultant, order


def _read_order(api, order_id):
    return validate_success(api.get_product_order(order_id, ADMIN))


def test_shipping_an_unpaid_order_is_refused_then_payment_moves_only_its_own_dimension(api):
    """SHIP reaches across to the payment dimension and is refused while the order is PENDING;
    paying it then advances payment alone and leaves fulfillment at NEW.

    PRD: "A `SHIP` event requires `fulfillment_status` `NEW` and `payment_status` `PAID`, and
    moves fulfillment `NEW → SHIPPED`."

    Design: Difficulty/non_linear_state_machine/order_payment_and_fulfillment_dimensions_advance_independently
    """
    env, quinn, order = _pending_serum_order(api)
    assert order["total_due_cents"] == 12645, "five SERUM in TX cost 12,645 cents"
    assert order["payment_status"] == "PENDING", "a new order starts PENDING"
    assert order["fulfillment_status"] == "NEW", "a new order starts NEW"

    validate_error(
        api.advance_fulfillment(order["id"], f.fulfillment_payload("SHIP"), ADMIN),
        "ERR_FULFILLMENT_SEQUENCE_INVALID",
        409,
    )
    unchanged = _read_order(api, order["id"])
    assert unchanged["payment_status"] == "PENDING", "the refused SHIP wrote nothing"
    assert unchanged["fulfillment_status"] == "NEW", "the refused SHIP left fulfillment at NEW"

    paid = validate_success(
        api.pay_product_order(
            order["id"],
            f.pay_order_payload(12645, "ORD-PAY-Q"),
            make_consultant_headers(quinn["id"]),
        )
    )
    assert paid["payment_status"] == "PAID", "the payment dimension moved"
    assert paid["fulfillment_status"] == "NEW", "the fulfillment dimension did not move with it"
    assert paid["volume_posted"] is True, "payment posted the order's volume"


def test_fulfillment_advances_twice_without_any_further_payment_write(api):
    """DELIVER never consults payment, so it is refused from NEW even on a PAID order, and once
    SHIP has run the fulfillment dimension advances alone to DELIVERED.

    PRD: "A `DELIVER` event requires `fulfillment_status` `SHIPPED` and moves it
    `SHIPPED → DELIVERED`."

    Design: Difficulty/non_linear_state_machine/order_payment_and_fulfillment_dimensions_advance_independently
    """
    env, quinn, order = _pending_serum_order(api)
    period = env["periods"]["2026-08"]
    fx.pay_order(api, quinn, order, amount_cents=12645, reference="ORD-PAY-Q")

    validate_error(
        api.advance_fulfillment(order["id"], f.fulfillment_payload("DELIVER"), ADMIN),
        "ERR_FULFILLMENT_SEQUENCE_INVALID",
        409,
    )

    shipped = validate_success(
        api.advance_fulfillment(order["id"], f.fulfillment_payload("SHIP"), ADMIN)
    )
    assert shipped["payment_status"] == "PAID", "shipping left payment untouched"
    assert shipped["fulfillment_status"] == "SHIPPED", "SHIP moved NEW to SHIPPED"

    delivered = validate_success(
        api.advance_fulfillment(order["id"], f.fulfillment_payload("DELIVER"), ADMIN)
    )
    assert delivered["payment_status"] == "PAID", "delivering left payment untouched"
    assert delivered["fulfillment_status"] == "DELIVERED", "DELIVER moved SHIPPED to DELIVERED"

    qualification = fx.qualification_of(api, quinn["id"], period["id"])
    assert qualification["personal_volume_points"] == 100, "five SERUM carry one hundred points"
    assert qualification["net_personal_volume_points"] == 100, "nothing was returned"


def test_payment_is_refused_while_the_posted_period_is_closed(api):
    """An already-created PENDING order cannot be paid once its posted period has been locked
    and closed, and the refusal writes nothing to the order.

    PRD: "the posted period must still be `OPEN` or `REOPENED`, or
    `ERR_PERIOD_NOT_ACCEPTING_VOLUME`".

    Design: Difficulty/cross_entity_state_dependency/order_payment_blocked_once_period_locked_and_admitted_after_reopen
    """
    env, hank, order = _pending_serum_order(api, "hank@example.com", quantity=25)
    period = env["periods"]["2026-08"]
    assert order["total_due_cents"] == 58250, "twenty-five SERUM in TX cost 58,250 cents"
    assert order["total_volume_points"] == 500, "twenty-five units at twenty points each"

    locked = fx.lock_period(api, period)
    assert locked["status"] == "LOCKED", "the lock froze the period"
    assert locked["qualification_count"] == 1, "the lock created a row for the only consultant"

    closed = fx.close_period(api, locked)
    assert closed["status"] == "CLOSED", "the close settled tenure"
    assert closed["total_net_personal_volume_points"] == 0, "the unpaid order posted no volume"

    validate_error(
        api.pay_product_order(
            order["id"],
            f.pay_order_payload(58250, "ORD-PAY-H"),
            make_consultant_headers(hank["id"]),
        ),
        "ERR_PERIOD_NOT_ACCEPTING_VOLUME",
        409,
    )
    still_pending = _read_order(api, order["id"])
    assert still_pending["payment_status"] == "PENDING", "the refused payment wrote nothing"
    assert still_pending["volume_posted"] is False, "no volume entered the system"


def test_reopening_the_period_admits_the_identical_payment_and_its_five_hundred_points(api):
    """Reopening the closed period makes group volume live again, and the byte-identical payment
    call now posts the five hundred points it was previously refused.

    PRD: "On success `status` becomes `REOPENED` in the transition `CLOSED → REOPENED`,
    `reopen_count` is incremented by 1".

    Design: Difficulty/cross_entity_state_dependency/order_payment_blocked_once_period_locked_and_admitted_after_reopen
    """
    env, hank, order = _pending_serum_order(api, "hank@example.com", quantity=25)
    period = env["periods"]["2026-08"]
    fx.close_period(api, fx.lock_period(api, period))

    validate_error(
        api.pay_product_order(
            order["id"],
            f.pay_order_payload(58250, "ORD-PAY-H"),
            make_consultant_headers(hank["id"]),
        ),
        "ERR_PERIOD_NOT_ACCEPTING_VOLUME",
        409,
    )

    reopened = fx.reopen_period(api, period, "late payment of an order posted to this period")
    assert reopened["status"] == "REOPENED", "a closed period is exitable through REOPENED"
    assert reopened["reopen_count"] == 1, "reopen_count is incremented by one"

    paid = validate_success(
        api.pay_product_order(
            order["id"],
            f.pay_order_payload(58250, "ORD-PAY-H"),
            make_consultant_headers(hank["id"]),
        )
    )
    assert paid["payment_status"] == "PAID", "the identical call now succeeds"
    assert paid["volume_posted"] is True, "the late volume entered the system"

    qualification = fx.qualification_of(api, hank["id"], period["id"])
    assert qualification["personal_volume_points"] == 500, "the whole order posted"
    assert qualification["net_personal_volume_points"] == 500, "nothing was returned"
    assert qualification["group_volume_points"] == 500, (
        "group volume became live again on reopen and picked up the late payment"
    )

    after = fx.read_period(api, period["id"])
    assert after["total_net_personal_volume_points"] == 500, (
        "the period's derived total picked up the late volume"
    )
    assert after["status"] == "REOPENED", "the period remains REOPENED"


def test_fulfillment_endpoint_enforces_its_sequence_and_the_exact_payment_amount(api):
    """The fulfillment action refuses to skip or repeat a step, and payment refuses any amount
    other than the exact total due.

    PRD: "the submitted `amount_cents` must equal `total_due_cents` exactly, per-line tax and
    shipping included, or `ERR_ORDER_AMOUNT_MISMATCH`".

    Design: Corner/endpoints/fulfillment_action_endpoint_enforces_its_own_sequence_and_a_payment_guard
    """
    env, alice, order = _pending_serum_order(api, "alice@example.com")
    assert order["total_due_cents"] == 12645, "five SERUM in TX cost 12,645 cents"

    validate_error(
        api.advance_fulfillment(order["id"], f.fulfillment_payload("SHIP"), ADMIN),
        "ERR_FULFILLMENT_SEQUENCE_INVALID",
        409,
    )
    validate_error(
        api.pay_product_order(order["id"], f.pay_order_payload(12000, "SHORT"), ADMIN),
        "ERR_ORDER_AMOUNT_MISMATCH",
        422,
    )

    paid = validate_success(
        api.pay_product_order(order["id"], f.pay_order_payload(12645, "PAY-1"), ADMIN)
    )
    assert paid["payment_status"] == "PAID", "the exact amount is accepted"
    assert paid["fulfillment_status"] == "NEW", "payment does not ship the order"

    validate_error(
        api.advance_fulfillment(order["id"], f.fulfillment_payload("DELIVER"), ADMIN),
        "ERR_FULFILLMENT_SEQUENCE_INVALID",
        409,
    )
    shipped = validate_success(
        api.advance_fulfillment(order["id"], f.fulfillment_payload("SHIP"), ADMIN)
    )
    assert shipped["fulfillment_status"] == "SHIPPED", "SHIP is legal from NEW once paid"
    assert shipped["payment_status"] == "PAID", "shipping leaves payment_status PAID untouched"

    validate_error(
        api.advance_fulfillment(order["id"], f.fulfillment_payload("SHIP"), ADMIN),
        "ERR_FULFILLMENT_SEQUENCE_INVALID",
        409,
    )
    delivered = validate_success(
        api.advance_fulfillment(order["id"], f.fulfillment_payload("DELIVER"), ADMIN)
    )
    assert delivered["fulfillment_status"] == "DELIVERED", "DELIVER is legal from SHIPPED"
    assert delivered["payment_status"] == "PAID", "delivering leaves payment_status PAID untouched"


def test_three_time_windows_reject_operations_that_are_otherwise_valid(api):
    """The period interval, the buyback window and the appeal deadline each refuse an operation
    whose every other precondition holds, and none of them mutates a row.

    PRD: "Then the logical clock must fall inside that period's half-open interval, at or after
    its `period_start` and strictly before its `period_end`".

    Design: Corner/validations/three_time_windows_reject_operations_that_are_otherwise_valid
    """
    env = fx.setup_two_period_environment(api)
    alice = fx.enroll_root(api, env)
    order = fx.place_and_pay_order(
        api, env, alice, [("SERUM", 5)], order_type="PERSONAL_INVENTORY"
    )
    case = fx.sanction_consultant(
        api,
        alice,
        sanction_level="PROBATION",
        effective_from="2026-08-05T00:00:00Z",
        effective_until="2026-08-20T00:00:00Z",
    )
    assert_instant(
        case["appeal_deadline_at"], "2026-08-19T00:00:00Z", "appeal_deadline_at"
    )
    assert case["status"] == "SANCTIONED", "the sanction was imposed"
    assert case["appeal_count"] == 0, "no appeal has been filed yet"

    validate_error(
        api.create_product_order(
            f.product_order_payload(
                alice["id"],
                fx.lines_for(env, ("SERUM", 5)),
                order_type="BUSINESS_SUPPLY",
                posted_period_code="2026-07",
                ship_to_state_code="TX",
            ),
            ADMIN,
        ),
        "ERR_PERIOD_CODE_MISMATCH",
        422,
    )

    fx.set_clock(api, "2027-09-01T00:00:00Z")

    validate_error(
        api.create_buyback_request(
            f.buyback_request_payload(
                alice["id"], fx.buyback_lines_from_order(env, order, "SERUM", 1)
            ),
            ADMIN,
        ),
        "ERR_BUYBACK_WINDOW_EXPIRED",
        422,
    )
    validate_error(
        api.appeal_compliance_case(
            case["id"],
            f.appeal_payload("Late appeal"),
            make_consultant_headers(alice["id"]),
        ),
        "ERR_APPEAL_WINDOW_EXPIRED",
        422,
    )

    case_after = validate_success(api.get_compliance_case(case["id"], ADMIN))
    assert case_after["status"] == "SANCTIONED", "the expired appeal changed nothing"
    assert case_after["appeal_count"] == 0, "no appeal was recorded"
    order_after = _read_order(api, order["id"])
    assert order_after["payment_status"] == "PAID", "the refused buyback left the order paid"
    assert order_after["returned_volume_points"] == 0, "no volume was returned"
    assert k.PLAN_DEFAULTS["buyback_window_days"] == 365, (
        "the order is 396 days old, beyond the plan's one-year buyback window"
    )
