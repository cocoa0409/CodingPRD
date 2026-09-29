"""Draft revisions: read surface (PRD 3.2). Drafts are created under a work item."""

from flask import Blueprint

from core import auth, envelope
from core.store import public, rows
from core.validation import apply_filters, load_path

bp = Blueprint("drafts", __name__)

FILTERS = ("work_item_id", "prior_draft_id", "status")


@bp.get("/sdo/drafts")
def list_drafts():
    auth.authenticate(auth.READ_ROLES)
    return envelope.list_response(apply_filters(rows("drafts"), FILTERS))


@bp.get("/sdo/drafts/<draft_id>")
def get_draft(draft_id):
    auth.authenticate(auth.READ_ROLES)
    return envelope.object_response(public(load_path("drafts", draft_id)))
