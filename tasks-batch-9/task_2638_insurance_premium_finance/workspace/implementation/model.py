"""Lookups, derived-field computation and response serializers."""

from core import clock, db, fail, ordered, parse_date


# ---------------------------------------------------------------------------
# Lookups (path-parameter resolution)
# ---------------------------------------------------------------------------

def get_state_rule(rule_id):
    rec = db.state_rules.get(rule_id)
    if rec is None:
        fail("ERR_STATE_RULE_NOT_FOUND", "state rate rule %s does not exist" % rule_id)
    return rec


def get_license(license_id):
    rec = db.licenses.get(license_id)
    if rec is None:
        fail("ERR_LICENSE_NOT_FOUND", "license %s does not exist" % license_id)
    return rec


def get_insured(insured_id):
    rec = db.insureds.get(insured_id)
    if rec is None:
        fail("ERR_INSURED_NOT_FOUND", "insured %s does not exist" % insured_id)
    return rec


def get_agent(agent_id):
    rec = db.agents.get(agent_id)
    if rec is None:
        fail("ERR_AGENT_NOT_FOUND", "producer agent %s does not exist" % agent_id)
    return rec


def get_insurer(insurer_id):
    rec = db.insurers.get(insurer_id)
    if rec is None:
        fail("ERR_INSURER_NOT_FOUND", "insurer %s does not exist" % insurer_id)
    return rec


def get_agreement(agreement_id):
    rec = db.agreements.get(agreement_id)
    if rec is None:
        fail("ERR_AGREEMENT_NOT_FOUND", "agreement %s does not exist" % agreement_id)
    return rec


def get_policy(policy_id):
    rec = db.policies.get(policy_id)
    if rec is None:
        fail("ERR_POLICY_NOT_FOUND", "policy %s does not exist" % policy_id)
    return rec


def get_payment(payment_id):
    rec = db.payments.get(payment_id)
    if rec is None:
        fail("ERR_PAYMENT_NOT_FOUND", "payment %s does not exist" % payment_id)
    return rec


def get_late_fee(fee_id):
    rec = db.late_fees.get(fee_id)
    if rec is None:
        fail("ERR_LATE_FEE_NOT_FOUND", "late fee %s does not exist" % fee_id)
    return rec


def get_cancel_request(request_id):
    rec = db.cancel_requests.get(request_id)
    if rec is None:
        fail("ERR_CANCEL_REQUEST_NOT_FOUND", "carrier cancellation request %s does not exist" % request_id)
    return rec


def get_endorsement(endorsement_id):
    rec = db.endorsements.get(endorsement_id)
    if rec is None:
        fail("ERR_ENDORSEMENT_NOT_FOUND", "endorsement %s does not exist" % endorsement_id)
    return rec


def get_chargeback(chargeback_id):
    rec = db.chargebacks.get(chargeback_id)
    if rec is None:
        fail("ERR_CHARGEBACK_NOT_FOUND", "chargeback %s does not exist" % chargeback_id)
    return rec


# ---------------------------------------------------------------------------
# Collection queries
# ---------------------------------------------------------------------------

def licenses_of_rule(rule_id):
    return ordered([r for r in db.licenses.values() if r["state_rule_id"] == rule_id])


def policies_of_agreement(agreement_id):
    return ordered([r for r in db.policies.values() if r["agreement_id"] == agreement_id])


def verifications_of_policy(policy_id):
    return ordered([r for r in db.verifications.values() if r["policy_id"] == policy_id])


def installments_of_agreement(agreement_id):
    rows = [r for r in db.installments.values() if r["agreement_id"] == agreement_id]
    return sorted(rows, key=lambda r: r["installment_number"])


def payments_of_agreement(agreement_id):
    return ordered([r for r in db.payments.values() if r["agreement_id"] == agreement_id])


def late_fees_of_agreement(agreement_id):
    return ordered([r for r in db.late_fees.values() if r["agreement_id"] == agreement_id])


def notices_of_agreement(agreement_id):
    return ordered([r for r in db.notices.values() if r["agreement_id"] == agreement_id])


