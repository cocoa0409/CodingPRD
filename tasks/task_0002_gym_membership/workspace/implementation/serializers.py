"""Serializers — strip private fields (e.g., password_hash) when returning entities."""
from common import format_iso


def _common(obj):
    return {
        "id": obj["id"],
        "created_at": format_iso(obj["created_at"]),
        "updated_at": format_iso(obj.get("updated_at")) if "updated_at" in obj else None,
        "version": obj.get("version"),
    }


def serialize_member(m):
    out = {
        "id": m["id"],
        "email": m["email"],
        "home_store_id": m["home_store_id"],
        "tier": m["tier"],
        "state_code": m["state_code"],
        "billing_status": m["billing_status"],
        "access_status": m["access_status"],
        "account_posture": m["account_posture"],
        "no_show_strike_count": m["no_show_strike_count"],
        "wallet_credit_cents": m["wallet_credit_cents"],
        "suspension_window_start": format_iso(m["suspension_window_start"]),
        "suspension_window_end": format_iso(m["suspension_window_end"]),
        "referred_by_member_id": m.get("referred_by_member_id"),
        "created_at": format_iso(m["created_at"]),
        "updated_at": format_iso(m["updated_at"]),
        "version": m["version"],
    }
    return out


def serialize_subscription(s):
    return {
        "id": s["id"],
        "member_id": s["member_id"],
        "plan": s["plan"],
        "billing_cycle": s["billing_cycle"],
        "base_price_cents": s["base_price_cents"],
        "status": s["status"],
        "current_period_start": format_iso(s.get("current_period_start")),
        "current_period_end": format_iso(s.get("current_period_end")),
        "auto_renew": s["auto_renew"],
        "failed_payment_attempts": s["failed_payment_attempts"],
        "grace_period_end": format_iso(s.get("grace_period_end")),
        "cancellation_effective_at": format_iso(s.get("cancellation_effective_at")),
        "applied_coupon_id": s.get("applied_coupon_id"),
        "created_at": format_iso(s["created_at"]),
        "updated_at": format_iso(s["updated_at"]),
        "version": s["version"],
    }


def serialize_payment_attempt(p):
    return {
        "id": p["id"],
        "subscription_id": p["subscription_id"],
        "member_id": p["member_id"],
        "attempt_number": p["attempt_number"],
        "amount_cents": p["amount_cents"],
        "gateway_txn_id": p["gateway_txn_id"],
        "idempotency_key": p["idempotency_key"],
        "outcome": p["outcome"],
        "failure_reason": p.get("failure_reason"),
        "created_at": format_iso(p["created_at"]),
    }


def serialize_store(s):
    return {
        "id": s["id"],
        "name": s["name"],
        "state_code": s["state_code"],
        "opens_at_local": s["opens_at_local"],
        "closes_at_local": s["closes_at_local"],
        "gate_device_id": s["gate_device_id"],
        "created_at": format_iso(s["created_at"]),
        "updated_at": format_iso(s["updated_at"]),
        "version": s["version"],
    }


def serialize_class_session(cs):
    return {
        "id": cs["id"],
        "store_id": cs["store_id"],
        "class_type": cs["class_type"],
        "trainer_id": cs["trainer_id"],
        "starts_at": format_iso(cs["starts_at"]),
        "ends_at": format_iso(cs["ends_at"]),
        "capacity": cs["capacity"],
        "minimum_tier": cs["minimum_tier"],
        "equipment_pool_id": cs.get("equipment_pool_id"),
        "equipment_units_required": cs["equipment_units_required"],
        "reserved_seat_count": cs["reserved_seat_count"],
        "status": cs["status"],
        "created_at": format_iso(cs["created_at"]),
        "updated_at": format_iso(cs["updated_at"]),
        "version": cs["version"],
    }


def serialize_trainer(t):
    return {
        "id": t["id"],
        "full_name": t["full_name"],
        "home_store_id": t["home_store_id"],
        "certifications": list(t["certifications"]),
        "hourly_rate_cents": t["hourly_rate_cents"],
        "created_at": format_iso(t["created_at"]),
        "updated_at": format_iso(t["updated_at"]),
        "version": t["version"],
    }


def serialize_equipment_pool(ep):
    return {
        "id": ep["id"],
        "store_id": ep["store_id"],
        "equipment_type": ep["equipment_type"],
        "total_units": ep["total_units"],
        "maintenance_window_start": ep.get("maintenance_window_start") and __import__("common").format_iso(ep["maintenance_window_start"]),
        "maintenance_window_end": ep.get("maintenance_window_end") and __import__("common").format_iso(ep["maintenance_window_end"]),
        "created_at": format_iso(ep["created_at"]),
        "updated_at": format_iso(ep["updated_at"]),
        "version": ep["version"],
    }


def serialize_booking(b):
    return {
        "id": b["id"],
        "member_id": b["member_id"],
        "booking_kind": b["booking_kind"],
        "class_session_id": b.get("class_session_id"),
        "trainer_id": b.get("trainer_id"),
        "store_id": b["store_id"],
        "starts_at": format_iso(b["starts_at"]),
        "ends_at": format_iso(b["ends_at"]),
        "applied_coupon_id": b.get("applied_coupon_id"),
        "waitlist_position": b.get("waitlist_position"),
        "provisional_price_cents": b.get("provisional_price_cents"),
        "final_price_cents": b.get("final_price_cents"),
        "status": b["status"],
        "gate_check_in_at": format_iso(b.get("gate_check_in_at")),
        "created_at": format_iso(b["created_at"]),
        "updated_at": format_iso(b["updated_at"]),
        "version": b["version"],
    }


def serialize_coupon(c):
    return {
        "id": c["id"],
        "code": c["code"],
        "kind": c["kind"],
        "value": c["value"],
        "applicable_to": c["applicable_to"],
        "valid_from": format_iso(c["valid_from"]),
        "valid_until": format_iso(c["valid_until"]),
        "max_redemptions": c["max_redemptions"],
        "redemption_count": c["redemption_count"],
        "status": c["status"],
        "tied_to_member_id": c.get("tied_to_member_id"),
        "created_at": format_iso(c["created_at"]),
        "updated_at": format_iso(c["updated_at"]),
        "version": c["version"],
    }


def serialize_referral(r):
    return {
        "id": r["id"],
        "sponsor_member_id": r["sponsor_member_id"],
        "invitee_member_id": r["invitee_member_id"],
        "minted_coupon_id": r.get("minted_coupon_id"),
        "status": r["status"],
        "qualifying_attempt_id": r.get("qualifying_attempt_id"),
        "reward_value_cents": r.get("reward_value_cents"),
        "created_at": format_iso(r["created_at"]),
        "updated_at": format_iso(r["updated_at"]),
        "version": r["version"],
    }


def serialize_wallet(m):
    return {
        "member_id": m["id"],
        "wallet_credit_cents": m["wallet_credit_cents"],
        "ledger": list(m.get("wallet_ledger", [])),
    }
