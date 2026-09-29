"""Payload factories: valid-by-default request bodies with keyword overrides."""

from .constants import DEFAULT_CLOCK
from .types import (
    DocType,
    FindingSeverity,
    FindingType,
    HygieneRunType,
    PublicationFrequency,
    PurchasingAuthorityLevel,
    RequestChannel,
    RuleDimension,
    SnapshotDecision,
    SnapshotSource,
    StatementBasis,
    SubscriptionClass,
)

_counter = {"n": 0}


def next_seq():
    """Monotonic counter for unique-ish string fields inside one test."""
    _counter["n"] += 1
    return _counter["n"]


# --------------------------------------------------------------------------
# Publications and qualification rules
# --------------------------------------------------------------------------
def publication_payload(**overrides):
    payload = {
        "name": f"Plant Engineering Weekly {next_seq()}",
        "frequency": PublicationFrequency.MONTHLY.value,
        "industry_code": "MFG-311",
    }
    payload.update(overrides)
    return payload


def publication_payload_full(**overrides):
    """Registration with every policy knob stated explicitly."""
    payload = publication_payload(
        qualification_validity_months=24,
        renewal_grace_days=60,
        source_doc_retention_months=48,
        undeliverable_restrict_pct=4.50,
        materiality_pct=1.50,
        controlled_cap_pct=30.00,
    )
    payload.update(overrides)
    return payload


def qualification_rule_payload(**overrides):
    payload = {
        "dimension": RuleDimension.JOB_FUNCTION.value,
        "allowed_values": ["PLANT_ENGINEER"],
        "points": 45,
        "is_mandatory": True,
    }
    payload.update(overrides)
    return payload


def job_function_rule_payload(**overrides):
    payload = {
        "dimension": RuleDimension.JOB_FUNCTION.value,
        "allowed_values": ["PLANT_ENGINEER", "MAINTENANCE_MANAGER"],
        "points": 45,
        "is_mandatory": True,
    }
    payload.update(overrides)
    return payload


def industry_rule_payload(**overrides):
    payload = {
        "dimension": RuleDimension.INDUSTRY.value,
        "allowed_values": ["MFG-311", "MFG-312"],
        "points": 30,
        "is_mandatory": False,
    }
    payload.update(overrides)
    return payload


def purchasing_authority_rule_payload(**overrides):
    payload = {
        "dimension": RuleDimension.PURCHASING_AUTHORITY.value,
        "allowed_values": [
            PurchasingAuthorityLevel.APPROVES.value,
            PurchasingAuthorityLevel.SPECIFIES.value,
        ],
        "points": 25,
        "is_mandatory": False,
    }
    payload.update(overrides)
    return payload


def complete_rule_set_payloads():
    """One rule per dimension: 45 + 30 + 25 = 100 base points available."""
    return [
        job_function_rule_payload(),
        industry_rule_payload(),
        purchasing_authority_rule_payload(),
    ]


# --------------------------------------------------------------------------
# Recipients, evidence
# --------------------------------------------------------------------------
def subscriber_payload(publication_id, **overrides):
    payload = {
        "publication_id": publication_id,
        "company_name": f"Acme Fabrication {next_seq()}",
        "contact_email": f"ops{next_seq()}@acme-fab.example",
        "job_function_code": "PLANT_ENGINEER",
        "industry_code": "MFG-311",
        "purchasing_authority_level": PurchasingAuthorityLevel.APPROVES.value,
        "subscription_class": SubscriptionClass.QUALIFIED_NON_PAID.value,
        "copies": 1,
    }
    payload.update(overrides)
    return payload


def paid_subscriber_payload(publication_id, **overrides):
    payload = subscriber_payload(
        publication_id,
        subscription_class=SubscriptionClass.PAID.value,
        paid_amount_cents=12000,
    )
    payload.update(overrides)
    return payload


def controlled_subscriber_payload(publication_id, **overrides):
    payload = subscriber_payload(
        publication_id,
        subscription_class=SubscriptionClass.CONTROLLED.value,
    )
    payload.update(overrides)
    return payload


def reclassify_payload(subscription_class, **overrides):
    payload = {"subscription_class": subscription_class}
    payload.update(overrides)
    return payload


def undeliverable_event_payload(**overrides):
    payload = {"reason_code": "RETURNED_NO_FORWARDING"}
    payload.update(overrides)
    return payload


def source_document_payload(**overrides):
    payload = {
        "doc_type": DocType.SIGNED_REQUEST_CARD.value,
        "captured_at": "2026-07-01T00:00:00Z",
        "storage_ref": f"archive://cards/{next_seq()}",
    }
    payload.update(overrides)
    return payload


def purge_payload(**overrides):
    payload = {"purge_reason": "RETENTION_ELAPSED"}
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# Qualification requests
# --------------------------------------------------------------------------
def qualification_request_payload(
    subscriber_id, source_document_id, expected_subscriber_version, **overrides
):
    payload = {
        "subscriber_id": subscriber_id,
        "source_document_id": source_document_id,
        "expected_subscriber_version": expected_subscriber_version,
        "request_channel": RequestChannel.DIRECT_MAIL.value,
        "signed_at": "2026-07-15T00:00:00Z",
        "attested_job_function_code": "PLANT_ENGINEER",
        "attested_industry_code": "MFG-311",
        "attested_purchasing_authority": PurchasingAuthorityLevel.APPROVES.value,
    }
    payload.update(overrides)
    return payload


