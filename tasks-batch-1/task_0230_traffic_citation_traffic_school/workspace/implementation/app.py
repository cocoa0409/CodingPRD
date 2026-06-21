"""Traffic Citation Payment & Traffic School API — Flask entry point.

Single-module implementation: all routes, state machines, calculations and
validations live here, backed by the in-memory store in db.py. Storage is
in-memory only; every process restart wipes all state.

Structural names (headers, envelope, error ids, OCC field, pagination params)
are taken verbatim from PRD.md / SCAFFOLD.yaml — see comments at each use.
"""
import os
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP

from flask import Flask, request

import db
import errors as E
from errors import ApiError, err
from response import success, error

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Roles (PRD §2.1) and enum value sets
# ---------------------------------------------------------------------------
ROLES = {"Driver", "CourtClerk", "HearingOfficer", "DmvAdmin"}

PAYMENT_METHODS = {"CARD", "CASH", "CHECK"}
VERDICTS = {"DISMISS", "UPHOLD"}


# ---------------------------------------------------------------------------
# Error handlers
# ---------------------------------------------------------------------------
@app.errorhandler(ApiError)
def _handle_api_error(e):
    return error(e.error_id, e.message, e.http_status)


@app.errorhandler(404)
def _handle_404(e):
    return error("ERR_NOT_FOUND", "Resource not found.", 404)


@app.errorhandler(405)
def _handle_405(e):
    return error("ERR_NOT_FOUND", "Method not allowed.", 404)


@app.errorhandler(Exception)
def _handle_unexpected(e):
    if isinstance(e, ApiError):
        return _handle_api_error(e)
    return error("ERR_INTERNAL", "Internal server error: %s" % e, 500)


# ===========================================================================
# Auth / RBAC (PRD §2.1, validations priority 1-2)
# ===========================================================================
def auth():
    """Validate X-User-ID + X-User-Role headers. Returns (user_id, role)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role:
        raise err(E.ERR_MISSING_AUTH, "Missing X-User-ID or X-User-Role header.")
    if role not in ROLES:
        raise err(E.ERR_MISSING_AUTH, "Unknown or malformed role.")
    return user_id, role


def require_role(role, allowed):
    if role not in allowed:
        raise err(E.ERR_FORBIDDEN_FOR_ROLE,
                  "Role %s is not permitted for this operation." % role)


# ===========================================================================
# Request-body helpers and validation (ERR_INVALID_REQUEST, priority 20)
# ===========================================================================
def body():
    data = request.get_json(silent=True)
    if data is None or not isinstance(data, dict):
        return {}
    return data


def require_fields(data, fields):
    for f in fields:
        if f not in data or data[f] is None:
            raise err(E.ERR_INVALID_REQUEST, "Missing required field: %s" % f)


def as_int(value, field):
    if isinstance(value, bool) or not isinstance(value, int):
        raise err(E.ERR_INVALID_REQUEST, "Field %s must be an integer." % field)
    return value


def as_nonneg_int(value, field):
    v = as_int(value, field)
    if v < 0:
        raise err(E.ERR_INVALID_REQUEST, "Field %s must be non-negative." % field)
    return v


def as_number(value, field):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise err(E.ERR_INVALID_REQUEST, "Field %s must be a number." % field)
    return value


def as_str(value, field):
    if not isinstance(value, str) or value == "":
        raise err(E.ERR_INVALID_REQUEST, "Field %s must be a non-empty string." % field)
    return value


def parse_dt(value, field):
    """Parse an ISO 8601 datetime into an aware UTC datetime."""
    if not isinstance(value, str):
        raise err(E.ERR_INVALID_REQUEST, "Field %s must be an ISO 8601 string." % field)
    s = value.strip()
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
    except (ValueError, TypeError):
        raise err(E.ERR_INVALID_REQUEST, "Field %s is not a valid ISO 8601 datetime." % field)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# ===========================================================================
# Date helpers
# ===========================================================================
def add_months(dt, months):
    """Advance an aware datetime by a whole number of calendar months,
    clamping the day to the last valid day of the target month."""
    month_index = dt.month - 1 + months
    year = dt.year + month_index // 12
    month = month_index % 12 + 1
    # clamp day
    day = dt.day
    while True:
        try:
            return dt.replace(year=year, month=month, day=day)
        except ValueError:
            day -= 1
            if day < 1:
                raise


def round_half_up(value):
    """Round a Decimal/number to the nearest integer, half rounding up."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ===========================================================================
# Common-field helpers
# ===========================================================================
def stamp_create(rec, versioned=True):
    rec["id"] = db.new_id()
    rec["created_at"] = db.iso_now_ms()
    rec["_seq"] = db.next_seq()
    if versioned:
        rec["updated_at"] = rec["created_at"]
        rec["version"] = 1
    return rec


def touch(rec):
    """Bump updated_at + version on a mutated versioned resource."""
    rec["updated_at"] = db.iso_now_ms()
    rec["version"] = rec.get("version", 1) + 1


# ===========================================================================
# Serialization — strip internal keys (_seq) from outgoing payloads
# ===========================================================================
INTERNAL_KEYS = {"_seq", "_completed_at"}


def view(rec):
    return {k: v for k, v in rec.items() if k not in INTERNAL_KEYS}


def driver_view(driver):
    """Driver with derived fields computed fresh on read."""
    out = view(driver)
    out["license_status"] = compute_license_status(driver["id"])
    out["point_balance"] = compute_point_balance(driver["id"])
    out["fta_warrant_active"] = compute_fta_warrant_active(driver["id"])
    return out


# ===========================================================================
# Pagination (PRD §2.3, envelope pagination_fields/defaults)
# ===========================================================================
def paginate(rows):
    """rows: list of records sorted by created_at ascending (use _seq).
    Returns (page_rows, pagination_meta)."""
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args:
        try:
            limit = int(args["limit"])
        except (ValueError, TypeError):
            raise err(E.ERR_INVALID_REQUEST, "limit must be an integer.")
        if limit < 1:
            limit = 1
        if limit > 100:
            limit = 100
    if "offset" in args:
        try:
            offset = int(args["offset"])
        except (ValueError, TypeError):
            raise err(E.ERR_INVALID_REQUEST, "offset must be an integer.")
        if offset < 0:
            offset = 0
    ordered = sorted(rows, key=lambda r: r["_seq"])
    total = len(ordered)
    page = ordered[offset:offset + limit]
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }
    return page, pagination


# ===========================================================================
# Lookups (existence; ERR_NOT_FOUND, priority 3)
# ===========================================================================
def get_or_404(store, rid):
    rec = store.get(rid)
    if rec is None:
        raise err(E.ERR_NOT_FOUND, "Resource not found.")
    return rec


# ===========================================================================
# Derived driver fields (PRD §2.7, §3.8; calcs license_status, driver_point_balance)
# ===========================================================================
def driver_open_holds(driver_id):
    return [h for h in db.license_holds.values()
            if h["driver_id"] == driver_id and h["status"] == "OPEN"]


