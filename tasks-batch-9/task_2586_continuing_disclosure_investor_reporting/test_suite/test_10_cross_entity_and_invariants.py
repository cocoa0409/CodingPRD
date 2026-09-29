"""Cross-entity state dependencies, temporal overlap conventions and compensating invariants.

Every test in this module starts against an empty database whose logical clock reads
its startup value of 2026-08-01T00:00:00Z (PRD §2.5), because the harness restarts
the server before each test.
"""

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    annual_report_cycle_payload,
    acknowledge_calendar,
    api_client,
    assert_score,
    attest_item,
    classify_placement,
    confirm,
    create_annual_report_filing,
    create_bond_issue,
    create_cycle,
    create_engagement,
    create_event_filing,
    create_notice,
    create_official_statement,
    create_placement,
    create_undertaking,
    determine_notice,
    direct_placement_payload,
    item_for_requirement,
    list_content_items,
    list_cycles,
    list_failure_events,
    list_notices,
    list_placements,
    make_agent_headers,
    material_event_notice_payload,
    prepare_item,
    read_bond_issue,
    read_cycle,
    read_engagement,
    read_filing,
    read_notice,
    read_official_statement,
    read_undertaking,
    run_sweep,
    set_clock,
    setup_cycle_with_engagement,
    setup_issue_with_undertaking,
    setup_undertaking_with_requirements,
    submit,
    undertaking_payload,
    validate_error,
    validate_success,
    withdraw,
)

FD = TEST_USERS["finance_director_headers"]
OFFICER = TEST_USERS["disclosure_officer_headers"]
REVIEWER = TEST_USERS["compliance_reviewer_headers"]


# --------------------------------------------------------------------------- #
# Module-local composite preconditions (fixtures.py covers no equivalent chain)
# --------------------------------------------------------------------------- #

def _drafted_annual_report_with_engagement() -> dict:
    """A READY_TO_FILE cycle, an ACTIVE engagement acknowledged through 2026-07-01,
    and an ANNUAL_REPORT filing sitting in DRAFT."""
    context = setup_cycle_with_engagement(
        engagement={"last_calendar_ack_date": "2026-07-01"}
    )
    context["filing"] = create_annual_report_filing(
        context["issue"]["id"], context["cycle"]["id"]
    )
    return context


def _matured_issue_with_outstanding_sibling() -> dict:
    """Two issues in one credit program; the first has been swept to MATURED."""
    set_clock("2026-07-01T00:00:00Z")
    issue1 = create_bond_issue(
        issuer_program_code="WATERWORKS",
        series_designation="2011A",
        security_type="REVENUE",
        dated_date="2011-07-01",
        final_maturity_date="2026-07-15",
        original_par_amount_cents=100000000,
    )
    issue2 = create_bond_issue(
        issuer_program_code="WATERWORKS",
        series_designation="2026R",
        security_type="REVENUE",
        dated_date="2026-06-01",
        final_maturity_date="2056-06-01",
        original_par_amount_cents=60000000,
    )
    undertaking = create_undertaking(issue1["id"])
    notice = create_notice(
        issue1["id"], event_type="TRUSTEE_SUBSTITUTION", occurrence_date="2026-06-25"
    )
    statement = create_official_statement(
        issue1["id"],
        dated_date="2026-07-01",
        lookback_policy="STRICT_FIVE_YEAR",
        disclosed_event_ids=[],
    )
    set_clock("2026-08-01T00:00:00Z")
    sweep = run_sweep()
    return {
        "issue1": issue1,
        "issue2": issue2,
        "undertaking": undertaking,
        "notice": notice,
        "statement": statement,
        "sweep": sweep,
    }


def _undertaking_with_one_drafting_cycle() -> dict:
    """One undertaking whose only cycle covers the half-open period [2025-07-01, 2026-06-30)."""
    context = setup_undertaking_with_requirements(
        issue={
            "issuer_program_code": "PARKSDIST",
            "series_designation": "2017A",
            "security_type": "GENERAL_OBLIGATION",
            "dated_date": "2017-09-01",
            "final_maturity_date": "2047-09-01",
            "original_par_amount_cents": 100000000,
        }
    )
    context["cycle_a"] = create_cycle(
        context["undertaking"]["id"],
        fiscal_year_label="FY2026",
        period_start_date="2025-07-01",
        period_end_date="2026-06-30",
    )
    return context


def _create_cycle_raw(undertaking_id: str, label: str, start: str, end: str):
    return api_client.create_annual_report_cycle(
        annual_report_cycle_payload(
            undertaking_id,
            fiscal_year_label=label,
            period_start_date=start,
            period_end_date=end,
        ),
        OFFICER,
    )


def _issue_with_par_of_one_hundred_million() -> dict:
    """An OUTSTANDING issue whose outstanding par is exactly 100000000 cents."""
    return setup_issue_with_undertaking(
        issue={
            "issuer_program_code": "UTILITYSYS",
            "series_designation": "2023A",
            "security_type": "REVENUE",
            "dated_date": "2023-05-01",
            "final_maturity_date": "2053-05-01",
            "original_par_amount_cents": 100000000,
        }
    )


def _create_placement_raw(issue_id: str, **overrides):
    return api_client.create_direct_placement(
        direct_placement_payload(issue_id, **overrides), OFFICER
    )


def _undertaking_with_material_notice_baseline() -> dict:
    """Two requirements closing at 10000 bp plus one MATERIAL notice, so the
    undertaking's baseline open_obligation_count is 1 with no cycle in existence."""
    context = setup_undertaking_with_requirements(
        specs=[
            {
                "kind": "OPERATING_DATA_TABLE",
                "label": "Operating Data Tables",
                "weight_bp": 6000,
                "waivable": False,
            },
            {
                "kind": "BUDGET_SUMMARY",
                "label": "Adopted Budget Summary",
                "weight_bp": 4000,
                "waivable": False,
            },
        ],
        issue={
            "issuer_program_code": "LIBRARYDIST",
            "series_designation": "2024A",
            "security_type": "GENERAL_OBLIGATION",
            "dated_date": "2024-03-01",
            "final_maturity_date": "2054-03-01",
            "original_par_amount_cents": 100000000,
        },
    )
    notice = create_notice(
        context["issue"]["id"],
        event_type="TRUSTEE_SUBSTITUTION",
        occurrence_date="2026-07-28",
    )
    context["notice"] = determine_notice(
        notice["id"], "MATERIAL", determination_note="Successor trustee appointed."
    )
    context["undertaking"] = read_undertaking(context["undertaking"]["id"])
    return context


