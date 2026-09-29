"""Authentication, RBAC and ownership helpers (PRD §2.1, §2.5, §2.10)."""

from flask import g, request

from db import db
from errors import ApiError

ROLES = (
    "ProgramAdministrator",
    "ProgramAuditor",
    "Registrant",
    "CollectionSiteOperator",
    "Hauler",
    "Recycler",
)

ADMIN = "ProgramAdministrator"
AUDITOR = "ProgramAuditor"
REGISTRANT = "Registrant"
SITE_OPERATOR = "CollectionSiteOperator"
HAULER = "Hauler"
RECYCLER = "Recycler"

ALL_ROLES = list(ROLES)


def auth(allowed_roles):
    """Step 1 (401) and step 2 (403) of the rejection ladder."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED",
                       "X-User-ID and a recognised X-User-Role header are required.")
    if role not in allowed_roles:
        raise ApiError("ERR_UNAUTHORIZED",
                       "Role %s may not perform this operation." % role)
    g.user_id = user_id
    g.role = role
    return user_id, role


def forbid_resource():
    raise ApiError("ERR_FORBIDDEN_RESOURCE",
                   "Acting principal does not own the target resource.")


def own(expected_owner_id):
    """Step 6: entity-backed ownership comparison."""
    if g.user_id != expected_owner_id:
        forbid_resource()


# --------------------------------------------------------------------------
# Reference resolution (step 5) — per-entity 404 codes
# --------------------------------------------------------------------------


def _lookup(collection, identifier, error_id):
    if not isinstance(identifier, str):
        raise ApiError(error_id)
    rec = collection.get(identifier)
    if rec is None:
        raise ApiError(error_id)
    return rec


def get_program(pid):
    return _lookup(db.state_programs, pid, "ERR_STATE_PROGRAM_NOT_FOUND")


def get_schedule(sid):
    return _lookup(db.fee_rate_schedules, sid, "ERR_RATE_SCHEDULE_NOT_FOUND")


def get_registrant(rid):
    return _lookup(db.registrants, rid, "ERR_REGISTRANT_NOT_FOUND")


def get_remittance(rid):
    return _lookup(db.sales_remittances, rid, "ERR_REMITTANCE_NOT_FOUND")


def get_claim(cid):
    return _lookup(db.exemption_claims, cid, "ERR_EXEMPTION_CLAIM_NOT_FOUND")


def get_site(sid):
    return _lookup(db.collection_sites, sid, "ERR_COLLECTION_SITE_NOT_FOUND")


def get_volume_report(vid):
    return _lookup(db.volume_reports, vid, "ERR_VOLUME_REPORT_NOT_FOUND")


def get_hauler(hid):
    return _lookup(db.haulers, hid, "ERR_HAULER_NOT_FOUND")


def get_recycler(rid):
    return _lookup(db.recyclers, rid, "ERR_RECYCLER_NOT_FOUND")


def get_order(oid):
    return _lookup(db.pickup_orders, oid, "ERR_PICKUP_ORDER_NOT_FOUND")


def get_commodity_record(cid):
    return _lookup(db.commodity_output_records, cid, "ERR_COMMODITY_RECORD_NOT_FOUND")


def get_delivery(did):
    return _lookup(db.take_back_deliveries, did, "ERR_TAKE_BACK_DELIVERY_NOT_FOUND")
