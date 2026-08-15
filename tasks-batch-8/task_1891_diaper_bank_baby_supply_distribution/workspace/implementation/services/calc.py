"""Calculation rules (scaffold §1.3 / PRD §3): allocation formula, forecasts,
valuations, PO totals, allotments, impact reports."""

from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from db import (store, now, base_fields, SIZE_CODES, FAIR_MARKET_CENTS,
                BASE_FLOOR_UNITS, UNITS_PER_CHILD_PER_MONTH,
                TRAILING_WINDOW_DAYS, DONATION_WINDOW_DAYS, WEEKS_IN_WINDOW)


def _rhup(value, places):
    """Round half up to the given number of decimal places."""
    q = Decimal(1).scaleb(-places)
    return Decimal(value).quantize(q, rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# purchase_order_total (PRD §3.3): per-line round half up to whole cents,
# then sum. The rounding order is pinned.
# ---------------------------------------------------------------------------
def po_total_cents(lines, discount_pct):
    disc = Decimal(str(discount_pct))
    total = 0
    for ln in lines:
        line_total = (Decimal(ln["quantity"]) * Decimal(ln["unit_cost_cents"])
                      * (Decimal(1) - disc))
        total += int(line_total.quantize(Decimal(1), rounding=ROUND_HALF_UP))
    return total


# ---------------------------------------------------------------------------
# intake_valuation (PRD §3.2): DONATION at the fair-market table; PURCHASE at
# the invoiced unit_cost_cents of the matching PO line.
# ---------------------------------------------------------------------------
def intake_valuation_cents(lines, source_type, po=None):
    total = 0
    if source_type == "DONATION":
        for ln in lines:
            total += ln["quantity"] * FAIR_MARKET_CENTS[ln["size_code"]]
    else:
        cost_by_size = {}
        for pl in (po["lines"] if po else []):
            cost_by_size.setdefault(pl["size_code"], pl["unit_cost_cents"])
        for ln in lines:
            total += ln["quantity"] * cost_by_size.get(ln["size_code"], 0)
    return total


# ---------------------------------------------------------------------------
# monthly_allocation_formula (PRD §3.4): per-size waterfall over ACTIVE
# agencies sorted by children_served_monthly DESC, created_at ASC.
# ---------------------------------------------------------------------------
def compute_allocation_run(run):
    # Recompute discards every line the run previously produced.
    doomed = [lid for lid, ln in store.allocation_lines.items()
              if ln["allocation_run_id"] == run["id"]]
    for lid in doomed:
        del store.allocation_lines[lid]

    eligible = [a for a in store.partner_agencies.values() if a["status"] == "ACTIVE"]
    eligible.sort(key=lambda a: (-a["children_served_monthly"], a["created_at"]))
    total_children = sum(a["children_served_monthly"] for a in eligible)
    variant = run["formula_variant"]

    inv = store.inventory
    for size in SIZE_CODES:
        if inv is not None:
            entry = inv["sizes"][size]
            pool = entry["on_hand_units"] - entry["reserved_units"]
        else:
            pool = 0
        remaining = pool
        for agency in eligible:
            if variant == "EQUAL_SPLIT":
                raw = 0 if len(eligible) == 0 else pool // len(eligible)
            else:  # NEED_WEIGHTED
                raw = 0 if total_children == 0 else (pool * agency["children_served_monthly"]) // total_children
            # Dignity floor: raise sub-100 raw shares to 100 when the pool
            # still holds at least 100 units and the agency serves a child.
            if (agency["children_served_monthly"] > 0 and raw < BASE_FLOOR_UNITS
                    and remaining >= BASE_FLOOR_UNITS):
                raw = BASE_FLOOR_UNITS
            # Capacity cap: half of storage capacity, rounded down.
            cap = agency["storage_capacity_units"] // 2
            grant = min(raw, cap, remaining)
            if grant > 0:
                line = base_fields()
                line.update({
                    "allocation_run_id": run["id"],
                    "agency_id": agency["id"],
                    "size_code": size,
                    "allocated_units": grant,
                    "fulfilled_units": 0,
                    "released_units": 0,
                    "status": "PROJECTED",
                })
                store.allocation_lines[line["id"]] = line
            remaining -= grant


# ---------------------------------------------------------------------------
# Allocation line selection used by issuance recording and event completion
# (PRD §3.5): run.period == clock month, run PUBLISHED, agency, size.
# ---------------------------------------------------------------------------
def find_active_line(agency_id, size_code):
    from db import current_month
    period = current_month()
    for r in store.allocation_runs.values():
        if r["period"] != period or r["status"] != "PUBLISHED":
            continue
        for ln in store.allocation_lines.values():
            if (ln["allocation_run_id"] == r["id"]
                    and ln["agency_id"] == agency_id
                    and ln["size_code"] == size_code):
                if ln["status"] in ("ALLOCATED", "PARTIALLY_FULFILLED", "FULFILLED"):
                    return ln
    return None


def credit_line(line, quantity):
    """Credit a fulfilled quantity to a line and recompute its status
    (PRD §3.4): equality with allocated_units flips the line to FULFILLED."""
    line["fulfilled_units"] += quantity
    if line["status"] in ("ALLOCATED", "PARTIALLY_FULFILLED"):
        if line["fulfilled_units"] >= line["allocated_units"]:
            line["status"] = "FULFILLED"
        elif line["fulfilled_units"] > 0:
            line["status"] = "PARTIALLY_FULFILLED"


def maybe_auto_finalize_run(run_id):
    """When every line of a PUBLISHED run is FULFILLED the run auto-finalizes
    with no reservation release (PRD §3.4)."""
    from db import touch
    run = store.allocation_runs.get(run_id)
    if run is None or run["status"] != "PUBLISHED":
        return
    lines = [ln for ln in store.allocation_lines.values()
             if ln["allocation_run_id"] == run_id]
    if lines and all(ln["status"] == "FULFILLED" for ln in lines):
        run["status"] = "FINALIZED"
        touch(run)


# ---------------------------------------------------------------------------
# household_monthly_allotment (PRD §3.6)
# ---------------------------------------------------------------------------
def household_allotment(h):
    return UNITS_PER_CHILD_PER_MONTH * len(h["children_sizes"])


def household_remaining(h):
    from serialize import household_consumed_units
    return household_allotment(h) - household_consumed_units(h)


# ---------------------------------------------------------------------------
# size_mix_forecast (PRD §3.8)
# ---------------------------------------------------------------------------
def _window_start(days):
    return now() - timedelta(days=days)


def forecast_report(variant):
    from db import fmt_ts, touch  # noqa: F401  (touch unused here)
    inv = store.inventory
    c = now()

    forecast = {s: 0 for s in SIZE_CODES}
    weekly_rates = {s: None for s in SIZE_CODES}

    if variant == "TRAILING_ACTUAL":
        start = _window_start(TRAILING_WINDOW_DAYS)
        totals = {s: 0 for s in SIZE_CODES}
        for i in store.issuances.values():
            if i["status"] != "FULFILLED" or i["fulfilled_at"] is None:
                continue
            f = i["fulfilled_at"]
            if start <= f <= c:  # inclusive both ends
                for ln in i["lines"]:
                    totals[ln["size_code"]] += ln["quantity"]
        for s in SIZE_CODES:
            rate = Decimal(totals[s]) / Decimal(WEEKS_IN_WINDOW)
            weekly_rates[s] = rate  # exact at 2 decimals (multiple of 0.25)
            forecast[s] = int(_rhup(rate * WEEKS_IN_WINDOW, 0))
    else:  # BOOKED_PIPELINE
        for ln in store.allocation_lines.values():
            run = store.allocation_runs.get(ln["allocation_run_id"])
            if run is not None and run["status"] == "PUBLISHED":
                forecast[ln["size_code"]] += ln["allocated_units"] - ln["fulfilled_units"]
        for i in store.issuances.values():
            if i["status"] != "RECORDED":
                continue
            ev = store.distribution_events.get(i["event_id"])
            if ev is not None and ev["status"] in ("OPEN", "LOCKED"):
                for ln in i["lines"]:
                    forecast[ln["size_code"]] += ln["quantity"]

    # Donation mix over [now - 90 days, now] inclusive, POSTED DONATION batches.
    donation_units = {s: 0 for s in SIZE_CODES}
    d_start = _window_start(DONATION_WINDOW_DAYS)
    total_donations = 0
    for b in store.intake_batches.values():
        if b["source_type"] != "DONATION" or b["status"] != "POSTED":
            continue
        p = b["posted_at"]
        if p is None or not (d_start <= p <= c):
            continue
        for ln in b["lines"]:
            donation_units[ln["size_code"]] += ln["quantity"]
            total_donations += ln["quantity"]

    forecast_total = sum(forecast.values())

    sizes_out = []
    for s in SIZE_CODES:
        if forecast_total == 0:
            need_share = Decimal(0)
        else:
            need_share = Decimal(forecast[s]) / Decimal(forecast_total)
        if total_donations == 0:
            donation_share = Decimal(0)
        else:
            donation_share = Decimal(donation_units[s]) / Decimal(total_donations)
        mix_gap = _rhup(need_share - donation_share, 4)

        if variant == "TRAILING_ACTUAL":
            rate = weekly_rates[s]
            if rate == 0:
                weeks_of_supply = None
            else:
                on_hand = inv["sizes"][s]["on_hand_units"] if inv is not None else 0
                weeks_of_supply = float(_rhup(Decimal(on_hand) / rate, 2))
            weekly_rate_out = float(_rhup(rate, 2))
        else:
            weeks_of_supply = None
            weekly_rate_out = None

        sizes_out.append({
            "size_code": s,
            "weekly_rate": weekly_rate_out,
            "forecast_4wk_units": forecast[s],
            "weeks_of_supply": weeks_of_supply,
            "need_share": float(_rhup(need_share, 4)),
            "donation_share": float(_rhup(donation_share, 4)),
            "mix_gap": float(mix_gap),
        })

    return {
        "variant": variant,
        "generated_at": fmt_ts(c),
        "sizes": sizes_out,
    }


# ---------------------------------------------------------------------------
# impact_report (PRD §3.8)
# ---------------------------------------------------------------------------
def impact_report(grant, year, month):
    from calendar import monthrange
    from datetime import datetime, timezone
    start = datetime(year, month, 1, tzinfo=timezone.utc)
    if month == 12:
        end = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
    else:
        end = datetime(year, month + 1, 1, tzinfo=timezone.utc)

    purchased = 0
    for b in store.intake_batches.values():
        if b["source_type"] != "PURCHASE" or b["status"] != "POSTED":
            continue
        if b["posted_at"] is None or not (start <= b["posted_at"] < end):
            continue
        po = store.purchase_orders.get(b["purchase_order_id"])
        if po is not None and po["grant_id"] == grant["id"]:
            purchased += sum(ln["quantity"] for ln in b["lines"])

    distributed = 0
    households = set()
    agencies = set()
    for i in store.issuances.values():
        if i["status"] != "FULFILLED" or i["fulfilled_at"] is None:
            continue
        if not (start <= i["fulfilled_at"] < end):
            continue
        distributed += i["total_units"]
        households.add(i["household_id"])
        ev = store.distribution_events.get(i["event_id"])
        if ev is not None:
            agencies.add(ev["host_agency_id"])

    from serialize import grant_funds
    _, spent, remaining = grant_funds(grant)

    return {
        "period": "%04d-%02d" % (year, month),
        "purchased_units": purchased,
        "diapers_distributed_units": distributed,
        "households_served": len(households),
        "agencies_served": len(agencies),
        "spent_cents": spent,
        "remaining_cents": remaining,
    }
