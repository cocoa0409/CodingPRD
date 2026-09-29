"""Entity assertions and domain invariant checkers."""

from typing import Optional

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    AmendmentPolicy,
    AmendmentStatus,
    AmendmentType,
    ApplicationStatus,
    AppraisalBasis,
    AppraisalMethod,
    AppraisalStatus,
    ClosingStatus,
    CommitmentStatus,
    ComplianceStatus,
    EasementStatus,
    FundingPlanStatus,
    LandownerStatus,
    NegotiationKind,
    OfferStructure,
    ParcelStatus,
    PermittedUse,
    ProgramStatus,
    RequirementStatus,
    RequirementType,
    RoundStatus,
    ScoreBasis,
    SourceLevel,
    SourceStatus,
    StewardshipStatus,
    VisitFinding,
    VisitStatus,
    ViolationSeverity,
    ViolationStatus,
    ViolationType,
)


def _values(enum_cls) -> list:
    return [member.value for member in enum_cls]


def assert_common_fields(data: dict, entity_label: str = "resource") -> None:
    """id + created_at + updated_at + version, as carried by thirteen of the
    fourteen resource types."""
    assert is_valid_uuid(data.get("id", "")), f"{entity_label}.id must be a UUID"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"{entity_label}.created_at must be ISO 8601, got {data.get('created_at')!r}"
    assert is_iso8601_timestamp(
        data.get("updated_at", "")
    ), f"{entity_label}.updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    assert isinstance(data.get("version"), int), f"{entity_label}.version must be int"
    assert data["version"] >= 1, f"{entity_label}.version starts at 1"


def assert_append_only_fields(data: dict, entity_label: str = "log entry") -> None:
    """id + created_at only; updated_at and version are absent entirely."""
    assert is_valid_uuid(data.get("id", "")), f"{entity_label}.id must be a UUID"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"{entity_label}.created_at must be ISO 8601"
    assert "updated_at" not in data, f"{entity_label} must not carry updated_at"
    assert "version" not in data, f"{entity_label} must not carry version"


# ---------------------------------------------------------------------------
# Per-entity assertions
# ---------------------------------------------------------------------------


def assert_program(data: dict) -> None:
    assert_common_fields(data, "program")
    assert isinstance(data["name"], str) and 1 <= len(data["name"]) <= 200
    for weight in (
        "soil_weight",
        "size_weight",
        "contiguity_weight",
        "pressure_weight",
    ):
        assert 0 <= data[weight] <= 1, f"{weight} must lie between 0 and 1"
    weight_sum = (
        data["soil_weight"]
        + data["size_weight"]
        + data["contiguity_weight"]
        + data["pressure_weight"]
    )
    assert abs(weight_sum - 1.00) < 0.005, f"weights must sum to 1.00, got {weight_sum}"
    assert 0.00 <= data["min_composite_score"] <= 100.00
    assert 1 <= data["max_negotiation_rounds"] <= 10
    assert 0 <= data["local_match_min_pct"] <= 1
    assert 0 <= data["federal_max_share_pct"] <= 1
    assert 0 <= data["impervious_allowance_pct"] <= 0.25
    assert data["amendment_policy"] in _values(AmendmentPolicy)
    assert 30 <= data["monitoring_interval_days"] <= 1095
    assert 0 <= data["monitoring_grace_days"] <= 365
    assert 0 <= data["appraisal_engagement_buffer_days"] <= 30
    assert data["status"] in _values(ProgramStatus)
    assert data["total_preserved_acres"] >= 0


def assert_funding_round(data: dict) -> None:
    assert_common_fields(data, "funding round")
    assert is_valid_uuid(data["program_id"])
    assert isinstance(data["round_label"], str) and 1 <= len(data["round_label"]) <= 80
    assert is_iso8601_timestamp(data["opens_on"])
    assert is_iso8601_timestamp(data["closes_on"])
    assert data["closes_on"] > data["opens_on"], "closes_on must be strictly later"
    assert data["pool_cents"] > 0
    assert data["status"] in _values(RoundStatus)
    assert data["score_basis"] is None or data["score_basis"] in _values(ScoreBasis)
    assert data["ranked_at"] is None or is_iso8601_timestamp(data["ranked_at"])
    assert isinstance(data["application_count"], int) and data["application_count"] >= 0
    assert isinstance(data["selected_count"], int) and data["selected_count"] >= 0


