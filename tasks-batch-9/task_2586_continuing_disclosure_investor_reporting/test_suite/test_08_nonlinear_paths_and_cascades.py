"""Non-linear filing paths and transitive cascades (PRD §3.1, §3.5, §3.7, §3.8, §3.9, §3.10, §3.11).

Two families of behaviour live here.  The first is path dependence: the same
endpoints, walked in a different order, leave the record in a different terminal
state — a rejection-and-resubmission loop destroys the timely submission instant,
and the two arms of a materiality determination fork have strictly disjoint
consequences.  The second is transitive cascade: one accepted request that fans
out across five entity types (defeasance) and one that walks a linear five-hop
chain before jumping a credit-program boundary into another issue's official
statement (a late confirmation).

Every hop is read back from the API rather than inferred, and every test starts
against an empty database whose logical clock reads its startup value of
2026-08-01T00:00:00Z.
"""

from test_helpers import (
    REVIEWER_ONE_ID,
    REVIEWER_TWO_ID,
    SIMPLE_REQUIREMENT_SPECS,
    ApiErrorId,
    api_client,
    assert_score,
    confirm,
    create_annual_report_filing,
    create_bond_issue,
    create_engagement,
    create_notice,
    create_official_statement,
    defease_issue,
    determine_notice,
    failure_events_for_cycle,
    failure_events_for_notice,
    is_iso8601_timestamp,
    list_notices,
    make_officer_headers,
    make_reviewer_headers,
    material_event_notice_payload,
    prepare_item,
    read_bond_issue,
    read_content_item,
    read_cycle,
    read_engagement,
    read_notice,
    read_official_statement,
    read_undertaking,
    reject,
    resubmit,
    review_official_statement,
    run_sweep,
    set_clock,
    setup_cycle,
    setup_cycle_with_engagement,
    setup_issue_with_undertaking,
    sole_failure_event_for_cycle,
    sole_failure_event_for_notice,
    submit,
    validate_error,
)


def normalized_instant(value):
    """Reduce a clock-stamped `*_at` field to second resolution.

    PRD §2.4 makes the fractional-second digits of a timestamp part of the
    housekeeping format rather than of the instant itself, so instant equality is
    compared without them.
    """
    assert is_iso8601_timestamp(value), f"expected an ISO 8601 UTC instant, got {value!r}"
    body = value[:-1] if value.endswith("Z") else value
    return body.split(".")[0]


def same_instant(actual, expected):
    return normalized_instant(actual) == normalized_instant(expected)


# --------------------------------------------------------------------------- #
# The rejection-and-resubmission loop
# --------------------------------------------------------------------------- #

SCHOOL_DISTRICT_ISSUE = {
    "issuer_program_code": "SCHOOLDIST",
    "series_designation": "2026A",
    "security_type": "GENERAL_OBLIGATION",
    "dated_date": "2026-04-01",
    "final_maturity_date": "2046-04-01",
    "original_par_amount_cents": 100000000,
}

REJECTION_REASON = "Operating data table missing the required five-year history."
CORRECTION_REASON = "Five-year operating data history appended per repository comment."


def drafted_annual_report(series_designation="2026A"):
    """A READY_TO_FILE FY2026 cycle due 2027-01-26 with its ANNUAL_REPORT filing in DRAFT.

    One 10000-bp OPERATING_DATA_TABLE requirement, a 210-day filing window on
    SUBMISSION_BASIS, and one ACTIVE engagement able to submit for it.
    """
    issue = dict(SCHOOL_DISTRICT_ISSUE, series_designation=series_designation)
    context = setup_cycle_with_engagement(
        specs=SIMPLE_REQUIREMENT_SPECS,
        issue=issue,
        undertaking={"filing_window_days": 210, "timeliness_basis": "SUBMISSION_BASIS"},
        cycle={
            "fiscal_year_label": "FY2026",
            "period_start_date": "2025-07-01",
            "period_end_date": "2026-06-30",
        },
        engagement={
            "agent_name": "Keystone Filing Agents",
            "effective_date": "2026-07-01",
            "expiration_date": "2027-12-31",
            "retainer_cents": 250000,
            "last_calendar_ack_date": "2026-08-01",
        },
    )
    context["filing"] = create_annual_report_filing(
        context["issue"]["id"], context["cycle"]["id"]
    )
    return context


