"""Small-Cell & Wireless Facility Permit (ROW) API.

Single-file Flask implementation. In-memory storage only; every byte of state is
wiped on process restart. All timestamps are driven by an explicit logical clock.
"""
import os
import random
import string
import uuid
from calendar import isleap, monthrange
from datetime import datetime, timedelta, timezone, date
from decimal import Decimal, ROUND_HALF_UP

from flask import Flask, request, jsonify

app = Flask(__name__)
app.url_map.strict_slashes = False

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
ROLES = {"Applicant", "ROWReviewer", "AestheticReviewer", "Approver",
         "Inspector", "PlatformAdmin"}

COLLOCATION_SHOT_CLOCK_DAYS = 60
NEW_POLE_SHOT_CLOCK_DAYS = 90
COLLOCATION_APP_FEE_CENTS = 47533
NEW_POLE_APP_FEE_CENTS = 95066
TECH_SURCHARGE = Decimal("1.0825")
ANNUAL_ROW_RENTAL_PER_NODE_CENTS = 27000

CLOCK_DEFAULT = "2026-05-01T00:00:00Z"

# ---------------------------------------------------------------------------
# In-memory stores
# ---------------------------------------------------------------------------
APPLICANTS = {}
STRUCTURES = {}
SEGMENTS = {}
APPLICATIONS = {}
NODES = {}
NODEREVIEWS = {}
INSPECTIONS = {}
INVOICES = {}
PAYMENTS = {}
RENTALS = {}
NOTICES = {}
APPEALS = {}

_SEQ = [0]


def next_seq():
    _SEQ[0] += 1
    return _SEQ[0]


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------
def parse_iso(s):
    if s is None:
        return None
    t = str(s).strip()
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    dt = datetime.fromisoformat(t)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt


