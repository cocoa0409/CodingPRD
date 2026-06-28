"""Build a priced Quote for a project (PRD §3.2). Used by ESTIMATE + FINAL paths."""
from db import db
from services import common, calculations


def _current_accepted_measurement(project_id):
    """The currently ACCEPTED measurement for the project (drives add-ons)."""
    for m in db.measurements.values():
        if m["project_id"] == project_id and m["status"] == "ACCEPTED":
            return m
    return None


def _next_revision_no(project_id):
    """1-based: (max existing revision_no on project) + 1, never less than 1."""
    max_rev = 0
    for q in db.quotes.values():
        if q["project_id"] == project_id:
            max_rev = max(max_rev, q["revision_no"])
    return max_rev + 1


def build_quote(project, variant, status="ISSUED"):
    """Create and store a priced Quote of the given variant. Returns the quote."""
    measurement = _current_accepted_measurement(project["id"])
    existing_slab = measurement["existing_slab"] if measurement else False

    base = calculations.quote_base_price(
        project["footprint_sqft"], project["structure_type"], project["material"])
    addons = calculations.quote_addons_total(
        existing_slab, project["requires_engineering"], project["requires_hoa"])
    tax, total = calculations.quote_tax(base, addons)

    quote = {
        "project_id": project["id"],
        "revision_no": _next_revision_no(project["id"]),
        "variant": variant,
        "base_price_cents": base,
        "addons_cents": addons,
        "tax_cents": tax,
        "total_cents": total,
        "status": status,
    }
    common.stamp_create(quote)
    db.quotes[quote["id"]] = quote
    return quote
