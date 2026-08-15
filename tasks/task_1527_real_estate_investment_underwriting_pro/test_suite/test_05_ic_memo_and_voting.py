"""IC memo drafting, submission, voting, and decision cascades (PRD §3.7, §3.8)."""
from test_helpers import (
    ANALYST_USER_ID,
    ApiErrorId,
    assert_ic_memo,
    assert_ic_vote,
    create_memo_fresh,
    create_scenario_fresh,
    get_deal,
    is_iso8601_timestamp,
    make_ic_member_headers,
    setup_computed_scenario,
    setup_deal_in_ic_review,
    setup_submitted_memo,
    setup_underwriting_env,
    validate_error,
    validate_success,
)


def test_memo_create_with_draft_scenario_rejected(api, analyst_headers):
    """PRD §3.7: "The referenced `scenario_id` must belong to the same deal and
    must already be in `COMPUTED` status; otherwise the create is rejected with
    `ERR_SCENARIO_NOT_COMPUTED` (HTTP 422)."

    Design: Corner/state_machines/memo_submit_on_non_computed_scenario_returns_error
    """
    env = setup_underwriting_env(deal_overrides={"deal_code": "D-PS"})
    scenario = create_scenario_fresh(
        env["deal"]["id"], env["assumption"]["id"],
        scenario_kind="BASE", occupancy_stress_pct=90,
    )
    assert scenario["status"] == "DRAFT"
    res = api.create_ic_memo(env["deal"]["id"], {
        "scenario_id": scenario["id"],
        "recommendation": "PURSUE",
        "thesis": "t",
        "risks": "r",
        "expected_deal_version": get_deal(env["deal"]["id"])["version"],
    }, analyst_headers)
    validate_error(res, ApiErrorId.ERR_SCENARIO_NOT_COMPUTED)


def test_vote_on_draft_memo_rejected(api, ic_member_headers):
    """PRD §3.8: "Voting is only permitted while the memo is in `UNDER_VOTE`;
    voting on an already-decided memo is rejected with `ERR_INVALID_STATE`
    (HTTP 409)."
    PRD §3.7: "A new memo starts in `DRAFT` status, and memo creation increments
    the deal's `version` by 1."

    Design: Difficulty/cross_entity_state_dependency/ic_vote_requires_memo_under_vote
    """
    env = setup_computed_scenario(deal_overrides={"deal_code": "D-X2"})
    memo = create_memo_fresh(env["deal"]["id"], env["scenario"]["id"])
    assert memo["status"] == "DRAFT"
    res = api.vote_ic_memo(memo["id"], {"vote": "YES"}, ic_member_headers)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE)


def test_vote_on_submitted_memo_rejected(api, ic_member_headers):
    """PRD §3.8: "Voting is only permitted while the memo is in `UNDER_VOTE`;
    voting on an already-decided memo is rejected with `ERR_INVALID_STATE`
    (HTTP 409)."
    PRD §3.7: "Submitting the memo transitions it `DRAFT → SUBMITTED`."

    Design: Difficulty/cross_entity_state_dependency/ic_vote_requires_memo_under_vote
    """
    env = setup_submitted_memo(deal_overrides={"deal_code": "D-X4"})
    memo = env["memo"]
    assert memo["status"] == "SUBMITTED"
    res = api.vote_ic_memo(memo["id"], {"vote": "YES"}, ic_member_headers)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE)


def test_single_yes_vote_keeps_memo_under_vote(api, ic_member_headers, analyst_headers):
    """PRD §3.8: "If the count of `YES` votes is at least 2 (the quorum constant
    `IC_QUORUM_YES`) and the count of `NO` votes is exactly zero, the memo
    cascades `UNDER_VOTE → APPROVED` and the deal cascades `IC_REVIEW →
    APPROVED`."
    A single YES vote is below the quorum (1 < 2), so neither cascade fires.

    Design: Difficulty/boundary_precision_check/yes_vote_quorum_boundary_exactly_two
    """
    env = setup_deal_in_ic_review(deal_overrides={"deal_code": "D-BND1"})
    memo_id = env["memo"]["id"]
    vote = validate_success(
        api.vote_ic_memo(memo_id, {"vote": "YES"}, ic_member_headers), 201
    )
    assert_ic_vote(vote)
    memo = validate_success(api.get_ic_memo(memo_id, analyst_headers), 200)
    assert memo["status"] == "UNDER_VOTE", (
        f"1 YES < quorum of 2: memo must stay UNDER_VOTE, got {memo['status']}"
    )
    deal = get_deal(env["deal"]["id"])
    assert deal["status"] == "IC_REVIEW"


