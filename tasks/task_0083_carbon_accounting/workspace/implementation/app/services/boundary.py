"""Facility inclusion resolver and boundary-related cascades."""
from __future__ import annotations

from decimal import Decimal

from ..store import store, now_ts


def compute_included(approach: str, facility: dict) -> bool:
    """Apply the facility_inclusion_resolver rule per Scaffold §1.3."""
    if approach == "EQUITY_SHARE":
        share = Decimal(str(facility.get("ownership_share_pct", 0)))
        return share > 0
    if approach == "FINANCIAL_CONTROL":
        return bool(facility.get("financial_control"))
    if approach == "OPERATIONAL_CONTROL":
        return bool(facility.get("operational_control"))
    return False


def _bump(row: dict) -> None:
    row["updated_at"] = now_ts()
    row["version"] = row.get("version", 0) + 1


def resolve_org_boundary(organization_id: str) -> None:
    """Recompute included_in_boundary for every facility of the org.

    If a facility flips from True→False, every EmissionSource on it is set
    RETIRED, and every FRESH EmissionRecord on those sources flips to STALE
    (with updated_at refreshed and version bumped). Affected DRAFT/UNDER_REVIEW
    reports flip to RECOMPUTE_REQUIRED.
    """
    org = store.organizations.get(organization_id)
    if not org:
        return
    approach = org["consolidation_approach"]
    flipped_facility_ids: set[str] = set()

    for f in store.facilities.values():
        if f.get("organization_id") != organization_id:
            continue
        if f.get("status") == "RETIRED":
            # Retired facilities are never in boundary
            if f.get("included_in_boundary") is not False:
                f["included_in_boundary"] = False
                _bump(f)
            continue
        new_included = compute_included(approach, f)
        prev = f.get("included_in_boundary")
        if prev != new_included:
            f["included_in_boundary"] = new_included
            _bump(f)
            if prev is True and new_included is False:
                flipped_facility_ids.add(f["id"])

    if flipped_facility_ids:
        # Cascade to EmissionSource → EmissionRecord
        affected_periods: set[str] = set()
        for src in store.emission_sources.values():
            if src.get("organization_id") != organization_id:
                continue
            if src.get("facility_id") in flipped_facility_ids and src.get("status") == "ACTIVE":
                src["status"] = "RETIRED"
                _bump(src)
                # Flip FRESH EmissionRecord for this source to STALE
                for er in store.emission_records.values():
                    if er.get("status") != "FRESH":
                        continue
                    ad = store.activity_data.get(er.get("activity_data_id"))
                    if not ad:
                        continue
                    if ad.get("emission_source_id") != src["id"]:
                        continue
                    er["status"] = "STALE"
                    _bump(er)
                    affected_periods.add(er.get("reporting_period_id"))

        # Cascade affected periods to reports
        if affected_periods:
            for rep in store.reports.values():
                if rep.get("organization_id") != organization_id:
                    continue
                if rep.get("reporting_period_id") in affected_periods and rep.get("status") in ("DRAFT", "UNDER_REVIEW"):
                    rep["status"] = "RECOMPUTE_REQUIRED"
                    _bump(rep)
