"""Validation-ladder precedence pairs and exact-boundary precision checks.

Two families live here.

Precedence pairs prove that when two rungs of the §2.10 ladder are violated by one
and the same request, only the lower-numbered rung's error is reported — each pair
therefore carries a double-violation test plus a control that isolates the
lower-priority rule so it does surface on its own.

Boundary checks pin the inclusive edges the PRD spells out: the tenth business day
of the listed-event window (§2.6 / §3.5) and the 100.00 completeness ceiling that
a wholly waived cycle reaches without carrying any fileable document (§3.4).

Every test builds its own world from scratch: the harness restarts the server
before each test, so each starts against an empty database with the logical clock
at its startup value of 2026-08-01T00:00:00Z.
"""

from test_helpers import (
    ApiErrorId,
    api_client,
    assemble,
    assert_score,
    attest_item,
    confirm,
    create_annual_report_filing,
    create_bond_issue,
    create_content_requirement,
    create_cycle,
    create_engagement,
    create_event_filing,
    create_notice,
    create_undertaking,
    determine_notice,
    item_for_requirement,
    list_content_items,
    make_agent_headers,
    make_officer_headers,
    material_event_notice_payload,
    prepare_item,
    read_bond_issue,
    read_cycle,
    read_content_item,
    read_engagement,
    read_filing,
    read_notice,
    read_undertaking,
    run_sweep,
    set_clock,
    submit,
    validate_error,
    validate_paginated,
    waive_item,
)
from test_helpers.test_users import OFFICER_ASSEMBLER_ID, OFFICER_PREPARER_ID


# --------------------------------------------------------------------------- #
# Module-level composite preconditions.  fixtures.py builds no chain that leaves
# one engagement SUSPENDED while it holds both a CONFIRMED and a SUBMITTED
# filing, so that world is assembled here through PRD-declared endpoints only.
# --------------------------------------------------------------------------- #

def _setup_suspended_engagement_holding_two_filings():
    """One SUSPENDED engagement, one CONFIRMED filing, one SUBMITTED filing.

    The engagement acknowledges the calendar on 2026-07-01 and the clock ends at
    2026-08-20, which is 50 calendar days of monitoring lapse — past the 45-day
    tolerance, so the sweep suspends it.  The annual report is already CONFIRMED;
    the material-event notice filing is still SUBMITTED and its notice therefore
    sits in FILING_IN_PROGRESS, which sweep step 3 never looks at.
    """
    set_clock("2026-07-05T00:00:00Z")
    issue = create_bond_issue(
        issuer_program_code="COUNTYGO",
        series_designation="2015A",
        security_type="GENERAL_OBLIGATION",
        dated_date="2015-08-01",
        final_maturity_date="2045-08-01",
        original_par_amount_cents=100000000,
    )
    undertaking = create_undertaking(
        issue["id"],
        fiscal_year_end_month_day="06-30",
        filing_window_days=210,
        timeliness_basis="SUBMISSION_BASIS",
    )
    create_content_requirement(
        undertaking["id"],
        kind="OPERATING_DATA_TABLE",
        label="Operating Data Tables",
        weight_bp=10000,
        waivable=False,
    )
    engagement = create_engagement(
        undertaking["id"],
        agent_name="Lakeside Agent Group",
        effective_date="2026-07-01",
        expiration_date="2027-12-31",
        retainer_cents=250000,
        last_calendar_ack_date="2026-07-01",
    )
    cycle = create_cycle(
        undertaking["id"],
        fiscal_year_label="FY2025",
        period_start_date="2024-07-01",
        period_end_date="2025-06-30",
    )
    item = list_content_items(cycle["id"])[0]
    prepare_item(
        item["id"],
        data_as_of_date="2025-06-30",
        source_document_ref="OPDATA-FY2025.pdf",
    )
    attest_item(item["id"])
    assemble(cycle["id"])

    annual_filing = create_annual_report_filing(issue["id"], cycle["id"])
    submit(annual_filing["id"], engagement["id"])
    confirm(annual_filing["id"], engagement["id"], "EMMA-CG-2026-0001")

    notice = create_notice(
        issue["id"],
        event_type="UNSCHEDULED_DRAW_ON_RESERVE",
        occurrence_date="2026-07-01",
    )
    determine_notice(notice["id"], "MATERIAL", determination_note="Reserve draw is material.")
    event_filing = create_event_filing(issue["id"], notice["id"])
    submit(event_filing["id"], engagement["id"])

    set_clock("2026-08-20T00:00:00Z")
    sweep = run_sweep()

    return {
        "issue": issue,
        "undertaking": undertaking,
        "engagement": engagement,
        "cycle": cycle,
        "notice": notice,
        "annual_filing": annual_filing,
        "event_filing": event_filing,
        "sweep": sweep,
    }


