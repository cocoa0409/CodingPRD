"""Difficulty rule 8 — resource temporal-interval conflicts (PRD §3.2, §3.8).

Two-sided containment of a purchase_date within the offering window, and the
one-sided lower-bound floor of a disposition sale_date at the lot's purchase_date.
"""
from test_helpers import (
    validate_error,
    get_success_data,
    create_purchase_period_payload,
    create_disposition_payload,
    create_offering_payload,
    create_plan_payload,
    setup_settled_purchase,
    make_participant_headers,
)


def test_purchase_date_after_offering_end_rejected(api, admin_headers):
    """PRD §3.2: "A batch's purchase_date must fall on or after the offering's
    grant_date and on or before its end_date; a date outside that inclusive window is
    rejected with ERR_PURCHASE_DATE_OUT_OF_RANGE (HTTP 422)."

    12-month offering grant 2024-01-01 => end_date 2025-01-01. purchase_date
    2025-06-30 is past end_date => rejected.

    Design: Difficulty/resource_temporal_overlap/purchase_date_must_fall_within_offering_window_closed_interval
    """
    plan = get_success_data(api.create_plan(create_plan_payload(), admin_headers))
    offering = get_success_data(
        api.create_offering_period(
            create_offering_payload(
                plan["id"], grant_date="2024-01-01T00:00:00.000Z", duration_months=12,
            ),
            admin_headers,
        )
    )
    resp = api.create_purchase_period(
        offering["id"],
        create_purchase_period_payload(purchase_date="2025-06-30T00:00:00.000Z"),
        admin_headers,
    )
    validate_error(resp, "ERR_PURCHASE_DATE_OUT_OF_RANGE")


def test_purchase_date_after_offering_end_status_422(api, admin_headers):
    """PRD §3.2: "A batch's purchase_date must fall on or after the offering's
    grant_date and on or before its end_date; a date outside that inclusive window is
    rejected with ERR_PURCHASE_DATE_OUT_OF_RANGE (HTTP 422)."

    Second test of the instance: confirm HTTP 422 accompanies the error id.

    Design: Difficulty/resource_temporal_overlap/purchase_date_must_fall_within_offering_window_closed_interval
    """
    plan = get_success_data(api.create_plan(create_plan_payload(), admin_headers))
    offering = get_success_data(
        api.create_offering_period(
            create_offering_payload(
                plan["id"], grant_date="2024-01-01T00:00:00.000Z", duration_months=12,
            ),
            admin_headers,
        )
    )
    resp = api.create_purchase_period(
        offering["id"],
        create_purchase_period_payload(purchase_date="2025-06-30T00:00:00.000Z"),
        admin_headers,
    )
    validate_error(resp, "ERR_PURCHASE_DATE_OUT_OF_RANGE", expected_status=422)


def _settled_lot_purchase_2024_06_30(api):
    return setup_settled_purchase(
        plan_overrides={"discount_pct": 15, "lookback_enabled": True},
        offering_overrides={
            "grant_date": "2024-01-01T00:00:00.000Z", "grant_date_fmv_cents": 1000,
        },
        batch_overrides={
            "purchase_date": "2024-06-30T00:00:00.000Z", "purchase_date_fmv_cents": 1200,
        },
        rate_pct=15,
    )


def test_sale_before_purchase_date_rejected(api):
    """PRD §3.8: "The sale_date must be on or after the lot's purchase_date, or it is
    rejected with ERR_SALE_BEFORE_PURCHASE (HTTP 422)."

    Lot purchase_date 2024-06-30; sale 2024-06-29 is strictly before => rejected.

    Design: Difficulty/resource_temporal_overlap/disposition_sale_date_not_before_purchase_date_half_open_floor
    """
    ctx = _settled_lot_purchase_2024_06_30(api)
    ph = make_participant_headers(ctx["participant"]["id"])
    resp = api.create_disposition(
        create_disposition_payload(
            ctx["share_lot"]["id"], ctx["participant"]["id"],
            sale_date="2024-06-29T00:00:00.000Z", shares_sold=10,
            sale_price_per_share_cents=1500,
        ),
        ph,
    )
    validate_error(resp, "ERR_SALE_BEFORE_PURCHASE")


def test_sale_before_purchase_date_status_422(api):
    """PRD §3.8: "The sale_date must be on or after the lot's purchase_date, or it is
    rejected with ERR_SALE_BEFORE_PURCHASE (HTTP 422)."

    Second test of the instance: confirm HTTP 422 accompanies the error id.

    Design: Difficulty/resource_temporal_overlap/disposition_sale_date_not_before_purchase_date_half_open_floor
    """
    ctx = _settled_lot_purchase_2024_06_30(api)
    ph = make_participant_headers(ctx["participant"]["id"])
    resp = api.create_disposition(
        create_disposition_payload(
            ctx["share_lot"]["id"], ctx["participant"]["id"],
            sale_date="2024-06-29T00:00:00.000Z", shares_sold=10,
            sale_price_per_share_cents=1500,
        ),
        ph,
    )
    validate_error(resp, "ERR_SALE_BEFORE_PURCHASE", expected_status=422)