def _confirmed_material_event_filing() -> dict:
    """A BOND_CALL notice filed and CONFIRMED through an engagement whose retainer is 400000."""
    issue = create_bond_issue(
        issuer_program_code="HOSPAUTH",
        series_designation="2025A",
        security_type="REVENUE",
        dated_date="2025-01-01",
        final_maturity_date="2055-01-01",
        original_par_amount_cents=100000000,
    )
    undertaking = create_undertaking(issue["id"])
    engagement = create_engagement(
        undertaking["id"],
        agent_name="Summit Disclosure Agents",
        effective_date="2026-08-01",
        expiration_date="2027-12-31",
        retainer_cents=400000,
        last_calendar_ack_date="2026-08-01",
    )
    notice = create_notice(issue["id"], event_type="BOND_CALL", occurrence_date="2026-08-01")
    determine_notice(
        notice["id"], "MATERIAL", determination_note="Partial call of the 2025A term bonds."
    )
    filing = create_event_filing(issue["id"], notice["id"])
    submit(filing["id"], engagement["id"])
    confirmed = confirm(filing["id"], engagement["id"], "EMMA-HA-2026-0001")
    return {
        "issue": issue,
        "undertaking": undertaking,
        "engagement_id": engagement["id"],
        "engagement_at_creation": engagement,
        "notice": notice,
        "filing": confirmed,
    }


class TestFilingSubmissionGatedOnEngagementStatus:
    """PRD §3.7 / §3.10: only a third entity's status decides the identical submit."""

    def test_monitoring_lapse_sweep_suspends_only_the_engagement(self):
        """A 50-day lapse suspends the engagement while the cycle and the issue stay put.

        PRD §3.10: "`monitoring_lapse_days` is the whole calendar days from the later-of-nothing baseline — `last_calendar_ack_date` when it is set, and `effective_date` when it is null — to the logical clock's date, floored at 0."
        PRD §3.10: "Suspension is a sweep-only transition and fires when `monitoring_lapse_days` is **strictly greater than** 45, so a lapse of exactly 45 days is still compliant while 46 days suspends."
        PRD §3.11: "Every `DisseminationEngagement` in `status` `ACTIVE` whose refreshed `monitoring_lapse_days` exceeds 45 moves to `SUSPENDED`."
        PRD §3.11: "It reports `swept_at`, the logical-clock instant of the sweep, alongside five counts: `matured_issue_count` for step 1, `delinquent_cycle_count` for step 2, `missed_event_count` for step 3, `suspended_engagement_count` for step 4, and `failure_event_created_count` for every `FailureToFileEvent` minted across steps 2 and 3 together."
        Design: Difficulty/cross_entity_state_dependency/filing_submission_gated_on_engagement_status_with_calendar_ack_as_the_cure
        """
        context = _drafted_annual_report_with_engagement()
        engagement = read_engagement(context["engagement"]["id"])
        assert engagement["status"] == "ACTIVE"
        assert engagement["monitoring_lapse_days"] == 31
        assert context["filing"]["status"] == "DRAFT"
        assert context["filing"]["submission_attempt_count"] == 0

        set_clock("2026-08-20T00:00:00Z")
        sweep = run_sweep()

        assert sweep["suspended_engagement_count"] == 1
        assert sweep["delinquent_cycle_count"] == 0
        assert sweep["matured_issue_count"] == 0

        engagement = read_engagement(context["engagement"]["id"])
        assert engagement["status"] == "SUSPENDED"
        assert engagement["monitoring_lapse_days"] == 50
        assert read_cycle(context["cycle"]["id"])["status"] == "READY_TO_FILE"
        assert read_bond_issue(context["issue"]["id"])["status"] == "OUTSTANDING"

    def test_the_cycle_due_date_is_the_filing_window_rolled_to_a_business_day(self):
        """A period ending 2026-06-30 plus a 210-day window is due 2027-01-26.

        PRD §3.3: "Take the cycle's own `period_end_date`, advance it by the owning undertaking's `filing_window_days` in **calendar** days, then roll the result forward — never backward — to the first business day at or after it, using the calendar of §2.6."
        Design: Difficulty/cross_entity_state_dependency/filing_submission_gated_on_engagement_status_with_calendar_ack_as_the_cure
        """
        context = _drafted_annual_report_with_engagement()

        cycle = read_cycle(context["cycle"]["id"])

        assert cycle["period_end_date"] == "2026-06-30"
        assert cycle["due_date"] == "2027-01-26"

    def test_submit_through_a_suspended_engagement_is_refused_and_burns_no_attempt(self):
        """The refusal is ERR_ENGAGEMENT_NOT_ACTIVE and the DRAFT filing is untouched.

        PRD §3.7: "The filing must be `DRAFT`; the acting `X-User-ID` must resolve to a `DisseminationEngagement` whose `undertaking_id` is the undertaking of the filing's issue, failing which the call is refused with `ERR_AGENT_NOT_ENGAGED`; that engagement's `status` must be `ACTIVE`, failing which the call is refused with `ERR_ENGAGEMENT_NOT_ACTIVE`; and the submission must not be the fourth attempt on this filing, since at most three submissions and resubmissions are permitted in total and the fourth is refused with `ERR_SUBMISSION_ATTEMPTS_EXHAUSTED`."
        PRD §3.10: "A `SUSPENDED` engagement can no longer submit or resubmit filings, and any attempt is refused with `ERR_ENGAGEMENT_NOT_ACTIVE`."
        Design: Difficulty/cross_entity_state_dependency/filing_submission_gated_on_engagement_status_with_calendar_ack_as_the_cure
        """
        context = _drafted_annual_report_with_engagement()
        engagement_id = context["engagement"]["id"]
        filing_id = context["filing"]["id"]
        set_clock("2026-08-20T00:00:00Z")
        run_sweep()

        response = api_client.submit_filing(filing_id, make_agent_headers(engagement_id))

        validate_error(response, ApiErrorId.ERR_ENGAGEMENT_NOT_ACTIVE.value)
        filing = read_filing(filing_id)
        assert filing["status"] == "DRAFT"
        assert filing["submission_attempt_count"] == 0
        assert filing["submitted_at"] is None
        assert read_cycle(context["cycle"]["id"])["status"] == "READY_TO_FILE"

    def test_calendar_acknowledgement_cures_the_suspension_and_the_same_submit_succeeds(self):
        """The cure runs through the one endpoint a SUSPENDED engagement may still call.

        PRD §3.10: "From `ACTIVE` it is a self-loop that resets the lapse clock; from `SUSPENDED` it is the cure that restores the engagement to `ACTIVE` and re-enables submissions."
        PRD §3.7: "A successful submission sets `submitted_at` from the logical clock, `submitted_by_user_id` from `X-User-ID`, `submitting_engagement_id` to the resolved engagement, and raises `submission_attempt_count` by 1."
        PRD §3.7: "It then advances the subject: an `ANNUAL_REPORT` filing drives its cycle from `READY_TO_FILE` to `FILING_IN_PROGRESS`, and a `MATERIAL_EVENT_NOTICE` filing drives its notice from `MATERIAL` to `FILING_IN_PROGRESS`."
        Design: Difficulty/cross_entity_state_dependency/filing_submission_gated_on_engagement_status_with_calendar_ack_as_the_cure
        """
        context = _drafted_annual_report_with_engagement()
        engagement_id = context["engagement"]["id"]
        filing_id = context["filing"]["id"]
        set_clock("2026-08-20T00:00:00Z")
        run_sweep()
        validate_error(
            api_client.submit_filing(filing_id, make_agent_headers(engagement_id)),
            ApiErrorId.ERR_ENGAGEMENT_NOT_ACTIVE.value,
        )

        cured = acknowledge_calendar(engagement_id, "2026-08-20")

        assert cured["status"] == "ACTIVE"
        assert cured["monitoring_lapse_days"] == 0
        assert cured["last_calendar_ack_date"] == "2026-08-20"

        submitted = validate_success(
            api_client.submit_filing(filing_id, make_agent_headers(engagement_id))
        )

        assert submitted["status"] == "SUBMITTED"
        assert submitted["submission_attempt_count"] == 1
        # PRD §2.4 fixes the timestamp format at three fractional digits; PRD §2.5
        # stamps `submitted_at` from the logical clock, here set to 2026-08-20T00:00:00Z.
        assert submitted["submitted_at"] == "2026-08-20T00:00:00.000Z"
        assert submitted["submitting_engagement_id"] == engagement_id
        assert read_cycle(context["cycle"]["id"])["status"] == "FILING_IN_PROGRESS"


