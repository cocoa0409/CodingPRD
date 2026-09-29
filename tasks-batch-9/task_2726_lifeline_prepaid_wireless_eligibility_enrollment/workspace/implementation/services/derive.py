"""Derived counters and JSON serializers for every entity.

Counters are recomputed from the rows they count. Derived aggregates are also
evaluated at serialization time so a read always observes the settled world;
version/updated_at bumps remain governed strictly by the PRD's cascade rules.
"""
import db
from db import fmt_dt
from services import calc

FAULT_DE_ENROLLMENT_REASONS = (
    "NON_USAGE", "RECERT_NON_RESPONSE", "INELIGIBLE_ON_RECERT", "AUDIT_INELIGIBLE",
)
LEDGER_GROSS_STATUSES = ("FILED", "HELD", "UNDER_AUDIT", "AUDIT_PASSED", "AUDIT_FAILED")
OPEN_CLAIM_STATUSES = ("DRAFT", "FILED", "HELD", "UNDER_AUDIT")


# ------------------------------------------------------------- selectors

def enrollments_of_provider(provider_id):
    return [e for e in db.db.enrollments.values() if e["provider_id"] == provider_id]


def devices_of_provider(provider_id):
    return [d for d in db.db.devices.values() if d["provider_id"] == provider_id]


def claims_of_provider(provider_id):
    return [c for c in db.db.claims.values() if c["provider_id"] == provider_id]


def enrollments_at_address(address_id):
    return [e for e in db.db.enrollments.values()
            if e["certified_address_id"] == address_id]


def subscribers_at_address(address_id):
    return [s for s in db.db.subscribers.values() if s["address_id"] == address_id]


def addresses_with_hash(address_hash):
    return [a for a in db.db.addresses.values() if a["address_hash"] == address_hash]


def checks_of_subscriber(subscriber_id):
    return [c for c in db.db.eligibility_checks.values()
            if c["subscriber_id"] == subscriber_id]


def enrollments_of_subscriber(subscriber_id):
    return [e for e in db.db.enrollments.values()
            if e["subscriber_id"] == subscriber_id]


def samples_of_claim(claim_id):
    return [s for s in db.db.audit_samples.values() if s["claim_id"] == claim_id]


def samples_of_enrollment(enrollment_id):
    return [s for s in db.db.audit_samples.values()
            if s["enrollment_id"] == enrollment_id]


def cases_of_enrollment(enrollment_id):
    return [c for c in db.db.cases.values() if c["enrollment_id"] == enrollment_id]


def transfers_of_enrollment(enrollment_id):
    return [t for t in db.db.service_transfers.values()
            if t["enrollment_id"] == enrollment_id]


def devices_of_enrollment(enrollment_id):
    return [d for d in db.db.devices.values()
            if d.get("issued_enrollment_id") == enrollment_id]


# --------------------------------------------------------- provider math

def provider_counters(provider):
    pid = provider["id"]
    enrollments = enrollments_of_provider(pid)
    devices = devices_of_provider(pid)
    claims = claims_of_provider(pid)
    statuses = [d["status"] for d in devices]
    gross = sum((c["final_amount_cents"] or 0) for c in claims
                if c["status"] in LEDGER_GROSS_STATUSES)
    recouped = sum((c["recoupment_amount_cents"] or 0) for c in claims
                   if c["status"] == "AUDIT_FAILED")
    return {
        "active_enrollment_count": len([e for e in enrollments
                                        if e["benefit_status"] == "ACTIVE"]),
        "devices_total_count": len(devices),
        "devices_in_stock_count": statuses.count("IN_STOCK"),
        "devices_issued_count": statuses.count("ISSUED"),
        "devices_reclaim_pending_count": statuses.count("RECLAIM_PENDING"),
        "devices_retired_count": statuses.count("RETIRED") + statuses.count("LOST"),
        "open_claim_count": len([c for c in claims
                                 if c["status"] in OPEN_CLAIM_STATUSES]),
        "claim_gross_cents": gross,
        "recouped_cents": recouped,
        "net_reimbursed_cents": gross - recouped,
        "audit_hold_flag": any(c["status"] == "AUDIT_FAILED" for c in claims),
    }


