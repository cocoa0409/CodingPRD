"""ConductCase endpoints."""
from flask import Blueprint

from db import store, new_id, next_seq
from errors import (
    ApiError,
    ERR_INVALID_REQUEST,
    ERR_CASE_NOT_FOUND,
    ERR_SEASON_NOT_FOUND,
    ERR_ORDER_NOT_FOUND,
    ERR_PERMIT_NOT_FOUND,
    ERR_CASE_ALREADY_RESOLVED,
    ERR_CASE_LINKAGE_INVALID,
    conflict,
)
from middleware import (
    require_roles,
    get_body,
    load,
    parse_pagination,
    apply_filters,
    sorted_by_creation,
)
from response import obj_response, list_response
from services import ban_guest_cascade, revoke_permit_cascade
from util import req, opt, present, check_unknown, new_record, mutate, public_view

bp = Blueprint("conduct_cases", __name__)

CATEGORIES = {"COSTUME_POLICY", "WEAPON_UNTIED", "BEHAVIOR", "VENDOR_CONDUCT"}
OUTCOMES = {"UPHELD", "DISMISSED"}
SANCTIONS = {"NONE", "BAN_GUEST", "REVOKE_PERMIT"}
CREATE_FIELDS = {
    "season_id",
    "category",
    "subject_description",
    "linked_order_id",
    "linked_permit_id",
}
RESOLVE_FIELDS = {"outcome", "sanction"}


def load_case(cid):
    return load(store.cases, cid, ERR_CASE_NOT_FOUND, "conduct case")


@bp.route("/conduct-cases", methods=["POST"])
def create_case():
    require_roles("GateAgent")
    body = get_body()
    # Layer 3 body FK existence, canonical order: season_id, linked_order_id, linked_permit_id.
    if isinstance(body.get("season_id"), str):
        load(store.seasons, body["season_id"], ERR_SEASON_NOT_FOUND, "season")
    if isinstance(body.get("linked_order_id"), str):
        load(store.orders, body["linked_order_id"], ERR_ORDER_NOT_FOUND, "ticket order")
    if isinstance(body.get("linked_permit_id"), str):
        load(store.permits, body["linked_permit_id"], ERR_PERMIT_NOT_FOUND, "food permit")
    check_unknown(body, CREATE_FIELDS)
    season_id = req(body, "season_id", "str")
    category = req(body, "category", "enum", enum=CATEGORIES)
    subject = req(body, "subject_description", "str")
    linked_order_id = opt(body, "linked_order_id", "str")
    linked_permit_id = opt(body, "linked_permit_id", "str")
    if category == "VENDOR_CONDUCT" and linked_permit_id is None:
        raise ApiError(
            ERR_INVALID_REQUEST, 400, "VENDOR_CONDUCT cases require linked_permit_id"
        )
    case = new_record()
    case.update(
        {
            "id": new_id(),
            "_seq": next_seq(),
            "season_id": season_id,
            "category": category,
            "subject_description": subject,
            "linked_order_id": linked_order_id,
            "linked_permit_id": linked_permit_id,
            "status": "REPORTED",
            "sanction": "NONE",
        }
    )
    store.cases[case["id"]] = case
    return obj_response(public_view(case), 201)


@bp.route("/conduct-cases", methods=["GET"])
def list_cases():
    require_roles()
    limit, offset = parse_pagination()
    items = apply_filters(
        sorted_by_creation(store.cases),
        [
            ("season_id", "season_id"),
            ("status", "status"),
            ("linked_order_id", "linked_order_id"),
            ("linked_permit_id", "linked_permit_id"),
        ],
    )
    total = len(items)
    page = items[offset : offset + limit]
    return list_response([public_view(c) for c in page], limit, offset, total)


@bp.route("/conduct-cases/<cid>", methods=["GET"])
def get_case(cid):
    require_roles()
    return obj_response(public_view(load_case(cid)))


@bp.route("/conduct-cases/<cid>/resolve", methods=["POST"])
def resolve_case(cid):
    require_roles("FaireOperator")
    case = load_case(cid)
    body = get_body()
    check_unknown(body, RESOLVE_FIELDS)
    outcome = req(body, "outcome", "enum", enum=OUTCOMES)
    sanction = opt(body, "sanction", "enum", enum=SANCTIONS)
    if outcome == "UPHELD" and sanction is None:
        raise ApiError(ERR_INVALID_REQUEST, 400, "an UPHELD resolution requires a sanction")
    if case["status"] != "REPORTED":
        raise conflict(ERR_CASE_ALREADY_RESOLVED, "resolve requires REPORTED")
    if outcome == "DISMISSED":
        mutate(case, status="DISMISSED")
        return obj_response(public_view(case))

    # UPHELD: enforce sanction linkage before applying effects.
    if sanction == "BAN_GUEST" and case["linked_order_id"] is None:
        raise conflict(ERR_CASE_LINKAGE_INVALID, "BAN_GUEST requires linked_order_id")
    if sanction == "REVOKE_PERMIT" and case["linked_permit_id"] is None:
        raise conflict(ERR_CASE_LINKAGE_INVALID, "REVOKE_PERMIT requires linked_permit_id")
    mutate(case, status="UPHELD", sanction=sanction)
    season = store.seasons.get(case["season_id"])
    if sanction == "BAN_GUEST":
        order = store.orders[case["linked_order_id"]]
        ban_guest_cascade(order, season)
    elif sanction == "REVOKE_PERMIT":
        permit = store.permits[case["linked_permit_id"]]
        if permit["status"] == "ISSUED":
            revoke_permit_cascade(permit)
    return obj_response(public_view(case))
