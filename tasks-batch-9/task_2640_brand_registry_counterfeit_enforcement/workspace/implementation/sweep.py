"""The operational enforcement sweep - every time-driven rule in the domain,
in a pinned step order, idempotent at a fixed clock."""

import db
import ledger
from versioning import touch

STEP_COUNTS = (
    "lapsed_registration_count",
    "suspended_enrollment_count",
    "withdrawn_takedown_count",
    "expired_counter_notice_count",
    "reinstated_takedown_count",
    "cd_ignored_case_count",
    "expired_recordation_count",
    "escalated_seller_count",
    "blocked_seller_count",
    "deescalated_seller_count",
)


def _release_listing_chain(takedown):
    claim = db.get("claims", takedown["claim_id"])
    if claim is None:
        return
    listing = db.get("listings", claim["listing_id"])
    if listing is None:
        return
    if ledger.release_listing_from_takedown(listing):
        ledger.demote_enforced_claims_on_listing(listing)


def run():
    now = db.now()
    today = now.date()
    counts = dict((name, 0) for name in STEP_COUNTS)

    # ---- STEP 1: lapse expired registrations and suspend what asserts them --
    for registration in db.all_rows("registrations"):
        if registration["status"] != "REGISTERED":
            continue
        if not registration["expiry_date"] < today:
            continue
        registration["status"] = "LAPSED"
        touch(registration)
        counts["lapsed_registration_count"] += 1
        for enrollment in db.all_rows("enrollments"):
            if enrollment["asserted_registration_id"] != registration["id"]:
                continue
            if enrollment["enrollment_status"] != "ACTIVE":
                continue
            withdrawn = ledger.suspend_enrollment(enrollment,
                                                  "REGISTRATION_LAPSED")
            counts["suspended_enrollment_count"] += 1
            counts["withdrawn_takedown_count"] += withdrawn

    # A submitted notice whose enrolment is no longer active is withdrawn too.
    for takedown in db.all_rows("takedowns"):
        if takedown["status"] != "SUBMITTED":
            continue
        enrollment = db.get("enrollments", takedown["enrollment_id"])
        if enrollment is not None and enrollment["enrollment_status"] == "ACTIVE":
            continue
        takedown["status"] = "WITHDRAWN"
        touch(takedown)
        counts["withdrawn_takedown_count"] += 1
        _release_listing_chain(takedown)

    # ---- STEP 2: expire counter notices past their response window ----------
    for notice in db.all_rows("counter_notices"):
        if notice["status"] != "FILED":
            continue
        due = notice["response_due_at"]
        if due is None or not now > due:
            continue
        notice["status"] = "EXPIRED"
        notice["resolved_at"] = due  # the deadline, never the current clock
        touch(notice)
        counts["expired_counter_notice_count"] += 1
        takedown = db.get("takedowns", notice["takedown_id"])
        if takedown is None:
            continue
        if takedown["status"] == "COUNTER_NOTICED":
            takedown["status"] = "REINSTATED"
            touch(takedown)
            counts["reinstated_takedown_count"] += 1
        claim = db.get("claims", takedown["claim_id"])
        listing = db.get("listings", claim["listing_id"]) if claim else None
        if listing is not None and listing["enforcement_status"] == "REMOVED":
            listing["enforcement_status"] = "REINSTATED"
            touch(listing)
        ledger.demote_claim_after_reversal(claim)

    # ---- STEP 3: cease-and-desist letters that went unanswered -------------
    for case in db.all_rows("cases"):
        if case["correspondence_status"] != "CD_SENT":
            continue
        due = case["cd_response_due_at"]
        if due is None or not now > due:
            continue
        case["correspondence_status"] = "CD_IGNORED"
        touch(case)
        counts["cd_ignored_case_count"] += 1

    # ---- STEP 4: expire recordations past their validity interval -----------
    for recordation in db.all_rows("recordations"):
        if recordation["status"] != "RECORDED":
            continue
        if not recordation["expires_on"] < today:
            continue
        recordation["status"] = "EXPIRED"
        touch(recordation)
        counts["expired_recordation_count"] += 1

    # ---- STEPS 5 and 6: decay, auto-block, escalate and de-escalate ---------
    transitions = ledger.recompute_all_sellers()
    for previous, current in transitions.values():
        if current == "BLOCKED":
            counts["blocked_seller_count"] += 1
        elif previous == "ACTIVE" and current == "UNDER_INVESTIGATION":
            counts["escalated_seller_count"] += 1
        if ledger.STATUS_RANK[current] < ledger.STATUS_RANK[previous]:
            counts["deescalated_seller_count"] += 1
    return counts
