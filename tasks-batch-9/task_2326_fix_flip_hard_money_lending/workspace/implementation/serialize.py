"""Entity lookups and JSON serialization (field names from SCAFFOLD §1.1 / PRD §2)."""

import calc
from core import (
    ApiError, clock_date, dec_out, db, iso_date, iso_instant, not_found,
)

# ---------------------------------------------------------------------------
# Lookups (PRD 2.8 -- one not-found code per entity type)
# ---------------------------------------------------------------------------
def _find(table, rec_id, error_id):
    if not isinstance(rec_id, str):
        raise not_found(error_id)
    rec = table.get(rec_id)
    if rec is None:
        raise not_found(error_id)
    return rec


def find_borrower(rec_id):
    return _find(db.borrowers, rec_id, "ERR_BORROWER_NOT_FOUND")


def find_property(rec_id):
    return _find(db.properties, rec_id, "ERR_PROPERTY_NOT_FOUND")


def find_application(rec_id):
    return _find(db.applications, rec_id, "ERR_APPLICATION_NOT_FOUND")


def find_rehab_line_item(rec_id):
    return _find(db.rehab_line_items, rec_id, "ERR_REHAB_LINE_ITEM_NOT_FOUND")


def find_contractor(rec_id):
    return _find(db.contractors, rec_id, "ERR_CONTRACTOR_NOT_FOUND")


def find_loan(rec_id):
    return _find(db.loans, rec_id, "ERR_LOAN_NOT_FOUND")


def find_draw_request(rec_id):
    return _find(db.draw_requests, rec_id, "ERR_DRAW_REQUEST_NOT_FOUND")


def find_draw_line_item(rec_id):
    return _find(db.draw_line_items, rec_id, "ERR_DRAW_REQUEST_NOT_FOUND")


def find_inspection_visit(rec_id):
    return _find(db.inspection_visits, rec_id, "ERR_INSPECTION_VISIT_NOT_FOUND")


def find_lien_waiver(rec_id):
    return _find(db.lien_waivers, rec_id, "ERR_LIEN_WAIVER_NOT_FOUND")


def find_foreclosure_case(rec_id):
    return _find(db.foreclosure_cases, rec_id, "ERR_FORECLOSURE_CASE_NOT_FOUND")


# ---------------------------------------------------------------------------
# Collection helpers
# ---------------------------------------------------------------------------
def application_lines(application_id):
    return [l for l in db.rehab_line_items.values() if l["application_id"] == application_id]


def live_lines(application_id):
    return [l for l in application_lines(application_id)
            if l["status"] in calc.LIVE_SCOPE_STATUSES]


def approved_rehab_total(application_id):
    total = 0
    for line in application_lines(application_id):
        if line["status"] in ("APPROVED", "FULLY_RELEASED") and line["approved_cost_cents"] is not None:
            total += line["approved_cost_cents"]
    return total


def loan_draw_requests(loan_id):
    return [d for d in db.draw_requests.values() if d["loan_id"] == loan_id]


def request_allocations(draw_request_id):
    return [a for a in db.draw_line_items.values() if a["draw_request_id"] == draw_request_id]


def request_visits(draw_request_id):
    return [v for v in db.inspection_visits.values() if v["draw_request_id"] == draw_request_id]


def loan_accrual_periods(loan_id):
    return [p for p in db.accrual_periods.values() if p["loan_id"] == loan_id]


def loan_ledger_entries(loan_id):
    return [e for e in db.ledger_entries.values() if e["loan_id"] == loan_id]


def loan_lien_waivers(loan_id):
    return [w for w in db.lien_waivers.values() if w["loan_id"] == loan_id]


def loan_foreclosure_cases(loan_id):
    return [c for c in db.foreclosure_cases.values() if c["loan_id"] == loan_id]


def borrower_loans(borrower_id):
    return [l for l in db.loans.values() if l["borrower_id"] == borrower_id]


def borrower_applications(borrower_id):
    return [a for a in db.applications.values() if a["borrower_id"] == borrower_id]


