"""Shape and invariant checkers for the lead service line domain."""

import math
from typing import Any, Dict, List, Optional, Sequence

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import (
    CONFIDENCE_DECIMALS,
    CONFIDENCE_WEIGHT_BY_SOURCE_TYPE,
    STANDARD_DECIMALS,
    TIER_RANK_BY_SOURCE_TYPE,
)

# ---------------------------------------------------------------------------
# generic field checks
# ---------------------------------------------------------------------------


def assert_common_fields(entity: Dict[str, Any], entity_name: str = "entity") -> None:
    """The identifier, timestamps and version every long lived row carries."""
    assert is_valid_uuid(entity.get("id")), (
        f"{entity_name}.id must be a uuid, got {entity.get('id')!r}"
    )
    assert is_iso8601_timestamp(entity.get("created_at")), (
        f"{entity_name}.created_at must be ISO 8601, got {entity.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(entity.get("updated_at")), (
        f"{entity_name}.updated_at must be ISO 8601, got {entity.get('updated_at')!r}"
    )
    assert isinstance(entity.get("version"), int) and entity["version"] >= 1, (
        f"{entity_name}.version must be a positive integer, got {entity.get('version')!r}"
    )


def assert_append_only_fields(entity: Dict[str, Any], entity_name: str = "entity") -> None:
    """A row that is written once carries an identifier and a creation stamp only."""
    assert is_valid_uuid(entity.get("id")), (
        f"{entity_name}.id must be a uuid, got {entity.get('id')!r}"
    )
    assert is_iso8601_timestamp(entity.get("created_at")), (
        f"{entity_name}.created_at must be ISO 8601, got {entity.get('created_at')!r}"
    )
    assert "version" not in entity, f"{entity_name} must not expose a version field"
    assert "updated_at" not in entity, f"{entity_name} must not expose an updated_at field"


def assert_rounded(value: Any, decimals: int, label: str) -> None:
    """``value`` must be a number carrying no more than ``decimals`` decimals."""
    assert isinstance(value, (int, float)) and not isinstance(value, bool), (
        f"{label} must be numeric, got {value!r}"
    )
    scaled = round(float(value), decimals)
    assert math.isclose(float(value), scaled, rel_tol=0, abs_tol=1e-9), (
        f"{label} must be rounded to {decimals} decimals, got {value!r}"
    )


def assert_two_decimals(value: Any, label: str) -> None:
    """A two decimal metric."""
    assert_rounded(value, STANDARD_DECIMALS, label)


def assert_four_decimals(value: Any, label: str) -> None:
    """A four decimal metric."""
    assert_rounded(value, CONFIDENCE_DECIMALS, label)


def assert_whole_cents(value: Any, label: str) -> None:
    """Money is always an integral number of cents."""
    assert isinstance(value, int) and not isinstance(value, bool), (
        f"{label} must be an integer number of cents, got {value!r}"
    )


def assert_meta_envelope(body: Dict[str, Any]) -> None:
    """Every response carries a request identifier and a request timestamp."""
    meta = body.get("meta")
    assert isinstance(meta, dict), f"meta must be an object, got {meta!r}"
    assert isinstance(meta.get("api_request_id"), str) and meta["api_request_id"], (
        "meta.api_request_id must be a non-empty string"
    )
    assert is_iso8601_timestamp(meta.get("api_request_timestamp")), (
        "meta.api_request_timestamp must be ISO 8601, got "
        f"{meta.get('api_request_timestamp')!r}"
    )


# ---------------------------------------------------------------------------
# per entity shape checks
# ---------------------------------------------------------------------------


def assert_water_system(water_system: Dict[str, Any]) -> None:
    """Shape of a water system row."""
    assert_common_fields(water_system, "WaterSystem")
    for field in (
        "pwsid",
        "system_name",
        "compliance_deadline_date",
        "inventory_status",
        "program_posture",
        "funding_mode",
        "cct_optimization_status",
    ):
        assert isinstance(water_system.get(field), str), (
            f"WaterSystem.{field} must be a string, got {water_system.get(field)!r}"
        )
    assert isinstance(water_system.get("disadvantaged_tract_codes"), list), (
        "WaterSystem.disadvantaged_tract_codes must be a list"
    )
    for field in (
        "baseline_lead_and_grr_count",
        "total_service_line_count",
        "lead_count",
        "grr_count",
        "non_lead_count",
        "unknown_count",
        "outstanding_notification_count",
    ):
        assert isinstance(water_system.get(field), int), (
            f"WaterSystem.{field} must be an integer, got {water_system.get(field)!r}"
        )
    assert_two_decimals(water_system.get("unknown_share_pct"), "WaterSystem.unknown_share_pct")
    assert_classification_partition(water_system)


