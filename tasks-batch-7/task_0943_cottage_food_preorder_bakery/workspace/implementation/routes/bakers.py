"""Operators (Baker) and customers."""

from flask import Blueprint

import config
from db import DB, base_record, touch
from errors import ApiError
from ladder import endpoint
from response import created, ok
from routes.common import list_endpoint
from serialize import dump
from services import money
from services.gates import require_state
from tsutil import ts_input

bp = Blueprint("bakers", __name__)

ADMIN = config.ROLE_ADMIN
BAKER = config.ROLE_BAKER
CUSTOMER = config.ROLE_CUSTOMER
INSPECTOR = config.ROLE_INSPECTOR


# ---------------------------------------------------------------------------
# Baker
# ---------------------------------------------------------------------------

@bp.post("/bakery/bakers")
@endpoint(roles=[ADMIN])
def create_baker(ctx):
    # rung 13
    display_name = ctx.req_str("display_name")
    jurisdiction_code = ctx.req_str("jurisdiction_code")
    payout_period_start = ctx.req_dt("payout_period_start")
    shared_kitchen = ctx.opt_bool("shared_kitchen", False)
    annual_cap_cents = ctx.opt_int("annual_cap_cents",
                                   config.ANNUAL_GROSS_SALES_CAP_CENTS, minimum=0)
    cap_year = ctx.opt_int("cap_year", 2026)
    permitted_radius_km = ctx.opt_num("permitted_radius_km",
                                      config.PERMITTED_DELIVERY_RADIUS_KM)

    rec = base_record(ctx.now)
    rec.update({
        "display_name": display_name,
        "jurisdiction_code": jurisdiction_code,
        "permit_status": "PENDING",
        "shared_kitchen": shared_kitchen,
        "annual_cap_cents": annual_cap_cents,
        "cap_year": cap_year,
        "annual_gross_sales_cents": 0,
        "permitted_radius_km": permitted_radius_km,
        "payout_period_start": ts_input(payout_period_start),
        "payout_net_cents": 0,
    })
    DB.coll("bakers")[rec["id"]] = rec
    return created(dump("bakers", rec))


@bp.post("/bakery/bakers/<baker_id>/permit-status")
@endpoint(roles=[ADMIN], path=("baker_id",))
def permit_status(ctx):
    baker = ctx.p["baker_id"]
    # rung 13 (presence) then rung 14 (membership).  CARVE-OUT: rung 15 never
    # applies to this endpoint, so reinstatement stays reachable.
    if ctx.body.get("to_status") is None:
        raise ApiError("ERR_VALIDATION", "to_status is required.")
    to_status = ctx.enum("to_status", "permit_status")
    cap_year = ctx.opt_int("cap_year")

    current = baker.get("permit_status")
    # rung 19: only the two administrator-driven targets are requestable;
    # ACTIVE -> CAP_REACHED is latched by the system at confirm time.
    if to_status == "ACTIVE":
        require_state(current, ("PENDING", "SUSPENDED", "CAP_REACHED"),
                      "permit_status")
        if current == "CAP_REACHED":
            # a new statutory year is the only escape from CAP_REACHED
            if cap_year is None or cap_year <= (baker.get("cap_year") or 0):
                raise ApiError("ERR_INVALID_STATE",
                               "Escaping CAP_REACHED requires an advanced cap_year.")
            baker["cap_year"] = cap_year
            baker["annual_gross_sales_cents"] = 0
        elif current == "PENDING":
            baker["annual_gross_sales_cents"] = 0
        baker["permit_status"] = "ACTIVE"
    elif to_status == "SUSPENDED":
        require_state(current, ("ACTIVE",), "permit_status")
        baker["permit_status"] = "SUSPENDED"
    else:
        raise ApiError("ERR_INVALID_STATE",
                       "%s is not an administrator-requestable posture." % to_status)
    touch(baker, ctx.now)
    return ok(dump("bakers", baker))


@bp.get("/bakery/bakers/<baker_id>")
@endpoint(roles=[ADMIN, BAKER, INSPECTOR], path=("baker_id",))
def read_baker(ctx):
    baker = ctx.p["baker_id"]
    ctx.ownership(baker_id=baker["id"])
    return ok(dump("bakers", baker))


