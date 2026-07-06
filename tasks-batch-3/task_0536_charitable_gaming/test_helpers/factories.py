"""Payload factories — one per input-bearing entity, input fields only.

Field names are PRD-exact. EIN values are generated with a monotonic counter so
multiple organizations created within a single test never collide on any field
(the PRD imposes no EIN-uniqueness rule, but distinct values keep intent clear).
"""
import itertools

_ein_counter = itertools.count(1)


def _next_ein() -> str:
    n = next(_ein_counter)
    return f"{n % 100:02d}-{n:07d}"


# ─── Organization (POST /organizations) ──────────────────────────────
def create_organization_payload(**overrides) -> dict:
    defaults = {
        "legal_name": "Test Charitable Org",
        "ein": _next_ein(),
        "nonprofit_type": "501C3",
        "incorporation_date": "2020-01-01T00:00:00Z",
        "good_standing": True,
        "state_code": "CA",
    }
    defaults.update(overrides)
    return defaults


# ─── License (POST /licenses) ─────────────────────────────────────────
def create_license_payload(organization_id: str, **overrides) -> dict:
    defaults = {
        "organization_id": organization_id,
        "license_type": "BINGO",
        "contact_email": "contact@x.org",
        "venue_name": "Main Hall",
    }
    defaults.update(overrides)
    return defaults


# ─── Occasion (POST /occasions) ───────────────────────────────────────
def create_occasion_payload(license_id: str, **overrides) -> dict:
    defaults = {
        "license_id": license_id,
        "occasion_type": "BINGO",
        "scheduled_start": "2026-06-01T18:00:00Z",
        "scheduled_end": "2026-06-01T22:00:00Z",
        "venue_name": "Main Hall",
        "planned_gross_cents": 200_000,
        "planned_prize_pool_cents": 50_000,
        "planned_expenses_cents": 20_000,
    }
    defaults.update(overrides)
    return defaults


# ─── Occasion report body (POST /occasions/{id}/report) ───────────────
def report_occasion_payload(**overrides) -> dict:
    defaults = {
        "gross_receipts_cents": 180_000,
        "prizes_paid_cents": 40_000,
        "expenses_cents": 25_000,
    }
    defaults.update(overrides)
    return defaults


# ─── Supplier (POST /suppliers) ───────────────────────────────────────
def create_supplier_payload(**overrides) -> dict:
    defaults = {
        "business_name": "Test GameCo",
        "state_code": "CA",
    }
    defaults.update(overrides)
    return defaults


# ─── Equipment (POST /equipment) ──────────────────────────────────────
def create_equipment_payload(supplier_id: str, **overrides) -> dict:
    defaults = {
        "supplier_id": supplier_id,
        "equipment_type": "BINGO_BLOWER",
        "serial_number": "SN-1",
    }
    defaults.update(overrides)
    return defaults


# ─── EquipmentAllocation (POST /equipment-allocations) ────────────────
def create_allocation_payload(equipment_id: str, occasion_id: str, **overrides) -> dict:
    defaults = {
        "equipment_id": equipment_id,
        "occasion_id": occasion_id,
        "start_date": "2026-06-01T00:00:00Z",
        "end_date": "2026-06-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


# ─── FinancialReport (POST /financial-reports) ────────────────────────
def create_financial_report_payload(license_id: str, **overrides) -> dict:
    defaults = {
        "license_id": license_id,
        "period_start": "2026-06-01T00:00:00Z",
        "period_end": "2026-06-30T23:59:59Z",
        "charitable_use_cents": 0,
    }
    defaults.update(overrides)
    return defaults


# ─── Violation (POST /violations) ─────────────────────────────────────
def create_violation_payload(license_id: str, **overrides) -> dict:
    defaults = {
        "license_id": license_id,
        "violation_type": "LATE_REPORT",
    }
    defaults.update(overrides)
    return defaults


# ─── Renewal (POST /renewals) ─────────────────────────────────────────
def create_renewal_payload(license_id: str, expected_license_version: int, **overrides) -> dict:
    defaults = {
        "license_id": license_id,
        "expected_license_version": expected_license_version,
    }
    defaults.update(overrides)
    return defaults
