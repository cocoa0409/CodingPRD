"""Calculations: emission_record kg_co2e, report totals, completeness, intensity."""
from __future__ import annotations

from decimal import Decimal

from ..store import store, now_ts
from ..utils import round_half_up


GWP_TABLE = {
    "CO2": Decimal("1"),
    "CH4": Decimal("28"),
    "N2O": Decimal("265"),
    "HFC": Decimal("1430"),
    "PFC": Decimal("7390"),
    "SF6": Decimal("23500"),
    "NF3": Decimal("16100"),
}

DQ_SCORES = {
    "METER_READING": Decimal("1.00"),
    "INVOICE": Decimal("0.80"),
    "SUPPLIER_DATA": Decimal("0.65"),
    "ESTIMATION": Decimal("0.40"),
}


def compute_kg_co2e(quantity: Decimal, kg_per_unit: Decimal, gas_type: str) -> Decimal:
    gwp = GWP_TABLE[gas_type]
    raw = quantity * kg_per_unit * gwp
    return round_half_up(raw, 4)


def consolidation_weight(approach: str, facility: dict) -> Decimal:
    if approach == "EQUITY_SHARE":
        return Decimal(str(facility.get("ownership_share_pct", 0))) / Decimal("100")
    if approach == "FINANCIAL_CONTROL":
        return Decimal("1") if facility.get("financial_control") else Decimal("0")
    if approach == "OPERATIONAL_CONTROL":
        return Decimal("1") if facility.get("operational_control") else Decimal("0")
    return Decimal("0")


def _bump(row: dict) -> None:
    row["updated_at"] = now_ts()
    row["version"] = row.get("version", 0) + 1


def derive_scope(category: str) -> str:
    if category in ("STATIONARY_COMBUSTION", "MOBILE_COMBUSTION", "PROCESS", "FUGITIVE"):
        return "SCOPE_1"
    if category == "PURCHASED_ENERGY":
        return "SCOPE_2"
    if category == "VALUE_CHAIN":
        return "SCOPE_3"
    return ""


def compile_totals(report: dict) -> dict:
    """Compute all the gross/net/intensity/completeness fields for the report.

    Returns a dict of fields to merge into the report row. Rounding is applied
    per facility-scope subtotal first, then sums are taken — exactly per
    scaffold's `report_compile_totals`.
    """
    org_id = report["organization_id"]
    period_id = report["reporting_period_id"]
    org = store.organizations[org_id]
    period = store.reporting_periods[period_id]
    approach = org["consolidation_approach"]

    # Build the inclusion set: FRESH ER on this period whose source's facility is included.
    contribs_s1: dict[str, Decimal] = {}
    contribs_s2_loc: dict[str, Decimal] = {}
    contribs_s2_mkt: dict[str, Decimal] = {}
    contribs_s3: dict[str, Decimal] = {}

    for er in store.emission_records.values():
        if er.get("reporting_period_id") != period_id:
            continue
        if er.get("status") != "FRESH":
            continue
        ad = store.activity_data.get(er.get("activity_data_id"))
        if not ad:
            continue
        src = store.emission_sources.get(ad.get("emission_source_id"))
        if not src:
            continue
        facility = store.facilities.get(src.get("facility_id"))
        if not facility or not facility.get("included_in_boundary"):
            continue

        fid = facility["id"]
        w = consolidation_weight(approach, facility)
        kg = Decimal(str(er["kg_co2e"]))
        contrib = kg * w
        scope = derive_scope(src["category"])
        method = er.get("scope2_method")
        if scope == "SCOPE_1":
            contribs_s1[fid] = contribs_s1.get(fid, Decimal("0")) + contrib
        elif scope == "SCOPE_2" and method == "LOCATION_BASED":
            contribs_s2_loc[fid] = contribs_s2_loc.get(fid, Decimal("0")) + contrib
        elif scope == "SCOPE_2" and method == "MARKET_BASED":
            contribs_s2_mkt[fid] = contribs_s2_mkt.get(fid, Decimal("0")) + contrib
        elif scope == "SCOPE_3":
            contribs_s3[fid] = contribs_s3.get(fid, Decimal("0")) + contrib

    def sum_subtotals(per_fac: dict[str, Decimal]) -> Decimal:
        total = Decimal("0")
        for v in per_fac.values():
            total += round_half_up(v, 4)
        return round_half_up(total, 4)

    g_s1 = sum_subtotals(contribs_s1)
    g_s2_loc = sum_subtotals(contribs_s2_loc)
    g_s2_mkt = sum_subtotals(contribs_s2_mkt)
    g_s3 = sum_subtotals(contribs_s3)

    applied = compute_applied_offsets(period_id)

    net = compute_net(g_s1, g_s2_mkt, g_s3, applied)

    rev = Decimal(str(period.get("revenue", 0)))
    head = Decimal(str(period.get("headcount", 0)))
    uo = Decimal(str(period.get("unit_output", 0)))

    i_rev = Decimal("0") if rev == 0 else round_half_up(net / rev, 4)
    i_emp = Decimal("0") if head == 0 else round_half_up(net / head, 4)
    i_uo = Decimal("0") if uo == 0 else round_half_up(net / uo, 4)

    # Completeness
    identified, covered = compute_coverage(org_id, period_id)
    if identified == 0:
        completeness_pct = Decimal("0.00")
    else:
        completeness_pct = round_half_up(Decimal("100") * Decimal(covered) / Decimal(identified), 2)
    threshold_pct = round_half_up(Decimal("100") - Decimal(str(org.get("materiality_threshold_pct", 0))), 2)
    passes = completeness_pct >= threshold_pct

    has_stale = any(
        er.get("reporting_period_id") == period_id and er.get("status") == "STALE"
        for er in store.emission_records.values()
    )
    assurance_ready = passes and (not has_stale) and period.get("status") in ("OPEN", "CLOSED")

    return {
        "gross_scope1_kg_co2e": float(g_s1),
        "gross_scope2_location_kg_co2e": float(g_s2_loc),
        "gross_scope2_market_kg_co2e": float(g_s2_mkt),
        "gross_scope3_kg_co2e": float(g_s3),
        "applied_offsets_kg_co2e": float(applied),
        "net_emissions_kg_co2e": float(net),
        "intensity_per_revenue": float(i_rev),
        "intensity_per_employee": float(i_emp),
        "intensity_per_unit_output": float(i_uo),
        "completeness_pct": float(completeness_pct),
        "completeness_passes": bool(passes),
        "assurance_ready": bool(assurance_ready),
    }


