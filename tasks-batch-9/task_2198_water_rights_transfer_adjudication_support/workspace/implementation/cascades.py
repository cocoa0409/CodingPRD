"""Multi-link cascades. Every row a cascade touches refreshes updated_at and
increments version by 1, including rows the caller never named."""
from decimal import Decimal

import calc
import clock
import db
import derive

ZERO2 = Decimal("0.00")


# ---------------------------------------------------------------------------
# Injury analysis helpers
# ---------------------------------------------------------------------------

def draft_analysis(app):
    for a in derive.sort_seq(derive.analyses_for_app(app["id"])):
        if a["status"] == "DRAFT":
            return a
    return None


def latest_live_analysis(app):
    """DRAFT or FINALIZED analysis, most recent first."""
    live = [
        a
        for a in derive.analyses_for_app(app["id"])
        if a["status"] in ("DRAFT", "FINALIZED")
    ]
    live.sort(key=lambda a: a["_seq"], reverse=True)
    return live[0] if live else None


def finalized_analysis(app):
    live = [
        a
        for a in derive.analyses_for_app(app["id"])
        if a["status"] == "FINALIZED"
    ]
    live.sort(key=lambda a: a["_seq"], reverse=True)
    return live[0] if live else None


def recompute_analysis(analysis, app, bump=True):
    gross = calc.injury_gross_depletion(
        analysis["method"], app["requested_af"], analysis["pod_move_miles"]
    )
    offset = derive.stipulated_offset_total(app["id"])
    analysis["gross_depletion_af"] = gross
    analysis["offset_af"] = offset
    analysis["net_injury_af"] = calc.injury_net(
        gross, offset, analysis["return_flow_credit_af"]
    )
    if bump:
        db.touch(analysis)
    return analysis


def void_draft_analyses(app):
    voided = 0
    for a in derive.analyses_for_app(app["id"]):
        if a["status"] == "DRAFT":
            a["status"] = "VOIDED"
            db.touch(a)
            voided += 1
    return voided


def finalize_draft_analyses(app):
    finalized = 0
    for a in derive.analyses_for_app(app["id"]):
        if a["status"] == "DRAFT":
            a["status"] = "FINALIZED"
            db.touch(a)
            finalized += 1
    return finalized


def dismiss_open_protests(app):
    dismissed = 0
    for p in derive.protests_for_app(app["id"]):
        if p["status"] in derive.PROTEST_OPEN_STATUSES:
            p["status"] = "DISMISSED"
            db.touch(p)
            dismissed += 1
    return dismissed


# ---------------------------------------------------------------------------
# Protest-clearance cascade, links 3-5
# ---------------------------------------------------------------------------

def protest_clearance(app):
    """Fires when a protest resolution or withdrawal empties the open set."""
    derive.recompute_app(app)
    if app["unresolved_protest_count"] != 0:
        return False
    if app["status"] != "UNDER_PROTEST":
        return False
    app["status"] = "READY_FOR_DECISION"
    finalize_draft_analyses(app)
    right = db.water_rights.get(app["water_right_id"])
    if right is not None:
        derive.recompute_right(right)
        db.touch(right)
    return True


# ---------------------------------------------------------------------------
# Condition-violation cascade (depth 4)
# ---------------------------------------------------------------------------

SUSPENDABLE_RIGHT_STATUSES = ("ACTIVE", "ENCUMBERED", "PARTIALLY_TRANSFERRED")


def condition_violation(condition):
    # link 1: the condition itself
    condition["status"] = "VIOLATED"
    db.touch(condition)

    app = db.transfer_applications.get(condition["transfer_application_id"])
    if app is None:
        return
    right = db.water_rights.get(app["water_right_id"])
    if right is None:
        return

    # link 2: the backing right is suspended
    derive.recompute_right(right)
    if right["status"] in SUSPENDABLE_RIGHT_STATUSES:
        right["status"] = "SUSPENDED"
        derive.refresh_forfeiture(right)
        db.touch(right)

    # link 3: every ACTIVE lease on the right is suspended
    accounts = {}
    for lease in derive.leases_for_right(right["id"]):
        if lease["status"] != "ACTIVE":
            continue
        lease["status"] = "SUSPENDED"
        lease["suspension_count"] = int(lease.get("suspension_count", 0)) + 1
        db.touch(lease)
        account = db.water_bank_accounts.get(lease["water_bank_account_id"])
        if account is not None:
            accounts[account["id"]] = account

    # link 4: each affected account re-ledgers and re-postures
    for account in accounts.values():
        derive.recompute_account(account)
        db.touch(account)


# ---------------------------------------------------------------------------
# Fee-payment cascade (depth 4) -- links 2-4
# ---------------------------------------------------------------------------

def fee_cascade(claimant):
    derive.apply_fee_cascade(claimant)


# ---------------------------------------------------------------------------
# Forfeiture cascade (depth 3)
# ---------------------------------------------------------------------------