class TestIssueGateAfterTheMaturitySweep:
    """PRD §2.10 rule 9: an ancestor issue that has left OUTSTANDING blocks its descendants."""

    def test_maturity_sweep_terminates_the_undertaking_and_voids_the_pending_notice(self):
        """Step 1 matures the issue, zeroes par, terminates the undertaking and voids the notice.

        PRD §3.11: "Every `BondIssue` in `status` `OUTSTANDING` whose `final_maturity_date` is strictly before the logical clock's date moves to `MATURED`, its `outstanding_par_amount_cents` is set to 0, its `matured_at` is stamped from the clock, and it fires the same four-hop termination cascade as defeasance with `termination_cause` `MATURITY`: the undertaking to `TERMINATED`, its non-terminal cycles to `CLOSED_NOT_REQUIRED`, its non-`TERMINATED` engagements to `TERMINATED` with `termination_reason` `UNDERTAKING_TERMINATED`, and the non-`VOID` content items of those cycles to `VOID`."
        PRD §3.11: "Every `DETERMINATION_PENDING` or `MATERIAL` notice on the issue is voided."
        PRD §3.11: "Unlike defeasance, maturity mints no notice of its own."
        PRD §3.11: "A notice still in `DETERMINATION_PENDING` is not swept, and a notice determined `NOT_MATERIAL` is skipped permanently."
        Design: Difficulty/cross_entity_state_dependency/notice_and_review_creation_gated_on_issue_outstanding_after_maturity_sweep
        """
        context = _matured_issue_with_outstanding_sibling()

        assert context["notice"]["status"] == "DETERMINATION_PENDING"
        assert context["statement"]["status"] == "DRAFT"
        assert context["sweep"]["matured_issue_count"] == 1
        assert context["sweep"]["missed_event_count"] == 0

        issue1 = read_bond_issue(context["issue1"]["id"])
        assert issue1["status"] == "MATURED"
        assert issue1["outstanding_par_amount_cents"] == 0
        assert issue1["open_material_event_count"] == 0

        undertaking = read_undertaking(context["undertaking"]["id"])
        assert undertaking["status"] == "TERMINATED"
        assert undertaking["termination_cause"] == "MATURITY"

        assert read_notice(context["notice"]["id"])["status"] == "VOID"
        assert len(list_notices(issue_id=context["issue1"]["id"])) == 1

    def test_opening_a_notice_on_a_matured_issue_is_refused_but_the_sibling_accepts_it(self):
        """The refusal is about the ancestor's state, not about the payload.

        PRD §2.10: "Issue gate — the `BondIssue` that owns the target row is `OUTSTANDING` → `ERR_ISSUE_NOT_OUTSTANDING` (409). Applies to `POST /disclosure/undertakings`, `POST /disclosure/annual-report-cycles`, `POST /disclosure/material-event-notices`, `POST /disclosure/direct-placements`, `POST /disclosure/filings`, and `POST /disclosure/official-statements/{id}/compliance-review`."
        PRD §3.5: "And `filing_deadline_date` is the **tenth business day strictly after** `occurrence_date`, computed with the add-business-days rule of §2.6: the occurrence date itself is never counted whether or not it is a business day, and the result is the tenth business day encountered walking forward."
        Design: Difficulty/cross_entity_state_dependency/notice_and_review_creation_gated_on_issue_outstanding_after_maturity_sweep
        """
        context = _matured_issue_with_outstanding_sibling()

        refused = api_client.create_material_event_notice(
            material_event_notice_payload(
                context["issue1"]["id"],
                event_type="UNSCHEDULED_DRAW_ON_RESERVE",
                occurrence_date="2026-07-28",
            ),
            OFFICER,
        )
        validate_error(refused, ApiErrorId.ERR_ISSUE_NOT_OUTSTANDING.value)

        accepted = validate_success(
            api_client.create_material_event_notice(
                material_event_notice_payload(
                    context["issue2"]["id"],
                    event_type="UNSCHEDULED_DRAW_ON_RESERVE",
                    occurrence_date="2026-07-28",
                ),
                OFFICER,
            ),
            201,
        )

        assert accepted["status"] == "DETERMINATION_PENDING"
        assert accepted["filing_deadline_date"] == "2026-08-11"

    def test_compliance_review_on_a_matured_issue_is_refused_and_leaves_the_statement_in_draft(self):
        """The same priority-9 rule reaches the official-statement review endpoint.

        PRD §3.9: "**Compliance review** is the `ComplianceReviewer`'s act and is a repeatable self-loop: it is available from `DRAFT` and from `COMPLIANCE_REVIEW`, and it requires the statement's issue to be `OUTSTANDING`, failing which it is refused with `ERR_ISSUE_NOT_OUTSTANDING`."
        Design: Difficulty/cross_entity_state_dependency/notice_and_review_creation_gated_on_issue_outstanding_after_maturity_sweep
        """
        context = _matured_issue_with_outstanding_sibling()

        refused = api_client.review_official_statement(
            context["statement"]["id"], REVIEWER, {"disclosed_event_ids": []}
        )

        validate_error(refused, ApiErrorId.ERR_ISSUE_NOT_OUTSTANDING.value)
        statement = read_official_statement(context["statement"]["id"])
        assert statement["status"] == "DRAFT"
        assert statement["disclosure_adequacy"] == "UNKNOWN"
        assert statement["reviewed_by_user_id"] is None

    def test_the_issue_gate_outranks_the_duplicate_undertaking_guard(self):
        """A body that violates rules 9 and 14 at once reports the lower-numbered rule.

        PRD §2.10: "Checks are evaluated in a single strictly ordered ladder, and the **first** rule that fails is the **only** error returned."
        PRD §2.10: "Issue gate — the `BondIssue` that owns the target row is `OUTSTANDING` → `ERR_ISSUE_NOT_OUTSTANDING` (409). Applies to `POST /disclosure/undertakings`, `POST /disclosure/annual-report-cycles`, `POST /disclosure/material-event-notices`, `POST /disclosure/direct-placements`, `POST /disclosure/filings`, and `POST /disclosure/official-statements/{id}/compliance-review`."
        PRD §2.10: "At most one `Undertaking` per `issue_id`, in any status → `ERR_UNDERTAKING_ALREADY_EXISTS` (409). Applies to `POST /disclosure/undertakings`."
        Design: Difficulty/cross_entity_state_dependency/notice_and_review_creation_gated_on_issue_outstanding_after_maturity_sweep
        """
        context = _matured_issue_with_outstanding_sibling()

        refused = api_client.create_undertaking(
            undertaking_payload(
                context["issue1"]["id"],
                fiscal_year_end_month_day="12-31",
                filing_window_days=210,
                timeliness_basis="SUBMISSION_BASIS",
            ),
            FD,
        )

        validate_error(refused, ApiErrorId.ERR_ISSUE_NOT_OUTSTANDING.value)


