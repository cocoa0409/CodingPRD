"""Derived (computed) fields and JSON serializers.

Computed fields are recomputed on every read rather than cached, which is what
makes Invariant M and Invariant G of PRD 2.8 hold "at every instant".
"""

from decimal import Decimal

import db
from services import calc


def num(value):
    """Render a gallons Decimal as a JSON number at two decimals."""
    if value is None:
        return None
    return float(calc.g2(value))


# --------------------------------------------------------------------------
# Row lookups.
# --------------------------------------------------------------------------
def licensee_returns(licensee_id):
    return [r for r in db.ordered(db.returns) if r["licensee_id"] == licensee_id]


def filed_returns(licensee_id):
    return [r for r in licensee_returns(licensee_id)
            if r["filing_status"] == "FILED"]


def filed_return_for_period(licensee_id, period_month):
    """The single FILED, non-superseded return of a filer for a period."""
    for r in db.ordered(db.returns):
        if (r["licensee_id"] == licensee_id
                and r["period_month"] == period_month
                and r["filing_status"] == "FILED"):
            return r
    return None


def return_schedules(return_id):
    return [s for s in db.ordered(db.schedules) if s["return_id"] == return_id]


def schedule_lines_of(schedule_id):
    return [l for l in db.ordered(db.schedule_lines)
            if l["schedule_id"] == schedule_id]


def line_return_id(line):
    schedule = db.schedules.get(line["schedule_id"])
    return schedule["return_id"] if schedule else None


def line_owner_licensee_id(line):
    schedule = db.schedules.get(line["schedule_id"])
    if not schedule:
        return None
    parent = db.returns.get(schedule["return_id"])
    return parent["licensee_id"] if parent else None


def schedule_owner_licensee_id(schedule):
    parent = db.returns.get(schedule["return_id"])
    return parent["licensee_id"] if parent else None


def schedule_gallons_sum(schedule_id):
    total = calc.ZERO
    for line in schedule_lines_of(schedule_id):
        total += line["gallons"]
    return calc.g2(total)


def basis_returns(licensee_id):
    """Newest up to three FILED returns: period_month DESC, created_at ASC."""
    rows = filed_returns(licensee_id)
    rows = sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))
    rows = sorted(rows, key=lambda r: r["period_month"], reverse=True)
    return rows[:3]


# --------------------------------------------------------------------------
# Licensee computed fields.
# --------------------------------------------------------------------------
def posted_bond_cents(licensee_id):
    return sum(int(b["amount_cents"]) for b in db.bonds.values()
               if b["licensee_id"] == licensee_id and b["status"] == "ACTIVE")


def bond_position(licensee):
    basis = basis_returns(licensee["id"])
    avg = calc.average_liability_cents(basis)
    required = calc.required_bond_cents(
        avg, licensee["license_type"], licensee["status"] == "SUSPENDED")
    posted = posted_bond_cents(licensee["id"])
    deficiency = max(0, required - posted)
    return {
        "avg_monthly_tax_liability_cents": avg,
        "required_bond_cents": required,
        "posted_bond_cents": posted,
        "bond_deficiency_cents": deficiency,
        "basis_return_count": len(basis),
    }


def balance_cents(licensee_id):
    return sum(int(e["amount_cents"]) for e in db.ledger_entries.values()
               if e["licensee_id"] == licensee_id)


def effective_taxable_gallons_ytd(licensee_id):
    year = db.now().strftime("%Y")
    total = calc.ZERO
    for r in filed_returns(licensee_id):
        if r["period_month"][:4] == year:
            total += r["taxable_gallons_total"] or calc.ZERO
    return calc.g2(total)


def dyed_violation_count(licensee_id):
    """Incremented by a penalty assessment, decremented by a dismissal."""
    return sum(1 for i in db.inspections.values()
               if i["inspected_licensee_id"] == licensee_id
               and i["dye_test_result"] == "POSITIVE"
               and i["status"] == "PENALTY_ASSESSED")


