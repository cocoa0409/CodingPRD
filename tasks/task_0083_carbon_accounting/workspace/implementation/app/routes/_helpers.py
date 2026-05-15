"""Shared route helpers: existence lookups for organization, period, etc."""
from __future__ import annotations

from ..errors import api_error
from ..store import store


def get_org_or_404(org_id: str) -> dict:
    org = store.organizations.get(org_id)
    if not org:
        raise api_error("ERR_NOT_FOUND", f"Organization {org_id} not found")
    return org


def get_facility_or_404(org_id: str, facility_id: str) -> dict:
    f = store.facilities.get(facility_id)
    if not f or f.get("organization_id") != org_id:
        raise api_error("ERR_NOT_FOUND", f"Facility {facility_id} not found")
    return f


def get_period_or_404(org_id: str, period_id: str) -> dict:
    p = store.reporting_periods.get(period_id)
    if not p or p.get("organization_id") != org_id:
        raise api_error("ERR_NOT_FOUND", f"ReportingPeriod {period_id} not found")
    return p


def get_source_or_404(org_id: str, source_id: str) -> dict:
    s = store.emission_sources.get(source_id)
    if not s or s.get("organization_id") != org_id:
        raise api_error("ERR_NOT_FOUND", f"EmissionSource {source_id} not found")
    return s


def get_factor_or_404(org_id: str, factor_id: str) -> dict:
    f = store.emission_factors.get(factor_id)
    if not f or f.get("organization_id") != org_id:
        raise api_error("ERR_NOT_FOUND", f"EmissionFactor {factor_id} not found")
    return f


def get_project_or_404(org_id: str, project_id: str) -> dict:
    p = store.reduction_projects.get(project_id)
    if not p or p.get("organization_id") != org_id:
        raise api_error("ERR_NOT_FOUND", f"ReductionProject {project_id} not found")
    return p


def get_credit_or_404(org_id: str, credit_id: str) -> dict:
    c = store.carbon_credits.get(credit_id)
    if not c or c.get("organization_id") != org_id:
        raise api_error("ERR_NOT_FOUND", f"CarbonCredit {credit_id} not found")
    return c


def get_report_or_404(org_id: str, report_id: str) -> dict:
    r = store.reports.get(report_id)
    if not r or r.get("organization_id") != org_id:
        raise api_error("ERR_NOT_FOUND", f"Report {report_id} not found")
    return r


def sort_by_created(items: list) -> list:
    return sorted(items, key=lambda x: (x.get("created_at", ""), x.get("id", "")))
