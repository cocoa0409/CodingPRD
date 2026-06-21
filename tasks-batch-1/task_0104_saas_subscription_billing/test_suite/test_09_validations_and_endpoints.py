"""Business-rule violations and endpoint surface (pagination, reporting,
adjacency, reverse-reachability listing).

Queue B (corner) translations for the `validations` and `endpoints` sections.
"""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    make_account_owner_headers,
    TEST_USERS,
    create_coupon_payload,
    create_plan_payload,
    create_subscription_payload,
    change_plan_payload,
    add_addon_payload,
    record_usage_payload,
    create_price_schedule_payload,
    find_line_by_kind,
    setup_active_subscription,
    setup_converted_subscription,
    setup_plan_with_price_schedule,
    create_addon,
    list_account_invoices,
)

ADMIN = TEST_USERS["billing_admin_headers"]


def _owner(account_id):
    return make_account_owner_headers(account_id)


# ─── validations ──────────────────────────────────────
def test_change_plan_to_same_plan_returns_no_plan_change(api):
    """PRD §3.5: "The target plan must differ from the subscription's current `plan_id` — a no-op change is rejected with `ERR_NO_PLAN_CHANGE`".

    Design: Corner/validations/change_plan_same_plan_returns_no_plan_change
    """
    plan, account, sub = setup_active_subscription(plan_tier="BASIC", email="npc@x.com")
    sub_now = validate_success(api.get_subscription(sub["id"], _owner(account["id"])), 200)
    res = api.change_plan(
        account["id"],
        sub["id"],
        change_plan_payload(plan["id"], sub_now["version"]),
        _owner(account["id"]),
    )
    validate_error(res, "ERR_NO_PLAN_CHANGE")


def test_add_duplicate_active_addon_returns_already_active(api):
    """PRD §3.9: "The same add-on may not be attached twice while still active: attaching an `addon_id` that is already `ACTIVE` on the subscription is rejected with `ERR_ADDON_ALREADY_ACTIVE`."

    Design: Corner/validations/add_duplicate_active_addon_returns_already_active
    """
    plan, account, sub = setup_active_subscription(plan_tier="BASIC", email="aa@x.com")
    seats = create_addon(code="SEATS", monthly_fee_cents=2000)
    get_success_data(
        api.add_subscription_addon(
            account["id"], sub["id"], add_addon_payload(seats["id"]), _owner(account["id"])
        )
    )
    res = api.add_subscription_addon(
        account["id"], sub["id"], add_addon_payload(seats["id"]), _owner(account["id"])
    )
    validate_error(res, "ERR_ADDON_ALREADY_ACTIVE")


def test_usage_zero_units_returns_invalid_request(api):
    """PRD §3.4: "Either an `AccountOwner` (on their own subscription) or a `BillingAdmin` records a **usage event** by supplying `units`, the number of metered units consumed, which must be greater than 0". PRD §2.7: "the body itself is validated for well-formedness (required fields present, enums within their allowed sets, numbers within range), failing with `ERR_INVALID_REQUEST`."

    Design: Corner/validations/usage_zero_units_returns_invalid_request
    """
    plan, account, sub = setup_converted_subscription(
        plan_fee_cents=9000, plan_tier="PRO", trial_days=14, email="zu@x.com"
    )
    res = api.record_usage(
        account["id"],
        sub["id"],
        record_usage_payload(0, "2026-06-05T00:00:00Z"),
        _owner(account["id"]),
    )
    validate_error(res, "ERR_INVALID_REQUEST")


def test_coupon_percent_off_out_of_range_returns_invalid_request(api):
    """PRD §3.1: "For a `PERCENT` coupon, `percent_off` is a whole-number percentage between 1 and 100 inclusive and is required". PRD §3.1: "or `percent_off` outside 1 to 100 — is rejected with `ERR_INVALID_REQUEST`".

    Design: Corner/validations/coupon_percent_off_out_of_range_returns_invalid_request
    """
    res = api.create_coupon(
        create_coupon_payload(
            code="BAD", discount_type="PERCENT", percent_off=150, duration="ONCE", max_redemptions=1
        ),
        ADMIN,
    )
    validate_error(res, "ERR_INVALID_REQUEST")


