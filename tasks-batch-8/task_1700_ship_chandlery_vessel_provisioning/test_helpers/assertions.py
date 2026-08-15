"""Entity assertions and domain invariant checkers (PRD §2.4, §2.7, §3.9).

assert_<entity>(data) validates the common resource shape plus the fields the
PRD guarantees on the response. Domain invariant checkers (money conservation
on invoices, stock conservation on lots) are shared by several tests.
"""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


# ---------------------------------------------------------------------------
# Common shape helpers
# ---------------------------------------------------------------------------

def _assert_common_fields(data: dict, entity_label: str):
    """PRD §2.4: id (UUID) + created_at + updated_at + integer version."""
    assert is_valid_uuid(data.get("id", "")), f"{entity_label}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity_label}.created_at must be an ISO 8601 timestamp"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity_label}.updated_at must be an ISO 8601 timestamp"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity_label}.version must be an integer starting at 1"
    )


# ---------------------------------------------------------------------------
# Per-entity assertions
# ---------------------------------------------------------------------------

def assert_ship_agent(data: dict):
    _assert_common_fields(data, "ShipAgent")
    assert isinstance(data["name"], str) and data["name"]
    assert data["settlement_currency"] in ["USD", "EUR", "GBP", "SGD"]
    assert isinstance(data["credit_limit_cents"], int) and data["credit_limit_cents"] >= 0
    assert isinstance(data["payment_terms_days"], int) and data["payment_terms_days"] >= 0
    assert isinstance(data["committed_exposure_cents"], int)
    assert isinstance(data["settled_exposure_cents"], int)


def assert_vessel_call(data: dict):
    _assert_common_fields(data, "VesselCall")
    assert isinstance(data["vessel_name"], str) and data["vessel_name"]
    assert isinstance(data["imo_number"], str) and data["imo_number"]
    assert is_valid_uuid(data.get("agent_id", "")), "VesselCall.agent_id must be a UUID"
    assert isinstance(data["port_code"], str) and data["port_code"]
    assert is_iso8601_timestamp(data["scheduled_eta"])
    assert is_iso8601_timestamp(data["scheduled_etd"])
    assert isinstance(data["foreign_going"], bool)
    assert data["status"] in ["SCHEDULED", "IN_PORT", "DEPARTED", "CANCELLED"]
    assert data["customs_clearance_status"] in ["PENDING", "CLEARED", "REJECTED"]
    if data.get("actual_eta") is not None:
        assert is_iso8601_timestamp(data["actual_eta"])
    if data.get("actual_etd") is not None:
        assert is_iso8601_timestamp(data["actual_etd"])


def assert_catalog_item(data: dict):
    _assert_common_fields(data, "CatalogItem")
    assert isinstance(data["sku"], str) and data["sku"]
    assert isinstance(data["name"], str) and data["name"]
    assert data["category"] in ["PROVISIONS", "BONDED", "DECK", "ENGINE", "CABIN"]
    assert isinstance(data["bonded_eligible"], bool)
    assert isinstance(data["requires_cold_chain"], bool)
    assert isinstance(data["base_price_cents"], int) and data["base_price_cents"] >= 1
    assert data.get("duty_rate_pct", 0) >= 0


def assert_stock_lot(data: dict):
    _assert_common_fields(data, "StockLot")
    assert is_valid_uuid(data.get("catalog_item_id", "")), "StockLot.catalog_item_id must be a UUID"
    assert isinstance(data["lot_code"], str) and data["lot_code"]
    assert data["storage_tier"] in ["BONDED_WAREHOUSE", "COLD_STORE", "DRY_STORE"]
    assert isinstance(data["received_qty"], int) and data["received_qty"] >= 0
    assert isinstance(data["on_hand_qty"], int) and data["on_hand_qty"] >= 0
    assert isinstance(data["reserved_qty"], int) and data["reserved_qty"] >= 0
    assert isinstance(data["capacity_qty"], int) and data["capacity_qty"] >= 0


