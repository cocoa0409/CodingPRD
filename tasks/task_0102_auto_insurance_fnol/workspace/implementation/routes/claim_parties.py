"""ClaimParty routes (PRD §3.8)."""
from flask import Blueprint

import db
import serializers as S
from auth import authenticate, authorize
from errors import err
from helpers import (get_json_body, require_resource, require_fields,
                     require_str, require_enum, require_fault_pct)
from response import success

bp = Blueprint("claim_parties", __name__)

PARTY_ROLES = {"INSURED", "THIRD_PARTY"}


@bp.route("/claim-parties", methods=["POST"])
def create_claim_party():
    principal = authenticate()
    authorize(principal, {"ClaimsAdjuster", "ClaimsSupervisor"})
    body = get_json_body()
    require_fields(body, ["claim_id", "party_role", "display_name"])
    claim = require_resource(db.claims, body["claim_id"], "claim")
    party_role = require_enum(body, "party_role", PARTY_ROLES)
    display_name = require_str(body, "display_name")
    fault_pct = require_fault_pct(body, "fault_pct", 0)

    at_fault_carrier_name = None
    if "at_fault_carrier_name" in body and body["at_fault_carrier_name"] is not None:
        v = body["at_fault_carrier_name"]
        if not isinstance(v, str):
            raise err("ERR_INVALID_REQUEST", "at_fault_carrier_name must be a string")
        at_fault_carrier_name = v

    # At most one INSURED party per claim.
    if party_role == "INSURED":
        existing = [p for p in db.claim_parties.values()
                    if p["claim_id"] == claim["id"] and p["party_role"] == "INSURED"]
        if existing:
            raise err("ERR_DUPLICATE_INSURED_PARTY",
                      "an INSURED party already exists for this claim")

    rec = {
        "claim_id": claim["id"],
        "party_role": party_role,
        "display_name": display_name,
        "fault_pct": fault_pct,
        "at_fault_carrier_name": at_fault_carrier_name,
    }
    db.insert(db.claim_parties, rec)
    return success(S.claim_party(rec), status=201)
