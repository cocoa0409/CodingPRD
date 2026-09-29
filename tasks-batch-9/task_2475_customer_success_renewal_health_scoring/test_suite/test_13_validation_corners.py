"""Corner cases of the validation ladder: one refusal, or one admission, per rule.

Each test drives a request that violates exactly one rule and pins both the
error identity and the fact that nothing was written, or drives the same request
once its rule is satisfied and pins the admitted result.
"""

from test_helpers import (
    ASSIGNMENT_COMMITTED,
    CASE_OPEN,
    CHURN_MERGER_ACQUISITION,
    CODE_DATA_INTEGRATION,
    CODE_KICKOFF,
    COMMITMENT_PROPOSED,
    CS_STATE_DRAFT,
    FINANCE_STATE_PENDING,
    HEALTH_RED,
    LIFECYCLE_ACTION_CHURN,
    LIFECYCLE_ACTION_WIN_BACK_TARGET,
    LIFECYCLE_CHURNED,
    LIFECYCLE_ONBOARDING,
    LIKELIHOOD_AT_RISK,
    MILESTONE_ACTION_COMPLETE,
    MILESTONE_PENDING,
    OPS_ADMIN_HEADERS,
    POSTURE_FROZEN,
    POSTURE_OPEN,
    POSTURE_RESTRICTED,
    TIER_HIGH_TOUCH,
    TIER_UNASSIGNED,
    EXECUTIVE_HEADERS,
    MISSING_USER_ID_HEADERS,
    ApiClient,
    ApiErrorId,
    add_milestone,
    assert_capacity_conserved,
    assert_cents,
    assert_created,
    assert_credit_ledger,
    assert_field,
    assert_fields,
    assert_null,
    assert_page,
    assert_present,
    create_account,
    create_csm,
    drive_lifecycle,
    factories,
    make_csm_headers,
    open_forecast,
    read_account,
    read_case,
    read_csm,
    read_milestone,
    segment_account,
    validate_error,
)


class TestAccountPatchContractEnd:
    """An amendment may not backdate the end of the term."""

    def test_patch_with_past_contract_end_date_is_refused(
        self, api: ApiClient, clock: str
    ) -> None:
        """A `contract_end_date` before the clock date is refused and nothing is written.

        PRD §2.5: "Until the clock has been set at least once, its value is `2026-08-01T00:00:00Z`."
        PRD §2.9: "For an account patch, a supplied `contract_end_date` is strictly after the logical clock date."
        PRD §3.1: "A supplied `contract_end_date` must be strictly after the logical clock date; a backdated term end is refused with `ERR_CONTRACT_END_IN_PAST`."
        PRD §2.4: "`version` is an integer that starts at 1 when the row is created and increments by exactly 1 on every mutation."

        Design: Corner/validations/patch_account_with_past_contract_end_date_returns_contract_end_in_past
        """
        account = create_account(api)
        assert_field(account, "contract_end_date", "2026-12-31")
        assert_field(account, "version", 1)

        response = api.patch_account(
            account["id"],
            factories.account_patch(contract_end_date="2026-07-01"),
            OPS_ADMIN_HEADERS,
        )
        validate_error(response, ApiErrorId.CONTRACT_END_IN_PAST)

        unchanged = read_account(api, account["id"])
        assert_fields(
            unchanged, {"contract_end_date": "2026-12-31", "version": 1}
        )


