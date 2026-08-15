"""All API endpoints (§1.5), mounted under /surveillance."""
import re
from datetime import timedelta

from flask import Blueprint, request

from core import (db, now, set_clock, fail, ok, paginate, sorted_rows,
                  identity, require_any_role, require_roles, require_transition_roles,
                  get_body, req_str, req_int, req_num, req_enum, req_dt_field,
                  opt_dt_field, parse_dt, new_resource, bump, get_or_404, fmt_dt)
import services as S

bp = Blueprint("surveillance", __name__, url_prefix="/surveillance")

DEPARTMENTS = {"TRADING", "OPERATIONS", "COMPLIANCE", "EXECUTIVE"}
VENUE_TYPES = {"EXCHANGE", "ATS", "MARKET_MAKER"}
SIDES = {"BUY", "SELL"}
ORDER_TYPES = {"MARKET", "LIMIT", "MARKET_ON_CLOSE"}
VARIANTS_EQ = {"FAR_TOUCH", "MIDPOINT"}
PRICING_VARIANTS = {"MARGINAL", "RETROACTIVE"}
DETERMINATIONS = {"CONTINUE", "MODIFY", "TERMINATE_ROUTING"}
DISPOSITIONS = {"VIOLATION_CONFIRMED", "UNFOUNDED"}
RESTRICTION_KINDS = {"ALL", "EMPLOYEE_ONLY", "CLIENT_ONLY"}
CHANNELS = {"EMAIL", "CHAT"}

MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
QUARTER_RE = re.compile(r"^\d{4}-Q[1-4]$")


def list_response(rows, serializer):
    rows = sorted_rows(rows)
    page_items, page = paginate(rows)
    return ok([serializer(r) for r in page_items], rtype="array", page=page)


def filter_param(rows, name, value):
    if value is None:
        return rows
    return [r for r in rows if r.get(name) == value]


# ==================================================================
# Ops / test-driving
# ==================================================================
@bp.post("/_clock/set_current_utc")
def set_current_utc():
    require_roles("OpsAdmin")
    body = get_body()
    to = req_dt_field(body, "to_iso8601")
    if to < now():
        fail("ERR_CLOCK_REGRESSION", 409, "to_iso8601 must be >= current clock value")
    set_clock(to)
    return ok({"current_utc": fmt_dt(now())})


@bp.post("/ops/runs")
def ops_runs():
    require_roles("OpsAdmin")
    return ok(S.run_ops_sweeps())


# ==================================================================
# Employees
# ==================================================================
def initial_attestation_status(due):
    n = now()
    if n >= due:
        return "LAPSED"
    if n >= due - timedelta(days=30):
        return "DUE"
    return "CURRENT"


@bp.post("/employees")
def create_employee():
    require_roles("ComplianceAdmin")
    body = get_body()
    full_name = req_str(body, "full_name")
    employee_ref = req_str(body, "employee_ref")
    department = req_enum(body, "department", DEPARTMENTS)
    due = req_dt_field(body, "attestation_due_at")
    if any(e["employee_ref"] == employee_ref for e in db["employees"].values()):
        fail("ERR_DUPLICATE_EMPLOYEE_REF", 409, "employee_ref already in use")
    e = new_resource()
    e.update({"full_name": full_name, "employee_ref": employee_ref, "department": department,
              "employment_status": "ACTIVE",
              "attestation_status": initial_attestation_status(due),
              "attestation_due_at": due, "last_attested_at": None})
    db["employees"][e["id"]] = e
    return ok(S.ser_employee(e), status=201)


@bp.get("/employees/<rid>")
def get_employee(rid):
    require_any_role()
    return ok(S.ser_employee(get_or_404("employees", rid)))


@bp.post("/employees/<rid>/employment-transition")
def employment_transition(rid):
    uid, body = require_transition_roles(
        {"ON_LEAVE": {"ComplianceAdmin"}, "ACTIVE": {"ComplianceAdmin"},
         "TERMINATED": {"ComplianceAdmin"}})
    emp = get_or_404("employees", rid)
    to = req_enum(body, "to_status", {"ON_LEAVE", "ACTIVE", "TERMINATED"})
    allowed_from = {"ON_LEAVE": {"ACTIVE"}, "ACTIVE": {"ON_LEAVE"},
                    "TERMINATED": {"ACTIVE", "ON_LEAVE"}}
    if emp["employment_status"] not in allowed_from[to]:
        fail("ERR_INVALID_STATE", 409,
             "employment_status %s does not admit transition to %s" % (emp["employment_status"], to))
    emp["employment_status"] = to
    if to == "TERMINATED":
        S.cascade_employee_terminated(emp)
    bump(emp)
    return ok(S.ser_employee(emp))


@bp.post("/employees/<rid>/attest")
def attest(rid):
    uid = require_roles("CoveredEmployee")
    # ownership: path identifier must equal the caller's X-User-ID
    if uid != rid:
        fail("ERR_NOT_RESOURCE_OWNER", 403, "covered employee may only attest for their own record")
    emp = get_or_404("employees", rid)
    if emp["employment_status"] == "TERMINATED":
        fail("ERR_INVALID_STATE", 409, "terminated employees admit no further transitions")
    emp["attestation_status"] = "CURRENT"
    emp["last_attested_at"] = now()
    emp["attestation_due_at"] = now() + timedelta(days=365)
    bump(emp)
    return ok(S.ser_employee(emp))


@bp.get("/employees/<rid>/personal-trades")
def employee_personal_trades(rid):
    require_any_role()
    get_or_404("employees", rid)
    rows = [t for t in db["trades"].values() if t["employee_id"] == rid]
    rows = filter_param(rows, "status", request.args.get("status"))
    return list_response(rows, S.ser_trade)


@bp.get("/employees/<rid>/comm-review-items")
def employee_comm_items(rid):
    require_any_role()
    get_or_404("employees", rid)
    rows = [i for i in db["comm_items"].values() if i["author_employee_id"] == rid]
    rows = filter_param(rows, "status", request.args.get("status"))
    return list_response(rows, S.ser_comm_item)


# ==================================================================
# Venues
# ==================================================================
@bp.post("/venues")
def create_venue():
    require_roles("ComplianceAdmin")
    body = get_body()
    venue_code = req_str(body, "venue_code")
    name = req_str(body, "name")
    venue_type = req_enum(body, "venue_type", VENUE_TYPES)
    if any(v["venue_code"] == venue_code for v in db["venues"].values()):
        fail("ERR_DUPLICATE_VENUE_CODE", 409, "venue_code already in use")
    v = new_resource()
    v.update({"venue_code": venue_code, "name": name, "venue_type": venue_type,
              "status": "ACTIVE"})
    db["venues"][v["id"]] = v
    return ok(S.ser_venue(v), status=201)


@bp.get("/venues/<rid>")
def get_venue(rid):
    require_any_role()
    return ok(S.ser_venue(get_or_404("venues", rid)))


