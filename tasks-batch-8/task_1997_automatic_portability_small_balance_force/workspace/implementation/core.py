"""Core infrastructure: logical clock, in-memory store, errors, envelope, auth,
validators, serializers, and shared domain helpers for the Automatic
Portability & Small-Balance Force-Out API.

All state lives in module-level dicts (in-memory only). The store starts empty
on every boot; all entities are constructed through the API.
"""

import re
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import request, jsonify


# ---------------------------------------------------------------------------
# Logical clock (PRD §2.4): deterministic, never wall-clock for domain logic.
# Startup default is exactly 2026-08-01T00:00:00Z.
# ---------------------------------------------------------------------------
class _Clock:
    current = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


def now():
    return _Clock.current


def set_clock(dt):
    _Clock.current = dt


# ---------------------------------------------------------------------------
# Datetime helpers — ISO 8601 UTC with three fractional digits everywhere.
# ---------------------------------------------------------------------------
def fmt_dt(dt):
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_dt(value):
    """Parse an ISO-8601 datetime (accepts trailing Z, fractional seconds,
    or a bare YYYY-MM-DD date). Returns an aware UTC datetime or None."""
    if not isinstance(value, str):
        return None
    s = value.strip()
    if not s:
        return None
    if s.endswith("Z") or s.endswith("z"):
        s = s[:-1] + "+00:00"
    try:
        d = datetime.fromisoformat(s)
    except ValueError:
        return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.astimezone(timezone.utc)


def is_date_str(value):
    """True when value is a valid YYYY-MM-DD calendar date string."""
    if not isinstance(value, str):
        return False
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return False
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        return False
    return True


# ---------------------------------------------------------------------------
# Errors (PRD §5 catalogue)
# ---------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, error_id, status, message):
        super().__init__(message)
        self.error_id = error_id
        self.status = status
        self.message = message


def err_400(msg):
    return ApiError("ERR_INVALID_REQUEST", 400, msg)


def err_404(what, rid):
    return ApiError("ERR_NOT_FOUND", 404, f"{what} not found: {rid}")


def err_409(msg):
    return ApiError("ERR_INVALID_STATE", 409, msg)


def err_422(error_id, msg):
    return ApiError(error_id, 422, msg)


# ---------------------------------------------------------------------------
# In-memory store — empty at every boot.
# ---------------------------------------------------------------------------
class DB:
    recordkeepers = {}
    plans = {}
    participants = {}
    batches = {}
    cases = {}
    notices = {}
    elections = {}
    iras = {}
    fees = {}
    checks = {}
    matches = {}
    transfers = {}
    reviews = {}


def new_id():
    return str(uuid.uuid4())


def stamp_new(entity, common=True):
    """Apply system-managed common fields on creation (PRD §2.5)."""
    entity["id"] = new_id()
    entity["created_at"] = now()
    if common:
        entity["updated_at"] = now()
        entity["version"] = 1
    return entity


def touch(entity):
    """Bump version and refresh updated_at on a mutation (PRD §2.5)."""
    entity["version"] += 1
    entity["updated_at"] = now()


def get_or_404(store, rid, what):
    it = store.get(rid)
    if it is None:
        raise err_404(what, rid)
    return it


# ---------------------------------------------------------------------------
# Response envelope (PRD §2.2)
# ---------------------------------------------------------------------------
def _meta():
    return {
        "api_request_id": "req_" + uuid.uuid4().hex,
        "api_request_timestamp": fmt_dt(datetime.now(timezone.utc)),
    }


def success(data, rtype="object", status=200, pagination=None):
    m = _meta()
    if pagination is not None:
        m.update(pagination)
    return jsonify({"meta": m, "response_type": rtype, "data": data}), status


def error_response(e):
    return jsonify({
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": e.error_id, "message": e.message},
    }), e.status


# ---------------------------------------------------------------------------
# Auth (PRD §2.1) — X-User-ID + X-User-Role on every request.
# ---------------------------------------------------------------------------
DECLARED_ROLES = ("Participant", "PlanSponsor", "ProviderOps", "FiduciaryReviewer")


