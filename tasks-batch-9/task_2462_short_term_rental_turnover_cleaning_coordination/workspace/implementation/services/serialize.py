"""Entity -> JSON views.  Field lists mirror the declared entity fields."""

from db import iso
from services.money import as_number

_COMMON = ["id", ("created_at", "dt"), ("updated_at", "dt"), "version"]

PROPERTY_FIELDS = _COMMON + [
    "code", "name", "zone_code", "size_tier", "bedroom_count", "bathroom_count",
    "bed_count", "local_utc_offset_minutes", "min_clean_minutes", "min_skill_level",
    "owner_contact_email", "owner_notify_min_cost_cents", "status", "open_issue_count",
    ("last_turnover_completed_at", "dt"),
]

CLEANER_FIELDS = _COMMON + [
    "name", "home_zone_code", "secondary_zone_codes", "accepts_cross_zone",
    "skill_level", "max_daily_turnovers", ("quality_score", "n2"), "status",
    "pending_payout_cents", "completed_turnover_count", "decline_count", "strike_count",
]

BOOKING_FIELDS = _COMMON + [
    "property_id", "external_ref", "guest_name", "party_size", "pet_stay",
    ("checkin_at", "dt"), ("checkout_at", "dt"), ("late_checkout_until_at", "dt"),
    ("early_checkin_at", "dt"), ("actual_checkout_at", "dt"), "status", "checkin_gate",
    "guest_notice_code", "cleanliness_rating", ("cleanliness_rated_at", "dt"),
]

TURNOVER_FIELDS = _COMMON + [
    "property_id", "outgoing_booking_id", "incoming_booking_id",
    "blocking_repair_order_id", ("window_start_at", "dt"), ("window_end_at", "dt"),
    "window_minutes", "required_minutes", "slack_minutes", "turn_type", "is_tight",
    "override_reason", "escalation_required", "status", "pre_hold_status",
    "rework_round", "rejected_review_count", "checklist_task_count",
    "restock_chargeback_cents", ("started_at", "dt"), ("finished_at", "dt"),
    "late_minutes",
]

ASSIGNMENT_FIELDS = _COMMON + [
    "turnover_id", "cleaner_id", "sequence_no", ("match_score", "n4"),
    ("zone_match_factor", "n1"), "selection_mode", "assigned_by_user_id", "status",
    ("accepted_at", "dt"), ("declined_at", "dt"), ("revoked_at", "dt"),
]

CHECKLIST_TASK_FIELDS = _COMMON + [
    "turnover_id", "task_code", "category", "sequence_no", "requires_photo",
    "photo_uri", "note", "status", ("submitted_at", "dt"), "reviewed_by_user_id",
    "reject_count", "reject_reason", "restock_line_count", "restock_charge_cents",
]

SUPPLY_LINE_FIELDS = _COMMON + [
    "property_id", "sku", "name", "category", "unit", "unit_cost_cents", "par_qty",
    "reorder_point", "on_hand_qty", "below_par", "status",
]

STOCK_MOVEMENT_FIELDS = [
    "id", ("created_at", "dt"), "supply_line_id", "turnover_id", "checklist_task_id",
    "sequence_no", "reason", "delta_qty", "unit_cost_cents_at_time", "charge_cents",
    "note",
]

ISSUE_REPORT_FIELDS = _COMMON + [
    "turnover_id", "property_id", "reported_by_cleaner_id", "issue_type", "severity",
    "description", "estimated_cost_cents", "guest_chargeable", "status",
    ("owner_notified_at", "dt"),
]

REPAIR_ORDER_FIELDS = _COMMON + [
    "issue_report_id", "property_id", "vendor_name", ("scheduled_at", "dt"),
    "blocks_checkin", "actual_cost_cents", "completion_note", "status",
    ("completed_at", "dt"),
]

QUALITY_AUDIT_FIELDS = _COMMON + [
    "turnover_id", "cleaner_id", "auditor_user_id", "score", "findings",
    "variant_applied", "guest_rating_at_audit", ("observed_score", "n2"),
    ("resulting_quality_score", "n2"), "pay_adjustment_cents", "status",
    ("finalized_at", "dt"),
]

PAY_LINE_FIELDS = _COMMON + [
    "assignment_id", "cleaner_id", "turnover_id", "variant", "size_base_cents",
    "rush_premium_cents", "tight_window_premium_cents", "cross_zone_premium_cents",
    "linen_units", "linen_adder_cents", "gross_cents", "on_time_bonus_cents",
    "photo_pass_bonus_cents", "bonus_cents", "late_minutes", "late_penalty_cents",
    "photo_penalty_cents", "audit_adjustment_cents", "penalty_cents", "net_cents",
    "status",
]


def _view(record, fields):
    out = {}
    for spec in fields:
        if isinstance(spec, tuple):
            name, kind = spec
        else:
            name, kind = spec, "raw"
        value = record.get(name)
        if kind == "dt":
            out[name] = iso(value)
        elif kind == "n1":
            out[name] = as_number(value, 1)
        elif kind == "n2":
            out[name] = as_number(value, 2)
        elif kind == "n4":
            out[name] = as_number(value, 4)
        else:
            out[name] = value
    return out


def property_view(record):
    return _view(record, PROPERTY_FIELDS)


def cleaner_view(record):
    return _view(record, CLEANER_FIELDS)


def booking_view(record):
    return _view(record, BOOKING_FIELDS)


def turnover_view(record):
    return _view(record, TURNOVER_FIELDS)


def assignment_view(record):
    return _view(record, ASSIGNMENT_FIELDS)


def checklist_task_view(record):
    return _view(record, CHECKLIST_TASK_FIELDS)


def supply_line_view(record):
    return _view(record, SUPPLY_LINE_FIELDS)


def stock_movement_view(record):
    return _view(record, STOCK_MOVEMENT_FIELDS)


def issue_report_view(record):
    return _view(record, ISSUE_REPORT_FIELDS)


def repair_order_view(record):
    return _view(record, REPAIR_ORDER_FIELDS)


def quality_audit_view(record):
    return _view(record, QUALITY_AUDIT_FIELDS)


def pay_line_view(record):
    return _view(record, PAY_LINE_FIELDS)


def pay_preview_view(numbers, turnover, assignment, cleaner):
    """An unpersisted PayLine projection: id and status are null (PRD 3.8)."""
    record = dict(numbers)
    record["assignment_id"] = assignment["id"] if assignment else None
    record["cleaner_id"] = cleaner["id"] if cleaner else None
    record["turnover_id"] = turnover["id"]
    record["id"] = None
    record["status"] = None
    record["created_at"] = None
    record["updated_at"] = None
    record["version"] = None
    return _view(record, PAY_LINE_FIELDS)