@bp.post("/venues/<rid>/transition")
def venue_transition(rid):
    uid, body = require_transition_roles(
        {"SUSPENDED": {"ComplianceAdmin"}, "ACTIVE": {"ComplianceAdmin"}})
    venue = get_or_404("venues", rid)
    to = req_enum(body, "to_status", {"ACTIVE", "SUSPENDED"})
    allowed_from = {"SUSPENDED": {"ACTIVE"}, "ACTIVE": {"SUSPENDED"}}
    if venue["status"] not in allowed_from[to]:
        fail("ERR_INVALID_STATE", 409,
             "venue status %s does not admit transition to %s" % (venue["status"], to))
    if to == "SUSPENDED":
        S.cascade_venue_suspended(venue)  # cascade links 2+3; reinstatement restores nothing
    else:
        venue["status"] = "ACTIVE"
        bump(venue)
    return ok(S.ser_venue(venue))


@bp.get("/venues/<rid>/routing-arrangements")
def venue_arrangements(rid):
    require_any_role()
    get_or_404("venues", rid)
    rows = [a for a in db["arrangements"].values() if a["venue_id"] == rid]
    rows = filter_param(rows, "status", request.args.get("status"))
    return list_response(rows, S.ser_arrangement)


@bp.get("/venues/<rid>/execution-quality-snapshots")
def venue_snapshots(rid):
    require_any_role()
    get_or_404("venues", rid)
    rows = [s for s in db["snapshots"].values() if s["venue_id"] == rid]
    rows = filter_param(rows, "period_month", request.args.get("period_month"))
    rows = filter_param(rows, "status", request.args.get("status"))
    rows = filter_param(rows, "variant", request.args.get("variant"))
    return list_response(rows, S.ser_snapshot)


# ==================================================================
# Routing arrangements
# ==================================================================
def validate_tiers(v):
    """pfof_tiers: non-empty array of {min_monthly_shares:int, rate_cents_per_share:number},
    strictly ascending by min, first min == 0."""
    if not isinstance(v, list) or len(v) == 0:
        fail("ERR_INVALID_REQUEST", 400, "pfof_tiers must be a non-empty array")
    prev = None
    for entry in v:
        if not isinstance(entry, dict):
            fail("ERR_INVALID_REQUEST", 400, "pfof_tiers entries must be objects")
        mn = entry.get("min_monthly_shares")
        rt = entry.get("rate_cents_per_share")
        if isinstance(mn, bool) or not isinstance(mn, int) or mn < 0:
            fail("ERR_INVALID_REQUEST", 400, "min_monthly_shares must be a non-negative integer")
        if isinstance(rt, bool) or not isinstance(rt, (int, float)):
            fail("ERR_INVALID_REQUEST", 400, "rate_cents_per_share must be a number")
        if prev is not None and mn <= prev:
            fail("ERR_INVALID_REQUEST", 400, "pfof_tiers must be sorted ascending by min_monthly_shares")
        prev = mn
    if v[0]["min_monthly_shares"] != 0:
        fail("ERR_INVALID_REQUEST", 400, "first pfof_tiers entry must have min_monthly_shares = 0")
    return v


def window_overlaps(venue_id, eff_from, eff_to, exclude_id=None):
    """Half-open window intersection vs arrangements of the same venue in
    {NEGOTIATION, ACTIVE, SUSPENDED}; touching endpoints allowed."""
    for a in db["arrangements"].values():
        if a["venue_id"] != venue_id or a["id"] == exclude_id:
            continue
        if a["status"] not in ("NEGOTIATION", "ACTIVE", "SUSPENDED"):
            continue
        if eff_from < a["effective_to"] and a["effective_from"] < eff_to:
            return True
    return False


@bp.post("/routing-arrangements")
def create_arrangement():
    require_roles("ComplianceAdmin")
    body = get_body()
    # body-referenced FK existence (priority 4) precedes remaining shape checks (priority 5)
    venue_id = body.get("venue_id")
    if venue_id is not None:
        if not isinstance(venue_id, str):
            fail("ERR_INVALID_REQUEST", 400, "venue_id must be a string")
        get_or_404("venues", venue_id)
    venue_id = req_str(body, "venue_id")
    eff_from = req_dt_field(body, "effective_from")
    eff_to = req_dt_field(body, "effective_to")
    tiers = validate_tiers(body.get("pfof_tiers"))
    fee = req_num(body, "routing_fee_bps")
    if eff_to <= eff_from:
        fail("ERR_INVALID_WINDOW", 422, "effective_to must be strictly after effective_from")
    if window_overlaps(venue_id, eff_from, eff_to):
        fail("ERR_ARRANGEMENT_WINDOW_OVERLAP", 409, "window overlaps another arrangement of this venue")
    a = new_resource()
    a.update({"venue_id": venue_id, "effective_from": eff_from, "effective_to": eff_to,
              "pfof_tiers": tiers, "routing_fee_bps": fee, "status": "NEGOTIATION"})
    db["arrangements"][a["id"]] = a
    return ok(S.ser_arrangement(a), status=201)


@bp.get("/routing-arrangements/<rid>")
def get_arrangement(rid):
    require_any_role()
    return ok(S.ser_arrangement(get_or_404("arrangements", rid)))


@bp.post("/routing-arrangements/<rid>/transition")
def arrangement_transition(rid):
    uid, body = require_transition_roles(
        {"ACTIVE": {"ComplianceAdmin"}, "SUSPENDED": {"ComplianceAdmin"},
         "TERMINATED": {"ComplianceAdmin"}})
    a = get_or_404("arrangements", rid)
    to = req_enum(body, "to_status", {"ACTIVE", "SUSPENDED", "TERMINATED"})
    allowed_from = {"ACTIVE": {"NEGOTIATION", "SUSPENDED"}, "SUSPENDED": {"ACTIVE"},
                    "TERMINATED": {"NEGOTIATION", "ACTIVE", "SUSPENDED"}}
    if a["status"] not in allowed_from[to]:
        fail("ERR_INVALID_STATE", 409,
             "arrangement status %s does not admit transition to %s" % (a["status"], to))
    if to == "ACTIVE":
        venue = db["venues"].get(a["venue_id"])
        if venue is None or venue["status"] != "ACTIVE":
            fail("ERR_VENUE_SUSPENDED", 409, "venue is not ACTIVE")
        if not a["effective_to"] > now():
            fail("ERR_INVALID_WINDOW", 422, "arrangement window has already closed")
        if window_overlaps(a["venue_id"], a["effective_from"], a["effective_to"], exclude_id=a["id"]):
            fail("ERR_ARRANGEMENT_WINDOW_OVERLAP", 409, "window overlaps another arrangement of this venue")
        a["status"] = "ACTIVE"
        bump(a)
    elif to == "SUSPENDED":
        S.cascade_arrangement_suspended(a)  # cascade link 3: cancels ROUTED orders
    else:  # TERMINATED
        was_active = a["status"] == "ACTIVE"
        a["status"] = "TERMINATED"
        bump(a)
        if was_active:
            S.cancel_routed_orders(a)
    return ok(S.ser_arrangement(a))


