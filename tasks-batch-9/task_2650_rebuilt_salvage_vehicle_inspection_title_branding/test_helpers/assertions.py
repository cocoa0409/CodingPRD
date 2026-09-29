"""Entity assertions and domain invariant checkers.

Every resource carries a server-minted UUID `id` and an ISO 8601 `created_at`.
Most resources also carry `updated_at` and an integer `version` starting at 1;
the two append-only records — a carrier's total-loss evaluation and an
inspector's finding — carry only `id` and `created_at`.
"""

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)

from .constants import (
    BRAND_SEVERITY,
    CHECKPOINT_CODES,
    PERCENT_DECIMALS,
    RATIO_DECIMALS,
)


# ---------------------------------------------------------------------------
# shared shape helpers
# ---------------------------------------------------------------------------
def assert_versioned_resource(data: dict, label: str = "resource") -> None:
    """id, created_at, updated_at and version are all present and well formed."""
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a UUID string"
    assert not str(data.get("id", "")).lower().startswith(
        (f"{label.lower()}_", "id_")
    ), f"{label}.id must carry no type prefix"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"{label}.created_at must be ISO 8601 UTC, got {data.get('created_at')!r}"
    assert is_iso8601_timestamp(
        data.get("updated_at", "")
    ), f"{label}.updated_at must be ISO 8601 UTC, got {data.get('updated_at')!r}"
    assert isinstance(data.get("version"), int), f"{label}.version must be an integer"
    assert data["version"] >= 1, f"{label}.version starts at 1, got {data['version']}"


def assert_append_only_resource(data: dict, label: str = "record") -> None:
    """An append-only record exposes id and created_at and neither of the two
    in-place-edit properties."""
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a UUID string"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"{label}.created_at must be ISO 8601 UTC, got {data.get('created_at')!r}"
    assert "updated_at" not in data, f"{label} must expose no updated_at field"
    assert "version" not in data, f"{label} must expose no version field"


def assert_money_cents(value, label: str = "amount_cents") -> None:
    """Monetary quantities are integers denominated in cents."""
    assert isinstance(value, int) and not isinstance(
        value, bool
    ), f"{label} must be an integer number of cents, got {value!r}"


def assert_percentage(value, label: str = "percentage") -> None:
    """Percentage and score quantities carry 2 decimal places, clamped 0.00-100.00."""
    assert isinstance(value, (int, float)), f"{label} must be numeric, got {value!r}"
    assert 0.00 <= float(value) <= 100.00, f"{label} must sit in [0.00, 100.00], got {value}"
    quantised = round(float(value), PERCENT_DECIMALS)
    assert abs(float(value) - quantised) < 1e-9, f"{label} must carry 2 decimal places, got {value}"


def assert_damage_ratio_precision(value, label: str = "damage_ratio") -> None:
    """The damage ratio is the single 4-decimal-place quantity in the program."""
    assert isinstance(value, (int, float)), f"{label} must be numeric, got {value!r}"
    quantised = round(float(value), RATIO_DECIMALS)
    assert abs(float(value) - quantised) < 1e-9, f"{label} must carry 4 decimal places, got {value}"


def assert_field_absent(data: dict, field: str, label: str = "resource") -> None:
    assert field not in data, f"{label} must not expose {field}, got {data.get(field)!r}"


# ---------------------------------------------------------------------------
# per-entity assertions
# ---------------------------------------------------------------------------
def assert_vehicle(data: dict) -> None:
    assert_versioned_resource(data, "vehicle")
    assert isinstance(data["vin"], str) and len(data["vin"]) == 17, "vin is 17 characters"
    assert isinstance(data["model_year"], int)
    assert isinstance(data["make"], str) and data["make"]
    assert isinstance(data["model"], str) and data["model"]
    assert data["body_class"] in ("SEDAN", "SUV", "TRUCK", "MOTORCYCLE", "TRAILER")
    assert data["fraud_hold"] in ("NONE", "UNDER_REFERRAL", "CONFIRMED")
    assert data["active_brand_code"] in BRAND_SEVERITY
    assert isinstance(data["brand_history"], list)
    assert all(b in BRAND_SEVERITY and b != "NONE" for b in data["brand_history"])
    assert isinstance(data["open_application_count"], int)
    assert data["last_odometer_miles"] is None or isinstance(
        data["last_odometer_miles"], int
    )
    assert isinstance(data["registered_state_code"], str)


