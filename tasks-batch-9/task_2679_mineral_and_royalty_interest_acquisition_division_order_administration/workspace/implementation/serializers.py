"""Output representations.  Field names and their presence come straight from
the SCAFFOLD entity table; a TitleChainEntry deliberately carries neither
`updated_at` nor `version` (PRD 2.4)."""

from decimal import Decimal

import calc
from db import db


def num(value):
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    return value


def _common(row, out):
    out["id"] = row["id"]
    out["created_at"] = row["created_at"]
    out["updated_at"] = row["updated_at"]
    out["version"] = row["version"]
    return out


# --------------------------------------------------------------------------
def tract_out(row):
    return _common(row, {
        "county": row["county"],
        "state_code": row["state_code"],
        "gross_acres": num(row["gross_acres"]),
        "operator_activity_tier": row["operator_activity_tier"],
        "title_status": row["title_status"],
        "net_mineral_acres_certified": num(row["net_mineral_acres_certified"]),
        "existing_burden_fraction": num(row["existing_burden_fraction"]),
        "chain_entry_count": row["chain_entry_count"],
        "certified_at": row["certified_at"],
    })


def chain_entry_out(row):
    return {
        "id": row["id"],
        "tract_id": row["tract_id"],
        "instrument_type": row["instrument_type"],
        "instrument_date": row["instrument_date"],
        "conveyed_fraction": num(row["conveyed_fraction"]),
        "conveyed_acres": num(row["conveyed_acres"]),
        "county_book_page": row["county_book_page"],
        "grantor_name": row["grantor_name"],
        "grantee_name": row["grantee_name"],
        "created_at": row["created_at"],
    }


def owner_suspense_total(owner_id):
    total = Decimal("0.00")
    for account in db.suspense_accounts.values():
        if account["royalty_owner_id"] != owner_id:
            continue
        if account["suspense_status"] != "ACCRUING":
            continue
        total += suspense_accrued(account)
    return calc.q2(total)


def owner_out(row):
    return _common(row, {
        "legal_name": row["legal_name"],
        "state_code": row["state_code"],
        "contact_status": row["contact_status"],
        "tax_id_on_file": row["tax_id_on_file"],
        "mailing_address": row["mailing_address"],
        "suspense_total": num(owner_suspense_total(row["id"])),
    })


def interest_out(row):
    return _common(row, {
        "tract_id": row["tract_id"],
        "seller_owner_id": row["seller_owner_id"],
        "seller_share_fraction": num(row["seller_share_fraction"]),
        "lease_royalty_rate": num(row["lease_royalty_rate"]),
        "undeveloped_net_acres": num(row["undeveloped_net_acres"]),
        "net_mineral_acres": num(row["net_mineral_acres"]),
        "existing_burden_fraction": num(row["existing_burden_fraction"]),
        "interest_status": row["interest_status"],
        "current_valuation_id": row["current_valuation_id"],
        "acquiring_deed_book_page": row["acquiring_deed_book_page"],
    })


def valuation_out(row):
    return _common(row, {
        "mineral_interest_id": row["mineral_interest_id"],
        "current_monthly_net_revenue": num(row["current_monthly_net_revenue"]),
        "annual_decline_rate": num(row["annual_decline_rate"]),
        "undeveloped_net_acres": num(row["undeveloped_net_acres"]),
        "operator_activity_tier": row["operator_activity_tier"],
        "pdp_pv": num(row["pdp_pv"]),
        "undeveloped_pv": num(row["undeveloped_pv"]),
        "bid_floor": num(row["bid_floor"]),
        "max_bid": num(row["max_bid"]),
        "valuation_status": row["valuation_status"],
        "approved_by_user_id": row["approved_by_user_id"],
    })


