"""Entity assertions and domain invariant checkers (PRD §2.4, §3).

Full-tracking resources carry id/created_at/updated_at/version; the four
evidence-style record types (EntryMaterial, ConflictDeclaration, Score,
AuditLog) carry only id and created_at (PRD §2.4).
"""
from decimal import Decimal, ROUND_HALF_UP

import pytest
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_tracked(data: dict):
    """Fields every full-tracking resource carries (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a bare UUID: {data.get('id')}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601: {data.get('created_at')}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be ISO 8601: {data.get('updated_at')}"
    )
    assert isinstance(data.get("version"), int), "version must be an integer"


def _assert_evidence_record(data: dict):
    """Evidence records carry only id + created_at of the common set."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a bare UUID: {data.get('id')}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601: {data.get('created_at')}"
    )
    assert "version" not in data, "evidence records must not carry version (PRD §2.4)"
    assert "updated_at" not in data, "evidence records must not carry updated_at (PRD §2.4)"


def assert_season(data: dict):
    _assert_common_tracked(data)
    assert isinstance(data["code"], str) and data["code"]
    assert data["status"] in [
        "DRAFT", "OPEN", "SUBMISSION_CLOSED", "JUDGING", "FINALISTS_LOCKED",
        "EMBARGOED", "CEREMONY_LIVE", "PUBLISHED", "ARCHIVED", "CANCELLED",
    ]
    assert isinstance(data["active_entries_count"], int)
    assert data["integrity_flag"] in ["CLEAN", "UNDER_REVIEW", "COMPROMISED"]


def assert_category(data: dict):
    _assert_common_tracked(data)
    assert data["status"] in ["DRAFT", "PUBLISHED", "SUSPENDED", "RETIRED"]
    weights = [c["weight_bp"] for c in data.get("scoring_rubric", [])]
    if weights:
        assert sum(weights) == 10000, "rubric weights must sum to exactly 10000 bp"


def assert_entrant(data: dict):
    _assert_common_tracked(data)
    assert data["standing"] in ["GOOD", "DELINQUENT", "BARRED"]
    assert isinstance(data["lifetime_disqualifications"], int)


def assert_entry(data: dict):
    _assert_common_tracked(data)
    assert data["status"] in [
        "DRAFT", "SUBMITTED", "UNDER_REVIEW", "ELIGIBLE", "INELIGIBLE",
        "IN_JUDGING", "FINALIST", "NON_FINALIST", "WINNER", "NON_WINNER",
        "WITHDRAWN", "DISQUALIFIED",
    ]
    assert data["payment_status"] in ["UNPAID", "INVOICED", "PAID", "REFUNDED", "WAIVED"]
    assert isinstance(data["revision_count"], int)


def assert_material(data: dict):
    _assert_evidence_record(data)
    assert data["material_type"] in ["VIDEO", "AUDIO", "PDF", "IMAGE", "URL"]
    assert data["status"] in ["PENDING", "ACCEPTED", "REJECTED"]


def assert_invoice(data: dict):
    _assert_common_tracked(data)
    assert data["status"] in ["ISSUED", "PAID", "VOIDED", "REFUNDED"]
    assert data["tier"] in ["EARLY", "STANDARD", "LATE"]
    assert isinstance(data["amount_cents"], int)


def assert_judge(data: dict):
    _assert_common_tracked(data)
    assert data["status"] in [
        "INVITED", "ACCEPTED", "DECLINED", "ACTIVE", "SUSPENDED", "RETIRED",
    ]
    assert 0 <= data["reliability_score_bp"] <= 10000


def assert_conflict_declaration(data: dict):
    _assert_evidence_record(data)
    assert data["conflict_type"] in [
        "FINANCIAL", "FAMILIAL", "PROFESSIONAL", "PERSONAL", "OTHER",
    ]
    assert data["severity"] in ["HARD", "SOFT"]
    assert data["status"] in ["DECLARED", "ACKNOWLEDGED", "RESCINDED"]


