"""Entity assertions and domain invariant checkers.

Every assertion reads field names verbatim from PRD prose. Versioned
entities (Work, RightsHolder, AgencyBinding, RightsShare, PlaybackBatch,
RoyaltyPool, Distribution, MicroBalance, Dispute, PayoutBatch, Payment)
carry id+created_at+updated_at+version. Append-only entities
(ShareChangeAudit, PlaybackEvent, DistributionRuleVersion,
ExternalSyncEvent) carry ONLY id+created_at (PRD §2.4).
"""
from __future__ import annotations
from typing import Any, Dict, Iterable, List, Optional

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)


# ---------------------------------------------------------------------------
# Status / enum reference sets (PRD §3.x)
# ---------------------------------------------------------------------------
WORK_REGISTRATION_STATUSES = {
    "DRAFT", "SUBMITTED", "UNDER_REVIEW",
    "APPROVED", "REJECTED", "WITHDRAWN",
}
WORK_DISPUTE_POSTURES = {"CLEAR", "FROZEN"}
WORK_RIGHTS_TYPES = {"COMPOSITION", "LYRICS", "RECORDING", "PERFORMANCE"}
CO_CREATOR_ROLES = {"COMPOSER", "LYRICIST", "PRODUCER", "PERFORMER"}

HOLDER_KINDS = {"INDIVIDUAL", "ORGANIZATION"}
PAYOUT_CURRENCIES = {"USD", "EUR", "GBP", "JPY", "CNY"}

AGENCY_KINDS = {"PUBLISHER", "LABEL", "CMO"}
AGENCY_BINDING_STATUSES = {"ACTIVE", "TERMINATED"}

SHARE_STATUSES = {"ACTIVE", "DISPUTED", "TERMINATED"}
SHARE_CHANGE_KINDS = {
    "CREATED", "PERCENT_UPDATED", "STATUS_TRANSITION",
    "AGENCY_REBOUND", "TERMINATED",
}

PLAYBACK_CHANNELS = {"STREAMING", "RADIO", "TV", "PUBLIC_VENUE", "LIVE"}
PLAYBACK_BATCH_VALIDITIES = {
    "PENDING", "VALID", "INVALID_SIGNATURE",
    "INVALID_RANGE", "DEDUPED_REJECTED",
}
PLAYBACK_EVENT_STATUSES = {
    "ACCEPTED", "DUPLICATE_DROPPED", "SUPPLEMENTED", "REJECTED",
}

REVENUE_SOURCES = {
    "STREAMING", "RADIO", "TV", "PUBLIC_VENUE", "LIVE",
    "SYNC", "MECHANICAL_LICENSE",
}
ROYALTY_POOL_STATUSES = {"OPEN", "CLOSED", "DISTRIBUTED"}

DISTRIBUTION_STATUSES = {"PENDING", "FROZEN", "RELEASED", "PAID", "FORFEITED"}
DISTRIBUTION_SUB_POOLS = {"MECHANICAL", "PERFORMANCE"}

DISTRIBUTION_MODES = {"PER_PLAY", "PER_DURATION", "HYBRID"}

DISPUTE_STATUSES = {
    "OPEN", "UNDER_INVESTIGATION", "MEDIATION", "ARBITRATION",
    "RESOLVED_UPHELD", "RESOLVED_DISMISSED", "WITHDRAWN",
}
DISPUTE_KINDS = {"SHARE_RATIO", "OWNERSHIP", "ORIGINALITY", "AGENCY_AUTHORITY"}
DISPUTE_OUTCOMES = {"UPHELD", "DISMISSED"}

PAYOUT_BATCH_STATUSES = {"PENDING", "RUNNING", "COMPLETED", "FAILED"}
PAYMENT_STATUSES = {"QUEUED", "SENT", "SUCCEEDED", "FAILED",
                    "RETRYING", "ABANDONED"}
ROUTING_CHANNELS = {"SWIFT", "SEPA", "ACH", "LOCAL_JP", "LOCAL_CN"}

EXTERNAL_TARGET_SYSTEMS = {"PAYMENT_PSP", "BANK", "CMO_GATEWAY"}
EXTERNAL_EVENT_KINDS = {
    "PAYMENT_INITIATED", "PAYMENT_SUCCEEDED", "PAYMENT_FAILED",
    "BANK_RECONCILIATION", "CMO_SHARE_PUSH", "CMO_REVENUE_PULL",
}
RELATED_ENTITY_KINDS = {"Payment", "PayoutBatch", "RightsShare", "RoyaltyPool"}


