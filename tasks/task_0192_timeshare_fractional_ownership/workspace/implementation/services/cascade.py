"""Cascading state-change engine: contract status reconciliation, invoice/case
cure, payment allocation and reversal."""
from db import db, touch
from services.calc import late_charge_delta
from services.computed import invoice_amount_due
from services.util import parse_iso, add_days


# ---------------------------------------------------------------------------
# Window helpers
# ---------------------------------------------------------------------------
def grace_elapsed(resort, invoice):
    """True iff current_utc >= due_date + delinquency_grace_days days."""
    current = parse_iso(resort["current_utc"])
    due = parse_iso(invoice["due_date"])
    threshold = add_days(due, resort["delinquency_grace_days"])
    return current >= threshold


# ---------------------------------------------------------------------------
# Contract cascade: suspend (on LIEN), reactivate (on CURE from LIEN),
# terminal foreclose/terminate.
# ---------------------------------------------------------------------------
def suspend_contract(contract):
    """ACTIVE -> SUSPENDED cascade; cancels every HELD reservation on the contract."""
    contract["status"] = "SUSPENDED"
    touch(contract)
    for res in db.reservations.values():
        if res["contract_id"] == contract["id"] and res["status"] == "HELD":
            res["status"] = "CANCELLED"
            touch(res)
            # No committed points at HELD, so no balance changes.


def reactivate_contract(contract):
    """SUSPENDED -> ACTIVE cascade."""
    contract["status"] = "ACTIVE"
    touch(contract)


def writeoff_delinquent_invoices(contract):
    for inv in db.invoices.values():
        if inv["contract_id"] == contract["id"] and inv["status"] == "DELINQUENT":
            inv["status"] = "WRITTEN_OFF"
            touch(inv)


def cancel_nonterminal_reservations(contract):
    """Cancel all non-terminal reservations on the contract, releasing committed points."""
    terminal = {"CANCELLED", "COMPLETED", "EXPIRED"}
    for res in db.reservations.values():
        if res["contract_id"] != contract["id"]:
            continue
        if res["status"] in terminal:
            continue
        was_committed = res["status"] in ("CONFIRMED", "DEPOSITED_TO_EXCHANGE")
        res["status"] = "CANCELLED"
        touch(res)
        # Release committed/borrowed points if the reservation had committed them.
        if was_committed:
            release_reservation_points(res)
            # Release the unit back to AVAILABLE.
            unit = db.inventory_units.get(res["inventory_unit_id"])
            if unit is not None:
                unit["status"] = "AVAILABLE"
                touch(unit)


def release_reservation_points(res):
    """Compensating release of committed/borrowed points for a CONFIRMED reservation."""
    non_borrowed = res["points_cost"] - res["borrowed_points"]
    src = db.points_accounts.get(res["source_use_year_account_id"])
    if src is not None:
        src["committed_points"] -= non_borrowed
        touch(src)
    if res["borrowed_points"] > 0 and res.get("borrow_source_account_id"):
        borrow = db.points_accounts.get(res["borrow_source_account_id"])
        if borrow is not None:
            borrow["borrowed_out_points"] -= res["borrowed_points"]
            touch(borrow)


def foreclose_or_terminate_contract(contract, terminal_status):
    """Drive contract to FORECLOSED or TERMINATED with full cascade."""
    contract["status"] = terminal_status
    touch(contract)
    writeoff_delinquent_invoices(contract)
    cancel_nonterminal_reservations(contract)
    # Release fixed unit for FIXED_WEEK deeded contracts.
    if contract["inventory_model"] == "FIXED_WEEK" and contract.get("fixed_unit_id"):
        unit = db.inventory_units.get(contract["fixed_unit_id"])
        if unit is not None:
            unit["status"] = "AVAILABLE"
            touch(unit)


# ---------------------------------------------------------------------------
# Delinquency-case cure logic (driven by payments / invoice clears)
# ---------------------------------------------------------------------------
def open_delinquency_case_for(contract, trigger_invoice):
    """Open a NOTICE case for the contract if none is open (non-terminal)."""
    open_states = {"NOTICE", "LIEN"}
    for case in db.delinquency_cases.values():
        if case["contract_id"] == contract["id"] and case["status"] in open_states:
            return case  # already open
    from db import stamp_create, new_id

    case = {
        "id": new_id(),
        "contract_id": contract["id"],
        "owner_id": contract["owner_id"],
        "trigger_invoice_id": trigger_invoice["id"],
        "escalation_periods": 0,
        "late_charge_basis": "COMPOUNDING",
        "status": "NOTICE",
    }
    stamp_create(case)
    db.delinquency_cases[case["id"]] = case
    return case


