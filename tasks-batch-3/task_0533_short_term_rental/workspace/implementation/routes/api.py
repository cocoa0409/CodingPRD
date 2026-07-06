"""All API routes."""
from flask import Blueprint, request

import errors
from errors import err
from db import db, new_id, new_api_key
from middleware import get_auth, require_role
from response import ok_object, ok_array
from clock import parse_iso, add_days
import validation as V
from services import domain as D
from services import calc

bp = Blueprint("api", __name__)


def _sorted(records):
    return sorted(records, key=lambda r: (r["created_at"], r["_seq"]))


# ---------------------------------------------------------------------------
# Existence helpers (ERR_NOT_FOUND 404)
# ---------------------------------------------------------------------------


def _find(collection, rid):
    rec = collection.get(rid)
    if rec is None:
        raise err(errors.ERR_NOT_FOUND, "Resource not found")
    return rec


# ===========================================================================
# Clock
# ===========================================================================
@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    _uid, role = get_auth()
    require_role(role, {"CityRegistrar", "TaxOfficer"})
    body = V.get_body()
    if "to_iso8601" not in body:
        raise err(errors.ERR_INVALID_REQUEST, "Missing required field: to_iso8601")
    try:
        dt = parse_iso(body["to_iso8601"])
    except Exception:
        raise err(errors.ERR_INVALID_REQUEST, "Invalid to_iso8601")
    db.clock.set(dt)
    return ok_object({})


# ===========================================================================
# Zones
# ===========================================================================
@bp.route("/zones", methods=["POST"])
def create_zone():
    _uid, role = get_auth()
    require_role(role, {"CityRegistrar"})
    body = V.get_body()
    zone_code = V.require_str(body, "zone_code")
    permit_cap = V.require_int(body, "permit_cap", minimum=0)
    str_eligible = V.opt_bool(body, "str_eligible", True)
    whole_home_allowed = V.opt_bool(body, "whole_home_allowed", False)
    lottery_enabled = V.opt_bool(body, "lottery_enabled", False)
    for z in db.zones.values():
        if z["zone_code"] == zone_code:
            raise err(errors.ERR_DUPLICATE_ZONE_CODE, "zone_code already exists")
    rec = D._common_new()
    rec.update({
        "zone_code": zone_code,
        "str_eligible": str_eligible,
        "whole_home_allowed": whole_home_allowed,
        "permit_cap": permit_cap,
        "active_permit_count": 0,
        "lottery_enabled": lottery_enabled,
    })
    db.zones[rec["id"]] = rec
    return ok_object(D.ser_zone(rec), 201)


@bp.route("/zones/<rid>", methods=["GET"])
def get_zone(rid):
    _uid, role = get_auth()
    require_role(role, {"CityRegistrar", "TaxOfficer", "Host"})
    z = _find(db.zones, rid)
    D.recompute_zone_count(z)
    return ok_object(D.ser_zone(z))


@bp.route("/zones", methods=["GET"])
def list_zones():
    _uid, role = get_auth()
    require_role(role, {"CityRegistrar", "TaxOfficer", "Host"})
    limit, offset = V.parse_pagination()
    items = list(db.zones.values())
    items = _sorted(items)
    for z in items:
        D.recompute_zone_count(z)
    page, total = V.paginate(items, limit, offset)
    return ok_array([D.ser_zone(z) for z in page], limit, offset, total)


# ===========================================================================
# Hosts
# ===========================================================================
@bp.route("/hosts", methods=["POST"])
def create_host():
    _uid, role = get_auth()
    require_role(role, {"CityRegistrar", "Host"})
    body = V.get_body()
    email = V.require_str(body, "email")
    full_name = V.require_str(body, "full_name")
    for h in db.hosts.values():
        if h["email"] == email:
            raise err(errors.ERR_DUPLICATE_EMAIL, "email already exists")
    rec = D._common_new()
    rec.update({
        "email": email,
        "full_name": full_name,
        "primary_residence_property_id": None,
        "strike_total": 0,
        "standing": "GOOD",
    })
    db.hosts[rec["id"]] = rec
    return ok_object(D.ser_host(rec), 201)


@bp.route("/hosts/<rid>", methods=["GET"])
def get_host(rid):
    _uid, role = get_auth()
    require_role(role, {"CityRegistrar", "TaxOfficer", "Host"})
    h = _find(db.hosts, rid)
    D.recompute_host_standing(h)
    return ok_object(D.ser_host(h))