def active_enrollment_count(provider_id):
    return len([e for e in enrollments_of_provider(provider_id)
                if e["benefit_status"] == "ACTIVE"])


def audit_hold_flag(provider_id):
    return any(c["status"] == "AUDIT_FAILED" for c in claims_of_provider(provider_id))


# ---------------------------------------------------------- address math

def max_permitted_benefit_slots(address):
    if (address["status"] == "RESOLVED_MULTI_HOUSEHOLD"
            and address.get("declared_household_count") is not None):
        return address["declared_household_count"]
    return 1


def occupied_benefit_slots(address_id):
    return len([e for e in enrollments_at_address(address_id)
                if e["benefit_status"] == "ACTIVE"])


def cohort_address_count(address):
    return len(addresses_with_hash(address["address_hash"]))


def address_counters(address):
    return {
        "max_permitted_benefit_slots": max_permitted_benefit_slots(address),
        "occupied_benefit_slots": occupied_benefit_slots(address["id"]),
        "cohort_address_count": cohort_address_count(address),
    }


# ------------------------------------------------------- subscriber math

def de_enrollment_count(subscriber_id):
    return len([e for e in enrollments_of_subscriber(subscriber_id)
                if e["benefit_status"] == "DE_ENROLLED"
                and e.get("de_enrollment_reason") in FAULT_DE_ENROLLMENT_REASONS])


def latest_confirmed_check(subscriber_id):
    confirmed = [c for c in checks_of_subscriber(subscriber_id)
                 if c["status"] == "ELIGIBLE_CONFIRMED"]
    if not confirmed:
        return None
    return max(confirmed, key=lambda c: (c["confirmed_at"], c["_seq"]))


def eligibility_basis(subscriber):
    check = latest_confirmed_check(subscriber["id"])
    if check is None:
        return "NONE"
    if check["claimed_basis"] == "BENEFIT":
        return "TRIBAL_BENEFIT" if subscriber["tribal_lands_flag"] else "BENEFIT"
    return "INCOME"


def income_threshold_cents(subscriber):
    return calc.fpg_income_threshold(subscriber["household_size"],
                                     subscriber["tribal_lands_flag"])


def has_usable_confirmed_check(subscriber_id, now):
    for c in checks_of_subscriber(subscriber_id):
        if c["status"] == "ELIGIBLE_CONFIRMED" and c.get("expires_at") is not None \
                and now <= c["expires_at"]:
            return True
    return False


# ------------------------------------------------------- enrollment math

def transfer_count(enrollment_id):
    return len([t for t in transfers_of_enrollment(enrollment_id)
                if t["status"] == "ACCEPTED_COMPLETED"])


def reinstatement_count(enrollment_id):
    return len([c for c in cases_of_enrollment(enrollment_id)
                if c["case_type"] == "DE_ENROLLMENT_APPEAL"
                and c["status"] == "GRANTED"
                and c.get("reinstated_enrollment_flag")])


def enrollment_risk_score(enrollment):
    address = db.db.addresses.get(enrollment["certified_address_id"])
    address_status = address["status"] if address else None
    return calc.audit_risk_score(
        address_status,
        enrollment["usage_status"],
        enrollment["recert_status"],
        enrollment.get("device_issuance_count") or 0,
        transfer_count(enrollment["id"]),
    )


def recompute_risk(enrollment):
    enrollment["audit_risk_score"] = enrollment_risk_score(enrollment)


# ------------------------------------------------------------ claim math

def audit_sample_count(claim_id):
    return len(samples_of_claim(claim_id))


def failed_sample_count(claim_id):
    return len([s for s in samples_of_claim(claim_id)
                if s["status"] == "ADJUDICATED_FAIL"])


# ----------------------------------------------------------- serializers

