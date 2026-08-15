"""Distributions, temperature logs, food-safety incidents."""
from flask import request

import errors as E
import services as svc
from db import store, stamp_new, touch, now
from errors import ApiError
from middleware import require_roles
from response import ok_obj, ok_list
from util import serialize, dec1, iso_week_key

PC = "ProgramCoordinator"
CL = "CrewLeader"
FSO = "FoodSafetyOfficer"
GR = "GrantReviewer"

TERMINAL_DIST = ("DELIVERED", "SHORTFALL", "CANCELLED")
TERMINAL_INCIDENT = ("RESOLVED_COMPOST", "RESOLVED_ANIMAL_FEED", "RESOLVED_LANDFILL")

# calculations.cold_chain_breach thresholds
THRESHOLD_HIGH_MEDIUM_F = 41.0
THRESHOLD_LOW_F = 55.0


def register(app):

    # ---------------- Distributions ----------------

    @app.route("/glean/distributions", methods=["POST"])
    def create_distribution():
        require_roles(PC)
        fs = svc.FieldSet()
        glean_event_id = fs.req_str("glean_event_id")
        agency_id = fs.req_str("agency_id")
        planned_lbs = fs.req_num("planned_lbs")
        delivery_date = fs.req_dt("delivery_date")
        expected_event_version = fs.req_int("expected_event_version")
        # Gate 3: body FK existence
        ev = svc.fk_or_404(store.events, glean_event_id, "GleanEvent")
        agency = svc.fk_or_404(store.agencies, agency_id, "Agency")
        # Gate 4: event must be HARVESTED
        if ev is not None and ev["status"] != "HARVESTED":
            raise ApiError(E.ERR_INVALID_STATE, 409,
                           "Distributions can be created only from a HARVESTED event")
        offer = svc.offer_of_event(ev) if ev is not None else None
        # Gate 13: refrigeration capability of the agency
        if offer is not None and agency is not None:
            if offer["requires_refrigeration"] and not agency["refrigeration_capable"]:
                raise ApiError(E.ERR_VEHICLE_REFRIGERATION_MISMATCH, 422,
                               "Agency cannot receive a refrigeration-required load")
        planned_r = dec1(planned_lbs) if planned_lbs is not None else None
        # Gate 14: allocation feasibility (equality allowed)
        if ev is not None and planned_r is not None:
            if planned_r > svc.event_available_lbs(ev):
                raise ApiError(E.ERR_ALLOCATION_EXCEEDS_HARVEST, 422,
                               "planned_lbs exceeds the event's available pounds")
        # Gate 17: agency weekly capacity (equality allowed)
        if agency is not None and planned_r is not None and delivery_date is not None:
            committed = svc.agency_week_committed(agency_id,
                                                  iso_week_key(delivery_date))
            if committed + planned_r > agency["weekly_capacity_lbs"]:
                raise ApiError(E.ERR_AGENCY_CAPACITY_EXCEEDED, 422,
                               "Agency weekly capacity would be exceeded")
        # Gate 19: optimistic concurrency on the parent event
        if ev is not None and expected_event_version is not None:
            if expected_event_version != ev["version"]:
                raise ApiError(E.ERR_STALE_EVENT_VERSION, 412,
                               "expected_event_version does not match the event's version")
        # Gate 24: agency active gate
        if agency is not None and not agency["active_flag"]:
            raise ApiError(E.ERR_AGENCY_INACTIVE, 422,
                           "Agency active_flag is false")
        # Gate 26: request shape
        if planned_lbs is not None and planned_lbs <= 0:
            fs.bad = True
        fs.raise_if_bad()
        rec = {
            "glean_event_id": glean_event_id,
            "agency_id": agency_id,
            "planned_lbs": planned_r,
            "delivery_date": delivery_date,
            "delivered_lbs": None,
            "status": "SCHEDULED",
            "cold_chain_intact": svc.compute_cold_chain_intact(ev),
        }
        stamp_new(rec)
        store.distributions[rec["id"]] = rec
        # Creating a distribution advances the parent event's version (PRD §2.9)
        svc.recompute_event_totals(ev)
        touch(ev)
        svc.refresh_agency_committed(agency)
        return ok_obj(serialize(rec), 201)

    @app.route("/glean/distributions", methods=["GET"])
    def list_distributions():
        require_roles(PC, GR, CL)
        page, limit, offset, total = svc.paginate(
            store.distributions.values(),
            {"glean_event_id": request.args.get("glean_event_id"),
             "agency_id": request.args.get("agency_id"),
             "status": request.args.get("status")})
        return ok_list([serialize(r) for r in page], limit, offset, total)

    @app.route("/glean/distributions/<rid>", methods=["GET"])
    def get_distribution(rid):
        require_roles(PC, GR, CL)
        d = svc.get_or_404(store.distributions, rid, "Distribution")
        return ok_obj(serialize(d))

    @app.route("/glean/distributions/<rid>/deliver", methods=["POST"])
    def deliver_distribution(rid):
        require_roles(CL)
        d = svc.get_or_404(store.distributions, rid, "Distribution")
        fs = svc.FieldSet()
        delivered_lbs = fs.req_num("delivered_lbs")
        status = d["status"]
        # Terminal-state lockdown dominates all later gates for the path target
        if status in TERMINAL_DIST:
            raise ApiError(E.ERR_ALREADY_TERMINAL, 409,
                           "Distribution is in terminal state %s" % status)
        ev = store.events.get(d["glean_event_id"])
        # Gate 4: state compatibility
        if status != "SCHEDULED":
            raise ApiError(E.ERR_INVALID_STATE, 409,
                           "Only a SCHEDULED distribution can be delivered")
        if ev is not None and ev["status"] != "HARVESTED":
            raise ApiError(E.ERR_INVALID_STATE, 409,
                           "The event must be HARVESTED to record a delivery")
        # Gate 5: cold-chain delivery gate
        offer = svc.offer_of_event(ev) if ev is not None else None
        if (offer is not None and offer["requires_refrigeration"]
                and not d["cold_chain_intact"]):
            raise ApiError(E.ERR_COLD_CHAIN_BREACH, 422,
                           "Cold chain breach recorded for this event")
        # Gate 26: request shape — delivered_lbs in (0, planned_lbs]
        delivered_r = dec1(delivered_lbs) if delivered_lbs is not None else None
        if delivered_r is not None and (delivered_r <= 0 or delivered_r > d["planned_lbs"]):
            fs.bad = True
        fs.raise_if_bad()
        d["delivered_lbs"] = delivered_r
        d["status"] = "DELIVERED" if delivered_r == d["planned_lbs"] else "SHORTFALL"
        touch(d)
        agency = store.agencies.get(d["agency_id"])
        if agency is not None:
            svc.refresh_agency_committed(agency)
        if ev is not None and svc.recompute_event_totals(ev):
            touch(ev)
        return ok_obj(serialize(d))

    @app.route("/glean/distributions/<rid>/cancel", methods=["POST"])
    def cancel_distribution(rid):
        require_roles(PC)
        d = svc.get_or_404(store.distributions, rid, "Distribution")
        status = d["status"]
        if status in TERMINAL_DIST:
            raise ApiError(E.ERR_ALREADY_TERMINAL, 409,
                           "Distribution is in terminal state %s" % status)
        d["status"] = "CANCELLED"
        touch(d)
        agency = store.agencies.get(d["agency_id"])
        if agency is not None:
            svc.refresh_agency_committed(agency)
        ev = store.events.get(d["glean_event_id"])
        if ev is not None and svc.recompute_event_totals(ev):
            touch(ev)
        return ok_obj(serialize(d))

    # ---------------- Temperature Logs ----------------

    @app.route("/glean/templogs", methods=["POST"])
    def create_templog():
        require_roles(CL, FSO)
        fs = svc.FieldSet()
        glean_event_id = fs.req_str("glean_event_id")
        recorded_at = fs.req_dt("recorded_at")
        temp_f = fs.req_num("temp_f")
        # Gate 3: body FK existence
        ev = svc.fk_or_404(store.events, glean_event_id, "GleanEvent")
        fs.raise_if_bad()
        temp_r = dec1(temp_f)
        offer = svc.offer_of_event(ev)
        threshold = (THRESHOLD_LOW_F
                     if offer is not None and offer["perishability_class"] == "LOW"
                     else THRESHOLD_HIGH_MEDIUM_F)
        breach = float(temp_r) > threshold  # strict: exactly at threshold is no breach
        rec = {
            "glean_event_id": glean_event_id,
            "recorded_at": recorded_at,
            "temp_f": temp_r,
            "breach_flag": breach,
        }
        stamp_new(rec, mutable=False)
        store.templogs[rec["id"]] = rec
        if breach:
            for d in svc.distributions_of_event(glean_event_id):
                if d["status"] != "SCHEDULED":
                    continue
                if not svc.compute_cold_chain_intact(ev):
                    if d["cold_chain_intact"]:
                        d["cold_chain_intact"] = False
                        touch(d)
        return ok_obj(serialize(rec), 201)

    @app.route("/glean/templogs", methods=["GET"])
    def list_templogs():
        require_roles(PC, FSO)
        page, limit, offset, total = svc.paginate(
            store.templogs.values(),
            {"glean_event_id": request.args.get("glean_event_id")})
        return ok_list([serialize(r) for r in page], limit, offset, total)

    @app.route("/glean/templogs/<rid>", methods=["GET"])
    def get_templog(rid):
        require_roles(PC, FSO)
        t = svc.get_or_404(store.templogs, rid, "TempLog")
        return ok_obj(serialize(t))

    # ---------------- Food Safety Incidents ----------------

    @app.route("/glean/incidents", methods=["POST"])
    def create_incident():
        require_roles(CL, FSO)
        fs = svc.FieldSet()
        glean_event_id = fs.req_str("glean_event_id")
        severity = fs.req_enum("severity", ("MINOR", "CRITICAL"))
        condemned_lbs = fs.req_num("condemned_lbs")
        reported_by_volunteer_id = fs.req_str("reported_by_volunteer_id")
        # Gate 3: body FK existence
        svc.fk_or_404(store.events, glean_event_id, "GleanEvent")
        svc.fk_or_404(store.volunteers, reported_by_volunteer_id, "Volunteer")
        # Gate 26: request shape
        if condemned_lbs is not None and condemned_lbs <= 0:
            fs.bad = True
        fs.raise_if_bad()
        rec = {
            "glean_event_id": glean_event_id,
            "severity": severity,
            "condemned_lbs": dec1(condemned_lbs),
            "reported_by_volunteer_id": reported_by_volunteer_id,
            "disposition": "OPEN",
        }
        stamp_new(rec)
        store.incidents[rec["id"]] = rec
        return ok_obj(serialize(rec), 201)

    @app.route("/glean/incidents", methods=["GET"])
    def list_incidents():
        require_roles(PC, FSO, GR)
        page, limit, offset, total = svc.paginate(
            store.incidents.values(),
            {"glean_event_id": request.args.get("glean_event_id"),
             "reported_by_volunteer_id": request.args.get("reported_by_volunteer_id")})
        return ok_list([serialize(r) for r in page], limit, offset, total)

    @app.route("/glean/incidents/<rid>", methods=["GET"])
    def get_incident(rid):
        require_roles(PC, FSO, GR)
        i = svc.get_or_404(store.incidents, rid, "FoodSafetyIncident")
        return ok_obj(serialize(i))

    @app.route("/glean/incidents/<rid>/resolve", methods=["POST"])
    def resolve_incident(rid):
        require_roles(FSO)
        inc = svc.get_or_404(store.incidents, rid, "FoodSafetyIncident")
        fs = svc.FieldSet()
        disposition = fs.req_enum("disposition", ("COMPOST", "ANIMAL_FEED", "LANDFILL"))
        status = inc["disposition"]
        if status in TERMINAL_INCIDENT:
            raise ApiError(E.ERR_ALREADY_TERMINAL, 409,
                           "Incident is in terminal state %s" % status)
        if status != "OPEN":
            raise ApiError(E.ERR_INVALID_STATE, 409,
                           "Only an OPEN incident can be resolved")
        fs.raise_if_bad()
        inc["disposition"] = "RESOLVED_" + disposition
        touch(inc)
        ev = store.events.get(inc["glean_event_id"])
        if ev is not None:
            if svc.recompute_event_totals(ev):
                touch(ev)
            # PRD §2.9: an incident resolution advances the offer's version,
            # invalidating a close requester's pinned expected_offer_version.
            offer = svc.offer_of_event(ev)
            if offer is not None and offer["status"] not in ("CLOSED", "CANCELLED", "EXPIRED"):
                touch(offer)
        return ok_obj(serialize(inc))
