"""Payload factories — one per input resource, input fields only.

Field names are exactly as the PRD names them.
"""

DEFAULTS = {
    "CLIENT_NAME": "Acme Corp",
    "CLIENT_TYPE": "ORGANIZATION",
    "TIMEKEEPER_NAME": "Pat Partner",
    "ROLE_KIND": "PARTNER",
    "STANDARD_RATE_CENTS": 50000,
    "MATTER_TITLE": "Acme Matter",
    "ADVERSE_NAME": "Opposing Co",
    "ISSUE_DATE": "2026-06-01T00:00:00Z",
    "NET_TERMS_DAYS": 30,
    "WORKED_AT": "2026-05-01T09:00:00Z",
    "MINUTES": 60,
    "TASK_CODE": "L110",
    "ACTIVITY_CODE": "A101",
    "EXPENSE_CODE": "E101",
    "PAYMENT_METHOD": "CHECK",
    "TRUST_ACCOUNT_NAME": "IOLTA Pool",
}


def create_client_payload(**overrides) -> dict:
    payload = {
        "display_name": DEFAULTS["CLIENT_NAME"],
        "client_type": DEFAULTS["CLIENT_TYPE"],
    }
    payload.update(overrides)
    return payload


def create_timekeeper_payload(**overrides) -> dict:
    payload = {
        "full_name": DEFAULTS["TIMEKEEPER_NAME"],
        "role_kind": DEFAULTS["ROLE_KIND"],
        "standard_rate_cents": DEFAULTS["STANDARD_RATE_CENTS"],
    }
    payload.update(overrides)
    return payload


def create_billing_code_payload(code, kind, label, **overrides) -> dict:
    payload = {"code": code, "kind": kind, "label": label}
    payload.update(overrides)
    return payload


def create_matter_payload(client_id, responsible_timekeeper_id, **overrides) -> dict:
    payload = {
        "client_id": client_id,
        "responsible_timekeeper_id": responsible_timekeeper_id,
        "title": DEFAULTS["MATTER_TITLE"],
    }
    payload.update(overrides)
    return payload


def create_rate_override_payload(role_kind, rate_cents, **overrides) -> dict:
    payload = {"role_kind": role_kind, "rate_cents": rate_cents}
    payload.update(overrides)
    return payload


def create_conflict_check_payload(adverse_party_name=None, **overrides) -> dict:
    payload = {"adverse_party_name": adverse_party_name or DEFAULTS["ADVERSE_NAME"]}
    payload.update(overrides)
    return payload


def create_time_entry_payload(matter_id, timekeeper_id, **overrides) -> dict:
    payload = {
        "matter_id": matter_id,
        "timekeeper_id": timekeeper_id,
        "worked_at": DEFAULTS["WORKED_AT"],
        "minutes": DEFAULTS["MINUTES"],
        "utbms_task_code": DEFAULTS["TASK_CODE"],
        "utbms_activity_code": DEFAULTS["ACTIVITY_CODE"],
    }
    payload.update(overrides)
    return payload


def create_expense_entry_payload(matter_id, amount_cents, **overrides) -> dict:
    payload = {
        "matter_id": matter_id,
        "utbms_expense_code": DEFAULTS["EXPENSE_CODE"],
        "amount_cents": amount_cents,
    }
    payload.update(overrides)
    return payload


def create_invoice_payload(matter_id, **overrides) -> dict:
    payload = {
        "matter_id": matter_id,
        "issue_date": DEFAULTS["ISSUE_DATE"],
        "net_terms_days": DEFAULTS["NET_TERMS_DAYS"],
    }
    payload.update(overrides)
    return payload


def create_payment_payload(amount_cents, method=None, **overrides) -> dict:
    payload = {"amount_cents": amount_cents, "method": method or DEFAULTS["PAYMENT_METHOD"]}
    payload.update(overrides)
    return payload


def trust_sweep_payload(amount_cents, client_trust_ledger_id, initiated_by_user_id,
                        expected_invoice_version, **overrides) -> dict:
    payload = {
        "amount_cents": amount_cents,
        "client_trust_ledger_id": client_trust_ledger_id,
        "initiated_by_user_id": initiated_by_user_id,
        "expected_invoice_version": expected_invoice_version,
    }
    payload.update(overrides)
    return payload


def write_off_payload(amount_cents, **overrides) -> dict:
    payload = {"amount_cents": amount_cents}
    payload.update(overrides)
    return payload


def create_trust_account_payload(**overrides) -> dict:
    payload = {"name": DEFAULTS["TRUST_ACCOUNT_NAME"]}
    payload.update(overrides)
    return payload


def create_trust_ledger_payload(trust_account_id, client_id, **overrides) -> dict:
    payload = {
        "trust_account_id": trust_account_id,
        "client_id": client_id,
        "retainer_floor_cents": 0,
    }
    payload.update(overrides)
    return payload


def create_trust_transaction_payload(client_trust_ledger_id, kind, amount_cents,
                                     initiated_by_user_id, **overrides) -> dict:
    payload = {
        "client_trust_ledger_id": client_trust_ledger_id,
        "kind": kind,
        "amount_cents": amount_cents,
        "initiated_by_user_id": initiated_by_user_id,
    }
    payload.update(overrides)
    return payload


def create_retainer_hold_payload(client_trust_ledger_id, amount_cents,
                                 hold_start_at, hold_end_at, **overrides) -> dict:
    payload = {
        "client_trust_ledger_id": client_trust_ledger_id,
        "amount_cents": amount_cents,
        "hold_start_at": hold_start_at,
        "hold_end_at": hold_end_at,
    }
    payload.update(overrides)
    return payload


def set_clock_payload(to_iso8601, **overrides) -> dict:
    payload = {"to_iso8601": to_iso8601}
    payload.update(overrides)
    return payload
