"""Routes: pools, settlement, advances, caretaking orders and invoices."""
from flask import Blueprint, request

from core import (
    DB, D, rhu, cents, now, err, ok_object, ok_list, require_roles, body,
    req_field, as_int, as_num, as_str, as_enum, parse_date, paginate,
    new_entity, touch, get_or_404, sort_asc, STAFF_ROLES,
    ERR_INVALID_REQUEST, ERR_NOT_FOUND, ERR_DUPLICATE_ENTITY,
    ERR_INVALID_STATE_TRANSITION, ERR_STALE_VERSION, ERR_GROVE_RETIRED,
    ERR_GROWER_NOT_ACTIVE, ERR_GROWER_OWNERSHIP_MISMATCH,
    ERR_POOL_NOT_ACCEPTING, ERR_POOL_HAS_OPEN_DELIVERIES,
    ERR_ADVANCE_CAP_EXCEEDED, ERR_INVOICE_OVERPAYMENT, ERR_PAYMENT_AMOUNT_INVALID,
    ERR_ACRES_EXCEED_GROVE, ERR_CHEMICAL_COST_NOT_ALLOWED,
    ERR_CARETAKING_NOT_ENROLLED,
)
from domain import (
    VARIETIES, SERVICE_TYPES, RECOUP_POLICIES, RATE_CENTS_PER_ACRE,
    CHEMICAL_MARKUP_PCT, CARETAKING_OFFSET_CAP_PCT, ADVANCE_CAP_PCT,
    TIER1_MAX, TIER2_MAX, grower_posted_ge_in_pool, ser_pool, ser_advance,
    ser_ct_order, ser_ct_invoice,
)

bp = Blueprint("money", __name__)
ALL_READ = STAFF_ROLES


# ---------------------------------------------------------------------------
# Pools
# ---------------------------------------------------------------------------
@bp.post("/packinghouse/pools")
def create_pool():
    require_roles(["PoolAccountant"])
    b = body()
    variety = as_enum(req_field(b, "variety"), "variety", VARIETIES)
    week_start = parse_date(req_field(b, "week_start"), "week_start")
    for p in DB["pools"].values():
        if p["variety"] == variety and p["week_start"] == week_start.isoformat():
            err(ERR_DUPLICATE_ENTITY, 409, "Pool already exists for variety + week_start")
    p = new_entity()
    p.update(
        variety=variety,
        week_start=week_start.isoformat(),
        status="OPEN",
        posted_ge_boxes=D(0),
        posted_proceeds_cents=0,
        sorted_field_boxes=0,
        provisional_price_cents_per_ge_box=0,
        final_price_cents_per_ge_box=None,
        statements=[],
        _week_start_date=week_start,
    )
    DB["pools"][p["id"]] = p
    return ok_object(ser_pool(p), 201)


@bp.get("/packinghouse/pools")
def list_pools():
    require_roles(ALL_READ + ["Grower"])
    items = sort_asc(DB["pools"].values())
    for f in ("variety", "status"):
        v = request.args.get(f)
        if v is not None:
            items = [p for p in items if p[f] == v]
    page, pag = paginate(items)
    return ok_list([ser_pool(p) for p in page], pag)


@bp.get("/packinghouse/pools/<rid>")
def get_pool(rid):
    require_roles(ALL_READ + ["Grower"])
    p = get_or_404("pools", rid, "Pool")
    return ok_object(ser_pool(p))


@bp.post("/packinghouse/pools/<rid>/close-intake")
def close_intake(rid):
    require_roles(["PoolAccountant"])
    p = get_or_404("pools", rid, "Pool")
    if p["status"] != "OPEN":
        err(ERR_INVALID_STATE_TRANSITION, 409, "Pool is not OPEN")
    for d in DB["deliveries"].values():
        if (
            d["pool_id"] == rid
            and d["processing_status"] in {"RECEIVED", "IN_DEGREENING", "READY_TO_SORT"}
            and d["regulatory_status"] != "CONDEMNED"
        ):
            err(ERR_POOL_HAS_OPEN_DELIVERIES, 409, "Pool has unfinished deliveries")
    p["status"] = "INTAKE_CLOSED"
    touch(p)
    return ok_object(ser_pool(p))


