"""Entity -> public JSON serializers.

Computed fields (latest_weight_kg, no_show_strikes, booking_privilege,
sessions_committed, sessions_remaining) are recomputed/refreshed by the service
layer and stored on the record before serialization; serializers simply project
the stored shape. Common-fields entities expose created_at/updated_at/version;
append-only events (HabitLog, Message) expose only id + created_at.
"""


def trainer_view(t):
    return {
        "id": t["id"],
        "full_name": t["full_name"],
        "email": t["email"],
        "timezone": t["timezone"],
        "status": t["status"],
        "created_at": t["created_at"],
        "updated_at": t["updated_at"],
        "version": t["version"],
    }


def client_view(c):
    return {
        "id": c["id"],
        "trainer_id": c["trainer_id"],
        "full_name": c["full_name"],
        "email": c["email"],
        "sex": c["sex"],
        "birth_year": c["birth_year"],
        "height_cm": c["height_cm"],
        "intake_status": c["intake_status"],
        "latest_weight_kg": c["latest_weight_kg"],
        "no_show_strikes": c["no_show_strikes"],
        "booking_privilege": c["booking_privilege"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def engagement_view(e):
    return {
        "id": e["id"],
        "client_id": e["client_id"],
        "trainer_id": e["trainer_id"],
        "billing_model": e["billing_model"],
        "status": e["status"],
        "wallet_credit_cents": e["wallet_credit_cents"],
        "pause_reason": e["pause_reason"],
        "created_at": e["created_at"],
        "updated_at": e["updated_at"],
        "version": e["version"],
    }


def session_pack_view(p):
    return {
        "id": p["id"],
        "engagement_id": p["engagement_id"],
        "total_sessions": p["total_sessions"],
        "price_cents": p["price_cents"],
        "per_session_value_cents": p["per_session_value_cents"],
        "sessions_committed": p["sessions_committed"],
        "sessions_remaining": p["sessions_remaining"],
        "status": p["status"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def booking_view(b):
    return {
        "id": b["id"],
        "engagement_id": b["engagement_id"],
        "session_pack_id": b["session_pack_id"],
        "trainer_id": b["trainer_id"],
        "start_utc": b["start_utc"],
        "end_utc": b["end_utc"],
        "rescheduled_from_booking_id": b["rescheduled_from_booking_id"],
        "fee_charged_cents": b["fee_charged_cents"],
        "status": b["status"],
        "created_at": b["created_at"],
        "updated_at": b["updated_at"],
        "version": b["version"],
    }


def program_view(p):
    return {
        "id": p["id"],
        "engagement_id": p["engagement_id"],
        "title": p["title"],
        "planned_workouts_per_week": p["planned_workouts_per_week"],
        "habit_checks_target": p["habit_checks_target"],
        "status": p["status"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def macro_plan_view(m):
    return {
        "id": m["id"],
        "engagement_id": m["engagement_id"],
        "goal": m["goal"],
        "activity_level": m["activity_level"],
        "snapshot_weight_kg": m["snapshot_weight_kg"],
        "target_calories": m["target_calories"],
        "protein_g": m["protein_g"],
        "carb_g": m["carb_g"],
        "fat_g": m["fat_g"],
        "status": m["status"],
        "created_at": m["created_at"],
        "updated_at": m["updated_at"],
        "version": m["version"],
    }


def check_in_view(c):
    return {
        "id": c["id"],
        "engagement_id": c["engagement_id"],
        "measured_at": c["measured_at"],
        "weight_kg": c["weight_kg"],
        "photo_urls": c["photo_urls"],
        "window_start_utc": c["window_start_utc"],
        "window_end_utc": c["window_end_utc"],
        "adherence_score": c["adherence_score"],
        "status": c["status"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def habit_log_view(h):
    return {
        "id": h["id"],
        "engagement_id": h["engagement_id"],
        "program_assignment_id": h["program_assignment_id"],
        "kind": h["kind"],
        "logged_at": h["logged_at"],
        "created_at": h["created_at"],
    }


def message_view(m):
    return {
        "id": m["id"],
        "engagement_id": m["engagement_id"],
        "sender_role": m["sender_role"],
        "body": m["body"],
        "created_at": m["created_at"],
    }
