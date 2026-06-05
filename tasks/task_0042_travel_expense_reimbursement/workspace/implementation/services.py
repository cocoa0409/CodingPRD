"""Cross-entity service logic: lookups, ledger recomputation, line reimbursable.

These helpers do NOT bump versions on their own except where the PRD requires a
cascade to mutate a resource; callers decide when a version bump is warranted.
"""
import calc
from db import store, touch
from errors import err


# -------------------------------------------------------------------------
# Lookups (raise ERR_NOT_FOUND when absent)
# -------------------------------------------------------------------------

def get_or_404(collection, entity_id):
    ent = collection.get(entity_id)
    if ent is None:
        raise err("ERR_NOT_FOUND", "Resource not found")
    return ent


def active_policy():
    for p in store.travel_policies.values():
        if p["status"] == "ACTIVE":
            return p
    return None


def perdiem_for_state(state_code):
    """Return the PerDiemRate for a state_code, or None."""
    for r in store.per_diem_rates.values():
        if r["state_code"] == state_code:
            return r
    return None


# -------------------------------------------------------------------------
# Line reimbursable computation
# -------------------------------------------------------------------------

def compute_line_reimbursable(line, report, trip, policy):
    """Compute (reimbursable_amount_cents, in_policy) for a line by type."""
    lt = line["line_type"]
    claimed = line["claimed_amount_cents"]
    if lt == "FLIGHT":
        return calc.flight_line(
            claimed, line.get("cabin_class"),
            line.get("scheduled_hours"), line.get("advance_days"), policy,
        )
    if lt == "RENTAL_CDW":
        return calc.cdw_line(claimed, line.get("rental_days"), policy)
    if lt == "MILEAGE":
        return calc.mileage_line(line.get("miles"), policy)
    if lt == "LODGING":
        pd = perdiem_for_state(trip["destination_state"])
        # destination perdiem is required for lodging caps
        lodging_cap = pd["lodging_cap_cents"] if pd else 0
        return calc.lodging_line(
            claimed, line.get("check_in_date"), line.get("check_out_date"), lodging_cap,
        )
    if lt == "MEAL":
        # MEAL lines have no per-line reimbursable; computed at report level.
        return 0, True
    return 0, True


# -------------------------------------------------------------------------
# Card ledger recomputation
# -------------------------------------------------------------------------

def card_lines(card_id):
    return [l for l in store.expense_lines.values() if l.get("virtual_card_id") == card_id]


def recompute_card(card, bump=False):
    """Recompute a card's authorized_holds/captured_total/available_balance.

    authorized_holds = sum reimbursable of charged lines with settlement PENDING
    captured_total   = sum reimbursable of charged lines with settlement SETTLED
    available        = load_limit - holds - captured
    """
    holds = 0
    captured = 0
    for l in card_lines(card["id"]):
        if l["settlement_status"] == "PENDING":
            holds += l["reimbursable_amount_cents"]
        elif l["settlement_status"] == "SETTLED":
            captured += l["reimbursable_amount_cents"]
    card["authorized_holds_cents"] = holds
    card["captured_total_cents"] = captured
    card["available_balance_cents"] = card["load_limit_cents"] - holds - captured
    if bump:
        touch(card)


# -------------------------------------------------------------------------
# Trip budget ledger recomputation
# -------------------------------------------------------------------------

def recompute_trip_ledger(trip, bump=False):
    """committed = sum total_reimbursable of APPROVED reports on this trip;
    remaining = budget_total - committed."""
    committed = 0
    for r in store.expense_reports.values():
        if r["trip_request_id"] == trip["id"] and r["status"] == "APPROVED":
            committed += r["total_reimbursable_cents"]
    trip["committed_amount_cents"] = committed
    trip["remaining_budget_cents"] = trip["budget_total_cents"] - committed
    if bump:
        touch(trip)


# -------------------------------------------------------------------------
# Report meal + total recomputation
# -------------------------------------------------------------------------

def report_lines(report_id):
    return [l for l in store.expense_lines.values() if l["report_id"] == report_id]


def recompute_report_totals(report, trip):
    """Recompute meal_reimbursable_cents then total_reimbursable_cents (pinned order)."""
    lines = report_lines(report["id"])
    meal_lines = [l for l in lines if l["line_type"] == "MEAL"]
    pd = perdiem_for_state(trip["destination_state"])
    mie = pd["mie_cents"] if pd else 0
    meal_amt = calc.meal_reimbursable(report, trip, meal_lines, mie)
    report["meal_reimbursable_cents"] = meal_amt
    report["total_reimbursable_cents"] = calc.report_total(meal_amt, lines)
