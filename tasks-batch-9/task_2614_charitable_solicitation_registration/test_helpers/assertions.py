"""Entity assertions and domain invariant checkers."""

from typing import Any, Dict, List

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    ASSURANCE_SCALE,
    CANONICAL_CLAUSE_ORDER,
    CANONICAL_TRIGGER_REASON_ORDER,
    ActionType,
    AssuranceBasis,
    AssuranceLevel,
    CompensationType,
    ContractStatus,
    DisclosureComplianceStatus,
    DocType,
    DocumentReviewStatus,
    EnforcementStatus,
    ExtensionBasis,
    ExtensionStatus,
    FilingPosture,
    FundraiserRegistrationStatus,
    FundraiserType,
    MaterialType,
    OfficerDisclosureStatus,
    OfficerTitle,
    OrganizationLifecycleStatus,
    PromotionStatus,
    RegistrationStatus,
    RegistrationType,
    RegistryStatus,
    RenewalDueRule,
    SolicitationChannel,
    SolicitationPosture,
    StatementStatus,
)


# --------------------------------------------------------------------------
# Shared shape helpers
# --------------------------------------------------------------------------


def assert_common_fields(data: Dict[str, Any]) -> None:
    """id is a bare UUID, created_at/updated_at are ISO 8601, version is an int."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a bare UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"created_at must be ISO 8601 UTC, got {data.get('created_at')!r}"
    assert is_iso8601_timestamp(
        data.get("updated_at", "")
    ), f"updated_at must be ISO 8601 UTC, got {data.get('updated_at')!r}"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, "version starts at 1 on creation"


def assert_event_fields(data: Dict[str, Any]) -> None:
    """An immutable event record carries id and created_at only."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a bare UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"created_at must be ISO 8601 UTC, got {data.get('created_at')!r}"
    assert "updated_at" not in data, "an immutable event record carries no updated_at"
    assert "version" not in data, "an immutable event record carries no version"


def assert_midnight_utc(value: str, label: str = "date") -> None:
    """Derived deadlines land at midnight UTC."""
    assert isinstance(value, str) and value, f"{label} must be a timestamp string"
    assert value[11:19] == "00:00:00", f"{label} must land at midnight UTC, got {value!r}"


def assert_date_equals(actual: str, expected_date: str, label: str = "date") -> None:
    """Compare a stamped instant against an expected calendar date at midnight UTC."""
    assert isinstance(actual, str) and actual, f"{label} must be a timestamp string, got {actual!r}"
    assert actual[:10] == expected_date, f"{label} must be {expected_date}, got {actual!r}"
    assert_midnight_utc(actual, label)


def assert_canonical_clause_order(clauses: List[str], label: str = "clauses") -> None:
    """Every derived clause array is emitted in the canonical clause order."""
    indexes = [CANONICAL_CLAUSE_ORDER.index(c) for c in clauses]
    assert indexes == sorted(indexes), f"{label} must follow the canonical clause order, got {clauses}"


def assert_canonical_trigger_order(reasons: List[str]) -> None:
    indexes = [CANONICAL_TRIGGER_REASON_ORDER.index(r) for r in reasons]
    assert indexes == sorted(
        indexes
    ), f"trigger_reasons must be DONOR_COUNT, CONTRIBUTION_TOTAL, TARGETED_ONLINE_PRESENCE, got {reasons}"


# --------------------------------------------------------------------------
# Per-entity assertions
# --------------------------------------------------------------------------


