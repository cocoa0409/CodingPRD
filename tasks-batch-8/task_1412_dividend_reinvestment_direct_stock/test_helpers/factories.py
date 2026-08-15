"""Payload factories — one per entity, input fields only."""
from .constants import (
    DEFAULT_AVG5_PRICE,
    DEFAULT_CLOSING_PRICE,
    DEFAULT_DIVIDEND_AMOUNT_PER_SHARE,
    DEFAULT_PAYABLE_DATE,
    DEFAULT_PLAN_CONFIG,
    DEFAULT_RECORD_DATE,
    DEFAULT_WINDOW_CLOSES,
    DEFAULT_WINDOW_OPENS,
    DEFAULT_WINDOW_PRICE_CENTS,
)


def create_plan_payload(**overrides) -> dict:
    defaults = {
        "issuer_name": "Acme Corp",
        "ticker": "ACME",
        "name": "ACME DRIP",
    }
    defaults.update(DEFAULT_PLAN_CONFIG)
    defaults.update(overrides)
    return defaults


def create_participant_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Pat Example",
        "email": "pat@example.com",
    }
    defaults.update(overrides)
    return defaults


def create_enrollment_payload(participant_id, election="FULL_REINVEST",
                              reinvest_pct=None, **overrides) -> dict:
    payload = {"participant_id": participant_id, "election": election}
    if reinvest_pct is not None:
        payload["reinvest_pct"] = reinvest_pct
    payload.update(overrides)
    return payload


def create_deposit_payload(quantity=100.0, cost_per_share_cents=1500,
                           **overrides) -> dict:
    payload = {"quantity": quantity, "cost_per_share_cents": cost_per_share_cents}
    payload.update(overrides)
    return payload


def create_dividend_payload(amount_per_share_cents=DEFAULT_DIVIDEND_AMOUNT_PER_SHARE,
                            record_date=DEFAULT_RECORD_DATE,
                            payable_date=DEFAULT_PAYABLE_DATE,
                            **overrides) -> dict:
    payload = {
        "amount_per_share_cents": amount_per_share_cents,
        "record_date": record_date,
        "payable_date": payable_date,
    }
    payload.update(overrides)
    return payload


def create_price_payload(closing_price_cents=DEFAULT_CLOSING_PRICE,
                         avg5_price_cents=DEFAULT_AVG5_PRICE,
                         **overrides) -> dict:
    payload = {
        "closing_price_cents": closing_price_cents,
        "avg5_price_cents": avg5_price_cents,
    }
    payload.update(overrides)
    return payload


def create_window_payload(opens_at=DEFAULT_WINDOW_OPENS,
                          closes_at=DEFAULT_WINDOW_CLOSES,
                          price_cents=DEFAULT_WINDOW_PRICE_CENTS,
                          **overrides) -> dict:
    payload = {
        "opens_at": opens_at,
        "closes_at": closes_at,
        "price_cents": price_cents,
    }
    payload.update(overrides)
    return payload


def create_order_payload(enrollment_id, amount_cents, **overrides) -> dict:
    payload = {"enrollment_id": enrollment_id, "amount_cents": amount_cents}
    payload.update(overrides)
    return payload


def create_notice_payload(notice_type="MODIFICATION",
                          effective_at="2026-08-20T00:00:00Z",
                          message="Plan communication",
                          **overrides) -> dict:
    payload = {
        "notice_type": notice_type,
        "effective_at": effective_at,
        "message": message,
    }
    payload.update(overrides)
    return payload


def create_transfer_payload(transfer_type="GIFT", quantity=1.0,
                            recipient_enrollment_id=None,
                            recipient_name=None,
                            recipient_address=None,
                            **overrides) -> dict:
    payload = {"transfer_type": transfer_type, "quantity": quantity}
    if recipient_enrollment_id is not None:
        payload["recipient_enrollment_id"] = recipient_enrollment_id
    if recipient_name is not None:
        payload["recipient_name"] = recipient_name
    if recipient_address is not None:
        payload["recipient_address"] = recipient_address
    payload.update(overrides)
    return payload
