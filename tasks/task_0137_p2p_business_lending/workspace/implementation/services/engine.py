"""Business-logic engine: state transitions, side effects, cascades.

The engine functions read & write the `store` directly. They assume callers
already validated auth, existence, body shape, and ordering preconditions —
the engine focuses on the side-effect graph and cross-entity consistency.

Conventions:
  - `stamp_create(entity)`: assigns id (if missing), sets created_at + updated_at + version=1.
  - `stamp_update(entity)`: bumps updated_at and increments version.
  - Append-only entities (PlaidSnapshot, Disclosure) use `stamp_audit_only`
    which sets id + created_at only.
"""
from __future__ import annotations

from db import store
from services.calculations import (
    build_amortization_schedule,
    charge_off_loss_shares,
    compute_final_grade,
    compute_interest_rate_bps,
    compute_monthly_payment_cents,
    compute_provisional_grade,
    origination_fee_cents,
    share_bps,
)
from utils import iso_now, new_uuid


# ── Audit / stamp helpers ──────────────────────────────────────────────────


def stamp_create(entity: dict) -> dict:
    now = iso_now(store.now())
    entity.setdefault("id", new_uuid())
    entity["created_at"] = now
    entity["updated_at"] = now
    entity["version"] = 1
    return entity


def stamp_update(entity: dict) -> dict:
    entity["updated_at"] = iso_now(store.now())
    entity["version"] = entity.get("version", 1) + 1
    return entity


def stamp_audit_only(entity: dict) -> dict:
    """For append-only entities (PlaidSnapshot, Disclosure)."""
    entity.setdefault("id", new_uuid())
    entity["created_at"] = iso_now(store.now())
    return entity


# ── Disclosure assembly ────────────────────────────────────────────────────


def _investor_count_for_listing(listing_id: str) -> int:
    invs = [
        i for i in store.investments_for_listing(listing_id)
        if i["status"] in ("COMMITTED", "CONVERTED", "LOST")
    ]
    distinct = {i["investor_id"] for i in invs}
    return len(distinct)


def _investor_count_for_loan(loan_id: str) -> int:
    loan = store.loans.get(loan_id)
    if not loan:
        return 0
    invs = [
        i for i in store.investments_for_listing(loan["listing_id"])
        if i["status"] in ("CONVERTED", "LOST")
    ]
    distinct = {i["investor_id"] for i in invs}
    return len(distinct)


def _build_disclosure_payload(kind: str, subject: dict, extra: dict | None = None) -> dict:
    extra = extra or {}
    if kind == "LISTING_OPENED":
        return {
            "principal_cents": subject["principal_cents"],
            "interest_rate_bps": subject["interest_rate_bps"],
            "term_months": subject["term_months"],
            "grade_at_listing": subject["grade_at_listing"],
        }
    if kind == "LISTING_FUNDED":
        return {
            "principal_cents": subject["principal_cents"],
            "interest_rate_bps": subject["interest_rate_bps"],
            "investor_count": _investor_count_for_listing(subject["id"]),
        }
    if kind == "LOAN_ORIGINATED":
        return {
            "principal_cents": subject["principal_cents"],
            "interest_rate_bps": subject["interest_rate_bps"],
            "term_months": subject["term_months"],
            "monthly_payment_cents": subject["monthly_payment_cents"],
            "origination_fee_cents": extra.get("origination_fee_cents", 0),
        }
    if kind == "DELINQUENCY_NOTICE":
        return {
            "principal_outstanding_cents": subject["principal_outstanding_cents"],
            "consecutive_missed_installments": subject["consecutive_missed_installments"],
            "accrued_late_fees_cents": subject["accrued_late_fees_cents"],
        }
    if kind == "DEFAULT_NOTICE":
        return {
            "principal_outstanding_cents": subject["principal_outstanding_cents"],
            "consecutive_missed_installments": subject["consecutive_missed_installments"],
        }
    if kind == "CHARGE_OFF_NOTICE":
        return {
            "charged_off_loss_cents": subject["charged_off_loss_cents"],
            "investor_count": _investor_count_for_loan(subject["id"]),
        }
    return {}


