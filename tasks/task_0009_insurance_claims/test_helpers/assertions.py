"""Entity assertions and domain invariant checkers (PRD-faithful)."""
import re
from prd_bench_local_runner.testing import (
    is_valid_uuid, is_iso8601_timestamp,
)


# Match CLM-YYYYMMDD-NNNN per PRD §2.4
CLAIM_NUMBER_RE = re.compile(r"^CLM-\d{8}-\d{4}$")


def _assert_common_fields(data: dict, entity_label: str) -> None:
    assert is_valid_uuid(data.get("id", "")), f"{entity_label}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"{entity_label}.created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), f"{entity_label}.updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        f"{entity_label}.version must be a positive integer"


def _assert_append_only_fields(data: dict, entity_label: str) -> None:
    assert is_valid_uuid(data.get("id", "")), f"{entity_label}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"{entity_label}.created_at must be ISO 8601"
    assert "updated_at" not in data, \
        f"{entity_label} is append-only and must not carry updated_at (PRD §2.4)"
    assert "version" not in data, \
        f"{entity_label} is append-only and must not carry version (PRD §2.4)"


# ─── Common-fields entities ───────────────────────────────────────
def assert_policy(data: dict) -> None:
    _assert_common_fields(data, "Policy")
    assert isinstance(data["policy_number"], str) and 8 <= len(data["policy_number"]) <= 24
    assert isinstance(data["insured_party_id"], str)
    assert data["coverage_type"] in ("AUTO", "PROPERTY", "LIABILITY")
    assert isinstance(data["coverage_limit_cents"], int) and data["coverage_limit_cents"] >= 0
    assert isinstance(data["deductible_cents"], int) and data["deductible_cents"] >= 0
    assert isinstance(data["coinsurance_ratio"], (int, float))
    assert 0.0 <= float(data["coinsurance_ratio"]) <= 1.0
    assert is_iso8601_timestamp(data["effective_from"])
    assert is_iso8601_timestamp(data["effective_to"])
    assert isinstance(data["reporting_window_days"], int) and data["reporting_window_days"] >= 1
    assert data["status"] in ("ACTIVE", "SUSPENDED", "EXPIRED", "CANCELLED")


def assert_adjuster(data: dict) -> None:
    _assert_common_fields(data, "Adjuster")
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["license_number"], str) and len(data["license_number"]) > 0
    assert data["specialty"] in ("AUTO", "PROPERTY", "LIABILITY")
    assert data["status"] in ("ACTIVE", "SUSPENDED")


def assert_repair_shop(data: dict) -> None:
    _assert_common_fields(data, "RepairShop")
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["tax_id"], str) and len(data["tax_id"]) > 0
    assert isinstance(data["trust_score"], (int, float))
    assert 0.0 <= float(data["trust_score"]) <= 1.0
    assert data["status"] in ("ACTIVE", "BLACKLISTED")


def assert_claim(data: dict) -> None:
    _assert_common_fields(data, "Claim")
    assert isinstance(data["claim_number"], str)
    assert CLAIM_NUMBER_RE.match(data["claim_number"]), (
        f"Claim.claim_number must match CLM-YYYYMMDD-NNNN, got {data['claim_number']!r}"
    )
    assert isinstance(data["policy_id"], str)
    assert isinstance(data["claimant_id"], str)
    assert data["report_channel"] in ("WEB", "MOBILE", "PHONE", "AGENT")
    assert isinstance(data["idempotency_key"], str)
    assert is_iso8601_timestamp(data["loss_date"])
    assert is_iso8601_timestamp(data["reported_at"])
    assert isinstance(data["incident_description"], str)
    assert isinstance(data["claimed_amount_cents"], int) and data["claimed_amount_cents"] > 0
    assert isinstance(data["assessed_loss_cents"], int) and data["assessed_loss_cents"] >= 0
    assert isinstance(data["salvage_value_cents"], int) and data["salvage_value_cents"] >= 0
    assert isinstance(data["subrogation_recovery_cents"], int) and data["subrogation_recovery_cents"] >= 0
    assert data["status"] in (
        "INTAKE", "UNDER_INVESTIGATION", "UNDER_REVIEW",
        "APPROVED", "DENIED", "PAID", "APPEALED", "CLOSED",
    )
    assert isinstance(data["fraud_score"], (int, float))
    assert 0.0 <= float(data["fraud_score"]) <= 1.0