def compute_applied_offsets(period_id: str) -> Decimal:
    retired = Decimal("0")
    for c in store.carbon_credits.values():
        if c.get("reporting_period_id") == period_id and c.get("status") == "RETIRED":
            retired += Decimal(str(c["quantity_kg_co2e"]))
    internal = Decimal("0")
    for p in store.reduction_projects.values():
        if (
            p.get("reporting_period_id") == period_id
            and p.get("status") == "COMPLETED"
            and p.get("project_type") == "INTERNAL_REDUCTION"
        ):
            internal += Decimal(str(p["reduction_kg_co2e"]))
    return round_half_up(retired + internal, 4)


def compute_net(g_s1: Decimal, g_s2_mkt: Decimal, g_s3: Decimal, applied: Decimal) -> Decimal:
    gross_total = g_s1 + g_s2_mkt + g_s3
    diff = round_half_up(gross_total - applied, 4)
    return max(Decimal("0"), diff)


def compute_coverage(organization_id: str, period_id: str) -> tuple[int, int]:
    identified_ids: set[str] = set()
    for src in store.emission_sources.values():
        if src.get("organization_id") != organization_id:
            continue
        if src.get("status") != "ACTIVE":
            continue
        facility = store.facilities.get(src.get("facility_id"))
        if facility and facility.get("included_in_boundary"):
            identified_ids.add(src["id"])

    covered_ids: set[str] = set()
    for er in store.emission_records.values():
        if er.get("reporting_period_id") != period_id:
            continue
        if er.get("status") != "FRESH":
            continue
        ad = store.activity_data.get(er.get("activity_data_id"))
        if ad:
            covered_ids.add(ad.get("emission_source_id"))
    return len(identified_ids), len(covered_ids)


def recompute_open_reports_for_period(period_id: str) -> None:
    """Recompute applied_offsets/net/intensities on DRAFT/UNDER_REVIEW reports
    that have already been compiled (i.e. their pinned totals exist)."""
    for rep in store.reports.values():
        if rep.get("reporting_period_id") != period_id:
            continue
        if rep.get("status") not in ("DRAFT", "UNDER_REVIEW"):
            continue
        # Skip reports that haven't been compiled yet (their totals are null)
        if rep.get("compiled_at") is None:
            continue
        new_vals = compile_totals(rep)
        # Only refresh offset/net/intensity, leave the gross subtotals pinned
        # at compile time. But per the scaffold cascade, "applied_offsets_kg_co2e
        # and net_emissions_kg_co2e are recomputed". Refresh these and the
        # derived intensities for consistency.
        rep["applied_offsets_kg_co2e"] = new_vals["applied_offsets_kg_co2e"]
        # Recompute net using pinned gross_scope1 + gross_scope2_market + gross_scope3 - new applied
        g_s1 = Decimal(str(rep.get("gross_scope1_kg_co2e") or 0))
        g_s2_mkt = Decimal(str(rep.get("gross_scope2_market_kg_co2e") or 0))
        g_s3 = Decimal(str(rep.get("gross_scope3_kg_co2e") or 0))
        applied = Decimal(str(rep["applied_offsets_kg_co2e"]))
        net = compute_net(g_s1, g_s2_mkt, g_s3, applied)
        rep["net_emissions_kg_co2e"] = float(net)
        period = store.reporting_periods[rep["reporting_period_id"]]
        rev = Decimal(str(period.get("revenue", 0)))
        head = Decimal(str(period.get("headcount", 0)))
        uo = Decimal(str(period.get("unit_output", 0)))
        rep["intensity_per_revenue"] = float(Decimal("0") if rev == 0 else round_half_up(net / rev, 4))
        rep["intensity_per_employee"] = float(Decimal("0") if head == 0 else round_half_up(net / head, 4))
        rep["intensity_per_unit_output"] = float(Decimal("0") if uo == 0 else round_half_up(net / uo, 4))
        _bump(rep)
