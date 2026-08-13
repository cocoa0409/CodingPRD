"""Rate sets (PRD §3.5): authoring, break-even review, rate cap, approval,
activation/supersession."""

from decimal import Decimal

from flask import Blueprint, request

from auth import authenticate, require_roles, auth_id
from errors import fail
from helpers import (
    Body, validate_body, is_int, is_num, dt_ok, parse_dt,
    effective_rate_set_for_fy, rate_line_for, break_even_verdict,
    projected_cost_cents, projected_revenue_cents, suggested_internal_rate,
    ser_rate_set, MAX_RATE_INCREASE_PCT,
)
from store import store, now
from util import new_entity, ok_object, parse_pagination, paginate, sort_default, touch, fmt_ts

bp = Blueprint("ratesets", __name__)

LINE_KEYS = {"instrument_id", "internal_rate_cents_per_hour", "external_rate_cents_per_hour",
             "billing_increment_minutes", "min_charge_minutes", "projected_billable_hours",
             "break_even_waiver_reason"}
LINE_REQUIRED = {"instrument_id", "internal_rate_cents_per_hour", "external_rate_cents_per_hour",
                 "billing_increment_minutes", "min_charge_minutes", "projected_billable_hours"}


def get_rate_set_or_404(rid):
    rs = store.rate_sets.get(rid)
    if rs is None:
        fail("ERR_NOT_FOUND", "Rate set not found")
    return rs


def _fy_period(fy):
    for p in store.fiscal_years.values():
        if p["fiscal_year"] == fy:
            return p
    return None


def _validate_lines_shape(lines):
    """Priority-21 structural validation of the lines array."""
    if not isinstance(lines, list):
        fail("ERR_INVALID_REQUEST", "lines must be an array")
    for line in lines:
        if not isinstance(line, dict):
            fail("ERR_INVALID_REQUEST", "each rate line must be an object")
        for k in line:
            if k not in LINE_KEYS:
                fail("ERR_INVALID_REQUEST", "Unknown field in rate line: %s" % k)
        for k in LINE_REQUIRED:
            if k not in line or line[k] is None:
                fail("ERR_INVALID_REQUEST", "Rate line missing required field: %s" % k)
        if not isinstance(line["instrument_id"], str):
            fail("ERR_INVALID_REQUEST", "line instrument_id must be a string")
        if not (is_int(line["internal_rate_cents_per_hour"]) and line["internal_rate_cents_per_hour"] > 0):
            fail("ERR_INVALID_REQUEST", "internal_rate_cents_per_hour must be a positive integer")
        if not (is_int(line["external_rate_cents_per_hour"]) and line["external_rate_cents_per_hour"] >= 0):
            fail("ERR_INVALID_REQUEST", "external_rate_cents_per_hour must be a non-negative integer")
        if not (is_int(line["billing_increment_minutes"]) and line["billing_increment_minutes"] > 0):
            fail("ERR_INVALID_REQUEST", "billing_increment_minutes must be a positive integer")
        if not (is_int(line["min_charge_minutes"]) and line["min_charge_minutes"] >= 0):
            fail("ERR_INVALID_REQUEST", "min_charge_minutes must be a non-negative integer")
        if not (is_num(line["projected_billable_hours"]) and line["projected_billable_hours"] > 0):
            fail("ERR_INVALID_REQUEST", "projected_billable_hours must be a positive number")
        if "break_even_waiver_reason" in line and line["break_even_waiver_reason"] is not None:
            if not isinstance(line["break_even_waiver_reason"], str):
                fail("ERR_INVALID_REQUEST", "break_even_waiver_reason must be a string or null")


def _check_lines_existence(lines):
    """Priority-4 FK existence for line instrument ids."""
    if isinstance(lines, list):
        for line in lines:
            if isinstance(line, dict):
                iid = line.get("instrument_id")
                if iid is not None and iid not in store.instruments:
                    fail("ERR_NOT_FOUND", "line instrument_id does not reference an existing instrument")


def _check_lines_unique(lines):
    seen = set()
    for line in lines:
        iid = line["instrument_id"]
        if iid in seen:
            fail("ERR_UNIQUE_CONSTRAINT", "Rate-set lines must be unique per instrument")
        seen.add(iid)


