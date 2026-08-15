"""Project registrations: submit / approve / reject / resubmit / renew / withdraw."""
from datetime import timedelta
from flask import Blueprint, request

import db
from db import now, touch
from errors import err, not_found, invalid_request
from middleware import api, body, ctx, ALL_ROLES
from response import success_object, success_list
import services
from services import (
    PROTECTION_DAYS, RENEWAL_DAYS, RENEWAL_WINDOW_DAYS, RENEWAL_LIMIT,
    reattribute_for_registration,
)

bp = Blueprint("registrations", __name__)


@bp.route("/rep-agency/project-registrations", methods=["POST"])
@api(["Rep"])
def submit_registration():
    data = body()
    principal_id = data.get("principal_id")
    customer_id = data.get("customer_id")
    # existence (body FK ids, left-to-right)
    if not isinstance(principal_id, str) or principal_id not in db.principals:
        raise not_found("Principal")
    if not isinstance(customer_id, str) or customer_id not in db.customers:
        raise not_found("Customer")
    principal = db.principals[principal_id]
    rep = db.reps[ctx()["user_id"]]
    # linked-entity gates
    if principal["status"] == "TERMINATED":
        raise err("ERR_LINE_TERMINATED", "Principal is TERMINATED")
    if principal["status"] == "NOTICE_PENDING":
        raise err("ERR_LINE_UNDER_TERMINATION_NOTICE",
                  "Principal is under a termination notice")
    if rep["status"] == "COMMISSION_HOLD":
        raise err("ERR_REP_ON_HOLD", "Rep is on COMMISSION_HOLD")
    family_code = data.get("family_code")
    project_name = data.get("project_name")
    if not isinstance(family_code, str) or not family_code:
        raise invalid_request("family_code is required")
    if not isinstance(project_name, str) or not project_name:
        raise invalid_request("project_name is required")
    reg = {
        "principal_id": principal_id,
        "customer_id": customer_id,
        "rep_id": rep["id"],
        "family_code": family_code,
        "project_name": project_name,
        "submitted_at": now(),
        "protection_start": None,
        "protection_end": None,
        "renewals_used": 0,
        "status": "SUBMITTED",
    }
    db.stamp_new(reg)
    db.registrations[reg["id"]] = reg
    return success_object(reg, 201)


@bp.route("/rep-agency/project-registrations", methods=["GET"])
@api(ALL_ROLES)
def list_registrations():
    items = list(db.registrations.values())
    for param in ("principal_id", "customer_id", "rep_id", "status"):
        value = request.args.get(param)
        if value is not None:
            items = [r for r in items if r[param] == value]
    return success_list(items)


@bp.route("/rep-agency/project-registrations/<rid>", methods=["GET"])
@api(ALL_ROLES)
def get_registration(rid):
    reg = db.registrations.get(rid)
    if reg is None:
        raise not_found("ProjectRegistration")
    return success_object(reg)


def _reg_principal_owned(rid):
    reg = db.registrations.get(rid)
    if reg is None:
        raise not_found("ProjectRegistration")
    if ctx()["user_id"] != reg["principal_id"]:
        raise err("ERR_FORBIDDEN_NOT_OWNER",
                  "PrincipalOps may only act on registrations of its own principal")
    return reg


def _reg_rep_owned(rid):
    reg = db.registrations.get(rid)
    if reg is None:
        raise not_found("ProjectRegistration")
    if ctx()["user_id"] != reg["rep_id"]:
        raise err("ERR_FORBIDDEN_NOT_OWNER",
                  "Rep may only act on its own registrations")
    return reg


