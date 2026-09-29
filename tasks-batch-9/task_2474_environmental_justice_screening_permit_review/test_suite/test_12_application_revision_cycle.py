"""The enhanced-track revision cycle and why the second pass is not a replay.

An application that is returned, resubmitted and screened again re-enters
`ENHANCED_REVIEW`, but it comes back with a higher revision round, a voided
assessment, a reopened plan carrying fifteen extra days, and a shorter required
comment period than it had the first time.
"""

from test_helpers import (
    ADEQUACY_COMPLIANT,
    ADEQUACY_PENDING,
    ANALYST_HEADERS,
    APP_ENHANCED_REVIEW,
    APP_RETURNED_FOR_REVISION,
    ASSESSMENT_INVALIDATED,
    ASSESSMENT_VOIDED,
    DETERMINATION_ENHANCED_REQUIRED,
    HIGH_IMPACT_EXTRA_DAYS,
    MAX_COMMENT_DAYS,
    PLAN_CLOSED,
    PLAN_OPEN,
    REOPEN_MAX_ADDED_DAYS,
    TRACK_ENHANCED,
    TRIGGER_DESIGNATION,
    TRIGGER_EMISSIONS_THRESHOLD,
    TRIGGER_FACILITY_TYPE,
    TRIGGER_PROXIMITY,
    assert_amount,
    assert_amounts,
    assert_field,
    assert_fields,
    assert_page,
    find_assessment,
    make_applicant_headers,
    read_application,
    read_area,
    read_plan,
    return_for_revision_payload,
    resubmit_payload,
    validate_success,
)

from prd_bench_local_runner.testing import get_success_data


def _return_for_revision(api, state):
    """Analyst returns the pending file, invalidating the accepted assessment."""
    return validate_success(
        api.return_for_revision(
            state["app_id"],
            return_for_revision_payload(
                "emissions inventory must be re-derived from stack test data"
            ),
            ANALYST_HEADERS,
        )
    )


def _resubmit(api, state, proposed_emissions_tpy):
    """The owning representative resubmits with a revised emissions figure."""
    return validate_success(
        api.resubmit_application(
            state["app_id"],
            make_applicant_headers(state["facility_id"]),
            payload=resubmit_payload(proposed_emissions_tpy=proposed_emissions_tpy),
        )
    )


class TestReturnForRevision:
    """PRD §3.9 strips the live analytical work off a returned file."""

    def test_return_invalidates_the_accepted_assessment_and_zeroes_the_indices(
        self, api, app_a_pending_decision
    ):
        """With nothing left governing, both indices fall back to 0.00.

        PRD §3.9: "An `EJAnalyst` who finds the file inadequate returns it to the
        applicant with a `reason`, moving the application `ENHANCED_REVIEW →
        RETURNED_FOR_REVISION` or `PENDING_DECISION → RETURNED_FOR_REVISION`. The
        return invalidates the live analytical work: every assessment of the
        application whose `status` is `SUBMITTED_FOR_QA` or `ACCEPTED` moves to
        `INVALIDATED`, the application's `pre_mitigation_index` and
        `residual_impact_index` are recomputed against whatever now governs, and its
        `version` increments by 1."
        PRD §3.3: "When no candidate exists there is no governing assessment, and both
        `pre_mitigation_index` and `residual_impact_index` are 0.00."

        Design: Difficulty/non_linear_state_machine/application_revision_cycle_enhanced_returned_resubmit
        """
        state = app_a_pending_decision
        before = read_application(api, state["app_id"])
        assert_amount(before.get("pre_mitigation_index"), 81.82, "pre_mitigation_index")
        assert_field(before, "revision_round", 0)

        returned = _return_for_revision(api, state)

        assert_field(returned, "status", APP_RETURNED_FOR_REVISION)
        assert_amounts(
            returned,
            {
                "pre_mitigation_index": 0.00,
                "residual_impact_index": 0.00,
            },
        )
        assert_field(
            find_assessment(api, state["app_id"], state["assessment_id"]),
            "status",
            ASSESSMENT_INVALIDATED,
        )
        # The plan is untouched by the return itself; only resubmission reopens it.
        assert_field(read_plan(api, state["plan_id"]), "status", PLAN_CLOSED)


