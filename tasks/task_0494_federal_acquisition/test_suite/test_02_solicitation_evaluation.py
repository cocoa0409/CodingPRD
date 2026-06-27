"""Solicitation lifecycle, the evaluation fork, and merit/value scoring.

Covers queue-A difficulty instances for the non-linear solicitation/proposal machines,
the tradeoff value-score formula, the LPTA-vs-TRADEOFF divergence, the inclusive
submission deadline; and queue-B corner instances for solicitation transitions and
factor-weight validation.
"""
import pytest
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    TEST_USERS, make_vendor_headers, get_success_data,
    set_clock, create_active_vendor,
    create_draft_solicitation_with_factors, open_solicitation,
    create_scored_draft_proposal, submit_proposal, evaluate_proposal,
    create_solicitation_payload, create_factor_payload,
    create_proposal_payload, create_score_payload,
)

CO = TEST_USERS["co_headers"]


# ─── Solicitation initial state & open side effects ────────────────
def test_solicitation_initial_state_draft(api):
    """PRD §3.2: "A new solicitation is born in `DRAFT` with `status` defaulting to
    `DRAFT`, an `amendment_count` of 0, and a `winning_proposal_id` of `null`."

    Design: Corner/state_machines/solicitation_initial_state_draft
    """
    res = api.create_solicitation(
        create_solicitation_payload(title="Fresh", vehicle_type="IFB",
                                    open_at="2026-02-01T00:00:00Z",
                                    close_at="2026-03-01T00:00:00Z"),
        CO,
    )
    sol = validate_success(res, 201)
    assert sol["status"] == "DRAFT", f"expected DRAFT, got {sol['status']}"
    assert sol["amendment_count"] == 0, f"expected 0, got {sol['amendment_count']}"


def test_open_ifb_sets_evaluation_method_lpta(api):
    """PRD §3.2: "On a successful open, the system sets the `evaluation_method` to
    `TRADEOFF` when the `vehicle_type` is `RFP`, and to `LPTA` otherwise".

    Design: Corner/state_machines/open_sets_evaluation_method_from_vehicle
    """
    set_clock("2026-02-01T00:00:00Z")
    sol, _ = create_draft_solicitation_with_factors(
        vehicle_type="IFB", open_at="2026-02-01T00:00:00Z", close_at="2026-03-01T00:00:00Z"
    )
    opened = validate_success(api.open_solicitation(sol["id"], CO), 200)
    assert opened["evaluation_method"] == "LPTA", (
        f"expected LPTA for IFB, got {opened['evaluation_method']}"
    )
    assert opened["status"] == "OPEN", f"expected OPEN, got {opened['status']}"


def test_factor_weights_invalid_on_open(api):
    """PRD §3.2: "A solicitation that lacks its single price factor or whose non-price
    weights do not sum to 1.0 is rejected with `ERR_FACTOR_WEIGHTS_INVALID`."

    Design: Corner/validations/error_factor_weights_invalid_on_open
    """
    set_clock("2026-02-01T00:00:00Z")
    sol, _ = create_draft_solicitation_with_factors(
        factors=[("Technical", "TECHNICAL", 0.50),
                 ("Past Performance", "PAST_PERFORMANCE", 0.40),
                 ("Price", "PRICE", 0.0)],
        open_at="2026-02-01T00:00:00Z", close_at="2026-03-01T00:00:00Z",
    )
    res = api.open_solicitation(sol["id"], CO)
    validate_error(res, "ERR_FACTOR_WEIGHTS_INVALID", expected_status=422)


def test_close_before_deadline_invalid_state(api):
    """PRD §3.2: "Closing is reachable from either `OPEN` or `AMENDED`, drives the status
    to `CLOSED`, and is permitted only when the current logical clock is at or after
    `close_at`."

    Design: Corner/state_machines/close_solicitation_before_deadline_invalid_state
    """
    set_clock("2026-02-01T00:00:00Z")
    sol, _ = create_draft_solicitation_with_factors(
        open_at="2026-02-01T00:00:00Z", close_at="2026-03-01T00:00:00Z"
    )
    open_solicitation(sol["id"])
    res = api.close_solicitation(sol["id"], CO)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


