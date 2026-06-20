"""Payload factories — one per entity, input fields only."""


def create_rate_schedule_payload(**overrides) -> dict:
    """RateSchedule: code, customer_class, fixed_customer_charge_cents,
    distribution_rate_cents_per_therm required; btu_factor / minimum_bill_cents optional."""
    defaults = {
        "code": "RES-1",
        "customer_class": "RESIDENTIAL",
        "fixed_customer_charge_cents": 1200,
        "distribution_rate_cents_per_therm": 15,
        "btu_factor": 1.025,
        "minimum_bill_cents": 0,
    }
    defaults.update(overrides)
    return defaults


def create_pga_schedule_payload(**overrides) -> dict:
    """PgaSchedule: effective_month, customer_class, commodity_rate_cents_per_therm
    required; supplier_refund_cents_per_therm optional."""
    defaults = {
        "effective_month": "2026-02",
        "customer_class": "RESIDENTIAL",
        "commodity_rate_cents_per_therm": 40,
        "supplier_refund_cents_per_therm": 5,
    }
    defaults.update(overrides)
    return defaults


def create_account_payload(**overrides) -> dict:
    """Account: rate_schedule_id, holder_name required."""
    defaults = {
        "holder_name": "Test Holder",
    }
    defaults.update(overrides)
    return defaults


def create_meter_payload(**overrides) -> dict:
    """PremiseMeter: serial_no required; uom / install_index optional."""
    defaults = {
        "serial_no": "M-001",
        "uom": "CCF",
        "install_index": 1000,
    }
    defaults.update(overrides)
    return defaults


def create_meter_read_payload(**overrides) -> dict:
    """MeterRead: reading_index required; read_date / read_type optional."""
    defaults = {
        "reading_index": 1100,
        "read_date": "2026-02-28T00:00:00.000Z",
        "read_type": "ACTUAL",
    }
    defaults.update(overrides)
    return defaults


def create_bill_payload(**overrides) -> dict:
    """Bill: service_month, to_read_id required; from_read_id / corrects_bill_id optional."""
    defaults = {
        "service_month": "2026-02",
    }
    defaults.update(overrides)
    return defaults


def issue_bill_payload(**overrides) -> dict:
    """Bill issue: expected_account_version required (OCC)."""
    defaults = {}
    defaults.update(overrides)
    return defaults


def create_payment_payload(**overrides) -> dict:
    """Payment: bill_id, amount_cents required; posted_date optional."""
    defaults = {
        "amount_cents": 6326,
        "posted_date": "2026-03-01T00:00:00.000Z",
    }
    defaults.update(overrides)
    return defaults


def create_budget_plan_payload(**overrides) -> dict:
    """BudgetPlan: anchor_month, projected_annual_cents, expected_account_version required."""
    defaults = {
        "anchor_month": "2026-02",
        "projected_annual_cents": 96000,
    }
    defaults.update(overrides)
    return defaults


def create_deposit_payload(**overrides) -> dict:
    """Deposit: reason required."""
    defaults = {
        "reason": "NEW_SERVICE",
    }
    defaults.update(overrides)
    return defaults


def create_low_income_credit_payload(**overrides) -> dict:
    """LowIncomeCredit: household_size, annual_income_cents required."""
    defaults = {
        "household_size": 1,
        "annual_income_cents": 1400000,
    }
    defaults.update(overrides)
    return defaults


def create_service_order_payload(**overrides) -> dict:
    """ServiceOrder: account_id, order_type required; premise_meter_id / scheduled_date optional."""
    defaults = {
        "order_type": "METER_SET",
        "scheduled_date": "2026-02-01T00:00:00.000Z",
    }
    defaults.update(overrides)
    return defaults


def create_ticket_payload(**overrides) -> dict:
    """EmergencyTicket: premise_meter_id, kind required; account_id / reported_indoors optional."""
    defaults = {
        "kind": "ODOR",
        "reported_indoors": False,
    }
    defaults.update(overrides)
    return defaults


def set_clock_payload(**overrides) -> dict:
    """Clock: current_utc / heating_season_active both optional."""
    defaults = {
        "current_utc": "2026-02-15T00:00:00.000Z",
        "heating_season_active": False,
    }
    defaults.update(overrides)
    return defaults
