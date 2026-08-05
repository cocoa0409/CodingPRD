"""Composite setup helpers.

Every helper takes the ApiClient as its first argument and builds all required
preconditions from scratch using only PRD-declared endpoints. The test harness
restarts the server (empty DB, logical clock reset to 2026-05-01T00:00:00Z)
before every test, so nothing is carried over.

Setup calls use get_success_data() (lenient) so a broken precondition surfaces
as a clear "Setup step failed" error rather than a confusing assertion failure.

Ownership: Operator-only actions (file/amend a return, submit an appeal, provide
appeal info) thread make_operator_headers(operator["id"]). Shared creates use the
TaxAdmin identity, matching the design-index setup chains.
"""
from prd_bench_local_runner.testing import get_success_data

from .factories import (
    create_jurisdiction_payload, create_operator_payload, create_property_payload,
    create_ota_platform_payload, create_ota_agreement_payload,
    create_return_payload, single_line, create_exemption_payload,
    create_remittance_payload, create_audit_payload, propose_assessment_payload,
    submit_appeal_payload, decide_appeal_payload, create_refund_claim_payload,
)
from .test_users import TEST_USERS, make_operator_headers

ADMIN = TEST_USERS["taxadmin_headers"]
AUDITOR = TEST_USERS["auditor_headers"]


def op_headers(operator_id: str) -> dict:
    return make_operator_headers(operator_id)


# ----------------------------------------------------------------------
# Clock
# ----------------------------------------------------------------------
def set_clock(api, iso: str):
    """Advance/reset the server logical clock to the given ISO 8601 instant."""
    return get_success_data(api.set_clock({"to_iso8601": iso}, ADMIN))


# ----------------------------------------------------------------------
# Tier 1: base entities & operator state progression
# ----------------------------------------------------------------------
def create_jurisdiction(api, **overrides) -> dict:
    return get_success_data(api.create_jurisdiction(create_jurisdiction_payload(**overrides), ADMIN))


def create_operator(api, jurisdiction_id, **overrides) -> dict:
    """Create a PENDING operator."""
    return get_success_data(
        api.create_operator(create_operator_payload(jurisdiction_id, **overrides), ADMIN)
    )


def activate_operator(api, operator_id) -> dict:
    return get_success_data(api.activate_operator(operator_id, ADMIN))


def create_active_operator(api, jurisdiction_id=None, jur_overrides=None, **op_overrides) -> dict:
    """Create a jurisdiction (if none given), an operator, and activate it.

    Returns the activated operator dict (status ACTIVE, certificate minted)."""
    if jurisdiction_id is None:
        jurisdiction_id = create_jurisdiction(api, **(jur_overrides or {}))["id"]
    op = create_operator(api, jurisdiction_id, **op_overrides)
    activate_operator(api, op["id"])
    return get_success_data(api.get_operator(op["id"], ADMIN))


def create_property(api, operator_id, **overrides) -> dict:
    return get_success_data(api.create_property(create_property_payload(operator_id, **overrides), ADMIN))


def setup_operator_with_property(api, jur_overrides=None, op_overrides=None) -> dict:
    """Active operator + one property under it.

    Returns {"jurisdiction_id", "operator", "property"}."""
    jur = create_jurisdiction(api, **(jur_overrides or {}))
    op = create_active_operator(api, jurisdiction_id=jur["id"], **(op_overrides or {}))
    prop = create_property(api, op["id"])
    return {"jurisdiction_id": jur["id"], "jurisdiction": jur, "operator": op, "property": prop}


def get_operator(api, operator_id) -> dict:
    return get_success_data(api.get_operator(operator_id, ADMIN))


# ----------------------------------------------------------------------
# Tier 2/3: returns, exemptions, remittances
# ----------------------------------------------------------------------
def create_draft_return(api, operator_id, line_items, period_start=None, period_end=None, **overrides) -> dict:
    kwargs = dict(overrides)
    if period_start is not None:
        kwargs["period_start"] = period_start
    if period_end is not None:
        kwargs["period_end"] = period_end
    return get_success_data(
        api.create_return(create_return_payload(operator_id, line_items, **kwargs), ADMIN)
    )


