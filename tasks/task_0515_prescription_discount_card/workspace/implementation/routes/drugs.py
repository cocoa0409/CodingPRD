"""Drug catalogue endpoints (PRD §3.1)."""
from flask import Blueprint, request
import db
import response
import common
import errors
import middleware
from services import serializers

bp = Blueprint("drugs", __name__)

DRUG_FORMS = {"TABLET", "CAPSULE", "LIQUID", "INJECTION"}
ALL_AUTHED = ["Anonymous", "Member", "PlatformAdmin", "PharmacyOperator", "CopayCardSponsor"]


@bp.route("/drugs", methods=["POST"])
def create_drug():
    middleware.require_auth(["PlatformAdmin"])
    body = common.get_body()
    name = common.req_str(body, "name")
    ndc = common.req_str(body, "ndc")  # non-empty
    dosage_mg = common.req_number(body, "dosage_mg")
    if dosage_mg <= 0:
        raise errors.invalid_request("dosage_mg must be > 0.")
    form = common.req_enum(body, "form", DRUG_FORMS)
    awp_cents = common.req_int(body, "awp_cents")
    if awp_cents < 1:
        raise errors.invalid_request("awp_cents must be >= 1.")
    is_controlled = common.opt_bool(body, "is_controlled", False)

    rec = {
        "name": name,
        "ndc": ndc,
        "dosage_mg": dosage_mg,
        "form": form,
        "is_controlled": is_controlled,
        "awp_cents": awp_cents,
    }
    db.stamp_create(rec, common_fields=True)
    db.drugs[rec["id"]] = rec
    return response.object_response(serializers.serialize(rec), 201)


@bp.route("/drugs/<did>", methods=["GET"])
def get_drug(did):
    middleware.require_auth(ALL_AUTHED)
    rec = common.must_exist(db.drugs, did, "Drug")
    return response.object_response(serializers.serialize(rec), 200)


@bp.route("/drugs", methods=["GET"])
def list_drugs():
    middleware.require_auth(ALL_AUTHED)
    limit, offset = common.parse_pagination()
    name = request.args.get("name")
    items = list(db.drugs.values())
    if name is not None:
        items = [d for d in items if d["name"] == name]
    window, total = common.paginate(items, limit, offset)
    return response.array_response(serializers.serialize_list(window), limit, offset, total, 200)
