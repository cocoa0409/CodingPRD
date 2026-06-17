"""Payload factories — one per entity, input fields only."""
import itertools

_seq = itertools.count(1)


def _unique(prefix: str) -> str:
    return f"{prefix}-{next(_seq)}"


# ─── Registration records ─────────────────────────────────────────────────

def create_customer_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Test Homeowner",
        "address": "1 Test St",
        "email": _unique("customer") + "@x.com",
    }
    defaults.update(overrides)
    return defaults


def create_sales_rep_payload(**overrides) -> dict:
    defaults = {"name": "Test Rep"}
    defaults.update(overrides)
    return defaults


# ─── Catalog ──────────────────────────────────────────────────────────────

def create_product_payload(**overrides) -> dict:
    """LVP product requiring underlayment by default. Override category/costs as needed."""
    defaults = {
        "sku": _unique("SKU"),
        "name": "Test Product",
        "category": "LVP",
        "material_cost_per_sqft_cents": 300,
        "labor_rate_per_sqft_cents": 250,
        "requires_underlayment": True,
        "underlayment_cost_per_sqft_cents": 30,
        "lead_time_days": 0,
        "warranty_years": 10,
    }
    defaults.update(overrides)
    return defaults


# ─── Jobs ─────────────────────────────────────────────────────────────────

def create_job_payload(customer_id: str, sales_rep_id: str, product_id: str,
                       declared_sqft: float = 200, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "sales_rep_id": sales_rep_id,
        "product_id": product_id,
        "declared_sqft": declared_sqft,
    }
    defaults.update(overrides)
    return defaults


def measure_payload(measured_sqft: float = 200, tear_out_sqft: float = 0,
                    room_count: int = 1, **overrides) -> dict:
    defaults = {
        "measured_sqft": measured_sqft,
        "tear_out_sqft": tear_out_sqft,
        "room_count": room_count,
    }
    defaults.update(overrides)
    return defaults


# ─── Estimates ────────────────────────────────────────────────────────────

def create_estimate_payload(job_id: str, variant: str = "MEASURED",
                            valid_until: str = "2026-07-01T00:00:00.000Z", **overrides) -> dict:
    defaults = {
        "job_id": job_id,
        "variant": variant,
        "valid_until": valid_until,
    }
    defaults.update(overrides)
    return defaults


def issue_payload(expected_job_version: int, **overrides) -> dict:
    defaults = {"expected_job_version": expected_job_version}
    defaults.update(overrides)
    return defaults


# ─── Crews ────────────────────────────────────────────────────────────────

def create_install_crew_payload(skill_categories=None, daily_sqft_capacity: int = 5000,
                                buffer_minutes: int = 0, **overrides) -> dict:
    defaults = {
        "name": "Test Crew",
        "skill_categories": skill_categories if skill_categories is not None else ["CARPET"],
        "daily_sqft_capacity": daily_sqft_capacity,
        "buffer_minutes": buffer_minutes,
    }
    defaults.update(overrides)
    return defaults


# ─── Install slots ────────────────────────────────────────────────────────

def create_install_slot_payload(job_id: str, crew_id: str,
                                start_at: str = "2026-06-10T09:00:00.000Z",
                                end_at: str = "2026-06-10T15:00:00.000Z", **overrides) -> dict:
    defaults = {
        "job_id": job_id,
        "crew_id": crew_id,
        "start_at": start_at,
        "end_at": end_at,
    }
    defaults.update(overrides)
    return defaults


# ─── Warranty claims ──────────────────────────────────────────────────────

def create_warranty_claim_payload(job_id: str, defect_description: str = "defect", **overrides) -> dict:
    defaults = {
        "job_id": job_id,
        "defect_description": defect_description,
    }
    defaults.update(overrides)
    return defaults


def resolution_payload(resolution_note: str = "resolved", **overrides) -> dict:
    defaults = {"resolution_note": resolution_note}
    defaults.update(overrides)
    return defaults
