from datetime import timedelta

from flask import Blueprint

import calc
import core
import gates
import ops
import serialize
from core import fail, get, new_row, now, parse_iso, rows, touch
from gates import check_state

bp = Blueprint("subscriptions", __name__)


def _live_visit_on_property(property_id):
    return any(v["status"] in ("EN_ROUTE", "IN_PROGRESS")
               for v in calc.children("visits", "property_id", property_id))


@bp.post("/property-care/subscriptions")
def create_subscription():
    gates.begin(["AccountManager", "PlatformAdmin"])
    body = gates.body_json()
    if isinstance(body.get("property_id"), str):
        gates.fetch_body_fk("properties", body["property_id"], "ERR_PROPERTY_NOT_FOUND")
    if isinstance(body.get("service_plan_id"), str):
        gates.fetch_body_fk("service_plans", body["service_plan_id"], "ERR_SERVICE_PLAN_NOT_FOUND")
    gates.validate_payload(body, [
        ("property_id", "string", True),
        ("service_plan_id", "string", True),
        ("started_on", "datetime", True),
    ])
    gates.fetch_body_fk("properties", body["property_id"], "ERR_PROPERTY_NOT_FOUND")
    gates.fetch_body_fk("service_plans", body["service_plan_id"], "ERR_SERVICE_PLAN_NOT_FOUND")
    sub = new_row(
        "subscriptions",
        property_id=body["property_id"],
        service_plan_id=body["service_plan_id"],
        status="PENDING_ACTIVATION",
        started_on=parse_iso(body["started_on"]),
        current_cycle_id=None,
        paused_at=None,
        resumed_at=None,
        cumulative_paused_days=0,
        pending_tier_change_plan_id=None,
        delinquent_since=None,
        cancelled_at=None,
    )
    return core.ok(serialize.subscription(sub), 201)


@bp.get("/property-care/subscriptions")
def list_subscriptions():
    gates.begin(["AccountManager", "PlatformAdmin", "Dispatcher", "Auditor", "Owner"])
    return gates.list_response("subscriptions", ["property_id", "service_plan_id", "status"],
                               serialize.subscription)


@bp.get("/property-care/subscriptions/<sid>")
def read_subscription(sid):
    role, user_id = gates.begin(["AccountManager", "PlatformAdmin", "Dispatcher", "Auditor", "Owner"])
    sub = gates.fetch_path("subscriptions", sid)
    prop = get("properties", sub["property_id"])
    gates.owner_scope(role, user_id, (prop or {}).get("owner_id"))
    return core.ok(serialize.subscription(sub))


@bp.post("/property-care/subscriptions/<sid>/activate")
def activate(sid):
    gates.begin(["AccountManager", "PlatformAdmin"])
    sub = gates.fetch_path("subscriptions", sid)
    check_state("subscription", sub, ["PENDING_ACTIVATION"])
    plan = calc.in_force_plan(sub)
    if plan is not None and plan["status"] == "RETIRED":
        fail("ERR_PLAN_RETIRED", "The service plan has been retired.")
    prop = get("properties", sub["property_id"])
    if prop is not None and prop["travel_zone"] == "OUT_OF_AREA":
        fail("ERR_PROPERTY_OUT_OF_AREA", "The property is out of the service area.")

    cycle = new_row(
        "billing_cycles",
        subscription_id=sub["id"],
        cycle_index=1,
        period_start=sub["started_on"],
        period_end=sub["started_on"] + timedelta(days=core.CYCLE_LENGTH_DAYS),
        status="OPEN",
        entitlement_granted_units=plan["included_visit_units"],
        entitlement_carried_in_units=0,
        entitlement_consumed_units=0,
        entitlement_remaining_units=plan["included_visit_units"],
        entitlement_expired_units=0,
        entitlement_carried_out_units=0,
        prorated_fee_cents=plan["monthly_fee_cents"],
        closed_at=None,
    )
    sub["status"] = "ACTIVE"
    sub["current_cycle_id"] = cycle["id"]
    touch(sub)
    return core.ok(serialize.subscription(sub))


