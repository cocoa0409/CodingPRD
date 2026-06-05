"""Convert internal records into API output dicts.

Internal bookkeeping keys (those prefixed with "_") are stripped. Each entity
serializer lists fields exactly as the PRD/scaffold define them, so output never
leaks internal state.
"""


def _common(rec):
    return {
        "id": rec["id"],
        "created_at": rec["created_at"],
        "updated_at": rec["updated_at"],
        "version": rec["version"],
    }


def fare_product_out(r):
    out = _common(r)
    out.update({
        "zone_code": r["zone_code"],
        "base_fare_cents": r["base_fare_cents"],
        "daily_cap_cents": r["daily_cap_cents"],
        "weekly_cap_cents": r["weekly_cap_cents"],
        "transfer_window_minutes": r["transfer_window_minutes"],
        "transfer_discount_pct": r["transfer_discount_pct"],
        "reduced_fare_pct": r["reduced_fare_pct"],
        "status": r["status"],
    })
    return out


def rider_out(r):
    out = _common(r)
    out.update({
        "email": r["email"],
        "full_name": r["full_name"],
        "home_zone_code": r["home_zone_code"],
        "income_tier": r["income_tier"],
        "low_income_discount_pct": r["low_income_discount_pct"],
        "status": r["status"],
    })
    return out


def funding_source_out(r):
    out = _common(r)
    out.update({
        "rider_id": r["rider_id"],
        "source_type": r["source_type"],
        "prepaid_balance_cents": r["prepaid_balance_cents"],
        "is_default": r["is_default"],
        "status": r["status"],
    })
    return out


def reduced_fare_card_out(r):
    out = _common(r)
    out.update({
        "rider_id": r["rider_id"],
        "program_code": r["program_code"],
        "expires_on": r["expires_on"],
        "verification_token": r["verification_token"],
        "status": r["status"],
    })
    return out


def benefit_allocation_out(r):
    out = _common(r)
    out.update({
        "rider_id": r["rider_id"],
        "employer_ref": r["employer_ref"],
        "period_month": r["period_month"],
        "allocated_cents": r["allocated_cents"],
        "consumed_cents": r["consumed_cents"],
        "status": r["status"],
    })
    return out


def fare_week_out(r):
    out = _common(r)
    out.update({
        "rider_id": r["rider_id"],
        "week_start_date": r["week_start_date"],
        "zone_code": r["zone_code"],
        "charged_total_cents": r["charged_total_cents"],
        "status": r["status"],
    })
    return out


def tap_out(r):
    out = _common(r)
    out.update({
        "rider_id": r["rider_id"],
        "fare_week_id": r["fare_week_id"],
        "funding_source_id": r["funding_source_id"],
        "benefit_allocation_id": r["benefit_allocation_id"],
        "tapped_at": r["tapped_at"],
        "list_fare_cents": r["list_fare_cents"],
        "transfer_discount_cents": r["transfer_discount_cents"],
        "cap_credit_cents": r["cap_credit_cents"],
        "charge_cents": r["charge_cents"],
        "benefit_applied_cents": r["benefit_applied_cents"],
        "status": r["status"],
    })
    return out
