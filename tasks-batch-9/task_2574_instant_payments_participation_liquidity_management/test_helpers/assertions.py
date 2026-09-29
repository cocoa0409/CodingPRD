"""Entity-shape and domain-invariant assertions.

Every entity except `LiquidityLedgerEntry` carries the full system quartet of
`id`, `created_at`, `updated_at` and `version`; a ledger entry is an append-only
accounting fact that carries only `id` and `created_at`, so it gets its own
shape check that positively asserts the absence of the other two.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from . import constants as K
from .types import Json

# --------------------------------------------------------------------- system fields
FULL_SYSTEM_FIELDS = ("id", "created_at", "updated_at", "version")
IMMUTABLE_SYSTEM_FIELDS = ("id", "created_at")


def assert_system_fields(entity: Json, entity_name: str = "resource") -> None:
    """Assert the id/created_at/updated_at/version quartet on a versioned entity."""
    for name in FULL_SYSTEM_FIELDS:
        assert name in entity, f"{entity_name} is missing the system field {name!r}"
    assert is_valid_uuid(entity["id"]), f"{entity_name}.id is not a bare UUID: {entity['id']!r}"
    assert is_iso8601_timestamp(entity["created_at"]), f"{entity_name}.created_at is not ISO 8601"
    assert is_iso8601_timestamp(entity["updated_at"]), f"{entity_name}.updated_at is not ISO 8601"
    assert isinstance(entity["version"], int) and entity["version"] >= 1, (
        f"{entity_name}.version must be an integer starting at 1, got {entity['version']!r}"
    )


def assert_immutable_system_fields(entity: Json, entity_name: str = "resource") -> None:
    """Assert an append-only entity carries only `id` and `created_at`."""
    for name in IMMUTABLE_SYSTEM_FIELDS:
        assert name in entity, f"{entity_name} is missing the system field {name!r}"
    assert is_valid_uuid(entity["id"]), f"{entity_name}.id is not a bare UUID: {entity['id']!r}"
    assert is_iso8601_timestamp(entity["created_at"]), f"{entity_name}.created_at is not ISO 8601"
    assert "updated_at" not in entity, f"{entity_name} must not carry updated_at"
    assert "version" not in entity, f"{entity_name} must not carry version"


def _assert_enum(entity: Json, field: str, allowed: Sequence[str], entity_name: str) -> None:
    assert entity[field] in allowed, (
        f"{entity_name}.{field} is {entity[field]!r}, outside the declared set {tuple(allowed)}"
    )


# --------------------------------------------------------------------- Participant
def assert_participant_shape(participant: Json) -> None:
    assert_system_fields(participant, "Participant")
    for field in (
        "legal_name",
        "routing_number",
        "settlement_agent_reference",
        "participation_model",
        "enrollment_status",
        "operational_posture",
        "certification_round",
        "certification_test_suite_version",
        "attestation_document_reference",
        "go_live_business_date",
        "suspension_reason",
    ):
        assert field in participant, f"Participant is missing {field!r}"
    _assert_enum(participant, "participation_model", K.PARTICIPATION_MODELS, "Participant")
    _assert_enum(participant, "enrollment_status", K.ENROLLMENT_STATUSES, "Participant")
    _assert_enum(participant, "operational_posture", K.OPERATIONAL_POSTURES, "Participant")
    assert len(participant["routing_number"]) == 9 and participant["routing_number"].isdigit(), (
        "Participant.routing_number must be exactly nine digits"
    )
    assert isinstance(participant["certification_round"], int)


# ------------------------------------------------------------ PrefundedPositionAccount
def assert_position_account_shape(account: Json) -> None:
    assert_system_fields(account, "PrefundedPositionAccount")
    for field in (
        "participant_id",
        "opening_balance_cents",
        "warning_threshold_cents",
        "critical_threshold_cents",
        "floor_cents",
        "current_balance_cents",
        "reserved_cents",
        "available_cents",
        "alert_tier",
        "last_ledger_sequence_no",
    ):
        assert field in account, f"PrefundedPositionAccount is missing {field!r}"
    _assert_enum(account, "alert_tier", K.ALERT_TIERS, "PrefundedPositionAccount")
    for field in (
        "opening_balance_cents",
        "current_balance_cents",
        "reserved_cents",
        "available_cents",
        "last_ledger_sequence_no",
    ):
        assert isinstance(account[field], int), f"PrefundedPositionAccount.{field} must be an integer"
    assert account["available_cents"] == account["current_balance_cents"] - account["reserved_cents"], (
        "available_cents must equal current_balance_cents minus reserved_cents"
    )


def assert_account_position(
    account: Json,
    current_balance_cents: int,
    reserved_cents: int,
    available_cents: int,
    alert_tier: Optional[str] = None,
) -> None:
    """Assert the derived trio, and optionally the band, in one place."""
    assert account["current_balance_cents"] == current_balance_cents, (
        f"current_balance_cents {account['current_balance_cents']} != {current_balance_cents}"
    )
    assert account["reserved_cents"] == reserved_cents, (
        f"reserved_cents {account['reserved_cents']} != {reserved_cents}"
    )
    assert account["available_cents"] == available_cents, (
        f"available_cents {account['available_cents']} != {available_cents}"
    )
    if alert_tier is not None:
        assert account["alert_tier"] == alert_tier, (
            f"alert_tier {account['alert_tier']!r} != {alert_tier!r}"
        )


# --------------------------------------------------------------- LiquidityLedgerEntry
def assert_ledger_entry_shape(entry: Json) -> None:
    assert_immutable_system_fields(entry, "LiquidityLedgerEntry")
    for field in (
        "account_id",
        "entry_type",
        "amount_cents",
        "balance_after_cents",
        "business_date",
        "sequence_no",
        "related_transfer_id",
        "reference",
    ):
        assert field in entry, f"LiquidityLedgerEntry is missing {field!r}"
    _assert_enum(entry, "entry_type", K.LEDGER_ENTRY_TYPES, "LiquidityLedgerEntry")
    assert isinstance(entry["amount_cents"], int)
    assert isinstance(entry["balance_after_cents"], int)
    assert isinstance(entry["sequence_no"], int) and entry["sequence_no"] >= 1
    if entry["entry_type"] in K.CREDIT_ENTRY_TYPES:
        assert entry["amount_cents"] > 0, "a credit entry must carry a positive amount_cents"
    else:
        assert entry["amount_cents"] < 0, "a debit entry must carry a negative amount_cents"


def assert_ledger_entry(
    entry: Json,
    entry_type: str,
    amount_cents: int,
    balance_after_cents: int,
    sequence_no: int,
    business_date: Optional[str] = None,
) -> None:
    assert_ledger_entry_shape(entry)
    assert entry["entry_type"] == entry_type, f"entry_type {entry['entry_type']!r} != {entry_type!r}"
    assert entry["amount_cents"] == amount_cents, f"amount_cents {entry['amount_cents']} != {amount_cents}"
    assert entry["balance_after_cents"] == balance_after_cents, (
        f"balance_after_cents {entry['balance_after_cents']} != {balance_after_cents}"
    )
    assert entry["sequence_no"] == sequence_no, f"sequence_no {entry['sequence_no']} != {sequence_no}"
    if business_date is not None:
        assert entry["business_date"] == business_date, (
            f"business_date {entry['business_date']!r} != {business_date!r}"
        )


def assert_ledger_identity(account: Json, entries: Sequence[Json]) -> None:
    """current_balance_cents == opening_balance_cents + the signed sum of all entries."""
    signed_sum = sum(entry["amount_cents"] for entry in entries)
    expected = account["opening_balance_cents"] + signed_sum
    assert account["current_balance_cents"] == expected, (
        f"ledger identity broken: current_balance_cents {account['current_balance_cents']} != "
        f"opening {account['opening_balance_cents']} + signed sum {signed_sum}"
    )


def assert_sequence_numbers_are_dense(entries: Sequence[Json]) -> None:
    """sequence_no is a per-account ordinal beginning at 1 and rising by one."""
    ordinals = [entry["sequence_no"] for entry in entries]
    assert ordinals == list(range(1, len(entries) + 1)), (
        f"sequence numbers must be 1..{len(entries)} in ascending order, got {ordinals}"
    )


def assert_running_balances(opening_balance_cents: int, entries: Sequence[Json]) -> None:
    """Each entry's balance_after_cents is the running balance at that ordinal."""
    running = opening_balance_cents
    for entry in entries:
        running += entry["amount_cents"]
        assert entry["balance_after_cents"] == running, (
            f"entry sequence_no {entry['sequence_no']} carries balance_after_cents "
            f"{entry['balance_after_cents']} but the running balance is {running}"
        )