# ---------------------------------------------------------------------------
# Common-field helpers (PRD §2.4)
# ---------------------------------------------------------------------------
def _assert_common_versioned(data: Dict[str, Any]) -> None:
    assert is_valid_uuid(data.get("id", "")), f"id must be UUID: {data.get('id')}"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"created_at must be ISO 8601: {data.get('created_at')}"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        f"updated_at must be ISO 8601: {data.get('updated_at')}"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        f"version must be int >= 1: {data.get('version')}"


def _assert_common_append_only(data: Dict[str, Any]) -> None:
    assert is_valid_uuid(data.get("id", "")), f"id must be UUID: {data.get('id')}"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"created_at must be ISO 8601: {data.get('created_at')}"


# ===========================================================================
# Versioned entities (PRD §2.4)
# ===========================================================================

def assert_work(data: Dict[str, Any]) -> None:
    """Work shape (PRD §3.1)."""
    _assert_common_versioned(data)
    assert isinstance(data["title"], str) and 1 <= len(data["title"]) <= 200
    assert isinstance(data["duration_seconds"], int)
    assert 1 <= data["duration_seconds"] <= 7200
    assert data["rights_type"] in WORK_RIGHTS_TYPES
    assert data["registration_status"] in WORK_REGISTRATION_STATUSES
    assert data["dispute_posture"] in WORK_DISPUTE_POSTURES
    co = data.get("co_creators", [])
    assert isinstance(co, list)
    if data["registration_status"] in {"SUBMITTED", "UNDER_REVIEW",
                                       "APPROVED", "REJECTED"}:
        # Submission required these to exist.
        assert 1 <= len(co) <= 16
        for item in co:
            assert item.get("role") in CO_CREATOR_ROLES


def assert_rights_holder(data: Dict[str, Any]) -> None:
    """RightsHolder shape (PRD §3.5)."""
    _assert_common_versioned(data)
    assert isinstance(data["legal_name"], str)
    assert 1 <= len(data["legal_name"]) <= 200
    assert data["holder_kind"] in HOLDER_KINDS
    assert data["payout_currency"] in PAYOUT_CURRENCIES
    assert isinstance(data["tax_jurisdiction"], str)
    assert len(data["tax_jurisdiction"]) == 2
    assert data["tax_jurisdiction"].isupper()
    assert isinstance(data.get("is_minor"), bool)
    if data["holder_kind"] == "INDIVIDUAL":
        assert data.get("date_of_birth") is not None


def assert_agency_binding(data: Dict[str, Any]) -> None:
    """AgencyBinding shape (PRD §3.4)."""
    _assert_common_versioned(data)
    assert data["agency_kind"] in AGENCY_KINDS
    assert 1 <= len(data["agency_name"]) <= 200
    territory = data["territory"]
    assert territory == "WW" or (len(territory) == 2 and territory.isupper())
    cp = float(data["commission_percent"])
    assert 0.00 <= cp <= 50.00
    assert is_iso8601_timestamp(data["effective_from"])
    if data.get("effective_until") is not None:
        assert is_iso8601_timestamp(data["effective_until"])
    assert data["status"] in AGENCY_BINDING_STATUSES


def assert_rights_share(data: Dict[str, Any]) -> None:
    """RightsShare shape (PRD §3.3)."""
    _assert_common_versioned(data)
    assert is_valid_uuid(data["work_id"])
    assert is_valid_uuid(data["rights_holder_id"])
    sp = float(data["share_percent"])
    assert 0.01 <= sp <= 100.00
    assert data["share_status"] in SHARE_STATUSES


def assert_share_change_audit(data: Dict[str, Any]) -> None:
    """ShareChangeAudit shape (PRD §2.9, §2.4: append-only)."""
    _assert_common_append_only(data)
    # PRD §2.4: append-only entities have NO updated_at and NO version.
    assert "updated_at" not in data or data.get("updated_at") is None
    assert "version" not in data or data.get("version") is None
    assert is_valid_uuid(data["rights_share_id"])
    assert data["change_kind"] in SHARE_CHANGE_KINDS
    if data["change_kind"] == "CREATED":
        # PRD §2.9: 'before_snapshot is null for the CREATED kind.'
        assert data.get("before_snapshot") is None
    else:
        assert isinstance(data["before_snapshot"], dict)
    assert isinstance(data["after_snapshot"], dict)


def assert_playback_batch(data: Dict[str, Any]) -> None:
    """PlaybackBatch shape (PRD §3.6)."""
    _assert_common_versioned(data)
    assert data["channel"] in PLAYBACK_CHANNELS
    assert data["validity_status"] in PLAYBACK_BATCH_VALIDITIES
    assert isinstance(data["total_events_submitted"], int)
    assert isinstance(data["total_events_accepted"], int)
    assert is_iso8601_timestamp(data["reporting_period_start"])
    assert is_iso8601_timestamp(data["reporting_period_end"])


