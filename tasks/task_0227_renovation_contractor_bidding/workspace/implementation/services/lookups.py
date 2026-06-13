"""Existence-checked entity lookups (ERR_NOT_FOUND, priority 4)."""
import db
import errors


def _get(store, rid):
    rec = store.get(rid)
    if rec is None:
        raise errors.not_found(f"Resource not found: {rid}.")
    return rec


def get_homeowner(rid):
    return _get(db.homeowners, rid)


def get_contractor(rid):
    return _get(db.contractors, rid)


def get_project(rid):
    return _get(db.projects, rid)


def get_scope_line_item(rid):
    return _get(db.scope_line_items, rid)


def get_bid(rid):
    return _get(db.bids, rid)


def get_bid_line_item(rid):
    return _get(db.bid_line_items, rid)


def get_milestone(rid):
    return _get(db.milestones, rid)


def get_escrow(rid):
    return _get(db.escrows, rid)


def get_draw(rid):
    return _get(db.draws, rid)


def get_lien_waiver(rid):
    return _get(db.lien_waivers, rid)


def get_change_order(rid):
    return _get(db.change_orders, rid)


def get_dispute(rid):
    return _get(db.disputes, rid)


# ---- collection scans (no pagination) -------------------------------------
def scope_items_for_project(project_id):
    return [s for s in db.scope_line_items.values() if s["project_id"] == project_id]


def milestones_for_project(project_id):
    return [m for m in db.milestones.values() if m["project_id"] == project_id]


def bids_for_project(project_id):
    return [b for b in db.bids.values() if b["project_id"] == project_id]


def line_items_for_bid(bid_id):
    return [li for li in db.bid_line_items.values() if li["bid_id"] == bid_id]


def escrow_for_project(project_id):
    for e in db.escrows.values():
        if e["project_id"] == project_id:
            return e
    return None
