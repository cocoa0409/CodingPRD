"""Payload factories — one per creatable resource, input fields only.

Field names are PRD-exact. Computed fields (status, balances, tou_period,
avg_demand_kw, totals, etc.) are never sent — the server derives them.
"""
import itertools

# Monotonic counters so default unique fields (tariff code, meter serial) do
# not collide across calls within a test that creates several resources.
_tariff_code_seq = itertools.count(1)
_meter_serial_seq = itertools.count(1)


def create_tariff_payload(**overrides) -> dict:
    """POST /tariffs input fields (PRD §3.1). Defaults to a well-shaped
    residential TOU tariff: rates strictly ascending, TOU ordered."""
    defaults = {
        "code": f"RES-TOU-{next(_tariff_code_seq):04d}",
        "name": "Residential TOU",
        "fixed_charge_cents": 1000,
        "tier_breakpoints_kwh": [500, 1000],
        "tier_rates_cents_per_kwh": [12, 18, 25],
        "tou_multipliers": {"ON_PEAK": 1.5, "MID_PEAK": 1.0, "OFF_PEAK": 0.8},
        "demand_charge_cents_per_kw": 800,
        "net_metering_credit_cents_per_kwh": 10,
    }
    defaults.update(overrides)
    return defaults


def create_account_payload(tariff_id: str, **overrides) -> dict:
    """POST /accounts input fields (PRD §3.2)."""
    defaults = {
        "tariff_id": tariff_id,
        "holder_name": "Test Holder",
    }
    defaults.update(overrides)
    return defaults


def create_meter_payload(account_id: str, **overrides) -> dict:
    """POST /meters input fields (PRD §3.2). meter_type is optional,
    defaulting server-side to BIDIRECTIONAL."""
    defaults = {
        "account_id": account_id,
        "serial": f"MTR-{next(_meter_serial_seq):05d}",
    }
    defaults.update(overrides)
    return defaults


def create_meter_read_payload(meter_id: str, interval_start: str,
                              interval_end: str, import_kwh: float,
                              **overrides) -> dict:
    """POST /meter-reads input fields (PRD §3.2). export_kwh is optional."""
    defaults = {
        "meter_id": meter_id,
        "interval_start": interval_start,
        "interval_end": interval_end,
        "import_kwh": import_kwh,
        "export_kwh": 0.0,
    }
    defaults.update(overrides)
    return defaults


def create_bill_payload(account_id: str, period_start: str, period_end: str,
                        due_date: str, **overrides) -> dict:
    """POST /bills input fields (PRD §3.3)."""
    defaults = {
        "account_id": account_id,
        "period_start": period_start,
        "period_end": period_end,
        "due_date": due_date,
    }
    defaults.update(overrides)
    return defaults


def create_payment_payload(account_id: str, amount_cents: int, **overrides) -> dict:
    """POST /payments input fields (PRD §3.5). method is optional (default ACH)."""
    defaults = {
        "account_id": account_id,
        "amount_cents": amount_cents,
        "method": "ACH",
    }
    defaults.update(overrides)
    return defaults


def create_budget_plan_payload(account_id: str, levelized_amount_cents: int,
                               **overrides) -> dict:
    """POST /budget-plans input fields (PRD §3.7)."""
    defaults = {
        "account_id": account_id,
        "levelized_amount_cents": levelized_amount_cents,
    }
    defaults.update(overrides)
    return defaults


def create_assistance_grant_payload(account_id: str, pledged_cents: int,
                                    **overrides) -> dict:
    """POST /assistance-grants input fields (PRD §3.8). program is optional
    (default LIHEAP)."""
    defaults = {
        "account_id": account_id,
        "pledged_cents": pledged_cents,
        "program": "LIHEAP",
    }
    defaults.update(overrides)
    return defaults
