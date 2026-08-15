"""Payload factories — one per creatable resource, input fields only."""
from .constants import (
    DEFAULT_LOSS_DATE,
    DEFAULT_PAYABLE_DATE,
    DEFAULT_PRICE_CENTS,
    DEFAULT_RECORD_DATE,
)


def create_issuer_payload(**overrides) -> dict:
    defaults = {
        "name": "Acme Corp",
        "cusip": "000000001",
        "ticker": "ACME",
        "shares_outstanding": 100,
        "par_value_cents": 1,
        "current_market_price_cents": DEFAULT_PRICE_CENTS,
    }
    defaults.update(overrides)
    return defaults


def create_account_payload(**overrides) -> dict:
    defaults = {
        "holder_name": "Test Holder",
        "address_line1": "1 Main St",
        "city": "Tulsa",
        "state_code": "OK",
        "postal_code": "74101",
        "country_code": "US",
        "tax_id": "000-00-0000",
    }
    defaults.update(overrides)
    return defaults


def create_position_payload(issuer_id, book_entry_shares, **overrides) -> dict:
    payload = {"issuer_id": issuer_id, "book_entry_shares": book_entry_shares}
    payload.update(overrides)
    return payload


def withdrawal_payload(share_quantity, **overrides) -> dict:
    payload = {"share_quantity": share_quantity}
    payload.update(overrides)
    return payload


def report_lost_payload(loss_date=DEFAULT_LOSS_DATE) -> dict:
    return {"loss_date": loss_date}


def post_bond_payload(bond_variant, premium_paid_cents) -> dict:
    return {"bond_variant": bond_variant, "premium_paid_cents": premium_paid_cents}


def transfer_request_payload(from_account_id, to_account_id, issuer_id,
                             share_quantity, expected_account_version,
                             source_certificate_id=None, **overrides) -> dict:
    payload = {
        "from_account_id": from_account_id,
        "to_account_id": to_account_id,
        "issuer_id": issuer_id,
        "share_quantity": share_quantity,
        "expected_account_version": expected_account_version,
    }
    if source_certificate_id is not None:
        payload["source_certificate_id"] = source_certificate_id
    payload.update(overrides)
    return payload


def medallion_payload(medallion_reference="MED-1", coverage_cents=0) -> dict:
    return {"medallion_reference": medallion_reference,
            "coverage_cents": coverage_cents}


def deficiency_payload(deficiency_reason="paperwork deficient") -> dict:
    return {"deficiency_reason": deficiency_reason}


def declaration_payload(issuer_id, record_date=DEFAULT_RECORD_DATE,
                        payable_date=DEFAULT_PAYABLE_DATE,
                        amount_per_share_millicents=500, **overrides) -> dict:
    payload = {
        "issuer_id": issuer_id,
        "record_date": record_date,
        "payable_date": payable_date,
        "amount_per_share_millicents": amount_per_share_millicents,
    }
    payload.update(overrides)
    return payload


def legend_request_payload(position_id, account_id, share_quantity,
                           acquisition_date, expected_position_version,
                           rule_basis="RULE_144", **overrides) -> dict:
    payload = {
        "position_id": position_id,
        "account_id": account_id,
        "share_quantity": share_quantity,
        "rule_basis": rule_basis,
        "acquisition_date": acquisition_date,
        "expected_position_version": expected_position_version,
    }
    payload.update(overrides)
    return payload


def opinion_payload(counsel_opinion_reference="OP-1") -> dict:
    return {"counsel_opinion_reference": counsel_opinion_reference}


def freeze_window_payload(start_date, end_date, reason="freeze") -> dict:
    return {"start_date": start_date, "end_date": end_date, "reason": reason}


def inquiry_payload(account_id, channel="EMAIL", subject="question") -> dict:
    return {"account_id": account_id, "channel": channel, "subject": subject}


def answer_payload(answer_text="answer") -> dict:
    return {"answer_text": answer_text}
