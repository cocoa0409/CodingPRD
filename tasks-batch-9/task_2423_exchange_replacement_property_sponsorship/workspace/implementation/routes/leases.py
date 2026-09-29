"""Master lease endpoints (PRD 3.3)."""
from flask import Blueprint

import clock
import constants as C
import db
import middleware
from errors import ApiError, bad_request
from response import created_response, object_response
from routes._common import listing, read_one
from services import domain
from util import as_date

bp = Blueprint("leases", __name__)

NEW_LEASE_PROHIBITED_STATUSES = ("OPERATING", "WINDING_DOWN", "TERMINATED",
                                 "CONVERTED_LLC")


@bp.post("/master-leases")
def create_lease():
    middleware.actor([C.TRUSTEE])
    payload = middleware.body_or_400()
    trust_id = middleware.req_str(payload, "trust_id")
    master_tenant_user_id = middleware.req_str(payload, "master_tenant_user_id")
    term_start_on = middleware.req_dt(payload, "term_start_on")
    term_end_on = middleware.req_dt(payload, "term_end_on")
    base_rent_annual_cents = middleware.req_int(payload, "base_rent_annual_cents", 0)
    supplemental_rent_annual_cents = middleware.req_int(
        payload, "supplemental_rent_annual_cents", 0)
    if as_date(term_start_on) > as_date(term_end_on):
        raise bad_request("Field 'term_start_on' must be at or before 'term_end_on'.")

    trust = domain.require("trust", trust_id)
    domain.check_frozen(trust)
    if trust["status"] in NEW_LEASE_PROHIBITED_STATUSES:
        raise ApiError("ERR_NEW_LEASE_PROHIBITED")

    # rung 45 — closed-interval overlap against every trust holding this property
    sibling_trust_ids = {t["id"] for t in db.sorted_rows(db.trusts)
                         if t["property_id"] == trust["property_id"]}
    start = as_date(term_start_on)
    end = as_date(term_end_on)
    for other in db.sorted_rows(db.leases):
        if other["trust_id"] not in sibling_trust_ids:
            continue
        if other["status"] not in ("DRAFT", "EXECUTED"):
            continue
        if as_date(other["term_start_on"]) <= end and start <= as_date(other["term_end_on"]):
            raise ApiError("ERR_LEASE_TERM_OVERLAP")

    row = db.new_row(db.leases, {
        "trust_id": trust["id"],
        "master_tenant_user_id": master_tenant_user_id,
        "term_start_on": term_start_on,
        "term_end_on": term_end_on,
        "base_rent_annual_cents": base_rent_annual_cents,
        "supplemental_rent_annual_cents": supplemental_rent_annual_cents,
        "executed_at": None,
        "status": "DRAFT",
    })
    return created_response(db.serialize(row))


@bp.get("/master-leases/<lease_id>")
def get_lease(lease_id):
    return read_one("lease", C.READ_TENANT_SIDE, lease_id)


@bp.get("/master-leases")
def list_leases():
    return listing(db.leases, C.READ_TENANT_SIDE,
                   str_filters=("trust_id", "status", "master_tenant_user_id"))


@bp.post("/master-leases/<lease_id>/execute")
def execute_lease(lease_id):
    middleware.actor([C.TRUSTEE])
    lease = domain.require("lease", lease_id)
    trust = db.trusts[lease["trust_id"]]

    domain.check_frozen(trust)
    domain.check_trust_status(trust, ("FORMING", "FUNDING"))
    if lease["status"] != "DRAFT":
        raise ApiError("ERR_MASTER_LEASE_INVALID_STATE")

    lease["status"] = "EXECUTED"
    lease["executed_at"] = clock.now()
    db.touch(lease)
    return object_response(db.serialize(lease))


@bp.post("/master-leases/<lease_id>/terminate")
def terminate_lease(lease_id):
    middleware.actor([C.TRUSTEE])
    payload = middleware.body_or_400()
    middleware.opt_str(payload, "reason")

    lease = domain.require("lease", lease_id)
    trust = db.trusts[lease["trust_id"]]
    domain.check_frozen(trust)
    if lease["status"] != "EXECUTED":
        raise ApiError("ERR_MASTER_LEASE_INVALID_STATE")

    lease["status"] = "TERMINATED"
    db.touch(lease)
    return object_response(db.serialize(lease))
