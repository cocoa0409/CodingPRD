import os
from datetime import datetime, timezone, date

from flask import Flask, request

from db import store, new_id, iso_ts
from clock import clock
from errors import (
    ApiError, err,
    ERR_UNAUTHENTICATED, ERR_FORBIDDEN, ERR_NOT_RESOURCE_OWNER,
    ERR_NOT_FOUND, ERR_REFERENCED_NOT_FOUND, ERR_INVALID_STATE,
    ERR_INVALID_REQUEST, ERR_DUPLICATE_PRIMARY, ERR_PLAN_AREA_MISMATCH,
    ERR_SEP_WINDOW_CLOSED, ERR_SEP_NOT_APPROVED, ERR_NO_BENCHMARK_PLAN,
    ERR_APTC_EXCEEDS_MAX, ERR_OVERLAPPING_COVERAGE, ERR_STALE_VERSION,
)
from response import success, error_response
import calculations as calc

app = Flask(__name__)

VALID_ROLES = {"Applicant", "Navigator", "MarketplaceAdmin"}


# ──────────────────────────────────────────────────────────────────────────
# Error handling
# ──────────────────────────────────────────────────────────────────────────
@app.errorhandler(ApiError)
def handle_api_error(e):
    return error_response(e.error_id, e.message, e.http_status)


@app.errorhandler(404)
def handle_404(e):
    return error_response("ERR_NOT_FOUND", "Resource not found.", 404)


@app.errorhandler(405)
def handle_405(e):
    return error_response("ERR_NOT_FOUND", "Method not allowed.", 404)


@app.errorhandler(Exception)
def handle_unexpected(e):
    if isinstance(e, ApiError):
        return error_response(e.error_id, e.message, e.http_status)
    return error_response("ERR_INVALID_REQUEST", str(e), 422)


# ──────────────────────────────────────────────────────────────────────────
# Auth helpers
# ──────────────────────────────────────────────────────────────────────────
def get_auth():
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in VALID_ROLES:
        raise err(ERR_UNAUTHENTICATED, "Missing or invalid auth headers.")
    return user_id, role


def require_role(role, allowed):
    if role not in allowed:
        raise err(ERR_FORBIDDEN, "Role not permitted for this operation.")


def check_owner(role, user_id, household):
    """Applicant must own the household; Navigator/Admin exempt."""
    if role == "Applicant" and household["applicant_user_id"] != user_id:
        raise err(ERR_NOT_RESOURCE_OWNER, "Not the resource owner.")


# ──────────────────────────────────────────────────────────────────────────
# Request body / param helpers
# ──────────────────────────────────────────────────────────────────────────
def get_body():
    if request.data and request.data.strip():
        try:
            data = request.get_json(force=True, silent=True)
        except Exception:
            raise err(ERR_INVALID_REQUEST, "Malformed JSON body.")
        if data is None:
            raise err(ERR_INVALID_REQUEST, "Malformed JSON body.")
        if not isinstance(data, dict):
            raise err(ERR_INVALID_REQUEST, "Body must be a JSON object.")
        return data
    return {}


def parse_pagination():
    try:
        limit_raw = request.args.get("limit")
        offset_raw = request.args.get("offset")
        limit = int(limit_raw) if limit_raw is not None else 10
        offset = int(offset_raw) if offset_raw is not None else 0
    except (ValueError, TypeError):
        raise err(ERR_INVALID_REQUEST, "Invalid pagination parameters.")
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    return limit, offset


def paginate(items, limit, offset):
    total = len(items)
    page = items[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + limit) < total,
    }
    return page, meta


def sort_by_created(items):
    return sorted(items, key=lambda x: (x["created_at"], x.get("_seq", 0)))


# ──────────────────────────────────────────────────────────────────────────
# Mutation helpers
# ──────────────────────────────────────────────────────────────────────────
def touch(entity):
    entity["updated_at"] = iso_ts()
    entity["version"] = entity.get("version", 1) + 1


def clock_date():
    return clock.now().astimezone(timezone.utc).date()


# ──────────────────────────────────────────────────────────────────────────
# Serializers (strip internal fields)
# ──────────────────────────────────────────────────────────────────────────
def _public(entity):
    return {k: v for k, v in entity.items() if not k.startswith("_")}


def household_view(h):
    return {
        "id": h["id"],
        "created_at": h["created_at"],
        "updated_at": h["updated_at"],
        "version": h["version"],
        "applicant_user_id": h["applicant_user_id"],
        "coverage_year": h["coverage_year"],
        "rating_area": h["rating_area"],
        "household_magi_cents": h["household_magi_cents"],
        "fpl_percent": float(h["fpl_percent"]),
        "countable_size": h["countable_size"],
    }


def member_view(m):
    return {
        "id": m["id"],
        "created_at": m["created_at"],
        "updated_at": m["updated_at"],
        "version": m["version"],
        "household_id": m["household_id"],
        "full_name": m["full_name"],
        "relationship": m["relationship"],
        "tax_filing_status": m["tax_filing_status"],
        "annual_income_cents": m["annual_income_cents"],
        "applies_for_coverage": m["applies_for_coverage"],
        "is_countable_income": m["is_countable_income"],
    }


def plan_view(p):
    return {
        "id": p["id"],
        "created_at": p["created_at"],
        "rating_area": p["rating_area"],
        "coverage_year": p["coverage_year"],
        "metal_tier": p["metal_tier"],
        "gross_premium_cents": p["gross_premium_cents"],
        "is_slcsp_benchmark": p["is_slcsp_benchmark"],
        "csr_eligible": p["csr_eligible"],
    }


