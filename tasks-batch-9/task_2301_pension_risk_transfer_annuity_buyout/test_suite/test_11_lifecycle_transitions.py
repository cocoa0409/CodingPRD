"""Lifecycle transitions of the Pension Risk Transfer & Annuity Buyout API.

Each test drives one state machine across a single boundary and pins down what
the transition wrote, what a refused transition did *not* write, and which error
identifier a refusal carries. The harness relaunches the API server before every
individual test, so every test builds its own preconditions from an empty
database through declared endpoints only.
"""

from typing import Any, Dict, Tuple

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    PrtApiClient,
    api_errors,
    factories,
    fixtures,
    make_expert_headers,
    make_insurer_rep_headers,
    make_participant_headers,
    types,
)

EPOCH = "2026-08-01T00:00:00Z"

# The window used by the notice, closing and revocation scenarios: half-open
# over [2026-08-01, 2026-09-30), a 10,000,000-cent cash cap and a 3,000,000-cent
# per-participant eligibility ceiling.
WINDOW_CLOSES_AT = "2026-09-30T00:00:00.000Z"
WINDOW_CAP_CENTS = 10000000
WINDOW_ELIGIBILITY_MAX_CENTS = 3000000


# ---------------------------------------------------------------------------
# Local builders -- only what `test_helpers.fixtures` does not already provide
# ---------------------------------------------------------------------------


def _lump_sum_authorized_plan(api: PrtApiClient, **plan_overrides: Any) -> Dict[str, Any]:
    """A plan authorized for lump-sum settlement, effective from the epoch."""
    plan = fixtures.create_plan(api, **plan_overrides)
    fixtures.create_approved_strategy(
        api, plan["id"], types.StrategyType.LUMP_SUM_WINDOW.value
    )
    return fixtures.adopt_amendment(
        api, plan["id"], types.AmendmentScope.LUMP_SUM_ONLY.value, EPOCH
    )


def _clean_deferred(
    api: PrtApiClient,
    plan_id: str,
    stated_monthly_benefit_cents: int,
    final_average_monthly_earnings_cents: int,
    credited_service_months: int,
) -> Dict[str, Any]:
    """A deferred-vested participant walked to a fully cleansed record."""
    return fixtures.create_clean_participant(
        api,
        plan_id,
        cohort=types.Cohort.DEFERRED_VESTED.value,
        stated_monthly_benefit_cents=stated_monthly_benefit_cents,
        final_average_monthly_earnings_cents=final_average_monthly_earnings_cents,
        credited_service_months=credited_service_months,
        date_of_birth="1967-01-01",
    )


def _uncleansed_deferred(
    api: PrtApiClient,
    plan_id: str,
    stated_monthly_benefit_cents: int,
    final_average_monthly_earnings_cents: int,
    credited_service_months: int,
) -> Dict[str, Any]:
    """A deferred-vested participant left exactly as loaded."""
    return fixtures.create_participant(
        api,
        plan_id,
        cohort=types.Cohort.DEFERRED_VESTED.value,
        stated_monthly_benefit_cents=stated_monthly_benefit_cents,
        final_average_monthly_earnings_cents=final_average_monthly_earnings_cents,
        credited_service_months=credited_service_months,
        date_of_birth="1964-08-08",
    )


def _scheduled_window(api: PrtApiClient, plan_id: str, opens_at: str) -> Dict[str, Any]:
    """Schedule the shared window shape without opening it."""
    return fixtures.create_window(
        api,
        plan_id,
        opens_at=opens_at,
        closes_at=WINDOW_CLOSES_AT,
        lump_sum_cap_cents=WINDOW_CAP_CENTS,
        eligibility_max_lump_sum_cents=WINDOW_ELIGIBILITY_MAX_CENTS,
    )


def _opened_window(api: PrtApiClient, plan_id: str, opens_at: str) -> Dict[str, Any]:
    """Schedule the shared window, move the clock to its lower bound, open it."""
    window = _scheduled_window(api, plan_id, opens_at)
    fixtures.set_clock(api, opens_at)
    return fixtures.open_window(api, window["id"])


def _election_count(api: PrtApiClient, headers: Dict[str, str], **filters: Any) -> int:
    """How many notice rows match the given filters."""
    _rows, meta = validate_paginated(api.list_elections(headers, filters))
    return meta["total_count"]


def _locked_buyout_tranche(api: PrtApiClient) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """A tranche locked on an 11,800,000-cent premium with a 90-day lock.

    Returns the receiving carrier and the locked tranche.
    """
    authorized = fixtures.build_authorized_plan(
        api,
        participants=[
            fixtures.ParticipantSpec(
                stated_monthly_benefit_cents=100000,
                cohort=types.Cohort.DEFERRED_VESTED.value,
                credited_service_months=320,
                final_average_monthly_earnings_cents=250000,
                date_of_birth="1968-04-04",
            )
        ],
        strategy_type=types.StrategyType.ANNUITY_BUYOUT.value,
        amendment_scope=types.AmendmentScope.BUYOUT_ONLY.value,
        amendment_effective_date=EPOCH,
    )
    insurer = fixtures.create_insurer(
        api,
        insurer_name="Beacon National Life",
        rating_grade=types.RatingGrade.AA_MINUS.value,
        capital_ratio_bp=3800,
        capacity_cents=200000000,
    )
    tranche = fixtures.build_locked_tranche(
        api,
        authorized.plan_id,
        authorized.participants,
        quotes=[
            fixtures.QuoteSpec(
                insurer_id=insurer["id"],
                premium_cents=11800000,
                lock_days=90,
                quote_valid_days=60,
            )
        ],
        target_cohort=types.Cohort.DEFERRED_VESTED.value,
        tranche_name="Ashcroft Deferred Vested Tranche",
    )
    return insurer, tranche


