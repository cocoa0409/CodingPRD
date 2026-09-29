"""Domain helpers: lookups, derived aggregates, compliance posture, cascades
and resource serializers.
"""

from core import (
    clock_date,
    db,
    err,
    fmt_date,
    norm_num,
    parse_date_str,
    setf,
    touch,
)

import calc


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------
NOT_FOUND = {
    "trade_classifications": "ERR_TRADE_CLASSIFICATION_NOT_FOUND",
    "recovery_fund_accounts": "ERR_RECOVERY_FUND_ACCOUNT_NOT_FOUND",
    "licensees": "ERR_LICENSEE_NOT_FOUND",
    "qualifying_individuals": "ERR_QUALIFYING_INDIVIDUAL_NOT_FOUND",
    "consumers": "ERR_CONSUMER_NOT_FOUND",
    "license_applications": "ERR_LICENSE_APPLICATION_NOT_FOUND",
    "licenses": "ERR_LICENSE_NOT_FOUND",
    "coverage_records": "ERR_COVERAGE_RECORD_NOT_FOUND",
    "qualifier_assignments": "ERR_QUALIFIER_ASSIGNMENT_NOT_FOUND",
    "complaints": "ERR_COMPLAINT_NOT_FOUND",
    "investigations": "ERR_INVESTIGATION_NOT_FOUND",
    "citations": "ERR_CITATION_NOT_FOUND",
    "disciplinary_hearings": "ERR_DISCIPLINARY_HEARING_NOT_FOUND",
    "recovery_fund_claims": "ERR_RECOVERY_FUND_CLAIM_NOT_FOUND",
}


def find(collection, row_id):
    return getattr(db, collection).get(row_id)


def must(collection, row_id):
    row = getattr(db, collection).get(row_id)
    if row is None:
        err(NOT_FOUND[collection], "%s not found" % collection[:-1].replace("_", " "))
    return row


def rows(collection):
    return list(getattr(db, collection).values())


def D(s):
    """Parse a stored ISO date string into a date."""
    if s is None:
        return None
    return parse_date_str(s)


# ---------------------------------------------------------------------------
# Derived aggregates
# ---------------------------------------------------------------------------
def license_claims(license_id):
    return [c for c in rows("recovery_fund_claims") if c.get("license_id") == license_id]


def license_outstanding_recovery(lic):
    total = 0
    for c in license_claims(lic["id"]):
        if c["status"] in ("PAID", "REIMBURSED"):
            total += c["paid_amount_cents"] - c["repaid_amount_cents"]
    return total


def license_recovery_paid_to_date(lic):
    total = 0
    for c in license_claims(lic["id"]):
        if c["status"] in ("PAID", "REIMBURSED"):
            total += c["paid_amount_cents"]
    return total


def license_recovery_encumbered(lic):
    total = 0
    for c in license_claims(lic["id"]):
        if c["status"] in ("APPROVED", "PAID", "REIMBURSED"):
            total += c.get("awarded_amount_cents") or 0
    return total


def account_balance(acct):
    total = acct["initial_balance_cents"]
    for c in rows("recovery_fund_claims"):
        if c.get("fund_account_id") != acct["id"]:
            continue
        if c["status"] in ("PAID", "REIMBURSED"):
            total -= c["paid_amount_cents"]
        total += c["repaid_amount_cents"]
    return total


def license_citations(license_id):
    return [c for c in rows("citations") if c.get("license_id") == license_id]


def unpaid_penalty_exposure(license_id):
    total = 0
    for c in license_citations(license_id):
        if c["status"] in ("FINAL", "AFFIRMED", "MODIFIED"):
            total += c["civil_penalty_cents"] - c["penalty_paid_cents"]
    return total


def licensee_unpaid_penalty(licensee_id):
    total = 0
    for lic in rows("licenses"):
        if lic["licensee_id"] != licensee_id:
            continue
        total += unpaid_penalty_exposure(lic["id"])
    return total


def licensee_outstanding_payout(licensee_id):
    total = 0
    for lic in rows("licenses"):
        if lic["licensee_id"] == licensee_id:
            total += license_outstanding_recovery(lic)
    return total


def qi_active_count(qi_id):
    return len([a for a in rows("qualifier_assignments")
                if a["qualifying_individual_id"] == qi_id and a["status"] == "ACTIVE"])


def license_assignments(license_id):
    return [a for a in rows("qualifier_assignments") if a["license_id"] == license_id]


