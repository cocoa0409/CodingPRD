"""Booking cascade: per-type booking algorithms, booking totals, reversal.

Pinned rounding orders (PRD 2.6 / 3.6): per-lot floor first, account-aggregate
sum of fractional parts second. All booking-created PositionLots take
acquisition_date = event.payable_date except SPIN_OFF lots, which inherit the
parent lot's acquisition_date.
"""

import db
import util
import errors as errmod
from errors import ApiError
from helpers import stamp_new, stamp_immutable, touch
from domain import open_lots, recompute_account, ODD_LOT_THRESHOLD


# ---------------------------------------------------------------------------
# ledger lines
# ---------------------------------------------------------------------------

def add_line(booking_id, entitlement_id, lot_id, kind,
             q_delta=0.0, b_delta=0, c_delta=0, prior_q=None, prior_b=None):
    line = {
        "booking_id": booking_id,
        "entitlement_id": entitlement_id,
        "position_lot_id": lot_id,
        "line_kind": kind,
        "quantity_delta": float(util.D(q_delta)),
        "basis_delta_cents": int(b_delta),
        "cash_delta_cents": int(c_delta),
        "prior_quantity": (None if prior_q is None else float(util.D(prior_q))),
        "prior_basis_cents": (None if prior_b is None else int(prior_b)),
    }
    stamp_immutable(line)
    db.insert("booking_lines", line)
    return line


def booking_lines(booking_id):
    return [l for l in db.all_rows("booking_lines") if l["booking_id"] == booking_id]


def create_booked_lot(account_id, security_id, quantity, basis, acquisition_date,
                      booking_id):
    lot = {
        "account_id": account_id,
        "security_id": security_id,
        "origin_booking_id": booking_id,
        "quantity": float(util.D(quantity)),
        "acquisition_date": acquisition_date,
        "cost_basis_total_cents": int(basis),
        "status": "OPEN",
    }
    stamp_new(lot)
    db.insert("position_lots", lot)
    return lot


# ---------------------------------------------------------------------------
# per-type booking algorithms
# ---------------------------------------------------------------------------

def _book_split_like(event, booking, ent):
    """SPLIT / STOCK_DIVIDEND: per-lot floor-then-sum; basis conserved."""
    terms = event["terms"]
    ratio_num = util.D(terms["ratio_num"])
    ratio_den = util.D(terms["ratio_den"])
    lots = open_lots(ent["account_id"], event["security_id"])
    sum_frac = util.D(0)
    whole_total = 0
    for lot in lots:
        prior_q = lot["quantity"]
        prior_b = lot["cost_basis_total_cents"]
        exact = util.dec_of(prior_q) * ratio_num / ratio_den
        whole = util.floor_int(exact)
        frac = exact - util.D(whole)
        lot["quantity"] = float(util.D(whole))
        # cost_basis_total_cents unchanged (total basis conserved)
        if whole == 0:
            lot["status"] = "FULLY_SURRENDERED"
        touch(lot)
        add_line(booking["id"], ent["id"], lot["id"], "LOT_MUTATION",
                 q_delta=util.D(whole) - util.dec_of(prior_q),
                 b_delta=0, c_delta=0, prior_q=prior_q, prior_b=prior_b)
        sum_frac += frac
        whole_total += whole
    account_fractional = util.round4_half_up(sum_frac)
    cil = util.policy_round_cents(
        account_fractional * util.D(terms["price_per_share_cents"]),
        terms["fractional_policy"])
    if cil:
        add_line(booking["id"], ent["id"], None, "CASH_IN_LIEU", c_delta=cil)
    ent["booked_whole_shares"] = whole_total
    ent["booked_cash_in_lieu_cents"] = cil


