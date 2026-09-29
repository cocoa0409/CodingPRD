"""The four timing guards and the two aggregate quotas that govern holds."""

from test_helpers import (
    OPS_AGENT_HEADERS,
    api_client,
    create_active_plan,
    create_active_print_plan,
    create_hold,
    create_registered_reader,
    invoice_for_cycle,
    list_holds,
    make_reader_headers,
    open_subscription,
    read_hold,
    read_subscription,
    record_payment,
    set_clock_date,
    validate_error,
)
from test_helpers import factories as f


def _paid_print_subscription(plan_name, reader_email):
    """An ACTIVE PRINT_DIGITAL subscription whose cycle-1 invoice of 999 is paid."""
    set_clock_date("2026-09-01")
    plan = create_active_print_plan(
        name=plan_name,
        intro_price_cents=999,
        intro_cycles=1,
        standard_price_cents=1899,
        standard_from_cycle=2,
        cycle_days=30,
        print_component_cents=900,
        print_deliveries_per_cycle=4,
        print_delivery_days=["SUN"],
    )
    reader = create_registered_reader(reader_email)
    subscription = open_subscription(reader["id"], plan["id"])
    record_payment(invoice_for_cycle(subscription["id"], 1), "SUCCEEDED", 999)
    return subscription, make_reader_headers(reader["id"])


def test_a_vacation_hold_has_no_meaning_on_a_digital_only_subscription():
    """There is no print economics to give back, so the request never becomes a hold.

    PRD: "Both print hold types additionally require the economics to exist: a `VACATION_DELIVERY` or `DELIVERY_INTERRUPTION` hold on a plan whose `bundle_type` is not `PRINT_DIGITAL`, or whose `print_deliveries_per_cycle` is below 1, answers `ERR_PLAN_NOT_PRINT_BUNDLE` (HTTP 422)."
    PRD: "On a `PRINT_DIGITAL` plan the same success also moves `print_fulfillment_status` from `NOT_APPLICABLE` to `SCHEDULED`; on any other bundle that dimension stays `NOT_APPLICABLE` for life."

    Design: Corner/validations/vacation_hold_on_digital_only_plan_rejected
    """
    set_clock_date("2026-09-01")
    plan = create_active_plan(name="Digital NoPrint")
    reader = create_registered_reader("noprint@mail.test")
    subscription = open_subscription(reader["id"], plan["id"])
    record_payment(invoice_for_cycle(subscription["id"], 1), "SUCCEEDED", 499)

    response = api_client.create_hold(
        subscription["id"],
        f.create_hold_payload("VACATION_DELIVERY", "2026-09-10", "2026-09-17"),
        make_reader_headers(reader["id"]),
    )

    validate_error(response, "ERR_PLAN_NOT_PRINT_BUNDLE", 422)
    assert list_holds(subscription["id"]) == []
    after = read_subscription(subscription["id"])
    assert after["print_fulfillment_status"] == "NOT_APPLICABLE"
    assert after["vacation_days_used_365"] == 0


def test_a_reader_may_not_start_a_vacation_hold_on_the_clock_date_itself():
    """Today is on or before the clock date, so the reader must plan a day ahead.

    PRD: "Reader-initiated holds must be genuinely future-dated: a `VACATION_DELIVERY` or `PAUSE_BILLING` hold whose `start_date` is on or before the clock date answers `ERR_HOLD_START_NOT_FUTURE` (HTTP 422)."
    PRD: "Creating a hold recomputes the subscription's `pending_credit_cents` upward — that field is the sum of `credit_cents` over holds on the subscription whose `status` is `SCHEDULED`, `ACTIVE` or `COMPLETED` and whose `credit_applied` is false — and recomputes `vacation_days_used_365` for a vacation hold."

    Design: Corner/validations/vacation_hold_starting_today_rejected
    """
    subscription, reader_headers = _paid_print_subscription(
        "Print Today", "today@mail.test"
    )

    response = api_client.create_hold(
        subscription["id"],
        f.create_hold_payload("VACATION_DELIVERY", "2026-09-01", "2026-09-08"),
        reader_headers,
    )

    validate_error(response, "ERR_HOLD_START_NOT_FUTURE", 422)
    assert list_holds(subscription["id"]) == []
    assert read_subscription(subscription["id"])["pending_credit_cents"] == 0


def test_a_publisher_interruption_may_start_today_but_never_yesterday():
    """The relaxed guard has its own code, so the past start is not the same refusal.

    PRD: "A publisher-caused `DELIVERY_INTERRUPTION` may start today, because the presses have already failed by the time anyone files it, but never earlier: a `start_date` before the clock date answers `ERR_HOLD_START_IN_PAST` (HTTP 422)."
    PRD: "A `DELIVERY_INTERRUPTION` whose `start_date` is the clock date does not wait: the hold is created directly in `status` `ACTIVE` and the print dimension moves `SCHEDULED → INTERRUPTED` in the same request."

    Design: Corner/validations/delivery_interruption_starting_in_past_rejected
    """
    subscription, _ = _paid_print_subscription("Print Past", "past@mail.test")

    response = api_client.create_hold(
        subscription["id"],
        f.create_hold_payload("DELIVERY_INTERRUPTION", "2026-08-31", "2026-09-06"),
        OPS_AGENT_HEADERS,
    )

    error = validate_error(response, "ERR_HOLD_START_IN_PAST", 422)
    assert error["error_id"] != "ERR_HOLD_START_NOT_FUTURE"
    assert list_holds(subscription["id"]) == []
    assert read_subscription(subscription["id"])["print_fulfillment_status"] == "SCHEDULED"


