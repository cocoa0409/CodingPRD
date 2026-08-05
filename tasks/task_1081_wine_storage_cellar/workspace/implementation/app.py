"""Wine-Storage & Cellar Management API (Flask, in-memory)."""
import os
from flask import Flask, request, jsonify
from decimal import Decimal

import store as S

app = Flask(__name__)


# ---------------------------------------------------------------------------
# Error type + envelope
# ---------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


def _meta(extra=None):
    m = {"api_request_id": S.request_id(), "api_request_timestamp": S.meta_timestamp()}
    if extra:
        m.update(extra)
    return m


def ok(data, status=200, response_type="object", meta_extra=None):
    body = {"meta": _meta(meta_extra), "response_type": response_type, "data": data}
    return jsonify(body), status


def list_ok(rows, limit, offset, serializer):
    rows = sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))
    total = len(rows)
    page = rows[offset:offset + limit]
    data = [serializer(r) for r in page]
    meta_extra = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(page) < total,
    }
    return ok(data, 200, "array", meta_extra)


@app.errorhandler(ApiError)
def handle_api_error(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


@app.errorhandler(404)
def handle_404(e):
    body = {"meta": _meta(), "response_type": "error",
            "data": {"error_id": "ERR_NOT_FOUND", "message": "Resource not found"}}
    return jsonify(body), 404


@app.errorhandler(405)
def handle_405(e):
    body = {"meta": _meta(), "response_type": "error",
            "data": {"error_id": "ERR_NOT_FOUND", "message": "Method not allowed"}}
    return jsonify(body), 404


# ---------------------------------------------------------------------------
# Auth / authorization
# ---------------------------------------------------------------------------
def authenticate():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in S.ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", 401, "Missing or invalid authentication headers")
    return uid, role


def authorize(role, allowed):
    if role not in allowed:
        raise ApiError("ERR_UNAUTHORIZED", 403, "Role not permitted for this operation")


def own_check(role, uid, owner_member_id):
    if role == "CellarMember" and owner_member_id != uid:
        raise ApiError("ERR_UNAUTHORIZED", 403, "Not the owner of the target resource")


# ---------------------------------------------------------------------------
# Body / field validation
# ---------------------------------------------------------------------------
def body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ApiError("ERR_VALIDATION", 400, "Request body must be a JSON object")
    return data


def v_required(data, field):
    if field not in data or data[field] is None:
        raise ApiError("ERR_VALIDATION", 400, f"Missing required field: {field}")
    return data[field]


def v_str(value, field):
    if not isinstance(value, str) or value == "":
        raise ApiError("ERR_VALIDATION", 400, f"Field {field} must be a non-empty string")
    return value


def v_enum(value, field, allowed):
    if value not in allowed:
        raise ApiError("ERR_VALIDATION", 400, f"Field {field} must be one of {sorted(allowed)}")
    return value


def v_int(value, field, minimum=None):
    if isinstance(value, bool) or not isinstance(value, int):
        raise ApiError("ERR_VALIDATION", 400, f"Field {field} must be an integer")
    if minimum is not None and value < minimum:
        raise ApiError("ERR_VALIDATION", 400, f"Field {field} must be >= {minimum}")
    return value


def v_number(value, field):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ApiError("ERR_VALIDATION", 400, f"Field {field} must be a number")
    return value


def parse_pagination():
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args:
        try:
            limit = int(args["limit"])
        except (ValueError, TypeError):
            raise ApiError("ERR_VALIDATION", 400, "limit must be an integer")
        if limit < 1 or limit > 100:
            raise ApiError("ERR_VALIDATION", 400, "limit must be between 1 and 100")
    if "offset" in args:
        try:
            offset = int(args["offset"])
        except (ValueError, TypeError):
            raise ApiError("ERR_VALIDATION", 400, "offset must be an integer")
        if offset < 0:
            raise ApiError("ERR_VALIDATION", 400, "offset must be >= 0")
    return limit, offset


# ---------------------------------------------------------------------------
# Existence helpers
# ---------------------------------------------------------------------------
def get_or_404(coll, rid):
    row = coll.get(rid)
    if row is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Resource not found")
    return row


def post_ledger(member_id, entry_type, amount_cents, reason, rel_type=None, rel_id=None):
    e = {
        "id": S.new_id(),
        "member_id": member_id,
        "entry_type": entry_type,
        "amount_cents": amount_cents,
        "signed_amount_cents": amount_cents if entry_type == "CREDIT" else -amount_cents,
        "reason": reason,
        "related_entity_type": rel_type,
        "related_entity_id": rel_id,
    }
    S.stamp_event(e)
    S.ledger_entries[e["id"]] = e
    return e


# ===========================================================================
# MEMBER
# ===========================================================================
@app.route("/members", methods=["POST"])
def create_member():
    uid, role = authenticate()
    authorize(role, {"CellarManager"})
    data = body()
    full_name = v_str(v_required(data, "full_name"), "full_name")
    email = v_str(v_required(data, "email"), "email")
    tier = v_enum(v_required(data, "membership_tier"), "membership_tier",
                  {"STANDARD", "PREMIUM", "RESERVE"})
    m = {
        "id": S.new_id(),
        "full_name": full_name,
        "email": email,
        "membership_tier": tier,
        "status": "PENDING",
    }
    S.stamp_new(m)
    S.members[m["id"]] = m
    return ok(S.ser_member(m), 201)


@app.route("/members/<member_id>", methods=["GET"])
def get_member(member_id):
    uid, role = authenticate()
    authorize(role, {"CellarMember", "CellarManager", "Appraiser", "InsuranceAgent", "AuctionBroker"})
    m = get_or_404(S.members, member_id)
    own_check(role, uid, m["id"])
    return ok(S.ser_member(m))


@app.route("/members", methods=["GET"])
def list_members():
    uid, role = authenticate()
    authorize(role, {"CellarManager", "InsuranceAgent", "AuctionBroker"})
    limit, offset = parse_pagination()
    rows = list(S.members.values())
    if "membership_tier" in request.args:
        rows = [r for r in rows if r["membership_tier"] == request.args["membership_tier"]]
    if "status" in request.args:
        rows = [r for r in rows if r["status"] == request.args["status"]]
    return list_ok(rows, limit, offset, S.ser_member)


def _member_transition(member_id, allowed_from, to_state):
    uid, role = authenticate()
    authorize(role, {"CellarManager"})
    m = get_or_404(S.members, member_id)
    if m["status"] not in allowed_from:
        raise ApiError("ERR_INVALID_STATE", 409, f"Member not in {allowed_from}")
    return uid, role, m


@app.route("/members/<member_id>/activate", methods=["POST"])
def activate_member(member_id):
    uid, role, m = _member_transition(member_id, {"PENDING"}, "ACTIVE")
    m["status"] = "ACTIVE"
    S.touch(m)
    return ok(S.ser_member(m))


@app.route("/members/<member_id>/suspend", methods=["POST"])
def suspend_member(member_id):
    uid, role, m = _member_transition(member_id, {"ACTIVE"}, "SUSPENDED")
    m["status"] = "SUSPENDED"
    S.touch(m)
    # CASCADE hop1: ASSIGNED lockers -> FROZEN
    for l in S.lockers.values():
        if l["member_id"] == m["id"] and l["status"] == "ASSIGNED":
            l["status"] = "FROZEN"
            S.touch(l)
            # hop2: open movement requests on this locker -> CANCELLED
            for mr in S.movement_requests.values():
                if mr["locker_id"] == l["id"] and mr["status"] in ("REQUESTED", "APPROVED"):
                    mr["status"] = "CANCELLED"
                    S.touch(mr)
            # hop3: reserved/free recomputed automatically (derived)
    return ok(S.ser_member(m))


@app.route("/members/<member_id>/reactivate", methods=["POST"])
def reactivate_member(member_id):
    uid, role, m = _member_transition(member_id, {"SUSPENDED"}, "ACTIVE")
    m["status"] = "ACTIVE"
    S.touch(m)
    for l in S.lockers.values():
        if l["member_id"] == m["id"] and l["status"] == "FROZEN":
            l["status"] = "ASSIGNED"
            S.touch(l)
    return ok(S.ser_member(m))


@app.route("/members/<member_id>/close", methods=["POST"])
def close_member(member_id):
    uid, role = authenticate()
    authorize(role, {"CellarManager"})
    m = get_or_404(S.members, member_id)
    if m["status"] not in ("ACTIVE", "SUSPENDED"):
        raise ApiError("ERR_INVALID_STATE", 409, "Member not ACTIVE/SUSPENDED")
    for l in S.lockers.values():
        if l["member_id"] == m["id"] and l["status"] in ("ASSIGNED", "FROZEN", "MAINTENANCE"):
            raise ApiError("ERR_MEMBER_HAS_ACTIVE_LOCKERS", 409, "Member still holds active lockers")
    if S.wallet_balance(m["id"]) < 0:
        raise ApiError("ERR_OUTSTANDING_BALANCE", 422, "Member has outstanding balance")
    m["status"] = "CLOSED"
    S.touch(m)
    return ok(S.ser_member(m))


@app.route("/members/<member_id>/ledger-adjustments", methods=["POST"])
def member_ledger_adjustment(member_id):
    uid, role = authenticate()
    authorize(role, {"CellarManager"})
    m = get_or_404(S.members, member_id)
    data = body()
    entry_type = v_enum(v_required(data, "entry_type"), "entry_type", {"DEBIT", "CREDIT"})
    amount = v_int(v_required(data, "amount_cents"), "amount_cents", minimum=1)
    reason = v_str(v_required(data, "reason"), "reason")
    rel_type = data.get("related_entity_type")
    rel_id = data.get("related_entity_id")
    e = post_ledger(m["id"], entry_type, amount, reason, rel_type, rel_id)
    return ok(S.ser_ledger(e), 201)


# ===========================================================================
# LEDGER ENTRY (read)
# ===========================================================================
@app.route("/ledger-entries/<ledger_entry_id>", methods=["GET"])
def get_ledger_entry(ledger_entry_id):
    uid, role = authenticate()
    authorize(role, {"CellarMember", "CellarManager", "InsuranceAgent", "AuctionBroker"})
    e = get_or_404(S.ledger_entries, ledger_entry_id)
    own_check(role, uid, e["member_id"])
    return ok(S.ser_ledger(e))


@app.route("/ledger-entries", methods=["GET"])
def list_ledger_entries():
    uid, role = authenticate()
    authorize(role, {"CellarMember", "CellarManager", "InsuranceAgent", "AuctionBroker"})
    limit, offset = parse_pagination()
    rows = list(S.ledger_entries.values())
    if "member_id" in request.args:
        rows = [r for r in rows if r["member_id"] == request.args["member_id"]]
    if "entry_type" in request.args:
        rows = [r for r in rows if r["entry_type"] == request.args["entry_type"]]
    if role == "CellarMember":
        rows = [r for r in rows if r["member_id"] == uid]
    return list_ok(rows, limit, offset, S.ser_ledger)


# ===========================================================================
# LOCKER
# ===========================================================================
@app.route("/lockers", methods=["POST"])
def create_locker():
    uid, role = authenticate()
    authorize(role, {"CellarManager"})
    data = body()
    label = v_str(v_required(data, "label"), "label")
    size_tier = v_enum(v_required(data, "size_tier"), "size_tier", {"SMALL", "MEDIUM", "LARGE"})
    climate_zone = v_enum(v_required(data, "climate_zone"), "climate_zone",
                          {"RED", "WHITE", "SPARKLING"})
    capacity = v_int(v_required(data, "capacity_bottles"), "capacity_bottles", minimum=1)
    l = {
        "id": S.new_id(),
        "label": label,
        "size_tier": size_tier,
        "climate_zone": climate_zone,
        "capacity_bottles": capacity,
        "member_id": None,
        "climate_status": "NOMINAL",
        "status": "AVAILABLE",
    }
    S.stamp_new(l)
    S.lockers[l["id"]] = l
    return ok(S.ser_locker(l), 201)


@app.route("/lockers/<locker_id>", methods=["GET"])
def get_locker(locker_id):
    uid, role = authenticate()
    authorize(role, {"CellarMember", "CellarManager", "Appraiser", "InsuranceAgent", "AuctionBroker"})
    l = get_or_404(S.lockers, locker_id)
    own_check(role, uid, l["member_id"])
    return ok(S.ser_locker(l))


@app.route("/lockers", methods=["GET"])
def list_lockers():
    uid, role = authenticate()
    authorize(role, {"CellarMember", "CellarManager", "Appraiser", "InsuranceAgent", "AuctionBroker"})
    limit, offset = parse_pagination()
    rows = list(S.lockers.values())
    for f in ("member_id", "status", "size_tier", "climate_zone"):
        if f in request.args:
            rows = [r for r in rows if r[f] == request.args[f]]
    if role == "CellarMember":
        rows = [r for r in rows if r["member_id"] == uid]
    return list_ok(rows, limit, offset, S.ser_locker)


@app.route("/lockers/<locker_id>/assign", methods=["POST"])
def assign_locker(locker_id):
    uid, role = authenticate()
    authorize(role, {"CellarManager"})
    l = get_or_404(S.lockers, locker_id)
    data = body()
    member_id = v_str(v_required(data, "member_id"), "member_id")
    m = get_or_404(S.members, member_id)
    if l["status"] != "AVAILABLE":
        raise ApiError("ERR_INVALID_STATE", 409, "Locker not AVAILABLE")
    if m["status"] != "ACTIVE":
        raise ApiError("ERR_MEMBER_NOT_ACTIVE", 409, "Target member not ACTIVE")
    l["member_id"] = m["id"]
    l["status"] = "ASSIGNED"
    S.touch(l)
    return ok(S.ser_locker(l))


@app.route("/lockers/<locker_id>/release", methods=["POST"])
def release_locker(locker_id):
    uid, role = authenticate()
    authorize(role, {"CellarManager"})
    l = get_or_404(S.lockers, locker_id)
    if l["status"] != "ASSIGNED":
        raise ApiError("ERR_INVALID_STATE", 409, "Locker not ASSIGNED")
    if S.occupied_bottles(l["id"]) != 0 or S.reserved_bottles(l["id"]) != 0:
        raise ApiError("ERR_LOCKER_NOT_EMPTY", 409, "Locker not empty")
    l["member_id"] = None
    l["status"] = "AVAILABLE"
    S.touch(l)
    return ok(S.ser_locker(l))


@app.route("/lockers/<locker_id>/retire", methods=["POST"])
def retire_locker(locker_id):
    uid, role = authenticate()
    authorize(role, {"CellarManager"})
    l = get_or_404(S.lockers, locker_id)
    if l["status"] != "AVAILABLE":
        raise ApiError("ERR_INVALID_STATE", 409, "Locker not AVAILABLE")
    if S.occupied_bottles(l["id"]) != 0:
        raise ApiError("ERR_LOCKER_NOT_EMPTY", 409, "Locker not empty")
    l["status"] = "RETIRED"
    S.touch(l)
    return ok(S.ser_locker(l))


# ===========================================================================
# BOTTLE
# ===========================================================================
@app.route("/bottles", methods=["POST"])
def create_bottle():
    uid, role = authenticate()
    authorize(role, {"CellarMember", "CellarManager"})
    data = body()
    locker_id = v_str(v_required(data, "locker_id"), "locker_id")
    l = get_or_404(S.lockers, locker_id)
    own_check(role, uid, l["member_id"])
    wine_name = v_str(v_required(data, "wine_name"), "wine_name")
    vintage_year = v_int(v_required(data, "vintage_year"), "vintage_year")
    varietal = v_str(v_required(data, "varietal"), "varietal")
    format_ml = v_required(data, "format_ml")
    if format_ml not in (375, 750, 1500, 3000):
        raise ApiError("ERR_VALIDATION", 400, "format_ml must be one of 375, 750, 1500, 3000")
    dw_start = v_int(v_required(data, "drink_window_start_year"), "drink_window_start_year")
    dw_end = v_int(v_required(data, "drink_window_end_year"), "drink_window_end_year")
    provenance = data.get("provenance_status", "UNVERIFIED")
    if provenance is None:
        provenance = "UNVERIFIED"
    v_enum(provenance, "provenance_status", {"DOCUMENTED", "UNVERIFIED", "DISPUTED"})
    if l["status"] in ("FROZEN", "MAINTENANCE", "RETIRED"):
        raise ApiError("ERR_LOCKER_IN_MAINTENANCE", 409, "Locker not accepting deposits")
    occ = S.occupied_bottles(l["id"])
    res = S.reserved_bottles(l["id"])
    if l["capacity_bottles"] - occ - res <= 0:
        raise ApiError("ERR_LOCKER_CAPACITY_EXCEEDED", 409, "Locker has no free capacity")
    b = {
        "id": S.new_id(),
        "member_id": l["member_id"],
        "locker_id": l["id"],
        "wine_name": wine_name,
        "vintage_year": vintage_year,
        "varietal": varietal,
        "format_ml": format_ml,
        "provenance_status": provenance,
        "drink_window_start_year": dw_start,
        "drink_window_end_year": dw_end,
        "appraised_value_cents": 0,
        "status": "STORED",
    }
    S.stamp_new(b)
    S.bottles[b["id"]] = b
    return ok(S.ser_bottle(b), 201)


@app.route("/bottles/<bottle_id>", methods=["GET"])
def get_bottle(bottle_id):
    uid, role = authenticate()
    authorize(role, {"CellarMember", "CellarManager", "Appraiser", "InsuranceAgent", "AuctionBroker"})
    b = get_or_404(S.bottles, bottle_id)
    own_check(role, uid, b["member_id"])
    return ok(S.ser_bottle(b))


@app.route("/bottles", methods=["GET"])
def list_bottles():
    uid, role = authenticate()
    authorize(role, {"CellarMember", "CellarManager", "Appraiser", "InsuranceAgent", "AuctionBroker"})
    limit, offset = parse_pagination()
    rows = list(S.bottles.values())
    for f in ("member_id", "locker_id", "status"):
        if f in request.args:
            rows = [r for r in rows if r[f] == request.args[f]]
    if role == "CellarMember":
        rows = [r for r in rows if r["member_id"] == uid]
    return list_ok(rows, limit, offset, S.ser_bottle)


@app.route("/bottles/<bottle_id>/provenance", methods=["POST"])
def set_provenance(bottle_id):
    uid, role = authenticate()
    authorize(role, {"CellarManager", "Appraiser"})
    b = get_or_404(S.bottles, bottle_id)
    data = body()
    provenance = v_enum(v_required(data, "provenance_status"), "provenance_status",
                        {"DOCUMENTED", "UNVERIFIED", "DISPUTED"})
    b["provenance_status"] = provenance
    S.touch(b)
    return ok(S.ser_bottle(b))


# ===========================================================================
# APPRAISAL
# ===========================================================================
def appraisal_valuation(method, base_value_cents):
    if method == "MARKET_COMPARABLE":
        return base_value_cents
    return S.rhu(Decimal(base_value_cents) * Decimal(S.REPLACEMENT_UPLIFT))


@app.route("/appraisals", methods=["POST"])
def create_appraisal():
    uid, role = authenticate()
    authorize(role, {"Appraiser"})
    data = body()
    bottle_id = v_str(v_required(data, "bottle_id"), "bottle_id")
    b = get_or_404(S.bottles, bottle_id)
    method = v_enum(v_required(data, "method"), "method", {"MARKET_COMPARABLE", "REPLACEMENT_COST"})
    base_value = v_int(v_required(data, "base_value_cents"), "base_value_cents", minimum=0)
    a = {
        "id": S.new_id(),
        "bottle_id": b["id"],
        "method": method,
        "base_value_cents": base_value,
        "assessed_value_cents": appraisal_valuation(method, base_value),
        "created_by_user_id": uid,
        "effective_date": None,
        "status": "DRAFT",
    }
    S.stamp_new(a)
    S.appraisals[a["id"]] = a
    return ok(S.ser_appraisal(a), 201)


@app.route("/appraisals/<appraisal_id>/finalize", methods=["POST"])
def finalize_appraisal(appraisal_id):
    uid, role = authenticate()
    authorize(role, {"Appraiser"})
    a = get_or_404(S.appraisals, appraisal_id)
    data = body()
    expected = v_int(v_required(data, "expected_bottle_version"), "expected_bottle_version")
    if a["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", 409, "Appraisal not DRAFT")
    if uid == a["created_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES", 403, "Finalizer must differ from creator")
    b = get_or_404(S.bottles, a["bottle_id"])
    if expected != b["version"]:
        raise ApiError("ERR_STALE_VERSION", 412, "expected_bottle_version does not match bottle version")
    # supersede prior FINALIZED appraisal for this bottle
    for other in S.appraisals.values():
        if other["bottle_id"] == b["id"] and other["status"] == "FINALIZED":
            other["status"] = "SUPERSEDED"
            S.touch(other)
    a["status"] = "FINALIZED"
    a["effective_date"] = S.clock_iso()
    S.touch(a)
    b["appraised_value_cents"] = a["assessed_value_cents"]
    S.touch(b)
    return ok(S.ser_appraisal(a))


@app.route("/appraisals/<appraisal_id>", methods=["GET"])
def get_appraisal(appraisal_id):
    uid, role = authenticate()
    authorize(role, {"CellarMember", "CellarManager", "Appraiser", "InsuranceAgent", "AuctionBroker"})
    a = get_or_404(S.appraisals, appraisal_id)
    if role == "CellarMember":
        b = S.bottles.get(a["bottle_id"])
        own_check(role, uid, b["member_id"] if b else None)
    return ok(S.ser_appraisal(a))


@app.route("/appraisals", methods=["GET"])
def list_appraisals():
    uid, role = authenticate()
    authorize(role, {"CellarMember", "CellarManager", "Appraiser", "InsuranceAgent", "AuctionBroker"})
    limit, offset = parse_pagination()
    rows = list(S.appraisals.values())
    if "bottle_id" in request.args:
        rows = [r for r in rows if r["bottle_id"] == request.args["bottle_id"]]
    if "status" in request.args:
        rows = [r for r in rows if r["status"] == request.args["status"]]
    if role == "CellarMember":
        rows = [r for r in rows
                if S.bottles.get(r["bottle_id"]) and S.bottles[r["bottle_id"]]["member_id"] == uid]
    return list_ok(rows, limit, offset, S.ser_appraisal)


# ===========================================================================
# INSURANCE POLICY
# ===========================================================================
def compute_premium(covered, coverage_tier):
    insured = 0
    premium = 0
    factor = Decimal(S.COVERAGE_TIER_FACTOR[coverage_tier])
    for b in covered:
        insured += b["appraised_value_cents"]
        base_rate = Decimal(S.INSURANCE_BASE_RATE[b["provenance_status"]])
        rate = base_rate * factor
        premium += S.rhu(Decimal(b["appraised_value_cents"]) * rate)
    return insured, premium


@app.route("/insurance-policies", methods=["POST"])
def create_policy():
    uid, role = authenticate()
    authorize(role, {"InsuranceAgent"})
    data = body()
    member_id = v_str(v_required(data, "member_id"), "member_id")
    m = get_or_404(S.members, member_id)
    coverage_tier = v_enum(v_required(data, "coverage_tier"), "coverage_tier", {"BASIC", "FULL"})
    covered_ids = v_required(data, "covered_bottle_ids")
    if not isinstance(covered_ids, list):
        raise ApiError("ERR_VALIDATION", 400, "covered_bottle_ids must be an array")
    covered = []
    for bid in covered_ids:
        covered.append(get_or_404(S.bottles, bid))
    for b in covered:
        if b["member_id"] != m["id"]:
            raise ApiError("ERR_BOTTLE_NOT_OWNED", 422, "Covered bottle not owned by member")
    insured, premium = compute_premium(covered, coverage_tier)
    p = {
        "id": S.new_id(),
        "member_id": m["id"],
        "coverage_tier": coverage_tier,
        "covered_bottle_ids": list(covered_ids),
        "insured_value_cents": insured,
        "premium_cents": premium,
        "bound_at": None,
        "status": "QUOTED",
    }
    S.stamp_new(p)
    S.policies[p["id"]] = p
    return ok(S.ser_policy(p), 201)


@app.route("/insurance-policies/<policy_id>/bind", methods=["POST"])
def bind_policy(policy_id):
    uid, role = authenticate()
    authorize(role, {"InsuranceAgent"})
    p = get_or_404(S.policies, policy_id)
    if p["status"] != "QUOTED":
        raise ApiError("ERR_INVALID_STATE", 409, "Policy not QUOTED")
    balance = S.wallet_balance(p["member_id"])
    if balance - p["premium_cents"] < S.WALLET_FLOOR_CENTS:
        raise ApiError("ERR_INSUFFICIENT_FUNDS", 422, "Bind would drop wallet below floor")
    post_ledger(p["member_id"], "DEBIT", p["premium_cents"],
                "Insurance premium", "InsurancePolicy", p["id"])
    p["status"] = "BOUND"
    p["bound_at"] = S.clock_iso()
    S.touch(p)
    return ok(S.ser_policy(p))


@app.route("/insurance-policies/<policy_id>/cancel", methods=["POST"])
def cancel_policy(policy_id):
    uid, role = authenticate()
    authorize(role, {"InsuranceAgent"})
    p = get_or_404(S.policies, policy_id)
    if p["status"] not in ("QUOTED", "BOUND"):
        raise ApiError("ERR_INVALID_STATE", 409, "Policy not QUOTED/BOUND")
    was_bound = p["status"] == "BOUND"
    p["status"] = "CANCELLED"
    S.touch(p)
    if was_bound:
        post_ledger(p["member_id"], "CREDIT", p["premium_cents"],
                    "Insurance premium refund", "InsurancePolicy", p["id"])
    return ok(S.ser_policy(p))


@app.route("/insurance-policies/<policy_id>", methods=["GET"])
def get_policy(policy_id):
    uid, role = authenticate()
    authorize(role, {"CellarMember", "CellarManager", "InsuranceAgent"})
    p = get_or_404(S.policies, policy_id)
    own_check(role, uid, p["member_id"])
    return ok(S.ser_policy(p))


@app.route("/insurance-policies", methods=["GET"])
def list_policies():
    uid, role = authenticate()
    authorize(role, {"CellarMember", "CellarManager", "InsuranceAgent"})
    limit, offset = parse_pagination()
    rows = list(S.policies.values())
    if "member_id" in request.args:
        rows = [r for r in rows if r["member_id"] == request.args["member_id"]]
    if "status" in request.args:
        rows = [r for r in rows if r["status"] == request.args["status"]]
    if role == "CellarMember":
        rows = [r for r in rows if r["member_id"] == uid]
    return list_ok(rows, limit, offset, S.ser_policy)


# ===========================================================================
# MOVEMENT REQUEST
# ===========================================================================
@app.route("/movement-requests", methods=["POST"])
def create_movement():
    uid, role = authenticate()
    authorize(role, {"CellarMember"})
    data = body()
    member_id = v_str(v_required(data, "member_id"), "member_id")
    own_check(role, uid, member_id)
    locker_id = v_str(v_required(data, "locker_id"), "locker_id")
    m = get_or_404(S.members, member_id)
    l = get_or_404(S.lockers, locker_id)
    request_type = v_enum(v_required(data, "request_type"), "request_type", {"INTAKE", "WITHDRAWAL"})
    quantity = v_int(v_required(data, "quantity"), "quantity", minimum=1)
    bottle_ids = data.get("bottle_ids")
    if request_type == "WITHDRAWAL":
        if not isinstance(bottle_ids, list) or len(bottle_ids) == 0:
            raise ApiError("ERR_VALIDATION", 400, "bottle_ids required for WITHDRAWAL")
        if quantity != len(bottle_ids):
            raise ApiError("ERR_VALIDATION", 400, "quantity must equal number of bottle_ids")
        for bid in bottle_ids:
            get_or_404(S.bottles, bid)
    else:
        bottle_ids = None
    if l["status"] in ("FROZEN", "MAINTENANCE", "RETIRED"):
        raise ApiError("ERR_LOCKER_IN_MAINTENANCE", 409, "Locker not accepting movement")
    if request_type == "INTAKE":
        occ = S.occupied_bottles(l["id"])
        res = S.reserved_bottles(l["id"])
        if l["capacity_bottles"] - occ - res - quantity < 0:
            raise ApiError("ERR_LOCKER_CAPACITY_EXCEEDED", 409, "Reservation exceeds capacity")
    mr = {
        "id": S.new_id(),
        "member_id": m["id"],
        "locker_id": l["id"],
        "request_type": request_type,
        "quantity": quantity,
        "bottle_ids": list(bottle_ids) if bottle_ids else None,
        "status": "REQUESTED",
    }
    S.stamp_new(mr)
    S.movement_requests[mr["id"]] = mr
    return ok(S.ser_movement(mr), 201)


@app.route("/movement-requests/<movement_request_id>/approve", methods=["POST"])
def approve_movement(movement_request_id):
    uid, role = authenticate()
    authorize(role, {"CellarManager"})
    mr = get_or_404(S.movement_requests, movement_request_id)
    if mr["status"] != "REQUESTED":
        raise ApiError("ERR_INVALID_STATE", 409, "Request not REQUESTED")
    m = S.members.get(mr["member_id"])
    if not m or m["status"] != "ACTIVE":
        raise ApiError("ERR_MEMBER_NOT_ACTIVE", 409, "Member not ACTIVE")
    l = S.lockers.get(mr["locker_id"])
    if l and l["status"] in ("FROZEN", "MAINTENANCE", "RETIRED"):
        raise ApiError("ERR_LOCKER_IN_MAINTENANCE", 409, "Locker not accepting movement")
    mr["status"] = "APPROVED"
    S.touch(mr)
    return ok(S.ser_movement(mr))


@app.route("/movement-requests/<movement_request_id>/reject", methods=["POST"])
def reject_movement(movement_request_id):
    uid, role = authenticate()
    authorize(role, {"CellarManager"})
    mr = get_or_404(S.movement_requests, movement_request_id)
    if mr["status"] != "REQUESTED":
        raise ApiError("ERR_INVALID_STATE", 409, "Request not REQUESTED")
    mr["status"] = "REJECTED"
    S.touch(mr)
    return ok(S.ser_movement(mr))


@app.route("/movement-requests/<movement_request_id>/complete", methods=["POST"])
def complete_movement(movement_request_id):
    uid, role = authenticate()
    authorize(role, {"CellarManager"})
    mr = get_or_404(S.movement_requests, movement_request_id)
    if mr["status"] != "APPROVED":
        raise ApiError("ERR_INVALID_STATE", 409, "Request not APPROVED")
    if mr["request_type"] == "WITHDRAWAL":
        listed = []
        for bid in mr["bottle_ids"] or []:
            b = S.bottles.get(bid)
            if not b or b["status"] != "STORED" or b["locker_id"] != mr["locker_id"]:
                raise ApiError("ERR_BOTTLE_NOT_STORED", 422, "Bottle not stored in locker")
            listed.append(b)
        for b in listed:
            b["status"] = "WITHDRAWN"
            b["locker_id"] = None
            S.touch(b)
    mr["status"] = "COMPLETED"
    S.touch(mr)
    return ok(S.ser_movement(mr))


@app.route("/movement-requests/<movement_request_id>/cancel", methods=["POST"])
def cancel_movement(movement_request_id):
    uid, role = authenticate()
    authorize(role, {"CellarMember", "CellarManager"})
    mr = get_or_404(S.movement_requests, movement_request_id)
    own_check(role, uid, mr["member_id"])
    if mr["status"] not in ("REQUESTED", "APPROVED"):
        raise ApiError("ERR_INVALID_STATE", 409, "Request not REQUESTED/APPROVED")
    mr["status"] = "CANCELLED"
    S.touch(mr)
    return ok(S.ser_movement(mr))


@app.route("/movement-requests/<movement_request_id>", methods=["GET"])
def get_movement(movement_request_id):
    uid, role = authenticate()
    authorize(role, {"CellarMember", "CellarManager"})
    mr = get_or_404(S.movement_requests, movement_request_id)
    own_check(role, uid, mr["member_id"])
    return ok(S.ser_movement(mr))


@app.route("/movement-requests", methods=["GET"])
def list_movements():
    uid, role = authenticate()
    authorize(role, {"CellarMember", "CellarManager"})
    limit, offset = parse_pagination()
    rows = list(S.movement_requests.values())
    for f in ("member_id", "locker_id", "status", "request_type"):
        if f in request.args:
            rows = [r for r in rows if r[f] == request.args[f]]
    if role == "CellarMember":
        rows = [r for r in rows if r["member_id"] == uid]
    return list_ok(rows, limit, offset, S.ser_movement)


# ===========================================================================
# DELIVERY ORDER
# ===========================================================================
def v_datetime(value, field):
    v_str(value, field)
    dt = S.parse_iso(value)
    if dt is None:
        raise ApiError("ERR_VALIDATION", 400, f"Field {field} must be a valid ISO 8601 datetime")
    return dt


@app.route("/delivery-orders", methods=["POST"])
def create_delivery():
    uid, role = authenticate()
    authorize(role, {"CellarManager"})
    data = body()
    member_id = v_str(v_required(data, "member_id"), "member_id")
    m = get_or_404(S.members, member_id)
    bottle_ids = v_required(data, "bottle_ids")
    if not isinstance(bottle_ids, list) or len(bottle_ids) == 0:
        raise ApiError("ERR_VALIDATION", 400, "bottle_ids must be a non-empty array")
    listed = [get_or_404(S.bottles, bid) for bid in bottle_ids]
    courier_ref = v_str(v_required(data, "courier_ref"), "courier_ref")
    slot_start_raw = v_required(data, "slot_start")
    slot_end_raw = v_required(data, "slot_end")
    new_start = v_datetime(slot_start_raw, "slot_start")
    new_end = v_datetime(slot_end_raw, "slot_end")
    for b in listed:
        if b["member_id"] != m["id"]:
            raise ApiError("ERR_BOTTLE_NOT_OWNED", 422, "Bottle not owned by member")
    for b in listed:
        if b["status"] != "WITHDRAWN":
            raise ApiError("ERR_DELIVERY_BOTTLE_NOT_WITHDRAWN", 422, "Bottle not WITHDRAWN")
    for e in S.delivery_orders.values():
        if e["courier_ref"] == courier_ref and e["status"] != "CANCELLED":
            e_start = S.parse_iso(e["slot_start"])
            e_end = S.parse_iso(e["slot_end"])
            if new_start < e_end and e_start < new_end:
                raise ApiError("ERR_COURIER_SLOT_CONFLICT", 409, "Courier slot conflict")
    do = {
        "id": S.new_id(),
        "member_id": m["id"],
        "bottle_ids": list(bottle_ids),
        "courier_ref": courier_ref,
        "slot_start": slot_start_raw,
        "slot_end": slot_end_raw,
        "status": "SCHEDULED",
    }
    S.stamp_new(do)
    S.delivery_orders[do["id"]] = do
    for b in listed:
        b["status"] = "IN_TRANSIT"
        S.touch(b)
    return ok(S.ser_delivery(do), 201)


@app.route("/delivery-orders/<delivery_order_id>/deliver", methods=["POST"])
def deliver_delivery(delivery_order_id):
    uid, role = authenticate()
    authorize(role, {"CellarManager"})
    do = get_or_404(S.delivery_orders, delivery_order_id)
    if do["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", 409, "Order not SCHEDULED")
    for bid in do["bottle_ids"]:
        b = S.bottles.get(bid)
        if b and b["status"] == "IN_TRANSIT":
            b["status"] = "DELIVERED"
            S.touch(b)
    do["status"] = "DELIVERED"
    S.touch(do)
    return ok(S.ser_delivery(do))


@app.route("/delivery-orders/<delivery_order_id>/cancel", methods=["POST"])
def cancel_delivery(delivery_order_id):
    uid, role = authenticate()
    authorize(role, {"CellarManager"})
    do = get_or_404(S.delivery_orders, delivery_order_id)
    if do["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", 409, "Order not SCHEDULED")
    for bid in do["bottle_ids"]:
        b = S.bottles.get(bid)
        if b and b["status"] == "IN_TRANSIT":
            b["status"] = "WITHDRAWN"
            S.touch(b)
    do["status"] = "CANCELLED"
    S.touch(do)
    return ok(S.ser_delivery(do))


@app.route("/delivery-orders/<delivery_order_id>", methods=["GET"])
def get_delivery(delivery_order_id):
    uid, role = authenticate()
    authorize(role, {"CellarMember", "CellarManager"})
    do = get_or_404(S.delivery_orders, delivery_order_id)
    own_check(role, uid, do["member_id"])
    return ok(S.ser_delivery(do))


@app.route("/delivery-orders", methods=["GET"])
def list_deliveries():
    uid, role = authenticate()
    authorize(role, {"CellarMember", "CellarManager"})
    limit, offset = parse_pagination()
    rows = list(S.delivery_orders.values())
    for f in ("member_id", "courier_ref", "status"):
        if f in request.args:
            rows = [r for r in rows if r[f] == request.args[f]]
    if role == "CellarMember":
        rows = [r for r in rows if r["member_id"] == uid]
    return list_ok(rows, limit, offset, S.ser_delivery)


# ===========================================================================
# CONSIGNMENT
# ===========================================================================
def consignment_proceeds(price):
    if price <= S.COMMISSION_TIER_1_CENTS:
        pct = "0.20"
    elif price <= S.COMMISSION_TIER_2_CENTS:
        pct = "0.15"
    else:
        pct = "0.10"
    commission = S.rhu(Decimal(price) * Decimal(pct))
    net = price - commission
    platform_fee = S.rhu(Decimal(net) * Decimal(S.PLATFORM_FEE_PCT))
    proceeds = net - platform_fee
    return float(pct), proceeds


@app.route("/consignments", methods=["POST"])
def create_consignment():
    uid, role = authenticate()
    authorize(role, {"CellarMember"})
    data = body()
    bottle_id = v_str(v_required(data, "bottle_id"), "bottle_id")
    b = get_or_404(S.bottles, bottle_id)
    own_check(role, uid, b["member_id"])
    reserve = v_int(v_required(data, "reserve_price_cents"), "reserve_price_cents", minimum=0)
    c = {
        "id": S.new_id(),
        "bottle_id": b["id"],
        "member_id": b["member_id"],
        "reserve_price_cents": reserve,
        "offer_price_cents": None,
        "counter_price_cents": None,
        "hammer_price_cents": None,
        "commission_pct": None,
        "net_proceeds_cents": None,
        "estimated_proceeds_cents": None,
        "status": "DRAFT",
    }
    S.stamp_new(c)
    S.consignments[c["id"]] = c
    return ok(S.ser_consignment(c), 201)


@app.route("/consignments/<consignment_id>/list", methods=["POST"])
def list_consignment(consignment_id):
    uid, role = authenticate()
    authorize(role, {"AuctionBroker"})
    c = get_or_404(S.consignments, consignment_id)
    if c["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", 409, "Consignment not DRAFT")
    b = get_or_404(S.bottles, c["bottle_id"])
    if b["status"] != "STORED":
        raise ApiError("ERR_BOTTLE_NOT_STORED", 422, "Bottle not STORED")
    if b["provenance_status"] != "DOCUMENTED":
        raise ApiError("ERR_PROVENANCE_NOT_DOCUMENTED", 422, "Bottle provenance not DOCUMENTED")
    if S.drink_window_status(b) == "TOO_YOUNG":
        raise ApiError("ERR_DRINK_WINDOW_NOT_OPEN", 409, "Bottle drink window not open")
    c["status"] = "LISTED"
    S.touch(c)
    b["status"] = "CONSIGNED"
    S.touch(b)
    return ok(S.ser_consignment(c))


@app.route("/consignments/<consignment_id>/offer", methods=["POST"])
def offer_consignment(consignment_id):
    uid, role = authenticate()
    authorize(role, {"AuctionBroker"})
    c = get_or_404(S.consignments, consignment_id)
    data = body()
    offer = v_int(v_required(data, "offer_price_cents"), "offer_price_cents", minimum=0)
    if c["status"] not in ("LISTED", "COUNTERED"):
        raise ApiError("ERR_INVALID_STATE", 409, "Consignment not LISTED/COUNTERED")
    c["status"] = "OFFERED"
    c["offer_price_cents"] = offer
    S.touch(c)
    return ok(S.ser_consignment(c))


@app.route("/consignments/<consignment_id>/counter", methods=["POST"])
def counter_consignment(consignment_id):
    uid, role = authenticate()
    authorize(role, {"CellarMember"})
    c = get_or_404(S.consignments, consignment_id)
    own_check(role, uid, c["member_id"])
    data = body()
    counter = v_int(v_required(data, "counter_price_cents"), "counter_price_cents", minimum=0)
    if c["status"] != "OFFERED":
        raise ApiError("ERR_INVALID_STATE", 409, "Consignment not OFFERED")
    c["status"] = "COUNTERED"
    c["counter_price_cents"] = counter
    S.touch(c)
    return ok(S.ser_consignment(c))


@app.route("/consignments/<consignment_id>/accept", methods=["POST"])
def accept_consignment(consignment_id):
    uid, role = authenticate()
    authorize(role, {"CellarMember"})
    c = get_or_404(S.consignments, consignment_id)
    own_check(role, uid, c["member_id"])
    if c["status"] != "OFFERED":
        raise ApiError("ERR_INVALID_STATE", 409, "Consignment not OFFERED")
    if c["offer_price_cents"] < c["reserve_price_cents"]:
        raise ApiError("ERR_OFFER_BELOW_RESERVE", 422, "Offer below reserve")
    _pct, proceeds = consignment_proceeds(c["offer_price_cents"])
    c["estimated_proceeds_cents"] = proceeds
    c["status"] = "ACCEPTED"
    S.touch(c)
    return ok(S.ser_consignment(c))


@app.route("/consignments/<consignment_id>/settle", methods=["POST"])
def settle_consignment(consignment_id):
    uid, role = authenticate()
    authorize(role, {"AuctionBroker"})
    c = get_or_404(S.consignments, consignment_id)
    data = body()
    hammer = v_int(v_required(data, "hammer_price_cents"), "hammer_price_cents", minimum=0)
    if c["status"] != "ACCEPTED":
        raise ApiError("ERR_INVALID_STATE", 409, "Consignment not ACCEPTED")
    if hammer < c["reserve_price_cents"]:
        raise ApiError("ERR_OFFER_BELOW_RESERVE", 422, "Hammer below reserve")
    pct, proceeds = consignment_proceeds(hammer)
    c["hammer_price_cents"] = hammer
    c["commission_pct"] = pct
    c["net_proceeds_cents"] = proceeds
    c["status"] = "SETTLED"
    S.touch(c)
    b = S.bottles.get(c["bottle_id"])
    if b:
        b["status"] = "SOLD"
        b["locker_id"] = None
        S.touch(b)
    post_ledger(c["member_id"], "CREDIT", proceeds,
                "Consignment proceeds", "Consignment", c["id"])
    return ok(S.ser_consignment(c))


@app.route("/consignments/<consignment_id>/withdraw", methods=["POST"])
def withdraw_consignment(consignment_id):
    uid, role = authenticate()
    authorize(role, {"CellarMember"})
    c = get_or_404(S.consignments, consignment_id)
    own_check(role, uid, c["member_id"])
    if c["status"] not in ("DRAFT", "LISTED", "OFFERED", "COUNTERED"):
        raise ApiError("ERR_INVALID_STATE", 409, "Consignment not in a withdrawable state")
    c["status"] = "WITHDRAWN"
    S.touch(c)
    b = S.bottles.get(c["bottle_id"])
    if b and b["status"] == "CONSIGNED":
        b["status"] = "STORED"
        S.touch(b)
    return ok(S.ser_consignment(c))


@app.route("/consignments/<consignment_id>", methods=["GET"])
def get_consignment(consignment_id):
    uid, role = authenticate()
    authorize(role, {"CellarMember", "CellarManager", "AuctionBroker"})
    c = get_or_404(S.consignments, consignment_id)
    own_check(role, uid, c["member_id"])
    return ok(S.ser_consignment(c))


@app.route("/consignments", methods=["GET"])
def list_consignments():
    uid, role = authenticate()
    authorize(role, {"CellarMember", "CellarManager", "AuctionBroker"})
    limit, offset = parse_pagination()
    rows = list(S.consignments.values())
    for f in ("member_id", "bottle_id", "status"):
        if f in request.args:
            rows = [r for r in rows if r[f] == request.args[f]]
    if role == "CellarMember":
        rows = [r for r in rows if r["member_id"] == uid]
    return list_ok(rows, limit, offset, S.ser_consignment)


# ===========================================================================
# WAITLIST ENTRY
# ===========================================================================
@app.route("/waitlist-entries", methods=["POST"])
def create_waitlist():
    uid, role = authenticate()
    authorize(role, {"CellarMember"})
    data = body()
    member_id = v_str(v_required(data, "member_id"), "member_id")
    own_check(role, uid, member_id)
    m = get_or_404(S.members, member_id)
    size_tier = v_enum(v_required(data, "requested_size_tier"), "requested_size_tier",
                       {"SMALL", "MEDIUM", "LARGE"})
    climate_zone = v_enum(v_required(data, "requested_climate_zone"), "requested_climate_zone",
                          {"RED", "WHITE", "SPARKLING"})
    w = {
        "id": S.new_id(),
        "member_id": m["id"],
        "requested_size_tier": size_tier,
        "requested_climate_zone": climate_zone,
        "offered_locker_id": None,
        "status": "WAITING",
    }
    S.stamp_new(w)
    S.waitlist_entries[w["id"]] = w
    return ok(S.ser_waitlist(w), 201)


@app.route("/waitlist-entries/<waitlist_entry_id>/accept", methods=["POST"])
def accept_waitlist(waitlist_entry_id):
    uid, role = authenticate()
    authorize(role, {"CellarMember"})
    w = get_or_404(S.waitlist_entries, waitlist_entry_id)
    own_check(role, uid, w["member_id"])
    if w["status"] != "OFFERED":
        raise ApiError("ERR_INVALID_STATE", 409, "Waitlist entry not OFFERED")
    l = S.lockers.get(w["offered_locker_id"])
    if not l or l["status"] != "AVAILABLE":
        raise ApiError("ERR_INVALID_STATE", 409, "Offered locker no longer available")
    l["status"] = "ASSIGNED"
    l["member_id"] = w["member_id"]
    S.touch(l)
    w["status"] = "FULFILLED"
    S.touch(w)
    return ok(S.ser_waitlist(w))


@app.route("/waitlist-entries/<waitlist_entry_id>/cancel", methods=["POST"])
def cancel_waitlist(waitlist_entry_id):
    uid, role = authenticate()
    authorize(role, {"CellarMember"})
    w = get_or_404(S.waitlist_entries, waitlist_entry_id)
    own_check(role, uid, w["member_id"])
    if w["status"] not in ("WAITING", "OFFERED"):
        raise ApiError("ERR_INVALID_STATE", 409, "Waitlist entry not WAITING/OFFERED")
    w["status"] = "CANCELLED"
    S.touch(w)
    return ok(S.ser_waitlist(w))


@app.route("/waitlist-entries/<waitlist_entry_id>", methods=["GET"])
def get_waitlist(waitlist_entry_id):
    uid, role = authenticate()
    authorize(role, {"CellarMember", "CellarManager"})
    w = get_or_404(S.waitlist_entries, waitlist_entry_id)
    own_check(role, uid, w["member_id"])
    return ok(S.ser_waitlist(w))


@app.route("/waitlist-entries", methods=["GET"])
def list_waitlist():
    uid, role = authenticate()
    authorize(role, {"CellarMember", "CellarManager"})
    limit, offset = parse_pagination()
    rows = list(S.waitlist_entries.values())
    if "member_id" in request.args:
        rows = [r for r in rows if r["member_id"] == request.args["member_id"]]
    if "status" in request.args:
        rows = [r for r in rows if r["status"] == request.args["status"]]
    if role == "CellarMember":
        rows = [r for r in rows if r["member_id"] == uid]
    return list_ok(rows, limit, offset, S.ser_waitlist)


# ===========================================================================
# MAINTENANCE WINDOW
# ===========================================================================
@app.route("/maintenance-windows", methods=["POST"])
def create_maintenance():
    uid, role = authenticate()
    authorize(role, {"CellarManager"})
    data = body()
    locker_id = v_str(v_required(data, "locker_id"), "locker_id")
    l = get_or_404(S.lockers, locker_id)
    ws_raw = v_required(data, "window_start")
    we_raw = v_required(data, "window_end")
    new_start = v_datetime(ws_raw, "window_start")
    new_end = v_datetime(we_raw, "window_end")
    reason = v_str(v_required(data, "reason"), "reason")
    from datetime import timedelta
    buffer = timedelta(minutes=S.MAINTENANCE_BUFFER_MINUTES)
    for e in S.maintenance_windows.values():
        if e["locker_id"] == l["id"] and e["status"] != "CANCELLED":
            e_start = S.parse_iso(e["window_start"])
            e_end = S.parse_iso(e["window_end"])
            if new_start <= e_end + buffer and e_start <= new_end + buffer:
                raise ApiError("ERR_MAINTENANCE_WINDOW_CONFLICT", 409, "Maintenance window conflict")
    mw = {
        "id": S.new_id(),
        "locker_id": l["id"],
        "window_start": ws_raw,
        "window_end": we_raw,
        "reason": reason,
        "status": "SCHEDULED",
    }
    S.stamp_new(mw)
    S.maintenance_windows[mw["id"]] = mw
    return ok(S.ser_maintenance(mw), 201)


@app.route("/maintenance-windows/<maintenance_window_id>/activate", methods=["POST"])
def activate_maintenance(maintenance_window_id):
    uid, role = authenticate()
    authorize(role, {"CellarManager"})
    mw = get_or_404(S.maintenance_windows, maintenance_window_id)
    if mw["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", 409, "Window not SCHEDULED")
    l = S.lockers.get(mw["locker_id"])
    if l and l["status"] == "RETIRED":
        raise ApiError("ERR_INVALID_STATE", 409, "Locker is RETIRED")
    mw["status"] = "ACTIVE"
    S.touch(mw)
    if l and l["status"] in ("AVAILABLE", "ASSIGNED", "FROZEN"):
        l["status"] = "MAINTENANCE"
        S.touch(l)
    return ok(S.ser_maintenance(mw))


@app.route("/maintenance-windows/<maintenance_window_id>/complete", methods=["POST"])
def complete_maintenance(maintenance_window_id):
    uid, role = authenticate()
    authorize(role, {"CellarManager"})
    mw = get_or_404(S.maintenance_windows, maintenance_window_id)
    if mw["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "Window not ACTIVE")
    mw["status"] = "COMPLETED"
    S.touch(mw)
    l = S.lockers.get(mw["locker_id"])
    if l and l["status"] == "MAINTENANCE":
        l["status"] = "ASSIGNED" if l["member_id"] else "AVAILABLE"
        l["climate_status"] = "NOMINAL"
        S.touch(l)
    return ok(S.ser_maintenance(mw))


@app.route("/maintenance-windows/<maintenance_window_id>/cancel", methods=["POST"])
def cancel_maintenance(maintenance_window_id):
    uid, role = authenticate()
    authorize(role, {"CellarManager"})
    mw = get_or_404(S.maintenance_windows, maintenance_window_id)
    if mw["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", 409, "Window not SCHEDULED")
    mw["status"] = "CANCELLED"
    S.touch(mw)
    return ok(S.ser_maintenance(mw))


@app.route("/maintenance-windows/<maintenance_window_id>", methods=["GET"])
def get_maintenance(maintenance_window_id):
    uid, role = authenticate()
    authorize(role, {"CellarMember", "CellarManager"})
    mw = get_or_404(S.maintenance_windows, maintenance_window_id)
    if role == "CellarMember":
        l = S.lockers.get(mw["locker_id"])
        own_check(role, uid, l["member_id"] if l else None)
    return ok(S.ser_maintenance(mw))


@app.route("/maintenance-windows", methods=["GET"])
def list_maintenance():
    uid, role = authenticate()
    authorize(role, {"CellarMember", "CellarManager"})
    limit, offset = parse_pagination()
    rows = list(S.maintenance_windows.values())
    if "locker_id" in request.args:
        rows = [r for r in rows if r["locker_id"] == request.args["locker_id"]]
    if "status" in request.args:
        rows = [r for r in rows if r["status"] == request.args["status"]]
    if role == "CellarMember":
        rows = [r for r in rows
                if S.lockers.get(r["locker_id"]) and S.lockers[r["locker_id"]]["member_id"] == uid]
    return list_ok(rows, limit, offset, S.ser_maintenance)


# ===========================================================================
# CLIMATE READING
# ===========================================================================
@app.route("/climate-readings", methods=["POST"])
def create_climate_reading():
    uid, role = authenticate()
    authorize(role, {"CellarManager"})
    data = body()
    locker_id = v_str(v_required(data, "locker_id"), "locker_id")
    l = get_or_404(S.lockers, locker_id)
    temperature_c = v_number(v_required(data, "temperature_c"), "temperature_c")
    humidity_pct = v_number(v_required(data, "humidity_pct"), "humidity_pct")
    in_band = (S.TEMP_MIN_C <= temperature_c <= S.TEMP_MAX_C) and \
              (S.HUMID_MIN_PCT <= humidity_pct <= S.HUMID_MAX_PCT)
    r = {
        "id": S.new_id(),
        "locker_id": l["id"],
        "temperature_c": temperature_c,
        "humidity_pct": humidity_pct,
        "in_band": in_band,
    }
    S.stamp_event(r)
    S.climate_readings[r["id"]] = r
    if not in_band:
        l["climate_status"] = "BREACH"
        S.touch(l)
    return ok(S.ser_climate(r), 201)


@app.route("/climate-readings/<climate_reading_id>", methods=["GET"])
def get_climate_reading(climate_reading_id):
    uid, role = authenticate()
    authorize(role, {"CellarMember", "CellarManager"})
    r = get_or_404(S.climate_readings, climate_reading_id)
    if role == "CellarMember":
        l = S.lockers.get(r["locker_id"])
        own_check(role, uid, l["member_id"] if l else None)
    return ok(S.ser_climate(r))


@app.route("/climate-readings", methods=["GET"])
def list_climate_readings():
    uid, role = authenticate()
    authorize(role, {"CellarMember", "CellarManager"})
    limit, offset = parse_pagination()
    rows = list(S.climate_readings.values())
    if "locker_id" in request.args:
        rows = [r for r in rows if r["locker_id"] == request.args["locker_id"]]
    if role == "CellarMember":
        rows = [r for r in rows
                if S.lockers.get(r["locker_id"]) and S.lockers[r["locker_id"]]["member_id"] == uid]
    return list_ok(rows, limit, offset, S.ser_climate)


# ===========================================================================
# OPERATIONS / CLOCK
# ===========================================================================
@app.route("/operations/cycle", methods=["POST"])
def operations_cycle():
    uid, role = authenticate()
    authorize(role, {"CellarManager"})

    offered_at_start = [w for w in S.waitlist_entries.values() if w["status"] == "OFFERED"]
    reserved_locker_ids = {w["offered_locker_id"] for w in offered_at_start}

    # --- promote: front of each (size, zone) queue into a matching AVAILABLE locker
    promoted_ids = []
    used_locker_ids = set(reserved_locker_ids)
    waiting = [w for w in S.waitlist_entries.values() if w["status"] == "WAITING"]
    groups = {}
    for w in waiting:
        key = (w["requested_size_tier"], w["requested_climate_zone"])
        groups.setdefault(key, []).append(w)
    for key, entries in groups.items():
        entries.sort(key=lambda w: (w["created_at"], w["_seq"]))
        front = entries[0]
        size_tier, climate_zone = key
        candidates = [l for l in S.lockers.values()
                      if l["status"] == "AVAILABLE"
                      and l["size_tier"] == size_tier
                      and l["climate_zone"] == climate_zone
                      and l["id"] not in used_locker_ids]
        if not candidates:
            continue
        candidates.sort(key=lambda l: (l["created_at"], l["_seq"]))
        locker = candidates[0]
        front["status"] = "OFFERED"
        front["offered_locker_id"] = locker["id"]
        S.touch(front)
        used_locker_ids.add(locker["id"])
        promoted_ids.append(front["id"])

    # --- expire: prior OFFERED entries not accepted this cycle
    expired_ids = []
    for w in offered_at_start:
        if w["status"] == "OFFERED":
            w["status"] = "EXPIRED"
            S.touch(w)
            expired_ids.append(w["id"])

    # --- lapse: BOUND policies whose holder wallet has gone negative
    lapsed_ids = []
    for p in S.policies.values():
        if p["status"] == "BOUND" and S.wallet_balance(p["member_id"]) < 0:
            p["status"] = "LAPSED"
            S.touch(p)
            lapsed_ids.append(p["id"])

    return ok({
        "promoted_waitlist_ids": promoted_ids,
        "expired_waitlist_ids": expired_ids,
        "lapsed_policy_ids": lapsed_ids,
    })


@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    uid, role = authenticate()
    authorize(role, {"CellarManager"})
    data = body()
    to_iso = v_str(v_required(data, "to_iso8601"), "to_iso8601")
    dt = S.parse_iso(to_iso)
    if dt is None:
        raise ApiError("ERR_VALIDATION", 400, "to_iso8601 must be a valid ISO 8601 datetime")
    S.set_clock(dt)
    return ok({"current_utc": S.clock_iso()})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
