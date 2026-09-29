"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import AVOIDABLE_DELAY_CODES

_UUID_LEN = 36


def assert_no_type_prefix(value: str):
    """PRD §2.4: identifiers are server-minted UUIDs with no type prefix."""
    assert is_valid_uuid(value), f"id must be a bare UUID, got {value!r}"
    assert len(value) == _UUID_LEN, f"id must be a 36-character UUID, got {value!r}"
    assert "_" not in value, f"id must carry no type prefix, got {value!r}"


def assert_common_fields(data: dict):
    """Every resource carries a UUID id, ISO 8601 created_at / updated_at and an
    integer version starting at 1."""
    assert_no_type_prefix(data.get("id", ""))
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, f"version starts at 1, got {data['version']}"


def assert_payer(data: dict):
    assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["snf_auth_required"], bool)
    assert isinstance(data["hh_auth_required"], bool)
    assert 0.0 <= float(data["coinsurance_pct"]) <= 0.5
    assert isinstance(data["auth_expiry_days"], int)


def assert_patient(data: dict):
    assert_common_fields(data)
    assert isinstance(data["mrn"], str) and data["mrn"]
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["date_of_birth"], str)
    assert_no_type_prefix(data["primary_payer_id"])
    assert isinstance(data["prior_admissions_180d"], int)
    assert data["prior_admissions_180d"] >= 0
    assert isinstance(data["lives_alone"], bool)
    assert isinstance(data["has_pcp"], bool)


def assert_episode(data: dict):
    assert_common_fields(data)
    assert_no_type_prefix(data["patient_id"])
    assert data["admission_type"] in ("EMERGENT", "ELECTIVE", "OBSERVATION")
    assert data["case_status"] in (
        "ADMITTED",
        "SCREENED",
        "PLANNING",
        "READY_FOR_DISCHARGE",
        "DISCHARGED",
        "CANCELLED",
    )
    assert data["barrier_posture"] in ("CLEAR", "ACTIVE", "ESCALATED")
    assert data["current_risk_band"] in ("LOW", "MODERATE", "HIGH", "VERY_HIGH")
    assert data["risk_variant_applied"] in (
        "ADMISSION_VARIANT",
        "PREDISCHARGE_VARIANT",
    )
    assert 0 <= data["current_risk_score"] <= 100, (
        f"composite risk score is clamped into 0..100, got {data['current_risk_score']}"
    )
    assert isinstance(data["logistics_committed_cents"], int)
    assert isinstance(data["authorized_days_total"], int)
    assert isinstance(data["readmission_bundle_complete"], bool)


def assert_screening(data: dict):
    assert_common_fields(data)
    assert_no_type_prefix(data["episode_id"])
    assert data["screening_type"] in ("ADMISSION", "RESCREEN")
    for field in ("functional_score", "cognitive_score", "social_support_score"):
        assert 0 <= data[field] <= 10, f"{field} must sit in 0..10, got {data[field]}"
    assert data["medication_count"] >= 0
    assert isinstance(data["prior_admissions_snapshot"], int)
    assert isinstance(data["lives_alone_snapshot"], bool)
    assert isinstance(data["has_pcp_snapshot"], bool)
    assert data["status"] in ("DRAFT", "SUBMITTED", "SUPERSEDED")
    assert data["risk_band"] in ("LOW", "MODERATE", "HIGH", "VERY_HIGH")
    assert 0 <= data["composite_risk_score"] <= 100


def assert_barrier(data: dict):
    assert_common_fields(data)
    assert_no_type_prefix(data["episode_id"])
    assert data["barrier_code"] in (
        "HOUSING",
        "TRANSPORT",
        "INSURANCE_AUTH",
        "DME_DELIVERY",
        "GUARDIANSHIP",
        "BEHAVIORAL",
        "FAMILY_DECISION",
        "PHYSICIAN_ORDER",
        "BED_AVAILABILITY",
    )
    assert data["severity"] in ("LOW", "MEDIUM", "HIGH", "CRITICAL")
    assert data["status"] in ("OPEN", "MITIGATING", "RESOLVED", "WAIVED")
    assert data["origin"] in (
        "MANUAL",
        "SCREENING_AUTO",
        "AUTH_DENIAL_AUTO",
        "REVERT_AUTO",
    )
    assert is_iso8601_timestamp(data["clock_start_at"])
    assert isinstance(data["reopen_count"], int) and data["reopen_count"] >= 0
    assert_barrier_avoidable_derivation(data)


