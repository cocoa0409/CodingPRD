"""Per-entity serializers — return only the documented fields, in stable shape."""


def _common(row, with_version=True):
    base = {"id": row["id"], "created_at": row["created_at"]}
    if with_version:
        base["updated_at"] = row.get("updated_at")
        base["version"] = row.get("version")
    return base


def view_volunteer(row):
    return {
        **_common(row),
        "full_name": row.get("full_name"),
        "id_number_hash": row.get("id_number_hash"),
        "identity_verification_status": row.get("identity_verification_status"),
        "background_check_status": row.get("background_check_status"),
        "home_lat": row.get("home_lat"),
        "home_lng": row.get("home_lng"),
        "total_service_hours": row.get("total_service_hours", 0),
        "total_completed_activities": row.get("total_completed_activities", 0),
        "points_balance": row.get("points_balance", 0),
        "archived_hours": row.get("archived_hours", 0),
    }


def view_skill(row):
    return {
        **_common(row),
        "code": row.get("code"),
        "name": row.get("name"),
        "requires_certificate": row.get("requires_certificate", False),
        "sensitivity_level": row.get("sensitivity_level", "STANDARD"),
    }


def view_volunteer_skill(row):
    return {
        **_common(row, with_version=False),
        "volunteer_id": row.get("volunteer_id"),
        "skill_id": row.get("skill_id"),
        "certificate_url": row.get("certificate_url"),
        "review_status": row.get("review_status"),
        "reviewed_at": row.get("reviewed_at"),
        "reviewer_id": row.get("reviewer_id"),
    }


def view_activity(row):
    return {
        **_common(row),
        "organizer_id": row.get("organizer_id"),
        "title": row.get("title"),
        "description": row.get("description"),
        "location_lat": row.get("location_lat"),
        "location_lng": row.get("location_lng"),
        "start_at": row.get("start_at"),
        "end_at": row.get("end_at"),
        "recruit_open_at": row.get("recruit_open_at"),
        "recruit_close_at": row.get("recruit_close_at"),
        "required_skill_codes": row.get("required_skill_codes", []),
        "position_quota": row.get("position_quota"),
        "filled_positions": row.get("filled_positions", 0),
        "difficulty": row.get("difficulty", "MEDIUM"),
        "hour_rule_type": row.get("hour_rule_type", "ACTUAL_DURATION"),
        "fixed_hour_value": row.get("fixed_hour_value"),
        "requires_sensitive_clearance": row.get("requires_sensitive_clearance", False),
        "status": row.get("status"),
        "site_code": row.get("site_code"),
    }


def view_activity_role(row):
    return {
        **_common(row, with_version=False),
        "activity_id": row.get("activity_id"),
        "role_label": row.get("role_label"),
        "coefficient": row.get("coefficient", 1.0),
    }


def view_application(row):
    return {
        **_common(row),
        "activity_id": row.get("activity_id"),
        "volunteer_id": row.get("volunteer_id"),
        "activity_role_id": row.get("activity_role_id"),
        "distance_km": row.get("distance_km"),
        "status": row.get("status"),
        "check_in_at": row.get("check_in_at"),
        "check_in_lat": row.get("check_in_lat"),
        "check_in_lng": row.get("check_in_lng"),
        "check_out_at": row.get("check_out_at"),
        "late_marker": row.get("late_marker", False),
        "early_departure_marker": row.get("early_departure_marker", False),
        "credited_hours": row.get("credited_hours", 0),
        "adjusted_hours": row.get("adjusted_hours", 0),
        "points_awarded": row.get("points_awarded", 0),
        "leave_reason": row.get("leave_reason"),
    }


def view_hour_adjustment(row):
    return {
        **_common(row),
        "application_id": row.get("application_id"),
        "requested_by_id": row.get("requested_by_id"),
        "delta_hours": row.get("delta_hours"),
        "reason": row.get("reason"),
        "status": row.get("status"),
        "approver_id": row.get("approver_id"),
        "decided_at": row.get("decided_at"),
    }


def view_point_mall_item(row):
    return {
        **_common(row),
        "sku": row.get("sku"),
        "name": row.get("name"),
        "point_cost": row.get("point_cost"),
        "stock": row.get("stock", 0),
        "status": row.get("status"),
    }


def view_redemption_order(row):
    return {
        **_common(row),
        "volunteer_id": row.get("volunteer_id"),
        "item_id": row.get("item_id"),
        "quantity": row.get("quantity"),
        "total_points": row.get("total_points"),
        "status": row.get("status"),
    }


def view_certificate_template(row):
    return {
        **_common(row),
        "code": row.get("code"),
        "title": row.get("title"),
        "min_hours": row.get("min_hours"),
        "min_completed_activities": row.get("min_completed_activities"),
        "status": row.get("status"),
    }


def view_certificate(row):
    return {
        **_common(row),
        "template_id": row.get("template_id"),
        "volunteer_id": row.get("volunteer_id"),
        "serial_number": row.get("serial_number"),
        "hours_at_issuance": row.get("hours_at_issuance"),
        "activities_at_issuance": row.get("activities_at_issuance"),
        "status": row.get("status"),
        "replacement_serial_number": row.get("replacement_serial_number"),
    }


def view_audit_log(row):
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "actor_role": row.get("actor_role"),
        "actor_id": row.get("actor_id"),
        "action_type": row.get("action_type"),
        "target_entity": row.get("target_entity"),
        "target_id": row.get("target_id"),
        "payload": row.get("payload"),
    }


def view_partner_sync_event(row):
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "channel": row.get("channel"),
        "event_type": row.get("event_type"),
        "payload": row.get("payload"),
    }