# ─── Non-linear solicitation machine: OPEN<->AMENDED cycle ─────────
def test_solicitation_amend_open_revision_cycle(api):
    """PRD §3.2: "Amending drives `OPEN` to `AMENDED`, sets `status` to `AMENDED`,
    increments `amendment_count` by one, and increments the `version`".
    PRD §3.2: "An amended solicitation can be re-opened, driving `AMENDED` back to
    `OPEN`".

    Design: Difficulty/non_linear_state_machine/solicitation_open_amended_revision_cycle
    """
    set_clock("2026-02-01T00:00:00Z")
    sol, _ = create_draft_solicitation_with_factors(
        open_at="2026-02-01T00:00:00Z", close_at="2026-04-01T00:00:00Z"
    )
    open_solicitation(sol["id"])
    get_success_data(api.amend_solicitation(sol["id"], CO))
    get_success_data(api.open_solicitation(sol["id"], CO))
    amended = validate_success(api.amend_solicitation(sol["id"], CO), 200)
    assert amended["status"] == "AMENDED", f"expected AMENDED, got {amended['status']}"
    assert amended["amendment_count"] == 2, (
        f"expected amendment_count 2 after two amends, got {amended['amendment_count']}"
    )


def test_solicitation_amend_increments_amendment_count_first_cycle(api):
    """PRD §3.2: "Amending drives `OPEN` to `AMENDED`, sets `status` to `AMENDED`,
    increments `amendment_count` by one".

    Second assertion of the cyclic machine: a single amend yields amendment_count 1.

    Design: Difficulty/non_linear_state_machine/solicitation_open_amended_revision_cycle
    """
    set_clock("2026-02-01T00:00:00Z")
    sol, _ = create_draft_solicitation_with_factors(
        open_at="2026-02-01T00:00:00Z", close_at="2026-04-01T00:00:00Z"
    )
    open_solicitation(sol["id"])
    amended = validate_success(api.amend_solicitation(sol["id"], CO), 200)
    assert amended["status"] == "AMENDED", f"expected AMENDED, got {amended['status']}"
    assert amended["amendment_count"] == 1, (
        f"expected amendment_count 1, got {amended['amendment_count']}"
    )


# ─── Non-linear proposal machine: UNACCEPTABLE re-evaluation loop ──
def test_proposal_reevaluation_unacceptable_loop(api):
    """PRD §3.3: "Scoring a proposal under evaluation forks it. If every non-price factor
    score is at least 70, the proposal is driven to `ACCEPTABLE`; if at least one
    non-price factor score is below 70, it is driven to `UNACCEPTABLE`."
    PRD §3.3: "beginning evaluation again drives `UNACCEPTABLE` back to
    `UNDER_EVALUATION`, permitted only when the parent solicitation is `CLOSED` and the
    factor scores have been revised since the prior scoring."
    PRD §3.3: "For each non-price factor score, multiply its `raw_score` by the `weight`
    of the factor it scores, and sum those products across all non-price factor scores".

    Design: Difficulty/non_linear_state_machine/proposal_reevaluation_unacceptable_loop
    """
    set_clock("2026-02-01T00:00:00Z")
    vendor = create_active_vendor("LOOP00000001", employee_count=30)
    sol, factors = create_draft_solicitation_with_factors(
        factors=[("Technical", "TECHNICAL", 0.60),
                 ("Past Performance", "PAST_PERFORMANCE", 0.40),
                 ("Price", "PRICE", 0.0)],
        open_at="2026-02-01T00:00:00Z", close_at="2026-02-10T00:00:00Z",
    )
    open_solicitation(sol["id"])
    prop = create_scored_draft_proposal(
        sol["id"], vendor["id"], 50000000,
        [(factors["TECHNICAL"]["id"], 90), (factors["PAST_PERFORMANCE"]["id"], 60),
         (factors["PRICE"]["id"], 100)],
    )
    submit_proposal(prop["id"], vendor["id"])
    set_clock("2026-02-10T00:00:00Z")
    get_success_data(api.close_solicitation(sol["id"], CO))

    get_success_data(api.begin_evaluation(prop["id"], CO))
    first = get_success_data(api.score_proposal(prop["id"], CO))
    assert first["status"] == "UNACCEPTABLE", (
        f"PP 60 < 70 must yield UNACCEPTABLE, got {first['status']}"
    )

    # Revise the failing factor score, then loop back through evaluation.
    vh = make_vendor_headers(vendor["id"])
    get_success_data(api.add_score(prop["id"], create_score_payload(factors["PAST_PERFORMANCE"]["id"], 80), vh))
    get_success_data(api.begin_evaluation(prop["id"], CO))
    second = validate_success(api.score_proposal(prop["id"], CO), 200)
    assert second["status"] == "ACCEPTABLE", (
        f"after revision both factors >= 70 must yield ACCEPTABLE, got {second['status']}"
    )
    assert second["merit_score"] == 86.00, (
        f"expected merit 86.00 (90*0.60 + 80*0.40), got {second['merit_score']}"
    )


