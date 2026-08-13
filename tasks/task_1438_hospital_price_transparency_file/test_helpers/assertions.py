"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "created_at must be an ISO 8601 UTC timestamp"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        "updated_at must be an ISO 8601 UTC timestamp"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        "version must be a positive integer"


def assert_facility(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["cms_certification_number"], str)
    assert isinstance(data["bed_count"], int)
    assert data["penalty_policy"] in ("SIMPLE", "TIERED")
    assert isinstance(data["min_records_per_cycle"], int)
    assert isinstance(data["shoppable_min_entries"], int)
    assert isinstance(data["mandated_min_entries"], int)
    assert isinstance(data["shoppable_display_enabled"], bool)
    assert data["attestation_status"] in (
        "NONE", "SUBMITTED", "ACCEPTED", "REJECTED", "PLAN_SUBMITTED",
        "CLOSED", "ESCALATED")
    assert isinstance(data["penalty_accrued_cents"], int)
    assert data["penalty_accrued_cents"] >= 0


def assert_payer(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert data["payer_type"] in (
        "COMMERCIAL", "MEDICARE_ADVANTAGE", "MEDICAID_MANAGED")
    assert data["confidentiality_tier"] in ("STANDARD", "PROPRIETARY")


def assert_payer_contract(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["facility_id"])
    assert is_valid_uuid(data["payer_id"])
    assert data["confidentiality_clause"] in (
        "DISCLOSE_ALLOWED", "DERIVED_ONLY", "AGGREGATE_ONLY")
    assert isinstance(data["annual_volume"], int)
    assert data["status"] in (
        "DRAFT", "ACTIVE", "RENEGOTIATING", "TERMINATED", "EXPIRED")


def assert_service_item(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["facility_id"])
    assert isinstance(data["code"], str) and data["code"]
    assert data["code_type"] in ("CPT", "HCPCS", "MS_DRG", "REVENUE_CODE")
    assert data["service_class"] in (
        "SHOPPABLE", "ANCILLARY", "SUPPLY", "DRUG", "FACILITY_FEE")
    assert isinstance(data["gross_charge_cents"], int)
    assert data["gross_charge_cents"] >= 0
    assert data["ancillary_inclusion"] in (
        "ALWAYS_BUNDLED", "CONDITIONALLY_INCLUDED", "SEPARATELY_PRICED")
    assert isinstance(data["cms_shoppable_mandated"], bool)
    assert data["status"] in ("ACTIVE", "RETIRED")


def assert_charge_record(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["facility_id"])
    assert is_valid_uuid(data["publication_cycle_id"])
    assert is_valid_uuid(data["service_item_id"])
    assert isinstance(data["gross_charge_cents"], int)
    assert isinstance(data["discounted_cash_cents"], int)
    assert data["min_negotiated_cents"] is None or isinstance(
        data["min_negotiated_cents"], int)
    assert data["max_negotiated_cents"] is None or isinstance(
        data["max_negotiated_cents"], int)
    assert data["derived_disclosure_cents"] is None or isinstance(
        data["derived_disclosure_cents"], int)
    assert data["derivation_method"] in ("EXACT_MIN", "MIX_WEIGHTED", "NONE")
    assert data["status"] in (
        "DRAFT", "VALIDATED", "PUBLISHED", "FLAGGED", "SUPERSEDED")


def assert_rate(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["contract_id"])
    assert is_valid_uuid(data["service_item_id"])
    assert data["rate_type"] in (
        "PERCENT_OF_GROSS", "FEE_SCHEDULE_FLAT", "PERCENT_OF_MEDICARE")
    assert isinstance(data["negotiated_amount_cents"], int)
    assert data["status"] in ("DRAFT", "ACTIVE", "SUPERSEDED", "INACTIVE")


def assert_shoppable_list(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["facility_id"])
    assert isinstance(data["title"], str)
    assert isinstance(data["entries"], list)
    assert isinstance(data["entry_count"], int)
    assert data["entry_count"] == len(data["entries"])
    assert isinstance(data["mandated_entry_count"], int)
    assert data["status"] in ("DRAFT", "CERTIFIED", "PUBLISHED", "ARCHIVED")


def assert_cycle(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["facility_id"])
    assert data["cycle_type"] in ("MONTHLY", "ANNUAL")
    assert data["status"] in ("OPEN", "FROZEN", "PUBLISHED", "SUPERSEDED")
    assert data["posture"] in (
        "COLLECTING", "FREEZABLE", "AWAITING_FILE", "FILE_UNVALIDATED",
        "PUBLISHABLE", "FILE_INVALID", "CURRENT", "ARCHIVED")
    assert isinstance(data["validated_record_count"], int)
    assert isinstance(data["total_gross_cents"], int)
    assert isinstance(data["derived_rollup_cents"], int)


def assert_machine_file(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["publication_cycle_id"])
    assert data["file_format"] in ("JSON", "CSV")
    assert data["generation_status"] in (
        "SEALED", "PUBLISHED", "SUPERSEDED", "RETRACTED")
    assert data["validation_status"] in ("UNVALIDATED", "VALID", "INVALID")
    assert isinstance(data["record_count"], int)
    assert isinstance(data["summary_total_discounted_cents"], int)
    assert isinstance(data["validation_errors"], list)


def assert_discrepancy(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["publication_cycle_id"])
    assert is_valid_uuid(data["standard_charge_record_id"])
    assert data["reporter_type"] in ("CONSUMER", "PAYER", "INTERNAL")
    assert data["status"] in (
        "SUBMITTED", "CONFIRMED", "DISMISSED", "CORRECTION_PROPOSED",
        "CORRECTION_APPROVED", "CORRECTED")


def assert_cycle_aggregates_consistent(cycle: dict, records: list):
    """Domain invariant: cycle aggregates equal the sums over its records in
    VALIDATED / PUBLISHED / FLAGGED status."""
    counted = [r for r in records
               if r.get("status") in ("VALIDATED", "PUBLISHED", "FLAGGED")]
    assert cycle["validated_record_count"] == len(counted), (
        f"validated_record_count {cycle['validated_record_count']} != "
        f"{len(counted)} counted records")
    assert cycle["total_gross_cents"] == sum(
        r["gross_charge_cents"] for r in counted)
    assert cycle["derived_rollup_cents"] == sum(
        (r["derived_disclosure_cents"] or 0) for r in counted)
