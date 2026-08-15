"""Payload factories — one per writable resource, input fields only (PRD §3)."""
from .constants import STANDARD_CARD


def create_customer_payload(name="Test Co", credit_limit_cents=50_000, **overrides):
    payload = {"name": name, "credit_limit_cents": credit_limit_cents}
    payload.update(overrides)
    return payload


def create_rate_card_payload(customer_id, expected_customer_version, **overrides):
    """Full rate schedule; defaults are the standard card rates."""
    payload = dict(STANDARD_CARD)
    payload["customer_id"] = customer_id
    payload["expected_customer_version"] = expected_customer_version
    payload.update(overrides)
    return payload


def create_zone_payload(zone_code="FZ-1", temp_class="FROZEN", capacity_pallets=10,
                        dock_doors=2, **overrides):
    payload = {
        "zone_code": zone_code,
        "temp_class": temp_class,
        "capacity_pallets": capacity_pallets,
        "dock_doors": dock_doors,
    }
    payload.update(overrides)
    return payload


def create_receipt_payload(customer_id, zone_id, product_code="PEAS", lot_code="L1",
                           production_date="2026-01-15", temp_class="FROZEN",
                           expected_pallets=1, window_start="2026-08-02T08:00:00Z",
                           window_end="2026-08-02T10:00:00Z", **overrides):
    payload = {
        "customer_id": customer_id,
        "zone_id": zone_id,
        "product_code": product_code,
        "lot_code": lot_code,
        "production_date": production_date,
        "temp_class": temp_class,
        "expected_pallets": expected_pallets,
        "window_start": window_start,
        "window_end": window_end,
    }
    payload.update(overrides)
    return payload


def create_order_payload(customer_id, product_code="PEAS", requested_pallets=1,
                         lot_code=None, **overrides):
    payload = {
        "customer_id": customer_id,
        "product_code": product_code,
        "requested_pallets": requested_pallets,
    }
    if lot_code is not None:
        payload["lot_code"] = lot_code
    payload.update(overrides)
    return payload


def create_cell_payload(cell_code="BC-1", capacity_pallets=5, turnaround_minutes=30,
                        **overrides):
    payload = {
        "cell_code": cell_code,
        "capacity_pallets": capacity_pallets,
        "turnaround_minutes": turnaround_minutes,
    }
    payload.update(overrides)
    return payload


def create_booking_payload(cell_id, lot_id, pallet_count=1,
                           window_start="2026-08-05T10:00:00Z",
                           window_end="2026-08-05T12:00:00Z", **overrides):
    payload = {
        "cell_id": cell_id,
        "lot_id": lot_id,
        "pallet_count": pallet_count,
        "window_start": window_start,
        "window_end": window_end,
    }
    payload.update(overrides)
    return payload


def create_excursion_payload(zone_id, observed_temp_c=-2.0,
                             window_start="2026-08-03T00:00:00Z",
                             window_end="2026-08-04T00:00:00Z", **overrides):
    payload = {
        "zone_id": zone_id,
        "observed_temp_c": observed_temp_c,
        "window_start": window_start,
        "window_end": window_end,
    }
    payload.update(overrides)
    return payload


def create_recall_payload(customer_id, product_code="PEAS", lot_code="L1",
                          reason="quality hold", **overrides):
    payload = {
        "customer_id": customer_id,
        "product_code": product_code,
        "lot_code": lot_code,
        "reason": reason,
    }
    payload.update(overrides)
    return payload


def create_claim_payload(customer_id, excursion_id, affected_pallet_count=1,
                         declared_value_cents=10_000, **overrides):
    payload = {
        "customer_id": customer_id,
        "excursion_id": excursion_id,
        "affected_pallet_count": affected_pallet_count,
        "declared_value_cents": declared_value_cents,
    }
    payload.update(overrides)
    return payload
