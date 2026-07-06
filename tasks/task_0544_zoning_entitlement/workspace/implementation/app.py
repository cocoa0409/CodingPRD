"""Zoning Entitlement API — Python + Flask, in-memory store.

Boots empty on every process start; no seeding/preloading of entities.
"""
import os
import random
import string
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import Flask, request, g, jsonify

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
ALL_ROLES = {"Applicant", "Planner", "Clerk", "Commissioner", "Admin"}
ZONING_DISTRICTS = {"RES", "COMM", "IND", "AG"}
APPLICATION_TYPES = {"VARIANCE", "REZONE", "CUP", "SUBDIVISION"}
NOTICE_KINDS = {"MAILED", "PUBLISHED", "POSTED"}
HEARING_BODIES = {"PLANNING_COMMISSION", "CITY_COUNCIL"}

NOTICE_MIN_DAYS = {"PLANNING_COMMISSION": 10, "CITY_COUNCIL": 15}
BODY_MIN_GAP_DAYS = 14
APPEAL_WINDOW_DAYS = 15
ENTITLEMENT_DAYS = {"VARIANCE": 730, "CUP": 730, "SUBDIVISION": 1095, "REZONE": None}
EXTENSION_DAYS = 365
MAX_EXTENSIONS = 1
EXT_REQUEST_WINDOW_DAYS = 90

CLOCK_DEFAULT = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)

# HTTP status for every error id
ERROR_HTTP = {
    "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_PARCEL_NOT_FOUND": 404,
    "ERR_FEE_SCHEDULE_NOT_FOUND": 404,
    "ERR_APPLICANT_NOT_FOUND": 404,
    "ERR_APPLICATION_NOT_FOUND": 404,
    "ERR_HEARING_NOT_FOUND": 404,
    "ERR_AGENDA_ITEM_NOT_FOUND": 404,
    "ERR_APPEAL_NOT_FOUND": 404,
    "ERR_PLAT_NOT_FOUND": 404,
    "ERR_FEE_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 400,
    "ERR_DEFICIENCY_NOTES_REQUIRED": 400,
    "ERR_INVALID_STATE": 409,
    "ERR_APPLICATION_NOT_ACCEPTED": 409,
    "ERR_HEARING_NOT_OPEN": 409,
    "ERR_AGENDA_FULL": 409,
    "ERR_AGENDA_NOT_EMPTY": 409,
    "ERR_APPEAL_WINDOW_OPEN": 409,
    "ERR_APPEAL_PENDING": 409,
    "ERR_NOT_YET_EXPIRED": 409,
    "ERR_FEE_NOT_ASSESSED": 409,
    "ERR_APPLICATION_NOT_EFFECTIVE": 409,
    "ERR_FINDINGS_REQUIRED": 422,
    "ERR_NOTICE_MISSING": 409,
    "ERR_NOTICE_PERIOD_NOT_MET": 422,
    "ERR_HEARING_CALENDAR_CONFLICT": 409,
    "ERR_PARCEL_REVIEW_CONFLICT": 409,
    "ERR_APPEAL_WINDOW_CLOSED": 422,
    "ERR_EXTENSION_WINDOW_CLOSED": 422,
    "ERR_MAX_EXTENSIONS_REACHED": 409,
    "ERR_FEE_AMOUNT_MISMATCH": 402,
    "ERR_STALE_HEARING_VERSION": 412,
}


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = ERROR_HTTP.get(error_id, 400)
        self.message = message or error_id


# ---------------------------------------------------------------------------
# In-memory store (empty on boot)
# ---------------------------------------------------------------------------
DB = {
    "parcels": {},
    "fee_schedules": {},
    "applicants": {},
    "applications": {},
    "completeness_reviews": {},
    "notices": {},
    "hearings": {},
    "agenda_items": {},
    "conditions": {},
    "findings": {},
    "appeals": {},
    "plats": {},
    "assessments": {},
}
STATE = {"clock": CLOCK_DEFAULT, "seq": 0}


def now():
    return STATE["clock"]


def next_seq():
    STATE["seq"] += 1
    return STATE["seq"]


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------
def parse_dt(s):
    if not isinstance(s, str):
        return None
    t = s.strip()
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(t)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt_dt(dt):
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def whole_days(later, earlier):
    """Signed whole-day span between two datetimes (floor)."""
    return int((later - earlier).total_seconds() // 86400)


# ---------------------------------------------------------------------------
# Envelope helpers
# ---------------------------------------------------------------------------
def _meta(extra=None):
    m = {
        "api_request_id": "req_" + "".join(
            random.choices(string.ascii_letters + string.digits, k=20)
        ),
        "api_request_timestamp": fmt_dt(now()),
    }
    if extra:
        m.update(extra)
    return m


def serialize(obj):
    out = {}
    for k, v in obj.items():
        if k.startswith("_"):
            continue
        if isinstance(v, datetime):
            out[k] = fmt_dt(v)
        else:
            out[k] = v
    return out


def respond(data, status=200, is_array=False, page_meta=None):
    body = {
        "meta": _meta(page_meta),
        "response_type": "array" if is_array else "object",
        "data": data,
    }
    return jsonify(body), status


def ok_obj(obj, status=200):
    return respond(serialize(obj), status=status)


def _int_param(name, default):
    raw = request.args.get(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except (ValueError, TypeError):
        return default


def paginate_and_respond(items):
    """items: list of raw entity dicts, already sorted."""
    limit = _int_param("limit", 10)
    offset = _int_param("offset", 0)
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    total = len(items)
    page = items[offset:offset + limit]
    has_more = (offset + limit) < total
    page_meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": has_more,
    }
    return respond([serialize(x) for x in page], is_array=True, page_meta=page_meta)


def sorted_by_created(items):
    return sorted(items, key=lambda x: (x["created_at"], x["_seq"]))


# ---------------------------------------------------------------------------
# Entity construction
# ---------------------------------------------------------------------------
def new_full(fields):
    t = now()
    obj = {"id": str(uuid.uuid4()), "created_at": t, "updated_at": t, "version": 1,
           "_seq": next_seq()}
    obj.update(fields)
    return obj


def new_append_only(fields):
    obj = {"id": str(uuid.uuid4()), "created_at": now(), "_seq": next_seq()}
    obj.update(fields)
    return obj


def touch(obj):
    obj["updated_at"] = now()
    if "version" in obj:
        obj["version"] += 1


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------
def body_json():
    b = request.get_json(silent=True)
    return b if isinstance(b, dict) else {}


def require(*roles):
    if g.role not in roles:
        raise ApiError("ERR_UNAUTHORIZED")


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def is_num(v):
    return (isinstance(v, (int, float)) and not isinstance(v, bool))


def get_or_404(store, key, error_id):
    obj = DB[store].get(key)
    if obj is None:
        raise ApiError(error_id)
    return obj


# ---------------------------------------------------------------------------
# Auth (priority 1)
# ---------------------------------------------------------------------------
@app.before_request
def _auth():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ALL_ROLES:
        raise ApiError("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER")
    g.user_id = uid
    g.role = role


@app.errorhandler(ApiError)
def _handle_api_error(e):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": e.error_id, "message": e.message},
    }
    return jsonify(body), e.http_status


