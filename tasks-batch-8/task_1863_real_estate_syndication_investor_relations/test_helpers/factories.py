"""Payload factories — one per entity, input fields only (PRD §3)."""
import uuid

from .types import DocType

DEFAULTS = {
    "SYNDICATION_NAME": "Test Syndication",
    "SPONSOR_LEGAL_ENTITY": "Test Sponsor LLC",
    "PREFERRED_RETURN_PCT_ANNUAL": 0.08,
    "CARRIED_INTEREST_PCT": 0.20,
    "TAX_ID_LAST4": "0001",
    "INVESTOR_CLASS": "ACCREDITED",
    "PROPERTY_LEGAL_NAME": "Test Property LLC",
    "STREET_ADDRESS": "1 Test St",
    "ACQUISITION_PRICE_CENTS": 100_000_000,
    "OFFERING_NAME": "Test Offering",
    "TARGET_RAISE_CENTS": 100_000_000,
    "MIN_SUBSCRIPTION_CENTS": 10_000,
    "MAX_NON_ACCREDITED_COUNT": 35,
    "COMMITTED_CENTS": 5_000_000,
    "TOTAL_CALL_CENTS": 5_000_000,
    "DUE_DATE": "2027-01-01T00:00:00Z",
    "REPORT_YEAR": 2026,
    "REPORT_QUARTER": 1,
    "NOI_CENTS": 10_000_000,
    "OCCUPANCY_PCT": 0.95,
    "TOTAL_DISTRIBUTABLE_CENTS": 1_000_000,
    "GROSS_PROCEEDS_CENTS": 6_000_000,
    "DEBT_PAYOFF_CENTS": 1_000_000,
    "TAX_YEAR": 2026,
    "PREPARER_FIRM": "Test CPA LLP",
    "TRANSFER_CENTS": 1_000_000,
}


def create_syndication_payload(**overrides) -> dict:
    defaults = {
        "syndication_name": DEFAULTS["SYNDICATION_NAME"],
        "sponsor_legal_entity": DEFAULTS["SPONSOR_LEGAL_ENTITY"],
        "preferred_return_pct_annual": DEFAULTS["PREFERRED_RETURN_PCT_ANNUAL"],
        "carried_interest_pct": DEFAULTS["CARRIED_INTEREST_PCT"],
    }
    defaults.update(overrides)
    return defaults


def create_investor_payload(**overrides) -> dict:
    defaults = {
        "full_legal_name": "Test Investor",
        "tax_id_last4": DEFAULTS["TAX_ID_LAST4"],
        "email": f"inv-{uuid.uuid4().hex[:12]}@example.com",
        "investor_class": DEFAULTS["INVESTOR_CLASS"],
    }
    defaults.update(overrides)
    return defaults


def create_property_payload(**overrides) -> dict:
    defaults = {
        "property_legal_name": DEFAULTS["PROPERTY_LEGAL_NAME"],
        "street_address": DEFAULTS["STREET_ADDRESS"],
        "acquisition_price_cents": DEFAULTS["ACQUISITION_PRICE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_offering_payload(property_id, **overrides) -> dict:
    defaults = {
        "property_id": property_id,
        "offering_name": DEFAULTS["OFFERING_NAME"],
        "target_raise_cents": DEFAULTS["TARGET_RAISE_CENTS"],
        "min_subscription_cents": DEFAULTS["MIN_SUBSCRIPTION_CENTS"],
        "max_non_accredited_count": DEFAULTS["MAX_NON_ACCREDITED_COUNT"],
        "preferred_return_pct_annual": DEFAULTS["PREFERRED_RETURN_PCT_ANNUAL"],
        "carried_interest_pct": DEFAULTS["CARRIED_INTEREST_PCT"],
    }
    defaults.update(overrides)
    return defaults


def create_subscription_payload(investor_id, committed_cents=None, **overrides) -> dict:
    defaults = {
        "investor_id": investor_id,
        "committed_cents": (committed_cents if committed_cents is not None
                            else DEFAULTS["COMMITTED_CENTS"]),
    }
    defaults.update(overrides)
    return defaults


def create_document_payload(doc_type=None, **overrides) -> dict:
    defaults = {
        "doc_type": (doc_type if doc_type is not None else DocType.W9.value),
        "file_uri": f"s3://docs/{uuid.uuid4().hex[:12]}.pdf",
    }
    defaults.update(overrides)
    return defaults


def create_capital_call_payload(total_call_cents=None, due_date=None, **overrides) -> dict:
    defaults = {
        "total_call_cents": (total_call_cents if total_call_cents is not None
                             else DEFAULTS["TOTAL_CALL_CENTS"]),
        "due_date": due_date if due_date is not None else DEFAULTS["DUE_DATE"],
    }
    defaults.update(overrides)
    return defaults


def receive_escrow_payload(amount_cents, **overrides) -> dict:
    defaults = {"amount_cents": amount_cents}
    defaults.update(overrides)
    return defaults


def create_quarterly_report_payload(**overrides) -> dict:
    defaults = {
        "report_year": DEFAULTS["REPORT_YEAR"],
        "report_quarter": DEFAULTS["REPORT_QUARTER"],
        "noi_cents": DEFAULTS["NOI_CENTS"],
        "occupancy_pct": DEFAULTS["OCCUPANCY_PCT"],
    }
    defaults.update(overrides)
    return defaults


def create_distribution_payload(distribution_kind, total_distributable_cents=None,
                                quarterly_report_id=None, capital_event_id=None,
                                **overrides) -> dict:
    defaults = {
        "distribution_kind": distribution_kind,
        "total_distributable_cents": (
            total_distributable_cents if total_distributable_cents is not None
            else DEFAULTS["TOTAL_DISTRIBUTABLE_CENTS"]),
    }
    if quarterly_report_id is not None:
        defaults["quarterly_report_id"] = quarterly_report_id
    if capital_event_id is not None:
        defaults["capital_event_id"] = capital_event_id
    defaults.update(overrides)
    return defaults


def create_capital_event_payload(event_kind="REFINANCE", **overrides) -> dict:
    defaults = {
        "event_kind": event_kind,
        "gross_proceeds_cents": DEFAULTS["GROSS_PROCEEDS_CENTS"],
        "debt_payoff_cents": DEFAULTS["DEBT_PAYOFF_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_k1_package_payload(**overrides) -> dict:
    defaults = {
        "tax_year": DEFAULTS["TAX_YEAR"],
        "preparer_firm": DEFAULTS["PREPARER_FIRM"],
    }
    defaults.update(overrides)
    return defaults


def create_transfer_request_payload(to_investor_id, transfer_cents,
                                    expected_subscription_version, **overrides) -> dict:
    defaults = {
        "to_investor_id": to_investor_id,
        "transfer_cents": transfer_cents,
        "expected_subscription_version": expected_subscription_version,
    }
    defaults.update(overrides)
    return defaults
