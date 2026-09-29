"""Non-linear lifecycle paths: a site's two independent status axes, and the claim's edit-check
failure cycle that returns a submitted claim to DRAFT and back.

A site carries a regulatory axis and an operational axis on the same row, so a move on one axis
must leave the other axis exactly where it stood. A meal claim, by contrast, is cyclic: the same
claim walks DRAFT -> SUBMITTED -> EDIT_CHECK_FAILED -> DRAFT -> SUBMITTED, and only the
post-payment revision loop advances its loop counter.

Every scenario is built from scratch against an empty database through PRD endpoints only.
"""

from test_helpers import (
    ApiErrorId,
    assert_claim_line_item,
    assert_meal_claim,
    assert_site,
    close_for_season,
    make_sponsor_admin_headers,
    open_claim_revision,
    run_edit_check,
    setup_june_claim_scenario,
    setup_program_baseline,
    start_operating,
    submit_claim,
    validate_error,
    validate_success,
)

# --- Site approval-axis decisions ------------------------------------------------------------

SUSPENSION_REASON = "Unannounced review found no site supervisor present"
REINSTATEMENT_REASON = "Supervisor coverage documented"

# --- The June claim under a missing first-week monitoring visit -------------------------------

# One rural SELF_PREP site serving 47 LUNCH first meals at the RURAL_OR_SELF_PREP lunch rate of
# 470.50 fractional cents: 47 * 470.50 = 22113.50, rounded half-up once for the line item's single
# meal type gives 22114 cents.
LUNCH_LINE_VALUE_CENTS = 22_114
CLAIMED_OPERATING_COST_CENTS = 20_000
CLAIMED_ADMIN_COST_CENTS = 1_000
PRELIMINARY_REIMBURSEMENT_CENTS = 23_114
DISALLOWED_MEAL_COUNT = 47


def _suspend(api, headers, site_id: str) -> dict:
    """Suspend an approved site on its approval axis with the mandatory reason."""
    return validate_success(
        api.decide_site_approval(
            site_id, {"decision": "SUSPENDED", "reason": SUSPENSION_REASON}, headers
        )
    )


def _reinstate(api, headers, site_id: str) -> dict:
    """Reinstate a suspended site back onto the approved rung of the approval axis."""
    return validate_success(
        api.decide_site_approval(
            site_id, {"decision": "REINSTATED", "reason": REINSTATEMENT_REASON}, headers
        )
    )


def _missing_monitoring_claim_scenario() -> dict:
    """An approved sponsor with an approved budget, one approved and operating rural SELF_PREP
    site with a FINALIZED June day of 47 LUNCH first meals, no monitoring visit at all, and a
    DRAFT June claim carrying that site's single line item."""
    return setup_june_claim_scenario(include_monitoring_visit=False)


