"""State machines that are not a single forward line.

Three shapes are exercised here: the renewal forecast, whose CS and finance axes
advance independently on the same row; the escalation case, whose
`COMMITTED → DISPUTED → COMMITTED` negotiation loop counts its traversals in
`remediation_round`; and the coverage assignment, whose identical creation call
lands in `QUEUED` and then forks into two branches with disjoint side effects.
"""

from typing import Optional, Tuple

from test_helpers import (
    ASSIGNMENT_COMMITTED,
    ASSIGNMENT_PREEMPTED,
    ASSIGNMENT_QUEUED,
    CASE_ACTION_COMMIT,
    CASE_COMMITTED,
    CASE_DISPUTED,
    CODE_KICKOFF,
    COMMITMENT_ACTION_ACCEPT,
    COMMITMENT_ACCEPTED,
    COMMITMENT_BREACHED,
    CS_STATE_DRAFT,
    CS_STATE_LOCKED,
    CS_STATE_SUBMITTED,
    EXECUTIVE_HEADERS,
    FINANCE_STATE_PENDING,
    FINANCE_STATE_RECONCILED,
    FINANCE_STATE_VARIANCE_FLAGGED,
    LIKELIHOOD_UPSIDE,
    MILESTONE_ACTION_WAIVE,
    NEWEST_USAGE_ROW,
    NORTHWIND,
    OPS_ADMIN_HEADERS,
    PLAY_ACTION_ACTIVATE,
    PLAY_TYPE_TECHNICAL_REMEDIATION,
    POSTURE_OPEN,
    POSTURE_RESTRICTED,
    RECONCILE_ACTION_LOCK,
    RECONCILE_ACTION_RECONCILE,
    RISING_USAGE_ROWS,
    RISK_SUPPORT_ESCALATION,
    SEGMENT_MIDMARKET,
    SEVERITY_HIGH,
    TIER_HIGH_TOUCH,
    ApiClient,
    ApiErrorId,
    add_sponsor,
    add_usage_signal,
    assert_capacity_conserved,
    assert_cents,
    assert_credit_ledger,
    assert_field,
    assert_fields,
    assert_null,
    assert_sweep_counts,
    assign_coverage,
    build_submitted_forecast,
    create_account,
    create_csm,
    data_of,
    draft_save_play,
    factories,
    make_csm_headers,
    propose_commitment,
    raise_escalation,
    read_account,
    read_assignment,
    read_case,
    read_commitment,
    read_csm,
    read_forecast,
    reconcile_forecast,
    run_sweep,
    segment_account,
    set_clock,
    submit_forecast,
    transition_commitment,
    transition_escalation,
    transition_save_play,
    validate_error,
)

# ---------------------------------------------------------------------------
# Local composition helpers
# ---------------------------------------------------------------------------

# A second account on the same manager, commercially identical to Northwind but
# banded MIDMARKET so that its weighted coverage cost differs.
CONTOSO = {
    "name": "Contoso Retail",
    "arr_cents": 30_000_000,
    "segment_band": SEGMENT_MIDMARKET,
    "contract_start_date": "2026-01-01",
    "contract_end_date": "2026-12-31",
}


def _waive_kickoff(api: ApiClient, account_id: str) -> None:
    """Add a single KICKOFF milestone and waive it, leaving onboarding behind.

    Waiving the only milestone satisfies the account's `ONBOARDING → ADOPTING`
    condition, which is what keeps the time-to-value comparison of PRD §3.1 from
    firing once the clock is moved forward.
    """
    milestone = data_of(
        api.create_milestone(
            account_id,
            factories.milestone(1, "2026-08-15", CODE_KICKOFF),
            OPS_ADMIN_HEADERS,
        )
    )
    data_of(
        api.transition_milestone(
            milestone["id"],
            factories.milestone_transition(MILESTONE_ACTION_WAIVE),
            OPS_ADMIN_HEADERS,
        )
    )