def _book_spin_off(event, booking, ent):
    """SPIN_OFF: basis split percentage rounded 4dp FIRST, per-lot cents SECOND,
    remainder always to the parent lot. Spin-co lots inherit acquisition_date."""
    terms = event["terms"]
    pct = util.round4_half_up(
        util.D(terms["fmv_spin_cents"]) /
        (util.D(terms["fmv_parent_cents"]) + util.D(terms["fmv_spin_cents"])))
    ratio_num = util.D(terms["ratio_num"])
    ratio_den = util.D(terms["ratio_den"])
    lots = open_lots(ent["account_id"], event["security_id"])
    sum_frac = util.D(0)
    whole_total = 0
    for lot in lots:
        prior_q = lot["quantity"]
        prior_b = lot["cost_basis_total_cents"]
        spin_basis = util.round_half_up_cents(util.D(prior_b) * pct)
        parent_kept = prior_b - spin_basis  # exact conservation per lot
        exact_new = util.dec_of(prior_q) * ratio_num / ratio_den
        whole = util.floor_int(exact_new)
        frac = exact_new - util.D(whole)
        lot["cost_basis_total_cents"] = parent_kept
        touch(lot)
        add_line(booking["id"], ent["id"], lot["id"], "LOT_MUTATION",
                 q_delta=0, b_delta=-spin_basis, c_delta=0,
                 prior_q=prior_q, prior_b=prior_b)
        new_lot = create_booked_lot(
            ent["account_id"], terms["spinoff_security_id"], float(util.D(whole)),
            spin_basis, lot["acquisition_date"], booking["id"])
        add_line(booking["id"], ent["id"], new_lot["id"], "LOT_CREATION",
                 q_delta=float(util.D(whole)), b_delta=spin_basis, c_delta=0,
                 prior_q=0, prior_b=0)
        sum_frac += frac
        whole_total += whole
    account_fractional = util.round4_half_up(sum_frac)
    cil = util.policy_round_cents(
        account_fractional * util.D(terms["price_per_share_cents"]),
        terms["fractional_policy"])
    if cil:
        add_line(booking["id"], ent["id"], None, "CASH_IN_LIEU", c_delta=cil)
    ent["booked_whole_shares"] = whole_total
    ent["booked_cash_in_lieu_cents"] = cil


def _book_cash_dividend(event, booking, ent):
    """CASH_DIVIDEND booking mutates no lots; credit the cash amount."""
    if ent["cash_amount_cents"]:
        add_line(booking["id"], ent["id"], None, "CASH_CREDIT",
                 c_delta=ent["cash_amount_cents"])
    ent["booked_whole_shares"] = 0
    ent["booked_cash_in_lieu_cents"] = 0


def _merger_convert_account(event, booking, ent, convert_shares, cash_paid):
    """Mutate the account's old-security lots for a merger leg: cash_shares of
    the position are redeemed, the remainder converts to the new security at
    the event ratio with per-lot floor; fractional remainders cash in lieu at
    terms.cash_per_share_cents rounded half-up."""
    terms = event["terms"]
    ratio = util.D(terms["ratio_num"]) / util.D(terms["ratio_den"])
    cps = util.D(terms["cash_per_share_cents"])
    lots = open_lots(ent["account_id"], event["security_id"])
    total_position = sum((util.dec_of(l["quantity"]) for l in lots), util.D(0))
    cash_shares_total = total_position - util.D(convert_shares)
    if cash_shares_total < 0:
        cash_shares_total = util.D(0)
    sum_frac = util.D(0)
    whole_total = 0
    for lot in lots:
        prior_q = lot["quantity"]
        prior_b = lot["cost_basis_total_cents"]
        lot_qty = util.dec_of(prior_q)
        cash_part = min(lot_qty, cash_shares_total)
        cash_shares_total -= cash_part
        convert_part = lot_qty - cash_part
        exact_new = convert_part * ratio
        whole = util.floor_int(exact_new)
        frac = exact_new - util.D(whole)
        moved_basis = (util.round_half_up_cents(util.D(prior_b) * convert_part / lot_qty)
                       if lot_qty > 0 else 0)
        lot["quantity"] = 0.0
        lot["cost_basis_total_cents"] = prior_b - moved_basis
        lot["status"] = "FULLY_SURRENDERED"
        touch(lot)
        add_line(booking["id"], ent["id"], lot["id"], "LOT_MUTATION",
                 q_delta=-util.dec_of(prior_q), b_delta=-moved_basis, c_delta=0,
                 prior_q=prior_q, prior_b=prior_b)
        if whole > 0 or moved_basis > 0:
            new_lot = create_booked_lot(
                ent["account_id"], terms["new_security_id"], float(util.D(whole)),
                moved_basis, event["payable_date"], booking["id"])
            add_line(booking["id"], ent["id"], new_lot["id"], "LOT_CREATION",
                     q_delta=float(util.D(whole)), b_delta=moved_basis, c_delta=0,
                     prior_q=0, prior_b=0)
        sum_frac += frac
        whole_total += whole
    account_fractional = util.round4_half_up(sum_frac)
    cil = util.round_half_up_cents(account_fractional * cps)
    if cash_paid:
        add_line(booking["id"], ent["id"], None, "CASH_CREDIT", c_delta=cash_paid)
    if cil:
        add_line(booking["id"], ent["id"], None, "CASH_IN_LIEU", c_delta=cil)
    ent["booked_whole_shares"] = whole_total
    ent["booked_cash_in_lieu_cents"] = cil


