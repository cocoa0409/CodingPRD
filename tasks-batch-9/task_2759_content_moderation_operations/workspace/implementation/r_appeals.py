"""Appeals, reinstatement and restoration (PRD §3.7)."""

from flask import Blueprint

import ser
from core import (
    APPEAL_STATUSES, RESOLUTIONS, base_fields, body, created, db, enum_filter,
    fail, listing, now, now_iso, ok, opt_str, paginate_args, parse_iso,
    req_enum, req_str, require, str_filter, touch,
)
from svc import (
    certification_target, content_of, find, recompute_account,
    recompute_reviewer_accuracy, select_reviewer,
)

bp = Blueprint("appeals", __name__)


@bp.post("/appeals")
def file_appeal():
    actor = require("AccountHolder")
    payload = body()
    case_id = req_str(payload, "case_id", 1, None)
    grounds_text = req_str(payload, "grounds_text", 1, 500)

    case = find(db.moderation_cases, case_id, "ERR_CASE_NOT_FOUND")
    content = content_of(case)

    if content["account_id"] != actor.user_id:
        fail("ERR_APPEAL_NOT_OWNED",
             "An account holder may only appeal a decision on their own content.")
    if case["status"] != "DECIDED":
        fail("ERR_CASE_NOT_DECIDED", "Only a decided case can be appealed.")
    for existing in db.appeals.values():
        if existing["case_id"] == case_id:
            fail("ERR_APPEAL_ALREADY_EXISTS", "This case already has an appeal.")
    deadline = parse_iso(case.get("appeal_deadline_at")) if case.get("appeal_deadline_at") else None
    if deadline is not None and now() > deadline:
        fail("ERR_APPEAL_WINDOW_CLOSED", "The appeal window for this case has closed.")
    account = db.accounts[content["account_id"]]
    if int(account["appeal_credits_remaining"]) < 1:
        fail("ERR_APPEAL_CREDITS_EXHAUSTED", "The account holds no appeal credits.")

    record = {
        "case_id": case_id,
        "account_id": content["account_id"],
        "independent_reviewer_id": None,
        "grounds_text": grounds_text,
        "filed_at": now_iso(),
        "resolved_at": None,
        "resolution_note": None,
        "reinstated_content": False,
        "status": "SUBMITTED",
    }
    base_fields(record)
    db.appeals[record["id"]] = record

    account["appeal_credits_remaining"] = int(account["appeal_credits_remaining"]) - 1
    touch(account)

    content["review_status"] = "APPEALED"
    touch(content)

    return created(ser.appeal(record))


@bp.post("/appeals/<appeal_id>/assign-reviewer")
def assign_appeal_reviewer(appeal_id):
    require("QAAuditor")
    payload = body()
    target_reviewer_id = opt_str(payload, "target_reviewer_id", 1, None)

    appeal = find(db.appeals, appeal_id, "ERR_APPEAL_NOT_FOUND")
    target = None
    if target_reviewer_id is not None:
        target = find(db.reviewers, target_reviewer_id, "ERR_REVIEWER_NOT_FOUND")

    case = db.moderation_cases[appeal["case_id"]]
    decider_id = case.get("decided_by_reviewer_id")

    # PRD §2.8 tier 8: segregation of duties precedes the lifecycle check.
    if target is not None and decider_id and target["id"] == decider_id:
        fail("ERR_SEGREGATION_OF_DUTIES",
             "An appeal may not be routed back to the reviewer who decided the case.")

    if appeal["status"] != "SUBMITTED":
        fail("ERR_APPEAL_NOT_UNDER_REVIEW", "Only a SUBMITTED appeal can be routed.")

    exclude = [decider_id] if decider_id else []
    if target is not None:
        if target["status"] != "ACTIVE":
            fail("ERR_REVIEWER_NOT_ACTIVE", "The independent reviewer is not ACTIVE.")
        certification = certification_target(case)
        if certification is None or certification not in (
                target.get("certified_policy_version_ids") or []):
            fail("ERR_REVIEWER_NOT_CERTIFIED",
                 "The independent reviewer is not certified on the governing policy version.")
        if target["role_class"] not in ("SENIOR", "QA"):
            fail("ERR_REVIEWER_NOT_ELIGIBLE_FOR_ESCALATION",
                 "An appeal may only be reviewed by a SENIOR or QA reviewer.")
        chosen = target
    else:
        # Appeal review is off-queue work: no exposure charge is levied.
        chosen = select_reviewer(case, None, 0, exclude, True)
        if chosen is None:
            fail("ERR_NO_ELIGIBLE_REVIEWER",
                 "No independent reviewer satisfies every eligibility predicate.")

    appeal["independent_reviewer_id"] = chosen["id"]
    appeal["status"] = "INDEPENDENT_REVIEW"
    touch(appeal)
    return ok(ser.appeal(appeal))