def assert_requisition(data: dict):
    _assert_common_fields(data, "Requisition")
    assert is_valid_uuid(data.get("vessel_call_id", "")), "Requisition.vessel_call_id must be a UUID"
    assert isinstance(data["title"], str)
    assert isinstance(data["lines"], list) and len(data["lines"]) >= 1
    assert data["status"] in ["DRAFT", "SUBMITTED", "QUOTED", "CLOSED"]
    if data.get("submitted_at") is not None:
        assert is_iso8601_timestamp(data["submitted_at"])


def assert_quotation(data: dict):
    _assert_common_fields(data, "Quotation")
    assert is_valid_uuid(data.get("requisition_id", "")), "Quotation.requisition_id must be a UUID"
    assert isinstance(data["lines"], list) and len(data["lines"]) >= 1
    assert is_iso8601_timestamp(data["valid_until"])
    assert isinstance(data["provisional_total_cents"], int)
    assert isinstance(data["revision_count"], int) and data["revision_count"] >= 0
    assert isinstance(data["authored_by_user_id"], str)
    assert data["status"] in ["DRAFT", "SENT", "ACCEPTED", "EXPIRED", "WITHDRAWN"]


def assert_order(data: dict):
    _assert_common_fields(data, "Order")
    assert is_valid_uuid(data.get("quotation_id", "")), "Order.quotation_id must be a UUID"
    assert is_valid_uuid(data.get("agent_id", "")), "Order.agent_id must be a UUID"
    assert isinstance(data["lines"], list) and len(data["lines"]) >= 1
    for line in data["lines"]:
        assert isinstance(line["qty_ordered"], int) and line["qty_ordered"] >= 1
        assert isinstance(line["qty_delivered"], int) and line["qty_delivered"] >= 0
        assert line["qty_delivered"] <= line["qty_ordered"]
        assert isinstance(line["unit_price_cents"], int)
        assert isinstance(line["allocations"], list)
    assert isinstance(data["subtotal_cents"], int)
    assert isinstance(data["rebate_cents"], int)
    assert isinstance(data["total_cents"], int)
    assert data["total_cents"] == data["subtotal_cents"] - data["rebate_cents"], (
        "Order total must equal subtotal minus rebate (PRD §3.4)"
    )
    assert is_iso8601_timestamp(data["accepted_at"])
    assert is_iso8601_timestamp(data["reservation_window_end"])
    assert data["fulfillment_status"] in [
        "OPEN", "PARTIALLY_DELIVERED", "DELIVERED", "CANCELLED",
    ]
    assert data["payment_status"] in [
        "UNINVOICED", "INVOICED", "PARTIALLY_PAID", "PAID", "CREDITED",
    ]


def assert_delivery(data: dict):
    _assert_common_fields(data, "Delivery")
    assert is_valid_uuid(data.get("order_id", "")), "Delivery.order_id must be a UUID"
    assert is_iso8601_timestamp(data["window_start"])
    assert is_iso8601_timestamp(data["window_end"])
    assert isinstance(data["lines"], list) and len(data["lines"]) >= 1
    assert data["status"] in [
        "SCHEDULED", "OUT_FOR_DELIVERY", "DELIVERED", "CANCELLED", "FAILED",
    ]
    assert isinstance(data.get("created_by_user_id"), str)
    if data.get("confirmed_at") is not None:
        assert is_iso8601_timestamp(data["confirmed_at"])


