"""Cascades, the logical-clock sweep, the funding waterfall and the funder
selector.  Ordering inside every cascade follows PRD 2.3 and 2.10.
"""

from datetime import timedelta

from db import (clock, clock_date, db, order_key, put_dt, sorted_rows, touch)
from errors import ApiError
from services import calc
from services import recompute as rc

OUTSTANDING_OFFER_STATUSES = ("NAMED", "COUNTERED")


# --------------------------------------------------------------------------
# offer cascades
# --------------------------------------------------------------------------

def expire_offers(offers):
    for offer in sorted_rows(offers):
        if offer["status"] in OUTSTANDING_OFFER_STATUSES:
            offer["status"] = "EXPIRED"
            touch(offer)


def expire_offers_of_invoice(invoice_id):
    expire_offers(rc.invoice_offers(invoice_id))


def refresh_named_offer_count(session):
    count = 0
    for offer in rc.session_offers(session["id"]):
        if offer["status"] in ("NAMED", "COUNTERED", "ACCEPTED"):
            count += 1
    if session["named_offer_count"] != count:
        session["named_offer_count"] = count
        return True
    return False


def session_clearing_apr(session_id):
    rows = []
    for offer in rc.session_offers(session_id):
        if offer["status"] != "ACCEPTED":
            continue
        invoice = db.invoices.get(offer["invoice_id"])
        if invoice is None:
            continue
        rows.append((offer["accepted_apr_bps"], invoice["face_amount_cents"]))
    return calc.clearing_apr(rows)


def close_session(session):
    """SETTLE semantics, shared with the clock driven close."""
    session["clearing_apr_bps"] = session_clearing_apr(session["id"])
    session["status"] = "CLOSED"
    expire_offers(rc.session_offers(session["id"]))
    refresh_named_offer_count(session)
    touch(session)


def cancel_session(session):
    session["status"] = "CANCELLED"
    expire_offers(rc.session_offers(session["id"]))
    refresh_named_offer_count(session)
    touch(session)


# --------------------------------------------------------------------------
# suppression cascade (PRD 3.4)
# --------------------------------------------------------------------------

def suppress_invoice(invoice):
    """Hops 2 to 4 of the dispute raise cascade."""
    voided_offers = []
    for offer in rc.invoice_offers(invoice["id"]):
        if offer["status"] in ("NAMED", "COUNTERED", "ACCEPTED"):
            offer["status"] = "VOIDED_BY_SUPPRESSION"
            touch(offer)
            voided_offers.append(offer)
            session = db.sessions.get(offer["session_id"])
            if session is not None and refresh_named_offer_count(session):
                touch(session)
    touched_funders = set()
    touched_buyers = set()
    for offer in voided_offers:
        for payment in rc.offer_payments(offer["id"]):
            if payment["funding_status"] not in ("RESERVED", "DEPLOYED"):
                continue
            payment["funding_status"] = "VOID"
            touch(payment)
            if payment.get("funder_id"):
                touched_funders.add(payment["funder_id"])
            else:
                program = rc.program_of_invoice(invoice)
                if program is not None:
                    touched_buyers.add(program["buyer_id"])
    for funder_id in sorted(touched_funders):
        funder = db.funders.get(funder_id)
        if funder is not None:
            rc.recompute_funder_capital(funder)
    for buyer_id in sorted(touched_buyers):
        buyer = db.buyers.get(buyer_id)
        if buyer is not None:
            rc.recompute_buyer_credit(buyer)
    rc.recompute_invoice_face(invoice)


# --------------------------------------------------------------------------
# invoice maturity
# --------------------------------------------------------------------------

def mature_invoice(invoice):
    invoice["status"] = "MATURED"
    expire_offers_of_invoice(invoice["id"])
    touch(invoice)
    program = rc.program_of_invoice(invoice)
    if program is not None:
        rc.recompute_program_adoption(program)


# --------------------------------------------------------------------------
# logical clock sweep (PRD 3.5) -- five steps, strictly in order
# --------------------------------------------------------------------------

