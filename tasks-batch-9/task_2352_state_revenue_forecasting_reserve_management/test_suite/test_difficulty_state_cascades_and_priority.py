"""Depth tests: re-entrant and branching state machines, transitive cascades and
rejection-ladder masking.

Every expected figure below is a literal. The chains they belong to are the two
canonical portfolios `test_helpers.constants` already pins; the few figures that
belong only to a scenario built here are stated once at module level with the
PRD step order that produces them named in the comment.
"""

from prd_bench_local_runner.testing import (
    get_success_data,
    is_valid_uuid,
    validate_error,
    validate_paginated,
)

from test_helpers import ApiErrorId
from test_helpers import assertions as A
from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as fx
from test_helpers import test_users as U

# --------------------------------------------------------------------------- #
# The narrow capital-gains gap: a legislative overlay of -5,100,000 keeps both
# per-source variances inside the 150 bps tolerance while the one-time item is
# ACTIVE, and pushes the capital-gains source outside it once the item is void.
# --------------------------------------------------------------------------- #
NARROW_CGT_JUDGMENTAL_CENTS = -5_100_000

PRE_VOID_LEG_TOTAL_CENTS = 1_593_316_273
PRE_VOID_VARIANCE_BPS = 82
PRE_VOID_RECONCILED_CENTS = 1_599_866_273

POST_VOID_VARIANCE_BPS = 83
POST_VOID_CGT_EXEC_CENTS = 335_459_589
POST_VOID_CGT_LEG_CENTS = 330_359_589
POST_VOID_CGT_VARIANCE_BPS = 153
POST_VOID_CGT_MIDPOINT_CENTS = 332_909_589
POST_VOID_RECONCILED_CENTS = 1_587_866_273

# --------------------------------------------------------------------------- #
# The two approval branches of one certified cycle
# --------------------------------------------------------------------------- #
REQUESTED_OVER_GAP_CENTS = 60_000_000
VOTE_CLOSES_DATE = "2026-08-08"
FAR_DEADLINE_DATE = "2027-06-30"

# --------------------------------------------------------------------------- #
# Certification cascade: opening balance 138,133,490 leaves headroom exactly
# equal to the 21,958,137 the deposit waterfall owes.
# --------------------------------------------------------------------------- #
CERT_DISCLOSED_TARGET_PCT_BPS = 300

# --------------------------------------------------------------------------- #
# Execution cascade: 71,958,137 less the 21,587,441 the fiscal-year cap allows.
# --------------------------------------------------------------------------- #
EXECUTION_CLOCK = "2026-08-05T00:00:00Z"
EXECUTION_BALANCE_CENTS = 50_370_696
EXECUTION_COVERAGE_BPS = 6_340
COOLING_OFF_UNTIL_DATE = "2026-09-04"

# --------------------------------------------------------------------------- #
# Lapse scenario: opening balance 20,000,000 plus the 21,958,137 deposit
# --------------------------------------------------------------------------- #
LAPSE_FUND_OPENING_CENTS = 20_000_000
LAPSE_FUND_BALANCE_CENTS = 41_958_137
LAPSE_FUND_COVERAGE_BPS = 5_281
LAPSE_DEADLINE_DATE = "2026-08-10"
LAPSE_CLOCK = "2026-08-20T00:00:00Z"

# --------------------------------------------------------------------------- #
# Ballot that never reaches quorum
# --------------------------------------------------------------------------- #
QUORUM_SHORTFALL_REQUESTED_CENTS = 12_000_000
AFTER_VOTE_WINDOW_CLOCK = "2026-08-09T00:00:00Z"


# --------------------------------------------------------------------------- #
# Setup builders
# --------------------------------------------------------------------------- #
def _compared_round_with_narrow_cgt_gap(api):
    """A COMPARED round whose capital-gains gap of 5,100,000 cents sits at 148
    basis points only because the ACTIVE one-time item inflates the midpoint."""
    fx.set_clock(api, C.DEFAULT_CLOCK)
    pit = fx.create_pit_source(api)
    cgt = fx.create_cgt_source(api)
    fx.create_policy_adjustment(api, pit["id"], F.pit_policy_adjustment_payload())
    fx.create_policy_adjustment(api, cgt["id"], F.cgt_policy_adjustment_payload())

    cycle = fx.create_cycle(api)
    fx.add_canonical_scenarios(api, cycle["id"])
    item = fx.create_one_time_item(api, cycle["id"], cgt["id"])
    fx.lock_inputs(api, cycle["id"])

    round_data = fx.open_round(api, cycle["id"])
    fx.file_estimate(api, round_data["id"], pit["id"], "EXECUTIVE")
    fx.file_estimate(api, round_data["id"], cgt["id"], "EXECUTIVE")
    fx.file_estimate(
        api,
        round_data["id"],
        pit["id"],
        "LEGISLATIVE",
        judgmental_adjustment_cents=C.LEG_PIT_JUDGMENTAL_CENTS,
    )
    fx.file_estimate(
        api,
        round_data["id"],
        cgt["id"],
        "LEGISLATIVE",
        judgmental_adjustment_cents=NARROW_CGT_JUDGMENTAL_CENTS,
    )
    fx.submit_body(api, round_data["id"], "EXECUTIVE")
    compared = fx.submit_body(api, round_data["id"], "LEGISLATIVE")
    return {
        "cycle_id": cycle["id"],
        "round_id": round_data["id"],
        "round": compared,
        "pit_source_id": pit["id"],
        "cgt_source_id": cgt["id"],
        "one_time_item_id": item["id"],
    }


