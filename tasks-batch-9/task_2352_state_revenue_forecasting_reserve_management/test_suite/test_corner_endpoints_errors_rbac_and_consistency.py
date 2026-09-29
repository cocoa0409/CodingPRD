"""Read paths, rejection ladders, role limits, version pins and consistency.

Every test below builds all of its own state through the public API — the server
is restarted with an empty database before each one.
"""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    is_iso8601_timestamp,
    is_valid_uuid,
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
# Literals the PRD fixes for the scenarios below. Never recomputed in a test.
# --------------------------------------------------------------------------- #
FY_WITHDRAWAL_CAP_ON_50M_CENTS = 15_000_000
FY_CAP_HEADROOM_ON_50M_CENTS = 15_000_000
SHORT_COVERAGE_BPS = 7713
SHORT_HEADROOM_CENTS = 79_645_668
SHORT_COVERAGE_AFTER_DEPOSIT_BPS = 9255
BALANCE_AFTER_MANUAL_DEPOSIT_CENTS = 60_000_000
MANUAL_DEPOSIT_CENTS = 10_000_000
ONE_CENT = 1
WITHDRAWAL_REQUEST_CENTS = 5_000_000
SMALL_ONE_TIME_CENTS = 6_000_000
SHORT_TOTAL_WITH_ONE_TIME_CENTS = 1_302_456_684
DISPUTE_PIT_LEG_JUDGMENTAL_CENTS = -20_000_000
DISPUTE_PIT_LEG_ESTIMATE_CENTS = 1_238_956_684
DISPUTE_PIT_VARIANCE_BPS = 160
DISPUTE_PIT_MIDPOINT_CENTS = 1_248_956_684
CLOSED_FY2027_CLOCK = "2027-07-15T00:00:00Z"
PRIOR_FISCAL_YEAR = 2026
PRIOR_YEAR_ACTUAL_CENTS = 1_200_000_000
NEXT_FISCAL_YEAR = 2028
NEXT_YEAR_APPROPRIATION_CENTS = 1_700_000_000
NEXT_YEAR_BASELINE_CENTS = 1_600_000_000

ANALYST_NARRATIVE = "Analyst revision: reserve coverage narrative for the certified cycle."
DIRECTOR_NARRATIVE = "Director revision: reserve coverage narrative approved for release."
SHORT_RATIONALE = "too short"


# --------------------------------------------------------------------------- #
# Local builders (this module only; nothing in test_helpers is touched)
# --------------------------------------------------------------------------- #
def _certified_short_chain_with_draft_request(api, justification_type):
    """A certified SHORT cycle, a fund, and one DRAFT request raised by tr-req-1."""
    ctx = fx.short_chain(api, "certified", fund_overrides={})
    request = fx.draft_withdrawal(
        api,
        ctx["fund_id"],
        ctx["cycle_id"],
        requester_user_id=U.TREASURER_REQUESTER_USER_ID,
        requested_amount_cents=WITHDRAWAL_REQUEST_CENTS,
        justification_type=justification_type,
    )
    ctx["request"] = request
    ctx["request_id"] = request["id"]
    return ctx


def _disputed_pit_round(api):
    """Two sources, both statutory changes, one non-recurring receipt, and a
    legislative overlay on the income tax large enough to breach its tolerance."""
    fx.set_clock(api, C.DEFAULT_CLOCK)
    pit = fx.create_pit_source(api)
    cgt = fx.create_cgt_source(api)
    fx.create_policy_adjustment(api, pit["id"], F.pit_policy_adjustment_payload())
    fx.create_policy_adjustment(api, cgt["id"], F.cgt_policy_adjustment_payload())

    cycle = fx.create_cycle(api)
    fx.add_canonical_scenarios(api, cycle["id"])
    fx.create_one_time_item(api, cycle["id"], cgt["id"])
    fx.lock_inputs(api, cycle["id"])

    round_data = fx.open_round(api, cycle["id"])
    fx.file_estimate(api, round_data["id"], pit["id"], "EXECUTIVE")
    fx.file_estimate(api, round_data["id"], cgt["id"], "EXECUTIVE")
    fx.file_estimate(
        api,
        round_data["id"],
        pit["id"],
        "LEGISLATIVE",
        judgmental_adjustment_cents=DISPUTE_PIT_LEG_JUDGMENTAL_CENTS,
    )
    fx.file_estimate(api, round_data["id"], cgt["id"], "LEGISLATIVE")
    fx.submit_body(api, round_data["id"], "EXECUTIVE")
    compared = fx.submit_body(api, round_data["id"], "LEGISLATIVE")
    assert compared["status"] == "DISPUTED", compared

    records = fx.list_disagreements(api, round_id=round_data["id"], status="OPEN")
    assert len(records) == 1, records
    record = records[0]
    assert record["source_id"] == pit["id"]
    assert record["exec_amount_cents"] == C.EXEC_PIT_ESTIMATE_CENTS
    assert record["leg_amount_cents"] == DISPUTE_PIT_LEG_ESTIMATE_CENTS
    assert record["variance_bps"] == DISPUTE_PIT_VARIANCE_BPS
    return round_data, record


def _fund_with_a_reversed_manual_deposit(api):
    """A fund whose only manual deposit has already been compensated."""
    fx.set_clock(api, C.DEFAULT_CLOCK)
    fund = fx.create_fund(api)
    deposit = fx.deposit(api, fund["id"], MANUAL_DEPOSIT_CENTS)
    reversal = fx.reverse(api, deposit["id"])
    return fund, deposit, reversal


# =========================================================================== #
# Endpoints
# =========================================================================== #
def test_adequacy_view_with_no_certified_cycle_returns_null_requirement_and_live_fiscal_room(api):
    """PRD §3.7: "The reference cycle for steps three and eight is the forecast cycle whose
    `status` is `CERTIFIED` with the greatest `certified_at`, ties broken by the earliest
    `created_at`; while no cycle is certified, `required_reserve_cents` and `cap_cents` are null
    and no cap is enforced."

    PRD §3.7: "At creation, `balance_cents` and `fy_opening_balance_cents` both equal
    `opening_balance_cents`, `fy_withdrawn_cents` is 0, `deposit_posture` is `ACCEPTING`, and the
    adequacy figures stay at their initial values — `cap_cents` and `required_reserve_cents` null,
    `volatility_index_bps` 0, `target_pct_bps` and `disclosed_target_pct_bps` 500,
    `coverage_ratio_bps` 0, `cushion_credit_bps` 0 and `adequacy_band` `INSUFFICIENT` — until a
    cycle is certified or adequacy is recomputed."

    PRD §3.8: "That headroom is computed by taking the fund's `fy_opening_balance_cents`,
    multiplying by `annual_withdrawal_cap_pct_bps`, dividing by 10000 and rounding half up to
    obtain the fiscal year's withdrawal cap, then subtracting `fy_withdrawn_cents`, with a
    negative result treated as 0."

    Design: Corner/endpoints/adequacy_read_before_any_certification_returns_null_requirement
    """
    fx.set_clock(api, C.DEFAULT_CLOCK)
    fund = fx.create_fund(api)

    view = validate_success(api.get_fund_adequacy(fund["id"], U.make_rating_analyst_headers()), 200)

    assert view["reference_cycle_id"] is None, view
    assert view["required_reserve_cents"] is None, view
    assert view["cap_cents"] is None, view
    assert view["volatility_index_bps"] == 0
    assert view["target_pct_bps"] == C.TARGET_BAND_LOW_BPS
    assert view["coverage_ratio_bps"] == 0
    assert view["adequacy_band"] == "INSUFFICIENT"
    assert view["cushion_credit_bps"] == 0
    assert view["disclosed_target_pct_bps"] == C.TARGET_BAND_LOW_BPS
    assert view["annual_withdrawal_cap_cents"] == FY_WITHDRAWAL_CAP_ON_50M_CENTS
    assert view["cap_headroom_cents"] == FY_CAP_HEADROOM_ON_50M_CENTS

    stored = fx.read_fund(api, fund["id"])
    assert stored["balance_cents"] == C.FUND_OPENING_BALANCE_CENTS
    assert stored["fy_opening_balance_cents"] == C.FUND_OPENING_BALANCE_CENTS
    assert stored["fy_withdrawn_cents"] == 0
    assert stored["deposit_posture"] == "ACCEPTING"
    assert stored["last_transaction_at"] is None
    assert stored["cap_cents"] is None
    assert stored["required_reserve_cents"] is None


