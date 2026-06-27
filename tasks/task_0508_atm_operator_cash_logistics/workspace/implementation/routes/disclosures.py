"""Fee-disclosure routes: draft, list, approve, reject."""
from flask import Blueprint, request

import lookups
import serialize
import validate
import services.disclosure as disclosure_svc
from constants import REGULATORY_CAPS
from db import store
from errors import err
from middleware import authenticate, authorize
from response import ok_array, ok_object

bp = Blueprint("disclosures", __name__)


@bp.route("/atms/<aid>/fee-disclosures", methods=["POST"])
def draft_disclosure(aid):
    _, role = authenticate()
    authorize(role, {"ComplianceOfficer", "PlatformAdmin"})
    atm = lookups.atm(store, aid)
    body = validate.get_body()
    disclosed = validate.require_int(body, "disclosed_surcharge_cents")
    ack = validate.optional_bool(body, "ack_text_present", False)
    # Snapshot jurisdiction from the ATM's location; compute the cap.
    location = store.locations.get(atm["location_id"])
    jurisdiction = location["jurisdiction_code"]
    cap = REGULATORY_CAPS[jurisdiction]
    disclosure = {
        "atm_id": atm["id"],
        "disclosed_surcharge_cents": disclosed,
        "jurisdiction_code": jurisdiction,
        "regulatory_cap_cents": cap,
        "ack_text_present": ack,
        "status": "DRAFT",
    }
    store.stamp_new(disclosure)
    store.fee_disclosures[disclosure["id"]] = disclosure
    return ok_object(store.clock, serialize.fee_disclosure(disclosure), 201)


@bp.route("/atms/<aid>/fee-disclosures", methods=["GET"])
def list_disclosures(aid):
    _, role = authenticate()
    authorize(role, {"PlatformAdmin", "ComplianceOfficer", "SettlementOfficer"})
    atm = lookups.atm(store, aid)
    limit, offset = validate.parse_pagination(request.args)
    status = request.args.get("status")
    items = [d for d in store.sorted_values(store.fee_disclosures) if d["atm_id"] == atm["id"]]
    if status is not None:
        items = [d for d in items if d["status"] == status]
    page, total = validate.paginate([serialize.fee_disclosure(d) for d in items], limit, offset)
    return ok_array(store.clock, page, limit, offset, total)


@bp.route("/fee-disclosures/<did>/approve", methods=["POST"])
def approve_disclosure(did):
    _, role = authenticate()
    authorize(role, {"ComplianceOfficer"})
    disclosure = lookups.fee_disclosure(store, did)
    if disclosure["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "Disclosure is not DRAFT.")
    atm = lookups.atm(store, disclosure["atm_id"])
    disclosure = disclosure_svc.approve(store, disclosure, atm)
    return ok_object(store.clock, serialize.fee_disclosure(disclosure))


@bp.route("/fee-disclosures/<did>/reject", methods=["POST"])
def reject_disclosure(did):
    _, role = authenticate()
    authorize(role, {"ComplianceOfficer"})
    disclosure = lookups.fee_disclosure(store, did)
    if disclosure["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "Disclosure is not DRAFT.")
    disclosure["status"] = "REJECTED"
    store.touch(disclosure)
    return ok_object(store.clock, serialize.fee_disclosure(disclosure))
