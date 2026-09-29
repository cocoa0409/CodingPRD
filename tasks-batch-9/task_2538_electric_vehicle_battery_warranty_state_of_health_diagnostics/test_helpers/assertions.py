"""Per-resource shape assertions and domain invariant checkers.

Every helper here asserts something the PRD states about a response body: the
common-field quartet, the numeric precision rules, the settlement waterfall
identity, the compliance-score formula, the two non-default list orderings.
Tests use them so that a shape regression is caught once, centrally, rather than
being silently tolerated by twenty hand-written dictionary lookups.
"""

from datetime import datetime, timezone
from decimal import Decimal
from typing import List, Optional

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import (
    COMPLIANCE_SCORE_BASE,
    COMPLIANCE_PENALTY_PER_LATE_NOTIFICATION,
    COMPLIANCE_PENALTY_PER_REJECTION,
    admin_fee_for_oem_share,
)


# ═══════════════════════════ common fields ═══════════════════════════


def assert_common_fields(obj: dict, label: str = "record") -> None:
    """Every resource but the snapshot carries id, created_at, updated_at, version."""
    assert is_valid_uuid(obj.get("id", "")), f"{label}.id must be a UUID, got {obj.get('id')!r}"
    assert is_iso8601_timestamp(obj.get("created_at", "")), (
        f"{label}.created_at must be an ISO-8601 timestamp, got {obj.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(obj.get("updated_at", "")), (
        f"{label}.updated_at must be an ISO-8601 timestamp, got {obj.get('updated_at')!r}"
    )
    assert isinstance(obj.get("version"), int), f"{label}.version must be an integer"
    assert obj["version"] >= 1, f"{label}.version starts at 1, got {obj['version']}"


def assert_event_fields(obj: dict, label: str = "event") -> None:
    """The append-only snapshot row carries id and created_at and nothing else of the quartet."""
    assert is_valid_uuid(obj.get("id", "")), f"{label}.id must be a UUID"
    assert is_iso8601_timestamp(obj.get("created_at", "")), (
        f"{label}.created_at must be an ISO-8601 timestamp"
    )
    assert "version" not in obj, f"{label} is immutable and must carry no version field"
    assert "updated_at" not in obj, f"{label} is immutable and must carry no updated_at field"


# ═══════════════════════════ numeric precision ═══════════════════════════


def assert_integer_cents(value, label: str = "amount") -> None:
    """Every monetary amount is an integer count of cents."""
    assert isinstance(value, int) and not isinstance(value, bool), (
        f"{label} must be an integer number of cents, got {value!r}"
    )


def assert_decimal_places(value, places: int, label: str) -> None:
    """Assert a numeric field carries no more than `places` decimal places."""
    assert value is not None, f"{label} must not be null"
    exponent = Decimal(str(value)).normalize().as_tuple().exponent
    actual = -exponent if isinstance(exponent, int) and exponent < 0 else 0
    assert actual <= places, (
        f"{label} must carry at most {places} decimal places, got {value!r}"
    )


def assert_capacity_precision(value, label: str = "capacity") -> None:
    """Capacities and weights are carried to three decimal places."""
    assert_decimal_places(value, 3, label)


def assert_percentage_precision(value, label: str = "percentage") -> None:
    """Percentages are carried to two decimal places."""
    assert_decimal_places(value, 2, label)


def assert_proration_precision(value, label: str = "proration_factor") -> None:
    """The proration factor is carried to four decimal places."""
    assert_decimal_places(value, 4, label)


# ═══════════════════════════ error envelope ═══════════════════════════


