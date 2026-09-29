"""fund_utilisation_by_basis and apc_fund_waterfall_allocation (PRD 3.3, 3.5)."""
from decimal import Decimal

import constants as C
from clock import clock
from db import db, new_row, set_fields, sort_rows
from errors import ApiError
from services.determination import effective_determination
from util import dec, fiscal_year_of, parse_iso_date, round_half_up

ENCUMBRANCE_INCLUSIVE = "ENCUMBRANCE_INCLUSIVE"
CASH_BASIS = "CASH_BASIS"


# ------------------------------------------------------------- utilisation

def allocations_of_request(fund_request_id):
    rows = [a for a in db.allocations.values() if a["fund_request_id"] == fund_request_id]
    return sorted(rows, key=lambda a: a["sequence_index"])


def _article_of_allocation(allocation):
    request = db.fund_requests.get(allocation["fund_request_id"])
    if request is None:
        return None
    return db.articles.get(request["article_id"])


def utilisation(basis, fiscal_year, author_id=None):
    """fund_utilisation_by_basis; RELEASED lines never count."""
    if basis == CASH_BASIS:
        counted = ("DISBURSED",)
    else:
        counted = ("ENCUMBERED", "DISBURSED")
    total = 0
    for allocation in db.allocations.values():
        fund = db.funds.get(allocation["fund_id"])
        if fund is None or fund["fiscal_year"] != fiscal_year:
            continue
        if allocation["status"] not in counted:
            continue
        if author_id is not None:
            article = _article_of_allocation(allocation)
            if article is None or article["corresponding_author_id"] != author_id:
                continue
        total += allocation["amount_cents"]
    return total


def author_remaining_cap(author, fiscal_year):
    used = utilisation(ENCUMBRANCE_INCLUSIVE, fiscal_year, author_id=author["id"])
    return max(0, author["annual_cap_cents"] - used)


def recompute_author_totals(author_id):
    author = db.authors.get(author_id)
    if author is None:
        return
    fiscal_year = fiscal_year_of(clock.date())
    committed = 0
    for allocation in db.allocations.values():
        if allocation["status"] != "ENCUMBERED":
            continue
        fund = db.funds.get(allocation["fund_id"])
        if fund is None or fund["fiscal_year"] != fiscal_year:
            continue
        article = _article_of_allocation(allocation)
        if article is None or article["corresponding_author_id"] != author_id:
            continue
        committed += allocation["amount_cents"]
    disbursed = utilisation(CASH_BASIS, fiscal_year, author_id=author_id)
    set_fields(author, apc_committed_cents=committed, apc_disbursed_cents=disbursed)


def recompute_author_outputs(author_id):
    """linked_output_count: ingested deposits of that author's articles."""
    author = db.authors.get(author_id)
    if author is None:
        return
    article_ids = set(
        a["id"] for a in db.articles.values() if a["corresponding_author_id"] == author_id
    )
    count = sum(
        1 for d in db.deposits.values()
        if d["article_id"] in article_ids and d["status"] == "INGESTED"
    )
    set_fields(author, linked_output_count=count)


# ------------------------------------------------------------------- funds

def refresh_fund(fund, committed_cents=None, spent_cents=None):
    """Recompute available_cents and apply the auto-freeze threshold."""
    changes = {}
    if committed_cents is not None:
        changes["committed_cents"] = committed_cents
    if spent_cents is not None:
        changes["spent_cents"] = spent_cents
    committed = changes.get("committed_cents", fund["committed_cents"])
    spent = changes.get("spent_cents", fund["spent_cents"])
    changes["available_cents"] = fund["total_budget_cents"] - committed - spent
    threshold = round_half_up(
        dec(fund["total_budget_cents"]) * Decimal(C.FUND_FREEZE_THRESHOLD_PCT)
    )
    if fund["status"] == "OPEN" and committed + spent >= threshold:
        changes["status"] = "FROZEN"
        changes["freeze_reason"] = "AUTO_THRESHOLD"
    set_fields(fund, **changes)


