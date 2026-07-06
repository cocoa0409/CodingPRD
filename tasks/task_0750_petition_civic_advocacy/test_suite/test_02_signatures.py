"""Signature collection, verification, tallies, milestones, and revocation.

Queue-A depth: signature_tally_official_vs_provisional, goal_reached_ge_boundary_on_verify,
sign_requires_petition_published, signature_count_conserved_on_revoke.
Queue-B breadth: jurisdiction / duplicate / invalid-token / system-fields / derived-count /
verify-idempotency corners.
"""
import pytest
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId,
    register_member, create_draft_petition, set_petition_target,
    publish_petition, submit_petition_under_review,
    sign, sign_and_verify, register_and_sign, register_sign_and_verify,
    TEST_USERS, make_member_headers,
)

MODERATOR = TEST_USERS["moderator_headers"]
GUEST = TEST_USERS["guest_headers"]


# ── dual_variant_calc / signature_tally_official_vs_provisional ──────────────
def _petition_with_one_verified_one_pending(api, goal=5):
    ctx = publish_petition(goal=goal)
    register_sign_and_verify(ctx["petition_id"])   # signer A -> VERIFIED
    register_and_sign(ctx["petition_id"])          # signer B -> PENDING
    return ctx


def test_official_verified_count_excludes_pending_signature(api):
    """PRD §2.7: "On a petition, the official figure is verified_signature_count, the
    number of signatures in VERIFIED status; it drives the goal, the milestone ladder,
    victory eligibility, and the public headline number."

    Design: Difficulty/dual_variant_calc/signature_tally_official_vs_provisional
    """
    ctx = _petition_with_one_verified_one_pending(api)
    pet = get_success_data(api.get_petition(ctx["petition_id"], GUEST))
    assert pet["verified_signature_count"] == 1


def test_provisional_pending_count_reflects_unconfirmed_signature(api):
    """PRD §2.7: "pending_signature_count is the number of signatures still in
    PENDING_VERIFICATION, and a signature that has been created but not yet confirmed
    raises the provisional picture without affecting the official count."

    Design: Difficulty/dual_variant_calc/signature_tally_official_vs_provisional
    """
    ctx = _petition_with_one_verified_one_pending(api)
    pet = get_success_data(api.get_petition(ctx["petition_id"], GUEST))
    assert pet["pending_signature_count"] == 1


# ── boundary_precision_check / goal_reached_ge_boundary_on_verify ────────────
def test_goal_not_reached_below_threshold(api):
    """PRD §3.3: "`goal_reached` is set true exactly when `verified_signature_count` is
    greater than or equal to `goal`."

    Design: Difficulty/boundary_precision_check/goal_reached_ge_boundary_on_verify
    """
    ctx = publish_petition(goal=3)
    register_sign_and_verify(ctx["petition_id"])
    register_sign_and_verify(ctx["petition_id"])
    pet = get_success_data(api.get_petition(ctx["petition_id"], GUEST))
    assert pet["verified_signature_count"] == 2
    assert pet["goal_reached"] is False


def test_goal_reached_and_milestones_at_exact_threshold(api):
    """PRD §3.3: "milestones_reached is recomputed as the subset of milestone_thresholds
    whose threshold is less than or equal to the current verified_signature_count, and
    goal_reached is set true exactly when verified_signature_count is greater than or
    equal to goal."
    PRD §3.3: "the three candidates are 100, the ceiling of goal divided by 2, and goal.
    From these candidates the system keeps only those that are at least 1 and at most the
    goal, removes duplicates, sorts them ascending, and stores the result as
    milestone_thresholds."

    Design: Difficulty/boundary_precision_check/goal_reached_ge_boundary_on_verify
    """
    ctx = publish_petition(goal=3)
    register_sign_and_verify(ctx["petition_id"])
    register_sign_and_verify(ctx["petition_id"])
    register_sign_and_verify(ctx["petition_id"])
    pet = get_success_data(api.get_petition(ctx["petition_id"], GUEST))
    assert pet["verified_signature_count"] == 3
    assert pet["goal_reached"] is True
    assert pet["milestones_reached"] == [2, 3]