def assert_organization(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert isinstance(data["legal_name"], str) and 1 <= len(data["legal_name"]) <= 200
    assert isinstance(data["ein"], str) and data["ein"].isdigit() and len(data["ein"]) == 9
    assert isinstance(data["domicile_state_code"], str) and len(data["domicile_state_code"]) == 2
    assert 1 <= data["fiscal_year_end_month"] <= 12
    assert isinstance(data["has_online_donation_page"], bool)
    assert data["lifecycle_status"] in [s.value for s in OrganizationLifecycleStatus]
    assert data["solicitation_posture"] in [s.value for s in SolicitationPosture]
    assert data["filing_posture"] in [s.value for s in FilingPosture]
    assert isinstance(data["registered_state_count"], int) and data["registered_state_count"] >= 0
    assert (
        isinstance(data["delinquent_registration_count"], int)
        and data["delinquent_registration_count"] >= 0
    )
    assert isinstance(data["ceased_state_codes"], list)
    assert data["ceased_state_codes"] == sorted(
        data["ceased_state_codes"]
    ), "ceased_state_codes is held in ascending order"
    assert isinstance(data["penalty_outstanding_cents"], int)
    assert data["penalty_outstanding_cents"] >= 0


def assert_state_profile(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2
    assert data["state_code"].isupper()
    assert isinstance(data["registration_required"], bool)
    assert data["renewal_due_rule"] in [r.value for r in RenewalDueRule]
    assert data["assurance_basis"] in [b.value for b in AssuranceBasis]
    assert data["review_threshold_cents"] >= 0
    assert data["audit_threshold_cents"] >= data["review_threshold_cents"]


def assert_solicitation_activity(data: Dict[str, Any]) -> None:
    assert_event_fields(data)
    assert is_valid_uuid(data["organization_id"])
    assert len(data["state_code"]) == 2
    assert 2000 <= data["fiscal_year"] <= 2100
    assert data["donor_count"] >= 0
    assert data["contributions_cents"] >= 0
    assert isinstance(data["channels"], list) and len(data["channels"]) >= 1
    for channel in data["channels"]:
        assert channel in [c.value for c in SolicitationChannel]
    assert isinstance(data["triggers_registration"], bool)
    assert isinstance(data["trigger_reasons"], list)
    assert_canonical_trigger_order(data["trigger_reasons"])
    assert data["triggers_registration"] == (len(data["trigger_reasons"]) > 0)


def assert_financial_statement(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["organization_id"])
    assert 2000 <= data["fiscal_year"] <= 2100
    assert data["total_revenue_cents"] >= data["contributions_cents"]
    assert data["government_grant_cents"] >= 0
    assert data["program_expense_cents"] >= 0
    assert data["fundraising_expense_cents"] >= 0
    assert data["management_expense_cents"] >= 0
    assert data["assurance_level"] in [a.value for a in AssuranceLevel]
    assert data["statement_status"] in [s.value for s in StatementStatus]
    expected_total = (
        data["program_expense_cents"]
        + data["fundraising_expense_cents"]
        + data["management_expense_cents"]
    )
    assert data["functional_expense_total_cents"] == expected_total, (
        "functional_expense_total_cents is the sum of the program, fundraising and "
        f"management expense amounts; expected {expected_total}, got "
        f"{data['functional_expense_total_cents']}"
    )
    assert isinstance(data["program_ratio"], (int, float))


def assert_officer_disclosure(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["organization_id"])
    assert isinstance(data["officer_name"], str) and data["officer_name"]
    assert data["title"] in [t.value for t in OfficerTitle]
    assert isinstance(data["is_certifying_officer"], bool)
    assert data["annual_compensation_cents"] >= 0
    assert isinstance(data["criminal_conviction_disclosed"], bool)
    assert data["disclosure_status"] in [s.value for s in OfficerDisclosureStatus]
    expected = (
        OfficerDisclosureStatus.INCOMPLETE.value
        if data["criminal_conviction_disclosed"]
        and not (data.get("conviction_explanation") or "")
        else OfficerDisclosureStatus.COMPLETE.value
    )
    assert data["disclosure_status"] == expected, (
        "disclosure_status is INCOMPLETE only when criminal_conviction_disclosed is true "
        f"while conviction_explanation is null or empty; expected {expected}"
    )


def assert_state_registration(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["organization_id"])
    assert len(data["state_code"]) == 2
    assert data["registration_type"] in [t.value for t in RegistrationType]
    assert 2000 <= data["fiscal_year"] <= 2100
    assert data["coverage_end"] > data["coverage_start"]
    assert is_valid_uuid(data["financial_statement_id"])
    assert data["status"] in [s.value for s in RegistrationStatus]
    assert_midnight_utc(data["renewal_due_date"], "renewal_due_date")
    assert data["required_financial_attestation"] in ASSURANCE_SCALE
    assert isinstance(data["filing_fee_cents"], int) and data["filing_fee_cents"] >= 0
    assert data["deficiency_round_count"] >= 0
    assert isinstance(data["deficiency_reasons"], list)
    expected_effective = data.get("extended_due_date") or data["renewal_due_date"]
    assert data["effective_due_date"] == expected_effective, (
        "effective_due_date is extended_due_date when that is non-null and "
        f"renewal_due_date otherwise; expected {expected_effective}, got "
        f"{data['effective_due_date']}"
    )


def assert_registration_document(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["registration_id"])
    assert data["doc_type"] in [d.value for d in DocType]
    assert is_valid_uuid(data["prepared_by_officer_id"])
    assert data["page_count"] >= 1
    assert data["review_status"] in [s.value for s in DocumentReviewStatus]


def assert_extension_request(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["registration_id"])
    assert data["basis"] in [b.value for b in ExtensionBasis]
    assert data["requested_days"] >= 1
    assert data["status"] in [s.value for s in ExtensionStatus]
    assert data["granted_days"] >= 0


def assert_professional_fundraiser(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert data["fundraiser_type"] in [t.value for t in FundraiserType]
    assert data["bond_amount_cents"] >= 0
    assert isinstance(data["bond_expires_at"], str) and data["bond_expires_at"]
    assert data["registry_status"] in [s.value for s in RegistryStatus]


def assert_fundraiser_registration(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["fundraiser_id"])
    assert len(data["state_code"]) == 2
    assert data["bond_on_file_cents"] >= 0
    assert data["status"] in [s.value for s in FundraiserRegistrationStatus]


def assert_fundraising_contract(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["organization_id"])
    assert is_valid_uuid(data["fundraiser_id"])
    assert isinstance(data["state_codes"], list) and len(data["state_codes"]) >= 1
    assert data["contract_end"] > data["contract_start"]
    assert data["compensation_type"] in [c.value for c in CompensationType]
    assert 0 <= data["percent_of_gross"] <= 1
    assert data["flat_fee_cents"] >= 0
    assert data["status"] in [s.value for s in ContractStatus]
    assert_midnight_utc(data["filing_due_date"], "filing_due_date")
    assert data["late_filing_surcharge_cents"] >= 0


def assert_coventure_promotion(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["organization_id"])
    assert is_valid_uuid(data["coventurer_id"])
    assert isinstance(data["state_codes"], list) and len(data["state_codes"]) >= 1
    assert data["promo_end"] >= data["promo_start"]
    assert data["guaranteed_minimum_cents"] >= 0
    assert data["per_unit_cents"] >= 0
    assert data["projected_units"] >= 0
    assert data["status"] in [s.value for s in PromotionStatus]
    assert isinstance(data["disclosure_clause_required"], bool)
    expected_projection = max(
        data["guaranteed_minimum_cents"], data["per_unit_cents"] * data["projected_units"]
    )
    assert data["projected_benefit_cents"] == expected_projection, (
        "projected_benefit_cents is the larger of guaranteed_minimum_cents and the "
        f"product of per_unit_cents and projected_units; expected {expected_projection}"
    )
    assert data["actual_units"] >= 0
    assert data["remitted_cents"] >= 0
    assert data["final_benefit_cents"] >= 0
    assert data["shortfall_cents"] >= 0


def assert_disclosure_statement(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["organization_id"])
    assert len(data["state_code"]) == 2
    assert data["material_type"] in [m.value for m in MaterialType]
    assert isinstance(data["included_clauses"], list)
    assert isinstance(data["required_clauses"], list)
    assert isinstance(data["missing_clauses"], list)
    assert_canonical_clause_order(data["required_clauses"], "required_clauses")
    assert_canonical_clause_order(data["missing_clauses"], "missing_clauses")
    expected_missing = [
        c for c in data["required_clauses"] if c not in data["included_clauses"]
    ]
    assert data["missing_clauses"] == expected_missing, (
        "missing_clauses is the members of required_clauses absent from "
        f"included_clauses, in canonical order; expected {expected_missing}"
    )
    expected_status = (
        DisclosureComplianceStatus.COMPLIANT.value
        if not data["missing_clauses"]
        else DisclosureComplianceStatus.NON_COMPLIANT.value
    )
    assert data["compliance_status"] == expected_status, (
        "compliance_status is COMPLIANT when missing_clauses is empty and "
        f"NON_COMPLIANT otherwise; expected {expected_status}"
    )


def assert_enforcement_action(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["organization_id"])
    assert is_valid_uuid(data["registration_id"])
    assert len(data["state_code"]) == 2
    assert data["action_type"] in [t.value for t in ActionType]
    assert isinstance(data["penalty_cents"], int) and data["penalty_cents"] >= 0
    assert data["status"] in [s.value for s in EnforcementStatus]
    assert is_iso8601_timestamp(data["issued_at"])
    assert data["settlement_total_cents"] >= 0


# --------------------------------------------------------------------------
# Domain invariant checkers
# --------------------------------------------------------------------------


def assert_penalty_ledger_conserved(
    organization: Dict[str, Any], actions: List[Dict[str, Any]]
) -> None:
    """penalty_outstanding_cents is the sum of penalty_cents over the
    organization's actions in OPEN, REMEDIATION_SUBMITTED or ESCALATED."""
    live = {
        EnforcementStatus.OPEN.value,
        EnforcementStatus.REMEDIATION_SUBMITTED.value,
        EnforcementStatus.ESCALATED.value,
    }
    expected = sum(a["penalty_cents"] for a in actions if a["status"] in live)
    assert organization["penalty_outstanding_cents"] == expected, (
        "penalty_outstanding_cents must equal the sum of penalty_cents over actions in "
        f"OPEN, REMEDIATION_SUBMITTED or ESCALATED; expected {expected}, got "
        f"{organization['penalty_outstanding_cents']}"
    )


def assert_registration_counters_conserved(
    organization: Dict[str, Any], registrations: List[Dict[str, Any]]
) -> None:
    """registered_state_count and delinquent_registration_count are exact counts."""
    expected_registered = sum(
        1 for r in registrations if r["status"] == RegistrationStatus.REGISTERED.value
    )
    expected_delinquent = sum(
        1 for r in registrations if r["status"] == RegistrationStatus.DELINQUENT.value
    )
    assert organization["registered_state_count"] == expected_registered, (
        "registered_state_count must equal the number of registrations in REGISTERED; "
        f"expected {expected_registered}, got {organization['registered_state_count']}"
    )
    assert organization["delinquent_registration_count"] == expected_delinquent, (
        "delinquent_registration_count must equal the number in DELINQUENT; expected "
        f"{expected_delinquent}, got {organization['delinquent_registration_count']}"
    )


def assert_posture_dimensions(organization: Dict[str, Any]) -> None:
    """solicitation_posture follows ceased_state_codes; filing_posture follows the
    delinquent count."""
    ceased = organization["ceased_state_codes"]
    domicile = organization["domicile_state_code"]
    if not ceased:
        expected_solicitation = SolicitationPosture.CLEAR.value
    elif domicile in ceased or len(ceased) >= 2:
        expected_solicitation = SolicitationPosture.HALTED.value
    else:
        expected_solicitation = SolicitationPosture.RESTRICTED.value
    assert organization["solicitation_posture"] == expected_solicitation, (
        f"solicitation_posture must be {expected_solicitation} for ceased_state_codes "
        f"{ceased} and domicile {domicile}"
    )
    expected_filing = (
        FilingPosture.DELINQUENT.value
        if organization["delinquent_registration_count"] >= 1
        else FilingPosture.CURRENT.value
    )
    assert organization["filing_posture"] == expected_filing, (
        f"filing_posture must be {expected_filing} for delinquent count "
        f"{organization['delinquent_registration_count']}"
    )