_SUBJECT_TYPE_FOR_KIND = {
    "LISTING_OPENED": "LISTING",
    "LISTING_FUNDED": "LISTING",
    "LOAN_ORIGINATED": "LOAN",
    "DELINQUENCY_NOTICE": "LOAN",
    "DEFAULT_NOTICE": "LOAN",
    "CHARGE_OFF_NOTICE": "LOAN",
    "MATERIAL_AMENDMENT": "BORROWER",
}


def emit_disclosure(platform_id: str, kind: str, subject: dict, extra: dict | None = None) -> dict:
    """Mint a DRAFT disclosure with by-value payload snapshot."""
    payload = _build_disclosure_payload(kind, subject, extra)
    disclosure = {
        "platform_id": platform_id,
        "subject_type": _SUBJECT_TYPE_FOR_KIND.get(kind, "LOAN"),
        "subject_id": subject["id"],
        "kind": kind,
        "payload": payload,
        "published": False,
        "published_on_day_index": None,
        # Snapshot of subject status at emission time — used by publish to
        # check ERR_DISCLOSURE_STALE.
        "_subject_status_at_emit": subject.get("status"),
    }
    stamp_audit_only(disclosure)
    store.disclosures[disclosure["id"]] = disclosure
    return disclosure


# ── Borrower side effects ──────────────────────────────────────────────────


def borrower_recompute_provisional(borrower: dict) -> None:
    borrower["provisional_grade"] = compute_provisional_grade(
        borrower["annual_revenue_cents"], borrower["requested_amount_cents"]
    )


def borrower_recompute_final(borrower: dict) -> None:
    snap = None
    if borrower.get("plaid_snapshot_id"):
        snap = store.plaid_snapshots.get(borrower["plaid_snapshot_id"])
    borrower["final_grade"] = compute_final_grade(borrower, snap)


def cascade_borrower_open_listings_withdraw(borrower: dict, refund: bool = True) -> None:
    """Cascade: every OPEN listing → WITHDRAWN; COMMITTED investments → RELEASED with refund."""
    for listing in list(store.listings_for_borrower(borrower["id"])):
        if listing["status"] != "OPEN":
            continue
        listing["status"] = "WITHDRAWN"
        stamp_update(listing)
        for inv in list(store.investments_for_listing(listing["id"])):
            if inv["status"] == "COMMITTED":
                inv["status"] = "RELEASED"
                stamp_update(inv)
                if refund:
                    investor = store.investors.get(inv["investor_id"])
                    if investor is not None:
                        investor["cash_balance_cents"] += inv["amount_cents"]
                        stamp_update(investor)


# ── Listing / Investment side effects ─────────────────────────────────────


def maybe_listing_funded(listing: dict, platform: dict) -> None:
    """If pledged_cents == principal_cents, transition OPEN→FUNDED and emit disclosure."""
    if listing["status"] == "OPEN" and listing["pledged_cents"] == listing["principal_cents"]:
        listing["status"] = "FUNDED"
        stamp_update(listing)
        emit_disclosure(platform["id"], "LISTING_FUNDED", listing)


def withdraw_listing_cascade(listing: dict) -> None:
    """Withdraw an OPEN listing: RELEASE all COMMITTED investments with refund."""
    listing["status"] = "WITHDRAWN"
    stamp_update(listing)
    for inv in list(store.investments_for_listing(listing["id"])):
        if inv["status"] == "COMMITTED":
            inv["status"] = "RELEASED"
            stamp_update(inv)
            investor = store.investors.get(inv["investor_id"])
            if investor is not None:
                investor["cash_balance_cents"] += inv["amount_cents"]
                stamp_update(investor)


