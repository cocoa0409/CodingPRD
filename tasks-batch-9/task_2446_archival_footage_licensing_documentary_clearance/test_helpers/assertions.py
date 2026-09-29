"""Entity assertions and domain invariant checkers for the Archival Clearance API."""
from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)

from .types import (
    ArchiveHolderType,
    ArchiveMfnPolicy,
    ArchiveStatus,
    AssetDepictionStatus,
    AssetLicensingStatus,
    AssetRightsBasis,
    AssetType,
    AssetUsagePurpose,
    ClearanceChartStatus,
    DeliveryPackageStatus,
    EOApplicationStatus,
    EOReviewStatus,
    FairUseAnalysisStatus,
    FairUseWeightingVariant,
    LicenseMedia,
    LicenseRightsLeg,
    LicenseStatus,
    LicenseTerritory,
    LicenseWindowClass,
    LIVE_LICENSE_STATUSES,
    NegotiationParty,
    OpinionLetterRiskRating,
    OpinionLetterStatus,
    ProductionPosture,
    ProductionStatus,
    RateCardStatus,
    SourceCandidateAvailability,
    SourceCandidateSelectionStatus,
    SubjectReleaseApprovalRights,
    SubjectReleaseStatus,
    SubjectReleaseType,
)


# ─── Shared structural helpers ───────────────────────────────────────────────

def _values(enum_cls) -> List[str]:
    return [member.value for member in enum_cls]


def assert_identity_fields(data: Dict[str, Any], entity: str = "resource") -> None:
    """PRD §2.4: a server-minted UUID `id` with no type prefix, plus `created_at`."""
    assert is_valid_uuid(data.get("id", "")), (
        f"{entity}.id must be a UUID string with no type prefix, got {data.get('id')!r}")
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity}.created_at must be an ISO 8601 UTC timestamp, got {data.get('created_at')!r}")


def assert_versioned_fields(data: Dict[str, Any], entity: str = "resource") -> None:
    """PRD §2.4: most resources additionally carry `updated_at` and an integer `version`."""
    assert_identity_fields(data, entity)
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity}.updated_at must be an ISO 8601 UTC timestamp, got {data.get('updated_at')!r}")
    assert isinstance(data.get("version"), int), (
        f"{entity}.version must be an integer, got {data.get('version')!r}")
    assert data["version"] >= 1, f"{entity}.version starts at 1, got {data['version']}"


def assert_cents(value: Any, field: str) -> None:
    """PRD §2.6: all money is an integer number of cents — never a fractional value."""
    assert isinstance(value, int) and not isinstance(value, bool), (
        f"{field} must be an integer number of cents, got {value!r}")


# ─── Per-entity assertions ───────────────────────────────────────────────────

def assert_production(data: Dict[str, Any]) -> None:
    assert_versioned_fields(data, "Production")
    assert isinstance(data["title"], str) and data["title"], "Production.title must be non-empty"
    assert isinstance(data["delivery_deadline_date"], str)
    assert data["status"] in _values(ProductionStatus), f"bad status {data['status']!r}"
    assert data["posture"] in _values(ProductionPosture), f"bad posture {data['posture']!r}"
    for counter in ("asset_count", "cleared_asset_count", "open_asset_count", "sweep_epoch"):
        assert isinstance(data[counter], int) and data[counter] >= 0, (
            f"Production.{counter} must be a non-negative integer, got {data[counter]!r}")
    assert_cents(data["committed_fee_cents"], "Production.committed_fee_cents")
    assert_asset_counter_ledger(data)


def assert_archive(data: Dict[str, Any]) -> None:
    assert_versioned_fields(data, "Archive")
    assert isinstance(data["name"], str) and data["name"]
    assert data["holder_type"] in _values(ArchiveHolderType)
    assert data["mfn_policy"] in _values(ArchiveMfnPolicy)
    assert data["status"] in _values(ArchiveStatus)


def assert_rate_card(data: Dict[str, Any]) -> None:
    assert_versioned_fields(data, "RateCard")
    for money in ("base_rate_per_30s_cents", "minimum_fee_cents", "festival_minimum_fee_cents"):
        assert_cents(data[money], f"RateCard.{money}")
    assert isinstance(data["effective_from_date"], str)
    assert data["status"] in _values(RateCardStatus)


def assert_asset(data: Dict[str, Any]) -> None:
    assert_versioned_fields(data, "Asset")
    assert data["asset_type"] in _values(AssetType)
    assert data["usage_purpose"] in _values(AssetUsagePurpose)
    assert data["rights_basis"] in _values(AssetRightsBasis)
    assert data["licensing_status"] in _values(AssetLicensingStatus)
    assert data["depiction_status"] in _values(AssetDepictionStatus)
    assert isinstance(data["timecode_in_seconds"], int) and data["timecode_in_seconds"] >= 0
    assert isinstance(data["timecode_out_seconds"], int)
    assert data["timecode_out_seconds"] > data["timecode_in_seconds"], (
        "PRD §3.1: the out-point is strictly greater than the in-point")
    assert data["duration_seconds"] == data["timecode_out_seconds"] - data["timecode_in_seconds"], (
        "PRD §3.1: duration_seconds is the out-point minus the in-point")
    assert isinstance(data["lapse_count"], int) and data["lapse_count"] >= 0


