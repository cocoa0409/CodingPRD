"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict, entity: str):
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"{entity}.created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), f"{entity}.updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), f"{entity}.version must be an integer"


def assert_payer_plan(data: dict):
    _assert_common(data, "PayerPlan")
    assert data["plan_type"] in ("MEDICARE_DMEPOS", "COMMERCIAL", "CASH_HSA")
    assert isinstance(data["coinsurance_pct"], (int, float))
    assert isinstance(data["cycle_months"], int)


def assert_formulary_item(data: dict):
    _assert_common(data, "FormularyItem")
    assert isinstance(data["hcpcs_code"], str) and data["hcpcs_code"]
    assert data["category"] in ("OSTOMY", "INCONTINENCE", "WOUND")
    assert isinstance(data["covered_plan_ids"], list)
    assert isinstance(data["size_codes"], list)
    assert data["status"] in ("ACTIVE", "DISCONTINUED")


def assert_patient(data: dict):
    _assert_common(data, "Patient")
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert data["status"] in ("PENDING_VERIFICATION", "ACTIVE", "INELIGIBLE")


def assert_prescription(data: dict):
    _assert_common(data, "Prescription")
    assert data["status"] in ("ACTIVE", "CANCELLED", "EXPIRED")
    assert isinstance(data["monthly_quantity"], int)


def assert_fit_profile(data: dict):
    _assert_common(data, "FitProfile")
    assert data["category"] in ("OSTOMY", "INCONTINENCE", "WOUND")
    assert data["status"] in ("CURRENT", "SUPERSEDED")


def assert_resupply_program(data: dict):
    _assert_common(data, "ResupplyProgram")
    assert data["category"] in ("OSTOMY", "INCONTINENCE", "WOUND")
    assert data["status"] in ("ACTIVE", "SUSPENDED")
    assert isinstance(data["frequency_days"], int)


def assert_supply_order(data: dict):
    _assert_common(data, "SupplyOrder")
    assert data["fulfillment_status"] in (
        "DRAFT", "SUBMITTED", "IN_FULFILLMENT", "FULFILLED", "CANCELLED",
    )
    assert data["billing_status"] in (
        "UNBILLED", "CLAIM_DRAFT", "CLAIM_SUBMITTED", "CLAIM_DENIED",
        "APPEAL_PENDING", "PAID_SETTLED", "PATIENT_BILLED",
    )
    assert data["origin"] in ("PROGRAM_CYCLE", "MANUAL_REORDER")


def assert_order_line(data: dict):
    _assert_common(data, "OrderLine")
    assert isinstance(data["quantity"], int) and data["quantity"] >= 1
    assert isinstance(data["unit_allowance_cents"], (int, float))
    assert isinstance(data["line_allowed_cents"], (int, float))


def assert_prior_authorization(data: dict):
    _assert_common(data, "PriorAuthorization")
    assert data["status"] in ("SUBMITTED", "APPROVED", "DENIED", "APPEALED", "EXPIRED")
    assert isinstance(data["appeal_count"], int)


def assert_shipment(data: dict):
    _assert_common(data, "Shipment")
    assert data["status"] in (
        "CREATED", "BACKORDERED", "READY", "SHIPPED", "DELIVERED", "RETURNED", "CANCELLED",
    )


def assert_stock_level(data: dict):
    _assert_common(data, "StockLevel")
    assert isinstance(data["on_hand_qty"], int)
    assert isinstance(data["reserved_qty"], int)
    assert isinstance(data["available_qty"], int)


def assert_backorder_reservation(data: dict):
    _assert_common(data, "BackorderReservation")
    assert data["status"] in ("PENDING", "PARTIALLY_ALLOCATED", "ALLOCATED", "CANCELLED")
    assert isinstance(data["quantity_pending"], int)
    assert isinstance(data["quantity_allocated"], int)


def assert_claim(data: dict):
    _assert_common(data, "Claim")
    assert data["status"] in ("DRAFT", "SUBMITTED", "PAID", "DENIED", "APPEALED", "DENIED_FINAL")
    assert isinstance(data["total_allowed_cents"], (int, float))
    assert isinstance(data["patient_resp_cents"], (int, float))
    assert isinstance(data["insurer_paid_cents"], (int, float))


def assert_hsa_account(data: dict):
    _assert_common(data, "HSAAccount")
    assert isinstance(data["initial_credit_cents"], (int, float))
    assert isinstance(data["balance_cents"], (int, float))


def assert_hsa_ledger_entry(data: dict):
    # Append-only: id + created_at, and no updated_at / version per PRD common-fields exception.
    assert is_valid_uuid(data.get("id", "")), "HSALedgerEntry.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "HSALedgerEntry.created_at must be ISO 8601"
    assert "updated_at" not in data, "append-only ledger entry must not carry updated_at"
    assert "version" not in data, "append-only ledger entry must not carry version"
    assert data["entry_type"] in ("DEBIT", "CREDIT", "REVERSAL")
    assert data["status"] == "POSTED"
    assert data["amount_cents"] > 0


def assert_fitting_sample(data: dict):
    _assert_common(data, "FittingSample")
    assert data["category"] in ("OSTOMY", "INCONTINENCE", "WOUND")
    assert data["status"] in ("REQUESTED", "SHIPPED", "OUTCOME_RECORDED")
    assert data["unit_price_cents"] == 0


def assert_stock_conservation(stock: dict):
    """available_qty must always equal on_hand_qty minus reserved_qty."""
    assert stock["available_qty"] == stock["on_hand_qty"] - stock["reserved_qty"], (
        f"stock conservation broken: available {stock['available_qty']} != "
        f"on_hand {stock['on_hand_qty']} - reserved {stock['reserved_qty']}"
    )
    assert stock["reserved_qty"] >= 0
    assert stock["available_qty"] >= 0