def expire_listing_cascade(listing: dict) -> None:
    """OPEN → EXPIRED: RELEASE all COMMITTED investments with refund."""
    listing["status"] = "EXPIRED"
    stamp_update(listing)
    for inv in list(store.investments_for_listing(listing["id"])):
        if inv["status"] == "COMMITTED":
            inv["status"] = "RELEASED"
            stamp_update(inv)
            investor = store.investors.get(inv["investor_id"])
            if investor is not None:
                investor["cash_balance_cents"] += inv["amount_cents"]
                stamp_update(investor)


# ── Origination ────────────────────────────────────────────────────────────


def originate_loan_from_listing(platform: dict, listing: dict) -> dict:
    """Atomically build the Loan + Installments and convert investments."""
    principal = listing["principal_cents"]
    rate_bps = listing["interest_rate_bps"]
    term = listing["term_months"]
    monthly_payment = compute_monthly_payment_cents(principal, rate_bps, term)

    origination_day = platform["clock_day_index"]

    loan = {
        "listing_id": listing["id"],
        "borrower_id": listing["borrower_id"],
        "platform_id": platform["id"],
        "principal_cents": principal,
        "interest_rate_bps": rate_bps,
        "term_months": term,
        "monthly_payment_cents": monthly_payment,
        "principal_outstanding_cents": principal,
        "accrued_late_fees_cents": 0,
        "charged_off_loss_cents": 0,
        "consecutive_missed_installments": 0,
        "origination_day_index": origination_day,
        "status": "ACTIVE",
    }
    stamp_create(loan)
    store.loans[loan["id"]] = loan

    # Build amortization schedule and persist installments.
    schedule = build_amortization_schedule(principal, rate_bps, term, monthly_payment)
    for k, (sched_p, sched_i) in enumerate(schedule, start=1):
        inst = {
            "loan_id": loan["id"],
            "sequence_number": k,
            "due_day_index": origination_day + k * 30,
            "scheduled_principal_cents": sched_p,
            "scheduled_interest_cents": sched_i,
            "paid_principal_cents": 0,
            "paid_interest_cents": 0,
            "paid_fees_cents": 0,
            "status": "SCHEDULED",
        }
        stamp_create(inst)
        store.installments[inst["id"]] = inst

    # Convert investments.
    for inv in store.investments_for_listing(listing["id"]):
        if inv["status"] != "COMMITTED":
            continue
        inv["status"] = "CONVERTED"
        inv["share_bps"] = share_bps(inv["amount_cents"], principal)
        stamp_update(inv)
        investor = store.investors.get(inv["investor_id"])
        if investor is not None:
            investor["outstanding_principal_cents"] += inv["amount_cents"]
            stamp_update(investor)

    # Listing → ORIGINATED.
    listing["status"] = "ORIGINATED"
    stamp_update(listing)

    # Disclosure.
    orig_fee = origination_fee_cents(principal, platform["origination_fee_bps"])
    emit_disclosure(platform["id"], "LOAN_ORIGINATED", loan, {"origination_fee_cents": orig_fee})
    return loan


# ── Charge-off cascade ─────────────────────────────────────────────────────


def charge_off_loan(platform: dict, loan: dict) -> None:
    """Loan DEFAULT → CHARGED_OFF with full cascade per PRD §3.6."""
    total_loss = loan["principal_outstanding_cents"] + loan["accrued_late_fees_cents"]
    loan["charged_off_loss_cents"] = total_loss
    loan["principal_outstanding_cents"] = 0
    loan["status"] = "CHARGED_OFF"
    stamp_update(loan)

    # WAIVE remaining installments (SCHEDULED, DUE, LATE).
    for inst in store.installments_for_loan(loan["id"]):
        if inst["status"] in ("SCHEDULED", "DUE", "LATE"):
            inst["status"] = "WAIVED"
            stamp_update(inst)

    # Distribute loss across CONVERTED investments, ordered (created_at, id).
    converted = [
        i for i in store.investments_for_listing(loan["listing_id"])
        if i["status"] == "CONVERTED"
    ]
    converted.sort(key=lambda i: (i["created_at"], i["id"]))
    shares = charge_off_loss_shares(total_loss, converted)
    for inv, actual in shares:
        investor = store.investors.get(inv["investor_id"])
        if investor is not None:
            investor["outstanding_principal_cents"] = max(
                0, investor["outstanding_principal_cents"] - actual
            )
            stamp_update(investor)
        inv["status"] = "LOST"
        stamp_update(inv)

    # Disclosure.
    emit_disclosure(platform["id"], "CHARGE_OFF_NOTICE", loan)


