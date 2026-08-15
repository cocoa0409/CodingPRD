"""Lazy transitions: quote expiry, invoice overdue, pool loan overdue, customer standing."""
from db import store
from services.calc import compute_standing, compute_overdue


def refresh_quote(quote):
    """Apply lazy EXPIRED transition to an ISSUED quote when now >= expires_at."""
    if quote["status"] != "ISSUED":
        return
    if quote["expires_at"] is None:
        return
    now = store.now()
    if now >= quote["expires_at"]:
        quote["status"] = "EXPIRED"
        # side effect: clear work order's active_quote_id and return AWAITING_APPROVAL -> QUOTED
        wo = store.work_orders.get(quote["work_order_id"])
        if wo is not None:
            if wo.get("active_quote_id") == quote["id"]:
                wo["active_quote_id"] = None
            if wo["status"] == "AWAITING_APPROVAL":
                wo["status"] = "QUOTED"
            bump(wo)


def refresh_invoice(invoice):
    """Lazy OVERDUE transition for OPEN invoices past due."""
    if invoice["status"] != "OPEN":
        return
    if invoice["due_at"] is None:
        return
    now = store.now()
    if now > invoice["due_at"] and invoice["balance_due_cents"] > 0:
        invoice["status"] = "OVERDUE"
        bump(invoice)
        recompute_standing(invoice["customer_id"])


def refresh_pool_loan(loan):
    """Lazy OVERDUE transition for OUT loans past due."""
    if loan["status"] != "OUT":
        return
    if loan["due_at"] is None:
        return
    now = store.now()
    if now > loan["due_at"]:
        loan["status"] = "OVERDUE"
        # recompute overdue fields
        shop_id = loan["_shop_id"]
        shop = store.shops.get(shop_id)
        od, oc = compute_overdue(loan["due_at"], loan.get("returned_at"), now, shop["pool_loan_daily_cents"])
        loan["overdue_days"] = od
        loan["overdue_charge_cents"] = oc
        bump(loan)
        # recompute standing for the customer that owns the contract
        contract = store.pool_contracts.get(loan["contract_id"])
        if contract:
            recompute_standing(contract["customer_id"])


def recompute_standing(customer_id):
    customer = store.customers.get(customer_id)
    if not customer:
        return
    now = store.now()
    invoices = list(store.invoices.values())
    loans = list(store.pool_loans.values())
    contracts = list(store.pool_contracts.values())
    new_standing = compute_standing(customer_id, invoices, loans, contracts, now)
    if customer["standing"] != new_standing:
        customer["standing"] = new_standing
        bump(customer)


def bump(entity):
    """Bump version + updated_at if the entity tracks them."""
    if "version" in entity:
        entity["version"] += 1
    if "updated_at" in entity:
        from db import format_ts
        entity["updated_at"] = format_ts(store.now())
