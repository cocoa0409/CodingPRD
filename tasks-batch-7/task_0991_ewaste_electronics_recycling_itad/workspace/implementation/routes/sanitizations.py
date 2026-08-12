"""DataSanitization verification endpoint (PRD §3.5)."""

from flask import Blueprint

import db
import serialize
import utils
from errors import (ApiError, ERR_INVALID_STATE, ERR_SANITIZATION_NOT_FOUND,
                    ERR_SEGREGATION_OF_DUTIES)
from middleware import require_roles
from response import ok_object

bp = Blueprint("sanitizations", __name__)


@bp.post("/itad/sanitizations/<sanitization_id>/verify")
def verify_sanitization(sanitization_id):
    uid, role = require_roles("ComplianceOfficer")
    record = db.sanitizations.get(sanitization_id)
    if record is None:
        raise ApiError(ERR_SANITIZATION_NOT_FOUND, 404,
                       "no DataSanitization with the given id")
    data = utils.body_json()
    verdict = utils.req_enum(data, "verdict", {"APPROVE", "REJECT"})
    if record["status"] != "LOGGED":
        raise ApiError(ERR_INVALID_STATE, 409, "only LOGGED records can be verified")
    # Segregation of duties is enforced before the verdict is considered.
    if uid == record["logged_by_id"]:
        raise ApiError(ERR_SEGREGATION_OF_DUTIES, 403,
                       "verifier must differ from the technician who logged the attempt")
    item = db.items[record["item_id"]]
    record["verified_by_id"] = uid
    if verdict == "APPROVE":
        if record["outcome"] != "PASS":
            raise ApiError(ERR_INVALID_STATE, 409,
                           "a FAIL attempt cannot be verified")
        record["status"] = "VERIFIED"
        item["data_status"] = "VERIFIED"
    else:
        record["status"] = "REJECTED"
        item["data_status"] = "PENDING"  # retry loop opens
    utils.touch(record)
    utils.touch(item)
    return ok_object(serialize.sanitization(record))