def auth():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in DECLARED_ROLES:
        raise ApiError(
            "ERR_UNAUTHENTICATED", 401,
            "X-User-ID and X-User-Role headers are required and the role must be a declared role",
        )
    return uid, role


def require_roles(*allowed):
    uid, role = auth()
    if role not in allowed:
        raise ApiError(
            "ERR_FORBIDDEN_ROLE", 403,
            f"Role {role} is not authorized for this operation",
        )
    return uid, role


ALL_ROLES = DECLARED_ROLES


# ---------------------------------------------------------------------------
# Request body + field validators (priority-4 shape checks)
# ---------------------------------------------------------------------------
MISSING = object()


def get_body():
    import json
    raw = request.get_data()
    if raw is None or raw == b"":
        return {}
    try:
        b = json.loads(raw)
    except Exception:
        raise err_400("Request body must be a valid JSON object")
    if not isinstance(b, dict):
        raise err_400("Request body must be a JSON object")
    return b


def v_req_str(b, k):
    v = b.get(k, MISSING)
    if v is MISSING or not isinstance(v, str) or v == "":
        raise err_400(f"Missing or invalid required field: {k}")
    return v


def v_opt_str(b, k, default=None):
    v = b.get(k, MISSING)
    if v is MISSING:
        return default
    if not isinstance(v, str):
        raise err_400(f"Field must be a string: {k}")
    return v


def _check_int(v, k, minv, maxv):
    if isinstance(v, bool) or not isinstance(v, int):
        raise err_400(f"Field must be an integer: {k}")
    if minv is not None and v < minv:
        raise err_400(f"Field {k} must be >= {minv}")
    if maxv is not None and v > maxv:
        raise err_400(f"Field {k} must be <= {maxv}")
    return v


def v_req_int(b, k, minv=None, maxv=None):
    v = b.get(k, MISSING)
    if v is MISSING:
        raise err_400(f"Missing required field: {k}")
    return _check_int(v, k, minv, maxv)


def v_opt_int(b, k, default=None, minv=None, maxv=None):
    v = b.get(k, MISSING)
    if v is MISSING:
        return default
    return _check_int(v, k, minv, maxv)


def v_req_bool(b, k):
    v = b.get(k, MISSING)
    if v is MISSING or not isinstance(v, bool):
        raise err_400(f"Missing or invalid required boolean field: {k}")
    return v


def v_opt_bool(b, k, default=None):
    v = b.get(k, MISSING)
    if v is MISSING:
        return default
    if not isinstance(v, bool):
        raise err_400(f"Field must be a boolean: {k}")
    return v


def v_req_num(b, k):
    v = b.get(k, MISSING)
    if v is MISSING or isinstance(v, bool) or not isinstance(v, (int, float)):
        raise err_400(f"Missing or invalid required numeric field: {k}")
    return v


def v_opt_num(b, k, default=None):
    v = b.get(k, MISSING)
    if v is MISSING:
        return default
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise err_400(f"Field must be a number: {k}")
    return v


def v_req_enum(b, k, allowed):
    v = b.get(k, MISSING)
    if v is MISSING or not isinstance(v, str) or v not in allowed:
        raise err_400(f"Field {k} must be one of {sorted(allowed)}")
    return v


def v_req_version(b, k):
    """OCC expected_*_version fields: accept int or digit-string."""
    v = b.get(k, MISSING)
    if v is MISSING:
        raise err_400(f"Missing required field: {k}")
    if isinstance(v, bool):
        raise err_400(f"Field must be an integer: {k}")
    if isinstance(v, int):
        return v
    if isinstance(v, str) and re.fullmatch(r"-?\d+", v):
        return int(v)
    raise err_400(f"Field must be an integer: {k}")


def v_req_dt(b, k):
    v = b.get(k, MISSING)
    d = parse_dt(v) if v is not MISSING else None
    if d is None:
        raise err_400(f"Missing or invalid required datetime field: {k}")
    return d


def v_req_date(b, k):
    v = b.get(k, MISSING)
    if not is_date_str(v):
        raise err_400(f"Missing or invalid required date field (YYYY-MM-DD): {k}")
    return v