def _build_committed_case(
    api: ApiClient, extra_commitment: Optional[Tuple[int, str]] = None
) -> dict:
    """An ADOPTING account whose escalation case rests in COMMITTED at round 1.

    The save play is activated while the account is still AMBER on the point-in
    time figure; the CXO economic buyer is registered afterwards, both because
    the commit edge demands executive cover and because the buyer debit is what
    lifts the stored scores to 77.60 and 70.95.

    `extra_commitment` adds a second credit — a `credit_cents` and `due_date`
    pair — accepted in the same round as the first. Acceptance requires the case
    to be `OPEN` or `DISPUTED`, so both are accepted before the case is
    committed.
    """
    csm = create_csm(
        api, coverage_specialty=TIER_HIGH_TOUCH, capacity_units_total=17
    )
    account = create_account(api, **NORTHWIND)
    for row in RISING_USAGE_ROWS:
        add_usage_signal(
            api,
            account["id"],
            csm["id"],
            row["period_end_date"],
            row["weekly_active_users"],
            row["licensed_seats"],
            row["feature_depth_pct"],
        )
    _waive_kickoff(api, account["id"])
    play = draft_save_play(
        api,
        account["id"],
        csm["id"],
        "2026-08-01",
        "2026-10-31",
        risk_code=RISK_SUPPORT_ESCALATION,
        play_type=PLAY_TYPE_TECHNICAL_REMEDIATION,
    )
    transition_save_play(api, play["id"], csm["id"], PLAY_ACTION_ACTIVATE)
    add_sponsor(api, account["id"], csm["id"])
    case = raise_escalation(api, account["id"], play["id"], SEVERITY_HIGH)
    first = propose_commitment(
        api, case["id"], 600_000, "2026-09-15", read_case(api, case["id"])["version"]
    )
    transition_commitment(api, first["id"], COMMITMENT_ACTION_ACCEPT)
    extra_id = None
    if extra_commitment is not None:
        credit_cents, due_date = extra_commitment
        extra = propose_commitment(
            api,
            case["id"],
            credit_cents,
            due_date,
            read_case(api, case["id"])["version"],
        )
        transition_commitment(api, extra["id"], COMMITMENT_ACTION_ACCEPT)
        extra_id = extra["id"]
    case = transition_escalation(api, case["id"], CASE_ACTION_COMMIT)
    return {
        "csm_id": csm["id"],
        "account_id": account["id"],
        "play_id": play["id"],
        "case_id": case["id"],
        "first_commitment_id": first["id"],
        "extra_commitment_id": extra_id,
    }


def _build_saturated_manager(api: ApiClient) -> dict:
    """One 17-unit manager fully committed to account A, with account B waiting.

    Account A is ENTERPRISE and prices at 17 weighted units, exactly filling the
    roster; account B is MIDMARKET and prices at 12, which cannot fit, so its
    assignment is left waiting.
    """
    csm = create_csm(
        api, coverage_specialty=TIER_HIGH_TOUCH, capacity_units_total=17
    )
    account_a = create_account(api, **NORTHWIND)
    account_b = create_account(api, **CONTOSO)
    for account in (account_a, account_b):
        add_usage_signal(
            api,
            account["id"],
            csm["id"],
            NEWEST_USAGE_ROW["period_end_date"],
            NEWEST_USAGE_ROW["weekly_active_users"],
            NEWEST_USAGE_ROW["licensed_seats"],
            NEWEST_USAGE_ROW["feature_depth_pct"],
        )
    segmented_a = segment_account(api, account_a["id"])
    assignment_a = assign_coverage(
        api, account_a["id"], segmented_a["version"], csm_id=csm["id"]
    )
    segmented_b = segment_account(api, account_b["id"])
    assignment_b = assign_coverage(
        api, account_b["id"], segmented_b["version"], csm_id=csm["id"]
    )
    return {
        "csm_id": csm["id"],
        "account_a_id": account_a["id"],
        "account_b_id": account_b["id"],
        "assignment_a_id": assignment_a["id"],
        "assignment_b_id": assignment_b["id"],
    }


