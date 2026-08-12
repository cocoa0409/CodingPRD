"""Non-linear state machines: the bounded claim deficiency cycle and the
repeatable classification rework loop."""
from test_helpers import ApiErrorId, add_classification, onboard_client, setup_filed_claim, TEST_USERS, validate_error, validate_success

ANALYST = TEST_USERS["analyst_headers"]
BROKER = TEST_USERS["broker_headers"]


def test_two_deficiency_cycles_succeed_and_the_third_is_rejected(api):
    """PRD 3.5: "An `outcome` of `DEFICIENCY` is CBP's request for more
    information; it is available only while the claim's `deficiency_count` is
    below two — a third deficiency attempt is rejected with
    `ERR_DEFICIENCY_LIMIT_REACHED` — and it moves the claim to
    `DEFICIENCY_ISSUED` while incrementing `deficiency_count`."
    PRD 3.5: "The cycle from `FILED` to `DEFICIENCY_ISSUED` and back may occur
    at most twice over the claim's life, as bounded by the deficiency counter."

    Design: Difficulty/non_linear_state_machine/claim_deficiency_cycle_with_limit
    """
    ctx = setup_filed_claim(matched_quantity=40)
    claim_id = ctx["claim"]["id"]

    # Cycle 1
    claim = validate_success(
        api.review_claim(claim_id, {"outcome": "DEFICIENCY"}, BROKER)
    )
    assert claim["status"] == "DEFICIENCY_ISSUED"
    assert claim["deficiency_count"] == 1
    claim = validate_success(api.deficiency_response(claim_id, ANALYST))
    assert claim["status"] == "FILED"

    # Cycle 2
    claim = validate_success(
        api.review_claim(claim_id, {"outcome": "DEFICIENCY"}, BROKER)
    )
    assert claim["status"] == "DEFICIENCY_ISSUED"
    assert claim["deficiency_count"] == 2
    claim = validate_success(api.deficiency_response(claim_id, ANALYST))
    assert claim["status"] == "FILED"

    # Third deficiency attempt exceeds the counter bound.
    res = api.review_claim(claim_id, {"outcome": "DEFICIENCY"}, BROKER)
    validate_error(res, ApiErrorId.ERR_DEFICIENCY_LIMIT_REACHED)

    claim = validate_success(api.get_claim(claim_id, ANALYST))
    assert claim["status"] == "FILED", "the failed outcome must leave state unchanged"
    assert claim["deficiency_count"] == 2


def test_deficiency_response_returns_the_claim_to_filed_for_another_round(api):
    """PRD 3.5: "The deficiency cycle is a loop: from `DEFICIENCY_ISSUED`, an
    `Analyst`, a `LicensedBroker`, or the client's own `ClientContact` may file
    the deficiency response, returning the claim to `FILED` for another review
    round."

    Design: Difficulty/non_linear_state_machine/claim_deficiency_cycle_with_limit
    """
    ctx = setup_filed_claim(matched_quantity=40)
    claim_id = ctx["claim"]["id"]

    validate_success(api.review_claim(claim_id, {"outcome": "DEFICIENCY"}, BROKER))
    claim = validate_success(api.deficiency_response(claim_id, BROKER))
    assert claim["status"] == "FILED", "a broker may file the deficiency response"
    assert claim["deficiency_count"] == 1

    # The loop is repeatable: a second full cycle also succeeds.
    claim = validate_success(api.review_claim(claim_id, {"outcome": "DEFICIENCY"}, BROKER))
    assert claim["status"] == "DEFICIENCY_ISSUED"
    assert claim["deficiency_count"] == 2
    claim = validate_success(api.deficiency_response(claim_id, ANALYST))
    assert claim["status"] == "FILED"


def test_rework_cycle_repeats_until_certification(api):
    """PRD 3.2: "A `decision` of `REWORK` returns the classification to `DRAFT`,
    and the cycle from `DRAFT` to `IN_REVIEW` and back may repeat indefinitely.
    A `decision` of `CERTIFY` moves it to `CERTIFIED` and stamps
    `certified_by_user_id` — but only if the certifying broker is not the same
    individual who submitted it; a self-certification is rejected with
    `ERR_SEGREGATION_OF_DUTIES`."

    Design: Difficulty/non_linear_state_machine/classification_rework_cycle
    """
    client = onboard_client()
    cls = add_classification(client["id"])

    # First loop: DRAFT -> IN_REVIEW -> DRAFT.
    submitted = validate_success(api.submit_classification(cls["id"], ANALYST))
    assert submitted["status"] == "IN_REVIEW"
    reworked = validate_success(
        api.review_classification(cls["id"], {"decision": "REWORK"}, BROKER)
    )
    assert reworked["status"] == "DRAFT", "REWORK closes the loop back to DRAFT"

    # Second pass terminates in CERTIFIED.
    resubmitted = validate_success(api.submit_classification(cls["id"], ANALYST))
    assert resubmitted["status"] == "IN_REVIEW"
    certified = validate_success(
        api.review_classification(cls["id"], {"decision": "CERTIFY"}, BROKER)
    )
    assert certified["status"] == "CERTIFIED"
    assert certified["certified_by_user_id"] == "u_br1"
    assert certified["submitted_by_user_id"] == "u_an1", (
        "the rework loop must not blur the segregation trail"
    )


def test_rework_loop_may_repeat_more_than_once(api):
    """PRD 3.2: "A `decision` of `REWORK` returns the classification to `DRAFT`,
    and the cycle from `DRAFT` to `IN_REVIEW` and back may repeat indefinitely."

    Design: Difficulty/non_linear_state_machine/classification_rework_cycle
    """
    client = onboard_client()
    cls = add_classification(client["id"])

    for _ in range(2):
        submitted = validate_success(api.submit_classification(cls["id"], ANALYST))
        assert submitted["status"] == "IN_REVIEW"
        reworked = validate_success(
            api.review_classification(cls["id"], {"decision": "REWORK"}, BROKER)
        )
        assert reworked["status"] == "DRAFT"

    certified = validate_success(api.submit_classification(cls["id"], ANALYST))
    assert certified["status"] == "IN_REVIEW"
    final = validate_success(
        api.review_classification(cls["id"], {"decision": "CERTIFY"}, BROKER)
    )
    assert final["status"] == "CERTIFIED"