@bp.post("/packinghouse/pools/<rid>/set-price")
def set_price(rid):
    require_roles(["PoolAccountant"])
    p = get_or_404("pools", rid, "Pool")
    b = body()
    expected = as_int(req_field(b, "expected_pool_version"), "expected_pool_version")
    if p["status"] not in {"INTAKE_CLOSED", "PRICED"}:
        err(ERR_INVALID_STATE_TRANSITION, 409, "Pool must be INTAKE_CLOSED or PRICED to set price")
    if expected != p["version"]:
        err(ERR_STALE_VERSION, 412, "expected_pool_version is stale")
    # pool_final_price: actuals only, tiered packing charge on sorted field boxes
    sfb = p["sorted_field_boxes"]
    if sfb < TIER1_MAX:
        rate = 150
    elif sfb < TIER2_MAX:
        rate = 140
    else:
        rate = 125
    packing_charge_total = sfb * rate
    ge = p["posted_ge_boxes"]
    denom = ge if ge > 1 else D(1)
    final = cents((D(p["posted_proceeds_cents"]) - D(packing_charge_total)) / denom)
    p["final_price_cents_per_ge_box"] = final
    p["status"] = "PRICED"
    touch(p)
    return ok_object(ser_pool(p))


@bp.post("/packinghouse/pools/<rid>/settle")
def settle_pool(rid):
    require_roles(["PoolAccountant"])
    p = get_or_404("pools", rid, "Pool")
    if p["status"] != "PRICED":
        err(ERR_INVALID_STATE_TRANSITION, 409, "Pool must be PRICED to settle")
    # settlement_waterfall: growers in created_at ASC order, pinned steps
    statements = []
    for g in sort_asc(DB["growers"].values()):
        ge = grower_posted_ge_in_pool(g["id"], rid)
        if ge <= 0:
            continue
        # step 1: share
        share = cents(ge * D(p["final_price_cents_per_ge_box"]))
        # step 2: caretaking offset (capped at half the share)
        offset = min(
            g["caretaking_balance_cents"], cents(CARETAKING_OFFSET_CAP_PCT * D(share))
        )
        residual = share - offset
        # step 3: advance recoupment, oldest issued_at ASC (tie: created_at ASC)
        advances = [
            a
            for a in DB["advances"].values()
            if a["grower_id"] == g["id"]
            and a["pool_id"] == rid
            and a["status"] in {"ISSUED", "PARTIALLY_RECOUPED"}
        ]
        advances.sort(key=lambda a: (a["issued_at"], a["created_at"], a["_seq"]))
        total_recouped = 0
        for adv in advances:
            if adv["recoup_policy"] == "NEXT_SETTLEMENT_FULL":
                cap_adv = adv["outstanding_cents"]
            else:  # PRO_RATA_THIRDS
                cap_adv = cents(D(adv["amount_cents"]) / D(3))
            recoup = max(0, min(adv["outstanding_cents"], cap_adv, residual))
            residual -= recoup
            if recoup > 0:
                adv["recouped_cents"] += recoup
                adv["outstanding_cents"] = (
                    adv["amount_cents"] - adv["recouped_cents"] - adv["written_off_cents"]
                )
                adv["status"] = (
                    "RECOUPED" if adv["outstanding_cents"] == 0 else "PARTIALLY_RECOUPED"
                )
                touch(adv)
                total_recouped += recoup
        # step 4: remainder is the grower's payment
        paid = residual
        g["caretaking_balance_cents"] -= offset
        g["advance_outstanding_cents"] -= total_recouped
        touch(g)
        statements.append(
            {
                "grower_id": g["id"],
                "posted_ge_boxes": float(ge),
                "share_cents": share,
                "offset_cents": offset,
                "recouped_cents": total_recouped,
                "paid_cents": paid,
            }
        )
    p["statements"] = statements
    p["status"] = "SETTLED"
    touch(p)
    return ok_object(ser_pool(p))