# ── Advance clock sweep ────────────────────────────────────────────────────


def advance_clock(platform: dict, days: int) -> None:
    """Move the platform clock forward day-by-day, running every system transition.

    Per PRD §2.7 + §3.6, the per-day order is:
      1. Installment SCHEDULED → DUE
      2. Installment DUE → LATE (accumulate late fees + consecutive_missed)
      3. Loan ACTIVE → DELINQUENT, DELINQUENT → DEFAULT, DEFAULT → CHARGED_OFF
      4. LoanListing OPEN → EXPIRED
    """
    for _ in range(days):
        platform["clock_day_index"] += 1
        stamp_update(platform)
        current_day = platform["clock_day_index"]

        # ── 1. Installments SCHEDULED → DUE ─────────────────────────────────
        for inst in store.installments.values():
            if inst["status"] != "SCHEDULED":
                continue
            paid = inst["paid_principal_cents"] + inst["paid_interest_cents"]
            owed = inst["scheduled_principal_cents"] + inst["scheduled_interest_cents"]
            if current_day >= inst["due_day_index"] and paid < owed:
                inst["status"] = "DUE"
                stamp_update(inst)

        # ── 2. Installments DUE → LATE ──────────────────────────────────────
        # Process by sequence within loan so consecutive miss counter
        # increments deterministically.
        new_late_loans: set[str] = set()
        late_installments_by_loan: dict[str, list[dict]] = {}
        for inst in sorted(store.installments.values(), key=lambda x: (x["loan_id"], x["sequence_number"])):
            if inst["status"] != "DUE":
                continue
            paid = inst["paid_principal_cents"] + inst["paid_interest_cents"]
            owed = inst["scheduled_principal_cents"] + inst["scheduled_interest_cents"]
            if current_day > inst["due_day_index"] + 5 and paid < owed:
                inst["status"] = "LATE"
                stamp_update(inst)
                loan = store.loans.get(inst["loan_id"])
                if loan is None:
                    continue
                loan["accrued_late_fees_cents"] += platform["late_fee_cents"]
                loan["consecutive_missed_installments"] += 1
                stamp_update(loan)
                late_installments_by_loan.setdefault(loan["id"], []).append(inst)
                new_late_loans.add(loan["id"])

        # ── 3. Loan ACTIVE → DELINQUENT ─────────────────────────────────────
        for loan_id in new_late_loans:
            loan = store.loans.get(loan_id)
            if loan is None:
                continue
            if loan["status"] == "ACTIVE" and loan["consecutive_missed_installments"] >= 1:
                loan["status"] = "DELINQUENT"
                stamp_update(loan)
                emit_disclosure(platform["id"], "DELINQUENCY_NOTICE", loan)

        # ── 3b. Loan DELINQUENT → DEFAULT ───────────────────────────────────
        for loan in list(store.loans.values()):
            if loan["status"] == "DELINQUENT" and loan["consecutive_missed_installments"] >= 3:
                loan["status"] = "DEFAULT"
                stamp_update(loan)
                emit_disclosure(platform["id"], "DEFAULT_NOTICE", loan)

        # ── 3c. Loan DEFAULT → CHARGED_OFF ──────────────────────────────────
        for loan in list(store.loans.values()):
            if loan["status"] == "DEFAULT" and loan["consecutive_missed_installments"] >= 5:
                charge_off_loan(platform, loan)

        # ── 4. LoanListing OPEN → EXPIRED ───────────────────────────────────
        for listing in list(store.loan_listings.values()):
            if listing["platform_id"] != platform["id"]:
                continue
            if listing["status"] != "OPEN":
                continue
            if current_day > listing["funding_deadline_day_index"] and listing["pledged_cents"] < listing["principal_cents"]:
                expire_listing_cascade(listing)


