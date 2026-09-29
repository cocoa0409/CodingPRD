"""Stateful recomputes, cascades and lookup helpers."""

from datetime import timedelta
from decimal import Decimal

from db import base_record, by_seq, clock, db, mark_fresh, touch
from errors import ApiError
from services import calculations as calc

# ------------------------------------------------------------------ id resolution

_NOT_FOUND = {
    "service_members": "ERR_SERVICE_MEMBER_NOT_FOUND",
    "orders": "ERR_ORDER_NOT_FOUND",
    "counseling_sessions": "ERR_COUNSELING_SESSION_NOT_FOUND",
    "entitlements": "ERR_ENTITLEMENT_NOT_FOUND",
    "tsps": "ERR_TSP_NOT_FOUND",
    "capacity_blocks": "ERR_CAPACITY_BLOCK_NOT_FOUND",
    "shipments": "ERR_SHIPMENT_NOT_FOUND",
    "pro_gear_declarations": "ERR_PRO_GEAR_DECLARATION_NOT_FOUND",
    "sit_authorizations": "ERR_SIT_AUTHORIZATION_NOT_FOUND",
    "claims": "ERR_CLAIM_NOT_FOUND",
    "claim_items": "ERR_CLAIM_ITEM_NOT_FOUND",
    "ppm_submissions": "ERR_PPM_SUBMISSION_NOT_FOUND",
    "notifications": "ERR_NOTIFICATION_NOT_FOUND",
}


def must_get(collection, identifier):
    store = getattr(db, collection)
    if not isinstance(identifier, str) or identifier not in store:
        raise ApiError(_NOT_FOUND[collection], "Referenced %s does not exist." % collection[:-1])
    return store[identifier]


def get_member(identifier):
    return must_get("service_members", identifier)


def get_order(identifier):
    return must_get("orders", identifier)


def get_session(identifier):
    return must_get("counseling_sessions", identifier)


def get_entitlement(identifier):
    return must_get("entitlements", identifier)


def get_tsp(identifier):
    return must_get("tsps", identifier)


def get_block(identifier):
    return must_get("capacity_blocks", identifier)


def get_shipment(identifier):
    return must_get("shipments", identifier)


def get_declaration(identifier):
    return must_get("pro_gear_declarations", identifier)


def get_sit(identifier):
    return must_get("sit_authorizations", identifier)


def get_claim(identifier):
    return must_get("claims", identifier)


def get_claim_item(identifier):
    return must_get("claim_items", identifier)


def get_ppm(identifier):
    return must_get("ppm_submissions", identifier)


def get_notification(identifier):
    return must_get("notifications", identifier)


# ------------------------------------------------------------- ownership chains


def member_of_order(order):
    return order["service_member_id"]


def member_of_session(session):
    return member_of_order(db.orders[session["order_id"]])


def member_of_entitlement(entitlement):
    return member_of_order(db.orders[entitlement["order_id"]])


def member_of_shipment(shipment):
    return member_of_order(db.orders[shipment["order_id"]])


def member_of_claim(claim):
    return member_of_shipment(db.shipments[claim["shipment_id"]])


# ------------------------------------------------------------- inclusion helpers

LEDGER_WEIGHT_STATES = ("ESTIMATED", "ACTUAL_RECORDED", "DISPUTED", "RECONCILED")


def in_inclusion_set(shipment):
    return (
        shipment["weight_recon_status"] in LEDGER_WEIGHT_STATES
        and shipment["movement_status"] != "CANCELLED"
    )


def shipments_of_entitlement(entitlement_id):
    return by_seq(
        [s for s in db.shipments.values() if s["entitlement_id"] == entitlement_id]
    )


def contributing_shipments(entitlement_id):
    return [s for s in shipments_of_entitlement(entitlement_id) if in_inclusion_set(s)]


# ------------------------------------------------------- shipment billable weight