class TestRenewalForecastParallelAxes:
    """The CS and finance axes of one forecast row move under separate owners."""

    def test_finance_reconcile_flags_variance_and_leaves_the_cs_axis_submitted(
        self, api: ApiClient, clock: str
    ) -> None:
        """Reconciling a submitted forecast flags the gap without moving `cs_state`.

        PRD §3.6: "When `cs_amount_cents` is omitted it is computed bottom up as the CS organisation's own number: the account's `arr_cents` multiplied by the likelihood weight for the snapshotted `likelihood_category` — 0.95 for `COMMIT`, 0.70 for `UPSIDE`, 0.35 for `AT_RISK` and 0.00 for `OMIT` — rounded half up to whole cents."
        PRD §3.6: "Finance's number is derived quite differently, top down from a flat segment retention rate that ignores account-level health entirely: `arr_cents` multiplied by 0.90 for `ENTERPRISE`, 0.80 for `MIDMARKET` or 0.65 for `SMB`, again rounded half up to whole cents."
        PRD §3.2: "An account with a `trended_health_score` of 67.20, no open plays and 152 days remaining is `UPSIDE`; the same account with exactly 60 days remaining is `AT_RISK`; a `trended_health_score` of 43.75 is `AT_RISK` on score alone."
        PRD §3.6: "It establishes `finance_amount_cents` from the request, or from the top-down segment method when the field is omitted, sets `variance_cents` to `finance_amount_cents` minus `cs_amount_cents` — keeping its sign, so an under-call by finance is negative — and stamps `reconciled_at` with the logical clock."
        PRD §3.6: "The variance is then judged against a tolerance of 500 basis points of the CS number, tested purely in integers by cross-multiplication so that no division or floating point is involved: when the absolute value of `variance_cents` multiplied by 10,000 is **strictly greater** than 500 multiplied by `cs_amount_cents`, `finance_state` becomes `VARIANCE_FLAGGED`; otherwise it becomes `RECONCILED`."
        PRD §3.6: "Note the shape this leaves in between: a row may legitimately rest at `cs_state` `SUBMITTED` with `finance_state` `VARIANCE_FLAGGED` indefinitely, because the finance axis cannot force the CS axis to move."

        Design: Difficulty/non_linear_state_machine/renewal_forecast_cs_and_finance_axes_advance_independently
        """
        state = build_submitted_forecast(api, fiscal_period="2026Q4")
        submitted = state["forecast"]
        assert_field(submitted, "likelihood_category", LIKELIHOOD_UPSIDE)
        assert_cents(submitted["cs_amount_cents"], 21_000_000, "cs_amount_cents")
        assert_fields(
            submitted,
            {"cs_state": CS_STATE_SUBMITTED, "finance_state": FINANCE_STATE_PENDING},
        )

        reconciled = reconcile_forecast(
            api, state["forecast_id"], RECONCILE_ACTION_RECONCILE
        )

        assert_cents(
            reconciled["finance_amount_cents"], 27_000_000, "finance_amount_cents"
        )
        assert_cents(reconciled["variance_cents"], 6_000_000, "variance_cents")
        assert_fields(
            reconciled,
            {
                "finance_state": FINANCE_STATE_VARIANCE_FLAGGED,
                "cs_state": CS_STATE_SUBMITTED,
            },
        )
        assert reconciled["reconciled_at"] is not None, "reconciled_at is not stamped"
        assert reconciled["submitted_at"] is not None, "submitted_at was cleared"

    def test_cs_revision_edge_returns_to_draft_and_resets_the_finance_axis(
        self, api: ApiClient, clock: str
    ) -> None:
        """A submit against a flagged row walks both axes backwards.

        PRD §3.6: "Submitting a forecast that is already `SUBMITTED` while its `finance_state` is `VARIANCE_FLAGGED` takes the revision edge: `cs_state` returns to `DRAFT`, `cs_amount_cents` is recomputed by the bottom-up method **using the account's current `renewal_likelihood`** rather than the stale `likelihood_category`, and the finance axis is reset to `PENDING` with both `variance_cents` and `finance_amount_cents` cleared to null."

        Design: Difficulty/non_linear_state_machine/renewal_forecast_cs_and_finance_axes_advance_independently
        """
        state = build_submitted_forecast(api, fiscal_period="2026Q4")
        reconcile_forecast(api, state["forecast_id"], RECONCILE_ACTION_RECONCILE)

        revised = submit_forecast(api, state["forecast_id"], state["csm_id"])

        assert_fields(
            revised,
            {"cs_state": CS_STATE_DRAFT, "finance_state": FINANCE_STATE_PENDING},
        )
        assert_null(revised, "variance_cents", "finance_amount_cents")
        assert_cents(revised["cs_amount_cents"], 21_000_000, "cs_amount_cents")

    def test_the_axes_reach_the_terminal_pair_one_after_the_other(
        self, api: ApiClient, clock: str
    ) -> None:
        """A variance of exactly the tolerance reconciles, and only then may the row lock.

        PRD §3.6: "The variance is then judged against a tolerance of 500 basis points of the CS number, tested purely in integers by cross-multiplication so that no division or floating point is involved: when the absolute value of `variance_cents` multiplied by 10,000 is **strictly greater** than 500 multiplied by `cs_amount_cents`, `finance_state` becomes `VARIANCE_FLAGGED`; otherwise it becomes `RECONCILED`."
        PRD §3.6: "Locking carries `cs_state` from `SUBMITTED` to `LOCKED` and is permitted only while `finance_state` is `RECONCILED`; a locked forecast is immutable, and any further submit or reconcile against it is refused with `ERR_INVALID_STATE_TRANSITION`."

        Design: Difficulty/non_linear_state_machine/renewal_forecast_cs_and_finance_axes_advance_independently
        """
        state = build_submitted_forecast(api, fiscal_period="2026Q4")
        reconcile_forecast(api, state["forecast_id"], RECONCILE_ACTION_RECONCILE)
        submit_forecast(api, state["forecast_id"], state["csm_id"])

        resubmitted = submit_forecast(api, state["forecast_id"], state["csm_id"])
        assert_fields(
            resubmitted,
            {"cs_state": CS_STATE_SUBMITTED, "finance_state": FINANCE_STATE_PENDING},
        )

        reconciled = reconcile_forecast(
            api,
            state["forecast_id"],
            RECONCILE_ACTION_RECONCILE,
            finance_amount_cents=22_050_000,
        )
        assert_cents(reconciled["variance_cents"], 1_050_000, "variance_cents")
        assert_fields(
            reconciled,
            {
                "finance_state": FINANCE_STATE_RECONCILED,
                "cs_state": CS_STATE_SUBMITTED,
            },
        )

        locked = reconcile_forecast(api, state["forecast_id"], RECONCILE_ACTION_LOCK)
        assert_fields(
            locked,
            {"cs_state": CS_STATE_LOCKED, "finance_state": FINANCE_STATE_RECONCILED},
        )

    def test_a_locked_forecast_refuses_a_further_submit(
        self, api: ApiClient, clock: str
    ) -> None:
        """Once both axes are closed the CS axis has no edge left.

        PRD §3.6: "Locking carries `cs_state` from `SUBMITTED` to `LOCKED` and is permitted only while `finance_state` is `RECONCILED`; a locked forecast is immutable, and any further submit or reconcile against it is refused with `ERR_INVALID_STATE_TRANSITION`."

        Design: Difficulty/non_linear_state_machine/renewal_forecast_cs_and_finance_axes_advance_independently
        """
        state = build_submitted_forecast(api, fiscal_period="2026Q4")
        reconcile_forecast(api, state["forecast_id"], RECONCILE_ACTION_RECONCILE)
        submit_forecast(api, state["forecast_id"], state["csm_id"])
        submit_forecast(api, state["forecast_id"], state["csm_id"])
        reconcile_forecast(
            api,
            state["forecast_id"],
            RECONCILE_ACTION_RECONCILE,
            finance_amount_cents=22_050_000,
        )
        reconcile_forecast(api, state["forecast_id"], RECONCILE_ACTION_LOCK)

        response = api.submit_renewal_forecast(
            state["forecast_id"], make_csm_headers(state["csm_id"])
        )

        validate_error(response, ApiErrorId.INVALID_STATE_TRANSITION, 409)
        still_locked = read_forecast(api, state["forecast_id"])
        assert_fields(
            still_locked,
            {"cs_state": CS_STATE_LOCKED, "finance_state": FINANCE_STATE_RECONCILED},
        )


