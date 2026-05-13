"""RecurringOrder lifecycle (PRD §3.4)."""

import pytest

from test_helpers import (
    OPERATOR_HEADERS,
    assert_recurring_order,
    create_customer,
    create_recurring_order_payload,
    create_service_item,
    iso_in,
    make_customer_headers,
    validate_error,
    validate_success,
)


def test_create_recurring_order_starts_active(api):
    """PRD §3.4: "A RecurringOrder is a parent template ... It carries
    cadence_days, a first_start_at timestamp for the first occurrence, the
    per-occurrence duration_hours, an occurrences_generated counter ... and
    a status of ACTIVE, PAUSED, or TERMINATED."

    Claim: a freshly created RecurringOrder has status=ACTIVE.
    """
    customer = create_customer()
    item = create_service_item()
    res = api.create_recurring_order(
        create_recurring_order_payload(
            customer_id=customer["id"], service_item_id=item["id"]
        ),
        make_customer_headers(customer["id"]),
    )
    body = validate_success(res, expected_status=201)
    assert_recurring_order(body)
    assert body["status"] == "ACTIVE"


def test_pause_resume_recurring_order_round_trip(api):
    """PRD §3.4: "A recurring order can be paused and resumed during its life."

    Claim: pause moves ACTIVE → PAUSED; resume moves PAUSED → ACTIVE.
    """
    customer = create_customer()
    item = create_service_item()
    created = api.create_recurring_order(
        create_recurring_order_payload(
            customer_id=customer["id"], service_item_id=item["id"]
        ),
        make_customer_headers(customer["id"]),
    ).json()["data"]

    paused = validate_success(
        api.pause_recurring_order(
            created["id"], make_customer_headers(customer["id"])
        )
    )
    assert paused["status"] == "PAUSED"

    resumed = validate_success(
        api.resume_recurring_order(
            created["id"], make_customer_headers(customer["id"])
        )
    )
    assert resumed["status"] == "ACTIVE"


def test_terminate_recurring_order_is_terminal(api):
    """PRD §3.4: "termination is final."

    Claim: terminate moves status to TERMINATED, and a subsequent pause
    returns ERR_INVALID_STATE.
    """
    customer = create_customer()
    item = create_service_item()
    created = api.create_recurring_order(
        create_recurring_order_payload(
            customer_id=customer["id"], service_item_id=item["id"]
        ),
        make_customer_headers(customer["id"]),
    ).json()["data"]
    terminated = validate_success(
        api.terminate_recurring_order(
            created["id"], make_customer_headers(customer["id"])
        )
    )
    assert terminated["status"] == "TERMINATED"
    res = api.pause_recurring_order(
        created["id"], make_customer_headers(customer["id"])
    )
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


@pytest.mark.parametrize("cadence", [1, 7, 14, 30])
def test_recurring_order_cadence_allowed_values(api, cadence):
    """PRD §3.4: "A RecurringOrder is a parent template for repeated bookings
    under the same customer and service item with a cadence of 1, 7, 14, or
    30 days."

    Claim: each of {1, 7, 14, 30} cadence_days is accepted.
    """
    customer = create_customer()
    item = create_service_item()
    res = api.create_recurring_order(
        create_recurring_order_payload(
            customer_id=customer["id"],
            service_item_id=item["id"],
            cadence_days=cadence,
        ),
        make_customer_headers(customer["id"]),
    )
    body = validate_success(res, expected_status=201)
    assert body["cadence_days"] == cadence