# ── cross_entity_state_dependency / sign_requires_petition_published ─────────
def test_sign_under_review_petition_rejected(api):
    """PRD §3.3: "Signing is permitted only while the parent petition's status is
    PUBLISHED; an attempt to sign a petition in any other state is rejected with
    ERR_PETITION_NOT_PUBLISHED."

    Design: Difficulty/cross_entity_state_dependency/sign_requires_petition_published
    """
    ctx = submit_petition_under_review(goal=10)
    signer = register_member()
    resp = api.sign_petition(ctx["petition_id"], {}, make_member_headers(signer["id"]))
    validate_error(resp, ApiErrorId.ERR_PETITION_NOT_PUBLISHED.value, expected_status=409)


def test_sign_draft_petition_rejected(api):
    """PRD §3.3: "Signing is permitted only while the parent petition's status is
    PUBLISHED; an attempt to sign a petition in any other state is rejected with
    ERR_PETITION_NOT_PUBLISHED."

    Design: Difficulty/cross_entity_state_dependency/sign_requires_petition_published
    """
    author = register_member()
    pet = create_draft_petition(author["id"], goal=10)
    signer = register_member()
    resp = api.sign_petition(pet["id"], {}, make_member_headers(signer["id"]))
    validate_error(resp, ApiErrorId.ERR_PETITION_NOT_PUBLISHED.value, expected_status=409)


# ── compensating_invariant / signature_count_conserved_on_revoke ─────────────
def test_revoke_verified_signature_sets_revoked_and_decrements_count(api):
    """PRD §3.3: "Revoking a signature that is already VERIFIED moves it to REVOKED and
    triggers the signature-revoke cascade: the petition's verified_signature_count is
    decreased by 1, and that lower count is then fed back through the goal and milestone
    recomputation."

    Design: Difficulty/compensating_invariant/signature_count_conserved_on_revoke
    """
    ctx = publish_petition(goal=5)
    sig = register_sign_and_verify(ctx["petition_id"])
    revoked = validate_success(api.revoke_signature(sig["id"], {"reason": "fraud"}, MODERATOR))
    assert revoked["status"] == "REVOKED"
    pet = get_success_data(api.get_petition(ctx["petition_id"], GUEST))
    assert pet["verified_signature_count"] == 0


def test_goal_recomputed_false_after_revoke(api):
    """PRD §3.3: "`goal_reached` is set true exactly when `verified_signature_count` is
    greater than or equal to `goal`."

    Design: Difficulty/compensating_invariant/signature_count_conserved_on_revoke
    """
    ctx = publish_petition(goal=5)
    sig = register_sign_and_verify(ctx["petition_id"])
    api.revoke_signature(sig["id"], {"reason": "fraud"}, MODERATOR)
    pet = get_success_data(api.get_petition(ctx["petition_id"], GUEST))
    assert pet["goal_reached"] is False


# ── priority_pair_validation_conflict / state_beats_duplicate_on_sign ────────
def test_sign_removed_petition_with_existing_pending_reports_not_published(api):
    """PRD §3.3: "Signing is permitted only while the parent petition's status is
    PUBLISHED; an attempt to sign a petition in any other state is rejected with
    ERR_PETITION_NOT_PUBLISHED."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_duplicate_on_sign
    """
    ctx = publish_petition(goal=100)
    signer = register_member()
    sign(ctx["petition_id"], signer["id"])   # existing non-terminal PENDING signature
    api.moderate_petition(ctx["petition_id"], {"decision": "REMOVE"}, MODERATOR)
    resp = api.sign_petition(ctx["petition_id"], {}, make_member_headers(signer["id"]))
    validate_error(resp, ApiErrorId.ERR_PETITION_NOT_PUBLISHED.value, expected_status=409)


def test_sign_removed_petition_reports_not_published_in_isolation(api):
    """PRD §3.3: "Signing is permitted only while the parent petition's status is
    PUBLISHED; an attempt to sign a petition in any other state is rejected with
    ERR_PETITION_NOT_PUBLISHED."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_duplicate_on_sign
    """
    ctx = publish_petition(goal=100)
    api.moderate_petition(ctx["petition_id"], {"decision": "REMOVE"}, MODERATOR)
    signer = register_member()
    resp = api.sign_petition(ctx["petition_id"], {}, make_member_headers(signer["id"]))
    validate_error(resp, ApiErrorId.ERR_PETITION_NOT_PUBLISHED.value, expected_status=409)


