"""Per-entity serializers.

Aggregate figures (pool ledger, issue undrawn balance, allocation delivered
credit, project designation counters, sponsor and investor ledgers) are
re-derived here from the live rows, so they can never drift from the stored
inputs they summarise.  Snapshots and stamped values are read from the row.
"""

import calc
from store import db

_COMMON = ("id", "created_at", "updated_at", "version")


def _base(row):
    return {key: row.get(key) for key in _COMMON}


def developer(row):
    out = _base(row)
    out.update({
        "name": row.get("name"),
        "tax_id": row.get("tax_id"),
        "contact_email": row.get("contact_email"),
        "status": row.get("status"),
        "sanction_reason": row.get("sanction_reason"),
        "active_project_count": calc.developer_active_project_count(row),
    })
    return out


def investor(row):
    out = _base(row)
    out.update({
        "name": row.get("name"),
        "tax_id": row.get("tax_id"),
        "investor_type": row.get("investor_type"),
        "total_credit_accepted_cents": row.get("total_credit_accepted_cents") or 0,
    })
    return out


def cap_pool(row):
    out = _base(row)
    out.update({
        "program_year": row.get("program_year"),
        "base_cap_cents": row.get("base_cap_cents"),
        "carryforward_cents": row.get("carryforward_cents"),
    })
    out.update(calc.pool_ledger(row))
    return out


def project(row):
    out = _base(row)
    out.update({
        "developer_id": row.get("developer_id"),
        "name": row.get("name"),
        "total_units": row.get("total_units"),
        "total_floor_space_sqft": row.get("total_floor_space_sqft"),
        "land_cost_cents": row.get("land_cost_cents"),
        "depreciable_basis_cents": row.get("depreciable_basis_cents"),
        "set_aside_election": row.get("set_aside_election"),
        "aggregate_basis_cents": row.get("aggregate_basis_cents"),
        "development_status": row.get("development_status"),
        "compliance_status": row.get("compliance_status"),
    })
    out.update(calc.applicable_fraction(row))
    ratio = calc.set_aside_compliance_ratio(row)
    out["set_aside_ratio_bps"] = ratio["set_aside_ratio_bps"]
    out["set_aside_satisfied"] = ratio["set_aside_satisfied"]
    out.update({
        "provisional_fifty_percent_ratio_bps": row.get("provisional_fifty_percent_ratio_bps"),
        "final_fifty_percent_ratio_bps": row.get("final_fifty_percent_ratio_bps"),
        "automatic_credit_triggered": bool(row.get("automatic_credit_triggered")),
        "placed_in_service_date": row.get("placed_in_service_date"),
        "compliance_start_date": row.get("compliance_start_date"),
        "compliance_end_date": row.get("compliance_end_date"),
        "extended_use_end_date": row.get("extended_use_end_date"),
        "volume_cap_deferral_count": row.get("volume_cap_deferral_count") or 0,
        "financing_stalled": bool(row.get("financing_stalled")),
    })
    return out


def allocation(row):
    out = _base(row)
    out.update({
        "project_id": row.get("project_id"),
        "cap_pool_id": row.get("cap_pool_id"),
        "requested_amount_cents": row.get("requested_amount_cents"),
        "requested_closing_date": row.get("requested_closing_date"),
        "status": row.get("status"),
        "awarded_amount_cents": row.get("awarded_amount_cents"),
        "expiry_date": row.get("expiry_date"),
        "denial_reason": row.get("denial_reason"),
        "return_reason": row.get("return_reason"),
        "decided_by_user_id": row.get("decided_by_user_id"),
        "decision_round": row.get("decision_round"),
    })
    return out


def bond_issue(row):
    out = _base(row)
    out.update({
        "project_id": row.get("project_id"),
        "volume_cap_allocation_id": row.get("volume_cap_allocation_id"),
        "eligible_cost_cents": row.get("eligible_cost_cents"),
        "capitalized_interest_cents": row.get("capitalized_interest_cents"),
        "bond_yield_bps": row.get("bond_yield_bps"),
        "investment_yield_bps": row.get("investment_yield_bps"),
        "issuance_allowance_cents": row.get("issuance_allowance_cents"),
        "par_amount_cents": row.get("par_amount_cents"),
        "status": row.get("status"),
        "closing_date": row.get("closing_date"),
    })
    out.update(calc.issue_ledger(row))
    out.update({
        "negative_arbitrage_cents": row.get("negative_arbitrage_cents") or 0,
        "negative_arbitrage_allowance_cents": row.get("negative_arbitrage_allowance_cents"),
        "operating_months": [dict(m) for m in (row.get("operating_months") or [])],
        "dscr_bps": row.get("dscr_bps"),
        "dscr_basis": row.get("dscr_basis"),
        "min_occupancy_bps": row.get("min_occupancy_bps"),
        "conversion_date": row.get("conversion_date"),
        "redemption_date": row.get("redemption_date"),
    })
    return out


def draw(row):
    out = _base(row)
    out.update({
        "bond_issue_id": row.get("bond_issue_id"),
        "draw_number": row.get("draw_number"),
        "period_start": row.get("period_start"),
        "period_end": row.get("period_end"),
        "requested_amount_cents": row.get("requested_amount_cents"),
        "approved_amount_cents": row.get("approved_amount_cents"),
        "status": row.get("status"),
        "funding_date": row.get("funding_date"),
        "rejection_reason": row.get("rejection_reason"),
        "void_reason": row.get("void_reason"),
        "negative_arbitrage_accrual_cents": row.get("negative_arbitrage_accrual_cents") or 0,
    })
    return out