def _certified_chain_with_published_briefing(api, *, opening_balance_cents=None):
    """The full chain certified against a fund holding a PUBLISHED briefing whose
    snapshot was taken after certification."""
    overrides = {}
    if opening_balance_cents is not None:
        overrides["opening_balance_cents"] = opening_balance_cents
    ctx = fx.full_chain(api, "certified", fund_overrides=overrides)
    fx.set_clock(api, EXECUTION_CLOCK)
    briefing = fx.draft_briefing(api, ctx["fund_id"], ctx["cycle_id"])
    ctx["briefing"] = fx.publish_briefing(api, briefing["id"])
    ctx["briefing_id"] = briefing["id"]
    return ctx


def _approved_ballot_request(api, ctx):
    """One SUPERMAJORITY_VOTE request for 30,000,000 cents carried by 8 YES of 11
    ballots, drafted by tr-req-1 so a different treasurer can execute it."""
    request = fx.draft_withdrawal(
        api,
        ctx["fund_id"],
        ctx["cycle_id"],
        requester_user_id=U.TREASURER_REQUESTER_USER_ID,
        requested_amount_cents=C.WITHDRAWAL_REQUESTED_OVER_CAP_CENTS,
        justification_type="SUPERMAJORITY_VOTE",
        deadline_date=FAR_DEADLINE_DATE,
    )
    fx.open_vote(api, request["id"])
    fx.cast_ballots(api, request["id"], yes=8, no=1, abstain=2)
    return fx.close_vote(api, request["id"])


# =========================================================================== #
# non_linear_state_machine — the re-entrant consensus round
# =========================================================================== #
def test_voiding_one_time_item_reenters_disputed_from_compared(api):
    """PRD §3.4: "When a one-time item of the cycle is voided (§3.3) and the resulting recompute pushes at least one per-source variance above `per_source_tolerance_bps`, the round goes `COMPARED → DISPUTED`, which requires that the round's estimates still have `locked` false: one disagreement record is minted per newly breaching source, `open_disagreement_count` is updated accordingly, `reconciled_total_cents` is recomputed, and the round's `version` increments by one."

    PRD §3.3: "This recompute has a counter-intuitive consequence that the negotiation must tolerate: removing a non-recurring amount shrinks each body's per-source figure and therefore shrinks the midpoint that per-source variance is measured against, so the same absolute gap between the two bodies can breach a relative tolerance it previously satisfied — a `COMPARED` round can be pushed back to `DISPUTED` by a void, as §3.4 describes."

    Design: Difficulty/non_linear_state_machine/consensus_round_reenters_disputed_from_compared_then_returns
    """
    ctx = _compared_round_with_narrow_cgt_gap(api)

    A.assert_round_comparison(
        ctx["round"],
        status="COMPARED",
        exec_total_cents=C.EXEC_TOTAL_CENTS,
        leg_total_cents=PRE_VOID_LEG_TOTAL_CENTS,
        variance_bps=PRE_VOID_VARIANCE_BPS,
        reconciled_total_cents=PRE_VOID_RECONCILED_CENTS,
        open_disagreement_count=0,
    )

    voided = fx.void_one_time_item(api, ctx["one_time_item_id"])
    assert voided["status"] == "VOIDED", f"expected the item VOIDED, got {voided['status']}"

    after = fx.read_round(api, ctx["round_id"])
    assert after["status"] == "DISPUTED", (
        f"the void must push the compared round back to DISPUTED, got {after['status']}"
    )
    assert after["open_disagreement_count"] == 1, (
        f"one record per newly breaching source, got {after['open_disagreement_count']}"
    )
    assert after["variance_bps"] == POST_VOID_VARIANCE_BPS, (
        f"variance_bps {after['variance_bps']} != {POST_VOID_VARIANCE_BPS}"
    )
    assert after["reconciled_total_cents"] == POST_VOID_RECONCILED_CENTS, (
        f"reconciled_total_cents {after['reconciled_total_cents']} "
        f"!= {POST_VOID_RECONCILED_CENTS}"
    )


def test_void_cascade_mints_one_record_for_the_breaching_source_only(api):
    """PRD §3.4: "Note that a single source breaching its own tolerance disputes the round even when the grand-total variance is comfortably inside `variance_tolerance_bps`, and that only the breaching sources get records — a source at 64 basis points is left alone while its neighbour at 902 basis points is written up."

    Design: Difficulty/non_linear_state_machine/consensus_round_reenters_disputed_from_compared_then_returns
    """
    ctx = _compared_round_with_narrow_cgt_gap(api)
    fx.void_one_time_item(api, ctx["one_time_item_id"])

    records = fx.list_disagreements(api, round_id=ctx["round_id"])
    assert len(records) == 1, (
        f"only the capital-gains source breached its tolerance, got {len(records)} records"
    )
    record = records[0]
    assert record["source_id"] == ctx["cgt_source_id"], (
        f"the record belongs to the breaching source, got {record['source_id']}"
    )
    assert record["status"] == "OPEN", f"a minted record starts OPEN, got {record['status']}"
    assert record["exec_amount_cents"] == POST_VOID_CGT_EXEC_CENTS, (
        f"exec_amount_cents {record['exec_amount_cents']} != {POST_VOID_CGT_EXEC_CENTS}"
    )
    assert record["leg_amount_cents"] == POST_VOID_CGT_LEG_CENTS, (
        f"leg_amount_cents {record['leg_amount_cents']} != {POST_VOID_CGT_LEG_CENTS}"
    )
    assert record["variance_bps"] == POST_VOID_CGT_VARIANCE_BPS, (
        f"variance_bps {record['variance_bps']} != {POST_VOID_CGT_VARIANCE_BPS}"
    )

    after = fx.read_round(api, ctx["round_id"])
    assert after["variance_bps"] == POST_VOID_VARIANCE_BPS, (
        "the aggregate variance never breached its own tolerance: "
        f"{after['variance_bps']} != {POST_VOID_VARIANCE_BPS}"
    )


