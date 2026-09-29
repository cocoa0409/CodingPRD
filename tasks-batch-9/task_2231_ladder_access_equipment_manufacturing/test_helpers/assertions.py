"""Entity assertions and domain invariant checkers derived from the PRD."""

from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import (
    assert_cost_precision,
    is_iso8601_timestamp,
    is_valid_uuid,
)

from .constants import (
    DEFLECTION_INCHES_PER_FOOT,
    DEFLECTION_SPAN_DIVISOR,
    RATED_LOAD_BY_DUTY_RATING,
    PULL_FORCE_MULTIPLIER,
)


# ---------------------------------------------------------------------------
# Shared record-shape helpers (PRD §2.4)
# ---------------------------------------------------------------------------
def assert_identity_fields(data: Dict[str, Any]) -> None:
    """Every persisted resource carries a UUID `id` and an ISO 8601 `created_at`."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"created_at must be ISO 8601 UTC, got {data.get('created_at')!r}"


def assert_versioned_record(data: Dict[str, Any]) -> None:
    """A resource that carries `updated_at` and an integer `version`."""
    assert_identity_fields(data)
    assert is_iso8601_timestamp(
        data.get("updated_at", "")
    ), f"updated_at must be ISO 8601 UTC, got {data.get('updated_at')!r}"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, f"version must start at 1 or above, got {data['version']}"


def assert_append_only_record(data: Dict[str, Any]) -> None:
    """An append-only measurement record: only `id` and `created_at`, no
    `updated_at` and no `version`."""
    assert_identity_fields(data)
    assert "updated_at" not in data, "append-only record must not carry updated_at"
    assert "version" not in data, "append-only record must not carry version"


def assert_decimal_places(value: float, places: int, label: str = "value") -> None:
    """A stored figure is rounded to exactly `places` decimal places."""
    assert value is not None, f"{label} must not be null"
    quantized = round(float(value), places)
    assert abs(float(value) - quantized) < 1e-9, (
        f"{label} must be stored to {places} decimal places, got {value}"
    )


def assert_two_decimal_places(value: float, label: str = "value") -> None:
    assert_decimal_places(value, 2, label)
    assert_cost_precision(value, decimal_places=2)


def assert_three_decimal_places(value: float, label: str = "value") -> None:
    assert_decimal_places(value, 3, label)


def assert_whole_percent(value: Any, label: str = "margin_pct") -> None:
    """A whole number of percent — zero decimal places."""
    assert isinstance(value, int) or float(value).is_integer(), (
        f"{label} must be a whole number of percent, got {value!r}"
    )


# ---------------------------------------------------------------------------
# Product (PRD §3.1, §2.7, §2.10)
# ---------------------------------------------------------------------------
def assert_product(data: Dict[str, Any]) -> None:
    assert_versioned_record(data)
    assert isinstance(data["model_code"], str) and 1 <= len(data["model_code"]) <= 40
    assert data["product_type"] in [
        "STEP_LADDER",
        "EXTENSION_LADDER",
        "PLATFORM_LADDER",
        "ARTICULATED_LADDER",
        "MOBILE_SCAFFOLD_TOWER",
    ]
    assert data["material"] in [
        "ALUMINUM_EXTRUSION",
        "FIBERGLASS_PULTRUSION",
        "STEEL",
    ]
    assert data["duty_rating"] in [
        "TYPE_III",
        "TYPE_II",
        "TYPE_I",
        "TYPE_IA",
        "TYPE_IAA",
    ]
    assert 0 < float(data["working_length_ft"]) <= 60, (
        "working_length_ft must be greater than zero and no greater than 60 feet"
    )
    assert data["design_status"] in ["DRAFT", "DESIGN_FROZEN", "DESIGN_OBSOLETE"]
    assert data["market_status"] in [
        "NOT_RELEASED",
        "RETAIL_RELEASED",
        "STOP_SHIP",
        "RECALLED",
    ]
    assert data["rated_load_lb"] == RATED_LOAD_BY_DUTY_RATING[data["duty_rating"]], (
        "rated_load_lb must follow the duty class"
    )
    assert_two_decimal_places(data["safety_factor"], "safety_factor")
    assert_two_decimal_places(data["required_test_load_lb"], "required_test_load_lb")
    assert_two_decimal_places(data["required_pull_force_lbf"], "required_pull_force_lbf")
    assert_three_decimal_places(
        data["max_allowed_deflection_in"], "max_allowed_deflection_in"
    )
    assert isinstance(data["held_registration_count"], int)
    assert_two_decimal_places(data["risk_score_gross"], "risk_score_gross")
    assert_two_decimal_places(data["risk_score_mitigated"], "risk_score_mitigated")


def assert_product_derivations(
    data: Dict[str, Any],
    expected_rated_load_lb: int,
    expected_safety_factor: float,
    expected_required_test_load_lb: float,
    expected_required_pull_force_lbf: float,
    expected_max_allowed_deflection_in: float,
) -> None:
    """The four derivation steps of PRD §3.1, pinned to literal expectations."""
    assert data["rated_load_lb"] == expected_rated_load_lb, (
        f"rated_load_lb: expected {expected_rated_load_lb}, got {data['rated_load_lb']}"
    )
    assert float(data["safety_factor"]) == expected_safety_factor, (
        f"safety_factor: expected {expected_safety_factor}, got {data['safety_factor']}"
    )
    assert float(data["required_test_load_lb"]) == expected_required_test_load_lb, (
        f"required_test_load_lb: expected {expected_required_test_load_lb}, "
        f"got {data['required_test_load_lb']}"
    )
    assert float(data["required_pull_force_lbf"]) == expected_required_pull_force_lbf, (
        f"required_pull_force_lbf: expected {expected_required_pull_force_lbf}, "
        f"got {data['required_pull_force_lbf']}"
    )
    assert (
        float(data["max_allowed_deflection_in"]) == expected_max_allowed_deflection_in
    ), (
        f"max_allowed_deflection_in: expected {expected_max_allowed_deflection_in}, "
        f"got {data['max_allowed_deflection_in']}"
    )


def assert_pull_force_follows_rated_load(data: Dict[str, Any]) -> None:
    """`required_pull_force_lbf` is `rated_load_lb` multiplied by one and a half."""
    expected = round(data["rated_load_lb"] * PULL_FORCE_MULTIPLIER + 1e-9, 2)
    assert float(data["required_pull_force_lbf"]) == expected, (
        f"required_pull_force_lbf: expected {expected}, got {data['required_pull_force_lbf']}"
    )


def assert_deflection_follows_length(data: Dict[str, Any]) -> None:
    """`max_allowed_deflection_in` is length in inches divided by 180."""
    raw = float(data["working_length_ft"]) * DEFLECTION_INCHES_PER_FOOT / DEFLECTION_SPAN_DIVISOR
    expected = round(raw + 1e-12, 3)
    assert float(data["max_allowed_deflection_in"]) == expected, (
        f"max_allowed_deflection_in: expected {expected}, "
        f"got {data['max_allowed_deflection_in']}"
    )


def assert_fresh_product_defaults(data: Dict[str, Any]) -> None:
    """A newly catalogued model's declared starting values (PRD §3.1)."""
    assert data["design_status"] == "DRAFT"
    assert data["market_status"] == "NOT_RELEASED"
    assert data["held_registration_count"] == 0
    assert float(data["risk_score_gross"]) == 0.00
    assert float(data["risk_score_mitigated"]) == 0.00
    for field in (
        "design_frozen_at",
        "frozen_revision_id",
        "market_status_changed_at",
        "stop_ship_reason_code",
        "dhf_retention_until",
        "retention_anchor_source",
    ):
        assert data[field] is None, f"{field} must start null, got {data[field]!r}"


