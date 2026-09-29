"""Domain services: chain resolution, allocation, totals, exposure, cascades."""

from decimal import Decimal

from db import db, now, fmt, parse_stored, touch, sort_key, whole_days_between
from errors import ApiError
from services import calc

SUBTOTAL_STATUSES = ("RESOLVED", "ALLOCATED", "BACKORDERED", "SHIPPED", "RETURNED")
CORE_STATUSES = ("SHIPPED", "RETURNED")
FREIGHT_STATUSES = ("ALLOCATED", "SHIPPED")
EXPOSURE_FULFILLMENT = ("DRAFT", "ALLOCATED", "HELD")
RA_COMMITTED = ("REQUESTED", "APPROVED", "RECEIVED", "CREDITED")


# --------------------------------------------------------------------------
# lookups
# --------------------------------------------------------------------------

def find(table, row_id, error_id):
    row = table.get(row_id) if isinstance(row_id, str) else None
    if row is None:
        raise ApiError(error_id, "%s not found" % error_id)
    return row


def part_or_404(part_id):
    return find(db.parts, part_id, "ERR_PART_NOT_FOUND")


def branch_or_404(branch_id):
    return find(db.branches, branch_id, "ERR_BRANCH_NOT_FOUND")


def account_or_404(account_id):
    return find(db.servicer_accounts, account_id, "ERR_SERVICER_ACCOUNT_NOT_FOUND")


def tier_or_404(tier_id):
    return find(db.pricing_tiers, tier_id, "ERR_PRICING_TIER_NOT_FOUND")


def order_or_404(order_id):
    return find(db.part_orders, order_id, "ERR_PART_ORDER_NOT_FOUND")


def line_or_404(line_id):
    return find(db.order_lines, line_id, "ERR_ORDER_LINE_NOT_FOUND")


def rows_sorted(table):
    return sorted(table.values(), key=sort_key)


# --------------------------------------------------------------------------
# supersession chain
# --------------------------------------------------------------------------

def resolve_chain(requested_part):
    """Returns (resolved_part, hops, substitute_required)."""
    cursor = requested_part
    hops = 0
    visited = set([cursor["id"]])
    while True:
        status = cursor["lifecycle_status"]
        if status == "ACTIVE":
            return cursor, hops, False
        if status == "OBSOLETE":
            return cursor, hops, True
        if status == "NLA":
            raise ApiError("ERR_PART_NO_LONGER_AVAILABLE",
                           "Part %s is no longer available" % cursor["id"])
        # SUPERSEDED
        if not cursor.get("superseded_by_part_id"):
            raise ApiError("ERR_SUPERSESSION_CHAIN_BROKEN",
                           "Part %s is SUPERSEDED with no successor" % cursor["id"])
        nxt = db.parts.get(cursor["superseded_by_part_id"])
        if nxt is None:
            raise ApiError("ERR_SUPERSESSION_CHAIN_BROKEN",
                           "Part %s points at a missing successor" % cursor["id"])
        if nxt["id"] in visited:
            raise ApiError("ERR_SUPERSESSION_CYCLE_DETECTED",
                           "Supersession chain cycles back on itself")
        hops += 1
        if hops > calc.MAX_SUPERSESSION_HOPS:
            raise ApiError("ERR_SUPERSESSION_CHAIN_TOO_LONG",
                           "Supersession chain exceeds %d hops"
                           % calc.MAX_SUPERSESSION_HOPS)
        visited.add(nxt["id"])
        cursor = nxt


# --------------------------------------------------------------------------
# authorization / certification gates
# --------------------------------------------------------------------------

def check_oem_authorization(account, part):
    if part["oem_code"] not in (account.get("oem_authorizations") or []):
        raise ApiError("ERR_OEM_AUTHORIZATION_MISSING",
                       "Account is not authorized for OEM %s" % part["oem_code"])


def cert_is_effective(cert):
    if cert["cert_status"] != "ACTIVE":
        return False
    current = now()
    trained = parse_stored(cert["training_completed_at"])
    expires = parse_stored(cert["expires_at"])
    return trained <= current and expires >= current


def account_certs(account_id):
    return [c for c in rows_sorted(db.technician_certifications)
            if c["servicer_account_id"] == account_id]


def effective_cert_count(account_id):
    return len([c for c in account_certs(account_id) if cert_is_effective(c)])


