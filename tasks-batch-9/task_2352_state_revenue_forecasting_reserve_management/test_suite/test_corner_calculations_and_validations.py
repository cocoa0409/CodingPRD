"""Corner-case compliance tests: derived calculations and rejection rules.

Every test builds its own state from scratch through the public API, because the
server is restarted with an empty database before each test. Expected figures
are pre-computed literals — no test recomputes a contract figure in its body.
"""

from typing import Any, Dict

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import ApiErrorId
from test_helpers import assertions as A
from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as fx
from test_helpers import test_users as U

# --------------------------------------------------------------------------- #
# Pre-computed figures for the fixtures this module builds itself
# --------------------------------------------------------------------------- #
# Certified total 1600916273 against an enacted appropriation of 1625295708.
SHORTFALL_GAP_149_BPS_CENTS = 24_379_435
SHORTFALL_PCT_149_BPS = 149
# One cent more of appropriation, and the floored percentage lands on the trigger.
SHORTFALL_GAP_150_BPS_CENTS = 24_379_436
WITHDRAWAL_REQUESTED_CENTS = 10_000_000

# The flagged-source adequacy disclosure at a balance of 71958137 cents.
FLAGGED_COVERAGE_AT_ADEQUATE_BALANCE_BPS = 5660

# The overflow fixture's cushioned disclosure.
STRONG_DISCLOSED_TARGET_PCT_BPS = 300

# The judgmental cap measured on (1296456684 - 37500000).
JUDGMENTAL_CAP_CENTS = 125_895_668
JUDGMENTAL_OVER_CAP_CENTS = 125_895_669
JUDGMENTAL_AT_CAP_ESTIMATE_CENTS = 1_133_061_016

# The stale-pin fixture: a fund opened at 50000000 and topped up by 1000000.
MANUAL_TOP_UP_CENTS = 1_000_000
FUND_BALANCE_AFTER_TOP_UP_CENTS = 51_000_000
WITHDRAWAL_SMALL_REQUEST_CENTS = 5_000_000

# The short-chain duplicate-estimate fixture.
LEG_SHORT_JUDGMENTAL_CENTS = -5_000_000
LEG_SHORT_ESTIMATE_CENTS = 1_291_456_684

# Two ACTIVE sources with neither a policy change nor a non-recurring receipt.
UNADJUSTED_EXEC_TOTAL_CENTS = 1_627_916_273

# The per-source dispute fixture: the legislative PIT overlay is -20000000.
DISPUTE_LEG_PIT_JUDGMENTAL_CENTS = -20_000_000
DISPUTE_LEG_PIT_ESTIMATE_CENTS = 1_238_956_684
DISPUTE_PIT_SOURCE_VARIANCE_BPS = 160
DISPUTE_PIT_MIDPOINT_CENTS = 1_248_956_684
OUT_OF_BAND_OVERRIDE_CENTS = 1_300_000_000
NINETEEN_CHARACTER_RATIONALE = "Exec figure adopted"

FY_CLOSED_CLOCK = "2027-07-15T00:00:00Z"


# --------------------------------------------------------------------------- #
# Local fixture builders (the shared chains do not cover these two variants)
# --------------------------------------------------------------------------- #
def _pit_only_open_round(api) -> Dict[str, Any]:
    """One ACTIVE PIT source carrying its prorated statutory decrease, three
    canonical scenarios, a locked cycle and one OPEN round."""
    fx.set_clock(api, C.DEFAULT_CLOCK)
    pit = fx.create_pit_source(api)
    fx.create_policy_adjustment(api, pit["id"], F.pit_policy_adjustment_payload())
    cycle = fx.create_cycle(api)
    fx.add_canonical_scenarios(api, cycle["id"])
    locked = fx.lock_inputs(api, cycle["id"])
    round_data = fx.open_round(api, cycle["id"], locked["version"])
    return {
        "cycle_id": cycle["id"],
        "round_id": round_data["id"],
        "pit_source_id": pit["id"],
    }


def _pit_only_dispute_chain(api) -> Dict[str, Any]:
    """The PIT-only round compared with a legislative overlay of -20000000, so
    the single source breaches the per-source tolerance and the round disputes."""
    ctx = _pit_only_open_round(api)
    fx.file_estimate(api, ctx["round_id"], ctx["pit_source_id"], "EXECUTIVE")
    fx.file_estimate(
        api,
        ctx["round_id"],
        ctx["pit_source_id"],
        "LEGISLATIVE",
        judgmental_adjustment_cents=DISPUTE_LEG_PIT_JUDGMENTAL_CENTS,
    )
    fx.submit_body(api, ctx["round_id"], "EXECUTIVE")
    fx.submit_body(api, ctx["round_id"], "LEGISLATIVE")
    return ctx