def _common(row):
    return {
        "id": row["id"],
        "created_at": fmt_dt(row["created_at"]),
        "updated_at": fmt_dt(row["updated_at"]),
        "version": row["version"],
    }


def provider_json(row):
    out = _common(row)
    out.update({
        "name": row["name"],
        "spin_id": row["spin_id"],
        "study_area_code": row["study_area_code"],
        "licensed_state_codes": list(row["licensed_state_codes"]),
        "status": row["status"],
        "enrollment_cap": row["enrollment_cap"],
    })
    out.update(provider_counters(row))
    return out


def address_json(row):
    out = _common(row)
    out.update({
        "address_line1": row["address_line1"],
        "unit_designator": row["unit_designator"],
        "city": row["city"],
        "state_code": row["state_code"],
        "postal_code": row["postal_code"],
        "address_hash": row["address_hash"],
        "status": row["status"],
        "declared_household_count": row["declared_household_count"],
        "independent_household_worksheet_ref": row["independent_household_worksheet_ref"],
    })
    out.update(address_counters(row))
    return out


def subscriber_json(row):
    out = _common(row)
    out.update({
        "address_id": row["address_id"],
        "full_name": row["full_name"],
        "date_of_birth": row["date_of_birth"],
        "last4_ssn": row["last4_ssn"],
        "household_size": row["household_size"],
        "annual_income_cents": row["annual_income_cents"],
        "last_3mo_income_cents": row["last_3mo_income_cents"],
        "qualifying_benefit": row["qualifying_benefit"],
        "tribal_lands_flag": row["tribal_lands_flag"],
        "identity_key": row["identity_key"],
        "status": row["status"],
        "eligibility_basis": eligibility_basis(row),
        "income_threshold_cents": income_threshold_cents(row),
        "de_enrollment_count": de_enrollment_count(row["id"]),
    })
    return out


def eligibility_check_json(row):
    out = _common(row)
    out.update({
        "subscriber_id": row["subscriber_id"],
        "claimed_basis": row["claimed_basis"],
        "proof_document_ref": row["proof_document_ref"],
        "income_variant": row["income_variant"],
        "evaluated_income_cents": row["evaluated_income_cents"],
        "income_threshold_cents": row["income_threshold_cents"],
        "status": row["status"],
        "verifier_outcome": row["verifier_outcome"],
        "verifier_reason_code": row["verifier_reason_code"],
        "matched_benefit": row["matched_benefit"],
        "confirmed_at": fmt_dt(row["confirmed_at"]),
        "expires_at": fmt_dt(row["expires_at"]),
        "resubmission_count": row["resubmission_count"],
    })
    return out


def enrollment_json(row):
    out = _common(row)
    out.update({
        "subscriber_id": row["subscriber_id"],
        "provider_id": row["provider_id"],
        "eligibility_check_id": row["eligibility_check_id"],
        "certified_address_id": row["certified_address_id"],
        "service_type": row["service_type"],
        "one_per_household_attested": row["one_per_household_attested"],
        "benefit_status": row["benefit_status"],
        "usage_status": row["usage_status"],
        "recert_status": row["recert_status"],
        "device_status": row["device_status"],
        "benefit_start_date": fmt_dt(row["benefit_start_date"]),
        "benefit_end_date": fmt_dt(row["benefit_end_date"]),
        "last_usage_at": fmt_dt(row["last_usage_at"]),
        "non_usage_flagged_at": fmt_dt(row["non_usage_flagged_at"]),
        "cure_deadline_at": fmt_dt(row["cure_deadline_at"]),
        "recert_due_date": fmt_dt(row["recert_due_date"]),
        "recert_notice_sent_at": fmt_dt(row["recert_notice_sent_at"]),
        "recert_response_deadline_at": fmt_dt(row["recert_response_deadline_at"]),
        "recert_last_responded_at": fmt_dt(row["recert_last_responded_at"]),
        "recert_evaluated_income_cents": row["recert_evaluated_income_cents"],
        "recert_income_threshold_cents": row["recert_income_threshold_cents"],
        "de_enrollment_reason": row["de_enrollment_reason"],
        "de_enrolled_at": fmt_dt(row["de_enrolled_at"]),
        "de_enrolled_by_ref": row["de_enrolled_by_ref"],
        "port_freeze_until": fmt_dt(calc.port_freeze_until(row["benefit_start_date"])),
        "appeal_deadline_at": fmt_dt(row["appeal_deadline_at"]),
        "transfer_count": transfer_count(row["id"]),
        "device_issuance_count": row["device_issuance_count"],
        "last_device_issued_at": fmt_dt(row["last_device_issued_at"]),
        "audit_risk_score": enrollment_risk_score(row),
        "reinstatement_count": reinstatement_count(row["id"]),
    })
    return out