def recompute_fund_ledger(fund_id):
    """Derive committed/spent from the allocation ledger (PRD 2.10)."""
    fund = db.funds.get(fund_id)
    if fund is None:
        return
    committed = 0
    spent = 0
    for allocation in db.allocations.values():
        if allocation["fund_id"] != fund_id:
            continue
        if allocation["status"] == "ENCUMBERED":
            committed += allocation["amount_cents"]
        elif allocation["status"] == "DISBURSED":
            spent += allocation["amount_cents"]
    refresh_fund(fund, committed_cents=committed, spent_cents=spent)


# -------------------------------------------------------------- waterfall

def _candidate_funds(author):
    today = clock.date()
    fiscal_year = fiscal_year_of(today)
    candidates = []
    for fund in db.funds.values():
        if fund["status"] != "OPEN":
            continue
        if fund["fiscal_year"] != fiscal_year:
            continue
        if parse_iso_date(fund["period_from"]) > today:
            continue
        if parse_iso_date(fund["period_to"]) < today:
            continue
        if author["affiliation_status"] not in fund["eligible_affiliation_statuses"]:
            continue
        candidates.append(fund)
    candidates.sort(key=lambda f: (f["priority_rank"], f["created_at"], f["_seq"]))
    return candidates


def run_waterfall(request_row, article, author):
    """apc_fund_waterfall_allocation. Raises before writing anything."""
    fiscal_year = fiscal_year_of(clock.date())
    remaining_cap = author_remaining_cap(author, fiscal_year)
    if remaining_cap == 0:
        raise ApiError("ERR_AUTHOR_CAP_EXHAUSTED", 422)

    determination = effective_determination(article["id"])
    eligible = determination["eligible_request_cents"] if determination else 0
    request_ceiling = min(request_row["requested_cents"], eligible, remaining_cap)

    # ---- dry run: decide the whole plan before mutating any row
    plan = []
    remaining = request_ceiling
    for fund in _candidate_funds(author):
        if remaining == 0:
            break
        available = fund["total_budget_cents"] - fund["committed_cents"] - fund["spent_cents"]
        take = min(remaining, available, fund["per_article_cap_cents"])
        if take <= 0:
            continue
        plan.append((fund, take))
        remaining -= take

    approved_cents = request_ceiling - remaining
    if approved_cents == 0:
        raise ApiError("ERR_NO_FUND_CAPACITY", 409)

    sequence_index = 0
    for fund, take in plan:
        sequence_index += 1
        row = new_row(
            fund_request_id=request_row["id"],
            fund_id=fund["id"],
            amount_cents=take,
            sequence_index=sequence_index,
            status="ENCUMBERED",
            released_reason=None,
        )
        db.allocations[row["id"]] = row
        refresh_fund(fund, committed_cents=fund["committed_cents"] + take)

    return approved_cents


def release_allocations(request_row, released_reason):
    """Compensating transaction for a withdrawal from APPROVED."""
    touched = []
    for allocation in allocations_of_request(request_row["id"]):
        if allocation["status"] != "ENCUMBERED":
            continue
        set_fields(allocation, status="RELEASED", released_reason=released_reason)
        if allocation["fund_id"] not in touched:
            touched.append(allocation["fund_id"])
    for fund_id in touched:
        recompute_fund_ledger(fund_id)


def disburse_allocations(request_row):
    """Payment cascade: ENCUMBERED -> DISBURSED, committed -> spent."""
    touched = []
    for allocation in allocations_of_request(request_row["id"]):
        if allocation["status"] != "ENCUMBERED":
            continue
        set_fields(allocation, status="DISBURSED")
        if allocation["fund_id"] not in touched:
            touched.append(allocation["fund_id"])
    for fund_id in touched:
        recompute_fund_ledger(fund_id)


def approved_request_of_article(article_id):
    rows = [
        r for r in db.fund_requests.values()
        if r["article_id"] == article_id and r["status"] == "APPROVED"
    ]
    return sort_rows(rows)[0] if rows else None
