"""Confirmation preconditions: the suspension guard and the credit line."""
from test_helpers import (
    new_order,
    new_order_line,
    quote_order,
    read_facility,
    read_order,
    setup_configured_order,
    suspend_facility,
    validate_error,
    validate_success,
)

SMALL_LIMIT = 1_000_000


def _facility_overrides(account_name, credit_limit_cents=SMALL_LIMIT):
    return {"account_name": account_name, "freight_zone": "Z1",
            "credit_limit_cents": credit_limit_cents}


def _quoted_order_pair_on_two_facilities(quantity):
    """Two identically quoted orders sitting at two identically capped facilities."""
    first = setup_configured_order(
        preset="T900", quantity=quantity,
        facility_overrides=_facility_overrides("Ashgrove Athletic Club"),
    )
    second = setup_configured_order(
        revision_ctx=first, quantity=quantity,
        facility_overrides=_facility_overrides("Brookside Athletic Club"),
    )
    first["order"] = quote_order(first["order"]["id"])
    second["order"] = quote_order(second["order"]["id"])
    return first, second


def test_suspended_facility_outranks_the_credit_gate_on_confirm(
    api, order_planner_headers
):
    """One confirm breaks both rules and reports the suspension, not the credit line.

    The PRD states that four preconditions apply to confirmation and lists them in
    order: "the `billing_status` must be `QUOTED` (`ERR_ORDER_NOT_QUOTED`), the
    facility's `status` must be `ACTIVE` (`ERR_FACILITY_SUSPENDED`), the order must
    have at least one `ACTIVE` line (`ERR_ORDER_HAS_NO_LINES`), and the credit gate
    must clear".

    Design: Difficulty/priority_pair_validation_conflict/facility_suspension_outranks_credit_limit_check_on_confirm
    """
    doomed, _control = _quoted_order_pair_on_two_facilities(quantity=2)
    assert doomed["order"]["quoted_total_cents"] == 1_120_619
    suspended = suspend_facility(doomed["facility"]["id"],
                                 suspend_reason="account placed on credit hold")
    assert suspended["status"] == "SUSPENDED"
    assert suspended["credit_limit_cents"] == SMALL_LIMIT
    assert suspended["open_order_exposure_cents"] == 0

    response = api.confirm_order(doomed["order"]["id"], order_planner_headers)

    error = validate_error(response, "ERR_FACILITY_SUSPENDED", 409)
    assert error["error_id"] != "ERR_CREDIT_LIMIT_EXCEEDED"
    assert response.status_code != 402
    order = read_order(doomed["order"]["id"])
    assert order["config_status"] == "CONFIGURING"
    assert order["fulfillment_status"] == "PENDING"
    assert order["billing_status"] == "QUOTED"
    assert order["quoted_total_cents"] == 1_120_619
    facility = read_facility(doomed["facility"]["id"])
    assert facility["status"] == "SUSPENDED"
    assert facility["open_order_exposure_cents"] == 0


def test_the_same_over_limit_order_returns_the_credit_code_at_an_active_facility(
    api, order_planner_headers
):
    """The control order proves the credit gate would otherwise have fired.

    The PRD states that the credit gate is "the facility's
    `open_order_exposure_cents` plus this order's `quoted_total_cents` must be less
    than or equal to the facility's `credit_limit_cents`, with equality explicitly
    allowed. Exceeding the limit is `ERR_CREDIT_LIMIT_EXCEEDED`."

    Design: Difficulty/priority_pair_validation_conflict/facility_suspension_outranks_credit_limit_check_on_confirm
    """
    doomed, control = _quoted_order_pair_on_two_facilities(quantity=2)
    suspend_facility(doomed["facility"]["id"],
                     suspend_reason="account placed on credit hold")
    assert control["order"]["quoted_total_cents"] == 1_120_619
    assert read_facility(control["facility"]["id"])["status"] == "ACTIVE"

    response = api.confirm_order(control["order"]["id"], order_planner_headers)

    validate_error(response, "ERR_CREDIT_LIMIT_EXCEEDED", 402)
    order = read_order(control["order"]["id"])
    assert order["config_status"] == "CONFIGURING"
    assert order["fulfillment_status"] == "PENDING"
    assert order["billing_status"] == "QUOTED"
    facility = read_facility(control["facility"]["id"])
    assert facility["open_order_exposure_cents"] == 0
    assert facility["credit_limit_cents"] == SMALL_LIMIT
    assert 1_120_619 > SMALL_LIMIT, "the control order alone breaches the limit"


