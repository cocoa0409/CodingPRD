"""Business logic: state machines, cascades, ledger, helpers.

Validation ordering (PRD §2.6): auth -> authz -> path existence ->
body FK existence -> payload shape -> state -> business rules. Route handlers
call into these functions after auth/authz/path checks.
"""
import calculations as calc
import constants as C
from clock import clock
from db import db, new_primary, touch
from errors import err
from validate import parse_iso


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------

def get_or_404(collection, rid):
    rec = collection.get(rid)
    if rec is None:
        raise err("ERR_NOT_FOUND", "Resource %s not found" % rid)
    return rec


def fk_or_404(collection, rid):
    """Body foreign-key existence check (ERR_FK_NOT_FOUND)."""
    rec = collection.get(rid)
    if rec is None:
        raise err("ERR_FK_NOT_FOUND", "Referenced resource %s not found" % rid)
    return rec


# ---------------------------------------------------------------------------
# Account ledger (apply_invoice; PRD §2.8, §3.10)
# ---------------------------------------------------------------------------

def ledger_debit(account, amount_cents):
    """On issue: applied = min(amount, balance_before); balance -= applied,
    floored at 0. Returns the applied amount (recorded for exact reversal)."""
    before = account["credit_balance_cents"]
    applied = min(amount_cents, before)
    account["credit_balance_cents"] = before - applied
    return applied


def ledger_credit(account, applied):
    account["credit_balance_cents"] = account["credit_balance_cents"] + applied


# ---------------------------------------------------------------------------
# Standing recomputation helpers (PRD §3.10)
# ---------------------------------------------------------------------------

def _has_other_past_due(account_id, exclude_invoice_id):
    for inv in db.invoices.values():
        if inv["id"] == exclude_invoice_id:
            continue
        if inv["account_id"] != account_id:
            continue
        if inv["status"] == "PAST_DUE":
            return True
    return False


# ---------------------------------------------------------------------------
# Invoice creation (shared by direct issue and cascades)
# ---------------------------------------------------------------------------

def create_invoice_record(account, *, contract_id, supersedes_invoice_id,
                          invoice_kind, period_start, period_end, amount_cents,
                          due_offset_days):
    inv = new_primary({
        "account_id": account["id"],
        "contract_id": contract_id,
        "supersedes_invoice_id": supersedes_invoice_id,
        "invoice_kind": invoice_kind,
        "period_start": period_start,
        "period_end": period_end,
        "amount_cents": amount_cents,
        "status": "OPEN",
        "due_offset_days": due_offset_days,
    })
    # debit ledger via apply_invoice; record applied amount for exact reversal
    applied = ledger_debit(account, amount_cents)
    inv["_applied_amount"] = applied
    touch(account)
    db.invoices[inv["id"]] = inv
    return inv


# ---------------------------------------------------------------------------
# ServiceVisit creation (shared by cascades)
# ---------------------------------------------------------------------------

def create_service_visit(system_id, *, stop_id, visit_type, gallons_treated_reading,
                         billable_cents):
    visit = new_primary({
        "system_id": system_id,
        "stop_id": stop_id,
        "visit_type": visit_type,
        "gallons_treated_reading": gallons_treated_reading,
        "status": "LOGGED",
        "billable_cents": billable_cents,
    })
    db.service_visits[visit["id"]] = visit
    return visit


# ---------------------------------------------------------------------------
# Regeneration helpers
# ---------------------------------------------------------------------------

def recompute_regen_health(system):
    account = db.accounts.get(system["account_id"])
    hardness = account["hardness_gpg"] if account else None
    cap = calc.capacity_gallons(system["grain_capacity"], hardness)
    system["regen_health"] = calc.regen_health_for(system["gallons_since_regen"], cap)


def parse_period(value, name):
    return parse_iso(value, name)
