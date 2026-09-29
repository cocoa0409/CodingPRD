"""Error corners: the refusals that guard capacity, windows and preconditions.

Every test asserts the exact `error_id` and HTTP status the PRD names for the
condition it creates, and then re-reads the affected rows to show the refusal
wrote nothing.
"""

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiClient,
    ApiErrorId,
    ASSIGNMENT_COMMITTED,
    CS_STATE_DRAFT,
    FINANCE_HEADERS,
    FINANCE_STATE_PENDING,
    HEALTH_RED,
    OPS_ADMIN_HEADERS,
    POSTURE_RESTRICTED,
    RECONCILE_ACTION_RECONCILE,
    TIER_HIGH_TOUCH,
    TIER_LOW_TOUCH,
    assert_capacity_conserved,
    assert_field,
    assert_fields,
    assert_created,
    assert_null,
    assert_ok,
    assert_page,
    build_roster_and_account,
    factories,
    make_csm_headers,
    open_forecast,
    read_account,
    read_csm,
    read_forecast,
    segment_account,
    validate_error,
)


class TestNoEligibleCsm:
    """The candidate pool is filtered by specialty before anything else."""

    def test_no_matching_specialty_returns_no_eligible_csm(
        self, api: ApiClient
    ) -> None:
        """A LOW_TOUCH-only roster cannot staff a HIGH_TOUCH account.

        PRD §3.4: "Otherwise, if `arr_cents` is at least 25,000,000 **or** the account is `ENTERPRISE` with `health_tier` `RED`, the tier is `HIGH_TOUCH` — the second half of that clause is the risk-escalation path that puts a small but distressed enterprise account on the same footing as a large one."
        PRD §3.4: "The candidate pool is the CSMs whose `status` is `ACTIVE` and whose `coverage_specialty` equals the account's current `coverage_tier`; managers who are `ON_LEAVE` or `OFFBOARDED` are excluded, as are managers whose specialty does not match."
        PRD §3.4: "If that pool is empty the request is refused with `ERR_NO_ELIGIBLE_CSM`."

        Design: Corner/errors/coverage_assignment_with_no_matching_specialty_returns_no_eligible_csm
        """
        state = build_roster_and_account(api, coverage_specialty=TIER_LOW_TOUCH)
        segmented = segment_account(api, state["account_id"])
        assert_field(segmented, "coverage_tier", TIER_HIGH_TOUCH)

        response = api.create_coverage_assignment(
            factories.coverage_assignment(state["account_id"], segmented["version"]),
            OPS_ADMIN_HEADERS,
        )

        validate_error(response, ApiErrorId.NO_ELIGIBLE_CSM)
        account = read_account(api, state["account_id"])
        assert_fields(
            account,
            {"coverage_tier": TIER_HIGH_TOUCH, "coverage_posture": POSTURE_RESTRICTED},
        )
        assert_null(account, "assigned_csm_id")
        csm = read_csm(api, state["csm_id"])
        assert_fields(
            csm, {"capacity_units_committed": 0, "capacity_units_available": 40}
        )
        assert_capacity_conserved(csm)
        assert_page(
            api.list_coverage_assignments(
                OPS_ADMIN_HEADERS, {"account_id": state["account_id"]}
            ),
            expected_total=0,
        )