def test_suspension_refuses_even_an_affordable_order_that_would_otherwise_confirm(
    api, order_planner_headers
):
    """With the credit gate satisfied, suspension alone still blocks confirmation.

    The PRD states that a "`SUSPENDED` facility can no longer have orders created,
    lines added, quotes taken, orders confirmed, maintenance programs activated, or
    refurbished units resold to it — all of those surface `ERR_FACILITY_SUSPENDED`."

    Design: Difficulty/priority_pair_validation_conflict/facility_suspension_outranks_credit_limit_check_on_confirm
    """
    blocked, allowed = _quoted_order_pair_on_two_facilities(quantity=1)
    assert blocked["order"]["quoted_total_cents"] == 560_310
    assert 560_310 <= SMALL_LIMIT
    suspend_facility(blocked["facility"]["id"],
                     suspend_reason="account placed on credit hold")

    validate_error(
        api.confirm_order(blocked["order"]["id"], order_planner_headers),
        "ERR_FACILITY_SUSPENDED", 409,
    )
    confirmed = validate_success(
        api.confirm_order(allowed["order"]["id"], order_planner_headers)
    )

    assert confirmed["config_status"] == "CONFIRMED"
    assert confirmed["fulfillment_status"] == "IN_PRODUCTION"
    assert confirmed["billing_status"] == "QUOTED"
    assert read_order(blocked["order"]["id"])["config_status"] == "CONFIGURING"
    assert read_facility(blocked["facility"]["id"])["open_order_exposure_cents"] == 0
    assert read_facility(allowed["facility"]["id"])[
        "open_order_exposure_cents"
    ] == 560_310


def _two_quoted_orders_on_one_facility(credit_limit_cents):
    """One capped facility carrying two separately quoted single-unit orders."""
    ctx = setup_configured_order(
        preset="T900", quantity=1,
        facility_overrides=_facility_overrides("Riverbend Fitness Collective",
                                               credit_limit_cents),
    )
    ctx["order"] = quote_order(ctx["order"]["id"])
    second_order = new_order(ctx["facility"]["id"])
    new_order_line(second_order["id"], ctx["revision"]["id"], quantity=1,
                   layout_zone_label="CARDIO-ANNEX")
    ctx["second_order"] = quote_order(second_order["id"])
    return ctx


def test_two_affordable_orders_breach_the_limit_once_their_exposure_is_summed(
    api, order_planner_headers
):
    """Each order fits the credit line, but their sum does not.

    The PRD states that a facility exposes "`open_order_exposure_cents`, the sum of
    `quoted_total_cents` over its own orders whose `config_status` is `CONFIRMED`
    and whose `billing_status` is `QUOTED` or `INVOICED`".

    Design: Corner/validations/two_individually_affordable_orders_exceed_the_credit_limit_together
    """
    ctx = _two_quoted_orders_on_one_facility(SMALL_LIMIT)
    assert ctx["order"]["quoted_total_cents"] == 560_310
    assert ctx["second_order"]["quoted_total_cents"] == 560_310

    first = validate_success(
        api.confirm_order(ctx["order"]["id"], order_planner_headers)
    )
    assert first["config_status"] == "CONFIRMED"
    assert first["fulfillment_status"] == "IN_PRODUCTION"
    after_first = read_facility(ctx["facility"]["id"])
    assert after_first["open_order_exposure_cents"] == 560_310
    assert after_first["open_order_exposure_cents"] <= SMALL_LIMIT

    validate_error(
        api.confirm_order(ctx["second_order"]["id"], order_planner_headers),
        "ERR_CREDIT_LIMIT_EXCEEDED", 402,
    )

    assert 560_310 + 560_310 == 1_120_620 > SMALL_LIMIT
    after_denial = read_facility(ctx["facility"]["id"])
    assert after_denial["open_order_exposure_cents"] == 560_310
    refused = read_order(ctx["second_order"]["id"])
    assert refused["config_status"] == "CONFIGURING"
    assert refused["fulfillment_status"] == "PENDING"
    assert refused["billing_status"] == "QUOTED"
    assert refused["quoted_total_cents"] == 560_310


def test_summed_exposure_landing_exactly_on_the_limit_is_allowed(
    api, order_planner_headers
):
    """Two confirms that add up to the limit exactly both go through.

    The PRD states that the credit gate requires the exposure plus the order total
    to be "less than or equal to the facility's `credit_limit_cents`, with equality
    explicitly allowed."

    Design: Corner/validations/two_individually_affordable_orders_exceed_the_credit_limit_together
    """
    ctx = _two_quoted_orders_on_one_facility(1_120_620)

    validate_success(api.confirm_order(ctx["order"]["id"], order_planner_headers))
    second = validate_success(
        api.confirm_order(ctx["second_order"]["id"], order_planner_headers)
    )

    assert second["config_status"] == "CONFIRMED"
    assert second["fulfillment_status"] == "IN_PRODUCTION"
    facility = read_facility(ctx["facility"]["id"])
    assert facility["open_order_exposure_cents"] == 1_120_620
    assert facility["open_order_exposure_cents"] == facility["credit_limit_cents"]
    assert read_order(ctx["order"]["id"])["config_status"] == "CONFIRMED"