class TestReportingPeriodsAreHalfOpen:
    """PRD §3.3: [start, end) intervals, so exact adjacency is legal."""

    def test_a_period_starting_one_day_before_the_incumbents_end_is_refused(self):
        """[2026-06-29, 2027-06-29) intrudes into the live cycle's half-open interval.

        PRD §3.3: "A new cycle is refused with `ERR_REPORTING_PERIOD_OVERLAP` when its start falls strictly before an existing cycle's end **and** that existing cycle's start falls strictly before the new cycle's end, considering only existing cycles of the same undertaking whose `status` is neither `WITHDRAWN` nor `CLOSED_NOT_REQUIRED`."
        Design: Difficulty/resource_temporal_overlap/reporting_periods_are_half_open_so_exact_adjacency_is_legal
        """
        context = _undertaking_with_one_drafting_cycle()
        assert context["cycle_a"]["status"] == "DRAFTING"

        refused = _create_cycle_raw(
            context["undertaking"]["id"], "FY2027-EARLY", "2026-06-29", "2027-06-29"
        )

        validate_error(refused, ApiErrorId.ERR_REPORTING_PERIOD_OVERLAP.value)
        assert len(list_cycles(undertaking_id=context["undertaking"]["id"])) == 1

    def test_a_period_starting_exactly_on_the_incumbents_end_date_is_accepted(self):
        """The legal boundary case: neither strict inequality holds at exact adjacency.

        PRD §3.3: "Exact adjacency — a new cycle beginning on the very day an existing cycle's `period_end_date` falls — is therefore permitted, since neither strict inequality holds."
        PRD §3.3: "Take the cycle's own `period_end_date`, advance it by the owning undertaking's `filing_window_days` in **calendar** days, then roll the result forward — never backward — to the first business day at or after it, using the calendar of §2.6."
        Design: Difficulty/resource_temporal_overlap/reporting_periods_are_half_open_so_exact_adjacency_is_legal
        """
        context = _undertaking_with_one_drafting_cycle()

        cycle_b = validate_success(
            _create_cycle_raw(
                context["undertaking"]["id"], "FY2027", "2026-06-30", "2027-06-30"
            ),
            201,
        )

        assert cycle_b["status"] == "DRAFTING"
        assert cycle_b["due_date"] == "2028-01-26"
        assert len(list_cycles(undertaking_id=context["undertaking"]["id"])) == 2

    def test_the_identical_period_of_a_live_cycle_is_refused(self):
        """A byte-identical period is the strongest form of overlap.

        PRD §3.3: "A new cycle is refused with `ERR_REPORTING_PERIOD_OVERLAP` when its start falls strictly before an existing cycle's end **and** that existing cycle's start falls strictly before the new cycle's end, considering only existing cycles of the same undertaking whose `status` is neither `WITHDRAWN` nor `CLOSED_NOT_REQUIRED`."
        Design: Difficulty/resource_temporal_overlap/reporting_periods_are_half_open_so_exact_adjacency_is_legal
        """
        context = _undertaking_with_one_drafting_cycle()

        refused = _create_cycle_raw(
            context["undertaking"]["id"], "FY2026-DUP", "2025-07-01", "2026-06-30"
        )

        validate_error(refused, ApiErrorId.ERR_REPORTING_PERIOD_OVERLAP.value)

    def test_withdrawing_a_cycle_frees_its_period_for_a_byte_identical_recreation(self):
        """WITHDRAWN cycles leave the overlap set, so the refused period becomes available.

        PRD §3.3: "A new cycle is refused with `ERR_REPORTING_PERIOD_OVERLAP` when its start falls strictly before an existing cycle's end **and** that existing cycle's start falls strictly before the new cycle's end, considering only existing cycles of the same undertaking whose `status` is neither `WITHDRAWN` nor `CLOSED_NOT_REQUIRED`."
        PRD §3.4: "Every `CycleContentItem` of the cycle whose `status` is `NOT_STARTED`, `DRAFT`, `READY`, or `WAIVED` moves to `VOID` in ascending `created_at` order, each with `readiness_factor` driven to 0.0."
        Design: Difficulty/resource_temporal_overlap/reporting_periods_are_half_open_so_exact_adjacency_is_legal
        """
        context = _undertaking_with_one_drafting_cycle()
        cycle_a_id = context["cycle_a"]["id"]
        validate_error(
            _create_cycle_raw(
                context["undertaking"]["id"], "FY2026-DUP", "2025-07-01", "2026-06-30"
            ),
            ApiErrorId.ERR_REPORTING_PERIOD_OVERLAP.value,
        )

        withdrawn = withdraw(cycle_a_id, "Opened against the wrong fiscal year label.")

        assert withdrawn["status"] == "WITHDRAWN"
        assert [item["status"] for item in list_content_items(cycle_a_id)] == ["VOID"]

        cycle_c = validate_success(
            _create_cycle_raw(
                context["undertaking"]["id"], "FY2026-REDO", "2025-07-01", "2026-06-30"
            ),
            201,
        )

        assert cycle_c["status"] == "DRAFTING"
        assert cycle_c["due_date"] == "2027-01-26"

    def test_the_overlap_set_is_the_currently_occupied_calendar(self):
        """After the withdrawal the same intruding period still collides, now with cycle B.

        PRD §3.3: "A new cycle is refused with `ERR_REPORTING_PERIOD_OVERLAP` when its start falls strictly before an existing cycle's end **and** that existing cycle's start falls strictly before the new cycle's end, considering only existing cycles of the same undertaking whose `status` is neither `WITHDRAWN` nor `CLOSED_NOT_REQUIRED`."
        PRD §3.4: "**Withdrawal** is the compensating operation for cycle creation, used when a cycle was opened in error."
        Design: Difficulty/resource_temporal_overlap/reporting_periods_are_half_open_so_exact_adjacency_is_legal
        """
        context = _undertaking_with_one_drafting_cycle()
        undertaking_id = context["undertaking"]["id"]
        validate_success(
            _create_cycle_raw(undertaking_id, "FY2027", "2026-06-30", "2027-06-30"), 201
        )
        withdraw(context["cycle_a"]["id"], "Opened against the wrong fiscal year label.")
        validate_success(
            _create_cycle_raw(undertaking_id, "FY2026-REDO", "2025-07-01", "2026-06-30"), 201
        )

        refused = _create_cycle_raw(
            undertaking_id, "FY2027-EARLY-2", "2026-06-29", "2027-06-29"
        )

        validate_error(refused, ApiErrorId.ERR_REPORTING_PERIOD_OVERLAP.value)
        assert len(list_cycles(undertaking_id=undertaking_id)) == 3


