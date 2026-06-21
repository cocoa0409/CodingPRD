"""Net metering: settlement variants, kWh bank conservation, period ordering."""
import pytest
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS,
    setup_operational_project, open_period, settle_period,
    create_net_meter_period_payload,
)

ADMIN = TEST_USERS["platform_admin_headers"]


# --- Difficulty: dual_variant_calc / net_metering_full_retail_vs_net_billing ---

def test_full_retail_surplus_credit(api):
    """PRD 3.8: "the bill_credit_cents is that credited figure multiplied by the
    utility's net_metering_rate_cents_per_kwh and by the utility's
    export_credit_ratio, rounded half up."

    Design: Difficulty/dual_variant_calc/net_metering_full_retail_vs_net_billing
    """
    ctx = setup_operational_project(net_metering_rate_cents_per_kwh=15.0, export_credit_ratio=1.0)
    period = open_period(ctx, "2026-01-01T00:00:00.000Z", "2026-02-01T00:00:00.000Z", 900, 600)
    settled = settle_period(ctx, period["id"])
    assert settled["net_kwh"] == 300
    # full retail: 300 * 15 * 1.0 == 4500
    assert settled["bill_credit_cents"] == 4500


def test_net_billing_surplus_credit_discounted(api):
    """PRD 3.8: "below 1.0 the surplus is credited at a discounted rate while
    consumption is still charged at full retail, an asymmetric net-billing outcome
    that yields a different bill_credit_cents for the same net_kwh."

    Design: Difficulty/dual_variant_calc/net_metering_full_retail_vs_net_billing
    """
    ctx = setup_operational_project(net_metering_rate_cents_per_kwh=15.0, export_credit_ratio=0.5)
    period = open_period(ctx, "2026-01-01T00:00:00.000Z", "2026-02-01T00:00:00.000Z", 900, 600)
    settled = settle_period(ctx, period["id"])
    assert settled["net_kwh"] == 300
    # net billing: 300 * 15 * 0.5 == 2250
    assert settled["bill_credit_cents"] == 2250


# --- Difficulty: compensating_invariant / net_metering_kwh_bank_conserved ---

def test_kwh_bank_banks_full_surplus(api):
    """PRD 3.8: "The bank_kwh_after grows by the full surplus over the prior bank
    balance."

    Design: Difficulty/compensating_invariant/net_metering_kwh_bank_conserved_surplus_then_draw
    """
    ctx = setup_operational_project(net_metering_rate_cents_per_kwh=15.0, export_credit_ratio=1.0)
    pA = open_period(ctx, "2026-01-01T00:00:00.000Z", "2026-02-01T00:00:00.000Z", 900, 600)
    settledA = settle_period(ctx, pA["id"])
    assert settledA["bank_kwh_after"] == 300


def test_kwh_bank_draws_then_bills_residual(api):
    """PRD 3.8: "The system first draws from the bank: the drawn amount is the
    smaller of the prior bank balance and the deficit, the bank_kwh_after is the
    prior balance minus that draw, and the billable remainder is the deficit minus
    the draw. The bill_credit_cents is then the negative of the billable
    kilowatt-hours multiplied by the net_metering_rate_cents_per_kwh, rounded half
    up — a negative value representing a charge."

    Design: Difficulty/compensating_invariant/net_metering_kwh_bank_conserved_surplus_then_draw
    """
    ctx = setup_operational_project(net_metering_rate_cents_per_kwh=15.0, export_credit_ratio=1.0)
    pA = open_period(ctx, "2026-01-01T00:00:00.000Z", "2026-02-01T00:00:00.000Z", 900, 600)
    settle_period(ctx, pA["id"])  # banks +300
    pB = open_period(ctx, "2026-02-01T00:00:00.000Z", "2026-03-01T00:00:00.000Z", 400, 1000)
    settledB = settle_period(ctx, pB["id"])
    assert settledB["net_kwh"] == -600
    assert settledB["bank_kwh_after"] == 0   # full 300 drawn out
    assert settledB["bill_credit_cents"] == -4500  # residual 300 * 15, negative


# --- Difficulty: resource_temporal_overlap / net_meter_period_half_open ---