@bp.get("/bakery/bakers")
@endpoint(roles=[ADMIN, INSPECTOR], list_ep=True)
def list_bakers(ctx):
    return list_endpoint(ctx, "bakers", {
        "permit_status": "permit_status",
        "jurisdiction_code": "jurisdiction_code",
    })


@bp.get("/bakery/bakers/<baker_id>/compliance")
@endpoint(roles=[ADMIN, BAKER, INSPECTOR], path=("baker_id",))
def compliance(ctx):
    baker = ctx.p["baker_id"]
    ctx.ownership(baker_id=baker["id"])
    # PRD 2.11: this read recomputes both figures.
    gross = money.refresh_gross_sales(baker)
    payout = money.refresh_payout_net(baker)
    return ok({
        "annual_gross_sales_cents": gross,
        "cap_remaining_cents": (baker.get("annual_cap_cents") or 0) - gross,
        "annual_cap_cents": baker.get("annual_cap_cents") or 0,
        "cap_year": baker.get("cap_year"),
        "permit_status": baker.get("permit_status"),
        "payout_net_cents": payout,
        "tip_counts_toward_cap": config.TIP_COUNTS_TOWARD_GROSS_CAP,
    })


# ---------------------------------------------------------------------------
# Customer
# ---------------------------------------------------------------------------

@bp.post("/bakery/customers")
@endpoint(roles=[ADMIN, BAKER])
def create_customer(ctx):
    fks = ctx.body_fks(required=("baker_id",))          # rung 10
    baker = fks["baker_id"]
    if baker is None:
        raise ApiError("ERR_VALIDATION", "baker_id is required.")
    ctx.ownership(baker_id=baker["id"])                 # rung 12
    # rung 13
    display_name = ctx.req_str("display_name")
    email = ctx.req_str("email")
    delivery_distance_km = ctx.req_num("delivery_distance_km")
    avoidances = ctx.opt_list("allergen_avoidances", [])
    unattended = ctx.opt_bool("unattended_consent", False)
    cooler = ctx.opt_bool("cooler_provided", False)
    normalised = []
    for entry in avoidances:
        if not isinstance(entry, dict):
            raise ApiError("ERR_VALIDATION",
                           "allergen_avoidances entries must be objects.")
        allergen_name = entry.get("allergen")
        if not isinstance(allergen_name, str):
            raise ApiError("ERR_VALIDATION",
                           "allergen_avoidances[].allergen must be a string.")
        normalised.append(entry)
    # rung 14: only the `severity` member of an avoidance entry routes here
    for entry in normalised:
        sev = entry.get("severity")
        if not isinstance(sev, str) or sev not in config.ENUM_SETS["severity"]:
            raise ApiError("ERR_INVALID_ENUM",
                           "allergen_avoidances[].severity must be one of %s."
                           % ", ".join(config.ENUM_SETS["severity"]))
    # email unique within (baker_id, email)
    for existing in DB.coll("customers").values():
        if (existing.get("baker_id") == baker["id"]
                and existing.get("email") == email):
            raise ApiError("ERR_VALIDATION",
                           "email must be unique within the operator.")

    rec = base_record(ctx.now)
    rec.update({
        "baker_id": baker["id"],
        "display_name": display_name,
        "email": email,
        "delivery_distance_km": delivery_distance_km,
        "allergen_avoidances": [
            {"allergen": e["allergen"], "severity": e["severity"]}
            for e in normalised
        ],
        "unattended_consent": unattended,
        "cooler_provided": cooler,
        "credit_balance_cents": 0,
    })
    DB.coll("customers")[rec["id"]] = rec
    return created(dump("customers", rec))


@bp.get("/bakery/customers/<customer_id>")
@endpoint(roles=[ADMIN, BAKER, CUSTOMER], path=("customer_id",))
def read_customer(ctx):
    cust = ctx.p["customer_id"]
    ctx.ownership(customer_id=cust["id"], baker_id=cust.get("baker_id"))
    money.refresh_credit_balance(cust, ctx.now)   # PRD 2.11
    return ok(dump("customers", cust))


@bp.get("/bakery/customers")
@endpoint(roles=[ADMIN, BAKER], list_ep=True)
def list_customers(ctx):
    return list_endpoint(ctx, "customers", {
        "baker_id": "baker_id",
        "email": "email",
    })
