"""Title endpoints (PRD §3.2, §2.6 withdrawal cascade)."""

from flask import Blueprint, request

import db
import errors
import response
from middleware import authenticate, require_roles, ROLE_PATRON, ROLE_LIBRARIAN, ROLE_MANAGER
from services import serialize, derive
from routes import helpers

bp = Blueprint("titles", __name__)


@bp.post("/library/titles")
def create_title():
    caller = authenticate()
    require_roles(caller, {ROLE_LIBRARIAN, ROLE_MANAGER})
    body = helpers.get_json_body()

    helpers.require_fields(body, ["branch_id", "isbn", "title_text"])
    branch_id = helpers.require_string(body, "branch_id")
    isbn = helpers.require_string(body, "isbn")
    title_text = helpers.require_string(body, "title_text")

    helpers.find_or_404(db.branches, branch_id)

    record = {
        "branch_id": branch_id,
        "isbn": isbn,
        "title_text": title_text,
        "status": "ACTIVE",
        "default_replacement_cents": helpers.optional_int(body, "default_replacement_cents", 3000),
        "available_copy_count": 0,
        "total_copy_count": 0,
        "waiting_hold_count": 0,
    }
    db.stamp_create(record)
    db.titles[record["id"]] = record
    return response.object_response(serialize.title(record), status=201)


@bp.get("/library/titles/<tid>")
def get_title(tid):
    caller = authenticate()
    require_roles(caller, {ROLE_PATRON, ROLE_LIBRARIAN, ROLE_MANAGER})
    record = helpers.find_or_404(db.titles, tid)
    derive.reconcile_title(record)
    return response.object_response(serialize.title(record))


@bp.get("/library/titles")
def list_titles():
    caller = authenticate()
    require_roles(caller, {ROLE_PATRON, ROLE_LIBRARIAN, ROLE_MANAGER})
    branch_id = request.args.get("branch_id")
    isbn = request.args.get("isbn")
    records = [
        t for t in db.titles.values()
        if (branch_id is None or t["branch_id"] == branch_id)
        and (isbn is None or t["isbn"] == isbn)
    ]
    for t in records:
        derive.reconcile_title(t)
    return helpers.list_response(records, serialize.title)


@bp.post("/library/titles/<tid>/withdraw")
def withdraw_title(tid):
    caller = authenticate()
    require_roles(caller, {ROLE_MANAGER})
    record = helpers.find_or_404(db.titles, tid)

    # state (priority 5): only ACTIVE titles may be withdrawn
    if record["status"] != "ACTIVE":
        raise errors.invalid_state("Title is not ACTIVE.")

    record["status"] = "WITHDRAWN"

    # Cascade (PRD §2.6): AVAILABLE copies -> WITHDRAWN; ON_LOAN/ON_HOLD_SHELF kept.
    affected_patrons = set()
    for c in db.copies.values():
        if c["title_id"] == tid and c["status"] == "AVAILABLE":
            c["status"] = "WITHDRAWN"
            db.touch(c)

    # WAITING/READY holds -> CANCELLED. A cancelled READY hold's copy is on the
    # hold shelf; withdrawal leaves ON_HOLD_SHELF copies in place per §2.6, so we
    # do NOT promote a successor here (the title is being retired).
    for h in db.holds.values():
        if h["title_id"] == tid and h["status"] in ("WAITING", "READY"):
            h["status"] = "CANCELLED"
            h["ready_copy_id"] = None
            h["ready_at"] = None
            db.touch(h)
            affected_patrons.add(h["patron_id"])

    db.touch(record)
    derive.reconcile_title(record)
    for pid in affected_patrons:
        derive.reconcile_patron_by_id(pid)
    return response.object_response(serialize.title(record))