def settle_lease(lease, from_status):
    start = clock.parse_date(lease["lease_start_date"])
    end = clock.parse_date(lease["lease_end_date"])
    result = calc.lease_settlement(
        lease["requested_af"],
        start,
        end,
        clock.now(),
        lease["valuation_method"],
        from_reserved=(from_status == "RESERVED"),
    )
    lease["used_af"] = result["used_af"]
    lease["settlement_credit_af"] = result["settlement_credit_af"]
    return result


def release_conditions(app):
    """Cascade link 3 of forfeiture: release compliance, reverse fees.

    Returns the number of conditions whose fiscal dimension was reversed, which
    is what PRD §3.2 makes the claimant's balance move on: "every condition whose
    fiscal dimension reads `OUTSTANDING` moves to `REVERSED`, decreasing the
    claimant's `outstanding_fee_balance_usd` by each reversed total fee."
    """
    reversed_count = 0
    for condition in derive.conditions_for_app(app["id"]):
        moved = False
        if condition["status"] == "IMPOSED":
            condition["status"] = "RELEASED"
            moved = True
        if condition["payment_status"] == "OUTSTANDING":
            condition["payment_status"] = "REVERSED"
            reversed_count += 1
            moved = True
        if moved:
            db.touch(condition)
    return reversed_count


def forfeiture(right):
    """Links 2 and 3. Link 1 (status + zeroed ledger) is done by the caller."""
    accounts = {}
    claimants = {}
    holder = db.claimants.get(right["claimant_id"])

    # link 2a: open applications are denied
    for app in derive.apps_for_right(right["id"]):
        if app["status"] not in derive.APP_OPEN_STATUSES:
            continue
        app["status"] = "DENIED"
        dismiss_open_protests(app)
        void_draft_analyses(app)
        db.touch(app)
        # link 3: conditions of the newly denied application. PRD §3.2 moves the
        # holder's fee balance (and, through it, the postures of that holder's
        # accounts) only where a condition was actually reversed, so a right with
        # nothing outstanding leaves every account row untouched.
        if release_conditions(app) and holder is not None:
            claimants[holder["id"]] = holder

    # link 2b: live leases are cancelled and settled
    for lease in derive.leases_for_right(right["id"]):
        if lease["status"] not in derive.LEASE_LIVE_STATUSES:
            continue
        from_status = lease["status"]
        settle_lease(lease, from_status)
        lease["status"] = "CANCELLED"
        db.touch(lease)
        account = db.water_bank_accounts.get(lease["water_bank_account_id"])
        if account is not None:
            accounts[account["id"]] = account
            owner = db.claimants.get(account["claimant_id"])
            if owner is not None:
                claimants[owner["id"]] = owner

    # link 3 tail: fee balance / standing for every touched claimant
    for claimant in claimants.values():
        derive.apply_fee_cascade(claimant)
        for account in derive.accounts_for_claimant(claimant["id"]):
            accounts.pop(account["id"], None)

    # The holder's derived counters (PRD §3.1) still have to reflect the denied
    # applications even where no fee moved, but re-deriving a counter is not the
    # cascade "touching" a row, so no version is bumped for it.
    if holder is not None and holder["id"] not in claimants:
        derive.recompute_claimant(holder)

    # remaining accounts (not already reposted by the fee cascade)
    for account in accounts.values():
        derive.recompute_account(account)
        db.touch(account)


# ---------------------------------------------------------------------------
# ApprovalCondition creation (shared by decide + hearing resolution)
# ---------------------------------------------------------------------------

def create_condition(app, condition_type, required_af, compliance_due_date,
                     source, user_id):
    """Mint one ApprovalCondition. MITIGATION_PAYMENT conditions are priced by
    the tiered fee schedule and start life OUTSTANDING; every other type is
    NOT_APPLICABLE with a zeroed fee block."""
    row = db.base_row()
    row.update({
        "transfer_application_id": app["id"],
        "condition_type": condition_type,
        "required_af": calc.q2(required_af),
        "compliance_due_date": compliance_due_date,
        "source": source,
        "status": "IMPOSED",
        "payment_status": "NOT_APPLICABLE",
        "base_fee_usd": ZERO2,
        "surcharge_pct": Decimal("0.000"),
        "admin_surcharge_usd": ZERO2,
        "total_fee_usd": ZERO2,
        "imposed_by_user_id": user_id,
    })
    if condition_type == "MITIGATION_PAYMENT":
        fee = calc.mitigation_fee(row["required_af"])
        row["base_fee_usd"] = fee["base_fee_usd"]
        row["surcharge_pct"] = fee["surcharge_pct"]
        row["admin_surcharge_usd"] = fee["admin_surcharge_usd"]
        row["total_fee_usd"] = fee["total_fee_usd"]
        row["payment_status"] = "OUTSTANDING"
    db.approval_conditions[row["id"]] = row
    return row
