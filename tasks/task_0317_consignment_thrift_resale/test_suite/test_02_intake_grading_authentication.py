"""Intake, grading, and the authentication separation-of-duties workflow.

Covers grading-state corner instances, batch/agreement preconditions, the
authentication dispute/reopen cycle, the depth-3 counterfeit cascade, the
cross-entity listing gate, the state-over-auth precedence, and segregation of
duties.
"""
import pytest
from test_helpers import (
    api_client,
    validate_success, validate_error,
    assert_authentication_review, assert_item,
    create_markdown_schedule_payload, create_consignor_payload,
    create_agreement_payload, create_intake_batch_payload, create_item_payload,
    grade_accept_payload, grade_payload, create_authentication_review_payload,
    verdict_payload,
    TEST_USERS,
    make_intake_grader_headers, make_authenticator_headers,
    setup_agreement, setup_graded_item, setup_item_with_open_review,
    setup_graded_auth_item,
)

ADMIN = TEST_USERS["store_admin_headers"]
GRADER = TEST_USERS["intake_grader_headers"]
AUTH = TEST_USERS["authenticator_headers"]
SETTLER = TEST_USERS["settlement_manager_headers"]


# ─── Grading state corner instances ──────────────────────────────────────────

def test_grade_already_graded_item_returns_invalid_state(api):
    """PRD §3.2: "an attempt to grade an item that is not in `PENDING_GRADE` is
    rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/grade_already_graded_item_returns_invalid_state
    """
    _, _, agreement = setup_agreement(consignor_email="rex@x.com")
    _, graded = setup_graded_item(agreement["id"], list_price_cents=5000)
    res = api.grade_item(
        graded["id"], grade_payload("REJECT", graded["version"]), GRADER)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_grade_accept_without_list_price_returns_422(api):
    """PRD §3.2: "Accepting without a `list_price_cents` is rejected with
    `ERR_LIST_PRICE_REQUIRED`."

    Design: Corner/state_machines/grade_accept_without_list_price_returns_422
    """
    _, _, agreement = setup_agreement(consignor_email="lp@x.com")
    batch = validate_success(api.create_intake_batch(
        create_intake_batch_payload(agreement["id"]), GRADER), 201)
    item = validate_success(api.create_item(
        create_item_payload(batch["id"], title="Coat"), GRADER), 201)
    res = api.grade_item(
        item["id"],
        {"decision": "ACCEPT", "expected_item_version": item["version"]}, GRADER)
    validate_error(res, "ERR_LIST_PRICE_REQUIRED", expected_status=422)


def test_list_item_before_accepted_returns_invalid_state(api):
    """PRD §3.4: "Listing requires the item's `grading_status` to be `ACCEPTED` and
    its `listing_status` to be `NOT_LISTED` (or `PULLED`, as below); an attempt to
    list from any other state is rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/list_item_before_accepted_returns_invalid_state
    """
    _, _, agreement = setup_agreement(consignor_email="ls@x.com")
    batch = validate_success(api.create_intake_batch(
        create_intake_batch_payload(agreement["id"]), GRADER), 201)
    item = validate_success(api.create_item(
        create_item_payload(batch["id"], title="Coat"), GRADER), 201)
    res = api.list_item(item["id"], GRADER)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_add_item_to_closed_batch_returns_batch_closed(api):
    """PRD §3.2: "Adding an item to a `CLOSED` batch is rejected with
    `ERR_BATCH_CLOSED`."

    Design: Corner/state_machines/add_item_to_closed_batch_returns_batch_closed
    """
    _, _, agreement = setup_agreement(consignor_email="bc@x.com")
    batch = validate_success(api.create_intake_batch(
        create_intake_batch_payload(agreement["id"]), GRADER), 201)
    validate_success(api.close_intake_batch(batch["id"], GRADER), 200)
    res = api.create_item(create_item_payload(batch["id"], title="Late coat"), GRADER)
    validate_error(res, "ERR_BATCH_CLOSED", expected_status=409)


def test_open_batch_under_terminated_agreement_returns_agreement_terminated(api):
    """PRD §3.2: "the agreement must be `ACTIVE`, and opening a batch under a
    `TERMINATED` agreement is rejected with `ERR_AGREEMENT_TERMINATED`."

    Design: Corner/state_machines/open_batch_under_terminated_agreement_returns_agreement_terminated
    """
    _, _, agreement = setup_agreement(consignor_email="term@x.com")
    validate_success(api.terminate_agreement(agreement["id"], ADMIN), 200)
    res = api.create_intake_batch(create_intake_batch_payload(agreement["id"]), GRADER)
    validate_error(res, "ERR_AGREEMENT_TERMINATED", expected_status=409)


