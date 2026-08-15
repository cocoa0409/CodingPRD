"""Run endpoints: fetch one run and list bids referencing a run."""
from flask import request, Blueprint

from db import db, ser
from helpers import get_run_or_404, paginated
from middleware import authenticate, require_roles, ALL_ROLES, READ_SO_OP_UR
from response import ok_obj

bp = Blueprint("runs", __name__)


@bp.get("/api/runs/<rid>")
def get_run(rid):
    auth = authenticate()
    require_roles(auth, ALL_ROLES)
    return ok_obj(ser(get_run_or_404(rid)))


@bp.get("/api/runs/<rid>/bid-entries")
def run_bids(rid):
    auth = authenticate()
    require_roles(auth, READ_SO_OP_UR)
    get_run_or_404(rid)
    items = [b for b in db.bid_entries.values() if b["run_id"] == rid]
    status = request.args.get("status")
    if status is not None:
        items = [b for b in items if b["status"] == status]
    return paginated(items)