@bp.post("/routing-arrangements/<rid>/amend")
def amend_arrangement(rid):
    require_roles("ComplianceAdmin")
    a = get_or_404("arrangements", rid)
    body = get_body()
    expected = req_int(body, "expected_arrangement_version")
    # validate provided replacement fields (shape precedes OCC/state)
    new_tiers = a["pfof_tiers"]
    if "pfof_tiers" in body and body["pfof_tiers"] is not None:
        new_tiers = validate_tiers(body["pfof_tiers"])
    new_fee = a["routing_fee_bps"]
    if "routing_fee_bps" in body and body["routing_fee_bps"] is not None:
        v = body["routing_fee_bps"]
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            fail("ERR_INVALID_REQUEST", 400, "routing_fee_bps must be a number")
        new_fee = v
    new_from = a["effective_from"]
    if "effective_from" in body and body["effective_from"] is not None:
        new_from = parse_dt(body["effective_from"], "effective_from")
    new_to = a["effective_to"]
    if "effective_to" in body and body["effective_to"] is not None:
        new_to = parse_dt(body["effective_to"], "effective_to")
    # OCC (priority 8) precedes state admissibility (priority 9)
    if expected != a["version"]:
        fail("ERR_STALE_VERSION", 412, "expected_arrangement_version does not match current version")
    if a["status"] == "TERMINATED":
        fail("ERR_INVALID_STATE", 409, "terminated arrangements admit no further transitions")
    if new_to <= new_from:
        fail("ERR_INVALID_WINDOW", 422, "effective_to must be strictly after effective_from")
    if window_overlaps(a["venue_id"], new_from, new_to, exclude_id=a["id"]):
        fail("ERR_ARRANGEMENT_WINDOW_OVERLAP", 409, "window overlaps another arrangement of this venue")
    a["pfof_tiers"] = new_tiers
    a["routing_fee_bps"] = new_fee
    a["effective_from"] = new_from
    a["effective_to"] = new_to
    bump(a)
    return ok(S.ser_arrangement(a))


@bp.get("/routing-arrangements/<rid>/orders")
def arrangement_orders(rid):
    require_any_role()
    get_or_404("arrangements", rid)
    rows = [o for o in db["orders"].values() if o["arrangement_id"] == rid]
    rows = filter_param(rows, "order_type", request.args.get("order_type"))
    rows = filter_param(rows, "status", request.args.get("status"))
    return list_response(rows, S.ser_order)


# ==================================================================
# Orders
# ==================================================================
@bp.post("/orders")
def create_order():
    require_roles("OpsAdmin")
    body = get_body()
    client_ref = req_str(body, "client_ref")
    symbol = req_str(body, "symbol")
    side = req_enum(body, "side", SIDES)
    quantity = req_int(body, "quantity")
    if quantity <= 0:
        fail("ERR_INVALID_REQUEST", 400, "quantity must be > 0")
    order_type = req_enum(body, "order_type", ORDER_TYPES)
    bid = req_int(body, "arrival_nbbo_bid_cents")
    ask = req_int(body, "arrival_nbbo_ask_cents")
    if bid <= 0:
        fail("ERR_INVALID_REQUEST", 400, "arrival_nbbo_bid_cents must be > 0")
    if ask <= bid:
        fail("ERR_INVALID_REQUEST", 400, "arrival_nbbo_ask_cents must be > arrival_nbbo_bid_cents")
    # conditional limit price rule reports ERR_LIMIT_PRICE_REQUIRED instead of a shape error
    lp = body.get("limit_price_cents")
    if order_type == "LIMIT":
        if lp is None:
            fail("ERR_LIMIT_PRICE_REQUIRED", 422, "limit_price_cents is required for LIMIT orders")
        if isinstance(lp, bool) or not isinstance(lp, int):
            fail("ERR_INVALID_REQUEST", 400, "limit_price_cents must be an integer")
    else:
        if lp is not None:
            fail("ERR_LIMIT_PRICE_REQUIRED", 422, "limit_price_cents is forbidden for non-LIMIT orders")
    o = new_resource()
    o.update({"client_ref": client_ref, "symbol": symbol, "side": side, "quantity": quantity,
              "order_type": order_type, "limit_price_cents": lp,
              "arrival_nbbo_bid_cents": bid, "arrival_nbbo_ask_cents": ask,
              "arrangement_id": None, "status": "RECEIVED", "routed_at": None,
              "executed_price_cents": None, "executed_at": None})
    db["orders"][o["id"]] = o
    return ok(S.ser_order(o), status=201)


@bp.post("/orders/<rid>/transition")
def order_transition(rid):
    uid, body = require_transition_roles(
        {"ROUTED": {"OpsAdmin"}, "EXECUTED": {"OpsAdmin"}, "CANCELLED": {"OpsAdmin"}})
    o = get_or_404("orders", rid)
    to = req_enum(body, "to_status", {"ROUTED", "EXECUTED", "CANCELLED"})
    if to == "ROUTED":
        arrangement_id = body.get("arrangement_id")
        if not isinstance(arrangement_id, str) or arrangement_id == "":
            fail("ERR_INVALID_REQUEST", 400, "arrangement_id is required for ROUTED")
        arrangement = get_or_404("arrangements", arrangement_id)
        if o["status"] != "RECEIVED":
            fail("ERR_INVALID_STATE", 409, "only RECEIVED orders can be routed")
        venue = db["venues"].get(arrangement["venue_id"])
        if venue is None or venue["status"] != "ACTIVE":
            fail("ERR_VENUE_SUSPENDED", 409, "arrangement venue is not ACTIVE")
        for r in db["restricted"].values():
            if (r["symbol"] == o["symbol"] and r["status"] == "ACTIVE"
                    and r["restriction_kind"] in ("ALL", "CLIENT_ONLY")):
                fail("ERR_SYMBOL_RESTRICTED", 409, "symbol is on the ACTIVE restricted list")
        if not (arrangement["status"] == "ACTIVE"
                and arrangement["effective_from"] <= now() < arrangement["effective_to"]):
            fail("ERR_NO_ACTIVE_ARRANGEMENT", 409,
                 "arrangement is not ACTIVE or now is outside its effective window")
        o["arrangement_id"] = arrangement_id
        o["status"] = "ROUTED"
        o["routed_at"] = now()
    elif to == "EXECUTED":
        price = req_int(body, "executed_price_cents")
        ex_at = req_dt_field(body, "executed_at")
        if o["status"] != "ROUTED":
            fail("ERR_INVALID_STATE", 409, "only ROUTED orders can be executed")
        if not (o["created_at"] <= ex_at <= now()):
            fail("ERR_EXECUTION_WINDOW_VIOLATION", 422,
                 "executed_at must lie in [created_at, now]")
        o["executed_price_cents"] = price
        o["executed_at"] = ex_at
        o["status"] = "EXECUTED"
        bump(o)
        # surveillance detections fire synchronously on execution
        S.forward_front_running_scan(o)
        S.marking_close_check(o)
        return ok(S.ser_order(o))
    else:  # CANCELLED
        if o["status"] not in ("RECEIVED", "ROUTED"):
            fail("ERR_INVALID_STATE", 409, "only RECEIVED or ROUTED orders can be cancelled")
        o["status"] = "CANCELLED"
    bump(o)
    return ok(S.ser_order(o))


