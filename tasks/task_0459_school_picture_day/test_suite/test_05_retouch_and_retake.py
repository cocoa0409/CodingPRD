"""Retouch and retake-day workflow: cost computation (premium comp discount),
credit reservation/release, the retake cascade, the photo retake cycle, and the
session-cancel credit-release cascade (PRD §3.5, §3.9).

Queue A: dual_variant_calc, transitive_cascade, compensating_invariant,
non_linear_state_machine.
Queue B: state_machines, errors, cross_cutting_complexity_layers sections.
"""
import pytest
from test_helpers import (
    validate_success, validate_error,
    create_retouch_order_payload,
    TEST_USERS, make_guardian_headers,
)
from test_helpers.fixtures import (
    create_session, add_student, add_package, capture_photo,
    create_session_capture_open, match_photo_for_student,
    setup_matched_photo_capture_open, create_retouch_requested,
    create_retouch_approved, read_session, create_paid_order,
    create_session_gallery_open_with_matched_student,
)
from test_helpers.api_client import api_client

COORD = TEST_USERS["coordinator_headers"]
PHOTOG = TEST_USERS["photographer_headers"]
CLERK = TEST_USERS["clerk_headers"]


# --------------------------------------------------------------------------- #
# dual_variant_calc / retouch_cost_premium_vs_nonpremium  (queue A)
# --------------------------------------------------------------------------- #
def _setup_premium_and_plain_matched_photos():
    """Session GALLERY_OPEN; student S1 PHOTOGRAPHED with a PAID premium order;
    student S2 PHOTOGRAPHED with no paid premium order. Returns (session, ph1, ph2)."""
    session = create_session(retouch_budget_cents=100000)
    pkg_p = add_package(session["id"], sku="PRM", name="Premium", tier="PREMIUM", base_price_cents=40000)
    add_package(session["id"], sku="BSC", name="Basic", tier="BASIC", base_price_cents=2499)
    s1 = add_student(session["id"], full_name="Sam One", grade="3", homeroom="H1", guardian_user_id="g1")
    s2 = add_student(session["id"], full_name="Sue Two", grade="3", homeroom="H2", guardian_user_id="g2")
    api_client.lock_roster(session["id"], COORD)
    api_client.open_capture(session["id"], PHOTOG)
    ph1 = match_photo_for_student(session["id"], s1)
    ph2 = match_photo_for_student(session["id"], s2)
    api_client.open_gallery(session["id"], COORD)
    # S1 gets a PAID premium order
    create_paid_order(session["id"], s1, pkg_p["id"], quantity=1)
    return session, ph1, ph2


def test_retouch_cost_premium_linked_half_off(api):
    """PRD §3.5: "First, the gross cost, stored as gross_cost_cents, is a base
    retouch fee of 1500 cents plus a per-adjustment fee of 500 cents for each
    adjustment requested."
    PRD §3.5: "Third, the complimentary discount, stored as comp_discount_cents, is
    half of the gross cost rounded half up when premium_linked is true, and zero
    otherwise. Fourth, the net cost, stored as net_cost_cents, is the gross cost
    minus the complimentary discount."

    Design: Difficulty/dual_variant_calc/retouch_cost_premium_vs_nonpremium
    """
    session, ph1, _ph2 = _setup_premium_and_plain_matched_photos()
    res = api.create_retouch_order(create_retouch_order_payload(ph1["id"], kind="RETOUCH", adjustment_count=3), PHOTOG)
    rt = validate_success(res, 201)
    assert rt["premium_linked"] is True
    assert rt["gross_cost_cents"] == 3000
    assert rt["comp_discount_cents"] == 1500
    assert rt["net_cost_cents"] == 1500


def test_retouch_cost_non_premium_full_price(api):
    """PRD §3.5: "Second, the system determines premium_linked: it is true when the
    photo's matched student has a photo order that is PAID and carries a premium
    line — that is, an order whose has_premium_line flag is true because at least
    one of its lines references a PREMIUM-tier package item."
    PRD §3.5: "Third, the complimentary discount, stored as comp_discount_cents, is
    half of the gross cost rounded half up when premium_linked is true, and zero
    otherwise."

    Design: Difficulty/dual_variant_calc/retouch_cost_premium_vs_nonpremium
    """
    session, _ph1, ph2 = _setup_premium_and_plain_matched_photos()
    res = api.create_retouch_order(create_retouch_order_payload(ph2["id"], kind="RETOUCH", adjustment_count=3), PHOTOG)
    rt = validate_success(res, 201)
    assert rt["premium_linked"] is False
    assert rt["net_cost_cents"] == 3000  # gross 3000, no comp discount


