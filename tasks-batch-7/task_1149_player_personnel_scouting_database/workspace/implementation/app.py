"""Player Personnel & Scouting API — single-file Flask implementation.

Built to the PRD/scaffold contract:
- Envelope: {meta:{api_request_id,api_request_timestamp[,limit,offset,total_count,has_more]}, response_type, data}
- Errors:   {meta:{api_request_id,api_request_timestamp}, response_type:"error", data:{error_id,message}}
- Auth:     X-User-ID + X-User-Role headers; roles AreaScout/ScoutingDirector (entity-backed by Scout.level),
            MedicalStaff/GeneralManager (opaque)
- OCC:      expected_board_version on reorder; expected_budget_version on adjustments
- Logical clock: POST /_clock/set_current_utc; default 2026-05-01T00:00:00Z; never wall-clock.
- Store:    fully in-memory; starts empty on every boot.
"""

import os
import re
import uuid
import math
import threading
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation

from flask import Flask, request, jsonify

# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

_CLOCK_LOCK = threading.Lock()
_CLOCK_CURRENT = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)


def now_utc():
    with _CLOCK_LOCK:
        return _CLOCK_CURRENT


def set_clock(dt):
    global _CLOCK_CURRENT
    with _CLOCK_LOCK:
        _CLOCK_CURRENT = dt


def iso_now():
    return iso_fmt(now_utc())


def iso_fmt(dt):
    # ISO 8601 UTC with exactly three fractional digits, 'Z' suffix
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_iso(s):
    """Parse ISO 8601 into aware datetime (UTC). Raises ValueError on bad input."""
    if not isinstance(s, str):
        raise ValueError("not a string")
    txt = s.strip()
    # Accept trailing Z or explicit offset
    m = re.match(
        r"^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.(\d+))?(Z|[+-]\d{2}:?\d{2})?$",
        txt,
    )
    if not m:
        raise ValueError("bad iso8601")
    y, mo, d, h, mi, sec = (int(m.group(i)) for i in range(1, 7))
    frac = m.group(7)
    micro = 0
    if frac:
        frac = (frac + "000000")[:6]
        micro = int(frac)
    off = m.group(8)
    if off in (None, "Z"):
        tz = timezone.utc
    else:
        sign = 1 if off[0] == "+" else -1
        digits = off[1:].replace(":", "")
        oh, om = int(digits[:2]), int(digits[2:4])
        tz = timezone(sign * timedelta(hours=oh, minutes=om))
    try:
        dt = datetime(y, mo, d, h, mi, sec, micro, tzinfo=tz)
    except ValueError:
        raise ValueError("bad datetime")
    return dt.astimezone(timezone.utc)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class ApiError(Exception):
    def __init__(self, error_id, message, http_status):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


def err_unauthenticated(msg="Authentication headers missing or role undeclared"):
    return ApiError("ERR_UNAUTHENTICATED", msg, 401)


def err_forbidden(msg="Role not permitted on this endpoint"):
    return ApiError("ERR_FORBIDDEN", msg, 403)


def err_validation(msg="Request validation failed"):
    return ApiError("ERR_VALIDATION", msg, 400)


def err_not_found(msg="Referenced resource does not exist"):
    return ApiError("ERR_NOT_FOUND", msg, 404)


# ---------------------------------------------------------------------------
# In-memory store
# ---------------------------------------------------------------------------


class Store:
    def __init__(self):
        self.scouts = {}            # id -> dict
        self.prospects = {}
        self.reports = {}
        self.video_tags = {}
        self.flags = {}
        self.boards = {}
        self.entries = {}
        self.needs = {}
        self.targets = {}
        self.budgets = {}
        self.interviews = {}
        self.facilities = {}
        self.bookings = {}
        self.outcomes = {}


DB = Store()


# ---------------------------------------------------------------------------
# Envelope helpers
# ---------------------------------------------------------------------------


def _meta(pagination=None):
    m = {
        "api_request_id": "req_" + uuid.uuid4().hex[:20],
        "api_request_timestamp": iso_now(),
    }
    if pagination is not None:
        m["limit"] = pagination["limit"]
        m["offset"] = pagination["offset"]
        m["total_count"] = pagination["total_count"]
        m["has_more"] = pagination["has_more"]
    return m


def ok_object(data, http_status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), http_status


def ok_list(items, limit, offset, total_count, http_status=200):
    has_more = (offset + len(items)) < total_count
    pag = {"limit": limit, "offset": offset, "total_count": total_count, "has_more": has_more}
    body = {"meta": _meta(pag), "response_type": "array", "data": items}
    return jsonify(body), http_status