class TestCsmCapacityFloor:
    """A manager's total may fall to their committed units but no further."""

    def test_lowering_below_committed_returns_capacity_exhausted(
        self, api: ApiClient
    ) -> None:
        """A manager carrying 19 committed units cannot be trimmed to a total of 16.

        PRD §3.4: "The single ceiling is load-bearing: a `HIGH_TOUCH`, `ENTERPRISE`, `AMBER` account at 30,000,000 cents gives 9 × 1.50 × 1.10 = 14.85, plus a surcharge of 2, giving 16.85, whose ceiling is `load_units` 17 — whereas taking a ceiling of the 13.50 sub-product before applying the risk multiplier would give 18, a different and incorrect cost."
        PRD §3.4: "Flipping only the health tier to `RED` yields 16.88 plus 2, so 19; flipping only to `GREEN` yields 13.50 plus 2, so 16; flipping only the segment to `MIDMARKET` yields 9.90 plus 2, so 12; flipping only the coverage tier to `LOW_TOUCH` yields 8.25 plus 2, so 11."
        PRD §3.4: "Lowering `capacity_units_total` below the manager's current `capacity_units_committed` is refused with `ERR_CSM_CAPACITY_EXHAUSTED`, because the resulting `capacity_units_available` would be negative and the capacity invariant unsatisfiable."

        Design: Corner/errors/lowering_csm_capacity_below_committed_returns_capacity_exhausted
        """
        state = build_roster_and_account(api)
        assert_field(state["account"], "health_tier", HEALTH_RED)
        segmented = segment_account(api, state["account_id"])
        assignment = assert_created(
            api.create_coverage_assignment(
                factories.coverage_assignment(
                    state["account_id"], segmented["version"]
                ),
                OPS_ADMIN_HEADERS,
            )
        )
        assert_fields(
            assignment, {"load_units": 19, "state": ASSIGNMENT_COMMITTED}
        )

        response = api.patch_csm(
            state["csm_id"], factories.csm_patch(capacity_units_total=16), OPS_ADMIN_HEADERS
        )

        validate_error(response, ApiErrorId.CSM_CAPACITY_EXHAUSTED)
        csm = read_csm(api, state["csm_id"])
        assert_fields(
            csm,
            {
                "capacity_units_total": 40,
                "capacity_units_committed": 19,
                "capacity_units_available": 21,
            },
        )
        assert_capacity_conserved(csm)

    def test_lowering_to_exactly_committed_succeeds(self, api: ApiClient) -> None:
        """Trimming the same manager to a total of exactly 19 is allowed and leaves 0 available.

        PRD §3.4: "Lowering `capacity_units_total` below the manager's current `capacity_units_committed` is refused with `ERR_CSM_CAPACITY_EXHAUSTED`, because the resulting `capacity_units_available` would be negative and the capacity invariant unsatisfiable."
        PRD §3.4: "CS operations may later amend `status` or `capacity_units_total`; either amendment recomputes `capacity_units_available` as `capacity_units_total` minus `capacity_units_committed`."
        PRD §2.10: "`capacity_units_available` must always equal `capacity_units_total` minus `capacity_units_committed`."

        Design: Corner/errors/lowering_csm_capacity_below_committed_returns_capacity_exhausted
        """
        state = build_roster_and_account(api)
        segmented = segment_account(api, state["account_id"])
        assignment = assert_created(
            api.create_coverage_assignment(
                factories.coverage_assignment(
                    state["account_id"], segmented["version"]
                ),
                OPS_ADMIN_HEADERS,
            )
        )
        assert_field(assignment, "load_units", 19)

        patched = assert_ok(
            api.patch_csm(
                state["csm_id"],
                factories.csm_patch(capacity_units_total=19),
                OPS_ADMIN_HEADERS,
            )
        )

        assert_fields(
            patched,
            {
                "capacity_units_total": 19,
                "capacity_units_committed": 19,
                "capacity_units_available": 0,
            },
        )
        assert_capacity_conserved(patched)


class TestSavePlayWindow:
    """A save play's calendar window must be non-empty."""

    def test_inverted_window_returns_invalid_engagement_interval(
        self, api: ApiClient
    ) -> None:
        """An end date before the start date is refused and no play row is written.

        PRD §3.5: "The window must be non-empty: `window_end_date` on or after `window_start_date`, or `ERR_INVALID_ENGAGEMENT_INTERVAL`; note that a single-day play is legitimate."
        PRD §3.5: "A new play enters state `DRAFT` with `outcome_note` null, and — this is deliberate — drafting a play does **not** increment `Account.open_save_play_count`, so it neither restricts the account's posture nor disqualifies it from a `COMMIT` renewal category."

        Design: Corner/errors/save_play_with_inverted_window_returns_invalid_engagement_interval
        """
        state = build_roster_and_account(api)

        response = api.create_save_play(
            factories.save_play(
                state["account_id"], state["csm_id"], "2026-08-20", "2026-08-05"
            ),
            make_csm_headers(state["csm_id"]),
        )

        validate_error(response, ApiErrorId.INVALID_ENGAGEMENT_INTERVAL)
        assert_page(
            api.list_save_plays(
                OPS_ADMIN_HEADERS, {"account_id": state["account_id"]}
            ),
            expected_total=0,
        )
        assert_field(read_account(api, state["account_id"]), "open_save_play_count", 0)