@bp.route("/hosts", methods=["GET"])
def list_hosts():
    _uid, role = get_auth()
    require_role(role, {"CityRegistrar", "TaxOfficer", "Host"})
    limit, offset = V.parse_pagination()
    items = list(db.hosts.values())
    prp = request.args.get("primary_residence_property_id")
    if prp is not None and prp != "":
        items = [h for h in items if h["primary_residence_property_id"] == prp]
    items = _sorted(items)
    for h in items:
        D.recompute_host_standing(h)
    page, total = V.paginate(items, limit, offset)
    return ok_array([D.ser_host(h) for h in page], limit, offset, total)


@bp.route("/hosts/<rid>/attest-primary-residence", methods=["POST"])
def attest_primary_residence(rid):
    uid, role = get_auth()
    require_role(role, {"Host"})
    body = V.get_body()
    property_id = V.require_str(body, "property_id")
    host = _find(db.hosts, rid)
    # ownership: acting host must be this host
    if uid != host["id"]:
        raise err(errors.ERR_UNAUTHORIZED, "Host may only attest own residence")
    prop = _find(db.properties, property_id)
    existing = host["primary_residence_property_id"]
    if existing is not None and existing != property_id:
        raise err(errors.ERR_PRIMARY_RESIDENCE_CONFLICT, "primary residence already set")
    if existing == property_id:
        # idempotent re-set to same property: no conflict, ensure flag set
        prop["is_primary_residence"] = True
        return ok_object(D.ser_host(host))
    host["primary_residence_property_id"] = property_id
    prop["is_primary_residence"] = True
    D.touch(host)
    return ok_object(D.ser_host(host))


# ===========================================================================
# Properties
# ===========================================================================
@bp.route("/properties", methods=["POST"])
def create_property():
    _uid, role = get_auth()
    require_role(role, {"CityRegistrar", "Host"})
    body = V.get_body()
    host_id = V.require_str(body, "host_id")
    zone_id = V.require_str(body, "zone_id")
    street_address = V.require_str(body, "street_address")
    bedroom_count = V.require_int(body, "bedroom_count", minimum=1)
    # existence left-to-right: Host, then Zone? PRD resolution order is
    # Zone, Host, Property... but body FKs resolved in that global order.
    _find(db.zones, zone_id)
    _find(db.hosts, host_id)
    for p in db.properties.values():
        if p["street_address"] == street_address:
            raise err(errors.ERR_DUPLICATE_ADDRESS, "street_address already exists")
    rec = D._common_new()
    rec.update({
        "host_id": host_id,
        "zone_id": zone_id,
        "street_address": street_address,
        "bedroom_count": bedroom_count,
        "is_primary_residence": False,
        "max_occupancy": calc.occupancy_max(bedroom_count),
    })
    db.properties[rec["id"]] = rec
    return ok_object(D.ser_property(rec), 201)


@bp.route("/properties/<rid>", methods=["GET"])
def get_property(rid):
    _uid, role = get_auth()
    require_role(role, {"CityRegistrar", "TaxOfficer", "Host"})
    p = _find(db.properties, rid)
    return ok_object(D.ser_property(p))


@bp.route("/properties", methods=["GET"])
def list_properties():
    _uid, role = get_auth()
    require_role(role, {"CityRegistrar", "TaxOfficer", "Host"})
    limit, offset = V.parse_pagination()
    items = list(db.properties.values())
    host_id = request.args.get("host_id")
    zone_id = request.args.get("zone_id")
    if host_id:
        items = [p for p in items if p["host_id"] == host_id]
    if zone_id:
        items = [p for p in items if p["zone_id"] == zone_id]
    items = _sorted(items)
    page, total = V.paginate(items, limit, offset)
    return ok_array([D.ser_property(p) for p in page], limit, offset, total)


# ===========================================================================
# Permits
# ===========================================================================
PERMIT_TYPES = {"PRIMARY_RESIDENCE", "WHOLE_HOME"}


