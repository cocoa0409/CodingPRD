"""ContractPharmacyArrangement: create (with half-open window overlap guard),
fetch, and the suspend/reactivate/terminate state machine."""
import re

from flask import Blueprint

import lookup
from db import db, base_record, touch
from errors import err
from middleware import get_identity, require_role, get_json_body, serialize
from response import success

bp = Blueprint("contract_pharmacies", __name__)

DATE_RE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")


@bp.route("/covered-entities/<ce_id>/contract-pharmacies", methods=["POST"])
def create_contract_pharmacy(ce_id):
    _, role = get_identity()
    require_role(role, {"ComplianceOfficer"})
    ce = lookup.covered_entity(ce_id)
    body = get_json_body()

    from validation import require_string

    pharmacy_name = require_string(body, "pharmacy_name")
    ship_to_bill_to_npi = require_string(body, "ship_to_bill_to_npi")
    effective_start = require_string(body, "effective_start")
    effective_end = require_string(body, "effective_end")

    if not DATE_RE.match(effective_start) or not DATE_RE.match(effective_end):
        raise err("ERR_INVALID_REQUEST", "dates must be YYYY-MM-DD")
    if effective_end <= effective_start:
        raise err("ERR_INVALID_REQUEST", "effective_end must be after effective_start")

    # Window overlap guard: same CE, same NPI, status ACTIVE/SUSPENDED, half-open
    # interval intersection. Adjacency (existing.end == new.start) does not collide.
    for cp in db.contract_pharmacies.all():
        if (
            cp["covered_entity_id"] == ce["id"]
            and cp["ship_to_bill_to_npi"] == ship_to_bill_to_npi
            and cp["arrangement_status"] in ("ACTIVE", "SUSPENDED")
            and _overlaps(
                cp["effective_start"], cp["effective_end"], effective_start, effective_end
            )
        ):
            raise err("ERR_CP_WINDOW_OVERLAP", "Overlapping contract-pharmacy window")

    rec = base_record(full_meta=True)
    rec.update(
        {
            "covered_entity_id": ce["id"],
            "pharmacy_name": pharmacy_name,
            "ship_to_bill_to_npi": ship_to_bill_to_npi,
            "effective_start": effective_start,
            "effective_end": effective_end,
            "arrangement_status": "ACTIVE",
        }
    )
    db.contract_pharmacies.put(rec)
    return success(serialize(rec), status=201)


def _overlaps(a_start, a_end, b_start, b_end):
    """Half-open [start, end) intersection: a_start < b_end AND b_start < a_end."""
    return a_start < b_end and b_start < a_end


@bp.route("/contract-pharmacies/<cp_id>", methods=["GET"])
def get_contract_pharmacy(cp_id):
    get_identity()
    cp = lookup.contract_pharmacy(cp_id)
    return success(serialize(cp))


def _transition(cp_id, expect, on_ok):
    _, role = get_identity()
    require_role(role, {"ComplianceOfficer"})
    cp = lookup.contract_pharmacy(cp_id)
    if cp["arrangement_status"] not in expect:
        raise err("ERR_INVALID_STATE", "Transition not allowed from current state")
    on_ok(cp)
    touch(cp)
    return success(serialize(cp))


@bp.route("/contract-pharmacies/<cp_id>/suspend", methods=["POST"])
def suspend_cp(cp_id):
    return _transition(cp_id, {"ACTIVE"}, lambda cp: cp.__setitem__("arrangement_status", "SUSPENDED"))


@bp.route("/contract-pharmacies/<cp_id>/reactivate", methods=["POST"])
def reactivate_cp(cp_id):
    def on_ok(cp):
        ce = db.covered_entities.get(cp["covered_entity_id"])
        if ce is None or ce["registration_status"] != "ACTIVE":
            raise err("ERR_INVALID_STATE", "Owning CE must be ACTIVE to reactivate")
        cp["arrangement_status"] = "ACTIVE"

    return _transition(cp_id, {"SUSPENDED"}, on_ok)


@bp.route("/contract-pharmacies/<cp_id>/terminate", methods=["POST"])
def terminate_cp(cp_id):
    return _transition(cp_id, {"ACTIVE"}, lambda cp: cp.__setitem__("arrangement_status", "TERMINATED"))