def assert_error_envelope(response) -> dict:
    """An error body carries exactly an error_id and a message under data."""
    body = response.json()
    assert body.get("response_type") == "error", (
        f"expected response_type 'error', got {body.get('response_type')!r}"
    )
    assert "meta" in body, "an error envelope still carries meta"
    meta = body["meta"]
    assert isinstance(meta.get("api_request_id"), str) and meta["api_request_id"].startswith("req_"), (
        f"meta.api_request_id must be a string beginning 'req_', got {meta.get('api_request_id')!r}"
    )
    data = body["data"]
    assert set(data.keys()) >= {"error_id", "message"}, (
        f"error data must carry error_id and message, got {sorted(data.keys())}"
    )
    assert isinstance(data["error_id"], str) and data["error_id"].startswith("ERR_")
    assert isinstance(data["message"], str) and data["message"].strip()
    return data


# ═══════════════════════════ per-resource shapes ═══════════════════════════


def assert_warranty_program(program: dict) -> None:
    assert_common_fields(program, "warranty_program")
    assert isinstance(program["retention_schedule"], list) and program["retention_schedule"]
    assert_integer_cents(program["accrued_liability_cents"], "accrued_liability_cents")
    assert isinstance(program["reman_available_count"], int)
    assert program["reman_stock_state"] in ("AVAILABLE", "DEPLETED")
    # The stock mirror and its state word must agree.
    if program["reman_available_count"] == 0:
        assert program["reman_stock_state"] == "DEPLETED", (
            "reman_stock_state must read DEPLETED while reman_available_count is zero"
        )
    else:
        assert program["reman_stock_state"] == "AVAILABLE", (
            "reman_stock_state must read AVAILABLE while a remanufactured pack is in stock"
        )


def assert_retention_schedule_ascending(program: dict) -> None:
    """Rows are persisted sorted ascending by through_months."""
    months = [row["through_months"] for row in program["retention_schedule"]]
    assert months == sorted(months), (
        f"retention_schedule must be stored ascending by through_months, got {months}"
    )
    last = program["retention_schedule"][-1]
    assert last["through_months"] == program["coverage_months"], (
        "the last tier's through_months must equal coverage_months"
    )
    assert last["through_miles"] == program["coverage_miles"], (
        "the last tier's through_miles must equal coverage_miles"
    )


def assert_vehicle(vehicle: dict) -> None:
    assert_common_fields(vehicle, "vehicle")
    assert vehicle["status"] in ("ACTIVE", "IMMOBILIZED")
    assert isinstance(vehicle["odometer_miles"], int)
    assert isinstance(vehicle["warranty_hold"], bool)


def assert_battery_pack(pack: dict) -> None:
    assert_common_fields(pack, "battery_pack")
    assert pack["status"] in (
        "STOCK",
        "RESERVED",
        "IN_SERVICE",
        "REMOVED",
        "QUARANTINED",
        "SCRAPPED",
    )
    assert pack["pack_type"] in ("NEW", "REMANUFACTURED")
    assert_capacity_precision(pack["nominal_capacity_kwh"], "pack.nominal_capacity_kwh")
    assert_capacity_precision(pack["gross_weight_kg"], "pack.gross_weight_kg")
    assert isinstance(pack["damaged_defective"], bool)
    assert isinstance(pack["faulted_module_count"], int)
    assert isinstance(pack["module_replacements_to_date"], int)


def assert_battery_module(module: dict) -> None:
    assert_common_fields(module, "battery_module")
    assert module["status"] in ("HEALTHY", "DEGRADED", "FAULTED", "REPLACED")
    assert isinstance(module["position_index"], int) and module["position_index"] >= 1
    assert_capacity_precision(module["module_capacity_kwh"], "module.module_capacity_kwh")
    assert isinstance(module["thermal_runaway_flag"], bool)


def assert_telematics_snapshot(snapshot: dict) -> None:
    assert_event_fields(snapshot, "telematics_snapshot")
    assert snapshot["validity_flag"] in (
        "VALID",
        "INVALID_FUTURE_CAPTURE",
        "INVALID_CAPACITY_RANGE",
        "INVALID_ODOMETER_REGRESSION",
    )
    assert_capacity_precision(
        snapshot["corrected_capacity_kwh"], "snapshot.corrected_capacity_kwh"
    )