def late_filing_count(licensee_id):
    """A period counts late exactly once, on its original filing."""
    total = 0
    for r in licensee_returns(licensee_id):
        if r["amends_return_id"] is not None:
            continue
        if r["filing_status"] not in ("FILED", "SUPERSEDED"):
            continue
        if (r["days_late"] or 0) >= 1:
            total += 1
    return total


def open_audit_count(licensee_id):
    return sum(1 for c in db.audit_cases.values()
               if c["subject_licensee_id"] == licensee_id
               and c["case_status"] != "CLOSED")


def open_discrepancy_count(licensee_id):
    return sum(1 for d in db.discrepancies.values()
               if d["distributor_licensee_id"] == licensee_id
               and d["status"] in calc.OPEN_DISCREPANCY_STATUSES)


def unreported_gallons_total(licensee_id):
    total = calc.ZERO
    for d in db.discrepancies.values():
        if (d["distributor_licensee_id"] == licensee_id
                and d["direction"] == "UNREPORTED_BY_PURCHASER"
                and d["status"] not in ("WRITTEN_OFF", "RESOLVED_EXPLAINED")):
            total += d["variance_gallons"]
    return calc.g2(total)


def risk_inputs(licensee_id):
    return {
        "unreported_gallons_total": unreported_gallons_total(licensee_id),
        "open_discrepancy_count": open_discrepancy_count(licensee_id),
        "late_filing_count": late_filing_count(licensee_id),
        "dyed_violation_count": dyed_violation_count(licensee_id),
    }


def risk_scores(licensee_id):
    inputs = risk_inputs(licensee_id)
    return calc.risk_scores(inputs["unreported_gallons_total"],
                            inputs["open_discrepancy_count"],
                            inputs["late_filing_count"],
                            inputs["dyed_violation_count"])


# --------------------------------------------------------------------------
# Serializers.
# --------------------------------------------------------------------------
def _common(row, versioned=True):
    out = {"id": row["id"], "created_at": row["created_at"]}
    if versioned:
        out["updated_at"] = row["updated_at"]
        out["version"] = row["version"]
    return out


def licensee_json(row):
    out = _common(row)
    out.update({
        "legal_name": row["legal_name"],
        "fein": row["fein"],
        "license_type": row["license_type"],
        "mailing_state": row["mailing_state"],
        "status": row["status"],
        "parent_licensee_id": row["parent_licensee_id"],
        "gross_net_election": row["gross_net_election"],
        "retail_channel": row["retail_channel"],
    })
    position = bond_position(row)
    out["avg_monthly_tax_liability_cents"] = position["avg_monthly_tax_liability_cents"]
    out["required_bond_cents"] = position["required_bond_cents"]
    out["posted_bond_cents"] = position["posted_bond_cents"]
    out["bond_deficiency_cents"] = position["bond_deficiency_cents"]
    out["balance_cents"] = balance_cents(row["id"])
    out["effective_taxable_gallons_ytd"] = num(effective_taxable_gallons_ytd(row["id"]))
    inputs = risk_inputs(row["id"])
    out["dyed_violation_count"] = inputs["dyed_violation_count"]
    out["late_filing_count"] = inputs["late_filing_count"]
    out["open_audit_count"] = open_audit_count(row["id"])
    out["open_discrepancy_count"] = inputs["open_discrepancy_count"]
    out["unreported_gallons_total"] = num(inputs["unreported_gallons_total"])
    variance, frequency = calc.risk_scores(
        inputs["unreported_gallons_total"], inputs["open_discrepancy_count"],
        inputs["late_filing_count"], inputs["dyed_violation_count"])
    out["risk_score_variance_weighted"] = variance
    out["risk_score_frequency_weighted"] = frequency
    return out


def bond_json(row):
    out = _common(row)
    out.update({
        "licensee_id": row["licensee_id"],
        "amount_cents": row["amount_cents"],
        "surety_name": row["surety_name"],
        "effective_date": db.iso_date(row["effective_date"]),
        "status": row["status"],
        "release_reason": row["release_reason"],
    })
    return out


def terminal_json(row):
    out = _common(row)
    out.update({
        "terminal_control_number": row["terminal_control_number"],
        "name": row["name"],
        "state_code": row["state_code"],
    })
    return out


