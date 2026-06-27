"""ComplianceCredential (PTIN) endpoints (PRD §3.1, §2.8)."""
import re

from flask import Blueprint, request

import errors
from db import db
from middleware import get_identity, require_role
from models import make_credential, credential_dict, touch
from response import object_response, array_response
from routes.common import get_json_body, get_office, get_credential, paginate, page_slice
from timeutil import parse_iso

bp = Blueprint("credentials", __name__)

PTIN_RE = re.compile(r"^P\d{8}$")


@bp.post("/credentials")
def create_credential():
    _, role = get_identity()
    require_role(role, {"OfficeManager"})
    body = get_json_body()

    office_id = body.get("office_id")
    ptin = body.get("ptin")
    holder_name = body.get("holder_name")
    expires_on = body.get("expires_on")

    if not isinstance(office_id, str) or not office_id:
        raise errors.err(errors.ERR_INVALID_REQUEST, "office_id is required")
    # existence (404) of body FK comes before well-formedness of remaining fields
    get_office(office_id)

    if not isinstance(ptin, str) or not PTIN_RE.match(ptin):
        raise errors.err(errors.ERR_INVALID_REQUEST, "ptin must be P followed by eight digits")
    if not isinstance(holder_name, str) or not holder_name:
        raise errors.err(errors.ERR_INVALID_REQUEST, "holder_name is required")
    if not isinstance(expires_on, str) or not expires_on:
        raise errors.err(errors.ERR_INVALID_REQUEST, "expires_on is required")
    try:
        parse_iso(expires_on)
    except (ValueError, TypeError):
        raise errors.err(errors.ERR_INVALID_REQUEST, "expires_on is not a valid instant")

    cred = make_credential(office_id, ptin, holder_name, expires_on)
    return object_response(credential_dict(cred), 201)


@bp.get("/credentials/<credential_id>")
def get_credential_ep(credential_id):
    _, role = get_identity()
    require_role(role, {"OfficeManager", "TaxPreparer"})
    cred = get_credential(credential_id)
    return object_response(credential_dict(cred), 200)


@bp.get("/credentials")
def list_credentials():
    _, role = get_identity()
    require_role(role, {"OfficeManager", "TaxPreparer"})
    limit, offset = paginate()

    office_id = request.args.get("office_id")
    items = list(db.credentials.values())
    if office_id is not None:
        items = [c for c in items if c["office_id"] == office_id]

    page, total = page_slice(items, limit, offset)
    return array_response([credential_dict(c) for c in page], limit, offset, total, 200)


@bp.post("/credentials/<credential_id>/revoke")
def revoke_credential(credential_id):
    _, role = get_identity()
    require_role(role, {"OfficeManager"})
    cred = get_credential(credential_id)

    cred["status"] = "REVOKED"
    touch(cred)
    return object_response(credential_dict(cred), 200)
