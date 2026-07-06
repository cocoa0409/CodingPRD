"""Transitive cascades: the depth-3 constituent purge and the depth-2 event
cancellation."""
from test_helpers import (
    validate_success,
    sent_referral, open_event_with_registration,
    TEST_USERS,
)

ADMIN = TEST_USERS["office_admin_headers"]
CASEWORKER = TEST_USERS["caseworker_headers"]


# --- Difficulty: transitive_cascade / purge_constituent_depth3_cascade ---

def test_purge_redacts_and_withdraws_open_case(api):
    """PRD §2.10: "the constituent's `full_name`, `email`, and `address` are
    overwritten with the literal string `REDACTED`".
    PRD §3.2: "every one of that constituent's cases whose `status` is any of `NEW`,
    `IN_PROGRESS`, `AWAITING_CONSTITUENT`, or `AWAITING_AGENCY` transitions to
    `WITHDRAWN`, stamping `withdrawn_at` with the current clock value."

    Design: Difficulty/transitive_cascade/purge_constituent_depth3_cascade
    """
    s = sent_referral(api, category="IMMIGRATION")
    con = validate_success(api.purge_constituent(s["con_id"], ADMIN))
    assert con["status"] == "PURGED"
    assert con["full_name"] == "REDACTED", f"full_name must be REDACTED, got {con['full_name']}"
    case = validate_success(api.get_case(s["case_id"], CASEWORKER))
    assert case["status"] == "WITHDRAWN", "the open case must cascade to WITHDRAWN"


def test_purge_recalls_sent_referral_and_decrements_agency(api):
    """PRD §3.2: "every referral of such a case whose `status` is `DRAFT` or `SENT`
    transitions to `RECALLED` with its `closed_reason` set to `RECALLED`. Fourth
    (cascade hop three, driven only by each referral that was `SENT` when recalled),
    that referral's agency has its `open_referral_count` decremented by one".

    Design: Difficulty/transitive_cascade/purge_constituent_depth3_cascade
    """
    s = sent_referral(api, category="IMMIGRATION")
    validate_success(api.purge_constituent(s["con_id"], ADMIN))
    ref = validate_success(api.get_referral(s["ref_id"], CASEWORKER))
    assert ref["status"] == "RECALLED", "the SENT referral must cascade to RECALLED"
    agency = validate_success(api.get_agency(s["agency_id"], ADMIN))
    assert agency["open_referral_count"] == 0, "recalling a SENT referral must decrement the agency ledger to 0"


# --- Difficulty: transitive_cascade / event_cancel_depth2_cascade ---

def test_cancel_event_cancels_registration(api):
    """PRD §3.7: "It sets `lifecycle_status` to `CANCELLED` and `registration_status`
    to `CLOSED`, then cascades: every registration of the event still in `REGISTERED`
    status moves to `CANCELLED`".

    Design: Difficulty/transitive_cascade/event_cancel_depth2_cascade
    """
    s = open_event_with_registration(api, event_capacity=10, venue_capacity=50)
    event = validate_success(api.cancel_event(s["event_id"], ADMIN))
    assert event["lifecycle_status"] == "CANCELLED"
    reg = validate_success(api.get_registration(s["reg_id"], ADMIN))
    assert reg["status"] == "CANCELLED", "the live registration must cascade to CANCELLED"


def test_cancel_event_decrements_counters(api):
    """PRD §3.7: "each such cancellation decrements the event's `registered_count` by
    one and the affected constituent's `upcoming_event_count` by one."

    Design: Difficulty/transitive_cascade/event_cancel_depth2_cascade
    """
    s = open_event_with_registration(api, event_capacity=10, venue_capacity=50)
    validate_success(api.cancel_event(s["event_id"], ADMIN))
    event = validate_success(api.get_event(s["event_id"], ADMIN))
    assert event["registered_count"] == 0, "registered_count must drop to 0"
    con = validate_success(api.get_constituent(s["con_id"], ADMIN))
    assert con["upcoming_event_count"] == 0, "upcoming_event_count must drop to 0"