def review_payload(**overrides):
    payload = {"review_note": "Opened for review."}
    payload.update(overrides)
    return payload


def request_info_payload(**overrides):
    payload = {"info_request_note": "Signature illegible; please re-attest."}
    payload.update(overrides)
    return payload


def resubmit_payload(**overrides):
    payload = {}
    payload.update(overrides)
    return payload


def verify_payload(**overrides):
    payload = {"decision_reason": "Evidence supports the attestation."}
    payload.update(overrides)
    return payload


def reject_request_payload(**overrides):
    payload = {"decision_reason": "Attestation not supported by evidence."}
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# Hygiene sweeps
# --------------------------------------------------------------------------
def hygiene_run_payload(publication_id, **overrides):
    payload = {
        "publication_id": publication_id,
        "run_type": HygieneRunType.UNDELIVERABLE_SWEEP.value,
    }
    payload.update(overrides)
    return payload


def expiry_sweep_payload(publication_id, **overrides):
    payload = {
        "publication_id": publication_id,
        "run_type": HygieneRunType.EXPIRY_SWEEP.value,
    }
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# Statements
# --------------------------------------------------------------------------
def statement_payload(publication_id, expected_publication_version, **overrides):
    payload = {
        "publication_id": publication_id,
        "expected_publication_version": expected_publication_version,
        "period_start": "2026-04-01T00:00:00Z",
        "period_end": "2026-07-01T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def recompute_payload(**overrides):
    payload = {}
    payload.update(overrides)
    return payload


def certify_payload(**overrides):
    payload = {"certification_note": "Sworn by the undersigned."}
    payload.update(overrides)
    return payload


def settle_guarantees_payload(**overrides):
    payload = {"settlement_note": "Quarterly guarantee settlement."}
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# Audit engagements, sampling and findings
# --------------------------------------------------------------------------
def engagement_payload(statement_id, **overrides):
    payload = {
        "statement_id": statement_id,
        "auditor_org": "Bureau of Trade Circulation Audits",
        "fieldwork_start": "2026-07-05T00:00:00Z",
        "fieldwork_end": "2026-07-10T00:00:00Z",
        "sample_size": 1,
    }
    payload.update(overrides)
    return payload


def sample_verification_payload(subscriber_id, **overrides):
    payload = {
        "subscriber_id": subscriber_id,
        "evidence_ok": True,
        "verified_copies": 1,
    }
    payload.update(overrides)
    return payload


def issue_report_payload(**overrides):
    payload = {"report_note": "Fieldwork complete."}
    payload.update(overrides)
    return payload


def finding_payload(engagement_id, **overrides):
    payload = {
        "engagement_id": engagement_id,
        "finding_type": FindingType.MISSING_SOURCE_DOC.value,
        "severity": FindingSeverity.MINOR.value,
        "affected_copies": 0,
    }
    payload.update(overrides)
    return payload


def finding_response_payload(**overrides):
    payload = {"response_note": "Documentation re-filed from the archive."}
    payload.update(overrides)
    return payload


def finding_rejection_payload(**overrides):
    payload = {"rejection_note": "Re-filed copy still does not support the claim."}
    payload.update(overrides)
    return payload


def accept_resolution_payload(**overrides):
    payload = {"resolution_note": "Remedy accepted."}
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# Advertiser contracts and make-goods
# --------------------------------------------------------------------------
def advertiser_contract_payload(publication_id, **overrides):
    payload = {
        "publication_id": publication_id,
        "advertiser_name": f"Ironworks Tooling {next_seq()}",
        "insertion_count": 12,
        "gross_rate_cents_per_insertion": 850000,
        "guaranteed_rate_base": 1000,
    }
    payload.update(overrides)
    return payload


def offer_payload(**overrides):
    payload = {"offer_note": "Credit offered against the shortfall."}
    payload.update(overrides)
    return payload


def accept_makegood_payload(**overrides):
    payload = {"acceptance_note": "Credit accepted."}
    payload.update(overrides)
    return payload


def waive_payload(**overrides):
    payload = {"waiver_reason": "Advertiser released the publisher."}
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# Digital audience snapshots
# --------------------------------------------------------------------------
def digital_snapshot_payload(**overrides):
    payload = {
        "window_start": "2026-04-01T00:00:00Z",
        "window_end": "2026-06-30T00:00:00Z",
        "website_unique_visitors": 48000,
        "newsletter_sends": 20000,
        "newsletter_unique_opens": 12500,
        "overlap_pct": 15.00,
        "source": SnapshotSource.THIRD_PARTY_CERTIFIED.value,
    }
    payload.update(overrides)
    return payload


def snapshot_decision_payload(decision=SnapshotDecision.VALIDATE.value, **overrides):
    payload = {"decision": decision}
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# Clock
# --------------------------------------------------------------------------
def clock_payload(to_iso8601=DEFAULT_CLOCK):
    return {"to_iso8601": to_iso8601}


AS_OF_PERIOD_END = StatementBasis.AS_OF_PERIOD_END.value
AUDIT_VERIFIED = StatementBasis.AUDIT_VERIFIED.value
