"""Assessment + repair line item endpoints (PRD §3.4)."""

from flask import Blueprint, request

from constants import CONDITION_SCALE, REPAIR_CATEGORIES
from db import store
from errors import err
from helpers import (
    get_assessment_or_404,
    pagination_params,
    paginate,
)
from middleware import authenticate, require_role
from models import serialize, stamp_create, touch
from money import round2
from response import array_response, object_response
from validators import as_enum, as_number, as_string_array, get_body, require

bp = Blueprint("assessments", __name__)

# POOR is worst. Map condition -> rank where higher == worse.
_RANK = {name: i for i, name in enumerate(CONDITION_SCALE)}  # EXCELLENT=0 ... POOR=3


@bp.route("/assessments/<assessment_id>", methods=["GET"])
def get_assessment(assessment_id):
    _uid, role = authenticate()
    require_role(role, {"OperationsAdmin", "PricingAnalyst", "Seller"})
    rec = get_assessment_or_404(assessment_id)
    return object_response(serialize(rec), 200)


@bp.route("/assessments/<assessment_id>/repair-line-items", methods=["POST"])
def create_repair_line_item(assessment_id):
    _uid, role = authenticate()
    require_role(role, {"OperationsAdmin"})
    assessment = get_assessment_or_404(assessment_id)

    # Only while DRAFT (locked once FINALIZED).
    if assessment["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "Assessment is not DRAFT")

    body = get_body(request)
    category = as_enum(require(body, "category"), "category", REPAIR_CATEGORIES)
    estimate_amount = as_number(require(body, "estimate_amount"), "estimate_amount", minimum=0)

    rec = {
        "assessment_id": assessment_id,
        "category": category,
        "estimate_amount": estimate_amount,
        "rounded_amount": round2(estimate_amount),
    }
    stamp_create(rec)
    store.repair_line_items[rec["id"]] = rec
    return object_response(serialize(rec), 201)


@bp.route("/assessments/<assessment_id>/repair-line-items", methods=["GET"])
def list_assessment_repair_line_items(assessment_id):
    _uid, role = authenticate()
    require_role(role, {"OperationsAdmin", "PricingAnalyst", "Seller"})
    get_assessment_or_404(assessment_id)
    records = [r for r in store.repair_line_items.values() if r["assessment_id"] == assessment_id]
    limit, offset = pagination_params()
    page, total = paginate(records, limit, offset)
    return array_response([serialize(r) for r in page], limit, offset, total)


@bp.route("/assessments/<assessment_id>/finalize", methods=["POST"])
def finalize_assessment(assessment_id):
    _uid, role = authenticate()
    require_role(role, {"OperationsAdmin"})
    assessment = get_assessment_or_404(assessment_id)

    # State: must be DRAFT (priority 5)
    if assessment["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "Assessment is not DRAFT")

    body = get_body(request)
    roof = as_enum(require(body, "roof_condition"), "roof_condition", CONDITION_SCALE)
    hvac = as_enum(require(body, "hvac_condition"), "hvac_condition", CONDITION_SCALE)
    foundation = as_enum(require(body, "foundation_condition"), "foundation_condition", CONDITION_SCALE)

    flags = assessment["questionnaire_flags"]
    if body.get("questionnaire_flags") is not None:
        flags = as_string_array(body["questionnaire_flags"], "questionnaire_flags")

    # Worst of the three components (highest rank).
    worst = max((roof, hvac, foundation), key=lambda c: _RANK[c])

    assessment["roof_condition"] = roof
    assessment["hvac_condition"] = hvac
    assessment["foundation_condition"] = foundation
    assessment["questionnaire_flags"] = flags
    assessment["condition_score"] = worst
    assessment["status"] = "FINALIZED"
    touch(assessment)

    # Write back onto the property's condition_score.
    offer = store.offers[assessment["offer_id"]]
    prop = store.properties[offer["property_id"]]
    prop["condition_score"] = worst
    touch(prop)

    return object_response(serialize(assessment), 200)
