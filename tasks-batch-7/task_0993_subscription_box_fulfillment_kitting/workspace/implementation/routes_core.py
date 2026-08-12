"""Routes: clock, clients, box plans, kit revisions/BOM, components, imports, subscribers."""
from flask import Blueprint, request

from core import (
    STORE, CLOCK, clock, iso, parse_dt, valid_period, period_bounds,
    ApiError, bad_request, not_found, forbidden, conflict,
    base_record, light_record, touch, pub, ok, list_resp,
    actor, require_roles, check_own,
    owner_of_plan, owner_of_revision, owner_of_batch, owner_of_subscriber,
    body, req_field, req_str, opt_str, req_int, req_enum, is_int,
    get_or_404, lines_of_revision, subs_of_plan,
    ser_component, append_event, EMAIL_RE,
)

bp = Blueprint("core_routes", __name__)

# ============================================================ logical clock
@bp.post("/_clock/set_current_utc")
def set_clock():
    require_roles("PlatformAdmin")
    b = body()
    raw = req_str(b, "to_iso8601", allow_empty=False)
    dt = parse_dt(raw)
    if dt is None:
        raise bad_request("to_iso8601 must be a valid ISO 8601 timestamp")
    if dt < clock():
        raise bad_request("clock regression is not allowed")
    CLOCK["dt"] = dt
    return ok({"current_utc": iso(clock())})

# ============================================================ clients
@bp.post("/clients")
def create_client():
    require_roles("PlatformAdmin")
    b = body()
    if "credit_balance_cents" in b:
        raise bad_request("credit_balance_cents may not be set at creation")
    name = req_str(b, "name")
    email = req_str(b, "billing_email")
    rec = base_record()
    rec.update({"name": name, "billing_email": email, "credit_balance_cents": 0})
    STORE["clients"][rec["id"]] = rec
    return ok(pub(rec), "object", 201)

@bp.get("/clients/<cid>")
def get_client(cid):
    uid, role = require_roles("PlatformAdmin", "ClientOps", "BillingAdmin")
    if role == "ClientOps" and uid != cid:
        raise forbidden("ClientOps may only read their own client record")
    rec = get_or_404("clients", cid)
    return ok(pub(rec))

@bp.post("/clients/<cid>/credit-adjustments")
def credit_adjustment(cid):
    require_roles("PlatformAdmin", "BillingAdmin")
    rec = get_or_404("clients", cid)
    b = body()
    amount = req_int(b, "amount_cents")
    req_str(b, "reason", allow_empty=True)
    rec["credit_balance_cents"] += amount
    touch(rec)
    return ok(pub(rec))

@bp.get("/clients/<cid>/billing-statements")
def list_client_statements(cid):
    uid, role = require_roles("PlatformAdmin", "ClientOps", "BillingAdmin")
    if role == "ClientOps" and uid != cid:
        raise forbidden("ClientOps may only list their own statements")
    get_or_404("clients", cid)
    res = [s for s in STORE["statements"].values() if s["client_id"] == cid]
    period = request.args.get("period")
    status = request.args.get("status")
    if period is not None:
        res = [s for s in res if s["period"] == period]
    if status is not None:
        res = [s for s in res if s["status"] == status]
    return list_resp(res, pub)

