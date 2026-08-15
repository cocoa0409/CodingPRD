"""Utility stock and material issuance endpoints (PRD 3.4).

StockItem.on_hand is derived from the ledger on read (initial_on_hand +
receipts - issued + returned); the two conserved quantities therefore stay
exact by construction.
"""
from flask import Blueprint, request

from db import db
from errors import (
    raise_error, ERR_INVALID_REQUEST, ERR_INVALID_STATE,
    ERR_CROSS_CONTRACT_REFERENCE, ERR_INSUFFICIENT_STOCK,
    ERR_RETURN_EXCEEDS_ISSUED, ERR_MATERIAL_VARIANCE_UNRESOLVED,
)
from middleware import authorized
from response import success_object
from routes.helpers import serialize, list_response, get_one
from routes.work_packages import require_contract_active
from services.core import (
    new_record, touch, contract_of_work_package, stock_on_hand,
)
from util import dec, num
from validate import (
    get_body, req_str, opt_num, req_num, require_path_resource, require_body_ref,
)

bp = Blueprint("stock", __name__)


@bp.post("/contracts/<contract_id>/stock-items")
def create_stock_item(contract_id):
    authorized(["UTILITY_DISPATCHER"])
    body = get_body()
    material_code = req_str(body, "material_code")
    description = req_str(body, "description")
    uom = req_str(body, "uom")
    initial_on_hand = opt_num(body, "initial_on_hand", 0, non_negative=True)
    contract = require_path_resource("contracts", contract_id)
    for s in db["stock_items"].values():
        if s["contract_id"] == contract["id"] and s["material_code"] == material_code:
            raise_error(ERR_INVALID_REQUEST,
                        f"material_code already exists in this contract: {material_code}")
    rec = new_record("stock_items", {
        "contract_id": contract["id"],
        "material_code": material_code,
        "description": description,
        "uom": uom,
        "initial_on_hand": initial_on_hand,
        "_receipts_total": 0,
    })
    return success_object(serialize("stock_items", rec), status=201)


@bp.post("/stock-items/<stock_item_id>/receipts")
def create_receipt(stock_item_id):
    authorized(["UTILITY_DISPATCHER"])
    body = get_body()
    quantity = req_num(body, "quantity", positive=True)
    item = require_path_resource("stock_items", stock_item_id)
    item["_receipts_total"] = dec(item.get("_receipts_total", 0)) + dec(quantity)
    touch(item)  # recording a receipt increments the stock item's version
    return success_object(serialize("stock_items", item))


@bp.get("/stock-items")
def list_stock_items():
    filters = {"contract_id": request.args.get("contract_id")}
    return list_response("stock_items", filters)


@bp.get("/stock-items/<stock_item_id>")
def get_stock_item(stock_item_id):
    return get_one("stock_items", stock_item_id)


# ---------------------------------------------------------------------------
# Material issues (PRD 3.4)
# ---------------------------------------------------------------------------

@bp.post("/work-packages/<work_package_id>/material-issues")
def create_material_issue(work_package_id):
    authorized(["FOREMAN"])
    body = get_body()
    stock_item_id = req_str(body, "stock_item_id")
    quantity_issued = req_num(body, "quantity_issued", positive=True)
    wp = require_path_resource("work_packages", work_package_id)
    stock_item = require_body_ref("stock_items", stock_item_id, "stock_item_id")
    contract = contract_of_work_package(wp)
    require_contract_active(contract)
    if wp["status"] != "IN_PROGRESS":
        raise_error(ERR_INVALID_STATE,
                    "material issuance requires work package IN_PROGRESS")
    if stock_item["contract_id"] != contract["id"]:
        raise_error(ERR_CROSS_CONTRACT_REFERENCE,
                    "stock item belongs to a different contract than the work package")
    if dec(quantity_issued) > stock_on_hand(stock_item):
        raise_error(ERR_INSUFFICIENT_STOCK,
                    "quantity_issued exceeds the stock item's on_hand")
    rec = new_record("material_issues", {
        "work_package_id": wp["id"],
        "stock_item_id": stock_item_id,
        "quantity_issued": quantity_issued,
        "quantity_returned": 0,
        "quantity_installed": None,
        "variance": None,
        "variance_note": None,
        "status": "OPEN",
    })
    return success_object(serialize("material_issues", rec), status=201)


@bp.get("/material-issues")
def list_material_issues():
    filters = {
        "work_package_id": request.args.get("work_package_id"),
        "stock_item_id": request.args.get("stock_item_id"),
        "status": request.args.get("status"),
    }
    return list_response("material_issues", filters)


@bp.get("/material-issues/<material_issue_id>")
def get_material_issue(material_issue_id):
    return get_one("material_issues", material_issue_id)


@bp.post("/material-issues/<material_issue_id>/return")
def return_material(material_issue_id):
    authorized(["FOREMAN"])
    body = get_body()
    quantity = req_num(body, "quantity", positive=True)
    issue = require_path_resource("material_issues", material_issue_id)
    wp = require_path_resource("work_packages", issue["work_package_id"])
    contract = contract_of_work_package(wp)
    require_contract_active(contract)
    if issue["status"] != "OPEN":
        raise_error(ERR_INVALID_STATE,
                    "returns are only accepted against an OPEN material issue")
    if dec(issue["quantity_returned"]) + dec(quantity) > dec(issue["quantity_issued"]):
        raise_error(ERR_RETURN_EXCEEDS_ISSUED,
                    "return would push quantity_returned above quantity_issued")
    issue["quantity_returned"] = num(dec(issue["quantity_returned"]) + dec(quantity))
    touch(issue)
    return success_object(serialize("material_issues", issue))


@bp.post("/material-issues/<material_issue_id>/reconcile")
def reconcile_material_issue(material_issue_id):
    role = authorized(["FOREMAN", "CONTRACTOR_PM"])
    body = get_body()
    quantity_installed = req_num(body, "quantity_installed", non_negative=True)
    variance_note = body.get("variance_note")
    if variance_note is not None and not isinstance(variance_note, str):
        raise_error(ERR_INVALID_REQUEST, "variance_note must be a string")
    issue = require_path_resource("material_issues", material_issue_id)
    wp = require_path_resource("work_packages", issue["work_package_id"])
    contract = contract_of_work_package(wp)
    require_contract_active(contract)
    if issue["status"] != "OPEN":
        raise_error(ERR_INVALID_STATE,
                    "only an OPEN material issue can be reconciled")

    variance = dec(issue["quantity_issued"]) - dec(quantity_installed) \
        - dec(issue["quantity_returned"])
    if variance != 0 and (
            role != "CONTRACTOR_PM" or not variance_note or not variance_note.strip()):
        # Variance path: CONTRACTOR_PM only, with a non-empty variance_note.
        raise_error(ERR_MATERIAL_VARIANCE_UNRESOLVED,
                    "non-zero reconciliation variance requires CONTRACTOR_PM "
                    "and a non-empty variance_note")
    issue["quantity_installed"] = quantity_installed
    if variance == 0:
        # Exact-match path: either role; variance recorded as zero.
        issue["variance"] = 0
        issue["status"] = "RECONCILED"
    else:
        issue["variance"] = num(variance)
        issue["variance_note"] = variance_note
        issue["status"] = "VARIANCE_RECONCILED"
    touch(issue)
    return success_object(serialize("material_issues", issue))
