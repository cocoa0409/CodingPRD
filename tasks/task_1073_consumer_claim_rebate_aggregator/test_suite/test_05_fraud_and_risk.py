"""Fraud governance, the two-tier risk score, and match relevance scoring.

NOTE ON A SKIPPED CORNER INSTANCE (no test emitted, intentionally):
  Corner/calculations/risk_score_confirmed_flag_weight asserts a VERIFIED
  consumer with one CONFIRMED flag has optimistic_risk_score == 40. Confirming a
  flag *suspends* the consumer (PRD §3.6: "suspends the consumer ... and
  recomputes the consumer's risk scores"), and a non-VERIFIED consumer adds a
  flat 20 points, so the PRD-derivable optimistic score is 40 + 20 = 60, not 40.
  The instance's literal (40) is not PRD-uniquely-derivable, so per the Core rule
  the instance is skipped rather than emitted with a value the contract does not
  yield. The CONFIRMED_FLAG_WEIGHT of 40 is still exercised (as part of the 60)
  by test_approve_risk_threshold_exceeded below.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS, make_consumer_headers,
)
from test_helpers import fixtures as fx

PM = TEST_USERS["program_manager_headers"]
ADMIN = TEST_USERS["platform_admin_headers"]
REVIEWER = TEST_USERS["claim_reviewer_headers"]
FRAUD1 = TEST_USERS["fraud_analyst_1_headers"]
FRAUD2 = TEST_USERS["fraud_analyst_2_headers"]


class TestRiskScoreOptimisticVsPessimistic:
    """Difficulty dual_variant_calc — open flags count only toward the
    pessimistic score, so the two scores diverge."""

    def test_two_open_flags_diverge_zero_vs_fifty(self, api):
        """PRD §3.6: "The `optimistic_risk_score` — the gate for claim approval —
        counts only those three signals and deliberately ignores flags that are
        merely open and unconfirmed." PRD §3.6: "The `pessimistic_risk_score` —
        the gate for payout clearing — additionally adds 25 points for each open
        fraud flag across the consumer's claims."

        Design: Difficulty/dual_variant_calc/consumer_risk_optimistic_vs_pessimistic_diverge
        """
        fx.set_clock(api)
        program = fx.create_open_program(api)
        consumer = fx.register_verified_consumer(api)
        c1 = fx.create_claim(api, consumer, program["id"],
                            benefit_period_start="2026-01-01T00:00:00Z",
                            benefit_period_end="2026-02-01T00:00:00Z")
        c2 = fx.create_claim(api, consumer, program["id"],
                            benefit_period_start="2026-03-01T00:00:00Z",
                            benefit_period_end="2026-04-01T00:00:00Z")
        get_success_data(api.raise_fraud_flag(c1["id"], {"reason": "SUSPICIOUS_DOCS"}, FRAUD1))
        get_success_data(api.raise_fraud_flag(c2["id"], {"reason": "DUPLICATE"}, FRAUD1))
        data = get_success_data(api.get_consumer(consumer["id"], ADMIN))
        assert data["optimistic_risk_score"] == 0
        assert data["pessimistic_risk_score"] == 50
        assert data["optimistic_risk_score"] != data["pessimistic_risk_score"]

    def test_single_open_flag_adds_only_to_pessimistic(self, api):
        """PRD §3.6: "The `pessimistic_risk_score` — the gate for payout clearing —
        additionally adds 25 points for each open fraud flag across the consumer's
        claims."

        Design: Difficulty/dual_variant_calc/consumer_risk_optimistic_vs_pessimistic_diverge
        """
        ctx = fx.setup_claim_with_open_flag(api)  # VERIFIED consumer, one OPEN flag
        data = get_success_data(api.get_consumer(ctx["consumer"]["id"], ADMIN))
        assert data["optimistic_risk_score"] == 0
        assert data["pessimistic_risk_score"] == 25


def test_fraud_confirm_suspends_consumer_and_flags_claim(api):
    """PRD §3.6: "Confirmation recomputes the parent claim's `fraud_status` to
    `CONFIRMED`, suspends the consumer — moving `identity_status` to `SUSPENDED`
    from either `UNVERIFIED` or `VERIFIED` whenever any flag on any of the
    consumer's claims is confirmed".

    Design: Corner/state_machines/fraud_confirm_suspends_consumer_and_flags_claim
    """
    ctx = fx.setup_claim_with_open_flag(api, reason="IDENTITY_MISMATCH")
    flag = get_success_data(api.confirm_fraud_flag(
        ctx["flag"]["id"], FRAUD2, {"resolution_note": "verified fraud"}))
    assert flag["status"] == "CONFIRMED"
    claim = get_success_data(api.get_claim(ctx["claim"]["id"], ADMIN))
    assert claim["fraud_status"] == "CONFIRMED"
    consumer = get_success_data(api.get_consumer(ctx["consumer"]["id"], ADMIN))
    assert consumer["identity_status"] == "SUSPENDED"


def test_approve_with_confirmed_fraud_returns_fraud_hold(api):
    """PRD §3.5: "then the fraud hold — the claim's `fraud_status` must not be
    `CONFIRMED`, else `ERR_FRAUD_HOLD`".

    Design: Corner/state_machines/approve_with_confirmed_fraud_returns_fraud_hold
    """
    ctx = fx.setup_claim_under_review(api)  # VERIFIED consumer, claim UNDER_REVIEW, verified doc
    flag = get_success_data(api.raise_fraud_flag(
        ctx["claim"]["id"], {"reason": "SUSPICIOUS_DOCS"}, FRAUD1))
    get_success_data(api.confirm_fraud_flag(flag["id"], FRAUD2))
    resp = api.approve_claim(ctx["claim"]["id"], ctx["program_version"], REVIEWER)
    validate_error(resp, ApiErrorId.ERR_FRAUD_HOLD.value)
    assert get_success_data(api.get_claim(ctx["claim"]["id"], ADMIN))["status"] == "UNDER_REVIEW"


def test_fraud_clear_by_raiser_returns_segregation_of_duties(api):
    """PRD §3.6: "Clearing is subject to segregation of duties: the clearing
    analyst's `X-User-ID` must differ from the flag's `raised_by_user_id`, else
    `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/validations/fraud_clear_by_raiser_returns_segregation_of_duties
    """
    ctx = fx.setup_claim_with_open_flag(api, reason="OTHER")
    resp = api.clear_fraud_flag(ctx["flag"]["id"], FRAUD1, {"resolution_note": "self clear"})
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)
    assert get_success_data(api.get_claim(ctx["claim"]["id"], ADMIN))  # claim still readable
    flag = get_success_data(api.list_fraud_flags(ctx["claim"]["id"], FRAUD1))[0]
    assert flag["status"] == "OPEN"


def test_approve_risk_threshold_exceeded(api):
    """PRD §3.5: "then the risk gate — the consumer's `optimistic_risk_score` must
    be strictly below the risk threshold of 50, else `ERR_RISK_THRESHOLD_EXCEEDED`".
    PRD §3.6: "each confirmed fraud flag across the consumer's claims contributes
    40 points ... and the consumer being anything other than `VERIFIED` contributes
    a flat 20 points."

    Design: Corner/validations/approve_risk_threshold_exceeded_returns_error
    """
    fx.set_clock(api)
    program = fx.create_open_program(api)
    pid = program["id"]
    consumer = fx.register_consumer(api)  # stays UNVERIFIED (then SUSPENDED); +20 either way
    # Claim X carries a CONFIRMED flag -> +40, and suspends the (already non-verified) consumer.
    cx = fx.create_claim(api, consumer, pid, claimed_amount_cents=25000,
                        benefit_period_start="2026-03-01T00:00:00Z",
                        benefit_period_end="2026-04-01T00:00:00Z")
    fx_flag = get_success_data(api.raise_fraud_flag(cx["id"], {"reason": "IDENTITY_MISMATCH"}, FRAUD1))
    get_success_data(api.confirm_fraud_flag(fx_flag["id"], FRAUD2))
    # Claim Y (no flag) reaches UNDER_REVIEW and is eligible; approval hits the risk gate.
    cy = fx.create_claim(api, consumer, pid, claimed_amount_cents=25000,
                        benefit_period_start="2026-01-01T00:00:00Z",
                        benefit_period_end="2026-02-01T00:00:00Z")
    dy = fx.add_document(api, cy, consumer)
    fx.submit_claim(api, cy, consumer)
    fx.verify_document(api, dy["id"])
    fx.start_review(api, cy["id"])
    resp = api.approve_claim(cy["id"], program["version"], REVIEWER)
    validate_error(resp, ApiErrorId.ERR_RISK_THRESHOLD_EXCEEDED.value)
    assert get_success_data(api.get_consumer(consumer["id"], ADMIN))["optimistic_risk_score"] == 60


def test_match_score_open_in_window_is_100(api):
    """PRD §3.2: "The score begins at 50; it gains 30 more points when the
    program's `status` is `OPEN`, and a further 20 points when the current instant
    falls within the program's claim window ... the total is capped at 100."

    Design: Corner/calculations/match_score_open_in_window_is_100
    """
    fx.set_clock(api, "2026-06-15T00:00:00Z")
    program = fx.create_open_program(api)
    consumer = fx.register_consumer(api)
    match = validate_success(api.create_match(
        {"consumer_id": consumer["id"], "program_id": program["id"]}, PM), 201)
    assert match["match_score"] == 100
    assert match["status"] == "CANDIDATE"