def file_return(api, return_id, operator_id) -> dict:
    """File a return as its owning operator (ownership-gated)."""
    return get_success_data(api.file_return(return_id, op_headers(operator_id)))


def amend_return(api, return_id, operator_id, line_items=None) -> dict:
    payload = {"line_items": line_items} if line_items is not None else {}
    return get_success_data(api.amend_return(return_id, op_headers(operator_id), payload))


def create_and_file_return(api, operator_id, line_items, period_start=None, period_end=None, **overrides) -> dict:
    """Create a draft return then file it. Returns the FILED return."""
    ret = create_draft_return(api, operator_id, line_items, period_start, period_end, **overrides)
    return file_return(api, ret["id"], operator_id)


def create_exemption(api, tax_return_id, exemption_type, amount_cents, **overrides) -> dict:
    return get_success_data(
        api.create_exemption(
            create_exemption_payload(tax_return_id, exemption_type, amount_cents, **overrides), ADMIN
        )
    )


def verify_exemption(api, exemption_id) -> dict:
    return get_success_data(api.verify_exemption(exemption_id, ADMIN))


def reject_exemption(api, exemption_id) -> dict:
    return get_success_data(api.reject_exemption(exemption_id, ADMIN))


def create_remittance(api, tax_return_id, amount_cents, remitter="OPERATOR", **overrides) -> dict:
    return get_success_data(
        api.create_remittance(
            create_remittance_payload(tax_return_id, amount_cents, remitter, **overrides), ADMIN
        )
    )


def clear_remittance(api, remittance_id) -> dict:
    return get_success_data(api.clear_remittance(remittance_id, ADMIN))


def reverse_remittance(api, remittance_id) -> dict:
    return get_success_data(api.reverse_remittance(remittance_id, ADMIN))


def create_cleared_remittance(api, tax_return_id, amount_cents, remitter="OPERATOR", **overrides) -> dict:
    rem = create_remittance(api, tax_return_id, amount_cents, remitter, **overrides)
    return clear_remittance(api, rem["id"])


# ----------------------------------------------------------------------
# Tier 3: OTA platform / agreement
# ----------------------------------------------------------------------
def create_ota_platform(api, **overrides) -> dict:
    return get_success_data(api.create_ota_platform(create_ota_platform_payload(**overrides), ADMIN))


def create_ota_agreement(api, operator_id, platform_id, **overrides) -> dict:
    return get_success_data(
        api.create_ota_agreement(create_ota_agreement_payload(operator_id, platform_id, **overrides), ADMIN)
    )


def activate_ota_agreement(api, agreement_id) -> dict:
    return get_success_data(api.activate_ota_agreement(agreement_id, ADMIN))


# ----------------------------------------------------------------------
# Tier 4: audits, assessments, appeals
# ----------------------------------------------------------------------
def open_audit(api, operator_id, period_start=None, period_end=None, **overrides) -> dict:
    kwargs = dict(overrides)
    if period_start is not None:
        kwargs["period_start"] = period_start
    if period_end is not None:
        kwargs["period_end"] = period_end
    return get_success_data(api.create_audit(create_audit_payload(operator_id, **kwargs), AUDITOR))


def begin_fieldwork(api, audit_id) -> dict:
    return get_success_data(api.begin_fieldwork(audit_id, AUDITOR))


def propose_assessment(api, audit_id, audited_taxable_cents, classification="NEGLIGENCE") -> dict:
    return get_success_data(
        api.propose_assessment(audit_id, propose_assessment_payload(audited_taxable_cents, classification), AUDITOR)
    )


def issue_assessment(api, assessment_id) -> dict:
    return get_success_data(api.issue_assessment(assessment_id, ADMIN))


def record_response(api, audit_id) -> dict:
    return get_success_data(api.record_response(audit_id, AUDITOR))


def reopen_fieldwork(api, audit_id) -> dict:
    return get_success_data(api.reopen_fieldwork(audit_id, AUDITOR))


