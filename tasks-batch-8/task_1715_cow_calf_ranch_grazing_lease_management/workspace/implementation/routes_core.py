"""Routes: clock, ranches, pastures, leases, statements, herd groups, drought.

Validation cascade per PRD §2.8 is applied in order on every endpoint:
auth(1-3) -> existence(4) -> body(5) -> state(6-8) -> OCC(9) -> business(10-20).
"""
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from flask import Blueprint, request

from core import (
    CLOCK, db, ApiError,
    success_envelope, paginate, require_ctx,
    get_body, check_allowed_fields, req_field, req_int, opt_int,
    req_str, req_enum, req_date, parse_iso8601,
    new_record, touch, dec,
    err_not_found, err_invalid_request, err_invalid_state, err_already_terminal,
)
from domain import (
    REDUCTION_REASONS,
    refresh_pasture, refresh_lease, lease_usage, lease_charges,
    assessment_figures, destock_required_reduction,
    flip_groups_to_destocking, release_groups_from_destocking,
    ranch_out, pasture_out, lease_out, statement_out, herd_group_out,
    assessment_out, destock_order_out,
)

bp = Blueprint("core_routes", __name__)

RM = ["RanchManager"]
RG = ["RangeManager"]
HM = ["HerdManager"]
SA = ["SalesAgent"]
ALL = ["RanchManager", "RangeManager", "HerdManager", "SalesAgent"]


# ===========================================================================
# Clock
# ===========================================================================
@bp.post("/api/_clock/set_current_utc")
def set_clock():
    require_ctx(RM)
    body = get_body()
    check_allowed_fields(body, {"to_iso8601"})
    raw = req_str(body, "to_iso8601")
    try:
        dt = parse_iso8601(raw)
    except (ValueError, TypeError):
        raise err_invalid_request("to_iso8601 must be an ISO-8601 timestamp")
    CLOCK.set(dt)
    cur = dt.strftime("%Y-%m-%dT%H:%M:%S")
    ms = dt.microsecond // 1000
    current_utc = f"{cur}.{ms:03d}Z"
    return success_envelope({"current_utc": current_utc})


# ===========================================================================
# Ranches
# ===========================================================================
@bp.post("/api/ranches")
def create_ranch():
    require_ctx(RM)
    body = get_body()
    check_allowed_fields(body, {"name", "hq_state", "destock_grace_days"})
    name = req_str(body, "name")
    hq_state = req_str(body, "hq_state")
    grace = opt_int(body, "destock_grace_days", default=30)
    r = new_record()
    r.update({
        "name": name, "hq_state": hq_state, "destock_grace_days": grace,
        "drought_posture": "NORMAL", "ranch_production_pct": 100.0,
        "assessment_seq": 0,
    })
    db.ranches[r["id"]] = r
    return success_envelope(ranch_out(r), status=201)


@bp.get("/api/ranches/<rid>")
def get_ranch(rid):
    require_ctx(ALL)
    r = db.ranches.get(rid)
    if not r:
        raise err_not_found()
    return success_envelope(ranch_out(r))


@bp.patch("/api/ranches/<rid>")
def patch_ranch(rid):
    require_ctx(RM)
    r = db.ranches.get(rid)
    if not r:
        raise err_not_found()
    body = get_body()
    check_allowed_fields(body, {"name", "hq_state", "destock_grace_days"})
    if "name" in body:
        r["name"] = req_str(body, "name")
    if "hq_state" in body:
        r["hq_state"] = req_str(body, "hq_state")
    if "destock_grace_days" in body:
        r["destock_grace_days"] = opt_int(body, "destock_grace_days")
    touch(r)
    return success_envelope(ranch_out(r))