class TestMilestoneSequence:
    """Onboarding milestones complete in ascending order of their position."""

    def test_completing_out_of_sequence_is_refused(
        self, api: ApiClient, clock: str
    ) -> None:
        """Completing position 2 while position 1 is still PENDING is refused.

        PRD §2.9: "For a `COMPLETE` milestone action, every onboarding milestone of the same account whose `sequence_index` is strictly lower is already in state `COMPLETED` or `WAIVED`."
        PRD §3.1: "Completing a milestone is the CSM's step, and it is gated three ways: the account's `coverage_posture` must not be `FROZEN`, every milestone of the same account whose `sequence_index` is strictly lower must already be `COMPLETED` or `WAIVED` (otherwise `ERR_MILESTONE_SEQUENCE_VIOLATION`), and a `completed_date` must be supplied."
        PRD §3.1: "A new milestone begins in state `PENDING` with `completed_date` null and `days_late` null, and milestones may only be added while the account's posture is not `FROZEN`."
        PRD §3.1: "It fires when the account has at least one onboarding milestone and every one of them is in state `COMPLETED` or `WAIVED`."

        Design: Corner/validations/milestone_completed_out_of_sequence_returns_sequence_violation
        """
        csm = create_csm(api)
        account = create_account(api)
        first = add_milestone(
            api, account["id"], csm["id"], 1, "2026-08-10", CODE_KICKOFF
        )
        second = add_milestone(
            api, account["id"], csm["id"], 2, "2026-08-20", CODE_DATA_INTEGRATION
        )

        response = api.transition_milestone(
            second["id"],
            factories.milestone_transition(
                MILESTONE_ACTION_COMPLETE, completed_date="2026-08-05"
            ),
            make_csm_headers(csm["id"]),
        )
        validate_error(response, ApiErrorId.MILESTONE_SEQUENCE_VIOLATION)

        blocked = read_milestone(api, account["id"], second["id"])
        assert_field(blocked, "state", MILESTONE_PENDING)
        assert_null(blocked, "completed_date", "days_late")
        assert_field(
            read_milestone(api, account["id"], first["id"]), "state", MILESTONE_PENDING
        )
        # No milestone reached a terminal state, so onboarding cannot be left.
        assert_field(
            read_account(api, account["id"]), "lifecycle_state", LIFECYCLE_ONBOARDING
        )


class TestMilestoneUniqueness:
    """A milestone code is unique within the account whatever its position."""

    def test_duplicate_milestone_code_is_refused(
        self, api: ApiClient, clock: str
    ) -> None:
        """A second KICKOFF at a different position is still a duplicate.

        PRD §2.9: "`milestone_code` and `sequence_index` are each unique within the account across milestones that are not `WAIVED`."
        PRD §3.1: "Both `milestone_code` and `sequence_index` must be unique within the account across milestones that are not `WAIVED`; a repeat of either is refused with `ERR_MILESTONE_CODE_DUPLICATE`."

        Design: Corner/validations/duplicate_milestone_code_on_the_same_account_returns_conflict
        """
        csm = create_csm(api)
        account = create_account(api)
        first = add_milestone(
            api, account["id"], csm["id"], 1, "2026-08-10", CODE_KICKOFF
        )

        response = api.create_milestone(
            account["id"],
            factories.milestone(3, "2026-09-10", CODE_KICKOFF),
            make_csm_headers(csm["id"]),
        )
        validate_error(response, ApiErrorId.MILESTONE_CODE_DUPLICATE)

        rows = assert_page(
            api.list_milestones(account["id"], OPS_ADMIN_HEADERS), expected_total=1
        )
        assert [row["id"] for row in rows] == [first["id"]]