def assert_assignment(data: dict):
    _assert_common_tracked(data)
    assert data["role"] in ["CHAIR", "MEMBER"]
    assert data["status"] in ["PROPOSED", "ACTIVE", "RECUSED", "REMOVED", "COMPLETED"]


def assert_round(data: dict):
    _assert_common_tracked(data)
    assert data["status"] in [
        "CONFIGURING", "PANEL_LOCKED", "OPEN", "CLOSED", "NORMALIZED",
        "PUBLISHED", "VOIDED",
    ]
    assert data["name"] in ["SCREENING", "SEMIFINAL", "FINAL"]
    assert data["scoring_mode"] in ["RAW_RANK", "Z_SCORE"]


def assert_score(data: dict):
    _assert_evidence_record(data)
    assert data["status"] in ["DRAFT", "SUBMITTED", "LOCKED", "VOIDED"]


def assert_finalist_record(data: dict):
    _assert_common_tracked(data)
    assert data["notification_status"] in [
        "PENDING", "NOTIFIED", "ACKNOWLEDGED", "DECLINED", "REVOKED",
    ]
    assert isinstance(data["embargo_visible"], bool)


def assert_ceremony(data: dict):
    _assert_common_tracked(data)
    assert data["status"] in ["PLANNING", "REHEARSAL", "LIVE", "CONCLUDED", "ABORTED"]


def assert_announcement(data: dict):
    _assert_common_tracked(data)
    assert data["status"] in ["STAGED", "ANNOUNCED", "RETRACTED", "RESTAGED"]


def assert_fulfillment_order(data: dict):
    _assert_common_tracked(data)
    assert data["item_type"] in ["TROPHY", "CERTIFICATE"]
    assert data["status"] in [
        "DRAFT", "QUEUED", "IN_PRODUCTION", "SHIPPED", "DELIVERED", "CANCELLED",
    ]


def assert_appeal(data: dict):
    _assert_common_tracked(data)
    assert data["grounds"] in [
        "SCORING_ERROR", "CONFLICT_UNDECLARED", "ELIGIBILITY_MISREAD",
        "PROCEDURAL_VIOLATION",
    ]
    assert data["status"] in ["FILED", "UNDER_REVIEW", "UPHELD", "DENIED", "WITHDRAWN"]


def assert_audit_log(data: dict):
    _assert_evidence_record(data)
    assert isinstance(data["hash_chain_prev"], str) and len(data["hash_chain_prev"]) == 64
    assert isinstance(data["hash_chain_self"], str) and len(data["hash_chain_self"]) == 64


# --- domain invariants ---


def quantize_4dp(value) -> Decimal:
    """Round a computed score field to 4 decimal places, round-half-up
    (PRD §2.8)."""
    return Decimal(str(value)).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def assert_score_4dp(actual, expected, context: str = ""):
    """Assert a computed score field equals the expected value at 4dp
    precision (PRD §2.8: four decimal places, round-half-up)."""
    assert quantize_4dp(actual) == quantize_4dp(expected), (
        f"Expected {expected} at 4dp, got {actual} {context}"
    )


def assert_refund_invariant(invoice: dict):
    """PRD §3.3: refund_cents + retained_cents == amount_cents always holds."""
    refund = invoice.get("refund_cents")
    retained = invoice.get("retained_cents")
    assert refund is not None and retained is not None, (
        "a REFUNDED invoice must carry refund_cents and retained_cents"
    )
    assert refund + retained == invoice["amount_cents"], (
        f"refund {refund} + retained {retained} != amount {invoice['amount_cents']}"
    )


def assert_approx_4dp(actual, expected, context: str = ""):
    """Loose comparison for values derived by the test itself (e.g. means of
    server-returned 4dp values)."""
    assert actual == pytest.approx(expected, abs=0.0002), (
        f"Expected ~{expected}, got {actual} {context}"
    )