class TestRejectionResubmitLoop:
    def test_the_rejection_loop_makes_late_what_the_direct_path_files_timely(self):
        """The rejection detour is what turns a boundary-timely filing into a late one.

        PRD §3.7: "Because timeliness is judged on the latest `submitted_at` and the earlier rejected attempt is discarded, a rejection loop can convert a filing that would have been timely into a late one."
        PRD §3.8: "In both variants the cycle's `filed_at` is set to the chosen basis instant, the cycle is timely when the date part of that instant is **less than or equal to** `due_date` (an inclusive boundary), and `days_late` is 0 when timely and otherwise the whole calendar days from `due_date` to that basis date."
        Design: Difficulty/non_linear_state_machine/rejection_resubmit_loop_converts_a_timely_filing_into_a_late_one
        """
        direct = drafted_annual_report("2026A")
        looped = drafted_annual_report("2026B")
        assert direct["cycle"]["due_date"] == "2027-01-26"
        assert looped["cycle"]["due_date"] == "2027-01-26"

        # Both filings are handed over on the due date itself.
        set_clock("2027-01-26T10:00:00Z")
        submit(direct["filing"]["id"], direct["engagement"]["id"])
        submit(looped["filing"]["id"], looped["engagement"]["id"])

        # Path A — straight through: DRAFT -> SUBMITTED -> CONFIRMED.
        confirm(direct["filing"]["id"], direct["engagement"]["id"], "EMMA-SD-2027-0002")

        # Path B — the same endpoints plus a detour back through SUBMITTED.
        set_clock("2027-01-27T11:00:00Z")
        reject(looped["filing"]["id"], looped["engagement"]["id"], REJECTION_REASON)
        set_clock("2027-01-28T09:00:00Z")
        resubmit(looped["filing"]["id"], looped["engagement"]["id"], CORRECTION_REASON)
        confirm(looped["filing"]["id"], looped["engagement"]["id"], "EMMA-SD-2027-0001")

        direct_cycle = read_cycle(direct["cycle"]["id"])
        looped_cycle = read_cycle(looped["cycle"]["id"])
        assert direct_cycle["status"] == "FILED_TIMELY"
        assert direct_cycle["days_late"] == 0
        assert looped_cycle["status"] == "FILED_LATE"
        assert looped_cycle["days_late"] == 2
        assert same_instant(looped_cycle["filed_at"], "2027-01-28T09:00:00Z")
        assert failure_events_for_cycle(direct["cycle"]["id"]) == []
        assert len(failure_events_for_cycle(looped["cycle"]["id"])) == 1

    def test_a_repository_rejection_returns_the_cycle_to_ready_to_file_and_mints_nothing(self):
        """SUBMITTED -> REJECTED compensates the subject and records no failure.

        PRD §3.7: "Rejection is a compensating transition: it returns the cycle from `FILING_IN_PROGRESS` to `READY_TO_FILE`, or the notice from `FILING_IN_PROGRESS` back to `MATERIAL`, and it mints no failure event."
        PRD §3.7: "A successful submission sets `submitted_at` from the logical clock, `submitted_by_user_id` from `X-User-ID`, `submitting_engagement_id` to the resolved engagement, and raises `submission_attempt_count` by 1."
        Design: Difficulty/non_linear_state_machine/rejection_resubmit_loop_converts_a_timely_filing_into_a_late_one
        """
        context = drafted_annual_report()
        assert context["filing"]["submission_attempt_count"] == 0

        set_clock("2027-01-26T10:00:00Z")
        submitted = submit(context["filing"]["id"], context["engagement"]["id"])
        assert submitted["status"] == "SUBMITTED"
        assert submitted["submission_attempt_count"] == 1
        assert same_instant(submitted["submitted_at"], "2027-01-26T10:00:00Z")
        assert read_cycle(context["cycle"]["id"])["status"] == "FILING_IN_PROGRESS"

        set_clock("2027-01-27T11:00:00Z")
        rejected = reject(context["filing"]["id"], context["engagement"]["id"], REJECTION_REASON)
        assert rejected["status"] == "REJECTED"
        assert rejected["rejection_reason"] == REJECTION_REASON
        assert read_cycle(context["cycle"]["id"])["status"] == "READY_TO_FILE"
        assert failure_events_for_cycle(context["cycle"]["id"]) == []

    def test_resubmission_overwrites_the_timely_submission_instant(self):
        """REJECTED -> SUBMITTED destroys the earlier, timely `submitted_at`.

        PRD §3.7: "It clears `rejection_reason` to null, **overwrites** `submitted_at` with the current clock instant, raises `submission_attempt_count`, re-stamps `submitting_engagement_id`, and drives the subject back into `FILING_IN_PROGRESS`."
        Design: Difficulty/non_linear_state_machine/rejection_resubmit_loop_converts_a_timely_filing_into_a_late_one
        """
        context = drafted_annual_report()
        set_clock("2027-01-26T10:00:00Z")
        first = submit(context["filing"]["id"], context["engagement"]["id"])
        set_clock("2027-01-27T11:00:00Z")
        reject(context["filing"]["id"], context["engagement"]["id"], REJECTION_REASON)

        set_clock("2027-01-28T09:00:00Z")
        resubmitted = resubmit(
            context["filing"]["id"], context["engagement"]["id"], CORRECTION_REASON
        )
        assert resubmitted["status"] == "SUBMITTED"
        assert resubmitted["submission_attempt_count"] == 2
        assert same_instant(resubmitted["submitted_at"], "2027-01-28T09:00:00Z")
        assert not same_instant(resubmitted["submitted_at"], first["submitted_at"])
        assert resubmitted["rejection_reason"] is None
        assert read_cycle(context["cycle"]["id"])["status"] == "FILING_IN_PROGRESS"

    def test_the_late_confirmation_after_the_loop_mints_one_minor_failure_event(self):
        """The loop's terminal confirmation records an ANNUAL_REPORT_LATE failure of 2 days.

        PRD §3.8: "A cycle reaching `FILED_LATE` mints one with `kind` `ANNUAL_REPORT_LATE`, `undertaking_id` and `cycle_id` from the cycle, `material_event_id` null, `occurred_at` set to the cycle's `due_date`, `days_late` copied from the cycle's `days_late`, and `status` `OPEN` — but only if no event with that `cycle_id` already exists; if the delinquency sweep already minted one, its `kind` is left unchanged, its `days_late` is refreshed, and its `status` moves from `OPEN` to `REMEDIATION_PENDING`."
        PRD §3.8: "For an `ANNUAL_REPORT_LATE` event the boundary is exact: 29 days late is `MINOR`, 30 days late is `MAJOR`."
        Design: Difficulty/non_linear_state_machine/rejection_resubmit_loop_converts_a_timely_filing_into_a_late_one
        """
        context = drafted_annual_report()
        set_clock("2027-01-26T10:00:00Z")
        submit(context["filing"]["id"], context["engagement"]["id"])
        set_clock("2027-01-27T11:00:00Z")
        reject(context["filing"]["id"], context["engagement"]["id"], REJECTION_REASON)
        set_clock("2027-01-28T09:00:00Z")
        resubmit(context["filing"]["id"], context["engagement"]["id"], CORRECTION_REASON)
        confirm(context["filing"]["id"], context["engagement"]["id"], "EMMA-SD-2027-0001")

        cycle = read_cycle(context["cycle"]["id"])
        assert cycle["status"] == "FILED_LATE"
        assert cycle["days_late"] == 2

        event = sole_failure_event_for_cycle(context["cycle"]["id"])
        assert event["kind"] == "ANNUAL_REPORT_LATE"
        assert event["cycle_id"] == context["cycle"]["id"]
        assert event["material_event_id"] is None
        assert event["occurred_at"] == "2027-01-26"
        assert event["days_late"] == 2
        assert event["severity"] == "MINOR"
        assert event["status"] == "OPEN"

    def test_the_loop_scores_the_undertaking_once_and_bills_only_the_confirmation(self):
        """One late annual report yields L of 1, a 12.00 risk score, and one billable filing.

        PRD §3.8: "`late_filing_count` is the number of that undertaking's failure events whose `kind` is `ANNUAL_REPORT_LATE` or `ANNUAL_REPORT_MISSED`."
        PRD §3.8: "Step 1 forms an additive base of 12 times L, plus 20 times M, plus 15 times D."
        PRD §3.7: "It does not raise `billable_filing_count` — a rejected submission is not billable."
        PRD §3.10: "The first input is the conserved filing count: let F be the number of `Filing` rows whose `submitting_engagement_id` is this engagement and whose `status` is exactly `CONFIRMED`."
        Design: Difficulty/non_linear_state_machine/rejection_resubmit_loop_converts_a_timely_filing_into_a_late_one
        """
        context = drafted_annual_report()
        set_clock("2027-01-26T10:00:00Z")
        submit(context["filing"]["id"], context["engagement"]["id"])
        set_clock("2027-01-27T11:00:00Z")
        reject(context["filing"]["id"], context["engagement"]["id"], REJECTION_REASON)
        set_clock("2027-01-28T09:00:00Z")
        resubmit(context["filing"]["id"], context["engagement"]["id"], CORRECTION_REASON)
        confirm(context["filing"]["id"], context["engagement"]["id"], "EMMA-SD-2027-0001")

        undertaking = read_undertaking(context["undertaking"]["id"])
        assert undertaking["late_filing_count"] == 1
        assert_score(undertaking["disclosure_risk_score"], 12.00, "disclosure_risk_score")
        assert undertaking["compliance_posture"] == "COMPLIANT"

        engagement = read_engagement(context["engagement"]["id"])
        assert engagement["billable_filing_count"] == 1


