import os
import uuid
import random
import string
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP, ROUND_CEILING

from flask import Flask, request, jsonify, g

app = Flask(__name__)

# =============================================================================
# Constants
# =============================================================================
VARIANCE_UPLIFT = Decimal("0.20")
TAX_RATE = Decimal("0.0725")
DEPOSIT_TIER = {
    "RED": Decimal("0.80"),
    "ORANGE": Decimal("0.60"),
    "YELLOW": Decimal("0.50"),
    "GREEN": Decimal("0.30"),
}
DEPOSIT_TIER_FLOAT = {"RED": 0.8, "ORANGE": 0.6, "YELLOW": 0.5, "GREEN": 0.3}

PROMO_MIN_CENTS = 100000
PROMO_MAX_MONTHS = 6
APR_MONTHLY = Decimal("0.0225")

PER_DIEM = {"ICU": 180000, "WARD": 60000}
ICU_CAPACITY = 20

TRIAGE_LEVELS = {"RED", "ORANGE", "YELLOW", "GREEN"}
SPECIES = {"CANINE", "FELINE", "EXOTIC"}
REFERRAL_DEPARTMENTS = {"CARDIOLOGY", "ONCOLOGY", "SURGERY", "NEUROLOGY"}
WARDS = {"ICU", "WARD"}
MODALITIES = {"IMAGING_CT", "IMAGING_MRI", "SURGERY"}
RESOURCE_ROOMS = {"CT_SUITE", "MRI_SUITE", "OR_1", "OR_2"}
MODALITY_ROOM = {
    "IMAGING_CT": {"CT_SUITE"},
    "IMAGING_MRI": {"MRI_SUITE"},
    "SURGERY": {"OR_1", "OR_2"},
}
PROVIDERS = {"CARECREDIT", "IN_HOUSE"}
ROLES = {"TriageNurse", "ClinicianDVM", "FinanceCoordinator", "Owner"}

DEFAULT_CLOCK = "2026-05-01T00:00:00Z"


# =============================================================================
# In-memory store (fresh on every boot)
# =============================================================================
class Store:
    def __init__(self):
        self.patients = {}
        self.visits = {}
        self.referrals = {}
        self.estimates = {}
        self.authorizations = {}
        self.hospitalizations = {}
        self.procedures = {}
        self.invoices = {}
        self.payment_plans = {}
        self.reports = {}
        self.clock = DEFAULT_CLOCK


db = Store()


# =============================================================================
# Error handling
# =============================================================================
class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id
        super().__init__(self.message)


ERR = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 400,
    "ERR_INVALID_STATE": 409,
    "ERR_VISIT_NOT_TRIAGED": 409,
    "ERR_VISIT_NOT_OPEN": 409,
    "ERR_NO_ACTIVE_AUTH": 409,
    "ERR_VISIT_HAS_ACTIVE_AUTH": 409,
    "ERR_ESTIMATE_NOT_ISSUED": 409,
    "ERR_CEILING_BELOW_ESTIMATE": 409,
    "ERR_CEILING_EXCEEDED": 409,
    "ERR_CEILING_BELOW_COMMITTED": 409,
    "ERR_PATIENT_STILL_BOARDED": 409,
    "ERR_PROCEDURE_PENDING": 409,
    "ERR_CHARGES_PENDING": 409,
    "ERR_RESOURCE_DOUBLE_BOOKED": 409,
    "ERR_CAGE_OCCUPIED": 409,
    "ERR_MODALITY_ROOM_MISMATCH": 422,
    "ERR_CAGE_OUT_OF_RANGE": 422,
    "ERR_INVOICE_NOT_SETTLED": 409,
    "ERR_INVOICE_NOT_FINALIZED": 409,
    "ERR_PLAN_ALREADY_ACTIVE": 409,
    "ERR_PAYMENT_INSUFFICIENT": 402,
    "ERR_STALE_VERSION": 412,
}


def err(error_id, message=None):
    return ApiError(error_id, ERR[error_id], message)


# =============================================================================
# Helpers: time, ids, response envelope
# =============================================================================
def now_iso():
    """Return current logical clock as ISO8601 with 3 fractional digits."""
    dt = parse_dt(db.clock)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + \
        f"{dt.microsecond // 1000:03d}Z"


def parse_dt(s):
    if not isinstance(s, str):
        raise err("ERR_INVALID_REQUEST", "invalid datetime")
    v = s.strip()
    if v.endswith("Z"):
        v = v[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(v)
    except Exception:
        raise err("ERR_INVALID_REQUEST", "invalid datetime")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def new_id():
    return str(uuid.uuid4())


def request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def meta(extra=None):
    m = {"api_request_id": request_id(), "api_request_timestamp": now_iso()}
    if extra:
        m.update(extra)
    return m


def ok(data, status=200, response_type="object", meta_extra=None):
    body = {"meta": meta(meta_extra), "response_type": response_type, "data": data}
    return jsonify(body), status


def paginate(items):
    """items already sorted. Returns (page, meta_extra)."""
    limit = request.args.get("limit")
    offset = request.args.get("offset")
    lim = 10
    off = 0
    if limit is not None:
        try:
            lim = int(limit)
        except Exception:
            raise err("ERR_INVALID_REQUEST", "bad limit")
        if lim < 1:
            lim = 1
        if lim > 100:
            lim = 100
    if offset is not None:
        try:
            off = int(offset)
        except Exception:
            raise err("ERR_INVALID_REQUEST", "bad offset")
        if off < 0:
            off = 0
    total = len(items)
    page = items[off:off + lim]
    meta_extra = {
        "limit": lim,
        "offset": off,
        "total_count": total,
        "has_more": off + lim < total,
    }
    return page, meta_extra


def list_response(items, filter_fn=None):
    seq = list(items.values()) if isinstance(items, dict) else list(items)
    if filter_fn:
        seq = [x for x in seq if filter_fn(x)]
    seq.sort(key=lambda r: (r["created_at"], r.get("_seq", 0)))
    page, meta_extra = paginate(seq)
    data = [serialize(r) for r in page]
    return ok(data, 200, "array", meta_extra)


# =============================================================================
# Rounding helpers (Decimal)
# =============================================================================
def round_half_up(value):
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def ceil_dec(value):
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_CEILING))