# ===========================================================================
# Pastures
# ===========================================================================
@bp.post("/api/pastures")
def create_pasture():
    require_ctx(RG)
    body = get_body()
    check_allowed_fields(body, {"ranch_id", "name", "acreage", "tenure", "forage_type",
                                "base_capacity_aum", "min_rest_days"})
    ranch_id = req_str(body, "ranch_id")
    ranch = db.ranches.get(ranch_id)
    if not ranch:
        raise err_not_found("ranch_id does not exist")
    name = req_str(body, "name")
    acreage = req_int(body, "acreage", positive=True)
    tenure = req_enum(body, "tenure", {"DEEDED", "LEASED"})
    forage = req_enum(body, "forage_type", {"NATIVE_RANGE", "IMPROVED", "CROP_RESIDUE"})
    base_cap = req_int(body, "base_capacity_aum", positive=True)
    min_rest = opt_int(body, "min_rest_days", default=45, nonneg=True)
    p = new_record()
    p.update({
        "ranch_id": ranch_id, "name": name, "acreage": acreage, "tenure": tenure,
        "forage_type": forage, "base_capacity_aum": base_cap, "min_rest_days": min_rest,
        "resting_until": None, "closed_flag": False,
        "effective_capacity_aum": 0, "committed_aum": 0, "consumed_total_aum": 0,
        "available_aum": 0, "condition_status": "GRAZEABLE",
    })
    db.pastures[p["id"]] = p
    refresh_pasture(p)
    return success_envelope(pasture_out(p), status=201)


@bp.get("/api/pastures/<pid>")
def get_pasture(pid):
    require_ctx(ALL)
    p = db.pastures.get(pid)
    if not p:
        raise err_not_found()
    return success_envelope(pasture_out(p))


@bp.get("/api/pastures")
def list_pastures():
    require_ctx(ALL)
    args = request.args
    items = list(db.pastures.values())
    if args.get("ranch_id"):
        items = [p for p in items if p["ranch_id"] == args["ranch_id"]]
    if args.get("tenure"):
        items = [p for p in items if p["tenure"] == args["tenure"]]
    # condition_status filter applied to recomputed values
    for p in items:
        refresh_pasture(p)
    if args.get("condition_status"):
        items = [p for p in items if p["condition_status"] == args["condition_status"]]
    window, pg = paginate(items)
    return success_envelope([pasture_out(p) for p in window], response_type="array", pagination=pg)


@bp.post("/api/pastures/<pid>/close")
def close_pasture(pid):
    require_ctx(RG)
    p = db.pastures.get(pid)
    if not p:
        raise err_not_found()
    get_body(required=False)
    if p.get("closed_flag"):
        raise err_already_terminal("Pasture is already CLOSED")
    for a in db.grazing_assignments.values():
        if a["pasture_id"] == pid and a["assignment_status"] == "ACTIVE":
            raise ApiError("ERR_INVALID_STATE_TRANSITION",
                           "Pasture has an ACTIVE assignment", 400)
    p["closed_flag"] = True
    touch(p)
    return success_envelope(pasture_out(p))


# ===========================================================================
# Grazing leases
# ===========================================================================
LEASE_AMENDABLE = {"aum_allotment", "rate_per_aum_cents", "minimum_commit_aum",
                   "overage_tier1_cap_aum", "overage_tier1_rate_cents",
                   "overage_tier2_rate_cents", "settlement_basis", "start_date", "end_date"}


def _capacity_check(pasture: dict, candidate: dict):
    """Priority 15: aggregate ACTIVE allotments incl. candidate <= base_capacity."""
    total = Decimal("0")
    for l in db.grazing_leases.values():
        if l["pasture_id"] != pasture["id"]:
            continue
        refresh_lease(l)
        if l["lease_status"] == "ACTIVE" and l["id"] != candidate["id"]:
            total += dec(l["aum_allotment"])
    total += dec(candidate["aum_allotment"])
    if total > dec(pasture["base_capacity_aum"]):
        raise ApiError("ERR_LEASE_CAPACITY_EXCEEDED",
                       "Aggregate ACTIVE lease allotments exceed base_capacity_aum", 422)