# ── Payment posting ────────────────────────────────────────────────────────


def post_payment_and_run_waterfall(platform: dict, loan: dict, payment_amount_cents: int) -> dict:
    """Allocate the payment, mutate installments + loan, return the Payment dict (unstored).

    The caller persists the payment record. Loan status transitions to
    PAID_OFF or DELINQUENT→ACTIVE are computed here.
    """
    from services.calculations import waterfall_allocate

    installments = sorted(
        store.installments_for_loan(loan["id"]), key=lambda x: x["sequence_number"]
    )
    allocation, deltas = waterfall_allocate(
        payment_amount_cents,
        installments,
        platform["late_fee_cents"],
        platform["servicing_fee_bps"],
    )

    # Apply deltas to installments.
    late_fee_per_event = platform["late_fee_cents"]
    for inst in installments:
        d = deltas.get(inst["id"])
        if not d:
            continue
        inst["paid_principal_cents"] += d["principal"]
        inst["paid_interest_cents"] += d["interest"]
        inst["paid_fees_cents"] += d["fees"]
        # Status updates.
        owed_pi = inst["scheduled_principal_cents"] + inst["scheduled_interest_cents"]
        paid_pi = inst["paid_principal_cents"] + inst["paid_interest_cents"]
        if inst["status"] == "LATE":
            owed_total = owed_pi + late_fee_per_event
            paid_total = paid_pi + inst["paid_fees_cents"]
            if paid_total >= owed_total and paid_pi >= owed_pi:
                inst["status"] = "PAID"
        elif inst["status"] == "DUE":
            if paid_pi >= owed_pi:
                inst["status"] = "PAID"
        elif inst["status"] == "SCHEDULED":
            # Prepayment may have fully paid this scheduled installment's
            # principal — but interest only accrues when the installment
            # comes due. Per PRD §3.5, prepayment principal records against
            # the next SCHEDULED installment. We mark it PAID only when both
            # scheduled principal and scheduled interest are fully paid
            # (which, for a still-SCHEDULED installment, means principal is
            # fully prepaid; interest is presumed zero until DUE).
            if (
                inst["paid_principal_cents"] >= inst["scheduled_principal_cents"]
                and inst["paid_interest_cents"] >= inst["scheduled_interest_cents"]
            ):
                inst["status"] = "PAID"
        stamp_update(inst)

    # Late fee accrual on loan: drop accrued by the amount actually paid
    # against late fees.
    loan["accrued_late_fees_cents"] = max(0, loan["accrued_late_fees_cents"] - allocation["late_fees_cents"])

    # Principal outstanding.
    loan["principal_outstanding_cents"] = max(
        0, loan["principal_outstanding_cents"] - allocation["principal_cents"]
    )

    # Recompute consecutive_missed_installments — if no LATE installments remain on the loan, reset to 0.
    any_late = any(i["status"] == "LATE" for i in store.installments_for_loan(loan["id"]))
    if not any_late:
        loan["consecutive_missed_installments"] = 0

    # Status transitions on the loan.
    all_done = all(
        i["status"] in ("PAID", "WAIVED") for i in store.installments_for_loan(loan["id"])
    )
    if loan["status"] == "DELINQUENT" and not any_late:
        loan["status"] = "ACTIVE"
    if loan["principal_outstanding_cents"] == 0 and all_done:
        loan["status"] = "PAID_OFF"
    stamp_update(loan)

    return allocation