def tax_of_line(amount_cents):
    return round_half_up(Decimal(amount_cents) * TAX_RATE)


# =============================================================================
# Auth
# =============================================================================
def authenticate():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role:
        raise err("ERR_UNAUTHENTICATED", "missing auth headers")
    if role not in ROLES:
        # Unknown role -> not permitted for any operation
        raise err("ERR_FORBIDDEN", "unknown role")
    g.user_id = uid
    g.role = role
    return uid, role


def require_role(*allowed):
    if g.role not in allowed:
        raise err("ERR_FORBIDDEN", "role not permitted")


def require_owner_of(visit):
    """Owner ownership check: X-User-ID must equal the patient's owner_user_id."""
    patient = db.patients.get(visit["patient_id"])
    if patient is None or patient.get("owner_user_id") != g.user_id:
        raise err("ERR_FORBIDDEN", "not the owner")


# =============================================================================
# Entity common fields / mutation helpers
# =============================================================================
_seq_counter = [0]


def next_seq():
    _seq_counter[0] += 1
    return _seq_counter[0]


def stamp_new(obj, versioned=True):
    ts = now_iso()
    obj["id"] = obj.get("id") or new_id()
    obj["created_at"] = ts
    obj["_seq"] = next_seq()
    if versioned:
        obj["updated_at"] = ts
        obj["version"] = 1
    return obj


def touch(obj):
    """Mark a versioned resource as mutated."""
    obj["updated_at"] = now_iso()
    obj["version"] = obj.get("version", 0) + 1


# =============================================================================
# Serialization (strip private fields)
# =============================================================================
def serialize(obj):
    return {k: v for k, v in obj.items() if not k.startswith("_")}


# =============================================================================
# Lookups with existence ordering
# =============================================================================
def get_visit_or_404(visit_id):
    v = db.visits.get(visit_id)
    if v is None:
        raise err("ERR_NOT_FOUND", "visit not found")
    return v


def child_or_404(store, child_id, visit_id):
    c = store.get(child_id)
    if c is None or c.get("visit_id") != visit_id:
        raise err("ERR_NOT_FOUND", "child not found")
    return c


# =============================================================================
# Body parsing
# =============================================================================
def body():
    if request.data and len(request.data) > 0:
        data = request.get_json(silent=True)
        if data is None:
            raise err("ERR_INVALID_REQUEST", "invalid json")
        if not isinstance(data, dict):
            raise err("ERR_INVALID_REQUEST", "body must be object")
        return data
    return {}


# =============================================================================
# Invoice recompute (per-line tax)
# =============================================================================
def recompute_invoice(invoice, visit):
    subtotal = sum(cl["qty"] * cl["unit_price_cents"] for cl in invoice["charge_lines"])
    tax = sum(tax_of_line(cl["qty"] * cl["unit_price_cents"]) for cl in invoice["charge_lines"])
    deposit = sum(
        a["deposit_paid_cents"]
        for a in db.authorizations.values()
        if a["visit_id"] == visit["id"] and a["status"] == "ACTIVE"
    )
    invoice["subtotal_cents"] = subtotal
    invoice["tax_cents"] = tax
    invoice["deposit_applied_cents"] = deposit
    invoice["balance_due_cents"] = max(0, subtotal + tax - deposit)


def visit_invoice(visit_id):
    for inv in db.invoices.values():
        if inv["visit_id"] == visit_id:
            return inv
    return None


def recompute_authorized_ceiling(visit):
    total = sum(
        a["approved_ceiling_cents"]
        for a in db.authorizations.values()
        if a["visit_id"] == visit["id"] and a["status"] == "ACTIVE"
    )
    visit["authorized_ceiling_cents"] = total


# =============================================================================
# Error handler
# =============================================================================
@app.errorhandler(ApiError)
def handle_api_error(e):
    body_ = {
        "meta": meta(),
        "response_type": "error",
        "data": {"error_id": e.error_id, "message": e.message},
    }
    return jsonify(body_), e.http_status


@app.errorhandler(404)
def handle_404(e):
    body_ = {
        "meta": meta(),
        "response_type": "error",
        "data": {"error_id": "ERR_NOT_FOUND", "message": "not found"},
    }
    return jsonify(body_), 404


@app.errorhandler(405)
def handle_405(e):
    body_ = {
        "meta": meta(),
        "response_type": "error",
        "data": {"error_id": "ERR_NOT_FOUND", "message": "method not allowed"},
    }
    return jsonify(body_), 404


@app.errorhandler(Exception)
def handle_unexpected(e):
    if isinstance(e, ApiError):
        return handle_api_error(e)
    body_ = {
        "meta": meta(),
        "response_type": "error",
        "data": {"error_id": "ERR_INVALID_REQUEST", "message": str(e)},
    }
    return jsonify(body_), 400


# =============================================================================
# Clock endpoint
# =============================================================================
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    authenticate()
    require_role("TriageNurse", "ClinicianDVM", "FinanceCoordinator")
    data = body()
    to = data.get("to_iso8601")
    if not to:
        raise err("ERR_INVALID_REQUEST", "missing to_iso8601")
    parse_dt(to)  # validate
    db.clock = to
    return ok({}, 200)


# =============================================================================
# Patient
# =============================================================================
@app.route("/patients", methods=["POST"])
def create_patient():
    authenticate()
    require_role("TriageNurse", "FinanceCoordinator")
    data = body()
    name = data.get("name")
    species = data.get("species")
    weight = data.get("weight_kg")
    owner = data.get("owner_user_id")
    if name is None or not isinstance(name, str) or name == "":
        raise err("ERR_INVALID_REQUEST", "name required")
    if species not in SPECIES:
        raise err("ERR_INVALID_REQUEST", "bad species")
    if not isinstance(weight, (int, float)) or isinstance(weight, bool) or weight <= 0:
        raise err("ERR_INVALID_REQUEST", "weight_kg must be > 0")
    if owner is None or not isinstance(owner, str) or owner == "":
        raise err("ERR_INVALID_REQUEST", "owner_user_id required")
    p = {
        "name": name,
        "species": species,
        "weight_kg": weight,
        "owner_user_id": owner,
    }
    stamp_new(p)
    db.patients[p["id"]] = p
    return ok(serialize(p), 201)