@bp.route("/permits", methods=["POST"])
def create_permit():
    _uid, role = get_auth()
    require_role(role, {"CityRegistrar", "Host"})
    body = V.get_body()
    property_id = V.require_str(body, "property_id")
    permit_type = V.require_enum(body, "permit_type", PERMIT_TYPES)
    attested_occupancy = V.require_int(body, "attested_occupancy")
    nightly_base_rate_cents = V.require_int(body, "nightly_base_rate_cents", minimum=0)
    safety_attested = V.opt_bool(body, "safety_attested", False)
    prop = _find(db.properties, property_id)
    rec = D._common_new()
    rec.update({
        "property_id": property_id,
        "host_id": prop["host_id"],
        "zone_id": prop["zone_id"],
        "permit_type": permit_type,
        "attested_occupancy": attested_occupancy,
        "safety_attested": safety_attested,
        "issued_at": None,
        "expires_at": None,
        "nightly_base_rate_cents": nightly_base_rate_cents,
        "status": "DRAFT",
    })
    db.permits[rec["id"]] = rec
    return ok_object(D.ser_permit(rec), 201)


@bp.route("/permits/<rid>", methods=["GET"])
def get_permit(rid):
    _uid, role = get_auth()
    require_role(role, {"CityRegistrar", "TaxOfficer", "Host"})
    p = _find(db.permits, rid)
    D.apply_permit_expiry(p)
    return ok_object(D.ser_permit(p))


@bp.route("/permits", methods=["GET"])
def list_permits():
    _uid, role = get_auth()
    require_role(role, {"CityRegistrar", "TaxOfficer", "Host"})
    limit, offset = V.parse_pagination()
    items = list(db.permits.values())
    for p in items:
        D.apply_permit_expiry(p)
    property_id = request.args.get("property_id")
    host_id = request.args.get("host_id")
    zone_id = request.args.get("zone_id")
    status = request.args.get("status")
    if property_id:
        items = [p for p in items if p["property_id"] == property_id]
    if host_id:
        items = [p for p in items if p["host_id"] == host_id]
    if zone_id:
        items = [p for p in items if p["zone_id"] == zone_id]
    if status:
        items = [p for p in items if p["status"] == status]
    items = _sorted(items)
    page, total = V.paginate(items, limit, offset)
    return ok_array([D.ser_permit(p) for p in page], limit, offset, total)


@bp.route("/permits/<rid>/issue", methods=["POST"])
def issue_permit(rid):
    _uid, role = get_auth()
    require_role(role, {"CityRegistrar"})
    p = _find(db.permits, rid)
    D.apply_permit_expiry(p)
    if p["status"] != "DRAFT":
        raise err(errors.ERR_INVALID_STATE, "permit not in DRAFT")
    prop = db.properties.get(p["property_id"])
    zone = db.zones.get(p["zone_id"])
    if prop is None or zone is None:
        raise err(errors.ERR_NOT_FOUND, "referenced resource not found")
    host = db.hosts.get(p["host_id"])
    # business gates in order
    if not zone["str_eligible"]:
        raise err(errors.ERR_ZONE_INELIGIBLE, "zone not STR eligible")
    if p["permit_type"] == "WHOLE_HOME" and not zone["whole_home_allowed"]:
        raise err(errors.ERR_WHOLE_HOME_FORBIDDEN, "whole home not allowed in zone")
    if p["permit_type"] == "PRIMARY_RESIDENCE" and not prop["is_primary_residence"]:
        raise err(errors.ERR_NOT_PRIMARY_RESIDENCE, "property is not primary residence")
    if not p["safety_attested"]:
        raise err(errors.ERR_SAFETY_NOT_ATTESTED, "safety not attested")
    if not (1 <= p["attested_occupancy"] <= prop["max_occupancy"]):
        raise err(errors.ERR_OCCUPANCY_EXCEEDS_MAX, "attested occupancy out of range")
    if host is not None:
        D.recompute_host_standing(host)
        if host["standing"] != "GOOD":
            raise err(errors.ERR_HOST_BARRED, "host barred")
    # cap gate
    if zone["active_permit_count"] < zone["permit_cap"]:
        p["status"] = "ISSUED"
        p["issued_at"] = db.clock.now
        p["expires_at"] = add_days(db.clock.now, 365)
        D._inc_zone_count(zone["id"])
        D.touch(p)
    else:
        if zone["lottery_enabled"]:
            p["status"] = "LOTTERY_PENDING"
            D.touch(p)
        else:
            raise err(errors.ERR_PERMIT_CAP_REACHED, "permit cap reached")
    return ok_object(D.ser_permit(p))