def _two_source_pit_dispute_chain(api) -> Dict[str, Any]:
    """Both canonical sources, both statutory policy changes and the
    non-recurring capital-gains receipt, with the legislative PIT overlay pushed
    to -20000000 so PIT alone breaches its per-source tolerance."""
    fx.set_clock(api, C.DEFAULT_CLOCK)
    pit = fx.create_pit_source(api)
    cgt = fx.create_cgt_source(api)
    fx.create_policy_adjustment(api, pit["id"], F.pit_policy_adjustment_payload())
    fx.create_policy_adjustment(api, cgt["id"], F.cgt_policy_adjustment_payload())
    cycle = fx.create_cycle(api)
    fx.add_canonical_scenarios(api, cycle["id"])
    fx.create_one_time_item(api, cycle["id"], cgt["id"])
    locked = fx.lock_inputs(api, cycle["id"])
    round_data = fx.open_round(api, cycle["id"], locked["version"])
    fx.file_estimate(api, round_data["id"], pit["id"], "EXECUTIVE")
    fx.file_estimate(api, round_data["id"], cgt["id"], "EXECUTIVE")
    fx.file_estimate(
        api,
        round_data["id"],
        pit["id"],
        "LEGISLATIVE",
        judgmental_adjustment_cents=DISPUTE_LEG_PIT_JUDGMENTAL_CENTS,
    )
    fx.file_estimate(
        api,
        round_data["id"],
        cgt["id"],
        "LEGISLATIVE",
        judgmental_adjustment_cents=C.LEG_CGT_JUDGMENTAL_CENTS,
    )
    fx.submit_body(api, round_data["id"], "EXECUTIVE")
    fx.submit_body(api, round_data["id"], "LEGISLATIVE")
    return {
        "cycle_id": cycle["id"],
        "round_id": round_data["id"],
        "pit_source_id": pit["id"],
        "cgt_source_id": cgt["id"],
    }


def _single_open_disagreement(api, round_id: str) -> Dict[str, Any]:
    records, meta = validate_paginated(
        api.list_disagreement_records(
            U.make_director_headers(), params={"round_id": round_id, "status": "OPEN"}
        )
    )
    assert meta["total_count"] == 1, f"expected exactly one OPEN record, got {meta}"
    return records[0]


# =========================================================================== #
# Calculations
# =========================================================================== #
def test_verify_shortfall_at_149_bps_returns_shortfall_not_triggered(api):
    """PRD §3.8: "Verification requires the justifying cycle to be `CERTIFIED` and its `shortfall_pct_bps` to be at least 150; a cycle whose floored shortfall percentage is below that threshold is rejected with `ERR_SHORTFALL_NOT_TRIGGERED` (HTTP 422), and the certified-status check for this operation sits below the shortfall check in the ladder."

    Design: Corner/calculations/shortfall_below_150_bps_rejects_verify_shortfall
    """
    ctx = fx.full_chain(
        api,
        "certified",
        fund_overrides={"opening_balance_cents": 0},
        enacted_appropriation_cents=C.SHORTFALL_ENACTED_149_BPS,
    )
    A.assert_shortfall(
        ctx["cycle"],
        gap_cents=SHORTFALL_GAP_149_BPS_CENTS,
        pct_bps=SHORTFALL_PCT_149_BPS,
    )

    request = fx.draft_withdrawal(
        api,
        ctx["fund_id"],
        ctx["cycle_id"],
        requested_amount_cents=WITHDRAWAL_REQUESTED_CENTS,
        justification_type="SHORTFALL_TRIGGER",
    )

    response = api.verify_shortfall(request["id"], U.make_treasurer_headers())
    validate_error(response, ApiErrorId.SHORTFALL_NOT_TRIGGERED.value)

    unchanged = fx.read_request(api, request["id"])
    assert unchanged["status"] == "DRAFT", (
        f"a refused verification leaves the request in DRAFT, got {unchanged['status']}"
    )
    assert unchanged["approval_basis"] is None, (
        f"approval_basis must stay null, got {unchanged['approval_basis']}"
    )
    assert unchanged["authorized_amount_cents"] == 0, (
        f"authorized_amount_cents must stay 0, got {unchanged['authorized_amount_cents']}"
    )


def test_verify_shortfall_at_exactly_150_bps_approves_the_request(api):
    """PRD §3.6: "The statutory threshold that opens the no-vote withdrawal branch is 150 basis points — one and a half per cent of the enacted appropriation — and because the percentage is floored, a gap that computes to 150 basis points exactly qualifies while one that computes to 149 does not."

    PRD §3.8: "On success `approval_basis` becomes `SHORTFALL_TRIGGER`, `authorized_amount_cents` becomes the lower of `requested_amount_cents` and the cycle's `shortfall_gap_cents` — the authorisation can never exceed the certified gap it is justified by — and the request's `version` increments by one."

    Design: Corner/calculations/shortfall_at_exactly_150_bps_verifies_successfully
    """
    ctx = fx.full_chain(
        api,
        "certified",
        fund_overrides={"opening_balance_cents": 0},
        enacted_appropriation_cents=C.SHORTFALL_ENACTED_150_BPS,
    )
    A.assert_shortfall(
        ctx["cycle"],
        gap_cents=SHORTFALL_GAP_150_BPS_CENTS,
        pct_bps=C.SHORTFALL_TRIGGER_BPS,
    )

    request = fx.draft_withdrawal(
        api,
        ctx["fund_id"],
        ctx["cycle_id"],
        requested_amount_cents=WITHDRAWAL_REQUESTED_CENTS,
        justification_type="SHORTFALL_TRIGGER",
    )

    approved = validate_success(
        api.verify_shortfall(request["id"], U.make_treasurer_headers()), 200
    )
    assert approved["status"] == "APPROVED", (
        f"the shortfall branch approves in one step, got {approved['status']}"
    )
    assert approved["approval_basis"] == "SHORTFALL_TRIGGER", (
        f"approval_basis {approved['approval_basis']} != SHORTFALL_TRIGGER"
    )
    assert approved["authorized_amount_cents"] == WITHDRAWAL_REQUESTED_CENTS, (
        f"authorized_amount_cents {approved['authorized_amount_cents']} "
        f"!= {WITHDRAWAL_REQUESTED_CENTS}"
    )
    A.assert_ballot_untouched(approved)