class TestForecastPeriodUniqueness:
    """One account holds at most one forecast per fiscal quarter."""

    def test_duplicate_fiscal_period_is_refused(
        self, api: ApiClient, clock: str
    ) -> None:
        """A second 2026Q4 forecast is refused and the first row is untouched.

        PRD §2.9: "`fiscal_period` is unique per account across that account's renewal forecasts."
        PRD §3.6: "Forecasts may only be created while the account's posture is not `FROZEN`, and only one forecast may exist per account per `fiscal_period`; a repeat is refused with `ERR_FORECAST_PERIOD_DUPLICATE`."
        PRD §3.6: "The new row starts with `cs_state` `DRAFT` and `finance_state` `PENDING`, with `finance_amount_cents`, `variance_cents`, `submitted_at` and `reconciled_at` all null, and it snapshots the account's current `renewal_likelihood` into `likelihood_category` — the forecast records the judgement of the moment it was written and does not track the account afterwards."
        PRD §2.8: "Its default on a brand-new account is `RESTRICTED`."

        Design: Corner/validations/duplicate_fiscal_period_on_the_same_account_returns_conflict
        """
        csm = create_csm(api)
        account = create_account(api)
        assert_field(account, "coverage_posture", POSTURE_RESTRICTED)
        first = open_forecast(api, account["id"], csm["id"], fiscal_period="2026Q4")

        response = api.create_renewal_forecast(
            factories.renewal_forecast(account["id"], fiscal_period="2026Q4"),
            make_csm_headers(csm["id"]),
        )
        validate_error(response, ApiErrorId.FORECAST_PERIOD_DUPLICATE)

        rows = assert_page(
            api.list_renewal_forecasts(account["id"], OPS_ADMIN_HEADERS),
            expected_total=1,
        )
        assert [row["id"] for row in rows] == [first["id"]]
        assert_fields(
            rows[0],
            {"cs_state": CS_STATE_DRAFT, "finance_state": FINANCE_STATE_PENDING},
        )