@bp.get("/packinghouse/pools/<rid>/settlement-statements")
def settlement_statements(rid):
    uid, role = require_roles(["PackinghouseAdmin", "PoolAccountant", "Grower"])
    p = get_or_404("pools", rid, "Pool")
    statements = list(p["statements"])
    if role == "Grower":
        statements = [s for s in statements if s["grower_id"] == uid]
    return ok_object({"pool_id": rid, "statements": statements})


# ---------------------------------------------------------------------------
# Advance payments
# ---------------------------------------------------------------------------
@bp.post("/packinghouse/advances")
def create_advance():
    uid, role = require_roles(["Grower", "PoolAccountant"])
    b = body()
    grower_id = as_str(req_field(b, "grower_id"), "grower_id")
    pool_id = as_str(req_field(b, "pool_id"), "pool_id")
    amount = as_int(req_field(b, "amount_cents"), "amount_cents")
    policy = b.get("recoup_policy")
    policy = "NEXT_SETTLEMENT_FULL" if policy is None else as_enum(
        policy, "recoup_policy", RECOUP_POLICIES
    )
    if amount <= 0:
        err(ERR_INVALID_REQUEST, 400, "amount_cents must be > 0")
    if role == "Grower" and grower_id != uid:
        err(ERR_GROWER_OWNERSHIP_MISMATCH, 403, "Grower may request advances only for itself")
    if grower_id not in DB["growers"]:
        err(ERR_NOT_FOUND, 404, f"Grower not found: {grower_id}")
    if pool_id not in DB["pools"]:
        err(ERR_NOT_FOUND, 404, f"Pool not found: {pool_id}")
    a = new_entity()
    a.update(
        grower_id=grower_id,
        pool_id=pool_id,
        amount_cents=amount,
        recoup_policy=policy,
        status="REQUESTED",
        issued_at=None,
        recouped_cents=0,
        written_off_cents=0,
        outstanding_cents=amount,
    )
    DB["advances"][a["id"]] = a
    return ok_object(ser_advance(a), 201)


@bp.get("/packinghouse/advances")
def list_advances():
    uid, role = require_roles(["PackinghouseAdmin", "PoolAccountant", "ComplianceOfficer", "Grower"])
    items = sort_asc(DB["advances"].values())
    if role == "Grower":
        items = [a for a in items if a["grower_id"] == uid]
    for f in ("grower_id", "pool_id", "status"):
        v = request.args.get(f)
        if v is not None:
            items = [a for a in items if a[f] == v]
    page, pag = paginate(items)
    return ok_list([ser_advance(a) for a in page], pag)


@bp.get("/packinghouse/advances/<rid>")
def get_advance(rid):
    uid, role = require_roles(["PackinghouseAdmin", "PoolAccountant", "ComplianceOfficer", "Grower"])
    a = get_or_404("advances", rid, "AdvancePayment")
    if role == "Grower" and a["grower_id"] != uid:
        err(ERR_GROWER_OWNERSHIP_MISMATCH, 403, "Grower may read only its own advances")
    return ok_object(ser_advance(a))


@bp.post("/packinghouse/advances/<rid>/approve")
def approve_advance(rid):
    require_roles(["PoolAccountant"])
    a = get_or_404("advances", rid, "AdvancePayment")
    if a["status"] != "REQUESTED":
        err(ERR_INVALID_STATE_TRANSITION, 409, "Advance is not REQUESTED")
    grower = DB["growers"][a["grower_id"]]
    pool = DB["pools"][a["pool_id"]]
    # tier 12: fiscal gates (grower standing, then advance cap)
    if grower["status"] != "ACTIVE":
        err(ERR_GROWER_NOT_ACTIVE, 409, "Grower is not ACTIVE")
    # advance_cap_check
    grower_pool_ge = grower_posted_ge_in_pool(a["grower_id"], a["pool_id"])
    projected_value = grower_pool_ge * D(pool["provisional_price_cents_per_ge_box"])
    cap = cents(ADVANCE_CAP_PCT * projected_value)
    if grower["advance_outstanding_cents"] + a["amount_cents"] > cap:
        err(ERR_ADVANCE_CAP_EXCEEDED, 422, "Advance exceeds the cap for this grower and pool")
    # tier 13: pool state
    if pool["status"] != "OPEN":
        err(ERR_POOL_NOT_ACCEPTING, 409, "Pool is not OPEN")
    a["status"] = "ISSUED"
    a["issued_at"] = now()
    touch(a)
    grower["advance_outstanding_cents"] += a["amount_cents"]
    touch(grower)
    return ok_object(ser_advance(a))


