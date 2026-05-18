"""Entity assertions and domain invariant checkers.

Each `assert_<entity>(data)` validates that a response payload carries
the fields the PRD declares for that entity, with the correct types
and PRD-stated enum domains. Common-fields entities (PRD §2.5) carry
id + created_at + updated_at + version; append-only audit records
(FurnisherInquiry, ResultNotice, HardInquiry per PRD §2.5) carry ONLY
id + created_at — these assertions intentionally do not demand
updated_at or version on them.
"""
from __future__ import annotations

from typing import Any, Dict

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)

from .constants import (
    DISPUTE_RISK_MAX,
    DISPUTE_RISK_MIN,
    FICO_MAX,
    FICO_MIN,
    FREE_REPORTS_MAX,
)


# ===========================================================================
# Common-field helpers — PRD §2.5
# ===========================================================================
def _assert_common_fields(data: Dict[str, Any], *, entity: str) -> None:
    """PRD §2.5 mandates id (UUID), created_at and updated_at
    (ISO 8601 UTC with three fractional digits), and version
    (monotonically increasing integer)."""
    assert is_valid_uuid(data.get("id", "")), (
        f"{entity}.id must be a UUID, got {data.get('id')!r}"
    )
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity}.created_at must be ISO 8601 UTC, got "
        f"{data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity}.updated_at must be ISO 8601 UTC, got "
        f"{data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int), (
        f"{entity}.version must be int, got {type(data.get('version'))}"
    )
    assert data["version"] >= 1, (
        f"{entity}.version must start at 1+, got {data['version']}"
    )


def _assert_appendonly_fields(data: Dict[str, Any], *, entity: str) -> None:
    """PRD §2.5: append-only records carry ONLY id and created_at;
    updated_at and version are absent."""
    assert is_valid_uuid(data.get("id", "")), (
        f"{entity}.id must be a UUID, got {data.get('id')!r}"
    )
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity}.created_at must be ISO 8601 UTC, got "
        f"{data.get('created_at')!r}"
    )


# ===========================================================================
# Consumer — PRD §3.1
# ===========================================================================
def assert_consumer(data: Dict[str, Any]) -> None:
    """Validate Consumer response per PRD §3.1 / §2.5."""
    _assert_common_fields(data, entity="Consumer")
    assert isinstance(data.get("full_name"), str) and data["full_name"], (
        "Consumer.full_name must be non-empty string"
    )
    # PRD §3.1: ssn_last4 must be exactly four digits.
    ssn = data.get("ssn_last4")
    assert isinstance(ssn, str) and len(ssn) == 4 and ssn.isdigit(), (
        f"Consumer.ssn_last4 must be exactly four digits, got {ssn!r}"
    )
    assert isinstance(data.get("email"), str) and "@" in data["email"], (
        "Consumer.email must be a non-empty string with '@'"
    )
    free = data.get("free_reports_remaining")
    assert isinstance(free, int) and 0 <= free <= FREE_REPORTS_MAX, (
        f"Consumer.free_reports_remaining must be int in [0, "
        f"{FREE_REPORTS_MAX}], got {free!r}"
    )
    # PRD §3.1: 'freeze_pin is server-minted later, on the consumer's
    # first credit freeze'. Null until first freeze, then string.
    pin = data.get("freeze_pin")
    assert pin is None or isinstance(pin, str), (
        f"Consumer.freeze_pin must be null or string, got {type(pin)}"
    )


# ===========================================================================
# Furnisher — PRD §3.1
# ===========================================================================
def assert_furnisher(data: Dict[str, Any]) -> None:
    _assert_common_fields(data, entity="Furnisher")
    assert isinstance(data.get("legal_name"), str) and data["legal_name"]
    assert isinstance(data.get("ecoa_code"), str) and data["ecoa_code"]
    assert data.get("status") in ("ACTIVE", "SUSPENDED"), (
        f"Furnisher.status must be ACTIVE or SUSPENDED, got "
        f"{data.get('status')!r}"
    )


