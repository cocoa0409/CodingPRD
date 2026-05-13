"""Object serializers: convert in-memory dicts to JSON-friendly forms."""
from clock import to_iso_ms
from db import state
from services.wallet import project_member_balances


def _iso(v):
    if v is None:
        return None
    if isinstance(v, str):
        return v
    return to_iso_ms(v)


def _common(obj):
    return {
        "id": obj["id"],
        "created_at": _iso(obj.get("created_at")),
        "updated_at": _iso(obj.get("updated_at")),
        "version": obj.get("version"),
    }


def _append_only(obj):
    return {
        "id": obj["id"],
        "created_at": _iso(obj.get("created_at")),
    }


def serialize_member(m):
    p, b, exp = project_member_balances(m["id"])
    out = {
        **_common(m),
        "full_name": m["full_name"],
        "phone": m["phone"],
        "email": m["email"],
        "family_group_id": m.get("family_group_id"),
        "notification_channels": list(m.get("notification_channels", [])),
        "auto_renew_authorized": m.get("auto_renew_authorized", False),
        "wallet_balance_cents": p + b,
        "principal_balance_cents": p,
        "bonus_balance_cents": b,
        "bonus_expires_at": _iso(exp),
    }
    return out


def serialize_card_type(ct):
    return {
        **_common(ct),
        "code": ct["code"],
        "category": ct["category"],
        "price_cents": ct["price_cents"],
        "validity_days": ct["validity_days"],
        "visit_quota": ct["visit_quota"],
        "family_shareable": ct.get("family_shareable", False),
        "max_freeze_days": ct["max_freeze_days"],
        "transfer_fee_pct_bp": ct["transfer_fee_pct_bp"],
        "renewal_discount_pct_bp": ct.get("renewal_discount_pct_bp", 0),
        "refund_eligibility_days": ct["refund_eligibility_days"],
        "status": ct.get("status", "ACTIVE"),
    }


def serialize_card(c):
    ct = state["card_types"].get(c["card_type_id"])
    quota = ct["visit_quota"] if ct else 0
    visits_consumed = c.get("visits_consumed", 0)
    if quota and quota > 0:
        visits_remaining = max(quota - visits_consumed, 0)
    else:
        visits_remaining = None
    return {
        **_common(c),
        "card_type_id": c["card_type_id"],
        "holder_member_id": c["holder_member_id"],
        "issuance_price_cents": c.get("issuance_price_cents"),
        "activation_date": _iso(c.get("activation_date")),
        "original_expiry_date": _iso(c.get("original_expiry_date")),
        "effective_expiry_date": _iso(c.get("effective_expiry_date")),
        "visits_consumed": visits_consumed,
        "visits_remaining": visits_remaining,
        "cumulative_freeze_days": c.get("cumulative_freeze_days", 0),
        "status": c.get("status", "PENDING"),
        "parent_card_id": c.get("parent_card_id"),
    }


def serialize_trainer(t):
    return {
        **_common(t),
        "full_name": t["full_name"],
        "specialties": list(t.get("specialties", [])),
        "session_commission_pct_bp": t["session_commission_pct_bp"],
        "package_commission_pct_bp": t["package_commission_pct_bp"],
        "tier": t.get("tier", "BRONZE"),
        "status": t.get("status", "ACTIVE"),
    }


def serialize_slot(s):
    return {
        **_common(s),
        "trainer_id": s["trainer_id"],
        "starts_at": _iso(s.get("starts_at")),
        "ends_at": _iso(s.get("ends_at")),
        "specialty_code": s["specialty_code"],
        "status": s.get("status", "OPEN"),
    }


def serialize_pt_booking(b):
    return {
        **_common(b),
        "member_id": b["member_id"],
        "trainer_id": b["trainer_id"],
        "slot_id": b["slot_id"],
        "package_id": b.get("package_id"),
        "billing_mode": b["billing_mode"],
        "session_price_cents": b.get("session_price_cents"),
        "status": b.get("status", "CONFIRMED"),
        "scheduled_starts_at": _iso(b.get("scheduled_starts_at")),
    }