@bp.post("/packinghouse/advances/<rid>/deny")
def deny_advance(rid):
    require_roles(["PoolAccountant"])
    a = get_or_404("advances", rid, "AdvancePayment")
    if a["status"] != "REQUESTED":
        err(ERR_INVALID_STATE_TRANSITION, 409, "Advance is not REQUESTED")
    a["status"] = "DENIED"
    touch(a)
    return ok_object(ser_advance(a))


@bp.post("/packinghouse/advances/<rid>/write-off")
def write_off_advance(rid):
    require_roles(["PoolAccountant"])
    a = get_or_404("advances", rid, "AdvancePayment")
    if a["status"] not in {"ISSUED", "PARTIALLY_RECOUPED"}:
        err(ERR_INVALID_STATE_TRANSITION, 409, "Advance cannot be written off")
    pool = DB["pools"][a["pool_id"]]
    if pool["status"] != "SETTLED":
        err(ERR_POOL_NOT_ACCEPTING, 409, "Advance's pool is not SETTLED")
    amount = a["outstanding_cents"]
    a["written_off_cents"] = amount
    a["outstanding_cents"] = 0
    a["status"] = "WRITTEN_OFF"
    touch(a)
    grower = DB["growers"][a["grower_id"]]
    grower["advance_outstanding_cents"] -= amount
    touch(grower)
    return ok_object(ser_advance(a))


# ---------------------------------------------------------------------------
# Caretaking service orders
# ---------------------------------------------------------------------------
def _grower_owns_grove_order(o, uid):
    grove = DB["groves"].get(o["grove_id"])
    return grove is not None and grove["grower_id"] == uid


@bp.post("/packinghouse/caretaking-orders")
def create_ct_order():
    uid, role = require_roles(["Grower", "FieldSupervisor"])
    b = body()
    grove_id = as_str(req_field(b, "grove_id"), "grove_id")
    grove = DB["groves"].get(grove_id)
    if grove is None:
        err(ERR_NOT_FOUND, 404, f"Grove not found: {grove_id}")
    if role == "Grower" and grove["grower_id"] != uid:
        err(ERR_GROWER_OWNERSHIP_MISMATCH, 403, "Grower may order only for its own groves")
    service_type = as_enum(req_field(b, "service_type"), "service_type", SERVICE_TYPES)
    service_date = parse_date(req_field(b, "service_date"), "service_date")
    acres = as_num(req_field(b, "acres_treated"), "acres_treated")
    if D(acres) <= 0:
        err(ERR_INVALID_REQUEST, 400, "acres_treated must be > 0")
    chem = b.get("chemical_cost_cents")
    chem = 0 if chem is None else as_int(chem, "chemical_cost_cents")
    if chem < 0:
        err(ERR_INVALID_REQUEST, 400, "chemical_cost_cents must be >= 0")
    # tier 7
    if grove["lifecycle_status"] != "PRODUCTIVE":
        err(ERR_GROVE_RETIRED, 409, "Grove is RETIRED")
    # tier 10
    if D(acres) > D(grove["acreage"]):
        err(ERR_ACRES_EXCEED_GROVE, 422, "acres_treated exceeds grove acreage")
    if chem > 0 and service_type != "SPRAY":
        err(ERR_CHEMICAL_COST_NOT_ALLOWED, 422, "chemical_cost_cents allowed only for SPRAY")
    # tier 12
    grower = DB["growers"][grove["grower_id"]]
    if grower["status"] != "ACTIVE":
        err(ERR_GROWER_NOT_ACTIVE, 409, "Grower is not ACTIVE")
    # tier 13
    if not grove["caretaking_enrolled"]:
        err(ERR_CARETAKING_NOT_ENROLLED, 422, "Grove is not enrolled in caretaking")
    o = new_entity()
    o.update(
        grove_id=grove_id,
        service_type=service_type,
        service_date=service_date,
        acres_treated=acres,
        chemical_cost_cents=chem,
        rate_tier=None,
        line_amount_cents=None,
        invoice_id=None,
        status="REQUESTED",
    )
    DB["ct_orders"][o["id"]] = o
    return ok_object(ser_ct_order(o), 201)


