"""Entity output serializers."""

import calc
from db import db

COMMON = ["id", "created_at", "updated_at", "version"]


def _base(row, fields):
    out = {}
    for name in fields:
        out[name] = row.get(name)
    out["id"] = row["id"]
    out["created_at"] = row["created_at"]
    out["updated_at"] = row["updated_at"]
    out["version"] = row["version"]
    return out


def jurisdiction(row):
    out = _base(
        row,
        [
            "name",
            "code_edition_year",
            "fire_service_required",
            "seismic_zone",
            "door_protection_required",
            "inspection_lead_days",
            "witness_test_required",
            "reinspection_extension_hours",
        ],
    )
    out["permit_surcharge_pct"] = calc.as_number(row["permit_surcharge_pct"])
    return out


def project(row):
    out = _base(
        row,
        [
            "jurisdiction_id",
            "building_name",
            "occupancy_type",
            "contract_value_cents",
            "staging_area_sqft",
            "max_concurrent_outages",
            "outage_buffer_hours",
            "tenant_notice_lead_hours",
            "status",
        ],
    )
    out["car_count"] = calc.project_car_count(row)
    out["approved_scope_value_cents"] = calc.project_approved_scope_value(row)
    out["staging_committed_sqft"] = calc.project_staging_committed(row)
    out["active_outage_count"] = calc.project_active_outage_count(row)
    out["downtime_posture"] = calc.downtime_posture(row)
    return out


def group(row):
    out = _base(row, ["project_id", "group_label", "min_cars_in_service"])
    out["car_count"] = calc.group_car_count(row)
    out["cars_in_service"] = calc.group_cars_in_service(row)
    return out


def car(row):
    out = _base(
        row,
        [
            "project_id",
            "group_id",
            "car_designation",
            "rated_load_lbs",
            "controller_type_legacy",
            "machine_type",
            "duty_rank",
            "work_status",
            "compliance_status",
            "recommended_scope_tier",
        ],
    )
    out["condition_score"] = calc.as_number(row["condition_score"])
    option = calc.approved_option_of_car(row["id"])
    out["approved_scope_option_id"] = option["id"] if option else None
    return out


def survey(row):
    out = _base(
        row,
        [
            "car_id",
            "surveyed_by_user_id",
            "countersigned_by_user_id",
            "controller_condition",
            "machine_condition",
            "door_equipment_condition",
            "recommended_scope_tier",
            "status",
        ],
    )
    out["provisional_score"] = calc.as_number(row["provisional_score"])
    out["final_score"] = calc.as_number(row["final_score"])
    return out


def scope_option(row):
    out = _base(
        row,
        [
            "car_id",
            "tier",
            "base_price_cents",
            "code_upgrade_cents",
            "max_lead_time_days",
            "escalation_fee_cents",
            "volume_discount_cents",
            "total_price_cents",
            "revision_count",
            "rejection_note",
            "status",
        ],
    )
    out["escalation_pct"] = calc.as_number(row["escalation_pct"])
    out["volume_discount_pct"] = calc.as_number(row["volume_discount_pct"])
    return out


def code_trigger(row):
    return _base(
        row,
        [
            "scope_option_id",
            "trigger_type",
            "source_rule",
            "status",
            "cost_cents",
            "waiver_reference",
        ],
    )


def procurement_order(row):
    return _base(
        row,
        [
            "scope_option_id",
            "item_type",
            "lead_time_days",
            "required_staging_sqft",
            "ordered_at",
            "promised_delivery_date",
            "staging_reservation_id",
            "status",
        ],
    )


def staging_reservation(row):
    return _base(
        row,
        ["procurement_order_id", "sqft", "hold_start", "hold_end", "status", "released_at"],
    )


def outage_window(row):
    out = _base(
        row,
        [
            "car_id",
            "predecessor_window_id",
            "start_at",
            "end_at",
            "extension_hours",
            "temporary_service_plan",
            "advance_notice_sent_at",
            "notice_count",
            "status",
            "activated_at",
            "completed_at",
        ],
    )
    out["notice_lead_hours"] = calc.as_number(row["notice_lead_hours"])
    return out


def inspection(row):
    return _base(
        row,
        [
            "car_id",
            "requested_date",
            "witness_requested",
            "scheduled_at",
            "recorded_by_jurisdiction_id",
            "lead_days_at_request",
            "reschedule_count",
            "punch_list_count",
            "status",
        ],
    )


def warranty_transition(row):
    return _base(
        row,
        [
            "car_id",
            "maintenance_contract_id",
            "warranty_months",
            "warranty_start",
            "warranty_end",
            "provisional_credit_cents",
            "final_credit_cents",
            "status",
        ],
    )


def maintenance_contract(row):
    return _base(
        row,
        [
            "project_id",
            "monthly_base_cents",
            "coverage_start",
            "monthly_total_cents",
            "cars_covered",
            "total_final_credit_cents",
            "status",
        ],
    )


SERIALIZERS = {
    "jurisdictions": jurisdiction,
    "projects": project,
    "groups": group,
    "cars": car,
    "surveys": survey,
    "scope_options": scope_option,
    "code_triggers": code_trigger,
    "procurement_orders": procurement_order,
    "staging_reservations": staging_reservation,
    "outage_windows": outage_window,
    "inspections": inspection,
    "warranty_transitions": warranty_transition,
    "contracts": maintenance_contract,
}


def collection(name):
    return getattr(db, name)