@app.route("/patients/<pid>", methods=["GET"])
def get_patient(pid):
    authenticate()
    require_role("TriageNurse", "ClinicianDVM", "FinanceCoordinator", "Owner")
    p = db.patients.get(pid)
    if p is None:
        raise err("ERR_NOT_FOUND", "patient not found")
    if g.role == "Owner" and p.get("owner_user_id") != g.user_id:
        raise err("ERR_FORBIDDEN", "not the owner")
    return ok(serialize(p), 200)


@app.route("/patients/<pid>/visits", methods=["GET"])
def list_patient_visits(pid):
    authenticate()
    require_role("TriageNurse", "ClinicianDVM", "FinanceCoordinator", "Owner")
    p = db.patients.get(pid)
    if p is None:
        raise err("ERR_NOT_FOUND", "patient not found")
    if g.role == "Owner" and p.get("owner_user_id") != g.user_id:
        raise err("ERR_FORBIDDEN", "not the owner")
    return list_response(db.visits, lambda v: v["patient_id"] == pid)


# =============================================================================
# Visit
# =============================================================================
@app.route("/visits", methods=["POST"])
def create_visit():
    authenticate()
    require_role("TriageNurse")
    data = body()
    patient_id = data.get("patient_id")
    chief = data.get("chief_complaint")
    if patient_id is None or not isinstance(patient_id, str):
        raise err("ERR_INVALID_REQUEST", "patient_id required")
    if chief is None or not isinstance(chief, str):
        raise err("ERR_INVALID_REQUEST", "chief_complaint required")
    if patient_id not in db.patients:
        raise err("ERR_NOT_FOUND", "patient not found")
    v = {
        "patient_id": patient_id,
        "chief_complaint": chief,
        "triage_level": None,
        "department": "ER",
        "attending_dvm_id": None,
        "status": "REGISTERED",
        "authorized_ceiling_cents": 0,
        "charges_committed_cents": 0,
    }
    stamp_new(v)
    db.visits[v["id"]] = v
    # Create the single OPEN invoice
    inv = {
        "visit_id": v["id"],
        "charge_lines": [],
        "subtotal_cents": 0,
        "tax_cents": 0,
        "deposit_applied_cents": 0,
        "balance_due_cents": 0,
        "status": "OPEN",
    }
    stamp_new(inv)
    db.invoices[inv["id"]] = inv
    return ok(serialize(v), 201)


def read_access_visit(vid):
    """Auth + role + ownership for read on a visit and its children."""
    require_role("TriageNurse", "ClinicianDVM", "FinanceCoordinator", "Owner")
    v = get_visit_or_404(vid)
    if g.role == "Owner":
        require_owner_of(v)
    return v


@app.route("/visits/<vid>", methods=["GET"])
def get_visit(vid):
    authenticate()
    v = read_access_visit(vid)
    return ok(serialize(v), 200)


@app.route("/visits/<vid>/triage", methods=["POST"])
def triage_visit(vid):
    authenticate()
    require_role("TriageNurse")
    v = get_visit_or_404(vid)
    data = body()
    level = data.get("triage_level")
    if v["status"] != "REGISTERED":
        raise err("ERR_INVALID_STATE", "visit not REGISTERED")
    if level not in TRIAGE_LEVELS:
        raise err("ERR_INVALID_REQUEST", "bad triage_level")
    v["triage_level"] = level
    v["status"] = "TRIAGED"
    touch(v)
    return ok(serialize(v), 200)


@app.route("/visits/<vid>/begin-treatment", methods=["POST"])
def begin_treatment(vid):
    authenticate()
    require_role("ClinicianDVM")
    v = get_visit_or_404(vid)
    if v["status"] != "TRIAGED":
        raise err("ERR_INVALID_STATE", "visit not TRIAGED")
    has_active = any(
        a["visit_id"] == vid and a["status"] == "ACTIVE"
        for a in db.authorizations.values()
    )
    if not has_active:
        raise err("ERR_NO_ACTIVE_AUTH", "no active authorization")
    v["attending_dvm_id"] = g.user_id
    v["status"] = "IN_TREATMENT"
    touch(v)
    return ok(serialize(v), 200)


@app.route("/visits/<vid>/ready-for-discharge", methods=["POST"])
def ready_for_discharge(vid):
    authenticate()
    require_role("ClinicianDVM")
    v = get_visit_or_404(vid)
    if v["status"] != "IN_TREATMENT":
        raise err("ERR_INVALID_STATE", "visit not IN_TREATMENT")
    if any(h["visit_id"] == vid and h["status"] == "ACTIVE" for h in db.hospitalizations.values()):
        raise err("ERR_PATIENT_STILL_BOARDED", "active hospitalization")
    if any(p["visit_id"] == vid and p["status"] == "SCHEDULED" for p in db.procedures.values()):
        raise err("ERR_PROCEDURE_PENDING", "scheduled procedure pending")
    v["status"] = "READY_FOR_DISCHARGE"
    touch(v)
    return ok(serialize(v), 200)


@app.route("/visits/<vid>/discharge", methods=["POST"])
def discharge(vid):
    authenticate()
    require_role("ClinicianDVM")
    v = get_visit_or_404(vid)
    if v["status"] != "READY_FOR_DISCHARGE":
        raise err("ERR_INVALID_STATE", "visit not READY_FOR_DISCHARGE")
    inv = visit_invoice(vid)
    if inv is None or inv["status"] != "SETTLED":
        raise err("ERR_INVOICE_NOT_SETTLED", "invoice not settled")
    # cascade hop1: finalize invoice if not already FINALIZED (it may be SETTLED already)
    if inv["status"] == "OPEN":
        inv["charge_lines"] = list(inv["charge_lines"])
        recompute_invoice(inv, v)
        inv["status"] = "FINALIZED"
        touch(inv)
    # cascade hop2: generate ReferringVetReport
    data = body()
    report = {
        "visit_id": vid,
        "referring_dvm_email": data.get("referring_dvm_email"),
        "summary": data.get("summary"),
        "procedures_performed": [
            p["id"] for p in sorted(
                (pp for pp in db.procedures.values()
                 if pp["visit_id"] == vid and pp["status"] == "PERFORMED"),
                key=lambda r: (r["created_at"], r.get("_seq", 0)),
            )
        ],
        "total_billed_cents": inv["subtotal_cents"] + inv["tax_cents"],
    }
    stamp_new(report, versioned=False)
    db.reports[report["id"]] = report
    v["status"] = "DISCHARGED"
    touch(v)
    return ok(serialize(v), 200)