def _book_merger(event, booking, settled):
    """Voluntary merger waterfall (SCAFFOLD merger_proration_allocation):
    odd-lot CASH in full first, then round-lot CASH prorated by a floored-4dp
    factor; STOCK electors and default_option accounts convert fully."""
    terms = event["terms"]
    cps = terms["cash_per_share_cents"]
    pool = terms["cash_pool_cents"]

    def is_odd(s):
        return util.D(0) < s["shares"] < util.D(ODD_LOT_THRESHOLD)

    odd = [s for s in settled if s["option"] == "CASH" and is_odd(s)]
    roundlot = [s for s in settled if s["option"] == "CASH" and not is_odd(s)]

    def full_cash(s):
        return util.round_half_up_cents(s["shares"] * util.D(cps))

    odd_full_total = sum(full_cash(s) for s in odd)
    if odd_full_total <= pool:
        for s in odd:
            s["cash_paid"] = full_cash(s)
            s["cash_shares"] = s["shares"]
        odd_spent = odd_full_total
    else:
        # odd-lot electors prorated among themselves, shares DESC, tie-break
        # election created_at ASC, so the pool never goes negative
        remaining = pool
        odd.sort(key=lambda s: (
            -s["shares"],
            s["election"]["_seq"] if s["election"] is not None else 0))
        for s in odd:
            pay = min(full_cash(s), remaining)
            s["cash_paid"] = pay
            s["cash_shares"] = (util.D(pay) / util.D(cps)) if cps else util.D(0)
            remaining -= pay
        odd_spent = pool - remaining
    remaining_pool = pool - odd_spent

    roundlot_elected = sum((s["shares"] * util.D(cps) for s in roundlot), util.D(0))
    if roundlot_elected == 0:
        factor = util.D(0)
    else:
        factor = min(util.D(1), util.floor4(util.D(remaining_pool) / roundlot_elected))
    for s in roundlot:
        cash_shares = util.D(util.floor_int(s["shares"] * factor))
        s["cash_shares"] = cash_shares
        s["cash_paid"] = int(cash_shares) * cps

    for s in settled:
        convert = s["shares"] - s.get("cash_shares", util.D(0))
        if convert < 0:
            convert = util.D(0)
        _merger_convert_account(event, booking, s["ent"], convert, s["cash_paid"])