# ==================================================================
# Execution quality snapshots
# ==================================================================
@bp.post("/execution-quality-snapshots")
def create_snapshot():
    require_roles("ComplianceAdmin")
    body = get_body()
    venue_id = body.get("venue_id")
    if venue_id is not None:
        if not isinstance(venue_id, str):
            fail("ERR_INVALID_REQUEST", 400, "venue_id must be a string")
        get_or_404("venues", venue_id)
    venue_id = req_str(body, "venue_id")
    order_type = req_enum(body, "order_type", ORDER_TYPES)
    period_month = req_str(body, "period_month")
    if not MONTH_RE.match(period_month):
        fail("ERR_INVALID_REQUEST", 400, "period_month must be in YYYY-MM format")
    variant = req_enum(body, "variant", VARIANTS_EQ)
    for s in db["snapshots"].values():
        if (s["venue_id"] == venue_id and s["order_type"] == order_type
                and s["period_month"] == period_month and s["variant"] == variant):
            fail("ERR_DUPLICATE_SNAPSHOT", 409,
                 "snapshot already exists for (venue_id, order_type, period_month, variant)")
    s = new_resource()
    s.update({"venue_id": venue_id, "order_type": order_type, "period_month": period_month,
              "variant": variant, "status": "PROVISIONAL", "frozen_metrics": None})
    db["snapshots"][s["id"]] = s
    return ok(S.ser_snapshot(s), status=201)


@bp.post("/execution-quality-snapshots/<rid>/lock")
def lock_snapshot(rid):
    require_roles("ComplianceAdmin")
    s = get_or_404("snapshots", rid)
    if s["status"] != "PROVISIONAL":
        fail("ERR_INVALID_STATE", 409, "only PROVISIONAL snapshots can be locked")
    _, period_end = S.month_window(s["period_month"])
    for o in db["orders"].values():
        if o["status"] not in ("RECEIVED", "ROUTED"):
            continue
        if o["order_type"] != s["order_type"]:
            continue
        if not o["created_at"] < period_end:
            continue
        a = db["arrangements"].get(o["arrangement_id"] or "")
        if a is None or a["venue_id"] != s["venue_id"]:
            continue
        fail("ERR_UNRESOLVED_ORDERS", 409, "in-scope orders remain unresolved")
    s["frozen_metrics"] = S.compute_eq(s)
    s["status"] = "LOCKED"
    bump(s)
    return ok(S.ser_snapshot(s))


# ==================================================================
# PFOF disclosures
# ==================================================================
@bp.post("/pfof-disclosures")
def create_disclosure():
    require_roles("FilingOfficer")
    body = get_body()
    quarter = req_str(body, "quarter")
    if not QUARTER_RE.match(quarter):
        fail("ERR_INVALID_REQUEST", 400, "quarter must be in YYYY-Qn format")
    pricing_variant = req_enum(body, "pricing_variant", PRICING_VARIANTS)
    for d in db["disclosures"].values():
        if d["quarter"] == quarter and d["status"] != "SUPERSEDED":
            fail("ERR_DUPLICATE_DISCLOSURE", 409,
                 "a non-SUPERSEDED disclosure already exists for this quarter; use revise")
    d = new_resource()
    d.update({"quarter": quarter, "pricing_variant": pricing_variant, "revision_number": 1,
              "supersedes_id": None, "has_pending_revision": False, "status": "DRAFT",
              "frozen_lines": [], "frozen_total": 0, "submitted_at": None})
    db["disclosures"][d["id"]] = d
    return ok(S.ser_disclosure(d), status=201)


@bp.get("/pfof-disclosures/<rid>")
def get_disclosure(rid):
    require_any_role()
    return ok(S.ser_disclosure(get_or_404("disclosures", rid)))


@bp.get("/pfof-disclosures")
def list_disclosures():
    require_any_role()
    rows = list(db["disclosures"].values())
    rows = filter_param(rows, "quarter", request.args.get("quarter"))
    rows = filter_param(rows, "status", request.args.get("status"))
    rows = filter_param(rows, "supersedes_id", request.args.get("supersedes_id"))
    return list_response(rows, S.ser_disclosure)


@bp.post("/pfof-disclosures/<rid>/transition")
def disclosure_transition(rid):
    uid, body = require_transition_roles(
        {"PENDING_APPROVAL": {"FilingOfficer"}, "PUBLISHED": {"FilingOfficer"},
         "DRAFT": {"FilingOfficer"}})
    d = get_or_404("disclosures", rid)
    to = req_enum(body, "to_status", {"PENDING_APPROVAL", "PUBLISHED", "DRAFT"})
    allowed_from = {"PENDING_APPROVAL": {"DRAFT"}, "PUBLISHED": {"PENDING_APPROVAL"},
                    "DRAFT": {"PENDING_APPROVAL"}}
    if d["status"] not in allowed_from[to]:
        fail("ERR_INVALID_STATE", 409,
             "disclosure status %s does not admit transition to %s" % (d["status"], to))
    if to == "PENDING_APPROVAL":
        # coverage gate: every EXECUTED order in the quarter needs a covering arrangement
        qstart, qend = S.quarter_window(d["quarter"])
        for o in db["orders"].values():
            if o["status"] != "EXECUTED" or o["executed_at"] is None:
                continue
            if qstart <= o["executed_at"] < qend and S.covering_arrangement(o) is None:
                fail("ERR_UNCOVERED_VOLUME", 409,
                     "an EXECUTED order in the quarter has no covering arrangement")
        lines, total = S.compute_venue_lines(d)
        d["frozen_lines"] = lines
        d["frozen_total"] = total
        d["submitted_at"] = now()
        d["status"] = "PENDING_APPROVAL"
    elif to == "PUBLISHED":
        for line in d["frozen_lines"]:
            a = db["arrangements"].get(line["arrangement_id"])
            if a is None or a["version"] != line["arrangement_version"]:
                fail("ERR_DISCLOSURE_STALE", 409,
                     "a pinned arrangement version no longer matches the current version")
        if d["supersedes_id"]:
            src = db["disclosures"].get(d["supersedes_id"])
            if src is not None and src["status"] == "PUBLISHED":
                src["status"] = "SUPERSEDED"
                bump(src)
        d["status"] = "PUBLISHED"
    else:  # DRAFT (withdraw for rework): unfreeze lines, clear submitted_at
        d["frozen_lines"] = []
        d["frozen_total"] = 0
        d["submitted_at"] = None
        d["status"] = "DRAFT"
    bump(d)
    return ok(S.ser_disclosure(d))


@bp.post("/pfof-disclosures/<rid>/revise")
def revise_disclosure(rid):
    require_roles("FilingOfficer")
    src = get_or_404("disclosures", rid)
    body = get_body()
    expected = req_int(body, "expected_disclosure_version")
    # OCC (priority 8) precedes state admissibility (priority 9)
    if expected != src["version"]:
        fail("ERR_STALE_VERSION", 412, "expected_disclosure_version does not match current version")
    if src["status"] != "PUBLISHED":
        fail("ERR_INVALID_STATE", 409, "only PUBLISHED disclosures can be revised")
    d = new_resource()
    d.update({"quarter": src["quarter"], "pricing_variant": src["pricing_variant"],
              "revision_number": src["revision_number"] + 1, "supersedes_id": src["id"],
              "has_pending_revision": False, "status": "DRAFT",
              "frozen_lines": [], "frozen_total": 0, "submitted_at": None})
    db["disclosures"][d["id"]] = d
    src["has_pending_revision"] = True
    bump(src)
    return ok(S.ser_disclosure(d), status=201)


