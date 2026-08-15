"""Entity assertions and domain invariant checkers (PRD §2.2–§2.4, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

INGREDIENT_STATUSES = ["DRAFT", "ACTIVE", "DISCONTINUED"]
SPEC_STATUSES = ["DRAFT", "PENDING_REVIEW", "APPROVED", "EFFECTIVE", "SUPERSEDED", "RETIRED", "REJECTED"]
SUPPLIER_STATUSES = ["PROSPECT", "IN_QUALIFICATION", "QUALIFIED", "SUSPENDED", "DISQUALIFIED"]
QUALIFICATION_STATUSES = ["SUBMITTED", "UNDER_EVALUATION", "APPROVED", "REJECTED"]
SOURCE_STATUSES = ["PROVISIONAL", "ACTIVE", "SUSPENDED", "REVOKED"]
CONTRACT_STATUSES = ["PENDING", "ACTIVE", "EXPIRED", "TERMINATED"]
COA_STATUSES = ["REGISTERED", "UNDER_REVIEW", "ACCEPTED", "CONDITIONALLY_ACCEPTED", "REJECTED"]
FINDING_DISPOSITIONS = ["REPORTED", "ACCEPT_AS_IS", "DOWNGRADED_TO_MINOR", "REJECT_LOT"]
DECLARATION_STATUSES = ["CURRENT", "SUPERSEDED", "EXPIRED"]
SUBSTITUTION_STATUSES = ["REQUESTED", "IMPACT_ASSESSED", "PENDING_REGULATORY", "APPROVED", "REJECTED", "EXECUTED", "CANCELLED"]
AUDIT_STATUSES = ["SCHEDULED", "IN_PROGRESS", "REPORT_ISSUED", "CLOSED", "CANCELLED"]
CAPA_STATUSES = ["OPEN", "SUBMITTED", "VERIFIED", "REJECTED"]


def assert_qty(actual, expected, places=4):
    """Numeric equality tolerant of JSON number formatting (round-half-up pinned
    values per PRD §2.5): the server value must be within half a unit of the
    last pinned decimal place."""
    assert actual is not None, f"expected a numeric value equal to {expected}, got None"
    tol = 0.5 * (10 ** -places) + 1e-9
    assert abs(float(actual) - float(expected)) <= tol, f"expected {expected}, got {actual}"


def _assert_common(data, context):
    assert is_valid_uuid(data.get("id", "")), f"{context}: id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"{context}: created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), f"{context}: updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), f"{context}: version must be an integer"


def assert_ingredient(data: dict):
    _assert_common(data, "Ingredient")
    assert isinstance(data["ingredient_code"], str) and data["ingredient_code"]
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["allergen_profile"], list)
    assert isinstance(data["requires_dual_source"], bool)
    assert data["status"] in INGREDIENT_STATUSES
    assert "active_spec_id" in data
    assert isinstance(data["current_dual_source_breach"], bool)


def assert_spec(data: dict):
    _assert_common(data, "IngredientSpec")
    assert isinstance(data["spec_version_label"], str) and data["spec_version_label"]
    assert data["status"] in SPEC_STATUSES
    assert isinstance(data["ingredient_id"], str)
    assert isinstance(data["author_user_id"], str) and data["author_user_id"]


def assert_parameter(data: dict):
    _assert_common(data, "SpecParameter")
    assert isinstance(data["parameter_name"], str) and data["parameter_name"]
    assert data["criticality"] in ["CRITICAL", "MAJOR", "MINOR"]
    assert float(data["min_value"]) < float(data["max_value"])


def assert_supplier(data: dict):
    _assert_common(data, "Supplier")
    assert isinstance(data["supplier_code"], str) and data["supplier_code"]
    assert data["status"] in SUPPLIER_STATUSES
    assert data["risk_tier"] in ["TIER_A", "TIER_B", "TIER_C"]
    assert isinstance(data["open_overdue_capa_count"], int)
    assert isinstance(data["requalification_cycle"], int)


def assert_qualification(data: dict):
    _assert_common(data, "SupplierQualification")
    assert data["status"] in QUALIFICATION_STATUSES
    assert isinstance(data["supplier_id"], str)


def assert_approved_source(data: dict):
    _assert_common(data, "ApprovedSource")
    assert data["status"] in SOURCE_STATUSES
    assert data["suspension_reason"] in ["NONE", "COA_RISK", "SUPPLIER_SUSPENDED", "MANUAL"]
    assert isinstance(data["supplier_id"], str)
    assert isinstance(data["pinned_spec_id"], str)


def assert_contract(data: dict):
    _assert_common(data, "SupplyContract")
    assert data["status"] in CONTRACT_STATUSES
    assert isinstance(data["approved_source_id"], str)
    assert isinstance(data["cumulative_shipped_kg"], int)


def assert_price_observation(data: dict):
    """Append-only log row: id + created_at, and version/updated_at absent (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "PriceIndexObservation: id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "version" not in data, "version must be absent on the immutable observation log"
    assert "updated_at" not in data, "updated_at must be absent on the immutable observation log"
    assert float(data["index_value"]) > 0


def assert_coa(data: dict):
    _assert_common(data, "CertificateOfAnalysis")
    assert data["status"] in COA_STATUSES
    assert isinstance(data["lot_number"], str) and data["lot_number"]
    assert isinstance(data["registered_by_user_id"], str) and data["registered_by_user_id"]


def assert_finding(data: dict):
    _assert_common(data, "CoAOutOfSpecFinding")
    assert data["disposition"] in FINDING_DISPOSITIONS
    assert data["criticality_at_finding"] in ["CRITICAL", "MAJOR", "MINOR"]
    assert isinstance(data["parameter_name"], str) and data["parameter_name"]


def assert_declaration(data: dict):
    _assert_common(data, "RegulatoryDeclaration")
    assert data["declaration_type"] in ["ALLERGEN", "COUNTRY_OF_ORIGIN"]
    assert data["status"] in DECLARATION_STATUSES
    assert isinstance(data["payload"], dict)


def assert_substitution_request(data: dict):
    _assert_common(data, "SubstitutionRequest")
    assert data["status"] in SUBSTITUTION_STATUSES
    assert isinstance(data["requested_by_user_id"], str) and data["requested_by_user_id"]
    assert isinstance(data["requires_regulatory_signoff"], bool)


def assert_assessment(data: dict):
    _assert_common(data, "FormulaImpactAssessment")
    assert isinstance(data["parameter_deltas"], list)
    assert isinstance(data["allergen_delta_tags"], list)
    assert isinstance(data["coo_changed"], bool)
    assert data.get("total_delta_per_unit") is not None


def assert_audit(data: dict):
    _assert_common(data, "SupplierAudit")
    assert data["status"] in AUDIT_STATUSES
    assert data["cadence_source"] in ["TIER_CADENCE", "ESCALATED"]


def assert_capa(data: dict):
    _assert_common(data, "CorrectiveAction")
    assert data["status"] in CAPA_STATUSES
    assert isinstance(data["audit_id"], str)


def assert_rebate_read(data: dict):
    """Rebate computed read shape (PRD §3.7)."""
    assert isinstance(data["contract_id"], str) and data["contract_id"]
    assert "rebate_rate" in data
    assert "accepted_value_total" in data
    assert "total_rebate" in data
    assert isinstance(data["line_count"], int)