def compute_license_status(driver_id):
    open_holds = driver_open_holds(driver_id)
    if any(h["hold_type"] == "POINT_SUSPENSION" for h in open_holds):
        return "SUSPENDED"
    if open_holds:
        return "HELD"
    return "VALID"


def compute_point_balance(driver_id):
    """Sum of ACTIVE point ledger entries within the rolling window.

    The window is jurisdiction.point_window_months back from now. The driver's
    jurisdiction supplies the window length.
    """
    driver = db.drivers.get(driver_id)
    if driver is None:
        return 0
    juris = db.jurisdictions.get(driver["jurisdiction_id"])
    window_months = juris["point_window_months"] if juris else 12
    window_start = add_months(db.now(), -window_months)
    total = 0
    for e in db.point_ledger.values():
        if e["driver_id"] != driver_id or e["state"] != "ACTIVE":
            continue
        eff = parse_stored_dt(e["effective_at"])
        if eff >= window_start:
            total += e["points"]
    return total


def compute_fta_warrant_active(driver_id):
    return any(w["driver_id"] == driver_id and w["status"] == "ACTIVE"
               for w in db.warrants.values())


def parse_stored_dt(value):
    s = value
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# ===========================================================================
# Point-suspension re-evaluation (calc driver_point_balance side effect)
# ===========================================================================
def reevaluate_point_suspension(driver_id):
    """Open a POINT_SUSPENSION hold when balance >= threshold; release any open
    POINT_SUSPENSION hold when balance falls below threshold.

    PRD §3.6: holds "are cleared either by a cascade (payment, dismissal, school
    completion) or by an explicit DMV release." PRD §3.9: masking the entries
    "re-evaluates the driver's point suspension and may release a point-suspension
    hold, re-deriving the driver's `license_status`.\""""
    driver = db.drivers.get(driver_id)
    if driver is None:
        return
    juris = db.jurisdictions.get(driver["jurisdiction_id"])
    threshold = juris["point_suspension_threshold"] if juris else 4
    balance = compute_point_balance(driver_id)
    existing = [h for h in db.license_holds.values()
                if h["driver_id"] == driver_id and h["status"] == "OPEN"
                and h["hold_type"] == "POINT_SUSPENSION"]
    if balance >= threshold:
        if not existing:
            open_hold(driver_id, None, "POINT_SUSPENSION")
    else:
        for h in existing:
            h["status"] = "RELEASED"
            h["released_at"] = db.iso_now_ms()
            touch(h)


# ===========================================================================
# License-hold open/release cascades
# ===========================================================================
def open_hold(driver_id, citation_id, hold_type):
    hold = {
        "driver_id": driver_id,
        "citation_id": citation_id,
        "hold_type": hold_type,
        "status": "OPEN",
        "released_at": None,
    }
    stamp_create(hold)
    db.license_holds[hold["id"]] = hold
    return hold


def open_nonpayment_hold_if_none(citation):
    """Open a NONPAYMENT_HOLD for the citation if none is currently open."""
    existing = [h for h in db.license_holds.values()
                if h["citation_id"] == citation["id"] and h["status"] == "OPEN"]
    if not existing:
        open_hold(citation["driver_id"], citation["id"], "NONPAYMENT_HOLD")


def release_citation_holds(citation):
    """Release OPEN NONPAYMENT_HOLD/FTA_HOLD tied to this citation (cascade)."""
    for h in db.license_holds.values():
        if (h["citation_id"] == citation["id"] and h["status"] == "OPEN"
                and h["hold_type"] in ("NONPAYMENT_HOLD", "FTA_HOLD")):
            h["status"] = "RELEASED"
            h["released_at"] = db.iso_now_ms()
            touch(h)
    # re-derivation happens on read; nothing else to write for license_status.


def quash_citation_warrants(citation):
    """Quash ACTIVE warrants tied to this citation (cascade)."""
    for w in db.warrants.values():
        if w["citation_id"] == citation["id"] and w["status"] == "ACTIVE":
            w["status"] = "QUASHED"
            w["quashed_at"] = db.iso_now_ms()
            touch(w)


# ===========================================================================
# Calculations
# ===========================================================================
def recompute_base_fine(citation):
    total = sum(c["base_fine_cents"] for c in db.charges.values()
                if c["citation_id"] == citation["id"])
    citation["base_fine_cents"] = total
    return total


def compute_assessed_total(citation, juris):
    """calc assessed_total: surcharge on base_fine only, rounded BEFORE adding
    integer court fee."""
    base = recompute_base_fine(citation)
    court_fee = juris["base_court_fee_cents"]
    surcharge = round_half_up(Decimal(base) * Decimal(str(juris["surcharge_pct"])))
    return base + court_fee + surcharge


def recompute_balance(citation):
    """calc citation_balance: assessed_total + penalty - amount_paid (POSTED)."""
    paid = sum(p["amount_cents"] for p in db.payments.values()
               if p["citation_id"] == citation["id"] and p["status"] == "POSTED")
    citation["amount_paid_cents"] = paid
    citation["balance_cents"] = (citation["assessed_total_cents"]
                                 + citation["penalty_cents"] - paid)
    return citation["balance_cents"]


# ===========================================================================
# Citation disposition / collections-recall helpers
# ===========================================================================
def recall_collections(citation):
    """On citation close, any REFERRED collections referral -> RECALLED."""
    for r in db.collections_referrals.values():
        if r["citation_id"] == citation["id"] and r["status"] == "REFERRED":
            r["status"] = "RECALLED"
            touch(r)


# ===========================================================================
# Ownership (priority 4)
# ===========================================================================
def require_owner(role, user_id, driver_id):
    """For Driver-initiated actions, X-User-ID must equal the resource driver_id."""
    if role == "Driver" and user_id != driver_id:
        raise err(E.ERR_NOT_RESOURCE_OWNER, "Driver does not own this resource.")


# ===========================================================================
# Routes — Test clock
# ===========================================================================
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    _, role = auth()
    require_role(role, {"CourtClerk", "DmvAdmin"})
    data = body()
    require_fields(data, ["to_iso8601"])
    dt = parse_dt(data["to_iso8601"], "to_iso8601")
    db.set_clock(dt)
    return success({}, 200)


# ===========================================================================
# Routes — Jurisdiction
# ===========================================================================
JURIS_DEFAULTS = {
    "collections_age_days": 30,
    "school_eligible_max_points": 1,
    "school_cooldown_months": 18,
    "point_suspension_threshold": 4,
    "point_window_months": 12,
}
JURIS_REQUIRED = ["name", "state_code", "base_court_fee_cents", "surcharge_pct",
                  "late_penalty_cents", "installment_setup_fee_cents",
                  "min_installment_cents", "collections_fee_pct",
                  "traffic_school_fee_cents"]
