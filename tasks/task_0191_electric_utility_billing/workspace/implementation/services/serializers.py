"""Response serializers — one per entity. Each emits exactly the fields the PRD
declares for that resource, plus the system-managed common fields.

Common fields (PRD §2.4):
  - all resources: id, created_at
  - resources carrying common_fields=True: also updated_at, version
  - MeterRead and SystemClock: only id, created_at (no updated_at/version)
"""


def _common(rec, with_version=True):
    out = {
        "id": rec["id"],
        "created_at": rec["created_at"],
    }
    if with_version:
        out["updated_at"] = rec["updated_at"]
        out["version"] = rec["version"]
    return out


def tariff(rec):
    out = _common(rec)
    out.update({
        "code": rec["code"],
        "name": rec["name"],
        "status": rec["status"],
        "fixed_charge_cents": rec["fixed_charge_cents"],
        "tier_breakpoints_kwh": rec["tier_breakpoints_kwh"],
        "tier_rates_cents_per_kwh": rec["tier_rates_cents_per_kwh"],
        "tou_multipliers": rec["tou_multipliers"],
        "demand_charge_cents_per_kw": rec["demand_charge_cents_per_kw"],
        "net_metering_credit_cents_per_kwh": rec["net_metering_credit_cents_per_kwh"],
    })
    return out


def account(rec):
    out = _common(rec)
    out.update({
        "tariff_id": rec["tariff_id"],
        "holder_name": rec["holder_name"],
        "service_status": rec["service_status"],
        "financial_status": rec["financial_status"],
        "balance_cents": rec["balance_cents"],
        "net_metering_credit_balance_cents": rec["net_metering_credit_balance_cents"],
        "oldest_unpaid_bill_due_date": rec["oldest_unpaid_bill_due_date"],
        "budget_plan_id": rec["budget_plan_id"],
    })
    return out


def meter(rec):
    out = _common(rec)
    out.update({
        "account_id": rec["account_id"],
        "serial": rec["serial"],
        "meter_type": rec["meter_type"],
        "status": rec["status"],
    })
    return out


def meter_read(rec):
    # MeterRead carries only id + created_at (no updated_at/version).
    out = _common(rec, with_version=False)
    out.update({
        "meter_id": rec["meter_id"],
        "interval_start": rec["interval_start"],
        "interval_end": rec["interval_end"],
        "import_kwh": rec["import_kwh"],
        "export_kwh": rec["export_kwh"],
        "tou_period": rec["tou_period"],
        "avg_demand_kw": rec["avg_demand_kw"],
    })
    return out


def bill(rec):
    out = _common(rec)
    out.update({
        "account_id": rec["account_id"],
        "tariff_id": rec["tariff_id"],
        "period_start": rec["period_start"],
        "period_end": rec["period_end"],
        "status": rec["status"],
        "total_import_kwh": rec["total_import_kwh"],
        "total_export_kwh": rec["total_export_kwh"],
        "billed_peak_demand_kw": rec["billed_peak_demand_kw"],
        "energy_charge_cents": rec["energy_charge_cents"],
        "demand_charge_cents": rec["demand_charge_cents"],
        "net_metering_credit_applied_cents": rec["net_metering_credit_applied_cents"],
        "assistance_applied_cents": rec["assistance_applied_cents"],
        "total_due_cents": rec["total_due_cents"],
        "amount_paid_cents": rec["amount_paid_cents"],
        "due_date": rec["due_date"],
        "is_budget_billed": rec["is_budget_billed"],
        "actual_cost_cents": rec["actual_cost_cents"],
    })
    return out


def payment(rec):
    out = _common(rec)
    out.update({
        "account_id": rec["account_id"],
        "amount_cents": rec["amount_cents"],
        "method": rec["method"],
        "status": rec["status"],
        "allocations": rec["allocations"],
    })
    return out


def service_order(rec):
    out = _common(rec)
    out.update({
        "account_id": rec["account_id"],
        "order_type": rec["order_type"],
        "status": rec["status"],
        "reason": rec["reason"],
    })
    return out


def budget_plan(rec):
    out = _common(rec)
    out.update({
        "account_id": rec["account_id"],
        "status": rec["status"],
        "levelized_amount_cents": rec["levelized_amount_cents"],
        "accumulated_actual_cents": rec["accumulated_actual_cents"],
        "accumulated_levelized_cents": rec["accumulated_levelized_cents"],
        "true_up_balance_cents": rec["true_up_balance_cents"],
    })
    return out


def assistance_grant(rec):
    out = _common(rec)
    out.update({
        "account_id": rec["account_id"],
        "program": rec["program"],
        "status": rec["status"],
        "pledged_cents": rec["pledged_cents"],
        "remaining_cents": rec["remaining_cents"],
    })
    return out


def clock(rec):
    # SystemClock carries only id + created_at + current_utc.
    return {
        "id": rec["id"],
        "created_at": rec["created_at"],
        "current_utc": rec["current_utc"],
    }
