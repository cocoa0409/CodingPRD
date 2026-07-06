"""Business logic: pricing, scheduling geometry, fulfilment/bubble-up,
invoice assembly, compliance, and account balances. All money is integer cents;
counts and rates are integers so no fractional rounding is ever applied (PRD 2.6).
"""
from datetime import timedelta

from store import (
    db,
    make_entity,
    touch,
    fmt_ts,
    parse_date,
    parse_dt,
    date_to_dt,
    ceil_div,
)
from core import ApiError

AFFIDAVIT_WAIVER_THRESHOLD_CENTS = 3000
WEEK_DAYS = 7


# --------------------------------------------------------------------------
# lookups
# --------------------------------------------------------------------------
def find_statutory(notice_type, county):
    for s in db.statutory.values():
        if s["notice_type"] == notice_type and s["county"] == county:
            return s
    return None


def notice_insertions(notice_id):
    return [i for i in db.insertions.values() if i["notice_id"] == notice_id]


# --------------------------------------------------------------------------
# pricing (calculations.notice_cost, PRD 2.6 / 3.2 / 3.6)
# --------------------------------------------------------------------------
def line_count_for(text, newspaper):
    return ceil_div(len(text), newspaper["chars_per_line"])


def per_insertion_cost(newspaper, notice, sequence_number, line_count):
    if newspaper["pricing_basis"] == "PER_LINE":
        if sequence_number == 1:
            rate = newspaper["line_rate_first_cents"]
        else:
            rate = newspaper["line_rate_subsequent_cents"]
        return line_count * rate
    # PER_WORD: flat across sequence_number, applied to word_count
    return notice["word_count"] * newspaper["word_rate_cents"]


def estimated_cost(newspaper, notice):
    total = 0
    for seq in range(1, notice["required_insertions"] + 1):
        total += per_insertion_cost(newspaper, notice, seq, notice["line_count"])
    return total


def final_cost(newspaper, notice):
    pub = [
        i
        for i in notice_insertions(notice["id"])
        if i["status"] == "PUBLISHED" and not i["is_make_good"]
    ]
    pub.sort(key=lambda i: i["sequence_number"])
    total = 0
    for i in pub:
        total += per_insertion_cost(newspaper, notice, i["sequence_number"], i["line_count_actual"])
    return total


# --------------------------------------------------------------------------
# compliance (calculations.compliance_status, PRD 3.6)
# --------------------------------------------------------------------------
def compute_compliance(notice):
    if notice["insertions_published"] < notice["required_insertions"]:
        return "PENDING"
    published = [i for i in notice_insertions(notice["id"]) if i["status"] == "PUBLISHED"]
    last = max(parse_dt(i["published_date"]) for i in published)
    cutoff = parse_date(notice["deadline_date"]) - timedelta(days=notice["_min_days_before_deadline"])
    if last.date() <= cutoff:
        return "COMPLIANT"
    return "NON_COMPLIANT"


# --------------------------------------------------------------------------
# scheduling geometry (calculations.insertion_schedule, PRD 3.4)
# --------------------------------------------------------------------------
def _blacked_out(d, newspaper):
    for rng in newspaper.get("blackout_dates", []):
        start = parse_date(rng[0])
        end = parse_date(rng[1])
        if start <= d < end:
            return True
    return False


def edition_occupied(newspaper_id, d, exclude_notice_id=None):
    total = 0
    for i in db.insertions.values():
        if i["newspaper_id"] != newspaper_id:
            continue
        if i["status"] not in ("SCHEDULED", "PUBLISHED"):
            continue
        if parse_date(i["scheduled_date"]) != d:
            continue
        if exclude_notice_id is not None and i["notice_id"] == exclude_notice_id:
            continue
        total += db.notices[i["notice_id"]]["line_count"]
    return total


def check_dates_temporal(dates, newspaper, notice, statutory):
    """Weekday, blackout, then deadline checks (PRD 3.4 order)."""
    for d in dates:
        if d.weekday() != newspaper["publication_weekday"]:
            raise ApiError("ERR_INVALID_PUBLICATION_DAY", 422,
                           "an insertion date does not fall on the newspaper's publication weekday")
    for d in dates:
        if _blacked_out(d, newspaper):
            raise ApiError("ERR_BLACKOUT_DATE", 422, "an insertion date falls inside a blackout range")
    cutoff = parse_date(notice["deadline_date"]) - timedelta(days=statutory["min_days_before_deadline"])
    if max(dates) > cutoff:
        raise ApiError("ERR_INSERTION_AFTER_DEADLINE", 422,
                       "the last insertion date is later than the statutory cutoff")


def check_capacity(dates, newspaper, notice, exclude_notice_id=None):
    for d in dates:
        occupied = edition_occupied(newspaper["id"], d, exclude_notice_id=exclude_notice_id)
        if occupied + notice["line_count"] > newspaper["edition_line_capacity"]:
            raise ApiError("ERR_EDITION_CAPACITY_EXCEEDED", 409,
                           "edition line capacity would be exceeded")