def test_resolving_the_cascade_record_returns_the_round_to_compared(api):
    """PRD §3.5: "When the resolution brings `open_disagreement_count` to 0, the round closes the negotiation cycle by moving `DISPUTED → COMPARED`."

    PRD §3.5: "If a disagreement record for this round and this source has `status` `RESOLVED`, the contribution is that record's `resolved_amount_cents`, which overrides the cycle's reconciliation policy for that source."

    Design: Difficulty/non_linear_state_machine/consensus_round_reenters_disputed_from_compared_then_returns
    """
    ctx = _compared_round_with_narrow_cgt_gap(api)
    fx.void_one_time_item(api, ctx["one_time_item_id"])
    record = fx.list_disagreements(api, round_id=ctx["round_id"], status="OPEN")[0]

    resolved = fx.resolve_disagreement(api, record["id"], "MIDPOINT")
    assert resolved["status"] == "RESOLVED", (
        f"expected the record RESOLVED, got {resolved['status']}"
    )
    assert resolved["resolution_method"] == "MIDPOINT", (
        f"resolution_method {resolved['resolution_method']} != MIDPOINT"
    )
    assert resolved["resolved_amount_cents"] == POST_VOID_CGT_MIDPOINT_CENTS, (
        f"resolved_amount_cents {resolved['resolved_amount_cents']} "
        f"!= {POST_VOID_CGT_MIDPOINT_CENTS}"
    )
    assert resolved["resolved_by_user_id"] == U.DIRECTOR_USER_ID, (
        f"resolved_by_user_id {resolved['resolved_by_user_id']} != {U.DIRECTOR_USER_ID}"
    )

    after = fx.read_round(api, ctx["round_id"])
    assert after["status"] == "COMPARED", (
        f"the round returns to COMPARED a second time, got {after['status']}"
    )
    assert after["open_disagreement_count"] == 0, (
        f"open_disagreement_count {after['open_disagreement_count']} != 0"
    )
    assert after["reconciled_total_cents"] == POST_VOID_RECONCILED_CENTS, (
        f"reconciled_total_cents {after['reconciled_total_cents']} "
        f"!= {POST_VOID_RECONCILED_CENTS}"
    )


# =========================================================================== #
# non_linear_state_machine — the forking withdrawal request
# =========================================================================== #
def test_shortfall_branch_authorizes_the_certified_gap_with_ballot_fields_untouched(api):
    """PRD §3.8: "On success `approval_basis` becomes `SHORTFALL_TRIGGER`, `authorized_amount_cents` becomes the lower of `requested_amount_cents` and the cycle's `shortfall_gap_cents` — the authorisation can never exceed the certified gap it is justified by — and the request's `version` increments by one."

    PRD §3.8: "Nothing about the ballot is touched: `votes_required` and `quorum_required` stay 0, `yes_votes`, `no_votes` and `abstain_votes` stay 0, and `vote_closes_at` stays null."

    Design: Difficulty/non_linear_state_machine/withdrawal_request_forks_into_two_approval_branches_with_disjoint_effects
    """
    ctx = fx.full_chain(api, "certified", fund_overrides={})
    A.assert_shortfall(
        ctx["cycle"],
        gap_cents=C.CERTIFIED_SHORTFALL_GAP_CENTS,
        pct_bps=C.CERTIFIED_SHORTFALL_PCT_BPS,
    )

    request = fx.draft_withdrawal(
        api,
        ctx["fund_id"],
        ctx["cycle_id"],
        requested_amount_cents=REQUESTED_OVER_GAP_CENTS,
        justification_type="SHORTFALL_TRIGGER",
        deadline_date=FAR_DEADLINE_DATE,
    )
    approved = fx.verify_shortfall(api, request["id"])

    assert approved["status"] == "APPROVED", (
        f"the shortfall branch approves in one step, got {approved['status']}"
    )
    assert approved["approval_basis"] == "SHORTFALL_TRIGGER", (
        f"approval_basis {approved['approval_basis']} != SHORTFALL_TRIGGER"
    )
    assert approved["authorized_amount_cents"] == C.CERTIFIED_SHORTFALL_GAP_CENTS, (
        f"authorized_amount_cents {approved['authorized_amount_cents']} "
        f"!= {C.CERTIFIED_SHORTFALL_GAP_CENTS}"
    )
    A.assert_ballot_untouched(approved)


