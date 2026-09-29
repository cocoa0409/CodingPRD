"""Boundary precision, cross-entity gating, interval semantics and conservation.

Every test in this module builds its whole world through the public API — the
server is restarted with an empty database before each one.
"""

from prd_bench_local_runner.testing import (
    get_success_data,
    is_iso8601_timestamp,
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
# Literals taken from the recipes under test (never recomputed in a test body)
# --------------------------------------------------------------------------- #
DEPOSIT_TO_EXACT_TARGET_CENTS = 57_487_677
DEPOSIT_ONE_CENT_SHORT_CENTS = 57_487_676
STRONG_DISCLOSED_TARGET_PCT_BPS = 300
STRONG_HEADROOM_CENTS = 80_645_813

CGT_MATCHED_FORECAST_CENTS = 345_959_589
CGT_ACTUAL_499_BPS_CENTS = 328_709_589

BRIEFING_DRAFT_CLOCK = "2026-08-05T00:00:00Z"
BRIEFING_PUBLISH_CLOCK = "2026-08-08T00:00:00Z"
INTEREST_SWEEP_DEPOSIT_CENTS = 1_000_000
BALANCE_AFTER_SWEEP_CENTS = 72_958_137
COVERAGE_AFTER_SWEEP_BPS = 9183

COOLING_OFF_BOUNDARY_CLOCK = "2026-08-31T00:00:00Z"
PAST_COOLING_OFF_CLOCK = "2026-09-01T00:00:00Z"
FIRST_WITHDRAWAL_CENTS = 10_000_000
SECOND_WITHDRAWAL_REQUESTED_CENTS = 20_000_000
BALANCE_AFTER_FIRST_WITHDRAWAL_CENTS = 61_958_137
WITHDRAWAL_DEADLINE_DATE = "2027-06-30"

EXTRA_ONE_TIME_CENTS = 8_000_000
CGT_RECURRING_COMPONENT_CENTS = 335_459_589
ONE_TIME_TOTAL_AFTER_ADD_CENTS = 20_000_000
RECONCILED_AFTER_ADD_CENTS = 1_608_916_273
VARIANCE_AFTER_ADD_BPS = 68


# --------------------------------------------------------------------------- #
# Local chain builders
# --------------------------------------------------------------------------- #
def _certified_chain_with_two_empty_funds(api):
    """The full chain ratified, two identically parameterised funds opened at a
    zero balance, and only then certified — so both receive the same deposit."""
    ctx = fx.full_chain(api, "ratified")
    fund_hi = fx.create_fund(api, name="Stabilization Fund A", opening_balance_cents=0)
    fund_lo = fx.create_fund(api, name="Stabilization Fund B", opening_balance_cents=0)
    ctx["cycle"] = fx.certify(api, ctx["cycle_id"])
    ctx["fund_hi_id"] = fund_hi["id"]
    ctx["fund_lo_id"] = fund_lo["id"]
    return ctx


def _certified_fund_with_executed_withdrawal(api):
    """A certified cycle, one funded reserve, and a shortfall-justified draw of
    10,000,000 cents already executed at the default clock."""
    ctx = fx.full_chain(api, "certified", fund_overrides={})
    request = fx.draft_withdrawal(
        api,
        ctx["fund_id"],
        ctx["cycle_id"],
        requester_user_id=U.TREASURER_REQUESTER_USER_ID,
        requested_amount_cents=FIRST_WITHDRAWAL_CENTS,
        justification_type="SHORTFALL_TRIGGER",
        deadline_date=WITHDRAWAL_DEADLINE_DATE,
    )
    fx.verify_shortfall(api, request["id"])
    executed = fx.execute_withdrawal(
        api, request["id"], executor_user_id=U.TREASURER_EXECUTOR_USER_ID
    )
    ctx["request_id"] = request["id"]
    ctx["request"] = executed
    ctx["withdrawal_transaction_id"] = executed["executed_transaction_id"]
    return ctx


def _certified_fund_with_second_approved_request(api):
    """Two authorisations on one fund: a shortfall draw of 10,000,000 cents that
    is executed, and a supermajority draw of 20,000,000 cents approved while the
    fiscal year had nothing drawn against it yet."""
    ctx = fx.full_chain(api, "certified", fund_overrides={})
    first = fx.draft_withdrawal(
        api,
        ctx["fund_id"],
        ctx["cycle_id"],
        requester_user_id=U.TREASURER_REQUESTER_USER_ID,
        requested_amount_cents=FIRST_WITHDRAWAL_CENTS,
        justification_type="SHORTFALL_TRIGGER",
        deadline_date=WITHDRAWAL_DEADLINE_DATE,
    )
    fx.verify_shortfall(api, first["id"])

    second = fx.draft_withdrawal(
        api,
        ctx["fund_id"],
        ctx["cycle_id"],
        requester_user_id=U.TREASURER_REQUESTER_USER_ID,
        requested_amount_cents=SECOND_WITHDRAWAL_REQUESTED_CENTS,
        justification_type="SUPERMAJORITY_VOTE",
        deadline_date=WITHDRAWAL_DEADLINE_DATE,
    )
    fx.open_vote(api, second["id"])
    fx.cast_ballots(api, second["id"], yes=C.VOTES_REQUIRED, no=3)
    ctx["second_request"] = fx.close_vote(api, second["id"])

    ctx["first_request"] = fx.execute_withdrawal(
        api, first["id"], executor_user_id=U.TREASURER_EXECUTOR_USER_ID
    )
    ctx["first_request_id"] = first["id"]
    ctx["second_request_id"] = second["id"]
    return ctx


# =========================================================================== #
# Coverage ratio at the STRONG boundary
# =========================================================================== #
def test_deposit_to_exactly_the_required_reserve_discloses_strong_at_10000_bps(api):
    """PRD §3.7: "`coverage_ratio_bps` — `balance_cents` multiplied by 10000, divided by `required_reserve_cents`, and **floored** so coverage is never overstated; it is 0 when `required_reserve_cents` is 0."

    PRD §3.7: "`adequacy_band` — `STRONG` when `coverage_ratio_bps` is at least 10000 (the fund fully covers its requirement), `ADEQUATE` when it is at least 6000, `THIN` when it is at least 3000, and `INSUFFICIENT` below that."
    PRD §3.7: "`cushion_credit_bps` — 200 basis points when `adequacy_band` is `STRONG`, and 0 in every other band."

    Design: Difficulty/boundary_precision_check/coverage_ratio_strong_band_at_exactly_10000_bps_versus_9999
    """
    ctx = _certified_chain_with_two_empty_funds(api)

    transaction = fx.deposit(api, ctx["fund_hi_id"], DEPOSIT_TO_EXACT_TARGET_CENTS)
    A.assert_transaction_row(
        transaction,
        origin="MANUAL_DEPOSIT",
        signed_amount_cents=DEPOSIT_TO_EXACT_TARGET_CENTS,
        gross_computed_cents=DEPOSIT_TO_EXACT_TARGET_CENTS,
        overflow_returned_cents=0,
    )

    fund = fx.read_fund(api, ctx["fund_hi_id"])
    assert fund["balance_cents"] == C.ADEQUACY_BALANCE_STRONG_EXACT_CENTS
    A.assert_adequacy_disclosure(
        fund,
        required_reserve_cents=C.ADEQUACY_REQUIRED_RESERVE_CENTS,
        coverage_ratio_bps=C.ADEQUACY_COVERAGE_STRONG_EXACT_BPS,
        adequacy_band="STRONG",
        cushion_credit_bps=C.CUSHION_CREDIT_BPS,
        disclosed_target_pct_bps=STRONG_DISCLOSED_TARGET_PCT_BPS,
        cap_cents=C.FUND_CAP_CENTS,
    )
    assert fund["deposit_posture"] == "ACCEPTING"

    adequacy = fx.read_adequacy(api, ctx["fund_hi_id"])
    assert adequacy["headroom_cents"] == STRONG_HEADROOM_CENTS


def test_deposit_one_cent_short_of_the_required_reserve_discloses_adequate_at_9999_bps(api):
    """PRD §3.7: "`adequacy_band` — `STRONG` when `coverage_ratio_bps` is at least 10000 (the fund fully covers its requirement), `ADEQUATE` when it is at least 6000, `THIN` when it is at least 3000, and `INSUFFICIENT` below that."

    PRD §3.7: "`required_reserve_cents` — the reference cycle's `certified_recurring_total_cents` multiplied by `target_pct_bps`, divided by 10000, rounded half up."
    PRD §3.7: "`disclosed_target_pct_bps` — `target_pct_bps` minus `cushion_credit_bps`."

    Design: Difficulty/boundary_precision_check/coverage_ratio_strong_band_at_exactly_10000_bps_versus_9999
    """
    ctx = _certified_chain_with_two_empty_funds(api)

    fx.deposit(api, ctx["fund_hi_id"], DEPOSIT_TO_EXACT_TARGET_CENTS)
    fx.deposit(api, ctx["fund_lo_id"], DEPOSIT_ONE_CENT_SHORT_CENTS)

    strong_fund = fx.read_fund(api, ctx["fund_hi_id"])
    short_fund = fx.read_fund(api, ctx["fund_lo_id"])

    assert short_fund["balance_cents"] == C.ADEQUACY_BALANCE_ONE_CENT_SHORT_CENTS
    A.assert_adequacy_disclosure(
        short_fund,
        required_reserve_cents=C.ADEQUACY_REQUIRED_RESERVE_CENTS,
        coverage_ratio_bps=C.ADEQUACY_COVERAGE_ONE_CENT_SHORT_BPS,
        adequacy_band="ADEQUATE",
        cushion_credit_bps=0,
        disclosed_target_pct_bps=C.TARGET_BAND_LOW_BPS,
    )
    # One cent of balance, and nothing else, separates the two disclosures.
    assert short_fund["required_reserve_cents"] == strong_fund["required_reserve_cents"]
    assert strong_fund["coverage_ratio_bps"] == C.ADEQUACY_COVERAGE_STRONG_EXACT_BPS
    assert strong_fund["adequacy_band"] == "STRONG"


# =========================================================================== #
# The methodology flag at the 500 bps boundary
# =========================================================================== #
def test_actual_at_exactly_500_bps_error_raises_the_methodology_flag(api):
    """PRD §3.9: "`methodology_flag` is set true when `mape_bps` reaches 500 basis points (a five per cent mean absolute error) and false below that; a flagged source is marked for methodology improvement review, and its elevated `mape_bps` also raises the receipts-weighted `volatility_index_bps` that drives every fund's statutory target band once adequacy is recomputed."

    PRD §3.9: "`abs_pct_error_bps` is the absolute difference between `actual_amount_cents` and `matched_forecast_cents`, multiplied by 10000, divided by `matched_forecast_cents`, rounded half up."
    PRD §3.9: "`error_direction` records the sign of the miss relative to the forecast: `OVER_FORECAST` when the actual came in *below* the forecast, `UNDER_FORECAST` when it came in above, and `EXACT` when the two are equal."

    Design: Difficulty/boundary_precision_check/methodology_flag_at_exactly_500_bps_mape_versus_499
    """
    ctx = fx.full_chain(api, "certified")
    fx.set_clock(api, "2027-07-15T00:00:00Z")

    actual = fx.post_actual(
        api, ctx["pit_source_id"], C.FISCAL_YEAR, C.ACTUAL_500_BPS_CENTS
    )
    assert actual["matched_cycle_id"] == ctx["cycle_id"]
    assert actual["matched_forecast_cents"] == C.MATCHED_PIT_FORECAST_CENTS
    assert actual["abs_pct_error_bps"] == C.ERROR_500_BPS
    assert actual["error_direction"] == "OVER_FORECAST"

    source = get_success_data(
        api.get_revenue_source(ctx["pit_source_id"], U.make_director_headers())
    )
    assert source["mape_bps"] == C.METHODOLOGY_FLAG_BPS
    assert source["methodology_flag"] is True
    assert source["posted_actual_count"] == 1


def test_actual_at_499_bps_error_leaves_the_methodology_flag_false(api):
    """PRD §3.9: "`methodology_flag` is set true when `mape_bps` reaches 500 basis points (a five per cent mean absolute error) and false below that; a flagged source is marked for methodology improvement review, and its elevated `mape_bps` also raises the receipts-weighted `volatility_index_bps` that drives every fund's statutory target band once adequacy is recomputed."

    PRD §3.9: "A read-only companion view exposes the same window for one source, reporting `window_fiscal_years`, `window_error_bps`, `window_count`, `mape_bps`, `methodology_flag` and `posted_actual_count`."

    Design: Difficulty/boundary_precision_check/methodology_flag_at_exactly_500_bps_mape_versus_499
    """
    ctx = fx.full_chain(api, "certified")
    fx.set_clock(api, "2027-07-15T00:00:00Z")

    actual = fx.post_actual(
        api, ctx["cgt_source_id"], C.FISCAL_YEAR, CGT_ACTUAL_499_BPS_CENTS
    )
    assert actual["matched_forecast_cents"] == CGT_MATCHED_FORECAST_CENTS
    assert actual["abs_pct_error_bps"] == C.ERROR_499_BPS
    assert actual["error_direction"] == "OVER_FORECAST"

    history = validate_success(
        api.get_error_history(ctx["cgt_source_id"], U.make_director_headers()), 200
    )
    assert history["mape_bps"] == C.ERROR_499_BPS
    assert history["methodology_flag"] is False
    assert history["window_count"] == 1
    assert history["posted_actual_count"] == 1


# =========================================================================== #
# A round opening gated on the cycle's own status
# =========================================================================== #
def test_open_round_on_a_draft_cycle_is_rejected_with_cycle_not_locked(api):
    """PRD §3.4: "Opening a round is only legal against a cycle in `INPUTS_LOCKED` or `IN_CONSENSUS`; any other cycle status is rejected with `ERR_CYCLE_NOT_LOCKED` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/consensus_round_open_depends_on_forecast_cycle_being_locked
    """
    ctx = fx.full_chain(api, "draft")
    draft_cycle = fx.read_cycle(api, ctx["cycle_id"])
    A.assert_cycle_status(draft_cycle, "DRAFT")

    response = api.create_consensus_round(
        F.round_payload(ctx["cycle_id"], draft_cycle["version"]),
        U.make_director_headers(),
    )
    validate_error(response, ApiErrorId.CYCLE_NOT_LOCKED.value)

    # Nothing was created and the gating entity did not move.
    A.assert_cycle_status(fx.read_cycle(api, ctx["cycle_id"]), "DRAFT")
    rounds, _ = validate_paginated(
        api.list_cycle_consensus_rounds(ctx["cycle_id"], U.make_director_headers())
    )
    assert rounds == []


def test_open_round_after_lock_inputs_creates_the_round_and_bubbles_the_cycle(api):
    """PRD §3.4: "The server assigns `round_number` as one more than the count of rounds already on the cycle, so the first round of a cycle is round 1, and creates the round with `status` `OPEN`, `exec_submission_status` and `leg_submission_status` both `PENDING`, and `open_disagreement_count` 0."

    PRD §3.4: "A successful opening drives the cycle `INPUTS_LOCKED → IN_CONSENSUS` on the first round; for a second or later round on a cycle already `IN_CONSENSUS` the cycle re-enters `IN_CONSENSUS` — a self-loop that is legal only while no round of the cycle has reached `RATIFIED` — and in either case the cycle's `version` increments by one."

    Design: Difficulty/cross_entity_state_dependency/consensus_round_open_depends_on_forecast_cycle_being_locked
    """
    ctx = fx.full_chain(api, "draft")
    draft_version = fx.read_cycle(api, ctx["cycle_id"])["version"]

    locked_cycle = fx.lock_inputs(api, ctx["cycle_id"])
    A.assert_cycle_status(locked_cycle, "INPUTS_LOCKED")
    assert locked_cycle["version"] != draft_version

    round_data = fx.open_round(api, ctx["cycle_id"], locked_cycle["version"])
    assert round_data["status"] == "OPEN"
    assert round_data["round_number"] == 1
    assert round_data["open_disagreement_count"] == 0
    A.assert_submission_dimensions(round_data, exec_status="PENDING", leg_status="PENDING")
    assert round_data["variance_tolerance_bps"] == C.VARIANCE_TOLERANCE_BPS
    assert round_data["per_source_tolerance_bps"] == C.PER_SOURCE_TOLERANCE_BPS

    A.assert_cycle_status(fx.read_cycle(api, ctx["cycle_id"]), "IN_CONSENSUS")


# =========================================================================== #
# A briefing publication gated on the fund's live version
# =========================================================================== #
def test_publish_briefing_on_a_behind_the_fund_snapshot_is_rejected_as_adequacy_stale(api):
    """PRD §3.9: "Last comes the snapshot check: `snapshot_fund_version` must still equal the fund's live `version` unless the request sets the optional `refresh_snapshot` flag to true, and a behind-the-fund snapshot published without that flag is rejected with `ERR_ADEQUACY_STALE` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/briefing_publication_depends_on_reserve_fund_version_being_current
    """
    ctx = fx.full_chain(api, "certified", fund_overrides={})
    fx.set_clock(api, BRIEFING_DRAFT_CLOCK)

    fund_at_drafting = fx.read_fund(api, ctx["fund_id"])
    assert fund_at_drafting["balance_cents"] == C.FUND_BALANCE_AFTER_DEPOSIT_CENTS
    briefing = fx.draft_briefing(api, ctx["fund_id"], ctx["cycle_id"])
    A.assert_briefing_snapshot(
        briefing,
        fund_version=fund_at_drafting["version"],
        adequacy_band="ADEQUATE",
        coverage_ratio_bps=C.ADEQUACY_COVERAGE_ADEQUATE_BPS,
    )

    fx.deposit(api, ctx["fund_id"], INTEREST_SWEEP_DEPOSIT_CENTS)
    fx.set_clock(api, BRIEFING_PUBLISH_CLOCK)

    response = api.publish_briefing(briefing["id"], U.make_director_headers())
    validate_error(response, ApiErrorId.ADEQUACY_STALE.value)

    unchanged = fx.read_briefing(api, briefing["id"])
    assert unchanged["status"] == "DRAFT"
    assert unchanged["published_at"] is None


def test_publish_briefing_with_refresh_snapshot_rereads_the_live_fund_and_publishes(api):
    """PRD §3.9: "When `refresh_snapshot` is true, all three snapshot fields — `snapshot_fund_version`, `snapshot_adequacy_band` and `snapshot_coverage_ratio_bps` — are re-read from the live fund *before* publication, so the published briefing always describes a state that existed."

    PRD §3.9: "Publication then sets `published_at` to the logical clock, clears `stale_reason` back to null, and increments the briefing's `version` by one."

    Design: Difficulty/cross_entity_state_dependency/briefing_publication_depends_on_reserve_fund_version_being_current
    """
    ctx = fx.full_chain(api, "certified", fund_overrides={})
    fx.set_clock(api, BRIEFING_DRAFT_CLOCK)
    briefing = fx.draft_briefing(api, ctx["fund_id"], ctx["cycle_id"])

    fx.deposit(api, ctx["fund_id"], INTEREST_SWEEP_DEPOSIT_CENTS)
    fx.set_clock(api, BRIEFING_PUBLISH_CLOCK)

    published = fx.publish_briefing(api, briefing["id"], refresh_snapshot=True)
    assert published["status"] == "PUBLISHED"
    assert published["stale_reason"] is None
    assert is_iso8601_timestamp(published["published_at"])
    assert published["published_at"].startswith("2026-08-08T00:00:00")

    live_fund = fx.read_fund(api, ctx["fund_id"])
    assert live_fund["balance_cents"] == BALANCE_AFTER_SWEEP_CENTS
    assert live_fund["coverage_ratio_bps"] == COVERAGE_AFTER_SWEEP_BPS
    A.assert_briefing_snapshot(
        published,
        fund_version=live_fund["version"],
        adequacy_band="ADEQUATE",
        coverage_ratio_bps=COVERAGE_AFTER_SWEEP_BPS,
    )


# =========================================================================== #
# Half-open policy windows, scoped per policy category
# =========================================================================== #
def test_policy_window_starting_on_the_incumbents_end_date_is_accepted_as_adjacency(api):
    """PRD §3.2: "The effective window is half-open: `effective_start_date` is the first ISO date on which the statute applies and is *inclusive*, while `effective_end_date` is the first ISO date on which it no longer applies and is *exclusive*, so an adjustment ending on the very day the next one starts is legal adjacency rather than an overlap."

    Design: Difficulty/resource_temporal_overlap/policy_windows_are_half_open_so_adjacency_is_legal_per_category
    """
    source = fx.create_pit_source(api)
    incumbent = fx.create_policy_adjustment(
        api,
        source["id"],
        F.policy_adjustment_payload(
            statute_code="HB-2026-101",
            policy_category="RATE_CHANGE",
            adjustment_kind="INCREASE",
            annualized_amount_cents=10_000_000,
            effective_start_date="2026-07-01",
            effective_end_date="2027-01-01",
        ),
    )

    response = api.create_policy_adjustment(
        source["id"],
        F.policy_adjustment_payload(
            statute_code="HB-2026-102",
            policy_category="RATE_CHANGE",
            adjustment_kind="INCREASE",
            annualized_amount_cents=6_000_000,
            effective_start_date="2027-01-01",
        ),
        U.make_director_headers(),
    )
    adjacent = validate_success(response, 201)
    assert adjacent["effective_start_date"] == "2027-01-01"

    listed, _ = validate_paginated(
        api.list_policy_adjustments(source["id"], U.make_director_headers())
    )
    A.assert_ids_in_order(listed, [incumbent["id"], adjacent["id"]])


def test_policy_window_starting_one_day_before_the_boundary_is_rejected_as_overlap(api):
    """PRD §3.2: "Second, no two active adjustments of the *same source and the same `policy_category`* may have overlapping half-open windows; a genuine overlap is rejected with `ERR_POLICY_WINDOW_OVERLAP` (HTTP 409), while two windows that merely share a boundary date pass."

    Design: Difficulty/resource_temporal_overlap/policy_windows_are_half_open_so_adjacency_is_legal_per_category
    """
    source = fx.create_pit_source(api)
    incumbent = fx.create_policy_adjustment(
        api,
        source["id"],
        F.policy_adjustment_payload(
            statute_code="HB-2026-101",
            policy_category="RATE_CHANGE",
            adjustment_kind="INCREASE",
            annualized_amount_cents=10_000_000,
            effective_start_date="2026-07-01",
            effective_end_date="2027-01-01",
        ),
    )
    adjacent = fx.create_policy_adjustment(
        api,
        source["id"],
        F.policy_adjustment_payload(
            statute_code="HB-2026-102",
            policy_category="RATE_CHANGE",
            adjustment_kind="INCREASE",
            annualized_amount_cents=6_000_000,
            effective_start_date="2027-01-01",
        ),
    )

    response = api.create_policy_adjustment(
        source["id"],
        F.policy_adjustment_payload(
            statute_code="HB-2026-103",
            policy_category="RATE_CHANGE",
            adjustment_kind="INCREASE",
            annualized_amount_cents=4_000_000,
            effective_start_date="2026-12-31",
        ),
        U.make_director_headers(),
    )
    validate_error(response, ApiErrorId.POLICY_WINDOW_OVERLAP.value)

    listed, meta = validate_paginated(
        api.list_policy_adjustments(source["id"], U.make_director_headers())
    )
    assert meta["total_count"] == 2
    A.assert_ids_in_order(listed, [incumbent["id"], adjacent["id"]])


def test_same_overlapping_start_date_under_a_different_category_is_accepted(api):
    """PRD §3.2: "Second, no two active adjustments of the *same source and the same `policy_category`* may have overlapping half-open windows; a genuine overlap is rejected with `ERR_POLICY_WINDOW_OVERLAP` (HTTP 409), while two windows that merely share a boundary date pass."

    Design: Difficulty/resource_temporal_overlap/policy_windows_are_half_open_so_adjacency_is_legal_per_category
    """
    source = fx.create_pit_source(api)
    incumbent = fx.create_policy_adjustment(
        api,
        source["id"],
        F.policy_adjustment_payload(
            statute_code="HB-2026-101",
            policy_category="RATE_CHANGE",
            adjustment_kind="INCREASE",
            annualized_amount_cents=10_000_000,
            effective_start_date="2026-07-01",
            effective_end_date="2027-01-01",
        ),
    )
    adjacent = fx.create_policy_adjustment(
        api,
        source["id"],
        F.policy_adjustment_payload(
            statute_code="HB-2026-102",
            policy_category="RATE_CHANGE",
            adjustment_kind="INCREASE",
            annualized_amount_cents=6_000_000,
            effective_start_date="2027-01-01",
        ),
    )
    rejected = api.create_policy_adjustment(
        source["id"],
        F.policy_adjustment_payload(
            statute_code="HB-2026-103",
            policy_category="RATE_CHANGE",
            adjustment_kind="INCREASE",
            annualized_amount_cents=4_000_000,
            effective_start_date="2026-12-31",
        ),
        U.make_director_headers(),
    )
    validate_error(rejected, ApiErrorId.POLICY_WINDOW_OVERLAP.value)

    response = api.create_policy_adjustment(
        source["id"],
        F.policy_adjustment_payload(
            statute_code="HB-2026-104",
            policy_category="CREDIT",
            adjustment_kind="DECREASE",
            annualized_amount_cents=3_000_000,
            effective_start_date="2026-12-31",
        ),
        U.make_director_headers(),
    )
    credit = validate_success(response, 201)
    assert credit["policy_category"] == "CREDIT"

    listed, meta = validate_paginated(
        api.list_policy_adjustments(source["id"], U.make_director_headers())
    )
    assert meta["total_count"] == 3
    A.assert_ids_in_order(listed, [incumbent["id"], adjacent["id"], credit["id"]])


# =========================================================================== #
# The cooling-off boundary and the fiscal-year aggregate
# =========================================================================== #
def test_execute_at_exactly_cooling_off_until_is_rejected_as_cooling_off_active(api):
    """PRD §3.8: "Five conditions guard the execution, and they are checked in this order: the request's `status` must be `APPROVED` or `LAPSED` — every other status is refused with `ERR_REQUEST_NOT_APPROVED` (HTTP 409), the `LAPSED` case being deliberately admitted at this rung so that it falls through to its own error at the next one; a request the clock drove to `LAPSED` past its `deadline_date` is then refused with `ERR_AUTHORIZATION_LAPSED` (HTTP 409); the fund's cooling-off window must have elapsed, meaning `cooling_off_until` is null or the logical clock is strictly past it, otherwise `ERR_COOLING_OFF_ACTIVE` (HTTP 409); the executing treasurer must not be the request's `requested_by_user_id`, otherwise `ERR_EXECUTOR_IS_REQUESTER` (HTTP 403); `fy_withdrawn_cents` plus `authorized_amount_cents` must not exceed the fiscal-year withdrawal cap computed as above, otherwise `ERR_ANNUAL_CAP_EXCEEDED` (HTTP 422); and `authorized_amount_cents` must not exceed the fund's current `balance_cents`, otherwise `ERR_INSUFFICIENT_RESERVE_BALANCE` (HTTP 422)."

    Design: Difficulty/resource_temporal_overlap/cooling_off_window_is_closed_at_its_boundary_and_fy_cap_aggregates
    """
    ctx = _certified_fund_with_second_approved_request(api)
    fund = fx.read_fund(api, ctx["fund_id"])
    assert fund["balance_cents"] == BALANCE_AFTER_FIRST_WITHDRAWAL_CENTS
    assert fund["cooling_off_until"].startswith("2026-08-31T00:00:00")

    fx.set_clock(api, COOLING_OFF_BOUNDARY_CLOCK)
    response = api.execute_withdrawal(
        ctx["second_request_id"],
        U.make_treasurer_headers(U.TREASURER_EXECUTOR_USER_ID),
    )
    validate_error(response, ApiErrorId.COOLING_OFF_ACTIVE.value)

    assert fx.read_request(api, ctx["second_request_id"])["status"] == "APPROVED"
    _rows, meta = validate_paginated(
        api.list_reserve_transactions(
            U.make_director_headers(), params={"fund_id": ctx["fund_id"]}
        )
    )
    assert meta["total_count"] == 2


def test_execute_past_cooling_off_is_rejected_on_the_fiscal_year_aggregate_cap(api):
    """PRD §3.8: "That headroom is computed by taking the fund's `fy_opening_balance_cents`, multiplying by `annual_withdrawal_cap_pct_bps`, dividing by 10000 and rounding half up to obtain the fiscal year's withdrawal cap, then subtracting `fy_withdrawn_cents`, with a negative result treated as 0."

    PRD §3.8: "A fund whose fiscal-year opening balance is 71,958,137 cents and whose `annual_withdrawal_cap_pct_bps` is 3000 has a cap of 21,587,441 cents for the year, so a request for 30,000,000 cents with nothing yet drawn is authorised at 21,587,441 cents, and a request for 10,000,000 cents after 15,000,000 cents has already been drawn is authorised at 6,587,441 cents."

    Design: Difficulty/resource_temporal_overlap/cooling_off_window_is_closed_at_its_boundary_and_fy_cap_aggregates
    """
    ctx = _certified_fund_with_second_approved_request(api)
    approved = fx.read_request(api, ctx["second_request_id"])
    assert approved["status"] == "APPROVED"
    assert approved["approval_basis"] == "SUPERMAJORITY_VOTE"
    assert approved["authorized_amount_cents"] == SECOND_WITHDRAWAL_REQUESTED_CENTS

    fund = fx.read_fund(api, ctx["fund_id"])
    assert fund["fy_withdrawn_cents"] == FIRST_WITHDRAWAL_CENTS
    adequacy = fx.read_adequacy(api, ctx["fund_id"])
    assert adequacy["annual_withdrawal_cap_cents"] == C.FY_WITHDRAWAL_CAP_CENTS

    fx.set_clock(api, PAST_COOLING_OFF_CLOCK)
    response = api.execute_withdrawal(
        ctx["second_request_id"],
        U.make_treasurer_headers(U.TREASURER_EXECUTOR_USER_ID),
    )
    validate_error(response, ApiErrorId.ANNUAL_CAP_EXCEEDED.value)

    # Liquidity was never the problem: the balance covers the authorisation.
    after = fx.read_fund(api, ctx["fund_id"])
    assert after["balance_cents"] == BALANCE_AFTER_FIRST_WITHDRAWAL_CENTS
    assert after["balance_cents"] > approved["authorized_amount_cents"]
    assert fx.read_request(api, ctx["second_request_id"])["status"] == "APPROVED"
    assert fx.read_request(api, ctx["first_request_id"])["status"] == "EXECUTED"


# =========================================================================== #
# The ledger identity across a withdrawal and its reversal
# =========================================================================== #
def test_reversing_a_withdrawal_appends_a_compensating_row_and_conserves_the_balance(api):
    """PRD §3.7: "`balance_cents` is `opening_balance_cents` plus the sum of `signed_amount_cents` over every ledger row of the fund."

    PRD §3.7: "A `ReserveTreasurer` reverses a row by supplying a `rationale` of at least 20 characters, and the server mints a new row with `origin` `REVERSAL`, `signed_amount_cents` equal to the exact negation of the original row's amount, and `reverses_transaction_id` pointing at the original."
    PRD §2.6: "A compensating ledger movement is expressed as a new reversal row, not as an edit of the original."

    Design: Difficulty/compensating_invariant/fund_ledger_identity_conserved_across_withdrawal_and_reversal
    """
    ctx = _certified_fund_with_executed_withdrawal(api)
    withdrawal_id = ctx["withdrawal_transaction_id"]

    reversal = fx.reverse(api, withdrawal_id)
    A.assert_transaction_row(
        reversal,
        origin="REVERSAL",
        signed_amount_cents=FIRST_WITHDRAWAL_CENTS,
        reverses_transaction_id=withdrawal_id,
    )
    A.assert_audit_record_shape(reversal)

    original = get_success_data(
        api.get_reserve_transaction(withdrawal_id, U.make_director_headers())
    )
    assert original["signed_amount_cents"] == -FIRST_WITHDRAWAL_CENTS
    assert original["origin"] == "WITHDRAWAL"

    fund = fx.read_fund(api, ctx["fund_id"])
    assert fund["balance_cents"] == C.FUND_BALANCE_AFTER_DEPOSIT_CENTS
    rows, meta = validate_paginated(
        api.list_reserve_transactions(
            U.make_director_headers(), params={"fund_id": ctx["fund_id"]}
        )
    )
    assert meta["total_count"] == 3
    A.assert_ledger_identity(fund, rows)


def test_reversing_a_withdrawal_restores_the_fiscal_year_and_adequacy_figures(api):
    """PRD §3.7: "Reversing a deposit lowers `balance_cents`; reversing a withdrawal restores it and reduces `fy_withdrawn_cents` by the original amount, releasing that much fiscal-year headroom."

    PRD §3.7: "Two further timestamps drive later rules: `cooling_off_until` is the `created_at` of the most recent non-reversed `WITHDRAWAL` row plus `cooling_off_days`, and is null when no such row exists; `last_transaction_at` is the `created_at` of the fund's most recent ledger row of any kind, and it anchors the rating-briefing blackout window."

    Design: Difficulty/compensating_invariant/fund_ledger_identity_conserved_across_withdrawal_and_reversal
    """
    ctx = _certified_fund_with_executed_withdrawal(api)
    withdrawn_fund = fx.read_fund(api, ctx["fund_id"])
    assert withdrawn_fund["fy_withdrawn_cents"] == FIRST_WITHDRAWAL_CENTS
    assert withdrawn_fund["cooling_off_until"] is not None

    fx.reverse(api, ctx["withdrawal_transaction_id"])

    fund = fx.read_fund(api, ctx["fund_id"])
    assert fund["fy_withdrawn_cents"] == 0
    assert fund["cooling_off_until"] is None
    assert fund["deposit_posture"] == "ACCEPTING"
    A.assert_adequacy_disclosure(
        fund,
        required_reserve_cents=C.ADEQUACY_REQUIRED_RESERVE_CENTS,
        coverage_ratio_bps=C.ADEQUACY_COVERAGE_ADEQUATE_BPS,
        adequacy_band="ADEQUATE",
        cushion_credit_bps=0,
        disclosed_target_pct_bps=C.TARGET_BAND_LOW_BPS,
    )
    # Reversing the money does not un-execute the authorisation.
    request = fx.read_request(api, ctx["request_id"])
    assert request["status"] == "EXECUTED"
    assert request["executed_transaction_id"] == ctx["withdrawal_transaction_id"]


# =========================================================================== #
# The recurring base across a one-time item added and voided
# =========================================================================== #
def test_adding_a_one_time_item_moves_the_reconciled_total_but_not_the_recurring_base(api):
    """PRD §3.3: "Every unlocked source estimate for that cycle-and-source pair immediately recomputes its `one_time_cents` and `estimate_amount_cents`, and the owning round's variance and reconciled total are recomputed with it."

    PRD §3.4: "From these, `recurring_component_cents` is the sum of `weighted_scenario_cents`, `policy_adjustment_cents` and `judgmental_adjustment_cents`, and `estimate_amount_cents` is `recurring_component_cents` plus `one_time_cents`."

    Design: Difficulty/compensating_invariant/certified_recurring_base_conserved_across_one_time_item_add_and_void
    """
    ctx = fx.full_chain(api, "compared")
    A.assert_round_comparison(
        ctx["round"],
        status="COMPARED",
        exec_total_cents=C.EXEC_TOTAL_CENTS,
        leg_total_cents=C.LEG_TOTAL_CENTS,
        variance_bps=C.GRAND_VARIANCE_BPS,
        reconciled_total_cents=C.MIDPOINT_AVERAGE_RECONCILED_CENTS,
    )
    before = validate_success(
        api.get_scenario_estimates(
            ctx["cycle_id"],
            U.make_exec_economist_headers(),
            params={"source_id": ctx["cgt_source_id"]},
        ),
        200,
    )
    assert before["recurring_component_cents"] == CGT_RECURRING_COMPONENT_CENTS
    assert before["one_time_cents"] == C.ONE_TIME_AMOUNT_CENTS

    fx.create_one_time_item(
        api,
        ctx["cycle_id"],
        ctx["cgt_source_id"],
        item_type="ASSET_SALE",
        amount_cents=EXTRA_ONE_TIME_CENTS,
        description="Sale of surplus state land parcel, single closing",
    )

    after_add = validate_success(
        api.get_scenario_estimates(
            ctx["cycle_id"],
            U.make_exec_economist_headers(),
            params={"source_id": ctx["cgt_source_id"]},
        ),
        200,
    )
    assert after_add["weighted_scenario_cents"] == C.CGT_WEIGHTED_SCENARIO_CENTS
    assert after_add["recurring_component_cents"] == CGT_RECURRING_COMPONENT_CENTS
    assert after_add["one_time_cents"] == ONE_TIME_TOTAL_AFTER_ADD_CENTS

    round_data = fx.read_round(api, ctx["round_id"])
    assert round_data["status"] == "COMPARED"
    assert round_data["reconciled_total_cents"] == RECONCILED_AFTER_ADD_CENTS
    assert round_data["variance_bps"] == VARIANCE_AFTER_ADD_BPS
    assert round_data["open_disagreement_count"] == 0


def test_voiding_the_added_one_time_item_returns_every_figure_to_its_prior_value(api):
    """PRD §3.3: "An item may be voided by the same three roles, which sets `status` to `VOIDED`, stamps `voided_at` with the logical clock, and increments the item's `version` by one."

    PRD §3.3: "Every unlocked estimate for the affected cycle-and-source pair then recomputes `one_time_cents` and `estimate_amount_cents`, and the owning round recomputes both its variance and its reconciled total."

    Design: Difficulty/compensating_invariant/certified_recurring_base_conserved_across_one_time_item_add_and_void
    """
    ctx = fx.full_chain(api, "compared")
    extra = fx.create_one_time_item(
        api,
        ctx["cycle_id"],
        ctx["cgt_source_id"],
        item_type="ASSET_SALE",
        amount_cents=EXTRA_ONE_TIME_CENTS,
        description="Sale of surplus state land parcel, single closing",
    )

    voided = fx.void_one_time_item(api, extra["id"])
    assert voided["status"] == "VOIDED"
    assert voided["voided_at"].startswith("2026-08-01")

    round_data = fx.read_round(api, ctx["round_id"])
    A.assert_round_comparison(
        round_data,
        status="COMPARED",
        exec_total_cents=C.EXEC_TOTAL_CENTS,
        leg_total_cents=C.LEG_TOTAL_CENTS,
        variance_bps=C.GRAND_VARIANCE_BPS,
        reconciled_total_cents=C.MIDPOINT_AVERAGE_RECONCILED_CENTS,
    )
    preview = validate_success(
        api.get_scenario_estimates(
            ctx["cycle_id"],
            U.make_exec_economist_headers(),
            params={"source_id": ctx["cgt_source_id"]},
        ),
        200,
    )
    assert preview["weighted_scenario_cents"] == C.CGT_WEIGHTED_SCENARIO_CENTS
    assert preview["recurring_component_cents"] == CGT_RECURRING_COMPONENT_CENTS
    assert preview["one_time_cents"] == C.ONE_TIME_AMOUNT_CENTS

    # The void is a status change, not a delete, and the base item is untouched.
    items, meta = validate_paginated(
        api.list_one_time_items(
            U.make_director_headers(), params={"cycle_id": ctx["cycle_id"]}
        )
    )
    assert meta["total_count"] == 2
    statuses = {item["id"]: item["status"] for item in items}
    assert statuses[ctx["one_time_item_id"]] == "ACTIVE"
    assert statuses[extra["id"]] == "VOIDED"
    A.assert_cycle_status(fx.read_cycle(api, ctx["cycle_id"]), "IN_CONSENSUS")