JURIS_INT_FIELDS = ["base_court_fee_cents", "late_penalty_cents",
                    "installment_setup_fee_cents", "min_installment_cents",
                    "traffic_school_fee_cents", "collections_age_days",
                    "school_eligible_max_points", "school_cooldown_months",
                    "point_suspension_threshold", "point_window_months"]


@app.route("/jurisdictions", methods=["POST"])
def create_jurisdiction():
    _, role = auth()
    require_role(role, {"CourtClerk", "DmvAdmin"})
    data = body()
    require_fields(data, JURIS_REQUIRED)
    as_str(data["name"], "name")
    as_str(data["state_code"], "state_code")
    rec = {}
    for f in JURIS_REQUIRED:
        if f in ("name", "state_code"):
            rec[f] = data[f]
        elif f in ("surcharge_pct", "collections_fee_pct"):
            rec[f] = as_number(data[f], f)
        else:
            rec[f] = as_nonneg_int(data[f], f)
    for f, default in JURIS_DEFAULTS.items():
        if f in data and data[f] is not None:
            rec[f] = as_nonneg_int(data[f], f)
        else:
            rec[f] = default
    stamp_create(rec)
    db.jurisdictions[rec["id"]] = rec
    return success(view(rec), 201)


@app.route("/jurisdictions/<jid>", methods=["GET"])
def get_jurisdiction(jid):
    _, role = auth()
    require_role(role, ROLES)
    rec = get_or_404(db.jurisdictions, jid)
    return success(view(rec), 200)


# ===========================================================================
# Routes — Driver
# ===========================================================================
@app.route("/drivers", methods=["POST"])
def create_driver():
    _, role = auth()
    require_role(role, {"CourtClerk", "DmvAdmin"})
    data = body()
    require_fields(data, ["jurisdiction_id", "license_number", "full_name"])
    juris = db.jurisdictions.get(data["jurisdiction_id"])
    if juris is None:
        raise err(E.ERR_INVALID_REQUEST, "jurisdiction_id does not reference a jurisdiction.")
    license_number = as_str(data["license_number"], "license_number")
    as_str(data["full_name"], "full_name")
    # unique license_number within jurisdiction
    for d in db.drivers.values():
        if (d["jurisdiction_id"] == data["jurisdiction_id"]
                and d["license_number"] == license_number):
            raise err(E.ERR_INVALID_REQUEST, "license_number already exists in jurisdiction.")
    rec = {
        "jurisdiction_id": data["jurisdiction_id"],
        "license_number": license_number,
        "full_name": data["full_name"],
    }
    stamp_create(rec)
    db.drivers[rec["id"]] = rec
    return success(driver_view(rec), 201)


@app.route("/drivers/<did>", methods=["GET"])
def get_driver(did):
    _, role = auth()
    require_role(role, ROLES)
    rec = get_or_404(db.drivers, did)
    return success(driver_view(rec), 200)


@app.route("/drivers", methods=["GET"])
def list_drivers():
    _, role = auth()
    require_role(role, ROLES)
    rows = list(db.drivers.values())
    jid = request.args.get("jurisdiction_id")
    ln = request.args.get("license_number")
    if jid is not None:
        rows = [r for r in rows if r["jurisdiction_id"] == jid]
    if ln is not None:
        rows = [r for r in rows if r["license_number"] == ln]
    page, pg = paginate(rows)
    return success([driver_view(r) for r in page], 200, pagination=pg)


# ===========================================================================
# Routes — Citation
# ===========================================================================
def new_citation_record(driver_id, citation_number, issued_at, appear_by):
    rec = {
        "driver_id": driver_id,
        "citation_number": citation_number,
        "issued_at": issued_at,
        "appear_by": appear_by,
        "base_fine_cents": 0,
        "assessed_total_cents": 0,
        "penalty_cents": 0,
        "amount_paid_cents": 0,
        "balance_cents": 0,
        "financial_status": "DRAFT",
        "adjudication_status": "NONE",
        "disposition": "OPEN",
        "late_penalty_applied": False,
        "collections_referred": False,
    }
    stamp_create(rec)
    return rec


@app.route("/citations", methods=["POST"])
def create_citation():
    _, role = auth()
    require_role(role, {"CourtClerk"})
    data = body()
    require_fields(data, ["driver_id", "citation_number", "issued_at", "appear_by"])
    driver = db.drivers.get(data["driver_id"])
    if driver is None:
        raise err(E.ERR_INVALID_REQUEST, "driver_id does not reference a driver.")
    citation_number = as_str(data["citation_number"], "citation_number")
    issued_at = parse_dt(data["issued_at"], "issued_at")
    appear_by = parse_dt(data["appear_by"], "appear_by")
    # unique citation_number within jurisdiction (driver -> jurisdiction)
    juris_id = driver["jurisdiction_id"]
    for c in db.citations.values():
        other = db.drivers.get(c["driver_id"])
        if (other and other["jurisdiction_id"] == juris_id
                and c["citation_number"] == citation_number):
            raise err(E.ERR_INVALID_REQUEST, "citation_number already exists in jurisdiction.")
    rec = new_citation_record(data["driver_id"], citation_number,
                              db.iso(issued_at), db.iso(appear_by))
    db.citations[rec["id"]] = rec
    return success(view(rec), 201)


@app.route("/citations/<cid>", methods=["GET"])
def get_citation(cid):
    _, role = auth()
    require_role(role, ROLES)
    rec = get_or_404(db.citations, cid)
    return success(view(rec), 200)


@app.route("/citations", methods=["GET"])
def list_citations():
    _, role = auth()
    require_role(role, ROLES)
    rows = list(db.citations.values())
    did = request.args.get("driver_id")
    cn = request.args.get("citation_number")
    fs = request.args.get("financial_status")
    if did is not None:
        rows = [r for r in rows if r["driver_id"] == did]
    if cn is not None:
        rows = [r for r in rows if r["citation_number"] == cn]
    if fs is not None:
        rows = [r for r in rows if r["financial_status"] == fs]
    page, pg = paginate(rows)
    return success([view(r) for r in page], 200, pagination=pg)


@app.route("/citations/<cid>/assess", methods=["POST"])
def assess_citation(cid):
    _, role = auth()
    require_role(role, {"CourtClerk"})
    citation = get_or_404(db.citations, cid)
    # state precondition before charge precondition? PRD §3.3 lists charges
    # check then DRAFT check; validations priority puts ERR_INVALID_STATE (5)
    # before ERR_NO_CHARGES (14). PRD prose: "must already carry at least one
    # charge ... and it must currently be in DRAFT". State precedence per the
    # global validation ordering (§2.9) wins, so check state first.
    if citation["financial_status"] != "DRAFT":
        raise err(E.ERR_INVALID_STATE, "Citation is not in DRAFT.")
    has_charge = any(c["citation_id"] == cid for c in db.charges.values())
    if not has_charge:
        raise err(E.ERR_NO_CHARGES, "Citation has no charges.")
    juris = db.jurisdictions[db.drivers[citation["driver_id"]]["jurisdiction_id"]]
    citation["assessed_total_cents"] = compute_assessed_total(citation, juris)
    citation["financial_status"] = "ASSESSED"
    recompute_balance(citation)
    touch(citation)
    return success(view(citation), 200)


