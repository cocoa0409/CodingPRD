"""ARC workflow: cyclic revision loop, fee calculation, approval cascade,
and cross-entity submission gates."""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    make_homeowner_headers,
    make_board_member_headers,
    create_arc_request_payload,
    create_arc_review_payload,
    setup_arc_request_submitted,
    setup_arc_request_under_review,
    setup_board_member,
    setup_homeowner_and_property,
    setup_property_suspended_via_fined_violation,
    api_client,
)

_MANAGER = TEST_USERS["hoa_manager_headers"]


# ===========================================================================
# Queue A — non_linear_state_machine / arc_request_cyclic_revision_loop
# ===========================================================================
def test_arc_cyclic_revision_loop_bumps_count_and_returns_to_submitted(api):
    """PRD §3.4: "otherwise, if at least one current-revision verdict is
    `REVISE` and none is `REJECT`, the request transitions to
    `REVISION_REQUESTED` and `revision_count` is incremented by one"
    PRD §3.4: "From `REVISION_REQUESTED` back to `SUBMITTED`, the same two
    cross-entity gates apply, plus the additional constraint that
    `revision_count` must be strictly less than 3"

    Design: Difficulty/non_linear_state_machine/arc_request_cyclic_revision_loop
    """
    board_member, homeowner, prop, arc = setup_arc_request_submitted(
        homeowner_email="hcyc@ex.com",
        board_email="bmcyc@ex.com",
        address="6 Cyc Ln",
    )
    resp = api.create_arc_review(
        arc["id"],
        create_arc_review_payload(
            board_member["id"], weight=2, verdict="REVISE"
        ),
        make_board_member_headers(board_member["id"]),
    )
    validate_success(resp, expected_status=201)
    resp = api.finalize_arc_request(
        arc["id"], make_board_member_headers(board_member["id"])
    )
    first = validate_success(resp)
    assert first["status"] == "REVISION_REQUESTED"
    assert first["revision_count"] == 1

    resp = api.submit_arc_request(
        arc["id"], make_homeowner_headers(homeowner["id"])
    )
    second = validate_success(resp)
    assert second["status"] == "SUBMITTED"
    assert second["revision_count"] == 1


# ===========================================================================
# Queue A — combinatorial_formula / arc_fee_sum_then_round_mode_b
# ===========================================================================
def test_arc_fee_sum_then_round_with_three_weighted_approve_reviews(api):
    """PRD §3.4: "A base fee in cents is selected from the request's
    `category`: 2500 for `SIMPLE`, 10000 for `MEDIUM`, and 25000 for
    `COMPLEX`."
    PRD §3.4: "For every current-revision `ARCReview` row, an unrounded
    per-review contribution is computed as the review's `weight` multiplied
    by the base fee multiplied by the fixed review rate of 0.10725. The
    final fee is the sum of the base fee and all unrounded per-review
    contributions, rounded half-up to a whole cent at the end of the
    summation. This evaluation order — **sum first, then round** — is
    pinned; the alternative of rounding each per-review contribution before
    summing is not used, since it produces a different total whenever any
    per-review contribution has a non-integer cents value."

    Design: Difficulty/combinatorial_formula/arc_fee_sum_then_round_mode_b
    """
    bm1 = setup_board_member("bm1@ex.com", "BM1")
    bm2 = setup_board_member("bm2@ex.com", "BM2")
    bm3 = setup_board_member("bm3@ex.com", "BM3")
    homeowner, prop = setup_homeowner_and_property(
        email="harc@ex.com", address="5 Arc Ln", monthly_dues_cents=30000
    )
    resp = api.create_arc_request(
        create_arc_request_payload(
            prop["id"], homeowner["id"],
            category="MEDIUM", description="Repaint fence beige",
        ),
        make_homeowner_headers(homeowner["id"]),
    )
    arc = validate_success(resp, expected_status=201)
    resp = api.submit_arc_request(
        arc["id"], make_homeowner_headers(homeowner["id"])
    )
    validate_success(resp)
    for bm, w in [(bm1, 1), (bm2, 2), (bm3, 3)]:
        resp = api.create_arc_review(
            arc["id"],
            create_arc_review_payload(bm["id"], weight=w, verdict="APPROVE"),
            make_board_member_headers(bm["id"]),
        )
        validate_success(resp, expected_status=201)
    resp = api.finalize_arc_request(
        arc["id"], make_board_member_headers(bm1["id"])
    )
    data = validate_success(resp)
    # base=10000; per-review raw = [1072.5, 2145.0, 3217.5]; sum=6435.0
    # total_raw = 10000 + 6435.0 = 16435.0; round → 16435
    assert data["fee_cents"] == 16435
    assert data["status"] == "APPROVED"