class TestCoverageAssignmentSegmentationGate:
    """Staffing is barred before segmentation and admitted immediately after it."""

    def test_assignment_before_segmentation_is_refused(
        self, api: ApiClient, clock: str
    ) -> None:
        """An unsegmented account cannot be staffed even with capacity to spare.

        PRD §2.9: "The account's `coverage_tier` is not `UNASSIGNED`, meaning a segmentation run has occurred at least once."
        PRD §3.4: "The account's `coverage_tier` must not be `UNASSIGNED`; staffing an unsegmented account is refused with `ERR_COVERAGE_TIER_UNASSIGNED`."
        PRD §3.1: "The account lands in `lifecycle_state` `ONBOARDING` with `coverage_tier` `UNASSIGNED`, `assigned_csm_id` null, `open_save_play_count` 0, `ttv_breach_flag` false, `contractual_ttv_days` and `activation_ttv_days` both null, `churn_root_cause_code` and `win_back_offer_bp` both null, and both credit counters — `remediation_credit_outstanding_cents` and `remediation_credit_settled_cents` — at 0."
        PRD §3.4: "On creation `capacity_units_committed` is 0, `capacity_units_available` equals `capacity_units_total`, and `status` is `ACTIVE`."
        PRD §2.8: "Its default on a brand-new account is `RESTRICTED`."

        Design: Corner/validations/coverage_assignment_before_segmentation_returns_coverage_tier_unassigned
        """
        csm = create_csm(api)
        account = create_account(api)
        assert_field(account, "coverage_tier", TIER_UNASSIGNED)

        response = api.create_coverage_assignment(
            factories.coverage_assignment(
                account["id"], account["version"], csm_id=csm["id"]
            ),
            OPS_ADMIN_HEADERS,
        )
        validate_error(response, ApiErrorId.COVERAGE_TIER_UNASSIGNED)

        assert_page(
            api.list_coverage_assignments(
                OPS_ADMIN_HEADERS, {"account_id": account["id"]}
            ),
            expected_total=0,
        )
        manager = read_csm(api, csm["id"])
        assert_fields(
            manager,
            {"capacity_units_committed": 0, "capacity_units_available": 40},
        )
        assert_capacity_conserved(manager)
        unchanged = read_account(api, account["id"])
        assert_fields(
            unchanged,
            {
                "coverage_tier": TIER_UNASSIGNED,
                "coverage_posture": POSTURE_RESTRICTED,
            },
        )

    def test_assignment_after_segmentation_commits(
        self, api: ApiClient, clock: str
    ) -> None:
        """Segmentation to HIGH_TOUCH admits the same call at a load of 19 units.

        PRD §3.4: "Otherwise, if `arr_cents` is at least 25,000,000 **or** the account is `ENTERPRISE` with `health_tier` `RED`, the tier is `HIGH_TOUCH` — the second half of that clause is the risk-escalation path that puts a small but distressed enterprise account on the same footing as a large one."
        PRD §3.4: "A base figure comes from the account's coverage tier — 9 units for `HIGH_TOUCH`, 5 for `LOW_TOUCH`, 2 for `DIGITAL`."
        PRD §3.4: "That base is multiplied by a segment multiplier of 1.50 for `ENTERPRISE`, 1.00 for `MIDMARKET` or 0.50 for `SMB`, and by a risk multiplier of 1.25 when `health_tier` is `RED`, 1.10 when `AMBER` and 1.00 when `GREEN`."
        PRD §3.4: "The triple product is rounded half up to two decimal places, and then an integer revenue surcharge is added: 4 units when `arr_cents` is at least 100,000,000, otherwise 2 when it is at least 25,000,000, otherwise 1 when it is at least 5,000,000, otherwise 0."
        PRD §3.4: "The resulting figure is taken to the next whole unit by a **single** ceiling operation, and only then clamped into the range 1 to 20."
        PRD §3.4: "Flipping only the health tier to `RED` yields 16.88 plus 2, so 19; flipping only to `GREEN` yields 13.50 plus 2, so 16; flipping only the segment to `MIDMARKET` yields 9.90 plus 2, so 12; flipping only the coverage tier to `LOW_TOUCH` yields 8.25 plus 2, so 11."
        PRD §3.4: "The assignment snapshots the account's `coverage_tier` onto itself and freezes a `load_units` cost at creation, so later re-tiering or health movement never silently repriced an assignment that is already in flight."
        PRD §3.4: "The test admits the row to `COMMITTED` when the chosen manager's `status` is `ACTIVE` and their `capacity_units_total` minus `capacity_units_committed` is greater than or equal to the assignment's `load_units`; the comparison is inclusive, so an exact fit is admitted and `capacity_units_available` may legitimately reach exactly 0."
        PRD §3.4: "On admission the manager's `capacity_units_committed` rises by the assignment's `load_units`, `capacity_units_available` is recomputed, the assignment's `committed_at` is stamped with the logical clock, the account's `assigned_csm_id` is set to the assignment's `csm_id`, and `coverage_posture` is re-derived — which is how an otherwise clean account finally reaches `OPEN`."

        Design: Corner/validations/coverage_assignment_after_segmentation_succeeds
        """
        csm = create_csm(api)
        account = create_account(api)
        # No signals, so the first health pass leaves the tier RED and the risk
        # multiplier at 1.25.
        assert_field(account, "health_tier", HEALTH_RED)

        segmented = segment_account(api, account["id"])
        assert_field(segmented, "coverage_tier", TIER_HIGH_TOUCH)

        assignment = assert_created(
            api.create_coverage_assignment(
                factories.coverage_assignment(
                    account["id"], segmented["version"], csm_id=csm["id"]
                ),
                OPS_ADMIN_HEADERS,
            )
        )
        assert_fields(
            assignment,
            {
                "state": ASSIGNMENT_COMMITTED,
                "coverage_tier": TIER_HIGH_TOUCH,
                # 9 * 1.50 * 1.25 = 16.875 -> 16.88, plus a surcharge of 2 is
                # 18.88, whose single ceiling is 19 and inside the 1-20 clamp.
                "load_units": 19,
                "csm_id": csm["id"],
            },
        )
        assert_present(assignment, "committed_at")
        assert assignment["committed_at"] is not None
        assert_null(assignment, "released_at", "superseded_by_assignment_id")

        manager = read_csm(api, csm["id"])
        assert_fields(
            manager,
            {"capacity_units_committed": 19, "capacity_units_available": 21},
        )
        assert_capacity_conserved(manager)
        staffed = read_account(api, account["id"])
        assert_fields(
            staffed,
            {"assigned_csm_id": csm["id"], "coverage_posture": POSTURE_OPEN},
        )


