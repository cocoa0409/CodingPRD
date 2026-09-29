"""Shared lookups, derived-field synchronisation and cascade fragments."""

import clock
from db import base_row, db, sort_rows, touch
from errors import ApiError
from services import calc

# ---------------------------------------------------------------------------
# path / body identifier resolution (checks 4 and 7)
# ---------------------------------------------------------------------------


def _require(collection, row_id, error_id):
    row = collection.get(row_id)
    if row is None:
        raise ApiError(error_id)
    return row


def require_store(store_id):
    return _require(db.stores, store_id, "ERR_STORE_NOT_FOUND")


def require_customer(customer_id):
    return _require(db.customers, customer_id, "ERR_CUSTOMER_NOT_FOUND")


def require_reference(reference_id):
    return _require(db.references, reference_id, "ERR_REFERENCE_NOT_FOUND")


def require_unit(unit_id):
    return _require(db.units, unit_id, "ERR_UNIT_NOT_FOUND")


def require_crew(crew_id):
    return _require(db.crews, crew_id, "ERR_CREW_NOT_FOUND")


def require_agreement(agreement_id):
    return _require(db.agreements, agreement_id, "ERR_AGREEMENT_NOT_FOUND")


def require_delivery_order(order_id):
    return _require(db.delivery_orders, order_id, "ERR_DELIVERY_ORDER_NOT_FOUND")


def require_ticket(ticket_id):
    return _require(db.tickets, ticket_id, "ERR_TICKET_NOT_FOUND")


def require_inspection(inspection_id):
    return _require(db.inspections, inspection_id, "ERR_INSPECTION_NOT_FOUND")


def require_payment(payment_id):
    return _require(db.payments, payment_id, "ERR_PAYMENT_NOT_FOUND")


def require_quote(quote_id):
    return _require(db.quotes, quote_id, "ERR_QUOTE_NOT_FOUND")


def require_state_rule_row(rule_id):
    return _require(db.state_rules, rule_id, "ERR_STATE_RULE_NOT_FOUND")


def require_ledger_entry(entry_id):
    return _require(db.ledger, entry_id, "ERR_LEDGER_ENTRY_NOT_FOUND")


# ---------------------------------------------------------------------------
# statutory rules (checks 8, snapshot pinning)
# ---------------------------------------------------------------------------


def rule_for_state(state_code):
    for rule in db.state_rules.values():
        if rule["state_code"] == state_code:
            return rule
    return None


def require_rule_for_state(state_code):
    rule = rule_for_state(state_code)
    if rule is None:
        raise ApiError("ERR_STATE_RULE_NOT_CONFIGURED")
    return rule


def pinned_rule(agreement):
    """Every fee and limit is read from the rule pinned at signing (PRD 2.5)."""
    return require_rule_for_state(agreement["state_code_snapshot"])


# ---------------------------------------------------------------------------
# agreement state gates (checks 12 and 13)
# ---------------------------------------------------------------------------

OP_PAYMENT = "payment"
OP_QUOTE_ISSUE = "quote_issue"
OP_QUOTE_ACCEPT = "quote_accept"
OP_RETURN = "return"
OP_REPOSSESS = "repossess"
OP_TICKET_CREATE = "ticket_create"
OP_DELIVERY_CREATE = "delivery_create"
OP_CONTACT = "contact"
OP_DELIVERY_COMPLETE = "delivery_complete"
OP_SWAP_ISSUE = "swap_issue"


def check_payment_status(agreement, operation):
    status = agreement["payment_status"]
    if status == "CLOSED":
        raise ApiError("ERR_AGREEMENT_CLOSED")
    if operation == OP_REPOSSESS:
        if status != "DEFAULTED":
            raise ApiError("ERR_AGREEMENT_NOT_DEFAULTED")
        return
    if operation == OP_CONTACT:
        return
    if status == "DEFAULTED":
        raise ApiError("ERR_AGREEMENT_DEFAULTED")
    if operation in (OP_QUOTE_ISSUE, OP_QUOTE_ACCEPT) and status != "CURRENT":
        raise ApiError("ERR_AGREEMENT_NOT_CURRENT")


