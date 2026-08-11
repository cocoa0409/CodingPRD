"""PermitApplication, AgencyEndorsement, and DispersalPlan endpoints."""
from flask import Blueprint, request

import db
from auth import guarded
from db import STORE, make_record, touch
from errors import api_err
from logic import (
    AGENCIES,
    compute_permit_final_fee,
    endorsement_or_404,
    parade_or_404,
    permit_of,
    permit_or_404,
    plan_of,
    plan_or_404,
    pull_assignment,
    ser_endorsement,
    ser_permit,
    ser_plan,
)
from util import body, paged, req_enum, req_int, req_num, req_str_list, opt_str, respond_object

bp = Blueprint("permits", __name__)

CA = ("CommitteeAdmin",)
AR = ("AgencyReviewer",)
CA_AR = ("CommitteeAdmin", "AgencyReviewer")


def add(rule, methods, view):
    bp.add_url_rule(rule, view_func=view, methods=methods, strict_slashes=False)


# --- PermitApplication -------------------------------------------------------

def create_permit(uid, role, id):
    parade = parade_or_404(id)
    body()  # no input fields; tolerate any/empty body
    if permit_of(id) is not None:
        raise api_err("ERR_PERMIT_ALREADY_EXISTS", "A PermitApplication already exists for the parade")
    rec = make_record()
    rec.update(
        {
            "parade_id": id,
            "status": "DRAFT",
            "provisional_fee_cents": 75000 + 5000 * 4,
            "final_fee_cents": None,
            "submitted_at": None,
            "required_agency_count": 4,
        }
    )
    STORE.permits[rec["id"]] = rec
    return respond_object(ser_permit(rec), 201)


def get_parade_permit(uid, role, id):
    parade_or_404(id)
    permit = permit_of(id)
    items = [permit] if permit is not None else []
    return paged(items, ser_permit)


def get_permit(uid, role, id):
    return respond_object(ser_permit(permit_or_404(id)))


def submit_permit(uid, role, id):
    permit = permit_or_404(id)
    if permit["status"] != "DRAFT":
        raise api_err("ERR_INVALID_STATE", "Permit must be in DRAFT to submit")
    parade = parade_or_404(permit["parade_id"])
    if parade["status"] != "PERMIT_PENDING":
        raise api_err("ERR_INVALID_STATE", "Parade must be in PERMIT_PENDING")
    for agency in AGENCIES:
        if not any(
            e["permit_id"] == id and e["agency_type"] == agency and e["status"] == "PENDING"
            for e in STORE.endorsements.values()
        ):
            raise api_err("ERR_INVALID_STATE", f"A PENDING endorsement is required for {agency}")
    permit["submitted_at"] = db.now()
    permit["final_fee_cents"] = compute_permit_final_fee(parade, permit["submitted_at"])
    permit["status"] = "AGENCY_REVIEW"
    touch(permit)
    return respond_object(ser_permit(permit))


def grant_permit(uid, role, id):
    permit = permit_or_404(id)
    if permit["status"] != "AGENCY_REVIEW":
        raise api_err("ERR_INVALID_STATE", "Permit must be in AGENCY_REVIEW to grant")
    for agency in AGENCIES:
        if not any(
            e["permit_id"] == id and e["agency_type"] == agency and e["status"] == "ENDORSED"
            for e in STORE.endorsements.values()
        ):
            raise api_err("ERR_INVALID_STATE", f"An ENDORSED endorsement is required for {agency}")
    permit["status"] = "GRANTED"
    touch(permit)
    parade = parade_or_404(permit["parade_id"])
    if parade["status"] == "PERMIT_PENDING":
        parade["status"] = "PERMIT_GRANTED"
        touch(parade)
    return respond_object(ser_permit(permit))


def deny_permit(uid, role, id):
    permit = permit_or_404(id)
    if permit["status"] != "AGENCY_REVIEW":
        raise api_err("ERR_INVALID_STATE", "Permit must be in AGENCY_REVIEW to deny")
    permit["status"] = "DENIED"
    touch(permit)
    return respond_object(ser_permit(permit))