# ------------------------------------------------------------------- LiquidityAlert
def assert_liquidity_alert_shape(alert: Json) -> None:
    assert_system_fields(alert, "LiquidityAlert")
    for field in (
        "account_id",
        "tier",
        "status",
        "threshold_cents",
        "observed_balance_cents",
        "acknowledged_by_user_id",
        "remediation_plan",
        "escalated_at",
        "cleared_at",
    ):
        assert field in alert, f"LiquidityAlert is missing {field!r}"
    _assert_enum(alert, "tier", ("AMBER", "RED", "BREACH"), "LiquidityAlert")
    _assert_enum(alert, "status", K.ALERT_STATUSES, "LiquidityAlert")


def assert_alert(
    alert: Json,
    tier: str,
    status: str,
    threshold_cents: int,
    observed_balance_cents: int,
) -> None:
    assert_liquidity_alert_shape(alert)
    assert alert["tier"] == tier, f"alert tier {alert['tier']!r} != {tier!r}"
    assert alert["status"] == status, f"alert status {alert['status']!r} != {status!r}"
    assert alert["threshold_cents"] == threshold_cents, (
        f"alert threshold_cents {alert['threshold_cents']} != {threshold_cents}"
    )
    assert alert["observed_balance_cents"] == observed_balance_cents, (
        f"alert observed_balance_cents {alert['observed_balance_cents']} != {observed_balance_cents}"
    )


