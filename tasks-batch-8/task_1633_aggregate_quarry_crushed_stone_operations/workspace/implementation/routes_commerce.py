"""Routes: freight zones, sales orders, scale tickets, royalty agreements and
statements, MSHA inspections/citations, training records, reclamation bonds,
truck queue entries."""

from datetime import timedelta
from decimal import Decimal

from flask import Blueprint

from core import (
    base_resource,
    body,
    list_response,
    logical_now_iso,
    logical_today,
    ok_object,
    require_roles,
    touch,
)
from db import db
from errors import (
    err_adjustment_below_reserved,
    err_agreement_already_active,
    err_bond_below_required,
    err_invalid_request,
    err_invalid_state,
    err_not_found,
    err_open_citations,
    err_over_shipment,
    err_queue_empty,
    err_royalty_agreement_required,
    err_scale_not_certified,
    err_site_posture_blocked,
    err_sod_violation,
    err_spec_retired,
    err_stale_version,
    err_statement_locked,
    err_statement_not_chronological,
    err_statement_period_overlap,
    err_stockpile_quarantined,
    err_tare_variance,
    err_truck_already_queued,
    err_truck_overweight,
    err_zone_inactive,
)
from routes_core import (
    ALL_ROLES,
    _qs,
    get_or_404,
    req_enum,
    req_field,
    req_number,
    req_positive,
    req_string,
)
from services import (
    D,
    active_agreement_covering,
    compute_quote,
    parse_iso_date,
    parse_iso_datetime,
    q,
    recompute_site,
    refresh_stockpile,
    scale_usable,
    ticket_date,
    to_float,
)

bp = Blueprint("commerce_routes", __name__)


# ---------------------------------------------------------------------------
# Freight zones
# ---------------------------------------------------------------------------

@bp.route("/freight-zones", methods=["POST"])
def create_zone():
    require_roles(["QuarryAdmin"])
    data = body()
    code = req_string(data, "zone_code")
    distance = req_positive(data, "distance_miles")
    freight = req_number(data, "base_freight_per_ton")
    if D(freight) < 0:
        raise err_invalid_request("base_freight_per_ton must be >= 0")
    for other in db.freight_zones.values():
        if other["zone_code"] == code:
            raise err_invalid_request("zone_code must be unique")
    zone = base_resource()
    zone.update(
        {
            "zone_code": code,
            "distance_miles": distance,
            "base_freight_per_ton": freight,
            "status": "ACTIVE",
        }
    )
    db.freight_zones[zone["id"]] = zone
    return ok_object(zone, 201)


@bp.route("/freight-zones", methods=["GET"])
def list_zones():
    require_roles(ALL_ROLES)
    return list_response(db.freight_zones, {"status": _qs("status")})


@bp.route("/freight-zones/<zid>", methods=["GET"])
def get_zone(zid):
    require_roles(ALL_ROLES)
    return ok_object(get_or_404(db.freight_zones, zid))


@bp.route("/freight-zones/<zid>/deactivate", methods=["POST"])
def deactivate_zone(zid):
    require_roles(["QuarryAdmin"])
    zone = get_or_404(db.freight_zones, zid)
    if zone["status"] != "ACTIVE":
        raise err_invalid_state("Only ACTIVE zones can be deactivated")
    zone["status"] = "INACTIVE"
    touch(zone)
    return ok_object(zone)


# ---------------------------------------------------------------------------
# Sales orders
# ---------------------------------------------------------------------------

@bp.route("/sales-orders", methods=["POST"])
def create_order():
    require_roles(["SalesAgent"])
    data = body()
    site_id = req_string(data, "site_id")
    spec_id = req_string(data, "product_spec_id")
    zone_id = req_string(data, "freight_zone_id")
    customer = req_string(data, "customer_name")
    quantity = req_positive(data, "quantity_tons")
    get_or_404(db.sites, site_id)
    spec = get_or_404(db.product_specs, spec_id)
    zone = get_or_404(db.freight_zones, zone_id)
    if spec["status"] != "ACTIVE":
        raise err_spec_retired("Spec is RETIRED")
    if zone["status"] != "ACTIVE":
        raise err_zone_inactive("Zone is INACTIVE")
    quote = compute_quote(spec, zone, quantity)
    order = base_resource()
    order.update(
        {
            "site_id": site_id,
            "product_spec_id": spec_id,
            "freight_zone_id": zone_id,
            "customer_name": customer,
            "quantity_tons": quantity,
            "stockpile_id": None,
            "prices_pinned": False,
            "fulfilled_tons": 0.0,
            "status": "QUOTED",
        }
    )
    order.update(quote)
    db.sales_orders[order["id"]] = order
    return ok_object(order, 201)


@bp.route("/sales-orders", methods=["GET"])
def list_orders():
    require_roles(ALL_ROLES)
    filters = {
        "site_id": _qs("site_id"),
        "product_spec_id": _qs("product_spec_id"),
        "freight_zone_id": _qs("freight_zone_id"),
        "stockpile_id": _qs("stockpile_id"),
        "status": _qs("status"),
    }
    return list_response(db.sales_orders, filters)


