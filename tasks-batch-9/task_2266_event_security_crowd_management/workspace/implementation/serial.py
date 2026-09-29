"""Explicit output projections per entity (internal bookkeeping keys stripped)."""

COMMON = ("id", "created_at", "updated_at", "version")

VENUE = (
    "id",
    "name",
    "gross_capacity",
    "door_count",
    "egress_capacity_per_minute",
    "perimeter_length_m",
    "alcohol_licensed",
    "prior_incident_rate",
    "status",
) + COMMON[1:]

ZONE = (
    "id",
    "venue_id",
    "zone_code",
    "zone_type",
    "floor_area_sqm",
    "posted_capacity",
    "exit_units",
    "post_slot_capacity",
    "is_ingress_zone",
    "max_safe_occupancy",
) + COMMON[1:]

EVENT = (
    "id",
    "venue_id",
    "event_name",
    "event_type",
    "doors_open_at",
    "event_start_at",
    "event_end_at",
    "expected_attendance",
    "ticketed_attendance",
    "alcohol_served",
    "vip_present",
    "status",
    "ingress_status",
    "gate_posture",
    "open_critical_incident_count",
) + COMMON[1:]

ASSESSMENT = (
    "id",
    "event_id",
    "revision_number",
    "threat_level_input",
    "protest_likelihood",
    "crowd_profile",
    "ingress_door_count",
    "layout_complexity_score",
    "history_incident_rate",
    "attendance_basis",
    "score_basis_attendance",
    "composite_threat_score",
    "risk_tier",
    "required_line_guards",
    "required_perimeter_guards",
    "required_ingress_guards",
    "required_floor_guards",
    "required_exit_guards",
    "required_supervisors",
    "required_total_staff",
    "required_screening_lanes",
    "minimum_staffing_cost_floor_cents",
    "status",
    "submitted_by_user_id",
    "approved_by_user_id",
    "rejection_reason",
) + COMMON[1:]

PLAN = (
    "id",
    "event_id",
    "risk_assessment_id",
    "pinned_risk_assessment_version",
    "supersedes_plan_id",
    "budget_cents",
    "committed_cost_cents",
    "billed_cost_cents",
    "budget_remaining_cents",
    "committed_guard_hours",
    "required_total_staff",
    "filled_total_staff",
    "coverage_ratio",
    "understaffed_post_count",
    "readiness_posture",
    "status",
    "is_current",
) + COMMON[1:]

POST = (
    "id",
    "staffing_plan_id",
    "zone_id",
    "reports_to_post_id",
    "lane_id",
    "post_code",
    "post_type",
    "required_guard_count",
    "min_credential_level",
    "window_start",
    "window_end",
    "filled_guard_count",
    "status",
) + COMMON[1:]

SUBCONTRACTOR = (
    "id",
    "company_name",
    "license_number",
    "insurance_expires_on",
    "markup_pct",
    "status",
    "verified_guard_count",
) + COMMON[1:]

GUARD = (
    "id",
    "full_name",
    "employment_type",
    "subcontractor_id",
    "credential_level",
    "license_number",
    "credential_expires_on",
    "base_hourly_rate_cents",
    "verification_status",
    "verified_at",
    "is_supervisor_qualified",
) + COMMON[1:]

ASSIGNMENT = (
    "id",
    "post_id",
    "guard_id",
    "window_start",
    "window_end",
    "assignment_status",
    "duty_status",
    "scheduled_hours",
    "night_differential_applies",
    "pay_basis",
    "line_cost_cents",
    "billed_hours",
    "billed_cost_cents",
    "radio_channel",
    "training_module_code",
    "briefed_at",
    "check_in_at",
    "relieved_at",
    "cancellation_reason",
) + COMMON[1:]

LANE = (
    "id",
    "event_id",
    "zone_id",
    "lane_type",
    "nominal_throughput_pph",
    "operator_capacity",
    "open_from",
    "open_to",
    "status",
    "assigned_operator_count",
    "effective_throughput_pph",
) + COMMON[1:]

READING = (
    "id",
    "event_id",
    "zone_id",
    "observed_at",
    "observed_occupancy",
    "reported_by_user_id",
    "density_persons_per_sqm",
    "occupancy_ratio",
    "rolling_mean_persons_per_sqm",
    "instantaneous_level",
    "rolling_level",
    "effective_level",
    "created_at",
)

INCIDENT = (
    "id",
    "event_id",
    "zone_id",
    "category",
    "severity",
    "severity_at_report",
    "description",
    "reported_by_user_id",
    "reported_at",
    "triaged_at",
    "resolved_at",
    "response_minutes",
    "sla_breached",
    "handoff_agency_ref",
    "ejection_patron_ref",
    "resolution_note",
    "status",
) + COMMON[1:]

REVIEW = (
    "id",
    "event_id",
    "narrative",
    "corrective_action_count",
    "authored_by_user_id",
    "finalized_by_user_id",
    "return_reason",
    "total_incident_count",
    "sla_breach_count",
    "peak_density_level",
    "no_show_rate",
    "coverage_shortfall_minutes",
    "status",
) + COMMON[1:]


def _project(record, fields):
    return {name: record.get(name) for name in fields}


def venue(record):
    return _project(record, VENUE)


def zone(record):
    return _project(record, ZONE)


def event(record):
    return _project(record, EVENT)


def assessment(record):
    return _project(record, ASSESSMENT)


def plan(record):
    return _project(record, PLAN)


def post(record):
    return _project(record, POST)


def subcontractor(record):
    return _project(record, SUBCONTRACTOR)


def guard(record):
    return _project(record, GUARD)


def assignment(record):
    return _project(record, ASSIGNMENT)


def lane(record):
    return _project(record, LANE)


def reading(record):
    return _project(record, READING)


def incident(record):
    return _project(record, INCIDENT)


def review(record):
    return _project(record, REVIEW)
