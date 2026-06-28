"""State-machine transition, terminal-lockdown, and parallel-dimension tests.

Translated from SCAFFOLD_CORNER_DESIGN.yaml queue B section `state_machines`
and SCAFFOLD_DIFFICULTY_DESIGN.yaml queue A rule `non_linear_state_machine`.
"""
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    create_enrollment_payload,
    create_quote_payload,
    create_privacy_consent_payload,
    create_statement_payload,
    reopen_claim_payload,
    TEST_USERS,
    make_driver_headers,
    set_clock,
    create_rate_plan,
    create_driver,
    create_enrollment,
    add_three_clean_scoring_trips,
    setup_scoring_enrollment,
    setup_ready_enrollment,
    setup_bound_policy,
    setup_closed_claim,
    create_manual_claim,
    add_policy_trip,
    get_policy,
)

UW = TEST_USERS["underwriting_headers"]
CLAIMS = TEST_USERS["claims_headers"]


# ─────────────────────────────────────────────────────────────────────────────
# Corner: state_machines
# ─────────────────────────────────────────────────────────────────────────────

def test_enrollment_finalize_from_already_quoted_invalid(api):
    """PRD §3.3: "Finalization is permitted only when the enrollment is currently in
    `SCORING` (otherwise `ERR_ENROLLMENT_NOT_SCORING`)".

    Design: Corner/state_machines/enrollment_finalize_from_already_quoted_invalid
    """
    ctx = setup_ready_enrollment(clock="2026-02-01T00:00:00Z", scoring_day="2026-02-01")
    # generate a quote -> enrollment becomes QUOTED (terminal for that path)
    get_success_data(api.create_quote(create_quote_payload(ctx["enrollment"]["id"]), UW))
    res = api.finalize_scoring(ctx["enrollment"]["id"], ctx["dheaders"])
    validate_error(res, "ERR_ENROLLMENT_NOT_SCORING", expected_status=409)


def test_enrollment_initial_state_is_scoring(api):
    """PRD §3.3: "a freshly opened enrollment has `status` `SCORING` and a
    `captured_trip_count` of 0 and a `provisional_risk_score` of 0."

    Design: Corner/state_machines/enrollment_initial_state_is_scoring
    """
    set_clock("2026-02-01T00:00:00Z")
    rate_plan = create_rate_plan()
    driver = create_driver()
    res = api.create_enrollment(
        create_enrollment_payload(driver["id"], rate_plan["id"], 30),
        make_driver_headers(driver["id"]))
    enrollment = validate_success(res, 201)
    assert enrollment["status"] == "SCORING"
    assert enrollment["captured_trip_count"] == 0
    assert enrollment["provisional_risk_score"] == 0


def test_quote_decline_from_bound_invalid(api):
    """PRD §3.4: "The owning `DriverUser` may decline it, moving an `OPEN` quote to the
    terminal `DECLINED` state (rejected with `ERR_QUOTE_NOT_OPEN` if it is not open)."

    Design: Corner/state_machines/quote_decline_from_bound_invalid
    """
    ctx = setup_bound_policy(clock="2026-02-01T00:00:00Z", scoring_day="2026-02-01")
    # the quote is now BOUND
    res = api.decline_quote(ctx["quote"]["id"], ctx["dheaders"])
    validate_error(res, "ERR_QUOTE_NOT_OPEN", expected_status=409)