class TestResubmissionReopensThePlan:
    """PRD §3.9 hands the file back with headroom-limited extra comment time."""

    def test_resubmit_voids_the_assessment_and_reopens_the_plan_with_fifteen_days(
        self, api, app_a_pending_decision
    ):
        """The reopen grants 15 of the 50 available days and re-arms the audit.

        PRD §3.9: "Resubmission moves the application `RETURNED_FOR_REVISION →
        SUBMITTED`, increments `revision_round` by 1, clears `screening_stale_flag` to
        false, moves every assessment of the application in `DRAFT`,
        `SUBMITTED_FOR_QA`, `RETURNED`, `ACCEPTED` or `INVALIDATED` to `VOIDED`,
        reopens the application's `CLOSED` participation plan to `OPEN` under the
        headroom-limited reopen rule of §3.4, recomputes `pre_mitigation_index` and
        `residual_impact_index`, and increments the application's `version` by 1."
        PRD §3.4: "Compute the remaining headroom as 120 minus the sum of
        `required_comment_days` and `granted_extension_days`; the days added are the
        smaller of **15** and that headroom, floored at zero so headroom can never
        subtract. Those added days are added to `granted_extension_days`, and the new
        `comment_end_date` is the later of the current clock date and the existing
        `comment_end_date`, plus the added days." and "Reopening also resets
        `adequacy_status` to `PENDING` and `deficiency_codes` to an empty array,
        increments the area's `open_plan_count` by 1, and increments the plan's
        `version` by 1 — the `OPEN → CLOSED → OPEN` cycle is a normal part of a
        contested file's life."

        Design: Difficulty/non_linear_state_machine/application_revision_cycle_enhanced_returned_resubmit
        """
        state = app_a_pending_decision
        closed = read_plan(api, state["plan_id"])
        assert_fields(
            closed,
            {
                "status": PLAN_CLOSED,
                "required_comment_days": 70,
                "granted_extension_days": 0,
                "comment_end_date": "2026-10-09",
                "adequacy_status": ADEQUACY_COMPLIANT,
            },
        )
        headroom = MAX_COMMENT_DAYS - (
            closed["required_comment_days"] + closed["granted_extension_days"]
        )
        assert headroom >= REOPEN_MAX_ADDED_DAYS, (
            "50 days of headroom should let the reopen grant its full 15 days"
        )

        _return_for_revision(api, state)
        resubmitted = _resubmit(api, state, proposed_emissions_tpy=40.00)

        assert_field(resubmitted, "revision_round", 1)
        assert_field(resubmitted, "screening_stale_flag", False)
        assert_amount(
            resubmitted.get("proposed_emissions_tpy"), 40.00, "proposed_emissions_tpy"
        )
        assert_field(
            find_assessment(api, state["app_id"], state["assessment_id"]),
            "status",
            ASSESSMENT_VOIDED,
        )

        reopened = read_plan(api, state["plan_id"])
        assert_fields(
            reopened,
            {
                "status": PLAN_OPEN,
                "granted_extension_days": REOPEN_MAX_ADDED_DAYS,
                # The clock stands at 2026-10-10, later than the 2026-10-09 end date.
                "comment_end_date": "2026-10-25",
                "adequacy_status": ADEQUACY_PENDING,
                "deficiency_codes": [],
            },
        )
        assert_field(read_area(api, state["area_id"]), "open_plan_count", 1)

    def test_the_voided_assessment_shortens_the_required_comment_period(
        self, api, app_a_pending_decision
    ):
        """Losing the 81.82 index drops the high-impact 10 days, 70 down to 60.

        PRD §3.4: "Start from a base of **30 days**. Add 15 days when the area's
        `designation` is `OVERBURDENED`. Add 30 days when it is
        `SEVERELY_OVERBURDENED`. Add a further 15 days when the area's
        `translation_required` flag is true. Add 10 more days when a governing
        assessment exists and its `cumulative_impact_index` is at least 70.00. Then
        take the smaller of the accumulated total and the ceiling of **120 days**."
        PRD §3.4: "`comment_end_date` is written by exactly three things: opening the
        period, extending it, and the reopen cascade. A later recomputation of
        `required_comment_days` — from a screen, a designation cascade or an
        assessment acceptance — rewrites `required_comment_days` **only** and never
        moves an already-set `comment_end_date`."

        Design: Difficulty/non_linear_state_machine/application_revision_cycle_enhanced_returned_resubmit
        """
        state = app_a_pending_decision
        assert_field(read_plan(api, state["plan_id"]), "required_comment_days", 70)

        _return_for_revision(api, state)
        _resubmit(api, state, proposed_emissions_tpy=40.00)
        # PRD §4 both enumerates the 201 creators (which do not name the screen) and
        # gives 200 to "every state transition"; the screen is both, so its exact 2xx
        # code is not pinned and only the envelope is asserted here.
        get_success_data(api.screen_application(state["app_id"], ANALYST_HEADERS))

        plan = read_plan(api, state["plan_id"])
        # 30 base + 15 designated + 15 translation, with no governing assessment left
        # to add the high-impact days.
        assert_field(plan, "required_comment_days", 60)
        assert plan["required_comment_days"] == 70 - HIGH_IMPACT_EXTRA_DAYS, (
            "the high-impact days should drop away with the voided assessment"
        )
        # The reopen already wrote the end date; the recomputation must not move it.
        assert_field(plan, "comment_end_date", "2026-10-25")
        assert_field(plan, "status", PLAN_OPEN)