# ---------------------------------------------------------------------------
# Coverage helpers
# ---------------------------------------------------------------------------
def coverage_records_for(license_id):
    return [c for c in rows("coverage_records") if c["license_id"] == license_id]


def has_live_coverage(license_id, coverage_type):
    today = clock_date()
    for c in coverage_records_for(license_id):
        if c["coverage_type"] != coverage_type or c["status"] != "VERIFIED":
            continue
        if D(c["effective_date"]) <= today < D(c["expiration_date"]):
            return True
    return False


def bond_spans(license_id):
    spans = []
    for c in coverage_records_for(license_id):
        if c["coverage_type"] != "BOND":
            continue
        if c["status"] not in ("VERIFIED", "LAPSED", "CANCELLED"):
            continue
        start = D(c["effective_date"])
        if c["status"] == "CANCELLED" and c.get("cancellation_date"):
            end = D(c["cancellation_date"])
        else:
            end = D(c["expiration_date"])
        spans.append((start, end))
    return spans


def bond_gap_days(lic):
    start = D(lic.get("last_renewed_on") or lic["issued_on"])
    return calc.bond_continuity_gap_days(start, clock_date(), bond_spans(lic["id"]))


# ---------------------------------------------------------------------------
# Compliance posture (PRD 2.6)
# ---------------------------------------------------------------------------
def latest_decided_hearing_tier(license_id):
    best = None
    for h in rows("disciplinary_hearings"):
        if h["status"] != "DECIDED" or not h.get("decided_at"):
            continue
        cit = find("citations", h["citation_id"])
        if cit is None or cit.get("license_id") != license_id:
            continue
        key = (h["decided_at"], h["_seq"])
        if best is None or key > best[0]:
            best = (key, h)
    return best[1].get("sanction_tier") if best else None


def compute_posture(lic):
    live_bond = has_live_coverage(lic["id"], "BOND")
    if (not live_bond
            or license_outstanding_recovery(lic) > 0
            or lic.get("qualifying_individual_id") is None
            or lic["status"] == "REVOKED"):
        return "NON_COMPLIANT"
    live_gl = has_live_coverage(lic["id"], "GENERAL_LIABILITY")
    probation = (latest_decided_hearing_tier(lic["id"]) == "PROBATION"
                 and lic["status"] == "ACTIVE")
    if unpaid_penalty_exposure(lic["id"]) > 0 or not live_gl or probation:
        return "CONDITIONAL"
    return "COMPLIANT"


def recompute_posture(lic):
    setf(lic, "compliance_posture", compute_posture(lic))


# ---------------------------------------------------------------------------
# Cascades (PRD 2.8)
# ---------------------------------------------------------------------------
def suspend_designations(lic):
    """License entered SUSPENDED from ACTIVE: park its ACTIVE designations."""
    for a in license_assignments(lic["id"]):
        if a["status"] == "ACTIVE":
            setf(a, "status", "SUSPENDED_BY_LICENSE")
            qi = find("qualifying_individuals", a["qualifying_individual_id"])
            touch(qi)


def restore_designations(lic):
    """License returned SUSPENDED -> ACTIVE: revive parked designations."""
    today = clock_date()
    for a in license_assignments(lic["id"]):
        if a["status"] != "SUSPENDED_BY_LICENSE":
            continue
        eff_to = a.get("effective_to")
        if eff_to is not None and D(eff_to) < today:
            continue
        setf(a, "status", "ACTIVE")
        qi = find("qualifying_individuals", a["qualifying_individual_id"])
        touch(qi)


def suspend_license(lic, reason, until=None):
    was_active = lic["status"] == "ACTIVE"
    setf(lic, "status", "SUSPENDED")
    setf(lic, "suspension_reason", reason)
    setf(lic, "suspension_until", until)
    if was_active:
        suspend_designations(lic)


def revoke_license(lic):
    today = fmt_date(clock_date())
    for a in license_assignments(lic["id"]):
        if a["status"] in ("ACTIVE", "SUSPENDED_BY_LICENSE"):
            came_from_active = a["status"] == "ACTIVE"
            setf(a, "status", "TERMINATED_BY_REVOCATION")
            setf(a, "effective_to", today)
            if came_from_active:
                touch(find("qualifying_individuals", a["qualifying_individual_id"]))
    setf(lic, "status", "REVOKED")
    setf(lic, "suspension_reason", None)
    setf(lic, "suspension_until", None)
    setf(lic, "qualifying_individual_id", None)