def recompute_shipment_weight(shipment):
    """calculations.shipment_billable_weight, steps one and two."""
    entitlement = db.entitlements.get(shipment["entitlement_id"])
    member_cap = entitlement["pro_gear_member_allowance_lbs"] if entitlement else 0
    spouse_cap = entitlement["pro_gear_spouse_allowance_lbs"] if entitlement else 0

    member_verified = 0
    spouse_verified = 0
    for declaration in db.pro_gear_declarations.values():
        if declaration["shipment_id"] != shipment["id"]:
            continue
        if declaration["status"] not in ("VERIFIED", "PARTIALLY_VERIFIED"):
            continue
        if declaration["owner"] == "MEMBER":
            member_verified += declaration["verified_weight_lbs"]
        else:
            spouse_verified += declaration["verified_weight_lbs"]

    excluded = min(member_verified, member_cap) + min(spouse_verified, spouse_cap)

    status = shipment["weight_recon_status"]
    if status == "ESTIMATED":
        gross = shipment["estimated_gross_lbs"] or 0
        billable = max(0, gross - excluded)
        basis = "ESTIMATED"
    elif status in ("ACTUAL_RECORDED", "DISPUTED", "RECONCILED"):
        gross = shipment["actual_gross_lbs"]
        tare = shipment["actual_tare_lbs"]
        if gross is None:
            billable = 0
            basis = "NONE"
        else:
            net = gross - (tare or 0)
            shipment["net_actual_lbs"] = net
            billable = max(0, net - excluded)
            basis = "ACTUAL"
    else:
        billable = 0
        basis = "NONE"

    changed = (
        shipment["pro_gear_excluded_lbs"] != excluded
        or shipment["billable_weight_lbs"] != billable
        or shipment["billable_basis"] != basis
    )
    weight_moved = shipment["billable_weight_lbs"] != billable
    shipment["pro_gear_excluded_lbs"] = excluded
    shipment["billable_weight_lbs"] = billable
    shipment["billable_basis"] = basis
    if changed:
        touch(shipment)
    if weight_moved and shipment["capacity_block_id"]:
        block = db.capacity_blocks.get(shipment["capacity_block_id"])
        if block is not None:
            recompute_capacity_block(block, force_touch=False)
    return shipment


# ----------------------------------------------------------- entitlement ledger


def recompute_entitlement_allowance(entitlement):
    """Re-derive dependent status, base allowance and cap from the orders."""
    order = db.orders[entitlement["order_id"]]
    dep_status = calc.dependent_status_effective(
        order["dependents_count_at_issue"], order["is_dependent_restricted"]
    )
    base = calc.base_weight_allowance(
        entitlement["rank_code_at_authorization"], dep_status, order["move_type"]
    )
    entitlement["dependent_status_effective"] = dep_status
    entitlement["base_weight_allowance_lbs"] = base
    entitlement["total_billable_cap_lbs"] = base + entitlement["admin_weight_bump_lbs"]


def ledger_view(entitlement):
    contributing = contributing_shipments(entitlement["id"])
    charged = sum(s["billable_weight_lbs"] for s in contributing)
    excluded = sum(s["pro_gear_excluded_lbs"] for s in contributing)
    breakdown = calc.excess_cost_breakdown(
        charged, entitlement["total_billable_cap_lbs"], entitlement["excess_cost_waived_usd"]
    )
    breakdown["charged_billable_weight_lbs"] = charged
    breakdown["pro_gear_excluded_total_lbs"] = excluded
    breakdown["contributing_shipment_count"] = len(contributing)
    return breakdown


def recompute_entitlement_ledger(entitlement, cascade=True):
    """PRD §2.8 — recomputed from scratch, never incremented."""
    view = ledger_view(entitlement)
    entitlement["charged_billable_weight_lbs"] = view["charged_billable_weight_lbs"]
    entitlement["pro_gear_excluded_total_lbs"] = view["pro_gear_excluded_total_lbs"]
    entitlement["excess_weight_lbs"] = view["excess_weight_lbs"]
    entitlement["gross_excess_cost_usd"] = view["gross_excess_cost_usd"]
    entitlement["excess_cost_waived_usd"] = view["excess_cost_waived_usd"]
    entitlement["excess_cost_due_usd"] = view["excess_cost_due_usd"]
    touch(entitlement)
    if cascade:
        apply_suspension_cascade(entitlement)
    return entitlement


def apply_suspension_cascade(entitlement):
    """Ledger chain levels three and four (PRD §2.9)."""
    if (
        entitlement["status"] == "AUTHORIZED"
        and entitlement["excess_cost_due_usd"] > calc.EXCESS_SUSPEND_THRESHOLD_USD
    ):
        entitlement["status"] = "SUSPENDED"
        entitlement["suspension_reason"] = "EXCESS_COST_UNPAID"
        touch(entitlement)
        for shipment in shipments_of_entitlement(entitlement["id"]):
            if shipment["movement_status"] == "AWARDED":
                shipment["movement_status"] = "ON_HOLD"
                shipment["hold_reason"] = "ENTITLEMENT_SUSPENDED"
                touch(shipment)


def close_entitlement_if_complete(entitlement):
    """PRD §3.8 — reconciliation is where a move ends."""
    shipments = shipments_of_entitlement(entitlement["id"])
    non_cancelled = [s for s in shipments if s["movement_status"] != "CANCELLED"]
    if not non_cancelled:
        return
    for shipment in non_cancelled:
        if shipment["weight_recon_status"] != "RECONCILED":
            return
    if entitlement["excess_cost_due_usd"] != Decimal("0.00"):
        return
    if entitlement["status"] != "AUTHORIZED":
        return
    entitlement["status"] = "CLOSED"
    touch(entitlement)
    order = db.orders.get(entitlement["order_id"])
    if order is not None and order["status"] in ("ISSUED", "AMENDED"):
        order["status"] = "CLOSED"
        touch(order)