def setup_proposed_assessment(api, gross=1000000, audited_taxable_cents=6000000,
                              classification="NEGLIGENCE", period_start=None, period_end=None) -> dict:
    """Active operator + property + FILED return + audit through PROPOSED.

    Returns {"operator", "property", "return", "audit", "assessment"}."""
    base = setup_operator_with_property(api)
    op, prop = base["operator"], base["property"]
    ret = create_and_file_return(api, op["id"], single_line(prop["id"], gross), period_start, period_end)
    aud = open_audit(api, op["id"], period_start, period_end)
    begin_fieldwork(api, aud["id"])
    asmt = propose_assessment(api, aud["id"], audited_taxable_cents, classification)
    return {"jurisdiction_id": base["jurisdiction_id"], "operator": op, "property": prop,
            "return": ret, "audit": aud, "assessment": asmt}


def setup_issued_assessment(api, gross=1000000, audited_taxable_cents=6000000,
                            classification="NEGLIGENCE", pay_full=True) -> dict:
    """Active operator; return FILED (on-time) and optionally fully paid;
    audit -> PROPOSED -> assessment ISSUED. Returns the same bundle plus fresh
    operator state after issuance."""
    bundle = setup_proposed_assessment(api, gross=gross, audited_taxable_cents=audited_taxable_cents,
                                       classification=classification)
    if pay_full:
        tax = bundle["return"]["tax_due_cents"]
        if tax > 0:
            create_cleared_remittance(api, bundle["return"]["id"], tax)
    issue_assessment(api, bundle["assessment"]["id"])
    bundle["operator"] = get_operator(api, bundle["operator"]["id"])
    bundle["assessment"] = get_success_data(api.get_assessment(bundle["assessment"]["id"], ADMIN))
    return bundle


def submit_appeal(api, assessment_id, operator_id, grounds="taxpayer disagrees") -> dict:
    return get_success_data(
        api.submit_appeal(assessment_id, submit_appeal_payload(grounds), op_headers(operator_id))
    )


def begin_review(api, appeal_id) -> dict:
    return get_success_data(api.begin_review(appeal_id, ADMIN))


def request_info(api, appeal_id) -> dict:
    return get_success_data(api.request_info(appeal_id, ADMIN))


def provide_info(api, appeal_id, operator_id) -> dict:
    return get_success_data(api.provide_info(appeal_id, op_headers(operator_id)))


def decide_appeal(api, appeal_id, decision, reduced_total_cents=None) -> dict:
    payload = decide_appeal_payload(decision)
    if reduced_total_cents is not None:
        payload["reduced_total_cents"] = reduced_total_cents
    return get_success_data(api.decide_appeal(appeal_id, payload, ADMIN))


# ----------------------------------------------------------------------
# Tier 4: liens & refunds
# ----------------------------------------------------------------------
def record_lien(api, operator_id, expected_operator_version) -> dict:
    return get_success_data(
        api.record_lien(operator_id, {"expected_operator_version": expected_operator_version}, ADMIN)
    )


def create_refund_claim(api, operator_id, reason, principal_cents, overpayment_date, **overrides) -> dict:
    return get_success_data(
        api.create_refund_claim(
            create_refund_claim_payload(operator_id, reason, principal_cents, overpayment_date, **overrides), ADMIN
        )
    )


# ----------------------------------------------------------------------
# Composite: DELINQUENT operator with a RECORDED lien (past-due return)
# ----------------------------------------------------------------------
def setup_delinquent_with_return(api, gross=5000000, lien_threshold_cents=500000,
                                 file_clock="2026-03-15T00:00:00Z",
                                 period_start="2026-01-01T00:00:00Z",
                                 period_end="2026-01-31T00:00:00Z") -> dict:
    """Active operator; past-due FILED return -> operator DELINQUENT.

    Returns {"operator", "property", "return"} with the operator refreshed."""
    base = setup_operator_with_property(api, jur_overrides={"lien_threshold_cents": lien_threshold_cents})
    op, prop = base["operator"], base["property"]
    ret = create_draft_return(api, op["id"], single_line(prop["id"], gross),
                              period_start=period_start, period_end=period_end)
    set_clock(api, file_clock)
    ret = file_return(api, ret["id"], op["id"])
    return {"jurisdiction_id": base["jurisdiction_id"], "operator": get_operator(api, op["id"]),
            "property": prop, "return": ret}