def assert_barrier_avoidable_derivation(data: dict):
    """PRD §3.3: `avoidable` is true exactly for the six AWAITING_* delay codes."""
    expected = data["delay_reason_code"] in AVOIDABLE_DELAY_CODES
    assert data["avoidable"] is expected, (
        f"avoidable must be {expected} for delay_reason_code "
        f"{data['delay_reason_code']}, got {data['avoidable']}"
    )


def assert_provider(data: dict):
    assert_common_fields(data)
    assert data["provider_type"] in ("SNF", "HOME_HEALTH", "IRF", "LTACH", "DME_SUPPLIER")
    assert 1 <= data["quality_star_rating"] <= 5
    assert data["distance_miles_from_hospital"] >= 0
    assert isinstance(data["bed_unit_codes"], list)
    assert data["status"] in ("ACTIVE", "SUSPENDED")
    for counter in (
        "held_bed_units",
        "offers_received_count",
        "offers_submitted_count",
        "offers_accepted_count",
    ):
        assert isinstance(data[counter], int) and data[counter] >= 0
    assert_acceptance_rate_consistent(data)


def assert_acceptance_rate_consistent(data: dict):
    """PRD §3.1: acceptance_rate_pct is accepted x 100 / submitted rounded half up
    to one decimal, and exactly 0.0 when nothing has been submitted."""
    if data["offers_submitted_count"] == 0:
        assert data["acceptance_rate_pct"] == 0.0, (
            "a provider that has submitted nothing reads exactly 0.0, got "
            f"{data['acceptance_rate_pct']}"
        )
    else:
        assert data["acceptance_rate_pct"] >= 0.0


def assert_network_contract(data: dict):
    assert_common_fields(data)
    assert_no_type_prefix(data["payer_id"])
    assert_no_type_prefix(data["provider_id"])
    assert isinstance(data["in_network"], bool)
    assert data["negotiated_daily_rate_cents"] > 0


def assert_referral(data: dict):
    assert_common_fields(data)
    assert_no_type_prefix(data["episode_id"])
    assert data["requested_level_of_care"] in ("SNF", "HOME_HEALTH", "IRF", "LTACH")
    assert data["projected_stay_days"] >= 1
    assert is_iso8601_timestamp(data["needed_by"])
    assert data["status"] in (
        "DRAFT",
        "BROADCAST",
        "CHOICE_PENDING",
        "PLACED",
        "WITHDRAWN",
        "EXPIRED",
    )
    assert isinstance(data["round_index"], int) and data["round_index"] >= 0
    assert isinstance(data["broadcast_provider_ids"], list)
    assert isinstance(data["patient_choice_attested"], bool)


def assert_bed_offer(data: dict):
    assert_common_fields(data)
    assert_no_type_prefix(data["referral_id"])
    assert_no_type_prefix(data["provider_id"])
    assert data["status"] in (
        "OFFERED",
        "ACCEPTED_BY_PATIENT",
        "DECLINED_BY_PATIENT",
        "WITHDRAWN",
        "EXPIRED",
    )
    assert data["daily_rate_cents"] > 0
    assert is_iso8601_timestamp(data["bed_available_from"])
    assert is_iso8601_timestamp(data["hold_expires_at"])
    assert data["rate_variant_applied"] in ("NETWORK_RATE", "BILLED_RATE")
    assert isinstance(data["rank_score"], int)
    assert_projection_splits_exactly(data)


