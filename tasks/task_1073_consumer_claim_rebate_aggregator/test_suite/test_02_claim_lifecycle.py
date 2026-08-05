"""State-machine transitions, cyclic loops, and immediate-consistency reads."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS, make_consumer_headers,
)
from test_helpers import fixtures as fx

PM = TEST_USERS["program_manager_headers"]
ADMIN = TEST_USERS["platform_admin_headers"]
REVIEWER = TEST_USERS["claim_reviewer_headers"]


def test_program_open_from_open_returns_invalid_state(api):
    """PRD §3.1: "opening a program that is not in `DRAFT` is rejected with
    `ERR_INVALID_STATE`."

    Design: Corner/state_machines/program_open_from_open_returns_invalid_state
    """
    program = fx.create_open_program(
        api, eligibility_min_purchase_cents=0, requires_proof=False, min_documents=0)
    resp = api.open_program(program["id"], PM)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_claim_approve_from_draft_returns_invalid_state(api):
    """PRD §3.5: "first the claim must actually be `UNDER_REVIEW`, else
    `ERR_INVALID_STATE`; then the optimistic-concurrency check".

    Design: Corner/state_machines/claim_approve_from_draft_returns_invalid_state
    """
    program = fx.create_open_program(
        api, eligibility_min_purchase_cents=0, requires_proof=False, min_documents=0)
    consumer = fx.register_consumer(api)
    claim = fx.create_claim(api, consumer, program["id"], claimed_amount_cents=12000)
    resp = api.approve_claim(claim["id"], program["version"], REVIEWER)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    assert get_success_data(api.get_claim(claim["id"], ADMIN))["status"] == "DRAFT"


def test_match_converts_when_claim_filed_from_it(api):
    """PRD §3.3: "when present, that match is converted from `CANDIDATE` to
    `CONVERTED` as a side effect of the filing, but only if it belongs to the
    same `consumer_id` and `program_id` as the new claim".

    Design: Corner/state_machines/match_converts_when_claim_filed_from_it
    """
    program = fx.create_open_program(
        api, eligibility_min_purchase_cents=0, requires_proof=False, min_documents=0)
    consumer = fx.register_consumer(api)
    match = get_success_data(api.create_match(
        {"consumer_id": consumer["id"], "program_id": program["id"]}, PM))
    fx.create_claim(api, consumer, program["id"], claimed_amount_cents=12000,
                    match_id=match["id"])
    data = get_success_data(api.get_match(match["id"], PM))
    assert data["status"] == "CONVERTED"


def test_approve_result_visible_immediately(api):
    """PRD §3.5: "The `final_payout_cents` is the smallest of the claim's
    `provisional_payout_cents`, the program's `per_claim_cap_cents`, and the
    program's live `fund_remaining_cents`".

    Design: Corner/consistency_model/approve_result_visible_immediately
    """
    ctx = fx.setup_approved_fixed_claim(api)
    data = get_success_data(api.get_claim(ctx["claim"]["id"], REVIEWER))
    assert data["status"] == "APPROVED"
    assert data["final_payout_cents"] == 20000


class TestClaimRevisionLoop:
    """Difficulty non_linear_state_machine — the NEEDS_INFO <-> UNDER_REVIEW cycle."""

    def test_request_info_twice_across_resubmit_reaches_needs_info_count_two(self, api):
        """PRD §3.4: "A claim can traverse this `NEEDS_INFO` ↔ `UNDER_REVIEW`
        cycle any number of times, and each request-info pass raises `needs_info_count`."

        Design: Difficulty/non_linear_state_machine/claim_needs_info_under_review_cycle
        """
        ctx = fx.setup_claim_under_review(api)
        claim_id = ctx["claim"]["id"]
        consumer = ctx["consumer"]
        get_success_data(api.request_info(claim_id, REVIEWER))
        get_success_data(api.resubmit_claim(claim_id, make_consumer_headers(consumer["id"])))
        data = get_success_data(api.request_info(claim_id, REVIEWER))
        assert data["status"] == "NEEDS_INFO"
        assert data["needs_info_count"] == 2

    def test_resubmit_returns_claim_to_under_review(self, api):
        """PRD §3.4: "The consumer answers by **resubmitting**, which returns the
        claim from `NEEDS_INFO` to `UNDER_REVIEW` and re-runs the eligibility
        assessment logic to refresh `eligibility_status`".

        Design: Difficulty/non_linear_state_machine/claim_needs_info_under_review_cycle
        """
        ctx = fx.setup_claim_under_review(api)
        claim_id = ctx["claim"]["id"]
        consumer = ctx["consumer"]
        ni = get_success_data(api.request_info(claim_id, REVIEWER))
        assert ni["status"] == "NEEDS_INFO"
        assert ni["needs_info_count"] == 1
        back = get_success_data(api.resubmit_claim(
            claim_id, make_consumer_headers(consumer["id"])))
        assert back["status"] == "UNDER_REVIEW"


class TestPayoutRetryLoop:
    """Difficulty non_linear_state_machine — the FAILED -> INITIATED retry cycle."""

    def test_fail_then_retry_reaches_initiated_attempt_count_two(self, api):
        """PRD §3.7: "A failed payout can be **retried**, moving it back from
        `FAILED` to `INITIATED` and incrementing its `attempt_count` by one."

        Design: Difficulty/non_linear_state_machine/payout_failed_initiated_retry_cycle
        """
        ctx = fx.setup_approved_fixed_claim(api)
        payout_id = ctx["payout"]["id"]
        get_success_data(api.fail_payout(payout_id, ADMIN, {"reason": "bank_reject"}))
        data = get_success_data(api.retry_payout(payout_id, ADMIN))
        assert data["status"] == "INITIATED"
        assert data["attempt_count"] == 2

    def test_retry_does_not_redebit_fund(self, api):
        """PRD §3.7: "Note that because `fund_remaining_cents` counts payouts in
        `INITIATED`, `CLEARED`, and `FAILED` status alike, a payout moving among
        these three states never changes the program's remaining fund."

        Design: Difficulty/non_linear_state_machine/payout_failed_initiated_retry_cycle
        """
        ctx = fx.setup_approved_fixed_claim(api)  # fund 100000, gross 20000 -> remaining 80000
        payout_id = ctx["payout"]["id"]
        program_id = ctx["program"]["id"]
        get_success_data(api.fail_payout(payout_id, ADMIN))
        get_success_data(api.retry_payout(payout_id, ADMIN))
        prog = get_success_data(api.get_program(program_id, PM))
        assert prog["fund_remaining_cents"] == 80000
