"""Multi-hop cross-entity side effects (PRD sections 3.4 - 3.9).

Every row that actually changes takes its own version increment and its own
updated_at refresh, and every bump lands BEFORE the response is serialised.
"""
import consts as C
import calc
import lookup
import store
from store import D, add_days, money


# --------------------------------------------------------------------------
# property
# --------------------------------------------------------------------------
def property_hop(prop, origin, target):
    if prop is None:
        return False
    if prop.get("prep_state") != origin:
        return False
    prop["prep_state"] = target
    store.touch(prop)
    return True


# --------------------------------------------------------------------------
# lease helpers
# --------------------------------------------------------------------------
def _auto_pickup(project, lease):
    return store.new_row("pickups", {
        "project_id": project["id"],
        "lease_id": lease["id"],
        "scheduled_at": lease.get("pickup_window_start"),
        "state": "SCHEDULED",
        "attempt_count": 0,
        "completed_at": None,
        "assessed_line_count": 0,
        "damage_total": money(0),
    })


def begin_destage(project, lease):
    """Lease ACTIVE/EXTENDED -> ENDING, project STAGED -> DESTAGE_PENDING and the
    auto-created pickup at the freshly derived pickup_window_start."""
    moved = False
    if lease is not None and lease.get("state") in ("ACTIVE", "EXTENDED"):
        lease["state"] = "ENDING"
        calc.derive_pickup_window(lease)
        store.touch(lease)
        moved = True
    if project.get("workflow_state") == "STAGED" and project["pipeline"] == "VACANT_STAGING":
        project["workflow_state"] = "DESTAGE_PENDING"
        project["destage_eligible"] = True
        store.touch(project)
    if moved:
        _auto_pickup(project, lease)
    return moved


# --------------------------------------------------------------------------
# listing lifecycle
# --------------------------------------------------------------------------
def listing_under_contract(listing):
    listing["under_contract_at"] = store.now()
    for project in store.where("projects", listing_id=listing["id"]):
        if project["workflow_state"] != "STAGED" or project["pipeline"] != "VACANT_STAGING":
            continue
        project["workflow_state"] = "DESTAGE_PENDING"         # hop 1
        project["destage_eligible"] = True
        store.touch(project)
        lease = lookup.active_lease(project)
        if lease is not None and lease["state"] in ("ACTIVE", "EXTENDED"):
            lease["state"] = "ENDING"                          # hop 2
            calc.derive_pickup_window(lease)
            store.touch(lease)
            _auto_pickup(project, lease)                       # hop 3
    store.touch(listing)


def listing_fall_out(listing):
    listing["fallout_count"] = int(listing.get("fallout_count") or 0) + 1
    for project in store.where("projects", listing_id=listing["id"]):
        if project["workflow_state"] == "DESTAGE_PENDING":     # hop 1
            project["workflow_state"] = "RESTAGE_REQUIRED"
            project["restage_count"] = int(project.get("restage_count") or 0) + 1
            project["destage_eligible"] = False
            store.touch(project)
        for pickup in lookup.project_pickups(project):         # hop 2
            if pickup["state"] == "SCHEDULED":
                pickup["state"] = "CANCELLED"
                store.touch(pickup)
        lease = lookup.active_lease(project)                   # hop 3
        if lease is not None and lease["state"] == "ENDING":
            lease["state"] = "ACTIVE"
            lease["pickup_window_start"] = None
            lease["pickup_window_end"] = None
            store.touch(lease)
        restage_availability_recheck(project)                  # hop 4
    store.touch(listing)


def restage_availability_recheck(project):
    pull = lookup.active_pull(project)
    if pull is None:
        return
    changed = False
    for line in lookup.pull_lines(pull):
        if line["state"] != "DEPLOYED":
            continue
        item = store.get("items", line.get("inventory_item_id"))
        if line["source"] == "OWNED" and (item is None or item["status"] != "DEPLOYED"):
            line["state"] = "UNFILLED"
            store.touch(line)
            changed = True
    calc.recompute_pull(pull)
    if pull["fill_rate"] < D("1.0000") and pull["state"] == "COMMITTED":
        pull["state"] = "PARTIAL"
        changed = True
    if changed:
        store.touch(pull)


def listing_close(listing):
    listing["closed_at"] = store.now()
    for project in store.where("projects", listing_id=listing["id"]):
        for invoice in store.where("invoices", project_id=project["id"]):
            if invoice["state"] != "DEFERRED_CLOSING":
                continue
            invoice["state"] = "ISSUED"
            invoice["due_date"] = add_days(listing["closed_at"], C.INVOICE_DUE_DAYS)
            calc.refresh_invoice(invoice)
            store.touch(invoice)
            if project.get("payment_state") == "DEFERRED":
                project["payment_state"] = "INVOICED"
                project["fiscal_hold"] = False
                store.touch(project)
    store.touch(listing)


