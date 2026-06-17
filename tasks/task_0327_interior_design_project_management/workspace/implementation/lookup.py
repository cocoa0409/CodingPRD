"""Existence lookups, ownership checks, and list helpers.

Existence is validation priority 3 (PRD §2.5/§2.6): ERR_NOT_FOUND, validated
left-to-right; child must belong to the parent named in the path.

Client ownership (PRD §2.1): the Client role is entity-backed; a Client may only
act on / read a Project whose client_user_id equals their X-User-ID, and only on
artifacts belonging to such a project. Mismatch -> ERR_FORBIDDEN.
"""
import db
from errors import err


def get_or_404(store, rid):
    rec = store.get(rid)
    if rec is None:
        raise err("ERR_NOT_FOUND", "Resource not found.")
    return rec


# --- entity getters that raise ERR_NOT_FOUND ---
def get_project(pid):
    return get_or_404(db.projects, pid)


def get_client(cid):
    return get_or_404(db.clients, cid)


def get_room(rid):
    return get_or_404(db.rooms, rid)


def get_moodboard(mid):
    return get_or_404(db.moodboards, mid)


def get_ffe_item(fid):
    return get_or_404(db.ffe_items, fid)


def get_selection(sid):
    return get_or_404(db.selections, sid)


def get_vendor(vid):
    return get_or_404(db.vendors, vid)


def get_order(oid):
    return get_or_404(db.orders, oid)


def get_order_line(olid):
    return get_or_404(db.order_lines, olid)


def get_revision(rid):
    return get_or_404(db.revisions, rid)


def get_punch_item(pid):
    return get_or_404(db.punch_items, pid)


def get_time_entry(tid):
    return get_or_404(db.time_entries, tid)


def get_payment(pid):
    return get_or_404(db.payments, pid)


# --- ownership: a Client may only touch their own project / its artifacts ---
def check_client_owns_project(role, user_id, project):
    if role == "Client" and project["client_user_id"] != user_id:
        raise err("ERR_FORBIDDEN", "Client does not own this project.")


def project_of_order(order):
    return db.projects.get(order["project_id"])


def project_of_room(room):
    return db.projects.get(room["project_id"])


def project_of_selection(sel):
    return db.projects.get(sel["project_id"])


def project_of_moodboard(mb):
    room = db.rooms.get(mb["room_id"])
    return db.projects.get(room["project_id"]) if room else None


def project_of_revision(rev):
    return db.projects.get(rev["project_id"])


def project_of_punch_item(pi):
    order = db.orders.get(pi["order_id"])
    return db.projects.get(order["project_id"]) if order else None


def project_of_time_entry(te):
    return db.projects.get(te["project_id"])


def project_of_payment(pay):
    return db.projects.get(pay["project_id"])


def project_of_order_line(ol):
    order = db.orders.get(ol["order_id"])
    return db.projects.get(order["project_id"]) if order else None


def paginate_sorted(records, limit, offset):
    """Sort by created_at ASC (tie-break insertion seq), then slice (PRD §2.3)."""
    ordered = sorted(records, key=lambda r: (r["created_at"], r["_seq"]))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return page, total