def test_ballot_branch_authorizes_the_fiscal_year_cap_headroom_at_eleven_seats(api):
    """PRD §3.8: "A fund whose fiscal-year opening balance is 71,958,137 cents and whose `annual_withdrawal_cap_pct_bps` is 3000 has a cap of 21,587,441 cents for the year, so a request for 30,000,000 cents with nothing yet drawn is authorised at 21,587,441 cents, and a request for 10,000,000 cents after 15,000,000 cents has already been drawn is authorised at 6,587,441 cents."

    PRD §3.8: "Opening the ballot freezes both seat requirements from the fund's `eligible_seats`: `votes_required` is two thirds of the eligible seats rounded up to a whole seat, and `quorum_required` is one half of the eligible seats rounded up to a whole seat — with eleven eligible seats, eight yes votes are required and six ballots constitute a quorum."

    Design: Difficulty/non_linear_state_machine/withdrawal_request_forks_into_two_approval_branches_with_disjoint_effects
    """
    ctx = fx.full_chain(api, "certified", fund_overrides={})
    request = fx.draft_withdrawal(
        api,
        ctx["fund_id"],
        ctx["cycle_id"],
        requested_amount_cents=C.WITHDRAWAL_REQUESTED_OVER_CAP_CENTS,
        justification_type="SUPERMAJORITY_VOTE",
        deadline_date=FAR_DEADLINE_DATE,
    )

    opened = fx.open_vote(api, request["id"])
    assert opened["status"] == "VOTE_OPEN", (
        f"the ballot branch leaves DRAFT for VOTE_OPEN, got {opened['status']}"
    )
    A.assert_ballot_requirements(
        opened, votes_required=C.VOTES_REQUIRED, quorum_required=C.QUORUM_REQUIRED
    )
    assert opened["vote_closes_at"][:10] == VOTE_CLOSES_DATE, (
        f"vote_closes_at {opened['vote_closes_at']} is not seven days after the clock"
    )

    fx.cast_ballots(api, request["id"], yes=8, no=3)
    closed = fx.close_vote(api, request["id"])

    A.assert_tally(closed, yes=8, no=3, abstain=0)
    assert closed["status"] == "APPROVED", (
        f"eight yes of eleven seats approves, got {closed['status']}"
    )
    assert closed["approval_basis"] == "SUPERMAJORITY_VOTE", (
        f"approval_basis {closed['approval_basis']} != SUPERMAJORITY_VOTE"
    )
    assert closed["authorized_amount_cents"] == C.WITHDRAWAL_AUTHORIZED_AT_CAP_CENTS, (
        f"authorized_amount_cents {closed['authorized_amount_cents']} "
        f"!= {C.WITHDRAWAL_AUTHORIZED_AT_CAP_CENTS} (the fiscal-year cap headroom)"
    )
    assert closed["authorized_amount_cents"] != C.CERTIFIED_SHORTFALL_GAP_CENTS, (
        "the ballot branch is never ceilinged by the shortfall gap"
    )

    _, ballot_meta = validate_paginated(
        api.list_withdrawal_votes(request["id"], U.make_director_headers())
    )
    assert ballot_meta["total_count"] == 11, (
        f"eleven seats cast eleven ballots, got {ballot_meta['total_count']}"
    )


def test_both_approval_branches_reach_approved_while_moving_no_money(api):
    """PRD §3.8: "Creating a draft also **rejects any other request on the same fund that is still in `DRAFT`**, moving each to `REJECTED` with `authorized_amount_cents` 0 and `approval_basis` left null and incrementing each one's `version` by one, and it increments the fund's own `version` by one even though no money has moved — which is exactly why the next drafter's pin must be fresh."

    Design: Difficulty/non_linear_state_machine/withdrawal_request_forks_into_two_approval_branches_with_disjoint_effects
    """
    ctx = fx.full_chain(api, "certified", fund_overrides={})

    shortfall_request = fx.draft_withdrawal(
        api,
        ctx["fund_id"],
        ctx["cycle_id"],
        requested_amount_cents=REQUESTED_OVER_GAP_CENTS,
        justification_type="SHORTFALL_TRIGGER",
        deadline_date=FAR_DEADLINE_DATE,
    )
    fx.verify_shortfall(api, shortfall_request["id"])

    ballot_request = fx.draft_withdrawal(
        api,
        ctx["fund_id"],
        ctx["cycle_id"],
        requested_amount_cents=C.WITHDRAWAL_REQUESTED_OVER_CAP_CENTS,
        justification_type="SUPERMAJORITY_VOTE",
        deadline_date=FAR_DEADLINE_DATE,
    )
    fx.open_vote(api, ballot_request["id"])
    fx.cast_ballots(api, ballot_request["id"], yes=8, no=3)
    fx.close_vote(api, ballot_request["id"])

    branch_a = fx.read_request(api, shortfall_request["id"])
    branch_b = fx.read_request(api, ballot_request["id"])
    assert branch_a["status"] == "APPROVED", (
        f"the approved shortfall request is not a DRAFT the later draft could reject, "
        f"got {branch_a['status']}"
    )
    assert branch_b["status"] == "APPROVED", f"expected APPROVED, got {branch_b['status']}"
    assert branch_a["authorized_amount_cents"] == C.CERTIFIED_SHORTFALL_GAP_CENTS, (
        f"branch A authorised {branch_a['authorized_amount_cents']} "
        f"!= {C.CERTIFIED_SHORTFALL_GAP_CENTS}"
    )
    assert branch_b["authorized_amount_cents"] == C.WITHDRAWAL_AUTHORIZED_AT_CAP_CENTS, (
        f"branch B authorised {branch_b['authorized_amount_cents']} "
        f"!= {C.WITHDRAWAL_AUTHORIZED_AT_CAP_CENTS}"
    )

    fund = fx.read_fund(api, ctx["fund_id"])
    assert fund["balance_cents"] == C.FUND_BALANCE_AFTER_DEPOSIT_CENTS, (
        f"approval alone moves no money: {fund['balance_cents']} "
        f"!= {C.FUND_BALANCE_AFTER_DEPOSIT_CENTS}"
    )
    assert fund["fy_withdrawn_cents"] == 0, (
        f"fy_withdrawn_cents {fund['fy_withdrawn_cents']} != 0"
    )
    rows = fx.list_transactions(api, fund_id=ctx["fund_id"])
    assert len(rows) == 1, f"only the certification deposit exists, got {len(rows)} rows"
    assert rows[0]["origin"] == "CERTIFICATION_DEPOSIT", (
        f"origin {rows[0]['origin']} != CERTIFICATION_DEPOSIT"
    )