def error_response(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


# ---------------------------------------------------------------------------
# Decimal helpers
# ---------------------------------------------------------------------------

TWO_PLACES = Decimal("0.01")


def dec2(value):
    """Round a Decimal/numeric to 2 places, half-up."""
    return Decimal(str(value)).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


def to_decimal(value):
    """Coerce incoming JSON number to Decimal; raise ValueError if invalid."""
    if isinstance(value, bool):
        raise ValueError("bool not numeric")
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        return Decimal(str(value))
    if isinstance(value, str):
        try:
            return Decimal(value)
        except InvalidOperation:
            raise ValueError("bad decimal")
    if isinstance(value, Decimal):
        return value
    raise ValueError("bad numeric")


def decimal_places(d):
    """Number of decimal places in a Decimal's canonical representation."""
    tup = d.normalize().as_tuple()
    if tup.exponent >= 0:
        return 0
    return -tup.exponent


def num_out(d):
    """Serialize a Decimal to a JSON float with 2 decimal places."""
    return float(dec2(d))


# ---------------------------------------------------------------------------
# Auth / RBAC
# ---------------------------------------------------------------------------

ROLES = {"AreaScout", "ScoutingDirector", "MedicalStaff", "GeneralManager"}


class Caller:
    def __init__(self, user_id, role, scout=None):
        self.user_id = user_id
        self.role = role
        self.scout = scout


def authenticate():
    """Priority-1 auth check."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise err_unauthenticated()
    scout = None
    if role == "AreaScout":
        scout = DB.scouts.get(user_id)
        if scout is None or scout["level"] != "AREA":
            raise err_forbidden("AreaScout identity must resolve to a Scout with level AREA")
    elif role == "ScoutingDirector":
        scout = DB.scouts.get(user_id)
        if scout is None or scout["level"] != "DIRECTOR":
            raise err_forbidden("ScoutingDirector identity must resolve to a Scout with level DIRECTOR")
    return Caller(user_id, role, scout)


def require_roles(caller, *roles):
    if caller.role not in roles:
        raise err_forbidden()


# ---------------------------------------------------------------------------
# Request body helpers
# ---------------------------------------------------------------------------


def body():
    if not request.is_json:
        return {}
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


def req_field(data, name):
    if name not in data or data[name] is None:
        raise err_validation(f"Missing required field: {name}")
    return data[name]


def opt_field(data, name, default=None):
    v = data.get(name, default)
    return default if v is None else v


def as_string(v, name):
    if not isinstance(v, str):
        raise err_validation(f"{name} must be a string")
    return v


def as_int(v, name, minimum=None):
    if isinstance(v, bool) or not isinstance(v, int):
        raise err_validation(f"{name} must be an integer")
    if minimum is not None and v < minimum:
        raise err_validation(f"{name} must be >= {minimum}")
    return v


def as_bool(v, name):
    if not isinstance(v, bool):
        raise err_validation(f"{name} must be a boolean")
    return v


def as_enum(v, name, allowed):
    if not isinstance(v, str) or v not in allowed:
        raise err_validation(f"{name} must be one of {sorted(allowed)}")
    return v


def as_number_decimal(v, name):
    """Coerce to Decimal; reject booleans/strings-that-arent-numbers."""
    try:
        return to_decimal(v)
    except ValueError:
        raise err_validation(f"{name} must be a number")


def parse_pagination():
    """limit/offset with defaults 10/0, bounds 1..100 / >=0."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except ValueError:
            raise err_validation("limit must be an integer")
        if limit < 1 or limit > 100:
            raise err_validation("limit out of range [1,100]")
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except ValueError:
            raise err_validation("offset must be an integer")
        if offset < 0:
            raise err_validation("offset must be >= 0")
    return limit, offset


def paginate(items, limit, offset):
    total = len(items)
    page = items[offset:offset + limit]
    return page, total


def new_id():
    return str(uuid.uuid4())


def stamp_new(record):
    ts = iso_now()
    record["id"] = new_id()
    record["created_at"] = ts
    record["updated_at"] = ts
    record["version"] = 1
    return record


def touch(record):
    record["updated_at"] = iso_now()
    record["version"] += 1


# ---------------------------------------------------------------------------
# Calculations
# ---------------------------------------------------------------------------

CENTER = Decimal("5.0")
SCALE = Decimal("1.5")
MIN_G = Decimal("1.0")
MAX_G = Decimal("9.0")

T1_MIN = Decimal("8.00")
T2_MIN = Decimal("7.00")
T3_MIN = Decimal("6.00")

DEFAULT_BASE = Decimal("20.0")
MEDICAL_HIGH_MULT = Decimal("0.8")
CHAR_DEDUCTION = Decimal("15.0")
BASE_NEED = {
    "P1": Decimal("90.0"),
    "P2": Decimal("70.0"),
    "P3": Decimal("50.0"),
    "P4": Decimal("30.0"),
}

POSTURE_FRACTION = Decimal("0.10")

HIT_GRADE_MIN = Decimal("7.00")
HIT_OUTCOME_MIN = 70
RMSE_PENALTY = Decimal("10")


def compute_normalized_grade(report, scout):
    """Provisional vs final variant, pinned at lock time."""
    if scout.get("locked_grade_mean") is not None:
        mean = Decimal(str(scout["locked_grade_mean"]))
        stdev = Decimal(str(scout["locked_grade_stdev"]))
    else:
        mean = Decimal(str(scout["season_grade_mean"]))
        stdev = Decimal(str(scout["season_grade_stdev"]))
    raw = Decimal(str(report["raw_grade"]))
    z = (raw - mean) / stdev
    normalized = CENTER + SCALE * z
    normalized = dec2(normalized)  # round before clamp
    if normalized < MIN_G:
        normalized = MIN_G
    if normalized > MAX_G:
        normalized = MAX_G
    return normalized


def locked_reports_for(prospect_id):
    return [r for r in DB.reports.values()
            if r["prospect_id"] == prospect_id and r["status"] == "LOCKED"]


def recompute_prospect_composite(prospect):
    """Round per report first, then sum and round again (pinned order)."""
    locked = locked_reports_for(prospect["id"])
    if not locked:
        prospect["composite_grade"] = None
        prospect["tier"] = None
        return
    total_w = Decimal(0)
    for r in locked:
        total_w += Decimal(str(DB.scouts[r["scout_id"]]["weight"]))
    comp = Decimal(0)
    for r in locked:
        w = Decimal(str(DB.scouts[r["scout_id"]]["weight"])) / total_w
        contrib = dec2(w * Decimal(str(r["normalized_grade"])))
        comp += contrib
    composite = dec2(comp)
    prospect["composite_grade"] = num_out(composite)
    if composite >= T1_MIN:
        prospect["tier"] = "T1"
    elif composite >= T2_MIN:
        prospect["tier"] = "T2"
    elif composite >= T3_MIN:
        prospect["tier"] = "T3"
    else:
        prospect["tier"] = "T4"


def best_locked_report(prospect_id):
    locked = locked_reports_for(prospect_id)
    if not locked:
        return None
    return sorted(locked, key=lambda r: (-float(r["normalized_grade"]), r["created_at"]))[0]


def compute_fit_score(prospect, board):
    needs = [n for n in DB.needs.values()
             if n["position"] == prospect["position"]
             and n["season_year"] == board["season_year"]
             and n["status"] == "OPEN"]
    if not needs:
        base = DEFAULT_BASE
    else:
        order = {"P1": 0, "P2": 1, "P3": 2, "P4": 3}
        needs.sort(key=lambda n: (order[n["priority_tier"]], n["created_at"]))
        base = BASE_NEED[needs[0]["priority_tier"]]
    fit_source = best_locked_report(prospect["id"])
    scheme = Decimal(str(fit_source["scheme_fit"])) if fit_source else Decimal(0)
    med_mult = MEDICAL_HIGH_MULT if any(
        f for f in DB.flags.values()
        if f["prospect_id"] == prospect["id"]
        and f["flag_type"] == "MEDICAL"
        and f["severity"] == "HIGH"
        and f["status"] == "RESOLVED"
    ) else Decimal("1.0")
    char_ded = CHAR_DEDUCTION if any(
        f for f in DB.flags.values()
        if f["prospect_id"] == prospect["id"]
        and f["flag_type"] == "CHARACTER"
        and f["status"] in ("OPEN", "ACKNOWLEDGED")
    ) else Decimal("0")
    fit = base * scheme * med_mult - char_ded
    if fit < Decimal("0.0"):
        fit = Decimal("0.0")
    if fit > Decimal("100.0"):
        fit = Decimal("100.0")
    return num_out(dec2(fit))


def rerank_board(board):
    """Sort active entries by composite DESC (nulls last), fit_score DESC, created_at ASC."""
    active = [e for e in DB.entries.values()
              if e["board_id"] == board["id"] and e["active"]]

    def key(e):
        p = DB.prospects.get(e["prospect_id"])
        cg = p["composite_grade"] if p else None
        null_flag = 1 if cg is None else 0
        cg_val = float(cg) if cg is not None else 0.0
        return (null_flag, -cg_val, -float(e["fit_score"]), e["created_at"])

    active.sort(key=key)
    for idx, e in enumerate(active, start=1):
        if e["rank"] != idx:
            e["rank"] = idx
            touch(e)
    board["active_entry_count"] = len(active)


def recompute_budget(budget):
    committed = sum(
        t["annual_cap_hit_cents"]
        for t in DB.targets.values()
        if t["status"] == "SIGNED" and t.get("signed_budget_id") == budget["id"]
    )
    budget["committed_cents"] = committed
    budget["available_cents"] = budget["base_cap_cents"] + budget["rollover_cents"] - committed
    threshold = (Decimal(budget["base_cap_cents"]) + Decimal(budget["rollover_cents"])) * POSTURE_FRACTION
    budget["posture"] = "TIGHT" if Decimal(budget["available_cents"]) < threshold else "HEALTHY"


def compute_cap_hit(base_salary_cents, signing_bonus_cents, contract_years):
    prorated = (Decimal(signing_bonus_cents) / Decimal(contract_years)).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP
    )
    return int(base_salary_cents + int(prorated))


# ---------------------------------------------------------------------------
# Cascade helpers
# ---------------------------------------------------------------------------


def recompute_prospect_and_touch(prospect):
    recompute_prospect_composite(prospect)
    touch(prospect)


def lock_cascade(report):
    """Lock cascade hops 2-4 (hop 1 normalized_grade done by caller)."""
    prospect = DB.prospects[report["prospect_id"]]
    recompute_prospect_and_touch(prospect)
    # hop 3: active entries of this prospect on OPEN boards -> fit_score recompute + rerank
    affected_board_ids = set()
    for e in DB.entries.values():
        if e["prospect_id"] == prospect["id"] and e["active"]:
            board = DB.boards[e["board_id"]]
            if board["status"] == "OPEN":
                e["fit_score"] = compute_fit_score(prospect, board)
                touch(e)
                affected_board_ids.add(board["id"])
    # hop 4: rerank + version bump per affected board
    for bid in affected_board_ids:
        board = DB.boards[bid]
        rerank_board(board)
        touch(board)


def exclusion_cascade(prospect):
    """HIGH MEDICAL escalation: deactivate entries on OPEN or FROZEN boards, rerank, bump version."""
    prospect["flag_status"] = "EXCLUDED"
    touch(prospect)
    affected_board_ids = set()
    for e in DB.entries.values():
        if e["prospect_id"] == prospect["id"] and e["active"]:
            board = DB.boards[e["board_id"]]
            if board["status"] in ("OPEN", "FROZEN"):
                e["active"] = False
                touch(e)
                affected_board_ids.add(board["id"])
    for bid in affected_board_ids:
        board = DB.boards[bid]
        rerank_board(board)
        touch(board)


def recompute_flag_status(prospect):
    """After a resolve: CLEARED only when no other flag is OPEN/ACKNOWLEDGED/ESCALATED.
    EXCLUDED is never reversed by resolve."""
    if prospect["flag_status"] == "EXCLUDED":
        return
    open_like = any(
        f for f in DB.flags.values()
        if f["prospect_id"] == prospect["id"] and f["status"] in ("OPEN", "ACKNOWLEDGED", "ESCALATED")
    )
    if not open_like and prospect["flag_status"] == "UNDER_REVIEW":
        prospect["flag_status"] = "CLEARED"
        touch(prospect)


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------


