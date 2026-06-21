"""Attorney routes (PRD §3.1)."""

from flask import Blueprint

from db import db
from errors import raise_api
from middleware import require_roles
from response import success
from services import models
from services.body import get_json_body, require_nonempty_string

bp = Blueprint("attorneys", __name__)


@bp.post("/attorneys")
@require_roles("Attorney")
def create_attorney(_user_id, _role):
    body = get_json_body()
    full_name = require_nonempty_string(body, "full_name")
    bar_number = require_nonempty_string(body, "bar_number")
    bar_state = require_nonempty_string(body, "bar_state")
    if not (len(bar_state) == 2 and bar_state.isalpha() and bar_state.isupper()):
        raise_api("ERR_VALIDATION", "bar_state must be 2 uppercase letters")

    # bar_number unique across Attorney.
    for a in db.attorneys.values():
        if a["bar_number"] == bar_number:
            raise_api("ERR_DUPLICATE_BAR_NUMBER", "bar_number already registered")

    rec = models.make_record({
        "full_name": full_name,
        "bar_number": bar_number,
        "bar_state": bar_state,
        "status": "ACTIVE",
    })
    db.attorneys[rec["id"]] = rec
    return success(models.ser_attorney(rec), 201)


@bp.get("/attorneys/<rid>")
@require_roles("Attorney", "Examiner", "TTABClerk")
def get_attorney(rid, _user_id, _role):
    rec = models.get_or_404(db.attorneys, rid, "Attorney")
    return success(models.ser_attorney(rec), 200)


@bp.post("/attorneys/<rid>/suspend")
@require_roles("Examiner")
def suspend_attorney(rid, _user_id, _role):
    rec = models.get_or_404(db.attorneys, rid, "Attorney")
    rec["status"] = "SUSPENDED"
    models.touch(rec)
    return success(models.ser_attorney(rec), 200)
