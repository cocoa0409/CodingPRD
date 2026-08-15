"""Entity serializers. Computed fields are derived live at read time (PRD §2.5)."""

from db import store, fmt_ts, UNITS_PER_CHILD_PER_MONTH


def _common(e):
    return {
        "id": e["id"],
        "created_at": fmt_ts(e["created_at"]),
        "updated_at": fmt_ts(e["updated_at"]),
        "version": e["version"],
    }


def agency_active_allocated_units(agency_id):
    """Sum of (allocated - fulfilled) over the agency's lines with status
    ALLOCATED or PARTIALLY_FULFILLED (PRD §2.9)."""
    total = 0
    for ln in store.allocation_lines.values():
        if ln["agency_id"] == agency_id and ln["status"] in ("ALLOCATED", "PARTIALLY_FULFILLED"):
            total += ln["allocated_units"] - ln["fulfilled_units"]
    return total


def agency_json(a):
    out = _common(a)
    out.update({
        "name": a["name"],
        "agency_code": a["agency_code"],
        "contact_email": a["contact_email"],
        "children_served_monthly": a["children_served_monthly"],
        "storage_capacity_units": a["storage_capacity_units"],
        "status": a["status"],
        "active_allocated_units": agency_active_allocated_units(a["id"]),
    })
    return out


def grant_funds(g):
    """Funds ledger, always derivable from PO statuses (PRD §3.3)."""
    committed = 0
    spent = 0
    for po in store.purchase_orders.values():
        if po["grant_id"] != g["id"]:
            continue
        if po["status"] == "SUBMITTED":
            committed += po["total_cost_cents"]
        elif po["status"] == "RECEIVED":
            spent += po["total_cost_cents"]
    return committed, spent, g["total_amount_cents"] - committed - spent


def grant_json(g):
    committed, spent, available = grant_funds(g)
    out = _common(g)
    out.update({
        "funder_name": g["funder_name"],
        "grant_code": g["grant_code"],
        "total_amount_cents": g["total_amount_cents"],
        "restriction": g["restriction"],
        "start_date": fmt_ts(g["start_date"]),
        "end_date": fmt_ts(g["end_date"]),
        "committed_cents": committed,
        "spent_cents": spent,
        "available_cents": available,
        "status": g["status"],
    })
    return out


def inventory_json(inv):
    sizes = {}
    total_on_hand = 0
    for code, entry in inv["sizes"].items():
        on_hand = entry["on_hand_units"]
        reserved = entry["reserved_units"]
        threshold = entry["reorder_threshold_units"]
        total_on_hand += on_hand
        sizes[code] = {
            "on_hand_units": on_hand,
            "reserved_units": reserved,
            "reorder_threshold_units": threshold,
            "available_units": on_hand - reserved,
            "restock_needed": on_hand <= threshold,
        }
    out = _common(inv)
    out.update({
        "sizes": sizes,
        "initialized": inv["initialized"],
        "total_on_hand_units": total_on_hand,
    })
    return out


def batch_json(b):
    out = _common(b)
    out.update({
        "source_type": b["source_type"],
        "donor_name": b["donor_name"],
        "purchase_order_id": b["purchase_order_id"],
        "lines": [dict(ln) for ln in b["lines"]],
        "total_units": sum(ln["quantity"] for ln in b["lines"]),
        "valued_total_cents": b["valued_total_cents"],
        "status": b["status"],
        "posted_at": fmt_ts(b["posted_at"]),
    })
    return out


def po_json(po):
    out = _common(po)
    out.update({
        "grant_id": po["grant_id"],
        "vendor_name": po["vendor_name"],
        "lines": [dict(ln) for ln in po["lines"]],
        "discount_pct": po["discount_pct"],
        "total_cost_cents": po["total_cost_cents"],
        "status": po["status"],
        "created_by_user_id": po["created_by_user_id"],
        "submitted_by_user_id": po["submitted_by_user_id"],
        "received_intake_batch_id": po["received_intake_batch_id"],
    })
    return out