# --------------------------------------------------------------------------- #
# The materiality determination fork
# --------------------------------------------------------------------------- #

def two_pending_notices():
    """One issue with an undertaking and no cycles, plus two non-per-se pending notices.

    Notice A is UNSCHEDULED_DRAW_ON_RESERVE occurring 2026-07-20 and notice B is
    TRUSTEE_SUBSTITUTION occurring 2026-07-22, both opened while the logical clock
    stands at 2026-07-25.
    """
    set_clock("2026-07-25T00:00:00Z")
    context = setup_issue_with_undertaking(
        issue={
            "issuer_program_code": "TRANSITAUTH",
            "series_designation": "2026A",
            "security_type": "REVENUE",
            "dated_date": "2026-03-15",
            "final_maturity_date": "2056-03-15",
            "original_par_amount_cents": 100000000,
        },
        undertaking={
            "fiscal_year_end_month_day": "12-31",
            "filing_window_days": 210,
            "timeliness_basis": "SUBMISSION_BASIS",
        },
    )
    context["notice_a"] = create_notice(
        context["issue"]["id"],
        event_type="UNSCHEDULED_DRAW_ON_RESERVE",
        occurrence_date="2026-07-20",
    )
    context["notice_b"] = create_notice(
        context["issue"]["id"],
        event_type="TRUSTEE_SUBSTITUTION",
        occurrence_date="2026-07-22",
    )
    return context


