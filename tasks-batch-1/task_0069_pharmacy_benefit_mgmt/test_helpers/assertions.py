"""Entity assertions and domain invariant checkers (PRD §1-§3)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"


def _common_versioned(data: dict):
    _common(data)
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be int"
    assert data["version"] >= 1


def assert_benefit_plan(data: dict):
    _common_versioned(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["plan_year"], int)
    assert isinstance(data["deductible_cents"], int) and data["deductible_cents"] >= 0
    assert isinstance(data["oop_max_cents"], int)
    assert data["oop_max_cents"] >= data["deductible_cents"]
    assert isinstance(data["tier_copay_cents"], dict)
    assert set(data["tier_copay_cents"].keys()) == {"TIER_1", "TIER_2", "TIER_3", "SPECIALTY"}
    assert data["status"] in ("ACTIVE", "ARCHIVED")


def assert_formulary_drug(data: dict):
    _common_versioned(data)
    assert is_valid_uuid(data.get("plan_id", "")), "plan_id must be UUID"
    assert isinstance(data["ndc"], str)
    assert isinstance(data["drug_name"], str)
    assert data["tier"] in ("TIER_1", "TIER_2", "TIER_3", "SPECIALTY")
    assert isinstance(data["ingredient_cost_cents"], int) and data["ingredient_cost_cents"] > 0
    assert isinstance(data["is_specialty"], bool)
    assert isinstance(data["pa_required"], bool)
    assert isinstance(data["rebate_per_fill_cents"], int) and data["rebate_per_fill_cents"] >= 0
    assert data["status"] in ("ACTIVE", "INACTIVE")


def assert_step_therapy_protocol(data: dict):
    # common_fields:false — no updated_at, no version
    _common(data)
    assert is_valid_uuid(data.get("plan_id", "")), "plan_id must be UUID"
    assert isinstance(data["name"], str)
    assert isinstance(data["first_line_ndcs"], list) and len(data["first_line_ndcs"]) >= 1
    assert "version" not in data, "StepTherapyProtocol must NOT carry a version field"
    assert "updated_at" not in data, "StepTherapyProtocol must NOT carry an updated_at field"


def assert_member(data: dict):
    _common_versioned(data)
    assert is_valid_uuid(data.get("plan_id", "")), "plan_id must be UUID"
    assert isinstance(data["full_name"], str)
    assert isinstance(data["deductible_met_cents"], int) and data["deductible_met_cents"] >= 0
    assert isinstance(data["oop_met_cents"], int) and data["oop_met_cents"] >= 0
    assert data["status"] in ("ACTIVE", "TERMINATED")


def assert_prior_authorization(data: dict):
    _common_versioned(data)
    assert is_valid_uuid(data.get("member_id", "")), "member_id must be UUID"
    assert is_valid_uuid(data.get("formulary_drug_id", "")), "formulary_drug_id must be UUID"
    assert data["status"] in ("PENDING_REVIEW", "APPROVED", "DENIED", "APPEALED", "EXPIRED")
    assert isinstance(data["approved_quantity_remaining"], int)
    assert isinstance(data["authorized_fills"], int) and data["authorized_fills"] >= 1
    assert isinstance(data["overrides_step_therapy"], bool)


def assert_claim(data: dict):
    _common_versioned(data)
    assert is_valid_uuid(data.get("member_id", "")), "member_id must be UUID"
    assert is_valid_uuid(data.get("formulary_drug_id", "")), "formulary_drug_id must be UUID"
    assert data["days_supply"] in (30, 90)
    assert data["pharmacy_type"] in ("RETAIL", "MAIL_ORDER", "SPECIALTY")
    assert data["adjudication_status"] in ("SUBMITTED", "PAID", "REVERSED", "REJECTED")
    assert data["rebate_status"] in ("NONE", "ACCRUED", "CLAWED_BACK")
    assert isinstance(data["gross_cost_cents"], int)
    assert isinstance(data["member_pay_cents"], int)
    assert isinstance(data["copay_card_paid_cents"], int)
    assert isinstance(data["plan_paid_cents"], int)


def assert_copay_card(data: dict):
    _common_versioned(data)
    assert is_valid_uuid(data.get("member_id", "")), "member_id must be UUID"
    assert is_valid_uuid(data.get("formulary_drug_id", "")), "formulary_drug_id must be UUID"
    assert isinstance(data["max_benefit_cents"], int) and data["max_benefit_cents"] > 0
    assert isinstance(data["benefit_used_cents"], int) and data["benefit_used_cents"] >= 0
    assert data["status"] in ("ACTIVE", "EXHAUSTED")


def assert_rebate_agreement(data: dict):
    _common_versioned(data)
    assert is_valid_uuid(data.get("plan_id", "")), "plan_id must be UUID"
    assert isinstance(data["manufacturer_name"], str)
    assert 0 <= data["clawback_pct"] <= 1


def assert_rebate_accrual(data: dict):
    _common_versioned(data)
    assert is_valid_uuid(data.get("claim_id", "")), "claim_id must be UUID"
    assert is_valid_uuid(data.get("rebate_agreement_id", "")), "rebate_agreement_id must be UUID"
    assert isinstance(data["accrued_cents"], int)
    assert isinstance(data["clawback_cents"], int)
    assert data["status"] in ("PROVISIONAL", "FINALIZED", "CLAWED_BACK")


def assert_plan_paid_consistency(claim: dict):
    """plan_paid_cents == gross_cost_cents - member_pay_cents (PRD §3.5)."""
    assert claim["plan_paid_cents"] == claim["gross_cost_cents"] - claim["member_pay_cents"], (
        f"plan_paid_cents {claim['plan_paid_cents']} != gross {claim['gross_cost_cents']} "
        f"- member_pay {claim['member_pay_cents']}"
    )