@app.route("/visits/<vid>/mark-deceased", methods=["POST"])
def mark_deceased(vid):
    authenticate()
    require_role("ClinicianDVM")
    v = get_visit_or_404(vid)
    if v["status"] != "IN_TREATMENT":
        raise err("ERR_INVALID_STATE", "visit not IN_TREATMENT")
    inv = visit_invoice(vid)
    # cascade: release ACTIVE hospitalizations
    active_hosps = sorted(
        (h for h in db.hospitalizations.values()
         if h["visit_id"] == vid and h["status"] == "ACTIVE"),
        key=lambda r: (r["created_at"], r.get("_seq", 0)),
    )
    for h in active_hosps:
        released_at = db.clock
        _release_hospitalization(h, v, inv, released_at)
    # cascade parallel: cancel SCHEDULED procedures
    sched_procs = sorted(
        (p for p in db.procedures.values()
         if p["visit_id"] == vid and p["status"] == "SCHEDULED"),
        key=lambda r: (r["created_at"], r.get("_seq", 0)),
    )
    for p in sched_procs:
        p["status"] = "CANCELLED"
        touch(p)
    v["status"] = "DECEASED"
    touch(v)
    return ok(serialize(v), 200)


@app.route("/visits/<vid>/mark-lwbs", methods=["POST"])
def mark_lwbs(vid):
    authenticate()
    require_role("TriageNurse")
    v = get_visit_or_404(vid)
    if v["status"] != "TRIAGED":
        raise err("ERR_INVALID_STATE", "visit not TRIAGED")
    if any(a["visit_id"] == vid and a["status"] == "ACTIVE" for a in db.authorizations.values()):
        raise err("ERR_VISIT_HAS_ACTIVE_AUTH", "active authorization exists")
    v["status"] = "LWBS"
    touch(v)
    return ok(serialize(v), 200)


# =============================================================================
# Referral
# =============================================================================
@app.route("/visits/<vid>/referrals", methods=["POST"])
def create_referral(vid):
    authenticate()
    require_role("ClinicianDVM")
    v = get_visit_or_404(vid)
    data = body()
    to_dept = data.get("to_department")
    accepting = data.get("accepting_dvm_id")
    reason = data.get("reason")
    if to_dept not in REFERRAL_DEPARTMENTS:
        raise err("ERR_INVALID_REQUEST", "bad to_department")
    if accepting is None or not isinstance(accepting, str):
        raise err("ERR_INVALID_REQUEST", "accepting_dvm_id required")
    if reason is None or not isinstance(reason, str):
        raise err("ERR_INVALID_REQUEST", "reason required")
    r = {
        "visit_id": vid,
        "to_department": to_dept,
        "accepting_dvm_id": accepting,
        "reason": reason,
        "status": "PENDING",
    }
    stamp_new(r)
    db.referrals[r["id"]] = r
    return ok(serialize(r), 201)


@app.route("/visits/<vid>/referrals", methods=["GET"])
def list_referrals(vid):
    authenticate()
    read_access_visit(vid)
    return list_response(db.referrals, lambda r: r["visit_id"] == vid)


@app.route("/visits/<vid>/referrals/<rid>/accept", methods=["POST"])
def accept_referral(vid, rid):
    authenticate()
    require_role("ClinicianDVM")
    v = get_visit_or_404(vid)
    r = child_or_404(db.referrals, rid, vid)
    if r["status"] != "PENDING":
        raise err("ERR_INVALID_STATE", "referral not PENDING")
    if v["status"] not in ("TRIAGED", "IN_TREATMENT"):
        raise err("ERR_VISIT_NOT_OPEN", "visit not open")
    r["status"] = "ACCEPTED"
    touch(r)
    v["department"] = r["to_department"]
    v["attending_dvm_id"] = r["accepting_dvm_id"]
    touch(v)
    return ok(serialize(r), 200)


@app.route("/visits/<vid>/referrals/<rid>/decline", methods=["POST"])
def decline_referral(vid, rid):
    authenticate()
    require_role("ClinicianDVM")
    get_visit_or_404(vid)
    r = child_or_404(db.referrals, rid, vid)
    if r["status"] != "PENDING":
        raise err("ERR_INVALID_STATE", "referral not PENDING")
    r["status"] = "DECLINED"
    touch(r)
    return ok(serialize(r), 200)


# =============================================================================
# Estimate
# =============================================================================
def compute_estimate_amounts(line_items, triage_level):
    subtotal_low = sum(li["qty"] * li["unit_price_cents"] for li in line_items)
    subtotal_high = ceil_dec(Decimal(subtotal_low) * (Decimal(1) + VARIANCE_UPLIFT))
    tax_low = sum(tax_of_line(li["qty"] * li["unit_price_cents"]) for li in line_items)
    tax_high = round_half_up(Decimal(subtotal_high) * TAX_RATE)
    low_cents = subtotal_low + tax_low
    high_cents = subtotal_high + tax_high
    if triage_level is not None:
        deposit_pct = DEPOSIT_TIER[triage_level]
        deposit_cents = ceil_dec(Decimal(high_cents) * deposit_pct)
        deposit_pct_out = DEPOSIT_TIER_FLOAT[triage_level]
    else:
        deposit_pct_out = None
        deposit_cents = None
    return low_cents, high_cents, deposit_pct_out, deposit_cents


