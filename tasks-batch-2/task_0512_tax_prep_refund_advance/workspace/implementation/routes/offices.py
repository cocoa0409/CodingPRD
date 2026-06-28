"""Office (storefront) endpoints (PRD §3.1, §2.8)."""
import re

from flask import Blueprint

import errors
from db import db
from middleware import get_identity, require_role
from models import make_office, office_dict, touch
from response import object_response
from routes.common import get_json_body, get_office

bp = Blueprint("offices", __name__)

EFIN_RE = re.compile(r"^\d{6}$")


@bp.post("/offices")
def create_office():
    _, role = get_identity()
    require_role(role, {"OfficeManager"})
    body = get_json_body()

    name = body.get("name")
    efin = body.get("efin")
    state_code = body.get("state_code")
    if not isinstance(name, str) or not name:
        raise errors.err(errors.ERR_INVALID_REQUEST, "name is required")
    if not isinstance(efin, str) or not EFIN_RE.match(efin):
        raise errors.err(errors.ERR_INVALID_REQUEST, "efin must be exactly six digits")
    if not isinstance(state_code, str) or not state_code:
        raise errors.err(errors.ERR_INVALID_REQUEST, "state_code is required")

    bank_product_enabled = body.get("bank_product_enabled", False)
    if not isinstance(bank_product_enabled, bool):
        raise errors.err(errors.ERR_INVALID_REQUEST, "bank_product_enabled must be boolean")

    office = make_office(name, efin, state_code, bank_product_enabled)
    return object_response(office_dict(office), 201)


@bp.get("/offices/<office_id>")
def get_office_ep(office_id):
    _, role = get_identity()
    require_role(role, {"OfficeManager", "FrontDeskAgent", "TaxPreparer", "BankProductOfficer"})
    office = get_office(office_id)
    return object_response(office_dict(office), 200)


@bp.post("/offices/<office_id>/efin-status")
def set_efin_status(office_id):
    _, role = get_identity()
    require_role(role, {"OfficeManager"})
    office = get_office(office_id)
    body = get_json_body()

    status = body.get("efin_status")
    if status not in ("ACTIVE", "SUSPENDED"):
        raise errors.err(errors.ERR_INVALID_REQUEST, "efin_status must be ACTIVE or SUSPENDED")

    office["efin_status"] = status
    touch(office)
    return object_response(office_dict(office), 200)