def offer_out(row):
    return _common(row, {
        "mineral_interest_id": row["mineral_interest_id"],
        "offer_amount": num(row["offer_amount"]),
        "expires_on": row["expires_on"],
        "current_amount": num(row["current_amount"]),
        "last_counter_amount": num(row["last_counter_amount"]),
        "counter_round_count": row["counter_round_count"],
        "offer_status": row["offer_status"],
        "issued_by_user_id": row["issued_by_user_id"],
        "accepted_at": row["accepted_at"],
        "rejection_reason": row.get("rejection_reason"),
    })


def psa_out(row):
    return _common(row, {
        "offer_letter_id": row["offer_letter_id"],
        "mineral_interest_id": row["mineral_interest_id"],
        "tract_id": row["tract_id"],
        "purchase_price": num(row["purchase_price"]),
        "effective_date": row["effective_date"],
        "curative_days": row["curative_days"],
        "curative_deadline": row["curative_deadline"],
        "window_end_with_buffer": row["window_end_with_buffer"],
        "individual_defect_threshold": num(row["individual_defect_threshold"]),
        "aggregate_defect_basket": num(row["aggregate_defect_basket"]),
        "defect_adjustment_amount": num(row["defect_adjustment_amount"]),
        "adjusted_purchase_price": num(row["adjusted_purchase_price"]),
        "curative_status": row["curative_status"],
        "funding_status": row["funding_status"],
        "psa_status": row["psa_status"],
        "wire_reference": row["wire_reference"],
        "recording_county": row["recording_county"],
        "recorded_book_page": row["recorded_book_page"],
        "recording_date": row["recording_date"],
        "created_by_user_id": row["created_by_user_id"],
    })


def defect_out(row):
    return _common(row, {
        "psa_id": row["psa_id"],
        "defect_type": row["defect_type"],
        "affected_nma": num(row["affected_nma"]),
        "description": row["description"],
        "allocated_value": num(row["allocated_value"]),
        "net_defect_value": num(row["net_defect_value"]),
        "defect_status": row["defect_status"],
        "cure_round_count": row["cure_round_count"],
        "cure_instrument_book_page": row["cure_instrument_book_page"],
        "raised_by_user_id": row["raised_by_user_id"],
        "waived_by_user_id": row["waived_by_user_id"],
        "decision_note": row.get("decision_note"),
        "waiver_note": row.get("waiver_note"),
    })


def unit_out(row):
    return _common(row, {
        "unit_name": row["unit_name"],
        "formation": row["formation"],
        "state_code": row["state_code"],
        "unit_gross_acres": num(row["unit_gross_acres"]),
        "royalty_rate_cap": num(row["royalty_rate_cap"]),
        "pugh_clause_active": row["pugh_clause_active"],
        "pugh_deadline": row["pugh_deadline"],
        "producing_depth_count": row["producing_depth_count"],
        "total_depth_count": row["total_depth_count"],
        "unallocated_acres": num(row["unallocated_acres"]),
        "active_allocation_count": row["active_allocation_count"],
        "operator_user_id": row["operator_user_id"],
    })


def allocation_out(row):
    return _common(row, {
        "unit_id": row["unit_id"],
        "tract_id": row["tract_id"],
        "allocated_acres": num(row["allocated_acres"]),
        "effective_from": row["effective_from"],
        "effective_to": row["effective_to"],
        "pooling_election": row["pooling_election"],
        "allocation_status": row["allocation_status"],
        "released_acres": num(row["released_acres"]),
        "termination_reason": row["termination_reason"],
    })


def order_out(row):
    return _common(row, {
        "mineral_interest_id": row["mineral_interest_id"],
        "unit_id": row["unit_id"],
        "royalty_owner_id": row["royalty_owner_id"],
        "allocation_id": row["allocation_id"],
        "expected_decimal": num(row["expected_decimal"]),
        "pinned_decimal": num(row["pinned_decimal"]),
        "operator_decimal": num(row["operator_decimal"]),
        "do_status": row["do_status"],
        "dispute_reason": row["dispute_reason"],
        "effective_production_month": row["effective_production_month"],
        "cumulative_variance_amount": num(row["cumulative_variance_amount"]),
        "paid_net_total": num(row["paid_net_total"]),
        "correction_round_count": row["correction_round_count"],
        "created_by_user_id": row["created_by_user_id"],
    })


