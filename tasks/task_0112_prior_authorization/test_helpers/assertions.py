"""Entity assertions and domain invariant checkers.

These check the response shape and domain invariants required by the
PRD contract. They are intentionally permissive on optional fields —
when PRD prose is silent on a specific projection, the assertion does
not pin it.
"""
from __future__ import annotations

from typing import Any, Dict

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)


# ---------------------------------------------------------------------------
# Common-fields helpers — PRD §2.4
# ---------------------------------------------------------------------------
def _assert_id_and_created_at(data: Dict[str, Any]) -> None:
    """PRD §2.4: "id (string): a unique, server-minted identifier
    formatted as a UUID without any type prefix."
    PRD §2.4: "created_at (string): an ISO 8601 UTC timestamp with three
    fractional digits indicating when the resource was first created."
    """
    assert "id" in data, f"missing id; got keys: {list(data)}"
    assert is_valid_uuid(data["id"]), (
        f"id must be a UUID with no type prefix, got {data['id']!r}"
    )
    assert "created_at" in data, "missing created_at"
    assert is_iso8601_timestamp(data["created_at"]), (
        f"created_at must be ISO 8601, got {data['created_at']!r}"
    )


def _assert_updated_at_and_version(data: Dict[str, Any]) -> None:
    """PRD §2.4: "updated_at (string): an ISO 8601 UTC timestamp updated
    on every mutation of the resource. version (integer): a system-
    managed counter that starts at 1 on creation and increments by one
    on every mutation."
    """
    assert "updated_at" in data, "missing updated_at"
    assert is_iso8601_timestamp(data["updated_at"]), (
        f"updated_at must be ISO 8601, got {data['updated_at']!r}"
    )
    assert "version" in data, "missing version"
    assert isinstance(data["version"], int) and data["version"] >= 1, (
        f"version must be a positive integer, "
        f"got {data.get('version')!r}"
    )


def _assert_no_updated_at_or_version(data: Dict[str, Any]) -> None:
    """PRD §2.4: append-only resources "carry id and created_at but omit
    both updated_at and version." Applies to ClinicalEvidence and
    Decision."""
    assert "updated_at" not in data, (
        "append-only resource must not carry updated_at"
    )
    assert "version" not in data, (
        "append-only resource must not carry version"
    )