# ===========================================================================
# CreditReport — PRD §3.1, §3.5, §3.7
# ===========================================================================
def assert_credit_report(data: Dict[str, Any]) -> None:
    _assert_common_fields(data, entity="CreditReport")
    assert is_valid_uuid(data.get("consumer_id", "")), (
        "CreditReport.consumer_id must be a UUID"
    )
    assert data.get("bureau") in ("EQUIFAX", "EXPERIAN", "TRANSUNION"), (
        f"CreditReport.bureau must be EQUIFAX|EXPERIAN|TRANSUNION, got "
        f"{data.get('bureau')!r}"
    )
    # PRD §2.10 / §3.5: fico_score is integer in [300, 850].
    fico = data.get("fico_score")
    assert isinstance(fico, int) and FICO_MIN <= fico <= FICO_MAX, (
        f"CreditReport.fico_score must be int in [{FICO_MIN}, {FICO_MAX}], "
        f"got {fico!r}"
    )
    # PRD §3.7: posture ∈ {OPEN, RESTRICTED, FROZEN}.
    assert data.get("posture") in ("OPEN", "RESTRICTED", "FROZEN"), (
        f"CreditReport.posture must be OPEN|RESTRICTED|FROZEN, got "
        f"{data.get('posture')!r}"
    )
    # PRD §3.1: last_pulled_day is null until first pull.
    lpd = data.get("last_pulled_day")
    assert lpd is None or (isinstance(lpd, int) and lpd >= 0), (
        f"CreditReport.last_pulled_day must be null or non-negative int, "
        f"got {lpd!r}"
    )
    assert data.get("status") in ("ACTIVE", "ARCHIVED"), (
        f"CreditReport.status must be ACTIVE|ARCHIVED, got "
        f"{data.get('status')!r}"
    )


# ===========================================================================
# TradelineItem — PRD §3.1
# ===========================================================================
def assert_tradeline_item(data: Dict[str, Any]) -> None:
    _assert_common_fields(data, entity="TradelineItem")
    assert is_valid_uuid(data.get("credit_report_id", ""))
    assert is_valid_uuid(data.get("furnisher_id", ""))
    assert isinstance(data.get("account_ref"), str) and data["account_ref"]
    odofd = data.get("original_dofd_day")
    assert isinstance(odofd, int) and odofd >= 0, (
        f"TradelineItem.original_dofd_day must be non-negative int, got {odofd!r}"
    )
    bal = data.get("balance_cents")
    assert isinstance(bal, int) and bal >= 0, (
        f"TradelineItem.balance_cents must be non-negative int, got {bal!r}"
    )
    assert data.get("payment_status") in (
        "CURRENT", "LATE_30", "LATE_60", "LATE_90",
        "CHARGE_OFF", "COLLECTION", "DELETED",
    ), f"TradelineItem.payment_status invalid: {data.get('payment_status')!r}"
    rdofd = data.get("reported_dofd_day")
    assert isinstance(rdofd, int) and rdofd >= 0, (
        f"TradelineItem.reported_dofd_day must be non-negative int, got {rdofd!r}"
    )
    assert data.get("verification_status") in (
        "UNVERIFIED", "VERIFIED", "UPDATED", "DELETED",
    ), (
        f"TradelineItem.verification_status invalid: "
        f"{data.get('verification_status')!r}"
    )


