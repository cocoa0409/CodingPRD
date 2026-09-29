"""Domain assertions: entity shape checks and cross-entity invariants."""

import re
from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import (
    CREDENTIAL_TOKEN_HEX_LEN,
    CREDENTIAL_TOKEN_PATTERN,
    CREDENTIAL_TOKEN_PREFIX,
    PARITY_INDEX_DECIMALS,
)
from .types import (
    AuditEventType,
    CellState,
    CoverageBasis,
    DistributionStatus,
    EntitlementModel,
    EntitlementStatus,
    IdentityStatus,
    JobStatus,
    JobType,
    LicenseModel,
    LicenseStatus,
    ParityBasis,
    ParityStatus,
    PublicationType,
    Region,
    ReviewStatus,
    SeatStatus,
    SessionStatus,
    SettlementStatus,
    ShopTier,
    ToolStatus,
)

# ---------------------------------------------------------------------------
# Generic building blocks
# ---------------------------------------------------------------------------


def assert_has_fields(record: Dict[str, Any], fields: List[str], label: str) -> None:
    missing = [field for field in fields if field not in record]
    assert not missing, f"{label} is missing field(s) {missing}: {record}"


def assert_identity_fields(record: Dict[str, Any], label: str) -> None:
    """Every resource carries a UUID id and an ISO-8601 created_at."""
    assert_has_fields(record, ["id", "created_at"], label)
    assert is_valid_uuid(record["id"]), f"{label} id is not a UUID: {record['id']}"
    assert is_iso8601_timestamp(
        record["created_at"]
    ), f"{label} created_at is not ISO-8601: {record['created_at']}"


def assert_mutable_common_fields(record: Dict[str, Any], label: str) -> None:
    """A mutable resource additionally carries updated_at and an integer version."""
    assert_identity_fields(record, label)
    assert_has_fields(record, ["updated_at", "version"], label)
    assert is_iso8601_timestamp(
        record["updated_at"]
    ), f"{label} updated_at is not ISO-8601: {record['updated_at']}"
    assert isinstance(
        record["version"], int
    ), f"{label} version is not an integer: {record['version']!r}"
    assert record["version"] >= 1, f"{label} version must start at 1: {record['version']}"


def assert_immutable_common_fields(record: Dict[str, Any], label: str) -> None:
    """An immutable resource carries only id and created_at — no updated_at, no version."""
    assert_identity_fields(record, label)
    assert "updated_at" not in record, f"{label} must not carry updated_at: {record}"
    assert "version" not in record, f"{label} must not carry a version field: {record}"


def assert_enum_value(value: Any, allowed: List[str], label: str) -> None:
    assert value in allowed, f"{label} is outside its vocabulary {allowed}: {value!r}"


def assert_non_negative_cents(value: Any, label: str) -> None:
    assert isinstance(value, int), f"{label} must be an integer cent amount: {value!r}"
    assert value >= 0, f"{label} must not be negative: {value}"


def assert_decimal_places(value: float, places: int, label: str) -> None:
    """A numeric value carries no more than ``places`` decimal places."""
    assert isinstance(value, (int, float)), f"{label} must be numeric: {value!r}"
    quantised = round(float(value), places)
    assert abs(float(value) - quantised) < 1e-9, (
        f"{label} carries more than {places} decimal places: {value!r}"
    )


# ---------------------------------------------------------------------------
# Per-entity shape checks
# ---------------------------------------------------------------------------


def assert_manufacturer(record: Dict[str, Any]) -> None:
    assert_mutable_common_fields(record, "Manufacturer")
    assert_has_fields(
        record,
        [
            "name",
            "oem_code",
            "region",
            "independent_list_monthly_cents",
            "independent_covered_system_count",
            "oem_dealer_monthly_cents",
            "oem_dealer_covered_system_count",
            "parity_index",
            "parity_status",
        ],
        "Manufacturer",
    )
    assert_enum_value(
        record["region"], [Region.NA, Region.EU, Region.APAC], "Manufacturer.region"
    )
    assert_enum_value(
        record["parity_status"],
        [ParityStatus.COMPLIANT, ParityStatus.NON_COMPLIANT],
        "Manufacturer.parity_status",
    )
    assert_decimal_places(
        record["parity_index"], PARITY_INDEX_DECIMALS, "Manufacturer.parity_index"
    )