# ── Corner instances ─────────────────────────────────────────────────────────
def test_signature_created_with_server_status_and_signer(api):
    """PRD §3.3: "A successful sign creates a `Signature` whose `petition_id` names the
    petition and whose `signer_user_id` is set to the acting `X-User-ID`, issues a
    server-minted `verification_token`, sets the signature's `status` to `PENDING_VERIFICATION`,
    and increases the petition's `pending_signature_count` by 1."

    Design: Corner/entities/signature_system_status_ignored_on_create
    """
    ctx = publish_petition(goal=10)
    signer = register_member()
    resp = api.sign_petition(
        ctx["petition_id"], {"public_comment": "hi"}, make_member_headers(signer["id"]))
    data = validate_success(resp, expected_status=201)
    assert data["status"] == "PENDING_VERIFICATION"
    assert data["signer_user_id"] == signer["id"]


def test_sign_with_jurisdiction_mismatch_rejected(api):
    """PRD §3.3: "If the petition carries an eligible_jurisdiction, the signer's
    User.jurisdiction must equal it exactly, or the request is refused with
    ERR_JURISDICTION_MISMATCH."

    Design: Corner/validations/jurisdiction_mismatch_on_sign
    """
    ctx = publish_petition(goal=10, eligible_jurisdiction="US-CA-12")
    signer = register_member(jurisdiction="US-NY-01")
    resp = api.sign_petition(ctx["petition_id"], {}, make_member_headers(signer["id"]))
    validate_error(resp, ApiErrorId.ERR_JURISDICTION_MISMATCH.value, expected_status=422)


def test_verify_with_wrong_token_rejected(api):
    """PRD §3.3: "The signer submits the verification_token; it must equal the token
    issued for that signature or the request fails with ERR_INVALID_VERIFICATION_TOKEN,
    and the parent petition must still be PUBLISHED or the request fails with
    ERR_PETITION_NOT_PUBLISHED."

    Design: Corner/validations/invalid_verification_token_on_verify
    """
    ctx = publish_petition(goal=10)
    sig = register_and_sign(ctx["petition_id"])
    resp = api.verify_signature(
        sig["id"], {"verification_token": "WRONG"}, make_member_headers(sig["_signer_id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_VERIFICATION_TOKEN.value, expected_status=422)


def test_second_signature_by_same_user_rejected(api):
    """PRD §3.3: "A user may hold at most one non-terminal signature — one in
    PENDING_VERIFICATION or VERIFIED — per petition; a second attempt while such a
    signature stands is rejected with ERR_DUPLICATE_SIGNATURE."

    Design: Corner/validations/duplicate_signature_same_user
    """
    ctx = publish_petition(goal=10)
    signer = register_member()
    sign(ctx["petition_id"], signer["id"])
    resp = api.sign_petition(ctx["petition_id"], {}, make_member_headers(signer["id"]))
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_SIGNATURE.value, expected_status=409)


def test_verify_already_verified_signature_rejected(api):
    """PRD §2.5: "the generic legal-state check for the requested transition
    (`ERR_INVALID_STATE`, 409)."

    Design: Corner/state_machines/verify_already_verified_signature_invalid_state
    """
    ctx = publish_petition(goal=10)
    signer = register_member()
    created = sign(ctx["petition_id"], signer["id"])
    token = created["verification_token"]
    validate_success(api.verify_signature(
        created["id"], {"verification_token": token}, make_member_headers(signer["id"])))
    # Re-verify with the same valid token: VERIFIED is not a legal from-state for verify,
    # and the generic legal-state check precedes the token check in the priority order.
    resp = api.verify_signature(
        created["id"], {"verification_token": token}, make_member_headers(signer["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, expected_status=409)


def test_pending_count_increments_on_sign(api):
    """PRD §3.3: "A successful sign creates a `Signature` whose `petition_id` names the
    petition and whose `signer_user_id` is set to the acting `X-User-ID`, issues a
    server-minted `verification_token`, sets the signature's `status` to `PENDING_VERIFICATION`,
    and increases the petition's `pending_signature_count` by 1."

    Design: Corner/cross_cutting_complexity_layers/derived_pending_count_increments_on_sign
    """
    ctx = publish_petition(goal=10)
    register_and_sign(ctx["petition_id"])
    pet = get_success_data(api.get_petition(ctx["petition_id"], GUEST))
    assert pet["pending_signature_count"] == 1
    assert pet["verified_signature_count"] == 0