def device_json(row):
    out = _common(row)
    out.update({
        "provider_id": row["provider_id"],
        "imei": row["imei"],
        "model_tier": row["model_tier"],
        "unit_cost_cents": row["unit_cost_cents"],
        "status": row["status"],
        "issued_enrollment_id": row["issued_enrollment_id"],
        "issued_at": fmt_dt(row["issued_at"]),
        "returned_at": fmt_dt(row["returned_at"]),
        "return_condition": row["return_condition"],
    })
    return out


def service_transfer_json(row):
    out = _common(row)
    out.update({
        "enrollment_id": row["enrollment_id"],
        "target_provider_id": row["target_provider_id"],
        "source_provider_id": row["source_provider_id"],
        "subscriber_consent_ref": row["subscriber_consent_ref"],
        "status": row["status"],
        "rejection_reason": row["rejection_reason"],
        "requested_at": fmt_dt(row["requested_at"]),
        "completed_at": fmt_dt(row["completed_at"]),
        "port_freeze_until_snapshot": fmt_dt(row["port_freeze_until_snapshot"]),
    })
    return out


def claim_json(row):
    out = _common(row)
    out.update({
        "provider_id": row["provider_id"],
        "service_month": row["service_month"],
        "status": row["status"],
        "provisional_amount_cents": row["provisional_amount_cents"],
        "final_amount_cents": row["final_amount_cents"],
        "variance_cents": row["variance_cents"],
        "covered_enrollment_count": row["covered_enrollment_count"],
        "certifying_officer_ref": row["certifying_officer_ref"],
        "filed_at": fmt_dt(row["filed_at"]),
        "audit_sample_count": audit_sample_count(row["id"]),
        "failed_sample_count": failed_sample_count(row["id"]),
        "sample_drawn_by_ref": row["sample_drawn_by_ref"],
        "recoupment_amount_cents": row["recoupment_amount_cents"],
        "penalty_cents": row["penalty_cents"],
        "net_payable_cents": row["net_payable_cents"],
    })
    return out


def audit_sample_json(row):
    out = _common(row)
    out.update({
        "claim_id": row["claim_id"],
        "enrollment_id": row["enrollment_id"],
        "selection_rank": row["selection_rank"],
        "risk_score_at_draw": row["risk_score_at_draw"],
        "claimed_line_cents": row["claimed_line_cents"],
        "drawn_by_ref": row["drawn_by_ref"],
        "status": row["status"],
        "finding": row["finding"],
        "finding_note": row["finding_note"],
        "adjudicated_by_ref": row["adjudicated_by_ref"],
        "disallowed_support_cents": row["disallowed_support_cents"],
    })
    return out


def case_json(row):
    out = _common(row)
    out.update({
        "subscriber_id": row["subscriber_id"],
        "enrollment_id": row["enrollment_id"],
        "case_type": row["case_type"],
        "narrative": row["narrative"],
        "status": row["status"],
        "reviewer_ref": row["reviewer_ref"],
        "review_round": row["review_round"],
        "decision": row["decision"],
        "decision_rationale": row["decision_rationale"],
        "decided_at": fmt_dt(row["decided_at"]),
        "decided_by_ref": row["decided_by_ref"],
        "reinstated_enrollment_flag": row["reinstated_enrollment_flag"],
    })
    return out
