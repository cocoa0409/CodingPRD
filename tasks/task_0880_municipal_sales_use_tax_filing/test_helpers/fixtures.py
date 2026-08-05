"""Composite setup helpers.

Every helper builds its preconditions from scratch using only PRD-declared
endpoints (the server database is empty at the start of each test). Setup calls
use get_success_data() (lenient) so a broken precondition surfaces as a clear
"Setup failed" rather than a confusing assertion failure.

Each helper takes the ApiClient as its first argument.
"""
from prd_bench_local_runner.testing import get_success_data
from .factories import (
    create_taxpayer_payload,
    create_jurisdiction_payload,
    create_return_payload,
    create_return_line,
    create_certificate_payload,
    create_remittance_payload,
    create_audit_payload,
    create_assessment_payload,
    create_appeal_payload,
    create_refund_claim_payload,
)
from .test_users import (
    make_admin_headers,
    make_auditor_headers,
    make_officer_headers,
    make_taxpayer_headers,
    make_anonymous_headers,
)


# --------------------------------------------------------------------------
# Logical clock
# --------------------------------------------------------------------------
def set_clock(api, to_iso8601):
    """Advance the logical clock (TaxAdmin-only)."""
    return get_success_data(api.set_clock(to_iso8601, make_admin_headers()))


# --------------------------------------------------------------------------
# Tier 1: single-entity creation / state progression
# --------------------------------------------------------------------------
def register_taxpayer(api, **overrides):
    """Public registration -> a PENDING taxpayer."""
    return get_success_data(
        api.create_taxpayer(create_taxpayer_payload(**overrides), make_anonymous_headers())
    )


def create_active_taxpayer(api, **overrides):
    """Register + activate -> an ACTIVE taxpayer (activate response is the ACTIVE entity)."""
    tp = register_taxpayer(api, **overrides)
    return get_success_data(api.activate_taxpayer(tp["id"], make_admin_headers()))


def create_suspended_taxpayer(api, suspend_reason="Delinquent", **overrides):
    """Register + activate + suspend -> a SUSPENDED taxpayer."""
    tp = create_active_taxpayer(api, **overrides)
    return get_success_data(
        api.suspend_taxpayer(tp["id"], {"suspend_reason": suspend_reason}, make_admin_headers())
    )


def create_jurisdiction(api, **overrides):
    return get_success_data(
        api.create_jurisdiction(create_jurisdiction_payload(**overrides), make_admin_headers())
    )


def create_certificate(api, taxpayer_id, **overrides):
    return get_success_data(
        api.create_certificate(
            create_certificate_payload(taxpayer_id, **overrides),
            make_taxpayer_headers(taxpayer_id),
        )
    )


def create_remittance(api, taxpayer_id, amount_cents=100000,
                      remittance_type="PAYMENT", **overrides):
    return get_success_data(
        api.create_remittance(
            create_remittance_payload(taxpayer_id, amount_cents, remittance_type, **overrides),
            make_taxpayer_headers(taxpayer_id),
        )
    )


# --------------------------------------------------------------------------
# Tier 2: returns
# --------------------------------------------------------------------------
def create_draft_return(api, taxpayer_id, jurisdiction_id=None, lines=None, **overrides):
    """Create a DRAFT return. Provide jurisdiction_id (single default line) or explicit lines."""
    payload = create_return_payload(taxpayer_id, jurisdiction_id=jurisdiction_id,
                                     lines=lines, **overrides)
    return get_success_data(
        api.create_return(payload, make_taxpayer_headers(taxpayer_id))
    )


def file_return(api, taxpayer_id, return_id):
    """File a DRAFT/AMENDING return. Returns the FILED entity (carries the new version)."""
    return get_success_data(
        api.file_return(return_id, make_taxpayer_headers(taxpayer_id))
    )


def create_filed_return(api, taxpayer_id, jurisdiction_id=None, lines=None, **overrides):
    """Create then file a return -> the FILED entity (carries version and net_return_due_cents)."""
    ret = create_draft_return(api, taxpayer_id, jurisdiction_id=jurisdiction_id,
                              lines=lines, **overrides)
    return file_return(api, taxpayer_id, ret["id"])


def setup_active_taxpayer_with_filed_return(api, gross_sales_cents=1000000,
                                            exempt_sales_cents=200000,
                                            rate_bps=850, **return_overrides):
    """ACTIVE taxpayer + one jurisdiction + one FILED return.

    Returns (taxpayer, jurisdiction, filed_return). The filed_return dict carries
    its post-file `version`, `net_return_due_cents`, and `tax_due_cents`.
    """
    tp = create_active_taxpayer(api)
    jur = create_jurisdiction(api, rate_bps=rate_bps)
    line = create_return_line(jur["id"], gross_sales_cents=gross_sales_cents,
                              exempt_sales_cents=exempt_sales_cents)
    filed = create_filed_return(api, tp["id"], lines=[line], **return_overrides)
    return tp, jur, filed


