"""Payload factories — one per entity, input fields only."""
import uuid

from .constants import (
    DEFAULT_OPEN_DATE,
    DEFAULT_CLOSE_DATE,
    DEFAULT_PERIOD_START,
    DEFAULT_PERIOD_END,
    DEFAULT_DRAWDOWN_PERIOD_START,
    DEFAULT_DRAWDOWN_PERIOD_END,
)


def _unique_uei() -> str:
    return "UEI-" + uuid.uuid4().hex[:10].upper()


def create_nonprofit_payload(**overrides) -> dict:
    defaults = {
        "legal_name": "Test Nonprofit",
        "uei": _unique_uei(),
        "ein": "11-1111111",
    }
    defaults.update(overrides)
    return defaults


def create_nofo_payload(**overrides) -> dict:
    defaults = {
        "title": "Community Opportunity",
        "cfda_number": "93.999",
        "total_pool_cents": 100_000_000,
        "max_award_cents": 100_000_000,
        "indirect_cost_cap_pct": 0.30,
        "open_date": DEFAULT_OPEN_DATE,
        "close_date": DEFAULT_CLOSE_DATE,
    }
    defaults.update(overrides)
    return defaults


def create_application_payload(nonprofit_id: str, **overrides) -> dict:
    defaults = {
        "nonprofit_id": nonprofit_id,
        "project_title": "Test Project",
        "requested_amount_cents": 11_000_000,
        "proposed_period_start": DEFAULT_PERIOD_START,
        "proposed_period_end": DEFAULT_PERIOD_END,
        "indirect_method": "DE_MINIMIS",
    }
    defaults.update(overrides)
    return defaults


def create_review_payload(score: int, **overrides) -> dict:
    defaults = {"score": score}
    defaults.update(overrides)
    return defaults


def create_budget_line_payload(category: str, amount_cents: int, federal_share_pct: float,
                               **overrides) -> dict:
    defaults = {
        "category": category,
        "amount_cents": amount_cents,
        "federal_share_pct": federal_share_pct,
    }
    defaults.update(overrides)
    return defaults


def create_drawdown_payload(requested_amount_cents: int, expected_subaward_version: int,
                            **overrides) -> dict:
    defaults = {
        "requested_amount_cents": requested_amount_cents,
        "period_covered_start": DEFAULT_DRAWDOWN_PERIOD_START,
        "period_covered_end": DEFAULT_DRAWDOWN_PERIOD_END,
        "expected_subaward_version": expected_subaward_version,
    }
    defaults.update(overrides)
    return defaults


def create_monitoring_visit_payload(scheduled_start: str, scheduled_end: str, **overrides) -> dict:
    defaults = {"scheduled_start": scheduled_start, "scheduled_end": scheduled_end}
    defaults.update(overrides)
    return defaults


def create_performance_report_payload(metric_target: int, metric_actual: int, **overrides) -> dict:
    defaults = {
        "reporting_period_start": DEFAULT_PERIOD_START,
        "reporting_period_end": DEFAULT_PERIOD_END,
        "metric_target": metric_target,
        "metric_actual": metric_actual,
    }
    defaults.update(overrides)
    return defaults


def create_single_audit_payload(fiscal_year: int, total_federal_expenditures_cents: int,
                                 **overrides) -> dict:
    defaults = {
        "fiscal_year": fiscal_year,
        "total_federal_expenditures_cents": total_federal_expenditures_cents,
        "material_weakness": False,
        "reported_finding_count": 0,
    }
    defaults.update(overrides)
    return defaults