# -------------------------------------------------------------- CustomerSegmentPolicy
def assert_segment_policy_shape(policy: Json) -> None:
    assert_system_fields(policy, "CustomerSegmentPolicy")
    for field in (
        "participant_id",
        "segment",
        "per_transaction_limit_cents",
        "daily_aggregate_limit_cents",
        "rolling_window_count_limit",
        "rolling_window_amount_limit_cents",
        "effective_from",
        "effective_to",
        "superseded_at",
    ):
        assert field in policy, f"CustomerSegmentPolicy is missing {field!r}"
    _assert_enum(policy, "segment", K.SEGMENTS, "CustomerSegmentPolicy")
    assert policy["per_transaction_limit_cents"] > 0
    assert policy["daily_aggregate_limit_cents"] >= policy["per_transaction_limit_cents"]
    assert policy["rolling_window_count_limit"] > 0
    assert policy["rolling_window_amount_limit_cents"] > 0


# ------------------------------------------------------------------ CustomerAccount
def assert_customer_account_shape(account: Json) -> None:
    assert_system_fields(account, "CustomerAccount")
    for field in (
        "participant_id",
        "segment",
        "account_reference",
        "fraud_risk_baseline",
        "status",
        "daily_sent_amount_cents",
        "restricted_at",
    ):
        assert field in account, f"CustomerAccount is missing {field!r}"
    _assert_enum(account, "segment", K.SEGMENTS, "CustomerAccount")
    _assert_enum(account, "status", K.CUSTOMER_ACCOUNT_STATUSES, "CustomerAccount")
    assert 0 <= account["fraud_risk_baseline"] <= 100


# -------------------------------------------------------------------- CreditTransfer
def assert_credit_transfer_shape(transfer: Json) -> None:
    assert_system_fields(transfer, "CreditTransfer")
    for field in (
        "originator_participant_id",
        "customer_account_id",
        "segment_policy_id",
        "receiver_routing_number",
        "amount_cents",
        "direction",
        "rail",
        "clearing_status",
        "exception_status",
        "fraud_score",
        "fraud_reason_codes",
        "rejection_reason_code",
        "remittance_reference",
        "rfp_id",
        "compensating_for_transfer_id",
        "initiated_by_user_id",
        "accepted_at",
        "irrevocable_at",
        "settled_at",
        "settlement_business_date",
        "queued_at",
        # PRD 3.9 says a diversion "writes the supplied value into the transfer's
        # `rail`" and names no `diverted_to_rail` or `diverted_at` attribute anywhere,
        # so neither field may be demanded of a PRD-faithful serializer.
    ):
        assert field in transfer, f"CreditTransfer is missing {field!r}"
    _assert_enum(transfer, "direction", K.TRANSFER_DIRECTIONS, "CreditTransfer")
    _assert_enum(transfer, "rail", K.TRANSFER_RAILS, "CreditTransfer")
    _assert_enum(transfer, "clearing_status", K.CLEARING_STATUSES, "CreditTransfer")
    _assert_enum(transfer, "exception_status", K.EXCEPTION_STATUSES, "CreditTransfer")
    assert isinstance(transfer["fraud_reason_codes"], list)
    for code in transfer["fraud_reason_codes"]:
        assert code in K.FRAUD_REASON_CODES, f"unknown fraud reason code {code!r}"
    assert 0 <= transfer["fraud_score"] <= K.FRAUD_SCORE_CEILING


