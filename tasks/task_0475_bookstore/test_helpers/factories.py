"""Payload factories — one per entity, input fields only."""
import itertools

_isbn_counter = itertools.count(1)


def unique_isbn13() -> str:
    """Return a fresh, valid 13-digit ISBN unique within a single test run.

    Each test runs against a fresh empty DB (server is restarted per test), so a
    sequence anchored on a counter is enough to avoid collisions within a test.
    """
    n = next(_isbn_counter)
    # 978 prefix + zero-padded counter to reach exactly 13 digits.
    return "978" + str(n).zfill(10)


def create_member_payload(**overrides) -> dict:
    """Required: email, full_name. Optional: tier, is_local_author."""
    defaults = {
        "email": f"member{next(_isbn_counter)}@example.com",
        "full_name": "Test Member",
    }
    defaults.update(overrides)
    return defaults


def create_title_payload(**overrides) -> dict:
    """Required: isbn13, name, list_price_cents.
    Optional: category, returnable, demand_flag, pod_eligible."""
    defaults = {
        "isbn13": unique_isbn13(),
        "name": "Test Title",
        "list_price_cents": 1000,
    }
    defaults.update(overrides)
    return defaults


def create_stock_items_payload(quantity=1, **overrides) -> dict:
    """Required: quantity. Optional: cost_cents."""
    defaults = {"quantity": quantity}
    defaults.update(overrides)
    return defaults


def create_sales_order_payload(member_id, **overrides) -> dict:
    """Required: member_id. Optional: credit_redeemed_cents."""
    defaults = {"member_id": member_id}
    defaults.update(overrides)
    return defaults


def create_order_line_payload(title_id, quantity=1, **overrides) -> dict:
    """Required: title_id, quantity."""
    defaults = {"title_id": title_id, "quantity": quantity}
    defaults.update(overrides)
    return defaults


def create_special_order_payload(member_id, title_id, quantity=1,
                                 fulfillment_method="DISTRIBUTOR", **overrides) -> dict:
    """Required: member_id, title_id, quantity, fulfillment_method."""
    defaults = {
        "member_id": member_id,
        "title_id": title_id,
        "quantity": quantity,
        "fulfillment_method": fulfillment_method,
    }
    defaults.update(overrides)
    return defaults


def create_publisher_return_payload(title_id, quantity=1, **overrides) -> dict:
    """Required: title_id, quantity."""
    defaults = {"title_id": title_id, "quantity": quantity}
    defaults.update(overrides)
    return defaults


def create_buyback_payload(member_id, **overrides) -> dict:
    """Required: member_id."""
    defaults = {"member_id": member_id}
    defaults.update(overrides)
    return defaults


def create_buyback_line_payload(title_id, condition_grade="GOOD", quantity=1,
                                **overrides) -> dict:
    """Required: title_id, condition_grade, quantity."""
    defaults = {
        "title_id": title_id,
        "condition_grade": condition_grade,
        "quantity": quantity,
    }
    defaults.update(overrides)
    return defaults


def create_author_event_payload(title_id, starts_at, capacity=10,
                                base_price_cents=2000, **overrides) -> dict:
    """Required: title_id, name, starts_at, capacity, base_price_cents."""
    defaults = {
        "title_id": title_id,
        "name": "Test Event",
        "starts_at": starts_at,
        "capacity": capacity,
        "base_price_cents": base_price_cents,
    }
    defaults.update(overrides)
    return defaults


def book_ticket_payload(member_id, **overrides) -> dict:
    """Required: member_id."""
    defaults = {"member_id": member_id}
    defaults.update(overrides)
    return defaults


def create_consignment_agreement_payload(author_member_id, title_id, **overrides) -> dict:
    """Required: author_member_id, title_id."""
    defaults = {"author_member_id": author_member_id, "title_id": title_id}
    defaults.update(overrides)
    return defaults


def create_consignment_copy_payload(sale_price_cents=2000, **overrides) -> dict:
    """Required: sale_price_cents."""
    defaults = {"sale_price_cents": sale_price_cents}
    defaults.update(overrides)
    return defaults


def credit_adjustment_payload(delta_cents, **overrides) -> dict:
    """Required: delta_cents."""
    defaults = {"delta_cents": delta_cents}
    defaults.update(overrides)
    return defaults
