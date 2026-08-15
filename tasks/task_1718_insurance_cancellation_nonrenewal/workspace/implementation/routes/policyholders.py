"""Policyholder endpoints (PRD §3.2)."""

import db
import util
from middleware import require_roles
from response import success_object
from flask import Blueprint

bp = Blueprint("policyholders", __name__)

ALL_READERS = ("ComplianceOfficer", "Underwriter", "Policyholder")


@bp.post("/carrier/policyholders")
@require_roles("Underwriter")
def create_policyholder(_user_id, _role):
    body = util.get_body()
    util.check_fields(body, required=["full_name", "mailing_address", "email"])
    rec = util.stamp_new(
        {
            "full_name": util.require_str(body, "full_name"),
            "mailing_address": util.require_str(body, "mailing_address"),
            "email": util.require_str(body, "email"),
        }
    )
    db.policyholders[rec["id"]] = rec
    return success_object(util.public(rec), 201)


@bp.get("/carrier/policyholders/<policyholderId>")
@require_roles(*ALL_READERS)
def get_policyholder(policyholderId, _user_id, _role):
    rec = util.resolve(db.policyholders, policyholderId)
    return success_object(util.public(rec), 200)