def listing_terminate(listing):
    for project in store.where("projects", listing_id=listing["id"]):
        escalated = False
        for invoice in store.where("invoices", project_id=project["id"]):
            if invoice["state"] != "DEFERRED_CLOSING":
                continue
            invoice["state"] = "ESCALATED"
            project["closing_escalation_booked"] = money(
                D(project.get("closing_escalation_booked") or 0) + C.CLOSING_ESCALATION_FEE)
            calc.refresh_invoice(invoice)
            store.touch(invoice)
            escalated = True
        if escalated:
            project["payment_state"] = "ESCALATED"
            project["fiscal_hold"] = True
            store.touch(project)
    store.touch(listing)


# --------------------------------------------------------------------------
# install completion
# --------------------------------------------------------------------------
def install_complete(install, project):
    install["completed_at"] = store.now()
    install["state"] = "COMPLETE"

    lease = lookup.active_lease(project)
    if lease is not None and lease["state"] == "PENDING":
        lease["state"] = "ACTIVE"                                  # hop 1
        lease["start_date"] = install["completed_at"]
        lease["billed_cycles"] = int(lease["initial_cycles"])
        lease["end_date"] = calc.lease_end_date(lease)              # hop 2
        calc.derive_pickup_window(lease)

    pull = lookup.active_pull(project)
    for line in lookup.pull_lines(pull):                            # hop 3
        if line["state"] != "ALLOCATED":
            continue
        line["state"] = "DEPLOYED"
        store.touch(line)
        item = store.get("items", line.get("inventory_item_id"))
        if item is not None and item["status"] == "RESERVED":
            item["status"] = "DEPLOYED"
            item["times_deployed"] = int(item.get("times_deployed") or 0) + 1
            store.touch(item)

    for order in lookup.project_orders(project):
        if order["state"] == "CONFIRMED":
            order["state"] = "DELIVERED"
            store.touch(order)

    if lease is not None and lease["state"] == "ACTIVE":
        lease["monthly_rent"] = calc.lease_monthly_rent(lease)
        store.touch(lease)

    if project["workflow_state"] == "INSTALL_SCHEDULED":
        project["workflow_state"] = "STAGED"
        store.touch(project)
    property_hop(lookup.property_of(project), "IN_PREP", "STAGED")
    store.touch(install)


# --------------------------------------------------------------------------
# invoice materialisation / deposit
# --------------------------------------------------------------------------
def materialise_invoice(project):
    invoice = lookup.project_invoice(project)
    if invoice is None:
        invoice = store.new_row("invoices", {
            "project_id": project["id"],
            "state": "DRAFT",
            "subtotal": money(0),
            "tax_amount": money(0),
            "deposit_applied": money(0),
            "interest_accrued": money(0),
            "total_due": money(0),
            "issued_at": None,
            "due_date": None,
            "paid_at": None,
            "line_summary": {},
        })
    calc.refresh_invoice(invoice)
    return invoice


def run_waterfall(project, deposit, invoice):
    before = D(deposit.get("held_remaining") or 0)
    calc.deposit_waterfall(deposit, project, invoice)
    if D(deposit["held_remaining"]) <= 0:
        deposit["state"] = "APPLIED"
        deposit["invoice_id"] = invoice["id"]
    else:
        deposit["state"] = "PARTIALLY_APPLIED"
    store.touch(deposit)
    calc.refresh_invoice(invoice)
    return before


def forfeit_deposit(project):
    deposit = lookup.project_deposit(project)
    if deposit is None or deposit["state"] not in ("HELD", "PARTIALLY_APPLIED"):
        return
    deposit["forfeited_amount"] = money(D(deposit.get("forfeited_amount") or 0)
                                        + D(deposit.get("held_remaining") or 0))
    deposit["held_remaining"] = money(0)
    deposit["state"] = "FORFEITED"
    store.touch(deposit)


# --------------------------------------------------------------------------
# pickup completion - the seven hop closeout cascade
# --------------------------------------------------------------------------
def pickup_complete(pickup, project):
    pickup["completed_at"] = store.now()
    pickup["state"] = "COMPLETED"

    pull = lookup.active_pull(project)
    if pull is not None and pull["state"] == "COMMITTED":            # hop 1
        pull["state"] = "RELEASED"
        store.touch(pull)

    lines = lookup.pull_lines(pull)
    for line in lines:                                               # hop 2
        if line["state"] == "DEPLOYED":
            line["state"] = "RETURNED"
            store.touch(line)
            item = store.get("items", line.get("inventory_item_id"))  # hop 3
            if item is not None and item["status"] == "DEPLOYED":
                item["status"] = "AVAILABLE"
                store.touch(item)

    for order in lookup.project_orders(project):
        if order["state"] == "DELIVERED":
            order["state"] = "RETURNED"
            store.touch(order)

    lease = lookup.active_lease(project)                             # hop 4
    if lease is not None and lease["state"] in ("ENDING", "HOLDOVER"):
        lease["state"] = "ENDED"
        store.touch(lease)

    invoice = materialise_invoice(project)                           # hop 5

    deposit = lookup.project_deposit(project)                        # hop 6
    if deposit is not None and deposit["state"] in ("HELD", "PARTIALLY_APPLIED"):
        run_waterfall(project, deposit, invoice)

    if project["workflow_state"] == "DESTAGE_PENDING":               # hop 7
        project["workflow_state"] = "PICKED_UP"
        store.touch(project)
    property_hop(lookup.property_of(project), "STAGED", "DESTAGED")
    store.touch(pickup)