class TestDeterminationFork:
    def test_the_two_determination_branches_leave_disjoint_open_obligation_footprints(self):
        """One trigger, two branches: MATERIAL stays open while NOT_MATERIAL releases the slot.

        PRD §3.5: "A `MATERIAL` determination leaves the notice in the open set — `open_material_event_count` and `open_obligation_count` are unchanged, the notice becomes fileable, and it remains exposed to the sweep that can strand it as `MISSED`."
        PRD §3.5: "A `NOT_MATERIAL` determination is terminal and releases the obligation: the notice leaves the open set, both counters fall, no `filing_deadline_date` enforcement ever applies to it again, the calendar sweep skips it permanently, and any later filing that names it is refused with `ERR_FILING_SUBJECT_MISMATCH`."
        PRD §3.5: "Either way the notice records `determined_by_user_id` from `X-User-ID` and `determined_at` from the logical clock, and either way the source status must be `DETERMINATION_PENDING`."
        Design: Difficulty/non_linear_state_machine/determination_fork_gives_the_two_branches_disjoint_side_effects
        """
        context = two_pending_notices()
        assert context["notice_a"]["status"] == "DETERMINATION_PENDING"
        assert context["notice_b"]["status"] == "DETERMINATION_PENDING"
        assert read_bond_issue(context["issue"]["id"])["open_material_event_count"] == 2

        material = determine_notice(
            context["notice_a"]["id"],
            "MATERIAL",
            "Reserve draw is material to holders.",
            user_id=REVIEWER_ONE_ID,
        )
        immaterial = determine_notice(
            context["notice_b"]["id"],
            "NOT_MATERIAL",
            "Successor trustee has identical powers; not material.",
            user_id=REVIEWER_TWO_ID,
        )

        assert material["status"] == "MATERIAL"
        assert material["determined_by_user_id"] == REVIEWER_ONE_ID
        assert same_instant(material["determined_at"], "2026-07-25T00:00:00Z")
        assert immaterial["status"] == "NOT_MATERIAL"
        assert immaterial["determined_by_user_id"] == REVIEWER_TWO_ID

        assert read_bond_issue(context["issue"]["id"])["open_material_event_count"] == 1
        assert read_undertaking(context["undertaking"]["id"])["open_obligation_count"] == 1

    def test_the_ten_business_day_window_is_measured_from_each_occurrence_date(self):
        """Both notices arm their deadline at the tenth business day after their occurrence.

        PRD §3.5: "And `filing_deadline_date` is the **tenth business day strictly after** `occurrence_date`, computed with the add-business-days rule of §2.6: the occurrence date itself is never counted whether or not it is a business day, and the result is the tenth business day encountered walking forward."
        Design: Difficulty/non_linear_state_machine/determination_fork_gives_the_two_branches_disjoint_side_effects
        """
        context = two_pending_notices()
        assert context["notice_a"]["filing_deadline_date"] == "2026-08-03"
        assert context["notice_b"]["filing_deadline_date"] == "2026-08-05"
        assert context["notice_a"]["per_se_material"] is False
        assert context["notice_b"]["per_se_material"] is False

    def test_a_not_material_determination_is_a_terminal_state(self):
        """Re-determining an immaterial notice is refused on its own status.

        PRD §3.5: "Either way the notice records `determined_by_user_id` from `X-User-ID` and `determined_at` from the logical clock, and either way the source status must be `DETERMINATION_PENDING`."
        PRD §2.10: "Own-status transition legality — the target row's own `status` admits the requested transition → `ERR_INVALID_STATE_TRANSITION` (409)."
        Design: Difficulty/non_linear_state_machine/determination_fork_gives_the_two_branches_disjoint_side_effects
        """
        context = two_pending_notices()
        determine_notice(
            context["notice_b"]["id"],
            "NOT_MATERIAL",
            "Successor trustee has identical powers; not material.",
            user_id=REVIEWER_TWO_ID,
        )
        response = api_client.determine_material_event_notice(
            context["notice_b"]["id"],
            {"determination": "MATERIAL", "determination_note": "Second thoughts."},
            make_reviewer_headers(REVIEWER_ONE_ID),
        )
        validate_error(response, ApiErrorId.ERR_INVALID_STATE_TRANSITION.value, 409)
        assert read_notice(context["notice_b"]["id"])["status"] == "NOT_MATERIAL"

    def test_the_sweep_strands_only_the_notice_that_was_determined_material(self):
        """One sweep past both deadlines finds exactly one sweepable notice.

        PRD §3.11: "Every `MaterialEventNotice` in `status` `MATERIAL` whose `filing_deadline_date` is strictly before the logical clock's date moves to `MISSED`, with `days_late` set to the calendar days from `filing_deadline_date` to the clock date."
        PRD §3.11: "A notice still in `DETERMINATION_PENDING` is not swept, and a notice determined `NOT_MATERIAL` is skipped permanently."
        PRD §3.11: "It reports `swept_at`, the logical-clock instant of the sweep, alongside five counts: `matured_issue_count` for step 1, `delinquent_cycle_count` for step 2, `missed_event_count` for step 3, `suspended_engagement_count` for step 4, and `failure_event_created_count` for every `FailureToFileEvent` minted across steps 2 and 3 together."
        Design: Difficulty/non_linear_state_machine/determination_fork_gives_the_two_branches_disjoint_side_effects
        """
        context = two_pending_notices()
        determine_notice(context["notice_a"]["id"], "MATERIAL", user_id=REVIEWER_ONE_ID)
        determine_notice(context["notice_b"]["id"], "NOT_MATERIAL", user_id=REVIEWER_TWO_ID)

        set_clock("2026-08-06T00:00:00Z")
        sweep = run_sweep()
        assert sweep["missed_event_count"] == 1
        assert sweep["failure_event_created_count"] == 1

        stranded = read_notice(context["notice_a"]["id"])
        assert stranded["status"] == "MISSED"
        assert stranded["days_late"] == 3

        released = read_notice(context["notice_b"]["id"])
        assert released["status"] == "NOT_MATERIAL"
        assert released["days_late"] == 0
        assert released["filed_filing_id"] is None

        event = sole_failure_event_for_notice(context["notice_a"]["id"])
        assert event["kind"] == "MATERIAL_EVENT_MISSED"
        assert event["occurred_at"] == "2026-08-03"
        assert event["cycle_id"] is None
        assert event["severity"] == "MAJOR"
        assert event["status"] == "OPEN"
        assert failure_events_for_notice(context["notice_b"]["id"]) == []

        assert read_bond_issue(context["issue"]["id"])["open_material_event_count"] == 0

    def test_only_the_material_branch_moves_the_undertakings_missed_event_counter(self):
        """The stranded notice scores 20.00; the immaterial one contributes nothing.

        PRD §3.8: "`missed_event_count` is the number whose `kind` is `MATERIAL_EVENT_MISSED`."
        PRD §3.8: "Step 1 forms an additive base of 12 times L, plus 20 times M, plus 15 times D."
        PRD §3.8: "Step 4 derives the new `remediation_tier` from the score just written, using inclusive lower bounds: `TIER_3` at 75.00 or above, else `TIER_2` at 50.00 or above, else `TIER_1` at 25.00 or above, else `TIER_0`."
        Design: Difficulty/non_linear_state_machine/determination_fork_gives_the_two_branches_disjoint_side_effects
        """
        context = two_pending_notices()
        determine_notice(context["notice_a"]["id"], "MATERIAL", user_id=REVIEWER_ONE_ID)
        determine_notice(context["notice_b"]["id"], "NOT_MATERIAL", user_id=REVIEWER_TWO_ID)

        set_clock("2026-08-06T00:00:00Z")
        run_sweep()

        undertaking = read_undertaking(context["undertaking"]["id"])
        assert undertaking["missed_event_count"] == 1
        assert undertaking["late_filing_count"] == 0
        assert_score(undertaking["disclosure_risk_score"], 20.00, "disclosure_risk_score")
        assert undertaking["remediation_tier"] == "TIER_0"
        assert undertaking["compliance_posture"] == "COMPLIANT"