def assert_vehicle_model(record: Dict[str, Any]) -> None:
    assert_immutable_common_fields(record, "VehicleModel")
    assert_has_fields(
        record, ["manufacturer_id", "model_code", "model_year"], "VehicleModel"
    )


def assert_system_area(record: Dict[str, Any]) -> None:
    assert_immutable_common_fields(record, "SystemArea")
    assert_has_fields(
        record,
        ["code", "name", "requires_calibration_doc", "requires_security_credential"],
        "SystemArea",
    )
    assert isinstance(record["requires_calibration_doc"], bool)
    assert isinstance(record["requires_security_credential"], bool)


def assert_license(record: Dict[str, Any]) -> None:
    assert_mutable_common_fields(record, "License")
    assert_has_fields(
        record,
        [
            "manufacturer_id",
            "license_model",
            "monthly_fee_cents",
            "per_vehicle_fee_cents",
            "seat_cap",
            "covered_system_area_ids",
            "effective_start",
            "effective_end",
            "status",
            "suspension_reason",
        ],
        "License",
    )
    assert_enum_value(
        record["license_model"],
        [LicenseModel.SUBSCRIPTION, LicenseModel.PER_VEHICLE, LicenseModel.EITHER],
        "License.license_model",
    )
    assert_enum_value(
        record["status"],
        [
            LicenseStatus.DRAFT,
            LicenseStatus.ACTIVE,
            LicenseStatus.SUSPENDED,
            LicenseStatus.TERMINATED,
        ],
        "License.status",
    )
    assert isinstance(record["covered_system_area_ids"], list)


def assert_shop(record: Dict[str, Any]) -> None:
    assert_mutable_common_fields(record, "Shop")
    assert_has_fields(
        record,
        [
            "name",
            "tier",
            "funded_credit_total_cents",
            "data_credit_balance_cents",
            "gateway_fee_accrued_cents",
            "coverage_completeness_pct",
        ],
        "Shop",
    )
    assert_enum_value(
        record["tier"],
        [ShopTier.BASIC, ShopTier.PRO, ShopTier.ENTERPRISE],
        "Shop.tier",
    )
    assert_non_negative_cents(
        record["funded_credit_total_cents"], "Shop.funded_credit_total_cents"
    )
    assert_non_negative_cents(
        record["gateway_fee_accrued_cents"], "Shop.gateway_fee_accrued_cents"
    )


def assert_technician(record: Dict[str, Any]) -> None:
    assert_mutable_common_fields(record, "Technician")
    assert_has_fields(
        record,
        [
            "shop_id",
            "full_name",
            "identity_status",
            "credential_expires_at",
            "identity_document_ref",
            "verified_by_user_id",
        ],
        "Technician",
    )
    assert_enum_value(
        record["identity_status"],
        [
            IdentityStatus.UNVERIFIED,
            IdentityStatus.VERIFIED,
            IdentityStatus.SUSPENDED,
            IdentityStatus.REVOKED,
        ],
        "Technician.identity_status",
    )


def assert_entitlement(record: Dict[str, Any]) -> None:
    assert_mutable_common_fields(record, "ShopEntitlement")
    assert_has_fields(
        record,
        [
            "shop_id",
            "license_id",
            "entitlement_model",
            "seats_total",
            "window_start",
            "window_end",
            "status",
            "charged_cents",
            "settled_cents",
            "settlement_status",
            "seats_assigned",
            "seats_available",
        ],
        "ShopEntitlement",
    )
    assert_enum_value(
        record["entitlement_model"],
        [EntitlementModel.SUBSCRIPTION, EntitlementModel.PER_VEHICLE],
        "ShopEntitlement.entitlement_model",
    )
    assert_enum_value(
        record["status"],
        [
            EntitlementStatus.PENDING,
            EntitlementStatus.ACTIVE,
            EntitlementStatus.LAPSED,
            EntitlementStatus.CANCELLED,
        ],
        "ShopEntitlement.status",
    )
    assert_enum_value(
        record["settlement_status"],
        [SettlementStatus.UNSETTLED, SettlementStatus.SETTLED],
        "ShopEntitlement.settlement_status",
    )
    assert_seat_ledger_consistent(record)


def assert_seat_assignment(record: Dict[str, Any]) -> None:
    assert_mutable_common_fields(record, "SeatAssignment")
    assert_has_fields(
        record,
        ["entitlement_id", "technician_id", "status", "revocation_reason"],
        "SeatAssignment",
    )
    assert_enum_value(
        record["status"],
        [SeatStatus.ACTIVE, SeatStatus.REVOKED, SeatStatus.SUPERSEDED],
        "SeatAssignment.status",
    )