def run_clock_sweep(new_clock):
    # step 1: store the instant
    db.clock = new_clock
    today = new_clock.date()

    # step 2: session windows, processed in opens_at ascending order
    closed = []
    sessions = sorted(
        db.sessions.values(), key=lambda s: (s["_opens_at"], s["created_at"], s["_seq"])
    )
    for session in sessions:
        status = session["status"]
        if status not in ("SCHEDULED", "LIVE"):
            continue
        if new_clock >= session["_closes_at"]:
            session["clearing_apr_bps"] = session_clearing_apr(session["id"])
            session["status"] = "CLOSED"
            touch(session)
            closed.append(session)
            continue
        if status == "SCHEDULED" and new_clock >= session["_opens_at"]:
            program = db.programs.get(session["program_id"])
            if program is not None and program["status"] in ("OPEN", "PAUSED"):
                session["status"] = "LIVE"
                touch(session)

    # step 3: outstanding offers on sessions closed in step 2
    pending = []
    for session in closed:
        for offer in rc.session_offers(session["id"]):
            if offer["status"] in OUTSTANDING_OFFER_STATUSES:
                pending.append(offer)
    expire_offers(pending)
    for session in closed:
        if refresh_named_offer_count(session):
            touch(session)

    # step 4: invoices whose net_due_date has passed (SUPPRESSED held out)
    due = [
        invoice
        for invoice in db.invoices.values()
        if invoice["status"] in ("ELIGIBLE", "OFFERED")
        and today > invoice["_net_due_date"].date()
    ]
    due.sort(key=lambda i: (i["_net_due_date"], i["created_at"], i["_seq"]))
    for invoice in due:
        mature_invoice(invoice)

    # step 5: commitments whose effective_to has passed
    expired_funders = set()
    for commitment in sorted_rows(list(db.commitments.values())):
        if commitment["status"] != "ACTIVE":
            continue
        if today > commitment["_effective_to"].date():
            commitment["status"] = "EXPIRED"
            touch(commitment)
            expired_funders.add(commitment["funder_id"])
    rc.recompute_all_funders()


# --------------------------------------------------------------------------
# supplier fork-join (PRD 3.2)
# --------------------------------------------------------------------------

def supplier_join(supplier):
    """Returns True when the identity and bank axes join into ACTIVE."""
    if supplier["onboarding_status"] != "VERIFYING":
        return False
    if supplier["idv_status"] != "PASSED":
        return False
    if supplier["bank_status"] != "VERIFIED":
        return False
    if supplier["sanctions_hold"]:
        return False
    supplier["onboarding_status"] = "ACTIVE"
    put_dt(supplier, "payment_ready_at", clock())
    return True


# --------------------------------------------------------------------------
# funder selection + funding waterfall (PRD 3.7)
# --------------------------------------------------------------------------

def select_funder(accepted_apr_bps, face_amount_cents, pre_fee_net, projected_value_date):
    scored = []
    for funder in sorted_rows(list(db.funders.values())):
        if funder["status"] != "ACTIVE":
            continue
        if funder["min_apr_bps"] > accepted_apr_bps:
            continue
        if funder["max_single_invoice_cents"] < face_amount_cents:
            continue
        encumbered = rc.funder_encumbered(funder["id"])
        headroom = rc.funder_committed_at(funder["id"], projected_value_date) - encumbered
        if headroom < pre_fee_net:
            continue
        score = calc.funder_score(funder, accepted_apr_bps, headroom, pre_fee_net)
        scored.append((-score, funder["fee_spread_bps"], order_key(funder), funder))
    if not scored:
        return None
    scored.sort(key=lambda row: (row[0], row[1], row[2]))
    return scored[0][3]


def funding_candidates(policy):
    if policy == "SELF_ONLY":
        return ["BUYER_SELF"]
    if policy == "FUNDER_ONLY":
        return ["FUNDER"]
    return ["BUYER_SELF", "FUNDER"]


def resolve_funding(program, buyer, invoice, accepted_apr_bps, pre_fee_net,
                    projected_value_date, exclude_payment_id=None):
    """Walk the programme's waterfall; the exhaustion error belongs to the
    last candidate the policy names."""
    candidates = funding_candidates(program["funding_policy"])
    credit_used = rc.buyer_credit_used(buyer["id"], exclude_payment_id)
    for candidate in candidates:
        if candidate == "BUYER_SELF":
            if buyer["self_funding_enabled"] and credit_used + pre_fee_net <= buyer["credit_limit_cents"]:
                return "BUYER_SELF", None
        else:
            funder = select_funder(
                accepted_apr_bps, invoice["face_amount_cents"], pre_fee_net,
                projected_value_date,
            )
            if funder is not None:
                return "FUNDER", funder
    last = candidates[-1]
    if last == "FUNDER":
        raise ApiError("ERR_NO_ELIGIBLE_FUNDER")
    if not buyer["self_funding_enabled"]:
        raise ApiError("ERR_SELF_FUNDING_DISABLED")
    raise ApiError("ERR_BUYER_CREDIT_LIMIT_EXCEEDED")


def projected_value_date(basis_dt):
    return (basis_dt + timedelta(days=calc.VALUE_DATE_LAG_DAYS)).date()