# ==================================================================
# Best-execution committee reviews
# ==================================================================
@bp.post("/best-ex-reviews")
def create_review():
    uid = require_roles("BestExAnalyst")
    body = get_body()
    quarter = req_str(body, "quarter")
    if not QUARTER_RE.match(quarter):
        fail("ERR_INVALID_REQUEST", 400, "quarter must be in YYYY-Qn format")
    snapshot_ids = body.get("snapshot_ids")
    venue_decisions = body.get("venue_decisions")
    # body-referenced ids resolve left to right (existence precedes remaining shape checks)
    if isinstance(snapshot_ids, list):
        for sid in snapshot_ids:
            if isinstance(sid, str):
                get_or_404("snapshots", sid)
    if isinstance(venue_decisions, list):
        for vd in venue_decisions:
            if isinstance(vd, dict) and isinstance(vd.get("venue_id"), str):
                get_or_404("venues", vd["venue_id"])
    if not isinstance(snapshot_ids, list) or any(not isinstance(x, str) for x in snapshot_ids):
        fail("ERR_INVALID_REQUEST", 400, "snapshot_ids must be an array of snapshot ids")
    if not isinstance(venue_decisions, list):
        fail("ERR_INVALID_REQUEST", 400, "venue_decisions must be an array")
    for vd in venue_decisions:
        if not isinstance(vd, dict) or not isinstance(vd.get("venue_id"), str):
            fail("ERR_INVALID_REQUEST", 400, "venue_decisions entries need a venue_id")
        if vd.get("determination") not in DETERMINATIONS:
            fail("ERR_INVALID_REQUEST", 400,
                 "determination must be one of: CONTINUE, MODIFY, TERMINATE_ROUTING")
    r = new_resource()
    r.update({"quarter": quarter, "snapshot_ids": list(snapshot_ids),
              "venue_decisions": venue_decisions, "created_by_user_id": uid,
              "voter_user_ids": [], "status": "DRAFT"})
    db["reviews"][r["id"]] = r
    return ok(S.ser_review(r), status=201)


@bp.get("/best-ex-reviews/<rid>")
def get_review(rid):
    require_any_role()
    return ok(S.ser_review(get_or_404("reviews", rid)))


@bp.post("/best-ex-reviews/<rid>/transition")
def review_transition(rid):
    uid, body = require_transition_roles(
        {"IN_COMMITTEE": {"BestExAnalyst"}, "DRAFT": {"CommitteeMember"},
         "PUBLISHED": {"BestExAnalyst"}})
    r = get_or_404("reviews", rid)
    to = req_enum(body, "to_status", {"IN_COMMITTEE", "DRAFT", "PUBLISHED"})
    # request-shape gate (priority 5) precedes state admissibility (priority 9)
    if to == "IN_COMMITTEE" and len(r["snapshot_ids"]) == 0:
        fail("ERR_INVALID_REQUEST", 400, "snapshot_ids must be non-empty")
    allowed_from = {"IN_COMMITTEE": {"DRAFT"}, "DRAFT": {"IN_COMMITTEE"},
                    "PUBLISHED": {"APPROVED"}}
    if r["status"] not in allowed_from[to]:
        fail("ERR_INVALID_STATE", 409,
             "review status %s does not admit transition to %s" % (r["status"], to))
    if to == "IN_COMMITTEE":
        for sid in r["snapshot_ids"]:
            s = db["snapshots"].get(sid)
            if s is None or s["status"] != "LOCKED":
                fail("ERR_SNAPSHOT_NOT_LOCKED", 409, "every referenced snapshot must be LOCKED")
        active_venues = [v["id"] for v in db["venues"].values() if v["status"] == "ACTIVE"]
        decision_ids = [vd["venue_id"] for vd in r["venue_decisions"]]
        if (len(decision_ids) != len(set(decision_ids))
                or set(decision_ids) != set(active_venues)):
            fail("ERR_INCOMPLETE_VENUE_DECISIONS", 409,
                 "venue_decisions must cover every ACTIVE venue exactly once")
        r["status"] = "IN_COMMITTEE"
    elif to == "DRAFT":
        r["voter_user_ids"] = []  # return for rework clears the vote count
        r["status"] = "DRAFT"
    else:  # PUBLISHED
        published = any(d["quarter"] == r["quarter"] and d["status"] == "PUBLISHED"
                        for d in db["disclosures"].values())
        if not published:
            fail("ERR_DISCLOSURE_NOT_PUBLISHED", 409,
                 "no PUBLISHED disclosure exists for the review's quarter")
        # cascade link 1: TERMINATE_ROUTING venues go SUSPENDED (links 2+3 follow)
        for vd in r["venue_decisions"]:
            if vd["determination"] == "TERMINATE_ROUTING":
                v = db["venues"].get(vd["venue_id"])
                if v is not None and v["status"] == "ACTIVE":
                    S.cascade_venue_suspended(v)
        r["status"] = "PUBLISHED"
    bump(r)
    return ok(S.ser_review(r))


@bp.post("/best-ex-reviews/<rid>/vote")
def vote_review(rid):
    uid = require_roles("CommitteeMember")
    r = get_or_404("reviews", rid)
    if r["status"] != "IN_COMMITTEE":
        fail("ERR_INVALID_STATE", 409, "votes are only accepted while IN_COMMITTEE")
    if uid == r["created_by_user_id"]:
        fail("ERR_SELF_APPROVAL_FORBIDDEN", 403, "review creator may not vote on their own review")
    if uid in r["voter_user_ids"]:
        fail("ERR_DUPLICATE_VOTE", 409, "committee member has already voted in this round")
    r["voter_user_ids"].append(uid)
    if len(r["voter_user_ids"]) >= 3:  # approval quorum: 3rd distinct vote auto-approves
        r["status"] = "APPROVED"
    bump(r)
    return ok(S.ser_review(r))


# ==================================================================
# Surveillance alerts
# ==================================================================
@bp.get("/surveillance-alerts")
def list_alerts():
    require_any_role()
    rows = list(db["alerts"].values())
    for f in ("subject_employee_id", "related_order_id", "related_trade_id",
              "case_id", "alert_type", "status"):
        rows = filter_param(rows, f, request.args.get(f))
    return list_response(rows, S.ser_alert)


@bp.get("/surveillance-alerts/<rid>")
def get_alert(rid):
    require_any_role()
    return ok(S.ser_alert(get_or_404("alerts", rid)))