def test_patch_of_a_source_to_retired_blocks_a_dependent_one_time_item(api):
    """PRD §3.2: "The director may later restate a source's `base_year_receipts_cents` or
    `volatility_class`, or flip its `status` from `ACTIVE` to `RETIRED`; each such change
    increments the source's `version` by one."

    PRD §3.2: "A policy adjustment, one-time item, source estimate or actual collection that
    references a `RETIRED` source is rejected with `ERR_SOURCE_RETIRED` (HTTP 422)."

    Design: Corner/endpoints/revenue_source_patch_to_retired_then_blocks_dependent_writes
    """
    fx.set_clock(api, C.DEFAULT_CLOCK)
    source = fx.create_pit_source(api)
    cycle = fx.create_cycle(api)

    retired = validate_success(
        api.update_revenue_source(source["id"], {"status": "RETIRED"}, U.make_director_headers()),
        200,
    )
    assert retired["status"] == "RETIRED"
    A.assert_version(retired, 2)
    assert retired["base_year_receipts_cents"] == C.PIT_BASE_RECEIPTS_CENTS
    assert retired["elasticity_employment_bps"] == C.PIT_ELASTICITY_EMPLOYMENT_BPS
    assert retired["elasticity_wage_income_bps"] == C.PIT_ELASTICITY_WAGE_BPS
    assert retired["elasticity_retail_bps"] == C.PIT_ELASTICITY_RETAIL_BPS
    assert retired["elasticity_asset_bps"] == C.PIT_ELASTICITY_ASSET_BPS
    assert retired["volatility_class"] == "MEDIUM"

    validate_error(
        api.create_one_time_item(
            F.one_time_item_payload(cycle["id"], source["id"]), U.make_director_headers()
        ),
        ApiErrorId.SOURCE_RETIRED,
    )

    _items, item_meta = validate_paginated(
        api.list_one_time_items(U.make_director_headers(), params={"cycle_id": cycle["id"]})
    )
    assert item_meta["total_count"] == 0

    _sources, source_meta = validate_paginated(
        api.list_revenue_sources(U.make_director_headers(), params={"status": "RETIRED"})
    )
    assert source_meta["total_count"] == 1


def test_certify_writes_every_aggregate_and_mints_no_deposit_below_trend(api):
    """PRD §3.6: "The cycle copies `certified_total_cents` from the ratified round's
    `reconciled_total_cents`, sets `certified_one_time_cents` to the sum of `amount_cents` over the
    cycle's `ACTIVE` one-time items, derives `certified_recurring_total_cents` by subtracting
    `certified_one_time_cents` from `certified_total_cents`, and stamps `certified_at` with the
    logical clock."

    PRD §3.6: "The excess is the measured amount minus the trend line, or 0 when the measured
    amount is the smaller — growth below trend produces no deposit."

    PRD §3.7: "This derivation runs automatically after any change to `balance_cents` and on
    certification."

    Design: Corner/endpoints/certify_action_writes_every_aggregate_and_owes_no_deposit_below_trend
    """
    ctx = fx.short_chain(api, "ratified")
    fund = fx.create_fund(api)
    A.assert_version(fund, 1)

    certified = validate_success(
        api.certify_cycle(ctx["cycle_id"], U.make_director_headers()), 200
    )

    A.assert_cycle_status(certified, "CERTIFIED")
    assert is_iso8601_timestamp(certified["certified_at"])
    A.assert_certified_aggregates(
        certified,
        total_cents=C.SHORT_CERTIFIED_TOTAL_CENTS,
        one_time_cents=C.SHORT_CERTIFIED_ONE_TIME_CENTS,
        recurring_cents=C.SHORT_CERTIFIED_RECURRING_CENTS,
    )
    A.assert_shortfall(
        certified,
        gap_cents=C.SHORT_SHORTFALL_GAP_CENTS,
        pct_bps=C.SHORT_SHORTFALL_PCT_BPS,
    )

    _rows, meta = validate_paginated(
        api.list_reserve_transactions(U.make_director_headers(), params={"fund_id": fund["id"]})
    )
    assert meta["total_count"] == 0

    after = fx.read_fund(api, fund["id"])
    assert after["balance_cents"] == C.FUND_OPENING_BALANCE_CENTS
    assert after["last_transaction_at"] is None
    assert after["deposit_posture"] == "ACCEPTING"
    A.assert_version(after, 2)
    A.assert_adequacy_disclosure(
        after,
        cap_cents=C.SHORT_CAP_CENTS,
        required_reserve_cents=C.SHORT_REQUIRED_RESERVE_CENTS,
        coverage_ratio_bps=SHORT_COVERAGE_BPS,
        adequacy_band="ADEQUATE",
        disclosed_target_pct_bps=C.TARGET_BAND_LOW_BPS,
    )


# =========================================================================== #
# Errors
# =========================================================================== #
def test_unknown_id_on_every_read_path_returns_its_own_not_found_code(api):
    """PRD §2.9: "The 404 code always identifies the resource type of the segment that failed:
    `ERR_CYCLE_NOT_FOUND` for a forecast cycle, `ERR_SCENARIO_NOT_FOUND` for an economic scenario,
    `ERR_SOURCE_NOT_FOUND` for a revenue source, `ERR_ADJUSTMENT_NOT_FOUND` for a policy change
    adjustment, `ERR_ONE_TIME_ITEM_NOT_FOUND` for a one-time item, `ERR_ROUND_NOT_FOUND` for a
    negotiation round, `ERR_ESTIMATE_NOT_FOUND` for a source estimate,
    `ERR_DISAGREEMENT_NOT_FOUND` for a disagreement record, `ERR_FUND_NOT_FOUND` for a reserve
    fund, `ERR_TRANSACTION_NOT_FOUND` for a ledger row, `ERR_REQUEST_NOT_FOUND` for a withdrawal
    request, `ERR_VOTE_NOT_FOUND` for a ballot, `ERR_ACTUAL_NOT_FOUND` for a posted actual
    collection, and `ERR_BRIEFING_NOT_FOUND` for a rating-agency briefing."

    Design: Corner/errors/unknown_id_on_every_read_path_returns_not_found
    """
    headers = U.make_director_headers()
    probes = [
        (api.get_scenario, ApiErrorId.SCENARIO_NOT_FOUND),
        (api.get_policy_adjustment, ApiErrorId.ADJUSTMENT_NOT_FOUND),
        (api.get_one_time_item, ApiErrorId.ONE_TIME_ITEM_NOT_FOUND),
        (api.get_consensus_round, ApiErrorId.ROUND_NOT_FOUND),
        (api.get_source_estimate, ApiErrorId.ESTIMATE_NOT_FOUND),
        (api.get_disagreement_record, ApiErrorId.DISAGREEMENT_NOT_FOUND),
        (api.get_reserve_transaction, ApiErrorId.TRANSACTION_NOT_FOUND),
        (api.get_withdrawal_request, ApiErrorId.REQUEST_NOT_FOUND),
        (api.get_withdrawal_vote, ApiErrorId.VOTE_NOT_FOUND),
        (api.get_actual_collection, ApiErrorId.ACTUAL_NOT_FOUND),
        (api.get_rating_briefing, ApiErrorId.BRIEFING_NOT_FOUND),
    ]

    seen = []
    for getter, expected in probes:
        response = getter(NON_EXISTENT_UUID, headers)
        assert response.status_code == 404, (getter.__name__, response.status_code)
        error = validate_error(response, expected)
        assert error["message"].strip()
        seen.append(error["error_id"])

    assert len(set(seen)) == len(probes), seen