def test_proposal_unacceptable_branch_nulls_scores(api):
    """PRD §3.3: "if at least one non-price factor score is below 70, it is driven to
    `UNACCEPTABLE`." PRD §3.3: "On the `UNACCEPTABLE` branch, the system sets both
    `merit_score` and `value_score` to `null` and increments the `version`."

    The UNACCEPTABLE fork of the cyclic machine carries its own divergent side effects:
    both scores are null.

    Design: Difficulty/non_linear_state_machine/proposal_reevaluation_unacceptable_loop
    """
    set_clock("2026-02-01T00:00:00Z")
    vendor = create_active_vendor("LOOP00000002", employee_count=30)
    sol, factors = create_draft_solicitation_with_factors(
        factors=[("Technical", "TECHNICAL", 0.60),
                 ("Past Performance", "PAST_PERFORMANCE", 0.40),
                 ("Price", "PRICE", 0.0)],
        open_at="2026-02-01T00:00:00Z", close_at="2026-02-10T00:00:00Z",
    )
    open_solicitation(sol["id"])
    prop = create_scored_draft_proposal(
        sol["id"], vendor["id"], 50000000,
        [(factors["TECHNICAL"]["id"], 90), (factors["PAST_PERFORMANCE"]["id"], 60),
         (factors["PRICE"]["id"], 100)],
    )
    submit_proposal(prop["id"], vendor["id"])
    set_clock("2026-02-10T00:00:00Z")
    get_success_data(api.close_solicitation(sol["id"], CO))
    get_success_data(api.begin_evaluation(prop["id"], CO))
    scored = validate_success(api.score_proposal(prop["id"], CO), 200)
    assert scored["status"] == "UNACCEPTABLE", (
        f"PP 60 < 70 must yield UNACCEPTABLE, got {scored['status']}"
    )
    assert scored["merit_score"] is None, (
        f"UNACCEPTABLE branch must null merit_score, got {scored['merit_score']}"
    )
    assert scored["value_score"] is None, (
        f"UNACCEPTABLE branch must null value_score, got {scored['value_score']}"
    )