# ===========================================================================
# Queue A — transitive_cascade / arc_approval_depth_2_cascade
# ===========================================================================
def test_arc_approval_cascades_flag_and_creates_work_order(api):
    """PRD §3.4: "When a finalise transitions the request to `APPROVED`, two
    secondary effects fire in addition to the fee stamp. First, the target
    property's `compliance_flag` is set to `APPROVED_MOD` — recording that
    a modification has been sanctioned on that property. Second, a
    `WorkOrder` is auto-created against the same property with `source` set
    to `AUTO_ARC`, `related_property_id` set to the property's `id`, `title`
    set to `Post-approval inspection`, and `cost_estimate_cents` set to `0`."

    Design: Difficulty/transitive_cascade/arc_approval_depth_2_cascade
    """
    board_member, homeowner, prop, arc = setup_arc_request_under_review(
        homeowner_email="harc2@ex.com",
        board_email="bmarc@ex.com",
        address="8 Arc Ln",
        arc_category="SIMPLE",
        review_verdict="APPROVE",
        review_weight=1,
    )
    resp = api.finalize_arc_request(
        arc["id"], make_board_member_headers(board_member["id"])
    )
    finalized = validate_success(resp)
    assert finalized["status"] == "APPROVED"

    resp = api.get_property(prop["id"], _MANAGER)
    p = validate_success(resp)
    assert p["compliance_flag"] == "APPROVED_MOD"

    resp = api.list_property_work_orders(prop["id"], _MANAGER)
    wos = validate_success(resp)
    assert len(wos) == 1
    assert wos[0]["source"] == "AUTO_ARC"


# ===========================================================================
# Queue A — cross_entity_state_dependency / arc_submit_blocked_on_property_suspended
# ===========================================================================
def test_arc_submit_blocked_when_property_suspended(api):
    """PRD §3.4: "A submission against a suspended property is rejected with
    `ERR_PROPERTY_SUSPENDED`"
    PRD §3.1: "Second, once an unresolved violation on the property reaches
    `FINED` and has remained without an appeal or resolution for at least
    60 days, the flag transitions to `SUSPENDED`."

    Design: Difficulty/cross_entity_state_dependency/arc_submit_blocked_on_property_suspended
    """
    homeowner, prop, _ = setup_property_suspended_via_fined_violation(
        email="hsus@ex.com",
        address="11 Sus Ln",
        fine_amount_cents=50000,
        fine_at_iso="2026-03-05T00:00:00Z",
        advance_to_iso="2026-05-15T00:00:00Z",  # 71 days later
    )
    resp = api.create_arc_request(
        create_arc_request_payload(
            prop["id"], homeowner["id"],
            category="SIMPLE", description="New gate",
        ),
        make_homeowner_headers(homeowner["id"]),
    )
    arc = validate_success(resp, expected_status=201)
    resp = api.submit_arc_request(
        arc["id"], make_homeowner_headers(homeowner["id"])
    )
    validate_error(resp, ApiErrorId.ERR_PROPERTY_SUSPENDED)


