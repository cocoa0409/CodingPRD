"""Payload factories — one per entity, input fields only."""
import itertools

from .constants import FL_SCHEDULE

# Monotonic counter so gov_id_number values are unique per test process
# (gov_id_number is unique; PRD §3.2).
_gov_id_seq = itertools.count(1)


def unique_gov_id(prefix: str = "ID") -> str:
    return f"{prefix}-{next(_gov_id_seq)}"


def create_state_schedule_payload(**overrides) -> dict:
    defaults = dict(FL_SCHEDULE)
    defaults.update(overrides)
    return defaults


def create_shop_payload(**overrides) -> dict:
    defaults = {
        "name": "Test Branch",
        "state_code": "FL",
        "police_reporting_enabled": False,
    }
    defaults.update(overrides)
    return defaults


def create_storage_bin_payload(shop_id: str, **overrides) -> dict:
    defaults = {
        "shop_id": shop_id,
        "label": "A-1",
        "capacity": 5,
    }
    defaults.update(overrides)
    return defaults


def create_customer_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Test Borrower",
        "gov_id_number": unique_gov_id(),
    }
    defaults.update(overrides)
    return defaults


def create_item_payload(shop_id: str, customer_id: str, **overrides) -> dict:
    defaults = {
        "shop_id": shop_id,
        "customer_id": customer_id,
        "description": "Test item",
    }
    defaults.update(overrides)
    return defaults


def appraise_item_payload(appraised_value_cents: int = 40000, **overrides) -> dict:
    defaults = {"appraised_value_cents": appraised_value_cents}
    defaults.update(overrides)
    return defaults


def create_loan_payload(shop_id: str, pawn_item_id: str, storage_bin_id: str, **overrides) -> dict:
    defaults = {
        "shop_id": shop_id,
        "pawn_item_id": pawn_item_id,
        "storage_bin_id": storage_bin_id,
    }
    defaults.update(overrides)
    return defaults


def extend_loan_payload(expected_loan_version: int, **overrides) -> dict:
    defaults = {"expected_loan_version": expected_loan_version}
    defaults.update(overrides)
    return defaults


def renew_loan_payload(expected_loan_version: int, **overrides) -> dict:
    defaults = {"expected_loan_version": expected_loan_version}
    defaults.update(overrides)
    return defaults


def sell_inventory_payload(sold_price_cents: int, **overrides) -> dict:
    defaults = {"sold_price_cents": sold_price_cents}
    defaults.update(overrides)
    return defaults


def create_layaway_plan_payload(inventory_item_id: str, customer_id: str,
                                installment_count: int = 3,
                                reserved_until_at: str = "2026-12-01T00:00:00.000Z",
                                **overrides) -> dict:
    defaults = {
        "inventory_item_id": inventory_item_id,
        "customer_id": customer_id,
        "installment_count": installment_count,
        "reserved_until_at": reserved_until_at,
    }
    defaults.update(overrides)
    return defaults


def post_installment_payload(amount_cents: int, **overrides) -> dict:
    defaults = {"amount_cents": amount_cents}
    defaults.update(overrides)
    return defaults


def create_police_hold_payload(subject_kind: str, case_number: str = "CASE-1",
                               pawn_item_id: str = None, inventory_item_id: str = None,
                               **overrides) -> dict:
    defaults = {
        "subject_kind": subject_kind,
        "case_number": case_number,
    }
    if pawn_item_id is not None:
        defaults["pawn_item_id"] = pawn_item_id
    if inventory_item_id is not None:
        defaults["inventory_item_id"] = inventory_item_id
    defaults.update(overrides)
    return defaults


def set_clock_payload(to_iso8601: str, **overrides) -> dict:
    defaults = {"to_iso8601": to_iso8601}
    defaults.update(overrides)
    return defaults