# --------------------------------------------------------------------------- #
# The defeasance termination cascade
# --------------------------------------------------------------------------- #

def defeasance_context():
    """An OUTSTANDING issue carrying every row the four-hop cascade has to touch.

    One ACTIVE undertaking with a single 10000-bp OPERATING_DATA_TABLE requirement,
    one ACTIVE engagement with a 250000-cent retainer, one DRAFTING FY2026 cycle
    whose only content item has been driven to DRAFT, and one pre-existing
    DETERMINATION_PENDING notice.  The logical clock stands at its startup value.
    """
    context = setup_cycle(
        specs=SIMPLE_REQUIREMENT_SPECS,
        issue={
            "issuer_program_code": "AIRPORTREV",
            "series_designation": "2016A",
            "security_type": "REVENUE",
            "dated_date": "2016-05-01",
            "final_maturity_date": "2046-05-01",
            "original_par_amount_cents": 100000000,
        },
        undertaking={"filing_window_days": 210, "timeliness_basis": "SUBMISSION_BASIS"},
        cycle={
            "fiscal_year_label": "FY2026",
            "period_start_date": "2025-07-01",
            "period_end_date": "2026-06-30",
        },
    )
    context["item"] = prepare_item(
        context["items"][0]["id"],
        data_as_of_date="2026-06-30",
        source_document_ref="OPDATA-FY2026.pdf",
    )
    context["engagement"] = create_engagement(
        context["undertaking"]["id"],
        agent_name="Beacon Dissemination Co",
        effective_date="2026-07-20",
        expiration_date="2027-12-31",
        retainer_cents=250000,
        last_calendar_ack_date="2026-08-01",
    )
    context["old_notice"] = create_notice(
        context["issue"]["id"],
        event_type="UNSCHEDULED_DRAW_ON_RESERVE",
        occurrence_date="2026-07-20",
    )
    context["cycle"] = read_cycle(context["cycle"]["id"])
    return context


def legal_defeasance(issue_id):
    return defease_issue(
        issue_id,
        defeasance_type="LEGAL",
        escrow_deposit_cents=100000000,
        occurrence_date="2026-08-01",
    )