def revoke_permit(uid, role, id):
    permit = permit_or_404(id)
    if permit["status"] != "GRANTED":
        raise api_err("ERR_INVALID_STATE", "Permit must be in GRANTED to revoke")
    permit["status"] = "REVOKED"
    touch(permit)
    # Freeze cascade: pull every CONFIRMED/CHECKED_IN lineup assignment of the
    # parade (slot release + ENTRY_INTRO cancellation per pull). TENTATIVE
    # assignments are left in place.
    for a in STORE.lineup_assignments.values():
        if a["parade_id"] == permit["parade_id"] and a["status"] in ("CONFIRMED", "CHECKED_IN"):
            pull_assignment(a)
    return respond_object(ser_permit(permit))


def refile_permit(uid, role, id):
    permit = permit_or_404(id)
    if permit["status"] != "DENIED":
        raise api_err("ERR_INVALID_STATE", "Permit must be in DENIED to refile")
    permit["status"] = "DRAFT"
    permit["final_fee_cents"] = None
    permit["submitted_at"] = None
    touch(permit)
    return respond_object(ser_permit(permit))


add("/parades/<id>/permit", ["POST"], guarded(CA)(create_permit))
add("/parades/<id>/permit", ["GET"], guarded(CA_AR)(get_parade_permit))
add("/permits/<id>", ["GET"], guarded(CA_AR)(get_permit))
add("/permits/<id>/submit", ["POST"], guarded(CA)(submit_permit))
add("/permits/<id>/grant", ["POST"], guarded(AR)(grant_permit))
add("/permits/<id>/deny", ["POST"], guarded(AR)(deny_permit))
add("/permits/<id>/revoke", ["POST"], guarded(AR)(revoke_permit))
add("/permits/<id>/refile", ["POST"], guarded(CA)(refile_permit))


# --- AgencyEndorsement -------------------------------------------------------

def create_endorsement(uid, role, id):
    permit = permit_or_404(id)
    data = body()
    agency_type = req_enum(data, "agency_type", AGENCIES)
    expected = req_int(data, "expected_permit_version")
    if expected != permit["version"]:
        raise api_err("ERR_STALE_VERSION", "expected_permit_version does not match the current version")
    if any(
        e["permit_id"] == id
        and e["agency_type"] == agency_type
        and e["status"] in ("PENDING", "ENDORSED")
        for e in STORE.endorsements.values()
    ):
        raise api_err(
            "ERR_DUPLICATE_AGENCY_ENDORSEMENT",
            "An endorsement with status PENDING or ENDORSED already exists for this agency",
        )
    rec = make_record()
    rec.update(
        {
            "permit_id": id,
            "agency_type": agency_type,
            "status": "PENDING",
            "decided_at": None,
        }
    )
    touch(permit)  # every endorsement creation advances the permit version
    rec["permit_version"] = permit["version"]
    STORE.endorsements[rec["id"]] = rec
    return respond_object(ser_endorsement(rec), 201)


def list_endorsements(uid, role, id):
    permit_or_404(id)
    items = [e for e in STORE.endorsements.values() if e["permit_id"] == id]
    status = request.args.get("status")
    if status is not None:
        items = [e for e in items if e["status"] == status]
    return paged(items, ser_endorsement)


def get_endorsement(uid, role, id):
    return respond_object(ser_endorsement(endorsement_or_404(id)))


def _decide_endorsement(id, target):
    endorsement = endorsement_or_404(id)
    if endorsement["status"] != "PENDING":
        raise api_err("ERR_INVALID_STATE", "Endorsement must be in PENDING")
    endorsement["status"] = target
    endorsement["decided_at"] = db.now()
    touch(endorsement)
    return respond_object(ser_endorsement(endorsement))


def endorse_endorsement(uid, role, id):
    return _decide_endorsement(id, "ENDORSED")


