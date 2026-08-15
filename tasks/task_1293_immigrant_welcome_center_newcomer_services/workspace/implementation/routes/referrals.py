"""Referrals (warm handoff pipeline) and appointments."""
from flask import Blueprint, request

import db
import services
from auth import require, get_or_404
from envelope import ok, ok_list, paginate
from errors import ApiError, bad_request, forbidden, invalid_state
from util import (body_json, req_str, opt_str, opt_int, req_enum,
                  req_present, req_datetime)

bp = Blueprint("referrals", __name__)

REFERRAL_CATEGORIES = {"HOUSING", "EMPLOYMENT", "EDUCATION", "LEGAL",
                       "HEALTH"}
APPOINTMENT_KINDS = {"DOCUMENT_ID", "ACCOMPANIMENT", "ORIENTATION",
                     "BENEFITS"}


# ---------------------------------------------------------------------------
# Referrals
# ---------------------------------------------------------------------------

@bp.route("/referrals", methods=["POST"])
def create_referral():
    require("CaseManager", "CenterAdmin")
    data = body_json()

    # rung 3: body ids in fixed order: organization_id before case_id
    org_id = data.get("organization_id")
    case_id = data.get("case_id")
    org = case = None
    if org_id is not None:
        if not isinstance(org_id, str):
            raise bad_request("organization_id must be a string")
        org = get_or_404("organizations", org_id, "organization")
    if case_id is not None:
        if not isinstance(case_id, str):
            raise bad_request("case_id must be a string")
        case = get_or_404("cases", case_id, "case")

    # rung 4: SUSPENDED/CLOSED cases reject referral creation
    if case is not None and case["service_status"] in ("SUSPENDED", "CLOSED"):
        raise invalid_state("case is not accepting new referrals")

    # rung 7: structural
    req_present(data, "case_id")
    req_present(data, "organization_id")
    category = req_enum(data, "service_category", REFERRAL_CATEGORIES)
    notes = opt_str(data, "notes", None)
    ttl_days = opt_int(data, "ttl_days", 14, minimum=1)
    if category not in org["service_categories"]:
        raise bad_request("service_category not offered by the organization")

    ref = db.new_entity("referrals", {
        "case_id": case_id,
        "organization_id": org_id,
        "service_category": category,
        "notes": notes,
        "status": "DRAFT",
        "sent_at": None,
        "responded_at": None,
        "warm_handoff_offered": False,
        "handoff_confirmed_at": None,
        "completed_at": None,
        "ttl_days": ttl_days,
        "suspension_reason": None,
    })
    return ok(db.pub(ref), status=201)


@bp.route("/referrals/<referral_id>", methods=["GET"])
def get_referral(referral_id):
    user_id, role = require("CenterAdmin", "CaseManager", "IntakeSpecialist",
                            "PartnerOrg")
    ref = get_or_404("referrals", referral_id, "referral")
    if role == "PartnerOrg" and ref["organization_id"] != user_id:
        raise forbidden("partners may read only their own referrals")
    return ok(db.pub(ref))


@bp.route("/referrals", methods=["GET"])
def list_referrals():
    user_id, role = require("CenterAdmin", "CaseManager", "IntakeSpecialist",
                            "PartnerOrg")
    items = db.all_of("referrals")
    if role == "PartnerOrg":
        items = [r for r in items if r["organization_id"] == user_id]
    for param in ("case_id", "organization_id", "status"):
        v = request.args.get(param)
        if v is not None:
            items = [r for r in items if str(r.get(param)) == v]
    page, meta = paginate(items)
    return ok_list([db.pub(r) for r in page], meta)