def _residual_plan(
    api: PrtApiClient,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """A plan bubbled to `RESIDUAL` by one settled lump-sum window.

    Returns the plan, the participant paid out through the window, and the
    participant who never received a notice and so never left the plan.
    """
    plan = _lump_sum_authorized_plan(
        api,
        total_liability_cents=100000000,
        plan_assets_cents=120000000,
        service_cost_cents=3000000,
        interest_cost_cents=9000000,
        unrecognized_actuarial_loss_cents=4000000,
        discount_rate_bps=500,
    )
    electing = _clean_deferred(api, plan["id"], 20000, 100000, 160)
    remaining = _uncleansed_deferred(api, plan["id"], 100000, 250000, 320)
    window = _opened_window(api, plan["id"], EPOCH)
    election = fixtures.election_for(api, window["id"], electing["id"])
    fixtures.elect(api, election["id"], electing["id"], types.ElectionChoice.LUMP_SUM.value)
    fixtures.set_clock(api, WINDOW_CLOSES_AT)
    fixtures.close_window(api, window["id"])
    fixtures.settle_window(api, window["id"])
    return fixtures.read_plan(api, plan["id"]), electing, remaining


# ---------------------------------------------------------------------------
# Initial states
# ---------------------------------------------------------------------------


class TestDeclaredInitialStates:
    """Freshly minted children start where the contract says, and nowhere else."""

    def test_lifecycle_drafted_strategy_is_born_in_draft_with_nothing_projected(
        self, api: PrtApiClient, actuary: Dict[str, str]
    ) -> None:
        """A newly drafted strategy sits in DRAFT with every projection and decision field unset.

        A drafted strategy starts in `DRAFT` with `revision_count` at 0, its `ldi_hedge_ratio_bp` at 0 — the target liability-driven-investing hedge ratio in basis points, between 0 and 10000, recorded for glidepath and hybrid options — and its `projected_accounting_cost_cents`, `projected_settlement_cost_cents`, `projected_basis_gap_cents`, `submitted_by_user_id`, `decided_by_user_id`, and `decision_rationale` all unset, with `in_scope_participant_count` at 0.

        Design: Corner/state_machines/strategy_and_window_are_born_in_their_declared_initial_states
        """
        plan = fixtures.create_plan(api)
        strategy = validate_success(
            api.create_strategy(
                plan["id"],
                factories.strategy_payload(
                    types.StrategyType.HYBRID_WINDOW_AND_BUYOUT.value,
                    strategy_name="Ashcroft Hybrid Programme",
                ),
                actuary,
            ),
            201,
        )
        assert strategy["strategy_status"] == types.StrategyStatus.DRAFT.value
        assert strategy["strategy_label"] == "Ashcroft Hybrid Programme"
        assert strategy["revision_count"] == 0
        assert strategy["ldi_hedge_ratio_bp"] == 0
        assert strategy["in_scope_participant_count"] == 0
        for unset_field in (
            "projected_accounting_cost_cents",
            "projected_settlement_cost_cents",
            "projected_basis_gap_cents",
            "submitted_by_user_id",
            "decided_by_user_id",
            "decision_rationale",
        ):
            assert strategy[unset_field] is None

        rows, meta = validate_paginated(api.list_strategies(plan["id"], actuary))
        assert meta["total_count"] == 1
        assert rows[0]["id"] == strategy["id"]
        assert rows[0]["strategy_status"] == types.StrategyStatus.DRAFT.value

    def test_lifecycle_scheduled_window_is_born_planned_with_zero_totals(
        self, api: PrtApiClient, administrator: Dict[str, str]
    ) -> None:
        """A scheduled window sits in PLANNED with zeroed counters, null stamps, and an untouched plan.

        A window starts in `PLANNED` with `notice_count` at 0, `approved_lump_sum_total_cents` and `paid_lump_sum_total_cents` at 0, and `opened_at`, `closed_at`, and `settled_at` all null.
        A new plan starts with a `plan_status` of `ONGOING`, has its `participant_liability_total_cents` set to 0 because it has no participants yet, and has its `accounting_funded_status_bp` derived immediately.

        Design: Corner/state_machines/strategy_and_window_are_born_in_their_declared_initial_states
        """
        plan = fixtures.create_plan(api)
        window = validate_success(
            api.create_window(
                plan["id"],
                factories.window_payload(
                    lump_sum_cap_cents=WINDOW_CAP_CENTS,
                    eligibility_max_lump_sum_cents=WINDOW_ELIGIBILITY_MAX_CENTS,
                    window_name="Ashcroft Window One",
                ),
                administrator,
            ),
            201,
        )
        assert window["window_status"] == types.WindowStatus.PLANNED.value
        assert window["window_label"] == "Ashcroft Window One"
        assert window["notice_count"] == 0
        assert window["approved_lump_sum_total_cents"] == 0
        assert window["paid_lump_sum_total_cents"] == 0
        assert window["opened_at"] is None
        assert window["closed_at"] is None
        assert window["settled_at"] is None

        assert (
            fixtures.read_plan(api, plan["id"])["plan_status"]
            == types.PlanStatus.ONGOING.value
        )


# ---------------------------------------------------------------------------
# Strategy submission and decision guards
# ---------------------------------------------------------------------------


class TestStrategyTransitionGuards:
    """The strategy machine refuses to be entered from the wrong state."""

    def test_lifecycle_strategy_decision_on_a_draft_strategy_is_refused(
        self, api: PrtApiClient, fiduciary: Dict[str, str], actuary: Dict[str, str]
    ) -> None:
        """Approving a strategy that was never submitted is refused and writes nothing.

        The strategy must be `UNDER_EVALUATION`, and the deciding `X-User-ID` must differ from the recorded `submitted_by_user_id`; an actuary who tries to approve their own submission is rejected with `ERR_SEGREGATION_OF_DUTIES`.
        **Own-state precondition** — the target resource's own status field permits the requested transition, else the entity-specific conflict error: `ERR_PLAN_STATE_INVALID`, `ERR_STRATEGY_STATE_INVALID`, `ERR_PARTICIPANT_STATE_INVALID`, `ERR_AUDIT_STATE_INVALID`, `ERR_WINDOW_STATE_INVALID`, `ERR_ELECTION_STATE_INVALID`, `ERR_TRANCHE_STATE_INVALID`, `ERR_QUOTE_STATE_INVALID`, `ERR_EXPERT_STATE_INVALID`, `ERR_TRANSFER_STATE_INVALID`, or `ERR_COMPLAINT_STATE_INVALID`, all HTTP 409. Applies to every state-transition endpoint.

        Design: Corner/state_machines/strategy_decision_on_a_draft_strategy_is_rejected
        """
        plan = fixtures.create_plan(api)
        strategy = fixtures.create_strategy(
            api, plan["id"], types.StrategyType.LUMP_SUM_WINDOW.value
        )

        validate_error(
            api.post_strategy_decision(
                strategy["id"],
                factories.strategy_decision_payload(types.StrategyDecision.APPROVE.value),
                fiduciary,
            ),
            api_errors.ERR_STRATEGY_STATE_INVALID,
        )

        rows, _meta = validate_paginated(api.list_strategies(plan["id"], actuary))
        unchanged = rows[0]
        assert unchanged["strategy_status"] == types.StrategyStatus.DRAFT.value
        assert unchanged["decided_by_user_id"] is None
        assert unchanged["decision_rationale"] is None
        assert unchanged["version"] == 1
        assert (
            fixtures.read_plan(api, plan["id"])["plan_status"]
            == types.PlanStatus.ONGOING.value
        )

    def test_lifecycle_second_strategy_submission_is_refused_and_writes_nothing(
        self, api: PrtApiClient, actuary: Dict[str, str]
    ) -> None:
        """A submitted strategy records its submitter once and refuses to be re-submitted.

        Submitting the strategy moves it `DRAFT → UNDER_EVALUATION` and is the moment the projection is priced.
        Submission records `submitted_by_user_id` from the acting `X-User-ID` and bumps the strategy's `version`.
        All resources except one additionally carry `updated_at`, an ISO 8601 UTC timestamp refreshed on every mutation of the resource, and `version`, an integer that starts at 1 and increments by one on every mutation.
        **Own-state precondition** — the target resource's own status field permits the requested transition, else the entity-specific conflict error: `ERR_PLAN_STATE_INVALID`, `ERR_STRATEGY_STATE_INVALID`, `ERR_PARTICIPANT_STATE_INVALID`, `ERR_AUDIT_STATE_INVALID`, `ERR_WINDOW_STATE_INVALID`, `ERR_ELECTION_STATE_INVALID`, `ERR_TRANCHE_STATE_INVALID`, `ERR_QUOTE_STATE_INVALID`, `ERR_EXPERT_STATE_INVALID`, `ERR_TRANSFER_STATE_INVALID`, or `ERR_COMPLAINT_STATE_INVALID`, all HTTP 409. Applies to every state-transition endpoint.

        Design: Corner/state_machines/strategy_second_submission_is_rejected_rather_than_re_evaluated
        """
        plan = fixtures.create_plan(api)
        strategy = fixtures.create_strategy(
            api, plan["id"], types.StrategyType.LUMP_SUM_WINDOW.value
        )
        submitted = validate_success(api.post_strategy_submission(strategy["id"], {}, actuary))
        assert submitted["strategy_status"] == types.StrategyStatus.UNDER_EVALUATION.value
        assert submitted["submitted_by_user_id"] == actuary["X-User-ID"]
        assert submitted["version"] == 2

        validate_error(
            api.post_strategy_submission(strategy["id"], {}, actuary),
            api_errors.ERR_STRATEGY_STATE_INVALID,
        )

        rows, _meta = validate_paginated(api.list_strategies(plan["id"], actuary))
        after = rows[0]
        assert after["strategy_status"] == types.StrategyStatus.UNDER_EVALUATION.value
        assert after["version"] == 2
        assert after["revision_count"] == 0


# ---------------------------------------------------------------------------
# Opening a window
# ---------------------------------------------------------------------------


class TestWindowOpening:
    """The window opens on its lower bound, not before, and fans out selectively."""

    def test_lifecycle_window_opening_before_opens_at_is_refused(
        self, api: PrtApiClient, administrator: Dict[str, str]
    ) -> None:
        """Opening a window while the clock is still short of opens_at is refused and leaves it PLANNED.

        Opening the window moves it `PLANNED → OPEN` and is gated on the plan's own authorization.
        The logical clock must be at or after `opens_at` and strictly before `closes_at`, and a clock outside that half-open interval is rejected with `ERR_WINDOW_STATE_INVALID`.

        Design: Corner/state_machines/window_opening_before_opens_at_is_refused_then_succeeds_at_opens_at
        """
        plan = _lump_sum_authorized_plan(api)
        assert plan["plan_status"] == types.PlanStatus.SETTLEMENT_AUTHORIZED.value
        assert plan["amendment_scope"] == types.AmendmentScope.LUMP_SUM_ONLY.value

        window = fixtures.create_window(
            api,
            plan["id"],
            opens_at="2026-09-01T00:00:00Z",
            closes_at="2026-10-31T00:00:00Z",
        )
        # The clock still reads the startup instant, a full month before `opens_at`.
        validate_error(
            api.post_window_opening(window["id"], {}, administrator),
            api_errors.ERR_WINDOW_STATE_INVALID,
        )

        rows, _meta = validate_paginated(api.list_windows(plan["id"], administrator))
        assert rows[0]["window_status"] == types.WindowStatus.PLANNED.value
        assert rows[0]["opened_at"] is None
        assert rows[0]["version"] == 1

    def test_lifecycle_window_opening_succeeds_exactly_at_opens_at(
        self, api: PrtApiClient, administrator: Dict[str, str]
    ) -> None:
        """At exactly opens_at the window opens, and with no cleansed participant it sends no notice.

        The logical clock must be at or after `opens_at` and strictly before `closes_at`, and a clock outside that half-open interval is rejected with `ERR_WINDOW_STATE_INVALID`.
        One election is created for every participant of the window's plan who satisfies all four of these predicates simultaneously: `participant_status` is `IN_PLAN`, `mortality_status` is `ALIVE_CONFIRMED`, `address_status` is `CONFIRMED`, and the participant's raw present value is at most the window's `eligibility_max_lump_sum_cents`.
        The number of elections created is stored in the window's `notice_count`, and the window's `version` is bumped.

        Design: Corner/state_machines/window_opening_before_opens_at_is_refused_then_succeeds_at_opens_at
        """
        plan = _lump_sum_authorized_plan(api)
        window = fixtures.create_window(
            api,
            plan["id"],
            opens_at="2026-09-01T00:00:00Z",
            closes_at="2026-10-31T00:00:00Z",
        )
        fixtures.set_clock(api, "2026-09-01T00:00:00Z")

        opened = validate_success(api.post_window_opening(window["id"], {}, administrator))
        assert opened["window_status"] == types.WindowStatus.OPEN.value
        assert opened["opened_at"] == "2026-09-01T00:00:00.000Z"
        assert opened["notice_count"] == 0
        assert _election_count(api, administrator, window_id=window["id"]) == 0

    def test_lifecycle_window_opening_notices_the_clean_and_eligible_participant(
        self, api: PrtApiClient, administrator: Dict[str, str]
    ) -> None:
        """Opening sends exactly one notice, to the cleansed participant priced inside the ceiling.

        One election is created for every participant of the window's plan who satisfies all four of these predicates simultaneously: `participant_status` is `IN_PLAN`, `mortality_status` is `ALIVE_CONFIRMED`, `address_status` is `CONFIRMED`, and the participant's raw present value is at most the window's `eligibility_max_lump_sum_cents`.
        Each created election starts in `NOTICE_SENT`, records `notice_sent_at` and its `window_id` and `participant_id`, and stores its `notice_estimated_lump_sum_cents` as the raw present value computed at notice time.
        It is multiplied by twelve to give an annual amount, that annual amount is multiplied by the lump-sum factor for the participant's `cohort` — 121,000 basis points for `RETIREE_IN_PAY` and 100,000 basis points for `DEFERRED_VESTED`, meaning a deferred-vested participant's raw present value is exactly 120 times the monthly benefit — and the product is rounded half up over 10,000 to give `raw_pv_cents`.

        Design: Corner/state_machines/window_opening_fans_notices_only_to_clean_and_eligible_participants
        """
        plan = _lump_sum_authorized_plan(api)
        eligible = _clean_deferred(api, plan["id"], 20000, 100000, 160)
        _clean_deferred(api, plan["id"], 30000, 100000, 240)
        _uncleansed_deferred(api, plan["id"], 20000, 100000, 160)

        opened = _opened_window(api, plan["id"], EPOCH)
        assert opened["window_status"] == types.WindowStatus.OPEN.value
        assert opened["notice_count"] == 1

        rows, meta = validate_paginated(
            api.list_elections(administrator, {"window_id": opened["id"]})
        )
        assert meta["total_count"] == 1
        notice = rows[0]
        assert notice["participant_id"] == eligible["id"]
        assert notice["window_id"] == opened["id"]
        assert notice["election_status"] == types.ElectionStatus.NOTICE_SENT.value
        assert notice["notice_estimated_lump_sum_cents"] == 2400000

    def test_lifecycle_window_opening_skips_the_over_ceiling_and_uncleansed_participants(
        self, api: PrtApiClient, administrator: Dict[str, str]
    ) -> None:
        """A participant priced above the ceiling and one never cleansed are both passed over silently.

        One election is created for every participant of the window's plan who satisfies all four of these predicates simultaneously: `participant_status` is `IN_PLAN`, `mortality_status` is `ALIVE_CONFIRMED`, `address_status` is `CONFIRMED`, and the participant's raw present value is at most the window's `eligibility_max_lump_sum_cents`.
        Participants failing any predicate are skipped silently — no error, no election.
        It is multiplied by twelve to give an annual amount, that annual amount is multiplied by the lump-sum factor for the participant's `cohort` — 121,000 basis points for `RETIREE_IN_PAY` and 100,000 basis points for `DEFERRED_VESTED`, meaning a deferred-vested participant's raw present value is exactly 120 times the monthly benefit — and the product is rounded half up over 10,000 to give `raw_pv_cents`.
        A freshly loaded participant therefore scores 25 and is `NEEDS_REVIEW`; a participant who is `CONFIRMED`, `ALIVE_CONFIRMED`, and `PASSED_CLOSED` scores 100; one who is `CONFIRMED`, `ALIVE_CONFIRMED`, and `CORRECTION_REQUIRED` scores 85 and is still `CLEAN`; and one who is `CONFIRMED` but `UNVERIFIED` with a closed audit sits at exactly 80, which is `CLEAN` because the boundary is inclusive.

        Design: Corner/state_machines/window_opening_fans_notices_only_to_clean_and_eligible_participants
        """
        plan = _lump_sum_authorized_plan(api)
        _clean_deferred(api, plan["id"], 20000, 100000, 160)
        # 30,000 cents a month prices at 3,600,000 — past the 3,000,000 ceiling.
        over_ceiling = _clean_deferred(api, plan["id"], 30000, 100000, 240)
        # Priced at 2,400,000, inside the ceiling, but never cleansed.
        uncleansed = _uncleansed_deferred(api, plan["id"], 20000, 100000, 160)

        opened = _opened_window(api, plan["id"], EPOCH)
        assert opened["notice_count"] == 1

        assert over_ceiling["data_status"] == types.DataStatus.CLEAN.value
        assert _election_count(api, administrator, participant_id=over_ceiling["id"]) == 0

        assert uncleansed["data_confidence_score"] == 25
        assert uncleansed["data_status"] == types.DataStatus.NEEDS_REVIEW.value
        assert _election_count(api, administrator, participant_id=uncleansed["id"]) == 0


# ---------------------------------------------------------------------------
# Closing a window
# ---------------------------------------------------------------------------


class TestWindowClosing:
    """Closing turns silence into a decision and honours whoever answered."""

    def test_lifecycle_window_closing_defaults_the_silent_notice(
        self, api: PrtApiClient
    ) -> None:
        """A notice never answered lands in DEFAULTED_NO_RESPONSE with no pricing and the participant kept.

        Closing a window moves it `OPEN → CLOSED` and may only be requested once the logical clock has reached `closes_at`; an early attempt is rejected with `ERR_WINDOW_STATE_INVALID`.
        First, every election of the window still sitting in `NOTICE_SENT` transitions to `DEFAULTED_NO_RESPONSE` — silence is a decision, and the participant keeps their annuity.

        Design: Corner/state_machines/window_closing_defaults_silent_notices_and_honours_the_responder
        """
        plan = _lump_sum_authorized_plan(api)
        responder = _clean_deferred(api, plan["id"], 20000, 100000, 160)
        silent = _clean_deferred(api, plan["id"], 24000, 100000, 192)

        opened = _opened_window(api, plan["id"], EPOCH)
        assert opened["notice_count"] == 2

        responder_notice = fixtures.election_for(api, opened["id"], responder["id"])
        fixtures.set_clock(api, "2026-08-05T00:00:00Z")
        fixtures.elect(
            api,
            responder_notice["id"],
            responder["id"],
            types.ElectionChoice.LUMP_SUM.value,
        )

        fixtures.set_clock(api, WINDOW_CLOSES_AT)
        closed = fixtures.close_window(api, opened["id"])
        assert closed["window_status"] == types.WindowStatus.CLOSED.value

        defaulted = fixtures.election_for(api, opened["id"], silent["id"])
        assert defaulted["election_status"] == types.ElectionStatus.DEFAULTED_NO_RESPONSE.value
        assert defaulted["election_choice"] is None
        assert defaulted["net_lump_sum_cents"] is None
        assert (
            fixtures.read_participant(api, silent["id"])["participant_status"]
            == types.ParticipantStatus.IN_PLAN.value
        )

    def test_lifecycle_window_closing_honours_the_responder_in_the_approved_total(
        self, api: PrtApiClient
    ) -> None:
        """Only the answered lump-sum election is walked into the approved total, and nobody is paid yet.

        For each election in turn, the running total plus that election's `net_lump_sum_cents` is compared against the window's `lump_sum_cap_cents`.
        If the candidate total is at most the cap, the election stays `ELECTED_LUMP_SUM` and the running total becomes the candidate total.
        When the walk finishes, the running total is stored as `approved_lump_sum_total_cents`.
        In the second hop, because those elections became `PAID`, each corresponding participant transitions `IN_PLAN → SETTLED_LUMP_SUM` and has its `tranche_id` cleared.

        Design: Corner/state_machines/window_closing_defaults_silent_notices_and_honours_the_responder
        """
        plan = _lump_sum_authorized_plan(api)
        responder = _clean_deferred(api, plan["id"], 20000, 100000, 160)
        _clean_deferred(api, plan["id"], 24000, 100000, 192)

        opened = _opened_window(api, plan["id"], EPOCH)
        responder_notice = fixtures.election_for(api, opened["id"], responder["id"])
        fixtures.set_clock(api, "2026-08-05T00:00:00Z")
        priced = fixtures.elect(
            api,
            responder_notice["id"],
            responder["id"],
            types.ElectionChoice.LUMP_SUM.value,
        )
        assert priced["admin_fee_bp"] == 0
        assert priced["admin_fee_cents"] == 0
        assert priced["net_lump_sum_cents"] == 2400000

        fixtures.set_clock(api, WINDOW_CLOSES_AT)
        closed = fixtures.close_window(api, opened["id"])
        assert closed["approved_lump_sum_total_cents"] == 2400000
        assert closed["paid_lump_sum_total_cents"] == 0

        honoured = fixtures.read_election(api, responder_notice["id"])
        assert honoured["election_status"] == types.ElectionStatus.ELECTED_LUMP_SUM.value
        assert (
            fixtures.read_participant(api, responder["id"])["participant_status"]
            == types.ParticipantStatus.IN_PLAN.value
        )


# ---------------------------------------------------------------------------
# Election revocation
# ---------------------------------------------------------------------------


class TestElectionRevocation:
    """The election may be taken back exactly once, and the take-back is total."""

    def test_lifecycle_election_revocation_returns_to_notice_sent_and_clears_pricing(
        self, api: PrtApiClient
    ) -> None:
        """Revoking a lump-sum election returns it to NOTICE_SENT and erases every priced field.

        Choosing the lump sum moves the election `NOTICE_SENT → ELECTED_LUMP_SUM`, stamps `elected_at` with the logical clock, records `election_choice`, and prices the offer immediately, storing `raw_pv_cents`, `admin_fee_bp`, `admin_fee_cents`, and `net_lump_sum_cents`.
        A `raw_pv_cents` of at most 2,400,000 (twenty-four thousand dollars) sets `admin_fee_bp` to 0.
        A revocation returns an election from either `ELECTED_LUMP_SUM` or `ELECTED_ANNUITY` back to `NOTICE_SENT`, with identical preconditions and identical consequences in both directions.
        A successful revocation clears `elected_at`, `election_choice`, `raw_pv_cents`, `admin_fee_bp`, `admin_fee_cents`, and `net_lump_sum_cents`, increments `revocation_count` by one, and bumps the `version` — leaving the participant free to elect again from a clean slate within the same window.

        Design: Corner/state_machines/election_revocation_clears_pricing_and_the_second_revocation_is_refused
        """
        plan = _lump_sum_authorized_plan(api)
        participant = _clean_deferred(api, plan["id"], 20000, 100000, 160)
        opened = _opened_window(api, plan["id"], EPOCH)
        notice = fixtures.election_for(api, opened["id"], participant["id"])

        fixtures.set_clock(api, "2026-08-05T00:00:00Z")
        elected = fixtures.elect(
            api, notice["id"], participant["id"], types.ElectionChoice.LUMP_SUM.value
        )
        assert elected["election_status"] == types.ElectionStatus.ELECTED_LUMP_SUM.value
        assert elected["elected_at"] == "2026-08-05T00:00:00.000Z"
        assert elected["raw_pv_cents"] == 2400000
        assert elected["admin_fee_cents"] == 0
        assert elected["net_lump_sum_cents"] == 2400000

        fixtures.set_clock(api, "2026-08-10T00:00:00Z")
        revoked = fixtures.revoke_election(api, notice["id"], participant["id"])
        assert revoked["election_status"] == types.ElectionStatus.NOTICE_SENT.value
        assert revoked["revocation_count"] == 1
        for cleared in (
            "elected_at",
            "election_choice",
            "raw_pv_cents",
            "admin_fee_bp",
            "admin_fee_cents",
            "net_lump_sum_cents",
        ):
            assert revoked[cleared] is None

    def test_lifecycle_second_election_revocation_is_refused_on_the_count(
        self, api: PrtApiClient
    ) -> None:
        """Re-electing the annuity prices nothing and leaves the counter spent, so a second revocation fails.

        Choosing the annuity moves the election `NOTICE_SENT → ELECTED_ANNUITY` and likewise stamps `elected_at` and records `election_choice`, but no pricing runs: `raw_pv_cents`, `admin_fee_bp`, `admin_fee_cents`, and `net_lump_sum_cents` all stay null, because the participant is keeping their annuity and staying in the plan.
        The logical clock must be at or before seven days after `elected_at` and strictly before the window's `closes_at`; a late attempt is rejected with `ERR_REVOCATION_PERIOD_ELAPSED`.
        And `revocation_count` must be below 1, so a second revocation of the same election is rejected with `ERR_ELECTION_STATE_INVALID`.

        Design: Corner/state_machines/election_revocation_clears_pricing_and_the_second_revocation_is_refused
        """
        plan = _lump_sum_authorized_plan(api)
        participant = _clean_deferred(api, plan["id"], 20000, 100000, 160)
        opened = _opened_window(api, plan["id"], EPOCH)
        notice = fixtures.election_for(api, opened["id"], participant["id"])

        fixtures.set_clock(api, "2026-08-05T00:00:00Z")
        fixtures.elect(
            api, notice["id"], participant["id"], types.ElectionChoice.LUMP_SUM.value
        )
        fixtures.set_clock(api, "2026-08-10T00:00:00Z")
        fixtures.revoke_election(api, notice["id"], participant["id"])

        re_elected = fixtures.elect(
            api, notice["id"], participant["id"], types.ElectionChoice.ANNUITY.value
        )
        assert re_elected["election_status"] == types.ElectionStatus.ELECTED_ANNUITY.value
        assert re_elected["elected_at"] == "2026-08-10T00:00:00.000Z"
        assert re_elected["raw_pv_cents"] is None
        assert re_elected["admin_fee_bp"] is None
        assert re_elected["admin_fee_cents"] is None
        assert re_elected["net_lump_sum_cents"] is None
        assert re_elected["revocation_count"] == 1

        # The clock is still inside both the seven-day revocation period and the
        # window, so only the spent counter can refuse this.
        validate_error(
            api.post_election_revocation(
                notice["id"], {}, make_participant_headers(participant["id"])
            ),
            api_errors.ERR_ELECTION_STATE_INVALID,
        )
        after = fixtures.read_election(api, notice["id"])
        assert after["election_status"] == types.ElectionStatus.ELECTED_ANNUITY.value
        assert after["revocation_count"] == 1


# ---------------------------------------------------------------------------
# The address locator ladder
# ---------------------------------------------------------------------------


class TestAddressSearchLadder:
    """Two failed searches are a self-loop; the third leaves the loop for good."""

    def test_lifecycle_address_search_self_loops_through_the_first_two_tiers(
        self, api: PrtApiClient
    ) -> None:
        """The first two failed searches only advance the tier counter, leaving the record UNCONFIRMED at 25.

        Each recorded attempt increments `address_search_attempts` by one and sets `address_search_tier` to the tier corresponding to the new attempt count — `TIER_1` after the first, `TIER_2` after the second, `TIER_3` after the third — reflecting the escalation from cheap batch matching to premium skip tracing.
        A `NO_MATCH` recorded while fewer than two attempts have already been made leaves the participant in `UNCONFIRMED`, a self-loop that only advances the tier and bumps the participant's `version`.
        A freshly loaded participant therefore scores 25 and is `NEEDS_REVIEW`; a participant who is `CONFIRMED`, `ALIVE_CONFIRMED`, and `PASSED_CLOSED` scores 100; one who is `CONFIRMED`, `ALIVE_CONFIRMED`, and `CORRECTION_REQUIRED` scores 85 and is still `CLEAN`; and one who is `CONFIRMED` but `UNVERIFIED` with a closed audit sits at exactly 80, which is `CLEAN` because the boundary is inclusive.

        Design: Corner/state_machines/address_search_escalates_three_tiers_then_lands_unlocatable
        """
        plan = fixtures.create_plan(api)
        participant = _uncleansed_deferred(api, plan["id"], 20000, 100000, 160)
        assert participant["address_status"] == types.AddressStatus.UNCONFIRMED.value
        assert participant["address_search_attempts"] == 0
        assert participant["address_search_tier"] == types.AddressSearchTier.NONE.value
        assert participant["data_confidence_score"] == 25

        first = fixtures.record_address_no_match(api, participant["id"])
        assert first["address_status"] == types.AddressStatus.UNCONFIRMED.value
        assert first["address_search_attempts"] == 1
        assert first["address_search_tier"] == types.AddressSearchTier.TIER_1.value
        assert first["data_confidence_score"] == 25

        second = fixtures.record_address_no_match(api, participant["id"])
        assert second["address_status"] == types.AddressStatus.UNCONFIRMED.value
        assert second["address_search_attempts"] == 2
        assert second["address_search_tier"] == types.AddressSearchTier.TIER_2.value
        assert second["data_confidence_score"] == 25

    def test_lifecycle_third_address_search_lands_unlocatable_and_lifts_the_score(
        self, api: PrtApiClient
    ) -> None:
        """The third failed search moves the record to UNLOCATABLE at TIER_3, lifting the score to 40 alone.

        A `NO_MATCH` recorded when exactly two attempts already stand is the third and final one: it moves the participant `UNCONFIRMED → UNLOCATABLE`, sets `address_search_attempts` to 3 and `address_search_tier` to `TIER_3`, and recomputes `data_confidence_score` and `data_status`.
        An `address_status` of `UNCONFIRMED` costs 40 points, while an `address_status` of `UNLOCATABLE` costs only 25 — an exhausted search is a documented outcome, an un-started one is not, so a participant whose locator ladder is exhausted can still reach 75 while one who has never been searched sits at 60.
        A `mortality_status` of `UNVERIFIED` or `DEATH_DISPUTED` costs 20 points.
        A `benefit_audit_status` of `NOT_AUDITED`, `AUDIT_OPEN`, `CORRECTION_REQUIRED`, or `REOPENED` costs 15 points.
        A participant may be `ASSIGNED` to a tranche while still `UNVERIFIED` for mortality and `UNCONFIRMED` for address; advancing one dimension never advances another.

        Design: Corner/state_machines/address_search_escalates_three_tiers_then_lands_unlocatable
        """
        plan = fixtures.create_plan(api)
        participant = _uncleansed_deferred(api, plan["id"], 20000, 100000, 160)
        fixtures.record_address_no_match(api, participant["id"])
        fixtures.record_address_no_match(api, participant["id"])

        third = fixtures.record_address_no_match(api, participant["id"])
        assert third["address_status"] == types.AddressStatus.UNLOCATABLE.value
        assert third["address_search_attempts"] == 3
        assert third["address_search_tier"] == types.AddressSearchTier.TIER_3.value
        assert third["data_confidence_score"] == 40
        assert third["data_status"] == types.DataStatus.NEEDS_REVIEW.value
        assert third["confirmed_address_line1"] is None
        assert third["confirmed_postal_code"] is None
        assert third["version"] == 4

        # The other two dimensions never moved with the address dimension.
        assert third["mortality_status"] == types.MortalityStatus.UNVERIFIED.value
        assert third["participant_status"] == types.ParticipantStatus.IN_PLAN.value


# ---------------------------------------------------------------------------
# A disqualified independent expert
# ---------------------------------------------------------------------------


class TestDisqualifiedExpertIsTerminal:
    """`DISQUALIFIED` admits no transition, and the two exits fail differently."""

    def test_lifecycle_disqualified_expert_cannot_issue_an_opinion(
        self, api: PrtApiClient
    ) -> None:
        """A disqualified engagement is refused the opinion endpoint and keeps a null opinion.

        `ENGAGE` moves the engagement `INDEPENDENCE_REVIEW → ENGAGED` and `DISQUALIFY` moves it `INDEPENDENCE_REVIEW → DISQUALIFIED`; both record `reviewed_by_user_id` and bump the `version`, and both `ENGAGED` and `DISQUALIFIED` are reached with equal finality — `DISQUALIFIED` is terminal.
        The engagement must be in `ENGAGED`, otherwise `ERR_EXPERT_NOT_ENGAGED`, and the acting `X-User-ID` must be this engagement's own identifier, otherwise `ERR_IDENTITY_MISMATCH`.
        **Named-state precondition** — the specialised variants that name the *required* state instead of complaining about the current one: `ERR_TRANCHE_NOT_SELECTED`, `ERR_TRANCHE_NOT_TRANSFERRED`, `ERR_QUOTE_NOT_REQUESTED`, `ERR_EXPERT_NOT_ENGAGED`, `ERR_TRANSFER_NOT_INITIATED`, `ERR_COMPLAINT_NOT_TRIAGED`, and `ERR_WINDOW_NOT_OPEN`, all HTTP 409.

        Design: Corner/state_machines/disqualified_expert_is_terminal_and_can_neither_opine_nor_be_re_reviewed
        """
        plan = fixtures.create_plan(api)
        expert = fixtures.create_expert(
            api, plan["id"], "Marlowe Actuarial Advisors", conflict_disclosed=True
        )
        disqualified = fixtures.review_expert(
            api, expert["id"], types.ExpertReviewDecision.DISQUALIFY.value
        )
        assert disqualified["expert_status"] == types.ExpertStatus.DISQUALIFIED.value
        assert disqualified["reviewed_by_user_id"] is not None
        assert disqualified["version"] == 2

        validate_error(
            api.post_expert_opinion(
                expert["id"],
                factories.expert_opinion_payload(
                    types.SafestAvailableOpinion.AFFIRMATIVE.value
                ),
                make_expert_headers(expert["id"]),
            ),
            api_errors.ERR_EXPERT_NOT_ENGAGED,
        )

        after = fixtures.read_expert(api, expert["id"])
        assert after["expert_status"] == types.ExpertStatus.DISQUALIFIED.value
        assert after["safest_available_opinion"] is None
        assert after["opinion_issued_at"] is None
        assert after["version"] == 2

    def test_lifecycle_disqualified_expert_cannot_be_reviewed_a_second_time(
        self, api: PrtApiClient, fiduciary: Dict[str, str]
    ) -> None:
        """A second independence review of a disqualified engagement fails on its own state, not its conflict.

        Either decision requires the engagement to be in `INDEPENDENCE_REVIEW`, otherwise `ERR_EXPERT_STATE_INVALID`, and requires the reviewing `X-User-ID` to differ from `proposed_by_user_id`, otherwise `ERR_SEGREGATION_OF_DUTIES`.
        The families below are evaluated in the order listed; the first family that finds a violation decides the response, and later families are not consulted.
        **Own-state precondition** — the target resource's own status field permits the requested transition, else the entity-specific conflict error: `ERR_PLAN_STATE_INVALID`, `ERR_STRATEGY_STATE_INVALID`, `ERR_PARTICIPANT_STATE_INVALID`, `ERR_AUDIT_STATE_INVALID`, `ERR_WINDOW_STATE_INVALID`, `ERR_ELECTION_STATE_INVALID`, `ERR_TRANCHE_STATE_INVALID`, `ERR_QUOTE_STATE_INVALID`, `ERR_EXPERT_STATE_INVALID`, `ERR_TRANSFER_STATE_INVALID`, or `ERR_COMPLAINT_STATE_INVALID`, all HTTP 409. Applies to every state-transition endpoint.
        **Disclosed conflict** — `ERR_EXPERT_CONFLICT_DISCLOSED`, on `POST /prt/independent-experts/{id}/independence-review`.

        Design: Corner/state_machines/disqualified_expert_is_terminal_and_can_neither_opine_nor_be_re_reviewed
        """
        plan = fixtures.create_plan(api)
        expert = fixtures.create_expert(
            api, plan["id"], "Marlowe Actuarial Advisors", conflict_disclosed=True
        )
        fixtures.review_expert(api, expert["id"], types.ExpertReviewDecision.DISQUALIFY.value)

        validate_error(
            api.post_independence_review(
                expert["id"],
                factories.expert_review_payload(types.ExpertReviewDecision.ENGAGE.value),
                fiduciary,
            ),
            api_errors.ERR_EXPERT_STATE_INVALID,
        )

        _rows, meta = validate_paginated(
            api.list_experts(
                plan["id"], fiduciary, {"expert_status": types.ExpertStatus.ENGAGED.value}
            )
        )
        assert meta["total_count"] == 0
        after = fixtures.read_expert(api, expert["id"])
        assert after["expert_status"] == types.ExpertStatus.DISQUALIFIED.value
        assert after["version"] == 2


# ---------------------------------------------------------------------------
# Benefit audits and the corrected ledger
# ---------------------------------------------------------------------------


class TestBenefitAuditCorrection:
    """A second audit supersedes the first, and its correction reaches the ledger."""

    def test_lifecycle_second_audit_supersedes_the_first_and_forks_to_correction_required(
        self, api: PrtApiClient
    ) -> None:
        """Opening a second audit supersedes the closed one and forks to CORRECTION_REQUIRED on the variance.

        Before the new audit exists, every non-superseded audit of that participant transitions to `SUPERSEDED`, each bumping its own `version`; this create-with-supersede pattern is exactly what the stale-participant guard protects.
        The `recomputed_monthly_benefit_cents` is then the `final_average_monthly_earnings_cents` multiplied by an accrual rate of 150 basis points and by the capped service months, with that product rounded half up over 120,000 — the divisor being 10,000 basis points times the twelve months of a year, because the accrual rate is expressed per year of service while the result is a monthly benefit.
        The `variance_cents` is the participant's `stated_monthly_benefit_cents` minus the `recomputed_monthly_benefit_cents`, and may be negative when the sponsor was understating the benefit.
        When the absolute value of `variance_cents` exceeds 500 cents, the audit lands in `CORRECTION_REQUIRED` instead, the participant's `benefit_audit_status` is set to `CORRECTION_REQUIRED`, `data_confidence_score` and `data_status` are recomputed, and — the branch-specific extra hop — if the participant is assigned to a tranche whose `tranche_status` is `DRAFT`, `QUOTING`, or `INSURER_SELECTED`, that tranche's `data_readiness_flag` is set to `BLOCKED`.
        Two endpoints declare their own ordering: the benefit-audit history of a participant is ordered by `audit_sequence` ascending, and the asset-transfer history of a tranche is ordered by `created_at` ascending.

        Design: Corner/state_machines/applied_correction_syncs_the_audited_benefit_into_the_participant_ledger
        """
        plan = fixtures.create_plan(api)
        participant = _clean_deferred(api, plan["id"], 100000, 250000, 320)
        assert participant["audited_monthly_benefit_cents"] == 100000
        assert participant["accounting_liability_cents"] == 11460000
        first_audit = fixtures.latest_audit(api, participant["id"])
        assert first_audit["audit_sequence"] == 1
        assert first_audit["variance_cents"] == 0

        second_audit = fixtures.open_benefit_audit(
            api,
            participant["id"],
            audit_basis=types.AuditBasis.COLLECTIVE_AGREEMENT.value,
            credited_service_months=360,
        )
        assert second_audit["audit_sequence"] == 2
        assert second_audit["recomputed_monthly_benefit_cents"] == 112500
        assert second_audit["variance_cents"] == -12500
        assert second_audit["audit_status"] == types.BenefitAuditStatus.CORRECTION_REQUIRED.value

        mirrored = fixtures.read_participant(api, participant["id"])
        assert (
            mirrored["benefit_audit_status"]
            == types.ParticipantAuditStatus.CORRECTION_REQUIRED.value
        )
        assert mirrored["data_confidence_score"] == 85
        assert mirrored["data_status"] == types.DataStatus.CLEAN.value

        history = fixtures.list_benefit_audits(api, participant["id"])
        assert [row["audit_sequence"] for row in history] == [1, 2]
        assert history[0]["audit_status"] == types.BenefitAuditStatus.SUPERSEDED.value

    def test_lifecycle_applied_correction_syncs_the_participant_ledger(
        self, api: PrtApiClient
    ) -> None:
        """Applying the correction rewrites the audited benefit and the derived accounting liability.

        Applying the correction to an audit in `CORRECTION_REQUIRED` moves it `CORRECTION_REQUIRED → CORRECTED`: the participant's `audited_monthly_benefit_cents` is set to the audit's `recomputed_monthly_benefit_cents`, `benefit_audit_status` becomes `CORRECTED`, both liability figures and the confidence fields are recomputed, and — when the participant is assigned to a tranche in `DRAFT`, `QUOTING`, or `INSURER_SELECTED` — that tranche's `accounting_liability_cents`, `settlement_liability_cents`, and `data_readiness_flag` are recomputed too.
        Otherwise the effective monthly amount is multiplied by twelve, the annual amount is multiplied by the factor for the participant's `cohort`, and the product is rounded half up over 10,000.
        For `accounting_liability_cents` the factor is 118,000 basis points for `RETIREE_IN_PAY` and 95,500 for `DEFERRED_VESTED`; for `settlement_liability_cents` it is 126,250 for `RETIREE_IN_PAY` and 104,500 for `DEFERRED_VESTED`.
        A `benefit_audit_status` of `NOT_AUDITED`, `AUDIT_OPEN`, `CORRECTION_REQUIRED`, or `REOPENED` costs 15 points.
        The score is floored at 0, and `data_status` is `CLEAN` when the score is at least 80 and `NEEDS_REVIEW` otherwise.

        Design: Corner/state_machines/applied_correction_syncs_the_audited_benefit_into_the_participant_ledger
        """
        plan = fixtures.create_plan(api)
        participant = _clean_deferred(api, plan["id"], 100000, 250000, 320)
        second_audit = fixtures.open_benefit_audit(
            api,
            participant["id"],
            audit_basis=types.AuditBasis.COLLECTIVE_AGREEMENT.value,
            credited_service_months=360,
        )

        corrected = fixtures.resolve_audit(
            api, second_audit["id"], types.AuditResolution.APPLY_CORRECTION.value
        )
        assert corrected["audit_status"] == types.BenefitAuditStatus.CORRECTED.value

        synced = fixtures.read_participant(api, participant["id"])
        assert synced["audited_monthly_benefit_cents"] == 112500
        assert synced["accounting_liability_cents"] == 12892500
        assert synced["benefit_audit_status"] == types.ParticipantAuditStatus.CORRECTED.value
        assert synced["data_confidence_score"] == 100
        assert synced["data_status"] == types.DataStatus.CLEAN.value


# ---------------------------------------------------------------------------
# Funding a locked tranche
# ---------------------------------------------------------------------------


class TestAssetTransferRetry:
    """Funding is retryable, and only an acceptance may move the tranche."""

    def test_lifecycle_rejected_transfer_leaves_the_tranche_priced_and_locked(
        self, api: PrtApiClient
    ) -> None:
        """A carrier rejection ends that delivery, leaves the tranche locked, and cannot be re-answered.

        An in-kind delivery suffers two frictions: a valuation haircut of 125 basis points applied to `gross_value_cents` and rounded half up over 10,000, plus a per-lot custody fee of 25,000 cents for each security lot delivered.
        In both modes `credited_value_cents` is `gross_value_cents` minus `transfer_expense_cents`, and `shortfall_cents` is the amount by which the tranche's `locked_premium_cents` exceeds `credited_value_cents`, or 0 when the credited value reaches or passes the premium.
        A `REJECT` moves the delivery `INITIATED → REJECTED`, requires a non-empty `rejection_reason` whose absence is rejected with `ERR_INVALID_REQUEST`, records that reason, and bumps only the delivery's `version` — the tranche stays in `PRICING_LOCKED`, consumes no additional capacity, and the sponsor may initiate a replacement delivery against the same lock.
        A drafted tranche starts in `DRAFT` with `data_readiness_flag` `BLOCKED`, `assigned_participant_count` 0, both `accounting_liability_cents` and `settlement_liability_cents` 0, `transfer_expense_cents` 0, and `selection_basis`, `selected_quote_id`, `selected_insurer_id`, `selection_score_bp`, `locked_premium_cents`, `lock_start_at`, `lock_expires_at`, `settlement_gain_loss_cents`, `settled_at`, `abandoned_at`, and `abandonment_reason` all null.
        Here too the status error is split: a delivery that has already been answered, being `SETTLED` or `REJECTED`, yields `ERR_TRANSFER_NOT_INITIATED`, while a delivery that was `SUPERSEDED` by a later delivery on the same tranche yields `ERR_TRANSFER_STATE_INVALID`.

        Design: Corner/state_machines/rejected_transfer_leaves_the_tranche_locked_and_a_later_transfer_supersedes
        """
        insurer, tranche = _locked_buyout_tranche(api)
        assert tranche["tranche_status"] == types.TrancheStatus.PRICING_LOCKED.value
        assert tranche["locked_premium_cents"] == 11800000

        delivery = fixtures.initiate_in_kind_transfer(
            api, tranche["id"], 12000000, 2, tranche["version"]
        )
        assert delivery["transfer_status"] == types.TransferStatus.INITIATED.value
        assert delivery["transfer_expense_cents"] == 200000
        assert delivery["credited_value_cents"] == 11800000
        assert delivery["shortfall_cents"] == 0

        rejected = fixtures.review_transfer(
            api,
            delivery["id"],
            insurer["id"],
            types.InsurerDecision.REJECT.value,
            rejection_reason="Two of the delivered lots are not on our admitted-asset list.",
        )
        assert rejected["transfer_status"] == types.TransferStatus.REJECTED.value

        still_locked = fixtures.read_tranche(api, tranche["id"])
        assert still_locked["tranche_status"] == types.TrancheStatus.PRICING_LOCKED.value
        assert still_locked["transfer_expense_cents"] == 0

        validate_error(
            api.post_insurer_review(
                delivery["id"],
                factories.insurer_review_payload(types.InsurerDecision.ACCEPT.value),
                make_insurer_rep_headers(insurer["id"]),
            ),
            api_errors.ERR_TRANSFER_NOT_INITIATED,
        )
        history = fixtures.list_asset_transfers(api, tranche["id"])
        assert [row["transfer_status"] for row in history] == [
            types.TransferStatus.REJECTED.value
        ]

    def test_lifecycle_later_transfer_supersedes_only_the_awaiting_delivery(
        self, api: PrtApiClient
    ) -> None:
        """A replacement delivery supersedes only the one still awaiting an answer, and its acceptance moves the tranche.

        Any delivery still awaiting the carrier's answer on the same tranche transitions `INITIATED → SUPERSEDED` before the new one is created, bumping its own `version`.
        A cash delivery suffers only a wire fee of 8 basis points applied to `gross_value_cents` and rounded half up over 10,000, and its `transfer_expense_cents` is that wire fee alone — no haircut, no per-lot component.
        In both modes `credited_value_cents` is `gross_value_cents` minus `transfer_expense_cents`, and `shortfall_cents` is the amount by which the tranche's `locked_premium_cents` exceeds `credited_value_cents`, or 0 when the credited value reaches or passes the premium.
        An `ACCEPT` moves the delivery `INITIATED → SETTLED`, stamps `settled_at` from the logical clock, and cascades: the tranche transitions `PRICING_LOCKED → ASSETS_TRANSFERRED` and copies this delivery's `transfer_expense_cents` onto its own `transfer_expense_cents`, bumping the tranche's `version` as well as the delivery's.
        Two endpoints declare their own ordering: the benefit-audit history of a participant is ordered by `audit_sequence` ascending, and the asset-transfer history of a tranche is ordered by `created_at` ascending.

        Design: Corner/state_machines/rejected_transfer_leaves_the_tranche_locked_and_a_later_transfer_supersedes
        """
        insurer, tranche = _locked_buyout_tranche(api)
        first = fixtures.initiate_in_kind_transfer(
            api, tranche["id"], 12000000, 2, tranche["version"]
        )
        fixtures.review_transfer(
            api,
            first["id"],
            insurer["id"],
            types.InsurerDecision.REJECT.value,
            rejection_reason="Two of the delivered lots are not on our admitted-asset list.",
        )

        second = fixtures.initiate_cash_transfer(api, tranche["id"], 12000000)
        third = fixtures.initiate_cash_transfer(api, tranche["id"], 12000000)
        assert third["transfer_expense_cents"] == 9600
        assert third["credited_value_cents"] == 11990400
        assert third["shortfall_cents"] == 0

        by_id = {row["id"]: row for row in fixtures.list_asset_transfers(api, tranche["id"])}
        assert by_id[first["id"]]["transfer_status"] == types.TransferStatus.REJECTED.value
        assert by_id[second["id"]]["transfer_status"] == types.TransferStatus.SUPERSEDED.value
        assert by_id[third["id"]]["transfer_status"] == types.TransferStatus.INITIATED.value
        assert (
            fixtures.read_tranche(api, tranche["id"])["tranche_status"]
            == types.TrancheStatus.PRICING_LOCKED.value
        )

        settled = fixtures.review_transfer(
            api, third["id"], insurer["id"], types.InsurerDecision.ACCEPT.value
        )
        assert settled["transfer_status"] == types.TransferStatus.SETTLED.value
        transferred = fixtures.read_tranche(api, tranche["id"])
        assert transferred["tranche_status"] == types.TrancheStatus.ASSETS_TRANSFERRED.value
        assert transferred["transfer_expense_cents"] == 9600

        assert [
            row["transfer_status"] for row in fixtures.list_asset_transfers(api, tranche["id"])
        ] == [
            types.TransferStatus.REJECTED.value,
            types.TransferStatus.SUPERSEDED.value,
            types.TransferStatus.SETTLED.value,
        ]


# ---------------------------------------------------------------------------
# The termination filing loop
# ---------------------------------------------------------------------------


class TestTerminationFilingLoop:
    """A deficient filing may be cured, and then the plan shuts for good."""

    def test_lifecycle_refiling_without_a_deficiency_response_is_refused(
        self, api: PrtApiClient, sponsor: Dict[str, str]
    ) -> None:
        """The payload that filed from RESIDUAL is refused from FILING_DEFICIENT, which the plan stays in.

        Filing moves the plan to `TERMINATION_FILED`, stores `filing_reference`, stamps `filing_submitted_at` from the logical clock, clears any `filing_deficiency_reason`, and bumps the `version`.
        A `RETURN_DEFICIENT` moves the plan `TERMINATION_FILED → FILING_DEFICIENT` and requires a non-empty `filing_deficiency_reason` in the payload, whose absence is rejected with `ERR_INVALID_REQUEST`; it stores that reason and bumps the `version`.
        The sponsor may then re-file from `FILING_DEFICIENT` back to `TERMINATION_FILED` any number of times, but a re-filing must carry a non-empty `deficiency_response` explaining how the deficiency was cured — its absence is rejected with `ERR_INVALID_REQUEST` — and the same zero-outstanding-complaints requirement applies.

        Design: Corner/state_machines/deficient_termination_filing_can_be_cured_then_the_plan_locks_down
        """
        plan, _paid, _remaining = _residual_plan(api)
        assert plan["plan_status"] == types.PlanStatus.RESIDUAL.value
        assert plan["total_liability_cents"] == 97708000
        assert plan["plan_assets_cents"] == 117600000

        filed = fixtures.submit_termination_filing(
            api, plan["id"], filing_reference="PBGC-500-2026-0001"
        )
        assert filed["plan_status"] == types.PlanStatus.TERMINATION_FILED.value
        assert filed["filing_reference"] == "PBGC-500-2026-0001"

        deficient = fixtures.review_filing(
            api,
            plan["id"],
            review_decision=types.FilingReviewDecision.RETURN_DEFICIENT.value,
            filing_deficiency_reason="Schedule of residual participants omitted.",
        )
        assert deficient["plan_status"] == types.PlanStatus.FILING_DEFICIENT.value
        assert (
            deficient["filing_deficiency_reason"]
            == "Schedule of residual participants omitted."
        )

        validate_error(
            api.post_termination_filing(
                plan["id"], {"filing_reference": "PBGC-500-2026-0002"}, sponsor
            ),
            api_errors.ERR_INVALID_REQUEST,
        )
        assert (
            fixtures.read_plan(api, plan["id"])["plan_status"]
            == types.PlanStatus.FILING_DEFICIENT.value
        )

    def test_lifecycle_cured_refiling_is_approved_and_annuitizes_the_residual_participant(
        self, api: PrtApiClient
    ) -> None:
        """A cured re-filing is accepted and its approval terminates the plan, annuitizing whoever stayed.

        The sponsor may then re-file from `FILING_DEFICIENT` back to `TERMINATION_FILED` any number of times, but a re-filing must carry a non-empty `deficiency_response` explaining how the deficiency was cured — its absence is rejected with `ERR_INVALID_REQUEST` — and the same zero-outstanding-complaints requirement applies.
        An `APPROVE` moves the plan `TERMINATION_FILED → TERMINATED`, its only terminal status, and is gated on solvency: the plan's `accounting_funded_status_bp` must be at least 10000, meaning assets at least equal the accounting liability, otherwise the approval is rejected with `ERR_PLAN_ASSETS_INSUFFICIENT`.
        Its accounting figure, `accounting_funded_status_bp`, is 0 whenever `total_liability_cents` is 0; otherwise it is `plan_assets_cents` multiplied by 10,000 and rounded half up over `total_liability_cents`, so a fully funded plan reads 10000 basis points.
        Every participant of the plan still in `IN_PLAN` transitions to `RESIDUAL_ANNUITY_PURCHASED` — the residual annuity contract that closes out the plan.
        And one settlement accounting entry is appended with an `entry_type` of `PLAN_TERMINATION`, an `amount_cents` of 0, and a `pbo_settled_cents` equal to the plan's `participant_liability_total_cents` measured **before** the participant cascade ran.
        Its `deferred_amount_cents`, defaulting to 0, is the charge held in accumulated other comprehensive income because the recognition threshold was not exceeded, and sums into the plan's `deferred_settlement_charge_cents`.

        Design: Corner/state_machines/deficient_termination_filing_can_be_cured_then_the_plan_locks_down
        """
        plan, paid, remaining = _residual_plan(api)
        assert plan["accounting_funded_status_bp"] == 12036

        fixtures.submit_termination_filing(
            api, plan["id"], filing_reference="PBGC-500-2026-0001"
        )
        fixtures.review_filing(
            api,
            plan["id"],
            review_decision=types.FilingReviewDecision.RETURN_DEFICIENT.value,
            filing_deficiency_reason="Schedule of residual participants omitted.",
        )

        refiled = fixtures.submit_termination_filing(
            api,
            plan["id"],
            filing_reference="PBGC-500-2026-0002",
            deficiency_response=(
                "Residual schedule attached; one deferred vested participant remains."
            ),
        )
        assert refiled["plan_status"] == types.PlanStatus.TERMINATION_FILED.value

        terminated = fixtures.review_filing(
            api, plan["id"], review_decision=types.FilingReviewDecision.APPROVE.value
        )
        assert terminated["plan_status"] == types.PlanStatus.TERMINATED.value
        assert terminated["terminated_at"] == WINDOW_CLOSES_AT

        assert (
            fixtures.read_participant(api, remaining["id"])["participant_status"]
            == types.ParticipantStatus.RESIDUAL_ANNUITY_PURCHASED.value
        )
        assert (
            fixtures.read_participant(api, paid["id"])["participant_status"]
            == types.ParticipantStatus.SETTLED_LUMP_SUM.value
        )

        entries = fixtures.list_settlement_entries(
            api,
            plan_id=plan["id"],
            entry_type=types.SettlementEntryType.PLAN_TERMINATION.value,
        )
        assert len(entries) == 1
        assert entries[0]["amount_cents"] == 0
        assert entries[0]["deferred_amount_cents"] == 0
        assert entries[0]["window_id"] is None
        assert entries[0]["tranche_id"] is None

    def test_lifecycle_terminated_plan_admits_no_further_filing(
        self, api: PrtApiClient, sponsor: Dict[str, str]
    ) -> None:
        """Once terminated the plan refuses another termination filing on its own state.

        An `APPROVE` moves the plan `TERMINATION_FILED → TERMINATED`, its only terminal status, and is gated on solvency: the plan's `accounting_funded_status_bp` must be at least 10000, meaning assets at least equal the accounting liability, otherwise the approval is rejected with `ERR_PLAN_ASSETS_INSUFFICIENT`.
        The plan must be in `RESIDUAL` or `FILING_DEFICIENT`, and the count of the plan's participant complaints whose `complaint_status` is `OPEN` or `TRIAGED` must be exactly 0; any outstanding complaint is rejected with `ERR_COMPLAINT_STATE_INVALID`.
        **Own-state precondition** — the target resource's own status field permits the requested transition, else the entity-specific conflict error: `ERR_PLAN_STATE_INVALID`, `ERR_STRATEGY_STATE_INVALID`, `ERR_PARTICIPANT_STATE_INVALID`, `ERR_AUDIT_STATE_INVALID`, `ERR_WINDOW_STATE_INVALID`, `ERR_ELECTION_STATE_INVALID`, `ERR_TRANCHE_STATE_INVALID`, `ERR_QUOTE_STATE_INVALID`, `ERR_EXPERT_STATE_INVALID`, `ERR_TRANSFER_STATE_INVALID`, or `ERR_COMPLAINT_STATE_INVALID`, all HTTP 409. Applies to every state-transition endpoint.

        Design: Corner/state_machines/deficient_termination_filing_can_be_cured_then_the_plan_locks_down
        """
        plan, _paid, _remaining = _residual_plan(api)
        fixtures.submit_termination_filing(
            api, plan["id"], filing_reference="PBGC-500-2026-0001"
        )
        terminated = fixtures.review_filing(
            api, plan["id"], review_decision=types.FilingReviewDecision.APPROVE.value
        )
        assert terminated["plan_status"] == types.PlanStatus.TERMINATED.value

        validate_error(
            api.post_termination_filing(
                plan["id"], {"filing_reference": "PBGC-500-2026-0003"}, sponsor
            ),
            api_errors.ERR_PLAN_STATE_INVALID,
        )
        assert (
            fixtures.read_plan(api, plan["id"])["plan_status"]
            == types.PlanStatus.TERMINATED.value
        )