def fmt(dt):
    """Render a datetime as ISO-8601 UTC with three fractional digits."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + ".%03dZ" % (dt.microsecond // 1000)


_CLOCK = {"now": parse_iso(CLOCK_DEFAULT)}


def now():
    return _CLOCK["now"]


def now_str():
    return fmt(_CLOCK["now"])


def add_months(dt, months):
    total = dt.month - 1 + months
    y = dt.year + total // 12
    m = total % 12 + 1
    d = min(dt.day, monthrange(y, m)[1])
    return dt.replace(year=y, month=m, day=d)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, error_id, http, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http = http
        self.message = message or error_id


# ---------------------------------------------------------------------------
# Response envelope
# ---------------------------------------------------------------------------
def _req_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def _meta(extra=None):
    m = {"api_request_id": _req_id(), "api_request_timestamp": now_str()}
    if extra:
        m.update(extra)
    return m


def respond(data, status=200, response_type="object", pagination=None):
    body = {"meta": _meta(pagination), "response_type": response_type, "data": data}
    resp = jsonify(body)
    resp.status_code = status
    return resp


def respond_list(items, pagination):
    body = {"meta": _meta(pagination), "response_type": "array", "data": items}
    resp = jsonify(body)
    resp.status_code = 200
    return resp


@app.after_request
def _conn_close(resp):
    resp.headers["Connection"] = "close"
    return resp


@app.errorhandler(ApiError)
def _handle_api_error(e):
    body = {"meta": _meta(), "response_type": "error",
            "data": {"error_id": e.error_id, "message": e.message}}
    resp = jsonify(body)
    resp.status_code = e.http
    return resp


@app.errorhandler(404)
def _nf(e):
    body = {"meta": _meta(), "response_type": "error",
            "data": {"error_id": "ERR_APPLICATION_NOT_FOUND", "message": "Not found"}}
    return jsonify(body), 404


@app.errorhandler(405)
def _mna(e):
    body = {"meta": _meta(), "response_type": "error",
            "data": {"error_id": "ERR_INVALID_REQUEST", "message": "Method not allowed"}}
    return jsonify(body), 405


@app.errorhandler(Exception)
def _handle_generic(e):
    if isinstance(e, ApiError):
        return _handle_api_error(e)
    body = {"meta": _meta(), "response_type": "error",
            "data": {"error_id": "ERR_INVALID_REQUEST", "message": str(e)}}
    return jsonify(body), 500


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
def require_auth(allowed_roles):
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", 401, "Missing or unknown authentication headers")
    if role not in allowed_roles:
        raise ApiError("ERR_UNAUTHORIZED", 403, "Role not permitted for this operation")
    return uid, role


def get_body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ApiError("ERR_INVALID_REQUEST", 422, "Request body must be a JSON object")
    return data


# ---------------------------------------------------------------------------
# Number normalization
# ---------------------------------------------------------------------------
def num(x):
    if x is None:
        return None
    try:
        f = float(x)
    except (TypeError, ValueError):
        return x
    if f.is_integer():
        return int(f)
    return x


def rhu(dec_value):
    return int(Decimal(dec_value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Versioning helpers
# ---------------------------------------------------------------------------
def touch(entity):
    entity["updated_at"] = now_str()
    entity["version"] = entity.get("version", 1) + 1


def new_versioned():
    ts = now_str()
    return {"id": str(uuid.uuid4()), "created_at": ts, "updated_at": ts,
            "version": 1, "_seq": next_seq()}


def new_audit():
    return {"id": str(uuid.uuid4()), "created_at": now_str(), "_seq": next_seq()}


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------
def s_applicant(a):
    return {k: a[k] for k in ("id", "company_name", "contact_email",
                              "certification_status", "master_agreement_signed",
                              "master_agreement_signed_at", "created_at",
                              "updated_at", "version")}


def s_structure(s):
    available = s["max_collocations"] - s["reserved_collocations"] - s["active_collocations"]
    return {"id": s["id"], "structure_type": s["structure_type"],
            "max_collocations": s["max_collocations"],
            "reserved_collocations": s["reserved_collocations"],
            "active_collocations": s["active_collocations"],
            "available_collocations": available,
            "status": s["status"], "in_design_district": s["in_design_district"],
            "location_desc": s["location_desc"], "created_at": s["created_at"],
            "updated_at": s["updated_at"], "version": s["version"]}


def s_segment(seg):
    return {"id": seg["id"], "name": seg["name"], "corridor_code": seg["corridor_code"],
            "last_paved_at": seg["last_paved_at"], "moratorium_months": seg["moratorium_months"],
            "in_historic_district": seg["in_historic_district"], "created_at": seg["created_at"]}


def application_node_count(app_id):
    return sum(1 for n in NODES.values() if n["application_id"] == app_id)


def application_deadline(a):
    if not a.get("submitted_at"):
        return None
    base = parse_iso(a["submitted_at"])
    return fmt(base + timedelta(days=a["shot_clock_base_days"])
               + timedelta(days=float(a["toll_days_accumulated"])))


def s_application(a):
    return {"id": a["id"], "applicant_id": a["applicant_id"], "project_name": a["project_name"],
            "status": a["status"], "node_count": application_node_count(a["id"]),
            "shot_clock_base_days": a["shot_clock_base_days"], "submitted_at": a["submitted_at"],
            "toll_days_accumulated": num(a["toll_days_accumulated"]),
            "shot_clock_deadline": application_deadline(a), "decided_at": a["decided_at"],
            "created_at": a["created_at"], "updated_at": a["updated_at"], "version": a["version"]}


def s_node(n):
    return {"id": n["id"], "application_id": n["application_id"],
            "support_structure_id": n["support_structure_id"], "row_segment_id": n["row_segment_id"],
            "facility_type": n["facility_type"], "proposed_construction_date": n["proposed_construction_date"],
            "location_desc": n["location_desc"], "status": n["status"],
            "design_review_status": n["design_review_status"],
            "aesthetic_review_status": n["aesthetic_review_status"],
            "created_at": n["created_at"], "updated_at": n["updated_at"], "version": n["version"]}


def s_review(r):
    return {"id": r["id"], "node_id": r["node_id"], "review_type": r["review_type"],
            "outcome": r["outcome"], "reviewer_user_id": r["reviewer_user_id"],
            "findings": r["findings"], "created_at": r["created_at"]}


def s_inspection(i):
    return {"id": i["id"], "node_id": i["node_id"], "outcome": i["outcome"],
            "inspector_user_id": i["inspector_user_id"], "scheduled_start": i["scheduled_start"],
            "scheduled_end": i["scheduled_end"], "notes": i["notes"], "created_at": i["created_at"]}


def s_invoice(inv):
    outstanding = inv["assessed_amount_cents"] - inv["paid_amount_cents"] + inv["refunded_amount_cents"]
    return {"id": inv["id"], "application_id": inv["application_id"], "fee_variant": inv["fee_variant"],
            "assessed_amount_cents": inv["assessed_amount_cents"], "paid_amount_cents": inv["paid_amount_cents"],
            "refunded_amount_cents": inv["refunded_amount_cents"], "outstanding_amount_cents": outstanding,
            "status": inv["status"], "created_at": inv["created_at"],
            "updated_at": inv["updated_at"], "version": inv["version"]}


def s_payment(p):
    return {"id": p["id"], "fee_invoice_id": p["fee_invoice_id"], "amount_cents": p["amount_cents"],
            "payment_type": p["payment_type"], "status": p["status"], "created_at": p["created_at"]}


def s_rental(r):
    return {"id": r["id"], "node_id": r["node_id"], "status": r["status"],
            "billing_year": r["billing_year"], "period_start": r["period_start"],
            "period_end": r["period_end"], "estimated_amount_cents": r["estimated_amount_cents"],
            "actual_amount_cents": r["actual_amount_cents"], "created_at": r["created_at"],
            "updated_at": r["updated_at"], "version": r["version"]}


def s_notice(n):
    return {"id": n["id"], "application_id": n["application_id"], "issued_at": n["issued_at"],
            "cured_at": n["cured_at"], "toll_days": num(n["toll_days"]),
            "deficiencies": n["deficiencies"], "created_at": n["created_at"]}


def s_appeal(a):
    return {"id": a["id"], "application_id": a["application_id"], "grounds": a["grounds"],
            "status": a["status"], "decided_by_user_id": a["decided_by_user_id"],
            "decision_notes": a["decision_notes"], "created_at": a["created_at"],
            "updated_at": a["updated_at"], "version": a["version"]}


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------
def get_or_404(store, key, error_id):
    obj = store.get(key)
    if obj is None:
        raise ApiError(error_id, 404, "Resource not found")
    return obj


def nodes_of(app_id):
    return sorted((n for n in NODES.values() if n["application_id"] == app_id),
                  key=lambda x: x["_seq"])


def invoice_of(app_id):
    for inv in INVOICES.values():
        if inv["application_id"] == app_id:
            return inv
    return None


def reviews_of_application(app_id):
    node_ids = {n["id"] for n in NODES.values() if n["application_id"] == app_id}
    return [r for r in NODEREVIEWS.values() if r["node_id"] in node_ids]


def rentals_of_node(node_id):
    return sorted((r for r in RENTALS.values() if r["node_id"] == node_id),
                  key=lambda x: x["_seq"])


def pending_rental_of_node(node_id):
    for r in rentals_of_node(node_id):
        if r["status"] == "PENDING":
            return r
    return None


def latest_inspection(node_id):
    insp = [i for i in INSPECTIONS.values() if i["node_id"] == node_id]
    if not insp:
        return None
    return max(insp, key=lambda x: x["_seq"])


# ---------------------------------------------------------------------------
# Ownership
# ---------------------------------------------------------------------------
def owner_guard(app_obj, uid, role):
    if role == "Applicant" and app_obj["applicant_id"] != uid:
        raise ApiError("ERR_UNAUTHORIZED", 403, "Applicant may only act on its own resources")


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------
def paginate(items):
    args = request.args
    try:
        limit = int(args.get("limit", 10))
    except (TypeError, ValueError):
        limit = 10
    try:
        offset = int(args.get("offset", 0))
    except (TypeError, ValueError):
        offset = 0
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    total = len(items)
    page = items[offset:offset + limit]
    meta = {"limit": limit, "offset": offset, "total_count": total,
            "has_more": offset + limit < total}
    return page, meta


# ---------------------------------------------------------------------------
# Calculations
# ---------------------------------------------------------------------------
def per_node_fee(facility_type):
    base = NEW_POLE_APP_FEE_CENTS if facility_type == "NEW_POLE" else COLLOCATION_APP_FEE_CENTS
    return rhu(Decimal(base) * TECH_SURCHARGE)


def application_fee(nodes):
    return sum(per_node_fee(n["facility_type"]) for n in nodes)


def prorate_rental(ref_dt):
    year = ref_dt.year
    diy = 366 if isleap(year) else 365
    remaining = (date(year, 12, 31) - ref_dt.date()).days + 1
    return rhu(Decimal(ANNUAL_ROW_RENTAL_PER_NODE_CENTS) * Decimal(remaining) / Decimal(diy))


# ---------------------------------------------------------------------------
# Structure slot accounting (each counter change bumps the structure version)
# ---------------------------------------------------------------------------
def adjust_structure(structure, d_reserved=0, d_active=0):
    structure["reserved_collocations"] += d_reserved
    structure["active_collocations"] += d_active
    touch(structure)


def release_reserved(node):
    """Release a reserved slot held by a node, exactly once."""
    if node.get("_slot_reserved"):
        structure = STRUCTURES.get(node["support_structure_id"])
        if structure:
            adjust_structure(structure, d_reserved=-1)
        node["_slot_reserved"] = False


# ---------------------------------------------------------------------------
# Fork-join evaluation for a node
# ---------------------------------------------------------------------------
def evaluate_join(node):
    if node["status"] != "IN_REVIEW":
        return
    d = node["design_review_status"]
    a = node["aesthetic_review_status"]
    if d == "FAIL" or a == "FAIL":
        release_reserved(node)
        node["status"] = "REJECTED"
    elif d == "PASS" and a in ("PASS", "WAIVED"):
        node["status"] = "APPROVED"


# ---------------------------------------------------------------------------
# Rental / invoice helpers
# ---------------------------------------------------------------------------
def create_rental(node, ref_dt):
    r = new_versioned()
    r.update({"node_id": node["id"], "status": "PENDING", "billing_year": None,
              "period_start": None, "period_end": None,
              "estimated_amount_cents": prorate_rental(ref_dt), "actual_amount_cents": 0})
    RENTALS[r["id"]] = r
    return r


def create_payment(inv, amount, ptype):
    p = new_audit()
    p.update({"fee_invoice_id": inv["id"], "amount_cents": amount,
              "payment_type": ptype, "status": "CAPTURED"})
    PAYMENTS[p["id"]] = p
    if ptype == "PAYMENT":
        inv["paid_amount_cents"] += amount
    else:
        inv["refunded_amount_cents"] += amount
    return p


def net_collected(inv):
    return inv["paid_amount_cents"] - inv["refunded_amount_cents"]


def recompute_final_assessed(app_obj, inv):
    permitted = [n for n in nodes_of(app_obj["id"]) if n["status"] == "PERMITTED"]
    inv["assessed_amount_cents"] = application_fee(permitted)
    inv["fee_variant"] = "FINAL"


# ===========================================================================
# ROUTES
# ===========================================================================

# --- Logical clock ---------------------------------------------------------
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    require_auth({"PlatformAdmin"})
    data = get_body()
    to_iso = data.get("to_iso8601")
    if to_iso is None:
        raise ApiError("ERR_INVALID_REQUEST", 422, "to_iso8601 is required")
    try:
        parsed = parse_iso(to_iso)
    except Exception:
        raise ApiError("ERR_INVALID_REQUEST", 422, "invalid to_iso8601")
    _CLOCK["now"] = parsed
    return respond({}, 200)


# --- Applicants ------------------------------------------------------------
@app.route("/applicants", methods=["POST"])
def create_applicant():
    require_auth({"PlatformAdmin"})
    data = get_body()
    company = data.get("company_name")
    email = data.get("contact_email")
    if not isinstance(company, str) or not company or not isinstance(email, str) or not email:
        raise ApiError("ERR_INVALID_REQUEST", 422, "company_name and contact_email are required")
    a = new_versioned()
    a.update({"company_name": company, "contact_email": email,
              "certification_status": "REGISTERED", "master_agreement_signed": False,
              "master_agreement_signed_at": None})
    APPLICANTS[a["id"]] = a
    return respond(s_applicant(a), 201)


@app.route("/applicants/<aid>", methods=["GET"])
def get_applicant(aid):
    uid, role = require_auth({"PlatformAdmin", "Applicant"})
    a = get_or_404(APPLICANTS, aid, "ERR_APPLICANT_NOT_FOUND")
    if role == "Applicant" and a["id"] != uid:
        raise ApiError("ERR_UNAUTHORIZED", 403, "Applicant may only read its own record")
    return respond(s_applicant(a), 200)


@app.route("/applicants/<aid>/sign-master-agreement", methods=["POST"])
def sign_master_agreement(aid):
    uid, role = require_auth({"Applicant"})
    a = get_or_404(APPLICANTS, aid, "ERR_APPLICANT_NOT_FOUND")
    if a["id"] != uid:
        raise ApiError("ERR_UNAUTHORIZED", 403, "Applicant may only sign its own agreement")
    a["master_agreement_signed"] = True
    a["master_agreement_signed_at"] = now_str()
    touch(a)
    return respond(s_applicant(a), 200)


# --- Support structures ----------------------------------------------------
@app.route("/support-structures", methods=["POST"])
def create_structure():
    require_auth({"PlatformAdmin", "Applicant"})
    data = get_body()
    st = data.get("structure_type")
    if st not in ("EXISTING_UTILITY", "EXISTING_MUNICIPAL", "NEW_POLE"):
        raise ApiError("ERR_INVALID_REQUEST", 422, "invalid structure_type")
    maxc = data.get("max_collocations")
    if not isinstance(maxc, int) or isinstance(maxc, bool) or maxc < 1:
        raise ApiError("ERR_INVALID_REQUEST", 422, "max_collocations must be an integer >= 1")
    in_dd = data.get("in_design_district", "NONE")
    if in_dd is None:
        in_dd = "NONE"
    if in_dd not in ("NONE", "STANDARD", "HISTORIC"):
        raise ApiError("ERR_INVALID_REQUEST", 422, "invalid in_design_district")
    s = new_versioned()
    s.update({"structure_type": st, "max_collocations": maxc, "reserved_collocations": 0,
              "active_collocations": 0, "status": "ACTIVE", "in_design_district": in_dd,
              "location_desc": data.get("location_desc")})
    STRUCTURES[s["id"]] = s
    return respond(s_structure(s), 201)


@app.route("/support-structures/<sid>", methods=["GET"])
def get_structure(sid):
    require_auth({"PlatformAdmin", "Applicant", "ROWReviewer"})
    s = get_or_404(STRUCTURES, sid, "ERR_SUPPORT_STRUCTURE_NOT_FOUND")
    return respond(s_structure(s), 200)


@app.route("/support-structures/<sid>/retire", methods=["POST"])
def retire_structure(sid):
    require_auth({"PlatformAdmin"})
    s = get_or_404(STRUCTURES, sid, "ERR_SUPPORT_STRUCTURE_NOT_FOUND")
    if s["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "structure is not ACTIVE")
    if s["reserved_collocations"] != 0 or s["active_collocations"] != 0:
        raise ApiError("ERR_INVALID_STATE", 409, "structure still holds slots")
    s["status"] = "RETIRED"
    touch(s)
    return respond(s_structure(s), 200)


@app.route("/support-structures/<sid>/nodes", methods=["GET"])
def list_structure_nodes(sid):
    uid, role = require_auth({"PlatformAdmin", "Applicant", "ROWReviewer"})
    get_or_404(STRUCTURES, sid, "ERR_SUPPORT_STRUCTURE_NOT_FOUND")
    items = sorted((n for n in NODES.values() if n["support_structure_id"] == sid),
                   key=lambda x: x["_seq"])
    if role == "Applicant":
        items = [n for n in items if APPLICATIONS[n["application_id"]]["applicant_id"] == uid]
    page, meta = paginate(items)
    return respond_list([s_node(n) for n in page], meta)


# --- ROW segments ----------------------------------------------------------
@app.route("/row-segments", methods=["POST"])
def create_segment():
    require_auth({"PlatformAdmin"})
    data = get_body()
    name = data.get("name")
    corridor = data.get("corridor_code")
    if not isinstance(name, str) or not name or not isinstance(corridor, str) or not corridor:
        raise ApiError("ERR_INVALID_REQUEST", 422, "name and corridor_code are required")
    mor = data.get("moratorium_months", 36)
    if mor is None:
        mor = 36
    if not isinstance(mor, int) or isinstance(mor, bool) or mor < 0:
        raise ApiError("ERR_INVALID_REQUEST", 422, "invalid moratorium_months")
    hist = data.get("in_historic_district", False)
    if hist is None:
        hist = False
    if not isinstance(hist, bool):
        raise ApiError("ERR_INVALID_REQUEST", 422, "invalid in_historic_district")
    last_paved = data.get("last_paved_at")
    if last_paved is not None:
        try:
            parse_iso(last_paved)
        except Exception:
            raise ApiError("ERR_INVALID_REQUEST", 422, "invalid last_paved_at")
    seg = new_audit()
    seg.update({"name": name, "corridor_code": corridor, "last_paved_at": last_paved,
                "moratorium_months": mor, "in_historic_district": hist})
    SEGMENTS[seg["id"]] = seg
    return respond(s_segment(seg), 201)


@app.route("/row-segments/<sid>", methods=["GET"])
def get_segment(sid):
    require_auth({"PlatformAdmin", "Applicant", "ROWReviewer"})
    seg = get_or_404(SEGMENTS, sid, "ERR_ROW_SEGMENT_NOT_FOUND")
    return respond(s_segment(seg), 200)


@app.route("/row-segments/<sid>/nodes", methods=["GET"])
def list_segment_nodes(sid):
    uid, role = require_auth({"PlatformAdmin", "Applicant", "ROWReviewer"})
    get_or_404(SEGMENTS, sid, "ERR_ROW_SEGMENT_NOT_FOUND")
    items = sorted((n for n in NODES.values() if n["row_segment_id"] == sid),
                   key=lambda x: x["_seq"])
    if role == "Applicant":
        items = [n for n in items if APPLICATIONS[n["application_id"]]["applicant_id"] == uid]
    page, meta = paginate(items)
    return respond_list([s_node(n) for n in page], meta)


# --- Applications ----------------------------------------------------------
@app.route("/applications", methods=["POST"])
def create_application():
    uid, role = require_auth({"Applicant"})
    data = get_body()
    a = new_versioned()
    a.update({"applicant_id": uid, "project_name": data.get("project_name"),
              "status": "DRAFT", "shot_clock_base_days": None, "submitted_at": None,
              "toll_days_accumulated": 0, "decided_at": None})
    APPLICATIONS[a["id"]] = a
    return respond(s_application(a), 201)


@app.route("/applications/<aid>", methods=["GET"])
def get_application(aid):
    uid, role = require_auth({"PlatformAdmin", "Applicant", "ROWReviewer",
                              "AestheticReviewer", "Approver", "Inspector"})
    a = get_or_404(APPLICATIONS, aid, "ERR_APPLICATION_NOT_FOUND")
    owner_guard(a, uid, role)
    return respond(s_application(a), 200)


@app.route("/applications", methods=["GET"])
def list_applications():
    uid, role = require_auth({"PlatformAdmin", "Applicant"})
    items = sorted(APPLICATIONS.values(), key=lambda x: x["_seq"])
    if role == "Applicant":
        items = [a for a in items if a["applicant_id"] == uid]
    else:
        filt = request.args.get("applicant_id")
        if filt:
            items = [a for a in items if a["applicant_id"] == filt]
    status = request.args.get("status")
    if status:
        items = [a for a in items if a["status"] == status]
    page, meta = paginate(items)
    return respond_list([s_application(a) for a in page], meta)


@app.route("/applications/<aid>/nodes", methods=["POST"])
def add_node(aid):
    uid, role = require_auth({"Applicant"})
    a = get_or_404(APPLICATIONS, aid, "ERR_APPLICATION_NOT_FOUND")
    owner_guard(a, uid, role)
    if a["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", 409, "nodes may only be added to a DRAFT application")
    data = get_body()
    ft = data.get("facility_type")
    if ft not in ("COLLOCATION", "NEW_POLE"):
        raise ApiError("ERR_INVALID_REQUEST", 422, "invalid facility_type")
    ssid = data.get("support_structure_id")
    rsid = data.get("row_segment_id")
    pcd = data.get("proposed_construction_date")
    if not ssid or not rsid or not pcd:
        raise ApiError("ERR_INVALID_REQUEST", 422,
                       "support_structure_id, row_segment_id and proposed_construction_date are required")
    try:
        parse_iso(pcd)
    except Exception:
        raise ApiError("ERR_INVALID_REQUEST", 422, "invalid proposed_construction_date")
    get_or_404(STRUCTURES, ssid, "ERR_SUPPORT_STRUCTURE_NOT_FOUND")
    get_or_404(SEGMENTS, rsid, "ERR_ROW_SEGMENT_NOT_FOUND")
    n = new_versioned()
    n.update({"application_id": aid, "support_structure_id": ssid, "row_segment_id": rsid,
              "facility_type": ft, "proposed_construction_date": pcd,
              "location_desc": data.get("location_desc"), "status": "PROPOSED",
              "design_review_status": "PENDING", "aesthetic_review_status": "PENDING",
              "_slot_reserved": False})
    NODES[n["id"]] = n
    return respond(s_node(n), 201)


@app.route("/applications/<aid>/nodes", methods=["GET"])
def list_application_nodes(aid):
    uid, role = require_auth({"PlatformAdmin", "Applicant", "ROWReviewer",
                              "AestheticReviewer", "Approver", "Inspector"})
    a = get_or_404(APPLICATIONS, aid, "ERR_APPLICATION_NOT_FOUND")
    owner_guard(a, uid, role)
    items = nodes_of(aid)
    page, meta = paginate(items)
    return respond_list([s_node(n) for n in page], meta)


@app.route("/nodes/<nid>", methods=["GET"])
def get_node(nid):
    uid, role = require_auth({"PlatformAdmin", "Applicant", "ROWReviewer",
                              "AestheticReviewer", "Approver", "Inspector"})
    n = get_or_404(NODES, nid, "ERR_NODE_NOT_FOUND")
    owner_guard(APPLICATIONS[n["application_id"]], uid, role)
    return respond(s_node(n), 200)


@app.route("/applications/<aid>/submit", methods=["POST"])
def submit_application(aid):
    uid, role = require_auth({"Applicant"})
    a = get_or_404(APPLICATIONS, aid, "ERR_APPLICATION_NOT_FOUND")
    owner_guard(a, uid, role)
    if a["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", 409, "application is not in DRAFT")
    applicant = APPLICANTS.get(a["applicant_id"])
    if not applicant or not applicant["master_agreement_signed"]:
        raise ApiError("ERR_MASTER_AGREEMENT_REQUIRED", 422, "master agreement not signed")
    child = nodes_of(aid)
    if len(child) < 1 or any(not n["support_structure_id"] or not n["row_segment_id"]
                             or not n["proposed_construction_date"] for n in child):
        raise ApiError("ERR_NO_NODES", 422, "at least one fully specified node is required")
    a["submitted_at"] = now_str()
    a["shot_clock_base_days"] = (NEW_POLE_SHOT_CLOCK_DAYS
                                 if any(n["facility_type"] == "NEW_POLE" for n in child)
                                 else COLLOCATION_SHOT_CLOCK_DAYS)
    a["status"] = "SUBMITTED"
    # provisional invoice over all filed nodes
    inv = new_versioned()
    inv.update({"application_id": aid, "fee_variant": "PROVISIONAL",
                "assessed_amount_cents": application_fee(child), "paid_amount_cents": 0,
                "refunded_amount_cents": 0, "status": "OPEN"})
    INVOICES[inv["id"]] = inv
    for n in child:
        n["status"] = "IN_REVIEW"
        seg = SEGMENTS[n["row_segment_id"]]
        struct = STRUCTURES[n["support_structure_id"]]
        if not seg["in_historic_district"] and struct["in_design_district"] == "NONE":
            n["aesthetic_review_status"] = "WAIVED"
        touch(n)
    touch(a)
    return respond(s_application(a), 200)


@app.route("/applications/<aid>/completeness-review", methods=["POST"])
def completeness_review(aid):
    require_auth({"ROWReviewer"})
    a = get_or_404(APPLICATIONS, aid, "ERR_APPLICATION_NOT_FOUND")
    if a["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE", 409, "application is not SUBMITTED")
    data = get_body()
    complete = data.get("complete")
    if not isinstance(complete, bool):
        raise ApiError("ERR_INVALID_REQUEST", 422, "complete flag is required")
    if complete:
        a["status"] = "UNDER_REVIEW"
    else:
        notice = new_audit()
        notice.update({"application_id": aid, "issued_at": now_str(), "cured_at": None,
                       "toll_days": 0, "deficiencies": data.get("deficiencies")})
        NOTICES[notice["id"]] = notice
        a["status"] = "INCOMPLETE"
    touch(a)
    return respond(s_application(a), 200)


@app.route("/applications/<aid>/incompleteness-notices", methods=["GET"])
def list_notices(aid):
    uid, role = require_auth({"PlatformAdmin", "Applicant", "ROWReviewer"})
    a = get_or_404(APPLICATIONS, aid, "ERR_APPLICATION_NOT_FOUND")
    owner_guard(a, uid, role)
    items = sorted((n for n in NOTICES.values() if n["application_id"] == aid),
                   key=lambda x: x["_seq"])
    page, meta = paginate(items)
    return respond_list([s_notice(n) for n in page], meta)


@app.route("/applications/<aid>/cure", methods=["POST"])
def cure_application(aid):
    uid, role = require_auth({"Applicant"})
    a = get_or_404(APPLICATIONS, aid, "ERR_APPLICATION_NOT_FOUND")
    owner_guard(a, uid, role)
    if a["status"] != "INCOMPLETE":
        raise ApiError("ERR_INVALID_STATE", 409, "application is not INCOMPLETE")
    open_notices = sorted((n for n in NOTICES.values()
                           if n["application_id"] == aid and n["cured_at"] is None),
                          key=lambda x: x["_seq"])
    if not open_notices:
        raise ApiError("ERR_INVALID_STATE", 409, "no open incompleteness notice")
    notice = open_notices[-1]
    issued = parse_iso(notice["issued_at"])
    cured = now()
    toll = (cured - issued).total_seconds() / 86400.0
    notice["cured_at"] = now_str()
    notice["toll_days"] = toll
    a["toll_days_accumulated"] = float(a["toll_days_accumulated"]) + toll
    a["status"] = "SUBMITTED"
    touch(a)
    return respond(s_application(a), 200)


# --- Node reviews ----------------------------------------------------------
@app.route("/nodes/<nid>/design-review", methods=["POST"])
def design_review(nid):
    uid, role = require_auth({"ROWReviewer"})
    n = get_or_404(NODES, nid, "ERR_NODE_NOT_FOUND")
    app_obj = APPLICATIONS[n["application_id"]]
    if n["status"] != "IN_REVIEW" or app_obj["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_INVALID_STATE", 409, "node is not reviewable")
    data = get_body()
    outcome = data.get("outcome")
    if outcome not in ("PASS", "FAIL"):
        raise ApiError("ERR_INVALID_REQUEST", 422, "invalid outcome")
    expected = data.get("expected_support_structure_version")
    if not isinstance(expected, int) or isinstance(expected, bool):
        raise ApiError("ERR_INVALID_REQUEST", 422, "expected_support_structure_version is required")
    structure = STRUCTURES[n["support_structure_id"]]
    segment = SEGMENTS[n["row_segment_id"]]
    # 9: structure active
    if structure["status"] != "ACTIVE":
        raise ApiError("ERR_STRUCTURE_NOT_ACTIVE", 409, "support structure is not ACTIVE")
    if outcome == "PASS":
        # 10: pavement moratorium (NEW_POLE only)
        if n["facility_type"] == "NEW_POLE" and segment["last_paved_at"] is not None:
            paved = parse_iso(segment["last_paved_at"])
            window_end = add_months(paved, segment["moratorium_months"])
            pcd = parse_iso(n["proposed_construction_date"])
            if paved <= pcd < window_end:
                raise ApiError("ERR_PAVEMENT_MORATORIUM", 409,
                               "construction date within pavement moratorium")
        # 11: capacity
        if structure["reserved_collocations"] + structure["active_collocations"] >= structure["max_collocations"]:
            raise ApiError("ERR_STRUCTURE_CAPACITY_EXCEEDED", 409, "no remaining capacity")
    # 17: OCC
    if expected != structure["version"]:
        raise ApiError("ERR_STALE_VERSION", 412, "stale support structure version")
    # side effects
    review = new_audit()
    review.update({"node_id": nid, "review_type": "DESIGN_STANDARD", "outcome": outcome,
                   "reviewer_user_id": uid, "findings": data.get("findings")})
    NODEREVIEWS[review["id"]] = review
    n["design_review_status"] = outcome
    if outcome == "PASS":
        structure["reserved_collocations"] += 1
        n["_slot_reserved"] = True
    touch(structure)
    evaluate_join(n)
    touch(n)
    return respond(s_review(review), 201)


@app.route("/nodes/<nid>/aesthetic-review", methods=["POST"])
def aesthetic_review(nid):
    uid, role = require_auth({"AestheticReviewer"})
    n = get_or_404(NODES, nid, "ERR_NODE_NOT_FOUND")
    app_obj = APPLICATIONS[n["application_id"]]
    if (n["status"] != "IN_REVIEW" or app_obj["status"] != "UNDER_REVIEW"
            or n["aesthetic_review_status"] != "PENDING"):
        raise ApiError("ERR_INVALID_STATE", 409, "node aesthetic dimension is not reviewable")
    data = get_body()
    outcome = data.get("outcome")
    if outcome not in ("PASS", "FAIL"):
        raise ApiError("ERR_INVALID_REQUEST", 422, "invalid outcome")
    review = new_audit()
    review.update({"node_id": nid, "review_type": "AESTHETIC_HISTORIC", "outcome": outcome,
                   "reviewer_user_id": uid, "findings": data.get("findings")})
    NODEREVIEWS[review["id"]] = review
    n["aesthetic_review_status"] = outcome
    evaluate_join(n)
    touch(n)
    return respond(s_review(review), 201)


@app.route("/nodes/<nid>/reviews", methods=["GET"])
def list_node_reviews(nid):
    uid, role = require_auth({"PlatformAdmin", "Applicant", "ROWReviewer",
                              "AestheticReviewer", "Approver"})
    n = get_or_404(NODES, nid, "ERR_NODE_NOT_FOUND")
    owner_guard(APPLICATIONS[n["application_id"]], uid, role)
    items = sorted((r for r in NODEREVIEWS.values() if r["node_id"] == nid),
                   key=lambda x: x["_seq"])
    page, meta = paginate(items)
    return respond_list([s_review(r) for r in page], meta)


# --- Batch decision --------------------------------------------------------
@app.route("/applications/<aid>/decision", methods=["POST"])
def application_decision(aid):
    uid, role = require_auth({"Approver"})
    a = get_or_404(APPLICATIONS, aid, "ERR_APPLICATION_NOT_FOUND")
    if a["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_INVALID_STATE", 409, "application is not UNDER_REVIEW")
    get_body()  # decision_notes optional; ignored on stored application
    # 5: four-eyes SoD
    reviewer_ids = {r["reviewer_user_id"] for r in reviews_of_application(aid)}
    if uid in reviewer_ids:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES", 409, "approver reviewed a node of this batch")
    child = nodes_of(aid)
    # 7: nodes pending review
    if any(n["status"] == "IN_REVIEW" for n in child):
        raise ApiError("ERR_NODES_PENDING_REVIEW", 409, "a node is still under review")
    approved = [n for n in child if n["status"] == "APPROVED"]
    rejected = [n for n in child if n["status"] == "REJECTED"]
    inv = invoice_of(aid)
    a["decided_at"] = now_str()
    if approved and not rejected:
        new_status = "GRANTED"
    elif approved and rejected:
        new_status = "PARTIALLY_GRANTED"
    else:
        new_status = "DENIED"
    for n in approved:
        n["status"] = "PERMITTED"
        touch(n)
        create_rental(n, now())
    for n in rejected:
        release_reserved(n)
        n["status"] = "DENIED"
        touch(n)
    if inv:
        if new_status == "DENIED":
            inv["assessed_amount_cents"] = 0
            inv["fee_variant"] = "FINAL"
            net = net_collected(inv)
            if net > 0:
                create_payment(inv, net, "REFUND")
            inv["status"] = "REFUNDED"
        else:
            recompute_final_assessed(a, inv)
            net = net_collected(inv)
            if net > inv["assessed_amount_cents"]:
                create_payment(inv, net - inv["assessed_amount_cents"], "REFUND")
        touch(inv)
    a["status"] = new_status
    touch(a)
    return respond(s_application(a), 200)


@app.route("/applications/<aid>/evaluate-deadline", methods=["POST"])
def evaluate_deadline(aid):
    require_auth({"PlatformAdmin"})
    a = get_or_404(APPLICATIONS, aid, "ERR_APPLICATION_NOT_FOUND")
    if a["status"] not in ("SUBMITTED", "INCOMPLETE", "UNDER_REVIEW"):
        raise ApiError("ERR_INVALID_STATE", 409, "application is not in an undecided state")
    deadline = parse_iso(application_deadline(a))
    if now() <= deadline:
        raise ApiError("ERR_SHOT_CLOCK_NOT_EXPIRED", 409, "shot clock has not strictly expired")
    a["decided_at"] = now_str()
    for n in nodes_of(aid):
        if n["status"] not in ("REJECTED", "DENIED", "WITHDRAWN"):
            n["status"] = "PERMITTED"
            touch(n)
            create_rental(n, now())
    inv = invoice_of(aid)
    if inv:
        recompute_final_assessed(a, inv)
        touch(inv)
    a["status"] = "DEEMED_GRANTED"
    touch(a)
    return respond(s_application(a), 200)


# --- Inspection & activation ----------------------------------------------
@app.route("/nodes/<nid>/inspection", methods=["POST"])
def create_inspection(nid):
    uid, role = require_auth({"Inspector"})
    n = get_or_404(NODES, nid, "ERR_NODE_NOT_FOUND")
    data = get_body()
    outcome = data.get("outcome")
    if outcome not in ("PASS", "FAIL"):
        raise ApiError("ERR_INVALID_REQUEST", 422, "invalid outcome")
    i = new_audit()
    i.update({"node_id": nid, "outcome": outcome, "inspector_user_id": uid,
              "scheduled_start": data.get("scheduled_start"),
              "scheduled_end": data.get("scheduled_end"), "notes": data.get("notes")})
    INSPECTIONS[i["id"]] = i
    return respond(s_inspection(i), 201)


@app.route("/nodes/<nid>/inspections", methods=["GET"])
def list_inspections(nid):
    uid, role = require_auth({"PlatformAdmin", "Applicant", "Inspector"})
    n = get_or_404(NODES, nid, "ERR_NODE_NOT_FOUND")
    if role == "Applicant":
        owner_guard(APPLICATIONS[n["application_id"]], uid, role)
    items = sorted((i for i in INSPECTIONS.values() if i["node_id"] == nid),
                   key=lambda x: x["_seq"])
    page, meta = paginate(items)
    return respond_list([s_inspection(i) for i in page], meta)


@app.route("/nodes/<nid>/activate", methods=["POST"])
def activate_node(nid):
    uid, role = require_auth({"Inspector"})
    n = get_or_404(NODES, nid, "ERR_NODE_NOT_FOUND")
    if n["status"] != "PERMITTED":
        raise ApiError("ERR_INVALID_STATE", 409, "node is not PERMITTED")
    latest = latest_inspection(nid)
    if latest is None or latest["outcome"] != "PASS":
        raise ApiError("ERR_INSPECTION_NOT_PASSED", 409, "latest inspection did not pass")
    inv = invoice_of(n["application_id"])
    outstanding = 0
    if inv:
        outstanding = inv["assessed_amount_cents"] - inv["paid_amount_cents"] + inv["refunded_amount_cents"]
    if outstanding != 0:
        raise ApiError("ERR_INVOICE_UNPAID", 402, "application invoice is not fully paid")
    n["status"] = "ACTIVATED"
    touch(n)
    rental = pending_rental_of_node(nid)
    if rental:
        ref = now()
        rental["status"] = "ACTIVE"
        rental["actual_amount_cents"] = prorate_rental(ref)
        rental["period_start"] = now_str()
        rental["period_end"] = fmt(datetime(ref.year + 1, 1, 1, tzinfo=timezone.utc))
        rental["billing_year"] = ref.year
        touch(rental)
    structure = STRUCTURES.get(n["support_structure_id"])
    if structure:
        d_reserved = -1 if n.get("_slot_reserved") else 0
        n["_slot_reserved"] = False
        adjust_structure(structure, d_reserved=d_reserved, d_active=1)
    return respond(s_node(n), 200)


# --- Rentals ---------------------------------------------------------------
@app.route("/nodes/<nid>/rentals", methods=["GET"])
def list_rentals(nid):
    uid, role = require_auth({"PlatformAdmin", "Applicant", "Inspector"})
    n = get_or_404(NODES, nid, "ERR_NODE_NOT_FOUND")
    if role == "Applicant":
        owner_guard(APPLICATIONS[n["application_id"]], uid, role)
    items = rentals_of_node(nid)
    page, meta = paginate(items)
    return respond_list([s_rental(r) for r in page], meta)


@app.route("/rentals/<rid>/renew", methods=["POST"])
def renew_rental(rid):
    require_auth({"PlatformAdmin"})
    r = get_or_404(RENTALS, rid, "ERR_RENTAL_NOT_FOUND")
    if r["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "rental is not ACTIVE")
    data = get_body()
    ps = data.get("period_start")
    pe = data.get("period_end")
    if not ps or not pe:
        raise ApiError("ERR_INVALID_REQUEST", 422, "period_start and period_end are required")
    try:
        ps_dt = parse_iso(ps)
        pe_dt = parse_iso(pe)
    except Exception:
        raise ApiError("ERR_INVALID_REQUEST", 422, "invalid period bounds")
    # overlap check against all non-VOID rentals of the same node (half-open)
    for other in rentals_of_node(r["node_id"]):
        if other["status"] == "VOID":
            continue
        if other["period_start"] is None or other["period_end"] is None:
            continue
        os_dt = parse_iso(other["period_start"])
        oe_dt = parse_iso(other["period_end"])
        if ps_dt < oe_dt and os_dt < pe_dt:
            raise ApiError("ERR_RENTAL_PERIOD_OVERLAP", 409, "requested period overlaps an existing period")
    r["status"] = "EXPIRED"
    touch(r)
    node = NODES.get(r["node_id"])
    nr = new_versioned()
    nr.update({"node_id": r["node_id"], "status": "ACTIVE",
               "billing_year": ps_dt.year, "period_start": ps, "period_end": pe,
               "estimated_amount_cents": 0, "actual_amount_cents": prorate_rental(ps_dt)})
    RENTALS[nr["id"]] = nr
    return respond(s_rental(nr), 201)


# --- Fee invoices & payments ----------------------------------------------
@app.route("/fee-invoices/<iid>/payments", methods=["POST"])
def create_invoice_payment(iid):
    uid, role = require_auth({"Applicant"})
    inv = get_or_404(INVOICES, iid, "ERR_FEE_INVOICE_NOT_FOUND")
    owner_guard(APPLICATIONS[inv["application_id"]], uid, role)
    data = get_body()
    amount = data.get("amount_cents")
    if not isinstance(amount, int) or isinstance(amount, bool):
        raise ApiError("ERR_INVALID_REQUEST", 422, "amount_cents is required")
    ptype = data.get("payment_type", "PAYMENT")
    if ptype is None:
        ptype = "PAYMENT"
    if ptype not in ("PAYMENT", "REFUND"):
        raise ApiError("ERR_INVALID_REQUEST", 422, "invalid payment_type")
    expected = data.get("expected_fee_invoice_version")
    if not isinstance(expected, int) or isinstance(expected, bool):
        raise ApiError("ERR_INVALID_REQUEST", 422, "expected_fee_invoice_version is required")
    outstanding = inv["assessed_amount_cents"] - inv["paid_amount_cents"] + inv["refunded_amount_cents"]
    # 15: payment amount valid
    if amount <= 0 or amount > outstanding:
        raise ApiError("ERR_INVALID_PAYMENT_AMOUNT", 422, "payment amount is out of range")
    # 17: OCC
    if expected != inv["version"]:
        raise ApiError("ERR_STALE_VERSION", 412, "stale fee invoice version")
    p = create_payment(inv, amount, ptype)
    new_outstanding = inv["assessed_amount_cents"] - inv["paid_amount_cents"] + inv["refunded_amount_cents"]
    if new_outstanding == 0:
        inv["status"] = "PAID"
    touch(inv)
    return respond(s_payment(p), 201)


@app.route("/fee-invoices/<iid>", methods=["GET"])
def get_invoice(iid):
    uid, role = require_auth({"PlatformAdmin", "Applicant"})
    inv = get_or_404(INVOICES, iid, "ERR_FEE_INVOICE_NOT_FOUND")
    if role == "Applicant":
        owner_guard(APPLICATIONS[inv["application_id"]], uid, role)
    return respond(s_invoice(inv), 200)


@app.route("/fee-invoices/<iid>/payments", methods=["GET"])
def list_invoice_payments(iid):
    uid, role = require_auth({"PlatformAdmin", "Applicant"})
    inv = get_or_404(INVOICES, iid, "ERR_FEE_INVOICE_NOT_FOUND")
    if role == "Applicant":
        owner_guard(APPLICATIONS[inv["application_id"]], uid, role)
    items = sorted((p for p in PAYMENTS.values() if p["fee_invoice_id"] == iid),
                   key=lambda x: x["_seq"])
    page, meta = paginate(items)
    return respond_list([s_payment(p) for p in page], meta)


@app.route("/applications/<aid>/fee-invoice", methods=["GET"])
def get_application_invoice(aid):
    uid, role = require_auth({"PlatformAdmin", "Applicant"})
    a = get_or_404(APPLICATIONS, aid, "ERR_APPLICATION_NOT_FOUND")
    owner_guard(a, uid, role)
    inv = invoice_of(aid)
    items = [inv] if inv else []
    page, meta = paginate(items)
    return respond_list([s_invoice(i) for i in page], meta)


# --- Appeals ---------------------------------------------------------------
@app.route("/applications/<aid>/appeal", methods=["POST"])
def file_appeal(aid):
    uid, role = require_auth({"Applicant"})
    a = get_or_404(APPLICATIONS, aid, "ERR_APPLICATION_NOT_FOUND")
    owner_guard(a, uid, role)
    if a["status"] not in ("DENIED", "PARTIALLY_GRANTED"):
        raise ApiError("ERR_APPEAL_NOT_ALLOWED", 409, "application is not appealable")
    data = get_body()
    grounds = data.get("grounds")
    if not isinstance(grounds, str) or not grounds:
        raise ApiError("ERR_INVALID_REQUEST", 422, "grounds is required")
    ap = new_versioned()
    ap.update({"application_id": aid, "grounds": grounds, "status": "FILED",
               "decided_by_user_id": None, "decision_notes": None})
    APPEALS[ap["id"]] = ap
    a["status"] = "UNDER_APPEAL"
    touch(a)
    return respond(s_appeal(ap), 201)


@app.route("/applications/<aid>/appeals", methods=["GET"])
def list_appeals(aid):
    uid, role = require_auth({"PlatformAdmin", "Applicant", "Approver"})
    a = get_or_404(APPLICATIONS, aid, "ERR_APPLICATION_NOT_FOUND")
    owner_guard(a, uid, role)
    items = sorted((ap for ap in APPEALS.values() if ap["application_id"] == aid),
                   key=lambda x: x["_seq"])
    page, meta = paginate(items)
    return respond_list([s_appeal(ap) for ap in page], meta)


@app.route("/appeals/<apid>/decision", methods=["POST"])
def appeal_decision(apid):
    uid, role = require_auth({"Approver"})
    ap = get_or_404(APPEALS, apid, "ERR_APPEAL_NOT_FOUND")
    a = APPLICATIONS[ap["application_id"]]
    if a["status"] != "UNDER_APPEAL" or ap["status"] != "FILED":
        raise ApiError("ERR_INVALID_STATE", 409, "appeal is not decidable")
    data = get_body()
    uphold = data.get("uphold")
    if not isinstance(uphold, bool):
        raise ApiError("ERR_INVALID_REQUEST", 422, "uphold flag is required")
    reviewer_ids = {r["reviewer_user_id"] for r in reviews_of_application(a["id"])}
    if uid in reviewer_ids:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES", 409, "approver reviewed a node of this batch")
    ap["decided_by_user_id"] = uid
    ap["decision_notes"] = data.get("decision_notes")
    if uphold:
        ap["status"] = "UPHELD"
        a["status"] = "APPEAL_DENIED"
        touch(ap)
        touch(a)
    else:
        ap["status"] = "OVERTURNED"
        for n in nodes_of(a["id"]):
            if n["status"] == "DENIED":
                n["status"] = "PERMITTED"
                touch(n)
                create_rental(n, now())
        inv = invoice_of(a["id"])
        if inv:
            recompute_final_assessed(a, inv)
            touch(inv)
        a["status"] = "APPEAL_GRANTED"
        touch(ap)
        touch(a)
    return respond(s_appeal(ap), 200)


# --- Withdraw --------------------------------------------------------------
@app.route("/applications/<aid>/withdraw", methods=["POST"])
def withdraw_application(aid):
    uid, role = require_auth({"Applicant"})
    a = get_or_404(APPLICATIONS, aid, "ERR_APPLICATION_NOT_FOUND")
    owner_guard(a, uid, role)
    if a["status"] not in ("DRAFT", "SUBMITTED", "INCOMPLETE", "UNDER_REVIEW",
                           "GRANTED", "PARTIALLY_GRANTED"):
        raise ApiError("ERR_INVALID_STATE", 409, "application cannot be withdrawn from this state")
    for n in nodes_of(aid):
        if n["status"] not in ("ACTIVATED", "DENIED", "WITHDRAWN"):
            release_reserved(n)
            n["status"] = "WITHDRAWN"
            touch(n)
            rental = pending_rental_of_node(n["id"])
            if rental:
                rental["status"] = "VOID"
                touch(rental)
    inv = invoice_of(aid)
    if inv:
        net = net_collected(inv)
        if net > 0:
            create_payment(inv, net, "REFUND")
            inv["status"] = "REFUNDED"
            touch(inv)
    a["status"] = "WITHDRAWN"
    touch(a)
    return respond(s_application(a), 200)


# ---------------------------------------------------------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