# ---------------------------------------------------------------------------
# Impact fee calculation
# ---------------------------------------------------------------------------
def _rhu(d):
    return d.quantize(Decimal("1"), rounding=ROUND_HALF_UP)


def compute_fee(fs, lots, acres, affordable, prior_paid):
    park = Decimal(fs["park_fee_per_lot_cents"]) * Decimal(lots)
    acres_d = Decimal(str(acres))
    t1 = min(acres_d, Decimal(5)) * Decimal(fs["road_fee_tier1_per_acre_cents"])
    t2 = min(max(acres_d - Decimal(5), Decimal(0)), Decimal(15)) * Decimal(
        fs["road_fee_tier2_per_acre_cents"])
    t3 = max(acres_d - Decimal(20), Decimal(0)) * Decimal(
        fs["road_fee_tier3_per_acre_cents"])
    road = t1 + t2 + t3
    subtotal = park + road
    if affordable:
        discount = _rhu(subtotal * Decimal(str(fs["affordable_discount_pct"])))
    else:
        discount = Decimal(0)
    subtotal_after = subtotal - discount
    admin = _rhu(subtotal_after * Decimal(str(fs["admin_pct"])))
    gross = min(Decimal(fs["fee_cap_cents"]), subtotal_after + admin)
    credit_cap = _rhu(gross * Decimal(str(fs["credit_pct"])))
    credit = min(credit_cap, Decimal(prior_paid))
    net = gross - credit
    return int(gross), int(credit), int(net)


# ===========================================================================
# Clock
# ===========================================================================
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    require("Admin")
    b = body_json()
    dt = parse_dt(b.get("to_iso8601"))
    if dt is None:
        raise ApiError("ERR_INVALID_REQUEST")
    STATE["clock"] = dt
    return respond({}, status=200)


# ===========================================================================
# Parcel
# ===========================================================================
@app.route("/parcels", methods=["POST"])
def create_parcel():
    require("Admin")
    b = body_json()
    apn = b.get("apn")
    zd = b.get("zoning_district")
    area = b.get("area_acres")
    ncount = b.get("neighbor_parcel_count")
    ecount = b.get("expanded_neighbor_count")
    sensitive = b.get("sensitive_area", False)

    if not isinstance(apn, str) or not apn:
        raise ApiError("ERR_INVALID_REQUEST")
    if zd not in ZONING_DISTRICTS:
        raise ApiError("ERR_INVALID_REQUEST")
    if not is_num(area) or area <= 0:
        raise ApiError("ERR_INVALID_REQUEST")
    if not is_int(ncount) or ncount < 0:
        raise ApiError("ERR_INVALID_REQUEST")
    if not is_int(ecount) or ecount < ncount:
        raise ApiError("ERR_INVALID_REQUEST")
    if not isinstance(sensitive, bool):
        raise ApiError("ERR_INVALID_REQUEST")
    for p in DB["parcels"].values():
        if p["apn"] == apn:
            raise ApiError("ERR_INVALID_REQUEST")

    obj = new_full({
        "apn": apn,
        "zoning_district": zd,
        "area_acres": area,
        "neighbor_parcel_count": ncount,
        "expanded_neighbor_count": ecount,
        "sensitive_area": sensitive,
        "assessed_fee_cents": 0,
        "status": "AVAILABLE",
    })
    DB["parcels"][obj["id"]] = obj
    return ok_obj(obj, 201)


@app.route("/parcels/<pid>", methods=["GET"])
def get_parcel(pid):
    require(*ALL_ROLES)
    return ok_obj(get_or_404("parcels", pid, "ERR_PARCEL_NOT_FOUND"))


# ===========================================================================
# FeeSchedule
# ===========================================================================
@app.route("/fee-schedules", methods=["POST"])
def create_fee_schedule():
    require("Admin")
    b = body_json()
    name = b.get("name")
    ints = ["park_fee_per_lot_cents", "road_fee_tier1_per_acre_cents",
            "road_fee_tier2_per_acre_cents", "road_fee_tier3_per_acre_cents",
            "fee_cap_cents"]
    nums = ["admin_pct", "affordable_discount_pct", "credit_pct"]
    if not isinstance(name, str) or not name:
        raise ApiError("ERR_INVALID_REQUEST")
    for f in ints:
        if not is_int(b.get(f)) or b.get(f) < 0:
            raise ApiError("ERR_INVALID_REQUEST")
    for f in nums:
        if not is_num(b.get(f)) or b.get(f) < 0:
            raise ApiError("ERR_INVALID_REQUEST")
    obj = new_full({
        "name": name,
        "park_fee_per_lot_cents": b["park_fee_per_lot_cents"],
        "road_fee_tier1_per_acre_cents": b["road_fee_tier1_per_acre_cents"],
        "road_fee_tier2_per_acre_cents": b["road_fee_tier2_per_acre_cents"],
        "road_fee_tier3_per_acre_cents": b["road_fee_tier3_per_acre_cents"],
        "admin_pct": b["admin_pct"],
        "affordable_discount_pct": b["affordable_discount_pct"],
        "credit_pct": b["credit_pct"],
        "fee_cap_cents": b["fee_cap_cents"],
    })
    DB["fee_schedules"][obj["id"]] = obj
    return ok_obj(obj, 201)


