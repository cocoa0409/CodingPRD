"""Business workflows: confirm, cancel, settle, stop completion, recall
activation, reallocation. All multi-step operations check every precondition
before committing any change (atomic)."""
from clock import now_dt
from db import bump, create_txn, sorted_ords, store
from errors import ApiError
from util import midnight
import calc


def lines_of(res_id):
    return sorted_ords([l for l in store.lines.values() if l["reservation_id"] == res_id])


def extensions_of(res_id):
    return sorted_ords([e for e in store.extensions.values() if e["reservation_id"] == res_id])


def claims_of_lines(line_ids):
    return sorted_ords([c for c in store.claims.values() if c["reservation_line_id"] in line_ids])


def _invalid_state(msg):
    raise ApiError("ERR_INVALID_STATE", 409, msg)


def _append_txn(res, txn_type, amount, reason, balance_after):
    create_txn({"reservation_id": res["id"], "txn_type": txn_type,
                "amount_cents": amount, "reason": reason,
                "balance_after_cents": balance_after})


# ---------------------------------------------------------------- confirm ----
def confirm_reservation(res, customer):
    if res["status"] != "QUOTED":
        _invalid_state("Reservation is not QUOTED")
    lines = lines_of(res["id"])
    # Priority 8 — recall safety
    for line in lines:
        if calc.item_under_active_mandatory_recall(line["catalog_item_id"]):
            raise ApiError("ERR_RECALL_BLOCKED", 409,
                           "Catalog item is under an ACTIVE MANDATORY recall")
    # Allocation simulation (atomicity: check all lines before committing any)
    s_dt, e_dt = midnight(res["start_date"]), midnight(res["end_date"])
    taken, assignment = set(), {}
    saw_overlap_only_failure = False
    for line in lines:
        pool = [u for u in store.units.values()
                if u["catalog_item_id"] == line["catalog_item_id"]
                and u["id"] not in taken and u["status"] in calc.ELIGIBLE_STATUSES]
        elig = calc.rank_units([u for u in pool if calc.unit_eligible(u, s_dt, e_dt)])
        if elig:
            assignment[line["id"]] = elig[0]
            taken.add(elig[0]["id"])
        else:
            assignment[line["id"]] = None
            if pool:
                saw_overlap_only_failure = True
    any_failed = any(v is None for v in assignment.values())
    # Priority 9 — temporal overlap beats structural errors
    if any_failed and saw_overlap_only_failure:
        raise ApiError("ERR_UNIT_UNAVAILABLE", 409,
                       "A unit's committed interval overlaps the requested window")
    # Priority 10 — structural constraints in declared order
    if customer["status"] != "ACTIVE":
        raise ApiError("ERR_CUSTOMER_SUSPENDED", 403, "Customer is SUSPENDED")
    for line in lines:
        if store.catalog_items[line["catalog_item_id"]]["status"] == "DELISTED":
            raise ApiError("ERR_CATALOG_ITEM_DELISTED", 409,
                           "Catalog item is DELISTED")
    if any_failed:
        raise ApiError("ERR_NO_ELIGIBLE_UNIT", 409,
                       "No eligible unit exists for a line")
    # Commit allocation
    for line in lines:
        unit = assignment[line["id"]]
        line["status"] = "ALLOCATED"
        line["assigned_unit_id"] = unit["id"]
        line["unit_rate_cents"] = store.catalog_items[line["catalog_item_id"]]["daily_rate_cents"]
        bump(line)
        unit["status"] = "RESERVED"
        bump(unit)
    hold = calc.deposit_hold(customer, lines)
    res["deposit_hold_cents"] = hold
    _append_txn(res, "HOLD", hold, "HOLD_AT_CONFIRM", hold)
    res["payment_status"] = "DEPOSIT_HELD"
    res["status"] = "CONFIRMED"
    bump(res)