def run_total_allocated_units(run_id):
    return sum(ln["allocated_units"]
               for ln in store.allocation_lines.values()
               if ln["allocation_run_id"] == run_id)


def run_json(r):
    out = _common(r)
    out.update({
        "period": r["period"],
        "formula_variant": r["formula_variant"],
        "status": r["status"],
        "computed_at": fmt_ts(r["computed_at"]),
        "total_allocated_units": run_total_allocated_units(r["id"]),
        "published_at": fmt_ts(r["published_at"]),
    })
    return out


def line_json(ln):
    out = _common(ln)
    out.update({
        "allocation_run_id": ln["allocation_run_id"],
        "agency_id": ln["agency_id"],
        "size_code": ln["size_code"],
        "allocated_units": ln["allocated_units"],
        "fulfilled_units": ln["fulfilled_units"],
        "released_units": ln["released_units"],
        "status": ln["status"],
    })
    return out


def event_issued_total_units(event_id):
    return sum(i["total_units"] for i in store.issuances.values()
               if i["event_id"] == event_id and i["status"] == "FULFILLED")


def event_json(ev):
    out = _common(ev)
    out.update({
        "host_agency_id": ev["host_agency_id"],
        "site_name": ev["site_name"],
        "starts_at": fmt_ts(ev["starts_at"]),
        "ends_at": fmt_ts(ev["ends_at"]),
        "status": ev["status"],
        "completed_at": fmt_ts(ev["completed_at"]),
        "issued_total_units": event_issued_total_units(ev["id"]),
    })
    return out


def issuance_json(i):
    out = _common(i)
    out.update({
        "event_id": i["event_id"],
        "household_id": i["household_id"],
        "lines": [dict(ln) for ln in i["lines"]],
        "total_units": i["total_units"],
        "status": i["status"],
        "fulfilled_at": fmt_ts(i["fulfilled_at"]),
        "recorded_by_role": i["recorded_by_role"],
    })
    return out


def household_consumed_units(h):
    """FULFILLED by fulfilled_at in clock month + RECORDED by created_at in
    clock month; VOIDED excluded entirely (PRD §3.6)."""
    from db import now
    c = now()
    year, month = c.year, c.month
    total = 0
    for i in store.issuances.values():
        if i["household_id"] != h["id"]:
            continue
        if i["status"] == "FULFILLED" and i["fulfilled_at"] is not None:
            f = i["fulfilled_at"]
            if (f.year, f.month) == (year, month):
                total += i["total_units"]
        elif i["status"] == "RECORDED":
            cr = i["created_at"]
            if (cr.year, cr.month) == (year, month):
                total += i["total_units"]
    return total


def household_json(h):
    out = _common(h)
    out.update({
        "household_code": h["household_code"],
        "children_sizes": list(h["children_sizes"]),
        "consent_on_file": h["consent_on_file"],
        "privacy_restricted": h["privacy_restricted"],
        "eligibility_status": h["eligibility_status"],
        "eligibility_reason": h["eligibility_reason"],
        "monthly_allotment_units": UNITS_PER_CHILD_PER_MONTH * len(h["children_sizes"]),
        "consumed_this_month_units": household_consumed_units(h),
    })
    return out


def shift_json(s):
    signups = [dict(x) for x in s["signups"]]
    for x in signups:
        x["signed_up_at"] = fmt_ts(x["signed_up_at"])
    count = len(signups)
    out = _common(s)
    out.update({
        "title": s["title"],
        "starts_at": fmt_ts(s["starts_at"]),
        "ends_at": fmt_ts(s["ends_at"]),
        "capacity": s["capacity"],
        "signups": signups,
        "signup_count": count,
        "status": "FULL" if count >= s["capacity"] else "OPEN",
    })
    return out