@bp.route("/sales-orders/<oid>", methods=["GET"])
def get_order(oid):
    require_roles(ALL_ROLES)
    return ok_object(get_or_404(db.sales_orders, oid))


@bp.route("/sales-orders/<oid>/confirm", methods=["POST"])
def confirm_order(oid):
    require_roles(["SalesAgent"])
    order = get_or_404(db.sales_orders, oid)
    if order["status"] != "QUOTED":
        raise err_invalid_state("Only QUOTED orders can be confirmed")
    spec = db.product_specs[order["product_spec_id"]]
    zone = db.freight_zones[order["freight_zone_id"]]
    if spec["status"] != "ACTIVE":
        raise err_spec_retired("Spec is RETIRED")
    if zone["status"] != "ACTIVE":
        raise err_zone_inactive("Zone is INACTIVE")
    pile = None
    for cand in db.stockpiles.values():
        if (
            cand["site_id"] == order["site_id"]
            and cand["product_spec_id"] == order["product_spec_id"]
        ):
            pile = cand
            break
    if pile is None or pile["status"] != "OPEN":
        raise err_stockpile_quarantined("No OPEN stockpile for site+spec")
    order["prices_pinned"] = True
    order["stockpile_id"] = pile["id"]
    refresh_stockpile(pile)
    if D(pile["available_tons"]) >= D(order["quantity_tons"]):
        order["status"] = "CONFIRMED"
        pile["reserved_tons"] = to_float(
            q(D(pile["reserved_tons"]) + D(order["quantity_tons"]), 3)
        )
        refresh_stockpile(pile)
        touch(pile)
    else:
        order["status"] = "BACKORDERED"
    touch(order)
    return ok_object(order)


@bp.route("/sales-orders/<oid>/cancel", methods=["POST"])
def cancel_order(oid):
    require_roles(["SalesAgent"])
    order = get_or_404(db.sales_orders, oid)
    if order["status"] not in ("QUOTED", "CONFIRMED", "BACKORDERED", "IN_FULFILLMENT"):
        raise err_invalid_state("Order cannot be cancelled from its state")
    if order["status"] == "CONFIRMED" and order.get("stockpile_id"):
        pile = db.stockpiles.get(order["stockpile_id"])
        if pile:
            pile["reserved_tons"] = to_float(
                q(D(pile["reserved_tons"]) - D(order["quantity_tons"]), 3)
            )
            refresh_stockpile(pile)
            touch(pile)
    elif order["status"] == "IN_FULFILLMENT" and order.get("stockpile_id"):
        pile = db.stockpiles.get(order["stockpile_id"])
        if pile:
            release = D(order["quantity_tons"]) - D(order["fulfilled_tons"])
            if release < 0:
                release = Decimal("0")
            pile["reserved_tons"] = to_float(q(D(pile["reserved_tons"]) - release, 3))
            refresh_stockpile(pile)
            touch(pile)
    order["status"] = "CANCELLED"
    touch(order)
    return ok_object(order)


@bp.route("/sales-orders/<oid>/reprice", methods=["POST"])
def reprice_order(oid):
    require_roles(["SalesAgent"])
    order = get_or_404(db.sales_orders, oid)
    if order["status"] != "QUOTED":
        raise err_invalid_state("Only QUOTED orders can be repriced")
    data = body()
    expected = req_field(data, "expected_sales_order_version")
    if not isinstance(expected, int) or isinstance(expected, bool):
        raise err_invalid_request("expected_sales_order_version must be an integer")
    if expected != order["version"]:
        raise err_stale_version("Stale sales order version")
    spec = db.product_specs[order["product_spec_id"]]
    zone = db.freight_zones[order["freight_zone_id"]]
    order.update(compute_quote(spec, zone, order["quantity_tons"]))
    touch(order)
    return ok_object(order)


# ---------------------------------------------------------------------------
# Truck queue entries
# ---------------------------------------------------------------------------

PRIORITY_RANK = {"CONTRACT": 0, "SPOT": 1, "INTERNAL": 2}


@bp.route("/queue-entries", methods=["POST"])
def create_queue_entry():
    require_roles(["ScaleHouseOperator"])
    data = body()
    site_id = req_string(data, "site_id")
    truck_id = req_string(data, "truck_id")
    priority = req_enum(data, "priority_class", {"CONTRACT", "SPOT", "INTERNAL"})
    tare = req_positive(data, "certified_tare_lbs")
    payload = req_positive(data, "max_payload_lbs")
    get_or_404(db.sites, site_id)
    for other in db.truck_queue_entries.values():
        if (
            other["site_id"] == site_id
            and other["truck_id"] == truck_id
            and other["status"] in ("QUEUED", "AT_SCALE_IN", "LOADING", "AT_SCALE_OUT")
        ):
            raise err_truck_already_queued("Truck already has an active entry")
    entry = base_resource()
    entry.update(
        {
            "site_id": site_id,
            "truck_id": truck_id,
            "priority_class": priority,
            "certified_tare_lbs": tare,
            "max_payload_lbs": payload,
            "queued_at": logical_now_iso(),
            "scale_ticket_id": None,
            "status": "QUEUED",
        }
    )
    db.truck_queue_entries[entry["id"]] = entry
    return ok_object(entry, 201)