class TestDefeasanceCascade:
    def test_defeasance_walks_every_hop_from_the_issue_down_to_the_content_item(self):
        """One FinanceDirector call terminates the undertaking, closes the cycle, terminates the engagement and voids the item.

        PRD §3.1: "Both endings drive `outstanding_par_amount_cents` to 0, advance the issue's `version`, and fire the same four-hop termination cascade."
        PRD §3.1: "Hop 1: the `Undertaking` whose `issue_id` names this issue, if its `status` is `ACTIVE` or `SUSPENDED`, moves to `TERMINATED`, with `termination_cause` set to `DEFEASANCE` for the defeasance path and `MATURITY` for the maturity path."
        PRD §3.1: "Hop 2: every `AnnualReportCycle` of that undertaking whose `status` is `DRAFTING`, `READY_TO_FILE`, or `DELINQUENT` moves to `CLOSED_NOT_REQUIRED`, processed in ascending `created_at` order; where such a cycle was `DELINQUENT`, leaving that status also forces a fresh derivation of `delinquent_cycle_count` and a re-run of the risk score of §3.8."
        PRD §3.1: "Hop 2b: every `DisseminationEngagement` of that undertaking whose `status` is `ACTIVE` or `SUSPENDED` moves to `TERMINATED` with `termination_reason` set to `UNDERTAKING_TERMINATED`, and its `invoice_total_cents` freezes at whatever value it then holds."
        PRD §3.1: "Hop 3: every `CycleContentItem` of each closed cycle whose `status` is `NOT_STARTED`, `DRAFT`, `READY`, or `WAIVED` moves to `VOID` in ascending `created_at` order, each with `readiness_factor` driven to 0.0 — though an item that had been attested keeps its `attested_by_user_id` for the audit trail — and each affected cycle's `completeness_score_pct` falls to 0.00 because its entire input set has left."
        Design: Difficulty/transitive_cascade/defeasance_cascades_four_hops_to_items_and_engagement
        """
        context = defeasance_context()
        assert context["issue"]["outstanding_par_amount_cents"] == 100000000
        assert context["cycle"]["status"] == "DRAFTING"
        assert_score(context["cycle"]["completeness_score_pct"], 50.00, "completeness_score_pct")
        assert context["engagement"]["status"] == "ACTIVE"

        defeased = legal_defeasance(context["issue"]["id"])
        assert defeased["status"] == "DEFEASED"
        assert defeased["outstanding_par_amount_cents"] == 0
        assert defeased["defeasance_type"] == "LEGAL"
        assert defeased["escrow_deposit_cents"] == 100000000
        assert same_instant(defeased["defeased_at"], "2026-08-01T00:00:00Z")

        undertaking = read_undertaking(context["undertaking"]["id"])
        assert undertaking["status"] == "TERMINATED"
        assert undertaking["termination_cause"] == "DEFEASANCE"

        cycle = read_cycle(context["cycle"]["id"])
        assert cycle["status"] == "CLOSED_NOT_REQUIRED"
        assert_score(cycle["completeness_score_pct"], 0.00, "completeness_score_pct")

        engagement = read_engagement(context["engagement"]["id"])
        assert engagement["status"] == "TERMINATED"
        assert engagement["termination_reason"] == "UNDERTAKING_TERMINATED"

        item = read_content_item(context["item"]["id"])
        assert item["status"] == "VOID"
        assert float(item["readiness_factor"]) == 0.0

    def test_the_defeasance_notice_is_minted_after_the_void_pass_and_survives_it(self):
        """The pre-existing pending notice is voided while the defeasance's own notice stays open.

        PRD §3.1: "Alongside the hops, every `MaterialEventNotice` on the issue whose `status` is `DETERMINATION_PENDING` or `MATERIAL` is driven to `VOID`, again in ascending `created_at` order."
        PRD §3.1: "Defeasance is itself a listed event, so after the void pass has finished the defeasance path mints one further `MaterialEventNotice` on the issue: `event_type` `DEFEASANCE`, `occurrence_date` taken from the request body, `status` `DETERMINATION_PENDING`, `per_se_material` true, `created_by_user_id` set from `X-User-ID`, and `filing_deadline_date` derived from the ten-business-day rule."
        PRD §3.1: "Because that notice is minted after the void pass rather than before it, it is never voided by its own trigger, and it is the one notice on a defeased issue that survives in an open status."
        Design: Difficulty/transitive_cascade/defeasance_cascades_four_hops_to_items_and_engagement
        """
        context = defeasance_context()
        legal_defeasance(context["issue"]["id"])

        assert read_notice(context["old_notice"]["id"])["status"] == "VOID"

        minted = list_notices(issue_id=context["issue"]["id"], event_type="DEFEASANCE")
        assert len(minted) == 1
        notice = minted[0]
        assert notice["status"] == "DETERMINATION_PENDING"
        assert notice["per_se_material"] is True
        assert notice["occurrence_date"] == "2026-08-01"
        assert notice["filing_deadline_date"] == "2026-08-14"

    def test_defeasance_re_derives_the_open_counters_down_to_the_surviving_notice(self):
        """The closed cycle and the voided notice leave the open set; the new notice is all that remains.

        PRD §3.1: "The undertaking's `open_obligation_count`, its delinquency counters, and the issue's `open_material_event_count` are all re-derived."
        PRD §3.3: "The undertaking's `open_obligation_count` is re-derived, and the new cycle raises it."
        PRD §3.5: "Creation also re-derives the issue's `open_material_event_count` and the undertaking's `open_obligation_count`, because a `DETERMINATION_PENDING` notice is an open obligation."
        Design: Difficulty/transitive_cascade/defeasance_cascades_four_hops_to_items_and_engagement
        """
        context = defeasance_context()
        assert read_undertaking(context["undertaking"]["id"])["open_obligation_count"] == 2
        assert read_bond_issue(context["issue"]["id"])["open_material_event_count"] == 1

        defeased = legal_defeasance(context["issue"]["id"])
        assert defeased["open_material_event_count"] == 1
        assert read_undertaking(context["undertaking"]["id"])["open_obligation_count"] == 1

    def test_the_cascaded_engagement_termination_freezes_the_minimum_annual_fee(self):
        """The engagement's invoice stands at the floor when hop 2b freezes it.

        PRD §3.10: "`monitoring_lapse_days` and `invoice_total_cents` are both derived immediately at creation, the latter meaning the minimum annual fee floor binds from the very first moment."
        PRD §3.10: "The cap and the floor then apply in this exact nested order: the subtotal plus surcharge is first capped at 12,000 dollars (1200000 cents), and that capped figure is then raised to the minimum annual fee of 3,000 dollars (300000 cents) if it falls below it."
        PRD §3.1: "Hop 2b: every `DisseminationEngagement` of that undertaking whose `status` is `ACTIVE` or `SUSPENDED` moves to `TERMINATED` with `termination_reason` set to `UNDERTAKING_TERMINATED`, and its `invoice_total_cents` freezes at whatever value it then holds."
        Design: Difficulty/transitive_cascade/defeasance_cascades_four_hops_to_items_and_engagement
        """
        context = defeasance_context()
        assert context["engagement"]["invoice_total_cents"] == 300000
        assert context["engagement"]["billable_filing_count"] == 0

        legal_defeasance(context["issue"]["id"])

        engagement = read_engagement(context["engagement"]["id"])
        assert engagement["status"] == "TERMINATED"
        assert engagement["invoice_total_cents"] == 300000

    def test_a_defeased_issue_accepts_no_further_listed_event_notice(self):
        """DEFEASED is terminal, so the issue gate closes the disclosure surface.

        PRD §2.10: "Issue gate — the `BondIssue` that owns the target row is `OUTSTANDING` → `ERR_ISSUE_NOT_OUTSTANDING` (409). Applies to `POST /disclosure/undertakings`, `POST /disclosure/annual-report-cycles`, `POST /disclosure/material-event-notices`, `POST /disclosure/direct-placements`, `POST /disclosure/filings`, and `POST /disclosure/official-statements/{id}/compliance-review`."
        Design: Difficulty/transitive_cascade/defeasance_cascades_four_hops_to_items_and_engagement
        """
        context = defeasance_context()
        legal_defeasance(context["issue"]["id"])

        response = api_client.create_material_event_notice(
            material_event_notice_payload(
                context["issue"]["id"],
                event_type="MERGER_OR_SALE",
                occurrence_date="2026-08-01",
            ),
            make_officer_headers(),
        )
        validate_error(response, ApiErrorId.ERR_ISSUE_NOT_OUTSTANDING.value, 409)