class TestSiteParallelStatusDimensions:
    """The approval axis and the operating axis move independently on the same site row."""

    def test_site_suspension_moves_only_the_approval_axis(self, api, reviewer_headers):
        """PRD §3.5: "Suspending a site on the approval axis never touches its operating axis, and
        closing the season never touches its approval axis."

        PRD §3.5: "Suspension is available from `APPROVED`, requires a `reason`, and fires a
        three-part cascade. The `reason` is stored in `suspension_reason` and `claim_hold` is
        raised to true."

        Design: Difficulty/non_linear_state_machine/site_parallel_status_dimensions_move_independently
        """
        scenario = setup_program_baseline(include_budget=False)
        site_id = scenario["site"]["id"]
        assert scenario["site"]["operating_status"] == "OPERATING", (
            "setup must leave the site on the OPERATING rung of the operating axis, got "
            f"{scenario['site']['operating_status']}"
        )

        _suspend(api, reviewer_headers, site_id)

        site = validate_success(api.get_site(site_id, reviewer_headers))
        assert_site(site)
        assert site["approval_status"] == "SUSPENDED", (
            f"the approval axis must read SUSPENDED after the decision, got {site['approval_status']}"
        )
        assert site["operating_status"] == "OPERATING", (
            "suspending on the approval axis must leave the operating axis untouched at OPERATING, "
            f"got {site['operating_status']}"
        )
        assert site["claim_hold"] is True, (
            f"suspension must raise claim_hold to true, got {site['claim_hold']!r}"
        )
        assert site["suspension_reason"] == SUSPENSION_REASON, (
            "the supplied reason must be stored in suspension_reason, expected "
            f"{SUSPENSION_REASON!r}, got {site['suspension_reason']!r}"
        )

    def test_site_reinstatement_restores_approval_axis_with_operating_axis_untouched(
        self, api, reviewer_headers
    ):
        """PRD §3.5: "On reinstatement `suspension_reason` returns to null, `claim_hold` returns to
        false, every claim line item referencing this site under a `DRAFT` or `REVISION_OPENED`
        claim has its `hold_flag` lowered to false, and each affected claim's `blocking_hold_count`
        is recomputed."

        PRD §3.5: "Suspending a site on the approval axis never touches its operating axis, and
        closing the season never touches its approval axis."

        Design: Difficulty/non_linear_state_machine/site_parallel_status_dimensions_move_independently
        """
        scenario = setup_program_baseline(include_budget=False)
        site_id = scenario["site"]["id"]
        _suspend(api, reviewer_headers, site_id)

        _reinstate(api, reviewer_headers, site_id)

        site = validate_success(api.get_site(site_id, reviewer_headers))
        assert_site(site)
        assert site["approval_status"] == "APPROVED", (
            "reinstatement must return the approval axis to APPROVED, got "
            f"{site['approval_status']}"
        )
        assert site["operating_status"] == "OPERATING", (
            "the operating axis must still read OPERATING after a suspension and a reinstatement, "
            f"got {site['operating_status']}"
        )
        assert site["claim_hold"] is False, (
            f"reinstatement must return claim_hold to false, got {site['claim_hold']!r}"
        )
        assert site["suspension_reason"] is None, (
            "reinstatement must clear suspension_reason back to null, got "
            f"{site['suspension_reason']!r}"
        )

    def test_season_close_moves_only_the_operating_axis(self, api, reviewer_headers):
        """PRD §3.5: "Closing the season leaves `approval_status` untouched: a
        `CLOSED_FOR_SEASON` site is still `APPROVED`, and the days it already finalized remain
        fully claimable."

        Design: Difficulty/non_linear_state_machine/site_parallel_status_dimensions_move_independently
        """
        scenario = setup_program_baseline(include_budget=False)
        site_id = scenario["site"]["id"]

        close_for_season(scenario["site"])

        site = validate_success(api.get_site(site_id, reviewer_headers))
        assert_site(site)
        assert site["operating_status"] == "CLOSED_FOR_SEASON", (
            "the operating axis must read CLOSED_FOR_SEASON after the season close, got "
            f"{site['operating_status']}"
        )
        assert site["approval_status"] == "APPROVED", (
            "closing the season must leave the approval axis at APPROVED, got "
            f"{site['approval_status']}"
        )
        assert site["claim_hold"] is False, (
            "a season close is not a compliance event, so claim_hold must stay false, got "
            f"{site['claim_hold']!r}"
        )

    def test_illegal_same_axis_moves_are_rejected_on_both_dimensions(self, api):
        """PRD §3.5: "Any move that the current value of the addressed dimension does not permit —
        a second attempt to start operating, or a season close from `NOT_STARTED` — is rejected
        with `ERR_SITE_STATE_INVALID`."

        Design: Difficulty/non_linear_state_machine/site_parallel_status_dimensions_move_independently
        """
        scenario = setup_program_baseline(include_budget=False, site_count=2, operating=False)
        sponsor_headers = make_sponsor_admin_headers(scenario["sponsor"]["id"])
        started, never_started = scenario["sites"][0], scenario["sites"][1]
        start_operating(started)

        repeat_start = api.set_site_operating_status(
            started["id"], {"to_status": "OPERATING"}, sponsor_headers
        )
        validate_error(repeat_start, ApiErrorId.ERR_SITE_STATE_INVALID.value)

        premature_close = api.set_site_operating_status(
            never_started["id"], {"to_status": "CLOSED_FOR_SEASON"}, sponsor_headers
        )
        validate_error(premature_close, ApiErrorId.ERR_SITE_STATE_INVALID.value)

    def test_operating_start_on_a_suspended_site_is_rejected_as_suspended(
        self, api, reviewer_headers
    ):
        """PRD §3.5: "Moving from `NOT_STARTED` to `OPERATING` requires that the acting
        `SponsorAdmin` owns the site and that the site's `approval_status` is `APPROVED`: a site
        still in `PENDING_REVIEW` or already `DENIED` is rejected with `ERR_SITE_NOT_APPROVED`, and
        a site in `SUSPENDED` is rejected with `ERR_SITE_SUSPENDED`."

        Design: Difficulty/non_linear_state_machine/site_parallel_status_dimensions_move_independently
        """
        scenario = setup_program_baseline(include_budget=False, operating=False)
        site_id = scenario["site"]["id"]
        sponsor_headers = make_sponsor_admin_headers(scenario["sponsor"]["id"])
        _suspend(api, reviewer_headers, site_id)

        response = api.set_site_operating_status(
            site_id, {"to_status": "OPERATING"}, sponsor_headers
        )

        validate_error(response, ApiErrorId.ERR_SITE_SUSPENDED.value)
        site = validate_success(api.get_site(site_id, reviewer_headers))
        assert site["operating_status"] == "NOT_STARTED", (
            "the refused move must leave the operating axis at NOT_STARTED, got "
            f"{site['operating_status']}"
        )

    def test_axis_moves_never_stamp_first_operating_date_or_void_a_day(
        self, api, reviewer_headers
    ):
        """PRD §3.5: "`first_operating_date` is not written when the operating axis moves; it is
        written when service actually begins, and it holds the earliest `service_date` among the
        site's service days that have ever reached `OPEN`. Before the first day opens it is null,
        and while it is null the site has no monitoring obligation clock running at all."

        PRD §3.5: "Then every service day of the site whose `status` is `PLANNED` and whose
        `service_date` is on or after the current logical clock date moves to `VOIDED` with
        `void_reason` set to the literal string `SITE_SUSPENDED`, along with every service day
        currently in `OPEN` regardless of its date, and `voided_day_count` grows by one for each
        day voided."

        Design: Difficulty/non_linear_state_machine/site_parallel_status_dimensions_move_independently
        """
        scenario = setup_program_baseline(include_budget=False)
        site_id = scenario["site"]["id"]

        after_start = validate_success(api.get_site(site_id, reviewer_headers))
        assert after_start["first_operating_date"] is None, (
            "no service day has ever reached OPEN, so moving the operating axis must leave "
            f"first_operating_date null, got {after_start['first_operating_date']!r}"
        )

        _suspend(api, reviewer_headers, site_id)
        after_suspension = validate_success(api.get_site(site_id, reviewer_headers))
        assert after_suspension["first_operating_date"] is None, (
            "the suspension must not stamp first_operating_date, got "
            f"{after_suspension['first_operating_date']!r}"
        )
        assert after_suspension["voided_day_count"] == 0, (
            "the site has no service days, so the suspension cascade voids nothing and "
            f"voided_day_count must stay 0, got {after_suspension['voided_day_count']}"
        )

        _reinstate(api, reviewer_headers, site_id)
        after_reinstatement = validate_success(api.get_site(site_id, reviewer_headers))
        assert after_reinstatement["first_operating_date"] is None, (
            "the reinstatement must not stamp first_operating_date either, got "
            f"{after_reinstatement['first_operating_date']!r}"
        )
        assert after_reinstatement["voided_day_count"] == 0, (
            "no day was ever voided, so voided_day_count must still be 0, got "
            f"{after_reinstatement['voided_day_count']}"
        )


