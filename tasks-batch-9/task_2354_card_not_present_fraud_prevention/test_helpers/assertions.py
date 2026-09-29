"""Entity-shape assertions and reconciliation checks for the two conserved ledgers."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import pytest
from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_paginated,
    validate_success,
)

from .constants import RATE_TOLERANCE, SCORE_TOLERANCE
from .types import (
    AccountStatus,
    AddressClassification,
    AnalystStatus,
    AssessmentState,
    AtoPosture,
    AuthOutcome,
    BlendMode,
    CaseState,
    ChallengeState,
    ChargebackState,
    Cohort,
    CustomerTier,
    Decision,
    DeviceReputation,
    DropRiskState,
    ExceptionScope,
    ExceptionState,
    GuaranteeState,
    OutcomeLabel,
    RiskModelStatus,
    RulePackStatus,
    Seniority,
    SignalFamily,
)

# ---------------------------------------------------------------------------
# Shared primitives
# ---------------------------------------------------------------------------


def assert_uuid_without_prefix(value: Any, field: str = "id") -> None:
    """A server-minted UUID, with no type prefix of any kind."""
    assert isinstance(value, str), f"{field} must be a string, got {type(value)!r}"
    assert is_valid_uuid(value), f"{field} must be a bare UUID with no prefix: {value!r}"


def assert_timestamp(value: Any, field: str) -> None:
    """An ISO 8601 UTC timestamp with three fractional digits."""
    assert value is not None, f"{field} must not be null"
    assert is_iso8601_timestamp(value), f"{field} is not an ISO 8601 UTC instant: {value!r}"


def assert_common_fields(data: Dict[str, Any], entity: str) -> None:
    """``id``, ``created_at``, ``updated_at`` and ``version`` on a versioned row."""
    assert_uuid_without_prefix(data.get("id"), f"{entity}.id")
    assert_timestamp(data.get("created_at"), f"{entity}.created_at")
    assert_timestamp(data.get("updated_at"), f"{entity}.updated_at")
    version = data.get("version")
    assert isinstance(version, int), f"{entity}.version must be an integer, got {version!r}"
    assert version >= 1, f"{entity}.version starts at 1, got {version}"


def assert_enum(data: Dict[str, Any], field: str, allowed: Any, entity: str) -> None:
    value = data.get(field)
    assert value in allowed, (
        f"{entity}.{field} must be one of {tuple(allowed)}, got {value!r}"
    )


def assert_counter(data: Dict[str, Any], field: str, entity: str) -> None:
    value = data.get(field)
    assert isinstance(value, int) and not isinstance(value, bool), (
        f"{entity}.{field} must be an integer, got {value!r}"
    )
    assert value >= 0, f"{entity}.{field} must never go negative, got {value}"


def assert_two_decimal_places(value: Any, field: str) -> None:
    """Scores carried at two decimal places."""
    assert isinstance(value, (int, float)) and not isinstance(value, bool), (
        f"{field} must be numeric, got {value!r}"
    )
    assert round(float(value), 2) == pytest.approx(float(value), abs=1e-9), (
        f"{field} must be carried at two decimal places, got {value!r}"
    )


def assert_four_decimal_places(value: Any, field: str) -> None:
    """Rates carried at four decimal places."""
    assert isinstance(value, (int, float)) and not isinstance(value, bool), (
        f"{field} must be numeric, got {value!r}"
    )
    assert round(float(value), 4) == pytest.approx(float(value), abs=1e-9), (
        f"{field} must be carried at four decimal places, got {value!r}"
    )


def assert_score(actual: Any, expected: float, field: str) -> None:
    assert actual == pytest.approx(expected, abs=SCORE_TOLERANCE), (
        f"{field} should be {expected}, got {actual}"
    )


def assert_rate(actual: Any, expected: float, field: str) -> None:
    assert actual == pytest.approx(expected, abs=RATE_TOLERANCE), (
        f"{field} should be {expected}, got {actual}"
    )


# ---------------------------------------------------------------------------
# Customer
# ---------------------------------------------------------------------------


def assert_customer(data: Dict[str, Any]) -> None:
    assert_common_fields(data, "customer")
    assert isinstance(data.get("email"), str), "customer.email must be a string"
    home_country = data.get("home_country")
    assert isinstance(home_country, str) and home_country == home_country.upper() and len(
        home_country
    ) == 2, f"customer.home_country must be exactly two uppercase letters, got {home_country!r}"
    assert_enum(data, "tier", CustomerTier.ALL, "customer")
    assert_enum(data, "account_status", AccountStatus.ALL, "customer")
    assert_enum(data, "ato_posture", AtoPosture.ALL, "customer")
    assert isinstance(data.get("good_customer_flag"), bool), (
        "customer.good_customer_flag must be a boolean"
    )
    for counter in (
        "lifetime_net_approved_cents",
        "approved_count",
        "declined_count",
        "confirmed_fraud_count",
        "failed_login_count",
    ):
        assert_counter(data, counter, "customer")


def assert_new_customer_defaults(data: Dict[str, Any]) -> None:
    """A new account starts ACTIVE, CLEAR, unlocked, not good, and all-zero."""
    assert_customer(data)
    assert data["account_status"] == AccountStatus.ACTIVE
    assert data["ato_posture"] == AtoPosture.CLEAR
    assert data["locked_reason"] is None, "a new account has no locked_reason"
    assert data["good_customer_flag"] is False
    assert data["lifetime_net_approved_cents"] == 0
    assert data["approved_count"] == 0
    assert data["declined_count"] == 0
    assert data["confirmed_fraud_count"] == 0
    assert data["failed_login_count"] == 0
    assert data["version"] == 1, "a freshly created row is at version 1"


# ---------------------------------------------------------------------------
# Device profile
# ---------------------------------------------------------------------------


def assert_device(data: Dict[str, Any]) -> None:
    assert_common_fields(data, "device")
    assert isinstance(data.get("device_hash"), str), "device.device_hash must be a string"
    assert isinstance(data.get("tz_offset_minutes"), int), (
        "device.tz_offset_minutes must be an integer"
    )
    assert isinstance(data.get("emulator_flag"), bool), (
        "device.emulator_flag must be a boolean"
    )
    assert_enum(data, "reputation", DeviceReputation.ALL, "device")
    for counter in (
        "distinct_customer_count",
        "approved_use_count",
        "fraud_confirmed_count",
    ):
        assert_counter(data, counter, "device")


# ---------------------------------------------------------------------------
# Address
# ---------------------------------------------------------------------------


def assert_address(data: Dict[str, Any]) -> None:
    assert_common_fields(data, "address")
    assert isinstance(data.get("line1"), str), "address.line1 must be a string"
    assert isinstance(data.get("postal_code"), str), "address.postal_code must be a string"
    country_code = data.get("country_code")
    assert isinstance(country_code, str) and country_code == country_code.upper() and len(
        country_code
    ) == 2, f"address.country_code must be exactly two uppercase letters, got {country_code!r}"
    assert_enum(data, "classification", AddressClassification.ALL, "address")
    assert_uuid_without_prefix(data.get("canonical_address_id"), "address.canonical_address_id")
    assert_enum(data, "drop_risk_state", DropRiskState.ALL, "address")
    for counter in (
        "distinct_customer_count",
        "approved_use_count",
        "fraud_confirmed_count",
        "promo_redemption_count",
    ):
        assert_counter(data, counter, "address")
    assert_two_decimal_places(data.get("reshipper_confidence"), "address.reshipper_confidence")
    assert 0.0 <= float(data["reshipper_confidence"]) <= 1.0, (
        "address.reshipper_confidence never exceeds 1.00"
    )


def assert_cluster_root(data: Dict[str, Any]) -> None:
    """A row that is its own cluster root."""
    assert data.get("canonical_parent_address_id") is None, (
        "a cluster root has a null canonical_parent_address_id"
    )
    assert data["canonical_address_id"] == data["id"], (
        "a cluster root's canonical_address_id equals its own id"
    )


def assert_cluster_variant(data: Dict[str, Any], parent_id: str) -> None:
    """A row that is a unit or suite variant of another address."""
    assert data.get("canonical_parent_address_id") == parent_id
    assert data["canonical_address_id"] == parent_id, (
        "a variant's canonical_address_id equals its parent's id"
    )


def assert_variant_reports_no_cluster_intelligence(data: Dict[str, Any]) -> None:
    """A variant row permanently reports zeroes, CLEAN and 0.00."""
    assert data["distinct_customer_count"] == 0
    assert data["approved_use_count"] == 0
    assert data["fraud_confirmed_count"] == 0
    assert data["promo_redemption_count"] == 0
    assert data["drop_risk_state"] == DropRiskState.CLEAN
    assert_score(data["reshipper_confidence"], 0.00, "variant.reshipper_confidence")


# ---------------------------------------------------------------------------
# Rule pack and fraud rule
# ---------------------------------------------------------------------------


def assert_rule_pack(data: Dict[str, Any]) -> None:
    assert_common_fields(data, "rule_pack")
    assert isinstance(data.get("version_label"), str)
    assert_enum(data, "status", RulePackStatus.ALL, "rule_pack")
    assert_enum(data, "blend_mode", BlendMode.ALL, "rule_pack")
    for field in ("rule_weight", "model_weight", "review_floor_score", "decline_floor_score"):
        assert_two_decimal_places(data.get(field), f"rule_pack.{field}")
    assert 0.0 <= float(data["rule_weight"]) <= 1.0
    assert 0.0 <= float(data["model_weight"]) <= 1.0
    assert_timestamp(data.get("effective_from"), "rule_pack.effective_from")
    assert_timestamp(data.get("effective_until"), "rule_pack.effective_until")
    assert_counter(data, "rule_count", "rule_pack")
    assert isinstance(data.get("created_by_user_id"), str), (
        "rule_pack.created_by_user_id records the drafting engineer"
    )


def assert_fraud_rule(data: Dict[str, Any]) -> None:
    """A fraud rule carries only ``id`` and ``created_at`` as audit stamps."""
    assert_uuid_without_prefix(data.get("id"), "rule.id")
    assert_timestamp(data.get("created_at"), "rule.created_at")
    assert "updated_at" not in data, (
        "a fraud rule is immutable: updated_at is absent from it entirely"
    )
    assert "version" not in data, (
        "a fraud rule is immutable: version is absent from it entirely"
    )
    assert_uuid_without_prefix(data.get("rule_pack_id"), "rule.rule_pack_id")
    assert isinstance(data.get("code"), str)
    assert_enum(data, "signal_family", SignalFamily.ALL, "rule")
    points = data.get("points")
    assert isinstance(points, int) and 0 <= points <= 100, (
        f"rule.points must be between 0 and 100 inclusive, got {points!r}"
    )
    order = data.get("evaluation_order")
    assert isinstance(order, int) and order >= 1, (
        f"rule.evaluation_order must be at least 1, got {order!r}"
    )
    assert isinstance(data.get("hard_decline"), bool)


# ---------------------------------------------------------------------------
# Risk model
# ---------------------------------------------------------------------------


def assert_risk_model(data: Dict[str, Any]) -> None:
    assert_common_fields(data, "risk_model")
    assert isinstance(data.get("model_version_label"), str)
    assert_enum(data, "status", RiskModelStatus.ALL, "risk_model")
    intercept = float(data["calibration_intercept"])
    assert -1.0 <= intercept <= 1.0, (
        f"risk_model.calibration_intercept must be between -1.0 and 1.0, got {intercept}"
    )
    slope = float(data["calibration_slope"])
    assert 0.0 < slope <= 4.0, (
        f"risk_model.calibration_slope must be above 0.0 and at most 4.0, got {slope}"
    )
    assert_counter(data, "scored_assessment_count", "risk_model")
    counts = data.get("training_segment_counts")
    assert counts is None or isinstance(counts, dict), (
        "risk_model.training_segment_counts is null or a per-reason-code map"
    )


# ---------------------------------------------------------------------------
# Checkout assessment
# ---------------------------------------------------------------------------


def assert_assessment(data: Dict[str, Any]) -> None:
    assert_common_fields(data, "assessment")
    for fk in (
        "customer_id",
        "device_profile_id",
        "shipping_address_id",
        "billing_address_id",
        "rule_pack_id",
        "risk_model_id",
    ):
        assert_uuid_without_prefix(data.get(fk), f"assessment.{fk}")
    amount = data.get("amount_cents")
    assert isinstance(amount, int) and amount >= 1, (
        f"assessment.amount_cents must be an integer of at least 1, got {amount!r}"
    )
    card_bin = data.get("card_bin")
    assert isinstance(card_bin, str) and len(card_bin) == 6 and card_bin.isdigit(), (
        f"assessment.card_bin must be exactly six digits, got {card_bin!r}"
    )
    ip_country = data.get("ip_country")
    assert isinstance(ip_country, str) and len(ip_country) == 2 and ip_country.isupper(), (
        f"assessment.ip_country must be exactly two uppercase letters, got {ip_country!r}"
    )
    assert isinstance(data.get("session_seconds"), int) and data["session_seconds"] >= 0
    assert isinstance(data.get("cart_item_count"), int) and data["cart_item_count"] >= 1
    assert_enum(data, "state", AssessmentState.ALL, "assessment")
    assert_enum(data, "outcome_label", OutcomeLabel.ALL, "assessment")
    assert isinstance(data.get("hard_decline_triggered"), bool)
    if data.get("decision") is not None:
        assert_enum(data, "decision", Decision.ALL, "assessment")


def assert_unscored_assessment(data: Dict[str, Any]) -> None:
    """The row created in PENDING_SIGNALS with every score field null."""
    assert_assessment(data)
    assert data["state"] == AssessmentState.PENDING_SIGNALS
    for field in (
        "velocity_customer_assessment_count_1h",
        "velocity_device_distinct_card_bin_count_24h",
        "velocity_promo_address_count_30d",
        "rule_score",
        "model_points",
        "blended_score",
        "triggered_rule_codes",
        "primary_signal_family",
        "decision",
        "decision_reason",
        "final_disposition",
        "decided_at",
        "good_customer_at_decision",
    ):
        assert data.get(field) is None, f"assessment.{field} must be null before scoring"
    assert data["hard_decline_triggered"] is False
    assert data["applied_exception_id"] is None
    assert data["outcome_label"] == OutcomeLabel.UNKNOWN


def assert_scored_assessment(data: Dict[str, Any]) -> None:
    """Every score field is written whichever branch of the fork was taken."""
    assert_assessment(data)
    for field in (
        "velocity_customer_assessment_count_1h",
        "velocity_device_distinct_card_bin_count_24h",
        "velocity_promo_address_count_30d",
        "rule_score",
        "model_points",
        "blended_score",
        "triggered_rule_codes",
        "primary_signal_family",
        "decision",
        "decision_reason",
    ):
        assert data.get(field) is not None, f"assessment.{field} is written at scoring"
    assert 0 <= int(data["rule_score"]) <= 100, "rule_score is capped at 100"
    assert_two_decimal_places(data["model_points"], "assessment.model_points")
    assert_two_decimal_places(data["blended_score"], "assessment.blended_score")
    assert 0.0 <= float(data["blended_score"]) <= 200.00, "blended_score never exceeds 200.00"
    assert 0.0 <= float(data["model_points"]) <= 100.00, "model_points is between 0.00 and 100.00"
    assert int(data["velocity_device_distinct_card_bin_count_24h"]) >= 1, (
        "the scored assessment's own card_bin is always included, so the minimum is 1"
    )


# ---------------------------------------------------------------------------
# Analyst and review case
# ---------------------------------------------------------------------------


def assert_analyst(data: Dict[str, Any]) -> None:
    assert_common_fields(data, "analyst")
    assert isinstance(data.get("display_name"), str)
    assert_enum(data, "seniority", Seniority.ALL, "analyst")
    families = data.get("skill_families")
    assert isinstance(families, list) and families, (
        "analyst.skill_families must be a non-empty array"
    )
    for family in families:
        assert family in SignalFamily.ALL, f"unknown skill family {family!r}"
    capacity = data.get("shift_capacity_cases")
    assert isinstance(capacity, int) and capacity >= 1, (
        f"analyst.shift_capacity_cases must be at least 1, got {capacity!r}"
    )
    assert_enum(data, "status", AnalystStatus.ALL, "analyst")
    assert_counter(data, "open_case_count", "analyst")
    assert_counter(data, "resolved_case_count", "analyst")


def assert_new_analyst_defaults(data: Dict[str, Any]) -> None:
    assert_analyst(data)
    assert data["status"] == AnalystStatus.AVAILABLE
    assert data["open_case_count"] == 0
    assert data["resolved_case_count"] == 0
    assert data["version"] == 1


def assert_review_case(data: Dict[str, Any]) -> None:
    assert_common_fields(data, "case")
    assert_uuid_without_prefix(data.get("assessment_id"), "case.assessment_id")
    assert_enum(data, "primary_signal_family", SignalFamily.ALL, "case")
    assert_enum(data, "state", CaseState.ALL, "case")
    assert_two_decimal_places(data.get("priority_score"), "case.priority_score")
    assert_timestamp(data.get("sla_due_at"), "case.sla_due_at")
    assert_counter(data, "requeue_count", "case")
    assert_counter(data, "escalation_count", "case")


def assert_queued_case_defaults(data: Dict[str, Any]) -> None:
    """The case the review branch creates, before anyone staffs it."""
    assert_review_case(data)
    assert data["state"] == CaseState.QUEUED
    for field in (
        "assigned_analyst_id",
        "escalated_by_analyst_id",
        "assigned_at",
        "resolved_at",
        "resolved_late",
        "resolution_note",
    ):
        assert data.get(field) is None, f"case.{field} is null on a freshly queued case"
    assert data["requeue_count"] == 0
    assert data["escalation_count"] == 0


# ---------------------------------------------------------------------------
# Authentication event
# ---------------------------------------------------------------------------


def assert_auth_event(data: Dict[str, Any]) -> None:
    assert_common_fields(data, "auth_event")
    assert_uuid_without_prefix(data.get("customer_id"), "auth_event.customer_id")
    assert_uuid_without_prefix(data.get("device_profile_id"), "auth_event.device_profile_id")
    assert isinstance(data.get("device_first_seen_for_customer"), bool)
    assert_two_decimal_places(data.get("ato_score"), "auth_event.ato_score")
    assert 0.0 <= float(data["ato_score"]) <= 100.00, "ato_score never exceeds 100.00"
    assert_enum(data, "outcome", AuthOutcome.ALL, "auth_event")
    assert_enum(data, "challenge_state", ChallengeState.ALL, "auth_event")
    assert_counter(data, "challenge_attempts", "auth_event")


# ---------------------------------------------------------------------------
# Chargeback
# ---------------------------------------------------------------------------


def assert_chargeback(data: Dict[str, Any]) -> None:
    assert_common_fields(data, "chargeback")
    assert_uuid_without_prefix(data.get("assessment_id"), "chargeback.assessment_id")
    amount = data.get("amount_cents")
    assert isinstance(amount, int) and amount >= 1
    assert isinstance(data.get("liability_shift"), bool)
    assert_timestamp(data.get("received_at"), "chargeback.received_at")
    assert_enum(data, "state", ChargebackState.ALL, "chargeback")
    assert_enum(data, "guarantee_state", GuaranteeState.ALL, "chargeback")
    for field in (
        "guarantee_eligible_cents",
        "guarantee_fee_cents",
        "guarantee_reimbursed_cents",
    ):
        assert_counter(data, field, "chargeback")


def assert_guarantee_denied(data: Dict[str, Any], expected_reason: str) -> None:
    """A DENIED outcome leaves all three guarantee amounts at 0."""
    assert data["guarantee_state"] == GuaranteeState.DENIED
    assert data["guarantee_denial_reason"] == expected_reason, (
        f"guarantee_denial_reason should be {expected_reason}, "
        f"got {data['guarantee_denial_reason']!r}"
    )
    assert data["guarantee_eligible_cents"] == 0
    assert data["guarantee_fee_cents"] == 0
    assert data["guarantee_reimbursed_cents"] == 0


def assert_guarantee_reimbursed(
    data: Dict[str, Any], eligible_cents: int, fee_cents: int, reimbursed_cents: int
) -> None:
    assert data["guarantee_state"] == GuaranteeState.REIMBURSED
    assert data["guarantee_denial_reason"] is None, (
        "a REIMBURSED outcome carries a null guarantee_denial_reason"
    )
    assert data["guarantee_eligible_cents"] == eligible_cents
    assert data["guarantee_fee_cents"] == fee_cents
    assert data["guarantee_reimbursed_cents"] == reimbursed_cents
    assert (
        data["guarantee_reimbursed_cents"]
        == data["guarantee_eligible_cents"] - data["guarantee_fee_cents"]
    ), "the reimbursement is the eligible amount minus the fee"


# ---------------------------------------------------------------------------
# Policy exception
# ---------------------------------------------------------------------------


def assert_policy_exception(data: Dict[str, Any]) -> None:
    assert_common_fields(data, "exception")
    assert_uuid_without_prefix(data.get("customer_id"), "exception.customer_id")
    assert isinstance(data.get("requested_by_analyst_id"), str)
    assert_enum(data, "scope", ExceptionScope.ALL, "exception")
    assert_enum(data, "state", ExceptionState.ALL, "exception")
    ceiling = data.get("max_amount_cents")
    assert isinstance(ceiling, int) and ceiling >= 1
    assert_timestamp(data.get("effective_from"), "exception.effective_from")
    assert_timestamp(data.get("expires_at"), "exception.expires_at")
    assert isinstance(data.get("justification"), str)
    assert_counter(data, "consumed_count", "exception")


def assert_requested_exception_defaults(data: Dict[str, Any]) -> None:
    assert_policy_exception(data)
    assert data["state"] == ExceptionState.REQUESTED
    assert data["consumed_count"] == 0
    assert data["approved_by_analyst_id"] is None
    assert data["decided_at"] is None
    assert data["decision_note"] is None


# ---------------------------------------------------------------------------
# Performance report
# ---------------------------------------------------------------------------


def assert_performance_report(data: Dict[str, Any]) -> None:
    assert_enum(data, "cohort", Cohort.ALL, "report")
    for counter in (
        "denominator_count",
        "approved_count",
        "declined_count",
        "false_positive_count",
        "confirmed_fraud_count",
    ):
        assert_counter(data, counter, "report")
    assert_four_decimal_places(data.get("insult_rate"), "report.insult_rate")
    assert_four_decimal_places(data.get("fraud_capture_rate"), "report.fraud_capture_rate")


# ---------------------------------------------------------------------------
# The two conserved ledgers
# ---------------------------------------------------------------------------


def assert_net_approved_ledger(
    api: Any, customer_id: str, headers: Dict[str, str]
) -> int:
    """Reconcile a customer's ``lifetime_net_approved_cents`` against its definition.

    The ledger must always equal the sum of ``amount_cents`` over that customer's
    assessments that are in state ``DECIDED_APPROVE`` and whose ``outcome_label``
    is not ``FRAUD``.
    """
    customer = validate_success(api.get_customer(customer_id, headers))
    rows, meta = validate_paginated(
        api.list_assessments(
            headers,
            params={
                "customer_id": customer_id,
                "state": AssessmentState.DECIDED_APPROVE,
                "limit": 100,
            },
        )
    )
    assert meta["total_count"] <= 100, (
        "this reconciliation reads a single page; widen it if the fixture grows"
    )
    expected = sum(
        int(row["amount_cents"])
        for row in rows
        if row["outcome_label"] != OutcomeLabel.FRAUD
    )
    assert customer["lifetime_net_approved_cents"] == expected, (
        "lifetime_net_approved_cents must equal the sum of amount_cents over "
        "DECIDED_APPROVE assessments not labelled FRAUD: expected "
        f"{expected}, got {customer['lifetime_net_approved_cents']}"
    )
    return expected


def assert_review_capacity_ledger(
    api: Any, analyst_id: str, headers: Dict[str, str]
) -> int:
    """Reconcile an analyst's ``open_case_count`` against its definition.

    The count must always equal the number of review cases whose
    ``assigned_analyst_id`` is that analyst and whose ``state`` is ``ASSIGNED``.
    """
    analyst = validate_success(api.get_analyst(analyst_id, headers))
    rows, meta = validate_paginated(
        api.list_review_cases(
            headers,
            params={
                "assigned_analyst_id": analyst_id,
                "state": CaseState.ASSIGNED,
                "limit": 100,
            },
        )
    )
    expected = meta["total_count"]
    assert len(rows) == expected, "the reconciliation page must hold every matching row"
    assert analyst["open_case_count"] == expected, (
        "open_case_count must equal the number of ASSIGNED cases held by this "
        f"analyst: expected {expected}, got {analyst['open_case_count']}"
    )
    return expected


# ---------------------------------------------------------------------------
# Ordering helpers
# ---------------------------------------------------------------------------


def assert_review_queue_order(rows: List[Dict[str, Any]]) -> None:
    """The review queue is returned in priority_score descending, created_at ascending."""
    keys = [(-float(row["priority_score"]), row["created_at"]) for row in rows]
    assert keys == sorted(keys), (
        "the review queue must be ordered by priority_score descending and then "
        f"created_at ascending, got {[(r['priority_score'], r['created_at']) for r in rows]}"
    )


def assert_rules_in_evaluation_order(rows: List[Dict[str, Any]]) -> None:
    """A pack's rules are returned in evaluation_order ascending, created_at ascending."""
    keys = [(int(row["evaluation_order"]), row["created_at"]) for row in rows]
    assert keys == sorted(keys), (
        "a pack's rules must be ordered by evaluation_order ascending and then "
        f"created_at ascending, got {keys}"
    )


def assert_created_at_ascending(rows: List[Dict[str, Any]]) -> None:
    stamps = [row["created_at"] for row in rows]
    assert stamps == sorted(stamps), (
        f"list results default to created_at ascending, got {stamps}"
    )


def find_by_id(rows: List[Dict[str, Any]], row_id: str) -> Optional[Dict[str, Any]]:
    for row in rows:
        if row.get("id") == row_id:
            return row
    return None
