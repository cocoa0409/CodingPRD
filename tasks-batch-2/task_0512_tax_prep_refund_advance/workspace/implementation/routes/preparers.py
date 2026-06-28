"""Preparer endpoints (PRD §3.1)."""
from flask import Blueprint, request

import errors
from db import db
from middleware import get_identity, require_role
from models import make_preparer, preparer_dict
from response import object_response, array_response
from routes.common import (get_json_body, get_office, get_credential, get_preparer,
                           paginate, page_slice)

bp = Blueprint("preparers", __name__)


@bp.post("/offices/<office_id>/preparers")
def add_preparer(office_id):
    _, role = get_identity()
    require_role(role, {"OfficeManager"})
    get_office(office_id)
    body = get_json_body()

    credential_id = body.get("credential_id")
    full_name = body.get("full_name")
    if not isinstance(credential_id, str) or not credential_id:
        raise errors.err(errors.ERR_INVALID_REQUEST, "credential_id is required")
    # existence of body FK before remaining well-formedness
    get_credential(credential_id)

    if not isinstance(full_name, str) or not full_name:
        raise errors.err(errors.ERR_INVALID_REQUEST, "full_name is required")

    max_open_returns = body.get("max_open_returns", 25)
    if not isinstance(max_open_returns, int) or isinstance(max_open_returns, bool):
        raise errors.err(errors.ERR_INVALID_REQUEST, "max_open_returns must be an integer")

    prep = make_preparer(office_id, credential_id, full_name, max_open_returns)
    return object_response(preparer_dict(prep), 201)


@bp.get("/offices/<office_id>/preparers")
def list_office_preparers(office_id):
    _, role = get_identity()
    require_role(role, {"OfficeManager", "FrontDeskAgent", "TaxPreparer"})
    get_office(office_id)
    limit, offset = paginate()

    items = [p for p in db.preparers.values() if p["office_id"] == office_id]
    page, total = page_slice(items, limit, offset)
    return array_response([preparer_dict(p) for p in page], limit, offset, total, 200)


@bp.get("/preparers/<preparer_id>")
def get_preparer_ep(preparer_id):
    _, role = get_identity()
    require_role(role, {"OfficeManager", "FrontDeskAgent", "TaxPreparer", "BankProductOfficer"})
    prep = get_preparer(preparer_id)
    return object_response(preparer_dict(prep), 200)


@bp.get("/preparers")
def list_preparers():
    _, role = get_identity()
    require_role(role, {"OfficeManager", "TaxPreparer"})
    limit, offset = paginate()

    credential_id = request.args.get("credential_id")
    items = list(db.preparers.values())
    if credential_id is not None:
        items = [p for p in items if p["credential_id"] == credential_id]

    page, total = page_slice(items, limit, offset)
    return array_response([preparer_dict(p) for p in page], limit, offset, total, 200)
