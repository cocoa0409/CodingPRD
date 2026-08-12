"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import (
    is_valid_uuid, is_iso8601_timestamp,
)


def _assert_common(data: dict, entity: str, with_version: bool = True):
    assert isinstance(data, dict), f"{entity}: expected object, got {type(data)}"
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"{entity}.created_at must be ISO 8601"
    if with_version:
        assert is_iso8601_timestamp(data.get("updated_at", "")), f"{entity}.updated_at must be ISO 8601"
        assert isinstance(data.get("version"), int), f"{entity}.version must be an integer"


def assert_provider(data: dict):
    _assert_common(data, "Provider")
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert isinstance(data["tin"], str) and data["tin"]
    assert isinstance(data["npi"], str) and data["npi"]
    assert isinstance(data["locality_code"], str) and data["locality_code"]
    assert data["provider_status"] in ["ACTIVE", "SUSPENDED"]


def assert_network(data: dict):
    _assert_common(data, "Network")
    assert isinstance(data["name"], str) and data["name"]
    assert data["line_of_business"] in [
        "COMMERCIAL_HMO", "COMMERCIAL_PPO", "MEDICARE_ADVANTAGE", "MEDICAID",
    ]
    assert data["network_status"] in ["ACTIVE", "RETIRED"]


def assert_benchmark(data: dict):
    _assert_common(data, "MedicareBenchmark")
    assert isinstance(data["benchmark_year"], int)
    assert isinstance(data["locality_code"], str) and data["locality_code"]
    assert isinstance(data["hcpcs_code"], str) and data["hcpcs_code"]
    assert isinstance(data["benchmark_amount_cents"], int)
    assert data["benchmark_status"] in ["DRAFT", "PUBLISHED"]


def assert_rate_parity_rule(data: dict):
    _assert_common(data, "RateParityRule")
    assert data["line_of_business_a"] in [
        "COMMERCIAL_HMO", "COMMERCIAL_PPO", "MEDICARE_ADVANTAGE", "MEDICAID",
    ]
    assert data["line_of_business_b"] in [
        "COMMERCIAL_HMO", "COMMERCIAL_PPO", "MEDICARE_ADVANTAGE", "MEDICAID",
    ]
    assert isinstance(data["band_bps"], int)
    assert data["rule_status"] in ["ACTIVE", "RETIRED"]


def assert_contract(data: dict):
    _assert_common(data, "Contract")
    assert is_valid_uuid(data.get("provider_id", "")), "Contract.provider_id must be a UUID"
    assert is_valid_uuid(data.get("network_id", "")), "Contract.network_id must be a UUID"
    assert isinstance(data["base_effective_date"], str)
    assert isinstance(data["term_months"], int)
    assert isinstance(data["escalator_bps"], int)
    assert data["escalator_mode"] in ["ANNIVERSARY", "CALENDAR"]
    assert isinstance(data["auto_renew"], bool)
    assert data["contract_status"] in [
        "DRAFT", "IN_NEGOTIATION", "PENDING_SIGNATURE", "SIGNED",
        "IN_CONFIGURATION", "IN_TESTING", "READY_FOR_GO_LIVE",
        "ACTIVE", "TERMINATION_NOTICE", "TERMINATED",
    ]
    assert isinstance(data["negotiation_round"], int)


def assert_contract_version(data: dict):
    _assert_common(data, "ContractVersion")
    assert is_valid_uuid(data.get("contract_id", "")), "ContractVersion.contract_id must be a UUID"
    assert isinstance(data["version_number"], int)
    assert isinstance(data["effective_date"], str)
    assert data["version_status"] in [
        "DRAFT", "LOADED", "VALIDATED", "REJECTED", "EFFECTIVE", "SUPERSEDED",
    ]


def assert_fee_schedule_entry(data: dict):
    _assert_common(data, "FeeScheduleEntry")
    assert is_valid_uuid(data.get("contract_version_id", "")), "FeeScheduleEntry.contract_version_id must be a UUID"
    assert isinstance(data["hcpcs_code"], str) and data["hcpcs_code"]
    assert isinstance(data["service_category"], str) and data["service_category"]
    assert data["rate_type"] in ["PERCENT_OF_MEDICARE", "FLAT_RATE", "PER_DIEM", "CASE_RATE"]
    assert data["benchmark_lookup_mode"] in ["STRICT", "PROVISIONAL"]
    assert data["entry_status"] in ["STAGED", "MAPPED", "LOCKED"]


def assert_carve_out(data: dict):
    _assert_common(data, "CarveOut")
    assert is_valid_uuid(data.get("contract_version_id", "")), "CarveOut.contract_version_id must be a UUID"
    assert isinstance(data["service_category"], str) and data["service_category"]
    assert data["override_type"] in ["FLAT_RATE", "PCT_OF_MEDICARE", "EXCLUDE"]
    assert isinstance(data["start_date"], str)
    assert isinstance(data["end_date"], str)
    assert isinstance(data["priority_rank"], int)