# --------------------------------------------------------------------------- #
# transitive_cascade / retake_complete_cascade_depth3  (queue A)
# --------------------------------------------------------------------------- #
def test_retake_complete_cascade_depth3(api):
    """PRD §3.5: "For a RETAKE, completion does more: it drives the linked photo
    RETAKE_REQUESTED → RETAKEN, creates a brand-new replacement photo that is
    MATCHED to the same student and whose retake_of_photo_id points back at the
    photo it supersedes, and records that new photo's id on the retouch order as
    replacement_photo_id."

    Design: Difficulty/transitive_cascade/retake_complete_cascade_depth3
    """
    session, student, package, photo = setup_matched_photo_capture_open(
        budget=50000, student_overrides={"full_name": "Kid X", "grade": "4",
                                         "homeroom": "Q", "guardian_user_id": "g1"})
    rt = create_retouch_approved(photo["id"], kind="RETAKE")  # net 1500 reserved
    completed = validate_success(api.complete_retouch_order(rt["id"], PHOTOG), 200)
    assert completed["status"] == "DONE"
    repl_id = completed["replacement_photo_id"]
    assert repl_id is not None
    orig_after = validate_success(api.get_photo(photo["id"], PHOTOG), 200)
    assert orig_after["status"] == "RETAKEN"
    repl = validate_success(api.get_photo(repl_id, PHOTOG), 200)
    assert repl["status"] == "MATCHED"
    assert repl["retake_of_photo_id"] == photo["id"]


def test_retake_complete_keeps_credit_debited(api):
    """PRD §3.5: "On approval the order advances REQUESTED → APPROVED and the
    session's retouch_credit_balance_cents is decreased by the net cost — the
    credit is reserved."
    PRD §3.5: "Completing an approved order advances it APPROVED → DONE and
    finalizes the already-reserved net cost (it stays debited)"

    Design: Difficulty/transitive_cascade/retake_complete_cascade_depth3
    """
    session, student, package, photo = setup_matched_photo_capture_open(
        budget=50000, student_overrides={"full_name": "Kid X", "grade": "4",
                                         "homeroom": "Q", "guardian_user_id": "g1"})
    rt = create_retouch_approved(photo["id"], kind="RETAKE")  # net 1500 reserved
    api.complete_retouch_order(rt["id"], PHOTOG)
    sess = read_session(session["id"])
    assert sess["retouch_credit_balance_cents"] == 48500  # 50000 - 1500


# --------------------------------------------------------------------------- #
# compensating_invariant / retouch_credit_conserved_on_approve_then_cancel (A)
# --------------------------------------------------------------------------- #
def test_retouch_credit_reserved_on_approve(api):
    """PRD §3.5: "On approval the order advances REQUESTED → APPROVED and the
    session's retouch_credit_balance_cents is decreased by the net cost — the
    credit is reserved."

    Design: Difficulty/compensating_invariant/retouch_credit_conserved_on_approve_then_cancel
    """
    session, student, package, photo = setup_matched_photo_capture_open(
        budget=5000, student_overrides={"full_name": "Kid Z", "grade": "4",
                                        "homeroom": "Q", "guardian_user_id": "g1"})
    create_retouch_approved(photo["id"], kind="RETOUCH", adjustment_count=3)  # net 3000
    sess = read_session(session["id"])
    assert sess["retouch_credit_balance_cents"] == 2000  # 5000 - 3000


def test_retouch_credit_released_on_cancel(api):
    """PRD §3.5: "Cancelling a retouch order is legal while it is REQUESTED or
    APPROVED (otherwise ERR_RETOUCH_NOT_CANCELLABLE); it advances the order to
    CANCELLED, and if the order was already APPROVED it releases the reserved net
    cost back into retouch_credit_balance_cents."

    Design: Difficulty/compensating_invariant/retouch_credit_conserved_on_approve_then_cancel
    """
    session, student, package, photo = setup_matched_photo_capture_open(
        budget=5000, student_overrides={"full_name": "Kid Z", "grade": "4",
                                        "homeroom": "Q", "guardian_user_id": "g1"})
    rt = create_retouch_approved(photo["id"], kind="RETOUCH", adjustment_count=3)  # net 3000
    validate_success(api.cancel_retouch_order(rt["id"], PHOTOG), 200)
    sess = read_session(session["id"])
    assert sess["retouch_credit_balance_cents"] == 5000  # released back to budget


# --------------------------------------------------------------------------- #
# non_linear_state_machine / photo_retake_cycle_back_to_matched  (queue A)
# --------------------------------------------------------------------------- #
def test_photo_enters_retake_requested_on_retake_creation(api):
    """PRD §3.5: "When the kind is RETAKE, creating the request also drives the
    referenced photo MATCHED → RETAKE_REQUESTED; this is only legal while the
    session is in CAPTURE_OPEN or GALLERY_OPEN (otherwise ERR_SESSION_NOT_RETAKEABLE)
    and only while the photo is MATCHED (otherwise ERR_PHOTO_NOT_RETAKEABLE)."

    Design: Difficulty/non_linear_state_machine/photo_retake_cycle_back_to_matched
    """
    session, student, package, photo = setup_matched_photo_capture_open(
        budget=50000, student_overrides={"full_name": "Tom Kid", "grade": "2",
                                         "homeroom": "Z", "guardian_user_id": "g1"})
    create_retouch_requested(photo["id"], kind="RETAKE")
    photo_after = validate_success(api.get_photo(photo["id"], PHOTOG), 200)
    assert photo_after["status"] == "RETAKE_REQUESTED"


