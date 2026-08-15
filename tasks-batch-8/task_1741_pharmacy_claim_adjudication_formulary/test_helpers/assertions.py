"""Entity assertions and domain invariant checkers (PRD §2.4, §3)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common_fields(data: dict):
    """Primary resources carry id, created_at, updated_at, version (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_plan(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["deductible_cents"], int) and data["deductible_cents"] >= 0
    assert isinstance(data["oop_max_cents"], int) and data["oop_max_cents"] >= 0
    assert data["assistance_model"] in ("ACCUMULATOR", "MAXIMIZER")
    assert isinstance(data["member_min_pay_cents"], int)
    assert isinstance(data["card_fill_cap_cents"], int)
    assert isinstance(data["dispensing_fee_cents"], int)
    assert data["status"] in ("DRAFT", "ACTIVE", "RETIRED")


def assert_drug(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["ndc"], str) and len(data["ndc"]) > 0
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["therapeutic_class"], str)
    assert isinstance(data["unit_cost_cents"], int) and data["unit_cost_cents"] > 0
    assert isinstance(data["max_daily_dose_units"], int) and data["max_daily_dose_units"] > 0
    assert isinstance(data["is_specialty"], bool)


def assert_formulary_entry(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("plan_id", "")), "plan_id must be valid UUID"
    assert is_valid_uuid(data.get("drug_id", "")), "drug_id must be valid UUID"
    assert isinstance(data["tier"], int) and 1 <= data["tier"] <= 4
    assert isinstance(data["pa_required"], bool)
    assert isinstance(data["step_therapy_required"], bool)
    assert isinstance(data["quantity_limit_per_fill"], int)
    assert isinstance(data["max_days_supply"], int)
    assert data["copay_type"] in ("FLAT", "PERCENTAGE")
    assert data["status"] in ("ACTIVE", "INACTIVE")


def assert_pharmacy(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["ncpdp_id"], str) and len(data["ncpdp_id"]) > 0
    assert isinstance(data["name"], str)
    assert data["channel"] in ("RETAIL", "SPECIALTY", "MAIL_ORDER")
    assert isinstance(data["auto_suspend_threshold_cents"], int)
    assert isinstance(data["balance_cents"], int)
    assert data["status"] in ("ACTIVE", "SUSPENDED")


def assert_member(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("plan_id", "")), "plan_id must be valid UUID"
    assert isinstance(data["external_ref"], str) and len(data["external_ref"]) > 0
    assert isinstance(data["full_name"], str)
    assert isinstance(data["eligibility_start_date"], str)
    assert isinstance(data["eligibility_end_date"], str)
    assert data["status"] in ("ACTIVE", "TERMINATED")
    assert isinstance(data["deductible_paid_cents"], int)
    assert isinstance(data["oop_paid_cents"], int)
    assert isinstance(data["oop_max_reached"], bool)
    assert data.get("card_drug_id") is None or isinstance(data["card_drug_id"], str)
    assert isinstance(data["card_balance_cents"], int)


def assert_prior_authorization(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("member_id", "")), "member_id must be valid UUID"
    assert is_valid_uuid(data.get("drug_id", "")), "drug_id must be valid UUID"
    assert isinstance(data["requested_quantity"], int) and data["requested_quantity"] > 0
    assert data["status"] in ("PENDING", "APPROVED", "DENIED", "CANCELLED")
    assert isinstance(data["quantity_consumed"], int)


def assert_claim(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("member_id", "")), "member_id must be valid UUID"
    assert is_valid_uuid(data.get("pharmacy_id", "")), "pharmacy_id must be valid UUID"
    assert is_valid_uuid(data.get("drug_id", "")), "drug_id must be valid UUID"
    assert isinstance(data["prescription_number"], str)
    assert isinstance(data["fill_date"], str)
    assert isinstance(data["quantity"], int) and data["quantity"] > 0
    assert isinstance(data["days_supply"], int) and data["days_supply"] > 0
    assert data["status"] in ("PAID", "REJECTED", "REVERSED")
    assert isinstance(data["reject_reasons"], list)
    assert isinstance(data["allowed_cents"], int)
    assert isinstance(data["copay_base_cents"], int)
    assert isinstance(data["deductible_applied_cents"], int)
    assert isinstance(data["card_applied_cents"], int)
    assert isinstance(data["member_pays_cents"], int)
    assert isinstance(data["plan_paid_cents"], int)
    assert data.get("pa_id") is None or isinstance(data["pa_id"], str)
    assert isinstance(data["resubmit_count"], int)
    assert data["audit_status"] in ("UNAUDITED", "FLAGGED", "CLAWED_BACK")
    assert data["rebate_tag"] in ("REBATE_ELIGIBLE", "REBATE_INELIGIBLE", "REBATE_VOID")


def assert_dur_alert(data: dict):
    """Append-only screening record: id + created_at only — no updated_at/version (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "DUR alerts carry no updated_at"
    assert "version" not in data, "DUR alerts carry no version"
    assert is_valid_uuid(data.get("claim_id", "")), "claim_id must be valid UUID"
    assert data["alert_type"] in ("EARLY_REFILL", "THERAPEUTIC_DUPLICATION", "HIGH_DAILY_DOSE")
    assert data["severity"] in ("MEDIUM", "HIGH")
    assert data["status"] in ("OPEN", "OVERRIDDEN", "SUPERSEDED")


def assert_pharmacy_audit(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("pharmacy_id", "")), "pharmacy_id must be valid UUID"
    assert isinstance(data["window_start_date"], str)
    assert isinstance(data["window_end_date"], str)
    assert data["extrapolation_method"] in ("CLAIM_LEVEL", "EXTRAPOLATED")
    assert data["status"] in (
        "OPEN", "FINDINGS_RECORDED", "DISPUTED",
        "CLOSED_WITH_FINDINGS", "CLOSED_NO_FINDINGS",
    )
    assert isinstance(data["findings"], list)
    assert isinstance(data["sample_size"], int)
    assert isinstance(data["universe_paid_claims"], int)
    assert isinstance(data["total_clawback_cents"], int)


def assert_member_accumulator_invariants(member: dict, plan: dict):
    """Accumulator invariants that must hold after any posting (PRD §3.5)."""
    assert member["deductible_paid_cents"] >= 0
    assert member["oop_paid_cents"] >= 0
    assert member["deductible_paid_cents"] <= plan["deductible_cents"]
    assert member["oop_max_reached"] == (member["oop_paid_cents"] >= plan["oop_max_cents"])
