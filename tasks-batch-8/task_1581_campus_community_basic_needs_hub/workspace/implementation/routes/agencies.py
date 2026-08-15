"""Partner agencies and warm-handoff referrals (PRD 3.7)."""
from datetime import timedelta

from flask import Blueprint, request

from db import db
from errors import (
    raise_error, ERR_INVALID_REQUEST, ERR_DUPLICATE_AGENCY, ERR_INVALID_STATE,
    ERR_CAPACITY_BELOW_ACTIVE, ERR_CLIENT_NOT_ACTIVE, ERR_AGENCY_NOT_ACTIVE,
    ERR_AGENCY_CAPACITY_FULL, ERR_CATEGORY_NOT_SERVED, ERR_WALK_INS_NOT_ACCEPTED,
    ERR_REFERRAL_NOT_ACTIONABLE,
)
from middleware import (
    authenticate, authorize, check_client_scope, check_agency_scope,
)
from response import success_object
from routes.helpers import list_response
from services import calculations as calc
from services.core import (
    new_record, touch, public, verified_assessment, recompute_agency,
)
from util import CLOCK
from validate import (
    get_body, req_int, opt_int, req_str, opt_str, req_enum, opt_bool, opt_enum_list,
    req_date, require_path_resource, require_body_ref,
)

bp = Blueprint("agencies", __name__)

SERVICE_CATEGORIES = ["SNAP_APPLICATION", "CHILDCARE_SUBSIDY", "HOUSING_PLACEMENT",
                      "LEGAL_AID", "MENTAL_HEALTH"]
AGENCY_READ_ROLES = ["Client", "IntakeCoordinator", "PantryStaff", "BenefitsCounselor",
                     "ShelterCoordinator", "HubAdmin", "PartnerAgencyRep"]
REFERRAL_HUB_ROLES = ["IntakeCoordinator", "BenefitsCounselor", "ShelterCoordinator"]
REFERRAL_READ_ROLES = REFERRAL_HUB_ROLES + ["Client", "HubAdmin", "PartnerAgencyRep"]


# ---------------------------------------------------------------------------
# Agencies
# ---------------------------------------------------------------------------

@bp.post("/partner-agencies")
def create_agency():
    caller = authenticate()
    authorize(caller, ["HubAdmin"])
    body = get_body()
    agency_name = req_str(body, "agency_name")
    service_categories = opt_enum_list(body, "service_categories", SERVICE_CATEGORIES,
                                       default=None, non_empty=True)
    if service_categories is None:
        raise_error(ERR_INVALID_REQUEST, "service_categories is required and must be non-empty")
    weekly_capacity = req_int(body, "weekly_capacity", minimum=1)
    accepts_walk_ins = opt_bool(body, "accepts_walk_ins", False)
    for a in db["partner_agencies"].values():
        if a["agency_name"] == agency_name:
            raise_error(ERR_DUPLICATE_AGENCY, "agency_name already registered")
    rec = new_record("partner_agencies", {
        "agency_name": agency_name,
        "service_categories": service_categories,
        "weekly_capacity": weekly_capacity,
        "accepts_walk_ins": accepts_walk_ins,
        "active_referral_count": 0,
        "status": "ACTIVE",
    })
    return success_object(public(rec), status=201)


@bp.get("/partner-agencies")
def list_agencies():
    caller = authenticate()
    authorize(caller, AGENCY_READ_ROLES)
    filters = {
        "status": request.args.get("status"),
        "service_category": request.args.get("service_category"),
    }
    return list_response("partner_agencies", filters,
                         membership_filter_field="service_category")


@bp.patch("/partner-agencies/<aid>")
def patch_agency(aid):
    caller = authenticate()
    authorize(caller, ["HubAdmin"])
    agency = require_path_resource("partner_agencies", aid, "partner agency")
    body = get_body()
    if "weekly_capacity" in body and body["weekly_capacity"] is not None:
        new_cap = req_int(body, "weekly_capacity", minimum=1)
        if new_cap < agency["active_referral_count"]:
            raise_error(ERR_CAPACITY_BELOW_ACTIVE,
                        "weekly_capacity may not be set below active_referral_count")
        agency["weekly_capacity"] = new_cap
    if "service_categories" in body and body["service_categories"] is not None:
        agency["service_categories"] = opt_enum_list(
            body, "service_categories", SERVICE_CATEGORIES, non_empty=True)
    if "accepts_walk_ins" in body and body["accepts_walk_ins"] is not None:
        agency["accepts_walk_ins"] = opt_bool(body, "accepts_walk_ins")
    touch(agency)
    return success_object(public(agency))


