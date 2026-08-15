"""Monthly agreement endpoints (PRD 3.4)."""
from flask import Blueprint, request

import db
from errors import (
    err_invalid_state, err_posture_blocks, err_monthly_pool, err_stale_agreement,
    err_credentials_outstanding, err_not_owner,
)
from middleware import get_actor, require_roles, ALL_ROLES
from response import success_object, success_list
from services.common import (
    body, require_int, optional_int, require_enum, parse_pagination, paginate,
    require_ref, get_agreement, public_view,
)
from services.fees import compute_first_invoice, pool_counts

bp = Blueprint("agreements", __name__)

TIERS = {"STANDARD", "PREMIUM", "EV"}


def _next_application_seq(facility_id):
    seqs = [a["application_seq"] for a in db.monthly_agreements.values()
            if a["facility_id"] == facility_id]
    return (max(seqs) if seqs else 0) + 1


def _check_posture_allows_agreement(facility):
    if facility["posture"] in ("CLOSED_TEMPORARY", "DECOMMISSIONED"):
        raise err_posture_blocks()


@bp.post("/ops/monthly-agreements")
def create_agreement():
    actor = get_actor()
    require_roles(actor, ["FacilityManager", "ParkingAttendant"])
    payload = body()
    facility = require_ref(payload, db.facilities, "facility_id")
    parker = require_ref(payload, db.parker_accounts, "parker_account_id")
    parker_id = parker["id"]
    tier = require_enum(payload, "tier", TIERS)
    rate = require_int(payload, "monthly_rate_cents", minimum=0, exclusive_min=True)
    ev_surcharge = optional_int(payload, "ev_surcharge_cents", default=0, minimum=0)
    _check_posture_allows_agreement(facility)
    allocated, _approved = pool_counts(facility["id"])
    status = "APPROVED" if allocated < facility["monthly_capacity"] else "WAITLISTED"
    ent = {
        "id": db.new_id(),
        "facility_id": facility["id"],
        "parker_account_id": parker_id,
        "tier": tier,
        "monthly_rate_cents": rate,
        "ev_surcharge_cents": ev_surcharge,
        "agreement_status": status,
        "application_seq": _next_application_seq(facility["id"]),
        "activated_at": None,
        "first_invoice_cents": None,
    }
    db.stamp_new(ent)
    db.monthly_agreements[ent["id"]] = ent
    return success_object(public_view(ent), status=201)


@bp.get("/ops/monthly-agreements/<monthly_agreement_id>")
def get_agreement_route(monthly_agreement_id):
    actor = get_actor()
    require_roles(actor, ALL_ROLES)
    return success_object(public_view(get_agreement(monthly_agreement_id)))


@bp.get("/ops/monthly-agreements")
def list_agreements():
    actor = get_actor()
    require_roles(actor, ALL_ROLES)
    limit, offset = parse_pagination()
    items = list(db.monthly_agreements.values())
    facility_id = request.args.get("facility_id")
    parker_account_id = request.args.get("parker_account_id")
    agreement_status = request.args.get("agreement_status")
    if facility_id is not None:
        items = [a for a in items if a["facility_id"] == facility_id]
    if parker_account_id is not None:
        items = [a for a in items if a["parker_account_id"] == parker_account_id]
    if agreement_status is not None:
        items = [a for a in items if a["agreement_status"] == agreement_status]
    page, total = paginate(items, limit, offset)
    return success_list([public_view(a) for a in page], limit, offset, total)


