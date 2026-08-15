"""Entity assertions and domain invariant checkers (PRD §2.2, §2.5, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert _is_int(data.get("version")), "version must be an integer"
    assert data["version"] >= 1, "version starts at 1"


def assert_patient(data: dict):
    _assert_common(data)
    assert isinstance(data["mrn"], str) and data["mrn"]
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["date_of_birth"], str) and data["date_of_birth"]


def assert_charge_item(data: dict):
    _assert_common(data)
    assert isinstance(data["cpt_code"], str) and data["cpt_code"]
    assert _is_int(data["list_price_cents"]) and data["list_price_cents"] > 0
    assert isinstance(data["requires_auth_prior"], bool)


def assert_payer_contract(data: dict):
    _assert_common(data)
    assert isinstance(data["payer_code"], str) and data["payer_code"]
    assert data["bundling_rule"] in ("NONE", "MULTIPLE_PROCEDURE_REDUCTION")


def assert_contract_rate(data: dict):
    _assert_common(data)
    assert isinstance(data["contract_id"], str) and data["contract_id"]
    assert isinstance(data["cpt_code"], str) and data["cpt_code"]
    assert _is_int(data["rate_cents"]) and data["rate_cents"] > 0
    assert isinstance(data["effective_from"], str) and data["effective_from"]


def assert_eligibility_snapshot(data: dict):
    _assert_common(data)
    assert isinstance(data["patient_id"], str) and data["patient_id"]
    assert isinstance(data["payer_code"], str) and data["payer_code"]
    assert _is_int(data["deductible_total_cents"]) and data["deductible_total_cents"] >= 0
    assert _is_int(data["deductible_met_cents"])
    assert 0 <= data["deductible_met_cents"] <= data["deductible_total_cents"]
    assert _is_int(data["oop_max_cents"]) and data["oop_max_cents"] > 0
    assert _is_int(data["oop_met_cents"])
    assert 0 <= data["oop_met_cents"] <= data["oop_max_cents"]
    assert _is_int(data["coinsurance_pct"]) and 0 <= data["coinsurance_pct"] <= 100
    assert is_iso8601_timestamp(data.get("verified_at", "")), "verified_at must be ISO 8601"
    assert data["status"] in ("ACTIVE", "SUPERSEDED", "STALE")


def assert_case(data: dict):
    _assert_common(data)
    assert isinstance(data["patient_id"], str) and data["patient_id"]
    assert isinstance(data["service_date"], str) and data["service_date"]
    assert data["status"] in ("OPEN", "IN_REVIEW", "CLEARED", "CANCELLED")
    assert isinstance(data["auth_required"], bool)
    assert isinstance(data["auth_satisfied"], bool)
    assert _is_int(data["required_deposit_cents"]) and data["required_deposit_cents"] >= 0
    assert _is_int(data["deposit_posted_cents"]) and data["deposit_posted_cents"] >= 0
    assert isinstance(data["deposit_satisfied"], bool)
    assert isinstance(data["high_dollar_flag"], bool)
    assert isinstance(data["escalation_cleared"], bool)
    assert data["clearance_posture"] in ("READY", "BLOCKED")


def assert_estimate(data: dict):
    _assert_common(data)
    assert isinstance(data["case_id"], str) and data["case_id"]
    assert data["pricing_mode"] in ("INSURED", "UNINSURED_GFE")
    assert _is_int(data["revision"]) and data["revision"] >= 1
    assert isinstance(data["lines"], list) and len(data["lines"]) >= 1
    assert data["status"] in ("DRAFT", "PRICED", "PRESENTED", "ACCEPTED", "FINALIZED",
                              "SUPERSEDED", "EXPIRED", "CANCELLED")
    for money_field in ("allowed_amount_cents", "deductible_applied_cents",
                        "coinsurance_cents", "patient_responsibility_cents",
                        "insurance_pays_cents", "gfe_total_cents"):
        assert _is_int(data[money_field]) and data[money_field] >= 0, money_field


def assert_authorization(data: dict):
    _assert_common(data)
    assert isinstance(data["case_id"], str) and data["case_id"]
    assert isinstance(data["payer_code"], str) and data["payer_code"]
    assert isinstance(data["cpt_codes"], list) and len(data["cpt_codes"]) >= 1
    assert data["status"] in ("REQUESTED", "APPROVED", "DENIED", "APPEALED",
                              "DENIED_FINAL", "WITHDRAWN", "EXPIRED")
    assert isinstance(data["requested_by_user_id"], str) and data["requested_by_user_id"]


def assert_payment_plan(data: dict):
    _assert_common(data)
    assert isinstance(data["case_id"], str) and data["case_id"]
    assert _is_int(data["principal_cents"]) and data["principal_cents"] > 0
    assert _is_int(data["num_installments"]) and 2 <= data["num_installments"] <= 12
    assert _is_int(data["installment_amount_cents"])
    assert isinstance(data["installments"], list)
    assert len(data["installments"]) == data["num_installments"]
    assert _is_int(data["principal_outstanding_cents"])
    assert _is_int(data["missed_payment_count"]) and data["missed_payment_count"] >= 0
    assert data["status"] in ("DRAFT", "ACTIVE", "DEFAULTED", "COMPLETED", "CANCELLED")


def assert_deposit(data: dict):
    _assert_common(data)
    assert isinstance(data["case_id"], str) and data["case_id"]
    assert _is_int(data["amount_cents"]) and data["amount_cents"] > 0
    assert data["method"] in ("CARD", "CHECK", "CASH")
    assert data["status"] in ("PLEDGED", "POSTED", "APPLIED", "REFUNDED", "CANCELLED")


def assert_variance_record(data: dict):
    _assert_common(data)
    assert isinstance(data["estimate_id"], str) and data["estimate_id"]
    for money_field in ("baseline_first_presented_resp_cents",
                        "baseline_last_accepted_resp_cents", "actual_billed_cents",
                        "variance_vs_first_cents", "variance_vs_accepted_cents"):
        assert _is_int(data[money_field]), money_field
    assert isinstance(data["variance_pct"], (int, float)) and not isinstance(
        data["variance_pct"], bool)
    assert data["classification"] in ("WITHIN_TOLERANCE", "OVER_TOLERANCE",
                                      "UNDER_TOLERANCE")
    assert isinstance(data["dispute_eligible"], bool)
    assert data["status"] in ("UNREVIEWED", "REVIEWED")


def assert_escalation(data: dict):
    _assert_common(data)
    assert isinstance(data["case_id"], str) and data["case_id"]
    assert data["reason"] in ("HIGH_DOLLAR", "AUTH_EXCEPTION", "GFE_DISPUTE")
    assert _is_int(data["trigger_amount_cents"]) and data["trigger_amount_cents"] >= 0
    assert data["status"] in ("OPEN", "APPROVED", "REJECTED")
    assert isinstance(data["opened_by_user_id"], str) and data["opened_by_user_id"]


def assert_plan_amounts_conserve_principal(plan: dict):
    """Installment schedule always sums exactly to principal_cents (PRD §3.8)."""
    total = sum(inst["amount_cents"] for inst in plan["installments"])
    assert total == plan["principal_cents"], (
        f"installment amounts {total} must equal principal {plan['principal_cents']}")
    paid = sum(inst["paid_cents"] for inst in plan["installments"])
    assert plan["principal_outstanding_cents"] == plan["principal_cents"] - paid
