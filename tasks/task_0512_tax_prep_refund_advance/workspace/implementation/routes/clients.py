"""Client (taxpayer) endpoints (PRD §3.2)."""
import re

from flask import Blueprint

import errors
from db import db
from middleware import get_identity, require_role
from models import make_client, client_dict
from response import object_response, array_response
from routes.common import get_json_body, get_office, get_client, paginate, page_slice
from constants import RISK_BANDS

bp = Blueprint("clients", __name__)

SSN4_RE = re.compile(r"^\d{4}$")


@bp.post("/offices/<office_id>/clients")
def intake_client(office_id):
    _, role = get_identity()
    require_role(role, {"FrontDeskAgent", "OfficeManager"})
    get_office(office_id)
    body = get_json_body()

    full_name = body.get("full_name")
    ssn_last4 = body.get("ssn_last4")
    if not isinstance(full_name, str) or not full_name:
        raise errors.err(errors.ERR_INVALID_REQUEST, "full_name is required")
    if not isinstance(ssn_last4, str) or not SSN4_RE.match(ssn_last4):
        raise errors.err(errors.ERR_INVALID_REQUEST, "ssn_last4 must be exactly four digits")

    risk_band = body.get("risk_band", "MEDIUM")
    if risk_band not in RISK_BANDS:
        raise errors.err(errors.ERR_INVALID_REQUEST, "risk_band must be LOW, MEDIUM, or HIGH")

    is_returning = body.get("is_returning", False)
    if not isinstance(is_returning, bool):
        raise errors.err(errors.ERR_INVALID_REQUEST, "is_returning must be boolean")

    client = make_client(office_id, full_name, ssn_last4, risk_band, is_returning)
    return object_response(client_dict(client), 201)


@bp.get("/offices/<office_id>/clients")
def list_office_clients(office_id):
    _, role = get_identity()
    require_role(role, {"FrontDeskAgent", "OfficeManager", "TaxPreparer"})
    get_office(office_id)
    limit, offset = paginate()

    items = [c for c in db.clients.values() if c["office_id"] == office_id]
    page, total = page_slice(items, limit, offset)
    return array_response([client_dict(c) for c in page], limit, offset, total, 200)


@bp.get("/clients/<client_id>")
def get_client_ep(client_id):
    _, role = get_identity()
    require_role(role, {"FrontDeskAgent", "OfficeManager", "TaxPreparer", "BankProductOfficer"})
    client = get_client(client_id)
    return object_response(client_dict(client), 200)