@bp.get("/packinghouse/caretaking-orders")
def list_ct_orders():
    uid, role = require_roles(["PackinghouseAdmin", "PoolAccountant", "FieldSupervisor", "Grower"])
    items = sort_asc(DB["ct_orders"].values())
    if role == "Grower":
        items = [o for o in items if _grower_owns_grove_order(o, uid)]
    for f in ("grove_id", "invoice_id", "status", "service_type"):
        v = request.args.get(f)
        if v is not None:
            items = [o for o in items if o[f] == v]
    page, pag = paginate(items)
    return ok_list([ser_ct_order(o) for o in page], pag)


@bp.get("/packinghouse/caretaking-orders/<rid>")
def get_ct_order(rid):
    uid, role = require_roles(["PackinghouseAdmin", "PoolAccountant", "FieldSupervisor", "Grower"])
    o = get_or_404("ct_orders", rid, "CaretakingServiceOrder")
    if role == "Grower" and not _grower_owns_grove_order(o, uid):
        err(ERR_GROWER_OWNERSHIP_MISMATCH, 403, "Grower may read only its own groves' orders")
    return ok_object(ser_ct_order(o))


@bp.post("/packinghouse/caretaking-orders/<rid>/schedule")
def schedule_ct_order(rid):
    require_roles(["FieldSupervisor"])
    o = get_or_404("ct_orders", rid, "CaretakingServiceOrder")
    if o["status"] != "REQUESTED":
        err(ERR_INVALID_STATE_TRANSITION, 409, "Order is not REQUESTED")
    o["status"] = "SCHEDULED"
    touch(o)
    return ok_object(ser_ct_order(o))


@bp.post("/packinghouse/caretaking-orders/<rid>/complete")
def complete_ct_order(rid):
    require_roles(["FieldSupervisor"])
    o = get_or_404("ct_orders", rid, "CaretakingServiceOrder")
    if o["status"] != "SCHEDULED":
        err(ERR_INVALID_STATE_TRANSITION, 409, "Order is not SCHEDULED")
    grove = DB["groves"][o["grove_id"]]
    # caretaking_billing_rollup: round per component, per line, THEN sum
    acreage = D(grove["acreage"])
    if acreage < 40:
        tier = "SMALL"
    elif acreage <= 120:
        tier = "MEDIUM"
    else:
        tier = "LARGE"
    rate = RATE_CENTS_PER_ACRE[o["service_type"]][tier]
    labor_component = cents(D(o["acres_treated"]) * D(rate))
    chemical_component = (
        cents(D(o["chemical_cost_cents"]) * (D(1) + CHEMICAL_MARKUP_PCT))
        if o["service_type"] == "SPRAY"
        else 0
    )
    o["rate_tier"] = tier
    o["line_amount_cents"] = labor_component + chemical_component
    o["status"] = "COMPLETED"
    touch(o)
    return ok_object(ser_ct_order(o))