@bp.route("/permits/<rid>/reject", methods=["POST"])
def reject_permit(rid):
    _uid, role = get_auth()
    require_role(role, {"CityRegistrar"})
    p = _find(db.permits, rid)
    D.apply_permit_expiry(p)
    if p["status"] != "DRAFT":
        raise err(errors.ERR_INVALID_STATE, "permit not in DRAFT")
    p["status"] = "REJECTED"
    D.touch(p)
    return ok_object(D.ser_permit(p))


@bp.route("/permits/<rid>/activate", methods=["POST"])
def activate_permit(rid):
    uid, role = get_auth()
    require_role(role, {"Host"})
    p = _find(db.permits, rid)
    if uid != p["host_id"]:
        raise err(errors.ERR_UNAUTHORIZED, "not permit owner")
    D.apply_permit_expiry(p)
    if p["status"] != "ISSUED":
        raise err(errors.ERR_INVALID_STATE, "permit not in ISSUED")
    p["status"] = "ACTIVE"
    D.touch(p)
    return ok_object(D.ser_permit(p))


@bp.route("/permits/<rid>/renew", methods=["POST"])
def renew_permit(rid):
    uid, role = get_auth()
    require_role(role, {"Host"})
    body = V.get_body()
    expected_version = V.require_int(body, "expected_permit_version")
    p = _find(db.permits, rid)
    if uid != p["host_id"]:
        raise err(errors.ERR_UNAUTHORIZED, "not permit owner")
    D.apply_permit_expiry(p)
    if p["status"] != "ACTIVE":
        raise err(errors.ERR_INVALID_STATE, "permit not ACTIVE")
    # business rules in priority order: HOST_BARRED(10), RENEWAL_WINDOW(11), STALE_VERSION(19)
    host = db.hosts.get(p["host_id"])
    if host is not None:
        D.recompute_host_standing(host)
        if host["standing"] != "GOOD":
            raise err(errors.ERR_HOST_BARRED, "host barred")
    now = db.clock.now
    window_start = add_days(p["expires_at"], -30)
    if not (window_start <= now < p["expires_at"]):
        raise err(errors.ERR_RENEWAL_WINDOW_CLOSED, "outside renewal window")
    if expected_version != p["version"]:
        raise err(errors.ERR_STALE_VERSION, "stale expected_permit_version")
    p["expires_at"] = add_days(p["expires_at"], 365)
    D.touch(p)
    return ok_object(D.ser_permit(p))


@bp.route("/permits/<rid>/reinstate", methods=["POST"])
def reinstate_permit(rid):
    _uid, role = get_auth()
    require_role(role, {"CityRegistrar"})
    p = _find(db.permits, rid)
    D.apply_permit_expiry(p)
    if p["status"] != "SUSPENDED":
        raise err(errors.ERR_INVALID_STATE, "permit not SUSPENDED")
    # precondition: cumulative upheld strikes < 4
    if D.permit_upheld_strikes(p["id"]) >= 4:
        raise err(errors.ERR_INVALID_STATE, "permit beyond reinstatement")
    p["status"] = "ACTIVE"
    D.touch(p)
    return ok_object(D.ser_permit(p))


# ===========================================================================
# Complaints
# ===========================================================================
COMPLAINT_CATEGORIES = {"NOISE", "TRASH", "OVER_OCCUPANCY", "UNPERMITTED"}


@bp.route("/complaints", methods=["POST"])
def create_complaint():
    _uid, role = get_auth()
    require_role(role, {"CityRegistrar", "Host"})
    body = V.get_body()
    permit_id = V.require_str(body, "permit_id")
    category = V.require_enum(body, "category", COMPLAINT_CATEGORIES)
    _find(db.permits, permit_id)
    rec = D._common_new()
    rec.update({
        "permit_id": permit_id,
        "category": category,
        "strike_points": 0,
        "status": "OPEN",
    })
    db.complaints[rec["id"]] = rec
    return ok_object(D.ser_complaint(rec), 201)


@bp.route("/complaints/<rid>", methods=["GET"])
def get_complaint(rid):
    _uid, role = get_auth()
    require_role(role, {"CityRegistrar", "TaxOfficer", "Host"})
    c = _find(db.complaints, rid)
    return ok_object(D.ser_complaint(c))