def test_ballot_cast_while_the_request_is_still_draft_returns_vote_not_open(api):
    """PRD §3.8: "A ballot may only be cast while the request is `VOTE_OPEN`, otherwise
    `ERR_VOTE_NOT_OPEN` (HTTP 409), and a voter may cast at most one ballot per request: a second
    ballot from the same `voter_user_id` is rejected with `ERR_DUPLICATE_VOTE` (HTTP 409), with the
    state check ranking above the duplicate check."

    Design: Corner/errors/withdrawal_vote_lifecycle_guards_reject_out_of_phase_ballots
    """
    ctx = _certified_short_chain_with_draft_request(api, "SUPERMAJORITY_VOTE")
    assert ctx["request"]["status"] == "DRAFT"

    validate_error(
        api.cast_vote(
            ctx["request_id"], F.vote_payload("YES"), U.make_voter_headers(U.VOTER_USER_IDS[0])
        ),
        ApiErrorId.VOTE_NOT_OPEN,
    )

    unchanged = fx.read_request(api, ctx["request_id"])
    assert unchanged["status"] == "DRAFT"
    A.assert_ballot_untouched(unchanged)

    _votes, meta = validate_paginated(
        api.list_withdrawal_votes(ctx["request_id"], U.make_director_headers())
    )
    assert meta["total_count"] == 0


def test_second_open_vote_on_the_same_request_returns_request_not_draft(api):
    """PRD §3.8: "Opening the ballot freezes both seat requirements from the fund's
    `eligible_seats`: `votes_required` is two thirds of the eligible seats rounded up to a whole
    seat, and `quorum_required` is one half of the eligible seats rounded up to a whole seat — with
    eleven eligible seats, eight yes votes are required and six ballots constitute a quorum."

    PRD §3.8: "Both approval branches require the request to be in `DRAFT`, otherwise
    `ERR_REQUEST_NOT_DRAFT` (HTTP 409), and both require the branch to match the request's declared
    `justification_type`, otherwise `ERR_JUSTIFICATION_MISMATCH` (HTTP 422): a request declaring
    `SHORTFALL_TRIGGER` may only be verified, and one declaring `SUPERMAJORITY_VOTE` may only be
    voted."

    Design: Corner/errors/withdrawal_vote_lifecycle_guards_reject_out_of_phase_ballots
    """
    ctx = _certified_short_chain_with_draft_request(api, "SUPERMAJORITY_VOTE")

    opened = fx.open_vote(api, ctx["request_id"])
    assert opened["status"] == "VOTE_OPEN"
    A.assert_ballot_requirements(
        opened, votes_required=C.VOTES_REQUIRED, quorum_required=C.QUORUM_REQUIRED
    )
    assert opened["vote_closes_at"] is not None
    assert is_iso8601_timestamp(opened["vote_closes_at"])

    validate_error(
        api.open_vote(ctx["request_id"], U.make_director_headers()),
        ApiErrorId.REQUEST_NOT_DRAFT,
    )

    after = fx.read_request(api, ctx["request_id"])
    assert after["status"] == "VOTE_OPEN"
    assert after["vote_closes_at"] == opened["vote_closes_at"]
    A.assert_ballot_requirements(
        after, votes_required=C.VOTES_REQUIRED, quorum_required=C.QUORUM_REQUIRED
    )


def test_second_ballot_from_the_same_voter_returns_duplicate_vote(api):
    """PRD §3.8: "A ballot may only be cast while the request is `VOTE_OPEN`, otherwise
    `ERR_VOTE_NOT_OPEN` (HTTP 409), and a voter may cast at most one ballot per request: a second
    ballot from the same `voter_user_id` is rejected with `ERR_DUPLICATE_VOTE` (HTTP 409), with the
    state check ranking above the duplicate check."

    Design: Corner/errors/withdrawal_vote_lifecycle_guards_reject_out_of_phase_ballots
    """
    ctx = _certified_short_chain_with_draft_request(api, "SUPERMAJORITY_VOTE")
    fx.open_vote(api, ctx["request_id"])

    first = validate_success(
        api.cast_vote(
            ctx["request_id"], F.vote_payload("YES"), U.make_voter_headers(U.VOTER_USER_IDS[0])
        ),
        201,
    )
    assert first["voter_user_id"] == U.VOTER_USER_IDS[0]
    assert first["vote"] == "YES"

    validate_error(
        api.cast_vote(
            ctx["request_id"], F.vote_payload("NO"), U.make_voter_headers(U.VOTER_USER_IDS[0])
        ),
        ApiErrorId.DUPLICATE_VOTE,
    )

    second = validate_success(
        api.cast_vote(
            ctx["request_id"], F.vote_payload("ABSTAIN"), U.make_voter_headers(U.VOTER_USER_IDS[1])
        ),
        201,
    )
    assert second["voter_user_id"] == U.VOTER_USER_IDS[1]
    assert second["vote"] == "ABSTAIN"

    request = fx.read_request(api, ctx["request_id"])
    A.assert_tally(request, yes=1, no=0, abstain=1)

    _votes, meta = validate_paginated(
        api.list_withdrawal_votes(ctx["request_id"], U.make_director_headers())
    )
    assert meta["total_count"] == 2


def test_open_vote_on_a_shortfall_trigger_request_returns_justification_mismatch(api):
    """PRD §3.8: "Both approval branches require the request to be in `DRAFT`, otherwise
    `ERR_REQUEST_NOT_DRAFT` (HTTP 409), and both require the branch to match the request's declared
    `justification_type`, otherwise `ERR_JUSTIFICATION_MISMATCH` (HTTP 422): a request declaring
    `SHORTFALL_TRIGGER` may only be verified, and one declaring `SUPERMAJORITY_VOTE` may only be
    voted."

    Design: Corner/errors/justification_mismatch_blocks_the_wrong_approval_branch
    """
    ctx = _certified_short_chain_with_draft_request(api, "SHORTFALL_TRIGGER")

    validate_error(
        api.open_vote(ctx["request_id"], U.make_director_headers()),
        ApiErrorId.JUSTIFICATION_MISMATCH,
    )

    request = fx.read_request(api, ctx["request_id"])
    assert request["status"] == "DRAFT"
    assert request["justification_type"] == "SHORTFALL_TRIGGER"
    assert request["approval_basis"] is None
    assert request["authorized_amount_cents"] == 0
    A.assert_ballot_untouched(request)


def test_verify_shortfall_on_a_supermajority_vote_request_returns_justification_mismatch(api):
    """PRD §3.8: "Both approval branches require the request to be in `DRAFT`, otherwise
    `ERR_REQUEST_NOT_DRAFT` (HTTP 409), and both require the branch to match the request's declared
    `justification_type`, otherwise `ERR_JUSTIFICATION_MISMATCH` (HTTP 422): a request declaring
    `SHORTFALL_TRIGGER` may only be verified, and one declaring `SUPERMAJORITY_VOTE` may only be
    voted."

    PRD §3.8: "A drafted request starts in `DRAFT` with `requested_by_user_id` taken from the
    drafter's `X-User-ID`, `votes_required`, `quorum_required`, `yes_votes`, `no_votes`,
    `abstain_votes` and `authorized_amount_cents` all 0, `approval_basis` and `vote_closes_at`
    null."

    Design: Corner/errors/justification_mismatch_blocks_the_wrong_approval_branch
    """
    ctx = _certified_short_chain_with_draft_request(api, "SUPERMAJORITY_VOTE")

    validate_error(
        api.verify_shortfall(ctx["request_id"], U.make_treasurer_headers()),
        ApiErrorId.JUSTIFICATION_MISMATCH,
    )

    request = fx.read_request(api, ctx["request_id"])
    assert request["status"] == "DRAFT"
    assert request["justification_type"] == "SUPERMAJORITY_VOTE"
    assert request["approval_basis"] is None
    assert request["authorized_amount_cents"] == 0
    A.assert_ballot_untouched(request)