@bp.post("/packinghouse/caretaking-orders/<rid>/cancel")
def cancel_ct_order(rid):
    uid, role = require_roles(["Grower", "FieldSupervisor"])
    o = get_or_404("ct_orders", rid, "CaretakingServiceOrder")
    if role == "Grower" and not _grower_owns_grove_order(o, uid):
        err(ERR_GROWER_OWNERSHIP_MISMATCH, 403, "Grower may cancel only its own groves' orders")
    if o["status"] not in {"REQUESTED", "SCHEDULED"}:
        err(ERR_INVALID_STATE_TRANSITION, 409, "Order cannot be cancelled")
    o["status"] = "CANCELLED"
    touch(o)
    return ok_object(ser_ct_order(o))


# ---------------------------------------------------------------------------
# Caretaking invoices
# ---------------------------------------------------------------------------
@bp.post("/packinghouse/caretaking-invoices")
def create_ct_invoice():
    require_roles(["PoolAccountant"])
    b = body()
    grower_id = as_str(req_field(b, "grower_id"), "grower_id")
    if grower_id not in DB["growers"]:
        err(ERR_NOT_FOUND, 404, f"Grower not found: {grower_id}")
    period_start = parse_date(req_field(b, "period_start"), "period_start")
    period_end = parse_date(req_field(b, "period_end"), "period_end")
    if period_end < period_start:
        err(ERR_INVALID_REQUEST, 400, "period_end must be >= period_start")
    grove_ids = {g["id"] for g in DB["groves"].values() if g["grower_id"] == grower_id}
    swept = [
        o
        for o in DB["ct_orders"].values()
        if o["grove_id"] in grove_ids
        and o["status"] == "COMPLETED"
        and o["invoice_id"] is None
        and period_start <= o["service_date"] <= period_end
    ]
    swept.sort(key=lambda o: (o["service_date"], o["created_at"], o["_seq"]))
    inv = new_entity()
    inv.update(
        grower_id=grower_id,
        period_start=period_start,
        period_end=period_end,
        line_order_ids=[o["id"] for o in swept],
        total_cents=sum(o["line_amount_cents"] for o in swept),
        paid_cents=0,
        status="DRAFT",
    )
    DB["ct_invoices"][inv["id"]] = inv
    return ok_object(ser_ct_invoice(inv), 201)


@bp.get("/packinghouse/caretaking-invoices")
def list_ct_invoices():
    uid, role = require_roles(["PackinghouseAdmin", "PoolAccountant", "Grower"])
    items = sort_asc(DB["ct_invoices"].values())
    if role == "Grower":
        items = [i for i in items if i["grower_id"] == uid]
    for f in ("grower_id", "status"):
        v = request.args.get(f)
        if v is not None:
            items = [i for i in items if i[f] == v]
    page, pag = paginate(items)
    return ok_list([ser_ct_invoice(i) for i in page], pag)


@bp.get("/packinghouse/caretaking-invoices/<rid>")
def get_ct_invoice(rid):
    uid, role = require_roles(["PackinghouseAdmin", "PoolAccountant", "Grower"])
    inv = get_or_404("ct_invoices", rid, "CaretakingInvoice")
    if role == "Grower" and inv["grower_id"] != uid:
        err(ERR_GROWER_OWNERSHIP_MISMATCH, 403, "Grower may read only its own invoices")
    return ok_object(ser_ct_invoice(inv))


@bp.post("/packinghouse/caretaking-invoices/<rid>/issue")
def issue_ct_invoice(rid):
    require_roles(["PoolAccountant"])
    inv = get_or_404("ct_invoices", rid, "CaretakingInvoice")
    if inv["status"] != "DRAFT":
        err(ERR_INVALID_STATE_TRANSITION, 409, "Invoice is not DRAFT")
    if not inv["line_order_ids"]:
        err(ERR_INVALID_STATE_TRANSITION, 409, "Invoice has no line items")
    grower = DB["growers"][inv["grower_id"]]
    if grower["status"] == "TERMINATED":
        err(ERR_GROWER_NOT_ACTIVE, 409, "Grower is TERMINATED")
    for oid in inv["line_order_ids"]:
        o = DB["ct_orders"][oid]
        o["status"] = "INVOICED"
        o["invoice_id"] = inv["id"]
        touch(o)
    inv["status"] = "ISSUED"
    touch(inv)
    grower["caretaking_balance_cents"] += inv["total_cents"]
    touch(grower)
    return ok_object(ser_ct_invoice(inv))


