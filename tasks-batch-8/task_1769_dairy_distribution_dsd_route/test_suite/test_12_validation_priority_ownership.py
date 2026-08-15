"""Validation priority ordering, entity-backed ownership checks, and state-gate
sweeps across store, pricing period, and return (PRD §2.1, §2.5, §3)."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    approve_return,
    create_distributor,
    create_driver,
    create_order,
    create_pricing_period,
    create_return,
    get_pricing_period,
    make_distributor_owner_headers,
    make_driver_headers,
    make_store_receiver_headers,
    order_line,
    publish_announcement,
    setup_delivered_order,
    setup_planned_order,
    validate_error,
    validate_paginated,
    validate_success,
)

TM = TEST_USERS["territory_manager_headers"]
MA = TEST_USERS["market_admin_headers"]


def test_input_format_trumps_state_on_return_create(api):
    """PRD §2.5: "the API applies a single global priority ladder, and a
    dual-failure request returns the error from the lowest priority number"
    with "(5) request well-formedness — required fields present, enums
    in-domain, numeric ranges valid, uniqueness respected — producing
    `ERR_INVALID_REQUEST`" ahead of the state family at rung (6).

    Design: Corner/validations/input_format_trumps_state_on_return_create
    """
    refs = setup_planned_order(prefix="CA", quantity_units=4)
    err1 = api.create_return(
        {
            "order_id": refs["order"]["id"],
            "store_id": refs["store"]["id"],
            "pickup_trip_id": refs["trip"]["id"],
            "product_id": refs["product"]["id"],
            "quantity_units": 1,
            "reason_code": "BOGUS",
            "scanned_code_date": "2026-09-01",
        },
        make_driver_headers(refs["driver"]["id"]),
    )
    validate_error(err1, ApiErrorId.ERR_INVALID_REQUEST)


def test_ownership_mismatch_driver_and_receiver(api):
    """PRD §2.1: "When `X-User-Role` is `RouteDriver`, `X-User-ID` is the `id`
    of the acting `Driver`; for departure, completion, temperature readings,
    delivery, return creation, crate pickup, and merchandising, the trip's
    `driver_id` must equal `X-User-ID`. When `X-User-Role` is `StoreReceiver`,
    `X-User-ID` is the `id` of the acting `Store`; for payments and disputes,
    the resource's `store_id` must equal `X-User-ID`. A failed entity-backed
    ownership check is rejected with `ERR_OWNERSHIP_MISMATCH` (HTTP 403)."

    Design: Corner/validations/ownership_mismatch_driver_and_receiver
    """
    refs = setup_delivered_order(prefix="CC", quantity_units=4)
    d_id = refs["distributor"]["id"]
    d2 = create_distributor(name="Dairy Dist CD", license_number="LIC-CD-1")
    dr2 = create_driver(d_id, name="Driver Two")

    err1 = api.deliver_order(
        refs["order"]["id"],
        {"delivered_lines": [
            {"product_id": refs["product"]["id"], "delivered_units": 4,
             "scanned_code_date": "2026-09-01"}
        ]},
        make_driver_headers(dr2["id"]),
    )
    validate_error(err1, ApiErrorId.ERR_OWNERSHIP_MISMATCH)

    err2 = api.pay_invoice(
        refs["invoice"]["id"], {"amount_cents": 100},
        make_store_receiver_headers(d2["id"]),
    )
    validate_error(err2, ApiErrorId.ERR_OWNERSHIP_MISMATCH)


def test_wrong_state_sweep_store_period_return(api):
    """PRD §3.1: "Deactivating a store moves it `ACTIVE` → `INACTIVE` and is
    refused from any other state with `ERR_STORE_NOT_ACTIVE`"
    PRD §3.3: "Closing a period requires it to be `OPEN` and to have an
    `ACTIVE` `FINAL` announcement — both failures surface as
    `ERR_PERIOD_CLOSED` — and a closed period accepts no further announcements
    (publishing into one is likewise `ERR_PERIOD_CLOSED`)."
    PRD §3.6: "Approval is defined from `UNDER_REVIEW` or `DISPUTED` (any
    other state, `ERR_RETURN_NOT_REVIEWABLE`)"

    Design: Corner/errors/wrong_state_sweep_store_period_return
    """
    period = create_pricing_period("2026-08")
    publish_announcement(period["id"], kind="FINAL", base=2000, assessment=35,
                         hauling=60, diesel=299)
    closed = validate_success(api.close_pricing_period(period["id"], MA), 200)
    assert closed["status"] == "CLOSED"

    refs = setup_delivered_order(prefix="EB", quantity_units=4)
    d_id = refs["distributor"]["id"]
    s1 = refs["store"]["id"]
    ret = create_return(refs["order"]["id"], s1, refs["trip"]["id"],
                        refs["product"]["id"], 1, "DAMAGED", "2026-09-01",
                        refs["driver"]["id"])
    approve_return(ret["id"], d_id)
    owner = make_distributor_owner_headers(d_id)
    validate_success(api.deactivate_store(s1, owner), 200)

    err1 = api.deactivate_store(s1, owner)
    validate_error(err1, ApiErrorId.ERR_STORE_NOT_ACTIVE)

    err2 = api.close_pricing_period(period["id"], MA)
    validate_error(err2, ApiErrorId.ERR_PERIOD_CLOSED)

    fresh_version = get_pricing_period(period["id"])["version"]
    err3 = api.publish_announcement(
        period["id"],
        {
            "kind": "PROVISIONAL",
            "class_i_base_cents_per_cwt": 2100,
            "processor_assessment_cents_per_cwt": 35,
            "hauling_cents_per_cwt": 60,
            "diesel_index_cents": 299,
            "expected_pricing_period_version": fresh_version,
        },
        MA,
    )
    validate_error(err3, ApiErrorId.ERR_PERIOD_CLOSED)

    err4 = api.approve_return(ret["id"], owner)
    validate_error(err4, ApiErrorId.ERR_RETURN_NOT_REVIEWABLE)
