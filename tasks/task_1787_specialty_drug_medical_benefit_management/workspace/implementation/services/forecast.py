"""Pipeline spend forecasting (PRD 3.8; calculations pipeline_spend_forecast
and inline_annualized_spend)."""
from datetime import timedelta
from decimal import Decimal

from db import db
from util import CLOCK, add_years, dec, pdate, round_cents

INLINE_WINDOW_DAYS = 90


def run_forecast(variant: str, horizon_years: int, enrollment_projection: int):
    T0 = CLOCK.today()
    horizon_end = add_years(T0, horizon_years)

    per_drug = []
    pipeline_total = 0
    drugs = sorted(db["pipeline_drugs"].values(), key=lambda p: p["_seq"])
    for p in drugs:
        approval = pdate(p["expected_approval_date"])
        if approval >= horizon_end:
            continue  # excluded from per_drug_projections entirely
        patients = dec(enrollment_projection) * dec(p["prevalence_per_100k"]) / Decimal(100000)
        annual_cost = dec(p["projected_annual_cost_cents"])
        projected = 0
        for y in range(1, horizon_years + 1):
            ystart = add_years(T0, y - 1)
            yend = add_years(T0, y)
            if approval >= yend:
                factor = Decimal(0)
            elif approval >= ystart:
                days = (yend - approval).days
                factor = dec(p["year1_uptake_pct"]) * Decimal(days) / Decimal(365)
            else:
                factor = dec(p["steady_state_uptake_pct"])
            projected += round_cents(patients * annual_cost * factor)
        if variant == "POLICY_ADJUSTED":
            projected = round_cents(dec(projected) * (Decimal(1) - dec(p["biosimilar_erosion_pct"])))
        per_drug.append({"pipeline_drug_id": p["id"], "projected_cents": projected})
        pipeline_total += projected

    # In-line annualized spend: trailing 90-day half-open window [T0-90d, T0).
    win_start = T0 - timedelta(days=INLINE_WINDOW_DAYS)
    base = sum(
        c["allowed_amount_cents"]
        for c in db["claims"].values()
        if c["status"] in ("PAID", "ADJUSTED")
        and win_start <= pdate(c["service_date"]) < T0
    )
    inline_annualized = round_cents(dec(base) * Decimal(365) / Decimal(INLINE_WINDOW_DAYS))

    total_projected = pipeline_total + inline_annualized * horizon_years
    return {
        "as_of_date": T0.isoformat(),
        "pipeline_total_cents": pipeline_total,
        "inline_annualized_cents": inline_annualized,
        "total_projected_cents": total_projected,
        "per_drug_projections": per_drug,
    }