# =========================================================================== #
# transitive_cascade — certification
# =========================================================================== #
def test_certification_writes_recurring_total_then_mints_the_deposit_row(api):
    """PRD §3.6: "The cycle copies `certified_total_cents` from the ratified round's `reconciled_total_cents`, sets `certified_one_time_cents` to the sum of `amount_cents` over the cycle's `ACTIVE` one-time items, derives `certified_recurring_total_cents` by subtracting `certified_one_time_cents` from `certified_total_cents`, and stamps `certified_at` with the logical clock."

    PRD §3.6: "A ledger row is minted **only when the deposited amount is greater than zero**, with `origin` `CERTIFICATION_DEPOSIT`, `signed_amount_cents` equal to the positive deposited amount, `source_cycle_id` pointing at the certifying cycle, and both `gross_computed_cents` and `overflow_returned_cents` recorded on the row; its `memo` is generated by the server, since no operator authored it."

    Design: Difficulty/transitive_cascade/certification_cascades_deposit_then_cap_posture_then_briefing_staleness
    """
    ctx = fx.full_chain(
        api,
        "ratified",
        fund_overrides={"opening_balance_cents": C.FUND_OPENING_EXACT_FILL_CENTS},
    )
    certified = fx.certify(api, ctx["cycle_id"])

    A.assert_cycle_status(certified, "CERTIFIED")
    A.assert_certified_aggregates(
        certified,
        total_cents=C.CERTIFIED_TOTAL_CENTS,
        one_time_cents=C.CERTIFIED_ONE_TIME_CENTS,
        recurring_cents=C.CERTIFIED_RECURRING_CENTS,
    )
    A.assert_shortfall(
        certified,
        gap_cents=C.CERTIFIED_SHORTFALL_GAP_CENTS,
        pct_bps=C.CERTIFIED_SHORTFALL_PCT_BPS,
    )

    rows = fx.list_transactions(api, fund_id=ctx["fund_id"])
    assert len(rows) == 1, f"one deposit row is owed, got {len(rows)} rows"
    A.assert_transaction_row(
        rows[0],
        origin="CERTIFICATION_DEPOSIT",
        signed_amount_cents=C.GROWTH_GROSS_COMPUTED_CENTS,
        gross_computed_cents=C.GROWTH_GROSS_COMPUTED_CENTS,
        overflow_returned_cents=0,
        source_cycle_id=ctx["cycle_id"],
    )

    fund = fx.read_fund(api, ctx["fund_id"])
    assert fund["balance_cents"] == C.ADEQUACY_BALANCE_AT_CAP_CENTS, (
        f"balance_cents {fund['balance_cents']} != {C.ADEQUACY_BALANCE_AT_CAP_CENTS}"
    )
    A.assert_ledger_identity(fund, rows)


def test_certification_deposit_flips_posture_at_cap_and_rescores_adequacy(api):
    """PRD §3.6: "Because `balance_cents` changed, the fund's entire adequacy disclosure is re-derived by the procedure in §3.7 — `cap_cents`, `volatility_index_bps`, `target_pct_bps`, `required_reserve_cents`, `coverage_ratio_bps`, `adequacy_band`, `cushion_credit_bps` and `disclosed_target_pct_bps` are all rewritten — `deposit_posture` flips `ACCEPTING → AT_CAP` when `cap_cents` is not null and `balance_cents` has reached or passed it, and the fund's `version` increments by one."

    Design: Difficulty/transitive_cascade/certification_cascades_deposit_then_cap_posture_then_briefing_staleness
    """
    ctx = fx.full_chain(
        api,
        "ratified",
        fund_overrides={"opening_balance_cents": C.FUND_OPENING_EXACT_FILL_CENTS},
    )
    before = fx.read_fund(api, ctx["fund_id"])
    assert before["deposit_posture"] == "ACCEPTING", (
        f"a new fund starts ACCEPTING, got {before['deposit_posture']}"
    )

    fx.certify(api, ctx["cycle_id"])
    fund = fx.read_fund(api, ctx["fund_id"])

    assert fund["deposit_posture"] == "AT_CAP", (
        f"the exact-fill deposit reaches the cap, got {fund['deposit_posture']}"
    )
    A.assert_adequacy_disclosure(
        fund,
        cap_cents=C.FUND_CAP_CENTS,
        required_reserve_cents=C.ADEQUACY_REQUIRED_RESERVE_CENTS,
        coverage_ratio_bps=C.ADEQUACY_COVERAGE_AT_CAP_BPS,
        adequacy_band="STRONG",
        cushion_credit_bps=C.CUSHION_CREDIT_BPS,
        disclosed_target_pct_bps=CERT_DISCLOSED_TARGET_PCT_BPS,
    )
    adequacy = fx.read_adequacy(api, ctx["fund_id"])
    assert adequacy["headroom_cents"] == 0, (
        f"the deposit filled the cap exactly, headroom {adequacy['headroom_cents']} != 0"
    )


def test_certification_balance_change_stales_published_briefing_without_refreshing_snapshot(api):
    """PRD §3.6: "Because the fund's balance moved, every rating-agency briefing of that fund whose `status` is `PUBLISHED` becomes `STALE` with `stale_reason` `RESERVE_BALANCE_CHANGED`, each such briefing's `version` incrementing by one."

    PRD §3.9: "That snapshot is taken automatically: `snapshot_fund_version` records the fund's `version` at creation, `snapshot_adequacy_band` its `adequacy_band`, and `snapshot_coverage_ratio_bps` its `coverage_ratio_bps`."

    Design: Difficulty/transitive_cascade/certification_cascades_deposit_then_cap_posture_then_briefing_staleness
    """
    ctx = fx.full_chain(
        api,
        "ratified",
        fund_overrides={"opening_balance_cents": C.FUND_OPENING_EXACT_FILL_CENTS},
    )
    briefing = fx.draft_briefing(api, ctx["fund_id"], ctx["cycle_id"])
    published = fx.publish_briefing(api, briefing["id"])
    assert published["status"] == "PUBLISHED", (
        f"expected PUBLISHED before certification, got {published['status']}"
    )
    assert published["snapshot_adequacy_band"] == "INSUFFICIENT", (
        f"no cycle is certified yet, so the snapshot froze the fund's default band, "
        f"got {published['snapshot_adequacy_band']}"
    )

    fx.certify(api, ctx["cycle_id"])
    after = fx.read_briefing(api, briefing["id"])

    A.assert_briefing_stale(after, stale_reason="RESERVE_BALANCE_CHANGED")
    A.assert_briefing_snapshot(
        after,
        fund_version=published["snapshot_fund_version"],
        adequacy_band="INSUFFICIENT",
        coverage_ratio_bps=0,
    )
    assert after["published_at"] == published["published_at"], (
        "staleness is not a retraction: published_at is preserved"
    )
    assert after["retracted_at"] is None, (
        f"retracted_at must stay null, got {after['retracted_at']}"
    )