@bp.post("/surveillance-alerts/<rid>/transition")
def alert_transition(rid):
    uid, body = require_transition_roles(
        {"ACKNOWLEDGED": {"SurveillanceAnalyst"}, "ESCALATED": {"SurveillanceAnalyst"},
         "CLOSED_FALSE_POSITIVE": {"SurveillanceAnalyst"}})
    a = get_or_404("alerts", rid)
    to = req_enum(body, "to_status", {"ACKNOWLEDGED", "ESCALATED", "CLOSED_FALSE_POSITIVE"})
    # note: ESCALATED -> ACKNOWLEDGED is system-only (case-reopen compensation), never via endpoint
    allowed_from = {"ACKNOWLEDGED": {"NEW"}, "ESCALATED": {"ACKNOWLEDGED"},
                    "CLOSED_FALSE_POSITIVE": {"NEW", "ACKNOWLEDGED"}}
    if a["status"] not in allowed_from[to]:
        fail("ERR_INVALID_STATE", 409,
             "alert status %s does not admit transition to %s" % (a["status"], to))
    if to == "ESCALATED":
        if not a["score"] >= 50:
            fail("ERR_ALERT_SCORE_BELOW_ESCALATION", 409, "escalation requires score >= 50")
        # deterministic case selector: link to the subject's open case when one exists
        candidate = None
        if a["subject_employee_id"] is not None:
            for c in db["cases"].values():
                if (c["subject_employee_id"] == a["subject_employee_id"]
                        and c["review_status"] in ("OPEN", "UNDER_INVESTIGATION", "REOPENED")):
                    candidate = c
                    break
        if candidate is None:
            candidate = S.create_case(a["subject_employee_id"], "ALERT",
                                      linked_alert_ids=[a["id"]])
        else:
            candidate["linked_alert_ids"].append(a["id"])
            bump(candidate)
        a["case_id"] = candidate["id"]
        a["status"] = "ESCALATED"
    elif to == "CLOSED_FALSE_POSITIVE":
        if not a["score"] < 50:
            fail("ERR_ALERT_SCORE_ABOVE_FP_CEILING", 409,
                 "close-as-false-positive requires score < 50")
        a["status"] = "CLOSED_FALSE_POSITIVE"
    else:
        a["status"] = "ACKNOWLEDGED"
    bump(a)
    return ok(S.ser_alert(a))


# ==================================================================
# Surveillance cases (two parallel dimensions: review_status, filing_status)
# ==================================================================
@bp.get("/surveillance-cases")
def list_cases():
    require_any_role()
    rows = list(db["cases"].values())
    for f in ("subject_employee_id", "source_comm_item_id", "review_status", "filing_status"):
        rows = filter_param(rows, f, request.args.get(f))
    return list_response(rows, S.ser_case)


@bp.get("/surveillance-cases/<rid>")
def get_case(rid):
    require_any_role()
    return ok(S.ser_case(get_or_404("cases", rid)))


@bp.post("/surveillance-cases/<rid>/review-transition")
def case_review_transition(rid):
    uid, body = require_transition_roles(
        {"UNDER_INVESTIGATION": {"SurveillanceAnalyst"}, "DISPOSITIONED": {"SurveillanceAnalyst"},
         "REOPENED": {"SurveillanceAnalyst"}})
    c = get_or_404("cases", rid)
    to = req_enum(body, "to_status", {"UNDER_INVESTIGATION", "DISPOSITIONED", "REOPENED"})
    disposition = None
    if to == "DISPOSITIONED":
        disposition = req_enum(body, "disposition", DISPOSITIONS)
    allowed_from = {"UNDER_INVESTIGATION": {"OPEN", "REOPENED"},
                    "DISPOSITIONED": {"UNDER_INVESTIGATION"}, "REOPENED": {"DISPOSITIONED"}}
    if c["review_status"] not in allowed_from[to]:
        fail("ERR_INVALID_STATE", 409,
             "review_status %s does not admit transition to %s" % (c["review_status"], to))
    if to == "UNDER_INVESTIGATION":
        c["review_status"] = "UNDER_INVESTIGATION"
    elif to == "DISPOSITIONED":
        c["disposition"] = disposition
        c["dispositioned_at"] = now()
        if disposition == "VIOLATION_CONFIRMED":
            c["filing_status"] = "DRAFT"
            c["filing_due_at"] = now() + timedelta(days=30)
        c["review_status"] = "DISPOSITIONED"
    else:  # REOPENED
        if c["filing_status"] in ("SUBMITTED", "ACKNOWLEDGED"):
            fail("ERR_FILING_IN_FLIGHT", 409, "cannot reopen while a filing is in flight")
        # compensation: linked alerts drop back to ACKNOWLEDGED with case_id cleared
        for aid in c["linked_alert_ids"]:
            a = db["alerts"].get(aid)
            if a is not None and a["status"] == "ESCALATED":
                a["status"] = "ACKNOWLEDGED"
                a["case_id"] = None
                bump(a)
        if c["filing_status"] == "DRAFT":
            c["filing_status"] = "NOT_REQUIRED"
            c["filing_due_at"] = None
            c["filing_submitted_at"] = None
            c["late_fee_cents"] = 0
        c["disposition"] = None
        c["dispositioned_at"] = None
        c["review_status"] = "REOPENED"
    bump(c)
    return ok(S.ser_case(c))


@bp.post("/surveillance-cases/<rid>/filing-transition")
def case_filing_transition(rid):
    uid, body = require_transition_roles(
        {"SUBMITTED": {"FilingOfficer"}, "ACKNOWLEDGED": {"FilingOfficer"},
         "DRAFT": {"FilingOfficer"}})
    c = get_or_404("cases", rid)
    to = req_enum(body, "to_status", {"SUBMITTED", "ACKNOWLEDGED", "DRAFT"})
    if to == "SUBMITTED":
        # a filing that never opened (NOT_REQUIRED) reports ERR_FILING_NOT_REQUIRED
        if c["filing_status"] == "NOT_REQUIRED":
            fail("ERR_FILING_NOT_REQUIRED", 409, "this case has no filing to submit")
        if c["filing_status"] != "DRAFT":
            fail("ERR_INVALID_STATE", 409,
                 "filing_status %s does not admit transition to SUBMITTED" % c["filing_status"])
        if not (c["review_status"] == "DISPOSITIONED" and c["disposition"] == "VIOLATION_CONFIRMED"):
            fail("ERR_FILING_NOT_REQUIRED", 409,
                 "filing submit requires a DISPOSITIONED case with disposition VIOLATION_CONFIRMED")
        c["filing_submitted_at"] = now()
        c["late_fee_cents"] = S.calc_late_fee(c["filing_submitted_at"], c["filing_due_at"])
        c["filing_status"] = "SUBMITTED"
    elif to == "ACKNOWLEDGED":
        if c["filing_status"] != "SUBMITTED":
            fail("ERR_INVALID_STATE", 409,
                 "filing_status %s does not admit transition to ACKNOWLEDGED" % c["filing_status"])
        c["filing_status"] = "ACKNOWLEDGED"
    else:  # DRAFT: regulator rejection returns the filing for amendment
        if c["filing_status"] != "SUBMITTED":
            fail("ERR_INVALID_STATE", 409,
                 "filing_status %s does not admit transition to DRAFT" % c["filing_status"])
        # filing_submitted_at retained as audit of the rejected submission
        c["filing_status"] = "DRAFT"
    bump(c)
    return ok(S.ser_case(c))


# ==================================================================
# Personal trades
# ==================================================================
@bp.post("/personal-trades")
def create_personal_trade():
    uid = require_roles("CoveredEmployee")
    body = get_body()
    symbol = req_str(body, "symbol")
    side = req_enum(body, "side", SIDES)
    quantity = req_int(body, "quantity")
    if quantity <= 0:
        fail("ERR_INVALID_REQUEST", 400, "quantity must be > 0")
    t = new_resource()
    # employee_id is taken from the caller's X-User-ID, never from the request body
    t.update({"employee_id": uid, "symbol": symbol, "side": side, "quantity": quantity,
              "status": "PRECLEARANCE_REQUESTED", "decided_at": None, "denial_reason": None,
              "expires_at": None, "executed_price_cents": None, "executed_at": None,
              "reconciled_at": None})
    db["trades"][t["id"]] = t
    return ok(S.ser_trade(t), status=201)


