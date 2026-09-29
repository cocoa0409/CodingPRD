"""Entity assertions and domain invariant checkers."""

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

AFFILIATION_STATUSES = ["DRAFT", "DILIGENCE", "SIGNED", "CLOSED"]
EARNOUT_MEASUREMENT_STATES = ["NOT_OPEN", "OPEN", "SUSPENDED"]
PRACTICE_AFFILIATION_STATUSES = ["PENDING", "AFFILIATED"]
INTEGRATION_POSTURES = [
    "PRE_CLOSE",
    "FROZEN",
    "RESTRICTED",
    "STABILIZING",
    "INTEGRATED",
]
STAFFING_MODEL_STATES = ["LEGACY", "STANDARDIZED"]
DOCTOR_SPECIALTIES = [
    "GENERAL",
    "ENDODONTICS",
    "ORTHODONTICS",
    "ORAL_SURGERY",
    "PERIODONTICS",
]
EMPLOYMENT_STATUSES = ["OFFERED", "ACTIVE", "LAPSED", "SEPARATED"]
CREDENTIALING_STATUSES = ["PENDING", "SUBMITTED", "APPROVED", "DENIED"]
RECORDS_CUSTODY_STATES = ["HELD_BY_PRACTICE", "TRANSFER_PENDING", "TRANSFERRED"]
NON_COMPETE_ENFORCEMENT_STATES = ["NOT_APPLICABLE", "PENDING", "ENFORCED"]
COMP_MODELS = ["MONTHLY_MIN_GUARANTEE", "ANNUAL_TRUE_UP"]
SERVICE_AGREEMENT_STATUSES = ["DRAFT", "LEGAL_REVIEW", "EFFECTIVE"]
FEE_MODELS = ["PCT_OF_COLLECTIONS", "FIXED_MONTHLY"]
NON_CLINICAL_SERVICE_DOMAINS = [
    "BILLING",
    "HR",
    "PROCUREMENT",
    "IT",
    "MARKETING",
    "FACILITIES",
    "CREDENTIALING",
]
CLINICAL_SERVICE_DOMAINS = ["TREATMENT_PLANNING", "CLINICAL_SUPERVISION", "DIAGNOSIS"]
MIGRATION_BATCH_STATUSES = [
    "STAGED",
    "SCHEDULED",
    "VALIDATED",
    "QUARANTINED",
    "RECONCILED",
    "HELD",
    "SUPERSEDED",
]
PAYER_CONTRACT_TRANSITION_STATES = [
    "LEGACY",
    "PENDING_CREDENTIALING",
    "DSO_SCHEDULE_ACTIVE",
]
PAYER_ENROLLMENT_STATUSES = [
    "NOT_STARTED",
    "SUBMITTED",
    "APPROVED",
    "DENIED",
    "SUSPENDED",
]
EARNOUT_TRANCHE_STATUSES = ["PROJECTED", "RESERVED", "SETTLED", "CLAWED_BACK"]
EARNOUT_VARIANTS = ["PROVISIONAL", "FINAL"]
VENDOR_CATEGORIES = ["SUPPLY", "LAB"]
SUPPLY_EXCEPTION_STATUSES = ["REQUESTED", "APPROVED", "DENIED"]
VENDOR_CONSOLIDATION_STATUSES = ["PLANNED", "FINALIZED"]
QUALITY_REVIEW_STATUSES = [
    "OPEN",
    "CLOSED_NO_FINDINGS",
    "CLOSED_WITH_PLAN",
    "ESCALATED",
]


def _assert_common_fields(data: dict, label: str):
    """Every primary resource carries id, created_at, updated_at and version."""
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a UUID"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"{label}.created_at must be ISO 8601 UTC"
    assert is_iso8601_timestamp(
        data.get("updated_at", "")
    ), f"{label}.updated_at must be ISO 8601 UTC"
    assert isinstance(data.get("version"), int), f"{label}.version must be an integer"
    assert data["version"] >= 1, f"{label}.version must start at or above 1"


def _assert_write_once_fields(data: dict, label: str):
    """Scope lines and priced procedures carry only id and created_at."""
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a UUID"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"{label}.created_at must be ISO 8601 UTC"
    assert "updated_at" not in data, f"{label} must not carry updated_at"
    assert "version" not in data, f"{label} must not carry version"