def test_second_yes_vote_reaches_quorum(api, ic_member_headers, ic_member_2_headers, analyst_headers):
    """PRD §3.8: "If the count of `YES` votes is at least 2 (the quorum constant
    `IC_QUORUM_YES`) and the count of `NO` votes is exactly zero, the memo
    cascades `UNDER_VOTE → APPROVED` and the deal cascades `IC_REVIEW →
    APPROVED`."
    The boundary is inclusive: exactly 2 YES votes with 0 NO votes is sufficient.

    Design: Difficulty/boundary_precision_check/yes_vote_quorum_boundary_exactly_two
    """
    env = setup_deal_in_ic_review(deal_overrides={"deal_code": "D-BND2"})
    memo_id = env["memo"]["id"]
    validate_success(api.vote_ic_memo(memo_id, {"vote": "YES"}, ic_member_headers), 201)
    validate_success(api.vote_ic_memo(memo_id, {"vote": "YES"}, ic_member_2_headers), 201)
    memo = validate_success(api.get_ic_memo(memo_id, analyst_headers), 200)
    assert memo["status"] == "APPROVED", (
        f"2 YES >= quorum of 2: memo must be APPROVED, got {memo['status']}"
    )


def test_yes_quorum_cascades_deal_approved(api, ic_member_headers, ic_member_2_headers, analyst_headers):
    """PRD §3.8: "If the count of `YES` votes is at least 2 (the quorum constant
    `IC_QUORUM_YES`) and the count of `NO` votes is exactly zero, the memo
    cascades `UNDER_VOTE → APPROVED` and the deal cascades `IC_REVIEW →
    APPROVED`."

    Design: Difficulty/transitive_cascade/yes_vote_quorum_cascades_deal_approved
    """
    env = setup_deal_in_ic_review(deal_overrides={"deal_code": "D-C1"})
    memo_id = env["memo"]["id"]
    validate_success(
        api.vote_ic_memo(memo_id, {"vote": "YES", "comment": "ok"}, ic_member_headers), 201
    )
    validate_success(
        api.vote_ic_memo(memo_id, {"vote": "YES", "comment": "ok2"}, ic_member_2_headers), 201
    )
    memo = validate_success(api.get_ic_memo(memo_id, analyst_headers), 200)
    assert_ic_memo(memo)
    assert memo["status"] == "APPROVED"
    deal = get_deal(env["deal"]["id"])
    assert deal["status"] == "APPROVED", (
        f"deal must cascade to APPROVED on the second YES, got {deal['status']}"
    )


def test_yes_quorum_stamps_approved_at(api, ic_member_headers, ic_member_2_headers, analyst_headers):
    """PRD §3.8: "The server stamps `decided_at` on the memo and `approved_at` on
    the deal with the current logical-clock UTC timestamp. The deal's `version`
    and the memo's `version` each increment by 1."

    Design: Difficulty/transitive_cascade/yes_vote_quorum_cascades_deal_approved
    """
    env = setup_deal_in_ic_review(deal_overrides={"deal_code": "D-C1B"})
    memo_id = env["memo"]["id"]
    validate_success(api.vote_ic_memo(memo_id, {"vote": "YES"}, ic_member_headers), 201)
    validate_success(api.vote_ic_memo(memo_id, {"vote": "YES"}, ic_member_2_headers), 201)
    memo = validate_success(api.get_ic_memo(memo_id, analyst_headers), 200)
    deal = get_deal(env["deal"]["id"])
    assert deal["approved_at"] is not None, "approved_at must be stamped on approval"
    assert is_iso8601_timestamp(deal["approved_at"]), (
        f"approved_at must be an ISO 8601 timestamp, got {deal['approved_at']!r}"
    )
    assert memo["decided_at"] is not None, "decided_at must be stamped on the memo"
    assert is_iso8601_timestamp(memo["decided_at"])


def test_no_vote_cascades_deal_rejected(api, ic_member_headers, analyst_headers):
    """PRD §3.8: "If any `NO` vote is cast, the memo cascades `UNDER_VOTE →
    REJECTED` and the deal cascades `IC_REVIEW → REJECTED`."

    Design: Difficulty/transitive_cascade/no_vote_cascades_deal_rejected
    """
    env = setup_deal_in_ic_review(deal_overrides={"deal_code": "D-C2"})
    memo_id = env["memo"]["id"]
    validate_success(
        api.vote_ic_memo(memo_id, {"vote": "NO", "comment": "market too rich"},
                         ic_member_headers),
        201,
    )
    memo = validate_success(api.get_ic_memo(memo_id, analyst_headers), 200)
    assert memo["status"] == "REJECTED", (
        f"a single NO vote must reject the memo, got {memo['status']}"
    )
    deal = get_deal(env["deal"]["id"])
    assert deal["status"] == "REJECTED", (
        f"deal must cascade to REJECTED, got {deal['status']}"
    )