def detail_out(row):
    return _common(row, {
        "division_order_id": row["division_order_id"],
        "production_month": row["production_month"],
        "product_code": row["product_code"],
        "gross_volume": num(row["gross_volume"]),
        "gross_value": num(row["gross_value"]),
        "operator_decimal_used": num(row["operator_decimal_used"]),
        "reported_gross_royalty": num(row["reported_gross_royalty"]),
        "severance_tax_rate": num(row["severance_tax_rate"]),
        "severance_tax_amount": num(row["severance_tax_amount"]),
        "net_amount": num(row["net_amount"]),
        "expected_gross_royalty": num(row["expected_gross_royalty"]),
        "expected_net_amount": num(row["expected_net_amount"]),
        "variance_amount": num(row["variance_amount"]),
        "audit_decimal": num(row["audit_decimal"]),
        "audit_gross_royalty": num(row["audit_gross_royalty"]),
        "audit_net_amount": num(row["audit_net_amount"]),
        "audit_variance_amount": num(row["audit_variance_amount"]),
        "check_status": row["check_status"],
    })


# --------------------------------------------------------------------------
# suspense figures are live against the logical clock while ACCRUING and are
# frozen once the account reaches a terminal posture (PRD 3.9).
# --------------------------------------------------------------------------
def suspense_held_details(account):
    order_id = account["division_order_id"]
    return [d for d in db.revenue_details.values()
            if d["division_order_id"] == order_id and d["check_status"] == "VARIANCE_HELD"]


def suspense_accrued(account):
    if account["suspense_status"] != "ACCRUING":
        return account["accrued_amount"]
    total = Decimal("0.00")
    for detail in suspense_held_details(account):
        total += detail["net_amount"]
    return calc.q2(total)


def refresh_suspense(account):
    """Recompute the four clock-sensitive figures in place."""
    if account["suspense_status"] != "ACCRUING":
        return account
    held = suspense_held_details(account)
    total = Decimal("0.00")
    for detail in held:
        total += detail["net_amount"]
    account["accrued_amount"] = calc.q2(total)
    account["held_detail_count"] = len(held)
    account["months_held"] = calc.months_between(account["first_suspended_month"])
    account["interest_accrued"] = calc.suspense_interest(
        account["accrued_amount"], account["months_held"])
    account["release_amount"] = calc.q2(
        account["accrued_amount"] + account["interest_accrued"])
    return account


def suspense_out(row):
    refresh_suspense(row)
    return _common(row, {
        "division_order_id": row["division_order_id"],
        "royalty_owner_id": row["royalty_owner_id"],
        "suspense_reason": row["suspense_reason"],
        "accrued_amount": num(row["accrued_amount"]),
        "held_detail_count": row["held_detail_count"],
        "first_suspended_month": row["first_suspended_month"],
        "months_held": row["months_held"],
        "interest_accrued": num(row["interest_accrued"]),
        "release_amount": num(row["release_amount"]),
        "suspense_status": row["suspense_status"],
        "escheat_state_code": row["escheat_state_code"],
        "released_by_user_id": row["released_by_user_id"],
    })


def tax_statement_out(stmt):
    return {
        "royalty_owner_id": stmt["royalty_owner_id"],
        "tax_year": stmt["tax_year"],
        "gross_royalty": num(stmt["gross_royalty"]),
        "severance_tax_withheld": num(stmt["severance_tax_withheld"]),
        "taxable_before_depletion": num(stmt["taxable_before_depletion"]),
        "depletion_allowance": num(stmt["depletion_allowance"]),
        "net_taxable": num(stmt["net_taxable"]),
        "detail_count": stmt["detail_count"],
    }