# ---------------------------------------------------------------------------
# Pagination + filters (PRD §2.3): limit (default 10, min 1, max 100),
# offset (default 0); results sorted by creation timestamp ascending
# (insertion order — dicts preserve it and all timestamps come from the
# same logical clock).
# ---------------------------------------------------------------------------
def list_response(items, serializer, filter_params):
    out = []
    for it in items:
        ok = True
        for param in filter_params:
            q = request.args.get(param)
            if q is not None and str(it.get(param)) != q:
                ok = False
                break
        if ok:
            out.append(it)

    limit = 10
    offset = 0
    raw_limit = request.args.get("limit")
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise err_400("limit must be an integer")
        limit = max(1, min(100, limit))
    raw_offset = request.args.get("offset")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise err_400("offset must be an integer")
        offset = max(0, offset)

    total = len(out)
    page = out[offset:offset + limit]
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + len(page)) < total,
    }
    return success([serializer(x) for x in page], "array", 200, pagination)


# ---------------------------------------------------------------------------
# Money / scoring calculations (PRD §2.6, §3; SCAFFOLD §1.3)
# ---------------------------------------------------------------------------
def rhu_ratio(numer, denom):
    """round_half_up(numer / denom) to integer cents."""
    return int((Decimal(numer) / Decimal(denom)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def rhu_product(amount_cents, rate):
    """round_half_up(amount_cents * rate) to integer cents; rate given as a
    JSON number (int/float), converted via str() to stay exact."""
    return int((Decimal(amount_cents) * Decimal(str(rate))).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def vested_balance(selected_balance, vesting_percent):
    return rhu_ratio(selected_balance * vesting_percent, 100)


def force_out_path(vested_cents, plan):
    if vested_cents <= plan["cash_out_threshold_cents"]:
        return "CASH_OUT"
    if vested_cents <= plan["rollover_threshold_cents"]:
        return "SAFE_HARBOR_IRA"
    return "INELIGIBLE_REMAINS"


FED_WITHHOLDING_RATE = "0.20"


def net_check_withholding(gross_cents, state_rate):
    """Pinned per-component rounding order (SCAFFOLD net_check_withholding)."""
    fed = int((Decimal(gross_cents) * Decimal(FED_WITHHOLDING_RATE)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    state = rhu_product(gross_cents, state_rate)
    return fed, state, gross_cents - fed - state


ANNUAL_FEE_CENTS = 6000


def fee_day_count(convention, anchor, end):
    """Days in the accrual period (anchor, end]."""
    if convention == "ACTUAL_365":
        return (end.date() - anchor.date()).days
    a, b = anchor, end
    return 30 * (b.month - a.month) + min(b.day, 30) - min(a.day, 30) + 360 * (b.year - a.year)


def fee_for_days(convention, days):
    div = 365 if convention == "ACTUAL_365" else 360
    return int((Decimal(ANNUAL_FEE_CENTS) * Decimal(days) / Decimal(div)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def accrued_fee(ira, end):
    """Unbilled fee from the fee anchor to `end`, WITHOUT the balance cap."""
    anchor = ira["last_fee_assessed_at"] or ira["opened_at"]
    days = fee_day_count(ira["fee_day_count_convention"], anchor, end)
    return fee_for_days(ira["fee_day_count_convention"], days), anchor, days


W_SSN = Decimal("0.55")
W_NAME = Decimal("0.30")
W_DOB = Decimal("0.15")
AUTO_CONFIRM = Decimal("0.850")
CONFIRM_FLOOR = Decimal("0.650")
REVIEW_FLOOR = Decimal("0.400")


def compute_match_score(ssn_exact, name_similarity, dob_match):
    s = (W_SSN * (1 if ssn_exact else 0)
         + W_NAME * Decimal(str(name_similarity))
         + W_DOB * (1 if dob_match else 0))
    return s.quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)


NOTICE_WINDOW_DAYS = 30
CHECK_STALE_DAYS = 180
ESCHEAT_WARNING_LEAD_DAYS = 90
ESCHEAT_DORMANCY_DAYS = 1095
MATCH_EXPIRY_DAYS = 90


# ---------------------------------------------------------------------------
# Domain helpers
# ---------------------------------------------------------------------------
def recompute_reachable(plan):
    """network_reachable is derived (PRD §2.8): recordkeeper ACTIVE and the
    plan's accepts_incoming_transfers flag; a TERMINATED plan is never
    reachable (PRD §3.1)."""
    rk = DB.recordkeepers.get(plan["recordkeeper_id"])
    return bool(
        rk
        and rk["network_status"] == "ACTIVE"
        and plan["accepts_incoming_transfers"]
        and plan["plan_status"] == "ACTIVE"
    )


def batch_counters(batch):
    """batch_reconciliation_totals over the cases of this batch only."""
    cs = [c for c in DB.cases.values() if c["distribution_batch_id"] == batch["id"]]
    case_count = len(cs)
    settled = sum(1 for c in cs if c["case_status"] in ("SETTLED", "ESCHEATED", "CANCELLED"))
    total = sum(
        c["vested_balance_cents"] or 0
        for c in cs
        if c["executed_path"] in ("CHECK_CASH_OUT", "SAFE_HARBOR_IRA", "DIRECT_NEW_PLAN")
    )
    return case_count, settled, total


def cases_of_batch(batch_id):
    return [c for c in DB.cases.values() if c["distribution_batch_id"] == batch_id]


def current_notice(case):
    nid = case.get("current_notice_id")
    if nid is None:
        return None
    return DB.notices.get(nid)


def submitted_election(case_id):
    for e in DB.elections.values():
        if e["distribution_case_id"] == case_id and e["election_status"] == "SUBMITTED":
            return e
    return None


def delivered_notice(case_id, ntype):
    """Latest DELIVERED notice of a type for a case, else None."""
    best = None
    for n in DB.notices.values():
        if (n["distribution_case_id"] == case_id and n["notice_type"] == ntype
                and n["delivery_status"] == "DELIVERED" and n["delivered_at"] is not None):
            if best is None or n["delivered_at"] > best["delivered_at"]:
                best = n
    return best


def escheat_warning_matured(case_id, at):
    cutoff = at - timedelta(days=ESCHEAT_WARNING_LEAD_DAYS)
    for n in DB.notices.values():
        if (n["distribution_case_id"] == case_id and n["notice_type"] == "ESCHEAT_WARNING"
                and n["delivery_status"] == "DELIVERED" and n["delivered_at"] is not None
                and n["delivered_at"] <= cutoff):
            return True
    return False


def confirmed_match_of_ira(ira_id):
    for m in DB.matches.values():
        if m["safe_harbor_ira_id"] == ira_id and m["match_status"] == "CONFIRMED":
            return m
    return None


def ira_of_case(case_id):
    for i in DB.iras.values():
        if i["distribution_case_id"] == case_id:
            return i
    return None


def mark_bad_address(participant):
    if participant["address_quality"] != "BAD_ADDRESS":
        participant["address_quality"] = "BAD_ADDRESS"
        touch(participant)


# ---------------------------------------------------------------------------
# Serializers — datetimes rendered with three fractional digits, UTC ("Z").
# ---------------------------------------------------------------------------
def ser_recordkeeper(r):
    return {
        "id": r["id"],
        "recordkeeper_code": r["recordkeeper_code"],
        "legal_name": r["legal_name"],
        "network_status": r["network_status"],
        "exited_at": fmt_dt(r["exited_at"]),
        "created_at": fmt_dt(r["created_at"]),
        "updated_at": fmt_dt(r["updated_at"]),
        "version": r["version"],
    }


def ser_plan(p):
    return {
        "id": p["id"],
        "plan_name": p["plan_name"],
        "sponsor_ein": p["sponsor_ein"],
        "recordkeeper_id": p["recordkeeper_id"],
        "cash_out_threshold_cents": p["cash_out_threshold_cents"],
        "rollover_threshold_cents": p["rollover_threshold_cents"],
        "state_withholding_rate": p["state_withholding_rate"],
        "valuation_basis": p["valuation_basis"],
        "auto_portability_enabled": p["auto_portability_enabled"],
        "accepts_incoming_transfers": p["accepts_incoming_transfers"],
        "network_reachable": p["network_reachable"],
        "plan_status": p["plan_status"],
        "created_at": fmt_dt(p["created_at"]),
        "updated_at": fmt_dt(p["updated_at"]),
        "version": p["version"],
    }


def ser_participant(p):
    return {
        "id": p["id"],
        "ssn_hash": p["ssn_hash"],
        "full_name": p["full_name"],
        "date_of_birth": p["date_of_birth"],
        "mailing_address_line1": p["mailing_address_line1"],
        "mailing_city": p["mailing_city"],
        "mailing_state": p["mailing_state"],
        "mailing_zip": p["mailing_zip"],
        "email": p["email"],
        "address_quality": p["address_quality"],
        "created_at": fmt_dt(p["created_at"]),
        "updated_at": fmt_dt(p["updated_at"]),
        "version": p["version"],
    }


def ser_batch(b):
    case_count, settled, total = batch_counters(b)
    return {
        "id": b["id"],
        "plan_id": b["plan_id"],
        "batch_status": b["batch_status"],
        "executed_by_user_id": b["executed_by_user_id"],
        "locked_at": fmt_dt(b["locked_at"]),
        "executed_at": fmt_dt(b["executed_at"]),
        "reconciled_at": fmt_dt(b["reconciled_at"]),
        "case_count": case_count,
        "settled_case_count": settled,
        "total_forced_out_cents": total,
        "created_at": fmt_dt(b["created_at"]),
        "updated_at": fmt_dt(b["updated_at"]),
        "version": b["version"],
    }


def ser_case(c):
    return {
        "id": c["id"],
        "distribution_batch_id": c["distribution_batch_id"],
        "plan_id": c["plan_id"],
        "participant_id": c["participant_id"],
        "separation_date": fmt_dt(c["separation_date"]),
        "separation_date_balance_cents": c["separation_date_balance_cents"],
        "processing_date_balance_cents": c["processing_date_balance_cents"],
        "vesting_percent": c["vesting_percent"],
        "quoted_balance_cents": c["quoted_balance_cents"],
        "vested_balance_cents": c["vested_balance_cents"],
        "force_out_path": c["force_out_path"],
        "case_status": c["case_status"],
        "executed_path": c["executed_path"],
        "current_notice_id": c["current_notice_id"],
        "created_at": fmt_dt(c["created_at"]),
        "updated_at": fmt_dt(c["updated_at"]),
        "version": c["version"],
    }


def ser_notice(n):
    return {
        "id": n["id"],
        "distribution_case_id": n["distribution_case_id"],
        "notice_type": n["notice_type"],
        "delivery_status": n["delivery_status"],
        "sent_at": fmt_dt(n["sent_at"]),
        "delivered_at": fmt_dt(n["delivered_at"]),
        "response_deadline": fmt_dt(n["response_deadline"]),
        "created_at": fmt_dt(n["created_at"]),
        "updated_at": fmt_dt(n["updated_at"]),
        "version": n["version"],
    }


def ser_election(e):
    return {
        "id": e["id"],
        "distribution_case_id": e["distribution_case_id"],
        "participant_id": e["participant_id"],
        "election_type": e["election_type"],
        "destination_plan_id": e["destination_plan_id"],
        "election_status": e["election_status"],
        "submitted_at": fmt_dt(e["submitted_at"]),
        "created_at": fmt_dt(e["created_at"]),
        "updated_at": fmt_dt(e["updated_at"]),
        "version": e["version"],
    }


def ser_ira(i):
    return {
        "id": i["id"],
        "distribution_case_id": i["distribution_case_id"],
        "participant_id": i["participant_id"],
        "ira_origin": i["ira_origin"],
        "ira_status": i["ira_status"],
        "funded_amount_cents": i["funded_amount_cents"],
        "balance_cents": i["balance_cents"],
        "in_flight_cents": i["in_flight_cents"],
        "total_fees_cents": i["total_fees_cents"],
        "total_transferred_out_cents": i["total_transferred_out_cents"],
        "fee_day_count_convention": i["fee_day_count_convention"],
        "default_investment": i["default_investment"],
        "last_fee_assessed_at": fmt_dt(i["last_fee_assessed_at"]),
        "last_activity_at": fmt_dt(i["last_activity_at"]),
        "opened_at": fmt_dt(i["opened_at"]),
        "created_at": fmt_dt(i["created_at"]),
        "updated_at": fmt_dt(i["updated_at"]),
        "version": i["version"],
    }


def ser_fee(f):
    # Append-only ledger: id and created_at only — no updated_at, no version.
    return {
        "id": f["id"],
        "safe_harbor_ira_id": f["safe_harbor_ira_id"],
        "period_start": fmt_dt(f["period_start"]),
        "period_end": fmt_dt(f["period_end"]),
        "days_in_period": f["days_in_period"],
        "day_count_convention": f["day_count_convention"],
        "amount_cents": f["amount_cents"],
        "created_at": fmt_dt(f["created_at"]),
    }


def ser_check(c):
    return {
        "id": c["id"],
        "distribution_case_id": c["distribution_case_id"],
        "supersedes_check_id": c["supersedes_check_id"],
        "origin": c["origin"],
        "gross_amount_cents": c["gross_amount_cents"],
        "fed_withholding_cents": c["fed_withholding_cents"],
        "state_withholding_cents": c["state_withholding_cents"],
        "amount_cents": c["amount_cents"],
        "check_status": c["check_status"],
        "issued_at": fmt_dt(c["issued_at"]),
        "stale_after": fmt_dt(c["stale_after"]),
        "cashed_at": fmt_dt(c["cashed_at"]),
        "voided_at": fmt_dt(c["voided_at"]),
        "void_reason": c["void_reason"],
        "created_at": fmt_dt(c["created_at"]),
        "updated_at": fmt_dt(c["updated_at"]),
        "version": c["version"],
    }


def ser_match(m):
    return {
        "id": m["id"],
        "safe_harbor_ira_id": m["safe_harbor_ira_id"],
        "participant_id": m["participant_id"],
        "new_plan_id": m["new_plan_id"],
        "new_recordkeeper_id": m["new_recordkeeper_id"],
        "employment_start_date": m["employment_start_date"],
        "ssn_exact": m["ssn_exact"],
        "name_similarity": m["name_similarity"],
        "dob_match": m["dob_match"],
        "match_score": float(m["match_score"]),
        "match_status": m["match_status"],
        "created_at": fmt_dt(m["created_at"]),
        "updated_at": fmt_dt(m["updated_at"]),
        "version": m["version"],
    }


def ser_transfer(t):
    return {
        "id": t["id"],
        "safe_harbor_ira_id": t["safe_harbor_ira_id"],
        "match_candidate_id": t["match_candidate_id"],
        "amount_cents": t["amount_cents"],
        "accrued_fee_offset_cents": t["accrued_fee_offset_cents"],
        "transfer_status": t["transfer_status"],
        "sent_at": fmt_dt(t["sent_at"]),
        "settled_at": fmt_dt(t["settled_at"]),
        "rejection_reason": t["rejection_reason"],
        "created_at": fmt_dt(t["created_at"]),
        "updated_at": fmt_dt(t["updated_at"]),
        "version": t["version"],
    }


def ser_review(r):
    return {
        "id": r["id"],
        "distribution_batch_id": r["distribution_batch_id"],
        "plan_id": r["plan_id"],
        "period_start": fmt_dt(r["period_start"]),
        "period_end": fmt_dt(r["period_end"]),
        "reviewer_user_id": r["reviewer_user_id"],
        "review_status": r["review_status"],
        "findings_count": r["findings_count"],
        "attested_at": fmt_dt(r["attested_at"]),
        "created_at": fmt_dt(r["created_at"]),
        "updated_at": fmt_dt(r["updated_at"]),
        "version": r["version"],
    }