@app.route("/fee-schedules/<fid>", methods=["GET"])
def get_fee_schedule(fid):
    require(*ALL_ROLES)
    return ok_obj(get_or_404("fee_schedules", fid, "ERR_FEE_SCHEDULE_NOT_FOUND"))


# ===========================================================================
# Applicant
# ===========================================================================
@app.route("/applicants", methods=["POST"])
def create_applicant():
    require("Applicant", "Admin")
    b = body_json()
    name = b.get("full_name")
    email = b.get("email")
    org = b.get("organization")
    if not isinstance(name, str) or not name:
        raise ApiError("ERR_INVALID_REQUEST")
    if not isinstance(email, str) or not email:
        raise ApiError("ERR_INVALID_REQUEST")
    if org is not None and not isinstance(org, str):
        raise ApiError("ERR_INVALID_REQUEST")
    obj = new_full({"full_name": name, "email": email, "organization": org})
    DB["applicants"][obj["id"]] = obj
    return ok_obj(obj, 201)


@app.route("/applicants/<aid>", methods=["GET"])
def get_applicant(aid):
    require(*ALL_ROLES)
    return ok_obj(get_or_404("applicants", aid, "ERR_APPLICANT_NOT_FOUND"))


# ===========================================================================
# EntitlementApplication
# ===========================================================================
@app.route("/applications", methods=["POST"])
def create_application():
    require("Applicant")
    b = body_json()
    app_type = b.get("application_type")
    parcel_id = b.get("parcel_id")
    applicant_id = b.get("applicant_id")
    requested_use = b.get("requested_use")
    affordable = b.get("affordable_housing", False)

    # existence (present ids) before field validity
    if parcel_id is not None and parcel_id not in DB["parcels"]:
        raise ApiError("ERR_PARCEL_NOT_FOUND")
    if applicant_id is not None and applicant_id not in DB["applicants"]:
        raise ApiError("ERR_APPLICANT_NOT_FOUND")

    if app_type not in APPLICATION_TYPES:
        raise ApiError("ERR_INVALID_REQUEST")
    if not parcel_id or not applicant_id:
        raise ApiError("ERR_INVALID_REQUEST")
    if not isinstance(requested_use, str) or not requested_use:
        raise ApiError("ERR_INVALID_REQUEST")
    if not isinstance(affordable, bool):
        raise ApiError("ERR_INVALID_REQUEST")

    obj = new_full({
        "application_type": app_type,
        "parcel_id": parcel_id,
        "applicant_id": applicant_id,
        "requested_use": requested_use,
        "affordable_housing": affordable,
        "status": "DRAFT",
        "submitted_at": None,
        "revision_count": 0,
        "assigned_planner_user_id": None,
        "decision": None,
        "decision_at": None,
        "appeal_deadline": None,
        "provisional_expiration_date": None,
        "effective_date": None,
        "final_expiration_date": None,
        "extension_count": 0,
        "review_window_closed_at": None,
    })
    DB["applications"][obj["id"]] = obj
    return ok_obj(obj, 201)


@app.route("/applications", methods=["GET"])
def list_applications():
    require(*ALL_ROLES)
    items = list(DB["applications"].values())
    f_applicant = request.args.get("applicant_id")
    f_parcel = request.args.get("parcel_id")
    f_status = request.args.get("status")
    if f_applicant is not None:
        items = [x for x in items if x["applicant_id"] == f_applicant]
    if f_parcel is not None:
        items = [x for x in items if x["parcel_id"] == f_parcel]
    if f_status is not None:
        items = [x for x in items if x["status"] == f_status]
    return paginate_and_respond(sorted_by_created(items))


@app.route("/applications/<app_id>", methods=["GET"])
def get_application(app_id):
    require(*ALL_ROLES)
    return ok_obj(get_or_404("applications", app_id, "ERR_APPLICATION_NOT_FOUND"))


def _apps_on_parcel(parcel_id, exclude_id):
    return [a for a in DB["applications"].values()
            if a["parcel_id"] == parcel_id and a["id"] != exclude_id]


@app.route("/applications/<app_id>/submit", methods=["POST"])
def submit_application(app_id):
    require("Applicant")
    app_o = get_or_404("applications", app_id, "ERR_APPLICATION_NOT_FOUND")
    # ownership
    if app_o["applicant_id"] != g.user_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")
    st = app_o["status"]
    if st not in ("DRAFT", "INCOMPLETE"):
        raise ApiError("ERR_INVALID_STATE")

    if st == "DRAFT":
        # parcel review overlap (half-open interval overlap on same parcel)
        t = now()
        for other in _apps_on_parcel(app_o["parcel_id"], app_id):
            if other["submitted_at"] is None:
                continue
            close = other["review_window_closed_at"]
            if close is None or close > t:
                raise ApiError("ERR_PARCEL_REVIEW_CONFLICT")
        app_o["submitted_at"] = t
        app_o["review_window_closed_at"] = None
        app_o["status"] = "SUBMITTED"
        touch(app_o)
        parcel = DB["parcels"].get(app_o["parcel_id"])
        if parcel is not None and parcel["status"] == "AVAILABLE":
            parcel["status"] = "UNDER_APPLICATION"
            touch(parcel)
    else:  # INCOMPLETE -> SUBMITTED (resubmit)
        app_o["revision_count"] += 1
        app_o["status"] = "SUBMITTED"
        touch(app_o)
    return ok_obj(app_o, 200)


