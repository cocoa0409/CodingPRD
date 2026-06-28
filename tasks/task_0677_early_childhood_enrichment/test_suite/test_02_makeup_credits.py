"""Makeup credit ledger: issuance valuation, redemption valuation, residual,
ledger conservation, empty-set rejection, trial exclusion, immutability.
"""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    TEST_USERS, ApiErrorId,
    set_clock, setup_membership_with_credit, setup_enrolled_child,
    create_program, create_room, create_instructor, create_session,
    create_active_membership, create_child, enroll_child, cancel_session,
)
from test_helpers import fixtures as fx

STAFF = TEST_USERS["front_desk_headers"]


def test_redeem_credit_onto_higher_tuition_session_charges_residual(api):
    """PRD §3.7: "The redemption coverage is the smaller of the credit's
    issued_tuition_cents and the target program's tuition_cents — a credit covers
    at most the target level's tuition."
    PRD §3.7: "When the target program's tuition exceeds the credit's snapshotted
    issuance value, the uncovered remainder is owed: the enrollment's
    residual_owed_cents is the larger of 0 and (the target program's tuition_cents
    minus the credit's issued_tuition_cents)."
    PRD §3.7: "Crucially, makeup redemption is exempt from the level-match rule: a
    credit may be applied to a target session of any level the child is
    age-eligible for, even one off the child's current_level."

    Credit issued at 2500 redeemed onto a level-1 session of tuition 3500:
    residual = max(0, 3500-2500) = 1000.

    Design: Difficulty/dual_variant_calc/makeup_credit_issuance_vs_redemption_valuation_credit_domain
    """
    set_clock("2026-05-01T00:00:00Z")
    ctx = setup_membership_with_credit(
        issued_tuition_cents=2500, tier="CORE",
        target_level_index=1, target_tuition_cents=3500,
        target_certified_levels=[0, 1],
    )
    tgt_v = get_success_data(api.get_session(ctx["target_session_id"], STAFF))["version"]
    resp = api.redeem_makeup(
        ctx["source_enrollment"]["id"],
        {"target_session_id": ctx["target_session_id"], "expected_session_version": tgt_v},
        STAFF,
    )
    enrollment = validate_success(resp, 201)
    assert enrollment["status"] == "ENROLLED"
    assert enrollment["residual_owed_cents"] == 1000, (
        f"residual expected 1000 (3500-2500), got {enrollment['residual_owed_cents']}"
    )
    membership = get_success_data(api.get_membership(ctx["membership"]["id"], STAFF))
    assert membership["makeup_credit_balance"] == 0
    target = get_success_data(api.get_session(ctx["target_session_id"], STAFF))
    assert target["enrolled_count"] == 1


def test_redeem_credit_decrements_balance_and_marks_redeemed(api):
    """PRD §3.7: "On a successful redemption the selected credit transitions from
    AVAILABLE to REDEEMED, the membership's makeup_credit_balance is decremented by
    one"

    Companion on the issuance-vs-redemption scenario: after redeeming the one
    AVAILABLE credit, makeup_credit_balance reads 0 and the credit's status is
    REDEEMED in the membership's credit listing.

    Design: Difficulty/dual_variant_calc/makeup_credit_issuance_vs_redemption_valuation_credit_domain
    """
    set_clock("2026-05-01T00:00:00Z")
    ctx = setup_membership_with_credit(
        issued_tuition_cents=2500, tier="CORE",
        target_level_index=1, target_tuition_cents=3500,
        target_certified_levels=[0, 1],
    )
    tgt_v = get_success_data(api.get_session(ctx["target_session_id"], STAFF))["version"]
    validate_success(api.redeem_makeup(
        ctx["source_enrollment"]["id"],
        {"target_session_id": ctx["target_session_id"], "expected_session_version": tgt_v},
        STAFF,
    ), 201)
    membership = get_success_data(api.get_membership(ctx["membership"]["id"], STAFF))
    assert membership["makeup_credit_balance"] == 0
    resp = api.list_membership_makeup_credits(ctx["membership"]["id"], STAFF)
    credits, _meta = validate_paginated(resp)
    assert len(credits) == 1
    assert credits[0]["status"] == "REDEEMED"


