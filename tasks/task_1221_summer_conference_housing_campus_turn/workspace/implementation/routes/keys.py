"""Key credentials: issue, activate, return (late fee), report-lost
(PRD 3.7)."""
from flask import Blueprint, request

from authz import ADMIN, HOUSEKEEPING, FINANCE, require_roles
from calc import KEY_LOST_FEE_CENTS, key_late_fee
from db import store
from errors import ApiError, invalid_request, invalid_state
from respond import success
from serialize import ser_key_credential
from store_ops import (
    get_or_404, json_body, new_common_fields, new_id, paginate, req_str,
    sorted_by_creation, touch,
)
from timeutil import as_date

bp = Blueprint("keys", __name__)

READ_ROLES = [ADMIN, HOUSEKEEPING, FINANCE]


@bp.route("/conference-groups/<gid>/key-credentials", methods=["POST"])
def issue_key(gid):
    require_roles([ADMIN])
    g = get_or_404(store.groups, gid)
    data = json_body()
    participant_id = req_str(data, "participant_id")
    participant = store.participants.get(participant_id)
    if participant is None or participant["group_id"] != gid:
        raise invalid_request("participant_id does not reference a participant of this group")
    credential_code = req_str(data, "credential_code")
    building = store.buildings[g["building_id"]]
    for k in store.key_credentials.values():
        kg = store.groups.get(k["group_id"])
        if kg is not None and kg["building_id"] == building["id"] and k["credential_code"] == credential_code:
            raise invalid_request("credential_code must be unique within the building")
    if building["available_key_count"] < 1:
        raise ApiError("ERR_KEY_INVENTORY_EXHAUSTED", 422,
                       "The building's key pool is exhausted")
    building["available_key_count"] -= 1
    touch(building)
    k = {
        "id": new_id(),
        "_seq": next(store.seq),
        "group_id": gid,
        "participant_id": participant_id,
        "credential_code": credential_code,
        "status": "ISSUED",
        "returned_at": None,
        "late_fee_cents": None,
        "lost_fee_cents": None,
    }
    k.update(new_common_fields())
    store.key_credentials[k["id"]] = k
    return success(ser_key_credential(k), status=201)


@bp.route("/key-credentials", methods=["GET"])
def list_keys():
    require_roles(READ_ROLES)
    group_id = request.args.get("group_id")
    participant_id = request.args.get("participant_id")
    status = request.args.get("status")
    items = [k for k in store.key_credentials.values()
             if (group_id is None or k["group_id"] == group_id)
             and (participant_id is None or k["participant_id"] == participant_id)
             and (status is None or k["status"] == status)]
    items = sorted_by_creation(items)
    page, pagination = paginate(items)
    return success([ser_key_credential(k) for k in page], response_type="array", pagination=pagination)


@bp.route("/key-credentials/<kid>", methods=["GET"])
def get_key(kid):
    require_roles(READ_ROLES)
    return success(ser_key_credential(get_or_404(store.key_credentials, kid)))


@bp.route("/key-credentials/<kid>/activate", methods=["POST"])
def activate_key(kid):
    require_roles([ADMIN])
    k = get_or_404(store.key_credentials, kid)
    if k["status"] != "ISSUED":
        raise invalid_state("Credential must be ISSUED to activate")
    g = store.groups[k["group_id"]]
    if g["status"] not in ("CONFIRMED", "IN_HOUSE"):
        raise invalid_state("Group must be CONFIRMED or IN_HOUSE to activate a credential")
    k["status"] = "ACTIVATED"
    touch(k)
    return success(ser_key_credential(k))


@bp.route("/key-credentials/<kid>/return", methods=["POST"])
def return_key(kid):
    require_roles([ADMIN])
    k = get_or_404(store.key_credentials, kid)
    if k["status"] not in ("ISSUED", "ACTIVATED"):
        raise invalid_state("Credential must be ISSUED or ACTIVATED to return")
    g = store.groups[k["group_id"]]
    k["status"] = "RETURNED"
    k["returned_at"] = store.clock
    k["late_fee_cents"] = key_late_fee(as_date(g["departure_date"]), store.clock)
    building = store.buildings[g["building_id"]]
    building["available_key_count"] += 1
    touch(building)
    touch(k)
    return success(ser_key_credential(k))


@bp.route("/key-credentials/<kid>/report-lost", methods=["POST"])
def report_lost_key(kid):
    require_roles([ADMIN])
    k = get_or_404(store.key_credentials, kid)
    if k["status"] not in ("ISSUED", "ACTIVATED"):
        raise invalid_state("Credential must be ISSUED or ACTIVATED to report lost")
    k["status"] = "LOST"
    k["lost_fee_cents"] = KEY_LOST_FEE_CENTS
    touch(k)
    return success(ser_key_credential(k))