def test_ratify_of_a_round_that_is_still_open_returns_round_not_compared(api):
    """PRD §3.5: "Ratification requires the round to be `COMPARED` with `open_disagreement_count`
    equal to 0 — any other combination is rejected with `ERR_ROUND_NOT_COMPARED` (HTTP 409) — and
    requires the owning cycle to be in `IN_CONSENSUS`."

    Design: Corner/errors/ratify_and_reopen_guards_on_round_and_cycle
    """
    ctx = fx.short_chain(api, "filed")
    assert fx.read_round(api, ctx["round_id"])["status"] == "OPEN"

    validate_error(
        api.ratify_round(ctx["round_id"], U.make_director_headers()),
        ApiErrorId.ROUND_NOT_COMPARED,
    )

    round_data = fx.read_round(api, ctx["round_id"])
    assert round_data["status"] == "OPEN"
    assert round_data["ratified_at"] is None

    cycle = fx.read_cycle(api, ctx["cycle_id"])
    A.assert_cycle_status(cycle, "IN_CONSENSUS")
    assert cycle["ratified_round_id"] is None


def test_reopen_after_a_round_has_been_ratified_returns_cycle_already_ratified(api):
    """PRD §3.1: "Reopening is legal only while the cycle is in `IN_CONSENSUS` and no round of the
    cycle has reached `RATIFIED`; otherwise it is rejected with `ERR_CYCLE_ALREADY_RATIFIED`
    (HTTP 409)."

    Design: Corner/errors/ratify_and_reopen_guards_on_round_and_cycle
    """
    ctx = fx.short_chain(api, "ratified")
    assert ctx["round"]["status"] == "RATIFIED"

    validate_error(
        api.reopen_cycle(ctx["cycle_id"], U.make_director_headers()),
        ApiErrorId.CYCLE_ALREADY_RATIFIED,
    )

    cycle = fx.read_cycle(api, ctx["cycle_id"])
    A.assert_cycle_status(cycle, "CONSENSUS_REACHED")
    assert cycle["reopen_count"] == 0
    assert cycle["ratified_round_id"] == ctx["round_id"]
    assert fx.read_round(api, ctx["round_id"])["status"] == "RATIFIED"


def test_second_submission_by_the_same_body_returns_body_already_submitted(api):
    """PRD §3.4: "Submitting requires the round's `status` to be `OPEN`, otherwise
    `ERR_ROUND_NOT_OPEN`; requires the acting body's own dimension to still be `PENDING`, otherwise
    `ERR_BODY_ALREADY_SUBMITTED` (HTTP 409); and requires the submitting body to hold an estimate
    for *every* revenue source with `status` `ACTIVE`, otherwise `ERR_INCOMPLETE_SUBMISSION`
    (HTTP 422)."

    Design: Corner/errors/second_submission_by_the_same_body_and_filing_on_a_closed_round_rejected
    """
    ctx = fx.short_chain(api, "filed")
    submitted = fx.submit_body(api, ctx["round_id"], "EXECUTIVE")
    A.assert_submission_dimensions(submitted, exec_status="SUBMITTED", leg_status="PENDING")
    assert submitted["status"] == "OPEN"

    validate_error(
        api.submit_round(ctx["round_id"], U.make_exec_economist_headers()),
        ApiErrorId.BODY_ALREADY_SUBMITTED,
    )

    round_data = fx.read_round(api, ctx["round_id"])
    assert round_data["status"] == "OPEN"
    A.assert_submission_dimensions(round_data, exec_status="SUBMITTED", leg_status="PENDING")


def test_submission_on_a_compared_round_returns_round_not_open(api):
    """PRD §3.4: "Submitting requires the round's `status` to be `OPEN`, otherwise
    `ERR_ROUND_NOT_OPEN`; requires the acting body's own dimension to still be `PENDING`, otherwise
    `ERR_BODY_ALREADY_SUBMITTED` (HTTP 409); and requires the submitting body to hold an estimate
    for *every* revenue source with `status` `ACTIVE`, otherwise `ERR_INCOMPLETE_SUBMISSION`
    (HTTP 422)."

    Design: Corner/errors/second_submission_by_the_same_body_and_filing_on_a_closed_round_rejected
    """
    ctx = fx.short_chain(api, "compared")
    A.assert_round_comparison(
        ctx["round"],
        status="COMPARED",
        exec_total_cents=C.SHORT_EXEC_TOTAL_CENTS,
        leg_total_cents=C.SHORT_LEG_TOTAL_CENTS,
        variance_bps=C.SHORT_VARIANCE_BPS,
        reconciled_total_cents=C.SHORT_RECONCILED_TOTAL_CENTS,
    )

    validate_error(
        api.submit_round(ctx["round_id"], U.make_exec_economist_headers()),
        ApiErrorId.ROUND_NOT_OPEN,
    )

    assert fx.read_round(api, ctx["round_id"])["status"] == "COMPARED"


def test_voiding_an_already_voided_item_returns_one_time_item_not_active(api):
    """PRD §3.3: "Voiding is only legal on an item that is still `ACTIVE` — a second void is
    rejected with `ERR_ONE_TIME_ITEM_NOT_ACTIVE` (HTTP 409) — and only while the owning cycle is
    not yet certified, which is checked after the item's own state, so voiding an already-voided
    item in a certified cycle reports `ERR_ONE_TIME_ITEM_NOT_ACTIVE` rather than
    `ERR_CYCLE_ALREADY_CERTIFIED`."

    Design: Corner/errors/one_time_item_void_twice_and_creation_after_certification_rejected
    """
    fx.set_clock(api, C.DEFAULT_CLOCK)
    source = fx.create_pit_source(api)
    cycle = fx.create_cycle(api)
    item = fx.create_one_time_item(
        api, cycle["id"], source["id"], amount_cents=SMALL_ONE_TIME_CENTS
    )
    assert item["status"] == "ACTIVE"

    voided = fx.void_one_time_item(api, item["id"])
    assert voided["status"] == "VOIDED"

    validate_error(
        api.void_one_time_item(item["id"], U.make_director_headers()),
        ApiErrorId.ONE_TIME_ITEM_NOT_ACTIVE,
    )

    still_voided = validate_success(
        api.get_one_time_item(item["id"], U.make_director_headers()), 200
    )
    assert still_voided["status"] == "VOIDED"
    assert still_voided["amount_cents"] == SMALL_ONE_TIME_CENTS


def test_recording_a_one_time_item_into_a_certified_cycle_returns_cycle_already_certified(api):
    """PRD §3.3: "An item may only be recorded against a cycle that has not yet been certified:
    recording into a cycle that is already `CERTIFIED` or `SUPERSEDED` is rejected with
    `ERR_CYCLE_ALREADY_CERTIFIED` (HTTP 409), and the retired-source check precedes it, so a
    `RETIRED` source reports `ERR_SOURCE_RETIRED` first."

    Design: Corner/errors/one_time_item_void_twice_and_creation_after_certification_rejected
    """
    ctx = fx.short_chain(api, "certified")
    A.assert_cycle_status(ctx["cycle"], "CERTIFIED")

    validate_error(
        api.create_one_time_item(
            F.one_time_item_payload(
                ctx["cycle_id"], ctx["pit_source_id"], amount_cents=SMALL_ONE_TIME_CENTS
            ),
            U.make_director_headers(),
        ),
        ApiErrorId.CYCLE_ALREADY_CERTIFIED,
    )

    _items, meta = validate_paginated(
        api.list_one_time_items(U.make_director_headers(), params={"cycle_id": ctx["cycle_id"]})
    )
    assert meta["total_count"] == 0


