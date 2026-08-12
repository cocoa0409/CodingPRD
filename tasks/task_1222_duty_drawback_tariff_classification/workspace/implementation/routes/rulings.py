"""Binding ruling endpoints (PRD §3.2)."""
from flask import Blueprint, request

from calc import mint_entity, touch
from db import STORE
from errors import (
    ERR_ALREADY_TERMINAL,
    ERR_CLASSIFICATION_NOT_CERTIFIED,
    ERR_INVALID_REQUEST,
    ERR_NOT_FOUND,
    raise_err,
)
from middleware import (
    authenticate,
    get_body,
    req_enum,
    req_int,
    req_str,
    require_client_scope,
    require_role,
)
from response import paginate, success_object
from serializers import serialize, sorted_by_creation

bp = Blueprint("rulings", __name__)

ALL_ROLES = {"FirmAdmin", "Analyst", "LicensedBroker", "ComplianceManager", "ClientContact"}
TERMINAL = {"ISSUED", "DENIED", "WITHDRAWN"}


def get_ruling_or_404(ruling_id):
    ruling = STORE["binding_rulings"].get(ruling_id)
    if ruling is None:
        raise_err(ERR_NOT_FOUND, f"Binding ruling {ruling_id} not found")
    return ruling


@bp.route("/customs/binding-rulings", methods=["POST"])
def create_ruling():
    _, role = authenticate()
    require_role(role, {"LicensedBroker"})
    body = get_body()
    classification_id = req_str(body, "classification_id")
    requested_hts_code = req_str(body, "requested_hts_code")
    cls = STORE["classifications"].get(classification_id)
    if cls is None:
        raise_err(ERR_NOT_FOUND, f"Classification {classification_id} not found")
    if cls["status"] != "CERTIFIED":
        raise_err(
            ERR_CLASSIFICATION_NOT_CERTIFIED,
            "Binding rulings may only reference a CERTIFIED classification",
        )
    ruling = mint_entity()
    ruling.update({
        "classification_id": classification_id,
        "requested_hts_code": requested_hts_code,
        "status": "SUBMITTED",
        "issued_hts_code": None,
        "issued_duty_rate_bps": None,
    })
    STORE["binding_rulings"][ruling["id"]] = ruling
    return success_object(serialize(ruling), 201)


@bp.route("/customs/binding-rulings/<ruling_id>", methods=["GET"])
def get_ruling(ruling_id):
    user_id, role = authenticate()
    require_role(role, ALL_ROLES)
    ruling = get_ruling_or_404(ruling_id)
    cls = STORE["classifications"].get(ruling["classification_id"])
    require_client_scope(user_id, role, cls["client_id"] if cls else None)
    return success_object(serialize(ruling))


@bp.route("/customs/binding-rulings", methods=["GET"])
def list_rulings():
    user_id, role = authenticate()
    require_role(role, ALL_ROLES)
    items = sorted_by_creation(STORE["binding_rulings"].values())
    if role == "ClientContact":
        items = [
            r for r in items
            if STORE["classifications"].get(r["classification_id"], {}).get("client_id") == user_id
        ]
    classification_id = request.args.get("classification_id")
    if classification_id is not None:
        items = [r for r in items if r["classification_id"] == classification_id]
    status = request.args.get("status")
    if status is not None:
        items = [r for r in items if r["status"] == status]
    return paginate([serialize(r) for r in items])


@bp.route("/customs/binding-rulings/<ruling_id>/outcome", methods=["POST"])
def ruling_outcome(ruling_id):
    _, role = authenticate()
    require_role(role, {"LicensedBroker"})
    ruling = get_ruling_or_404(ruling_id)
    body = get_body()
    outcome = req_enum(body, "outcome", {"ISSUED", "DENIED", "WITHDRAWN"})
    issued_hts_code = None
    issued_duty_rate_bps = None
    if outcome == "ISSUED":
        if body.get("issued_hts_code") is None or body.get("issued_duty_rate_bps") is None:
            raise_err(
                ERR_INVALID_REQUEST,
                "outcome=ISSUED requires issued_hts_code and issued_duty_rate_bps",
            )
        issued_hts_code = req_str(body, "issued_hts_code")
        issued_duty_rate_bps = req_int(body, "issued_duty_rate_bps", minimum=0)
    if ruling["status"] in TERMINAL:
        raise_err(ERR_ALREADY_TERMINAL, f"Ruling is {ruling['status']} (terminal)")

    ruling["status"] = outcome
    if outcome == "ISSUED":
        ruling["issued_hts_code"] = issued_hts_code
        ruling["issued_duty_rate_bps"] = issued_duty_rate_bps
        # Re-rate the linked classification in place.
        cls = STORE["classifications"].get(ruling["classification_id"])
        if cls is not None:
            cls["hts_code"] = issued_hts_code
            cls["duty_rate_bps"] = issued_duty_rate_bps
            touch(cls)
    touch(ruling)
    return success_object(serialize(ruling))