# ─── endpoints ────────────────────────────────────────
def test_list_subscriptions_returns_paginated_envelope(api):
    """PRD §2.3: "Every list response carries `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope."

    Design: Corner/endpoints/list_subscriptions_paginated_envelope
    """
    plan, account, sub = setup_active_subscription(plan_tier="BASIC", email="lst@x.com")
    res = api.list_subscriptions(account["id"], _owner(account["id"]), params={"limit": 10, "offset": 0})
    data, meta = validate_paginated(res)
    assert meta["total_count"] == 1, f"total_count, got {meta['total_count']}"
    assert meta["has_more"] is False, f"has_more, got {meta['has_more']}"


def test_pagination_limit_out_of_range_returns_validation_range(api):
    """PRD §2.3: "A `limit` outside the inclusive range of 1 to 100, or a negative `offset`, is rejected with `ERR_VALIDATION_RANGE`."

    Design: Corner/endpoints/pagination_limit_out_of_range_returns_validation_range
    """
    res = api.list_plans(ADMIN, params={"limit": 500})
    validate_error(res, "ERR_VALIDATION_RANGE")


def test_reporting_mrr_totals(api):
    """PRD §3.8: "an MRR report that may take an optional `since` clock anchor. The report returns `total_mrr_cents`, the committed MRR summed across all active accounts; `active_subscription_count`".

    Design: Corner/endpoints/computed_read_reporting_mrr_totals
    """
    plan, account, sub = setup_active_subscription(
        plan_fee_cents=9000, plan_tier="PRO", email="rep@x.com"
    )
    res = api.get_mrr_report(ADMIN)
    report = validate_success(res, 200)
    assert report["total_mrr_cents"] == 9000, f"total_mrr_cents, got {report['total_mrr_cents']}"
    assert report["active_subscription_count"] == 1, (
        f"active_subscription_count, got {report['active_subscription_count']}"
    )


def test_price_schedule_adjacent_window_allowed(api):
    """PRD §3.1: "because the intervals are half-open, two windows that merely touch — where one window's `effective_to` equals the next window's `effective_from` — are permitted, but any overlap of positive measure is rejected with `ERR_PRICE_SCHEDULE_OVERLAP`."

    Design: Corner/endpoints/price_schedule_adjacent_window_allowed
    """
    plan, schedule = setup_plan_with_price_schedule(
        effective_from="2026-01-01T00:00:00Z", effective_to="2026-04-01T00:00:00Z"
    )
    res = api.create_price_schedule(
        plan["id"],
        create_price_schedule_payload(3500, "2026-04-01T00:00:00Z", "2026-07-01T00:00:00Z"),
        ADMIN,
    )
    created = validate_success(res, 201)
    assert created["effective_from"].startswith("2026-04-01"), (
        f"adjacent window should be created, effective_from={created['effective_from']}"
    )


def test_list_invoice_lines_surfaces_subscription_line(api):
    """PRD §3.6: "Each billable fact is an **invoice line** carrying its `invoice_id`, a `kind` from `SUBSCRIPTION`, `ADDON`, `OVERAGE`, `PRORATION_CREDIT`, or `PRORATION_CHARGE`, a human-readable `description`, and a signed `amount_cents`".

    Design: Corner/endpoints/list_invoice_lines_reverse_reachability
    """
    plan, account, sub = setup_active_subscription(
        plan_fee_cents=9000, plan_tier="PRO", email="lns@x.com"
    )
    invoices = list_account_invoices(account["id"])
    assert invoices, "ACTIVE create should produce a first invoice"
    lines = validate_success(api.list_invoice_lines(invoices[0]["id"], _owner(account["id"])))
    sub_line = find_line_by_kind(lines, "SUBSCRIPTION")
    assert sub_line is not None, "expected a SUBSCRIPTION line"
    assert sub_line["amount_cents"] == 9000, (
        f"SUBSCRIPTION line for PRO 9000, got {sub_line['amount_cents']}"
    )