def assert_soh_assessment(assessment: dict) -> None:
    assert_common_fields(assessment, "soh_assessment")
    assert assessment["variant"] in ("TELEMATICS_FLEET", "BENCH_CAPACITY_TEST")
    assert assessment["diagnostic_validity"] in (
        "VALID",
        "STALE_TELEMETRY",
        "INSUFFICIENT_DATA",
        "BENCH_OUT_OF_RANGE",
    )
    assert assessment["coverage_position"] in (
        "IN_COVERAGE",
        "GOODWILL_BAND",
        "OUT_OF_COVERAGE",
    )
    assert isinstance(assessment["qualifies_for_claim"], bool)
    assert isinstance(assessment["superseded"], bool)
    assert isinstance(assessment["window_snapshot_count"], int)
    if assessment["retention_pct"] is not None:
        assert_percentage_precision(assessment["retention_pct"], "assessment.retention_pct")


def assert_service_center(center: dict) -> None:
    assert_common_fields(center, "service_center")
    assert center["status"] in ("ACTIVE", "SHIPPING_SUSPENDED", "DECERTIFIED")
    assert center["hv_certification_level"] in ("L1", "L2", "L3")
    assert isinstance(center["has_pack_lift"], bool)
    assert isinstance(center["hv_bay_count"], int)
    assert_integer_cents(center["labor_rate_cents_per_hour"], "labor_rate_cents_per_hour")
    assert_compliance_score_formula(center)


def assert_compliance_score_formula(center: dict) -> None:
    """100 minus 15 per rejected shipment minus 40 per late notification, floored at 0."""
    expected = max(
        0,
        COMPLIANCE_SCORE_BASE
        - COMPLIANCE_PENALTY_PER_REJECTION * center["rejected_shipment_count"]
        - COMPLIANCE_PENALTY_PER_LATE_NOTIFICATION * center["late_notification_count"],
    )
    assert center["compliance_score"] == expected, (
        f"compliance_score must be {expected} for "
        f"{center['rejected_shipment_count']} rejected shipments and "
        f"{center['late_notification_count']} late notifications, "
        f"got {center['compliance_score']}"
    )


def assert_technician(technician: dict) -> None:
    assert_common_fields(technician, "technician")
    assert technician["hv_cert_level"] in ("L1", "L2", "L3")
    assert technician["status"] in ("ACTIVE", "CERT_LAPSED")


def assert_warranty_claim(claim: dict) -> None:
    assert_common_fields(claim, "warranty_claim")
    assert claim["adjudication_status"] in (
        "SUBMITTED",
        "INFO_REQUESTED",
        "APPROVED_MODULE",
        "APPROVED_PACK",
        "APPROVED_SOFTWARE",
        "DENIED",
        "FULFILLED",
        "CLOSED",
    )
    assert claim["recommended_remedy"] in (
        "MODULE_REPLACEMENT",
        "PACK_REPLACEMENT",
        "SOFTWARE_REMEDIATION",
    )
    assert claim["recommendation_basis"] in (
        "THERMAL_HISTORY",
        "CELL_DELTA",
        "RETENTION_FLOOR",
        "MODULE_ALLOWANCE",
        "MODULE_FAULT",
        "NO_MODULE_FAULT",
    )
    assert isinstance(claim["info_request_round"], int)
    assert isinstance(claim["reopened_count"], int)
    assert isinstance(claim["fulfilment_blocked"], bool)
    assert isinstance(claim["pack_shipment_required"], bool)