def scout_out(s):
    return {
        "id": s["id"],
        "full_name": s["full_name"],
        "level": s["level"],
        "weight": s["weight"],
        "season_grade_mean": s["season_grade_mean"],
        "season_grade_stdev": s["season_grade_stdev"],
        "locked_grade_mean": s["locked_grade_mean"],
        "locked_grade_stdev": s["locked_grade_stdev"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


def prospect_out(p):
    return {
        "id": p["id"],
        "full_name": p["full_name"],
        "position": p["position"],
        "college": p["college"],
        "evaluation_status": p["evaluation_status"],
        "flag_status": p["flag_status"],
        "composite_grade": p["composite_grade"],
        "tier": p["tier"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def report_out(r):
    return {
        "id": r["id"],
        "prospect_id": r["prospect_id"],
        "scout_id": r["scout_id"],
        "raw_grade": r["raw_grade"],
        "scheme_fit": r["scheme_fit"],
        "notes": r["notes"],
        "status": r["status"],
        "normalized_grade": r["normalized_grade"],
        "return_reason": r["return_reason"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def video_tag_out(v):
    return {
        "id": v["id"],
        "report_id": v["report_id"],
        "clip_url": v["clip_url"],
        "start_sec": v["start_sec"],
        "end_sec": v["end_sec"],
        "tag": v["tag"],
        "created_at": v["created_at"],
    }


def flag_out(f, caller):
    detail = f["detail"]
    if f["flag_type"] == "MEDICAL" and caller.role != "MedicalStaff":
        detail = None
    return {
        "id": f["id"],
        "prospect_id": f["prospect_id"],
        "flag_type": f["flag_type"],
        "severity": f["severity"],
        "detail": detail,
        "status": f["status"],
        "author_role": f["author_role"],
        "resolution_note": f["resolution_note"],
        "created_at": f["created_at"],
        "updated_at": f["updated_at"],
        "version": f["version"],
    }


def board_out(b):
    return {
        "id": b["id"],
        "season_year": b["season_year"],
        "status": b["status"],
        "active_entry_count": b["active_entry_count"],
        "created_at": b["created_at"],
        "updated_at": b["updated_at"],
        "version": b["version"],
    }


def entry_out(e):
    return {
        "id": e["id"],
        "board_id": e["board_id"],
        "prospect_id": e["prospect_id"],
        "rank": e["rank"],
        "fit_score": e["fit_score"],
        "active": e["active"],
        "created_at": e["created_at"],
        "updated_at": e["updated_at"],
        "version": e["version"],
    }


def need_out(n):
    return {
        "id": n["id"],
        "season_year": n["season_year"],
        "position": n["position"],
        "priority_tier": n["priority_tier"],
        "status": n["status"],
        "created_at": n["created_at"],
        "updated_at": n["updated_at"],
        "version": n["version"],
    }


def target_out(t):
    return {
        "id": t["id"],
        "player_name": t["player_name"],
        "position": t["position"],
        "season_year": t["season_year"],
        "base_salary_cents": t["base_salary_cents"],
        "signing_bonus_cents": t["signing_bonus_cents"],
        "contract_years": t["contract_years"],
        "status": t["status"],
        "annual_cap_hit_cents": t["annual_cap_hit_cents"],
        "signed_budget_id": t["signed_budget_id"],
        "created_at": t["created_at"],
        "updated_at": t["updated_at"],
        "version": t["version"],
    }


def budget_out(b):
    return {
        "id": b["id"],
        "season_year": b["season_year"],
        "base_cap_cents": b["base_cap_cents"],
        "rollover_cents": b["rollover_cents"],
        "committed_cents": b["committed_cents"],
        "available_cents": b["available_cents"],
        "posture": b["posture"],
        "created_at": b["created_at"],
        "updated_at": b["updated_at"],
        "version": b["version"],
    }


def interview_out(i):
    return {
        "id": i["id"],
        "prospect_id": i["prospect_id"],
        "start_at": i["start_at"],
        "end_at": i["end_at"],
        "location": i["location"],
        "status": i["status"],
        "created_at": i["created_at"],
        "updated_at": i["updated_at"],
        "version": i["version"],
    }


def facility_out(f):
    return {
        "id": f["id"],
        "name": f["name"],
        "capacity": f["capacity"],
        "created_at": f["created_at"],
        "updated_at": f["updated_at"],
        "version": f["version"],
    }


def booking_out(b):
    return {
        "id": b["id"],
        "facility_id": b["facility_id"],
        "start_at": b["start_at"],
        "end_at": b["end_at"],
        "purpose": b["purpose"],
        "created_at": b["created_at"],
        "updated_at": b["updated_at"],
        "version": b["version"],
    }


def outcome_out(o):
    return {
        "id": o["id"],
        "prospect_id": o["prospect_id"],
        "season_year": o["season_year"],
        "games_started": o["games_started"],
        "pro_bowl": o["pro_bowl"],
        "outcome_percentile": o["outcome_percentile"],
        "created_at": o["created_at"],
        "updated_at": o["updated_at"],
        "version": o["version"],
    }


# ---------------------------------------------------------------------------
# Flask app & error handling
# ---------------------------------------------------------------------------

app = Flask(__name__)


@app.errorhandler(ApiError)
def handle_api_error(err):
    return error_response(err)


@app.errorhandler(404)
def handle_404(_e):
    return error_response(err_not_found("Resource not found"))


@app.errorhandler(405)
def handle_405(_e):
    return error_response(ApiError("ERR_NOT_FOUND", "Method not allowed", 404))


@app.errorhandler(Exception)
def handle_unexpected(err):
    # Never leak a bare 500 HTML page; wrap in envelope.
    import traceback
    traceback.print_exc()
    return error_response(ApiError("ERR_VALIDATION", f"Unexpected error: {err}", 400))


# ---------------------------------------------------------------------------
# Clock endpoint
# ---------------------------------------------------------------------------


@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock_endpoint():
    caller = authenticate()
    require_roles(caller, "GeneralManager", "ScoutingDirector", "AreaScout", "MedicalStaff")
    data = body()
    to_iso = req_field(data, "to_iso8601")
    if not isinstance(to_iso, str):
        raise err_validation("to_iso8601 must be a string")
    try:
        dt = parse_iso(to_iso)
    except ValueError:
        raise err_validation("to_iso8601 must be a valid ISO 8601 timestamp")
    set_clock(dt)
    return ok_object({"current_utc": iso_fmt(dt)}, 200)


# ---------------------------------------------------------------------------
# Scouts
# ---------------------------------------------------------------------------


@app.route("/scouting/scouts", methods=["POST"])
def create_scout():
    caller = authenticate()
    require_roles(caller, "GeneralManager")
    data = body()
    full_name = as_string(req_field(data, "full_name"), "full_name")
    level = as_enum(req_field(data, "level"), "level", {"AREA", "DIRECTOR"})
    weight = data.get("weight", 1.0)
    try:
        weight_d = to_decimal(weight)
    except ValueError:
        raise err_validation("weight must be a number")
    if weight_d <= 0:
        raise ApiError("ERR_WEIGHT_INVALID", "weight must be > 0", 422)

    def opt_stat(name, lo=None, gt=None):
        v = data.get(name)
        if v is None:
            return None
        try:
            d = to_decimal(v)
        except ValueError:
            raise err_validation(f"{name} must be a number")
        if decimal_places(d) > 2:
            raise err_validation(f"{name} must have at most 2 decimal places")
        if lo is not None and not (lo[0] <= d <= lo[1]):
            raise err_validation(f"{name} out of range")
        if gt is not None and not (d > gt):
            raise err_validation(f"{name} must be > 0")
        return num_out(d)

    season_mean = opt_stat("season_grade_mean", lo=(Decimal("1.00"), Decimal("9.00")))
    season_stdev = opt_stat("season_grade_stdev", gt=Decimal("0"))
    locked_mean = opt_stat("locked_grade_mean", lo=(Decimal("1.00"), Decimal("9.00")))
    locked_stdev = opt_stat("locked_grade_stdev", gt=Decimal("0"))

    s = stamp_new({
        "full_name": full_name,
        "level": level,
        "weight": num_out(weight_d),
        "season_grade_mean": season_mean,
        "season_grade_stdev": season_stdev,
        "locked_grade_mean": locked_mean,
        "locked_grade_stdev": locked_stdev,
    })
    DB.scouts[s["id"]] = s
    return ok_object(scout_out(s), 201)


@app.route("/scouting/scouts/<sid>", methods=["GET"])
def get_scout(sid):
    caller = authenticate()
    require_roles(caller, "GeneralManager", "ScoutingDirector", "AreaScout", "MedicalStaff")
    s = DB.scouts.get(sid)
    if not s:
        raise err_not_found("Scout not found")
    return ok_object(scout_out(s))


@app.route("/scouting/scouts/<sid>/evaluation", methods=["GET"])
def scout_evaluation(sid):
    caller = authenticate()
    require_roles(caller, "GeneralManager", "ScoutingDirector")
    s = DB.scouts.get(sid)
    if not s:
        raise err_not_found("Scout not found")
    eligible = []
    for r in DB.reports.values():
        if r["scout_id"] != sid or r["status"] != "LOCKED":
            continue
        outs = [o for o in DB.outcomes.values() if o["prospect_id"] == r["prospect_id"]]
        if not outs:
            continue
        latest = max(outs, key=lambda o: o["season_year"])
        eligible.append((r, latest))
    if not eligible:
        return ok_object({
            "scout_id": sid,
            "rmse_accuracy": None,
            "hit_rate_accuracy": None,
            "evaluated_report_count": 0,
        })
    sq = Decimal(0)
    for r, o in eligible:
        err = Decimal(str(r["normalized_grade"])) - (Decimal(o["outcome_percentile"]) / Decimal(10))
        sq += err * err
    mse = sq / Decimal(len(eligible))
    rmse = Decimal(str(math.sqrt(float(mse))))
    rmse_acc = Decimal("100") - RMSE_PENALTY * rmse
    rmse_acc = dec2(rmse_acc)
    if rmse_acc < 0:
        rmse_acc = Decimal("0.00")
    predictions = [(r, o) for r, o in eligible if Decimal(str(r["normalized_grade"])) >= HIT_GRADE_MIN]
    if predictions:
        hits = sum(1 for _, o in predictions if o["outcome_percentile"] >= HIT_OUTCOME_MIN)
        hit_rate = dec2(Decimal("100") * Decimal(hits) / Decimal(len(predictions)))
        hit_rate_val = num_out(hit_rate)
    else:
        hit_rate_val = None
    return ok_object({
        "scout_id": sid,
        "rmse_accuracy": num_out(rmse_acc),
        "hit_rate_accuracy": hit_rate_val,
        "evaluated_report_count": len(eligible),
    })


@app.route("/scouting/scouts/<sid>/weight", methods=["POST"])
def set_scout_weight(sid):
    caller = authenticate()
    require_roles(caller, "ScoutingDirector")
    s = DB.scouts.get(sid)
    if not s:
        raise err_not_found("Scout not found")
    data = body()
    new_weight = req_field(data, "new_weight")
    try:
        wd = to_decimal(new_weight)
    except ValueError:
        raise ApiError("ERR_WEIGHT_INVALID", "new_weight must be a number > 0", 422)
    if wd <= 0:
        raise ApiError("ERR_WEIGHT_INVALID", "new_weight must be > 0", 422)
    s["weight"] = num_out(wd)
    touch(s)
    # Recompute composite/tier for every prospect with a LOCKED report by this scout
    affected_prospect_ids = {
        r["prospect_id"] for r in DB.reports.values()
        if r["scout_id"] == sid and r["status"] == "LOCKED"
    }
    affected_board_ids = set()
    for pid in affected_prospect_ids:
        prospect = DB.prospects[pid]
        recompute_prospect_and_touch(prospect)
    # Rerank OPEN boards containing active entries of affected prospects
    for e in DB.entries.values():
        if e["prospect_id"] in affected_prospect_ids and e["active"]:
            board = DB.boards[e["board_id"]]
            if board["status"] == "OPEN":
                affected_board_ids.add(board["id"])
    for bid in affected_board_ids:
        board = DB.boards[bid]
        rerank_board(board)
        touch(board)
    return ok_object(scout_out(s))


# ---------------------------------------------------------------------------
# Prospects
# ---------------------------------------------------------------------------


@app.route("/scouting/prospects", methods=["POST"])
def create_prospect():
    caller = authenticate()
    require_roles(caller, "AreaScout", "ScoutingDirector")
    data = body()
    full_name = as_string(req_field(data, "full_name"), "full_name")
    position = as_string(req_field(data, "position"), "position")
    college = as_string(req_field(data, "college"), "college")
    p = stamp_new({
        "full_name": full_name,
        "position": position,
        "college": college,
        "evaluation_status": "NEW",
        "flag_status": "CLEAR",
        "composite_grade": None,
        "tier": None,
    })
    DB.prospects[p["id"]] = p
    return ok_object(prospect_out(p), 201)


@app.route("/scouting/prospects", methods=["GET"])
def list_prospects():
    caller = authenticate()
    require_roles(caller, "GeneralManager", "ScoutingDirector", "AreaScout", "MedicalStaff")
    limit, offset = parse_pagination()
    items = list(DB.prospects.values())
    pos = request.args.get("position")
    ev = request.args.get("evaluation_status")
    fs = request.args.get("flag_status")
    if pos is not None:
        items = [p for p in items if p["position"] == pos]
    if ev is not None:
        items = [p for p in items if p["evaluation_status"] == ev]
    if fs is not None:
        items = [p for p in items if p["flag_status"] == fs]
    items.sort(key=lambda p: p["created_at"])
    page, total = paginate(items, limit, offset)
    return ok_list([prospect_out(p) for p in page], limit, offset, total)


@app.route("/scouting/prospects/<pid>", methods=["GET"])
def get_prospect(pid):
    caller = authenticate()
    require_roles(caller, "GeneralManager", "ScoutingDirector", "AreaScout", "MedicalStaff")
    p = DB.prospects.get(pid)
    if not p:
        raise err_not_found("Prospect not found")
    return ok_object(prospect_out(p))


@app.route("/scouting/prospects/<pid>/advance", methods=["POST"])
def advance_prospect(pid):
    caller = authenticate()
    require_roles(caller, "ScoutingDirector")
    p = DB.prospects.get(pid)
    if not p:
        raise err_not_found("Prospect not found")
    data = body()
    to_state = req_field(data, "to_state")
    if to_state not in ("EVALUATED", "BOARD_READY", "ARCHIVED"):
        raise err_validation("to_state must be EVALUATED, BOARD_READY, or ARCHIVED")
    has_locked = any(
        r for r in DB.reports.values()
        if r["prospect_id"] == pid and r["status"] == "LOCKED"
    )
    cur = p["evaluation_status"]
    allowed = False
    if to_state == "EVALUATED":
        allowed = (cur == "SCOUTING") and has_locked
    elif to_state == "BOARD_READY":
        allowed = (cur == "EVALUATED") and has_locked
    elif to_state == "ARCHIVED":
        allowed = cur in ("EVALUATED", "BOARD_READY")
    if not allowed:
        raise ApiError("ERR_INVALID_STATE", f"Cannot advance from {cur} to {to_state}", 409)
    p["evaluation_status"] = to_state
    touch(p)
    return ok_object(prospect_out(p))


@app.route("/scouting/prospects/<pid>/mark-drafted", methods=["POST"])
def mark_drafted(pid):
    caller = authenticate()
    require_roles(caller, "GeneralManager")
    p = DB.prospects.get(pid)
    if not p:
        raise err_not_found("Prospect not found")
    if p["evaluation_status"] != "BOARD_READY":
        raise ApiError("ERR_INVALID_STATE", "Prospect must be BOARD_READY to be marked drafted", 409)
    p["evaluation_status"] = "DRAFTED"
    touch(p)
    return ok_object(prospect_out(p))


@app.route("/scouting/prospects/<pid>/board-entries", methods=["GET"])
def prospect_board_entries(pid):
    caller = authenticate()
    require_roles(caller, "ScoutingDirector", "GeneralManager")
    p = DB.prospects.get(pid)
    if not p:
        raise err_not_found("Prospect not found")
    limit, offset = parse_pagination()
    items = [e for e in DB.entries.values() if e["prospect_id"] == pid]
    items.sort(key=lambda e: e["created_at"])
    page, total = paginate(items, limit, offset)
    return ok_list([entry_out(e) for e in page], limit, offset, total)


# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------


def check_grade_ranges(raw_d, scheme_d):
    if decimal_places(raw_d) > 2 or not (Decimal("1.00") <= raw_d <= Decimal("9.00")):
        raise ApiError("ERR_GRADE_OUT_OF_RANGE", "raw_grade must be in [1.00, 9.00] with <= 2 decimals", 422)
    if decimal_places(scheme_d) > 2 or not (Decimal("0.00") <= scheme_d <= Decimal("1.50")):
        raise ApiError("ERR_GRADE_OUT_OF_RANGE", "scheme_fit must be in [0.00, 1.50] with <= 2 decimals", 422)


@app.route("/scouting/prospects/<pid>/reports", methods=["POST"])
def create_report(pid):
    caller = authenticate()
    require_roles(caller, "AreaScout")
    data = body()
    # Schema validation (priority 3) before existence (priority 4)? PRD ordering:
    # schema (3) precedes existence (4). Validate raw_grade/scheme_fit types first.
    raw_v = req_field(data, "raw_grade")
    scheme_v = req_field(data, "scheme_fit")
    raw_d = as_number_decimal(raw_v, "raw_grade")
    scheme_d = as_number_decimal(scheme_v, "scheme_fit")
    notes = data.get("notes", "")
    if notes is None:
        notes = ""
    if not isinstance(notes, str):
        raise err_validation("notes must be a string")
    # Existence
    p = DB.prospects.get(pid)
    if not p:
        raise err_not_found("Prospect not found")
    # State: report creation requires prospect.evaluation_status in {NEW, SCOUTING, EVALUATED}
    if p["evaluation_status"] not in ("NEW", "SCOUTING", "EVALUATED"):
        raise ApiError("ERR_INVALID_STATE", "Prospect no longer accepts new reports", 409)
    # Business safety: none for this endpoint
    # Business constraint: uniqueness (scout_id, prospect_id)
    for r in DB.reports.values():
        if r["prospect_id"] == pid and r["scout_id"] == caller.user_id:
            raise ApiError("ERR_DUPLICATE_REPORT", "Report already exists for this scout and prospect", 409)
    # Grade ranges (priority 7)
    check_grade_ranges(raw_d, scheme_d)

    r = stamp_new({
        "prospect_id": pid,
        "scout_id": caller.user_id,
        "raw_grade": num_out(raw_d),
        "scheme_fit": num_out(scheme_d),
        "notes": notes,
        "status": "DRAFT",
        "normalized_grade": None,
        "return_reason": "",
    })
    DB.reports[r["id"]] = r
    # First report moves prospect NEW -> SCOUTING
    if p["evaluation_status"] == "NEW":
        p["evaluation_status"] = "SCOUTING"
        touch(p)
    return ok_object(report_out(r), 201)


@app.route("/scouting/reports", methods=["GET"])
def list_reports():
    caller = authenticate()
    require_roles(caller, "AreaScout", "ScoutingDirector", "GeneralManager")
    limit, offset = parse_pagination()
    items = list(DB.reports.values())
    scout_id = request.args.get("scout_id")
    prospect_id = request.args.get("prospect_id")
    status = request.args.get("status")
    if scout_id is not None:
        items = [r for r in items if r["scout_id"] == scout_id]
    if prospect_id is not None:
        items = [r for r in items if r["prospect_id"] == prospect_id]
    if status is not None:
        items = [r for r in items if r["status"] == status]
    items.sort(key=lambda r: r["created_at"])
    page, total = paginate(items, limit, offset)
    return ok_list([report_out(r) for r in page], limit, offset, total)


@app.route("/scouting/reports/<rid>", methods=["GET"])
def get_report(rid):
    caller = authenticate()
    require_roles(caller, "AreaScout", "ScoutingDirector", "GeneralManager")
    r = DB.reports.get(rid)
    if not r:
        raise err_not_found("Report not found")
    return ok_object(report_out(r))


@app.route("/scouting/reports/<rid>/submit", methods=["POST"])
def submit_report(rid):
    caller = authenticate()
    require_roles(caller, "AreaScout")
    r = DB.reports.get(rid)
    if not r:
        raise err_not_found("Report not found")
    if caller.user_id != r["scout_id"]:
        raise ApiError("ERR_REPORT_NOT_OWNED", "Only the authoring scout may submit this report", 403)
    if r["status"] not in ("DRAFT", "RETURNED"):
        raise ApiError("ERR_INVALID_STATE", f"Cannot submit a report in state {r['status']}", 409)
    if r["status"] == "RETURNED":
        r["return_reason"] = ""
    r["status"] = "SUBMITTED"
    touch(r)
    return ok_object(report_out(r))


@app.route("/scouting/reports/<rid>/return", methods=["POST"])
def return_report(rid):
    caller = authenticate()
    require_roles(caller, "ScoutingDirector")
    r = DB.reports.get(rid)
    if not r:
        raise err_not_found("Report not found")
    data = body()
    reason = data.get("return_reason", "")
    if reason is None:
        reason = ""
    if not isinstance(reason, str):
        raise err_validation("return_reason must be a string")
    if r["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE", f"Cannot return a report in state {r['status']}", 409)
    r["status"] = "RETURNED"
    r["return_reason"] = reason
    touch(r)
    return ok_object(report_out(r))


@app.route("/scouting/reports/<rid>/lock", methods=["POST"])
def lock_report(rid):
    caller = authenticate()
    require_roles(caller, "ScoutingDirector")
    r = DB.reports.get(rid)
    if not r:
        raise err_not_found("Report not found")
    if r["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE", f"Cannot lock a report in state {r['status']}", 409)
    scout = DB.scouts.get(r["scout_id"])
    # Variant selection: locked pair wins if locked_grade_mean is set
    if scout.get("locked_grade_mean") is not None:
        mean = scout.get("locked_grade_mean")
        stdev = scout.get("locked_grade_stdev")
    else:
        mean = scout.get("season_grade_mean")
        stdev = scout.get("season_grade_stdev")
    if mean is None or stdev is None:
        # No baseline stats available for normalization
        raise ApiError("ERR_INVALID_STATE", "Scout grading baseline not established", 409)
    # hop 1
    r["normalized_grade"] = num_out(compute_normalized_grade(r, scout))
    r["status"] = "LOCKED"
    touch(r)
    # hops 2-4
    lock_cascade(r)
    return ok_object(report_out(r))


@app.route("/scouting/reports/<rid>/video-tags", methods=["POST"])
def create_video_tag(rid):
    caller = authenticate()
    require_roles(caller, "AreaScout")
    r = DB.reports.get(rid)
    if not r:
        raise err_not_found("Report not found")
    if caller.user_id != r["scout_id"]:
        raise ApiError("ERR_REPORT_NOT_OWNED", "Only the authoring scout may attach video tags", 403)
    data = body()
    clip_url = as_string(req_field(data, "clip_url"), "clip_url")
    start_sec = as_int(req_field(data, "start_sec"), "start_sec", minimum=0)
    end_sec = as_int(req_field(data, "end_sec"), "end_sec", minimum=0)
    tag = as_enum(req_field(data, "tag"), "tag", {"SCHEME", "ATHLETICISM", "TECHNIQUE", "CHARACTER"})
    if end_sec <= start_sec:
        raise err_validation("end_sec must be > start_sec")
    if r["status"] not in ("DRAFT", "RETURNED"):
        raise ApiError("ERR_INVALID_STATE", f"Cannot attach video tags to a report in state {r['status']}", 409)
    v = {
        "id": new_id(),
        "report_id": rid,
        "clip_url": clip_url,
        "start_sec": start_sec,
        "end_sec": end_sec,
        "tag": tag,
        "created_at": iso_now(),
    }
    DB.video_tags[v["id"]] = v
    return ok_object(video_tag_out(v), 201)


@app.route("/scouting/reports/<rid>/video-tags", methods=["GET"])
def list_video_tags(rid):
    caller = authenticate()
    require_roles(caller, "GeneralManager", "ScoutingDirector", "AreaScout", "MedicalStaff")
    r = DB.reports.get(rid)
    if not r:
        raise err_not_found("Report not found")
    limit, offset = parse_pagination()
    items = [v for v in DB.video_tags.values() if v["report_id"] == rid]
    items.sort(key=lambda v: v["created_at"])
    page, total = paginate(items, limit, offset)
    return ok_list([video_tag_out(v) for v in page], limit, offset, total)


# ---------------------------------------------------------------------------
# Confidential flags
# ---------------------------------------------------------------------------


@app.route("/scouting/prospects/<pid>/flags", methods=["POST"])
def create_flag(pid):
    caller = authenticate()
    require_roles(caller, "MedicalStaff", "AreaScout", "ScoutingDirector")
    data = body()
    flag_type = req_field(data, "flag_type")
    severity = req_field(data, "severity")
    detail = req_field(data, "detail")
    # Schema enum checks
    if flag_type not in ("MEDICAL", "CHARACTER"):
        raise err_validation("flag_type must be MEDICAL or CHARACTER")
    if severity not in ("LOW", "HIGH"):
        raise err_validation("severity must be LOW or HIGH")
    if not isinstance(detail, str):
        raise err_validation("detail must be a string")
    # Flag-type clearance (auth priority 2)
    if flag_type == "MEDICAL" and caller.role != "MedicalStaff":
        raise ApiError("ERR_FLAG_ACCESS_DENIED", "MEDICAL flags may only be created by MedicalStaff", 403)
    if flag_type == "CHARACTER" and caller.role not in ("AreaScout", "ScoutingDirector"):
        raise ApiError("ERR_FLAG_ACCESS_DENIED", "CHARACTER flags may only be created by scouting roles", 403)
    p = DB.prospects.get(pid)
    if not p:
        raise err_not_found("Prospect not found")
    f = stamp_new({
        "prospect_id": pid,
        "flag_type": flag_type,
        "severity": severity,
        "detail": detail,
        "status": "OPEN",
        "author_role": caller.role,
        "resolution_note": "",
    })
    DB.flags[f["id"]] = f
    # Flag creation moves prospect flag_status to UNDER_REVIEW (from CLEAR or CLEARED)
    if p["flag_status"] in ("CLEAR", "CLEARED"):
        p["flag_status"] = "UNDER_REVIEW"
        touch(p)
    return ok_object(flag_out(f, caller), 201)


@app.route("/scouting/prospects/<pid>/flags", methods=["GET"])
def list_flags(pid):
    caller = authenticate()
    require_roles(caller, "GeneralManager", "ScoutingDirector", "AreaScout", "MedicalStaff")
    p = DB.prospects.get(pid)
    if not p:
        raise err_not_found("Prospect not found")
    limit, offset = parse_pagination()
    items = [f for f in DB.flags.values() if f["prospect_id"] == pid]
    ftype = request.args.get("flag_type")
    fstatus = request.args.get("status")
    if ftype is not None:
        items = [f for f in items if f["flag_type"] == ftype]
    if fstatus is not None:
        items = [f for f in items if f["status"] == fstatus]
    items.sort(key=lambda f: f["created_at"])
    page, total = paginate(items, limit, offset)
    return ok_list([flag_out(f, caller) for f in page], limit, offset, total)


def _flag_review_role_check(caller, flag):
    """Acknowledge/resolve: MedicalStaff for MEDICAL, ScoutingDirector for CHARACTER."""
    if flag["flag_type"] == "MEDICAL":
        if caller.role != "MedicalStaff":
            raise err_forbidden("MEDICAL flags are reviewed by MedicalStaff")
    else:
        if caller.role != "ScoutingDirector":
            raise err_forbidden("CHARACTER flags are reviewed by ScoutingDirector")


@app.route("/scouting/flags/<fid>/acknowledge", methods=["POST"])
def acknowledge_flag(fid):
    caller = authenticate()
    require_roles(caller, "MedicalStaff", "ScoutingDirector")
    f = DB.flags.get(fid)
    if not f:
        raise err_not_found("Flag not found")
    _flag_review_role_check(caller, f)
    if f["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", f"Cannot acknowledge a flag in state {f['status']}", 409)
    f["status"] = "ACKNOWLEDGED"
    touch(f)
    return ok_object(flag_out(f, caller))


@app.route("/scouting/flags/<fid>/resolve", methods=["POST"])
def resolve_flag(fid):
    caller = authenticate()
    require_roles(caller, "MedicalStaff", "ScoutingDirector")
    f = DB.flags.get(fid)
    if not f:
        raise err_not_found("Flag not found")
    _flag_review_role_check(caller, f)
    data = body()
    note = data.get("resolution_note", "")
    if note is None:
        note = ""
    if not isinstance(note, str):
        raise err_validation("resolution_note must be a string")
    if f["status"] not in ("OPEN", "ACKNOWLEDGED", "ESCALATED"):
        raise ApiError("ERR_INVALID_STATE", f"Cannot resolve a flag in state {f['status']}", 409)
    f["status"] = "RESOLVED"
    f["resolution_note"] = note
    touch(f)
    prospect = DB.prospects[f["prospect_id"]]
    recompute_flag_status(prospect)
    return ok_object(flag_out(f, caller))


@app.route("/scouting/flags/<fid>/escalate", methods=["POST"])
def escalate_flag(fid):
    caller = authenticate()
    require_roles(caller, "ScoutingDirector")
    f = DB.flags.get(fid)
    if not f:
        raise err_not_found("Flag not found")
    if f["status"] not in ("OPEN", "ACKNOWLEDGED"):
        raise ApiError("ERR_INVALID_STATE", f"Cannot escalate a flag in state {f['status']}", 409)
    f["status"] = "ESCALATED"
    touch(f)
    prospect = DB.prospects[f["prospect_id"]]
    if f["flag_type"] == "MEDICAL" and f["severity"] == "HIGH":
        exclusion_cascade(prospect)
    else:
        # remains UNDER_REVIEW, no board impact
        if prospect["flag_status"] in ("CLEAR", "CLEARED"):
            prospect["flag_status"] = "UNDER_REVIEW"
            touch(prospect)
    return ok_object(flag_out(f, caller))


# ---------------------------------------------------------------------------
# Draft boards
# ---------------------------------------------------------------------------


@app.route("/scouting/draft-boards", methods=["POST"])
def create_board():
    caller = authenticate()
    require_roles(caller, "ScoutingDirector")
    data = body()
    season_year = as_int(req_field(data, "season_year"), "season_year")
    b = stamp_new({
        "season_year": season_year,
        "status": "OPEN",
        "active_entry_count": 0,
    })
    DB.boards[b["id"]] = b
    return ok_object(board_out(b), 201)


@app.route("/scouting/draft-boards/<bid>", methods=["GET"])
def get_board(bid):
    caller = authenticate()
    require_roles(caller, "ScoutingDirector", "GeneralManager")
    b = DB.boards.get(bid)
    if not b:
        raise err_not_found("Draft board not found")
    return ok_object(board_out(b))


@app.route("/scouting/draft-boards/<bid>/entries", methods=["GET"])
def list_board_entries(bid):
    caller = authenticate()
    require_roles(caller, "ScoutingDirector", "GeneralManager")
    b = DB.boards.get(bid)
    if not b:
        raise err_not_found("Draft board not found")
    limit, offset = parse_pagination()
    items = [e for e in DB.entries.values() if e["board_id"] == bid]
    active_q = request.args.get("active")
    if active_q is not None:
        if active_q.lower() in ("true", "1"):
            items = [e for e in items if e["active"]]
        elif active_q.lower() in ("false", "0"):
            items = [e for e in items if not e["active"]]
        else:
            raise err_validation("active must be true or false")
    # rank ASC, active first: actives have contiguous ranks; inactives sort after by created_at
    items.sort(key=lambda e: (0, e["rank"]) if e["active"] else (1, e["created_at"]))
    page, total = paginate(items, limit, offset)
    return ok_list([entry_out(e) for e in page], limit, offset, total)


@app.route("/scouting/draft-boards/<bid>/entries", methods=["POST"])
def add_board_entry(bid):
    caller = authenticate()
    require_roles(caller, "ScoutingDirector")
    data = body()
    prospect_id = req_field(data, "prospect_id")
    if not isinstance(prospect_id, str):
        raise err_validation("prospect_id must be a string")
    b = DB.boards.get(bid)
    if not b:
        raise err_not_found("Draft board not found")
    p = DB.prospects.get(prospect_id)
    if not p:
        raise err_not_found("Prospect not found")
    if b["status"] != "OPEN":
        raise ApiError("ERR_BOARD_NOT_OPEN", "Board is not OPEN", 409)
    if p["evaluation_status"] != "BOARD_READY":
        raise ApiError("ERR_PROSPECT_NOT_BOARD_READY", "Prospect is not BOARD_READY", 409)
    if p["flag_status"] == "EXCLUDED":
        raise ApiError("ERR_PROSPECT_EXCLUDED", "Prospect is EXCLUDED", 409)
    fit = compute_fit_score(p, b)
    e = stamp_new({
        "board_id": bid,
        "prospect_id": prospect_id,
        "rank": 0,
        "fit_score": fit,
        "active": True,
    })
    DB.entries[e["id"]] = e
    rerank_board(b)
    touch(b)
    return ok_object(entry_out(e), 201)


@app.route("/scouting/draft-boards/<bid>/entries/reorder", methods=["POST"])
def reorder_board_entries(bid):
    caller = authenticate()
    require_roles(caller, "ScoutingDirector")
    data = body()
    entry_id = req_field(data, "entry_id")
    new_rank = req_field(data, "new_rank")
    expected = req_field(data, "expected_board_version")
    if not isinstance(entry_id, str):
        raise err_validation("entry_id must be a string")
    new_rank = as_int(new_rank, "new_rank")
    expected = as_int(expected, "expected_board_version", minimum=0)
    b = DB.boards.get(bid)
    if not b:
        raise err_not_found("Draft board not found")
    e = DB.entries.get(entry_id)
    if not e:
        raise err_not_found("Entry not found")
    # OCC check
    if expected != b["version"]:
        raise ApiError("ERR_STALE_VERSION", "expected_board_version does not match current board version", 412)
    if b["status"] != "OPEN":
        raise ApiError("ERR_BOARD_NOT_OPEN", "Board is not OPEN", 409)
    if e["board_id"] != bid or not e["active"]:
        raise ApiError("ERR_RANK_OUT_OF_BOUNDS", "entry_id is not an active entry of this board", 422)
    if new_rank < 1 or new_rank > b["active_entry_count"]:
        raise ApiError("ERR_RANK_OUT_OF_BOUNDS", f"new_rank must be within [1, {b['active_entry_count']}]", 422)
    # Insert semantics
    actives = sorted(
        [x for x in DB.entries.values() if x["board_id"] == bid and x["active"]],
        key=lambda x: x["rank"],
    )
    actives = [x for x in actives if x["id"] != entry_id]
    actives.insert(new_rank - 1, e)
    for idx, x in enumerate(actives, start=1):
        if x["rank"] != idx:
            x["rank"] = idx
            touch(x)
    touch(b)
    return ok_object(board_out(b))


@app.route("/scouting/draft-boards/<bid>/freeze", methods=["POST"])
def freeze_board(bid):
    caller = authenticate()
    require_roles(caller, "ScoutingDirector")
    b = DB.boards.get(bid)
    if not b:
        raise err_not_found("Draft board not found")
    if b["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", f"Cannot freeze a board in state {b['status']}", 409)
    b["status"] = "FROZEN"
    touch(b)
    return ok_object(board_out(b))


@app.route("/scouting/draft-boards/<bid>/unfreeze", methods=["POST"])
def unfreeze_board(bid):
    caller = authenticate()
    require_roles(caller, "ScoutingDirector")
    b = DB.boards.get(bid)
    if not b:
        raise err_not_found("Draft board not found")
    if b["status"] != "FROZEN":
        raise ApiError("ERR_INVALID_STATE", f"Cannot unfreeze a board in state {b['status']}", 409)
    b["status"] = "OPEN"
    touch(b)
    return ok_object(board_out(b))


@app.route("/scouting/draft-boards/<bid>/finalize", methods=["POST"])
def finalize_board(bid):
    caller = authenticate()
    require_roles(caller, "ScoutingDirector")
    b = DB.boards.get(bid)
    if not b:
        raise err_not_found("Draft board not found")
    if b["status"] != "FROZEN":
        raise ApiError("ERR_INVALID_STATE", f"Cannot finalize a board in state {b['status']}", 409)
    if b["active_entry_count"] < 1:
        raise ApiError("ERR_BOARD_EMPTY", "Cannot finalize a board with no active entries", 409)
    b["status"] = "FINALIZED"
    touch(b)
    return ok_object(board_out(b))


# ---------------------------------------------------------------------------
# Roster needs
# ---------------------------------------------------------------------------


@app.route("/scouting/roster-needs", methods=["POST"])
def create_need():
    caller = authenticate()
    require_roles(caller, "GeneralManager")
    data = body()
    season_year = as_int(req_field(data, "season_year"), "season_year")
    position = as_string(req_field(data, "position"), "position")
    priority_tier = as_enum(req_field(data, "priority_tier"), "priority_tier", {"P1", "P2", "P3", "P4"})
    n = stamp_new({
        "season_year": season_year,
        "position": position,
        "priority_tier": priority_tier,
        "status": "OPEN",
    })
    DB.needs[n["id"]] = n
    return ok_object(need_out(n), 201)


@app.route("/scouting/roster-needs", methods=["GET"])
def list_needs():
    caller = authenticate()
    require_roles(caller, "GeneralManager", "ScoutingDirector", "AreaScout", "MedicalStaff")
    limit, offset = parse_pagination()
    items = list(DB.needs.values())
    sy = request.args.get("season_year")
    pos = request.args.get("position")
    st = request.args.get("status")
    if sy is not None:
        try:
            sy_i = int(sy)
        except ValueError:
            raise err_validation("season_year must be an integer")
        items = [n for n in items if n["season_year"] == sy_i]
    if pos is not None:
        items = [n for n in items if n["position"] == pos]
    if st is not None:
        items = [n for n in items if n["status"] == st]
    items.sort(key=lambda n: n["created_at"])
    page, total = paginate(items, limit, offset)
    return ok_list([need_out(n) for n in page], limit, offset, total)


@app.route("/scouting/roster-needs/<nid>", methods=["GET"])
def get_need(nid):
    caller = authenticate()
    require_roles(caller, "GeneralManager", "ScoutingDirector", "AreaScout", "MedicalStaff")
    n = DB.needs.get(nid)
    if not n:
        raise err_not_found("Roster need not found")
    return ok_object(need_out(n))


@app.route("/scouting/roster-needs/<nid>/close", methods=["POST"])
def close_need(nid):
    caller = authenticate()
    require_roles(caller, "GeneralManager")
    n = DB.needs.get(nid)
    if not n:
        raise err_not_found("Roster need not found")
    if n["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", f"Cannot close a need in state {n['status']}", 409)
    n["status"] = "CLOSED"
    touch(n)
    return ok_object(need_out(n))


# ---------------------------------------------------------------------------
# Free-agent targets
# ---------------------------------------------------------------------------


@app.route("/scouting/free-agent-targets", methods=["POST"])
def create_target():
    caller = authenticate()
    require_roles(caller, "GeneralManager")
    data = body()
    player_name = as_string(req_field(data, "player_name"), "player_name")
    position = as_string(req_field(data, "position"), "position")
    season_year = as_int(req_field(data, "season_year"), "season_year")
    base_salary = as_int(req_field(data, "base_salary_cents"), "base_salary_cents", minimum=0)
    signing_bonus = as_int(req_field(data, "signing_bonus_cents"), "signing_bonus_cents", minimum=0)
    contract_years = as_int(req_field(data, "contract_years"), "contract_years", minimum=1)
    hit = compute_cap_hit(base_salary, signing_bonus, contract_years)
    t = stamp_new({
        "player_name": player_name,
        "position": position,
        "season_year": season_year,
        "base_salary_cents": base_salary,
        "signing_bonus_cents": signing_bonus,
        "contract_years": contract_years,
        "status": "IDENTIFIED",
        "annual_cap_hit_cents": hit,
        "signed_budget_id": None,
    })
    DB.targets[t["id"]] = t
    return ok_object(target_out(t), 201)


@app.route("/scouting/free-agent-targets", methods=["GET"])
def list_targets():
    caller = authenticate()
    require_roles(caller, "GeneralManager", "ScoutingDirector")
    limit, offset = parse_pagination()
    items = list(DB.targets.values())
    st = request.args.get("status")
    pos = request.args.get("position")
    sy = request.args.get("season_year")
    if st is not None:
        items = [t for t in items if t["status"] == st]
    if pos is not None:
        items = [t for t in items if t["position"] == pos]
    if sy is not None:
        try:
            sy_i = int(sy)
        except ValueError:
            raise err_validation("season_year must be an integer")
        items = [t for t in items if t["season_year"] == sy_i]
    items.sort(key=lambda t: t["created_at"])
    page, total = paginate(items, limit, offset)
    return ok_list([target_out(t) for t in page], limit, offset, total)


@app.route("/scouting/free-agent-targets/<tid>", methods=["GET"])
def get_target(tid):
    caller = authenticate()
    require_roles(caller, "GeneralManager", "ScoutingDirector")
    t = DB.targets.get(tid)
    if not t:
        raise err_not_found("Free-agent target not found")
    return ok_object(target_out(t))


@app.route("/scouting/free-agent-targets/<tid>/advance", methods=["POST"])
def advance_target(tid):
    caller = authenticate()
    require_roles(caller, "GeneralManager")
    t = DB.targets.get(tid)
    if not t:
        raise err_not_found("Free-agent target not found")
    data = body()
    to_state = req_field(data, "to_state")
    if to_state not in ("EVALUATING", "APPROVED", "OFFERED"):
        raise err_validation("to_state must be EVALUATING, APPROVED, or OFFERED")
    cur = t["status"]
    allowed = (
        (to_state == "EVALUATING" and cur == "IDENTIFIED")
        or (to_state == "APPROVED" and cur == "EVALUATING")
        or (to_state == "OFFERED" and cur == "APPROVED")
    )
    if not allowed:
        raise ApiError("ERR_INVALID_STATE", f"Cannot advance target from {cur} to {to_state}", 409)
    if to_state == "APPROVED":
        has_need = any(
            n for n in DB.needs.values()
            if n["position"] == t["position"]
            and n["season_year"] == t["season_year"]
            and n["status"] == "OPEN"
        )
        if not has_need:
            raise ApiError("ERR_NO_ROSTER_NEED", "No OPEN roster need matches position and season_year", 409)
    t["status"] = to_state
    touch(t)
    return ok_object(target_out(t))


@app.route("/scouting/free-agent-targets/<tid>/sign", methods=["POST"])
def sign_target(tid):
    caller = authenticate()
    require_roles(caller, "GeneralManager")
    data = body()
    budget_id = req_field(data, "budget_id")
    if not isinstance(budget_id, str):
        raise err_validation("budget_id must be a string")
    t = DB.targets.get(tid)
    if not t:
        raise err_not_found("Free-agent target not found")
    b = DB.budgets.get(budget_id)
    if not b:
        raise err_not_found("Budget not found")
    if t["status"] != "OFFERED":
        raise ApiError("ERR_TARGET_NOT_OFFERED", f"Target is in state {t['status']}, not OFFERED", 409)
    if t["annual_cap_hit_cents"] > b["available_cents"]:
        raise ApiError("ERR_BUDGET_EXCEEDED", "annual_cap_hit_cents exceeds available_cents", 422)
    t["status"] = "SIGNED"
    t["signed_budget_id"] = budget_id
    touch(t)
    recompute_budget(b)
    touch(b)
    return ok_object(target_out(t))


@app.route("/scouting/free-agent-targets/<tid>/release", methods=["POST"])
def release_target(tid):
    caller = authenticate()
    require_roles(caller, "GeneralManager")
    t = DB.targets.get(tid)
    if not t:
        raise err_not_found("Free-agent target not found")
    if t["status"] != "SIGNED":
        raise ApiError("ERR_INVALID_STATE", f"Cannot release a target in state {t['status']}", 409)
    budget_id = t["signed_budget_id"]
    t["status"] = "RELEASED"
    touch(t)
    b = DB.budgets.get(budget_id)
    if b:
        recompute_budget(b)
        touch(b)
    return ok_object(target_out(t))


@app.route("/scouting/free-agent-targets/<tid>/pass", methods=["POST"])
def pass_target(tid):
    caller = authenticate()
    require_roles(caller, "GeneralManager")
    t = DB.targets.get(tid)
    if not t:
        raise err_not_found("Free-agent target not found")
    if t["status"] not in ("IDENTIFIED", "EVALUATING", "APPROVED", "OFFERED"):
        raise ApiError("ERR_INVALID_STATE", f"Cannot pass on a target in state {t['status']}", 409)
    t["status"] = "PASSED"
    touch(t)
    return ok_object(target_out(t))


# ---------------------------------------------------------------------------
# Budgets
# ---------------------------------------------------------------------------


@app.route("/scouting/budgets", methods=["POST"])
def create_budget():
    caller = authenticate()
    require_roles(caller, "GeneralManager")
    data = body()
    season_year = as_int(req_field(data, "season_year"), "season_year")
    base_cap = as_int(req_field(data, "base_cap_cents"), "base_cap_cents", minimum=0)
    rollover = as_int(req_field(data, "rollover_cents"), "rollover_cents", minimum=0)
    b = stamp_new({
        "season_year": season_year,
        "base_cap_cents": base_cap,
        "rollover_cents": rollover,
        "committed_cents": 0,
        "available_cents": base_cap + rollover,
        "posture": "HEALTHY",
    })
    # Compute posture properly
    recompute_budget(b)
    DB.budgets[b["id"]] = b
    return ok_object(budget_out(b), 201)


@app.route("/scouting/budgets/<bid>", methods=["GET"])
def get_budget(bid):
    caller = authenticate()
    require_roles(caller, "GeneralManager", "ScoutingDirector")
    b = DB.budgets.get(bid)
    if not b:
        raise err_not_found("Budget not found")
    return ok_object(budget_out(b))


@app.route("/scouting/budgets/<bid>/adjustments", methods=["POST"])
def adjust_budget(bid):
    caller = authenticate()
    require_roles(caller, "GeneralManager")
    data = body()
    delta = req_field(data, "rollover_delta_cents")
    expected = req_field(data, "expected_budget_version")
    delta = as_int(delta, "rollover_delta_cents")
    expected = as_int(expected, "expected_budget_version", minimum=0)
    b = DB.budgets.get(bid)
    if not b:
        raise err_not_found("Budget not found")
    if expected != b["version"]:
        raise ApiError("ERR_STALE_VERSION", "expected_budget_version does not match current budget version", 412)
    new_rollover = b["rollover_cents"] + delta
    if new_rollover < 0:
        raise ApiError("ERR_BUDGET_EXCEEDED", "Adjustment would drive rollover below zero", 422)
    new_available = b["base_cap_cents"] + new_rollover - b["committed_cents"]
    if new_available < 0:
        raise ApiError("ERR_BUDGET_EXCEEDED", "Adjustment would drive available_cents below zero", 422)
    b["rollover_cents"] = new_rollover
    recompute_budget(b)
    touch(b)
    return ok_object(budget_out(b))


# ---------------------------------------------------------------------------
# Interviews
# ---------------------------------------------------------------------------


@app.route("/scouting/prospects/<pid>/interviews", methods=["POST"])
def create_interview(pid):
    caller = authenticate()
    require_roles(caller, "AreaScout", "ScoutingDirector")
    data = body()
    start_at_s = req_field(data, "start_at")
    end_at_s = req_field(data, "end_at")
    location = as_string(req_field(data, "location"), "location")
    if not isinstance(start_at_s, str) or not isinstance(end_at_s, str):
        raise err_validation("start_at and end_at must be ISO 8601 strings")
    try:
        start_dt = parse_iso(start_at_s)
        end_dt = parse_iso(end_at_s)
    except ValueError:
        raise err_validation("start_at and end_at must be valid ISO 8601 timestamps")
    if not (end_dt > start_dt):
        raise err_validation("end_at must be strictly after start_at")
    p = DB.prospects.get(pid)
    if not p:
        raise err_not_found("Prospect not found")
    if p["flag_status"] == "UNDER_REVIEW":
        raise ApiError("ERR_FLAG_REVIEW_OPEN", "Prospect has an open confidential review", 409)
    # Half-open overlap check against SCHEDULED sessions
    for s in DB.interviews.values():
        if s["prospect_id"] != pid or s["status"] != "SCHEDULED":
            continue
        s_start = parse_iso(s["start_at"])
        s_end = parse_iso(s["end_at"])
        # overlap iff new.start < existing.end and new.end > existing.start
        if start_dt < s_end and end_dt > s_start:
            raise ApiError("ERR_INTERVIEW_OVERLAP", "Session overlaps an existing SCHEDULED session", 409)
    i = stamp_new({
        "prospect_id": pid,
        "start_at": iso_fmt(start_dt),
        "end_at": iso_fmt(end_dt),
        "location": location,
        "status": "SCHEDULED",
    })
    DB.interviews[i["id"]] = i
    return ok_object(interview_out(i), 201)


@app.route("/scouting/interviews/<iid>/cancel", methods=["POST"])
def cancel_interview(iid):
    caller = authenticate()
    require_roles(caller, "AreaScout", "ScoutingDirector")
    i = DB.interviews.get(iid)
    if not i:
        raise err_not_found("Interview not found")
    if i["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", f"Cannot cancel an interview in state {i['status']}", 409)
    i["status"] = "CANCELLED"
    touch(i)
    return ok_object(interview_out(i))


@app.route("/scouting/prospects/<pid>/interviews", methods=["GET"])
def list_interviews(pid):
    caller = authenticate()
    require_roles(caller, "GeneralManager", "ScoutingDirector", "AreaScout", "MedicalStaff")
    p = DB.prospects.get(pid)
    if not p:
        raise err_not_found("Prospect not found")
    limit, offset = parse_pagination()
    items = [i for i in DB.interviews.values() if i["prospect_id"] == pid]
    st = request.args.get("status")
    if st is not None:
        items = [i for i in items if i["status"] == st]
    items.sort(key=lambda i: i["created_at"])
    page, total = paginate(items, limit, offset)
    return ok_list([interview_out(i) for i in page], limit, offset, total)


# ---------------------------------------------------------------------------
# Facilities & bookings
# ---------------------------------------------------------------------------


@app.route("/scouting/facilities", methods=["POST"])
def create_facility():
    caller = authenticate()
    require_roles(caller, "GeneralManager")
    data = body()
    name = as_string(req_field(data, "name"), "name")
    capacity = as_int(req_field(data, "capacity"), "capacity", minimum=1)
    f = stamp_new({"name": name, "capacity": capacity})
    DB.facilities[f["id"]] = f
    return ok_object(facility_out(f), 201)


@app.route("/scouting/facilities/<fid>", methods=["GET"])
def get_facility(fid):
    caller = authenticate()
    require_roles(caller, "GeneralManager", "ScoutingDirector")
    f = DB.facilities.get(fid)
    if not f:
        raise err_not_found("Facility not found")
    return ok_object(facility_out(f))


@app.route("/scouting/facilities/<fid>/bookings", methods=["POST"])
def create_booking(fid):
    caller = authenticate()
    require_roles(caller, "GeneralManager", "ScoutingDirector")
    data = body()
    start_at_s = req_field(data, "start_at")
    end_at_s = req_field(data, "end_at")
    purpose = as_string(req_field(data, "purpose"), "purpose")
    if not isinstance(start_at_s, str) or not isinstance(end_at_s, str):
        raise err_validation("start_at and end_at must be ISO 8601 strings")
    try:
        start_dt = parse_iso(start_at_s)
        end_dt = parse_iso(end_at_s)
    except ValueError:
        raise err_validation("start_at and end_at must be valid ISO 8601 timestamps")
    if not (end_dt > start_dt):
        raise err_validation("end_at must be strictly after start_at")
    f = DB.facilities.get(fid)
    if not f:
        raise err_not_found("Facility not found")
    buffer = timedelta(minutes=30)
    for bk in DB.bookings.values():
        if bk["facility_id"] != fid:
            continue
        b_start = parse_iso(bk["start_at"])
        b_end = parse_iso(bk["end_at"])
        ok = (start_dt >= b_end + buffer) or (end_dt <= b_start - buffer)
        if not ok:
            raise ApiError("ERR_FACILITY_BUFFER_CONFLICT",
                           "Booking leaves less than a 30-minute gap against an existing booking", 409)
    bk = stamp_new({
        "facility_id": fid,
        "start_at": iso_fmt(start_dt),
        "end_at": iso_fmt(end_dt),
        "purpose": purpose,
    })
    DB.bookings[bk["id"]] = bk
    return ok_object(booking_out(bk), 201)


@app.route("/scouting/facilities/<fid>/bookings", methods=["GET"])
def list_bookings(fid):
    caller = authenticate()
    require_roles(caller, "GeneralManager", "ScoutingDirector")
    f = DB.facilities.get(fid)
    if not f:
        raise err_not_found("Facility not found")
    limit, offset = parse_pagination()
    items = [b for b in DB.bookings.values() if b["facility_id"] == fid]
    items.sort(key=lambda b: b["created_at"])
    page, total = paginate(items, limit, offset)
    return ok_list([booking_out(b) for b in page], limit, offset, total)


# ---------------------------------------------------------------------------
# Outcomes
# ---------------------------------------------------------------------------


@app.route("/scouting/prospects/<pid>/outcomes", methods=["POST"])
def create_outcome(pid):
    caller = authenticate()
    require_roles(caller, "GeneralManager")
    data = body()
    season_year = as_int(req_field(data, "season_year"), "season_year")
    games_started = as_int(req_field(data, "games_started"), "games_started", minimum=0)
    pro_bowl = as_bool(req_field(data, "pro_bowl"), "pro_bowl")
    outcome_percentile = as_int(req_field(data, "outcome_percentile"), "outcome_percentile", minimum=0)
    if outcome_percentile > 100:
        raise err_validation("outcome_percentile must be in [0, 100]")
    p = DB.prospects.get(pid)
    if not p:
        raise err_not_found("Prospect not found")
    if p["evaluation_status"] != "DRAFTED":
        raise ApiError("ERR_OUTCOME_NOT_DRAFTED", "Outcomes may only be recorded for DRAFTED prospects", 409)
    o = stamp_new({
        "prospect_id": pid,
        "season_year": season_year,
        "games_started": games_started,
        "pro_bowl": pro_bowl,
        "outcome_percentile": outcome_percentile,
    })
    DB.outcomes[o["id"]] = o
    return ok_object(outcome_out(o), 201)


@app.route("/scouting/prospects/<pid>/outcomes", methods=["GET"])
def list_outcomes(pid):
    caller = authenticate()
    require_roles(caller, "GeneralManager", "ScoutingDirector")
    p = DB.prospects.get(pid)
    if not p:
        raise err_not_found("Prospect not found")
    limit, offset = parse_pagination()
    items = [o for o in DB.outcomes.values() if o["prospect_id"] == pid]
    items.sort(key=lambda o: o["created_at"])
    page, total = paginate(items, limit, offset)
    return ok_list([outcome_out(o) for o in page], limit, offset, total)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
