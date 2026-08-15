"""Logical clock and dormancy sweep endpoints (PRD 2.5, 3.2)."""

from datetime import timedelta

from flask import Blueprint

import clock
import db
import middleware as mw
import response as resp
from helpers import (
    touch, find_applicable_rule, add_years,
)

bp = Blueprint("system", __name__)


@bp.post("/escheatment/_clock/set_current_utc")
def set_clock():
    ctx = mw.get_user()
    mw.require_role(ctx, ("HolderAdmin",))
    data = mw.body_json()
    dt = mw.parse_iso_datetime(data.get("to_iso8601"), "to_iso8601")
    clock.set_current(dt)
    return resp.success({"current_utc": clock.current_utc_iso()}, "object", 200)


@bp.post("/escheatment/_sweeps/dormancy")
def run_sweep():
    ctx = mw.get_user()
    mw.require_role(ctx, ("HolderAdmin",))
    mw.body_json(required=False)
    sweep_date = clock.today()

    transitioned_property_ids = []
    expired_letter_ids = []
    reportable_property_ids = []

    # Pass 1: ACTIVE -> DORMANT (strictly past the dormancy anniversary).
    for prop in list(db.properties.values()):
        if prop["status"] != "ACTIVE":
            continue
        rule = find_applicable_rule(
            prop["state_code"], prop["property_type"], prop["last_contact_date"]
        )
        if rule is None:
            continue  # sweep treats a missing rule as a skip, not an error
        anniversary = add_years(prop["last_contact_date"], rule["dormancy_years"])
        if sweep_date > anniversary:
            prop["status"] = "DORMANT"
            prop["dormancy_date"] = anniversary + timedelta(days=1)
            touch(prop)
            transitioned_property_ids.append(prop["id"])

    # Pass 2: properties ALREADY DORMANT at sweep start with value below the
    # dd threshold advance to REPORTABLE. (A property that turned DORMANT in
    # pass 1 is not reconsidered until a later sweep.)
    for prop in list(db.properties.values()):
        if prop["status"] != "DORMANT":
            continue
        if prop["id"] in transitioned_property_ids:
            continue
        rule = find_applicable_rule(
            prop["state_code"], prop["property_type"], prop["last_contact_date"]
        )
        if rule is None:
            continue
        if prop["original_value_cents"] < rule["dd_threshold_cents"]:
            prop["status"] = "REPORTABLE"
            touch(prop)
            reportable_property_ids.append(prop["id"])

    # Pass 3: SENT/DELIVERED letters whose response_deadline is strictly
    # before the sweep date expire; their property DUE_DILIGENCE -> REPORTABLE.
    for letter in list(db.letters.values()):
        if letter["status"] not in ("SENT", "DELIVERED"):
            continue
        if sweep_date > letter["response_deadline"]:
            letter["status"] = "EXPIRED"
            touch(letter)
            expired_letter_ids.append(letter["id"])
            prop = db.properties.get(letter["property_id"])
            if prop is not None and prop["status"] == "DUE_DILIGENCE":
                prop["status"] = "REPORTABLE"
                touch(prop)
                reportable_property_ids.append(prop["id"])

    return resp.success(
        {
            "transitioned_property_ids": transitioned_property_ids,
            "expired_letter_ids": expired_letter_ids,
            "reportable_property_ids": reportable_property_ids,
        },
        "object",
        200,
    )
