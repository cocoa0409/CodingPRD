"""Payload factories — one per creatable resource, input fields only (PRD §3)."""
import itertools

from .constants import (
    STD_COVER_DATE,
    STD_EDITORIAL_CLOSE_DATE,
    STD_AD_CLOSE_DATE,
    STD_SHIP_TO_PRINTER_DATE,
    STD_MAIL_DATE,
    TEST_DEFAULTS,
)

_pub_counter = itertools.count(1)
_issn_counter = itertools.count(1)
_issue_number_counter = itertools.count(1)
_subscriber_counter = itertools.count(1)
_series_counter = itertools.count(1)
_permit_counter = itertools.count(1)


def _next_issn() -> str:
    # issn is exactly eight characters (PRD §2.7).
    return f"{10000000 + next(_issn_counter)}"[-8:]


def create_publication_payload(**overrides) -> dict:
    n = next(_pub_counter)
    defaults = {
        "title": f"Test Publication {n}",
        "issn": _next_issn(),
        "frequency": "MONTHLY",
        "circulation_model": "PAID",
        "base_cover_price_cents": TEST_DEFAULTS["BASE_COVER_PRICE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_issue_payload(**overrides) -> dict:
    defaults = {
        "issue_number": next(_issue_number_counter),
        "volume_number": 1,
        "cover_date": STD_COVER_DATE,
        "editorial_close_date": STD_EDITORIAL_CLOSE_DATE,
        "ad_close_date": STD_AD_CLOSE_DATE,
        "ship_to_printer_date": STD_SHIP_TO_PRINTER_DATE,
        "mail_date": STD_MAIL_DATE,
        "ad_pages_sold": TEST_DEFAULTS["AD_PAGES_SOLD"],
        "newsstand_buffer_copies": TEST_DEFAULTS["NEWSSTAND_BUFFER_COPIES"],
    }
    defaults.update(overrides)
    return defaults


def create_subscriber_payload(**overrides) -> dict:
    n = next(_subscriber_counter)
    defaults = {
        "email": f"subscriber{n}@example.com",
        "full_name": f"Test Subscriber {n}",
        "address_line1": f"{n} Main Street",
        "city": "Springfield",
        "state_code": "IL",
        "postal_code": "62701",
        # country_code intentionally omitted: PRD §3.2 defaults it to US.
    }
    defaults.update(overrides)
    return defaults


def create_subscription_payload(start_issue_id, **overrides) -> dict:
    defaults = {
        "start_issue_id": start_issue_id,
        "term_issues": TEST_DEFAULTS["TERM_ISSUES"],
        "price_paid_cents": TEST_DEFAULTS["PRICE_PAID_CENTS"],
        "qualification_tier": "PAID",
        "payment_method": "CARD",
        # is_gift / donor_subscriber_id / auto_renew / expire_action are
        # optional inputs (PRD §3.2); included only when explicitly given.
    }
    defaults.update(overrides)
    return defaults


def create_controlled_subscription_payload(start_issue_id, **overrides) -> dict:
    defaults = {
        "start_issue_id": start_issue_id,
        "term_issues": TEST_DEFAULTS["TERM_ISSUES"],
        "price_paid_cents": 0,
        "qualification_tier": "CONTROLLED",
        "payment_method": "NONE",
    }
    defaults.update(overrides)
    return defaults


def create_renewal_series_payload(**overrides) -> dict:
    n = next(_series_counter)
    defaults = {
        "series_code": f"STD{n}",
        "effort_offsets_days": [-90, -60, -30],
        "effort_pricing_cents": [999, 1099, 1199],
        "is_default": True,
    }
    defaults.update(overrides)
    return defaults


def create_mailing_batch_payload(**overrides) -> dict:
    defaults = {
        "batch_label": "DOMESTIC",
        "postal_class": "FIRST_CLASS",
        "entry_point": "ORIGIN",
        "permit_number": f"P-{100 + next(_permit_counter)}",
        "is_controlled_copy_included": False,
    }
    defaults.update(overrides)
    return defaults


def create_back_issue_order_payload(issue_id, **overrides) -> dict:
    defaults = {
        "issue_id": issue_id,
        "quantity": 1,
    }
    defaults.update(overrides)
    return defaults


def create_circulation_audit_payload(**overrides) -> dict:
    defaults = {
        "audit_period_start": "2026-01-01T00:00:00Z",
        "audit_period_end": "2026-06-30T23:59:59Z",
    }
    defaults.update(overrides)
    return defaults
