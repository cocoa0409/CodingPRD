"""Emergency tickets -- two independent axes on one row."""

import calc
import common
import serialize
from core import ApiError, F, d, db, endpoint, floor_div

CAUSE_CLASSES = ["PUMP_FAILURE", "WELL_DRY", "PRESSURE_TANK_FAILURE",
                 "CONTROL_FAILURE", "TREATMENT_FAILURE", "NON_WELL_CAUSE"]


def _ticket_account(ctx):
    return ctx.path["emergency_ticket_id"]["account_id"]


def _ticket_technician(ctx):
    return ctx.path["emergency_ticket_id"]["assigned_technician_id"]


def _dispatch_gate(*allowed):
    def check(ctx):
        ticket = ctx.path["emergency_ticket_id"]
        if ticket["dispatch_status"] not in allowed:
            raise ApiError("ERR_EMERGENCY_DISPATCH_INVALID_STATE",
                           "The dispatch axis is not in a state that permits this.")
    return check


def _auth_pending_gate(ctx):
    ticket = ctx.path["emergency_ticket_id"]
    if ticket["authorization_status"] != "PENDING":
        raise ApiError("ERR_EMERGENCY_AUTH_INVALID_STATE",
                       "The authorisation axis is not PENDING.")


@endpoint("POST", "/water-service/emergency-tickets", ["Dispatcher", "PlatformAdmin"],
          code=201, fields=[
              F("property_id", "string"),
              F("well_profile_id", "string"),
              F("account_id", "string"),
              F("reported_outage_hours", "number", minimum=0.0, maximum=240.0),
          ])
def create_ticket(ctx):
    common.resolve("Property", ctx.body["property_id"])
    common.resolve("WellProfile", ctx.body["well_profile_id"])
    account = common.resolve("Account", ctx.body["account_id"])
    row = ctx.new("EmergencyTicket", {
        "property_id": ctx.body["property_id"],
        "well_profile_id": ctx.body["well_profile_id"],
        "account_id": account["id"],
        "assigned_technician_id": None,
        "dispatch_status": "INTAKE",
        "authorization_status": "NOT_REQUIRED",
        "intake_at": db.clock,
        "dispatched_at": None,
        "reported_outage_hours": ctx.body["reported_outage_hours"],
        "cause_class": None,
        "membership_tier_at_intake": account["membership_tier"],
        "severity_score": None,
        "dispatch_surcharge_cents": 0,
        "membership_credit_cents": 0,
        "net_dispatch_charge_cents": 0,
        "onsite_estimate_cents": None,
        "preauth_cap_cents": None,
        "response_minutes": None,
    })
    return serialize.dump(row)


@endpoint("GET", "/water-service/emergency-tickets/<emergency_ticket_id>",
          ["PlatformAdmin", "Dispatcher", "Technician", "BillingClerk",
           "CustomerContact"], read=True,
          path_params=[("emergency_ticket_id", "EmergencyTicket")],
          # PRD 4.13 names the scope gate for CustomerContact only on this read.
          scope=common.scope(customer=_ticket_account))
def read_ticket(ctx):
    return serialize.dump(ctx.path["emergency_ticket_id"])


@endpoint("GET", "/water-service/emergency-tickets",
          ["PlatformAdmin", "Dispatcher", "Technician", "BillingClerk"], read=True,
          paginated=True,
          filters=["property_id", "well_profile_id", "account_id",
                   "assigned_technician_id", "dispatch_status", "authorization_status"])
def list_tickets(ctx):
    return db.all("EmergencyTicket")


@endpoint("POST", "/water-service/emergency-tickets/<emergency_ticket_id>/triage",
          ["Dispatcher"], path_params=[("emergency_ticket_id", "EmergencyTicket")],
          g5=_dispatch_gate("INTAKE"))
def triage_ticket(ctx):
    ticket = ctx.path["emergency_ticket_id"]
    prop = db.get("Property", ticket["property_id"])
    if prop is None or calc.service_zone(prop["distance_miles"]) == "OUT_OF_AREA":
        raise ApiError("ERR_OUT_OF_SERVICE_AREA", "The property is out of service area.")
    ticket["dispatch_status"] = "TRIAGED"
    ctx.touch(ticket)
    return serialize.dump(ticket)


@endpoint("POST", "/water-service/emergency-tickets/<emergency_ticket_id>/dispatch",
          ["Dispatcher"], path_params=[("emergency_ticket_id", "EmergencyTicket")],
          g5=_dispatch_gate("TRIAGED"), fields=[F("technician_id", "string")])
def dispatch_ticket(ctx):
    ticket = ctx.path["emergency_ticket_id"]
    technician = common.resolve("Technician", ctx.body["technician_id"])
    if technician["status"] != "AVAILABLE":
        raise ApiError("ERR_TECHNICIAN_UNAVAILABLE", "The technician is not available.")
    ticket["assigned_technician_id"] = technician["id"]
    ticket["dispatched_at"] = db.clock
    ticket["response_minutes"] = floor_div(
        d((ticket["dispatched_at"] - ticket["intake_at"]).total_seconds()) / d(60))
    ticket["dispatch_status"] = "DISPATCHED"
    ctx.touch(ticket)
    return serialize.dump(ticket)