@bp.route("/rep-agency/project-registrations/<rid>/approve", methods=["POST"])
@api(["PrincipalOps"])
def approve_registration(rid):
    reg = _reg_principal_owned(rid)
    if reg["status"] != "SUBMITTED":
        raise err("ERR_INVALID_STATE_TRANSITION",
                  "Only a SUBMITTED registration can be approved")
    if services.active_agreement(reg["principal_id"]) is None:
        raise err("ERR_AGREEMENT_NOT_ACTIVE",
                  "The principal has no ACTIVE territory agreement")
    # half-open overlap: [now, now+PROTECTION_DAYS) vs existing windows
    new_start = now()
    new_end = new_start + timedelta(days=PROTECTION_DAYS)
    for other in db.registrations.values():
        if (other["id"] != reg["id"] and other["status"] == "APPROVED"
                and other["principal_id"] == reg["principal_id"]
                and other["customer_id"] == reg["customer_id"]
                and other["family_code"] == reg["family_code"]
                and other["protection_start"] is not None
                and new_start < other["protection_end"]
                and other["protection_start"] < new_end):
            raise err("ERR_PROTECTION_WINDOW_OVERLAP",
                      "Protection window overlaps an existing APPROVED registration")
    reg["status"] = "APPROVED"
    reg["protection_start"] = new_start
    reg["protection_end"] = new_end
    touch(reg)
    return success_object(reg)


@bp.route("/rep-agency/project-registrations/<rid>/reject", methods=["POST"])
@api(["PrincipalOps"])
def reject_registration(rid):
    reg = _reg_principal_owned(rid)
    if reg["status"] != "SUBMITTED":
        raise err("ERR_INVALID_STATE_TRANSITION",
                  "Only a SUBMITTED registration can be rejected")
    reg["status"] = "REJECTED"
    touch(reg)
    return success_object(reg)


@bp.route("/rep-agency/project-registrations/<rid>/resubmit", methods=["POST"])
@api(["Rep"])
def resubmit_registration(rid):
    reg = _reg_rep_owned(rid)
    if reg["status"] != "REJECTED":
        raise err("ERR_INVALID_STATE_TRANSITION",
                  "Only a REJECTED registration can be resubmitted")
    rep = db.reps[ctx()["user_id"]]
    if rep["status"] == "COMMISSION_HOLD":
        raise err("ERR_REP_ON_HOLD", "Rep is on COMMISSION_HOLD")
    reg["status"] = "SUBMITTED"
    reg["submitted_at"] = now()
    touch(reg)
    return success_object(reg)


@bp.route("/rep-agency/project-registrations/<rid>/renew", methods=["POST"])
@api(["Rep"])
def renew_registration(rid):
    reg = _reg_rep_owned(rid)
    if reg["status"] != "APPROVED":
        raise err("ERR_INVALID_STATE_TRANSITION",
                  "Only an APPROVED registration can be renewed")
    if now() < reg["protection_end"] - timedelta(days=RENEWAL_WINDOW_DAYS):
        raise err("ERR_RENEWAL_WINDOW_NOT_OPEN", "Renewal window is not yet open")
    if now() >= reg["protection_end"]:
        raise err("ERR_RENEWAL_WINDOW_NOT_OPEN", "Protection has lapsed")
    if reg["renewals_used"] >= RENEWAL_LIMIT:
        raise err("ERR_RENEWAL_LIMIT_REACHED", "Renewal limit reached")
    reg["renewals_used"] += 1
    reg["protection_end"] = reg["protection_end"] + timedelta(days=RENEWAL_DAYS)
    touch(reg)
    return success_object(reg)


@bp.route("/rep-agency/project-registrations/<rid>/withdraw", methods=["POST"])
@api(["Rep"])
def withdraw_registration(rid):
    reg = _reg_rep_owned(rid)
    if reg["status"] not in ("SUBMITTED", "APPROVED"):
        raise err("ERR_INVALID_STATE_TRANSITION",
                  "Only a SUBMITTED or APPROVED registration can be withdrawn")
    was_approved = reg["status"] == "APPROVED"
    reg["status"] = "WITHDRAWN"
    touch(reg)
    if was_approved:
        reattribute_for_registration(reg)
    return success_object(reg)