def _send_gates(ref, case, org, check_case_status=True):
    """Shared send/reroute/resume gates in the PRD-pinned surfacing order."""
    # privacy posture
    if case["privacy_posture"] != "STANDARD":
        raise ApiError("ERR_PRIVACY_SEALED", 409,
                       "case privacy posture blocks sending")
    # consent
    if not services.has_granted_consent(case["client_id"], "REFERRAL_SHARE"):
        raise ApiError("ERR_CONSENT_MISSING", 409,
                       "client holds no GRANTED REFERRAL_SHARE consent")
    # org status
    if org["status"] != "ACTIVE":
        raise ApiError("ERR_ORG_SUSPENDED", 409,
                       "organization is SUSPENDED")
    # org capacity
    if org["referral_slots_used"] >= org["referral_capacity"]:
        raise ApiError("ERR_ORG_CAPACITY_FULL", 409,
                       "organization has no open referral slots")
    # case status
    if check_case_status and case["service_status"] in ("SUSPENDED",
                                                        "CLOSED"):
        raise invalid_state("case is SUSPENDED or CLOSED")


@bp.route("/referrals/<referral_id>/send", methods=["POST"])
def send_referral(referral_id):
    require("CaseManager")
    ref = get_or_404("referrals", referral_id, "referral")
    if ref["status"] != "DRAFT":
        raise invalid_state("referral is not DRAFT")
    case = db.get("cases", ref["case_id"])
    org = db.get("organizations", ref["organization_id"])
    _send_gates(ref, case, org, check_case_status=True)
    ref["status"] = "SENT"
    ref["sent_at"] = db.now()
    db.touch(ref)
    services.org_slot_delta(org, +1)
    return ok(db.pub(ref))


@bp.route("/referrals/<referral_id>/respond", methods=["POST"])
def respond_referral(referral_id):
    user_id, _ = require("PartnerOrg")
    ref = get_or_404("referrals", referral_id, "referral")
    if ref["organization_id"] != user_id:
        raise forbidden("referral belongs to another organization")
    if ref["status"] != "SENT":
        raise invalid_state("referral is not SENT")
    data = body_json()
    decision = req_enum(data, "decision", {"ACCEPTED", "DECLINED"})
    warm = data.get("warm_handoff_offered", False)
    if not isinstance(warm, bool):
        raise bad_request("warm_handoff_offered must be a boolean")
    ref["responded_at"] = db.now()
    if decision == "ACCEPTED":
        ref["status"] = "ACCEPTED"
        ref["warm_handoff_offered"] = warm
    else:
        ref["status"] = "DECLINED"
        org = db.get("organizations", ref["organization_id"])
        if org is not None:
            services.org_slot_delta(org, -1)
    db.touch(ref)
    return ok(db.pub(ref))


@bp.route("/referrals/<referral_id>/confirm-handoff", methods=["POST"])
def confirm_handoff(referral_id):
    require("CaseManager", "CenterAdmin")
    ref = get_or_404("referrals", referral_id, "referral")
    if ref["status"] != "ACCEPTED":
        raise invalid_state("referral is not ACCEPTED")
    ref["handoff_confirmed_at"] = db.now()
    db.touch(ref)
    return ok(db.pub(ref))


@bp.route("/referrals/<referral_id>/complete", methods=["POST"])
def complete_referral(referral_id):
    require("CaseManager", "CenterAdmin")
    ref = get_or_404("referrals", referral_id, "referral")
    if ref["status"] != "ACCEPTED":
        raise invalid_state("referral is not ACCEPTED")
    if ref.get("handoff_confirmed_at") is None:
        raise ApiError("ERR_HANDOFF_NOT_CONFIRMED", 409,
                       "warm handoff has not been confirmed")
    ref["status"] = "COMPLETED"
    ref["completed_at"] = db.now()
    db.touch(ref)
    org = db.get("organizations", ref["organization_id"])
    if org is not None:
        services.org_slot_delta(org, -1)
    return ok(db.pub(ref))