def assert_diagnostic_tool(record: Dict[str, Any]) -> None:
    assert_mutable_common_fields(record, "DiagnosticTool")
    assert_has_fields(
        record,
        [
            "shop_id",
            "serial_no",
            "oem_attestation_expires_at",
            "status",
            "occupied_by_session_id",
        ],
        "DiagnosticTool",
    )
    assert_enum_value(
        record["status"], [ToolStatus.IDLE, ToolStatus.OCCUPIED], "DiagnosticTool.status"
    )
    if record["status"] == ToolStatus.IDLE:
        assert record["occupied_by_session_id"] is None, (
            "An idle tool must not name an occupying session: "
            f"{record['occupied_by_session_id']}"
        )
    else:
        assert record["occupied_by_session_id"] is not None, (
            "An occupied tool must name the session holding it"
        )


def assert_publication(record: Dict[str, Any]) -> None:
    assert_mutable_common_fields(record, "Publication")
    assert_has_fields(
        record,
        [
            "vehicle_model_id",
            "system_area_id",
            "publication_type",
            "current_version_no",
            "published_version_id",
        ],
        "Publication",
    )
    assert_enum_value(
        record["publication_type"],
        [
            PublicationType.REPAIR_PROCEDURE,
            PublicationType.TSB,
            PublicationType.CALIBRATION_DOC,
        ],
        "Publication.publication_type",
    )


def assert_publication_version(record: Dict[str, Any]) -> None:
    assert_mutable_common_fields(record, "PublicationVersion")
    assert_has_fields(
        record,
        [
            "publication_id",
            "version_no",
            "source_tsb_ref",
            "calibration_procedure_ref",
            "review_status",
            "distribution_status",
            "validated_by_user_id",
            "published_by_user_id",
            "active_pin_count",
        ],
        "PublicationVersion",
    )
    assert_enum_value(
        record["review_status"],
        [ReviewStatus.DRAFT, ReviewStatus.VALIDATED],
        "PublicationVersion.review_status",
    )
    assert_enum_value(
        record["distribution_status"],
        [
            DistributionStatus.WITHHELD,
            DistributionStatus.PUBLISHED,
            DistributionStatus.SUPERSEDED,
            DistributionStatus.RECALLED,
        ],
        "PublicationVersion.distribution_status",
    )
    assert record["active_pin_count"] >= 0


def assert_gateway_session(record: Dict[str, Any]) -> None:
    assert_mutable_common_fields(record, "GatewaySession")
    assert_has_fields(
        record,
        [
            "seat_assignment_id",
            "diagnostic_tool_id",
            "vin",
            "window_start",
            "window_end",
            "status",
            "credential_token",
            "base_subtotal_cents",
            "discount_cents",
            "surcharge_cents",
            "total_access_fee_cents",
            "termination_reason",
        ],
        "GatewaySession",
    )
    assert_enum_value(
        record["status"],
        [
            SessionStatus.REQUESTED,
            SessionStatus.ACTIVE,
            SessionStatus.COMPLETED,
            SessionStatus.EXPIRED,
            SessionStatus.TERMINATED,
        ],
        "GatewaySession.status",
    )


def assert_programming_job(record: Dict[str, Any]) -> None:
    assert_mutable_common_fields(record, "ModuleProgrammingJob")
    assert_has_fields(
        record,
        [
            "session_id",
            "job_type",
            "pinned_publication_version_id",
            "status",
            "repin_count",
            "abort_reason",
        ],
        "ModuleProgrammingJob",
    )
    assert_enum_value(
        record["job_type"],
        [JobType.IMMOBILIZER_KEY, JobType.MODULE_FLASH, JobType.ADAS_CALIBRATION],
        "ModuleProgrammingJob.job_type",
    )
    assert_enum_value(
        record["status"],
        [
            JobStatus.QUEUED,
            JobStatus.IN_PROGRESS,
            JobStatus.REVALIDATION_REQUIRED,
            JobStatus.COMPLETED,
            JobStatus.ABORTED,
        ],
        "ModuleProgrammingJob.status",
    )


def assert_audit_event(record: Dict[str, Any]) -> None:
    assert_immutable_common_fields(record, "AuditEvent")
    assert_has_fields(
        record,
        [
            "actor_role",
            "actor_user_id",
            "subject_entity",
            "subject_id",
            "event_type",
            "detail",
            "occurred_at",
        ],
        "AuditEvent",
    )
    assert_enum_value(
        record["event_type"], AuditEventType.ALL, "AuditEvent.event_type"
    )


