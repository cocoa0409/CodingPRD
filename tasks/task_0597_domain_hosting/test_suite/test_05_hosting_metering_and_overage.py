"""Hosting subscriptions, metering windows, and the two bandwidth-overage figures."""
from test_helpers import (
    BILLING,
    PLATFORM,
    ApiErrorId,
    billing_period_payload,
    close_period,
    create_account,
    create_mailbox_payload,
    create_plan,
    create_subscription,
    first_billing_period,
    get_billing_period,
    get_subscription,
    ingest_usage,
    invoice_lines,
    make_registrant_headers,
    register_and_activate_domain,
    setup_period_with_usage,
    setup_subscription_without_domain,
    usage_record_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

# Four records inside the first period of a 10240 MB / 200-cents-per-GB plan.
FOUR_RECORDS = [
    (6000, "2026-05-02T00:00:00Z"),
    (6000, "2026-05-03T00:00:00Z"),
    (6000, "2026-05-04T00:00:00Z"),
    (8000, "2026-05-05T00:00:00Z"),
]


# =========================================================================
# PROVISIONAL vs FINAL over the same rows  (Difficulty/dual_variant_calc)
# =========================================================================

def test_provisional_overage_over_charges_relative_to_the_final_tiered_figure(api):
    """PRD §3.6: "Each record's over-portion is converted to gigabytes by dividing by 1024,
    multiplied by the plan's flat `overage_rate_cents_per_gb`, **rounded half up to whole
    cents at that point**, and only then added to the running provisional total."
    PRD §3.6: "The three tier charges are added together and the sum is **rounded half up to
    whole cents exactly once**, at the very end. This — not the provisional figure — is what
    the customer is billed."

    The same four records (6000, 6000, 6000, 8000 MB against a 10240 MB quota) yield 3079
    cents provisionally and 2809 cents finally.

    Design: Difficulty/dual_variant_calc/hosting_overage_provisional_vs_final_same_usage_rows
    """
    _account, _plan, subscription, period = setup_period_with_usage(FOUR_RECORDS)

    before_close = get_billing_period(subscription["id"], period["id"])
    assert before_close["provisional_overage_cents"] == 3079
    assert before_close["final_overage_cents"] is None, "null while the period stays OPEN"

    closed = close_period(period["id"])

    assert closed["provisional_overage_cents"] == 3079
    assert closed["final_overage_cents"] == 2809
    assert closed["provisional_overage_cents"] != closed["final_overage_cents"], (
        "the provisional estimate is deliberately the pessimistic one"
    )


def test_period_close_bills_the_final_figure_and_resets_the_bandwidth_counter(api):
    """PRD §3.6: "When that figure is greater than zero, an `ISSUED` invoice is raised with
    its `billing_period_id` pointing at the closed period and a single `BANDWIDTH_OVERAGE`
    line for the amount."
    PRD §3.6: "The close then resets the subscription's `bandwidth_used_mb` to zero,
    restarting the quota baseline, and if the subscription was sitting in `OVER_QUOTA` it
    returns to `ACTIVE` — the `ACTIVE → OVER_QUOTA → ACTIVE` cycle repeats once per billing
    period."

    Design: Difficulty/dual_variant_calc/hosting_overage_provisional_vs_final_same_usage_rows
    """
    account, _plan, subscription, period = setup_period_with_usage(FOUR_RECORDS)
    headers = make_registrant_headers(account["id"])

    over_quota = get_subscription(subscription["id"], account)
    assert over_quota["status"] == "OVER_QUOTA"

    close_period(period["id"])

    invoices, meta = validate_paginated(
        api.list_invoices(
            headers, {"account_id": account["id"], "billing_period_id": period["id"]}
        )
    )
    assert meta["total_count"] == 1
    overage_invoice = invoices[0]
    assert overage_invoice["subtotal_cents"] == 2809, "the FINAL figure is what is billed"
    assert overage_invoice["tax_cents"] == 232
    assert overage_invoice["total_cents"] == 3041

    lines = invoice_lines(overage_invoice["id"], account)
    assert len(lines) == 1
    assert lines[0]["item_type"] == "BANDWIDTH_OVERAGE"

    after = get_subscription(subscription["id"], account)
    assert after["status"] == "ACTIVE"
    assert after["bandwidth_used_mb"] == 0


# =========================================================================
# Half-open metering intervals  (Difficulty/resource_temporal_overlap)
# =========================================================================

def test_billing_period_overlapping_by_one_day_is_rejected(api):
    """PRD §3.6: "A period is a half-open interval — its start is inclusive, its end
    exclusive — and two periods of the same subscription may abut exactly, with a new
    `period_start` equal to an existing `period_end`, but may not overlap by so much as an
    instant. A conflict exists when some existing period of that subscription has a
    `period_start` strictly before the new `period_end` *and* the new `period_start` is
    strictly before that period's `period_end`, and it is refused with
    `ERR_BILLING_PERIOD_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/billing_period_half_open_interval_on_a_subscription
    """
    _account, _plan, subscription = setup_subscription_without_domain()
    period = first_billing_period(subscription["id"])

    assert period["period_start"][:10] == "2026-05-01"
    assert period["period_end"][:10] == "2026-05-31", "period_end is thirty days later"

    resp = api.create_billing_period(
        subscription["id"],
        billing_period_payload("2026-05-30T00:00:00Z", "2026-06-29T00:00:00Z"),
        BILLING,
    )
    validate_error(resp, ApiErrorId.ERR_BILLING_PERIOD_OVERLAP.value, 409)

    _, meta = validate_paginated(api.list_billing_periods(subscription["id"], BILLING))
    assert meta["total_count"] == 1, "the rejected period was not created"


def test_billing_period_abutting_exactly_on_the_incumbent_end_is_accepted(api):
    """PRD §3.6: "A period is a half-open interval — its start is inclusive, its end
    exclusive — and two periods of the same subscription may abut exactly, with a new
    `period_start` equal to an existing `period_end`, but may not overlap by so much as an
    instant."
    PRD §3.6: "Both `OPEN` and `CLOSED` periods occupy the timeline for this purpose."

    Design: Difficulty/resource_temporal_overlap/billing_period_half_open_interval_on_a_subscription
    """
    _account, _plan, subscription = setup_subscription_without_domain()

    resp = api.create_billing_period(
        subscription["id"],
        billing_period_payload("2026-05-31T00:00:00Z", "2026-06-30T00:00:00Z"),
        BILLING,
    )
    created = validate_success(resp, 201)
    assert created["status"] == "OPEN"
    assert created["period_start"][:10] == "2026-05-31"

    _, meta = validate_paginated(api.list_billing_periods(subscription["id"], BILLING))
    assert meta["total_count"] == 2, "abutting periods coexist under half-open semantics"


# =========================================================================
# Corner instances
# =========================================================================

def test_usage_exactly_on_the_bandwidth_quota_keeps_the_subscription_active(api):
    """PRD §3.6: "If, after the ingest, `bandwidth_used_mb` is *strictly greater* than the
    plan's `bandwidth_quota_mb`, the subscription moves `ACTIVE → OVER_QUOTA`; usage landing
    exactly on the quota leaves it `ACTIVE`."

    Design: Corner/calculations/bandwidth_exactly_at_quota_does_not_trip_over_quota
    """
    account, _plan, subscription = setup_subscription_without_domain()
    period = first_billing_period(subscription["id"])

    ingest_usage(subscription["id"], 10240, "2026-05-02T00:00:00Z")

    at_quota = get_subscription(subscription["id"], account)
    assert at_quota["bandwidth_used_mb"] == 10240
    assert at_quota["status"] == "ACTIVE", "equal to the quota is not over the quota"
    assert get_billing_period(subscription["id"], period["id"])[
        "provisional_overage_cents"
    ] == 0

    ingest_usage(subscription["id"], 1, "2026-05-03T00:00:00Z")

    over = get_subscription(subscription["id"], account)
    assert over["bandwidth_used_mb"] == 10241
    assert over["status"] == "OVER_QUOTA"
    assert get_billing_period(subscription["id"], period["id"])[
        "provisional_overage_cents"
    ] == 0, "round_half_up(1 / 1024 * 200) == 0"


def test_closing_an_already_closed_period_is_rejected(api):
    """PRD §3.6: "A `BillingAdmin` closes an `OPEN` period; closing one that is already
    `CLOSED` yields `ERR_PERIOD_ALREADY_CLOSED`."
    PRD §3.6: "When that figure is greater than zero, an `ISSUED` invoice is raised with its
    `billing_period_id` pointing at the closed period and a single `BANDWIDTH_OVERAGE` line
    for the amount."

    Design: Corner/state_machines/closing_an_already_closed_billing_period_rejected
    """
    account, _plan, subscription = setup_subscription_without_domain()
    period = first_billing_period(subscription["id"])

    first_close = close_period(period["id"])
    assert first_close["status"] == "CLOSED"
    assert first_close["final_overage_cents"] == 0, "no usage means no overage"

    resp = api.close_billing_period(period["id"], BILLING)
    validate_error(resp, ApiErrorId.ERR_PERIOD_ALREADY_CLOSED.value, 409)

    still = get_billing_period(subscription["id"], period["id"])
    assert still["status"] == "CLOSED"
    assert still["final_overage_cents"] == 0

    _, meta = validate_paginated(
        api.list_invoices(
            BILLING, {"account_id": account["id"], "billing_period_id": period["id"]}
        )
    )
    assert meta["total_count"] == 0, "a zero overage raises no invoice, and no second one"


def test_usage_recorded_outside_every_open_period_is_rejected(api):
    """PRD §3.6: "Usage may be back-dated — late-arriving telemetry is normal — but
    `recorded_at` must fall inside an `OPEN` billing period of that subscription, or the
    record is refused with `ERR_USAGE_OUTSIDE_PERIOD`."

    Design: Corner/validations/usage_recorded_outside_any_open_period_rejected
    """
    account, _plan, subscription = setup_subscription_without_domain()

    resp = api.create_usage_record(
        subscription["id"],
        usage_record_payload(500, "2026-06-15T00:00:00Z"),
        PLATFORM,
    )
    validate_error(resp, ApiErrorId.ERR_USAGE_OUTSIDE_PERIOD.value, 422)

    after = get_subscription(subscription["id"], account)
    assert after["bandwidth_used_mb"] == 0
    assert after["status"] == "ACTIVE"

    _, meta = validate_paginated(api.list_usage_records(subscription["id"], PLATFORM))
    assert meta["total_count"] == 0


def test_add_on_against_a_still_provisioning_subscription_is_rejected(api):
    """PRD §3.5: "The subscription must be in `ACTIVE` or `OVER_QUOTA` — anything else is
    `ERR_SUBSCRIPTION_NOT_ACTIVE` — and the domain must be `ACTIVE`, or the request draws
    `ERR_INVALID_DOMAIN_STATE`."
    PRD §3.6: "The subscription is created in `PROVISIONING` with an `auto_renew` flag that
    defaults to true and is purely informational in this system (the plan is billed once at
    creation), alongside an `ISSUED` invoice carrying a `HOSTING_PLAN` line priced at the
    plan's `monthly_price_cents`."

    Design: Corner/validations/add_on_on_a_provisioning_subscription_rejected
    """
    plan = create_plan()
    account = create_account()
    headers = make_registrant_headers(account["id"])
    domain = register_and_activate_domain(account, "example", "com")
    subscription = create_subscription(account, plan, primary_domain_id=domain["id"])

    assert subscription["status"] == "PROVISIONING", "its HOSTING_PLAN invoice is unpaid"

    resp = api.create_add_on(
        create_mailbox_payload(subscription["id"], domain["id"], "info", 1024), headers
    )
    validate_error(resp, ApiErrorId.ERR_SUBSCRIPTION_NOT_ACTIVE.value, 409)

    after = validate_success(api.get_hosting_subscription(subscription["id"], headers))
    assert after["storage_committed_mb"] == 0
