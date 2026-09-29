"""Fiscal ledger moves, Cascade A, Cascade B, seat release and clock lapse."""
from calc import (
    CONTRACT_ACTIVATION_GRACE_DAYS,
    HIGH_COST_TRIGGER_CENTS,
    high_cost_amounts,
    placement_fiscal_year,
    recompute_placement_encumbrance,
    transport_encumbrance,
    waitlist_candidate,
)
from store import (
    add_days,
    db,
    new_row,
    now_iso,
    ordered,
    parse_date,
    reset_touch,
    touch,
)


# --------------------------------------------------------------------------
# fiscal ledger primitives (2.6 conservation: authorized = available +
# encumbered + disbursed, always)
# --------------------------------------------------------------------------

def book_encumbrance(account, amount):
    account["available_cents"] -= amount
    account["encumbered_cents"] += amount
    touch(account)


def release_encumbrance(account, amount):
    account["encumbered_cents"] -= amount
    account["available_cents"] += amount
    touch(account)


def settle_encumbrance(account, amount):
    account["encumbered_cents"] -= amount
    account["disbursed_cents"] += amount
    touch(account)


def disburse_direct(account, amount):
    account["available_cents"] -= amount
    account["disbursed_cents"] += amount
    touch(account)


def reverse_direct(account, amount):
    account["disbursed_cents"] -= amount
    account["available_cents"] += amount
    touch(account)


def account_of(placement):
    return db.accounts.get(placement.get("fiscal_account_id"))


def student_of_placement(placement):
    return db.students.get(placement.get("student_id"))


# --------------------------------------------------------------------------
# transport seat release + promotion (3.4, Cascade A links 5-7)
# --------------------------------------------------------------------------

def promote_from_waitlist(route, account):
    """Runs the pinned promotion selector for exactly one freed seat."""
    winner = waitlist_candidate(route["id"])
    if winner is None:
        return None
    commitment = transport_encumbrance(winner, route)
    target = db.placements.get(winner["placement_id"])
    winner["status"] = "ACTIVE"
    winner["encumbrance_cents"] = commitment
    winner["promoted_at"] = now_iso()
    touch(winner)
    route["seats_committed"] += 1
    route["seats_available"] = route["seat_capacity"] - route["seats_committed"]
    touch(route)
    if target is not None:
        target["transport_encumbrance_cents"] += commitment
        target["transport_status"] = "ASSIGNED"
        recompute_placement_encumbrance(target)
        touch(target)
        target_account = account_of(target)
        if target_account is not None:
            book_encumbrance(target_account, commitment)
    return winner


def unwind_active_assignment(assignment, placement, account):
    """Route seat + money unwind for an assignment released from ACTIVE."""
    route = db.routes.get(assignment["route_id"])
    amount = assignment["encumbrance_cents"]
    if route is not None:
        route["seats_committed"] -= 1
        route["seats_available"] = route["seat_capacity"] - route["seats_committed"]
        touch(route)
    if account is not None and amount:
        release_encumbrance(account, amount)
    placement["transport_encumbrance_cents"] -= amount
    placement["released_encumbrance_cents"] += amount
    assignment["encumbrance_cents"] = 0
    return route


# --------------------------------------------------------------------------
# contract commitment release (Cascade A link 1, also used by lapse)
# --------------------------------------------------------------------------

def release_contract_commitment(placement, account):
    release = placement["contract_encumbrance_cents"] - placement["paid_total_ytd_cents"]
    if account is not None and release:
        release_encumbrance(account, release)
    elif account is not None:
        touch(account)
    placement["contract_encumbrance_cents"] = placement["paid_total_ytd_cents"]
    placement["released_encumbrance_cents"] += release
    return release


# --------------------------------------------------------------------------
# Cascade A (termination) and its return-to-district sibling
# --------------------------------------------------------------------------