def assert_affiliation(data: dict):
    _assert_common_fields(data, "Affiliation")
    assert isinstance(data["seller_group_name"], str) and data["seller_group_name"]
    assert data["purchase_price_cents"] >= 1
    assert data["earnout_pool_cents"] >= 0
    assert data["baseline_ebitda_cents"] >= 1
    assert data["baseline_net_collections_cents"] >= 1
    assert isinstance(data["post_close_doctor_term_months"], int)
    assert data["status"] in AFFILIATION_STATUSES
    assert data["earnout_measurement_state"] in EARNOUT_MEASUREMENT_STATES
    assert data["repricing_round"] >= 0
    assert data["practice_count"] >= 0
    assert_earnout_pool_ledger(data)


def assert_earnout_pool_ledger(data: dict):
    """PRD §2.8 — the pool equals unallocated plus reserved plus settled."""
    total = (
        data["earnout_unallocated_cents"]
        + data["earnout_reserved_cents"]
        + data["earnout_settled_cents"]
    )
    assert total == data["earnout_pool_cents"], (
        "earn-out pool ledger must balance: "
        f"{data['earnout_unallocated_cents']} + {data['earnout_reserved_cents']} + "
        f"{data['earnout_settled_cents']} != {data['earnout_pool_cents']}"
    )
    assert (
        data["earnout_unallocated_cents"] >= 0
    ), "earnout_unallocated_cents must never be negative"


def assert_conversion_vendor(data: dict):
    _assert_common_fields(data, "ConversionVendor")
    assert isinstance(data["name"], str) and data["name"]
    assert data["max_concurrent_windows"] >= 1
    assert data["active_window_count"] >= 0


def assert_practice(data: dict):
    _assert_common_fields(data, "Practice")
    assert is_valid_uuid(data["affiliation_id"])
    assert is_valid_uuid(data["conversion_vendor_id"])
    assert isinstance(data["name"], str) and data["name"]
    assert len(data["state_code"]) == 2 and data["state_code"].isupper()
    assert data["charts_total_expected"] >= 1
    assert data["affiliation_status"] in PRACTICE_AFFILIATION_STATUSES
    assert data["integration_posture"] in INTEGRATION_POSTURES
    assert data["staffing_model_state"] in STAFFING_MODEL_STATES
    for counter in (
        "active_doctor_count",
        "charts_migrated_count",
        "pending_credentialing_count",
        "denied_enrollment_count",
        "quarantined_batch_count",
    ):
        assert data[counter] >= 0, f"Practice.{counter} must never be negative"
    assert isinstance(data["clinical_coverage_gap"], bool)
    assert_practice_posture(data)


def assert_practice_posture(data: dict):
    """PRD §2.6 — recompute the posture ladder and the coverage-gap flag."""
    if data["affiliation_status"] != "AFFILIATED":
        expected = "PRE_CLOSE"
    elif data["active_doctor_count"] == 0:
        expected = "FROZEN"
    elif data["quarantined_batch_count"] > 0 or data["denied_enrollment_count"] > 0:
        expected = "RESTRICTED"
    elif (
        data["pending_credentialing_count"] > 0
        or data["charts_migrated_count"] < data["charts_total_expected"]
    ):
        expected = "STABILIZING"
    else:
        expected = "INTEGRATED"
    assert data["integration_posture"] == expected, (
        f"Expected posture {expected} from the derivation ladder, got "
        f"{data['integration_posture']}"
    )
    assert data["clinical_coverage_gap"] is (expected == "FROZEN"), (
        "clinical_coverage_gap must be true exactly when the posture is FROZEN"
    )


def assert_doctor(data: dict):
    _assert_common_fields(data, "Doctor")
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert len(data["npi"]) == 10 and data["npi"].isdigit()
    assert isinstance(data["license_number"], str) and data["license_number"]
    assert len(data["license_state"]) == 2 and data["license_state"].isupper()
    assert data["specialty"] in DOCTOR_SPECIALTIES
    assert isinstance(data["is_seller_owner"], bool)