def assert_simulation_batch(data: dict):
    _assert_common(data, "SimulationBatch")
    assert is_valid_uuid(data.get("contract_version_id", "")), "SimulationBatch.contract_version_id must be a UUID"
    assert isinstance(data["label"], str)
    assert data["batch_status"] in ["OPEN", "PRICED", "PASSED", "FAILED", "CLOSED"]
    for f in ("total_claims", "matched_claims", "mismatched_claims",
              "excluded_claims", "pending_claims", "total_priced_cents"):
        assert isinstance(data[f], int), f"SimulationBatch.{f} must be int"


def assert_simulation_claim(data: dict):
    _assert_common(data, "SimulationClaim")
    assert is_valid_uuid(data.get("simulation_batch_id", "")), "SimulationClaim.simulation_batch_id must be a UUID"
    assert isinstance(data["hcpcs_code"], str) and data["hcpcs_code"]
    assert isinstance(data["service_category"], str) and data["service_category"]
    assert isinstance(data["service_date"], str)
    assert isinstance(data["billed_cents"], int)
    assert isinstance(data["expected_allowed_cents"], int)
    assert data["claim_outcome"] in ["PENDING", "MATCH", "MISMATCH", "EXCLUDED"]


def assert_paid_claim_snapshot(data: dict):
    _assert_common(data, "PaidClaimSnapshot")
    assert is_valid_uuid(data.get("contract_id", "")), "PaidClaimSnapshot.contract_id must be a UUID"
    assert isinstance(data["claim_number"], str) and data["claim_number"]
    assert isinstance(data["hcpcs_code"], str) and data["hcpcs_code"]
    assert isinstance(data["service_category"], str)
    assert isinstance(data["service_date"], str)
    assert isinstance(data["billed_cents"], int)
    assert isinstance(data["paid_cents"], int)
    assert data["snapshot_status"] in ["OPEN", "ADJUSTED"]


def assert_retro_run(data: dict):
    _assert_common(data, "RetroAdjustmentRun")
    assert is_valid_uuid(data.get("contract_version_id", "")), "RetroAdjustmentRun.contract_version_id must be a UUID"
    assert data["run_status"] in ["CREATED", "COMPUTED", "FINALIZED", "SETTLED", "VOID"]
    for f in ("adjustment_count", "total_underpaid_cents",
              "total_overpaid_cents", "net_delta_cents"):
        assert isinstance(data[f], int), f"RetroAdjustmentRun.{f} must be int"


def assert_retro_adjustment(data: dict):
    _assert_common(data, "RetroAdjustment")
    assert is_valid_uuid(data.get("retro_run_id", "")), "RetroAdjustment.retro_run_id must be a UUID"
    assert is_valid_uuid(data.get("paid_claim_id", "")), "RetroAdjustment.paid_claim_id must be a UUID"
    assert isinstance(data["service_date"], str)
    assert isinstance(data["original_paid_cents"], int)
    assert data["adjustment_status"] in [
        "PROPOSED", "APPROVED", "REJECTED", "PAID", "RECOVERED", "VOIDED",
    ]


def assert_termination_notice(data: dict):
    _assert_common(data, "TerminationNotice")
    assert is_valid_uuid(data.get("contract_id", "")), "TerminationNotice.contract_id must be a UUID"
    assert isinstance(data["notice_date"], str)
    assert isinstance(data["termination_date"], str)
    assert isinstance(data["reason"], str)
    assert data["notice_status"] in ["DRAFT", "ISSUED", "EFFECTIVE", "RESCINDED"]


def assert_continuity_case(data: dict):
    _assert_common(data, "ContinuityOfCareCase")
    assert is_valid_uuid(data.get("termination_notice_id", "")), "ContinuityOfCareCase.termination_notice_id must be a UUID"
    assert isinstance(data["member_ref"], str)
    assert data["condition_category"] in [
        "INPATIENT_CONFINEMENT", "PREGNANCY", "DIALYSIS",
        "ONCOLOGY_TREATMENT", "TRANSPLANT_WORKUP",
    ]
    assert isinstance(data["treatment_end_date"], str)
    assert data["case_status"] in [
        "IDENTIFIED", "NOTIFIED", "ACTIVE_COVERAGE",
        "COMPLETED", "EXPIRED", "CLOSED_RESCINDED",
    ]


def assert_audit_event(data: dict):
    """Append-only: id + created_at only, no updated_at/version."""
    assert isinstance(data, dict), "AuditEvent: expected object"
    assert is_valid_uuid(data.get("id", "")), "AuditEvent.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "AuditEvent.created_at must be ISO 8601"
    assert isinstance(data.get("contract_id"), str)
    assert isinstance(data.get("event_type"), str) and data["event_type"]
    assert isinstance(data.get("actor_role"), str)
    assert isinstance(data.get("actor_id"), str)
    assert isinstance(data.get("occurred_at"), str)
    assert "version" not in data, "AuditEvent must not carry version"
    assert "updated_at" not in data, "AuditEvent must not carry updated_at"


def assert_batch_counter_partition(data: dict):
    """Batch counters must always partition total_claims."""
    total = data["total_claims"]
    summed = (data["matched_claims"] + data["mismatched_claims"]
              + data["excluded_claims"] + data["pending_claims"])
    assert total == summed, (
        f"Batch counter partition violated: total={total} "
        f"but m+mm+x+p={summed}"
    )