@bp.post("/api/grazing-leases")
def create_lease():
    require_ctx(RG)
    body = get_body()
    allowed = {"ranch_id", "pasture_id", "lessor_name", "start_date", "end_date",
               "aum_allotment", "rate_per_aum_cents", "minimum_commit_aum",
               "overage_tier1_cap_aum", "overage_tier1_rate_cents",
               "overage_tier2_rate_cents", "settlement_basis"}
    check_allowed_fields(body, allowed)
    ranch_id = req_str(body, "ranch_id")
    pasture_id = req_str(body, "pasture_id")
    ranch = db.ranches.get(ranch_id)
    if not ranch:
        raise err_not_found("ranch_id does not exist")
    pasture = db.pastures.get(pasture_id)
    if not pasture or pasture["ranch_id"] != ranch_id:
        raise err_not_found("pasture_id does not exist on this ranch")
    lessor = req_str(body, "lessor_name")
    start = req_date(body, "start_date")
    end = req_date(body, "end_date")
    allotment = req_int(body, "aum_allotment", positive=True)
    rate = req_int(body, "rate_per_aum_cents", nonneg=True)
    min_commit = req_int(body, "minimum_commit_aum", nonneg=True)
    t1cap = req_int(body, "overage_tier1_cap_aum", nonneg=True)
    t1rate = req_int(body, "overage_tier1_rate_cents", nonneg=True)
    t2rate = req_int(body, "overage_tier2_rate_cents", nonneg=True)
    basis = req_enum(body, "settlement_basis", {"ALLOTMENT", "ACTUAL_USE"})
    if start > end:
        raise err_invalid_request("start_date must precede or equal end_date")
    if pasture["tenure"] != "LEASED":
        raise err_invalid_request("A grazing lease may only be written against LEASED pasture")
    l = new_record()
    l.update({
        "ranch_id": ranch_id, "pasture_id": pasture_id, "lessor_name": lessor,
        "start_date": start, "end_date": end, "aum_allotment": allotment,
        "rate_per_aum_cents": rate, "minimum_commit_aum": min_commit,
        "overage_tier1_cap_aum": t1cap, "overage_tier1_rate_cents": t1rate,
        "overage_tier2_rate_cents": t2rate, "settlement_basis": basis,
        "lease_status": "DRAFT",
    })
    db.grazing_leases[l["id"]] = l
    return success_envelope(lease_out(l), status=201)


@bp.get("/api/grazing-leases/<lid>")
def get_lease(lid):
    require_ctx(ALL)
    l = db.grazing_leases.get(lid)
    if not l:
        raise err_not_found()
    return success_envelope(lease_out(l))


@bp.get("/api/grazing-leases")
def list_leases():
    require_ctx(ALL)
    args = request.args
    items = list(db.grazing_leases.values())
    for l in items:
        refresh_lease(l)
    if args.get("ranch_id"):
        items = [l for l in items if l["ranch_id"] == args["ranch_id"]]
    if args.get("pasture_id"):
        items = [l for l in items if l["pasture_id"] == args["pasture_id"]]
    if args.get("lease_status"):
        items = [l for l in items if l["lease_status"] == args["lease_status"]]
    window, pg = paginate(items)
    return success_envelope([lease_out(l) for l in window], response_type="array", pagination=pg)