def assert_investigation(data: dict) -> None:
    _assert_common_fields(data, "Investigation")
    assert isinstance(data["claim_id"], str)
    assert isinstance(data["adjuster_id"], str)
    assert isinstance(data["photo_urls"], list)
    for url in data["photo_urls"]:
        assert isinstance(url, str)
    assert isinstance(data["assessed_loss_cents"], int) and data["assessed_loss_cents"] >= 0
    assert isinstance(data["document_authenticity_passed"], bool)
    assert data["status"] in ("OPEN", "COMPLETED", "REJECTED")


def assert_appeal(data: dict) -> None:
    _assert_common_fields(data, "Appeal")
    assert isinstance(data["claim_id"], str)
    assert isinstance(data["requestor_id"], str)
    assert isinstance(data["grounds"], str)
    assert data["status"] in (
        "SUBMITTED", "UNDER_RECONSIDERATION",
        "UPHELD_DENIAL", "OVERTURNED", "WITHDRAWN",
    )


def assert_payout(data: dict) -> None:
    _assert_common_fields(data, "Payout")
    assert isinstance(data["claim_id"], str)
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] >= 0
    assert data["status"] in ("PENDING", "SETTLED", "REVERSED")


# ─── Append-only entities (no version, no updated_at) ─────────────
def assert_estimate_line_item(data: dict) -> None:
    _assert_append_only_fields(data, "EstimateLineItem")
    assert isinstance(data["investigation_id"], str)
    assert isinstance(data["repair_shop_id"], str)
    assert isinstance(data["description"], str)
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0


def assert_review_decision(data: dict) -> None:
    _assert_append_only_fields(data, "ReviewDecision")
    assert isinstance(data["claim_id"], str)
    assert isinstance(data["reviewer_id"], str)
    assert data["review_level"] in ("PRIMARY", "SECONDARY")
    assert data["outcome"] in ("APPROVE", "DENY")
    assert isinstance(data["rationale"], str)
    assert is_iso8601_timestamp(data["decided_at"])


def assert_fraud_flag(data: dict) -> None:
    _assert_append_only_fields(data, "FraudFlag")
    assert isinstance(data["claim_id"], str)
    assert data["signal"] in (
        "DUPLICATE_PATTERN", "REPAIR_SHOP_COLLUSION",
        "DOCUMENT_FORGERY", "RAPID_RESUBMISSION",
    )
    assert isinstance(data["severity"], (int, float))
    assert 0.0 <= float(data["severity"]) <= 1.0


def assert_audit_log_entry(data: dict) -> None:
    _assert_append_only_fields(data, "AuditLogEntry")
    assert isinstance(data["claim_id"], str)
    assert isinstance(data["actor_id"], str)
    assert isinstance(data["actor_role"], str)
    assert data["event_type"] in (
        "STATUS_CHANGE", "REVIEW_DECISION", "APPEAL_DECISION",
        "PAYOUT_EVENT", "FRAUD_FLAG_ADDED",
    )
    assert isinstance(data["payload"], dict)


# ─── Domain invariants ────────────────────────────────────────────
def assert_payout_balance_invariant(claim: dict) -> None:
    """PRD §3.5 (net payout): "The compensating invariant — that
    gross_payout_cents minus salvage_value_cents minus subrogation_recovery_cents
    equals net_payout_cents — must hold at all times."

    With the additional clamp at zero ("if that subtraction would yield a
    negative number, the result is clamped to zero").
    """
    g = claim.get("gross_payout_cents")
    if g is None:
        return  # No gross pinned yet (e.g., still in INTAKE / UNDER_INVESTIGATION).
    s = claim["salvage_value_cents"]
    r = claim["subrogation_recovery_cents"]
    n = claim["net_payout_cents"]
    expected_net = max(0, g - s - r)
    assert n == expected_net, (
        f"Net-payout invariant broken: gross={g}, salvage={s}, subrog={r}, "
        f"net={n}, expected_net={expected_net}"
    )


def find_audit_entry(entries: list, *, event_type: str,
                     from_state=None, to_state=None) -> dict:
    """Return the first AuditLogEntry matching the predicate, or raise."""
    for e in entries:
        if e.get("event_type") != event_type:
            continue
        if from_state is not None and e.get("from_state") != from_state:
            continue
        if to_state is not None and e.get("to_state") != to_state:
            continue
        return e
    raise AssertionError(
        f"No AuditLogEntry matching event_type={event_type!r}, "
        f"from_state={from_state!r}, to_state={to_state!r} found among "
        f"{[(e.get('event_type'), e.get('from_state'), e.get('to_state')) for e in entries]}"
    )


def has_audit_entry(entries: list, *, event_type: str,
                    from_state=None, to_state=None) -> bool:
    try:
        find_audit_entry(entries, event_type=event_type,
                         from_state=from_state, to_state=to_state)
        return True
    except AssertionError:
        return False
