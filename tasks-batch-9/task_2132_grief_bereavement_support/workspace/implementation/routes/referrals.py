"""Intake referrals (§3.1)."""

from flask import Blueprint, request

from core import calc
from core.auth import authenticate
from core.envelope import created, listing, ok
from core.errors import ApiError
from core.shape import (LOSS_TYPES, RELATIONSHIPS, SOURCE_TYPES, DECLINE_REASONS,
                        body, iso_date, opt_str, req_date, req_enum, req_str, bad, parse_date)
from core.store import public, store
from services import derive
from services.state import must_exist, transition

bp = Blueprint("referrals", __name__)

READ_ROLES = ["IntakeCoordinator", "ProgramDirector"]


@bp.route("/bereavement/referrals", methods=["POST"])
def create_referral():
    ctx = authenticate(["ReferralSource", "IntakeCoordinator"])
    data = body()
    source_type = req_enum(data, "source_type", SOURCE_TYPES)
    decedent_name = req_str(data, "decedent_name")
    date_of_death = req_date(data, "date_of_death")
    relationship = req_enum(data, "relationship_to_deceased", RELATIONSHIPS)
    loss_type = req_enum(data, "loss_type", LOSS_TYPES)
    contact_name = req_str(data, "contact_name")
    contact_email = req_str(data, "contact_email")
    source_org_name = opt_str(data, "source_org_name")
    if source_type == "SELF":
        if source_org_name is not None:
            bad("source_org_name must be omitted or null for a SELF referral.")
    elif source_org_name is None:
        bad("source_org_name is required when source_type is not SELF.")

    # rung 12 — time geometry
    if date_of_death > store.today():
        raise ApiError("ERR_DECEASED_DATE_IN_FUTURE", "date_of_death is later than the logical clock date.")

    # rung 13 — uniqueness
    dod = iso_date(date_of_death)
    for other in store.all("Referral"):
        if (other["status"] in ("RECEIVED", "SCREENED", "ACCEPTED")
                and other["contact_email"] == contact_email
                and other["date_of_death"] == dod):
            raise ApiError("ERR_DUPLICATE_REFERRAL", "This bereavement has already been filed.")

    rec = store.create("Referral", {
        "source_type": source_type,
        "source_org_name": source_org_name,
        "decedent_name": decedent_name,
        "date_of_death": dod,
        "relationship_to_deceased": relationship,
        "loss_type": loss_type,
        "contact_name": contact_name,
        "contact_email": contact_email,
        "status": "RECEIVED",
        "screening_band": None,
        "days_since_death": None,
        "eligibility_note": None,
        "decline_reason": None,
        "participant_id": None,
    })
    return created(public(rec))


@bp.route("/bereavement/referrals/<rid>", methods=["GET"])
def read_referral(rid):
    authenticate(READ_ROLES)
    return ok(public(must_exist("Referral", rid)))


@bp.route("/bereavement/referrals", methods=["GET"])
def list_referrals():
    authenticate(READ_ROLES)
    rows = store.all("Referral")
    status = request.args.get("status")
    source_type = request.args.get("source_type")
    participant_id = request.args.get("participant_id")
    if status:
        rows = [r for r in rows if r["status"] == status]
    if source_type:
        rows = [r for r in rows if r["source_type"] == source_type]
    if participant_id:
        rows = [r for r in rows if r["participant_id"] == participant_id]
    return listing(rows, public)


@bp.route("/bereavement/referrals/<rid>/screen", methods=["POST"])
def screen_referral(rid):
    authenticate(["IntakeCoordinator"])
    rec = must_exist("Referral", rid)
    data = body()
    note = opt_str(data, "eligibility_note")
    transition(rec, {"RECEIVED"})
    dod = parse_date(rec["date_of_death"], "date_of_death")
    if dod > store.today():
        raise ApiError("ERR_DECEASED_DATE_IN_FUTURE", "date_of_death is later than the logical clock date.")
    days = (store.today() - dod).days
    rec["status"] = "SCREENED"
    rec["days_since_death"] = days
    rec["screening_band"] = calc.screening_band(days)
    if note is not None:
        rec["eligibility_note"] = note
    store.touch(rec)
    return ok(public(rec))


@bp.route("/bereavement/referrals/<rid>/decline", methods=["POST"])
def decline_referral(rid):
    authenticate(["IntakeCoordinator"])
    rec = must_exist("Referral", rid)
    data = body()
    reason = req_enum(data, "decline_reason", DECLINE_REASONS)
    transition(rec, {"RECEIVED", "SCREENED"})
    rec["status"] = "DECLINED"
    rec["decline_reason"] = reason
    store.touch(rec)
    return ok(public(rec))


@bp.route("/bereavement/referrals/<rid>/accept", methods=["POST"])
def accept_referral(rid):
    authenticate(["IntakeCoordinator"])
    rec = must_exist("Referral", rid)
    body()
    transition(rec, {"SCREENED"}, "ERR_REFERRAL_NOT_SCREENED")

    participant = store.create("Participant", {
        "referral_id": rec["id"],
        "display_name": rec["contact_name"],
        "loss_type": rec["loss_type"],
        "relationship_to_deceased": rec["relationship_to_deceased"],
        "date_of_death": rec["date_of_death"],
        "anniversary_month_day": rec["date_of_death"][5:],
        "service_status": "INTAKE",
        "outreach_status": "SCHEDULED",
        "risk_tier": "LOW",
        "composite_need_index": 0,
        "waitlist_reentry_count": 0,
        "sessions_attended_total": 0,
        "outreach_cadence_days": 90,
        "baseline_score": None,
        "latest_score": None,
        "has_active_companion": False,
    })
    derive.create_cadence_plan(participant)
    rec["status"] = "ACCEPTED"
    rec["participant_id"] = participant["id"]
    store.touch(rec)
    return created(public(participant))
