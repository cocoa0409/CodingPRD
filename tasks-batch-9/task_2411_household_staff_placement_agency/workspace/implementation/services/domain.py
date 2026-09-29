"""Shared domain services: lookups, derived-field recomputation, the ledger
fold, and the multi-hop cascades.

Consistency is immediate: by the time a mutating call returns, every derived
figure it can reach has already been recomputed and every touched row has had
its version incremented.
"""

import db
from db import (
    ACTIVE_TRIAL_STATUSES,
    COOLING_OFF_DAYS,
    COUNTED_PLACEMENT_STATUSES,
    CREDIT_HOLD_LIMIT_CENTS,
    MILESTONE_SEQUENCE,
    MILESTONE_WEIGHTS_BPS,
    NON_SOLICITATION_TERM_DAYS,
    serialize,
    sort_rows,
    stamp_ledger,
    stamp_new,
    store,
    touch,
)
from errors import fail
from services import calc
from timeutil import add_days, format_date, parse_date

# ---------------------------------------------------------------------------
# Path / body reference resolution (PRD 2.5)
# ---------------------------------------------------------------------------
_NOT_FOUND = {
    "clients": "ERR_CLIENT_NOT_FOUND",
    "fee_schedules": "ERR_FEE_SCHEDULE_NOT_FOUND",
    "requisitions": "ERR_REQUISITION_NOT_FOUND",
    "candidates": "ERR_CANDIDATE_NOT_FOUND",
    "reference_checks": "ERR_REFERENCE_CHECK_NOT_FOUND",
    "background_verifications": "ERR_BACKGROUND_VERIFICATION_NOT_FOUND",
    "trial_engagements": "ERR_TRIAL_NOT_FOUND",
    "accommodation_terms": "ERR_ACCOMMODATION_TERM_NOT_FOUND",
    "placements": "ERR_PLACEMENT_NOT_FOUND",
    "fee_milestones": "ERR_FEE_MILESTONE_NOT_FOUND",
    "replacement_claims": "ERR_REPLACEMENT_CLAIM_NOT_FOUND",
    "payroll_handoffs": "ERR_PAYROLL_HANDOFF_NOT_FOUND",
    "non_solicitation_cases": "ERR_NON_SOLICITATION_CASE_NOT_FOUND",
}


def resolve(collection, row_id):
    table = getattr(store, collection)
    row = table.get(row_id) if isinstance(row_id, str) else None
    if row is None:
        fail(_NOT_FOUND[collection])
    return row


def resolve_optional(collection, row_id):
    if row_id is None:
        return None
    return resolve(collection, row_id)


# ---------------------------------------------------------------------------
# Child collections
# ---------------------------------------------------------------------------
def children(collection, field, value):
    return [r for r in getattr(store, collection).values() if r.get(field) == value]


def references_of(candidate_id):
    return children("reference_checks", "candidate_id", candidate_id)


def backgrounds_of(candidate_id):
    return children("background_verifications", "candidate_id", candidate_id)


def milestones_of(placement_id):
    return children("fee_milestones", "placement_id", placement_id)


def claims_of(placement_id):
    return children("replacement_claims", "placement_id", placement_id)


def handoffs_of(placement_id):
    return children("payroll_handoffs", "placement_id", placement_id)


def ledger_of(client_id):
    return children("ledger_entries", "client_id", client_id)


# ---------------------------------------------------------------------------
# Terminal-state guards (PRD 2.9)
# ---------------------------------------------------------------------------
def guard_terminal(current_state, terminal_states):
    if current_state in terminal_states:
        fail("ERR_ENTITY_TERMINAL")


