"""Entity assertions and domain invariant checkers (PRD §2.5, §2.9, §2.10, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_fields(data: dict, entity: str):
    """Every resource carries id, created_at, updated_at, version (PRD §2.5)."""
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"{entity}.created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        f"{entity}.updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        f"{entity}.version must be an integer starting at 1"


def assert_customer(data: dict):
    _assert_common_fields(data, "Customer")
    assert isinstance(data["account_no"], str) and data["account_no"]
    assert isinstance(data["name"], str) and data["name"]
    assert data["terms"] in ("CASH", "NET30")
    assert data["status"] in ("ACTIVE", "CREDIT_HOLD", "SUSPENDED")
    assert isinstance(data["credit_limit_cents"], int)
    assert data.get("price_book_id") is None or is_valid_uuid(data["price_book_id"])
    for field in ("posted_exposure_cents", "accrued_rental_cents",
                  "projected_exposure_cents", "outstanding_balance_cents",
                  "credit_balance_cents"):
        assert isinstance(data[field], int), f"Customer.{field} must be int cents"


def assert_price_book(data: dict):
    _assert_common_fields(data, "PriceBook")
    assert isinstance(data["name"], str) and data["name"]
    assert data["scope"] in ("RETAIL", "CONTRACT")
    assert data.get("customer_id") is None or is_valid_uuid(data["customer_id"])
    assert isinstance(data["effective_from"], str)
    assert isinstance(data["effective_to"], str)
    assert isinstance(data["default_discount_pct"], (int, float))
    assert 0 <= data["default_discount_pct"] <= 0.90
    assert isinstance(data["volume_tiers"], list)
    assert data["status"] in ("DRAFT", "ACTIVE", "EXPIRED")


def assert_product(data: dict):
    _assert_common_fields(data, "Product")
    assert isinstance(data["sku"], str) and data["sku"]
    assert isinstance(data["name"], str) and data["name"]
    assert data["category"] in ("HARDGOOD", "GAS", "SPECIALTY_GAS")
    if data["category"] in ("GAS", "SPECIALTY_GAS"):
        assert data["gas_grade"] in ("OXYGEN", "ACETYLENE", "ARGON",
                                     "AR_CO2_7525", "NITROGEN")
    else:
        assert data.get("gas_grade") is None
    assert isinstance(data["retail_price_cents"], int) \
        and data["retail_price_cents"] >= 0
    assert isinstance(data["hazmat"], bool)
    assert isinstance(data["stock_on_hand"], int)
    assert isinstance(data["reorder_point"], int)
    assert isinstance(data["lead_time_days"], int)
    assert isinstance(data["needs_reorder"], bool)


def assert_cylinder_asset(data: dict):
    _assert_common_fields(data, "CylinderAsset")
    assert isinstance(data["serial_no"], str) and data["serial_no"]
    assert data["gas_grade"] in ("OXYGEN", "ACETYLENE", "ARGON",
                                 "AR_CO2_7525", "NITROGEN")
    assert data["size"] in ("SMALL", "MEDIUM", "LARGE")
    assert data["status"] in ("FULL", "EMPTY", "OUT", "RETIRED")
    assert data.get("holder_customer_id") is None or \
        is_valid_uuid(data["holder_customer_id"])
    assert data.get("rental_agreement_id") is None or \
        is_valid_uuid(data["rental_agreement_id"])


def assert_machine(data: dict):
    _assert_common_fields(data, "Machine")
    assert isinstance(data["model"], str) and data["model"]
    assert isinstance(data["serial_no"], str) and data["serial_no"]
    for field in ("daily_rate_cents", "weekly_rate_cents", "monthly_rate_cents"):
        assert isinstance(data[field], int) and data[field] > 0
    assert data["status"] in ("AVAILABLE", "RENTED")


def assert_rental_agreement(data: dict):
    _assert_common_fields(data, "RentalAgreement")
    assert is_valid_uuid(data.get("customer_id", ""))
    assert data["item_type"] in ("CYLINDER", "MACHINE")
    if data["item_type"] == "CYLINDER":
        assert is_valid_uuid(data.get("cylinder_asset_id", ""))
        assert data.get("machine_id") is None
    else:
        assert is_valid_uuid(data.get("machine_id", ""))
        assert data.get("cylinder_asset_id") is None
    assert data["rate_plan"] in ("DEMURRAGE", "DAILY", "WEEKLY", "MONTHLY")
    assert isinstance(data["start_date"], str)
    assert isinstance(data["grace_days"], int) and data["grace_days"] >= 0
    assert data["status"] in ("ACTIVE", "SUSPENDED", "CLOSED")
    assert data.get("billed_through_date") is None or \
        isinstance(data["billed_through_date"], str)
    assert isinstance(data["lifetime_billed_cents"], int)
    assert isinstance(data["waived_cents"], int)
    assert isinstance(data["accrued_unbilled_cents"], int)
    assert data.get("closed_at") is None or isinstance(data["closed_at"], str)


def assert_delivery_route(data: dict):
    _assert_common_fields(data, "DeliveryRoute")
    assert isinstance(data["route_date"], str)
    assert isinstance(data["truck_capacity_units"], int) \
        and data["truck_capacity_units"] > 0
    assert isinstance(data["reserved_units"], int) and data["reserved_units"] >= 0
    assert data["status"] in ("PLANNED", "DISPATCHED", "CLOSED")


def assert_order(data: dict):
    _assert_common_fields(data, "Order")
    assert is_valid_uuid(data.get("customer_id", ""))
    assert data["order_type"] in ("RETAIL", "EXCHANGE", "SPECIAL_MIX")
    assert data["fulfillment"] in ("WILL_CALL", "ROUTE")
    assert data.get("route_id") is None or is_valid_uuid(data["route_id"])
    assert isinstance(data["lines"], list) and data["lines"]
    assert isinstance(data["units"], int) and data["units"] >= 1
    assert data.get("available_date") is None or \
        isinstance(data["available_date"], str)
    assert data["fulfillment_status"] in ("DRAFT", "CONFIRMED", "STAGED",
                                          "FULFILLED", "CANCELLED")
    assert data["payment_status"] in ("UNPAID", "PAID", "INVOICED", "SETTLED")
    for field in ("subtotal_cents", "delivery_fee_cents", "hazmat_fee_cents",
                  "total_cents"):
        assert isinstance(data[field], int), f"Order.{field} must be int cents"
    assert data.get("invoice_id") is None or is_valid_uuid(data["invoice_id"])


def assert_invoice(data: dict):
    _assert_common_fields(data, "Invoice")
    assert is_valid_uuid(data.get("customer_id", ""))
    assert data["source"] in ("ORDER", "RENTAL_CYCLE", "RENTAL_CLOSE")
    if data["source"] == "ORDER":
        assert is_valid_uuid(data.get("order_id", ""))
    else:
        assert data.get("order_id") is None
    assert isinstance(data["amount_cents"], int)
    assert isinstance(data["paid_cents"], int)
    assert data["status"] in ("OPEN", "PAID", "VOID")
    assert is_iso8601_timestamp(data.get("issued_at", ""))
    assert isinstance(data["due_at"], str) and data["due_at"]


def assert_training_class(data: dict):
    _assert_common_fields(data, "TrainingClass")
    assert isinstance(data["title"], str) and data["title"]
    assert data["room"] in ("ROOM_A", "ROOM_B")
    assert is_iso8601_timestamp(data.get("start_at", ""))
    assert is_iso8601_timestamp(data.get("end_at", ""))
    assert isinstance(data["capacity"], int) and data["capacity"] > 0
    assert isinstance(data["price_cents"], int) and data["price_cents"] >= 0
    assert isinstance(data["seats_booked"], int) and data["seats_booked"] >= 0
    assert data["status"] in ("SCHEDULED", "COMPLETED", "CANCELLED")


def assert_training_enrollment(data: dict):
    _assert_common_fields(data, "TrainingEnrollment")
    assert is_valid_uuid(data.get("class_id", ""))
    assert is_valid_uuid(data.get("customer_id", ""))
    assert isinstance(data["attendee_name"], str) and data["attendee_name"]
    assert data["status"] in ("ENROLLED", "ATTENDED", "NO_SHOW", "CANCELLED")
    assert data.get("cert_code") is None or isinstance(data["cert_code"], str)
    assert data.get("cert_expires_at") is None or \
        isinstance(data["cert_expires_at"], str)


def assert_repair_ticket(data: dict):
    _assert_common_fields(data, "RepairTicket")
    assert is_valid_uuid(data.get("customer_id", ""))
    assert isinstance(data["machine_desc"], str)
    assert isinstance(data["issue_desc"], str)
    assert data["status"] in ("INTAKE", "DIAGNOSING", "QUOTED", "APPROVED",
                              "IN_REPAIR", "READY_FOR_PICKUP", "REJECTED",
                              "CLOSED")
    assert data.get("quote_cents") is None or isinstance(data["quote_cents"], int)
    assert isinstance(data["revision_no"], int) and data["revision_no"] >= 0
    assert data.get("charged_cents") is None or \
        isinstance(data["charged_cents"], int)


# ---------------------------------------------------------------------------
# Domain invariants
# ---------------------------------------------------------------------------

def assert_customer_exposure_invariants(customer: dict):
    """Balance figures obey the floor/ordering relations of PRD §2.9."""
    assert customer["posted_exposure_cents"] == max(
        0, customer["outstanding_balance_cents"]
        - customer["credit_balance_cents"]), (
        "posted exposure must be outstanding minus credit, floored at zero")
    assert customer["projected_exposure_cents"] >= \
        customer["posted_exposure_cents"], (
        "projected exposure is never less than posted exposure (PRD §2.9)")


def float_grade(summary: dict, gas_grade: str) -> dict:
    """Return the per-grade entry of a float-summary response (PRD §2.10)."""
    for entry in summary.get("grades", []):
        if entry["gas_grade"] == gas_grade:
            return entry
    raise AssertionError(
        f"float summary has no entry for grade {gas_grade}: {summary}")