def assert_rebuilder(data: dict) -> None:
    assert_versioned_resource(data, "rebuilder")
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert isinstance(data["license_number"], str) and data["license_number"]
    assert data["license_status"] in ("ACTIVE", "PROBATION", "SUSPENDED", "REVOKED")
    assert is_iso8601_timestamp(data["license_expires_at"])
    for field in (
        "bond_amount_cents",
        "fees_deposited_cents",
        "fee_balance_cents",
        "escrowed_fee_total_cents",
        "fees_consumed_cents",
    ):
        assert_money_cents(data[field], f"rebuilder.{field}")
    for field in (
        "open_referral_count",
        "substantiated_referral_count",
        "applications_titled_count",
    ):
        assert isinstance(data[field], int) and data[field] >= 0
    assert_percentage(data["recordkeeping_score_rolling"], "recordkeeping_score_rolling")
    assert_percentage(data["recordkeeping_score_lifetime"], "recordkeeping_score_lifetime")


def assert_inspector(data: dict) -> None:
    assert_versioned_resource(data, "inspector")
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["badge_number"], str) and data["badge_number"]
    assert is_iso8601_timestamp(data["credential_expires_at"])
    assert data["credential_status"] in ("CURRENT", "EXPIRED")
    assert isinstance(data["certifications"], list)
    assert all(c in ("STRUCTURAL", "FLOOD", "THEFT_RECOVERY") for c in data["certifications"])
    assert isinstance(data["scheduled_inspection_count"], int)
    assert isinstance(data["home_state_code"], str)


def assert_inspection_station(data: dict) -> None:
    assert_versioned_resource(data, "station")
    assert isinstance(data["station_code"], str) and data["station_code"]
    assert isinstance(data["bay_count"], int) and data["bay_count"] >= 1
    assert isinstance(data["supports_flood"], bool)
    assert isinstance(data["address_state_code"], str)
    assert isinstance(data["scheduled_occupancy_count"], int)
    assert data["scheduled_occupancy_count"] >= 0


def assert_damage_report(data: dict) -> None:
    assert_append_only_resource(data, "damage report")
    assert is_valid_uuid(data["vehicle_id"])
    assert isinstance(data["insurer_name"], str) and data["insurer_name"]
    assert isinstance(data["claim_number"], str) and data["claim_number"]
    assert data["basis_code"] in ("GROSS_ESTIMATE", "NET_OF_SALVAGE")
    for field in ("acv_cents", "repair_estimate_cents", "salvage_retention_cents"):
        assert_money_cents(data[field], f"damage report.{field}")
    assert data["damage_type"] in ("COLLISION", "FLOOD", "HAIL", "THEFT_RECOVERY", "FIRE")
    assert isinstance(data["flood_water_depth_cm"], int)
    assert isinstance(data["odometer_reading_miles"], int)
    assert is_iso8601_timestamp(data["report_effective_at"])
    assert isinstance(data["total_loss_declared"], bool)
    assert_damage_ratio_precision(data["damage_ratio"])
    assert data["recommended_brand_code"] in ("NONE", "SALVAGE", "FLOOD", "NON_REPAIRABLE")


def assert_title_record(data: dict) -> None:
    assert_versioned_resource(data, "title record")
    assert is_valid_uuid(data["vehicle_id"])
    assert data["brand_code"] in BRAND_SEVERITY
    assert isinstance(data["brand_history"], list)
    assert data["status"] in ("ACTIVE", "SUPERSEDED", "VOID", "SURRENDERED")
    assert data["recognition_state"] in (
        "NOT_SUBMITTED",
        "RECOGNITION_PENDING",
        "RECOGNIZED",
        "DOWNGRADED",
        "STALE",
    )
    assert isinstance(data["issuing_state_code"], str)
    assert is_iso8601_timestamp(data["issued_at"])
    assert isinstance(data["is_current"], bool)
    assert isinstance(data["transfer_sequence"], int) and data["transfer_sequence"] >= 0
    assert isinstance(data["owner_name"], str) and data["owner_name"]
    assert data["brand_severity"] == BRAND_SEVERITY[data["brand_code"]], (
        f"brand_severity {data['brand_severity']} must match the ladder value "
        f"{BRAND_SEVERITY[data['brand_code']]} for {data['brand_code']}"
    )