# ----------------------------------------------------------------- cancel ----
def cancel_reservation(res):
    if res["status"] not in ("QUOTED", "CONFIRMED"):
        _invalid_state("Only QUOTED or CONFIRMED reservations may be cancelled")
    lines = lines_of(res["id"])
    if res["status"] == "QUOTED":
        for line in lines:
            if line["status"] == "PENDING":
                line["status"] = "CANCELLED"
                bump(line)
        # payment_status stays DEPOSIT_PENDING; no ledger entries
    else:  # CONFIRMED
        for line in lines:
            if line["status"] == "ALLOCATED":
                line["status"] = "CANCELLED"  # assigned_unit_id kept for audit
                bump(line)
                unit = store.units.get(line["assigned_unit_id"])
                if unit is not None and unit["status"] == "RESERVED":
                    unit["status"] = "AVAILABLE"
                    bump(unit)
            elif line["status"] in ("PENDING", "PENDING_REALLOCATION"):
                line["status"] = "CANCELLED"
                bump(line)
        affected_routes = set()
        for stop in store.stops.values():
            if stop["reservation_id"] == res["id"] and stop["status"] == "SCHEDULED":
                stop["status"] = "SKIPPED"
                bump(stop)
                affected_routes.add(stop["route_id"])
        for rid in affected_routes:
            route = store.routes[rid]
            calc.recompute_route_weight(route)
            bump(route)
        for ext in extensions_of(res["id"]):
            if ext["status"] == "PENDING":
                ext["status"] = "SUPERSEDED"
                bump(ext)
        # Cancellation waterfall: CAPTURE min(fee, hold), RELEASE remainder
        fee = calc.cancellation_fee(res["quoted_total_cents"])
        balance = res["deposit_hold_cents"]
        amt = min(fee, balance)
        _append_txn(res, "CAPTURE", amt, "CANCELLATION_FEE", balance - amt)
        balance -= amt
        captured, released = amt, 0
        if balance > 0:
            _append_txn(res, "RELEASE", balance, "RELEASE_REMAINDER", 0)
            released = balance
        res["deposit_captured_cents"] = captured
        res["deposit_released_cents"] = released
        res["payment_status"] = "SETTLED_PAID" if captured > 0 else "REFUNDED"
    res["status"] = "CANCELLED"
    bump(res)


# ----------------------------------------------------------------- settle ----
def settle_reservation(res):
    if res["status"] != "RETURNED":
        _invalid_state("Reservation is not RETURNED")
    lines = lines_of(res["id"])
    customer = store.customers[res["customer_id"]]
    fee, late_minutes = calc.late_fee(res, lines)
    res["late_fee_cents"] = fee
    res["final_total_cents"] = (res["quoted_total_cents"]
                                + res["extension_charge_cents"] + fee)
    customer_mutated = False
    if late_minutes > calc.GRACE_MINUTES:
        customer["late_return_count"] += 1  # once per reservation
        customer_mutated = True
    # Waterfall bucket 1: APPROVED claims in claim created_at ASC order
    line_ids = {l["id"] for l in lines}
    approved = [c for c in claims_of_lines(line_ids) if c["status"] == "APPROVED"]
    balance = res["deposit_hold_cents"]
    captured = 0
    for claim in approved:
        amt = min(claim["capture_amount_cents"], balance)
        _append_txn(res, "CAPTURE", amt, "DAMAGE_CLAIM", balance - amt)
        balance -= amt
        captured += amt
        claim["status"] = "CAPTURED"   # reviewed_by_user_id preserved
        bump(claim)
    # Waterfall bucket 2: late fee
    if fee > 0:
        amt = min(fee, balance)
        _append_txn(res, "CAPTURE", amt, "LATE_FEE", balance - amt)
        balance -= amt
        captured += amt
    # Waterfall bucket 3: release remainder
    released = 0
    if balance > 0:
        _append_txn(res, "RELEASE", balance, "RELEASE_REMAINDER", 0)
        released = balance
    res["deposit_captured_cents"] = captured
    res["deposit_released_cents"] = released
    res["commission_cents"] = calc.hotel_commission(res, lines)
    if approved:
        customer["captured_damage_count"] += len(approved)
        customer_mutated = True
    new_risk = calc.risk_score(customer)
    if new_risk != customer["risk_score"]:
        customer["risk_score"] = new_risk
        customer_mutated = True
    if customer_mutated:
        bump(customer)
    # Auto-suspension cascade at settlement
    if new_risk >= calc.SUSPEND_THRESHOLD and customer["status"] == "ACTIVE":
        customer["status"] = "SUSPENDED"
        bump(customer)
    res["payment_status"] = "SETTLED_PAID" if captured > 0 else "REFUNDED"
    res["status"] = "SETTLED"
    bump(res)


