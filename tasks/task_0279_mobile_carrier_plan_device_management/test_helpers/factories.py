"""Payload factories — one per entity, input fields only (PRD §3).

Each factory builds the request body for a create/transition endpoint using
only client-supplied (source: input) fields, with sensible defaults that
**overrides can replace.
"""
import itertools

from .constants import PLAN_DEFAULTS

# Monotonic counters so default unique fields (plan code, device sku, iccid,
# emails) never collide within a single test run.
_seq = itertools.count(1)


def _next() -> int:
    return next(_seq)


def create_account_payload(**overrides) -> dict:
    n = _next()
    defaults = {
        "holder_name": f"Holder {n}",
        "holder_email": f"holder{n}@example.com",
        "billing_day_of_month": 1,
    }
    defaults.update(overrides)
    return defaults


def create_plan_payload(**overrides) -> dict:
    n = _next()
    defaults = {
        "code": f"PLAN-{n}",
        "name": "Plus",
        "monthly_fee_cents": PLAN_DEFAULTS["monthly_fee_cents"],
        "included_data_mb": PLAN_DEFAULTS["included_data_mb"],
        "overage_tier1_cap_mb": PLAN_DEFAULTS["overage_tier1_cap_mb"],
        "overage_tier1_rate_milli_cents": PLAN_DEFAULTS["overage_tier1_rate_milli_cents"],
        "overage_tier2_rate_milli_cents": PLAN_DEFAULTS["overage_tier2_rate_milli_cents"],
    }
    defaults.update(overrides)
    return defaults


def create_device_payload(**overrides) -> dict:
    n = _next()
    defaults = {
        "model": f"Phone {n}",
        "sku": f"SKU-{n}",
        "retail_price_cents": 99900,
        "stock_count": 5,
    }
    defaults.update(overrides)
    return defaults


def create_line_payload(account_id: str, plan_id: str, expected_account_version: int,
                        sim_type: str = "PHYSICAL", **overrides) -> dict:
    defaults = {
        "account_id": account_id,
        "plan_id": plan_id,
        "sim_type": sim_type,
        "expected_account_version": expected_account_version,
    }
    defaults.update(overrides)
    return defaults


def create_sim_assignment_payload(line_id: str, sim_type: str = "PHYSICAL",
                                  iccid: str = None, **overrides) -> dict:
    defaults = {"line_id": line_id, "sim_type": sim_type}
    if sim_type == "PHYSICAL":
        defaults["iccid"] = iccid if iccid is not None else f"890100000000000{_next():04d}"
    elif iccid is not None:
        defaults["iccid"] = iccid
    defaults.update(overrides)
    return defaults


def create_installment_plan_payload(line_id: str, device_id: str,
                                    term_months: int = 24,
                                    down_payment_cents: int = 9900, **overrides) -> dict:
    defaults = {
        "line_id": line_id,
        "device_id": device_id,
        "term_months": term_months,
        "down_payment_cents": down_payment_cents,
    }
    defaults.update(overrides)
    return defaults


def create_upgrade_payload(line_id: str, old_installment_plan_id: str,
                           new_device_id: str, new_term_months: int = 24,
                           new_down_payment_cents: int = 19900,
                           trade_in_credit_cents: int = 0, **overrides) -> dict:
    defaults = {
        "line_id": line_id,
        "old_installment_plan_id": old_installment_plan_id,
        "new_device_id": new_device_id,
        "new_term_months": new_term_months,
        "new_down_payment_cents": new_down_payment_cents,
        "trade_in_credit_cents": trade_in_credit_cents,
    }
    defaults.update(overrides)
    return defaults


def create_port_request_payload(line_id: str, direction: str = "PORT_IN",
                                external_number: str = "12025550100",
                                donor_carrier: str = "OtherCo",
                                account_pin: str = "1234", **overrides) -> dict:
    defaults = {
        "line_id": line_id,
        "direction": direction,
        "external_number": external_number,
        "donor_carrier": donor_carrier,
        "account_pin": account_pin,
    }
    defaults.update(overrides)
    return defaults


def create_addon_payload(line_id: str, addon_type: str, window_start: str,
                         window_end: str, daily_fee_cents: int = None,
                         monthly_fee_cents: int = None, **overrides) -> dict:
    defaults = {
        "line_id": line_id,
        "addon_type": addon_type,
        "window_start": window_start,
        "window_end": window_end,
    }
    if addon_type == "ROAMING_DAYPASS":
        defaults["daily_fee_cents"] = daily_fee_cents if daily_fee_cents is not None else 1000
    elif addon_type == "INTL_MONTHLY":
        defaults["monthly_fee_cents"] = monthly_fee_cents if monthly_fee_cents is not None else 3000
    if daily_fee_cents is not None:
        defaults["daily_fee_cents"] = daily_fee_cents
    if monthly_fee_cents is not None:
        defaults["monthly_fee_cents"] = monthly_fee_cents
    defaults.update(overrides)
    return defaults


def create_usage_record_payload(line_id: str, usage_type: str = "DATA",
                                data_mb: int = 0, occurred_at: str = None,
                                **overrides) -> dict:
    defaults = {
        "line_id": line_id,
        "usage_type": usage_type,
        "data_mb": data_mb,
        "occurred_at": occurred_at,
    }
    defaults.update(overrides)
    return defaults


def create_billing_cycle_payload(account_id: str, cycle_start: str,
                                 cycle_end: str, **overrides) -> dict:
    defaults = {
        "account_id": account_id,
        "cycle_start": cycle_start,
        "cycle_end": cycle_end,
    }
    defaults.update(overrides)
    return defaults
