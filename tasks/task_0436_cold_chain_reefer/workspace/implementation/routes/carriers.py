"""Carrier endpoints (PRD §3.1)."""

from flask import Blueprint, request

from constants import CARRIER_LIABILITY_CAP_DEFAULT
from db import store
from helpers import get_carrier_or_404, pagination_params, paginate
from middleware import authenticate, require_role
from models import serialize, stamp_create, touch
from response import array_response, object_response
from validators import as_bool, as_int, as_string, get_body, require

bp = Blueprint("carriers", __name__)


@bp.route("/carriers", methods=["POST"])
def create_carrier():
    _uid, role = authenticate()
    require_role(role, {"Carrier", "PlatformAdmin"})

    body = get_body(request)
    legal_name = as_string(require(body, "legal_name"), "legal_name")

    fsma_registered = False
    if body.get("fsma_registered") is not None:
        fsma_registered = as_bool(body["fsma_registered"], "fsma_registered")

    sanitary_training_current = False
    if body.get("sanitary_training_current") is not None:
        sanitary_training_current = as_bool(
            body["sanitary_training_current"], "sanitary_training_current"
        )

    liability_cap_cents = CARRIER_LIABILITY_CAP_DEFAULT
    if body.get("liability_cap_cents") is not None:
        liability_cap_cents = as_int(
            body["liability_cap_cents"], "liability_cap_cents", minimum=0
        )

    rec = {
        "legal_name": legal_name,
        "fsma_registered": fsma_registered,
        "sanitary_training_current": sanitary_training_current,
        "liability_cap_cents": liability_cap_cents,
    }
    stamp_create(rec)
    store.carriers[rec["id"]] = rec
    return object_response(serialize(rec), 201)


@bp.route("/carriers/<cid>", methods=["GET"])
def get_carrier(cid):
    _uid, role = authenticate()
    require_role(role, {"Carrier", "Shipper", "ComplianceOfficer", "PlatformAdmin"})
    rec = get_carrier_or_404(cid)
    return object_response(serialize(rec), 200)


@bp.route("/carriers/<cid>", methods=["PATCH"])
def patch_carrier(cid):
    _uid, role = authenticate()
    require_role(role, {"Carrier", "PlatformAdmin"})
    rec = get_carrier_or_404(cid)

    body = get_body(request)
    changed = False
    if body.get("fsma_registered") is not None:
        rec["fsma_registered"] = as_bool(body["fsma_registered"], "fsma_registered")
        changed = True
    if body.get("sanitary_training_current") is not None:
        rec["sanitary_training_current"] = as_bool(
            body["sanitary_training_current"], "sanitary_training_current"
        )
        changed = True
    if body.get("liability_cap_cents") is not None:
        rec["liability_cap_cents"] = as_int(
            body["liability_cap_cents"], "liability_cap_cents", minimum=0
        )
        changed = True

    if changed:
        touch(rec)
    return object_response(serialize(rec), 200)


@bp.route("/carriers", methods=["GET"])
def list_carriers():
    _uid, role = authenticate()
    require_role(role, {"Carrier", "Shipper", "ComplianceOfficer", "PlatformAdmin"})
    limit, offset = pagination_params()
    records = list(store.carriers.values())
    page, total = paginate(records, limit, offset)
    return array_response(page, limit, offset, total)