@bp.route("/queue-entries", methods=["GET"])
def list_queue_entries():
    require_roles(ALL_ROLES)
    filters = {
        "site_id": _qs("site_id"),
        "scale_ticket_id": _qs("scale_ticket_id"),
        "truck_id": _qs("truck_id"),
        "status": _qs("status"),
    }
    return list_response(db.truck_queue_entries, filters)


@bp.route("/queue-entries/call-next", methods=["POST"])
def call_next():
    require_roles(["ScaleHouseOperator"])
    data = body()
    site_id = req_string(data, "site_id")
    get_or_404(db.sites, site_id)
    pool = [
        e
        for e in db.truck_queue_entries.values()
        if e["site_id"] == site_id and e["status"] == "QUEUED"
    ]
    if not pool:
        raise err_queue_empty("No QUEUED entries for the site")
    pool.sort(
        key=lambda e: (
            PRIORITY_RANK[e["priority_class"]],
            e["queued_at"],
            e["truck_id"],
        )
    )
    winner = pool[0]
    winner["status"] = "AT_SCALE_IN"
    touch(winner)
    return ok_object(winner)


@bp.route("/queue-entries/<eid>", methods=["GET"])
def get_queue_entry(eid):
    require_roles(ALL_ROLES)
    return ok_object(get_or_404(db.truck_queue_entries, eid))


@bp.route("/queue-entries/<eid>/begin-scale-out", methods=["POST"])
def begin_scale_out(eid):
    require_roles(["ScaleHouseOperator"])
    entry = get_or_404(db.truck_queue_entries, eid)
    if entry["status"] != "LOADING":
        raise err_invalid_state("Only LOADING entries can begin scale-out")
    entry["status"] = "AT_SCALE_OUT"
    touch(entry)
    return ok_object(entry)


@bp.route("/queue-entries/<eid>/mark-no-show", methods=["POST"])
def mark_no_show(eid):
    require_roles(["ScaleHouseOperator"])
    entry = get_or_404(db.truck_queue_entries, eid)
    if entry["status"] != "QUEUED":
        raise err_invalid_state("Only QUEUED entries can be marked no-show")
    entry["status"] = "NO_SHOW"
    touch(entry)
    return ok_object(entry)


# ---------------------------------------------------------------------------
# Scale tickets
# ---------------------------------------------------------------------------

@bp.route("/scale-tickets", methods=["POST"])
def create_ticket():
    require_roles(["ScaleHouseOperator"])
    data = body()
    queue_entry_id = req_string(data, "queue_entry_id")
    order_id = req_string(data, "sales_order_id")
    scale_id = req_string(data, "scale_id")
    gross = req_positive(data, "gross_lbs")
    entry = get_or_404(db.truck_queue_entries, queue_entry_id)
    order = get_or_404(db.sales_orders, order_id)
    scale = get_or_404(db.scales, scale_id)
    if entry["status"] != "AT_SCALE_IN":
        raise err_invalid_state("Queue entry must be AT_SCALE_IN for weigh-in")
    if order["status"] not in ("CONFIRMED", "IN_FULFILLMENT"):
        raise err_invalid_state("Order must be CONFIRMED or IN_FULFILLMENT")
    site = db.sites[entry["site_id"]]
    if site["posture"] == "SUSPENDED":
        raise err_site_posture_blocked("Site is SUSPENDED")
    if not scale_usable(scale):
        raise err_scale_not_certified("Scale not certified or out of date")
    pile = db.stockpiles.get(order.get("stockpile_id") or "")
    if pile is None or pile["status"] != "OPEN":
        raise err_stockpile_quarantined("Order's stockpile is not OPEN")
    ticket = base_resource()
    ticket.update(
        {
            "queue_entry_id": queue_entry_id,
            "sales_order_id": order_id,
            "scale_id": scale_id,
            "site_id": entry["site_id"],
            "stockpile_id": order["stockpile_id"],
            "truck_id": entry["truck_id"],
            "gross_lbs": gross,
            "tare_lbs": None,
            "net_tons": None,
            "tare_variance_pct": None,
            "royalty_provisional_usd": None,
            "completed_at": None,
            "status": "OPEN",
            "void_reason": None,
        }
    )
    db.scale_tickets[ticket["id"]] = ticket
    entry["status"] = "LOADING"
    entry["scale_ticket_id"] = ticket["id"]
    touch(entry)
    return ok_object(ticket, 201)