def assert_parity_report(record: Dict[str, Any]) -> None:
    assert_has_fields(
        record,
        [
            "manufacturer_id",
            "basis",
            "parity_index",
            "parity_status",
            "independent_effective_cents_per_system_day",
            "oem_effective_cents_per_system_day",
            "threshold",
        ],
        "ParityReport",
    )
    assert_enum_value(
        record["basis"],
        [ParityBasis.LIST_BASIS, ParityBasis.EFFECTIVE_BASIS],
        "ParityReport.basis",
    )
    assert_enum_value(
        record["parity_status"],
        [ParityStatus.COMPLIANT, ParityStatus.NON_COMPLIANT],
        "ParityReport.parity_status",
    )
    assert_decimal_places(
        record["parity_index"], PARITY_INDEX_DECIMALS, "ParityReport.parity_index"
    )


def assert_coverage_map(record: Dict[str, Any]) -> None:
    assert_has_fields(
        record,
        [
            "shop_id",
            "basis",
            "total_cells",
            "covered_cells",
            "degraded_cells",
            "gap_cells",
            "completeness_pct",
            "gaps",
        ],
        "CoverageMap",
    )
    assert_enum_value(
        record["basis"],
        [CoverageBasis.EFFECTIVE, CoverageBasis.DECLARED],
        "CoverageMap.basis",
    )
    assert isinstance(record["gaps"], list)
    assert_coverage_partition(record)


# ---------------------------------------------------------------------------
# Cross-entity invariants
# ---------------------------------------------------------------------------


def assert_seat_ledger_consistent(entitlement: Dict[str, Any]) -> None:
    """Seats total always equals seats assigned plus seats available."""
    total = entitlement["seats_total"]
    assigned = entitlement["seats_assigned"]
    available = entitlement["seats_available"]
    assert total == assigned + available, (
        "Seat ledger does not balance: "
        f"seats_total={total} but seats_assigned={assigned} + seats_available={available}"
    )


def assert_seat_counts(
    entitlement: Dict[str, Any], assigned: int, available: int
) -> None:
    assert entitlement["seats_assigned"] == assigned, (
        f"Expected seats_assigned={assigned}, got {entitlement['seats_assigned']}"
    )
    assert entitlement["seats_available"] == available, (
        f"Expected seats_available={available}, got {entitlement['seats_available']}"
    )
    assert_seat_ledger_consistent(entitlement)


def assert_data_credit_conservation(shop: Dict[str, Any], *entitlements: Dict[str, Any]) -> None:
    """Balance plus outstanding charges minus settled amounts equals funding.

    Outstanding exposure of an entitlement is its charged amount while it is
    unsettled and the settled amount once it has been settled, so the sum of the
    balance and the outstanding exposure of every entitlement of the shop must
    always come back to the total funding the shop has received.
    """
    outstanding = 0
    for entitlement in entitlements:
        if entitlement["settlement_status"] == SettlementStatus.SETTLED:
            outstanding += entitlement["settled_cents"]
        else:
            outstanding += entitlement["charged_cents"]
    total = shop["data_credit_balance_cents"] + outstanding
    assert total == shop["funded_credit_total_cents"], (
        "Data credit is not conserved: balance "
        f"{shop['data_credit_balance_cents']} + outstanding {outstanding} = {total}, "
        f"but funded total is {shop['funded_credit_total_cents']}"
    )


def assert_coverage_partition(coverage_map: Dict[str, Any]) -> None:
    """Covered, degraded and gap cells partition the cell universe."""
    parts = (
        coverage_map["covered_cells"]
        + coverage_map["degraded_cells"]
        + coverage_map["gap_cells"]
    )
    assert parts == coverage_map["total_cells"], (
        "Cell states do not partition the universe: covered "
        f"{coverage_map['covered_cells']} + degraded {coverage_map['degraded_cells']} + "
        f"gap {coverage_map['gap_cells']} = {parts}, "
        f"but total_cells is {coverage_map['total_cells']}"
    )
    non_covered = coverage_map["degraded_cells"] + coverage_map["gap_cells"]
    assert len(coverage_map["gaps"]) == non_covered, (
        f"gaps array holds {len(coverage_map['gaps'])} entries but there are "
        f"{non_covered} non-covered cells"
    )
    for gap in coverage_map["gaps"]:
        assert_enum_value(
            gap["cell_state"], [CellState.DEGRADED, CellState.GAP], "gap cell_state"
        )


