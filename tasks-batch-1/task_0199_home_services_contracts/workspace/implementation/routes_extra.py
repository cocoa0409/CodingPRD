"""Membership, RenewalOffer, ServiceVisit, RefrigerantLog, PartUsage,
WarrantyClaim, and administrative clock routes.

Validation precedence (PRD §2.9) is respected in each handler:
auth -> authz -> ownership -> existence -> body -> domain business rules.
"""
from flask import request

import db
import lookups as L
import models
import services as S
from common import (
    get_body, pagination, paginate, sort_by_created, parse_iso, parse_dt,
    req_int, opt_int, req_str, opt_str, req_enum, opt_bool,
)
from errors import err
from middleware import authenticate, authorize
from response import ok, created, listing

VISIT_KINDS = {"SEASONAL", "PRIORITY", "WARRANTY"}
REFRIG_ACTIONS = {"ADD", "RECOVER"}

# Visit statuses cascade-cancelled by membership suspend (PRD §3.3)
SUSPEND_CANCEL_STATES = {"SCHEDULED", "DISPATCHED"}
# Visit statuses cascade-cancelled by membership cancel (PRD §3.3)
CANCEL_CANCEL_STATES = {"SCHEDULED", "DISPATCHED", "EN_ROUTE"}


def register(app, PREFIX):

    def _auth(allowed_roles):
        user_id, role = authenticate()
        authorize(role, allowed_roles)
        return user_id, role

    def _list_response(rows, serialize_fn):
        limit, offset = pagination()
        rows = sort_by_created(rows)
        page, total = paginate(rows, limit, offset)
        return listing([serialize_fn(r) for r in page], limit, offset, total)

    # =======================================================================
    # Membership
    # =======================================================================
    @app.route(PREFIX + "/memberships", methods=["POST"])
    def create_membership():
        _auth(["ContractAdmin"])
        body = get_body()
        customer_id = req_str(body, "customer_id")
        site_id = req_str(body, "site_id")
        plan_id = req_str(body, "plan_id")
        # existence (priority 4), left-to-right as listed in input
        customer = L.customer(customer_id)
        site = L.site(site_id)
        plan = L.plan(plan_id)
        auto_renew = opt_bool(body, "auto_renew", default=plan["auto_renew_default"])
        # priority 6: site.customer_id == body.customer_id
        if site["customer_id"] != customer_id:
            raise err("ERR_SITE_OWNER_MISMATCH",
                      "Site does not belong to the named customer")
        rec = models.new_record("Membership", {
            "customer_id": customer_id, "site_id": site_id, "plan_id": plan_id,
            "status": "PENDING_ACTIVATION", "auto_renew": auto_renew,
            "term_start": None, "term_end": None, "visits_consumed": 0,
            "term_index": 1,
        })
        db.memberships[rec["id"]] = rec
        return created(S.membership_view(rec))

    @app.route(PREFIX + "/memberships/<mid>", methods=["GET"])
    def get_membership(mid):
        user_id, role = _auth(["ContractAdmin", "Customer"])
        rec = L.membership(mid)
        if role == "Customer":
            L.require_customer_owns(user_id, rec["customer_id"])
        return ok(S.membership_view(rec))

    @app.route(PREFIX + "/memberships", methods=["GET"])
    def list_memberships():
        user_id, role = _auth(["ContractAdmin", "Customer"])
        rows = list(db.memberships.values())
        for field in ("customer_id", "site_id", "plan_id", "status"):
            val = request.args.get(field)
            if val is not None:
                rows = [r for r in rows if r[field] == val]
        if role == "Customer":
            rows = [r for r in rows if r["customer_id"] == user_id]
        return _list_response(rows, S.membership_view)

    @app.route(PREFIX + "/memberships/<mid>/activate", methods=["POST"])
    def activate_membership(mid):
        _auth(["ContractAdmin"])
        m = L.membership(mid)
        if m["status"] != "PENDING_ACTIVATION":
            raise err("ERR_INVALID_STATE", "Membership is not PENDING_ACTIVATION")
        plan = db.service_plans[m["plan_id"]]
        if not plan["active"]:
            # PRD §3.3: plan must be active to activate against it.
            raise err("ERR_INVALID_STATE", "Referenced plan is not active")
        S.begin_first_term(m)
        customer = db.customers[m["customer_id"]]
        customer["billing_balance_cents"] += plan["annual_fee_cents"]
        models.touch(customer)
        m["status"] = "ACTIVE"
        models.touch(m)
        return ok(S.membership_view(m))

    @app.route(PREFIX + "/memberships/<mid>/suspend", methods=["POST"])
    def suspend_membership(mid):
        _auth(["ContractAdmin"])
        m = L.membership(mid)
        if m["status"] != "ACTIVE":
            raise err("ERR_INVALID_STATE", "Membership is not ACTIVE")
        _cascade_cancel_visits(m, SUSPEND_CANCEL_STATES)
        m["status"] = "SUSPENDED"
        models.touch(m)
        return ok(S.membership_view(m))

    @app.route(PREFIX + "/memberships/<mid>/reinstate", methods=["POST"])
    def reinstate_membership(mid):
        _auth(["ContractAdmin"])
        m = L.membership(mid)
        if m["status"] != "SUSPENDED":
            raise err("ERR_INVALID_STATE", "Membership is not SUSPENDED")
        m["status"] = "ACTIVE"
        models.touch(m)
        return ok(S.membership_view(m))

    @app.route(PREFIX + "/memberships/<mid>/cancel", methods=["POST"])
    def cancel_membership(mid):
        user_id, role = _auth(["Customer", "ContractAdmin"])
        m = L.membership(mid)
        if role == "Customer":
            L.require_customer_owns(user_id, m["customer_id"])
        if m["status"] not in ("ACTIVE", "SUSPENDED", "RENEWAL_PENDING"):
            raise err("ERR_INVALID_STATE", "Membership cannot be cancelled from its state")
        _cascade_cancel_visits(m, CANCEL_CANCEL_STATES)
        # expire any PENDING renewal offer for this membership
        for o in db.renewal_offers.values():
            if o["membership_id"] == m["id"] and o["status"] == "PENDING":
                o["status"] = "EXPIRED"
                models.touch(o)
        m["status"] = "CANCELLED"
        models.touch(m)
        return ok(S.membership_view(m))

    def _cascade_cancel_visits(m, states):
        for v in db.service_visits.values():
            if v["membership_id"] != m["id"]:
                continue
            if v["status"] in states:
                # cancellation clears technician_id (PRD §3.5)
                if v["status"] in ("DISPATCHED", "EN_ROUTE"):
                    v["technician_id"] = None
                v["status"] = "CANCELLED"
                models.touch(v)

    # =======================================================================
    # RenewalOffer
    # =======================================================================
    @app.route(PREFIX + "/memberships/<mid>/renewal-offers", methods=["POST"])
    def create_offer(mid):
        _auth(["ContractAdmin"])
        m = L.membership(mid)
        body = get_body()
        offered_plan_id = req_str(body, "offered_plan_id")
        expires_at = parse_dt(body, "expires_at", required=True)
        expected_version = req_int(body, "expected_membership_version")
        offered_plan = L.plan(offered_plan_id)  # existence
        # no open offer: a PENDING offer always coexists with a
        # RENEWAL_PENDING membership, so this guard must precede the ACTIVE
        # gate for the enumerated PENDING case to yield ERR_OFFER_ALREADY_OPEN.
        for o in db.renewal_offers.values():
            if o["membership_id"] == m["id"] and o["status"] in (
                "PENDING", "ACCEPTED", "AUTO_ACCEPTED"
            ):
                raise err("ERR_OFFER_ALREADY_OPEN",
                          "An open renewal offer already exists")
        # state gate: membership must be ACTIVE
        if m["status"] != "ACTIVE":
            raise err("ERR_INVALID_STATE", "Membership is not ACTIVE")
        # priority 21: OCC stale-version guard
        if expected_version != m["version"]:
            raise err("ERR_STALE_VERSION", "Membership version is stale")
        offer = models.new_record("RenewalOffer", {
            "membership_id": m["id"], "offered_plan_id": offered_plan_id,
            "status": "PENDING",
            "offered_annual_fee_cents": offered_plan["annual_fee_cents"],
            "expires_at": db.iso(expires_at),
        })
        db.renewal_offers[offer["id"]] = offer
        m["status"] = "RENEWAL_PENDING"
        models.touch(m)
        return created(models.serialize(offer))

    @app.route(PREFIX + "/memberships/<mid>/renewal-offers", methods=["GET"])
    def list_membership_offers(mid):
        user_id, role = _auth(["ContractAdmin", "Customer"])
        m = L.membership(mid)
        if role == "Customer":
            L.require_customer_owns(user_id, m["customer_id"])
        rows = [o for o in db.renewal_offers.values()
                if o["membership_id"] == mid]
        status = request.args.get("status")
        if status is not None:
            rows = [r for r in rows if r["status"] == status]
        return _list_response(rows, models.serialize)

    @app.route(PREFIX + "/memberships/<mid>/service-visits", methods=["GET"])
    def list_membership_visits(mid):
        user_id, role = _auth(["ContractAdmin", "Dispatcher", "Customer"])
        m = L.membership(mid)
        if role == "Customer":
            L.require_customer_owns(user_id, m["customer_id"])
        rows = [v for v in db.service_visits.values()
                if v["membership_id"] == mid]
        status = request.args.get("status")
        visit_kind = request.args.get("visit_kind")
        if status is not None:
            rows = [r for r in rows if r["status"] == status]
        if visit_kind is not None:
            rows = [r for r in rows if r["visit_kind"] == visit_kind]
        return _list_response(rows, models.serialize)

    @app.route(PREFIX + "/renewal-offers/<oid>", methods=["GET"])
    def get_offer(oid):
        user_id, role = _auth(["ContractAdmin", "Customer"])
        o = L.offer(oid)
        if role == "Customer":
            L.require_customer_owns(user_id, L.owner_customer_id_of_offer(o))
        return ok(models.serialize(o))

    @app.route(PREFIX + "/renewal-offers", methods=["GET"])
    def list_offers():
        user_id, role = _auth(["ContractAdmin", "Customer"])
        rows = list(db.renewal_offers.values())
        for field in ("membership_id", "offered_plan_id", "status"):
            val = request.args.get(field)
            if val is not None:
                rows = [r for r in rows if r[field] == val]
        if role == "Customer":
            rows = [r for r in rows
                    if L.owner_customer_id_of_offer(r) == user_id]
        return _list_response(rows, models.serialize)

    @app.route(PREFIX + "/renewal-offers/<oid>/accept", methods=["POST"])
    def accept_offer(oid):
        user_id, role = _auth(["Customer"])
        o = L.offer(oid)
        m = db.memberships[o["membership_id"]]
        L.require_customer_owns(user_id, m["customer_id"])
        # state gate (priority 8): offer must be PENDING
        if o["status"] != "PENDING" or m["status"] != "RENEWAL_PENDING":
            raise err("ERR_INVALID_STATE", "Offer is not acceptable in its state")
        # priority 18: current clock < expires_at
        if db.get_clock() >= parse_iso(o["expires_at"]):
            raise err("ERR_OFFER_EXPIRED", "Offer has expired")
        S.accept_offer(o, m, auto=False)
        return ok(models.serialize(o))

    @app.route(PREFIX + "/renewal-offers/<oid>/decline", methods=["POST"])
    def decline_offer(oid):
        user_id, role = _auth(["Customer"])
        o = L.offer(oid)
        m = db.memberships[o["membership_id"]]
        L.require_customer_owns(user_id, m["customer_id"])
        if o["status"] != "PENDING" or m["status"] != "RENEWAL_PENDING":
            raise err("ERR_INVALID_STATE", "Offer is not declinable in its state")
        if db.get_clock() >= parse_iso(o["expires_at"]):
            raise err("ERR_OFFER_EXPIRED", "Offer has expired")
        S.lapse_offer(o, m, expired=False)
        return ok(models.serialize(o))

    # =======================================================================
    # ServiceVisit
    # =======================================================================
    @app.route(PREFIX + "/service-visits", methods=["POST"])
    def create_visit():
        _auth(["Dispatcher", "ContractAdmin"])
        body = get_body()
        membership_id = req_str(body, "membership_id")
        visit_kind = req_enum(body, "visit_kind", VISIT_KINDS)
        requested_at = parse_dt(body, "requested_at", required=True)
        window_start = parse_dt(body, "window_start", required=True)
        window_end = parse_dt(body, "window_end", required=True)
        technician_id = body.get("technician_id")
        expected_version = req_int(body, "expected_membership_version")
        # existence (priority 4)
        m = L.membership(membership_id)
        tech = None
        if technician_id is not None:
            if not isinstance(technician_id, str):
                raise err("ERR_INVALID_REQUEST", "technician_id must be a string")
            tech = L.technician(technician_id)
        # priority 7: membership must be ACTIVE
        if m["status"] != "ACTIVE":
            raise err("ERR_MEMBERSHIP_NOT_ACTIVE", "Membership is not ACTIVE")
        # priority 13: window_end > window_start
        if not (window_end > window_start):
            raise err("ERR_INVALID_WINDOW", "window_end must be after window_start")
        # priority 16: PRIORITY requested_at <= window_start
        if visit_kind == "PRIORITY" and requested_at > window_start:
            raise err("ERR_INVALID_WINDOW",
                      "requested_at may not fall after window_start")
        # priority 15: daily capacity on the visit's window_start calendar date
        if tech is not None:
            _check_daily_capacity(tech, window_start, exclude_visit_id=None)
        # priority 21: OCC stale-version guard
        if expected_version != m["version"]:
            raise err("ERR_STALE_VERSION", "Membership version is stale")

        plan = db.service_plans[m["plan_id"]]
        rec = models.new_record("ServiceVisit", {
            "membership_id": membership_id, "site_id": m["site_id"],
            "technician_id": technician_id, "visit_kind": visit_kind,
            "status": "SCHEDULED", "requested_at": db.iso(requested_at),
            "window_start": db.iso(window_start), "window_end": db.iso(window_end),
            "sla_met": None, "billable_charge_cents": 0,
        })
        S.evaluate_sla(rec, plan)
        db.service_visits[rec["id"]] = rec
        return created(models.serialize(rec))

    @app.route(PREFIX + "/service-visits/<vid>", methods=["GET"])
    def get_visit(vid):
        user_id, role = _auth(["ContractAdmin", "Dispatcher", "Customer", "Technician"])
        v = L.visit(vid)
        if role == "Customer":
            L.require_customer_owns(user_id, L.owner_customer_id_of_visit(v))
        return ok(models.serialize(v))

    @app.route(PREFIX + "/service-visits", methods=["GET"])
    def list_visits():
        _auth(["ContractAdmin", "Dispatcher", "Technician"])
        rows = list(db.service_visits.values())
        for field in ("membership_id", "technician_id", "site_id", "status", "visit_kind"):
            val = request.args.get(field)
            if val is not None:
                rows = [r for r in rows if r.get(field) == val]
        return _list_response(rows, models.serialize)

    @app.route(PREFIX + "/service-visits/<vid>/reschedule", methods=["POST"])
    def reschedule_visit(vid):
        _auth(["Dispatcher"])
        v = L.visit(vid)
        body = get_body()
        window_start = parse_dt(body, "window_start", required=True)
        window_end = parse_dt(body, "window_end", required=True)
        if v["status"] != "SCHEDULED":
            raise err("ERR_INVALID_STATE", "Visit is not SCHEDULED")
        if not (window_end > window_start):
            raise err("ERR_INVALID_WINDOW", "window_end must be after window_start")
        # re-run capacity check under the new window (PRD §3.5/§3.6)
        if v["technician_id"] is not None:
            tech = db.technicians[v["technician_id"]]
            _check_daily_capacity(tech, window_start, exclude_visit_id=v["id"])
        v["window_start"] = db.iso(window_start)
        v["window_end"] = db.iso(window_end)
        m = db.memberships[v["membership_id"]]
        plan = db.service_plans[m["plan_id"]]
        S.evaluate_sla(v, plan)
        models.touch(v)
        return ok(models.serialize(v))

    @app.route(PREFIX + "/service-visits/<vid>/dispatch", methods=["POST"])
    def dispatch_visit(vid):
        _auth(["Dispatcher"])
        v = L.visit(vid)
        body = get_body()
        technician_id = req_str(body, "technician_id")
        tech = L.technician(technician_id)  # existence
        if v["status"] != "SCHEDULED":
            raise err("ERR_INVALID_STATE", "Visit is not SCHEDULED")
        m = db.memberships[v["membership_id"]]
        plan = db.service_plans[m["plan_id"]]
        site = db.sites[v["site_id"]]
        # priority 12: region/trade match
        if tech["region_code"] != site["region_code"] or tech["trade"] != plan["trade"]:
            raise err("ERR_TECH_REGION_TRADE_MISMATCH",
                      "Technician region/trade mismatch")
        # priority 14: half-open overlap with this tech's DISPATCHED/EN_ROUTE/ON_SITE
        _check_overlap(tech, v)
        # priority 15: daily capacity on window_start calendar date
        _check_daily_capacity(tech, parse_iso(v["window_start"]),
                              exclude_visit_id=v["id"])
        v["technician_id"] = technician_id
        v["status"] = "DISPATCHED"
        models.touch(v)
        return ok(models.serialize(v))

    @app.route(PREFIX + "/service-visits/<vid>/recall", methods=["POST"])
    def recall_visit(vid):
        _auth(["Dispatcher"])
        v = L.visit(vid)
        if v["status"] != "DISPATCHED":
            raise err("ERR_INVALID_STATE", "Visit is not DISPATCHED")
        v["technician_id"] = None
        v["status"] = "SCHEDULED"
        models.touch(v)
        return ok(models.serialize(v))

    @app.route(PREFIX + "/service-visits/<vid>/depart", methods=["POST"])
    def depart_visit(vid):
        user_id, role = _auth(["Technician"])
        v = L.visit(vid)
        if v["status"] != "DISPATCHED":
            raise err("ERR_INVALID_STATE", "Visit is not DISPATCHED")
        _require_assigned_tech(user_id, v)
        v["status"] = "EN_ROUTE"
        models.touch(v)
        return ok(models.serialize(v))

    @app.route(PREFIX + "/service-visits/<vid>/arrive", methods=["POST"])
    def arrive_visit(vid):
        user_id, role = _auth(["Technician"])
        v = L.visit(vid)
        if v["status"] != "EN_ROUTE":
            raise err("ERR_INVALID_STATE", "Visit is not EN_ROUTE")
        _require_assigned_tech(user_id, v)
        v["status"] = "ON_SITE"
        models.touch(v)
        return ok(models.serialize(v))

    @app.route(PREFIX + "/service-visits/<vid>/complete", methods=["POST"])
    def complete_visit(vid):
        user_id, role = _auth(["Technician"])
        v = L.visit(vid)
        if v["status"] != "ON_SITE":
            raise err("ERR_INVALID_STATE", "Visit is not ON_SITE")
        _require_assigned_tech(user_id, v)
        m = db.memberships[v["membership_id"]]
        plan = db.service_plans[m["plan_id"]]
        # 1) charge assessment
        charge = S.assess_visit_charge(v, m, plan)
        v["billable_charge_cents"] = charge
        v["status"] = "COMPLETED"
        v["completed_at"] = db.iso(db.get_clock())
        if charge > 0:
            customer = db.customers[m["customer_id"]]
            customer["billing_balance_cents"] += charge
            models.touch(customer)
        # 3) deep-recovery equipment cascade for units that received a RECOVER
        #    on this visit and fell below 10% of nameplate.
        recovered_equipment_ids = set()
        for log in db.refrigerant_logs.values():
            if log["visit_id"] == v["id"] and log["action"] == "RECOVER":
                recovered_equipment_ids.add(log["equipment_id"])
        for eid in recovered_equipment_ids:
            equip = db.equipment.get(eid)
            if equip is None:
                continue
            if equip["operational_status"] == "OPERATIONAL" and S.is_below_low_charge(equip):
                equip["operational_status"] = "NEEDS_SERVICE"
                models.touch(equip)
        models.touch(v)  # version bump after the coordinated effects
        return ok(models.serialize(v))

    @app.route(PREFIX + "/service-visits/<vid>/cancel", methods=["POST"])
    def cancel_visit(vid):
        _auth(["Dispatcher", "ContractAdmin"])
        v = L.visit(vid)
        if v["status"] not in ("SCHEDULED", "DISPATCHED", "EN_ROUTE"):
            raise err("ERR_INVALID_STATE", "Visit cannot be cancelled from its state")
        if v["status"] in ("DISPATCHED", "EN_ROUTE"):
            v["technician_id"] = None
        v["status"] = "CANCELLED"
        models.touch(v)
        return ok(models.serialize(v))

    @app.route(PREFIX + "/service-visits/<vid>/mark-no-show", methods=["POST"])
    def mark_no_show(vid):
        _auth(["Dispatcher"])
        v = L.visit(vid)
        if v["status"] != "DISPATCHED":
            raise err("ERR_INVALID_STATE", "Visit is not DISPATCHED")
        # PRD §3.5: only once clock >= window_end
        if db.get_clock() < parse_iso(v["window_end"]):
            raise err("ERR_INVALID_STATE", "Window has not yet elapsed")
        v["status"] = "NO_SHOW"
        models.touch(v)
        return ok(models.serialize(v))

    def _require_assigned_tech(user_id, v):
        if v["technician_id"] != user_id:
            raise err("ERR_NOT_RESOURCE_OWNER",
                      "Technician is not assigned to this visit")

    def _check_overlap(tech, target_visit):
        ws = parse_iso(target_visit["window_start"])
        we = parse_iso(target_visit["window_end"])
        for other in db.service_visits.values():
            if other["id"] == target_visit["id"]:
                continue
            if other.get("technician_id") != tech["id"]:
                continue
            if other["status"] not in ("DISPATCHED", "EN_ROUTE", "ON_SITE"):
                continue
            ows = parse_iso(other["window_start"])
            owe = parse_iso(other["window_end"])
            # half-open overlap: intervals [ws,we) and [ows,owe) intersect
            if ws < owe and ows < we:
                raise err("ERR_TECH_DOUBLE_BOOKED",
                          "Window overlaps another visit for this technician")

    def _check_daily_capacity(tech, window_start_dt, exclude_visit_id):
        target_date = window_start_dt.date()
        count = 0
        for other in db.service_visits.values():
            if other["id"] == exclude_visit_id:
                continue
            if other.get("technician_id") != tech["id"]:
                continue
            if other["status"] not in ("SCHEDULED", "DISPATCHED"):
                continue
            if parse_iso(other["window_start"]).date() == target_date:
                count += 1
        if count + 1 > tech["daily_visit_capacity"]:
            raise err("ERR_TECH_DAILY_CAPACITY",
                      "Technician daily capacity exceeded")

    # =======================================================================
    # RefrigerantLog
    # =======================================================================
    @app.route(PREFIX + "/service-visits/<vid>/refrigerant-logs", methods=["POST"])
    def post_refrigerant_log(vid):
        user_id, role = _auth(["Technician"])
        v = L.visit(vid)
        body = get_body()
        equipment_id = req_str(body, "equipment_id")
        action = req_enum(body, "action", REFRIG_ACTIONS)
        grams = req_int(body, "grams")
        equip = L.equipment(equipment_id)  # existence
        # ownership: technician must be the assigned tech of the visit
        _require_assigned_tech(user_id, v)
        # priority 7: visit must be ON_SITE
        if v["status"] != "ON_SITE":
            raise err("ERR_MEMBERSHIP_NOT_ACTIVE", "Visit is not ON_SITE")
        # body rule: grams > 0
        if grams <= 0:
            raise err("ERR_INVALID_REQUEST", "grams must be > 0")
        # equipment.site_id must equal visit.site_id (PRD §3.7)
        if equip["site_id"] != v["site_id"]:
            raise err("ERR_INVALID_REQUEST",
                      "Equipment is not at the visit's site")
        # priority 9: assigned tech EPA certified
        tech = db.technicians[v["technician_id"]]
        if not tech["epa_certified"]:
            raise err("ERR_TECH_NOT_CERTIFIED",
                      "Technician is not EPA 608 certified")
        # priority 10: mass balance
        current = equip["current_charge_grams"]
        if action == "RECOVER":
            new_charge = current - grams
            if new_charge < 0:
                raise err("ERR_REFRIGERANT_BALANCE",
                          "RECOVER would drive charge below 0")
        else:  # ADD
            new_charge = current + grams
            if new_charge > equip["nameplate_charge_grams"]:
                raise err("ERR_REFRIGERANT_BALANCE",
                          "ADD would exceed nameplate charge")
        log = models.new_record("RefrigerantLog", {
            "visit_id": v["id"], "equipment_id": equipment_id,
            "action": action, "grams": grams,
            "posted_by_tech_id": v["technician_id"],
        })
        db.refrigerant_logs[log["id"]] = log
        equip["current_charge_grams"] = new_charge
        models.touch(equip)
        return created(models.serialize(log))

    @app.route(PREFIX + "/service-visits/<vid>/refrigerant-logs", methods=["GET"])
    def list_visit_refrigerant_logs(vid):
        _auth(["ContractAdmin", "Technician", "Dispatcher"])
        L.visit(vid)
        rows = [l for l in db.refrigerant_logs.values() if l["visit_id"] == vid]
        return _list_response(rows, models.serialize)

    @app.route(PREFIX + "/refrigerant-logs/<lid>", methods=["GET"])
    def get_refrigerant_log(lid):
        _auth(["ContractAdmin", "Technician", "Dispatcher"])
        log = L.refrigerant_log(lid)
        return ok(models.serialize(log))

    @app.route(PREFIX + "/refrigerant-logs", methods=["GET"])
    def list_refrigerant_logs():
        _auth(["ContractAdmin", "Technician", "Dispatcher"])
        rows = list(db.refrigerant_logs.values())
        for field in ("equipment_id", "posted_by_tech_id", "visit_id"):
            val = request.args.get(field)
            if val is not None:
                rows = [r for r in rows if r.get(field) == val]
        return _list_response(rows, models.serialize)

    # =======================================================================
    # PartUsage
    # =======================================================================
    @app.route(PREFIX + "/service-visits/<vid>/part-usages", methods=["POST"])
    def post_part_usage(vid):
        user_id, role = _auth(["Technician"])
        v = L.visit(vid)
        body = get_body()
        part_name = req_str(body, "part_name")
        quantity = req_int(body, "quantity")
        list_price_cents = req_int(body, "list_price_cents", minimum=0)
        _require_assigned_tech(user_id, v)
        # priority 7: visit must be ON_SITE
        if v["status"] != "ON_SITE":
            raise err("ERR_MEMBERSHIP_NOT_ACTIVE", "Visit is not ON_SITE")
        if quantity <= 0:
            raise err("ERR_INVALID_REQUEST", "quantity must be > 0")
        m = db.memberships[v["membership_id"]]
        plan = db.service_plans[m["plan_id"]]
        charged = S.part_charge(list_price_cents, quantity, plan["parts_discount_pct"])
        usage = models.new_record("PartUsage", {
            "visit_id": v["id"], "part_name": part_name, "quantity": quantity,
            "list_price_cents": list_price_cents, "charged_cents": charged,
        })
        db.part_usages[usage["id"]] = usage
        customer = db.customers[m["customer_id"]]
        customer["billing_balance_cents"] += charged
        models.touch(customer)
        return created(models.serialize(usage))

    @app.route(PREFIX + "/service-visits/<vid>/part-usages", methods=["GET"])
    def list_visit_part_usages(vid):
        _auth(["ContractAdmin", "Technician", "Dispatcher"])
        L.visit(vid)
        rows = [p for p in db.part_usages.values() if p["visit_id"] == vid]
        return _list_response(rows, models.serialize)

    # =======================================================================
    # WarrantyClaim
    # =======================================================================
    @app.route(PREFIX + "/warranty-claims", methods=["POST"])
    def create_claim():
        _auth(["ContractAdmin", "Technician"])
        body = get_body()
        equipment_id = req_str(body, "equipment_id")
        origin_visit_id = req_str(body, "origin_visit_id")
        claimed_amount = req_int(body, "claimed_amount_cents", minimum=0)
        equip = L.equipment(equipment_id)
        origin_visit = L.visit(origin_visit_id)
        # priority 20: origin must be a WARRANTY visit at the equipment's site
        if origin_visit["visit_kind"] != "WARRANTY" or \
                origin_visit["site_id"] != equip["site_id"]:
            raise err("ERR_CLAIM_ORIGIN_INVALID",
                      "Claim origin is not a valid warranty visit at the site")
        claim = models.new_record("WarrantyClaim", {
            "equipment_id": equipment_id, "origin_visit_id": origin_visit_id,
            "status": "SUBMITTED", "claimed_amount_cents": claimed_amount,
            "approved_amount_cents": 0, "denial_reason": "",
        })
        db.warranty_claims[claim["id"]] = claim
        return created(models.serialize(claim))

    @app.route(PREFIX + "/warranty-claims/<cid>", methods=["GET"])
    def get_claim(cid):
        user_id, role = _auth(["ContractAdmin", "Customer", "Technician"])
        c = L.claim(cid)
        if role == "Customer":
            L.require_customer_owns(user_id, L.owner_customer_id_of_claim(c))
        return ok(models.serialize(c))

    @app.route(PREFIX + "/warranty-claims", methods=["GET"])
    def list_claims():
        user_id, role = _auth(["ContractAdmin", "Customer", "Technician"])
        rows = list(db.warranty_claims.values())
        for field in ("equipment_id", "origin_visit_id", "status"):
            val = request.args.get(field)
            if val is not None:
                rows = [r for r in rows if r[field] == val]
        if role == "Customer":
            rows = [r for r in rows
                    if L.owner_customer_id_of_claim(r) == user_id]
        return _list_response(rows, models.serialize)

    @app.route(PREFIX + "/warranty-claims/<cid>/start-review", methods=["POST"])
    def start_review_claim(cid):
        _auth(["ContractAdmin"])
        c = L.claim(cid)
        if c["status"] != "SUBMITTED":
            raise err("ERR_INVALID_STATE", "Claim is not SUBMITTED")
        equip = db.equipment[c["equipment_id"]]
        S.refresh_warranty(equip)
        # PRD §3.10: equipment must still be IN_WARRANTY at review start.
        if equip["warranty_status"] != "IN_WARRANTY":
            raise err("ERR_INVALID_STATE", "Equipment is not IN_WARRANTY")
        c["status"] = "UNDER_REVIEW"
        models.touch(c)
        return ok(models.serialize(c))

    @app.route(PREFIX + "/warranty-claims/<cid>/approve", methods=["POST"])
    def approve_claim(cid):
        _auth(["ContractAdmin"])
        c = L.claim(cid)
        body = get_body()
        approved_amount = req_int(body, "approved_amount_cents", minimum=0)
        if c["status"] != "UNDER_REVIEW":
            raise err("ERR_INVALID_STATE", "Claim is not UNDER_REVIEW")
        # priority 19: approved <= claimed
        if approved_amount > c["claimed_amount_cents"]:
            raise err("ERR_APPROVAL_EXCEEDS_CLAIM",
                      "Approved amount exceeds claimed amount")
        c["approved_amount_cents"] = approved_amount
        c["status"] = "APPROVED"
        models.touch(c)
        return ok(models.serialize(c))

    @app.route(PREFIX + "/warranty-claims/<cid>/deny", methods=["POST"])
    def deny_claim(cid):
        _auth(["ContractAdmin"])
        c = L.claim(cid)
        body = get_body()
        denial_reason = req_str(body, "denial_reason")
        if c["status"] != "UNDER_REVIEW":
            raise err("ERR_INVALID_STATE", "Claim is not UNDER_REVIEW")
        c["approved_amount_cents"] = 0
        c["denial_reason"] = denial_reason
        c["status"] = "DENIED"
        # cascade: deny voids the equipment warranty
        equip = db.equipment[c["equipment_id"]]
        equip["warranty_status"] = "VOIDED"
        models.touch(equip)
        models.touch(c)
        return ok(models.serialize(c))

    @app.route(PREFIX + "/warranty-claims/<cid>/settle", methods=["POST"])
    def settle_claim(cid):
        _auth(["ContractAdmin"])
        c = L.claim(cid)
        if c["status"] != "APPROVED":
            raise err("ERR_INVALID_STATE", "Claim is not APPROVED")
        equip = db.equipment[c["equipment_id"]]
        site = db.sites[equip["site_id"]]
        customer = db.customers[site["customer_id"]]
        customer["billing_balance_cents"] -= c["approved_amount_cents"]
        models.touch(customer)
        c["status"] = "SETTLED"
        models.touch(c)
        return ok(models.serialize(c))

    # =======================================================================
    # Administrative test clock (PRD §3.11)
    # =======================================================================
    @app.route(PREFIX + "/_clock/set_current_utc", methods=["POST"])
    def clock_set():
        _auth(["ContractAdmin"])
        body = get_body()
        target = parse_dt(body, "to_iso8601", required=True)
        S.set_clock(target)
        return ok({})

    @app.route(PREFIX + "/_clock/advance", methods=["POST"])
    def clock_advance():
        _auth(["ContractAdmin"])
        body = get_body()
        target = parse_dt(body, "to_iso8601", required=True)
        S.advance_clock(target)
        return ok({})
