"""Payload factories — input fields only (PRD §3)."""
from .constants import BRANCH_DEFAULTS


def create_branch_payload(**overrides):
    payload = dict(BRANCH_DEFAULTS)
    payload.update(overrides)
    return payload


def create_teller_payload(display_name="Teller One", **overrides):
    payload = {"display_name": display_name}
    payload.update(overrides)
    return payload


def create_account_payload(owner_name="Acct Owner", balance_cents=0, **overrides):
    payload = {"owner_name": owner_name, "balance_cents": balance_cents}
    payload.update(overrides)
    return payload


def transaction_payload(account_id, type_, amount_cents, **overrides):
    payload = {"account_id": account_id, "type": type_, "amount_cents": amount_cents}
    payload.update(overrides)
    return payload


def cash_order_payload(delivery_date, expected_branch_version, **overrides):
    payload = {"delivery_date": delivery_date,
               "expected_branch_version": expected_branch_version}
    payload.update(overrides)
    return payload


def teller_request_payload(type_, params):
    return {"type": type_, "params": params}


def instrument_params(account_id, instrument_type, amount_cents, fee_waived=False):
    return {"account_id": account_id, "instrument_type": instrument_type,
            "amount_cents": amount_cents, "fee_waived": fee_waived}


def fee_waiver_params(transaction_id):
    return {"transaction_id": transaction_id}


def over_limit_params(account_id, amount_cents, is_ctr_exempt=False):
    return {"account_id": account_id, "amount_cents": amount_cents,
            "is_ctr_exempt": is_ctr_exempt}


def audit_payload(type_, **overrides):
    payload = {"type": type_}
    payload.update(overrides)
    return payload
