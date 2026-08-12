"""Certificate void endpoint (PRD §3.5)."""

from flask import Blueprint

import db
import serialize
import utils
from errors import ApiError, ERR_CERTIFICATE_NOT_FOUND, ERR_INVALID_STATE
from middleware import require_roles
from response import ok_object

bp = Blueprint("certificates", __name__)


@bp.post("/itad/certificates/<certificate_id>/void")
def void_certificate(certificate_id):
    uid, role = require_roles("ComplianceOfficer")
    certificate = db.certificates.get(certificate_id)
    if certificate is None:
        raise ApiError(ERR_CERTIFICATE_NOT_FOUND, 404, "no Certificate with the given id")
    if certificate["status"] != "ISSUED":
        raise ApiError(ERR_INVALID_STATE, 409, "only ISSUED certificates can be voided")
    certificate["status"] = "VOIDED"
    utils.touch(certificate)
    return ok_object(serialize.certificate(certificate))