def cancel_requests_of_agreement(agreement_id):
    return ordered([r for r in db.cancel_requests.values() if r["agreement_id"] == agreement_id])


def endorsements_of_policy(policy_id):
    return ordered([r for r in db.endorsements.values() if r["policy_id"] == policy_id])


def chargebacks_of_agent(agent_id):
    return ordered([r for r in db.chargebacks.values() if r["producer_agent_id"] == agent_id])


def rule_of_agreement(agreement):
    return db.state_rules[agreement["state_rule_id"]]


# ---------------------------------------------------------------------------
# Derived fields
# ---------------------------------------------------------------------------

def license_is_effective(lic):
    if lic["status"] != "ACTIVE":
        return False
    today = clock.date()
    return (parse_date(lic["effective_date"], "effective_date") <= today
            <= parse_date(lic["expiration_date"], "expiration_date"))


def state_is_licensed(rule):
    if not rule["license_required"]:
        return True
    return any(license_is_effective(l) for l in licenses_of_rule(rule["id"]))


def active_agreement_count(rule_id):
    return sum(1 for a in db.agreements.values()
               if a["state_rule_id"] == rule_id
               and a["status"] in ("PENDING_VERIFICATION", "ACTIVE"))


def policy_count(agreement_id):
    return sum(1 for p in db.policies.values()
               if p["agreement_id"] == agreement_id and p["status"] != "CANCELLED")


def verified_policy_count(agreement_id):
    return sum(1 for p in db.policies.values()
               if p["agreement_id"] == agreement_id and p["status"] == "VERIFIED")


def outstanding_chargeback_cents(agent_id):
    return sum(c["amount_cents"] - c["offset_applied_cents"]
               for c in db.chargebacks.values()
               if c["producer_agent_id"] == agent_id
               and c["status"] in ("PENDING", "PARTIALLY_OFFSET"))


def endorsed_premium_cents(policy_id):
    return sum(e["signed_amount_cents"] for e in db.endorsements.values()
               if e["policy_id"] == policy_id and e["status"] == "FINANCED")


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------

def _base(rec, versioned=True):
    out = {"id": rec["id"], "created_at": rec["created_at"]}
    if versioned:
        out["updated_at"] = rec["updated_at"]
        out["version"] = rec["version"]
    return out


STATE_RULE_FIELDS = (
    "state_code", "finance_charge_method", "max_annual_rate_bps",
    "max_service_fee_cents", "min_down_payment_bps", "max_term_months",
    "late_fee_bps", "late_fee_min_cents", "late_fee_max_cents",
    "grace_period_days", "noic_notice_days", "unearned_premium_method",
    "short_rate_penalty_bps", "rebate_method", "max_late_fees_per_agreement",
    "license_required",
)


def ser_state_rule(rec):
    out = _base(rec)
    for f in STATE_RULE_FIELDS:
        out[f] = rec[f]
    out["active_agreement_count"] = active_agreement_count(rec["id"])
    return out


def ser_license(rec):
    out = _base(rec)
    for f in ("state_rule_id", "license_number", "status", "effective_date",
              "expiration_date"):
        out[f] = rec[f]
    out["is_effective"] = license_is_effective(rec)
    return out


def ser_insured(rec):
    out = _base(rec)
    for f in ("legal_name", "mailing_state_code", "email"):
        out[f] = rec[f]
    return out


def ser_agent(rec):
    out = _base(rec)
    for f in ("agency_name", "state_code", "agent_commission_bps",
              "chargeback_basis", "chargeback_liability_cap_cents",
              "chargeback_reserve_balance_cents", "status"):
        out[f] = rec[f]
    out["outstanding_chargeback_cents"] = outstanding_chargeback_cents(rec["id"])
    return out


def ser_insurer(rec):
    out = _base(rec)
    for f in ("carrier_name", "naic_code", "status"):
        out[f] = rec[f]
    return out


