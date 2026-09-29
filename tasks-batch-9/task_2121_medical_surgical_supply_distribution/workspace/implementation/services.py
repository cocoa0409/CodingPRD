"""Business logic: pricing, totals, ledgers, allocation, cascades, settlement."""
from decimal import Decimal, ROUND_HALF_UP

from db import (
    by_creation,
    clock_now,
    parse_iso,
    sort_key,
    store,
    touch,
)
from errors import ApiError

# ---------------------------------------------------------------------------
# constants (SCAFFOLD 1.3 + global_constants)
# ---------------------------------------------------------------------------
TIER_MULT = {
    "TIER_1": Decimal("1.00"),
    "TIER_2": Decimal("1.06"),
    "TIER_3": Decimal("1.13"),
}
LUM_FEE_CENTS_PER_EA = 12
COLD_HANDLING_MIN_CENTS = 45
COLD_HANDLING_PCT = Decimal("0.03")
DIST_FEE_PCT = Decimal("0.0275")
ADMIN_FEE_BRACKET_1_MAX_EXCLUSIVE = 50000
ADMIN_FEE_BRACKET_2_MAX_EXCLUSIVE = 250000
ADMIN_FEE_PCT_BRACKET_1 = Decimal("0.020")
ADMIN_FEE_PCT_BRACKET_2 = Decimal("0.015")
ADMIN_FEE_PCT_BRACKET_3 = Decimal("0.010")
COLD_CHAIN_ROUTE_CAPACITY_UNITS = 400
AMBIENT_VAN_COLD_CAPACITY_UNITS = 0
ROOM_TURNOVER_BUFFER_MIN = 15
CONTROLLED_MAX_UNITS_PER_ORDER = 100
SUBSTITUTION_MAX_ROUNDS = 2

COLD_CLASSES = ("COLD_CHAIN", "CONTROLLED_COLD")
CONTROLLED_CLASSES = ("CONTROLLED", "CONTROLLED_COLD")

TOTAL_PARTICIPATING_STATUSES = ("OPEN", "ALLOCATED", "SUBSTITUTED", "DELIVERED")
NON_TERMINAL_LINE_STATUSES = ("OPEN", "ALLOCATED", "BACKORDERED", "SUBSTITUTED")
COMMITTED_FULFILLMENT_STATUSES = ("SUBMITTED", "ALLOCATED", "IN_TRANSIT", "HELD")
ROUTE_LOAD_FULFILLMENT_STATUSES = ("ALLOCATED", "IN_TRANSIT", "DELIVERED")
PAYABLE_CLAIM_STATUSES = ("SUBMITTED", "ACCEPTED", "RECONCILED")


def round_half_up(value):
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# lookup helpers
# ---------------------------------------------------------------------------
def lines_of_order(order):
    return by_creation([ln for ln in store.order_lines.values()
                        if ln["order_id"] == order["id"]])


def formulary_for(supply_room_id, item_id):
    for fi in store.formulary_items.values():
        if fi["supply_room_id"] == supply_room_id and fi["item_id"] == item_id:
            return fi
    return None


def room_of_order(order):
    return store.supply_rooms.get(order["supply_room_id"])


def orders_on_route(route_id):
    return by_creation([o for o in store.orders.values()
                        if o.get("route_id") == route_id])


def claims_of_order(order_id):
    return by_creation([c for c in store.claims.values()
                        if c["order_id"] == order_id])


# ---------------------------------------------------------------------------
# contract_unit_price (SCAFFOLD 1.3 / PRD 3.2)
# ---------------------------------------------------------------------------
def select_contract_line(item_id, room, instant):
    """Return (contract_line, contract) or None for the given instant."""
    candidates = []
    for cl in store.contract_lines.values():
        if cl["item_id"] != item_id:
            continue
        if cl["activation_state"] != "ACTIVE":
            continue
        contract = store.contracts.get(cl["contract_id"])
        if contract is None or contract["status"] != "ACTIVE":
            continue
        if contract["member_class_scope"] != room["gpo_member_class"]:
            continue
        try:
            eff_from = parse_iso(contract["effective_from"])
            eff_to = parse_iso(contract["effective_to"])
        except Exception:
            continue
        # CLOSED interval on both ends
        if not (eff_from <= instant <= eff_to):
            continue
        candidates.append((cl, contract, eff_from))
    if not candidates:
        return None
    candidates.sort(key=lambda triple: (
        triple[0]["tier_price_cents"],          # lowest tier price first
        -triple[2].timestamp(),                 # later parent effective_from wins
        sort_key(triple[0]),                    # earlier contract-line created_at
    ))
    winner = candidates[0]
    return winner[0], winner[1]


