"""Domain assertions: entity shape checks and PRD invariant checks."""
import math

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)

from .constants import (
    ADEQUATE_RATIO_PCT,
    FRONTAGE_FLOOR_WEIGHT,
    RESERVE_CONTRIBUTION_PCT,
    TRIP_UNIT_FACTOR,
    TURNOUT_SPACING_FEET,
    USAGE_MULTIPLIER,
)


# --------------------------------------------------------------------------
# Shared system fields (PRD §2.4)
# --------------------------------------------------------------------------

def assert_system_fields(data: dict) -> None:
    """Every persisted record carries `id`, `created_at`, `updated_at`, `version`."""
    assert is_valid_uuid(data["id"]), f"id is not a UUID: {data['id']!r}"
    assert is_iso8601_timestamp(data["created_at"]), data["created_at"]
    assert is_iso8601_timestamp(data["updated_at"]), data["updated_at"]
    assert isinstance(data["version"], int), data["version"]
    assert data["version"] >= 1, data["version"]


def assert_fields_present(data: dict, field_names) -> None:
    missing = [name for name in field_names if name not in data]
    assert not missing, f"missing response fields: {missing}"


# --------------------------------------------------------------------------
# Per-entity shape assertions
# --------------------------------------------------------------------------

def assert_association(data: dict) -> None:
    assert_system_fields(data)
    assert_fields_present(
        data,
        [
            "name",
            "reserve_target_cents",
            "default_voting_basis",
            "delinquency_interest_basis",
            "quorum_bps",
            "reserve_balance_cents",
            "reserve_funding_ratio",
            "reserve_posture",
        ],
    )
    assert data["default_voting_basis"] in ("PER_PARCEL", "ASSESSED_SHARE")
    assert data["delinquency_interest_basis"] in ("STATUTORY", "ASSOCIATION_POLICY")
    assert data["reserve_posture"] in ("UNDERFUNDED", "ADEQUATE", "FULLY_FUNDED")
    assert data["reserve_balance_cents"] >= 0


def assert_road_segment(data: dict) -> None:
    assert_system_fields(data)
    assert_fields_present(
        data,
        [
            "association_id",
            "name",
            "length_feet",
            "width_feet",
            "max_grade_pct",
            "surface_type",
            "turnout_count",
            "culvert_count",
            "turnaround_present",
            "bridge_present",
            "required_turnouts",
            "emergency_access_grade",
        ],
    )
    assert data["surface_type"] in ("GRAVEL", "CHIP_SEAL", "PAVED")
    assert data["emergency_access_grade"] in ("UNKNOWN", "COMPLIANT", "DEFICIENT")
    assert data["required_turnouts"] >= 0


def assert_parcel(data: dict) -> None:
    assert_system_fields(data)
    assert_fields_present(
        data,
        [
            "road_segment_id",
            "deed_book_page",
            "frontage_feet",
            "usage_class",
            "trips_per_day",
            "covenant_recorded",
            "status",
            "frontage_share_units",
            "trip_share_units",
        ],
    )
    assert data["usage_class"] in USAGE_MULTIPLIER
    assert data["status"] in ("ACTIVE", "SUBDIVIDED", "PENDING_CONNECTION", "WITHDRAWN")


def assert_member(data: dict) -> None:
    assert_system_fields(data)
    assert_fields_present(
        data,
        [
            "parcel_id",
            "owner_name",
            "deed_book_page",
            "deed_recorded_date",
            "standing_status",
            "access_status",
            "encumbered_principal_cents",
            "restricted_days_used",
        ],
    )
    assert data["standing_status"] in (
        "PENDING_DEED_VERIFICATION",
        "GOOD_STANDING",
        "DELINQUENT",
        "LIEN_FILED",
    )
    assert data["access_status"] in ("UNRESTRICTED", "WARNED", "RESTRICTED")


def assert_assessment_roll(data: dict) -> None:
    assert_system_fields(data)
    assert_fields_present(
        data,
        [
            "association_id",
            "fiscal_year",
            "fy_start_date",
            "fy_end_date",
            "budget_requirement_cents",
            "method_variant",
            "status",
            "total_share_units",
            "total_levied_cents",
            "unallocated_residual_cents",
            "reserve_contribution_cents",
            "recall_count",
        ],
    )
    assert data["method_variant"] in ("FRONTAGE_WEIGHTED", "TRIP_GENERATION_WEIGHTED")
    assert data["status"] in ("DRAFT", "CERTIFIED", "LEVIED")


