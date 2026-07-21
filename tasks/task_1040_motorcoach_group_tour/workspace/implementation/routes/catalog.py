"""TourProduct, Coach, Driver, Guide endpoints."""
from flask import Blueprint

import services
from calc import DEFAULT_DEPOSIT_CENTS
from store import db
from web import authenticate, get_body, created, ok, req_str, req_int, opt_int

bp = Blueprint("catalog", __name__)

READ_ROLES = "ALL"


@bp.post("/api/tour-products")
def create_tour_product():
    authenticate({"OpsManager"})
    body = get_body()
    name = req_str(body, "name")
    duration_days = req_int(body, "duration_days", min_val=1)
    base_price = req_int(body, "base_price_per_person_cents", min_val=0)
    deposit = opt_int(body, "deposit_per_person_cents", DEFAULT_DEPOSIT_CENTS, min_val=0)
    tp = services.create_tour_product(name, duration_days, base_price, deposit)
    return created(services.serialize(tp))


@bp.post("/api/coaches")
def create_coach():
    authenticate({"OpsManager"})
    body = get_body()
    code = req_str(body, "code")
    seat_capacity = req_int(body, "seat_capacity", min_val=1)
    day_rate = req_int(body, "day_rate_cents", min_val=0)
    c = services.create_coach(code, seat_capacity, day_rate)
    return created(services.serialize(c))


@bp.get("/api/coaches/<coach_id>")
def get_coach(coach_id):
    authenticate(READ_ROLES)
    c = services.get_or_404(db.coaches, coach_id)
    return ok(services.serialize(c))


@bp.post("/api/drivers")
def create_driver():
    authenticate({"OpsManager"})
    body = get_body()
    name = req_str(body, "name")
    license_no = req_str(body, "license_no")
    day_rate = req_int(body, "day_rate_cents", min_val=0)
    d = services.create_driver(name, license_no, day_rate)
    return created(services.serialize(d))


@bp.get("/api/drivers/<driver_id>")
def get_driver(driver_id):
    authenticate(READ_ROLES)
    d = services.get_or_404(db.drivers, driver_id)
    return ok(services.serialize(d))


@bp.post("/api/guides")
def create_guide():
    authenticate({"OpsManager"})
    body = get_body()
    name = req_str(body, "name")
    day_rate = req_int(body, "day_rate_cents", min_val=0)
    g = services.create_guide(name, day_rate)
    return created(services.serialize(g))