# ===========================================================================
# Queue B — state_machines / arc_finalize_from_draft_returns_invalid_state
# ===========================================================================
def test_arc_finalize_from_draft_returns_invalid_state(api):
    """PRD §3.4: "A `BoardMember` finalises an `UNDER_REVIEW` request."
    PRD §2.8: "State precondition — the target resource must be in a state
    that permits the requested transition (see §3 for per-entity state
    machines); otherwise `ERR_INVALID_STATE` (HTTP 409)."

    Design: Corner/state_machines/arc_finalize_from_draft_returns_invalid_state
    """
    board_member = setup_board_member("bmd@ex.com", "BM D")
    homeowner, prop = setup_homeowner_and_property(
        email="hd@ex.com", address="24 D Ln"
    )
    resp = api.create_arc_request(
        create_arc_request_payload(
            prop["id"], homeowner["id"],
            category="SIMPLE", description="Draft",
        ),
        make_homeowner_headers(homeowner["id"]),
    )
    arc = validate_success(resp, expected_status=201)
    resp = api.finalize_arc_request(
        arc["id"], make_board_member_headers(board_member["id"])
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


# ===========================================================================
# Queue B — calculations / arc_fee_simple_no_reviews_edge (SIMPLE + 1 REJECT)
# ===========================================================================
def test_arc_fee_simple_with_one_reject_review(api):
    """PRD §3.4: "A base fee in cents is selected from the request's
    `category`: 2500 for `SIMPLE`, 10000 for `MEDIUM`, and 25000 for
    `COMPLEX`."
    PRD §3.4: "if at least one current-revision verdict is `REJECT`, the
    request transitions to `REJECTED`"
    PRD §3.4: "For every current-revision `ARCReview` row, an unrounded
    per-review contribution is computed as the review's `weight` multiplied
    by the base fee multiplied by the fixed review rate of 0.10725. The
    final fee is the sum of the base fee and all unrounded per-review
    contributions, rounded half-up to a whole cent at the end of the
    summation."

    Design: Corner/calculations/arc_fee_simple_no_reviews_edge
    """
    board_member, homeowner, prop, arc = setup_arc_request_under_review(
        homeowner_email="har@ex.com",
        board_email="bmar@ex.com",
        address="28 AR Ln",
        arc_category="SIMPLE",
        review_verdict="REJECT",
        review_weight=1,
    )
    resp = api.finalize_arc_request(
        arc["id"], make_board_member_headers(board_member["id"])
    )
    data = validate_success(resp)
    # base=2500; per-review raw = 1*2500*0.10725 = 268.125; total_raw=2768.125
    # round half-up → 2768
    assert data["fee_cents"] == 2768
    assert data["status"] == "REJECTED"


# ===========================================================================
# ARCReview reviewer must be a Homeowner with is_board_member=true
# ===========================================================================
def test_arc_review_reviewer_not_board_returns_error(api):
    """PRD §3.4: "A `BoardMember` submits a review on a request by supplying
    the `reviewer_homeowner_id` (which must reference a homeowner whose
    `is_board_member` is `true`; otherwise `ERR_REVIEWER_NOT_BOARD`)"

    Design: Corner/validations/reservation_reviewer_not_board_returns_error
    """
    non_board = get_success_data(
        api.create_homeowner(
            {"email": "nb@ex.com", "full_name": "Not Board"}, _MANAGER
        )
    )
    homeowner, prop = setup_homeowner_and_property(
        email="hnb@ex.com", address="29 NB Ln"
    )
    resp = api.create_arc_request(
        create_arc_request_payload(
            prop["id"], homeowner["id"],
            category="SIMPLE", description="Deck",
        ),
        make_homeowner_headers(homeowner["id"]),
    )
    arc = validate_success(resp, expected_status=201)
    resp = api.submit_arc_request(
        arc["id"], make_homeowner_headers(homeowner["id"])
    )
    validate_success(resp)
    # X-User-ID is the non-board homeowner acting as a BoardMember.
    resp = api.create_arc_review(
        arc["id"],
        create_arc_review_payload(non_board["id"], weight=1, verdict="APPROVE"),
        make_board_member_headers(non_board["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_REVIEWER_NOT_BOARD)


# ===========================================================================
# Queue B — validations / revision_limit_after_3_revisions
# ===========================================================================
def test_arc_submit_after_three_revisions_returns_revision_limit(api):
    """PRD §3.4: "From `REVISION_REQUESTED` back to `SUBMITTED`, the same two
    cross-entity gates apply, plus the additional constraint that
    `revision_count` must be strictly less than 3; a resubmit past that
    limit is rejected with `ERR_REVISION_LIMIT`."

    Design: Corner/validations/revision_limit_after_3_revisions
    """
    board_member, homeowner, prop, arc = setup_arc_request_submitted(
        homeowner_email="hrl@ex.com",
        board_email="bmrl@ex.com",
        address="32 RL Ln",
        arc_category="SIMPLE",
    )
    # Three REVISE-finalize cycles. Between cycles the homeowner resubmits;
    # after the third finalize, revision_count == 3 and the fourth submit
    # attempt should be rejected.
    for cycle in range(3):
        resp = api.create_arc_review(
            arc["id"],
            create_arc_review_payload(board_member["id"], weight=1, verdict="REVISE"),
            make_board_member_headers(board_member["id"]),
        )
        validate_success(resp, expected_status=201)
        resp = api.finalize_arc_request(
            arc["id"], make_board_member_headers(board_member["id"])
        )
        finalized = validate_success(resp)
        assert finalized["revision_count"] == cycle + 1
        if cycle < 2:
            resp = api.submit_arc_request(
                arc["id"], make_homeowner_headers(homeowner["id"])
            )
            validate_success(resp)
    # Fourth submit — revision_count is now 3 → rejected.
    resp = api.submit_arc_request(
        arc["id"], make_homeowner_headers(homeowner["id"])
    )
    validate_error(resp, ApiErrorId.ERR_REVISION_LIMIT)