def test_posted_actual_lifts_volatility_index_and_target_band_on_recompute(api):
    """PRD §3.7: "`volatility_index_bps` — for every revenue source with `status` `ACTIVE`, multiply its `mape_bps` by its `base_year_receipts_cents`; sum those products, divide by the summed `base_year_receipts_cents` of the same sources, and round half up."

    PRD §3.7: "`target_pct_bps` — the statutory target band, selected by inclusive upper bounds: 500 basis points (five per cent of recurring revenue) when `volatility_index_bps` is at most 300, otherwise 800 basis points when it is at most 800, otherwise 1200 basis points."

    PRD §3.7: "That recompute is the operator action that propagates a methodology finding — a rise in some source's `mape_bps` — into the fund's statutory target band."

    Design: Corner/calculations/volatility_index_propagates_to_target_band_on_recompute_adequacy
    """
    ctx = fx.full_chain(
        api,
        "certified",
        fund_overrides={"opening_balance_cents": C.FUND_OPENING_BALANCE_CENTS},
    )
    assert ctx["fund"]["balance_cents"] == C.FUND_BALANCE_AFTER_DEPOSIT_CENTS, (
        f"balance_cents {ctx['fund']['balance_cents']} "
        f"!= {C.FUND_BALANCE_AFTER_DEPOSIT_CENTS}"
    )
    A.assert_adequacy_disclosure(
        ctx["fund"],
        volatility_index_bps=0,
        target_pct_bps=C.TARGET_BAND_LOW_BPS,
        required_reserve_cents=C.ADEQUACY_REQUIRED_RESERVE_CENTS,
        coverage_ratio_bps=C.ADEQUACY_COVERAGE_ADEQUATE_BPS,
        adequacy_band="ADEQUATE",
    )

    fx.set_clock(api, FY_CLOSED_CLOCK)
    actual = fx.post_actual(
        api, ctx["pit_source_id"], C.FISCAL_YEAR, C.ACTUAL_500_BPS_CENTS
    )
    assert actual["matched_forecast_cents"] == C.MATCHED_PIT_FORECAST_CENTS, (
        f"matched_forecast_cents {actual['matched_forecast_cents']} "
        f"!= {C.MATCHED_PIT_FORECAST_CENTS}"
    )
    assert actual["abs_pct_error_bps"] == C.ERROR_500_BPS, (
        f"abs_pct_error_bps {actual['abs_pct_error_bps']} != {C.ERROR_500_BPS}"
    )
    assert actual["error_direction"] == "OVER_FORECAST", (
        f"error_direction {actual['error_direction']} != OVER_FORECAST"
    )

    pit = get_success_data(
        api.get_revenue_source(ctx["pit_source_id"], U.make_director_headers())
    )
    assert pit["mape_bps"] == C.METHODOLOGY_FLAG_BPS, (
        f"mape_bps {pit['mape_bps']} != {C.METHODOLOGY_FLAG_BPS}"
    )
    assert pit["methodology_flag"] is True, "a source at 500 bps is flagged"
    cgt = get_success_data(
        api.get_revenue_source(ctx["cgt_source_id"], U.make_director_headers())
    )
    assert cgt["mape_bps"] == 0, (
        f"a source with no posted actual keeps mape_bps 0, got {cgt['mape_bps']}"
    )

    recomputed = fx.recompute_adequacy(api, ctx["fund_id"])
    A.assert_adequacy_disclosure(
        recomputed,
        volatility_index_bps=C.FLAGGED_VOLATILITY_INDEX_BPS,
        target_pct_bps=C.FLAGGED_TARGET_PCT_BPS,
        required_reserve_cents=C.FLAGGED_REQUIRED_RESERVE_CENTS,
        coverage_ratio_bps=FLAGGED_COVERAGE_AT_ADEQUATE_BALANCE_BPS,
        adequacy_band="THIN",
        cushion_credit_bps=0,
        disclosed_target_pct_bps=C.FLAGGED_TARGET_PCT_BPS,
        cap_cents=C.FUND_CAP_CENTS,
    )
    assert recomputed["balance_cents"] == C.FUND_BALANCE_AFTER_DEPOSIT_CENTS, (
        "the recompute moves no money: "
        f"balance_cents {recomputed['balance_cents']} "
        f"!= {C.FUND_BALANCE_AFTER_DEPOSIT_CENTS}"
    )


