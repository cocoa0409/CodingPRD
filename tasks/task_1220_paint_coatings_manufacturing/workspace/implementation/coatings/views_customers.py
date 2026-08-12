"""Customer endpoints."""
from flask import Blueprint

from .domain import ser_customer
from .errors import ApiError, not_found
from .store import store
from .util import auth, body, list_response, new_record, success, v_int, v_state_code, v_str

bp = Blueprint("customers", __name__)

ALL = ("PlantManager", "LabTechnician", "ProductionOperator", "QCInspector", "RegulatoryClerk", "Dealer")


@bp.post("/coatings/customers")
def create_customer():
    auth(("PlantManager",))
    b = body()
    name = v_str(b, "name")
    home_state_code = v_state_code(b, "home_state_code")
    cap = v_int(b, "annual_credit_cap_cents", minv=0)
    rec = new_record()
    rec.update({
        "name": name,
        "home_state_code": home_state_code,
        "annual_credit_cap_cents": cap,
        "credit_balance_cents": 0,
        "credit_used_ytd_cents": 0,
    })
    store.customers[rec["id"]] = rec
    return success(ser_customer(rec), 201)


@bp.get("/coatings/customers/<cid>")
def get_customer(cid):
    user_id, role = auth(ALL)
    if role == "Dealer" and cid != user_id:
        raise ApiError(403, "ERR_FORBIDDEN", "Dealer may only read its own customer record")
    rec = store.customers.get(cid)
    if rec is None:
        raise not_found()
    return success(ser_customer(rec), 200)