def _check_rate_order(lines):
    for line in lines:
        if line["external_rate_cents_per_hour"] < line["internal_rate_cents_per_hour"]:
            fail("ERR_RATE_ORDER_INVALID", "external rate must be >= internal rate on every line")


def _normalize_lines(lines):
    out = []
    for line in lines:
        out.append({
            "instrument_id": line["instrument_id"],
            "internal_rate_cents_per_hour": line["internal_rate_cents_per_hour"],
            "external_rate_cents_per_hour": line["external_rate_cents_per_hour"],
            "billing_increment_minutes": line["billing_increment_minutes"],
            "min_charge_minutes": line["min_charge_minutes"],
            "projected_billable_hours": line["projected_billable_hours"],
            "break_even_waiver_reason": line.get("break_even_waiver_reason"),
        })
    return out


@bp.route("/rate-sets", methods=["POST"])
def create_rate_set():
    authenticate()
    require_roles("FacilityAdmin")
    body = Body(request.get_json(silent=True))
    # Priority 4 — line instrument FK existence
    if isinstance(body.raw, dict) and isinstance(body.raw.get("lines"), list):
        _check_lines_existence(body.raw["lines"])
    # Priority 21 — formats
    validate_body(
        body,
        allowed={"fiscal_year", "effective_from", "lines"},
        required={"fiscal_year", "effective_from", "lines"},
        checkers={
            "fiscal_year": is_int,
            "effective_from": dt_ok,
        },
    )
    _validate_lines_shape(body.get("lines"))
    # Priority 22 — instrument unique within the set
    _check_lines_unique(body.get("lines"))
    # Priority 26 — rate ordering
    _check_rate_order(body.get("lines"))
    rs = new_entity({
        "fiscal_year": body.get("fiscal_year"),
        "effective_from": fmt_ts(parse_dt(body.get("effective_from"))),
        "lines": _normalize_lines(body.get("lines")),
        "status": "DRAFT",
        "supersedes_rate_set_id": None,
        "developed_by": auth_id(),
        "approved_by": None,
        "_verdicts": None,  # internal: per-line PASS/DEFICIT/WAIVED once submitted
        "_line_flags": [False] * len(body.get("lines")),
        "_effective_from": parse_dt(body.get("effective_from")),
    })
    store.rate_sets[rs["id"]] = rs
    return ok_object(ser_rate_set(rs), status=201)


@bp.route("/rate-sets", methods=["GET"])
def list_rate_sets():
    authenticate()
    require_roles("FacilityAdmin", "FinanceOfficer")
    limit, offset = parse_pagination(request.args)
    items = list(store.rate_sets.values())
    fy = request.args.get("fiscal_year")
    if fy is not None:
        try:
            fy_int = int(fy)
            items = [r for r in items if r["fiscal_year"] == fy_int]
        except (TypeError, ValueError):
            items = []
    status = request.args.get("status")
    if status is not None:
        items = [r for r in items if r["status"] == status]
    sup = request.args.get("supersedes_rate_set_id")
    if sup is not None:
        items = [r for r in items if r.get("supersedes_rate_set_id") == sup]
    return paginate(sort_default(items), limit, offset, ser_rate_set)


@bp.route("/rate-sets/<rid>", methods=["GET"])
def get_rate_set(rid):
    authenticate()
    require_roles("FacilityAdmin", "FinanceOfficer")
    return ok_object(ser_rate_set(get_rate_set_or_404(rid)))


@bp.route("/rate-sets/<rid>", methods=["PUT"])
def edit_rate_set(rid):
    authenticate()
    require_roles("FacilityAdmin")
    rs = get_rate_set_or_404(rid)
    body = Body(request.get_json(silent=True))
    # Priority 5 — OCC
    expected = body.get("expected_rate_set_version")
    if expected is not None and is_int(expected) and expected != rs["version"]:
        fail("ERR_STALE_VERSION", "expected_rate_set_version does not match the set's current version")
    # Priority 6 — only DRAFT is editable
    if rs["status"] != "DRAFT":
        fail("ERR_INVALID_STATE", "Only a DRAFT rate set can be edited")
    # Priority 4 — new line instrument FK existence
    if isinstance(body.raw, dict) and isinstance(body.raw.get("lines"), list):
        _check_lines_existence(body.raw["lines"])
    # Priority 21 — formats
    validate_body(
        body,
        allowed={"expected_rate_set_version", "effective_from", "lines"},
        required={"expected_rate_set_version"},
        checkers={
            "expected_rate_set_version": is_int,
            "effective_from": dt_ok,
        },
    )
    if body.has("lines"):
        _validate_lines_shape(body.get("lines"))
        _check_lines_unique(body.get("lines"))
        _check_rate_order(body.get("lines"))
    if body.has("effective_from"):
        rs["effective_from"] = fmt_ts(parse_dt(body.get("effective_from")))
        rs["_effective_from"] = parse_dt(body.get("effective_from"))
    if body.has("lines"):
        rs["lines"] = _normalize_lines(body.get("lines"))
        rs["_line_flags"] = [False] * len(rs["lines"])
        rs["_verdicts"] = None
    touch(rs)
    return ok_object(ser_rate_set(rs))