class TestStatePreconditionOutranksEngagementGate:
    """§2.10 rung 8 versus rung 11, both HTTP 409, on one suspended engagement."""

    def test_sweep_suspends_the_engagement_at_fifty_lapse_days_and_spares_an_in_progress_notice(self):
        """The precondition world: 50 lapse days suspend the agent, the in-progress notice is untouched.

        PRD §3.10: "Suspension is a sweep-only transition and fires when `monitoring_lapse_days` is **strictly greater than** 45, so a lapse of exactly 45 days is still compliant while 46 days suspends."
        PRD §3.11: "Every `MaterialEventNotice` in `status` `MATERIAL` whose `filing_deadline_date` is strictly before the logical clock's date moves to `MISSED`, with `days_late` set to the calendar days from `filing_deadline_date` to the clock date."
        Design: Difficulty/priority_pair_validation_conflict/state_precondition_at_priority_8_outranks_engagement_not_active_at_11
        """
        context = _setup_suspended_engagement_holding_two_filings()

        assert context["notice"]["filing_deadline_date"] == "2026-07-16"

        engagement = read_engagement(context["engagement"]["id"])
        assert engagement["monitoring_lapse_days"] == 50
        assert engagement["status"] == "SUSPENDED"
        assert context["sweep"]["suspended_engagement_count"] == 1

        # The notice is FILING_IN_PROGRESS, not MATERIAL, so step 3 finds no candidate.
        assert context["sweep"]["missed_event_count"] == 0
        assert read_notice(context["notice"]["id"])["status"] == "FILING_IN_PROGRESS"

    def test_confirming_an_already_confirmed_filing_through_a_suspended_engagement_returns_invalid_state_transition(self):
        """Rung 8 wins the double violation: the filing's own status is reported, not the engagement gate.

        PRD §2.10: "This rule sits deliberately below rule 8, so confirming an already-`CONFIRMED` filing through a terminated engagement returns `ERR_INVALID_STATE_TRANSITION`, not `ERR_ENGAGEMENT_NOT_ACTIVE`."
        PRD §2.10: "This is the highest-priority business check and wins every conflict with the rules below it."
        Design: Difficulty/priority_pair_validation_conflict/state_precondition_at_priority_8_outranks_engagement_not_active_at_11
        """
        context = _setup_suspended_engagement_holding_two_filings()

        response = api_client.confirm_filing(
            context["annual_filing"]["id"],
            {"repository_receipt_id": "EMMA-CG-2026-0002"},
            make_agent_headers(context["engagement"]["id"]),
        )
        validate_error(response, ApiErrorId.ERR_INVALID_STATE_TRANSITION.value)

    def test_confirming_a_submitted_filing_through_a_suspended_engagement_returns_engagement_not_active(self):
        """Control: with rung 8 satisfied, rung 11 surfaces on its own.

        PRD §2.10: "A `SUSPENDED` engagement may still acknowledge the calendar, which is its cure path, and may still be terminated by a `FinanceDirector`; it may not submit, resubmit, confirm, or reject."
        PRD §2.10: "Engagement gate — the engagement acting on this request is `ACTIVE` → `ERR_ENGAGEMENT_NOT_ACTIVE` (409)."
        Design: Difficulty/priority_pair_validation_conflict/state_precondition_at_priority_8_outranks_engagement_not_active_at_11
        """
        context = _setup_suspended_engagement_holding_two_filings()

        response = api_client.confirm_filing(
            context["event_filing"]["id"],
            {"repository_receipt_id": "EMMA-CG-2026-0003"},
            make_agent_headers(context["engagement"]["id"]),
        )
        validate_error(response, ApiErrorId.ERR_ENGAGEMENT_NOT_ACTIVE.value)

    def test_neither_refused_confirmation_writes_anything(self):
        """Both refusals are pure: receipt ids, filing statuses and the notice are all unchanged.

        PRD §5: "When several conditions are simultaneously unmet, the identifier returned is the one belonging to the lowest-numbered rule of the ladder in §2.10 that fails; only one error is ever reported."
        PRD §2.10: "Checks are evaluated in a single strictly ordered ladder, and the **first** rule that fails is the **only** error returned."
        Design: Difficulty/priority_pair_validation_conflict/state_precondition_at_priority_8_outranks_engagement_not_active_at_11
        """
        context = _setup_suspended_engagement_holding_two_filings()
        agent = make_agent_headers(context["engagement"]["id"])

        validate_error(
            api_client.confirm_filing(
                context["annual_filing"]["id"],
                {"repository_receipt_id": "EMMA-CG-2026-0002"},
                agent,
            ),
            ApiErrorId.ERR_INVALID_STATE_TRANSITION.value,
        )
        validate_error(
            api_client.confirm_filing(
                context["event_filing"]["id"],
                {"repository_receipt_id": "EMMA-CG-2026-0003"},
                agent,
            ),
            ApiErrorId.ERR_ENGAGEMENT_NOT_ACTIVE.value,
        )

        annual = read_filing(context["annual_filing"]["id"])
        assert annual["status"] == "CONFIRMED"
        assert annual["repository_receipt_id"] == "EMMA-CG-2026-0001"

        event = read_filing(context["event_filing"]["id"])
        assert event["status"] == "SUBMITTED"
        assert event["repository_receipt_id"] is None

        assert read_notice(context["notice"]["id"])["status"] == "FILING_IN_PROGRESS"


