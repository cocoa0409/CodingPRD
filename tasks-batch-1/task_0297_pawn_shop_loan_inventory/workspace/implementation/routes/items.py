"""Customer & PawnItem routes (PRD §3.2)."""
from flask import Blueprint, request

from db import store
from errors import err
from middleware import require_auth
from models import base_record, touch
from helpers import (
    get_body,
    as_str,
    as_int,
    parse_pagination,
    paginate,
    sort_by_creation,
    serialize,
)
from response import success_object, success_array

bp = Blueprint("items", __name__)


# ---------------------------------------------------------------------------
# Customers (PRD §3.2)
# ---------------------------------------------------------------------------
@bp.route("/pawn/customers", methods=["POST"])
def create_customer():
    require_auth(["LoanOfficer", "ShopManager"])
    body = get_body()

    full_name = as_str(body, "full_name")
    gov_id_number = as_str(body, "gov_id_number")

    # gov_id_number uniqueness (PRD §3.2 ERR_DUPLICATE_GOV_ID).
    for c in store.customers.values():
        if c["gov_id_number"] == gov_id_number:
            raise err("ERR_DUPLICATE_GOV_ID", "Government ID already registered.")

    rec = base_record({
        "full_name": full_name,
        "gov_id_number": gov_id_number,
        "is_flagged": False,
    })
    store.customers[rec["id"]] = rec
    return success_object(serialize(rec), 201)


@bp.route("/pawn/customers/<customer_id>", methods=["GET"])
def get_customer(customer_id):
    user_id, role = require_auth(["LoanOfficer", "ShopManager", "LawEnforcement", "Customer"])
    cust = store.customers.get(customer_id)
    if cust is None:
        raise err("ERR_NOT_FOUND", "Customer not found.")
    # A Customer may read only its own record (PRD §2.1).
    if role == "Customer" and user_id != customer_id:
        raise err("ERR_FORBIDDEN_ROLE", "A customer may only read its own record.")
    return success_object(serialize(cust))


# ---------------------------------------------------------------------------
# Pawn items (PRD §3.2)
# ---------------------------------------------------------------------------
@bp.route("/pawn/items", methods=["POST"])
def create_item():
    require_auth(["LoanOfficer", "ShopManager"])
    body = get_body()

    shop_id = as_str(body, "shop_id")
    customer_id = as_str(body, "customer_id")
    description = as_str(body, "description")
    serial_number = as_str(body, "serial_number", required=False)

    # FK existence (priority 3): body FKs checked left-to-right as listed.
    shop = store.shops.get(shop_id)
    if shop is None:
        raise err("ERR_NOT_FOUND", "Shop not found.")
    if customer_id not in store.customers:
        raise err("ERR_NOT_FOUND", "Customer not found.")

    # police_report_status seeded per shop.police_reporting_enabled (PRD §3.2).
    if shop["police_reporting_enabled"]:
        prs = "PENDING_REPORT"
    else:
        prs = "NOT_REQUIRED"

    rec = base_record({
        "shop_id": shop_id,
        "customer_id": customer_id,
        "description": description,
        "serial_number": serial_number,
        "appraised_value_cents": None,
        "appraised_by_user_id": None,
        "status": "INTAKE",
        "police_report_status": prs,
    })
    store.pawn_items[rec["id"]] = rec
    return success_object(serialize(rec), 201)


@bp.route("/pawn/items/<item_id>", methods=["GET"])
def get_item(item_id):
    require_auth(["LoanOfficer", "ShopManager", "Appraiser", "LawEnforcement"])
    item = store.pawn_items.get(item_id)
    if item is None:
        raise err("ERR_NOT_FOUND", "Pawn item not found.")
    return success_object(serialize(item))


@bp.route("/pawn/items", methods=["GET"])
def list_items():
    require_auth(["LoanOfficer", "ShopManager", "Appraiser", "LawEnforcement"])
    limit, offset = parse_pagination()
    shop_id = request.args.get("shop_id")
    customer_id = request.args.get("customer_id")
    items = list(store.pawn_items.values())
    if shop_id is not None:
        items = [i for i in items if i["shop_id"] == shop_id]
    if customer_id is not None:
        items = [i for i in items if i["customer_id"] == customer_id]
    items = sort_by_creation(items)
    window, total = paginate(items, limit, offset)
    return success_array([serialize(i) for i in window], limit, offset, total)


@bp.route("/pawn/items/<item_id>/appraise", methods=["POST"])
def appraise_item(item_id):
    user_id, _ = require_auth(["Appraiser"])
    item = store.pawn_items.get(item_id)
    if item is None:
        raise err("ERR_NOT_FOUND", "Pawn item not found.")

    body = get_body()
    appraised_value_cents = as_int(body, "appraised_value_cents")

    # State precondition (priority 5): must be INTAKE.
    if item["status"] != "INTAKE":
        raise err("ERR_INVALID_STATE", "Item is not in INTAKE.")

    # appraised_value must be > 0 (PRD §3.2). Business well-formedness.
    if appraised_value_cents <= 0:
        raise err("ERR_INVALID_REQUEST", "appraised_value_cents must be > 0.")

    item["appraised_value_cents"] = appraised_value_cents
    item["appraised_by_user_id"] = user_id
    item["status"] = "APPRAISED"
    touch(item)
    return success_object(serialize(item))


@bp.route("/pawn/items/<item_id>/report-police", methods=["POST"])
def report_police(item_id):
    require_auth(["ShopManager", "LoanOfficer"])
    item = store.pawn_items.get(item_id)
    if item is None:
        raise err("ERR_NOT_FOUND", "Pawn item not found.")

    # PENDING_REPORT -> REPORTED (PRD §3.2). Other states are invalid.
    if item["police_report_status"] != "PENDING_REPORT":
        raise err("ERR_INVALID_STATE", "Item is not PENDING_REPORT.")

    item["police_report_status"] = "REPORTED"
    touch(item)
    return success_object(serialize(item))
