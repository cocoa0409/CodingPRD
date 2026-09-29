"""Customer account endpoints."""

from flask import Blueprint

import db
import validation as v
from middleware import (
    COMMUNITY_LIAISON,
    GRID_PLANNER,
    PSPS_DUTY_OFFICER,
    REGULATORY_REVIEWER,
    TRANSMISSION_ENGINEER,
    roles,
)
from response import object_response
from services import calc

bp = Blueprint("customers", __name__)

CUSTOMER_CLASSES = ("RESIDENTIAL", "COMMERCIAL", "CRITICAL_FACILITY")
LANGUAGES = ("EN", "ES", "ZH", "TL", "VI")
CHANNELS = ("SMS", "VOICE", "EMAIL")
ACCESSIBILITY_NEEDS = ("LARGE_PRINT", "TTY", "AUDIO")

READ_ROLES = (
    GRID_PLANNER,
    PSPS_DUTY_OFFICER,
    COMMUNITY_LIAISON,
    REGULATORY_REVIEWER,
    TRANSMISSION_ENGINEER,
)


@bp.post("/customers")
@roles(GRID_PLANNER, COMMUNITY_LIAISON)
def create_customer():
    body = v.Body()
    account_number = body.string("account_number", 3, 40)
    circuit_id = body.string("circuit_id", 1, None)
    customer_class = body.enum("customer_class", CUSTOMER_CLASSES)
    preferred_language = body.enum("preferred_language", LANGUAGES)
    channels = body.string_set("notification_channels", CHANNELS)
    address_zone_code = body.string("address_zone_code", 1, 20)
    medical_baseline = body.boolean("medical_baseline", default=False)
    needs = body.string_set(
        "accessibility_needs", ACCESSIBILITY_NEEDS, required=False, non_empty=False, default=()
    )

    circuit = v.circuit(circuit_id)
    v.unique_code(db.customers, "account_number", account_number)

    row = db.new_row()
    row["account_number"] = account_number
    row["circuit_id"] = circuit["id"]
    row["customer_class"] = customer_class
    row["medical_baseline"] = medical_baseline
    row["preferred_language"] = preferred_language
    row["notification_channels"] = list(channels)
    row["accessibility_needs"] = list(needs)
    row["address_zone_code"] = address_zone_code
    row["notification_tier"] = calc.customer_notification_tier(
        customer_class, medical_baseline
    )
    db.customers[row["id"]] = row

    calc.recompute_customer_counts(circuit)
    db.touch(circuit)

    return object_response(db.customer_out(row), 201)


@bp.get("/customers/<customer_id>")
@roles(*READ_ROLES)
def get_customer(customer_id):
    return object_response(db.customer_out(v.customer(customer_id)))