@bp.post("/partner-agencies/<aid>/pause")
def pause_agency(aid):
    caller = authenticate()
    authorize(caller, ["HubAdmin"])
    agency = require_path_resource("partner_agencies", aid, "partner agency")
    if agency["status"] != "ACTIVE":
        raise_error(ERR_INVALID_STATE, "only an ACTIVE agency can be paused")
    agency["status"] = "PAUSED"
    touch(agency)
    return success_object(public(agency))


@bp.post("/partner-agencies/<aid>/resume")
def resume_agency(aid):
    caller = authenticate()
    authorize(caller, ["HubAdmin"])
    agency = require_path_resource("partner_agencies", aid, "partner agency")
    if agency["status"] != "PAUSED":
        raise_error(ERR_INVALID_STATE, "only a PAUSED agency can be resumed")
    agency["status"] = "ACTIVE"
    touch(agency)
    return success_object(public(agency))


# ---------------------------------------------------------------------------
# Referrals
# ---------------------------------------------------------------------------

@bp.post("/clients/<cid>/referrals")
def create_referral(cid):
    caller = authenticate()
    authorize(caller, REFERRAL_HUB_ROLES)
    client = require_path_resource("clients", cid, "client")
    body = get_body()
    agency_id = req_str(body, "agency_id")
    service_category = req_enum(body, "service_category", SERVICE_CATEGORIES)
    warm_handoff = opt_bool(body, "warm_handoff", False)
    notes = opt_str(body, "notes")
    if client["status"] != "ACTIVE":
        raise_error(ERR_CLIENT_NOT_ACTIVE, "referral creation requires an ACTIVE client")
    agency = require_body_ref("partner_agencies", agency_id, "agency_id")
    if service_category not in (agency["service_categories"] or []):
        raise_error(ERR_CATEGORY_NOT_SERVED, "service_category not in the agency's catalog")
    if warm_handoff and not agency["accepts_walk_ins"]:
        raise_error(ERR_WALK_INS_NOT_ACCEPTED, "agency does not accept walk-ins")
    # Capacity pre-checked at initiation (an INITIATED referral occupies no capacity)
    va = verified_assessment(client["id"])
    risk_tier = calc.compute_risk_tier(va)
    if not calc.referral_admits(agency, risk_tier):
        raise_error(ERR_AGENCY_CAPACITY_FULL, "agency is at capacity for this risk tier")
    rec = new_record("referrals", {
        "client_id": client["id"],
        "agency_id": agency["id"],
        "service_category": service_category,
        "warm_handoff": warm_handoff,
        "notes": notes,
        "status": "INITIATED",
        "sent_at": None,
        "ack_due_at": None,
        "decline_reason": None,
    })
    return success_object(public(rec), status=201)


@bp.get("/referrals")
def list_referrals():
    caller = authenticate()
    authorize(caller, REFERRAL_READ_ROLES)
    filters = {
        "client_id": request.args.get("client_id"),
        "agency_id": request.args.get("agency_id"),
        "status": request.args.get("status"),
    }

    def scope(rec):
        if caller.role == "Client":
            return rec["client_id"] == caller.user_id
        if caller.role == "PartnerAgencyRep":
            return rec["agency_id"] == caller.user_id
        return True

    return list_response("referrals", filters, scope_fn=scope)


@bp.get("/referrals/<rid>")
def get_referral(rid):
    caller = authenticate()
    authorize(caller, REFERRAL_READ_ROLES)
    referral = require_path_resource("referrals", rid, "referral")
    check_client_scope(caller, referral["client_id"])
    check_agency_scope(caller, referral["agency_id"])
    return success_object(public(referral))


def _send_referral(referral, agency):
    now = CLOCK.now()
    referral["sent_at"] = CLOCK.now_iso()
    referral["ack_due_at"] = _fmt(now + timedelta(hours=120))
    referral["status"] = "SENT"
    touch(referral)
    recompute_agency(agency)


def _fmt(dt):
    from util import fmt_ts
    return fmt_ts(dt)


@bp.post("/referrals/<rid>/send")
def send_referral(rid):
    caller = authenticate()
    authorize(caller, REFERRAL_HUB_ROLES)
    referral = require_path_resource("referrals", rid, "referral")
    if referral["status"] != "INITIATED":
        raise_error(ERR_REFERRAL_NOT_ACTIONABLE, "only an INITIATED referral can be sent")
    agency = db["partner_agencies"].get(referral["agency_id"])
    if agency is None or agency["status"] != "ACTIVE":
        raise_error(ERR_AGENCY_NOT_ACTIVE, "agency is not ACTIVE")
    _send_referral(referral, agency)
    return success_object(public(referral))