def assert_funding_source(data: dict) -> None:
    assert_common_fields(data, "funding source")
    assert is_valid_uuid(data["program_id"])
    assert isinstance(data["source_name"], str) and 1 <= len(data["source_name"]) <= 160
    assert data["level"] in _values(SourceLevel)
    assert data["authorized_cents"] > 0
    assert is_iso8601_timestamp(data["obligation_window_start"])
    assert is_iso8601_timestamp(data["obligation_window_end"])
    assert data["obligation_window_end"] > data["obligation_window_start"]
    assert 0 < data["max_share_pct"] <= 1
    assert data["priority_order"] >= 1
    assert isinstance(data["requires_match"], bool)
    assert data["match_ratio"] >= 0
    if not data["requires_match"]:
        assert data["match_ratio"] == 0, "match_ratio must be 0 when requires_match is false"
    assert 0 < data["fully_obligated_threshold_pct"] <= 1
    assert data["status"] in _values(SourceStatus)
    for ledger in ("committed_cents", "reserved_cents", "disbursed_cents", "available_cents"):
        assert data[ledger] >= 0, f"{ledger} must be non-negative"
    assert_source_ledger_conserved(data)


def assert_source_ledger_conserved(data: dict) -> None:
    """`authorized_cents` must always equal `available_cents` plus
    `committed_cents` exactly."""
    assert (
        data["authorized_cents"] == data["available_cents"] + data["committed_cents"]
    ), (
        "authorized_cents must equal available_cents + committed_cents: "
        f"{data['authorized_cents']} != {data['available_cents']} + {data['committed_cents']}"
    )


def assert_landowner(data: dict) -> None:
    assert_common_fields(data, "landowner")
    assert isinstance(data["legal_name"], str) and 1 <= len(data["legal_name"]) <= 160
    assert len(data["mailing_state"]) == 2 and data["mailing_state"].isupper()
    assert len(data["tax_id_last4"]) == 4 and data["tax_id_last4"].isdigit()
    assert data["status"] in _values(LandownerStatus)


def assert_parcel(data: dict) -> None:
    assert_common_fields(data, "parcel")
    assert is_valid_uuid(data["landowner_id"])
    assert isinstance(data["county"], str) and 1 <= len(data["county"]) <= 80
    assert data["acres"] > 0
    assert data["prime_soil_acres"] >= 0
    assert data["statewide_important_soil_acres"] >= 0
    assert (
        data["prime_soil_acres"] + data["statewide_important_soil_acres"]
        <= data["acres"] + 1e-9
    )
    assert data["contiguous_preserved_acres"] >= 0
    assert isinstance(data["road_frontage_feet"], int) and data["road_frontage_feet"] >= 0
    assert isinstance(data["sewer_available"], bool)
    assert data["zoning_min_lot_acres"] > 0
    assert isinstance(data["baseline_dwelling_rights"], int)
    assert data["baseline_dwelling_rights"] >= 0
    assert data["unrestricted_value_cents"] > 0
    assert data["restricted_value_cents"] >= 0
    assert data["status"] in _values(ParcelStatus)
    assert 0.00 <= data["soil_quality_score"] <= 100.00
    assert 0.00 <= data["development_pressure_score"] <= 100.00


def assert_application(data: dict) -> None:
    assert_common_fields(data, "application")
    assert is_valid_uuid(data["funding_round_id"])
    assert is_valid_uuid(data["parcel_id"])
    assert is_valid_uuid(data["landowner_id"])
    assert data["requested_price_cents"] > 0
    assert data["status"] in _values(ApplicationStatus)
    assert data["closing_status"] in _values(ClosingStatus)
    assert data["funding_plan_status"] in _values(FundingPlanStatus)
    assert data["contiguity_acres_at_receipt"] >= 0
    assert data["preliminary_easement_value_cents"] >= 0
    assert isinstance(data["negotiation_round_count"], int)
    assert data["negotiation_round_count"] >= 0
    if data.get("composite_score") is not None:
        assert 0.00 <= data["composite_score"] <= 100.00
    if data.get("structure") is not None:
        assert data["structure"] in _values(OfferStructure)
    if data.get("donation_pct") is not None:
        assert 0 <= data["donation_pct"] < 1
    if data.get("installment_years") is not None:
        assert 2 <= data["installment_years"] <= 10