def check_technician_cert(account, part):
    required = calc.cert_level_required(part)
    if required == "NONE":
        return
    need = calc.CERT_RANK[required]
    for cert in account_certs(account["id"]):
        if cert["oem_code"] != part["oem_code"]:
            continue
        if not cert_is_effective(cert):
            continue
        if calc.CERT_RANK.get(cert["cert_level"], 0) >= need:
            return
    raise ApiError("ERR_TECHNICIAN_CERT_REQUIRED",
                   "An effective %s certification for OEM %s is required"
                   % (required, part["oem_code"]))


# --------------------------------------------------------------------------
# order aggregates
# --------------------------------------------------------------------------

def order_lines_of(order):
    return sorted([l for l in db.order_lines.values()
                   if l["part_order_id"] == order["id"]], key=sort_key)


def orders_of_account(account_id):
    return sorted([o for o in db.part_orders.values()
                   if o["servicer_account_id"] == account_id], key=sort_key)


def compute_subtotal(order):
    total = 0
    for line in order_lines_of(order):
        if line["line_status"] in SUBTOTAL_STATUSES:
            total += line["extended_price_cents"] or 0
    return total


def compute_core_total(order):
    total = 0
    for line in order_lines_of(order):
        if line["line_status"] not in CORE_STATUSES:
            continue
        part = db.parts.get(line["resolved_part_id"])
        if part is not None and part["core_required"]:
            total += (line["core_deposit_cents"] or 0) * line["quantity"]
    return total


def compute_freight(order):
    if order["fulfillment_mode"] == "WILL_CALL":
        return 0
    lines = [l for l in order_lines_of(order)
             if l["line_status"] in FREIGHT_STATUSES]
    if not lines:
        # nothing is on the truck, so no freight is assessed
        return 0
    weight = 0
    for line in lines:
        part = db.parts.get(line["resolved_part_id"])
        if part is not None:
            weight += part["weight_grams"] * line["quantity"]
    branch_ids = []
    for line in lines:
        bid = line.get("allocation_branch_id")
        if bid and bid not in branch_ids:
            branch_ids.append(bid)
    branches = [db.branches[b] for b in branch_ids if b in db.branches]
    base_cents = calc.OVERNIGHT_BASE_CENTS
    weight_cents = calc.weight_block_cents(weight)
    surcharge_cents = 0
    late_cents = 0
    if branches:
        surcharge_cents = max(b["overnight_surcharge_cents"] for b in branches)
        earliest_cutoff = min(b["cutoff_hour_utc"] for b in branches)
        if now().hour >= earliest_cutoff:
            late_cents = calc.LATE_CUTOFF_SURCHARGE_CENTS
    if order["subtotal_cents"] >= calc.FREE_FREIGHT_SUBTOTAL_CENTS:
        # the waiver removes base, weight and surcharge only
        return late_cents
    return base_cents + weight_cents + surcharge_cents + late_cents


def recompute_totals(order, reassess_freight=True):
    """Recompute the money aggregates.

    Freight is re-assessed only where the PRD says it is: at allocation, at
    hand-over, after a line cancellation, and during a re-allocation sweep.
    """
    order["subtotal_cents"] = compute_subtotal(order)
    order["core_deposit_total_cents"] = compute_core_total(order)
    if reassess_freight:
        order["freight_cents"] = compute_freight(order)
    order["total_cents"] = (order["subtotal_cents"]
                            + order["core_deposit_total_cents"]
                            + order["freight_cents"])


def ship_date_subtotal(order):
    total = 0
    for line in order_lines_of(order):
        if line["line_status"] in CORE_STATUSES \
                and line.get("invoiced_unit_price_cents") is not None:
            total += line["invoiced_unit_price_cents"] * line["quantity"]
    return total


# --------------------------------------------------------------------------
# inventory & allocation
# --------------------------------------------------------------------------

def available_units(record):
    return record["on_hand_units"] - record["reserved_units"]


def inventory_for(branch_id, part_id):
    for record in rows_sorted(db.inventory_records):
        if record["branch_id"] == branch_id and record["part_id"] == part_id:
            return record
    return None


