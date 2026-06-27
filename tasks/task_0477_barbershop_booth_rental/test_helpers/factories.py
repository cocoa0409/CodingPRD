"""Payload factories — one per entity, input fields only.

Required inputs (no default, no source: system/computed) are always present;
optional inputs are added only when overridden.
"""

DEFAULTS = {
    "SHOP_NAME": "Test Shop",
    "BARBER_NAME": "Test Barber",
    "CUSTOMER_NAME": "Test Customer",
    "LICENSE_NUMBER": "L-0001",
    "LICENSE_EXPIRES_ON": "2027-01-01",
}


def create_shop_payload(**overrides) -> dict:
    """Required: name, tax_rate_pct, default_booth_rent_cents, default_commission_pct.
    Optional config fields fall back to PRD defaults when omitted."""
    defaults = {
        "name": DEFAULTS["SHOP_NAME"],
        "tax_rate_pct": 0,
        "default_booth_rent_cents": 0,
        "default_commission_pct": 0,
    }
    defaults.update(overrides)
    return defaults


def create_barber_payload(shop_id, comp_model="COMMISSION", **overrides) -> dict:
    """Required: shop_id, full_name, license_number, license_expires_on, comp_model."""
    defaults = {
        "shop_id": shop_id,
        "full_name": DEFAULTS["BARBER_NAME"],
        "license_number": DEFAULTS["LICENSE_NUMBER"],
        "license_expires_on": DEFAULTS["LICENSE_EXPIRES_ON"],
        "comp_model": comp_model,
    }
    defaults.update(overrides)
    return defaults


def create_chair_payload(shop_id, label="Chair 1", **overrides) -> dict:
    defaults = {"shop_id": shop_id, "label": label}
    defaults.update(overrides)
    return defaults


def create_shift_payload(shop_id, barber_id, chair_id, start_utc, end_utc,
                         expected_shop_version, **overrides) -> dict:
    defaults = {
        "shop_id": shop_id,
        "barber_id": barber_id,
        "chair_id": chair_id,
        "start_utc": start_utc,
        "end_utc": end_utc,
        "expected_shop_version": expected_shop_version,
    }
    defaults.update(overrides)
    return defaults


def create_service_payload(shop_id, name="Haircut", price_cents=3000,
                           duration_minutes=30, **overrides) -> dict:
    defaults = {
        "shop_id": shop_id,
        "name": name,
        "price_cents": price_cents,
        "duration_minutes": duration_minutes,
    }
    defaults.update(overrides)
    return defaults


def create_addon_payload(shop_id, name="Beard", price_cents=1500, **overrides) -> dict:
    defaults = {"shop_id": shop_id, "name": name, "price_cents": price_cents}
    defaults.update(overrides)
    return defaults


def create_product_payload(shop_id, name="Pomade", price_cents=1200, **overrides) -> dict:
    defaults = {"shop_id": shop_id, "name": name, "price_cents": price_cents}
    defaults.update(overrides)
    return defaults


def create_membership_payload(shop_id, name="Gold", monthly_fee_cents=4000,
                              **overrides) -> dict:
    defaults = {
        "shop_id": shop_id,
        "name": name,
        "monthly_fee_cents": monthly_fee_cents,
    }
    defaults.update(overrides)
    return defaults


_customer_seq = [0]


def create_customer_payload(shop_id, full_name=None, email=None, **overrides) -> dict:
    """email must be unique within the shop; auto-generate a unique one if absent."""
    _customer_seq[0] += 1
    defaults = {
        "shop_id": shop_id,
        "full_name": full_name or DEFAULTS["CUSTOMER_NAME"],
        "email": email or f"cust{_customer_seq[0]}@example.com",
    }
    defaults.update(overrides)
    return defaults


def create_appointment_payload(shop_id, customer_id, barber_id, chair_id,
                               service_item_id, start_utc, **overrides) -> dict:
    defaults = {
        "shop_id": shop_id,
        "customer_id": customer_id,
        "barber_id": barber_id,
        "chair_id": chair_id,
        "service_item_id": service_item_id,
        "start_utc": start_utc,
    }
    defaults.update(overrides)
    return defaults


def create_queue_payload(shop_id, customer_id, **overrides) -> dict:
    defaults = {"shop_id": shop_id, "customer_id": customer_id}
    defaults.update(overrides)
    return defaults


def set_lines_payload(**overrides) -> dict:
    """All fields optional on PUT /tickets/{id}/lines."""
    return dict(overrides)
