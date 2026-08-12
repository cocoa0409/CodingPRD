"""Clock, host sites, pricing policies, drivers, technicians."""
from flask import Blueprint, request

import db
from errors import (
    ApiError, ERR_VALIDATION, ERR_NOT_FOUND, ERR_REFERENCE_NOT_FOUND,
    ERR_STALE_VERSION, ERR_INVALID_STATE, ERR_SITE_NOT_EMPTY, ERR_FORBIDDEN,
    ERR_POLICY_WINDOW_IN_PAST, ERR_POLICY_WINDOW_OVERLAP,
)
from middleware import get_actor, require_roles
from response import success_object, success_list
from services import core
from util import (
    body, req_str, opt_str, req_int, opt_int, req_enum, opt_enum, opt_bool,
    req_num, req_date, opt_date, parse_instant, format_instant, paginate,
    sorted_by_creation,
)

bp = Blueprint("admin", __name__)

SITE_STATUSES = ("ACTIVE", "SUSPENDED", "DECOMMISSIONED")
SITE_PATCH_FIELDS = (
    "name", "address", "cage_capacity_cylinders", "par_level_full",
    "commission_rate_bps", "commission_tier_threshold_cents",
    "commission_tier2_bonus_bps", "commission_basis", "recon_basis",
    "hazmat_fee_cents", "promo_waives_hazmat", "opening_float_cents",
)


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    uid, role = get_actor()
    require_roles(role, ("PlatformAdmin",))
    b = body()
    if "to_iso8601" not in b:
        raise ApiError(ERR_VALIDATION, 400, "Missing required field: to_iso8601")
    dt = parse_instant(b["to_iso8601"])
    db.set_clock(dt)
    today = db.current_date()
    # RECERT_DUE sweep: CERTIFIED cylinders whose expiry is strictly before today.
    for c in db.cylinders.values():
        if c["cert_status"] == "CERTIFIED" and c["certification_expires_on"] < today:
            c["cert_status"] = "RECERT_DUE"
            db.touch(c)
    return success_object({"current_utc": format_instant(db.get_clock())})


# ---------------------------------------------------------------------------
# Host sites
# ---------------------------------------------------------------------------

def _get_site(site_id):
    site = db.sites.get(site_id)
    if site is None:
        raise ApiError(ERR_NOT_FOUND, 404, "Site not found")
    return site


@bp.route("/sites", methods=["POST"])
def create_site():
    uid, role = get_actor()
    require_roles(role, ("PlatformAdmin",))
    b = body()
    name = req_str(b, "name")
    cap = req_int(b, "cage_capacity_cylinders", min_v=1)
    par = req_int(b, "par_level_full", min_v=1)
    if par > cap:
        raise ApiError(ERR_VALIDATION, 400, "par_level_full may not exceed cage_capacity_cylinders")
    rate = req_int(b, "commission_rate_bps", min_v=0, max_v=3000)
    site = db.new_entity({
        "name": name,
        "address": opt_str(b, "address", ""),
        "status": "ACTIVE",
        "cage_capacity_cylinders": cap,
        "par_level_full": par,
        "opening_float_cents": opt_int(b, "opening_float_cents", 20000, min_v=0),
        "commission_rate_bps": rate,
        "commission_tier_threshold_cents": opt_int(b, "commission_tier_threshold_cents", 100000, min_v=0),
        "commission_tier2_bonus_bps": opt_int(b, "commission_tier2_bonus_bps", 100, min_v=0),
        "commission_basis": opt_enum(b, "commission_basis", ("GROSS", "NET"), "GROSS"),
        "recon_basis": opt_enum(b, "recon_basis", ("BOOK", "PHYSICAL"), "BOOK"),
        "hazmat_fee_cents": opt_int(b, "hazmat_fee_cents", 0, min_v=0),
        "promo_waives_hazmat": opt_bool(b, "promo_waives_hazmat", False),
    })
    db.sites[site["id"]] = site
    return success_object(core.serialize_site(site), 201)


@bp.route("/sites/<siteId>", methods=["GET"])
def get_site(siteId):
    uid, role = get_actor()
    site = _get_site(siteId)
    if role == "HostSiteManager" and uid != siteId:
        raise ApiError(ERR_FORBIDDEN, 403, "Host-site manager may only read own site")
    return success_object(core.serialize_site(site))