def test_reopen_in_review_returns_invalid_state(api):
    """PRD §3.3: "A dispute is only valid from `IN_REVIEW` and a reopen only from
    `DISPUTED`; either out of turn is rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/reopen_in_review_returns_invalid_state
    """
    _, _, review = setup_item_with_open_review(
        list_price_cents=6000, consignor_email="revroy@x.com")
    res = api.review_reopen(review["id"], make_authenticator_headers("U-AUTH"))
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


# ─── Segregation of duties (corner) ──────────────────────────────────────────

def test_authenticator_cannot_authenticate_item_they_graded(api):
    """PRD §3.3: "the operator who opens or rules on a review must not be the same
    person who graded the item. The server compares the acting `X-User-ID` against
    the item's recorded `graded_by_user_id`, and if they match it rejects the
    action with `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/rbac/authenticator_cannot_authenticate_item_they_graded_segregation
    """
    _, _, agreement = setup_agreement(consignor_email="sod@x.com")
    _, item = setup_graded_item(agreement["id"], list_price_cents=9000,
                                title="Branded", requires_authentication=True,
                                grader_user_id="U-SAME")
    res = api.create_authentication_review(
        create_authentication_review_payload(item["id"]),
        make_authenticator_headers("U-SAME"))
    validate_error(res, "ERR_SEGREGATION_OF_DUTIES", expected_status=403)


# ─── Difficulty: non-linear state machine — dispute/reopen cycle ─────────────

def test_dispute_reopen_two_rounds_dispute_round_is_two(api):
    """PRD §3.3: "an `Authenticator` may then reopen it, advancing it
    `DISPUTED → IN_REVIEW` and incrementing the review's `dispute_round` by one.
    This dispute-and-reopen cycle may repeat any number of rounds before a
    terminal verdict is reached."

    Design: Difficulty/non_linear_state_machine/authentication_review_dispute_reopen_cycle
    """
    _, _, review = setup_item_with_open_review(
        list_price_cents=5000, consignor_email="auth@x.com")
    auth_headers = make_authenticator_headers("U-AUTH")
    validate_success(api.review_dispute(review["id"], SETTLER), 200)
    validate_success(api.review_reopen(review["id"], auth_headers), 200)
    validate_success(api.review_dispute(review["id"], SETTLER), 200)
    final = validate_success(api.review_reopen(review["id"], auth_headers), 200)
    assert final["status"] == "IN_REVIEW", f"expected IN_REVIEW, got {final['status']}"
    assert final["dispute_round"] == 2, f"expected dispute_round 2, got {final['dispute_round']}"


def test_dispute_reopen_single_round_increments_dispute_round(api):
    """PRD §3.3: "an `Authenticator` may then reopen it, advancing it
    `DISPUTED → IN_REVIEW` and incrementing the review's `dispute_round` by one."

    Design: Difficulty/non_linear_state_machine/authentication_review_dispute_reopen_cycle
    """
    _, _, review = setup_item_with_open_review(
        list_price_cents=5000, consignor_email="auth1@x.com")
    assert review["dispute_round"] == 0, "fresh review starts at dispute_round 0"
    validate_success(api.review_dispute(review["id"], SETTLER), 200)
    reopened = validate_success(
        api.review_reopen(review["id"], make_authenticator_headers("U-AUTH")), 200)
    assert reopened["status"] == "IN_REVIEW"
    assert reopened["dispute_round"] == 1, f"expected 1, got {reopened['dispute_round']}"


# ─── Difficulty: transitive cascade — counterfeit verdict depth 3 ────────────

def test_counterfeit_verdict_cascades_status_and_grading(api):
    """PRD §3.3: "A `verdict` of `COUNTERFEIT` advances the review
    `IN_REVIEW → COUNTERFEIT`, sets the item's `authentication_status` to
    `COUNTERFEIT`, and additionally cascades the item's `grading_status` to
    `REJECTED`, because counterfeit goods may never be sold."

    Design: Difficulty/transitive_cascade/counterfeit_verdict_cascade_depth3
    """
    _, item, review = setup_item_with_open_review(
        list_price_cents=30000, consignor_email="fake@x.com")
    ruled = validate_success(api.review_verdict(
        review["id"], verdict_payload("COUNTERFEIT", verdict_note="stitching off"),
        make_authenticator_headers("U-AUTH")), 200)
    assert ruled["status"] == "COUNTERFEIT"
    after = validate_success(api.get_item(item["id"], GRADER), 200)
    assert after["authentication_status"] == "COUNTERFEIT"
    assert after["grading_status"] == "REJECTED"


