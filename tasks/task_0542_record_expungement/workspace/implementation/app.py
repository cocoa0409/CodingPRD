import os
import uuid
import random
import string
import calendar
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP

from flask import Flask, request, jsonify

app = Flask(__name__)

# ---------------------------------------------------------------------------
# In-memory store (fresh on every boot — NO seeding)
# ---------------------------------------------------------------------------
petitioners = {}
courtrooms = {}
judges = {}
background_vendors = {}
criminal_records = {}
petitions = {}
petition_items = {}
fee_waivers = {}
agency_notifications = {}
objections = {}
hearings = {}
court_orders = {}
sealing_distributions = {}

_seq_counter = 0

# Logical clock — starts at 2026-05-01T00:00:00Z, only moves on explicit set.
STATE = {"clock": datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)}

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
KNOWN_ROLES = {"Petitioner", "Clerk", "Agency", "Judge"}
ALL_ROLES = ["Petitioner", "Clerk", "Agency", "Judge"]

OFFENSE_CLASSES = {
    "INFRACTION", "MISDEMEANOR", "FELONY_CLASS_C",
    "FELONY_CLASS_B", "FELONY_CLASS_A", "VIOLENT_FELONY",
}
DISPOSITIONS = {"CONVICTED", "DISMISSED", "ARREST_ONLY", "ACQUITTED"}

WAITING_PERIOD_YEARS = {
    "INFRACTION": 1, "MISDEMEANOR": 2, "FELONY_CLASS_C": 3,
    "FELONY_CLASS_B": 5, "FELONY_CLASS_A": 7,
}
NEVER_ELIGIBLE = {"VIOLENT_FELONY"}

BASE_FEE_CENTS = {
    "INFRACTION": 5000, "MISDEMEANOR": 12000, "FELONY_CLASS_C": 18000,
    "FELONY_CLASS_B": 25000, "FELONY_CLASS_A": 30000, "VIOLENT_FELONY": 30000,
}
DISP_MULT = {"CONVICTED": "1.0", "DISMISSED": "0.5", "ARREST_ONLY": "0.25", "ACQUITTED": "0.10"}
EFILE_SURCHARGE = Decimal("1.075")

FPL_BASE_CENTS = 1500000
FPL_PER_ADDL_CENTS = 530000
FPL_MULTIPLIER = Decimal("1.25")
ASSET_CAP_CENTS = 200000

OBJECTION_WINDOW = timedelta(days=30)
COURTROOM_BUFFER = timedelta(minutes=30)
MAX_ATTEMPTS = 2

AGENCY_TYPES = ["DA", "ARRESTING_AGENCY", "STATE_REPOSITORY"]

PETITION_STATUSES = {"DRAFT", "SCREENED", "FILED", "OBJECTION_REVIEW",
                     "HEARING_SET", "GRANTED", "DENIED", "WITHDRAWN"}
FEEWAIVER_STATUSES = {"REQUESTED", "GRANTED", "DENIED", "SUPERSEDED"}
NOTIFICATION_STATUSES = {"PENDING", "SERVED", "OBJECTED", "CLEARED"}
OBJECTION_STATUSES = {"REQUESTED", "SUSTAINED", "OVERRULED"}
HEARING_STATUSES = {"SCHEDULED", "HELD", "VACATED", "SUPERSEDED"}
DISTRIBUTION_STATUSES = {"QUEUED", "SENT", "ACKNOWLEDGED", "FAILED", "CANCELLED"}


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
# Helpers
# ---------------------------------------------------------------------------
def next_seq():
    global _seq_counter
    _seq_counter += 1
    return _seq_counter


def new_id():
    return str(uuid.uuid4())


def gen_req_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def now_iso():
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def fmt_iso(dt):
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_dt(s):
    if isinstance(s, datetime):
        dt = s
    else:
        x = str(s).strip()
        if x.endswith("Z") or x.endswith("z"):
            x = x[:-1] + "+00:00"
        dt = datetime.fromisoformat(x)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def clock():
    return STATE["clock"]


def add_years(dt, years):
    year = dt.year + years
    month = dt.month
    day = dt.day
    last = calendar.monthrange(year, month)[1]
    if day > last:
        day = last
    return dt.replace(year=year, month=month, day=day)


