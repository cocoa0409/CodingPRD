import os
import uuid
import random
import string
import calendar
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP

from flask import Flask, request, jsonify

app = Flask(__name__)

# =============================================================================
# Constants
# =============================================================================
ROLES = {"Admin", "Customer", "Designer", "ShopManager", "FieldOps"}
MATERIALS = {"GRANITE", "BRONZE", "MARBLE"}
SUBJECT_TYPES = {"HUMAN", "PET"}
SERVICE_TYPES = {"CLEANING", "REPAIR", "REFINISH"}
CONDITIONS = {"NORMAL", "SEVERE"}

ENGRAVE_RATE = {"HUMAN": 250, "PET": 180}
VOLUME_DISCOUNT_PCT = 15
MATERIAL_RATE = {"GRANITE": 8, "BRONZE": 15, "MARBLE": 11}
FOUNDATION_FLAT_CENTS = 45000
DEPOSIT_PCT = Decimal("0.40")
RESTORE_RATE = {"CLEANING": 2, "REPAIR": 6, "REFINISH": 9}
SEVERE_SURCHARGE_CENTS = 5000
WARRANTY_MONTHS = {"HUMAN": 120, "PET": 60}
CREW_BUFFER_MINUTES = 60

# =============================================================================
# In-memory store
# =============================================================================
cemeteries = {}
customers = {}
orders = {}
proofs = {}
payments = {}
workshops = {}
fabrication_jobs = {}
permits = {}
crews = {}
installations = {}
restorations = {}

_seq_counter = 0
logical_clock = datetime(2026, 3, 1, 0, 0, 0, tzinfo=timezone.utc)


def next_seq():
    global _seq_counter
    _seq_counter += 1
    return _seq_counter


def new_id():
    return str(uuid.uuid4())


def now_wall():
    return datetime.now(timezone.utc)


# =============================================================================
# Errors
# =============================================================================
class ApiError(Exception):
    def __init__(self, error_id, http_status, message=""):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# =============================================================================
# Time helpers
# =============================================================================
def fmt(dt):
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def parse_iso(s):
    if not isinstance(s, str):
        return None
    t = s.strip()
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(t)
    except Exception:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def add_months(dt, months):
    m = dt.month - 1 + months
    y = dt.year + m // 12
    mm = m % 12 + 1
    d = min(dt.day, calendar.monthrange(y, mm)[1])
    return dt.replace(year=y, month=mm, day=d)


# =============================================================================
# Calculations
# =============================================================================
def rhu(dec):
    return int(Decimal(dec).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def engraving_charge(counts, subject_type):
    rate = ENGRAVE_RATE[subject_type]
    total = 0
    for n in counts:
        total += rhu(Decimal(n * rate * (100 - VOLUME_DISCOUNT_PCT)) / Decimal(100))
    return total


def material_priced(order, engraving):
    face = order["height_cm"] * order["width_cm"]
    comp = face * MATERIAL_RATE[order["material"]]
    if face >= 6000:
        mult = 125
    elif face >= 3000:
        mult = 110
    else:
        mult = 100
    priced = rhu(Decimal(comp * mult) / Decimal(100))
    return priced + engraving


def recompute_contract(order):
    cem = cemeteries[order["cemetery_id"]]
    permit_fee = cem["permit_fee_cents"] if cem["requires_permit"] else 0
    total = order["merchandise_price_cents"] + FOUNDATION_FLAT_CENTS + permit_fee
    order["contract_total_cents"] = total
    order["deposit_amount_cents"] = rhu(DEPOSIT_PCT * Decimal(total))
    order["balance_amount_cents"] = total - order["deposit_amount_cents"]


def compute_amount_paid(order_id):
    total = 0
    for p in payments.values():
        if p["order_id"] == order_id and p["status"] == "CAPTURED":
            total += p["signed_amount_cents"]
    return total


def workshop_booked(wid):
    total = 0
    for fj in fabrication_jobs.values():
        if fj["workshop_id"] == wid and fj["status"] == "SCHEDULED":
            total += fj["duration_minutes"]
    for rj in restorations.values():
        if rj.get("workshop_id") == wid and rj["status"] == "ASSESSED":
            total += rj["duration_minutes"] or 0
    return total


def crew_booked(cid):
    total = 0
    for ins in installations.values():
        if ins["crew_id"] == cid and ins["status"] == "SCHEDULED":
            total += ins["duration_minutes"]
    return total


# =============================================================================
# Response envelope
# =============================================================================
def _meta():
    rid = "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))
    return {"api_request_id": rid, "api_request_timestamp": fmt(now_wall())}


def respond(data, status=200, response_type="object", pagination=None):
    meta = _meta()
    if pagination:
        meta.update(pagination)
    return jsonify({"meta": meta, "response_type": response_type, "data": data}), status


@app.errorhandler(ApiError)
def _handle_api_error(e):
    meta = _meta()
    return jsonify({
        "meta": meta,
        "response_type": "error",
        "data": {"error_id": e.error_id, "message": e.message},
    }), e.http_status


@app.errorhandler(404)
def _handle_404(e):
    meta = _meta()
    return jsonify({
        "meta": meta,
        "response_type": "error",
        "data": {"error_id": "ERR_NOT_FOUND", "message": "Not found"},
    }), 404


@app.errorhandler(405)
def _handle_405(e):
    meta = _meta()
    return jsonify({
        "meta": meta,
        "response_type": "error",
        "data": {"error_id": "ERR_METHOD_NOT_ALLOWED", "message": "Method not allowed"},
    }), 405


@app.errorhandler(Exception)
def _handle_uncaught(e):
    if isinstance(e, ApiError):
        return _handle_api_error(e)
    meta = _meta()
    return jsonify({
        "meta": meta,
        "response_type": "error",
        "data": {"error_id": "ERR_INTERNAL", "message": str(e)},
    }), 500


# =============================================================================
# Auth / request helpers
# =============================================================================
def get_auth():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise ApiError("ERR_MISSING_USER_CONTEXT", 400, "Missing or invalid user context headers")
    return uid, role


def require_role(role, allowed):
    if role not in allowed:
        raise ApiError("ERR_FORBIDDEN_ROLE", 403, "Role not permitted for this operation")


def get_body():
    body = request.get_json(silent=True)
    if body is None:
        body = {}
    if not isinstance(body, dict):
        raise ApiError("ERR_INVALID_REQUEST", 400, "Request body must be a JSON object")
    return body


def invalid(msg="Invalid request"):
    raise ApiError("ERR_INVALID_REQUEST", 400, msg)


def req_str(body, key):
    v = body.get(key)
    if not isinstance(v, str) or v == "":
        invalid("Missing or invalid field: " + key)
    return v


def req_int(body, key):
    v = body.get(key)
    if isinstance(v, bool) or not isinstance(v, int):
        invalid("Missing or invalid integer field: " + key)
    return v


def req_enum(body, key, allowed):
    v = body.get(key)
    if v not in allowed:
        invalid("Missing or invalid enum field: " + key)
    return v


def req_int_array(body, key):
    v = body.get(key)
    if not isinstance(v, list):
        invalid("Missing or invalid array field: " + key)
    for n in v:
        if isinstance(n, bool) or not isinstance(n, int) or n <= 0:
            invalid("Array must contain positive integers: " + key)
    return v


def get_pagination():
    try:
        limit = int(request.args.get("limit", 10))
    except (TypeError, ValueError):
        limit = 10
    try:
        offset = int(request.args.get("offset", 0))
    except (TypeError, ValueError):
        offset = 0
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    return limit, offset


def paginate(items):
    limit, offset = get_pagination()
    total = len(items)
    page = items[offset:offset + limit]
    pag = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(page) < total,
    }
    return page, pag