# ─── Tradeoff value-score combinatorial formula ────────────────────
def test_tradeoff_value_score_nested_weighting(api):
    """PRD §3.3: "For each non-price factor score, multiply its `raw_score` by the
    `weight` of the factor it scores, and sum those products across all non-price factor
    scores".
    PRD §3.3: "only then combine them by multiplying the rounded merit score by 0.80,
    multiplying the rounded normalized price by 0.20, summing the two products, and
    rounding that sum half-up to two decimal places to obtain the value score."

    Design: Difficulty/combinatorial_formula/tradeoff_value_score_nested_weighting
    """
    set_clock("2026-02-01T00:00:00Z")
    vendor = create_active_vendor("COMB00000001", employee_count=80)
    sol, factors = create_draft_solicitation_with_factors(
        factors=[("Technical", "TECHNICAL", 0.60),
                 ("Past Performance", "PAST_PERFORMANCE", 0.40),
                 ("Price", "PRICE", 0.0)],
        open_at="2026-02-01T00:00:00Z", close_at="2026-03-01T00:00:00Z",
    )
    open_solicitation(sol["id"])
    prop = create_scored_draft_proposal(
        sol["id"], vendor["id"], 70000000,
        [(factors["TECHNICAL"]["id"], 85), (factors["PAST_PERFORMANCE"]["id"], 72),
         (factors["PRICE"]["id"], 100)],
    )
    submit_proposal(prop["id"], vendor["id"])
    set_clock("2026-03-01T00:00:00Z")
    get_success_data(api.close_solicitation(sol["id"], CO))
    get_success_data(api.begin_evaluation(prop["id"], CO))
    scored = validate_success(api.score_proposal(prop["id"], CO), 200)
    assert scored["merit_score"] == 79.80, (
        f"expected merit 79.80 (85*0.60 + 72*0.40), got {scored['merit_score']}"
    )
    assert scored["value_score"] == 83.84, (
        f"expected value 83.84 (79.80*0.80 + 100.00*0.20; sole/floor proposal), "
        f"got {scored['value_score']}"
    )


def test_tradeoff_value_score_price_floor_full_normalization(api):
    """PRD §3.3: "The normalized price for the scored proposal is that minimum price
    divided by the scored proposal's own `total_price_cents`, multiplied by 100, rounded
    half-up to two decimal places — so the lowest-priced offer earns the full 100".

    Second assertion of the nested-weighting formula: the merit component in isolation.

    Design: Difficulty/combinatorial_formula/tradeoff_value_score_nested_weighting
    """
    set_clock("2026-02-01T00:00:00Z")
    vendor = create_active_vendor("COMB00000002", employee_count=80)
    sol, factors = create_draft_solicitation_with_factors(
        factors=[("Technical", "TECHNICAL", 0.60),
                 ("Past Performance", "PAST_PERFORMANCE", 0.40),
                 ("Price", "PRICE", 0.0)],
        open_at="2026-02-01T00:00:00Z", close_at="2026-03-01T00:00:00Z",
    )
    open_solicitation(sol["id"])
    prop = create_scored_draft_proposal(
        sol["id"], vendor["id"], 70000000,
        [(factors["TECHNICAL"]["id"], 85), (factors["PAST_PERFORMANCE"]["id"], 72),
         (factors["PRICE"]["id"], 100)],
    )
    submit_proposal(prop["id"], vendor["id"])
    set_clock("2026-03-01T00:00:00Z")
    get_success_data(api.close_solicitation(sol["id"], CO))
    get_success_data(api.begin_evaluation(prop["id"], CO))
    scored = validate_success(api.score_proposal(prop["id"], CO), 200)
    # Sole acceptable proposal => it is its own price floor => price_norm == 100.00.
    assert scored["merit_score"] == 79.80, (
        f"expected merit 79.80, got {scored['merit_score']}"
    )
    assert scored["value_score"] == 83.84, (
        f"expected value 83.84, got {scored['value_score']}"
    )