@bp.route("/scale-tickets", methods=["GET"])
def list_tickets():
    require_roles(ALL_ROLES)
    filters = {
        "site_id": _qs("site_id"),
        "sales_order_id": _qs("sales_order_id"),
        "stockpile_id": _qs("stockpile_id"),
        "scale_id": _qs("scale_id"),
        "queue_entry_id": _qs("queue_entry_id"),
        "status": _qs("status"),
    }
    return list_response(db.scale_tickets, filters)


@bp.route("/scale-tickets/<tid>", methods=["GET"])
def get_ticket(tid):
    require_roles(ALL_ROLES)
    return ok_object(get_or_404(db.scale_tickets, tid))


@bp.route("/scale-tickets/<tid>/weigh-out", methods=["POST"])
def weigh_out(tid):
    require_roles(["ScaleHouseOperator"])
    ticket = get_or_404(db.scale_tickets, tid)
    if ticket["status"] != "OPEN":
        raise err_invalid_state("Only OPEN tickets can be weighed out")
    data = body()
    tare = req_positive(data, "tare_lbs")
    allow_variance = data.get("allow_tare_variance", False)
    if allow_variance is None:
        allow_variance = False
    if not isinstance(allow_variance, bool):
        raise err_invalid_request("allow_tare_variance must be a boolean")
    entry = db.truck_queue_entries[ticket["queue_entry_id"]]
    if entry["status"] != "AT_SCALE_OUT":
        raise err_invalid_state("Queue entry must be AT_SCALE_OUT")
    site = db.sites[ticket["site_id"]]
    if site["posture"] == "SUSPENDED":
        raise err_site_posture_blocked("Site is SUSPENDED")
    scale = db.scales[ticket["scale_id"]]
    if not scale_usable(scale):
        raise err_scale_not_certified("Scale not certified or out of date")
    # Tare variance (2.00 inclusive passes)
    variance = q(
        abs(D(tare) - D(entry["certified_tare_lbs"]))
        / D(entry["certified_tare_lbs"])
        * Decimal(100),
        2,
    )
    if variance > Decimal("2.00") and not allow_variance:
        raise err_tare_variance("Tare variance exceeds 2%")
    # Legal weight
    net_lbs = D(ticket["gross_lbs"]) - D(tare)
    if net_lbs > D(entry["max_payload_lbs"]):
        raise err_truck_overweight("Net weight exceeds max payload")
    # Royalty coverage
    today = logical_today()
    agreement = active_agreement_covering(ticket["site_id"], today)
    if agreement is None:
        raise err_royalty_agreement_required("No ACTIVE agreement covers today")
    # Over-shipment guard
    order = db.sales_orders[ticket["sales_order_id"]]
    net_tons = q(net_lbs / Decimal(2000), 3)
    max_allowed = q(D(order["quantity_tons"]) * Decimal("1.10"), 3)
    if D(order["fulfilled_tons"]) + net_tons > max_allowed:
        raise err_over_shipment("Draw exceeds 110% of ordered quantity")
    # Commit
    ticket["tare_lbs"] = tare
    ticket["net_tons"] = to_float(net_tons)
    ticket["tare_variance_pct"] = to_float(variance)
    ticket["royalty_provisional_usd"] = to_float(
        q(net_tons * D(agreement["base_rate_per_ton"]), 2)
    )
    ticket["completed_at"] = logical_now_iso()
    ticket["status"] = "COMPLETED"
    touch(ticket)
    pile = db.stockpiles[ticket["stockpile_id"]]
    pile["on_hand_tons"] = to_float(q(D(pile["on_hand_tons"]) - net_tons, 3))
    order["fulfilled_tons"] = to_float(q(D(order["fulfilled_tons"]) + net_tons, 3))
    remaining_res = D(order["quantity_tons"]) - D(order["fulfilled_tons"])
    if remaining_res < 0:
        remaining_res = Decimal("0")
    pile["reserved_tons"] = to_float(q(remaining_res, 3))
    if order["status"] == "CONFIRMED":
        order["status"] = "IN_FULFILLMENT"
    if D(order["fulfilled_tons"]) >= D(order["quantity_tons"]):
        order["status"] = "COMPLETED"
    refresh_stockpile(pile)
    touch(pile)
    touch(order)
    entry["status"] = "EXITED"
    touch(entry)
    return ok_object(ticket)


@bp.route("/scale-tickets/<tid>/void", methods=["POST"])
def void_ticket(tid):
    require_roles(["SiteManager"])
    ticket = get_or_404(db.scale_tickets, tid)
    data = body()
    reason = req_string(data, "void_reason")
    if ticket["status"] != "COMPLETED":
        raise err_invalid_state("Only COMPLETED tickets can be voided")
    tdate = ticket_date(ticket)
    for stmt in db.royalty_statements.values():
        if stmt["site_id"] != ticket["site_id"] or stmt["status"] == "VOID":
            continue
        if (
            parse_iso_date(stmt["period_start"]) <= tdate
            < parse_iso_date(stmt["period_end"])
        ):
            raise err_statement_locked("A live statement covers this ticket's date")
    net = D(ticket["net_tons"])
    ticket["status"] = "VOIDED"
    ticket["void_reason"] = reason
    touch(ticket)
    pile = db.stockpiles[ticket["stockpile_id"]]
    pile["on_hand_tons"] = to_float(q(D(pile["on_hand_tons"]) + net, 3))
    order = db.sales_orders[ticket["sales_order_id"]]
    order["fulfilled_tons"] = to_float(q(D(order["fulfilled_tons"]) - net, 3))
    remaining_res = D(order["quantity_tons"]) - D(order["fulfilled_tons"])
    if remaining_res < 0:
        remaining_res = Decimal("0")
    pile["reserved_tons"] = to_float(q(remaining_res, 3))
    if order["status"] == "COMPLETED":
        order["status"] = "IN_FULFILLMENT"
    refresh_stockpile(pile)
    touch(pile)
    touch(order)
    return ok_object(ticket)