class TestPlacementReviewWindowsAreClosedIntervals:
    """PRD §3.6: [start, end] inclusive, with an aggregate capacity of two per date."""

    def test_the_materiality_ratio_is_pinned_from_both_sides_of_the_five_hundred_bp_boundary(self):
        """4990000 of 100000000 is 499 bp; 5000000 is exactly 500 bp; both open at RECEIVED.

        PRD §2.7: "`materiality_ratio_bp` is an integer number of basis points."
        PRD §3.1: "The `outstanding_par_amount_cents` figure matters downstream because it is the denominator of the direct-placement materiality ratio and the escrow yardstick for a legal defeasance."
        PRD §3.6: "`materiality_ratio_bp` is derived once, at creation, as `principal_amount_cents` multiplied by 10000, divided by the issue's `outstanding_par_amount_cents`, rounded half-up to a whole basis point."
        PRD §3.6: "The placement opens at `status` `RECEIVED`, `version` 1, with `linked_notice_id` and `waiver_reason` null."
        Design: Difficulty/resource_temporal_overlap/placement_review_windows_are_closed_intervals_with_aggregate_capacity_two
        """
        context = _issue_with_par_of_one_hundred_million()
        assert context["issue"]["outstanding_par_amount_cents"] == 100000000

        placement_one = create_placement(
            context["issue"]["id"],
            lender_name="First Meridian Bank",
            principal_amount_cents=4990000,
            execution_date="2026-08-05",
            review_window_start_date="2026-08-10",
            review_window_end_date="2026-08-20",
            disclosure_practice="VOLUNTARY",
        )
        placement_two = create_placement(
            context["issue"]["id"],
            lender_name="Cascade Trust Company",
            principal_amount_cents=5000000,
            execution_date="2026-08-06",
            review_window_start_date="2026-08-15",
            review_window_end_date="2026-08-25",
            disclosure_practice="VOLUNTARY",
        )

        assert placement_one["materiality_ratio_bp"] == 499
        assert placement_one["status"] == "RECEIVED"
        assert placement_one["linked_notice_id"] is None
        assert placement_one["waiver_reason"] is None
        assert placement_two["materiality_ratio_bp"] == 500
        assert placement_two["status"] == "RECEIVED"

    def test_a_third_cover_of_a_single_calendar_date_is_refused(self):
        """P3 starts on the last day of P1's closed window, so 2026-08-20 would be covered thrice.

        PRD §3.6: "The review window models the finance office's own capacity to assess obligations, and it is a **closed** interval: `review_window_start_date` and `review_window_end_date` are both inclusive, so two windows that merely touch on a single day do overlap."
        PRD §3.6: "At most two placements whose `status` is not `DISCLOSED` may cover any single calendar date on the same issue."
        PRD §3.6: "The check is aggregate rather than pairwise — each existing placement is individually legal, and it is the third one covering some shared date that is refused, with `ERR_PLACEMENT_REVIEW_CAPACITY_EXCEEDED`."
        Design: Difficulty/resource_temporal_overlap/placement_review_windows_are_closed_intervals_with_aggregate_capacity_two
        """
        context = _issue_with_par_of_one_hundred_million()
        issue_id = context["issue"]["id"]
        create_placement(
            issue_id,
            lender_name="First Meridian Bank",
            principal_amount_cents=4990000,
            execution_date="2026-08-05",
            review_window_start_date="2026-08-10",
            review_window_end_date="2026-08-20",
        )
        create_placement(
            issue_id,
            lender_name="Cascade Trust Company",
            principal_amount_cents=5000000,
            execution_date="2026-08-06",
            review_window_start_date="2026-08-15",
            review_window_end_date="2026-08-25",
        )

        refused = _create_placement_raw(
            issue_id,
            lender_name="Northbank Capital",
            principal_amount_cents=3000000,
            execution_date="2026-08-07",
            review_window_start_date="2026-08-20",
            review_window_end_date="2026-08-30",
        )

        validate_error(refused, ApiErrorId.ERR_PLACEMENT_REVIEW_CAPACITY_EXCEEDED.value)
        assert len(list_placements(issue_id=issue_id)) == 2

    def test_starting_one_day_after_the_closed_window_ends_leaves_a_cover_of_two(self):
        """Shifting the start to 2026-08-21 clears P1 entirely, so the placement is accepted.

        PRD §3.6: "The review window models the finance office's own capacity to assess obligations, and it is a **closed** interval: `review_window_start_date` and `review_window_end_date` are both inclusive, so two windows that merely touch on a single day do overlap."
        PRD §3.6: "At most two placements whose `status` is not `DISCLOSED` may cover any single calendar date on the same issue."
        PRD §3.6: "`materiality_ratio_bp` is derived once, at creation, as `principal_amount_cents` multiplied by 10000, divided by the issue's `outstanding_par_amount_cents`, rounded half-up to a whole basis point."
        Design: Difficulty/resource_temporal_overlap/placement_review_windows_are_closed_intervals_with_aggregate_capacity_two
        """
        context = _issue_with_par_of_one_hundred_million()
        issue_id = context["issue"]["id"]
        create_placement(
            issue_id,
            lender_name="First Meridian Bank",
            principal_amount_cents=4990000,
            execution_date="2026-08-05",
            review_window_start_date="2026-08-10",
            review_window_end_date="2026-08-20",
        )
        create_placement(
            issue_id,
            lender_name="Cascade Trust Company",
            principal_amount_cents=5000000,
            execution_date="2026-08-06",
            review_window_start_date="2026-08-15",
            review_window_end_date="2026-08-25",
        )
        validate_error(
            _create_placement_raw(
                issue_id,
                lender_name="Northbank Capital",
                principal_amount_cents=3000000,
                execution_date="2026-08-07",
                review_window_start_date="2026-08-20",
                review_window_end_date="2026-08-30",
            ),
            ApiErrorId.ERR_PLACEMENT_REVIEW_CAPACITY_EXCEEDED.value,
        )

        placement_four = validate_success(
            _create_placement_raw(
                issue_id,
                lender_name="Northbank Capital",
                principal_amount_cents=3000000,
                execution_date="2026-08-07",
                review_window_start_date="2026-08-21",
                review_window_end_date="2026-08-31",
            ),
            201,
        )

        assert placement_four["status"] == "RECEIVED"
        assert placement_four["materiality_ratio_bp"] == 300
        assert len(list_placements(issue_id=issue_id)) == 3

    def test_four_hundred_ninety_nine_bp_takes_the_waived_fork_and_mints_no_notice(self):
        """Strictly below 500 bp with practice VOLUNTARY waives disclosure and moves no counter.

        PRD §3.6: "Otherwise — ratio strictly below 500 basis points **and** `disclosure_practice` not `MANDATORY_MATERIAL_EVENT` — the placement becomes `DISCLOSURE_WAIVED`, which requires a `waiver_reason` in the body and is refused with `ERR_WAIVER_REASON_REQUIRED` without one."
        PRD §3.6: "The waived branch creates no notice, leaves `linked_notice_id` null, and moves no counter at all."
        Design: Difficulty/resource_temporal_overlap/placement_review_windows_are_closed_intervals_with_aggregate_capacity_two
        """
        context = _issue_with_par_of_one_hundred_million()
        issue_id = context["issue"]["id"]
        placement_one = create_placement(
            issue_id,
            lender_name="First Meridian Bank",
            principal_amount_cents=4990000,
            execution_date="2026-08-05",
            review_window_start_date="2026-08-10",
            review_window_end_date="2026-08-20",
        )
        assert placement_one["materiality_ratio_bp"] == 499

        classified = classify_placement(
            placement_one["id"],
            waiver_reason="499 bp of outstanding par; below the 500 bp materiality threshold.",
        )

        assert classified["status"] == "DISCLOSURE_WAIVED"
        assert classified["linked_notice_id"] is None
        assert list_notices(issue_id=issue_id) == []
        assert read_bond_issue(issue_id)["open_material_event_count"] == 0
        assert read_undertaking(context["undertaking"]["id"])["open_obligation_count"] == 0

    def test_exactly_five_hundred_bp_mints_a_financial_obligation_notice(self):
        """The boundary is inclusive, so 500 bp takes the disclosure fork and mints the notice.

        PRD §3.6: "The placement becomes `DISCLOSURE_REQUIRED` when `materiality_ratio_bp` is **greater than or equal to** 500, or when `disclosure_practice` is `MANDATORY_MATERIAL_EVENT` regardless of the ratio."
        PRD §3.6: "That branch mints a `MaterialEventNotice` with `event_type` `FINANCIAL_OBLIGATION_INCURRENCE`, `issue_id` copied from the placement, `occurrence_date` set to the placement's `execution_date`, `financial_obligation_ref` pointing back at the placement, `per_se_material` false, and `status` `DETERMINATION_PENDING`, with its own `filing_deadline_date` ten business days after that occurrence date; the new notice's id is stored in `linked_notice_id`, and the issue's `open_material_event_count` and the undertaking's `open_obligation_count` are both re-derived."
        Design: Difficulty/resource_temporal_overlap/placement_review_windows_are_closed_intervals_with_aggregate_capacity_two
        """
        context = _issue_with_par_of_one_hundred_million()
        issue_id = context["issue"]["id"]
        placement_two = create_placement(
            issue_id,
            lender_name="Cascade Trust Company",
            principal_amount_cents=5000000,
            execution_date="2026-08-06",
            review_window_start_date="2026-08-15",
            review_window_end_date="2026-08-25",
            disclosure_practice="VOLUNTARY",
        )
        assert placement_two["materiality_ratio_bp"] == 500

        classified = classify_placement(placement_two["id"])

        assert classified["status"] == "DISCLOSURE_REQUIRED"
        minted = list_notices(financial_obligation_ref=placement_two["id"])
        assert len(minted) == 1
        notice = minted[0]
        assert classified["linked_notice_id"] == notice["id"]
        assert notice["issue_id"] == issue_id
        assert notice["event_type"] == "FINANCIAL_OBLIGATION_INCURRENCE"
        assert notice["occurrence_date"] == "2026-08-06"
        assert notice["filing_deadline_date"] == "2026-08-20"
        assert notice["per_se_material"] is False
        assert notice["status"] == "DETERMINATION_PENDING"