@bp.get("/clients/<cid>/reports/fulfillment-summary")
def fulfillment_summary(cid):
    from decimal import Decimal, ROUND_HALF_UP
    uid, role = require_roles("PlatformAdmin", "ClientOps", "WarehouseOps")
    if role == "ClientOps" and uid != cid:
        raise forbidden("ClientOps may only read their own reports")
    get_or_404("clients", cid)
    period = request.args.get("period")
    if not valid_period(period):
        raise bad_request("period query parameter (YYYY-MM) is required")
    plan_ids = {p["id"] for p in STORE["plans"].values() if p["client_id"] == cid}
    run_set = [r for r in STORE["runs"].values()
               if r["plan_id"] in plan_ids and r["period"] == period
               and r["status"] in ("LOCKED", "KITTING", "KITTED", "CLOSED")]
    planned = sum(r["planned_box_count"] for r in run_set)
    kitted = sum(r["kitted_box_count"] for r in run_set)
    run_ids = {r["id"] for r in run_set}
    shipped = sum(1 for s in STORE["shipments"].values()
                  if s["run_id"] in run_ids
                  and s["fulfill_status"] in ("SHIPPED", "DELIVERED", "RETURNED"))
    returned = sum(1 for s in STORE["shipments"].values()
                   if s["run_id"] in run_ids and s["fulfill_status"] == "RETURNED")
    active_subs = sum(1 for s in STORE["subscribers"].values()
                      if s["plan_id"] in plan_ids and s["status"] == "ACTIVE")
    start, end = period_bounds(period)
    churned = 0
    for s in STORE["subscribers"].values():
        if s["plan_id"] in plan_ids and s.get("churned_at"):
            cat = parse_dt(s["churned_at"])
            if cat is not None and start <= cat < end:
                churned += 1
    if planned == 0:
        fill = 0.0
    else:
        fill = float((Decimal(kitted * 100) / Decimal(planned)).quantize(
            Decimal("0.1"), rounding=ROUND_HALF_UP))
    return ok({"period": period, "planned_boxes": planned, "kitted_boxes": kitted,
               "shipped_boxes": shipped, "returned_boxes": returned,
               "active_subscribers": active_subs, "churned_in_period": churned,
               "fill_rate_pct": fill})

# ============================================================ box plans
@bp.post("/box-plans")
def create_plan():
    uid, role = require_roles("ClientOps", "PlatformAdmin")
    b = body()
    client_id = req_str(b, "client_id")
    name = req_str(b, "name")
    sku = req_str(b, "sku")
    price = req_int(b, "price_per_box_cents")
    weight = req_int(b, "shipping_weight_grams")
    if role == "ClientOps" and client_id != uid:
        raise forbidden("client_id must equal X-User-ID")
    get_or_404("clients", client_id)
    if price <= 0:
        raise ApiError("ERR_INVALID_QUANTITY", 400, "price_per_box_cents must be > 0")
    if weight <= 0:
        raise ApiError("ERR_INVALID_QUANTITY", 400, "shipping_weight_grams must be > 0")
    if any(p["sku"] == sku for p in STORE["plans"].values()):
        raise conflict("ERR_DUPLICATE_SKU", "BoxPlan sku already in use")
    rec = base_record()
    rec.update({"client_id": client_id, "name": name, "sku": sku,
                "price_per_box_cents": price, "shipping_weight_grams": weight,
                "status": "DRAFT", "active_revision_id": None})
    STORE["plans"][rec["id"]] = rec
    return ok(pub(rec), "object", 201)

@bp.get("/box-plans")
def list_plans():
    uid, role = require_roles("PlatformAdmin", "ClientOps", "WarehouseOps", "BillingAdmin")
    res = list(STORE["plans"].values())
    f_client = request.args.get("client_id")
    f_status = request.args.get("status")
    f_rev = request.args.get("active_revision_id")
    if role == "ClientOps":
        if f_client is not None and f_client != uid:
            raise forbidden("ClientOps may only list their own plans")
        res = [p for p in res if p["client_id"] == uid]
    if f_client is not None:
        res = [p for p in res if p["client_id"] == f_client]
    if f_status is not None:
        res = [p for p in res if p["status"] == f_status]
    if f_rev is not None:
        res = [p for p in res if p["active_revision_id"] == f_rev]
    return list_resp(res, pub)

@bp.get("/box-plans/<pid>")
def get_plan(pid):
    uid, role = require_roles("PlatformAdmin", "ClientOps", "WarehouseOps",
                              "BillingAdmin", "CustomerService")
    rec = get_or_404("plans", pid)
    check_own(uid, role, owner_of_plan(rec))
    return ok(pub(rec))

@bp.post("/box-plans/<pid>/activate")
def activate_plan(pid):
    uid, role = require_roles("ClientOps")
    rec = get_or_404("plans", pid)
    check_own(uid, role, owner_of_plan(rec))
    if rec["status"] != "DRAFT":
        raise invalid_state_exc()
    if not rec["active_revision_id"]:
        raise conflict("ERR_PLAN_HAS_NO_APPROVED_REVISION",
                       "Plan has no approved revision")
    rec["status"] = "ACTIVE"
    touch(rec)
    return ok(pub(rec))