def assert_playback_event(data: Dict[str, Any]) -> None:
    """PlaybackEvent shape (PRD §3.6: append-only)."""
    _assert_common_append_only(data)
    assert "updated_at" not in data or data.get("updated_at") is None
    assert "version" not in data or data.get("version") is None
    assert data["status"] in PLAYBACK_EVENT_STATUSES
    assert is_iso8601_timestamp(data["played_at"])
    assert isinstance(data["play_duration_seconds"], int)
    assert data["play_duration_seconds"] > 0


def assert_royalty_pool(data: Dict[str, Any]) -> None:
    """RoyaltyPool shape (PRD §3.8)."""
    _assert_common_versioned(data)
    assert data["revenue_source"] in REVENUE_SOURCES
    region = data["region"]
    assert region == "WW" or (len(region) == 2 and region.isupper())
    assert isinstance(data["gross_revenue_cents"], int)
    assert data["gross_revenue_cents"] >= 0
    psp = float(data["platform_share_percent"])
    assert 0.00 <= psp <= 40.00
    msp = float(data["mechanical_split_percent"])
    assert 0.00 <= msp <= 100.00
    assert data["pool_currency"] in PAYOUT_CURRENCIES
    assert data["status"] in ROYALTY_POOL_STATUSES
    assert isinstance(data["net_distributable_cents"], int)
    assert data["net_distributable_cents"] >= 0


def assert_distribution_rule_version(data: Dict[str, Any]) -> None:
    """DistributionRuleVersion shape (PRD §3.7: append-only)."""
    _assert_common_append_only(data)
    assert "updated_at" not in data or data.get("updated_at") is None
    assert "version" not in data or data.get("version") is None
    assert isinstance(data["version_tag"], str)
    assert 1 <= len(data["version_tag"]) <= 32
    assert data["channel"] in REVENUE_SOURCES
    assert data["distribution_mode"] in DISTRIBUTION_MODES
    assert isinstance(data["minimum_payout_cents"], int)
    assert data["minimum_payout_cents"] >= 0
    assert isinstance(data["micro_accumulation_cap_cents"], int)
    assert data["micro_accumulation_cap_cents"] >= data["minimum_payout_cents"]
    assert isinstance(data["playback_type_weights"], dict)


def assert_distribution(data: Dict[str, Any]) -> None:
    """Distribution shape (PRD §3.9)."""
    _assert_common_versioned(data)
    assert is_valid_uuid(data["royalty_pool_id"])
    assert is_valid_uuid(data["work_id"])
    assert is_valid_uuid(data["rights_holder_id"])
    assert is_valid_uuid(data["rights_share_id"])
    assert data["sub_pool"] in DISTRIBUTION_SUB_POOLS
    assert isinstance(data["gross_amount_cents"], int)
    assert isinstance(data["commission_cents"], int)
    assert isinstance(data["net_after_commission_cents"], int)
    assert data["status"] in DISTRIBUTION_STATUSES
    # PRD §3.9: 'net_after_commission_cents is the gross_amount_cents
    # minus the commission_cents, as a plain integer subtraction.'
    assert (data["net_after_commission_cents"]
            == data["gross_amount_cents"] - data["commission_cents"])


def assert_micro_balance(data: Dict[str, Any]) -> None:
    """MicroBalance shape (PRD §3.12)."""
    _assert_common_versioned(data)
    assert is_valid_uuid(data["rights_holder_id"])
    assert data["currency"] in PAYOUT_CURRENCIES
    assert isinstance(data["balance_cents"], int)
    assert data["balance_cents"] >= 0


def assert_dispute(data: Dict[str, Any]) -> None:
    """Dispute shape (PRD §3.11)."""
    _assert_common_versioned(data)
    assert is_valid_uuid(data["work_id"])
    assert is_valid_uuid(data["claimant_rights_holder_id"])
    assert data["dispute_kind"] in DISPUTE_KINDS
    assert data["status"] in DISPUTE_STATUSES
    assert isinstance(data["claim_summary"], str)
    assert 1 <= len(data["claim_summary"]) <= 2000
    assert isinstance(data["evidence_items"], list)


def assert_payout_batch(data: Dict[str, Any]) -> None:
    """PayoutBatch shape (PRD §3.12)."""
    _assert_common_versioned(data)
    assert isinstance(data["cycle_tag"], str)
    assert 1 <= len(data["cycle_tag"]) <= 32
    assert data["status"] in PAYOUT_BATCH_STATUSES
    assert is_iso8601_timestamp(data["scheduled_run_at"])
    assert isinstance(data["total_payments"], int)
    assert isinstance(data["total_paid_cents_by_currency"], dict)