def serialize_pt_package(p):
    return {
        **_common(p),
        "member_id": p["member_id"],
        "trainer_id": p["trainer_id"],
        "total_sessions": p["total_sessions"],
        "gross_price_cents": p["gross_price_cents"],
        "sessions_consumed": p.get("sessions_consumed", 0),
        "sessions_refunded": p.get("sessions_refunded", 0),
        "status": p.get("status", "ACTIVE"),
    }


def serialize_group_class(c):
    confirmed_count = sum(
        1 for b in state["group_bookings"].values()
        if b["class_id"] == c["id"] and b["status"] == "CONFIRMED"
    )
    waitlist_count = sum(
        1 for b in state["group_bookings"].values()
        if b["class_id"] == c["id"] and b["status"] == "WAITLISTED"
    )
    return {
        **_common(c),
        "class_code": c["class_code"],
        "instructor_trainer_id": c["instructor_trainer_id"],
        "substitute_trainer_id": c.get("substitute_trainer_id"),
        "starts_at": _iso(c.get("starts_at")),
        "ends_at": _iso(c.get("ends_at")),
        "capacity": c["capacity"],
        "recurrence_series_id": c.get("recurrence_series_id"),
        "deduction_cents": c.get("deduction_cents", 0),
        "status": c.get("status", "SCHEDULED"),
        "confirmed_count": confirmed_count,
        "waitlist_count": waitlist_count,
    }


def serialize_group_booking(b):
    return {
        **_common(b),
        "class_id": b["class_id"],
        "member_id": b["member_id"],
        "card_id": b.get("card_id"),
        "status": b.get("status", "CONFIRMED"),
        "waitlist_position": b.get("waitlist_position"),
        "waitlisted_at": _iso(b.get("waitlisted_at")),
    }


def serialize_wallet_transaction(w):
    return {
        **_append_only(w),
        "member_id": w["member_id"],
        "kind": w["kind"],
        "amount_cents": w["amount_cents"],
        "bucket": w["bucket"],
        "service_type": w.get("service_type"),
        "ref_entity": w.get("ref_entity"),
        "expires_at": _iso(w.get("expires_at")),
    }


def serialize_freeze_episode(f):
    return {
        **_common(f),
        "card_id": f["card_id"],
        "reason": f["reason"],
        "requested_days": f["requested_days"],
        "actual_days": f.get("actual_days", 0),
        "starts_at": _iso(f.get("starts_at")),
        "ends_at": _iso(f.get("ends_at")),
        "status": f.get("status", "REQUESTED"),
    }


def serialize_transfer_record(t):
    return {
        **_append_only(t),
        "source_card_id": t["source_card_id"],
        "destination_card_id": t["destination_card_id"],
        "from_member_id": t["from_member_id"],
        "to_member_id": t["to_member_id"],
        "remaining_value_cents": t["remaining_value_cents"],
        "transfer_fee_cents": t["transfer_fee_cents"],
    }


def serialize_commission_record(r):
    return {
        **_append_only(r),
        "trainer_id": r["trainer_id"],
        "kind": r["kind"],
        "amount_cents": r["amount_cents"],
        "ref_entity": r.get("ref_entity"),
        "payout_cycle_id": r.get("payout_cycle_id"),
    }


def serialize_payout_cycle(p):
    return {
        **_append_only(p),
        "cycle_start": _iso(p["cycle_start"]),
        "cycle_end": _iso(p["cycle_end"]),
        "closed_at": _iso(p.get("closed_at")),
        "status": p.get("status", "OPEN"),
    }


def serialize_renewal_reminder(r):
    return {
        **_append_only(r),
        "card_id": r["card_id"],
        "tier": r["tier"],
        "channels_dispatched": list(r.get("channels_dispatched", [])),
        "status": r.get("status"),
    }


def serialize_audit_log(a):
    return {
        **_append_only(a),
        "actor_role": a["actor_role"],
        "actor_id": a["actor_id"],
        "action": a["action"],
        "target_entity": a.get("target_entity"),
        "payload": a.get("payload", {}),
    }