@bp.route("/complaints", methods=["GET"])
def list_complaints():
    _uid, role = get_auth()
    require_role(role, {"CityRegistrar", "TaxOfficer", "Host"})
    limit, offset = V.parse_pagination()
    items = list(db.complaints.values())
    permit_id = request.args.get("permit_id")
    status = request.args.get("status")
    if permit_id:
        items = [c for c in items if c["permit_id"] == permit_id]
    if status:
        items = [c for c in items if c["status"] == status]
    items = _sorted(items)
    page, total = V.paginate(items, limit, offset)
    return ok_array([D.ser_complaint(c) for c in page], limit, offset, total)


@bp.route("/complaints/<rid>/dismiss", methods=["POST"])
def dismiss_complaint(rid):
    _uid, role = get_auth()
    require_role(role, {"CityRegistrar"})
    c = _find(db.complaints, rid)
    if c["status"] != "OPEN":
        raise err(errors.ERR_INVALID_STATE, "complaint not OPEN")
    c["status"] = "DISMISSED"
    D.touch(c)
    return ok_object(D.ser_complaint(c))


@bp.route("/complaints/<rid>/uphold", methods=["POST"])
def uphold_complaint(rid):
    _uid, role = get_auth()
    require_role(role, {"CityRegistrar"})
    c = _find(db.complaints, rid)
    if c["status"] != "OPEN":
        raise err(errors.ERR_INVALID_STATE, "complaint not OPEN")
    permit = db.permits.get(c["permit_id"])
    if permit is None:
        raise err(errors.ERR_NOT_FOUND, "permit not found")
    D.apply_permit_expiry(permit)
    if permit["status"] not in ("ISSUED", "ACTIVE", "SUSPENDED"):
        raise err(errors.ERR_PERMIT_NOT_ENFORCEABLE, "permit not enforceable")
    # set strike points
    c["strike_points"] = 1 if c["category"] in ("NOISE", "TRASH") else 2
    c["status"] = "UPHELD"
    D.touch(c)
    # cascade: permit strike aggregation
    cumulative = D.permit_upheld_strikes(permit["id"])
    if cumulative >= 4:
        if permit["status"] in ("ACTIVE", "SUSPENDED"):
            permit["status"] = "REVOKED"
            D._dec_zone_count(permit["zone_id"])
            D.touch(permit)
    elif cumulative >= 2:
        if permit["status"] == "ACTIVE":
            permit["status"] = "SUSPENDED"
            D.touch(permit)
    # cascade second hop: host standing
    host = db.hosts.get(permit["host_id"])
    if host is not None:
        D.recompute_host_standing(host)
    return ok_object(D.ser_complaint(c))


# ===========================================================================
# Tax Filings
# ===========================================================================
def _period_last_day_plus_30(year, month):
    from datetime import datetime, timezone
    if month == 12:
        ny, nm = year + 1, 1
    else:
        ny, nm = year, month + 1
    first_next = datetime(ny, nm, 1, 0, 0, 0, tzinfo=timezone.utc)
    # last day = first_next - 1 day (that day's start). end of period + 30 days.
    # We interpret "end of period + 30 days" as last day's date + 30 days,
    # anchored at that last day's 00:00:00 UTC.
    last_day = add_days(first_next, -1)
    return add_days(last_day, 30)


@bp.route("/tax-filings", methods=["POST"])
def create_filing():
    _uid, role = get_auth()
    require_role(role, {"TaxOfficer", "Host"})
    body = V.get_body()
    permit_id = V.require_str(body, "permit_id")
    period_year = V.require_int(body, "period_year")
    period_month = V.require_int(body, "period_month", minimum=1, maximum=12)
    nights_booked = V.require_int(body, "nights_booked", minimum=0)
    gross_revenue_cents = V.require_int(body, "gross_revenue_cents", minimum=0)
    _find(db.permits, permit_id)
    for f in db.tax_filings.values():
        if (f["permit_id"] == permit_id and f["period_year"] == period_year
                and f["period_month"] == period_month):
            raise err(errors.ERR_DUPLICATE_FILING_PERIOD, "duplicate filing period")
    rec = D._common_new()
    rec.update({
        "permit_id": permit_id,
        "period_year": period_year,
        "period_month": period_month,
        "nights_booked": nights_booked,
        "gross_revenue_cents": gross_revenue_cents,
        "tot_due_cents": None,
        "penalty_cents": 0,
        "amount_remitted_cents": 0,
        "due_at": None,
        "status": "DRAFT",
    })
    db.tax_filings[rec["id"]] = rec
    return ok_object(D.ser_filing(rec), 201)


