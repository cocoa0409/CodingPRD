"""Serializers — produce the exact public field set for each entity.

Internal-only keys (those prefixed with '_') are never exposed.
"""


def _pub(entity, fields):
    out = {}
    for f in fields:
        out[f] = entity.get(f)
    return out


COMMON = ["id", "created_at", "updated_at", "version"]


def farm_out(f):
    return _pub(f, COMMON + [
        "name", "timezone", "parking_fee_cents", "window_buffer_minutes",
        "operational_status", "active_weather_event_id", "refunds_issued_cents",
    ])


def weather_event_out(w):
    # Append-only log: only id + created_at, plus its own fields. No updated_at/version.
    return _pub(w, ["id", "created_at"] + [
        "farm_id", "kind", "affected_span_start", "affected_span_end",
        "note", "resulting_status",
    ])


def pricing_policy_out(p):
    return _pub(p, COMMON + [
        "farm_id", "adult_admission_cents", "child_admission_cents",
        "hayride_pass_cents", "maze_pass_cents", "upick_pass_cents",
        "pumpkin_per_lb_cents", "pumpkin_flat_each_cents", "heavy_pumpkin_lb",
        "group_rate_min_headcount", "group_discount_pct", "school_discount_pct",
        "season_pass_price_cents", "status",
    ])


def window_out(w):
    return _pub(w, COMMON + [
        "farm_id", "starts_at", "ends_at", "capacity",
        "seats_held", "seats_committed", "seats_available", "status",
    ])


def visitor_out(v):
    return _pub(v, COMMON + ["email", "full_name", "wallet_credit_cents"])


def season_pass_out(s):
    return _pub(s, COMMON + [
        "farm_id", "visitor_id", "purchase_price_cents",
        "valid_from", "valid_until", "status", "visits_used",
    ])


def reservation_out(r):
    return _pub(r, COMMON + [
        "window_id", "visitor_id", "season_pass_id", "group_booking_id",
        "adult_count", "child_count", "participant_count",
        "admission_charge_cents", "settled_charge_cents",
        "expected_window_version", "status",
        "checkout_finalized", "waiver_satisfied",
        "gross_cents", "net_due_cents",
    ])


def activity_pass_out(a):
    return _pub(a, COMMON + [
        "reservation_id", "activity", "quantity",
        "unit_price_cents", "line_total_cents", "status",
    ])


def waiver_out(w):
    return _pub(w, COMMON + [
        "reservation_id", "participant_name", "is_minor", "guardian_name", "status",
    ])


def pumpkin_out(p):
    return _pub(p, COMMON + [
        "reservation_id", "estimated_weight_lb", "scale_weight_lb",
        "charge_cents", "status",
    ])


def concession_out(c):
    return _pub(c, COMMON + [
        "reservation_id", "food_cents", "vehicle_count",
        "parking_cents", "total_cents", "status",
    ])


def group_booking_out(g):
    return _pub(g, COMMON + [
        "farm_id", "window_id", "group_leader_id", "parent_group_id", "kind",
        "adult_count", "child_count", "headcount",
        "quoted_total_cents", "deposit_cents", "expected_window_version", "status",
    ])