# --------------------------------------------------------------------------
# Tier 3: audits & assessments
# --------------------------------------------------------------------------
def open_field_audit(api, taxpayer_id, period_key="2026-Q1", auditor_id="aud-1"):
    return get_success_data(
        api.create_audit(
            create_audit_payload(taxpayer_id, audit_type="FIELD_AUDIT", period_key=period_key),
            make_auditor_headers(auditor_id),
        )
    )


def open_nexus_audit(api, taxpayer_id, gross_receipts_cents, period_key="2026",
                     auditor_id="aud-1"):
    return get_success_data(
        api.create_audit(
            create_audit_payload(taxpayer_id, audit_type="NEXUS_DISCOVERY",
                                 period_key=period_key,
                                 gross_receipts_cents=gross_receipts_cents),
            make_auditor_headers(auditor_id),
        )
    )


def create_late_filing_assessment(api, taxpayer_id, tax_deficiency_cents=100000,
                                  original_due_date="2026-01-20T00:00:00Z",
                                  auditor_id="aud-1", **overrides):
    """Issue a LATE_FILING assessment directly. Clock should already be set."""
    return get_success_data(
        api.create_assessment(
            create_assessment_payload(taxpayer_id,
                                      tax_deficiency_cents=tax_deficiency_cents,
                                      assessment_type="LATE_FILING",
                                      original_due_date=original_due_date, **overrides),
            make_auditor_headers(auditor_id),
        )
    )


def close_audit_assessed(api, audit_id, tax_deficiency_cents=100000,
                         original_due_date="2026-01-20T00:00:00Z",
                         return_id=None, auditor_id="aud-1"):
    payload = {
        "outcome": "ASSESSED",
        "tax_deficiency_cents": tax_deficiency_cents,
        "original_due_date": original_due_date,
    }
    if return_id is not None:
        payload["return_id"] = return_id
    return get_success_data(
        api.close_audit(audit_id, payload, make_auditor_headers(auditor_id))
    )


def find_assessment_for_audit(api, audit_id):
    """Return the Assessment created by an ASSESSED audit close (via audit_id filter)."""
    data, _ = _list(api, api.list_assessments, params={"audit_id": audit_id})
    assert data, f"no assessment found for audit_id={audit_id}"
    return data[0]


# --------------------------------------------------------------------------
# Tier 4: appeals
# --------------------------------------------------------------------------
def create_submitted_appeal(api, assessment_id, taxpayer_id, grounds="Dispute."):
    return get_success_data(
        api.create_appeal(
            create_appeal_payload(assessment_id, grounds=grounds),
            make_taxpayer_headers(taxpayer_id),
        )
    )


# --------------------------------------------------------------------------
# Tier 5: refunds & remittance application
# --------------------------------------------------------------------------
def create_open_refund_claim(api, taxpayer_id, return_id, expected_return_version,
                             claim_amount_cents=5000, reason="TAXPAYER_ERROR",
                             overpayment_date="2026-04-01T00:00:00Z", **overrides):
    return get_success_data(
        api.create_refund_claim(
            create_refund_claim_payload(taxpayer_id, return_id, expected_return_version,
                                        claim_amount_cents=claim_amount_cents,
                                        reason=reason, overpayment_date=overpayment_date,
                                        **overrides),
            make_taxpayer_headers(taxpayer_id),
        )
    )


def apply_remittance(api, remittance_id, return_id, apply_amount_cents, taxpayer_id):
    return get_success_data(
        api.apply_remittance(
            remittance_id,
            {"applied_return_id": return_id, "apply_amount_cents": apply_amount_cents},
            make_taxpayer_headers(taxpayer_id),
        )
    )


# --------------------------------------------------------------------------
# Read helpers
# --------------------------------------------------------------------------
def get_taxpayer(api, taxpayer_id):
    return get_success_data(api.get_taxpayer(taxpayer_id, make_admin_headers()))


def get_return(api, return_id):
    return get_success_data(api.get_return(return_id, make_admin_headers()))


def get_assessment(api, assessment_id):
    return get_success_data(api.get_assessment(assessment_id, make_admin_headers()))


def get_refund_claim(api, refund_id):
    return get_success_data(api.get_refund_claim(refund_id, make_admin_headers()))


def get_remittance(api, remittance_id):
    return get_success_data(api.get_remittance(remittance_id, make_admin_headers()))


def get_appeal(api, appeal_id):
    return get_success_data(api.get_appeal(appeal_id, make_admin_headers()))


def get_audit(api, audit_id):
    return get_success_data(api.get_audit(audit_id, make_admin_headers()))


def _list(api, list_method, params=None):
    """Return (data_list, meta_dict) from a list endpoint using an admin caller."""
    from prd_bench_local_runner.testing import validate_paginated
    return validate_paginated(list_method(make_admin_headers(), params=params))