def application_view(a):
    return {
        "id": a["id"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
        "household_id": a["household_id"],
        "status": a["status"],
        "enrollment_window": a["enrollment_window"],
        "sep_request_id": a["sep_request_id"],
        "submitted_at": a["submitted_at"],
    }


def determination_view(d):
    return {
        "id": d["id"],
        "created_at": d["created_at"],
        "updated_at": d["updated_at"],
        "version": d["version"],
        "application_id": d["application_id"],
        "fpl_percent_snapshot": float(d["fpl_percent_snapshot"]),
        "applicable_pct": float(d["applicable_pct"]),
        "max_aptc_monthly_cents": d["max_aptc_monthly_cents"],
        "csr_tier": d["csr_tier"],
        "is_subsidy_eligible": d["is_subsidy_eligible"],
    }


def enrollment_view(e):
    return {
        "id": e["id"],
        "created_at": e["created_at"],
        "updated_at": e["updated_at"],
        "version": e["version"],
        "application_id": e["application_id"],
        "plan_id": e["plan_id"],
        "elected_aptc_monthly_cents": e["elected_aptc_monthly_cents"],
        "applied_aptc_monthly_cents": e["applied_aptc_monthly_cents"],
        "net_premium_monthly_cents": e["net_premium_monthly_cents"],
        "effective_date": e["effective_date"],
        "first_month_premium_cents": e["first_month_premium_cents"],
        "lifecycle_status": e["lifecycle_status"],
        "payment_status": e["payment_status"],
    }


def sep_view(s):
    return {
        "id": s["id"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
        "application_id": s["application_id"],
        "qualifying_event_type": s["qualifying_event_type"],
        "event_date": s["event_date"],
        "status": s["status"],
        "window_close_date": s["window_close_date"],
    }


def reconciliation_view(r):
    return {
        "id": r["id"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
        "enrollment_id": r["enrollment_id"],
        "actual_annual_magi_cents": r["actual_annual_magi_cents"],
        "months_enrolled": r["months_enrolled"],
        "advanced_aptc_total_cents": r["advanced_aptc_total_cents"],
        "allowed_aptc_total_cents": r["allowed_aptc_total_cents"],
        "settlement_cents": r["settlement_cents"],
    }


# ──────────────────────────────────────────────────────────────────────────
# Validation helpers
# ──────────────────────────────────────────────────────────────────────────
ENUM_RELATIONSHIP = {"PRIMARY", "SPOUSE", "DEPENDENT"}
ENUM_TAX_STATUS = {"FILER", "JOINT_FILER", "DEPENDENT_FILER", "DEPENDENT_NONFILER"}
ENUM_METAL = {"BRONZE", "SILVER", "GOLD", "PLATINUM"}
ENUM_WINDOW = {"OEP", "SEP"}
ENUM_QUALIFYING = {"BIRTH", "ADOPTION", "MARRIAGE", "LOSS_OF_COVERAGE", "PERMANENT_MOVE"}


def require_fields(body, fields):
    for f in fields:
        if f not in body or body[f] is None:
            raise err(ERR_INVALID_REQUEST, f"Missing required field: {f}")


def validate_nonneg_int(body, field, required=True, default=None):
    if field not in body or body[field] is None:
        if required:
            raise err(ERR_INVALID_REQUEST, f"Missing required field: {field}")
        return default
    v = body[field]
    if isinstance(v, bool) or not isinstance(v, int):
        raise err(ERR_INVALID_REQUEST, f"Field {field} must be an integer.")
    if v < 0:
        raise err(ERR_INVALID_REQUEST, f"Field {field} must be >= 0.")
    return v


def members_of(household_id):
    return [m for m in store.members.values() if m["household_id"] == household_id]


def recompute_household(household):
    members = members_of(household["id"])
    magi, countable_size = calc.compute_household_magi(members)
    fpl = calc.compute_fpl_percent(magi, countable_size)
    household["household_magi_cents"] = magi
    household["countable_size"] = countable_size
    household["fpl_percent"] = fpl


# ──────────────────────────────────────────────────────────────────────────
# Household endpoints
# ──────────────────────────────────────────────────────────────────────────
@app.route("/households", methods=["POST"])
def create_household():
    user_id, role = get_auth()
    require_role(role, {"Applicant", "Navigator"})
    body = get_body()
    require_fields(body, ["coverage_year", "rating_area"])
    cy = body["coverage_year"]
    if isinstance(cy, bool) or not isinstance(cy, int):
        raise err(ERR_INVALID_REQUEST, "coverage_year must be an integer.")
    if not isinstance(body["rating_area"], str):
        raise err(ERR_INVALID_REQUEST, "rating_area must be a string.")
    now = iso_ts()
    h = {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "applicant_user_id": user_id,
        "coverage_year": cy,
        "rating_area": body["rating_area"],
        "household_magi_cents": 0,
        "fpl_percent": calc.Decimal("0.00"),
        "countable_size": 0,
        "_seq": store.next_seq(),
    }
    store.households[h["id"]] = h
    return success(household_view(h), 201)


@app.route("/households/<hid>", methods=["GET"])
def get_household(hid):
    user_id, role = get_auth()
    require_role(role, VALID_ROLES)
    h = store.households.get(hid)
    if not h:
        raise err(ERR_NOT_FOUND, "Household not found.")
    if role == "Applicant" and h["applicant_user_id"] != user_id:
        raise err(ERR_NOT_RESOURCE_OWNER, "Not the resource owner.")
    return success(household_view(h), 200)


@app.route("/households", methods=["GET"])
def list_households():
    user_id, role = get_auth()
    require_role(role, VALID_ROLES)
    limit, offset = parse_pagination()
    items = list(store.households.values())
    if role == "Applicant":
        items = [h for h in items if h["applicant_user_id"] == user_id]
    if request.args.get("applicant_user_id"):
        items = [h for h in items if h["applicant_user_id"] == request.args.get("applicant_user_id")]
    if request.args.get("coverage_year"):
        try:
            cy = int(request.args.get("coverage_year"))
        except ValueError:
            raise err(ERR_INVALID_REQUEST, "Invalid coverage_year filter.")
        items = [h for h in items if h["coverage_year"] == cy]
    items = sort_by_created(items)
    page, meta = paginate(items, limit, offset)
    return success([household_view(h) for h in page], 200, pagination=meta)


# ──────────────────────────────────────────────────────────────────────────
# HouseholdMember endpoints
# ──────────────────────────────────────────────────────────────────────────
@app.route("/households/<hid>/members", methods=["POST"])
def add_member(hid):
    user_id, role = get_auth()
    require_role(role, {"Applicant", "Navigator"})
    h = store.households.get(hid)
    if not h:
        raise err(ERR_NOT_FOUND, "Household not found.")
    check_owner(role, user_id, h)
    body = get_body()
    require_fields(body, ["full_name", "relationship", "tax_filing_status"])
    if not isinstance(body["full_name"], str):
        raise err(ERR_INVALID_REQUEST, "full_name must be a string.")
    if body["relationship"] not in ENUM_RELATIONSHIP:
        raise err(ERR_INVALID_REQUEST, "Invalid relationship.")
    if body["tax_filing_status"] not in ENUM_TAX_STATUS:
        raise err(ERR_INVALID_REQUEST, "Invalid tax_filing_status.")
    income = validate_nonneg_int(body, "annual_income_cents", required=False, default=0)
    applies = body.get("applies_for_coverage", True)
    if applies is None:
        applies = True
    if not isinstance(applies, bool):
        raise err(ERR_INVALID_REQUEST, "applies_for_coverage must be a boolean.")
    # business rule: exactly one PRIMARY
    if body["relationship"] == "PRIMARY":
        existing_primary = any(
            m["relationship"] == "PRIMARY" for m in members_of(hid)
        )
        if existing_primary:
            raise err(ERR_DUPLICATE_PRIMARY, "A PRIMARY member already exists.")
    now = iso_ts()
    m = {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "household_id": hid,
        "full_name": body["full_name"],
        "relationship": body["relationship"],
        "tax_filing_status": body["tax_filing_status"],
        "annual_income_cents": income,
        "applies_for_coverage": applies,
        "_seq": store.next_seq(),
    }
    m["is_countable_income"] = calc.member_is_countable_income(m)
    store.members[m["id"]] = m
    # cascade: recompute household + bump version
    recompute_household(h)
    touch(h)
    return success(member_view(m), 201)


@app.route("/households/<hid>/members/<mid>", methods=["PATCH"])
def update_member(hid, mid):
    user_id, role = get_auth()
    require_role(role, {"Applicant", "Navigator"})
    h = store.households.get(hid)
    if not h:
        raise err(ERR_NOT_FOUND, "Household not found.")
    m = store.members.get(mid)
    if not m or m["household_id"] != hid:
        raise err(ERR_NOT_FOUND, "Member not found.")
    check_owner(role, user_id, h)
    body = get_body()
    if "full_name" in body and body["full_name"] is not None:
        if not isinstance(body["full_name"], str):
            raise err(ERR_INVALID_REQUEST, "full_name must be a string.")
        m["full_name"] = body["full_name"]
    if "tax_filing_status" in body and body["tax_filing_status"] is not None:
        if body["tax_filing_status"] not in ENUM_TAX_STATUS:
            raise err(ERR_INVALID_REQUEST, "Invalid tax_filing_status.")
        m["tax_filing_status"] = body["tax_filing_status"]
    if "annual_income_cents" in body and body["annual_income_cents"] is not None:
        v = body["annual_income_cents"]
        if isinstance(v, bool) or not isinstance(v, int):
            raise err(ERR_INVALID_REQUEST, "annual_income_cents must be an integer.")
        if v < 0:
            raise err(ERR_INVALID_REQUEST, "annual_income_cents must be >= 0.")
        m["annual_income_cents"] = v
    if "applies_for_coverage" in body and body["applies_for_coverage"] is not None:
        if not isinstance(body["applies_for_coverage"], bool):
            raise err(ERR_INVALID_REQUEST, "applies_for_coverage must be a boolean.")
        m["applies_for_coverage"] = body["applies_for_coverage"]
    m["is_countable_income"] = calc.member_is_countable_income(m)
    touch(m)
    recompute_household(h)
    touch(h)
    return success(member_view(m), 200)


@app.route("/households/<hid>/members", methods=["GET"])
def list_members(hid):
    user_id, role = get_auth()
    require_role(role, VALID_ROLES)
    h = store.households.get(hid)
    if not h:
        raise err(ERR_NOT_FOUND, "Household not found.")
    if role == "Applicant" and h["applicant_user_id"] != user_id:
        raise err(ERR_NOT_RESOURCE_OWNER, "Not the resource owner.")
    limit, offset = parse_pagination()
    items = sort_by_created(members_of(hid))
    page, meta = paginate(items, limit, offset)
    return success([member_view(m) for m in page], 200, pagination=meta)


# ──────────────────────────────────────────────────────────────────────────
# Application endpoints
# ──────────────────────────────────────────────────────────────────────────
@app.route("/applications", methods=["POST"])
def create_application():
    user_id, role = get_auth()
    require_role(role, {"Applicant", "Navigator"})
    body = get_body()
    require_fields(body, ["household_id", "enrollment_window"])
    if body["enrollment_window"] not in ENUM_WINDOW:
        raise err(ERR_INVALID_REQUEST, "Invalid enrollment_window.")
    h = store.households.get(body["household_id"])
    if not h:
        raise err(ERR_REFERENCED_NOT_FOUND, "Referenced household not found.")
    check_owner(role, user_id, h)
    now = iso_ts()
    a = {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "household_id": body["household_id"],
        "status": "DRAFT",
        "enrollment_window": body["enrollment_window"],
        "sep_request_id": None,
        "submitted_at": None,
        "_seq": store.next_seq(),
    }
    store.applications[a["id"]] = a
    return success(application_view(a), 201)


@app.route("/applications/<aid>", methods=["GET"])
def get_application(aid):
    user_id, role = get_auth()
    require_role(role, VALID_ROLES)
    a = store.applications.get(aid)
    if not a:
        raise err(ERR_NOT_FOUND, "Application not found.")
    if role == "Applicant":
        h = store.households.get(a["household_id"])
        if not h or h["applicant_user_id"] != user_id:
            raise err(ERR_NOT_RESOURCE_OWNER, "Not the resource owner.")
    return success(application_view(a), 200)


@app.route("/applications", methods=["GET"])
def list_applications():
    user_id, role = get_auth()
    require_role(role, VALID_ROLES)
    limit, offset = parse_pagination()
    items = list(store.applications.values())
    if role == "Applicant":
        owned = {h["id"] for h in store.households.values() if h["applicant_user_id"] == user_id}
        items = [a for a in items if a["household_id"] in owned]
    if request.args.get("household_id"):
        items = [a for a in items if a["household_id"] == request.args.get("household_id")]
    if request.args.get("status"):
        items = [a for a in items if a["status"] == request.args.get("status")]
    items = sort_by_created(items)
    page, meta = paginate(items, limit, offset)
    return success([application_view(a) for a in page], 200, pagination=meta)


def _approved_sep_for(application_id):
    for s in store.sep_requests.values():
        if s["application_id"] == application_id and s["status"] == "APPROVED":
            return s
    return None


@app.route("/applications/<aid>/submit", methods=["POST"])
def submit_application(aid):
    user_id, role = get_auth()
    require_role(role, {"Applicant", "Navigator"})
    a = store.applications.get(aid)
    if not a:
        raise err(ERR_NOT_FOUND, "Application not found.")
    h = store.households.get(a["household_id"])
    check_owner(role, user_id, h)
    if a["status"] != "DRAFT":
        raise err(ERR_INVALID_STATE, "Application is not in DRAFT.")
    body = get_body()
    require_fields(body, ["expected_household_version"])
    ehv = body["expected_household_version"]
    if isinstance(ehv, bool) or not isinstance(ehv, int):
        raise err(ERR_INVALID_REQUEST, "expected_household_version must be an integer.")
    # business: countable_size >= 1
    if h["countable_size"] < 1:
        raise err(ERR_INVALID_STATE, "Household has no countable members.")
    # SEP precondition
    sep = None
    if a["enrollment_window"] == "SEP":
        sep = _approved_sep_for(aid)
        if sep is None:
            raise err(ERR_SEP_NOT_APPROVED, "No approved SEP request for this application.")
    # OCC last
    if ehv != h["version"]:
        raise err(ERR_STALE_VERSION, "Stale household version.")
    a["status"] = "SUBMITTED"
    a["submitted_at"] = iso_ts_from_clock()
    if a["enrollment_window"] == "SEP" and sep is not None:
        a["sep_request_id"] = sep["id"]
    touch(a)
    touch(h)
    return success(application_view(a), 200)


def iso_ts_from_clock():
    dt = clock.now().astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


@app.route("/applications/<aid>/determine", methods=["POST"])
def determine_application(aid):
    user_id, role = get_auth()
    require_role(role, {"MarketplaceAdmin"})
    a = store.applications.get(aid)
    if not a:
        raise err(ERR_NOT_FOUND, "Application not found.")
    if a["status"] != "SUBMITTED":
        raise err(ERR_INVALID_STATE, "Application is not SUBMITTED.")
    h = store.households[a["household_id"]]
    # benchmark plan
    benchmark = _benchmark_plan(h["rating_area"], h["coverage_year"])
    if benchmark is None:
        raise err(ERR_NO_BENCHMARK_PLAN, "No SLCSP benchmark plan available.")
    fpl_snapshot = h["fpl_percent"]
    applicable_pct = calc.applicable_percentage(fpl_snapshot)
    max_aptc = calc.compute_max_aptc(
        h["household_magi_cents"], applicable_pct, benchmark["gross_premium_cents"]
    )
    csr_tier = calc.compute_csr_tier(fpl_snapshot)
    now = iso_ts()
    d = {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "application_id": aid,
        "fpl_percent_snapshot": fpl_snapshot,
        "applicable_pct": applicable_pct,
        "max_aptc_monthly_cents": max_aptc,
        "csr_tier": csr_tier,
        "is_subsidy_eligible": max_aptc > 0,
        "_seq": store.next_seq(),
    }
    store.determinations[d["id"]] = d
    a["status"] = "DETERMINED"
    touch(a)
    return success(determination_view(d), 201)


def _benchmark_plan(rating_area, coverage_year):
    for p in store.health_plans.values():
        if (p["rating_area"] == rating_area
                and p["coverage_year"] == coverage_year
                and p["metal_tier"] == "SILVER"
                and p["is_slcsp_benchmark"]):
            return p
    return None


def _determination_for(application_id):
    for d in store.determinations.values():
        if d["application_id"] == application_id:
            return d
    return None


@app.route("/applications/<aid>/reopen", methods=["POST"])
def reopen_application(aid):
    user_id, role = get_auth()
    require_role(role, {"Applicant", "Navigator"})
    a = store.applications.get(aid)
    if not a:
        raise err(ERR_NOT_FOUND, "Application not found.")
    h = store.households.get(a["household_id"])
    check_owner(role, user_id, h)
    if a["status"] != "DETERMINED":
        raise err(ERR_INVALID_STATE, "Application is not DETERMINED.")
    # no enrollment exists for this application
    if any(e["application_id"] == aid for e in store.enrollments.values()):
        raise err(ERR_INVALID_STATE, "Enrollment exists; cannot reopen.")
    d = _determination_for(aid)
    if d is not None:
        del store.determinations[d["id"]]
    a["status"] = "DRAFT"
    a["submitted_at"] = None
    touch(a)
    return success(application_view(a), 200)


@app.route("/applications/<aid>/cancel", methods=["POST"])
def cancel_application(aid):
    user_id, role = get_auth()
    require_role(role, {"Applicant", "Navigator"})
    a = store.applications.get(aid)
    if not a:
        raise err(ERR_NOT_FOUND, "Application not found.")
    h = store.households.get(a["household_id"])
    check_owner(role, user_id, h)
    if a["status"] not in ("DRAFT", "SUBMITTED"):
        raise err(ERR_INVALID_STATE, "Application cannot be cancelled from its current state.")
    a["status"] = "CANCELLED"
    touch(a)
    return success(application_view(a), 200)


@app.route("/applications/<aid>/determination", methods=["GET"])
def get_determination(aid):
    user_id, role = get_auth()
    require_role(role, VALID_ROLES)
    a = store.applications.get(aid)
    if not a:
        raise err(ERR_NOT_FOUND, "Application not found.")
    if role == "Applicant":
        h = store.households.get(a["household_id"])
        if not h or h["applicant_user_id"] != user_id:
            raise err(ERR_NOT_RESOURCE_OWNER, "Not the resource owner.")
    d = _determination_for(aid)
    result = [determination_view(d)] if d is not None else []
    limit, offset = parse_pagination()
    page, meta = paginate(result, limit, offset)
    return success(page, 200, pagination=meta)


# ──────────────────────────────────────────────────────────────────────────
# HealthPlan endpoints
# ──────────────────────────────────────────────────────────────────────────
@app.route("/health-plans", methods=["POST"])
def create_plan():
    user_id, role = get_auth()
    require_role(role, {"MarketplaceAdmin"})
    body = get_body()
    require_fields(body, ["rating_area", "coverage_year", "metal_tier", "gross_premium_cents"])
    if not isinstance(body["rating_area"], str):
        raise err(ERR_INVALID_REQUEST, "rating_area must be a string.")
    cy = body["coverage_year"]
    if isinstance(cy, bool) or not isinstance(cy, int):
        raise err(ERR_INVALID_REQUEST, "coverage_year must be an integer.")
    if body["metal_tier"] not in ENUM_METAL:
        raise err(ERR_INVALID_REQUEST, "Invalid metal_tier.")
    gp = body["gross_premium_cents"]
    if isinstance(gp, bool) or not isinstance(gp, int):
        raise err(ERR_INVALID_REQUEST, "gross_premium_cents must be an integer.")
    if gp <= 0:
        raise err(ERR_INVALID_REQUEST, "gross_premium_cents must be > 0.")
    is_bench = body.get("is_slcsp_benchmark", False)
    if is_bench is None:
        is_bench = False
    if not isinstance(is_bench, bool):
        raise err(ERR_INVALID_REQUEST, "is_slcsp_benchmark must be a boolean.")
    now = iso_ts()
    p = {
        "id": new_id(),
        "created_at": now,
        "rating_area": body["rating_area"],
        "coverage_year": cy,
        "metal_tier": body["metal_tier"],
        "gross_premium_cents": gp,
        "is_slcsp_benchmark": is_bench,
        "csr_eligible": body["metal_tier"] == "SILVER",
        "_seq": store.next_seq(),
    }
    store.health_plans[p["id"]] = p
    return success(plan_view(p), 201)


@app.route("/health-plans", methods=["GET"])
def list_plans():
    user_id, role = get_auth()
    require_role(role, VALID_ROLES)
    limit, offset = parse_pagination()
    items = list(store.health_plans.values())
    if request.args.get("rating_area"):
        items = [p for p in items if p["rating_area"] == request.args.get("rating_area")]
    if request.args.get("coverage_year"):
        try:
            cy = int(request.args.get("coverage_year"))
        except ValueError:
            raise err(ERR_INVALID_REQUEST, "Invalid coverage_year filter.")
        items = [p for p in items if p["coverage_year"] == cy]
    if request.args.get("metal_tier"):
        items = [p for p in items if p["metal_tier"] == request.args.get("metal_tier")]
    items = sort_by_created(items)
    page, meta = paginate(items, limit, offset)
    return success([plan_view(p) for p in page], 200, pagination=meta)


@app.route("/health-plans/<pid>", methods=["GET"])
def get_plan(pid):
    user_id, role = get_auth()
    require_role(role, VALID_ROLES)
    p = store.health_plans.get(pid)
    if not p:
        raise err(ERR_NOT_FOUND, "Plan not found.")
    return success(plan_view(p), 200)


# ──────────────────────────────────────────────────────────────────────────
# SepRequest endpoints
# ──────────────────────────────────────────────────────────────────────────
@app.route("/sep-requests", methods=["POST"])
def create_sep():
    user_id, role = get_auth()
    require_role(role, {"Applicant", "Navigator"})
    body = get_body()
    require_fields(body, ["application_id", "qualifying_event_type", "event_date"])
    if body["qualifying_event_type"] not in ENUM_QUALIFYING:
        raise err(ERR_INVALID_REQUEST, "Invalid qualifying_event_type.")
    if not isinstance(body["event_date"], str):
        raise err(ERR_INVALID_REQUEST, "event_date must be a string.")
    try:
        date.fromisoformat(body["event_date"])
    except (ValueError, TypeError):
        raise err(ERR_INVALID_REQUEST, "event_date must be YYYY-MM-DD.")
    a = store.applications.get(body["application_id"])
    if not a:
        raise err(ERR_REFERENCED_NOT_FOUND, "Referenced application not found.")
    h = store.households.get(a["household_id"])
    check_owner(role, user_id, h)
    now = iso_ts()
    s = {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "application_id": body["application_id"],
        "qualifying_event_type": body["qualifying_event_type"],
        "event_date": body["event_date"],
        "status": "PENDING",
        "window_close_date": calc.compute_sep_window_close(body["event_date"]),
        "_seq": store.next_seq(),
    }
    store.sep_requests[s["id"]] = s
    return success(sep_view(s), 201)


@app.route("/sep-requests/<sid>", methods=["GET"])
def get_sep(sid):
    user_id, role = get_auth()
    require_role(role, VALID_ROLES)
    s = store.sep_requests.get(sid)
    if not s:
        raise err(ERR_NOT_FOUND, "SEP request not found.")
    if role == "Applicant":
        a = store.applications.get(s["application_id"])
        h = store.households.get(a["household_id"]) if a else None
        if not h or h["applicant_user_id"] != user_id:
            raise err(ERR_NOT_RESOURCE_OWNER, "Not the resource owner.")
    return success(sep_view(s), 200)


@app.route("/sep-requests", methods=["GET"])
def list_sep():
    user_id, role = get_auth()
    require_role(role, VALID_ROLES)
    limit, offset = parse_pagination()
    items = list(store.sep_requests.values())
    if role == "Applicant":
        owned = {h["id"] for h in store.households.values() if h["applicant_user_id"] == user_id}
        owned_apps = {a["id"] for a in store.applications.values() if a["household_id"] in owned}
        items = [s for s in items if s["application_id"] in owned_apps]
    if request.args.get("application_id"):
        items = [s for s in items if s["application_id"] == request.args.get("application_id")]
    if request.args.get("status"):
        items = [s for s in items if s["status"] == request.args.get("status")]
    items = sort_by_created(items)
    page, meta = paginate(items, limit, offset)
    return success([sep_view(s) for s in page], 200, pagination=meta)


@app.route("/sep-requests/<sid>/approve", methods=["POST"])
def approve_sep(sid):
    user_id, role = get_auth()
    require_role(role, {"MarketplaceAdmin"})
    s = store.sep_requests.get(sid)
    if not s:
        raise err(ERR_NOT_FOUND, "SEP request not found.")
    if s["status"] != "PENDING":
        raise err(ERR_INVALID_STATE, "SEP request is not PENDING.")
    a = store.applications.get(s["application_id"])
    if a is None or a["status"] != "DRAFT":
        raise err(ERR_INVALID_STATE, "Linked application is not DRAFT.")
    # window open check
    if clock_date() > date.fromisoformat(s["window_close_date"]):
        raise err(ERR_SEP_WINDOW_CLOSED, "SEP filing window has closed.")
    s["status"] = "APPROVED"
    touch(s)
    return success(sep_view(s), 200)


@app.route("/sep-requests/<sid>/deny", methods=["POST"])
def deny_sep(sid):
    user_id, role = get_auth()
    require_role(role, {"MarketplaceAdmin"})
    s = store.sep_requests.get(sid)
    if not s:
        raise err(ERR_NOT_FOUND, "SEP request not found.")
    if s["status"] != "PENDING":
        raise err(ERR_INVALID_STATE, "SEP request is not PENDING.")
    s["status"] = "DENIED"
    touch(s)
    return success(sep_view(s), 200)


# ──────────────────────────────────────────────────────────────────────────
# Enrollment endpoints
# ──────────────────────────────────────────────────────────────────────────
def _coverage_interval(effective_date_str, coverage_year):
    start = date.fromisoformat(effective_date_str)
    end = date(coverage_year, 12, 31)
    return start, end


@app.route("/enrollments", methods=["POST"])
def create_enrollment():
    user_id, role = get_auth()
    require_role(role, {"Applicant", "Navigator"})
    body = get_body()
    # FK existence
    require_fields(body, ["application_id", "plan_id", "expected_household_version"])
    a = store.applications.get(body["application_id"])
    if not a:
        raise err(ERR_REFERENCED_NOT_FOUND, "Referenced application not found.")
    p = store.health_plans.get(body["plan_id"])
    if not p:
        raise err(ERR_REFERENCED_NOT_FOUND, "Referenced plan not found.")
    h = store.households.get(a["household_id"])
    check_owner(role, user_id, h)
    # state
    if a["status"] != "DETERMINED":
        raise err(ERR_INVALID_STATE, "Application is not DETERMINED.")
    # schema
    ehv = body["expected_household_version"]
    if isinstance(ehv, bool) or not isinstance(ehv, int):
        raise err(ERR_INVALID_REQUEST, "expected_household_version must be an integer.")
    elected = validate_nonneg_int(body, "elected_aptc_monthly_cents", required=False, default=0)
    # business: plan area + year match (priority 9)
    if p["rating_area"] != h["rating_area"] or p["coverage_year"] != h["coverage_year"]:
        raise err(ERR_PLAN_AREA_MISMATCH, "Plan rating area/coverage year mismatch.")
    determination = _determination_for(a["id"])
    if determination is None:
        # should not happen for DETERMINED, but guard
        raise err(ERR_INVALID_STATE, "No determination found.")
    # compute effective date for overlap check
    sub_date = date.fromisoformat(a["submitted_at"][:10])
    sep_event_type = None
    sep_event_date = None
    if a["enrollment_window"] == "SEP":
        sep = _approved_sep_for(a["id"])
        if sep is not None:
            sep_event_type = sep["qualifying_event_type"]
            sep_event_date = sep["event_date"]
    effective_date = calc.compute_effective_date(
        sub_date, a["enrollment_window"], sep_event_type, sep_event_date
    )
    # overlapping coverage (priority 13)
    new_start, new_end = _coverage_interval(effective_date, h["coverage_year"])
    for e in store.enrollments.values():
        if e["lifecycle_status"] not in ("PENDING_EFFECTUATION", "ACTIVE"):
            continue
        e_app = store.applications.get(e["application_id"])
        if not e_app or e_app["household_id"] != h["id"]:
            continue
        e_plan = store.health_plans.get(e["plan_id"])
        if not e_plan or e_plan["coverage_year"] != h["coverage_year"]:
            continue
        e_start, e_end = _coverage_interval(e["effective_date"], h["coverage_year"])
        # closed intervals overlap if start <= other_end and other_start <= end
        if new_start <= e_end and e_start <= new_end:
            raise err(ERR_OVERLAPPING_COVERAGE, "Coverage interval overlaps an existing enrollment.")
    # elected APTC ceiling (priority 14)
    if elected > determination["max_aptc_monthly_cents"]:
        raise err(ERR_APTC_EXCEEDS_MAX, "Elected APTC exceeds maximum.")
    # OCC (priority 15, last)
    if ehv != h["version"]:
        raise err(ERR_STALE_VERSION, "Stale household version.")
    # compute applied aptc + premiums
    applied = calc.compute_applied_aptc(
        elected, determination["max_aptc_monthly_cents"], p["gross_premium_cents"]
    )
    net = p["gross_premium_cents"] - applied
    first_month = calc.compute_first_month_proration(net, effective_date)
    now = iso_ts()
    e = {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "application_id": a["id"],
        "plan_id": p["id"],
        "elected_aptc_monthly_cents": elected,
        "applied_aptc_monthly_cents": applied,
        "net_premium_monthly_cents": net,
        "effective_date": effective_date,
        "first_month_premium_cents": first_month,
        "lifecycle_status": "PENDING_EFFECTUATION",
        "payment_status": "AWAITING_BINDER",
        "_seq": store.next_seq(),
    }
    store.enrollments[e["id"]] = e
    a["status"] = "ENROLLED"
    touch(a)
    return success(enrollment_view(e), 201)


@app.route("/enrollments/<eid>", methods=["GET"])
def get_enrollment(eid):
    user_id, role = get_auth()
    require_role(role, VALID_ROLES)
    e = store.enrollments.get(eid)
    if not e:
        raise err(ERR_NOT_FOUND, "Enrollment not found.")
    if role == "Applicant":
        a = store.applications.get(e["application_id"])
        h = store.households.get(a["household_id"]) if a else None
        if not h or h["applicant_user_id"] != user_id:
            raise err(ERR_NOT_RESOURCE_OWNER, "Not the resource owner.")
    return success(enrollment_view(e), 200)


@app.route("/enrollments", methods=["GET"])
def list_enrollments():
    user_id, role = get_auth()
    require_role(role, VALID_ROLES)
    limit, offset = parse_pagination()
    items = list(store.enrollments.values())
    if role == "Applicant":
        owned = {h["id"] for h in store.households.values() if h["applicant_user_id"] == user_id}
        owned_apps = {a["id"] for a in store.applications.values() if a["household_id"] in owned}
        items = [e for e in items if e["application_id"] in owned_apps]
    if request.args.get("application_id"):
        items = [e for e in items if e["application_id"] == request.args.get("application_id")]
    if request.args.get("plan_id"):
        items = [e for e in items if e["plan_id"] == request.args.get("plan_id")]
    items = sort_by_created(items)
    page, meta = paginate(items, limit, offset)
    return success([enrollment_view(e) for e in page], 200, pagination=meta)


def _enrollment_owner_check(role, user_id, e):
    if role == "Applicant":
        a = store.applications.get(e["application_id"])
        h = store.households.get(a["household_id"]) if a else None
        if not h or h["applicant_user_id"] != user_id:
            raise err(ERR_NOT_RESOURCE_OWNER, "Not the resource owner.")


@app.route("/enrollments/<eid>/pay-binder", methods=["POST"])
def pay_binder(eid):
    user_id, role = get_auth()
    require_role(role, {"Applicant", "Navigator"})
    e = store.enrollments.get(eid)
    if not e:
        raise err(ERR_NOT_FOUND, "Enrollment not found.")
    _enrollment_owner_check(role, user_id, e)
    if e["payment_status"] != "AWAITING_BINDER":
        raise err(ERR_INVALID_STATE, "Payment status is not AWAITING_BINDER.")
    e["payment_status"] = "PAID"
    touch(e)
    return success(enrollment_view(e), 200)


@app.route("/enrollments/<eid>/effectuate", methods=["POST"])
def effectuate(eid):
    user_id, role = get_auth()
    require_role(role, {"MarketplaceAdmin"})
    e = store.enrollments.get(eid)
    if not e:
        raise err(ERR_NOT_FOUND, "Enrollment not found.")
    if e["lifecycle_status"] != "PENDING_EFFECTUATION":
        raise err(ERR_INVALID_STATE, "Lifecycle status is not PENDING_EFFECTUATION.")
    if e["payment_status"] != "PAID":
        raise err(ERR_INVALID_STATE, "Binder must be PAID before effectuation.")
    e["lifecycle_status"] = "ACTIVE"
    touch(e)
    return success(enrollment_view(e), 200)


@app.route("/enrollments/<eid>/mark-delinquent", methods=["POST"])
def mark_delinquent(eid):
    user_id, role = get_auth()
    require_role(role, {"MarketplaceAdmin"})
    e = store.enrollments.get(eid)
    if not e:
        raise err(ERR_NOT_FOUND, "Enrollment not found.")
    if e["payment_status"] != "PAID":
        raise err(ERR_INVALID_STATE, "Payment status is not PAID.")
    e["payment_status"] = "DELINQUENT"
    touch(e)
    return success(enrollment_view(e), 200)


@app.route("/enrollments/<eid>/terminate", methods=["POST"])
def terminate(eid):
    user_id, role = get_auth()
    require_role(role, {"Applicant", "Navigator"})
    e = store.enrollments.get(eid)
    if not e:
        raise err(ERR_NOT_FOUND, "Enrollment not found.")
    _enrollment_owner_check(role, user_id, e)
    if e["lifecycle_status"] not in ("PENDING_EFFECTUATION", "ACTIVE"):
        raise err(ERR_INVALID_STATE, "Enrollment cannot be terminated from its current state.")
    e["lifecycle_status"] = "TERMINATED"
    touch(e)
    return success(enrollment_view(e), 200)


# ──────────────────────────────────────────────────────────────────────────
# Reconciliation endpoints
# ──────────────────────────────────────────────────────────────────────────
@app.route("/reconciliations", methods=["POST"])
def create_reconciliation():
    user_id, role = get_auth()
    require_role(role, {"MarketplaceAdmin"})
    body = get_body()
    require_fields(body, ["enrollment_id", "actual_annual_magi_cents", "months_enrolled"])
    e = store.enrollments.get(body["enrollment_id"])
    if not e:
        raise err(ERR_REFERENCED_NOT_FOUND, "Referenced enrollment not found.")
    magi = body["actual_annual_magi_cents"]
    if isinstance(magi, bool) or not isinstance(magi, int):
        raise err(ERR_INVALID_REQUEST, "actual_annual_magi_cents must be an integer.")
    if magi < 0:
        raise err(ERR_INVALID_REQUEST, "actual_annual_magi_cents must be >= 0.")
    months = body["months_enrolled"]
    if isinstance(months, bool) or not isinstance(months, int):
        raise err(ERR_INVALID_REQUEST, "months_enrolled must be an integer.")
    if months < 1 or months > 12:
        raise err(ERR_INVALID_REQUEST, "months_enrolled must be between 1 and 12.")
    # reuse determination's countable_size + benchmark
    a = store.applications.get(e["application_id"])
    h = store.households.get(a["household_id"])
    benchmark = _benchmark_plan(h["rating_area"], h["coverage_year"])
    benchmark_cents = benchmark["gross_premium_cents"] if benchmark else 0
    countable_size = h["countable_size"]
    advanced, allowed, settlement = calc.compute_reconciliation(
        e["applied_aptc_monthly_cents"], months, magi, countable_size, benchmark_cents
    )
    now = iso_ts()
    r = {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "enrollment_id": e["id"],
        "actual_annual_magi_cents": magi,
        "months_enrolled": months,
        "advanced_aptc_total_cents": advanced,
        "allowed_aptc_total_cents": allowed,
        "settlement_cents": settlement,
        "_seq": store.next_seq(),
    }
    store.reconciliations[r["id"]] = r
    return success(reconciliation_view(r), 201)


@app.route("/reconciliations/<rid>", methods=["GET"])
def get_reconciliation(rid):
    user_id, role = get_auth()
    require_role(role, VALID_ROLES)
    r = store.reconciliations.get(rid)
    if not r:
        raise err(ERR_NOT_FOUND, "Reconciliation record not found.")
    if role == "Applicant":
        e = store.enrollments.get(r["enrollment_id"])
        a = store.applications.get(e["application_id"]) if e else None
        h = store.households.get(a["household_id"]) if a else None
        if not h or h["applicant_user_id"] != user_id:
            raise err(ERR_NOT_RESOURCE_OWNER, "Not the resource owner.")
    return success(reconciliation_view(r), 200)


@app.route("/reconciliations", methods=["GET"])
def list_reconciliations():
    user_id, role = get_auth()
    require_role(role, VALID_ROLES)
    limit, offset = parse_pagination()
    items = list(store.reconciliations.values())
    if role == "Applicant":
        owned = {h["id"] for h in store.households.values() if h["applicant_user_id"] == user_id}
        owned_apps = {a["id"] for a in store.applications.values() if a["household_id"] in owned}
        owned_enr = {en["id"] for en in store.enrollments.values() if en["application_id"] in owned_apps}
        items = [r for r in items if r["enrollment_id"] in owned_enr]
    if request.args.get("enrollment_id"):
        items = [r for r in items if r["enrollment_id"] == request.args.get("enrollment_id")]
    items = sort_by_created(items)
    page, meta = paginate(items, limit, offset)
    return success([reconciliation_view(r) for r in page], 200, pagination=meta)


# ──────────────────────────────────────────────────────────────────────────
# Test clock
# ──────────────────────────────────────────────────────────────────────────
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    user_id, role = get_auth()
    require_role(role, {"MarketplaceAdmin"})
    body = get_body()
    require_fields(body, ["to_iso8601"])
    raw = body["to_iso8601"]
    if not isinstance(raw, str):
        raise err(ERR_INVALID_REQUEST, "to_iso8601 must be a string.")
    try:
        s = raw.replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        raise err(ERR_INVALID_REQUEST, "to_iso8601 must be a valid ISO 8601 timestamp.")
    clock.set(dt)
    return success({}, 200)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    # On some hosts socket.getfqdn() blocks ~5s on a reverse-DNS timeout. Werkzeug's
    # dev server calls it when binding 0.0.0.0 (to compute server_name), which would
    # push cold-boot past the harness's restart window. Neutralize it so we still
    # bind 0.0.0.0 (per the build contract) but start listening immediately.
    import socket as _socket
    _socket.getfqdn = lambda *a, **k: "localhost"
    app.run(host="0.0.0.0", port=port, threaded=True)