def assert_doctor_employment(data: dict):
    _assert_common_fields(data, "DoctorEmployment")
    assert is_valid_uuid(data["practice_id"])
    assert is_valid_uuid(data["doctor_id"])
    assert data["base_salary_monthly_cents"] >= 0
    assert 0 <= data["collections_pct_bps"] <= 5000
    assert data["comp_model"] in COMP_MODELS
    assert data["legacy_annual_comp_cents"] >= 0
    assert 0 <= data["non_compete_months"] <= 24
    assert 0 <= data["non_compete_radius_miles"] <= 15
    assert data["employment_status"] in EMPLOYMENT_STATUSES
    assert data["credentialing_status"] in CREDENTIALING_STATUSES
    assert data["records_custody_state"] in RECORDS_CUSTODY_STATES
    assert data["non_compete_enforcement_state"] in NON_COMPETE_ENFORCEMENT_STATES
    assert isinstance(data["offer_accepted"], bool)
    assert isinstance(data["is_harmonized"], bool)


def assert_service_agreement(data: dict):
    _assert_common_fields(data, "ServiceAgreement")
    assert is_valid_uuid(data["practice_id"])
    assert data["fee_model"] in FEE_MODELS
    assert data["mgmt_fee_bps"] >= 0
    assert data["status"] in SERVICE_AGREEMENT_STATUSES
    assert data["review_round"] >= 0
    assert data["scope_findings_count"] >= 0
    assert data["line_item_count"] >= 0


def assert_service_line_item(data: dict):
    _assert_write_once_fields(data, "ServiceLineItem")
    assert isinstance(data["service_code"], str) and data["service_code"]
    assert data["service_domain"] in NON_CLINICAL_SERVICE_DOMAINS
    assert data["monthly_fee_cents"] >= 0
    assert data["is_clinical"] is False, (
        "a clinical domain never survives to be stored, so is_clinical is always false"
    )


def assert_migration_batch(data: dict):
    _assert_common_fields(data, "MigrationBatch")
    assert is_valid_uuid(data["practice_id"])
    assert isinstance(data["batch_label"], str) and data["batch_label"]
    assert data["records_total"] >= 1
    assert data["status"] in MIGRATION_BATCH_STATUSES
    assert data["remediation_round"] >= 0
    assert_batch_record_ledger(data)


def assert_batch_record_ledger(data: dict):
    """PRD §2.8 — records_total equals validated plus quarantined plus pending."""
    total = (
        data["records_validated"] + data["records_quarantined"] + data["records_pending"]
    )
    assert total == data["records_total"], (
        "batch record ledger must balance: "
        f"{data['records_validated']} + {data['records_quarantined']} + "
        f"{data['records_pending']} != {data['records_total']}"
    )


def assert_payer_contract(data: dict):
    _assert_common_fields(data, "PayerContract")
    assert is_valid_uuid(data["practice_id"])
    assert isinstance(data["payer_name"], str) and data["payer_name"]
    assert data["transition_state"] in PAYER_CONTRACT_TRANSITION_STATES
    assert data["fee_schedule_item_count"] >= 0
    assert data["enrollment_open_count"] >= 0
    assert isinstance(data["erosion_override_ack"], bool)


def assert_fee_schedule_item(data: dict):
    _assert_write_once_fields(data, "FeeScheduleItem")
    assert isinstance(data["procedure_code"], str) and data["procedure_code"]
    assert data["legacy_allowed_cents"] >= 0
    assert data["dso_allowed_cents"] >= 0
    assert data["annual_volume"] >= 0
    assert isinstance(data["line_impact_cents"], int)


def assert_payer_enrollment(data: dict):
    _assert_common_fields(data, "PayerEnrollment")
    assert is_valid_uuid(data["payer_contract_id"])
    assert is_valid_uuid(data["doctor_employment_id"])
    assert data["status"] in PAYER_ENROLLMENT_STATUSES
    assert data["submission_round"] >= 0


def assert_earnout_tranche(data: dict):
    _assert_common_fields(data, "EarnoutTranche")
    assert is_valid_uuid(data["affiliation_id"])
    assert isinstance(data["period_label"], str) and data["period_label"]
    assert data["status"] in EARNOUT_TRANCHE_STATUSES
    if data.get("variant_applied") is not None:
        assert data["variant_applied"] in EARNOUT_VARIANTS
    assert data["reserved_cents"] >= 0
    assert data["awarded_cents"] >= 0
    assert data["clawed_back_cents"] >= 0


