"""Tank leases, market quotes, budget enrollment, and order origin.

Translates queue A (Difficulty) rule resource_temporal_overlap (lease half-open
overlap) and queue B (Corner) instances from `calculations` (monthly installment),
`endpoints` (lease/decommission, market supersede, will-call origin), and
`validations` (13th installment, active-lease decommission guard).
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, TEST_USERS, make_customer_headers,
    create_lease_payload, create_market_price_payload,
    create_budget_plan_payload, create_order_payload,
)
from test_helpers import fixtures as fx

AM = TEST_USERS["account_manager_headers"]
DISP = TEST_USERS["dispatcher_headers"]


# ---------------------------------------------------------------------------
# Difficulty: resource_temporal_overlap — lease half-open [start, end) overlap
# ---------------------------------------------------------------------------
def test_lease_touching_interval_admitted(api):
    """PRD §3.9: "its half-open interval from `lease_start` up to but not including `lease_end` is checked against the tank's other `ACTIVE` leases: any overlap of those half-open intervals is rejected with `ERR_LEASE_PERIOD_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/lease_halfopen_overlap_on_tank
    """
    account = fx.create_account(customer_name="Lease Lena")
    tank = fx.create_tank(account["id"], current_gallons=100)
    fx.create_lease(tank["id"], lease_start="2026-01-01T00:00:00Z",
                    lease_end="2026-04-01T00:00:00Z")
    # New lease starts exactly at 2026-04-01 (where the prior half-open interval
    # ends, exclusive) -> no overlap -> admitted ACTIVE.
    resp = api.create_lease(tank["id"], create_lease_payload(
        lease_start="2026-04-01T00:00:00Z", lease_end="2026-07-01T00:00:00Z"), AM)
    data = validate_success(resp, expected_status=201)
    assert data["status"] == "ACTIVE"


def test_lease_overlapping_interval_rejected(api):
    """PRD §3.9: "any overlap of those half-open intervals is rejected with `ERR_LEASE_PERIOD_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/lease_halfopen_overlap_on_tank
    """
    account = fx.create_account(customer_name="Lease Lena")
    tank = fx.create_tank(account["id"], current_gallons=100)
    fx.create_lease(tank["id"], lease_start="2026-01-01T00:00:00Z",
                    lease_end="2026-04-01T00:00:00Z")
    # [2026-03-15, 2026-06-01) overlaps [2026-01-01, 2026-04-01) -> rejected.
    resp = api.create_lease(tank["id"], create_lease_payload(
        lease_start="2026-03-15T00:00:00Z", lease_end="2026-06-01T00:00:00Z"), AM)
    validate_error(resp, ApiErrorId.ERR_LEASE_PERIOD_OVERLAP.value)


# ---------------------------------------------------------------------------
# Corner: endpoints — lease terminate then decommission; market supersede
# ---------------------------------------------------------------------------
def test_terminate_lease_then_decommission_tank(api):
    """PRD §3.9: "An account manager terminates a lease, `ACTIVE → TERMINATED`, which requires the lease to be `ACTIVE` (else `ERR_INVALID_STATE`)."
    PRD §3.3: "A tank may be decommissioned `IN_SERVICE → DECOMMISSIONED` by an account manager, but only when no `ACTIVE` `TankLease` exists on it"

    Design: Corner/endpoints/terminate_lease_then_decommission_tank
    """
    account = fx.create_account(customer_name="Decom Deb")
    tank = fx.create_tank(account["id"], current_gallons=100)
    lease = fx.create_lease(tank["id"])
    terminated = validate_success(api.terminate_lease(tank["id"], lease["id"], AM))
    assert terminated["status"] == "TERMINATED"
    decom = validate_success(api.decommission_tank(tank["id"], AM))
    assert decom["service_status"] == "DECOMMISSIONED"


def test_decommission_tank_with_active_lease_rejected(api):
    """PRD §3.3: "A tank may be decommissioned `IN_SERVICE → DECOMMISSIONED` by an account manager, but only when no `ACTIVE` `TankLease` exists on it (else `ERR_ACCOUNT_HAS_ACTIVE_LEASE`)"

    Design: Corner/endpoints/decommission_tank_with_active_lease_rejected
    """
    account = fx.create_account(customer_name="Leased Lee")
    tank = fx.create_tank(account["id"], current_gallons=100)
    fx.create_lease(tank["id"])
    resp = api.decommission_tank(tank["id"], AM)
    validate_error(resp, ApiErrorId.ERR_ACCOUNT_HAS_ACTIVE_LEASE.value)


def test_market_price_supersede_expires_prior(api):
    """PRD §2.11: "publishing a newer quote for the same `region_code` and `fuel_type` automatically transitions the prior `ACTIVE` quote to `EXPIRED`."

    Design: Corner/endpoints/market_price_supersede_expires_prior
    """
    mp1 = validate_success(api.create_market_price(
        create_market_price_payload(region_code="NE_05", fuel_type="HEATING_OIL",
                                    market_price_cents_per_gallon=400), AM),
        expected_status=201)
    validate_success(api.create_market_price(
        create_market_price_payload(region_code="NE_05", fuel_type="HEATING_OIL",
                                    market_price_cents_per_gallon=420), AM),
        expected_status=201)
    expired = validate_success(api.get_market_price(mp1["id"], AM))
    assert expired["status"] == "EXPIRED"
    data, meta = validate_paginated(api.list_market_prices(
        AM, params={"region_code": "NE_05", "status": "ACTIVE"}))
    assert meta["total_count"] == 1


def test_will_call_order_created_origin(api):
    """PRD §3.6: "such an order is born with `origin` of `WILL_CALL` and `status` of `CREATED`."

    Design: Corner/endpoints/will_call_order_created_origin
    """
    account = fx.create_account(customer_name="WillCall Win")
    tank = fx.create_tank(account["id"], current_gallons=100)
    resp = api.create_order(account["id"],
                            create_order_payload(tank["id"], requested_gallons=150),
                            make_customer_headers(account["id"]))
    data = validate_success(resp, expected_status=201)
    assert data["origin"] == "WILL_CALL"
    assert data["status"] == "CREATED"


# ---------------------------------------------------------------------------
# Corner: calculations / validations — budget plan
# ---------------------------------------------------------------------------
def test_monthly_installment_round_half_up(api):
    """PRD §3.10: "the estimated annual cost is `estimated_annual_gallons` multiplied by `estimated_price_cents_per_gallon`, and the monthly installment is that product divided by 12, rounded half up to a whole cent."

    Design: Corner/calculations/monthly_installment_round_half_up
    """
    account = fx.create_account(customer_name="Round Rod")
    resp = api.create_budget_plan(account["id"], create_budget_plan_payload(
        estimated_annual_gallons=1000, estimated_price_cents_per_gallon=305), AM)
    data = validate_success(resp, expected_status=201)
    # 1000*305 = 305000; 305000/12 = 25416.67 -> round_half_up 25417.
    assert data["monthly_installment_cents"] == 25417


def test_budget_plan_thirteenth_installment_rejected(api):
    """PRD §3.10: "which requires the plan to be `ACTIVE` (else `ERR_INVALID_STATE`) and the `installments_paid_count` to be below 12 (else `ERR_BUDGET_PLAN_FULLY_PAID`, since at most twelve installments may be posted)."

    Design: Corner/validations/budget_plan_thirteenth_installment_rejected
    """
    account = fx.create_account(customer_name="Twelve Tom")
    bp = fx.create_budget_plan(account["id"], estimated_annual_gallons=1200,
                               estimated_price_cents_per_gallon=300)
    fx.post_installments(account["id"], bp["id"], 12)
    resp = api.post_installment(account["id"], bp["id"], AM)
    validate_error(resp, ApiErrorId.ERR_BUDGET_PLAN_FULLY_PAID.value)