# ---------------------------------------------------------------------------
# Household derived figures (PRD 3.1)
# ---------------------------------------------------------------------------
def recompute_client_derived(client):
    """placement_count and non_solicitation_expires_on are maintained
    continuously; the household row is touched only when a figure moves."""
    placements = children("placements", "client_id", client["id"])
    count = len([p for p in placements if p["placement_status"] in COUNTED_PLACEMENT_STATUSES])

    expires_on = None
    if count > 0:
        start_dates = [
            parse_date(p["start_date"]) for p in placements if p["placement_status"] != "VOIDED"
        ]
        start_dates = [d for d in start_dates if d is not None]
        if start_dates:
            expires_on = format_date(add_days(max(start_dates), NON_SOLICITATION_TERM_DAYS))

    if client["placement_count"] != count or client["non_solicitation_expires_on"] != expires_on:
        client["placement_count"] = count
        client["non_solicitation_expires_on"] = expires_on
        touch(client)


def recompute_client_balance(client):
    balance = calc.fold_balance(ledger_of(client["id"]))
    if client["outstanding_balance_cents"] != balance:
        client["outstanding_balance_cents"] = balance
        touch(client)


def guard_credit_hold(client):
    """The hold engages only when the balance is strictly greater than the
    limit; a balance of exactly the limit still transacts."""
    if client["outstanding_balance_cents"] > CREDIT_HOLD_LIMIT_CENTS:
        fail("ERR_CLIENT_CREDIT_HOLD")


def guard_client_not_suspended(client):
    if client["status"] == "SUSPENDED":
        fail("ERR_CLIENT_SUSPENDED")


def guard_nda_countersigned(client):
    if client["confidentiality_agreement_status"] != "COUNTERSIGNED":
        fail("ERR_NDA_NOT_COUNTERSIGNED")


# ---------------------------------------------------------------------------
# Ledger append (PRD 3.7)
# ---------------------------------------------------------------------------
POSITIVE_ENTRY_TYPES = {"FEE_INVOICED", "PENALTY_ASSESSED"}
NEGATIVE_ENTRY_TYPES = {"FEE_PAYMENT", "FEE_REVERSAL", "REFUND_ISSUED", "PENALTY_SETTLED"}


def append_ledger_entry(client, entry_type, signed_amount_cents, memo,
                        related_ref_type="NONE", related_ref_id=None):
    existing = ledger_of(client["id"])
    sequence_no = len(existing) + 1
    balance_after = calc.fold_balance(existing) + signed_amount_cents
    row = {
        "client_id": client["id"],
        "sequence_no": sequence_no,
        "entry_type": entry_type,
        "signed_amount_cents": signed_amount_cents,
        "related_ref_type": related_ref_type,
        "related_ref_id": related_ref_id,
        "memo": memo,
        "balance_after_cents": balance_after,
    }
    stamp_ledger(row)
    store.ledger_entries[row["id"]] = row
    return row


# ---------------------------------------------------------------------------
# Candidate derived figures (PRD 3.3)
# ---------------------------------------------------------------------------
def recompute_candidate(candidate):
    figures = calc.vetting_figures(
        candidate, references_of(candidate["id"]), backgrounds_of(candidate["id"])
    )
    changed = False
    for key, value in figures.items():
        if candidate[key] != value:
            candidate[key] = value
            changed = True
    if changed:
        touch(candidate)
    return figures


def chain_requirement(role_type):
    if role_type in db.SENIOR_ROLE_TYPES:
        return db.MIN_CHAIN_MONTHS_SENIOR
    return db.MIN_CHAIN_MONTHS_STANDARD


# ---------------------------------------------------------------------------
# Requisition derived figures (PRD 3.1)
# ---------------------------------------------------------------------------
def recompute_active_trial_count(requisition):
    trials = children("trial_engagements", "requisition_id", requisition["id"])
    count = len([t for t in trials if t["status"] in ACTIVE_TRIAL_STATUSES])
    if requisition["active_trial_count"] != count:
        requisition["active_trial_count"] = count
        touch(requisition)
    return count


def requisition_has_pending_acceptance(requisition):
    return any(
        p["placement_status"] == "PENDING_ACCEPTANCE"
        for p in children("placements", "requisition_id", requisition["id"])
    )


def fallback_trialing_to_sourcing(requisition):
    """System transition TRIALING -> SOURCING: the last non-terminal trial has
    left the active set through a failed outcome or a cancellation and no
    placement is awaiting acceptance."""
    count = recompute_active_trial_count(requisition)
    if (
        requisition["status"] == "TRIALING"
        and count == 0
        and not requisition_has_pending_acceptance(requisition)
    ):
        requisition["status"] = "SOURCING"
        touch(requisition)


