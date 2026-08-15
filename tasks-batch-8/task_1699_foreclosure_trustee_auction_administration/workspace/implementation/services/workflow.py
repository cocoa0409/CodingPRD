"""Workflow cascades and multi-entity transactions.

Every resource mutated by a cascade gets its own updated_at refresh and
version increment (PRD §2.4). The parent ForeclosureCase is touched exactly
once per triggering operation regardless of how many of its fields changed.
"""
from datetime import timedelta

import db
from db import stamp_new, touch, now_iso
from services import calc
from services.domain import (
    recorded_nod, live_nots, active_instruction, pending_sale, closed_sale,
    approved_advances, case_quotes, case_instructions, case_advances,
    case_disbursements, sale_registrations, sale_bids, sale_deeds,
    case_claims, get_beneficiary, claim_derived_status,
)
from util import parse_date_strict, format_like


# ---------------------------------------------------------------------------
# Shared cascade pieces
# ---------------------------------------------------------------------------

def _rescind_recorded_nod(case):
    nod = recorded_nod(case["id"])
    if nod is not None:
        nod["status"] = "RESCINDED"
        nod["rescinded_at"] = now_iso()
        touch(nod)


def _void_live_nots_on_cancel(case):
    """NOD rescind path: NOTS in RECORDED/PUBLICATION_COMPLETE (and
    SALE_SCHEDULED) becomes VOIDED."""
    nots = live_nots(case["id"])
    if nots is not None and nots["status"] in ("RECORDED", "PUBLICATION_COMPLETE", "SALE_SCHEDULED"):
        nots["status"] = "VOIDED"
        touch(nots)


def _conclude_nots_on_cure(case):
    """Payoff/reinstatement from NOTS_RECORDED: NOTS in RECORDED /
    PUBLICATION_COMPLETE -> VOIDED. From SALE_SCHEDULED: -> CONCLUDED."""
    nots = live_nots(case["id"])
    if nots is None:
        return
    if nots["status"] in ("RECORDED", "PUBLICATION_COMPLETE"):
        nots["status"] = "VOIDED"
        touch(nots)
    elif nots["status"] == "SALE_SCHEDULED":
        nots["status"] = "CONCLUDED"
        touch(nots)


def _void_pending_sale_and_settle(case):
    """Void the SCHEDULED sale of the case and push its QUALIFIED
    registrations to REFUND_PENDING (case terminal-transition cascade)."""
    sale = pending_sale(case["id"])
    if sale is not None and sale["status"] == "SCHEDULED":
        sale["status"] = "VOIDED"
        touch(sale)
        for reg in sale_registrations(sale["id"]):
            if reg["status"] == "QUALIFIED":
                reg["status"] = "REFUND_PENDING"
                touch(reg)


def _expire_active_instruction(case):
    ins = active_instruction(case["id"])
    if ins is not None:
        ins["status"] = "EXPIRED"
        touch(ins)


def _void_issued_quotes(case, except_quote_id=None):
    for q in case_quotes(case["id"]):
        if q["status"] == "ISSUED" and q["id"] != except_quote_id:
            q["status"] = "VOIDED"
            touch(q)


def _reimburse_approved_advances(case, by_sale_id=None):
    """Every APPROVED advance -> REIMBURSED; beneficiary outstanding total
    falls by the same amounts."""
    advances = approved_advances(case["id"])
    if not advances:
        return
    ben = get_beneficiary(case["beneficiary_id"])
    for adv in advances:
        adv["status"] = "REIMBURSED"
        adv["_reimbursed_by_sale_id"] = by_sale_id
        touch(adv)
        ben["total_outstanding_advances_cents"] -= adv["amount_cents"]
    touch(ben)


# ---------------------------------------------------------------------------
# Quote acceptance cascades (PRD §3.6)
# ---------------------------------------------------------------------------

def apply_quote_acceptance(case, quote):
    """Drive the case to REINSTATED or PAID_OFF with the full cascade set for
    the quote type and the case's current lifecycle state. The quote itself
    (ACCEPTED) is stamped by the caller before this runs."""
    state = case["lifecycle_status"]
    if quote["quote_type"] == "REINSTATEMENT":
        _rescind_recorded_nod(case)
        if state == "NOTS_RECORDED":
            _conclude_nots_on_cure(case)   # RECORDED/PUBLICATION_COMPLETE -> VOIDED
        elif state == "SALE_SCHEDULED":
            _conclude_nots_on_cure(case)   # SALE_SCHEDULED -> CONCLUDED
            _void_pending_sale_and_settle(case)
        case["lifecycle_status"] = "REINSTATED"
    else:  # PAYOFF
        if state in ("NOD_RECORDED", "NOTS_RECORDED", "SALE_SCHEDULED"):
            _rescind_recorded_nod(case)
        if state == "NOTS_RECORDED":
            _conclude_nots_on_cure(case)
        elif state == "SALE_SCHEDULED":
            _conclude_nots_on_cure(case)
            _void_pending_sale_and_settle(case)
        # every payoff acceptance reimburses the beneficiary's costs inside
        # the payoff
        _reimburse_approved_advances(case)
        case["lifecycle_status"] = "PAID_OFF"
    # blanket terminal rule (PRD §3.6): any ISSUED quote -> VOIDED, any
    # ACTIVE instruction -> EXPIRED
    _void_issued_quotes(case, except_quote_id=quote["id"])
    _expire_active_instruction(case)
    touch(case)


