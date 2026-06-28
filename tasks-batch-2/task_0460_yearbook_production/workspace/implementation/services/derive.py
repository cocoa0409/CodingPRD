"""Derived-field reconciliation (PRD §2.5, §3.8; SCAFFOLD §1.3 ladder_fill,
production_phase, and the revenue rollups).

Recomputing a derived field is a mutation: when a recompute changes any derived
value on an entity, refresh updated_at and bump version (db.touch). A recompute
that changes nothing is a no-op (no version bump).
"""
from db import db, touch


def _yb_pages(yearbook_id):
    return [p for p in db.ladder_pages.values() if p["yearbook_id"] == yearbook_id]


def recompute_page_counts(page):
    """approved_submission_count for a single page; touch if changed."""
    count = sum(
        1 for s in db.submissions.values()
        if s["ladder_page_id"] == page["id"] and s["status"] == "APPROVED"
    )
    if page.get("approved_submission_count") != count:
        page["approved_submission_count"] = count
        touch(page)


def recompute_assignment_page_count(assignment):
    count = sum(
        1 for p in db.ladder_pages.values()
        if p.get("assigned_staff_id") == assignment["id"]
    )
    if assignment.get("assigned_page_count") != count:
        assignment["assigned_page_count"] = count
        touch(assignment)


def _compute_production_phase(yb):
    """Top-down, first match wins (PRD §3.8)."""
    yb_id = yb["id"]
    pages = _yb_pages(yb_id)
    ladder_filled = len(pages)
    ladder_complete = (ladder_filled == yb["target_page_count"])
    approved_pages = sum(1 for p in pages if p["status"] == "APPROVED")

    print_runs = [r for r in db.print_runs.values() if r["yearbook_id"] == yb_id]
    proofs = [pr for pr in db.proofs.values() if pr["yearbook_id"] == yb_id]

    if any(r["status"] == "DELIVERED" for r in print_runs):
        return "DELIVERED"
    if any(pr["status"] == "PLANT_APPROVED" for pr in proofs):
        return "PRINTING"
    if any(pr["status"] == "PLANT_SUBMITTED" for pr in proofs):
        return "PLANT"
    if ladder_complete and ladder_filled > 0 and approved_pages == ladder_filled:
        return "PROOFING"
    if ladder_filled > 0 and any(p["status"] != "DRAFT" for p in pages):
        return "CONTENT"
    return "LADDER_BUILD"


def recompute_yearbook(yb):
    """Recompute all derived yearbook fields; touch once if anything changed."""
    yb_id = yb["id"]
    pages = _yb_pages(yb_id)
    ladder_filled = len(pages)
    ladder_complete = (ladder_filled == yb["target_page_count"])

    ad_revenue = sum(
        c["net_price_cents"] for c in db.ad_contracts.values()
        if c["yearbook_id"] == yb_id and c["status"] in ("SIGNED", "PLACED")
    )
    presale_revenue = sum(
        o["total_price_cents"] for o in db.presale_orders.values()
        if o["yearbook_id"] == yb_id and o["status"] in ("PAID", "FULFILLED")
    )
    phase = _compute_production_phase(yb)

    changed = (
        yb.get("ladder_filled_count") != ladder_filled
        or yb.get("ladder_complete") != ladder_complete
        or yb.get("ad_revenue_cents") != ad_revenue
        or yb.get("presale_revenue_cents") != presale_revenue
        or yb.get("production_phase") != phase
    )
    if changed:
        yb["ladder_filled_count"] = ladder_filled
        yb["ladder_complete"] = ladder_complete
        yb["ad_revenue_cents"] = ad_revenue
        yb["presale_revenue_cents"] = presale_revenue
        yb["production_phase"] = phase
        touch(yb)
