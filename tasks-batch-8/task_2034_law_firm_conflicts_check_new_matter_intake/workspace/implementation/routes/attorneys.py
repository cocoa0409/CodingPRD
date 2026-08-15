"""Attorney onboarding incl. the lateral sweep (PRD 3.2)."""

from flask import Blueprint

import db
from db import stamp_new
from errors import invalid
from middleware import caller, admit, body
from response import ok_object
from services.matching import run_lateral_sweep
from services.validate import PRACTICE_GROUPS, HIRE_TYPES, resolve, valid_date_string

bp = Blueprint("attorneys", __name__)

STAFF = ("FirmAdmin", "IntakeSpecialist", "ResponsibleAttorney",
         "ConflictsPartner", "BillingClerk")


@bp.post("/intake/attorneys")
def create_attorney():
    _, role = caller()
    admit(role, ("FirmAdmin",))
    data = body()

    # Tier 12: request shape.
    full_name = data.get("full_name")
    if not isinstance(full_name, str) or full_name == "":
        raise invalid("full_name is required")
    bar_number = data.get("bar_number")
    if not isinstance(bar_number, str) or bar_number == "":
        raise invalid("bar_number is required")
    practice_group = data.get("practice_group")
    if practice_group not in PRACTICE_GROUPS:
        raise invalid("practice_group must be one of " + ", ".join(PRACTICE_GROUPS))
    hire_type = data.get("hire_type", "INTERNAL")
    if hire_type not in HIRE_TYPES:
        raise invalid("hire_type must be INTERNAL or LATERAL")

    lateral_employed_from = data.get("lateral_employed_from")
    lateral_employed_to = data.get("lateral_employed_to")
    prior_client_names = data.get("prior_client_names")
    if hire_type == "LATERAL":
        # All three lateral inputs are required (names list may be empty).
        if not valid_date_string(lateral_employed_from):
            raise invalid("lateral_employed_from (YYYY-MM-DD) is required for LATERAL")
        if not valid_date_string(lateral_employed_to):
            raise invalid("lateral_employed_to (YYYY-MM-DD) is required for LATERAL")
        if (not isinstance(prior_client_names, list)
                or any(not isinstance(n, str) for n in prior_client_names)):
            raise invalid("prior_client_names must be a list of strings for LATERAL")
    else:
        if prior_client_names is None:
            prior_client_names = []

    attorney = stamp_new({
        "full_name": full_name,
        "bar_number": bar_number,
        "practice_group": practice_group,
        "hire_type": hire_type,
        "lateral_employed_from": lateral_employed_from,
        "lateral_employed_to": lateral_employed_to,
        "prior_client_names": list(prior_client_names) if prior_client_names else [],
        "status": "ACTIVE",
    })
    db.store.attorneys[attorney["id"]] = attorney

    if hire_type == "LATERAL":
        # Synchronous lateral sweep; the attorney starts LATERAL_PENDING if
        # the sweep created at least one hit, else ACTIVE.
        if run_lateral_sweep(attorney) > 0:
            attorney["status"] = "LATERAL_PENDING"

    return ok_object(attorney, 201)


@bp.get("/intake/attorneys/<aid>")
def get_attorney(aid):
    _, role = caller()
    admit(role, STAFF)
    attorney = resolve(db.store.attorneys, aid)
    return ok_object(attorney)
