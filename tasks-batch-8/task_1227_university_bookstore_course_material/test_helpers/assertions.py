"""Entity assertions and domain invariant checkers.

Every assert_{entity} checks the common field set (id / created_at /
updated_at / version) plus entity-specific shape, using only PRD-named
fields and PRD-declared enum values.
"""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common(data: dict, entity: str):
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"{entity}.created_at must be ISO 8601"
    assert is_iso8601_timestamp(
        data.get("updated_at", "")
    ), f"{entity}.updated_at must be ISO 8601"
    assert isinstance(
        data.get("version"), int
    ) and data["version"] >= 1, f"{entity}.version must be a positive integer"


def assert_term(data: dict):
    _assert_common(data, "AcademicTerm")
    assert isinstance(data["code"], str) and data["code"]
    assert isinstance(data["length_weeks"], int) and data["length_weeks"] > 0
    assert data["status"] in [
        "SETUP", "ADOPTION_OPEN", "ADOPTION_CLOSED", "SALES_OPEN",
        "CENSUS_DONE", "BUYBACK_OPEN", "TERM_CLOSED",
    ]
    assert isinstance(data["noncompliant_section_count"], int)
    assert data["compliance_posture"] in ["CLEAR", "RESTRICTED"]
    assert isinstance(data["buy_budget_cents"], int) and data["buy_budget_cents"] >= 0


def assert_publisher(data: dict):
    _assert_common(data, "Publisher")
    assert isinstance(data["name"], str) and data["name"]


def assert_agreement(data: dict):
    _assert_common(data, "PublisherAgreement")
    assert is_valid_uuid(data.get("publisher_id", ""))
    for pct in ("discount_pct", "digital_discount_pct", "commission_pct"):
        assert 0 <= data[pct] < 1, f"{pct} must satisfy 0 <= x < 1"


def assert_title(data: dict):
    _assert_common(data, "Title")
    assert isinstance(data["isbn"], str) and data["isbn"]
    assert is_valid_uuid(data.get("publisher_id", ""))
    assert isinstance(data["list_price_cents"], int) and data["list_price_cents"] > 0
    for flag in ("has_new", "has_used", "has_rental", "has_digital"):
        assert isinstance(data[flag], bool), f"{flag} must be boolean"
    for stock in ("new_stock_qty", "used_stock_qty", "rental_stock_qty"):
        assert isinstance(data[stock], int) and data[stock] >= 0


def assert_faculty(data: dict):
    _assert_common(data, "Faculty")
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and "@" in data["email"]


def assert_student(data: dict):
    _assert_common(data, "Student")
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and "@" in data["email"]
    assert isinstance(data["awarded_aid_cents"], int) and data["awarded_aid_cents"] >= 0
    assert isinstance(data["aid_balance_cents"], int)


def assert_section(data: dict):
    _assert_common(data, "CourseSection")
    assert is_valid_uuid(data.get("term_id", ""))
    assert is_valid_uuid(data.get("faculty_id", ""))
    assert isinstance(data["course_code"], str) and data["course_code"]
    assert isinstance(data["section_code"], str) and data["section_code"]
    assert isinstance(data["enrollment_capacity"], int) and data["enrollment_capacity"] >= 0
    assert isinstance(data["ia_enabled"], bool)
    assert data["status"] in ["DRAFT", "OPEN", "LOCKED", "CLOSED"]
    assert data["compliance_status"] in ["PENDING", "COMPLIANT", "NON_COMPLIANT"]


def assert_enrollment(data: dict):
    _assert_common(data, "Enrollment")
    assert is_valid_uuid(data.get("section_id", ""))
    assert is_valid_uuid(data.get("student_id", ""))
    assert data["status"] in ["ENROLLED", "DROPPED"]


def assert_adoption(data: dict):
    _assert_common(data, "Adoption")
    assert is_valid_uuid(data.get("section_id", ""))
    assert is_valid_uuid(data.get("title_id", ""))
    assert is_valid_uuid(data.get("faculty_id", ""))
    for qty in (
        "qty_new_requested", "qty_used_requested",
        "qty_rental_requested", "qty_digital_requested",
    ):
        assert isinstance(data[qty], int) and data[qty] >= 0
    assert data["status"] in [
        "DRAFT", "SUBMITTED", "UNDER_REVIEW", "APPROVED",
        "RETURNED", "EXPIRED", "SUPERSEDED",
    ]
    assert isinstance(data["late_flag"], bool)
    assert isinstance(data["transparency_late_flag"], bool)