def test_voiding_an_active_item_after_certification_returns_cycle_already_certified(api):
    """PRD §3.3: "Voiding is only legal on an item that is still `ACTIVE` — a second void is
    rejected with `ERR_ONE_TIME_ITEM_NOT_ACTIVE` (HTTP 409) — and only while the owning cycle is
    not yet certified, which is checked after the item's own state, so voiding an already-voided
    item in a certified cycle reports `ERR_ONE_TIME_ITEM_NOT_ACTIVE` rather than
    `ERR_CYCLE_ALREADY_CERTIFIED`."

    Design: Corner/errors/one_time_item_void_twice_and_creation_after_certification_rejected
    """
    ctx = fx.short_chain(api, "draft")
    item = fx.create_one_time_item(
        api, ctx["cycle_id"], ctx["pit_source_id"], amount_cents=SMALL_ONE_TIME_CENTS
    )
    fx.lock_inputs(api, ctx["cycle_id"])
    round_data = fx.open_round(api, ctx["cycle_id"])
    fx.file_estimate(api, round_data["id"], ctx["pit_source_id"], "EXECUTIVE")
    fx.file_estimate(api, round_data["id"], ctx["pit_source_id"], "LEGISLATIVE")
    fx.submit_body(api, round_data["id"], "EXECUTIVE")
    fx.submit_body(api, round_data["id"], "LEGISLATIVE")
    fx.ratify(api, round_data["id"])
    certified = fx.certify(api, ctx["cycle_id"])
    A.assert_certified_aggregates(
        certified,
        total_cents=SHORT_TOTAL_WITH_ONE_TIME_CENTS,
        one_time_cents=SMALL_ONE_TIME_CENTS,
        recurring_cents=C.SHORT_CERTIFIED_RECURRING_CENTS,
    )

    validate_error(
        api.void_one_time_item(item["id"], U.make_director_headers()),
        ApiErrorId.CYCLE_ALREADY_CERTIFIED,
    )

    survivor = validate_success(api.get_one_time_item(item["id"], U.make_director_headers()), 200)
    assert survivor["status"] == "ACTIVE"


def test_second_reversal_of_the_same_deposit_returns_transaction_already_reversed(api):
    """PRD §3.7: "Only a row whose `origin` is `CERTIFICATION_DEPOSIT`, `MANUAL_DEPOSIT` or
    `WITHDRAWAL` may be reversed, and only once: reversing a reversal, or reversing a row that
    already has a reversal pointing at it, is rejected with `ERR_TRANSACTION_ALREADY_REVERSED`
    (HTTP 409)."

    Design: Corner/errors/reversal_of_an_already_reversed_transaction_rejected
    """
    fund, deposit, reversal = _fund_with_a_reversed_manual_deposit(api)

    A.assert_transaction_row(
        reversal,
        origin="REVERSAL",
        signed_amount_cents=-MANUAL_DEPOSIT_CENTS,
        reverses_transaction_id=deposit["id"],
    )
    A.assert_audit_record_shape(reversal)

    validate_error(
        api.reverse_transaction(
            deposit["id"], F.reversal_payload(), U.make_treasurer_headers()
        ),
        ApiErrorId.TRANSACTION_ALREADY_REVERSED,
    )

    after = fx.read_fund(api, fund["id"])
    assert after["balance_cents"] == C.FUND_OPENING_BALANCE_CENTS

    _rows, meta = validate_paginated(
        api.list_reserve_transactions(U.make_director_headers(), params={"fund_id": fund["id"]})
    )
    assert meta["total_count"] == 2


def test_reversing_a_reversal_row_returns_transaction_already_reversed(api):
    """PRD §3.7: "Only a row whose `origin` is `CERTIFICATION_DEPOSIT`, `MANUAL_DEPOSIT` or
    `WITHDRAWAL` may be reversed, and only once: reversing a reversal, or reversing a row that
    already has a reversal pointing at it, is rejected with `ERR_TRANSACTION_ALREADY_REVERSED`
    (HTTP 409)."

    Design: Corner/errors/reversal_of_an_already_reversed_transaction_rejected
    """
    fund, _deposit, reversal = _fund_with_a_reversed_manual_deposit(api)

    validate_error(
        api.reverse_transaction(
            reversal["id"], F.reversal_payload(), U.make_treasurer_headers()
        ),
        ApiErrorId.TRANSACTION_ALREADY_REVERSED,
    )

    after = fx.read_fund(api, fund["id"])
    assert after["balance_cents"] == C.FUND_OPENING_BALANCE_CENTS
    assert after["fy_withdrawn_cents"] == 0

    _rows, meta = validate_paginated(
        api.list_reserve_transactions(U.make_director_headers(), params={"fund_id": fund["id"]})
    )
    assert meta["total_count"] == 2


def test_short_rationale_on_an_already_reversed_row_still_returns_the_state_error(api):
    """PRD §3.7: "That state check comes first, the rationale length check second, and the fiscal
    check last — a reversal that would drive `balance_cents` below zero is rejected with
    `ERR_REVERSAL_WOULD_OVERDRAW` (HTTP 422)."

    Design: Corner/errors/reversal_of_an_already_reversed_transaction_rejected
    """
    fund, deposit, _reversal = _fund_with_a_reversed_manual_deposit(api)

    validate_error(
        api.reverse_transaction(
            deposit["id"],
            F.reversal_payload(rationale=SHORT_RATIONALE),
            U.make_treasurer_headers(),
        ),
        ApiErrorId.TRANSACTION_ALREADY_REVERSED,
    )

    _rows, meta = validate_paginated(
        api.list_reserve_transactions(U.make_director_headers(), params={"fund_id": fund["id"]})
    )
    assert meta["total_count"] == 2


def test_second_actual_for_the_same_source_and_year_returns_duplicate_actual(api):
    """PRD §3.9: "At most one actual collection may exist per source and fiscal year; a second is
    rejected with `ERR_DUPLICATE_ACTUAL` (HTTP 409)."

    PRD §3.9: "`error_direction` records the sign of the miss relative to the forecast:
    `OVER_FORECAST` when the actual came in *below* the forecast, `UNDER_FORECAST` when it came in
    above, and `EXACT` when the two are equal."

    Design: Corner/errors/duplicate_actual_collection_for_the_same_source_and_year_rejected
    """
    ctx = fx.short_chain(api, "certified")
    fx.set_clock(api, CLOSED_FY2027_CLOCK)

    posted = fx.post_actual(api, ctx["pit_source_id"], C.FISCAL_YEAR, C.SHORT_ESTIMATE_CENTS)
    assert posted["matched_cycle_id"] == ctx["cycle_id"]
    assert posted["matched_forecast_cents"] == C.SHORT_ESTIMATE_CENTS
    assert posted["abs_pct_error_bps"] == 0
    assert posted["error_direction"] == "EXACT"

    source = validate_success(
        api.get_revenue_source(ctx["pit_source_id"], U.make_director_headers()), 200
    )
    assert source["posted_actual_count"] == 1
    assert source["mape_bps"] == 0
    assert source["methodology_flag"] is False

    validate_error(
        api.create_actual_collection(
            F.actual_collection_payload(
                ctx["pit_source_id"], C.FISCAL_YEAR, C.SHORT_ESTIMATE_CENTS
            ),
            U.make_exec_economist_headers(),
        ),
        ApiErrorId.DUPLICATE_ACTUAL,
    )

    unchanged = validate_success(
        api.get_revenue_source(ctx["pit_source_id"], U.make_director_headers()), 200
    )
    assert unchanged["posted_actual_count"] == 1

    _actuals, meta = validate_paginated(
        api.list_actual_collections(
            U.make_director_headers(), params={"source_id": ctx["pit_source_id"]}
        )
    )
    assert meta["total_count"] == 1


def test_manual_deposit_into_a_fund_at_its_cap_returns_fund_at_cap(api):
    """PRD §3.7: "First, the fund's `deposit_posture` must be `ACCEPTING`; a deposit into a fund
    already at its cap is rejected with `ERR_FUND_AT_CAP` (HTTP 409)."

    PRD §3.7: "It flips `ACCEPTING → AT_CAP` on any balance increase — a certification deposit, a
    manual deposit, or the reversal of a withdrawal — when `cap_cents` is not null and
    `balance_cents` reaches or passes `cap_cents` after the increase, and while `AT_CAP` further
    manual deposits are refused with `ERR_FUND_AT_CAP`."

    Design: Corner/errors/manual_deposit_into_a_fund_at_cap_rejected
    """
    ctx = fx.full_chain(
        api,
        "certified",
        fund_overrides={"opening_balance_cents": C.FUND_OPENING_OVERFLOW_CENTS},
    )
    fund = ctx["fund"]
    assert fund["balance_cents"] == C.ADEQUACY_BALANCE_AT_CAP_CENTS
    assert fund["cap_cents"] == C.FUND_CAP_CENTS
    assert fund["deposit_posture"] == "AT_CAP"

    validate_error(
        api.create_deposit(
            fund["id"], F.deposit_payload(ONE_CENT), U.make_treasurer_headers()
        ),
        ApiErrorId.FUND_AT_CAP,
    )

    after = fx.read_fund(api, fund["id"])
    assert after["balance_cents"] == C.ADEQUACY_BALANCE_AT_CAP_CENTS
    assert after["deposit_posture"] == "AT_CAP"

    _rows, meta = validate_paginated(
        api.list_reserve_transactions(U.make_director_headers(), params={"fund_id": fund["id"]})
    )
    assert meta["total_count"] == 1