def assert_cost_stack(data: dict) -> None:
    """`total_program_cost_cents` is `bargain_sale_price_cents` plus
    `admin_fee_cents`, over the donation-reduced negotiated amount."""
    assert (
        data["total_program_cost_cents"]
        == data["bargain_sale_price_cents"] + data["admin_fee_cents"]
    ), (
        "total_program_cost_cents must equal bargain_sale_price_cents + admin_fee_cents: "
        f"{data['total_program_cost_cents']} != "
        f"{data['bargain_sale_price_cents']} + {data['admin_fee_cents']}"
    )
    assert (
        data["proposed_price_cents"]
        == data["bargain_sale_price_cents"] + data["donation_cents"]
    ), "the donation plus the cash portion must reconstitute the negotiated amount"


def assert_installment_schedule(data: dict) -> None:
    """The early payments plus the final payment reconstitute the total exactly."""
    years = data["installment_years"]
    assert years is not None, "installment_years must be populated on an INSTALLMENT offer"
    reconstituted = (
        data["first_installment_cents"] * (years - 1) + data["final_installment_cents"]
    )
    assert reconstituted == data["total_program_cost_cents"], (
        "early payments plus the final payment must reconstitute the total: "
        f"{reconstituted} != {data['total_program_cost_cents']}"
    )


def assert_appraisal(data: dict) -> None:
    assert_common_fields(data, "appraisal")
    assert is_valid_uuid(data["application_id"])
    assert isinstance(data["appraiser_user_id"], str)
    assert 1 <= len(data["appraiser_user_id"]) <= 64
    assert isinstance(data["appraiser_firm"], str)
    assert 1 <= len(data["appraiser_firm"]) <= 160
    assert is_iso8601_timestamp(data["engagement_start"])
    assert is_iso8601_timestamp(data["engagement_end"])
    assert data["engagement_end"] >= data["engagement_start"]
    assert data["method"] in _values(AppraisalMethod)
    assert data["basis"] in _values(AppraisalBasis)
    assert data["status"] in _values(AppraisalStatus)
    assert isinstance(data["submission_count"], int) and data["submission_count"] >= 0
    assert isinstance(data["engaged_by_user_id"], str)


def assert_negotiation_round(data: dict) -> None:
    assert_append_only_fields(data, "negotiation round")
    assert is_valid_uuid(data["application_id"])
    assert data["round_index"] >= 1
    assert data["kind"] in _values(NegotiationKind)
    if data["kind"] in ("EXPIRATION", "WITHDRAWAL"):
        assert data["amount_cents"] is None, (
            f"amount_cents is null on {data['kind']} entries"
        )
    else:
        assert data["amount_cents"] is not None
    if data["kind"] != "OFFER":
        assert data.get("offer_expires_on") is None, (
            "offer_expires_on is populated only on OFFER entries"
        )
    assert isinstance(data["actor_role"], str)
    assert isinstance(data["actor_user_id"], str)


def assert_funding_commitment(data: dict) -> None:
    assert_common_fields(data, "funding commitment")
    assert is_valid_uuid(data["application_id"])
    assert is_valid_uuid(data["funding_source_id"])
    assert data["amount_cents"] > 0
    assert data["sweep_order"] >= 1
    assert data["absorbed_remainder_cents"] >= 0
    assert is_iso8601_timestamp(data["window_start"])
    assert is_iso8601_timestamp(data["window_end"])
    assert data["status"] in _values(CommitmentStatus)


def assert_closing_requirement(data: dict) -> None:
    assert_common_fields(data, "closing requirement")
    assert is_valid_uuid(data["application_id"])
    assert data["requirement_type"] in _values(RequirementType)
    assert data["status"] in _values(RequirementStatus)
    assert isinstance(data["exception_count"], int) and data["exception_count"] >= 0