# =========================================================================== #
# transitive_cascade — withdrawal execution
# =========================================================================== #
def test_execution_mints_withdrawal_row_and_arms_the_cooling_off_window(api):
    """PRD §3.8: "`executed_at` is stamped from the logical clock and a ledger row is minted with `origin` `WITHDRAWAL`, `signed_amount_cents` equal to the negation of `authorized_amount_cents`, and `source_cycle_id` set to the request's `cycle_id`; `executed_transaction_id` points at that row."

    PRD §3.8: "Because the row exists, the fund's `balance_cents` falls by `authorized_amount_cents`, `fy_withdrawn_cents` rises by the same amount, `cooling_off_until` becomes the new row's `created_at` plus `cooling_off_days`, `last_transaction_at` becomes the row's `created_at`, and the fund's `version` increments by one."

    Design: Difficulty/transitive_cascade/withdrawal_execution_cascades_ledger_then_adequacy_then_briefing_staleness
    """
    ctx = _certified_chain_with_published_briefing(api)
    approved = _approved_ballot_request(api, ctx)
    A.assert_tally(approved, yes=8, no=1, abstain=2)
    assert approved["authorized_amount_cents"] == C.WITHDRAWAL_AUTHORIZED_AT_CAP_CENTS, (
        f"authorized_amount_cents {approved['authorized_amount_cents']} "
        f"!= {C.WITHDRAWAL_AUTHORIZED_AT_CAP_CENTS}"
    )

    executed = fx.execute_withdrawal(
        api, approved["id"], executor_user_id=U.TREASURER_EXECUTOR_USER_ID
    )
    assert executed["status"] == "EXECUTED", (
        f"expected EXECUTED, got {executed['status']}"
    )
    assert is_valid_uuid(executed["executed_transaction_id"]), (
        f"executed_transaction_id must point at the minted row, "
        f"got {executed['executed_transaction_id']!r}"
    )

    row = get_success_data(
        api.get_reserve_transaction(
            executed["executed_transaction_id"], U.make_director_headers()
        )
    )
    A.assert_transaction_row(
        row,
        origin="WITHDRAWAL",
        signed_amount_cents=-C.WITHDRAWAL_AUTHORIZED_AT_CAP_CENTS,
        source_cycle_id=ctx["cycle_id"],
    )

    fund = fx.read_fund(api, ctx["fund_id"])
    assert fund["balance_cents"] == EXECUTION_BALANCE_CENTS, (
        f"balance_cents {fund['balance_cents']} != {EXECUTION_BALANCE_CENTS}"
    )
    assert fund["fy_withdrawn_cents"] == C.WITHDRAWAL_AUTHORIZED_AT_CAP_CENTS, (
        f"fy_withdrawn_cents {fund['fy_withdrawn_cents']} "
        f"!= {C.WITHDRAWAL_AUTHORIZED_AT_CAP_CENTS}"
    )
    assert fund["cooling_off_until"][:10] == COOLING_OFF_UNTIL_DATE, (
        f"cooling_off_until {fund['cooling_off_until']} is not the row's created_at "
        f"plus {C.FUND_COOLING_OFF_DAYS} days"
    )
    A.assert_ledger_identity(fund, fx.list_transactions(api, fund_id=ctx["fund_id"]))


def test_execution_rescores_coverage_downward_with_required_reserve_unchanged(api):
    """PRD §3.8: "Because the balance changed, the adequacy disclosure is re-derived — `coverage_ratio_bps`, `adequacy_band`, `cushion_credit_bps` and `disclosed_target_pct_bps` all move with it — and `deposit_posture` flips `AT_CAP → ACCEPTING` when `balance_cents` now sits below `cap_cents`."

    Design: Difficulty/transitive_cascade/withdrawal_execution_cascades_ledger_then_adequacy_then_briefing_staleness
    """
    ctx = _certified_chain_with_published_briefing(api)
    before = fx.read_fund(api, ctx["fund_id"])
    A.assert_adequacy_disclosure(
        before,
        required_reserve_cents=C.ADEQUACY_REQUIRED_RESERVE_CENTS,
        coverage_ratio_bps=C.ADEQUACY_COVERAGE_ADEQUATE_BPS,
        adequacy_band="ADEQUATE",
    )

    approved = _approved_ballot_request(api, ctx)
    fx.execute_withdrawal(api, approved["id"], executor_user_id=U.TREASURER_EXECUTOR_USER_ID)
    fund = fx.read_fund(api, ctx["fund_id"])

    A.assert_adequacy_disclosure(
        fund,
        required_reserve_cents=C.ADEQUACY_REQUIRED_RESERVE_CENTS,
        coverage_ratio_bps=EXECUTION_COVERAGE_BPS,
        adequacy_band="ADEQUATE",
        cushion_credit_bps=0,
        disclosed_target_pct_bps=C.TARGET_BAND_LOW_BPS,
    )
    assert fund["deposit_posture"] == "ACCEPTING", (
        f"the balance now sits below the cap, got {fund['deposit_posture']}"
    )