def application_loan(application_id):
    for loan in db.loans.values():
        if loan["application_id"] == application_id:
            return loan
    return None


# ---------------------------------------------------------------------------
# Derived-field helpers that need cross-record reads
# ---------------------------------------------------------------------------
def sizing_stale(app):
    if app.get("_sizing_stale"):
        return True
    if app["status"] != "SIZED":
        return False
    prop = db.properties.get(app["property_id"])
    if prop is not None and app.get("sizing_arv_cents") is not None:
        if prop["arv_cents"] != app["sizing_arv_cents"]:
            return True
    if app.get("_sizing_rehab_total_cents") is not None:
        if approved_rehab_total(app["id"]) != app["_sizing_rehab_total_cents"]:
            return True
    return False


def _common(rec, journal=False):
    out = {"id": rec["id"], "created_at": rec["created_at"]}
    if not journal:
        out["updated_at"] = rec["updated_at"]
        out["version"] = rec["version"]
    return out


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------
def borrower_out(b):
    out = _common(b)
    out.update({
        "legal_entity_name": b["legal_entity_name"],
        "entity_type": b["entity_type"],
        "guarantor_name": b["guarantor_name"],
        "flips_last_24mo": b["flips_last_24mo"],
        "flips_lifetime": b["flips_lifetime"],
        "credit_score": b["credit_score"],
        "liquidity_cents": b["liquidity_cents"],
        "prior_default_count": b["prior_default_count"],
        "declared_target_loan_cents": b["declared_target_loan_cents"],
        "intake_experience_score": dec_out(b["intake_experience_score"], 2),
        "recertified_experience_score": dec_out(b["recertified_experience_score"], 2),
        "recertified_at": b["recertified_at"],
        "effective_experience_score": dec_out(calc.effective_score(b), 2),
        "experience_tier": calc.experience_tier(b),
        "guarantee_status": b["guarantee_status"],
        "guarantee_effective_date": iso_date(b["guarantee_effective_date"]),
        "status": b["status"],
        "suspension_reason": b["suspension_reason"],
    })
    return out


def property_out(p):
    out = _common(p)
    out.update({
        "address_line": p["address_line"],
        "county_code": p["county_code"],
        "purchase_price_cents": p["purchase_price_cents"],
        "as_is_value_cents": p["as_is_value_cents"],
        "arv_cents": p["arv_cents"],
        "appraisal_date": iso_date(p["appraisal_date"]),
        "status": p["status"],
        "valuation_revision_count": p["valuation_revision_count"],
    })
    return out


def application_out(a):
    out = _common(a)
    out.update({
        "borrower_id": a["borrower_id"],
        "property_id": a["property_id"],
        "term_months": a["term_months"],
        "quoted_rate_bps": a["quoted_rate_bps"],
        "interest_reserve_months": a["interest_reserve_months"],
        "day_count_convention": a["day_count_convention"],
        "intake_experience_score": dec_out(a["intake_experience_score"], 2),
        "pricing_tier": a["pricing_tier"],
        "approved_rehab_total_cents": a["approved_rehab_total_cents"],
        "cap_purchase_advance_cents": a["cap_purchase_advance_cents"],
        "cap_ltc_cents": a["cap_ltc_cents"],
        "cap_ltarv_cents": a["cap_ltarv_cents"],
        "max_total_loan_cents": a["max_total_loan_cents"],
        "sized_committed_amount_cents": a["sized_committed_amount_cents"],
        "sized_initial_funding_cents": a["sized_initial_funding_cents"],
        "sized_interest_reserve_cents": a["sized_interest_reserve_cents"],
        "sizing_arv_cents": a["sizing_arv_cents"],
        "sizing_rate_bps": a["sizing_rate_bps"],
        "sizing_stale": sizing_stale(a),
        "approved_loan_amount_cents": a["approved_loan_amount_cents"],
        "approved_rate_bps": a["approved_rate_bps"],
        "alloc_initial_funding_cents": a["alloc_initial_funding_cents"],
        "alloc_interest_reserve_cents": a["alloc_interest_reserve_cents"],
        "alloc_rehab_holdback_cents": a["alloc_rehab_holdback_cents"],
        "status": a["status"],
        "decline_reason": a["decline_reason"],
    })
    return out


