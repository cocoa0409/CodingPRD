"""Vacation Rental Management API — Flask implementation.

In-memory storage only; fresh empty state on every boot.
"""
import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import Flask, request, jsonify

import store
from errors import ApiError, err

app = Flask(__name__)

ROLES = {"PlatformAdmin", "PropertyManager", "Owner", "Guest", "Vendor", "Anonymous"}

# ---- calculation constants ----
WINDOW_HALF_DAYS = 15
WINDOW_TOTAL_DAYS = 30
OCC_HIGH_PCT = 80
OCC_MID_PCT = 50
OCC_HIGH_MULT = Decimal("1.25")
OCC_MID_MULT = Decimal("1.10")
LAST_MINUTE_DAYS = 7
LAST_MINUTE_MULT = Decimal("0.85")
FLEX_FULL_DAYS = 1
MOD_FULL_DAYS = 30
MOD_HALF_DAYS = 7
STRICT_FULL_DAYS = 60
OWNER_APPROVAL_THRESHOLD_CENTS = 50000
TURNOVER_BUFFER_MINUTES = 120

# =============================================================================
# Response envelope
# =============================================================================


def _meta(extra=None):
    m = {"api_request_id": store.request_id(), "api_request_timestamp": store.iso_now()}
    if extra:
        m.update(extra)
    return m


def public(entity):
    """Serialize an entity, stripping internal keys."""
    return {k: v for k, v in entity.items() if not k.startswith("_")}


def ok(data, code=200, is_array=False, meta_extra=None):
    body = {
        "meta": _meta(meta_extra),
        "response_type": "array" if is_array else "object",
        "data": data,
    }
    return jsonify(body), code


def object_response(entity, code=200):
    return ok(public(entity), code=code, is_array=False)


@app.errorhandler(ApiError)
def handle_api_error(e):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": e.error_id, "message": e.message},
    }
    return jsonify(body), e.http_status


@app.after_request
def _no_keepalive(resp):
    # The werkzeug dev server + requests keep-alive pool can race: werkzeug closes
    # an idle keep-alive connection just as the client reuses it, surfacing as a
    # flaky RemoteDisconnected on heavy multi-request fixtures. Forcing a fresh
    # connection per request removes the race. Transport-only; no PRD semantics.
    resp.headers["Connection"] = "close"
    return resp


@app.errorhandler(404)
def handle_404(e):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": "ERR_NOT_FOUND", "message": "Resource not found"},
    }
    return jsonify(body), 404


@app.errorhandler(405)
def handle_405(e):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": "ERR_NOT_FOUND", "message": "Method not allowed"},
    }
    return jsonify(body), 404


@app.errorhandler(Exception)
def handle_uncaught(e):
    if isinstance(e, ApiError):
        return handle_api_error(e)
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": "ERR_VALIDATION", "message": str(e)},
    }
    return jsonify(body), 422


# =============================================================================
# Auth / RBAC
# =============================================================================


def get_body():
    if not request.data:
        return {}
    try:
        j = request.get_json(force=True, silent=True)
    except Exception:
        j = None
    return j if isinstance(j, dict) else {}