@app.route("/citations/<cid>/void", methods=["POST"])
def void_citation(cid):
    _, role = auth()
    require_role(role, {"CourtClerk"})
    citation = get_or_404(db.citations, cid)
    fs = citation["financial_status"]
    # PRD §3.10: void is gated on "no posted payment exists against it" — a void
    # with payments present is rejected with ERR_HAS_PAYMENTS. A DRAFT/ASSESSED
    # citation can never carry a posted payment (the first posted payment moves
    # the citation to PARTIALLY_PAID/PAID), so for ERR_HAS_PAYMENTS to be a
    # reachable rejection the payment check must precede the bare state check.
    has_payment = any(p["citation_id"] == cid and p["status"] == "POSTED"
                      for p in db.payments.values())
    if has_payment:
        raise err(E.ERR_HAS_PAYMENTS, "Citation has posted payments.")
    if fs not in ("DRAFT", "ASSESSED"):
        raise err(E.ERR_INVALID_STATE, "Citation cannot be voided from %s." % fs)
    # ASSESSED extra precondition: adjudication_status != UPHELD
    if fs == "ASSESSED" and citation["adjudication_status"] == "UPHELD":
        raise err(E.ERR_INVALID_STATE, "Cannot void an UPHELD citation.")
    citation["financial_status"] = "VOID"
    citation["disposition"] = "CLOSED"
    if fs == "ASSESSED":
        release_citation_holds(citation)
        quash_citation_warrants(citation)
    recall_collections(citation)
    touch(citation)
    return success(view(citation), 200)


@app.route("/citations/<cid>/apply-late-penalty", methods=["POST"])
def apply_late_penalty(cid):
    _, role = auth()
    require_role(role, {"CourtClerk"})
    citation = get_or_404(db.citations, cid)
    if citation["financial_status"] not in ("ASSESSED", "PARTIALLY_PAID"):
        raise err(E.ERR_INVALID_STATE, "Late penalty only valid in ASSESSED/PARTIALLY_PAID.")
    appear_by = parse_stored_dt(citation["appear_by"])
    if db.now() < appear_by:
        raise err(E.ERR_NOT_YET_LATE, "appear_by deadline has not passed.")
    if citation["late_penalty_applied"]:
        raise err(E.ERR_PENALTY_ALREADY_APPLIED, "Late penalty already applied.")
    juris = db.jurisdictions[db.drivers[citation["driver_id"]]["jurisdiction_id"]]
    citation["penalty_cents"] += juris["late_penalty_cents"]
    citation["late_penalty_applied"] = True
    recompute_balance(citation)
    open_nonpayment_hold_if_none(citation)
    touch(citation)
    return success(view(citation), 200)


# ===========================================================================
# Routes — CitationCharge
# ===========================================================================
@app.route("/charges", methods=["POST"])
def create_charge():
    _, role = auth()
    require_role(role, {"CourtClerk"})
    data = body()
    require_fields(data, ["citation_id", "violation_code", "description",
                          "base_fine_cents", "points"])
    citation = db.citations.get(data["citation_id"])
    if citation is None:
        raise err(E.ERR_INVALID_REQUEST, "citation_id does not reference a citation.")
    as_str(data["violation_code"], "violation_code")
    as_str(data["description"], "description")
    base = as_nonneg_int(data["base_fine_cents"], "base_fine_cents")
    points = as_nonneg_int(data["points"], "points")
    # PRD §3.3: charges added only while DRAFT
    if citation["financial_status"] != "DRAFT":
        raise err(E.ERR_INVALID_STATE, "Charges may only be added to a DRAFT citation.")
    rec = {
        "citation_id": data["citation_id"],
        "violation_code": data["violation_code"],
        "description": data["description"],
        "base_fine_cents": base,
        "points": points,
    }
    stamp_create(rec)
    db.charges[rec["id"]] = rec
    # PRD §3.3: adding a charge recomputes Citation.base_fine_cents. The PRD's
    # enumerated version bumps (assess, payment, penalty, enrollment, void,
    # collections, plan supersede) do NOT include charge creation, so the
    # citation stays at version 1 in DRAFT until assessment bumps it. Refresh
    # updated_at to reflect the derived-field change without advancing version.
    recompute_base_fine(citation)
    citation["updated_at"] = db.iso_now_ms()
    return success(view(rec), 201)


@app.route("/charges/<chid>", methods=["GET"])
def get_charge(chid):
    _, role = auth()
    require_role(role, ROLES)
    rec = get_or_404(db.charges, chid)
    return success(view(rec), 200)


@app.route("/charges", methods=["GET"])
def list_charges():
    _, role = auth()
    require_role(role, ROLES)
    rows = list(db.charges.values())
    cid = request.args.get("citation_id")
    if cid is not None:
        rows = [r for r in rows if r["citation_id"] == cid]
    page, pg = paginate(rows)
    return success([view(r) for r in page], 200, pagination=pg)


# ===========================================================================
# Routes — Payment
# ===========================================================================
def complete_plan_on_citation_paid(citation):
    """When a citation reaches PAID: any ACTIVE plan -> COMPLETED, remaining
    SCHEDULED installments -> PAID."""
    for plan in db.installment_plans.values():
        if plan["citation_id"] == citation["id"] and plan["status"] == "ACTIVE":
            plan["status"] = "COMPLETED"
            touch(plan)
            for inst in db.installments.values():
                if inst["installment_plan_id"] == plan["id"] and inst["status"] == "SCHEDULED":
                    inst["status"] = "PAID"
                    touch(inst)


def maybe_complete_plan_all_paid(citation):
    """A plan completes when all its installments are PAID."""
    for plan in db.installment_plans.values():
        if plan["citation_id"] == citation["id"] and plan["status"] == "ACTIVE":
            insts = [i for i in db.installments.values()
                     if i["installment_plan_id"] == plan["id"]]
            if insts and all(i["status"] == "PAID" for i in insts):
                plan["status"] = "COMPLETED"
                touch(plan)