def rehab_line_item_out(l):
    out = _common(l)
    out.update({
        "application_id": l["application_id"],
        "contractor_id": l["contractor_id"],
        "scope_code": l["scope_code"],
        "description": l["description"],
        "cost_cents": l["cost_cents"],
        "approved_cost_cents": l["approved_cost_cents"],
        "released_cents": l["released_cents"],
        "released_percent": dec_out(calc.released_percent(l), 4),
        "status": l["status"],
        "revision_round": l["revision_round"],
        "reviewer_note": l["reviewer_note"],
    })
    return out


def contractor_out(c):
    out = _common(c)
    coverage = calc.collected_waiver_coverage_cents(c["id"])
    released = calc.released_to_contractor_cents(c["id"])
    out.update({
        "business_name": c["business_name"],
        "license_number": c["license_number"],
        "license_expires_on": iso_date(c["license_expires_on"]),
        "w9_on_file": c["w9_on_file"],
        "joint_check_required": c["joint_check_required"],
        "license_status": calc.license_status(c),
        "collected_waiver_coverage_cents": coverage,
        "released_to_contractor_cents": released,
        "open_waiver_headroom_cents": coverage - released,
        "payable": calc.payable(c),
    })
    return out


def loan_out(loan):
    out = _common(loan)
    out.update({
        "application_id": loan["application_id"],
        "borrower_id": loan["borrower_id"],
        "closing_date": iso_date(loan["closing_date"]),
        "maturity_date": iso_date(loan["maturity_date"]),
        "term_months": loan["term_months"],
        "note_rate_bps": loan["note_rate_bps"],
        "default_rate_bps": loan["default_rate_bps"],
        "day_count_convention": loan["day_count_convention"],
        "committed_amount_cents": loan["committed_amount_cents"],
        "funded_principal_cents": loan["funded_principal_cents"],
        "repaid_principal_cents": loan["repaid_principal_cents"],
        "reserved_release_cents": loan["reserved_release_cents"],
        "undisbursed_holdback_cents": loan["undisbursed_holdback_cents"],
        "interest_reserve_balance_cents": loan["interest_reserve_balance_cents"],
        "interest_reserve_funded_cents": loan["interest_reserve_funded_cents"],
        "decommitted_holdback_cents": loan["decommitted_holdback_cents"],
        "accrued_interest_unpaid_cents": loan["accrued_interest_unpaid_cents"],
        "fee_balance_cents": loan["fee_balance_cents"],
        "available_rehab_pool_cents": calc.available_rehab_pool_cents(loan),
        "commitment_balance_check_cents": calc.commitment_balance_check_cents(loan),
        "last_accrual_through": iso_date(loan["last_accrual_through"]),
        "delinquent_since": iso_date(loan["delinquent_since"]),
        "default_effective_date": iso_date(loan["default_effective_date"]),
        "extension_count": loan["extension_count"],
        "extension_months_total": loan["extension_months_total"],
        "payment_status": loan["payment_status"],
        "construction_status": loan["construction_status"],
        "exit_status": loan["exit_status"],
        "days_on_market": calc.days_on_market(loan),
        "exit_watch_flag": calc.exit_watch_flag(loan),
        "payoff_quote_cents": calc.payoff_quote(loan, clock_date()),
        "recovery_cents": loan["recovery_cents"],
        "charge_off_cents": loan["charge_off_cents"],
        "surplus_returned_cents": loan["surplus_returned_cents"],
    })
    return out


def draw_request_out(d):
    out = _common(d)
    out.update({
        "loan_id": d["loan_id"],
        "sequence_number": d["sequence_number"],
        "verification_method": d["verification_method"],
        "photo_count": d["photo_count"],
        "requested_total_cents": d["requested_total_cents"],
        "approved_release_cents": d["approved_release_cents"],
        "status": d["status"],
        "reviewed_by_user_id": d["reviewed_by_user_id"],
        "funded_by_user_id": d["funded_by_user_id"],
        "funded_at": d["funded_at"],
        "superseded_by_draw_request_id": d["superseded_by_draw_request_id"],
    })
    return out