def test_actual_collection_with_no_certified_forecast_returns_no_certified_forecast(api):
    """PRD §3.9: "When no such cycle exists the posting is rejected with
    `ERR_NO_CERTIFIED_FORECAST` (HTTP 422)."

    PRD §3.2: "A newly registered source begins with `status` `ACTIVE`, `mape_bps` 0,
    `methodology_flag` false and `posted_actual_count` 0."

    Design: Corner/errors/actual_collection_without_a_certified_forecast_rejected
    """
    fx.set_clock(api, C.DEFAULT_CLOCK)
    source = fx.create_pit_source(api)
    fx.create_cycle(api)

    validate_error(
        api.create_actual_collection(
            F.actual_collection_payload(
                source["id"], PRIOR_FISCAL_YEAR, PRIOR_YEAR_ACTUAL_CENTS
            ),
            U.make_director_headers(),
        ),
        ApiErrorId.NO_CERTIFIED_FORECAST,
    )

    unchanged = validate_success(
        api.get_revenue_source(source["id"], U.make_director_headers()), 200
    )
    assert unchanged["posted_actual_count"] == 0
    assert unchanged["mape_bps"] == 0
    assert unchanged["methodology_flag"] is False
    A.assert_version(unchanged, 1)

    _actuals, meta = validate_paginated(
        api.list_actual_collections(
            U.make_director_headers(), params={"fiscal_year": PRIOR_FISCAL_YEAR}
        )
    )
    assert meta["total_count"] == 0


def test_revision_naming_an_uncertified_target_returns_invalid_supersede_target(api):
    """PRD §3.1: "Naming no target on a revision, naming a target that is not certified, naming one
    whose fiscal year differs, or naming any target at all on a baseline cycle are all rejected
    with `ERR_INVALID_SUPERSEDE_TARGET` (HTTP 422)."

    Design: Corner/errors/revision_cycle_naming_an_uncertified_supersede_target_rejected
    """
    fx.set_clock(api, C.DEFAULT_CLOCK)
    draft = fx.create_cycle(api)
    A.assert_cycle_status(draft, "DRAFT")

    validate_error(
        api.create_forecast_cycle(
            F.revision_cycle_payload(draft["id"]), U.make_director_headers()
        ),
        ApiErrorId.INVALID_SUPERSEDE_TARGET,
    )

    _cycles, meta = validate_paginated(api.list_forecast_cycles(U.make_director_headers()))
    assert meta["total_count"] == 1

    unchanged = fx.read_cycle(api, draft["id"])
    A.assert_cycle_status(unchanged, "DRAFT")
    assert unchanged["supersedes_cycle_id"] is None


def test_revision_naming_no_target_at_all_returns_invalid_supersede_target(api):
    """PRD §3.1: "Naming no target on a revision, naming a target that is not certified, naming one
    whose fiscal year differs, or naming any target at all on a baseline cycle are all rejected
    with `ERR_INVALID_SUPERSEDE_TARGET` (HTTP 422)."

    Design: Corner/errors/revision_cycle_naming_an_uncertified_supersede_target_rejected
    """
    fx.set_clock(api, C.DEFAULT_CLOCK)

    validate_error(
        api.create_forecast_cycle(
            F.cycle_payload(cycle_type="REVISION"), U.make_director_headers()
        ),
        ApiErrorId.INVALID_SUPERSEDE_TARGET,
    )

    _cycles, meta = validate_paginated(api.list_forecast_cycles(U.make_director_headers()))
    assert meta["total_count"] == 0


def test_baseline_cycle_naming_a_supersede_target_returns_invalid_supersede_target(api):
    """PRD §3.1: "Naming no target on a revision, naming a target that is not certified, naming one
    whose fiscal year differs, or naming any target at all on a baseline cycle are all rejected
    with `ERR_INVALID_SUPERSEDE_TARGET` (HTTP 422)."

    Design: Corner/errors/revision_cycle_naming_an_uncertified_supersede_target_rejected
    """
    ctx = fx.short_chain(api, "certified")
    A.assert_cycle_status(ctx["cycle"], "CERTIFIED")

    validate_error(
        api.create_forecast_cycle(
            F.cycle_payload(
                fiscal_year=NEXT_FISCAL_YEAR,
                cycle_type="BASELINE",
                enacted_appropriation_cents=NEXT_YEAR_APPROPRIATION_CENTS,
                prior_recurring_baseline_cents=NEXT_YEAR_BASELINE_CENTS,
                supersedes_cycle_id=ctx["cycle_id"],
            ),
            U.make_director_headers(),
        ),
        ApiErrorId.INVALID_SUPERSEDE_TARGET,
    )

    _cycles, meta = validate_paginated(
        api.list_forecast_cycles(U.make_director_headers(), params={"fiscal_year": NEXT_FISCAL_YEAR})
    )
    assert meta["total_count"] == 0

    predecessor = fx.read_cycle(api, ctx["cycle_id"])
    A.assert_cycle_status(predecessor, "CERTIFIED")


# =========================================================================== #
# Role limits
# =========================================================================== #
def test_legislative_economist_certifying_the_cycle_returns_unauthorized(api):
    """PRD §3.6: "Only a `ForecastDirector` may certify, only from `CONSENSUS_REACHED` — any other
    status is rejected with `ERR_CYCLE_NOT_CONSENSUS_REACHED` (HTTP 409) — and only when
    `ratified_round_id` is not null."

    PRD §2.1: "Once both headers are accepted, the endpoint's own role list decides: an operator
    whose role is not listed for the operation receives `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/rbac/legislative_economist_cannot_certify_the_cycle
    """
    ctx = fx.short_chain(api, "ratified")

    validate_error(
        api.certify_cycle(ctx["cycle_id"], U.make_leg_economist_headers()),
        ApiErrorId.UNAUTHORIZED,
    )

    cycle = fx.read_cycle(api, ctx["cycle_id"])
    A.assert_cycle_status(cycle, "CONSENSUS_REACHED")
    assert cycle["certified_at"] is None
    assert cycle["ratified_round_id"] == ctx["round_id"]


def test_rating_analyst_publishing_a_briefing_returns_unauthorized(api):
    """PRD §3.9: "Publication is the `ForecastDirector`'s alone and moves a briefing to `PUBLISHED`
    from either `DRAFT` or `STALE`."

    PRD §2.1: "`RatingAnalyst` — the rating-agency-facing analyst. Drafts and edits briefings and
    reads everything, but publication and retraction belong to the `ForecastDirector` alone."

    PRD §2.1: "Once both headers are accepted, the endpoint's own role list decides: an operator
    whose role is not listed for the operation receives `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/rbac/rating_analyst_cannot_publish_a_briefing
    """
    ctx = fx.short_chain(api, "certified", fund_overrides={})
    briefing = fx.draft_briefing(api, ctx["fund_id"], ctx["cycle_id"])
    assert briefing["status"] == "DRAFT"

    validate_error(
        api.publish_briefing(briefing["id"], U.make_rating_analyst_headers()),
        ApiErrorId.UNAUTHORIZED,
    )

    unchanged = fx.read_briefing(api, briefing["id"])
    assert unchanged["status"] == "DRAFT"
    assert unchanged["published_at"] is None
    A.assert_version(unchanged, 1)

    _briefings, meta = validate_paginated(
        api.list_rating_briefings(U.make_director_headers(), params={"status": "PUBLISHED"})
    )
    assert meta["total_count"] == 0