def test_touching_period_endpoint_is_accepted(api):
    """PRD 3.8: "intervals are half-open [period_start, period_end), so a new
    period whose half-open span intersects any existing period on the project is
    rejected with ERR_PERIOD_OVERLAP (HTTP 409), though periods that merely touch
    at an endpoint are allowed."

    Design: Difficulty/resource_temporal_overlap/net_meter_period_half_open_no_overlap_touching_ok
    """
    ctx = setup_operational_project()
    open_period(ctx, "2026-01-01T00:00:00.000Z", "2026-02-01T00:00:00.000Z", 900, 600)
    resp = api.create_net_meter_period(
        create_net_meter_period_payload(
            project_id=ctx["project"]["id"],
            period_start="2026-02-01T00:00:00.000Z",
            period_end="2026-03-01T00:00:00.000Z",
            kwh_produced=800, kwh_consumed=500,
        ),
        ctx["util_headers"],
    )
    data = validate_success(resp, 201)
    assert data["status"] == "OPEN"


def test_interior_overlapping_period_rejected(api):
    """PRD 3.8: "a new period whose half-open span intersects any existing period
    on the project is rejected with ERR_PERIOD_OVERLAP (HTTP 409)"

    Design: Difficulty/resource_temporal_overlap/net_meter_period_half_open_no_overlap_touching_ok
    """
    ctx = setup_operational_project()
    open_period(ctx, "2026-01-01T00:00:00.000Z", "2026-02-01T00:00:00.000Z", 900, 600)
    resp = api.create_net_meter_period(
        create_net_meter_period_payload(
            project_id=ctx["project"]["id"],
            period_start="2026-01-15T00:00:00.000Z",
            period_end="2026-02-15T00:00:00.000Z",
            kwh_produced=700, kwh_consumed=400,
        ),
        ctx["util_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_PERIOD_OVERLAP, 409)


# --- Difficulty: cross_entity_state_dependency / settle_period_requires_project_operational ---

def test_settle_open_period_on_operational_project_succeeds(api):
    """PRD 3.8: "Once a project is operational, the serving Utility records monthly
    net-meter periods and settles them in order."

    Design: Difficulty/cross_entity_state_dependency/settle_period_requires_project_operational
    """
    ctx = setup_operational_project(net_metering_rate_cents_per_kwh=15.0)
    period = open_period(ctx, "2026-01-01T00:00:00.000Z", "2026-02-01T00:00:00.000Z", 900, 600)
    settled = settle_period(ctx, period["id"])
    assert settled["status"] == "SETTLED"
    assert settled["net_kwh"] == 300


def test_settle_computes_bill_credit_on_operational_project(api):
    """PRD 3.8: "Settlement moves a period from OPEN to SETTLED and must proceed in
    chronological period_start order"

    Design: Difficulty/cross_entity_state_dependency/settle_period_requires_project_operational
    """
    ctx = setup_operational_project(net_metering_rate_cents_per_kwh=15.0, export_credit_ratio=1.0)
    period = open_period(ctx, "2026-01-01T00:00:00.000Z", "2026-02-01T00:00:00.000Z", 900, 600)
    settled = settle_period(ctx, period["id"])
    assert settled["bill_credit_cents"] == 4500


# --- Corner: out-of-order settlement + invalid interval ---

def test_out_of_order_settlement_rejected(api):
    """PRD 3.8: "settling a period while an earlier OPEN period still exists on the
    same project is rejected with ERR_OUT_OF_ORDER_SETTLEMENT (HTTP 409)."

    Design: Corner/state_machines/out_of_order_settlement_rejected
    """
    ctx = setup_operational_project()
    open_period(ctx, "2026-01-01T00:00:00.000Z", "2026-02-01T00:00:00.000Z", 900, 600)
    feb = open_period(ctx, "2026-02-01T00:00:00.000Z", "2026-03-01T00:00:00.000Z", 800, 500)
    resp = api.settle_net_meter_period(feb["id"], ctx["util_headers"])
    validate_error(resp, ApiErrorId.ERR_OUT_OF_ORDER_SETTLEMENT, 409)


def test_net_meter_period_end_before_start_rejected(api):
    """PRD 3.8: "the inclusive period_start and exclusive period_end (the end must
    be strictly after the start, else ERR_INVALID_INTERVAL, HTTP 422)"

    Design: Corner/state_machines/invalid_interval_end_before_start
    """
    ctx = setup_operational_project()
    resp = api.create_net_meter_period(
        create_net_meter_period_payload(
            project_id=ctx["project"]["id"],
            period_start="2026-03-01T00:00:00.000Z",
            period_end="2026-02-01T00:00:00.000Z",
            kwh_produced=100, kwh_consumed=50,
        ),
        ctx["util_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_INTERVAL, 422)