class TestCycleWithdrawalRestoresTheObligationCount:
    """PRD §3.4: withdrawal is the compensating operation for cycle creation."""

    def test_a_material_notice_alone_holds_the_obligation_baseline_at_one(self):
        """The counter is fed by open notices as well as open cycles, so it reads 1 with no cycle.

        PRD §3.2: "All four counters — `late_filing_count`, `missed_event_count`, `delinquent_cycle_count`, and `open_obligation_count` — start at 0, and so does `content_weight_bp_total`."
        PRD §3.5: "Creation also re-derives the issue's `open_material_event_count` and the undertaking's `open_obligation_count`, because a `DETERMINATION_PENDING` notice is an open obligation."
        PRD §3.5: "A `MATERIAL` determination leaves the notice in the open set — `open_material_event_count` and `open_obligation_count` are unchanged, the notice becomes fileable, and it remains exposed to the sweep that can strand it as `MISSED`."
        PRD §3.2: "Each accepted requirement re-derives the undertaking's `content_weight_bp_total` as the sum of `weight_bp` across all of that undertaking's requirements, which is the figure the weight-closure gate of §3.3 tests."
        Design: Difficulty/compensating_invariant/cycle_withdrawal_restores_the_open_obligation_count_exactly
        """
        context = _undertaking_with_material_notice_baseline()

        assert context["notice"]["status"] == "MATERIAL"
        assert context["undertaking"]["open_obligation_count"] == 1
        assert context["undertaking"]["content_weight_bp_total"] == 10000
        assert list_cycles(undertaking_id=context["undertaking"]["id"]) == []

    def test_opening_a_cycle_snapshots_the_weights_and_raises_the_count_to_two(self):
        """The new DRAFTING cycle joins the still-open notice in the obligation set.

        PRD §3.3: "One **`CycleContentItem`** is minted for each `ContentRequirement` of the undertaking, each carrying the `cycle_id` of the new cycle, the `content_requirement_id` of its source requirement, `status` `NOT_STARTED`, `readiness_factor` 0.0, and a `weight_bp_snapshot` copied from the requirement's `weight_bp` at that instant."
        PRD §3.3: "The cycle itself opens in `status` `DRAFTING` with `version` 1, `completeness_score_pct` 0.00, `days_late` 0, and null `assembled_by_user_id`, `assembled_at`, `filed_filing_id`, `filed_at`, `timeliness_basis_applied`, and `withdrawal_reason`."
        PRD §3.3: "The undertaking's `open_obligation_count` is re-derived, and the new cycle raises it."
        Design: Difficulty/compensating_invariant/cycle_withdrawal_restores_the_open_obligation_count_exactly
        """
        context = _undertaking_with_material_notice_baseline()
        requirements = context["requirements"]

        cycle = create_cycle(
            context["undertaking"]["id"],
            fiscal_year_label="FY2026",
            period_start_date="2025-07-01",
            period_end_date="2026-06-30",
        )

        assert cycle["status"] == "DRAFTING"
        assert_score(cycle["completeness_score_pct"], 0.00, "completeness_score_pct at creation")
        items = list_content_items(cycle["id"])
        item_one = item_for_requirement(items, requirements[0]["id"])
        item_two = item_for_requirement(items, requirements[1]["id"])
        assert item_one["weight_bp_snapshot"] == 6000
        assert item_two["weight_bp_snapshot"] == 4000
        assert read_undertaking(context["undertaking"]["id"])["open_obligation_count"] == 2

    def test_attesting_the_six_thousand_bp_item_scores_the_cycle_at_sixty(self):
        """One READY 6000-bp item plus one NOT_STARTED 4000-bp item scores 60.00.

        PRD §3.3: "First, each item's contribution is its `weight_bp_snapshot` divided by 10000, multiplied by its readiness factor, multiplied by its opinion multiplier, and that product is rounded half-up to **4 decimal places**."
        PRD §3.3: "Third, the sum is multiplied by 100 and rounded half-up to **2 decimal places** to give `completeness_score_pct`."
        PRD §3.3: "The opinion multiplier is 1.0 whenever the item's `ContentRequirement` has `requires_audit_opinion` false, regardless of what `audit_opinion_type` holds."
        Design: Difficulty/compensating_invariant/cycle_withdrawal_restores_the_open_obligation_count_exactly
        """
        context = _undertaking_with_material_notice_baseline()
        cycle = create_cycle(
            context["undertaking"]["id"],
            fiscal_year_label="FY2026",
            period_start_date="2025-07-01",
            period_end_date="2026-06-30",
        )
        item_one = item_for_requirement(
            list_content_items(cycle["id"]), context["requirements"][0]["id"]
        )

        drafted = prepare_item(
            item_one["id"],
            data_as_of_date="2026-06-30",
            source_document_ref="OPDATA-FY2026.pdf",
        )
        assert drafted["status"] == "DRAFT"

        attested = attest_item(item_one["id"])
        assert attested["status"] == "READY"
        assert_score(
            read_cycle(cycle["id"])["completeness_score_pct"], 60.00, "score after attestation"
        )

    def test_withdrawal_returns_the_count_to_exactly_its_captured_pre_creation_value(self):
        """The compensation lands on the captured 1 — not on 0 and not on 2 — and leaves no residue.

        PRD §2.11: "This is what makes compensating operations exact: withdrawing a cycle created moments earlier returns `open_obligation_count` to precisely its pre-creation value."
        PRD §3.4: "**Withdrawal** is the compensating operation for cycle creation, used when a cycle was opened in error."
        PRD §3.4: "Withdrawal cascades. Every `CycleContentItem` of the cycle whose `status` is `NOT_STARTED`, `DRAFT`, `READY`, or `WAIVED` moves to `VOID` in ascending `created_at` order, each with `readiness_factor` driven to 0.0. With the entire input set gone, `completeness_score_pct` is re-derived to 0.00. And the undertaking's `open_obligation_count` is re-derived from source, which is what makes the compensation exact: withdrawing a cycle created moments earlier must restore `open_obligation_count` to precisely the value it held before the creation."
        PRD §3.3: "When the input set is empty — because every item is `VOID`, or because the cycle has no items at all — the sum is zero and the score is 0.00."
        Design: Difficulty/compensating_invariant/cycle_withdrawal_restores_the_open_obligation_count_exactly
        """
        context = _undertaking_with_material_notice_baseline()
        undertaking_id = context["undertaking"]["id"]
        captured_baseline = read_undertaking(undertaking_id)["open_obligation_count"]
        assert captured_baseline == 1
        cycle = create_cycle(
            undertaking_id,
            fiscal_year_label="FY2026",
            period_start_date="2025-07-01",
            period_end_date="2026-06-30",
        )
        item_one = item_for_requirement(
            list_content_items(cycle["id"]), context["requirements"][0]["id"]
        )
        prepare_item(
            item_one["id"],
            data_as_of_date="2026-06-30",
            source_document_ref="OPDATA-FY2026.pdf",
        )
        attest_item(item_one["id"])
        assert read_undertaking(undertaking_id)["open_obligation_count"] == 2

        withdrawn = withdraw(cycle["id"], "Cycle opened against the wrong undertaking.")

        assert withdrawn["status"] == "WITHDRAWN"
        assert withdrawn["withdrawal_reason"] == "Cycle opened against the wrong undertaking."
        assert_score(withdrawn["completeness_score_pct"], 0.00, "score after withdrawal")
        items_after = list_content_items(cycle["id"])
        assert [item["status"] for item in items_after] == ["VOID", "VOID"]
        assert all(float(item["readiness_factor"]) == 0.0 for item in items_after)
        undertaking_after = read_undertaking(undertaking_id)
        assert undertaking_after["open_obligation_count"] == captured_baseline
        assert read_notice(context["notice"]["id"])["status"] == "MATERIAL"
        assert undertaking_after["content_weight_bp_total"] == 10000
        assert undertaking_after["delinquent_cycle_count"] == 0
        assert_score(undertaking_after["disclosure_risk_score"], 0.00, "disclosure_risk_score")
        assert undertaking_after["compliance_posture"] == "COMPLIANT"