@app.route("/visits/<vid>/estimates", methods=["POST"])
def create_estimate(vid):
    authenticate()
    require_role("FinanceCoordinator")
    v = get_visit_or_404(vid)
    data = body()
    line_items = data.get("line_items")
    if not isinstance(line_items, list) or len(line_items) == 0:
        raise err("ERR_INVALID_REQUEST", "line_items required")
    clean = []
    for li in line_items:
        if not isinstance(li, dict):
            raise err("ERR_INVALID_REQUEST", "bad line item")
        code = li.get("code")
        desc = li.get("description")
        qty = li.get("qty")
        price = li.get("unit_price_cents")
        if not isinstance(qty, int) or isinstance(qty, bool) or qty <= 0:
            raise err("ERR_INVALID_REQUEST", "qty must be positive int")
        if not isinstance(price, int) or isinstance(price, bool) or price < 0:
            raise err("ERR_INVALID_REQUEST", "unit_price_cents must be non-negative int")
        clean.append({
            "code": code,
            "description": desc,
            "qty": qty,
            "unit_price_cents": price,
        })
    low, high, dpct, dcents = compute_estimate_amounts(clean, v["triage_level"])
    e = {
        "visit_id": vid,
        "line_items": clean,
        "low_cents": low,
        "high_cents": high,
        "deposit_pct": dpct,
        "deposit_cents": dcents,
        "status": "DRAFT",
    }
    stamp_new(e)
    db.estimates[e["id"]] = e
    return ok(serialize(e), 201)


@app.route("/visits/<vid>/estimates", methods=["GET"])
def list_estimates(vid):
    authenticate()
    read_access_visit(vid)
    return list_response(db.estimates, lambda e: e["visit_id"] == vid)


@app.route("/visits/<vid>/estimates/<eid>", methods=["GET"])
def get_estimate(vid, eid):
    authenticate()
    read_access_visit(vid)
    e = child_or_404(db.estimates, eid, vid)
    return ok(serialize(e), 200)