def assert_gaps_sorted(gaps: List[Dict[str, Any]]) -> None:
    """Gap entries run in ascending model code, then ascending system-area code."""
    keys = [(gap["model_code"], gap["system_area_code"]) for gap in gaps]
    assert keys == sorted(keys), f"gaps are not ordered by model code then area code: {keys}"


def assert_credential_token_derived_from_session(session: Dict[str, Any]) -> None:
    """The token is 'GW-' followed by the first eight hex characters of the session id, upper-cased."""
    token = session["credential_token"]
    assert token is not None, "An active session must carry a credential token"
    assert re.match(CREDENTIAL_TOKEN_PATTERN, token), (
        f"credential_token is not of the form GW-XXXXXXXX: {token!r}"
    )
    hex_chars = [char for char in session["id"] if char in "0123456789abcdefABCDEF"]
    expected_suffix = "".join(hex_chars[:CREDENTIAL_TOKEN_HEX_LEN]).upper()
    assert token == CREDENTIAL_TOKEN_PREFIX + expected_suffix, (
        f"credential_token {token!r} is not derived from session id {session['id']!r}; "
        f"expected {CREDENTIAL_TOKEN_PREFIX + expected_suffix!r}"
    )


def assert_gateway_fee_breakdown(
    session: Dict[str, Any],
    base_subtotal_cents: int,
    discount_cents: int,
    surcharge_cents: int,
    total_access_fee_cents: int,
) -> None:
    """The four fee components carry the expected values and add up."""
    assert session["base_subtotal_cents"] == base_subtotal_cents, (
        f"base_subtotal_cents expected {base_subtotal_cents}, "
        f"got {session['base_subtotal_cents']}"
    )
    assert session["discount_cents"] == discount_cents, (
        f"discount_cents expected {discount_cents}, got {session['discount_cents']}"
    )
    assert session["surcharge_cents"] == surcharge_cents, (
        f"surcharge_cents expected {surcharge_cents}, got {session['surcharge_cents']}"
    )
    assert session["total_access_fee_cents"] == total_access_fee_cents, (
        f"total_access_fee_cents expected {total_access_fee_cents}, "
        f"got {session['total_access_fee_cents']}"
    )
    assert (
        base_subtotal_cents - discount_cents + surcharge_cents == total_access_fee_cents
    ), "The stated components do not add up to the stated total"


def find_audit_events(
    events: List[Dict[str, Any]],
    event_type: Optional[str] = None,
    subject_id: Optional[str] = None,
    subject_entity: Optional[str] = None,
) -> List[Dict[str, Any]]:
    matched = events
    if event_type is not None:
        matched = [event for event in matched if event["event_type"] == event_type]
    if subject_id is not None:
        matched = [event for event in matched if event["subject_id"] == subject_id]
    if subject_entity is not None:
        matched = [
            event for event in matched if event["subject_entity"] == subject_entity
        ]
    return matched


def assert_single_audit_event(
    events: List[Dict[str, Any]],
    event_type: str,
    subject_id: Optional[str] = None,
    detail: Optional[str] = None,
) -> Dict[str, Any]:
    """Exactly one trail row of the given type exists for the subject; return it."""
    matched = find_audit_events(events, event_type=event_type, subject_id=subject_id)
    assert len(matched) == 1, (
        f"Expected exactly one {event_type} row for subject {subject_id}, "
        f"found {len(matched)}: {matched}"
    )
    event = matched[0]
    assert_audit_event(event)
    if detail is not None:
        assert event["detail"] == detail, (
            f"{event_type} detail expected {detail!r}, got {event['detail']!r}"
        )
    return event


def assert_no_audit_event(
    events: List[Dict[str, Any]], event_type: str, subject_id: Optional[str] = None
) -> None:
    matched = find_audit_events(events, event_type=event_type, subject_id=subject_id)
    assert not matched, (
        f"Expected no {event_type} row for subject {subject_id}, found {matched}"
    )


def assert_audit_ascending(events: List[Dict[str, Any]]) -> None:
    """Trail rows read in ascending occurrence order with created_at breaking ties."""
    keys = [(event["occurred_at"], event["created_at"]) for event in events]
    assert keys == sorted(keys), f"audit rows are not in ascending order: {keys}"
