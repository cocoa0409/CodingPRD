"""Carrier and TPA onboarding (PRD section 3.1). Suspension toggles and is
narrow in scope: no cascades."""
from flask import Blueprint, request

import serialize
from db import STORE, new_entity, touch
from errors import raise_err, ERR_NAIC_CODE_EXISTS, ERR_LICENSE_NUMBER_EXISTS
from middleware import require_roles, ALL_ROLES
from response import success_object
from routes.common import get_or_404, render_list, filter_query
from validation import get_body, req_str

bp = Blueprint("carriers", __name__)


@bp.post("/mga/carriers")
def create_carrier():
    require_roles("PlatformAdmin")
    body = get_body()
    name = req_str(body, "name")
    naic_code = req_str(body, "naic_code")
    contact_email = req_str(body, "contact_email")
    for c in STORE.carriers.values():
        if c["naic_code"] == naic_code:
            raise_err(ERR_NAIC_CODE_EXISTS, "Carrier naic_code '%s' is already registered." % naic_code)
    c = new_entity()
    c.update({
        "name": name,
        "naic_code": naic_code,
        "contact_email": contact_email,
        "status": "ACTIVE",
    })
    STORE.carriers[c["id"]] = c
    return success_object(serialize.carrier(c), status=201)


@bp.get("/mga/carriers/<carrierId>")
def get_carrier(carrierId):
    require_roles(*ALL_ROLES)
    c = get_or_404(STORE.carriers, carrierId, "Carrier")
    return success_object(serialize.carrier(c))


@bp.get("/mga/carriers")
def list_carriers():
    require_roles(*ALL_ROLES)
    items = filter_query(list(STORE.carriers.values()), status=request.args.get("status"))
    return render_list(items, serialize.carrier)


@bp.post("/mga/carriers/<carrierId>/suspend")
def suspend_carrier(carrierId):
    """Toggles ACTIVE <-> SUSPENDED. Existing programs are not affected."""
    require_roles("PlatformAdmin")
    c = get_or_404(STORE.carriers, carrierId, "Carrier")
    c["status"] = "SUSPENDED" if c["status"] == "ACTIVE" else "ACTIVE"
    touch(c)
    return success_object(serialize.carrier(c))


@bp.post("/mga/tpas")
def create_tpa():
    require_roles("PlatformAdmin")
    body = get_body()
    name = req_str(body, "name")
    license_number = req_str(body, "license_number")
    contact_email = req_str(body, "contact_email")
    for t in STORE.tpas.values():
        if t["license_number"] == license_number:
            raise_err(ERR_LICENSE_NUMBER_EXISTS, "TPA license_number '%s' is already registered." % license_number)
    t = new_entity()
    t.update({
        "name": name,
        "license_number": license_number,
        "contact_email": contact_email,
        "status": "ACTIVE",
    })
    STORE.tpas[t["id"]] = t
    return success_object(serialize.tpa(t), status=201)


@bp.get("/mga/tpas/<tpaId>")
def get_tpa(tpaId):
    require_roles(*ALL_ROLES)
    t = get_or_404(STORE.tpas, tpaId, "TPA")
    return success_object(serialize.tpa(t))


@bp.get("/mga/tpas")
def list_tpas():
    require_roles(*ALL_ROLES)
    items = filter_query(list(STORE.tpas.values()), status=request.args.get("status"))
    return render_list(items, serialize.tpa)


@bp.post("/mga/tpas/<tpaId>/suspend")
def suspend_tpa(tpaId):
    """Toggles ACTIVE <-> SUSPENDED. In-flight claims and existing appointments
    are NOT cascaded; only new appointment create/activate is blocked."""
    require_roles("PlatformAdmin")
    t = get_or_404(STORE.tpas, tpaId, "TPA")
    t["status"] = "SUSPENDED" if t["status"] == "ACTIVE" else "ACTIVE"
    touch(t)
    return success_object(serialize.tpa(t))