@bp.post("/appeals/<appeal_id>/resolve")
def resolve_appeal(appeal_id):
    actor = require("Reviewer")
    payload = body()
    resolution = req_enum(payload, "resolution", RESOLUTIONS)
    resolution_note = opt_str(payload, "resolution_note", 0, None)

    appeal = find(db.appeals, appeal_id, "ERR_APPEAL_NOT_FOUND")
    if appeal.get("independent_reviewer_id") != actor.user_id:
        fail("ERR_NOT_APPEAL_REVIEWER",
             "Only the appeal's independent reviewer may resolve it.")
    if appeal["status"] != "INDEPENDENT_REVIEW":
        fail("ERR_APPEAL_NOT_UNDER_REVIEW",
             "Only an appeal under independent review can be resolved.")

    case = db.moderation_cases[appeal["case_id"]]
    content = content_of(case)
    account = db.accounts[content["account_id"]]
    decider = db.reviewers.get(case.get("decided_by_reviewer_id"))

    appeal["resolved_at"] = now_iso()
    appeal["resolution_note"] = resolution_note
    appeal["status"] = resolution

    if resolution == "UPHELD":
        appeal["reinstated_content"] = False
        touch(appeal)
        content["review_status"] = "ACTIONED"
        touch(content)
        # The credit is not refunded: a losing appeal costs a credit.
        recompute_reviewer_accuracy(decider)
    else:
        # Cascade 1: the overturn permanently excludes the case from the ledger.
        case["is_overturned"] = True
        touch(case)
        # Cascade 2: restore the content item.
        if content["visibility_status"] in ("REMOVED", "AGE_GATED"):
            content["visibility_status"] = "REINSTATED"
            content["reinstated_at"] = now_iso()
            appeal["reinstated_content"] = True
        content["review_status"] = "CLEAR"
        touch(content)
        touch(appeal)
        # Cascades 3 and 4: make the author whole, then recompute the posture.
        account["appeal_credits_remaining"] = int(account["appeal_credits_remaining"]) + 1
        recompute_account(account)
        # Cascades 5 and 6: reviewer accuracy, the gate and its case handling.
        recompute_reviewer_accuracy(decider)

    return ok(ser.appeal(appeal))


@bp.get("/appeals/<appeal_id>")
def get_appeal(appeal_id):
    actor = require("TrustSafetyAdmin", "PolicyManager", "QAAuditor", "Reviewer",
                    "LegalCounsel", "AccountHolder")
    record = find(db.appeals, appeal_id, "ERR_APPEAL_NOT_FOUND")
    if actor.role == "AccountHolder" and record["account_id"] != actor.user_id:
        fail("ERR_APPEAL_NOT_OWNED", "An account holder may only read their own appeals.")
    return ok(ser.appeal(record))


@bp.get("/appeals")
def list_appeals():
    actor = require("TrustSafetyAdmin", "PolicyManager", "QAAuditor", "Reviewer",
                    "LegalCounsel", "AccountHolder")
    limit, offset = paginate_args()
    case_id = str_filter("case_id")
    account_id = str_filter("account_id")
    independent_reviewer_id = str_filter("independent_reviewer_id")
    status = enum_filter("status", APPEAL_STATUSES)

    if actor.role == "AccountHolder":
        if account_id is not None and account_id != actor.user_id:
            fail("ERR_APPEAL_NOT_OWNED",
                 "An account holder may only read their own appeals.")
        account_id = actor.user_id

    records = []
    for record in db.appeals.values():
        if case_id is not None and record["case_id"] != case_id:
            continue
        if account_id is not None and record["account_id"] != account_id:
            continue
        if independent_reviewer_id is not None \
                and record["independent_reviewer_id"] != independent_reviewer_id:
            continue
        if status is not None and record["status"] != status:
            continue
        records.append(record)
    return listing(records, limit, offset, ser.appeal)