class TestCommitmentCreditCap:
    """The credit cap is an inclusive ceiling at ten percent of ARR."""

    def test_credit_one_cent_above_the_cap_is_refused(
        self, api: ApiClient, clock: str, escalated_account: dict
    ) -> None:
        """3,000,001 cents against 30,000,000 of ARR is refused and writes nothing.

        PRD §2.9: "`credit_cents` does not exceed 1,000 basis points — ten percent — of the owning account's `arr_cents`, tested by comparing `credit_cents` multiplied by 10,000 against 1,000 multiplied by `arr_cents`, with equality permitted."
        PRD §3.5: "Its `credit_cents` may not exceed 1,000 basis points — ten percent — of the owning account's `arr_cents`, tested by cross-multiplication so that `credit_cents` × 10,000 must be less than or equal to 1,000 × `arr_cents`; a larger figure is refused with `ERR_CREDIT_EXCEEDS_CAP`."
        PRD §3.5: "The commitment is created in state `PROPOSED` with its `round_index` snapshotted from the case's current `remediation_round`, and it moves no credit counter yet."

        Design: Corner/validations/remediation_commitment_credit_above_the_arr_cap_returns_credit_exceeds_cap
        """
        case = escalated_account["case"]
        account = read_account(api, escalated_account["account_id"])
        assert_cents(account["arr_cents"], 30_000_000, "arr_cents")

        response = api.create_remediation_commitment(
            case["id"],
            factories.remediation_commitment(
                3_000_001, "2026-08-25", case["version"]
            ),
            EXECUTIVE_HEADERS,
        )
        validate_error(response, ApiErrorId.CREDIT_EXCEEDS_CAP)

        assert_page(
            api.list_remediation_commitments(case["id"], OPS_ADMIN_HEADERS),
            expected_total=0,
        )
        assert_credit_ledger(
            read_account(api, escalated_account["account_id"]), 0, 0
        )

    def test_credit_exactly_at_the_cap_is_admitted(
        self, api: ApiClient, clock: str, escalated_account: dict
    ) -> None:
        """3,000,000 cents is exactly ten percent of ARR and is admitted as PROPOSED.

        PRD §2.9: "`credit_cents` does not exceed 1,000 basis points — ten percent — of the owning account's `arr_cents`, tested by comparing `credit_cents` multiplied by 10,000 against 1,000 multiplied by `arr_cents`, with equality permitted."
        PRD §3.5: "The commitment is created in state `PROPOSED` with its `round_index` snapshotted from the case's current `remediation_round`, and it moves no credit counter yet."
        PRD §3.5: "The case opens in state `OPEN` with `remediation_round` 1 and `final_credit_cents` null, and its creation re-derives the account's `coverage_posture`, which an open case forces to `RESTRICTED`."

        Design: Corner/validations/remediation_commitment_credit_above_the_arr_cap_returns_credit_exceeds_cap
        """
        case = escalated_account["case"]

        commitment = assert_created(
            api.create_remediation_commitment(
                case["id"],
                factories.remediation_commitment(
                    3_000_000, "2026-08-25", case["version"]
                ),
                EXECUTIVE_HEADERS,
            )
        )
        assert_cents(commitment["credit_cents"], 3_000_000, "credit_cents")
        assert_fields(
            commitment, {"state": COMMITMENT_PROPOSED, "round_index": 1}
        )

        # A proposed credit accrues nothing yet.
        assert_credit_ledger(
            read_account(api, escalated_account["account_id"]), 0, 0
        )
        case_row = read_case(api, case["id"])
        assert_field(case_row, "state", CASE_OPEN)
        assert_null(case_row, "final_credit_cents")


