"""Payload factories — one per entity, input fields only."""
import itertools

from .constants import TEST_DEFAULTS

_counter = itertools.count(1)


def _uniq(prefix: str) -> str:
    return f"{prefix}-{next(_counter)}"


def create_licensee_payload(**overrides) -> dict:
    n = next(_counter)
    defaults = {
        "legal_name": f"Test Licensee {n}",
        "tax_id": f"TAX-{n:06d}",
        "contact_email": f"contact{n}@example.test",
    }
    defaults.update(overrides)
    return defaults


def create_agreement_payload(licensee_id: str, **overrides) -> dict:
    n = next(_counter)
    defaults = {
        "licensee_id": licensee_id,
        "patent_reference": f"US-{10000000 + n}-B2",
        "title": f"License Agreement {n}",
        "royalty_base_definition": "NET_SALES",
        "base_rate_bp": TEST_DEFAULTS["BASE_RATE_BP"],
        "inventor_shares": [{"inventor_name": "Ada", "share_bp": 10000}],
        "effective_date": TEST_DEFAULTS["EFFECTIVE_DATE"],
        "expiration_date": TEST_DEFAULTS["EXPIRATION_DATE"],
    }
    defaults.update(overrides)
    return defaults


def create_milestone_payload(agreement_id: str, **overrides) -> dict:
    defaults = {
        "agreement_id": agreement_id,
        "name": _uniq("Milestone"),
        "trigger_type": "CUMULATIVE_SALES",
        "fee_cents": 1000,
    }
    defaults.update(overrides)
    # PRD section 3.4 conditional-required rule: threshold_cents belongs only
    # to CUMULATIVE_SALES, trigger_date only to DATE. Sending the other field
    # (or omitting the required one) is ERR_VALIDATION, so the factory must
    # shape the payload to the resolved trigger type.
    if defaults["trigger_type"] == "DATE":
        defaults.setdefault("trigger_date", "2027-01-01T00:00:00Z")
    else:
        defaults.setdefault("threshold_cents", 1_000_000)
        defaults.pop("trigger_date", None)
    return defaults


def create_sublicense_grant_payload(agreement_id: str, **overrides) -> dict:
    defaults = {
        "agreement_id": agreement_id,
        "sublicensee_name": _uniq("SubCo"),
        "territory": "EU",
    }
    defaults.update(overrides)
    return defaults


def make_report_line(**overrides) -> dict:
    defaults = {
        "product_label": _uniq("P"),
        "units_sold": 1,
        "gross_sales_cents": 100_000,
        "deductions_cents": 0,
        "is_sublicense_revenue": False,
    }
    defaults.update(overrides)
    return defaults


def create_royalty_report_payload(agreement_id: str, licensee_id: str, **overrides) -> dict:
    defaults = {
        "agreement_id": agreement_id,
        "licensee_id": licensee_id,
        "period_start": "2026-03-01T00:00:00Z",
        "period_end": "2026-03-31T00:00:00Z",
        "lines": [make_report_line()],
    }
    defaults.update(overrides)
    return defaults


def create_audit_payload(agreement_id: str, **overrides) -> dict:
    defaults = {
        "agreement_id": agreement_id,
        "scope_period_start": "2026-03-01T00:00:00Z",
        "scope_period_end": "2026-03-31T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_audit_finding_payload(audit_id: str, report_id: str, **overrides) -> dict:
    defaults = {
        "audit_id": audit_id,
        "report_id": report_id,
        "finding_type": "UNDERREPORTED_BASE",
        "audited_base_cents": 180_000,
    }
    defaults.update(overrides)
    return defaults


def create_offer_payload(amount_cents: int, expected_dispute_version: int, **overrides) -> dict:
    defaults = {
        "amount_cents": amount_cents,
        "expected_dispute_version": expected_dispute_version,
    }
    defaults.update(overrides)
    return defaults


def create_distribution_run_payload(agreement_id: str, **overrides) -> dict:
    defaults = {
        "agreement_id": agreement_id,
        "period_start": "2026-03-01T00:00:00Z",
        "period_end": "2026-03-31T00:00:00Z",
        "pool_cents": 1000,
    }
    defaults.update(overrides)
    return defaults