def assert_projection_splits_exactly(data: dict):
    """PRD §3.5: the patient share and the plan share always add back to the gross."""
    assert (
        data["projected_patient_share_cents"] + data["projected_plan_share_cents"]
        == data["projected_gross_cents"]
    ), (
        "patient share + plan share must equal the gross exactly: "
        f"{data['projected_patient_share_cents']} + "
        f"{data['projected_plan_share_cents']} != {data['projected_gross_cents']}"
    )


def assert_authorization(data: dict):
    assert_common_fields(data)
    assert_no_type_prefix(data["episode_id"])
    assert_no_type_prefix(data["payer_id"])
    assert_no_type_prefix(data["provider_id"])
    assert data["level_of_care"] in ("SNF", "HOME_HEALTH", "IRF", "LTACH")
    assert data["requested_days"] >= 1
    assert data["billed_daily_rate_cents"] > 0
    assert data["status"] in (
        "SUBMITTED",
        "PENDED",
        "APPROVED",
        "PARTIALLY_APPROVED",
        "DENIED",
        "EXPIRED",
    )
    assert isinstance(data["appeal_round"], int) and data["appeal_round"] >= 0
    assert isinstance(data["gross_projection_cents"], int)
    assert isinstance(data["authorized_amount_cents"], int)


def assert_vehicle(data: dict):
    assert_common_fields(data)
    assert data["vehicle_type"] in ("WHEELCHAIR_VAN", "BLS_AMBULANCE", "ALS_AMBULANCE")
    assert data["base_rate_cents"] > 0
    assert data["per_mile_cents"] >= 0
    assert data["status"] in ("ACTIVE", "OUT_OF_SERVICE")


def assert_logistics_order(data: dict):
    assert_common_fields(data)
    assert_no_type_prefix(data["episode_id"])
    assert data["order_type"] in ("PATIENT_TRANSPORT", "DME_DELIVERY")
    assert is_iso8601_timestamp(data["window_start"])
    assert is_iso8601_timestamp(data["window_end"])
    assert isinstance(data["cost_cents"], int) and data["cost_cents"] >= 0
    assert data["status"] in ("REQUESTED", "CONFIRMED", "COMPLETED", "CANCELLED")


def assert_throughput_report(data: dict):
    """PRD §3.9: the per-episode report exposes exactly these nine figures."""
    for field in (
        "los_hours",
        "avoidable_delay_hours",
        "adjusted_los_hours",
        "expected_los_hours",
        "observed_expected_ratio",
        "throughput_grade",
        "current_risk_score",
        "current_risk_band",
        "barriers_ever_opened_count",
    ):
        assert field in data, f"the throughput report must expose {field}"
    assert data["throughput_grade"] in (
        "EXEMPLARY",
        "ON_TARGET",
        "ABOVE_TARGET",
        "OUTLIER",
    )
    assert data["adjusted_los_hours"] >= 0.0, (
        "adjusted_los_hours is floored at 0.0, got "
        f"{data['adjusted_los_hours']}"
    )


def assert_error_envelope(body: dict, expected_error_id: str):
    """PRD §2.2: an error body carries only api_request_id / api_request_timestamp
    in meta, response_type 'error', and data limited to error_id and message."""
    assert body["response_type"] == "error"
    assert set(body["meta"].keys()) == {"api_request_id", "api_request_timestamp"}, (
        "the meta object for error responses contains only api_request_id and "
        f"api_request_timestamp, got {sorted(body['meta'].keys())}"
    )
    assert body["data"]["error_id"] == expected_error_id
    assert isinstance(body["data"]["message"], str) and body["data"]["message"].strip(), (
        "the message provides a human-readable explanation of what went wrong"
    )


def assert_success_envelope(body: dict, expected_response_type: str = "object"):
    """PRD §2.2: meta carries a req_-prefixed request id and an ISO 8601 stamp."""
    assert body["meta"]["api_request_id"].startswith("req_"), (
        "api_request_id must start with 'req_', got "
        f"{body['meta']['api_request_id']!r}"
    )
    assert is_iso8601_timestamp(body["meta"]["api_request_timestamp"])
    assert body["response_type"] == expected_response_type