def _book_rights(event, booking, settled):
    """Rights allocation (SCAFFOLD rights_oversubscription_allocation): basic =
    min(requested, entitled); exactly ONE oversubscription pass over the
    remainder; debit allocated * subscription_price_cents."""
    terms = event["terms"]
    price = terms["subscription_price_cents"]
    exercised = 0
    for s in settled:
        s["basic"] = min(s["requested"], s["entitled_rights"])
        exercised += s["basic"]
    remainder = max(0, terms["shares_offered"] - exercised)
    overs = [s for s in settled
             if s["requested"] > s["entitled_rights"] and terms["oversubscription_allowed"]]
    denom = sum(s["entitled_rights"] for s in overs)
    for s in settled:
        over = 0
        if s in overs and denom:
            proportional = util.floor_int(
                util.D(remainder) * util.D(s["entitled_rights"]) / util.D(denom))
            over = min(s["requested"] - s["entitled_rights"], proportional)
        allocated = s["basic"] + over
        debit = allocated * price
        ent = s["ent"]
        if allocated > 0:
            new_lot = create_booked_lot(
                ent["account_id"], event["security_id"], float(allocated), debit,
                event["payable_date"], booking["id"])
            add_line(booking["id"], ent["id"], new_lot["id"], "LOT_CREATION",
                     q_delta=float(allocated), b_delta=debit, c_delta=0,
                     prior_q=0, prior_b=0)
        if debit > 0:
            add_line(booking["id"], ent["id"], None, "CASH_DEBIT", c_delta=-debit)
        ent["booked_whole_shares"] = allocated
        ent["booked_cash_in_lieu_cents"] = 0
        touch(ent)


# ---------------------------------------------------------------------------
# booking entry point
# ---------------------------------------------------------------------------

def run_booking(event, operator_user_id):
    """Full booking cascade (PRD 3.6). Preconditions already validated."""
    booking = {
        "event_id": event["id"],
        "booked_by_user_id": operator_user_id,
        "booked_at": util.now_iso(),
        "total_whole_shares_credited": 0,
        "total_cash_credited_cents": 0,
        "total_cash_in_lieu_cents": 0,
        "status": "POSTED",
    }
    stamp_new(booking)
    db.insert("bookings", booking)

    etype = event["event_type"]
    firm_ents = [e for e in db.all_rows("entitlements")
                 if e["event_id"] == event["id"] and e["status"] == "FIRM"]

    # election resolution: latest SUBMITTED per account -> APPLIED,
    # any WITHDRAWN election -> LAPSED
    applied = {}
    elections = [e for e in db.all_rows("elections") if e["event_id"] == event["id"]]
    by_account = {}
    for el in elections:
        by_account.setdefault(el["account_id"], []).append(el)
    for aid, els in by_account.items():
        submitted = [el for el in els if el["status"] == "SUBMITTED"]
        if submitted:
            latest = max(submitted, key=lambda el: (el["election_seq"], el["_seq"]))
            latest["status"] = "APPLIED"
            touch(latest)
            applied[aid] = latest
        for el in els:
            if el["status"] == "WITHDRAWN":
                el["status"] = "LAPSED"
                touch(el)

    affected_accounts = set()

    if etype in ("MERGER", "RIGHTS_OFFERING"):
        settled = []
        for ent in firm_ents:
            acct = db.get("accounts", ent["account_id"])
            affected_accounts.add(ent["account_id"])
            if acct["status"] != "ACTIVE":
                ent["status"] = "MISSED"
                touch(ent)
                continue
            ent["status"] = "SETTLED"
            touch(ent)
            election = applied.get(ent["account_id"])
            if etype == "MERGER":
                option = election["option_code"] if election else event["terms"]["default_option"]
                settled.append({
                    "ent": ent,
                    "option": option,
                    "shares": util.dec_of(ent["record_position_quantity"]),
                    "election": election,
                    "cash_paid": 0,
                    "cash_shares": util.D(0),
                })
            else:
                settled.append({
                    "ent": ent,
                    "requested": (election["quantity"] or 0) if election else 0,
                    "entitled_rights": ent["entitled_shares"],
                })
        if etype == "MERGER":
            _book_merger(event, booking, settled)
        else:
            _book_rights(event, booking, settled)
    else:
        for ent in firm_ents:
            acct = db.get("accounts", ent["account_id"])
            affected_accounts.add(ent["account_id"])
            if acct["status"] != "ACTIVE":
                ent["status"] = "MISSED"
                touch(ent)
                continue
            ent["status"] = "SETTLED"
            if etype in ("SPLIT", "STOCK_DIVIDEND"):
                _book_split_like(event, booking, ent)
            elif etype == "SPIN_OFF":
                _book_spin_off(event, booking, ent)
            elif etype == "CASH_DIVIDEND":
                _book_cash_dividend(event, booking, ent)
            touch(ent)

    # booking totals
    lines = booking_lines(booking["id"])
    settled_ents = [e for e in db.all_rows("entitlements")
                    if e["event_id"] == event["id"] and e["status"] == "SETTLED"]
    booking["total_whole_shares_credited"] = sum(
        e["booked_whole_shares"] or 0 for e in settled_ents)
    booking["total_cash_credited_cents"] = sum(
        l["cash_delta_cents"] for l in lines if l["line_kind"] == "CASH_CREDIT")
    booking["total_cash_in_lieu_cents"] = sum(
        l["cash_delta_cents"] for l in lines if l["line_kind"] == "CASH_IN_LIEU")

    # derived balances for every affected account
    for aid in affected_accounts:
        recompute_account(aid)

    # auto-resolve OPEN POSITION_MISMATCH breaks whose account/security now
    # matches internal books (PRD 3.6 chain 5)
    for brk in db.all_rows("recon_breaks"):
        if brk["status"] != "OPEN" or brk["break_type"] != "POSITION_MISMATCH":
            continue
        expected = sum((util.dec_of(l["quantity"]) for l in
                        open_lots(brk["account_id"], brk["security_id"])), util.D(0))
        if util.round4_half_up(expected) == util.round4_half_up(brk["reported_quantity"]):
            brk["status"] = "RESOLVED"
            brk["resolution"] = "AUTO_BOOKING"
            touch(brk)

    event["status"] = "BOOKED"
    touch(event)
    return booking