@bp.route("/sites", methods=["GET"])
def list_sites():
    uid, role = get_actor()
    require_roles(role, ("PlatformAdmin", "ComplianceOfficer"))
    items = list(db.sites.values())
    status = request.args.get("status")
    if status is not None:
        items = [s for s in items if s["status"] == status]
    items = sorted_by_creation(items)
    page, total, limit, offset = paginate(items)
    return success_list([core.serialize_site(s) for s in page], total, limit, offset)


@bp.route("/sites/<siteId>", methods=["PATCH"])
def patch_site(siteId):
    uid, role = get_actor()
    require_roles(role, ("PlatformAdmin",))
    site = _get_site(siteId)
    b = body()
    expected = req_int(b, "expected_site_version")

    # Shape validation of the optional fields being patched.
    new_values = {}
    if "name" in b and b["name"] is not None:
        new_values["name"] = req_str(b, "name")
    if "address" in b and b["address"] is not None:
        new_values["address"] = opt_str(b, "address", site["address"])
    if "cage_capacity_cylinders" in b and b["cage_capacity_cylinders"] is not None:
        new_values["cage_capacity_cylinders"] = req_int(b, "cage_capacity_cylinders", min_v=1)
    if "par_level_full" in b and b["par_level_full"] is not None:
        new_values["par_level_full"] = req_int(b, "par_level_full", min_v=1)
    if "commission_rate_bps" in b and b["commission_rate_bps"] is not None:
        new_values["commission_rate_bps"] = req_int(b, "commission_rate_bps", min_v=0, max_v=3000)
    if "commission_tier_threshold_cents" in b and b["commission_tier_threshold_cents"] is not None:
        new_values["commission_tier_threshold_cents"] = req_int(b, "commission_tier_threshold_cents", min_v=0)
    if "commission_tier2_bonus_bps" in b and b["commission_tier2_bonus_bps"] is not None:
        new_values["commission_tier2_bonus_bps"] = req_int(b, "commission_tier2_bonus_bps", min_v=0)
    if "commission_basis" in b and b["commission_basis"] is not None:
        new_values["commission_basis"] = req_enum(b, "commission_basis", ("GROSS", "NET"))
    if "recon_basis" in b and b["recon_basis"] is not None:
        new_values["recon_basis"] = req_enum(b, "recon_basis", ("BOOK", "PHYSICAL"))
    if "hazmat_fee_cents" in b and b["hazmat_fee_cents"] is not None:
        new_values["hazmat_fee_cents"] = req_int(b, "hazmat_fee_cents", min_v=0)
    if "promo_waives_hazmat" in b and b["promo_waives_hazmat"] is not None:
        new_values["promo_waives_hazmat"] = opt_bool(b, "promo_waives_hazmat", site["promo_waives_hazmat"])
    if "opening_float_cents" in b and b["opening_float_cents"] is not None:
        new_values["opening_float_cents"] = req_int(b, "opening_float_cents", min_v=0)

    new_cap = new_values.get("cage_capacity_cylinders", site["cage_capacity_cylinders"])
    new_par = new_values.get("par_level_full", site["par_level_full"])
    if new_par > new_cap:
        raise ApiError(ERR_VALIDATION, 400, "par_level_full may not exceed cage_capacity_cylinders")

    new_status = None
    if "status" in b and b["status"] is not None:
        new_status = req_enum(b, "status", SITE_STATUSES)

    # Stage 5: optimistic concurrency.
    if expected != site["version"]:
        raise ApiError(ERR_STALE_VERSION, 412, "expected_site_version does not match current site version")

    # Stage 6: state legality / terminal lockdown.
    if site["status"] == "DECOMMISSIONED":
        raise ApiError(ERR_INVALID_STATE, 409, "Site is DECOMMISSIONED (terminal)")
    if new_status is not None:
        allowed = {
            ("ACTIVE", "SUSPENDED"),
            ("SUSPENDED", "ACTIVE"),
            ("SUSPENDED", "DECOMMISSIONED"),
        }
        if (site["status"], new_status) not in allowed:
            raise ApiError(ERR_INVALID_STATE, 409, "Illegal site status transition %s -> %s" % (site["status"], new_status))
        if new_status == "DECOMMISSIONED":
            full, empty, quar = core.cage_counts(site["id"])
            if full + empty + quar != 0:
                raise ApiError(ERR_SITE_NOT_EMPTY, 409, "Site cage is not empty")
            for r in db.restock_runs.values():
                if r["site_id"] == site["id"] and r["status"] in ("DRAFT", "DISPATCHED", "IN_PROGRESS", "COMPLETED"):
                    raise ApiError(ERR_SITE_NOT_EMPTY, 409, "Site has an open restock run")

    site.update(new_values)
    if new_status is not None:
        site["status"] = new_status
    db.touch(site)
    return success_object(core.serialize_site(site))