# ===========================================================================
# Dispute — PRD §3.2 – §3.4
# ===========================================================================
def assert_dispute(data: Dict[str, Any]) -> None:
    _assert_common_fields(data, entity="Dispute")
    assert is_valid_uuid(data.get("consumer_id", ""))
    assert is_valid_uuid(data.get("credit_report_id", ""))
    assert is_valid_uuid(data.get("tradeline_item_id", ""))
    assert data.get("channel") in ("ONLINE", "MAIL"), (
        f"Dispute.channel must be ONLINE|MAIL, got {data.get('channel')!r}"
    )
    docs = data.get("supporting_documents")
    assert isinstance(docs, list), (
        f"Dispute.supporting_documents must be list, got {type(docs)}"
    )
    assert data.get("requested_action") in (
        "CORRECT_BALANCE", "CORRECT_STATUS", "DELETE_ITEM", "CORRECT_DOFD",
    ), f"Dispute.requested_action invalid: {data.get('requested_action')!r}"
    assert "requested_payload" in data, (
        "Dispute.requested_payload field missing"
    )
    sub = data.get("submitted_day")
    assert isinstance(sub, int) and sub >= 0, (
        f"Dispute.submitted_day must be non-negative int, got {sub!r}"
    )
    dl = data.get("deadline_day")
    assert isinstance(dl, int) and dl >= 0, (
        f"Dispute.deadline_day must be non-negative int, got {dl!r}"
    )
    assert isinstance(data.get("additional_info_accepted"), bool), (
        "Dispute.additional_info_accepted must be bool"
    )
    # PRD §3.2: 'investigation_outcome initialized to PENDING'.
    assert data.get("investigation_outcome") in (
        "PENDING", "VERIFIED", "UPDATED", "DELETED", "DISMISSED_FRIVOLOUS",
    ), (
        f"Dispute.investigation_outcome invalid: "
        f"{data.get('investigation_outcome')!r}"
    )
    rn = data.get("result_notice_id")
    assert rn is None or is_valid_uuid(rn), (
        f"Dispute.result_notice_id must be null or UUID, got {rn!r}"
    )
    assert data.get("status") in (
        "RECEIVED", "UNDER_INVESTIGATION", "RESULTS_PENDING",
        "CLOSED_VERIFIED", "CLOSED_UPDATED", "CLOSED_DELETED",
        "CLOSED_DISMISSED", "ESCALATED",
    ), f"Dispute.status invalid: {data.get('status')!r}"


# ===========================================================================
# FurnisherInquiry — append-only per PRD §2.5
# ===========================================================================
def assert_furnisher_inquiry(data: Dict[str, Any]) -> None:
    """PRD §2.5 declares FurnisherInquiry append-only — only id and
    created_at on the standard envelope."""
    _assert_appendonly_fields(data, entity="FurnisherInquiry")
    assert is_valid_uuid(data.get("dispute_id", ""))
    assert is_valid_uuid(data.get("furnisher_id", ""))
    fd = data.get("forwarded_day")
    assert isinstance(fd, int) and fd >= 0
    rd = data.get("reverification_deadline_day")
    assert isinstance(rd, int) and rd >= 0
    assert data.get("response") in (
        "PENDING", "VERIFIED", "UPDATED", "DELETED", "NO_RESPONSE",
    ), f"FurnisherInquiry.response invalid: {data.get('response')!r}"
    rday = data.get("response_day")
    assert rday is None or (isinstance(rday, int) and rday >= 0)


# ===========================================================================
# ResultNotice — append-only per PRD §2.5
# ===========================================================================
def assert_result_notice(data: Dict[str, Any]) -> None:
    """PRD §2.5 declares ResultNotice append-only — only id and
    created_at on the standard envelope."""
    _assert_appendonly_fields(data, entity="ResultNotice")
    assert is_valid_uuid(data.get("dispute_id", ""))
    iss = data.get("issued_day")
    assert isinstance(iss, int) and iss >= 0
    assert data.get("delivery_channel") in ("ONLINE", "MAIL"), (
        f"ResultNotice.delivery_channel invalid: "
        f"{data.get('delivery_channel')!r}"
    )
    assert data.get("outcome") in (
        "VERIFIED", "UPDATED", "DELETED", "DISMISSED_FRIVOLOUS",
    ), f"ResultNotice.outcome invalid: {data.get('outcome')!r}"
    assert isinstance(data.get("free_report_granted"), bool), (
        "ResultNotice.free_report_granted must be bool"
    )
    assert isinstance(data.get("summary"), str), (
        "ResultNotice.summary must be string"
    )


# ===========================================================================
# RegulatoryComplaint — PRD §3.10
# ===========================================================================
def assert_regulatory_complaint(data: Dict[str, Any]) -> None:
    _assert_common_fields(data, entity="RegulatoryComplaint")
    assert is_valid_uuid(data.get("consumer_id", ""))
    assert is_valid_uuid(data.get("dispute_id", ""))
    pc = data.get("parent_complaint_id")
    assert pc is None or is_valid_uuid(pc), (
        f"RegulatoryComplaint.parent_complaint_id must be null or UUID, "
        f"got {pc!r}"
    )
    # PRD §3.10: agency defaults to CFPB; only value supported in v1.
    assert data.get("agency") == "CFPB", (
        f"RegulatoryComplaint.agency must be CFPB in v1, got "
        f"{data.get('agency')!r}"
    )
    narrative = data.get("narrative")
    assert isinstance(narrative, str) and 1 <= len(narrative) <= 4000, (
        f"RegulatoryComplaint.narrative must be 1..4000 chars, "
        f"got len={len(narrative) if isinstance(narrative, str) else '?'}"
    )
    fd = data.get("filed_day")
    assert isinstance(fd, int) and fd >= 0
    assert data.get("status") in (
        "FILED", "UNDER_REVIEW", "RESOLVED", "REJECTED",
    ), f"RegulatoryComplaint.status invalid: {data.get('status')!r}"