@app.route("/citations/<cid>/payments", methods=["POST"])
def create_payment(cid):
    user_id, role = auth()
    require_role(role, {"Driver", "CourtClerk"})
    citation = get_or_404(db.citations, cid)
    require_owner(role, user_id, citation["driver_id"])
    data = body()
    require_fields(data, ["amount_cents", "method"])
    amount = as_int(data["amount_cents"], "amount_cents")
    method = data["method"]
    if method not in PAYMENT_METHODS:
        raise err(E.ERR_INVALID_REQUEST, "Invalid payment method.")
    installment = None
    if data.get("installment_id") is not None:
        installment = db.installments.get(data["installment_id"])
        if installment is None:
            raise err(E.ERR_INVALID_REQUEST, "installment_id does not reference an installment.")
    # state: citation must be OPEN
    if citation["disposition"] != "OPEN":
        raise err(E.ERR_INVALID_STATE, "Citation is not OPEN.")
    # also must be in a payable financial state
    if citation["financial_status"] not in ("ASSESSED", "PARTIALLY_PAID"):
        raise err(E.ERR_INVALID_STATE, "Citation is not in a payable state.")
    # overpayment: 0 < amount <= balance
    if amount <= 0 or amount > citation["balance_cents"]:
        raise err(E.ERR_OVERPAYMENT, "Amount must be > 0 and <= balance.")
    rec = {
        "citation_id": cid,
        "amount_cents": amount,
        "method": method,
        "installment_id": data.get("installment_id"),
        "status": "POSTED",
        "posted_at": db.iso_now_ms(),
    }
    stamp_create(rec)
    db.payments[rec["id"]] = rec
    # mark targeted installment PAID
    if installment is not None and installment["status"] == "SCHEDULED":
        installment["status"] = "PAID"
        touch(installment)
    recompute_balance(citation)
    if citation["balance_cents"] == 0:
        citation["financial_status"] = "PAID"
        citation["disposition"] = "CLOSED"
        # depth-3 cascade
        release_citation_holds(citation)
        quash_citation_warrants(citation)
        complete_plan_on_citation_paid(citation)
        recall_collections(citation)
        reevaluate_point_suspension(citation["driver_id"])
    else:
        citation["financial_status"] = "PARTIALLY_PAID"
        maybe_complete_plan_all_paid(citation)
    touch(citation)
    return success(view(rec), 201)


@app.route("/payments/<pid>", methods=["GET"])
def get_payment(pid):
    _, role = auth()
    require_role(role, ROLES)
    rec = get_or_404(db.payments, pid)
    return success(view(rec), 200)


@app.route("/payments", methods=["GET"])
def list_payments():
    _, role = auth()
    require_role(role, ROLES)
    rows = list(db.payments.values())
    cid = request.args.get("citation_id")
    iid = request.args.get("installment_id")
    if cid is not None:
        rows = [r for r in rows if r["citation_id"] == cid]
    if iid is not None:
        rows = [r for r in rows if r.get("installment_id") == iid]
    page, pg = paginate(rows)
    return success([view(r) for r in page], 200, pagination=pg)


# ===========================================================================
# Routes — Installment plan
# ===========================================================================
@app.route("/citations/<cid>/installment-plans", methods=["POST"])
def create_installment_plan(cid):
    user_id, role = auth()
    require_role(role, {"Driver", "CourtClerk"})
    citation = get_or_404(db.citations, cid)
    require_owner(role, user_id, citation["driver_id"])
    data = body()
    require_fields(data, ["term_count", "first_due_at", "expected_citation_version"])
    term_count = as_int(data["term_count"], "term_count")
    first_due_at = parse_dt(data["first_due_at"], "first_due_at")
    expected_version = as_int(data["expected_citation_version"], "expected_citation_version")
    # OCC check (§2.6): compare expected_citation_version to current version
    if expected_version != citation["version"]:
        raise err(E.ERR_STALE_VERSION, "expected_citation_version is stale.")
    # term_count in [2,12] and computed base >= min_installment_cents
    juris = db.jurisdictions[db.drivers[citation["driver_id"]]["jurisdiction_id"]]
    if term_count < 2 or term_count > 12:
        raise err(E.ERR_INSTALLMENT_TOO_SMALL, "term_count must be in [2,12].")
    principal = citation["balance_cents"] + juris["installment_setup_fee_cents"]
    base = principal // term_count
    if base < juris["min_installment_cents"]:
        raise err(E.ERR_INSTALLMENT_TOO_SMALL, "Per-installment base below minimum.")
    remainder = principal - base * term_count
    # supersede prior ACTIVE plan
    for plan in db.installment_plans.values():
        if plan["citation_id"] == cid and plan["status"] == "ACTIVE":
            plan["status"] = "SUPERSEDED"
            touch(plan)
            for inst in db.installments.values():
                if inst["installment_plan_id"] == plan["id"] and inst["status"] == "SCHEDULED":
                    inst["status"] = "MISSED"
                    touch(inst)
    rec = {
        "citation_id": cid,
        "term_count": term_count,
        "first_due_at": db.iso(first_due_at),
        "principal_cents": principal,
        "installment_cents": base,
        "status": "ACTIVE",
    }
    stamp_create(rec)
    db.installment_plans[rec["id"]] = rec
    for seq in range(1, term_count + 1):
        amount = base + (remainder if seq == term_count else 0)
        due = add_months(first_due_at, seq - 1)
        inst = {
            "installment_plan_id": rec["id"],
            "sequence_no": seq,
            "due_at": db.iso(due),
            "amount_cents": amount,
            "status": "SCHEDULED",
        }
        stamp_create(inst)
        db.installments[inst["id"]] = inst
    # plan creation advances citation version
    touch(citation)
    return success(view(rec), 201)


@app.route("/installment-plans/<pid>", methods=["GET"])
def get_installment_plan(pid):
    _, role = auth()
    require_role(role, ROLES)
    rec = get_or_404(db.installment_plans, pid)
    return success(view(rec), 200)


@app.route("/installment-plans", methods=["GET"])
def list_installment_plans():
    _, role = auth()
    require_role(role, ROLES)
    rows = list(db.installment_plans.values())
    cid = request.args.get("citation_id")
    st = request.args.get("status")
    if cid is not None:
        rows = [r for r in rows if r["citation_id"] == cid]
    if st is not None:
        rows = [r for r in rows if r["status"] == st]
    page, pg = paginate(rows)
    return success([view(r) for r in page], 200, pagination=pg)


@app.route("/installment-plans/<pid>/mark-default", methods=["POST"])
def mark_default(pid):
    _, role = auth()
    require_role(role, {"CourtClerk"})
    plan = get_or_404(db.installment_plans, pid)
    if plan["status"] != "ACTIVE":
        raise err(E.ERR_INVALID_STATE, "Plan is not ACTIVE.")
    now = db.now()
    past_due = [i for i in db.installments.values()
                if i["installment_plan_id"] == pid and i["status"] == "SCHEDULED"
                and now > parse_stored_dt(i["due_at"])]
    if not past_due:
        raise err(E.ERR_NOT_YET_LATE, "No installment is past due.")
    plan["status"] = "DEFAULTED"
    for i in past_due:
        i["status"] = "MISSED"
        touch(i)
    touch(plan)
    citation = db.citations.get(plan["citation_id"])
    if citation is not None:
        open_nonpayment_hold_if_none(citation)
    return success(view(plan), 200)


