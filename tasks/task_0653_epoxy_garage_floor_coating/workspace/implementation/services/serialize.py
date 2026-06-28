"""Entity -> JSON view serializers.

Common fields (PRD §2.4): id, created_at, updated_at, version on every entity.
Datetime fields are ISO 8601 UTC with three fractional digits.
"""
from db import iso_ms


def _common(row):
    return {
        "id": row["id"],
        "created_at": iso_ms(row["created_at"]),
        "updated_at": iso_ms(row["updated_at"]),
        "version": row["version"],
    }


def coating_system(row):
    out = _common(row)
    out.update({
        "name": row["name"],
        "family": row["family"],
        "sku": row["sku"],
        "requires_metallic_certified_crew": row["requires_metallic_certified_crew"],
        "active": row["active"],
    })
    return out


def color_option(row):
    out = _common(row)
    out.update({
        "coating_system_id": row["coating_system_id"],
        "name": row["name"],
        "flake_blend_code": row["flake_blend_code"],
        "active": row["active"],
    })
    return out


def financing_plan(row):
    out = _common(row)
    out.update({
        "name": row["name"],
        "apr_bps": row["apr_bps"],
        "term_months": row["term_months"],
        "min_principal_cents": row["min_principal_cents"],
        "active": row["active"],
    })
    return out


def crew(row):
    out = _common(row)
    out.update({
        "name": row["name"],
        "metallic_certified": row["metallic_certified"],
        "max_sqft_per_day": row["max_sqft_per_day"],
        "active": row["active"],
    })
    return out


def customer(row):
    out = _common(row)
    out.update({
        "full_name": row["full_name"],
        "email": row["email"],
        "referral_code": row["referral_code"],
        "account_credit_balance_cents": row["account_credit_balance_cents"],
    })
    return out


def project(row):
    out = _common(row)
    out.update({
        "customer_id": row["customer_id"],
        "site_zip": row["site_zip"],
        "sales_status": row["sales_status"],
        "build_status": row["build_status"],
        "accepted_quote_id": row["accepted_quote_id"],
        "referral_id": row["referral_id"],
    })
    return out


def assessment(row):
    out = _common(row)
    out.update({
        "project_id": row["project_id"],
        "measured_sqft": row["measured_sqft"],
        "oil_stain_pct": row["oil_stain_pct"],
        "crack_density": row["crack_density"],
        "crack_linear_ft": row["crack_linear_ft"],
        "spalling": row["spalling"],
        "moisture_pct": row["moisture_pct"],
        "condition_score": row["condition_score"],
        "prep_tier": row["prep_tier"],
        "billable_crack_ft": row["billable_crack_ft"],
        "status": row["status"],
    })
    return out


def quote(row):
    out = _common(row)
    out.update({
        "project_id": row["project_id"],
        "assessment_id": row["assessment_id"],
        "coating_system_id": row["coating_system_id"],
        "color_option_id": row["color_option_id"],
        "financing_plan_id": row["financing_plan_id"],
        "install_season": row["install_season"],
        "variant": row["variant"],
        "priced_sqft": row["priced_sqft"],
        "system_material_cents": row["system_material_cents"],
        "prep_labor_cents": row["prep_labor_cents"],
        "volume_discount_pct_bps": row["volume_discount_pct_bps"],
        "discount_cents": row["discount_cents"],
        "mobilization_cents": row["mobilization_cents"],
        "grand_total_cents": row["grand_total_cents"],
        "monthly_payment_cents": row["monthly_payment_cents"],
        "status": row["status"],
    })
    return out


def _iso_or_none(v):
    return iso_ms(v) if v is not None else None


def install_job(row):
    out = _common(row)
    out.update({
        "project_id": row["project_id"],
        "crew_id": row["crew_id"],
        "install_date": _iso_or_none(row["install_date"]),
        "install_end": _iso_or_none(row["install_end"]),
        "foot_traffic_ok_at": _iso_or_none(row["foot_traffic_ok_at"]),
        "vehicle_traffic_ok_at": _iso_or_none(row["vehicle_traffic_ok_at"]),
        "as_measured_sqft": row["as_measured_sqft"],
        "as_measured_crack_ft": row["as_measured_crack_ft"],
        "status": row["status"],
    })
    return out


def warranty(row):
    out = _common(row)
    out.update({
        "project_id": row["project_id"],
        "install_job_id": row["install_job_id"],
        "covered_install_price_cents": row["covered_install_price_cents"],
        "term_months": row["term_months"],
        "coverage_start_at": _iso_or_none(row["coverage_start_at"]),
        "status": row["status"],
    })
    return out


def warranty_claim(row):
    out = _common(row)
    out.update({
        "warranty_id": row["warranty_id"],
        "defect_type": row["defect_type"],
        "reported_at": _iso_or_none(row["reported_at"]),
        "months_elapsed": row["months_elapsed"],
        "prorated_credit_cents": row["prorated_credit_cents"],
        "revision_rounds": row["revision_rounds"],
        "status": row["status"],
    })
    return out


def referral(row):
    out = _common(row)
    out.update({
        "referrer_customer_id": row["referrer_customer_id"],
        "referred_customer_id": row["referred_customer_id"],
        "project_id": row["project_id"],
        "credit_cents": row["credit_cents"],
        "status": row["status"],
    })
    return out
