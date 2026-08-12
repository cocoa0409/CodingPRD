"""Entity assertions and domain invariant checkers (PRD §2.4, §3)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common_fields(data: dict):
    """Every persisted resource carries id, created_at, updated_at, version (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        "version must be an integer starting at 1"


def assert_production(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["production_code"], str) and data["production_code"]
    assert data["production_type"] in [
        "FEATURE", "EPISODIC", "DOCUMENTARY", "COMMERCIAL", "MUSIC_VIDEO"]
    assert isinstance(data["budget_cents"], int) and data["budget_cents"] > 0
    assert data["status"] in ["DRAFT", "ACTIVE", "WRAPPED", "CANCELLED"]
    assert data["coverage_posture"] in [
        "UNBOUND", "BOUND_PARTIAL", "BOUND_FULL", "RESTRICTED", "SUSPENDED"]
    assert isinstance(data["posture_reasons"], list)


def assert_policy(data: dict):
    _assert_common_fields(data)
    assert data["coverage_line"] in [
        "GENERAL_LIABILITY", "EQUIPMENT", "CAST", "ERRORS_OMISSIONS", "FOREIGN_TRAVEL"]
    assert isinstance(data["carrier_code"], str) and data["carrier_code"]
    assert isinstance(data["policy_number"], str) and data["policy_number"]
    assert isinstance(data["limit_cents"], int) and data["limit_cents"] > 0
    assert isinstance(data["aggregate_limit_cents"], int)
    assert isinstance(data["deductible_cents"], int) and data["deductible_cents"] >= 0
    assert data["status"] in [
        "QUOTED", "BOUND", "ENDORSED_PENDING", "ACTIVE", "EXPIRED", "CANCELLED"]


def assert_cast_member(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert data["role_tier"] in ["PRINCIPAL", "SUPPORTING", "DAY_PLAYER", "STUNT"]
    assert isinstance(data["weekly_salary_cents"], int) and data["weekly_salary_cents"] > 0
    assert data["physical_exam_status"] in [
        "PENDING", "CLEARED", "CONDITIONAL", "FAILED", "EXPIRED"]
    assert isinstance(data["endorsement_required"], bool)


def assert_cast_endorsement(data: dict):
    _assert_common_fields(data)
    assert data["endorsement_type"] in [
        "PHYSICAL_CLEARANCE", "ESSENTIAL_ELEMENT", "STUNT_RIDER"]
    assert data["status"] in ["DRAFT", "ISSUED", "REVOKED"]


def assert_certificate(data: dict):
    _assert_common_fields(data)
    assert data["certificate_type"] in ["LOCATION", "VENDOR", "EQUIPMENT_RENTAL", "PERMIT"]
    assert isinstance(data["holder_name"], str) and data["holder_name"]
    assert isinstance(data["coverage_lines"], list)
    assert data["status"] in ["DRAFT", "ISSUED", "VOIDED", "EXPIRED"]


def assert_claim(data: dict):
    _assert_common_fields(data)
    assert data["claim_type"] in [
        "DAMAGE", "INJURY", "WEATHER_DELAY", "THEFT", "THIRD_PARTY"]
    assert isinstance(data["loss_amount_cents"], int) and data["loss_amount_cents"] > 0
    assert isinstance(data["deductible_applied_cents"], int)
    assert isinstance(data["carrier_payable_cents"], int)
    assert data["status"] in [
        "SUBMITTED", "UNDER_REVIEW", "ADJUSTED", "DENIED", "SETTLED", "CLOSED"]


def assert_claim_event(data: dict):
    """Append-only log rows carry only id + created_at (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["event_type"] in [
        "SUBMIT", "ADJUST_RESERVE", "DENY", "SETTLE", "REOPEN", "CLOSE"]
    assert isinstance(data.get("claim_id"), str) and data["claim_id"]
    assert "updated_at" not in data, "claim events must not carry updated_at"
    assert "version" not in data, "claim events must not carry version"


def assert_clearance_item(data: dict):
    _assert_common_fields(data)
    assert data["clearance_kind"] in [
        "SCRIPT", "TITLE", "MUSIC", "PERSONAL_RIGHTS", "TRADEMARK", "LOCATION_RIGHTS"]
    assert isinstance(data["item_reference"], str)
    assert isinstance(data["legal_reviewer"], str)
    assert data["status"] in ["PENDING", "CLEARED", "FLAGGED", "WAIVED"]


def assert_completion_bond(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["surety_company"], str) and data["surety_company"]
    assert isinstance(data["bond_amount_cents"], int) and data["bond_amount_cents"] > 0
    assert data["status"] in [
        "APPLIED", "UNDERWRITTEN", "ISSUED", "CLAIMED", "RELEASED", "LAPSED"]


def assert_travel_extension(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["territory_code"], str) and len(data["territory_code"]) == 2
    assert isinstance(data["travelers_count"], int) and data["travelers_count"] > 0
    assert isinstance(data["repatriation_limit_cents"], int) \
        and data["repatriation_limit_cents"] > 0
    assert data["status"] in ["REQUESTED", "APPROVED", "ACTIVE", "EXPIRED", "DENIED"]


def assert_payroll_audit(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["auditor_name"], str) and data["auditor_name"]
    assert isinstance(data["reported_payroll_cents"], int) \
        and data["reported_payroll_cents"] >= 0
    assert data["status"] in ["SCHEDULED", "SUBMITTED", "POSTED", "DISPUTED"]


def assert_renewal_offer(data: dict):
    _assert_common_fields(data)
    assert data["renewal_term_months"] in [6, 12, 18]
    assert data["status"] in ["OFFERED", "ACCEPTED", "DECLINED", "EXPIRED", "SUPERSEDED"]


def assert_claim_amount_invariant(claim: dict):
    """loss_amount_cents == deductible_applied_cents + carrier_payable_cents (PRD §3.8)."""
    assert claim["loss_amount_cents"] == (
        claim["deductible_applied_cents"] + claim["carrier_payable_cents"]
    ), (f"Claim invariant violated: loss {claim['loss_amount_cents']} != "
        f"deductible {claim['deductible_applied_cents']} + "
        f"carrier_payable {claim['carrier_payable_cents']}")