# ---------------------------------------------------------------------------
# Royalty agreements
# ---------------------------------------------------------------------------

@bp.route("/royalty-agreements", methods=["POST"])
def create_agreement():
    require_roles(["FinanceClerk"])
    data = body()
    site_id = req_string(data, "site_id")
    landowner = req_string(data, "landowner_name")
    base_rate = req_positive(data, "base_rate_per_ton")
    threshold = req_positive(data, "tier_threshold_tons")
    tier_rate = req_positive(data, "tier_rate_per_ton")
    effective_from = req_string(data, "effective_from")
    parse_iso_date(effective_from)
    get_or_404(db.sites, site_id)
    for other in db.royalty_agreements.values():
        if other["site_id"] == site_id and other["status"] == "ACTIVE":
            raise err_agreement_already_active("Site already has an ACTIVE agreement")
    ag = base_resource()
    ag.update(
        {
            "site_id": site_id,
            "landowner_name": landowner,
            "base_rate_per_ton": base_rate,
            "tier_threshold_tons": threshold,
            "tier_rate_per_ton": tier_rate,
            "effective_from": effective_from,
            "effective_to": None,
            "supersedes_agreement_id": None,
            "status": "ACTIVE",
        }
    )
    db.royalty_agreements[ag["id"]] = ag
    return ok_object(ag, 201)


@bp.route("/royalty-agreements", methods=["GET"])
def list_agreements():
    require_roles(ALL_ROLES)
    filters = {
        "site_id": _qs("site_id"),
        "supersedes_agreement_id": _qs("supersedes_agreement_id"),
        "status": _qs("status"),
    }
    return list_response(db.royalty_agreements, filters)


@bp.route("/royalty-agreements/<aid>", methods=["GET"])
def get_agreement(aid):
    require_roles(ALL_ROLES)
    return ok_object(get_or_404(db.royalty_agreements, aid))


@bp.route("/royalty-agreements/<aid>/amendments", methods=["POST"])
def amend_agreement(aid):
    require_roles(["FinanceClerk"])
    old = get_or_404(db.royalty_agreements, aid)
    data = body()
    base_rate = req_positive(data, "base_rate_per_ton")
    threshold = req_positive(data, "tier_threshold_tons")
    tier_rate = req_positive(data, "tier_rate_per_ton")
    effective_from = req_string(data, "effective_from")
    parse_iso_date(effective_from)
    if old["status"] != "ACTIVE":
        raise err_invalid_state("Only ACTIVE agreements can be amended")
    old["status"] = "SUPERSEDED"
    old["effective_to"] = effective_from
    touch(old)
    new = base_resource()
    new.update(
        {
            "site_id": old["site_id"],
            "landowner_name": old["landowner_name"],
            "base_rate_per_ton": base_rate,
            "tier_threshold_tons": threshold,
            "tier_rate_per_ton": tier_rate,
            "effective_from": effective_from,
            "effective_to": None,
            "supersedes_agreement_id": old["id"],
            "status": "ACTIVE",
        }
    )
    db.royalty_agreements[new["id"]] = new
    return ok_object(new, 201)


@bp.route("/royalty-agreements/<aid>/terminate", methods=["POST"])
def terminate_agreement(aid):
    require_roles(["FinanceClerk"])
    ag = get_or_404(db.royalty_agreements, aid)
    if ag["status"] != "ACTIVE":
        raise err_invalid_state("Only ACTIVE agreements can be terminated")
    ag["status"] = "TERMINATED"
    touch(ag)
    return ok_object(ag)


# ---------------------------------------------------------------------------
# Royalty statements
# ---------------------------------------------------------------------------

