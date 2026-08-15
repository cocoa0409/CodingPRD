"""Record lifecycle, aggregate recomputation, and fund exhaustion machinery.

PRD 2.4: every entity carries id / created_at / updated_at / version; version
increments with every modification, including recomputation of a derived
aggregate such as a pool total. PRD 2.10 pins the aggregate definitions.
"""
from db import db
from util import CLOCK, new_id

# AwardLine statuses that reserve pool / count toward offered-packaged totals
# (PRD 2.10).
RESERVING_STATUSES = {"OFFERED", "ACCEPTED", "PARTIALLY_ACCEPTED", "DISBURSING", "DISBURSED"}
# AwardLine statuses that count toward accepted totals (PRD 3.6).
ACCEPTED_STATUSES = {"ACCEPTED", "PARTIALLY_ACCEPTED", "DISBURSING", "DISBURSED"}
LOAN_FUND_CODES = {"SUB", "UNSUB", "PLUS"}


def new_record(collection, fields):
    rec = {
        "id": new_id(),
        "created_at": CLOCK.now_iso(),
        "updated_at": CLOCK.now_iso(),
        "version": 1,
        "_seq": db.next_seq(),
    }
    rec.update(fields)
    getattr(db, collection)[rec["id"]] = rec
    return rec


def touch(rec):
    """Refresh updated_at and bump version (PRD 2.4)."""
    rec["updated_at"] = CLOCK.now_iso()
    rec["version"] += 1


def public(rec):
    if rec is None:
        return None
    return {k: v for k, v in rec.items() if not k.startswith("_")}


def line_reserved_amount(line):
    """A line's contribution to pool_reserved_cents / total_packaged_cents.

    PRD 2.10 defines the reserving status set; the acceptance rules of PRD 3.6
    release (offered - accepted) on partial acceptance, so counted lines past
    acceptance contribute their accepted amount.
    """
    if line["status"] not in RESERVING_STATUSES:
        return 0
    if line["status"] == "OFFERED":
        return line["offered_cents"]
    return line["accepted_cents"]


def recompute_fund_pool_reserved(fund):
    total = 0
    for line in db.award_lines.values():
        if line["fund_type_id"] == fund["id"]:
            total += line_reserved_amount(line)
    if fund["pool_reserved_cents"] != total:
        fund["pool_reserved_cents"] = total
        touch(fund)
    return fund["pool_reserved_cents"]


def apply_fund_exhaustion(fund):
    """PRD 2.10 auto-transitions. A zero pool_budget_cents means the fund has no
    pool constraint: the pool check is skipped during packaging and the fund
    never exhausts. PELL is exempt regardless (entitlement)."""
    if fund["fund_code"] == "PELL":
        return
    if fund["pool_budget_cents"] <= 0:
        return
    if fund["status"] == "ACTIVE" and fund["pool_reserved_cents"] >= fund["pool_budget_cents"]:
        fund["status"] = "EXHAUSTED"
        touch(fund)
    elif fund["status"] == "EXHAUSTED" and fund["pool_reserved_cents"] < fund["pool_budget_cents"]:
        fund["status"] = "ACTIVE"
        touch(fund)


def recompute_package_totals(pkg):
    """total_offered_cents / total_accepted_cents / gift_aid_cents (PRD 3.6).

    total_offered sums offered_cents over the reserving status set;
    total_accepted sums accepted_cents over the accepted status set;
    gift_aid sums offered_cents over reserving lines whose fund is need_based
    and not a loan fund (fund_code not in {SUB, UNSUB, PLUS}).
    """
    offered = 0
    accepted = 0
    gift = 0
    for line in db.award_lines.values():
        if line["package_id"] != pkg["id"]:
            continue
        if line["status"] in RESERVING_STATUSES:
            offered += line["offered_cents"]
            fund = db.fund_types.get(line["fund_type_id"])
            if fund is not None and fund["need_based"] and fund["fund_code"] not in LOAN_FUND_CODES:
                gift += line["offered_cents"]
        if line["status"] in ACCEPTED_STATUSES:
            accepted += line["accepted_cents"]
    changed = (
        pkg["total_offered_cents"] != offered
        or pkg["total_accepted_cents"] != accepted
        or pkg["gift_aid_cents"] != gift
    )
    if changed:
        pkg["total_offered_cents"] = offered
        pkg["total_accepted_cents"] = accepted
        pkg["gift_aid_cents"] = gift
        touch(pkg)
    return changed


def recompute_aid_year_totals(aid_year):
    """Recompute total_packaged_cents from line states (PRD 2.10).

    total_disbursed_cents is maintained incrementally by the disbursement
    post/return handlers: PRD 3.7 requires line-level partial returns to
    subtract return_cents from the aggregate even though the underlying
    disbursement rows remain POSTED with their full amounts, so the aggregate
    is not a pure function of POSTED rows.
    """
    packaged = 0
    for pkg in db.award_packages.values():
        if pkg["aid_year_id"] != aid_year["id"]:
            continue
        for line in db.award_lines.values():
            if line["package_id"] == pkg["id"]:
                packaged += line_reserved_amount(line)
    if aid_year["total_packaged_cents"] != packaged:
        aid_year["total_packaged_cents"] = packaged
        touch(aid_year)
        return True
    return False


def adjust_disbursed_aggregates(line, delta):
    """Incremental ledger for disbursed aggregates (PRD 3.7): the line, its
    fund pool, and the aid-year total move together."""
    line["disbursed_cents"] += delta
    fund = db.fund_types.get(line["fund_type_id"])
    if fund is not None:
        fund["pool_disbursed_cents"] += delta
        touch(fund)
    pkg = db.award_packages.get(line["package_id"])
    if pkg is not None:
        ay = db.aid_years.get(pkg["aid_year_id"])
        if ay is not None:
            ay["total_disbursed_cents"] += delta
            touch(ay)


def recompute_aggregates(aid_year_id):
    """Recompute every fund pool_reserved in the aid year plus the year's
    totals, firing EXHAUSTED auto-transitions in both directions (PRD 2.10)."""
    ay = db.aid_years.get(aid_year_id)
    if ay is None:
        return
    for fund in db.fund_types.values():
        if fund["aid_year_id"] == aid_year_id:
            recompute_fund_pool_reserved(fund)
    for fund in db.fund_types.values():
        if fund["aid_year_id"] == aid_year_id:
            apply_fund_exhaustion(fund)
    recompute_aid_year_totals(ay)


def current_isir(student_id, aid_year_id):
    for rec in db.isir_records.values():
        if (rec["student_id"] == student_id and rec["aid_year_id"] == aid_year_id
                and rec["is_current"]):
            return rec
    return None


def latest_verification_case(student_id, aid_year_id):
    cases = [c for c in db.verification_cases.values()
             if c["student_id"] == student_id and c["aid_year_id"] == aid_year_id]
    if not cases:
        return None
    cases.sort(key=lambda c: c["_seq"])
    return cases[-1]


def package_for(student_id, aid_year_id):
    for pkg in db.award_packages.values():
        if pkg["student_id"] == student_id and pkg["aid_year_id"] == aid_year_id:
            return pkg
    return None


def counted_external_aid(student_id, aid_year_id):
    total = 0
    for row in db.external_aid.values():
        if (row["student_id"] == student_id and row["aid_year_id"] == aid_year_id
                and row["counts_against_coa"]):
            total += row["amount_cents"]
    return total