# --------------------------------------------------------------------------- #
# The late-confirmation cascade
# --------------------------------------------------------------------------- #

def harbor_program_context():
    """The HARBORDIST credit program held one hop short of the confirmation.

    Series 2018A carries an undertaking on SUBMISSION_BASIS, one 10000-bp
    requirement, one ACTIVE engagement with a 250000-cent retainer and an FY2025
    cycle due 2026-01-26 whose ANNUAL_REPORT filing is already SUBMITTED at the
    clock's startup instant — long past the due date, and never swept, so the
    cycle is still FILING_IN_PROGRESS.  A second issue in the same program, series
    2026N, carries an OfficialStatement dated 2026-09-01 already reviewed ADEQUATE
    against an empty disclosed set.
    """
    context = setup_cycle_with_engagement(
        specs=SIMPLE_REQUIREMENT_SPECS,
        issue={
            "issuer_program_code": "HARBORDIST",
            "series_designation": "2018A",
            "security_type": "REVENUE",
            "dated_date": "2018-07-01",
            "final_maturity_date": "2048-07-01",
            "original_par_amount_cents": 100000000,
        },
        undertaking={"filing_window_days": 210, "timeliness_basis": "SUBMISSION_BASIS"},
        cycle={
            "fiscal_year_label": "FY2025",
            "period_start_date": "2024-07-01",
            "period_end_date": "2025-06-30",
        },
        engagement={
            "agent_name": "Harbor Filing Services",
            "effective_date": "2026-07-25",
            "expiration_date": "2027-12-31",
            "retainer_cents": 250000,
            "last_calendar_ack_date": "2026-08-01",
        },
    )
    context["filing"] = create_annual_report_filing(
        context["issue"]["id"], context["cycle"]["id"]
    )
    submit(context["filing"]["id"], context["engagement"]["id"])

    context["new_issue"] = create_bond_issue(
        issuer_program_code="HARBORDIST",
        series_designation="2026N",
        security_type="REVENUE",
        dated_date="2026-09-01",
        final_maturity_date="2056-09-01",
        original_par_amount_cents=40000000,
    )
    statement = create_official_statement(
        context["new_issue"]["id"],
        dated_date="2026-09-01",
        lookback_policy="STRICT_FIVE_YEAR",
        disclosed_event_ids=[],
    )
    context["statement"] = review_official_statement(
        statement["id"], disclosed_event_ids=[], user_id=REVIEWER_ONE_ID
    )
    return context