def assert_payment(data: Dict[str, Any]) -> None:
    """Payment shape (PRD §3.12, §3.13)."""
    _assert_common_versioned(data)
    assert is_valid_uuid(data["payout_batch_id"])
    assert is_valid_uuid(data["rights_holder_id"])
    assert data["currency"] in PAYOUT_CURRENCIES
    assert isinstance(data["gross_cents"], int)
    assert isinstance(data["tax_withheld_cents"], int)
    assert isinstance(data["net_payable_cents"], int)
    assert data["routing_channel"] in ROUTING_CHANNELS
    assert data["status"] in PAYMENT_STATUSES
    assert isinstance(data["retry_count"], int)
    assert 0 <= data["retry_count"] <= 3
    # PRD §3.12: 'The net_payable_cents is gross_cents minus
    # tax_withheld_cents, as an integer subtraction.'
    assert (data["net_payable_cents"]
            == data["gross_cents"] - data["tax_withheld_cents"])


def assert_external_sync_event(data: Dict[str, Any]) -> None:
    """ExternalSyncEvent shape (PRD §3.13, §3.14: append-only)."""
    _assert_common_append_only(data)
    assert "updated_at" not in data or data.get("updated_at") is None
    assert "version" not in data or data.get("version") is None
    assert data["target_system"] in EXTERNAL_TARGET_SYSTEMS
    assert data["event_kind"] in EXTERNAL_EVENT_KINDS
    assert data["related_entity_kind"] in RELATED_ENTITY_KINDS
    assert is_valid_uuid(data["related_entity_id"])


# ===========================================================================
# Search/find helpers for cross-row assertions
# ===========================================================================
def find_audit_by_kind(audits: Iterable[Dict[str, Any]],
                       change_kind: str) -> List[Dict[str, Any]]:
    return [a for a in audits if a.get("change_kind") == change_kind]


def find_distribution_for(distributions: Iterable[Dict[str, Any]],
                          rights_holder_id: str,
                          work_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
    for d in distributions:
        if d.get("rights_holder_id") != rights_holder_id:
            continue
        if work_id is not None and d.get("work_id") != work_id:
            continue
        return d
    return None


def find_distributions_for_work(distributions: Iterable[Dict[str, Any]],
                                work_id: str) -> List[Dict[str, Any]]:
    return [d for d in distributions if d.get("work_id") == work_id]


def find_payment_for(payments: Iterable[Dict[str, Any]],
                     rights_holder_id: str,
                     currency: str = "USD") -> Optional[Dict[str, Any]]:
    for p in payments:
        if (p.get("rights_holder_id") == rights_holder_id
                and p.get("currency") == currency):
            return p
    return None


def find_micro_balance(rows: Iterable[Dict[str, Any]],
                       currency: str = "USD") -> Optional[Dict[str, Any]]:
    for r in rows:
        if r.get("currency") == currency:
            return r
    return None


__all__ = [
    "WORK_REGISTRATION_STATUSES", "WORK_DISPUTE_POSTURES", "WORK_RIGHTS_TYPES",
    "CO_CREATOR_ROLES", "HOLDER_KINDS", "PAYOUT_CURRENCIES",
    "AGENCY_KINDS", "AGENCY_BINDING_STATUSES",
    "SHARE_STATUSES", "SHARE_CHANGE_KINDS",
    "PLAYBACK_CHANNELS", "PLAYBACK_BATCH_VALIDITIES", "PLAYBACK_EVENT_STATUSES",
    "REVENUE_SOURCES", "ROYALTY_POOL_STATUSES",
    "DISTRIBUTION_STATUSES", "DISTRIBUTION_SUB_POOLS", "DISTRIBUTION_MODES",
    "DISPUTE_STATUSES", "DISPUTE_KINDS", "DISPUTE_OUTCOMES",
    "PAYOUT_BATCH_STATUSES", "PAYMENT_STATUSES", "ROUTING_CHANNELS",
    "EXTERNAL_TARGET_SYSTEMS", "EXTERNAL_EVENT_KINDS", "RELATED_ENTITY_KINDS",
    "assert_work", "assert_rights_holder", "assert_agency_binding",
    "assert_rights_share", "assert_share_change_audit",
    "assert_playback_batch", "assert_playback_event",
    "assert_royalty_pool", "assert_distribution_rule_version",
    "assert_distribution", "assert_micro_balance",
    "assert_dispute", "assert_payout_batch", "assert_payment",
    "assert_external_sync_event",
    "find_audit_by_kind", "find_distribution_for",
    "find_distributions_for_work", "find_payment_for", "find_micro_balance",
]