def assert_assessment_charge(data: dict) -> None:
    assert_system_fields(data)
    assert_fields_present(
        data,
        [
            "roll_id",
            "parcel_id",
            "member_id",
            "charge_type",
            "status",
            "share_units_snapshot",
            "amount_cents",
            "paid_cents",
            "balance_cents",
        ],
    )
    assert data["charge_type"] in ("ANNUAL", "SPECIAL", "CONNECTION_FEE")
    assert data["status"] in (
        "PENDING",
        "OPEN",
        "DELINQUENT",
        "LIEN_ENCUMBERED",
        "PAID",
        "VOIDED",
    )
    assert data["balance_cents"] == data["amount_cents"] - data["paid_cents"], (
        "balance_cents must equal amount_cents minus paid_cents: "
        f"{data['balance_cents']} != {data['amount_cents']} - {data['paid_cents']}"
    )


def assert_proposal(data: dict) -> None:
    assert_system_fields(data)
    assert_fields_present(
        data,
        [
            "road_segment_id",
            "project_type",
            "title",
            "estimated_cost_cents",
            "cost_allocation_method",
            "voting_basis",
            "status",
            "required_threshold_bps",
            "eligible_weight_total",
            "counted_weight_total",
            "yes_weight_total",
            "no_weight_total",
            "abstain_weight_total",
            "quorum_met",
            "failed_tally_count",
            "approved_amount_cents",
        ],
    )
    assert data["status"] in ("DRAFT", "BALLOTING", "ADOPTED", "REJECTED")
    assert data["project_type"] in ("GRADING", "CULVERT", "PAVING", "BRIDGE")
    assert data["required_threshold_bps"] <= 8000


def assert_ballot(data: dict) -> None:
    assert_system_fields(data)
    assert_fields_present(
        data,
        ["proposal_id", "member_id", "choice", "status", "weight_snapshot", "cast_at"],
    )
    assert data["choice"] in ("YES", "NO", "ABSTAIN")
    assert data["status"] in ("CAST", "SUPERSEDED", "REVOKED", "VOIDED")


def assert_maintenance_project(data: dict) -> None:
    assert_system_fields(data)
    assert_fields_present(
        data,
        [
            "road_segment_id",
            "category",
            "window_start_date",
            "window_end_date",
            "status",
            "created_by_user_id",
            "awarded_amount_cents",
            "reserve_draw_cents",
        ],
    )
    assert data["status"] in ("BID_SOLICITATION", "AWARDED", "COMPLETE", "CANCELLED")
    assert data["category"] in ("GRADING", "SNOW", "DUST", "CULVERT", "PAVING", "BRIDGE")


def assert_contractor_bid(data: dict) -> None:
    assert_system_fields(data)
    assert_fields_present(
        data,
        [
            "project_id",
            "contractor_name",
            "contractor_user_id",
            "amount_cents",
            "bond_on_file",
            "status",
            "submitted_at",
        ],
    )
    assert data["status"] in ("SUBMITTED", "AWARDED", "REJECTED", "SUPERSEDED", "WITHDRAWN")


def assert_delinquency_action(data: dict) -> None:
    assert_system_fields(data)
    assert_fields_present(
        data,
        [
            "charge_id",
            "member_id",
            "action_type",
            "status",
            "restriction_days",
            "lien_amount_cents",
            "payoff_amount_cents",
            "initiated_by_user_id",
        ],
    )
    assert data["action_type"] in ("NOTICE", "LIEN_FILING", "ACCESS_RESTRICTION")
    assert data["status"] in ("INITIATED", "EFFECTIVE", "RELEASED", "VOIDED")


def assert_connection_request(data: dict) -> None:
    assert_system_fields(data)
    assert_fields_present(
        data,
        [
            "parcel_id",
            "requested_usage_class",
            "requested_trips_per_day",
            "easement_grant_recorded",
            "status",
            "connection_fee_cents",
            "reserve_buyin_cents",
        ],
    )
    assert data["status"] in ("SUBMITTED", "DISPUTED", "APPROVED", "DENIED")


# --------------------------------------------------------------------------
# Rounding helper (PRD §2.5: half-up away from zero, then integer cents)
# --------------------------------------------------------------------------

def round_half_up(value: float) -> int:
    """Round a positive money amount half-up to whole cents."""
    return int(math.floor(value + 0.5))


# --------------------------------------------------------------------------
# Derived-field invariants
# --------------------------------------------------------------------------