# ---------------------------------------------------------------------------
# Patient — PRD §3.1
# ---------------------------------------------------------------------------
def assert_patient(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert isinstance(data.get("member_id"), str) and data["member_id"]
    assert isinstance(data.get("full_name"), str) and data["full_name"]
    assert isinstance(data.get("date_of_birth"), str)
    # PRD §3.1: plan_type "must be one of COMMERCIAL, MEDICARE, or
    # MEDICAID".
    assert data.get("plan_type") in {"COMMERCIAL", "MEDICARE", "MEDICAID"}
    # PRD §3.1: "Every patient starts in ACTIVE status; the only other
    # allowed status value is INACTIVE."
    assert data.get("status") in {"ACTIVE", "INACTIVE"}


# ---------------------------------------------------------------------------
# Provider — PRD §3.1
# ---------------------------------------------------------------------------
def assert_provider(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    npi = data.get("npi")
    # PRD §3.1: "exactly 10 digits and unique across the system".
    assert isinstance(npi, str) and len(npi) == 10 and npi.isdigit(), (
        f"npi must be a 10-digit string, got {npi!r}"
    )
    assert isinstance(data.get("full_name"), str) and data["full_name"]
    assert isinstance(data.get("specialty"), str)
    # PRD §3.1: in_network "defaults to true". Type-check only.
    assert isinstance(data.get("in_network", True), bool)
    # PRD §3.1: "Every provider starts in ACTIVE status; the only other
    # allowed status value is SUSPENDED."
    assert data.get("status") in {"ACTIVE", "SUSPENDED"}


# ---------------------------------------------------------------------------
# ServiceCatalogItem — PRD §3.1
# ---------------------------------------------------------------------------
def assert_service_catalog_item(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert isinstance(data.get("code"), str) and data["code"]
    # PRD §3.1: "a kind discriminator that is one of SERVICE or DRUG".
    assert data.get("kind") in {"SERVICE", "DRUG"}
    assert isinstance(data.get("name"), str)
    # PRD §3.1: "a boolean requires_pa that defaults to true".
    assert isinstance(data.get("requires_pa", True), bool)
    assert isinstance(data.get("standard_sla_hours"), int)
    # PRD §3.1: "standard_sla_hours … required to be at least 24".
    assert data["standard_sla_hours"] >= 24
    assert isinstance(data.get("expedited_sla_hours"), int)
    # PRD §3.1: "expedited_sla_hours … required to be at least 4 and
    # strictly less than standard_sla_hours".
    assert data["expedited_sla_hours"] >= 4
    assert data["expedited_sla_hours"] < data["standard_sla_hours"]
    assert isinstance(data.get("approval_validity_days"), int)
    # PRD §3.1: "approval_validity_days (defaulting to 90 and required
    # to be at least 1)".
    assert data["approval_validity_days"] >= 1
    cats = data.get("required_evidence_categories", [])
    assert isinstance(cats, list)
    for cat in cats:
        # PRD §3.1: "an array drawn from LAB, IMAGING, NOTES,
        # MED_HISTORY, and OTHER".
        assert cat in {"LAB", "IMAGING", "NOTES", "MED_HISTORY", "OTHER"}
    # PRD §3.1: "Every catalog item starts in ACTIVE status; an admin
    # may retire a catalog item by moving its status to RETIRED."
    assert data.get("status") in {"ACTIVE", "RETIRED"}


# ---------------------------------------------------------------------------
# AuthorizationRequest — PRD §3.2 / §3.9 / §3.10
# ---------------------------------------------------------------------------
AUTH_REQUEST_STATUSES = {
    "DRAFT", "SUBMITTED", "UNDER_REVIEW", "PENDING_INFO",
    "PEER_REVIEW", "APPROVED", "DENIED", "EXPIRED", "WITHDRAWN",
}


def assert_authorization_request(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert is_valid_uuid(data.get("patient_id", ""))
    assert is_valid_uuid(data.get("provider_id", ""))
    assert is_valid_uuid(data.get("service_catalog_item_id", ""))
    # PRD §3.2 (submission side-effect): "service_code is denormalized
    # to the catalog item's current code" only on the DRAFT -> SUBMITTED
    # transition; in DRAFT it is not yet pinned.
    if data.get("status") not in {"DRAFT"}:
        assert isinstance(data.get("service_code"), str)
    # PRD §2.10: "every AuthorizationRequest captures
    # service_catalog_item_version at the moment it transitions from
    # DRAFT to SUBMITTED".
    if data.get("status") not in {"DRAFT"}:
        assert isinstance(data.get("service_catalog_item_version"), int)
    # PRD §3.2: urgency "is one of STANDARD or EXPEDITED (defaults to
    # STANDARD)".
    assert data.get("urgency") in {"STANDARD", "EXPEDITED"}
    assert isinstance(data.get("clinical_justification"), str)
    # PRD §3.2: "requested_units — the number of visits, doses, or
    # sessions requested, which must be at least 1".
    ru = data.get("requested_units")
    assert isinstance(ru, int) and ru >= 1
    assert data.get("status") in AUTH_REQUEST_STATUSES, (
        f"unexpected status {data.get('status')!r}"
    )
    # prior_request_id is null or UUID.
    pid = data.get("prior_request_id")
    if pid is not None:
        assert is_valid_uuid(pid)


# ---------------------------------------------------------------------------
# ClinicalEvidence — PRD §3.3 (append-only)
# ---------------------------------------------------------------------------
def assert_clinical_evidence(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    _assert_no_updated_at_or_version(data)
    assert is_valid_uuid(data.get("authorization_request_id", ""))
    # PRD §3.3: category is one of LAB, IMAGING, NOTES, MED_HISTORY,
    # OTHER.
    assert data.get("category") in {
        "LAB", "IMAGING", "NOTES", "MED_HISTORY", "OTHER",
    }
    assert isinstance(data.get("title"), str)
    assert isinstance(data.get("uri"), str)
    assert isinstance(data.get("byte_size"), int)
    # PRD §3.3: byte_size > 0 and <= 50_000_000.
    assert 1 <= data["byte_size"] <= 50_000_000
    # PRD §3.3: "Every evidence row is created in ATTACHED status by
    # default. A provider can withdraw a previously attached document;
    # this transitions its status from ATTACHED to WITHDRAWN."
    assert data.get("status") in {"ATTACHED", "WITHDRAWN"}
    sf = data.get("sourced_from_request_id")
    if sf is not None:
        assert is_valid_uuid(sf)


# ---------------------------------------------------------------------------
# PeerToPeerReview — PRD §3.5
# ---------------------------------------------------------------------------
def assert_peer_to_peer_review(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert is_valid_uuid(data.get("authorization_request_id", ""))
    assert is_iso8601_timestamp(data.get("scheduled_at", ""))
    dm = data.get("duration_minutes")
    # PRD §3.5: "between 15 and 60 inclusive".
    assert isinstance(dm, int) and 15 <= dm <= 60
    assert isinstance(data.get("payer_reviewer_id"), str)
    # PRD §3.5: outcome starts PENDING and may move to UPHELD,
    # OVERTURNED, or NO_SHOW.
    assert data.get("outcome") in {
        "PENDING", "UPHELD", "OVERTURNED", "NO_SHOW",
    }
    # PRD §3.5: status starts SCHEDULED; terminal states COMPLETED and
    # CANCELLED.
    assert data.get("status") in {"SCHEDULED", "COMPLETED", "CANCELLED"}


# ---------------------------------------------------------------------------
# Decision — PRD §3.9 (append-only)
# ---------------------------------------------------------------------------
def assert_decision(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    _assert_no_updated_at_or_version(data)
    assert is_valid_uuid(data.get("authorization_request_id", ""))
    assert data.get("outcome") in {"APPROVED", "DENIED"}
    assert isinstance(data.get("rationale"), str)
    au = data.get("approved_units")
    # PRD §3.9: "When the outcome is APPROVED, approved_units must be
    # at least 1 …. When the outcome is DENIED, approved_units must be 0".
    assert isinstance(au, int)
    if data["outcome"] == "APPROVED":
        assert au >= 1
    else:
        assert au == 0
    # PRD §3.9: "denial_reason_code drawn from NOT_MEDICALLY_NECESSARY,
    # EXPERIMENTAL, OUT_OF_NETWORK, EVIDENCE_INSUFFICIENT, and
    # NON_COVERED_BENEFIT. … The denial_reason_code is null on approved
    # decisions and is non-null on denials."
    drc = data.get("denial_reason_code")
    if data["outcome"] == "APPROVED":
        assert drc is None
    else:
        assert drc in {
            "NOT_MEDICALLY_NECESSARY", "EXPERIMENTAL", "OUT_OF_NETWORK",
            "EVIDENCE_INSUFFICIENT", "NON_COVERED_BENEFIT",
        }
    # PRD §3.9: decided_by_role takes "INITIAL_REVIEWER,
    # MEDICAL_DIRECTOR, or EXTERNAL_REVIEWER".
    assert data.get("decided_by_role") in {
        "INITIAL_REVIEWER", "MEDICAL_DIRECTOR", "EXTERNAL_REVIEWER",
    }


# ---------------------------------------------------------------------------
# Appeal — PRD §3.11
# ---------------------------------------------------------------------------
def assert_appeal(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert is_valid_uuid(data.get("authorization_request_id", ""))
    # PRD §3.11: "The values 1, 2, and 3 are the only legal tiers."
    assert data.get("tier") in {1, 2, 3}
    assert isinstance(data.get("reason"), str)
    assert is_iso8601_timestamp(data.get("filed_at", ""))
    assert is_iso8601_timestamp(data.get("decision_deadline_at", ""))
    # PRD §3.11: outcome can be PENDING, UPHELD, OVERTURNED, or
    # WITHDRAWN.
    assert data.get("outcome") in {
        "PENDING", "UPHELD", "OVERTURNED", "WITHDRAWN",
    }


# ---------------------------------------------------------------------------
# Version-bump invariant — PRD §2.4 / §2.5
# ---------------------------------------------------------------------------
def assert_version_incremented_by_one(after: Dict[str, Any],
                                      before_version: int) -> None:
    """PRD §2.4: "version (integer): a system-managed counter that
    starts at 1 on creation and increments by one on every mutation."
    """
    assert after["version"] == before_version + 1, (
        f"expected version {before_version + 1}, "
        f"got {after['version']}"
    )


# ---------------------------------------------------------------------------
# Score precision — PRD §2.9
# ---------------------------------------------------------------------------
def assert_score_precision(score: float) -> None:
    """PRD §2.9: "All numeric scores produced by the system — most
    notably evidence_completeness_score and evidence_reuse_discount —
    are stored and returned to exactly two decimal places, rounded
    half-up. Scores are clamped into the closed interval from 0.00 to
    1.00 after rounding."
    """
    assert 0.0 <= score <= 1.0, f"score must be in [0,1], got {score}"
    # Two decimal places — value rounds equal to itself at 2dp.
    rounded = round(score + 1e-9, 2)
    assert abs(score - rounded) < 1e-6, (
        f"score {score} must be at two decimal places"
    )


__all__ = [
    "assert_patient",
    "assert_provider",
    "assert_service_catalog_item",
    "assert_authorization_request",
    "assert_clinical_evidence",
    "assert_peer_to_peer_review",
    "assert_decision",
    "assert_appeal",
    "assert_version_incremented_by_one",
    "assert_score_precision",
    "AUTH_REQUEST_STATUSES",
]
