"""Cross-entity resolution, ownership chains, and cascade helpers."""

import calc
from common import touch
from store import db


# --------------------------------------------------------------------------
# FK resolution
# --------------------------------------------------------------------------
def assessment_of_appeal(appeal):
    return db.assessments.get(appeal["assessment_id"])


def parcel_of_assessment(assessment):
    return db.parcels.get(assessment["parcel_id"])


def jurisdiction_of_appeal(appeal):
    a = assessment_of_appeal(appeal)
    if not a:
        return None
    p = parcel_of_assessment(a)
    if not p:
        return None
    return db.jurisdictions.get(p["jurisdiction_id"])


def fee_agreement_of_appeal(appeal):
    return db.fee_agreements.get(appeal["fee_agreement_id"])


# --------------------------------------------------------------------------
# Ownership chains (resolve owning client_id)
# --------------------------------------------------------------------------
def client_of_parcel(parcel):
    return parcel["client_id"]


def client_of_assessment(assessment):
    p = db.parcels.get(assessment["parcel_id"])
    return p["client_id"] if p else None


def client_of_appeal(appeal):
    a = db.assessments.get(appeal["assessment_id"])
    return client_of_assessment(a) if a else None


def client_of_offer(offer):
    ap = db.appeals.get(offer["appeal_id"])
    return client_of_appeal(ap) if ap else None


def client_of_invoice(invoice):
    ap = db.appeals.get(invoice["appeal_id"])
    return client_of_appeal(ap) if ap else None


def client_of_exemption(claim):
    p = db.parcels.get(claim["parcel_id"])
    return p["client_id"] if p else None


# --------------------------------------------------------------------------
# Evidence / valuation helpers
# --------------------------------------------------------------------------
def included_evidence(appeal_id):
    rows = [e for e in db.evidence.values()
            if e["appeal_id"] == appeal_id and e["included"]]
    rows.sort(key=lambda r: (r["created_at"], r["_seq"]))
    return rows


def approved_exemption_total(parcel_id, tax_year):
    return sum(ec["exemption_value_cents"] for ec in db.exemption_claims.values()
               if ec["parcel_id"] == parcel_id and ec["tax_year"] == tax_year
               and ec["status"] == "APPROVED")


def recompute_assessment_tax(assessment):
    """Reconcile total_approved_exemption_cents and projected_annual_tax_cents
    from the current set of APPROVED exemption claims."""
    total = approved_exemption_total(assessment["parcel_id"], assessment["tax_year"])
    assessment["total_approved_exemption_cents"] = total
    assessment["projected_annual_tax_cents"] = calc.projected_annual_tax(
        assessment["assessed_value_cents"], total, assessment["millage_rate"])


def recompute_projected_client_tax_bill(appeal):
    a = assessment_of_appeal(appeal)
    if a is None or appeal.get("requested_value_cents") is None:
        return
    appeal["projected_client_tax_bill_cents"] = calc.projected_client_tax_bill(
        appeal["requested_value_cents"], a["total_approved_exemption_cents"],
        a["millage_rate"])


# --------------------------------------------------------------------------
# Terminal-outcome cascades
# --------------------------------------------------------------------------
NON_TERMINAL_APPEAL = {"DRAFT", "FILED", "INFORMAL_REVIEW", "HEARING_SCHEDULED"}
LIVE_APPEAL = {"FILED", "INFORMAL_REVIEW", "HEARING_SCHEDULED"}


def finalize_assessment(assessment, outcome_value):
    assessment["status"] = "FINALIZED"
    assessment["assessed_value_cents"] = outcome_value
    total = assessment["total_approved_exemption_cents"]
    assessment["projected_annual_tax_cents"] = calc.projected_annual_tax(
        outcome_value, total, assessment["millage_rate"])
    touch(assessment)


def create_terminal_invoice(appeal, realized_savings):
    fa = fee_agreement_of_appeal(appeal)
    fee = calc.contingency_fee(realized_savings, fa) if fa else 0
    from common import base_record
    inv = base_record()
    inv.update({
        "appeal_id": appeal["id"],
        "gross_savings_cents": realized_savings,
        "fee_amount_cents": fee,
        "amount_paid_cents": 0,
        "issued_date": None,
        "paid_date": None,
        "status": "DRAFT",
    })
    db.invoices[inv["id"]] = inv
    return inv
