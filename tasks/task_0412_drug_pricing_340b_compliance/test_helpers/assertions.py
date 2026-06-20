"""Entity assertions and domain invariant checkers for the 340B Drug Pricing &
Compliance API."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

ENTITY_TYPES = [
    "DSH", "CHILDRENS_HOSPITAL", "FREESTANDING_CANCER", "CRITICAL_ACCESS",
    "RURAL_REFERRAL", "FQHC", "RYAN_WHITE", "STD_CLINIC",
]
CE_STATUSES = ["PENDING", "ACTIVE", "RECERT_DUE", "DENIED", "TERMINATED"]
POSTURES = ["GOOD", "FLAGGED"]
MEDICAID_MODES = ["CARVE_IN", "CARVE_OUT"]
DISPENSE_STATUSES = ["DISPENSED", "REVERSED", "DISCLOSED"]
CLASSIFICATIONS = ["CLASSIFIED_340B", "CLASSIFIED_WAC"]
ELIGIBILITY_REASONS = [
    "ELIGIBLE_340B", "INELIGIBLE_NO_RELATIONSHIP", "INELIGIBLE_NO_RESPONSIBILITY",
    "INELIGIBLE_PRESCRIBER", "INELIGIBLE_UNREGISTERED_SITE", "CARVED_OUT_MEDICAID",
]
PRICING_VARIANTS = ["STANDARD", "PENNY"]
ARRANGEMENT_STATUSES = ["ACTIVE", "SUSPENDED", "TERMINATED"]
CLAIM_STATUSES = ["CLEAN", "DUPLICATE_RISK", "VOIDED"]
FINDING_TYPES = ["DIVERSION", "DUPLICATE_DISCOUNT", "GPO_VIOLATION", "INELIGIBLE_PATIENT"]
FINDING_ORIGINS = ["SELF_DISCLOSURE", "HRSA_AUDIT"]
FINDING_STATUSES = ["OPEN", "UNDER_REVIEW", "DISPUTED", "RESOLVED", "DISMISSED"]
SOURCE_KINDS = ["AUDIT_FINDING", "CEILING_RECONCILIATION"]
REPAYMENT_STATUSES = ["OWED", "PARTIALLY_PAID", "SETTLED", "WAIVED"]
CHANNELS = ["GPO", "WAC", "B340B"]


def _assert_full_entity_fields(data: dict):
    """id + created_at + updated_at + version for full (common_fields:true) entities."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, "version starts at 1"