# ---------------------------------------------------------------------------
# booking reversal (PRD 3.7)
# ---------------------------------------------------------------------------

def reverse_booking(booking):
    """Exact restore from recorded prior values; never a recompute."""
    lines = booking_lines(booking["id"])
    event = db.get("events", booking["event_id"])

    booking["status"] = "REVERSED"
    touch(booking)

    affected_accounts = set()
    settled_ent_ids = set()
    for line in lines:
        ent = db.get("entitlements", line["entitlement_id"])
        if ent is not None:
            affected_accounts.add(ent["account_id"])
            if ent["status"] == "SETTLED":
                settled_ent_ids.add(ent["id"])
        if line["line_kind"] == "LOT_MUTATION" and line["position_lot_id"]:
            lot = db.get("position_lots", line["position_lot_id"])
            if lot is not None:
                lot["quantity"] = line["prior_quantity"]
                lot["cost_basis_total_cents"] = line["prior_basis_cents"]
                lot["status"] = "OPEN" if util.dec_of(lot["quantity"]) > 0 else "FULLY_SURRENDERED"
                touch(lot)
        elif line["line_kind"] == "LOT_CREATION" and line["position_lot_id"]:
            lot = db.get("position_lots", line["position_lot_id"])
            if lot is not None:
                lot["quantity"] = 0.0
                lot["status"] = "FULLY_SURRENDERED"
                touch(lot)

    for ent_id in settled_ent_ids:
        ent = db.get("entitlements", ent_id)
        ent["status"] = "FIRM"
        ent["booked_whole_shares"] = None
        ent["booked_cash_in_lieu_cents"] = None
        touch(ent)

    for aid in affected_accounts:
        recompute_account(aid)

    if event is not None and event["status"] == "BOOKED":
        event["status"] = "CONFIRMED"
        touch(event)