# ---------------------------------------------------------------------------
# NOD rescission cascade (PRD §3.2)
# ---------------------------------------------------------------------------

def apply_nod_rescission(case, nod):
    state = case["lifecycle_status"]
    nod["status"] = "RESCINDED"
    nod["rescinded_at"] = now_iso()
    touch(nod)
    if state == "NOTS_RECORDED":
        _void_live_nots_on_cancel(case)
    elif state == "SALE_SCHEDULED":
        _void_live_nots_on_cancel(case)    # rescind VOIDS the SALE_SCHEDULED nots
        _void_pending_sale_and_settle(case)
    _void_issued_quotes(case)
    _expire_active_instruction(case)
    case["lifecycle_status"] = "CANCELLED"
    touch(case)


# ---------------------------------------------------------------------------
# Stay filing side effect: auto-postpone a SCHEDULED sale, or overflow-void
# the notice machinery (PRD §3.7)
# ---------------------------------------------------------------------------

def apply_stay_auto_postponement(case, stay_type):
    """If a sale of the case is SCHEDULED: postpone it exactly 30 days with a
    system Postponement consuming one of the notice's three; when the count
    is already 3 the sale and the NOTS are VOIDED and the case rewinds
    SALE_SCHEDULED -> NOD_RECORDED. Returns nothing; caller touches case."""
    sale = pending_sale(case["id"])
    if sale is None or sale["status"] != "SCHEDULED":
        return
    nots = db.notices_of_trustee_sale.get(sale["notice_of_trustee_sale_id"])
    if nots is not None and nots["postponement_count"] >= calc.MAX_POSTPONEMENTS_PER_NOTS:
        # forced fourth postponement overflows: void the machinery
        sale["status"] = "VOIDED"
        touch(sale)
        for reg in sale_registrations(sale["id"]):
            if reg["status"] == "QUALIFIED":
                reg["status"] = "REFUND_PENDING"
                touch(reg)
        nots["status"] = "VOIDED"
        touch(nots)
        case["lifecycle_status"] = "NOD_RECORDED"
        return
    reason = "BANKRUPTCY_STAY" if stay_type.startswith("BANKRUPTCY") else "OPERATION_OF_LAW"
    prior = sale["scheduled_sale_start_at"]
    new_start = format_like(prior, db._parse_iso(prior) + timedelta(days=30))
    post = {
        "auction_sale_id": sale["id"],
        "prior_sale_start_at": prior,
        "new_sale_start_at": new_start,
        "reason": reason,
        "announced_via": "ADVANCE",
    }
    stamp_new(post, common=False)  # Postponement: immutable ledger entry
    db.postponements[post["id"]] = post
    sale["scheduled_sale_start_at"] = new_start
    touch(sale)
    if nots is not None:
        nots["postponement_count"] += 1
        touch(nots)


# ---------------------------------------------------------------------------
# Sale close: winner determination, proceeds application, room settlement
# (PRD §3.8 "Closing the sale")
# ---------------------------------------------------------------------------

def determine_winner(sale):
    """Candidates are bids whose registration is QUALIFIED at close.
    Highest amount wins; ties break to earliest placed_at (never id).
    Returns (winner_type, winning_bid_cents, winning_registration_or_None)."""
    candidates = []
    for bid in sale_bids(sale["id"]):
        reg = db.bidder_registrations.get(bid["bidder_registration_id"])
        if reg is not None and reg["status"] == "QUALIFIED":
            candidates.append(bid)
    if not candidates:
        return "BENEFICIARY", sale["opening_bid_cents"], None
    # placed_at ASC order already; stable max by amount keeps earliest on ties
    best = None
    for bid in candidates:
        if best is None or bid["amount_cents"] > best["amount_cents"]:
            best = bid
    return "THIRD_PARTY", best["amount_cents"], best["bidder_registration_id"]