def select_branch_record(order, line):
    candidates = []
    for record in rows_sorted(db.inventory_records):
        if record["part_id"] != line["resolved_part_id"]:
            continue
        if available_units(record) < line["quantity"]:
            continue
        branch = db.branches.get(record["branch_id"])
        if branch is None or branch["branch_status"] != "OPEN":
            continue
        if order["fulfillment_mode"] == "WILL_CALL":
            if record["branch_id"] != order.get("pickup_branch_id"):
                continue
            if not branch["will_call_enabled"]:
                continue
        candidates.append((record, branch))
    if not candidates:
        return None
    candidates.sort(key=lambda pair: (
        -available_units(pair[0]),
        pair[1]["overnight_surcharge_cents"],
        pair[1]["created_at"],
        pair[1]["_seq"],
    ))
    return candidates[0][0]


def release_reservation(line):
    """Give back a line's reservation, if it holds one."""
    if not line.get("allocation_branch_id"):
        return
    record = inventory_for(line["allocation_branch_id"], line["resolved_part_id"])
    if record is not None:
        record["reserved_units"] = max(0, record["reserved_units"] - line["quantity"])
        touch(record)
    line["allocation_branch_id"] = None


def allocation_sweep(order, eligible_statuses):
    """Run the per-line allocation sweep; returns the number of allocated lines."""
    allocated = 0
    for line in order_lines_of(order):
        if line["line_status"] not in eligible_statuses:
            continue
        record = select_branch_record(order, line)
        if record is None:
            if line["line_status"] != "BACKORDERED":
                line["line_status"] = "BACKORDERED"
                touch(line)
            continue
        record["reserved_units"] = record["reserved_units"] + line["quantity"]
        touch(record)
        line["line_status"] = "ALLOCATED"
        line["allocation_branch_id"] = record["branch_id"]
        touch(line)
        allocated += 1
    return allocated


# --------------------------------------------------------------------------
# account aggregates
# --------------------------------------------------------------------------

def credit_used_cents(account_id):
    open_exposure = 0
    for order in orders_of_account(account_id):
        if order["settlement_status"] == "INVOICED":
            open_exposure += order.get("invoiced_total_cents") or 0
        elif order["settlement_status"] in ("PENDING_CREDIT", "CREDIT_APPROVED") \
                and order["fulfillment_status"] in EXPOSURE_FULFILLMENT:
            open_exposure += order["total_cents"]
    credits = 0
    for ra in db.return_authorizations.values():
        if ra["servicer_account_id"] == account_id and ra["ra_status"] == "CREDITED":
            credits += ra.get("credit_amount_cents") or 0
    for claim in db.warranty_claims.values():
        if claim["servicer_account_id"] == account_id \
                and claim["claim_status"] == "CREDITED":
            credits += claim.get("credit_amount_cents") or 0
    return max(0, open_exposure - credits)


def open_order_count(account_id):
    count = 0
    for order in orders_of_account(account_id):
        if order["settlement_status"] == "INVOICED":
            count += 1
        elif order["settlement_status"] in ("PENDING_CREDIT", "CREDIT_APPROVED") \
                and order["fulfillment_status"] in EXPOSURE_FULFILLMENT:
            count += 1
    return count


def core_liability_cents(account_id):
    total = 0
    for order in orders_of_account(account_id):
        for line in order_lines_of(order):
            if line["line_status"] not in CORE_STATUSES:
                continue
            part = db.parts.get(line["resolved_part_id"])
            if part is not None and part["core_required"]:
                total += (line["core_deposit_cents"] or 0) * line["quantity"]
    for ra in db.return_authorizations.values():
        if ra["servicer_account_id"] == account_id \
                and ra["ra_status"] == "CREDITED" \
                and ra["reason_code"] == "CORE_RETURN":
            total -= ra.get("core_deposit_refund_cents") or 0
    return total


def sync_account(account):
    """Refresh the account's derived money fields; bump version only on change."""
    changed = False
    used = credit_used_cents(account["id"])
    if account["credit_used_cents"] != used:
        account["credit_used_cents"] = used
        changed = True
    liability = core_liability_cents(account["id"])
    if account["core_liability_cents"] != liability:
        account["core_liability_cents"] = liability
        changed = True
    if changed:
        touch(account)
    return changed


def _within_window(anchor, days):
    if anchor is None:
        return False
    return whole_days_between(parse_stored(anchor), now()) <= days


