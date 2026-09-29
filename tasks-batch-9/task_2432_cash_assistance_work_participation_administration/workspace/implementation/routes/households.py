"""Household registration, reads and carried-in prior assistance (PRD 3.1)."""

import re

from flask import Blueprint

import guards
from calc import FAMILY_TYPES, derive_family_type
from domain import lookup, recompute_household_clocks, rows_where
from guards import Fields, raw_body, require, require_owner
from respond import created, filter_value, listing, ok
from store import db, new_record, ordered

bp = Blueprint("households", __name__)

COUNTY_CODE_RE = re.compile(r"^[A-Z]{3}$")
APPLICATION_STATUSES = ("RECEIVED", "DETERMINED", "DIVERSION_OFFERED", "APPROVED",
                        "DENIED", "DIVERTED", "WITHDRAWN")


@bp.post("/households")
def register_household():
    require(guards.CASEWORKER)
    body = raw_body()
    fields = Fields(body)
    fields.text("head_of_household_name", allow_empty=False)
    fields.pattern("county_code", COUNTY_CODE_RE)
    fields.integer("household_size", minimum=1)
    fields.integer("adult_count", minimum=0)
    fields.integer("youngest_child_age_months", minimum=0)
    fields.boolean("has_subsidized_child_care", required=False, default=False)

    family_type = derive_family_type(fields["adult_count"],
                                    fields["has_subsidized_child_care"],
                                    fields["youngest_child_age_months"])
    household = new_record({
        "head_of_household_name": fields["head_of_household_name"],
        "county_code": fields["county_code"],
        "household_size": fields["household_size"],
        "adult_count": fields["adult_count"],
        "youngest_child_age_months": fields["youngest_child_age_months"],
        "has_subsidized_child_care": fields["has_subsidized_child_care"],
        "family_type": family_type,
        "prior_state_clock_months": 0,
        "prior_federal_clock_months": 0,
        "state_clock_months_used": 0,
        "federal_clock_months_used": 0,
        "extension_months_used": 0,
        "issued_countable_months": 0,
        "diversion_ineligible_through_month": None,
    })
    db.households[household["id"]] = household
    return created(household)


@bp.get("/households/<household_id>")
def read_household(household_id):
    actor = require()
    household = lookup("households", household_id, "ERR_HOUSEHOLD_NOT_FOUND")
    require_owner(actor, household_id)
    return ok(household)


@bp.get("/households/<household_id>/applications")
def list_household_applications(household_id):
    actor = require()
    lookup("households", household_id, "ERR_HOUSEHOLD_NOT_FOUND")
    from respond import pagination
    limit, offset = pagination()
    require_owner(actor, household_id)
    status = filter_value("status")
    rows = rows_where("applications", household_id=household_id)
    if status is not None:
        rows = [row for row in rows if row["status"] == status]
    rows = list(reversed(ordered(rows)))  # PRD 3.1: newest first
    return listing(rows, limit, offset)


@bp.post("/households/<household_id>/prior-assistance-record")
def prior_assistance_record(household_id):
    require(*guards.STAFF_ROLES)
    household = lookup("households", household_id, "ERR_HOUSEHOLD_NOT_FOUND")
    fields = Fields(raw_body())
    fields.text("source_state_code", allow_empty=False)
    fields.integer("state_clock_months", minimum=0)
    fields.integer("federal_clock_months", minimum=0)

    household["prior_state_clock_months"] = fields["state_clock_months"]
    household["prior_federal_clock_months"] = fields["federal_clock_months"]
    from store import touch
    touch(household)
    recompute_household_clocks(household)
    return ok(household)


APPLICATION_STATUS_DOMAIN = APPLICATION_STATUSES
FAMILY_TYPE_DOMAIN = tuple(FAMILY_TYPES)
