"""Payload factories — one per creatable resource, input fields only.

Only fields the client supplies (source: input) appear here. System- and
computed-fields are never sent.
"""


def create_merchant_payload(**overrides) -> dict:
    """POST /merchants. Only legal_name is required; settlement_currency
    defaults to USD server-side (PRD §3.1)."""
    payload = {"legal_name": "Acme Retail"}
    payload.update(overrides)
    return payload


def create_card_program_payload(merchant_id: str, **overrides) -> dict:
    """POST /card-programs. merchant_id and name are required; the rest carry
    server-side defaults (PRD §3.2)."""
    payload = {"merchant_id": merchant_id, "name": "Standard Program"}
    payload.update(overrides)
    return payload


def create_incentive_campaign_payload(card_program_id: str, starts_at: str,
                                       ends_at: str, **overrides) -> dict:
    """POST /incentive-campaigns. All of card_program_id, name, bonus_bps,
    starts_at, ends_at are required (PRD §3.2)."""
    payload = {
        "card_program_id": card_program_id,
        "name": "Campaign",
        "bonus_bps": 1000,
        "starts_at": starts_at,
        "ends_at": ends_at,
    }
    payload.update(overrides)
    return payload


def create_card_batch_payload(card_program_id: str, card_count: int,
                              unit_load_cents: int, channel: str = "DIGITAL",
                              **overrides) -> dict:
    """POST /card-batches. card_program_id, channel, card_count, unit_load_cents
    are required; purpose defaults to RETAIL (PRD §3.3)."""
    payload = {
        "card_program_id": card_program_id,
        "channel": channel,
        "card_count": card_count,
        "unit_load_cents": unit_load_cents,
    }
    payload.update(overrides)
    return payload


def create_velocity_rule_payload(card_program_id: str, **overrides) -> dict:
    """POST /velocity-rules. Only card_program_id is required; window_hours,
    max_count, max_amount_cents, enabled carry defaults (PRD §3.2)."""
    payload = {"card_program_id": card_program_id}
    payload.update(overrides)
    return payload


def create_settlement_batch_payload(merchant_id: str, period_start: str,
                                    period_end: str, expected_merchant_version: int,
                                    **overrides) -> dict:
    """POST /settlement-batches. All fields required, including the OCC field
    expected_merchant_version (PRD §2.9, §3.7)."""
    payload = {
        "merchant_id": merchant_id,
        "period_start": period_start,
        "period_end": period_end,
        "expected_merchant_version": expected_merchant_version,
    }
    payload.update(overrides)
    return payload


def create_escheat_report_payload(merchant_id: str, jurisdiction: str,
                                  period_start: str, period_end: str,
                                  **overrides) -> dict:
    """POST /escheat-reports. All fields required (PRD §3.8)."""
    payload = {
        "merchant_id": merchant_id,
        "jurisdiction": jurisdiction,
        "period_start": period_start,
        "period_end": period_end,
    }
    payload.update(overrides)
    return payload


def redeem_payload(amount_cents: int) -> dict:
    """POST /gift-cards/{id}/redeem body (PRD §3.4)."""
    return {"amount_cents": amount_cents}


def reload_payload(amount_cents: int) -> dict:
    """POST /gift-cards/{id}/reload body (PRD §3.4)."""
    return {"amount_cents": amount_cents}


def set_clock_payload(to_iso8601: str) -> dict:
    """POST /_clock/set_current_utc body (PRD §2.4)."""
    return {"to_iso8601": to_iso8601}