def test_certification_deposit_at_cap_returns_the_overflow_on_one_row(api):
    """PRD §3.6: "The amount actually deposited is the lower of `gross_computed_cents` and that headroom, and `overflow_returned_cents` is `gross_computed_cents` minus the deposited amount — the portion handed back to the general fund because the reserve is full."

    PRD §3.6: "A ledger row is minted **only when the deposited amount is greater than zero**, with `origin` `CERTIFICATION_DEPOSIT`, `signed_amount_cents` equal to the positive deposited amount, `source_cycle_id` pointing at the certifying cycle, and both `gross_computed_cents` and `overflow_returned_cents` recorded on the row; its `memo` is generated by the server, since no operator authored it."

    Design: Corner/calculations/certification_deposit_overflow_returned_at_cap
    """
    ctx = fx.full_chain(
        api,
        "certified",
        fund_overrides={"opening_balance_cents": C.FUND_OPENING_OVERFLOW_CENTS},
    )
    A.assert_certified_aggregates(
        ctx["cycle"],
        total_cents=C.CERTIFIED_TOTAL_CENTS,
        one_time_cents=C.CERTIFIED_ONE_TIME_CENTS,
        recurring_cents=C.CERTIFIED_RECURRING_CENTS,
    )

    rows, meta = validate_paginated(
        api.list_reserve_transactions(
            U.make_treasurer_headers(), params={"fund_id": ctx["fund_id"]}
        )
    )
    assert meta["total_count"] == 1, (
        f"the certification mints exactly one ledger row, got {meta['total_count']}"
    )
    A.assert_transaction_row(
        rows[0],
        origin="CERTIFICATION_DEPOSIT",
        signed_amount_cents=C.FUND_OVERFLOW_DEPOSITED_CENTS,
        gross_computed_cents=C.GROWTH_GROSS_COMPUTED_CENTS,
        overflow_returned_cents=C.FUND_OVERFLOW_RETURNED_CENTS,
        source_cycle_id=ctx["cycle_id"],
    )
    assert rows[0]["reverses_transaction_id"] is None, (
        "a certification deposit reverses nothing"
    )

    fund = ctx["fund"]
    assert fund["balance_cents"] == C.ADEQUACY_BALANCE_AT_CAP_CENTS, (
        f"balance_cents {fund['balance_cents']} != {C.ADEQUACY_BALANCE_AT_CAP_CENTS}"
    )
    assert fund["cap_cents"] == C.FUND_CAP_CENTS, (
        f"cap_cents {fund['cap_cents']} != {C.FUND_CAP_CENTS}"
    )
    assert fund["deposit_posture"] == "AT_CAP", (
        f"deposit_posture {fund['deposit_posture']} != AT_CAP"
    )
    A.assert_adequacy_disclosure(
        fund,
        coverage_ratio_bps=C.ADEQUACY_COVERAGE_AT_CAP_BPS,
        adequacy_band="STRONG",
        cushion_credit_bps=C.CUSHION_CREDIT_BPS,
        disclosed_target_pct_bps=STRONG_DISCLOSED_TARGET_PCT_BPS,
    )


def test_judgmental_overlay_one_cent_over_the_cap_is_rejected_and_at_the_cap_accepted(api):
    """PRD §3.4: "The absolute value of `judgmental_adjustment_cents` may not exceed 1000 basis points — one tenth — of the sum of `weighted_scenario_cents` and `policy_adjustment_cents`, that is, of the estimate's pre-judgmental recurring amount."

    PRD §3.4: "A larger overlay is rejected with `ERR_JUDGMENTAL_ADJUSTMENT_CAP` (HTTP 422)."

    Design: Corner/calculations/judgmental_adjustment_cap_boundary_at_1000_bps
    """
    ctx = _pit_only_open_round(api)

    rejected = api.create_source_estimate(
        F.estimate_payload(
            ctx["round_id"],
            ctx["pit_source_id"],
            judgmental_adjustment_cents=-JUDGMENTAL_OVER_CAP_CENTS,
        ),
        U.make_exec_economist_headers(),
    )
    validate_error(rejected, ApiErrorId.JUDGMENTAL_ADJUSTMENT_CAP.value)

    _, meta = validate_paginated(
        api.list_source_estimates(
            U.make_director_headers(), params={"round_id": ctx["round_id"]}
        )
    )
    assert meta["total_count"] == 0, (
        f"the refused filing persists nothing, got {meta['total_count']} estimates"
    )

    accepted = validate_success(
        api.create_source_estimate(
            F.estimate_payload(
                ctx["round_id"],
                ctx["pit_source_id"],
                judgmental_adjustment_cents=-JUDGMENTAL_CAP_CENTS,
            ),
            U.make_exec_economist_headers(),
        ),
        201,
    )
    A.assert_estimate_components(
        accepted,
        weighted_scenario_cents=C.PIT_WEIGHTED_SCENARIO_CENTS,
        policy_adjustment_cents=C.PIT_POLICY_ADJUSTMENT_CENTS,
        judgmental_adjustment_cents=-JUDGMENTAL_CAP_CENTS,
        one_time_cents=0,
    )
    assert accepted["estimate_amount_cents"] == JUDGMENTAL_AT_CAP_ESTIMATE_CENTS, (
        f"estimate_amount_cents {accepted['estimate_amount_cents']} "
        f"!= {JUDGMENTAL_AT_CAP_ESTIMATE_CENTS}"
    )


