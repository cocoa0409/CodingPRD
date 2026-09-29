"""County filings: drafting, submission, adjudication and lien priority (PRD 3.2)."""

from flask import request

from auth import check_judgment_ownership
from domain import (
    JUDGMENT_TERM_YEARS,
    LIVE_FILING_STATES,
    add_years,
    by_seq,
    debtor_of_judgment,
    get_filing,
    get_judgment,
    guard_judgment_alive,
    invalid_state,
    recompute_balances,
    recount_judgment,
    renumber_priority,
    to_date,
)
from errors import ApiError
from store import bump, new_row, store
from validators import (
    ENUM_FILING_OUTCOME,
    ENUM_FILING_TYPE,
    check_enum,
    json_body,
    non_negative,
    pagination,
    present,
    require_date,
    require_int,
    require_state_code,
    require_string,
)
from web import endpoint, make_list

from .helpers import apply_filter, scope, serialize

READ_ROLES = ("CaseManager", "EnforcementOfficer", "ComplianceOfficer", "Creditor")


def _duplicate_live_filing(judgment_id, county_code, filing_type, exclude_id=None):
    for f in store.county_filings.values():
        if exclude_id is not None and f["id"] == exclude_id:
            continue
        if (f["judgment_id"] == judgment_id
                and f["county_code"] == county_code
                and f["filing_type"] == filing_type
                and f["status"] in LIVE_FILING_STATES):
            return True
    return False


def register(app):
    # ---- POST /county-filings --------------------------------------------
    @endpoint(app, "/county-filings", "POST", ("CaseManager",), 201)
    def create_filing(ctx):
        body = json_body()
        judgment = get_judgment(body.get("judgment_id")) if present(body, "judgment_id") else None
        judgment_id = require_string(body, "judgment_id")
        county_code = require_string(body, "county_code")
        state_code = require_state_code(body, "state_code")
        require_string(body, "filing_type")
        fee_cents = require_int(body, "fee_cents")
        filing_type = check_enum(body, "filing_type", ENUM_FILING_TYPE)
        non_negative(fee_cents, "fee_cents")
        guard_judgment_alive(judgment)
        # rung 34 - no live duplicate instrument in the same county
        if _duplicate_live_filing(judgment_id, county_code, filing_type):
            raise ApiError("ERR_DUPLICATE_COUNTY_FILING",
                           "A live filing of this instrument already exists in this county.")
        row = new_row({
            "judgment_id": judgment_id,
            "county_code": county_code,
            "state_code": state_code,
            "filing_type": filing_type,
            "fee_cents": fee_cents,
            "status": "DRAFT",
            "submitted_on": None,
            "recorded_on": None,
            "lien_expires_on": None,
            "priority_rank": None,
            "rejection_count": 0,
            "rejection_reason": None,
        })
        store.county_filings[row["id"]] = row
        return serialize(row)

    # ---- GET /county-filings ---------------------------------------------
    @endpoint(app, "/county-filings", "GET", READ_ROLES, 200)
    def list_filings(ctx):
        limit, offset = pagination(request.args)
        rows = by_seq(list(store.county_filings.values()))
        rows = apply_filter(rows, request.args, "judgment_id")
        rows = apply_filter(rows, request.args, "county_code")
        rows = apply_filter(rows, request.args, "status")
        rows = scope(ctx, rows, lambda r: store.judgments.get(r["judgment_id"]))
        return make_list(rows, limit, offset, serialize)

    # ---- GET /county-filings/{county_filing_id} --------------------------
    @endpoint(app, "/county-filings/<county_filing_id>", "GET", READ_ROLES, 200)
    def read_filing(ctx, county_filing_id):
        filing = get_filing(county_filing_id)
        check_judgment_ownership(ctx, store.judgments.get(filing["judgment_id"]))
        return serialize(filing)

    # ---- POST /county-filings/{county_filing_id}/submit ------------------
    @endpoint(app, "/county-filings/<county_filing_id>/submit", "POST", ("CaseManager",), 200)
    def submit_filing(ctx, county_filing_id):
        filing = get_filing(county_filing_id)
        if filing["status"] not in ("DRAFT", "REJECTED"):
            invalid_state("Only a DRAFT or REJECTED filing may be submitted.")
        judgment = store.judgments.get(filing["judgment_id"])
        guard_judgment_alive(judgment)
        if _duplicate_live_filing(filing["judgment_id"], filing["county_code"],
                                  filing["filing_type"], exclude_id=filing["id"]):
            raise ApiError("ERR_DUPLICATE_COUNTY_FILING",
                           "A live filing of this instrument already exists in this county.")
        filing["status"] = "SUBMITTED"
        filing["submitted_on"] = store.clock_date().isoformat()
        bump(filing)
        return serialize(filing)

    # ---- POST /county-filings/{county_filing_id}/adjudicate --------------
    @endpoint(app, "/county-filings/<county_filing_id>/adjudicate", "POST", ("CaseManager",), 200)
    def adjudicate_filing(ctx, county_filing_id):
        filing = get_filing(county_filing_id)
        body = json_body()
        outcome_raw = require_string(body, "outcome")
        recorded_on = None
        rejection_reason = None
        if outcome_raw == "RECORDED":
            recorded_on = require_date(body, "recorded_on")
        elif outcome_raw == "REJECTED":
            rejection_reason = require_string(body, "rejection_reason")
        outcome = check_enum(body, "outcome", ENUM_FILING_OUTCOME)

        if filing["status"] != "SUBMITTED":
            invalid_state("Only a SUBMITTED filing may be adjudicated.")
        judgment = store.judgments.get(filing["judgment_id"])
        guard_judgment_alive(judgment)

        if outcome == "REJECTED":
            filing["status"] = "REJECTED"
            filing["rejection_count"] += 1
            filing["rejection_reason"] = rejection_reason
            bump(filing)
            return serialize(filing)

        submitted_on = to_date(filing["submitted_on"])
        clock_date = store.clock_date()
        if recorded_on < submitted_on or recorded_on > clock_date:
            raise ApiError("ERR_INVALID_REQUEST",
                           "recorded_on must fall between submitted_on and the current clock date.")

        filing["status"] = "RECORDED"
        filing["recorded_on"] = recorded_on.isoformat()
        filing["lien_expires_on"] = add_years(recorded_on, JUDGMENT_TERM_YEARS).isoformat()
        bump(filing)
        # the whole (county_code, state_code) RECORDED cohort is renumbered
        renumber_priority(filing)

        judgment["_recorded_fees"] += filing["fee_cents"]
        recompute_balances(judgment)
        recount_judgment(judgment)
        debtor = debtor_of_judgment(judgment)
        if (judgment["enforcement_posture"] == "NONE"
                and debtor is not None
                and filing["state_code"] == debtor["state_code"]):
            judgment["enforcement_posture"] = "LIEN_PERFECTED"
        bump(judgment)
        return serialize(filing)
