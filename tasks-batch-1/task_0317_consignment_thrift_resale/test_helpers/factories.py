"""Payload factories — one per entity, input fields only.

Field names are PRD-exact. Only fields the client supplies appear here; all
system/computed fields are omitted.
"""

# A standard single-tier (age-0, no discount) schedule with the default floor.
DEFAULT_TIERS = [{"min_age_days": 0, "discount_pct": 0.0}]


def create_consignor_payload(**overrides) -> dict:
    defaults = {"full_name": "Test Consignor", "email": "consignor@example.com"}
    defaults.update(overrides)
    return defaults


def create_markdown_schedule_payload(**overrides) -> dict:
    defaults = {
        "name": "Standard Schedule",
        "tiers": [dict(t) for t in DEFAULT_TIERS],
        "base_floor_pct": 0.30,
    }
    defaults.update(overrides)
    return defaults


def create_agreement_payload(consignor_id: str, markdown_schedule_id: str, **overrides) -> dict:
    """Required: consignor_id, markdown_schedule_id, split_pct (defaulted to 0.50).
    Optional behavioral terms (split_basis, unsold_disposition, return_window_days,
    payout_method) are left out unless overridden so server defaults apply."""
    defaults = {
        "consignor_id": consignor_id,
        "markdown_schedule_id": markdown_schedule_id,
        "split_pct": 0.50,
    }
    defaults.update(overrides)
    return defaults


def create_intake_batch_payload(agreement_id: str, **overrides) -> dict:
    defaults = {"agreement_id": agreement_id}
    defaults.update(overrides)
    return defaults


def create_item_payload(batch_id: str, **overrides) -> dict:
    """Required: batch_id, title. Optional: requires_authentication (defaults false)."""
    defaults = {"batch_id": batch_id, "title": "Test Garment"}
    defaults.update(overrides)
    return defaults


def grade_payload(decision: str, expected_item_version: int, **overrides) -> dict:
    """decision is ACCEPT or REJECT; ACCEPT requires list_price_cents."""
    defaults = {"decision": decision, "expected_item_version": expected_item_version}
    defaults.update(overrides)
    return defaults


def grade_accept_payload(list_price_cents: int, expected_item_version: int, **overrides) -> dict:
    defaults = {
        "decision": "ACCEPT",
        "list_price_cents": list_price_cents,
        "expected_item_version": expected_item_version,
    }
    defaults.update(overrides)
    return defaults


def create_authentication_review_payload(item_id: str, **overrides) -> dict:
    defaults = {"item_id": item_id}
    defaults.update(overrides)
    return defaults


def verdict_payload(verdict: str, **overrides) -> dict:
    """verdict is AUTHENTIC or COUNTERFEIT; optional verdict_note."""
    defaults = {"verdict": verdict}
    defaults.update(overrides)
    return defaults


def create_sale_payload(item_ids=None, lines=None, **overrides) -> dict:
    """`lines` is an array of {item_id, sold_price_cents?}. Pass either explicit
    `lines` or a list of `item_ids` (each becomes a line with default pricing)."""
    if lines is None:
        lines = [{"item_id": iid} for iid in (item_ids or [])]
    defaults = {"lines": lines, "payment_method": "CARD"}
    defaults.update(overrides)
    return defaults


def create_settlement_payload(business_date: str, **overrides) -> dict:
    defaults = {"business_date": business_date}
    defaults.update(overrides)
    return defaults


def finalize_settlement_payload(expected_settlement_version: int, **overrides) -> dict:
    defaults = {"expected_settlement_version": expected_settlement_version}
    defaults.update(overrides)
    return defaults


def redeem_payload(amount_cents: int, **overrides) -> dict:
    defaults = {"amount_cents": amount_cents}
    defaults.update(overrides)
    return defaults