# ---------------------------------------------------------------------------
# Design revision (PRD §3.2)
# ---------------------------------------------------------------------------
def assert_design_revision(data: Dict[str, Any]) -> None:
    assert_versioned_record(data)
    assert is_valid_uuid(data["product_id"])
    assert isinstance(data["revision_label"], str) and data["revision_label"]
    assert data["joint_type"] in ["RIVETED", "BONDED", "WELDED"]
    assert float(data["structural_margin_pct"]) >= 0
    assert_two_decimal_places(data["structural_margin_pct"], "structural_margin_pct")
    assert float(data["rail_section_modulus_in3"]) > 0
    assert_three_decimal_places(
        data["rail_section_modulus_in3"], "rail_section_modulus_in3"
    )
    assert data["status"] in [
        "DRAFT",
        "UNDER_REVIEW",
        "CHANGES_REQUESTED",
        "APPROVED",
        "SUPERSEDED",
    ]
    assert isinstance(data["review_round"], int) and data["review_round"] >= 1


# ---------------------------------------------------------------------------
# Product document (PRD §3.3)
# ---------------------------------------------------------------------------
def assert_product_document(data: Dict[str, Any]) -> None:
    assert_versioned_record(data)
    assert is_valid_uuid(data["product_id"])
    assert data["doc_kind"] in [
        "DUTY_RATING_LABEL",
        "WARNING_LABEL",
        "INSTRUCTION_LABEL",
        "CERT_MARK_LABEL",
        "RETAIL_CARTON",
        "ASSEMBLY_INSTRUCTION_SHEET",
        "CONSUMER_SAFETY_SHEET",
    ]
    assert data["status"] in ["DRAFT", "APPROVED", "SUPERSEDED"]
    if data["doc_kind"] in [
        "DUTY_RATING_LABEL",
        "WARNING_LABEL",
        "INSTRUCTION_LABEL",
        "CERT_MARK_LABEL",
    ]:
        assert data["placement_zone"] in [
            "SIDE_RAIL_UPPER",
            "SIDE_RAIL_LOWER",
            "TOP_CAP",
            "BACK_RAIL",
        ], "a label kind must have a non-null placement_zone"
    else:
        assert data["placement_zone"] is None, (
            "a non-label kind must carry a null placement_zone"
        )