@bp.post("/property-care/subscriptions/<sid>/pause")
def pause(sid):
    gates.begin(["AccountManager", "PlatformAdmin"])
    sub = gates.fetch_path("subscriptions", sid)
    check_state("subscription", sub, ["ACTIVE"])
    cycle = None
    if sub.get("current_cycle_id"):
        cycle = get("billing_cycles", sub["current_cycle_id"])
    if cycle is None or cycle["status"] != "OPEN":
        fail("ERR_NO_OPEN_CYCLE", "The subscription has no OPEN billing cycle.")

    sub["status"] = "PAUSED"
    sub["paused_at"] = now()
    plan = calc.in_force_plan(sub)
    cycle["prorated_fee_cents"] = calc.proration_pause(cycle, sub, plan)
    touch(cycle)
    _rewrite_subscription_fee_line(cycle)
    for v in calc.children("visits", "property_id", sub["property_id"]):
        if v["status"] == "SCHEDULED" and sub["paused_at"] <= v["scheduled_start_at"] < cycle["period_end"]:
            v["status"] = "DEFERRED"
            v["defer_reason"] = "SUBSCRIPTION_PAUSED"
            v["deferral_count"] += 1
            touch(v)
    touch(sub)
    return core.ok(serialize.subscription(sub))


def _rewrite_subscription_fee_line(cycle):
    for inv in calc.children("invoices", "billing_cycle_id", cycle["id"]):
        if inv["status"] != "DRAFT":
            continue
        for line in calc.invoice_lines_of(inv["id"]):
            if line["status"] == "ACTIVE" and line["line_type"] == "SUBSCRIPTION_FEE":
                line["amount_cents"] = cycle["prorated_fee_cents"]
                line["tax_cents"] = calc.invoice_line_tax(line)
                touch(line)
        calc.recompute_invoice(inv)
        touch(inv)


@bp.post("/property-care/subscriptions/<sid>/resume")
def resume(sid):
    gates.begin(["AccountManager", "PlatformAdmin"])
    sub = gates.fetch_path("subscriptions", sid)
    check_state("subscription", sub, ["PAUSED"])
    if sub.get("paused_at") is None:
        fail("ERR_NO_OPEN_CYCLE", "The subscription was never paused.")
    sub["status"] = "ACTIVE"
    sub["resumed_at"] = now()
    interval_days = calc.whole_days((sub["resumed_at"] - sub["paused_at"]).total_seconds())
    sub["cumulative_paused_days"] += max(0, interval_days)
    cycle = calc.open_cycle(sub)
    if cycle is not None:
        plan = calc.in_force_plan(sub)
        cycle["prorated_fee_cents"] = calc.proration_pause(cycle, sub, plan)
        touch(cycle)
        _rewrite_subscription_fee_line(cycle)
    touch(sub)
    return core.ok(serialize.subscription(sub))


