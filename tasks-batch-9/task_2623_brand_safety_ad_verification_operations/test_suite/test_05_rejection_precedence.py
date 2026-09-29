"""Rejection precedence: which error wins when two checks are violated at once.

Each scenario below drives one request that breaks two rules simultaneously and
pins the single error the PRD says must surface, and each is paired with a
companion request that breaks only the losing rule — proving the outranked check
is genuinely live rather than unimplemented.
"""
from test_helpers import (
    ANALYST_AUTHOR_USER_ID,
    ANALYST_THIRD_USER_ID,
    OFFICER_USER_ID,
    ApiErrorId,
    factories,
    get_success_data,
    make_officer_headers,
    make_operator_headers,
    read_advertiser,
    read_appeal,
    read_batch,
    read_claim,
    read_page,
    read_publisher,
    setup_appeal_at_round,
    setup_base_world,
    setup_claim_under_review,
    setup_quarantined_batch,
    setup_reviewed_classification,
    validate_error,
    validate_paginated,
    validate_success,
)

# ---------------------------------------------------------------------------
# shared scenario builders (not tests)
# ---------------------------------------------------------------------------

#: Sensor figures that quarantine the batch on a coverage shortfall
#: (6000 / 10000 = 0.6000, below the 0.7 floor) and leave every one of the
#: 6000 measurable impressions non-viewable, because an average in-view duration
#: of 0.8 seconds misses the 1.0-second DISPLAY threshold wholesale. The credit
#: such a batch supports is therefore far above a 100-cent lifetime cap.
UNCOVERED_FIGURES = {
    "measurable_impressions": 6000,
    "in_view_impressions": 5000,
    "avg_in_view_seconds": 0.8,
}


def _tiny_cap_world(api):
    """A world whose advertiser may never receive more than 100 cents of credit."""
    return setup_base_world(api, advertiser_overrides={"credit_cap_cents": 100})


def _claim_under_review_over_cap(api, world, index=0):
    """A claim in UNDER_REVIEW whose approval would breach the 100-cent cap."""
    batch = setup_quarantined_batch(api, world, index=index, **UNCOVERED_FIGURES)
    claim = setup_claim_under_review(api, world, batch_ids=[batch["id"]])
    return batch, claim


def _ingest_batch(api, world, window_start, window_end, **figures):
    """Ingest one batch with an explicit delivery window; returns the raw response."""
    payload = factories.create_measurement_batch_payload(
        world["campaign"]["id"],
        world["publisher"]["id"],
        world["page"]["id"],
        world["viewability_version"]["id"],
        window_start=window_start,
        window_end=window_end,
        **figures,
    )
    return api.create_measurement_batch(payload, make_operator_headers())


def _appeal_at_round_three(api):
    """An appeal in FILED at round_no 3 whose classification was authored by
    analyst-1 and confirmed by analyst-7."""
    world = setup_base_world(api)
    classification = setup_reviewed_classification(
        api,
        world["page"],
        world["suitability_version"]["id"],
        decision="CONFIRM",
        reviewer_user_id=ANALYST_THIRD_USER_ID,
        classification_overrides={
            "classifier_kind": "HUMAN",
            "category_codes": ["ARMS"],
        },
    )
    filed = setup_appeal_at_round(api, world, 3, classification=classification)
    return world, classification, filed["appeal"]