# ---------------------------------------------------------------------------
# Test bench and reservation (PRD §3.4, §2.9)
# ---------------------------------------------------------------------------
def assert_test_bench(data: Dict[str, Any]) -> None:
    assert_versioned_record(data)
    assert isinstance(data["bench_code"], str) and data["bench_code"]
    assert float(data["max_load_capacity_lb"]) > 0
    assert 0 <= int(data["cooldown_minutes"]) <= 480
    assert isinstance(data["reserved_minutes_total"], int)
    assert data["reserved_minutes_total"] >= 0


def assert_bench_reservation(data: Dict[str, Any]) -> None:
    assert_versioned_record(data)
    assert is_valid_uuid(data["test_bench_id"])
    assert is_valid_uuid(data["test_campaign_id"])
    assert data["status"] in ["HELD", "CONSUMED", "CANCELLED"]
    assert isinstance(data["duration_minutes"], int) and data["duration_minutes"] > 0


def assert_bench_minutes_conserved(
    bench: Dict[str, Any], reservations: List[Dict[str, Any]]
) -> None:
    """`reserved_minutes_total` equals the sum of `duration_minutes` over the
    bench's reservations whose `status` is `HELD` or `CONSUMED` (PRD §2.9)."""
    expected = sum(
        int(r["duration_minutes"])
        for r in reservations
        if r["test_bench_id"] == bench["id"] and r["status"] in ("HELD", "CONSUMED")
    )
    assert int(bench["reserved_minutes_total"]) == expected, (
        f"reserved_minutes_total {bench['reserved_minutes_total']} must equal the "
        f"HELD+CONSUMED duration sum {expected}"
    )