def _setup_live_notice_then_backdate_the_clock():
    """One DETERMINATION_PENDING notice, then a clock 62 days past its occurrence.

    The notice is opened at clock 2026-07-05 with occurrence_date 2026-07-01 and is
    deliberately left undetermined, so its status is neither NOT_MATERIAL nor VOID
    and it still participates in the duplicate check.  The clock then moves to
    2026-09-01, which puts 2026-07-01 sixty-two calendar days in the past — well
    beyond the thirty-day backdating tolerance.
    """
    set_clock("2026-07-05T00:00:00Z")
    issue = create_bond_issue(
        issuer_program_code="SEWERREV",
        series_designation="2020A",
        security_type="REVENUE",
        dated_date="2020-04-01",
        final_maturity_date="2050-04-01",
        original_par_amount_cents=100000000,
    )
    undertaking = create_undertaking(
        issue["id"],
        fiscal_year_end_month_day="12-31",
        filing_window_days=210,
        timeliness_basis="SUBMISSION_BASIS",
    )
    notice = create_notice(
        issue["id"],
        event_type="UNSCHEDULED_DRAW_ON_RESERVE",
        occurrence_date="2026-07-01",
    )
    set_clock("2026-09-01T00:00:00Z")
    return {"issue": issue, "undertaking": undertaking, "notice": notice}


def _open_notice_response(issue_id, event_type, occurrence_date):
    return api_client.create_material_event_notice(
        material_event_notice_payload(
            issue_id, event_type=event_type, occurrence_date=occurrence_date
        ),
        make_officer_headers(OFFICER_PREPARER_ID),
    )


