"""Change notifications and their three divergent assessment outcomes."""

from flask import Blueprint

import clock
import db
import middleware as mw
import query
import response
from constants import (
    CHANGE_NOTICE_DAYS,
    CHANGE_TYPES,
    IMPACT_LEVELS,
    READ_CHANGE_NOTIFICATIONS,
    ROLE_APPLICANT_CONTACT,
    ROLE_CERTIFICATION_REVIEWER,
)
from errors import ApiError
from services import derive, nc as nc_service

bp = Blueprint("change_notifications", __name__)

_NOTICE_REQUIRED_TYPES = ("INGREDIENT_SUBSTITUTION", "SUPPLIER_CHANGE")


@bp.post("/gfco/change-notifications")
def create_notification():
    user_id, _ = mw.authenticate([ROLE_APPLICANT_CONTACT])
    data = mw.body()
    certificate_id = mw.req_str(data, "certificate_id")
    change_type = mw.req_enum(data, "change_type", CHANGE_TYPES)
    effective_on = mw.req_dt(data, "effective_on")
    description = mw.req_str(data, "description")
    replacement_ingredient_id = mw.opt_id(data, "replacement_ingredient_id")

    cert = query.fetch("certificate", certificate_id)
    query.maybe("ingredient", replacement_ingredient_id)
    if cert["applicant_id"] != user_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")
    if cert["status"] in ("REVOKED", "EXPIRED"):
        raise ApiError("ERR_CERTIFICATE_TERMINAL")

    now = clock.now()
    notice_days = clock.day_span(effective_on, now)
    if change_type in _NOTICE_REQUIRED_TYPES and notice_days < CHANGE_NOTICE_DAYS:
        raise ApiError("ERR_LATE_CHANGE_NOTIFICATION")

    applicant = db.applicants.get(cert["applicant_id"])
    if applicant is not None and applicant["compliance_posture"] in (
        "PROBATION",
        "SUSPENDED",
    ):
        raise ApiError("ERR_APPLICANT_POSTURE_BLOCKED")

    row = db.insert(
        db.change_notifications,
        {
            "certificate_id": certificate_id,
            "replacement_ingredient_id": replacement_ingredient_id,
            "change_type": change_type,
            "effective_on": effective_on,
            "description": description,
            "status": "SUBMITTED",
            "notified_days_before_effective": notice_days,
            "late_notification": notice_days < CHANGE_NOTICE_DAYS,
            "impact_level": None,
            "assessed_by_user_id": None,
            "assessed_on": None,
            "required_retest": False,
        },
    )
    return response.created(response.serialize(row))


@bp.get("/gfco/change-notifications/<notification_id>")
def get_notification(notification_id):
    mw.authenticate(READ_CHANGE_NOTIFICATIONS)
    return response.ok(
        response.serialize(query.fetch("change_notification", notification_id))
    )


@bp.get("/gfco/change-notifications")
def list_notifications():
    mw.authenticate(READ_CHANGE_NOTIFICATIONS)
    return query.listing(
        db.change_notifications,
        {
            "certificate_id": query.arg("certificate_id"),
            "replacement_ingredient_id": query.arg("replacement_ingredient_id"),
            "status": query.arg("status"),
        },
    )


@bp.post("/gfco/change-notifications/<notification_id>/assessment")
def assess(notification_id):
    user_id, _ = mw.authenticate([ROLE_CERTIFICATION_REVIEWER])
    data = mw.body()
    decision = mw.req_enum(data, "decision", ("ACCEPT", "REJECT"))
    impact_level = mw.req_enum(data, "impact_level", IMPACT_LEVELS)
    notice = query.fetch("change_notification", notification_id)

    if notice["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_CHANGE_NOTIFICATION_STATE")
    cert = db.certificates.get(notice["certificate_id"])
    if cert is not None and cert["status"] in ("REVOKED", "EXPIRED"):
        raise ApiError("ERR_CERTIFICATE_TERMINAL")

    notice["impact_level"] = impact_level
    notice["assessed_by_user_id"] = user_id
    notice["assessed_on"] = clock.now()

    product = db.products.get(cert["product_id"]) if cert is not None else None

    if decision == "ACCEPT" and impact_level == "NONE":
        notice["status"] = "ACCEPTED_NO_IMPACT"
        notice["required_retest"] = False
        db.touch(notice)
        return response.ok(response.serialize(notice))

    if decision == "ACCEPT" and impact_level == "LOW":
        notice["status"] = "ACCEPTED_WITH_CONDITIONS"
        notice["required_retest"] = True
        db.touch(notice)
        if product is not None:
            before = db.snapshot(product)
            derive.recompute_product_plan(product)
            db.touch_if_changed(product, before)
        return response.ok(response.serialize(notice))

    notice["status"] = "REJECTED_REQUIRES_RECERT"
    notice["required_retest"] = True
    db.touch(notice)
    if cert is not None:
        derive.suspend_certificate(cert, "CHANGE_REQUIRES_RECERT")
        nc_service.create(
            applicant_id=cert["applicant_id"],
            source_type="CHANGE_NOTIFICATION",
            category="DOCUMENTATION",
            severity="MAJOR",
            description="Change notification %s requires recertification"
            % notice["id"],
            raised_by_user_id=user_id,
            certificate_id=cert["id"],
        )
    return response.ok(response.serialize(notice))