def _assert_append_only_fields(data: dict):
    """id + created_at only for append-only (common_fields:false) entities."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"


def assert_covered_entity(data: dict):
    _assert_full_entity_fields(data)
    assert isinstance(data["hrsa_id"], str) and len(data["hrsa_id"]) > 0
    assert isinstance(data["legal_name"], str)
    assert data["entity_type"] in ENTITY_TYPES
    assert isinstance(data["gpo_prohibited"], bool)
    assert data["medicaid_billing_mode"] in MEDICAID_MODES
    assert data["registration_status"] in CE_STATUSES
    assert isinstance(data["recert_period_index"], int) and data["recert_period_index"] >= 0
    assert data["compliance_posture"] in POSTURES
    assert isinstance(data["open_repayment_cents"], int) and data["open_repayment_cents"] >= 0


def assert_child_site(data: dict):
    _assert_full_entity_fields(data)
    assert isinstance(data["covered_entity_id"], str)
    assert isinstance(data["site_name"], str)
    assert isinstance(data["service_address"], str)
    assert isinstance(data["registered"], bool)


def assert_prescriber(data: dict):
    # common_fields:false — only id + created_at; no version / updated_at.
    _assert_append_only_fields(data)
    assert isinstance(data["covered_entity_id"], str)
    assert isinstance(data["npi"], str) and len(data["npi"]) > 0
    assert isinstance(data["full_name"], str)
    assert data["relationship_type"] in ["EMPLOYED", "CONTRACTED", "REFERRAL_ONLY", "EXTERNAL"]


def assert_patient(data: dict):
    _assert_full_entity_fields(data)
    assert isinstance(data["covered_entity_id"], str)
    assert isinstance(data["mrn"], str)
    assert isinstance(data["has_ce_care_record"], bool)
    assert isinstance(data["ce_retains_responsibility"], bool)
    assert isinstance(data["medicaid_ffs_enrolled"], bool)


def assert_drug_product(data: dict):
    _assert_full_entity_fields(data)
    assert isinstance(data["ndc"], str) and len(data["ndc"]) > 0
    assert isinstance(data["drug_name"], str)
    assert isinstance(data["package_size_units"], int) and data["package_size_units"] >= 1
    assert isinstance(data["is_covered_outpatient_drug"], bool)
    assert isinstance(data["wac_price_per_unit_cents"], int) and data["wac_price_per_unit_cents"] >= 0


def assert_ceiling_price_record(data: dict):
    _assert_full_entity_fields(data)
    assert isinstance(data["drug_product_id"], str)
    assert isinstance(data["quarter"], str)
    assert isinstance(data["amp_per_unit_cents"], int) and data["amp_per_unit_cents"] >= 0
    assert isinstance(data["ura_per_unit_cents"], int) and data["ura_per_unit_cents"] >= 0
    assert isinstance(data["is_published"], bool)
    assert isinstance(data["ceiling_price_per_unit_cents"], int) and data["ceiling_price_per_unit_cents"] >= 0
    assert data["pricing_variant"] in PRICING_VARIANTS


def assert_contract_pharmacy(data: dict):
    _assert_full_entity_fields(data)
    assert isinstance(data["covered_entity_id"], str)
    assert isinstance(data["pharmacy_name"], str)
    assert isinstance(data["ship_to_bill_to_npi"], str)
    assert isinstance(data["effective_start"], str)
    assert isinstance(data["effective_end"], str)
    assert data["arrangement_status"] in ARRANGEMENT_STATUSES


def assert_accumulator(data: dict):
    _assert_full_entity_fields(data)
    assert isinstance(data["covered_entity_id"], str)
    assert isinstance(data["drug_product_id"], str)
    assert isinstance(data["accrued_units"], int) and data["accrued_units"] >= 0
    assert isinstance(data["replenished_packages_total"], int) and data["replenished_packages_total"] >= 0


def assert_dispense(data: dict):
    _assert_full_entity_fields(data)
    assert isinstance(data["covered_entity_id"], str)
    assert isinstance(data["patient_id"], str)
    assert isinstance(data["prescriber_id"], str)
    assert isinstance(data["drug_product_id"], str)
    assert isinstance(data["quantity_units"], int) and data["quantity_units"] >= 1
    assert isinstance(data["quarter"], str)
    assert data["dispense_status"] in DISPENSE_STATUSES
    assert data["classification_status"] in CLASSIFICATIONS
    assert data["eligibility_reason"] in ELIGIBILITY_REASONS
    assert isinstance(data["applied_price_per_unit_cents"], int) and data["applied_price_per_unit_cents"] >= 0
    assert isinstance(data["line_cost_cents"], int) and data["line_cost_cents"] >= 0


def assert_medicaid_claim(data: dict):
    _assert_full_entity_fields(data)
    assert isinstance(data["prescription_dispense_id"], str)
    assert isinstance(data["medicaid_state_code"], str)
    assert data["claim_status"] in CLAIM_STATUSES


def assert_audit_finding(data: dict):
    _assert_full_entity_fields(data)
    assert isinstance(data["covered_entity_id"], str)
    assert isinstance(data["prescription_dispense_id"], str)
    assert data["finding_type"] in FINDING_TYPES
    assert data["origin"] in FINDING_ORIGINS
    assert data["finding_status"] in FINDING_STATUSES
    assert isinstance(data["assessed_units"], int) and data["assessed_units"] >= 1


def assert_repayment_obligation(data: dict):
    _assert_full_entity_fields(data)
    assert isinstance(data["covered_entity_id"], str)
    assert data["source_kind"] in SOURCE_KINDS
    assert isinstance(data["source_ref_id"], str)
    assert isinstance(data["assessed_cents"], int) and data["assessed_cents"] >= 0
    assert isinstance(data["paid_cents"], int) and data["paid_cents"] >= 0
    assert isinstance(data["remaining_balance_cents"], int) and data["remaining_balance_cents"] >= 0
    assert data["status"] in REPAYMENT_STATUSES


def assert_purchase_order(data: dict):
    _assert_full_entity_fields(data)
    assert isinstance(data["covered_entity_id"], str)
    assert isinstance(data["drug_product_id"], str)
    assert data["channel"] in CHANNELS
    assert isinstance(data["packages_ordered"], int) and data["packages_ordered"] >= 1
    assert isinstance(data["quarter"], str)
    assert isinstance(data["unit_price_paid_cents"], int) and data["unit_price_paid_cents"] >= 0


# ---------------------------------------------------------------------------
# Domain invariant checkers
# ---------------------------------------------------------------------------
def assert_repayment_balance_invariant(data: dict):
    """remaining_balance_cents == assessed_cents - paid_cents, never negative (PRD §3.9)."""
    assert data["remaining_balance_cents"] == data["assessed_cents"] - data["paid_cents"], (
        "remaining_balance_cents must equal assessed_cents - paid_cents"
    )
    assert data["remaining_balance_cents"] >= 0, "remaining_balance_cents is never negative"


def assert_accumulator_remainder_invariant(data: dict, package_size: int):
    """After any replenish sweep, accrued_units sits in [0, package_size - 1] (PRD §3.6)."""
    assert 0 <= data["accrued_units"] <= package_size - 1, (
        f"accrued_units {data['accrued_units']} must be in [0, {package_size - 1}]"
    )
