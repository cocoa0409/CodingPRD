"""Entity assertions and domain invariant checkers for the Flood Zone API."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    AmendmentRequestType,
    AmendmentStatus,
    CertificateStatus,
    CompliancePosture,
    CoverageAvailability,
    Datum,
    DeterminationStatus,
    DeterminationType,
    DeterminationZoneCode,
    FeeTier,
    FoundationType,
    GeocodeMethod,
    GeocodeStatus,
    InsuranceStatus,
    MonitoringStatus,
    NoticeStatus,
    NoticeType,
    OccupancyType,
    PanelRevisionStatus,
    PanelZoneCode,
    ParticipationStatus,
    PositionClass,
    DisputeStatus,
)

_VALUES = lambda enum_cls: [e.value for e in enum_cls]  # noqa: E731


def assert_common_fields(data: dict, entity_name: str = "entity"):
    """PRD 2.4 — every persisted resource carries id, created_at, updated_at, version."""
    assert is_valid_uuid(data.get("id", "")), f"{entity_name}.id must be a UUID: {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity_name}.created_at must be ISO 8601: {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity_name}.updated_at must be ISO 8601: {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int), f"{entity_name}.version must be an integer"
    assert data["version"] >= 1, f"{entity_name}.version starts at 1, got {data['version']}"


def assert_community(data: dict):
    assert_common_fields(data, "Community")
    assert isinstance(data["community_id_code"], str) and data["community_id_code"]
    assert isinstance(data["name"], str) and data["name"]
    assert data["state_code"] in ["CA", "FL", "TX", "NC"], data["state_code"]
    assert data["participation_status"] in _VALUES(ParticipationStatus)
    assert isinstance(data["cbrs_flag"], bool)
    assert isinstance(data["probation_surcharge_cents"], int)
    assert data["probation_surcharge_cents"] >= 0
    assert data["coverage_availability"] in _VALUES(CoverageAvailability)
    assert is_iso8601_timestamp(data["last_participation_change_at"])
    assert isinstance(data["active_folio_count"], int) and data["active_folio_count"] >= 0


def assert_lender(data: dict):
    assert_common_fields(data, "Lender")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["contact_email"], str) and data["contact_email"]
    assert isinstance(data["force_placement_authorized_flag"], bool)
    assert isinstance(data["escrow_servicing_flag"], bool)
    assert isinstance(data["open_force_placement_count"], int)
    assert data["open_force_placement_count"] >= 0


def assert_map_panel(data: dict):
    assert_common_fields(data, "MapPanel")
    assert is_valid_uuid(data["community_id"])
    assert isinstance(data["map_panel_number"], str) and data["map_panel_number"]
    assert isinstance(data["revision_sequence"], int) and data["revision_sequence"] >= 1
    assert data["revision_status"] in _VALUES(PanelRevisionStatus)
    assert data["zone_code"] in _VALUES(PanelZoneCode), data["zone_code"]
    assert data["base_flood_elevation_ft"] is None or isinstance(
        data["base_flood_elevation_ft"], (int, float)
    )
    assert isinstance(data["sfha_boundary_shift_ft"], (int, float))
    assert isinstance(data["horizontal_uncertainty_ft"], (int, float))
    assert data["horizontal_uncertainty_ft"] >= 0
    assert is_iso8601_timestamp(data["effective_date"])
    assert isinstance(data["revision_round"], int) and data["revision_round"] >= 0


def assert_property(data: dict):
    assert_common_fields(data, "Property")
    assert is_valid_uuid(data["community_id"])
    for field in ("street_address", "city", "postal_code", "map_panel_number"):
        assert isinstance(data[field], str) and data[field], field
    assert isinstance(data["latitude"], (int, float))
    assert isinstance(data["longitude"], (int, float))
    assert data["geocode_method"] in _VALUES(GeocodeMethod)
    assert 0.0 <= data["geocode_confidence_score"] <= 1.0
    assert data["geocode_status"] in _VALUES(GeocodeStatus)
    assert isinstance(data["geocode_buffer_ft"], (int, float))
    assert isinstance(data["geocode_corrected_count"], int)
    assert data["geocode_corrected_count"] >= 0
    assert isinstance(data["structure_count"], int) and data["structure_count"] >= 0


def assert_structure(data: dict):
    assert_common_fields(data, "Structure")
    assert is_valid_uuid(data["property_id"])
    assert isinstance(data["structure_label"], str) and data["structure_label"]
    assert data["occupancy_type"] in _VALUES(OccupancyType)
    assert data["foundation_type"] in _VALUES(FoundationType)
    assert isinstance(data["replacement_cost_cents"], int)
    assert data["replacement_cost_cents"] > 0, "replacement_cost_cents must exceed zero"
    assert isinstance(data["sfha_offset_ft"], (int, float))
    assert isinstance(data["post_firm_flag"], bool)
    assert isinstance(data["fill_placed_flag"], bool)


def assert_loan_folio(data: dict):
    assert_common_fields(data, "LoanFolio")
    assert is_valid_uuid(data["lender_id"])
    assert is_valid_uuid(data["property_id"])
    assert isinstance(data["loan_number"], str) and data["loan_number"]
    assert isinstance(data["borrower_user_id"], str) and data["borrower_user_id"]
    assert isinstance(data["principal_balance_cents"], int)
    assert data["principal_balance_cents"] > 0
    assert isinstance(data["escrow_balance_cents"], int) and data["escrow_balance_cents"] >= 0
    assert isinstance(data["initial_escrow_balance_cents"], int)
    assert is_iso8601_timestamp(data["policy_anniversary_date"])
    assert data["monitoring_status"] in _VALUES(MonitoringStatus)
    assert data["insurance_status"] in _VALUES(InsuranceStatus)
    assert data["compliance_posture"] in _VALUES(CompliancePosture)
    for field in (
        "required_coverage_cents", "reported_coverage_cents", "uninsured_exposure_cents",
        "force_placed_premium_cents", "force_placed_coverage_days",
        "cumulative_earned_premium_cents", "open_notice_count",
        "pending_redetermination_count",
    ):
        assert isinstance(data[field], int), f"{field} must be an integer, got {data[field]!r}"
        assert data[field] >= 0, f"{field} must not be negative, got {data[field]}"


def assert_determination(data: dict):
    assert_common_fields(data, "Determination")
    assert is_valid_uuid(data["loan_folio_id"])
    assert is_valid_uuid(data["structure_id"])
    assert is_valid_uuid(data["map_panel_id"])
    assert data["determination_type"] in _VALUES(DeterminationType)
    assert data["status"] in _VALUES(DeterminationStatus)
    assert data["position_class"] in _VALUES(PositionClass)
    assert data["zone_code"] in _VALUES(DeterminationZoneCode)
    assert isinstance(data["sfha_flag"], bool)
    assert isinstance(data["mandatory_purchase_flag"], bool)
    assert isinstance(data["issued_by_user_id"], str) and data["issued_by_user_id"]
    assert is_iso8601_timestamp(data["issued_at"])
    assert data["flagged_reason"] in (None, "MAP_REVISION", "GEOCODE_CORRECTION")
    if data["sfha_flag"] is False:
        assert data["zone_code"] == "X", (
            "PRD 3.5: an OUTSIDE classification sets zone_code to X"
        )
        assert data["base_flood_elevation_ft"] is None, (
            "PRD 3.5: base_flood_elevation_ft is null when sfha_flag is false"
        )


def assert_dispute(data: dict):
    assert_common_fields(data, "Dispute")
    assert is_valid_uuid(data["determination_id"])
    assert data["status"] in _VALUES(DisputeStatus)
    assert isinstance(data["round_number"], int)
    assert 1 <= data["round_number"] <= 2, "PRD 3.9: round_number never leaves 1 through 2"
    assert isinstance(data["borrower_statement"], str) and data["borrower_statement"]
    assert isinstance(data["asserted_sfha_offset_ft"], (int, float))
    assert is_iso8601_timestamp(data["filed_at"])
    assert is_iso8601_timestamp(data["decision_due_at"])


def assert_elevation_certificate(data: dict):
    assert_common_fields(data, "ElevationCertificate")
    assert is_valid_uuid(data["structure_id"])
    assert is_valid_uuid(data["reference_panel_id"])
    assert data["datum"] in _VALUES(Datum)
    assert data["status"] in _VALUES(CertificateStatus)
    assert isinstance(data["surveyor_license_number"], str)
    assert is_iso8601_timestamp(data["survey_date"])
    assert isinstance(data["raw_lowest_floor_elevation_ft"], (int, float))
    assert isinstance(data["raw_lowest_adjacent_grade_ft"], (int, float))
    assert isinstance(data["submitted_by_user_id"], str) and data["submitted_by_user_id"]


def assert_map_amendment_request(data: dict):
    assert_common_fields(data, "MapAmendmentRequest")
    assert is_valid_uuid(data["determination_id"])
    assert is_valid_uuid(data["elevation_certificate_id"])
    assert data["request_type"] in _VALUES(AmendmentRequestType)
    assert data["status"] in _VALUES(AmendmentStatus)
    assert isinstance(data["expedite_flag"], bool)
    assert isinstance(data["resubmission_count"], int)
    assert 0 <= data["resubmission_count"] <= 2, (
        "PRD 3.8: resubmission_count never exceeds 2"
    )
    assert data["fee_tier"] in _VALUES(FeeTier)
    for field in ("base_review_fee_cents", "expedite_surcharge_cents", "total_fee_cents"):
        assert isinstance(data[field], int), f"{field} must be integer cents"
        assert data[field] >= 0
    assert data["total_fee_cents"] == (
        data["base_review_fee_cents"] + data["expedite_surcharge_cents"]
    ), "PRD 3.8: total_fee_cents is base_review_fee_cents plus expedite_surcharge_cents"


def assert_compliance_notice(data: dict):
    assert_common_fields(data, "ComplianceNotice")
    assert is_valid_uuid(data["loan_folio_id"])
    assert is_valid_uuid(data["determination_id"])
    assert data["notice_type"] in _VALUES(NoticeType)
    assert data["status"] in _VALUES(NoticeStatus)
    assert isinstance(data["annual_premium_rate_cents"], int)
    assert data["annual_premium_rate_cents"] >= 0
    assert is_iso8601_timestamp(data["sent_at"])
    assert is_iso8601_timestamp(data["response_deadline_at"])
    assert isinstance(data["required_coverage_snapshot_cents"], int)
    assert isinstance(data["estimated_force_place_premium_cents"], int)
    assert data["acknowledged_by_role"] in (None, "Lender", "Borrower")


# --------------------------------------------------------------------------
# Domain invariants
# --------------------------------------------------------------------------
def assert_escrow_conservation(folio: dict):
    """PRD 2.10: escrow_balance_cents + cumulative_earned_premium_cents ==
    initial_escrow_balance_cents at every point where the folio is at rest."""
    total = folio["escrow_balance_cents"] + folio["cumulative_earned_premium_cents"]
    assert total == folio["initial_escrow_balance_cents"], (
        "escrow conservation broken: "
        f"{folio['escrow_balance_cents']} + {folio['cumulative_earned_premium_cents']} "
        f"!= {folio['initial_escrow_balance_cents']}"
    )


def assert_uninsured_exposure(folio: dict):
    """PRD 3.6: uninsured_exposure_cents is 0 while FORCE_PLACED, otherwise
    required minus reported floored at 0."""
    if folio["insurance_status"] == "FORCE_PLACED":
        assert folio["uninsured_exposure_cents"] == 0
    else:
        expected = max(
            0, folio["required_coverage_cents"] - folio["reported_coverage_cents"]
        )
        assert folio["uninsured_exposure_cents"] == expected, (
            f"expected uninsured_exposure_cents {expected}, "
            f"got {folio['uninsured_exposure_cents']}"
        )


def assert_no_error_payload(body: dict):
    """A success envelope carries no error_id."""
    assert body.get("response_type") != "error", f"unexpected error envelope: {body}"
    data = body.get("data")
    if isinstance(data, dict):
        assert "error_id" not in data, f"unexpected error_id in success data: {data}"


def assert_version_advanced(before: dict, after: dict, by: int = 1):
    """PRD 2.4: version increases by exactly 1 on every mutation of that row."""
    assert after["version"] == before["version"] + by, (
        f"expected version {before['version'] + by}, got {after['version']}"
    )
