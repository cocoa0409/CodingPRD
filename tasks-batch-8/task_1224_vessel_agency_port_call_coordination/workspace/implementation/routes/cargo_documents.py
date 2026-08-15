"""CargoDocument endpoints."""
from flask import Blueprint, request

from errors import invalid_request, invalid_state, not_found, raise_err
from middleware import require_roles, ANY_ROLE
from response import ok_list, ok_object
from services import domain
from services.serializers import serialize, serialize_many
from utils import new_entity, paginate, pagination_args, sort_created, touch

bp = Blueprint("cargo_documents", __name__)

DOC_TYPES = {"BILL_OF_LADING", "CARGO_MANIFEST", "DELIVERY_ORDER"}


def _get_or_404(did):
    ent = domain.get("cargo_documents", did)
    if ent is None:
        not_found("cargo document")
    return ent


@bp.post("/cargo-documents")
def create_cargo_document():
    require_roles(["AgencyOps"])
    body = request.get_json(silent=True) or {}
    call = None
    pcid = body.get("port_call_id")
    if isinstance(pcid, str):
        call = domain.get("port_calls", pcid)
        if call is None:
            not_found("port call")
    bl = body.get("bl_number")
    if call is not None and isinstance(bl, str):
        for doc in domain.all_of("cargo_documents"):
            if (doc["port_call_id"] == pcid and doc["bl_number"] == bl
                    and doc["status"] != "RELEASED"):
                raise_err("ERR_DUPLICATE_BL_NUMBER",
                          "This bl_number is already registered on the port call")
    if call is not None:
        domain.require_call_editable(call)
    freight_paid = body.get("freight_paid", False)
    if (call is None
            or body.get("doc_type") not in DOC_TYPES
            or not isinstance(bl, str) or not bl
            or not isinstance(body.get("consignee_name"), str) or not body.get("consignee_name")
            or not isinstance(freight_paid, bool)):
        invalid_request("invalid cargo document payload")
    ent = new_entity("cargo_documents", {
        "port_call_id": pcid,
        "doc_type": body["doc_type"],
        "bl_number": bl,
        "consignee_name": body["consignee_name"],
        "freight_paid": freight_paid,
        "status": "RECEIVED",
    })
    return ok_object(serialize(ent), status=201)


@bp.get("/cargo-documents")
def list_cargo_documents():
    require_roles(ANY_ROLE)
    items = list(domain.all_of("cargo_documents"))
    for param in ("port_call_id", "status", "doc_type"):
        value = request.args.get(param)
        if value is not None:
            items = [d for d in items if d[param] == value]
    items = sort_created(items)
    limit, offset = pagination_args(request.args)
    page, total, has_more = paginate(items, limit, offset)
    return ok_list(serialize_many(page), total, limit, offset, has_more)


@bp.get("/cargo-documents/<did>")
def get_cargo_document(did):
    require_roles(ANY_ROLE)
    return ok_object(serialize(_get_or_404(did)))


@bp.post("/cargo-documents/<did>/verify")
def verify_cargo_document(did):
    require_roles(["AgencyOps"])
    ent = _get_or_404(did)
    if ent["status"] != "RECEIVED":
        invalid_state("Only a RECEIVED cargo document can be verified")
    call = domain.get("port_calls", ent["port_call_id"])
    if call is not None:
        domain.require_call_editable(call)
    ent["status"] = "VERIFIED"
    touch(ent)
    return ok_object(serialize(ent))


@bp.post("/cargo-documents/<did>/hold")
def hold_cargo_document(did):
    require_roles(["AgencyOps"])
    ent = _get_or_404(did)
    if ent["status"] != "VERIFIED":
        invalid_state("Only a VERIFIED cargo document can be placed on hold")
    ent["status"] = "ON_HOLD"
    touch(ent)
    return ok_object(serialize(ent))


@bp.post("/cargo-documents/<did>/release-hold")
def release_hold_cargo_document(did):
    require_roles(["AgencyOps"])
    ent = _get_or_404(did)
    if ent["status"] != "ON_HOLD":
        invalid_state("Only an ON_HOLD cargo document can have its hold released")
    ent["status"] = "VERIFIED"
    touch(ent)
    return ok_object(serialize(ent))


@bp.post("/cargo-documents/<did>/release")
def release_cargo_document(did):
    require_roles(["AgencyOps"])
    ent = _get_or_404(did)
    if ent["status"] != "VERIFIED":
        invalid_state("Only a VERIFIED cargo document can be released")
    call = domain.get("port_calls", ent["port_call_id"])
    if call is None or call["ops_status"] != "ALONGSIDE":
        raise_err("ERR_BL_RELEASE_TOO_EARLY", "Documents may only be released while ALONGSIDE")
    if ent["doc_type"] == "BILL_OF_LADING" and not ent["freight_paid"]:
        raise_err("ERR_FREIGHT_NOT_PAID", "A bill of lading requires freight_paid before release")
    ent["status"] = "RELEASED"
    touch(ent)
    return ok_object(serialize(ent))