@bp.route("/rate-sets/<rid>/submit", methods=["POST"])
def submit_rate_set(rid):
    authenticate()
    require_roles("FacilityAdmin")
    rs = get_rate_set_or_404(rid)
    body = Body(request.get_json(silent=True))
    if body.raw is None:
        body.raw = {}
    for k in body.raw:
        if k not in ("override_justification",):
            fail("ERR_INVALID_REQUEST", "Unknown field in request body: %s" % k)
    # Priority 6 — state legality
    if rs["status"] != "DRAFT":
        fail("ERR_INVALID_STATE", "Only a DRAFT rate set can be submitted")
    # Submit preconditions: non-empty lines; instruments exist and not RETIRED
    if not rs["lines"]:
        fail("ERR_INVALID_REQUEST", "Cannot submit a rate set with no lines")
    for line in rs["lines"]:
        inst = store.instruments.get(line["instrument_id"])
        if inst is None:
            fail("ERR_NOT_FOUND", "line instrument_id does not reference an existing instrument")
        if inst["status"] == "RETIRED":
            fail("ERR_INVALID_REQUEST", "Cannot submit a set containing a RETIRED instrument")
    # Priority 26 — rate ordering re-checked
    _check_rate_order(rs["lines"])
    # Priority 36 — year-over-year rate cap vs the preceding FY's EFFECTIVE set
    override = body.get("override_justification")
    has_override = isinstance(override, str) and len(override.strip()) > 0
    prior_set = effective_rate_set_for_fy(rs["fiscal_year"] - 1)
    if prior_set is not None and not has_override:
        for line in rs["lines"]:
            prior_line = rate_line_for(prior_set, line["instrument_id"])
            if prior_line is None:
                continue
            cap = Decimal(int(prior_line["internal_rate_cents_per_hour"])) * (Decimal(1) + MAX_RATE_INCREASE_PCT)
            if Decimal(int(line["internal_rate_cents_per_hour"])) > cap:
                fail("ERR_RATE_CAP_EXCEEDED",
                     "Internal rate exceeds 110%% of the prior fiscal year's effective rate")
    # Side effect: projected break-even review per line
    rs["_verdicts"] = [break_even_verdict(line, rs["fiscal_year"])[0] for line in rs["lines"]]
    rs["status"] = "UNDER_REVIEW"
    touch(rs)
    return ok_object(ser_rate_set(rs))


@bp.route("/rate-sets/<rid>/approve", methods=["POST"])
def approve_rate_set(rid):
    authenticate()
    require_roles("FinanceOfficer")
    rs = get_rate_set_or_404(rid)
    # Priority 3 — segregation of duties: approver != developer
    if auth_id() == rs.get("developed_by"):
        fail("ERR_SEGREGATION_OF_DUTIES", "The rate-set developer cannot approve their own set")
    # Priority 6 — state legality
    if rs["status"] != "UNDER_REVIEW":
        fail("ERR_INVALID_STATE", "Only an UNDER_REVIEW rate set can be approved")
    # Priority 8 — fiscal year must exist and be OPEN
    period = _fy_period(rs["fiscal_year"])
    if period is None or period["status"] != "OPEN":
        fail("ERR_FY_CLOSED", "Fiscal year period is missing or CLOSED")
    # Priority 37 — every DEFICIT line needs a waiver
    verdicts = rs.get("_verdicts") or [break_even_verdict(l, rs["fiscal_year"])[0] for l in rs["lines"]]
    for i, line in enumerate(rs["lines"]):
        if verdicts[i] == "DEFICIT" and not line.get("break_even_waiver_reason"):
            fail("ERR_BREAK_EVEN_WAIVER_REQUIRED", "DEFICIT lines require a break_even_waiver_reason")
    # Record waived lines
    rs["_verdicts"] = ["WAIVED" if (v == "DEFICIT" and rs["lines"][i].get("break_even_waiver_reason")) else v
                      for i, v in enumerate(verdicts)]
    rs["approved_by"] = auth_id()
    rs["status"] = "APPROVED"
    touch(rs)
    return ok_object(ser_rate_set(rs))


