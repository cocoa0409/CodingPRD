"""Minibar dispute window, investigation, resolution branches, and the
waiver net-zero invariant (PRD §3.11).
"""
from __future__ import annotations
import pytest

from test_helpers import (
    ApiErrorId,
    MINIBAR_DISPUTE_WINDOW_HOURS,
    MINUTES_PER_HOUR,
    TEST_USERS,
    dispute_minibar_payload,
    investigate_minibar_payload,
    resolve_minibar_payload,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import (
    advance_clock,
    drive_consumption_to_state,
    list_audit_entries_for_subject,
    post_consumption,
    setup_consumption_in_state,
)


# ===========================================================================
# Dispute window (PRD §3.11)
# ===========================================================================
def test_dispute_inside_window_succeeds(api):
    """PRD §3.11: "A guest dispute is a front-desk action that may only
    be raised while the consumption is POSTED and within a strict
    72-hour window measured from posted_at."

    Claim: a dispute within the window advances to DISPUTED.
    """
    room, items, posted = setup_consumption_in_state(target="POSTED")
    # Stay well inside the 72h window.
    res = api.dispute_minibar_consumption(
        posted["id"],
        dispute_minibar_payload("guest claims not consumed"),
        TEST_USERS["frontdesk_headers"],
    )
    data = validate_success(res)
    assert data["status"] == "DISPUTED"


def test_dispute_at_exactly_72_hours_rejected(api):
    """PRD §3.11: "The window is half-open — strictly less than 72
    hours — so an attempt at exactly 72 hours is rejected with
    ERR_DISPUTE_WINDOW_EXPIRED."
    """
    room, items, posted = setup_consumption_in_state(target="POSTED")
    advance_clock(MINIBAR_DISPUTE_WINDOW_HOURS * MINUTES_PER_HOUR)
    res = api.dispute_minibar_consumption(
        posted["id"],
        dispute_minibar_payload("at exactly 72h"),
        TEST_USERS["frontdesk_headers"],
    )
    validate_error(res, ApiErrorId.ERR_DISPUTE_WINDOW_EXPIRED.value)


def test_dispute_at_72h_minus_one_minute_succeeds(api):
    """PRD §3.11: "an attempt at exactly 72 hours is rejected with
    ERR_DISPUTE_WINDOW_EXPIRED."

    Boundary: 72h - 1 minute is INSIDE the half-open window and must
    succeed.
    """
    room, items, posted = setup_consumption_in_state(target="POSTED")
    advance_clock(
        MINIBAR_DISPUTE_WINDOW_HOURS * MINUTES_PER_HOUR - 1,
    )
    res = api.dispute_minibar_consumption(
        posted["id"],
        dispute_minibar_payload("just inside 72h"),
        TEST_USERS["frontdesk_headers"],
    )
    data = validate_success(res)
    assert data["status"] == "DISPUTED"


def test_dispute_on_pending_consumption_rejected(api):
    """PRD §3.11: "A guest dispute is a front-desk action that may
    only be raised while the consumption is POSTED and within a
    strict 72-hour window measured from posted_at ... an attempt
    outside POSTED is rejected with ERR_CONSUMPTION_NOT_POSTED."

    Claim: a /dispute call while status is PENDING (not POSTED) yields
    ERR_CONSUMPTION_NOT_POSTED — PRD §2.6 evaluates state before
    temporal-window checks, so the state error fires.
    """
    room, items, pending = setup_consumption_in_state(target="PENDING")
    res = api.dispute_minibar_consumption(
        pending["id"],
        dispute_minibar_payload("attempt from PENDING"),
        TEST_USERS["frontdesk_headers"],
    )
    validate_error(res, ApiErrorId.ERR_CONSUMPTION_NOT_POSTED.value)


# ===========================================================================
# Investigation (PRD §3.11)
# ===========================================================================
def test_investigate_advances_disputed_to_investigated(api):
    """PRD §3.11: "A supervisor then opens an investigation by posting
    a finding_note, advancing the record from DISPUTED to
    INVESTIGATED."
    """
    room, items, disputed = setup_consumption_in_state(
        target="DISPUTED",
    )
    res = api.investigate_minibar_consumption(
        disputed["id"],
        investigate_minibar_payload("evidence reviewed"),
        TEST_USERS["supervisor_headers"],
    )
    data = validate_success(res)
    assert data["status"] == "INVESTIGATED"


def test_investigate_non_disputed_rejected(api):
    """PRD §3.11: "attempting to investigate a consumption that is not
    in DISPUTED is rejected with ERR_CONSUMPTION_NOT_DISPUTED."
    """
    room, items, posted = setup_consumption_in_state(target="POSTED")
    res = api.investigate_minibar_consumption(
        posted["id"],
        investigate_minibar_payload("attempt from POSTED"),
        TEST_USERS["supervisor_headers"],
    )
    validate_error(res, ApiErrorId.ERR_CONSUMPTION_NOT_DISPUTED.value)


# ===========================================================================
# Resolution branches (PRD §3.11)
# ===========================================================================
def test_resolve_keep_charge_true_yields_resolved(api):
    """PRD §3.11: "when keep_charge is true the record advances to
    RESOLVED (the folio charge stands) and an audit entry is appended."
    """
    room, items, inv = setup_consumption_in_state(target="INVESTIGATED")
    res = api.resolve_minibar_consumption(
        inv["id"], resolve_minibar_payload(keep_charge=True),
        TEST_USERS["supervisor_headers"],
    )
    data = validate_success(res)
    assert data["status"] == "RESOLVED"


def test_resolve_keep_charge_false_yields_waived(api):
    """PRD §3.11: "when keep_charge is false the record advances to
    WAIVED, the server emits an outbound payment-reverse event
    reversing folio_reference."
    """
    room, items, inv = setup_consumption_in_state(target="INVESTIGATED")
    res = api.resolve_minibar_consumption(
        inv["id"], resolve_minibar_payload(keep_charge=False),
        TEST_USERS["supervisor_headers"],
    )
    data = validate_success(res)
    assert data["status"] == "WAIVED"


# ===========================================================================
# Net-zero waiver invariant (PRD §3.11)
# ===========================================================================
def test_waiver_appends_minibar_consumption_waive_audit(api):
    """PRD §3.11: "and a MINIBAR_CONSUMPTION_WAIVE audit entry is
    appended."
    """
    room, items, inv = setup_consumption_in_state(target="INVESTIGATED")
    res = api.resolve_minibar_consumption(
        inv["id"], resolve_minibar_payload(keep_charge=False),
        TEST_USERS["supervisor_headers"],
    )
    validate_success(res)
    waive_audit = list_audit_entries_for_subject(
        inv["id"], action_type="MINIBAR_CONSUMPTION_WAIVE",
    )
    assert len(waive_audit) >= 1, (
        "PRD §3.11: a waive must append an AuditLog entry with "
        "action_type=MINIBAR_CONSUMPTION_WAIVE."
    )


def test_waiver_net_zero_invariant_two_25c_lines(api):
    """PRD §3.11: "The waiver path preserves a strict invariant: the
    absolute reversal recorded at resolution exactly equals the
    gross_amount_cents plus tax_cents posted on the original
    folio-post action, so a posted-then-waived charge nets to zero on
    the folio."

    Two 25¢ items → gross=50, tax=5, posted=55. After waive, the
    POST + WAIVE audit pair must net to 0.
    """
    from test_helpers.fixtures import setup_consumption_two_25c_items
    room, items, pending = setup_consumption_two_25c_items()
    posted = post_consumption(pending["id"])
    assert posted["posted_amount_cents"] == 55
    waived = drive_consumption_to_state(
        posted, target="WAIVED", keep_charge=False,
    )
    assert waived["status"] == "WAIVED"
    audit = list_audit_entries_for_subject(pending["id"])
    posts = [
        a for a in audit if a["action_type"] == "MINIBAR_CONSUMPTION_POST"
    ]
    waives = [
        a for a in audit if a["action_type"] == "MINIBAR_CONSUMPTION_WAIVE"
    ]
    assert len(posts) == 1 and len(waives) == 1
    post_amt = posts[0]["detail"].get("amount_cents") \
        or posts[0]["detail"].get("posted_amount_cents")
    waive_amt = waives[0]["detail"].get("amount_cents") \
        or waives[0]["detail"].get("posted_amount_cents")
    assert post_amt == 55, (
        f"POST audit detail must record amount_cents=55, got {post_amt}"
    )
    assert waive_amt == 55, (
        "PRD §3.11: 'the absolute reversal recorded at resolution "
        "exactly equals the gross_amount_cents plus tax_cents posted "
        f"on the original folio-post action.' Got waive {waive_amt}."
    )


def test_resolve_non_investigated_rejected(api):
    """PRD §2.6: "state-machine eligibility for the requested
    transition (raising the family of state errors enumerated in §5,
    such as ... ERR_CONSUMPTION_NOT_INVESTIGATED ...)."

    PRD §3.11: "The supervisor resolves the investigation by supplying
    keep_charge." The /resolve endpoint requires INVESTIGATED; a
    DISPUTED record cannot be resolved directly.
    """
    room, items, disp = setup_consumption_in_state(target="DISPUTED")
    res = api.resolve_minibar_consumption(
        disp["id"], resolve_minibar_payload(keep_charge=True),
        TEST_USERS["supervisor_headers"],
    )
    validate_error(res, ApiErrorId.ERR_CONSUMPTION_NOT_INVESTIGATED.value)