def compute_unit_price(item, room, instant, formulary_item=None):
    """The pinned/settled unit price formula. Raises when no candidate exists."""
    selection = select_contract_line(item["id"], room, instant)
    if selection is None:
        raise ApiError(
            "ERR_NO_ACTIVE_CONTRACT_PRICE",
            "No ACTIVE contract line prices item %s for member class %s at this instant."
            % (item["id"], room["gpo_member_class"]),
        )
    contract_line, contract = selection
    base = Decimal(contract_line["tier_price_cents"])
    tier_priced = round_half_up(base * TIER_MULT[contract["tier"]])
    if item["uom"] == "EA" and formulary_item is not None and formulary_item.get("lum_enabled"):
        lum_adj = LUM_FEE_CENTS_PER_EA
    else:
        lum_adj = 0
    if item["handling_class"] in COLD_CLASSES:
        cold_adj = max(COLD_HANDLING_MIN_CENTS, round_half_up(base * COLD_HANDLING_PCT))
    else:
        cold_adj = 0
    raw = tier_priced + lum_adj + cold_adj
    # floor first, WAC ceiling second
    priced = max(raw, contract_line["floor_price_cents"])
    priced = min(priced, item["wac_cents"])
    return priced, contract_line


# ---------------------------------------------------------------------------
# order_total (SCAFFOLD 1.3 / PRD 3.4)
# ---------------------------------------------------------------------------
def line_quantity_basis(line):
    if line["line_status"] in ("ALLOCATED", "DELIVERED"):
        return line["allocated_qty"]
    return line["requested_qty"]


def compute_line_amounts(line):
    if line["line_status"] not in TOTAL_PARTICIPATING_STATUSES:
        return 0, 0
    extended = line["pinned_unit_price_cents"] * line_quantity_basis(line)
    fee = round_half_up(Decimal(extended) * DIST_FEE_PCT)
    return extended, fee


def recompute_order_total(order):
    """Rewrite every line's extended/fee figure and return the order total."""
    total = 0
    for line in lines_of_order(order):
        extended, fee = compute_line_amounts(line)
        if line["extended_price_cents"] != extended or line["line_fee_cents"] != fee:
            line["extended_price_cents"] = extended
            line["line_fee_cents"] = fee
            touch(line)
        total += extended + fee
    return total


def apply_order_total(order):
    """Recompute the total, adjust the room ledger and cascade a rebill."""
    previous = order["order_total_cents"]
    total = recompute_order_total(order)
    if total == previous:
        return total
    order["order_total_cents"] = total
    touch(order)
    if order["fulfillment_status"] in COMMITTED_FULFILLMENT_STATUSES:
        room = room_of_order(order)
        if room is not None:
            room["open_commitment_cents"] = room["open_commitment_cents"] + (total - previous)
            touch(room)
    if order["settlement_status"] == "CLAIMED":
        trigger_rebill(order)
    return total


def trigger_rebill(order):
    """CLAIMED order whose total changed -> REBILL_REQUIRED on both axes."""
    order["settlement_status"] = "REBILL_REQUIRED"
    touch(order)
    for claim in claims_of_order(order["id"]):
        if claim["status"] == "SUBMITTED":
            claim["status"] = "REBILL_REQUIRED"
            touch(claim)
            contract = store.contracts.get(claim["contract_id"])
            if contract is not None:
                contract["chargeback_payable_cents"] = (
                    contract["chargeback_payable_cents"] - claim["net_chargeback_cents"])
                touch(contract)
            break


# ---------------------------------------------------------------------------
# FEFO allocation (PRD 3.5)
# ---------------------------------------------------------------------------
def find_fefo_lot(line):
    instant = clock_now()
    candidates = []
    for lot in store.lots.values():
        if lot["item_id"] != line["item_id"]:
            continue
        if lot["status"] != "AVAILABLE":
            continue
        try:
            expiry = parse_iso(lot["expiry_date"])
        except Exception:
            continue
        if not (expiry > instant):
            continue
        if lot["quantity_on_hand"] < line["requested_qty"]:
            continue
        candidates.append((expiry, lot))
    if not candidates:
        return None
    candidates.sort(key=lambda pair: (pair[0], sort_key(pair[1])))
    return candidates[0][1]