class TestSecondScreeningPass:
    """PRD §3.9 stamps a fresh determination for the new revision round."""

    def test_the_rescreen_returns_the_file_to_enhanced_review_with_a_new_row(
        self, api, app_a_pending_decision
    ):
        """Round 1 gets its own determination and round 0 is left as filed.

        PRD §3.9: "The application is then screened afresh, so the full cycle reads
        `RETURNED_FOR_REVISION → SUBMITTED → ENHANCED_REVIEW`, with a new
        applicability determination stamped with the incremented `revision_round`."
        PRD §2.3: "There is exactly one documented exception in this API: the list of
        an application's applicability determinations is returned newest first,
        ordered by `revision_round` descending and then by `created_at` descending, so
        that the determination governing the current revision round appears first."

        Design: Difficulty/non_linear_state_machine/application_revision_cycle_enhanced_returned_resubmit
        """
        state = app_a_pending_decision
        _return_for_revision(api, state)
        _resubmit(api, state, proposed_emissions_tpy=40.00)

        # PRD §4 does not pin whether the screen answers 201 (it mints a
        # determination) or 200 (it is a state transition); any 2xx is accepted.
        screened = get_success_data(
            api.screen_application(state["app_id"], ANALYST_HEADERS)
        )

        assert_field(screened, "result", DETERMINATION_ENHANCED_REQUIRED)

        application = read_application(api, state["app_id"])
        assert_fields(
            application,
            {
                "status": APP_ENHANCED_REVIEW,
                "review_track": TRACK_ENHANCED,
                "revision_round": 1,
                "screening_stale_flag": False,
            },
        )

        rows = assert_page(
            api.list_applicability_determinations(state["app_id"], ANALYST_HEADERS),
            expected_rows=2,
            expected_total=2,
            expected_has_more=False,
        )
        current, original = rows[0], rows[1]
        assert_fields(
            current,
            {
                "revision_round": 1,
                "result": DETERMINATION_ENHANCED_REQUIRED,
                "trigger_codes": [
                    TRIGGER_FACILITY_TYPE,
                    TRIGGER_PROXIMITY,
                    TRIGGER_DESIGNATION,
                    TRIGGER_EMISSIONS_THRESHOLD,
                ],
            },
        )
        assert_amount(
            current.get("ej_screen_score_snapshot"), 74.03, "ej_screen_score_snapshot"
        )
        assert_fields(
            original,
            {
                "revision_round": 0,
                "result": DETERMINATION_ENHANCED_REQUIRED,
            },
        )
        assert_amount(
            original.get("ej_screen_score_snapshot"), 74.03, "ej_screen_score_snapshot"
        )