def test_an_inverted_interval_is_caught_after_the_future_dating_check_passes():
    """A 2026-09-20 start is genuinely future-dated, so only the interval can fail.

    PRD: "Regardless of type, `end_date` must be on or after `start_date` and the closed interval must span no more than ninety days, otherwise `ERR_HOLD_INTERVAL_INVALID` (HTTP 422)."

    Design: Corner/validations/hold_end_before_start_rejected
    """
    subscription, reader_headers = _paid_print_subscription(
        "Print Inverted", "inverted@mail.test"
    )

    response = api_client.create_hold(
        subscription["id"],
        f.create_hold_payload("VACATION_DELIVERY", "2026-09-20", "2026-09-10"),
        reader_headers,
    )

    validate_error(response, "ERR_HOLD_INTERVAL_INVALID", 422)
    assert list_holds(subscription["id"]) == []
    assert read_subscription(subscription["id"])["pending_credit_cents"] == 0


def test_one_thirty_day_vacation_already_breaks_the_four_week_annual_quota():
    """The quota counts days, not holds, so a single legal interval can still exceed it.

    PRD: "Vacation days are capped at twenty-eight per rolling year — four weeks: `vacation_days_used_365`, which is the sum of the inclusive day counts of `VACATION_DELIVERY` holds whose `status` is `SCHEDULED`, `ACTIVE` or `COMPLETED` and whose `start_date` falls on or after the clock date less 365 days, plus the requested hold's own inclusive day count, must not exceed 28, otherwise `ERR_VACATION_DAY_CAP_EXCEEDED` (HTTP 422)."
    PRD: "Regardless of type, `end_date` must be on or after `start_date` and the closed interval must span no more than ninety days, otherwise `ERR_HOLD_INTERVAL_INVALID` (HTTP 422)."

    Design: Corner/validations/annual_vacation_day_cap_exceeded_rejected
    """
    subscription, reader_headers = _paid_print_subscription(
        "Print Quota", "quota@mail.test"
    )
    assert read_subscription(subscription["id"])["vacation_days_used_365"] == 0

    response = api_client.create_hold(
        subscription["id"],
        f.create_hold_payload("VACATION_DELIVERY", "2026-09-06", "2026-10-05"),
        reader_headers,
    )

    error = validate_error(response, "ERR_VACATION_DAY_CAP_EXCEEDED", 422)
    assert error["error_id"] != "ERR_HOLD_INTERVAL_INVALID"
    assert list_holds(subscription["id"]) == []
    assert read_subscription(subscription["id"])["vacation_days_used_365"] == 0


def test_a_third_pause_in_the_trailing_year_is_refused_on_count_not_on_geometry():
    """The two standing pauses are far enough apart that only the annual cap can fire.

    PRD: "Pauses are capped by count rather than by length: at most two `PAUSE_BILLING` holds whose `status` is `SCHEDULED`, `ACTIVE` or `COMPLETED` may exist on a subscription with a `start_date` inside the trailing 365 days, and a third answers `ERR_PAUSE_LIMIT_EXCEEDED`."
    PRD: "For a `PAUSE_BILLING` hold, `delivery_days_credited` is 0 and `credit_cents` is 0, because paused days are not billed at all and there is nothing to give back."

    Design: Corner/validations/third_pause_billing_hold_in_year_rejected
    """
    set_clock_date("2026-09-01")
    plan = create_active_plan(name="Digital Pauses")
    reader = create_registered_reader("pauses@mail.test")
    reader_headers = make_reader_headers(reader["id"])
    subscription = open_subscription(reader["id"], plan["id"])
    record_payment(invoice_for_cycle(subscription["id"], 1), "SUCCEEDED", 499)
    first = create_hold(
        subscription["id"], "PAUSE_BILLING", "2026-09-06", "2026-09-12", reader_headers
    )
    second = create_hold(
        subscription["id"], "PAUSE_BILLING", "2026-09-20", "2026-09-26", reader_headers
    )

    response = api_client.create_hold(
        subscription["id"],
        f.create_hold_payload("PAUSE_BILLING", "2026-10-05", "2026-10-11"),
        reader_headers,
    )

    error = validate_error(response, "ERR_PAUSE_LIMIT_EXCEEDED", 409)
    assert error["error_id"] != "ERR_HOLD_BUFFER_VIOLATION"
    assert len(list_holds(subscription["id"])) == 2
    assert read_hold(first["id"])["status"] == "SCHEDULED"
    assert read_hold(first["id"])["credit_cents"] == 0
    assert read_hold(second["id"])["status"] == "SCHEDULED"
    assert read_subscription(subscription["id"])["pending_credit_cents"] == 0