def authenticate(exempt=False):
    """Returns (user_id, role). Raises ERR_UNAUTHENTICATED on failure."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if exempt:
        return uid, role
    if not uid or not role or role not in ROLES:
        raise err("ERR_UNAUTHENTICATED", "Missing or invalid authentication headers")
    return uid, role


def authorize(role, allowed):
    if role not in allowed:
        raise err("ERR_UNAUTHORIZED", "Role not permitted for this operation")


# =============================================================================
# Lookups
# =============================================================================


def find(table, _id):
    ent = table.get(_id)
    if ent is None:
        raise err("ERR_NOT_FOUND", "Resource not found")
    return ent


def maybe(table, _id):
    return table.get(_id)


# =============================================================================
# Datetime / numeric helpers
# =============================================================================


def parse_dt(value):
    if value is None:
        raise err("ERR_VALIDATION", "Missing datetime value")
    if isinstance(value, datetime):
        dt = value
    else:
        if not isinstance(value, str):
            raise err("ERR_VALIDATION", "Invalid datetime")
        s = value.strip()
        try:
            if s.endswith("Z"):
                s = s[:-1] + "+00:00"
            dt = datetime.fromisoformat(s)
        except Exception:
            # Try date-only
            try:
                dt = datetime.strptime(value.strip(), "%Y-%m-%d")
            except Exception:
                raise err("ERR_VALIDATION", "Invalid datetime format")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def whole_days(delta):
    return int(delta.total_seconds() // 86400)


def rhu(dec):
    """Round half up (away from zero at .5) to whole integer."""
    return int(Decimal(dec).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def as_dec(pct):
    return Decimal(str(pct))


# =============================================================================
# Validation helpers
# =============================================================================


def require_fields(body, names):
    for n in names:
        if n not in body or body[n] is None:
            raise err("ERR_VALIDATION", "Missing required field: %s" % n)


def check_enum(value, allowed, field):
    if value not in allowed:
        raise err("ERR_VALIDATION", "Invalid value for %s" % field)


def require_int(body, name, min_value=None):
    v = body.get(name)
    if not isinstance(v, int) or isinstance(v, bool):
        raise err("ERR_VALIDATION", "Field %s must be an integer" % name)
    if min_value is not None and v < min_value:
        raise err("ERR_VALIDATION", "Field %s below minimum" % name)
    return v


# =============================================================================
# Pagination + list helper
# =============================================================================


def paginate(items):
    try:
        limit = int(request.args.get("limit", 10))
    except Exception:
        limit = 10
    try:
        offset = int(request.args.get("offset", 0))
    except Exception:
        offset = 0
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    items = sorted(items, key=lambda e: e["_seq"])
    total = len(items)
    page = items[offset:offset + limit]
    has_more = offset + limit < total
    meta_extra = {"limit": limit, "offset": offset, "total_count": total, "has_more": has_more}
    data = [public(e) for e in page]
    return ok(data, code=200, is_array=True, meta_extra=meta_extra)


# =============================================================================
# Domain calculations
# =============================================================================


def active_permit_pct(property_id):
    for p in store.permits.values():
        if p["property_id"] == property_id and p["status"] == "ACTIVE":
            return as_dec(p["occupancy_tax_pct"])
    return Decimal("0")


def compute_occupancy_pct(property_id, check_in_dt, exclude_booking_id=None):
    window_start = (check_in_dt - timedelta(days=WINDOW_HALF_DAYS)).date()
    qualifying = []
    for b in store.bookings.values():
        if b["property_id"] != property_id:
            continue
        if exclude_booking_id is not None and b["id"] == exclude_booking_id:
            continue
        if b["stay_status"] not in ("HOLD", "CONFIRMED", "CHECKED_IN", "CHECKED_OUT"):
            continue
        qualifying.append(
            (parse_dt(b["check_in"]).date(), parse_dt(b["check_out"]).date())
        )
    booked = 0
    for i in range(WINDOW_TOTAL_DAYS):
        night = window_start + timedelta(days=i)
        for (ci, co) in qualifying:
            if ci <= night < co:
                booked += 1
                break
    return booked * 100 // WINDOW_TOTAL_DAYS


def seasonal_factor(property_id, check_in_dt):
    best = None
    for r in store.pricing_rules.values():
        if r["property_id"] != property_id or not r.get("active"):
            continue
        if r["rule_type"] != "SEASONAL":
            continue
        sd = r.get("start_date")
        ed = r.get("end_date")
        if sd is None or ed is None:
            continue
        if parse_dt(sd) <= check_in_dt < parse_dt(ed):
            key = (r["priority"], -r["_seq"])  # higher priority, then earliest created
            if best is None or key > best[0]:
                best = (key, r)
    if best is None:
        return Decimal("1.0")
    mult = best[1].get("multiplier_bps")
    if mult is None:
        return Decimal("1.0")
    return Decimal(mult) / Decimal(10000)


def occupancy_factor(occ_pct):
    if occ_pct >= OCC_HIGH_PCT:
        return OCC_HIGH_MULT
    if occ_pct >= OCC_MID_PCT:
        return OCC_MID_MULT
    return Decimal("1.0")


def last_minute_factor(check_in_dt):
    gap = whole_days(check_in_dt - store.now_clock())
    if gap <= LAST_MINUTE_DAYS:
        return LAST_MINUTE_MULT
    return Decimal("1.0")


def dynamic_quote(prop, check_in_dt, check_out_dt, exclude_booking_id=None):
    nights = whole_days(check_out_dt - check_in_dt)
    occ_pct = compute_occupancy_pct(prop["id"], check_in_dt, exclude_booking_id)
    base = Decimal(prop["base_nightly_rate_cents"])
    sf = seasonal_factor(prop["id"], check_in_dt)
    of = occupancy_factor(occ_pct)
    lf = last_minute_factor(check_in_dt)
    per_night = rhu(base * sf * of * lf)
    nightly_subtotal = per_night * nights
    cleaning = prop["cleaning_fee_cents"]
    taxable_base = nightly_subtotal + cleaning
    tax = rhu(as_dec(taxable_base) * active_permit_pct(prop["id"]) / 100)
    total = nightly_subtotal + cleaning + tax
    return {
        "per_night_rate_cents": per_night,
        "nights": nights,
        "nightly_subtotal_cents": nightly_subtotal,
        "cleaning_fee_cents": cleaning,
        "occupancy_tax_cents": tax,
        "total_cents": total,
        "occupancy_pct": occ_pct,
    }


def refund_pct_for(policy, days_to_check_in):
    if policy == "FLEXIBLE":
        return Decimal("1.00") if days_to_check_in >= FLEX_FULL_DAYS else Decimal("0.00")
    if policy == "MODERATE":
        if days_to_check_in >= MOD_FULL_DAYS:
            return Decimal("1.00")
        if days_to_check_in >= MOD_HALF_DAYS:
            return Decimal("0.50")
        return Decimal("0.00")
    if policy == "STRICT":
        return Decimal("1.00") if days_to_check_in >= STRICT_FULL_DAYS else Decimal("0.00")
    return Decimal("0.00")


def compute_refund(booking):
    check_in_dt = parse_dt(booking["check_in"])
    days = whole_days(check_in_dt - store.now_clock())
    pct = refund_pct_for(booking["cancellation_policy"], days)
    refundable_nightly = rhu(as_dec(booking["nightly_subtotal_cents"]) * pct)
    if booking["stay_status"] != "CHECKED_IN" and pct > 0:
        cleaning_refund = booking["quoted_cleaning_fee_cents"]
    else:
        cleaning_refund = 0
    tax_refund = rhu(as_dec(booking["occupancy_tax_cents"]) * pct)
    return refundable_nightly + cleaning_refund + tax_refund


# =============================================================================
# Cascades
# =============================================================================


def cancel_inspection_cascade(turnover):
    for insp in store.inspections.values():
        if insp["turnover_task_id"] == turnover["id"] and insp["status"] == "COMPLETED":
            insp["status"] = "CANCELLED"
            store.touch(insp)


def cancel_turnover_cascade(booking):
    for t in store.turnover_tasks.values():
        if t["booking_id"] == booking["id"] and t["status"] not in ("INSPECTED", "CANCELLED"):
            t["status"] = "CANCELLED"
            store.touch(t)
            cancel_inspection_cascade(t)


def cancel_booking_internal(booking):
    """Cancel side effects: refund, release nights (implicit), cascade turnover."""
    booking["refund_cents"] = compute_refund(booking)
    booking["stay_status"] = "CANCELLED"
    store.touch(booking)
    cancel_turnover_cascade(booking)


# =============================================================================
# Owner statement recompute
# =============================================================================


def qualifying_bookings(owner_id, year, month):
    owner_prop_ids = {p["id"] for p in store.properties.values() if p["owner_id"] == owner_id}
    result = []
    for b in store.bookings.values():
        if b["property_id"] not in owner_prop_ids:
            continue
        if b["stay_status"] != "CHECKED_OUT":
            continue
        co = parse_dt(b["check_out"])
        if co.year == year and co.month == month:
            result.append(b)
    return sorted(result, key=lambda b: b["_seq"])


def wo_owner_charges_for_statement(statement_id):
    total = 0
    for w in store.work_orders.values():
        if (
            w.get("owner_statement_id") == statement_id
            and w["billable_to"] == "OWNER"
            and w["status"] == "APPROVED"
        ):
            total += w["cost_cents"]
    return total


def recompute_statement(stmt, final=False):
    owner = store.owners[stmt["owner_id"]]
    mgmt_pct = as_dec(owner["default_management_fee_pct"])
    qbs = qualifying_bookings(stmt["owner_id"], stmt["period_year"], stmt["period_month"])
    gross = 0
    mgmt = 0
    cleaning = 0
    tax = 0
    for b in qbs:
        gross += b["nightly_subtotal_cents"]
        mgmt += rhu(as_dec(b["nightly_subtotal_cents"]) * mgmt_pct / 100)
        cleaning += b["quoted_cleaning_fee_cents"]
        tax += b["occupancy_tax_cents"]
    wo_charges = wo_owner_charges_for_statement(stmt["id"])
    stmt["gross_rental_cents"] = gross
    stmt["mgmt_fee_cents"] = mgmt
    stmt["cleaning_pass_through_cents"] = cleaning
    stmt["work_order_owner_charges_cents"] = wo_charges
    stmt["owner_payout_cents"] = gross - mgmt - wo_charges
    if final:
        stmt["tax_remitted_cents"] = tax
    return qbs


def add_statement_line(statement_id, line_type, amount_cents, source_ref):
    line = store.new_common(with_common=False)
    line.update(
        {
            "statement_id": statement_id,
            "line_type": line_type,
            "amount_cents": amount_cents,
            "source_ref": source_ref,
        }
    )
    store.statement_lines[line["id"]] = line
    return line


# =============================================================================
# Routes: Clock
# =============================================================================


@app.route("/_clock/set_current_utc", methods=["POST"])
def clock_set():
    _uid, role = authenticate()
    authorize(role, {"PlatformAdmin"})
    body = get_body()
    require_fields(body, ["to_iso8601"])
    store.set_clock(parse_dt(body["to_iso8601"]))
    return ok({}, code=200)


# =============================================================================
# Routes: Owner
# =============================================================================


@app.route("/owners", methods=["POST"])
def create_owner():
    _uid, role = authenticate()
    authorize(role, {"PlatformAdmin"})
    body = get_body()
    require_fields(body, ["legal_name", "email", "default_management_fee_pct"])
    payout = body.get("payout_method", "ACH")
    if payout is None:
        payout = "ACH"
    check_enum(payout, {"ACH", "CHECK", "WIRE"}, "payout_method")
    ent = store.new_common()
    ent.update(
        {
            "legal_name": body["legal_name"],
            "email": body["email"],
            "payout_method": payout,
            "default_management_fee_pct": body["default_management_fee_pct"],
            "status": "ACTIVE",
        }
    )
    store.owners[ent["id"]] = ent
    return object_response(ent, 201)


@app.route("/owners/<oid>", methods=["GET"])
def get_owner(oid):
    uid, role = authenticate()
    authorize(role, {"PlatformAdmin", "PropertyManager", "Owner"})
    ent = find(store.owners, oid)
    if role == "Owner" and ent["id"] != uid:
        raise err("ERR_UNAUTHORIZED", "Owners may read only their own record")
    return object_response(ent)


# =============================================================================
# Routes: Guest
# =============================================================================


@app.route("/guests", methods=["POST"])
def create_guest():
    # Fully public: no auth required.
    body = get_body()
    require_fields(body, ["full_name", "email"])
    gid_verified = body.get("government_id_verified", False)
    if gid_verified is None:
        gid_verified = False
    if not isinstance(gid_verified, bool):
        raise err("ERR_VALIDATION", "government_id_verified must be boolean")
    ent = store.new_common()
    ent.update(
        {
            "full_name": body["full_name"],
            "email": body["email"],
            "government_id_verified": gid_verified,
            "status": "UNSCREENED",
        }
    )
    store.guests[ent["id"]] = ent
    return object_response(ent, 201)


@app.route("/guests/<gid>", methods=["GET"])
def get_guest(gid):
    uid, role = authenticate()
    authorize(role, {"PlatformAdmin", "PropertyManager", "Guest"})
    ent = find(store.guests, gid)
    if role == "Guest" and ent["id"] != uid:
        raise err("ERR_UNAUTHORIZED", "Guests may read only their own record")
    return object_response(ent)


@app.route("/guests/<gid>/ban", methods=["POST"])
def ban_guest(gid):
    _uid, role = authenticate()
    authorize(role, {"PlatformAdmin", "PropertyManager"})
    ent = find(store.guests, gid)
    ent["status"] = "BANNED"
    store.touch(ent)
    return object_response(ent)


# =============================================================================
# Routes: Vendor
# =============================================================================


@app.route("/vendors", methods=["POST"])
def create_vendor():
    _uid, role = authenticate()
    authorize(role, {"PlatformAdmin", "PropertyManager"})
    body = get_body()
    require_fields(body, ["name", "vendor_type", "email"])
    check_enum(body["vendor_type"], {"CLEANER", "INSPECTOR", "MAINTENANCE", "GENERAL"}, "vendor_type")
    ent = store.new_common()
    ent.update(
        {
            "name": body["name"],
            "vendor_type": body["vendor_type"],
            "email": body["email"],
            "status": "ACTIVE",
        }
    )
    store.vendors[ent["id"]] = ent
    return object_response(ent, 201)


@app.route("/vendors/<vid>", methods=["GET"])
def get_vendor(vid):
    uid, role = authenticate()
    authorize(role, {"PlatformAdmin", "PropertyManager", "Vendor"})
    ent = find(store.vendors, vid)
    if role == "Vendor" and ent["id"] != uid:
        raise err("ERR_UNAUTHORIZED", "Vendors may read only their own record")
    return object_response(ent)


# =============================================================================
# Routes: Property
# =============================================================================


@app.route("/properties", methods=["POST"])
def create_property():
    _uid, role = authenticate()
    authorize(role, {"PlatformAdmin", "PropertyManager"})
    body = get_body()
    require_fields(
        body,
        [
            "owner_id",
            "address",
            "city",
            "state_code",
            "jurisdiction_code",
            "base_nightly_rate_cents",
            "cleaning_fee_cents",
            "max_occupancy",
        ],
    )
    # existence of owner (FK)
    find(store.owners, body["owner_id"])
    policy = body.get("default_cancellation_policy", "MODERATE")
    if policy is None:
        policy = "MODERATE"
    check_enum(policy, {"FLEXIBLE", "MODERATE", "STRICT"}, "default_cancellation_policy")
    ent = store.new_common()
    ent.update(
        {
            "owner_id": body["owner_id"],
            "address": body["address"],
            "city": body["city"],
            "state_code": body["state_code"],
            "jurisdiction_code": body["jurisdiction_code"],
            "base_nightly_rate_cents": body["base_nightly_rate_cents"],
            "cleaning_fee_cents": body["cleaning_fee_cents"],
            "max_occupancy": body["max_occupancy"],
            "default_cancellation_policy": policy,
            "status": "ONBOARDING",
        }
    )
    store.properties[ent["id"]] = ent
    return object_response(ent, 201)


@app.route("/properties/<pid>", methods=["GET"])
def get_property(pid):
    uid, role = authenticate()
    authorize(role, {"PlatformAdmin", "PropertyManager", "Owner"})
    ent = find(store.properties, pid)
    if role == "Owner" and ent["owner_id"] != uid:
        raise err("ERR_UNAUTHORIZED", "Owners may read only their own properties")
    return object_response(ent)


@app.route("/properties", methods=["GET"])
def list_properties():
    uid, role = authenticate()
    authorize(role, {"PlatformAdmin", "PropertyManager", "Owner"})
    items = list(store.properties.values())
    if role == "Owner":
        items = [p for p in items if p["owner_id"] == uid]
    owner_id = request.args.get("owner_id")
    if owner_id is not None:
        items = [p for p in items if p["owner_id"] == owner_id]
    status = request.args.get("status")
    if status is not None:
        items = [p for p in items if p["status"] == status]
    return paginate(items)


@app.route("/properties/<pid>/list", methods=["POST"])
def list_property(pid):
    _uid, role = authenticate()
    authorize(role, {"PropertyManager"})
    prop = find(store.properties, pid)
    if prop["status"] not in ("ONBOARDING", "UNLISTED"):
        raise err("ERR_INVALID_STATE", "Property cannot be listed from its current state")
    active_permits = [
        p for p in store.permits.values()
        if p["property_id"] == pid and p["status"] == "ACTIVE"
    ]
    if not active_permits:
        raise err("ERR_PERMIT_NOT_ACTIVE", "Property has no ACTIVE permit")
    if not any(store.now_clock() <= parse_dt(p["expires_on"]) for p in active_permits):
        raise err("ERR_PERMIT_EXPIRED", "Active permit is expired")
    prop["status"] = "LISTED"
    store.touch(prop)
    return object_response(prop)


@app.route("/properties/<pid>/unlist", methods=["POST"])
def unlist_property(pid):
    _uid, role = authenticate()
    authorize(role, {"PropertyManager"})
    prop = find(store.properties, pid)
    if prop["status"] != "LISTED":
        raise err("ERR_INVALID_STATE", "Only LISTED properties can be unlisted")
    prop["status"] = "UNLISTED"
    store.touch(prop)
    return object_response(prop)


@app.route("/properties/<pid>/offboard", methods=["POST"])
def offboard_property(pid):
    uid, role = authenticate()
    authorize(role, {"PropertyManager", "PlatformAdmin", "Owner"})
    prop = find(store.properties, pid)
    if role == "Owner" and prop["owner_id"] != uid:
        raise err("ERR_UNAUTHORIZED", "Owners may offboard only their own properties")
    if prop["status"] not in ("ONBOARDING", "LISTED", "UNLISTED"):
        raise err("ERR_INVALID_STATE", "Property cannot be offboarded from its current state")
    prop["status"] = "OFFBOARDED"
    store.touch(prop)
    # cascade: cancel non-terminal bookings on this property
    for b in list(store.bookings.values()):
        if b["property_id"] == pid and b["stay_status"] in ("HOLD", "CONFIRMED"):
            cancel_booking_internal(b)
    # delist channel listings
    for cl in store.channel_listings.values():
        if cl["property_id"] == pid and cl["status"] != "DELISTED":
            cl["status"] = "DELISTED"
            store.touch(cl)
    return object_response(prop)


@app.route("/properties/<pid>/pricing-rules", methods=["POST"])
def create_pricing_rule(pid):
    _uid, role = authenticate()
    authorize(role, {"PropertyManager"})
    prop = find(store.properties, pid)
    body = get_body()
    require_fields(body, ["rule_type", "priority", "expected_property_version"])
    check_enum(body["rule_type"], {"SEASONAL", "OCCUPANCY", "LAST_MINUTE", "MIN_STAY"}, "rule_type")
    # OCC (priority 11 — last)
    if body["expected_property_version"] != prop["version"]:
        raise err("ERR_STALE_VERSION", "expected_property_version does not match property version")
    sd = body.get("start_date")
    ed = body.get("end_date")
    if sd is not None:
        parse_dt(sd)
    if ed is not None:
        parse_dt(ed)
    rule_type = body["rule_type"]
    new_start = parse_dt(sd) if sd is not None else None
    new_end = parse_dt(ed) if ed is not None else None
    # supersede same-type active overlapping rules
    for r in store.pricing_rules.values():
        if r["property_id"] != pid or not r.get("active") or r["rule_type"] != rule_type:
            continue
        r_start = parse_dt(r["start_date"]) if r.get("start_date") is not None else None
        r_end = parse_dt(r["end_date"]) if r.get("end_date") is not None else None
        if _windows_overlap(new_start, new_end, r_start, r_end):
            r["active"] = False
            store.touch(r)
    ent = store.new_common()
    ent.update(
        {
            "property_id": pid,
            "rule_type": rule_type,
            "multiplier_bps": body.get("multiplier_bps"),
            "min_nights": body.get("min_nights"),
            "start_date": sd,
            "end_date": ed,
            "priority": body["priority"],
            "active": True,
        }
    )
    store.pricing_rules[ent["id"]] = ent
    # bump property version
    prop["version"] = prop["version"] + 1
    prop["updated_at"] = store.iso_now()
    return object_response(ent, 201)


def _windows_overlap(a_start, a_end, b_start, b_end):
    lo_a = a_start if a_start is not None else datetime.min.replace(tzinfo=timezone.utc)
    hi_a = a_end if a_end is not None else datetime.max.replace(tzinfo=timezone.utc)
    lo_b = b_start if b_start is not None else datetime.min.replace(tzinfo=timezone.utc)
    hi_b = b_end if b_end is not None else datetime.max.replace(tzinfo=timezone.utc)
    return lo_a < hi_b and lo_b < hi_a


@app.route("/properties/<pid>/pricing-rules", methods=["GET"])
def list_pricing_rules(pid):
    _uid, role = authenticate()
    authorize(role, {"PlatformAdmin", "PropertyManager"})
    find(store.properties, pid)
    items = [r for r in store.pricing_rules.values() if r["property_id"] == pid]
    rt = request.args.get("rule_type")
    if rt is not None:
        items = [r for r in items if r["rule_type"] == rt]
    active = request.args.get("active")
    if active is not None:
        want = active.lower() == "true"
        items = [r for r in items if bool(r.get("active")) == want]
    return paginate(items)


@app.route("/pricing-rules/<rid>", methods=["GET"])
def get_pricing_rule(rid):
    _uid, role = authenticate()
    authorize(role, {"PlatformAdmin", "PropertyManager"})
    ent = find(store.pricing_rules, rid)
    return object_response(ent)


@app.route("/properties/<pid>/quote", methods=["POST"])
def quote_property(pid):
    # Fully public.
    prop = maybe(store.properties, pid)
    if prop is None:
        raise err("ERR_NOT_FOUND", "Property not found")
    body = get_body()
    require_fields(body, ["check_in", "check_out"])
    ci = parse_dt(body["check_in"])
    co = parse_dt(body["check_out"])
    if co <= ci:
        raise err("ERR_VALIDATION", "check_out must be after check_in")
    q = dynamic_quote(prop, ci, co, exclude_booking_id=None)
    return ok(q, code=200)


# =============================================================================
# Routes: Permit
# =============================================================================


@app.route("/permits", methods=["POST"])
def create_permit():
    _uid, role = authenticate()
    authorize(role, {"PlatformAdmin", "PropertyManager"})
    body = get_body()
    require_fields(
        body,
        ["property_id", "permit_number", "jurisdiction_code", "occupancy_tax_pct", "issued_on", "expires_on"],
    )
    find(store.properties, body["property_id"])
    parse_dt(body["issued_on"])
    parse_dt(body["expires_on"])
    ent = store.new_common()
    ent.update(
        {
            "property_id": body["property_id"],
            "permit_number": body["permit_number"],
            "jurisdiction_code": body["jurisdiction_code"],
            "occupancy_tax_pct": body["occupancy_tax_pct"],
            "issued_on": body["issued_on"],
            "expires_on": body["expires_on"],
            "status": "PENDING",
        }
    )
    store.permits[ent["id"]] = ent
    return object_response(ent, 201)


@app.route("/permits/<pid>", methods=["GET"])
def get_permit(pid):
    _uid, role = authenticate()
    authorize(role, {"PlatformAdmin", "PropertyManager"})
    ent = find(store.permits, pid)
    return object_response(ent)


@app.route("/permits", methods=["GET"])
def list_permits():
    _uid, role = authenticate()
    authorize(role, {"PlatformAdmin", "PropertyManager"})
    items = list(store.permits.values())
    prop_id = request.args.get("property_id")
    if prop_id is not None:
        items = [p for p in items if p["property_id"] == prop_id]
    status = request.args.get("status")
    if status is not None:
        items = [p for p in items if p["status"] == status]
    return paginate(items)


@app.route("/permits/<pid>/activate", methods=["POST"])
def activate_permit(pid):
    _uid, role = authenticate()
    authorize(role, {"PlatformAdmin", "PropertyManager"})
    ent = find(store.permits, pid)
    if ent["status"] != "PENDING":
        raise err("ERR_INVALID_STATE", "Only PENDING permits can be activated")
    if store.now_clock() > parse_dt(ent["expires_on"]):
        raise err("ERR_PERMIT_EXPIRED", "Permit is expired")
    ent["status"] = "ACTIVE"
    store.touch(ent)
    return object_response(ent)


@app.route("/permits/<pid>/revoke", methods=["POST"])
def revoke_permit(pid):
    _uid, role = authenticate()
    authorize(role, {"PlatformAdmin", "PropertyManager"})
    ent = find(store.permits, pid)
    if ent["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Only ACTIVE permits can be revoked")
    ent["status"] = "REVOKED"
    store.touch(ent)
    prop = maybe(store.properties, ent["property_id"])
    if prop is not None and prop["status"] == "LISTED":
        prop["status"] = "UNLISTED"
        store.touch(prop)
    return object_response(ent)


# =============================================================================
# Routes: ChannelListing
# =============================================================================


@app.route("/channel-listings", methods=["POST"])
def create_channel_listing():
    _uid, role = authenticate()
    authorize(role, {"PropertyManager"})
    body = get_body()
    require_fields(body, ["property_id", "channel"])
    find(store.properties, body["property_id"])
    check_enum(body["channel"], {"AIRBNB", "VRBO", "DIRECT", "BOOKING_COM"}, "channel")
    ent = store.new_common()
    ent.update(
        {
            "property_id": body["property_id"],
            "channel": body["channel"],
            "external_listing_ref": body.get("external_listing_ref"),
            "status": "DRAFT",
        }
    )
    store.channel_listings[ent["id"]] = ent
    return object_response(ent, 201)


@app.route("/channel-listings/<cid>", methods=["GET"])
def get_channel_listing(cid):
    _uid, role = authenticate()
    authorize(role, {"PlatformAdmin", "PropertyManager"})
    ent = find(store.channel_listings, cid)
    return object_response(ent)


@app.route("/channel-listings", methods=["GET"])
def list_channel_listings():
    _uid, role = authenticate()
    authorize(role, {"PlatformAdmin", "PropertyManager"})
    items = list(store.channel_listings.values())
    prop_id = request.args.get("property_id")
    if prop_id is not None:
        items = [c for c in items if c["property_id"] == prop_id]
    channel = request.args.get("channel")
    if channel is not None:
        items = [c for c in items if c["channel"] == channel]
    status = request.args.get("status")
    if status is not None:
        items = [c for c in items if c["status"] == status]
    return paginate(items)


@app.route("/channel-listings/<cid>/sync", methods=["POST"])
def sync_channel_listing(cid):
    _uid, role = authenticate()
    authorize(role, {"PropertyManager"})
    ent = find(store.channel_listings, cid)
    if ent["status"] not in ("DRAFT", "PAUSED"):
        raise err("ERR_INVALID_STATE", "Channel listing cannot be synced from its current state")
    prop = maybe(store.properties, ent["property_id"])
    if prop is None or prop["status"] != "LISTED":
        raise err("ERR_INVALID_STATE", "Property must be LISTED to sync a channel listing")
    ent["status"] = "SYNCED"
    store.touch(ent)
    return object_response(ent)


@app.route("/channel-listings/<cid>/pause", methods=["POST"])
def pause_channel_listing(cid):
    _uid, role = authenticate()
    authorize(role, {"PropertyManager"})
    ent = find(store.channel_listings, cid)
    if ent["status"] != "SYNCED":
        raise err("ERR_INVALID_STATE", "Only SYNCED channel listings can be paused")
    ent["status"] = "PAUSED"
    store.touch(ent)
    return object_response(ent)


# =============================================================================
# Routes: Booking
# =============================================================================


@app.route("/bookings", methods=["POST"])
def create_booking():
    uid, role = authenticate()
    authorize(role, {"Guest", "PropertyManager", "Anonymous"})
    body = get_body()
    # existence (priority 3): resolve provided FKs left-to-right
    prop = None
    if body.get("property_id") is not None:
        prop = find(store.properties, body["property_id"])
    guest = None
    if body.get("guest_id") is not None:
        guest = find(store.guests, body["guest_id"])
    # ownership for Guest role
    if role == "Guest" and body.get("guest_id") is not None and body["guest_id"] != uid:
        raise err("ERR_UNAUTHORIZED", "Guests may only create their own bookings")
    # body well-formedness (priority 4)
    require_fields(body, ["property_id", "guest_id", "check_in", "check_out"])
    ci = parse_dt(body["check_in"])
    co = parse_dt(body["check_out"])
    if co <= ci:
        raise err("ERR_VALIDATION", "check_out must be after check_in")
    policy = body.get("cancellation_policy")
    if policy is None:
        policy = prop["default_cancellation_policy"]
    else:
        check_enum(policy, {"FLEXIBLE", "MODERATE", "STRICT"}, "cancellation_policy")
    # state (priority 5): property LISTED
    if prop["status"] != "LISTED":
        raise err("ERR_PROPERTY_NOT_BOOKABLE", "Property is not LISTED")
    # business-safety (priority 6): guest not BANNED
    if guest["status"] == "BANNED":
        raise err("ERR_GUEST_BANNED", "Guest is banned")
    # domain-constraint (priority 8): min stay
    nights = whole_days(co - ci)
    _check_min_stay(prop["id"], nights)
    # temporal (priority 9): overlap
    for b in store.bookings.values():
        if b["property_id"] != prop["id"]:
            continue
        if b["stay_status"] not in ("HOLD", "CONFIRMED", "CHECKED_IN"):
            continue
        b_ci = parse_dt(b["check_in"])
        b_co = parse_dt(b["check_out"])
        if ci < b_co and b_ci < co:
            raise err("ERR_DATES_UNAVAILABLE", "Requested dates overlap an existing booking")
    # compute price snapshot
    q = dynamic_quote(prop, ci, co, exclude_booking_id=None)
    ent = store.new_common()
    ent.update(
        {
            "property_id": prop["id"],
            "guest_id": guest["id"],
            "check_in": body["check_in"],
            "check_out": body["check_out"],
            "nights": q["nights"],
            "cancellation_policy": policy,
            "quoted_per_night_cents": q["per_night_rate_cents"],
            "nightly_subtotal_cents": q["nightly_subtotal_cents"],
            "quoted_cleaning_fee_cents": q["cleaning_fee_cents"],
            "occupancy_tax_cents": q["occupancy_tax_cents"],
            "total_cents": q["total_cents"],
            "refund_cents": 0,
            "stay_status": "HOLD",
            "screening_status": "PENDING",
            "messages": [],
        }
    )
    store.bookings[ent["id"]] = ent
    return object_response(ent, 201)


def _check_min_stay(property_id, nights):
    for r in store.pricing_rules.values():
        if r["property_id"] != property_id or not r.get("active"):
            continue
        if r["rule_type"] != "MIN_STAY":
            continue
        mn = r.get("min_nights")
        if mn is not None and nights < mn:
            raise err("ERR_MIN_STAY_NOT_MET", "Minimum stay not met")


def _booking_owner_check(booking, uid, role):
    if role == "Guest" and booking["guest_id"] != uid:
        raise err("ERR_UNAUTHORIZED", "Guests may act only on their own bookings")


@app.route("/bookings/<bid>", methods=["GET"])
def get_booking(bid):
    uid, role = authenticate()
    authorize(role, {"PlatformAdmin", "PropertyManager", "Guest"})
    ent = find(store.bookings, bid)
    _booking_owner_check(ent, uid, role)
    return object_response(ent)


@app.route("/bookings", methods=["GET"])
def list_bookings():
    uid, role = authenticate()
    authorize(role, {"PlatformAdmin", "PropertyManager", "Guest"})
    items = list(store.bookings.values())
    if role == "Guest":
        items = [b for b in items if b["guest_id"] == uid]
    prop_id = request.args.get("property_id")
    if prop_id is not None:
        items = [b for b in items if b["property_id"] == prop_id]
    guest_id = request.args.get("guest_id")
    if guest_id is not None:
        items = [b for b in items if b["guest_id"] == guest_id]
    ss = request.args.get("stay_status")
    if ss is not None:
        items = [b for b in items if b["stay_status"] == ss]
    scs = request.args.get("screening_status")
    if scs is not None:
        items = [b for b in items if b["screening_status"] == scs]
    return paginate(items)


@app.route("/bookings/<bid>/screen", methods=["POST"])
def screen_booking(bid):
    _uid, role = authenticate()
    authorize(role, {"PropertyManager"})
    ent = find(store.bookings, bid)
    body = get_body()
    require_fields(body, ["decision"])
    check_enum(body["decision"], {"APPROVED", "DECLINED"}, "decision")
    if ent["screening_status"] != "PENDING":
        raise err("ERR_INVALID_STATE", "Screening already decided")
    if body["decision"] == "APPROVED":
        guest = store.guests[ent["guest_id"]]
        if guest["status"] == "BANNED":
            raise err("ERR_GUEST_BANNED", "Guest is banned")
        ent["screening_status"] = "APPROVED"
        store.touch(ent)
    else:
        ent["screening_status"] = "DECLINED"
        ent["stay_status"] = "CANCELLED"
        store.touch(ent)
    return object_response(ent)


@app.route("/bookings/<bid>/confirm", methods=["POST"])
def confirm_booking(bid):
    uid, role = authenticate()
    authorize(role, {"PropertyManager", "Guest"})
    ent = find(store.bookings, bid)
    _booking_owner_check(ent, uid, role)
    if ent["stay_status"] != "HOLD":
        raise err("ERR_INVALID_STATE", "Only HOLD bookings can be confirmed")
    if ent["screening_status"] != "APPROVED":
        raise err("ERR_SCREENING_NOT_APPROVED", "Screening is not APPROVED")
    ent["stay_status"] = "CONFIRMED"
    store.touch(ent)
    return object_response(ent)


@app.route("/bookings/<bid>/check-in", methods=["POST"])
def checkin_booking(bid):
    _uid, role = authenticate()
    authorize(role, {"PropertyManager"})
    ent = find(store.bookings, bid)
    if ent["stay_status"] != "CONFIRMED":
        raise err("ERR_INVALID_STATE", "Only CONFIRMED bookings can be checked in")
    if store.now_clock() < parse_dt(ent["check_in"]):
        raise err("ERR_INVALID_STATE", "Clock is before check_in")
    # most recent turnover on property (if any) must be INSPECTED
    turnovers = [t for t in store.turnover_tasks.values() if t["property_id"] == ent["property_id"]]
    if turnovers:
        latest = max(turnovers, key=lambda t: t["_seq"])
        if latest["status"] != "INSPECTED":
            raise err("ERR_TURNOVER_NOT_READY", "Most recent turnover is not INSPECTED")
    ent["stay_status"] = "CHECKED_IN"
    store.touch(ent)
    return object_response(ent)


@app.route("/bookings/<bid>/check-out", methods=["POST"])
def checkout_booking(bid):
    _uid, role = authenticate()
    authorize(role, {"PropertyManager"})
    ent = find(store.bookings, bid)
    if ent["stay_status"] != "CHECKED_IN":
        raise err("ERR_INVALID_STATE", "Only CHECKED_IN bookings can be checked out")
    ent["stay_status"] = "CHECKED_OUT"
    store.touch(ent)
    return object_response(ent)


@app.route("/bookings/<bid>/cancel", methods=["POST"])
def cancel_booking(bid):
    uid, role = authenticate()
    authorize(role, {"Guest", "PropertyManager"})
    ent = find(store.bookings, bid)
    _booking_owner_check(ent, uid, role)
    if ent["stay_status"] not in ("HOLD", "CONFIRMED"):
        raise err("ERR_INVALID_STATE", "Only HOLD or CONFIRMED bookings can be cancelled")
    cancel_booking_internal(ent)
    return object_response(ent)


@app.route("/bookings/<bid>/messages", methods=["POST"])
def add_message(bid):
    uid, role = authenticate()
    authorize(role, {"Guest", "PropertyManager"})
    ent = find(store.bookings, bid)
    _booking_owner_check(ent, uid, role)
    body = get_body()
    require_fields(body, ["body"])
    msg = {
        "sender_role": body.get("sender_role"),
        "body": body["body"],
        "at": store.iso_now(),
    }
    ent["messages"].append(msg)
    store.touch(ent)
    return object_response(ent, 201)


# =============================================================================
# Routes: TurnoverTask
# =============================================================================


@app.route("/turnover-tasks", methods=["POST"])
def create_turnover():
    _uid, role = authenticate()
    authorize(role, {"PropertyManager"})
    body = get_body()
    # existence (left-to-right per body order)
    booking = None
    if body.get("booking_id") is not None:
        booking = find(store.bookings, body["booking_id"])
    if body.get("property_id") is not None:
        find(store.properties, body["property_id"])
    vendor = None
    if body.get("assigned_vendor_id") is not None:
        vendor = find(store.vendors, body["assigned_vendor_id"])
    require_fields(
        body,
        ["booking_id", "property_id", "assigned_vendor_id", "scheduled_window_start", "scheduled_window_end"],
    )
    start = parse_dt(body["scheduled_window_start"])
    end = parse_dt(body["scheduled_window_end"])
    # domain constraint (priority 8): vendor must be CLEANER
    if vendor["vendor_type"] != "CLEANER":
        raise err("ERR_VENDOR_NOT_CLEANER", "Assigned vendor is not a CLEANER")
    # temporal (priority 9): buffered overlap for the same vendor
    buf = timedelta(minutes=TURNOVER_BUFFER_MINUTES)
    for t in store.turnover_tasks.values():
        if t["assigned_vendor_id"] != vendor["id"]:
            continue
        if t["status"] not in ("SCHEDULED", "IN_PROGRESS", "CLEANED", "FAILED"):
            continue
        t_start = parse_dt(t["scheduled_window_start"]) - buf
        t_end = parse_dt(t["scheduled_window_end"]) + buf
        if start <= t_end and t_start <= end:
            raise err("ERR_VENDOR_UNAVAILABLE", "Vendor is unavailable in the requested window")
    ent = store.new_common()
    ent.update(
        {
            "booking_id": booking["id"],
            "property_id": body["property_id"],
            "assigned_vendor_id": vendor["id"],
            "scheduled_window_start": body["scheduled_window_start"],
            "scheduled_window_end": body["scheduled_window_end"],
            "status": "SCHEDULED",
        }
    )
    store.turnover_tasks[ent["id"]] = ent
    return object_response(ent, 201)


@app.route("/turnover-tasks/<tid>", methods=["GET"])
def get_turnover(tid):
    uid, role = authenticate()
    authorize(role, {"PlatformAdmin", "PropertyManager", "Vendor"})
    ent = find(store.turnover_tasks, tid)
    if role == "Vendor" and ent["assigned_vendor_id"] != uid:
        raise err("ERR_UNAUTHORIZED", "Vendors may read only their own turnovers")
    return object_response(ent)


@app.route("/turnover-tasks", methods=["GET"])
def list_turnovers():
    uid, role = authenticate()
    authorize(role, {"PlatformAdmin", "PropertyManager", "Vendor"})
    items = list(store.turnover_tasks.values())
    if role == "Vendor":
        items = [t for t in items if t["assigned_vendor_id"] == uid]
    for key in ("booking_id", "property_id", "assigned_vendor_id", "status"):
        val = request.args.get(key)
        if val is not None:
            items = [t for t in items if t[key] == val]
    return paginate(items)


@app.route("/turnover-tasks/<tid>/start", methods=["POST"])
def start_turnover(tid):
    uid, role = authenticate()
    authorize(role, {"Vendor"})
    ent = find(store.turnover_tasks, tid)
    if ent["assigned_vendor_id"] != uid:
        raise err("ERR_UNAUTHORIZED", "Only the assigned vendor may start the turnover")
    if ent["status"] not in ("SCHEDULED", "FAILED"):
        raise err("ERR_INVALID_STATE", "Turnover cannot be started from its current state")
    ent["status"] = "IN_PROGRESS"
    store.touch(ent)
    return object_response(ent)


@app.route("/turnover-tasks/<tid>/complete", methods=["POST"])
def complete_turnover(tid):
    uid, role = authenticate()
    authorize(role, {"Vendor"})
    ent = find(store.turnover_tasks, tid)
    if ent["assigned_vendor_id"] != uid:
        raise err("ERR_UNAUTHORIZED", "Only the assigned vendor may complete the turnover")
    if ent["status"] != "IN_PROGRESS":
        raise err("ERR_INVALID_STATE", "Only IN_PROGRESS turnovers can be completed")
    ent["status"] = "CLEANED"
    store.touch(ent)
    return object_response(ent)


@app.route("/turnover-tasks/<tid>/cancel", methods=["POST"])
def cancel_turnover(tid):
    _uid, role = authenticate()
    authorize(role, {"PropertyManager"})
    ent = find(store.turnover_tasks, tid)
    if ent["status"] not in ("SCHEDULED", "IN_PROGRESS", "CLEANED"):
        raise err("ERR_INVALID_STATE", "Turnover cannot be cancelled from its current state")
    ent["status"] = "CANCELLED"
    store.touch(ent)
    cancel_inspection_cascade(ent)
    return object_response(ent)


# =============================================================================
# Routes: Inspection
# =============================================================================


@app.route("/inspections", methods=["POST"])
def create_inspection():
    _uid, role = authenticate()
    authorize(role, {"Vendor", "PropertyManager"})
    body = get_body()
    task = None
    if body.get("turnover_task_id") is not None:
        task = find(store.turnover_tasks, body["turnover_task_id"])
    if body.get("inspector_vendor_id") is not None:
        find(store.vendors, body["inspector_vendor_id"])
    require_fields(body, ["turnover_task_id", "inspector_vendor_id", "result"])
    check_enum(body["result"], {"PASS", "FAIL"}, "result")
    # state (priority 5): turnover CLEANED
    if task["status"] != "CLEANED":
        raise err("ERR_TURNOVER_NOT_CLEANED", "Turnover is not in CLEANED status")
    # business-safety (priority 6): SoD
    if body["inspector_vendor_id"] == task["assigned_vendor_id"]:
        raise err("ERR_SOD_INSPECTOR_IS_CLEANER", "Inspector must differ from the cleaner")
    ent = store.new_common()
    ent.update(
        {
            "turnover_task_id": task["id"],
            "inspector_vendor_id": body["inspector_vendor_id"],
            "result": body["result"],
            "notes": body.get("notes"),
            "status": "COMPLETED",
        }
    )
    store.inspections[ent["id"]] = ent
    # cascade to turnover
    if body["result"] == "PASS":
        task["status"] = "INSPECTED"
    else:
        task["status"] = "FAILED"
    store.touch(task)
    return object_response(ent, 201)


@app.route("/inspections/<iid>", methods=["GET"])
def get_inspection(iid):
    _uid, role = authenticate()
    authorize(role, {"PlatformAdmin", "PropertyManager", "Vendor"})
    ent = find(store.inspections, iid)
    return object_response(ent)


@app.route("/inspections", methods=["GET"])
def list_inspections():
    _uid, role = authenticate()
    authorize(role, {"PlatformAdmin", "PropertyManager", "Vendor"})
    items = list(store.inspections.values())
    for key in ("turnover_task_id", "inspector_vendor_id", "result"):
        val = request.args.get(key)
        if val is not None:
            items = [i for i in items if i[key] == val]
    return paginate(items)


# =============================================================================
# Routes: WorkOrder
# =============================================================================


@app.route("/work-orders", methods=["POST"])
def create_work_order():
    uid, role = authenticate()
    authorize(role, {"PropertyManager", "Owner", "Vendor"})
    body = get_body()
    prop = None
    if body.get("property_id") is not None:
        prop = find(store.properties, body["property_id"])
    if body.get("vendor_id") is not None:
        find(store.vendors, body["vendor_id"])
    if role == "Owner" and prop is not None and prop["owner_id"] != uid:
        raise err("ERR_UNAUTHORIZED", "Owners may create work orders only on their own properties")
    require_fields(body, ["property_id", "description", "cost_cents", "billable_to"])
    require_int(body, "cost_cents", min_value=0)
    check_enum(body["billable_to"], {"OWNER", "GUEST", "COMPANY"}, "billable_to")
    requires_owner_approval = (
        body["billable_to"] == "OWNER" and body["cost_cents"] > OWNER_APPROVAL_THRESHOLD_CENTS
    )
    ent = store.new_common()
    ent.update(
        {
            "property_id": prop["id"],
            "vendor_id": body.get("vendor_id"),
            "owner_statement_id": None,
            "description": body["description"],
            "cost_cents": body["cost_cents"],
            "billable_to": body["billable_to"],
            "requires_owner_approval": requires_owner_approval,
            "status": "OPEN",
        }
    )
    store.work_orders[ent["id"]] = ent
    return object_response(ent, 201)


def _wo_owner_scope(wo, uid, role):
    prop = store.properties.get(wo["property_id"])
    if role == "Owner" and (prop is None or prop["owner_id"] != uid):
        raise err("ERR_UNAUTHORIZED", "Owners may act only on their own work orders")
    if role == "Vendor" and wo.get("vendor_id") != uid:
        raise err("ERR_UNAUTHORIZED", "Vendors may act only on their assigned work orders")


@app.route("/work-orders/<wid>", methods=["GET"])
def get_work_order(wid):
    uid, role = authenticate()
    authorize(role, {"PlatformAdmin", "PropertyManager", "Owner", "Vendor"})
    ent = find(store.work_orders, wid)
    _wo_owner_scope(ent, uid, role)
    return object_response(ent)


@app.route("/work-orders", methods=["GET"])
def list_work_orders():
    uid, role = authenticate()
    authorize(role, {"PlatformAdmin", "PropertyManager", "Owner", "Vendor"})
    items = list(store.work_orders.values())
    if role == "Owner":
        own_props = {p["id"] for p in store.properties.values() if p["owner_id"] == uid}
        items = [w for w in items if w["property_id"] in own_props]
    if role == "Vendor":
        items = [w for w in items if w.get("vendor_id") == uid]
    for key in ("property_id", "vendor_id", "owner_statement_id", "status", "billable_to"):
        val = request.args.get(key)
        if val is not None:
            items = [w for w in items if w.get(key) == val]
    return paginate(items)


@app.route("/work-orders/<wid>/assign", methods=["POST"])
def assign_work_order(wid):
    _uid, role = authenticate()
    authorize(role, {"PropertyManager"})
    ent = find(store.work_orders, wid)
    body = get_body()
    vendor = None
    if body.get("vendor_id") is not None:
        vendor = find(store.vendors, body["vendor_id"])
    require_fields(body, ["vendor_id"])
    if ent["status"] != "OPEN":
        raise err("ERR_INVALID_STATE", "Only OPEN work orders can be assigned")
    if vendor["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Assigned vendor is not ACTIVE")
    ent["vendor_id"] = vendor["id"]
    ent["status"] = "ASSIGNED"
    store.touch(ent)
    return object_response(ent)


@app.route("/work-orders/<wid>/start", methods=["POST"])
def start_work_order(wid):
    uid, role = authenticate()
    authorize(role, {"Vendor"})
    ent = find(store.work_orders, wid)
    if ent.get("vendor_id") != uid:
        raise err("ERR_UNAUTHORIZED", "Only the assigned vendor may start the work order")
    if ent["status"] != "ASSIGNED":
        raise err("ERR_INVALID_STATE", "Only ASSIGNED work orders can be started")
    ent["status"] = "IN_PROGRESS"
    store.touch(ent)
    return object_response(ent)


@app.route("/work-orders/<wid>/request-info", methods=["POST"])
def request_info_work_order(wid):
    _uid, role = authenticate()
    authorize(role, {"Vendor", "PropertyManager"})
    ent = find(store.work_orders, wid)
    if ent["status"] != "IN_PROGRESS":
        raise err("ERR_INVALID_STATE", "Only IN_PROGRESS work orders can be sent to NEEDS_INFO")
    ent["status"] = "NEEDS_INFO"
    store.touch(ent)
    return object_response(ent)


@app.route("/work-orders/<wid>/resume", methods=["POST"])
def resume_work_order(wid):
    _uid, role = authenticate()
    authorize(role, {"PropertyManager"})
    ent = find(store.work_orders, wid)
    if ent["status"] != "NEEDS_INFO":
        raise err("ERR_INVALID_STATE", "Only NEEDS_INFO work orders can be resumed")
    ent["status"] = "ASSIGNED"
    store.touch(ent)
    return object_response(ent)


@app.route("/work-orders/<wid>/complete", methods=["POST"])
def complete_work_order(wid):
    uid, role = authenticate()
    authorize(role, {"Vendor"})
    ent = find(store.work_orders, wid)
    if ent.get("vendor_id") != uid:
        raise err("ERR_UNAUTHORIZED", "Only the assigned vendor may complete the work order")
    if ent["status"] != "IN_PROGRESS":
        raise err("ERR_INVALID_STATE", "Only IN_PROGRESS work orders can be completed")
    ent["status"] = "COMPLETED"
    store.touch(ent)
    return object_response(ent)


@app.route("/work-orders/<wid>/approve", methods=["POST"])
def approve_work_order(wid):
    uid, role = authenticate()
    authorize(role, {"PropertyManager", "Owner"})
    ent = find(store.work_orders, wid)
    prop = store.properties.get(ent["property_id"])
    if role == "Owner" and (prop is None or prop["owner_id"] != uid):
        raise err("ERR_UNAUTHORIZED", "Owners may act only on their own work orders")
    if ent["status"] != "COMPLETED":
        raise err("ERR_INVALID_STATE", "Only COMPLETED work orders can be approved")
    # referential (priority 7): over-threshold owner-billable requires Owner actor
    if ent["requires_owner_approval"]:
        if not (role == "Owner" and prop is not None and prop["owner_id"] == uid):
            raise err("ERR_OWNER_APPROVAL_REQUIRED", "Owner approval required for this work order")
    ent["status"] = "APPROVED"
    store.touch(ent)
    # cascade: billable_to OWNER posts a charge line to the DRAFT statement
    if ent["billable_to"] == "OWNER" and prop is not None:
        stmt = _current_draft_statement(prop["owner_id"])
        if stmt is not None:
            ent["owner_statement_id"] = stmt["id"]
            add_statement_line(stmt["id"], "WORK_ORDER_CHARGE", -ent["cost_cents"], ent["id"])
            recompute_statement(stmt, final=False)
            store.touch(stmt)
    return object_response(ent)


def _current_draft_statement(owner_id):
    clock = store.now_clock()
    candidates = [
        s for s in store.owner_statements.values()
        if s["owner_id"] == owner_id
        and s["status"] == "DRAFT"
        and s["period_year"] == clock.year
        and s["period_month"] == clock.month
    ]
    if not candidates:
        return None
    return sorted(candidates, key=lambda s: s["_seq"])[0]


@app.route("/work-orders/<wid>/reject", methods=["POST"])
def reject_work_order(wid):
    uid, role = authenticate()
    authorize(role, {"PropertyManager", "Owner"})
    ent = find(store.work_orders, wid)
    prop = store.properties.get(ent["property_id"])
    if role == "Owner" and (prop is None or prop["owner_id"] != uid):
        raise err("ERR_UNAUTHORIZED", "Owners may act only on their own work orders")
    if ent["status"] != "COMPLETED":
        raise err("ERR_INVALID_STATE", "Only COMPLETED work orders can be rejected")
    ent["status"] = "REJECTED"
    store.touch(ent)
    return object_response(ent)


# =============================================================================
# Routes: OwnerStatement
# =============================================================================


@app.route("/owner-statements", methods=["POST"])
def create_owner_statement():
    _uid, role = authenticate()
    authorize(role, {"PropertyManager", "PlatformAdmin"})
    body = get_body()
    owner = None
    if body.get("owner_id") is not None:
        owner = find(store.owners, body["owner_id"])
    require_fields(body, ["owner_id", "period_year", "period_month"])
    require_int(body, "period_year")
    month = require_int(body, "period_month")
    if month < 1 or month > 12:
        raise err("ERR_VALIDATION", "period_month must be 1-12")
    ent = store.new_common()
    ent.update(
        {
            "owner_id": owner["id"],
            "period_year": body["period_year"],
            "period_month": body["period_month"],
            "gross_rental_cents": 0,
            "mgmt_fee_cents": 0,
            "cleaning_pass_through_cents": 0,
            "work_order_owner_charges_cents": 0,
            "tax_remitted_cents": 0,
            "owner_payout_cents": 0,
            "status": "DRAFT",
        }
    )
    store.owner_statements[ent["id"]] = ent
    # provisional aggregate + ledger lines
    qbs = recompute_statement(ent, final=False)
    owner_pct = as_dec(owner["default_management_fee_pct"])
    for b in qbs:
        add_statement_line(ent["id"], "RENTAL", b["nightly_subtotal_cents"], b["id"])
        fee = rhu(as_dec(b["nightly_subtotal_cents"]) * owner_pct / 100)
        add_statement_line(ent["id"], "MGMT_FEE", -fee, b["id"])
        add_statement_line(ent["id"], "CLEANING_PASS_THROUGH", b["quoted_cleaning_fee_cents"], b["id"])
    return object_response(ent, 201)


def _statement_owner_scope(stmt, uid, role):
    if role == "Owner" and stmt["owner_id"] != uid:
        raise err("ERR_UNAUTHORIZED", "Owners may read only their own statements")


@app.route("/owner-statements/<sid>", methods=["GET"])
def get_owner_statement(sid):
    uid, role = authenticate()
    authorize(role, {"PlatformAdmin", "PropertyManager", "Owner"})
    ent = find(store.owner_statements, sid)
    _statement_owner_scope(ent, uid, role)
    return object_response(ent)


@app.route("/owner-statements", methods=["GET"])
def list_owner_statements():
    uid, role = authenticate()
    authorize(role, {"PlatformAdmin", "PropertyManager", "Owner"})
    items = list(store.owner_statements.values())
    if role == "Owner":
        items = [s for s in items if s["owner_id"] == uid]
    owner_id = request.args.get("owner_id")
    if owner_id is not None:
        items = [s for s in items if s["owner_id"] == owner_id]
    status = request.args.get("status")
    if status is not None:
        items = [s for s in items if s["status"] == status]
    for key in ("period_year", "period_month"):
        val = request.args.get(key)
        if val is not None:
            try:
                iv = int(val)
                items = [s for s in items if s[key] == iv]
            except Exception:
                pass
    return paginate(items)


@app.route("/owner-statements/<sid>/lines", methods=["GET"])
def list_statement_lines(sid):
    uid, role = authenticate()
    authorize(role, {"PlatformAdmin", "PropertyManager", "Owner"})
    stmt = find(store.owner_statements, sid)
    _statement_owner_scope(stmt, uid, role)
    items = [l for l in store.statement_lines.values() if l["statement_id"] == sid]
    lt = request.args.get("line_type")
    if lt is not None:
        items = [l for l in items if l["line_type"] == lt]
    return paginate(items)


@app.route("/owner-statements/<sid>/finalize", methods=["POST"])
def finalize_statement(sid):
    _uid, role = authenticate()
    authorize(role, {"PropertyManager"})
    stmt = find(store.owner_statements, sid)
    if stmt["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "Only DRAFT statements can be finalized")
    # referential (priority 7): no open work orders for owner's properties in the period
    own_props = {p["id"] for p in store.properties.values() if p["owner_id"] == stmt["owner_id"]}
    for w in store.work_orders.values():
        if w["property_id"] in own_props and w["status"] in (
            "OPEN", "ASSIGNED", "IN_PROGRESS", "NEEDS_INFO", "COMPLETED"
        ):
            raise err("ERR_OPEN_WORK_ORDERS", "Open work orders exist for the period")
    recompute_statement(stmt, final=True)
    add_statement_line(stmt["id"], "TAX_REMITTANCE", -stmt["tax_remitted_cents"], None)
    stmt["status"] = "FINALIZED"
    store.touch(stmt)
    return object_response(stmt)


@app.route("/owner-statements/<sid>/reopen", methods=["POST"])
def reopen_statement(sid):
    _uid, role = authenticate()
    authorize(role, {"PropertyManager"})
    stmt = find(store.owner_statements, sid)
    if stmt["status"] != "FINALIZED":
        raise err("ERR_INVALID_STATE", "Only FINALIZED statements can be reopened")
    # remove derived TAX_REMITTANCE lines
    to_remove = [
        lid for lid, l in store.statement_lines.items()
        if l["statement_id"] == sid and l["line_type"] == "TAX_REMITTANCE"
    ]
    for lid in to_remove:
        del store.statement_lines[lid]
    stmt["tax_remitted_cents"] = 0
    recompute_statement(stmt, final=False)
    stmt["status"] = "DRAFT"
    store.touch(stmt)
    return object_response(stmt)


@app.route("/owner-statements/<sid>/pay", methods=["POST"])
def pay_statement(sid):
    _uid, role = authenticate()
    authorize(role, {"PropertyManager"})
    stmt = find(store.owner_statements, sid)
    if stmt["status"] != "FINALIZED":
        raise err("ERR_STATEMENT_NOT_FINALIZED", "Statement is not FINALIZED")
    if stmt["owner_payout_cents"] < 0:
        raise err("ERR_NEGATIVE_PAYOUT", "Owner payout is negative")
    stmt["status"] = "PAID"
    store.touch(stmt)
    return object_response(stmt)


# =============================================================================
# Routes: Review
# =============================================================================


@app.route("/reviews", methods=["POST"])
def create_review():
    uid, role = authenticate()
    authorize(role, {"Guest", "PropertyManager"})
    body = get_body()
    booking = None
    if body.get("booking_id") is not None:
        booking = find(store.bookings, body["booking_id"])
    if body.get("property_id") is not None:
        find(store.properties, body["property_id"])
    if role == "Guest" and booking is not None and booking["guest_id"] != uid:
        raise err("ERR_UNAUTHORIZED", "Guests may review only their own bookings")
    require_fields(body, ["booking_id", "property_id", "rating", "author_role"])
    rating = require_int(body, "rating")
    if rating < 1 or rating > 5:
        raise err("ERR_VALIDATION", "rating must be between 1 and 5")
    check_enum(body["author_role"], {"GUEST", "MANAGER"}, "author_role")
    if booking["stay_status"] != "CHECKED_OUT":
        raise err("ERR_BOOKING_NOT_CHECKED_OUT", "Booking is not CHECKED_OUT")
    ent = store.new_common()
    ent.update(
        {
            "booking_id": booking["id"],
            "property_id": body["property_id"],
            "rating": rating,
            "comment": body.get("comment"),
            "author_role": body["author_role"],
            "status": "SUBMITTED",
        }
    )
    store.reviews[ent["id"]] = ent
    return object_response(ent, 201)


@app.route("/reviews/<rid>", methods=["GET"])
def get_review(rid):
    _uid, role = authenticate()
    authorize(role, {"PlatformAdmin", "PropertyManager", "Guest"})
    ent = find(store.reviews, rid)
    return object_response(ent)


@app.route("/reviews", methods=["GET"])
def list_reviews():
    _uid, role = authenticate()
    authorize(role, {"PlatformAdmin", "PropertyManager", "Guest"})
    items = list(store.reviews.values())
    for key in ("booking_id", "property_id", "status"):
        val = request.args.get(key)
        if val is not None:
            items = [r for r in items if r[key] == val]
    return paginate(items)


@app.route("/reviews/<rid>/publish", methods=["POST"])
def publish_review(rid):
    _uid, role = authenticate()
    authorize(role, {"PropertyManager"})
    ent = find(store.reviews, rid)
    if ent["status"] != "SUBMITTED":
        raise err("ERR_INVALID_STATE", "Only SUBMITTED reviews can be published")
    ent["status"] = "PUBLISHED"
    store.touch(ent)
    return object_response(ent)


@app.route("/reviews/<rid>/suppress", methods=["POST"])
def suppress_review(rid):
    _uid, role = authenticate()
    authorize(role, {"PropertyManager"})
    ent = find(store.reviews, rid)
    if ent["status"] not in ("SUBMITTED", "PUBLISHED"):
        raise err("ERR_INVALID_STATE", "Only SUBMITTED or PUBLISHED reviews can be suppressed")
    ent["status"] = "SUPPRESSED"
    store.touch(ent)
    return object_response(ent)


# =============================================================================
# Health
# =============================================================================


@app.route("/", methods=["GET"])
def health():
    return ok({"status": "ok"}, code=200)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
