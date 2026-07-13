"""Payload factories — one per entity, input (client-supplied) fields only."""
import uuid


def unique_email(prefix: str = "member") -> str:
    """A per-call unique email (members require a unique email)."""
    return f"{prefix}-{uuid.uuid4().hex[:12]}@x.com"


def create_member_payload(email=None, full_name="Test Member", promo_opt_in=None, **overrides) -> dict:
    payload = {"email": email or unique_email(), "full_name": full_name}
    if promo_opt_in is not None:
        payload["promo_opt_in"] = promo_opt_in
    payload.update(overrides)
    return payload


def create_attraction_payload(name="Racer", chip_cost_cents=100, points_award=10, **overrides) -> dict:
    payload = {"name": name, "chip_cost_cents": chip_cost_cents, "points_award": points_award}
    payload.update(overrides)
    return payload


def create_prize_item_payload(name="Teddy", points_price=500, stock_qty=100, **overrides) -> dict:
    payload = {"name": name, "points_price": points_price, "stock_qty": stock_qty}
    payload.update(overrides)
    return payload


def create_party_package_payload(name="Gold", base_price_cents=20_000, included_guests=10,
                                 included_hours=2, included_chip_cents=1_000, tier="GOLD",
                                 combo_name="Pizza Combo", combo_value_cents=3_000, **overrides) -> dict:
    payload = {
        "name": name,
        "base_price_cents": base_price_cents,
        "included_guests": included_guests,
        "included_hours": included_hours,
        "included_chip_cents": included_chip_cents,
        "tier": tier,
        "combo_name": combo_name,
        "combo_value_cents": combo_value_cents,
    }
    payload.update(overrides)
    return payload


def create_room_payload(name="Room A", capacity=20, hourly_rate_cents=8_000, **overrides) -> dict:
    payload = {"name": name, "capacity": capacity, "hourly_rate_cents": hourly_rate_cents}
    payload.update(overrides)
    return payload


def create_game_card_payload(owner_member_id=None, **overrides) -> dict:
    payload = {}
    if owner_member_id is not None:
        payload["owner_member_id"] = owner_member_id
    payload.update(overrides)
    return payload


def reload_payload(amount_cents, promo_code=None, **overrides) -> dict:
    payload = {"amount_cents": amount_cents}
    if promo_code is not None:
        payload["promo_code"] = promo_code
    payload.update(overrides)
    return payload


def game_play_payload(card_id, attraction_id, **overrides) -> dict:
    payload = {"card_id": card_id, "attraction_id": attraction_id}
    payload.update(overrides)
    return payload


def redemption_payload(card_id, prize_item_id, quantity, expected_card_version, **overrides) -> dict:
    payload = {
        "card_id": card_id,
        "prize_item_id": prize_item_id,
        "quantity": quantity,
        "expected_card_version": expected_card_version,
    }
    payload.update(overrides)
    return payload


def create_party_booking_payload(room_id, package_id, host_member_id, start_at, end_at,
                                 guest_count, **overrides) -> dict:
    payload = {
        "room_id": room_id,
        "package_id": package_id,
        "host_member_id": host_member_id,
        "start_at": start_at,
        "end_at": end_at,
        "guest_count": guest_count,
    }
    payload.update(overrides)
    return payload


def issue_wristband_payload(expected_booking_version, card_id=None, **overrides) -> dict:
    payload = {"expected_booking_version": expected_booking_version}
    if card_id is not None:
        payload["card_id"] = card_id
    payload.update(overrides)
    return payload


def create_reconciliation_payload(business_day, **overrides) -> dict:
    payload = {"business_day": business_day}
    payload.update(overrides)
    return payload


def count_reconciliation_payload(counted_chip_liability_cents, counted_prize_units, **overrides) -> dict:
    payload = {
        "counted_chip_liability_cents": counted_chip_liability_cents,
        "counted_prize_units": counted_prize_units,
    }
    payload.update(overrides)
    return payload
