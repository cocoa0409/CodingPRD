"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def assert_party(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1
    assert data["kind"] in ("SCHOOL", "PUBLISHER", "AUTHOR")
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["contact_email"], str)


def assert_fair(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1
    assert data["status"] in (
        "DRAFT", "SCHEDULED", "STOCKING", "OPEN", "RECONCILING", "SETTLED", "CANCELLED"
    )
    assert isinstance(data["school_party_id"], str)
    assert isinstance(data["title"], str)
    assert isinstance(data["venue_key"], str)
    assert isinstance(data["signing_floor_capacity_units"], int)
    assert isinstance(data["promo_budget_cents"], int)
    for f in ("gross_sales_cents", "firm_purchases_cents", "publisher_remittance_cents",
              "return_credits_cents", "honorarium_total_cents"):
        assert isinstance(data[f], int), f"{f} must be an integer"
        assert data[f] >= 0, f"{f} must be non-negative"
    assert isinstance(data["preorder_allocation_run"], bool)


def assert_venue_slot(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert data["status"] in ("HELD", "CONFIRMED", "RELEASED")
    assert data["purpose"] in ("SETUP", "FAIR_DAY", "AUTHOR_EVENT", "TEARDOWN")
    assert isinstance(data["setup_buffer_minutes"], int)
    assert isinstance(data["teardown_buffer_minutes"], int)


def assert_agreement(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert data["status"] in ("PROPOSED", "COUNTERED", "ACCEPTED", "DECLINED", "EXPIRED")
    assert data["offered_by"] in ("ORGANIZER", "PUBLISHER")
    assert isinstance(data["negotiation_round"], int) and data["negotiation_round"] >= 1
    assert isinstance(data.get("version"), int) and data["version"] >= 1


def assert_stock_line(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert data["status"] in ("QUOTED", "COMMITTED", "DELIVERED", "RECONCILED")
    assert data["line_type"] in ("FRONTLIST", "BACKLIST")
    for f in ("qty_committed", "qty_delivered", "qty_held_preorder", "qty_sold",
              "qty_damaged", "qty_returned_shipped", "qty_returned_credited",
              "qty_available_for_sale"):
        assert isinstance(data[f], int), f"{f} must be an integer"


def assert_booking(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert data["status"] in (
        "INVITED", "NEGOTIATING", "CONFIRMED", "TRAVEL_BOOKED",
        "SETTLED", "CANCELLED", "DECLINED"
    )
    assert data["offered_by"] in ("ORGANIZER", "AUTHOR")
    assert isinstance(data["negotiation_round"], int)
    assert isinstance(data.get("version"), int) and data["version"] >= 1


def assert_session(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert data["status"] in (
        "SCHEDULED", "OPEN_FOR_SIGNING", "CLOSED_FOR_SIGNING", "RECONCILED", "CANCELLED"
    )
    assert data["mode"] in ("TICKETED", "FREE")
    assert isinstance(data["line_space_units"], int) and data["line_space_units"] > 0
    assert isinstance(data["capacity_seats"], int) and data["capacity_seats"] > 0
    assert isinstance(data["admit_concurrent_cap"], int) and data["admit_concurrent_cap"] > 0


def assert_ticket(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["status"] in ("ISSUED", "ADMITTED", "REDEEMED", "NO_SHOW", "VOIDED")
    assert data["kind"] in ("TICKET", "WRISTBAND")
    # common_fields: false — must NOT have version or updated_at
    assert "version" not in data, "SigningTicket must not expose version"
    assert "updated_at" not in data, "SigningTicket must not expose updated_at"


def assert_preorder(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert data["status"] in ("PLACED", "ALLOCATED", "FULFILLED", "CONVERTED_BACKLIST", "CANCELLED")
    assert isinstance(data["qty"], int) and data["qty"] > 0


def assert_sale(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert data["status"] in ("DRAFT", "TENDERED", "VOIDED")
    assert isinstance(data["total_cents"], int)
    assert isinstance(data["lines"], list)


def assert_reconciliation(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert data["status"] in (
        "OPEN", "VARIANCE_REVIEW", "APPROVED", "SUBMITTED", "DISPUTED", "ACCEPTED"
    )
    assert isinstance(data["total_abs_variance"], int)
    assert isinstance(data.get("version"), int) and data["version"] >= 1


def assert_return_authorization(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert data["status"] in ("REQUESTED", "APPROVED", "REJECTED", "SHIPPED", "CREDITED")
    assert isinstance(data["lines"], list)


def assert_payout(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert data["status"] in ("DRAFT", "CALCULATED", "APPROVED", "PAID")


def assert_media_blast(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert data["status"] in ("DRAFT", "PENDING_APPROVAL", "APPROVED", "REJECTED", "PUBLISHED")
    assert data["channel"] in ("LOCAL_PAPER", "RADIO", "SOCIAL", "SCHOOL_NEWSLETTER")
    assert isinstance(data["spend_cents"], int) and data["spend_cents"] >= 0


def assert_copy_conservation(line: dict):
    """Copy-conservation invariant: qty_delivered == held + sold + damaged + returned_shipped + available."""
    total = (
        line["qty_held_preorder"]
        + line["qty_sold"]
        + line["qty_damaged"]
        + line["qty_returned_shipped"]
        + line["qty_available_for_sale"]
    )
    assert total == line["qty_delivered"], (
        f"copy-conservation violated: delivered={line['qty_delivered']} but "
        f"held={line['qty_held_preorder']} + sold={line['qty_sold']} + "
        f"damaged={line['qty_damaged']} + returned_shipped={line['qty_returned_shipped']} + "
        f"available={line['qty_available_for_sale']} = {total}"
    )
