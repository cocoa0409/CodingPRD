"""Public representations of every entity.

Flow links, factory acceptance tests and commissioning ramp steps are
append-only ledger entries: they expose only `id` and `created_at` beside their
own fields, and neither `updated_at` nor `version` appears at all
(PRD section 2.4).
"""

from store import public

PROJECT_FIELDS = [
    "id",
    "customer_name",
    "facility_code",
    "customer_rep_user_id",
    "required_throughput_cph",
    "contract_base_cents",
    "authorized_ceiling_cents",
    "escalation_fee_cents",
    "contract_value_cents",
    "spares_budget_cents",
    "spares_allocated_cents",
    "spares_unallocated_cents",
    "service_tier",
    "response_sla_minutes",
    "design_version",
    "delivery_status",
    "commercial_status",
    "legacy_share_bps",
    "in_transition_share_bps",
    "cutover_share_bps",
    "design_frozen_at",
    "acceptance_ready",
    "created_at",
    "updated_at",
    "version",
]

SEGMENT_FIELDS = [
    "id",
    "project_id",
    "segment_code",
    "equipment_class",
    "rated_capacity_cph",
    "availability_pct",
    "source_share_bps",
    "inbound_link_count",
    "outbound_link_count",
    "flow_share_bps",
    "derated_capacity_cph",
    "created_at",
    "updated_at",
    "version",
]

FLOW_LINK_FIELDS = [
    "id",
    "project_id",
    "from_segment_id",
    "to_segment_id",
    "split_share_bps",
    "created_at",
]

SIMULATION_RUN_FIELDS = [
    "id",
    "project_id",
    "method",
    "design_version_at_run",
    "effective_throughput_cph",
    "bottleneck_segment_code",
    "bottleneck_availability_pct",
    "shortfall_cph",
    "status",
    "created_at",
    "updated_at",
    "version",
]

STAGING_BAY_FIELDS = [
    "id",
    "bay_code",
    "concurrent_capacity",
    "created_at",
    "updated_at",
    "version",
]

FABRICATION_LOT_FIELDS = [
    "id",
    "project_id",
    "staging_bay_id",
    "lot_code",
    "segment_codes",
    "occupancy_start_utc",
    "occupancy_end_utc",
    "fat_target_cph",
    "fat_attempt_count",
    "status",
    "created_at",
    "updated_at",
    "version",
]

FAT_TEST_FIELDS = [
    "id",
    "fabrication_lot_id",
    "attempt_no",
    "measured_cph",
    "defect_count",
    "target_cph_at_test",
    "result",
    "created_at",
]

SITE_ZONE_FIELDS = [
    "id",
    "project_id",
    "zone_code",
    "throughput_share_bps",
    "protected_shift_start_minute",
    "protected_shift_end_minute",
    "buffer_minutes",
    "ops_status",
    "created_at",
    "updated_at",
    "version",
]

CUTOVER_WINDOW_FIELDS = [
    "id",
    "project_id",
    "site_zone_id",
    "fabrication_lot_id",
    "start_utc",
    "end_utc",
    "status",
    "abort_reason",
    "started_at",
    "closed_at",
    "created_at",
    "updated_at",
    "version",
]

COMMISSIONING_RAMP_FIELDS = [
    "id",
    "project_id",
    "step_pct",
    "measured_cph",
    "sustained_minutes",
    "target_cph",
    "min_sustained_minutes",
    "verdict",
    "recorded_by_user_id",
    "created_at",
]

ACCEPTANCE_CERTIFICATE_FIELDS = [
    "id",
    "project_id",
    "accepted_throughput_cph",
    "bottleneck_availability_pct",
    "retention_amount_cents",
    "retention_release_cents",
    "issued_by_user_id",
    "dispute_deadline_utc",
    "status",
    "created_at",
    "updated_at",
    "version",
]

CHANGE_ORDER_FIELDS = [
    "id",
    "project_id",
    "title",
    "scope_delta_cph",
    "price_delta_cents",
    "schedule_delta_days",
    "round_no",
    "decision_comment",
    "reviewed_by_user_id",
    "status",
    "created_at",
    "updated_at",
    "version",
]

SPARE_PART_LINE_FIELDS = [
    "id",
    "project_id",
    "part_no",
    "criticality",
    "unit_cost_cents",
    "min_stock_qty",
    "lead_time_days",
    "requested_cents",
    "weighted_target_cents",
    "allocated_cents",
    "status",
    "created_at",
    "updated_at",
    "version",
]

PERFORMANCE_DISPUTE_FIELDS = [
    "id",
    "acceptance_certificate_id",
    "claimed_cph",
    "damages_basis",
    "provisional_nameplate_cents",
    "provisional_observed_cents",
    "bound_provisional_cents",
    "retest_measured_cph",
    "final_damages_cents",
    "sla_credit_cents",
    "filed_by_user_id",
    "retest_by_user_id",
    "retest_recorded_at",
    "status",
    "created_at",
    "updated_at",
    "version",
]


def project_out(project):
    from services.calculations import acceptance_ready

    data = public(project, PROJECT_FIELDS)
    data["acceptance_ready"] = acceptance_ready(project)
    return data


def segment_out(segment):
    return public(segment, SEGMENT_FIELDS)


def flow_link_out(link):
    return public(link, FLOW_LINK_FIELDS)


def simulation_run_out(run):
    return public(run, SIMULATION_RUN_FIELDS)


def staging_bay_out(bay):
    return public(bay, STAGING_BAY_FIELDS)


def fabrication_lot_out(lot):
    data = public(lot, FABRICATION_LOT_FIELDS)
    data["segment_codes"] = list(lot.get("segment_codes") or [])
    return data


def fat_test_out(test):
    return public(test, FAT_TEST_FIELDS)


def site_zone_out(zone):
    return public(zone, SITE_ZONE_FIELDS)


def cutover_window_out(window):
    return public(window, CUTOVER_WINDOW_FIELDS)


def commissioning_ramp_out(ramp):
    return public(ramp, COMMISSIONING_RAMP_FIELDS)


def acceptance_certificate_out(certificate):
    return public(certificate, ACCEPTANCE_CERTIFICATE_FIELDS)


def change_order_out(order):
    return public(order, CHANGE_ORDER_FIELDS)


def spare_part_line_out(line):
    return public(line, SPARE_PART_LINE_FIELDS)


def performance_dispute_out(dispute):
    return public(dispute, PERFORMANCE_DISPUTE_FIELDS)