AGREEMENT_FIELDS = (
    "insured_id", "producer_agent_id", "state_rule_id",
    "restructured_from_agreement_id", "originated_by_user_id", "status",
    "delinquency_stage", "down_payment_cents", "service_fee_cents",
    "installment_count", "first_installment_due_date",
    "rate_exception_approved", "rate_exception_approved_by_user_id",
    "approved_service_fee_cap_cents", "approved_annual_rate_bps",
    "total_premium_cents", "amount_financed_cents", "effective_annual_rate_bps",
    "finance_charge_cents", "total_of_payments_cents", "quote_basis",
    "principal_balance_cents", "unpaid_finance_charge_cents",
    "late_fee_balance_cents", "late_fee_count", "unapplied_credit_cents",
    "unearned_premium_received_cents", "deficiency_balance_cents",
    "refund_due_cents", "agent_chargeback_cents", "carried_over_balance_cents",
    "activated_at",
)


def ser_agreement(rec):
    out = _base(rec)
    for f in AGREEMENT_FIELDS:
        out[f] = rec[f]
    out["policy_count"] = policy_count(rec["id"])
    out["verified_policy_count"] = verified_policy_count(rec["id"])
    return out


POLICY_FIELDS = (
    "agreement_id", "insurer_id", "policy_number", "gross_premium_cents",
    "effective_date", "expiration_date", "min_earned_days", "fully_earned",
    "carried_over", "status", "verified_premium_cents",
    "verified_effective_date", "dispute_reason", "financed_premium_cents",
    "cancellation_effective_date", "earned_days",
    "unearned_premium_estimate_cents", "unearned_premium_returned_cents",
)


def ser_policy(rec):
    out = _base(rec)
    for f in POLICY_FIELDS:
        out[f] = rec[f]
    out["endorsed_premium_cents"] = endorsed_premium_cents(rec["id"])
    return out


def ser_verification(rec):
    out = _base(rec, versioned=False)
    for f in ("policy_id", "party", "party_user_id", "decision",
              "corrected_premium_cents", "corrected_effective_date",
              "effective_premium_cents", "effective_date_asserted", "note",
              "superseded"):
        out[f] = rec[f]
    return out


def ser_installment(rec):
    out = _base(rec)
    for f in ("agreement_id", "installment_number", "due_date", "amount_cents",
              "principal_component_cents", "finance_charge_component_cents",
              "paid_cents", "status"):
        out[f] = rec[f]
    return out


def ser_payment(rec):
    out = _base(rec)
    for f in ("agreement_id", "amount_cents", "received_date", "method",
              "status", "applied_late_fee_cents", "applied_finance_charge_cents",
              "applied_principal_cents", "applied_unapplied_cents",
              "rebate_applied_cents", "allocation_variant", "reversal_reason",
              "reversed_at"):
        out[f] = rec[f]
    return out


def ser_late_fee(rec):
    out = _base(rec)
    for f in ("agreement_id", "installment_number", "assessed_date",
              "amount_cents", "status", "waived_by_user_id"):
        out[f] = rec[f]
    return out


def ser_notice(rec):
    out = _base(rec)
    for f in ("agreement_id", "issued_date", "issued_by_user_id", "notice_days",
              "effective_cancel_date", "past_due_amount_cents", "status",
              "cured_date", "executed_date"):
        out[f] = rec[f]
    return out


def ser_cancel_request(rec):
    out = _base(rec)
    for f in ("agreement_id", "policy_id", "requested_date",
              "cancellation_effective_date", "requested_by_user_id",
              "computed_unearned_premium_cents", "estimate_method",
              "carrier_returned_cents", "variance_cents", "status"):
        out[f] = rec[f]
    return out


def ser_endorsement(rec):
    out = _base(rec)
    for f in ("policy_id", "endorsement_type", "amount_cents", "effective_date",
              "status", "signed_amount_cents", "financed_at"):
        out[f] = rec[f]
    return out


def ser_chargeback(rec):
    out = _base(rec)
    for f in ("producer_agent_id", "agreement_id", "amount_cents", "basis",
              "offset_applied_cents", "status", "reason"):
        out[f] = rec[f]
    return out