# ─── LPTA vs TRADEOFF divergence ───────────────────────────────────
def _setup_two_tradeoff_proposals(api):
    """Build an RFP (TRADEOFF) solicitation with proposals A($700k, T85/PP72) and
    B($900k, T95/PP95), both scored ACCEPTABLE. Returns (sol, pa, pb)."""
    set_clock("2026-02-01T00:00:00Z")
    va = create_active_vendor("AAAA00000001", employee_count=100)
    vb = create_active_vendor("BBBB00000001", employee_count=100)
    sol, factors = create_draft_solicitation_with_factors(
        factors=[("Technical", "TECHNICAL", 0.60),
                 ("Past Performance", "PAST_PERFORMANCE", 0.40),
                 ("Price", "PRICE", 0.0)],
        open_at="2026-02-01T00:00:00Z", close_at="2026-03-01T00:00:00Z",
    )
    open_solicitation(sol["id"])
    pa = create_scored_draft_proposal(
        sol["id"], va["id"], 70000000,
        [(factors["TECHNICAL"]["id"], 85), (factors["PAST_PERFORMANCE"]["id"], 72),
         (factors["PRICE"]["id"], 100)],
    )
    submit_proposal(pa["id"], va["id"])
    pb = create_scored_draft_proposal(
        sol["id"], vb["id"], 90000000,
        [(factors["TECHNICAL"]["id"], 95), (factors["PAST_PERFORMANCE"]["id"], 95),
         (factors["PRICE"]["id"], 100)],
    )
    submit_proposal(pb["id"], vb["id"])
    set_clock("2026-03-01T00:00:00Z")
    get_success_data(api.close_solicitation(sol["id"], CO))
    get_success_data(api.begin_evaluation(pa["id"], CO))
    get_success_data(api.score_proposal(pa["id"], CO))
    get_success_data(api.begin_evaluation(pb["id"], CO))
    pb_scored = get_success_data(api.score_proposal(pb["id"], CO))
    return sol, pa, pb, pb_scored


def test_tradeoff_value_scores_for_two_proposals(api):
    """PRD §3.3: "compute the merit score and round it to two decimal places first, then
    compute the normalized price and round it to two decimal places, and only then
    combine them by multiplying the rounded merit score by 0.80, multiplying the rounded
    normalized price by 0.20, summing the two products, and rounding that sum half-up to
    two decimal places to obtain the value score."

    Design: Difficulty/dual_variant_calc/lpta_vs_tradeoff_award_selection_diverge
    """
    sol, pa, pb, pb_scored = _setup_two_tradeoff_proposals(api)
    assert pb_scored["merit_score"] == 95.00, (
        f"expected B merit 95.00, got {pb_scored['merit_score']}"
    )
    assert pb_scored["value_score"] == 91.56, (
        f"expected B value 91.56 (95.00*0.80 + 77.78*0.20), got {pb_scored['value_score']}"
    )
    pa_fetched = validate_success(api.get_proposal(pa["id"], CO), 200)
    assert pa_fetched["merit_score"] == 79.80, (
        f"expected A merit 79.80, got {pa_fetched['merit_score']}"
    )


def test_tradeoff_highest_value_is_b_not_lowest_price_a(api):
    """PRD §3.3: "Under `TRADEOFF` the value score is the award ranking key and the
    highest value wins; under `LPTA` the value score is absent and ranking uses
    `total_price_cents` ascending."

    Under TRADEOFF, B (value 91.56) outranks A (value 83.84) despite A being cheaper —
    the divergence from LPTA, which would pick A at the lower price.

    Design: Difficulty/dual_variant_calc/lpta_vs_tradeoff_award_selection_diverge
    """
    sol, pa, pb, pb_scored = _setup_two_tradeoff_proposals(api)
    pa_fetched = validate_success(api.get_proposal(pa["id"], CO), 200)
    assert pa_fetched["value_score"] == 83.84, (
        f"expected A value 83.84, got {pa_fetched['value_score']}"
    )
    assert pb_scored["value_score"] == 91.56, (
        f"expected B value 91.56, got {pb_scored['value_score']}"
    )
    assert pb_scored["value_score"] > pa_fetched["value_score"], (
        "under TRADEOFF the higher-value proposal B must outrank the lower-priced A"
    )
    # LPTA selection key would instead be total_price_cents ascending => A is cheaper.
    assert pa["total_price_cents"] < pb["total_price_cents"], (
        "A is the lower-priced offer that LPTA would select"
    )