@bp.post("/referrals/<rid>/resend")
def resend_referral(rid):
    caller = authenticate()
    authorize(caller, REFERRAL_HUB_ROLES)
    referral = require_path_resource("referrals", rid, "referral")
    if referral["status"] != "EXPIRED":
        raise_error(ERR_REFERRAL_NOT_ACTIONABLE, "only an EXPIRED referral can be resent")
    agency = db["partner_agencies"].get(referral["agency_id"])
    if agency is None or agency["status"] != "ACTIVE":
        raise_error(ERR_AGENCY_NOT_ACTIVE, "agency is not ACTIVE")
    # Capacity re-checked against the client's CURRENT risk tier
    va = verified_assessment(referral["client_id"])
    risk_tier = calc.compute_risk_tier(va)
    if not calc.referral_admits(agency, risk_tier):
        raise_error(ERR_AGENCY_CAPACITY_FULL, "agency is at capacity for this risk tier")
    _send_referral(referral, agency)
    return success_object(public(referral))


@bp.post("/referrals/<rid>/acknowledge")
def acknowledge_referral(rid):
    caller = authenticate()
    authorize(caller, ["PartnerAgencyRep"])
    referral = require_path_resource("referrals", rid, "referral")
    check_agency_scope(caller, referral["agency_id"])
    if referral["status"] != "SENT":
        raise_error(ERR_REFERRAL_NOT_ACTIONABLE, "only a SENT referral can be acknowledged")
    referral["status"] = "ACKNOWLEDGED"
    touch(referral)
    return success_object(public(referral))


@bp.post("/referrals/<rid>/book-appointment")
def book_appointment(rid):
    caller = authenticate()
    authorize(caller, ["PartnerAgencyRep"])
    referral = require_path_resource("referrals", rid, "referral")
    check_agency_scope(caller, referral["agency_id"])
    if referral["status"] != "ACKNOWLEDGED":
        raise_error(ERR_REFERRAL_NOT_ACTIONABLE, "only an ACKNOWLEDGED referral can be booked")
    body = get_body()
    appointment_date = req_date(body, "appointment_date")
    from util import parse_date as _pdate
    if _pdate(appointment_date) < CLOCK.today():
        raise_error(ERR_INVALID_REQUEST, "appointment_date may not be before today")
    referral["status"] = "APPOINTMENT_BOOKED"
    touch(referral)
    return success_object(public(referral))


@bp.post("/referrals/<rid>/record-service")
def record_service(rid):
    caller = authenticate()
    authorize(caller, ["PartnerAgencyRep"])
    referral = require_path_resource("referrals", rid, "referral")
    check_agency_scope(caller, referral["agency_id"])
    if referral["status"] != "APPOINTMENT_BOOKED":
        raise_error(ERR_REFERRAL_NOT_ACTIONABLE, "only an APPOINTMENT_BOOKED referral can record service")
    referral["status"] = "SERVICE_RECEIVED"
    touch(referral)
    agency = db["partner_agencies"].get(referral["agency_id"])
    if agency is not None:
        recompute_agency(agency)
    return success_object(public(referral))


@bp.post("/referrals/<rid>/decline")
def decline_referral(rid):
    caller = authenticate()
    authorize(caller, ["PartnerAgencyRep"])
    referral = require_path_resource("referrals", rid, "referral")
    check_agency_scope(caller, referral["agency_id"])
    if referral["status"] not in ("SENT", "ACKNOWLEDGED"):
        raise_error(ERR_REFERRAL_NOT_ACTIONABLE, "only a SENT or ACKNOWLEDGED referral can be declined")
    body = get_body()
    reason = req_str(body, "decline_reason")
    referral["decline_reason"] = reason
    referral["status"] = "DECLINED"
    touch(referral)
    agency = db["partner_agencies"].get(referral["agency_id"])
    if agency is not None:
        recompute_agency(agency)
    return success_object(public(referral))


@bp.post("/referrals/<rid>/withdraw")
def withdraw_referral(rid):
    caller = authenticate()
    authorize(caller, REFERRAL_HUB_ROLES)
    referral = require_path_resource("referrals", rid, "referral")
    if referral["status"] not in ("INITIATED", "SENT"):
        raise_error(ERR_REFERRAL_NOT_ACTIONABLE, "only an INITIATED or SENT referral can be withdrawn")
    was_sent = referral["status"] == "SENT"
    referral["status"] = "WITHDRAWN"
    touch(referral)
    if was_sent:
        agency = db["partner_agencies"].get(referral["agency_id"])
        if agency is not None:
            recompute_agency(agency)
    return success_object(public(referral))