def test_credit_issue_then_redeem_balances_ledger(api):
    """PRD §3.7: "On a successful redemption the selected credit transitions from
    AVAILABLE to REDEEMED, the membership's makeup_credit_balance is decremented by
    one, and that membership's version is incremented."
    PRD §3.7: "A new RECURRING enrollment is created ENROLLED on the target
    session, the target session's enrolled_count is incremented by one, and the
    target session's version is incremented."

    Issue (balance 0->1) then redeem (1->0) onto a same-level target session:
    balance reconciles to 0 and the new enrollment is ENROLLED.

    Design: Difficulty/compensating_invariant/credit_conservation_issue_then_redeem_balances_ledger
    """
    set_clock("2026-05-01T00:00:00Z")
    ctx = setup_membership_with_credit(
        issued_tuition_cents=2500, tier="CORE",
        target_level_index=0, target_tuition_cents=2500,
    )
    tgt_v = get_success_data(api.get_session(ctx["target_session_id"], STAFF))["version"]
    resp = api.redeem_makeup(
        ctx["source_enrollment"]["id"],
        {"target_session_id": ctx["target_session_id"], "expected_session_version": tgt_v},
        STAFF,
    )
    enrollment = validate_success(resp, 201)
    assert enrollment["status"] == "ENROLLED"
    membership = get_success_data(api.get_membership(ctx["membership"]["id"], STAFF))
    assert membership["makeup_credit_balance"] == 0, (
        f"balance expected 0 after redeem, got {membership['makeup_credit_balance']}"
    )
    target = get_success_data(api.get_session(ctx["target_session_id"], STAFF))
    assert target["enrolled_count"] == 1


def test_credit_conservation_redeemed_credit_marked_redeemed(api):
    """PRD §3.7: "On a successful redemption the selected credit transitions from
    AVAILABLE to REDEEMED, the membership's makeup_credit_balance is decremented by
    one, and that membership's version is incremented."

    Conserved-quantity companion: after issue (balance 0->1) then redeem (1->0) onto
    a same-level target, the one credit is REDEEMED (no AVAILABLE credit remains).

    Design: Difficulty/compensating_invariant/credit_conservation_issue_then_redeem_balances_ledger
    """
    set_clock("2026-05-01T00:00:00Z")
    ctx = setup_membership_with_credit(
        issued_tuition_cents=2500, tier="CORE",
        target_level_index=0, target_tuition_cents=2500,
    )
    tgt_v = get_success_data(api.get_session(ctx["target_session_id"], STAFF))["version"]
    validate_success(api.redeem_makeup(
        ctx["source_enrollment"]["id"],
        {"target_session_id": ctx["target_session_id"], "expected_session_version": tgt_v},
        STAFF,
    ), 201)
    resp = api.list_membership_makeup_credits(ctx["membership"]["id"], STAFF)
    credits, _meta = validate_paginated(resp)
    available = [c for c in credits if c["status"] == "AVAILABLE"]
    redeemed = [c for c in credits if c["status"] == "REDEEMED"]
    assert len(available) == 0, "no AVAILABLE credit should remain after redeem"
    assert len(redeemed) == 1, "exactly one credit should be REDEEMED"


def test_redeem_with_zero_available_credits_returns_no_credit_available(api):
    """PRD §3.7: "There must be a usable credit at all: if makeup_credit_balance is
    0, or every credit is expired, the redeem is rejected with
    ERR_NO_CREDIT_AVAILABLE (HTTP 409)."

    A membership with zero credits attempting redeem onto a SCHEDULED session is
    rejected with ERR_NO_CREDIT_AVAILABLE.

    Design: Difficulty/boundary_precision_check/zero_available_credits_redeem_endpoint_empty_set
    """
    set_clock("2026-05-01T00:00:00Z")
    program = create_program(level_index=0, tuition_cents=2500)
    room = create_room(physical_capacity=12)
    instructor = create_instructor(certified_level_indices=[0])
    sess_a = create_session(program["id"], room["id"], instructor["id"],
                            start_at="2026-05-10T09:00:00Z", end_at="2026-05-10T10:00:00Z", capacity=5)
    sess_b = create_session(program["id"], room["id"], instructor["id"],
                            start_at="2026-05-17T09:00:00Z", end_at="2026-05-17T10:00:00Z", capacity=5)
    family, membership = create_active_membership(tier="CORE")
    child = create_child(family["id"], birth_date="2024-01-01")
    enr = enroll_child(child["id"], sess_a["id"], membership["id"], kind="RECURRING")
    tgt_v = get_success_data(api.get_session(sess_b["id"], STAFF))["version"]
    resp = api.redeem_makeup(
        enr["id"],
        {"target_session_id": sess_b["id"], "expected_session_version": tgt_v},
        STAFF,
    )
    validate_error(resp, ApiErrorId.ERR_NO_CREDIT_AVAILABLE.value)