def unit(row):
    out = _base(row)
    out.update({
        "project_id": row.get("project_id"),
        "unit_number": row.get("unit_number"),
        "bedroom_count": row.get("bedroom_count"),
        "floor_space_sqft": row.get("floor_space_sqft"),
        "designation": row.get("designation"),
        "ami_percent": row.get("ami_percent"),
        "utility_allowance_cents": row.get("utility_allowance_cents"),
        "market_rent_cents": row.get("market_rent_cents"),
        "imputed_household_size": calc.imputed_household_size(row.get("bedroom_count")),
        "restricted_rent_cents": row.get("restricted_rent_cents"),
        "status": row.get("status"),
    })
    return out


def agreement(row):
    out = _base(row)
    out.update({
        "project_id": row.get("project_id"),
        "set_aside_election": row.get("set_aside_election"),
        "compliance_period_years": row.get("compliance_period_years"),
        "extended_use_years": row.get("extended_use_years"),
        "recording_county": row.get("recording_county"),
        "status": row.get("status"),
        "instrument_number": row.get("instrument_number"),
        "recording_date": row.get("recording_date"),
        "amendment_count": row.get("amendment_count") or 0,
        "amendment_reason": row.get("amendment_reason"),
        "compliance_period_end_date": row.get("compliance_period_end_date"),
        "extended_use_end_date": row.get("extended_use_end_date"),
    })
    return out


def cost_cert(row):
    out = _base(row)
    out.update({
        "project_id": row.get("project_id"),
        "certified_land_cost_cents": row.get("certified_land_cost_cents"),
        "certified_depreciable_basis_cents": row.get("certified_depreciable_basis_cents"),
        "certified_eligible_basis_cents": row.get("certified_eligible_basis_cents"),
        "preparer_name": row.get("preparer_name"),
        "certified_aggregate_basis_cents": row.get("certified_aggregate_basis_cents"),
        "status": row.get("status"),
        "submission_round": row.get("submission_round") or 0,
        "deficiency_notes": row.get("deficiency_notes"),
        "reviewed_by_user_id": row.get("reviewed_by_user_id"),
        "accepted_at": row.get("accepted_at"),
    })
    return out


def credit_allocation(row):
    out = _base(row)
    out.update({
        "project_id": row.get("project_id"),
        "cost_certification_id": row.get("cost_certification_id"),
        "credit_percentage_bps": row.get("credit_percentage_bps"),
        "placed_in_service_date": row.get("placed_in_service_date"),
        "qualified_basis_cents": row.get("qualified_basis_cents"),
        "applicable_fraction_bps": row.get("applicable_fraction_bps"),
        "annual_credit_cents": row.get("annual_credit_cents"),
        "total_credit_cents": row.get("total_credit_cents"),
    })
    out.update(calc.allocation_ledger(row))
    out.update({
        "status": row.get("status"),
        "form_8609_number": row.get("form_8609_number"),
        "issued_by_user_id": row.get("issued_by_user_id"),
        "recapture_amount_cents": row.get("recapture_amount_cents") or 0,
    })
    return out


def delivery(row):
    out = _base(row)
    out.update({
        "credit_allocation_id": row.get("credit_allocation_id"),
        "investor_id": row.get("investor_id"),
        "requested_credit_cents": row.get("requested_credit_cents"),
        "capital_contribution_cents": row.get("capital_contribution_cents"),
        "delivered_credit_cents": row.get("delivered_credit_cents"),
        "price_per_credit_dollar_bps": row.get("price_per_credit_dollar_bps"),
        "status": row.get("status"),
        "accepted_at": row.get("accepted_at"),
        "rescind_reason": row.get("rescind_reason"),
    })
    return out


def report(row):
    out = _base(row)
    out.update({
        "project_id": row.get("project_id"),
        "reporting_year": row.get("reporting_year"),
        "restricted_units_occupied": row.get("restricted_units_occupied"),
        "total_units_occupied": row.get("total_units_occupied"),
        "average_ami_percent": row.get("average_ami_percent"),
        "status": row.get("status"),
        "achieved_set_aside_bps": row.get("achieved_set_aside_bps"),
        "shortfall_bps": row.get("shortfall_bps") or 0,
        "finding_notes": row.get("finding_notes"),
        "reviewed_by_user_id": row.get("reviewed_by_user_id"),
    })
    return out


def inspection(row):
    out = _base(row)
    out.update({
        "project_id": row.get("project_id"),
        "window_start": row.get("window_start"),
        "window_end": row.get("window_end"),
        "inspector_name": row.get("inspector_name"),
        "status": row.get("status"),
        "completed_date": row.get("completed_date"),
        "score": row.get("score"),
        "deficiency_count": row.get("deficiency_count"),
        "next_inspection_due_date": row.get("next_inspection_due_date"),
    })
    return out


SERIALIZERS = {
    "developers": developer,
    "investors": investor,
    "cap_pools": cap_pool,
    "projects": project,
    "allocations": allocation,
    "bond_issues": bond_issue,
    "draws": draw,
    "units": unit,
    "agreements": agreement,
    "cost_certs": cost_cert,
    "credit_allocations": credit_allocation,
    "deliveries": delivery,
    "reports": report,
    "inspections": inspection,
}


def serialize(collection_name, row):
    return SERIALIZERS[collection_name](row)


def collection(name):
    return getattr(db, name)