def invalid_state_exc(msg="Target entity is not in a valid state for this transition"):
    return conflict("ERR_INVALID_STATE", msg)

@bp.post("/box-plans/<pid>/retire")
def retire_plan(pid):
    uid, role = require_roles("ClientOps")
    rec = get_or_404("plans", pid)
    check_own(uid, role, owner_of_plan(rec))
    if rec["status"] != "ACTIVE":
        raise invalid_state_exc()
    if any(r["plan_id"] == pid and r["status"] in ("LOCKED", "KITTING", "KITTED")
           for r in STORE["runs"].values()):
        raise conflict("ERR_PLAN_HAS_OPEN_RUNS", "Plan has open assembly runs")
    rec["status"] = "RETIRED"
    touch(rec)
    return ok(pub(rec))

@bp.post("/box-plans/<pid>/kit-revisions")
def create_revision(pid):
    uid, role = require_roles("ClientOps")
    plan = get_or_404("plans", pid)
    check_own(uid, role, owner_of_plan(plan))
    b = body()
    expected = req_int(b, "expected_box_plan_version")
    if expected != plan["version"]:
        raise ApiError("ERR_STALE_VERSION", 412,
                       "expected_box_plan_version does not match current version")
    existing = [r for r in STORE["revisions"].values() if r["plan_id"] == pid]
    rev_no = (max(r["revision_no"] for r in existing) + 1) if existing else 1
    supersedes = None
    for r in existing:
        if r["status"] == "DRAFT":
            r["status"] = "RETIRED"
            touch(r)
            supersedes = r["id"]
    rec = base_record()
    rec.update({"plan_id": pid, "revision_no": rev_no,
                "supersedes_revision_id": supersedes, "status": "DRAFT",
                "approved_at": None})
    STORE["revisions"][rec["id"]] = rec
    touch(plan)
    return ok(pub(rec), "object", 201)

@bp.get("/box-plans/<pid>/kit-revisions")
def list_plan_revisions(pid):
    uid, role = require_roles("PlatformAdmin", "ClientOps", "WarehouseOps")
    plan = get_or_404("plans", pid)
    check_own(uid, role, owner_of_plan(plan))
    res = [r for r in STORE["revisions"].values() if r["plan_id"] == pid]
    f_status = request.args.get("status")
    if f_status is not None:
        res = [r for r in res if r["status"] == f_status]
    return list_resp(res, pub)

# ============================================================ kit revisions / BOM
@bp.get("/kit-revisions/<rid>")
def get_revision(rid):
    uid, role = require_roles("PlatformAdmin", "ClientOps", "WarehouseOps")
    rec = get_or_404("revisions", rid)
    check_own(uid, role, owner_of_revision(rec))
    return ok(pub(rec))

@bp.get("/kit-revisions")
def list_revisions():
    uid, role = require_roles("PlatformAdmin", "ClientOps", "WarehouseOps")
    res = list(STORE["revisions"].values())
    f_plan = request.args.get("plan_id")
    f_super = request.args.get("supersedes_revision_id")
    f_status = request.args.get("status")
    if role == "ClientOps":
        if f_plan is not None and f_plan in STORE["plans"]:
            check_own(uid, role, owner_of_plan(STORE["plans"][f_plan]))
        own_plans = {p["id"] for p in STORE["plans"].values() if p["client_id"] == uid}
        res = [r for r in res if r["plan_id"] in own_plans]
    if f_plan is not None:
        res = [r for r in res if r["plan_id"] == f_plan]
    if f_super is not None:
        res = [r for r in res if r["supersedes_revision_id"] == f_super]
    if f_status is not None:
        res = [r for r in res if r["status"] == f_status]
    return list_resp(res, pub)