def touch(entity):
    entity["updated_at"] = now_wall()
    entity["version"] += 1


def base_entity(initial_version=1):
    return {
        "id": new_id(),
        "created_at": now_wall(),
        "updated_at": now_wall(),
        "version": initial_version,
        "_seq": next_seq(),
    }


# =============================================================================
# Lookups
# =============================================================================
def get_order(oid):
    o = orders.get(oid)
    if o is None:
        raise ApiError("ERR_ORDER_NOT_FOUND", 404, "Order not found")
    return o


def get_customer(cid):
    c = customers.get(cid)
    if c is None:
        raise ApiError("ERR_CUSTOMER_NOT_FOUND", 404, "Customer not found")
    return c


def get_cemetery(cid):
    c = cemeteries.get(cid)
    if c is None:
        raise ApiError("ERR_CEMETERY_NOT_FOUND", 404, "Cemetery not found")
    return c


def get_proof(pid):
    p = proofs.get(pid)
    if p is None:
        raise ApiError("ERR_PROOF_NOT_FOUND", 404, "Design proof not found")
    return p


def get_workshop(wid):
    w = workshops.get(wid)
    if w is None:
        raise ApiError("ERR_WORKSHOP_NOT_FOUND", 404, "Workshop not found")
    return w


def get_fab(fid):
    f = fabrication_jobs.get(fid)
    if f is None:
        raise ApiError("ERR_FAB_JOB_NOT_FOUND", 404, "Fabrication job not found")
    return f


def get_permit(pid):
    p = permits.get(pid)
    if p is None:
        raise ApiError("ERR_PERMIT_NOT_FOUND", 404, "Permit not found")
    return p


def get_crew(cid):
    c = crews.get(cid)
    if c is None:
        raise ApiError("ERR_CREW_NOT_FOUND", 404, "Installation crew not found")
    return c


def get_installation(iid):
    i = installations.get(iid)
    if i is None:
        raise ApiError("ERR_INSTALLATION_NOT_FOUND", 404, "Installation not found")
    return i


def get_restoration(rid):
    r = restorations.get(rid)
    if r is None:
        raise ApiError("ERR_RESTORATION_NOT_FOUND", 404, "Restoration job not found")
    return r


def require_owner(order, uid):
    if order["customer_id"] != uid:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", 403, "Acting customer is not the resource owner")


def check_spec(order, cemetery):
    if order["material"] not in cemetery["allowed_materials"]:
        raise ApiError("ERR_MATERIAL_NOT_ALLOWED", 422, "Material not allowed at cemetery")
    if (order["height_cm"] > cemetery["max_height_cm"]
            or order["width_cm"] > cemetery["max_width_cm"]
            or order["base_width_cm"] > cemetery["max_base_width_cm"]):
        raise ApiError("ERR_EXCEEDS_CEMETERY_SPEC", 422, "Marker dimensions exceed cemetery spec")


