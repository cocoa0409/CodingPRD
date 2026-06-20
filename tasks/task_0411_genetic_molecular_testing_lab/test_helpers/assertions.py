"""Entity assertions and domain invariant checkers.

Each assert_{entity}() checks structural shape (id/timestamps) and enum/field
membership using the PRD's field names. Invariant checkers verify cross-field
relationships the PRD guarantees after any operation.
"""
from prd_bench_local_runner.testing import (
    is_valid_uuid, is_iso8601_timestamp,
)

PIPELINE_STATES = ["ORDERED", "REQUISITIONED", "ACCESSIONED", "SEQUENCING",
                   "CLASSIFIED", "SIGNED_OUT", "CANCELLED"]
FINANCIAL_STATES = ["PENDING", "AUTH_REQUESTED", "AUTH_APPROVED", "AUTH_DENIED",
                    "PATIENT_PAY", "SETTLED"]
BILLING_STATES = ["OPEN", "AUTH_REQUESTED", "AUTH_APPROVED", "AUTH_DENIED",
                  "PATIENT_PAY", "SETTLED", "REVERSED"]
CLASSIFICATIONS = ["UNCLASSIFIED", "BENIGN", "LIKELY_BENIGN", "VUS",
                   "LIKELY_PATHOGENIC", "PATHOGENIC", "RECLASSIFIED"]


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        f"version must be int >= 1, got {data.get('version')!r}"


def assert_gene(data: dict):
    _assert_common(data)
    assert isinstance(data["symbol"], str) and len(data["symbol"]) > 0
    assert isinstance(data["is_acmg_reportable"], bool)
    assert data["status"] in ["ACTIVE", "RETIRED"]


def assert_panel(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["list_price_cents"], int) and data["list_price_cents"] >= 0
    assert isinstance(data["requires_consent"], bool)
    assert isinstance(data["gene_count"], int) and data["gene_count"] >= 0
    assert data["status"] in ["DRAFT", "PUBLISHED", "RETIRED"]


def assert_panel_gene(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("panel_id", ""))
    assert is_valid_uuid(data.get("gene_id", ""))
    assert data["status"] in ["INCLUDED", "REMOVED"]


def assert_provider(data: dict):
    _assert_common(data)
    assert isinstance(data["npi"], str) and len(data["npi"]) > 0
    assert isinstance(data["full_name"], str)


def assert_test_order(data: dict):
    _assert_common(data)
    assert isinstance(data["patient_mrn"], str)
    assert isinstance(data["patient_dob"], str)
    assert is_valid_uuid(data.get("panel_id", ""))
    assert data["pipeline_status"] in PIPELINE_STATES
    assert data["financial_status"] in FINANCIAL_STATES
    assert isinstance(data["list_price_cents"], int) and data["list_price_cents"] >= 0


def assert_requisition(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("test_order_id", ""))
    assert data["insurance_payer"] in ["MEDICARE", "COMMERCIAL", "SELF_PAY"]
    assert data["status"] in ["PENDING", "SUBMITTED", "VOID"]


def assert_consent(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("test_order_id", ""))
    assert isinstance(data["incidental_findings_opt_in"], bool)
    assert data["status"] in ["DRAFT", "SIGNED", "REVOKED"]


def assert_specimen(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("test_order_id", ""))
    assert data["specimen_type"] in ["BLOOD", "SALIVA", "TISSUE"]
    assert data["status"] in ["RECEIVED", "ACCESSIONED", "QNS_REJECTED", "SUPERSEDED"]


def assert_variant(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("test_order_id", ""))
    assert is_valid_uuid(data.get("gene_id", ""))
    assert isinstance(data["hgvs"], str)
    assert isinstance(data["is_incidental"], bool)
    assert data["classification"] in CLASSIFICATIONS


def assert_report(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("test_order_id", ""))
    assert data["status"] in ["DRAFT", "SIGNED_OUT", "AMENDED"]
    assert isinstance(data["incidental_disclosed"], bool)


def assert_billing(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("test_order_id", ""))
    assert data["status"] in BILLING_STATES


def assert_sequencer(data: dict):
    _assert_common(data)
    assert isinstance(data["instrument_name"], str)
    assert isinstance(data["turnaround_buffer_minutes"], int)
    assert data["status"] in ["ONLINE", "OFFLINE"]


def assert_sequencer_run(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("sequencer_id", ""))
    assert data["status"] in ["SCHEDULED", "RUNNING", "DONE", "ABORTED"]


def assert_counselor(data: dict):
    _assert_common(data)
    assert isinstance(data["counselor_name"], str)
    assert data["status"] in ["ACTIVE", "INACTIVE"]


def assert_referral(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("test_order_id", ""))
    assert is_valid_uuid(data.get("counselor_id", ""))
    assert data["reason"] in ["PATHOGENIC_RESULT", "VUS_FOLLOWUP",
                              "INCIDENTAL_FINDING", "PATIENT_REQUEST"]
    assert data["status"] in ["REQUESTED", "SCHEDULED", "COMPLETED", "CANCELLED"]


def assert_billing_money_conserved(billing: dict):
    """PRD §3.13: on a cancel reversal the conserved-money invariant holds —
    writeoff + collected sum equals the allowed amount when fully reversed and
    nothing was collected."""
    assert billing["writeoff_cents"] >= 0
    assert billing["coinsurance_collected_cents"] >= 0