def delinquency_score(account, variant):
    window = calc.DELINQUENCY_ROLLING_WINDOW_DAYS
    rolling = variant == "rolling"
    term_days = calc.CREDIT_TERM_DAYS.get(account["credit_terms"], 0)

    overdue = 0
    for order in orders_of_account(account["id"]):
        if order["settlement_status"] != "INVOICED":
            continue
        if not order.get("fulfilled_at"):
            continue
        elapsed = whole_days_between(parse_stored(order["fulfilled_at"]), now())
        if elapsed <= term_days:
            continue
        if rolling and not _within_window(order["fulfilled_at"], window):
            continue
        overdue += 1

    denied = 0
    for claim in db.warranty_claims.values():
        if claim["servicer_account_id"] != account["id"]:
            continue
        if claim["claim_status"] not in ("OEM_DENIED", "VOID"):
            continue
        if rolling and not _within_window(claim.get("submitted_at"), window):
            continue
        denied += 1

    nln = 0
    for ra in db.return_authorizations.values():
        if ra["servicer_account_id"] != account["id"]:
            continue
        if ra["ra_status"] != "CREDITED" or ra["reason_code"] != "NO_LONGER_NEEDED":
            continue
        if rolling and not _within_window(ra.get("received_at"), window):
            continue
        nln += 1

    bonus = min(calc.DELINQUENCY_CERT_BONUS_PER * effective_cert_count(account["id"]),
                calc.DELINQUENCY_CERT_BONUS_CAP)
    score = (calc.DELINQUENCY_BASE_SCORE
             - calc.DELINQUENCY_OVERDUE_PENALTY * overdue
             - calc.DELINQUENCY_DENIED_CLAIM_PENALTY * denied
             - calc.DELINQUENCY_NLN_RETURN_PENALTY * nln
             + bonus)
    return calc.clamp_score(score)


def rolling_12m_volume_cents(account):
    total = 0
    for order in orders_of_account(account["id"]):
        if order["settlement_status"] not in ("INVOICED", "PAID"):
            continue
        if not order.get("fulfilled_at"):
            continue
        elapsed = whole_days_between(parse_stored(order["fulfilled_at"]), now())
        if elapsed <= calc.TIER_LOOKBACK_DAYS:
            total += order.get("invoiced_total_cents") or 0
    return total


def assign_pricing_tier(volume):
    tiers = rows_sorted(db.pricing_tiers)
    if not tiers:
        return None
    eligible = [t for t in tiers if t["min_annual_volume_cents"] <= volume]
    if eligible:
        best = sorted(eligible, key=lambda t: (-t["min_annual_volume_cents"],
                                               t["tier_code"]))[0]
    else:
        best = sorted(tiers, key=lambda t: (t["min_annual_volume_cents"],
                                            t["tier_code"]))[0]
    return best


# --------------------------------------------------------------------------
# substitute requests
# --------------------------------------------------------------------------

def pending_substitutes_for_order(order):
    line_ids = set(l["id"] for l in order_lines_of(order))
    return [s for s in rows_sorted(db.substitute_requests)
            if s["order_line_id"] in line_ids and s["request_status"] == "PENDING"]


def pending_substitutes_for_line(line):
    return [s for s in rows_sorted(db.substitute_requests)
            if s["order_line_id"] == line["id"] and s["request_status"] == "PENDING"]


# --------------------------------------------------------------------------
# cascades
# --------------------------------------------------------------------------

def freeze_account_orders(account):
    """ACTIVE -> CREDIT_HOLD: freeze every ALLOCATED order of the account."""
    for order in orders_of_account(account["id"]):
        if order["fulfillment_status"] != "ALLOCATED":
            continue
        for line in order_lines_of(order):
            if line["line_status"] == "ALLOCATED":
                release_reservation(line)
                line["line_status"] = "BACKORDERED"
                touch(line)
        order["fulfillment_status"] = "HELD"
        order["hold_reason"] = "CREDIT_HOLD"
        # PRD 3.2 lists exactly what a freeze changes; freight is not
        # re-assessed here and neither the subtotal nor the total move,
        # because ALLOCATED and BACKORDERED lines both count in the subtotal.
        touch(order)


def release_order(order):
    """HELD -> ALLOCATED attempt with a re-allocation sweep."""
    allocated = allocation_sweep(order, ("RESOLVED", "BACKORDERED"))
    if allocated > 0:
        order["fulfillment_status"] = "ALLOCATED"
        order["hold_reason"] = None
    else:
        order["fulfillment_status"] = "HELD"
        order["hold_reason"] = "BACKORDER"
    recompute_totals(order)
    touch(order)


