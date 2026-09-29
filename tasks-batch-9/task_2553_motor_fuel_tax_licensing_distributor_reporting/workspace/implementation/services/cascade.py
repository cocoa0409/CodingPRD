"""Ledger posting, hold cascades and shared cross-entity rules."""

import db
from services import calc, derive


# --------------------------------------------------------------------------
# The append-only ledger (PRD 2.8).
# --------------------------------------------------------------------------
def post_ledger(licensee_id, entry_type, amount_cents, source_entity_type,
                source_entity_id, memo, effective_date=None):
    row = db.base_row(versioned=False)
    row.update({
        "licensee_id": licensee_id,
        "entry_type": entry_type,
        "amount_cents": int(amount_cents),
        "source_entity_type": source_entity_type,
        "source_entity_id": source_entity_id,
        "effective_date": effective_date or db.now().date(),
        "memo": memo,
    })
    db.ledger_entries[row["id"]] = row
    return row


# --------------------------------------------------------------------------
# Refund-claim holds (PRD 3.7).
# --------------------------------------------------------------------------
def hold_claims(licensee_id, hold_reason):
    """Move the licensee's SUBMITTED and REVIEWED claims to HELD."""
    for claim in db.ordered(db.refund_claims):
        if claim["licensee_id"] != licensee_id:
            continue
        if claim["status"] not in ("SUBMITTED", "REVIEWED"):
            continue
        claim["status_before_hold"] = claim["status"]
        claim["status"] = "HELD"
        claim["hold_reason"] = hold_reason
        db.touch(claim)


def release_holds(licensee_id, hold_reason):
    """Revert HELD claims frozen for one cause back to status_before_hold."""
    for claim in db.ordered(db.refund_claims):
        if claim["licensee_id"] != licensee_id:
            continue
        if claim["status"] != "HELD" or claim["hold_reason"] != hold_reason:
            continue
        claim["status"] = claim["status_before_hold"] or "SUBMITTED"
        claim["status_before_hold"] = None
        claim["hold_reason"] = None
        db.touch(claim)


def apply_bond_deficiency_hold(licensee):
    """Hop four of a suspension: freeze claims only when a deficiency remains."""
    if derive.bond_position(licensee)["bond_deficiency_cents"] > 0:
        hold_claims(licensee["id"], "BOND_DEFICIENCY")


# --------------------------------------------------------------------------
# Exemption certificates (PRD 3.3).
# --------------------------------------------------------------------------
def cert_validly_presented(cert_id, exemption_type, purchaser_licensee_id,
                           txn_date, product_code):
    """All six conditions of PRD 3.3 must hold."""
    if not cert_id:
        return False
    cert = db.certificates.get(cert_id)
    if cert is None:
        return False
    if cert["status"] != "ACTIVE":
        return False
    if cert["exemption_type"] != exemption_type:
        return False
    if cert["purchaser_licensee_id"] != purchaser_licensee_id:
        return False
    if txn_date < cert["valid_from"] or txn_date > cert["valid_to"]:
        return False
    if product_code not in calc.CERT_PRODUCT_SET[exemption_type]:
        return False
    return True


def cert_active_on_date(cert, txn_date):
    return (cert["status"] == "ACTIVE"
            and cert["valid_from"] <= txn_date <= cert["valid_to"])


# --------------------------------------------------------------------------
# Audit-case periods (PRD 3.9).
# --------------------------------------------------------------------------
def buffered_overlap(a_start, a_end, b_start, b_end):
    """Each window is widened by one month on both ends before comparison."""
    buffer_months = calc.AUDIT_PERIOD_BUFFER_MONTHS
    a_lo = db.month_index(a_start) - buffer_months
    a_hi = db.month_index(a_end) + buffer_months
    b_lo = db.month_index(b_start) - buffer_months
    b_hi = db.month_index(b_end) + buffer_months
    return a_lo <= b_hi and b_lo <= a_hi


def overlapping_open_case(subject_licensee_id, period_start_month,
                          period_end_month):
    """The first non-closed case of the subject whose buffered window collides."""
    for case in db.ordered(db.audit_cases):
        if case["subject_licensee_id"] != subject_licensee_id:
            continue
        if case["case_status"] == "CLOSED":
            continue
        if buffered_overlap(case["period_start_month"], case["period_end_month"],
                            period_start_month, period_end_month):
            return case
    return None


def escalation_subject_id(discrepancy):
    if discrepancy["direction"] == "UNREPORTED_BY_PURCHASER":
        return discrepancy["distributor_licensee_id"]
    return discrepancy["supplier_licensee_id"]


def create_audit_case(subject_licensee_id, selection_method, risk_score_variant,
                      selection_score, period_start_month, period_end_month,
                      opened_by_user_id, source_discrepancy_id=None):
    """Create a case and fire the open-audit hold cascade."""
    row = db.base_row()
    row.update({
        "subject_licensee_id": subject_licensee_id,
        "source_discrepancy_id": source_discrepancy_id,
        "selection_method": selection_method,
        "risk_score_variant": risk_score_variant,
        "selection_score": selection_score,
        "period_start_month": period_start_month,
        "period_end_month": period_end_month,
        "case_status": "OPEN",
        "assessment_status": "NONE",
        "response_rounds": 0,
        "additional_tax_cents": 0,
        "evasion_indicator": False,
        "assessment_penalty_cents": 0,
        "assessment_interest_cents": 0,
        "assessed_total_cents": 0,
        "opened_by_user_id": opened_by_user_id,
        "assessed_by_user_id": None,
        "protest_grounds": None,
        "abatement_reason": None,
    })
    db.audit_cases[row["id"]] = row
    # open_audit_count is now positive, so pending claims are held.
    hold_claims(subject_licensee_id, "OPEN_AUDIT")
    return row
