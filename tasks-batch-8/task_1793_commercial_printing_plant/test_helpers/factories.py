"""Payload factories — one per entity, input fields only (PRD §4 inputs).

Defaults follow the standard scenario the design indices converge on:
single/two-signature WEB jobs on a 9c coated stock, 5% tolerance customer.
"""
from .constants import DUE_DATE_ISO, DROP_DATE, PRESS_IPH, PRESS_MR_MINUTES, PRESS_WASHUP_MINUTES


def create_customer_payload(**overrides) -> dict:
    defaults = {
        "name": "Test Customer",
        "credit_limit_cents": 100000000,
        "default_tolerance_pct": 5,
    }
    defaults.update(overrides)
    return defaults


def signature_payload(stock_id, name="S1", pages=8, up_count=1,
                      make_ready_cents=50000, rate_per_thousand_cents=30000):
    return {
        "name": name,
        "pages": pages,
        "up_count": up_count,
        "paper_stock_id": stock_id,
        "make_ready_cents": make_ready_cents,
        "rate_per_thousand_cents": rate_per_thousand_cents,
    }


def create_estimate_payload(customer_id, **overrides) -> dict:
    """Caller must inject signatures via overrides when a stock id is needed."""
    defaults = {
        "customer_id": customer_id,
        "job_name": "Test Job",
        "quantity_ordered": 1000,
        "press_type": "WEB",
        "binding_method": "SADDLE_STITCH",
        "fulfillment_type": "SHIP",
        "press_spoilage_pct": 0,
        "bindery_spoilage_pct": 0,
        "due_date": DUE_DATE_ISO,
    }
    defaults.update(overrides)
    return defaults


def create_proof_payload(job_id, **overrides) -> dict:
    defaults = {"job_id": job_id, "file_uri": "s3://proofs/p.pdf"}
    defaults.update(overrides)
    return defaults


def create_paper_stock_payload(**overrides) -> dict:
    defaults = {
        "name": "80# gloss text",
        "grade": "COATED",
        "cost_per_sheet_cents": 9,
        "reorder_threshold_sheets": 0,
        "reorder_quantity_sheets": 20000,
    }
    defaults.update(overrides)
    return defaults


def create_po_payload(paper_stock_id, **overrides) -> dict:
    defaults = {
        "paper_stock_id": paper_stock_id,
        "ordered_sheets": 5000,
        "cost_per_sheet_cents": 5,
    }
    defaults.update(overrides)
    return defaults


def receive_po_payload(sheets_received, **overrides) -> dict:
    defaults = {"sheets_received": sheets_received}
    defaults.update(overrides)
    return defaults


def create_press_payload(**overrides) -> dict:
    defaults = {
        "name": "W1",
        "press_type": "WEB",
        "rated_impressions_per_hour": PRESS_IPH,
        "make_ready_minutes_base": PRESS_MR_MINUTES,
        "washup_buffer_minutes": PRESS_WASHUP_MINUTES,
    }
    defaults.update(overrides)
    return defaults


def create_press_run_payload(press_id, expected_press_version, **overrides) -> dict:
    defaults = {
        "press_id": press_id,
        "run_quantity": 1000,
        "scheduled_start": "2026-08-10T08:00:00Z",
        "expected_press_version": expected_press_version,
    }
    defaults.update(overrides)
    return defaults


def complete_press_run_payload(**overrides) -> dict:
    defaults = {"gross_impressions": 1000, "sheets_used": 1000, "waste_sheets": 0}
    defaults.update(overrides)
    return defaults


def create_gang_run_payload(paper_stock_id, **overrides) -> dict:
    defaults = {
        "paper_stock_id": paper_stock_id,
        "press_type": "WEB",
        "anchor_due_date": DUE_DATE_ISO,
    }
    defaults.update(overrides)
    return defaults


def gang_member_payload(job_id, expected_gang_run_version) -> dict:
    return {"job_id": job_id, "expected_gang_run_version": expected_gang_run_version}


def create_bindery_ticket_payload(job_id, **overrides) -> dict:
    defaults = {"job_id": job_id, "operation": "FOLD", "sequence_no": 1}
    defaults.update(overrides)
    return defaults


def create_mail_drop_payload(job_id, zip_counts=None, **overrides) -> dict:
    defaults = {
        "job_id": job_id,
        "drop_date": DROP_DATE,
        "destination_entry": "NONE",
        "piece_weight_oz": 2.0,
        "zip_counts": zip_counts if zip_counts is not None else [{"zip5": "94101", "pieces": 100}],
    }
    defaults.update(overrides)
    return defaults


def create_invoice_payload(job_id) -> dict:
    return {"job_id": job_id}


def payment_payload(amount_cents) -> dict:
    return {"amount_cents": amount_cents}


def dispute_payload(reason="quality") -> dict:
    return {"reason": reason}


def create_claim_payload(job_id, **overrides) -> dict:
    defaults = {"job_id": job_id, "claimed_defect": "SHORTAGE", "defect_qty": 1}
    defaults.update(overrides)
    return defaults


def approve_claim_payload(resolution="REPRINT", liability_pct=100) -> dict:
    return {"resolution": resolution, "liability_pct": liability_pct}


def deny_claim_payload(reason="not liable") -> dict:
    return {"reason": reason}


def set_clock_payload(to_iso8601) -> dict:
    return {"to_iso8601": to_iso8601}