def test_no_vote_records_rejected_reason(api, ic_member_headers, analyst_headers):
    """PRD §3.8: "If any `NO` vote is cast, the memo cascades `UNDER_VOTE →
    REJECTED` and the deal cascades `IC_REVIEW → REJECTED`. The deal's
    `rejected_reason` is set from the vote's `comment`."

    Design: Difficulty/transitive_cascade/no_vote_cascades_deal_rejected
    """
    env = setup_deal_in_ic_review(deal_overrides={"deal_code": "D-C2B"})
    memo_id = env["memo"]["id"]
    validate_success(
        api.vote_ic_memo(memo_id, {"vote": "NO", "comment": "market too rich"},
                         ic_member_headers),
        201,
    )
    deal = get_deal(env["deal"]["id"])
    assert deal["rejected_reason"] == "market too rich", (
        f"rejected_reason must come from the vote comment, got {deal['rejected_reason']!r}"
    )
    memo = validate_success(api.get_ic_memo(memo_id, analyst_headers), 200)
    assert memo["decided_at"] is not None


def test_duplicate_vote_rejected(api, ic_member_headers):
    """PRD §3.8: "The same voter may not vote twice on the same memo — a repeat
    attempt is rejected with `ERR_DUPLICATE_VOTE` (HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/business_fiscal_vs_business_safety_on_debt_sizing
    """
    env = setup_deal_in_ic_review(deal_overrides={"deal_code": "D-VOTE"})
    memo_id = env["memo"]["id"]
    validate_success(api.vote_ic_memo(memo_id, {"vote": "ABSTAIN"}, ic_member_headers), 201)
    res = api.vote_ic_memo(memo_id, {"vote": "YES"}, ic_member_headers)
    validate_error(res, ApiErrorId.ERR_DUPLICATE_VOTE)


def test_analyst_cannot_vote_on_own_deal_memo(api, analyst_headers):
    """PRD §3.8: "A segregation-of-duties rule separates the deal's originator
    from its deciders: the user identified by `deal.analyst_id` may not cast an
    `ICVote` on any memo belonging to that deal. A violation is rejected with
    `ERR_SEG_DUTIES` (HTTP 403)."

    Design: Corner/validations/analyst_cannot_vote_on_own_deal_memo
    """
    env = setup_deal_in_ic_review(deal_overrides={"deal_code": "D-SEG"})
    # The deal's analyst holds an IC_Member role header here; the stored
    # deal.analyst_id is what triggers the segregation-of-duties rejection.
    res = api.vote_ic_memo(
        env["memo"]["id"], {"vote": "YES"}, make_ic_member_headers(ANALYST_USER_ID)
    )
    validate_error(res, ApiErrorId.ERR_SEG_DUTIES)


def test_ic_chair_can_reject_memo(api, ic_chair_headers, analyst_headers):
    """PRD §3.8: "Independent of the vote tally, an `IC_Chair` may force-reject a
    memo. The chair supplies a `reason`; the memo transitions `UNDER_VOTE →
    REJECTED` with `decided_at` stamped, the deal transitions `IC_REVIEW →
    REJECTED` with `rejected_reason` set from the supplied `reason`, and both
    `version` fields increment by 1."

    Design: Corner/rbac/ic_chair_can_reject_memo
    """
    env = setup_deal_in_ic_review(deal_overrides={"deal_code": "D-CHR"})
    memo_id = env["memo"]["id"]
    memo = validate_success(
        api.reject_ic_memo(memo_id, {"reason": "pricing too aggressive"}, ic_chair_headers),
        200,
    )
    assert memo["status"] == "REJECTED"
    assert memo["decided_at"] is not None
    deal = get_deal(env["deal"]["id"])
    assert deal["status"] == "REJECTED"
    assert deal["rejected_reason"] == "pricing too aggressive", (
        f"rejected_reason must come from the chair's reason, got {deal['rejected_reason']!r}"
    )


def test_ic_member_cannot_reject_memo(api, ic_member_headers):
    """PRD §2.1: "`IC_Chair` — IC chair; may cast votes just like an `IC_Member`
    and additionally may force-reject a memo."
    PRD §2.1: "A request whose role is not permitted for the requested endpoint
    is rejected with `ERR_FORBIDDEN` (HTTP 403)."

    Design: Corner/rbac/ic_member_cannot_reject_memo
    """
    env = setup_deal_in_ic_review(deal_overrides={"deal_code": "D-CHR2"})
    res = api.reject_ic_memo(env["memo"]["id"], {"reason": "x"}, ic_member_headers)
    validate_error(res, ApiErrorId.ERR_FORBIDDEN)