def get_json_body():
    body = request.get_json(silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise ApiError("ERR_VALIDATION", 422, "request body must be a JSON object")
    return body


def req_str(body, field):
    v = body.get(field)
    if not isinstance(v, str) or v == "":
        raise ApiError("ERR_VALIDATION", 422, f"{field} is required")
    return v


def req_int_nonneg(body, field):
    v = body.get(field)
    if not isinstance(v, int) or isinstance(v, bool) or v < 0:
        raise ApiError("ERR_VALIDATION", 422, f"{field} must be a non-negative integer")
    return v


def req_dt(body, field):
    if body.get(field) is None:
        raise ApiError("ERR_VALIDATION", 422, f"{field} is required")
    try:
        return parse_dt(body.get(field))
    except Exception:
        raise ApiError("ERR_VALIDATION", 422, f"{field} must be ISO 8601")


def req_enum(body, field, allowed):
    v = body.get(field)
    if not isinstance(v, str) or v not in allowed:
        raise ApiError("ERR_VALIDATION", 422, f"{field} invalid")
    return v


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
def require_auth(allowed_roles):
    role = request.headers.get("X-User-Role")
    uid = request.headers.get("X-User-ID")
    if not role or not uid or role not in KNOWN_ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", 401, "missing or unknown authentication headers")
    if role not in allowed_roles:
        raise ApiError("ERR_UNAUTHORIZED", 403, "role not permitted for this operation")
    return role, uid


# ---------------------------------------------------------------------------
# Entity + response helpers
# ---------------------------------------------------------------------------
def create_entity(store, fields, common=True):
    rec = dict(fields)
    rec["id"] = new_id()
    rec["created_at"] = datetime.now(timezone.utc)
    if common:
        rec["updated_at"] = rec["created_at"]
        rec["version"] = 1
    rec["_seq"] = next_seq()
    store[rec["id"]] = rec
    return rec


def touch(rec):
    if "version" in rec:
        rec["version"] += 1
        rec["updated_at"] = datetime.now(timezone.utc)


def out(rec):
    return {k: (fmt_iso(v) if isinstance(v, datetime) else v)
            for k, v in rec.items() if not k.startswith("_")}


def success(data, status=200, response_type="object", pagination=None):
    meta = {"api_request_id": gen_req_id(), "api_request_timestamp": now_iso()}
    if pagination:
        meta.update(pagination)
    return jsonify({"meta": meta, "response_type": response_type, "data": data}), status


def get_pagination():
    limit = request.args.get("limit")
    offset = request.args.get("offset")
    if limit is None:
        limit = 10
    else:
        try:
            limit = int(limit)
        except (TypeError, ValueError):
            raise ApiError("ERR_VALIDATION", 422, "limit must be an integer")
        if limit < 1:
            limit = 1
        if limit > 100:
            limit = 100
    if offset is None:
        offset = 0
    else:
        try:
            offset = int(offset)
        except (TypeError, ValueError):
            raise ApiError("ERR_VALIDATION", 422, "offset must be an integer")
        if offset < 0:
            offset = 0
    return limit, offset


def list_response(items):
    items = sorted(items, key=lambda x: x["_seq"])
    total = len(items)
    limit, offset = get_pagination()
    page = items[offset:offset + limit]
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + len(page)) < total,
    }
    return success([out(i) for i in page], 200, "array", pagination)


# ---------------------------------------------------------------------------
# Lookup helpers (with proper not-found error ids)
# ---------------------------------------------------------------------------
def get_or_404(store, oid, error_id):
    rec = store.get(oid)
    if rec is None:
        raise ApiError(error_id, 404, "resource not found")
    return rec


