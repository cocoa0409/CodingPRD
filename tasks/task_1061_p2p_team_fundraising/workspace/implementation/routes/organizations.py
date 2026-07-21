"""Organization endpoints (PRD 3.1)."""
from flask import Blueprint

import config
import db
import response
import validators as v
from auth import authorize
from db import store
from services import domain

bp = Blueprint("organizations", __name__)


@bp.post("/api/organizations")
def create_organization():
    authorize([config.ROLE_PLATFORM_ADMIN])
    body = v.get_body()
    name = v.req_str(body, "name")
    ein = v.req_str(body, "ein")
    contact_email = v.req_str(body, "contact_email")
    rec = db.new_record(
        name=name,
        ein=ein,
        contact_email=contact_email,
        payout_account_status="UNVERIFIED",
    )
    store.organizations[rec["id"]] = rec
    return response.object_response(domain.ser_organization(rec), 201)


@bp.get("/api/organizations/<org_id>")
def read_organization(org_id):
    user_id, role = authorize(
        [
            config.ROLE_PLATFORM_ADMIN,
            config.ROLE_CAMPAIGN_MANAGER,
            config.ROLE_FINANCE_REVIEWER,
        ]
    )
    rec = domain.get_organization(org_id)
    if role == config.ROLE_CAMPAIGN_MANAGER:
        domain.require_manager_owns_organization(user_id, rec)
    return response.object_response(domain.ser_organization(rec))


@bp.post("/api/organizations/<org_id>/payout-account")
def set_payout_account(org_id):
    authorize([config.ROLE_PLATFORM_ADMIN])
    body = v.get_body()
    # PRD 3.1: UNVERIFIED is the initial value and cannot be re-selected.
    status = v.req_enum(body, "status", ["VERIFIED", "SUSPENDED"])
    rec = domain.get_organization(org_id)
    rec["payout_account_status"] = status
    db.touch(rec)
    return response.object_response(domain.ser_organization(rec))