# ===========================================================================
# state reachability (priority 7) versus the credit cap (priority 34)
# ===========================================================================
def test_approving_rejected_claim_over_the_cap_returns_the_state_error(api):
    """Approving an already REJECTED claim whose credit would also blow the advertiser's cap answers the state error, never the fiscal one.

    PRD: "A rejected claim submitted for approval over an exhausted credit cap returns `ERR_INVALID_CLAIM_STATE`, because state reachability at priority 7 precedes the fiscal cap at priority 34."

    Design: Difficulty/priority_pair_validation_conflict/rejected_claim_over_exhausted_cap_returns_state_error_not_fiscal_error
    """
    world = _tiny_cap_world(api)
    batch, claim = _claim_under_review_over_cap(api, world)

    rejected = get_success_data(
        api.reject_refund_claim(
            claim["id"],
            factories.reject_claim_payload(
                reject_reason_code="EVIDENCE_INSUFFICIENT",
                decision_note="Log sample not reconcilable",
            ),
            make_officer_headers(OFFICER_USER_ID),
        )
    )
    assert rejected["claim_state"] == "REJECTED", (
        f"expected REJECTED before the trigger, got {rejected['claim_state']}"
    )

    response = api.approve_refund_claim(
        claim["id"],
        make_officer_headers(OFFICER_USER_ID),
        {"decision_note": "Attempt to approve an already rejected claim"},
    )
    validate_error(response, ApiErrorId.ERR_INVALID_CLAIM_STATE.value, expected_status=409)

    after = read_claim(api, claim["id"])
    assert after["claim_state"] == "REJECTED", (
        f"expected the claim to stay REJECTED, got {after['claim_state']} "
        "after the refused approval"
    )
    assert after["reject_reason_code"] == "EVIDENCE_INSUFFICIENT", (
        f"expected reject_reason_code EVIDENCE_INSUFFICIENT, got "
        f"{after['reject_reason_code']} after the refused approval"
    )
    assert after["net_credit_cents"] is None, (
        f"expected net_credit_cents null on a claim that was never approved, got "
        f"{after['net_credit_cents']}"
    )

    advertiser = read_advertiser(api, world["advertiser"]["id"])
    publisher = read_publisher(api, world["publisher"]["id"])
    assert advertiser["credit_received_cents_total"] == 0, (
        f"expected 0 cents credited, got {advertiser['credit_received_cents_total']} "
        "after the refused approval"
    )
    assert advertiser["settled_claim_count"] == 0, (
        f"expected settled_claim_count 0, got {advertiser['settled_claim_count']} "
        "after the refused approval"
    )
    assert publisher["credit_issued_cents_total"] == 0, (
        f"expected 0 cents charged back, got {publisher['credit_issued_cents_total']} "
        "after the refused approval"
    )

    settled = read_batch(api, batch["id"])
    assert settled["settlement_status"] == "CLOSED_NO_CREDIT", (
        f"expected the cited batch to stay CLOSED_NO_CREDIT, got "
        f"{settled['settlement_status']} after the refused approval"
    )


def test_credit_cap_alone_refuses_a_claim_that_is_under_review(api):
    """A claim still UNDER_REVIEW against the same 100-cent cap is refused on the cap, so the fiscal rule is live and merely outranked.

    PRD: "And an approval whose `net_credit_cents` would push the advertiser's `credit_received_cents_total` above that advertiser's `credit_cap_cents` is refused with `ERR_CREDIT_CAP_EXCEEDED`; the sum of the existing total and the new net credit must remain at or below the cap."

    Design: Difficulty/priority_pair_validation_conflict/rejected_claim_over_exhausted_cap_returns_state_error_not_fiscal_error
    """
    world = _tiny_cap_world(api)
    batch, claim = _claim_under_review_over_cap(api, world)
    assert claim["claim_state"] == "UNDER_REVIEW", (
        f"expected UNDER_REVIEW before the trigger, got {claim['claim_state']}"
    )

    response = api.approve_refund_claim(
        claim["id"],
        make_officer_headers(OFFICER_USER_ID),
        {"decision_note": "Isolation check with the state rule satisfied"},
    )
    validate_error(response, ApiErrorId.ERR_CREDIT_CAP_EXCEEDED.value, expected_status=409)

    after = read_claim(api, claim["id"])
    assert after["claim_state"] == "UNDER_REVIEW", (
        f"expected the claim to stay UNDER_REVIEW, got {after['claim_state']} "
        "after the refused approval"
    )
    assert after["net_credit_cents"] is None, (
        f"expected net_credit_cents null on a refused approval, got "
        f"{after['net_credit_cents']}"
    )

    advertiser = read_advertiser(api, world["advertiser"]["id"])
    publisher = read_publisher(api, world["publisher"]["id"])
    assert advertiser["credit_received_cents_total"] == 0, (
        f"expected 0 cents credited, got {advertiser['credit_received_cents_total']} "
        "after the refused approval"
    )
    assert publisher["credit_issued_cents_total"] == 0, (
        f"expected 0 cents charged back, got {publisher['credit_issued_cents_total']} "
        "after the refused approval"
    )

    settled = read_batch(api, batch["id"])
    assert settled["settlement_status"] == "CLAIMED", (
        f"expected the cited batch to stay CLAIMED, got {settled['settlement_status']} "
        "after the refused approval"
    )


