"""ProducerDisclosure endpoints: list, get, deliver, acknowledge."""
from flask import Blueprint

from db import DB, now_iso
from errors import ApiError
from middleware import auth, ADMIN_ACCT, ALL_ROLES, PRODUCER_ONLY
from response import ok
from services import ser_disclosure, touch
from util import apply_filters, respond_list

bp = Blueprint("disclosures", __name__)


@bp.get("/agency/producer-disclosures")
def list_disclosures():
    auth(ALL_ROLES)
    items = apply_filters(
        DB["disclosures"].values(),
        {"policy_id": "policy_id", "producer_id": "producer_id", "status": "status"},
    )
    return respond_list(items, ser_disclosure)


@bp.get("/agency/producer-disclosures/<disclosureId>")
def get_disclosure(disclosureId):
    auth(ALL_ROLES)
    d = DB["disclosures"].get(disclosureId)
    if d is None:
        raise ApiError("ERR_NOT_FOUND", 404, "ProducerDisclosure not found")
    return ok(ser_disclosure(d))


@bp.post("/agency/producer-disclosures/<disclosureId>/deliver")
def deliver_disclosure(disclosureId):
    auth(ADMIN_ACCT)
    d = DB["disclosures"].get(disclosureId)
    if d is None:
        raise ApiError("ERR_NOT_FOUND", 404, "ProducerDisclosure not found")
    if d["status"] != "GENERATED":
        raise ApiError("ERR_INVALID_STATE", 409, "Disclosure is not GENERATED")
    d["status"] = "DELIVERED"
    d["disclosed_at"] = now_iso()
    touch(d)
    return ok(ser_disclosure(d))


@bp.post("/agency/producer-disclosures/<disclosureId>/acknowledge")
def acknowledge_disclosure(disclosureId):
    user_id, _role = auth(PRODUCER_ONLY)
    d = DB["disclosures"].get(disclosureId)
    if d is None:
        raise ApiError("ERR_NOT_FOUND", 404, "ProducerDisclosure not found")
    # Priority 4: state admissibility.
    if d["status"] != "DELIVERED":
        raise ApiError("ERR_INVALID_STATE", 409, "Disclosure is not DELIVERED")
    # Priority 7: ownership — X-User-ID must equal the disclosure's producer_id.
    if user_id != d["producer_id"]:
        raise ApiError(
            "ERR_NOT_RESOURCE_OWNER", 403, "Disclosure belongs to another producer"
        )
    d["status"] = "ACKNOWLEDGED"
    d["acknowledged_at"] = now_iso()
    touch(d)
    return ok(ser_disclosure(d))