# ---------------------------------------------------------------------------
# Pricing policies
# ---------------------------------------------------------------------------

@bp.route("/pricing-policies", methods=["POST"])
def create_policy():
    uid, role = get_actor()
    require_roles(role, ("PlatformAdmin",))
    b = body()
    site_id = req_str(b, "site_id")
    expected = req_int(b, "expected_site_version")
    swap = req_int(b, "swap_price_cents", min_v=0)
    deposit = req_int(b, "core_deposit_cents", min_v=0)
    tax = req_int(b, "tax_rate_bps", min_v=0, max_v=2000)
    t1 = req_int(b, "refill_tier1_cents_per_lb", min_v=0)
    t1max = req_num(b, "refill_tier1_max_lbs")
    if t1max <= 0:
        raise ApiError(ERR_VALIDATION, 400, "refill_tier1_max_lbs must be > 0")
    t2 = req_int(b, "refill_tier2_cents_per_lb", min_v=0)
    ef = req_date(b, "effective_from")
    et = opt_date(b, "effective_to", None)
    if et is not None and et <= ef:
        raise ApiError(ERR_VALIDATION, 400, "effective_to must be after effective_from")
    supersede = opt_bool(b, "supersede_current", False)

    site = db.sites.get(site_id)
    if site is None:
        raise ApiError(ERR_REFERENCE_NOT_FOUND, 422, "site_id does not reference an existing site")
    if expected != site["version"]:
        raise ApiError(ERR_STALE_VERSION, 412, "expected_site_version does not match current site version")

    today = db.current_date()
    if ef < today:
        raise ApiError(ERR_POLICY_WINDOW_IN_PAST, 422, "effective_from is before the current date")

    site_policies = [p for p in db.policies.values() if p["site_id"] == site_id]
    clipped = None
    if supersede:
        cur = core.current_policy(site_id)
        if cur is not None:
            if not (ef > cur["effective_from"]):
                raise ApiError(
                    ERR_POLICY_WINDOW_OVERLAP, 409,
                    "supersede_current requires effective_from strictly after the current policy's effective_from",
                )
            clipped = cur
    for p in site_policies:
        if clipped is not None and p["id"] == clipped["id"]:
            continue
        if core.windows_overlap(ef, et, p["effective_from"], p["effective_to"]):
            raise ApiError(ERR_POLICY_WINDOW_OVERLAP, 409, "Policy window overlaps an existing window for the site")

    policy = db.new_entity({
        "site_id": site_id,
        "swap_price_cents": swap,
        "core_deposit_cents": deposit,
        "tax_rate_bps": tax,
        "refill_tier1_cents_per_lb": t1,
        "refill_tier1_max_lbs": t1max,
        "refill_tier2_cents_per_lb": t2,
        "effective_from": ef,
        "effective_to": et,
    })
    db.policies[policy["id"]] = policy
    if clipped is not None:
        clipped["effective_to"] = ef
        db.touch(clipped)
    db.touch(site)
    return success_object(core.serialize_policy(policy), 201)


def _get_policy(policyId):
    p = db.policies.get(policyId)
    if p is None:
        raise ApiError(ERR_NOT_FOUND, 404, "Pricing policy not found")
    return p


@bp.route("/pricing-policies/<policyId>", methods=["GET"])
def get_policy(policyId):
    uid, role = get_actor()
    require_roles(role, ("PlatformAdmin", "HostSiteManager"))
    p = _get_policy(policyId)
    if role == "HostSiteManager" and p["site_id"] != uid:
        raise ApiError(ERR_FORBIDDEN, 403, "Host-site manager may only read own site's policies")
    return success_object(core.serialize_policy(p))


@bp.route("/pricing-policies", methods=["GET"])
def list_policies():
    uid, role = get_actor()
    require_roles(role, ("PlatformAdmin", "HostSiteManager"))
    site_filter = request.args.get("site_id")
    items = list(db.policies.values())
    if role == "HostSiteManager":
        items = [p for p in items if p["site_id"] == uid]
    if site_filter is not None:
        items = [p for p in items if p["site_id"] == site_filter]
    items = sorted_by_creation(items)
    page, total, limit, offset = paginate(items)
    return success_list([core.serialize_policy(p) for p in page], total, limit, offset)