@bp.patch("/api/grazing-leases/<lid>")
def amend_lease(lid):
    require_ctx(RG)
    l = db.grazing_leases.get(lid)
    if not l:
        raise err_not_found()
    refresh_lease(l)
    body = get_body()
    check_allowed_fields(body, LEASE_AMENDABLE | {"expected_lease_version"})
    # body well-formedness (priority 5) — OCC field is non-optional (PRD §2.7)
    if "expected_lease_version" not in body or body["expected_lease_version"] is None:
        raise err_invalid_request("expected_lease_version is required")
    ev = body["expected_lease_version"]
    if isinstance(ev, bool) or not isinstance(ev, int):
        raise err_invalid_request("expected_lease_version must be an integer")
    # generic state / terminal checks (priorities 6-7)
    if l["lease_status"] in ("EXPIRED", "TERMINATED"):
        raise err_already_terminal("Lease in terminal state rejects amendment")
    if l["lease_status"] not in ("DRAFT", "ACTIVE", "SUSPENDED"):
        raise err_invalid_state("Lease may be amended only in DRAFT, ACTIVE or SUSPENDED")
    # OCC (priority 9)
    if ev != l["version"]:
        raise ApiError("ERR_STALE_VERSION", "expected_lease_version does not match current version", 412)
    # validate new values
    new_start = l["start_date"]
    new_end = l["end_date"]
    if "start_date" in body:
        new_start = req_date(body, "start_date")
    if "end_date" in body:
        new_end = req_date(body, "end_date")
    if new_start > new_end:
        raise err_invalid_request("start_date must precede or equal end_date")
    for f in ("aum_allotment", "rate_per_aum_cents", "minimum_commit_aum",
              "overage_tier1_cap_aum", "overage_tier1_rate_cents", "overage_tier2_rate_cents"):
        if f in body and body[f] is not None:
            v = body[f]
            if isinstance(v, bool) or not isinstance(v, int):
                raise err_invalid_request(f"Field {f} must be an integer")
    if "settlement_basis" in body and body["settlement_basis"] is not None:
        if body["settlement_basis"] not in ("ALLOTMENT", "ACTUAL_USE"):
            raise err_invalid_request("settlement_basis must be ALLOTMENT or ACTUAL_USE")
    # amendment floor (priority 16)
    new_allotment = body.get("aum_allotment", l["aum_allotment"])
    max_used = None
    for s in db.lease_statements.values():
        if s["lease_id"] == lid and s["statement_status"] != "DRAFT":
            used = dec(s["actual_aum_used"])
            if max_used is None or used > max_used:
                max_used = used
    if max_used is not None and dec(new_allotment) < max_used:
        raise ApiError("ERR_ALLOTMENT_BELOW_RECORDED_USAGE",
                       "New aum_allotment below recorded usage on non-DRAFT statements", 422)
    # apply
    for f in ("aum_allotment", "rate_per_aum_cents", "minimum_commit_aum",
              "overage_tier1_cap_aum", "overage_tier1_rate_cents", "overage_tier2_rate_cents",
              "settlement_basis"):
        if f in body and body[f] is not None:
            l[f] = body[f]
    l["start_date"] = new_start
    l["end_date"] = new_end
    touch(l)
    return success_envelope(lease_out(l))


@bp.post("/api/grazing-leases/<lid>/activate")
def activate_lease(lid):
    require_ctx(RG)
    l = db.grazing_leases.get(lid)
    if not l:
        raise err_not_found()
    get_body(required=False)
    refresh_lease(l)
    if l["lease_status"] in ("EXPIRED", "TERMINATED"):
        raise err_already_terminal("Lease in terminal state")
    if l["lease_status"] != "DRAFT":
        raise err_invalid_state("Only a DRAFT lease may be activated")
    pasture = db.pastures.get(l["pasture_id"])
    if not pasture or pasture["tenure"] != "LEASED":
        raise ApiError("ERR_LEASE_NOT_ACTIVE", "Lease pasture missing or not LEASED", 400)
    refresh_pasture(pasture)
    if pasture["condition_status"] == "CLOSED":
        raise ApiError("ERR_PASTURE_NOT_GRAZEABLE", "Pasture is CLOSED", 400)
    _capacity_check(pasture, l)
    l["lease_status"] = "ACTIVE"
    touch(l)
    return success_envelope(lease_out(l))


@bp.post("/api/grazing-leases/<lid>/suspend")
def suspend_lease(lid):
    require_ctx(RG)
    l = db.grazing_leases.get(lid)
    if not l:
        raise err_not_found()
    get_body(required=False)
    refresh_lease(l)
    if l["lease_status"] in ("EXPIRED", "TERMINATED"):
        raise err_already_terminal("Lease in terminal state")
    if l["lease_status"] != "ACTIVE":
        raise err_invalid_state("Only an ACTIVE lease may be suspended")
    l["lease_status"] = "SUSPENDED"
    touch(l)
    return success_envelope(lease_out(l))


@bp.post("/api/grazing-leases/<lid>/reinstate")
def reinstate_lease(lid):
    require_ctx(RG)
    l = db.grazing_leases.get(lid)
    if not l:
        raise err_not_found()
    get_body(required=False)
    refresh_lease(l)
    if l["lease_status"] in ("EXPIRED", "TERMINATED"):
        raise err_already_terminal("Lease in terminal state")
    if l["lease_status"] != "SUSPENDED":
        raise err_invalid_state("Only a SUSPENDED lease may be reinstated")
    pasture = db.pastures.get(l["pasture_id"])
    _capacity_check(pasture, l)
    l["lease_status"] = "ACTIVE"
    touch(l)
    return success_envelope(lease_out(l))