IN_POSSESSION = ("DELIVERED", "SERVICE_SWAP_PENDING")


def check_possession_status(agreement, operation):
    status = agreement["possession_status"]
    if operation == OP_DELIVERY_COMPLETE:
        if status != "PENDING_DELIVERY":
            raise ApiError("ERR_POSSESSION_STATE_INVALID")
        return
    if status not in IN_POSSESSION:
        raise ApiError("ERR_POSSESSION_STATE_INVALID")


def check_expected_version(agreement, expected):
    if expected != agreement["version"]:
        raise ApiError("ERR_STALE_AGREEMENT_VERSION")


# ---------------------------------------------------------------------------
# derived field synchronisation
# ---------------------------------------------------------------------------


def sync_store(store):
    """Possession conservation for one store (PRD 2.10)."""
    on_rent = 0
    in_service = 0
    for unit in db.units.values():
        if unit["store_id"] != store["id"]:
            continue
        if unit["status"] == "ON_RENT":
            on_rent += 1
        elif unit["status"] == "IN_SERVICE":
            in_service += 1
    intake_open = in_service < store["service_bay_capacity"]
    if (
        store["units_on_rent_count"] != on_rent
        or store["units_in_service_count"] != in_service
        or store["service_intake_open"] != intake_open
    ):
        store["units_on_rent_count"] = on_rent
        store["units_in_service_count"] = in_service
        store["service_intake_open"] = intake_open
        touch(store)
    return store


def customer_ledger_entries(customer_id):
    return [e for e in db.ledger.values() if e["customer_id"] == customer_id]


def sync_customer(customer):
    """Verified references, point conservation and adverse posture (PRD 2.10, 2.11)."""
    verified = sum(
        1
        for ref in db.references.values()
        if ref["customer_id"] == customer["id"] and ref["check_status"] == "VERIFIED"
    )
    balance = 0
    lifetime = 0
    for entry in customer_ledger_entries(customer["id"]):
        balance += entry["delta_points"]
        if entry["delta_points"] > 0:
            lifetime += entry["delta_points"]
    tier = calc.loyalty_tier_for_lifetime(lifetime)
    adverse = sum(
        1
        for ag in db.agreements.values()
        if ag["customer_id"] == customer["id"] and ag["collections_stage"] == "ADVERSE"
    )
    flag = "ADVERSE" if adverse >= 1 else "NORMAL"
    if (
        customer["verified_reference_count"] != verified
        or customer["loyalty_points_balance"] != balance
        or customer["loyalty_points_lifetime"] != lifetime
        or customer["loyalty_tier"] != tier
        or customer["adverse_agreement_count"] != adverse
        or customer["account_flag"] != flag
    ):
        customer["verified_reference_count"] = verified
        customer["loyalty_points_balance"] = balance
        customer["loyalty_points_lifetime"] = lifetime
        customer["loyalty_tier"] = tier
        customer["adverse_agreement_count"] = adverse
        customer["account_flag"] = flag
        touch(customer)
    return customer


def append_ledger_entry(customer, agreement_id, source_payment_id, entry_type, delta_points):
    entry = base_row(versioned=False)
    entry["customer_id"] = customer["id"]
    entry["agreement_id"] = agreement_id
    entry["source_payment_id"] = source_payment_id
    entry["entry_type"] = entry_type
    entry["delta_points"] = delta_points
    entry["balance_after"] = 0
    entry["occurred_at"] = clock.now_str()
    db.ledger[entry["id"]] = entry
    sync_customer(customer)
    entry["balance_after"] = customer["loyalty_points_balance"]
    return entry


def period_days(agreement):
    return calc.PERIOD_DAYS[agreement["term_type"]]


def due_date_for(agreement, periods_paid):
    anchor = clock.parse(agreement["cycle_anchor_at"])
    if anchor is None:
        return None
    return clock.plus_days(anchor, period_days(agreement) * (periods_paid + 1))