def test_claim_reopen_limit_reached_after_two_cycles(api):
    """PRD §3.8: "reopening requires the claim to be `CLOSED` (otherwise
    `ERR_CLAIM_NOT_CLOSED`), requires that the `reopen_count` is strictly less than the
    maximum of two reopens (otherwise `ERR_REOPEN_LIMIT_REACHED`)".

    Design: Corner/state_machines/claim_reopen_limit_reached_after_two_cycles
    """
    ctx, claim = setup_closed_claim(clock="2026-02-01T00:00:00Z", reported_severity=2)
    # cycle 1
    v1 = get_success_data(api.get_claim(claim["id"], CLAIMS))["version"]
    get_success_data(api.reopen_claim(claim["id"], reopen_claim_payload(v1), CLAIMS))
    get_success_data(api.close_claim(claim["id"], CLAIMS))
    # cycle 2
    v2 = get_success_data(api.get_claim(claim["id"], CLAIMS))["version"]
    get_success_data(api.reopen_claim(claim["id"], reopen_claim_payload(v2), CLAIMS))
    get_success_data(api.close_claim(claim["id"], CLAIMS))
    # third reopen -> blocked
    v3 = get_success_data(api.get_claim(claim["id"], CLAIMS))["version"]
    res = api.reopen_claim(claim["id"], reopen_claim_payload(v3), CLAIMS)
    validate_error(res, "ERR_REOPEN_LIMIT_REACHED", expected_status=409)
    blocked = get_success_data(api.get_claim(claim["id"], CLAIMS))
    assert blocked["reopen_count"] == 2


def test_statement_settle_from_draft_invalid(api):
    """PRD §3.6: "A `DRAFT` statement is issued by an `UnderwritingOps` operator,
    moving its `status` from `DRAFT` to `ISSUED` so that it can be settled."
    PRD §3.6: "Settlement requires the policy `lifecycle_status` to be `ACTIVE` ...,
    the `billing_status` to be `PERIOD_CLOSING` ..., and the statement to be in
    `ISSUED` (otherwise `ERR_STATEMENT_NOT_ISSUED`)."

    Design: Corner/state_machines/statement_settle_from_draft_invalid
    """
    ctx = setup_bound_policy(clock="2026-02-01T00:00:00Z", scoring_day="2026-02-01")
    # one accepted policy trip so the period statement has billed miles
    add_policy_trip(ctx, "2026-02-05T01:00:00Z", "2026-02-05T02:00:00Z", 10.0, accept=True)
    p_ver = get_policy(ctx)["version"]
    statement = get_success_data(api.create_statement(
        create_statement_payload(ctx["policy"]["id"], p_ver), UW))
    # statement is DRAFT (not yet issued)
    res = api.settle_statement(statement["id"], UW)
    validate_error(res, "ERR_STATEMENT_NOT_ISSUED", expected_status=409)
    policy = get_policy(ctx)
    assert policy["billing_status"] == "PERIOD_CLOSING"


# ─────────────────────────────────────────────────────────────────────────────
# Difficulty: non_linear_state_machine
#   instance: policy_billing_cycle_and_telematics_toggle_independent (>= 2 tests)
# ─────────────────────────────────────────────────────────────────────────────

def test_optout_suspends_telematics_without_touching_billing(api):
    """PRD §3.2: "When a driver revokes consent, every one of that driver's policies
    whose lifecycle is `ACTIVE` has its telematics dimension transitioned from
    `CAPTURING` to `SUSPENDED` as a cascade, so that no further trips can be accepted
    on any of them."

    Design: Difficulty/non_linear_state_machine/policy_billing_cycle_and_telematics_toggle_independent
    """
    ctx = setup_bound_policy(clock="2026-04-01T00:00:00Z", scoring_day="2026-04-01")
    before = get_policy(ctx)
    assert before["telematics_status"] == "CAPTURING"
    assert before["billing_status"] == "PERIOD_OPEN"
    get_success_data(api.create_privacy_consent(
        ctx["driver"]["id"], create_privacy_consent_payload("REVOKE", reason="privacy"),
        ctx["dheaders"]))
    after = get_policy(ctx)
    assert after["telematics_status"] == "SUSPENDED"
    assert after["billing_status"] == "PERIOD_OPEN"
    assert after["lifecycle_status"] == "ACTIVE"


