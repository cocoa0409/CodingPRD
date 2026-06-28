"""Entity constructors and serializers.

Records are plain dicts. Internal-only keys are prefixed with "_" and are
stripped from serialized output. Every mutable entity carries id, created_at,
updated_at, version. Attendee is the sole exception (id + created_at only).
"""
import db


def _base(common=True):
    rec = {
        "id": db.new_id(),
        "created_at": db.now_iso(),
        "_seq": db.next_seq(),
    }
    if common:
        rec["updated_at"] = rec["created_at"]
        rec["version"] = 1
    return rec


def touch(rec):
    """Bump updated_at + version on any mutation of a common-fields entity."""
    rec["updated_at"] = db.now_iso()
    rec["version"] = rec.get("version", 1) + 1


# ---- Constructors ----

def make_studio(name, room_capacity_seats, timezone_label):
    rec = _base()
    rec.update({
        "name": name,
        "room_capacity_seats": room_capacity_seats,
        "timezone": timezone_label,
        "status": "ACTIVE",
    })
    return rec


def make_artist(full_name, hourly_rate_cents):
    rec = _base()
    rec.update({
        "full_name": full_name,
        "hourly_rate_cents": hourly_rate_cents,
        "status": "ACTIVE",
    })
    return rec


def make_customer(email, full_name, birthdate_dt):
    rec = _base()
    rec.update({
        "email": email,
        "full_name": full_name,
        "_birthdate_dt": birthdate_dt,
        "credit_balance_cents": 0,
        "credit_redeemed_cents": 0,
    })
    return rec


def make_event(studio_id, title, event_type, start_dt, end_dt, seats_capacity,
               price_cents_per_seat, kit_fee_cents, byob_allowed, min_age,
               fundraiser_donation_pct):
    rec = _base()
    rec.update({
        "studio_id": studio_id,
        "title": title,
        "event_type": event_type,
        "_start_dt": start_dt,
        "_end_dt": end_dt,
        "seats_capacity": seats_capacity,
        "price_cents_per_seat": price_cents_per_seat,
        "kit_fee_cents": kit_fee_cents,
        "byob_allowed": byob_allowed,
        "min_age": min_age,
        "fundraiser_donation_pct": fundraiser_donation_pct,
        "status": "DRAFT",
        # Computed/derived fields (kept current by the seat ledger / donation calc).
        "seats_reserved": 0,
        "walk_in_seats": 0,
        "seats_available": seats_capacity,
        "pledged_donation_cents": 0,
        "settled_donation_cents": 0,
    })
    return rec


def make_assignment(event_id, artist_id):
    rec = _base()
    rec.update({
        "event_id": event_id,
        "artist_id": artist_id,
        "status": "ASSIGNED",
    })
    return rec


def make_kit_batch(event_id, sku, prepared_count):
    rec = _base()
    rec.update({
        "event_id": event_id,
        "sku": sku,
        "prepared_count": prepared_count,
        "consumed_count": 0,
    })
    return rec


def make_reservation(event_id, customer_id, booking_mode, seats, include_supply_kit):
    rec = _base()
    rec.update({
        "event_id": event_id,
        "customer_id": customer_id,
        "booking_mode": booking_mode,
        "seats": seats,
        "include_supply_kit": include_supply_kit,
        "status": "HELD",
        "payment_status": "UNPAID",
        "base_cents": 0,
        "group_discount_pct": 0,
        "kit_charge_cents": 0,
        "total_cents": 0,
        "amount_paid_cents": 0,
        "credit_granted_cents": 0,
        "cancelled_at_hours_before": None,
    })
    return rec


def make_attendee(reservation_id, full_name, age_years, waiver_signed):
    rec = _base(common=False)
    rec.update({
        "reservation_id": reservation_id,
        "full_name": full_name,
        "age_years": age_years,
        "waiver_signed": waiver_signed,
    })
    return rec


def make_walk_in(event_id, party_name, party_size, include_supply_kit):
    rec = _base()
    rec.update({
        "event_id": event_id,
        "party_name": party_name,
        "party_size": party_size,
        "include_supply_kit": include_supply_kit,
        "status": "REGISTERED",
    })
    return rec


def make_gift_card(code, issued_value_cents):
    rec = _base()
    rec.update({
        "code": code,
        "issued_value_cents": issued_value_cents,
        "balance_cents": issued_value_cents,
        "redeemed_cents": 0,
        "status": "ACTIVE",
    })
    return rec


def make_payment(reservation_id, method, gift_card_id, amount_cents):
    rec = _base()
    rec.update({
        "reservation_id": reservation_id,
        "method": method,
        "gift_card_id": gift_card_id,
        "amount_cents": amount_cents,
        "status": "SETTLED",
    })
    return rec


# ---- Serializers ----

def _public(rec, fields):
    return {k: rec.get(k) for k in fields}


from helpers import iso_from_dt  # noqa: E402

_COMMON = ["id", "created_at", "updated_at", "version"]


def serialize_studio(r):
    out = _public(r, _COMMON + ["name", "room_capacity_seats", "timezone", "status"])
    return out


def serialize_artist(r):
    return _public(r, _COMMON + ["full_name", "hourly_rate_cents", "status"])


def serialize_customer(r):
    out = _public(r, _COMMON + ["email", "full_name", "credit_balance_cents",
                                "credit_redeemed_cents"])
    out["birthdate"] = iso_from_dt(r.get("_birthdate_dt"))
    return out


def serialize_event(r):
    out = _public(r, _COMMON + [
        "studio_id", "title", "event_type", "seats_capacity",
        "price_cents_per_seat", "kit_fee_cents", "byob_allowed", "min_age",
        "fundraiser_donation_pct", "status", "seats_reserved", "walk_in_seats",
        "seats_available", "pledged_donation_cents", "settled_donation_cents",
    ])
    out["start_utc"] = iso_from_dt(r.get("_start_dt"))
    out["end_utc"] = iso_from_dt(r.get("_end_dt"))
    return out


def serialize_assignment(r):
    return _public(r, _COMMON + ["event_id", "artist_id", "status"])


def serialize_kit_batch(r):
    return _public(r, _COMMON + ["event_id", "sku", "prepared_count", "consumed_count"])


def serialize_reservation(r):
    return _public(r, _COMMON + [
        "event_id", "customer_id", "booking_mode", "seats", "include_supply_kit",
        "status", "payment_status", "base_cents", "group_discount_pct",
        "kit_charge_cents", "total_cents", "amount_paid_cents",
        "credit_granted_cents", "cancelled_at_hours_before",
    ])


def serialize_attendee(r):
    return _public(r, ["id", "created_at", "reservation_id", "full_name",
                       "age_years", "waiver_signed"])


def serialize_walk_in(r):
    return _public(r, _COMMON + ["event_id", "party_name", "party_size",
                                 "include_supply_kit", "status"])


def serialize_gift_card(r):
    return _public(r, _COMMON + ["code", "issued_value_cents", "balance_cents",
                                 "redeemed_cents", "status"])


def serialize_payment(r):
    return _public(r, _COMMON + ["reservation_id", "method", "gift_card_id",
                                 "amount_cents", "status"])