class TestDuplicateNoticeOutranksStaleOccurrenceDate:
    """§2.10 rung 19 versus rung 20 — and the pair also pins 409 against 422."""

    def test_reposting_a_stale_duplicate_reports_the_duplicate_rather_than_the_stale_date(self):
        """Rung 19 wins although the 62-day-old occurrence date violates rung 20 too.

        PRD §3.5: "The duplicate check deliberately outranks both temporal checks, so re-posting a stale duplicate returns `ERR_DUPLICATE_EVENT_NOTICE` rather than `ERR_OCCURRENCE_DATE_STALE`."
        PRD §2.10: "Ranked above rules 20 and 21, so a re-submitted stale duplicate is reported as a duplicate rather than as a stale occurrence date."
        Design: Difficulty/priority_pair_validation_conflict/duplicate_event_notice_at_priority_19_outranks_stale_occurrence_date_at_20
        """
        context = _setup_live_notice_then_backdate_the_clock()

        # The incumbent is live, so it counts for duplicate suppression.
        assert context["notice"]["status"] == "DETERMINATION_PENDING"

        response = _open_notice_response(
            context["issue"]["id"], "UNSCHEDULED_DRAW_ON_RESERVE", "2026-07-01"
        )
        validate_error(response, ApiErrorId.ERR_DUPLICATE_EVENT_NOTICE.value)

    def test_changing_only_the_event_type_clears_rung_nineteen_and_exposes_the_stale_date(self):
        """Control: the same 2026-07-01 occurrence on a fresh event_type surfaces rung 20 alone.

        PRD §3.5: "Then `occurrence_date` must not lie more than 30 calendar days before the logical clock's date, or the request is refused with `ERR_OCCURRENCE_DATE_STALE` — backdating further would mint a notice whose ten-business-day window had already closed at creation."
        PRD §3.5: "Duplicate suppression comes first: no other `MaterialEventNotice` on the same `issue_id` may share the same `event_type` **and** `occurrence_date` while its `status` is neither `NOT_MATERIAL` nor `VOID`; a collision returns `ERR_DUPLICATE_EVENT_NOTICE`."
        Design: Difficulty/priority_pair_validation_conflict/duplicate_event_notice_at_priority_19_outranks_stale_occurrence_date_at_20
        """
        context = _setup_live_notice_then_backdate_the_clock()

        response = _open_notice_response(
            context["issue"]["id"], "TRUSTEE_SUBSTITUTION", "2026-07-01"
        )
        validate_error(response, ApiErrorId.ERR_OCCURRENCE_DATE_STALE.value)

    def test_a_forward_dated_occurrence_is_refused_by_the_separate_future_date_rule(self):
        """Rung 21 is a distinct rule, not a rename of rung 20.

        PRD §3.5: "Then `occurrence_date` must not lie after the logical clock's date, or the request is refused with `ERR_OCCURRENCE_DATE_IN_FUTURE`."
        Design: Difficulty/priority_pair_validation_conflict/duplicate_event_notice_at_priority_19_outranks_stale_occurrence_date_at_20
        """
        context = _setup_live_notice_then_backdate_the_clock()

        response = _open_notice_response(
            context["issue"]["id"], "TRUSTEE_SUBSTITUTION", "2026-09-02"
        )
        validate_error(response, ApiErrorId.ERR_OCCURRENCE_DATE_IN_FUTURE.value)

    def test_an_in_window_occurrence_is_accepted_and_none_of_the_refusals_wrote_a_row(self):
        """A 2026-08-25 occurrence clears all three guards; the three refusals created nothing.

        PRD §3.5: "And `filing_deadline_date` is the **tenth business day strictly after** `occurrence_date`, computed with the add-business-days rule of §2.6: the occurrence date itself is never counted whether or not it is a business day, and the result is the tenth business day encountered walking forward."
        PRD §2.6: "The recognised market holidays are exactly these fourteen dates: 2026-07-03, 2026-09-07, 2026-10-12, 2026-11-11, 2026-11-26, 2026-12-25, 2027-01-01, 2027-01-18, 2027-02-15, 2027-05-31, 2027-07-05, 2027-09-06, 2027-11-25, and 2027-12-24."
        PRD §3.5: "Creation also re-derives the issue's `open_material_event_count` and the undertaking's `open_obligation_count`, because a `DETERMINATION_PENDING` notice is an open obligation."
        Design: Difficulty/priority_pair_validation_conflict/duplicate_event_notice_at_priority_19_outranks_stale_occurrence_date_at_20
        """
        context = _setup_live_notice_then_backdate_the_clock()
        issue_id = context["issue"]["id"]

        validate_error(
            _open_notice_response(issue_id, "UNSCHEDULED_DRAW_ON_RESERVE", "2026-07-01"),
            ApiErrorId.ERR_DUPLICATE_EVENT_NOTICE.value,
        )
        validate_error(
            _open_notice_response(issue_id, "TRUSTEE_SUBSTITUTION", "2026-07-01"),
            ApiErrorId.ERR_OCCURRENCE_DATE_STALE.value,
        )
        validate_error(
            _open_notice_response(issue_id, "TRUSTEE_SUBSTITUTION", "2026-09-02"),
            ApiErrorId.ERR_OCCURRENCE_DATE_IN_FUTURE.value,
        )

        accepted = create_notice(
            issue_id, event_type="TRUSTEE_SUBSTITUTION", occurrence_date="2026-08-25"
        )
        assert accepted["status"] == "DETERMINATION_PENDING"
        # Ten business days after 2026-08-25, with the 2026-09-07 market holiday skipped.
        assert accepted["filing_deadline_date"] == "2026-09-09"

        rows, meta = validate_paginated(
            api_client.list_material_event_notices(
                make_officer_headers(OFFICER_PREPARER_ID),
                params={"issue_id": issue_id, "limit": 100},
            )
        )
        assert meta["total_count"] == 2, "the three refused requests must have created nothing"
        assert len(rows) == 2

        assert read_bond_issue(issue_id)["open_material_event_count"] == 2


