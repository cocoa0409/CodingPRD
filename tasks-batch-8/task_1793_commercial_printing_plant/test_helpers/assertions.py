"""Entity assertions and domain invariant checkers.

Every checker validates the common resource properties (PRD §2.4) plus the
entity-specific shape described in the PRD prose.
"""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common(data: dict, entity: str):
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"{entity}.created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), f"{entity}.updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity}.version must be an integer >= 1, got {data.get('version')!r}"
    )


def assert_customer(data: dict):
    _assert_common(data, "Customer")
    assert isinstance(data.get("name"), str) and len(data["name"]) > 0
    assert isinstance(data.get("credit_limit_cents"), int) and data["credit_limit_cents"] >= 0
    assert isinstance(data.get("default_tolerance_pct"), int)
    assert isinstance(data.get("exposure_cents"), int) and data["exposure_cents"] >= 0
    assert data.get("posture") in ("ACTIVE", "CREDIT_HOLD"), f"bad posture {data.get('posture')!r}"
    assert isinstance(data.get("reprint_credit_balance_cents"), int)


def assert_estimate(data: dict):
    _assert_common(data, "Estimate")
    assert is_valid_uuid(data.get("customer_id", "")), "Estimate.customer_id must be a UUID"
    assert isinstance(data.get("job_name"), str)
    assert isinstance(data.get("quantity_ordered"), int) and data["quantity_ordered"] >= 1
    assert data.get("press_type") in ("WEB", "SHEETFED")
    assert data.get("binding_method") in ("SADDLE_STITCH", "PERFECT_BIND", "CASE_BIND", "PLASTIC_COIL")
    assert data.get("fulfillment_type") in ("SHIP", "MAIL")
    assert isinstance(data.get("signatures"), list) and len(data["signatures"]) >= 1
    assert isinstance(data.get("finishing_options"), list)
    assert isinstance(data.get("impressions_per_signature"), list)
    assert isinstance(data.get("total_impressions"), int)
    assert isinstance(data.get("make_ready_total_cents"), int)
    assert isinstance(data.get("running_cost_cents"), int)
    assert isinstance(data.get("paper_sheets_total"), int)
    assert isinstance(data.get("paper_cost_cents"), int)
    assert isinstance(data.get("finishing_cost_cents"), int)
    assert isinstance(data.get("subtotal_cents"), int)
    assert data.get("discount_pct") in (0, 3, 5), f"bad discount_pct {data.get('discount_pct')!r}"
    assert isinstance(data.get("total_price_cents"), int)
    assert data.get("status") in ("DRAFT", "QUOTED", "ACCEPTED", "DECLINED", "EXPIRED")


def assert_job(data: dict):
    _assert_common(data, "Job")
    assert is_valid_uuid(data.get("customer_id", "")), "Job.customer_id must be a UUID"
    assert isinstance(data.get("quantity_ordered"), int) and data["quantity_ordered"] >= 1
    assert data.get("press_type") in ("WEB", "SHEETFED")
    assert data.get("fulfillment_type") in ("SHIP", "MAIL")
    assert data.get("production_status") in (
        "PREPRESS", "PROOF_REVIEW", "PLATED", "PRESS_SCHEDULED",
        "BINDERY", "READY_TO_SHIP", "FULFILLED", "CLOSED", "CANCELLED",
    ), f"bad production_status {data.get('production_status')!r}"
    assert data.get("billing_status") in ("UNBILLED", "INVOICED", "SETTLED", "NOT_BILLABLE"), (
        f"bad billing_status {data.get('billing_status')!r}"
    )
    assert isinstance(data.get("zero_charge"), bool)
    assert isinstance(data.get("total_price_cents"), int)
    assert isinstance(data.get("make_ready_total_cents"), int)
    assert isinstance(data.get("tolerance_pct"), int)
    assert isinstance(data.get("proof_rounds_used"), int)


def assert_proof(data: dict):
    _assert_common(data, "Proof")
    assert is_valid_uuid(data.get("job_id", "")), "Proof.job_id must be a UUID"
    assert isinstance(data.get("round_number"), int) and data["round_number"] >= 1
    assert data.get("status") in ("AWAITING_CUSTOMER", "CHANGES_REQUESTED", "APPROVED", "SUPERSEDED")


def assert_paper_stock(data: dict):
    _assert_common(data, "PaperStock")
    assert isinstance(data.get("name"), str) and len(data["name"]) > 0
    assert data.get("grade") in ("COATED", "UNCOATED", "NEWSPRINT")
    assert isinstance(data.get("cost_per_sheet_cents"), int) and data["cost_per_sheet_cents"] >= 0
    assert isinstance(data.get("reorder_threshold_sheets"), int)
    assert isinstance(data.get("reorder_quantity_sheets"), int)
    assert isinstance(data.get("available_sheets"), int)


def assert_paper_purchase_order(data: dict):
    _assert_common(data, "PaperPurchaseOrder")
    assert is_valid_uuid(data.get("paper_stock_id", ""))
    assert isinstance(data.get("ordered_sheets"), int) and data["ordered_sheets"] >= 1
    assert isinstance(data.get("received_sheets_total"), int)
    assert data.get("source") in ("MANUAL", "AUTO_REPLENISH")
    assert data.get("status") in ("ORDERED", "PARTIALLY_RECEIVED", "RECEIVED", "CANCELLED")