@app.route("/installment-plans/<pid>/cancel", methods=["POST"])
def cancel_plan(pid):
    user_id, role = auth()
    require_role(role, {"Driver", "CourtClerk"})
    plan = get_or_404(db.installment_plans, pid)
    citation = db.citations.get(plan["citation_id"])
    require_owner(role, user_id, citation["driver_id"] if citation else None)
    if plan["status"] != "ACTIVE":
        raise err(E.ERR_INVALID_STATE, "Plan is not ACTIVE.")
    # no POSTED payment allocated to any of this plan's installments
    plan_inst_ids = {i["id"] for i in db.installments.values()
                     if i["installment_plan_id"] == pid}
    has_payment = any(p["status"] == "POSTED" and p.get("installment_id") in plan_inst_ids
                      for p in db.payments.values())
    if has_payment:
        raise err(E.ERR_HAS_PAYMENTS, "Plan has payments allocated to installments.")
    plan["status"] = "CANCELLED"
    for i in db.installments.values():
        if i["installment_plan_id"] == pid and i["status"] == "SCHEDULED":
            i["status"] = "MISSED"
            touch(i)
    touch(plan)
    return success(view(plan), 200)


@app.route("/installments/<iid>", methods=["GET"])
def get_installment(iid):
    _, role = auth()
    require_role(role, ROLES)
    rec = get_or_404(db.installments, iid)
    return success(view(rec), 200)


@app.route("/installments", methods=["GET"])
def list_installments():
    _, role = auth()
    require_role(role, ROLES)
    rows = list(db.installments.values())
    pid = request.args.get("installment_plan_id")
    if pid is not None:
        rows = [r for r in rows if r["installment_plan_id"] == pid]
    page, pg = paginate(rows)
    return success([view(r) for r in page], 200, pagination=pg)


# ===========================================================================
# Routes — Contest / hearing
# ===========================================================================
@app.route("/citations/<cid>/contest-requests", methods=["POST"])
def create_contest(cid):
    user_id, role = auth()
    require_role(role, {"Driver"})
    citation = get_or_404(db.citations, cid)
    require_owner(role, user_id, citation["driver_id"])
    data = body()
    require_fields(data, ["grounds"])
    as_str(data["grounds"], "grounds")
    if citation["adjudication_status"] in ("CONTESTED", "DISMISSED", "UPHELD"):
        raise err(E.ERR_ALREADY_CONTESTED, "Citation already contested or adjudicated.")
    rec = {
        "citation_id": cid,
        "grounds": data["grounds"],
        "hearing_at": None,
        "continuance_count": 0,
        "status": "REQUESTED",
    }
    stamp_create(rec)
    db.contest_requests[rec["id"]] = rec
    citation["adjudication_status"] = "CONTESTED"
    touch(citation)
    return success(view(rec), 201)


@app.route("/contest-requests/<rid>", methods=["GET"])
def get_contest(rid):
    _, role = auth()
    require_role(role, ROLES)
    rec = get_or_404(db.contest_requests, rid)
    return success(view(rec), 200)


@app.route("/contest-requests", methods=["GET"])
def list_contests():
    _, role = auth()
    require_role(role, ROLES)
    rows = list(db.contest_requests.values())
    cid = request.args.get("citation_id")
    if cid is not None:
        rows = [r for r in rows if r["citation_id"] == cid]
    page, pg = paginate(rows)
    return success([view(r) for r in page], 200, pagination=pg)


@app.route("/contest-requests/<rid>/schedule", methods=["POST"])
def schedule_hearing(rid):
    _, role = auth()
    require_role(role, {"CourtClerk"})
    cr = get_or_404(db.contest_requests, rid)
    if cr["status"] not in ("REQUESTED", "CONTINUANCE"):
        raise err(E.ERR_INVALID_STATE, "Contest is not in a schedulable state.")
    data = body()
    require_fields(data, ["hearing_at"])
    hearing_at = parse_dt(data["hearing_at"], "hearing_at")
    if hearing_at <= db.now():
        raise err(E.ERR_INVALID_HEARING_DATE, "hearing_at must be in the future.")
    cr["hearing_at"] = db.iso(hearing_at)
    cr["status"] = "HEARING_SET"
    touch(cr)
    return success(view(cr), 200)


@app.route("/contest-requests/<rid>/continue", methods=["POST"])
def continue_hearing(rid):
    _, role = auth()
    require_role(role, {"HearingOfficer"})
    cr = get_or_404(db.contest_requests, rid)
    if cr["status"] != "HEARING_SET":
        raise err(E.ERR_INVALID_STATE, "Contest is not in HEARING_SET.")
    if cr["continuance_count"] >= 2:
        raise err(E.ERR_CONTINUANCE_LIMIT, "Continuance limit reached.")
    cr["continuance_count"] += 1
    cr["status"] = "CONTINUANCE"
    cr["hearing_at"] = None
    touch(cr)
    return success(view(cr), 200)


@app.route("/contest-requests/<rid>/decide", methods=["POST"])
def decide_contest(rid):
    _, role = auth()
    require_role(role, {"HearingOfficer"})
    cr = get_or_404(db.contest_requests, rid)
    if cr["status"] != "HEARING_SET":
        raise err(E.ERR_INVALID_STATE, "Contest is not in HEARING_SET.")
    data = body()
    require_fields(data, ["verdict"])
    verdict = data["verdict"]
    if verdict not in VERDICTS:
        raise err(E.ERR_INVALID_REQUEST, "Invalid verdict.")
    citation = db.citations.get(cr["citation_id"])
    if verdict == "DISMISS":
        cr["status"] = "DISMISSED"
        touch(cr)
        citation["adjudication_status"] = "DISMISSED"
        citation["disposition"] = "CLOSED"
        # charges vacated -> balance 0; financial_status untouched unless PAID
        citation["balance_cents"] = 0
        release_citation_holds(citation)
        quash_citation_warrants(citation)
        recall_collections(citation)
        touch(citation)
    else:  # UPHOLD
        cr["status"] = "UPHELD"
        touch(cr)
        citation["adjudication_status"] = "UPHELD"
        # post one PointLedgerEntry per charge with points > 0
        for charge in [c for c in db.charges.values() if c["citation_id"] == citation["id"]]:
            if charge["points"] > 0:
                entry = {
                    "driver_id": citation["driver_id"],
                    "citation_id": citation["id"],
                    "points": charge["points"],
                    "effective_at": citation["issued_at"],
                    "state": "ACTIVE",
                }
                # PointLedgerEntry: only id + created_at (no version/updated_at)
                stamp_create(entry, versioned=False)
                db.point_ledger[entry["id"]] = entry
        reevaluate_point_suspension(citation["driver_id"])
        touch(citation)
    return success(view(cr), 200)