def close_sale(case, sale):
    """The full close transaction. Precondition checks live in the route."""
    close_dt = db.now_dt()
    close_date = close_dt.date()

    winner_type, winning_bid, winner_reg_id = determine_winner(sale)
    debt = calc.total_debt_at_close(case, close_date)
    fee = calc.trustee_compensation_fee(winner_type, winning_bid, debt)
    advances = approved_advances(case["id"])  # created_at ASC
    costs_total = sum(a["amount_cents"] for a in advances)
    obligations = fee + costs_total + debt
    surplus = max(0, winning_bid - obligations)

    # --- proceeds application: fixed order, each a CLEARED disbursement ---
    def _disburse(recipient_type, amount, claim_id=None, advance_id=None):
        d = {
            "foreclosure_case_id": case["id"],
            "surplus_claim_id": claim_id,
            "recipient_type": recipient_type,
            "amount_cents": amount,
            "distribution_run_index": 0,  # 0 marks proceeds-application legs
            "status": "CLEARED",
            "reversal_reason": None,
            "_sale_id": sale["id"],
            "_advance_id": advance_id,
        }
        stamp_new(d)
        db.disbursements[d["id"]] = d
        return d

    _disburse("TRUSTEE_FEE", fee)
    ben = get_beneficiary(case["beneficiary_id"])
    ben_changed = False
    for adv in advances:
        _disburse("BENEFICIARY_COST_REIMBURSEMENT", adv["amount_cents"], advance_id=adv["id"])
        adv["status"] = "REIMBURSED"
        adv["_reimbursed_by_sale_id"] = sale["id"]
        touch(adv)
        ben["total_outstanding_advances_cents"] -= adv["amount_cents"]
        ben_changed = True
    if ben_changed:
        touch(ben)
    remaining = winning_bid - fee - costs_total
    debt_payoff = min(remaining, debt)
    if debt_payoff > 0:
        _disburse("BENEFICIARY_DEBT_PAYOFF", debt_payoff)

    # --- sale / notice / instruction / registration settlement ---
    sale["winner_type"] = winner_type
    sale["winning_bid_cents"] = winning_bid
    sale["winning_bidder_registration_id"] = winner_reg_id
    sale["total_debt_at_close_cents"] = debt
    sale["closed_at"] = now_iso()
    sale["status"] = "CLOSED"
    touch(sale)

    nots = db.notices_of_trustee_sale.get(sale["notice_of_trustee_sale_id"])
    if nots is not None:
        nots["status"] = "CONCLUDED"
        touch(nots)

    ins = active_instruction(case["id"])
    if ins is not None:
        ins["status"] = "EXECUTED"
        touch(ins)

    for reg in sale_registrations(sale["id"]):
        if reg["status"] == "QUALIFIED":
            if winner_type == "THIRD_PARTY" and reg["id"] == winner_reg_id:
                reg["status"] = "DEPOSIT_APPLIED"
            else:
                reg["status"] = "REFUND_PENDING"
            touch(reg)

    case["lifecycle_status"] = "SOLD"
    case["undistributed_surplus_cents"] = surplus
    touch(case)


# ---------------------------------------------------------------------------
# Sale void: full compensation unwind (PRD §3.8 "Voiding the sale")
# ---------------------------------------------------------------------------

def void_sale(case, sale, reason):
    was_closed = sale["status"] == "CLOSED"
    sale["status"] = "VOIDED"
    touch(sale)

    for deed in sale_deeds(sale["id"]):
        if deed["status"] == "DRAFTED":
            deed["status"] = "VOIDED"
            touch(deed)

    for reg in sale_registrations(sale["id"]):
        if reg["status"] in ("QUALIFIED", "DEPOSIT_APPLIED"):
            reg["status"] = "REFUND_PENDING"
            touch(reg)

    if was_closed:
        # reverse every still-CLEARED proceeds-application disbursement of
        # this sale's close (compensation)
        for d in case_disbursements(case["id"]):
            if (d.get("_sale_id") == sale["id"] and d["status"] == "CLEARED"
                    and d["recipient_type"] in ("TRUSTEE_FEE",
                                                "BENEFICIARY_COST_REIMBURSEMENT",
                                                "BENEFICIARY_DEBT_PAYOFF")):
                d["status"] = "REVERSED"
                d["reversal_reason"] = reason
                touch(d)
        # every advance this sale's close reimbursed returns to APPROVED
        ben = get_beneficiary(case["beneficiary_id"])
        ben_changed = False
        for adv in case_advances(case["id"]):
            if adv["status"] == "REIMBURSED" and adv.get("_reimbursed_by_sale_id") == sale["id"]:
                adv["status"] = "APPROVED"
                adv["_reimbursed_by_sale_id"] = None
                touch(adv)
                ben["total_outstanding_advances_cents"] += adv["amount_cents"]
                ben_changed = True
        if ben_changed:
            touch(ben)
        case["undistributed_surplus_cents"] = 0

    nots = db.notices_of_trustee_sale.get(sale["notice_of_trustee_sale_id"])
    if nots is not None and nots["status"] in ("SALE_SCHEDULED", "CONCLUDED"):
        # publications remain valid; the notice is immediately re-schedulable
        nots["status"] = "PUBLICATION_COMPLETE"
        touch(nots)

    case["lifecycle_status"] = "NOTS_RECORDED"
    touch(case)