def assert_service_line(service_line: Dict[str, Any]) -> None:
    """Shape of a service line row."""
    assert_common_fields(service_line, "ServiceLine")
    for field in (
        "water_system_id",
        "address_label",
        "census_tract_code",
        "utility_side_material",
        "customer_side_material",
        "classification",
        "certainty_basis",
        "inventory_state",
        "replacement_state",
    ):
        assert isinstance(service_line.get(field), str), (
            f"ServiceLine.{field} must be a string, got {service_line.get(field)!r}"
        )
    for field in ("serves_sensitive_population", "disadvantaged_status", "consent_barrier_flag"):
        assert isinstance(service_line.get(field), bool), (
            f"ServiceLine.{field} must be a boolean, got {service_line.get(field)!r}"
        )
    assert_two_decimals(service_line.get("certainty_score"), "ServiceLine.certainty_score")
    assert_two_decimals(
        service_line.get("replacement_priority_score"),
        "ServiceLine.replacement_priority_score",
    )
    assert 0.0 <= float(service_line["certainty_score"]) <= 100.0, (
        "ServiceLine.certainty_score must sit between 0 and 100"
    )
    assert 0.0 <= float(service_line["replacement_priority_score"]) <= 100.0, (
        "ServiceLine.replacement_priority_score must sit between 0 and 100"
    )


def assert_evidence_item(evidence: Dict[str, Any]) -> None:
    """Shape of an evidence item row, including its derived tier constants."""
    assert_common_fields(evidence, "EvidenceItem")
    source_type = evidence.get("source_type")
    assert source_type in TIER_RANK_BY_SOURCE_TYPE, (
        f"EvidenceItem.source_type must be a declared source type, got {source_type!r}"
    )
    assert evidence.get("tier_rank") == TIER_RANK_BY_SOURCE_TYPE[source_type], (
        f"EvidenceItem.tier_rank for {source_type} must be "
        f"{TIER_RANK_BY_SOURCE_TYPE[source_type]}, got {evidence.get('tier_rank')!r}"
    )
    expected_weight = CONFIDENCE_WEIGHT_BY_SOURCE_TYPE[source_type]
    assert math.isclose(float(evidence.get("confidence_weight")), expected_weight, abs_tol=1e-9), (
        f"EvidenceItem.confidence_weight for {source_type} must be {expected_weight}, "
        f"got {evidence.get('confidence_weight')!r}"
    )
    assert isinstance(evidence.get("retracted"), bool), "EvidenceItem.retracted must be a boolean"
    assert evidence.get("origin") in ("MANUAL", "APPOINTMENT_CASCADE", "REPLACEMENT_CASCADE"), (
        f"EvidenceItem.origin must be a declared origin, got {evidence.get('origin')!r}"
    )


def assert_verification_crew(crew: Dict[str, Any]) -> None:
    """Shape of a verification crew row."""
    assert_common_fields(crew, "VerificationCrew")
    assert isinstance(crew.get("certified_methods"), list) and crew["certified_methods"], (
        "VerificationCrew.certified_methods must be a non-empty list"
    )
    assert isinstance(crew.get("daily_appointment_capacity"), int), (
        "VerificationCrew.daily_appointment_capacity must be an integer"
    )
    assert crew["daily_appointment_capacity"] >= 1, (
        "VerificationCrew.daily_appointment_capacity must be at least 1"
    )
    assert crew.get("status") in ("ACTIVE", "INACTIVE"), (
        f"VerificationCrew.status must be ACTIVE or INACTIVE, got {crew.get('status')!r}"
    )
    assert isinstance(crew.get("scheduled_appointment_count"), int), (
        "VerificationCrew.scheduled_appointment_count must be an integer"
    )