def test_counterfeit_then_list_attempt_is_rejected(api):
    """PRD §3.4: "An item still `PENDING_AUTH` or found `COUNTERFEIT` cannot be
    listed, and the attempt is rejected with `ERR_AUTHENTICATION_REQUIRED`."

    Design: Difficulty/transitive_cascade/counterfeit_verdict_cascade_depth3
    """
    _, item, review = setup_item_with_open_review(
        list_price_cents=30000, consignor_email="fake2@x.com")
    validate_success(api.review_verdict(
        review["id"], verdict_payload("COUNTERFEIT"),
        make_authenticator_headers("U-AUTH")), 200)
    res = api.list_item(item["id"], GRADER)
    # After a COUNTERFEIT verdict the item is both REJECTED at grading (state
    # precondition) and COUNTERFEIT at authentication; per PRD §2.5 the state
    # check precedes the authentication-gating business rule.
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


# ─── Difficulty: cross-entity state dependency — list gated by verdict ───────

def test_list_blocked_while_review_pending(api):
    """PRD §3.4: "Listing is additionally gated on authentication: the item's
    `authentication_status` must be either `NOT_REQUIRED` or `AUTHENTIC`. An item
    still `PENDING_AUTH` or found `COUNTERFEIT` cannot be listed, and the attempt
    is rejected with `ERR_AUTHENTICATION_REQUIRED`."

    Design: Difficulty/cross_entity_state_dependency/item_list_gated_by_authentication_review_verdict
    """
    _, item, review = setup_item_with_open_review(
        list_price_cents=7000, consignor_email="gate@x.com")
    res = api.list_item(item["id"], GRADER)
    validate_error(res, "ERR_AUTHENTICATION_REQUIRED", expected_status=409)


def test_list_permitted_after_authentic_verdict(api):
    """PRD §3.3: "A `verdict` of `AUTHENTIC` advances the review
    `IN_REVIEW → AUTHENTIC` and cascades the item's `authentication_status` to
    `AUTHENTIC`, which unblocks listing."

    Design: Difficulty/cross_entity_state_dependency/item_list_gated_by_authentication_review_verdict
    """
    _, item, review = setup_item_with_open_review(
        list_price_cents=7000, consignor_email="gate2@x.com")
    ruled = validate_success(api.review_verdict(
        review["id"], verdict_payload("AUTHENTIC"),
        make_authenticator_headers("U-AUTH")), 200)
    assert ruled["status"] == "AUTHENTIC"
    after_item = validate_success(api.get_item(item["id"], GRADER), 200)
    assert after_item["authentication_status"] == "AUTHENTIC"
    listed = validate_success(api.list_item(item["id"], GRADER), 200)
    assert listed["listing_status"] == "ON_FLOOR"


# ─── Difficulty: priority-pair conflict — INVALID_STATE beats AUTH_REQUIRED ──

def test_counterfeit_item_list_surfaces_invalid_state_not_auth_required(api):
    """PRD §2.5: "the check that the target resource is in a state from which the
    requested transition is defined, then the optimistic-concurrency version check
    on endpoints that take one, and only after all of those do the
    operation-specific business rules (separation of duties, authentication
    gating, on-floor and pricing constraints, window timing, uniqueness, and
    fiscal limits) run."

    Design: Difficulty/priority_pair_validation_conflict/state_vs_business_safety_invalidstate_beats_authrequired
    """
    _, item, review = setup_item_with_open_review(
        list_price_cents=9000, consignor_email="prio@x.com")
    validate_success(api.review_verdict(
        review["id"], verdict_payload("COUNTERFEIT", verdict_note="fake"),
        make_authenticator_headers("U-AUTH")), 200)
    after = validate_success(api.get_item(item["id"], GRADER), 200)
    assert after["grading_status"] == "REJECTED"
    assert after["authentication_status"] == "COUNTERFEIT"
    res = api.list_item(item["id"], GRADER)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_counterfeit_item_list_error_is_not_authentication_required(api):
    """PRD §2.5: "a state violation (`ERR_INVALID_STATE`) before the stale-version
    check — never the reverse."
    PRD §3.4: "an attempt to list from any other state is rejected with
    `ERR_INVALID_STATE`."

    Design: Difficulty/priority_pair_validation_conflict/state_vs_business_safety_invalidstate_beats_authrequired
    """
    _, item, review = setup_item_with_open_review(
        list_price_cents=9000, consignor_email="prio2@x.com")
    validate_success(api.review_verdict(
        review["id"], verdict_payload("COUNTERFEIT"),
        make_authenticator_headers("U-AUTH")), 200)
    res = api.list_item(item["id"], GRADER)
    body = res.json()["data"]
    assert body["error_id"] != "ERR_AUTHENTICATION_REQUIRED", (
        f"state violation must win, got {body['error_id']}")
    assert body["error_id"] == "ERR_INVALID_STATE"
