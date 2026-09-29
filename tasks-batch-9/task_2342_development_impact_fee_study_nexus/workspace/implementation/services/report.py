"""The statutory annual report (PRD 3.9)."""

from datetime import datetime

import clock
import db
from services import derive
from util import UTC, add_days, add_years, iso_ms


def window(program, fiscal_year):
    start = datetime(int(fiscal_year), program["fiscal_year_start_month"], 1, tzinfo=UTC)
    return start, add_years(start, 1)


def grace_deadline(program, fiscal_year):
    _start, end = window(program, fiscal_year)
    return add_days(end, program["report_grace_days"])


def filing(program_id, fiscal_year):
    return db.annual_reports.get((program_id, int(fiscal_year)))


def expenditure_authorizers(program, fiscal_year):
    """User ids that authorized an EXPENDITURE inside the reported window."""
    start, end = window(program, fiscal_year)
    category_ids = {category["id"] for category in derive.categories_of_program(program["id"])}
    authorizers = set()
    for entry in db.fund_ledger_entries.values():
        if entry["kind"] != "EXPENDITURE":
            continue
        if entry["facility_category_id"] not in category_ids:
            continue
        if start <= entry["created_at"] < end:
            if entry.get("authorized_by_user_id"):
                authorizers.add(entry["authorized_by_user_id"])
    return authorizers


def compute(program, fiscal_year):
    start, end = window(program, fiscal_year)
    categories = []
    totals = {
        "collections_cents": 0,
        "expenditures_cents": 0,
        "refunds_cents": 0,
        "unexpended_cents": 0,
        "refund_obligation_cents": 0,
    }
    earliest_overall = None

    for category in derive.categories_of_program(program["id"]):
        collections = 0
        expenditures = 0
        refunds = 0
        unexpended = 0
        obligation = 0
        earliest = None
        for entry in derive.entries_of_category(category["id"]):
            kind = entry["kind"]
            if kind == "COLLECTION":
                if start <= entry["vintage_at"] < end:
                    collections += entry["amount_cents"]
                if entry["vintage_at"] < end:
                    unexpended += entry.get("unexpended_cents") or 0
                    if entry["entry_status"] == "REFUND_DUE":
                        obligation += entry.get("unexpended_cents") or 0
                    if entry["entry_status"] in derive.ELIGIBLE_ENTRY_STATUSES:
                        deadline = entry.get("deadline_at")
                        if deadline is not None and (earliest is None or deadline < earliest):
                            earliest = deadline
            elif kind == "EXPENDITURE":
                if start <= entry["created_at"] < end:
                    expenditures += entry["amount_cents"]
            elif kind == "REFUND":
                if start <= entry["created_at"] < end:
                    refunds += entry["amount_cents"]

        categories.append({
            "facility_category_id": category["id"],
            "code": category["code"],
            "existing_deficiency_demand_units": float(category["existing_deficiency_demand_units"]),
            "collections_cents": collections,
            "expenditures_cents": expenditures,
            "refunds_cents": refunds,
            "unexpended_cents": unexpended,
            "refund_obligation_cents": obligation,
            "earliest_deadline_at": iso_ms(earliest),
        })
        totals["collections_cents"] += collections
        totals["expenditures_cents"] += expenditures
        totals["refunds_cents"] += refunds
        totals["unexpended_cents"] += unexpended
        totals["refund_obligation_cents"] += obligation
        if earliest is not None and (earliest_overall is None or earliest < earliest_overall):
            earliest_overall = earliest

    record = filing(program["id"], fiscal_year)
    if record is not None:
        filed_late = record["filed_late"]
        report_status = record["report_status"]
    else:
        filed_late = clock.now() > grace_deadline(program, fiscal_year)
        report_status = "UNFILED"

    payload = {
        "fiscal_year": int(fiscal_year),
        "window_start": iso_ms(start),
        "window_end": iso_ms(end),
        "collections_cents": totals["collections_cents"],
        "expenditures_cents": totals["expenditures_cents"],
        "refunds_cents": totals["refunds_cents"],
        "unexpended_cents": totals["unexpended_cents"],
        "refund_obligation_cents": totals["refund_obligation_cents"],
        "earliest_deadline_at": iso_ms(earliest_overall),
        "categories": categories,
        "filed_late": filed_late,
        "report_status": report_status,
    }
    return payload


def file_report(program, fiscal_year, user_id):
    moment = clock.now()
    filed_late = moment > grace_deadline(program, fiscal_year)
    status = "FILED_LATE" if filed_late else "FILED_ON_TIME"
    db.annual_reports[(program["id"], int(fiscal_year))] = {
        "fiscal_year": int(fiscal_year),
        "filed_at": moment,
        "filed_late": filed_late,
        "report_status": status,
        "filed_by_user_id": user_id,
    }
    program["last_report_fiscal_year"] = int(fiscal_year)
    program["last_report_filed_at"] = moment
    program["last_report_filed_by_user_id"] = user_id
    program["last_report_status"] = status
    db.touch(program)

    computed = compute(program, fiscal_year)
    return {
        "fiscal_year": int(fiscal_year),
        "filed_at": iso_ms(moment),
        "filed_late": filed_late,
        "report_status": status,
        "collections_cents": computed["collections_cents"],
        "expenditures_cents": computed["expenditures_cents"],
        "refunds_cents": computed["refunds_cents"],
        "unexpended_cents": computed["unexpended_cents"],
        "refund_obligation_cents": computed["refund_obligation_cents"],
    }