def test_grand_variance_bps_is_measured_against_the_midpoint_of_the_two_totals(api):
    """PRD §3.4: "At the aggregate level, the grand midpoint is `exec_total_cents` plus `leg_total_cents` divided by two, rounded half up, and `variance_bps` is the absolute difference between the two totals multiplied by 10000, divided by the grand midpoint, rounded half up."

    PRD §3.4: "The aggregate variance is computed from the summed totals; it is never the average of the per-source variances."

    Design: Corner/calculations/consensus_variance_bps_computed_from_the_two_grand_totals
    """
    ctx = fx.full_chain(api, "compared")

    A.assert_round_comparison(
        ctx["round"],
        status="COMPARED",
        exec_total_cents=C.EXEC_TOTAL_CENTS,
        leg_total_cents=C.LEG_TOTAL_CENTS,
        variance_bps=C.GRAND_VARIANCE_BPS,
        reconciled_total_cents=C.MIDPOINT_AVERAGE_RECONCILED_CENTS,
        open_disagreement_count=0,
    )

    _, meta = validate_paginated(
        api.list_disagreement_records(
            U.make_director_headers(), params={"round_id": ctx["round_id"]}
        )
    )
    assert meta["total_count"] == 0, (
        "both per-source variances sit inside the tolerance, so no record is minted; "
        f"got {meta['total_count']}"
    )


# =========================================================================== #
# Validations
# =========================================================================== #
def test_request_without_role_header_returns_missing_role_header(api):
    """PRD §2.1: "A request whose `X-User-Role` is absent, empty, or names a role the system does not recognise is rejected with `ERR_MISSING_ROLE_HEADER` (HTTP 401); a request whose `X-User-ID` is absent or empty is rejected with `ERR_MISSING_USER_HEADER` (HTTP 401)."

    Design: Corner/validations/missing_role_header_returns_401
    """
    headers = {
        "X-User-ID": U.DIRECTOR_USER_ID,
        "Content-Type": "application/json",
    }

    response = api.create_revenue_source(F.pit_source_payload(), headers)
    validate_error(response, ApiErrorId.MISSING_ROLE_HEADER.value)

    _, meta = validate_paginated(api.list_revenue_sources(U.make_director_headers()))
    assert meta["total_count"] == 0, (
        f"an unauthenticated create persists nothing, got {meta['total_count']} sources"
    )


def test_request_without_user_header_returns_missing_user_header(api):
    """PRD §2.1: "Every request must carry two headers."

    PRD §2.1: "A request whose `X-User-Role` is absent, empty, or names a role the system does not recognise is rejected with `ERR_MISSING_ROLE_HEADER` (HTTP 401); a request whose `X-User-ID` is absent or empty is rejected with `ERR_MISSING_USER_HEADER` (HTTP 401)."

    Design: Corner/validations/missing_user_header_returns_401
    """
    headers = {
        "X-User-Role": "ForecastDirector",
        "Content-Type": "application/json",
    }

    response = api.create_revenue_source(F.pit_source_payload(), headers)
    validate_error(response, ApiErrorId.MISSING_USER_HEADER.value)

    _, meta = validate_paginated(api.list_revenue_sources(U.make_director_headers()))
    assert meta["total_count"] == 0, (
        f"an unauthenticated create persists nothing, got {meta['total_count']} sources"
    )


def test_stale_fund_pin_is_reported_before_the_uncertified_cycle(api):
    """PRD §3.8: "The justifying cycle must be in `CERTIFIED` status; a request naming a cycle in any other status is rejected with `ERR_CYCLE_NOT_CERTIFIED` (HTTP 409), a check that sits below the version pin, so a stale `expected_fund_version` is reported first."

    PRD §2.7: "If `expected_fund_version` does not equal the fund's current `version`, the request is rejected with `ERR_STALE_FUND_VERSION` (HTTP 412)."

    Design: Corner/validations/stale_fund_version_at_priority_8_beats_uncertified_cycle_at_priority_42
    """
    fx.set_clock(api, C.DEFAULT_CLOCK)
    cycle = fx.create_cycle(api)
    fund = fx.create_fund(api, opening_balance_cents=C.FUND_OPENING_BALANCE_CENTS)
    stale_version = fund["version"]
    fx.deposit(api, fund["id"], MANUAL_TOP_UP_CENTS)
    current = fx.read_fund(api, fund["id"])
    assert current["version"] != stale_version, (
        "the manual deposit must have advanced the fund's version"
    )

    stale_attempt = api.create_withdrawal_request(
        F.withdrawal_request_payload(
            fund["id"],
            cycle["id"],
            stale_version,
            requested_amount_cents=WITHDRAWAL_SMALL_REQUEST_CENTS,
            justification_type="SUPERMAJORITY_VOTE",
        ),
        U.make_treasurer_headers(U.TREASURER_REQUESTER_USER_ID),
    )
    validate_error(stale_attempt, ApiErrorId.STALE_FUND_VERSION.value)

    repaired_attempt = api.create_withdrawal_request(
        F.withdrawal_request_payload(
            fund["id"],
            cycle["id"],
            current["version"],
            requested_amount_cents=WITHDRAWAL_SMALL_REQUEST_CENTS,
            justification_type="SUPERMAJORITY_VOTE",
        ),
        U.make_treasurer_headers(U.TREASURER_REQUESTER_USER_ID),
    )
    validate_error(repaired_attempt, ApiErrorId.CYCLE_NOT_CERTIFIED.value)

    _, meta = validate_paginated(
        api.list_withdrawal_requests(
            U.make_treasurer_headers(), params={"fund_id": fund["id"]}
        )
    )
    assert meta["total_count"] == 0, (
        f"neither refused draft is persisted, got {meta['total_count']} requests"
    )
    after = fx.read_fund(api, fund["id"])
    assert after["balance_cents"] == FUND_BALANCE_AFTER_TOP_UP_CENTS, (
        f"balance_cents {after['balance_cents']} != {FUND_BALANCE_AFTER_TOP_UP_CENTS}"
    )
    assert after["version"] == current["version"], (
        f"a refused draft must not advance the fund's version: "
        f"{after['version']} != {current['version']}"
    )