@app.route("/contest-requests/<rid>/fail-to-appear", methods=["POST"])
def fail_to_appear(rid):
    _, role = auth()
    require_role(role, {"CourtClerk"})
    cr = get_or_404(db.contest_requests, rid)
    if cr["status"] != "HEARING_SET":
        raise err(E.ERR_INVALID_STATE, "Contest is not in HEARING_SET.")
    hearing_at = cr.get("hearing_at")
    if hearing_at is None or db.now() <= parse_stored_dt(hearing_at):
        raise err(E.ERR_NOT_YET_LATE, "hearing_at has not passed.")
    cr["status"] = "FTA"
    touch(cr)
    citation = db.citations.get(cr["citation_id"])
    # citation.adjudication_status stays CONTESTED
    # create ACTIVE warrant -> open FTA_HOLD
    warrant = {
        "citation_id": citation["id"],
        "driver_id": citation["driver_id"],
        "reason": "FTA_HEARING",
        "status": "ACTIVE",
        "quashed_at": None,
    }
    stamp_create(warrant)
    db.warrants[warrant["id"]] = warrant
    open_hold(citation["driver_id"], citation["id"], "FTA_HOLD")
    return success(view(cr), 200)


# ===========================================================================
# Routes — Traffic school
# ===========================================================================
@app.route("/citations/<cid>/enrollments", methods=["POST"])
def create_enrollment(cid):
    user_id, role = auth()
    require_role(role, {"Driver", "CourtClerk"})
    citation = get_or_404(db.citations, cid)
    require_owner(role, user_id, citation["driver_id"])
    data = body()
    require_fields(data, ["completion_due_at"])
    completion_due_at = parse_dt(data["completion_due_at"], "completion_due_at")
    juris = db.jurisdictions[db.drivers[citation["driver_id"]]["jurisdiction_id"]]
    # eligibility (ERR_SCHOOL_INELIGIBLE)
    charge_points = sum(c["points"] for c in db.charges.values()
                        if c["citation_id"] == cid)
    if charge_points > juris["school_eligible_max_points"]:
        raise err(E.ERR_SCHOOL_INELIGIBLE, "Citation points exceed school cap.")
    if citation["financial_status"] == "VOID":
        raise err(E.ERR_SCHOOL_INELIGIBLE, "Citation is VOID.")
    if citation["adjudication_status"] in ("CONTESTED", "DISMISSED"):
        raise err(E.ERR_SCHOOL_INELIGIBLE, "Citation is contested or dismissed.")
    # cooldown: no prior COMPLETED enrollment within school_cooldown_months
    cooldown_start = add_months(db.now(), -juris["school_cooldown_months"])
    for e in db.enrollments.values():
        if e["driver_id"] == citation["driver_id"] and e["status"] == "COMPLETED":
            completed_at = parse_stored_dt(e.get("_completed_at") or e["created_at"])
            if completed_at >= cooldown_start:
                raise err(E.ERR_SCHOOL_INELIGIBLE, "Cooldown not elapsed.")
    rec = {
        "citation_id": cid,
        "driver_id": citation["driver_id"],
        "eligible_points": charge_points,
        "completion_due_at": db.iso(completion_due_at),
        "points_reduced": 0,
        "status": "ENROLLED",
    }
    stamp_create(rec)
    db.enrollments[rec["id"]] = rec
    citation["penalty_cents"] += juris["traffic_school_fee_cents"]
    recompute_balance(citation)
    touch(citation)
    return success(view(rec), 201)


@app.route("/enrollments/<eid>", methods=["GET"])
def get_enrollment(eid):
    _, role = auth()
    require_role(role, ROLES)
    rec = get_or_404(db.enrollments, eid)
    return success(view(rec), 200)


@app.route("/enrollments", methods=["GET"])
def list_enrollments():
    _, role = auth()
    require_role(role, ROLES)
    rows = list(db.enrollments.values())
    cid = request.args.get("citation_id")
    did = request.args.get("driver_id")
    if cid is not None:
        rows = [r for r in rows if r["citation_id"] == cid]
    if did is not None:
        rows = [r for r in rows if r["driver_id"] == did]
    page, pg = paginate(rows)
    return success([view(r) for r in page], 200, pagination=pg)


@app.route("/enrollments/<eid>/complete", methods=["POST"])
def complete_enrollment(eid):
    _, role = auth()
    require_role(role, {"CourtClerk"})
    enr = get_or_404(db.enrollments, eid)
    if enr["status"] != "ENROLLED":
        raise err(E.ERR_INVALID_STATE, "Enrollment is not ENROLLED.")
    citation = db.citations.get(enr["citation_id"])
    # deadline check (ERR_SCHOOL_DEADLINE_PASSED) then fine-paid (ERR_FINE_UNPAID)
    if db.now() > parse_stored_dt(enr["completion_due_at"]):
        raise err(E.ERR_SCHOOL_DEADLINE_PASSED, "Completion deadline passed.")
    if citation["financial_status"] != "PAID":
        raise err(E.ERR_FINE_UNPAID, "Fine must be fully PAID first.")
    # calc point_reduction
    active_entries = [e for e in db.point_ledger.values()
                      if e["citation_id"] == enr["citation_id"] and e["state"] == "ACTIVE"]
    candidate = sum(e["points"] for e in active_entries)
    points_reduced = min(enr["eligible_points"], candidate)
    # mask points_reduced worth of this citation's ACTIVE entries
    remaining = points_reduced
    for e in sorted(active_entries, key=lambda x: x["_seq"]):
        if remaining <= 0:
            break
        if e["points"] <= remaining:
            e["state"] = "MASKED"
            remaining -= e["points"]
    enr["points_reduced"] = points_reduced
    enr["status"] = "COMPLETED"
    enr["_completed_at"] = db.iso_now_ms()
    touch(enr)
    # re-evaluate point suspension (may make a POINT_SUSPENSION hold releasable;
    # release itself remains an explicit DMV action per PRD §3.8)
    reevaluate_point_suspension(citation["driver_id"])
    return success(view(enr), 200)


@app.route("/enrollments/<eid>/fail", methods=["POST"])
def fail_enrollment(eid):
    _, role = auth()
    require_role(role, {"CourtClerk"})
    enr = get_or_404(db.enrollments, eid)
    if enr["status"] != "ENROLLED":
        raise err(E.ERR_INVALID_STATE, "Enrollment is not ENROLLED.")
    if db.now() <= parse_stored_dt(enr["completion_due_at"]):
        raise err(E.ERR_NOT_YET_LATE, "Completion deadline has not passed.")
    enr["status"] = "FAILED"
    touch(enr)
    return success(view(enr), 200)