def assert_invoice(data: dict):
    _assert_common_fields(data, "Invoice")
    assert is_valid_uuid(data.get("order_id", "")), "Invoice.order_id must be a UUID"
    assert data["settlement_currency"] in ["USD", "EUR", "GBP", "SGD"]
    assert data["fx_rate_to_settlement"] > 0
    assert isinstance(data["lines"], list)
    for money_field in (
        "duty_free_subtotal_cents", "dutiable_subtotal_cents", "total_duty_cents",
        "subtotal_cents", "rebate_cents", "total_usd_cents", "total_cents",
        "paid_amount_cents", "credited_amount_cents", "fx_writeoff_cents",
        "outstanding_cents",
    ):
        assert isinstance(data[money_field], int), (
            f"Invoice.{money_field} must be integer cents"
        )
    assert data["status"] in ["ISSUED", "PARTIALLY_PAID", "PAID", "CREDITED", "VOID"]
    assert is_iso8601_timestamp(data["issued_at"])
    assert is_iso8601_timestamp(data["due_date"])
    assert_invoice_money_conservation(data)


def assert_payment(data: dict):
    """Payment is append-only (PRD §2.4): id + created_at, NO updated_at/version."""
    assert is_valid_uuid(data.get("id", "")), "Payment.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "Payment.created_at must be an ISO 8601 timestamp"
    )
    assert "version" not in data, "Payment must not carry a version field"
    assert "updated_at" not in data, "Payment must not carry an updated_at field"
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] >= 1
    assert data["currency"] in ["USD", "EUR", "GBP", "SGD"]
    assert isinstance(data["converted_amount_cents"], int)
    assert isinstance(data.get("writeoff_applied_cents", 0), int)
    assert isinstance(data.get("recorded_by_user_id"), str)


def assert_quality_complaint(data: dict):
    _assert_common_fields(data, "QualityComplaint")
    assert is_valid_uuid(data.get("delivery_id", "")), "QualityComplaint.delivery_id must be a UUID"
    assert isinstance(data["lines"], list) and len(data["lines"]) >= 1
    for line in data["lines"]:
        assert isinstance(line["rejected_qty"], int) and line["rejected_qty"] >= 1
        assert line["reason"] in ["SPOILED", "DAMAGED", "WRONG_ITEM", "SHORT"]
    assert isinstance(data["evidence_note"], str)
    assert isinstance(data["reopen_count"], int) and data["reopen_count"] >= 0
    assert data["status"] in ["SUBMITTED", "ACCEPTED", "REJECTED"]


def assert_credit_note(data: dict):
    _assert_common_fields(data, "CreditNote")
    assert is_valid_uuid(data.get("complaint_id", "")), "CreditNote.complaint_id must be a UUID"
    assert is_valid_uuid(data.get("invoice_id", "")), "CreditNote.invoice_id must be a UUID"
    assert isinstance(data["gross_amount_cents"], int)
    assert isinstance(data["restocking_fee_cents"], int)
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert data["status"] in ["APPLIED", "REVOKED"]


# ---------------------------------------------------------------------------
# Domain invariant checkers
# ---------------------------------------------------------------------------

def assert_invoice_money_conservation(invoice: dict):
    """PRD §3.9: paid + credited + write-off + outstanding == total, always."""
    lhs = (
        invoice["paid_amount_cents"]
        + invoice["credited_amount_cents"]
        + invoice["fx_writeoff_cents"]
        + invoice["outstanding_cents"]
    )
    assert lhs == invoice["total_cents"], (
        f"Invoice money conservation violated: "
        f"{invoice['paid_amount_cents']} paid + {invoice['credited_amount_cents']} credited "
        f"+ {invoice['fx_writeoff_cents']} writeoff + {invoice['outstanding_cents']} "
        f"outstanding != {invoice['total_cents']} total"
    )


def assert_stock_conservation(lot: dict):
    """PRD §3.2/§3.5: on_hand_qty + reserved_qty tracks received_qty."""
    assert lot["on_hand_qty"] >= 0 and lot["reserved_qty"] >= 0
    assert lot["on_hand_qty"] <= lot["received_qty"], (
        f"on_hand_qty {lot['on_hand_qty']} exceeds received_qty {lot['received_qty']}"
    )
