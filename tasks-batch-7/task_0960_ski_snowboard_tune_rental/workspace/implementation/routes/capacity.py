from flask import Blueprint

from auth import auth
from envelope import created, success
from errors import err
from store import db, new_entity, pub
from validate import body, get_or_404, req_date, req_int

bp = Blueprint("capacity", __name__)


@bp.post("/shop/shop-day-capacity")
def create_capacity():
    auth("Manager")
    b = body()
    service_date = req_date(b, "service_date")
    base = req_int(b, "base_labor_minutes", minimum=0)
    rush = req_int(b, "rush_reserved_minutes", minimum=0)
    if rush > base:
        raise err("ERR_INVALID_REQUEST",
                  "rush_reserved_minutes may not exceed base_labor_minutes")
    if any(c["service_date"] == service_date
           for c in db.shop_day_capacity.values()):
        raise err("ERR_CAPACITY_EXISTS",
                  "A ShopDayCapacity row already exists for this service_date")
    cap = new_entity({
        "service_date": service_date,
        "base_labor_minutes": base,
        "rush_reserved_minutes": rush,
        "booked_minutes": 0,
        "rush_booked_minutes": 0,
    })
    db.shop_day_capacity[cap["id"]] = cap
    return created(pub(cap))


@bp.get("/shop/shop-day-capacity/<cid>")
def get_capacity(cid):
    auth("FrontDesk", "Technician", "Manager")
    cap = get_or_404(db.shop_day_capacity, cid, "Shop-day capacity")
    return success(pub(cap))