class TestEscalationNegotiationCycle:
    """A breach drives the case out of COMMITTED and a new round drives it back."""

    def test_breach_disputes_the_case_and_increments_the_round(
        self, api: ApiClient, clock: str
    ) -> None:
        """The outbound leg of the cycle counts one traversal.

        PRD §3.5: "During the nightly sweep, any commitment in state `ACCEPTED` whose `due_date` is strictly earlier than the logical clock date, and whose case is in state `COMMITTED`, breaches — and the breach fans out through four links inside that one sweep."
        PRD §3.5: "Second, because the commitment breached, the owning case moves `COMMITTED → DISPUTED` and its `remediation_round` is incremented by 1 — which is why a fresh commitment must be proposed and accepted before the case can be committed again."
        PRD §3.9: "The sweep returns four counters describing what it did: `milestones_marked_overdue` counts the milestones it moved from `PENDING` to `OVERDUE`; `commitments_breached` counts the commitments it moved from `ACCEPTED` to `BREACHED`; `opportunities_expired` counts the opportunities it moved from `IDENTIFIED` to `EXPIRED`; and `accounts_repostured` counts the accounts whose `coverage_posture` value differs after the sweep from the value it held before, whether the change came from the flag evaluation or from a breach cascade."

        Design: Difficulty/non_linear_state_machine/escalation_case_negotiation_cycle_returns_to_committed_at_round_two
        """
        state = _build_committed_case(api)
        before = read_case(api, state["case_id"])
        assert_fields(before, {"state": CASE_COMMITTED, "remediation_round": 1})

        set_clock(api, "2026-09-20T00:00:00Z")
        sweep = run_sweep(api)

        assert_sweep_counts(sweep, commitments_breached=1)
        breached = read_commitment(
            api, state["case_id"], state["first_commitment_id"]
        )
        assert_field(breached, "state", COMMITMENT_BREACHED)
        disputed = read_case(api, state["case_id"])
        assert_fields(disputed, {"state": CASE_DISPUTED, "remediation_round": 2})

    def test_a_round_two_commitment_closes_the_cycle_back_to_committed(
        self, api: ApiClient, clock: str
    ) -> None:
        """The return leg lands in COMMITTED one round higher, with the ledger reset.

        PRD §3.5: "It carries the case `OPEN → COMMITTED` or, closing the negotiation cycle, `DISPUTED → COMMITTED`."
        PRD §3.5: "The commitment is created in state `PROPOSED` with its `round_index` snapshotted from the case's current `remediation_round`, and it moves no credit counter yet."
        PRD §3.5: "A case may traverse `COMMITTED → DISPUTED → COMMITTED` any number of times, and `remediation_round` counts the traversals."
        PRD §3.5: "First, the commitment moves `ACCEPTED → BREACHED` and the account's `remediation_credit_outstanding_cents` falls by that commitment's `credit_cents`, reversing exactly what acceptance added."
        PRD §3.5: "Acceptance stamps `accepted_by_user_id` with the acting `X-User-ID` and increments the account's `remediation_credit_outstanding_cents` by the commitment's `credit_cents`."

        Design: Difficulty/non_linear_state_machine/escalation_case_negotiation_cycle_returns_to_committed_at_round_two
        """
        state = _build_committed_case(api)
        set_clock(api, "2026-09-20T00:00:00Z")
        run_sweep(api)

        disputed = read_case(api, state["case_id"])
        second = propose_commitment(
            api, state["case_id"], 400_000, "2026-10-31", disputed["version"]
        )
        assert_field(second, "round_index", 2)
        transition_commitment(api, second["id"], COMMITMENT_ACTION_ACCEPT)

        recommitted = transition_escalation(
            api, state["case_id"], CASE_ACTION_COMMIT
        )

        assert_fields(recommitted, {"state": CASE_COMMITTED, "remediation_round": 2})
        account = read_account(api, state["account_id"])
        assert_credit_ledger(account, 400_000, 0)

    def test_a_stale_round_one_commitment_cannot_recommit_round_two(
        self, api: ApiClient, clock: str
    ) -> None:
        """An ACCEPTED commitment from the previous round does not satisfy the commit edge.

        PRD §3.5: "Both edges require executive cover — the account must have a sponsor contact with `is_economic_buyer` true and `status` `ACTIVE`, or the request is refused with `ERR_SPONSOR_DEPARTED` — and at least one commitment of the case in state `ACCEPTED` whose `round_index` equals the case's current `remediation_round`, or the request is refused with `ERR_NO_ACCEPTED_COMMITMENT`."
        PRD §3.5: "The round check is what stops a stale round-one commitment from re-committing round two."

        Design: Difficulty/non_linear_state_machine/escalation_case_negotiation_cycle_returns_to_committed_at_round_two
        """
        state = _build_committed_case(api, extra_commitment=(500_000, "2026-12-31"))

        set_clock(api, "2026-09-20T00:00:00Z")
        run_sweep(api)

        disputed = read_case(api, state["case_id"])
        assert_fields(disputed, {"state": CASE_DISPUTED, "remediation_round": 2})
        still_accepted = read_commitment(
            api, state["case_id"], state["extra_commitment_id"]
        )
        assert_fields(
            still_accepted, {"state": COMMITMENT_ACCEPTED, "round_index": 1}
        )

        response = api.transition_escalation_case(
            state["case_id"],
            factories.escalation_transition(CASE_ACTION_COMMIT),
            EXECUTIVE_HEADERS,
        )

        validate_error(response, ApiErrorId.NO_ACCEPTED_COMMITMENT, 422)
        unchanged = read_case(api, state["case_id"])
        assert_fields(unchanged, {"state": CASE_DISPUTED, "remediation_round": 2})