# ===========================================================================
# Routes — Collections
# ===========================================================================
@app.route("/citations/<cid>/collections-referrals", methods=["POST"])
def create_collections_referral(cid):
    _, role = auth()
    require_role(role, {"CourtClerk"})
    citation = get_or_404(db.citations, cid)
    # already referred guard
    if citation["collections_referred"]:
        raise err(E.ERR_PENALTY_ALREADY_APPLIED, "Collections fee already applied.")
    juris = db.jurisdictions[db.drivers[citation["driver_id"]]["jurisdiction_id"]]
    appear_by = parse_stored_dt(citation["appear_by"])
    age_days = int((db.now() - appear_by).total_seconds() // 86400)
    eligible = (age_days >= juris["collections_age_days"]
                and citation["disposition"] == "OPEN"
                and citation["balance_cents"] > 0)
    if not eligible:
        raise err(E.ERR_NOT_YET_LATE, "Citation not yet eligible for collections.")
    outstanding = citation["balance_cents"]
    fee = round_half_up(Decimal(outstanding) * Decimal(str(juris["collections_fee_pct"])))
    rec = {
        "citation_id": cid,
        "outstanding_at_referral_cents": outstanding,
        "collections_fee_cents": fee,
        "status": "REFERRED",
    }
    stamp_create(rec)
    db.collections_referrals[rec["id"]] = rec
    citation["penalty_cents"] += fee
    citation["collections_referred"] = True
    recompute_balance(citation)
    touch(citation)
    return success(view(rec), 201)


@app.route("/collections-referrals/<crid>", methods=["GET"])
def get_collections_referral(crid):
    _, role = auth()
    require_role(role, ROLES)
    rec = get_or_404(db.collections_referrals, crid)
    return success(view(rec), 200)


@app.route("/collections-referrals", methods=["GET"])
def list_collections_referrals():
    _, role = auth()
    require_role(role, ROLES)
    rows = list(db.collections_referrals.values())
    cid = request.args.get("citation_id")
    if cid is not None:
        rows = [r for r in rows if r["citation_id"] == cid]
    page, pg = paginate(rows)
    return success([view(r) for r in page], 200, pagination=pg)


# ===========================================================================
# Routes — License holds (DMV)
# ===========================================================================
@app.route("/license-holds/<hid>", methods=["GET"])
def get_license_hold(hid):
    _, role = auth()
    require_role(role, ROLES)
    rec = get_or_404(db.license_holds, hid)
    return success(view(rec), 200)


@app.route("/license-holds", methods=["GET"])
def list_license_holds():
    _, role = auth()
    require_role(role, ROLES)
    rows = list(db.license_holds.values())
    did = request.args.get("driver_id")
    cid = request.args.get("citation_id")
    st = request.args.get("status")
    if did is not None:
        rows = [r for r in rows if r["driver_id"] == did]
    if cid is not None:
        rows = [r for r in rows if r.get("citation_id") == cid]
    if st is not None:
        rows = [r for r in rows if r["status"] == st]
    page, pg = paginate(rows)
    return success([view(r) for r in page], 200, pagination=pg)


@app.route("/license-holds/<hid>/release", methods=["POST"])
def release_hold(hid):
    _, role = auth()
    require_role(role, {"DmvAdmin"})
    hold = get_or_404(db.license_holds, hid)
    if hold["status"] != "OPEN":
        raise err(E.ERR_INVALID_STATE, "Hold is not OPEN.")
    if hold["hold_type"] in ("NONPAYMENT_HOLD", "FTA_HOLD"):
        citation = db.citations.get(hold["citation_id"])
        if citation is None or citation["disposition"] != "CLOSED":
            raise err(E.ERR_HOLD_CONDITION_UNMET, "Linked citation is not CLOSED.")
    else:  # POINT_SUSPENSION
        driver = db.drivers.get(hold["driver_id"])
        juris = db.jurisdictions[driver["jurisdiction_id"]]
        if compute_point_balance(hold["driver_id"]) >= juris["point_suspension_threshold"]:
            raise err(E.ERR_HOLD_CONDITION_UNMET, "point_balance still at/above threshold.")
    hold["status"] = "RELEASED"
    hold["released_at"] = db.iso_now_ms()
    touch(hold)
    return success(view(hold), 200)


# ===========================================================================
# Routes — Warrants
# ===========================================================================
@app.route("/warrants/<wid>", methods=["GET"])
def get_warrant(wid):
    _, role = auth()
    require_role(role, ROLES)
    rec = get_or_404(db.warrants, wid)
    return success(view(rec), 200)


@app.route("/warrants", methods=["GET"])
def list_warrants():
    _, role = auth()
    require_role(role, ROLES)
    rows = list(db.warrants.values())
    cid = request.args.get("citation_id")
    did = request.args.get("driver_id")
    st = request.args.get("status")
    if cid is not None:
        rows = [r for r in rows if r["citation_id"] == cid]
    if did is not None:
        rows = [r for r in rows if r["driver_id"] == did]
    if st is not None:
        rows = [r for r in rows if r["status"] == st]
    page, pg = paginate(rows)
    return success([view(r) for r in page], 200, pagination=pg)


@app.route("/warrants/<wid>/quash", methods=["POST"])
def quash_warrant(wid):
    _, role = auth()
    require_role(role, {"CourtClerk"})
    warrant = get_or_404(db.warrants, wid)
    if warrant["status"] != "ACTIVE":
        raise err(E.ERR_INVALID_STATE, "Warrant is not ACTIVE.")
    citation = db.citations.get(warrant["citation_id"])
    # condition: citation CLOSED OR contest has a fresh future hearing_at
    closed = citation is not None and citation["disposition"] == "CLOSED"
    future_hearing = False
    if not closed:
        for cr in db.contest_requests.values():
            if cr["citation_id"] == warrant["citation_id"]:
                ha = cr.get("hearing_at")
                if cr["status"] == "HEARING_SET" and ha is not None \
                        and parse_stored_dt(ha) > db.now():
                    future_hearing = True
                    break
    if not (closed or future_hearing):
        raise err(E.ERR_HOLD_CONDITION_UNMET, "Warrant quash condition unmet.")
    warrant["status"] = "QUASHED"
    warrant["quashed_at"] = db.iso_now_ms()
    touch(warrant)
    return success(view(warrant), 200)


# ===========================================================================
# Routes — Point ledger (DMV)
# ===========================================================================
@app.route("/point-ledger/<pleid>", methods=["GET"])
def get_point_entry(pleid):
    _, role = auth()
    require_role(role, ROLES)
    rec = get_or_404(db.point_ledger, pleid)
    return success(view(rec), 200)


@app.route("/point-ledger", methods=["GET"])
def list_point_ledger():
    _, role = auth()
    require_role(role, ROLES)
    rows = list(db.point_ledger.values())
    did = request.args.get("driver_id")
    cid = request.args.get("citation_id")
    st = request.args.get("state")
    if did is not None:
        rows = [r for r in rows if r["driver_id"] == did]
    if cid is not None:
        rows = [r for r in rows if r["citation_id"] == cid]
    if st is not None:
        rows = [r for r in rows if r["state"] == st]
    page, pg = paginate(rows)
    return success([view(r) for r in page], 200, pagination=pg)


# ===========================================================================
# Entry point
# ===========================================================================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
