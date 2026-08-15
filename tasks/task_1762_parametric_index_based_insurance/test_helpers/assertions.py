"""Entity assertions and domain invariant checkers (PRD §2.5, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        "version must be a positive integer"
    )


def assert_program(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["program_code"], str) and data["program_code"]
    assert data["peril_type"] in [
        "RAINFALL_DEFICIT", "WINDSPEED", "EARTHQUAKE_MAGNITUDE", "TEMPERATURE_EXCESS",
    ]
    assert data["regulatory_classification"] in [
        "ADMITTED_INSURANCE", "SURPLUS_LINES", "DERIVATIVE_CONTRACT",
    ]
    assert isinstance(data["exposure_limit_cents"], int)
    assert data["status"] in ["DRAFT", "ACTIVE", "SUSPENDED", "CLOSED"]
    for f in (
        "gross_written_premium_cents", "incurred_claims_cents", "ceded_recovery_cents",
        "net_retained_exposure_cents", "fraud_alert_count", "reporting_epoch",
    ):
        assert isinstance(data[f], int), f"{f} must be an integer"


def assert_index_definition(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("program_id", "")), "program_id must be a UUID"
    assert isinstance(data["index_code"], str) and data["index_code"]
    assert data["source_priority_mode"] in ["STATION_PRIMARY", "MODEL_PRIMARY"]
    assert data["strike_direction"] in ["BELOW", "ABOVE"]
    assert isinstance(data["trigger_thresholds"], list) and data["trigger_thresholds"]
    assert data["status"] in [
        "PENDING_AGREEMENT", "ACTIVE", "SUSPENDED", "DECOMMISSIONED",
    ]


def assert_station(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("program_id", "")), "program_id must be a UUID"
    assert isinstance(data["station_code"], str) and data["station_code"]
    assert data["station_kind"] in ["PHYSICAL_STATION", "GRID_MODEL"]
    assert data["status"] in ["COMMISSIONED", "OFFLINE", "DECOMMISSIONED"]


def assert_observation(data: dict):
    # Append-only log: id + created_at only; updated_at/version MUST be absent.
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "observation must not carry updated_at"
    assert "version" not in data, "observation must not carry version"
    assert is_valid_uuid(data.get("index_definition_id", ""))
    assert is_valid_uuid(data.get("station_id", ""))
    assert isinstance(data["window_end_date"], str)
    assert isinstance(data["sequence_no"], int) and data["sequence_no"] >= 1
    assert isinstance(data["is_effective"], bool)


def assert_policyholder(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("program_id", "")), "program_id must be a UUID"
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert isinstance(data["tax_id"], str) and data["tax_id"]
    assert isinstance(data["basis_risk_disclosure_acknowledged"], bool)
    assert isinstance(data["fraud_score"], int) and 0 <= data["fraud_score"] <= 100
    assert data["status"] in ["PROSPECT", "ACTIVE", "BLACKLISTED"]


def assert_policy(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("policyholder_id", ""))
    assert is_valid_uuid(data.get("program_id", ""))
    assert is_valid_uuid(data.get("index_definition_id", ""))
    assert isinstance(data["sum_insured_cents"], int) and data["sum_insured_cents"] > 0
    assert isinstance(data["premium_cents"], int) and data["premium_cents"] >= 0
    assert isinstance(data["premium_tax_cents"], int) and data["premium_tax_cents"] >= 0
    assert data["lifecycle_status"] in ["QUOTED", "BOUND", "EXPIRED", "CANCELLED"]
    assert data["settlement_posture"] in ["CLEAR", "PAYMENT_PENDING", "SETTLED_QUIET"]


def assert_trigger_event(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("index_definition_id", ""))
    assert is_valid_uuid(data.get("program_id", ""))
    assert isinstance(data["window_end_date"], str)
    assert isinstance(data["max_tier_breached"], int) and data["max_tier_breached"] >= 0
    assert data["verification_method"] in ["STATION_VERIFIED", "MODEL_FALLBACK"]
    assert data["status"] in [
        "DETECTED", "UNDER_REVIEW", "VERIFIED", "REJECTED", "ANNULLED",
    ]


def assert_claim(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("policy_id", ""))
    assert is_valid_uuid(data.get("trigger_event_id", ""))
    assert isinstance(data["tier_applied"], int) and data["tier_applied"] >= 1
    assert isinstance(data["provisional_payout_cents"], int)
    assert isinstance(data["ceded_recovery_cents"], int)
    assert data["status"] in [
        "GENERATED", "ADJUSTED", "APPROVED", "FRAUD_HOLD",
        "PAID", "RECOVERY_CEDED", "DECLINED", "VOIDED",
    ]


def assert_dispute(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("claim_id", ""))
    assert data["dispute_reason"] in [
        "BASIS_RISK_MISMATCH", "DATA_SOURCE_ERROR", "THRESHOLD_BOUNDARY", "LATE_REVISION",
    ]
    assert isinstance(data["claimed_tier"], int) and data["claimed_tier"] >= 1
    assert data["resolution"] in ["NONE", "UPHELD", "PARTIAL_UPHELD", "DENIED"]
    assert isinstance(data["adjustment_delta_cents"], int)
    assert data["status"] in ["OPEN", "AWAITING_CUSTOMER", "RESOLVED", "WITHDRAWN"]


def assert_treaty(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("program_id", ""))
    assert isinstance(data["treaty_name"], str) and data["treaty_name"]
    assert 0 < data["ceded_percentage"] <= 100
    assert isinstance(data["attachment_point_cents"], int)
    assert isinstance(data["treaty_limit_cents"], int)
    assert isinstance(data["recovered_to_date_cents"], int)
    assert data["recovered_to_date_cents"] <= data["treaty_limit_cents"], (
        "cumulative recoveries can never exceed the treaty limit"
    )
    assert data["status"] in ["PROPOSED", "ACTIVE", "EXHAUSTED", "COMMUTED"]


def assert_invoice(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("policy_id", ""))
    assert isinstance(data["invoice_amount_cents"], int)
    assert isinstance(data["amount_paid_cents"], int)
    assert 0 <= data["amount_paid_cents"] <= data["invoice_amount_cents"], (
        "payments must never exceed the billed amount"
    )
    assert isinstance(data["due_date"], str)
    assert data["status"] in ["ISSUED", "PARTIALLY_PAID", "PAID", "VOID"]