class TestMealClaimEditCheckFailureCycle:
    """The same claim walks DRAFT -> SUBMITTED -> EDIT_CHECK_FAILED -> DRAFT -> SUBMITTED."""

    def test_draft_claim_submission_records_submitted_status_and_preliminary_entitlement(self):
        """PRD §3.8: "Submitting moves `status` to `SUBMITTED`, writes both cost figures, stamps
        `submitted_at` with the logical clock's current instant, and sets `is_late` true when the
        UTC date of `submitted_at` falls after `deadline_date` — submitting on the `deadline_date`
        itself is on time."

        PRD §3.8: "The claim's `preliminary_reimbursement_cents` is then written from the
        **preliminary** reimbursement variant, which is deliberately simple: it is the claim's
        `meals_rate_value_cents` plus its `claimed_admin_cost_cents`, with no disallowances
        subtracted and **no caps of any kind applied**."

        Design: Difficulty/non_linear_state_machine/meal_claim_edit_check_failure_cycle_returns_to_draft
        """
        scenario = _missing_monitoring_claim_scenario()

        claim = submit_claim(
            scenario["claim"],
            claimed_operating_cost_cents=CLAIMED_OPERATING_COST_CENTS,
            claimed_admin_cost_cents=CLAIMED_ADMIN_COST_CENTS,
        )

        assert_meal_claim(claim)
        assert claim["status"] == "SUBMITTED", (
            f"the first submit must move the claim to SUBMITTED, got {claim['status']}"
        )
        assert claim["claimed_operating_cost_cents"] == CLAIMED_OPERATING_COST_CENTS, (
            "the asserted operating cost must be written onto the claim, expected "
            f"{CLAIMED_OPERATING_COST_CENTS}, got {claim['claimed_operating_cost_cents']}"
        )
        assert claim["claimed_admin_cost_cents"] == CLAIMED_ADMIN_COST_CENTS, (
            "the asserted administrative cost must be written onto the claim, expected "
            f"{CLAIMED_ADMIN_COST_CENTS}, got {claim['claimed_admin_cost_cents']}"
        )
        assert claim["is_late"] is False, (
            "the claim was submitted on 2026-07-06, well before its deadline, so is_late must be "
            f"false, got {claim['is_late']!r}"
        )
        assert claim["meals_rate_value_cents"] == LUNCH_LINE_VALUE_CENTS, (
            "the single LUNCH line of 47 first meals must be worth 22114 cents, got "
            f"{claim['meals_rate_value_cents']}"
        )
        assert claim["preliminary_reimbursement_cents"] == PRELIMINARY_REIMBURSEMENT_CENTS, (
            "the preliminary figure must add the asserted admin cost of 1000 to the meals value of "
            f"22114 with no cap applied, expected {PRELIMINARY_REIMBURSEMENT_CENTS}, got "
            f"{claim['preliminary_reimbursement_cents']}"
        )

    def test_failed_edit_check_moves_claim_to_edit_check_failed_with_line_disallowance(
        self, api, reviewer_headers
    ):
        """PRD §3.8: "On the **disallowance branch**, where at least one line failed, the claim
        moves from `SUBMITTED` to `EDIT_CHECK_FAILED`: each failing line records its
        `edit_check_status`, `disallow_reason`, `disallowed_counts_by_type` and
        `disallowed_meal_count` while the passing lines are set to `PASSED`, the claim's
        `edit_check_failure_codes` is set to the distinct failing reasons in sorted order, the
        claim's `disallowed_meal_count` is recomputed, and the final reimbursement variant runs on
        the surviving meals to write `final_reimbursement_cents`."

        PRD §3.8: "When it fires, the disallowed count for every meal type is that type's claimed
        first meals plus its claimed second meals — the entire line's meals come out."

        Design: Difficulty/non_linear_state_machine/meal_claim_edit_check_failure_cycle_returns_to_draft
        """
        scenario = _missing_monitoring_claim_scenario()
        submitted = submit_claim(
            scenario["claim"],
            claimed_operating_cost_cents=CLAIMED_OPERATING_COST_CENTS,
            claimed_admin_cost_cents=CLAIMED_ADMIN_COST_CENTS,
        )

        claim = run_edit_check(submitted)

        assert_meal_claim(claim)
        assert claim["status"] == "EDIT_CHECK_FAILED", (
            "a line disallowed for its missing first-week visit must move the claim to "
            f"EDIT_CHECK_FAILED, got {claim['status']}"
        )
        assert claim["edit_check_failure_codes"] == ["MISSING_MONITORING"], (
            "the claim must carry the single distinct failing reason MISSING_MONITORING, got "
            f"{claim['edit_check_failure_codes']!r}"
        )
        assert claim["final_reimbursement_cents"] == 0, (
            "with all 47 meals disallowed no meals survive and the administrative cap is keyed to "
            f"an operating reimbursement of 0, so the final figure must be 0, got "
            f"{claim['final_reimbursement_cents']}"
        )

        line_item = validate_success(
            api.get_claim_line_item(scenario["line_item"]["id"], reviewer_headers)
        )
        assert_claim_line_item(line_item)
        assert line_item["edit_check_status"] == "FAILED", (
            f"the disallowed line must read edit_check_status FAILED, got "
            f"{line_item['edit_check_status']}"
        )
        assert line_item["disallow_reason"] == "MISSING_MONITORING", (
            "the site has no conducted and timely FIRST_WEEK visit, so the line's reason must be "
            f"MISSING_MONITORING, got {line_item['disallow_reason']}"
        )
        assert line_item["disallowed_meal_count"] == DISALLOWED_MEAL_COUNT, (
            "the whole line comes out, so disallowed_meal_count must be the 47 claimed LUNCH "
            f"meals, got {line_item['disallowed_meal_count']}"
        )
        assert line_item["disallowed_counts_by_type"] == {"LUNCH": DISALLOWED_MEAL_COUNT}, (
            "the disallowed map must carry the line's 47 LUNCH meals, got "
            f"{line_item['disallowed_counts_by_type']!r}"
        )

    def test_missing_monitoring_disallowance_flags_the_site_without_raising_a_claim_hold(
        self, api, reviewer_headers
    ):
        """PRD §3.8: "First, for every line whose `disallow_reason` became `EXCEEDS_PRODUCTION` or
        `MISSING_MONITORING`, that line's site has `compliance_flag_count` increased by 1 — a
        `FOOD_SAFETY_BREACH` disallowance costs the claim its meals but does not add a compliance
        flag. Second, a site whose `compliance_flag_count` reaches the threshold of 2 has one
        corrective action opened against it with `origin` `COMPLIANCE_FLAG`, `severity` `MAJOR`,
        `status` `OPEN`, `monitoring_visit_id` null, `finding_code` `COMPLIANCE_FLAG_THRESHOLD`,
        `opened_by_user_id` the literal value `SYSTEM`, and a `due_date` 15 days out per the
        severity ladder; the same site has `claim_hold` set to true."

        Design: Difficulty/non_linear_state_machine/meal_claim_edit_check_failure_cycle_returns_to_draft
        """
        scenario = _missing_monitoring_claim_scenario()
        submitted = submit_claim(
            scenario["claim"],
            claimed_operating_cost_cents=CLAIMED_OPERATING_COST_CENTS,
            claimed_admin_cost_cents=CLAIMED_ADMIN_COST_CENTS,
        )

        run_edit_check(submitted)

        site = validate_success(api.get_site(scenario["site"]["id"], reviewer_headers))
        assert_site(site)
        assert site["compliance_flag_count"] == 1, (
            "one MISSING_MONITORING disallowance must add exactly one compliance flag to the "
            f"site, got {site['compliance_flag_count']}"
        )
        assert site["claim_hold"] is False, (
            "a single flag has not reached the threshold of 2, so claim_hold must stay false, got "
            f"{site['claim_hold']!r}"
        )

    def test_open_revision_returns_failed_claim_to_draft_and_resets_line_items(
        self, api, reviewer_headers
    ):
        """PRD §3.8: "Reopening from `EDIT_CHECK_FAILED` returns the claim to `DRAFT`:
        `revision_round` increases by 1, `submitted_at`, `preliminary_reimbursement_cents`,
        `final_reimbursement_cents` and `edit_check_failure_codes` are all set to null, and every
        line item returns to `edit_check_status` `PENDING` with `disallow_reason` `NONE`,
        `disallowed_counts_by_type` cleared and `disallowed_meal_count` back to 0."

        Design: Difficulty/non_linear_state_machine/meal_claim_edit_check_failure_cycle_returns_to_draft
        """
        scenario = _missing_monitoring_claim_scenario()
        submitted = submit_claim(
            scenario["claim"],
            claimed_operating_cost_cents=CLAIMED_OPERATING_COST_CENTS,
            claimed_admin_cost_cents=CLAIMED_ADMIN_COST_CENTS,
        )
        failed = run_edit_check(submitted)

        claim = open_claim_revision(failed, "Sponsor to document the first-week monitoring visit")

        assert_meal_claim(claim)
        assert claim["status"] == "DRAFT", (
            "reopening a claim from EDIT_CHECK_FAILED must return it to DRAFT rather than to a new "
            f"terminal state, got {claim['status']}"
        )
        assert claim["revision_round"] == 1, (
            f"the loop counter must advance exactly once, to 1, got {claim['revision_round']}"
        )
        for nulled_field in (
            "submitted_at",
            "preliminary_reimbursement_cents",
            "final_reimbursement_cents",
            "edit_check_failure_codes",
        ):
            assert claim[nulled_field] is None, (
                f"{nulled_field} must be set to null when the claim returns to DRAFT, got "
                f"{claim[nulled_field]!r}"
            )

        line_item = validate_success(
            api.get_claim_line_item(scenario["line_item"]["id"], reviewer_headers)
        )
        assert_claim_line_item(line_item)
        assert line_item["edit_check_status"] == "PENDING", (
            "the line item must return to edit_check_status PENDING on re-entry to DRAFT, got "
            f"{line_item['edit_check_status']}"
        )
        assert line_item["disallow_reason"] == "NONE", (
            f"the line item's disallow_reason must reset to NONE, got {line_item['disallow_reason']}"
        )
        assert line_item["disallowed_meal_count"] == 0, (
            "the line item's disallowed_meal_count must reset to 0, got "
            f"{line_item['disallowed_meal_count']}"
        )
        assert not line_item["disallowed_counts_by_type"], (
            "the line item's disallowed_counts_by_type must be cleared, got "
            f"{line_item['disallowed_counts_by_type']!r}"
        )

    def test_resubmission_from_draft_leaves_revision_round_at_one(self, api, reviewer_headers):
        """PRD §3.8: "Submitting from `REVISION_OPENED` behaves identically except that it also
        increases `revision_round` by 1."

        Design: Difficulty/non_linear_state_machine/meal_claim_edit_check_failure_cycle_returns_to_draft
        """
        scenario = _missing_monitoring_claim_scenario()
        submitted = submit_claim(
            scenario["claim"],
            claimed_operating_cost_cents=CLAIMED_OPERATING_COST_CENTS,
            claimed_admin_cost_cents=CLAIMED_ADMIN_COST_CENTS,
        )
        failed = run_edit_check(submitted)
        reopened = open_claim_revision(failed, "Sponsor to document the first-week monitoring visit")

        claim = submit_claim(
            reopened,
            claimed_operating_cost_cents=CLAIMED_OPERATING_COST_CENTS,
            claimed_admin_cost_cents=CLAIMED_ADMIN_COST_CENTS,
        )

        assert_meal_claim(claim)
        assert claim["status"] == "SUBMITTED", (
            f"the clean re-submit must move the claim back to SUBMITTED, got {claim['status']}"
        )
        assert claim["revision_round"] == 1, (
            "only a submission from REVISION_OPENED advances the loop counter, so a re-submit from "
            f"DRAFT must leave revision_round at 1, got {claim['revision_round']}"
        )
        assert claim["preliminary_reimbursement_cents"] == PRELIMINARY_REIMBURSEMENT_CENTS, (
            "the re-submit must recompute the same preliminary figure of 23114 cents from the "
            f"unchanged finalized day, got {claim['preliminary_reimbursement_cents']}"
        )