@bp.post("/kit-revisions/<rid>/approve")
def approve_revision(rid):
    uid, role = require_roles("ClientOps")
    rec = get_or_404("revisions", rid)
    check_own(uid, role, owner_of_revision(rec))
    if rec["status"] != "DRAFT":
        raise invalid_state_exc()
    if not lines_of_revision(rid):
        raise conflict("ERR_REVISION_EMPTY_BOM", "Revision has no BOM lines")
    plan = STORE["plans"][rec["plan_id"]]
    if plan["status"] not in ("DRAFT", "ACTIVE"):
        raise conflict("ERR_PLAN_NOT_ACTIVE", "Owning plan is not DRAFT or ACTIVE")
    for r in STORE["revisions"].values():
        if r["plan_id"] == plan["id"] and r["status"] == "APPROVED" and r["id"] != rid:
            r["status"] = "RETIRED"
            touch(r)
    plan["active_revision_id"] = rid
    touch(plan)
    rec["status"] = "APPROVED"
    rec["approved_at"] = iso(clock())
    touch(rec)
    return ok(pub(rec))

@bp.put("/kit-revisions/<rid>/bom-lines")
def put_bom_lines(rid):
    uid, role = require_roles("ClientOps")
    rec = get_or_404("revisions", rid)
    check_own(uid, role, owner_of_revision(rec))
    b = body()
    lines = req_field(b, "lines")
    if not isinstance(lines, list):
        raise bad_request("lines must be an array")
    parsed = []
    for ln in lines:
        if not isinstance(ln, dict):
            raise bad_request("each line must be an object")
        comp_id = req_str(ln, "component_id")
        qty = req_int(ln, "qty_per_box")
        parsed.append((comp_id, qty))
    for comp_id, _ in parsed:
        get_or_404("components", comp_id)
    if rec["status"] != "DRAFT":
        raise invalid_state_exc("BOM line set may only be replaced on a DRAFT revision")
    for _, qty in parsed:
        if qty <= 0:
            raise ApiError("ERR_INVALID_QUANTITY", 400, "qty_per_box must be > 0")
    seen = set()
    for comp_id, _ in parsed:
        if comp_id in seen:
            raise bad_request("duplicate component_id within lines")
        seen.add(comp_id)
    # transactional replace
    for lid in [l["id"] for l in lines_of_revision(rid)]:
        del STORE["bom_lines"][lid]
    out = []
    for comp_id, qty in parsed:
        rec_l = light_record()
        rec_l.update({"revision_id": rid, "component_id": comp_id, "qty_per_box": qty})
        STORE["bom_lines"][rec_l["id"]] = rec_l
        out.append(rec_l)
    return ok([pub(l) for l in out], "array", 200)

@bp.get("/kit-revisions/<rid>/bom-lines")
def list_bom_lines(rid):
    uid, role = require_roles("PlatformAdmin", "ClientOps", "WarehouseOps")
    rec = get_or_404("revisions", rid)
    check_own(uid, role, owner_of_revision(rec))
    return list_resp(lines_of_revision(rid), pub)

# ============================================================ components
@bp.post("/components")
def create_component():
    require_roles("WarehouseOps")
    b = body()
    sku = req_str(b, "sku")
    name = req_str(b, "name")
    cost = req_int(b, "unit_cost_cents")
    reorder = b.get("reorder_point_units", 0)
    if not is_int(reorder):
        raise bad_request("reorder_point_units must be an integer")
    if cost < 0:
        raise ApiError("ERR_INVALID_QUANTITY", 400, "unit_cost_cents must be >= 0")
    if reorder < 0:
        raise ApiError("ERR_INVALID_QUANTITY", 400, "reorder_point_units must be >= 0")
    if any(c["sku"] == sku for c in STORE["components"].values()):
        raise conflict("ERR_DUPLICATE_SKU", "Component sku already in use")
    rec = base_record()
    rec.update({"sku": sku, "name": name, "unit_cost_cents": cost,
                "reorder_point_units": reorder, "on_hand_units": 0,
                "reserved_units": 0})
    STORE["components"][rec["id"]] = rec
    return ok(ser_component(rec), "object", 201)