def allocate_order(order):
    allocated_any = False
    for line in lines_of_order(order):
        if line["line_status"] not in ("OPEN", "BACKORDERED", "SUBSTITUTED"):
            continue
        lot = find_fefo_lot(line)
        if lot is not None:
            lot["quantity_on_hand"] = lot["quantity_on_hand"] - line["requested_qty"]
            touch(lot)
            line["lot_id"] = lot["id"]
            line["allocated_qty"] = line["requested_qty"]
            line["line_status"] = "ALLOCATED"
            touch(line)
            allocated_any = True
        else:
            if line["line_status"] != "BACKORDERED":
                line["line_status"] = "BACKORDERED"
                touch(line)
    return allocated_any


# ---------------------------------------------------------------------------
# route load (SCAFFOLD 1.3 route_cold_chain_load)
# ---------------------------------------------------------------------------
def order_cold_units(order):
    units = 0
    for line in lines_of_order(order):
        if line["line_status"] not in ("ALLOCATED", "DELIVERED"):
            continue
        item = store.items.get(line["item_id"])
        if item is None or item["handling_class"] not in COLD_CLASSES:
            continue
        units += line["allocated_qty"]
    return units


def route_counters(route_id, exclude_order_id=None):
    count = 0
    cold = 0
    for order in store.orders.values():
        if order.get("route_id") != route_id:
            continue
        if exclude_order_id is not None and order["id"] == exclude_order_id:
            continue
        if order["fulfillment_status"] not in ROUTE_LOAD_FULFILLMENT_STATUSES:
            continue
        count += 1
        cold += order_cold_units(order)
    return count, cold


def recompute_route_counters(route):
    count, cold = route_counters(route["id"])
    if route["planned_order_count"] != count or route["cold_units_loaded"] != cold:
        route["planned_order_count"] = count
        route["cold_units_loaded"] = cold
        touch(route)


def route_cold_capacity(route):
    if route["vehicle_class"] == "REEFER_VAN":
        return COLD_CHAIN_ROUTE_CAPACITY_UNITS
    return AMBIENT_VAN_COLD_CAPACITY_UNITS


# ---------------------------------------------------------------------------
# chargeback settlement (PRD 3.9)
# ---------------------------------------------------------------------------
def eligible_claim_lines(order):
    return [ln for ln in lines_of_order(order)
            if ln["line_status"] == "DELIVERED" and ln.get("chargeback_eligible")]


def compute_settlement(order):
    """Four pinned steps. Raises when the eligible set is empty."""
    lines = eligible_claim_lines(order)
    if not lines:
        raise ApiError(
            "ERR_NO_CHARGEBACK_ELIGIBLE_LINES",
            "The order carries no DELIVERED chargeback-eligible line.",
        )
    gross = 0
    for line in lines:
        item = store.items.get(line["item_id"])
        if item is None:
            continue
        settled = line["settled_unit_price_cents"]
        if settled is None:
            settled = 0
        per_unit = item["wac_cents"] - settled
        if per_unit < 0:
            per_unit = 0
        gross += per_unit * line["allocated_qty"]
    if gross < ADMIN_FEE_BRACKET_1_MAX_EXCLUSIVE:
        pct = ADMIN_FEE_PCT_BRACKET_1
    elif gross < ADMIN_FEE_BRACKET_2_MAX_EXCLUSIVE:
        pct = ADMIN_FEE_PCT_BRACKET_2
    else:
        pct = ADMIN_FEE_PCT_BRACKET_3
    fee = round_half_up(Decimal(gross) * pct)
    net = gross - fee
    return {
        "gross_chargeback_cents": gross,
        "admin_fee_pct": float(pct),
        "admin_fee_cents": fee,
        "net_chargeback_cents": net,
        "eligible_line_count": len(lines),
    }


# ---------------------------------------------------------------------------
# contract activation cascades (PRD 3.2)
# ---------------------------------------------------------------------------
def contract_lines_of(contract_id):
    return by_creation([cl for cl in store.contract_lines.values()
                        if cl["contract_id"] == contract_id])


def activate_contract_lines(contract):
    for line in contract_lines_of(contract["id"]):
        if line["activation_state"] != "ACTIVE":
            line["activation_state"] = "ACTIVE"
            touch(line)