def assert_settlement_waterfall(claim: dict) -> None:
    """The four settlement identities the PRD states, checked together.

    The owner and OEM shares partition the remedy cost exactly; the
    administrative fee is keyed on the OEM share rather than on the remedy cost;
    and the OEM total is the OEM share plus that fee.
    """
    remedy = claim["remedy_cost_cents"]
    owner = claim["owner_share_cents"]
    oem = claim["oem_share_cents"]
    admin = claim["admin_fee_cents"]
    total = claim["oem_total_cents"]
    for label, value in (
        ("remedy_cost_cents", remedy),
        ("owner_share_cents", owner),
        ("oem_share_cents", oem),
        ("admin_fee_cents", admin),
        ("oem_total_cents", total),
    ):
        assert_integer_cents(value, label)
    assert owner + oem == remedy, (
        f"owner_share_cents {owner} plus oem_share_cents {oem} must equal "
        f"remedy_cost_cents {remedy}"
    )
    assert admin == admin_fee_for_oem_share(oem), (
        f"admin_fee_cents must be tiered on the OEM share {oem}, got {admin}"
    )
    assert total == oem + admin, (
        f"oem_total_cents must be oem_share_cents {oem} plus admin_fee_cents "
        f"{admin}, got {total}"
    )
    assert_proration_precision(claim["proration_factor"], "claim.proration_factor")


def assert_denied_claim_zeroed(claim: dict) -> None:
    """A denial carries no money at all and names its reason."""
    assert claim["adjudication_status"] == "DENIED"
    # No PRD sentence states what `approved_remedy` reads once a claim is denied --
    # neither the adjudicator's own denial branch (PRD 3.5) nor the consent-decline
    # collapse (PRD 3.8) mentions the field -- so it is left unasserted.
    assert claim["remedy_cost_cents"] == 0
    assert claim["owner_share_cents"] == 0
    assert claim["oem_share_cents"] == 0
    assert claim["admin_fee_cents"] == 0
    assert claim["oem_total_cents"] == 0
    assert claim["denial_reason"] in (
        "ADJUDICATOR_DECISION",
        "DISPUTE_DOWNGRADE",
        "CONSENT_DECLINED",
    )


def assert_thermal_event(event: dict) -> None:
    assert_common_fields(event, "thermal_event")
    assert event["severity"] in ("S1", "S2", "S3", "S4")
    assert event["source"] in ("TELEMATICS", "SERVICE_CENTER")
    assert event["containment_status"] in (
        "DETECTED",
        "ISOLATED",
        "PACK_QUARANTINED",
        "CONTAINMENT_CLOSED",
    )
    assert event["notification_status"] in (
        "NOT_REQUIRED",
        "PENDING",
        "FILED",
        "LATE_FILED",
    )
    assert event["event_status"] in ("OPEN", "COMPLETE")
    assert isinstance(event["containment_steps_completed"], int)
    assert_event_status_join(event)


def assert_event_status_join(event: dict) -> None:
    """`event_status` is COMPLETE only once containment is closed and notification settled."""
    containment_done = event["containment_status"] == "CONTAINMENT_CLOSED"
    notification_done = event["notification_status"] in (
        "NOT_REQUIRED",
        "FILED",
        "LATE_FILED",
    )
    expected = "COMPLETE" if containment_done and notification_done else "OPEN"
    assert event["event_status"] == expected, (
        f"event_status must be {expected} for containment "
        f"{event['containment_status']} and notification "
        f"{event['notification_status']}, got {event['event_status']}"
    )


def assert_remediation_campaign(campaign: dict) -> None:
    assert_common_fields(campaign, "remediation_campaign")
    assert campaign["status"] in (
        "DRAFT",
        "LIMITED_RELEASE",
        "FIELD_RELEASE",
        "SUSPENDED",
        "CLOSED",
    )
    assert campaign["target_defect"] in ("CHARGING", "THERMAL_MANAGEMENT")
    assert campaign["applies_to_pack_type"] in ("NEW", "REMANUFACTURED", "ANY")
    for key in ("solicited_consent_count", "open_consent_count", "applied_count"):
        assert isinstance(campaign[key], int) and campaign[key] >= 0


