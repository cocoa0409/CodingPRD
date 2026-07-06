"""Project ledger recomputation and invoice deposit-credit drawdown."""
from db import db
from services.calc import final_deposit


def project_milestones(project_id):
    return [m for m in db.milestones.values() if m["project_id"] == project_id]


def project_invoices(project_id):
    return [iv for iv in db.invoices.values() if iv["project_id"] == project_id]


def project_licenses(project_id):
    return [lc for lc in db.licenses.values() if lc["project_id"] == project_id]


def project_change_orders(project_id):
    return [co for co in db.change_orders.values() if co["project_id"] == project_id]


def recompute_contract_and_final_deposit(project):
    """contract_value_cents = base_scope_cents + sum(delta of APPROVED COs);
    final_deposit_cents = round_half_up(contract_value_cents * deposit_pct).
    (PRD §3.8). Caller is responsible for db.touch on the project."""
    base = project["base_scope_cents"]
    approved_delta = sum(
        co["delta_cents"]
        for co in project_change_orders(project["id"])
        if co["status"] == "APPROVED"
    )
    project["contract_value_cents"] = base + approved_delta
    project["final_deposit_cents"] = final_deposit(
        project["contract_value_cents"], project["deposit_pct"])


def already_credited_deposit(project_id, exclude_invoice_id=None):
    """Sum of deposit_credit_cents over the project's invoices that have already
    consumed deposit. VOID invoices release their credit back (they no longer
    consume it).

    Deposit credit is drawn down across a project's invoices in ascending
    milestone sequence_index order, tie-break created_at ascending (PRD §3.6).
    Because credit is computed at issue time against the deposit already consumed
    by *earlier-sequenced* invoices, and invoices are issued one at a time, the
    running consumed total is simply the sum of deposit_credit_cents on all
    currently non-VOID invoices of the project (excluding the one being issued).
    """
    total = 0
    for iv in project_invoices(project_id):
        if iv["id"] == exclude_invoice_id:
            continue
        if iv["status"] == "VOID":
            continue
        total += iv["deposit_credit_cents"]
    return total
