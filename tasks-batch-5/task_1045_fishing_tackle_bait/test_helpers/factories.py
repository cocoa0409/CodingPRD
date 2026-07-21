"""Payload factories — one per entity, input fields only.

Each factory returns a dict of the caller-supplied input fields the PRD accepts
for a create/action call. Computed and system fields are never emitted.
"""
import itertools

_counter = itertools.count(1)


def unique_suffix() -> str:
    """Monotonic suffix so email/sku/code stay unique within a test's DB."""
    return str(next(_counter))


# ─── Customer ──────────────────────────────────────────────────
def create_customer_payload(**overrides) -> dict:
    n = unique_suffix()
    defaults = {
        "full_name": "Test Angler",
        "email": f"angler{n}@example.com",
        "date_of_birth": "1985-01-01",
        "residency_state": "CA",
    }
    defaults.update(overrides)
    return defaults


# ─── Product ───────────────────────────────────────────────────
def create_product_payload(**overrides) -> dict:
    n = unique_suffix()
    defaults = {
        "sku": f"SKU-{n}",
        "name": "Test Product",
        "category": "LINE",
        "unit_price_cents": 0,
        "stock_qty": 50,
    }
    defaults.update(overrides)
    return defaults


# ─── LicenseType ───────────────────────────────────────────────
def create_license_type_payload(**overrides) -> dict:
    n = unique_suffix()
    defaults = {
        "code": f"CA-LT-{n}",
        "state_code": "CA",
        "license_class": "RESIDENT",
        "base_price_cents": 3000,
        "min_age": 0,
        "season_start_date": "2026-01-01",
        "season_end_date": "2026-12-31",
        "validity_days": 365,
    }
    defaults.update(overrides)
    return defaults


# ─── LicenseSale ───────────────────────────────────────────────
def create_license_sale_payload(customer_id: str, license_type_id: str, **overrides) -> dict:
    defaults = {"customer_id": customer_id, "license_type_id": license_type_id}
    defaults.update(overrides)
    return defaults


# ─── Guide ─────────────────────────────────────────────────────
def create_guide_payload(**overrides) -> dict:
    n = unique_suffix()
    defaults = {"name": f"Captain {n}", "license_no": f"CAP-{n}"}
    defaults.update(overrides)
    return defaults


# ─── Charter ───────────────────────────────────────────────────
def create_charter_payload(guide_id: str, **overrides) -> dict:
    defaults = {
        "guide_id": guide_id,
        "title": "Test Charter",
        "start_at": "2026-08-01T09:00:00Z",
        "end_at": "2026-08-01T12:00:00Z",
        "capacity": 4,
        "price_per_seat_cents": 10000,
    }
    defaults.update(overrides)
    return defaults


# ─── CharterBooking ────────────────────────────────────────────
def create_booking_payload(charter_id: str, customer_id: str, **overrides) -> dict:
    defaults = {"charter_id": charter_id, "customer_id": customer_id, "seats": 1}
    defaults.update(overrides)
    return defaults


# ─── Tournament ────────────────────────────────────────────────
def create_tournament_payload(**overrides) -> dict:
    n = unique_suffix()
    defaults = {
        "name": f"Tournament {n}",
        "species": "BASS",
        "start_at": "2026-07-20T06:00:00Z",
        "end_at": "2026-07-20T18:00:00Z",
        "min_qualifying_weight_grams": 1000,
    }
    defaults.update(overrides)
    return defaults


# ─── TournamentEntry ───────────────────────────────────────────
def create_entry_payload(tournament_id: str, customer_id: str, **overrides) -> dict:
    defaults = {"tournament_id": tournament_id, "customer_id": customer_id}
    defaults.update(overrides)
    return defaults


# ─── ServiceOrder ──────────────────────────────────────────────
def create_service_order_payload(customer_id: str, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "service_type": "SPOOLING",
        "base_service_cents": 2500,
    }
    defaults.update(overrides)
    return defaults
