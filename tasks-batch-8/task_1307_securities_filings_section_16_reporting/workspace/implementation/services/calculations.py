"""Business-logic calculations (SCAFFOLD Table 3 / PRD §3)."""
from datetime import timedelta, date
from decimal import Decimal, ROUND_HALF_UP

from db import db
from utils import advance_bd, add_calendar_months, parse_date, logical_clock_date


# ---------------------------------------------------------------------------
# filing_deadline
# ---------------------------------------------------------------------------

def compute_form4_deadline(earliest_txn_date_str, issuer):
    d = parse_date(earliest_txn_date_str)
    return advance_bd(d, 2, issuer.get("holiday_dates") or []).isoformat()


def compute_form3_deadline(designation_date_str):
    d = parse_date(designation_date_str)
    return (d + timedelta(days=10)).isoformat()


def compute_form5_deadline(fy_end_date_str):
    d = parse_date(fy_end_date_str)
    return (d + timedelta(days=45)).isoformat()


# ---------------------------------------------------------------------------
# cooling_off_end_date
# ---------------------------------------------------------------------------

def compute_cooling_off_end_date(plan, person, issuer):
    adoption = parse_date(plan["adoption_date"])
    base_end = adoption + timedelta(days=90)
    if person.get("is_officer") or person.get("is_director"):
        next_earnings = issuer.get("next_earnings_filing_date")
        if next_earnings:
            earnings_end = advance_bd(
                parse_date(next_earnings), 2, issuer.get("holiday_dates") or []
            )
            extended = max(base_end, earnings_end)
        else:
            extended = base_end
        cap = adoption + timedelta(days=120)
        return min(extended, cap).isoformat()
    return base_end.isoformat()


# ---------------------------------------------------------------------------
# insider_shares_balance
# ---------------------------------------------------------------------------

DIRECTION_BY_CODE = {
    "P": "ACQUIRED",
    "A": "ACQUIRED",
    "M": "ACQUIRED",
    "V": "ACQUIRED",
    "S": "DISPOSED",
    "F": "DISPOSED",
    "G": "DISPOSED",
}


def recompute_balance_chain(person_id, security_type):
    """Recompute shares_owned_after for the (person, security_type) chain."""
    txns = [
        t for t in db.transactions.values()
        if t["reporting_person_id"] == person_id
        and t["security_type"] == security_type
        and t["status"] in ("CONFIRMED", "REPORTED")
    ]
    txns.sort(key=lambda t: (t["transaction_date"], t["created_at"]))
    running = 0
    for t in txns:
        if t.get("direction") == "ACQUIRED":
            running += t["shares"]
        else:
            running -= t["shares"]
        t["shares_owned_after"] = running
    # Null out for INGESTED / VOID
    for t in db.transactions.values():
        if t["reporting_person_id"] == person_id and t["security_type"] == security_type:
            if t["status"] in ("INGESTED", "VOID"):
                t["shares_owned_after"] = None


# ---------------------------------------------------------------------------
# beneficial_ownership_pct
# ---------------------------------------------------------------------------

FILING_THRESHOLD_PCT = Decimal("5.00")
AMENDMENT_DELTA_PCT = Decimal("1.00")