def test_legislative_voter_drafting_a_withdrawal_request_returns_unauthorized(api):
    """PRD §2.1: "`LegislativeVoter` — a seat holder on the body that must supermajority-approve a
    withdrawal. Casts exactly one ballot per request and can read reserve state; nothing else."

    PRD §2.1: "Once both headers are accepted, the endpoint's own role list decides: an operator
    whose role is not listed for the operation receives `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/rbac/legislative_voter_cannot_raise_a_withdrawal_request
    """
    ctx = fx.short_chain(api, "certified", fund_overrides={})
    fund = fx.read_fund(api, ctx["fund_id"])

    validate_error(
        api.create_withdrawal_request(
            F.withdrawal_request_payload(
                fund["id"],
                ctx["cycle_id"],
                fund["version"],
                requested_amount_cents=WITHDRAWAL_REQUEST_CENTS,
            ),
            U.make_voter_headers(U.VOTER_USER_ID),
        ),
        ApiErrorId.UNAUTHORIZED,
    )

    _requests, meta = validate_paginated(
        api.list_withdrawal_requests(U.make_director_headers(), params={"fund_id": fund["id"]})
    )
    assert meta["total_count"] == 0

    after = fx.read_fund(api, fund["id"])
    A.assert_version(after, fund["version"])


def test_analyst_and_director_both_edit_the_briefing_draft_and_each_edit_bumps_version(api):
    """PRD §3.9: "While it is a draft its `narrative` may be edited, which increments its `version`
    by one."

    PRD §3.9: "That snapshot is taken automatically: `snapshot_fund_version` records the fund's
    `version` at creation, `snapshot_adequacy_band` its `adequacy_band`, and
    `snapshot_coverage_ratio_bps` its `coverage_ratio_bps`."

    Design: Corner/rbac/rating_analyst_and_director_share_the_briefing_draft_operations
    """
    ctx = fx.short_chain(api, "certified", fund_overrides={})
    briefing = fx.draft_briefing(api, ctx["fund_id"], ctx["cycle_id"])
    A.assert_version(briefing, 1)
    A.assert_briefing_snapshot(
        briefing,
        fund_version=2,
        adequacy_band="ADEQUATE",
        coverage_ratio_bps=SHORT_COVERAGE_BPS,
    )

    analyst_edit = validate_success(
        api.update_rating_briefing(
            briefing["id"], {"narrative": ANALYST_NARRATIVE}, U.make_rating_analyst_headers()
        ),
        200,
    )
    A.assert_version(analyst_edit, 2)
    assert analyst_edit["narrative"] == ANALYST_NARRATIVE
    assert analyst_edit["status"] == "DRAFT"

    director_edit = validate_success(
        api.update_rating_briefing(
            briefing["id"], {"narrative": DIRECTOR_NARRATIVE}, U.make_director_headers()
        ),
        200,
    )
    A.assert_version(director_edit, 3)
    assert director_edit["narrative"] == DIRECTOR_NARRATIVE
    assert director_edit["status"] == "DRAFT"
    assert director_edit["published_at"] is None
    A.assert_briefing_snapshot(
        director_edit,
        fund_version=2,
        adequacy_band="ADEQUATE",
        coverage_ratio_bps=SHORT_COVERAGE_BPS,
    )


def test_director_who_filed_a_contested_estimate_cannot_resolve_the_disagreement(api):
    """PRD §3.5: "The server compares the resolver's `X-User-ID` against the
    `submitted_by_user_id` of both the `EXECUTIVE` and the `LEGISLATIVE` estimate for the disputed
    source, and a match is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

    Design: Corner/rbac/economist_who_filed_the_estimate_cannot_resolve_the_disagreement
    """
    _round_data, record = _disputed_pit_round(api)

    validate_error(
        api.resolve_disagreement(
            record["id"],
            F.resolution_payload("MIDPOINT"),
            U.make_director_headers(U.LEG_ECONOMIST_USER_ID),
        ),
        ApiErrorId.SEGREGATION_OF_DUTIES,
    )

    unchanged = validate_success(
        api.get_disagreement_record(record["id"], U.make_director_headers()), 200
    )
    assert unchanged["status"] == "OPEN"
    assert unchanged["resolved_amount_cents"] is None
    assert unchanged["resolved_by_user_id"] is None


def test_uninvolved_director_resolving_the_same_disagreement_closes_it_at_the_midpoint(api):
    """PRD §3.5: "`EXEC_VALUE` adopts the executive figure recorded on the record, `LEG_VALUE`
    adopts the legislative figure, `MIDPOINT` adopts their sum divided by two rounded half up, and
    `DIRECTOR_OVERRIDE` adopts a figure the director supplies."

    PRD §3.5: "The server compares the resolver's `X-User-ID` against the `submitted_by_user_id` of
    both the `EXECUTIVE` and the `LEGISLATIVE` estimate for the disputed source, and a match is
    rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

    Design: Corner/rbac/economist_who_filed_the_estimate_cannot_resolve_the_disagreement
    """
    round_data, record = _disputed_pit_round(api)

    resolved = validate_success(
        api.resolve_disagreement(
            record["id"],
            F.resolution_payload("MIDPOINT"),
            U.make_director_headers(U.DIRECTOR_USER_ID),
        ),
        200,
    )
    assert resolved["status"] == "RESOLVED"
    assert resolved["resolution_method"] == "MIDPOINT"
    assert resolved["resolved_amount_cents"] == DISPUTE_PIT_MIDPOINT_CENTS
    assert resolved["resolved_by_user_id"] == U.DIRECTOR_USER_ID

    after = fx.read_round(api, round_data["id"])
    assert after["open_disagreement_count"] == 0
    assert after["status"] == "COMPARED"


# =========================================================================== #
# Version pinning across parents
# =========================================================================== #
def test_stale_expected_cycle_version_on_round_open_is_rejected_then_the_fresh_pin_is_accepted(api):
    """PRD §2.7: "If `expected_cycle_version` does not equal the cycle's current `version`, the
    request is rejected with `ERR_STALE_CYCLE_VERSION` (HTTP 412) and nothing is created or
    superseded."

    PRD §3.1: "Every scenario creation, re-weighting or deletion rewrites the cycle's
    `scenario_weight_total_bps` to the sum of the weights of the cycle's scenarios and increments
    the cycle's `version` by one; a re-weighting also increments the scenario's own `version`."

    Design: Corner/cross_cutting_complexity_layers/stale_expected_cycle_version_on_round_open_returns_412
    """
    fx.set_clock(api, C.DEFAULT_CLOCK)
    fx.create_pit_source(api)
    cycle = fx.create_cycle(api)
    stale_version = cycle["version"]

    fx.add_canonical_scenarios(api, cycle["id"])
    locked = fx.lock_inputs(api, cycle["id"])
    fresh_version = locked["version"]
    assert fresh_version != stale_version

    validate_error(
        api.create_consensus_round(
            F.round_payload(cycle["id"], stale_version), U.make_director_headers()
        ),
        ApiErrorId.STALE_CYCLE_VERSION,
    )

    _rounds, meta = validate_paginated(
        api.list_consensus_rounds(U.make_director_headers(), params={"cycle_id": cycle["id"]})
    )
    assert meta["total_count"] == 0
    assert fx.read_cycle(api, cycle["id"])["version"] == fresh_version

    opened = validate_success(
        api.create_consensus_round(
            F.round_payload(cycle["id"], fresh_version), U.make_director_headers()
        ),
        201,
    )
    assert opened["status"] == "OPEN"
    assert opened["round_number"] == 1
    assert opened["cycle_id"] == cycle["id"]


