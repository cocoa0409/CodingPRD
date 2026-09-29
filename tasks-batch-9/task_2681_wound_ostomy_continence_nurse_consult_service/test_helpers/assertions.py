"""Resource assertions and domain invariant checkers for the WOC Consult Service."""
from datetime import datetime, timezone

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    AnatomicLocation,
    BillingStatus,
    CaseClassification,
    CaseStatus,
    CertificationStatus,
    ConsultStatus,
    ConsultType,
    FormularyTier,
    FulfillmentStatus,
    ObservationClassification,
    ObservedStage,
    PatientStatus,
    PlanStatus,
    ProductCategory,
    ProductStatus,
    ProtocolStatus,
    ReportedStage,
    RoundType,
    SurfaceClass,
    SurfaceStatus,
    SurveyPosture,
    SurveyRoundStatus,
    ValidationStatus,
)


def _members(enum_cls) -> list:
    return [member.value for member in enum_cls]


def assert_common_fields(data: dict) -> None:
    """PRD §2.4 — every resource carries a server-minted UUID `id` and a
    `created_at`; most also carry `updated_at` and an integer `version`."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID string, got {data.get('id')!r}"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    assert is_iso8601_timestamp(
        data.get("updated_at", "")
    ), f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, "version starts at 1"


def assert_audit_record_fields(data: dict) -> None:
    """PRD §2.4 — the survey observation carries only `id` and `created_at`."""
    assert is_valid_uuid(data.get("id", "")), "id must be a UUID string"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"


def assert_unit(data: dict) -> None:
    assert_common_fields(data)
    assert isinstance(data["unit_code"], str) and 2 <= len(data["unit_code"]) <= 12
    assert isinstance(data["name"], str) and 1 <= len(data["name"]) <= 120
    assert isinstance(data["bed_count"], int) and 1 <= data["bed_count"] <= 400
    for field in (
        "rental_budget_cap_cents",
        "rental_encumbered_cents",
        "rental_committed_cents",
        "rental_released_cents",
        "rental_available_cents",
        "open_hapi_rca_count",
        "disputed_staging_count",
    ):
        assert isinstance(data[field], int), f"{field} must be an integer"
        assert data[field] >= 0, f"{field} must never be negative"
    assert data["survey_posture"] in _members(SurveyPosture)
    assert_unit_ledger_invariants(data)


def assert_unit_ledger_invariants(data: dict) -> None:
    """PRD §3.1 — `rental_available_cents` is always the cap less the encumbered
    and committed sums, and `survey_posture` is always re-derived from
    `open_hapi_rca_count` on the three-rung ladder."""
    expected_available = (
        data["rental_budget_cap_cents"]
        - data["rental_encumbered_cents"]
        - data["rental_committed_cents"]
    )
    assert data["rental_available_cents"] == expected_available, (
        "rental_available_cents must equal rental_budget_cap_cents less "
        f"rental_encumbered_cents less rental_committed_cents; expected "
        f"{expected_available}, got {data['rental_available_cents']}"
    )
    assert data["rental_available_cents"] >= 0, "rental_available_cents must never be negative"
    count = data["open_hapi_rca_count"]
    expected_posture = "FROZEN" if count >= 4 else ("RESTRICTED" if count >= 2 else "OPEN")
    assert data["survey_posture"] == expected_posture, (
        f"survey_posture must be {expected_posture} at open_hapi_rca_count={count}, "
        f"got {data['survey_posture']}"
    )


def assert_patient(data: dict) -> None:
    assert_common_fields(data)
    assert isinstance(data["mrn"], str) and 6 <= len(data["mrn"]) <= 16
    assert is_valid_uuid(data["unit_id"])
    assert is_iso8601_timestamp(data["admitted_at"])
    assert data["status"] in _members(PatientStatus)
    assert isinstance(data["comorbidity_count"], int) and 0 <= data["comorbidity_count"] <= 10
    assert isinstance(data["device_related_risk"], bool)
    assert isinstance(data["ostomy_present"], bool)
    assert isinstance(data["poa_skin_assessment_documented"], bool)
    assert isinstance(data["pending_outpatient_followup_count"], int)
    assert data["pending_outpatient_followup_count"] >= 0


def assert_woc_nurse(data: dict) -> None:
    assert_common_fields(data)
    assert isinstance(data["full_name"], str) and 1 <= len(data["full_name"]) <= 120
    assert is_valid_uuid(data["home_unit_id"])
    assert data["certification_status"] in _members(CertificationStatus)
    assert isinstance(data["ce_credits"], int) and 0 <= data["ce_credits"] <= 200
    assert isinstance(data["competency_signoff_count"], int)
    assert isinstance(data["mentored_consult_count"], int)
    assert isinstance(data["active_consult_load"], int)
    assert isinstance(data["max_consult_load"], int)
    assert_nurse_load_invariants(data)


def assert_nurse_load_invariants(data: dict) -> None:
    """PRD §3.3 — `max_consult_load` is derived solely from
    `certification_status`, and `active_consult_load` may never exceed it or
    fall below 0."""
    expected_max = {"CERTIFIED": 8, "CANDIDATE": 3, "TRAINEE": 0, "LAPSED": 0}[
        data["certification_status"]
    ]
    assert data["max_consult_load"] == expected_max, (
        f"max_consult_load must be {expected_max} for {data['certification_status']}, "
        f"got {data['max_consult_load']}"
    )
    assert data["active_consult_load"] >= 0, "active_consult_load must never fall below 0"


def assert_consult_request(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["patient_id"])
    assert is_valid_uuid(data["requesting_unit_id"])
    assert data["consult_type"] in _members(ConsultType)
    assert data["reported_stage"] in _members(ReportedStage)
    assert isinstance(data["clinical_note"], str) and 1 <= len(data["clinical_note"]) <= 2000
    assert data["status"] in _members(ConsultStatus)
    assert isinstance(data["revision_count"], int) and 0 <= data["revision_count"] <= 2
    assert isinstance(data["escalation_count"], int) and data["escalation_count"] >= 0
    assert isinstance(data["protocol_hold"], bool)
    if data.get("acuity_score") is not None:
        assert_one_decimal_place(data["acuity_score"])
        assert 0.0 <= data["acuity_score"] <= 100.0
    if data.get("priority_band") is not None:
        assert data["priority_band"] in ("P1", "P2", "P3")
    if data.get("acuity_variant") is not None:
        assert data["acuity_variant"] in ("INTAKE_PROVISIONAL", "ASSESSED_FINAL")


def assert_band_matches_acuity(data: dict) -> None:
    """PRD §3.4 — `P1` when the score is 70.0 or higher, otherwise `P2` when it
    is 40.0 or higher, otherwise `P3`."""
    score = data["acuity_score"]
    expected = "P1" if score >= 70.0 else ("P2" if score >= 40.0 else "P3")
    assert data["priority_band"] == expected, (
        f"priority_band must be {expected} at acuity_score {score}, "
        f"got {data['priority_band']}"
    )


def assert_skin_assessment(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["consult_request_id"])
    assert is_valid_uuid(data["patient_id"])
    assert is_valid_uuid(data["staged_by_nurse_id"])
    assert data["anatomic_location"] in _members(AnatomicLocation)
    assert data["observed_stage"] in _members(ObservedStage)
    assert 0 <= float(data["measured_area_cm2"]) <= 500
    assert is_iso8601_timestamp(data["observed_at"])
    assert isinstance(data["present_on_admission_claimed"], bool)
    assert data["validation_status"] in _members(ValidationStatus)
    assert isinstance(data["restage_count"], int) and data["restage_count"] >= 0
    if data.get("poa_determination") is not None:
        assert data["poa_determination"] in ("POA", "HAPI", "INDETERMINATE")
    if data.get("confirmed_stage") is not None:
        assert data["confirmed_stage"] in _members(ObservedStage)


def assert_pressure_injury_case(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["patient_id"])
    assert is_valid_uuid(data["unit_id"])
    assert is_valid_uuid(data["skin_assessment_id"])
    assert data["classification"] in _members(CaseClassification)
    assert data["status"] in _members(CaseStatus)
    assert isinstance(data["contributing_factors"], list)


def assert_survey_round(data: dict) -> None:
    assert_common_fields(data)
    assert data["round_type"] in _members(RoundType)
    assert is_iso8601_timestamp(data["window_start"])
    assert is_iso8601_timestamp(data["window_end"])
    assert isinstance(data["participating_unit_ids"], list)
    assert 1 <= len(data["participating_unit_ids"]) <= 20
    assert data["status"] in _members(SurveyRoundStatus)
    assert isinstance(data["observation_count"], int) and data["observation_count"] >= 0


def assert_survey_observation(data: dict) -> None:
    assert_audit_record_fields(data)
    assert "updated_at" not in data, (
        "the survey observation is an immutable audit record and has no updated_at"
    )
    assert "version" not in data, (
        "the survey observation is an immutable audit record and has no version"
    )
    assert is_valid_uuid(data["survey_round_id"])
    assert is_valid_uuid(data["unit_id"])
    assert is_valid_uuid(data["patient_id"])
    assert is_valid_uuid(data["observer_nurse_id"])
    assert is_iso8601_timestamp(data["observed_at"])
    assert isinstance(data["injury_present"], bool)
    assert data["classification"] in _members(ObservationClassification)
    assert isinstance(data["at_risk"], bool)


def assert_support_surface(data: dict) -> None:
    assert_common_fields(data)
    assert isinstance(data["asset_tag"], str) and 3 <= len(data["asset_tag"]) <= 24
    assert data["surface_class"] in _members(SurfaceClass)
    assert isinstance(data["daily_rate_cents"], int)
    assert 1 <= data["daily_rate_cents"] <= 2000000
    assert isinstance(data["vendor_name"], str) and 1 <= len(data["vendor_name"]) <= 120
    assert data["status"] in _members(SurfaceStatus)
    if data.get("occupied_until") is None:
        assert data.get("available_from") is None, (
            "available_from is null exactly while occupied_until is null"
        )


def assert_support_surface_order(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["patient_id"])
    assert is_valid_uuid(data["unit_id"])
    assert is_valid_uuid(data["support_surface_id"])
    assert is_iso8601_timestamp(data["rental_start"])
    assert is_iso8601_timestamp(data["rental_end"])
    assert isinstance(data["authorized_days"], int) and 1 <= data["authorized_days"] <= 120
    assert data["fulfillment_status"] in _members(FulfillmentStatus)
    assert data["billing_status"] in _members(BillingStatus)
    assert isinstance(data["requires_director_override"], bool)
    assert_order_cost_invariants(data)


def assert_order_cost_invariants(data: dict) -> None:
    """PRD §3.8 — `authorized_cost_cents` is exactly `projected_cost_cents` plus
    `vendor_service_fee_cents`, by integer addition."""
    for field in ("billable_days", "projected_cost_cents", "vendor_service_fee_cents",
                  "authorized_cost_cents"):
        assert isinstance(data[field], int), f"{field} must be an integer count"
        assert data[field] >= 0, f"{field} must not be negative"
    assert data["authorized_cost_cents"] == (
        data["projected_cost_cents"] + data["vendor_service_fee_cents"]
    ), (
        "authorized_cost_cents must equal projected_cost_cents plus "
        f"vendor_service_fee_cents; got {data['authorized_cost_cents']} vs "
        f"{data['projected_cost_cents']} + {data['vendor_service_fee_cents']}"
    )


def assert_formulary_product(data: dict) -> None:
    assert_common_fields(data)
    assert isinstance(data["sku"], str) and 3 <= len(data["sku"]) <= 24
    assert isinstance(data["name"], str) and 1 <= len(data["name"]) <= 120
    assert data["category"] in _members(ProductCategory)
    assert isinstance(data["unit_cost_cents"], int)
    assert 0 <= data["unit_cost_cents"] <= 1000000
    assert data["formulary_tier"] in _members(FormularyTier)
    assert data["status"] in _members(ProductStatus)


def assert_dressing_protocol(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["consult_request_id"])
    assert is_valid_uuid(data["formulary_product_id"])
    assert isinstance(data["change_frequency_hours"], int)
    assert 8 <= data["change_frequency_hours"] <= 168
    assert isinstance(data["units_per_change"], int) and 1 <= data["units_per_change"] <= 20
    assert isinstance(data["changes_per_week"], int) and data["changes_per_week"] >= 1
    assert isinstance(data["weekly_cost_cents"], int) and data["weekly_cost_cents"] >= 0
    assert data["status"] in _members(ProtocolStatus)


def assert_ostomy_education_plan(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["consult_request_id"])
    assert is_valid_uuid(data["patient_id"])
    assert isinstance(data["sessions_completed"], int) and data["sessions_completed"] >= 0
    assert data["supply_transition_status"] in ("PENDING", "TRANSITIONED")
    assert data["status"] in _members(PlanStatus)
    if data.get("teach_back_score") is not None:
        assert 0 <= data["teach_back_score"] <= 100


def assert_one_decimal_place(value) -> None:
    """PRD §2.8 — consult acuity is carried to 1 decimal place."""
    assert value == round(float(value), 1), (
        f"expected a value carried to one decimal place, got {value!r}"
    )


def assert_two_decimal_places(value) -> None:
    """PRD §2.8 — survey rates and the certification score are carried to 2
    decimal places."""
    assert value == round(float(value), 2), (
        f"expected a value carried to two decimal places, got {value!r}"
    )


def assert_money_conserved(unit: dict, expected_authorized_total: int) -> None:
    """PRD §3.8 — what leaves `rental_encumbered_cents` always arrives either in
    `rental_committed_cents` or in `rental_released_cents`."""
    settled = unit["rental_committed_cents"] + unit["rental_released_cents"]
    assert settled == expected_authorized_total, (
        "rental_committed_cents plus rental_released_cents must account for the "
        f"whole authorized amount {expected_authorized_total}; got {settled}"
    )


def as_instant(raw):
    """Parse an ISO 8601 UTC instant so two spellings compare equal.

    PRD §2.4 pins a three-fractional-digit rendering for `created_at` and
    `updated_at`, and says only "an ISO 8601 UTC instant" about the business
    datetimes — a deadline, a window bound or an occupation mark may therefore
    come back with or without fractional digits. Every comparison of such a
    field goes through this parser so the assertion is about the moment and not
    about its spelling. `None` passes straight through.
    """
    if raw is None:
        return None
    text = str(raw).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def assert_envelope_meta(response) -> None:
    """PRD §2.2 — `api_request_id` starts with `req_` and the timestamp is an
    ISO 8601 UTC instant with three fractional digits."""
    body = response.json()
    meta = body["meta"]
    assert str(meta["api_request_id"]).startswith("req_"), (
        f"api_request_id must start with req_, got {meta['api_request_id']!r}"
    )
    assert is_iso8601_timestamp(meta["api_request_timestamp"])
