"""Derived values, conserved ledgers and status derivation."""
from decimal import Decimal

import calc
import clock
import db
from calc import D, ZERO, ZERO2, q2

# TransferApplication status families
APP_ESCROW_STATUSES = (
    "SUBMITTED",
    "PROTEST_PERIOD",
    "UNDER_PROTEST",
    "REVISION_REQUESTED",
    "READY_FOR_DECISION",
)
APP_APPROVED_STATUSES = ("APPROVED", "APPROVED_WITH_CONDITIONS")
APP_TERMINAL_STATUSES = ("APPROVED", "APPROVED_WITH_CONDITIONS", "DENIED", "WITHDRAWN")
APP_OPEN_STATUSES = (
    "DRAFT",
    "SUBMITTED",
    "PROTEST_PERIOD",
    "UNDER_PROTEST",
    "REVISION_REQUESTED",
    "READY_FOR_DECISION",
)

TRANSFERABLE_RIGHT_STATUSES = (
    "ACTIVE",
    "ENCUMBERED",
    "PARTIALLY_TRANSFERRED",
)

LEASE_LIVE_STATUSES = ("RESERVED", "ACTIVE", "SUSPENDED")
LEASE_TERMINAL_USED_STATUSES = ("COMPLETED", "CANCELLED")
PROTEST_OPEN_STATUSES = ("FILED", "IN_NEGOTIATION", "IN_HEARING")


# ---------------------------------------------------------------------------
# Lookup helpers
# ---------------------------------------------------------------------------

def sort_seq(rows):
    return sorted(rows, key=lambda r: r["_seq"])


def apps_for_right(right_id):
    return [a for a in db.transfer_applications.values() if a["water_right_id"] == right_id]


def leases_for_right(right_id):
    return [l for l in db.lease_assignments.values() if l["water_right_id"] == right_id]


def leases_for_account(account_id):
    return [
        l
        for l in db.lease_assignments.values()
        if l["water_bank_account_id"] == account_id
    ]


def use_records_for_right(right_id):
    return [
        r
        for r in db.beneficial_use_records.values()
        if r["water_right_id"] == right_id
    ]


def studies_for_right(right_id):
    return [s for s in db.hcu_studies.values() if s["water_right_id"] == right_id]


def pods_for_right(right_id):
    return [p for p in db.points_of_diversion.values() if p["water_right_id"] == right_id]


def analyses_for_app(app_id):
    return [
        a
        for a in db.injury_analyses.values()
        if a["transfer_application_id"] == app_id
    ]


def protests_for_app(app_id):
    return [p for p in db.protests.values() if p["transfer_application_id"] == app_id]


def conditions_for_app(app_id):
    return [
        c
        for c in db.approval_conditions.values()
        if c["transfer_application_id"] == app_id
    ]


def claims_for_docket(docket_id):
    return [
        c
        for c in db.adjudication_claims.values()
        if c["decree_docket_id"] == docket_id
    ]


def accounts_for_claimant(claimant_id):
    return [
        a
        for a in db.water_bank_accounts.values()
        if a["claimant_id"] == claimant_id
    ]


def rights_for_claimant(claimant_id):
    return [r for r in db.water_rights.values() if r["claimant_id"] == claimant_id]


def condition_owner_claimant_id(condition):
    app = db.transfer_applications.get(condition["transfer_application_id"])
    if not app:
        return None
    right = db.water_rights.get(app["water_right_id"])
    return right["claimant_id"] if right else None


def app_owner_claimant_id(app):
    right = db.water_rights.get(app["water_right_id"])
    return right["claimant_id"] if right else None


# ---------------------------------------------------------------------------
# calculations.right_volume_ledger + right_status_derivation
# ---------------------------------------------------------------------------

def right_ledger(right):
    if right["status"] == "FORFEITED":
        return {
            "certified_hcu_af": ZERO2,
            "encumbered_af": ZERO2,
            "transferred_away_af": ZERO2,
            "transferable_af": ZERO2,
        }
    right_id = right["id"]
    apps = apps_for_right(right_id)
    pending = ZERO
    approved = ZERO
    for a in apps:
        if a["status"] in APP_ESCROW_STATUSES:
            pending += D(a["requested_af"])
        elif a["status"] in APP_APPROVED_STATUSES:
            approved += D(a["requested_af"])
    pending_escrow = q2(pending)

    deposits = ZERO
    for dep in db.bank_deposits:
        if dep["water_right_id"] == right_id:
            deposits += D(dep["deposit_af"])
    terminal_used = ZERO
    for lease in leases_for_right(right_id):
        if lease["status"] in LEASE_TERMINAL_USED_STATUSES:
            terminal_used += D(lease["used_af"])
    bank_hold = q2(deposits - terminal_used)

    encumbered = q2(pending_escrow + bank_hold)
    transferred = q2(approved + terminal_used)
    certified = D(right["certified_hcu_af"])
    transferable = q2(certified - encumbered - transferred)
    if transferable < ZERO:
        transferable = ZERO2
    return {
        "certified_hcu_af": q2(certified),
        "encumbered_af": encumbered,
        "transferred_away_af": transferred,
        "transferable_af": transferable,
    }