@bp.route("/referrals/<referral_id>/withdraw", methods=["POST"])
def withdraw_referral(referral_id):
    require("CaseManager", "CenterAdmin")
    ref = get_or_404("referrals", referral_id, "referral")
    if ref["status"] not in ("DRAFT", "SENT", "ACCEPTED", "SUSPENDED"):
        raise invalid_state("referral cannot be withdrawn from "
                            + ref["status"])
    prior = ref["status"]
    ref["status"] = "WITHDRAWN"
    db.touch(ref)
    if prior in ("SENT", "ACCEPTED"):
        org = db.get("organizations", ref["organization_id"])
        if org is not None:
            services.org_slot_delta(org, -1)
    # SUSPENDED held no slot; DRAFT never held one
    return ok(db.pub(ref))


@bp.route("/referrals/<referral_id>/reroute", methods=["POST"])
def reroute_referral(referral_id):
    require("CaseManager")
    ref = get_or_404("referrals", referral_id, "referral")
    data = body_json()

    # rung 3: body-referenced id
    new_org_id = data.get("organization_id")
    new_org = None
    if new_org_id is not None:
        if not isinstance(new_org_id, str):
            raise bad_request("organization_id must be a string")
        new_org = get_or_404("organizations", new_org_id, "organization")

    # rung 4: state
    if ref["status"] not in ("DECLINED", "EXPIRED"):
        raise invalid_state("only DECLINED or EXPIRED referrals reroute")

    # rung 7: structural
    req_present(data, "organization_id")
    if new_org_id == ref["organization_id"]:
        raise bad_request("reroute requires a different organization")
    if ref["service_category"] not in new_org["service_categories"]:
        raise bad_request("new organization does not serve the referral's "
                          "category")

    # full send gates against the new org
    case = db.get("cases", ref["case_id"])
    _send_gates(ref, case, new_org, check_case_status=True)

    ref["organization_id"] = new_org_id
    ref["status"] = "SENT"
    ref["sent_at"] = db.now()
    db.touch(ref)
    services.org_slot_delta(new_org, +1)
    return ok(db.pub(ref))


@bp.route("/referrals/<referral_id>/resume", methods=["POST"])
def resume_referral(referral_id):
    require("CaseManager")
    ref = get_or_404("referrals", referral_id, "referral")
    if ref["status"] != "SUSPENDED":
        raise invalid_state("referral is not SUSPENDED")
    case = db.get("cases", ref["case_id"])
    org = db.get("organizations", ref["organization_id"])
    # resume gates: posture, consent, org status, org capacity (no case gate)
    _send_gates(ref, case, org, check_case_status=False)
    ref["status"] = "SENT"
    ref["suspension_reason"] = None
    ref["sent_at"] = db.now()
    db.touch(ref)
    services.org_slot_delta(org, +1)
    return ok(db.pub(ref))


# ---------------------------------------------------------------------------
# Appointments
# ---------------------------------------------------------------------------

def _advocate_conflict(advocate_id, starts_at, ends_at):
    """Half-open interval intersection among REQUESTED/CONFIRMED rows."""
    for appt in db.all_of("appointments"):
        if appt["advocate_id"] != advocate_id:
            continue
        if appt["status"] not in ("REQUESTED", "CONFIRMED"):
            continue
        if ends_at <= appt["starts_at"] or starts_at >= appt["ends_at"]:
            continue  # adjacency allowed
        return True
    return False