def assert_verification_appointment(appointment: Dict[str, Any]) -> None:
    """Shape of a verification appointment row."""
    assert_common_fields(appointment, "VerificationAppointment")
    assert appointment.get("state") in (
        "SCHEDULED",
        "ON_SITE",
        "COMPLETED",
        "NO_ACCESS",
        "ABANDONED",
    ), f"VerificationAppointment.state unexpected: {appointment.get('state')!r}"
    assert isinstance(appointment.get("attempt_count"), int), (
        "VerificationAppointment.attempt_count must be an integer"
    )
    assert appointment["attempt_count"] >= 1, (
        "VerificationAppointment.attempt_count starts at 1"
    )
    assert is_iso8601_timestamp(appointment.get("window_start_utc")), (
        "VerificationAppointment.window_start_utc must be ISO 8601"
    )
    assert is_iso8601_timestamp(appointment.get("window_end_utc")), (
        "VerificationAppointment.window_end_utc must be ISO 8601"
    )


def assert_sampling_batch(batch: Dict[str, Any]) -> None:
    """Shape of a sampling batch row."""
    assert_common_fields(batch, "SamplingBatch")
    assert batch.get("state") in ("OPEN", "VALIDATED", "REJECTED"), (
        f"SamplingBatch.state unexpected: {batch.get('state')!r}"
    )
    assert isinstance(batch.get("samples"), list), "SamplingBatch.samples must be a list"
    for field in (
        "stratum_line_count",
        "required_sample_count",
        "valid_sample_count",
        "exceedance_count",
        "reopen_count",
    ):
        assert isinstance(batch.get(field), int), (
            f"SamplingBatch.{field} must be an integer, got {batch.get(field)!r}"
        )
    assert isinstance(batch.get("exceedance"), bool), "SamplingBatch.exceedance must be a boolean"
    if batch.get("classification_confidence") is not None:
        assert_four_decimals(
            batch["classification_confidence"], "SamplingBatch.classification_confidence"
        )
    assert_sample_sequence(batch["samples"])


def assert_sample_sequence(samples: Sequence[Dict[str, Any]]) -> None:
    """Sample sequence numbers start at 1 and increase by one per appended row."""
    for index, sample in enumerate(samples, start=1):
        assert sample.get("sample_seq") == index, (
            f"samples[{index - 1}].sample_seq must be {index}, got {sample.get('sample_seq')!r}"
        )
        assert isinstance(sample.get("invalidated"), bool), (
            "sample.invalidated must be a boolean"
        )


def assert_inventory_publication(publication: Dict[str, Any]) -> None:
    """Shape of an inventory publication row."""
    assert_common_fields(publication, "InventoryPublication")
    assert publication.get("state") in ("DRAFT", "CERTIFIED", "PUBLISHED", "SUPERSEDED"), (
        f"InventoryPublication.state unexpected: {publication.get('state')!r}"
    )
    assert publication.get("basis") in ("RECORDS", "FIELD_VERIFIED"), (
        f"InventoryPublication.basis unexpected: {publication.get('basis')!r}"
    )
    assert isinstance(publication.get("drafted_by_user_id"), str), (
        "InventoryPublication.drafted_by_user_id must be a string"
    )


def assert_customer_notification(notification: Dict[str, Any]) -> None:
    """Shape of a customer notification row."""
    assert_common_fields(notification, "CustomerNotification")
    assert notification.get("state") in ("PENDING", "DELIVERED", "ACKNOWLEDGED", "RETURNED"), (
        f"CustomerNotification.state unexpected: {notification.get('state')!r}"
    )
    assert notification.get("notified_classification") in ("LEAD", "GRR", "UNKNOWN"), (
        "CustomerNotification.notified_classification must be a notifiable classification, "
        f"got {notification.get('notified_classification')!r}"
    )
    assert isinstance(notification.get("overdue"), bool), (
        "CustomerNotification.overdue must be a boolean"
    )
    assert isinstance(notification.get("delivery_attempt_count"), int), (
        "CustomerNotification.delivery_attempt_count must be an integer"
    )
    assert is_iso8601_timestamp(notification.get("due_at")), (
        "CustomerNotification.due_at must be ISO 8601"
    )