def reject_endorsement(uid, role, id):
    return _decide_endorsement(id, "REJECTED")


add("/permits/<id>/endorsements", ["POST"], guarded(CA)(create_endorsement))
add("/permits/<id>/endorsements", ["GET"], guarded(CA_AR)(list_endorsements))
add("/endorsements/<id>", ["GET"], guarded(CA_AR)(get_endorsement))
add("/endorsements/<id>/endorse", ["POST"], guarded(AR)(endorse_endorsement))
add("/endorsements/<id>/reject", ["POST"], guarded(AR)(reject_endorsement))


# --- DispersalPlan -----------------------------------------------------------

def create_plan(uid, role, id):
    parade_or_404(id)
    data = body()
    lane = req_num(data, "emergency_lane_width_m")
    corridors = req_str_list(data, "dispersal_corridors")
    notes = opt_str(data, "evacuation_notes")
    if plan_of(id) is not None:
        raise api_err("ERR_PLAN_ALREADY_EXISTS", "A DispersalPlan already exists for the parade")
    rec = make_record()
    rec.update(
        {
            "parade_id": id,
            "emergency_lane_width_m": lane,
            "dispersal_corridors": corridors,
            "evacuation_notes": notes,
            "status": "DRAFT",
        }
    )
    STORE.dispersal_plans[rec["id"]] = rec
    return respond_object(ser_plan(rec), 201)


def get_parade_plan(uid, role, id):
    parade_or_404(id)
    plan = plan_of(id)
    items = [plan] if plan is not None else []
    return paged(items, ser_plan)


def get_plan(uid, role, id):
    return respond_object(ser_plan(plan_or_404(id)))


def submit_plan(uid, role, id):
    plan = plan_or_404(id)
    if plan["status"] != "DRAFT":
        raise api_err("ERR_INVALID_STATE", "Dispersal plan must be in DRAFT to submit")
    if not plan["emergency_lane_width_m"] >= 3.0:
        raise api_err("ERR_EMERGENCY_LANE_TOO_NARROW", "emergency_lane_width_m must be >= 3.0")
    if len(plan["dispersal_corridors"]) == 0:
        raise api_err("ERR_VALIDATION", "dispersal_corridors must be non-empty at submit")
    plan["status"] = "SUBMITTED"
    touch(plan)
    return respond_object(ser_plan(plan))


def approve_plan(uid, role, id):
    plan = plan_or_404(id)
    if plan["status"] != "SUBMITTED":
        raise api_err("ERR_INVALID_STATE", "Dispersal plan must be in SUBMITTED to approve")
    plan["status"] = "APPROVED"
    touch(plan)
    return respond_object(ser_plan(plan))


def reject_plan(uid, role, id):
    plan = plan_or_404(id)
    if plan["status"] != "SUBMITTED":
        raise api_err("ERR_INVALID_STATE", "Dispersal plan must be in SUBMITTED to reject")
    plan["status"] = "REJECTED"
    touch(plan)
    return respond_object(ser_plan(plan))


def revise_plan(uid, role, id):
    plan = plan_or_404(id)
    if plan["status"] != "REJECTED":
        raise api_err("ERR_INVALID_STATE", "Dispersal plan must be in REJECTED to revise")
    plan["status"] = "DRAFT"
    touch(plan)
    return respond_object(ser_plan(plan))


add("/parades/<id>/dispersal-plan", ["POST"], guarded(CA)(create_plan))
add("/parades/<id>/dispersal-plan", ["GET"], guarded(CA_AR)(get_parade_plan))
add("/dispersal-plans/<id>", ["GET"], guarded(CA_AR)(get_plan))
add("/dispersal-plans/<id>/submit", ["POST"], guarded(CA)(submit_plan))
add("/dispersal-plans/<id>/approve", ["POST"], guarded(AR)(approve_plan))
add("/dispersal-plans/<id>/reject", ["POST"], guarded(AR)(reject_plan))
add("/dispersal-plans/<id>/revise", ["POST"], guarded(CA)(revise_plan))
