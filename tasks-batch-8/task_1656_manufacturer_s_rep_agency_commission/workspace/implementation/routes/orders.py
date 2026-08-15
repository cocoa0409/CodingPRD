"""Orders: booking + attribution, ship, invoice, mark_paid, cancel, split override,
and read-only order-split endpoints."""
from datetime import timedelta
from flask import Blueprint, request

import db
from db import now, touch
from errors import err, not_found, invalid_request
from middleware import api, body, ctx, ALL_ROLES
from response import success_object, success_list, success_array
import services
from services import (
    attribute_line, split_rows_for, allocate, post_entry, recompute_rep,
    active_agreement, active_schedule, family_base_rate, select_tier,
    attainment_bp, rhu_div,
)

bp = Blueprint("orders", __name__)


def _get_order(oid):
    order = db.orders.get(oid)
    if order is None:
        raise not_found("Order")
    return order


def _order_principal_owned(oid):
    order = _get_order(oid)
    if ctx()["user_id"] != order["principal_id"]:
        raise err("ERR_FORBIDDEN_NOT_OWNER",
                  "PrincipalOps may only act on orders of its own principal")
    return order


# ---------------------------------------------------------------------------
# Create (booking + attribution)
# ---------------------------------------------------------------------------
@bp.route("/rep-agency/orders", methods=["POST"])
@api(["AgencyAdmin"])
def create_order():
    data = body()
    customer_id = data.get("customer_id")
    principal_id = data.get("principal_id")
    # structural shape first (body must be minimally parseable)
    if not isinstance(customer_id, str):
        raise invalid_request("customer_id is required")
    if not isinstance(principal_id, str):
        raise invalid_request("principal_id is required")
    ref = data.get("external_order_ref")
    if not isinstance(ref, str) or not ref:
        raise invalid_request("external_order_ref is required")
    placed_at = db.parse_ts(data.get("placed_at"))
    if placed_at is None:
        raise invalid_request("placed_at must be a valid ISO-8601 timestamp")
    raw_lines = data.get("lines")
    if not isinstance(raw_lines, list) or not raw_lines:
        raise invalid_request("lines must be a non-empty array")
    for ln in raw_lines:
        if not isinstance(ln, dict):
            raise invalid_request("each line must be an object")
        if not isinstance(ln.get("line_id"), str) or not ln.get("line_id"):
            raise invalid_request("each line requires a line_id")
        if not isinstance(ln.get("family_code"), str) or not ln.get("family_code"):
            raise invalid_request("each line requires a family_code")
        if not db.is_int(ln.get("quantity")):
            raise invalid_request("line quantity must be an integer")
        if not db.is_int(ln.get("unit_price_cents")):
            raise invalid_request("line unit_price_cents must be an integer")
        for opt in ("spec_territory_code", "ship_to_territory_code"):
            if ln.get(opt) is not None and not isinstance(ln.get(opt), str):
                raise invalid_request("%s must be a string" % opt)
    # existence (body FK ids, left-to-right)
    customer = db.customers.get(customer_id)
    if customer is None:
        raise not_found("Customer")
    principal = db.principals.get(principal_id)
    if principal is None:
        raise not_found("Principal")
    # linked-entity gates
    if principal["status"] == "TERMINATED":
        raise err("ERR_LINE_TERMINATED", "A TERMINATED principal accepts no new orders")
    agreement = active_agreement(principal_id)
    if agreement is None:
        raise err("ERR_AGREEMENT_NOT_ACTIVE",
                  "The principal has no ACTIVE territory agreement")
    lines = []
    for ln in raw_lines:
        line = {
            "line_id": ln["line_id"],
            "family_code": ln["family_code"],
            "quantity": ln["quantity"],
            "unit_price_cents": ln["unit_price_cents"],
            "spec_territory_code": ln.get("spec_territory_code") or customer["spec_territory_code"],
            "ship_to_territory_code": ln.get("ship_to_territory_code") or customer["ship_to_territory_code"],
            "shipped_qty": 0,
            "returned_qty": 0,
            "applied_rate_bp": None,
            "commission_cents": None,
            "protected_registration_id": None,
        }
        lines.append(line)
    covered = set(agreement["territory_codes"] or [])
    for line in lines:
        if (line["spec_territory_code"] not in covered
                or line["ship_to_territory_code"] not in covered):
            raise err("ERR_TERRITORY_NOT_COVERED",
                      "A line territory is outside the ACTIVE agreement")
    schedule = active_schedule(principal_id)
    if schedule is None:
        raise err("ERR_NO_ACTIVE_RATE_SCHEDULE",
                  "The principal has no ACTIVE rate schedule")
    for line in lines:
        if family_base_rate(schedule, line["family_code"]) is None:
            raise err("ERR_UNKNOWN_FAMILY_CODE",
                      "family_code %s is not in the ACTIVE rate schedule" % line["family_code"])
    # temporal
    if placed_at > now():
        raise err("ERR_FUTURE_DATED", "placed_at is after the current logical clock")
    # shape / uniqueness
    seen = set()
    for line in lines:
        if line["line_id"] in seen:
            raise invalid_request("duplicate line_id within order")
        seen.add(line["line_id"])
        if line["quantity"] <= 0:
            raise invalid_request("line quantity must be positive")
        if line["unit_price_cents"] <= 0:
            raise invalid_request("line unit_price_cents must be positive")
    for other in db.orders.values():
        if (other["principal_id"] == principal_id
                and other["external_order_ref"] == ref
                and other["fulfillment_status"] != "CANCELLED"):
            raise err("ERR_DUPLICATE_EXTERNAL_REF",
                      "external_order_ref already used by a non-CANCELLED order of this principal")
    order = {
        "customer_id": customer_id,
        "principal_id": principal_id,
        "external_order_ref": ref,
        "placed_at": placed_at,
        "lines": lines,
        "fulfillment_status": "PLACED",
        "commission_status": "ATTRIBUTED",
        "shipped_at": None,
        "invoiced_at": None,
        "paid_at": None,
    }
    db.stamp_new(order)
    db.orders[order["id"]] = order
    for line in lines:
        attribute_line(order, line, agreement)
    return success_object(order, 201)


