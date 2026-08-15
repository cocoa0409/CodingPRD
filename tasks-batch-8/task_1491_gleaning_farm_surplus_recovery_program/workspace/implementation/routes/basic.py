"""Farms, volunteers, agencies, containers, vehicles."""
from decimal import Decimal

import errors as E
import services as svc
from db import store, stamp_new, touch
from errors import ApiError
from middleware import require_roles
from response import ok_obj, ok_list
from util import serialize, dec1

PC = "ProgramCoordinator"
CL = "CrewLeader"
FSO = "FoodSafetyOfficer"
GR = "GrantReviewer"


def register(app):

    # ---------------- Farms ----------------

    @app.route("/glean/farms", methods=["POST"])
    def create_farm():
        require_roles(PC)
        fs = svc.FieldSet()
        farm_name = fs.req_str("farm_name")
        contact_email = fs.req_str("contact_email")
        county_code = fs.req_str("county_code")
        donor_tin = fs.req_str("donor_tin")
        active_flag = fs.opt_bool("active_flag", True)
        fs.raise_if_bad()
        rec = {
            "farm_name": farm_name,
            "contact_email": contact_email,
            "county_code": county_code,
            "donor_tin": donor_tin,
            "active_flag": active_flag,
            "lifetime_donated_lbs": Decimal("0.0"),
        }
        stamp_new(rec)
        store.farms[rec["id"]] = rec
        return ok_obj(serialize(rec), 201)

    @app.route("/glean/farms", methods=["GET"])
    def list_farms():
        require_roles(PC, GR, FSO)
        page, limit, offset, total = svc.paginate(
            store.farms.values(),
            {"county_code": svc.request.args.get("county_code")})
        return ok_list([serialize(r) for r in page], limit, offset, total)

    @app.route("/glean/farms/<rid>", methods=["GET"])
    def get_farm(rid):
        require_roles(PC, GR)
        farm = svc.get_or_404(store.farms, rid, "Farm")
        return ok_obj(serialize(farm))

    @app.route("/glean/farms/<rid>/offers", methods=["GET"])
    def list_farm_offers(rid):
        require_roles(PC, GR)
        svc.get_or_404(store.farms, rid, "Farm")
        offers = [o for o in store.offers.values() if o["farm_id"] == rid]
        page, limit, offset, total = svc.paginate(offers)
        return ok_list([serialize(r) for r in page], limit, offset, total)

    @app.route("/glean/farms/<rid>/receipts", methods=["GET"])
    def list_farm_receipts(rid):
        require_roles(PC, GR)
        svc.get_or_404(store.farms, rid, "Farm")
        receipts = [r for r in store.receipts.values() if r["farm_id"] == rid]
        page, limit, offset, total = svc.paginate(receipts)
        return ok_list([serialize(r) for r in page], limit, offset, total)

    # ---------------- Volunteers ----------------

    @app.route("/glean/volunteers", methods=["POST"])
    def create_volunteer():
        require_roles(PC)
        fs = svc.FieldSet()
        full_name = fs.req_str("full_name")
        email = fs.req_str("email")
        crew_leader_certified = fs.opt_bool("crew_leader_certified", False)
        # Gate 18 (uniqueness) precedes gate 26 (request shape)
        if isinstance(email, str):
            for v in store.volunteers.values():
                if v["email"] == email:
                    raise ApiError(E.ERR_DUPLICATE, 409,
                                   "A volunteer with this email already exists")
        fs.raise_if_bad()
        rec = {
            "full_name": full_name,
            "email": email,
            "crew_leader_certified": crew_leader_certified,
            "status": "ACTIVE",
            "no_show_count": 0,
        }
        stamp_new(rec)
        store.volunteers[rec["id"]] = rec
        return ok_obj(serialize(rec), 201)

    @app.route("/glean/volunteers", methods=["GET"])
    def list_volunteers():
        require_roles(PC)
        page, limit, offset, total = svc.paginate(
            store.volunteers.values(),
            {"email": svc.request.args.get("email")})
        return ok_list([serialize(r) for r in page], limit, offset, total)

    @app.route("/glean/volunteers/<rid>", methods=["GET"])
    def get_volunteer(rid):
        require_roles(PC)
        vol = svc.get_or_404(store.volunteers, rid, "Volunteer")
        return ok_obj(serialize(vol))

    @app.route("/glean/volunteers/<rid>/reinstate", methods=["POST"])
    def reinstate_volunteer(rid):
        require_roles(PC)
        vol = svc.get_or_404(store.volunteers, rid, "Volunteer")
        if vol["status"] != "SUSPENDED":
            raise ApiError(E.ERR_INVALID_STATE, 409,
                           "Only a SUSPENDED volunteer can be reinstated")
        vol["status"] = "ACTIVE"
        vol["no_show_count"] = 0
        touch(vol)
        return ok_obj(serialize(vol))

    @app.route("/glean/volunteers/<rid>/waivers", methods=["GET"])
    def list_volunteer_waivers(rid):
        require_roles(PC)
        svc.get_or_404(store.volunteers, rid, "Volunteer")
        waivers = [w for w in store.waivers.values() if w["volunteer_id"] == rid]
        page, limit, offset, total = svc.paginate(waivers)
        return ok_list([serialize(r) for r in page], limit, offset, total)

    # ---------------- Agencies ----------------

    def serialize_agency(a):
        # current_week_committed_lbs tracks the ISO week of the logical clock
        out = dict(a)
        out["current_week_committed_lbs"] = svc.agency_current_week_committed(a["id"])
        return serialize(out)

    @app.route("/glean/agencies", methods=["POST"])
    def create_agency():
        require_roles(PC)
        fs = svc.FieldSet()
        agency_name = fs.req_str("agency_name")
        county_code = fs.req_str("county_code")
        weekly_capacity_lbs = fs.req_num("weekly_capacity_lbs")
        refrigeration_capable = fs.req_bool("refrigeration_capable")
        active_flag = fs.opt_bool("active_flag", True)
        if weekly_capacity_lbs is not None and weekly_capacity_lbs <= 0:
            fs.bad = True
        fs.raise_if_bad()
        rec = {
            "agency_name": agency_name,
            "county_code": county_code,
            "weekly_capacity_lbs": dec1(weekly_capacity_lbs),
            "refrigeration_capable": refrigeration_capable,
            "active_flag": active_flag,
            "current_week_committed_lbs": Decimal("0.0"),
        }
        stamp_new(rec)
        store.agencies[rec["id"]] = rec
        return ok_obj(serialize_agency(rec), 201)

    @app.route("/glean/agencies", methods=["GET"])
    def list_agencies():
        require_roles(PC, GR)
        page, limit, offset, total = svc.paginate(
            store.agencies.values(),
            {"county_code": svc.request.args.get("county_code")})
        return ok_list([serialize_agency(r) for r in page], limit, offset, total)

    @app.route("/glean/agencies/<rid>", methods=["GET"])
    def get_agency(rid):
        require_roles(PC, GR)
        agency = svc.get_or_404(store.agencies, rid, "Agency")
        return ok_obj(serialize_agency(agency))

    @app.route("/glean/agencies/<rid>/distributions", methods=["GET"])
    def list_agency_distributions(rid):
        require_roles(PC, GR)
        svc.get_or_404(store.agencies, rid, "Agency")
        dists = [d for d in store.distributions.values() if d["agency_id"] == rid]
        page, limit, offset, total = svc.paginate(dists)
        return ok_list([serialize(r) for r in page], limit, offset, total)

    # ---------------- Containers ----------------

    @app.route("/glean/containers", methods=["POST"])
    def create_container():
        require_roles(PC)
        fs = svc.FieldSet()
        label = fs.req_str("label")
        tare_lbs = fs.req_num("tare_lbs")
        capacity_lbs = fs.req_num("capacity_lbs")
        refrigerated = fs.req_bool("refrigerated")
        if isinstance(label, str):
            for c in store.containers.values():
                if c["label"] == label:
                    raise ApiError(E.ERR_DUPLICATE, 409,
                                   "A container with this label already exists")
        if tare_lbs is not None and tare_lbs <= 0:
            fs.bad = True
        if capacity_lbs is not None and capacity_lbs <= 0:
            fs.bad = True
        fs.raise_if_bad()
        rec = {
            "label": label,
            "tare_lbs": dec1(tare_lbs),
            "capacity_lbs": dec1(capacity_lbs),
            "refrigerated": refrigerated,
            "status": "AVAILABLE",
        }
        stamp_new(rec)
        store.containers[rec["id"]] = rec
        return ok_obj(serialize(rec), 201)

    @app.route("/glean/containers", methods=["GET"])
    def list_containers():
        require_roles(PC, CL)
        page, limit, offset, total = svc.paginate(store.containers.values())
        return ok_list([serialize(r) for r in page], limit, offset, total)

    @app.route("/glean/containers/<rid>", methods=["GET"])
    def get_container(rid):
        require_roles(PC, CL)
        c = svc.get_or_404(store.containers, rid, "Container")
        return ok_obj(serialize(c))

    # ---------------- Vehicles ----------------

    @app.route("/glean/vehicles", methods=["POST"])
    def create_vehicle():
        require_roles(PC)
        fs = svc.FieldSet()
        plate = fs.req_str("plate")
        payload_capacity_lbs = fs.req_num("payload_capacity_lbs")
        refrigerated = fs.req_bool("refrigerated")
        if isinstance(plate, str):
            for v in store.vehicles.values():
                if v["plate"] == plate:
                    raise ApiError(E.ERR_DUPLICATE, 409,
                                   "A vehicle with this plate already exists")
        if payload_capacity_lbs is not None and payload_capacity_lbs <= 0:
            fs.bad = True
        fs.raise_if_bad()
        rec = {
            "plate": plate,
            "payload_capacity_lbs": dec1(payload_capacity_lbs),
            "refrigerated": refrigerated,
            "status": "AVAILABLE",
        }
        stamp_new(rec)
        store.vehicles[rec["id"]] = rec
        return ok_obj(serialize(rec), 201)

    @app.route("/glean/vehicles", methods=["GET"])
    def list_vehicles():
        require_roles(PC, CL)
        page, limit, offset, total = svc.paginate(store.vehicles.values())
        return ok_list([serialize(r) for r in page], limit, offset, total)

    @app.route("/glean/vehicles/<rid>", methods=["GET"])
    def get_vehicle(rid):
        require_roles(PC, CL)
        v = svc.get_or_404(store.vehicles, rid, "Vehicle")
        return ok_obj(serialize(v))