def _setup_two_notices_sharing_one_deadline():
    """Two MATERIAL notices with the identical occurrence_date and a DRAFT filing each.

    Both notices carry occurrence_date 2026-09-01; their event_types differ so the
    duplicate-suppression guard never fires.  An ACTIVE engagement acknowledges the
    calendar on 2026-09-01 so no monitoring lapse can interfere, and no calendar
    sweep is ever run, so nothing can move the notices to MISSED behind the test's
    back.
    """
    set_clock("2026-09-01T00:00:00Z")
    issue = create_bond_issue(
        issuer_program_code="TRANSITAUTH",
        series_designation="2021B",
        security_type="REVENUE",
        dated_date="2021-03-01",
        final_maturity_date="2051-03-01",
        original_par_amount_cents=100000000,
    )
    undertaking = create_undertaking(
        issue["id"],
        fiscal_year_end_month_day="06-30",
        filing_window_days=210,
        timeliness_basis="SUBMISSION_BASIS",
    )
    engagement = create_engagement(
        undertaking["id"],
        agent_name="Transit Filing Partners",
        effective_date="2026-09-01",
        expiration_date="2027-12-31",
        retainer_cents=250000,
        last_calendar_ack_date="2026-09-01",
    )
    notice_a = create_notice(
        issue["id"],
        event_type="UNSCHEDULED_DRAW_ON_RESERVE",
        occurrence_date="2026-09-01",
    )
    notice_b = create_notice(
        issue["id"],
        event_type="TRUSTEE_SUBSTITUTION",
        occurrence_date="2026-09-01",
    )
    determine_notice(notice_a["id"], "MATERIAL", determination_note="Reserve draw.")
    determine_notice(notice_b["id"], "MATERIAL", determination_note="Trustee replaced.")
    filing_a = create_event_filing(issue["id"], notice_a["id"])
    filing_b = create_event_filing(issue["id"], notice_b["id"])
    return {
        "issue": issue,
        "undertaking": undertaking,
        "engagement": engagement,
        "notice_a": notice_a,
        "notice_b": notice_b,
        "filing_a": filing_a,
        "filing_b": filing_b,
    }