def fallback_offer_pending_to_sourcing(requisition):
    """System transition OFFER_PENDING -> SOURCING once no placement of the
    requisition remains in PENDING_ACCEPTANCE or ACTIVE."""
    placements = children("placements", "requisition_id", requisition["id"])
    if any(p["placement_status"] in ("PENDING_ACCEPTANCE", "ACTIVE") for p in placements):
        return
    if requisition["status"] == "OFFER_PENDING":
        requisition["status"] = "SOURCING"
        touch(requisition)


# ---------------------------------------------------------------------------
# Candidate availability restoration after a trial leaves the active set
# ---------------------------------------------------------------------------
def restore_candidate_after_trial(candidate):
    """ON_TRIAL -> AVAILABLE, admissible only when the candidate holds no other
    active trial and the vetting axis has not been rejected."""
    if candidate["availability_status"] != "ON_TRIAL":
        return
    if candidate["vetting_status"] == "REJECTED":
        return
    others = [
        t for t in children("trial_engagements", "candidate_id", candidate["id"])
        if t["status"] in ACTIVE_TRIAL_STATUSES
    ]
    if others:
        return
    candidate["availability_status"] = "AVAILABLE"
    touch(candidate)


def cancel_trial(trial, reason, note=None, restore_candidate=True):
    # PRD §3.4: cancellation takes the engagement "to `CANCELLED` with the
    # supplied reason stamped" — `outcome_note` belongs to the record-outcome
    # path and stays null on a cancelled row.
    trial["status"] = "CANCELLED"
    trial["cancel_reason"] = reason
    touch(trial)
    candidate = store.candidates.get(trial["candidate_id"])
    if restore_candidate and candidate is not None:
        restore_candidate_after_trial(candidate)


def start_cooling_off(candidate):
    """PLACED -> COOLING_OFF with the cooling-off date set thirty days out."""
    if candidate["availability_status"] != "PLACED":
        return
    candidate["availability_status"] = "COOLING_OFF"
    candidate["cooling_off_until"] = format_date(add_days(store.today(), COOLING_OFF_DAYS))
    touch(candidate)


# ---------------------------------------------------------------------------
# Fee milestones (PRD 3.7)
# ---------------------------------------------------------------------------
def create_milestones(placement):
    rows = []
    for index, milestone_type in enumerate(MILESTONE_SEQUENCE, start=1):
        row = {
            "placement_id": placement["id"],
            "sequence_no": index,
            "milestone_type": milestone_type,
            "weight_bps": MILESTONE_WEIGHTS_BPS[milestone_type],
            "amount_cents": 0,
            "invoice_status": "PENDING",
            "invoiced_on": None,
            "due_date": None,
            "paid_on": None,
            "payment_reference": None,
            "invoiced_by_user_id": None,
        }
        stamp_new(row)
        store.fee_milestones[row["id"]] = row
        rows.append(row)
    reallocate_milestones(placement, rows, touch_rows=False)
    return rows


def reallocate_milestones(placement, rows=None, touch_rows=True):
    rows = rows if rows is not None else milestones_of(placement["id"])
    assigned = calc.allocate_milestones(placement["fee_cents"], rows)
    for row in rows:
        if row["id"] in assigned and row["amount_cents"] != assigned[row["id"]]:
            row["amount_cents"] = assigned[row["id"]]
            if touch_rows:
                touch(row)


def recompute_billing_status(placement):
    rows = [m for m in milestones_of(placement["id"])]
    statuses = [m["invoice_status"] for m in rows]
    current = placement["billing_status"]
    new_status = current
    if current == "UNBILLED":
        if any(s in ("INVOICED", "OVERDUE", "PAID") for s in statuses) and "PENDING" in statuses:
            new_status = "PARTIALLY_BILLED"
    elif current == "PARTIALLY_BILLED":
        if "PENDING" not in statuses and "PAID" in statuses:
            new_status = "FULLY_BILLED"
        elif not any(s in ("INVOICED", "OVERDUE", "PAID") for s in statuses) and "REVERSED" in statuses:
            new_status = "REVERSED"
    if new_status != current:
        placement["billing_status"] = new_status
        touch(placement)


