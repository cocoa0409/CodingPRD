"""Entity assertions and domain invariant checkers.

Every one of the twelve resource types carries ``id``, ``created_at``,
``updated_at`` and ``version`` (PRD §2.4), so ``assert_common_fields`` applies
to all of them.
"""
from typing import Any, Dict

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)

from .types import (
    AgreementStatus,
    ApplicationStatus,
    AuditStatus,
    BatchStatus,
    DairyStatus,
    DeliveryStatus,
    DistributionPosture,
    GasState,
    InterconnectStatus,
    NominationStatus,
    OpsDayStatus,
    OpsPosture,
    PathwayStatus,
    StatementStatus,
)


def _members(enum_cls) -> list:
    return [member.value for member in enum_cls]


def assert_common_fields(data: Dict[str, Any], label: str = "entity") -> None:
    """id, created_at, updated_at and version on every resource type."""
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be an opaque UUID"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"{label}.created_at must be an ISO 8601 timestamp"
    assert is_iso8601_timestamp(
        data.get("updated_at", "")
    ), f"{label}.updated_at must be an ISO 8601 timestamp"
    assert isinstance(data.get("version"), int), f"{label}.version must be an integer"
    assert data["version"] >= 1, f"{label}.version starts at 1, got {data['version']}"


def assert_dairy(data: Dict[str, Any]) -> None:
    assert_common_fields(data, "Dairy")
    assert data["status"] in _members(DairyStatus), f"unexpected dairy status {data['status']}"
    assert isinstance(data["active_agreement_count"], int)
    assert isinstance(data["contracted_agreement_count"], int)
    assert data["active_agreement_count"] >= 0
    assert data["contracted_agreement_count"] >= 0
    assert data["pan_applied_ytd_kg"] >= 0


def assert_facility(data: Dict[str, Any]) -> None:
    assert_common_fields(data, "DigesterFacility")
    assert data["ops_posture"] in _members(OpsPosture)
    assert data["distribution_posture"] in _members(DistributionPosture)
    assert isinstance(data["posture_override_active"], bool)
    assert data["reserve_balance_cents"] >= 0
    assert data["reserve_balance_cents"] <= data["reserve_target_cents"], (
        "reserve balance may never exceed the reserve target"
    )


def assert_agreement(data: Dict[str, Any]) -> None:
    assert_common_fields(data, "FeedstockAgreement")
    assert data["status"] in _members(AgreementStatus)
    assert isinstance(data["negotiation_round"], int)
    assert 0 <= data["negotiation_round"] <= 3


def assert_delivery(data: Dict[str, Any]) -> None:
    assert_common_fields(data, "FeedstockDelivery")
    assert data["status"] in _members(DeliveryStatus)


def assert_ops_day(data: Dict[str, Any]) -> None:
    assert_common_fields(data, "OperationsDay")
    assert data["status"] in _members(OpsDayStatus)
    assert data["gas_state"] in _members(GasState)
    assert isinstance(data["separation_recorded"], bool)
    assert isinstance(data["conditioning_attempts"], int)
    assert isinstance(data["reopen_count"], int)


def assert_interconnect(data: Dict[str, Any]) -> None:
    assert_common_fields(data, "InterconnectAgreement")
    assert data["status"] in _members(InterconnectStatus)
    assert isinstance(data["curtailment_count"], int)
    assert data["curtailment_count"] >= 0


def assert_nomination(data: Dict[str, Any]) -> None:
    assert_common_fields(data, "InjectionNomination")
    assert data["status"] in _members(NominationStatus)
    assert isinstance(data["window_minutes"], int)
    assert data["window_minutes"] > 0


def assert_pathway(data: Dict[str, Any]) -> None:
    assert_common_fields(data, "CreditPathway")
    assert data["status"] in _members(PathwayStatus)
    assert_credit_control_holds(data)


def assert_batch(data: Dict[str, Any]) -> None:
    assert_common_fields(data, "CreditBatch")
    assert data["status"] in _members(BatchStatus)


def assert_audit(data: Dict[str, Any]) -> None:
    assert_common_fields(data, "VerificationAudit")
    assert data["status"] in _members(AuditStatus)
    assert isinstance(data["remediation_round"], int)
    assert 0 <= data["remediation_round"] <= 2


def assert_nutrient_application(data: Dict[str, Any]) -> None:
    assert_common_fields(data, "NutrientApplication")
    assert data["status"] in _members(ApplicationStatus)


def assert_statement(data: Dict[str, Any]) -> None:
    assert_common_fields(data, "RevenueStatement")
    assert data["status"] in _members(StatementStatus)
    assert isinstance(data["share_lines"], list)


# ---------------------------------------------------------------------------
# Conserved quantities (PRD §2.8)
# ---------------------------------------------------------------------------


def assert_mass_control_holds(facility: Dict[str, Any]) -> None:
    """mass_control_residual_tonnes must always equal exactly 0.000."""
    residual = facility["mass_control_residual_tonnes"]
    assert residual == 0.000, (
        "mass_control_residual_tonnes must always equal exactly 0.000, "
        f"got {residual}"
    )
    expected = round(
        facility["total_manure_received_tonnes"]
        - facility["unseparated_manure_tonnes"]
        - facility["digestate_solids_produced_tonnes"]
        - facility["digestate_liquid_produced_tonnes"],
        3,
    )
    assert expected == 0.000, (
        "received minus unseparated minus solids produced minus liquid produced "
        f"must be 0.000, got {expected}"
    )


def assert_credit_control_holds(pathway: Dict[str, Any]) -> None:
    """credit_control_residual must always equal exactly 0.000."""
    residual = pathway["credit_control_residual"]
    assert residual == 0.000, (
        f"credit_control_residual must always equal exactly 0.000, got {residual}"
    )
    expected = round(
        pathway["credits_issued_total"]
        - pathway["credits_reversed_total"]
        - pathway["credits_outstanding"],
        3,
    )
    assert expected == 0.000, (
        "issued minus reversed minus outstanding must be 0.000, "
        f"got {expected}"
    )


# ---------------------------------------------------------------------------
# Rounding-scale helpers (PRD §2.5)
# ---------------------------------------------------------------------------


def assert_decimal_places(value: float, places: int, label: str = "value") -> None:
    assert value == round(value, places), (
        f"{label} must carry no more than {places} decimal places, got {value}"
    )
