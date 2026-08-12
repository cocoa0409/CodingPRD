"""Payload factories — one per creatable entity, input fields only (PRD §3)."""
import itertools

_COUNTER = itertools.count(1)


def _seq() -> int:
    return next(_COUNTER)


def create_donor_payload(**overrides) -> dict:
    n = _seq()
    defaults = {
        "full_name": f"Donor {n}",
        "donor_type": "INDIVIDUAL",
        "email": f"donor{n}@example.org",
        "address_text": f"{n} Reuse Way",
    }
    defaults.update(overrides)
    return defaults


def create_category_payload(**overrides) -> dict:
    n = _seq()
    defaults = {
        "code": f"CAT{n:04d}",
        "display_name": f"Category {n}",
        "pricing_model": "PER_UNIT",
        "base_rate_cents": 100,
        "hazmat_risk_flag": False,
        "markdown_after_days": 30,
        "markdown_step_pct": 0.20,
        "markdown_interval_days": 15,
        "max_markdown_steps": 2,
        "floor_price_pct": 0.40,
        "target_turn_days": 45,
    }
    defaults.update(overrides)
    return defaults


def create_donation_offer_payload(donor_id: str, category_id: str, **overrides) -> dict:
    n = _seq()
    defaults = {
        "donor_id": donor_id,
        "source_type": "DROPOFF",
        "category_id": category_id,
        "description_text": f"Offered materials {n}",
        "estimated_quantity": 1,
        "quantity_unit": "UNIT",
        "condition_grade": "A",
        "pre_1978_flag": False,
    }
    defaults.update(overrides)
    return defaults


def create_deconstruction_job_payload(**overrides) -> dict:
    n = _seq()
    defaults = {
        "title": f"Job {n}",
        "site_address_text": f"{n} Site Rd",
        "quoted_fee_cents": 100000,
    }
    defaults.update(overrides)
    return defaults


def create_hazmat_screening_payload(job_id: str, **overrides) -> dict:
    defaults = {
        "job_id": job_id,
        "lead_result": "NEGATIVE",
        "asbestos_result": "NEGATIVE",
    }
    defaults.update(overrides)
    return defaults


def create_salvage_batch_payload(job_id: str, category_id: str, **overrides) -> dict:
    defaults = {
        "job_id": job_id,
        "category_id": category_id,
        "estimated_weight_lbs": 500,
    }
    defaults.update(overrides)
    return defaults


def create_item_payload(category_id: str, **overrides) -> dict:
    n = _seq()
    defaults = {
        "category_id": category_id,
        "description_text": f"Item {n}",
        "condition_grade": "A",
        "measure_qty": 1,
        "measure_unit": "UNIT",
        "pre_1978_flag": False,
        "estimated_weight_lbs": 10,
    }
    defaults.update(overrides)
    return defaults


def create_store_zone_payload(**overrides) -> dict:
    n = _seq()
    defaults = {
        "code": f"Z{n:04d}",
        "display_name": f"Zone {n}",
        "capacity": 10,
        "restock_threshold": 0,
    }
    defaults.update(overrides)
    return defaults


def create_contractor_account_payload(**overrides) -> dict:
    n = _seq()
    defaults = {
        "company_name": f"Contractor {n} LLC",
        "contact_email": f"contractor{n}@example.org",
        "credit_limit_cents": 100000000,
    }
    defaults.update(overrides)
    return defaults


def create_bulk_agreement_payload(contractor_id: str, category_id: str,
                                  expected_account_version: int, **overrides) -> dict:
    defaults = {
        "contractor_id": contractor_id,
        "category_id": category_id,
        "discount_pct": 0.10,
        "min_quantity": 1.0,
        "quantity_unit": "UNIT",
        "valid_from": "2026-01-01T00:00:00Z",
        "valid_until": "2027-01-01T00:00:00Z",
        "expected_account_version": expected_account_version,
    }
    defaults.update(overrides)
    return defaults


def create_sale_payload(**overrides) -> dict:
    defaults = {"sale_channel": "WALK_IN"}
    defaults.update(overrides)
    return defaults


def create_crew_member_payload(**overrides) -> dict:
    n = _seq()
    defaults = {
        "full_name": f"Crew Member {n}",
        "crew_type": "PAID",
        "hourly_rate_cents": 4000,
    }
    defaults.update(overrides)
    return defaults


def create_crew_assignment_payload(job_id: str, crew_member_id: str,
                                   start_at: str, end_at: str, **overrides) -> dict:
    defaults = {
        "job_id": job_id,
        "crew_member_id": crew_member_id,
        "role_on_job": "WORKER",
        "start_at": start_at,
        "end_at": end_at,
    }
    defaults.update(overrides)
    return defaults


def create_vehicle_payload(**overrides) -> dict:
    n = _seq()
    defaults = {
        "plate_code": f"TRK-{n:04d}",
        "capacity_lbs": 9000,
    }
    defaults.update(overrides)
    return defaults


def create_pickup_appointment_payload(subject_type: str, subject_id: str, vehicle_id: str,
                                      window_start: str, window_end: str, **overrides) -> dict:
    defaults = {
        "subject_type": subject_type,
        "subject_id": subject_id,
        "vehicle_id": vehicle_id,
        "window_start": window_start,
        "window_end": window_end,
    }
    defaults.update(overrides)
    return defaults


def create_diversion_report_payload(period: str, **overrides) -> dict:
    defaults = {"period": period}
    defaults.update(overrides)
    return defaults


def create_tax_receipt_payload(offer_id: str, **overrides) -> dict:
    defaults = {"offer_id": offer_id}
    defaults.update(overrides)
    return defaults