# ---------------------------------------------------------------------------
# Test campaign and load test (PRD §3.4, §3.5)
# ---------------------------------------------------------------------------
def assert_test_campaign(data: Dict[str, Any]) -> None:
    assert_versioned_record(data)
    assert is_valid_uuid(data["product_id"])
    assert is_valid_uuid(data["design_revision_id"])
    assert data["purpose"] in [
        "DESIGN_QUALIFICATION",
        "CERTIFICATION_LISTING",
        "PERIODIC_AUDIT",
        "INCIDENT_INVESTIGATION",
    ]
    assert data["status"] in [
        "PLANNED",
        "IN_PROGRESS",
        "PASSED",
        "FAILED",
        "CANCELLED",
    ]
    assert isinstance(data["load_test_count"], int) and data["load_test_count"] >= 0
    assert isinstance(data["failed_test_count"], int) and data["failed_test_count"] >= 0
    assert data["failed_test_count"] <= data["load_test_count"]
    if data["purpose"] != "PERIODIC_AUDIT":
        assert data["audit_sample_size"] is None, (
            "audit_sample_size stays null for non-audit purposes"
        )
        assert data["escalation_tier"] is None, (
            "escalation_tier stays null for non-audit purposes"
        )
        assert data["prior_failure_rate_pct"] is None, (
            "prior_failure_rate_pct stays null for non-audit purposes"
        )
        for field in (
            "listing_record_id",
            "sampled_lot_id",
            "sample_window_start",
            "sample_window_end",
        ):
            assert data[field] is None, (
                f"{field} belongs exclusively to the audit purpose, got {data[field]!r}"
            )


def assert_load_test(data: Dict[str, Any]) -> None:
    assert_append_only_record(data)
    assert data["test_code"] in [
        "STATIC_VERTICAL",
        "RAIL_BENDING",
        "SLIP_RESISTANCE",
        "HINGE_CYCLE",
        "ELECTRICAL_LEAKAGE",
        "RIVET_SHEAR",
    ]
    assert float(data["applied_load_lb"]) > 0
    assert float(data["measured_deflection_in"]) >= 0
    assert float(data["permanent_set_in"]) >= 0
    assert data["outcome"] in ["PASS", "FAIL"]
    if data["outcome"] == "PASS":
        assert data["failure_reason_code"] is None, (
            "a passing load test has a null failure_reason_code"
        )
    else:
        assert data["failure_reason_code"] in [
            "LOAD_BELOW_REQUIRED",
            "DEFLECTION_EXCEEDED",
            "PERMANENT_SET_EXCEEDED",
        ]


# ---------------------------------------------------------------------------
# Production lot and joint samples (PRD §3.6, §2.9)
# ---------------------------------------------------------------------------
def assert_production_lot(data: Dict[str, Any]) -> None:
    assert_versioned_record(data)
    assert is_valid_uuid(data["product_id"])
    assert is_valid_uuid(data["design_revision_id"])
    assert isinstance(data["lot_code"], str) and data["lot_code"]
    assert int(data["planned_units"]) > 0
    assert data["status"] in [
        "OPEN",
        "IN_PROCESS",
        "RELEASED",
        "QUARANTINED",
        "SCRAPPED",
    ]
    for field in (
        "produced_units",
        "units_wip",
        "units_quarantined",
        "units_released",
        "units_scrapped",
        "joint_sample_count",
        "joint_fail_count",
        "required_joint_sample_count",
    ):
        assert isinstance(data[field], int), f"{field} must be an exact integer"
        assert data[field] >= 0, f"{field} must not go negative"
    if data["conformance_index"] is not None:
        assert_two_decimal_places(data["conformance_index"], "conformance_index")
    assert_lot_units_conserved(data)


def assert_lot_units_conserved(lot: Dict[str, Any]) -> None:
    """`units_wip` plus `units_quarantined` plus `units_released` plus
    `units_scrapped` always equals `produced_units` (PRD §2.9)."""
    total = (
        int(lot["units_wip"])
        + int(lot["units_quarantined"])
        + int(lot["units_released"])
        + int(lot["units_scrapped"])
    )
    assert total == int(lot["produced_units"]), (
        f"conserved identity broken: units_wip {lot['units_wip']} + units_quarantined "
        f"{lot['units_quarantined']} + units_released {lot['units_released']} + "
        f"units_scrapped {lot['units_scrapped']} = {total}, but produced_units is "
        f"{lot['produced_units']}"
    )