# ---------------------------------------------------------------------------
# Calculations
# ---------------------------------------------------------------------------
def per_record_fee(rec):
    base = BASE_FEE_CENTS[rec["offense_class"]]
    mult = Decimal(DISP_MULT[rec["disposition"]])
    val = Decimal(base) * mult * EFILE_SURCHARGE
    return int(val.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def compute_waiver(petitioner):
    poverty = FPL_BASE_CENTS + (petitioner["household_size"] - 1) * FPL_PER_ADDL_CENTS
    threshold = int((Decimal(poverty) * FPL_MULTIPLIER).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    if petitioner["annual_income_cents"] <= threshold and petitioner["monthly_liquid_assets_cents"] <= ASSET_CAP_CENTS:
        basis = "INCOME_UNDER_125"
    else:
        basis = "OVER_THRESHOLD"
    return basis, threshold


def items_of_petition(petition_id):
    return [i for i in petition_items.values() if i["petition_id"] == petition_id]


def notifications_of_petition(petition_id):
    return [n for n in agency_notifications.values() if n["petition_id"] == petition_id]


def distributions_of_order(order_id):
    return [d for d in sealing_distributions.values() if d["court_order_id"] == order_id]


# ===========================================================================
# Configuration resources
# ===========================================================================
@app.route("/expungement/courtrooms", methods=["POST"])
def create_courtroom():
    require_auth(["Clerk"])
    body = get_json_body()
    name = req_str(body, "name")
    juris = req_str(body, "jurisdiction_code")
    rec = create_entity(courtrooms, {"name": name, "jurisdiction_code": juris}, common=False)
    return success(out(rec), 201)


@app.route("/expungement/courtrooms/<oid>", methods=["GET"])
def get_courtroom(oid):
    require_auth(ALL_ROLES)
    return success(out(get_or_404(courtrooms, oid, "ERR_NOT_FOUND")), 200)


@app.route("/expungement/judges", methods=["POST"])
def create_judge():
    require_auth(["Clerk"])
    body = get_json_body()
    name = req_str(body, "name")
    juris = req_str(body, "jurisdiction_code")
    rec = create_entity(judges, {"name": name, "jurisdiction_code": juris}, common=False)
    return success(out(rec), 201)


@app.route("/expungement/judges/<oid>", methods=["GET"])
def get_judge(oid):
    require_auth(ALL_ROLES)
    return success(out(get_or_404(judges, oid, "ERR_NOT_FOUND")), 200)


@app.route("/expungement/background-vendors", methods=["POST"])
def create_vendor():
    require_auth(["Clerk"])
    body = get_json_body()
    name = req_str(body, "name")
    endpoint = req_str(body, "api_endpoint")
    rec = create_entity(background_vendors,
                        {"name": name, "api_endpoint": endpoint, "records_updated_count": 0},
                        common=False)
    return success(out(rec), 201)


@app.route("/expungement/background-vendors/<oid>", methods=["GET"])
def get_vendor(oid):
    require_auth(ALL_ROLES)
    return success(out(get_or_404(background_vendors, oid, "ERR_NOT_FOUND")), 200)


# ===========================================================================
# Petitioner
# ===========================================================================
@app.route("/expungement/petitioners", methods=["POST"])
def create_petitioner():
    require_auth(["Clerk"])
    body = get_json_body()
    full_name = req_str(body, "full_name")
    dob = req_dt(body, "date_of_birth")
    income = req_int_nonneg(body, "annual_income_cents")
    hs = req_int_nonneg(body, "household_size")
    if hs < 1:
        raise ApiError("ERR_VALIDATION", 422, "household_size must be >= 1")
    if body.get("monthly_liquid_assets_cents") is None:
        assets = 0
    else:
        assets = req_int_nonneg(body, "monthly_liquid_assets_cents")
    rec = create_entity(petitioners, {
        "full_name": full_name,
        "date_of_birth": dob,
        "annual_income_cents": income,
        "household_size": hs,
        "monthly_liquid_assets_cents": assets,
        "fee_paid_cents": 0,
        "fee_refunded_cents": 0,
    })
    return success(out(rec), 201)


@app.route("/expungement/petitioners/<oid>", methods=["GET"])
def get_petitioner(oid):
    require_auth(ALL_ROLES)
    return success(out(get_or_404(petitioners, oid, "ERR_PETITIONER_NOT_FOUND")), 200)


# ===========================================================================
# Criminal records
# ===========================================================================
@app.route("/expungement/criminal-records", methods=["POST"])
def create_record():
    role, uid = require_auth(["Petitioner", "Clerk"])
    body = get_json_body()
    petitioner_id = req_str(body, "petitioner_id")
    offense_code = req_str(body, "offense_code")
    offense_class = req_enum(body, "offense_class", OFFENSE_CLASSES)
    disposition = req_enum(body, "disposition", DISPOSITIONS)
    disposition_date = req_dt(body, "disposition_date")
    scd = None
    if disposition == "CONVICTED":
        scd = req_dt(body, "sentence_completion_date")
    else:
        if body.get("sentence_completion_date") is not None:
            try:
                scd = parse_dt(body.get("sentence_completion_date"))
            except Exception:
                raise ApiError("ERR_VALIDATION", 422, "sentence_completion_date must be ISO 8601")
            scd = None  # non-convicted: sentence_completion_date is null
    # existence
    get_or_404(petitioners, petitioner_id, "ERR_PETITIONER_NOT_FOUND")
    # ownership
    if role == "Petitioner" and uid != petitioner_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", 403, "not resource owner")
    rec = create_entity(criminal_records, {
        "petitioner_id": petitioner_id,
        "offense_code": offense_code,
        "offense_class": offense_class,
        "disposition": disposition,
        "disposition_date": disposition_date,
        "sentence_completion_date": scd,
        "status": "UNSCREENED",
        "eligible_on": None,
        "ineligible_reason": None,
    })
    return success(out(rec), 201)


@app.route("/expungement/criminal-records/<oid>", methods=["GET"])
def get_record(oid):
    require_auth(ALL_ROLES)
    return success(out(get_or_404(criminal_records, oid, "ERR_RECORD_NOT_FOUND")), 200)


@app.route("/expungement/criminal-records", methods=["GET"])
def list_records():
    require_auth(ALL_ROLES)
    items = list(criminal_records.values())
    pid = request.args.get("petitioner_id")
    status = request.args.get("status")
    if pid is not None:
        items = [r for r in items if r["petitioner_id"] == pid]
    if status is not None:
        items = [r for r in items if r["status"] == status]
    return list_response(items)


@app.route("/expungement/criminal-records/<oid>/screen", methods=["POST"])
def screen_record(oid):
    require_auth(["Clerk"])
    rec = get_or_404(criminal_records, oid, "ERR_RECORD_NOT_FOUND")
    if rec["status"] not in ("UNSCREENED", "INELIGIBLE"):
        raise ApiError("ERR_INVALID_STATE", 409, "record cannot be screened from its current state")
    if rec["offense_class"] in NEVER_ELIGIBLE:
        rec["status"] = "INELIGIBLE"
        rec["ineligible_reason"] = "NEVER_ELIGIBLE"
        rec["eligible_on"] = None
    else:
        base = rec["sentence_completion_date"] if rec["disposition"] == "CONVICTED" else rec["disposition_date"]
        eligible_on = add_years(base, WAITING_PERIOD_YEARS[rec["offense_class"]])
        rec["eligible_on"] = eligible_on
        if clock() >= eligible_on:
            rec["status"] = "ELIGIBLE"
            rec["ineligible_reason"] = None
        else:
            rec["status"] = "INELIGIBLE"
            rec["ineligible_reason"] = "WAITING_PERIOD"
    touch(rec)
    return success(out(rec), 200)


# ===========================================================================
# Petitions & items
# ===========================================================================
@app.route("/expungement/petitions", methods=["POST"])
def create_petition():
    role, uid = require_auth(["Petitioner", "Clerk"])
    body = get_json_body()
    petitioner_id = req_str(body, "petitioner_id")
    juris = req_str(body, "jurisdiction_code")
    record_ids = body.get("record_ids")
    if not isinstance(record_ids, list):
        raise ApiError("ERR_VALIDATION", 422, "record_ids must be a list")
    for rid in record_ids:
        if not isinstance(rid, str):
            raise ApiError("ERR_VALIDATION", 422, "record_ids must be strings")
    # existence: petitioner then each record (left to right)
    get_or_404(petitioners, petitioner_id, "ERR_PETITIONER_NOT_FOUND")
    for rid in record_ids:
        get_or_404(criminal_records, rid, "ERR_RECORD_NOT_FOUND")
    # ownership
    if role == "Petitioner" and uid != petitioner_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", 403, "not resource owner")
    # reference integrity: each record belongs to petitioner
    for rid in record_ids:
        if criminal_records[rid]["petitioner_id"] != petitioner_id:
            raise ApiError("ERR_RECORD_NOT_OWNED", 409, "record belongs to a different petitioner")
    petition = create_entity(petitions, {
        "petitioner_id": petitioner_id,
        "jurisdiction_code": juris,
        "status": "DRAFT",
        "provisional_fee_cents": None,
        "final_fee_cents": None,
        "amount_paid_cents": 0,
        "fee_due_cents": None,
        "fee_waived": False,
    })
    for rid in record_ids:
        create_entity(petition_items, {
            "petition_id": petition["id"],
            "record_id": rid,
            "eligibility_at_screening": None,
            "fee_at_screening_cents": None,
        }, common=False)
    return success(out(petition), 201)


@app.route("/expungement/petitions/<oid>", methods=["GET"])
def get_petition(oid):
    require_auth(ALL_ROLES)
    return success(out(get_or_404(petitions, oid, "ERR_PETITION_NOT_FOUND")), 200)


@app.route("/expungement/petitions", methods=["GET"])
def list_petitions():
    require_auth(ALL_ROLES)
    items = list(petitions.values())
    pid = request.args.get("petitioner_id")
    juris = request.args.get("jurisdiction_code")
    status = request.args.get("status")
    if pid is not None:
        items = [p for p in items if p["petitioner_id"] == pid]
    if juris is not None:
        items = [p for p in items if p["jurisdiction_code"] == juris]
    if status is not None:
        items = [p for p in items if p["status"] == status]
    return list_response(items)


@app.route("/expungement/petition-items/<oid>", methods=["GET"])
def get_petition_item(oid):
    require_auth(ALL_ROLES)
    return success(out(get_or_404(petition_items, oid, "ERR_NOT_FOUND")), 200)


@app.route("/expungement/petition-items", methods=["GET"])
def list_petition_items():
    require_auth(ALL_ROLES)
    items = list(petition_items.values())
    petition_id = request.args.get("petition_id")
    record_id = request.args.get("record_id")
    if petition_id is not None:
        items = [i for i in items if i["petition_id"] == petition_id]
    if record_id is not None:
        items = [i for i in items if i["record_id"] == record_id]
    return list_response(items)


def _petition_screened(petition):
    items = items_of_petition(petition["id"])
    if len(items) == 0:
        raise ApiError("ERR_RECORDS_NOT_SCREENED", 409, "petition has no records screened")
    for i in items:
        rec = criminal_records.get(i["record_id"])
        if rec is None or rec["status"] not in ("ELIGIBLE", "INELIGIBLE"):
            raise ApiError("ERR_RECORDS_NOT_SCREENED", 409, "a record is still unscreened")
    provisional = 0
    for i in items:
        rec = criminal_records[i["record_id"]]
        fee = per_record_fee(rec)
        i["eligibility_at_screening"] = rec["status"]
        i["fee_at_screening_cents"] = fee
        provisional += fee
    petition["provisional_fee_cents"] = provisional
    petition["status"] = "SCREENED"
    touch(petition)


def _petition_filed(petition):
    items = items_of_petition(petition["id"])
    eligible_items = [i for i in items if i["eligibility_at_screening"] == "ELIGIBLE"]
    if len(eligible_items) == 0:
        raise ApiError("ERR_NO_ELIGIBLE_RECORDS", 409, "petition has no eligible records")
    final = sum(i["fee_at_screening_cents"] for i in eligible_items)
    if not petition["fee_waived"] and petition["amount_paid_cents"] < final:
        raise ApiError("ERR_FILING_FEE_UNPAID", 402, "filing fee not satisfied")
    petition["final_fee_cents"] = final
    petition["fee_due_cents"] = 0 if petition["fee_waived"] else max(final - petition["amount_paid_cents"], 0)
    for agency in AGENCY_TYPES:
        create_entity(agency_notifications, {
            "petition_id": petition["id"],
            "agency_type": agency,
            "status": "PENDING",
            "served_at": None,
            "objection_deadline": None,
        })
    petition["status"] = "FILED"
    touch(petition)


def _petition_withdrawn(petition):
    src = petition["status"]
    petitioner = petitioners.get(petition["petitioner_id"])
    if src in ("SCREENED", "FILED", "HEARING_SET"):
        if petitioner is not None:
            petitioner["fee_refunded_cents"] += petition["amount_paid_cents"]
            touch(petitioner)
    if src == "FILED":
        for n in notifications_of_petition(petition["id"]):
            if n["status"] != "CLEARED":
                n["status"] = "CLEARED"
                touch(n)
    if src == "HEARING_SET":
        for h in hearings.values():
            if h["petition_id"] == petition["id"] and h["status"] == "SCHEDULED":
                h["status"] = "VACATED"
                touch(h)
    petition["status"] = "WITHDRAWN"
    touch(petition)


@app.route("/expungement/petitions/<oid>/transition", methods=["POST"])
def petition_transition(oid):
    role, uid = require_auth(["Petitioner", "Clerk"])
    body = get_json_body()
    to_status = req_str(body, "to_status")
    if to_status not in ("SCREENED", "FILED", "WITHDRAWN"):
        if to_status in PETITION_STATUSES:
            raise ApiError("ERR_INVALID_STATE", 409, "transition not available via this endpoint")
        raise ApiError("ERR_VALIDATION", 422, "invalid to_status")
    petition = get_or_404(petitions, oid, "ERR_PETITION_NOT_FOUND")
    # ownership: petitioner may only act on own petition
    if role == "Petitioner" and uid != petition["petitioner_id"]:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", 403, "not resource owner")
    if to_status == "SCREENED":
        if petition["status"] != "DRAFT":
            raise ApiError("ERR_INVALID_STATE", 409, "SCREENED only from DRAFT")
        _petition_screened(petition)
    elif to_status == "FILED":
        if petition["status"] != "SCREENED":
            raise ApiError("ERR_INVALID_STATE", 409, "FILED only from SCREENED")
        _petition_filed(petition)
    else:  # WITHDRAWN
        if petition["status"] not in ("DRAFT", "SCREENED", "FILED", "HEARING_SET"):
            raise ApiError("ERR_INVALID_STATE", 409, "cannot withdraw from current state")
        _petition_withdrawn(petition)
    return success(out(petition), 200)


@app.route("/expungement/petitions/<oid>/pay-fee", methods=["POST"])
def pay_fee(oid):
    role, uid = require_auth(["Petitioner", "Clerk"])
    body = get_json_body()
    amount = req_int_nonneg(body, "amount_cents")
    petition = get_or_404(petitions, oid, "ERR_PETITION_NOT_FOUND")
    if role == "Petitioner" and uid != petition["petitioner_id"]:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", 403, "not resource owner")
    petition["amount_paid_cents"] += amount
    petitioner = petitioners.get(petition["petitioner_id"])
    if petitioner is not None:
        petitioner["fee_paid_cents"] += amount
        touch(petitioner)
    if not petition["fee_waived"] and petition["final_fee_cents"] is not None:
        petition["fee_due_cents"] = max(petition["final_fee_cents"] - petition["amount_paid_cents"], 0)
    touch(petition)
    return success(out(petition), 200)


def _hearing_conflict(petition, courtroom_id, judge_id, start, end):
    for h in hearings.values():
        if h["status"] != "SCHEDULED":
            continue
        if h["petition_id"] == petition["id"]:
            continue
        # courtroom buffer semantics (30-min changeover buffer, closed with buffer)
        if h["courtroom_id"] == courtroom_id:
            if start < h["scheduled_end"] + COURTROOM_BUFFER and h["scheduled_start"] < end + COURTROOM_BUFFER:
                raise ApiError("ERR_COURTROOM_UNAVAILABLE", 409, "courtroom conflict")
    for h in hearings.values():
        if h["status"] != "SCHEDULED":
            continue
        if h["petition_id"] == petition["id"]:
            continue
        # judge half-open semantics [start, end), no buffer
        if h["judge_id"] == judge_id:
            if start < h["scheduled_end"] and h["scheduled_start"] < end:
                raise ApiError("ERR_JUDGE_UNAVAILABLE", 409, "judge conflict")


@app.route("/expungement/petitions/<oid>/hearings", methods=["POST"])
def schedule_hearing(oid):
    require_auth(["Clerk"])
    body = get_json_body()
    courtroom_id = req_str(body, "courtroom_id")
    judge_id = req_str(body, "judge_id")
    start = req_dt(body, "scheduled_start")
    end = req_dt(body, "scheduled_end")
    if end <= start:
        raise ApiError("ERR_VALIDATION", 422, "scheduled_end must be after scheduled_start")
    epv = body.get("expected_petition_version")
    if not isinstance(epv, int) or isinstance(epv, bool):
        raise ApiError("ERR_VALIDATION", 422, "expected_petition_version is required")
    # existence: petition (path), courtroom, judge
    petition = get_or_404(petitions, oid, "ERR_PETITION_NOT_FOUND")
    courtroom = get_or_404(courtrooms, courtroom_id, "ERR_NOT_FOUND")
    judge = get_or_404(judges, judge_id, "ERR_NOT_FOUND")
    # state
    if petition["status"] not in ("FILED", "HEARING_SET"):
        raise ApiError("ERR_INVALID_STATE", 409, "hearing scheduling not allowed from current state")
    # concurrency
    if epv != petition["version"]:
        raise ApiError("ERR_STALE_VERSION", 412, "stale petition version")
    # reference integrity: jurisdiction
    if courtroom["jurisdiction_code"] != petition["jurisdiction_code"] or judge["jurisdiction_code"] != petition["jurisdiction_code"]:
        raise ApiError("ERR_JURISDICTION_MISMATCH", 409, "jurisdiction mismatch")
    # temporal availability
    _hearing_conflict(petition, courtroom_id, judge_id, start, end)
    # compliance: all notifications cleared
    for n in notifications_of_petition(petition["id"]):
        if n["status"] != "CLEARED":
            raise ApiError("ERR_NOTIFICATIONS_NOT_CLEARED", 409, "notifications not cleared")
    # side effects
    if petition["status"] == "HEARING_SET":
        for h in hearings.values():
            if h["petition_id"] == petition["id"] and h["status"] == "SCHEDULED":
                h["status"] = "SUPERSEDED"
                touch(h)
    hearing = create_entity(hearings, {
        "petition_id": petition["id"],
        "courtroom_id": courtroom_id,
        "judge_id": judge_id,
        "scheduled_start": start,
        "scheduled_end": end,
        "status": "SCHEDULED",
    })
    petition["status"] = "HEARING_SET"
    touch(petition)
    return success(out(hearing), 201)


# ===========================================================================
# Fee waivers
# ===========================================================================
@app.route("/expungement/fee-waivers", methods=["POST"])
def create_fee_waiver():
    role, uid = require_auth(["Petitioner", "Clerk"])
    body = get_json_body()
    petitioner_id = req_str(body, "petitioner_id")
    petition_id = req_str(body, "petition_id")
    petitioner = get_or_404(petitioners, petitioner_id, "ERR_PETITIONER_NOT_FOUND")
    get_or_404(petitions, petition_id, "ERR_PETITION_NOT_FOUND")
    if role == "Petitioner" and uid != petitioner_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", 403, "not resource owner")
    # supersede prior REQUESTED waiver for the same petition
    for w in fee_waivers.values():
        if w["petition_id"] == petition_id and w["status"] == "REQUESTED":
            w["status"] = "SUPERSEDED"
            touch(w)
    basis, threshold = compute_waiver(petitioner)
    waiver = create_entity(fee_waivers, {
        "petitioner_id": petitioner_id,
        "petition_id": petition_id,
        "status": "REQUESTED",
        "determination_basis": basis,
        "income_threshold_cents": threshold,
    })
    return success(out(waiver), 201)


@app.route("/expungement/fee-waivers/<oid>", methods=["GET"])
def get_fee_waiver(oid):
    require_auth(ALL_ROLES)
    return success(out(get_or_404(fee_waivers, oid, "ERR_NOT_FOUND")), 200)


@app.route("/expungement/fee-waivers", methods=["GET"])
def list_fee_waivers():
    require_auth(ALL_ROLES)
    items = list(fee_waivers.values())
    pid = request.args.get("petitioner_id")
    petition_id = request.args.get("petition_id")
    status = request.args.get("status")
    if pid is not None:
        items = [w for w in items if w["petitioner_id"] == pid]
    if petition_id is not None:
        items = [w for w in items if w["petition_id"] == petition_id]
    if status is not None:
        items = [w for w in items if w["status"] == status]
    return list_response(items)


@app.route("/expungement/fee-waivers/<oid>/transition", methods=["POST"])
def fee_waiver_transition(oid):
    require_auth(["Clerk"])
    body = get_json_body()
    to_status = req_str(body, "to_status")
    if to_status not in ("GRANTED", "DENIED"):
        if to_status in FEEWAIVER_STATUSES:
            raise ApiError("ERR_INVALID_STATE", 409, "transition not available via this endpoint")
        raise ApiError("ERR_VALIDATION", 422, "invalid to_status")
    waiver = get_or_404(fee_waivers, oid, "ERR_NOT_FOUND")
    if waiver["status"] != "REQUESTED":
        raise ApiError("ERR_INVALID_STATE", 409, "waiver not in REQUESTED state")
    if to_status == "GRANTED":
        if waiver["determination_basis"] != "INCOME_UNDER_125":
            raise ApiError("ERR_WAIVER_NOT_ELIGIBLE", 409, "waiver not eligible")
        petition = petitions.get(waiver["petition_id"])
        if petition is not None:
            petition["fee_waived"] = True
            petition["fee_due_cents"] = 0
            touch(petition)
        waiver["status"] = "GRANTED"
        touch(waiver)
    else:
        waiver["status"] = "DENIED"
        touch(waiver)
    return success(out(waiver), 200)


# ===========================================================================
# Agency notifications & objections
# ===========================================================================
@app.route("/expungement/agency-notifications/<oid>", methods=["GET"])
def get_notification(oid):
    require_auth(ALL_ROLES)
    return success(out(get_or_404(agency_notifications, oid, "ERR_NOT_FOUND")), 200)


@app.route("/expungement/agency-notifications", methods=["GET"])
def list_notifications():
    require_auth(ALL_ROLES)
    items = list(agency_notifications.values())
    petition_id = request.args.get("petition_id")
    status = request.args.get("status")
    if petition_id is not None:
        items = [n for n in items if n["petition_id"] == petition_id]
    if status is not None:
        items = [n for n in items if n["status"] == status]
    return list_response(items)


@app.route("/expungement/agency-notifications/<oid>/transition", methods=["POST"])
def notification_transition(oid):
    require_auth(["Clerk"])
    body = get_json_body()
    to_status = req_str(body, "to_status")
    if to_status not in ("SERVED", "CLEARED"):
        if to_status in NOTIFICATION_STATUSES:
            raise ApiError("ERR_INVALID_STATE", 409, "transition not available via this endpoint")
        raise ApiError("ERR_VALIDATION", 422, "invalid to_status")
    n = get_or_404(agency_notifications, oid, "ERR_NOT_FOUND")
    if to_status == "SERVED":
        if n["status"] != "PENDING":
            raise ApiError("ERR_INVALID_STATE", 409, "SERVED only from PENDING")
        n["served_at"] = clock()
        n["objection_deadline"] = clock() + OBJECTION_WINDOW
        n["status"] = "SERVED"
        touch(n)
    else:  # CLEARED
        if n["status"] != "SERVED":
            raise ApiError("ERR_INVALID_STATE", 409, "CLEARED only from SERVED")
        if n["objection_deadline"] is not None and clock() < n["objection_deadline"]:
            raise ApiError("ERR_OBJECTION_WINDOW_OPEN", 409, "objection window still open")
        for obj in objections.values():
            if obj["notification_id"] == n["id"] and obj["status"] == "REQUESTED":
                raise ApiError("ERR_INVALID_STATE", 409, "objection outstanding")
        n["status"] = "CLEARED"
        touch(n)
    return success(out(n), 200)


@app.route("/expungement/agency-notifications/<oid>/objections", methods=["POST"])
def file_objection(oid):
    require_auth(["Agency"])
    body = get_json_body()
    grounds = req_str(body, "grounds")
    n = get_or_404(agency_notifications, oid, "ERR_NOT_FOUND")
    if n["status"] != "SERVED":
        raise ApiError("ERR_INVALID_STATE", 409, "objection only against a SERVED notification")
    if n["objection_deadline"] is not None and clock() > n["objection_deadline"]:
        raise ApiError("ERR_OBJECTION_WINDOW_CLOSED", 409, "objection window closed")
    obj = create_entity(objections, {
        "notification_id": n["id"],
        "grounds": grounds,
        "status": "REQUESTED",
        "filed_at": clock(),
    })
    n["status"] = "OBJECTED"
    touch(n)
    petition = petitions.get(n["petition_id"])
    if petition is not None and petition["status"] == "FILED":
        petition["status"] = "OBJECTION_REVIEW"
        touch(petition)
    return success(out(obj), 201)


@app.route("/expungement/objections/<oid>", methods=["GET"])
def get_objection(oid):
    require_auth(ALL_ROLES)
    return success(out(get_or_404(objections, oid, "ERR_NOT_FOUND")), 200)


@app.route("/expungement/objections", methods=["GET"])
def list_objections():
    require_auth(ALL_ROLES)
    items = list(objections.values())
    notification_id = request.args.get("notification_id")
    status = request.args.get("status")
    if notification_id is not None:
        items = [o for o in items if o["notification_id"] == notification_id]
    if status is not None:
        items = [o for o in items if o["status"] == status]
    return list_response(items)


@app.route("/expungement/objections/<oid>/transition", methods=["POST"])
def objection_transition(oid):
    require_auth(["Clerk"])
    body = get_json_body()
    to_status = req_str(body, "to_status")
    if to_status not in ("SUSTAINED", "OVERRULED"):
        if to_status in OBJECTION_STATUSES:
            raise ApiError("ERR_INVALID_STATE", 409, "transition not available via this endpoint")
        raise ApiError("ERR_VALIDATION", 422, "invalid to_status")
    obj = get_or_404(objections, oid, "ERR_NOT_FOUND")
    if obj["status"] != "REQUESTED":
        raise ApiError("ERR_INVALID_STATE", 409, "objection not in REQUESTED state")
    n = agency_notifications.get(obj["notification_id"])
    petition = petitions.get(n["petition_id"]) if n is not None else None
    if to_status == "SUSTAINED":
        obj["status"] = "SUSTAINED"
        touch(obj)
        if petition is not None and petition["status"] == "OBJECTION_REVIEW":
            petition["status"] = "DENIED"
            touch(petition)
    else:  # OVERRULED
        obj["status"] = "OVERRULED"
        touch(obj)
        if n is not None and n["status"] == "OBJECTED":
            n["status"] = "CLEARED"
            touch(n)
        if petition is not None and petition["status"] == "OBJECTION_REVIEW":
            still_objected = any(
                x["status"] == "OBJECTED" for x in notifications_of_petition(petition["id"])
            )
            if not still_objected:
                petition["status"] = "FILED"
                touch(petition)
    return success(out(obj), 200)


# ===========================================================================
# Hearing transitions & court order
# ===========================================================================
@app.route("/expungement/hearings/<oid>", methods=["GET"])
def get_hearing(oid):
    require_auth(ALL_ROLES)
    return success(out(get_or_404(hearings, oid, "ERR_HEARING_NOT_FOUND")), 200)


@app.route("/expungement/hearings", methods=["GET"])
def list_hearings():
    require_auth(ALL_ROLES)
    items = list(hearings.values())
    petition_id = request.args.get("petition_id")
    courtroom_id = request.args.get("courtroom_id")
    judge_id = request.args.get("judge_id")
    status = request.args.get("status")
    if petition_id is not None:
        items = [h for h in items if h["petition_id"] == petition_id]
    if courtroom_id is not None:
        items = [h for h in items if h["courtroom_id"] == courtroom_id]
    if judge_id is not None:
        items = [h for h in items if h["judge_id"] == judge_id]
    if status is not None:
        items = [h for h in items if h["status"] == status]
    return list_response(items)


@app.route("/expungement/hearings/<oid>/transition", methods=["POST"])
def hearing_transition(oid):
    require_auth(["Clerk"])
    body = get_json_body()
    to_status = req_str(body, "to_status")
    if to_status not in ("HELD", "VACATED"):
        if to_status in HEARING_STATUSES:
            raise ApiError("ERR_INVALID_STATE", 409, "transition not available via this endpoint")
        raise ApiError("ERR_VALIDATION", 422, "invalid to_status")
    h = get_or_404(hearings, oid, "ERR_HEARING_NOT_FOUND")
    if h["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", 409, "hearing not in SCHEDULED state")
    h["status"] = to_status
    touch(h)
    return success(out(h), 200)


@app.route("/expungement/hearings/<oid>/order", methods=["POST"])
def enter_order(oid):
    require_auth(["Judge"])
    body = get_json_body()
    disposition = req_enum(body, "disposition", {"GRANTED", "DENIED"})
    h = get_or_404(hearings, oid, "ERR_HEARING_NOT_FOUND")
    petition = petitions.get(h["petition_id"])
    if petition is None or petition["status"] != "HEARING_SET":
        raise ApiError("ERR_INVALID_STATE", 409, "petition not awaiting an order")
    if h["status"] != "HELD":
        raise ApiError("ERR_HEARING_NOT_HELD", 409, "hearing has not been held")
    order = create_entity(court_orders, {
        "petition_id": petition["id"],
        "hearing_id": h["id"],
        "disposition": disposition,
        "status": "ENTERED",
        "entered_at": clock(),
    })
    if disposition == "GRANTED":
        petition["status"] = "GRANTED"
        touch(petition)
        for item in items_of_petition(petition["id"]):
            if item["eligibility_at_screening"] != "ELIGIBLE":
                continue
            rec = criminal_records.get(item["record_id"])
            if rec is None or rec["status"] != "ELIGIBLE":
                continue
            rec["status"] = "SEALED"
            touch(rec)
            for agency in AGENCY_TYPES:
                create_entity(sealing_distributions, {
                    "court_order_id": order["id"],
                    "recipient_type": agency,
                    "recipient_ref": agency,
                    "status": "QUEUED",
                    "attempt_count": 0,
                })
            for vendor in sorted(background_vendors.values(), key=lambda v: v["_seq"]):
                create_entity(sealing_distributions, {
                    "court_order_id": order["id"],
                    "recipient_type": "BACKGROUND_VENDOR",
                    "recipient_ref": vendor["id"],
                    "status": "QUEUED",
                    "attempt_count": 0,
                })
    else:  # DENIED
        petition["status"] = "DENIED"
        touch(petition)
    return success(out(order), 201)


@app.route("/expungement/court-orders/<oid>", methods=["GET"])
def get_court_order(oid):
    require_auth(ALL_ROLES)
    return success(out(get_or_404(court_orders, oid, "ERR_COURT_ORDER_NOT_FOUND")), 200)


@app.route("/expungement/court-orders", methods=["GET"])
def list_court_orders():
    require_auth(ALL_ROLES)
    items = list(court_orders.values())
    petition_id = request.args.get("petition_id")
    hearing_id = request.args.get("hearing_id")
    status = request.args.get("status")
    if petition_id is not None:
        items = [c for c in items if c["petition_id"] == petition_id]
    if hearing_id is not None:
        items = [c for c in items if c["hearing_id"] == hearing_id]
    if status is not None:
        items = [c for c in items if c["status"] == status]
    return list_response(items)


@app.route("/expungement/court-orders/<oid>/vacate", methods=["POST"])
def vacate_order(oid):
    require_auth(["Judge"])
    order = get_or_404(court_orders, oid, "ERR_COURT_ORDER_NOT_FOUND")
    from_state = order["status"]
    if from_state == "ENTERED":
        if order["disposition"] != "GRANTED":
            raise ApiError("ERR_INVALID_STATE", 409, "only a granted order can be vacated")
    elif from_state == "DISTRIBUTED":
        pass
    else:
        raise ApiError("ERR_INVALID_STATE", 409, "order cannot be vacated from its current state")
    petition = petitions.get(order["petition_id"])
    if petition is not None:
        for item in items_of_petition(petition["id"]):
            rec = criminal_records.get(item["record_id"])
            if rec is not None and rec["status"] == "SEALED":
                rec["status"] = "ELIGIBLE"
                touch(rec)
    if from_state == "ENTERED":
        for d in distributions_of_order(order["id"]):
            if d["status"] not in ("ACKNOWLEDGED", "CANCELLED"):
                d["status"] = "CANCELLED"
                touch(d)
    order["status"] = "VACATED"
    touch(order)
    return success(out(order), 200)


# ===========================================================================
# Sealing distributions
# ===========================================================================
@app.route("/expungement/sealing-distributions/<oid>", methods=["GET"])
def get_distribution(oid):
    require_auth(ALL_ROLES)
    return success(out(get_or_404(sealing_distributions, oid, "ERR_NOT_FOUND")), 200)


@app.route("/expungement/sealing-distributions", methods=["GET"])
def list_distributions():
    require_auth(ALL_ROLES)
    items = list(sealing_distributions.values())
    court_order_id = request.args.get("court_order_id")
    recipient_type = request.args.get("recipient_type")
    status = request.args.get("status")
    if court_order_id is not None:
        items = [d for d in items if d["court_order_id"] == court_order_id]
    if recipient_type is not None:
        items = [d for d in items if d["recipient_type"] == recipient_type]
    if status is not None:
        items = [d for d in items if d["status"] == status]
    return list_response(items)


ALLOWED_DIST_TRANSITIONS = {
    ("QUEUED", "SENT"),
    ("SENT", "ACKNOWLEDGED"),
    ("SENT", "FAILED"),
    ("FAILED", "QUEUED"),
}


@app.route("/expungement/sealing-distributions/<oid>/transition", methods=["POST"])
def distribution_transition(oid):
    require_auth(["Clerk"])
    body = get_json_body()
    to_status = req_str(body, "to_status")
    if to_status not in DISTRIBUTION_STATUSES:
        raise ApiError("ERR_VALIDATION", 422, "invalid to_status")
    d = get_or_404(sealing_distributions, oid, "ERR_NOT_FOUND")
    if (d["status"], to_status) not in ALLOWED_DIST_TRANSITIONS:
        raise ApiError("ERR_INVALID_STATE", 409, "transition not defined from current state")
    if to_status == "SENT":
        d["status"] = "SENT"
        touch(d)
    elif to_status == "FAILED":
        d["status"] = "FAILED"
        touch(d)
    elif to_status == "QUEUED":  # retry
        if d["attempt_count"] >= MAX_ATTEMPTS:
            raise ApiError("ERR_MAX_RETRIES_EXCEEDED", 409, "retry cap reached")
        d["attempt_count"] += 1
        d["status"] = "QUEUED"
        touch(d)
    else:  # ACKNOWLEDGED
        d["status"] = "ACKNOWLEDGED"
        if d["recipient_type"] == "BACKGROUND_VENDOR":
            vendor = background_vendors.get(d["recipient_ref"])
            if vendor is not None:
                vendor["records_updated_count"] += 1
        touch(d)
        order = court_orders.get(d["court_order_id"])
        if order is not None and order["status"] == "ENTERED" and order["disposition"] == "GRANTED":
            siblings = distributions_of_order(order["id"])
            if siblings and all(s["status"] == "ACKNOWLEDGED" for s in siblings):
                order["status"] = "DISTRIBUTED"
                touch(order)
    return success(out(d), 200)


# ===========================================================================
# Logical clock (test-driving)
# ===========================================================================
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    require_auth(["Clerk"])
    body = get_json_body()
    if body.get("to_iso8601") is None:
        raise ApiError("ERR_VALIDATION", 422, "to_iso8601 is required")
    try:
        STATE["clock"] = parse_dt(body.get("to_iso8601"))
    except Exception:
        raise ApiError("ERR_VALIDATION", 422, "to_iso8601 must be ISO 8601")
    return success({}, 200)


# ---------------------------------------------------------------------------
# Error handlers
# ---------------------------------------------------------------------------
@app.errorhandler(ApiError)
def handle_api_error(e):
    meta = {"api_request_id": gen_req_id(), "api_request_timestamp": now_iso()}
    body = {"meta": meta, "response_type": "error",
            "data": {"error_id": e.error_id, "message": e.message}}
    return jsonify(body), e.http_status


@app.errorhandler(404)
def handle_404(e):
    meta = {"api_request_id": gen_req_id(), "api_request_timestamp": now_iso()}
    body = {"meta": meta, "response_type": "error",
            "data": {"error_id": "ERR_NOT_FOUND", "message": "resource not found"}}
    return jsonify(body), 404


@app.errorhandler(405)
def handle_405(e):
    meta = {"api_request_id": gen_req_id(), "api_request_timestamp": now_iso()}
    body = {"meta": meta, "response_type": "error",
            "data": {"error_id": "ERR_NOT_FOUND", "message": "method not allowed"}}
    return jsonify(body), 404


@app.errorhandler(Exception)
def handle_uncaught(e):
    if isinstance(e, ApiError):
        return handle_api_error(e)
    meta = {"api_request_id": gen_req_id(), "api_request_timestamp": now_iso()}
    body = {"meta": meta, "response_type": "error",
            "data": {"error_id": "ERR_INTERNAL", "message": str(e)}}
    return jsonify(body), 500


@app.route("/", methods=["GET"])
def root():
    return success({"service": "record-expungement"}, 200)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