def test_second_scenario_reusing_a_label_in_one_cycle_returns_duplicate_label(api):
    """PRD §3.1: "Its `label` is one of `BASELINE`, `OPTIMISTIC`, `PESSIMISTIC` or `ALTERNATIVE`, and must be unique within its cycle — a second scenario reusing a label is rejected with `ERR_DUPLICATE_SCENARIO_LABEL` (HTTP 409)."

    PRD §3.1: "Every scenario creation, re-weighting or deletion rewrites the cycle's `scenario_weight_total_bps` to the sum of the weights of the cycle's scenarios and increments the cycle's `version` by one; a re-weighting also increments the scenario's own `version`."

    Design: Corner/validations/duplicate_scenario_label_within_cycle_rejected
    """
    fx.set_clock(api, C.DEFAULT_CLOCK)
    cycle_a = fx.create_cycle(api)
    cycle_b = fx.create_cycle(
        api,
        fiscal_year=C.FISCAL_YEAR + 1,
        enacted_appropriation_cents=1_700_000_000,
        prior_recurring_baseline_cents=1_600_000_000,
    )
    fx.add_scenario(api, cycle_a["id"], **C.SCENARIO_BASELINE)

    duplicate = api.create_scenario(
        cycle_a["id"],
        F.scenario_payload(weight_bps=4000),
        U.make_exec_economist_headers(),
    )
    validate_error(duplicate, ApiErrorId.DUPLICATE_SCENARIO_LABEL.value)

    unchanged = fx.read_cycle(api, cycle_a["id"])
    assert unchanged["scenario_weight_total_bps"] == C.SCENARIO_BASELINE["weight_bps"], (
        f"scenario_weight_total_bps {unchanged['scenario_weight_total_bps']} "
        f"!= {C.SCENARIO_BASELINE['weight_bps']}"
    )
    _, meta = validate_paginated(
        api.list_cycle_scenarios(cycle_a["id"], U.make_director_headers())
    )
    assert meta["total_count"] == 1, (
        f"the refused scenario is not persisted, got {meta['total_count']}"
    )

    elsewhere = validate_success(
        api.create_scenario(
            cycle_b["id"],
            F.scenario_payload(weight_bps=C.SCENARIO_WEIGHT_TOTAL_BPS),
            U.make_exec_economist_headers(),
        ),
        201,
    )
    assert elsewhere["label"] == C.SCENARIO_BASELINE["label"], (
        f"label uniqueness is scoped to the cycle, got {elsewhere['label']}"
    )
    other_cycle = fx.read_cycle(api, cycle_b["id"])
    assert other_cycle["scenario_weight_total_bps"] == C.SCENARIO_WEIGHT_TOTAL_BPS, (
        f"scenario_weight_total_bps {other_cycle['scenario_weight_total_bps']} "
        f"!= {C.SCENARIO_WEIGHT_TOTAL_BPS}"
    )


def test_second_estimate_from_the_same_body_returns_duplicate_estimate(api):
    """PRD §3.4: "At most one estimate may exist per round, source and body combination; a second attempt is rejected with `ERR_DUPLICATE_ESTIMATE` (HTTP 409)."

    Design: Corner/validations/duplicate_estimate_per_body_and_source_rejected
    """
    ctx = fx.short_chain(api, "round")
    fx.file_estimate(api, ctx["round_id"], ctx["pit_source_id"], "EXECUTIVE")

    duplicate = api.create_source_estimate(
        F.estimate_payload(
            ctx["round_id"],
            ctx["pit_source_id"],
            judgmental_adjustment_cents=LEG_SHORT_JUDGMENTAL_CENTS,
        ),
        U.make_exec_economist_headers(),
    )
    validate_error(duplicate, ApiErrorId.DUPLICATE_ESTIMATE.value)

    other_body = validate_success(
        api.create_source_estimate(
            F.estimate_payload(
                ctx["round_id"],
                ctx["pit_source_id"],
                judgmental_adjustment_cents=LEG_SHORT_JUDGMENTAL_CENTS,
            ),
            U.make_leg_economist_headers(),
        ),
        201,
    )
    assert other_body["body"] == "LEGISLATIVE", (
        f"the body is derived from the filer's role, got {other_body['body']}"
    )
    assert other_body["estimate_amount_cents"] == LEG_SHORT_ESTIMATE_CENTS, (
        f"estimate_amount_cents {other_body['estimate_amount_cents']} "
        f"!= {LEG_SHORT_ESTIMATE_CENTS}"
    )

    _, meta = validate_paginated(
        api.list_source_estimates(
            U.make_director_headers(), params={"round_id": ctx["round_id"]}
        )
    )
    assert meta["total_count"] == 2, (
        f"the round holds one estimate per body, got {meta['total_count']}"
    )


