"""Scent-of-month subscriptions: dual actual/projected charge, the cyclic
pause/resume lifecycle, shipment generation gating and period overlap, and
tiering through shipment fulfillment."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    make_customer, make_subscription, make_shipment, fulfill_shipment,
    TEST_USERS,
)
from test_helpers.test_users import make_customer_headers

FULFILL = TEST_USERS["fulfillment_headers"]


# ─── Difficulty/dual_variant_calc/subscription_actual_vs_projected_charge ───
def test_shipment_actual_charge_uses_fee_at_period_start(api):
    """PRD §3.6: "A shipment's actual charge, by contrast, is the same rule
    evaluated at the shipment's own `period_start`."

    Design: Difficulty/dual_variant_calc/subscription_actual_vs_projected_charge
    """
    cust = make_customer()
    sub = make_subscription(cust["id"], tier="BASIC", monthly_fee_cents=5000,
                            pending_fee_cents=6000, fee_effective_date="2026-08-01T00:00:00Z")
    ship = validate_success(
        api.create_shipment(sub["id"], {"period_start": "2026-07-01T00:00:00Z",
                                        "period_end": "2026-08-01T00:00:00Z"}, FULFILL), 201)
    assert ship["charge_cents"] == 5000


def test_projected_next_charge_uses_fee_at_period_end(api):
    """PRD §3.6: "The projected charge is that rule evaluated at the
    subscription's `current_period_end` — the next boundary."

    Design: Difficulty/dual_variant_calc/subscription_actual_vs_projected_charge
    """
    cust = make_customer()
    sub = make_subscription(cust["id"], tier="BASIC", monthly_fee_cents=5000,
                            pending_fee_cents=6000, fee_effective_date="2026-08-01T00:00:00Z")
    fetched = validate_success(api.get_subscription(sub["id"], make_customer_headers(cust["id"])), 200)
    assert fetched["projected_next_charge_cents"] == 6000


# ─── Difficulty/non_linear_state_machine/subscription_cyclic_pause_resume ───
def test_pause_resume_pause_cycle_returns_to_paused(api):
    """PRD §3.6: "Pausing an `ACTIVE` subscription moves it to `PAUSED` and
    increments its `version`; resuming a `PAUSED` subscription moves it back to
    `ACTIVE` and again increments `version`."

    Design: Difficulty/non_linear_state_machine/subscription_cyclic_pause_resume
    """
    cust = make_customer()
    headers = make_customer_headers(cust["id"])
    sub = make_subscription(cust["id"], tier="PREMIUM", monthly_fee_cents=5000)
    api.pause_subscription(sub["id"], headers)
    api.resume_subscription(sub["id"], headers)
    final = validate_success(api.pause_subscription(sub["id"], headers), 200)
    assert final["status"] == "PAUSED"


def test_each_pause_resume_hop_increments_version(api):
    """PRD §3.6: "Pausing an `ACTIVE` subscription moves it to `PAUSED` and
    increments its `version`; resuming a `PAUSED` subscription moves it back to
    `ACTIVE` and again increments `version`."

    Design: Difficulty/non_linear_state_machine/subscription_cyclic_pause_resume
    """
    cust = make_customer()
    headers = make_customer_headers(cust["id"])
    sub = make_subscription(cust["id"], tier="PREMIUM", monthly_fee_cents=5000)
    base = sub["version"]
    api.pause_subscription(sub["id"], headers)
    api.resume_subscription(sub["id"], headers)
    final = validate_success(api.pause_subscription(sub["id"], headers), 200)
    # three mutations from the created baseline, each +1
    assert final["version"] == base + 3


# ─── Difficulty/cross_entity_state_dependency/generate_shipment_requires_subscription_active ───
def test_generate_shipment_on_paused_subscription_rejected(api):
    """PRD §3.6: "The subscription must be `ACTIVE`, or generation is rejected with
    `ERR_SUBSCRIPTION_NOT_ACTIVE`; a paused or cancelled subscription cannot be
    shipped."

    Design: Difficulty/cross_entity_state_dependency/generate_shipment_requires_subscription_active
    """
    cust = make_customer()
    headers = make_customer_headers(cust["id"])
    sub = make_subscription(cust["id"], tier="BASIC", monthly_fee_cents=5000)
    api.pause_subscription(sub["id"], headers)
    resp = api.create_shipment(sub["id"], {"period_start": "2026-07-01T00:00:00Z",
                                           "period_end": "2026-08-01T00:00:00Z"}, FULFILL)
    validate_error(resp, ApiErrorId.ERR_SUBSCRIPTION_NOT_ACTIVE, 409)


def test_generate_shipment_on_cancelled_subscription_rejected(api):
    """PRD §3.6: "a paused or cancelled subscription cannot be shipped." (the
    generation gate is `ERR_SUBSCRIPTION_NOT_ACTIVE`).

    Design: Difficulty/cross_entity_state_dependency/generate_shipment_requires_subscription_active
    """
    cust = make_customer()
    headers = make_customer_headers(cust["id"])
    sub = make_subscription(cust["id"], tier="BASIC", monthly_fee_cents=5000)
    api.cancel_subscription(sub["id"], headers)
    resp = api.create_shipment(sub["id"], {"period_start": "2026-07-01T00:00:00Z",
                                           "period_end": "2026-08-01T00:00:00Z"}, FULFILL)
    validate_error(resp, ApiErrorId.ERR_SUBSCRIPTION_NOT_ACTIVE, 409)


# ─── Difficulty/resource_temporal_overlap/shipment_period_halfopen_overlap ───
def test_overlapping_shipment_period_rejected(api):
    """PRD §3.6: "The new period must not overlap any existing shipment period of
    the same subscription".
    PRD §3.6: "any true overlap is rejected with `ERR_SHIPMENT_PERIOD_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/shipment_period_halfopen_overlap
    """
    cust = make_customer()
    sub = make_subscription(cust["id"], tier="BASIC", monthly_fee_cents=5000)
    make_shipment(sub["id"], "2026-07-01T00:00:00Z", "2026-08-01T00:00:00Z")
    resp = api.create_shipment(sub["id"], {"period_start": "2026-07-15T00:00:00Z",
                                           "period_end": "2026-08-15T00:00:00Z"}, FULFILL)
    validate_error(resp, ApiErrorId.ERR_SHIPMENT_PERIOD_OVERLAP, 409)


def test_adjacent_shipment_period_allowed(api):
    """PRD §3.6: "two periods that merely touch — one ending exactly where the
    next begins — are adjacent and allowed, while any true overlap is rejected
    with `ERR_SHIPMENT_PERIOD_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/shipment_period_halfopen_overlap
    """
    cust = make_customer()
    sub = make_subscription(cust["id"], tier="BASIC", monthly_fee_cents=5000)
    make_shipment(sub["id"], "2026-07-01T00:00:00Z", "2026-08-01T00:00:00Z")
    resp = api.create_shipment(sub["id"], {"period_start": "2026-08-01T00:00:00Z",
                                           "period_end": "2026-09-01T00:00:00Z"}, FULFILL)
    ship = validate_success(resp, 201)
    assert ship["status"] == "PENDING"


# ─── Corner instances ─────────────────────────────────
def test_resume_active_subscription_rejected(api):
    """PRD §3.6: "a resume requires it to currently be `PAUSED`." — resuming an
    already ACTIVE subscription is an invalid transition (`ERR_INVALID_STATE`).

    Design: Corner/state_machines/resume_active_subscription_returns_409
    """
    cust = make_customer()
    headers = make_customer_headers(cust["id"])
    sub = make_subscription(cust["id"], tier="BASIC", monthly_fee_cents=5000)
    resp = api.resume_subscription(sub["id"], headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)


def test_shipment_fulfillment_drives_silver_tier_boundary(api):
    """PRD §3.3: "a lifetime spend of two thousand dollars (200000 cents) or more
    is `GOLD`; a lifetime spend of five hundred dollars (50000 cents) or more but
    below the gold threshold is `SILVER`; anything below five hundred dollars is
    `BRONZE`."
    PRD §3.3: "These boundaries are inclusive at the stated amount." — a 50000
    shipment charge lands exactly on the boundary.

    Design: Corner/calculations/customer_tier_silver_boundary_via_shipment
    """
    cust = make_customer()
    sub = make_subscription(cust["id"], tier="PREMIUM", monthly_fee_cents=50000)
    ship = make_shipment(sub["id"], "2026-07-01T00:00:00Z", "2026-08-01T00:00:00Z")
    fulfill_shipment(ship["id"])
    fetched = validate_success(api.get_customer(cust["id"], make_customer_headers(cust["id"])), 200)
    assert fetched["lifetime_spend_cents"] == 50000
    assert fetched["tier"] == "SILVER"
