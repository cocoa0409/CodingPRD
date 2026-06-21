"""Payload factories — one per create/action endpoint, input fields only."""


def create_flat_fee_plan_payload(**overrides) -> dict:
    """FLAT fee plan: requires flat_pct_bps + flat_fixed_cents."""
    defaults = {
        "name": "Flat Plan",
        "pricing_model": "FLAT",
        "flat_pct_bps": 290,
        "flat_fixed_cents": 30,
        "chargeback_fee_cents": 1500,
    }
    defaults.update(overrides)
    return defaults


def create_interchange_plus_fee_plan_payload(**overrides) -> dict:
    """INTERCHANGE_PLUS fee plan: requires markup_pct_bps + markup_fixed_cents."""
    defaults = {
        "name": "IcPlus Plan",
        "pricing_model": "INTERCHANGE_PLUS",
        "markup_pct_bps": 30,
        "markup_fixed_cents": 10,
        "volume_tier_threshold_cents": 1000000,
        "discounted_markup_pct_bps": 20,
        "chargeback_fee_cents": 1500,
    }
    defaults.update(overrides)
    return defaults


def create_merchant_payload(fee_plan_id, **overrides) -> dict:
    defaults = {
        "legal_name": "Test Merchant Co",
        "mcc": "5812",
        "fee_plan_id": fee_plan_id,
        "requested_monthly_volume_cents": 100000,
    }
    defaults.update(overrides)
    return defaults


def approve_review_payload(assigned_risk_band="LOW", **overrides) -> dict:
    defaults = {"assigned_risk_band": assigned_risk_band}
    defaults.update(overrides)
    return defaults


def create_charge_payload(auth_amount_cents=10000, card_last4="4242", **overrides) -> dict:
    defaults = {
        "auth_amount_cents": auth_amount_cents,
        "card_last4": card_last4,
    }
    defaults.update(overrides)
    return defaults


def capture_payload(amount_cents, **overrides) -> dict:
    defaults = {"amount_cents": amount_cents}
    defaults.update(overrides)
    return defaults


def create_refund_payload(amount_cents, **overrides) -> dict:
    defaults = {"amount_cents": amount_cents}
    defaults.update(overrides)
    return defaults


def create_dispute_payload(disputed_amount_cents, **overrides) -> dict:
    defaults = {"disputed_amount_cents": disputed_amount_cents}
    defaults.update(overrides)
    return defaults


def resolve_payload(outcome, **overrides) -> dict:
    defaults = {"outcome": outcome}
    defaults.update(overrides)
    return defaults


def create_settlement_batch_payload(business_date, **overrides) -> dict:
    defaults = {"business_date": business_date}
    defaults.update(overrides)
    return defaults


def settle_batch_payload(expected_merchant_version, **overrides) -> dict:
    defaults = {"expected_merchant_version": expected_merchant_version}
    defaults.update(overrides)
    return defaults


def create_payout_payload(amount_cents, scheduled_for, **overrides) -> dict:
    defaults = {
        "amount_cents": amount_cents,
        "scheduled_for": scheduled_for,
    }
    defaults.update(overrides)
    return defaults


def generate_tax_1099k_payload(tax_year, **overrides) -> dict:
    defaults = {"tax_year": tax_year}
    defaults.update(overrides)
    return defaults


def emit_webhook_event_payload(event_type, source_id, idempotency_key, **overrides) -> dict:
    defaults = {
        "event_type": event_type,
        "source_id": source_id,
        "idempotency_key": idempotency_key,
    }
    defaults.update(overrides)
    return defaults


def set_clock_payload(to_iso8601, **overrides) -> dict:
    defaults = {"to_iso8601": to_iso8601}
    defaults.update(overrides)
    return defaults