def open_case_for_contract(contract):
    for case in db.delinquency_cases.values():
        if case["contract_id"] == contract["id"] and case["status"] in ("NOTICE", "LIEN"):
            return case
    return None


def contract_has_delinquent_invoice(contract):
    for inv in db.invoices.values():
        if inv["contract_id"] == contract["id"] and inv["status"] == "DELINQUENT":
            return True
    return False


def maybe_cure_case(contract):
    """If the contract has no remaining DELINQUENT invoices, cure its open case.

    Returns (case, prior_status) if a cure happened, else None.
    """
    case = open_case_for_contract(contract)
    if case is None:
        return None
    if contract_has_delinquent_invoice(contract):
        return None
    prior = case["status"]
    case["status"] = "CURED"
    touch(case)
    # A cure out of LIEN reactivates the contract.
    if prior == "LIEN" and contract["status"] == "SUSPENDED":
        reactivate_contract(contract)
    return (case, prior)


# ---------------------------------------------------------------------------
# Invoice paid/revert transitions
# ---------------------------------------------------------------------------
def settle_invoice_status_after_payment(inv):
    """If amount_due reaches 0, transition ISSUED/DELINQUENT -> PAID."""
    if invoice_amount_due(inv) <= 0 and inv["status"] in ("ISSUED", "DELINQUENT"):
        inv["status"] = "PAID"
        touch(inv)


# ---------------------------------------------------------------------------
# Payment clear: allocate amount across invoices
# ---------------------------------------------------------------------------
def allocate_payment(payment, contract, resort):
    """Allocate a clearing payment's amount across invoices.

    Records allocations on the payment as a list of {invoice_id, amount}.
    Cascades PAID and possible CURE. Returns nothing.
    """
    amount = payment["amount_cents"]
    allocations = []

    if payment.get("invoice_id"):
        targets = [db.invoices[payment["invoice_id"]]]
    else:
        candidates = [
            inv
            for inv in db.invoices.values()
            if inv["contract_id"] == contract["id"]
            and inv["status"] in ("ISSUED", "DELINQUENT")
        ]
        # oldest due_date first, then created_at ASC (stable via _seq).
        candidates.sort(key=lambda i: (parse_iso(i["due_date"]), i["_seq"]))
        targets = candidates

    for inv in targets:
        if amount <= 0:
            break
        due = invoice_amount_due(inv)
        if due <= 0:
            continue
        applied = min(amount, due)
        inv["amount_paid_cents"] += applied
        amount -= applied
        touch(inv)
        allocations.append({"invoice_id": inv["id"], "amount": applied})
        settle_invoice_status_after_payment(inv)

    payment["allocations"] = allocations
    # Cure check: if last DELINQUENT invoice cleared.
    cure = maybe_cure_case(contract)
    if cure is not None:
        case, prior = cure
        payment["cured_case_id"] = case["id"]
        payment["cured_case_prior_status"] = prior
    else:
        payment["cured_case_id"] = None
        payment["cured_case_prior_status"] = None


# ---------------------------------------------------------------------------
# Payment reverse: undo allocations
# ---------------------------------------------------------------------------
def reverse_payment(payment, contract, resort):
    """Undo a cleared payment's allocations and re-open any case it cured."""
    for alloc in payment.get("allocations", []):
        inv = db.invoices.get(alloc["invoice_id"])
        if inv is None:
            continue
        inv["amount_paid_cents"] -= alloc["amount"]
        # Revert PAID -> ISSUED (or DELINQUENT if now past grace and has balance).
        if inv["status"] == "PAID" and invoice_amount_due(inv) > 0:
            if grace_elapsed(resort, inv):
                inv["status"] = "DELINQUENT"
            else:
                inv["status"] = "ISSUED"
        touch(inv)

    # Re-open a case cured by this very payment.
    cured_case_id = payment.get("cured_case_id")
    if cured_case_id:
        case = db.delinquency_cases.get(cured_case_id)
        if case is not None and case["status"] == "CURED":
            prior = payment.get("cured_case_prior_status")
            case["status"] = prior
            touch(case)
            if prior == "LIEN" and contract["status"] == "ACTIVE":
                # Re-suspend the contract.
                contract["status"] = "SUSPENDED"
                touch(contract)
    payment["allocations"] = []
    payment["cured_case_id"] = None
    payment["cured_case_prior_status"] = None