def reactivate_license(lic):
    setf(lic, "status", "ACTIVE")
    setf(lic, "suspension_reason", None)
    setf(lic, "suspension_until", None)
    restore_designations(lic)


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------
def ser_classification(r):
    return {
        "id": r["id"],
        "code": r["code"],
        "name": r["name"],
        "hazard_tier": r["hazard_tier"],
        "min_experience_months": r["min_experience_months"],
        "min_net_worth_cents": r["min_net_worth_cents"],
        "required_bond_amount_cents": r["required_bond_amount_cents"],
        "required_ce_hours": r["required_ce_hours"],
        "renewal_base_fee_cents": r["renewal_base_fee_cents"],
        "mediation_required": r["mediation_required"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def ser_fund_account(r):
    return {
        "id": r["id"],
        "fiscal_year": r["fiscal_year"],
        "initial_balance_cents": r["initial_balance_cents"],
        "per_claim_cap_cents": r["per_claim_cap_cents"],
        "per_license_aggregate_cap_cents": r["per_license_aggregate_cap_cents"],
        "balance_cents": account_balance(r),
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def ser_licensee(r):
    return {
        "id": r["id"],
        "legal_name": r["legal_name"],
        "entity_type": r["entity_type"],
        "contact_email": r["contact_email"],
        "unpaid_penalty_cents": licensee_unpaid_penalty(r["id"]),
        "outstanding_recovery_payout_cents": licensee_outstanding_payout(r["id"]),
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def ser_qualifying_individual(r):
    return {
        "id": r["id"],
        "full_name": r["full_name"],
        "verified_experience_months": r["verified_experience_months"],
        "active_qualification_count": qi_active_count(r["id"]),
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def ser_exam_result(r):
    return {
        "id": r["id"],
        "qualifying_individual_id": r["qualifying_individual_id"],
        "exam_type": r["exam_type"],
        "trade_code": r.get("trade_code"),
        "score": r["score"],
        "passed": r["passed"],
        "taken_on": r["taken_on"],
        "expires_on": r["expires_on"],
        "created_at": r["created_at"],
    }


def ser_application(r):
    return {
        "id": r["id"],
        "licensee_id": r["licensee_id"],
        "classification_id": r["classification_id"],
        "qualifying_individual_id": r["qualifying_individual_id"],
        "predecessor_license_id": r.get("predecessor_license_id"),
        "application_type": r["application_type"],
        "education_credential": r["education_credential"],
        "declared_net_worth_cents": r["declared_net_worth_cents"],
        "credited_experience_months": r.get("credited_experience_months"),
        "status": r["status"],
        "deficiency_round_count": r["deficiency_round_count"],
        "deficiency_reason": r.get("deficiency_reason"),
        "denial_reason": r.get("denial_reason"),
        "submitted_at": r.get("submitted_at"),
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def ser_license(r):
    return {
        "id": r["id"],
        "licensee_id": r["licensee_id"],
        "classification_id": r["classification_id"],
        "application_id": r.get("application_id"),
        "qualifying_individual_id": r.get("qualifying_individual_id"),
        "predecessor_license_id": r.get("predecessor_license_id"),
        "license_number": r["license_number"],
        "status": r["status"],
        "compliance_posture": r["compliance_posture"],
        "issued_on": r["issued_on"],
        "expires_on": r["expires_on"],
        "suspension_reason": r.get("suspension_reason"),
        "suspension_until": r.get("suspension_until"),
        "ce_hours_completed": norm_num(r["ce_hours_completed"]),
        "outstanding_recovery_repayment_cents": license_outstanding_recovery(r),
        "recovery_paid_to_date_cents": license_recovery_paid_to_date(r),
        "recovery_encumbered_cents": license_recovery_encumbered(r),
        "last_renewed_on": r.get("last_renewed_on"),
        "renewal_count": r["renewal_count"],
        "last_renewal_fee_cents": r.get("last_renewal_fee_cents"),
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def ser_coverage(r):
    return {
        "id": r["id"],
        "license_id": r["license_id"],
        "coverage_type": r["coverage_type"],
        "carrier_name": r["carrier_name"],
        "policy_number": r["policy_number"],
        "amount_cents": r["amount_cents"],
        "effective_date": r["effective_date"],
        "expiration_date": r["expiration_date"],
        "status": r["status"],
        "verified_on": r.get("verified_on"),
        "cancellation_date": r.get("cancellation_date"),
        "rejection_reason": r.get("rejection_reason"),
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def ser_assignment(r):
    return {
        "id": r["id"],
        "license_id": r["license_id"],
        "qualifying_individual_id": r["qualifying_individual_id"],
        "relationship_type": r["relationship_type"],
        "ownership_pct": norm_num(r["ownership_pct"]),
        "effective_from": r["effective_from"],
        "effective_to": r.get("effective_to"),
        "status": r["status"],
        "withdrawn_on": r.get("withdrawn_on"),
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def ser_consumer(r):
    return {
        "id": r["id"],
        "full_name": r["full_name"],
        "contact_email": r["contact_email"],
        "mailing_state": r["mailing_state"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def ser_complaint(r):
    return {
        "id": r["id"],
        "consumer_id": r["consumer_id"],
        "license_id": r.get("license_id"),
        "subject_business_name": r.get("subject_business_name"),
        "alleged_loss_cents": r["alleged_loss_cents"],
        "contract_date": r["contract_date"],
        "work_completed_on": r.get("work_completed_on"),
        "description": r["description"],
        "status": r["status"],
        "mediation_round_count": r["mediation_round_count"],
        "mediation_deadline": r.get("mediation_deadline"),
        "settlement_amount_cents": r["settlement_amount_cents"],
        "jurisdiction_basis": r.get("jurisdiction_basis"),
        "dismissal_reason": r.get("dismissal_reason"),
        "remand_reason": r.get("remand_reason"),
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def ser_investigation(r):
    return {
        "id": r["id"],
        "complaint_id": r.get("complaint_id"),
        "subject_license_id": r.get("subject_license_id"),
        "subject_business_name": r.get("subject_business_name"),
        "origin": r["origin"],
        "assigned_investigator_user_id": r["assigned_investigator_user_id"],
        "status": r["status"],
        "finding": r.get("finding"),
        "finding_severity": r.get("finding_severity"),
        "evidence_summary": r.get("evidence_summary"),
        "opened_on": r["opened_on"],
        "closed_on": r.get("closed_on"),
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def ser_citation(r):
    return {
        "id": r["id"],
        "investigation_id": r["investigation_id"],
        "license_id": r.get("license_id"),
        "classification_id": r["classification_id"],
        "subject_type": r["subject_type"],
        "violation_code": r["violation_code"],
        "severity": r["severity"],
        "civil_penalty_cents": r["civil_penalty_cents"],
        "penalty_variant": r["penalty_variant"],
        "penalty_paid_cents": r["penalty_paid_cents"],
        "prior_final_citation_count": r["prior_final_citation_count"],
        "correction_due_date": r["correction_due_date"],
        "correction_completed_on": r.get("correction_completed_on"),
        "issued_on": r["issued_on"],
        "appeal_deadline": r["appeal_deadline"],
        "appeal_grounds": r.get("appeal_grounds"),
        "status": r["status"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def ser_hearing(r):
    return {
        "id": r["id"],
        "citation_id": r["citation_id"],
        "presiding_officer_user_id": r["presiding_officer_user_id"],
        "scheduled_start_utc": r["scheduled_start_utc"],
        "scheduled_end_utc": r["scheduled_end_utc"],
        "status": r["status"],
        "decision": r.get("decision"),
        "findings_summary": r.get("findings_summary"),
        "modified_penalty_cents": r.get("modified_penalty_cents"),
        "sanction_points": r.get("sanction_points"),
        "sanction_tier": r.get("sanction_tier"),
        "decided_at": r.get("decided_at"),
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def ser_claim(r):
    return {
        "id": r["id"],
        "fund_account_id": r["fund_account_id"],
        "complaint_id": r["complaint_id"],
        "consumer_id": r["consumer_id"],
        "license_id": r["license_id"],
        "basis": r["basis"],
        "claimed_amount_cents": r["claimed_amount_cents"],
        "judgment_amount_cents": r.get("judgment_amount_cents"),
        "judgment_docket_number": r.get("judgment_docket_number"),
        "judgment_entered_on": r.get("judgment_entered_on"),
        "estimated_award_cents": r["estimated_award_cents"],
        "awarded_amount_cents": r.get("awarded_amount_cents"),
        "paid_amount_cents": r["paid_amount_cents"],
        "repaid_amount_cents": r["repaid_amount_cents"],
        "status": r["status"],
        "denial_reason": r.get("denial_reason"),
        "adjudicated_on": r.get("adjudicated_on"),
        "paid_on": r.get("paid_on"),
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }
