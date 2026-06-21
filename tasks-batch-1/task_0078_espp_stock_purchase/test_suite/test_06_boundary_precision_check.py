"""Difficulty rule 6 — boundary-precision checks (PRD §3.2, §3.8).

Holding-period anniversary inclusivity on dispositions, and the offering
duration_months lower bound.
"""
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    create_disposition_payload,
    create_offering_payload,
    create_plan_payload,
    setup_settled_purchase,
    make_participant_headers,
)


def _lot_2022(api):
    """Purchased lot: grant 2022-01-01, purchase 2022-06-30 (so grant+2y = 2024-01-01,
    purchase+1y = 2023-06-30)."""
    return setup_settled_purchase(
        plan_overrides={"discount_pct": 15, "lookback_enabled": True},
        offering_overrides={
            "grant_date": "2022-01-01T00:00:00.000Z", "grant_date_fmv_cents": 1000,
        },
        batch_overrides={
            "purchase_date": "2022-06-30T00:00:00.000Z", "purchase_date_fmv_cents": 1200,
        },
        rate_pct=15,
    )


def test_sale_on_exact_anniversary_is_qualifying(api):
    """PRD §3.8: "The disposition is QUALIFYING when the sale_date is on or after the
    second anniversary of the lot's grant_date and also on or after the first
    anniversary of the lot's purchase_date ... The anniversary boundary is inclusive:
    selling exactly on the two-year-and-one-year anniversaries qualifies, while
    selling one day earlier than either does not."

    Sale 2024-06-30 is >= grant+2y (2024-01-01) and >= purchase+1y (2023-06-30)
    => QUALIFYING.

    Design: Difficulty/boundary_precision_check/qualifying_holding_period_exact_anniversary_inclusive
    """
    ctx = _lot_2022(api)
    ph = make_participant_headers(ctx["participant"]["id"])
    disp = get_success_data(
        api.create_disposition(
            create_disposition_payload(
                ctx["share_lot"]["id"], ctx["participant"]["id"],
                sale_date="2024-06-30T00:00:00.000Z", shares_sold=50,
                sale_price_per_share_cents=1500,
            ),
            ph,
        )
    )
    assert disp["disposition_type"] == "QUALIFYING", disp


def test_sale_one_day_before_purchase_anniversary_is_disqualifying(api):
    """PRD §3.8: "The anniversary boundary is inclusive: selling exactly on the
    two-year-and-one-year anniversaries qualifies, while selling one day earlier than
    either does not."

    Sale 2023-06-29 is one day before purchase+1y (2023-06-30) => DISQUALIFYING even
    though grant+2y is also unmet; either unmet anniversary disqualifies.

    Design: Difficulty/boundary_precision_check/qualifying_holding_period_exact_anniversary_inclusive
    """
    ctx = _lot_2022(api)
    ph = make_participant_headers(ctx["participant"]["id"])
    disp = get_success_data(
        api.create_disposition(
            create_disposition_payload(
                ctx["share_lot"]["id"], ctx["participant"]["id"],
                sale_date="2023-06-29T00:00:00.000Z", shares_sold=50,
                sale_price_per_share_cents=1500,
            ),
            ph,
        )
    )
    assert disp["disposition_type"] == "DISQUALIFYING", disp


def test_offering_duration_six_months_accepted(api, admin_headers):
    """PRD §3.2: "The duration_months must be at least 6 and at most 24; a value
    outside that inclusive range is rejected with ERR_OFFERING_DURATION (HTTP 422)."

    duration_months = 6 is the inclusive lower bound => accepted (201).

    Design: Difficulty/boundary_precision_check/offering_duration_lower_bound_six_months_inclusive
    """
    plan = get_success_data(api.create_plan(create_plan_payload(), admin_headers))
    resp = api.create_offering_period(
        create_offering_payload(plan["id"], duration_months=6), admin_headers
    )
    off = validate_success(resp, expected_status=201)
    assert off["duration_months"] == 6, off
    assert off["status"] == "OPEN", off


def test_offering_duration_five_months_rejected(api, admin_headers):
    """PRD §3.2: "The duration_months must be at least 6 and at most 24; a value
    outside that inclusive range is rejected with ERR_OFFERING_DURATION (HTTP 422)."

    duration_months = 5 is one below the lower bound => ERR_OFFERING_DURATION.

    Design: Difficulty/boundary_precision_check/offering_duration_lower_bound_six_months_inclusive
    """
    plan = get_success_data(api.create_plan(create_plan_payload(), admin_headers))
    resp = api.create_offering_period(
        create_offering_payload(plan["id"], duration_months=5), admin_headers
    )
    validate_error(resp, "ERR_OFFERING_DURATION")