@bp.route("/royalty-statements", methods=["POST"])
def create_statement():
    user_id, _ = require_roles(["FinanceClerk"])
    data = body()
    site_id = req_string(data, "site_id")
    period_start = req_string(data, "period_start")
    period_end = req_string(data, "period_end")
    ps = parse_iso_date(period_start)
    pe = parse_iso_date(period_end)
    if pe <= ps:
        raise err_invalid_request("period_end must be after period_start")
    get_or_404(db.sites, site_id)
    # Overlap + chronological checks against non-VOID statements of the site
    existing = [
        s
        for s in db.royalty_statements.values()
        if s["site_id"] == site_id and s["status"] != "VOID"
    ]
    for s in existing:
        sps = parse_iso_date(s["period_start"])
        spe = parse_iso_date(s["period_end"])
        if ps < spe and sps < pe:
            raise err_statement_period_overlap("Statement period overlaps")
    for s in existing:
        spe = parse_iso_date(s["period_end"])
        if ps < spe:
            raise err_statement_not_chronological(
                "Statement period_start earlier than an existing period_end"
            )
    agreement = active_agreement_covering(site_id, ps)
    if agreement is None:
        raise err_royalty_agreement_required("No ACTIVE agreement covers the period")
    # ytd_tons_before: same-site non-VOID statements, same calendar year of
    # period_start, strictly earlier period_start
    ytd_before = Decimal("0")
    prior = [
        s
        for s in existing
        if parse_iso_date(s["period_start"]).year == ps.year
        and parse_iso_date(s["period_start"]) < ps
    ]
    prior.sort(key=lambda s: s["created_at"])
    for s in prior:
        ytd_before += D(s["tons_sold"])
    # Ticket sweep: COMPLETED tickets of the site within [period_start, period_end)
    tickets = [
        t
        for t in db.scale_tickets.values()
        if t["site_id"] == site_id
        and t["status"] == "COMPLETED"
        and t.get("completed_at")
        and ps <= ticket_date(t) < pe
    ]
    tickets.sort(key=lambda t: (t["completed_at"], t["created_at"]))
    ytd = ytd_before
    royalty_due = Decimal("0")
    tons_sold = Decimal("0")
    base_rate = D(agreement["base_rate_per_ton"])
    tier_rate = D(agreement["tier_rate_per_ton"])
    threshold = D(agreement["tier_threshold_tons"])
    for t in tickets:
        net = D(t["net_tons"])
        below = threshold - ytd
        if below < 0:
            below = Decimal("0")
        if below > net:
            below = net
        above = net - below
        royalty_due += q(below * base_rate + above * tier_rate, 2)
        ytd += net
        tons_sold += net
    stmt = base_resource()
    stmt.update(
        {
            "site_id": site_id,
            "period_start": period_start,
            "period_end": period_end,
            "royalty_agreement_id": agreement["id"],
            "tons_sold": to_float(q(tons_sold, 3)),
            "ytd_tons_before": to_float(q(ytd_before, 3)),
            "ytd_tons_after": to_float(q(ytd_before + tons_sold, 3)),
            "royalty_due_usd": to_float(q(royalty_due, 2)),
            "status": "DRAFT",
            "generated_by_user_id": user_id,
            "issued_by_user_id": None,
            "issued_on": None,
            "due_on": None,
            "paid_on": None,
            "penalty_usd": None,
        }
    )
    db.royalty_statements[stmt["id"]] = stmt
    return ok_object(stmt, 201)


@bp.route("/royalty-statements", methods=["GET"])
def list_statements():
    require_roles(ALL_ROLES)
    filters = {
        "site_id": _qs("site_id"),
        "royalty_agreement_id": _qs("royalty_agreement_id"),
        "status": _qs("status"),
    }
    return list_response(db.royalty_statements, filters)


@bp.route("/royalty-statements/<sid>", methods=["GET"])
def get_statement(sid):
    require_roles(ALL_ROLES)
    return ok_object(get_or_404(db.royalty_statements, sid))


@bp.route("/royalty-statements/<sid>/issue", methods=["POST"])
def issue_statement(sid):
    user_id, _ = require_roles(["SiteManager"])
    stmt = get_or_404(db.royalty_statements, sid)
    if stmt["status"] != "DRAFT":
        raise err_invalid_state("Only DRAFT statements can be issued")
    if user_id == stmt["generated_by_user_id"]:
        raise err_sod_violation("Issuer must differ from generator")
    today = logical_today()
    stmt["status"] = "ISSUED"
    stmt["issued_by_user_id"] = user_id
    stmt["issued_on"] = today.isoformat()
    stmt["due_on"] = (today + timedelta(days=30)).isoformat()
    touch(stmt)
    return ok_object(stmt)


@bp.route("/royalty-statements/<sid>/pay", methods=["POST"])
def pay_statement(sid):
    require_roles(["FinanceClerk"])
    stmt = get_or_404(db.royalty_statements, sid)
    data = body()
    paid_on = req_string(data, "paid_on")
    pd = parse_iso_date(paid_on)
    if stmt["status"] != "ISSUED":
        raise err_invalid_state("Only ISSUED statements can be paid")
    due = parse_iso_date(stmt["due_on"])
    if pd <= due:
        penalty = Decimal("0.00")
    else:
        penalty = q(D(stmt["royalty_due_usd"]) * Decimal("0.05"), 2)
    stmt["status"] = "PAID"
    stmt["paid_on"] = paid_on
    stmt["penalty_usd"] = to_float(penalty)
    touch(stmt)
    return ok_object(stmt)