def assert_joint_integrity_sample(data: Dict[str, Any]) -> None:
    assert_append_only_record(data)
    assert is_valid_uuid(data["production_lot_id"])
    assert int(data["sample_seq"]) > 0
    assert float(data["pull_force_lbf"]) > 0
    assert_two_decimal_places(data["pull_force_lbf"], "pull_force_lbf")
    assert data["result"] in ["PASS", "FAIL"]
    assert_whole_percent(data["margin_pct"])
    if float(data["pull_force_lbf"]) >= float(data["required_pull_force_lbf"]):
        assert data["result"] == "PASS", (
            "result is PASS when pull_force_lbf is at or above the snapshot requirement"
        )
    else:
        assert data["result"] == "FAIL"


# ---------------------------------------------------------------------------
# Listing body and listing record (PRD §3.5)
# ---------------------------------------------------------------------------
def assert_listing_body(data: Dict[str, Any]) -> None:
    assert_versioned_record(data)
    assert isinstance(data["body_code"], str) and data["body_code"]
    assert isinstance(data["accredited_standards"], list)
    assert len(data["accredited_standards"]) >= 1, "accredited_standards is non-empty"
    for standard in data["accredited_standards"]:
        assert standard in [
            "ANSI_ASC_A14_2",
            "ANSI_ASC_A14_5",
            "EN_131_2",
            "CSA_Z11",
        ]
    assert 0 < int(data["audit_interval_days"]) <= 730


def assert_listing_record(data: Dict[str, Any]) -> None:
    assert_versioned_record(data)
    assert is_valid_uuid(data["product_id"])
    assert is_valid_uuid(data["listing_body_id"])
    assert data["standard_code"] in [
        "ANSI_ASC_A14_2",
        "ANSI_ASC_A14_5",
        "EN_131_2",
        "CSA_Z11",
    ]
    assert data["status"] in ["APPLIED", "LISTED", "SUSPENDED", "WITHDRAWN"]
    if data["suspension_reason"] is not None:
        assert data["suspension_reason"] in [
            "AUDIT_FAILURE",
            "STOP_SHIP_CASCADE",
            "BODY_REQUEST",
        ]


# ---------------------------------------------------------------------------
# Consumer registration (PRD §3.8, §3.9)
# ---------------------------------------------------------------------------
def assert_consumer_registration(data: Dict[str, Any]) -> None:
    assert_versioned_record(data)
    assert is_valid_uuid(data["production_lot_id"])
    assert isinstance(data["consumer_email"], str) and data["consumer_email"]
    assert data["purchase_channel"] in ["BIG_BOX_RETAIL", "PRO_DEALER", "ONLINE"]
    assert data["registration_status"] in ["REGISTERED", "NOTIFIED", "ACKNOWLEDGED"]
    assert isinstance(data["hold_flag"], bool)
    if data["remedy_choice"] is not None:
        assert data["remedy_choice"] in ["REPAIR_KIT", "REPLACEMENT", "REFUND"]


# ---------------------------------------------------------------------------
# Field incident and corrective action (PRD §3.8)
# ---------------------------------------------------------------------------
def assert_field_incident(data: Dict[str, Any]) -> None:
    assert_versioned_record(data)
    assert is_valid_uuid(data["product_id"])
    assert data["incident_type"] in [
        "RAIL_FRACTURE",
        "RUNG_SEPARATION",
        "HINGE_FAILURE",
        "SLIP_FALL",
        "LABEL_ILLEGIBLE",
    ]
    assert data["injury_severity"] in [
        "NONE",
        "MINOR",
        "HOSPITALIZATION",
        "FATALITY",
    ]
    assert data["status"] in [
        "REPORTED",
        "UNDER_INVESTIGATION",
        "ROOT_CAUSE_IDENTIFIED",
        "CAPA_OPENED",
        "NOT_SUBSTANTIATED",
        "CLOSED",
    ]
    assert isinstance(data["requires_capa"], bool)
    if data["incident_points"] is not None:
        assert_two_decimal_places(data["incident_points"], "incident_points")
    if data["root_cause_code"] is not None:
        assert data["root_cause_code"] in [
            "RIVET_SHEAR_MARGIN",
            "RAIL_SECTION_MODULUS",
            "LABEL_ADHESION",
            "HINGE_STOP_GEOMETRY",
            "CONSUMER_MISUSE",
        ]


