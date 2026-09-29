"""Row -> JSON projections. Internal ``_``-prefixed fields never leak."""

from datetime import date, datetime

import derive
from store import iso

COMMON_TAIL = ("created_at", "updated_at", "version")
APPEND_ONLY_TAIL = ("created_at",)

FIELDS = {
    "InteropProfile": (
        "profile_code", "standard_version", "accepted_issuer_states",
        "required_assurance_level", "max_devices_per_holder",
        "max_active_credentials_per_holder", "proofing_validity_days",
        "revocation_freshness_seconds", "age_only_allowed_elements",
        "pending_republish_count", "is_active",
    ),
    "Holder": (
        "legal_name", "date_of_birth", "address_line1", "city", "state_code",
        "postal_code", "physical_credential_number", "physical_credential_status",
        "physical_credential_expires_on", "restriction_codes",
        "active_credential_count", "bound_device_count", "revoked_credential_count",
        "address_version",
    ),
    "IdentityProofingSession": (
        "holder_id", "requested_assurance_level", "state", "proofing_agent_user_id",
        "adjudicator_user_id", "submission_count", "evidence_count",
        "adjudication_score", "achieved_assurance_level", "verified_at",
        "assurance_expires_at", "return_reason",
    ),
    "ProofingEvidence": (
        "proofing_session_id", "evidence_type", "quality", "captured_at",
        "source_reference", "strength_points", "superseded",
    ),
    "Device": (
        "holder_id", "platform", "model_name", "hardware_attestation_token",
        "protection_method", "state", "attestation_result", "secure_element_grade",
        "active_binding_count", "lost_reported_at", "reprovision_count",
    ),
    "DigitalCredential": (
        "holder_id", "device_id", "proofing_session_id", "supersedes_credential_id",
        "lifecycle_state", "sync_state", "doc_version", "valid_from", "valid_until",
        "assurance_level", "restriction_codes", "address_version_synced",
        "pending_update_count", "failed_delivery_count", "suspend_reason",
        "revocation_sequence", "activated_at", "protection_method_at_activation",
        "reissuance_settlement_cents", "age_only_capable",
    ),
    "UpdateOrder": (
        "holder_id", "reason", "status", "payload_summary", "delivery_count",
        "delivered_count", "failed_count", "target_address_version", "opened_at",
        "closed_at",
    ),
    "UpdateDelivery": (
        "update_order_id", "credential_id", "status", "attempt_count",
        "failure_code", "delivered_at", "device_receipt_token",
        "resulting_doc_version",
    ),
    "RevocationEntry": (
        "credential_id", "sequence", "status", "reason", "effective_at", "published",
    ),
    "Verifier": (
        "organization_name", "category", "purpose_scope", "retention_ceiling_days",
        "trust_status", "exposure_index", "last_attestation_at",
        "attested_max_retention_days", "open_session_count",
        "billable_query_balance_cents", "credited_amount_cents",
        "probation_strike_count",
    ),
    "ReaderApp": (
        "verifier_id", "app_identifier", "certificate_serial", "cert_not_before",
        "cert_not_after", "requested_elements", "base_rate_cents", "trust_state",
        "listed_at", "query_count", "volume_discount_pct",
    ),
    "TrustListSnapshot": (
        "interop_profile_id", "snapshot_sequence", "effective_from",
        "effective_until", "listed_reader_app_count", "revocation_pointer_sequence",
        "revocation_pointer_stale", "pending_delta_count", "standard_version",
        "published_at",
    ),
    "PresentationSession": (
        "credential_id", "reader_app_id", "context", "purpose",
        "requested_elements", "handset_handling", "retention_days", "state",
        "minimized_elements", "withheld_elements", "disclosed_element_count",
        "excess_element_count", "billed_amount_cents", "billing_state",
        "consent_unlock_method", "abort_reason", "age_attestation_only", "opened_at",
    ),
    "PresentationLogEntry": (
        "presentation_session_id", "verifier_id", "credential_pseudonym", "outcome",
        "disclosed_element_count", "excess_element_count", "retention_days_declared",
        "billed_amount_cents", "billing_state", "pseudonym_reuse_index",
        "recorded_at",
    ),
}

APPEND_ONLY = ("ProofingEvidence", "RevocationEntry", "PresentationLogEntry")


def _derived(kind, row):
    if kind == "Holder":
        return {
            "active_credential_count": derive.active_credential_count(row["id"]),
            "bound_device_count": derive.bound_device_count(row["id"]),
            "revoked_credential_count": derive.revoked_credential_count(row["id"]),
        }
    if kind == "Device":
        return {"active_binding_count": derive.active_binding_count(row["id"])}
    if kind == "DigitalCredential":
        return {
            "pending_update_count": derive.pending_update_count(row["id"]),
            "failed_delivery_count": derive.failed_delivery_count(row["id"]),
            "revocation_sequence": derive.revocation_sequence(row["id"]),
        }
    if kind == "IdentityProofingSession":
        return {"evidence_count": derive.evidence_count(row["id"])}
    if kind == "UpdateOrder":
        delivery, delivered, failed = derive.order_counts(row["id"])
        return {
            "delivery_count": delivery,
            "delivered_count": delivered,
            "failed_count": failed,
        }
    if kind == "ReaderApp":
        return {
            "query_count": derive.query_count(row["id"]),
            "volume_discount_pct": derive.volume_discount_pct(row["id"]),
        }
    if kind == "Verifier":
        return {
            "open_session_count": derive.open_session_count(row["id"]),
            "billable_query_balance_cents":
                derive.billable_query_balance_cents(row["id"]),
        }
    return {}


def _value(value):
    if isinstance(value, datetime):
        return iso(value)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, list):
        return list(value)
    return value


def dump(row):
    kind = row["_kind"]
    overrides = _derived(kind, row)
    out = {"id": row["id"]}
    for name in FIELDS[kind]:
        if name in overrides:
            out[name] = overrides[name]
        else:
            out[name] = _value(row.get(name))
    tail = APPEND_ONLY_TAIL if kind in APPEND_ONLY else COMMON_TAIL
    for name in tail:
        out[name] = _value(row.get(name))
    return out


def dump_many(rows):
    return [dump(r) for r in rows]