@bp.post("/packinghouse/caretaking-invoices/<rid>/payments")
def pay_ct_invoice(rid):
    uid, role = require_roles(["Grower", "PoolAccountant"])
    inv = get_or_404("ct_invoices", rid, "CaretakingInvoice")
    if role == "Grower" and inv["grower_id"] != uid:
        err(ERR_GROWER_OWNERSHIP_MISMATCH, 403, "Grower may pay only its own invoices")
    b = body()
    amount = as_int(req_field(b, "amount_cents"), "amount_cents")
    if amount <= 0:
        err(ERR_PAYMENT_AMOUNT_INVALID, 400, "amount_cents must be > 0")
    if inv["status"] not in {"ISSUED", "PARTIALLY_PAID"}:
        err(ERR_INVALID_STATE_TRANSITION, 409, "Invoice does not accept payments")
    remaining = inv["total_cents"] - inv["paid_cents"]
    if amount > remaining:
        err(ERR_INVOICE_OVERPAYMENT, 422, "Payment exceeds the invoice's remaining balance")
    inv["paid_cents"] += amount
    inv["status"] = "PAID" if inv["paid_cents"] == inv["total_cents"] else "PARTIALLY_PAID"
    touch(inv)
    grower = DB["growers"][inv["grower_id"]]
    grower["caretaking_balance_cents"] -= amount
    touch(grower)
    return ok_object(ser_ct_invoice(inv), 201)


@bp.post("/packinghouse/caretaking-invoices/<rid>/dispute")
def dispute_ct_invoice(rid):
    uid, role = require_roles(["Grower"])
    inv = get_or_404("ct_invoices", rid, "CaretakingInvoice")
    if inv["grower_id"] != uid:
        err(ERR_GROWER_OWNERSHIP_MISMATCH, 403, "Grower may dispute only its own invoices")
    if inv["status"] != "ISSUED":
        err(ERR_INVALID_STATE_TRANSITION, 409, "Invoice is not ISSUED")
    inv["status"] = "DISPUTED"
    touch(inv)
    grower = DB["growers"][inv["grower_id"]]
    grower["caretaking_balance_cents"] -= inv["total_cents"] - inv["paid_cents"]
    touch(grower)
    return ok_object(ser_ct_invoice(inv))


@bp.post("/packinghouse/caretaking-invoices/<rid>/reissue")
def reissue_ct_invoice(rid):
    require_roles(["PoolAccountant"])
    inv = get_or_404("ct_invoices", rid, "CaretakingInvoice")
    b = body()
    adjusted = as_int(req_field(b, "adjusted_total_cents"), "adjusted_total_cents")
    if inv["status"] != "DISPUTED":
        err(ERR_INVALID_STATE_TRANSITION, 409, "Invoice is not DISPUTED")
    if adjusted <= 0 or adjusted > inv["total_cents"] or adjusted < inv["paid_cents"]:
        err(
            ERR_INVALID_REQUEST,
            400,
            "adjusted_total_cents must be > 0, <= original total, and >= paid_cents",
        )
    inv["total_cents"] = adjusted
    inv["status"] = "ISSUED"
    touch(inv)
    grower = DB["growers"][inv["grower_id"]]
    grower["caretaking_balance_cents"] += adjusted - inv["paid_cents"]
    touch(grower)
    return ok_object(ser_ct_invoice(inv))


@bp.post("/packinghouse/caretaking-invoices/<rid>/void")
def void_ct_invoice(rid):
    require_roles(["PoolAccountant"])
    inv = get_or_404("ct_invoices", rid, "CaretakingInvoice")
    if inv["status"] != "DRAFT":
        err(ERR_INVALID_STATE_TRANSITION, 409, "Only DRAFT invoices can be voided")
    inv["status"] = "VOID"
    touch(inv)
    return ok_object(ser_ct_invoice(inv))