@bp.route("/rep-agency/orders", methods=["GET"])
@api(ALL_ROLES)
def list_orders():
    items = list(db.orders.values())
    for param in ("customer_id", "principal_id", "fulfillment_status"):
        value = request.args.get(param)
        if value is not None:
            items = [o for o in items if o[param] == value]
    return success_list(items)


@bp.route("/rep-agency/orders/<oid>", methods=["GET"])
@api(ALL_ROLES)
def get_order(oid):
    return success_object(_get_order(oid))


# ---------------------------------------------------------------------------
# Fulfillment transitions
# ---------------------------------------------------------------------------
@bp.route("/rep-agency/orders/<oid>/ship", methods=["POST"])
@api(["PrincipalOps"])
def ship_order(oid):
    order = _order_principal_owned(oid)
    if order["fulfillment_status"] != "PLACED":
        raise err("ERR_INVALID_STATE_TRANSITION",
                  "Only a PLACED order can be shipped")
    order["fulfillment_status"] = "SHIPPED"
    order["shipped_at"] = now()
    for line in order["lines"]:
        line["shipped_qty"] = line["quantity"]
    touch(order)
    return success_object(order)


@bp.route("/rep-agency/orders/<oid>/invoice", methods=["POST"])
@api(["PrincipalOps"])
def invoice_order(oid):
    order = _order_principal_owned(oid)
    if order["fulfillment_status"] != "SHIPPED":
        raise err("ERR_INVALID_STATE_TRANSITION",
                  "Only a SHIPPED order can be invoiced")
    principal = db.principals[order["principal_id"]]
    # linked-entity gate: an ACTIVE rate schedule must exist at invoice time
    schedule = active_schedule(order["principal_id"])
    if schedule is None:
        raise err("ERR_NO_ACTIVE_RATE_SCHEDULE",
                  "The principal has no ACTIVE rate schedule at invoice time")
    for line in order["lines"]:
        if family_base_rate(schedule, line["family_code"]) is None:
            raise err("ERR_UNKNOWN_FAMILY_CODE",
                      "family_code %s is not in the ACTIVE rate schedule" % line["family_code"])
    # temporal gate: termination tail eligibility
    if principal["status"] == "TERMINATED":
        tail_days = 180
        terminated = [a for a in db.agreements.values()
                      if a["principal_id"] == principal["id"] and a["status"] == "TERMINATED"]
        if terminated:
            tail_days = max(terminated, key=lambda a: a["updated_at"])["tail_period_days"]
        eff = principal["termination_effective_at"]
        tail_end = eff + timedelta(days=tail_days)
        if not (order["placed_at"] < eff and now() <= tail_end):
            raise err("ERR_TAIL_PERIOD_EXPIRED",
                      "Invoice is outside the termination tail window")
    # pinned rating order: pool EXCLUDING this order -> attainment -> tier
    attain = attainment_bp(principal)
    tier = select_tier(schedule, attain)
    mult = tier["multiplier_bp"] if tier else 10000
    bonus = schedule["registration_bonus_bp"]
    rep_totals = {}
    rep_order_seq = []
    for line in order["lines"]:
        base = family_base_rate(schedule, line["family_code"])
        effective_bp = (base * mult) // 10000
        if line.get("protected_registration_id"):
            effective_bp += bonus
        net = line["quantity"] * line["unit_price_cents"]
        commission = rhu_div(net * effective_bp, 10000)
        line["applied_rate_bp"] = effective_bp
        line["commission_cents"] = commission
        rows = split_rows_for(order["id"], line["line_id"])
        alloc = allocate(commission, rows)
        for row in rows:
            if row["rep_id"] is None:
                continue  # house share: no ledger entry
            cents = alloc.get(row["id"], 0)
            if row["rep_id"] not in rep_totals:
                rep_totals[row["rep_id"]] = 0
                rep_order_seq.append(row["rep_id"])
            rep_totals[row["rep_id"]] += cents
    invoiced_at = now()
    order["invoiced_at"] = invoiced_at
    order["fulfillment_status"] = "INVOICED"
    order["commission_status"] = "ACCRUED"
    # one ACCRUAL entry per (rep, order)
    for rep_id in rep_order_seq:
        total = rep_totals[rep_id]
        if total == 0:
            continue
        post_entry(rep_id=rep_id, principal_id=order["principal_id"],
                   order_id=order["id"], statement_id=None, etype="ACCRUAL",
                   amount_cents=total, business_date=invoiced_at)
    for rep_id in rep_order_seq:
        recompute_rep(rep_id)
    # only after the order's own rate is fixed does it join the YTD pool
    principal["credited_ytd_sales_cents"] += sum(
        ln["quantity"] * ln["unit_price_cents"] for ln in order["lines"])
    touch(principal)
    touch(order)
    return success_object(order)


