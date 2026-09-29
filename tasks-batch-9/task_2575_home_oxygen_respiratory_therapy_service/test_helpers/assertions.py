"""Entity assertions and domain invariant checkers for this API."""

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)

# ─── Shared common-property helpers ───────────────────

def assert_common_fields(data: dict) -> None:
    """Every resource except a qualifying study carries id, created_at,
    updated_at and version."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a server-minted UUID: {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601 UTC with three fractional digits: {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be ISO 8601 UTC with three fractional digits: {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, "version starts at 1 on creation"


def assert_immutable_record_fields(data: dict) -> None:
    """A qualifying study carries only id and created_at: updated_at and version
    are absent from its representation entirely."""
    assert is_valid_uuid(data.get("id", "")), "id must be a server-minted UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "a qualifying study carries no updated_at"
    assert "version" not in data, "a qualifying study carries no version"


def assert_two_decimals(value, label: str = "value") -> None:
    """Decimal fields are carried to exactly two decimal places."""
    assert isinstance(value, (int, float)), f"{label} must be numeric, got {value!r}"
    assert round(float(value), 2) == float(value), (
        f"{label} must carry at most two decimal places, got {value!r}"
    )


def assert_whole_cents(value, label: str = "amount_cents") -> None:
    """Monetary amounts are integers denominated in cents."""
    assert isinstance(value, int) and not isinstance(value, bool), (
        f"{label} must be an integer number of cents, got {value!r}"
    )


def assert_ymd_date(value, label: str = "date") -> None:
    assert isinstance(value, str) and len(value) == 10 and value[4] == "-" and value[7] == "-", (
        f"{label} must be a YYYY-MM-DD date, got {value!r}"
    )


def assert_ym_month(value, label: str = "service_month") -> None:
    assert isinstance(value, str) and len(value) == 7 and value[4] == "-", (
        f"{label} must be a YYYY-MM month, got {value!r}"
    )


# ─── Entity assertions ────────────────────────────────

def assert_branch(data: dict) -> None:
    assert_common_fields(data)
    assert isinstance(data["name"], str) and 1 <= len(data["name"]) <= 120
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2
    assert data["state_code"].isupper(), "state_code is exactly two uppercase letters"
    assert isinstance(data["competitive_bid_area"], bool)
    assert isinstance(data["liquid_oxygen_certified"], bool)
    assert 0 <= data["refill_capacity_per_day"] <= 40
    assert 0 <= data["tank_exchange_buffer_minutes"] <= 120


def assert_patient(data: dict) -> None:
    assert_common_fields(data)
    assert isinstance(data["mrn"], str) and 1 <= len(data["mrn"]) <= 40
    assert isinstance(data["full_name"], str) and 1 <= len(data["full_name"]) <= 120
    assert is_valid_uuid(data["branch_id"])
    assert data["payer_type"] in [
        "MEDICARE_COMPETITIVE_BID",
        "MEDICARE_NON_BID",
        "MEDICAID",
        "COMMERCIAL",
    ]
    assert data["mobility_profile"] in [
        "HOMEBOUND",
        "LIMITED_AMBULATORY",
        "ACTIVE_AMBULATORY",
    ]
    assert 0 <= data["altitude_feet"] <= 15000
    assert data["status"] in ["ACTIVE", "TRANSFER_PENDING", "DISCHARGED"]
    assert data["current_cmn_status"] in [
        "NONE",
        "DRAFT",
        "SUBMITTED",
        "PHYSICIAN_SIGNED",
        "RETURNED_FOR_CORRECTION",
        "ACTIVE",
        "EXPIRED",
        "VOIDED",
        "SUPERSEDED",
    ]
    assert_two_decimals(data["oxygen_safety_risk_score"], "oxygen_safety_risk_score")
    assert 0.00 <= float(data["oxygen_safety_risk_score"]) <= 100.00
    assert data["risk_variant_applied"] in [
        "NONE",
        "INITIAL_ASSESSMENT",
        "ONGOING_SURVEILLANCE",
    ]
    assert isinstance(data["compliance_hold"], bool)
    assert_compliance_hold_matches_score(data)


def assert_compliance_hold_matches_score(patient: dict) -> None:
    """compliance_hold is true exactly when oxygen_safety_risk_score has
    reached 70.00, and false otherwise."""
    expected = float(patient["oxygen_safety_risk_score"]) >= 70.00
    assert patient["compliance_hold"] is expected, (
        f"compliance_hold must be {expected} at score "
        f"{patient['oxygen_safety_risk_score']}, got {patient['compliance_hold']}"
    )


def assert_qualifying_test(data: dict) -> None:
    assert_immutable_record_fields(data)
    assert is_valid_uuid(data["patient_id"])
    assert data["test_type"] in [
        "RESTING_ROOM_AIR",
        "EXERCISE",
        "NOCTURNAL_OVERNIGHT_OXIMETRY",
        "SLEEP_STUDY",
    ]
    assert is_iso8601_timestamp(data["tested_at"])
    assert isinstance(data["ordering_physician_npi"], str)
    assert len(data["ordering_physician_npi"]) == 10 and data["ordering_physician_npi"].isdigit()
    if data.get("spo2_percent") is not None:
        assert 50 <= data["spo2_percent"] <= 100
    if data.get("pao2_mmhg") is not None:
        assert 20 <= data["pao2_mmhg"] <= 120
    assert 0 <= data["desat_minutes"] <= 1440
    assert isinstance(data["cor_pulmonale_or_edema"], bool)
    assert data["validity_days"] in [30, 90]
    assert is_iso8601_timestamp(data["test_validity_expires_at"])
    assert data["qualifying_group"] in ["GROUP_I", "GROUP_II", "NON_QUALIFYING"]


def assert_cmn(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["patient_id"])
    assert is_valid_uuid(data["qualifying_test_id"])
    assert data["form_type"] in ["INITIAL", "RECERTIFICATION", "REVISED"]
    assert 0.5 <= float(data["prescribed_lpm"]) <= 15.0
    assert 1 <= data["hours_per_day"] <= 24
    assert isinstance(data["portable_prescribed"], bool)
    assert 1 <= data["length_of_need_months"] <= 99
    assert 0 <= data["narrative_element_count"] <= 3
    assert data["status"] in [
        "DRAFT",
        "SUBMITTED",
        "PHYSICIAN_SIGNED",
        "RETURNED_FOR_CORRECTION",
        "ACTIVE",
        "EXPIRED",
        "VOIDED",
        "SUPERSEDED",
    ]
    assert_two_decimals(data["documentation_score"], "documentation_score")
    assert 0 <= data["revision_round"] <= 3
    if data.get("recert_due_date") is not None:
        assert_ymd_date(data["recert_due_date"], "recert_due_date")
    if data.get("initial_date") is not None:
        assert_ymd_date(data["initial_date"], "initial_date")
    if data.get("physician_signature_date") is not None:
        assert_ymd_date(data["physician_signature_date"], "physician_signature_date")


def assert_rental_contract(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["patient_id"])
    assert is_valid_uuid(data["cmn_id"])
    assert data["pricing_basis"] in [
        "COMPETITIVE_BID_SINGLE_PAYMENT",
        "FEE_SCHEDULE_ADJUSTED",
        "CASH",
    ]
    assert 1 <= data["cap_month_limit"] <= 36
    assert data["billing_status"] in ["ACCRUING", "CAP_REACHED", "SUSPENDED", "CLOSED"]
    assert data["service_status"] in [
        "PENDING_SETUP",
        "IN_SERVICE",
        "PICKUP_SCHEDULED",
        "RETURNED",
        "SETUP_FAILED",
    ]
    assert data["suspension_reason"] in [
        "NONE",
        "CMN_VOIDED",
        "CMN_EXPIRED",
        "RECALL",
        "TRANSFER",
        "SETUP_FAILED",
    ]
    assert_whole_cents(data["monthly_allowable_cents"], "monthly_allowable_cents")
    assert isinstance(data["posted_months"], list)
    assert data["posted_month_count"] == len(data["posted_months"])
    assert_whole_cents(data["lifetime_paid_cents"], "lifetime_paid_cents")
    assert data["malfunction_count"] >= 0
    assert data["cumulative_oxygen_gap_minutes"] >= 0
    assert_contract_ledger_consistent(data)


def assert_contract_ledger_consistent(contract: dict) -> None:
    """lifetime_paid_cents is the exact sum of the ledger's amounts, and
    last_posted_service_month is the largest service_month present."""
    months = contract["posted_months"]
    total = sum(element["amount_cents"] for element in months)
    assert contract["lifetime_paid_cents"] == total, (
        f"lifetime_paid_cents {contract['lifetime_paid_cents']} must equal the sum of "
        f"the ledger's amount_cents {total}"
    )
    if months:
        expected_last = max(element["service_month"] for element in months)
        assert contract["last_posted_service_month"] == expected_last
    else:
        assert contract["last_posted_service_month"] is None


def assert_equipment_unit(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["branch_id"])
    assert isinstance(data["serial_number"], str) and 1 <= len(data["serial_number"]) <= 40
    assert isinstance(data["model_code"], str) and 1 <= len(data["model_code"]) <= 40
    assert data["equipment_class"] in [
        "STATIONARY_CONCENTRATOR",
        "PORTABLE_CONCENTRATOR",
        "LIQUID_RESERVOIR",
        "LIQUID_PORTABLE",
        "COMPRESSED_CYLINDER",
    ]
    assert 0.5 <= float(data["max_continuous_lpm"]) <= 15.0
    assert 0 <= data["max_pulse_setting"] <= 9
    assert 30 <= data["pm_interval_days"] <= 1095
    assert_ymd_date(data["next_pm_due_date"], "next_pm_due_date")
    assert data["status"] in [
        "IN_STOCK",
        "RESERVED",
        "DEPLOYED",
        "IN_QUARANTINE",
        "RETIRED",
    ]
    assert data["quarantine_reason"] in [
        "NONE",
        "RECALL",
        "MALFUNCTION",
        "SAFETY",
        "TRANSFER",
    ]
    if data.get("recall_remediated_at") is not None:
        assert is_iso8601_timestamp(data["recall_remediated_at"])


def assert_placement(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["contract_id"])
    assert is_valid_uuid(data["equipment_unit_id"])
    assert data["role"] in ["PRIMARY_STATIONARY", "PORTABLE", "BACKUP"]
    assert data["status"] in [
        "RESERVED",
        "PLACED",
        "REMOVED",
        "RECALLED_OUT_OF_SERVICE",
    ]
    assert data["removal_reason"] in [
        "NONE",
        "RELEASED",
        "SETUP_FAILED",
        "RECALL",
        "MALFUNCTION",
        "PICKUP",
        "TRANSFER",
    ]
    assert data["malfunction_count"] >= 0
    assert data["last_symptom"] in [
        "NONE",
        "NO_FLOW",
        "ALARM_CONTINUOUS",
        "LOW_PURITY",
        "POWER_FAILURE",
        "LEAK",
    ]
    assert data["last_severity_tier"] in ["NONE", "TIER_1", "TIER_2", "TIER_3"]


def assert_delivery_route(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["branch_id"])
    assert_ymd_date(data["service_date"], "service_date")
    assert isinstance(data["driver_user_id"], str) and data["driver_user_id"]
    assert is_iso8601_timestamp(data["shift_start_utc"])
    assert is_iso8601_timestamp(data["shift_end_utc"])
    assert data["status"] in ["PLANNING", "LOCKED", "DISPATCHED", "COMPLETED"]
    assert data["total_o2_liters_committed"] >= 0
    assert data["refill_slots_used"] >= 0
    assert data["planned_stop_count"] >= 0


def assert_route_stop(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["route_id"])
    assert is_valid_uuid(data["contract_id"])
    assert data["stop_type"] in [
        "SETUP_DELIVERY",
        "TANK_EXCHANGE",
        "PORTABLE_REFILL",
        "PICKUP",
        "MAINTENANCE_SWAP",
    ]
    assert is_iso8601_timestamp(data["window_start_utc"])
    assert is_iso8601_timestamp(data["window_end_utc"])
    assert 5 <= data["service_minutes"] <= 240
    assert 0 <= data["cylinders_requested"] <= 6
    assert data["liters_committed"] >= 0
    assert data["sequence_index"] >= 1
    assert data["status"] in ["PLANNED", "COMPLETED", "MISSED", "CANCELLED"]
    assert data["safety_result"] in ["NOT_ASSESSED", "PASS", "FAIL"]
    assert isinstance(data["education_topics_covered"], list)
    assert 0 <= data["safety_findings_count"] <= 3


def assert_recall_notice(data: dict) -> None:
    assert_common_fields(data)
    assert isinstance(data["model_code"], str) and data["model_code"]
    assert data["severity"] in ["CLASS_I", "CLASS_II", "CLASS_III"]
    assert data["status"] in ["OPEN", "IN_REMEDIATION", "CLOSED"]
    assert is_iso8601_timestamp(data["issued_at"])
    assert is_iso8601_timestamp(data["remediation_deadline_utc"])
    assert data["affected_unit_count"] >= 0
    assert data["auto_quarantined_unit_count"] >= 0
    assert data["remediated_unit_count"] >= 0


def assert_travel_authorization(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["contract_id"])
    assert is_iso8601_timestamp(data["depart_utc"])
    assert is_iso8601_timestamp(data["return_utc"])
    assert 0 <= data["destination_altitude_feet"] <= 15000
    assert data["status"] in ["REQUESTED", "APPROVED", "DENIED"]
    assert isinstance(data["trip_hours"], int) and data["trip_hours"] >= 0
    assert_two_decimals(data["altitude_factor"], "altitude_factor")
    assert 1.00 <= float(data["altitude_factor"]) <= 1.30
    assert_two_decimals(data["effective_lpm"], "effective_lpm")
    assert isinstance(data["base_liters"], int)
    assert isinstance(data["reserve_liters"], int)
    assert data["required_liters"] == data["base_liters"] + data["reserve_liters"]
    assert isinstance(data["cylinders_raw"], int)
    assert data["handling_surcharge_cylinders"] in [0, 1]
    assert (
        data["supply_cylinders_authorized"]
        == data["cylinders_raw"] + data["handling_surcharge_cylinders"]
    )
    assert data["supply_cylinders_authorized"] <= 12


# ─── Computed read assertions ─────────────────────────


def assert_risk_assessment_read(data: dict) -> None:
    assert is_valid_uuid(data["patient_id"])
    for factor in (
        "factor_smoking",
        "factor_electrical",
        "factor_teachback",
        "factor_flow",
        "factor_incident",
    ):
        assert 0 <= float(data[factor]) <= 100, f"{factor} lives on a 0 to 100 scale"
    assert_two_decimals(data["initial_assessment_score"], "initial_assessment_score")
    assert_two_decimals(data["ongoing_surveillance_score"], "ongoing_surveillance_score")
    assert_two_decimals(data["persisted_score"], "persisted_score")
    assert data["persisted_variant"] in [
        "NONE",
        "INITIAL_ASSESSMENT",
        "ONGOING_SURVEILLANCE",
    ]
    assert isinstance(data["compliance_hold"], bool)
    assert data["compliance_hold"] is (float(data["persisted_score"]) >= 70.00)


def assert_cap_summary_read(data: dict) -> None:
    assert is_valid_uuid(data["contract_id"])
    assert isinstance(data["service_month_basis_position"], int)
    assert isinstance(data["paid_month_basis_position"], int)
    assert data["variant_applied"] in ["SERVICE_MONTH_BASIS", "PAID_MONTH_BASIS"]
    assert isinstance(data["effective_position"], int)
    assert 1 <= data["cap_month_limit"] <= 36
    assert data["months_remaining"] >= 0, "months_remaining is floored at 0"
    expected_remaining = max(0, data["cap_month_limit"] - data["effective_position"])
    assert data["months_remaining"] == expected_remaining
    assert_whole_cents(data["monthly_allowable_cents"], "monthly_allowable_cents")
    assert_whole_cents(data["lifetime_paid_cents"], "lifetime_paid_cents")
    assert data["posted_month_count"] >= 0


def assert_route_manifest_read(data: dict) -> None:
    assert is_valid_uuid(data["route_id"])
    assert data["status"] in ["PLANNING", "LOCKED", "DISPATCHED", "COMPLETED"]
    for field in (
        "planned_stop_count",
        "completed_stop_count",
        "missed_stop_count",
        "cancelled_stop_count",
        "refill_slots_used",
        "refill_capacity_per_day",
        "total_o2_liters_committed",
    ):
        assert isinstance(data[field], int) and data[field] >= 0, f"{field} must be a non-negative integer"


def assert_clock_advance_result(data: dict) -> None:
    assert is_iso8601_timestamp(data["current_utc"])
    assert is_iso8601_timestamp(data["previous_utc"])
    assert data["current_utc"] > data["previous_utc"], "the clock is monotone forward-only"
    assert isinstance(data["expired_cmn_count"], int) and data["expired_cmn_count"] >= 0
    assert (
        isinstance(data["suspended_contract_count"], int)
        and data["suspended_contract_count"] >= 0
    )


# ─── Envelope helpers ─────────────────────────────────


def assert_request_meta(response) -> None:
    """meta.api_request_id starts with req_ and the timestamp is ISO 8601."""
    meta = response.json()["meta"]
    assert isinstance(meta["api_request_id"], str)
    assert meta["api_request_id"].startswith("req_"), (
        f"api_request_id must start with req_, got {meta['api_request_id']!r}"
    )
    assert is_iso8601_timestamp(meta["api_request_timestamp"])


def assert_pagination_meta(meta: dict, limit: int, offset: int, total_count: int) -> None:
    assert meta["limit"] == limit
    assert meta["offset"] == offset
    assert meta["total_count"] == total_count
    assert meta["has_more"] is (offset + limit < total_count)
