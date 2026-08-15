"""Collection action halt / complete (PRD 3.11)."""
from flask import Blueprint

from db import db
from errors import (
    raise_error, ERR_ACTION_NOT_FOUND, ERR_ACTION_NOT_INITIATED,
    ERR_ACCOUNT_NOT_IN_COLLECTIONS,
)
from middleware import authorized
from response import success_object
from routes.helpers import require
from services.core import public, touch
from util import CLOCK
from validate import get_body, opt_str

bp = Blueprint("collection_actions", __name__)


@bp.post("/charity-care/collection-actions/<cid>/halt")
def halt_action(cid):
    authorized(["ComplianceOfficer"])
    action = require("collection_actions", cid, ERR_ACTION_NOT_FOUND)
    if action["status"] != "INITIATED":
        raise_error(ERR_ACTION_NOT_INITIATED, "halt requires an INITIATED collection action")
    body = get_body()
    reason = opt_str(body, "reason")
    action["status"] = "HALTED"
    action["halted_at"] = CLOCK.now_iso()
    action["halt_reason"] = reason
    touch(action)
    return success_object(public(action))


@bp.post("/charity-care/collection-actions/<cid>/complete")
def complete_action(cid):
    authorized(["CollectionsAgent"])
    action = require("collection_actions", cid, ERR_ACTION_NOT_FOUND)
    if action["status"] != "INITIATED":
        raise_error(ERR_ACTION_NOT_INITIATED, "complete requires an INITIATED collection action")
    acct = db["accounts"].get(action["account_id"])
    if acct is None or acct["collection_posture"] not in ("ECA_ACTIVE", "ECA_ELIGIBLE"):
        raise_error(ERR_ACCOUNT_NOT_IN_COLLECTIONS,
                    "owning account must be in ECA_ACTIVE or ECA_ELIGIBLE")
    action["status"] = "COMPLETED"
    touch(action)
    return success_object(public(action))