@app.route("/applications/<app_id>/completeness", methods=["POST"])
def record_completeness(app_id):
    require("Planner")
    app_o = get_or_404("applications", app_id, "ERR_APPLICATION_NOT_FOUND")
    if app_o["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE")
    b = body_json()
    determination = b.get("determination")
    notes = b.get("deficiency_notes")
    if determination not in ("COMPLETE", "INCOMPLETE"):
        raise ApiError("ERR_INVALID_REQUEST")
    if determination == "INCOMPLETE" and (not isinstance(notes, str) or not notes):
        raise ApiError("ERR_DEFICIENCY_NOTES_REQUIRED")

    review = new_append_only({
        "application_id": app_id,
        "cycle_number": app_o["revision_count"] + 1,
        "determination": determination,
        "deficiency_notes": notes if determination == "INCOMPLETE" else None,
        "reviewed_by": g.user_id,
    })
    DB["completeness_reviews"][review["id"]] = review

    if app_o["assigned_planner_user_id"] is None:
        app_o["assigned_planner_user_id"] = g.user_id
    if determination == "COMPLETE":
        app_o["status"] = "ACCEPTED"
    else:
        app_o["status"] = "INCOMPLETE"
    touch(app_o)
    return ok_obj(review, 201)


@app.route("/applications/<app_id>/completeness-reviews", methods=["GET"])
def list_completeness(app_id):
    require(*ALL_ROLES)
    get_or_404("applications", app_id, "ERR_APPLICATION_NOT_FOUND")
    items = [r for r in DB["completeness_reviews"].values()
             if r["application_id"] == app_id]
    return paginate_and_respond(sorted_by_created(items))


@app.route("/applications/<app_id>/notices", methods=["POST"])
def create_notice(app_id):
    require("Clerk")
    app_o = get_or_404("applications", app_id, "ERR_APPLICATION_NOT_FOUND")
    b = body_json()
    kind = b.get("notice_kind")
    if kind not in NOTICE_KINDS:
        raise ApiError("ERR_INVALID_REQUEST")
    parcel = DB["parcels"].get(app_o["parcel_id"])
    if parcel is not None and parcel["sensitive_area"]:
        recipient_count = parcel["expanded_neighbor_count"]
        used_expanded = True
    else:
        recipient_count = parcel["neighbor_parcel_count"] if parcel else 0
        used_expanded = False
    obj = new_full({
        "application_id": app_id,
        "notice_kind": kind,
        "mailed_at": now(),
        "recipient_count": recipient_count,
        "used_expanded_radius": used_expanded,
        "status": "SENT",
    })
    DB["notices"][obj["id"]] = obj
    return ok_obj(obj, 201)


@app.route("/applications/<app_id>/notices", methods=["GET"])
def list_notices(app_id):
    require(*ALL_ROLES)
    get_or_404("applications", app_id, "ERR_APPLICATION_NOT_FOUND")
    items = [n for n in DB["notices"].values() if n["application_id"] == app_id]
    return paginate_and_respond(sorted_by_created(items))


@app.route("/applications/<app_id>/withdraw", methods=["POST"])
def withdraw_application(app_id):
    require("Applicant")
    app_o = get_or_404("applications", app_id, "ERR_APPLICATION_NOT_FOUND")
    if app_o["applicant_id"] != g.user_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")
    st = app_o["status"]
    if st not in ("DRAFT", "SUBMITTED", "INCOMPLETE", "ACCEPTED", "SCHEDULED"):
        raise ApiError("ERR_INVALID_STATE")

    if st == "SCHEDULED":
        for item in DB["agenda_items"].values():
            if item["application_id"] == app_id and item["status"] == "PLACED":
                item["status"] = "REMOVED"
                touch(item)
                hearing = DB["hearings"].get(item["hearing_id"])
                if hearing is not None:
                    hearing["agenda_slots_remaining"] += 1
                    touch(hearing)

    app_o["status"] = "WITHDRAWN"
    app_o["review_window_closed_at"] = now()
    touch(app_o)
    parcel = DB["parcels"].get(app_o["parcel_id"])
    if parcel is not None and parcel["status"] == "UNDER_APPLICATION":
        parcel["status"] = "AVAILABLE"
        touch(parcel)
    return ok_obj(app_o, 200)


def _entitlement_days(app_o):
    return ENTITLEMENT_DAYS[app_o["application_type"]]


@app.route("/applications/<app_id>/effectuate", methods=["POST"])
def effectuate_application(app_id):
    require("Clerk")
    app_o = get_or_404("applications", app_id, "ERR_APPLICATION_NOT_FOUND")
    st = app_o["status"]
    t = now()

    if st == "DECIDED_APPROVED":
        if not (t > app_o["appeal_deadline"]):
            raise ApiError("ERR_APPEAL_WINDOW_OPEN")
        if _has_blocking_appeal(app_id):
            raise ApiError("ERR_APPEAL_PENDING")
        app_o["status"] = "EFFECTIVE"
        app_o["effective_date"] = app_o["appeal_deadline"]
        ed = _entitlement_days(app_o)
        app_o["final_expiration_date"] = (
            None if ed is None else app_o["effective_date"] + timedelta(days=ed))
        touch(app_o)
        parcel = DB["parcels"].get(app_o["parcel_id"])
        if parcel is not None and parcel["status"] == "UNDER_APPLICATION":
            parcel["status"] = "ENTITLED"
            touch(parcel)
        return ok_obj(app_o, 200)

    if st == "DECIDED_DENIED":
        if not (t > app_o["appeal_deadline"]):
            raise ApiError("ERR_APPEAL_WINDOW_OPEN")
        if _has_blocking_appeal(app_id):
            raise ApiError("ERR_APPEAL_PENDING")
        app_o["status"] = "CLOSED"
        app_o["review_window_closed_at"] = t
        touch(app_o)
        parcel = DB["parcels"].get(app_o["parcel_id"])
        if parcel is not None and parcel["status"] == "UNDER_APPLICATION":
            parcel["status"] = "AVAILABLE"
            touch(parcel)
        return ok_obj(app_o, 200)

    if st == "EFFECTIVE":
        if app_o["application_type"] == "REZONE" or app_o["final_expiration_date"] is None:
            raise ApiError("ERR_NOT_YET_EXPIRED")
        if not (t > app_o["final_expiration_date"]):
            raise ApiError("ERR_NOT_YET_EXPIRED")
        app_o["status"] = "EXPIRED"
        app_o["review_window_closed_at"] = t
        touch(app_o)
        parcel = DB["parcels"].get(app_o["parcel_id"])
        if parcel is not None and parcel["status"] == "ENTITLED":
            parcel["status"] = "AVAILABLE"
            touch(parcel)
        return ok_obj(app_o, 200)

    raise ApiError("ERR_INVALID_STATE")