@bp.post("/property-care/subscriptions/<sid>/tier-changes")
def tier_change(sid):
    gates.begin(["AccountManager", "PlatformAdmin"])
    sub = gates.fetch_path("subscriptions", sid)
    body = gates.body_json()
    if isinstance(body.get("service_plan_id"), str):
        gates.fetch_body_fk("service_plans", body["service_plan_id"], "ERR_SERVICE_PLAN_NOT_FOUND")
    # ---- G4 OCC (rung 16) ----
    expected = body.get("expected_subscription_version")
    if isinstance(expected, int) and not isinstance(expected, bool):
        if expected != sub["version"]:
            fail("ERR_STALE_SUBSCRIPTION_VERSION", "The subscription has been modified.")
    # ---- G5 ----
    if sub["status"] == "CANCELLED":
        fail("ERR_SUBSCRIPTION_CANCELLED", "The subscription is cancelled.")
    new_plan = get("service_plans", body.get("service_plan_id")) if isinstance(
        body.get("service_plan_id"), str) else None
    if new_plan is not None and new_plan["status"] == "RETIRED":
        fail("ERR_PLAN_RETIRED", "The service plan has been retired.")
    # ---- G9 ----
    cycle = calc.open_cycle(sub)
    if cycle is None:
        fail("ERR_NO_OPEN_CYCLE", "The subscription has no OPEN billing cycle.")
    # ---- G10 ----
    gates.validate_payload(body, [
        ("service_plan_id", "string", True),
        ("expected_subscription_version", "integer", True),
    ])
    gates.fetch_body_fk("service_plans", body["service_plan_id"], "ERR_SERVICE_PLAN_NOT_FOUND")

    old_plan = calc.in_force_plan(sub)
    cycle["prorated_fee_cents"] = calc.proration_tier_change(cycle, old_plan, new_plan)
    calc.tier_change_entitlement_rederivation(cycle, new_plan)
    touch(cycle)
    sub["service_plan_id"] = new_plan["id"]
    sub["pending_tier_change_plan_id"] = new_plan["id"]
    touch(sub)
    return core.ok(serialize.subscription(sub))


@bp.post("/property-care/subscriptions/<sid>/cancel")
def cancel(sid):
    gates.begin(["AccountManager", "PlatformAdmin"])
    sub = gates.fetch_path("subscriptions", sid)
    check_state("subscription", sub, ["ACTIVE", "PAUSED", "DELINQUENT"])
    if _live_visit_on_property(sub["property_id"]):
        fail("ERR_VISIT_IN_FLIGHT", "A visit on the property is still in flight.")
    sub["status"] = "CANCELLED"
    sub["cancelled_at"] = now()
    cycle = calc.open_cycle(sub)
    if cycle is not None:
        ops.close_cycle(cycle, calc.in_force_plan(sub), force_zero_carry_out=True)
    sub["current_cycle_id"] = None
    touch(sub)
    return core.ok(serialize.subscription(sub))


@bp.post("/property-care/subscriptions/<sid>/mark-delinquent")
def mark_delinquent(sid):
    gates.begin(["AccountManager", "PlatformAdmin"])
    sub = gates.fetch_path("subscriptions", sid)
    check_state("subscription", sub, ["ACTIVE"])
    invoices = _subscription_invoices(sub)
    qualifying = [i for i in invoices if _qualifies_delinquent(i)]
    if not qualifying:
        fail("ERR_NOT_YET_DELINQUENT", "No issued invoice has been outstanding long enough.")
    sub["status"] = "DELINQUENT"
    sub["delinquent_since"] = now()
    for inv in qualifying:
        inv["late_fee_cents"] = calc.late_fee(inv)
        calc.recompute_invoice(inv)
        touch(inv)
    touch(sub)
    return core.ok(serialize.subscription(sub))


def _qualifies_delinquent(inv):
    from datetime import timedelta as _td
    return (inv["status"] == "ISSUED" and inv["balance_due_cents"] > 0
            and inv.get("issued_at") is not None
            and inv["issued_at"] + _td(days=core.DELINQUENCY_THRESHOLD_DAYS) <= now())


def _subscription_invoices(sub):
    out = []
    for cycle in calc.children("billing_cycles", "subscription_id", sub["id"]):
        out.extend(calc.children("invoices", "billing_cycle_id", cycle["id"]))
    return out


@bp.post("/property-care/subscriptions/<sid>/clear-delinquency")
def clear_delinquency(sid):
    gates.begin(["AccountManager", "PlatformAdmin"])
    sub = gates.fetch_path("subscriptions", sid)
    check_state("subscription", sub, ["DELINQUENT"])
    for inv in _subscription_invoices(sub):
        if inv["status"] == "ISSUED" and inv["balance_due_cents"] > 0:
            fail("ERR_BALANCE_STILL_OUTSTANDING", "An issued invoice still carries a balance.")
    sub["status"] = "ACTIVE"
    sub["delinquent_since"] = None
    touch(sub)
    return core.ok(serialize.subscription(sub))


