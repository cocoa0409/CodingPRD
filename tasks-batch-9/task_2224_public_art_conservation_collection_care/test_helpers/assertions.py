"""Entity assertions and domain invariant checkers for the conservation register."""

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    AbortReason,
    Accreditation,
    AllocationPurpose,
    AllocationStatus,
    AssessmentStatus,
    CaseStatus,
    ClaimBasis,
    ClaimStatus,
    ConservationStatus,
    ConservatorStatus,
    ConsultationStatus,
    ConsultationSubject,
    CustodyStatus,
    DamageStatus,
    Disposition,
    ExposureClass,
    IncidentType,
    MaterialClass,
    MoralRightsStatus,
    NoticeActionType,
    NoticeStatus,
    PoolType,
    PriorityBasis,
    ProposalStatus,
    ProtocolMethod,
    Recommendation,
    ReleaseReason,
    SignificanceTier,
    SolventClass,
    TreatmentScope,
    TriageClass,
    VisitStatus,
    WithdrawReason,
)


def _members(enum_cls) -> list:
    return [member.value for member in enum_cls]


def assert_common_record_properties(data: dict) -> None:
    """Every record carries id, created_at, updated_at and version (PRD §2.5)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')}"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"created_at must be ISO 8601, got {data.get('created_at')}"
    assert is_iso8601_timestamp(
        data.get("updated_at", "")
    ), f"updated_at must be ISO 8601, got {data.get('updated_at')}"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, f"version must start at 1 or more, got {data['version']}"


def assert_artist(data: dict) -> None:
    assert_common_record_properties(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["is_living"], bool)
    assert isinstance(data["contact_email"], str) and data["contact_email"]
    assert isinstance(data["artwork_count"], int) and data["artwork_count"] >= 0
    if data["is_living"]:
        assert data.get("deceased_on") is None, "a living artist has no deceased_on"


def assert_site(data: dict) -> None:
    assert_common_record_properties(data)
    assert isinstance(data["site_code"], str) and data["site_code"]
    assert data["exposure_class"] in _members(ExposureClass)
    assert isinstance(data["capacity_units"], int) and data["capacity_units"] >= 0
    assert (
        isinstance(data["concurrent_work_capacity"], int)
        and data["concurrent_work_capacity"] >= 1
    )
    assert isinstance(data["installed_units_used"], int)
    assert 0 <= data["installed_units_used"] <= data["capacity_units"], (
        "installed_units_used must never exceed capacity_units, got "
        f"{data['installed_units_used']} of {data['capacity_units']}"
    )


def assert_artwork(data: dict) -> None:
    assert_common_record_properties(data)
    assert isinstance(data["accession_number"], str) and data["accession_number"]
    assert data["material_class"] in _members(MaterialClass)
    assert data["significance_tier"] in _members(SignificanceTier)
    assert isinstance(data["footprint_units"], int) and data["footprint_units"] >= 1
    assert isinstance(data["insured_value_cents"], int)
    assert data["insured_value_cents"] >= 0
    assert data["custody_status"] in _members(CustodyStatus)
    assert data["conservation_status"] in _members(ConservationStatus)
    assert data["moral_rights_status"] in _members(MoralRightsStatus)
    assert data["priority_basis"] in _members(PriorityBasis)
    assert isinstance(data["open_notice_count"], int) and data["open_notice_count"] >= 0
    if data.get("condition_index") is not None:
        assert_condition_index_precision(data["condition_index"])
    if data.get("treatment_priority_score") is not None:
        assert_priority_score_precision(data["treatment_priority_score"])


def assert_maintenance_protocol(data: dict) -> None:
    assert_common_record_properties(data)
    assert isinstance(data["protocol_code"], str) and data["protocol_code"]
    assert data["material_class"] in _members(MaterialClass)
    assert data["method"] in _members(ProtocolMethod)
    assert 1 <= data["cycle_days"] <= 3650
    assert data["max_annual_applications"] >= 1
    assert isinstance(data["requires_conservator"], bool)
    assert data["solvent_class"] in _members(SolventClass)


def assert_maintenance_visit(data: dict) -> None:
    assert_common_record_properties(data)
    assert data["status"] in _members(VisitStatus)
    assert data["abort_reason"] in _members(AbortReason)
    assert isinstance(data["sla_breached"], bool)
    assert data["window_end"] > data["window_start"], (
        "window_end must be strictly after window_start, got "
        f"{data['window_start']}..{data['window_end']}"
    )


def assert_condition_assessment(data: dict) -> None:
    assert_common_record_properties(data)
    assert data["status"] in _members(AssessmentStatus)
    assert data["recommendation"] in _members(Recommendation)
    assert 2000 <= data["cycle_year"] <= 2100
    for field in (
        "surface_score",
        "structural_score",
        "coating_score",
        "mount_score",
        "graffiti_score",
    ):
        assert 0 <= data[field] <= 4, f"{field} must be between 0 and 4"
    assert isinstance(data["photo_count"], int) and data["photo_count"] >= 0
    assert isinstance(data["photo_view_codes"], list)
    assert isinstance(data["revision_rounds"], int) and data["revision_rounds"] >= 0
    if data.get("condition_index") is not None:
        assert_condition_index_precision(data["condition_index"])


def assert_conservator(data: dict) -> None:
    assert_common_record_properties(data)
    assert isinstance(data["firm_name"], str) and data["firm_name"]
    assert data["accreditation"] in _members(Accreditation)
    assert isinstance(data["material_specialties"], list)
    assert data["material_specialties"], "material_specialties must be non-empty"
    for specialty in data["material_specialties"]:
        assert specialty in _members(MaterialClass)
    assert data["hourly_rate_cents"] >= 1
    assert data["status"] in _members(ConservatorStatus)
    assert (
        isinstance(data["active_engagement_count"], int)
        and data["active_engagement_count"] >= 0
    )


def assert_treatment_proposal(data: dict) -> None:
    assert_common_record_properties(data)
    assert data["status"] in _members(ProposalStatus)
    assert data["treatment_scope"] in _members(TreatmentScope)
    assert data["withdraw_reason"] in _members(WithdrawReason)
    assert isinstance(data["line_items"], list)
    assert data["engagement_end"] > data["engagement_start"]
    for field in (
        "subtotal_cents",
        "overhead_cents",
        "contingency_cents",
        "mobilization_cents",
        "estimate_total_cents",
    ):
        assert isinstance(data[field], int), f"{field} must be an integer cent amount"
        assert data[field] >= 0
    if data.get("pinned_estimate_total_cents") is not None:
        assert isinstance(data["pinned_estimate_total_cents"], int)


def assert_artist_consultation(data: dict) -> None:
    assert_common_record_properties(data)
    assert data["subject"] in _members(ConsultationSubject)
    assert data["status"] in _members(ConsultationStatus)


def assert_moral_rights_notice(data: dict) -> None:
    assert_common_record_properties(data)
    assert data["action_type"] in _members(NoticeActionType)
    assert data["status"] in _members(NoticeStatus)


def assert_deaccession_case(data: dict) -> None:
    assert_common_record_properties(data)
    assert data["status"] in _members(CaseStatus)
    assert data["disposition"] in _members(Disposition)
    assert isinstance(data["criteria"], list) and data["criteria"]
    assert isinstance(data["vote_records"], list)
    for counter in ("approve_count", "deny_count", "abstain_count", "recuse_count"):
        assert isinstance(data[counter], int) and data[counter] >= 0
    assert 7 <= data["comment_days"] <= 180


def assert_funding_pool(data: dict) -> None:
    assert_common_record_properties(data)
    assert data["pool_type"] in _members(PoolType)
    assert 2000 <= data["fiscal_year"] <= 2100
    for field in (
        "admin_fee_cents",
        "draw_authorized_cents",
        "recovery_credits_cents",
        "available_cents",
    ):
        assert isinstance(data[field], int), f"{field} must be an integer cent amount"


def assert_funding_allocation(data: dict) -> None:
    assert_common_record_properties(data)
    assert data["status"] in _members(AllocationStatus)
    assert data["purpose"] in _members(AllocationPurpose)
    assert data["release_reason"] in _members(ReleaseReason)
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] >= 1
    if data["purpose"] == AllocationPurpose.TREATMENT.value:
        assert data.get("proposal_id") is not None
        assert data.get("visit_id") is None
    else:
        assert data.get("visit_id") is not None
        assert data.get("proposal_id") is None


def assert_damage_incident(data: dict) -> None:
    assert_common_record_properties(data)
    assert data["incident_type"] in _members(IncidentType)
    assert data["damage_status"] in _members(DamageStatus)
    assert data["claim_status"] in _members(ClaimStatus)
    assert data["triage_class"] in _members(TriageClass)
    assert data["claim_basis"] in _members(ClaimBasis)
    assert 0.0 <= data["damage_extent_pct"] <= 1.0
    assert isinstance(data["claimed_gross_cents"], int)
    assert isinstance(data["settlement_cents"], int)
    assert data["settlement_cents"] >= 0


# --------------------------------------------------------------------------
# Domain invariant checkers
# --------------------------------------------------------------------------
def assert_condition_index_precision(index: float) -> None:
    """A condition index is carried to exactly one decimal place and floored at 0.0."""
    assert index >= 0.0, f"condition_index is floored at 0.0, got {index}"
    assert round(float(index), 1) == float(index), (
        f"condition_index must carry exactly one decimal place, got {index}"
    )


def assert_priority_score_precision(score: float) -> None:
    """A treatment priority score is carried to exactly two decimal places."""
    assert round(float(score), 2) == float(score), (
        f"treatment_priority_score must carry exactly two decimal places, got {score}"
    )


def assert_integer_cents(value, label: str = "amount") -> None:
    """All monetary quantities are integers denominated in cents (PRD §2.10)."""
    assert isinstance(value, int) and not isinstance(value, bool), (
        f"{label} must be an integer number of cents, got {value!r}"
    )


def assert_pool_availability_identity(pool: dict, encumbered_cents: int) -> None:
    """available = draw_authorized + recovery_credits - encumbered (PRD §3.10)."""
    expected = (
        pool["draw_authorized_cents"] + pool["recovery_credits_cents"] - encumbered_cents
    )
    assert pool["available_cents"] == expected, (
        f"available_cents must equal draw_authorized_cents "
        f"{pool['draw_authorized_cents']} plus recovery_credits_cents "
        f"{pool['recovery_credits_cents']} less encumbrances {encumbered_cents}; "
        f"got {pool['available_cents']}, expected {expected}"
    )


def assert_estimate_breakdown(proposal: dict) -> None:
    """estimate_total is the sum of its four declared components (PRD §3.4)."""
    total = (
        proposal["subtotal_cents"]
        + proposal["overhead_cents"]
        + proposal["contingency_cents"]
        + proposal["mobilization_cents"]
    )
    assert proposal["estimate_total_cents"] == total, (
        "estimate_total_cents must be the sum of subtotal, overhead, contingency and "
        f"mobilization ({total}); got {proposal['estimate_total_cents']}"
    )


def assert_no_version_change(before: dict, after: dict, label: str = "record") -> None:
    """A rejected request must leave the target record untouched."""
    assert after["version"] == before["version"], (
        f"{label} version must be unchanged after a rejected request: was "
        f"{before['version']}, now {after['version']}"
    )
