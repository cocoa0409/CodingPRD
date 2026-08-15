"""Payload factories — one per creatable resource, input fields only (PRD §4)."""
import itertools

from .constants import TEST_DEFAULTS

_counter = itertools.count(1)


def _next(tag: str) -> str:
    return f"{tag}-{next(_counter)}"


def create_case_payload(**overrides) -> dict:
    n = next(_counter)
    defaults = {
        "case_number": f"2026-CV-{4000 + n}",
        "court_jurisdiction": TEST_DEFAULTS["COURT_JURISDICTION"],
        "debtor_name": TEST_DEFAULTS["DEBTOR_NAME"],
        "appointed_receiver_name": TEST_DEFAULTS["APPOINTED_RECEIVER_NAME"],
        "appointment_effective_at": TEST_DEFAULTS["APPOINTMENT_EFFECTIVE_AT"],
        "authority_limit_cents": TEST_DEFAULTS["AUTHORITY_LIMIT_CENTS"],
        "business_operation_authorized": TEST_DEFAULTS["BUSINESS_OPERATION_AUTHORIZED"],
        "bar_date": TEST_DEFAULTS["BAR_DATE"],
        "reporting_interval_days": TEST_DEFAULTS["REPORTING_INTERVAL_DAYS"],
        "operating_reserve_cents": TEST_DEFAULTS["OPERATING_RESERVE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_asset_payload(case_id: str, **overrides) -> dict:
    defaults = {
        "case_id": case_id,
        "description": _next("Asset"),
        "asset_class": "EQUIPMENT",
        "estimated_value_cents": 25000,
    }
    defaults.update(overrides)
    return defaults


def create_claim_payload(case_id: str, **overrides) -> dict:
    defaults = {
        "case_id": case_id,
        "creditor_name": _next("Creditor"),
        "creditor_type": "GENERAL_UNSECURED",
        "filed_amount_cents": 50000,
    }
    defaults.update(overrides)
    return defaults


def create_engagement_payload(case_id: str, **overrides) -> dict:
    defaults = {
        "case_id": case_id,
        "professional_name": _next("Pro"),
        "firm_name": "Law LLP",
        "role_type": "COUNSEL",
        "fee_arrangement": "HOURLY",
        "hourly_rate_cents": TEST_DEFAULTS["HOURLY_RATE_CENTS"],
        "fee_cap_cents": TEST_DEFAULTS["FEE_CAP_CENTS"],
    }
    defaults.update(overrides)
    # Prune the conditional field that does not belong to the arrangement:
    # CONTINGENT forbids hourly_rate_cents; HOURLY forbids contingency_pct.
    if defaults.get("fee_arrangement") == "CONTINGENT":
        defaults.pop("hourly_rate_cents", None)
        defaults.setdefault("contingency_pct", 0.10)
    else:
        defaults.pop("contingency_pct", None)
    return defaults


def create_fee_application_payload(engagement_id: str, **overrides) -> dict:
    defaults = {
        "engagement_id": engagement_id,
        "period_start": "2026-08-01T00:00:00Z",
        "period_end": "2026-08-31T00:00:00Z",
        "time_entries": [{"hours": 1.0, "rate_cents": TEST_DEFAULTS["HOURLY_RATE_CENTS"]}],
        "expenses_cents": 0,
    }
    defaults.update(overrides)
    # Contingent applications must not carry time_entries; hourly ones must
    # not carry recovery_basis_cents.
    if "recovery_basis_cents" in defaults and defaults["recovery_basis_cents"] is not None:
        defaults.pop("time_entries", None)
    return defaults


def create_authorization_request_payload(case_id: str, **overrides) -> dict:
    defaults = {
        "case_id": case_id,
        "request_type": "EXPENDITURE",
        "description": _next("Authorization"),
        "amount_cents": 10000,
    }
    defaults.update(overrides)
    return defaults


def create_status_report_payload(case_id: str, **overrides) -> dict:
    defaults = {
        "case_id": case_id,
        "report_type": "PERIODIC",
        "period_start": "2026-08-01T00:00:00Z",
        "period_end": "2026-08-31T00:00:00Z",
        "narrative": "Periodic report.",
    }
    defaults.update(overrides)
    return defaults


def create_distribution_plan_payload(case_id: str, **overrides) -> dict:
    defaults = {
        "case_id": case_id,
        "reserve_cents": 0,
    }
    defaults.update(overrides)
    return defaults
