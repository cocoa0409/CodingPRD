"""Payload factories — one per entity, input fields only."""
import uuid


def _unique_email(prefix: str = "u") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}@x.com"


def create_customer_payload(**overrides) -> dict:
    defaults = {
        "email": _unique_email("cust"),
        "full_name": "Test Customer",
        "phone": "555-0100",
    }
    defaults.update(overrides)
    return defaults


def create_designer_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Test Designer",
        "active": True,
    }
    defaults.update(overrides)
    return defaults


def create_paper_stock_payload(**overrides) -> dict:
    defaults = {
        "name": f"Test Paper {uuid.uuid4().hex[:6]}",
        "base_price_cents": 500,
        "lead_days": 7,
    }
    defaults.update(overrides)
    return defaults


def create_finish_option_payload(**overrides) -> dict:
    defaults = {
        "name": f"Test Finish {uuid.uuid4().hex[:6]}",
        "surcharge_cents": 100,
        "additional_lead_days": 5,
    }
    defaults.update(overrides)
    return defaults


def create_event_package_payload(**overrides) -> dict:
    defaults = {
        "name": "Wedding Suite Std",
        "package_type": "WEDDING",
        "deposit_pct": 0.5,
        "min_qty": 50,
        "proof_expiry_days": 14,
    }
    defaults.update(overrides)
    return defaults


def create_design_payload(customer_id: str, event_package_id: str,
                          paper_stock_id: str, finish_option_id: str, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "event_package_id": event_package_id,
        "paper_stock_id": paper_stock_id,
        "finish_option_id": finish_option_id,
    }
    defaults.update(overrides)
    return defaults


def create_order_payload(customer_id: str, design_id: str, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "design_id": design_id,
    }
    defaults.update(overrides)
    return defaults


def create_line_item_payload(paper_stock_id: str, finish_option_id: str,
                              quantity: int, expected_order_version: int, **overrides) -> dict:
    defaults = {
        "paper_stock_id": paper_stock_id,
        "finish_option_id": finish_option_id,
        "quantity": quantity,
        "expected_order_version": expected_order_version,
    }
    defaults.update(overrides)
    return defaults


def create_addressing_job_payload(job_type: str = "ADDRESSING", quantity: int = 150,
                                  scheduled_date: str = "2026-04-20",
                                  unit_price_cents: int = 200, **overrides) -> dict:
    defaults = {
        "job_type": job_type,
        "quantity": quantity,
        "scheduled_date": scheduled_date,
        "unit_price_cents": unit_price_cents,
    }
    defaults.update(overrides)
    return defaults


def create_initial_proof_payload(designer_id: str, **overrides) -> dict:
    defaults = {"designer_id": designer_id}
    defaults.update(overrides)
    return defaults
