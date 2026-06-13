"""Lookup + ownership helpers shared by route modules."""
from db import db
from errors import err

# Map collection name -> store dict.
_COLLECTIONS = {
    "market": "markets",
    "vendor": "vendors",
    "permit": "permits",
    "application": "applications",
    "booth": "booths",
    "market_day": "market_days",
    "booth_assignment": "booth_assignments",
    "check_in": "check_ins",
    "sales_report": "sales_reports",
    "voucher_batch": "voucher_batches",
    "voucher_redemption": "voucher_redemptions",
}


def get_or_404(kind, rid):
    store = getattr(db, _COLLECTIONS[kind])
    obj = store.get(rid)
    if obj is None:
        raise err("ERR_NOT_FOUND", f"{kind} {rid} not found")
    return obj


def fk_or_404(kind, rid):
    """Body FK existence check -> ERR_NOT_FOUND (PRD §2.6)."""
    return get_or_404(kind, rid)


def vendor_owns_assignment(check_in):
    asg = db.booth_assignments.get(check_in["booth_assignment_id"])
    return asg["vendor_id"] if asg else None