@endpoint("POST", "/water-service/emergency-tickets/<emergency_ticket_id>/arrive",
          ["Technician"], path_params=[("emergency_ticket_id", "EmergencyTicket")],
          scope=common.scope(technician=_ticket_technician),
          g5=_dispatch_gate("DISPATCHED"))
def arrive_ticket(ctx):
    ticket = ctx.path["emergency_ticket_id"]
    ticket["dispatch_status"] = "ON_SITE"
    ctx.touch(ticket)
    return serialize.dump(ticket)


@endpoint("POST", "/water-service/emergency-tickets/<emergency_ticket_id>/diagnosis",
          ["Technician"], path_params=[("emergency_ticket_id", "EmergencyTicket")],
          scope=common.scope(technician=_ticket_technician),
          g5=_dispatch_gate("ON_SITE"), fields=[
              F("cause_class", "string", enum=CAUSE_CLASSES),
              F("onsite_estimate_cents", "integer", minimum=0, maximum=10000000),
          ])
def diagnose_ticket(ctx):
    ticket = ctx.path["emergency_ticket_id"]
    prop = db.get("Property", ticket["property_id"])
    cause = ctx.body["cause_class"]
    ticket["cause_class"] = cause
    ticket["onsite_estimate_cents"] = ctx.body["onsite_estimate_cents"]

    score = calc.severity_score(cause, ticket["reported_outage_hours"],
                                prop["household_size"], prop["has_vulnerable_occupant"])
    surcharge = calc.dispatch_surcharge_cents(score)
    credit = calc.membership_credit_cents(ticket["membership_tier_at_intake"],
                                          surcharge, score)
    ticket["severity_score"] = score
    ticket["dispatch_surcharge_cents"] = surcharge
    ticket["membership_credit_cents"] = credit
    ticket["net_dispatch_charge_cents"] = calc.net_dispatch_charge_cents(
        surcharge, credit, cause)
    ticket["preauth_cap_cents"] = calc.PREAUTH_CAP_CENTS[
        ticket["membership_tier_at_intake"]]
    ticket["dispatch_status"] = "DIAGNOSED"
    if ticket["onsite_estimate_cents"] > ticket["preauth_cap_cents"]:
        ticket["authorization_status"] = "PENDING"
    else:
        ticket["authorization_status"] = "PRE_AUTHORIZED"
    ctx.touch(ticket)
    return serialize.dump(ticket)


@endpoint("POST", "/water-service/emergency-tickets/<emergency_ticket_id>/authorize",
          ["CustomerContact"],
          path_params=[("emergency_ticket_id", "EmergencyTicket")],
          scope=common.scope(customer=_ticket_account), g5=_auth_pending_gate)
def authorize_ticket(ctx):
    ticket = ctx.path["emergency_ticket_id"]
    account = db.get("Account", ticket["account_id"])
    if account is not None and account["credit_hold"]:
        raise ApiError("ERR_ACCOUNT_ON_CREDIT_HOLD", "The account is on credit hold.")
    ticket["authorization_status"] = "AUTHORIZED"
    ctx.touch(ticket)
    return serialize.dump(ticket)


@endpoint("POST",
          "/water-service/emergency-tickets/<emergency_ticket_id>/decline-authorization",
          ["CustomerContact"],
          path_params=[("emergency_ticket_id", "EmergencyTicket")],
          scope=common.scope(customer=_ticket_account), g5=_auth_pending_gate)
def decline_authorization(ctx):
    ticket = ctx.path["emergency_ticket_id"]
    ticket["authorization_status"] = "DECLINED"
    ctx.touch(ticket)
    return serialize.dump(ticket)


def _cancel_gate(ctx):
    ticket = ctx.path["emergency_ticket_id"]
    status = ticket["dispatch_status"]
    if status in ("INTAKE", "TRIAGED"):
        return
    if status == "DIAGNOSED" and ticket["authorization_status"] == "DECLINED":
        return
    raise ApiError("ERR_EMERGENCY_DISPATCH_INVALID_STATE",
                   "The ticket cannot be cancelled in this state.")


@endpoint("POST", "/water-service/emergency-tickets/<emergency_ticket_id>/cancel",
          ["Dispatcher", "PlatformAdmin"],
          path_params=[("emergency_ticket_id", "EmergencyTicket")], g5=_cancel_gate)
def cancel_ticket(ctx):
    ticket = ctx.path["emergency_ticket_id"]
    ticket["dispatch_status"] = "CANCELLED"
    ctx.touch(ticket)
    return serialize.dump(ticket)


@endpoint("GET", "/water-service/emergency-tickets/<emergency_ticket_id>/work-orders",
          ["PlatformAdmin", "Dispatcher", "Technician", "BillingClerk",
           "CustomerContact"], read=True, paginated=True,
          path_params=[("emergency_ticket_id", "EmergencyTicket")])
def ticket_work_orders(ctx):
    return common.rows_where("WorkOrder",
                             emergency_ticket_id=ctx.path["emergency_ticket_id"]["id"])