@bp.route("/tax-filings/<rid>", methods=["GET"])
def get_filing(rid):
    _uid, role = get_auth()
    require_role(role, {"CityRegistrar", "TaxOfficer", "Host"})
    f = _find(db.tax_filings, rid)
    D.apply_filing_delinquency(f)
    return ok_object(D.ser_filing(f))


@bp.route("/tax-filings", methods=["GET"])
def list_filings():
    _uid, role = get_auth()
    require_role(role, {"CityRegistrar", "TaxOfficer", "Host"})
    limit, offset = V.parse_pagination()
    items = list(db.tax_filings.values())
    for f in items:
        D.apply_filing_delinquency(f)
    permit_id = request.args.get("permit_id")
    status = request.args.get("status")
    if permit_id:
        items = [f for f in items if f["permit_id"] == permit_id]
    if status:
        items = [f for f in items if f["status"] == status]
    items = _sorted(items)
    page, total = V.paginate(items, limit, offset)
    return ok_array([D.ser_filing(f) for f in page], limit, offset, total)


@bp.route("/tax-filings/<rid>/file", methods=["POST"])
def file_filing(rid):
    _uid, role = get_auth()
    require_role(role, {"TaxOfficer"})
    f = _find(db.tax_filings, rid)
    if f["status"] != "DRAFT":
        raise err(errors.ERR_INVALID_STATE, "filing not DRAFT")
    permit = db.permits.get(f["permit_id"])
    if permit is None:
        raise err(errors.ERR_NOT_FOUND, "permit not found")
    D.apply_permit_expiry(permit)
    # business rules priority: NO_NIGHTS_TO_FILE(13), PERMIT_NOT_FILEABLE(14)
    if f["nights_booked"] < 1:
        raise err(errors.ERR_NO_NIGHTS_TO_FILE, "no nights to file")
    if permit["status"] in ("DRAFT", "REJECTED", "LOTTERY_PENDING"):
        raise err(errors.ERR_PERMIT_NOT_FILEABLE, "permit not fileable")
    f["tot_due_cents"] = calc.tot_due(f["gross_revenue_cents"], f["nights_booked"])
    f["due_at"] = _period_last_day_plus_30(f["period_year"], f["period_month"])
    f["status"] = "FILED"
    D.touch(f)
    return ok_object(D.ser_filing(f))


@bp.route("/tax-filings/<rid>/amend", methods=["POST"])
def amend_filing(rid):
    _uid, role = get_auth()
    require_role(role, {"TaxOfficer"})
    f = _find(db.tax_filings, rid)
    D.apply_filing_delinquency(f)
    if f["status"] != "FILED":
        raise err(errors.ERR_INVALID_STATE, "filing not FILED")
    if f["amount_remitted_cents"] != 0:
        raise err(errors.ERR_FILING_HAS_REMITTANCES, "filing has remittances")
    f["tot_due_cents"] = None
    f["due_at"] = None
    f["status"] = "DRAFT"
    D.touch(f)
    return ok_object(D.ser_filing(f))


@bp.route("/tax-filings/<rid>/remit", methods=["POST"])
def remit_filing(rid):
    uid, role = get_auth()
    require_role(role, {"Host"})
    body = V.get_body()
    payment_cents = V.require_int(body, "payment_cents", minimum=0)
    f = _find(db.tax_filings, rid)
    permit = db.permits.get(f["permit_id"])
    if permit is None:
        raise err(errors.ERR_NOT_FOUND, "permit not found")
    if uid != permit["host_id"]:
        raise err(errors.ERR_UNAUTHORIZED, "not owner of permit")
    D.apply_filing_delinquency(f)
    if f["status"] not in ("FILED", "DELINQUENT"):
        raise err(errors.ERR_INVALID_STATE, "filing not remittable")
    f["amount_remitted_cents"] += payment_cents
    if f["status"] == "FILED":
        if f["amount_remitted_cents"] >= f["tot_due_cents"]:
            f["status"] = "REMITTED"
    else:  # DELINQUENT
        if f["amount_remitted_cents"] >= f["tot_due_cents"] + f["penalty_cents"]:
            f["status"] = "REMITTED"
    D.touch(f)
    return ok_object(D.ser_filing(f))


