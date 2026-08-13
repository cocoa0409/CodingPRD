"""Nested site resources: stalls, rate plans, amenity products (PRD §3.1)."""
from flask import Blueprint, request

import auth
import db
import domain
import errors
import services
import util

bp = Blueprint("site_children", __name__)

READ_ROLES = ("Driver", "SiteOperator", "NetworkAdmin")
STALL_CLASSES = ("STANDARD", "OVERSIZED")
AMENITY_CODES = ("SHOWER", "FUEL", "WIFI", "POWER")


def _site_or_404(site_id):
    site = domain.get("sites", site_id)
    if site is None:
        raise errors.not_found("Site not found")
    return site


def _child_or_404(store, child_id, site_id, label):
    child = domain.get(store, child_id)
    if child is None or child["site_id"] != site_id:
        raise errors.not_found(f"{label} not found")
    return child


def _bool_param(name):
    raw = request.args.get(name)
    if raw is None:
        return None
    if raw.lower() == "true":
        return True
    if raw.lower() == "false":
        return False
    return "__no_match__"


# --------------------------------------------------------------------------
# Stalls
# --------------------------------------------------------------------------
@bp.post("/sites/<site_id>/stalls")
def create_stall(site_id):
    ident = auth.identity()
    auth.require_roles(ident, ("NetworkAdmin",))
    site = _site_or_404(site_id)
    body = util.get_body(required=True)
    util.req_fields(body, ["stall_number", "stall_class", "is_reservable"])
    number = util.req_str(body, "stall_number")
    stall_class = util.req_enum(body, "stall_class", STALL_CLASSES)
    reservable = body["is_reservable"]
    if not isinstance(reservable, bool):
        raise errors.validation("Field is_reservable must be a boolean")
    for s in domain.all_of("stalls"):
        if s["site_id"] == site_id and s["stall_number"] == number:
            raise errors.duplicate_stall_number()
    stall = domain.new_entity("stalls", {
        "site_id": site_id,
        "stall_number": number,
        "stall_class": stall_class,
        "is_reservable": reservable,
        "status": "ACTIVE",
    })
    return util.ok(domain.serialize_stall(stall), status=201)


@bp.get("/sites/<site_id>/stalls")
def list_stalls(site_id):
    ident = auth.identity()
    auth.require_roles(ident, READ_ROLES)
    _site_or_404(site_id)
    status_f = request.args.get("status")
    reservable_f = _bool_param("is_reservable")
    items = []
    for s in domain.all_of("stalls"):
        if s["site_id"] != site_id:
            continue
        if status_f is not None and s["status"] != status_f:
            continue
        if reservable_f is not None:
            if reservable_f == "__no_match__" or s["is_reservable"] != reservable_f:
                continue
        items.append(s)
    items = util.sort_created(items)
    page, pg = util.paginate(items)
    return util.ok([domain.serialize_stall(s) for s in page], pagination=pg)


@bp.patch("/sites/<site_id>/stalls/<stall_id>")
def update_stall(site_id, stall_id):
    ident = auth.identity()
    auth.require_roles(ident, ("SiteOperator", "NetworkAdmin"))
    _site_or_404(site_id)
    stall = _child_or_404("stalls", stall_id, site_id, "Stall")
    body = util.get_body()
    if "status" not in body or body["status"] is None:
        return util.ok(domain.serialize_stall(stall))
    target = util.req_enum(body, "status", ("ACTIVE", "OUT_OF_SERVICE"))
    if target == stall["status"]:
        raise errors.invalid_state(f"Stall already {target}")

    if target == "OUT_OF_SERVICE":
        stall["status"] = "OUT_OF_SERVICE"
        domain.touch(stall)
        # Reassignment cascade (PRD §3.1): only BOOKED bookings whose check-in
        # window has NOT opened yet are moved.
        now = db.clock_now()
        bookings = [b for b in domain.all_of("bookings")
                    if b["stall_id"] == stall_id and b["status"] == "BOOKED"
                    and b["checkin_open_at"] > now]
        for b in sorted(bookings, key=lambda x: (x["created_at"], x["_seq"])):
            window = (b["checkin_open_at"], b["checkout_due_at"])
            eligible = services.eligible_stalls(
                site_id, stall["is_reservable"], stall["stall_class"], window,
                exclude_stall_id=stall_id)
            if eligible:
                b["stall_id"] = eligible[0]["id"]
                domain.touch(b)
            else:
                services.system_cancel_booking(b)
    else:
        stall["status"] = "ACTIVE"
        domain.touch(stall)
    return util.ok(domain.serialize_stall(stall))


# --------------------------------------------------------------------------
# Rate plans
# --------------------------------------------------------------------------
def _plan_defaults_from(body):
    fields = {}
    for key in ("tier2_pct", "tier3_pct", "tier4_pct"):
        fields[key] = util.opt_int(body, key, services.RATE_PLAN_DEFAULTS[key])
    for key in ("mult_low", "mult_mid", "mult_high", "mult_max", "peak_multiplier"):
        fields[key] = util.opt_num(body, key, services.RATE_PLAN_DEFAULTS[key])
    peak_days = body.get("peak_days", services.RATE_PLAN_DEFAULTS["peak_days"])
    if peak_days is None:
        peak_days = services.RATE_PLAN_DEFAULTS["peak_days"]
    if (not isinstance(peak_days, list)
            or any(d not in services.WEEKDAY_CODES for d in peak_days)):
        raise errors.validation("Field peak_days must be a list of weekday codes")
    fields["peak_days"] = list(peak_days)
    return fields