# ---------------------------------------------------------------------------
# Surplus distribution waterfall (PRD §3.9, calculation surplus_waterfall)
# ---------------------------------------------------------------------------

def run_distribution(case):
    """Run one waterfall pass. Returns (run_index, created_count,
    distributed_cents, undistributed_after, case_status_after).

    Raises nothing; the caller applies the ERR_NO_DISTRIBUTABLE_SURPLUS gate
    via the returned counts (zero disbursements and no close => error)."""
    eligible = [c for c in case_claims(case["id"])
                if c["status"] == "APPROVED" and c["paid_cents"] < c["approved_amount_cents"]]
    created = []
    remaining = case["undistributed_surplus_cents"]

    def _pay(claim, amount):
        nonlocal remaining
        d = {
            "foreclosure_case_id": case["id"],
            "surplus_claim_id": claim["id"],
            "recipient_type": "CLAIMANT",
            "amount_cents": amount,
            "distribution_run_index": 0,  # set after run index is known
            "status": "CLEARED",
            "reversal_reason": None,
            "_sale_id": None,
            "_advance_id": None,
        }
        stamp_new(d)
        db.disbursements[d["id"]] = d
        created.append(d)
        claim["paid_cents"] += amount
        if claim["paid_cents"] >= claim["approved_amount_cents"]:
            claim["status"] = "PAID"
        touch(claim)
        remaining -= amount

    # tiers in priority_rank ASC; the tier pool is the full remaining surplus
    # when entering the tier — a tier is fully satisfied or the run ends with
    # the surplus exhausted inside it.
    tiers = sorted({c["priority_rank"] for c in eligible})
    for rank in tiers:
        if remaining <= 0:
            break
        tier = [c for c in eligible if c["priority_rank"] == rank]
        tier.sort(key=lambda c: (c["created_at"], c["_seq"]))  # never id
        if case["distribution_method"] == "STATUTORY_PRIORITY":
            for claim in tier:
                if remaining <= 0:
                    break
                amount = min(claim["approved_amount_cents"] - claim["paid_cents"], remaining)
                if amount > 0:
                    _pay(claim, amount)
        else:  # PRO_RATA
            unpaid = [c["approved_amount_cents"] - c["paid_cents"] for c in tier]
            tier_total = sum(unpaid)
            pool = remaining
            if pool >= tier_total:
                for claim, u in zip(tier, unpaid):
                    if u > 0:
                        _pay(claim, u)
            else:
                for claim, share in zip(tier, calc.pro_rata_shares(pool, unpaid)):
                    if share > 0:
                        _pay(claim, share)

    # borrower residue: no eligible approved claims remain, surplus still
    # positive, and either the claims window has closed or no non-terminal
    # claims exist on the case.
    still_eligible = [c for c in case_claims(case["id"])
                      if c["status"] == "APPROVED" and c["paid_cents"] < c["approved_amount_cents"]]
    if not still_eligible and remaining > 0:
        deadline_passed = False
        sale = closed_sale(case["id"])
        if sale is not None and sale.get("closed_at"):
            close_date = db._parse_iso(sale["closed_at"]).date()
            deadline_passed = (db.CLOCK.now_date()
                               > close_date + timedelta(days=calc.CLAIMS_WINDOW_DAYS))
        non_terminal = [c for c in case_claims(case["id"])
                        if (c["status"] == "APPROVED")
                        or (c["status"] == "FILED"
                            and claim_derived_status(c) != "EXPIRED")]
        if deadline_passed or not non_terminal:
            d = {
                "foreclosure_case_id": case["id"],
                "surplus_claim_id": None,
                "recipient_type": "BORROWER_RESIDUE",
                "amount_cents": remaining,
                "distribution_run_index": 0,
                "status": "CLEARED",
                "reversal_reason": None,
                "_sale_id": None,
                "_advance_id": None,
            }
            stamp_new(d)
            db.disbursements[d["id"]] = d
            created.append(d)
            remaining = 0

    case["undistributed_surplus_cents"] = remaining

    # final reconciliation pass closes the file
    closes = False
    open_claims = [c for c in case_claims(case["id"])
                   if c["status"] == "APPROVED"
                   or (c["status"] == "FILED"
                       and claim_derived_status(c) != "EXPIRED")]
    if case["lifecycle_status"] == "DEED_RECORDED" and remaining == 0 and not open_claims:
        case["lifecycle_status"] = "CLOSED"
        closes = True

    return created, closes