class TestForecastReconcilePrecondition:
    """Finance may only reconcile a forecast the CSM has submitted."""

    def test_reconciling_a_draft_returns_forecast_not_submitted(
        self, api: ApiClient
    ) -> None:
        """A DRAFT forecast is refused before any variance arithmetic happens.

        PRD §3.6: "Reconciling requires that `cs_state` be `SUBMITTED`; reconciling a draft is refused with `ERR_FORECAST_NOT_SUBMITTED`."
        PRD §3.6: "The new row starts with `cs_state` `DRAFT` and `finance_state` `PENDING`, with `finance_amount_cents`, `variance_cents`, `submitted_at` and `reconciled_at` all null, and it snapshots the account's current `renewal_likelihood` into `likelihood_category` — the forecast records the judgement of the moment it was written and does not track the account afterwards."

        Design: Corner/errors/reconciling_a_draft_forecast_returns_forecast_not_submitted
        """
        state = build_roster_and_account(api)
        forecast = open_forecast(
            api, state["account_id"], state["csm_id"], fiscal_period="2026Q4"
        )
        assert_fields(
            forecast,
            {"cs_state": CS_STATE_DRAFT, "finance_state": FINANCE_STATE_PENDING},
        )

        response = api.reconcile_renewal_forecast(
            forecast["id"],
            factories.forecast_reconcile(
                RECONCILE_ACTION_RECONCILE, finance_amount_cents=27_000_000
            ),
            FINANCE_HEADERS,
        )

        validate_error(response, ApiErrorId.FORECAST_NOT_SUBMITTED)
        unchanged = read_forecast(api, forecast["id"])
        assert_fields(
            unchanged,
            {"cs_state": CS_STATE_DRAFT, "finance_state": FINANCE_STATE_PENDING},
        )
        assert_null(
            unchanged, "finance_amount_cents", "variance_cents", "reconciled_at"
        )


class TestCoverageAssignmentLookup:
    """A path identifier that names nothing yields that entity's own 404."""

    def test_unknown_id_returns_not_found(self, api: ApiClient) -> None:
        """Reading an assignment that was never created is a coverage-assignment 404.

        PRD §2.9: "Every entity addressed by a path parameter exists, checked outermost-first."
        PRD §2.9: "Violation: the 404 code for the missing entity type — `ERR_ACCOUNT_NOT_FOUND`, `ERR_CSM_NOT_FOUND`, `ERR_COVERAGE_ASSIGNMENT_NOT_FOUND`, `ERR_SPONSOR_CONTACT_NOT_FOUND`, `ERR_EXECUTIVE_ENGAGEMENT_NOT_FOUND`, `ERR_OUTCOME_GOAL_NOT_FOUND`, `ERR_ONBOARDING_MILESTONE_NOT_FOUND`, `ERR_SAVE_PLAY_NOT_FOUND`, `ERR_ESCALATION_CASE_NOT_FOUND`, `ERR_REMEDIATION_COMMITMENT_NOT_FOUND`, `ERR_RENEWAL_FORECAST_NOT_FOUND`, `ERR_EXPANSION_OPPORTUNITY_NOT_FOUND` or `ERR_ADVOCACY_ENROLLMENT_NOT_FOUND`."

        Design: Corner/errors/coverage_assignment_get_with_unknown_id_returns_not_found
        """
        response = api.get_coverage_assignment(NON_EXISTENT_UUID, OPS_ADMIN_HEADERS)

        validate_error(response, ApiErrorId.COVERAGE_ASSIGNMENT_NOT_FOUND)
