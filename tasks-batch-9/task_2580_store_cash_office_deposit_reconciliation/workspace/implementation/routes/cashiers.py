"""Cashier enrolment, coaching acknowledgement and reads (PRD section 3.2)."""
from flask import Blueprint

import db
import domain
import response
import serializers
import validation
from auth import endpoint, is_cashier, user_id
from errors import bad_request, err
from routes.common import list_collection

bp = Blueprint("cashiers", __name__)

TILL_ELIGIBILITIES = ("ELIGIBLE", "RESTRICTED", "BARRED")
COACHING_STATES = ("NONE", "COACHING_DUE", "COACHING_ACKNOWLEDGED")


def _ownership_guard(cashier_id):
    """PRD section 2.1: a Cashier may only act on their own cashier record."""
    if is_cashier():
        record = db.cashiers.get(cashier_id)
        if record is not None and record["id"] != user_id():
            raise err("ERR_UNAUTHORIZED", "a Cashier may only act on their own record")


@bp.post("/cash-ops/cashiers")
@endpoint(["StoreManager"])
def create_cashier():
    data = validation.body()
    store_id = validation.req_str(data, "store_id")
    employee_code = validation.req_str(data, "employee_code")
    display_name = validation.req_str(data, "display_name")
    till_eligibility = validation.opt_enum(data, "till_eligibility", TILL_ELIGIBILITIES, "ELIGIBLE")
    store = domain.get_store(store_id)
    for existing in db.cashiers.values():
        if existing["store_id"] == store["id"] and existing["employee_code"] == employee_code:
            raise bad_request("employee_code %s already exists at this store" % employee_code)
    record = db.base_record()
    record.update(
        {
            "store_id": store["id"],
            "employee_code": employee_code,
            "display_name": display_name,
            "till_eligibility": till_eligibility,
            "coaching_state": "NONE",
            "coaching_due_at": None,
            "rolling_absolute_variance_cents": 0,
            "rolling_net_variance_cents": 0,
            "reconciled_session_count": 0,
        }
    )
    db.cashiers[record["id"]] = record
    return response.object_response(serializers.cashier(record), 201)


@bp.post("/cash-ops/cashiers/<cashier_id>/acknowledge-coaching")
@endpoint(["Cashier", "StoreManager"])
def acknowledge_coaching(cashier_id):
    _ownership_guard(cashier_id)
    data = validation.body()
    validation.opt_str(data, "acknowledgement_note")
    cashier = domain.get_cashier(cashier_id)
    if cashier["coaching_state"] != "COACHING_DUE":
        raise bad_request("there is no coaching obligation to acknowledge")
    cashier["coaching_state"] = "COACHING_ACKNOWLEDGED"
    db.touch(cashier)
    return response.object_response(serializers.cashier(cashier))


@bp.get("/cash-ops/cashiers/<cashier_id>")
@endpoint(["Cashier", "StoreManager", "CashOfficeClerk", "LossPreventionInvestigator"])
def read_cashier(cashier_id):
    _ownership_guard(cashier_id)
    cashier = domain.get_cashier(cashier_id)
    return response.object_response(serializers.cashier(cashier))


@bp.get("/cash-ops/cashiers")
@endpoint(["StoreManager", "CashOfficeClerk", "LossPreventionInvestigator", "TreasuryAnalyst"])
def list_cashiers():
    return list_collection(
        db.cashiers,
        [
            ("store_id", "store_id"),
            ("till_eligibility", "till_eligibility"),
            ("coaching_state", "coaching_state"),
        ],
        serializers.cashier,
    )