def test_stale_expected_fund_version_on_withdrawal_create_is_rejected_then_retried(api):
    """PRD §2.7: "If `expected_fund_version` does not equal the fund's current `version`, the
    request is rejected with `ERR_STALE_FUND_VERSION` (HTTP 412)."

    PRD §3.8: "A drafted request starts in `DRAFT` with `requested_by_user_id` taken from the
    drafter's `X-User-ID`, `votes_required`, `quorum_required`, `yes_votes`, `no_votes`,
    `abstain_votes` and `authorized_amount_cents` all 0, `approval_basis` and `vote_closes_at`
    null."

    Design: Corner/cross_cutting_complexity_layers/stale_expected_fund_version_on_withdrawal_create_returns_412
    """
    ctx = fx.short_chain(api, "ratified")
    fund = fx.create_fund(api)
    stale_version = fund["version"]
    A.assert_version(fund, 1)

    fx.certify(api, ctx["cycle_id"])
    fresh = fx.read_fund(api, fund["id"])
    A.assert_version(fresh, 2)

    validate_error(
        api.create_withdrawal_request(
            F.withdrawal_request_payload(
                fund["id"],
                ctx["cycle_id"],
                stale_version,
                requested_amount_cents=WITHDRAWAL_REQUEST_CENTS,
            ),
            U.make_treasurer_headers(U.TREASURER_REQUESTER_USER_ID),
        ),
        ApiErrorId.STALE_FUND_VERSION,
    )

    _requests, empty_meta = validate_paginated(
        api.list_withdrawal_requests(U.make_director_headers(), params={"fund_id": fund["id"]})
    )
    assert empty_meta["total_count"] == 0

    created = validate_success(
        api.create_withdrawal_request(
            F.withdrawal_request_payload(
                fund["id"],
                ctx["cycle_id"],
                fresh["version"],
                requested_amount_cents=WITHDRAWAL_REQUEST_CENTS,
            ),
            U.make_treasurer_headers(U.TREASURER_REQUESTER_USER_ID),
        ),
        201,
    )
    assert created["status"] == "DRAFT"
    assert created["requested_amount_cents"] == WITHDRAWAL_REQUEST_CENTS
    assert created["requested_by_user_id"] == U.TREASURER_REQUESTER_USER_ID
    assert created["approval_basis"] is None
    A.assert_ballot_untouched(created)

    _again, meta = validate_paginated(
        api.list_withdrawal_requests(U.make_director_headers(), params={"fund_id": fund["id"]})
    )
    assert meta["total_count"] == 1


def test_reserve_fund_version_increments_on_create_certify_deposit_and_recompute(api):
    """PRD §2.6: "Most resources additionally carry `updated_at` (same format, refreshed on every
    mutation) and `version` (an integer that starts at 1 and increments by one on every mutation of
    that resource, including mutations the server performs on its own initiative when a derived
    field is rewritten)."

    PRD §3.7: "The posting mints a ledger row with `origin` `MANUAL_DEPOSIT`, `signed_amount_cents`
    equal to the positive `amount_cents`, `gross_computed_cents` equal to the same amount and
    `overflow_returned_cents` 0; the fund's `balance_cents` rises by that amount,
    `last_transaction_at` becomes the row's `created_at`, the adequacy disclosure is re-derived,
    `deposit_posture` may flip `ACCEPTING → AT_CAP`, every `PUBLISHED` briefing of the fund goes
    `STALE` with `stale_reason` `RESERVE_BALANCE_CHANGED`, and the fund's `version` increments by
    one."

    PRD §3.7: "It can also be run on demand by a `ForecastDirector` or a `ReserveTreasurer`: an
    explicit recompute rewrites `volatility_index_bps`, `target_pct_bps`, `required_reserve_cents`,
    `coverage_ratio_bps`, `adequacy_band`, `cushion_credit_bps`, `disclosed_target_pct_bps` and
    `cap_cents`, re-evaluates `deposit_posture` against the recomputed `cap_cents`, and increments
    the fund's `version` by one."

    Design: Corner/cross_cutting_complexity_layers/reserve_fund_version_increments_on_every_write_path
    """
    ctx = fx.short_chain(api, "ratified")

    fund = fx.create_fund(api)
    A.assert_version(fund, 1)

    fx.certify(api, ctx["cycle_id"])
    after_certify = fx.read_fund(api, fund["id"])
    A.assert_version(after_certify, 2)
    assert after_certify["balance_cents"] == C.FUND_OPENING_BALANCE_CENTS
    assert after_certify["cap_cents"] == C.SHORT_CAP_CENTS
    assert after_certify["coverage_ratio_bps"] == SHORT_COVERAGE_BPS
    view = fx.read_adequacy(api, fund["id"])
    assert view["headroom_cents"] == SHORT_HEADROOM_CENTS

    row = fx.deposit(api, fund["id"], MANUAL_DEPOSIT_CENTS)
    A.assert_transaction_row(
        row,
        origin="MANUAL_DEPOSIT",
        signed_amount_cents=MANUAL_DEPOSIT_CENTS,
        gross_computed_cents=MANUAL_DEPOSIT_CENTS,
        overflow_returned_cents=0,
    )
    after_deposit = fx.read_fund(api, fund["id"])
    A.assert_version(after_deposit, 3)
    assert after_deposit["balance_cents"] == BALANCE_AFTER_MANUAL_DEPOSIT_CENTS
    assert after_deposit["coverage_ratio_bps"] == SHORT_COVERAGE_AFTER_DEPOSIT_BPS
    assert after_deposit["adequacy_band"] == "ADEQUATE"
    assert after_deposit["deposit_posture"] == "ACCEPTING"

    after_recompute = fx.recompute_adequacy(api, fund["id"])
    A.assert_version(after_recompute, 4)
    assert after_recompute["balance_cents"] == BALANCE_AFTER_MANUAL_DEPOSIT_CENTS
    assert after_recompute["coverage_ratio_bps"] == SHORT_COVERAGE_AFTER_DEPOSIT_BPS
    assert after_recompute["cap_cents"] == C.SHORT_CAP_CENTS
    assert after_recompute["required_reserve_cents"] == C.SHORT_REQUIRED_RESERVE_CENTS


# =========================================================================== #
# Consistency model
# =========================================================================== #
def test_a_created_source_is_complete_in_its_own_response_and_in_the_next_read(api):
    """PRD §2.8: "The system's consistency model is immediate: when a write changes a value another
    resource derives from, the dependent resource is recomputed inside the same request, not by a
    later job."

    PRD §3.2: "A newly registered source begins with `status` `ACTIVE`, `mape_bps` 0,
    `methodology_flag` false and `posted_actual_count` 0."

    Design: Corner/consistency_model/writes_are_visible_in_the_same_response_and_in_the_next_read
    """
    fx.set_clock(api, C.DEFAULT_CLOCK)

    created = validate_success(
        api.create_revenue_source(F.pit_source_payload(), U.make_director_headers()), 201
    )
    assert is_valid_uuid(created["id"])
    assert is_iso8601_timestamp(created["created_at"])
    A.assert_version(created, 1)
    assert created["status"] == "ACTIVE"
    assert created["mape_bps"] == 0
    assert created["methodology_flag"] is False
    assert created["posted_actual_count"] == 0

    read = validate_success(
        api.get_revenue_source(created["id"], U.make_rating_analyst_headers()), 200
    )
    assert read["version"] == created["version"]
    assert read["status"] == created["status"]
    assert read["created_at"] == created["created_at"]
    assert read["base_year_receipts_cents"] == C.PIT_BASE_RECEIPTS_CENTS
    assert read["elasticity_employment_bps"] == C.PIT_ELASTICITY_EMPLOYMENT_BPS
    assert read["elasticity_wage_income_bps"] == C.PIT_ELASTICITY_WAGE_BPS
    assert read["elasticity_retail_bps"] == C.PIT_ELASTICITY_RETAIL_BPS
    assert read["elasticity_asset_bps"] == C.PIT_ELASTICITY_ASSET_BPS
    assert read["volatility_class"] == "MEDIUM"
    assert read["mape_bps"] == 0
    assert read["posted_actual_count"] == 0
    assert read["methodology_flag"] is False

    items, meta = validate_paginated(api.list_revenue_sources(U.make_rating_analyst_headers()))
    assert meta["total_count"] == 1
    assert meta["has_more"] is False
    assert [item["id"] for item in items] == [created["id"]]