def certificate_json(row):
    out = _common(row)
    out.update({
        "purchaser_licensee_id": row["purchaser_licensee_id"],
        "exemption_type": row["exemption_type"],
        "document_number": row["document_number"],
        "valid_from": db.iso_date(row["valid_from"]),
        "valid_to": db.iso_date(row["valid_to"]),
        "status": row["status"],
    })
    return out


def rack_removal_json(row):
    out = _common(row, versioned=False)
    out.update({
        "terminal_id": row["terminal_id"],
        "position_holder_licensee_id": row["position_holder_licensee_id"],
        "purchaser_licensee_id": row["purchaser_licensee_id"],
        "exemption_certificate_id": row["exemption_certificate_id"],
        "product_code": row["product_code"],
        "gross_gallons": num(row["gross_gallons"]),
        "net_gallons": num(row["net_gallons"]),
        "removal_date": db.iso_date(row["removal_date"]),
        "destination_state": row["destination_state"],
        "bill_of_lading_number": row["bill_of_lading_number"],
        "taxable_gallons": num(row["taxable_gallons"]),
        "imposition_point": row["imposition_point"],
        "tax_imposed": row["tax_imposed"],
        "tax_amount_cents": row["tax_amount_cents"],
        "deferred_tax_cents": row["deferred_tax_cents"],
        "basis_used": row["basis_used"],
    })
    return out


def monthly_return_json(row):
    out = _common(row)
    out.update({
        "licensee_id": row["licensee_id"],
        "period_month": row["period_month"],
        "amends_return_id": row["amends_return_id"],
        "amendment_sequence": row["amendment_sequence"],
        "amendment_count": row["amendment_count"],
        "filing_status": row["filing_status"],
        "match_status": row["match_status"],
        "attest_name": row["attest_name"],
        "filed_at": db.iso(row["filed_at"]),
        "due_at": db.iso(row["due_at"]),
        "days_late": row["days_late"],
        "taxable_gallons_total": num(row["taxable_gallons_total"]),
        "tax_due_cents": row["tax_due_cents"],
        "interest_cents": row["interest_cents"],
        "penalty_cents": row["penalty_cents"],
        "total_remittance_cents": row["total_remittance_cents"],
        "amendment_delta_cents": row["amendment_delta_cents"],
    })
    return out


def schedule_json(row):
    out = _common(row)
    out.update({
        "return_id": row["return_id"],
        "schedule_code": row["schedule_code"],
        "product_code": row["product_code"],
        "total_gallons": num(row["total_gallons"]),
        "line_count": row["line_count"],
    })
    return out


def schedule_line_json(row):
    out = _common(row, versioned=False)
    out.update({
        "schedule_id": row["schedule_id"],
        "counterparty_licensee_id": row["counterparty_licensee_id"],
        "exemption_certificate_id": row["exemption_certificate_id"],
        "transaction_type": row["transaction_type"],
        "gallons": num(row["gallons"]),
        "document_date": db.iso_date(row["document_date"]),
        "bill_of_lading_number": row["bill_of_lading_number"],
    })
    return out


def run_discrepancies(run_id):
    return [d for d in db.ordered(db.discrepancies) if d["run_id"] == run_id]


def run_live_counters(run_id):
    """The two live gallons counters of PRD 3.6; their sum is the frozen gross."""
    unreported = calc.ZERO
    written_off = calc.ZERO
    for d in db.discrepancies.values():
        if d["run_id"] != run_id or d["direction"] != "UNREPORTED_BY_PURCHASER":
            continue
        if d["status"] == "WRITTEN_OFF":
            written_off += d["variance_gallons"]
        else:
            unreported += d["variance_gallons"]
    return calc.g2(unreported), calc.g2(written_off)


def cross_match_run_json(row):
    out = _common(row)
    unreported, written_off = run_live_counters(row["id"])
    out.update({
        "period_month": row["period_month"],
        "run_status": row["run_status"],
        "tolerance_gallons": num(row["tolerance_gallons"]),
        "matched_cells_count": row["matched_cells_count"],
        "discrepancy_count": row["discrepancy_count"],
        "gross_unreported_gallons_total": num(row["gross_unreported_gallons_total"]),
        "unreported_gallons_total": num(unreported),
        "written_off_gallons_total": num(written_off),
        "escalated_count": row["escalated_count"],
        "escalation_skipped_count": row["escalation_skipped_count"],
    })
    return out


