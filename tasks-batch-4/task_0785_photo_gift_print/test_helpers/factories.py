"""Payload factories — one per entity, input fields only.

Each factory returns a dict of required + defaulted input fields; pass overrides
to change any value. Optional fields (line2, min_dpi, promo_codes, product_type_scope)
are only included when explicitly supplied.
"""


def create_customer_payload(**overrides) -> dict:
    defaults = {"email": "c@x.com", "full_name": "C"}
    defaults.update(overrides)
    return defaults


def create_address_payload(**overrides) -> dict:
    defaults = {
        "recipient_name": "C",
        "line1": "1 A St",
        "city": "SF",
        "region": "CA",
        "postal_code": "94101",
        "country": "US",
    }
    defaults.update(overrides)
    return defaults


def create_credit_adjustment_payload(amount_cents: int, reason: str = "seed", **overrides) -> dict:
    defaults = {"amount_cents": amount_cents, "reason": reason}
    defaults.update(overrides)
    return defaults


def create_template_payload(**overrides) -> dict:
    defaults = {
        "product_type": "PHOTOBOOK",
        "name": "Book",
        "surface_count": 20,
        "base_unit_price_cents": 1000,
        "production_days": 3,
        "allowed_finishes": ["MATTE"],
        "min_photos": 2,
        "max_photos": 50,
    }
    defaults.update(overrides)
    return defaults


def create_project_payload(customer_id: str, template_id: str, title: str = "P", **overrides) -> dict:
    defaults = {"customer_id": customer_id, "template_id": template_id, "title": title}
    defaults.update(overrides)
    return defaults


def create_photo_payload(**overrides) -> dict:
    defaults = {"filename": "a.jpg", "width_px": 3000, "height_px": 2000, "dpi": 300}
    defaults.update(overrides)
    return defaults


def create_promotion_payload(code: str, kind: str, value: int = 0, **overrides) -> dict:
    defaults = {
        "code": code,
        "kind": kind,
        "value": value,
        "min_subtotal_cents": 0,
        "stackable": True,
        "per_customer_limit": 5,
    }
    defaults.update(overrides)
    return defaults


def create_promo_window_payload(starts_at: str, ends_at: str, **overrides) -> dict:
    defaults = {"starts_at": starts_at, "ends_at": ends_at}
    defaults.update(overrides)
    return defaults


def create_surge_window_payload(**overrides) -> dict:
    defaults = {
        "name": "W",
        "starts_at": "2026-06-01T00:00:00Z",
        "ends_at": "2026-06-10T00:00:00Z",
        "turnaround_extra_days": 2,
        "capacity_per_day": 100,
    }
    defaults.update(overrides)
    return defaults


def create_order_payload(project_id: str, ship_address_id: str, **overrides) -> dict:
    defaults = {
        "project_id": project_id,
        "quantity": 5,
        "finish": "MATTE",
        "ship_method": "STANDARD",
        "ship_address_id": ship_address_id,
        "payment_method": "CARD",
    }
    defaults.update(overrides)
    return defaults


def create_quote_payload(**overrides) -> dict:
    defaults = {"quantity": 5, "finish": "MATTE", "ship_method": "STANDARD"}
    defaults.update(overrides)
    return defaults


def create_shipment_payload(address_id: str, **overrides) -> dict:
    defaults = {"address_id": address_id, "carrier": "UPS", "method": "STANDARD"}
    defaults.update(overrides)
    return defaults


def create_cancel_payload(refund_destination: str, **overrides) -> dict:
    defaults = {"refund_destination": refund_destination}
    defaults.update(overrides)
    return defaults


def create_clock_payload(to_iso8601: str) -> dict:
    return {"to_iso8601": to_iso8601}