def parse_slot(body):
    start_raw = body.get("scheduled_start")
    end_raw = body.get("scheduled_end")
    if not isinstance(start_raw, str) or not isinstance(end_raw, str):
        invalid("scheduled_start and scheduled_end are required")
    start = parse_iso(start_raw)
    end = parse_iso(end_raw)
    if start is None or end is None:
        invalid("scheduled_start and scheduled_end must be ISO8601 datetimes")
    if end <= start:
        raise ApiError("ERR_INVALID_SCHEDULE_WINDOW", 400, "scheduled_end must be after scheduled_start")
    duration = int((end - start).total_seconds() // 60)
    return start_raw, end_raw, start, end, duration


def workshop_conflict(wid, start, end):
    for fj in fabrication_jobs.values():
        if fj["workshop_id"] == wid and fj["status"] == "SCHEDULED":
            s = parse_iso(fj["scheduled_start"])
            e = parse_iso(fj["scheduled_end"])
            if start < e and s < end:
                return True
    for rj in restorations.values():
        if rj.get("workshop_id") == wid and rj["status"] == "ASSESSED":
            s = parse_iso(rj["scheduled_start"])
            e = parse_iso(rj["scheduled_end"])
            if start < e and s < end:
                return True
    return False


def crew_conflict(cid, start, end):
    buf = timedelta(minutes=CREW_BUFFER_MINUTES)
    for ins in installations.values():
        if ins["crew_id"] == cid and ins["status"] == "SCHEDULED":
            s = parse_iso(ins["scheduled_start"])
            e = parse_iso(ins["scheduled_end"])
            # acceptable only if new.start >= e + buf OR new.end + buf <= s
            if not (start >= e + buf or end + buf <= s):
                return True
    return False


# =============================================================================
# Serializers
# =============================================================================
def s_cemetery(c):
    return {
        "id": c["id"], "created_at": fmt(c["created_at"]), "updated_at": fmt(c["updated_at"]),
        "version": c["version"], "name": c["name"], "allowed_materials": c["allowed_materials"],
        "max_height_cm": c["max_height_cm"], "max_width_cm": c["max_width_cm"],
        "max_base_width_cm": c["max_base_width_cm"], "requires_permit": c["requires_permit"],
        "permit_fee_cents": c["permit_fee_cents"], "requires_foundation": c["requires_foundation"],
    }


def s_customer(c):
    return {
        "id": c["id"], "created_at": fmt(c["created_at"]), "updated_at": fmt(c["updated_at"]),
        "version": c["version"], "full_name": c["full_name"], "email": c["email"], "phone": c["phone"],
    }


def s_order(o):
    return {
        "id": o["id"], "created_at": fmt(o["created_at"]), "updated_at": fmt(o["updated_at"]),
        "version": o["version"], "customer_id": o["customer_id"], "cemetery_id": o["cemetery_id"],
        "subject_type": o["subject_type"], "material": o["material"], "height_cm": o["height_cm"],
        "width_cm": o["width_cm"], "base_width_cm": o["base_width_cm"],
        "estimated_line_char_counts": o["estimated_line_char_counts"],
        "production_status": o["production_status"], "payment_status": o["payment_status"],
        "current_proof_id": o["current_proof_id"],
        "provisional_merchandise_cents": o["provisional_merchandise_cents"],
        "merchandise_price_cents": o["merchandise_price_cents"],
        "contract_total_cents": o["contract_total_cents"],
        "deposit_amount_cents": o["deposit_amount_cents"],
        "balance_amount_cents": o["balance_amount_cents"],
        "amount_paid_cents": compute_amount_paid(o["id"]),
        "warranty_expires_at": fmt(o["warranty_expires_at"]),
    }


def s_proof(p):
    return {
        "id": p["id"], "created_at": fmt(p["created_at"]), "updated_at": fmt(p["updated_at"]),
        "version": p["version"], "order_id": p["order_id"], "engraving_text": p["engraving_text"],
        "line_char_counts": p["line_char_counts"], "layout_spec": p["layout_spec"],
        "revision_round": p["revision_round"], "status": p["status"],
    }


def s_payment(p):
    return {
        "id": p["id"], "created_at": fmt(p["created_at"]), "order_id": p["order_id"],
        "payment_type": p["payment_type"], "amount_cents": p["amount_cents"],
        "signed_amount_cents": p["signed_amount_cents"], "status": p["status"],
    }


def s_workshop(w):
    return {
        "id": w["id"], "created_at": fmt(w["created_at"]), "updated_at": fmt(w["updated_at"]),
        "version": w["version"], "name": w["name"], "booked_minutes": workshop_booked(w["id"]),
    }


def s_fab(f):
    return {
        "id": f["id"], "created_at": fmt(f["created_at"]), "updated_at": fmt(f["updated_at"]),
        "version": f["version"], "order_id": f["order_id"], "workshop_id": f["workshop_id"],
        "scheduled_start": f["scheduled_start"], "scheduled_end": f["scheduled_end"],
        "duration_minutes": f["duration_minutes"], "status": f["status"],
        "completed_at": fmt(f["completed_at"]),
    }


def s_permit(p):
    return {
        "id": p["id"], "created_at": fmt(p["created_at"]), "updated_at": fmt(p["updated_at"]),
        "version": p["version"], "order_id": p["order_id"], "cemetery_id": p["cemetery_id"],
        "permit_number": p["permit_number"], "placement_date": p["placement_date"],
        "status": p["status"],
    }


def s_crew(c):
    return {
        "id": c["id"], "created_at": fmt(c["created_at"]), "updated_at": fmt(c["updated_at"]),
        "version": c["version"], "name": c["name"], "booked_minutes": crew_booked(c["id"]),
    }


def s_installation(i):
    return {
        "id": i["id"], "created_at": fmt(i["created_at"]), "updated_at": fmt(i["updated_at"]),
        "version": i["version"], "order_id": i["order_id"], "crew_id": i["crew_id"],
        "scheduled_start": i["scheduled_start"], "scheduled_end": i["scheduled_end"],
        "duration_minutes": i["duration_minutes"], "status": i["status"],
        "completed_at": fmt(i["completed_at"]),
    }


def s_restoration(r):
    return {
        "id": r["id"], "created_at": fmt(r["created_at"]), "updated_at": fmt(r["updated_at"]),
        "version": r["version"], "order_id": r["order_id"], "workshop_id": r.get("workshop_id"),
        "service_type": r["service_type"], "is_warranty": r["is_warranty"],
        "reported_area_cm2": r["reported_area_cm2"], "measured_area_cm2": r.get("measured_area_cm2"),
        "condition": r.get("condition"), "quoted_cost_cents": r["quoted_cost_cents"],
        "assessed_cost_cents": r.get("assessed_cost_cents"),
        "scheduled_start": r.get("scheduled_start"), "scheduled_end": r.get("scheduled_end"),
        "duration_minutes": r.get("duration_minutes"), "status": r["status"],
    }


def sorted_vals(d):
    return sorted(d.values(), key=lambda x: x["_seq"])


# =============================================================================
# Admin / config endpoints
# =============================================================================
@app.route("/memorials/cemeteries", methods=["POST"])
def create_cemetery():
    uid, role = get_auth()
    require_role(role, {"Admin"})
    body = get_body()
    name = req_str(body, "name")
    mats = body.get("allowed_materials")
    if not isinstance(mats, list) or not mats or any(m not in MATERIALS for m in mats):
        invalid("allowed_materials must be a non-empty subset of GRANITE/BRONZE/MARBLE")
    max_h = req_int(body, "max_height_cm")
    max_w = req_int(body, "max_width_cm")
    max_bw = req_int(body, "max_base_width_cm")
    requires_permit = body.get("requires_permit", True)
    if not isinstance(requires_permit, bool):
        invalid("requires_permit must be boolean")
    permit_fee = body.get("permit_fee_cents", 0)
    if isinstance(permit_fee, bool) or not isinstance(permit_fee, int):
        invalid("permit_fee_cents must be integer")
    requires_foundation = body.get("requires_foundation", True)
    if not isinstance(requires_foundation, bool):
        invalid("requires_foundation must be boolean")

    c = base_entity()
    c.update({
        "name": name, "allowed_materials": list(mats), "max_height_cm": max_h,
        "max_width_cm": max_w, "max_base_width_cm": max_bw, "requires_permit": requires_permit,
        "permit_fee_cents": permit_fee, "requires_foundation": requires_foundation,
    })
    cemeteries[c["id"]] = c
    return respond(s_cemetery(c), 201)


@app.route("/memorials/customers", methods=["POST"])
def create_customer():
    uid, role = get_auth()
    require_role(role, {"Admin"})
    body = get_body()
    full_name = req_str(body, "full_name")
    email = req_str(body, "email")
    phone = body.get("phone")
    if phone is not None and not isinstance(phone, str):
        invalid("phone must be a string")
    c = base_entity()
    c.update({"full_name": full_name, "email": email, "phone": phone})
    customers[c["id"]] = c
    return respond(s_customer(c), 201)


@app.route("/memorials/workshops", methods=["POST"])
def create_workshop():
    uid, role = get_auth()
    require_role(role, {"Admin"})
    body = get_body()
    name = req_str(body, "name")
    w = base_entity()
    w.update({"name": name})
    workshops[w["id"]] = w
    return respond(s_workshop(w), 201)


@app.route("/memorials/crews", methods=["POST"])
def create_crew():
    uid, role = get_auth()
    require_role(role, {"Admin"})
    body = get_body()
    name = req_str(body, "name")
    c = base_entity()
    c.update({"name": name})
    crews[c["id"]] = c
    return respond(s_crew(c), 201)


@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    global logical_clock
    uid, role = get_auth()
    require_role(role, {"Admin"})
    body = get_body()
    to_iso = body.get("to_iso8601")
    dt = parse_iso(to_iso)
    if dt is None:
        invalid("to_iso8601 must be an ISO8601 datetime")
    logical_clock = dt
    return respond({}, 200)


# =============================================================================
# MonumentOrder
# =============================================================================
@app.route("/memorials/orders", methods=["POST"])
def create_order():
    uid, role = get_auth()
    require_role(role, {"Customer"})
    body = get_body()
    # existence (left-to-right): customer_id, cemetery_id
    customer_id = body.get("customer_id")
    if isinstance(customer_id, str) and customer_id:
        get_customer(customer_id)
    cemetery_id = body.get("cemetery_id")
    if isinstance(cemetery_id, str) and cemetery_id:
        get_cemetery(cemetery_id)
    # well-formedness
    customer_id = req_str(body, "customer_id")
    cemetery_id = req_str(body, "cemetery_id")
    get_customer(customer_id)
    cem = get_cemetery(cemetery_id)
    subject_type = req_enum(body, "subject_type", SUBJECT_TYPES)
    material = req_enum(body, "material", MATERIALS)
    height_cm = req_int(body, "height_cm")
    width_cm = req_int(body, "width_cm")
    base_width_cm = req_int(body, "base_width_cm")
    est = req_int_array(body, "estimated_line_char_counts")
    # ownership: customer acting on their own order
    require_owner({"customer_id": customer_id}, uid)

    o = base_entity()
    o.update({
        "customer_id": customer_id, "cemetery_id": cemetery_id, "subject_type": subject_type,
        "material": material, "height_cm": height_cm, "width_cm": width_cm,
        "base_width_cm": base_width_cm, "estimated_line_char_counts": list(est),
        "production_status": "DRAFTING", "payment_status": "UNPAID", "current_proof_id": None,
        "warranty_expires_at": None,
    })
    # spec compliance (422)
    check_spec(o, cem)
    # provisional pricing
    prov = material_priced(o, engraving_charge(est, subject_type))
    o["provisional_merchandise_cents"] = prov
    o["merchandise_price_cents"] = prov
    recompute_contract(o)
    orders[o["id"]] = o
    return respond(s_order(o), 201)


@app.route("/memorials/orders/<oid>", methods=["GET"])
def get_order_ep(oid):
    uid, role = get_auth()
    require_role(role, ROLES)
    o = get_order(oid)
    return respond(s_order(o), 200)


@app.route("/memorials/orders", methods=["GET"])
def list_orders():
    uid, role = get_auth()
    require_role(role, ROLES)
    items = sorted_vals(orders)
    cem = request.args.get("cemetery_id")
    cust = request.args.get("customer_id")
    if cem is not None:
        items = [o for o in items if o["cemetery_id"] == cem]
    if cust is not None:
        items = [o for o in items if o["customer_id"] == cust]
    page, pag = paginate(items)
    return respond([s_order(o) for o in page], 200, "array", pag)


@app.route("/memorials/orders/<oid>/cancel", methods=["POST"])
def cancel_order(oid):
    uid, role = get_auth()
    require_role(role, {"Customer"})
    o = get_order(oid)
    require_owner(o, uid)
    if o["production_status"] in ("INSTALLED", "CANCELLED"):
        raise ApiError("ERR_ORDER_ALREADY_TERMINAL", 409, "Order already terminal")
    # primary transition
    o["production_status"] = "CANCELLED"
    # cascade
    for fj in fabrication_jobs.values():
        if fj["order_id"] == oid and fj["status"] == "SCHEDULED":
            fj["status"] = "CANCELLED"
            touch(fj)
    for ins in installations.values():
        if ins["order_id"] == oid and ins["status"] == "SCHEDULED":
            ins["status"] = "CANCELLED"
            touch(ins)
    for pm in permits.values():
        if pm["order_id"] == oid and pm["status"] in ("PENDING", "ISSUED"):
            pm["status"] = "REVOKED"
            touch(pm)
    for pr in proofs.values():
        if pr["order_id"] == oid and pr["status"] in ("DRAFT", "SUBMITTED", "CHANGES_REQUESTED", "APPROVED"):
            pr["status"] = "VOIDED"
            touch(pr)
    # refund branch
    paid = compute_amount_paid(oid)
    if paid > 0:
        p = {
            "id": new_id(), "created_at": now_wall(), "_seq": next_seq(), "order_id": oid,
            "payment_type": "REFUND", "amount_cents": paid, "signed_amount_cents": -paid,
            "status": "CAPTURED",
        }
        payments[p["id"]] = p
        o["payment_status"] = "REFUNDED"
    touch(o)
    return respond(s_order(o), 200)


# =============================================================================
# DesignProof
# =============================================================================
@app.route("/memorials/design-proofs", methods=["POST"])
def create_proof():
    uid, role = get_auth()
    require_role(role, {"Designer"})
    body = get_body()
    order_id = body.get("order_id")
    if isinstance(order_id, str) and order_id:
        o = get_order(order_id)
    order_id = req_str(body, "order_id")
    o = get_order(order_id)
    engraving_text = req_str(body, "engraving_text")
    line_counts = req_int_array(body, "line_char_counts")
    expected_version = body.get("expected_order_version")
    if isinstance(expected_version, bool) or not isinstance(expected_version, int):
        invalid("expected_order_version is required")
    layout_spec = body.get("layout_spec")
    if layout_spec is not None and not isinstance(layout_spec, str):
        invalid("layout_spec must be a string")
    # OCC (checked last, priority 12)
    if expected_version != o["version"]:
        raise ApiError("ERR_STALE_ORDER_VERSION", 412, "expected_order_version does not match current order version")

    # supersede prior current proof
    prev_id = o["current_proof_id"]
    if prev_id and prev_id in proofs:
        prev = proofs[prev_id]
        if prev["status"] in ("DRAFT", "SUBMITTED", "CHANGES_REQUESTED"):
            prev["status"] = "SUPERSEDED"
            touch(prev)

    p = base_entity()
    p.update({
        "order_id": order_id, "engraving_text": engraving_text, "line_char_counts": list(line_counts),
        "layout_spec": layout_spec, "revision_round": 1, "status": "DRAFT",
    })
    proofs[p["id"]] = p
    o["current_proof_id"] = p["id"]
    touch(o)
    return respond(s_proof(p), 201)


@app.route("/memorials/orders/<oid>/design-proofs", methods=["GET"])
def list_order_proofs(oid):
    uid, role = get_auth()
    require_role(role, ROLES)
    get_order(oid)
    items = [p for p in sorted_vals(proofs) if p["order_id"] == oid]
    page, pag = paginate(items)
    return respond([s_proof(p) for p in page], 200, "array", pag)


@app.route("/memorials/design-proofs/<pid>/submit", methods=["POST"])
def submit_proof(pid):
    uid, role = get_auth()
    require_role(role, {"Designer"})
    p = get_proof(pid)
    if p["status"] not in ("DRAFT", "CHANGES_REQUESTED"):
        raise ApiError("ERR_PROOF_NOT_DRAFT", 409, "Proof is not in DRAFT/CHANGES_REQUESTED")
    if p["status"] == "CHANGES_REQUESTED":
        p["revision_round"] += 1
    p["status"] = "SUBMITTED"
    touch(p)
    return respond(s_proof(p), 200)


@app.route("/memorials/design-proofs/<pid>/approve", methods=["POST"])
def approve_proof(pid):
    uid, role = get_auth()
    require_role(role, {"Customer"})
    p = get_proof(pid)
    o = get_order(p["order_id"])
    require_owner(o, uid)
    # state family (409)
    if o["production_status"] != "DRAFTING":
        raise ApiError("ERR_ORDER_NOT_DRAFTING", 409, "Order is not in DRAFTING")
    if o["current_proof_id"] != p["id"]:
        raise ApiError("ERR_PROOF_NOT_CURRENT", 409, "Proof is not the order's current proof")
    if p["status"] != "SUBMITTED":
        raise ApiError("ERR_PROOF_NOT_SUBMITTED", 409, "Proof is not in SUBMITTED")
    # fiscal (402)
    if o["payment_status"] == "UNPAID":
        raise ApiError("ERR_DEPOSIT_NOT_PAID", 402, "Deposit has not been paid")
    # transition + final pricing
    p["status"] = "APPROVED"
    touch(p)
    o["merchandise_price_cents"] = material_priced(o, engraving_charge(p["line_char_counts"], o["subject_type"]))
    recompute_contract(o)
    touch(o)
    return respond(s_proof(p), 200)


@app.route("/memorials/design-proofs/<pid>/request-changes", methods=["POST"])
def request_changes(pid):
    uid, role = get_auth()
    require_role(role, {"Customer"})
    p = get_proof(pid)
    o = get_order(p["order_id"])
    require_owner(o, uid)
    if p["status"] != "SUBMITTED":
        raise ApiError("ERR_PROOF_NOT_SUBMITTED", 409, "Proof is not in SUBMITTED")
    p["status"] = "CHANGES_REQUESTED"
    touch(p)
    return respond(s_proof(p), 200)


# =============================================================================
# Payment
# =============================================================================
@app.route("/memorials/payments", methods=["POST"])
def create_payment():
    uid, role = get_auth()
    require_role(role, {"Customer"})
    body = get_body()
    order_id = body.get("order_id")
    if isinstance(order_id, str) and order_id:
        o = get_order(order_id)
        require_owner(o, uid)
    order_id = req_str(body, "order_id")
    o = get_order(order_id)
    require_owner(o, uid)
    payment_type = req_enum(body, "payment_type", {"DEPOSIT", "BALANCE"})
    amount = req_int(body, "amount_cents")
    # fiscal (402)
    if amount <= 0:
        raise ApiError("ERR_ZERO_PAYMENT_AMOUNT", 402, "amount_cents must be greater than zero")
    current_paid = compute_amount_paid(order_id)
    new_cum = current_paid + amount
    if payment_type == "DEPOSIT":
        if new_cum < o["deposit_amount_cents"]:
            raise ApiError("ERR_DEPOSIT_NOT_PAID", 402, "Deposit not fully paid")
    else:  # BALANCE
        if new_cum < o["contract_total_cents"]:
            raise ApiError("ERR_BALANCE_NOT_PAID", 402, "Balance not fully paid")

    p = {
        "id": new_id(), "created_at": now_wall(), "_seq": next_seq(), "order_id": order_id,
        "payment_type": payment_type, "amount_cents": amount, "signed_amount_cents": amount,
        "status": "CAPTURED",
    }
    payments[p["id"]] = p
    if payment_type == "DEPOSIT":
        if o["payment_status"] == "UNPAID":
            o["payment_status"] = "DEPOSIT_PAID"
    else:
        if o["payment_status"] in ("UNPAID", "DEPOSIT_PAID"):
            o["payment_status"] = "PAID_IN_FULL"
    touch(o)
    return respond(s_payment(p), 201)


@app.route("/memorials/orders/<oid>/payments", methods=["GET"])
def list_order_payments(oid):
    uid, role = get_auth()
    require_role(role, ROLES)
    get_order(oid)
    items = [p for p in sorted_vals(payments) if p["order_id"] == oid]
    page, pag = paginate(items)
    return respond([s_payment(p) for p in page], 200, "array", pag)


# =============================================================================
# FabricationJob
# =============================================================================
@app.route("/memorials/fabrication-jobs", methods=["POST"])
def create_fab():
    uid, role = get_auth()
    require_role(role, {"ShopManager"})
    body = get_body()
    order_id = body.get("order_id")
    if isinstance(order_id, str) and order_id:
        get_order(order_id)
    workshop_id = body.get("workshop_id")
    if isinstance(workshop_id, str) and workshop_id:
        get_workshop(workshop_id)
    order_id = req_str(body, "order_id")
    o = get_order(order_id)
    workshop_id = req_str(body, "workshop_id")
    get_workshop(workshop_id)
    start_raw, end_raw, start, end, duration = parse_slot(body)
    # state (6): order DRAFTING
    if o["production_status"] != "DRAFTING":
        raise ApiError("ERR_ORDER_NOT_DRAFTING", 409, "Order is not in DRAFTING")
    # slot conflict (9)
    if workshop_conflict(workshop_id, start, end):
        raise ApiError("ERR_WORKSHOP_SLOT_CONFLICT", 409, "Workshop slot conflict")
    # cross-entity (10): current proof APPROVED
    cur = o["current_proof_id"]
    if not cur or cur not in proofs or proofs[cur]["status"] != "APPROVED":
        raise ApiError("ERR_PROOF_NOT_APPROVED", 409, "Order's current proof is not APPROVED")

    f = base_entity()
    f.update({
        "order_id": order_id, "workshop_id": workshop_id, "scheduled_start": start_raw,
        "scheduled_end": end_raw, "duration_minutes": duration, "status": "SCHEDULED",
        "completed_at": None,
    })
    fabrication_jobs[f["id"]] = f
    o["production_status"] = "IN_FABRICATION"
    touch(o)
    return respond(s_fab(f), 201)


@app.route("/memorials/fabrication-jobs/<fid>", methods=["GET"])
def get_fab_ep(fid):
    uid, role = get_auth()
    require_role(role, ROLES)
    f = get_fab(fid)
    return respond(s_fab(f), 200)


@app.route("/memorials/fabrication-jobs", methods=["GET"])
def list_fabs():
    uid, role = get_auth()
    require_role(role, ROLES)
    items = sorted_vals(fabrication_jobs)
    order_id = request.args.get("order_id")
    workshop_id = request.args.get("workshop_id")
    if order_id is not None:
        items = [f for f in items if f["order_id"] == order_id]
    if workshop_id is not None:
        items = [f for f in items if f["workshop_id"] == workshop_id]
    page, pag = paginate(items)
    return respond([s_fab(f) for f in page], 200, "array", pag)


@app.route("/memorials/fabrication-jobs/<fid>/complete", methods=["POST"])
def complete_fab(fid):
    uid, role = get_auth()
    require_role(role, {"ShopManager"})
    f = get_fab(fid)
    if f["status"] != "SCHEDULED":
        raise ApiError("ERR_FAB_JOB_NOT_SCHEDULED", 409, "Fabrication job is not SCHEDULED")
    f["status"] = "COMPLETED"
    f["completed_at"] = logical_clock
    touch(f)
    o = orders.get(f["order_id"])
    if o is not None:
        o["production_status"] = "READY_TO_INSTALL"
        touch(o)
    return respond(s_fab(f), 200)


# =============================================================================
# CemeteryPermit
# =============================================================================
@app.route("/memorials/permits", methods=["POST"])
def create_permit():
    uid, role = get_auth()
    require_role(role, {"FieldOps"})
    body = get_body()
    order_id = body.get("order_id")
    if isinstance(order_id, str) and order_id:
        get_order(order_id)
    cemetery_id = body.get("cemetery_id")
    if isinstance(cemetery_id, str) and cemetery_id:
        get_cemetery(cemetery_id)
    order_id = req_str(body, "order_id")
    o = get_order(order_id)
    cemetery_id = req_str(body, "cemetery_id")
    get_cemetery(cemetery_id)
    permit_number = req_str(body, "permit_number")
    placement_raw = body.get("placement_date")
    if not isinstance(placement_raw, str) or parse_iso(placement_raw) is None:
        invalid("placement_date must be an ISO8601 datetime")
    # well-formedness: permit cemetery_id must equal order.cemetery_id
    if cemetery_id != o["cemetery_id"]:
        invalid("cemetery_id must equal the order's cemetery_id")

    p = base_entity()
    p.update({
        "order_id": order_id, "cemetery_id": cemetery_id, "permit_number": permit_number,
        "placement_date": placement_raw, "status": "PENDING",
    })
    permits[p["id"]] = p
    return respond(s_permit(p), 201)


@app.route("/memorials/permits/<pid>", methods=["GET"])
def get_permit_ep(pid):
    uid, role = get_auth()
    require_role(role, ROLES)
    p = get_permit(pid)
    return respond(s_permit(p), 200)


@app.route("/memorials/permits", methods=["GET"])
def list_permits():
    uid, role = get_auth()
    require_role(role, ROLES)
    items = sorted_vals(permits)
    order_id = request.args.get("order_id")
    cemetery_id = request.args.get("cemetery_id")
    if order_id is not None:
        items = [p for p in items if p["order_id"] == order_id]
    if cemetery_id is not None:
        items = [p for p in items if p["cemetery_id"] == cemetery_id]
    page, pag = paginate(items)
    return respond([s_permit(p) for p in page], 200, "array", pag)


@app.route("/memorials/permits/<pid>/issue", methods=["POST"])
def issue_permit(pid):
    uid, role = get_auth()
    require_role(role, {"FieldOps"})
    p = get_permit(pid)
    if p["status"] != "PENDING":
        raise ApiError("ERR_PERMIT_NOT_PENDING", 409, "Permit is not PENDING")
    o = orders.get(p["order_id"])
    cem = cemeteries.get(p["cemetery_id"])
    if o is not None and cem is not None:
        check_spec(o, cem)
    p["status"] = "ISSUED"
    touch(p)
    return respond(s_permit(p), 200)


# =============================================================================
# Installation
# =============================================================================
@app.route("/memorials/installations", methods=["POST"])
def create_installation():
    uid, role = get_auth()
    require_role(role, {"FieldOps"})
    body = get_body()
    order_id = body.get("order_id")
    if isinstance(order_id, str) and order_id:
        get_order(order_id)
    crew_id = body.get("crew_id")
    if isinstance(crew_id, str) and crew_id:
        get_crew(crew_id)
    order_id = req_str(body, "order_id")
    o = get_order(order_id)
    crew_id = req_str(body, "crew_id")
    get_crew(crew_id)
    start_raw, end_raw, start, end, duration = parse_slot(body)
    cem = cemeteries[o["cemetery_id"]]

    # order readiness state (no dedicated code) + temporal readiness (8)
    completed_fab = None
    for f in fabrication_jobs.values():
        if f["order_id"] == order_id and f["status"] == "COMPLETED":
            completed_fab = f
    if o["production_status"] != "READY_TO_INSTALL" or completed_fab is None:
        raise ApiError("ERR_INSTALL_BEFORE_FAB_READY", 409, "Order is not ready for installation")
    if start < completed_fab["completed_at"]:
        raise ApiError("ERR_INSTALL_BEFORE_FAB_READY", 409, "Installation starts before fabrication completed")
    issued_permit = None
    for pm in permits.values():
        if pm["order_id"] == order_id and pm["status"] == "ISSUED":
            issued_permit = pm
    if issued_permit is not None:
        pd = parse_iso(issued_permit["placement_date"])
        if pd is not None and start < pd:
            raise ApiError("ERR_INSTALL_BEFORE_FAB_READY", 409, "Installation starts before permit placement date")
    # slot conflict (9)
    if crew_conflict(crew_id, start, end):
        raise ApiError("ERR_CREW_SLOT_CONFLICT", 409, "Crew slot conflict")
    # cross-entity (10): ISSUED permit required when cemetery requires a permit
    if cem["requires_permit"] and issued_permit is None:
        raise ApiError("ERR_PERMIT_NOT_ISSUED", 409, "Order has no ISSUED permit")

    i = base_entity()
    i.update({
        "order_id": order_id, "crew_id": crew_id, "scheduled_start": start_raw,
        "scheduled_end": end_raw, "duration_minutes": duration, "status": "SCHEDULED",
        "completed_at": None,
    })
    installations[i["id"]] = i
    return respond(s_installation(i), 201)


@app.route("/memorials/installations/<iid>", methods=["GET"])
def get_installation_ep(iid):
    uid, role = get_auth()
    require_role(role, ROLES)
    i = get_installation(iid)
    return respond(s_installation(i), 200)


@app.route("/memorials/installations", methods=["GET"])
def list_installations():
    uid, role = get_auth()
    require_role(role, ROLES)
    items = sorted_vals(installations)
    order_id = request.args.get("order_id")
    crew_id = request.args.get("crew_id")
    if order_id is not None:
        items = [i for i in items if i["order_id"] == order_id]
    if crew_id is not None:
        items = [i for i in items if i["crew_id"] == crew_id]
    page, pag = paginate(items)
    return respond([s_installation(i) for i in page], 200, "array", pag)


@app.route("/memorials/installations/<iid>/complete", methods=["POST"])
def complete_installation(iid):
    uid, role = get_auth()
    require_role(role, {"FieldOps"})
    i = get_installation(iid)
    if i["status"] != "SCHEDULED":
        raise ApiError("ERR_INSTALLATION_NOT_SCHEDULED", 409, "Installation is not SCHEDULED")
    o = orders.get(i["order_id"])
    if o is None or o["payment_status"] != "PAID_IN_FULL":
        raise ApiError("ERR_BALANCE_NOT_PAID", 402, "Order is not PAID_IN_FULL")
    i["status"] = "COMPLETED"
    i["completed_at"] = logical_clock
    touch(i)
    o["production_status"] = "INSTALLED"
    o["warranty_expires_at"] = add_months(logical_clock, WARRANTY_MONTHS[o["subject_type"]])
    touch(o)
    return respond(s_installation(i), 200)


# =============================================================================
# RestorationJob
# =============================================================================
@app.route("/memorials/restorations", methods=["POST"])
def create_restoration():
    uid, role = get_auth()
    require_role(role, {"Customer"})
    body = get_body()
    order_id = body.get("order_id")
    if isinstance(order_id, str) and order_id:
        o = get_order(order_id)
        require_owner(o, uid)
    order_id = req_str(body, "order_id")
    o = get_order(order_id)
    require_owner(o, uid)
    service_type = req_enum(body, "service_type", SERVICE_TYPES)
    reported_area = req_int(body, "reported_area_cm2")
    is_warranty = body.get("is_warranty", False)
    if not isinstance(is_warranty, bool):
        invalid("is_warranty must be boolean")

    quoted = reported_area * RESTORE_RATE[service_type]
    r = base_entity()
    r.update({
        "order_id": order_id, "workshop_id": None, "service_type": service_type,
        "is_warranty": is_warranty, "reported_area_cm2": reported_area,
        "measured_area_cm2": None, "condition": None, "quoted_cost_cents": quoted,
        "assessed_cost_cents": None, "scheduled_start": None, "scheduled_end": None,
        "duration_minutes": None, "status": "REQUESTED",
    })
    restorations[r["id"]] = r
    return respond(s_restoration(r), 201)


@app.route("/memorials/restorations/<rid>", methods=["GET"])
def get_restoration_ep(rid):
    uid, role = get_auth()
    require_role(role, ROLES)
    r = get_restoration(rid)
    return respond(s_restoration(r), 200)


@app.route("/memorials/restorations", methods=["GET"])
def list_restorations():
    uid, role = get_auth()
    require_role(role, ROLES)
    items = sorted_vals(restorations)
    order_id = request.args.get("order_id")
    workshop_id = request.args.get("workshop_id")
    if order_id is not None:
        items = [r for r in items if r["order_id"] == order_id]
    if workshop_id is not None:
        items = [r for r in items if r.get("workshop_id") == workshop_id]
    page, pag = paginate(items)
    return respond([s_restoration(r) for r in page], 200, "array", pag)


@app.route("/memorials/restorations/<rid>/assess", methods=["POST"])
def assess_restoration(rid):
    uid, role = get_auth()
    require_role(role, {"ShopManager"})
    r = get_restoration(rid)
    body = get_body()
    workshop_id = body.get("workshop_id")
    if isinstance(workshop_id, str) and workshop_id:
        get_workshop(workshop_id)
    workshop_id = req_str(body, "workshop_id")
    get_workshop(workshop_id)
    measured_area = req_int(body, "measured_area_cm2")
    condition = req_enum(body, "condition", CONDITIONS)
    start_raw, end_raw, start, end, duration = parse_slot(body)
    # state (6)
    if r["status"] != "REQUESTED":
        raise ApiError("ERR_RESTORATION_NOT_REQUESTED", 409, "Restoration is not REQUESTED")
    # slot conflict (9)
    if workshop_conflict(workshop_id, start, end):
        raise ApiError("ERR_WORKSHOP_SLOT_CONFLICT", 409, "Workshop slot conflict")

    o = orders.get(r["order_id"])
    # assessed cost
    if (r["is_warranty"] and o is not None and o["production_status"] == "INSTALLED"
            and o["warranty_expires_at"] is not None and logical_clock <= o["warranty_expires_at"]):
        assessed = 0
    else:
        assessed = measured_area * RESTORE_RATE[r["service_type"]]
        if condition == "SEVERE":
            assessed += SEVERE_SURCHARGE_CENTS

    r["workshop_id"] = workshop_id
    r["measured_area_cm2"] = measured_area
    r["condition"] = condition
    r["scheduled_start"] = start_raw
    r["scheduled_end"] = end_raw
    r["duration_minutes"] = duration
    r["assessed_cost_cents"] = assessed
    r["status"] = "ASSESSED"
    touch(r)
    return respond(s_restoration(r), 200)


# =============================================================================
# Entry point
# =============================================================================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
