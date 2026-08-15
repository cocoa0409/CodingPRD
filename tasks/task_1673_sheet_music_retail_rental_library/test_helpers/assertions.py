"""Entity assertions and domain invariant checkers (PRD §2.4, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "created_at must be an ISO 8601 timestamp"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        "updated_at must be an ISO 8601 timestamp"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_publisher(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["rental_discount_pct"], (int, float))
    assert isinstance(data["allows_digital_perusal"], bool)
    assert isinstance(data["print_only_rental"], bool)
    assert isinstance(data["out_of_print"], bool)
    assert data["status"] in ("ACTIVE", "SUSPENDED")


def assert_work(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("publisher_id", ""))
    assert isinstance(data["title"], str) and data["title"]
    assert isinstance(data["catalog_number"], str) and data["catalog_number"]
    assert data["ensemble_tier"] in ("CHAMBER", "BAND", "ORCHESTRA")
    assert isinstance(data["base_rental_rate_cents"], int)
    assert isinstance(data["sale_price_cents"], int)
    assert data["license_format"] in ("PRINT_ONLY", "DIGITAL_ONLY", "PRINT_AND_DIGITAL")
    assert isinstance(data["perusal_allowed"], bool)
    assert data["rights_class"] in ("STANDARD", "GRAND_RIGHTS", "RESTRICTED")
    assert data["status"] in ("CATALOGED", "WITHDRAWN")


def assert_rental_set(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("work_id", ""))
    assert isinstance(data["set_code"], str) and data["set_code"]
    assert isinstance(data["copy_count"], int) and data["copy_count"] >= 1
    assert isinstance(data["available_copy_count"], int)
    assert data["condition_grade"] in ("A", "B", "C", "D")
    assert isinstance(data["replacement_value_cents"], int)
    assert data["status"] in ("IN_SERVICE", "UNDER_REPAIR", "RETIRED")


def assert_customer_account(data: dict):
    _assert_common(data)
    assert isinstance(data["account_name"], str) and data["account_name"]
    assert data["account_kind"] in ("INDIVIDUAL", "SCHOOL", "INSTITUTION")
    assert data["credit_tier"] in ("PREFERRED", "STANDARD", "PREPAY")
    assert isinstance(data["credit_limit_cents"], int)
    assert isinstance(data["open_exposure_cents"], int)
    assert isinstance(data["settled_exposure_cents"], int)
    assert data["standing"] in ("GOOD", "HOLD", "BARRED")
    assert isinstance(data["requires_purchase_order"], bool)


def assert_purchase_order(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("account_id", ""))
    assert isinstance(data["po_number"], str) and data["po_number"]
    assert isinstance(data["authorized_amount_cents"], int)
    assert isinstance(data["encumbered_cents"], int)
    assert data["status"] in (
        "SUBMITTED", "APPROVED", "SUSPENDED", "EXPIRED", "CLOSED", "REJECTED",
    )


def assert_rental_order(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("account_id", ""))
    assert is_valid_uuid(data.get("rental_set_id", ""))
    assert data["fulfillment_format"] in ("PHYSICAL", "DIGITAL")
    assert isinstance(data["copies_requested"], int) and data["copies_requested"] >= 1
    assert isinstance(data["loan_periods"], int) and data["loan_periods"] >= 1
    assert isinstance(data["renewal_count"], int) and data["renewal_count"] >= 0
    assert isinstance(data["prepayment_cents"], int) and data["prepayment_cents"] >= 0
    assert data["status"] in (
        "DRAFT", "RESERVED", "DISPATCHED", "ON_LOAN", "OVERDUE",
        "RETURNED", "DISPUTED", "SETTLED", "CANCELLED",
    )


def assert_rental_line(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("rental_order_id", ""))
    assert isinstance(data["copy_seq"], int) and data["copy_seq"] >= 1
    assert data["checkout_condition"] in ("A", "B", "C", "D")
    assert data.get("return_condition") in (None, "A", "B", "C", "D", "LOST")
    assert data["status"] in (
        "RESERVED", "DISPATCHED", "ON_LOAN", "OVERDUE", "RETURNED", "LOST", "RELEASED",
    )


def assert_condition_report(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("rental_line_id", ""))
    assert data["observed_grade"] in ("A", "B", "C", "D", "LOST")
    assert isinstance(data["assessed_charge_cents"], int)
    assert data["status"] in ("FILED", "INVOICED", "SUPERSEDED")


def assert_damage_invoice(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("rental_line_id", ""))
    assert is_valid_uuid(data.get("condition_report_id", ""))
    assert is_valid_uuid(data.get("account_id", ""))
    assert isinstance(data["amount_cents"], int)
    assert data["status"] in (
        "DRAFT", "ISSUED", "PAID", "DISPUTED", "RESOLVED_ACCEPTED", "RESOLVED_WAIVED",
    )


def assert_perusal_request(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("account_id", ""))
    assert is_valid_uuid(data.get("work_id", ""))
    assert data["format"] in ("PHYSICAL", "DIGITAL")
    assert data["converted_target_kind"] in ("NONE", "RENTAL", "PURCHASE")
    assert data["status"] in (
        "REQUESTED", "APPROVED", "SHIPPED", "OVERDUE_PERUSAL",
        "RETURNED", "CONVERTED", "EXPIRED", "REJECTED",
    )


def assert_sale_record(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("account_id", ""))
    assert is_valid_uuid(data.get("work_id", ""))
    assert isinstance(data["quantity"], int) and data["quantity"] >= 1
    assert isinstance(data["unit_price_cents"], int)
    assert isinstance(data["total_cents"], int)
    assert isinstance(data["balance_due_cents"], int)
    assert data["status"] in ("INVOICED", "PAID", "WRITTEN_OFF")


def assert_rights_case(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("account_id", ""))
    assert is_valid_uuid(data.get("work_id", ""))
    assert data["venue_kind"] in ("EDUCATIONAL", "CONCERT", "COMPETITION", "RELIGIOUS")
    assert data["determination"] in (
        "PENDING", "CLEARED", "LICENSE_REQUIRED", "PROHIBITED",
    )
    assert data["status"] in ("OPEN", "DECIDED", "WITHDRAWN")


def assert_copy_pool_invariant(rental_set: dict, held_line_count: int):
    """PRD §3.2: available_copy_count equals copy_count minus the copies held by
    lines in RESERVED / DISPATCHED / ON_LOAN / OVERDUE status."""
    expected = rental_set["copy_count"] - held_line_count
    assert rental_set["available_copy_count"] == expected, (
        f"copy pool invariant violated: available "
        f"{rental_set['available_copy_count']} != copy_count "
        f"{rental_set['copy_count']} - held {held_line_count}"
    )