@bp.post("/personal-trades/<rid>/transition")
def personal_trade_transition(rid):
    uid, body = require_transition_roles(
        {"APPROVED": {"ComplianceAdmin"}, "DENIED": {"ComplianceAdmin"},
         "RECONCILED": {"ComplianceAdmin"}, "EXECUTION_REPORTED": {"CoveredEmployee"}})
    t = get_or_404("trades", rid)
    to = req_enum(body, "to_status", {"APPROVED", "DENIED", "EXECUTION_REPORTED", "RECONCILED"})
    if to == "EXECUTION_REPORTED" and uid != t["employee_id"]:
        fail("ERR_NOT_RESOURCE_OWNER", 403, "only the owning employee may report execution")
    allowed_from = {"APPROVED": {"PRECLEARANCE_REQUESTED"}, "DENIED": {"PRECLEARANCE_REQUESTED"},
                    "EXECUTION_REPORTED": {"APPROVED"}, "RECONCILED": {"EXECUTION_REPORTED"}}
    if t["status"] not in allowed_from[to]:
        fail("ERR_INVALID_STATE", 409,
             "trade status %s does not admit transition to %s" % (t["status"], to))
    if to == "APPROVED":
        # eligibility gauntlet, evaluated in this fixed order
        emp = db["employees"].get(t["employee_id"])
        if emp is None or emp["employment_status"] != "ACTIVE":
            fail("ERR_EMPLOYEE_NOT_ACTIVE", 409, "employee is not ACTIVE")
        if emp["attestation_status"] == "LAPSED":
            fail("ERR_ATTESTATION_LAPSED", 409, "employee attestation is LAPSED")
        if S.training_overdue_count(emp["id"]) != 0:
            fail("ERR_TRAINING_OVERDUE", 409, "employee has overdue training")
        if S.open_case_count(emp["id"]) != 0:
            fail("ERR_OPEN_SURVEILLANCE_CASE", 409, "employee has an open surveillance case")
        for r in db["restricted"].values():
            if (r["symbol"] == t["symbol"] and r["status"] == "ACTIVE"
                    and r["restriction_kind"] in ("ALL", "EMPLOYEE_ONLY")):
                fail("ERR_SYMBOL_RESTRICTED", 409, "symbol is on the ACTIVE restricted list")
        if t["side"] == "SELL":
            n = now()
            for b in db["trades"].values():
                if (b["employee_id"] == t["employee_id"] and b["symbol"] == t["symbol"]
                        and b["side"] == "BUY" and b["status"] == "RECONCILED"
                        and b["executed_at"] is not None
                        and (n - b["executed_at"]).total_seconds() < 30 * 86400):
                    fail("ERR_MIN_HOLDING_PERIOD", 409,
                         "SELL within 30 days of a RECONCILED BUY in the same symbol")
        t["decided_at"] = now()
        t["expires_at"] = now() + timedelta(hours=48)
        t["status"] = "APPROVED"
    elif to == "DENIED":
        reason = body.get("denial_reason")
        if reason is not None and not isinstance(reason, str):
            fail("ERR_INVALID_REQUEST", 400, "denial_reason must be a string")
        t["denial_reason"] = reason
        t["decided_at"] = now()
        t["status"] = "DENIED"
    elif to == "EXECUTION_REPORTED":
        price = req_int(body, "executed_price_cents")
        ex_at = req_dt_field(body, "executed_at")
        if not (t["decided_at"] <= ex_at <= t["expires_at"]):
            fail("ERR_EXECUTION_WINDOW_VIOLATION", 422,
                 "executed_at must lie in [decided_at, expires_at]")
        t["executed_price_cents"] = price
        t["executed_at"] = ex_at
        t["status"] = "EXECUTION_REPORTED"
        bump(t)
        S.reverse_front_running_scan(t)
        return ok(S.ser_trade(t))
    else:  # RECONCILED
        t["reconciled_at"] = now()
        t["status"] = "RECONCILED"
    bump(t)
    return ok(S.ser_trade(t))


# ==================================================================
# Restricted list
# ==================================================================
@bp.post("/restricted-list-entries")
def create_restricted():
    require_roles("ComplianceAdmin")
    body = get_body()
    symbol = req_str(body, "symbol")
    kind = req_enum(body, "restriction_kind", RESTRICTION_KINDS)
    eff_from = req_dt_field(body, "effective_from")
    eff_to = req_dt_field(body, "effective_to")
    if eff_to <= eff_from:
        fail("ERR_INVALID_WINDOW", 422, "effective_to must be strictly after effective_from")
    if not eff_from > now():
        fail("ERR_INVALID_WINDOW", 422, "effective_from must lie strictly in the future")
    # one-day buffer rule: buffered new window must not intersect any
    # SCHEDULED/ACTIVE entry's plain window for the same symbol (exact 86400s gap allowed)
    day = timedelta(seconds=86400)
    for r in db["restricted"].values():
        if r["symbol"] != symbol or r["status"] not in ("SCHEDULED", "ACTIVE"):
            continue
        if eff_from - day < r["effective_to"] and r["effective_from"] < eff_to + day:
            fail("ERR_RESTRICTED_WINDOW_CONFLICT", 409,
                 "buffered window conflicts with an existing entry for this symbol")
    r = new_resource()
    r.update({"symbol": symbol, "restriction_kind": kind,
              "effective_from": eff_from, "effective_to": eff_to, "status": "SCHEDULED"})
    db["restricted"][r["id"]] = r
    return ok(S.ser_restricted(r), status=201)


@bp.get("/restricted-list-entries/<rid>")
def get_restricted(rid):
    require_any_role()
    return ok(S.ser_restricted(get_or_404("restricted", rid)))


# ==================================================================
# Communications review
# ==================================================================
@bp.post("/comm-review-items")
def create_comm_item():
    require_roles("OpsAdmin")
    body = get_body()
    author_id = body.get("author_employee_id")
    if author_id is not None:
        if not isinstance(author_id, str):
            fail("ERR_INVALID_REQUEST", 400, "author_employee_id must be a string")
        get_or_404("employees", author_id)
    channel = req_enum(body, "channel", CHANNELS)
    author_id = req_str(body, "author_employee_id")
    body_text = body.get("body_text")
    if not isinstance(body_text, str):
        fail("ERR_INVALID_REQUEST", 400, "body_text must be a string")
    policy = S.active_lexicon_policy()
    score, matched, ver = S.lexicon_score(body_text, policy)
    item = new_resource()
    item.update({"channel": channel, "author_employee_id": author_id, "body_text": body_text,
                 "captured_at": now(), "score": score, "matched_terms": matched,
                 "scored_policy_version": ver, "status": "QUEUED"})
    db["comm_items"][item["id"]] = item
    # auto-tiering at capture: >=100 ESCALATED (+case), 40..99 QUEUED, <40 CLEARED
    if score >= 100:
        S.escalate_comm_item(item)
    elif score < 40:
        item["status"] = "CLEARED"
    return ok(S.ser_comm_item(item), status=201)


