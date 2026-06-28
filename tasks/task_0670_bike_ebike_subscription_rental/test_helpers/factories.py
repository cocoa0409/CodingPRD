"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "MODEL_NAME": "Std",
    "MODEL_CLASS": "STANDARD",
    "MONTHLY_FEE_CENTS": 8000,
    "DAILY_RATE_CENTS": 2000,
    "PURCHASE_PRICE_CENTS": 90000,
    "DEPOSIT_CENTS": 10000,
    "FLEET_SIZE": 5,
    "ACCOUNT_TYPE": "SUBSCRIBER",
    "DISPLAY_NAME": "Sam",
    "RENTAL_CAP": 1,
    "RENTAL_MODE": "MONTHLY",
    "RETURN_DUE_CLOCK": "2027-06-01T00:00:00Z",
    "ADDRESS": "1 A St",
    "WINDOW_START": "2026-06-01T08:00:00Z",
    "WINDOW_END": "2026-06-01T12:00:00Z",
    "ISSUE_TYPE": "BRAKE",
    "SEVERITY": "MINOR",
    "DESCRIPTION": "squeak",
}


def create_bike_model_payload(**overrides) -> dict:
    payload = {
        "name": DEFAULTS["MODEL_NAME"],
        "model_class": DEFAULTS["MODEL_CLASS"],
        "monthly_fee_cents": DEFAULTS["MONTHLY_FEE_CENTS"],
        "daily_rate_cents": DEFAULTS["DAILY_RATE_CENTS"],
        "purchase_price_cents": DEFAULTS["PURCHASE_PRICE_CENTS"],
        "deposit_cents": DEFAULTS["DEPOSIT_CENTS"],
        "fleet_size": DEFAULTS["FLEET_SIZE"],
    }
    payload.update(overrides)
    return payload


def create_bike_payload(model_id, serial_number="S-1", **overrides) -> dict:
    payload = {"model_id": model_id, "serial_number": serial_number}
    payload.update(overrides)
    return payload


def create_account_payload(**overrides) -> dict:
    payload = {
        "account_type": DEFAULTS["ACCOUNT_TYPE"],
        "display_name": DEFAULTS["DISPLAY_NAME"],
        "email": "sam@x.com",
        "rental_cap": DEFAULTS["RENTAL_CAP"],
    }
    payload.update(overrides)
    return payload


def create_rental_payload(account_id, model_id, expected_model_version, **overrides) -> dict:
    payload = {
        "account_id": account_id,
        "model_id": model_id,
        "rental_mode": DEFAULTS["RENTAL_MODE"],
        "return_due_clock": DEFAULTS["RETURN_DUE_CLOCK"],
        "expected_model_version": expected_model_version,
    }
    payload.update(overrides)
    return payload


def create_delivery_payload(rental_id, delivery_type="INITIAL", **overrides) -> dict:
    payload = {
        "rental_id": rental_id,
        "delivery_type": delivery_type,
        "address": DEFAULTS["ADDRESS"],
        "window_start_clock": DEFAULTS["WINDOW_START"],
        "window_end_clock": DEFAULTS["WINDOW_END"],
    }
    payload.update(overrides)
    return payload


def request_return_payload(return_address=DEFAULTS["ADDRESS"], **overrides) -> dict:
    payload = {"return_address": return_address}
    payload.update(overrides)
    return payload


def inspect_payload(bike_condition="GOOD", damage_charge_cents=0, cleaning_fee_cents=0, **overrides) -> dict:
    payload = {
        "bike_condition": bike_condition,
        "damage_charge_cents": damage_charge_cents,
        "cleaning_fee_cents": cleaning_fee_cents,
    }
    payload.update(overrides)
    return payload


def create_service_ticket_payload(rental_id, **overrides) -> dict:
    payload = {
        "rental_id": rental_id,
        "issue_type": DEFAULTS["ISSUE_TYPE"],
        "severity": DEFAULTS["SEVERITY"],
        "description": DEFAULTS["DESCRIPTION"],
    }
    payload.update(overrides)
    return payload


def resolve_ticket_payload(resolution_note="resolved", **overrides) -> dict:
    payload = {"resolution_note": resolution_note}
    payload.update(overrides)
    return payload


def create_coverage_claim_payload(rental_id, claim_type="DAMAGE",
                                  incident_clock="2026-06-02T00:00:00Z",
                                  claimed_amount_cents=20000, **overrides) -> dict:
    payload = {
        "rental_id": rental_id,
        "claim_type": claim_type,
        "incident_clock": incident_clock,
        "claimed_amount_cents": claimed_amount_cents,
    }
    payload.update(overrides)
    return payload


def approve_claim_payload(approved_payout_cents, **overrides) -> dict:
    payload = {"approved_payout_cents": approved_payout_cents}
    payload.update(overrides)
    return payload


def create_buyout_offer_payload(expires_at_clock="2026-12-01T00:00:00Z", **overrides) -> dict:
    payload = {"expires_at_clock": expires_at_clock}
    payload.update(overrides)
    return payload


def create_fleet_invoice_payload(cycle_index=0, **overrides) -> dict:
    payload = {"cycle_index": cycle_index}
    payload.update(overrides)
    return payload
