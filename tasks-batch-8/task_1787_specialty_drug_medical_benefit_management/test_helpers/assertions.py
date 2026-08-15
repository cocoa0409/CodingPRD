"""Entity assertions and domain invariant checkers (PRD §2.2, §2.5, §3)."""
import re

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

# PRD §2.5: timestamps are ISO 8601 UTC with THREE fractional digits.
_TS_3DP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")


def assert_timestamp_three_fractional(value: str):
    """Timestamps carry exactly three fractional digits (PRD §2.5)."""
    assert isinstance(value, str) and _TS_3DP_RE.match(value), (
        f"Expected ISO 8601 UTC timestamp with 3 fractional digits, got {value!r}"
    )


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a bare UUID, got {data.get('id')!r}"
    assert_timestamp_three_fractional(data.get("created_at", ""))
    assert_timestamp_three_fractional(data.get("updated_at", ""))
    assert isinstance(data.get("version"), int) and data["version"] >= 1


def _assert_immutable_record_fields(data: dict):
    """Append-only records carry only id + created_at (PRD §2.5)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a bare UUID, got {data.get('id')!r}"
    assert_timestamp_three_fractional(data.get("created_at", ""))
    assert "updated_at" not in data, "immutable record must not carry updated_at (PRD §2.5)"
    assert "version" not in data, "immutable record must not carry version (PRD §2.5)"


def assert_drug(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["j_code"], str) and data["j_code"]
    assert isinstance(data["drug_name"], str) and data["drug_name"]
    assert isinstance(data["billing_unit_mg"], int) and data["billing_unit_mg"] >= 1
    assert isinstance(data["vial_size_mg"], int) and data["vial_size_mg"] >= 1
    assert data["vial_size_mg"] % data["billing_unit_mg"] == 0
    assert isinstance(data["single_dose_vial"], bool)
    assert data["sourcing_rule"] in (
        "BUY_AND_BILL_ONLY",
        "SPECIALTY_PHARMACY_ONLY",
        "EITHER",
    )
    assert isinstance(data["weight_based_dosing"], bool)
    assert data["dose_rounding_mode"] in ("VIAL", "INCREMENT")
    assert isinstance(data["max_single_dose_mg"], int) and data["max_single_dose_mg"] >= 1
    assert isinstance(data["site_of_care_eligible"], bool)


def assert_asp_schedule(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["drug_id"])
    assert isinstance(data["effective_start"], str) and data["effective_start"]
    assert isinstance(data["asp_rate_cents"], int) and data["asp_rate_cents"] > 0
    assert data["status"] in ("SCHEDULED", "EFFECTIVE", "SUPERSEDED")


def assert_clinical_policy(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["drug_id"])
    assert isinstance(data["covered_diagnoses"], list) and len(data["covered_diagnoses"]) >= 1
    assert isinstance(data["step_therapy_required"], bool)
    assert isinstance(data["requires_site_of_care_redirection"], bool)
    assert data["biosimilar_substitution"] in ("DISABLED", "PREFERRED", "MANDATORY")
    assert isinstance(data["version_no"], int) and data["version_no"] >= 1
    assert data["status"] in ("DRAFT", "ACTIVE", "SUPERSEDED")


def assert_provider_account(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert data["status"] in ("ACTIVE", "RECOUPMENT_HOLD")
    assert isinstance(data["cumulative_paid_cents"], int)
    assert isinstance(data["recoupment_balance_cents"], int)
    assert_provider_ledger_invariants(data)


def assert_provider_ledger_invariants(data: dict):
    """Ledger invariants from PRD §2.10 that must hold after any operation."""
    assert data["recoupment_balance_cents"] >= 0, "recoupment balance is never negative"
    if data["status"] == "RECOUPMENT_HOLD":
        assert data["recoupment_balance_cents"] > 0, (
            "HOLD is entered only when the recoupment balance is positive"
        )


def assert_prior_authorization(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["drug_id"])
    assert isinstance(data["member_id"], str) and data["member_id"]
    assert is_valid_uuid(data["provider_account_id"])
    assert isinstance(data["diagnosis_code"], str) and data["diagnosis_code"]
    assert isinstance(data["requested_start_date"], str) and data["requested_start_date"]
    assert isinstance(data["step_therapy_completed"], bool)
    assert data["status"] in (
        "SUBMITTED",
        "APPROVED",
        "DENIED",
        "SUSPENDED",
        "EXPIRED",
        "CANCELLED",
        "EXHAUSTED",
    )
    assert isinstance(data["administrations_used"], int) and data["administrations_used"] >= 0
    if data["status"] == "APPROVED" or data["status"] == "SUSPENDED":
        assert data["approved_dose_mg"] is not None
        assert data["validity_start"] is not None
        assert data["validity_end"] is not None
        assert isinstance(data["max_administrations"], int) and data["max_administrations"] >= 1


def assert_infusion_claim(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["auth_id"])
    assert is_valid_uuid(data["drug_id"])
    assert is_valid_uuid(data["provider_account_id"])
    assert isinstance(data["service_date"], str) and data["service_date"]
    assert data["site_of_care"] in ("HOPD", "OFFICE", "HOME", "AMBULATORY")
    assert data["sourcing_path"] in ("BUY_AND_BILL", "WHITE_BAG")
    assert isinstance(data["j_code_billed"], str) and data["j_code_billed"]
    assert isinstance(data["billed_units"], int) and data["billed_units"] >= 1
    assert isinstance(data["waste_units"], int) and data["waste_units"] >= 0
    assert isinstance(data["jw_modifier"], bool)
    assert data["status"] in (
        "APPROVED_FOR_PAYMENT",
        "PENDED",
        "PAID",
        "ADJUSTED",
        "DENIED",
    )
    assert isinstance(data["allowed_amount_cents"], int)
    assert isinstance(data["member_cost_share_cents"], int)
    assert isinstance(data["payable_waste_units"], int) and data["payable_waste_units"] >= 0
    if data["status"] == "PENDED":
        assert data.get("pend_reason") in ("DOSE_REVIEW", "AUTH_SUSPENDED")


def assert_claim_adjustment(data: dict):
    """Append-only repricing event (PRD §2.5, §3.3)."""
    _assert_immutable_record_fields(data)
    assert is_valid_uuid(data["claim_id"])
    assert is_valid_uuid(data["asp_schedule_id"])
    assert isinstance(data["old_allowed_cents"], int)
    assert isinstance(data["new_allowed_cents"], int)
    assert isinstance(data["delta_cents"], int)
    assert data["delta_cents"] == data["new_allowed_cents"] - data["old_allowed_cents"]
    assert data["reason"] == "ASP_RETRO"


def assert_redirection(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["auth_id"])
    assert data["from_site"] == "HOPD"
    assert data["candidate_sites"] == ["OFFICE", "HOME", "AMBULATORY"]
    assert data["status"] in ("OFFERED", "ACCEPTED", "DECLINED", "EXPIRED")
    assert isinstance(data["member_incentive_cents"], int)
    if data["status"] == "ACCEPTED":
        assert data["accepted_site"] in ("OFFICE", "HOME", "AMBULATORY")


def assert_biosimilar_policy(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["reference_drug_id"])
    assert is_valid_uuid(data["biosimilar_drug_id"])
    assert data["reference_drug_id"] != data["biosimilar_drug_id"]
    assert 0 < data["provider_incentive_addon_pct"] <= 0.10
    assert 0 <= data["member_copay_waiver_pct"] <= 1
    assert isinstance(data["effective_start"], str) and data["effective_start"]
    assert isinstance(data["effective_end"], str) and data["effective_end"]
    assert data["effective_end"] > data["effective_start"]
    assert data["status"] in ("DRAFT", "ACTIVE", "EXPIRED")


def assert_pipeline_drug(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["drug_name"], str) and data["drug_name"]
    assert isinstance(data["expected_approval_date"], str)
    assert data["prevalence_per_100k"] > 0
    assert isinstance(data["projected_annual_cost_cents"], int)
    assert data["projected_annual_cost_cents"] > 0
    assert 0 < data["year1_uptake_pct"] <= 1
    assert 0 < data["steady_state_uptake_pct"] <= 1
    assert 0 <= data["biosimilar_erosion_pct"] < 1


def assert_spend_forecast_run(data: dict):
    """Immutable computed snapshot (PRD §2.5, §3.8)."""
    _assert_immutable_record_fields(data)
    assert data["variant"] in ("BASELINE", "POLICY_ADJUSTED")
    assert isinstance(data["horizon_years"], int) and 1 <= data["horizon_years"] <= 5
    assert isinstance(data["enrollment_projection"], int) and data["enrollment_projection"] >= 1
    assert isinstance(data["as_of_date"], str) and data["as_of_date"]
    assert isinstance(data["pipeline_total_cents"], int)
    assert isinstance(data["inline_annualized_cents"], int)
    assert isinstance(data["total_projected_cents"], int)
    assert isinstance(data["per_drug_projections"], list)
    assert (
        data["total_projected_cents"]
        == data["pipeline_total_cents"]
        + data["inline_annualized_cents"] * data["horizon_years"]
    ), "total_projected_cents must equal pipeline_total + inline x horizon (PRD §3.8)"


def assert_iso8601(value: str):
    assert is_iso8601_timestamp(value), f"Not ISO 8601: {value!r}"
