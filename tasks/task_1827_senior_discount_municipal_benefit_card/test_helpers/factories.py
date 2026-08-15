"""Payload factories — one per creatable resource, input fields only (PRD §3)."""
from .constants import TEST_DEFAULTS


def create_application_payload(kind="INITIAL", applicant_full_name="Test Senior",
                               date_of_birth=TEST_DEFAULTS["DATE_OF_BIRTH"],
                               annual_income_cents=TEST_DEFAULTS["ANNUAL_INCOME_CENTS"],
                               residency_address=TEST_DEFAULTS["RESIDENCY_ADDRESS"],
                               cardholder_id=None, **overrides):
    payload = {
        "kind": kind,
        "applicant_full_name": applicant_full_name,
        "date_of_birth": date_of_birth,
        "annual_income_cents": annual_income_cents,
        "residency_address": residency_address,
    }
    if cardholder_id is not None:
        payload["cardholder_id"] = cardholder_id
    payload.update(overrides)
    return payload


def create_document_payload(document_type="PROOF_OF_AGE",
                            document_reference="DOC-REF-1", **overrides):
    payload = {
        "document_type": document_type,
        "document_reference": document_reference,
    }
    payload.update(overrides)
    return payload


def create_merchant_payload(name="Test Merchant",
                            reimbursement_rate_pct=TEST_DEFAULTS["MERCHANT_RATE_PCT"],
                            monthly_reimbursement_cap_cents=TEST_DEFAULTS["MERCHANT_MONTHLY_CAP_CENTS"],
                            **overrides):
    payload = {
        "name": name,
        "reimbursement_rate_pct": reimbursement_rate_pct,
        "monthly_reimbursement_cap_cents": monthly_reimbursement_cap_cents,
    }
    payload.update(overrides)
    return payload


def create_offer_payload(category="GROCERY",
                         discount_pct=TEST_DEFAULTS["OFFER_DISCOUNT_PCT"],
                         max_discount_cents=TEST_DEFAULTS["OFFER_MAX_DISCOUNT_CENTS"],
                         valid_from=TEST_DEFAULTS["OFFER_VALID_FROM"],
                         valid_until=TEST_DEFAULTS["OFFER_VALID_UNTIL"],
                         **overrides):
    payload = {
        "category": category,
        "discount_pct": discount_pct,
        "max_discount_cents": max_discount_cents,
        "valid_from": valid_from,
        "valid_until": valid_until,
    }
    payload.update(overrides)
    return payload


def create_fee_waiver_payload(waiver_type="TRANSIT_FARE",
                              start_date="2026-09-01",
                              end_date="2026-09-30", **overrides):
    payload = {
        "waiver_type": waiver_type,
        "start_date": start_date,
        "end_date": end_date,
    }
    payload.update(overrides)
    return payload


def create_usage_transaction_payload(card_id, merchant_id, category="GROCERY",
                                     purchase_amount_cents=100, **overrides):
    payload = {
        "card_id": card_id,
        "merchant_id": merchant_id,
        "category": category,
        "purchase_amount_cents": purchase_amount_cents,
    }
    payload.update(overrides)
    return payload


def create_program_fund_payload(fiscal_year=TEST_DEFAULTS["FUND_FISCAL_YEAR"],
                                allocated_cents=TEST_DEFAULTS["FUND_ALLOCATED_CENTS"],
                                **overrides):
    payload = {
        "fiscal_year": fiscal_year,
        "allocated_cents": allocated_cents,
    }
    payload.update(overrides)
    return payload