@bp.post("/api/grazing-leases/<lid>/terminate")
def terminate_lease(lid):
    require_ctx(RM)
    l = db.grazing_leases.get(lid)
    if not l:
        raise err_not_found()
    get_body(required=False)
    refresh_lease(l)
    if l["lease_status"] in ("EXPIRED", "TERMINATED"):
        raise err_already_terminal("Lease in terminal state")
    for s in db.lease_statements.values():
        if s["lease_id"] == lid and s["statement_status"] in ("DRAFT", "ISSUED"):
            raise err_invalid_state("Lease has a statement in DRAFT or ISSUED")
    l["lease_status"] = "TERMINATED"
    touch(l)
    return success_envelope(lease_out(l))


# ===========================================================================
# Lease statements
# ===========================================================================
@bp.post("/api/lease-statements")
def create_statement():
    ctx = require_ctx(RG)
    body = get_body()
    check_allowed_fields(body, {"lease_id", "ranch_id", "period_year"})
    lease_id = req_str(body, "lease_id")
    ranch_id = req_str(body, "ranch_id")
    lease = db.grazing_leases.get(lease_id)
    if not lease:
        raise err_not_found("lease_id does not exist")
    ranch = db.ranches.get(ranch_id)
    if not ranch or lease["ranch_id"] != ranch_id:
        raise err_not_found("ranch_id does not exist or does not match the lease")
    period_year = req_int(body, "period_year")
    if period_year < lease["start_date"].year or period_year > lease["end_date"].year:
        raise err_invalid_request("period_year must fall within the lease window years")
    refresh_lease(lease)
    if lease["lease_status"] in ("DRAFT", "TERMINATED"):
        raise ApiError("ERR_LEASE_NOT_ACTIVE", "Lease must be ACTIVE, SUSPENDED or EXPIRED for statement generation", 400)
    for s in db.lease_statements.values():
        if s["lease_id"] == lease_id and s["period_year"] == period_year:
            raise ApiError("ERR_DUPLICATE_STATEMENT_PERIOD",
                           "A statement already exists for this lease and period_year", 409)
    actual = lease_usage(lease, period_year)
    base, overage, total = lease_charges(lease, actual)
    s = new_record()
    s.update({
        "lease_id": lease_id, "ranch_id": ranch_id, "period_year": period_year,
        "actual_aum_used": actual, "base_charge_cents": base,
        "overage_charge_cents": overage, "total_due_cents": total,
        "recorded_by_user_id": ctx.user_id, "approved_by_user_id": None,
        "statement_status": "DRAFT",
    })
    db.lease_statements[s["id"]] = s
    return success_envelope(statement_out(s), status=201)


@bp.get("/api/lease-statements/<sid>")
def get_statement(sid):
    require_ctx(ALL)
    s = db.lease_statements.get(sid)
    if not s:
        raise err_not_found()
    return success_envelope(statement_out(s))


@bp.get("/api/lease-statements")
def list_statements():
    require_ctx(ALL)
    args = request.args
    items = list(db.lease_statements.values())
    if args.get("lease_id"):
        items = [s for s in items if s["lease_id"] == args["lease_id"]]
    if args.get("ranch_id"):
        items = [s for s in items if s["ranch_id"] == args["ranch_id"]]
    if args.get("statement_status"):
        items = [s for s in items if s["statement_status"] == args["statement_status"]]
    if args.get("period_year"):
        try:
            py = int(args["period_year"])
            items = [s for s in items if s["period_year"] == py]
        except ValueError:
            items = []
    window, pg = paginate(items)
    return success_envelope([statement_out(s) for s in window], response_type="array", pagination=pg)


@bp.post("/api/lease-statements/<sid>/issue")
def issue_statement(sid):
    require_ctx(RG)
    s = db.lease_statements.get(sid)
    if not s:
        raise err_not_found()
    get_body(required=False)
    if s["statement_status"] == "PAID":
        raise err_already_terminal("Statement is PAID")
    if s["statement_status"] != "DRAFT":
        raise err_invalid_state("Only a DRAFT statement may be issued")
    s["statement_status"] = "ISSUED"
    touch(s)
    return success_envelope(statement_out(s))