def sync_agreement_money(agreement):
    """Counters that are always functions of other counters (PRD 3.5)."""
    agreement["rent_applied_cents"] = (
        agreement["periods_paid"] * agreement["renewal_rate_cents"]
    )
    agreement["late_fee_balance_cents"] = (
        agreement["late_fee_assessed_cents"] - agreement["late_fee_paid_cents"]
    )
    agreement["reinstatement_fee_balance_cents"] = (
        agreement["reinstatement_fee_assessed_cents"]
        - agreement["reinstatement_fee_paid_cents"]
    )
    agreement["paid_pct"] = calc.ratio_4dp(
        agreement["rent_applied_cents"], agreement["total_of_payments_cents"]
    )
    due = due_date_for(agreement, agreement["periods_paid"])
    agreement["current_period_due_at"] = clock.fmt(due) if due else None
    return agreement


# ---------------------------------------------------------------------------
# related-row helpers
# ---------------------------------------------------------------------------


def agreement_windows(agreement_id):
    return [w for w in db.windows.values() if w["agreement_id"] == agreement_id]


def open_window(agreement_id):
    """At most one can exist; the earliest by created_at is taken (PRD 3.5)."""
    rows = [w for w in agreement_windows(agreement_id) if w["status"] == "OPEN"]
    rows = sort_rows(rows)
    return rows[0] if rows else None


def agreement_payments(agreement_id):
    return [p for p in db.payments.values() if p["agreement_id"] == agreement_id]


def latest_posted_payment(agreement_id):
    rows = [p for p in agreement_payments(agreement_id) if p["status"] == "POSTED"]
    rows = sort_rows(rows, "posted_at")
    return rows[-1] if rows else None


def agreement_tickets(agreement_id):
    return [t for t in db.tickets.values() if t["agreement_id"] == agreement_id]


def agreement_delivery_orders(agreement_id):
    return [d for d in db.delivery_orders.values() if d["agreement_id"] == agreement_id]


def agreement_quotes(agreement_id):
    return [q for q in db.quotes.values() if q["agreement_id"] == agreement_id]


def agreement_contacts(agreement_id):
    return [c for c in db.contacts.values() if c["agreement_id"] == agreement_id]


# ---------------------------------------------------------------------------
# cascade fragments shared by return, repossession and early purchase
# ---------------------------------------------------------------------------


def write_provisional_residual(unit):
    unit["residual_value_cents"] = calc.provisional_residual_cents(unit)
    unit["residual_valuation_basis"] = "PROVISIONAL"
    touch(unit)
    return unit


def cancel_scheduled_delivery_orders(agreement):
    """A delivery order still SCHEDULED releases its crew window."""
    for order in sort_rows(agreement_delivery_orders(agreement["id"]), "window_start_at"):
        if order["status"] == "SCHEDULED":
            order["status"] = "CANCELLED"
            touch(order)


def void_open_tickets(agreement, touched_stores):
    """Every live ticket on the agreement releases its bay (PRD 3.8, 3.9)."""
    for ticket in sort_rows(agreement_tickets(agreement["id"]), "window_start_at"):
        if ticket["status"] not in ("SCHEDULED", "SWAP_ISSUED"):
            continue
        was_swapped = ticket["status"] == "SWAP_ISSUED"
        ticket["status"] = "VOIDED"
        touch(ticket)
        if not was_swapped:
            continue
        replacement_id = ticket.get("replacement_unit_id")
        if replacement_id:
            replacement = db.units.get(replacement_id)
            if replacement is not None and replacement["status"] == "ON_RENT":
                replacement["status"] = "AVAILABLE"
                replacement["rent_cycle_count"] += 1
                touch(replacement)
                touched_stores.add(replacement["store_id"])
        serviced = db.units.get(ticket["unit_id"])
        if serviced is not None and serviced["status"] == "IN_SERVICE":
            serviced["status"] = "AVAILABLE"
            touch(serviced)
            touched_stores.add(serviced["store_id"])


def expire_open_window(agreement):
    window = open_window(agreement["id"])
    if window is not None:
        window["status"] = "EXPIRED"
        touch(window)
    return window