def test_execution_balance_change_stales_the_briefing_with_frozen_snapshot(api):
    """PRD §3.8: "And because the fund's balance changed, every `PUBLISHED` briefing of that fund becomes `STALE` with `stale_reason` `RESERVE_BALANCE_CHANGED`."

    Design: Difficulty/transitive_cascade/withdrawal_execution_cascades_ledger_then_adequacy_then_briefing_staleness
    """
    ctx = _certified_chain_with_published_briefing(api)
    published = ctx["briefing"]
    A.assert_briefing_snapshot(
        published,
        fund_version=published["snapshot_fund_version"],
        adequacy_band="ADEQUATE",
        coverage_ratio_bps=C.ADEQUACY_COVERAGE_ADEQUATE_BPS,
    )

    approved = _approved_ballot_request(api, ctx)
    fx.execute_withdrawal(api, approved["id"], executor_user_id=U.TREASURER_EXECUTOR_USER_ID)
    after = fx.read_briefing(api, ctx["briefing_id"])

    A.assert_briefing_stale(after, stale_reason="RESERVE_BALANCE_CHANGED")
    A.assert_briefing_snapshot(
        after,
        fund_version=published["snapshot_fund_version"],
        adequacy_band="ADEQUATE",
        coverage_ratio_bps=C.ADEQUACY_COVERAGE_ADEQUATE_BPS,
    )


# =========================================================================== #
# priority_pair_validation_conflict — lapse over the two fiscal ceilings
# =========================================================================== #
def test_execute_on_lapsed_authorization_reports_authorization_lapsed(api):
    """PRD §3.8: "Five conditions guard the execution, and they are checked in this order: the request's `status` must be `APPROVED` or `LAPSED` — every other status is refused with `ERR_REQUEST_NOT_APPROVED` (HTTP 409), the `LAPSED` case being deliberately admitted at this rung so that it falls through to its own error at the next one; a request the clock drove to `LAPSED` past its `deadline_date` is then refused with `ERR_AUTHORIZATION_LAPSED` (HTTP 409); the fund's cooling-off window must have elapsed, meaning `cooling_off_until` is null or the logical clock is strictly past it, otherwise `ERR_COOLING_OFF_ACTIVE` (HTTP 409); the executing treasurer must not be the request's `requested_by_user_id`, otherwise `ERR_EXECUTOR_IS_REQUESTER` (HTTP 403); `fy_withdrawn_cents` plus `authorized_amount_cents` must not exceed the fiscal-year withdrawal cap computed as above, otherwise `ERR_ANNUAL_CAP_EXCEEDED` (HTTP 422); and `authorized_amount_cents` must not exceed the fund's current `balance_cents`, otherwise `ERR_INSUFFICIENT_RESERVE_BALANCE` (HTTP 422)."

    PRD §2.9: "Fiscal checks come last on purpose: a request in the wrong state must never leak balance information through a fiscal error."

    Design: Difficulty/priority_pair_validation_conflict/lapsed_authorization_at_priority_22_masks_both_fiscal_ceilings
    """
    ctx = fx.full_chain(
        api,
        "certified",
        fund_overrides={"opening_balance_cents": LAPSE_FUND_OPENING_CENTS},
    )
    request = fx.draft_withdrawal(
        api,
        ctx["fund_id"],
        ctx["cycle_id"],
        requester_user_id=U.TREASURER_REQUESTER_USER_ID,
        requested_amount_cents=C.CERTIFIED_SHORTFALL_GAP_CENTS,
        justification_type="SHORTFALL_TRIGGER",
        deadline_date=LAPSE_DEADLINE_DATE,
    )
    approved = fx.verify_shortfall(api, request["id"])
    assert approved["authorized_amount_cents"] == C.CERTIFIED_SHORTFALL_GAP_CENTS, (
        f"authorized_amount_cents {approved['authorized_amount_cents']} "
        f"!= {C.CERTIFIED_SHORTFALL_GAP_CENTS}"
    )
    fund = fx.read_fund(api, ctx["fund_id"])
    assert fund["balance_cents"] == LAPSE_FUND_BALANCE_CENTS, (
        f"balance_cents {fund['balance_cents']} != {LAPSE_FUND_BALANCE_CENTS}"
    )
    assert approved["authorized_amount_cents"] > fund["balance_cents"], (
        "the authorisation must also breach the balance, so the masking is real"
    )

    clock = fx.set_clock(api, LAPSE_CLOCK)
    assert clock["lapsed_request_count"] == 1, (
        f"lapsed_request_count {clock['lapsed_request_count']} != 1"
    )
    lapsed = fx.read_request(api, request["id"])
    assert lapsed["status"] == "LAPSED", f"expected LAPSED, got {lapsed['status']}"

    response = api.execute_withdrawal(
        request["id"], U.make_treasurer_headers(U.TREASURER_EXECUTOR_USER_ID)
    )
    validate_error(response, ApiErrorId.AUTHORIZATION_LAPSED.value)