@bp.post("/ops/monthly-agreements/<monthly_agreement_id>/activate")
def activate_agreement(monthly_agreement_id):
    actor = get_actor()
    require_roles(actor, ["ParkingAttendant", "FacilityManager"])
    ag = get_agreement(monthly_agreement_id)
    if ag["agreement_status"] != "APPROVED":
        raise err_invalid_state("only an APPROVED agreement may be activated")
    facility = db.facilities[ag["facility_id"]]
    _check_posture_allows_agreement(facility)
    allocated, _approved = pool_counts(facility["id"])
    if allocated >= facility["monthly_capacity"]:
        raise err_monthly_pool()
    now = db.now_dt()
    ag["agreement_status"] = "ACTIVE"
    ag["activated_at"] = db.now_iso()
    ag["first_invoice_cents"] = compute_first_invoice(ag, now)
    db.touch(ag)
    return success_object(public_view(ag))


@bp.post("/ops/monthly-agreements/<monthly_agreement_id>/suspend")
def suspend_agreement(monthly_agreement_id):
    actor = get_actor()
    require_roles(actor, ["FacilityManager"])
    ag = get_agreement(monthly_agreement_id)
    if ag["agreement_status"] != "ACTIVE":
        raise err_invalid_state("only an ACTIVE agreement may be suspended")
    ag["agreement_status"] = "SUSPENDED"
    db.touch(ag)
    return success_object(public_view(ag))


@bp.post("/ops/monthly-agreements/<monthly_agreement_id>/resume")
def resume_agreement(monthly_agreement_id):
    actor = get_actor()
    require_roles(actor, ["FacilityManager"])
    ag = get_agreement(monthly_agreement_id)
    if ag["agreement_status"] != "SUSPENDED":
        raise err_invalid_state("only a SUSPENDED agreement may be resumed")
    ag["agreement_status"] = "ACTIVE"
    db.touch(ag)
    return success_object(public_view(ag))


@bp.post("/ops/monthly-agreements/<monthly_agreement_id>/terminate")
def terminate_agreement(monthly_agreement_id):
    actor = get_actor()
    require_roles(actor, ["FacilityManager", "ParkingAttendant"])
    ag = get_agreement(monthly_agreement_id)
    if ag["agreement_status"] not in ("APPROVED", "ACTIVE", "SUSPENDED"):
        raise err_invalid_state("only APPROVED/ACTIVE/SUSPENDED agreements may be terminated")
    for cred in db.credentials.values():
        if (cred["agreement_id"] == ag["id"]
                and cred["credential_status"] in ("ACTIVE", "LOST_REPORTED")):
            raise err_credentials_outstanding()
    ag["agreement_status"] = "TERMINATED"
    db.touch(ag)
    return success_object(public_view(ag))


@bp.post("/ops/monthly-agreements/<monthly_agreement_id>/amend")
def amend_agreement(monthly_agreement_id):
    actor = get_actor()
    require_roles(actor, ["FacilityManager"])
    ag = get_agreement(monthly_agreement_id)
    payload = body()
    expected = require_int(payload, "expected_agreement_version")
    rate = optional_int(payload, "monthly_rate_cents", minimum=0, exclusive_min=True)
    surcharge = optional_int(payload, "ev_surcharge_cents", minimum=0)
    # OCC (pipeline stage 8)
    if expected != ag["version"]:
        raise err_stale_agreement()
    if rate is not None:
        ag["monthly_rate_cents"] = rate
    if surcharge is not None:
        ag["ev_surcharge_cents"] = surcharge
    db.touch(ag)
    return success_object(public_view(ag))


@bp.post("/ops/monthly-agreements/<monthly_agreement_id>/withdraw")
def withdraw_agreement(monthly_agreement_id):
    actor = get_actor()
    require_roles(actor, ["FacilityManager", "ParkingAttendant", "MonthlyParker"])
    ag = get_agreement(monthly_agreement_id)
    if actor.role == "MonthlyParker" and actor.user_id != ag["parker_account_id"]:
        raise err_not_owner("a parker may withdraw only their own agreement")
    if ag["agreement_status"] != "WAITLISTED":
        raise err_invalid_state("only a WAITLISTED agreement may be withdrawn")
    ag["agreement_status"] = "WITHDRAWN"
    db.touch(ag)
    return success_object(public_view(ag))