class TestConfirmedCorrectionConservesTheInvoice:
    """PRD §3.7 / §3.10: a correction is never double-billed."""

    def test_the_engagement_invoice_opens_at_the_retainer_and_the_deadline_is_pinned(self):
        """400000 of retainer alone clears the floor, and the per-se call is due 2026-08-14.

        PRD §3.5: "And `filing_deadline_date` is the **tenth business day strictly after** `occurrence_date`, computed with the add-business-days rule of §2.6: the occurrence date itself is never counted whether or not it is a business day, and the result is the tenth business day encountered walking forward."
        PRD §3.5: "`per_se_material` is true if and only if `event_type` is one of the four per-se listed events — `PRINCIPAL_PAYMENT_DELINQUENCY`, `RATING_CHANGE`, `DEFEASANCE`, `BOND_CALL` — and false for the other four."
        PRD §3.10: "The engagement opens at `status` `ACTIVE`, `version` 1, `billable_filing_count` 0, with `superseded_by_engagement_id` and `termination_reason` null."
        PRD §3.10: "`monitoring_lapse_days` and `invoice_total_cents` are both derived immediately at creation, the latter meaning the minimum annual fee floor binds from the very first moment."
        Design: Difficulty/compensating_invariant/confirmed_correction_conserves_billable_filing_count_and_invoice_total
        """
        context = _confirmed_material_event_filing()

        assert context["notice"]["per_se_material"] is True
        assert context["notice"]["filing_deadline_date"] == "2026-08-14"
        assert context["engagement_at_creation"]["billable_filing_count"] == 0
        assert context["engagement_at_creation"]["invoice_total_cents"] == 400000

    def test_the_first_confirmation_bills_exactly_one_tier_one_filing(self):
        """F of 1 puts 45000 on top of the 400000 retainer and discharges the notice timely.

        PRD §3.10: "The first input is the conserved filing count: let F be the number of `Filing` rows whose `submitting_engagement_id` is this engagement and whose `status` is exactly `CONFIRMED`."
        PRD §3.10: "In cents: take the lesser of F and 4 at 45000 cents, plus the lesser of 5 and the excess of F over 4 (floored at zero) at 32500 cents, plus the excess of F over 9 (floored at zero) at 25000 cents. Those filing fees are added to the engagement's `retainer_cents` to give a subtotal."
        PRD §3.10: "The cap and the floor then apply in this exact nested order: the subtotal plus surcharge is first capped at 12,000 dollars (1200000 cents), and that capped figure is then raised to the minimum annual fee of 3,000 dollars (300000 cents) if it falls below it."
        PRD §3.5: "When the filing that carries the notice is confirmed, the notice is `FILED_TIMELY` if the date part of the filing's `submitted_at` is **less than or equal to** `filing_deadline_date` — a submission on the deadline date is timely — and `FILED_LATE` otherwise, with `days_late` set to the whole calendar days from `filing_deadline_date` to that submission date, floored at 0."
        Design: Difficulty/compensating_invariant/confirmed_correction_conserves_billable_filing_count_and_invoice_total
        """
        context = _confirmed_material_event_filing()

        assert context["filing"]["status"] == "CONFIRMED"
        engagement = read_engagement(context["engagement_id"])
        assert engagement["billable_filing_count"] == 1
        assert engagement["invoice_total_cents"] == 445000
        notice = read_notice(context["notice"]["id"])
        assert notice["status"] == "FILED_TIMELY"
        assert notice["days_late"] == 0
        assert notice["filed_filing_id"] == context["filing"]["id"]

    def test_a_submitted_corrector_is_drafted_against_a_discharged_subject_and_is_not_billable(self):
        """The correction clears the discharged-state test, and a SUBMITTED filing bills nothing.

        PRD §3.7: "Corrections invert the last clause: when `supersedes_filing_id` is present, the fileable-state test is replaced by a **discharged**-state test, because a correction re-files a document the repository already holds — the cycle or notice must be `FILED_TIMELY` or `FILED_LATE`, or the placement must be `DISCLOSED`."
        PRD §3.7: "A correcting draft must also carry a non-empty `correction_reason`, checked at draft creation and refused with `ERR_CORRECTION_REASON_REQUIRED`."
        PRD §3.10: "The first input is the conserved filing count: let F be the number of `Filing` rows whose `submitting_engagement_id` is this engagement and whose `status` is exactly `CONFIRMED`."
        PRD §3.10: "Filings in `DRAFT`, `SUBMITTED`, `REJECTED`, and `SUPERSEDED` are all excluded, which is precisely why a correction that supersedes its predecessor leaves F unchanged."
        Design: Difficulty/compensating_invariant/confirmed_correction_conserves_billable_filing_count_and_invoice_total
        """
        context = _confirmed_material_event_filing()

        corrector = create_event_filing(
            context["issue"]["id"],
            context["notice"]["id"],
            supersedes_filing_id=context["filing"]["id"],
            correction_reason="Called maturities table omitted two CUSIPs.",
        )

        assert corrector["status"] == "DRAFT"
        assert corrector["supersedes_filing_id"] == context["filing"]["id"]
        assert corrector["correction_reason"] == "Called maturities table omitted two CUSIPs."

        submitted = submit(corrector["id"], context["engagement_id"])

        assert submitted["status"] == "SUBMITTED"
        engagement = read_engagement(context["engagement_id"])
        assert engagement["billable_filing_count"] == 1
        assert engagement["invoice_total_cents"] == 445000

    def test_confirming_the_correction_leaves_the_count_and_the_invoice_untouched(self):
        """Two confirmations, one billable filing: the invoice holds at exactly 445000 cents.

        PRD §3.7: "Finally, when `supersedes_filing_id` is set, the target filing moves from `CONFIRMED` to `SUPERSEDED`, its `superseded_by_filing_id` is stamped with this filing's id, and the subject's `filed_filing_id` is repointed at this filing."
        PRD §3.7: "Because the target leaves the `CONFIRMED` set at the same moment this filing enters it, the engagement's `billable_filing_count` is unchanged and the invoice total is identical — a correction is never double-billed."
        PRD §3.10: "Filings in `DRAFT`, `SUBMITTED`, `REJECTED`, and `SUPERSEDED` are all excluded, which is precisely why a correction that supersedes its predecessor leaves F unchanged."
        Design: Difficulty/compensating_invariant/confirmed_correction_conserves_billable_filing_count_and_invoice_total
        """
        context = _confirmed_material_event_filing()
        engagement_before = read_engagement(context["engagement_id"])
        captured_billable = engagement_before["billable_filing_count"]
        captured_invoice = engagement_before["invoice_total_cents"]
        assert (captured_billable, captured_invoice) == (1, 445000)
        corrector = create_event_filing(
            context["issue"]["id"],
            context["notice"]["id"],
            supersedes_filing_id=context["filing"]["id"],
            correction_reason="Called maturities table omitted two CUSIPs.",
        )
        submit(corrector["id"], context["engagement_id"])

        confirmed = confirm(corrector["id"], context["engagement_id"], "EMMA-HA-2026-0002")

        assert confirmed["status"] == "CONFIRMED"
        predecessor = read_filing(context["filing"]["id"])
        assert predecessor["status"] == "SUPERSEDED"
        assert predecessor["superseded_by_filing_id"] == corrector["id"]
        assert predecessor["repository_receipt_id"] == "EMMA-HA-2026-0001"
        engagement_after = read_engagement(context["engagement_id"])
        assert engagement_after["billable_filing_count"] == captured_billable == 1
        assert engagement_after["invoice_total_cents"] == captured_invoice == 445000

    def test_the_correction_skips_hop_one_and_mints_no_failure_event(self):
        """The discharged notice keeps its timeliness verbatim and only its pointer moves.

        PRD §3.7: "**Hop 1 is skipped entirely for a correcting filing:** when `supersedes_filing_id` is set, the timeliness branch does not re-run, the subject's `status`, `filed_at`, `days_late`, and `timeliness_basis_applied` are all left exactly as they stood, and no new `FailureToFileEvent` is minted."
        PRD §3.7: "Finally, when `supersedes_filing_id` is set, the target filing moves from `CONFIRMED` to `SUPERSEDED`, its `superseded_by_filing_id` is stamped with this filing's id, and the subject's `filed_filing_id` is repointed at this filing."
        Design: Difficulty/compensating_invariant/confirmed_correction_conserves_billable_filing_count_and_invoice_total
        """
        context = _confirmed_material_event_filing()
        notice_before = read_notice(context["notice"]["id"])
        corrector = create_event_filing(
            context["issue"]["id"],
            context["notice"]["id"],
            supersedes_filing_id=context["filing"]["id"],
            correction_reason="Called maturities table omitted two CUSIPs.",
        )
        submit(corrector["id"], context["engagement_id"])
        confirm(corrector["id"], context["engagement_id"], "EMMA-HA-2026-0002")

        notice_after = read_notice(context["notice"]["id"])

        assert notice_after["status"] == "FILED_TIMELY" == notice_before["status"]
        assert notice_after["days_late"] == 0 == notice_before["days_late"]
        assert notice_after["filed_filing_id"] == corrector["id"]
        assert list_failure_events(undertaking_id=context["undertaking"]["id"]) == []
        undertaking = read_undertaking(context["undertaking"]["id"])
        assert undertaking["compliance_posture"] == "COMPLIANT"
        assert_score(undertaking["disclosure_risk_score"], 0.00, "disclosure_risk_score")