def test_lapsed_execution_attempt_leaves_the_ledger_and_authorisation_untouched(api):
    """PRD §3.8: "When the logical clock is advanced past a request's `deadline_date`, that request moves `APPROVED → LAPSED`; `authorized_amount_cents` stays exactly as approved for the audit trail, no ledger row is minted, and the request's `version` increments by one."

    Design: Difficulty/priority_pair_validation_conflict/lapsed_authorization_at_priority_22_masks_both_fiscal_ceilings
    """
    ctx = fx.full_chain(
        api,
        "certified",
        fund_overrides={"opening_balance_cents": LAPSE_FUND_OPENING_CENTS},
    )
    request = fx.draft_withdrawal(
        api,
        ctx["fund_id"],
        ctx["cycle_id"],
        requester_user_id=U.TREASURER_REQUESTER_USER_ID,
        requested_amount_cents=C.CERTIFIED_SHORTFALL_GAP_CENTS,
        justification_type="SHORTFALL_TRIGGER",
        deadline_date=LAPSE_DEADLINE_DATE,
    )
    fx.verify_shortfall(api, request["id"])
    fx.set_clock(api, LAPSE_CLOCK)

    response = api.execute_withdrawal(
        request["id"], U.make_treasurer_headers(U.TREASURER_EXECUTOR_USER_ID)
    )
    validate_error(response, ApiErrorId.AUTHORIZATION_LAPSED.value)

    lapsed = fx.read_request(api, request["id"])
    assert lapsed["status"] == "LAPSED", f"expected LAPSED, got {lapsed['status']}"
    assert lapsed["authorized_amount_cents"] == C.CERTIFIED_SHORTFALL_GAP_CENTS, (
        f"the authorisation stays as approved for the audit trail: "
        f"{lapsed['authorized_amount_cents']} != {C.CERTIFIED_SHORTFALL_GAP_CENTS}"
    )
    assert lapsed["executed_transaction_id"] is None, (
        f"no ledger row is minted, got {lapsed['executed_transaction_id']}"
    )

    rows = fx.list_transactions(api, fund_id=ctx["fund_id"])
    assert len(rows) == 1, f"only the certification deposit exists, got {len(rows)} rows"
    fund = fx.read_fund(api, ctx["fund_id"])
    assert fund["balance_cents"] == LAPSE_FUND_BALANCE_CENTS, (
        f"the rejected call moved nothing: {fund['balance_cents']} "
        f"!= {LAPSE_FUND_BALANCE_CENTS}"
    )
    assert fund["fy_withdrawn_cents"] == 0, (
        f"fy_withdrawn_cents {fund['fy_withdrawn_cents']} != 0"
    )
    A.assert_adequacy_disclosure(
        fund, coverage_ratio_bps=LAPSE_FUND_COVERAGE_BPS, adequacy_band="THIN"
    )


# =========================================================================== #
# priority_pair_validation_conflict — the open ballot over the quorum tally
# =========================================================================== #
def test_close_vote_before_the_window_reports_vote_still_open(api):
    """PRD §2.9: "Temporal checks deliberately precede statutory safety checks: a ballot that is still open has no meaningful tally, so `ERR_VOTE_STILL_OPEN` must win over `ERR_QUORUM_NOT_MET` and `ERR_SUPERMAJORITY_NOT_MET`."

    PRD §3.8: "Closing requires the request to be `VOTE_OPEN` (otherwise `ERR_VOTE_NOT_OPEN`) and requires either that the logical clock has reached `vote_closes_at` or that every eligible seat has cast a ballot; closing early with seats still silent is rejected with `ERR_VOTE_STILL_OPEN` (HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/vote_still_open_at_priority_27_masks_quorum_shortfall_at_priority_35
    """
    ctx = fx.full_chain(api, "certified", fund_overrides={})
    request = fx.draft_withdrawal(
        api,
        ctx["fund_id"],
        ctx["cycle_id"],
        requested_amount_cents=QUORUM_SHORTFALL_REQUESTED_CENTS,
        justification_type="SUPERMAJORITY_VOTE",
        deadline_date=FAR_DEADLINE_DATE,
    )
    opened = fx.open_vote(api, request["id"])
    A.assert_ballot_requirements(
        opened, votes_required=C.VOTES_REQUIRED, quorum_required=C.QUORUM_REQUIRED
    )
    fx.cast_ballots(api, request["id"], yes=2, no=2)

    response = api.close_vote(request["id"], U.make_director_headers())
    validate_error(response, ApiErrorId.VOTE_STILL_OPEN.value)

    still_open = fx.read_request(api, request["id"])
    assert still_open["status"] == "VOTE_OPEN", (
        f"neither approval nor rejection was taken, got {still_open['status']}"
    )
    A.assert_tally(still_open, yes=2, no=2, abstain=0)


def test_close_vote_after_the_window_reports_quorum_not_met(api):
    """PRD §3.8: "Only then is the tally examined, and in a fixed order: total ballots cast must reach `quorum_required`, otherwise `ERR_QUORUM_NOT_MET` (HTTP 422); and only after quorum passes are the yes votes compared against `votes_required`, a shortfall there yielding `ERR_SUPERMAJORITY_NOT_MET` (HTTP 422)."

    Design: Difficulty/priority_pair_validation_conflict/vote_still_open_at_priority_27_masks_quorum_shortfall_at_priority_35
    """
    ctx = fx.full_chain(api, "certified", fund_overrides={})
    request = fx.draft_withdrawal(
        api,
        ctx["fund_id"],
        ctx["cycle_id"],
        requested_amount_cents=QUORUM_SHORTFALL_REQUESTED_CENTS,
        justification_type="SUPERMAJORITY_VOTE",
        deadline_date=FAR_DEADLINE_DATE,
    )
    fx.open_vote(api, request["id"])
    fx.cast_ballots(api, request["id"], yes=2, no=2)
    validate_error(
        api.close_vote(request["id"], U.make_director_headers()),
        ApiErrorId.VOTE_STILL_OPEN.value,
    )

    clock = fx.set_clock(api, AFTER_VOTE_WINDOW_CLOCK)
    assert clock["lapsed_request_count"] == 0, (
        "only an APPROVED request is subject to the deadline lapse, "
        f"got lapsed_request_count {clock['lapsed_request_count']}"
    )

    response = api.close_vote(request["id"], U.make_director_headers())
    validate_error(response, ApiErrorId.QUORUM_NOT_MET.value)

    still_open = fx.read_request(api, request["id"])
    assert still_open["status"] == "VOTE_OPEN", (
        f"the request stays VOTE_OPEN after both rejections, got {still_open['status']}"
    )
    A.assert_tally(still_open, yes=2, no=2, abstain=0)
    fund = fx.read_fund(api, ctx["fund_id"])
    assert fund["balance_cents"] == C.FUND_BALANCE_AFTER_DEPOSIT_CENTS, (
        f"balance_cents {fund['balance_cents']} != {C.FUND_BALANCE_AFTER_DEPOSIT_CENTS}"
    )
    assert fund["fy_withdrawn_cents"] == 0, (
        f"fy_withdrawn_cents {fund['fy_withdrawn_cents']} != 0"
    )