@bp.get("/components/<cid>")
def get_component(cid):
    require_roles("PlatformAdmin", "ClientOps", "WarehouseOps", "BillingAdmin")
    rec = get_or_404("components", cid)
    return ok(ser_component(rec))

@bp.get("/components/<cid>/bom-lines")
def list_component_bom_lines(cid):
    require_roles("PlatformAdmin", "ClientOps", "WarehouseOps")
    get_or_404("components", cid)
    res = [l for l in STORE["bom_lines"].values() if l["component_id"] == cid]
    return list_resp(res, pub)

@bp.post("/components/<cid>/receipts")
def create_receipt(cid):
    require_roles("WarehouseOps")
    rec = get_or_404("components", cid)
    b = body()
    qty = req_int(b, "quantity")
    expected = req_int(b, "expected_component_version")
    note = opt_str(b, "note")
    if expected != rec["version"]:
        raise ApiError("ERR_STALE_VERSION", 412,
                       "expected_component_version does not match current version")
    if qty <= 0:
        raise ApiError("ERR_INVALID_QUANTITY", 400, "quantity must be > 0")
    append_event(cid, None, "RECEIPT", qty, note)
    rec["on_hand_units"] += qty
    touch(rec)
    return ok(ser_component(rec))

@bp.get("/components/<cid>/inventory-events")
def list_component_events(cid):
    require_roles("PlatformAdmin", "ClientOps", "WarehouseOps")
    get_or_404("components", cid)
    res = [e for e in STORE["events"].values() if e["component_id"] == cid]
    f_type = request.args.get("event_type")
    if f_type is not None:
        res = [e for e in res if e["event_type"] == f_type]
    return list_resp(res, pub)

# ============================================================ import batches
@bp.post("/box-plans/<pid>/import-batches")
def upload_batch(pid):
    uid, role = require_roles("ClientOps")
    plan = get_or_404("plans", pid)
    check_own(uid, role, owner_of_plan(plan))
    b = body()
    rows = req_field(b, "rows")
    if not isinstance(rows, list):
        raise bad_request("rows must be an array")
    rec = base_record()
    rec.update({"plan_id": pid, "rows": rows, "total_rows": len(rows),
                "accepted_count": 0, "rejected_count": 0, "status": "UPLOADED"})
    STORE["batches"][rec["id"]] = rec
    return ok(pub(rec), "object", 201)

@bp.get("/box-plans/<pid>/import-batches")
def list_plan_batches(pid):
    uid, role = require_roles("PlatformAdmin", "ClientOps")
    plan = get_or_404("plans", pid)
    check_own(uid, role, owner_of_plan(plan))
    res = [x for x in STORE["batches"].values() if x["plan_id"] == pid]
    f_status = request.args.get("status")
    if f_status is not None:
        res = [x for x in res if x["status"] == f_status]
    return list_resp(res, pub)

@bp.get("/import-batches/<bid>")
def get_batch(bid):
    uid, role = require_roles("PlatformAdmin", "ClientOps")
    rec = get_or_404("batches", bid)
    check_own(uid, role, owner_of_batch(rec))
    return ok(pub(rec))

@bp.post("/import-batches/<bid>/commit")
def commit_batch(bid):
    uid, role = require_roles("ClientOps")
    rec = get_or_404("batches", bid)
    check_own(uid, role, owner_of_batch(rec))
    if rec["status"] != "UPLOADED":
        raise conflict("ERR_IMPORT_ALREADY_COMMITTED", "Batch already committed")
    pid = rec["plan_id"]
    seen = set()
    accepted = rejected = 0
    for row in rec["rows"]:
        okrow = isinstance(row, dict)
        email = row.get("email") if okrow else None
        zone = row.get("zone") if okrow else None
        fname = row.get("full_name") if okrow else None
        valid = (okrow and isinstance(email, str) and EMAIL_RE.match(email)
                 and is_int(zone) and 1 <= zone <= 8
                 and (fname is None or isinstance(fname, str)))
        if not valid:
            rejected += 1
            continue
        if email in seen:
            rejected += 1
            continue
        seen.add(email)
        existing = next((s for s in STORE["subscribers"].values()
                         if s["plan_id"] == pid and s["email"] == email), None)
        if existing is not None and existing["status"] == "CHURNED":
            rejected += 1
            continue
        if existing is not None:
            existing["zone"] = zone
            existing["full_name"] = fname
            existing["import_batch_id"] = bid
            touch(existing)
            accepted += 1
        else:
            sub = base_record()
            sub.update({"plan_id": pid, "import_batch_id": bid, "email": email,
                        "full_name": fname, "zone": zone, "status": "ACTIVE",
                        "churned_at": None, "churn_reason": None})
            STORE["subscribers"][sub["id"]] = sub
            accepted += 1
    rec["accepted_count"] = accepted
    rec["rejected_count"] = rejected
    rec["status"] = "COMMITTED"
    touch(rec)
    return ok(pub(rec))