def derive_right_status(right, ledger):
    if right["status"] == "FORFEITED":
        return "FORFEITED"
    if right["status"] == "SUSPENDED":
        return "SUSPENDED"
    if not right.get("_activated"):
        return "UNADJUDICATED"
    if ledger["transferred_away_af"] > ZERO2:
        return "PARTIALLY_TRANSFERRED"
    if ledger["encumbered_af"] > ZERO2:
        return "ENCUMBERED"
    return "ACTIVE"


def refresh_forfeiture(right):
    records = use_records_for_right(right["id"])
    assessment = calc.forfeiture_assessment(
        records,
        right["authorized_diversion_af"],
        right["status"],
        clock.current_year(),
    )
    right["consecutive_nonuse_years"] = assessment["consecutive_nonuse_years"]
    right["forfeiture_risk_score"] = assessment["forfeiture_risk_score"]
    right["forfeiture_risk_band"] = assessment["forfeiture_risk_band"]
    right["_forfeiture_eligible"] = assessment["forfeiture_eligible"]
    return assessment


def pending_review_count(right_id):
    total = 0
    for app in apps_for_right(right_id):
        for analysis in analyses_for_app(app["id"]):
            if analysis["status"] == "DRAFT":
                total += 1
    return total


def recompute_right(right, bump=False, refresh_score=True):
    """Recompute the right's ledger, derived status and abandonment score.

    When `bump` is set the row's updated_at/version advance only if a ledger
    value or the status actually moved.

    `refresh_score` re-stamps the stored abandonment projection. PRD §3.2 pins
    the events that may move it — "appending a beneficial-use record, perfecting
    a right, reinstating a right, and any movement of the right into or out of
    `SUSPENDED`" — and PRD §4 says the assessment endpoint returns the
    recomputed score "without persisting anything", so a plain read must leave
    the stored projection exactly where the last such event left it.
    """
    before = (
        right.get("certified_hcu_af"),
        right.get("encumbered_af"),
        right.get("transferred_away_af"),
        right.get("transferable_af"),
        right.get("status"),
    )
    ledger = right_ledger(right)
    right["certified_hcu_af"] = ledger["certified_hcu_af"]
    right["encumbered_af"] = ledger["encumbered_af"]
    right["transferred_away_af"] = ledger["transferred_away_af"]
    right["transferable_af"] = ledger["transferable_af"]
    right["status"] = derive_right_status(right, ledger)
    right["pending_review_count"] = pending_review_count(right["id"])
    if refresh_score:
        refresh_forfeiture(right)
    after = (
        right["certified_hcu_af"],
        right["encumbered_af"],
        right["transferred_away_af"],
        right["transferable_af"],
        right["status"],
    )
    if bump and before != after:
        db.touch(right)
    return right


# ---------------------------------------------------------------------------
# calculations.bank_credit_ledger + bank_posture
# ---------------------------------------------------------------------------

def bank_ledger(account):
    account_id = account["id"]
    committed = ZERO
    leased_out = ZERO
    terminal_used = ZERO
    suspended = 0
    for lease in leases_for_account(account_id):
        status = lease["status"]
        if status in ("RESERVED", "SUSPENDED"):
            committed += D(lease["requested_af"])
            if status == "SUSPENDED":
                suspended += 1
        elif status == "ACTIVE":
            leased_out += D(lease["requested_af"])
        elif status in LEASE_TERMINAL_USED_STATUSES:
            terminal_used += D(lease["used_af"])
    deposits = ZERO
    for dep in db.bank_deposits:
        if dep["water_bank_account_id"] == account_id:
            deposits += D(dep["deposit_af"])
    deposited = q2(deposits - terminal_used)
    committed = q2(committed)
    leased_out = q2(leased_out)
    available = q2(deposited - committed - leased_out)
    if available < ZERO:
        available = ZERO2
    return {
        "deposited_credit_af": deposited,
        "committed_credit_af": committed,
        "leased_out_af": leased_out,
        "available_credit_af": available,
        "suspended_lease_count": suspended,
    }


