"""Entity assertions and domain invariant checkers.

Every row carries a UUID ``id`` and an ISO 8601 ``created_at``; almost every row
also carries ``updated_at`` and an integer ``version`` starting at 1.  A
marriage joint is the deliberate exception and carries ``id`` and ``created_at``
only.
"""

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    AnchorCertificationStatus,
    ClosureStatus,
    DamageClaimStatus,
    EscortAssignmentStatus,
    EscortCrewStatus,
    FinalResult,
    HaulerStatus,
    OrderPosture,
    PadType,
    PermitClass,
    PermitStatus,
    PlantStatus,
    RouteLegStatus,
    SectionTransitStatus,
    SetCrewStatus,
    SetJobProgressStatus,
    SetJobScopeStatus,
    SiteReadinessStatus,
)


def _values(enum_cls):
    return [m.value for m in enum_cls]


def assert_common_row(data):
    """id, created_at, updated_at and version, per PRD §2.4."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')}"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"created_at must be ISO 8601 UTC, got {data.get('created_at')}"
    assert is_iso8601_timestamp(
        data.get("updated_at", "")
    ), f"updated_at must be ISO 8601 UTC, got {data.get('updated_at')}"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, "version starts at 1 on creation"


def assert_append_only_row(data):
    """id and created_at only — no updated_at, no version (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')}"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"created_at must be ISO 8601 UTC, got {data.get('created_at')}"
    assert "updated_at" not in data, "an append-only measurement event has no updated_at"
    assert "version" not in data, "an append-only measurement event has no version"


def assert_three_fractional_digits(timestamp):
    """PRD §2.4: exactly three fractional digits on stored timestamps."""
    assert "." in timestamp, f"timestamp {timestamp} carries no fractional part"
    fraction = timestamp.split(".")[1].rstrip("Z")
    assert len(fraction) == 3, f"expected three fractional digits, got {timestamp}"


def assert_ymd_date(value, field="date"):
    import re

    assert isinstance(value, str) and re.fullmatch(
        r"\d{4}-\d{2}-\d{2}", value
    ), f"{field} must be YYYY-MM-DD, got {value!r}"


# ---------------------------------------------------------------------------
# Trading partners
# ---------------------------------------------------------------------------


def assert_plant(data):
    assert_common_row(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2
    assert data["state_code"].isupper(), "state_code is two uppercase letters"
    assert isinstance(data["hud_plant_code"], str) and data["hud_plant_code"]
    assert isinstance(data["chargeback_balance_cents"], int)
    assert data["chargeback_balance_cents"] >= 0
    assert data["status"] in _values(PlantStatus)


def assert_hauler(data):
    assert_common_row(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["dot_number"], str) and data["dot_number"]
    assert_ymd_date(data["insurance_expiry_date"], "insurance_expiry_date")
    assert isinstance(data["endorsed_states"], list) and data["endorsed_states"]
    assert isinstance(data["chargeback_balance_cents"], int)
    assert data["status"] in _values(HaulerStatus)


def assert_escort_crew(data):
    assert_common_row(data)
    assert isinstance(data["vendor_name"], str) and data["vendor_name"]
    assert isinstance(data["endorsed_states"], list)
    assert isinstance(data["certified_roles"], list) and data["certified_roles"]
    assert set(data["certified_roles"]) <= {"ESCORT", "PILOT_CAR"}
    assert data["endorsement_class"] in ["STANDARD", "OVERSIZE", "SUPERLOAD"]
    assert isinstance(data["buffer_minutes"], int)
    assert 0 <= data["buffer_minutes"] <= 240, "buffer_minutes lies between 0 and 240"
    assert isinstance(data["max_reserved_minutes"], int)
    assert data["max_reserved_minutes"] >= 1
    assert isinstance(data["reserved_minutes"], int)
    assert data["reserved_minutes"] >= 0
    assert data["status"] in _values(EscortCrewStatus)


def assert_set_crew(data):
    assert_common_row(data)
    assert isinstance(data["company_name"], str) and data["company_name"]
    assert isinstance(data["hud_installer_license_no"], str)
    assert isinstance(data["license_state"], str) and len(data["license_state"]) == 2
    assert_ymd_date(data["license_expiry_date"], "license_expiry_date")
    assert isinstance(data["daily_capacity"], int)
    assert 1 <= data["daily_capacity"] <= 4, "daily_capacity lies between 1 and 4"
    assert isinstance(data["chargeback_balance_cents"], int)
    assert data["status"] in _values(SetCrewStatus)


# ---------------------------------------------------------------------------
# Order, floors, site
# ---------------------------------------------------------------------------


def assert_installation_order(data):
    assert_common_row(data)
    assert is_valid_uuid(data["plant_id"])
    assert isinstance(data["dealer_name"], str) and data["dealer_name"]
    assert isinstance(data["home_model"], str) and data["home_model"]
    assert isinstance(data["section_count"], int)
    assert 1 <= data["section_count"] <= 4, "section_count lies between 1 and 4"
    assert isinstance(data["destination_state"], str)
    assert data["wind_zone"] in ["I", "II", "III"]
    assert data["posture"] in _values(OrderPosture)


def assert_home_section(data):
    assert_common_row(data)
    assert is_valid_uuid(data["order_id"])
    assert isinstance(data["section_index"], int)
    assert 1 <= data["section_index"] <= 4, "section_index lies between 1 and 4"
    assert 120 <= data["declared_width_in"] <= 240
    assert 120 <= data["declared_height_in"] <= 200
    assert isinstance(data["declared_length_in"], int)
    assert isinstance(data["declared_weight_lb"], int)
    assert data["transit_status"] in _values(SectionTransitStatus)


def assert_site(data):
    assert_common_row(data)
    assert is_valid_uuid(data["order_id"])
    assert data["pad_type"] in _values(PadType)
    assert isinstance(data["pier_plan_ref"], str) and data["pier_plan_ref"]
    assert isinstance(data["pier_count"], int) and data["pier_count"] >= 0
    for flag in ("utility_water", "utility_sewer", "utility_electric"):
        assert isinstance(data[flag], bool), f"{flag} must be a boolean"
    assert data["readiness_status"] in _values(SiteReadinessStatus)
    assert isinstance(data["inspection_round"], int) and data["inspection_round"] >= 0
    assert isinstance(data["blocking_defect_count"], int)
    assert (
        0 <= data["blocking_defect_count"] <= 3
    ), "blocking_defect_count lands between 0 and 3 inclusive"


# ---------------------------------------------------------------------------
# Permits, legs, escort reservations
# ---------------------------------------------------------------------------


def assert_transport_permit(data):
    assert_common_row(data)
    assert is_valid_uuid(data["section_id"])
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2
    assert isinstance(data["planned_leg_count"], int)
    assert 1 <= data["planned_leg_count"] <= 6
    assert data["permit_class"] in _values(PermitClass)
    assert isinstance(data["escort_count_required"], int)
    assert 0 <= data["escort_count_required"] <= 4, "escorts are capped at four"
    assert isinstance(data["pilot_car_required"], bool)
    assert isinstance(data["provisional_fee_cents"], int)
    assert isinstance(data["paid_amount_cents"], int)
    assert data["status"] in _values(PermitStatus)


def assert_route_leg(data):
    assert_common_row(data)
    assert is_valid_uuid(data["permit_id"])
    assert is_valid_uuid(data["hauler_id"])
    assert isinstance(data["sequence_no"], int)
    assert 1 <= data["sequence_no"] <= 6
    assert isinstance(data["corridor_id"], str) and data["corridor_id"]
    assert isinstance(data["state_code"], str)
    assert data["window_end"] > data["window_start"], "window_end is strictly after window_start"
    assert data["status"] in _values(RouteLegStatus)


def assert_escort_assignment(data):
    assert_common_row(data)
    assert is_valid_uuid(data["route_leg_id"])
    assert is_valid_uuid(data["escort_crew_id"])
    assert data["role"] in ["ESCORT", "PILOT_CAR"]
    assert data["window_end"] > data["window_start"]
    assert isinstance(data["reserved_minutes"], int) and data["reserved_minutes"] >= 0
    assert data["status"] in _values(EscortAssignmentStatus)


# ---------------------------------------------------------------------------
# Set jobs, joints, anchoring, claims
# ---------------------------------------------------------------------------


def assert_set_job(data):
    assert_common_row(data)
    assert is_valid_uuid(data["order_id"])
    assert is_valid_uuid(data["set_crew_id"])
    assert_ymd_date(data["scheduled_start_date"], "scheduled_start_date")
    assert_ymd_date(data["scheduled_end_date"], "scheduled_end_date")
    assert (
        data["scheduled_end_date"] >= data["scheduled_start_date"]
    ), "scheduled_end_date falls on or after scheduled_start_date"
    assert isinstance(data["labor_base_cents"], int) and data["labor_base_cents"] >= 0
    assert data["progress_status"] in _values(SetJobProgressStatus)
    assert data["scope_status"] in _values(SetJobScopeStatus)
    assert data["closure_status"] in _values(ClosureStatus)
    assert data["final_result"] in _values(FinalResult)
    assert isinstance(data["crossover_recorded"], bool)


def assert_marriage_joint(data):
    assert_append_only_row(data)
    assert is_valid_uuid(data["set_job_id"])
    assert isinstance(data["joint_index"], int)
    assert 1 <= data["joint_index"] <= 3, "joint_index lies between 1 and 3"
    assert 0 <= data["gap_in"] <= 4
    assert -4 <= data["vertical_offset_in"] <= 4
    assert 0 <= data["ridge_beam_shim_in"] <= 2
    assert isinstance(data["deviation_score"], (int, float))


def assert_anchor_certification(data):
    assert_common_row(data)
    assert is_valid_uuid(data["set_job_id"])
    assert isinstance(data["anchor_count"], int) and data["anchor_count"] >= 0
    assert data["avg_torque_ft_lb"] >= 0
    assert isinstance(data["strap_count"], int) and data["strap_count"] >= 0
    assert isinstance(data["pier_count"], int) and data["pier_count"] >= 0
    assert isinstance(data["hud_pass"], bool)
    assert isinstance(data["state_pass"], bool)
    assert isinstance(data["revision_round"], int) and data["revision_round"] >= 1
    assert data["status"] in _values(AnchorCertificationStatus)


def assert_damage_claim(data):
    assert_common_row(data)
    for ref in ("order_id", "section_id", "hauler_id", "set_crew_id"):
        assert is_valid_uuid(data[ref]), f"{ref} must be a UUID"
    assert data["discovered_stage"] in [
        "PLANT_QC",
        "IN_TRANSIT",
        "AT_SET",
        "FINAL_INSPECTION",
        "UNKNOWN",
    ]
    assert isinstance(data["claimed_amount_cents"], int)
    assert 1 <= data["claimed_amount_cents"] <= 2_500_000
    assert isinstance(data["blocks_set"], bool)
    for points in (
        "plant_evidence_points",
        "hauler_evidence_points",
        "installer_evidence_points",
    ):
        assert 0 <= data[points] <= 10, f"{points} lies between 0 and 10 inclusive"
    for charge in ("plant_charge_cents", "hauler_charge_cents", "installer_charge_cents"):
        assert isinstance(data[charge], int) and data[charge] >= 0
    assert isinstance(data["dispute_round"], int) and data["dispute_round"] >= 0
    assert data["status"] in _values(DamageClaimStatus)


# ---------------------------------------------------------------------------
# Domain invariants
# ---------------------------------------------------------------------------


def assert_allocation_sums_exactly(claim):
    """PRD §3.9: the three charges sum to approved_amount_cents to the cent."""
    total = (
        claim["plant_charge_cents"]
        + claim["hauler_charge_cents"]
        + claim["installer_charge_cents"]
    )
    assert total == claim["approved_amount_cents"], (
        "plant_charge_cents + hauler_charge_cents + installer_charge_cents must equal "
        f"approved_amount_cents, got {total} vs {claim['approved_amount_cents']}"
    )


def assert_network_chargeback_conserved(summary, expected_cents):
    """PRD §2.9: the network chargeback total equals the adjudicated sum."""
    assert summary["network_chargeback_cents"] == expected_cents, (
        f"network_chargeback_cents must be {expected_cents}, "
        f"got {summary['network_chargeback_cents']}"
    )


def assert_crew_minutes_match_reservations(crew, expected_minutes):
    """PRD §2.9: reserved_minutes equals the sum of the reserved assignments."""
    assert crew["reserved_minutes"] == expected_minutes, (
        f"reserved_minutes must be {expected_minutes}, got {crew['reserved_minutes']}"
    )


def assert_order_summary(summary):
    for field in (
        "order_id",
        "posture",
        "section_count_declared",
        "section_count_actual",
        "sections_delivered_count",
        "sections_on_hold_count",
        "issued_permit_count",
        "open_claim_count",
        "network_chargeback_cents",
    ):
        assert field in summary, f"the roll-up must report {field}"
    assert summary["posture"] in _values(OrderPosture)