# ===========================================================================
# Lottery Rounds
# ===========================================================================
@bp.route("/lottery-rounds", methods=["POST"])
def create_lottery():
    _uid, role = get_auth()
    require_role(role, {"CityRegistrar"})
    body = V.get_body()
    zone_id = V.require_str(body, "zone_id")
    seats_available = V.require_int(body, "seats_available", minimum=0)
    _find(db.zones, zone_id)
    rec = D._common_new()
    rec.update({
        "zone_id": zone_id,
        "seats_available": seats_available,
        "awarded_permit_ids": [],
        "status": "OPEN",
    })
    db.lottery_rounds[rec["id"]] = rec
    return ok_object(D.ser_lottery(rec), 201)


@bp.route("/lottery-rounds/<rid>", methods=["GET"])
def get_lottery(rid):
    _uid, role = get_auth()
    require_role(role, {"CityRegistrar", "TaxOfficer", "Host"})
    l = _find(db.lottery_rounds, rid)
    return ok_object(D.ser_lottery(l))


@bp.route("/lottery-rounds", methods=["GET"])
def list_lotteries():
    _uid, role = get_auth()
    require_role(role, {"CityRegistrar", "TaxOfficer", "Host"})
    limit, offset = V.parse_pagination()
    items = list(db.lottery_rounds.values())
    zone_id = request.args.get("zone_id")
    status = request.args.get("status")
    if zone_id:
        items = [l for l in items if l["zone_id"] == zone_id]
    if status:
        items = [l for l in items if l["status"] == status]
    items = _sorted(items)
    page, total = V.paginate(items, limit, offset)
    return ok_array([D.ser_lottery(l) for l in page], limit, offset, total)


@bp.route("/lottery-rounds/<rid>/draw", methods=["POST"])
def draw_lottery(rid):
    _uid, role = get_auth()
    require_role(role, {"CityRegistrar"})
    body = V.get_body()
    expected_version = V.require_int(body, "expected_lottery_round_version")
    l = _find(db.lottery_rounds, rid)
    if l["status"] != "OPEN":
        raise err(errors.ERR_INVALID_STATE, "lottery not OPEN")
    if expected_version != l["version"]:
        raise err(errors.ERR_STALE_VERSION, "stale expected_lottery_round_version")
    # order LOTTERY_PENDING permits in this zone by created_at ASC
    entrants = [p for p in db.permits.values()
                if p["zone_id"] == l["zone_id"] and p["status"] == "LOTTERY_PENDING"]
    entrants = sorted(entrants, key=lambda p: (p["created_at"], p["_seq"]))
    seats = l["seats_available"]
    awarded = entrants[:seats]
    unseated = entrants[seats:]
    for p in awarded:
        p["status"] = "ISSUED"
        p["issued_at"] = db.clock.now
        p["expires_at"] = add_days(db.clock.now, 365)
        D._inc_zone_count(p["zone_id"])
        D.touch(p)
    for p in unseated:
        p["status"] = "REJECTED"
        D.touch(p)
    l["awarded_permit_ids"] = [p["id"] for p in awarded]
    l["status"] = "DRAWN"
    D.touch(l)
    return ok_object(D.ser_lottery(l))


# ===========================================================================
# Platforms
# ===========================================================================
@bp.route("/platforms", methods=["POST"])
def create_platform():
    _uid, role = get_auth()
    require_role(role, {"CityRegistrar"})
    body = V.get_body()
    platform_name = V.require_str(body, "platform_name")
    for p in db.platforms.values():
        if p["platform_name"] == platform_name:
            raise err(errors.ERR_INVALID_REQUEST, "platform_name already exists")
    rec = D._common_new()
    rec.update({
        "platform_name": platform_name,
        "api_key": new_api_key(),
    })
    db.platforms[rec["id"]] = rec
    return ok_object(D.ser_platform(rec), 201)


@bp.route("/platforms/<rid>", methods=["GET"])
def get_platform(rid):
    _uid, role = get_auth()
    require_role(role, {"CityRegistrar"})
    p = _find(db.platforms, rid)
    return ok_object(D.ser_platform(p))