# --------------------------------------------------------------- capacity blocks


def derive_block_status(block):
    tsp = db.tsps[block["tsp_id"]]
    if (
        block["committed_lbs"] >= block["total_capacity_lbs"]
        or tsp["status"] == "SUSPENDED"
    ):
        return "CLOSED"
    if (
        block["committed_lbs"] >= calc.restrict_threshold(block["total_capacity_lbs"])
        or tsp["status"] == "PROBATION"
    ):
        return "RESTRICTED"
    return "OPEN"


def recompute_capacity_block(block, force_touch=True):
    """Capacity conservation invariant (PRD §2.8) plus status re-derivation."""
    general = 0
    short_notice = 0
    for shipment in db.shipments.values():
        if shipment["capacity_block_id"] != block["id"]:
            continue
        if shipment["movement_status"] == "CANCELLED":
            continue
        if shipment["is_short_notice"]:
            short_notice += shipment["billable_weight_lbs"]
        else:
            general += shipment["billable_weight_lbs"]
    status = None
    changed = (
        block["committed_general_lbs"] != general
        or block["committed_short_notice_lbs"] != short_notice
    )
    block["committed_general_lbs"] = general
    block["committed_short_notice_lbs"] = short_notice
    block["committed_lbs"] = general + short_notice
    status = derive_block_status(block)
    if block["status"] != status:
        changed = True
    block["status"] = status
    if changed or force_touch:
        touch(block)
    return block


def apply_tsp_standing_to_blocks(tsp):
    """Performance chain level four (PRD §3.10)."""
    for block in by_seq(list(db.capacity_blocks.values())):
        if block["tsp_id"] != tsp["id"]:
            continue
        if tsp["status"] == "PROBATION" and block["status"] == "OPEN":
            block["status"] = "RESTRICTED"
            touch(block)
        elif tsp["status"] == "SUSPENDED" and block["status"] in ("OPEN", "RESTRICTED"):
            block["status"] = "CLOSED"
            touch(block)


def recompute_tsp_performance(tsp):
    """Performance chain levels two and three (PRD §3.10)."""
    count = 0
    total = Decimal("0.00")
    for claim in db.claims.values():
        if claim["status"] != "SETTLED":
            continue
        shipment = db.shipments.get(claim["shipment_id"])
        if shipment is None or shipment["tsp_id"] != tsp["id"]:
            continue
        count += 1
        total += Decimal(claim["settlement_total_usd"])
    total = calc.money(total)
    score = calc.performance_score(count, total)
    tsp["settled_claim_count"] = count
    tsp["claim_settlement_total_usd"] = total
    tsp["performance_score"] = score
    tsp["status"] = calc.standing_for_score(score)
    touch(tsp)
    apply_tsp_standing_to_blocks(tsp)
    return tsp


# ------------------------------------------------------- member shipment counter


def recompute_member_shipment_count(member):
    count = 0
    for shipment in db.shipments.values():
        order = db.orders.get(shipment["order_id"])
        if order is None or order["service_member_id"] != member["id"]:
            continue
        if shipment["movement_status"] in ("DELIVERED", "CANCELLED"):
            continue
        count += 1
    if member["active_shipment_count"] != count:
        member["active_shipment_count"] = count
        touch(member)
    return member


# ---------------------------------------------------------------- notifications


def create_notification(shipment_id, notification_type):
    """PRD §2.11 — a notification obligation, not a dispatch."""
    trigger_at = clock()
    sla_hours = calc.NOTIFICATION_SLA_HOURS[notification_type]
    record = base_record()
    record.update(
        {
            "shipment_id": shipment_id,
            "notification_type": notification_type,
            "trigger_event_at": trigger_at,
            "sla_hours": sla_hours,
            "due_by": trigger_at + timedelta(hours=sla_hours),
            "channel": None,
            "sent_at": None,
            "hours_late": Decimal("0.00"),
            "status": "PENDING",
        }
    )
    mark_fresh(record)
    db.notifications[record["id"]] = record
    return record


# -------------------------------------------------------------- claim totals


def recompute_claim_totals(claim):
    items = [i for i in db.claim_items.values() if i["claim_id"] == claim["id"]]
    total = calc.money(sum((Decimal(i["replacement_cost_usd"]) for i in items), Decimal("0.00")))
    claim["item_count"] = len(items)
    claim["claimed_total_usd"] = total
    touch(claim)
    return claim


def claim_items_of(claim):
    return by_seq([i for i in db.claim_items.values() if i["claim_id"] == claim["id"]])