def recompute_account(account, bump=False):
    before = (
        account.get("deposited_credit_af"),
        account.get("committed_credit_af"),
        account.get("leased_out_af"),
        account.get("available_credit_af"),
        account.get("suspended_lease_count"),
        account.get("posture"),
    )
    ledger = bank_ledger(account)
    account.update(ledger)
    claimant = db.claimants.get(account["claimant_id"])
    standing = claimant["standing_status"] if claimant else "IN_GOOD_STANDING"
    account["posture"] = calc.bank_posture(
        standing, ledger["suspended_lease_count"], ledger["available_credit_af"]
    )
    after = (
        account["deposited_credit_af"],
        account["committed_credit_af"],
        account["leased_out_af"],
        account["available_credit_af"],
        account["suspended_lease_count"],
        account["posture"],
    )
    if bump and before != after:
        db.touch(account)
    return account


# ---------------------------------------------------------------------------
# Claimant computed fields + fee/standing cascade
# ---------------------------------------------------------------------------

def outstanding_fee_balance(claimant_id):
    total = ZERO
    for condition in db.approval_conditions.values():
        if condition["payment_status"] != "OUTSTANDING":
            continue
        if condition_owner_claimant_id(condition) == claimant_id:
            total += D(condition["total_fee_usd"])
    return q2(total)


def open_application_count(claimant_id):
    count = 0
    for app in db.transfer_applications.values():
        if app["status"] not in APP_OPEN_STATUSES:
            continue
        if app_owner_claimant_id(app) == claimant_id:
            count += 1
    return count


def recompute_claimant(claimant):
    claimant["outstanding_fee_balance_usd"] = outstanding_fee_balance(claimant["id"])
    claimant["open_application_count"] = open_application_count(claimant["id"])
    return claimant


def apply_fee_cascade(claimant):
    """Re-derive the fee balance, move standing across the delinquency boundary
    and force every one of the claimant's bank accounts to re-posture."""
    if claimant is None:
        return
    balance = outstanding_fee_balance(claimant["id"])
    claimant["outstanding_fee_balance_usd"] = balance
    claimant["open_application_count"] = open_application_count(claimant["id"])
    standing = claimant["standing_status"]
    if balance > ZERO2 and standing == "IN_GOOD_STANDING":
        claimant["standing_status"] = "DELINQUENT"
    elif balance == ZERO2 and standing == "DELINQUENT":
        claimant["standing_status"] = "IN_GOOD_STANDING"
    db.touch(claimant)
    for account in accounts_for_claimant(claimant["id"]):
        recompute_account(account)
        db.touch(account)


def repost_claimant_accounts(claimant):
    for account in accounts_for_claimant(claimant["id"]):
        recompute_account(account)
        db.touch(account)


# ---------------------------------------------------------------------------
# TransferApplication derived fields
# ---------------------------------------------------------------------------

def unresolved_protest_count(app_id):
    return sum(
        1
        for p in protests_for_app(app_id)
        if p["status"] in PROTEST_OPEN_STATUSES
    )


def app_escrowed_af(app):
    if app["status"] in APP_ESCROW_STATUSES:
        return q2(D(app["requested_af"]))
    return ZERO2


def app_mitigation_fee_total(app_id):
    total = ZERO
    for condition in conditions_for_app(app_id):
        if condition["payment_status"] in ("OUTSTANDING", "PAID"):
            total += D(condition["total_fee_usd"])
    return q2(total)


def recompute_app(app):
    app["unresolved_protest_count"] = unresolved_protest_count(app["id"])
    app["escrowed_af"] = app_escrowed_af(app)
    app["mitigation_fee_total_usd"] = app_mitigation_fee_total(app["id"])
    return app


# ---------------------------------------------------------------------------
# Protest offsets (calculations.injury_net_analysis, offset component)
# ---------------------------------------------------------------------------

def stipulated_offset_total(app_id):
    total = ZERO
    for protest in protests_for_app(app_id):
        if protest["status"] == "RESOLVED_STIPULATED" and protest["track"] == "NEGOTIATION":
            total += D(protest["stipulated_offset_af"] or 0)
    return q2(total)


# ---------------------------------------------------------------------------
# DecreeDocket derived counters + priority ranking
# ---------------------------------------------------------------------------

def recompute_docket(docket):
    claims = claims_for_docket(docket["id"])
    docket["claim_count"] = len(claims)
    decreed = [c for c in claims if c["filing_status"] == "DECREED"]
    docket["decreed_claim_count"] = len(decreed)
    total = ZERO
    for c in decreed:
        total += D(c["decreed_af"] or 0)
    docket["total_decreed_af"] = q2(total)
    return docket


def reassign_priority_ranks(docket_id):
    decreed = [
        c
        for c in claims_for_docket(docket_id)
        if c["filing_status"] == "DECREED"
    ]
    decreed.sort(
        key=lambda c: (clock.parse_date(c["claimed_priority_date"]), c["_seq"])
    )
    for index, claim in enumerate(decreed, start=1):
        claim["priority_rank"] = index


def claim_objection_count(claim_id):
    claim = db.adjudication_claims.get(claim_id)
    return claim["objection_count"] if claim else 0