def assert_source_candidate(data: Dict[str, Any]) -> None:
    assert_versioned_fields(data, "SourceCandidate")
    assert data["availability_status"] in _values(SourceCandidateAvailability)
    assert data["selection_status"] in _values(SourceCandidateSelectionStatus)
    confidence = data.get("provenance_confidence")
    if confidence is not None:
        assert isinstance(confidence, int) and 0 <= confidence <= 100, (
            "PRD §3.2: provenance_confidence is an integer from 0 to 100 inclusive")


def assert_license(data: Dict[str, Any]) -> None:
    assert_versioned_fields(data, "License")
    assert data["rights_leg"] in _values(LicenseRightsLeg)
    assert data["media"] in _values(LicenseMedia)
    assert data["territory"] in _values(LicenseTerritory)
    assert data["window_class"] in _values(LicenseWindowClass)
    assert data["status"] in _values(LicenseStatus)
    assert isinstance(data["term_months"], int) and data["term_months"] >= 1, (
        "PRD §3.3: term_months is a whole month count of at least 1")
    assert isinstance(data["billable_units"], int) and data["billable_units"] >= 1
    assert_cents(data["rate_card_fee_cents"], "License.rate_card_fee_cents")
    assert_cents(data["current_proposed_fee_cents"], "License.current_proposed_fee_cents")
    assert isinstance(data["round_count"], int) and data["round_count"] >= 0
    if data.get("executed_fee_cents") is not None:
        assert_cents(data["executed_fee_cents"], "License.executed_fee_cents")


def assert_negotiation_round(data: Dict[str, Any]) -> None:
    """PRD §2.4: a round carries only `id` and `created_at` — no `updated_at`, no `version`."""
    assert_identity_fields(data, "NegotiationRound")
    assert "updated_at" not in data, (
        "PRD §2.4: a negotiation round has no updated_at field")
    assert "version" not in data, (
        "PRD §2.4: a negotiation round has no version field")
    assert data["party"] in _values(NegotiationParty)
    assert isinstance(data["round_number"], int) and data["round_number"] >= 1
    assert_cents(data["proposed_fee_cents"], "NegotiationRound.proposed_fee_cents")
    assert data["license_status_after"] in _values(LicenseStatus)
    assert isinstance(data["license_version_after"], int)


def assert_fair_use_analysis(data: Dict[str, Any]) -> None:
    assert_versioned_fields(data, "FairUseAnalysis")
    assert data["weighting_variant"] in _values(FairUseWeightingVariant)
    assert data["status"] in _values(FairUseAnalysisStatus)
    for factor in ("transformative_score", "nature_score", "amount_used_score",
                   "market_harm_score"):
        assert isinstance(data[factor], int) and 0 <= data[factor] <= 100, (
            f"PRD §3.5: {factor} is an integer from 0 to 100 inclusive")
    assert_strength_score_precision(data["strength_score"])


def assert_opinion_letter(data: Dict[str, Any]) -> None:
    assert_versioned_fields(data, "OpinionLetter")
    assert data["risk_rating"] in _values(OpinionLetterRiskRating)
    assert data["status"] in _values(OpinionLetterStatus)
    assert isinstance(data["counsel_firm"], str) and data["counsel_firm"]
    assert isinstance(data["letter_reference"], str) and data["letter_reference"]
    assert isinstance(data["issued_by_user_id"], str) and data["issued_by_user_id"], (
        "PRD §3.5: the acting operator's X-User-ID is captured as issued_by_user_id")


def assert_subject_release(data: Dict[str, Any]) -> None:
    assert_versioned_fields(data, "SubjectRelease")
    assert data["release_type"] in _values(SubjectReleaseType)
    assert data["approval_rights"] in _values(SubjectReleaseApprovalRights)
    assert data["status"] in _values(SubjectReleaseStatus)
    assert isinstance(data["subject_person_key"], str) and data["subject_person_key"]
    assert data["depiction_from_date"] <= data["depiction_to_date"], (
        "PRD §3.6: the to-date must not precede the from-date")
    assert isinstance(data["revision_round_count"], int) and data["revision_round_count"] >= 0


def assert_clearance_chart(data: Dict[str, Any]) -> None:
    assert_versioned_fields(data, "ClearanceChart")
    assert data["status"] in _values(ClearanceChartStatus)
    assert isinstance(data["pinned_rows"], list)
    assert data["pinned_row_count"] == len(data["pinned_rows"]), (
        "PRD §3.7: pinned_row_count is the length of the pinned_rows array")
    assert isinstance(data["pinned_opinion_letter_ids"], list)
    assert isinstance(data["music_leg_gap_count"], int) and data["music_leg_gap_count"] >= 0