class TestMaterialEventDeadlineIsInclusiveOnTheTenthBusinessDay:
    """The listed-event window: business days, the 2026-09-07 holiday, and a `<=` edge."""

    def test_the_deadline_is_the_tenth_business_day_not_ten_calendar_days(self):
        """2026-09-01 plus ten business days is 2026-09-16, not the naive 2026-09-11.

        PRD §3.5: "And `filing_deadline_date` is the **tenth business day strictly after** `occurrence_date`, computed with the add-business-days rule of §2.6: the occurrence date itself is never counted whether or not it is a business day, and the result is the tenth business day encountered walking forward."
        PRD §2.6: "**Adding business days** to a base date walks forward one calendar day at a time, counting only business days, and stops when the requested count has been reached; the base date itself is never counted, whether or not it is itself a business day, so adding ten business days to a base date yields the tenth business day strictly after it."
        Design: Difficulty/boundary_precision_check/material_event_deadline_is_inclusive_on_the_tenth_business_day
        """
        context = _setup_two_notices_sharing_one_deadline()

        assert context["notice_a"]["filing_deadline_date"] == "2026-09-16"
        assert context["notice_b"]["filing_deadline_date"] == "2026-09-16"

    def test_submitting_on_the_deadline_date_itself_is_timely(self):
        """Inside the boundary: a 2026-09-16 submission equals the deadline and is timely.

        PRD §3.5: "When the filing that carries the notice is confirmed, the notice is `FILED_TIMELY` if the date part of the filing's `submitted_at` is **less than or equal to** `filing_deadline_date` — a submission on the deadline date is timely — and `FILED_LATE` otherwise, with `days_late` set to the whole calendar days from `filing_deadline_date` to that submission date, floored at 0."
        PRD §3.5: "Either branch stamps `filed_filing_id`, re-derives `open_material_event_count` and `open_obligation_count`, and, when `financial_obligation_ref` is set, moves the referenced `DirectPlacement` from `DISCLOSURE_REQUIRED` to `DISCLOSED`."
        Design: Difficulty/boundary_precision_check/material_event_deadline_is_inclusive_on_the_tenth_business_day
        """
        context = _setup_two_notices_sharing_one_deadline()

        set_clock("2026-09-16T00:00:00Z")
        submitted = submit(context["filing_a"]["id"], context["engagement"]["id"])
        assert submitted["submitted_at"][:10] == "2026-09-16"
        confirm(context["filing_a"]["id"], context["engagement"]["id"], "EMMA-TA-2026-0001")

        notice = read_notice(context["notice_a"]["id"])
        assert notice["status"] == "FILED_TIMELY"
        assert notice["days_late"] == 0
        assert notice["filed_filing_id"] == context["filing_a"]["id"]

    def test_submitting_one_calendar_day_past_the_deadline_is_late_by_one_day(self):
        """Just outside the boundary: a 2026-09-17 submission is FILED_LATE with days_late 1.

        PRD §3.5: "When the filing that carries the notice is confirmed, the notice is `FILED_TIMELY` if the date part of the filing's `submitted_at` is **less than or equal to** `filing_deadline_date` — a submission on the deadline date is timely — and `FILED_LATE` otherwise, with `days_late` set to the whole calendar days from `filing_deadline_date` to that submission date, floored at 0."
        Design: Difficulty/boundary_precision_check/material_event_deadline_is_inclusive_on_the_tenth_business_day
        """
        context = _setup_two_notices_sharing_one_deadline()

        set_clock("2026-09-17T00:00:00Z")
        submitted = submit(context["filing_b"]["id"], context["engagement"]["id"])
        assert submitted["submitted_at"][:10] == "2026-09-17"
        confirm(context["filing_b"]["id"], context["engagement"]["id"], "EMMA-TA-2026-0002")

        notice = read_notice(context["notice_b"]["id"])
        assert notice["status"] == "FILED_LATE"
        assert notice["days_late"] == 1
        assert notice["filed_filing_id"] == context["filing_b"]["id"]

    def test_both_sides_of_the_boundary_land_in_one_world_and_the_late_one_mints_no_failure(self):
        """The timely and the late notice coexist; the late one leaves every counter at zero.

        PRD §3.5: "**A late material-event filing mints no `FailureToFileEvent`.**"
        PRD §3.5: "A notice that is filed after its ten-business-day window closes lands in `FILED_LATE` and stops there; the undertaking's counters and risk score are untouched by it."
        Design: Difficulty/boundary_precision_check/material_event_deadline_is_inclusive_on_the_tenth_business_day
        """
        context = _setup_two_notices_sharing_one_deadline()

        set_clock("2026-09-16T00:00:00Z")
        submit(context["filing_a"]["id"], context["engagement"]["id"])
        confirm(context["filing_a"]["id"], context["engagement"]["id"], "EMMA-TA-2026-0001")

        set_clock("2026-09-17T00:00:00Z")
        submit(context["filing_b"]["id"], context["engagement"]["id"])
        confirm(context["filing_b"]["id"], context["engagement"]["id"], "EMMA-TA-2026-0002")

        assert read_notice(context["notice_a"]["id"])["status"] == "FILED_TIMELY"
        assert read_notice(context["notice_b"]["id"])["status"] == "FILED_LATE"

        rows, meta = validate_paginated(
            api_client.list_failure_events(
                make_officer_headers(OFFICER_PREPARER_ID),
                params={"undertaking_id": context["undertaking"]["id"], "limit": 100},
            )
        )
        assert meta["total_count"] == 0, "only the sweep's MISSED transition mints an event"
        assert rows == []

        undertaking = read_undertaking(context["undertaking"]["id"])
        assert undertaking["late_filing_count"] == 0
        assert undertaking["missed_event_count"] == 0
        assert_score(undertaking["disclosure_risk_score"], 0.00, "disclosure_risk_score")
        assert undertaking["remediation_tier"] == "TIER_0"
        assert undertaking["compliance_posture"] == "COMPLIANT"


_WAIVABLE_HALVES = [
    {
        "kind": "OPERATING_DATA_TABLE",
        "label": "Operating Data Tables",
        "weight_bp": 5000,
        "waivable": True,
    },
    {
        "kind": "BUDGET_SUMMARY",
        "label": "Adopted Budget Summary",
        "weight_bp": 5000,
        "waivable": True,
    },
]


