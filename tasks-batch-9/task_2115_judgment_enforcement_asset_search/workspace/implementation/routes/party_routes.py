"""Creditors and debtors (PRD 3.1 and 3.3)."""

from auth import ALL_STAFF
from domain import (
    by_seq,
    get_debtor,
    preliminary_score,
    refresh_preliminary,
)
from errors import ApiError
from store import bump, new_row, store
from validators import (
    json_body,
    require_bool,
    require_int,
    require_state_code,
    require_string,
    non_negative,
    positive,
)
from web import endpoint

from .helpers import serialize


def register(app):
    # ---- POST /creditors --------------------------------------------------
    @endpoint(app, "/creditors", "POST", ("CaseManager",), 201)
    def create_creditor(ctx):
        body = json_body()
        name = require_string(body, "name")
        contact_email = require_string(body, "contact_email")
        row = new_row({
            "name": name,
            "contact_email": contact_email,
            "active_judgment_count": 0,
        })
        store.creditors[row["id"]] = row
        return serialize(row)

    # ---- POST /debtors ----------------------------------------------------
    @endpoint(app, "/debtors", "POST", ("CaseManager",), 201)
    def create_debtor(ctx):
        body = json_body()
        full_name = require_string(body, "full_name")
        state_code = require_state_code(body, "state_code")
        head_of_household = require_bool(body, "head_of_household", optional=True, default=False)
        earnings = require_int(body, "weekly_disposable_earnings_cents", optional=True, default=0)
        non_negative(earnings, "weekly_disposable_earnings_cents")
        row = new_row({
            "full_name": full_name,
            "state_code": state_code,
            "head_of_household": head_of_household,
            "weekly_disposable_earnings_cents": earnings,
            "locate_status": "UNLOCATED",
            "last_skip_trace_on": None,
            "skip_trace_count": 0,
            "no_show_count": 0,
            "recoverability_score": 0,
            "certified_recoverability_score": None,
        })
        store.debtors[row["id"]] = row
        row["recoverability_score"] = preliminary_score(row)
        return serialize(row)

    # ---- GET /debtors/{debtor_id} ----------------------------------------
    @endpoint(app, "/debtors/<debtor_id>", "GET", ALL_STAFF + ("Debtor",), 200)
    def read_debtor(ctx, debtor_id):
        debtor = get_debtor(debtor_id)
        if ctx.is_debtor and debtor["id"] != ctx.user_id:
            raise ApiError("ERR_NOT_RESOURCE_OWNER", "Caller may only read their own debtor record.")
        return serialize(debtor)

    # ---- POST /debtors/{debtor_id}/skip-trace ----------------------------
    @endpoint(app, "/debtors/<debtor_id>/skip-trace", "POST", ("AssetInvestigator",), 200)
    def skip_trace(ctx, debtor_id):
        debtor = get_debtor(debtor_id)
        body = json_body()
        # rung 7 - shape
        require_string(body, "vendor")
        located = require_bool(body, "located")
        hits_count = require_int(body, "hits_count")
        current_state_code = require_state_code(body, "current_state_code", optional=True)
        expected_version = require_int(body, "expected_debtor_version")
        # rung 9 - sign constraints
        positive(hits_count, "hits_count")
        # rung 13 - optimistic concurrency on the debtor row
        if expected_version != debtor["version"]:
            raise ApiError("ERR_STALE_DEBTOR_VERSION",
                           "expected_debtor_version does not match the debtor's current version.")

        if located:
            debtor["locate_status"] = "LOCATED"
        else:
            debtor["locate_status"] = "STALE" if debtor["locate_status"] == "LOCATED" else "UNLOCATED"
        if current_state_code is not None:
            debtor["state_code"] = current_state_code

        # a completed trace supersedes earlier skip-trace-sourced findings
        judgment_ids = set(j["id"] for j in store.judgments.values() if j["debtor_id"] == debtor["id"])
        findings = by_seq([f for f in store.asset_findings.values()
                           if f["judgment_id"] in judgment_ids
                           and f["source"] == "SKIP_TRACE"
                           and f["status"] in ("OPEN", "VERIFIED")])
        for finding in findings:
            finding["status"] = "STALE"
            bump(finding)

        debtor["skip_trace_count"] += 1
        debtor["last_skip_trace_on"] = store.clock_date().isoformat()
        refresh_preliminary(debtor)
        bump(debtor)
        return serialize(debtor)