class TestLateConfirmationCascade:
    def test_one_confirmation_walks_five_hops_and_then_crosses_into_another_issues_statement(self):
        """Filing, cycle, failure event, undertaking, invoice and finally a sibling issue's official statement.

        PRD §3.7: "Hop 1 discharges the subject."
        PRD §3.7: "Hop 2 runs only when hop 1 produced a `FILED_LATE` **cycle**, and creates the `FailureToFileEvent` described in §3.8."
        PRD §3.7: "Hop 3 re-derives the undertaking's counters and then re-runs the risk-score pass, which may move `compliance_posture`."
        PRD §3.7: "Hop 4 re-derives the submitting engagement's `billable_filing_count` and then its `invoice_total_cents`, the latter sensitive to the posture hop 3 just wrote."
        PRD §3.7: "Hop 5 re-runs the official-statement lookback for every `OfficialStatement` in `COMPLIANCE_REVIEW` whose issue shares the failure event's `issuer_program_code`, which can flip `disclosure_adequacy` to `INCOMPLETE`."
        PRD §3.8: "In both variants the cycle's `filed_at` is set to the chosen basis instant, the cycle is timely when the date part of that instant is **less than or equal to** `due_date` (an inclusive boundary), and `days_late` is 0 when timely and otherwise the whole calendar days from `due_date` to that basis date."
        Design: Difficulty/transitive_cascade/late_confirmation_cascades_five_hops_into_official_statement_adequacy
        """
        context = harbor_program_context()
        assert context["cycle"]["due_date"] == "2026-01-26"
        assert read_cycle(context["cycle"]["id"])["status"] == "FILING_IN_PROGRESS"

        confirmed = confirm(
            context["filing"]["id"], context["engagement"]["id"], "EMMA-HD-2026-0001"
        )
        # Hop 1 — the filing itself.
        assert confirmed["status"] == "CONFIRMED"
        assert same_instant(confirmed["repository_confirmed_at"], "2026-08-01T00:00:00Z")

        # Hop 2 — the cycle.
        cycle = read_cycle(context["cycle"]["id"])
        assert cycle["status"] == "FILED_LATE"
        assert cycle["days_late"] == 187
        assert cycle["timeliness_basis_applied"] == "SUBMISSION_BASIS"
        assert cycle["filed_filing_id"] == context["filing"]["id"]

        # Hop 3 — the failure event.
        event = sole_failure_event_for_cycle(context["cycle"]["id"])
        assert event["kind"] == "ANNUAL_REPORT_LATE"
        assert event["occurred_at"] == "2026-01-26"
        assert event["days_late"] == 187
        assert event["severity"] == "MAJOR"
        assert event["status"] == "OPEN"

        # Hop 4 — the undertaking's counters and score.
        undertaking = read_undertaking(context["undertaking"]["id"])
        assert undertaking["late_filing_count"] == 1
        assert_score(undertaking["disclosure_risk_score"], 12.00, "disclosure_risk_score")
        assert undertaking["remediation_tier"] == "TIER_0"
        assert undertaking["compliance_posture"] == "COMPLIANT"

        # Hop 5 — the agent's invoice.
        engagement = read_engagement(context["engagement"]["id"])
        assert engagement["billable_filing_count"] == 1
        assert engagement["invoice_total_cents"] == 300000

        # The cross-aggregate hop into the other issue's official statement.
        statement = read_official_statement(context["statement"]["id"])
        assert statement["required_disclosure_event_ids"] == [event["id"]]
        assert statement["required_disclosure_event_count"] == 1
        assert statement["disclosure_adequacy"] == "INCOMPLETE"

    def test_the_invoice_hop_raises_a_single_confirmed_filing_to_the_minimum_annual_fee(self):
        """F of 1 against a 250000-cent retainer bills 295000 and is lifted to the floor.

        PRD §3.10: "Two worked cases pin the order. With F of 6, a `retainer_cents` of 250000, and posture `IMPAIRED`: filing fees are four at 45000 plus two at 32500, which is 245000; the subtotal is 495000; the surcharge is the lesser of 74250 and 150000, which is 74250; the capped figure is the lesser of 569250 and 1200000, which is 569250; and `invoice_total_cents` is the greater of 569250 and 300000, which is 569250. With F of 1, a `retainer_cents` of 250000, and posture `COMPLIANT`: the subtotal is 295000, the surcharge is 0, the capped figure is 295000, and `invoice_total_cents` is 300000 — the floor binds."
        PRD §3.7: "Hop 4 re-derives the submitting engagement's `billable_filing_count` and then its `invoice_total_cents`, the latter sensitive to the posture hop 3 just wrote."
        Design: Difficulty/transitive_cascade/late_confirmation_cascades_five_hops_into_official_statement_adequacy
        """
        context = harbor_program_context()
        assert context["engagement"]["billable_filing_count"] == 0
        assert context["engagement"]["invoice_total_cents"] == 300000

        confirm(context["filing"]["id"], context["engagement"]["id"], "EMMA-HD-2026-0001")

        engagement = read_engagement(context["engagement"]["id"])
        assert engagement["billable_filing_count"] == 1
        assert engagement["invoice_total_cents"] == 300000

    def test_the_failure_event_flips_a_sibling_issues_review_from_adequate_to_incomplete(self):
        """The lookback is scoped to the credit program, not to the statement's own issue.

        PRD §3.9: "The scope is the credit **program**, not the single issue: let the scope program be the `issuer_program_code` of the official statement's own `BondIssue`, and the candidate set is every `FailureToFileEvent` whose undertaking hangs off any `BondIssue` sharing that `issuer_program_code`, the statement's own issue included, whose `occurred_at` is at or after the left edge and strictly before `dated_date`."
        PRD §3.9: "`disclosure_adequacy` is `ADEQUATE` when every id in `required_disclosure_event_ids` appears in `disclosed_event_ids`, and `INCOMPLETE` otherwise; ids in `disclosed_event_ids` that are not required are ignored rather than treated as errors, so an over-inclusive document is adequate."
        PRD §3.7: "Hop 5 re-runs the official-statement lookback for every `OfficialStatement` in `COMPLIANCE_REVIEW` whose issue shares the failure event's `issuer_program_code`, which can flip `disclosure_adequacy` to `INCOMPLETE`."
        Design: Difficulty/transitive_cascade/late_confirmation_cascades_five_hops_into_official_statement_adequacy
        """
        context = harbor_program_context()
        assert context["statement"]["status"] == "COMPLIANCE_REVIEW"
        assert context["statement"]["required_disclosure_event_count"] == 0
        assert context["statement"]["required_disclosure_event_ids"] == []
        assert context["statement"]["disclosure_adequacy"] == "ADEQUATE"
        assert context["statement"]["issue_id"] == context["new_issue"]["id"]
        assert context["new_issue"]["id"] != context["issue"]["id"]

        confirm(context["filing"]["id"], context["engagement"]["id"], "EMMA-HD-2026-0001")
        event = sole_failure_event_for_cycle(context["cycle"]["id"])

        statement = read_official_statement(context["statement"]["id"])
        assert statement["required_disclosure_event_count"] == 1
        assert statement["required_disclosure_event_ids"] == [event["id"]]
        assert statement["disclosure_adequacy"] == "INCOMPLETE"

    def test_a_failure_minted_between_review_and_posting_blocks_the_post(self):
        """The post-time re-run of the lookback refuses the stale ADEQUATE verdict.

        PRD §3.9: "The lookback is **re-run at post time**, and posting is refused with `ERR_DISCLOSURE_INADEQUATE` unless the freshly recomputed `disclosure_adequacy` is `ADEQUATE` — so a failure event minted between the review and the posting blocks the post even though the stored verdict said `ADEQUATE`."
        Design: Difficulty/transitive_cascade/late_confirmation_cascades_five_hops_into_official_statement_adequacy
        """
        context = harbor_program_context()
        assert context["statement"]["disclosure_adequacy"] == "ADEQUATE"

        confirm(context["filing"]["id"], context["engagement"]["id"], "EMMA-HD-2026-0001")

        response = api_client.post_official_statement(
            context["statement"]["id"], make_reviewer_headers(REVIEWER_TWO_ID)
        )
        validate_error(response, ApiErrorId.ERR_DISCLOSURE_INADEQUATE.value, 409)
        assert read_official_statement(context["statement"]["id"])["status"] == "COMPLIANCE_REVIEW"