# ===========================================================================
# counter consistency (priority 23) versus window separation (priority 30)
# ===========================================================================
def test_inconsistent_counts_outrank_a_colliding_window_on_batch_intake(api):
    """A batch whose measurable count exceeds its measured count and whose window sits inside the 60-second buffer answers the counter error, not the collision.

    PRD: "A batch whose counters are inconsistent *and* whose window collides with an existing batch returns `ERR_IMPRESSION_COUNTS_INCONSISTENT`, because counter consistency at priority 23 precedes window separation at priority 30."

    Design: Difficulty/priority_pair_validation_conflict/inconsistent_counts_outrank_window_collision_on_batch_intake
    """
    world = setup_base_world(api)
    base = get_success_data(
        _ingest_batch(
            api,
            world,
            "2026-07-01T00:00:00Z",
            "2026-07-01T01:00:00Z",
            measured_impressions=5000,
            measurable_impressions=4000,
            in_view_impressions=3500,
        ),
        expected_status=201,
    )

    response = _ingest_batch(
        api,
        world,
        "2026-07-01T01:00:45Z",
        "2026-07-01T02:00:00Z",
        measured_impressions=1000,
        measurable_impressions=2000,
        in_view_impressions=900,
    )
    validate_error(
        response, ApiErrorId.ERR_IMPRESSION_COUNTS_INCONSISTENT.value, expected_status=422
    )

    batches, meta = validate_paginated(
        api.list_measurement_batches(
            make_operator_headers(), params={"campaign_id": world["campaign"]["id"]}
        )
    )
    assert meta["total_count"] == 1, (
        f"expected only the pre-existing batch to survive the refusal, got "
        f"{meta['total_count']} batches"
    )
    assert [item["id"] for item in batches] == [base["id"]], (
        f"expected exactly {base['id']}, got {[item['id'] for item in batches]}"
    )


def test_repairing_the_counts_then_surfaces_the_window_collision(api):
    """With the counters repaired the same colliding window is refused on separation, and clearing 61 seconds of air finally ingests.

    PRD: "A new batch is refused when its `window_start` is at or before the existing batch's `window_end` plus 60 seconds *and* the existing batch's `window_start` is at or before the new batch's `window_end` plus 60 seconds."

    Design: Difficulty/priority_pair_validation_conflict/inconsistent_counts_outrank_window_collision_on_batch_intake
    """
    world = setup_base_world(api)
    base = get_success_data(
        _ingest_batch(
            api,
            world,
            "2026-07-01T00:00:00Z",
            "2026-07-01T01:00:00Z",
            measured_impressions=5000,
            measurable_impressions=4000,
            in_view_impressions=3500,
        ),
        expected_status=201,
    )

    colliding = _ingest_batch(
        api,
        world,
        "2026-07-01T01:00:45Z",
        "2026-07-01T02:00:00Z",
        measured_impressions=3000,
        measurable_impressions=2000,
        in_view_impressions=900,
    )
    validate_error(
        colliding, ApiErrorId.ERR_BATCH_WINDOW_COLLISION.value, expected_status=409
    )

    cleared = _ingest_batch(
        api,
        world,
        "2026-07-01T01:01:01Z",
        "2026-07-01T02:00:00Z",
        measured_impressions=3000,
        measurable_impressions=2000,
        in_view_impressions=900,
    )
    accepted = validate_success(cleared, expected_status=201)
    assert accepted["window_start"].startswith("2026-07-01T01:01:01"), (
        f"expected the 61-second-clear window to be stored, got "
        f"{accepted['window_start']}"
    )
    assert accepted["scoring_status"] == "INGESTED", (
        f"expected a freshly ingested batch at INGESTED, got {accepted['scoring_status']}"
    )

    batches, meta = validate_paginated(
        api.list_measurement_batches(
            make_operator_headers(), params={"campaign_id": world["campaign"]["id"]}
        )
    )
    assert meta["total_count"] == 2, (
        f"expected exactly 2 batches after one refusal and one acceptance, got "
        f"{meta['total_count']}"
    )
    assert sorted(item["id"] for item in batches) == sorted([base["id"], accepted["id"]]), (
        "expected only the base batch and the accepted batch to exist, got "
        f"{[item['id'] for item in batches]}"
    )