@app.route("/visits/<vid>/estimates/<eid>/issue", methods=["POST"])
def issue_estimate(vid, eid):
    authenticate()
    require_role("FinanceCoordinator")
    v = get_visit_or_404(vid)
    e = child_or_404(db.estimates, eid, vid)
    data = body()
    if e["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "estimate not DRAFT")
    if v["triage_level"] is None:
        raise err("ERR_VISIT_NOT_TRIAGED", "visit not triaged")
    # OCC check
    expected = data.get("expected_visit_version")
    if expected is not None and expected != v["version"]:
        raise err("ERR_STALE_VERSION", "stale visit version")
    # freeze amounts using current triage level
    low, high, dpct, dcents = compute_estimate_amounts(e["line_items"], v["triage_level"])
    e["low_cents"] = low
    e["high_cents"] = high
    e["deposit_pct"] = dpct
    e["deposit_cents"] = dcents
    e["status"] = "ISSUED"
    touch(e)
    # supersede other ISSUED estimates on the visit
    for other in db.estimates.values():
        if other["id"] != eid and other["visit_id"] == vid and other["status"] == "ISSUED":
            other["status"] = "SUPERSEDED"
            touch(other)
    touch(v)
    return ok(serialize(e), 200)


# =============================================================================
# Authorization
# =============================================================================
@app.route("/visits/<vid>/authorizations", methods=["POST"])
def create_authorization(vid):
    authenticate()
    require_role("FinanceCoordinator")
    get_visit_or_404(vid)
    data = body()
    estimate_id = data.get("estimate_id")
    ceiling = data.get("approved_ceiling_cents")
    if estimate_id is None or not isinstance(estimate_id, str):
        raise err("ERR_INVALID_REQUEST", "estimate_id required")
    if not isinstance(ceiling, int) or isinstance(ceiling, bool) or ceiling < 0:
        raise err("ERR_INVALID_REQUEST", "approved_ceiling_cents required")
    est = db.estimates.get(estimate_id)
    if est is None or est["visit_id"] != vid:
        raise err("ERR_NOT_FOUND", "estimate not found")
    a = {
        "visit_id": vid,
        "estimate_id": estimate_id,
        "approved_ceiling_cents": ceiling,
        "deposit_paid_cents": 0,
        "status": "PENDING",
    }
    stamp_new(a)
    db.authorizations[a["id"]] = a
    return ok(serialize(a), 201)


@app.route("/visits/<vid>/authorizations", methods=["GET"])
def list_authorizations(vid):
    authenticate()
    read_access_visit(vid)
    return list_response(db.authorizations, lambda a: a["visit_id"] == vid)


@app.route("/authorizations/<aid>", methods=["GET"])
def get_authorization(aid):
    authenticate()
    require_role("TriageNurse", "ClinicianDVM", "FinanceCoordinator", "Owner")
    a = db.authorizations.get(aid)
    if a is None:
        raise err("ERR_NOT_FOUND", "authorization not found")
    if g.role == "Owner":
        v = db.visits.get(a["visit_id"])
        require_owner_of(v)
    return ok(serialize(a), 200)


@app.route("/authorizations", methods=["GET"])
def list_authorizations_top():
    authenticate()
    require_role("TriageNurse", "ClinicianDVM", "FinanceCoordinator", "Owner")
    estimate_id = request.args.get("estimate_id")

    def flt(a):
        if estimate_id is not None and a["estimate_id"] != estimate_id:
            return False
        if g.role == "Owner":
            v = db.visits.get(a["visit_id"])
            p = db.patients.get(v["patient_id"]) if v else None
            if p is None or p.get("owner_user_id") != g.user_id:
                return False
        return True

    return list_response(db.authorizations, flt)


@app.route("/visits/<vid>/authorizations/<aid>/approve", methods=["POST"])
def approve_authorization(vid, aid):
    authenticate()
    require_role("Owner")
    v = get_visit_or_404(vid)
    require_owner_of(v)
    a = child_or_404(db.authorizations, aid, vid)
    if a["status"] != "PENDING":
        raise err("ERR_INVALID_STATE", "authorization not PENDING")
    est = db.estimates.get(a["estimate_id"])
    if est is None or est["status"] != "ISSUED":
        raise err("ERR_ESTIMATE_NOT_ISSUED", "estimate not issued")
    if a["approved_ceiling_cents"] < est["high_cents"]:
        raise err("ERR_CEILING_BELOW_ESTIMATE", "ceiling below estimate high")
    # transition
    a["status"] = "ACTIVE"
    a["deposit_paid_cents"] = est["deposit_cents"]
    touch(a)
    # estimate ISSUED -> CONSUMED
    est["status"] = "CONSUMED"
    touch(est)
    # recompute ceiling
    recompute_authorized_ceiling(v)
    # credit deposit into invoice
    inv = visit_invoice(vid)
    if inv is not None:
        recompute_invoice(inv, v)
        touch(inv)
    touch(v)
    return ok(serialize(a), 200)


@app.route("/visits/<vid>/authorizations/<aid>/decline", methods=["POST"])
def decline_authorization(vid, aid):
    authenticate()
    require_role("Owner")
    v = get_visit_or_404(vid)
    require_owner_of(v)
    a = child_or_404(db.authorizations, aid, vid)
    if a["status"] != "PENDING":
        raise err("ERR_INVALID_STATE", "authorization not PENDING")
    a["status"] = "DECLINED"
    touch(a)
    est = db.estimates.get(a["estimate_id"])
    if est is not None and est["status"] == "ISSUED":
        est["status"] = "SUPERSEDED"
        touch(est)
    return ok(serialize(a), 200)


@app.route("/visits/<vid>/authorizations/<aid>/void", methods=["POST"])
def void_authorization(vid, aid):
    authenticate()
    require_role("FinanceCoordinator")
    v = get_visit_or_404(vid)
    a = child_or_404(db.authorizations, aid, vid)
    if a["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "authorization not ACTIVE")
    remaining_ceiling = v["authorized_ceiling_cents"] - a["approved_ceiling_cents"]
    if v["charges_committed_cents"] > remaining_ceiling:
        raise err("ERR_CEILING_BELOW_COMMITTED", "void would strand committed charges")
    a["status"] = "VOIDED"
    touch(a)
    recompute_authorized_ceiling(v)
    inv = visit_invoice(vid)
    if inv is not None:
        recompute_invoice(inv, v)
        touch(inv)
    touch(v)
    return ok(serialize(a), 200)


# =============================================================================
# Hospitalization
# =============================================================================
@app.route("/visits/<vid>/hospitalizations", methods=["POST"])
def create_hospitalization(vid):
    authenticate()
    require_role("ClinicianDVM")
    get_visit_or_404(vid)
    data = body()
    ward = data.get("ward")
    cage = data.get("cage_number")
    admit = data.get("admit_at")
    planned = data.get("planned_discharge_at")
    if ward not in WARDS:
        raise err("ERR_INVALID_REQUEST", "bad ward")
    if not isinstance(cage, int) or isinstance(cage, bool):
        raise err("ERR_INVALID_REQUEST", "cage_number required")
    if admit is None or planned is None:
        raise err("ERR_INVALID_REQUEST", "admit_at/planned_discharge_at required")
    admit_dt = parse_dt(admit)
    planned_dt = parse_dt(planned)
    if not (admit_dt < planned_dt):
        raise err("ERR_INVALID_REQUEST", "admit_at must be before planned_discharge_at")
    # priority 7: cage occupancy (temporal)
    occupied = any(
        h["visit_id"] is not None and h["ward"] == ward and h["cage_number"] == cage
        and h["status"] == "ACTIVE"
        for h in db.hospitalizations.values()
    )
    if occupied:
        raise err("ERR_CAGE_OCCUPIED", "cage occupied")
    # priority 8: cage range for ICU
    if ward == "ICU" and not (1 <= cage <= ICU_CAPACITY):
        raise err("ERR_CAGE_OUT_OF_RANGE", "cage out of range")
    h = {
        "visit_id": vid,
        "ward": ward,
        "cage_number": cage,
        "admit_at": admit,
        "planned_discharge_at": planned,
        "released_at": None,
        "nights_accrued": None,
        "board_cents": None,
        "status": "ACTIVE",
    }
    stamp_new(h)
    db.hospitalizations[h["id"]] = h
    return ok(serialize(h), 201)


@app.route("/visits/<vid>/hospitalizations", methods=["GET"])
def list_hospitalizations(vid):
    authenticate()
    read_access_visit(vid)
    return list_response(db.hospitalizations, lambda h: h["visit_id"] == vid)


def _release_hospitalization(h, v, inv, released_at):
    """Perform release accrual + invoice posting. Assumes preconditions met."""
    admit_dt = parse_dt(h["admit_at"])
    rel_dt = parse_dt(released_at)
    hours = (rel_dt - admit_dt).total_seconds() / 3600.0
    nights = max(1, ceil_dec(Decimal(hours) / Decimal(24)))
    board = nights * PER_DIEM[h["ward"]]
    h["released_at"] = released_at
    h["nights_accrued"] = nights
    h["board_cents"] = board
    h["status"] = "RELEASED"
    touch(h)
    if inv is not None:
        inv["charge_lines"].append({
            "source_type": "HOSPITALIZATION",
            "source_id": h["id"],
            "qty": 1,
            "unit_price_cents": board,
        })
        recompute_invoice(inv, v)
        touch(inv)
    v["charges_committed_cents"] += board


@app.route("/visits/<vid>/hospitalizations/<hid>/release", methods=["POST"])
def release_hospitalization(vid, hid):
    authenticate()
    require_role("ClinicianDVM")
    v = get_visit_or_404(vid)
    h = child_or_404(db.hospitalizations, hid, vid)
    data = body()
    released_at = data.get("released_at")
    if h["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "hospitalization not ACTIVE")
    if released_at is None:
        raise err("ERR_INVALID_REQUEST", "released_at required")
    rel_dt = parse_dt(released_at)
    admit_dt = parse_dt(h["admit_at"])
    if not (rel_dt > admit_dt):
        raise err("ERR_INVALID_REQUEST", "released_at must be after admit_at")
    inv = visit_invoice(vid)
    _release_hospitalization(h, v, inv, released_at)
    touch(v)
    return ok(serialize(h), 200)


@app.route("/visits/<vid>/hospitalizations/<hid>/cancel", methods=["POST"])
def cancel_hospitalization(vid, hid):
    authenticate()
    require_role("ClinicianDVM")
    v = get_visit_or_404(vid)
    h = child_or_404(db.hospitalizations, hid, vid)
    if h["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "hospitalization not ACTIVE")
    h["status"] = "CANCELLED"
    touch(h)
    touch(v)
    return ok(serialize(h), 200)


# =============================================================================
# Procedure
# =============================================================================
def intervals_overlap(s1, e1, s2, e2):
    # half-open [start, end)
    return s1 < e2 and s2 < e1


@app.route("/visits/<vid>/procedures", methods=["POST"])
def create_procedure(vid):
    authenticate()
    require_role("ClinicianDVM")
    get_visit_or_404(vid)
    data = body()
    modality = data.get("modality")
    room = data.get("resource_room")
    start = data.get("start_at")
    end = data.get("end_at")
    price = data.get("price_cents")
    if modality not in MODALITIES:
        raise err("ERR_INVALID_REQUEST", "bad modality")
    if room not in RESOURCE_ROOMS:
        raise err("ERR_INVALID_REQUEST", "bad resource_room")
    if start is None or end is None:
        raise err("ERR_INVALID_REQUEST", "start_at/end_at required")
    if not isinstance(price, int) or isinstance(price, bool) or price < 0:
        raise err("ERR_INVALID_REQUEST", "price_cents must be non-negative int")
    start_dt = parse_dt(start)
    end_dt = parse_dt(end)
    if not (start_dt < end_dt):
        raise err("ERR_INVALID_REQUEST", "start_at must be before end_at")
    # priority 7: double booking (temporal) — checked before structural constraint
    for p in db.procedures.values():
        if p["resource_room"] == room and p["status"] in ("SCHEDULED", "PERFORMED"):
            if intervals_overlap(start_dt, end_dt, parse_dt(p["start_at"]), parse_dt(p["end_at"])):
                raise err("ERR_RESOURCE_DOUBLE_BOOKED", "resource double booked")
    # priority 8: modality/room family match (structural)
    if room not in MODALITY_ROOM[modality]:
        raise err("ERR_MODALITY_ROOM_MISMATCH", "modality/room mismatch")
    p = {
        "visit_id": vid,
        "modality": modality,
        "resource_room": room,
        "start_at": start,
        "end_at": end,
        "price_cents": price,
        "status": "SCHEDULED",
    }
    stamp_new(p)
    db.procedures[p["id"]] = p
    return ok(serialize(p), 201)


@app.route("/visits/<vid>/procedures", methods=["GET"])
def list_procedures(vid):
    authenticate()
    read_access_visit(vid)
    return list_response(db.procedures, lambda p: p["visit_id"] == vid)


@app.route("/visits/<vid>/procedures/<pid>/perform", methods=["POST"])
def perform_procedure(vid, pid):
    authenticate()
    require_role("ClinicianDVM")
    v = get_visit_or_404(vid)
    p = child_or_404(db.procedures, pid, vid)
    if p["status"] != "SCHEDULED":
        raise err("ERR_INVALID_STATE", "procedure not SCHEDULED")
    if v["charges_committed_cents"] + p["price_cents"] > v["authorized_ceiling_cents"]:
        raise err("ERR_CEILING_EXCEEDED", "ceiling exceeded")
    p["status"] = "PERFORMED"
    touch(p)
    inv = visit_invoice(vid)
    if inv is not None:
        inv["charge_lines"].append({
            "source_type": "PROCEDURE",
            "source_id": p["id"],
            "qty": 1,
            "unit_price_cents": p["price_cents"],
        })
        recompute_invoice(inv, v)
        touch(inv)
    v["charges_committed_cents"] += p["price_cents"]
    touch(v)
    return ok(serialize(p), 200)


@app.route("/visits/<vid>/procedures/<pid>/cancel", methods=["POST"])
def cancel_procedure(vid, pid):
    authenticate()
    require_role("ClinicianDVM")
    v = get_visit_or_404(vid)
    p = child_or_404(db.procedures, pid, vid)
    if p["status"] != "SCHEDULED":
        raise err("ERR_INVALID_STATE", "procedure not SCHEDULED")
    p["status"] = "CANCELLED"
    touch(p)
    touch(v)
    return ok(serialize(p), 200)


# =============================================================================
# Invoice
# =============================================================================
@app.route("/visits/<vid>/invoice", methods=["GET"])
def get_invoice(vid):
    authenticate()
    read_access_visit(vid)
    return list_response(db.invoices, lambda i: i["visit_id"] == vid)


@app.route("/visits/<vid>/invoice/finalize", methods=["POST"])
def finalize_invoice(vid):
    authenticate()
    require_role("FinanceCoordinator")
    v = get_visit_or_404(vid)
    inv = visit_invoice(vid)
    if inv is None:
        raise err("ERR_NOT_FOUND", "invoice not found")
    if inv["status"] != "OPEN":
        raise err("ERR_INVALID_STATE", "invoice not OPEN")
    if any(p["visit_id"] == vid and p["status"] == "SCHEDULED" for p in db.procedures.values()):
        raise err("ERR_CHARGES_PENDING", "scheduled procedure pending")
    if any(h["visit_id"] == vid and h["status"] == "ACTIVE" for h in db.hospitalizations.values()):
        raise err("ERR_CHARGES_PENDING", "active hospitalization pending")
    recompute_invoice(inv, v)
    inv["status"] = "FINALIZED"
    touch(inv)
    touch(v)
    return ok(serialize(inv), 200)


@app.route("/visits/<vid>/invoice/pay", methods=["POST"])
def pay_invoice(vid):
    authenticate()
    require_role("FinanceCoordinator")
    v = get_visit_or_404(vid)
    inv = visit_invoice(vid)
    if inv is None:
        raise err("ERR_NOT_FOUND", "invoice not found")
    data = body()
    amount = data.get("amount_cents")
    if inv["status"] != "FINALIZED":
        raise err("ERR_INVALID_STATE", "invoice not FINALIZED")
    if not isinstance(amount, int) or isinstance(amount, bool) or amount < 0:
        raise err("ERR_INVALID_REQUEST", "amount_cents required")
    if amount < inv["balance_due_cents"]:
        raise err("ERR_PAYMENT_INSUFFICIENT", "amount below balance due")
    inv["status"] = "SETTLED"
    touch(inv)
    touch(v)
    return ok(serialize(inv), 200)


# =============================================================================
# PaymentPlan
# =============================================================================
def compute_plan_schedule(principal, provider, term_months):
    promo = (
        provider == "CARECREDIT"
        and principal >= PROMO_MIN_CENTS
        and term_months <= PROMO_MAX_MONTHS
    )
    if promo:
        fee = 0
    else:
        fee = ceil_dec(Decimal(principal) * APR_MONTHLY * Decimal(term_months))
    total = principal + fee
    installment = ceil_dec(Decimal(total) / Decimal(term_months))
    final = total - installment * (term_months - 1)
    return promo, fee, installment, final


@app.route("/visits/<vid>/payment-plans", methods=["POST"])
def create_payment_plan(vid):
    authenticate()
    require_role("FinanceCoordinator")
    get_visit_or_404(vid)
    data = body()
    invoice_id = data.get("invoice_id")
    provider = data.get("provider")
    term = data.get("term_months")
    if invoice_id is None or not isinstance(invoice_id, str):
        raise err("ERR_INVALID_REQUEST", "invoice_id required")
    if provider not in PROVIDERS:
        raise err("ERR_INVALID_REQUEST", "bad provider")
    if not isinstance(term, int) or isinstance(term, bool) or term < 1 or term > 24:
        raise err("ERR_INVALID_REQUEST", "term_months must be 1..24")
    inv = db.invoices.get(invoice_id)
    if inv is None or inv["visit_id"] != vid:
        raise err("ERR_NOT_FOUND", "invoice not found")
    principal = inv["balance_due_cents"]
    promo, fee, installment, final = compute_plan_schedule(principal, provider, term)
    plan = {
        "visit_id": vid,
        "invoice_id": invoice_id,
        "provider": provider,
        "principal_cents": principal,
        "term_months": term,
        "promo_applied": promo,
        "financing_fee_cents": fee,
        "installment_cents": installment,
        "final_installment_cents": final,
        "status": "PROPOSED",
    }
    stamp_new(plan)
    db.payment_plans[plan["id"]] = plan
    return ok(serialize(plan), 201)


@app.route("/visits/<vid>/payment-plans", methods=["GET"])
def list_payment_plans(vid):
    authenticate()
    require_role("FinanceCoordinator", "Owner")
    v = get_visit_or_404(vid)
    if g.role == "Owner":
        require_owner_of(v)
    return list_response(db.payment_plans, lambda p: p["visit_id"] == vid)


@app.route("/payment-plans/<ppid>", methods=["GET"])
def get_payment_plan(ppid):
    authenticate()
    require_role("FinanceCoordinator", "Owner")
    plan = db.payment_plans.get(ppid)
    if plan is None:
        raise err("ERR_NOT_FOUND", "payment plan not found")
    if g.role == "Owner":
        v = db.visits.get(plan["visit_id"])
        require_owner_of(v)
    return ok(serialize(plan), 200)


@app.route("/payment-plans", methods=["GET"])
def list_payment_plans_top():
    authenticate()
    require_role("FinanceCoordinator", "Owner")
    invoice_id = request.args.get("invoice_id")

    def flt(p):
        if invoice_id is not None and p["invoice_id"] != invoice_id:
            return False
        if g.role == "Owner":
            v = db.visits.get(p["visit_id"])
            pat = db.patients.get(v["patient_id"]) if v else None
            if pat is None or pat.get("owner_user_id") != g.user_id:
                return False
        return True

    return list_response(db.payment_plans, flt)


@app.route("/visits/<vid>/payment-plans/<ppid>/activate", methods=["POST"])
def activate_payment_plan(vid, ppid):
    authenticate()
    require_role("FinanceCoordinator")
    v = get_visit_or_404(vid)
    plan = child_or_404(db.payment_plans, ppid, vid)
    data = body()
    if plan["status"] != "PROPOSED":
        raise err("ERR_INVALID_STATE", "plan not PROPOSED")
    inv = db.invoices.get(plan["invoice_id"])
    # If another ACTIVE plan already links this invoice, that is the governing
    # error even though that first activation moved the invoice to SETTLED.
    if any(
        pp["id"] != ppid and pp["invoice_id"] == plan["invoice_id"] and pp["status"] == "ACTIVE"
        for pp in db.payment_plans.values()
    ):
        raise err("ERR_PLAN_ALREADY_ACTIVE", "another plan already active")
    if inv is None or inv["status"] != "FINALIZED":
        raise err("ERR_INVOICE_NOT_FINALIZED", "invoice not finalized")
    expected = data.get("expected_visit_version")
    if expected is not None and expected != v["version"]:
        raise err("ERR_STALE_VERSION", "stale visit version")
    plan["status"] = "ACTIVE"
    touch(plan)
    inv["status"] = "SETTLED"
    touch(inv)
    touch(v)
    return ok(serialize(plan), 200)


@app.route("/visits/<vid>/payment-plans/<ppid>/cancel", methods=["POST"])
def cancel_payment_plan(vid, ppid):
    authenticate()
    require_role("FinanceCoordinator")
    get_visit_or_404(vid)
    plan = child_or_404(db.payment_plans, ppid, vid)
    if plan["status"] != "PROPOSED":
        raise err("ERR_INVALID_STATE", "plan not PROPOSED")
    plan["status"] = "CANCELLED"
    touch(plan)
    return ok(serialize(plan), 200)


# =============================================================================
# ReferringVetReport
# =============================================================================
@app.route("/visits/<vid>/referring-vet-reports", methods=["GET"])
def list_reports(vid):
    authenticate()
    require_role("ClinicianDVM", "FinanceCoordinator", "Owner")
    v = get_visit_or_404(vid)
    if g.role == "Owner":
        require_owner_of(v)
    return list_response(db.reports, lambda r: r["visit_id"] == vid)


# =============================================================================
# Main
# =============================================================================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