# ---------------------------------------------------------------------------
# Placement void cascade (PRD 3.6)
# ---------------------------------------------------------------------------
def void_placement(placement, void_reason, client, requisition,
                   restore_candidate=True, requisition_fallback=True):
    """Four hops: void the placement, unwind its milestones, mirror every
    reversal into the ledger, then recompute the household balance."""
    placement["placement_status"] = "VOIDED"
    placement["void_reason"] = void_reason
    touch(placement)

    reversed_any = False
    for milestone in db.sort_by_sequence(milestones_of(placement["id"])):
        status = milestone["invoice_status"]
        if status == "PENDING":
            milestone["invoice_status"] = "VOIDED"
            touch(milestone)
        elif status in ("INVOICED", "OVERDUE"):
            milestone["invoice_status"] = "REVERSED"
            touch(milestone)
            reversed_any = True
            append_ledger_entry(
                client,
                "FEE_REVERSAL",
                -milestone["amount_cents"],
                "Fee reversal for voided placement milestone %s" % milestone["milestone_type"],
                related_ref_type="FEE_MILESTONE",
                related_ref_id=milestone["id"],
            )

    if reversed_any and placement["billing_status"] != "REVERSED":
        placement["billing_status"] = "REVERSED"
        touch(placement)

    recompute_client_balance(client)
    recompute_client_derived(client)

    candidate = store.candidates.get(placement["candidate_id"])
    if restore_candidate and candidate is not None and candidate["availability_status"] == "OFFER_HELD":
        candidate["availability_status"] = "AVAILABLE"
        touch(candidate)

    if requisition_fallback and requisition is not None:
        fallback_offer_pending_to_sourcing(requisition)


# ---------------------------------------------------------------------------
# Household suspension cascade (PRD 3.9)
# ---------------------------------------------------------------------------
def suspend_client_cascade(client):
    if client["status"] == "ONBOARDED":
        client["status"] = "SUSPENDED"
        touch(client)
    affected = set()
    for trial in children("trial_engagements", "client_id", client["id"]):
        if trial["status"] == "SCHEDULED":
            cancel_trial(trial, "CLIENT_SUSPENDED")
            affected.add(trial["requisition_id"])
    for requisition_id in affected:
        requisition = store.requisitions.get(requisition_id)
        if requisition is not None:
            fallback_trialing_to_sourcing(requisition)


# ---------------------------------------------------------------------------
# Ops sweep on clock advance (PRD 2.6)
# ---------------------------------------------------------------------------
def run_ops_sweep():
    today = store.today()
    milestones_marked_overdue = 0
    for milestone in db.sort_rows(list(store.fee_milestones.values())):
        if milestone["invoice_status"] != "INVOICED":
            continue
        due = parse_date(milestone["due_date"]) if milestone["due_date"] else None
        if due is not None and due < today:
            milestone["invoice_status"] = "OVERDUE"
            touch(milestone)
            milestones_marked_overdue += 1

    placements_guarantee_expired = 0
    for placement in db.sort_rows(list(store.placements.values())):
        if placement["placement_status"] != "ACTIVE":
            continue
        expires = parse_date(placement["guarantee_expires_on"]) if placement["guarantee_expires_on"] else None
        if expires is not None and expires <= today:
            placement["placement_status"] = "GUARANTEE_EXPIRED"
            touch(placement)
            placements_guarantee_expired += 1

    return milestones_marked_overdue, placements_guarantee_expired


# ---------------------------------------------------------------------------
# Listing helper
# ---------------------------------------------------------------------------
def page(rows, limit, offset, ordered=None):
    ordered_rows = ordered if ordered is not None else sort_rows(rows)
    total = len(ordered_rows)
    window = ordered_rows[offset:offset + limit]
    return [serialize(r) for r in window], total
