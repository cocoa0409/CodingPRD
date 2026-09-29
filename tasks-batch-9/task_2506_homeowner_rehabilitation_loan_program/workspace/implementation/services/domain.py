"""Shared derived values, ledger rollups and multi-hop cascades."""

import db
from services import calc
from services import constants as C

COMMITTED_LOAN_STATUSES = ("LIEN_RECORDED", "DISBURSING", "FULLY_DISBURSED")


# ---------------------------------------------------------------------------
# lookups
# ---------------------------------------------------------------------------


def application_of(row):
    return db.applications.get(row["application_id"])


def program_year_of_application(application):
    return db.program_years.get(application["program_year_id"])


def program_year_of_loan(loan):
    application = db.applications.get(loan["application_id"])
    if application is None:
        return None
    return db.program_years.get(application["program_year_id"])


def loans_of_program_year(program_year_id):
    result = []
    for loan in db.loans.values():
        application = db.applications.get(loan["application_id"])
        if application is not None and application["program_year_id"] == program_year_id:
            result.append(loan)
    return result


def work_items_of(write_up_id):
    return db.ordered(
        [item for item in db.work_items.values() if item["write_up_id"] == write_up_id]
    )


def write_ups_of(application_id):
    return db.ordered(
        [row for row in db.write_ups.values() if row["application_id"] == application_id]
    )


def bids_of(solicitation_id):
    return db.ordered(
        [row for row in db.bids.values() if row["solicitation_id"] == solicitation_id]
    )


def solicitations_of(application_id):
    return db.ordered(
        [row for row in db.solicitations.values() if row["application_id"] == application_id]
    )


def change_orders_of(loan_id):
    return db.ordered(
        [row for row in db.change_orders.values() if row["loan_id"] == loan_id]
    )


def loan_of_application(application_id):
    for loan in db.ordered(list(db.loans.values())):
        if loan["application_id"] == application_id:
            return loan
    return None


def complaints_of_contractor(contractor_id):
    return db.ordered(
        [row for row in db.complaints.values() if row["contractor_id"] == contractor_id]
    )


# ---------------------------------------------------------------------------
# program-year ledger (PRD 2.9)
# ---------------------------------------------------------------------------


def ledger(program_year):
    committed = 0
    disbursed = 0
    for loan in loans_of_program_year(program_year["id"]):
        disbursed += loan["disbursed_cents"]
        if loan["status"] in COMMITTED_LOAN_STATUSES:
            committed += loan["principal_cents"] - loan["disbursed_cents"]
    uncommitted = (
        program_year["allocation_budget_cents"]
        + program_year["program_income_balance_cents"]
        - committed
        - disbursed
    )
    return {
        "committed_amount_cents": committed,
        "disbursed_amount_cents": disbursed,
        "uncommitted_amount_cents": uncommitted,
    }


def program_year_snapshot(program_year):
    """Everything a program year exposes that can move as a side effect."""
    figures = ledger(program_year)
    return (
        program_year["allocation_budget_cents"],
        program_year["program_income_balance_cents"],
        figures["committed_amount_cents"],
        figures["disbursed_amount_cents"],
        figures["uncommitted_amount_cents"],
    )


def touch_program_year(program_year, snapshot):
    """Advance the program year's version only when its ledger actually moved."""
    if program_year is None:
        return
    if program_year_snapshot(program_year) != snapshot:
        db.touch(program_year)


# ---------------------------------------------------------------------------
# write-up rollup
# ---------------------------------------------------------------------------


def recompute_write_up(write_up):
    totals = calc.write_up_totals(work_items_of(write_up["id"]))
    write_up.update(totals)
    return totals


# ---------------------------------------------------------------------------
# contractor derived counters
# ---------------------------------------------------------------------------


def open_complaint_count(contractor):
    return sum(
        1
        for row in db.complaints.values()
        if row["contractor_id"] == contractor["id"]
        and row["status"] in C.OPEN_COMPLAINT_STATUSES
    )


def active_award_count(contractor):
    total = 0
    for solicitation in db.solicitations.values():
        if solicitation["status"] != "AWARDED":
            continue
        award_bid_id = solicitation.get("award_bid_id")
        if not award_bid_id:
            continue
        bid = db.bids.get(award_bid_id)
        if bid is None or bid["contractor_id"] != contractor["id"]:
            continue
        application = db.applications.get(solicitation["application_id"])
        if application is None:
            continue
        if application["workflow_state"] in ("AWARDED", "UNDER_CONSTRUCTION"):
            total += 1
    return total


def performance_score(contractor):
    return calc.performance_score(
        open_complaint_count(contractor),
        contractor["sanction_count"],
        contractor["on_time_completion_count"],
    )