@bp.route("/royalty-statements/<sid>/void", methods=["POST"])
def void_statement(sid):
    require_roles(["FinanceClerk"])
    stmt = get_or_404(db.royalty_statements, sid)
    if stmt["status"] != "DRAFT":
        raise err_invalid_state("Only DRAFT statements can be voided")
    stmt["status"] = "VOID"
    touch(stmt)
    return ok_object(stmt)


# ---------------------------------------------------------------------------
# MSHA inspections and citations
# ---------------------------------------------------------------------------

@bp.route("/msha-inspections", methods=["POST"])
def create_inspection():
    require_roles(["SafetyOfficer"])
    data = body()
    site_id = req_string(data, "site_id")
    itype = req_enum(data, "inspection_type", {"REGULAR", "SPOT", "COMPLAINT"})
    get_or_404(db.sites, site_id)
    insp = base_resource()
    insp.update(
        {
            "site_id": site_id,
            "inspection_type": itype,
            "opened_on": logical_today().isoformat(),
            "closed_on": None,
            "status": "OPEN",
        }
    )
    db.msha_inspections[insp["id"]] = insp
    return ok_object(insp, 201)


@bp.route("/msha-inspections", methods=["GET"])
def list_inspections():
    require_roles(ALL_ROLES)
    filters = {"site_id": _qs("site_id"), "status": _qs("status")}
    return list_response(db.msha_inspections, filters)


@bp.route("/msha-inspections/<iid>", methods=["GET"])
def get_inspection(iid):
    require_roles(ALL_ROLES)
    return ok_object(get_or_404(db.msha_inspections, iid))


@bp.route("/msha-inspections/<iid>/close", methods=["POST"])
def close_inspection(iid):
    require_roles(["SafetyOfficer"])
    insp = get_or_404(db.msha_inspections, iid)
    if insp["status"] != "OPEN":
        raise err_invalid_state("Only OPEN inspections can be closed")
    for cit in db.msha_citations.values():
        if cit["msha_inspection_id"] == iid and cit["status"] == "ISSUED":
            raise err_open_citations("Inspection has non-terminal citations")
    insp["status"] = "CLOSED"
    insp["closed_on"] = logical_today().isoformat()
    touch(insp)
    return ok_object(insp)


@bp.route("/msha-citations", methods=["POST"])
def create_citation():
    require_roles(["SafetyOfficer"])
    data = body()
    inspection_id = req_string(data, "msha_inspection_id")
    code = req_string(data, "citation_code")
    s_and_s = req_field(data, "s_and_s")
    if not isinstance(s_and_s, bool):
        raise err_invalid_request("s_and_s must be a boolean")
    due = req_string(data, "abatement_due_on")
    parse_iso_date(due)
    insp = get_or_404(db.msha_inspections, inspection_id)
    if insp["status"] != "OPEN":
        raise err_invalid_state("Citations require an OPEN inspection")
    cit = base_resource()
    cit.update(
        {
            "msha_inspection_id": inspection_id,
            "citation_code": code,
            "s_and_s": s_and_s,
            "abatement_due_on": due,
            "abated_on": None,
            "status": "ISSUED",
        }
    )
    db.msha_citations[cit["id"]] = cit
    recompute_site(insp["site_id"])
    return ok_object(cit, 201)


@bp.route("/msha-citations", methods=["GET"])
def list_citations():
    require_roles(ALL_ROLES)
    filters = {"msha_inspection_id": _qs("msha_inspection_id"), "status": _qs("status")}
    return list_response(db.msha_citations, filters)


@bp.route("/msha-citations/<cid>", methods=["GET"])
def get_citation(cid):
    require_roles(ALL_ROLES)
    return ok_object(get_or_404(db.msha_citations, cid))


@bp.route("/msha-citations/<cid>/abate", methods=["POST"])
def abate_citation(cid):
    require_roles(["SafetyOfficer"])
    cit = get_or_404(db.msha_citations, cid)
    data = body()
    abated_on = req_string(data, "abated_on")
    parse_iso_date(abated_on)
    if cit["status"] != "ISSUED":
        raise err_invalid_state("Only ISSUED citations can be abated")
    cit["status"] = "ABATED"
    cit["abated_on"] = abated_on
    touch(cit)
    insp = db.msha_inspections[cit["msha_inspection_id"]]
    recompute_site(insp["site_id"])
    return ok_object(cit)


@bp.route("/msha-citations/<cid>/vacate", methods=["POST"])
def vacate_citation(cid):
    require_roles(["SafetyOfficer"])
    cit = get_or_404(db.msha_citations, cid)
    if cit["status"] != "ISSUED":
        raise err_invalid_state("Only ISSUED citations can be vacated")
    cit["status"] = "VACATED"
    touch(cit)
    insp = db.msha_inspections[cit["msha_inspection_id"]]
    recompute_site(insp["site_id"])
    return ok_object(cit)


# ---------------------------------------------------------------------------
# Training records
# ---------------------------------------------------------------------------

