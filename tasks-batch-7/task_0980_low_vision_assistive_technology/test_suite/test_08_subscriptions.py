"""Subscriptions: closed-interval overlap, loyalty tiers, prorated cancel,
past-due decay and reactivation."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId,
    create_client_payload, create_subscription_payload,
    create_client, create_screen_reader_model, create_subscription,
    setup_active_subscription, set_clock, run_daily,
    TEST_USERS,
)

INTAKE = TEST_USERS["intake_coordinator_headers"]
BILLING = TEST_USERS["billing_specialist_headers"]
ADMIN = TEST_USERS["clinic_admin_headers"]


def _setup_subscription_20260501(api):
    """Nia Tob scenario: client + screen-reader model (monthly 25000) + ACTIVE
    subscription with period_start 2026-05-01."""
    c = get_success_data(api.create_client(create_client_payload(
        full_name="Nia Tob", date_of_birth="1975-10-14"), INTAKE))
    m = get_success_data(api.create_device_model({
        "name": "ReadAloud SR", "category": "SCREEN_READER",
        "list_price_cents": 0, "subscription_monthly_cents": 25000}, ADMIN))
    sub = get_success_data(api.create_subscription(create_subscription_payload(
        c["id"], m["id"], period_start="2026-05-01T00:00:00Z"), BILLING))
    return c, m, sub


def test_subscription_period_end_is_start_plus_30_days(api):
    """PRD §3.8: "At creation `period_end` is computed as `period_start` plus 30
    days".

    Design: Difficulty/resource_temporal_overlap/rto_subscription_closed_interval
    """
    c, m, sub = _setup_subscription_20260501(api)
    assert sub["period_end"] == "2026-05-31T00:00:00Z"
    assert sub["status"] == "ACTIVE"


def test_subscription_closed_interval_boundary_conflicts_and_frees(api):
    """PRD §3.8: "if the same client already has an `ACTIVE` or `PAST_DUE`
    subscription on the same model whose period overlaps the new one under a
    **closed**-interval reading — the new `period_start` falling on or before the
    existing `period_end` conflicts — creation is rejected with
    `ERR_SUBSCRIPTION_OVERLAP` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/rto_subscription_closed_interval
    """
    c, m, sub = _setup_subscription_20260501(api)
    resp = api.create_subscription(create_subscription_payload(
        c["id"], m["id"], period_start="2026-05-31T00:00:00Z"), BILLING)
    validate_error(resp, ApiErrorId.ERR_SUBSCRIPTION_OVERLAP)
    free = get_success_data(api.create_subscription(create_subscription_payload(
        c["id"], m["id"], period_start="2026-06-01T00:00:00Z"), BILLING))
    assert free["status"] == "ACTIVE", "one day later is free"
    assert free["period_end"] == "2026-07-01T00:00:00Z"


def test_loyalty_tier_boundary_at_50000(api):
    """PRD §3.8: "The tier is read from the subscription's `total_paid_cents`
    **prior to the charge being computed**: at least 100000 cents paid earns a
    10-percent discount; at least 50000 cents — and note the boundary is
    inclusive, so exactly 50000 earns it — earns a 5-percent discount; anything
    below earns none."

    Design: Corner/calculations/calc_subscription_loyalty_tier_boundary
    """
    c, m, sub = _setup_subscription_20260501(api)
    assert sub["last_fee_cents"] == 25000, "tier 0 at creation (prior total 0)"
    r1 = get_success_data(api.renew_subscription(sub["id"], BILLING))
    assert r1["last_fee_cents"] == 25000, "tier 0 (prior 25000 < 50000)"
    r2 = get_success_data(api.renew_subscription(sub["id"], BILLING))
    assert r2["last_fee_cents"] == 23750, (
        f"prior 50000 >= 50000: round_half_up(25000*0.95) = 23750, got {r2['last_fee_cents']}")
    assert r2["total_paid_cents"] == 73750
    assert r2["period_end"] == "2026-07-30T00:00:00Z"


def test_cancel_active_prorates_credit(api):
    """PRD §3.8: "From `ACTIVE`, `credit_cents` is computed from the days
    remaining in the period: the whole days from now to `period_end`, clamped to
    the range 0 to 30, divided by 30 and multiplied by the model's
    `subscription_monthly_cents`, rounded half-up to a whole cent."

    Design: Corner/calculations/calc_subscription_cancel_credit_proration
    """
    c, m, sub = _setup_subscription_20260501(api)
    set_clock("2026-05-16T00:00:00Z")
    cancelled = get_success_data(api.cancel_subscription(sub["id"], BILLING))
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["credit_cents"] == 12500, (
        f"15 days remaining of 30: round_half_up(25000*15/30) = 12500, got {cancelled['credit_cents']}")


def test_subscription_past_due_then_suspended_after_grace(api):
    """PRD §2.6: "A subscription in `ACTIVE` whose `period_end` is strictly
    before the current clock transitions `ACTIVE → PAST_DUE`, stamping
    `past_due_since` with the value of `period_end`."
    PRD §2.6: "A subscription in `PAST_DUE` transitions `PAST_DUE → SUSPENDED`
    once the current clock is strictly more than 14 days after its
    `past_due_since`."
    PRD §2.6: "All five boundaries are strict: exact equality of the clock with
    the threshold does **not** trigger the transition."

    Design: Corner/state_machines/sm_subscription_past_due_then_suspended
    """
    c, m, sub = _setup_subscription_20260501(api)
    set_clock("2026-06-01T00:00:00Z")
    run_daily()
    mid = get_success_data(api.get_subscription(sub["id"], BILLING))
    assert mid["status"] == "PAST_DUE"
    assert mid["past_due_since"] == "2026-05-31T00:00:00Z"
    set_clock("2026-06-14T00:00:00Z")
    run_daily()
    still = get_success_data(api.get_subscription(sub["id"], BILLING))
    assert still["status"] == "PAST_DUE", (
        "2026-06-14 is not strictly greater than past_due_since + 14 days")
    set_clock("2026-06-15T00:00:00Z")
    run_daily()
    end = get_success_data(api.get_subscription(sub["id"], BILLING))
    assert end["status"] == "SUSPENDED", "grace elapsed"


def test_renew_from_past_due_reactivates(api):
    """PRD §3.8: "From `PAST_DUE` it does the same fee computation but resets
    `period_end` to now plus 30 days and clears `past_due_since` to null,
    reactivating the subscription to `ACTIVE`."

    Design: Corner/state_machines/sm_subscription_renew_from_past_due
    """
    c, m, sub = _setup_subscription_20260501(api)
    set_clock("2026-06-10T00:00:00Z")
    run_daily()
    renewed = get_success_data(api.renew_subscription(sub["id"], BILLING))
    assert renewed["status"] == "ACTIVE"
    assert renewed["past_due_since"] is None
    assert renewed["period_end"] == "2026-07-10T00:00:00Z", "now + 30 days"
    assert renewed["last_fee_cents"] == 25000, "total_paid prior is 25000 < 50000: tier 0"