class TestWinBackRootCauseBar:
    """A merger-driven churn cannot be reopened as a win-back campaign."""

    def test_win_back_after_merger_acquisition_churn_is_refused(
        self, api: ApiClient, clock: str
    ) -> None:
        """The one barred root cause refuses WIN_BACK_TARGET and stores no offer.

        PRD §3.9: "Every churn requires a `churn_root_cause_code`, drawn from `PRODUCT_GAP`, `PRICE`, `SPONSOR_CHURN`, `POOR_ONBOARDING`, `SUPPORT_QUALITY` and `MERGER_ACQUISITION`, stores it on the account, and ends by re-deriving `coverage_posture`, which necessarily yields `FROZEN` because the first posture clause matches on lifecycle alone."
        PRD §3.9: "`MERGER_ACQUISITION` is the single root cause that bars a win-back campaign — there is no one left to win back — and an attempt is refused with `ERR_ACCOUNT_LIFECYCLE_INVALID`."
        PRD §3.9: "The `WIN_BACK_TARGET` action carries `CHURNED → WIN_BACK_TARGETED`, requires a supplied `win_back_offer_bp` between 0 and 5,000 basis points, and requires that the account's stored `churn_root_cause_code` be one of `PRODUCT_GAP`, `PRICE`, `SPONSOR_CHURN`, `POOR_ONBOARDING` or `SUPPORT_QUALITY`."
        PRD §3.9: "it does not recompute `renewal_likelihood`, because an account that never adopted has no forecast to withdraw."
        PRD §3.1: "Because a freshly registered account has no usage, no tickets, no sponsors and no goals, this deterministic first pass always produces `adoption_index` 0.00, `support_risk_penalty` 0.00, `exec_engagement_score` 25.00, `outcome_attainment_index` 60.00, `snapshot_health_score` and `trended_health_score` both 43.75, `health_tier` `RED`, `renewal_likelihood` `AT_RISK` and `coverage_posture` `RESTRICTED`."

        Design: Corner/validations/win_back_target_after_merger_acquisition_churn_is_barred
        """
        account = create_account(api)
        churned = drive_lifecycle(
            api,
            account["id"],
            LIFECYCLE_ACTION_CHURN,
            churn_root_cause_code=CHURN_MERGER_ACQUISITION,
        )
        assert_field(churned, "lifecycle_state", LIFECYCLE_CHURNED)

        response = api.account_lifecycle(
            account["id"],
            factories.lifecycle_action(
                LIFECYCLE_ACTION_WIN_BACK_TARGET, win_back_offer_bp=500
            ),
            OPS_ADMIN_HEADERS,
        )
        validate_error(response, ApiErrorId.ACCOUNT_LIFECYCLE_INVALID)

        unchanged = read_account(api, account["id"])
        assert_fields(
            unchanged,
            {
                "lifecycle_state": LIFECYCLE_CHURNED,
                "churn_root_cause_code": CHURN_MERGER_ACQUISITION,
                "coverage_posture": POSTURE_FROZEN,
                # A churn out of ONBOARDING leaves the registration-time
                # category in place.
                "renewal_likelihood": LIKELIHOOD_AT_RISK,
            },
        )
        assert_null(unchanged, "win_back_offer_bp")


class TestAuthenticationPrecedence:
    """Identity is checked before anything else about the request."""

    def test_missing_user_id_header_is_unauthenticated(
        self, api: ApiClient, clock: str
    ) -> None:
        """A valid body with no `X-User-ID` is 401 and registers no account.

        PRD §2.1: "If `X-User-ID` is absent or empty, or if `X-User-Role` does not name one of the roles declared below, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401) before anything else about the request is examined."
        PRD §2.9: "`X-User-ID` is present and non-empty and `X-User-Role` names one of the six declared roles."

        Design: Corner/validations/request_missing_x_user_header_returns_unauthenticated
        """
        response = api.create_account(
            factories.account(name="Header Probe"), MISSING_USER_ID_HEADERS
        )
        validate_error(response, ApiErrorId.UNAUTHENTICATED)

        assert_page(api.list_accounts(OPS_ADMIN_HEADERS), expected_total=0)