def block_contract_lines(contract):
    for line in contract_lines_of(contract["id"]):
        if line["activation_state"] == "ACTIVE":
            line["activation_state"] = "BLOCKED"
            touch(line)


def contract_prices_items(contract_id):
    return set(cl["item_id"] for cl in store.contract_lines.values()
               if cl["contract_id"] == contract_id)


def check_contract_overlap(contract):
    """Validation priority 17."""
    try:
        new_from = parse_iso(contract["effective_from"])
        new_to = parse_iso(contract["effective_to"])
    except Exception:
        return
    own_items = contract_prices_items(contract["id"])
    for other in by_creation(list(store.contracts.values())):
        if other["id"] == contract["id"]:
            continue
        if other["status"] != "ACTIVE":
            continue
        if other["manufacturer_code"] != contract["manufacturer_code"]:
            continue
        if other["member_class_scope"] != contract["member_class_scope"]:
            continue
        if not (own_items & contract_prices_items(other["id"])):
            continue
        try:
            other_from = parse_iso(other["effective_from"])
            other_to = parse_iso(other["effective_to"])
        except Exception:
            continue
        if not (new_from <= other_to and other_from <= new_to):
            continue
        if contract.get("supersedes_contract_id") == other["id"]:
            continue
        raise ApiError(
            "ERR_CONTRACT_PERIOD_OVERLAP",
            "Contract %s is already ACTIVE over an intersecting period for a shared item."
            % other["id"],
        )


# ---------------------------------------------------------------------------
# recall cascade (PRD 3.8)
# ---------------------------------------------------------------------------
def cascade_recall(notice):
    # HOP 1 - lots
    scoped_lots = []
    for lot in store.lots.values():
        if lot["item_id"] != notice["item_id"]:
            continue
        if notice.get("lot_id") is not None and lot["id"] != notice["lot_id"]:
            continue
        if lot["status"] not in ("AVAILABLE", "EXCURSION_HOLD"):
            continue
        scoped_lots.append(lot)
    scoped_lots = by_creation(scoped_lots)
    quarantined_ids = []
    for lot in scoped_lots:
        was_hold = lot["status"] == "EXCURSION_HOLD"
        lot["status"] = "QUARANTINED"
        if was_hold:
            lot["excursion_flagged_by_user_id"] = None
        touch(lot)
        quarantined_ids.append(lot["id"])

    # HOP 2 - order lines
    affected_lines = [ln for ln in store.order_lines.values()
                      if ln["line_status"] == "ALLOCATED" and ln.get("lot_id") in quarantined_ids]
    affected_lines = by_creation(affected_lines)
    affected_order_ids = []
    for line in affected_lines:
        lot = store.lots.get(line["lot_id"])
        if lot is not None:
            lot["quantity_on_hand"] = lot["quantity_on_hand"] + line["allocated_qty"]
            touch(lot)
        line["allocated_qty"] = 0
        line["lot_id"] = None
        line["line_status"] = "BACKORDERED"
        line["extended_price_cents"] = 0
        line["line_fee_cents"] = 0
        touch(line)
        if line["order_id"] not in affected_order_ids:
            affected_order_ids.append(line["order_id"])

    # HOP 3 - orders
    held_orders = []
    affected_orders = by_creation([store.orders[oid] for oid in affected_order_ids
                                   if oid in store.orders])
    for order in affected_orders:
        apply_order_total(order)
        lines = lines_of_order(order)
        if (order["fulfillment_status"] == "ALLOCATED" and lines and
                all(ln["line_status"] in ("BACKORDERED", "SHORTED", "CANCELLED") for ln in lines)):
            order["fulfillment_status"] = "HELD"
            touch(order)
            held_orders.append(order)

    # HOP 4 - routes
    for order in held_orders:
        route_id = order.get("route_id")
        if not route_id:
            continue
        order["route_id"] = None
        order["stop_arrival_min"] = None
        order["stop_service_minutes"] = None
        order["service_date"] = None
        touch(order)
        route = store.routes.get(route_id)
        if route is None:
            continue
        recompute_route_counters(route)
        if route["status"] == "PLANNED" and route["planned_order_count"] == 0:
            route["status"] = "CANCELLED"
            if route["cold_units_loaded"] != 0:
                route["cold_units_loaded"] = 0
            touch(route)

    notice["quarantined_lot_count"] = len(quarantined_ids)
    notice["backordered_line_count"] = len(affected_lines)