def _has_blocking_appeal(app_id):
    for ap in DB["appeals"].values():
        if ap["application_id"] == app_id and ap["status"] in ("FILED", "UPHELD"):
            return True
    return False


@app.route("/applications/<app_id>/extend", methods=["POST"])
def extend_application(app_id):
    require("Clerk")
    app_o = get_or_404("applications", app_id, "ERR_APPLICATION_NOT_FOUND")
    if app_o["status"] != "EFFECTIVE":
        raise ApiError("ERR_INVALID_STATE")
    fexp = app_o["final_expiration_date"]
    t = now()
    if fexp is None:
        raise ApiError("ERR_EXTENSION_WINDOW_CLOSED")
    window_open = fexp - timedelta(days=EXT_REQUEST_WINDOW_DAYS)
    if not (window_open <= t <= fexp):
        raise ApiError("ERR_EXTENSION_WINDOW_CLOSED")
    if app_o["extension_count"] >= MAX_EXTENSIONS:
        raise ApiError("ERR_MAX_EXTENSIONS_REACHED")
    app_o["final_expiration_date"] = fexp + timedelta(days=EXTENSION_DAYS)
    app_o["extension_count"] += 1
    touch(app_o)
    return ok_obj(app_o, 200)


def _child_list(store, parent_key, parent_val, err):
    get_or_404("applications", parent_val, err)
    items = [x for x in DB[store].values() if x[parent_key] == parent_val]
    return paginate_and_respond(sorted_by_created(items))


@app.route("/applications/<app_id>/conditions", methods=["GET"])
def list_conditions(app_id):
    require(*ALL_ROLES)
    return _child_list("conditions", "application_id", app_id,
                       "ERR_APPLICATION_NOT_FOUND")


@app.route("/applications/<app_id>/findings", methods=["GET"])
def list_findings(app_id):
    require(*ALL_ROLES)
    return _child_list("findings", "application_id", app_id,
                       "ERR_APPLICATION_NOT_FOUND")


@app.route("/applications/<app_id>/appeals", methods=["GET"])
def list_app_appeals(app_id):
    require(*ALL_ROLES)
    return _child_list("appeals", "application_id", app_id,
                       "ERR_APPLICATION_NOT_FOUND")


@app.route("/applications/<app_id>/agenda-items", methods=["GET"])
def list_app_agenda_items(app_id):
    require(*ALL_ROLES)
    return _child_list("agenda_items", "application_id", app_id,
                       "ERR_APPLICATION_NOT_FOUND")


