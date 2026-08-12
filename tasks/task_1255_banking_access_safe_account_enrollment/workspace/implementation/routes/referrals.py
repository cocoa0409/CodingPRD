"""Referral endpoints."""

import db
from errors import (
    err_not_found, err_invalid_state, err_validation, raise_err,
    ERR_DOCS_INCOMPLETE, ERR_EVENT_NOT_BOOKABLE, ERR_INSTITUTION_NOT_CERTIFIED,
    ERR_EVENT_FULL,
)
from middleware import require_roles, get_json_body, require_fields, check_string, check_enum
from response import success_object, success_list, parse_pagination
from services.common import new_entity, touch, recompute_pipeline
from flask import request

CREATED_VIA = {"NAVIGATOR", "CAMPAIGN"}


def _serialize(r):
    return dict(r)


def register(bp):
    @bp.route("/referrals", methods=["POST"])
    def create_referral():
        user_id, role = require_roles("AgencyNavigator", "CoalitionAdmin")
        body = get_json_body()
        require_fields(body, ["participant_id", "created_via"])
        check_string(body["participant_id"], "participant_id")
        check_enum(body["created_via"], CREATED_VIA, "created_via")
        campaign_id = body.get("campaign_id")
        if body["created_via"] == "CAMPAIGN":
            if not campaign_id:
                err_validation("campaign_id is required when created_via=CAMPAIGN")
        else:
            if campaign_id is not None:
                err_validation("campaign_id must be null when created_via=NAVIGATOR")

        participant = db.participants.get(body["participant_id"])
        if participant is None:
            err_not_found("Participant not found")

        campaign = None
        if campaign_id is not None:
            campaign = db.outreach_campaigns.get(campaign_id)
            if campaign is None:
                err_not_found("OutreachCampaign not found")
            if campaign["status"] != "ACTIVE":
                err_invalid_state("Campaign must be ACTIVE for new referrals")

        ref = new_entity()
        ref.update({
            "participant_id": participant["id"],
            "campaign_id": campaign_id if body["created_via"] == "CAMPAIGN" else None,
            "created_via": body["created_via"],
            "agency_user_id": user_id if body["created_via"] == "NAVIGATOR" else None,
            "status": "DOCS_PENDING",
            "booked_event_id": None,
        })
        db.referrals[ref["id"]] = ref
        recompute_pipeline(participant["id"])
        return success_object(_serialize(ref), status=201)

    @bp.route("/referrals", methods=["GET"])
    def list_referrals():
        require_roles("CoalitionAdmin", "AgencyNavigator", "InstitutionOfficer")
        limit, offset = parse_pagination(request.args)
        items = sorted(db.referrals.values(), key=lambda x: db.parse_dt(x["created_at"]))
        pid = request.args.get("participant_id")
        cid = request.args.get("campaign_id")
        beid = request.args.get("booked_event_id")
        st = request.args.get("status")
        if pid is not None:
            items = [r for r in items if r["participant_id"] == pid]
        if cid is not None:
            items = [r for r in items if r.get("campaign_id") == cid]
        if beid is not None:
            items = [r for r in items if r.get("booked_event_id") == beid]
        if st is not None:
            items = [r for r in items if r["status"] == st]
        total = len(items)
        page = items[offset:offset + limit]
        return success_list([_serialize(r) for r in page], limit, offset, total)

    @bp.route("/referrals/<rid>", methods=["GET"])
    def get_referral(rid):
        require_roles("CoalitionAdmin", "AgencyNavigator", "InstitutionOfficer")
        ref = db.referrals.get(rid)
        if ref is None:
            err_not_found("Referral not found")
        return success_object(_serialize(ref))

    @bp.route("/referrals/<rid>/docs-complete", methods=["POST"])
    def docs_complete(rid):
        require_roles("AgencyNavigator")
        ref = db.referrals.get(rid)
        if ref is None:
            err_not_found("Referral not found")
        if ref["status"] != "DOCS_PENDING":
            err_invalid_state("Referral must be DOCS_PENDING")
        participant = db.participants.get(ref["participant_id"])
        if participant is None or not participant.get("docs_complete"):
            raise_err(ERR_DOCS_INCOMPLETE, "Participant documentation is not complete")
        ref["status"] = "DOCS_COMPLETE"
        touch(ref)
        recompute_pipeline(ref["participant_id"])
        return success_object(_serialize(ref))

    @bp.route("/referrals/<rid>/book", methods=["POST"])
    def book(rid):
        require_roles("AgencyNavigator")
        ref = db.referrals.get(rid)
        if ref is None:
            err_not_found("Referral not found")
        body = get_json_body()
        require_fields(body, ["event_id"])
        check_string(body["event_id"], "event_id")
        ev = db.account_opening_events.get(body["event_id"])
        if ev is None:
            err_not_found("AccountOpeningEvent not found")
        if ref["status"] != "DOCS_COMPLETE":
            err_invalid_state("Referral must be DOCS_COMPLETE to book")
        if ev["status"] != "SCHEDULED":
            raise_err(ERR_EVENT_NOT_BOOKABLE, "Event is not SCHEDULED")
        inst = db.partner_institutions.get(ev["institution_id"])
        if inst is None or inst["certification_status"] != "CERTIFIED":
            raise_err(ERR_INSTITUTION_NOT_CERTIFIED, "Event institution must be CERTIFIED")
        if ev["booked_count"] >= ev["capacity"]:
            raise_err(ERR_EVENT_FULL, "Event is at capacity")
        ref["status"] = "BOOKED"
        ref["booked_event_id"] = ev["id"]
        touch(ref)
        ev["booked_count"] += 1
        touch(ev)
        recompute_pipeline(ref["participant_id"])
        return success_object(_serialize(ref))

    @bp.route("/referrals/<rid>/unbook", methods=["POST"])
    def unbook(rid):
        require_roles("AgencyNavigator")
        ref = db.referrals.get(rid)
        if ref is None:
            err_not_found("Referral not found")
        if ref["status"] != "BOOKED":
            err_invalid_state("Referral must be BOOKED to unbook")
        ev = db.account_opening_events.get(ref.get("booked_event_id"))
        ref["status"] = "DOCS_COMPLETE"
        ref["booked_event_id"] = None
        touch(ref)
        if ev is not None and ev["booked_count"] > 0:
            ev["booked_count"] -= 1
            touch(ev)
        recompute_pipeline(ref["participant_id"])
        return success_object(_serialize(ref))
