"""NocRecord apply (originator marks the correction applied)."""

from __future__ import annotations

from flask import Blueprint

import db
from db import touch
from errors import raise_err, ERR_NOC_NOT_ACTIONABLE, ERR_NOT_FOUND, ERR_RESOURCE_OWNERSHIP
from middleware import require_roles
from response import success_object
from services.domain import originator_id_of_entry

bp = Blueprint("nocs", __name__)


@bp.route("/ach/noc-records/<noc_id>/apply", methods=["POST"])
@require_roles("OriginatorOps")
def apply_noc(noc_id: str, _user_id: str, _role: str):
    # Existence (p4)
    noc = db.noc_records.get(noc_id)
    if noc is None:
        raise_err(ERR_NOT_FOUND, "NocRecord not found")
    # Ownership (p3): NOC -> entry -> file -> originator id == X-User-ID.
    entry = db.ach_entries[noc["entry_id"]]
    if originator_id_of_entry(entry) != _user_id:
        raise_err(ERR_RESOURCE_OWNERSHIP, "Caller does not own this NOC's entry's file")
    # State (p6)
    if noc["status"] not in ("RECEIVED", "OVERDUE"):
        raise_err(ERR_NOC_NOT_ACTIONABLE, "NocRecord is already APPLIED")

    if noc["status"] == "OVERDUE":
        # Late application while OVERDUE is recorded.
        noc["late_applied"] = True
    noc["status"] = "APPLIED"
    touch(noc)
    return success_object(noc)