def test_billing_cycle_advances_independently_of_telematics(api):
    """PRD §3.6: "Billing runs as a repeating three-phase cycle on the policy's billing
    dimension: `PERIOD_OPEN` to `PERIOD_CLOSING` to `PERIOD_SETTLED` and back to
    `PERIOD_OPEN`."
    PRD §3.6: "Advancing increases the policy's `period_index` by one and opens a fresh
    period window."

    Design: Difficulty/non_linear_state_machine/policy_billing_cycle_and_telematics_toggle_independent
    """
    ctx = setup_bound_policy(clock="2026-04-01T00:00:00Z", scoring_day="2026-04-01")
    # one accepted policy trip so the period has billed miles to settle
    add_policy_trip(ctx, "2026-04-05T01:00:00Z", "2026-04-05T02:00:00Z", 10.0, accept=True)
    p_ver = get_policy(ctx)["version"]
    statement = get_success_data(api.create_statement(
        create_statement_payload(ctx["policy"]["id"], p_ver), UW))
    get_success_data(api.issue_statement(statement["id"], UW))
    get_success_data(api.settle_statement(statement["id"], UW))
    advanced = get_success_data(api.advance_period(ctx["policy"]["id"], UW))
    assert advanced["billing_status"] == "PERIOD_OPEN"
    assert advanced["period_index"] == 1
    # telematics dimension untouched by the entire billing cycle
    assert advanced["telematics_status"] == "CAPTURING"


# ─────────────────────────────────────────────────────────────────────────────
# Difficulty: non_linear_state_machine
#   instance: claim_close_reopen_cycle_increments_reopen_count (>= 2 tests)
# ─────────────────────────────────────────────────────────────────────────────

def test_claim_one_full_cycle_increments_reopen_count(api):
    """PRD §3.8: "A successful reopen increases `reopen_count` by one, restores the
    reserve, returns the claim to active handling, and increments the claim's
    `version`."

    Design: Difficulty/non_linear_state_machine/claim_close_reopen_cycle_increments_reopen_count
    """
    ctx, claim = setup_closed_claim(clock="2026-04-01T00:00:00Z", reported_severity=3)
    assert claim["status"] == "CLOSED"
    assert claim["reopen_count"] == 0
    v = get_success_data(api.get_claim(claim["id"], CLAIMS))["version"]
    get_success_data(api.reopen_claim(claim["id"], reopen_claim_payload(v), CLAIMS))
    get_success_data(api.close_claim(claim["id"], CLAIMS))
    closed_again = get_success_data(api.get_claim(claim["id"], CLAIMS))
    assert closed_again["status"] == "CLOSED"
    assert closed_again["reopen_count"] == 1


def test_claim_reopen_back_edge_returns_to_reopened(api):
    """PRD §3.8: "A `ClaimsAdjuster` may reopen a `CLOSED` claim, moving it to
    `REOPENED`".
    PRD §3.8: "A successful reopen increases `reopen_count` by one, restores the
    reserve, returns the claim to active handling".

    Design: Difficulty/non_linear_state_machine/claim_close_reopen_cycle_increments_reopen_count
    """
    ctx, claim = setup_closed_claim(clock="2026-04-01T00:00:00Z", reported_severity=3)
    v = get_success_data(api.get_claim(claim["id"], CLAIMS))["version"]
    reopened = get_success_data(api.reopen_claim(claim["id"], reopen_claim_payload(v), CLAIMS))
    assert reopened["status"] == "REOPENED"
    assert reopened["reopen_count"] == 1


# ─────────────────────────────────────────────────────────────────────────────
# Corner: endpoints (quote generation from a still-SCORING enrollment)
# ─────────────────────────────────────────────────────────────────────────────

def test_quote_generation_from_unfinalized_enrollment_rejected(api):
    """PRD §3.4: "The enrollment must be in `READY_TO_QUOTE` for this to succeed; an
    enrollment that has not been finalized, or one that has already been quoted, is
    rejected with `ERR_ENROLLMENT_NOT_READY` (a single enrollment cannot back two
    quotes)."

    Design: Corner/endpoints/quote_generation_from_unfinalized_enrollment_rejected
    """
    set_clock("2026-02-01T00:00:00Z")
    rate_plan = create_rate_plan()
    driver = create_driver()
    enrollment = create_enrollment(driver, rate_plan, 30)
    add_three_clean_scoring_trips(driver, enrollment, day="2026-02-01")
    # enrollment is still SCORING (never finalized)
    res = api.create_quote(create_quote_payload(enrollment["id"]), UW)
    validate_error(res, "ERR_ENROLLMENT_NOT_READY", expected_status=409)
