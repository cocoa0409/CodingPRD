"""Public JSON representations.  Computed fields are derived at read time."""
from services import ifta as ifta_service
from services import mpg as mpg_service
from services.ledger import hold_amount, ledger


def _common(record):
    return {
        "id": record["id"],
        "created_at": record["created_at"],
        "updated_at": record["updated_at"],
        "version": record["version"],
    }


def fleet_account(record):
    out = _common(record)
    out.update({
        "company_name": record["company_name"],
        "status": record["status"],
        "base_jurisdiction": record["base_jurisdiction"],
        "credit_limit_cents": record["credit_limit_cents"],
        "rebate_tiers": record["rebate_tiers"],
    })
    out.update(ledger(record))
    return out


def vehicle(record):
    out = _common(record)
    out.update({
        "fleet_account_id": record["fleet_account_id"],
        "plate": record["plate"],
        "tank_capacity_gallons": record["tank_capacity_gallons"],
        "starting_odometer": record["starting_odometer"],
        "current_odometer": mpg_service.current_odometer(record),
        "expected_mpg_min": record["expected_mpg_min"],
        "expected_mpg_max": record["expected_mpg_max"],
        "home_jurisdiction": record["home_jurisdiction"],
        "status": record["status"],
    })
    return out


def driver(record):
    out = _common(record)
    out.update({
        "fleet_account_id": record["fleet_account_id"],
        "full_name": record["full_name"],
        "pin": record["pin"],
        "status": record["status"],
    })
    return out


def fuel_card(record):
    out = _common(record)
    out.update({
        "fleet_account_id": record["fleet_account_id"],
        "last4": record["last4"],
        "status": record["status"],
        "allowed_products": record["allowed_products"],
        "daily_dollar_limit_cents": record["daily_dollar_limit_cents"],
        "per_txn_gallon_limit": record["per_txn_gallon_limit"],
        "allowed_start_hour": record["allowed_start_hour"],
        "allowed_end_hour": record["allowed_end_hour"],
    })
    return out


def card_assignment(record):
    out = _common(record)
    out.update({
        "card_id": record["card_id"],
        "vehicle_id": record["vehicle_id"],
        "driver_id": record["driver_id"],
        "effective_from": record["effective_from"],
        "effective_to": record["effective_to"],
        "status": record["status"],
    })
    return out


def transaction(record):
    out = _common(record)
    out.update({
        "card_id": record["card_id"],
        "vehicle_id": record["vehicle_id"],
        "driver_id": record["driver_id"],
        "product": record["product"],
        "gallons": record["gallons"],
        "unit_price_cents": record["unit_price_cents"],
        "odometer": record["odometer"],
        "jurisdiction": record["jurisdiction"],
        "gross_amount_cents": record["gross_amount_cents"],
        "hold_amount_cents": hold_amount(record),
        "segment_miles": record["segment_miles"],
        "mpg_snapshot": record["mpg_snapshot"],
        "mpg_exception": record["mpg_exception"],
        "purchased_at": record["purchased_at"],
        "posting_status": record["posting_status"],
        "review_status": record["review_status"],
        "provisional_rebate_cents": record["provisional_rebate_cents"],
        "final_rebate_cents": record["final_rebate_cents"],
    })
    return out


def fraud_alert(record):
    out = _common(record)
    out.update({
        "transaction_id": record["transaction_id"],
        "card_id": record["card_id"],
        "rule_code": record["rule_code"],
        "status": record["status"],
        "resolution_note": record["resolution_note"],
    })
    return out


def telematics_fault(record):
    out = _common(record)
    out.update({
        "vehicle_id": record["vehicle_id"],
        "fault_code": record["fault_code"],
        "severity": record["severity"],
        "status": record["status"],
        "maintenance_window_start": record["maintenance_window_start"],
        "maintenance_window_end": record["maintenance_window_end"],
    })
    return out


def ifta_report(record):
    """A DRAFT report reconciles against current settled activity; filing freezes
    jurisdiction_lines and total_tax_cents (PRD §3.9)."""
    if record["status"] == "DRAFT":
        lines, total = ifta_service.compute(
            record["fleet_account_id"], record["_period_start_dt"], record["_period_end_dt"])
    else:
        lines, total = record["jurisdiction_lines"], record["total_tax_cents"]

    out = _common(record)
    out.update({
        "fleet_account_id": record["fleet_account_id"],
        "quarter": record["quarter"],
        "period_start": record["period_start"],
        "period_end": record["period_end"],
        "jurisdiction_lines": lines,
        "total_tax_cents": total,
        "status": record["status"],
        "filed_at": record["filed_at"],
    })
    return out