def _setup_two_cycles_of_waivable_halves():
    """Two cycles on one undertaking whose two requirements are both waivable 5000-bp halves.

    Neither requirement is AUDITED_FINANCIALS, so `requires_audit_opinion` is false on
    both and the opinion multiplier is always 1.0.  Cycle A covers
    [2025-07-01, 2026-06-30) and both of its items are left NOT_STARTED; cycle B covers
    [2026-07-01, 2027-06-30), a gap rather than an overlap.  Items are located by their
    source requirement id, so no step depends on list ordering.
    """
    issue = create_bond_issue(
        issuer_program_code="SCHOOLDIST",
        series_designation="2019A",
        security_type="GENERAL_OBLIGATION",
        dated_date="2019-06-01",
        final_maturity_date="2049-06-01",
        original_par_amount_cents=100000000,
    )
    undertaking = create_undertaking(
        issue["id"],
        fiscal_year_end_month_day="06-30",
        filing_window_days=210,
        timeliness_basis="SUBMISSION_BASIS",
    )
    requirements = [
        create_content_requirement(undertaking["id"], **spec) for spec in _WAIVABLE_HALVES
    ]
    cycle_a = create_cycle(
        undertaking["id"],
        fiscal_year_label="FY2026",
        period_start_date="2025-07-01",
        period_end_date="2026-06-30",
    )
    items_a = list_content_items(cycle_a["id"])
    cycle_b = create_cycle(
        undertaking["id"],
        fiscal_year_label="FY2027",
        period_start_date="2026-07-01",
        period_end_date="2027-06-30",
    )
    items_b = list_content_items(cycle_b["id"])
    return {
        "issue": issue,
        "undertaking": undertaking,
        "operating_requirement": requirements[0],
        "budget_requirement": requirements[1],
        "cycle_a": cycle_a,
        "a_operating": item_for_requirement(items_a, requirements[0]["id"]),
        "a_budget": item_for_requirement(items_a, requirements[1]["id"]),
        "cycle_b": cycle_b,
        "b_operating": item_for_requirement(items_b, requirements[0]["id"]),
        "b_budget": item_for_requirement(items_b, requirements[1]["id"]),
    }


def _assemble_response(cycle_id):
    return api_client.assemble_cycle(cycle_id, make_officer_headers(OFFICER_ASSEMBLER_ID))