def expected_frontage_share_units(frontage_feet: float, usage_class: str) -> float:
    """PRD §3.2: frontage share units are frontage feet times the usage multiplier."""
    return frontage_feet * USAGE_MULTIPLIER[usage_class]


def expected_trip_share_units(frontage_feet: float, trips_per_day: int) -> float:
    """PRD §3.2: trip share units blend a frontage floor with trip generation."""
    return FRONTAGE_FLOOR_WEIGHT * frontage_feet + TRIP_UNIT_FACTOR * trips_per_day


def assert_share_units(parcel: dict) -> None:
    """Both share-unit fields agree with the parcel's own inputs (PRD §3.2)."""
    assert parcel["frontage_share_units"] == expected_frontage_share_units(
        parcel["frontage_feet"], parcel["usage_class"]
    ), parcel
    assert parcel["trip_share_units"] == expected_trip_share_units(
        parcel["frontage_feet"], parcel["trips_per_day"]
    ), parcel


def expected_required_turnouts(length_feet: float) -> int:
    """PRD §2.7: `required_turnouts = max(0, ceil(length_feet / 800) - 1)`."""
    return max(0, math.ceil(length_feet / TURNOUT_SPACING_FEET) - 1)


def assert_required_turnouts(segment: dict) -> None:
    assert segment["required_turnouts"] == expected_required_turnouts(
        segment["length_feet"]
    ), segment


def expected_reserve_posture(reserve_balance_cents: int, reserve_target_cents: int) -> str:
    """PRD §2.6: FULLY_FUNDED at or above target, ADEQUATE when the balance is at
    least sixty percent of target (inclusive), otherwise UNDERFUNDED."""
    if reserve_balance_cents >= reserve_target_cents:
        return "FULLY_FUNDED"
    if reserve_balance_cents * 100 >= reserve_target_cents * ADEQUATE_RATIO_PCT:
        return "ADEQUATE"
    return "UNDERFUNDED"


def assert_reserve_posture(association: dict) -> None:
    expected = expected_reserve_posture(
        association["reserve_balance_cents"], association["reserve_target_cents"]
    )
    assert association["reserve_posture"] == expected, (
        f"reserve_posture {association['reserve_posture']} != {expected} for balance "
        f"{association['reserve_balance_cents']} / target {association['reserve_target_cents']}"
    )


def expected_reserve_contribution(budget_requirement_cents: int) -> int:
    """PRD §3.4: the reserve contribution is fifteen percent of the budget."""
    return round_half_up(budget_requirement_cents * RESERVE_CONTRIBUTION_PCT)


def assert_levy_allocation_conserved(roll: dict, charges: list) -> None:
    """PRD §3.4: the charges plus the unallocated residual reconstruct the budget."""
    charged = sum(c["amount_cents"] for c in charges)
    assert roll["total_levied_cents"] == charged, (
        f"total_levied_cents {roll['total_levied_cents']} != sum of charges {charged}"
    )
    assert (
        roll["total_levied_cents"] + roll["unallocated_residual_cents"]
        == roll["budget_requirement_cents"]
    ), roll


def assert_one_charge_per_parcel(charges: list, parcel_ids) -> None:
    """Certification writes exactly one charge per assessable parcel."""
    charged_parcels = [c["parcel_id"] for c in charges]
    assert sorted(charged_parcels) == sorted(parcel_ids), (
        f"charged parcels {sorted(charged_parcels)} != expected {sorted(parcel_ids)}"
    )
    assert len(set(charged_parcels)) == len(charged_parcels), "duplicate charge per parcel"


def assert_weight_totals_reconcile(proposal: dict) -> None:
    """PRD §3.5: the counted weight is the sum of the three choice buckets."""
    assert proposal["counted_weight_total"] == (
        proposal["yes_weight_total"]
        + proposal["no_weight_total"]
        + proposal["abstain_weight_total"]
    ), proposal
    assert proposal["counted_weight_total"] <= proposal["eligible_weight_total"], proposal


def assert_version_is(data: dict, expected: int) -> None:
    assert data["version"] == expected, f"version {data['version']} != {expected}"


def assert_unchanged(before: dict, after: dict, *field_names) -> None:
    """Assert the named fields (and `version`) did not move."""
    for name in field_names:
        assert before[name] == after[name], (
            f"{name} changed from {before[name]!r} to {after[name]!r}"
        )
    assert before["version"] == after["version"], (
        f"version changed from {before['version']} to {after['version']}"
    )