@bp.post("/sites/<site_id>/rate-plans")
def create_rate_plan(site_id):
    ident = auth.identity()
    auth.require_roles(ident, ("NetworkAdmin",))
    _site_or_404(site_id)
    body = util.get_body()
    fields = _plan_defaults_from(body)
    fields["site_id"] = site_id
    fields["status"] = "DRAFT"
    plan = domain.new_entity("rate_plans", fields)
    return util.ok(domain.serialize_rate_plan(plan), status=201)


@bp.get("/sites/<site_id>/rate-plans")
def list_rate_plans(site_id):
    ident = auth.identity()
    auth.require_roles(ident, READ_ROLES)
    _site_or_404(site_id)
    status_f = request.args.get("status")
    items = [p for p in domain.all_of("rate_plans")
             if p["site_id"] == site_id
             and (status_f is None or p["status"] == status_f)]
    items = util.sort_created(items)
    page, pg = util.paginate(items)
    return util.ok([domain.serialize_rate_plan(p) for p in page], pagination=pg)


@bp.post("/sites/<site_id>/rate-plans/<plan_id>/transition")
def rate_plan_transition(site_id, plan_id):
    ident = auth.identity()
    auth.require_roles(ident, ("NetworkAdmin",))
    site = _site_or_404(site_id)
    plan = _child_or_404("rate_plans", plan_id, site_id, "RatePlan")
    body = util.get_body(required=True)
    util.req_fields(body, ["to"])
    to = util.req_enum(body, "to", ("DRAFT", "ACTIVE", "SUPERSEDED", "RETIRED"))
    if to == "ACTIVE" and ("expected_site_version" not in body
                           or body["expected_site_version"] is None):
        raise errors.validation("expected_site_version is required for activation")

    # Priority 5: state machine permits the transition.
    if to == "ACTIVE":
        if plan["status"] != "DRAFT":
            raise errors.invalid_state("Only a DRAFT rate plan may be activated")
    elif to == "RETIRED":
        if plan["status"] not in ("DRAFT", "SUPERSEDED"):
            raise errors.invalid_state(
                "Only DRAFT or SUPERSEDED plans may be retired; activate a "
                "replacement before retiring the ACTIVE plan")
    else:
        raise errors.invalid_state(f"No transition to {to}")

    # Priority 6: OCC on Site.version for activation.
    if to == "ACTIVE":
        expected = util.req_int(body, "expected_site_version")
        if expected != site["version"]:
            raise errors.stale_version()

    if to == "ACTIVE":
        current = services.active_rate_plan(site_id)
        if current is not None and current["id"] != plan["id"]:
            current["status"] = "SUPERSEDED"
            domain.touch(current)
        plan["status"] = "ACTIVE"
        domain.touch(plan)
        domain.touch(site)  # activation mutates the site (version +1)
    else:
        plan["status"] = "RETIRED"
        domain.touch(plan)
    return util.ok(domain.serialize_rate_plan(plan))


# --------------------------------------------------------------------------
# Amenity products
# --------------------------------------------------------------------------
@bp.post("/sites/<site_id>/amenity-products")
def create_amenity_product(site_id):
    ident = auth.identity()
    auth.require_roles(ident, ("NetworkAdmin",))
    _site_or_404(site_id)
    body = util.get_body(required=True)
    util.req_fields(body, ["code", "name", "price_cents"])
    code = util.req_enum(body, "code", AMENITY_CODES)
    name = util.req_str(body, "name")
    price = util.req_int(body, "price_cents")
    capacity = util.opt_int(body, "nightly_capacity", None)
    for p in domain.all_of("amenity_products"):
        if p["site_id"] == site_id and p["code"] == code:
            raise errors.validation("Amenity code already exists at this site")
    product = domain.new_entity("amenity_products", {
        "site_id": site_id,
        "code": code,
        "name": name,
        "price_cents": price,
        "nightly_capacity": capacity,
        "status": "ACTIVE",
    })
    return util.ok(domain.serialize_amenity_product(product), status=201)


@bp.get("/sites/<site_id>/amenity-products")
def list_amenity_products(site_id):
    ident = auth.identity()
    auth.require_roles(ident, READ_ROLES)
    _site_or_404(site_id)
    items = util.sort_created(
        [p for p in domain.all_of("amenity_products") if p["site_id"] == site_id])
    page, pg = util.paginate(items)
    return util.ok([domain.serialize_amenity_product(p) for p in page], pagination=pg)


@bp.patch("/sites/<site_id>/amenity-products/<product_id>")
def update_amenity_product(site_id, product_id):
    ident = auth.identity()
    auth.require_roles(ident, ("NetworkAdmin",))
    _site_or_404(site_id)
    product = _child_or_404("amenity_products", product_id, site_id, "AmenityProduct")
    body = util.get_body()
    changed = False
    if "price_cents" in body and body["price_cents"] is not None:
        product["price_cents"] = util.req_int(body, "price_cents")
        changed = True
    if "nightly_capacity" in body:
        # explicit null recapacitates to uncapped
        if body["nightly_capacity"] is None:
            product["nightly_capacity"] = None
        else:
            product["nightly_capacity"] = util.req_int(body, "nightly_capacity")
        changed = True
    if "status" in body and body["status"] is not None:
        target = util.req_enum(body, "status", ("ACTIVE", "DISCONTINUED"))
        if target == "DISCONTINUED":
            if product["status"] != "ACTIVE":
                raise errors.invalid_state("Product already DISCONTINUED")
            product["status"] = "DISCONTINUED"
            changed = True
        else:
            if product["status"] != "ACTIVE":
                raise errors.invalid_state("DISCONTINUED is terminal")
    if changed:
        domain.touch(product)
    return util.ok(domain.serialize_amenity_product(product))