def assert_eo_application(data: Dict[str, Any]) -> None:
    assert_versioned_fields(data, "EOApplication")
    assert data["status"] in _values(EOApplicationStatus)
    assert data["legal_review_status"] in _values(EOReviewStatus)
    assert data["underwriting_review_status"] in _values(EOReviewStatus)
    assert_cents(data["coverage_limit_cents"], "EOApplication.coverage_limit_cents")
    assert_cents(data["retention_cents"], "EOApplication.retention_cents")
    if data.get("premium_cents") is not None:
        assert_cents(data["premium_cents"], "EOApplication.premium_cents")


def assert_delivery_package(data: Dict[str, Any]) -> None:
    assert_versioned_fields(data, "DeliveryPackage")
    assert data["status"] in _values(DeliveryPackageStatus)
    assert data["window_class"] in _values(LicenseWindowClass)
    for counter in ("cue_sheet_row_count", "rights_chart_row_count", "music_leg_gap_count"):
        assert isinstance(data[counter], int) and data[counter] >= 0


# ─── Domain invariants ───────────────────────────────────────────────────────

def assert_asset_counter_ledger(production: Dict[str, Any]) -> None:
    """PRD §2.9: cleared_asset_count plus open_asset_count always equals asset_count."""
    cleared = production["cleared_asset_count"]
    open_count = production["open_asset_count"]
    total = production["asset_count"]
    assert cleared + open_count == total, (
        f"Asset counter ledger broken: cleared {cleared} + open {open_count} != "
        f"asset_count {total}")


def assert_license_money_ledger(api, production_id: str, headers: Dict[str, str]) -> None:
    """PRD §2.9: committed_fee_cents equals the sum of executed_fee_cents over every
    licence of the production whose status is EXECUTED, ACTIVE or EXPIRING."""
    from prd_bench_local_runner.testing import validate_paginated, validate_success

    production = validate_success(api.get_production(production_id, headers))
    rows, _meta = validate_paginated(
        api.list_licenses(headers, params={"production_id": production_id, "limit": 100}))
    expected = sum(
        row["executed_fee_cents"] or 0
        for row in rows
        if row["status"] in LIVE_LICENSE_STATUSES
    )
    assert production["committed_fee_cents"] == expected, (
        f"Licence money ledger broken: committed_fee_cents "
        f"{production['committed_fee_cents']} != summed executed_fee_cents {expected}")


def assert_posture(production: Dict[str, Any], expected: str) -> None:
    assert production["posture"] == expected, (
        f"Expected posture {expected}, got {production['posture']} "
        f"(asset_count={production['asset_count']}, "
        f"cleared={production['cleared_asset_count']}, "
        f"open={production['open_asset_count']})")


def assert_strength_score_precision(score: Any) -> None:
    """PRD §2.6: strength_score lies in the closed interval 0 to 1, at four decimals."""
    assert isinstance(score, (int, float)) and not isinstance(score, bool), (
        f"strength_score must be numeric, got {score!r}")
    assert 0 <= score <= 1, f"strength_score must lie between 0 and 1, got {score}"
    assert round(float(score), 4) == float(score), (
        f"strength_score must carry at most four decimal places, got {score}")


def assert_asset_dimensions(asset: Dict[str, Any], licensing_status: str,
                            depiction_status: Optional[str] = None,
                            rights_basis: Optional[str] = None,
                            lapse_count: Optional[int] = None) -> None:
    """Assert the asset's two independent status dimensions of PRD §3.1."""
    assert asset["licensing_status"] == licensing_status, (
        f"Expected licensing_status {licensing_status}, got {asset['licensing_status']}")
    if depiction_status is not None:
        assert asset["depiction_status"] == depiction_status, (
            f"Expected depiction_status {depiction_status}, got {asset['depiction_status']}")
    if rights_basis is not None:
        assert asset["rights_basis"] == rights_basis, (
            f"Expected rights_basis {rights_basis}, got {asset['rights_basis']}")
    if lapse_count is not None:
        assert asset["lapse_count"] == lapse_count, (
            f"Expected lapse_count {lapse_count}, got {asset['lapse_count']}")


def assert_production_counters(production: Dict[str, Any], asset_count: int,
                               cleared_asset_count: int, open_asset_count: int) -> None:
    assert production["asset_count"] == asset_count, (
        f"Expected asset_count {asset_count}, got {production['asset_count']}")
    assert production["cleared_asset_count"] == cleared_asset_count, (
        f"Expected cleared_asset_count {cleared_asset_count}, "
        f"got {production['cleared_asset_count']}")
    assert production["open_asset_count"] == open_asset_count, (
        f"Expected open_asset_count {open_asset_count}, got {production['open_asset_count']}")
    assert_asset_counter_ledger(production)


def assert_success_envelope_meta(response) -> None:
    """PRD §2.2: every 2xx envelope carries a server-generated api_request_id starting
    with `req_` and an ISO 8601 api_request_timestamp."""
    body = response.json()
    meta = body["meta"]
    assert isinstance(meta.get("api_request_id"), str) and \
        meta["api_request_id"].startswith("req_"), (
            f"api_request_id must start with req_, got {meta.get('api_request_id')!r}")
    assert is_iso8601_timestamp(meta.get("api_request_timestamp", "")), (
        f"api_request_timestamp must be ISO 8601, got {meta.get('api_request_timestamp')!r}")
