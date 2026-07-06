"""
Eminent Domain & Right-of-Way Acquisition API — Flask reference implementation.

In-memory only. State starts empty on every boot (per-test-server isolation).
No seeding / preloading of any entity data.
"""
import os
import random
import string
import uuid
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP

from flask import Flask, request, jsonify, g

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
ROLES = {
    "ProgramAdmin",
    "RightOfWayAgent",
    "Appraiser",
    "PropertyOwner",
    "EscrowOfficer",
    "UtilityCoordinator",
}
ALL_ROLES = list(ROLES)

CLOCK_DEFAULT_RAW = "2026-05-01T00:00:00Z"

CREW_BUFFER_MINUTES = 60
ESCROW_WAITING_PERIOD_DAYS = 3

RESIDENTIAL_REPLACEMENT_CAP_CENTS = 3150000
BUSINESS_REESTABLISHMENT_CAP_CENTS = 5000000

PROMPT_BONUS_TIER_THRESHOLD_CENTS = 25000000
PROMPT_BONUS_LOW_PCT = Decimal("0.03")
PROMPT_BONUS_HIGH_PCT = Decimal("0.05")
PROMPT_BONUS_MAX_ROUND = 2

STATUTORY_DAILY_INTEREST_RATE = Decimal("0.0001")

PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100


# ---------------------------------------------------------------------------
# In-memory store
# ---------------------------------------------------------------------------
class Store:
    def __init__(self):
        self.reset()

    def reset(self):
        self.projects = {}
        self.parcels = {}
        self.ownership_interests = {}
        self.appraisals = {}
        self.inspection_appointments = {}
        self.negotiations = {}
        self.offer_rounds = {}
        self.relocation_benefits = {}
        self.condemnations = {}
        self.utility_relocations = {}
        self.escrows = {}
        self._seq = 0
        self.clock_raw = CLOCK_DEFAULT_RAW
        self.clock_dt = parse_dt(CLOCK_DEFAULT_RAW)

    def next_seq(self):
        self._seq += 1
        return self._seq


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# ---------------------------------------------------------------------------
# Datetime helpers
# ---------------------------------------------------------------------------
def parse_dt(s):
    if not isinstance(s, str):
        raise ValueError("not a string")
    t = s.strip()
    if t.endswith("Z") or t.endswith("z"):
        t = t[:-1] + "+00:00"
    dt = datetime.fromisoformat(t)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt_dt(dt):
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def now_wall():
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Rounding
# ---------------------------------------------------------------------------
def round_half_up(value):
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Response envelope
# ---------------------------------------------------------------------------
def _request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def _meta(extra=None):
    m = {
        "api_request_id": _request_id(),
        "api_request_timestamp": fmt_dt(now_wall()),
    }
    if extra:
        m.update(extra)
    return m


def ok(data, code=200, response_type="object", meta_extra=None):
    body = {
        "meta": _meta(meta_extra),
        "response_type": response_type,
        "data": data,
    }
    return jsonify(body), code


def ok_list(items, limit, offset, total_count):
    has_more = (offset + len(items)) < total_count
    meta_extra = {
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": has_more,
    }
    return ok(items, code=200, response_type="array", meta_extra=meta_extra)


