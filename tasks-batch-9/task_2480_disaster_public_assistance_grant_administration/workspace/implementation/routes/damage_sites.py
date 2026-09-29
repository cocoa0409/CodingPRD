"""DamageAssessmentSite endpoints: collection and adjudication."""
from flask import Blueprint

from db import new_row, parse_instant, setf, touch
from errors import fail
from middleware import ALL_ROLES, authenticate, check_scope
from routes.common import PREFIX, find, render_list, require, respond
from services.constants import CATEGORIES
from services.ledger import disaster_of_facility, recompute_disaster_indicator
from validate import body, present, v_enum, v_id, v_instant, v_int, v_num, v_str

bp = Blueprint("damage_sites", __name__)


@bp.route(PREFIX + "/damage-sites", methods=["POST"])
def create_damage_site():
    actor = authenticate(("ApplicantAgent",))
    payload = body()

    raw_facility = payload.get("facility_id")
    if isinstance(raw_facility, str):
        facility = find("facilities", raw_facility)
        if facility is not None:
            check_scope(actor, facility["applicant_id"])

    facility_id = v_id(payload, "facility_id")
    category = v_enum(payload, "category", CATEGORIES)
    reported_loss_cents = v_int(payload, "reported_loss_cents", minimum=0)
    damage_observed_at = v_instant(payload, "damage_observed_at")
    work_completed_pct = v_num(payload, "work_completed_pct", required=False,
                               default=0, minimum=0, maximum=100)

    facility = require("facilities", facility_id)

    disaster = disaster_of_facility(facility)
    if disaster is not None:
        observed = parse_instant(damage_observed_at)
        start = parse_instant(disaster["incident_start_at"])
        end = parse_instant(disaster["incident_end_at"])
        if not (start <= observed <= end):
            fail("ERR_OUTSIDE_INCIDENT_PERIOD",
                 "damage_observed_at falls outside the incident period")

    row = new_row("damage_sites", {
        "facility_id": facility_id,
        "category": category,
        "reported_loss_cents": reported_loss_cents,
        "damage_observed_at": damage_observed_at,
        "work_completed_pct": work_completed_pct,
        "validated_loss_cents": 0,
        "validation_status": "REPORTED",
        "rejection_reason": None,
    })
    return respond(row, 201)


@bp.route(PREFIX + "/damage-sites", methods=["GET"])
def list_damage_sites():
    authenticate(ALL_ROLES)
    return render_list("damage_sites", {
        "facility_id": "facility_id",
        "validation_status": "validation_status",
        "category": "category",
    })


@bp.route(PREFIX + "/damage-sites/<damage_site_id>", methods=["GET"])
def get_damage_site(damage_site_id):
    authenticate(ALL_ROLES)
    row = require("damage_sites", damage_site_id)
    return respond(row)


@bp.route(PREFIX + "/damage-sites/<damage_site_id>/validate", methods=["POST"])
def validate_damage_site(damage_site_id):
    authenticate(("ProgramSpecialist",))
    site = require("damage_sites", damage_site_id)
    payload = body()

    decision = v_enum(payload, "decision", ("VALIDATE", "REJECT"))
    validated_loss_cents = None
    rejection_reason = None
    if decision == "VALIDATE":
        validated_loss_cents = v_int(payload, "validated_loss_cents", minimum=0)
    else:
        rejection_reason = v_str(payload, "rejection_reason", non_empty=False)

    if site["validation_status"] != "REPORTED":
        fail("ERR_DAMAGE_SITE_ALREADY_ADJUDICATED",
             "this damage site has already been adjudicated")

    if decision == "VALIDATE":
        setf(site, "validated_loss_cents", validated_loss_cents)
        setf(site, "validation_status", "VALIDATED")
        touch(site)
        facility = find("facilities", site["facility_id"])
        disaster = disaster_of_facility(facility) if facility else None
        if disaster is not None:
            recompute_disaster_indicator(disaster)
            touch(disaster)
    else:
        setf(site, "validated_loss_cents", 0)
        setf(site, "validation_status", "REJECTED")
        setf(site, "rejection_reason", rejection_reason)
        touch(site)

    return respond(site)