class TestAllWaivedCycleScoresOneHundredWithNoFileableContent:
    """The score ceiling seen from the wrong side: 100.00 is not the assembly gate."""

    def test_a_waived_item_keeps_its_full_weight_and_carries_the_cycle_to_fifty(self):
        """One WAIVED 5000-bp item plus one NOT_STARTED 5000-bp item scores exactly 50.00.

        PRD §3.3: "A waived item takes `readiness_factor` 1.0 and contributes its **full** weight to completeness."
        PRD §3.3: "First, each item's contribution is its `weight_bp_snapshot` divided by 10000, multiplied by its readiness factor, multiplied by its opinion multiplier, and that product is rounded half-up to **4 decimal places**."
        Design: Difficulty/boundary_precision_check/all_waived_cycle_scores_exactly_100_but_has_no_fileable_content
        """
        context = _setup_two_cycles_of_waivable_halves()

        assert context["a_operating"]["status"] == "NOT_STARTED"
        assert context["a_operating"]["weight_bp_snapshot"] == 5000
        assert_score(context["cycle_a"]["completeness_score_pct"], 0.00, "completeness_score_pct")

        waived = waive_item(
            context["a_operating"]["id"],
            waiver_reason="No enterprise operations during the period.",
        )
        assert waived["status"] == "WAIVED"
        assert float(waived["readiness_factor"]) == 1.0

        cycle = read_cycle(context["cycle_a"]["id"])
        assert_score(cycle["completeness_score_pct"], 50.00, "completeness_score_pct")

    def test_rung_twenty_five_fires_while_one_item_is_still_not_started(self):
        """Control that isolates the readiness rung: a half-waived cycle is CONTENT_NOT_READY.

        PRD §3.4: "Only then does content readiness come into play — every non-`VOID` item must be `READY` or `WAIVED`, and any item still `NOT_STARTED` or `DRAFT` yields `ERR_CONTENT_NOT_READY`."
        PRD §2.10: "Assembly readiness — every non-`VOID` content item of the cycle is `READY` or `WAIVED` → `ERR_CONTENT_NOT_READY` (409)."
        Design: Difficulty/boundary_precision_check/all_waived_cycle_scores_exactly_100_but_has_no_fileable_content
        """
        context = _setup_two_cycles_of_waivable_halves()

        waive_item(
            context["a_operating"]["id"],
            waiver_reason="No enterprise operations during the period.",
        )
        assert read_content_item(context["a_budget"]["id"])["status"] == "NOT_STARTED"

        validate_error(
            _assemble_response(context["cycle_a"]["id"]),
            ApiErrorId.ERR_CONTENT_NOT_READY.value,
        )
        assert read_cycle(context["cycle_a"]["id"])["status"] == "DRAFTING"

    def test_a_wholly_waived_cycle_scores_exactly_one_hundred_and_is_still_refused(self):
        """The boundary from the wrong side: 100.00 with no document is ERR_NO_FILEABLE_CONTENT.

        PRD §3.4: "Last comes the fileable-content floor: at least one non-`VOID` item must be `READY`, and a cycle whose every remaining item is `WAIVED` is refused with `ERR_NO_FILEABLE_CONTENT`."
        PRD §3.4: "That last check exists because a wholly waived cycle scores `completeness_score_pct` of 100.00 while carrying no document whatsoever; such a cycle belongs in `CLOSED_NOT_REQUIRED`, not in the repository, and the readiness check one rung above cannot see the difference."
        PRD §3.3: "Third, the sum is multiplied by 100 and rounded half-up to **2 decimal places** to give `completeness_score_pct`."
        Design: Difficulty/boundary_precision_check/all_waived_cycle_scores_exactly_100_but_has_no_fileable_content
        """
        context = _setup_two_cycles_of_waivable_halves()

        waive_item(
            context["a_operating"]["id"],
            waiver_reason="No enterprise operations during the period.",
        )
        second = waive_item(
            context["a_budget"]["id"],
            waiver_reason="No adopted budget summary produced.",
        )
        assert second["status"] == "WAIVED"

        cycle = read_cycle(context["cycle_a"]["id"])
        # Contributions 0.5000 + 0.5000 = 1.0000, so the score sits exactly at the ceiling.
        assert_score(cycle["completeness_score_pct"], 100.00, "completeness_score_pct")
        assert cycle["status"] == "DRAFTING"

        validate_error(
            _assemble_response(context["cycle_a"]["id"]),
            ApiErrorId.ERR_NO_FILEABLE_CONTENT.value,
        )

        after = read_cycle(context["cycle_a"]["id"])
        assert after["status"] == "DRAFTING", "the refused assemble left the cycle untouched"
        assert_score(after["completeness_score_pct"], 100.00, "completeness_score_pct")

    def test_one_ready_item_clears_the_floor_at_the_identical_one_hundred_score(self):
        """The same 100.00 from a READY-plus-WAIVED mix does assemble, so the score is not the gate.

        PRD §3.4: "Last comes the fileable-content floor: at least one non-`VOID` item must be `READY`, and a cycle whose every remaining item is `WAIVED` is refused with `ERR_NO_FILEABLE_CONTENT`."
        PRD §3.4: "A successful assembly stamps `assembled_by_user_id` from `X-User-ID` and `assembled_at` from the logical clock, and re-derives `completeness_score_pct`."
        Design: Difficulty/boundary_precision_check/all_waived_cycle_scores_exactly_100_but_has_no_fileable_content
        """
        context = _setup_two_cycles_of_waivable_halves()

        prepare_item(
            context["b_operating"]["id"],
            data_as_of_date="2027-06-30",
            source_document_ref="OPDATA-FY2027.pdf",
        )
        attested = attest_item(context["b_operating"]["id"])
        assert attested["status"] == "READY"

        waived = waive_item(
            context["b_budget"]["id"],
            waiver_reason="District publishes no separate adopted budget summary.",
        )
        assert waived["status"] == "WAIVED"

        assembled = assemble(context["cycle_b"]["id"])
        assert assembled["status"] == "READY_TO_FILE"
        assert assembled["assembled_by_user_id"] == OFFICER_ASSEMBLER_ID
        # The SAME score as the wholly waived cycle A, from a different item mix.
        assert_score(assembled["completeness_score_pct"], 100.00, "completeness_score_pct")
