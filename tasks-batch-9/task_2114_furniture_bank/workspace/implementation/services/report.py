"""The unmet-need report (PRD 3.6)."""

from core import CATEGORY_PRIORITY, COUNTY_ORDER, clock, dec, iso, round_half_up
from db import db, referral_of_voucher
from services.calc import whole_days_between


def _line_demand(county, category):
    requested = 0
    allocated = 0
    for line in db.voucher_lines.values():
        if line["category"] != category:
            continue
        if line["status"] == "CANCELLED":
            continue
        voucher = db.vouchers.get(line["voucher_id"])
        if voucher is None:
            continue
        referral = referral_of_voucher(voucher)
        if referral is None:
            continue
        client = db.clients.get(referral["client_id"])
        if client is None or client["county"] != county:
            continue
        requested += line["quantity_requested"]
        allocated += line["quantity_allocated"]
    return requested, allocated


def unmet_need_report(county_filter=None, category_filter=None):
    now = clock.now()
    source = []
    for entry in db.waitlist_entries.values():
        if entry["status"] != "WAITING":
            continue
        if county_filter is not None and entry["county"] != county_filter:
            continue
        if category_filter is not None and entry["category"] != category_filter:
            continue
        source.append(entry)

    groups = {}
    for entry in source:
        groups.setdefault((entry["county"], entry["category"]), []).append(entry)

    ordered_keys = sorted(
        groups.keys(),
        key=lambda k: (COUNTY_ORDER.index(k[0]) if k[0] in COUNTY_ORDER else len(COUNTY_ORDER),
                       CATEGORY_PRIORITY.get(k[1], 99)),
    )

    rows = []
    total_unmet = 0
    for key in ordered_keys:
        county, category = key
        entries = groups[key]
        unmet_quantity = sum(e["quantity_unmet"] for e in entries)
        households_waiting = len(set(e["client_id"] for e in entries))
        max_wait_days = max(whole_days_between(e["waiting_since"], now) for e in entries)
        top_priority_score = max(dec(e["priority_score"]) for e in entries)
        requested_units, allocated_units = _line_demand(county, category)
        if requested_units == 0:
            fill_rate_pct = None
        else:
            fill_rate_pct = float(round_half_up(
                dec(100) * dec(allocated_units) / dec(requested_units), 1))
        rows.append({
            "county": county,
            "category": category,
            "unmet_quantity": unmet_quantity,
            "households_waiting": households_waiting,
            "max_wait_days": max_wait_days,
            "top_priority_score": float(top_priority_score),
            "requested_units": requested_units,
            "allocated_units": allocated_units,
            "fill_rate_pct": fill_rate_pct,
        })
        total_unmet += unmet_quantity

    return {
        "generated_at": iso(now),
        "rows": rows,
        "total_unmet_quantity": total_unmet,
        "total_households_waiting": len(set(e["client_id"] for e in source)),
    }