def assert_application(data: dict) -> None:
    assert_versioned_resource(data, "application")
    assert is_valid_uuid(data["vehicle_id"])
    assert is_valid_uuid(data["rebuilder_id"])
    assert is_valid_uuid(data["salvage_title_id"])
    assert data["status"] in (
        "DRAFT",
        "SUBMITTED",
        "DOCS_UNDER_REVIEW",
        "DOCS_ACCEPTED",
        "SCHEDULED",
        "IN_INSPECTION",
        "PASSED",
        "FAILED",
        "APPEAL_PENDING",
        "TITLE_ISSUED",
        "DENIED_FINAL",
        "WITHDRAWN",
        "VOID_FRAUD",
    )
    assert isinstance(data["expedite_requested"], bool)
    for field in (
        "declared_repair_cost_cents",
        "documented_parts_cost_cents",
        "assessed_fee_cents",
        "total_program_charge_cents",
        "fee_escrowed_cents",
    ):
        assert_money_cents(data[field], f"application.{field}")
    assert_percentage(data["documentation_completeness_pct"], "documentation_completeness_pct")
    assert isinstance(data["photo_view_count"], int) and data["photo_view_count"] >= 0
    assert isinstance(data["attempts_completed"], int) and data["attempts_completed"] >= 0
    assert isinstance(data["attempt_limit"], int) and data["attempt_limit"] >= 1
    assert data["last_inspection_result"] in (None, "PASS", "FAIL")


def assert_parts_document(data: dict) -> None:
    assert_versioned_resource(data, "parts document")
    assert is_valid_uuid(data["application_id"])
    assert data["doc_type"] in ("RECEIPT", "PHOTOGRAPH", "PARTS_INVOICE", "DONOR_CERTIFICATE")
    assert data["part_class"] in (
        "STRUCTURAL",
        "RESTRAINT",
        "POWERTRAIN",
        "BODY_PANEL",
        "GLAZING",
        "LIGHTING",
        "WHEEL",
        "PHOTO_SET",
    )
    assert data["photo_view_code"] in (
        None,
        "FRONT",
        "REAR",
        "LEFT",
        "RIGHT",
        "VIN_PLATE",
        "ENGINE_BAY",
    )
    assert data["source_type"] in ("NEW", "USED_DONOR", "RECYCLER", "OWNER_SUPPLIED")
    assert_money_cents(data["amount_cents"], "parts document.amount_cents")
    assert data["status"] in ("SUBMITTED", "VERIFIED", "REJECTED")
    assert data["rejection_reason"] in (
        None,
        "STOLEN_COMPONENT",
        "UNTRACEABLE_SOURCE",
        "ILLEGIBLE",
        "DUPLICATE",
    )
    assert isinstance(data["traceable"], bool)


def assert_inspection(data: dict) -> None:
    assert_versioned_resource(data, "inspection")
    assert is_valid_uuid(data["application_id"])
    assert is_valid_uuid(data["inspector_id"])
    assert is_valid_uuid(data["station_id"])
    assert isinstance(data["attempt_no"], int) and data["attempt_no"] >= 1
    assert is_iso8601_timestamp(data["scheduled_start_at"])
    assert is_iso8601_timestamp(data["scheduled_end_at"])
    assert is_iso8601_timestamp(data["effective_end_at"])
    assert data["status"] in (
        "SCHEDULED",
        "IN_PROGRESS",
        "COMPLETED_PASS",
        "COMPLETED_FAIL",
        "CANCELLED",
    )
    assert data["result"] in (None, "PASS", "FAIL")
    if data.get("adequacy_score") is not None:
        assert_percentage(data["adequacy_score"], "adequacy_score")
    assert isinstance(data["blocking_findings_count"], int)
    assert isinstance(data["forced_fail"], bool)
    assert isinstance(data["vin_verified"], bool)
    assert data["cancellation_reason"] in (
        None,
        "RESCHEDULED",
        "FRAUD_HOLD",
        "APPLICATION_VOIDED",
        "CLERK_REQUEST",
    )


def assert_finding(data: dict) -> None:
    assert_append_only_resource(data, "finding")
    assert is_valid_uuid(data["inspection_id"])
    assert data["category"] in (
        "STOLEN_COMPONENT",
        "VIN_ALTERATION",
        "STRUCTURAL_INADEQUACY",
        "ODOMETER_DISCREPANCY",
        "DOCUMENTATION_GAP",
    )
    assert data["severity"] in ("ADVISORY", "MAJOR", "CRITICAL")
    assert isinstance(data["description"], str) and data["description"]
    assert isinstance(data["blocking"], bool)
    assert isinstance(data["resolved"], bool)


def assert_appeal(data: dict) -> None:
    assert_versioned_resource(data, "appeal")
    assert is_valid_uuid(data["inspection_id"])
    assert data["grounds"] in (
        "SCORING_ERROR",
        "PART_TRACEABILITY_DISPUTE",
        "PROCEDURAL_DEFECT",
    )
    assert isinstance(data["narrative"], str) and data["narrative"]
    assert data["status"] in ("FILED", "UNDER_REVIEW", "GRANTED", "DENIED", "REMANDED")
    assert is_iso8601_timestamp(data["filed_at"])
    assert isinstance(data["remand_count"], int) and data["remand_count"] >= 0