def assert_paper_lot(data: dict):
    _assert_common(data, "PaperLot")
    assert is_valid_uuid(data.get("paper_stock_id", ""))
    assert is_valid_uuid(data.get("paper_purchase_order_id", ""))
    for f in ("received_sheets", "damaged_sheets", "reserved_sheets", "consumed_sheets", "remaining_sheets"):
        assert isinstance(data.get(f), int), f"PaperLot.{f} must be int"
    # Conservation invariant: remaining == received - reserved - consumed - damaged
    assert data["remaining_sheets"] == (
        data["received_sheets"] - data["reserved_sheets"]
        - data["consumed_sheets"] - data["damaged_sheets"]
    ), "PaperLot conservation invariant violated"


def assert_press(data: dict):
    _assert_common(data, "Press")
    assert isinstance(data.get("name"), str) and len(data["name"]) > 0
    assert data.get("press_type") in ("WEB", "SHEETFED")
    assert isinstance(data.get("rated_impressions_per_hour"), int) and data["rated_impressions_per_hour"] >= 1
    assert isinstance(data.get("make_ready_minutes_base"), int)
    assert isinstance(data.get("washup_buffer_minutes"), int)
    assert data.get("status") in ("AVAILABLE", "DOWN")


def assert_press_run(data: dict):
    _assert_common(data, "PressRun")
    assert is_valid_uuid(data.get("press_id", ""))
    assert isinstance(data.get("run_quantity"), int) and data["run_quantity"] >= 1
    assert is_iso8601_timestamp(data.get("scheduled_start", ""))
    assert isinstance(data.get("planned_impressions"), int)
    assert isinstance(data.get("planned_sheets"), int)
    assert isinstance(data.get("duration_minutes"), int)
    assert is_iso8601_timestamp(data.get("scheduled_end", ""))
    assert data.get("status") in ("SCHEDULED", "COMPLETE", "CANCELLED")


def assert_gang_run(data: dict):
    _assert_common(data, "GangRun")
    assert is_valid_uuid(data.get("paper_stock_id", ""))
    assert data.get("press_type") in ("WEB", "SHEETFED")
    assert isinstance(data.get("members"), list)
    assert data.get("status") in ("FORMING", "LOCKED", "CONSUMED")


def assert_bindery_ticket(data: dict):
    _assert_common(data, "BinderyTicket")
    assert is_valid_uuid(data.get("job_id", ""))
    assert data.get("operation") in (
        "FOLD", "STITCH", "TRIM", "PERF", "SCORE", "UV_COAT",
        "LAMINATE", "FOIL", "DIE_CUT", "COLLATE", "PAD",
    )
    assert isinstance(data.get("sequence_no"), int) and data["sequence_no"] >= 1
    assert data.get("status") in ("QUEUED", "COMPLETE")


def assert_mail_drop(data: dict):
    _assert_common(data, "MailDrop")
    assert is_valid_uuid(data.get("job_id", ""))
    assert data.get("destination_entry") in ("NONE", "BMC", "SCF", "DDU")
    assert isinstance(data.get("zip_counts"), list) and len(data["zip_counts"]) >= 1
    assert isinstance(data.get("total_pieces"), int) and data["total_pieces"] >= 1
    assert data.get("status") in ("PLANNED", "PRESORTED", "DROPPED")


def assert_invoice(data: dict):
    _assert_common(data, "Invoice")
    assert is_valid_uuid(data.get("job_id", ""))
    assert is_valid_uuid(data.get("customer_id", ""))
    assert data.get("kind") in ("PRODUCTION", "CANCELLATION_FEE")
    for f in ("billable_quantity", "base_amount_cents", "postage_cents", "proof_overage_cents",
              "shortage_credit_cents", "total_due_cents", "amount_paid_cents",
              "credit_applied_cents", "amount_outstanding_cents"):
        assert isinstance(data.get(f), int), f"Invoice.{f} must be int, got {data.get(f)!r}"
    assert data.get("status") in ("DRAFT", "ISSUED", "PARTIALLY_PAID", "PAID", "DISPUTED")


def assert_reprint_claim(data: dict):
    _assert_common(data, "ReprintClaim")
    assert is_valid_uuid(data.get("job_id", ""))
    assert data.get("claimed_defect") in (
        "MISREGISTER", "COLOR_SHIFT", "TRIM_ERROR",
        "BINDING_DEFECT", "PAPER_STOCK_WRONG", "SHORTAGE",
    )
    assert isinstance(data.get("defect_qty"), int) and data["defect_qty"] >= 1
    assert data.get("status") in ("FILED", "UNDER_REVIEW", "APPROVED", "DENIED")


def assert_invoice_monetary_conservation(invoice: dict):
    """PRD: amount_outstanding_cents is a monetary conservation invariant:
    total_due_cents minus amount_paid_cents minus credit_applied_cents."""
    assert invoice["amount_outstanding_cents"] == (
        invoice["total_due_cents"] - invoice["amount_paid_cents"] - invoice["credit_applied_cents"]
    ), (
        f"Invoice conservation violated: {invoice['total_due_cents']} - {invoice['amount_paid_cents']}"
        f" - {invoice['credit_applied_cents']} != {invoice['amount_outstanding_cents']}"
    )