# ---------------------------------------------------------------------------
# Billing cycles
# ---------------------------------------------------------------------------
@bp.post("/property-care/subscriptions/<sid>/billing-cycles")
def open_next_cycle(sid):
    gates.begin(["AccountManager", "PlatformAdmin"])
    sub = gates.fetch_path("subscriptions", sid)
    if sub["status"] == "CANCELLED":
        fail("ERR_SUBSCRIPTION_CANCELLED", "The subscription is cancelled.")
    body = gates.body_json()
    gates.validate_payload(body, [("period_start", "datetime", True)])

    existing = calc.children("billing_cycles", "subscription_id", sub["id"])
    previous = None
    if existing:
        previous = sorted(existing, key=lambda c: c["cycle_index"])[-1]
    index = (previous["cycle_index"] + 1) if previous else 1
    carried_in = previous["entitlement_carried_out_units"] if previous else 0
    plan = get("service_plans", sub.get("pending_tier_change_plan_id")) or calc.in_force_plan(sub)
    period_start = parse_iso(body["period_start"])
    cycle = new_row(
        "billing_cycles",
        subscription_id=sub["id"],
        cycle_index=index,
        period_start=period_start,
        period_end=period_start + timedelta(days=core.CYCLE_LENGTH_DAYS),
        status="OPEN",
        entitlement_granted_units=plan["included_visit_units"] if plan else 0,
        entitlement_carried_in_units=carried_in,
        entitlement_consumed_units=0,
        entitlement_remaining_units=(plan["included_visit_units"] if plan else 0) + carried_in,
        entitlement_expired_units=0,
        entitlement_carried_out_units=0,
        prorated_fee_cents=plan["monthly_fee_cents"] if plan else 0,
        closed_at=None,
    )
    sub["current_cycle_id"] = cycle["id"]
    touch(sub)
    return core.ok(serialize.billing_cycle(cycle), 201)


@bp.get("/property-care/billing-cycles")
def list_cycles():
    gates.begin(["AccountManager", "PlatformAdmin", "Auditor", "Owner"])
    return gates.list_response("billing_cycles", ["subscription_id", "status"],
                               serialize.billing_cycle)


@bp.get("/property-care/billing-cycles/<cid>")
def read_cycle(cid):
    role, user_id = gates.begin(["AccountManager", "PlatformAdmin", "Auditor", "Owner"])
    cycle = gates.fetch_path("billing_cycles", cid)
    sub = get("subscriptions", cycle["subscription_id"])
    prop = get("properties", (sub or {}).get("property_id"))
    gates.owner_scope(role, user_id, (prop or {}).get("owner_id"))
    return core.ok(serialize.billing_cycle(cycle))


@bp.post("/property-care/billing-cycles/<cid>/close")
def close_cycle(cid):
    gates.begin(["AccountManager", "PlatformAdmin"])
    cycle = gates.fetch_path("billing_cycles", cid)
    check_state("billing_cycle", cycle, ["OPEN"])
    for v in rows("visits"):
        if v.get("billing_cycle_id") == cycle["id"] and v["status"] in ("EN_ROUTE", "IN_PROGRESS"):
            fail("ERR_CYCLE_HAS_LIVE_VISIT", "A visit bound to this cycle is still live.")
    for inv in calc.children("invoices", "billing_cycle_id", cycle["id"]):
        if inv["status"] not in ("ISSUED", "PAID", "PARTIALLY_PAID", "VOID", "DRAFT"):
            fail("ERR_INVALID_STATE_TRANSITION", "An invoice on this cycle is disputed.")
    sub = get("subscriptions", cycle["subscription_id"])
    ops.close_cycle(cycle, calc.in_force_plan(sub))
    return core.ok(serialize.billing_cycle(cycle))