def error_response(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


# ---------------------------------------------------------------------------
# Auth / RBAC
# ---------------------------------------------------------------------------
def authenticate():
    role = request.headers.get("X-User-Role")
    if not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", 401, "Missing or unrecognized X-User-Role")
    g.role = role
    g.user_id = request.headers.get("X-User-ID")
    return role


def authorize(allowed):
    if g.role not in allowed:
        raise ApiError("ERR_FORBIDDEN", 403, "Role not permitted for this operation")


def body_json():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ApiError("ERR_VALIDATION", 400, "Request body must be a JSON object")
    return data


# ---------------------------------------------------------------------------
# Existence helpers
# ---------------------------------------------------------------------------
def get_or_404(coll, rid):
    obj = coll.get(rid)
    if obj is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Resource not found")
    return obj


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------
def require_present(body, field):
    if field not in body or body[field] is None:
        raise ApiError("ERR_VALIDATION", 400, f"Missing required field: {field}")
    return body[field]


def as_int(value, field):
    if isinstance(value, bool) or not isinstance(value, int):
        raise ApiError("ERR_VALIDATION", 400, f"Field {field} must be an integer")
    return value


def require_int(body, field, min_value=None, max_value=None):
    v = require_present(body, field)
    v = as_int(v, field)
    if min_value is not None and v < min_value:
        raise ApiError("ERR_VALIDATION", 400, f"Field {field} below minimum")
    if max_value is not None and v > max_value:
        raise ApiError("ERR_VALIDATION", 400, f"Field {field} above maximum")
    return v


def optional_int(body, field, default=0, min_value=None, max_value=None):
    if field not in body or body[field] is None:
        return default
    v = as_int(body[field], field)
    if min_value is not None and v < min_value:
        raise ApiError("ERR_VALIDATION", 400, f"Field {field} below minimum")
    if max_value is not None and v > max_value:
        raise ApiError("ERR_VALIDATION", 400, f"Field {field} above maximum")
    return v


def require_enum(body, field, allowed):
    v = require_present(body, field)
    if v not in allowed:
        raise ApiError("ERR_VALIDATION", 400, f"Invalid value for {field}")
    return v


def require_str(body, field):
    v = require_present(body, field)
    if not isinstance(v, str) or v == "":
        raise ApiError("ERR_VALIDATION", 400, f"Field {field} must be a non-empty string")
    return v


def pagination_params():
    args = request.args
    limit = PAGINATION_DEFAULT_LIMIT
    offset = 0
    if "limit" in args:
        try:
            limit = int(args["limit"])
        except (ValueError, TypeError):
            raise ApiError("ERR_PAGINATION_INVALID", 400, "Invalid limit")
    if "offset" in args:
        try:
            offset = int(args["offset"])
        except (ValueError, TypeError):
            raise ApiError("ERR_PAGINATION_INVALID", 400, "Invalid offset")
    if limit < PAGINATION_MIN_LIMIT or limit > PAGINATION_MAX_LIMIT:
        raise ApiError("ERR_PAGINATION_INVALID", 400, "limit out of range")
    if offset < 0:
        raise ApiError("ERR_PAGINATION_INVALID", 400, "offset out of range")
    return limit, offset


def paginate(items, limit, offset):
    total = len(items)
    page = items[offset:offset + limit]
    return page, total


# ---------------------------------------------------------------------------
# Entity base / touch
# ---------------------------------------------------------------------------
def new_entity(with_common=True):
    ent = {
        "id": str(uuid.uuid4()),
        "_seq": store.next_seq(),
    }
    ts = fmt_dt(now_wall())
    ent["created_at"] = ts
    if with_common:
        ent["updated_at"] = ts
        ent["version"] = 1
    return ent


def touch(ent):
    ent["updated_at"] = fmt_dt(now_wall())
    ent["version"] = ent.get("version", 1) + 1


def sort_seq(items):
    return sorted(items, key=lambda e: e["_seq"])


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------
def project_ledger(project):
    committed = 0
    acquired_area = 0
    for p in store.parcels.values():
        if p["project_id"] != project["id"]:
            continue
        if p["acquisition_status"] in ("IN_NEGOTIATION", "AGREED", "IN_CONDEMNATION", "POSSESSED"):
            committed += p["appraised_value_cents"]
        if p["acquisition_status"] == "ACQUIRED":
            acquired_area += p["take_area_sqft"]
    disbursed = 0
    for e in store.escrows.values():
        parcel = store.parcels.get(e["parcel_id"])
        if not parcel or parcel["project_id"] != project["id"]:
            continue
        if e["status"] == "CLOSED":
            disbursed += e["agreed_amount_cents"]
    available = project["total_budget_cents"] - committed - disbursed
    return committed, disbursed, acquired_area, available


def ser_project(p):
    committed, disbursed, acquired_area, available = project_ledger(p)
    return {
        "id": p["id"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
        "name": p["name"],
        "agency_name": p["agency_name"],
        "total_budget_cents": p["total_budget_cents"],
        "committed_cents": committed,
        "disbursed_cents": disbursed,
        "acquired_area_sqft": acquired_area,
        "available_cents": available,
    }


def ser_parcel(p):
    return {
        "id": p["id"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
        "project_id": p["project_id"],
        "apn": p["apn"],
        "total_area_sqft": p["total_area_sqft"],
        "take_area_sqft": p["take_area_sqft"],
        "take_type": p["take_type"],
        "research_status": p["research_status"],
        "acquisition_status": p["acquisition_status"],
        "appraised_value_cents": p["appraised_value_cents"],
    }


def ser_ownership(o):
    return {
        "id": o["id"],
        "created_at": o["created_at"],
        "updated_at": o["updated_at"],
        "version": o["version"],
        "parcel_id": o["parcel_id"],
        "interest_type": o["interest_type"],
        "holder_name": o["holder_name"],
        "ownership_pct": o["ownership_pct"],
        "lien_priority": o["lien_priority"],
        "lien_balance_cents": o["lien_balance_cents"],
        "is_occupant": o["is_occupant"],
    }


def ser_appraisal(a):
    return {
        "id": a["id"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
        "parcel_id": a["parcel_id"],
        "appraiser_name": a["appraiser_name"],
        "land_value_cents": a["land_value_cents"],
        "improvements_value_cents": a["improvements_value_cents"],
        "severance_damages_cents": a["severance_damages_cents"],
        "special_benefits_cents": a["special_benefits_cents"],
        "just_compensation_cents": a["just_compensation_cents"],
        "condemnation_basis_cents": a["condemnation_basis_cents"],
        "status": a["status"],
    }


def ser_inspection(i):
    return {
        "id": i["id"],
        "created_at": i["created_at"],
        "updated_at": i["updated_at"],
        "version": i["version"],
        "appraisal_id": i["appraisal_id"],
        "appraiser_name": i["appraiser_name"],
        "start_at": i["start_at"],
        "end_at": i["end_at"],
        "status": i["status"],
    }


def negotiation_rounds(neg_id):
    return sort_seq([r for r in store.offer_rounds.values() if r["negotiation_id"] == neg_id])


def negotiation_current_amount(neg_id):
    amt = 0
    for r in negotiation_rounds(neg_id):
        if r["action"] in ("OFFER", "COUNTER"):
            amt = r["amount_cents"]
    return amt


def ser_negotiation(n):
    rounds = negotiation_rounds(n["id"])
    return {
        "id": n["id"],
        "created_at": n["created_at"],
        "updated_at": n["updated_at"],
        "version": n["version"],
        "parcel_id": n["parcel_id"],
        "status": n["status"],
        "initial_offer_cents": n["initial_offer_cents"],
        "current_amount_cents": negotiation_current_amount(n["id"]),
        "round_count": len(rounds),
        "agreed_amount_cents": n["agreed_amount_cents"],
        "prompt_bonus_cents": n["prompt_bonus_cents"],
        "settlement_total_cents": n["settlement_total_cents"],
    }


def ser_round(r):
    return {
        "id": r["id"],
        "created_at": r["created_at"],
        "negotiation_id": r["negotiation_id"],
        "round_no": r["round_no"],
        "party": r["party"],
        "action": r["action"],
        "amount_cents": r["amount_cents"],
    }


def ser_relocation(b):
    return {
        "id": b["id"],
        "created_at": b["created_at"],
        "updated_at": b["updated_at"],
        "version": b["version"],
        "parcel_id": b["parcel_id"],
        "claimant_name": b["claimant_name"],
        "occupant_type": b["occupant_type"],
        "comparable_replacement_cost_cents": b["comparable_replacement_cost_cents"],
        "acquired_dwelling_price_cents": b["acquired_dwelling_price_cents"],
        "moving_expense_cents": b["moving_expense_cents"],
        "reestablishment_cost_cents": b["reestablishment_cost_cents"],
        "benefit_amount_cents": b["benefit_amount_cents"],
        "status": b["status"],
    }


def ser_condemnation(c):
    return {
        "id": c["id"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
        "parcel_id": c["parcel_id"],
        "just_compensation_snapshot_cents": c["just_compensation_snapshot_cents"],
        "deposit_amount_cents": c["deposit_amount_cents"],
        "deposit_at": c["deposit_at"],
        "possession_at": c["possession_at"],
        "final_award_cents": c["final_award_cents"],
        "statutory_interest_cents": c["statutory_interest_cents"],
        "settlement_total_cents": c["settlement_total_cents"],
        "status": c["status"],
    }


def ser_utility(u):
    return {
        "id": u["id"],
        "created_at": u["created_at"],
        "updated_at": u["updated_at"],
        "version": u["version"],
        "parcel_id": u["parcel_id"],
        "utility_type": u["utility_type"],
        "crew_name": u["crew_name"],
        "scheduled_start": u["scheduled_start"],
        "scheduled_end": u["scheduled_end"],
        "possession_cleared": u["possession_cleared"],
        "status": u["status"],
    }


def ser_escrow(e):
    return {
        "id": e["id"],
        "created_at": e["created_at"],
        "updated_at": e["updated_at"],
        "version": e["version"],
        "parcel_id": e["parcel_id"],
        "source": e["source"],
        "agreed_amount_cents": e["agreed_amount_cents"],
        "funded_amount_cents": e["funded_amount_cents"],
        "funded_at": e["funded_at"],
        "disbursed_total_cents": e["disbursed_total_cents"],
        "disbursements": e["disbursements"],
        "status": e["status"],
    }


# ---------------------------------------------------------------------------
# Domain helpers
# ---------------------------------------------------------------------------
def fee_owner_pct_sum(parcel_id):
    total = Decimal(0)
    for o in store.ownership_interests.values():
        if o["parcel_id"] == parcel_id and o["interest_type"] == "FEE_OWNER":
            total += Decimal(str(o["ownership_pct"]))
    return total


def finalized_appraisal(parcel_id):
    for a in store.appraisals.values():
        if a["parcel_id"] == parcel_id and a["status"] == "FINALIZED":
            return a
    return None


def acting_ownership_interest(parcel_id):
    """Return the OwnershipInterest identified by X-User-ID iff it belongs to parcel_id."""
    oi = store.ownership_interests.get(g.user_id)
    if oi is None or oi["parcel_id"] != parcel_id:
        return None
    return oi


# ---------------------------------------------------------------------------
# Clock endpoint
# ---------------------------------------------------------------------------
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    authenticate()
    authorize(["ProgramAdmin"])
    body = body_json()
    raw = require_present(body, "to_iso8601")
    try:
        dt = parse_dt(raw)
    except (ValueError, TypeError):
        raise ApiError("ERR_VALIDATION", 400, "Invalid to_iso8601")
    store.clock_raw = raw
    store.clock_dt = dt
    return ok({"current_utc": raw})


# ---------------------------------------------------------------------------
# Projects
# ---------------------------------------------------------------------------
@app.route("/projects", methods=["POST"])
def create_project():
    authenticate()
    authorize(["ProgramAdmin"])
    body = body_json()
    name = require_str(body, "name")
    agency_name = require_str(body, "agency_name")
    total_budget = require_int(body, "total_budget_cents", min_value=0)
    p = new_entity()
    p.update({
        "name": name,
        "agency_name": agency_name,
        "total_budget_cents": total_budget,
    })
    store.projects[p["id"]] = p
    return ok(ser_project(p), code=201)


@app.route("/projects/<pid>", methods=["GET"])
def get_project(pid):
    authenticate()
    authorize(ALL_ROLES)
    p = get_or_404(store.projects, pid)
    return ok(ser_project(p))


@app.route("/projects/<pid>/parcels", methods=["GET"])
def list_project_parcels(pid):
    authenticate()
    authorize(ALL_ROLES)
    get_or_404(store.projects, pid)
    limit, offset = pagination_params()
    items = sort_seq([p for p in store.parcels.values() if p["project_id"] == pid])
    page, total = paginate(items, limit, offset)
    return ok_list([ser_parcel(x) for x in page], limit, offset, total)


# ---------------------------------------------------------------------------
# Parcels
# ---------------------------------------------------------------------------
@app.route("/parcels", methods=["POST"])
def create_parcel():
    authenticate()
    authorize(["RightOfWayAgent"])
    body = body_json()
    project_id = require_str(body, "project_id")
    apn = require_str(body, "apn")
    total_area = require_int(body, "total_area_sqft")
    take_area = require_int(body, "take_area_sqft")
    take_type = require_enum(body, "take_type", ("FULL", "PARTIAL"))
    if total_area <= 0:
        raise ApiError("ERR_VALIDATION", 400, "total_area_sqft must be > 0")
    if take_area <= 0:
        raise ApiError("ERR_VALIDATION", 400, "take_area_sqft must be > 0")
    if take_area > total_area:
        raise ApiError("ERR_VALIDATION", 400, "take_area_sqft must be <= total_area_sqft")
    if project_id not in store.projects:
        raise ApiError("ERR_NOT_FOUND", 404, "project_id does not exist")
    # apn unique within project
    for p in store.parcels.values():
        if p["project_id"] == project_id and p["apn"] == apn:
            raise ApiError("ERR_VALIDATION", 400, "apn must be unique within the project")
    parcel = new_entity()
    parcel.update({
        "project_id": project_id,
        "apn": apn,
        "total_area_sqft": total_area,
        "take_area_sqft": take_area,
        "take_type": take_type,
        "research_status": "RESEARCHING",
        "acquisition_status": "PENDING",
        "appraised_value_cents": 0,
    })
    store.parcels[parcel["id"]] = parcel
    return ok(ser_parcel(parcel), code=201)


@app.route("/parcels/<pid>", methods=["GET"])
def get_parcel(pid):
    authenticate()
    authorize(ALL_ROLES)
    p = get_or_404(store.parcels, pid)
    return ok(ser_parcel(p))


@app.route("/parcels/<pid>/clear-ownership", methods=["POST"])
def clear_ownership(pid):
    authenticate()
    authorize(["RightOfWayAgent"])
    parcel = get_or_404(store.parcels, pid)
    # state
    if parcel["research_status"] != "RESEARCHING":
        raise ApiError("ERR_INVALID_PARCEL_STATE", 409, "Parcel research not in RESEARCHING")
    # ownership completeness
    if fee_owner_pct_sum(pid) != Decimal(100):
        raise ApiError("ERR_OWNERSHIP_INCOMPLETE", 422, "FEE_OWNER ownership_pct must sum to 100")
    parcel["research_status"] = "OWNERSHIP_CLEARED"
    touch(parcel)
    return ok(ser_parcel(parcel))


# ---------------------------------------------------------------------------
# Ownership Interests
# ---------------------------------------------------------------------------
@app.route("/parcels/<pid>/ownership-interests", methods=["POST"])
def create_ownership(pid):
    authenticate()
    authorize(["RightOfWayAgent"])
    parcel = get_or_404(store.parcels, pid)
    body = body_json()
    interest_type = require_enum(body, "interest_type",
                                 ("FEE_OWNER", "LIENHOLDER", "TENANT", "EASEMENT_HOLDER"))
    holder_name = require_str(body, "holder_name")
    ownership_pct = body.get("ownership_pct", 0)
    if ownership_pct is None:
        ownership_pct = 0
    if isinstance(ownership_pct, bool) or not isinstance(ownership_pct, (int, float)):
        raise ApiError("ERR_VALIDATION", 400, "ownership_pct must be a number")
    if ownership_pct < 0 or ownership_pct > 100:
        raise ApiError("ERR_VALIDATION", 400, "ownership_pct must be within [0, 100]")
    lien_priority = optional_int(body, "lien_priority", default=0)
    lien_balance = optional_int(body, "lien_balance_cents", default=0)
    is_occupant = body.get("is_occupant", False)
    if is_occupant is None:
        is_occupant = False
    if not isinstance(is_occupant, bool):
        raise ApiError("ERR_VALIDATION", 400, "is_occupant must be a boolean")
    o = new_entity()
    o.update({
        "parcel_id": pid,
        "interest_type": interest_type,
        "holder_name": holder_name,
        "ownership_pct": ownership_pct,
        "lien_priority": lien_priority,
        "lien_balance_cents": lien_balance,
        "is_occupant": is_occupant,
    })
    store.ownership_interests[o["id"]] = o
    return ok(ser_ownership(o), code=201)


@app.route("/parcels/<pid>/ownership-interests", methods=["GET"])
def list_ownership(pid):
    authenticate()
    authorize(ALL_ROLES)
    get_or_404(store.parcels, pid)
    limit, offset = pagination_params()
    items = sort_seq([o for o in store.ownership_interests.values() if o["parcel_id"] == pid])
    page, total = paginate(items, limit, offset)
    return ok_list([ser_ownership(x) for x in page], limit, offset, total)


# ---------------------------------------------------------------------------
# Appraisals
# ---------------------------------------------------------------------------
def compute_appraisal_bases(land, improvements, severance, special):
    just_comp = land + improvements + max(0, severance - special)
    condemnation_basis = land + improvements + severance
    return just_comp, condemnation_basis


@app.route("/parcels/<pid>/appraisals", methods=["POST"])
def create_appraisal(pid):
    authenticate()
    authorize(["Appraiser"])
    parcel = get_or_404(store.parcels, pid)
    body = body_json()
    appraiser_name = require_str(body, "appraiser_name")
    land = require_int(body, "land_value_cents", min_value=0)
    improvements = require_int(body, "improvements_value_cents", min_value=0)
    severance = optional_int(body, "severance_damages_cents", default=0, min_value=0)
    special = optional_int(body, "special_benefits_cents", default=0, min_value=0)
    expected_version = require_int(body, "expected_parcel_version")
    # OCC
    if expected_version != parcel["version"]:
        raise ApiError("ERR_STALE_VERSION", 412, "expected_parcel_version does not match parcel")
    just_comp, condemnation_basis = compute_appraisal_bases(land, improvements, severance, special)
    # supersede any prior DRAFT appraisal for this parcel
    for a in store.appraisals.values():
        if a["parcel_id"] == pid and a["status"] == "DRAFT":
            a["status"] = "SUPERSEDED"
            touch(a)
    appraisal = new_entity()
    appraisal.update({
        "parcel_id": pid,
        "appraiser_name": appraiser_name,
        "land_value_cents": land,
        "improvements_value_cents": improvements,
        "severance_damages_cents": severance,
        "special_benefits_cents": special,
        "just_compensation_cents": just_comp,
        "condemnation_basis_cents": condemnation_basis,
        "status": "DRAFT",
    })
    store.appraisals[appraisal["id"]] = appraisal
    # appraisal creation increments parcel version
    touch(parcel)
    return ok(ser_appraisal(appraisal), code=201)


@app.route("/appraisals/<aid>", methods=["GET"])
def get_appraisal(aid):
    authenticate()
    authorize(ALL_ROLES)
    a = get_or_404(store.appraisals, aid)
    return ok(ser_appraisal(a))


@app.route("/parcels/<pid>/appraisals", methods=["GET"])
def list_appraisals(pid):
    authenticate()
    authorize(ALL_ROLES)
    get_or_404(store.parcels, pid)
    limit, offset = pagination_params()
    items = sort_seq([a for a in store.appraisals.values() if a["parcel_id"] == pid])
    page, total = paginate(items, limit, offset)
    return ok_list([ser_appraisal(x) for x in page], limit, offset, total)


@app.route("/appraisals/<aid>/finalize", methods=["POST"])
def finalize_appraisal(aid):
    authenticate()
    authorize(["Appraiser"])
    appraisal = get_or_404(store.appraisals, aid)
    if appraisal["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_APPRAISAL_STATE", 409, "Appraisal not in DRAFT")
    parcel = store.parcels.get(appraisal["parcel_id"])
    # supersede any other FINALIZED appraisal for the same parcel
    for a in store.appraisals.values():
        if a["id"] != appraisal["id"] and a["parcel_id"] == appraisal["parcel_id"] and a["status"] == "FINALIZED":
            a["status"] = "SUPERSEDED"
            touch(a)
    appraisal["status"] = "FINALIZED"
    touch(appraisal)
    if parcel is not None:
        parcel["appraised_value_cents"] = appraisal["just_compensation_cents"]
        touch(parcel)
    return ok(ser_appraisal(appraisal))


# ---------------------------------------------------------------------------
# Inspection Appointments
# ---------------------------------------------------------------------------
def windows_overlap(s1, e1, s2, e2):
    # half-open [s,e); overlap iff s1 < e2 and s2 < e1
    return s1 < e2 and s2 < e1


@app.route("/appraisals/<aid>/inspection-appointments", methods=["POST"])
def create_inspection(aid):
    authenticate()
    authorize(["Appraiser"])
    appraisal = get_or_404(store.appraisals, aid)
    body = body_json()
    appraiser_name = require_str(body, "appraiser_name")
    start_raw = require_present(body, "start_at")
    end_raw = require_present(body, "end_at")
    try:
        start_dt = parse_dt(start_raw)
        end_dt = parse_dt(end_raw)
    except (ValueError, TypeError):
        raise ApiError("ERR_VALIDATION", 400, "Invalid start_at/end_at")
    if end_dt <= start_dt:
        raise ApiError("ERR_VALIDATION", 400, "end_at must be after start_at")
    # overlap check against existing SCHEDULED appointments for same appraiser_name
    for other in store.inspection_appointments.values():
        if other["appraiser_name"] != appraiser_name or other["status"] != "SCHEDULED":
            continue
        os_ = parse_dt(other["start_at"])
        oe = parse_dt(other["end_at"])
        if windows_overlap(start_dt, end_dt, os_, oe):
            raise ApiError("ERR_APPRAISER_DOUBLE_BOOKED", 409, "Appraiser window overlaps existing")
    appt = new_entity()
    appt.update({
        "appraisal_id": aid,
        "appraiser_name": appraiser_name,
        "start_at": fmt_dt(start_dt),
        "end_at": fmt_dt(end_dt),
        "status": "SCHEDULED",
    })
    store.inspection_appointments[appt["id"]] = appt
    return ok(ser_inspection(appt), code=201)


@app.route("/appraisals/<aid>/inspection-appointments", methods=["GET"])
def list_inspections(aid):
    authenticate()
    authorize(ALL_ROLES)
    get_or_404(store.appraisals, aid)
    limit, offset = pagination_params()
    items = sort_seq([i for i in store.inspection_appointments.values() if i["appraisal_id"] == aid])
    page, total = paginate(items, limit, offset)
    return ok_list([ser_inspection(x) for x in page], limit, offset, total)


# ---------------------------------------------------------------------------
# Negotiations
# ---------------------------------------------------------------------------
@app.route("/parcels/<pid>/negotiations", methods=["POST"])
def open_negotiation(pid):
    authenticate()
    authorize(["RightOfWayAgent"])
    parcel = get_or_404(store.parcels, pid)
    body = body_json()
    initial_offer = require_int(body, "initial_offer_cents", min_value=0)
    # state: parcel acquisition must be PENDING
    if parcel["acquisition_status"] != "PENDING":
        raise ApiError("ERR_INVALID_PARCEL_STATE", 409, "Parcel not PENDING")
    # readiness
    if parcel["research_status"] != "OWNERSHIP_CLEARED":
        raise ApiError("ERR_OWNERSHIP_NOT_CLEARED", 422, "Ownership not cleared")
    if finalized_appraisal(pid) is None:
        raise ApiError("ERR_APPRAISAL_NOT_FINALIZED", 422, "No finalized appraisal")
    # fiscal floor
    if initial_offer < parcel["appraised_value_cents"]:
        raise ApiError("ERR_OFFER_BELOW_APPRAISED", 402, "Initial offer below appraised value")
    neg = new_entity()
    neg.update({
        "parcel_id": pid,
        "status": "AGENCY_OFFERED",
        "initial_offer_cents": initial_offer,
        "agreed_amount_cents": 0,
        "prompt_bonus_cents": 0,
        "settlement_total_cents": 0,
    })
    store.negotiations[neg["id"]] = neg
    # seed first offer round
    round1 = new_entity(with_common=False)
    round1.update({
        "negotiation_id": neg["id"],
        "round_no": 1,
        "party": "AGENCY",
        "action": "OFFER",
        "amount_cents": initial_offer,
    })
    store.offer_rounds[round1["id"]] = round1
    # cascade parcel PENDING -> IN_NEGOTIATION
    parcel["acquisition_status"] = "IN_NEGOTIATION"
    touch(parcel)
    return ok(ser_negotiation(neg), code=201)


@app.route("/negotiations/<nid>", methods=["GET"])
def get_negotiation(nid):
    authenticate()
    authorize(ALL_ROLES)
    n = get_or_404(store.negotiations, nid)
    return ok(ser_negotiation(n))


@app.route("/parcels/<pid>/negotiations", methods=["GET"])
def list_negotiations(pid):
    authenticate()
    authorize(ALL_ROLES)
    get_or_404(store.parcels, pid)
    limit, offset = pagination_params()
    items = sort_seq([n for n in store.negotiations.values() if n["parcel_id"] == pid])
    page, total = paginate(items, limit, offset)
    return ok_list([ser_negotiation(x) for x in page], limit, offset, total)


@app.route("/negotiations/<nid>/rounds", methods=["POST"])
def append_round(nid):
    authenticate()
    authorize(["RightOfWayAgent", "PropertyOwner"])
    neg = get_or_404(store.negotiations, nid)
    # resource ownership check for owner party
    if g.role == "PropertyOwner":
        if acting_ownership_interest(neg["parcel_id"]) is None:
            raise ApiError("ERR_NOT_RESOURCE_OWNER", 403, "Not an owner of the target parcel")
    body = body_json()
    action = require_enum(body, "action", ("OFFER", "COUNTER", "ACCEPT", "REJECT"))
    amount = 0
    if action in ("OFFER", "COUNTER"):
        amount = require_int(body, "amount_cents", min_value=0)
    # state: not terminal
    if neg["status"] in ("AGREED", "IMPASSE"):
        raise ApiError("ERR_INVALID_NEGOTIATION_STATE", 409, "Negotiation is terminal")
    party = "OWNER" if g.role == "PropertyOwner" else "AGENCY"
    # turn ordering
    if party == "OWNER" and neg["status"] != "AGENCY_OFFERED":
        raise ApiError("ERR_NOT_YOUR_TURN", 409, "Not the owner's turn")
    if party == "AGENCY" and neg["status"] != "OWNER_COUNTERED":
        raise ApiError("ERR_NOT_YOUR_TURN", 409, "Not the agency's turn")

    round_no = len(negotiation_rounds(nid)) + 1
    rnd = new_entity(with_common=False)
    rnd.update({
        "negotiation_id": nid,
        "round_no": round_no,
        "party": party,
        "action": action,
        "amount_cents": amount,
    })
    store.offer_rounds[rnd["id"]] = rnd

    if action in ("OFFER", "COUNTER"):
        neg["status"] = "OWNER_COUNTERED" if party == "OWNER" else "AGENCY_OFFERED"
        touch(neg)
    elif action == "REJECT":
        neg["status"] = "IMPASSE"
        touch(neg)
    elif action == "ACCEPT":
        agreed = negotiation_current_amount(nid)
        round_count = len(negotiation_rounds(nid))
        neg["agreed_amount_cents"] = agreed
        if round_count > PROMPT_BONUS_MAX_ROUND:
            bonus = 0
        else:
            pct = PROMPT_BONUS_LOW_PCT if agreed <= PROMPT_BONUS_TIER_THRESHOLD_CENTS else PROMPT_BONUS_HIGH_PCT
            bonus = round_half_up(Decimal(agreed) * pct)
        neg["prompt_bonus_cents"] = bonus
        neg["settlement_total_cents"] = agreed + bonus
        neg["status"] = "AGREED"
        touch(neg)
        parcel = store.parcels.get(neg["parcel_id"])
        if parcel is not None and parcel["acquisition_status"] == "IN_NEGOTIATION":
            parcel["acquisition_status"] = "AGREED"
            touch(parcel)

    return ok(ser_round(rnd), code=201)


@app.route("/negotiations/<nid>/rounds", methods=["GET"])
def list_rounds(nid):
    authenticate()
    authorize(ALL_ROLES)
    get_or_404(store.negotiations, nid)
    limit, offset = pagination_params()
    items = negotiation_rounds(nid)
    page, total = paginate(items, limit, offset)
    return ok_list([ser_round(x) for x in page], limit, offset, total)


# ---------------------------------------------------------------------------
# Condemnations
# ---------------------------------------------------------------------------
@app.route("/parcels/<pid>/condemnations", methods=["POST"])
def file_condemnation(pid):
    authenticate()
    authorize(["RightOfWayAgent"])
    parcel = get_or_404(store.parcels, pid)
    # state: parcel must be IN_NEGOTIATION
    if parcel["acquisition_status"] != "IN_NEGOTIATION":
        raise ApiError("ERR_INVALID_PARCEL_STATE", 409, "Parcel not IN_NEGOTIATION")
    # readiness
    if parcel["research_status"] != "OWNERSHIP_CLEARED":
        raise ApiError("ERR_OWNERSHIP_NOT_CLEARED", 422, "Ownership not cleared")
    appr = finalized_appraisal(pid)
    if appr is None:
        raise ApiError("ERR_APPRAISAL_NOT_FINALIZED", 422, "No finalized appraisal")
    # good-faith negotiation: a negotiation with at least one offer round
    attempted = False
    for n in store.negotiations.values():
        if n["parcel_id"] == pid and len(negotiation_rounds(n["id"])) >= 1:
            attempted = True
            break
    if not attempted:
        raise ApiError("ERR_NEGOTIATION_NOT_ATTEMPTED", 422, "No good-faith negotiation attempt")
    cond = new_entity()
    cond.update({
        "parcel_id": pid,
        "just_compensation_snapshot_cents": appr["condemnation_basis_cents"],
        "deposit_amount_cents": 0,
        "deposit_at": None,
        "possession_at": None,
        "final_award_cents": 0,
        "statutory_interest_cents": 0,
        "settlement_total_cents": 0,
        "status": "FILED",
    })
    store.condemnations[cond["id"]] = cond
    parcel["acquisition_status"] = "IN_CONDEMNATION"
    touch(parcel)
    return ok(ser_condemnation(cond), code=201)


@app.route("/condemnations/<cid>", methods=["GET"])
def get_condemnation(cid):
    authenticate()
    authorize(ALL_ROLES)
    c = get_or_404(store.condemnations, cid)
    return ok(ser_condemnation(c))


@app.route("/parcels/<pid>/condemnations", methods=["GET"])
def list_condemnations(pid):
    authenticate()
    authorize(ALL_ROLES)
    get_or_404(store.parcels, pid)
    limit, offset = pagination_params()
    items = sort_seq([c for c in store.condemnations.values() if c["parcel_id"] == pid])
    page, total = paginate(items, limit, offset)
    return ok_list([ser_condemnation(x) for x in page], limit, offset, total)


@app.route("/condemnations/<cid>/deposit", methods=["POST"])
def condemnation_deposit(cid):
    authenticate()
    authorize(["RightOfWayAgent"])
    cond = get_or_404(store.condemnations, cid)
    body = body_json()
    deposit = require_int(body, "deposit_amount_cents", min_value=0)
    if cond["status"] != "FILED":
        raise ApiError("ERR_INVALID_CONDEMNATION_STATE", 409, "Condemnation not FILED")
    if deposit < cond["just_compensation_snapshot_cents"]:
        raise ApiError("ERR_DEPOSIT_BELOW_COMPENSATION", 402, "Deposit below compensation floor")
    cond["deposit_amount_cents"] = deposit
    cond["deposit_at"] = fmt_dt(store.clock_dt)
    cond["status"] = "DEPOSIT_MADE"
    touch(cond)
    return ok(ser_condemnation(cond))


@app.route("/condemnations/<cid>/grant-possession", methods=["POST"])
def grant_possession(cid):
    authenticate()
    authorize(["ProgramAdmin"])
    cond = get_or_404(store.condemnations, cid)
    if cond["status"] != "DEPOSIT_MADE":
        raise ApiError("ERR_INVALID_CONDEMNATION_STATE", 409, "Condemnation not DEPOSIT_MADE")
    cond["possession_at"] = fmt_dt(store.clock_dt)
    cond["status"] = "POSSESSED"
    touch(cond)
    parcel = store.parcels.get(cond["parcel_id"])
    if parcel is not None and parcel["acquisition_status"] == "IN_CONDEMNATION":
        parcel["acquisition_status"] = "POSSESSED"
        touch(parcel)
        # cascade: flip utility relocation possession flags
        for u in store.utility_relocations.values():
            if u["parcel_id"] == parcel["id"] and not u["possession_cleared"]:
                u["possession_cleared"] = True
                touch(u)
    return ok(ser_condemnation(cond))


@app.route("/condemnations/<cid>/award", methods=["POST"])
def condemnation_award(cid):
    authenticate()
    authorize(["ProgramAdmin"])
    cond = get_or_404(store.condemnations, cid)
    body = body_json()
    final_award = require_int(body, "final_award_cents", min_value=0)
    if cond["status"] != "POSSESSED":
        raise ApiError("ERR_INVALID_CONDEMNATION_STATE", 409, "Condemnation not POSSESSED")
    possession_dt = parse_dt(cond["possession_at"])
    seconds = (store.clock_dt - possession_dt).total_seconds()
    days = int(seconds // 86400)
    interest = round_half_up(
        Decimal(final_award - cond["deposit_amount_cents"]) * STATUTORY_DAILY_INTEREST_RATE * Decimal(days)
    )
    cond["final_award_cents"] = final_award
    cond["statutory_interest_cents"] = interest
    cond["settlement_total_cents"] = final_award + interest
    cond["status"] = "AWARDED"
    touch(cond)
    return ok(ser_condemnation(cond))


# ---------------------------------------------------------------------------
# Relocation Benefits
# ---------------------------------------------------------------------------
def compute_relocation_benefit(occupant_type, comparable, acquired_price, moving, reestablishment):
    if occupant_type == "RESIDENTIAL":
        differential = max(0, comparable - acquired_price)
        differential = min(RESIDENTIAL_REPLACEMENT_CAP_CENTS, differential)
        return differential + moving
    else:  # BUSINESS
        component = min(BUSINESS_REESTABLISHMENT_CAP_CENTS, reestablishment)
        return component + moving


@app.route("/parcels/<pid>/relocation-benefits", methods=["POST"])
def submit_relocation(pid):
    authenticate()
    authorize(["PropertyOwner"])
    parcel = get_or_404(store.parcels, pid)
    # resource ownership
    oi = acting_ownership_interest(pid)
    if oi is None:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", 403, "Not an owner of the target parcel")
    body = body_json()
    claimant_name = require_str(body, "claimant_name")
    occupant_type = require_enum(body, "occupant_type", ("RESIDENTIAL", "BUSINESS"))
    comparable = optional_int(body, "comparable_replacement_cost_cents", default=0, min_value=0)
    acquired_price = optional_int(body, "acquired_dwelling_price_cents", default=0, min_value=0)
    moving = optional_int(body, "moving_expense_cents", default=0, min_value=0)
    reestablishment = optional_int(body, "reestablishment_cost_cents", default=0, min_value=0)
    # occupant eligibility
    if not oi["is_occupant"]:
        raise ApiError("ERR_NOT_OCCUPANT", 422, "Claimant is not an occupant")
    benefit = compute_relocation_benefit(occupant_type, comparable, acquired_price, moving, reestablishment)
    b = new_entity()
    b.update({
        "parcel_id": pid,
        "claimant_name": claimant_name,
        "occupant_type": occupant_type,
        "comparable_replacement_cost_cents": comparable,
        "acquired_dwelling_price_cents": acquired_price,
        "moving_expense_cents": moving,
        "reestablishment_cost_cents": reestablishment,
        "benefit_amount_cents": benefit,
        "status": "SUBMITTED",
    })
    store.relocation_benefits[b["id"]] = b
    return ok(ser_relocation(b), code=201)


@app.route("/relocation-benefits/<bid>", methods=["GET"])
def get_relocation(bid):
    authenticate()
    authorize(ALL_ROLES)
    b = get_or_404(store.relocation_benefits, bid)
    return ok(ser_relocation(b))


@app.route("/parcels/<pid>/relocation-benefits", methods=["GET"])
def list_relocations(pid):
    authenticate()
    authorize(ALL_ROLES)
    get_or_404(store.parcels, pid)
    limit, offset = pagination_params()
    items = sort_seq([b for b in store.relocation_benefits.values() if b["parcel_id"] == pid])
    page, total = paginate(items, limit, offset)
    return ok_list([ser_relocation(x) for x in page], limit, offset, total)


@app.route("/relocation-benefits/<bid>/approve", methods=["POST"])
def approve_relocation(bid):
    authenticate()
    authorize(["RightOfWayAgent"])
    b = get_or_404(store.relocation_benefits, bid)
    if b["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_RELOCATION_STATE", 409, "Benefit not SUBMITTED")
    b["status"] = "APPROVED"
    touch(b)
    return ok(ser_relocation(b))


@app.route("/relocation-benefits/<bid>/deny", methods=["POST"])
def deny_relocation(bid):
    authenticate()
    authorize(["RightOfWayAgent"])
    b = get_or_404(store.relocation_benefits, bid)
    body_json()  # reason is optional/ignored beyond acceptance
    if b["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_RELOCATION_STATE", 409, "Benefit not SUBMITTED")
    b["status"] = "DENIED"
    touch(b)
    return ok(ser_relocation(b))


@app.route("/relocation-benefits/<bid>/pay", methods=["POST"])
def pay_relocation(bid):
    authenticate()
    authorize(["EscrowOfficer"])
    b = get_or_404(store.relocation_benefits, bid)
    if b["status"] != "APPROVED":
        raise ApiError("ERR_INVALID_RELOCATION_STATE", 409, "Benefit not APPROVED")
    b["status"] = "PAID"
    touch(b)
    return ok(ser_relocation(b))


# ---------------------------------------------------------------------------
# Utility Relocations
# ---------------------------------------------------------------------------
@app.route("/parcels/<pid>/utility-relocations", methods=["POST"])
def identify_utility(pid):
    authenticate()
    authorize(["UtilityCoordinator"])
    parcel = get_or_404(store.parcels, pid)
    body = body_json()
    utility_type = require_enum(body, "utility_type",
                                ("WATER", "GAS", "ELECTRIC", "TELECOM", "SEWER"))
    possession_cleared = parcel["acquisition_status"] in ("POSSESSED", "ACQUIRED")
    u = new_entity()
    u.update({
        "parcel_id": pid,
        "utility_type": utility_type,
        "crew_name": "",
        "scheduled_start": None,
        "scheduled_end": None,
        "possession_cleared": possession_cleared,
        "status": "IDENTIFIED",
    })
    store.utility_relocations[u["id"]] = u
    return ok(ser_utility(u), code=201)


@app.route("/utility-relocations/<uid>", methods=["GET"])
def get_utility(uid):
    authenticate()
    authorize(ALL_ROLES)
    u = get_or_404(store.utility_relocations, uid)
    return ok(ser_utility(u))


@app.route("/parcels/<pid>/utility-relocations", methods=["GET"])
def list_utilities(pid):
    authenticate()
    authorize(ALL_ROLES)
    get_or_404(store.parcels, pid)
    limit, offset = pagination_params()
    items = sort_seq([u for u in store.utility_relocations.values() if u["parcel_id"] == pid])
    page, total = paginate(items, limit, offset)
    return ok_list([ser_utility(x) for x in page], limit, offset, total)


@app.route("/utility-relocations/<uid>/schedule", methods=["POST"])
def schedule_utility(uid):
    authenticate()
    authorize(["UtilityCoordinator"])
    u = get_or_404(store.utility_relocations, uid)
    body = body_json()
    crew_name = require_str(body, "crew_name")
    start_raw = require_present(body, "scheduled_start")
    end_raw = require_present(body, "scheduled_end")
    try:
        start_dt = parse_dt(start_raw)
        end_dt = parse_dt(end_raw)
    except (ValueError, TypeError):
        raise ApiError("ERR_VALIDATION", 400, "Invalid scheduled_start/scheduled_end")
    if end_dt <= start_dt:
        raise ApiError("ERR_VALIDATION", 400, "scheduled_end must be after scheduled_start")
    # state
    if u["status"] != "IDENTIFIED":
        raise ApiError("ERR_INVALID_UTILITY_STATE", 409, "Utility relocation not IDENTIFIED")
    # possession readiness
    if not u["possession_cleared"]:
        raise ApiError("ERR_PARCEL_NOT_POSSESSED", 409, "Parcel not possessed")
    # crew buffer overlap
    buffer = timedelta(minutes=CREW_BUFFER_MINUTES)
    for other in store.utility_relocations.values():
        if other["id"] == uid or other["crew_name"] != crew_name or other["status"] != "SCHEDULED":
            continue
        os_ = parse_dt(other["scheduled_start"])
        oe = parse_dt(other["scheduled_end"])
        # far enough apart if new starts >= other end + buffer OR new ends <= other start - buffer
        if not (start_dt >= oe + buffer or end_dt <= os_ - buffer):
            raise ApiError("ERR_CREW_UNAVAILABLE", 409, "Crew window within buffer of another")
    u["crew_name"] = crew_name
    u["scheduled_start"] = fmt_dt(start_dt)
    u["scheduled_end"] = fmt_dt(end_dt)
    u["status"] = "SCHEDULED"
    touch(u)
    return ok(ser_utility(u))


@app.route("/utility-relocations/<uid>/complete", methods=["POST"])
def complete_utility(uid):
    authenticate()
    authorize(["UtilityCoordinator"])
    u = get_or_404(store.utility_relocations, uid)
    if u["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_UTILITY_STATE", 409, "Utility relocation not SCHEDULED")
    u["status"] = "RELOCATED"
    touch(u)
    return ok(ser_utility(u))


# ---------------------------------------------------------------------------
# Escrow
# ---------------------------------------------------------------------------
@app.route("/parcels/<pid>/escrows", methods=["POST"])
def open_escrow(pid):
    authenticate()
    authorize(["EscrowOfficer"])
    parcel = get_or_404(store.parcels, pid)
    body = body_json()
    source = require_enum(body, "source", ("NEGOTIATED", "CONDEMNATION"))
    if source == "NEGOTIATED":
        neg = None
        for n in store.negotiations.values():
            if n["parcel_id"] == pid and n["status"] == "AGREED":
                neg = n
                break
        if neg is None:
            raise ApiError("ERR_INVALID_NEGOTIATION_STATE", 409, "No AGREED negotiation")
        agreed_amount = neg["settlement_total_cents"]
    else:  # CONDEMNATION
        cond = None
        for c in store.condemnations.values():
            if c["parcel_id"] == pid and c["status"] == "AWARDED":
                cond = c
                break
        if cond is None:
            raise ApiError("ERR_INVALID_CONDEMNATION_STATE", 409, "No AWARDED condemnation")
        agreed_amount = cond["settlement_total_cents"]
    e = new_entity()
    e.update({
        "parcel_id": pid,
        "source": source,
        "agreed_amount_cents": agreed_amount,
        "funded_amount_cents": 0,
        "funded_at": None,
        "disbursed_total_cents": 0,
        "disbursements": [],
        "status": "OPENED",
    })
    store.escrows[e["id"]] = e
    return ok(ser_escrow(e), code=201)


@app.route("/escrows/<eid>", methods=["GET"])
def get_escrow(eid):
    authenticate()
    authorize(ALL_ROLES)
    e = get_or_404(store.escrows, eid)
    return ok(ser_escrow(e))


@app.route("/parcels/<pid>/escrows", methods=["GET"])
def list_escrows(pid):
    authenticate()
    authorize(ALL_ROLES)
    get_or_404(store.parcels, pid)
    limit, offset = pagination_params()
    items = sort_seq([e for e in store.escrows.values() if e["parcel_id"] == pid])
    page, total = paginate(items, limit, offset)
    return ok_list([ser_escrow(x) for x in page], limit, offset, total)


@app.route("/escrows/<eid>/fund", methods=["POST"])
def fund_escrow(eid):
    authenticate()
    authorize(["EscrowOfficer"])
    e = get_or_404(store.escrows, eid)
    if e["status"] != "OPENED":
        raise ApiError("ERR_INVALID_ESCROW_STATE", 409, "Escrow not OPENED")
    parcel = store.parcels.get(e["parcel_id"])
    project = store.projects.get(parcel["project_id"]) if parcel else None
    _, _, _, available = project_ledger(project) if project else (0, 0, 0, 0)
    if available < e["agreed_amount_cents"]:
        raise ApiError("ERR_BUDGET_EXCEEDED", 402, "Insufficient available budget")
    e["funded_amount_cents"] = e["agreed_amount_cents"]
    e["funded_at"] = fmt_dt(store.clock_dt)
    e["status"] = "FUNDED"
    touch(e)
    return ok(ser_escrow(e))


def run_disbursement_waterfall(parcel_id, pool):
    disbursements = []
    lienholders = sort_seq([
        o for o in store.ownership_interests.values()
        if o["parcel_id"] == parcel_id and o["interest_type"] == "LIENHOLDER"
    ])
    lienholders = sorted(lienholders, key=lambda o: (o["lien_priority"], o["_seq"]))
    for lh in lienholders:
        pay = min(pool, lh["lien_balance_cents"])
        disbursements.append({
            "payee_label": lh["holder_name"],
            "payee_kind": "LIENHOLDER",
            "amount_cents": pay,
        })
        pool -= pay
    fee_owners = sort_seq([
        o for o in store.ownership_interests.values()
        if o["parcel_id"] == parcel_id and o["interest_type"] == "FEE_OWNER"
    ])
    if fee_owners:
        rounded = []
        for o in fee_owners:
            raw = Decimal(pool) * Decimal(str(o["ownership_pct"])) / Decimal(100)
            rounded.append(round_half_up(raw))
        delta = pool - sum(rounded)
        # earliest-created fee owner is first by _seq
        rounded[0] += delta
        for o, amt in zip(fee_owners, rounded):
            disbursements.append({
                "payee_label": o["holder_name"],
                "payee_kind": "FEE_OWNER",
                "amount_cents": amt,
            })
    return disbursements


@app.route("/escrows/<eid>/close", methods=["POST"])
def close_escrow(eid):
    authenticate()
    authorize(["EscrowOfficer"])
    e = get_or_404(store.escrows, eid)
    if e["status"] != "FUNDED":
        raise ApiError("ERR_INVALID_ESCROW_STATE", 409, "Escrow not FUNDED")
    parcel = store.parcels.get(e["parcel_id"])
    # ownership completeness
    if fee_owner_pct_sum(e["parcel_id"]) != Decimal(100):
        raise ApiError("ERR_OWNERSHIP_INCOMPLETE", 422, "FEE_OWNER ownership_pct must sum to 100")
    # waiting period
    funded_dt = parse_dt(e["funded_at"])
    if store.clock_dt < funded_dt + timedelta(days=ESCROW_WAITING_PERIOD_DAYS):
        raise ApiError("ERR_WAITING_PERIOD_ACTIVE", 409, "Escrow waiting period not elapsed")
    disbursements = run_disbursement_waterfall(e["parcel_id"], e["agreed_amount_cents"])
    e["disbursements"] = disbursements
    e["disbursed_total_cents"] = e["agreed_amount_cents"]
    e["status"] = "CLOSED"
    touch(e)
    if parcel is not None:
        parcel["acquisition_status"] = "ACQUIRED"
        touch(parcel)
    return ok(ser_escrow(e))


@app.route("/escrows/<eid>/rescind", methods=["POST"])
def rescind_escrow(eid):
    authenticate()
    authorize(["ProgramAdmin"])
    e = get_or_404(store.escrows, eid)
    if e["status"] not in ("OPENED", "FUNDED", "CLOSED"):
        raise ApiError("ERR_INVALID_ESCROW_STATE", 409, "Escrow cannot be rescinded")
    was_closed = e["status"] == "CLOSED"
    e["status"] = "CANCELLED"
    if was_closed:
        e["disbursements"] = []
        e["disbursed_total_cents"] = 0
        parcel = store.parcels.get(e["parcel_id"])
        if parcel is not None and parcel["acquisition_status"] == "ACQUIRED":
            parcel["acquisition_status"] = "PENDING"
            touch(parcel)
    touch(e)
    return ok(ser_escrow(e))


# ---------------------------------------------------------------------------
# Error handlers
# ---------------------------------------------------------------------------
@app.errorhandler(ApiError)
def handle_api_error(err):
    return error_response(err)


@app.errorhandler(404)
def handle_404(err):
    return error_response(ApiError("ERR_NOT_FOUND", 404, "Resource not found"))


@app.errorhandler(405)
def handle_405(err):
    return error_response(ApiError("ERR_NOT_FOUND", 404, "Method not allowed"))


@app.errorhandler(Exception)
def handle_unexpected(err):
    if isinstance(err, ApiError):
        return error_response(err)
    return error_response(ApiError("ERR_VALIDATION", 400, f"Unexpected error: {err}"))


# ---------------------------------------------------------------------------
# Store instance (empty at boot — no seeding)
# ---------------------------------------------------------------------------
store = Store()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