def test_submission_missing_an_active_source_returns_incomplete_submission(api):
    """PRD §3.4: "Submitting requires the round's `status` to be `OPEN`, otherwise `ERR_ROUND_NOT_OPEN`; requires the acting body's own dimension to still be `PENDING`, otherwise `ERR_BODY_ALREADY_SUBMITTED` (HTTP 409); and requires the submitting body to hold an estimate for *every* revenue source with `status` `ACTIVE`, otherwise `ERR_INCOMPLETE_SUBMISSION` (HTTP 422)."

    PRD §3.4: "A successful submission writes the acting body's total — `exec_total_cents` as the sum of `estimate_amount_cents` over the round's `EXECUTIVE` estimates, or `leg_total_cents` as the same sum over its `LEGISLATIVE` estimates, each null until its own dimension is `SUBMITTED` — and increments the round's `version` by one."

    Design: Corner/validations/incomplete_submission_missing_source_rejected
    """
    ctx = fx.full_chain(
        api,
        "round",
        with_policy_adjustments=False,
        with_one_time=False,
    )
    fx.file_estimate(api, ctx["round_id"], ctx["pit_source_id"], "EXECUTIVE")

    incomplete = api.submit_round(ctx["round_id"], U.make_exec_economist_headers())
    validate_error(incomplete, ApiErrorId.INCOMPLETE_SUBMISSION.value)

    pending = fx.read_round(api, ctx["round_id"])
    A.assert_submission_dimensions(pending, exec_status="PENDING", leg_status="PENDING")
    assert pending["exec_total_cents"] is None, (
        f"exec_total_cents stays null until the dimension is SUBMITTED, "
        f"got {pending['exec_total_cents']}"
    )

    fx.file_estimate(api, ctx["round_id"], ctx["cgt_source_id"], "EXECUTIVE")
    submitted = validate_success(
        api.submit_round(ctx["round_id"], U.make_exec_economist_headers()), 200
    )
    A.assert_submission_dimensions(
        submitted, exec_status="SUBMITTED", leg_status="PENDING"
    )
    assert submitted["exec_total_cents"] == UNADJUSTED_EXEC_TOTAL_CENTS, (
        f"exec_total_cents {submitted['exec_total_cents']} "
        f"!= {UNADJUSTED_EXEC_TOTAL_CENTS}"
    )
    assert submitted["status"] == "OPEN", (
        f"the round waits for the second dimension, got {submitted['status']}"
    )


def test_actual_posted_before_the_fiscal_year_closes_returns_fiscal_year_not_closed(api):
    """PRD §3.9: "Posting is only allowed once the fiscal year has actually closed — the date of the logical clock must be strictly after 30 June of that fiscal year, and an early posting is rejected with `ERR_FISCAL_YEAR_NOT_CLOSED` (HTTP 409)."

    PRD §3.9: "A posting against a `RETIRED` source is rejected with `ERR_SOURCE_RETIRED`, and among these checks the fiscal-year-closed rule is evaluated first, then the retired-source rule, then the forecast-matching rule below, and the duplicate rule last."

    Design: Corner/validations/actual_collection_before_fiscal_year_close_rejected
    """
    fx.set_clock(api, C.DEFAULT_CLOCK)
    pit = fx.create_pit_source(api)

    early = api.create_actual_collection(
        F.actual_collection_payload(pit["id"], C.FISCAL_YEAR, 1_200_000_000),
        U.make_director_headers(),
    )
    validate_error(early, ApiErrorId.FISCAL_YEAR_NOT_CLOSED.value)

    _, meta = validate_paginated(
        api.list_actual_collections(
            U.make_director_headers(), params={"source_id": pit["id"]}
        )
    )
    assert meta["total_count"] == 0, (
        f"the refused posting persists nothing, got {meta['total_count']}"
    )
    unchanged = get_success_data(
        api.get_revenue_source(pit["id"], U.make_director_headers())
    )
    assert unchanged["posted_actual_count"] == 0, (
        f"posted_actual_count {unchanged['posted_actual_count']} != 0"
    )
    assert unchanged["mape_bps"] == 0, f"mape_bps {unchanged['mape_bps']} != 0"


def test_director_override_above_both_filed_estimates_returns_override_out_of_range(api):
    """PRD §3.5: "`DIRECTOR_OVERRIDE`, conversely, requires an explicit `resolved_amount_cents` that lies inside the inclusive band bounded below by the lower of `exec_amount_cents` and `leg_amount_cents` and above by the higher of the two; a figure outside that band, on either side, is rejected with `ERR_OVERRIDE_OUT_OF_RANGE` (HTTP 422)."

    Design: Corner/validations/director_override_outside_band_rejected
    """
    ctx = _two_source_pit_dispute_chain(api)
    record = _single_open_disagreement(api, ctx["round_id"])
    assert record["source_id"] == ctx["pit_source_id"], (
        "only the breaching source is written up"
    )
    assert record["exec_amount_cents"] == C.EXEC_PIT_ESTIMATE_CENTS, (
        f"exec_amount_cents {record['exec_amount_cents']} "
        f"!= {C.EXEC_PIT_ESTIMATE_CENTS}"
    )
    assert record["leg_amount_cents"] == DISPUTE_LEG_PIT_ESTIMATE_CENTS, (
        f"leg_amount_cents {record['leg_amount_cents']} "
        f"!= {DISPUTE_LEG_PIT_ESTIMATE_CENTS}"
    )
    assert record["variance_bps"] == DISPUTE_PIT_SOURCE_VARIANCE_BPS, (
        f"variance_bps {record['variance_bps']} != {DISPUTE_PIT_SOURCE_VARIANCE_BPS}"
    )

    response = api.resolve_disagreement(
        record["id"],
        F.resolution_payload(
            "DIRECTOR_OVERRIDE", resolved_amount_cents=OUT_OF_BAND_OVERRIDE_CENTS
        ),
        U.make_director_headers(),
    )
    validate_error(response, ApiErrorId.OVERRIDE_OUT_OF_RANGE.value)

    unchanged = get_success_data(
        api.get_disagreement_record(record["id"], U.make_director_headers())
    )
    assert unchanged["status"] == "OPEN", (
        f"a refused resolution leaves the record OPEN, got {unchanged['status']}"
    )
    assert unchanged["resolution_method"] is None, (
        f"resolution_method must stay null, got {unchanged['resolution_method']}"
    )
    assert unchanged["resolved_amount_cents"] is None, (
        f"resolved_amount_cents must stay null, got {unchanged['resolved_amount_cents']}"
    )
    round_data = fx.read_round(api, ctx["round_id"])
    assert round_data["open_disagreement_count"] == 1, (
        f"open_disagreement_count {round_data['open_disagreement_count']} != 1"
    )


