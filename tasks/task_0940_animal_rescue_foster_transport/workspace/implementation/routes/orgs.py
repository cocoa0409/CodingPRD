"""Organizations, people and the logical-clock test-driving endpoint."""

from flask import Blueprint, request

import auth
import clock
import derive
import envelope
import gates
from errors import ApiError
from routing import must
from store import DB, touch
from validation import Field, parse_body

bp = Blueprint("orgs", __name__)


@bp.post("/rescue/organizations")
def create_organization():
    auth.authenticate(["PlatformAdmin"])
    body = parse_body(request, [
        Field("name", "string", required=True),
        Field("org_type", "string", required=True, enum="org_type"),
        Field("state_code", "string", required=True, fmt="state"),
        Field("default_methodology", "string", default="SAC", enum="methodology"),
    ])
    # Gate 1: a brand-new organization has no owning organization to be frozen.
    org = DB.insert("Organization", {
        "name": body["name"],
        "org_type": body["org_type"],
        "state_code": body["state_code"],
        "default_methodology": body["default_methodology"],
        "records_freeze_active": False,
        "records_freeze_reason": None,
        "freeze_status": "UNFROZEN",
    })
    return envelope.created(derive.organization(org))


@bp.get("/rescue/organizations/<org_id>")
def read_organization(org_id):
    ctx = auth.authenticate(["PlatformAdmin", "FinanceOfficer", "TransportDispatcher", "PartnerRescue"])
    org = DB.get("Organization", org_id)
    if org is not None:
        # PRD 2.1: a PartnerRescue may read "its own organization record".
        auth.own_if(ctx, "PartnerRescue", org["id"])
    org = must("Organization", org_id)
    return envelope.ok(derive.organization(org))


@bp.post("/rescue/organizations/<org_id>/records-freeze")
def records_freeze(org_id):
    auth.authenticate(["PlatformAdmin"])
    body = parse_body(request, [
        Field("freeze_active", "boolean", required=True),
        Field("reason", "string"),
    ])
    org = must("Organization", org_id)
    # Gate 1 exempts this write so that a freeze can always be lifted (PRD 2.6).

    if body["freeze_active"]:
        # Rung 18: the UNFROZEN -> FROZEN transition, whose declared
        # preconditions are, in order, "freeze_status == UNFROZEN" and
        # "reason is a non-empty string".
        if org["freeze_status"] != "UNFROZEN":
            raise ApiError("ERR_INVALID_STATE", "The organization is already FROZEN.")
        # Adjudication of friction 3: Reading B -- a missing or empty `reason`
        # on a freeze-raise is a present-but-inadequate value at the
        # state-machine level and reports ERR_INVALID_STATE at rung 18.
        # Reading A (ERR_VALIDATION at rung 6) would have to invent a
        # conditionally-required body field, contradicting the endpoint's own
        # declaration that `reason` is optional, and would leave the declared
        # transition precondition "reason is a non-empty string" with no
        # observable effect of its own.  Reading B contradicts nothing and
        # strands nothing.
        reason = body["reason"]
        if not isinstance(reason, str) or reason.strip() == "":
            raise ApiError("ERR_INVALID_STATE",
                           "Raising a records freeze requires a non-empty reason.")
        org["records_freeze_active"] = True
        org["records_freeze_reason"] = reason
        org["freeze_status"] = "FROZEN"
    else:
        if org["freeze_status"] != "FROZEN":
            raise ApiError("ERR_INVALID_STATE", "The organization is already UNFROZEN.")
        org["records_freeze_active"] = False
        org["freeze_status"] = "UNFROZEN"
        # PRD 3.1: records_freeze_reason is deliberately RETAINED across a lift.
    touch(org)
    return envelope.ok(derive.organization(org))


@bp.post("/rescue/persons")
def create_person():
    auth.authenticate(["PlatformAdmin", "IntakeOfficer", "FosterCoordinator", "AdoptionCounselor"])
    body = parse_body(request, [
        Field("full_name", "string", required=True),
        Field("email", "string", required=True, fmt="email"),
        Field("youngest_child_age_years", "integer", default=99, fmt="gte0"),
        Field("resident_cat_count", "integer", default=0, fmt="gte0"),
        Field("resident_dog_count", "integer", default=0, fmt="gte0"),
        Field("housing_type", "string", default="HOUSE", enum="housing_type"),
        Field("has_fenced_yard", "boolean", default=False),
        Field("hardship_certified", "boolean", default=False),
        Field("driver_license_number", "string", default=None),
    ])
    # Gate 1: a Person carries no organization-bearing field, so it is ungated.
    person = DB.insert("Person", {
        "full_name": body["full_name"],
        "email": body["email"],
        "youngest_child_age_years": body["youngest_child_age_years"],
        "resident_cat_count": body["resident_cat_count"],
        "resident_dog_count": body["resident_dog_count"],
        "housing_type": body["housing_type"],
        "has_fenced_yard": body["has_fenced_yard"],
        "hardship_certified": body["hardship_certified"],
        "driver_license_number": body["driver_license_number"],
    })
    return envelope.created(derive.person(person))


@bp.get("/rescue/persons/<person_id>")
def read_person(person_id):
    auth.authenticate(["PlatformAdmin", "IntakeOfficer", "FosterCoordinator",
                       "AdoptionCounselor", "FinanceOfficer", "TransportDispatcher"])
    return envelope.ok(derive.person(must("Person", person_id)))


@bp.post("/rescue/_clock/set_current_utc")
def set_clock():
    auth.authenticate(["PlatformAdmin"])
    body = parse_body(request, [Field("to_iso8601", "datetime", required=True)])
    # PRD 2.6: the clock setter is the second write exempt from the freeze gate.
    # (b) The caller's own bytes are stored and echoed back verbatim.
    current = clock.CLOCK.set(body["to_iso8601"])
    return envelope.ok({"current_utc": current})