class TestCoverageAssignmentQueuedFork:
    """One creation call lands in QUEUED, then forks to COMMITTED or PREEMPTED."""

    def test_the_committed_branch_consumes_capacity_and_names_the_manager(
        self, api: ApiClient, clock: str
    ) -> None:
        """Admission is the branch that moves capacity and opens the account.

        PRD §3.4: "Every assignment row is born in state `QUEUED`, and an admission test then runs immediately at the end of the same request."
        PRD §3.4: "The test admits the row to `COMMITTED` when the chosen manager's `status` is `ACTIVE` and their `capacity_units_total` minus `capacity_units_committed` is greater than or equal to the assignment's `load_units`; the comparison is inclusive, so an exact fit is admitted and `capacity_units_available` may legitimately reach exactly 0."
        PRD §3.4: "On admission the manager's `capacity_units_committed` rises by the assignment's `load_units`, `capacity_units_available` is recomputed, the assignment's `committed_at` is stamped with the logical clock, the account's `assigned_csm_id` is set to the assignment's `csm_id`, and `coverage_posture` is re-derived — which is how an otherwise clean account finally reaches `OPEN`."

        Design: Difficulty/non_linear_state_machine/coverage_assignment_queued_fork_has_divergent_branch_side_effects
        """
        state = _build_saturated_manager(api)

        admitted = read_assignment(api, state["assignment_a_id"])

        assert_fields(admitted, {"state": ASSIGNMENT_COMMITTED, "load_units": 17})
        assert admitted["committed_at"] is not None, "committed_at is not stamped"
        manager = read_csm(api, state["csm_id"])
        assert_fields(
            manager, {"capacity_units_committed": 17, "capacity_units_available": 0}
        )
        assert_capacity_conserved(manager)
        account_a = read_account(api, state["account_a_id"])
        assert_fields(
            account_a,
            {
                "assigned_csm_id": state["csm_id"],
                "coverage_posture": POSTURE_OPEN,
            },
        )

    def test_the_queued_branch_moves_no_counter_and_is_not_an_error(
        self, api: ApiClient, clock: str
    ) -> None:
        """An assignment that does not fit simply waits.

        PRD §3.4: "When the capacity does not fit, the row simply **stays** in `QUEUED`; an over-capacity assignment is not an error, and no counter moves."
        PRD §3.4: "Throughout, the account's `assigned_csm_id` names the manager of the account's single `COMMITTED` assignment and is null whenever the account has no `COMMITTED` assignment left, so a preemption clears it only when nothing has taken the preempted row's place."
        PRD §3.4: "Flipping only the health tier to `RED` yields 16.88 plus 2, so 19; flipping only to `GREEN` yields 13.50 plus 2, so 16; flipping only the segment to `MIDMARKET` yields 9.90 plus 2, so 12; flipping only the coverage tier to `LOW_TOUCH` yields 8.25 plus 2, so 11."

        Design: Difficulty/non_linear_state_machine/coverage_assignment_queued_fork_has_divergent_branch_side_effects
        """
        state = _build_saturated_manager(api)

        waiting = read_assignment(api, state["assignment_b_id"])

        assert_fields(waiting, {"state": ASSIGNMENT_QUEUED, "load_units": 12})
        assert_null(waiting, "committed_at")
        manager = read_csm(api, state["csm_id"])
        assert_fields(
            manager, {"capacity_units_committed": 17, "capacity_units_available": 0}
        )
        assert_capacity_conserved(manager)
        account_b = read_account(api, state["account_b_id"])
        assert_fields(
            account_b,
            {"assigned_csm_id": None, "coverage_posture": POSTURE_RESTRICTED},
        )

    def test_the_preempted_branch_stamps_supersession_and_touches_no_capacity(
        self, api: ApiClient, clock: str
    ) -> None:
        """A superseding create pushes the waiting row down the other branch.

        PRD §3.4: "After the new row's admission test has run — so the test is evaluated against the manager's capacity as it stands **before** any supersession frees units — every prior assignment of the same account in state `QUEUED` or `COMMITTED` is driven to `PREEMPTED`, with its `superseded_by_assignment_id` set to the new row's identifier and its `released_at` stamped with the logical clock."
        PRD §3.4: "Preempting a row that was merely `QUEUED` moves no counters."

        Design: Difficulty/non_linear_state_machine/coverage_assignment_queued_fork_has_divergent_branch_side_effects
        """
        state = _build_saturated_manager(api)
        account_b = read_account(api, state["account_b_id"])

        successor = assign_coverage(
            api,
            state["account_b_id"],
            account_b["version"],
            csm_id=state["csm_id"],
        )

        assert_fields(successor, {"state": ASSIGNMENT_QUEUED, "load_units": 12})
        preempted = read_assignment(api, state["assignment_b_id"])
        assert_fields(
            preempted,
            {
                "state": ASSIGNMENT_PREEMPTED,
                "superseded_by_assignment_id": successor["id"],
            },
        )
        assert preempted["released_at"] is not None, "released_at is not stamped"
        manager = read_csm(api, state["csm_id"])
        assert_fields(
            manager, {"capacity_units_committed": 17, "capacity_units_available": 0}
        )
        assert_capacity_conserved(manager)
        refreshed_b = read_account(api, state["account_b_id"])
        assert_fields(
            refreshed_b,
            {"assigned_csm_id": None, "coverage_posture": POSTURE_RESTRICTED},
        )