def discrepancy_json(row):
    out = _common(row)
    out.update({
        "run_id": row["run_id"],
        "supplier_licensee_id": row["supplier_licensee_id"],
        "distributor_licensee_id": row["distributor_licensee_id"],
        "supplier_return_id": row["supplier_return_id"],
        "distributor_return_id": row["distributor_return_id"],
        "product_code": row["product_code"],
        "supplier_gallons": num(row["supplier_gallons"]),
        "distributor_gallons": num(row["distributor_gallons"]),
        "variance_gallons": num(row["variance_gallons"]),
        "direction": row["direction"],
        "status": row["status"],
        "inquiry_round": row["inquiry_round"],
        "last_question": row["last_question"],
        "last_explanation": row["last_explanation"],
        "response_due_date": db.iso_date(row["response_due_date"]),
    })
    return out


def refund_claim_json(row):
    out = _common(row)
    out.update({
        "licensee_id": row["licensee_id"],
        "claim_type": row["claim_type"],
        "period_month": row["period_month"],
        "claimed_gallons": num(row["claimed_gallons"]),
        "equipment_class": row["equipment_class"],
        "allowable_gallons": num(row["allowable_gallons"]),
        "refund_amount_cents": row["refund_amount_cents"],
        "status": row["status"],
        "status_before_hold": row["status_before_hold"],
        "hold_reason": row["hold_reason"],
        "recommendation": row["recommendation"],
        "recommended_gallons": num(row["recommended_gallons"]),
        "reviewer_user_id": row["reviewer_user_id"],
        "decider_user_id": row["decider_user_id"],
        "payment_reference": row["payment_reference"],
    })
    return out


def inspection_json(row):
    out = _common(row)
    out.update({
        "inspected_licensee_id": row["inspected_licensee_id"],
        "inspection_date": db.iso_date(row["inspection_date"]),
        "dye_test_result": row["dye_test_result"],
        "gallons_in_tank": num(row["gallons_in_tank"]),
        "vehicle_identifier": row["vehicle_identifier"],
        "location_description": row["location_description"],
        "prior_positive_count": row["prior_positive_count"],
        "penalty_cents": row["penalty_cents"],
        "status": row["status"],
        "dismissal_reason": row["dismissal_reason"],
    })
    return out


def audit_case_json(row):
    out = _common(row)
    out.update({
        "subject_licensee_id": row["subject_licensee_id"],
        "source_discrepancy_id": row["source_discrepancy_id"],
        "selection_method": row["selection_method"],
        "risk_score_variant": row["risk_score_variant"],
        "selection_score": row["selection_score"],
        "period_start_month": row["period_start_month"],
        "period_end_month": row["period_end_month"],
        "case_status": row["case_status"],
        "assessment_status": row["assessment_status"],
        "response_rounds": row["response_rounds"],
        "additional_tax_cents": row["additional_tax_cents"],
        "evasion_indicator": row["evasion_indicator"],
        "assessment_penalty_cents": row["assessment_penalty_cents"],
        "assessment_interest_cents": row["assessment_interest_cents"],
        "assessed_total_cents": row["assessed_total_cents"],
        "opened_by_user_id": row["opened_by_user_id"],
        "assessed_by_user_id": row["assessed_by_user_id"],
        "protest_grounds": row["protest_grounds"],
        "abatement_reason": row["abatement_reason"],
    })
    return out


def ledger_entry_json(row):
    out = _common(row, versioned=False)
    out.update({
        "licensee_id": row["licensee_id"],
        "entry_type": row["entry_type"],
        "amount_cents": row["amount_cents"],
        "source_entity_type": row["source_entity_type"],
        "source_entity_id": row["source_entity_id"],
        "effective_date": db.iso_date(row["effective_date"]),
        "memo": row["memo"],
    })
    return out
