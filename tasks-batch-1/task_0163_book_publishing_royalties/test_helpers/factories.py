"""Payload factories — one per entity, input fields only."""
import uuid


def _unique_email(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}@example.com"


def create_author_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Test Author",
        "email": _unique_email("author"),
    }
    defaults.update(overrides)
    return defaults


def create_agent_payload(**overrides) -> dict:
    defaults = {
        "agency_name": "Test Agency",
        "email": _unique_email("agent"),
    }
    defaults.update(overrides)
    return defaults


def create_contract_payload(author_id: str, **overrides) -> dict:
    defaults = {
        "author_id": author_id,
        "advance_cents": 0,
    }
    defaults.update(overrides)
    return defaults


def create_royalty_tier_payload(lower_unit: int, rate: float, upper_unit=None, **overrides) -> dict:
    defaults = {"lower_unit": lower_unit, "rate": rate}
    if upper_unit is not None:
        defaults["upper_unit"] = upper_unit
    defaults.update(overrides)
    return defaults


def create_title_payload(name: str = "Test Book", **overrides) -> dict:
    defaults = {"name": name}
    defaults.update(overrides)
    return defaults


def create_format_payload(format_type: str = "HARDCOVER", list_price_cents: int = 3000, **overrides) -> dict:
    defaults = {"format_type": format_type, "list_price_cents": list_price_cents}
    defaults.update(overrides)
    return defaults


def create_sales_period_payload(label: str, sequence: int, **overrides) -> dict:
    defaults = {"label": label, "sequence": sequence}
    defaults.update(overrides)
    return defaults


def create_sales_record_payload(format_id: str, units_sold: int = 0, units_returned: int = 0, **overrides) -> dict:
    defaults = {
        "format_id": format_id,
        "units_sold": units_sold,
        "units_returned": units_returned,
    }
    defaults.update(overrides)
    return defaults


def create_subsidiary_right_payload(
    right_type: str = "FOREIGN", proceeds_cents: int = 1000000, author_share_pct: float = 0.5, **overrides
) -> dict:
    defaults = {
        "right_type": right_type,
        "proceeds_cents": proceeds_cents,
        "author_share_pct": author_share_pct,
    }
    defaults.update(overrides)
    return defaults
