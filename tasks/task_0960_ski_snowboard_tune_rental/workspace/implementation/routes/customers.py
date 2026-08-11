from flask import Blueprint, g

from auth import auth, check_own
from envelope import created, success
from errors import err
from store import db, new_entity, pub
from validate import (SKIER_TYPES, body, get_or_404, req_date, req_enum,
                      req_int, req_num, req_str)

bp = Blueprint("customers", __name__)


@bp.post("/shop/customers")
def create_customer():
    auth("FrontDesk", "Manager")
    b = body()
    full_name = req_str(b, "full_name")
    email = req_str(b, "email")
    date_of_birth = req_date(b, "date_of_birth")
    height_cm = req_num(b, "height_cm")
    weight_kg = req_num(b, "weight_kg")
    boot_sole_mm = req_int(b, "boot_sole_mm")
    skier_type = req_enum(b, "skier_type", SKIER_TYPES)
    if any(c["email"] == email for c in db.customers.values()):
        raise err("ERR_INVALID_REQUEST", "Email already registered: %s" % email)
    cust = new_entity({
        "full_name": full_name,
        "email": email,
        "date_of_birth": date_of_birth,
        "height_cm": height_cm,
        "weight_kg": weight_kg,
        "boot_sole_mm": boot_sole_mm,
        "skier_type": skier_type,
        "standing": "GOOD_STANDING",
        "late_return_count": 0,
    })
    db.customers[cust["id"]] = cust
    return created(pub(cust))


@bp.get("/shop/customers/<cid>")
def get_customer(cid):
    auth("Customer", "FrontDesk", "Technician", "Manager")
    cust = get_or_404(db.customers, cid, "Customer")
    check_own(cust["id"])
    return success(pub(cust))