def assert_replacement_order(order: Dict[str, Any]) -> None:
    """Shape of a replacement order row, including its two independent axes."""
    assert_common_fields(order, "ReplacementOrder")
    assert order.get("fulfillment_state") in (
        "DRAFT",
        "SCOPED",
        "FUNDED",
        "SCHEDULED",
        "IN_PROGRESS",
        "COMPLETED",
        "CANCELLED",
    ), f"ReplacementOrder.fulfillment_state unexpected: {order.get('fulfillment_state')!r}"
    assert order.get("consent_state") in (
        "NOT_REQUESTED",
        "REQUESTED",
        "GRANTED",
        "DENIED",
        "NO_RESPONSE",
    ), f"ReplacementOrder.consent_state unexpected: {order.get('consent_state')!r}"
    assert order.get("scope") in (None, "FULL", "PARTIAL"), (
        f"ReplacementOrder.scope unexpected: {order.get('scope')!r}"
    )
    assert isinstance(order.get("funding_allocations"), list), (
        "ReplacementOrder.funding_allocations must be a list"
    )
    assert isinstance(order.get("replaced_sides"), list), (
        "ReplacementOrder.replaced_sides must be a list"
    )
    assert_whole_cents(order.get("estimated_cost_cents"), "ReplacementOrder.estimated_cost_cents")
    assert_whole_cents(order.get("allocated_total_cents"), "ReplacementOrder.allocated_total_cents")
    assert_allocation_total(order)


def assert_street_project(project: Dict[str, Any]) -> None:
    """Shape of a street project row."""
    assert_common_fields(project, "StreetProject")
    assert isinstance(project.get("max_concurrent_excavations"), int), (
        "StreetProject.max_concurrent_excavations must be an integer"
    )
    assert project["max_concurrent_excavations"] >= 1, (
        "StreetProject.max_concurrent_excavations must be at least 1"
    )
    assert isinstance(project.get("active_excavation_order_count"), int), (
        "StreetProject.active_excavation_order_count must be an integer"
    )
    assert project["moratorium_end_date"] >= project["moratorium_start_date"], (
        "StreetProject moratorium must not end before it starts"
    )


def assert_funding_source(source: Dict[str, Any]) -> None:
    """Shape of a funding source row, including the ledger identity."""
    assert_common_fields(source, "FundingSource")
    assert source.get("status") in ("ACTIVE", "SUSPENDED", "CLOSED"), (
        f"FundingSource.status unexpected: {source.get('status')!r}"
    )
    for field in (
        "authorized_cents",
        "available_cents",
        "committed_cents",
        "drawn_cents",
        "disadvantaged_committed_cents",
        "equity_shortfall_cents",
    ):
        assert_whole_cents(source.get(field), f"FundingSource.{field}")
    assert_two_decimals(
        source.get("disadvantaged_share_pct"), "FundingSource.disadvantaged_share_pct"
    )
    assert_funding_ledger_identity(source)


def assert_progress_report(report: Dict[str, Any]) -> None:
    """Shape of a progress report row, which carries no version field."""
    assert_append_only_fields(report, "ProgressReport")
    assert report.get("equity_tier") in ("TIER_A", "TIER_B", "TIER_C", "TIER_D"), (
        f"ProgressReport.equity_tier unexpected: {report.get('equity_tier')!r}"
    )
    assert report.get("compliance_status") in ("ON_TRACK", "BEHIND"), (
        f"ProgressReport.compliance_status unexpected: {report.get('compliance_status')!r}"
    )
    for field in (
        "full_replacement_count",
        "partial_replacement_count",
        "disadvantaged_full_count",
        "mandated_annual_credit",
        "deferral_allowance",
        "replaced_count",
        "baseline_denominator",
    ):
        assert isinstance(report.get(field), int), (
            f"ProgressReport.{field} must be an integer, got {report.get(field)!r}"
        )
    for field in (
        "base_credit",
        "disadvantaged_share_pct",
        "total_credit",
        "shortfall_credit",
        "replacement_progress_pct",
    ):
        assert_two_decimals(report.get(field), f"ProgressReport.{field}")


# ---------------------------------------------------------------------------
# domain invariants
# ---------------------------------------------------------------------------


def assert_classification_partition(water_system: Dict[str, Any]) -> None:
    """The four classification buckets partition the line population exactly."""
    total = water_system["total_service_line_count"]
    parts = (
        water_system["lead_count"]
        + water_system["grr_count"]
        + water_system["non_lead_count"]
        + water_system["unknown_count"]
    )
    assert total == parts, (
        "total_service_line_count must equal lead + grr + non_lead + unknown, got "
        f"{total} versus {parts}"
    )