def assert_fraud_referral(data: dict) -> None:
    assert_versioned_resource(data, "fraud referral")
    assert is_valid_uuid(data["vehicle_id"])
    assert data["referral_type"] in ("ODOMETER", "IDENTITY_TAMPERING", "DOCUMENT_FORGERY")
    assert data["origin"] in ("AUTO_CASCADE", "MANUAL")
    assert data["status"] in ("OPEN", "INVESTIGATING", "SUBSTANTIATED", "UNSUBSTANTIATED")
    assert isinstance(data["evidence_summary"], str) and data["evidence_summary"]
    assert isinstance(data["opened_by_user_id"], str) and data["opened_by_user_id"]


def assert_recognition_request(data: dict) -> None:
    assert_versioned_resource(data, "recognition request")
    assert is_valid_uuid(data["title_record_id"])
    assert isinstance(data["requesting_state_code"], str)
    assert data["submitted_brand_code"] in BRAND_SEVERITY
    assert data["mapped_brand_code"] in (None, *BRAND_SEVERITY.keys())
    assert data["outcome"] in (None, "RECOGNIZED", "DOWNGRADED", "REJECTED")
    assert data["status"] in ("PENDING", "DECIDED", "SUPERSEDED")


def assert_title_transfer(data: dict) -> None:
    assert_versioned_resource(data, "conveyance")
    assert is_valid_uuid(data["from_title_id"])
    assert is_valid_uuid(data["to_title_id"])
    assert isinstance(data["buyer_name"], str) and data["buyer_name"]
    assert is_iso8601_timestamp(data["transfer_effective_at"])
    assert isinstance(data["odometer_reading_miles"], int)
    assert data["odometer_flag"] in ("OK", "ROLLBACK_SUSPECTED")
    assert data["carried_brand_code"] in BRAND_SEVERITY
    assert_money_cents(data["sale_price_cents"], "conveyance.sale_price_cents")
    assert data["status"] in ("RECORDED", "VOID")


# ---------------------------------------------------------------------------
# domain invariant checkers
# ---------------------------------------------------------------------------
def assert_fee_ledger_closes(rebuilder: dict) -> None:
    """fee_balance_cents + escrowed_fee_total_cents + fees_consumed_cents == fees_deposited_cents."""
    left = (
        rebuilder["fee_balance_cents"]
        + rebuilder["escrowed_fee_total_cents"]
        + rebuilder["fees_consumed_cents"]
    )
    assert left == rebuilder["fees_deposited_cents"], (
        "the fee ledger must close: "
        f"{rebuilder['fee_balance_cents']} + {rebuilder['escrowed_fee_total_cents']} + "
        f"{rebuilder['fees_consumed_cents']} != {rebuilder['fees_deposited_cents']}"
    )


def assert_brand_severity_ladder(title: dict) -> None:
    """brand_severity is the ladder value of brand_code, and brand_history is
    ordered by severity descending."""
    assert title["brand_severity"] == BRAND_SEVERITY[title["brand_code"]]
    severities = [BRAND_SEVERITY[b] for b in title["brand_history"]]
    assert severities == sorted(severities, reverse=True), (
        f"brand_history must be sorted by severity descending, got {title['brand_history']}"
    )


def assert_title_dimensions_independent(
    title: dict, expected_status: str, expected_recognition_state: str
) -> None:
    """A title row's lifecycle status and its interstate recognition state move
    independently of one another."""
    assert title["status"] == expected_status, (
        f"expected status {expected_status}, got {title['status']}"
    )
    assert title["recognition_state"] == expected_recognition_state, (
        f"expected recognition_state {expected_recognition_state}, "
        f"got {title['recognition_state']}"
    )


def assert_documented_parts_cost_reconciles(application: dict, verified_documents: list) -> None:
    """documented_parts_cost_cents equals the exact sum of the verified documents'
    amount_cents."""
    expected = sum(d["amount_cents"] for d in verified_documents if d["status"] == "VERIFIED")
    assert application["documented_parts_cost_cents"] == expected, (
        f"documented_parts_cost_cents {application['documented_parts_cost_cents']} "
        f"must equal the verified sum {expected}"
    )


def assert_checkpoint_results_complete(inspection: dict) -> None:
    """The recorded checkpoint outcomes cover every weighted checkpoint exactly once."""
    codes = [entry["code"] for entry in inspection["checkpoint_results"]]
    assert sorted(codes) == sorted(CHECKPOINT_CODES), (
        f"checkpoint_results must carry one entry per checkpoint code, got {codes}"
    )


def assert_version_bumped_by(new: dict, old: dict, increment: int = 1) -> None:
    assert new["version"] == old["version"] + increment, (
        f"version must move from {old['version']} by {increment}, got {new['version']}"
    )