def assert_easement(data: dict) -> None:
    assert_common_fields(data, "easement")
    assert is_valid_uuid(data["parcel_id"])
    assert is_valid_uuid(data["application_id"])
    assert is_iso8601_timestamp(data["recorded_on"])
    assert data["protected_acres"] > 0
    assert data["residential_rights_retained"] >= 0
    assert data["residential_rights_extinguished"] >= 0
    assert isinstance(data["subdivision_permitted"], bool)
    assert isinstance(data["permitted_uses"], list) and len(data["permitted_uses"]) >= 1
    assert len(set(data["permitted_uses"])) == len(data["permitted_uses"]), (
        "permitted_uses members must be distinct"
    )
    for use in data["permitted_uses"]:
        assert use in _values(PermittedUse), f"unknown permitted use {use}"
    assert data["status"] in _values(EasementStatus)
    assert data["stewardship_status"] in _values(StewardshipStatus)
    assert data["compliance_status"] in _values(ComplianceStatus)
    assert isinstance(data["stewardship_hold"], bool)
    assert data["impervious_allowance_sqft"] >= 0
    assert data["impervious_used_sqft"] >= 0
    assert is_iso8601_timestamp(data["next_monitoring_due_on"])
    for counter in ("open_violation_count", "pending_amendment_count", "amendment_count"):
        assert isinstance(data[counter], int) and data[counter] >= 0


def assert_rights_conserved(easement: dict, baseline_dwelling_rights: int) -> None:
    """`residential_rights_retained` plus `residential_rights_extinguished` must
    always equal the parcel's `baseline_dwelling_rights`."""
    total = (
        easement["residential_rights_retained"]
        + easement["residential_rights_extinguished"]
    )
    assert total == baseline_dwelling_rights, (
        "retained plus extinguished rights must equal baseline_dwelling_rights: "
        f"{easement['residential_rights_retained']} + "
        f"{easement['residential_rights_extinguished']} != {baseline_dwelling_rights}"
    )


def assert_monitoring_visit(data: dict) -> None:
    assert_common_fields(data, "monitoring visit")
    assert is_valid_uuid(data["easement_id"])
    assert is_iso8601_timestamp(data["window_start"])
    assert is_iso8601_timestamp(data["window_end"])
    assert data["window_end"] > data["window_start"]
    assert data["status"] in _values(VisitStatus)
    if data.get("finding") is not None:
        assert data["finding"] in _values(VisitFinding)


def assert_violation(data: dict) -> None:
    assert_common_fields(data, "violation")
    assert is_valid_uuid(data["easement_id"])
    assert data["violation_type"] in _values(ViolationType)
    assert data["severity"] in _values(ViolationSeverity)
    assert data["excess_sqft"] >= 0
    assert data["status"] in _values(ViolationStatus)
    assert is_iso8601_timestamp(data["opened_on"])
    assert is_iso8601_timestamp(data["cure_deadline_on"])


def assert_amendment(data: dict) -> None:
    assert_common_fields(data, "amendment")
    assert is_valid_uuid(data["easement_id"])
    assert data["amendment_type"] in _values(AmendmentType)
    assert data["net_conservation_benefit_cents"] >= 0
    assert data["status"] in _values(AmendmentStatus)
    assert isinstance(data["applied_rights_delta"], int)


# ---------------------------------------------------------------------------
# Cross-cutting helpers
# ---------------------------------------------------------------------------


def assert_version_advanced(before: dict, after: dict, by: int = 1) -> None:
    assert after["version"] == before["version"] + by, (
        f"version should have advanced by {by}: "
        f"{before['version']} -> {after['version']}"
    )
    assert after["updated_at"] >= before["updated_at"], (
        "updated_at must be refreshed on every mutation"
    )


def assert_two_decimals(value: float, label: str = "value") -> None:
    """Scores and acreage rollups are carried to exactly 2 decimal places."""
    assert abs(float(value) - round(float(value), 2)) < 1e-9, (
        f"{label} must be carried to 2 decimal places, got {value}"
    )


def find_requirement(requirements: list, requirement_type: str) -> Optional[dict]:
    for requirement in requirements:
        if requirement["requirement_type"] == requirement_type:
            return requirement
    return None