def draw_line_item_out(a):
    out = _common(a)
    out.update({
        "draw_request_id": a["draw_request_id"],
        "rehab_line_item_id": a["rehab_line_item_id"],
        "claimed_percent_complete": dec_out(a["claimed_percent_complete"], 2),
        "verified_percent_complete": dec_out(a["verified_percent_complete"], 2),
        "effective_percent_complete": dec_out(a["effective_percent_complete"], 2),
        "requested_amount_cents": a["requested_amount_cents"],
        "approved_amount_cents": a["approved_amount_cents"],
        "released_cents": a["released_cents"],
    })
    return out


def inspection_visit_out(v):
    out = _common(v)
    out.update({
        "draw_request_id": v["draw_request_id"],
        "inspector_id": v["inspector_id"],
        "window_start": iso_instant(v["window_start"]),
        "window_end": iso_instant(v["window_end"]),
        "status": v["status"],
        "reported_at": v["reported_at"],
        "site_notes": v["site_notes"],
    })
    return out


def lien_waiver_out(w):
    out = _common(w)
    out.update({
        "loan_id": w["loan_id"],
        "contractor_id": w["contractor_id"],
        "waiver_type": w["waiver_type"],
        "amount_covered_cents": w["amount_covered_cents"],
        "through_date": iso_date(w["through_date"]),
        "status": w["status"],
        "counts_toward_coverage": calc.counts_toward_coverage(w),
    })
    return out


def ledger_entry_out(e):
    out = _common(e, journal=True)
    out.update({
        "loan_id": e["loan_id"],
        "entry_type": e["entry_type"],
        "amount_cents": e["amount_cents"],
        "effective_date": iso_date(e["effective_date"]),
        "memo": e["memo"],
        "source_ref": e["source_ref"],
    })
    return out


def accrual_period_out(p):
    out = _common(p, journal=True)
    out.update({
        "loan_id": p["loan_id"],
        "period_start": iso_date(p["period_start"]),
        "period_end": iso_date(p["period_end"]),
        "day_count": p["day_count"],
        "note_rate_days": p["note_rate_days"],
        "default_rate_days": p["default_rate_days"],
        "principal_snapshot_cents": p["principal_snapshot_cents"],
        "note_rate_interest_cents": p["note_rate_interest_cents"],
        "default_rate_interest_cents": p["default_rate_interest_cents"],
        "interest_accrued_cents": p["interest_accrued_cents"],
        "swept_from_reserve_cents": p["swept_from_reserve_cents"],
        "unpaid_added_cents": p["unpaid_added_cents"],
    })
    return out


def exit_milestone_out(m):
    out = _common(m, journal=True)
    out.update({
        "loan_id": m["loan_id"],
        "milestone_type": m["milestone_type"],
        "effective_date": iso_date(m["effective_date"]),
        "listing_price_cents": m["listing_price_cents"],
        "lender_name": m["lender_name"],
        "note": m["note"],
        "derived_exit_status": m["derived_exit_status"],
    })
    return out


def foreclosure_case_out(c):
    out = _common(c)
    out.update({
        "loan_id": c["loan_id"],
        "notice_date": iso_date(c["notice_date"]),
        "county_code": c["county_code"],
        "redemption_expires_on": iso_date(c["redemption_expires_on"]),
        "takeover_date": iso_date(c["takeover_date"]),
        "completion_budget_cents": c["completion_budget_cents"],
        "completion_advanced_cents": c["completion_advanced_cents"],
        "sale_price_cents": c["sale_price_cents"],
        "selling_costs_cents": c["selling_costs_cents"],
        "net_proceeds_cents": c["net_proceeds_cents"],
        "recovery_cents": c["recovery_cents"],
        "charge_off_cents": c["charge_off_cents"],
        "surplus_returned_cents": c["surplus_returned_cents"],
        "status": c["status"],
    })
    return out
