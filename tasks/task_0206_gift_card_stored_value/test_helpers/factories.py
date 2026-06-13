"""Payload factories — one per entity, input fields only.

Only fields the client supplies (source: input) appear here. Computed/system fields
(balances, status, version, net_invoice_cents, transferred_amount_cents, ...) are never
sent by the client.
"""

DEFAULTS = {
    "PROGRAM_NAME": "Acme",
    "STATE_CODE": "FL",
    "B2B_DISCOUNT_PCT": 0.035,
}


def create_program_payload(**overrides) -> dict:
    """POST /v1/programs — only `name` is required; all other fields have server defaults."""
    payload = {"name": DEFAULTS["PROGRAM_NAME"]}
    payload.update(overrides)
    return payload


def create_state_rule_payload(program_id: str, state_code: str = "FL",
                              expiration_allowed: bool = True,
                              dormancy_fee_allowed: bool = False,
                              breakage_policy: str = "RECOGNIZE",
                              **overrides) -> dict:
    """POST /v1/state-rules. breakage_policy is required (RECOGNIZE | ESCHEAT)."""
    payload = {
        "program_id": program_id,
        "state_code": state_code,
        "expiration_allowed": expiration_allowed,
        "dormancy_fee_allowed": dormancy_fee_allowed,
        "breakage_policy": breakage_policy,
    }
    payload.update(overrides)
    return payload


def create_campaign_payload(program_id: str, window_start: str, window_end: str,
                            name: str = "Winter", bonus_pct: float = 0.10,
                            **overrides) -> dict:
    """POST /v1/campaigns. Half-open window [window_start, window_end)."""
    payload = {
        "program_id": program_id,
        "name": name,
        "bonus_pct": bonus_pct,
        "window_start": window_start,
        "window_end": window_end,
    }
    payload.update(overrides)
    return payload


def create_customer_payload(email: str = "cust@x.com", full_name: str = "Cust",
                            residence_state_code: str = "FL", **overrides) -> dict:
    """POST /v1/customers. is_corporate defaults to false server-side."""
    payload = {
        "email": email,
        "full_name": full_name,
        "residence_state_code": residence_state_code,
    }
    payload.update(overrides)
    return payload


def create_card_payload(program_id: str, form_factor: str = "DIGITAL",
                        state_code: str = "FL", **overrides) -> dict:
    """POST /v1/cards. owner_customer_id is optional."""
    payload = {
        "program_id": program_id,
        "form_factor": form_factor,
        "state_code": state_code,
    }
    payload.update(overrides)
    return payload


def activate_card_payload(initial_load_cents: int, **overrides) -> dict:
    """POST /v1/cards/{id}/activate."""
    payload = {"initial_load_cents": initial_load_cents}
    payload.update(overrides)
    return payload


def reload_card_payload(amount_cents: int, **overrides) -> dict:
    """POST /v1/cards/{id}/reload."""
    payload = {"amount_cents": amount_cents}
    payload.update(overrides)
    return payload


def create_hold_payload(card_id: str, amount_cents: int, **overrides) -> dict:
    """POST /v1/holds. amount_cents must be > 0."""
    payload = {"card_id": card_id, "amount_cents": amount_cents}
    payload.update(overrides)
    return payload


def create_redemption_payload(program_id: str, requested_amount_cents: int,
                              card_id_order: list, **overrides) -> dict:
    """POST /v1/redemptions. customer_id optional."""
    payload = {
        "program_id": program_id,
        "requested_amount_cents": requested_amount_cents,
        "card_id_order": card_id_order,
    }
    payload.update(overrides)
    return payload


def settle_redemption_payload(expected_redemption_version: int, **overrides) -> dict:
    """POST /v1/redemptions/{id}/settle."""
    payload = {"expected_redemption_version": expected_redemption_version}
    payload.update(overrides)
    return payload


def create_bulk_order_payload(program_id: str, buyer_customer_id: str,
                              card_count: int, face_value_cents: int,
                              state_code: str = "FL", **overrides) -> dict:
    """POST /v1/bulk-orders."""
    payload = {
        "program_id": program_id,
        "buyer_customer_id": buyer_customer_id,
        "card_count": card_count,
        "face_value_cents": face_value_cents,
        "state_code": state_code,
    }
    payload.update(overrides)
    return payload


def create_replacement_payload(old_card_id: str, reason: str = "FRAUD", **overrides) -> dict:
    """POST /v1/replacements. reason is FRAUD | LOST | DAMAGED."""
    payload = {"old_card_id": old_card_id, "reason": reason}
    payload.update(overrides)
    return payload


def approve_replacement_payload(expected_old_card_version: int, **overrides) -> dict:
    """POST /v1/replacements/{id}/approve."""
    payload = {"expected_old_card_version": expected_old_card_version}
    payload.update(overrides)
    return payload


def create_refund_payload(card_id: str, requested_refund_cents: int,
                          redemption_id: str = None, **overrides) -> dict:
    """POST /v1/refunds. redemption_id optional."""
    payload = {"card_id": card_id, "requested_refund_cents": requested_refund_cents}
    if redemption_id is not None:
        payload["redemption_id"] = redemption_id
    payload.update(overrides)
    return payload


def resubmit_refund_payload(requested_refund_cents: int, **overrides) -> dict:
    """POST /v1/refunds/{id}/resubmit."""
    payload = {"requested_refund_cents": requested_refund_cents}
    payload.update(overrides)
    return payload


def create_dormancy_waiver_payload(card_id: str, window_start: str, window_end: str,
                                   **overrides) -> dict:
    """POST /v1/dormancy-waivers. Closed interval [window_start, window_end]."""
    payload = {
        "card_id": card_id,
        "window_start": window_start,
        "window_end": window_end,
    }
    payload.update(overrides)
    return payload