def assert_transfer_dimensions(transfer: Json, clearing_status: str, exception_status: str) -> None:
    """Assert both independent status dimensions of a transfer at once."""
    assert transfer["clearing_status"] == clearing_status, (
        f"clearing_status {transfer['clearing_status']!r} != {clearing_status!r}"
    )
    assert transfer["exception_status"] == exception_status, (
        f"exception_status {transfer['exception_status']!r} != {exception_status!r}"
    )


# ----------------------------------------------------------------- RequestForPayment
def assert_request_for_payment_shape(rfp: Json) -> None:
    assert_system_fields(rfp, "RequestForPayment")
    for field in (
        "requestor_participant_id",
        "debtor_customer_account_id",
        "amount_cents",
        "expiry_at",
        "memo",
        "status",
        "delivered_at",
        "response_deadline_at",
        "last_response",
        "decline_reason_code",
        "amendment_round",
    ):
        assert field in rfp, f"RequestForPayment is missing {field!r}"
    _assert_enum(rfp, "status", K.RFP_STATUSES, "RequestForPayment")
    assert isinstance(rfp["amendment_round"], int) and 0 <= rfp["amendment_round"] <= K.MAX_AMENDMENT_ROUNDS


# ---------------------------------------------------------------------- FraudReview
def assert_fraud_review_shape(review: Json) -> None:
    assert_system_fields(review, "FraudReview")
    for field in (
        "credit_transfer_id",
        "status",
        "score_at_origination",
        "final_fraud_score",
        "queue_priority",
        "assigned_reviewer_user_id",
        "sla_deadline_at",
        "decision_rationale",
    ):
        assert field in review, f"FraudReview is missing {field!r}"
    _assert_enum(review, "status", K.FRAUD_REVIEW_STATUSES, "FraudReview")
    assert review["queue_priority"] in (1, 2), f"queue_priority must be 1 or 2, got {review['queue_priority']!r}"


# --------------------------------------------------------------------- ReturnRequest
def assert_return_request_shape(request: Json) -> None:
    assert_system_fields(request, "ReturnRequest")
    for field in (
        "credit_transfer_id",
        "requested_by_participant_id",
        "reason_code",
        "narrative",
        "original_amount_cents",
        "returned_amount_cents",
        "status",
        "response_deadline_at",
        "decline_reason_code",
        "honored_transfer_id",
    ):
        assert field in request, f"ReturnRequest is missing {field!r}"
    _assert_enum(request, "reason_code", K.RETURN_REASON_CODES, "ReturnRequest")
    _assert_enum(request, "status", K.RETURN_STATUSES, "ReturnRequest")


# -------------------------------------------------------------------- SettlementCycle
def assert_settlement_cycle_shape(cycle: Json) -> None:
    assert_system_fields(cycle, "SettlementCycle")
    for field in (
        "business_date",
        "status",
        "cutoff_at",
        "closed_at",
        "assessed_fee_total_cents",
        "settled_transfer_count",
    ):
        assert field in cycle, f"SettlementCycle is missing {field!r}"
    _assert_enum(cycle, "status", K.SETTLEMENT_CYCLE_STATUSES, "SettlementCycle")
    assert isinstance(cycle["assessed_fee_total_cents"], int)
    assert isinstance(cycle["settled_transfer_count"], int)


# ------------------------------------------------------------------ ReconciliationRun
def assert_reconciliation_run_shape(run: Json) -> None:
    assert_system_fields(run, "ReconciliationRun")
    for field in (
        "settlement_cycle_id",
        "participant_id",
        "variant",
        "revision",
        "core_deposit_total_cents",
        "rail_net_position_cents",
        "fee_component_cents",
        "variance_cents",
        "outcome",
        "included_transfer_count",
    ):
        assert field in run, f"ReconciliationRun is missing {field!r}"
    _assert_enum(run, "variant", K.RECONCILIATION_VARIANTS, "ReconciliationRun")
    _assert_enum(run, "outcome", K.RECONCILIATION_OUTCOMES, "ReconciliationRun")
    assert run["revision"] >= 1
    assert run["variance_cents"] == run["core_deposit_total_cents"] - run["rail_net_position_cents"], (
        "variance_cents must equal core_deposit_total_cents minus rail_net_position_cents"
    )