# ============================================================ subscribers
@bp.get("/subscribers")
def list_subscribers():
    uid, role = require_roles("PlatformAdmin", "ClientOps", "WarehouseOps",
                              "CustomerService")
    res = list(STORE["subscribers"].values())
    f_plan = request.args.get("plan_id")
    f_batch = request.args.get("import_batch_id")
    f_status = request.args.get("status")
    if role == "ClientOps":
        if f_plan is not None and f_plan in STORE["plans"]:
            check_own(uid, role, owner_of_plan(STORE["plans"][f_plan]))
        own_plans = {p["id"] for p in STORE["plans"].values() if p["client_id"] == uid}
        res = [s for s in res if s["plan_id"] in own_plans]
    if f_plan is not None:
        res = [s for s in res if s["plan_id"] == f_plan]
    if f_batch is not None:
        res = [s for s in res if s["import_batch_id"] == f_batch]
    if f_status is not None:
        res = [s for s in res if s["status"] == f_status]
    return list_resp(res, pub)

@bp.get("/subscribers/<sid>")
def get_subscriber(sid):
    uid, role = require_roles("PlatformAdmin", "ClientOps", "WarehouseOps",
                              "CustomerService")
    rec = get_or_404("subscribers", sid)
    check_own(uid, role, owner_of_subscriber(rec))
    return ok(pub(rec))

@bp.post("/subscribers/<sid>/pause")
def pause_subscriber(sid):
    uid, role = require_roles("ClientOps")
    rec = get_or_404("subscribers", sid)
    check_own(uid, role, owner_of_subscriber(rec))
    if rec["status"] != "ACTIVE":
        raise invalid_state_exc()
    rec["status"] = "PAUSED"
    touch(rec)
    return ok(pub(rec))

@bp.post("/subscribers/<sid>/resume")
def resume_subscriber(sid):
    uid, role = require_roles("ClientOps")
    rec = get_or_404("subscribers", sid)
    check_own(uid, role, owner_of_subscriber(rec))
    if rec["status"] != "PAUSED":
        raise invalid_state_exc()
    rec["status"] = "ACTIVE"
    touch(rec)
    return ok(pub(rec))

@bp.post("/subscribers/<sid>/churn")
def churn_subscriber(sid):
    uid, role = require_roles("ClientOps")
    rec = get_or_404("subscribers", sid)
    check_own(uid, role, owner_of_subscriber(rec))
    b = body()
    reason = req_enum(b, "reason", {"PRICE", "PRODUCT", "MOVED", "OTHER"})
    if rec["status"] not in ("ACTIVE", "PAUSED"):
        raise invalid_state_exc()
    rec["status"] = "CHURNED"
    rec["churned_at"] = iso(clock())
    rec["churn_reason"] = reason
    touch(rec)
    return ok(pub(rec))

@bp.get("/subscribers/<sid>/shipments")
def list_subscriber_shipments(sid):
    uid, role = require_roles("PlatformAdmin", "ClientOps", "WarehouseOps",
                              "CustomerService")
    rec = get_or_404("subscribers", sid)
    check_own(uid, role, owner_of_subscriber(rec))
    res = [s for s in STORE["shipments"].values() if s["subscriber_id"] == sid]
    f = request.args.get("fulfill_status")
    if f is not None:
        res = [s for s in res if s["fulfill_status"] == f]
    return list_resp(res, pub)
