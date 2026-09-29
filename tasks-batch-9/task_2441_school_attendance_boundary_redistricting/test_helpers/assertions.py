"""Record-shape assertions and domain invariant checkers."""

from prd_bench_local_runner.testing import (
    assert_cost_precision,
    is_iso8601_timestamp,
    is_valid_uuid,
)

from .types import (
    CommentPriority,
    CommentStatus,
    CommentTheme,
    EntitlementStatus,
    GradeBand,
    ImpactVariant,
    ImplementationStatus,
    PhaseInRuleType,
    ProjectionRunStatus,
    ProjectionVariant,
    PromotionSource,
    ResolvedReason,
    ScenarioStatus,
    SchoolLevel,
    SchoolStatus,
    StudyStatus,
    TransferReason,
    TransferStatus,
    TransferWindowStatus,
    UnitType,
    VarianceFlag,
)


def _values(enum_cls):
    return [member.value for member in enum_cls]


def assert_common_record_fields(data: dict):
    """Every record carries an id and a creation timestamp."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"created_at must be ISO 8601, got {data.get('created_at')!r}"


def assert_versioned_record_fields(data: dict):
    """A mutable record additionally carries updated_at and an integer version."""
    assert_common_record_fields(data)
    assert is_iso8601_timestamp(
        data.get("updated_at", "")
    ), f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, f"version must start at 1 or above, got {data['version']}"


def assert_immutable_record_fields(data: dict):
    """An immutable record carries id and created_at and no revision bookkeeping."""
    assert_common_record_fields(data)
    assert "updated_at" not in data, "immutable records do not carry updated_at"
    assert "version" not in data, "immutable records do not carry version"


# ---------------------------------------------------------------------------
# Per-record assertions
# ---------------------------------------------------------------------------
def assert_boundary_study(data: dict):
    assert_versioned_record_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["district_name"], str) and data["district_name"]
    assert isinstance(data["target_school_year"], int)
    assert isinstance(data["horizon_years"], int)
    assert isinstance(data["capacity_target_low_pct"], (int, float))
    assert isinstance(data["capacity_target_high_pct"], (int, float))
    assert isinstance(data["portables_count_toward_capacity"], bool)
    assert isinstance(data["required_program_types"], list)
    assert data["status"] in _values(StudyStatus), f"unexpected study status {data['status']!r}"
    assert isinstance(data["comment_intake_open"], bool)
    assert isinstance(data["resident_student_total"], int)
    assert isinstance(data["enrolled_of_record_total"], int)
    assert isinstance(data["projection_stale"], bool)


def assert_school(data: dict):
    assert_versioned_record_fields(data)
    assert isinstance(data["study_id"], str) and data["study_id"]
    assert isinstance(data["name"], str) and data["name"]
    assert data["level"] in _values(SchoolLevel), f"unexpected level {data['level']!r}"
    assert isinstance(data["core_capacity_seats"], int)
    assert isinstance(data["portable_capacity_seats"], int)
    assert isinstance(data["program_types"], list)
    assert data["status"] in _values(SchoolStatus), f"unexpected school status {data['status']!r}"
    assert isinstance(data["effective_capacity_seats"], int)
    assert isinstance(data["enrolled_students_of_record"], int)


def assert_planning_area(data: dict):
    assert_versioned_record_fields(data)
    assert isinstance(data["study_id"], str) and data["study_id"]
    assert isinstance(data["area_code"], str) and data["area_code"]
    assert data["grade_band"] in _values(GradeBand)
    assert isinstance(data["current_school_id"], str) and data["current_school_id"]
    assert isinstance(data["resident_student_count"], int)
    assert isinstance(data["frl_student_count"], int)
    assert isinstance(data["ell_student_count"], int)
    assert isinstance(data["median_household_income_usd"], int)
    assert isinstance(data["annual_absorption_cap_units"], int)
    assert isinstance(data["travel_options"], list)
    for option in data["travel_options"]:
        assert isinstance(option["school_id"], str) and option["school_id"]
        assert isinstance(option["walk_distance_miles"], (int, float))
        assert isinstance(option["bus_minutes"], int)
        assert isinstance(option["has_safe_route"], bool)


def assert_area_adjacency(data: dict):
    assert_immutable_record_fields(data)
    assert isinstance(data["area_id"], str) and data["area_id"]
    assert isinstance(data["neighbor_area_id"], str) and data["neighbor_area_id"]
    assert data["area_id"] != data["neighbor_area_id"], "an area is never its own neighbour"
    assert isinstance(data["shared_boundary_length_ft"], int)
    assert isinstance(data["is_reciprocal"], bool)


def assert_housing_development(data: dict):
    assert_versioned_record_fields(data)
    assert isinstance(data["area_id"], str) and data["area_id"]
    assert isinstance(data["name"], str) and data["name"]
    assert data["unit_type"] in _values(UnitType)
    assert isinstance(data["total_units"], int)
    assert is_iso8601_timestamp(data["first_occupancy_date"])
    assert isinstance(data["buildout_months"], int)
    assert data["entitlement_status"] in _values(EntitlementStatus)


def assert_projection_run(data: dict):
    assert_versioned_record_fields(data)
    assert isinstance(data["study_id"], str) and data["study_id"]
    assert data["variant"] in _values(ProjectionVariant)
    assert isinstance(data["horizon_years"], int)
    assert data["status"] in _values(ProjectionRunStatus)
    assert isinstance(data["area_projections"], list)
    assert isinstance(data["projected_total_students"], int)
    for row in data["area_projections"]:
        assert isinstance(row["area_id"], str) and row["area_id"]
        assert isinstance(row["base_students"], int)
        assert isinstance(row["development_students"], (int, float))
        assert isinstance(row["projected_students"], int)


def assert_boundary_scenario(data: dict):
    assert_versioned_record_fields(data)
    assert isinstance(data["study_id"], str) and data["study_id"]
    assert isinstance(data["projection_run_id"], str) and data["projection_run_id"]
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["author_user_id"], str) and data["author_user_id"]
    assert data["status"] in _values(ScenarioStatus)
    assert isinstance(data["revision_round"], int)
    assert isinstance(data["projection_stale"], bool)
    assert isinstance(data["program_placements"], list)
    assert data["impact_variant"] in _values(ImpactVariant)
    assert isinstance(data["contiguity_ok"], bool)
    assert isinstance(data["noncontiguous_school_ids"], list)
    assert isinstance(data["total_assigned_students"], int)
    assert isinstance(data["max_utilization_pct"], (int, float))
    assert isinstance(data["walk_eligible_pct"], (int, float))
    assert isinstance(data["transport_cost_annual_usd"], (int, float))
    assert isinstance(data["students_reassigned_count"], int)
    assert isinstance(data["students_reassigned_pct"], (int, float))
    assert isinstance(data["frl_dissimilarity_index"], (int, float))


def assert_area_assignment(data: dict):
    assert_versioned_record_fields(data)
    assert isinstance(data["scenario_id"], str) and data["scenario_id"]
    assert isinstance(data["area_id"], str) and data["area_id"]
    assert isinstance(data["assigned_school_id"], str) and data["assigned_school_id"]
    assert isinstance(data["is_superseded"], bool)
    assert isinstance(data["projected_students"], int)
    if data["is_superseded"]:
        assert is_iso8601_timestamp(
            data.get("superseded_at") or ""
        ), "a superseded assignment carries the instant it was superseded"


def assert_public_comment(data: dict):
    assert_versioned_record_fields(data)
    assert isinstance(data["scenario_id"], str) and data["scenario_id"]
    assert isinstance(data["guardian_user_id"], str) and data["guardian_user_id"]
    assert isinstance(data["body"], str) and data["body"]
    assert data["status"] in _values(CommentStatus)
    if data.get("theme") is not None:
        assert data["theme"] in _values(CommentTheme)
    if data.get("priority") is not None:
        assert data["priority"] in _values(CommentPriority)


def assert_adoption_record(data: dict):
    assert_versioned_record_fields(data)
    assert isinstance(data["study_id"], str) and data["study_id"]
    assert isinstance(data["scenario_id"], str) and data["scenario_id"]
    assert is_iso8601_timestamp(data["effective_date"])
    assert isinstance(data["effective_school_year"], int)
    assert isinstance(data["regime_years"], int)
    assert is_iso8601_timestamp(data["transfer_deadline_date"])
    assert isinstance(data["transfer_cap_pct"], (int, float))
    assert isinstance(data["variance_tolerance_pct"], (int, float))
    assert isinstance(data["votes_for"], int)
    assert isinstance(data["votes_against"], int)
    assert isinstance(data["votes_abstain"], int)
    assert isinstance(data["board_member_count"], int)
    assert isinstance(data["adopted_by_user_id"], str) and data["adopted_by_user_id"]
    assert isinstance(data["supermajority_required"], bool)
    assert data["implementation_status"] in _values(ImplementationStatus)
    assert data["transfer_window_status"] in _values(TransferWindowStatus)


def assert_phase_in_rule(data: dict):
    assert_immutable_record_fields(data)
    assert isinstance(data["adoption_id"], str) and data["adoption_id"]
    assert data["rule_type"] in _values(PhaseInRuleType)
    assert isinstance(data["grade_low"], int)
    assert isinstance(data["grade_high"], int)
    assert data["grade_low"] <= data["grade_high"], "grade_low never exceeds grade_high"
    assert isinstance(data["sunset_school_year"], int)
    assert isinstance(data["consumes_seat_pool"], bool)


def assert_transfer_request(data: dict):
    assert_versioned_record_fields(data)
    assert isinstance(data["adoption_id"], str) and data["adoption_id"]
    assert isinstance(data["area_id"], str) and data["area_id"]
    assert isinstance(data["origin_school_id"], str) and data["origin_school_id"]
    assert isinstance(data["requested_school_id"], str) and data["requested_school_id"]
    assert isinstance(data["guardian_user_id"], str) and data["guardian_user_id"]
    assert isinstance(data["student_reference"], str) and data["student_reference"]
    assert isinstance(data["student_grade"], int)
    assert data["reason"] in _values(TransferReason)
    assert data["status"] in _values(TransferStatus)
    assert data["resolved_reason"] in _values(ResolvedReason)
    assert isinstance(data["consumes_seat_pool"], bool)
    if data.get("promotion_source") is not None:
        assert data["promotion_source"] in _values(PromotionSource)


def assert_variance_observation(data: dict):
    assert_immutable_record_fields(data)
    assert isinstance(data["adoption_id"], str) and data["adoption_id"]
    assert isinstance(data["school_id"], str) and data["school_id"]
    assert is_iso8601_timestamp(data["observed_on"])
    assert isinstance(data["observed_enrollment"], int)
    assert isinstance(data["projected_enrollment"], int)
    assert isinstance(data["variance_pct"], (int, float))
    assert data["flag"] in _values(VarianceFlag)


# ---------------------------------------------------------------------------
# Domain invariants
# ---------------------------------------------------------------------------
def assert_effective_capacity(school: dict, portables_count_toward_capacity: bool):
    """Effective capacity is core seats, plus portable seats only when the study counts them."""
    expected = school["core_capacity_seats"] + (
        school["portable_capacity_seats"] if portables_count_toward_capacity else 0
    )
    assert school["effective_capacity_seats"] == expected, (
        f"Expected effective_capacity_seats {expected}, got "
        f"{school['effective_capacity_seats']} for school {school['name']!r}"
    )


def assert_two_decimal_places(value, label="value"):
    """A currency or percentage figure carries at most two decimal places."""
    assert round(float(value), 2) == float(value), (
        f"{label} must carry at most 2 decimals, got {value}"
    )


def assert_currency_precision(value, label="value"):
    """A monetary figure is rounded to the cent."""
    assert_cost_precision(float(value))
    assert_two_decimal_places(value, label)


def assert_scenario_score_invariants(scenario_or_analysis: dict):
    """Derived scenario scores never leave their declared ranges."""
    data = scenario_or_analysis
    assert data["total_assigned_students"] >= 0
    assert data["max_utilization_pct"] >= 0
    assert 0.0 <= data["walk_eligible_pct"] <= 100.0, (
        f"walk_eligible_pct must be a percentage, got {data['walk_eligible_pct']}"
    )
    assert data["transport_cost_annual_usd"] >= 0
    assert_two_decimal_places(data["transport_cost_annual_usd"], "transport_cost_annual_usd")
    assert data["students_reassigned_count"] >= 0
    assert 0.0 <= data["students_reassigned_pct"] <= 100.0
    assert data["frl_dissimilarity_index"] >= 0


def assert_district_enrollment_conserved(schools, expected_total):
    """The district-wide sum of enrolled_students_of_record equals expected_total."""
    actual = sum(school["enrolled_students_of_record"] for school in schools)
    assert actual == expected_total, (
        f"Expected district enrolled_students_of_record total {expected_total}, got {actual}"
    )


def assert_pagination_meta(meta: dict, expected_total=None, expected_limit=None, expected_offset=None):
    """The pagination envelope carries limit, offset, total_count and has_more."""
    for key in ("limit", "offset", "total_count", "has_more"):
        assert key in meta, f"pagination meta must carry {key}"
    if expected_total is not None:
        assert meta["total_count"] == expected_total, (
            f"Expected total_count {expected_total}, got {meta['total_count']}"
        )
    if expected_limit is not None:
        assert meta["limit"] == expected_limit, f"Expected limit {expected_limit}, got {meta['limit']}"
    if expected_offset is not None:
        assert meta["offset"] == expected_offset, (
            f"Expected offset {expected_offset}, got {meta['offset']}"
        )


def assert_has_more_consistent(items, meta: dict):
    """has_more is true exactly when records remain beyond this page."""
    expected = meta["offset"] + len(items) < meta["total_count"]
    assert meta["has_more"] is expected, (
        f"Expected has_more {expected} for offset {meta['offset']}, page size "
        f"{len(items)} and total_count {meta['total_count']}, got {meta['has_more']}"
    )