@bp.route("/rate-sets/<rid>/reject", methods=["POST"])
def reject_rate_set(rid):
    authenticate()
    require_roles("FinanceOfficer")
    rs = get_rate_set_or_404(rid)
    body = Body(request.get_json(silent=True))
    if body.raw is None:
        body.raw = {}
    for k in body.raw:
        if k not in ("reason",):
            fail("ERR_INVALID_REQUEST", "Unknown field in request body: %s" % k)
    if rs["status"] != "UNDER_REVIEW":
        fail("ERR_INVALID_STATE", "Only an UNDER_REVIEW rate set can be rejected")
    rs["status"] = "DRAFT"
    touch(rs)
    return ok_object(ser_rate_set(rs))


@bp.route("/rate-sets/<rid>/activate", methods=["POST"])
def activate_rate_set(rid):
    authenticate()
    require_roles("FinanceOfficer")
    rs = get_rate_set_or_404(rid)
    body = Body(request.get_json(silent=True))
    if body.raw is None:
        body.raw = {}
    for k in body.raw:
        fail("ERR_INVALID_REQUEST", "Unknown field in request body: %s" % k)
    # Priority 6 — state legality + activation gate
    if rs["status"] != "APPROVED":
        fail("ERR_INVALID_STATE", "Only an APPROVED rate set can be activated")
    if rs.get("_effective_from") is not None and now() < rs["_effective_from"]:
        fail("ERR_INVALID_STATE", "Current logical time is before effective_from")
    # Priority 8 — fiscal year still OPEN
    period = _fy_period(rs["fiscal_year"])
    if period is None or period["status"] != "OPEN":
        fail("ERR_FY_CLOSED", "Fiscal year period is missing or CLOSED")
    # Supersede the incumbent EFFECTIVE set of the same fiscal year
    incumbent = None
    for other in store.rate_sets.values():
        if other["id"] != rid and other["fiscal_year"] == rs["fiscal_year"] and other["status"] == "EFFECTIVE":
            incumbent = other
            break
    if incumbent is not None:
        incumbent["status"] = "SUPERSEDED"
        touch(incumbent)
    rs["supersedes_rate_set_id"] = incumbent["id"] if incumbent is not None else None
    rs["status"] = "EFFECTIVE"
    touch(rs)
    return ok_object(ser_rate_set(rs))


@bp.route("/rate-sets/<rid>/break-even", methods=["GET"])
def break_even(rid):
    authenticate()
    require_roles("FacilityAdmin", "FinanceOfficer")
    rs = get_rate_set_or_404(rid)
    period = _fy_period(rs["fiscal_year"])
    carryforward = period["carryforward_in_cents"] if period is not None else 0
    lines_out = []
    all_ok = True
    for i, line in enumerate(rs["lines"]):
        verdict, revenue, cost = break_even_verdict(line, rs["fiscal_year"])
        stored = rs.get("_verdicts")
        if stored is not None and i < len(stored) and stored[i] is not None:
            verdict = stored[i]
        if verdict == "DEFICIT":
            all_ok = False
        flags = rs.get("_line_flags") or []
        elem = dict(line)
        elem["break_even_verdict"] = verdict
        elem["flagged_for_review"] = bool(flags[i]) if i < len(flags) else False
        elem["projected_revenue_cents"] = revenue
        elem["projected_cost_cents"] = cost
        elem["suggested_internal_rate_cents_per_hour"] = suggested_internal_rate(
            line["instrument_id"], rs["fiscal_year"], carryforward, line["projected_billable_hours"])
        lines_out.append(elem)
    data = {
        "fiscal_year": rs["fiscal_year"],
        "overall_verdict": "PASS" if all_ok else "DEFICIT",
        "lines": lines_out,
    }
    return ok_object(data)