def assert_corrective_action(data: Dict[str, Any]) -> None:
    assert_versioned_record(data)
    assert is_valid_uuid(data["field_incident_id"])
    assert isinstance(data["action_summary"], str) and data["action_summary"]
    assert data["status"] in ["OPEN", "VERIFIED", "SUPERSEDED"]
    assert isinstance(data["authored_by_user_id"], str) and data["authored_by_user_id"]


# ---------------------------------------------------------------------------
# Recall event (PRD §3.9)
# ---------------------------------------------------------------------------
def assert_recall_event(data: Dict[str, Any]) -> None:
    assert_versioned_record(data)
    assert is_valid_uuid(data["product_id"])
    assert data["remedy_type"] in ["REPAIR_KIT", "REPLACEMENT", "REFUND"]
    assert isinstance(data["affected_revision_ids"], list)
    assert len(data["affected_revision_ids"]) >= 1, "affected_revision_ids is non-empty"
    assert data["status"] in ["DRAFT", "ANNOUNCED", "IN_PROGRESS", "CLOSED"]
    if data["notification_coverage_pct"] is not None:
        assert_two_decimal_places(
            data["notification_coverage_pct"], "notification_coverage_pct"
        )


def assert_recall_remedy_ledger(data: Dict[str, Any]) -> None:
    """`units_remedied` plus `units_outstanding` always equals
    `exposure_units_registered_basis` (PRD §3.9)."""
    assert (
        int(data["units_remedied"]) + int(data["units_outstanding"])
        == int(data["exposure_units_registered_basis"])
    ), (
        f"units_remedied {data['units_remedied']} + units_outstanding "
        f"{data['units_outstanding']} must equal exposure_units_registered_basis "
        f"{data['exposure_units_registered_basis']}"
    )


# ---------------------------------------------------------------------------
# Liability dossier (PRD §2.10)
# ---------------------------------------------------------------------------
def assert_liability_dossier(data: Dict[str, Any]) -> None:
    assert is_valid_uuid(data["product_id"])
    assert isinstance(data["model_code"], str) and data["model_code"]
    for field in (
        "design_history_revision_count",
        "passed_campaign_count",
        "released_lot_count",
        "open_incident_count",
    ):
        assert isinstance(data[field], int), f"{field} must be an integer count"
        assert data[field] >= 0
    assert isinstance(data["approved_document_kinds"], list)
    assert_two_decimal_places(data["risk_score_gross"], "risk_score_gross")
    assert_two_decimal_places(data["risk_score_mitigated"], "risk_score_mitigated")
    if data["retention_anchor_source"] is not None:
        assert data["retention_anchor_source"] in [
            "LOT_RELEASE",
            "INCIDENT_CLOSURE",
            "RECALL",
            "DESIGN_FREEZE",
        ]


# ---------------------------------------------------------------------------
# Misc
# ---------------------------------------------------------------------------
def assert_sorted_by_created_at_ascending(rows: List[Dict[str, Any]]) -> None:
    """Every list endpoint returns rows sorted by `created_at` ascending."""
    stamps = [row["created_at"] for row in rows]
    assert stamps == sorted(stamps), f"rows must be sorted by created_at ascending: {stamps}"


def assert_optional_null(data: Dict[str, Any], *fields: str) -> None:
    for field in fields:
        assert data.get(field) is None, f"{field} must be null, got {data.get(field)!r}"


def parse_instant(value: str) -> "datetime":
    """Parse an ISO 8601 UTC instant, with or without fractional digits."""
    from datetime import datetime

    text = value.replace("Z", "+00:00")
    return datetime.fromisoformat(text)


def assert_instant_equals(actual: Optional[str], expected: str, label: str = "instant") -> None:
    """Compare two ISO 8601 UTC instants by value, so a serializer that writes
    three fractional digits and one that writes none both satisfy the check."""
    assert actual is not None, f"{label} must be stamped, got null"
    assert parse_instant(actual) == parse_instant(expected), (
        f"{label}: expected {expected}, got {actual}"
    )