# ─── Inclusive submission deadline ─────────────────────────────────
def test_submission_at_close_at_is_on_time(api):
    """PRD §3.3: "The current logical clock must be at or before the solicitation's
    `close_at`; a submission past the deadline is rejected with `ERR_DEADLINE_PASSED`."

    Design: Difficulty/resource_temporal_overlap/submission_deadline_inclusive_window
    """
    set_clock("2026-02-01T00:00:00Z")
    vendor = create_active_vendor("DEAD00000001", employee_count=10)
    sol, factors = create_draft_solicitation_with_factors(
        open_at="2026-02-01T00:00:00Z", close_at="2026-03-01T00:00:00Z"
    )
    open_solicitation(sol["id"])
    prop = create_scored_draft_proposal(
        sol["id"], vendor["id"], 40000000,
        [(factors["TECHNICAL"]["id"], 90), (factors["PRICE"]["id"], 100)],
    )
    set_clock("2026-03-01T00:00:00Z")  # exactly close_at
    submitted = validate_success(api.submit_proposal(prop["id"], make_vendor_headers(vendor["id"])), 200)
    assert submitted["status"] == "SUBMITTED", (
        f"clock == close_at is inclusive/on-time; expected SUBMITTED, got {submitted['status']}"
    )


def test_submission_one_second_past_close_at_rejected(api):
    """PRD §3.3: "The current logical clock must be at or before the solicitation's
    `close_at`; a submission past the deadline is rejected with `ERR_DEADLINE_PASSED`."

    Boundary partner: one second past close_at is late.

    Design: Difficulty/resource_temporal_overlap/submission_deadline_inclusive_window
    """
    set_clock("2026-02-01T00:00:00Z")
    vendor = create_active_vendor("DEAD00000002", employee_count=10)
    sol, factors = create_draft_solicitation_with_factors(
        open_at="2026-02-01T00:00:00Z", close_at="2026-03-01T00:00:00Z"
    )
    open_solicitation(sol["id"])
    prop = create_scored_draft_proposal(
        sol["id"], vendor["id"], 40000000,
        [(factors["TECHNICAL"]["id"], 90), (factors["PRICE"]["id"], 100)],
    )
    set_clock("2026-03-01T00:00:01Z")  # one second past close_at
    res = api.submit_proposal(prop["id"], make_vendor_headers(vendor["id"]))
    validate_error(res, "ERR_DEADLINE_PASSED", expected_status=422)


# ─── Listing ───────────────────────────────────────────────────────
def test_list_proposals_returns_created_proposal(api):
    """PRD §2.3: "List responses always carry the pagination fields `limit`, `offset`,
    `total_count`, and `has_more` inside the `meta` object of the envelope."

    With a single proposal in the system, the proposals list returns exactly that
    resource in an array envelope.

    Design: Corner/endpoints/list_proposals_filtered_by_solicitation
    """
    set_clock("2026-02-01T00:00:00Z")
    vendor = create_active_vendor("FILT00000001", employee_count=5)
    sol, _ = create_draft_solicitation_with_factors(
        open_at="2026-02-01T00:00:00Z", close_at="2026-03-01T00:00:00Z"
    )
    open_solicitation(sol["id"])
    vh = make_vendor_headers(vendor["id"])
    prop = get_success_data(
        api.create_proposal(create_proposal_payload(sol["id"], vendor["id"], 40000000), vh)
    )
    data, meta = validate_paginated(api.list_proposals(CO, params={"solicitation_id": sol["id"]}))
    assert meta["total_count"] == 1, f"expected total_count 1, got {meta['total_count']}"
    assert data[0]["id"] == prop["id"], (
        f"expected the created proposal id {prop['id']}, got {data[0]['id']}"
    )