def assert_reconciliation_figures(
    run: Json,
    rail_net_position_cents: int,
    variance_cents: int,
    outcome: str,
    included_transfer_count: int,
    fee_component_cents: int,
    revision: int,
) -> None:
    assert_reconciliation_run_shape(run)
    assert run["rail_net_position_cents"] == rail_net_position_cents
    assert run["variance_cents"] == variance_cents
    assert run["outcome"] == outcome
    assert run["included_transfer_count"] == included_transfer_count
    assert run["fee_component_cents"] == fee_component_cents
    assert run["revision"] == revision


# ---------------------------------------------------------------------- OutageEvent
def assert_outage_event_shape(event: Json) -> None:
    assert_system_fields(event, "OutageEvent")
    for field in (
        "scope",
        "severity",
        "fallback_rail",
        "started_at",
        "ended_at",
        "participant_id",
        "status",
        "diverted_transfer_count",
    ):
        assert field in event, f"OutageEvent is missing {field!r}"
    _assert_enum(event, "scope", K.OUTAGE_SCOPES, "OutageEvent")
    _assert_enum(event, "severity", K.OUTAGE_SEVERITIES, "OutageEvent")
    _assert_enum(event, "fallback_rail", K.FALLBACK_RAILS, "OutageEvent")
    _assert_enum(event, "status", K.OUTAGE_STATUSES, "OutageEvent")
    assert isinstance(event["diverted_transfer_count"], int)


# ---------------------------------------------------------------------- misc helpers
def assert_sweep_counts(
    report: Json,
    expired_rfp_count: int,
    expired_return_request_count: int,
    expired_transfer_count: int,
    escalated_alert_count: int,
) -> None:
    """Assert all four counts the housekeeping sweep reports."""
    assert report["expired_rfp_count"] == expired_rfp_count, (
        f"expired_rfp_count {report['expired_rfp_count']} != {expired_rfp_count}"
    )
    assert report["expired_return_request_count"] == expired_return_request_count, (
        f"expired_return_request_count {report['expired_return_request_count']} != {expired_return_request_count}"
    )
    assert report["expired_transfer_count"] == expired_transfer_count, (
        f"expired_transfer_count {report['expired_transfer_count']} != {expired_transfer_count}"
    )
    assert report["escalated_alert_count"] == escalated_alert_count, (
        f"escalated_alert_count {report['escalated_alert_count']} != {escalated_alert_count}"
    )


def _parse_instant(value: str, label: str) -> "datetime":
    assert isinstance(value, str), f"{label} is not a timestamp string: {value!r}"
    text = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        return datetime.fromisoformat(text)
    except ValueError as exc:  # pragma: no cover - surfaces as a readable failure
        raise AssertionError(f"{label} is not a parseable ISO 8601 instant: {value!r}") from exc


def assert_instant(actual: Any, expected: str, field: str = "timestamp") -> None:
    """Assert `actual` names exactly the same UTC instant as `expected`.

    PRD 2.4 pins three fractional digits on `created_at` and `updated_at`, while
    PRD 2.5 quotes the logical clock itself as `2026-08-01T00:00:00Z` with none. The
    PRD therefore does not pin a single wire spelling for the clock-derived domain
    timestamps, so the instant — not its spelling — is what these tests assert. The
    comparison stays exact to the millisecond; only the trailing-zero fraction is
    treated as the same instant it denotes.
    """
    assert actual is not None, f"{field} should be stamped, got None"
    assert _parse_instant(actual, field) == _parse_instant(expected, f"expected {field}"), (
        f"{field} is {actual!r}, which is not the instant {expected!r}"
    )


def assert_null_fields(entity: Json, *fields: str) -> None:
    for field in fields:
        assert entity[field] is None, f"{field} should still be null, got {entity[field]!r}"


def assert_pagination_meta(
    meta: Dict[str, Any],
    total_count: int,
    has_more: bool,
    limit: Optional[int] = None,
    offset: Optional[int] = None,
) -> None:
    assert meta["total_count"] == total_count, f"total_count {meta['total_count']} != {total_count}"
    assert meta["has_more"] is has_more, f"has_more {meta['has_more']!r} != {has_more!r}"
    if limit is not None:
        assert meta["limit"] == limit, f"limit {meta['limit']} != {limit}"
    if offset is not None:
        assert meta["offset"] == offset, f"offset {meta['offset']} != {offset}"