def assert_remediation_consent(consent: dict) -> None:
    assert_common_fields(consent, "remediation_consent")
    assert consent["consent_status"] in (
        "PENDING",
        "GRANTED",
        "DECLINED",
        "EXPIRED",
        "APPLIED",
    )
    assert isinstance(consent["solicitation_round"], int) and consent["solicitation_round"] >= 1


def assert_capacity_dispute(dispute: dict) -> None:
    assert_common_fields(dispute, "capacity_dispute")
    assert dispute["dispute_status"] in (
        "LAB_ASSIGNED",
        "LAB_RESULT_RECEIVED",
        "RESOLVED_UPHELD",
        "RESOLVED_OVERTURNED",
        "RESOLVED_DOWNGRADED",
    )
    assert_capacity_precision(dispute["nominal_basis_kwh"], "dispute.nominal_basis_kwh")
    assert_percentage_precision(dispute["oem_retention_pct"], "dispute.oem_retention_pct")
    assert isinstance(dispute["retest_count"], int)


def assert_pack_shipment(shipment: dict) -> None:
    assert_common_fields(shipment, "pack_shipment")
    assert shipment["status"] in ("DRAFT", "TENDERED", "RECEIVED", "REJECTED")
    assert shipment["hazmat_classification"] in ("UN3480", "UN3481", "UN3536")
    assert shipment["required_packaging_spec"] in (
        "STANDARD_UN_4G",
        "SP376_STRONG_OUTER",
    )
    assert_capacity_precision(shipment["gross_weight_kg"], "shipment.gross_weight_kg")
    assert_integer_cents(shipment["hazmat_fee_cents"], "hazmat_fee_cents")
    assert_percentage_precision(shipment["soc_limit_pct"], "shipment.soc_limit_pct")
    assert_packaging_requirement_follows_classification(shipment)


def assert_packaging_requirement_follows_classification(shipment: dict) -> None:
    """SP376_STRONG_OUTER for UN3536; STANDARD_UN_4G for UN3480 and UN3481 alike."""
    expected = (
        "SP376_STRONG_OUTER"
        if shipment["hazmat_classification"] == "UN3536"
        else "STANDARD_UN_4G"
    )
    assert shipment["required_packaging_spec"] == expected, (
        f"required_packaging_spec must be {expected} for classification "
        f"{shipment['hazmat_classification']}, got {shipment['required_packaging_spec']}"
    )


# ═══════════════════════════ list orderings ═══════════════════════════


def assert_modules_ascending_by_position(rows: List[dict]) -> None:
    """A pack's modules come back in ascending position_index order."""
    positions = [row["position_index"] for row in rows]
    assert positions == sorted(positions), (
        f"modules must be listed in ascending position_index order, got {positions}"
    )


def assert_snapshots_newest_first(rows: List[dict]) -> None:
    """A vehicle's snapshots come back newest captured_at first."""
    captured = [row["captured_at"] for row in rows]
    assert captured == sorted(captured, reverse=True), (
        f"snapshots must be listed newest captured_at first, got {captured}"
    )


def assert_created_at_ascending(rows: List[dict]) -> None:
    """The default ordering for every other collection is created_at ascending."""
    stamps = [row["created_at"] for row in rows]
    assert stamps == sorted(stamps), (
        f"the default listing order is created_at ascending, got {stamps}"
    )


def assert_pagination_meta(
    meta: dict,
    expected_total: int,
    expected_limit: Optional[int] = None,
    expected_offset: Optional[int] = None,
    expected_has_more: Optional[bool] = None,
) -> None:
    """Check the four list-meta keys the PRD publishes for every collection."""
    assert meta["total_count"] == expected_total, (
        f"meta.total_count must be {expected_total}, got {meta['total_count']}"
    )
    if expected_limit is not None:
        assert meta["limit"] == expected_limit, (
            f"meta.limit must be {expected_limit}, got {meta['limit']}"
        )
    if expected_offset is not None:
        assert meta["offset"] == expected_offset, (
            f"meta.offset must be {expected_offset}, got {meta['offset']}"
        )
    if expected_has_more is not None:
        assert meta["has_more"] is expected_has_more, (
            f"meta.has_more must be {expected_has_more}, got {meta['has_more']}"
        )


