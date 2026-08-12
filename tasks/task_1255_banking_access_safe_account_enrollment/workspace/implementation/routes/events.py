"""AccountOpeningEvent endpoints."""

import db
from errors import (
    err_not_found, err_invalid_state, err_validation, err_unauthorized, raise_err,
    ERR_INSTITUTION_NOT_CERTIFIED, ERR_EVENT_WINDOW_CONFLICT,
)
from middleware import (
    require_roles, get_json_body, require_fields, check_string, check_int, check_bool,
)
from response import success_object, success_list, parse_pagination
from services.common import new_entity, touch, recompute_pipeline
from flask import request


def _serialize(e):
    return dict(e)


def release_event_bookings(ev):
    """Release all BOOKED referrals of an event back to DOCS_COMPLETE."""
    for ref in db.referrals.values():
        if ref.get("booked_event_id") == ev["id"] and ref["status"] == "BOOKED":
            ref["status"] = "DOCS_COMPLETE"
            ref["booked_event_id"] = None
            touch(ref)
            if ev["booked_count"] > 0:
                ev["booked_count"] -= 1
            recompute_pipeline(ref["participant_id"])


def register(bp):
    @bp.route("/account-opening-events", methods=["POST"])
    def create_event():
        user_id, _ = require_roles("InstitutionOfficer")
        body = get_json_body()
        require_fields(body, ["institution_id", "venue_code", "starts_at", "ends_at", "capacity", "alt_id_accepted"])
        check_string(body["institution_id"], "institution_id")
        check_string(body["venue_code"], "venue_code")
        check_string(body["starts_at"], "starts_at")
        check_string(body["ends_at"], "ends_at")
        check_int(body["capacity"], "capacity")
        check_bool(body["alt_id_accepted"], "alt_id_accepted")
        if not db.is_valid_iso_datetime(body["starts_at"]) or not db.is_valid_iso_datetime(body["ends_at"]):
            err_validation("starts_at and ends_at must be ISO 8601 timestamps")
        if db.parse_dt(body["starts_at"]) >= db.parse_dt(body["ends_at"]):
            err_validation("starts_at must be strictly before ends_at")

        # ownership: officer identity equals institution_id
        if user_id != body["institution_id"]:
            err_unauthorized("InstitutionOfficer identity must equal institution_id")

        inst = db.partner_institutions.get(body["institution_id"])
        if inst is None:
            err_not_found("PartnerInstitution not found")

        # temporal: window overlap at same institution+venue
        ns = db.parse_dt(body["starts_at"])
        ne = db.parse_dt(body["ends_at"])
        for other in db.account_opening_events.values():
            if other["institution_id"] != inst["id"]:
                continue
            if other["venue_code"] != body["venue_code"]:
                continue
            if other["status"] != "SCHEDULED":
                continue
            os_ = db.parse_dt(other["starts_at"])
            oe = db.parse_dt(other["ends_at"])
            if ns < oe and os_ < ne:
                raise_err(ERR_EVENT_WINDOW_CONFLICT, "Event window overlaps an existing SCHEDULED event at this venue")

        # cross-entity state: institution must be CERTIFIED
        if inst["certification_status"] != "CERTIFIED":
            raise_err(ERR_INSTITUTION_NOT_CERTIFIED, "Institution must be CERTIFIED to schedule events")

        # alt_id_accepted requires certified standard to accept >= 1 alt id type
        if body["alt_id_accepted"]:
            std = db.account_standards.get(inst.get("certified_standard_id"))
            if std is None or not std.get("accepted_alt_id_types"):
                err_validation("alt_id_accepted requires the certified standard to accept alternative ID types")

        ev = new_entity()
        ev.update({
            "institution_id": inst["id"],
            "venue_code": body["venue_code"],
            "starts_at": body["starts_at"],
            "ends_at": body["ends_at"],
            "capacity": body["capacity"],
            "booked_count": 0,
            "alt_id_accepted": body["alt_id_accepted"],
            "status": "SCHEDULED",
        })
        db.account_opening_events[ev["id"]] = ev
        return success_object(_serialize(ev), status=201)

    @bp.route("/account-opening-events", methods=["GET"])
    def list_events():
        require_roles("CoalitionAdmin", "InstitutionOfficer", "AgencyNavigator", "Participant")
        limit, offset = parse_pagination(request.args)
        items = sorted(db.account_opening_events.values(), key=lambda x: db.parse_dt(x["created_at"]))
        iid = request.args.get("institution_id")
        st = request.args.get("status")
        if iid is not None:
            items = [e for e in items if e["institution_id"] == iid]
        if st is not None:
            items = [e for e in items if e["status"] == st]
        total = len(items)
        page = items[offset:offset + limit]
        return success_list([_serialize(e) for e in page], limit, offset, total)

    @bp.route("/account-opening-events/<eid>", methods=["GET"])
    def get_event(eid):
        require_roles("CoalitionAdmin", "InstitutionOfficer", "AgencyNavigator", "Participant")
        ev = db.account_opening_events.get(eid)
        if ev is None:
            err_not_found("AccountOpeningEvent not found")
        return success_object(_serialize(ev))

    @bp.route("/account-opening-events/<eid>/referrals", methods=["GET"])
    def event_roster(eid):
        require_roles("CoalitionAdmin", "InstitutionOfficer", "AgencyNavigator")
        ev = db.account_opening_events.get(eid)
        if ev is None:
            err_not_found("AccountOpeningEvent not found")
        limit, offset = parse_pagination(request.args)
        items = [
            r for r in sorted(db.referrals.values(), key=lambda x: db.parse_dt(x["created_at"]))
            if r.get("booked_event_id") == eid
        ]
        total = len(items)
        page = items[offset:offset + limit]
        return success_list([dict(r) for r in page], limit, offset, total)

    @bp.route("/account-opening-events/<eid>/cancel", methods=["POST"])
    def cancel_event(eid):
        user_id, _ = require_roles("InstitutionOfficer")
        ev = db.account_opening_events.get(eid)
        if ev is None:
            err_not_found("AccountOpeningEvent not found")
        if user_id != ev["institution_id"]:
            err_unauthorized("Officer must belong to the event's institution")
        if ev["status"] != "SCHEDULED":
            err_invalid_state("Event must be SCHEDULED to cancel")
        release_event_bookings(ev)
        ev["status"] = "CANCELLED"
        touch(ev)
        return success_object(_serialize(ev))