def close_placement(placement, mode, reason, receiving_lre_setting=None):
    """mode is TERMINATE or RETURN. Ten links, applied in order."""
    account = account_of(placement)
    student = student_of_placement(placement)

    # Link 0 - the placement and its student
    placement["status"] = "TERMINATED" if mode == "TERMINATE" else "RETURNED_TO_DISTRICT"
    placement["terminated_at"] = now_iso()
    placement["termination_reason"] = reason
    if student is not None:
        student["placement_status"] = "TERMINATED" if mode == "TERMINATE" else "RETURNED"
        if mode == "RETURN" and receiving_lre_setting is not None:
            student["lre_current_setting"] = receiving_lre_setting
        touch(student)

    # Link 1 - placement to fiscal account
    release_contract_commitment(placement, account)

    # Link 2 / 3 - service addenda and their releases
    terminal_addendum_state = "TERMINATED" if mode == "TERMINATE" else "TRANSFERRED"
    for addendum in ordered([a for a in db.addenda.values()
                             if a["placement_id"] == placement["id"] and a["status"] == "ACTIVE"]):
        addendum["status"] = terminal_addendum_state
        amount = addendum["encumbrance_cents"]
        if account is not None and amount:
            release_encumbrance(account, amount)
        placement["addendum_encumbrance_cents"] -= amount
        placement["released_encumbrance_cents"] += amount
        addendum["encumbrance_cents"] = 0
        touch(addendum)

    # Link 4 - transportation assignments
    live = ordered([a for a in db.assignments.values()
                    if a["placement_id"] == placement["id"]
                    and a["status"] in ("REQUESTED", "ACTIVE", "WAITLISTED")])
    prior_states = [(a, a["status"]) for a in live]
    for assignment, _ in prior_states:
        assignment["status"] = "RELEASED"
        touch(assignment)
    if prior_states:
        placement["transport_status"] = "RELEASED"

    # Links 5-7 - route seats, money, then one promotion per freed seat
    for assignment, prior in prior_states:
        if prior != "ACTIVE":
            continue
        route = unwind_active_assignment(assignment, placement, account)
        if route is not None:
            promote_from_waitlist(route, account)

    # Link 8 - transition plan
    for plan in ordered([p for p in db.plans.values()
                         if p["placement_id"] == placement["id"] and p["status"] == "ACTIVE"]):
        if mode == "TERMINATE":
            plan["status"] = "ABANDONED"
            reserve = plan["reserve_cents"]
            if account is not None and reserve:
                release_encumbrance(account, reserve)
            placement["transition_reserve_cents"] = 0
            # 2.6: released_encumbrance_cents accumulates every cent the placement
            # has ever pushed back into available_cents through termination, so the
            # abandoned plan's reserve counts too.
            placement["released_encumbrance_cents"] += reserve
            plan["reserve_cents"] = 0
        else:
            plan["status"] = "COMPLETED"
        touch(plan)

    # Link 9 - disputed unpaid invoices (termination only)
    if mode == "TERMINATE":
        for invoice in ordered([i for i in db.invoices.values()
                                if i["placement_id"] == placement["id"]
                                and i["verification_status"] == "DISPUTED"
                                and i["payment_status"] == "UNPAID"]):
            invoice["payment_status"] = "VOIDED"
            touch(invoice)

    recompute_placement_encumbrance(placement)
    touch(placement)


# --------------------------------------------------------------------------
# Cascade B (payment approval)
# --------------------------------------------------------------------------

def approve_payment_cascade(invoice, placement, actor_id):
    account = account_of(placement)
    settled = invoice["verified_amount_cents"]

    # Link 0 - the invoice itself
    invoice["payment_status"] = "PAID"
    invoice["settled_amount_cents"] = settled
    invoice["approved_by_user_id"] = actor_id
    touch(invoice)

    # Link 1 - invoice to fiscal account
    if account is not None:
        settle_encumbrance(account, settled)

    # Link 2 - invoice to placement
    placement["paid_total_ytd_cents"] += settled
    recompute_placement_encumbrance(placement)
    touch(placement)

    # Link 3 - placement to funding claim
    if placement["paid_total_ytd_cents"] < HIGH_COST_TRIGGER_CENTS:
        return
    fiscal_year = placement_fiscal_year(placement)
    for claim in db.funding.values():
        if (claim["placement_id"] == placement["id"]
                and claim["claim_type"] == "HIGH_COST_FUND"
                and claim["fiscal_year"] == fiscal_year
                and claim["status"] in ("ELIGIBLE", "SUBMITTED")):
            return
    eligible_base, tier_rate, reimbursable = high_cost_amounts(placement, fiscal_year)
    claim = new_row("funding", {
        "placement_id": placement["id"],
        "claim_type": "HIGH_COST_FUND",
        "fiscal_year": fiscal_year,
        "eligible_base_cents": placement["paid_total_ytd_cents"],
        "billable_service_hours": 0,
        "tier_rate": tier_rate,
        "reimbursable_amount_cents": reimbursable,
        "source": "AUTO_CASCADE",
        "status": "ELIGIBLE",
        "submitted_at": None,
        "state_claim_reference": None,
    })
    db.funding[claim["id"]] = claim

    # Link 4 - funding claim to student
    student = student_of_placement(placement)
    if student is not None:
        student["high_cost_flag"] = True
        student["projected_state_recovery_cents"] += reimbursable
        touch(student)


# --------------------------------------------------------------------------
# activation-grace lapse sweep (fired by the clock endpoint only)
# --------------------------------------------------------------------------

def run_lapse_sweep():
    today = db.clock.date()
    for placement in ordered([p for p in db.placements.values() if p["status"] == "CONTRACTED"]):
        start = parse_date(placement["start_date"])
        if start is None:
            continue
        if today <= add_days(start, CONTRACT_ACTIVATION_GRACE_DAYS):
            continue
        reset_touch()
        account = account_of(placement)
        placement["status"] = "EXPIRED"
        placement["terminated_at"] = now_iso()
        placement["termination_reason"] = "ACTIVATION_GRACE_EXPIRED"
        release_contract_commitment(placement, account)
        recompute_placement_encumbrance(placement)
        touch(placement)