# ═══════════════════════════ domain invariants ═══════════════════════════


def assert_faulted_module_count_matches_roster(pack: dict, module_rows: List[dict]) -> None:
    """The pack's faulted counter mirrors exactly the modules at status FAULTED."""
    faulted = [row for row in module_rows if row["status"] == "FAULTED"]
    assert pack["faulted_module_count"] == len(faulted), (
        f"faulted_module_count must mirror the {len(faulted)} FAULTED modules, "
        f"got {pack['faulted_module_count']}"
    )


def assert_module_statuses(
    module_rows: List[dict], expected_by_position: dict
) -> None:
    """Assert the status of named positions, leaving the rest unexamined."""
    by_position = {row["position_index"]: row for row in module_rows}
    for position, expected in expected_by_position.items():
        assert position in by_position, f"no module at position {position}"
        actual = by_position[position]["status"]
        assert actual == expected, (
            f"module at position {position} must read {expected}, got {actual}"
        )


def assert_accrual(program: dict, expected_cents: int) -> None:
    """The program's liability ledger is the sum of every live approval's OEM total."""
    assert program["accrued_liability_cents"] == expected_cents, (
        f"accrued_liability_cents must be {expected_cents}, "
        f"got {program['accrued_liability_cents']}"
    )


def assert_reman_stock(program: dict, expected_count: int, expected_state: str) -> None:
    assert program["reman_available_count"] == expected_count, (
        f"reman_available_count must be {expected_count}, "
        f"got {program['reman_available_count']}"
    )
    assert program["reman_stock_state"] == expected_state, (
        f"reman_stock_state must be {expected_state}, got {program['reman_stock_state']}"
    )


def assert_lab_deviation(dispute: dict) -> None:
    """The signed deviation is the laboratory retention minus the OEM retention."""
    assert dispute["lab_retention_pct"] is not None, "lab_retention_pct must be recorded"
    expected = round(dispute["lab_retention_pct"] - dispute["oem_retention_pct"], 2)
    assert abs(dispute["deviation_pct"] - expected) < 0.005, (
        f"deviation_pct must be lab_retention_pct minus oem_retention_pct "
        f"({expected}), got {dispute['deviation_pct']}"
    )
    assert_percentage_precision(dispute["deviation_pct"], "dispute.deviation_pct")


def assert_unchanged(before: dict, after: dict, *fields: str) -> None:
    """Assert a refused write left the named fields exactly as they were."""
    for field in fields:
        assert before.get(field) == after.get(field), (
            f"a refused write must leave {field} unchanged: "
            f"was {before.get(field)!r}, now {after.get(field)!r}"
        )


def assert_version_unchanged(before: dict, after: dict, label: str = "record") -> None:
    """A refused write and a read alike leave the version untouched."""
    assert before["version"] == after["version"], (
        f"{label}.version must be unchanged at {before['version']}, "
        f"got {after['version']}"
    )


# ═══════════════════════════ instants ═══════════════════════════


def parse_instant(value: str) -> datetime:
    """Parse an ISO-8601 UTC instant, tolerating a trailing Z and optional millis."""
    assert isinstance(value, str) and value, f"expected an ISO-8601 instant, got {value!r}"
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def assert_same_instant(actual, expected: str, label: str = "timestamp") -> None:
    """Compare two timestamps as instants, not as strings.

    The PRD fixes the timezone and the precision of a stored instant but a body
    may spell one out with or without its three fractional digits, so the two
    spellings of the same moment must both pass.
    """
    assert actual is not None, f"{label} must be set, got null"
    assert parse_instant(actual) == parse_instant(expected), (
        f"{label} must be the instant {expected}, got {actual}"
    )
