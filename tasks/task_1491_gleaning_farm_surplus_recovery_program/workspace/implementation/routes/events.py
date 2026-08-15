"""Glean events, crew assignments, waivers, harvest lots."""
from decimal import Decimal
from flask import request

import errors as E
import services as svc
from db import store, stamp_new, touch, now
from errors import ApiError
from middleware import require_roles
from response import ok_obj, ok_list
from util import serialize, dec1, intervals_overlap

PC = "ProgramCoordinator"
CL = "CrewLeader"
VOL = "Volunteer"
FSO = "FoodSafetyOfficer"
GR = "GrantReviewer"

TERMINAL_EVENT = ("RECONCILED", "CANCELLED")
TERMINAL_ASSIGNMENT = ("DECLINED", "NO_SHOW", "COMPLETED")
TERMINAL_LOT = ("VERIFIED", "REJECTED")


def register(app):

    # ---------------- Glean Events ----------------

    @app.route("/glean/events", methods=["POST"])
    def create_event():
        require_roles(PC)
        fs = svc.FieldSet()
        surplus_offer_id = fs.req_str("surplus_offer_id")
        scheduled_start = fs.req_dt("scheduled_start")
        scheduled_end = fs.req_dt("scheduled_end")
        crew_leader_volunteer_id = fs.req_str("crew_leader_volunteer_id")
        assigned_vehicle_id = fs.req_str("assigned_vehicle_id")
        crew_capacity = fs.req_int("crew_capacity")
        # Gate 3: body FK existence
        offer = svc.fk_or_404(store.offers, surplus_offer_id, "SurplusOffer")
        leader = svc.fk_or_404(store.volunteers, crew_leader_volunteer_id, "Volunteer")
        vehicle = svc.fk_or_404(store.vehicles, assigned_vehicle_id, "Vehicle")
        # Gate 4: offer must be OFFERED or SCHEDULED
        if offer is not None and offer["status"] not in ("OFFERED", "SCHEDULED"):
            raise ApiError(E.ERR_INVALID_STATE, 409,
                           "Cannot create an event against an offer in state %s"
                           % offer["status"])
        # OFFERED -> SCHEDULED transition preconditions (PRD §3.3): the logical
        # clock must not have reached the offer's window_end.
        if offer is not None and offer["status"] == "OFFERED" and now() >= offer["window_end"]:
            raise ApiError(E.ERR_INVALID_STATE, 409,
                           "The offer's harvest window has already ended")
        # Gate 7: event window containment in the offer's [window_start, window_end)
        if offer is not None and scheduled_start is not None and scheduled_end is not None:
            if (scheduled_start < offer["window_start"]
                    or scheduled_end > offer["window_end"]
                    or scheduled_start >= scheduled_end):
                raise ApiError(E.ERR_EVENT_WINDOW_OUTSIDE_OFFER, 422,
                               "Event schedule is not contained in the offer window")
        # Gate 10: vehicle schedule conflict
        if assigned_vehicle_id is not None and scheduled_start is not None \
                and scheduled_end is not None:
            if svc.vehicle_schedule_conflict(assigned_vehicle_id,
                                             scheduled_start, scheduled_end):
                raise ApiError(E.ERR_VEHICLE_SCHEDULE_CONFLICT, 422,
                               "Vehicle is assigned to an overlapping event")
        # Gate 13: refrigeration match
        if offer is not None and vehicle is not None:
            if offer["requires_refrigeration"] != vehicle["refrigerated"]:
                raise ApiError(E.ERR_VEHICLE_REFRIGERATION_MISMATCH, 422,
                               "Offer refrigeration requirement does not match vehicle")
        # Gate 23: farm active gate — required for the first event creation
        # (the OFFERED -> SCHEDULED transition) per PRD §3.3.
        if offer is not None and offer["status"] == "OFFERED":
            farm = store.farms.get(offer["farm_id"])
            if farm is not None and not farm["active_flag"]:
                raise ApiError(E.ERR_FARM_INACTIVE, 422,
                               "Farm active_flag is false")
        # Gate 26: request shape
        if crew_capacity is not None and crew_capacity <= 0:
            fs.bad = True
        if leader is not None and not leader["crew_leader_certified"]:
            fs.bad = True
        fs.raise_if_bad()
        rec = {
            "surplus_offer_id": surplus_offer_id,
            "scheduled_start": scheduled_start,
            "scheduled_end": scheduled_end,
            "crew_leader_volunteer_id": crew_leader_volunteer_id,
            "assigned_vehicle_id": assigned_vehicle_id,
            "crew_capacity": crew_capacity,
            "status": "DRAFT",
            "crew_confirmed_count": 0,
            "total_harvested_lbs": Decimal("0.0"),
            "total_distributed_lbs": Decimal("0.0"),
            "undistributed_lbs": Decimal("0.0"),
            "_harvested_at": None,
        }
        stamp_new(rec)
        store.events[rec["id"]] = rec
        if offer["status"] == "OFFERED":
            offer["status"] = "SCHEDULED"
            touch(offer)
        return ok_obj(serialize(rec), 201)

    @app.route("/glean/events", methods=["GET"])
    def list_events():
        require_roles(PC, CL, FSO, GR)
        page, limit, offset, total = svc.paginate(
            store.events.values(),
            {"surplus_offer_id": request.args.get("surplus_offer_id"),
             "status": request.args.get("status"),
             "crew_leader_volunteer_id": request.args.get("crew_leader_volunteer_id"),
             "assigned_vehicle_id": request.args.get("assigned_vehicle_id")})
        return ok_list([serialize(r) for r in page], limit, offset, total)

    @app.route("/glean/events/<rid>", methods=["GET"])
    def get_event(rid):
        require_roles(PC, CL, FSO, GR)
        ev = svc.get_or_404(store.events, rid, "GleanEvent")
        return ok_obj(serialize(ev))

    @app.route("/glean/events/<rid>/publish", methods=["POST"])
    def publish_event(rid):
        require_roles(PC)
        ev = svc.get_or_404(store.events, rid, "GleanEvent")
        status = ev["status"]
        if status in TERMINAL_EVENT:
            raise ApiError(E.ERR_ALREADY_TERMINAL, 409,
                           "Event is in terminal state %s" % status)
        if status != "DRAFT":
            raise ApiError(E.ERR_INVALID_STATE, 409,
                           "Only a DRAFT event can be published")
        offer = svc.offer_of_event(ev)
        if offer is None or offer["status"] != "SCHEDULED":
            raise ApiError(E.ERR_INVALID_STATE, 409,
                           "The offer must be SCHEDULED to publish an event")
        if offer is not None:
            if (ev["scheduled_start"] < offer["window_start"]
                    or ev["scheduled_end"] > offer["window_end"]):
                raise ApiError(E.ERR_EVENT_WINDOW_OUTSIDE_OFFER, 422,
                               "Event schedule is outside the offer window")
        # Gate 10: vehicle schedule conflict re-checked at publish
        if svc.vehicle_schedule_conflict(ev["assigned_vehicle_id"],
                                         ev["scheduled_start"], ev["scheduled_end"],
                                         exclude_event_id=ev["id"]):
            raise ApiError(E.ERR_VEHICLE_SCHEDULE_CONFLICT, 422,
                           "Vehicle is assigned to an overlapping event")
        vehicle = store.vehicles.get(ev["assigned_vehicle_id"])
        if vehicle is None or vehicle["status"] != "AVAILABLE":
            raise ApiError(E.ERR_INVALID_STATE, 409,
                           "Assigned vehicle is not AVAILABLE")
        vehicle["status"] = "ASSIGNED"
        touch(vehicle)
        ev["status"] = "OPEN"
        touch(ev)
        return ok_obj(serialize(ev))

    @app.route("/glean/events/<rid>/cancel", methods=["POST"])
    def cancel_event(rid):
        require_roles(PC)
        ev = svc.get_or_404(store.events, rid, "GleanEvent")
        status = ev["status"]
        if status in TERMINAL_EVENT:
            raise ApiError(E.ERR_ALREADY_TERMINAL, 409,
                           "Event is in terminal state %s" % status)
        if status not in ("DRAFT", "OPEN"):
            raise ApiError(E.ERR_INVALID_STATE, 409,
                           "Only a DRAFT or OPEN event can be cancelled")
        svc.cascade_event_cancel(ev)
        return ok_obj(serialize(ev))

    @app.route("/glean/events/<rid>/start", methods=["POST"])
    def start_event(rid):
        _, uid = require_roles(CL)
        ev = svc.get_or_404(store.events, rid, "GleanEvent")
        if uid != ev["crew_leader_volunteer_id"]:
            raise ApiError(E.ERR_UNAUTHORIZED, 403,
                           "Only the event's designated crew leader may start it")
        status = ev["status"]
        if status in TERMINAL_EVENT:
            raise ApiError(E.ERR_ALREADY_TERMINAL, 409,
                           "Event is in terminal state %s" % status)
        if status not in ("OPEN", "FULL"):
            raise ApiError(E.ERR_INVALID_STATE, 409,
                           "Only an OPEN or FULL event can be started")
        if status == "OPEN" and ev["crew_confirmed_count"] < 1:
            raise ApiError(E.ERR_INVALID_STATE, 409,
                           "At least one confirmed crew member is required to start")
        # Gate 21: scheduled_start <= now < scheduled_end
        if not (ev["scheduled_start"] <= now() < ev["scheduled_end"]):
            raise ApiError(E.ERR_EVENT_NOT_STARTED, 422,
                           "The logical clock is outside the event's scheduled window")
        ev["status"] = "IN_PROGRESS"
        touch(ev)
        return ok_obj(serialize(ev))

    @app.route("/glean/events/<rid>/finish", methods=["POST"])
    def finish_event(rid):
        require_roles(CL)
        ev = svc.get_or_404(store.events, rid, "GleanEvent")
        status = ev["status"]
        if status in TERMINAL_EVENT:
            raise ApiError(E.ERR_ALREADY_TERMINAL, 409,
                           "Event is in terminal state %s" % status)
        if status != "IN_PROGRESS":
            raise ApiError(E.ERR_INVALID_STATE, 409,
                           "Only an IN_PROGRESS event can be finished")
        verified = [l for l in svc.lots_of_event(rid) if l["status"] == "VERIFIED"]
        if not verified:
            raise ApiError(E.ERR_INVALID_STATE, 409,
                           "At least one VERIFIED harvest lot is required to finish")
        # Finish sweep: CONFIRMED -> COMPLETED; PENDING -> NO_SHOW
        for a in svc.assignments_of_event(rid):
            if a["status"] == "CONFIRMED":
                a["status"] = "COMPLETED"
                touch(a)
            elif a["status"] == "PENDING":
                a["status"] = "NO_SHOW"
                touch(a)
                vol = store.volunteers.get(a["volunteer_id"])
                if vol is not None:
                    vol["no_show_count"] += 1
                    if vol["no_show_count"] >= 2 and vol["status"] == "ACTIVE":
                        vol["status"] = "SUSPENDED"
                    touch(vol)
        ev["status"] = "HARVESTED"
        ev["_harvested_at"] = now()
        svc.recompute_event_totals(ev)
        touch(ev)
        offer = svc.offer_of_event(ev)
        if offer is not None:
            svc.reeval_offer_gleaned(offer)
        return ok_obj(serialize(ev))

    @app.route("/glean/events/<rid>/reconcile", methods=["POST"])
    def reconcile_event(rid):
        require_roles(PC)
        ev = svc.get_or_404(store.events, rid, "GleanEvent")
        status = ev["status"]
        if status in TERMINAL_EVENT:
            raise ApiError(E.ERR_ALREADY_TERMINAL, 409,
                           "Event is in terminal state %s" % status)
        if status != "HARVESTED":
            raise ApiError(E.ERR_INVALID_STATE, 409,
                           "Only a HARVESTED event can be reconciled")
        bad_dists = [d for d in svc.distributions_of_event(rid)
                     if d["status"] not in ("DELIVERED", "SHORTFALL", "CANCELLED")]
        if bad_dists:
            raise ApiError(E.ERR_INVALID_STATE, 409,
                           "Every distribution must be DELIVERED, SHORTFALL, or CANCELLED")
        bad_lots = [l for l in svc.lots_of_event(rid)
                    if l["status"] not in ("VERIFIED", "REJECTED")]
        if bad_lots:
            raise ApiError(E.ERR_INVALID_STATE, 409,
                           "Every harvest lot must be VERIFIED or REJECTED")
        # Gate 25: open-incident gate
        for i in svc.incidents_of_event(rid):
            if i["disposition"] == "OPEN":
                raise ApiError(E.ERR_INCIDENT_OPEN, 422,
                               "An OPEN food-safety incident blocks reconciliation")
        svc.recompute_event_totals(ev)
        for lot in svc.lots_of_event(rid):
            if lot["status"] == "VERIFIED":
                c = store.containers.get(lot["container_id"])
                if c is not None and c["status"] == "IN_USE":
                    c["status"] = "AVAILABLE"
                    touch(c)
        vehicle = store.vehicles.get(ev["assigned_vehicle_id"])
        if vehicle is not None and vehicle["status"] == "ASSIGNED":
            vehicle["status"] = "AVAILABLE"
            touch(vehicle)
        ev["status"] = "RECONCILED"
        touch(ev)
        offer = svc.offer_of_event(ev)
        if offer is not None:
            svc.reeval_offer_gleaned(offer)
        return ok_obj(serialize(ev))

    @app.route("/glean/events/<rid>/waivers", methods=["GET"])
    def list_event_waivers(rid):
        require_roles(PC, CL)
        svc.get_or_404(store.events, rid, "GleanEvent")
        waivers = [w for w in store.waivers.values() if w["glean_event_id"] == rid]
        page, limit, offset, total = svc.paginate(waivers)
        return ok_list([serialize(r) for r in page], limit, offset, total)

    # ---------------- Crew Assignments ----------------

    @app.route("/glean/assignments", methods=["POST"])
    def create_assignment():
        require_roles(PC, CL)
        fs = svc.FieldSet()
        glean_event_id = fs.req_str("glean_event_id")
        volunteer_id = fs.req_str("volunteer_id")
        svc.fk_or_404(store.events, glean_event_id, "GleanEvent")
        svc.fk_or_404(store.volunteers, volunteer_id, "Volunteer")
        fs.raise_if_bad()
        rec = {
            "glean_event_id": glean_event_id,
            "volunteer_id": volunteer_id,
            "status": "PENDING",
            "confirmed_at": None,
            "hours_worked": None,
        }
        stamp_new(rec)
        store.assignments[rec["id"]] = rec
        return ok_obj(serialize(rec), 201)

    @app.route("/glean/assignments", methods=["GET"])
    def list_assignments():
        require_roles(PC, CL)
        page, limit, offset, total = svc.paginate(
            store.assignments.values(),
            {"glean_event_id": request.args.get("glean_event_id"),
             "volunteer_id": request.args.get("volunteer_id")})
        return ok_list([serialize(r) for r in page], limit, offset, total)

    @app.route("/glean/assignments/<rid>", methods=["GET"])
    def get_assignment(rid):
        require_roles(PC, CL)
        a = svc.get_or_404(store.assignments, rid, "CrewAssignment")
        return ok_obj(serialize(a))

    @app.route("/glean/assignments/<rid>/confirm", methods=["POST"])
    def confirm_assignment(rid):
        _, uid = require_roles(VOL)
        a = svc.get_or_404(store.assignments, rid, "CrewAssignment")
        if a["volunteer_id"] != uid:
            raise ApiError(E.ERR_UNAUTHORIZED, 403,
                           "A volunteer may only confirm their own assignment")
        status = a["status"]
        # Terminal-state lockdown dominates all later gates for the path target
        if status in TERMINAL_ASSIGNMENT:
            raise ApiError(E.ERR_ALREADY_TERMINAL, 409,
                           "Assignment is in terminal state %s" % status)
        ev = store.events.get(a["glean_event_id"])
        if status != "PENDING":
            raise ApiError(E.ERR_INVALID_STATE, 409,
                           "Only a PENDING assignment can be confirmed")
        if ev is None or ev["status"] not in ("OPEN", "FULL"):
            raise ApiError(E.ERR_INVALID_STATE, 409,
                           "The event must be OPEN or FULL to confirm")
        # Gate 9: volunteer double-booking
        if svc.volunteer_double_booked(uid, ev, exclude_assignment_id=a["id"]):
            raise ApiError(E.ERR_VOLUNTEER_DOUBLE_BOOKED, 422,
                           "Volunteer already holds a CONFIRMED assignment on an "
                           "overlapping event")
        # Gate 11: waiver presence
        if not svc.has_valid_waiver(uid, a["glean_event_id"]):
            raise ApiError(E.ERR_WAIVER_MISSING, 422,
                           "No witnessed waiver exists for this volunteer and event")
        # Gate 12: crew capacity
        if ev["crew_confirmed_count"] + 1 > ev["crew_capacity"]:
            raise ApiError(E.ERR_CREW_FULL, 422,
                           "Confirming would exceed the event's crew_capacity")
        # Gate 22: volunteer standing
        vol = store.volunteers.get(uid)
        if vol is None or vol["status"] != "ACTIVE":
            raise ApiError(E.ERR_VOLUNTEER_SUSPENDED, 422,
                           "A SUSPENDED volunteer cannot confirm an assignment")
        a["status"] = "CONFIRMED"
        a["confirmed_at"] = now()
        touch(a)
        svc.recompute_crew(ev)
        touch(ev)
        return ok_obj(serialize(a))

    @app.route("/glean/assignments/<rid>/decline", methods=["POST"])
    def decline_assignment(rid):
        _, uid = require_roles(VOL)
        a = svc.get_or_404(store.assignments, rid, "CrewAssignment")
        if a["volunteer_id"] != uid:
            raise ApiError(E.ERR_UNAUTHORIZED, 403,
                           "A volunteer may only decline their own assignment")
        status = a["status"]
        if status in TERMINAL_ASSIGNMENT:
            raise ApiError(E.ERR_ALREADY_TERMINAL, 409,
                           "Assignment is in terminal state %s" % status)
        ev = store.events.get(a["glean_event_id"])
        if status == "CONFIRMED":
            if ev is None or ev["status"] not in ("OPEN", "FULL"):
                raise ApiError(E.ERR_INVALID_STATE, 409,
                               "A CONFIRMED assignment can be declined only while "
                               "the event is OPEN or FULL")
        was_confirmed = status == "CONFIRMED"
        a["status"] = "DECLINED"
        touch(a)
        if was_confirmed and ev is not None:
            svc.recompute_crew(ev)
            touch(ev)
        return ok_obj(serialize(a))

    @app.route("/glean/assignments/<rid>/complete", methods=["POST"])
    def complete_assignment(rid):
        _, uid = require_roles(VOL)
        a = svc.get_or_404(store.assignments, rid, "CrewAssignment")
        if a["volunteer_id"] != uid:
            raise ApiError(E.ERR_UNAUTHORIZED, 403,
                           "A volunteer may only report hours on their own assignment")
        fs = svc.FieldSet()
        hours_worked = fs.req_num("hours_worked")
        status = a["status"]
        if status in TERMINAL_ASSIGNMENT:
            raise ApiError(E.ERR_ALREADY_TERMINAL, 409,
                           "Assignment is in terminal state %s" % status)
        if status != "CONFIRMED":
            raise ApiError(E.ERR_INVALID_STATE, 409,
                           "Only a CONFIRMED assignment can record hours")
        ev = store.events.get(a["glean_event_id"])
        if ev is None or ev["status"] != "IN_PROGRESS":
            raise ApiError(E.ERR_INVALID_STATE, 409,
                           "Hours can be recorded only while the event is IN_PROGRESS")
        if hours_worked is not None and hours_worked < 0:
            fs.bad = True
        fs.raise_if_bad()
        a["hours_worked"] = hours_worked
        touch(a)
        return ok_obj(serialize(a))

    # ---------------- Waivers ----------------

    @app.route("/glean/waivers", methods=["POST"])
    def create_waiver():
        require_roles(VOL)
        fs = svc.FieldSet()
        volunteer_id = fs.req_str("volunteer_id")
        glean_event_id = fs.req_str("glean_event_id")
        signature_payload = fs.req_str("signature_payload")
        witness_volunteer_id = fs.req_str("witness_volunteer_id")
        # Gate 3: body FK existence
        svc.fk_or_404(store.volunteers, volunteer_id, "Volunteer")
        svc.fk_or_404(store.events, glean_event_id, "GleanEvent")
        svc.fk_or_404(store.volunteers, witness_volunteer_id, "Volunteer")
        # Gate 6: segregation of duties — witness must differ from signer
        if (volunteer_id is not None and witness_volunteer_id is not None
                and volunteer_id == witness_volunteer_id):
            raise ApiError(E.ERR_SEGREGATION_OF_DUTIES, 422,
                           "The waiver witness must differ from the signer")
        fs.raise_if_bad()
        rec = {
            "volunteer_id": volunteer_id,
            "glean_event_id": glean_event_id,
            "signed_at": now(),
            "signature_payload": signature_payload,
            "witness_volunteer_id": witness_volunteer_id,
        }
        stamp_new(rec, mutable=False)
        store.waivers[rec["id"]] = rec
        return ok_obj(serialize(rec), 201)

    @app.route("/glean/waivers/<rid>", methods=["GET"])
    def get_waiver(rid):
        require_roles(PC)
        w = svc.get_or_404(store.waivers, rid, "Waiver")
        return ok_obj(serialize(w))

    # ---------------- Harvest Lots ----------------

    @app.route("/glean/lots", methods=["POST"])
    def create_lot():
        require_roles(CL)
        fs = svc.FieldSet()
        glean_event_id = fs.req_str("glean_event_id")
        container_id = fs.req_str("container_id")
        gross_lbs = fs.req_num("gross_lbs")
        tare_lbs = fs.opt_num("tare_lbs")
        cull_lbs = fs.req_num("cull_lbs")
        recorded_by_volunteer_id = fs.req_str("recorded_by_volunteer_id")
        # Gate 3: body FK existence
        ev = svc.fk_or_404(store.events, glean_event_id, "GleanEvent")
        container = svc.fk_or_404(store.containers, container_id, "Container")
        svc.fk_or_404(store.volunteers, recorded_by_volunteer_id, "Volunteer")
        # Gate 4: lots are recorded while the event is IN_PROGRESS
        if ev is not None and ev["status"] != "IN_PROGRESS":
            raise ApiError(E.ERR_INVALID_STATE, 409,
                           "Harvest lots can be recorded only while the event is IN_PROGRESS")
        # Container must be AVAILABLE or already IN_USE by this event
        if ev is not None and container is not None:
            if container["status"] == "IN_USE":
                if not svc.container_in_use_by_event(container_id, glean_event_id):
                    raise ApiError(E.ERR_INVALID_STATE, 409,
                                   "Container is IN_USE by another event")
            elif container["status"] != "AVAILABLE":
                raise ApiError(E.ERR_INVALID_STATE, 409,
                               "Container is not AVAILABLE")
        # Resolve tare (defaults to the container's tare_lbs), round inputs to 1dp
        gross_r = dec1(gross_lbs) if gross_lbs is not None else None
        if tare_lbs is None and container is not None:
            tare_r = container["tare_lbs"]
        elif tare_lbs is not None:
            tare_r = dec1(tare_lbs)
        else:
            tare_r = None
        cull_r = dec1(cull_lbs) if cull_lbs is not None else None
        # Gate 15: cull sanity — cull_lbs <= gross_lbs - tare_lbs
        if gross_r is not None and tare_r is not None and cull_r is not None:
            if cull_r > gross_r - tare_r:
                raise ApiError(E.ERR_CULL_EXCEEDS_NET, 422,
                               "cull_lbs exceeds gross_lbs minus tare_lbs")
        # Gate 26: request shape
        if gross_lbs is not None and gross_lbs <= 0:
            fs.bad = True
        if cull_lbs is not None and cull_lbs < 0:
            fs.bad = True
        if tare_lbs is not None and tare_lbs < 0:
            fs.bad = True
        fs.raise_if_bad()
        rec = {
            "glean_event_id": glean_event_id,
            "container_id": container_id,
            "gross_lbs": gross_r,
            "tare_lbs": tare_r,
            "cull_lbs": cull_r,
            "net_lbs": gross_r - tare_r - cull_r,
            "recorded_by_volunteer_id": recorded_by_volunteer_id,
            "verified_by_coordinator_id": None,
            "status": "PENDING",
        }
        stamp_new(rec)
        store.lots[rec["id"]] = rec
        return ok_obj(serialize(rec), 201)

    @app.route("/glean/lots", methods=["GET"])
    def list_lots():
        require_roles(PC, CL, FSO)
        page, limit, offset, total = svc.paginate(
            store.lots.values(),
            {"glean_event_id": request.args.get("glean_event_id"),
             "container_id": request.args.get("container_id"),
             "recorded_by_volunteer_id": request.args.get("recorded_by_volunteer_id"),
             "verified_by_coordinator_id": request.args.get("verified_by_coordinator_id")})
        return ok_list([serialize(r) for r in page], limit, offset, total)

    @app.route("/glean/lots/<rid>", methods=["GET"])
    def get_lot(rid):
        require_roles(PC, CL, FSO)
        lot = svc.get_or_404(store.lots, rid, "HarvestLot")
        return ok_obj(serialize(lot))

    @app.route("/glean/lots/<rid>/verify", methods=["POST"])
    def verify_lot(rid):
        require_roles(PC)
        lot = svc.get_or_404(store.lots, rid, "HarvestLot")
        fs = svc.FieldSet()
        verified_by_coordinator_id = fs.req_str("verified_by_coordinator_id")
        # Gate 3: body FK existence
        svc.fk_or_404(store.volunteers, verified_by_coordinator_id, "Volunteer")
        status = lot["status"]
        # Terminal-state lockdown dominates all later gates for the path target
        if status in TERMINAL_LOT:
            raise ApiError(E.ERR_ALREADY_TERMINAL, 409,
                           "Lot is in terminal state %s" % status)
        ev = store.events.get(lot["glean_event_id"])
        # Gate 4: state compatibility
        if status != "PENDING":
            raise ApiError(E.ERR_INVALID_STATE, 409,
                           "Only a PENDING lot can be verified")
        if ev is not None and ev["status"] != "IN_PROGRESS":
            raise ApiError(E.ERR_INVALID_STATE, 409,
                           "The event must be IN_PROGRESS to verify a lot")
        # Gate 6: segregation of duties
        if (verified_by_coordinator_id is not None
                and verified_by_coordinator_id == lot["recorded_by_volunteer_id"]):
            raise ApiError(E.ERR_SEGREGATION_OF_DUTIES, 422,
                           "Verifier must differ from the recorder")
        # Gate 16: vehicle payload — VERIFIED net sum including this lot may not
        # exceed the vehicle's payload capacity (equality allowed)
        if ev is not None:
            vehicle = store.vehicles.get(ev["assigned_vehicle_id"])
            if vehicle is not None:
                projected = svc.dsum([l["net_lbs"] for l in svc.lots_of_event(ev["id"])
                                      if l["status"] == "VERIFIED"] + [lot["net_lbs"]])
                if projected > vehicle["payload_capacity_lbs"]:
                    raise ApiError(E.ERR_VEHICLE_PAYLOAD_EXCEEDED, 422,
                                   "Verifying this lot would exceed the vehicle's "
                                   "payload capacity")
        fs.raise_if_bad()
        lot["status"] = "VERIFIED"
        lot["verified_by_coordinator_id"] = verified_by_coordinator_id
        touch(lot)
        container = store.containers.get(lot["container_id"])
        if container is not None and container["status"] == "AVAILABLE":
            container["status"] = "IN_USE"
            touch(container)
        if ev is not None:
            svc.recompute_event_totals(ev)
            touch(ev)
            offer = svc.offer_of_event(ev)
            if offer is not None and svc.recompute_offer_actual(offer):
                touch(offer)
        return ok_obj(serialize(lot))

    @app.route("/glean/lots/<rid>/reject", methods=["POST"])
    def reject_lot(rid):
        require_roles(PC)
        lot = svc.get_or_404(store.lots, rid, "HarvestLot")
        status = lot["status"]
        if status in TERMINAL_LOT:
            raise ApiError(E.ERR_ALREADY_TERMINAL, 409,
                           "Lot is in terminal state %s" % status)
        ev = store.events.get(lot["glean_event_id"])
        if ev is None or ev["status"] != "IN_PROGRESS":
            raise ApiError(E.ERR_INVALID_STATE, 409,
                           "The event must be IN_PROGRESS to reject a lot")
        lot["status"] = "REJECTED"
        touch(lot)
        return ok_obj(serialize(lot))