def assert_funding_ledger_identity(source: Dict[str, Any]) -> None:
    """Authorised cents are always fully accounted for."""
    total = source["available_cents"] + source["committed_cents"] + source["drawn_cents"]
    assert source["authorized_cents"] == total, (
        "authorized_cents must equal available + committed + drawn, got "
        f"{source['authorized_cents']} versus {total}"
    )


def assert_allocation_total(order: Dict[str, Any]) -> None:
    """The order total mirrors the sum of its non released allocation rows."""
    live = sum(
        row["allocated_cents"]
        for row in order["funding_allocations"]
        if row.get("state") in ("COMMITTED", "DRAWN")
    )
    assert order["allocated_total_cents"] == live, (
        "allocated_total_cents must equal the sum of COMMITTED and DRAWN allocation rows, "
        f"got {order['allocated_total_cents']} versus {live}"
    )


def assert_unknown_share(water_system: Dict[str, Any]) -> None:
    """The unknown share is the unknown count over the line population."""
    total = water_system["total_service_line_count"]
    if total == 0:
        assert float(water_system["unknown_share_pct"]) == 0.0, (
            "unknown_share_pct must be 0.00 on an empty system"
        )
        return
    expected = round(100.0 * water_system["unknown_count"] / total, STANDARD_DECIMALS)
    assert math.isclose(float(water_system["unknown_share_pct"]), expected, abs_tol=1e-9), (
        f"unknown_share_pct must be {expected}, got {water_system['unknown_share_pct']}"
    )


def assert_allocations_in_state(order: Dict[str, Any], state: str) -> None:
    """Every allocation row of ``order`` sits in ``state``."""
    assert order["funding_allocations"], "expected at least one allocation row"
    for row in order["funding_allocations"]:
        assert row["state"] == state, (
            f"allocation on {row['funding_source_id']} must be {state}, got {row['state']}"
        )


def assert_allocation_rows(
    order: Dict[str, Any], expected: Sequence[Dict[str, Any]]
) -> None:
    """Allocation rows match ``expected`` in order, source and amount."""
    actual = order["funding_allocations"]
    assert len(actual) == len(expected), (
        f"expected {len(expected)} allocation rows, got {len(actual)}: {actual!r}"
    )
    for index, (row, want) in enumerate(zip(actual, expected)):
        for key, value in want.items():
            assert row.get(key) == value, (
                f"allocation[{index}].{key} must be {value!r}, got {row.get(key)!r}"
            )


def assert_no_version_field(payload: Dict[str, Any], label: str = "payload") -> None:
    """A response body that must not carry a version."""
    assert "version" not in payload, f"{label} must not expose a version field"


def assert_error_shape(body: Dict[str, Any]) -> None:
    """The error envelope carries an identifier and a human readable message."""
    assert body.get("response_type") == "error", (
        f"response_type must be 'error', got {body.get('response_type')!r}"
    )
    data = body.get("data")
    assert isinstance(data, dict), "error data must be an object"
    assert isinstance(data.get("error_id"), str) and data["error_id"], (
        "error data.error_id must be a non-empty string"
    )
    assert isinstance(data.get("message"), str) and data["message"].strip(), (
        "error data.message must be a non-empty string"
    )


def assert_list_meta(
    meta: Dict[str, Any],
    total_count: int,
    has_more: bool,
    limit: Optional[int] = None,
    offset: Optional[int] = None,
) -> None:
    """Pagination metadata of a list response."""
    assert meta["total_count"] == total_count, (
        f"meta.total_count must be {total_count}, got {meta['total_count']}"
    )
    assert meta["has_more"] is has_more, (
        f"meta.has_more must be {has_more}, got {meta['has_more']}"
    )
    if limit is not None:
        assert meta["limit"] == limit, f"meta.limit must be {limit}, got {meta['limit']}"
    if offset is not None:
        assert meta["offset"] == offset, f"meta.offset must be {offset}, got {meta['offset']}"


def ids_of(rows: Sequence[Dict[str, Any]]) -> List[str]:
    """The identifiers of a list response, in the order returned."""
    return [row["id"] for row in rows]