@bp.post("/api/lease-statements/<sid>/approve")
def approve_statement(sid):
    ctx = require_ctx(RM)
    s = db.lease_statements.get(sid)
    if not s:
        raise err_not_found()
    get_body(required=False)
    # segregation of duties (priority 3)
    if ctx.user_id == s["recorded_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "Approver must differ from recorded_by_user_id", 403)
    if s["statement_status"] == "PAID":
        raise err_already_terminal("Statement is PAID")
    if s["statement_status"] != "ISSUED":
        raise err_invalid_state("Only an ISSUED statement may be approved")
    s["statement_status"] = "APPROVED"
    s["approved_by_user_id"] = ctx.user_id
    touch(s)
    return success_envelope(statement_out(s))


@bp.post("/api/lease-statements/<sid>/mark-paid")
def mark_paid_statement(sid):
    require_ctx(RM)
    s = db.lease_statements.get(sid)
    if not s:
        raise err_not_found()
    get_body(required=False)
    if s["statement_status"] == "PAID":
        raise err_already_terminal("Statement is PAID")
    if s["statement_status"] != "APPROVED":
        raise err_invalid_state("Only an APPROVED statement may be marked paid")
    s["statement_status"] = "PAID"
    touch(s)
    return success_envelope(statement_out(s))


# ===========================================================================
# Herd groups
# ===========================================================================
@bp.post("/api/herd-groups")
def create_herd_group():
    require_ctx(HM)
    body = get_body()
    check_allowed_fields(body, {"ranch_id", "group_name", "animal_class", "head_count", "avg_weight_lbs"})
    ranch_id = req_str(body, "ranch_id")
    ranch = db.ranches.get(ranch_id)
    if not ranch:
        raise err_not_found("ranch_id does not exist")
    gname = req_str(body, "group_name")
    aclass = req_enum(body, "animal_class", {"MATURE_COW", "REPLACEMENT_HEIFER", "GROWING"})
    head = req_int(body, "head_count", nonneg=True)
    weight = req_int(body, "avg_weight_lbs", positive=True)
    g = new_record()
    g.update({
        "ranch_id": ranch_id, "group_name": gname, "animal_class": aclass,
        "head_count": head, "avg_weight_lbs": weight,
        "marked_open_head": 0, "retained_from_crop_id": None,
        "group_status": "ACTIVE",
    })
    db.herd_groups[g["id"]] = g
    return success_envelope(herd_group_out(g), status=201)


@bp.get("/api/herd-groups/<gid>")
def get_herd_group(gid):
    require_ctx(ALL)
    g = db.herd_groups.get(gid)
    if not g:
        raise err_not_found()
    return success_envelope(herd_group_out(g))


@bp.get("/api/herd-groups")
def list_herd_groups():
    require_ctx(ALL)
    args = request.args
    items = list(db.herd_groups.values())
    if args.get("ranch_id"):
        items = [g for g in items if g["ranch_id"] == args["ranch_id"]]
    if args.get("animal_class"):
        items = [g for g in items if g["animal_class"] == args["animal_class"]]
    if args.get("group_status"):
        items = [g for g in items if g["group_status"] == args["group_status"]]
    if args.get("retained_from_crop_id"):
        items = [g for g in items if g.get("retained_from_crop_id") == args["retained_from_crop_id"]]
    window, pg = paginate(items)
    return success_envelope([herd_group_out(g) for g in window], response_type="array", pagination=pg)


@bp.post("/api/herd-groups/<gid>/reductions")
def herd_reduction(gid):
    require_ctx(HM)
    g = db.herd_groups.get(gid)
    if not g:
        raise err_not_found()
    body = get_body()
    check_allowed_fields(body, {"head_count", "reason", "destock_order_id"})
    head = req_int(body, "head_count", positive=True)
    reason = req_enum(body, "reason", REDUCTION_REASONS)
    order_id = body.get("destock_order_id")
    order = None
    if order_id is not None:
        if not isinstance(order_id, str):
            raise err_invalid_request("destock_order_id must be a string")
        order = db.destock_orders.get(order_id)
        if not order or order["ranch_id"] != g["ranch_id"]:
            raise err_not_found("destock_order_id does not exist on this ranch")
    if g["group_status"] == "LIQUIDATED":
        raise err_already_terminal("HerdGroup is LIQUIDATED")
    if reason == "LIQUIDATION":
        if head != g["head_count"]:
            raise ApiError("ERR_DESTOCK_REDUCTION_EXCEEDS_HEAD",
                           "LIQUIDATION must take the group's full remaining head", 422)
    elif head > g["head_count"]:
        raise ApiError("ERR_DESTOCK_REDUCTION_EXCEEDS_HEAD",
                       "reduction head_count exceeds group head_count", 422)
    g["head_count"] -= head
    if reason == "LIQUIDATION":
        g["group_status"] = "LIQUIDATED"
    touch(g)
    if order is not None and order["order_status"] in ("OPEN", "EXPIRED"):
        order["received_reduction_head"] += head
        touch(order)
    return success_envelope(herd_group_out(g))


# ===========================================================================
# Drought assessments
# ===========================================================================
@bp.post("/api/drought-assessments")
def create_assessment():
    require_ctx(RG)
    body = get_body()
    check_allowed_fields(body, {"ranch_id", "assessment_date", "pasture_measurements"})
    ranch_id = req_str(body, "ranch_id")
    ranch = db.ranches.get(ranch_id)
    if not ranch:
        raise err_not_found("ranch_id does not exist")
    a_date = req_date(body, "assessment_date")
    measurements = req_field(body, "pasture_measurements")
    if not isinstance(measurements, list):
        raise err_invalid_request("pasture_measurements must be an array")
    # measurement completeness (priority 18)
    open_pastures = [p for p in db.pastures.values()
                     if p["ranch_id"] == ranch_id and not p.get("closed_flag")]
    open_ids = {p["id"] for p in open_pastures}
    seen = set()
    normalized = []
    for m in measurements:
        if not isinstance(m, dict) or "pasture_id" not in m or "production_pct_of_normal" not in m:
            raise ApiError("ERR_ASSESSMENT_MEASUREMENT_INCOMPLETE",
                           "Each measurement must carry pasture_id and production_pct_of_normal", 422)
        pid = m["pasture_id"]
        pct = m["production_pct_of_normal"]
        if pid not in open_ids:
            raise ApiError("ERR_ASSESSMENT_MEASUREMENT_INCOMPLETE",
                           "pasture_measurements references an unknown or closed pasture", 422)
        if pid in seen:
            raise ApiError("ERR_ASSESSMENT_MEASUREMENT_INCOMPLETE",
                           "pasture_measurements duplicates a pasture", 422)
        if isinstance(pct, bool) or not isinstance(pct, (int, float)):
            raise ApiError("ERR_ASSESSMENT_MEASUREMENT_INCOMPLETE",
                           "production_pct_of_normal must be a number", 422)
        seen.add(pid)
        normalized.append({"pasture_id": pid, "production_pct_of_normal": pct})
    if seen != open_ids:
        raise ApiError("ERR_ASSESSMENT_MEASUREMENT_INCOMPLETE",
                       "pasture_measurements must cover every non-closed pasture exactly once", 422)
    ranch_pct, posture, supply, demand, deficit = assessment_figures(ranch, normalized)
    a = new_record()
    a.update({
        "ranch_id": ranch_id, "assessment_date": a_date,
        "pasture_measurements": normalized,
        "ranch_production_pct": ranch_pct, "monthly_supply_aum": supply,
        "monthly_demand_aum": demand, "deficit_aum_per_30d": deficit,
        "resulting_posture": posture, "assessment_status": "DRAFT",
    })
    db.drought_assessments[a["id"]] = a
    return success_envelope(assessment_out(a), status=201)


@bp.get("/api/drought-assessments/<aid>")
def get_assessment(aid):
    require_ctx(ALL)
    a = db.drought_assessments.get(aid)
    if not a:
        raise err_not_found()
    return success_envelope(assessment_out(a))


@bp.get("/api/drought-assessments")
def list_assessments():
    require_ctx(ALL)
    args = request.args
    items = list(db.drought_assessments.values())
    if args.get("ranch_id"):
        items = [a for a in items if a["ranch_id"] == args["ranch_id"]]
    if args.get("assessment_status"):
        items = [a for a in items if a["assessment_status"] == args["assessment_status"]]
    window, pg = paginate(items)
    return success_envelope([assessment_out(a) for a in window], response_type="array", pagination=pg)


@bp.post("/api/drought-assessments/<aid>/finalize")
def finalize_assessment(aid):
    require_ctx(RG)
    a = db.drought_assessments.get(aid)
    if not a:
        raise err_not_found()
    body = get_body()
    check_allowed_fields(body, {"expected_ranch_version"})
    ranch = db.ranches.get(a["ranch_id"])
    if "expected_ranch_version" not in body or body["expected_ranch_version"] is None:
        raise err_invalid_request("expected_ranch_version is required")
    ev = body["expected_ranch_version"]
    if isinstance(ev, bool) or not isinstance(ev, int):
        raise err_invalid_request("expected_ranch_version must be an integer")
    if a["assessment_status"] == "FINALIZED":
        raise err_already_terminal("Assessment is FINALIZED")
    if ev != ranch["version"]:
        raise ApiError("ERR_STALE_VERSION", "expected_ranch_version does not match current ranch version", 412)
    a["assessment_status"] = "FINALIZED"
    touch(a)
    ranch["drought_posture"] = a["resulting_posture"]
    ranch["ranch_production_pct"] = a["ranch_production_pct"]
    ranch["assessment_seq"] += 1
    touch(ranch)
    # deficit strictly > 0 => create DestockOrder + flip ACTIVE groups to DESTOCKING
    if dec(a["deficit_aum_per_30d"]) > 0:
        required = destock_required_reduction(ranch, dec(a["deficit_aum_per_30d"]))
        o = new_record()
        o.update({
            "ranch_id": ranch["id"], "drought_assessment_id": a["id"],
            "required_reduction_head": required, "received_reduction_head": 0,
            "deadline_date": a["assessment_date"] + timedelta(days=ranch["destock_grace_days"]),
            "waiver_note": None, "order_status": "OPEN",
        })
        db.destock_orders[o["id"]] = o
        flip_groups_to_destocking(ranch["id"])
    return success_envelope(assessment_out(a))


# ===========================================================================
# Destock orders
# ===========================================================================
@bp.get("/api/destock-orders/<oid>")
def get_destock_order(oid):
    require_ctx(ALL)
    o = db.destock_orders.get(oid)
    if not o:
        raise err_not_found()
    return success_envelope(destock_order_out(o))


@bp.get("/api/destock-orders")
def list_destock_orders():
    require_ctx(ALL)
    args = request.args
    items = list(db.destock_orders.values())
    if args.get("ranch_id"):
        items = [o for o in items if o["ranch_id"] == args["ranch_id"]]
    if args.get("drought_assessment_id"):
        items = [o for o in items if o["drought_assessment_id"] == args["drought_assessment_id"]]
    if args.get("order_status"):
        items = [o for o in items if o["order_status"] == args["order_status"]]
    window, pg = paginate(items)
    return success_envelope([destock_order_out(o) for o in window], response_type="array", pagination=pg)


@bp.post("/api/destock-orders/<oid>/verify-compliance")
def verify_compliance(oid):
    require_ctx(RG)
    o = db.destock_orders.get(oid)
    if not o:
        raise err_not_found()
    get_body(required=False)
    if o["order_status"] in ("COMPLIANT", "WAIVED"):
        raise err_already_terminal("Order is already resolved")
    if o["received_reduction_head"] >= o["required_reduction_head"]:
        o["order_status"] = "COMPLIANT"
        touch(o)
        release_groups_from_destocking(o["ranch_id"])
    elif CLOCK.current_date() > o["deadline_date"]:
        o["order_status"] = "EXPIRED"
        touch(o)
    # else: remains OPEN, no mutation
    return success_envelope(destock_order_out(o))


@bp.post("/api/destock-orders/<oid>/waive")
def waive_order(oid):
    require_ctx(RM)
    o = db.destock_orders.get(oid)
    if not o:
        raise err_not_found()
    body = get_body()
    check_allowed_fields(body, {"waiver_note"})
    note = body.get("waiver_note")
    if not isinstance(note, str) or note.strip() == "":
        raise err_invalid_request("waiver_note is required and must be non-empty")
    if o["order_status"] in ("COMPLIANT", "WAIVED"):
        raise err_already_terminal("Order is already resolved")
    o["order_status"] = "WAIVED"
    o["waiver_note"] = note
    touch(o)
    release_groups_from_destocking(o["ranch_id"])
    return success_envelope(destock_order_out(o))
