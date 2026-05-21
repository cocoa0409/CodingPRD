"""Fine read/list/waive."""
from flask import request

from ..auth import parse_headers, require_role
from ..envelope import success
from ..errors import fail
from ..pagination import parse_pagination, window
from ..server import store


def register(app, prefix):
    app.add_url_rule("/api/fines/<fid>", endpoint=f"{prefix}.read", view_func=read, methods=["GET"])
    app.add_url_rule("/api/fines", endpoint=f"{prefix}.list", view_func=list_fines, methods=["GET"])
    app.add_url_rule("/api/fines/<fid>/waive", endpoint=f"{prefix}.waive", view_func=waive, methods=["POST"])


def _subject_visible(f, user_id, role) -> bool:
    if role in ("PlatformAdmin", "CustomerService"):
        return True
    if role == "Rider":
        return f["subject_type"] == "RIDER" and f["subject_id"] == user_id
    if role == "Restaurant":
        return f["subject_type"] == "RESTAURANT" and f["subject_id"] == user_id
    if role == "Customer":
        return f["subject_type"] == "CUSTOMER" and f["subject_id"] == user_id
    return False


def read(fid):
    user_id, role = parse_headers()
    require_role("PlatformAdmin", "CustomerService", "Rider", "Restaurant", "Customer")
    f = store.fines.get(fid)
    if not f:
        raise fail("ERR_NOT_FOUND")
    if not _subject_visible(f, user_id, role):
        raise fail("ERR_FORBIDDEN")
    return success(f)


def list_fines():
    user_id, role = parse_headers()
    require_role("PlatformAdmin", "CustomerService", "Rider", "Restaurant", "Customer")
    limit, offset = parse_pagination()
    subject_type = request.args.get("subject_type")
    subject_id = request.args.get("subject_id")
    settlement_status = request.args.get("settlement_status")
    # Role-scope: non-CS/Admin must only query their own subject
    if role == "Rider":
        if subject_id is not None and subject_id != user_id:
            raise fail("ERR_FORBIDDEN")
        subject_id = user_id
        subject_type = "RIDER"
    elif role == "Restaurant":
        if subject_id is not None and subject_id != user_id:
            raise fail("ERR_FORBIDDEN")
        subject_id = user_id
        subject_type = "RESTAURANT"
    elif role == "Customer":
        if subject_id is not None and subject_id != user_id:
            raise fail("ERR_FORBIDDEN")
        subject_id = user_id
        subject_type = "CUSTOMER"
    rows = list(store.fines.values())
    if subject_type:
        rows = [f for f in rows if f["subject_type"] == subject_type]
    if subject_id:
        rows = [f for f in rows if f["subject_id"] == subject_id]
    if settlement_status:
        rows = [f for f in rows if f["settlement_status"] == settlement_status]
    rows.sort(key=lambda f: f["created_at"])
    page, meta = window(rows, limit, offset)
    return success(page, page=meta, response_type="array")


def waive(fid):
    from ..services.fines import waive_fine
    return waive_fine(fid)