def contractor_snapshot(contractor):
    return (
        contractor["approved_list_status"],
        contractor["sanction_count"],
        contractor["on_time_completion_count"],
        open_complaint_count(contractor),
        performance_score(contractor),
    )


def rescore_contractor(contractor, snapshot):
    """Recompute the score, apply the automatic probation demotion, then bump the
    row's version when anything the row exposes actually moved."""
    if (
        performance_score(contractor) < C.PROBATION_SCORE_THRESHOLD
        and contractor["approved_list_status"] == "APPROVED"
    ):
        contractor["approved_list_status"] = "PROBATION"
    if contractor_snapshot(contractor) != snapshot:
        db.touch(contractor)


# ---------------------------------------------------------------------------
# solicitation counters
# ---------------------------------------------------------------------------


def recompute_solicitation_counts(solicitation):
    rows = bids_of(solicitation["id"])
    solicitation["bid_count"] = sum(
        1 for row in rows if row["status"] in ("SUBMITTED", "RESPONSIVE", "NON_RESPONSIVE")
    )
    solicitation["responsive_bid_count"] = sum(
        1 for row in rows if row["status"] in ("RESPONSIVE", "AWARDED")
    )


# ---------------------------------------------------------------------------
# suspension / reinstatement cascades (PRD 3.9)
# ---------------------------------------------------------------------------


def withdraw_live_bids(contractor):
    """Hops 2-4 of the suspension cascade."""
    affected = {}
    for bid in db.ordered(list(db.bids.values())):
        if bid["contractor_id"] != contractor["id"]:
            continue
        if bid["status"] not in ("SUBMITTED", "RESPONSIVE"):
            continue
        solicitation = db.solicitations.get(bid["solicitation_id"])
        if solicitation is None or solicitation["status"] not in ("OPEN", "TABULATED"):
            continue
        bid["_pre_withdrawal_status"] = bid["status"]
        bid["status"] = "WITHDRAWN_BY_PROGRAM"
        db.touch(bid)
        affected[solicitation["id"]] = solicitation

    newly_failed = []
    for solicitation in db.ordered(list(affected.values())):
        before = (
            solicitation["bid_count"],
            solicitation["responsive_bid_count"],
            solicitation["status"],
        )
        recompute_solicitation_counts(solicitation)
        if (
            solicitation["status"] in ("OPEN", "TABULATED")
            and solicitation["responsive_bid_count"] < solicitation["min_bids_required"]
        ):
            solicitation["status"] = "FAILED"
            newly_failed.append(solicitation)
        after = (
            solicitation["bid_count"],
            solicitation["responsive_bid_count"],
            solicitation["status"],
        )
        if before != after:
            db.touch(solicitation)

    for solicitation in newly_failed:
        application = db.applications.get(solicitation["application_id"])
        if application is not None and application["workflow_state"] == "BID_OPEN":
            application["workflow_state"] = "BID_FAILED"
            db.touch(application)


def restore_withdrawn_bids(contractor):
    """Compensating restoration on reinstatement."""
    affected = {}
    for bid in db.ordered(list(db.bids.values())):
        if bid["contractor_id"] != contractor["id"]:
            continue
        if bid["status"] != "WITHDRAWN_BY_PROGRAM":
            continue
        solicitation = db.solicitations.get(bid["solicitation_id"])
        if solicitation is None or solicitation["status"] not in ("OPEN", "TABULATED", "FAILED"):
            continue
        bid["status"] = bid.get("_pre_withdrawal_status") or "SUBMITTED"
        db.touch(bid)
        affected[solicitation["id"]] = solicitation

    revived = []
    for solicitation in db.ordered(list(affected.values())):
        before = (
            solicitation["bid_count"],
            solicitation["responsive_bid_count"],
            solicitation["status"],
        )
        recompute_solicitation_counts(solicitation)
        if (
            solicitation["status"] == "FAILED"
            and solicitation["responsive_bid_count"] >= solicitation["min_bids_required"]
        ):
            solicitation["status"] = "TABULATED"
            revived.append(solicitation)
        after = (
            solicitation["bid_count"],
            solicitation["responsive_bid_count"],
            solicitation["status"],
        )
        if before != after:
            db.touch(solicitation)

    for solicitation in revived:
        application = db.applications.get(solicitation["application_id"])
        if application is not None and application["workflow_state"] == "BID_FAILED":
            application["workflow_state"] = "BID_OPEN"
            db.touch(application)


# ---------------------------------------------------------------------------
# compliance posture (PRD 3.2)
# ---------------------------------------------------------------------------


def initial_posture(lead_required, historic_required):
    if lead_required and historic_required:
        return "DUAL_HOLD"
    if lead_required:
        return "LEAD_HOLD"
    if historic_required:
        return "HISTORIC_HOLD"
    return "CLEAR"