@bp.post("/comm-review-items/<rid>/transition")
def comm_item_transition(rid):
    uid, body = require_transition_roles(
        {"IN_REVIEW": {"SurveillanceAnalyst"}, "CLEARED": {"SurveillanceAnalyst"},
         "ESCALATED": {"SurveillanceAnalyst"}})
    item = get_or_404("comm_items", rid)
    to = req_enum(body, "to_status", {"IN_REVIEW", "CLEARED", "ESCALATED"})
    allowed_from = {"IN_REVIEW": {"QUEUED"}, "CLEARED": {"QUEUED", "IN_REVIEW"},
                    "ESCALATED": {"QUEUED", "IN_REVIEW"}}
    if item["status"] not in allowed_from[to]:
        fail("ERR_INVALID_STATE", 409,
             "comm item status %s does not admit transition to %s" % (item["status"], to))
    if to == "ESCALATED":
        S.escalate_comm_item(item)  # opens a COMM_REVIEW case on the author
    else:
        item["status"] = to
    bump(item)
    return ok(S.ser_comm_item(item))


# ==================================================================
# Lexicon policies
# ==================================================================
def validate_terms(v):
    if not isinstance(v, list):
        fail("ERR_INVALID_REQUEST", 400, "terms must be an array")
    for entry in v:
        if not isinstance(entry, dict):
            fail("ERR_INVALID_REQUEST", 400, "terms entries must be objects")
        term = entry.get("term")
        weight = entry.get("weight")
        if not isinstance(term, str) or term == "":
            fail("ERR_INVALID_REQUEST", 400, "term must be a non-empty string")
        if isinstance(weight, bool) or not isinstance(weight, int) or not (1 <= weight <= 100):
            fail("ERR_INVALID_REQUEST", 400, "weight must be an integer between 1 and 100")
    return v


@bp.post("/lexicon-policies")
def create_lexicon():
    require_roles("ComplianceAdmin")
    body = get_body()
    name = req_str(body, "name")
    terms = validate_terms(body.get("terms"))
    p = new_resource()
    p.update({"name": name, "terms": terms, "status": "DRAFT"})
    db["lexicon"][p["id"]] = p
    return ok(S.ser_lexicon(p), status=201)


@bp.get("/lexicon-policies/<rid>")
def get_lexicon(rid):
    require_any_role()
    return ok(S.ser_lexicon(get_or_404("lexicon", rid)))


@bp.patch("/lexicon-policies/<rid>")
def patch_lexicon(rid):
    require_roles("ComplianceAdmin")
    p = get_or_404("lexicon", rid)
    body = get_body()
    expected = req_int(body, "expected_lexicon_policy_version")
    new_terms = None
    if "terms" in body and body["terms"] is not None:
        new_terms = validate_terms(body["terms"])
    to_status = None
    if "to_status" in body and body["to_status"] is not None:
        to_status = req_enum(body, "to_status", {"ACTIVE", "RETIRED"})
    # OCC (priority 8) precedes state admissibility (priority 9)
    if expected != p["version"]:
        fail("ERR_STALE_VERSION", 412, "expected_lexicon_policy_version does not match current version")
    if p["status"] == "RETIRED":
        fail("ERR_INVALID_STATE", 409, "retired lexicon policies admit no transitions")
    if to_status == "ACTIVE" and p["status"] != "DRAFT":
        fail("ERR_INVALID_STATE", 409, "only a DRAFT policy can be activated")
    if to_status == "RETIRED" and p["status"] != "ACTIVE":
        fail("ERR_INVALID_STATE", 409, "only the ACTIVE policy can be retired")
    if new_terms is not None:
        p["terms"] = new_terms
    active_set_changed = False
    if to_status == "ACTIVE":
        # at most one ACTIVE policy fleet-wide: retire the predecessor
        for other in db["lexicon"].values():
            if other["id"] != p["id"] and other["status"] == "ACTIVE":
                other["status"] = "RETIRED"
                bump(other)
        p["status"] = "ACTIVE"
        active_set_changed = True
    elif to_status == "RETIRED":
        p["status"] = "RETIRED"
        active_set_changed = True
    bump(p)
    # rescore cascade: on activation/retirement, or on a terms retune of the ACTIVE policy
    if active_set_changed or (new_terms is not None and p["status"] == "ACTIVE"):
        S.rescore_queued_comm_items()
    return ok(S.ser_lexicon(p))


# ==================================================================
# Compliance policies + training
# ==================================================================
@bp.post("/compliance-policies")
def create_policy():
    require_roles("ComplianceAdmin")
    body = get_body()
    policy_code = req_str(body, "policy_code")
    title = req_str(body, "title")
    version_label = req_str(body, "version_label")
    p = new_resource()
    p.update({"policy_code": policy_code, "title": title, "version_label": version_label,
              "status": "DRAFT"})
    db["policies"][p["id"]] = p
    return ok(S.ser_policy(p), status=201)


@bp.get("/compliance-policies/<rid>")
def get_policy(rid):
    require_any_role()
    return ok(S.ser_policy(get_or_404("policies", rid)))


@bp.post("/compliance-policies/<rid>/publish")
def publish_policy(rid):
    require_roles("ComplianceAdmin")
    p = get_or_404("policies", rid)
    if p["status"] != "DRAFT":
        fail("ERR_INVALID_STATE", 409, "only DRAFT policies can be published")
    prior = None
    for other in db["policies"].values():
        if (other["id"] != p["id"] and other["policy_code"] == p["policy_code"]
                and other["status"] == "EFFECTIVE"):
            prior = other
            break
    if prior is not None:
        prior["status"] = "SUPERSEDED"
        bump(prior)
    p["status"] = "EFFECTIVE"
    bump(p)
    # fan-out: one assignment per ACTIVE employee, due publish instant + 30 days
    due = now() + timedelta(days=30)
    for e in db["employees"].values():
        if e["employment_status"] != "ACTIVE":
            continue
        ta = new_resource()
        ta.update({"employee_id": e["id"], "policy_id": p["id"], "due_date": due,
                   "status": "ASSIGNED", "completed_at": None})
        db["training"][ta["id"]] = ta
    # compensation: superseded policy's non-terminal assignments are cancelled
    if prior is not None:
        for ta in db["training"].values():
            if ta["policy_id"] == prior["id"] and ta["status"] in ("ASSIGNED", "OVERDUE"):
                ta["status"] = "CANCELLED"
                bump(ta)
    return ok(S.ser_policy(p))


@bp.get("/training-assignments")
def list_training():
    require_any_role()
    rows = list(db["training"].values())
    for f in ("employee_id", "policy_id", "status"):
        rows = filter_param(rows, f, request.args.get(f))
    return list_response(rows, S.ser_training)


@bp.get("/training-assignments/<rid>")
def get_training(rid):
    require_any_role()
    return ok(S.ser_training(get_or_404("training", rid)))


@bp.post("/training-assignments/<rid>/complete")
def complete_training(rid):
    uid = require_roles("CoveredEmployee")
    ta = get_or_404("training", rid)
    if uid != ta["employee_id"]:
        fail("ERR_NOT_RESOURCE_OWNER", 403, "only the assigned employee may complete the assignment")
    if ta["status"] not in ("ASSIGNED", "OVERDUE"):
        fail("ERR_INVALID_STATE", 409,
             "assignment status %s does not admit completion" % ta["status"])
    ta["status"] = "COMPLETED"
    ta["completed_at"] = now()
    bump(ta)
    return ok(S.ser_training(ta))