def test_photo_cycles_back_to_matched_on_retake_cancel(api):
    """PRD §3.5: "As with rejection, cancelling a RETAKE reverts the linked photo
    RETAKE_REQUESTED → MATCHED."

    Design: Difficulty/non_linear_state_machine/photo_retake_cycle_back_to_matched
    """
    session, student, package, photo = setup_matched_photo_capture_open(
        budget=50000, student_overrides={"full_name": "Tom Kid", "grade": "2",
                                         "homeroom": "Z", "guardian_user_id": "g1"})
    rt = create_retouch_requested(photo["id"], kind="RETAKE")
    cancelled = validate_success(api.cancel_retouch_order(rt["id"], PHOTOG), 200)
    assert cancelled["status"] == "CANCELLED"
    photo_after = validate_success(api.get_photo(photo["id"], PHOTOG), 200)
    assert photo_after["status"] == "MATCHED"


# --------------------------------------------------------------------------- #
# Queue B / state_machines / reject_retake_reverts_photo_to_matched
# --------------------------------------------------------------------------- #
def test_reject_retake_reverts_photo_to_matched(api):
    """PRD §3.5: "Rejecting a retouch order is only legal while it is REQUESTED
    (otherwise ERR_RETOUCH_NOT_REQUESTED); it advances the order REQUESTED →
    REJECTED, and for a RETAKE it reverts the linked photo RETAKE_REQUESTED →
    MATCHED."

    Design: Corner/state_machines/reject_retake_reverts_photo_to_matched
    """
    session, student, package, photo = setup_matched_photo_capture_open(
        budget=50000, student_overrides={"full_name": "Rk Kid", "grade": "1",
                                         "homeroom": "A", "guardian_user_id": "g1"})
    rt = create_retouch_requested(photo["id"], kind="RETAKE")
    rejected = validate_success(api.reject_retouch_order(rt["id"], PHOTOG), 200)
    assert rejected["status"] == "REJECTED"
    photo_after = validate_success(api.get_photo(photo["id"], PHOTOG), 200)
    assert photo_after["status"] == "MATCHED"


# --------------------------------------------------------------------------- #
# Queue B / errors / insufficient_retouch_credit_triggerable
# --------------------------------------------------------------------------- #
def test_insufficient_retouch_credit_on_approve(api):
    """PRD §3.5: "Approving a retouch order requires that its net_cost_cents be no
    greater than the session's current retouch_credit_balance_cents; if the net
    cost would exceed the remaining credit, approval is refused with
    ERR_INSUFFICIENT_RETOUCH_CREDIT (HTTP 402)."

    Design: Corner/errors/insufficient_retouch_credit_triggerable
    """
    session, student, package, photo = setup_matched_photo_capture_open(
        budget=1000, student_overrides={"full_name": "Cr Kid", "grade": "1",
                                        "homeroom": "A", "guardian_user_id": "g1"})
    rt = create_retouch_requested(photo["id"], kind="RETOUCH", adjustment_count=2)  # net 2500
    assert rt["net_cost_cents"] == 2500
    res = api.approve_retouch_order(rt["id"], PHOTOG)
    validate_error(res, "ERR_INSUFFICIENT_RETOUCH_CREDIT", expected_status=402)


# --------------------------------------------------------------------------- #
# Queue B / cross_cutting / session_cancel_releases_retouch_credit_cascade
# --------------------------------------------------------------------------- #
def test_session_cancel_releases_retouch_credit(api):
    """PRD §3.9: "Cancellation is a cascade: every retouch order for the session's
    photos that is in REQUESTED or APPROVED is moved to CANCELLED, and any that
    were APPROVED release their reserved net_cost_cents back into the session's
    retouch_credit_balance_cents"

    Design: Corner/cross_cutting_complexity_layers/session_cancel_releases_retouch_credit_cascade
    """
    session, student, package, photo = setup_matched_photo_capture_open(
        budget=5000, student_overrides={"full_name": "Cn Kid", "grade": "1",
                                        "homeroom": "A", "guardian_user_id": "g1"})
    rt = create_retouch_approved(photo["id"], kind="RETOUCH", adjustment_count=3)  # net 3000
    validate_success(api.cancel_session(session["id"], COORD), 200)
    rt_after = validate_success(api.get_retouch_order(rt["id"], PHOTOG), 200)
    assert rt_after["status"] == "CANCELLED"
    sess = read_session(session["id"])
    assert sess["status"] == "CANCELLED"
    assert sess["retouch_credit_balance_cents"] == 5000  # 3000 released