def test_zero_available_credits_redeem_does_not_mint_enrollment(api):
    """PRD §3.7: "There must be a usable credit at all: if makeup_credit_balance is
    0, or every credit is expired, the redeem is rejected with
    ERR_NO_CREDIT_AVAILABLE (HTTP 409)."

    Companion: the rejected redeem leaves the target session's enrolled_count at 0
    (no enrollment minted).

    Design: Difficulty/boundary_precision_check/zero_available_credits_redeem_endpoint_empty_set
    """
    set_clock("2026-05-01T00:00:00Z")
    program = create_program(level_index=0, tuition_cents=2500)
    room = create_room(physical_capacity=12)
    instructor = create_instructor(certified_level_indices=[0])
    sess_a = create_session(program["id"], room["id"], instructor["id"],
                            start_at="2026-05-10T09:00:00Z", end_at="2026-05-10T10:00:00Z", capacity=5)
    sess_b = create_session(program["id"], room["id"], instructor["id"],
                            start_at="2026-05-17T09:00:00Z", end_at="2026-05-17T10:00:00Z", capacity=5)
    family, membership = create_active_membership(tier="CORE")
    child = create_child(family["id"], birth_date="2024-01-01")
    enr = enroll_child(child["id"], sess_a["id"], membership["id"], kind="RECURRING")
    tgt_v = get_success_data(api.get_session(sess_b["id"], STAFF))["version"]
    resp = api.redeem_makeup(
        enr["id"],
        {"target_session_id": sess_b["id"], "expected_session_version": tgt_v},
        STAFF,
    )
    validate_error(resp, ApiErrorId.ERR_NO_CREDIT_AVAILABLE.value)
    target = get_success_data(api.get_session(sess_b["id"], STAFF))
    assert target["enrolled_count"] == 0


def test_cancel_session_with_only_trial_enrollment_mints_no_credit(api):
    """PRD §3.3: "TRIAL enrollments are pointedly excluded — a trial never earns a
    makeup credit."
    PRD §3.4: "A TRIAL is a one-off paid trial that never grants makeup credits"

    Cancelling a session whose only enrollment is a TRIAL leaves
    makeup_credit_balance at 0.

    Design: Corner/calculations/trial_enrollment_never_grants_makeup_credit_on_cancel
    """
    set_clock("2026-05-01T00:00:00Z")
    program = create_program(level_index=0, tuition_cents=2500)
    room = create_room(physical_capacity=12)
    instructor = create_instructor(certified_level_indices=[0])
    session = create_session(program["id"], room["id"], instructor["id"], capacity=5)
    family, membership = create_active_membership(tier="CORE")
    child = create_child(family["id"], birth_date="2024-01-01")
    enroll_child(child["id"], session["id"], membership["id"], kind="TRIAL")
    cancelled = validate_success(api.cancel_session(session["id"], STAFF), 200)
    assert cancelled["status"] == "CANCELLED"
    membership_after = get_success_data(api.get_membership(membership["id"], STAFF))
    assert membership_after["makeup_credit_balance"] == 0, (
        f"trial cancel must mint no credit, balance={membership_after['makeup_credit_balance']}"
    )


def test_makeup_credit_listing_exposes_available_credit_from_cancel(api):
    """PRD §2.4: "An AttendanceRecord and a MakeupCredit each carry only an id and
    a created_at; they have no updated_at and no version."
    PRD §3.3: "each EXCUSED record mints exactly one MakeupCredit on that
    enrollment's membership, with issued_tuition_cents snapshotted to this
    cancelled session's program tuition_cents and status AVAILABLE."

    A membership holding one credit from a cancelled session lists exactly one
    AVAILABLE credit.

    Design: Corner/entities/immutable_makeup_credit_has_no_version_field
    """
    set_clock("2026-05-01T00:00:00Z")
    ctx = setup_membership_with_credit(issued_tuition_cents=2500, tier="CORE", target_level_index=0)
    resp = api.list_membership_makeup_credits(ctx["membership"]["id"], STAFF)
    credits, _meta = validate_paginated(resp)
    assert len(credits) == 1, f"expected 1 credit, got {len(credits)}"
    assert credits[0]["status"] == "AVAILABLE"