# ===========================================================================
# Listing Reports
# ===========================================================================
@bp.route("/listing-reports", methods=["POST"])
def create_listing_report():
    uid, role = get_auth()
    require_role(role, {"Platform"})
    body = V.get_body()
    platform_id = V.require_str(body, "platform_id")
    street_address = V.require_str(body, "street_address")
    reported_nights = V.require_int(body, "reported_nights", minimum=0)
    claimed_permit_number = body.get("claimed_permit_number")
    if claimed_permit_number is not None and not isinstance(claimed_permit_number, str):
        raise err(errors.ERR_INVALID_REQUEST, "claimed_permit_number must be a string")
    platform = _find(db.platforms, platform_id)
    # ownership: acting platform (api_key as X-User-ID) must be this platform
    if uid != platform["api_key"] and uid != platform["id"]:
        raise err(errors.ERR_UNAUTHORIZED, "platform mismatch")
    match_result, matched_permit_id = _reconcile(claimed_permit_number, street_address)
    rec = {
        "id": new_id(),
        "created_at": db.clock.now,
        "_seq": db.next_seq(),
        "platform_id": platform_id,
        "claimed_permit_number": claimed_permit_number,
        "street_address": street_address,
        "reported_nights": reported_nights,
        "match_result": match_result,
        "matched_permit_id": matched_permit_id,
    }
    db.listing_reports[rec["id"]] = rec
    return ok_object(D.ser_listing_report(rec), 201)


def _reconcile(claimed_permit_number, street_address):
    """platform-match calc (order-pinned)."""
    active_states = ("ISSUED", "ACTIVE")
    if claimed_permit_number:
        p = db.permits.get(claimed_permit_number)
        if p is not None:
            D.apply_permit_expiry(p)
            prop = db.properties.get(p["property_id"])
            prop_addr = prop["street_address"] if prop else None
            if prop_addr == street_address:
                if p["status"] in active_states:
                    return "MATCHED", p["id"]
                return "PERMIT_INACTIVE", p["id"]
            return "ADDRESS_MISMATCH", p["id"]
    # fall back to address resolution
    matches = []
    for p in db.permits.values():
        D.apply_permit_expiry(p)
        prop = db.properties.get(p["property_id"])
        if prop and prop["street_address"] == street_address:
            matches.append(p)
    if not matches:
        return "NO_PERMIT", None
    # latest issued_at; tie-break created_at ASC (never id)
    def sort_key(p):
        issued = p["issued_at"]
        # None issued_at sorts earliest; use created_at as tie-break
        return (issued is not None, issued or p["created_at"], -p["_seq"])
    # select the permit with latest issued_at; tie-break by created_at ASC
    # (earliest created wins on tie). Build accordingly.
    best = None
    for p in matches:
        if best is None:
            best = p
            continue
        pi = p["issued_at"]
        bi = best["issued_at"]
        if pi is not None and bi is None:
            best = p
        elif pi is not None and bi is not None:
            if pi > bi:
                best = p
            elif pi == bi:
                # tie-break created_at ASC
                if (p["created_at"], p["_seq"]) < (best["created_at"], best["_seq"]):
                    best = p
        elif pi is None and bi is None:
            # neither issued; tie-break created_at ASC
            if (p["created_at"], p["_seq"]) < (best["created_at"], best["_seq"]):
                best = p
    if best["status"] in active_states:
        return "MATCHED", best["id"]
    return "PERMIT_INACTIVE", best["id"]


@bp.route("/listing-reports/<rid>", methods=["GET"])
def get_listing_report(rid):
    _uid, role = get_auth()
    require_role(role, {"CityRegistrar", "TaxOfficer"})
    r = _find(db.listing_reports, rid)
    return ok_object(D.ser_listing_report(r))


@bp.route("/listing-reports", methods=["GET"])
def list_listing_reports():
    _uid, role = get_auth()
    require_role(role, {"CityRegistrar", "TaxOfficer"})
    limit, offset = V.parse_pagination()
    items = list(db.listing_reports.values())
    platform_id = request.args.get("platform_id")
    matched_permit_id = request.args.get("matched_permit_id")
    match_result = request.args.get("match_result")
    if platform_id:
        items = [r for r in items if r["platform_id"] == platform_id]
    if matched_permit_id:
        items = [r for r in items if r["matched_permit_id"] == matched_permit_id]
    if match_result:
        items = [r for r in items if r["match_result"] == match_result]
    items = _sorted(items)
    page, total = V.paginate(items, limit, offset)
    return ok_array([D.ser_listing_report(r) for r in page], limit, offset, total)