# ===========================================================================
# segregation of duties (priority 10) versus the round ceiling (priority 26)
# ===========================================================================
def test_self_review_on_an_exhausted_appeal_returns_the_duty_breach(api):
    """The analyst who confirmed the disputed classification asks for a fourth evidence round and is refused on self-review, not on the round ceiling.

    PRD: "A self-review by the deciding officer on an appeal already at round 3 returns `ERR_SEGREGATION_OF_DUTIES`, because the duty check at priority 10 precedes the round ceiling at priority 26."

    Design: Difficulty/priority_pair_validation_conflict/appeal_sod_breach_outranks_round_exhaustion
    """
    world, classification, appeal = _appeal_at_round_three(api)
    assert appeal["appeal_state"] == "FILED", (
        f"expected FILED before the trigger, got {appeal['appeal_state']}"
    )
    assert appeal["round_no"] == 3, (
        f"expected round_no 3 before the trigger, got {appeal['round_no']}"
    )
    assert classification["reviewed_by_user_id"] == ANALYST_THIRD_USER_ID, (
        f"expected reviewed_by_user_id {ANALYST_THIRD_USER_ID}, got "
        f"{classification['reviewed_by_user_id']}"
    )
    assert classification["classifier_user_id"] == ANALYST_AUTHOR_USER_ID, (
        f"expected classifier_user_id {ANALYST_AUTHOR_USER_ID}, got "
        f"{classification['classifier_user_id']}"
    )

    response = api.decide_appeal(
        appeal["id"],
        factories.decide_appeal_payload(
            outcome="MORE_EVIDENCE", decision_note="Decided by the reviewing analyst"
        ),
        make_officer_headers(ANALYST_THIRD_USER_ID),
    )
    validate_error(
        response, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, expected_status=403
    )

    after = read_appeal(api, appeal["id"])
    assert after["appeal_state"] == "FILED", (
        f"expected the appeal to stay FILED, got {after['appeal_state']} "
        "after the refused decision"
    )
    assert after["round_no"] == 3, (
        f"expected round_no to stay 3, got {after['round_no']} after the refused decision"
    )
    assert after["decided_by_user_id"] is None, (
        f"expected decided_by_user_id to stay null, got {after['decided_by_user_id']} "
        "after the refused decision"
    )

    page = read_page(api, world["page"]["id"])
    assert page["classification_state"] == "APPEALED", (
        f"expected the page to stay APPEALED, got {page['classification_state']} "
        "after the refused decision"
    )


def test_round_ceiling_alone_refuses_a_clean_officer_at_round_three(api):
    """The identical fourth-round request from an officer with no duty conflict is refused on the round ceiling, so that rule is live and merely outranked.

    PRD: "It is only available while `round_no` is strictly below the ceiling of 3 rounds; at round 3 it answers `ERR_APPEAL_ROUNDS_EXHAUSTED`."

    Design: Difficulty/priority_pair_validation_conflict/appeal_sod_breach_outranks_round_exhaustion
    """
    world, classification, appeal = _appeal_at_round_three(api)
    assert appeal["round_no"] == 3, (
        f"expected round_no 3 before the trigger, got {appeal['round_no']}"
    )
    assert OFFICER_USER_ID not in (
        classification["reviewed_by_user_id"],
        classification["classifier_user_id"],
    ), f"{OFFICER_USER_ID} must carry no duty conflict with the disputed classification"

    response = api.decide_appeal(
        appeal["id"],
        factories.decide_appeal_payload(
            outcome="MORE_EVIDENCE", decision_note="Same request from a clean officer"
        ),
        make_officer_headers(OFFICER_USER_ID),
    )
    validate_error(
        response, ApiErrorId.ERR_APPEAL_ROUNDS_EXHAUSTED.value, expected_status=409
    )

    after = read_appeal(api, appeal["id"])
    assert after["appeal_state"] == "FILED", (
        f"expected the appeal to stay FILED, got {after['appeal_state']} "
        "after the refused decision"
    )
    assert after["round_no"] == 3, (
        f"expected round_no to stay 3, got {after['round_no']} after the refused decision"
    )
    assert after["decided_by_user_id"] is None, (
        f"expected decided_by_user_id to stay null, got {after['decided_by_user_id']} "
        "after the refused decision"
    )

    page = read_page(api, world["page"]["id"])
    assert page["classification_state"] == "APPEALED", (
        f"expected the page to stay APPEALED, got {page['classification_state']} "
        "after the refused decision"
    )