# ---------------------------------------------------------------------------
# Drivers
# ---------------------------------------------------------------------------

@bp.route("/drivers", methods=["POST"])
def create_driver():
    uid, role = get_actor()
    require_roles(role, ("PlatformAdmin",))
    b = body()
    name = req_str(b, "name")
    lic = req_str(b, "license_number")
    med = req_date(b, "dot_medical_expires_on")
    payload = req_int(b, "vehicle_max_payload_lbs", min_v=1)
    for d in db.drivers.values():
        if d["license_number"] == lic:
            raise ApiError(ERR_VALIDATION, 400, "license_number must be unique across drivers")
    driver = db.new_entity({
        "name": name,
        "license_number": lic,
        "dot_medical_expires_on": med,
        "vehicle_max_payload_lbs": payload,
        "status": "ACTIVE",
    })
    db.drivers[driver["id"]] = driver
    return success_object(core.serialize(driver), 201)


def _get_driver(driverId):
    d = db.drivers.get(driverId)
    if d is None:
        raise ApiError(ERR_NOT_FOUND, 404, "Driver not found")
    return d


@bp.route("/drivers/<driverId>", methods=["GET"])
def get_driver(driverId):
    uid, role = get_actor()
    require_roles(role, ("PlatformAdmin", "Driver"))
    d = _get_driver(driverId)
    if role == "Driver" and uid != driverId:
        raise ApiError(ERR_FORBIDDEN, 403, "Driver may only read self")
    return success_object(core.serialize(d))


@bp.route("/drivers/<driverId>", methods=["PATCH"])
def patch_driver(driverId):
    uid, role = get_actor()
    require_roles(role, ("PlatformAdmin",))
    d = _get_driver(driverId)
    b = body()
    if "status" in b and b["status"] is not None:
        d["status"] = req_enum(b, "status", ("ACTIVE", "SUSPENDED"))
    if "dot_medical_expires_on" in b and b["dot_medical_expires_on"] is not None:
        d["dot_medical_expires_on"] = req_date(b, "dot_medical_expires_on")
    if "vehicle_max_payload_lbs" in b and b["vehicle_max_payload_lbs"] is not None:
        d["vehicle_max_payload_lbs"] = req_int(b, "vehicle_max_payload_lbs", min_v=1)
    db.touch(d)
    return success_object(core.serialize(d))


# ---------------------------------------------------------------------------
# Technicians
# ---------------------------------------------------------------------------

@bp.route("/technicians", methods=["POST"])
def create_technician():
    uid, role = get_actor()
    require_roles(role, ("PlatformAdmin",))
    b = body()
    name = req_str(b, "name")
    level = req_enum(b, "cert_level", ("VISUAL_ONLY", "FULL"))
    tech = db.new_entity({"name": name, "cert_level": level, "status": "ACTIVE"})
    db.technicians[tech["id"]] = tech
    return success_object(core.serialize(tech), 201)


def _get_technician(technicianId):
    t = db.technicians.get(technicianId)
    if t is None:
        raise ApiError(ERR_NOT_FOUND, 404, "Technician not found")
    return t


@bp.route("/technicians/<technicianId>", methods=["GET"])
def get_technician(technicianId):
    uid, role = get_actor()
    require_roles(role, ("PlatformAdmin", "Technician"))
    t = _get_technician(technicianId)
    if role == "Technician" and uid != technicianId:
        raise ApiError(ERR_FORBIDDEN, 403, "Technician may only read self")
    return success_object(core.serialize(t))


@bp.route("/technicians/<technicianId>", methods=["PATCH"])
def patch_technician(technicianId):
    uid, role = get_actor()
    require_roles(role, ("PlatformAdmin",))
    t = _get_technician(technicianId)
    b = body()
    if "status" in b and b["status"] is not None:
        t["status"] = req_enum(b, "status", ("ACTIVE", "SUSPENDED"))
    if "cert_level" in b and b["cert_level"] is not None:
        t["cert_level"] = req_enum(b, "cert_level", ("VISUAL_ONLY", "FULL"))
    db.touch(t)
    return success_object(core.serialize(t))