@bp.route("/appointments", methods=["POST"])
def create_appointment():
    require("CaseManager", "IntakeSpecialist", "CenterAdmin")
    data = body_json()

    # rung 3: body ids in fixed order: case_id, advocate_id, referral_id
    case_id = data.get("case_id")
    advocate_id = data.get("advocate_id")
    referral_id = data.get("referral_id")
    case = None
    if case_id is not None:
        if not isinstance(case_id, str):
            raise bad_request("case_id must be a string")
        case = get_or_404("cases", case_id, "case")
    if advocate_id is not None:
        if not isinstance(advocate_id, str):
            raise bad_request("advocate_id must be a string")
        get_or_404("staff", advocate_id, "staff")
    if referral_id is not None:
        if not isinstance(referral_id, str):
            raise bad_request("referral_id must be a string")
        get_or_404("referrals", referral_id, "referral")

    # rung 4: SUSPENDED/CLOSED cases reject appointment creation
    if case is not None and case["service_status"] in ("SUSPENDED", "CLOSED"):
        raise invalid_state("case is not accepting new appointments")

    # rung 5: SEALED posture blocks appointment creation for everyone
    if case is not None and case["privacy_posture"] == "SEALED":
        raise ApiError("ERR_PRIVACY_SEALED", 409,
                       "case is SEALED")

    # rung 7: structural
    req_present(data, "case_id")
    req_present(data, "advocate_id")
    kind = req_enum(data, "kind", APPOINTMENT_KINDS)
    starts_at = req_datetime(data, "starts_at")
    ends_at = req_datetime(data, "ends_at")
    if ends_at <= starts_at:
        raise bad_request("ends_at must be after starts_at")

    # rung 8: temporal
    if starts_at < db.now():
        raise ApiError("ERR_TIME_IN_PAST", 409,
                       "starts_at precedes the current logical clock")
    if _advocate_conflict(advocate_id, starts_at, ends_at):
        raise ApiError("ERR_ADVOCATE_TIME_CONFLICT", 409,
                       "advocate has an overlapping appointment")

    appt = db.new_entity("appointments", {
        "case_id": case_id,
        "advocate_id": advocate_id,
        "referral_id": referral_id,
        "kind": kind,
        "starts_at": starts_at,
        "ends_at": ends_at,
        "status": "REQUESTED",
        "completed_at": None,
        "cancelled_by_system": False,
    })
    return ok(db.pub(appt), status=201)


@bp.route("/appointments/<appointment_id>", methods=["GET"])
def get_appointment(appointment_id):
    require("CenterAdmin", "CaseManager", "IntakeSpecialist")
    appt = get_or_404("appointments", appointment_id, "appointment")
    return ok(db.pub(appt))


@bp.route("/appointments", methods=["GET"])
def list_appointments():
    require("CenterAdmin", "CaseManager", "IntakeSpecialist")
    items = db.all_of("appointments")
    for param in ("case_id", "advocate_id", "referral_id", "status"):
        v = request.args.get(param)
        if v is not None:
            items = [a for a in items if str(a.get(param)) == v]
    page, meta = paginate(items)
    return ok_list([db.pub(a) for a in page], meta)


@bp.route("/appointments/<appointment_id>/confirm", methods=["POST"])
def confirm_appointment(appointment_id):
    require("CaseManager", "CenterAdmin")
    appt = get_or_404("appointments", appointment_id, "appointment")
    if appt["status"] != "REQUESTED":
        raise invalid_state("appointment is not REQUESTED")
    if appt["kind"] == "ACCOMPANIMENT":
        case = db.get("cases", appt["case_id"])
        if not services.has_granted_consent(case["client_id"],
                                            "ACCOMPANIMENT"):
            raise ApiError("ERR_CONSENT_MISSING", 409,
                           "client holds no GRANTED ACCOMPANIMENT consent")
    appt["status"] = "CONFIRMED"
    db.touch(appt)
    return ok(db.pub(appt))


@bp.route("/appointments/<appointment_id>/cancel", methods=["POST"])
def cancel_appointment(appointment_id):
    require("CaseManager", "CenterAdmin")
    appt = get_or_404("appointments", appointment_id, "appointment")
    if appt["status"] not in ("REQUESTED", "CONFIRMED"):
        raise invalid_state("appointment cannot be cancelled")
    appt["status"] = "CANCELLED"
    appt["cancelled_by_system"] = False
    db.touch(appt)
    return ok(db.pub(appt))


@bp.route("/appointments/<appointment_id>/complete", methods=["POST"])
def complete_appointment(appointment_id):
    require("CaseManager", "CenterAdmin")
    appt = get_or_404("appointments", appointment_id, "appointment")
    if appt["status"] != "CONFIRMED":
        raise invalid_state("appointment is not CONFIRMED")
    appt["status"] = "COMPLETED"
    appt["completed_at"] = db.now()
    db.touch(appt)
    return ok(db.pub(appt))