def recompute_holder(holder_id):
    holder = db.beneficial_holders.get(holder_id)
    if not holder:
        return
    issuer = db.issuers.get(holder["issuer_id"])
    if not issuer:
        return

    pcs = [pc for pc in db.position_changes.values() if pc["holder_id"] == holder_id]
    shares = sum(pc["shares_delta"] for pc in pcs)
    deriv = sum(pc["derivative_shares_delta"] for pc in pcs)

    shares_out = issuer["shares_outstanding"]
    holder["shares_beneficially_owned"] = shares
    holder["exercisable_derivative_shares"] = deriv

    current_pct = Decimal(0)
    if shares_out > 0:
        current_pct = (
            Decimal(100) * Decimal(shares) / Decimal(shares_out)
        ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    holder["current_pct"] = float(current_pct)

    fully_diluted = Decimal(0)
    denom = shares_out + deriv
    if denom > 0:
        fully_diluted = (
            Decimal(100) * Decimal(shares + deriv) / Decimal(denom)
        ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    holder["fully_diluted_pct"] = float(fully_diluted)

    # Threshold transitions
    if holder["status"] == "MONITORING" and current_pct >= FILING_THRESHOLD_PCT:
        holder["status"] = "FILING_REQUIRED"
    elif holder["status"] == "FILED" and holder.get("last_reported_pct") is not None:
        last = Decimal(str(holder["last_reported_pct"]))
        if abs(current_pct - last) >= AMENDMENT_DELTA_PCT:
            holder["status"] = "AMENDMENT_REQUIRED"

    holder["updated_at"] = __import__("utils").now_stamp()
    holder["version"] = holder.get("version", 1) + 1


# ---------------------------------------------------------------------------
# short_swing_profit
# ---------------------------------------------------------------------------

def short_swing_analysis(person_id):
    txns = [
        t for t in db.transactions.values()
        if t["reporting_person_id"] == person_id
        and t["transaction_code"] in ("P", "S")
        and t["status"] in ("CONFIRMED", "REPORTED")
    ]
    purchases = [t for t in txns if t["transaction_code"] == "P"]
    sales = [t for t in txns if t["transaction_code"] == "S"]

    def is_matchable(p, s):
        # PRD §3.9: matchable only when the dates lie STRICTLY less than six
        # calendar months apart, in either order; exactly six months apart is
        # not matchable. Both directional checks must hold (AND), so that a
        # pair exactly six months apart — or further — is excluded.
        p_date = parse_date(p["transaction_date"])
        s_date = parse_date(s["transaction_date"])
        return (
            s_date < add_calendar_months(p_date, 6)
            and p_date < add_calendar_months(s_date, 6)
        )

    # --- MAX_RECOVERY ---
    mr_pairs = []
    p_rem = {p["id"]: p["shares"] for p in purchases}
    s_rem = {s["id"]: s["shares"] for s in sales}

    sales_mr = sorted(sales, key=lambda s: (-s["price_per_share"], s["created_at"]))
    for s in sales_mr:
        s_date = parse_date(s["transaction_date"])
        candidates = []
        for p in purchases:
            if p_rem[p["id"]] <= 0:
                continue
            if not is_matchable(p, s):
                continue
            if s["price_per_share"] <= p["price_per_share"]:
                continue
            candidates.append(p)
        # Sort candidates: lowest price first, tie created_at ASC
        candidates.sort(key=lambda p: (p["price_per_share"], p["created_at"]))
        for p in candidates:
            if s_rem[s["id"]] <= 0:
                break
            matched = min(p_rem[p["id"]], s_rem[s["id"]])
            if matched <= 0:
                continue
            profit = Decimal(
                str((s["price_per_share"] - p["price_per_share"]) * matched)
            ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            p_rem[p["id"]] -= matched
            s_rem[s["id"]] -= matched
            mr_pairs.append({
                "purchase_transaction_id": p["id"],
                "sale_transaction_id": s["id"],
                "matched_shares": matched,
                "profit": float(profit),
            })

    mr_total = sum(Decimal(str(p["profit"])) for p in mr_pairs)

    # --- FIFO_CHRONOLOGICAL ---
    fifo_pairs = []
    p_rem2 = {p["id"]: p["shares"] for p in purchases}
    s_rem2 = {s["id"]: s["shares"] for s in sales}

    sales_fifo = sorted(sales, key=lambda s: (s["transaction_date"], s["created_at"]))
    for s in sales_fifo:
        candidates = []
        for p in purchases:
            if p_rem2[p["id"]] <= 0:
                continue
            if not is_matchable(p, s):
                continue
            if s["price_per_share"] <= p["price_per_share"]:
                continue
            candidates.append(p)
        candidates.sort(key=lambda p: (p["transaction_date"], p["created_at"]))
        for p in candidates:
            if s_rem2[s["id"]] <= 0:
                break
            matched = min(p_rem2[p["id"]], s_rem2[s["id"]])
            if matched <= 0:
                continue
            profit = Decimal(
                str((s["price_per_share"] - p["price_per_share"]) * matched)
            ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            p_rem2[p["id"]] -= matched
            s_rem2[s["id"]] -= matched
            fifo_pairs.append({
                "purchase_transaction_id": p["id"],
                "sale_transaction_id": s["id"],
                "matched_shares": matched,
                "profit": float(profit),
            })

    fifo_total = sum(Decimal(str(p["profit"])) for p in fifo_pairs)

    all_pairs = mr_pairs  # for matchable_pair_count we count MR pairs
    return {
        "reporting_person_id": person_id,
        "as_of_date": logical_clock_date().isoformat(),
        "matchable_pair_count": len(all_pairs),
        "short_swing_profit": float(mr_total),
        "short_swing_profit_fifo": float(fifo_total),
        "pairs": all_pairs,
    }


# ---------------------------------------------------------------------------
# annual_sweep
# ---------------------------------------------------------------------------

def run_annual_sweep(sweep):
    issuer = db.issuers[sweep["issuer_id"]]
    fy_end = parse_date(sweep["fy_end_date"])
    fy_start = parse_date(sweep["fy_start_date"])

    persons = [
        p for p in db.reporting_persons.values()
        if p["issuer_id"] == sweep["issuer_id"]
        and p["status"] in ("ACTIVE", "EXITED")
        and p.get("designation_date")
        and parse_date(p["designation_date"]) <= fy_end
        and (p.get("exit_date") is None or parse_date(p["exit_date"]) >= fy_start)
    ]
    persons.sort(key=lambda p: (p["full_name"], p["created_at"]))

    results = []
    for person in persons:
        # late filings in window
        late_count = sum(
            1 for f in db.filings.values()
            if f["reporting_person_id"] == person["id"]
            and f["status"] in ("ACCEPTED", "SUPERSEDED")
            and f.get("is_late")
            and f.get("accepted_at")
            and fy_start <= parse_date(f["accepted_at"][:10]) <= fy_end
        )
        # unreported exempt (gift) transactions
        unreported = [
            t for t in db.transactions.values()
            if t["reporting_person_id"] == person["id"]
            and t["transaction_code"] == "G"
            and t["status"] == "CONFIRMED"
            and t.get("filing_id") is None
            and fy_start <= parse_date(t["transaction_date"]) <= fy_end
        ]
        needs_form5 = len(unreported) > 0
        row = {
            "reporting_person_id": person["id"],
            "late_filing_count": late_count,
            "unreported_exempt_count": len(unreported),
            "needs_form5": needs_form5,
            "delinquent": late_count > 0,
            "form5_filing_id": None,
        }
        if needs_form5:
            filing = {
                "issuer_id": sweep["issuer_id"],
                "reporting_person_id": person["id"],
                "form_type": "FORM_5",
                "amends_filing_id": None,
                "filing_deadline": compute_form5_deadline(sweep["fy_end_date"]),
                "is_late": False,
                "status": "DRAFT",
                "prepared_by_user_id": None,
                "submitted_by_user_id": None,
                "submitted_at": None,
                "accepted_at": None,
                "accession_number": None,
                "rejection_reason": None,
            }
            from utils import stamp_created
            stamp_created(filing)
            db.filings[filing["id"]] = filing
            # Attach transactions
            for t in unreported:
                t["filing_id"] = filing["id"]
            row["form5_filing_id"] = filing["id"]
            # Recompute open_obligation_count
            recompute_open_obligation_count(person["id"])
        results.append(row)

    sweep["results"] = results
    sweep["run_at"] = __import__("utils").now_stamp()
    sweep["status"] = "COMPLETED"


# ---------------------------------------------------------------------------
# open_filing_obligations
# ---------------------------------------------------------------------------

def recompute_open_obligation_count(person_id):
    count = sum(
        1 for f in db.filings.values()
        if f["reporting_person_id"] == person_id
        and f["status"] in ("DRAFT", "READY", "SUBMITTED")
    )
    person = db.reporting_persons.get(person_id)
    if person:
        person["open_obligation_count"] = count
        person["updated_at"] = __import__("utils").now_stamp()
        person["version"] = person.get("version", 1) + 1
