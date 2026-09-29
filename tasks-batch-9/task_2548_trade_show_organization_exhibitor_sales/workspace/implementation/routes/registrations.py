"""Attendee registration, buyer screening and manual override (PRD 3.8)."""
from flask import Blueprint, request

import calc
import guards
import validate
import views
from db import base_row, by_created, db, touch
from errors import ApiError
from middleware import (FLOOR_MANAGER, REGISTRANT, SALES_REP, SHOW_DIRECTOR, authenticate)
from response import created, list_response, object_response, pagination

bp = Blueprint("registrations", __name__)

CATEGORIES = ("BUYER", "VIP_BUYER", "PRESS", "STUDENT", "EXHIBITOR_STAFF")
AUTHORITIES = ("NONE", "INFLUENCER", "RECOMMENDER", "DECISION_MAKER")
SPEND_BANDS = ("UNDER_50K", "K50_250K", "K250K_1M", "OVER_1M")


@bp.route("/shows/<show_id>/registrations", methods=["POST"])
def create_registration(show_id):
    body = validate.body()
    category = validate.enum(body, "category", CATEGORIES)
    company_name = validate.text(body, "company_name", 1, 160)
    job_title = validate.text(body, "job_title", 1, 120)
    purchasing_authority = validate.enum(body, "purchasing_authority", AUTHORITIES)
    annual_spend_band = validate.enum(body, "annual_spend_band", SPEND_BANDS)
    email = validate.email(body, "email")

    authenticate((REGISTRANT, SHOW_DIRECTOR))
    show = guards.get_show(show_id)
    guards.require_show_status(show, ("SPACE_SELECTION", "SELLING", "ON_SITE"))

    folded = email.casefold()
    for other in calc.show_registrations(show["id"]):
        if other["email"].casefold() == folded:
            validate.bad("email must be unique among the registrations of this show")

    score, status = calc.registration_score(category, purchasing_authority,
                                           annual_spend_band, job_title)
    row = base_row()
    row.update({
        "show_id": show["id"],
        "category": category,
        "company_name": company_name,
        "job_title": job_title,
        "purchasing_authority": purchasing_authority,
        "annual_spend_band": annual_spend_band,
        "email": email,
        "qualification_score": score,
        "qualification_status": status,
        "screening_override_reason": None,
    })
    db.registrations[row["id"]] = row
    touch(row)
    return created(views.registration_view(row))


@bp.route("/registrations/<registration_id>", methods=["GET"])
def read_registration(registration_id):
    authenticate((SHOW_DIRECTOR, SALES_REP, FLOOR_MANAGER, REGISTRANT))
    registration = guards.get_registration(registration_id)
    return object_response(views.registration_view(registration))


@bp.route("/shows/<show_id>/registrations", methods=["GET"])
def list_registrations(show_id):
    limit, offset = pagination()
    authenticate((SHOW_DIRECTOR, SALES_REP))
    show = guards.get_show(show_id)
    rows = by_created(calc.show_registrations(show["id"]))
    for field in ("category", "qualification_status"):
        wanted = request.args.get(field)
        if wanted:
            rows = [r for r in rows if r[field] == wanted]
    return list_response([views.registration_view(r) for r in rows], limit, offset)


@bp.route("/registrations/<registration_id>/screen", methods=["POST"])
def screen_registration(registration_id):
    body = validate.body()
    decision = validate.enum(body, "decision", ("QUALIFIED", "REJECTED"))
    # An empty reason is not a structural failure: PRD 3.8 pins the empty-string
    # case to ERR_WAIVER_REASON_REQUIRED, checked after the state gates below.
    reason = validate.text(body, "reason", 0, 500, required=False)

    authenticate((SHOW_DIRECTOR,))
    registration = guards.get_registration(registration_id)
    show = guards.get_show(registration["show_id"])
    guards.require_show_status(show, ("PLANNING", "SPACE_SELECTION", "SELLING", "ON_SITE"))
    if registration["qualification_status"] != "WAITLISTED":
        validate.bad("only a WAITLISTED registration may be overridden")
    if not reason:
        raise ApiError("ERR_WAIVER_REASON_REQUIRED",
                       "a screening override requires a reason")

    registration["qualification_status"] = decision
    registration["screening_override_reason"] = reason
    touch(registration)
    return object_response(views.registration_view(registration))
