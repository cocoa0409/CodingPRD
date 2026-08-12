"""Passengers."""
from datetime import date

from flask import Blueprint

import db
from errors import bad_request
from middleware import require_roles
from response import success_object
from routes.util import (get_or_404, json_body, parse_date_field, require_enum,
                         require_fields, serialize_passenger)

bp = Blueprint("passengers", __name__)

ALL_ROLES = ("PlatformAdmin", "OpsManager", "Dispatcher", "Agent",
             "Confirmer", "Requester", "BillingClerk")


def _passenger_class(dob: date) -> str:
    """Derive ADULT | SENIOR | UMNR from dob and the logical clock."""
    now = db.now().date()
    age = now.year - dob.year - ((now.month, now.day) < (dob.month, dob.day))
    if age < 18:
        return "UMNR"
    if age >= 65:
        return "SENIOR"
    return "ADULT"


@bp.post("/maa/passengers")
def create_passenger():
    require_roles("Requester", "PlatformAdmin")
    body = json_body()
    require_fields(body, ["full_name", "dob", "mobility_code"])
    full_name = body["full_name"]
    if not isinstance(full_name, str) or not full_name.strip():
        raise bad_request("full_name must be a non-empty string")
    dob = parse_date_field(body["dob"], "dob")
    mobility = require_enum(body["mobility_code"], {"WCHR", "WCHS", "WCHC"}, "mobility_code")
    passenger = db.common_fields()
    passenger.update({
        "full_name": full_name,
        "dob": body["dob"],
        "mobility_code": mobility,
        "passenger_class": _passenger_class(dob),
        "airline_pnr": body.get("airline_pnr"),
        "private_card_token": body.get("private_card_token"),
    })
    db.passengers[passenger["id"]] = passenger
    return success_object(serialize_passenger(passenger), status=201)


@bp.get("/maa/passengers/<pid>")
def get_passenger(pid):
    require_roles(*ALL_ROLES)
    passenger = get_or_404(db.passengers, pid, "Passenger")
    return success_object(serialize_passenger(passenger))
