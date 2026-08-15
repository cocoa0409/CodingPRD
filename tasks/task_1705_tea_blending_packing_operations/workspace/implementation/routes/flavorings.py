"""Flavoring catalog (PRD 3.3)."""
from flask import Blueprint

import store
from auth import ALL_ROLES, authenticate, authorize
from errors import (
    ERR_ALREADY_TERMINAL, ERR_INVALID_REQUEST, raise_err,
)
from services import (
    ALLERGEN_TAGS, flavoring_application_out, flavoring_out,
)
from util import (
    body_json, bump, get_or_404, list_response, new_record, req_bool,
    req_int, req_str, success_object,
)

bp = Blueprint("flavorings", __name__)


def _parse_allergen_tags(body):
    tags = body.get("allergen_tags")
    if not isinstance(tags, list):
        raise_err(ERR_INVALID_REQUEST, "allergen_tags is required and must be an array")
    for t in tags:
        if not isinstance(t, str) or t not in ALLERGEN_TAGS:
            raise_err(
                ERR_INVALID_REQUEST,
                "allergen_tags entries must be drawn from %s"
                % ", ".join(ALLERGEN_TAGS),
            )
    return list(tags)


@bp.route("/tea-ops/flavorings", methods=["POST"])
def create_flavoring():
    _, role = authenticate()
    authorize(role, ["BlendMaster"])
    body = body_json()
    name = req_str(body, "name")
    allergen_tags = _parse_allergen_tags(body)
    natural_certified = req_bool(body, "natural_certified")
    cost_per_kg_cents = req_int(body, "cost_per_kg_cents")
    if cost_per_kg_cents < 0:
        raise_err(ERR_INVALID_REQUEST, "cost_per_kg_cents must be >= 0")

    rec = new_record()
    rec.update({
        "name": name,
        "allergen_tags": allergen_tags,
        "natural_certified": natural_certified,
        "cost_per_kg_cents": cost_per_kg_cents,
        "status": "ACTIVE",
    })
    store.flavorings[rec["id"]] = rec
    return success_object(flavoring_out(rec), 201)


@bp.route("/tea-ops/flavorings/<fid>", methods=["GET"])
def get_flavoring(fid):
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    rec = get_or_404(store.flavorings, fid, "Flavoring")
    return success_object(flavoring_out(rec))


@bp.route("/tea-ops/flavorings/<fid>/retire", methods=["POST"])
def retire_flavoring(fid):
    _, role = authenticate()
    authorize(role, ["BlendMaster"])
    rec = get_or_404(store.flavorings, fid, "Flavoring")
    if rec["status"] == "RETIRED":
        raise_err(ERR_ALREADY_TERMINAL, "Flavoring is already RETIRED")
    rec["status"] = "RETIRED"
    bump(rec)
    # Existing FlavoringApplication rows are unaffected (PRD 3.3).
    return success_object(flavoring_out(rec))


@bp.route("/tea-ops/flavorings/<fid>/flavoring-applications", methods=["GET"])
def list_flavoring_applications(fid):
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    rec = get_or_404(store.flavorings, fid, "Flavoring")
    records = [
        fa for fa in store.flavoring_applications.values()
        if fa["flavoring_id"] == rec["id"]
    ]
    return list_response(records, flavoring_application_out)