@bp.route("/rep-agency/orders/<oid>/mark_paid", methods=["POST"])
@api(["PrincipalOps"])
def mark_paid(oid):
    order = _order_principal_owned(oid)
    if order["fulfillment_status"] != "INVOICED":
        raise err("ERR_INVALID_STATE_TRANSITION",
                  "Only an INVOICED order can be marked paid")
    order["fulfillment_status"] = "PAID"
    order["paid_at"] = now()
    touch(order)
    return success_object(order)


@bp.route("/rep-agency/orders/<oid>/cancel", methods=["POST"])
@api(["AgencyAdmin"])
def cancel_order(oid):
    order = _get_order(oid)
    if order["fulfillment_status"] != "PLACED":
        raise err("ERR_INVALID_STATE_TRANSITION",
                  "Only a PLACED order can be cancelled")
    order["fulfillment_status"] = "CANCELLED"
    order["commission_status"] = "CLOSED"
    touch(order)
    return success_object(order)


# ---------------------------------------------------------------------------
# Split override (OCC-guarded)
# ---------------------------------------------------------------------------
@bp.route("/rep-agency/orders/<oid>/splits", methods=["PUT"])
@api(["AgencyAdmin", "Rep"])
def put_splits(oid):
    order = _get_order(oid)
    data = body()
    raw = data.get("splits")
    if not isinstance(raw, list) or not raw:
        raise invalid_request("splits must be a non-empty array")
    for row in raw:
        if not isinstance(row, dict) or not isinstance(row.get("line_id"), str):
            raise invalid_request("each split row requires a line_id")
        if row.get("rep_id") is not None and not isinstance(row.get("rep_id"), str):
            raise invalid_request("rep_id must be a string or null")
    # body FK existence (priority 3)
    for row in raw:
        if row.get("rep_id") is not None and row["rep_id"] not in db.reps:
            raise not_found("Rep")
    # ownership (priority 4): a Rep caller must hold a split row on the order
    if ctx()["role"] == "Rep":
        uid = ctx()["user_id"]
        if not any(s["rep_id"] == uid for s in split_rows_for(oid)):
            raise err("ERR_FORBIDDEN_NOT_OWNER",
                      "Rep holds no split row on this order")
    # state (priority 5)
    if order["commission_status"] != "ATTRIBUTED":
        raise err("ERR_SPLITS_LOCKED",
                  "Splits are locked once the order is no longer ATTRIBUTED")
    # OCC (priority 6)
    eov = data.get("expected_order_version")
    if eov is None:
        raise invalid_request("expected_order_version is required")
    if not db.is_int(eov):
        raise invalid_request("expected_order_version must be an integer")
    if eov != order["version"]:
        raise err("ERR_STALE_ORDER_VERSION",
                  "expected_order_version does not match the order's version")
    # shape (priority 9): every line covered, each line sums to exactly 10000
    order_line_ids = [ln["line_id"] for ln in order["lines"]]
    sums = {}
    for row in raw:
        share = row.get("share_bp")
        if not db.is_int(share):
            raise invalid_request("share_bp must be an integer")
        if row["line_id"] not in order_line_ids or share < 0:
            raise err("ERR_SPLIT_SUM_INVALID",
                      "Split rows must cover only order lines with non-negative shares")
        sums[row["line_id"]] = sums.get(row["line_id"], 0) + share
    for lid in order_line_ids:
        if sums.get(lid) != 10000:
            raise err("ERR_SPLIT_SUM_INVALID",
                      "Split rows for line %s do not sum to 10000 bp" % lid)
    # replace all prior rows with OVERRIDE rows
    for old in split_rows_for(oid):
        del db.splits[old["id"]]
    new_rows = []
    for row in raw:
        new_rows.append(services._make_split(oid, row["line_id"], row.get("rep_id"),
                                             "OVERRIDE", row["share_bp"], True))
    touch(order)
    return success_array(new_rows)


# ---------------------------------------------------------------------------
# OrderSplit reads
# ---------------------------------------------------------------------------
@bp.route("/rep-agency/order-splits", methods=["GET"])
@api(ALL_ROLES)
def list_splits():
    items = list(db.splits.values())
    order_id = request.args.get("order_id")
    if order_id is not None:
        items = [s for s in items if s["order_id"] == order_id]
    rep_id = request.args.get("rep_id")
    if rep_id is not None:
        items = [s for s in items if s["rep_id"] == rep_id]
    return success_list(items)


@bp.route("/rep-agency/order-splits/<sid>", methods=["GET"])
@api(ALL_ROLES)
def get_split(sid):
    row = db.splits.get(sid)
    if row is None:
        raise not_found("OrderSplit")
    return success_object(row)
