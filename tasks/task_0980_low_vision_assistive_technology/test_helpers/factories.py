"""Payload factories — one per entity, input fields only."""
import itertools

_counter = itertools.count(1)


def _seq() -> int:
    return next(_counter)


DEFAULTS = {
    "DOB": "1960-01-01",
    "VALID_FROM": "2026-05-01T00:00:00Z",
    "VALID_UNTIL": "2026-12-31T23:59:59Z",
    "SERVICE_DATE": "2026-05-10T00:00:00Z",
    "SESSION_START": "2026-05-04T10:00:00Z",
    "SESSION_END": "2026-05-04T11:00:00Z",
}


def create_client_payload(**overrides) -> dict:
    defaults = {
        "full_name": f"Test Client {_seq()}",
        "date_of_birth": DEFAULTS["DOB"],
    }
    defaults.update(overrides)
    return defaults


def create_referral_payload(client_id, **overrides) -> dict:
    defaults = {
        "client_id": client_id,
        "source_type": "SELF",
        "referring_party": "self",
    }
    defaults.update(overrides)
    return defaults


def create_evaluation_payload(client_id, referral_id, expected_client_version, **overrides) -> dict:
    defaults = {
        "client_id": client_id,
        "referral_id": referral_id,
        "expected_client_version": expected_client_version,
        "acuity_score": 60,
        "contrast_score": 60,
        "field_loss_pct": 20,
        "recommended_category": "MAGNIFIER",
    }
    defaults.update(overrides)
    return defaults


def create_device_model_payload(**overrides) -> dict:
    defaults = {
        "name": f"Model {_seq()}",
        "category": "MAGNIFIER",
        "list_price_cents": 25000,
    }
    defaults.update(overrides)
    return defaults


def create_device_unit_payload(device_model_id, **overrides) -> dict:
    defaults = {
        "device_model_id": device_model_id,
        "serial_no": f"SN-{_seq()}-{_seq()}",
        "condition": "NEW",
    }
    defaults.update(overrides)
    return defaults


def create_device_order_payload(client_id, evaluation_id, device_model_id, **overrides) -> dict:
    defaults = {
        "client_id": client_id,
        "evaluation_id": evaluation_id,
        "device_model_id": device_model_id,
        "fulfillment_type": "PURCHASE",
    }
    defaults.update(overrides)
    return defaults


def create_training_plan_payload(client_id, device_order_id, **overrides) -> dict:
    defaults = {
        "client_id": client_id,
        "device_order_id": device_order_id,
        "total_sessions": 3,
    }
    defaults.update(overrides)
    return defaults


def create_training_session_payload(**overrides) -> dict:
    defaults = {
        "instructor_user_id": "inst-1",
        "scheduled_start": DEFAULTS["SESSION_START"],
        "scheduled_end": DEFAULTS["SESSION_END"],
    }
    defaults.update(overrides)
    return defaults


def create_funding_authorization_payload(client_id, **overrides) -> dict:
    defaults = {
        "client_id": client_id,
        "payer_type": "INSURANCE",
        "payer_ref": f"POL-{_seq()}",
        "authorized_amount_cents": 50000,
        "valid_from": DEFAULTS["VALID_FROM"],
        "valid_until": DEFAULTS["VALID_UNTIL"],
    }
    defaults.update(overrides)
    return defaults


def claim_line(line_type="DEVICE", unit_price_cents=1000, quantity=1) -> dict:
    return {"line_type": line_type, "unit_price_cents": unit_price_cents, "quantity": quantity}


def create_claim_payload(funding_authorization_id, device_order_id, **overrides) -> dict:
    defaults = {
        "funding_authorization_id": funding_authorization_id,
        "device_order_id": device_order_id,
        "service_date": DEFAULTS["SERVICE_DATE"],
        "lines": [claim_line()],
    }
    defaults.update(overrides)
    return defaults


def create_repair_ticket_payload(device_unit_id, **overrides) -> dict:
    defaults = {
        "device_unit_id": device_unit_id,
        "issue_description": "needs repair",
    }
    defaults.update(overrides)
    return defaults


def create_subscription_payload(client_id, device_model_id, **overrides) -> dict:
    defaults = {
        "client_id": client_id,
        "device_model_id": device_model_id,
        "period_start": "2026-05-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_outcome_assessment_payload(client_id, **overrides) -> dict:
    defaults = {
        "client_id": client_id,
        "kind": "BASELINE",
        "task_score": 50,
        "satisfaction_score": 50,
    }
    defaults.update(overrides)
    return defaults