def create_insertion(notice, newspaper, d, sequence_number,
                     is_make_good=False, makes_good_insertion_id=None):
    ins = make_entity({
        "notice_id": notice["id"],
        "newspaper_id": newspaper["id"],
        "scheduled_date": d.isoformat(),
        "sequence_number": sequence_number,
        "status": "SCHEDULED",
        "published_date": None,
        "line_count_actual": None,
        "cost_cents": 0,
        "is_make_good": is_make_good,
        "makes_good_insertion_id": makes_good_insertion_id,
    })
    db.insertions[ins["id"]] = ins
    return ins


# --------------------------------------------------------------------------
# fulfilment bubble-up (PRD 3.5 / 3.6)
# --------------------------------------------------------------------------
def on_publish(insertion):
    notice = db.notices[insertion["notice_id"]]
    newspaper = db.newspapers[notice["newspaper_id"]]
    notice["insertions_published"] += 1
    if not insertion["is_make_good"]:
        notice["paid_insertion_count"] += 1
    if notice["insertions_published"] >= notice["required_insertions"]:
        complete_notice(notice, newspaper)
    else:
        notice["status"] = "RUNNING"
        notice["compliance_status"] = compute_compliance(notice)
    touch(notice)


def complete_notice(notice, newspaper):
    notice["final_cost_cents"] = final_cost(newspaper, notice)
    notice["compliance_status"] = compute_compliance(notice)
    notice["status"] = "PUBLISHED"
    _create_affidavit(notice)
    _create_invoice(notice, newspaper)


def _create_affidavit(notice):
    aff = make_entity({
        "notice_id": notice["id"],
        "status": "PENDING",
        "publication_dates": [],
        "sworn_by": None,
        "issued_at": None,
    })
    db.affidavits[aff["id"]] = aff
    return aff


def _create_invoice(notice, newspaper):
    subtotal = notice["final_cost_cents"]
    fee = 0 if subtotal >= AFFIDAVIT_WAIVER_THRESHOLD_CENTS else newspaper["affidavit_fee_cents"]
    total = subtotal + fee
    inv = make_entity({
        "account_id": notice["account_id"],
        "notice_id": notice["id"],
        "status": "DRAFT",
        "subtotal_cents": subtotal,
        "affidavit_fee_cents": fee,
        "total_cents": total,
        "amount_paid_cents": 0,
    })
    db.invoices[inv["id"]] = inv

    pub = [
        i
        for i in notice_insertions(notice["id"])
        if i["status"] == "PUBLISHED" and not i["is_make_good"]
    ]
    pub.sort(key=lambda i: i["sequence_number"])
    count = len(pub)
    for i in pub:
        lc_actual = i["line_count_actual"]
        if newspaper["pricing_basis"] == "PER_LINE":
            rate = (newspaper["line_rate_first_cents"] if i["sequence_number"] == 1
                    else newspaper["line_rate_subsequent_cents"])
            amount = lc_actual * rate
        else:
            rate = newspaper["word_rate_cents"]
            amount = notice["word_count"] * rate
        li = make_entity({
            "invoice_id": inv["id"],
            "insertion_id": i["id"],
            "description": "Insertion %d of %d" % (i["sequence_number"], count),
            "line_count": lc_actual,
            "rate_cents": rate,
            "amount_cents": amount,
        }, light=True)
        db.line_items[li["id"]] = li

    if fee > 0:
        li = make_entity({
            "invoice_id": inv["id"],
            "insertion_id": None,
            "description": "Affidavit of publication fee",
            "line_count": 0,
            "rate_cents": fee,
            "amount_cents": fee,
        }, light=True)
        db.line_items[li["id"]] = li
    return inv


def draft_invoice_of(notice_id):
    for inv in db.invoices.values():
        if inv["notice_id"] == notice_id and inv["status"] == "DRAFT":
            return inv
    return None


def issued_invoice_of(notice_id):
    for inv in db.invoices.values():
        if inv["notice_id"] == notice_id and inv["status"] == "ISSUED":
            return inv
    return None


def issued_or_paid_invoice_of(notice_id):
    for inv in db.invoices.values():
        if inv["notice_id"] == notice_id and inv["status"] in ("ISSUED", "PAID"):
            return inv
    return None


def issued_affidavit_of(notice_id):
    for a in db.affidavits.values():
        if a["notice_id"] == notice_id and a["status"] == "ISSUED":
            return a
    return None


# --------------------------------------------------------------------------
# account balances (calculations.account_balance, PRD 3.7)
# --------------------------------------------------------------------------
def account_balances(account_id):
    # Closed form that reproduces every incremental state-machine delta:
    #   DRAFT->ISSUED: +total; Payment: -amount; ISSUED->VOID: -total.
    # An invoice contributes its total to 'outstanding' while it is ISSUED and
    # keeps contributing once PAID (its payments cancel it to 0); VOID drops it.
    outstanding = 0
    committed_extra = 0
    for inv in db.invoices.values():
        if inv["account_id"] != account_id:
            continue
        if inv["status"] in ("ISSUED", "PAID"):
            outstanding += inv["total_cents"]
        elif inv["status"] == "DRAFT":
            committed_extra += inv["total_cents"]
    paid = sum(p["amount_cents"] for p in db.payments.values() if p["account_id"] == account_id)
    outstanding -= paid
    committed = outstanding + committed_extra
    return outstanding, committed