def _add_months(d, months):
    month = d.month - 1 + months
    year = d.year + month // 12
    month = month % 12 + 1
    import calendar

    day = min(d.day, calendar.monthrange(year, month)[1])
    return d.replace(year=year, month=month, day=day)


@bp.route("/training-records", methods=["POST"])
def create_training():
    require_roles(["SafetyOfficer"])
    data = body()
    miner_name = req_string(data, "miner_name")
    miner_user_id = req_string(data, "miner_user_id")
    course = req_enum(
        data, "course_type", {"NEW_MINER", "ANNUAL_REFRESHER", "TASK_TRAINING"}
    )
    completed_on = req_string(data, "completed_on")
    cd = parse_iso_date(completed_on)
    expires = _add_months(cd, 12)
    rec = base_resource()
    rec.update(
        {
            "miner_name": miner_name,
            "miner_user_id": miner_user_id,
            "course_type": course,
            "completed_on": completed_on,
            "expires_on": expires.isoformat(),
            "is_current": expires >= logical_today(),
        }
    )
    db.training_records[rec["id"]] = rec
    return ok_object(rec, 201)


@bp.route("/training-records", methods=["GET"])
def list_training():
    require_roles(ALL_ROLES)
    filters = {"miner_user_id": _qs("miner_user_id"), "course_type": _qs("course_type")}
    items = list(db.training_records.values())
    today = logical_today()
    for rec in items:
        rec["is_current"] = parse_iso_date(rec["expires_on"]) >= today
    if filters["miner_user_id"] is not None:
        items = [r for r in items if r["miner_user_id"] == filters["miner_user_id"]]
    if filters["course_type"] is not None:
        items = [r for r in items if r["course_type"] == filters["course_type"]]
    items.sort(key=lambda r: (r["created_at"], r["id"]))
    from core import ok_list, parse_pagination

    total = len(items)
    limit, offset = parse_pagination()
    return ok_list(items[offset:offset + limit], limit, offset, total)


@bp.route("/training-records/<tid>", methods=["GET"])
def get_training(tid):
    require_roles(ALL_ROLES)
    rec = get_or_404(db.training_records, tid)
    rec["is_current"] = parse_iso_date(rec["expires_on"]) >= logical_today()
    return ok_object(rec)


# ---------------------------------------------------------------------------
# Reclamation bonds
# ---------------------------------------------------------------------------

@bp.route("/reclamation-bonds", methods=["POST"])
def create_bond():
    require_roles(["FinanceClerk"])
    data = body()
    site_id = req_string(data, "site_id")
    surety = req_string(data, "surety_name")
    amount = req_positive(data, "amount_usd")
    get_or_404(db.sites, site_id)
    bond = base_resource()
    bond.update(
        {
            "site_id": site_id,
            "surety_name": surety,
            "amount_usd": amount,
            "released_usd": 0.0,
            "status": "POSTED",
        }
    )
    db.reclamation_bonds[bond["id"]] = bond
    recompute_site(site_id)
    return ok_object(bond, 201)


@bp.route("/reclamation-bonds", methods=["GET"])
def list_bonds():
    require_roles(ALL_ROLES)
    filters = {"site_id": _qs("site_id"), "status": _qs("status")}
    return list_response(db.reclamation_bonds, filters)


@bp.route("/reclamation-bonds/<bid>", methods=["GET"])
def get_bond(bid):
    require_roles(ALL_ROLES)
    return ok_object(get_or_404(db.reclamation_bonds, bid))


@bp.route("/reclamation-bonds/<bid>/release", methods=["POST"])
def release_bond(bid):
    require_roles(["FinanceClerk"])
    bond = get_or_404(db.reclamation_bonds, bid)
    if bond["status"] == "FULLY_RELEASED":
        raise err_invalid_state("Bond already FULLY_RELEASED")
    data = body()
    release_amount = req_positive(data, "release_amount_usd")
    expected = req_field(data, "expected_reclamation_bond_version")
    site = db.sites[bond["site_id"]]
    remaining = D(bond["amount_usd"]) - D(bond["released_usd"])
    if D(release_amount) > remaining:
        raise err_invalid_request("release_amount_usd exceeds remaining bond amount")
    # Post-release coverage check (pre-OCC business tier)
    posted_after = D(site["bond_posted_usd"]) - D(release_amount)
    if posted_after < D(site["bond_required_usd"]):
        raise err_bond_below_required("Release would drop coverage below required")
    # OCC last
    if not isinstance(expected, int) or isinstance(expected, bool):
        raise err_invalid_request("expected_reclamation_bond_version must be an integer")
    if expected != bond["version"]:
        raise err_stale_version("Stale bond version")
    bond["released_usd"] = to_float(q(D(bond["released_usd"]) + D(release_amount), 2))
    if D(bond["released_usd"]) == D(bond["amount_usd"]):
        bond["status"] = "FULLY_RELEASED"
    else:
        bond["status"] = "PARTIALLY_RELEASED"
    touch(bond)
    recompute_site(bond["site_id"])
    return ok_object(bond)
