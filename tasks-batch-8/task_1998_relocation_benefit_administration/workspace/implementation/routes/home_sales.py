from flask import Blueprint, request

from db import DB
from errors import (
    err_not_found, err_invalid_request, err_invalid_state, err_already_terminal,
    err_case_not_open, err_duplicate_resource, err_home_sale_not_eligible,
)
from middleware import get_actor, require_role
from response import success_object, success_list
from serializers import serialize_home_sale
from util import require_fields, require_string, require_positive_int, get_pagination
from services.caps import approved_increases
from services.ledger import touch_entity, pay_direct

bp = Blueprint("home_sales", __name__)

ALL_ROLES = ["MobilityCoordinator", "FinanceSpecialist", "ProgramManager", "Employee", "Vendor"]

TERMINAL = {"SETTLED"}


def _get_or_404(id):
    h = DB.home_sales.get(id)
    if h is None:
        raise err_not_found("HomeSaleTransaction not found")
    return h


@bp.route("/home-sales", methods=["POST"])
def create_home_sale():
    actor = get_actor()
    require_role(actor, ["MobilityCoordinator"])
    payload = request.get_json(silent=True) or {}
    require_fields(payload, ["case_id", "appraised_value_cents", "original_purchase_price_cents", "list_price_cents"])
    case_id = require_string(payload, "case_id")
    appraised = require_positive_int(payload, "appraised_value_cents")
    purchase = require_positive_int(payload, "original_purchase_price_cents")
    list_price = require_positive_int(payload, "list_price_cents")
    with DB.lock:
        case = DB.cases.get(case_id)
        if case is None:
            raise err_not_found("Case not found")
        if case["status"] != "IN_PROGRESS":
            raise err_case_not_open("Case is not IN_PROGRESS")
        policy = DB.policies.get(case["policy_id"])
        if not policy.get("home_sale_eligible"):
            raise err_home_sale_not_eligible("Policy is not home-sale eligible")
        for h in DB.home_sales.values():
            if h["case_id"] == case_id:
                raise err_duplicate_resource("Home-sale transaction already exists for this case")
        now = DB.now()
        h = {
            "id": DB.new_id(),
            "case_id": case_id,
            "appraised_value_cents": appraised,
            "original_purchase_price_cents": purchase,
            "list_price_cents": list_price,
            "sale_price_cents": None,
            "loss_basis_used": None,
            "gross_loss_cents": None,
            "capped_benefit_cents": None,
            "status": "LISTED",
            "created_at": now,
            "updated_at": now,
            "version": 0,
            "_seq": DB.next_seq(),
        }
        DB.home_sales[h["id"]] = h
        return success_object(serialize_home_sale(h), status=201)


@bp.route("/home-sales/<id>", methods=["GET"])
def get_home_sale(id):
    actor = get_actor()
    require_role(actor, ALL_ROLES)
    with DB.lock:
        h = _get_or_404(id)
        return success_object(serialize_home_sale(h))


@bp.route("/relocation-cases/<case_id>/home-sales", methods=["GET"])
def list_case_home_sales(case_id):
    actor = get_actor()
    require_role(actor, ALL_ROLES)
    limit, offset = get_pagination(request.args)
    with DB.lock:
        case = DB.cases.get(case_id)
        if case is None:
            raise err_not_found("Case not found")
        items = [h for h in DB.home_sales.values() if h["case_id"] == case_id]
        items.sort(key=lambda h: (h["created_at"], h.get("_seq", 0)))
        total_count = len(items)
        page = items[offset:offset + limit]
        return success_list([serialize_home_sale(h) for h in page], limit, offset, total_count)


@bp.route("/home-sales/<id>/record-sale", methods=["POST"])
def record_sale(id):
    actor = get_actor()
    require_role(actor, ["MobilityCoordinator"])
    payload = request.get_json(silent=True) or {}
    require_fields(payload, ["sale_price_cents"])
    sale_price = require_positive_int(payload, "sale_price_cents")
    with DB.lock:
        h = _get_or_404(id)
        if h["status"] in TERMINAL:
            raise err_already_terminal("Home-sale transaction is SETTLED")
        if h["status"] != "LISTED":
            raise err_invalid_state("Home-sale transaction is not LISTED")
        case = DB.cases.get(h["case_id"])
        if case is None or case["status"] != "IN_PROGRESS":
            raise err_case_not_open("Case is not IN_PROGRESS")
        policy = DB.policies.get(case["policy_id"])
        h["sale_price_cents"] = sale_price
        h["loss_basis_used"] = policy["loss_basis"]
        if policy["loss_basis"] == "APPRAISED":
            gross_loss = max(0, h["appraised_value_cents"] - sale_price)
        else:
            gross_loss = max(0, h["original_purchase_price_cents"] - sale_price)
        h["gross_loss_cents"] = gross_loss
        effective_cap = policy["loss_on_sale_cap_cents"] + approved_increases(case["id"], "LOSS_ON_SALE")
        h["capped_benefit_cents"] = min(gross_loss, effective_cap)
        h["status"] = "SOLD"
        touch_entity(h)
        return success_object(serialize_home_sale(h))


@bp.route("/home-sales/<id>/settle", methods=["POST"])
def settle_home_sale(id):
    actor = get_actor()
    require_role(actor, ["FinanceSpecialist"])
    with DB.lock:
        h = _get_or_404(id)
        if h["status"] in TERMINAL:
            raise err_already_terminal("Home-sale transaction is SETTLED")
        if h["status"] != "SOLD":
            raise err_invalid_state("Home-sale transaction is not SOLD")
        case = DB.cases.get(h["case_id"])
        if case is None:
            raise err_not_found("Case not found")
        h["status"] = "SETTLED"
        touch_entity(h)
        pay_direct(case, h["capped_benefit_cents"])
        return success_object(serialize_home_sale(h))