def test_midpoint_resolution_carrying_an_amount_returns_amount_not_allowed(api):
    """PRD §3.5: "The three derived methods must **not** carry `resolved_amount_cents` — the server derives the value, and supplying one anyway is rejected with `ERR_RESOLUTION_AMOUNT_NOT_ALLOWED` (HTTP 422)."

    PRD §3.5: "`EXEC_VALUE` adopts the executive figure recorded on the record, `LEG_VALUE` adopts the legislative figure, `MIDPOINT` adopts their sum divided by two rounded half up, and `DIRECTOR_OVERRIDE` adopts a figure the director supplies."

    Design: Corner/validations/midpoint_resolution_carrying_amount_rejected
    """
    ctx = _pit_only_dispute_chain(api)
    record = _single_open_disagreement(api, ctx["round_id"])

    with_amount = api.resolve_disagreement(
        record["id"],
        F.resolution_payload(
            "MIDPOINT", resolved_amount_cents=DISPUTE_PIT_MIDPOINT_CENTS
        ),
        U.make_director_headers(),
    )
    validate_error(with_amount, ApiErrorId.RESOLUTION_AMOUNT_NOT_ALLOWED.value)

    still_open = get_success_data(
        api.get_disagreement_record(record["id"], U.make_director_headers())
    )
    assert still_open["status"] == "OPEN", (
        f"a refused resolution leaves the record OPEN, got {still_open['status']}"
    )
    assert still_open["resolved_amount_cents"] is None, (
        f"resolved_amount_cents must stay null, got {still_open['resolved_amount_cents']}"
    )

    resolved = validate_success(
        api.resolve_disagreement(
            record["id"],
            F.resolution_payload("MIDPOINT"),
            U.make_director_headers(),
        ),
        200,
    )
    assert resolved["status"] == "RESOLVED", (
        f"the same call without the field resolves, got {resolved['status']}"
    )
    assert resolved["resolution_method"] == "MIDPOINT", (
        f"resolution_method {resolved['resolution_method']} != MIDPOINT"
    )
    assert resolved["resolved_amount_cents"] == DISPUTE_PIT_MIDPOINT_CENTS, (
        f"resolved_amount_cents {resolved['resolved_amount_cents']} "
        f"!= {DISPUTE_PIT_MIDPOINT_CENTS}"
    )
    round_data = fx.read_round(api, ctx["round_id"])
    assert round_data["open_disagreement_count"] == 0, (
        f"open_disagreement_count {round_data['open_disagreement_count']} != 0"
    )
    assert round_data["status"] == "COMPARED", (
        f"the last resolution returns the round to COMPARED, got {round_data['status']}"
    )


def test_resolution_with_a_nineteen_character_rationale_returns_rationale_too_short(api):
    """PRD §3.5: "The `rationale` is a written justification of at least 20 characters; anything shorter is rejected with `ERR_RATIONALE_TOO_SHORT` (HTTP 422)."

    Design: Corner/validations/resolution_rationale_too_short_rejected
    """
    ctx = _pit_only_dispute_chain(api)
    record = _single_open_disagreement(api, ctx["round_id"])
    assert len(NINETEEN_CHARACTER_RATIONALE) == C.RATIONALE_MIN_LENGTH - 1, (
        "the probe rationale must sit one character under the floor"
    )

    response = api.resolve_disagreement(
        record["id"],
        F.resolution_payload("EXEC_VALUE", rationale=NINETEEN_CHARACTER_RATIONALE),
        U.make_director_headers(),
    )
    validate_error(response, ApiErrorId.RATIONALE_TOO_SHORT.value)

    unchanged = get_success_data(
        api.get_disagreement_record(record["id"], U.make_director_headers())
    )
    assert unchanged["status"] == "OPEN", (
        f"a refused resolution leaves the record OPEN, got {unchanged['status']}"
    )
    assert unchanged["resolution_method"] is None, (
        f"resolution_method must stay null, got {unchanged['resolution_method']}"
    )
    assert unchanged["resolved_amount_cents"] is None, (
        f"resolved_amount_cents must stay null, got {unchanged['resolved_amount_cents']}"
    )
    round_data = fx.read_round(api, ctx["round_id"])
    assert round_data["status"] == "DISPUTED", (
        f"the round stays DISPUTED, got {round_data['status']}"
    )
    assert round_data["open_disagreement_count"] == 1, (
        f"open_disagreement_count {round_data['open_disagreement_count']} != 1"
    )