# ===========================================================================
# CreditFreeze — PRD §3.11
# ===========================================================================
def assert_credit_freeze(data: Dict[str, Any]) -> None:
    _assert_common_fields(data, entity="CreditFreeze")
    assert is_valid_uuid(data.get("consumer_id", ""))
    assert data.get("bureau") in ("EQUIFAX", "EXPERIAN", "TRANSUNION")
    pd = data.get("placed_day")
    assert isinstance(pd, int) and pd >= 0
    lifted = data.get("lifted_day")
    assert lifted is None or (isinstance(lifted, int) and lifted >= 0), (
        f"CreditFreeze.lifted_day must be null or non-negative int, "
        f"got {lifted!r}"
    )
    assert data.get("status") in ("ACTIVE", "LIFTED"), (
        f"CreditFreeze.status invalid: {data.get('status')!r}"
    )


# ===========================================================================
# CreditLock — PRD §3.11
# ===========================================================================
def assert_credit_lock(data: Dict[str, Any]) -> None:
    _assert_common_fields(data, entity="CreditLock")
    assert is_valid_uuid(data.get("consumer_id", ""))
    assert data.get("bureau") in ("EQUIFAX", "EXPERIAN", "TRANSUNION")
    lad = data.get("locked_at_day")
    assert isinstance(lad, int) and lad >= 0
    assert data.get("status") in ("LOCKED", "UNLOCKED"), (
        f"CreditLock.status invalid: {data.get('status')!r}"
    )


# ===========================================================================
# HardInquiry — append-only per PRD §2.5
# ===========================================================================
def assert_hard_inquiry(data: Dict[str, Any]) -> None:
    """PRD §2.5 declares HardInquiry append-only — only id and
    created_at on the standard envelope."""
    _assert_appendonly_fields(data, entity="HardInquiry")
    assert is_valid_uuid(data.get("credit_report_id", ""))
    assert is_valid_uuid(data.get("requesting_furnisher_id", ""))
    iday = data.get("inquiry_day")
    assert isinstance(iday, int) and iday >= 0
    assert data.get("outcome") in (
        "ACCEPTED", "BLOCKED_FREEZE", "BLOCKED_LOCK",
    ), f"HardInquiry.outcome invalid: {data.get('outcome')!r}"


# ===========================================================================
# Domain invariant checkers
# ===========================================================================
def assert_dispute_risk_score(score: int) -> None:
    """PRD §2.10 / §3.6: dispute risk score is integer in [0, 100]."""
    assert isinstance(score, int) and DISPUTE_RISK_MIN <= score <= DISPUTE_RISK_MAX, (
        f"dispute_risk_score must be int in [{DISPUTE_RISK_MIN}, "
        f"{DISPUTE_RISK_MAX}], got {score!r}"
    )


def assert_fico_score(score: int) -> None:
    """PRD §2.10 / §3.5: fico_score is integer in [300, 850]."""
    assert isinstance(score, int) and FICO_MIN <= score <= FICO_MAX, (
        f"fico_score must be int in [{FICO_MIN}, {FICO_MAX}], got {score!r}"
    )


__all__ = [
    "assert_consumer",
    "assert_furnisher",
    "assert_credit_report",
    "assert_tradeline_item",
    "assert_dispute",
    "assert_furnisher_inquiry",
    "assert_result_notice",
    "assert_regulatory_complaint",
    "assert_credit_freeze",
    "assert_credit_lock",
    "assert_hard_inquiry",
    "assert_dispute_risk_score",
    "assert_fico_score",
]
