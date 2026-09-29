"""The epoch advance and the logical clock (PRD 2.10, 2.11)."""

from flask import Blueprint

import clock
import db
from auth import COMPLIANCE_OFFICER, authenticate
from db import store
from response import raw_response
from services import derive
from validation import Field, parse_body, validate

bp = Blueprint("ops", __name__)

CLOCK_FIELDS = [Field("to_iso8601", "datetime")]

TERMINAL_QUOTE_STATES = ("LAPSED", "SUPERSEDED")
LAPSING_SUBMISSION_STATES = ("DRAFT", "SCORED", "QUOTED")


def _expire_policy(policy, touched):
    policy["coverage_status"] = "EXPIRED"
    derive.release_policy(policy, touched)


@bp.post("/dno/ops-runs")
def advance_epoch():
    authenticate(COMPLIANCE_OFFICER)
    parse_body()
    now = clock.now()
    store.epoch += 1
    touched = derive.Touched()

    counters = {
        "activated_policy_count": 0,
        "expired_policy_count": 0,
        "delinquent_policy_count": 0,
        "lapsed_quote_count": 0,
        "expired_submission_count": 0,
        "reverted_submission_count": 0,
        "lapsed_circumstance_report_count": 0,
        "expired_runoff_count": 0,
    }

    for policy in db.ordered(list(store.policies.values())):
        if policy["coverage_status"] == "INCEPTED" and now >= policy["period_start"]:
            policy["coverage_status"] = "ACTIVE"
            counters["activated_policy_count"] += 1
            touched.add(policy)

        if policy["coverage_status"] in ("INCEPTED", "ACTIVE") and now >= policy["period_end"]:
            _expire_policy(policy, touched)
            counters["expired_policy_count"] += 1
        elif (
            policy["coverage_status"] == "RUNOFF"
            and policy["runoff_end_date"] is not None
            and now >= policy["runoff_end_date"]
        ):
            _expire_policy(policy, touched)
            counters["expired_policy_count"] += 1
            for endorsement in derive.endorsements_of(policy["id"]):
                if endorsement["status"] == "ENDORSED":
                    endorsement["status"] = "EXPIRED"
                    counters["expired_runoff_count"] += 1
                    touched.add(endorsement)

        if (
            policy["premium_status"] == "INVOICED"
            and policy["premium_due_date"] is not None
            and now >= policy["premium_due_date"]
        ):
            policy["premium_status"] = "DELINQUENT"
            counters["delinquent_policy_count"] += 1
            touched.add(policy)

    for quote in db.ordered(list(store.quotes.values())):
        if quote["status"] == "OFFERED" and now >= quote["quote_valid_until"]:
            quote["status"] = "LAPSED"
            counters["lapsed_quote_count"] += 1
            touched.add(quote)

    for submission in db.ordered(list(store.submissions.values())):
        if submission["status"] not in LAPSING_SUBMISSION_STATES:
            continue
        if submission["expires_at"] is None or now < submission["expires_at"]:
            continue
        submission["status"] = "EXPIRED"
        counters["expired_submission_count"] += 1
        touched.add(submission)
        for quote in derive.quotes_of(submission["id"]):
            if quote["status"] == "OFFERED":
                quote["status"] = "LAPSED"
                counters["lapsed_quote_count"] += 1
                touched.add(quote)

    for submission in db.ordered(list(store.submissions.values())):
        if submission["status"] != "QUOTED":
            continue
        quotes = derive.quotes_of(submission["id"])
        if quotes and all(q["status"] in TERMINAL_QUOTE_STATES for q in quotes):
            submission["status"] = "SCORED"
            counters["reverted_submission_count"] += 1
            touched.add(submission)

    for report in db.ordered(list(store.circumstance_reports.values())):
        if (
            report["status"] == "REPORTED"
            and report["reporting_deadline"] is not None
            and now >= report["reporting_deadline"]
        ):
            report["status"] = "LAPSED"
            counters["lapsed_circumstance_report_count"] += 1
            touched.add(report)

    touched.flush()
    payload = {"epoch": store.epoch, "current_utc": now}
    payload.update(counters)
    return raw_response(payload)


@bp.post("/_clock/set_current_utc")
def set_clock():
    authenticate(COMPLIANCE_OFFICER)
    values, _ = validate(parse_body(), CLOCK_FIELDS)
    clock.set_now(values["to_iso8601"])
    return raw_response({"current_utc": clock.now()})