# ===========================================================================
# Hearing
# ===========================================================================
@app.route("/hearings", methods=["POST"])
def create_hearing():
    require("Clerk")
    b = body_json()
    body = b.get("body")
    scheduled = parse_dt(b.get("scheduled_date"))
    capacity = b.get("agenda_capacity")
    if body not in HEARING_BODIES:
        raise ApiError("ERR_INVALID_REQUEST")
    if scheduled is None:
        raise ApiError("ERR_INVALID_REQUEST")
    if not is_int(capacity) or capacity < 1:
        raise ApiError("ERR_INVALID_REQUEST")
    # calendar buffer vs same-body non-cancelled hearings
    for h in DB["hearings"].values():
        if h["body"] == body and h["status"] != "CANCELLED":
            gap = int(abs((scheduled - h["scheduled_date"]).total_seconds()) // 86400)
            if gap < BODY_MIN_GAP_DAYS:
                raise ApiError("ERR_HEARING_CALENDAR_CONFLICT")
    obj = new_full({
        "body": body,
        "scheduled_date": scheduled,
        "agenda_capacity": capacity,
        "agenda_slots_remaining": capacity,
        "status": "SCHEDULED",
    })
    DB["hearings"][obj["id"]] = obj
    return ok_obj(obj, 201)


@app.route("/hearings/<hid>", methods=["GET"])
def get_hearing(hid):
    require(*ALL_ROLES)
    return ok_obj(get_or_404("hearings", hid, "ERR_HEARING_NOT_FOUND"))


def _hearing_item_count(hearing_id):
    return sum(1 for i in DB["agenda_items"].values()
               if i["hearing_id"] == hearing_id)


@app.route("/hearings/<hid>/agenda-items", methods=["POST"])
def place_agenda_item(hid):
    require("Clerk")
    hearing = get_or_404("hearings", hid, "ERR_HEARING_NOT_FOUND")
    b = body_json()
    application_id = b.get("application_id")
    expected_version = b.get("expected_hearing_version")
    # existence: application (body) after hearing (path)
    if application_id is None:
        raise ApiError("ERR_INVALID_REQUEST")
    app_o = get_or_404("applications", application_id, "ERR_APPLICATION_NOT_FOUND")

    # state: application ACCEPTED
    if app_o["status"] != "ACCEPTED":
        raise ApiError("ERR_APPLICATION_NOT_ACCEPTED")
    # state: hearing SCHEDULED
    if hearing["status"] != "SCHEDULED":
        raise ApiError("ERR_HEARING_NOT_OPEN")
    # state: free slot
    if hearing["agenda_slots_remaining"] <= 0:
        raise ApiError("ERR_AGENDA_FULL")
    # OCC
    if not is_int(expected_version):
        raise ApiError("ERR_INVALID_REQUEST")
    if expected_version != hearing["version"]:
        raise ApiError("ERR_STALE_HEARING_VERSION")
    # notice present
    sent_notices = [n for n in DB["notices"].values()
                    if n["application_id"] == application_id and n["status"] == "SENT"]
    if not sent_notices:
        raise ApiError("ERR_NOTICE_MISSING")
    # notice period: use most-recently-mailed SENT notice
    notice = max(sent_notices, key=lambda n: (n["mailed_at"], n["_seq"]))
    span = whole_days(hearing["scheduled_date"], notice["mailed_at"])
    if span < NOTICE_MIN_DAYS[hearing["body"]]:
        raise ApiError("ERR_NOTICE_PERIOD_NOT_MET")

    item = _create_agenda_item(hearing, application_id)
    app_o["status"] = "SCHEDULED"
    touch(app_o)
    return ok_obj(item, 201)


def _create_agenda_item(hearing, application_id):
    position = _hearing_item_count(hearing["id"]) + 1
    item = new_full({
        "hearing_id": hearing["id"],
        "application_id": application_id,
        "agenda_position": position,
        "decision": None,
        "continued_to_hearing_id": None,
        "status": "PLACED",
    })
    DB["agenda_items"][item["id"]] = item
    hearing["agenda_slots_remaining"] -= 1
    touch(hearing)
    return item


@app.route("/hearings/<hid>/agenda-items", methods=["GET"])
def list_hearing_agenda_items(hid):
    require(*ALL_ROLES)
    get_or_404("hearings", hid, "ERR_HEARING_NOT_FOUND")
    items = [i for i in DB["agenda_items"].values() if i["hearing_id"] == hid]
    return paginate_and_respond(sorted_by_created(items))


@app.route("/hearings/<hid>/cancel", methods=["POST"])
def cancel_hearing(hid):
    require("Clerk")
    hearing = get_or_404("hearings", hid, "ERR_HEARING_NOT_FOUND")
    if hearing["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE")
    for i in DB["agenda_items"].values():
        if i["hearing_id"] == hid and i["status"] == "PLACED":
            raise ApiError("ERR_AGENDA_NOT_EMPTY")
    hearing["status"] = "CANCELLED"
    touch(hearing)
    return ok_obj(hearing, 200)


# ===========================================================================
# Agenda item decision
# ===========================================================================
@app.route("/agenda-items/<iid>", methods=["GET"])
def get_agenda_item(iid):
    require(*ALL_ROLES)
    return ok_obj(get_or_404("agenda_items", iid, "ERR_AGENDA_ITEM_NOT_FOUND"))


@app.route("/agenda-items/<iid>/decide", methods=["POST"])
def decide_agenda_item(iid):
    require("Commissioner")
    item = get_or_404("agenda_items", iid, "ERR_AGENDA_ITEM_NOT_FOUND")
    app_o = DB["applications"].get(item["application_id"])
    if app_o is None:
        raise ApiError("ERR_APPLICATION_NOT_FOUND")
    # state
    if item["status"] != "PLACED" or app_o["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE")
    # segregation of duties
    if g.user_id == app_o["assigned_planner_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    b = body_json()
    decision = b.get("decision")
    if decision not in ("APPROVE", "DENY", "CONTINUE"):
        raise ApiError("ERR_INVALID_REQUEST")

    findings_in = b.get("findings") or []
    conditions_in = b.get("conditions") or []
    t = now()

    if decision == "APPROVE":
        if not isinstance(findings_in, list) or not any(
                isinstance(f, dict) and f.get("supports_approval") is True
                for f in findings_in):
            raise ApiError("ERR_FINDINGS_REQUIRED")
        item["decision"] = "APPROVED"
        item["status"] = "APPROVED"
        touch(item)
        app_o["decision"] = "APPROVED"
        app_o["decision_at"] = t
        app_o["appeal_deadline"] = t + timedelta(days=APPEAL_WINDOW_DAYS)
        ed = _entitlement_days(app_o)
        app_o["provisional_expiration_date"] = (
            None if ed is None else t + timedelta(days=ed))
        app_o["status"] = "DECIDED_APPROVED"
        touch(app_o)
        _create_conditions(app_o["id"], conditions_in)
        _create_findings(app_o["id"], findings_in)
        return ok_obj(item, 200)

    if decision == "DENY":
        if not isinstance(findings_in, list) or len(findings_in) < 1:
            raise ApiError("ERR_FINDINGS_REQUIRED")
        item["decision"] = "DENIED"
        item["status"] = "DENIED"
        touch(item)
        app_o["decision"] = "DENIED"
        app_o["decision_at"] = t
        app_o["appeal_deadline"] = t + timedelta(days=APPEAL_WINDOW_DAYS)
        app_o["status"] = "DECIDED_DENIED"
        touch(app_o)
        _create_findings(app_o["id"], findings_in)
        return ok_obj(item, 200)

    # CONTINUE
    target_id = b.get("continued_to_hearing_id")
    if target_id is None:
        raise ApiError("ERR_INVALID_REQUEST")
    target = get_or_404("hearings", target_id, "ERR_HEARING_NOT_FOUND")
    if target["status"] != "SCHEDULED" or target["agenda_slots_remaining"] <= 0:
        raise ApiError("ERR_HEARING_NOT_OPEN")
    item["status"] = "CONTINUED"
    item["continued_to_hearing_id"] = target_id
    touch(item)
    _create_agenda_item(target, app_o["id"])
    # application stays SCHEDULED
    return ok_obj(item, 200)


def _create_conditions(app_id, conditions_in):
    if not isinstance(conditions_in, list):
        return
    for c in conditions_in:
        if not isinstance(c, dict):
            continue
        obj = new_full({
            "application_id": app_id,
            "condition_code": c.get("condition_code"),
            "condition_text": c.get("condition_text"),
            "satisfied": False,
            "status": "ACTIVE",
        })
        DB["conditions"][obj["id"]] = obj


def _create_findings(app_id, findings_in):
    if not isinstance(findings_in, list):
        return
    for f in findings_in:
        if not isinstance(f, dict):
            continue
        obj = new_append_only({
            "application_id": app_id,
            "finding_code": f.get("finding_code"),
            "finding_text": f.get("finding_text"),
            "supports_approval": bool(f.get("supports_approval")),
        })
        DB["findings"][obj["id"]] = obj


# ===========================================================================
# Appeal
# ===========================================================================
@app.route("/appeals", methods=["POST"])
def file_appeal():
    require("Applicant", "Clerk")
    b = body_json()
    application_id = b.get("application_id")
    appellant = b.get("appellant_name")
    grounds = b.get("grounds")
    if application_id is not None:
        app_o = get_or_404("applications", application_id, "ERR_APPLICATION_NOT_FOUND")
    else:
        raise ApiError("ERR_INVALID_REQUEST")
    if not isinstance(appellant, str) or not appellant:
        raise ApiError("ERR_INVALID_REQUEST")
    if not isinstance(grounds, str) or not grounds:
        raise ApiError("ERR_INVALID_REQUEST")
    t = now()
    deadline = app_o["appeal_deadline"]
    if deadline is None or t > deadline:
        raise ApiError("ERR_APPEAL_WINDOW_CLOSED")
    obj = new_full({
        "application_id": application_id,
        "appellant_name": appellant,
        "grounds": grounds,
        "filed_at": t,
        "status": "FILED",
    })
    DB["appeals"][obj["id"]] = obj
    return ok_obj(obj, 201)


@app.route("/appeals/<aid>", methods=["GET"])
def get_appeal(aid):
    require(*ALL_ROLES)
    return ok_obj(get_or_404("appeals", aid, "ERR_APPEAL_NOT_FOUND"))


@app.route("/appeals/<aid>/resolve", methods=["POST"])
def resolve_appeal(aid):
    require("Clerk")
    appeal = get_or_404("appeals", aid, "ERR_APPEAL_NOT_FOUND")
    if appeal["status"] != "FILED":
        raise ApiError("ERR_INVALID_STATE")
    b = body_json()
    resolution = b.get("resolution")
    if resolution not in ("UPHELD", "DENIED", "WITHDRAWN"):
        raise ApiError("ERR_INVALID_REQUEST")
    app_o = DB["applications"].get(appeal["application_id"])

    if resolution == "UPHELD":
        if app_o is None or app_o["status"] != "DECIDED_APPROVED":
            raise ApiError("ERR_INVALID_STATE")
        appeal["status"] = "UPHELD"
        touch(appeal)
        app_o["status"] = "DENIED_ON_APPEAL"
        app_o["review_window_closed_at"] = now()
        touch(app_o)
        for c in DB["conditions"].values():
            if c["application_id"] == app_o["id"] and c["status"] == "ACTIVE":
                c["status"] = "VOIDED"
                touch(c)
        parcel = DB["parcels"].get(app_o["parcel_id"])
        if parcel is not None and parcel["status"] in ("UNDER_APPLICATION", "ENTITLED"):
            parcel["status"] = "AVAILABLE"
            touch(parcel)
        return ok_obj(appeal, 200)

    # DENIED / WITHDRAWN — decision stands
    appeal["status"] = resolution
    touch(appeal)
    return ok_obj(appeal, 200)


# ===========================================================================
# Plat / Impact Fee
# ===========================================================================
@app.route("/plats", methods=["POST"])
def submit_plat():
    require("Applicant")
    b = body_json()
    application_id = b.get("application_id")
    fee_schedule_id = b.get("fee_schedule_id")
    declared_lots = b.get("declared_lot_count")
    declared_acres = b.get("declared_gross_acres")
    prior_paid = b.get("prior_paid_fee_cents", 0)

    # existence
    if application_id is None:
        raise ApiError("ERR_INVALID_REQUEST")
    app_o = get_or_404("applications", application_id, "ERR_APPLICATION_NOT_FOUND")
    if fee_schedule_id is None:
        raise ApiError("ERR_INVALID_REQUEST")
    fs = get_or_404("fee_schedules", fee_schedule_id, "ERR_FEE_SCHEDULE_NOT_FOUND")

    # state
    if app_o["application_type"] != "SUBDIVISION" or app_o["status"] != "EFFECTIVE":
        raise ApiError("ERR_APPLICATION_NOT_EFFECTIVE")

    # field validity
    if not is_int(declared_lots) or declared_lots < 1:
        raise ApiError("ERR_INVALID_REQUEST")
    if not is_num(declared_acres) or declared_acres <= 0:
        raise ApiError("ERR_INVALID_REQUEST")
    if not is_int(prior_paid) or prior_paid < 0:
        raise ApiError("ERR_INVALID_REQUEST")

    plat = new_full({
        "application_id": application_id,
        "fee_schedule_id": fee_schedule_id,
        "declared_lot_count": declared_lots,
        "declared_gross_acres": declared_acres,
        "prior_paid_fee_cents": prior_paid,
        "recorded_lot_count": None,
        "recorded_gross_acres": None,
        "status": "PENDING",
    })
    DB["plats"][plat["id"]] = plat

    gross, credit, net = compute_fee(
        fs, declared_lots, declared_acres, app_o["affordable_housing"], prior_paid)
    assessment = new_full({
        "plat_id": plat["id"],
        "provisional_fee_cents": net,
        "final_fee_cents": None,
        "total_fee_cents": net,
        "gross_fee_cents": gross,
        "credit_cents": credit,
        "amount_paid_cents": 0,
        "status": "PROVISIONAL",
    })
    DB["assessments"][assessment["id"]] = assessment
    return ok_obj(plat, 201)


@app.route("/plats", methods=["GET"])
def list_plats():
    require(*ALL_ROLES)
    items = list(DB["plats"].values())
    f_app = request.args.get("application_id")
    f_fs = request.args.get("fee_schedule_id")
    if f_app is not None:
        items = [x for x in items if x["application_id"] == f_app]
    if f_fs is not None:
        items = [x for x in items if x["fee_schedule_id"] == f_fs]
    return paginate_and_respond(sorted_by_created(items))


@app.route("/plats/<pid>", methods=["GET"])
def get_plat(pid):
    require(*ALL_ROLES)
    return ok_obj(get_or_404("plats", pid, "ERR_PLAT_NOT_FOUND"))


def _assessment_for_plat(plat_id):
    for a in DB["assessments"].values():
        if a["plat_id"] == plat_id:
            return a
    return None


@app.route("/plats/<pid>/record", methods=["POST"])
def record_plat(pid):
    require("Clerk")
    plat = get_or_404("plats", pid, "ERR_PLAT_NOT_FOUND")
    if plat["status"] != "PENDING":
        raise ApiError("ERR_INVALID_STATE")
    b = body_json()
    rec_lots = b.get("recorded_lot_count")
    rec_acres = b.get("recorded_gross_acres")
    if not is_int(rec_lots) or rec_lots < 1:
        raise ApiError("ERR_INVALID_REQUEST")
    if not is_num(rec_acres) or rec_acres <= 0:
        raise ApiError("ERR_INVALID_REQUEST")

    app_o = DB["applications"].get(plat["application_id"])
    fs = DB["fee_schedules"].get(plat["fee_schedule_id"])
    assessment = _assessment_for_plat(pid)

    gross, credit, net = compute_fee(
        fs, rec_lots, rec_acres, app_o["affordable_housing"], plat["prior_paid_fee_cents"])

    plat["recorded_lot_count"] = rec_lots
    plat["recorded_gross_acres"] = rec_acres
    plat["status"] = "RECORDED"
    touch(plat)

    if assessment is not None:
        assessment["final_fee_cents"] = net
        assessment["total_fee_cents"] = net
        assessment["gross_fee_cents"] = gross
        assessment["credit_cents"] = credit
        assessment["status"] = "ASSESSED"
        touch(assessment)

    parcel = DB["parcels"].get(app_o["parcel_id"])
    if parcel is not None:
        parcel["assessed_fee_cents"] += net
        if parcel["status"] == "ENTITLED":
            parcel["status"] = "SUBDIVIDED"
        touch(parcel)

    if app_o["status"] == "EFFECTIVE":
        app_o["status"] = "RECORDED"
        app_o["review_window_closed_at"] = now()
        touch(app_o)

    return ok_obj(plat, 200)


@app.route("/plats/<pid>/vacate", methods=["POST"])
def vacate_plat(pid):
    require("Clerk")
    plat = get_or_404("plats", pid, "ERR_PLAT_NOT_FOUND")
    st = plat["status"]
    assessment = _assessment_for_plat(pid)

    if st == "RECORDED":
        plat["status"] = "VACATED"
        touch(plat)
        app_o = DB["applications"].get(plat["application_id"])
        parcel = DB["parcels"].get(app_o["parcel_id"]) if app_o else None
        if assessment is not None:
            if parcel is not None:
                parcel["assessed_fee_cents"] -= assessment["total_fee_cents"]
            assessment["status"] = "VOIDED"
            touch(assessment)
        if parcel is not None and parcel["status"] == "SUBDIVIDED":
            parcel["status"] = "ENTITLED"
            touch(parcel)
        if app_o is not None and app_o["status"] == "RECORDED":
            app_o["status"] = "EFFECTIVE"
            app_o["review_window_closed_at"] = None
            touch(app_o)
        return ok_obj(plat, 200)

    if st == "PENDING":
        plat["status"] = "REJECTED"
        touch(plat)
        if assessment is not None and assessment["status"] == "PROVISIONAL":
            assessment["status"] = "VOIDED"
            touch(assessment)
        return ok_obj(plat, 200)

    raise ApiError("ERR_INVALID_STATE")


@app.route("/plats/<pid>/impact-fee", methods=["GET"])
def list_plat_impact_fee(pid):
    require(*ALL_ROLES)
    get_or_404("plats", pid, "ERR_PLAT_NOT_FOUND")
    items = [a for a in DB["assessments"].values() if a["plat_id"] == pid]
    return paginate_and_respond(sorted_by_created(items))


@app.route("/impact-fees/<fid>", methods=["GET"])
def get_impact_fee(fid):
    require(*ALL_ROLES)
    return ok_obj(get_or_404("assessments", fid, "ERR_FEE_NOT_FOUND"))


@app.route("/impact-fees/<fid>/pay", methods=["POST"])
def pay_impact_fee(fid):
    require("Applicant")
    assessment = get_or_404("assessments", fid, "ERR_FEE_NOT_FOUND")
    # ownership: paying applicant owns the plat's application
    plat = DB["plats"].get(assessment["plat_id"])
    app_o = DB["applications"].get(plat["application_id"]) if plat else None
    if app_o is None or app_o["applicant_id"] != g.user_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")
    # state
    if assessment["status"] != "ASSESSED":
        raise ApiError("ERR_FEE_NOT_ASSESSED")
    b = body_json()
    amount = b.get("amount_cents")
    if not is_int(amount):
        raise ApiError("ERR_INVALID_REQUEST")
    if amount != assessment["total_fee_cents"]:
        raise ApiError("ERR_FEE_AMOUNT_MISMATCH")
    assessment["status"] = "PAID"
    assessment["amount_paid_cents"] = assessment["total_fee_cents"]
    touch(assessment)
    return ok_obj(assessment, 200)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