# ----------------------------------------------------------- stop complete ----
def complete_stop(stop):
    route = store.routes[stop["route_id"]]
    res = store.reservations[stop["reservation_id"]]
    if stop["status"] != "SCHEDULED":
        _invalid_state("Stop is not SCHEDULED")
    if route["status"] != "DISPATCHED":
        _invalid_state("Route is not DISPATCHED")
    if stop["stop_type"] == "DELIVERY_SETUP":
        if res["status"] != "CONFIRMED":
            _invalid_state("Delivery stop requires a CONFIRMED reservation")
    else:
        if res["status"] != "DELIVERED":
            _invalid_state("Pickup stop requires a DELIVERED reservation")
    now = now_dt()
    stop["completed_at"] = now
    stop["status"] = "COMPLETED"
    bump(stop)
    lines = lines_of(res["id"])
    if stop["stop_type"] == "DELIVERY_SETUP":
        for line in lines:
            if line["status"] == "ALLOCATED":
                line["status"] = "OUT"
                bump(line)
                unit = store.units.get(line["assigned_unit_id"])
                if unit is not None and unit["status"] == "RESERVED":
                    unit["status"] = "RENTED_OUT"
                    bump(unit)
        res["status"] = "DELIVERED"
        bump(res)
    else:  # PICKUP
        res["returned_at"] = now
        for line in lines:
            if line["status"] != "OUT":
                continue
            line["status"] = "RETURNED"
            bump(line)
            unit = store.units.get(line["assigned_unit_id"])
            # A unit quarantined while RENTED_OUT stays QUARANTINED and must be
            # decontaminated; only RENTED_OUT units enter the cleaning cascade.
            if unit is not None and unit["status"] == "RENTED_OUT":
                item = store.catalog_items[unit["catalog_item_id"]]
                unit["status"] = "AWAITING_CLEANING"
                unit["blocked_until"] = now + __import__("datetime").timedelta(
                    hours=item["cleaning_turnaround_hours"])
                bump(unit)
                ttype = ("DEEP" if unit["cleans_since_deep"] >= item["deep_clean_every_cycles"]
                         else "STANDARD")
                from db import create_rec
                create_rec(store.tickets, {
                    "unit_id": unit["id"], "ticket_type": ttype, "status": "OPEN",
                    "inspector_user_id": None, "resolution_note": None})
                unit["status"] = "IN_CLEANING"
                bump(unit)
        res["status"] = "RETURNED"
        bump(res)


# ------------------------------------------------------------ recall activate ----
def activate_recall(recall):
    if recall["status"] != "DRAFT":
        _invalid_state("Recall is not DRAFT")
    recall["activated_at"] = now_dt()
    recall["status"] = "ACTIVE"
    if recall["severity"] == "MANDATORY":
        affected_res_ids = []
        for unit in sorted_ords(list(store.units.values())):
            if unit["catalog_item_id"] != recall["catalog_item_id"]:
                continue
            if unit["status"] not in ("AVAILABLE", "RESERVED", "RENTED_OUT",
                                      "AWAITING_CLEANING", "IN_CLEANING"):
                continue
            was_reserved = unit["status"] == "RESERVED"
            unit["status"] = "QUARANTINED"
            bump(unit)
            if was_reserved:
                # Depth-2 hop: holding ALLOCATED line -> PENDING_REALLOCATION
                for line in sorted_ords(list(store.lines.values())):
                    if line["assigned_unit_id"] == unit["id"] and line["status"] == "ALLOCATED":
                        line["status"] = "PENDING_REALLOCATION"
                        line["assigned_unit_id"] = None
                        bump(line)
                        if line["reservation_id"] not in affected_res_ids:
                            affected_res_ids.append(line["reservation_id"])
        for rid in affected_res_ids:
            bump(store.reservations[rid])
        # Depth-3 hop: SCHEDULED DELIVERY_SETUP stops of affected reservations
        affected_routes = set()
        for rid in affected_res_ids:
            for stop in store.stops.values():
                if (stop["reservation_id"] == rid and stop["status"] == "SCHEDULED"
                        and stop["stop_type"] == "DELIVERY_SETUP"):
                    stop["status"] = "SKIPPED"
                    bump(stop)
                    affected_routes.add(stop["route_id"])
        for route_id in affected_routes:
            route = store.routes[route_id]
            calc.recompute_route_weight(route)
            bump(route)
    bump(recall)


# --------------------------------------------------------------- reallocate ----
def reallocate_line(line):
    if line["status"] != "PENDING_REALLOCATION":
        _invalid_state("Line is not PENDING_REALLOCATION")
    res = store.reservations[line["reservation_id"]]
    if res["status"] != "CONFIRMED":
        _invalid_state("Reservation is not CONFIRMED")
    item_id = line["catalog_item_id"]
    s_dt, e_dt = midnight(res["start_date"]), midnight(res["end_date"])
    under_recall = calc.item_under_active_mandatory_recall(item_id)
    pool = [u for u in store.units.values() if u["catalog_item_id"] == item_id]
    non_quarantined = [u for u in pool
                       if u["status"] in calc.ELIGIBLE_STATUSES and not under_recall]
    elig = calc.rank_units([u for u in non_quarantined
                            if calc.unit_eligible(u, s_dt, e_dt,
                                                  exclude_reservation_id=res["id"])])
    if not elig:
        if not non_quarantined:
            if any(u["status"] == "QUARANTINED" for u in pool):
                raise ApiError("ERR_UNIT_QUARANTINED", 409,
                               "Only quarantined candidates exist")
            raise ApiError("ERR_NO_ELIGIBLE_UNIT", 409, "No candidates exist")
        raise ApiError("ERR_UNIT_UNAVAILABLE", 409,
                       "Candidates' committed intervals overlap the window")
    unit = elig[0]
    line["assigned_unit_id"] = unit["id"]
    line["status"] = "ALLOCATED"
    bump(line)
    unit["status"] = "RESERVED"
    bump(unit)
    bump(res)
