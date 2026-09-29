"""Entity field lists, serializers and path/foreign-key resolution."""
from errors import ApiError
from store import db
from web import serialize

GROUP_FIELDS = [
    "name", "base_state_code", "fiscal_year_end_month",
    "everywhere_sales", "everywhere_property", "everywhere_payroll",
    "open_registration_obligations", "compliance_posture", "nowhere_sales_pool",
]

LEGAL_ENTITY_FIELDS = [
    "group_id", "name", "entity_type", "incorporation_state_code",
    "is_unitary_member", "vda_shield_until",
]

REGISTRATION_FIELDS = [
    "group_id", "state_code", "factor_formula", "tax_rate", "throwback_rule",
    "service_sourcing_rule", "economic_nexus_sales_threshold",
    "economic_nexus_employee_days_threshold", "nexus_status", "registration_status",
    "state_account_number", "registered_on_date", "due_month", "due_day",
    "extension_months", "estimated_installment_count", "safe_harbor_basis",
    "prior_year_tax", "current_year_estimated_tax", "state_permits_early_revocation",
    "calendar_rolled_through_year", "total_payments_received", "unapplied_payment_balance",
]

ACTIVITY_FIELDS = [
    "registration_id", "legal_entity_id", "tax_year", "destination_sales",
    "origin_sales", "purchaser_taxable_in_state", "service_receipts",
    "cost_of_performance_state_code", "property_average_value",
    "rented_property_annual_rent", "payroll_compensation", "employee_days_in_state",
    "protected_solicitation_only",
]

ELECTION_FIELDS = [
    "registration_id", "election_basis", "effective_tax_year", "binding_years",
    "expires_after_tax_year", "status", "revocation_tax_year",
    "reinstatement_count", "reason",
]

FILING_FIELDS = [
    "registration_id", "election_id", "primary_legal_entity_id", "tax_year",
    "filing_basis", "federal_taxable_income", "apportionment_variant",
    "preparation_status", "payment_status", "apportionment_percentage",
    "modification_total", "state_taxable_income", "tax_before_credits",
    "credits_applied_total", "estimated_credits_applied", "assessment_added_total",
    "balance_due", "original_due_date", "extended_due_date", "preparer_user_id",
    "approver_user_id", "confirmation_number", "filed_on_date", "amendment_count",
]

FACTOR_FIELDS = [
    "filing_id", "factor_type", "numerator", "denominator", "ratio", "weight",
    "included", "throwback_added", "throwout_removed",
]

MODIFICATION_FIELDS = [
    "filing_id", "modification_code", "direction", "raw_amount",
    "allocation_ratio", "line_amount", "sequence_number",
]

CREDIT_FIELDS = [
    "filing_id", "credit_code", "granted_amount", "refundable", "priority_order",
    "expires_after_years", "applied_amount", "carryforward_amount",
    "expired_amount", "status",
]

PAYMENT_FIELDS = [
    "registration_id", "applied_filing_id", "tax_year", "installment_number",
    "amount", "paid_on_date", "due_date", "is_timely",
    "safe_harbor_required_amount", "underpayment_amount", "underpayment_penalty",
    "status",
]

EXTENSION_FIELDS = [
    "filing_id", "estimated_tax_paid", "requested_on_date", "required_prepayment",
    "status", "new_due_date", "state_confirmation",
]

NOTICE_FIELDS = [
    "filing_id", "notice_type", "state_notice_number", "assessed_tax", "notice_date",
    "response_due_days", "response_due_date", "appeal_due_date", "status",
    "response_round", "contested_amount", "sustained_amount", "penalty_amount",
    "interest_amount", "assessment_final_amount",
]

VDA_FIELDS = [
    "registration_id", "legal_entity_id", "anchor_tax_year", "lookback_years",
    "exposure_variant", "estimated_exposure_tax", "effective_lookback_years",
    "lookback_start_year", "lookback_end_year", "computed_exposure_tax",
    "waived_penalty_amount", "negotiated_tax", "negotiated_interest",
    "settlement_total", "status", "executed_on_date", "shield_expires_at",
]


def ser_group(r):
    return serialize(r, GROUP_FIELDS)


def ser_legal_entity(r):
    return serialize(r, LEGAL_ENTITY_FIELDS)


def ser_registration(r):
    return serialize(r, REGISTRATION_FIELDS)


def ser_activity(r):
    return serialize(r, ACTIVITY_FIELDS, versioned=False)


def ser_election(r):
    return serialize(r, ELECTION_FIELDS)


def ser_filing(r):
    return serialize(r, FILING_FIELDS)


def ser_factor(r):
    return serialize(r, FACTOR_FIELDS)


def ser_modification(r):
    return serialize(r, MODIFICATION_FIELDS)


def ser_credit(r):
    return serialize(r, CREDIT_FIELDS)


def ser_payment(r):
    return serialize(r, PAYMENT_FIELDS)


def ser_extension(r):
    return serialize(r, EXTENSION_FIELDS)


def ser_notice(r):
    return serialize(r, NOTICE_FIELDS)


def ser_vda(r):
    return serialize(r, VDA_FIELDS)


# --------------------------------------------------------------------------
# Lookups.  Each entity has its own not-found code (PRD 2.7).
# --------------------------------------------------------------------------
def _lookup(table, key, error_id, label):
    if not isinstance(key, str):
        raise ApiError(error_id, "%s not found." % label)
    record = table.get(key)
    if record is None:
        raise ApiError(error_id, "%s not found." % label)
    return record


def find_group(gid):
    return _lookup(db.groups, gid, "ERR_GROUP_NOT_FOUND", "Taxpayer group")


def find_legal_entity(eid):
    return _lookup(db.legal_entities, eid, "ERR_LEGAL_ENTITY_NOT_FOUND", "Legal entity")


def find_registration(rid):
    return _lookup(db.registrations, rid, "ERR_REGISTRATION_NOT_FOUND", "State registration")


def find_activity(aid):
    return _lookup(db.activity_records, aid, "ERR_ACTIVITY_RECORD_NOT_FOUND", "Activity record")


def find_election(eid):
    return _lookup(db.elections, eid, "ERR_ELECTION_NOT_FOUND", "Filing election")


def find_filing(fid):
    return _lookup(db.filings, fid, "ERR_FILING_NOT_FOUND", "State filing")


def find_credit(cid):
    return _lookup(db.credit_claims, cid, "ERR_CREDIT_CLAIM_NOT_FOUND", "Credit claim")


def find_payment(pid):
    return _lookup(db.payments, pid, "ERR_PAYMENT_NOT_FOUND", "Estimated payment")


def find_extension(xid):
    return _lookup(db.extensions, xid, "ERR_EXTENSION_NOT_FOUND", "Extension request")


def find_notice(nid):
    return _lookup(db.notices, nid, "ERR_NOTICE_NOT_FOUND", "Notice")


def find_vda(vid):
    return _lookup(db.vdas, vid, "ERR_VDA_NOT_FOUND", "Voluntary disclosure agreement")