def release_account_orders(account):
    """CREDIT_HOLD -> ACTIVE: try to release every credit-frozen order."""
    for order in orders_of_account(account["id"]):
        if order["fulfillment_status"] == "HELD" \
                and order["hold_reason"] == "CREDIT_HOLD":
            release_order(order)


def release_order_if_ready(order):
    """Release a HELD order once no substitute request is pending on it."""
    if order["fulfillment_status"] != "HELD":
        return
    if pending_substitutes_for_order(order):
        return
    account = db.servicer_accounts.get(order["servicer_account_id"])
    if account is None or account["account_status"] != "ACTIVE":
        return
    release_order(order)


def cancel_order(order):
    """Shared cancellation body (explicit cancel and the suspension cascade)."""
    for line in order_lines_of(order):
        if line["line_status"] in ("RESOLVED", "ALLOCATED", "BACKORDERED",
                                  "SUBSTITUTE_PENDING"):
            release_reservation(line)
            for request in pending_substitutes_for_line(line):
                request["request_status"] = "WITHDRAWN"
                touch(request)
            line["line_status"] = "CANCELLED"
            touch(line)
    if order["settlement_status"] == "CREDIT_APPROVED":
        order["settlement_status"] = "CREDIT_DECLINED"
    order["fulfillment_status"] = "CANCELLED"
    order["hold_reason"] = None
    recompute_totals(order)
    touch(order)


def suspend_account_orders(account):
    for order in orders_of_account(account["id"]):
        if order["settlement_status"] == "INVOICED":
            order["settlement_status"] = "WRITTEN_OFF"
            touch(order)
        elif order["fulfillment_status"] in EXPOSURE_FULFILLMENT:
            cancel_order(order)


def apply_credit_hold(account):
    if account["account_status"] != "ACTIVE":
        return
    account["account_status"] = "CREDIT_HOLD"
    touch(account)
    freeze_account_orders(account)
    sync_account(account)


def maybe_release_credit_hold(account):
    """Auto-release once exposure falls to 90% of the limit or below."""
    if account["account_status"] != "CREDIT_HOLD":
        return
    if account["credit_used_cents"] > calc.hold_release_ceiling(
            account["credit_limit_cents"]):
        return
    account["account_status"] = "ACTIVE"
    touch(account)
    release_account_orders(account)
    sync_account(account)


# --------------------------------------------------------------------------
# credit exposure guard
# --------------------------------------------------------------------------

def check_credit_limit(account, projected_used):
    if projected_used > account["credit_limit_cents"]:
        raise ApiError("ERR_CREDIT_LIMIT_EXCEEDED",
                       "Projected exposure %d exceeds credit limit %d"
                       % (projected_used, account["credit_limit_cents"]))


def projected_credit_used(account, order, projected_total):
    """Exposure with one order's contribution replaced by a projected total."""
    open_exposure = 0
    for other in orders_of_account(account["id"]):
        if other["id"] == order["id"]:
            if other["settlement_status"] in ("PENDING_CREDIT", "CREDIT_APPROVED") \
                    and other["fulfillment_status"] in EXPOSURE_FULFILLMENT:
                open_exposure += projected_total
            elif other["settlement_status"] == "INVOICED":
                open_exposure += other.get("invoiced_total_cents") or 0
            continue
        if other["settlement_status"] == "INVOICED":
            open_exposure += other.get("invoiced_total_cents") or 0
        elif other["settlement_status"] in ("PENDING_CREDIT", "CREDIT_APPROVED") \
                and other["fulfillment_status"] in EXPOSURE_FULFILLMENT:
            open_exposure += other["total_cents"]
    credits = 0
    for ra in db.return_authorizations.values():
        if ra["servicer_account_id"] == account["id"] and ra["ra_status"] == "CREDITED":
            credits += ra.get("credit_amount_cents") or 0
    for claim in db.warranty_claims.values():
        if claim["servicer_account_id"] == account["id"] \
                and claim["claim_status"] == "CREDITED":
            credits += claim.get("credit_amount_cents") or 0
    return max(0, open_exposure - credits)


# --------------------------------------------------------------------------
# price files
# --------------------------------------------------------------------------

def price_file_lines_of(price_file):
    return sorted([l for l in db.price_file_lines.values()
                   if l["price_file_id"] == price_file["id"]], key=sort_key)


def price_file_part_ids(price_file):
    return set(l["part_id"] for l in price_file_lines_of(price_file))
