"""Entity -> output JSON serializers.

Each serializer returns a plain dict with datetimes formatted to ISO 8601 ms-UTC
and internal bookkeeping fields (_seq) stripped. Derived counters are assumed to
have been reconciled by the caller before serialization.
"""

from timeutil import iso, add_days
from constants import PICKUP_WINDOW_DAYS
import db


def _common(record):
    return {
        "id": record["id"],
        "created_at": iso(record["created_at"]),
        "updated_at": iso(record["updated_at"]),
        "version": record["version"],
    }


def branch(b):
    out = _common(b)
    out.update({
        "name": b["name"],
        "fine_free": b["fine_free"],
        "daily_fine_cents": b["daily_fine_cents"],
        "max_fine_cents": b["max_fine_cents"],
        "grace_days": b["grace_days"],
        "loan_period_days": b["loan_period_days"],
        "block_threshold_cents": b["block_threshold_cents"],
        "reservation_buffer_minutes": b["reservation_buffer_minutes"],
    })
    return out


def patron(p):
    out = _common(p)
    out.update({
        "branch_id": p["branch_id"],
        "full_name": p["full_name"],
        "patron_type": p["patron_type"],
        "card_status": p["card_status"],
        "borrowing_status": p.get("borrowing_status", "CLEAR"),
        "checkout_limit": p["checkout_limit"],
        "hold_limit": p["hold_limit"],
        "active_loan_count": p.get("active_loan_count", 0),
        "active_hold_count": p.get("active_hold_count", 0),
        "total_owed_cents": p.get("total_owed_cents", 0),
        "ready_pickup_count": p.get("ready_pickup_count", 0),
    })
    return out


def title(t):
    out = _common(t)
    out.update({
        "branch_id": t["branch_id"],
        "isbn": t["isbn"],
        "title_text": t["title_text"],
        "status": t["status"],
        "default_replacement_cents": t["default_replacement_cents"],
        "available_copy_count": t.get("available_copy_count", 0),
        "total_copy_count": t.get("total_copy_count", 0),
        "waiting_hold_count": t.get("waiting_hold_count", 0),
    })
    return out


def copy(c):
    out = _common(c)
    out.update({
        "title_id": c["title_id"],
        "branch_id": c["branch_id"],
        "barcode": c["barcode"],
        "status": c["status"],
        "acquired_on": iso(c["acquired_on"]),
        "condition_factor": c["condition_factor"],
    })
    return out


def loan(ln):
    out = _common(ln)
    out.update({
        "copy_id": ln["copy_id"],
        "patron_id": ln["patron_id"],
        "status": ln["status"],
        "checked_out_at": iso(ln["checked_out_at"]),
        "due_date": iso(ln["due_date"]),
        "renewal_count": ln["renewal_count"],
        "returned_at": iso(ln["returned_at"]),
        "accrued_fine_cents": ln["accrued_fine_cents"],
    })
    return out


def hold(h):
    """Serialize a hold. queue_position and pickup_deadline are derived on read."""
    from services import derive
    out = _common(h)
    qp = derive.queue_position_of(h)
    pickup_deadline = None
    if h.get("ready_at") is not None:
        pickup_deadline = iso(add_days(h["ready_at"], PICKUP_WINDOW_DAYS))
    out.update({
        "title_id": h["title_id"],
        "patron_id": h["patron_id"],
        "status": h["status"],
        "queue_position": qp,
        "ready_copy_id": h.get("ready_copy_id"),
        "ready_at": iso(h.get("ready_at")),
        "pickup_deadline": pickup_deadline,
    })
    return out


def reservation(r):
    out = _common(r)
    out.update({
        "resource_id": r["resource_id"],
        "patron_id": r["patron_id"],
        "status": r["status"],
        "start_at": iso(r["start_at"]),
        "end_at": iso(r["end_at"]),
        "checked_in_at": iso(r.get("checked_in_at")),
    })
    return out


def resource(res):
    out = _common(res)
    out.update({
        "branch_id": res["branch_id"],
        "resource_kind": res["resource_kind"],
        "label": res["label"],
        "capacity": res["capacity"],
        "status": res["status"],
    })
    return out


def ill_request(ir):
    out = _common(ir)
    out.update({
        "patron_id": ir["patron_id"],
        "branch_id": ir["branch_id"],
        "isbn": ir["isbn"],
        "status": ir["status"],
        "lending_fee_cents": ir["lending_fee_cents"],
    })
    return out


def license_pool(pl):
    out = _common(pl)
    out.update({
        "title_id": pl["title_id"],
        "total_licenses": pl["total_licenses"],
        "loan_term_days": pl["loan_term_days"],
        "loaned_licenses": pl.get("loaned_licenses", 0),
        "available_licenses": pl.get("available_licenses", pl["total_licenses"]),
    })
    return out


def ebook_loan(e):
    out = _common(e)
    out.update({
        "pool_id": e["pool_id"],
        "patron_id": e["patron_id"],
        "status": e["status"],
        "checked_out_at": iso(e["checked_out_at"]),
        "expires_at": iso(e["expires_at"]),
    })
    return out


def fine(f):
    out = _common(f)
    out.update({
        "patron_id": f["patron_id"],
        "loan_id": f.get("loan_id"),
        "fine_type": f["fine_type"],
        "amount_cents": f["amount_cents"],
        "settlement_status": f["settlement_status"],
        "settled_at": iso(f.get("settled_at")),
    })
    return out