def assert_buy_plan(data: dict):
    _assert_common(data, "BuyPlan")
    assert is_valid_uuid(data.get("adoption_id", ""))
    for qty in ("qty_new", "qty_used", "qty_rental", "qty_digital"):
        assert isinstance(data[qty], int) and data[qty] >= 0
    assert isinstance(data["landed_cost_cents"], int)
    assert isinstance(data["tier_bonus_applied"], bool)
    assert data["status"] in ["DRAFT", "COMMITTED", "RECEIVED", "CANCELLED"]


def assert_order(data: dict):
    _assert_common(data, "Order")
    assert is_valid_uuid(data.get("student_id", ""))
    assert is_valid_uuid(data.get("term_id", ""))
    for money in ("total_cents", "aid_tendered_cents", "card_tendered_cents", "refund_total_cents"):
        assert isinstance(data[money], int) and data[money] >= 0
    assert data["status"] in ["SETTLED", "PARTIALLY_REFUNDED", "REFUNDED", "CLOSED"]


def assert_order_line(data: dict):
    _assert_common(data, "OrderLine")
    assert is_valid_uuid(data.get("order_id", ""))
    assert is_valid_uuid(data.get("adoption_id", ""))
    assert is_valid_uuid(data.get("title_id", ""))
    assert data["format"] in ["NEW", "USED", "RENTAL", "DIGITAL"]
    assert isinstance(data["qty"], int) and data["qty"] >= 1
    for money in (
        "unit_price_cents", "line_total_cents", "aid_tendered_cents",
        "card_tendered_cents", "aid_refunded_cents", "card_refunded_cents",
    ):
        assert isinstance(data[money], int) and data[money] >= 0
    assert data["status"] in ["FULFILLED", "RETURNED"]


def assert_ia_charge(data: dict):
    _assert_common(data, "InclusiveAccessCharge")
    assert is_valid_uuid(data.get("enrollment_id", ""))
    assert is_valid_uuid(data.get("section_id", ""))
    assert is_valid_uuid(data.get("student_id", ""))
    assert is_valid_uuid(data.get("term_id", ""))
    for money in ("fee_cents", "aid_applied_cents", "balance_due_cents"):
        assert isinstance(data[money], int) and data[money] >= 0
    assert data["status"] in [
        "PENDING", "OPTED_OUT", "BILLED", "REFUNDED", "CANCELLED",
    ]


def assert_wholesale_quote(data: dict):
    _assert_common(data, "WholesaleQuote")
    assert is_valid_uuid(data.get("title_id", ""))
    assert data["condition"] in ["LIKE_NEW", "GOOD", "ACCEPTABLE"]
    assert isinstance(data["price_cents"], int) and data["price_cents"] > 0


def assert_buyback_ticket(data: dict):
    _assert_common(data, "BuybackTicket")
    assert is_valid_uuid(data.get("student_id", ""))
    assert is_valid_uuid(data.get("title_id", ""))
    assert is_valid_uuid(data.get("upcoming_term_id", ""))
    assert data["condition"] in ["LIKE_NEW", "GOOD", "ACCEPTABLE"]
    assert data["pricing_variant"] in ["NEEDS_BASED", "WHOLESALE"]
    assert isinstance(data["quoted_price_cents"], int)
    assert is_iso8601_timestamp(data.get("quote_valid_until", ""))
    assert data["status"] in ["QUOTED", "ACCEPTED", "PAID", "EXPIRED", "REJECTED"]


def assert_commission_statement(data: dict):
    _assert_common(data, "CommissionStatement")
    assert is_valid_uuid(data.get("publisher_id", ""))
    assert is_valid_uuid(data.get("term_id", ""))
    assert data["calculation_variant"] in ["PROVISIONAL", "FINAL"]
    for money in ("gross_sales_cents", "returns_cents", "net_sales_cents", "commission_cents"):
        assert isinstance(data[money], int)
    assert data["status"] in ["DRAFT", "ISSUED", "SETTLED"]