def assert_supply_preference_exception(data: dict):
    _assert_common_fields(data, "SupplyPreferenceException")
    assert is_valid_uuid(data["doctor_employment_id"])
    assert data["vendor_category"] in VENDOR_CATEGORIES
    assert isinstance(data["item_code"], str) and data["item_code"]
    assert data["annual_qty"] >= 1
    assert data["formulary_unit_cents"] >= 0
    assert data["preferred_unit_cents"] >= 0
    assert data["status"] in SUPPLY_EXCEPTION_STATUSES


def assert_vendor_consolidation(data: dict):
    _assert_common_fields(data, "VendorConsolidation")
    assert is_valid_uuid(data["practice_id"])
    assert data["vendor_category"] in VENDOR_CATEGORIES
    assert data["baseline_annual_spend_cents"] >= 0
    assert data["formulary_annual_spend_cents"] >= 0
    assert data["status"] in VENDOR_CONSOLIDATION_STATUSES
    assert data["exception_count_applied"] >= 0
    if data.get("projected_savings_cents") is not None:
        assert data["projected_savings_cents"] >= 0, (
            "projected_savings_cents is floored at zero and never reports a loss"
        )


def assert_clinical_quality_review(data: dict):
    _assert_common_fields(data, "ClinicalQualityReview")
    assert is_valid_uuid(data["doctor_employment_id"])
    assert data["charts_sampled"] >= 20
    assert data["charts_with_findings"] <= data["charts_sampled"]
    assert data["treatment_plan_overrides"] <= data["charts_sampled"]
    assert data["status"] in QUALITY_REVIEW_STATUSES
    assert 0 <= data["score_bps"] <= 10000


def assert_success_envelope_meta(meta: dict):
    """PRD §2.2 — the request id is server-generated and prefixed with req_."""
    assert str(meta.get("api_request_id", "")).startswith(
        "req_"
    ), "api_request_id must start with req_"
    assert is_iso8601_timestamp(
        meta.get("api_request_timestamp", "")
    ), "api_request_timestamp must be ISO 8601 UTC"


def assert_version_advanced(before: dict, after: dict, label: str = "resource"):
    assert after["version"] > before["version"], (
        f"{label}.version must increment on a mutation: "
        f"{before['version']} -> {after['version']}"
    )


def assert_version_unchanged(before: dict, after: dict, label: str = "resource"):
    assert after["version"] == before["version"], (
        f"{label}.version must be unchanged: "
        f"{before['version']} -> {after['version']}"
    )


def assert_credentialing_rollup(employment: dict, enrollment_statuses: list):
    """PRD §3.4 — recompute the credentialing precedence ladder."""
    if not enrollment_statuses:
        expected = "PENDING"
    elif "DENIED" in enrollment_statuses:
        expected = "DENIED"
    elif all(status == "APPROVED" for status in enrollment_statuses):
        expected = "APPROVED"
    elif "SUBMITTED" in enrollment_statuses:
        expected = "SUBMITTED"
    else:
        expected = "PENDING"
    assert employment["credentialing_status"] == expected, (
        f"Expected credentialing rollup {expected} from {enrollment_statuses}, got "
        f"{employment['credentialing_status']}"
    )


__all__ = [
    "assert_affiliation",
    "assert_earnout_pool_ledger",
    "assert_conversion_vendor",
    "assert_practice",
    "assert_practice_posture",
    "assert_doctor",
    "assert_doctor_employment",
    "assert_service_agreement",
    "assert_service_line_item",
    "assert_migration_batch",
    "assert_batch_record_ledger",
    "assert_payer_contract",
    "assert_fee_schedule_item",
    "assert_payer_enrollment",
    "assert_earnout_tranche",
    "assert_supply_preference_exception",
    "assert_vendor_consolidation",
    "assert_clinical_quality_review",
    "assert_success_envelope_meta",
    "assert_version_advanced",
    "assert_version_unchanged",
    "assert_credentialing_rollup",
    "AFFILIATION_STATUSES",
    "INTEGRATION_POSTURES",
    "EMPLOYMENT_STATUSES",
    "MIGRATION_BATCH_STATUSES",
    "PAYER_CONTRACT_TRANSITION_STATES",
    "PAYER_ENROLLMENT_STATUSES",
    "EARNOUT_TRANCHE_STATUSES",
    "NON_CLINICAL_SERVICE_DOMAINS",
    "CLINICAL_SERVICE_DOMAINS",
]
