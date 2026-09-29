"""Variant and combinatorial calculation depth (PRD §3.3, §3.8, §3.9).

Four design instances are translated here:

* the two annual-report timeliness variants (`SUBMISSION_BASIS` versus
  `CONFIRMATION_BASIS`) diverging on one byte-identical filing;
* the two official-statement lookback variants (`STRICT_FIVE_YEAR` versus
  `REMEDIATED_EXCLUDED`) diverging over one identical failure population;
* the pinned round-then-sum order of `completeness_score_pct`, whose worked
  example in §3.3 must produce 50.01 rather than 50.00;
* the risk-score escalation that reads the *persisted* prior `remediation_tier`,
  whose worked chain in §3.8 must produce 20.00 -> 40.00 -> 66.00.

Every test starts against an empty database with the logical clock at its
startup value of 2026-08-01T00:00:00Z.
"""

from test_helpers import (
    assemble,
    assert_annual_report_cycle,
    assert_failure_to_file_event,
    assert_official_statement,
    assert_readiness_matches_status,
    assert_tier_matches_score,
    assert_two_decimals,
    assert_undertaking,
    assert_undertaking_posture_consistent,
    attest_item,
    create_annual_report_filing,
    create_bond_issue,
    create_cycle,
    create_engagement,
    create_notice,
    create_official_statement,
    create_requirements,
    create_undertaking,
    determine_notice,
    item_of_kind,
    list_content_items,
    list_failure_events,
    prepare_item,
    read_cycle,
    read_failure_event,
    read_notice,
    read_official_statement,
    read_undertaking,
    remediate_event,
    review_official_statement,
    run_sweep,
    set_clock,
    setup_cycle,
    setup_filed_annual_report,
    sole_failure_event_for_cycle,
    submit_and_confirm,
)

# --------------------------------------------------------------------------- #
# Shared literals, all pre-computed by the design and pinned by the PRD.
# --------------------------------------------------------------------------- #

SUBMIT_CLOCK = "2027-01-26T09:00:00Z"
CONFIRM_CLOCK = "2027-01-28T14:00:00Z"
DUE_DATE_FY2026 = "2027-01-26"
DUE_DATE_FY2025 = "2026-01-26"

# Four requirements summing to exactly 10000 basis points: 3333 + 3333 + 3333 + 1.
ROUNDING_REQUIREMENT_SPECS = [
    {
        "kind": "AUDITED_FINANCIALS",
        "label": "Audited Financial Statements",
        "weight_bp": 3333,
        "waivable": False,
    },
    {
        "kind": "OPERATING_DATA_TABLE",
        "label": "Operating Data Tables",
        "weight_bp": 3333,
        "waivable": False,
    },
    {
        "kind": "DEBT_SERVICE_SCHEDULE",
        "label": "Debt Service Schedule",
        "weight_bp": 3333,
        "waivable": False,
    },
    {
        "kind": "ENTERPRISE_STATISTICS",
        "label": "Enterprise Statistics",
        "weight_bp": 1,
        "waivable": False,
    },
]

ROUNDING_ISSUE = {
    "issuer_program_code": "CITYWATER",
    "series_designation": "2026C",
    "dated_date": "2026-02-01",
    "final_maturity_date": "2046-02-01",
    "original_par_amount_cents": 100000000,
}


# --------------------------------------------------------------------------- #
# Composite preconditions fixtures.py does not build.
# --------------------------------------------------------------------------- #

def _setup_rounding_cycle() -> dict:
    """A DRAFTING cycle whose four snapshotted weights are 3333/3333/3333/1.

    The three heavy items are driven to `DRAFT`; the `AUDITED_FINANCIALS` item
    also carries an `UNMODIFIED` opinion so its opinion multiplier is 1.0, and
    the weight-1 item is left untouched at `NOT_STARTED`.
    """
    context = setup_cycle(specs=ROUNDING_REQUIREMENT_SPECS, issue=dict(ROUNDING_ISSUE))
    items, requirements = context["items"], context["requirements"]
    context["audited"] = item_of_kind(items, requirements, "AUDITED_FINANCIALS")
    context["operating"] = item_of_kind(items, requirements, "OPERATING_DATA_TABLE")
    context["debt_service"] = item_of_kind(items, requirements, "DEBT_SERVICE_SCHEDULE")
    context["enterprise"] = item_of_kind(items, requirements, "ENTERPRISE_STATISTICS")
    context["undertaking"] = read_undertaking(context["undertaking"]["id"])
    return context


def _draft_three_heavy_items(context: dict) -> dict:
    """PATCH the three 3333-bp items to DRAFT and return the last item row."""
    prepare_item(
        context["audited"]["id"],
        audit_opinion_type="UNMODIFIED",
        data_as_of_date="2026-06-30",
        source_document_ref="CAFR-FY2026.pdf",
    )
    prepare_item(
        context["operating"]["id"],
        data_as_of_date="2026-06-30",
        source_document_ref="OPDATA-FY2026.pdf",
    )
    return prepare_item(
        context["debt_service"]["id"],
        data_as_of_date="2026-06-30",
        source_document_ref="DEBTSVC-FY2026.pdf",
    )


def _setup_program_with_two_late_cycles() -> dict:
    """Credit program CITYWATER with two late annual reports on one undertaking.

    The FY2025 cycle (due 2026-01-26) is confirmed while the clock still reads
    its startup instant, so its failure event is 187 days late; the FY2026 cycle
    (due 2027-01-26) is confirmed at 2027-02-05, so its event is 10 days late.
    The first event is then remediated at 2027-02-06, strictly before the new
    official statement's dated_date of 2027-03-01.
    """
    issue = create_bond_issue(
        issuer_program_code="CITYWATER",
        series_designation="2019A",
        dated_date="2019-06-01",
        final_maturity_date="2049-06-01",
        original_par_amount_cents=100000000,
    )
    undertaking = create_undertaking(
        issue["id"], filing_window_days=210, timeliness_basis="SUBMISSION_BASIS"
    )
    create_requirements(
        undertaking["id"],
        [{"kind": "OPERATING_DATA_TABLE", "label": "Operating Data Tables", "weight_bp": 10000}],
    )
    engagement = create_engagement(
        undertaking["id"],
        agent_name="Meridian Disclosure LLC",
        effective_date="2026-07-01",
        expiration_date="2027-12-31",
        retainer_cents=250000,
        last_calendar_ack_date="2026-08-01",
    )

    cycle_one = create_cycle(
        undertaking["id"],
        fiscal_year_label="FY2025",
        period_start_date="2024-07-01",
        period_end_date="2025-06-30",
    )
    item_one = list_content_items(cycle_one["id"])[0]
    prepare_item(
        item_one["id"], data_as_of_date="2025-06-30", source_document_ref="OPDATA-FY2025.pdf"
    )
    attest_item(item_one["id"])
    assemble(cycle_one["id"])
    filing_one = create_annual_report_filing(issue["id"], cycle_one["id"])
    submit_and_confirm(filing_one["id"], engagement["id"], "EMMA-FY2025-0001")

    cycle_two = create_cycle(
        undertaking["id"],
        fiscal_year_label="FY2026",
        period_start_date="2025-07-01",
        period_end_date="2026-06-30",
    )
    item_two = list_content_items(cycle_two["id"])[0]
    prepare_item(
        item_two["id"], data_as_of_date="2026-06-30", source_document_ref="OPDATA-FY2026.pdf"
    )
    attest_item(item_two["id"])
    assemble(cycle_two["id"])
    set_clock("2027-02-05T10:00:00Z")
    filing_two = create_annual_report_filing(issue["id"], cycle_two["id"])
    submit_and_confirm(filing_two["id"], engagement["id"], "EMMA-FY2026-0001")

    event_one = sole_failure_event_for_cycle(cycle_one["id"])
    event_two = sole_failure_event_for_cycle(cycle_two["id"])

    set_clock("2027-02-06T08:00:00Z")
    remediate_event(
        event_one["id"],
        filing_one["id"],
        "FY2025 annual report filed and confirmed; remediation policy step 3 complete.",
    )

    new_issue = create_bond_issue(
        issuer_program_code="CITYWATER",
        series_designation="2027A",
        dated_date="2027-03-01",
        final_maturity_date="2057-03-01",
        original_par_amount_cents=50000000,
    )
    statement = create_official_statement(
        new_issue["id"],
        dated_date="2027-03-01",
        lookback_policy="STRICT_FIVE_YEAR",
        disclosed_event_ids=[event_two["id"]],
    )
    return {
        "issue": issue,
        "undertaking": undertaking,
        "engagement": engagement,
        "cycle_one": read_cycle(cycle_one["id"]),
        "cycle_two": read_cycle(cycle_two["id"]),
        "filing_one": filing_one,
        "filing_two": filing_two,
        "event_one": read_failure_event(event_one["id"]),
        "event_two": read_failure_event(event_two["id"]),
        "new_issue": new_issue,
        "statement": statement,
    }


def _setup_three_material_notices() -> dict:
    """Three non-per-se MATERIAL notices whose deadlines fall on separate days.

    No cycle and no engagement exist, so sweep steps 2 and 4 have nothing to do
    and `delinquent_cycle_count` stays 0 for the whole chain.
    """
    set_clock("2026-07-25T00:00:00Z")
    issue = create_bond_issue(
        issuer_program_code="PORTAUTH",
        series_designation="2026A",
        dated_date="2026-03-01",
        final_maturity_date="2056-03-01",
        original_par_amount_cents=100000000,
    )
    undertaking = create_undertaking(
        issue["id"],
        fiscal_year_end_month_day="12-31",
        filing_window_days=210,
        timeliness_basis="SUBMISSION_BASIS",
    )
    notices = []
    for event_type, occurrence_date in (
        ("UNSCHEDULED_DRAW_ON_RESERVE", "2026-07-20"),
        ("TRUSTEE_SUBSTITUTION", "2026-07-22"),
        ("MERGER_OR_SALE", "2026-07-24"),
    ):
        notice = create_notice(issue["id"], event_type=event_type, occurrence_date=occurrence_date)
        notices.append(determine_notice(notice["id"], "MATERIAL"))
    return {"issue": issue, "undertaking": undertaking, "notices": notices}


# --------------------------------------------------------------------------- #
# Instance 1 — the two annual-report timeliness variants (PRD §3.8)
# --------------------------------------------------------------------------- #

class TestCycleTimelinessVariants:
    """One byte-identical filing judged under both `timeliness_basis` variants."""

    def test_submission_basis_arm_files_timely_on_the_due_date(self):
        """SUBMISSION_BASIS reads submitted_at, so a due-date submission is timely.

        PRD §3.8: "Under `SUBMISSION_BASIS`, the default, the basis instant is the filing's `submitted_at` — the moment the agent handed the document to the repository — so a document submitted on the due date is timely even if the repository confirms it days later."
        PRD §3.8: "In both variants the cycle's `filed_at` is set to the chosen basis instant, the cycle is timely when the date part of that instant is **less than or equal to** `due_date` (an inclusive boundary), and `days_late` is 0 when timely and otherwise the whole calendar days from `due_date` to that basis date."
        PRD §3.3: "Take the cycle's own `period_end_date`, advance it by the owning undertaking's `filing_window_days` in **calendar** days, then roll the result forward — never backward — to the first business day at or after it, using the calendar of §2.6."
        Design: Difficulty/dual_variant_calc/cycle_timeliness_submission_basis_vs_confirmation_basis_divergence
        """
        context = setup_filed_annual_report(
            timeliness_basis="SUBMISSION_BASIS",
            submit_clock=SUBMIT_CLOCK,
            confirm_clock=CONFIRM_CLOCK,
        )
        cycle, filing, undertaking = context["cycle"], context["filing"], context["undertaking"]

        assert_annual_report_cycle(cycle)
        assert cycle["due_date"] == DUE_DATE_FY2026
        assert cycle["status"] == "FILED_TIMELY"
        assert cycle["days_late"] == 0
        assert cycle["timeliness_basis_applied"] == "SUBMISSION_BASIS"
        assert cycle["filed_filing_id"] == filing["id"]
        # filed_at is the submission instant, not the confirmation instant.
        assert cycle["filed_at"] == filing["submitted_at"]
        assert str(cycle["filed_at"])[:19] == "2027-01-26T09:00:00"
        assert str(filing["repository_confirmed_at"])[:19] == "2027-01-28T14:00:00"

        assert undertaking["late_filing_count"] == 0
        assert float(undertaking["disclosure_risk_score"]) == 0.00
        assert undertaking["remediation_tier"] == "TIER_0"
        assert undertaking["compliance_posture"] == "COMPLIANT"
        assert list_failure_events(undertaking_id=undertaking["id"]) == []

    def test_confirmation_basis_arm_files_late_two_days_after_the_due_date(self):
        """CONFIRMATION_BASIS reads repository_confirmed_at, two days past due.

        PRD §3.8: "Under `CONFIRMATION_BASIS` the basis instant is the filing's `repository_confirmed_at`."
        PRD §3.8: "In both variants the cycle's `filed_at` is set to the chosen basis instant, the cycle is timely when the date part of that instant is **less than or equal to** `due_date` (an inclusive boundary), and `days_late` is 0 when timely and otherwise the whole calendar days from `due_date` to that basis date."
        PRD §3.8: "**Annual-report timeliness has two variants**, selected per undertaking by its persisted `timeliness_basis` and recorded on the cycle as `timeliness_basis_applied` so the verdict is auditable after the fact."
        Design: Difficulty/dual_variant_calc/cycle_timeliness_submission_basis_vs_confirmation_basis_divergence
        """
        context = setup_filed_annual_report(
            timeliness_basis="CONFIRMATION_BASIS",
            submit_clock=SUBMIT_CLOCK,
            confirm_clock=CONFIRM_CLOCK,
        )
        cycle, filing = context["cycle"], context["filing"]

        assert_annual_report_cycle(cycle)
        assert cycle["due_date"] == DUE_DATE_FY2026
        assert cycle["status"] == "FILED_LATE"
        assert cycle["days_late"] == 2
        assert cycle["timeliness_basis_applied"] == "CONFIRMATION_BASIS"
        assert cycle["filed_filing_id"] == filing["id"]
        assert cycle["filed_at"] == filing["repository_confirmed_at"]
        assert str(cycle["filed_at"])[:19] == "2027-01-28T14:00:00"
        assert str(filing["submitted_at"])[:19] == "2027-01-26T09:00:00"

    def test_confirmation_basis_arm_mints_one_minor_failure_event_and_scores_twelve(self):
        """The late arm mints ANNUAL_REPORT_LATE and scores 12 * 1 * 1.00 = 12.00.

        PRD §3.8: "A cycle reaching `FILED_LATE` mints one with `kind` `ANNUAL_REPORT_LATE`, `undertaking_id` and `cycle_id` from the cycle, `material_event_id` null, `occurred_at` set to the cycle's `due_date`, `days_late` copied from the cycle's `days_late`, and `status` `OPEN` — but only if no event with that `cycle_id` already exists; if the delinquency sweep already minted one, its `kind` is left unchanged, its `days_late` is refreshed, and its `status` moves from `OPEN` to `REMEDIATION_PENDING`."
        PRD §3.8: "`severity` is `MAJOR` when `kind` is `ANNUAL_REPORT_MISSED` or `MATERIAL_EVENT_MISSED`, or when `days_late` is **greater than or equal to** 30; it is `MINOR` otherwise."
        PRD §3.8: "Step 1 forms an additive base of 12 times L, plus 20 times M, plus 15 times D."
        PRD §3.8: "Step 2 escalates that base by the tier multiplier for T — 1.00 for `TIER_0`, 1.10 for `TIER_1`, 1.25 for `TIER_2`, 1.40 for `TIER_3` — and rounds the product half-up to 2 decimal places."
        PRD §3.8: "Step 6 derives `compliance_posture`, and here any delinquent cycle dominates the score bands outright: the posture is `DELINQUENT` whenever D is 1 or more, regardless of score; otherwise `IMPAIRED` at a score of 50.00 or above; otherwise `WATCH` at 25.00 or above; otherwise `COMPLIANT`."
        Design: Difficulty/dual_variant_calc/cycle_timeliness_submission_basis_vs_confirmation_basis_divergence
        """
        context = setup_filed_annual_report(
            timeliness_basis="CONFIRMATION_BASIS",
            submit_clock=SUBMIT_CLOCK,
            confirm_clock=CONFIRM_CLOCK,
        )
        undertaking = context["undertaking"]

        events = list_failure_events(undertaking_id=undertaking["id"])
        assert len(events) == 1
        event = events[0]
        assert_failure_to_file_event(event)
        assert event["kind"] == "ANNUAL_REPORT_LATE"
        assert event["cycle_id"] == context["cycle"]["id"]
        assert event["material_event_id"] is None
        assert str(event["occurred_at"])[:10] == DUE_DATE_FY2026
        assert event["days_late"] == 2
        assert event["severity"] == "MINOR"
        assert event["status"] == "OPEN"

        assert_undertaking(undertaking)
        assert undertaking["late_filing_count"] == 1
        assert undertaking["missed_event_count"] == 0
        assert undertaking["delinquent_cycle_count"] == 0
        assert float(undertaking["disclosure_risk_score"]) == 12.00
        assert undertaking["remediation_tier"] == "TIER_0"
        assert undertaking["compliance_posture"] == "COMPLIANT"
        assert_tier_matches_score(undertaking)
        assert_undertaking_posture_consistent(undertaking)

    def test_identical_filing_instants_diverge_between_the_two_variants(self):
        """Same due date, same submitted_at, same confirmed_at — opposite verdicts.

        PRD §3.8: "For one and the same filing — identical `submitted_at`, identical `repository_confirmed_at` — `CONFIRMATION_BASIS` can yield `FILED_LATE` where `SUBMISSION_BASIS` yields `FILED_TIMELY`, and therefore mints a failure event, raises `late_filing_count`, and re-runs the risk score, none of which the other variant does."
        Design: Difficulty/dual_variant_calc/cycle_timeliness_submission_basis_vs_confirmation_basis_divergence
        """
        submission = setup_filed_annual_report(
            timeliness_basis="SUBMISSION_BASIS",
            submit_clock=SUBMIT_CLOCK,
            confirm_clock=CONFIRM_CLOCK,
        )
        confirmation = setup_filed_annual_report(
            timeliness_basis="CONFIRMATION_BASIS",
            submit_clock=SUBMIT_CLOCK,
            confirm_clock=CONFIRM_CLOCK,
            issue={"series_designation": "2026B"},
        )

        # The two filings are byte-identical on every instant the rule reads.
        assert submission["cycle"]["due_date"] == confirmation["cycle"]["due_date"] == DUE_DATE_FY2026
        assert (
            str(submission["filing"]["submitted_at"])[:19]
            == str(confirmation["filing"]["submitted_at"])[:19]
            == "2027-01-26T09:00:00"
        )
        assert (
            str(submission["filing"]["repository_confirmed_at"])[:19]
            == str(confirmation["filing"]["repository_confirmed_at"])[:19]
            == "2027-01-28T14:00:00"
        )

        # Only the persisted timeliness_basis differs, and the verdicts diverge.
        assert submission["cycle"]["status"] == "FILED_TIMELY"
        assert confirmation["cycle"]["status"] == "FILED_LATE"
        assert submission["cycle"]["status"] != confirmation["cycle"]["status"]
        assert submission["cycle"]["days_late"] == 0
        assert confirmation["cycle"]["days_late"] == 2
        assert submission["undertaking"]["late_filing_count"] == 0
        assert confirmation["undertaking"]["late_filing_count"] == 1
        assert float(submission["undertaking"]["disclosure_risk_score"]) == 0.00
        assert float(confirmation["undertaking"]["disclosure_risk_score"]) == 12.00
        assert list_failure_events(undertaking_id=submission["undertaking"]["id"]) == []
        assert len(list_failure_events(undertaking_id=confirmation["undertaking"]["id"])) == 1


# --------------------------------------------------------------------------- #
# Instance 2 — the two official-statement lookback variants (PRD §3.9)
# --------------------------------------------------------------------------- #

class TestOfficialStatementLookbackVariants:
    """One identical two-event failure population under both lookback policies."""

    def test_strict_five_year_requires_both_events_and_reports_incomplete(self):
        """STRICT_FIVE_YEAR keeps the cured event, so two events are required.

        PRD §3.9: "Under `STRICT_FIVE_YEAR` the required set is the candidate set unchanged: every in-window failure must be described in the document, even ones already cured, which yields the larger required set."
        PRD §3.9: "Failure events in every `status` are candidates — `OPEN`, `REMEDIATION_PENDING`, and `REMEDIATED` alike."
        PRD §3.9: "`required_disclosure_event_ids` is the surviving set sorted by `occurred_at` ascending, ties broken by `created_at` ascending and never by id."
        PRD §3.9: "`disclosure_adequacy` is `ADEQUATE` when every id in `required_disclosure_event_ids` appears in `disclosed_event_ids`, and `INCOMPLETE` otherwise; ids in `disclosed_event_ids` that are not required are ignored rather than treated as errors, so an over-inclusive document is adequate."
        Design: Difficulty/dual_variant_calc/official_statement_lookback_strict_five_year_vs_remediated_excluded
        """
        context = _setup_program_with_two_late_cycles()
        event_one, event_two = context["event_one"], context["event_two"]

        strict = review_official_statement(context["statement"]["id"])

        assert_official_statement(strict)
        assert strict["lookback_policy"] == "STRICT_FIVE_YEAR"
        assert strict["required_disclosure_event_count"] == 2
        assert strict["required_disclosure_event_ids"] == [event_one["id"], event_two["id"]]
        assert strict["disclosed_event_ids"] == [event_two["id"]]
        assert strict["disclosure_adequacy"] == "INCOMPLETE"
        assert strict["status"] == "COMPLIANCE_REVIEW"

    def test_remediated_excluded_drops_the_cured_event_and_reports_adequate(self):
        """REMEDIATED_EXCLUDED drops the event cured before dated_date, leaving one.

        PRD §3.9: "Under `REMEDIATED_EXCLUDED` an event drops out when its `status` is `REMEDIATED` **and** the date part of its `remediated_at` is strictly before `dated_date`; a failure remediated on or after the dated date stays in."
        PRD §3.9: "Supplied `disclosed_event_ids` and `lookback_policy` overwrite the stored values wholesale, and omitted keys leave them untouched."
        Design: Difficulty/dual_variant_calc/official_statement_lookback_strict_five_year_vs_remediated_excluded
        """
        context = _setup_program_with_two_late_cycles()
        event_one, event_two = context["event_one"], context["event_two"]

        review_official_statement(context["statement"]["id"])
        excluded = review_official_statement(
            context["statement"]["id"], lookback_policy="REMEDIATED_EXCLUDED"
        )

        assert_official_statement(excluded)
        assert excluded["lookback_policy"] == "REMEDIATED_EXCLUDED"
        assert excluded["required_disclosure_event_count"] == 1
        assert excluded["required_disclosure_event_ids"] == [event_two["id"]]
        assert event_one["id"] not in excluded["required_disclosure_event_ids"]
        assert excluded["disclosure_adequacy"] == "ADEQUATE"
        assert excluded["status"] == "COMPLIANCE_REVIEW"

    def test_lookback_policies_diverge_over_the_identical_failure_population(self):
        """The STRICT/EXCLUDED delta is exactly the event remediated before dated_date.

        PRD §3.9: "For the identical failure population `REMEDIATED_EXCLUDED` therefore yields a smaller `required_disclosure_event_count` and can flip `disclosure_adequacy` from `INCOMPLETE` to `ADEQUATE`, which in turn decides whether the document may be posted at all."
        PRD §3.9: "**Compliance review** is the `ComplianceReviewer`'s act and is a repeatable self-loop: it is available from `DRAFT` and from `COMPLIANCE_REVIEW`, and it requires the statement's issue to be `OUTSTANDING`, failing which it is refused with `ERR_ISSUE_NOT_OUTSTANDING`."
        Design: Difficulty/dual_variant_calc/official_statement_lookback_strict_five_year_vs_remediated_excluded
        """
        context = _setup_program_with_two_late_cycles()
        event_one, event_two = context["event_one"], context["event_two"]

        strict = review_official_statement(context["statement"]["id"])
        excluded = review_official_statement(
            context["statement"]["id"], lookback_policy="REMEDIATED_EXCLUDED"
        )

        assert strict["required_disclosure_event_count"] == 2
        assert excluded["required_disclosure_event_count"] == 1
        assert excluded["required_disclosure_event_count"] < strict["required_disclosure_event_count"]
        assert strict["disclosure_adequacy"] == "INCOMPLETE"
        assert excluded["disclosure_adequacy"] == "ADEQUATE"

        delta = [
            event_id
            for event_id in strict["required_disclosure_event_ids"]
            if event_id not in excluded["required_disclosure_event_ids"]
        ]
        assert delta == [event_one["id"]]
        assert excluded["required_disclosure_event_ids"] == [event_two["id"]]

        # The second review is a self-loop, not an error.
        assert read_official_statement(context["statement"]["id"])["status"] == "COMPLIANCE_REVIEW"

    def test_both_in_window_events_survive_remediation_of_the_earlier_one(self):
        """Remediation closes e1 without decrementing the monotone late counter.

        PRD §3.8: "A `DisclosureOfficer` supplies a `remediation_filing_id` and a `remediation_note` against an event in `status` `OPEN` or `REMEDIATION_PENDING`, and the event moves to `REMEDIATED` with `remediated_at` stamped from the logical clock."
        PRD §3.8: "Both are **monotone**: remediating an event does not decrement them, because the historical failure still has to be disclosed."
        PRD §3.8: "`late_filing_count` is the number of that undertaking's failure events whose `kind` is `ANNUAL_REPORT_LATE` or `ANNUAL_REPORT_MISSED`."
        PRD §3.9: "Its left edge is `dated_date` less five calendar years — the same month and day five years earlier, with 29 February mapping to 28 February in a non-leap year — and that edge is inclusive."
        Design: Difficulty/dual_variant_calc/official_statement_lookback_strict_five_year_vs_remediated_excluded
        """
        context = _setup_program_with_two_late_cycles()
        event_one, event_two = context["event_one"], context["event_two"]

        assert context["cycle_one"]["due_date"] == DUE_DATE_FY2025
        assert context["cycle_two"]["due_date"] == DUE_DATE_FY2026

        # Both events sit inside the window [2022-03-01, 2027-03-01).
        assert str(event_one["occurred_at"])[:10] == DUE_DATE_FY2025
        assert str(event_two["occurred_at"])[:10] == DUE_DATE_FY2026

        assert event_one["days_late"] == 187
        assert event_one["severity"] == "MAJOR"
        assert event_two["days_late"] == 10
        assert event_two["severity"] == "MINOR"

        assert event_one["status"] == "REMEDIATED"
        assert str(event_one["remediated_at"])[:19] == "2027-02-06T08:00:00"
        assert event_one["remediation_filing_id"] == context["filing_one"]["id"]
        assert event_two["status"] == "OPEN"

        undertaking = read_undertaking(context["undertaking"]["id"])
        assert undertaking["late_filing_count"] == 2


# --------------------------------------------------------------------------- #
# Instance 3 — the pinned round-then-sum completeness order (PRD §3.3)
# --------------------------------------------------------------------------- #

class TestCompletenessScoreRoundingOrder:
    """The §3.3 worked example: weights 3333/3333/3333/1 must score 50.01."""

    def test_completeness_score_rounds_each_item_before_summation(self):
        """Three DRAFT items at 3333 bp each contribute 0.1667, summing to 50.01.

        PRD §3.3: "First, each item's contribution is its `weight_bp_snapshot` divided by 10000, multiplied by its readiness factor, multiplied by its opinion multiplier, and that product is rounded half-up to **4 decimal places**."
        PRD §3.3: "Second, those already-rounded contributions are summed exactly, with no further rounding of the sum."
        PRD §3.3: "Third, the sum is multiplied by 100 and rounded half-up to **2 decimal places** to give `completeness_score_pct`."
        PRD §3.3: "Under the pinned order each heavy item contributes 0.1667 after rounding to four places, the sum is 0.5001, and the score is 50.01."
        Design: Difficulty/combinatorial_formula/completeness_score_rounds_each_item_before_summation
        """
        context = _setup_rounding_cycle()
        third_item = _draft_three_heavy_items(context)

        assert third_item["status"] == "DRAFT"
        assert float(third_item["readiness_factor"]) == 0.5
        assert_readiness_matches_status(third_item)

        cycle = read_cycle(context["cycle"]["id"])
        assert_two_decimals(cycle["completeness_score_pct"], "completeness_score_pct")
        assert round(float(cycle["completeness_score_pct"]), 2) == 50.01

        # The weight-1 item never left NOT_STARTED and contributed 0.0000.
        enterprise = [
            item
            for item in list_content_items(context["cycle"]["id"])
            if item["id"] == context["enterprise"]["id"]
        ][0]
        assert enterprise["status"] == "NOT_STARTED"
        assert float(enterprise["readiness_factor"]) == 0.0

    def test_completeness_score_is_not_the_sum_then_round_result(self):
        """The rejected sum-then-round order would give 50.00; 50.01 is required.

        PRD §3.3: "The order is not interchangeable, and the alternative of summing unrounded contributions and rounding once at the end is explicitly rejected."
        PRD §3.3: "Under the rejected order the unrounded sum would be 0.49995 and the score would be 50.00."
        PRD §3.3: "Implementations must produce 50.01."
        Design: Difficulty/combinatorial_formula/completeness_score_rounds_each_item_before_summation
        """
        context = _setup_rounding_cycle()
        _draft_three_heavy_items(context)

        score = round(float(read_cycle(context["cycle"]["id"])["completeness_score_pct"]), 2)
        # 0.1667 * 3 == 0.5001 under the pinned order; 0.49995 under the rejected one.
        assert score != 50.00
        assert score == 50.01
        assert score > 50.00

    def test_snapshot_weights_and_opinion_multiplier_feed_the_rounding_case(self):
        """The inputs of the 50.01 case: 10000 bp closed, four snapshots, score 0.00.

        PRD §3.2: "Each accepted requirement re-derives the undertaking's `content_weight_bp_total` as the sum of `weight_bp` across all of that undertaking's requirements, which is the figure the weight-closure gate of §3.3 tests."
        PRD §3.2: "One further field, `requires_audit_opinion`, is derived rather than supplied: it is true when and only when `kind` is `AUDITED_FINANCIALS`, and any value a client sends for it is discarded."
        PRD §3.3: "One **`CycleContentItem`** is minted for each `ContentRequirement` of the undertaking, each carrying the `cycle_id` of the new cycle, the `content_requirement_id` of its source requirement, `status` `NOT_STARTED`, `readiness_factor` 0.0, and a `weight_bp_snapshot` copied from the requirement's `weight_bp` at that instant."
        PRD §3.3: "Where the requirement does demand an opinion, the multiplier is 1.0 for an `UNMODIFIED` opinion, 0.8 for a `QUALIFIED` one, 0.5 for `UNAUDITED_INTERIM`, and 0.0 when `audit_opinion_type` is still null."
        Design: Difficulty/combinatorial_formula/completeness_score_rounds_each_item_before_summation
        """
        context = _setup_rounding_cycle()

        assert context["undertaking"]["content_weight_bp_total"] == 10000
        requirements = {r["kind"]: r for r in context["requirements"]}
        assert requirements["AUDITED_FINANCIALS"]["requires_audit_opinion"] is True
        assert requirements["OPERATING_DATA_TABLE"]["requires_audit_opinion"] is False

        assert context["audited"]["weight_bp_snapshot"] == 3333
        assert context["operating"]["weight_bp_snapshot"] == 3333
        assert context["debt_service"]["weight_bp_snapshot"] == 3333
        assert context["enterprise"]["weight_bp_snapshot"] == 1
        assert all(item["status"] == "NOT_STARTED" for item in context["items"])
        assert float(context["cycle"]["completeness_score_pct"]) == 0.00

        # The AUDITED_FINANCIALS item carries UNMODIFIED, so its multiplier is 1.0.
        _draft_three_heavy_items(context)
        cycle = read_cycle(context["cycle"]["id"])
        assert round(float(cycle["completeness_score_pct"]), 2) == 50.01
        assert cycle["status"] == "DRAFTING"


# --------------------------------------------------------------------------- #
# Instance 4 — risk-score escalation on the persisted prior tier (PRD §3.8)
# --------------------------------------------------------------------------- #

SWEEP_CLOCKS = ("2026-08-04T00:00:00Z", "2026-08-06T00:00:00Z", "2026-08-08T00:00:00Z")


def _run_three_separate_sweeps(context: dict) -> list:
    """Sweep once per deadline day, capturing the undertaking after each pass."""
    stages = []
    for clock in SWEEP_CLOCKS:
        set_clock(clock)
        sweep = run_sweep()
        stages.append(
            {"sweep": sweep, "undertaking": read_undertaking(context["undertaking"]["id"])}
        )
    return stages


class TestRiskScoreEscalationOnPersistedTier:
    """The §3.8 worked chain: 20.00/TIER_0 -> 40.00/TIER_1 -> 66.00/TIER_2."""

    def test_risk_score_escalates_on_the_persisted_prior_tier(self):
        """Three separate sweeps walk the pinned 20.00 / 40.00 / 66.00 chain.

        PRD §3.8: "Let L be `late_filing_count`, M be `missed_event_count`, D be `delinquent_cycle_count`, and let T be the undertaking's **persisted** `remediation_tier` as it stood before this pass."
        PRD §3.8: "After the first, the base is 20, the persisted tier is `TIER_0`, the score is 20.00, and the new tier is `TIER_0`."
        PRD §3.8: "After the second, the base is 40, the persisted tier is still `TIER_0`, the score is 40.00, and the new tier becomes `TIER_1`."
        PRD §3.8: "After the third, the base is 60, the persisted tier is `TIER_1`, so the score is 66.00 and the new tier becomes `TIER_2`."
        PRD §3.8: "Step 4 derives the new `remediation_tier` from the score just written, using inclusive lower bounds: `TIER_3` at 75.00 or above, else `TIER_2` at 50.00 or above, else `TIER_1` at 25.00 or above, else `TIER_0`."
        Design: Difficulty/combinatorial_formula/risk_score_escalates_on_the_persisted_prior_tier
        """
        context = _setup_three_material_notices()
        assert context["undertaking"]["remediation_tier"] == "TIER_0"
        assert float(context["undertaking"]["disclosure_risk_score"]) == 0.00

        stages = _run_three_separate_sweeps(context)
        first, second, third = (stage["undertaking"] for stage in stages)

        assert first["missed_event_count"] == 1
        assert float(first["disclosure_risk_score"]) == 20.00
        assert first["remediation_tier"] == "TIER_0"
        assert first["compliance_posture"] == "COMPLIANT"

        assert second["missed_event_count"] == 2
        assert float(second["disclosure_risk_score"]) == 40.00
        assert second["remediation_tier"] == "TIER_1"
        assert second["compliance_posture"] == "WATCH"

        assert third["missed_event_count"] == 3
        assert float(third["disclosure_risk_score"]) == 66.00
        assert third["remediation_tier"] == "TIER_2"
        assert third["compliance_posture"] == "IMPAIRED"

        for undertaking in (first, second, third):
            assert_undertaking(undertaking)
            assert undertaking["delinquent_cycle_count"] == 0
            assert undertaking["late_filing_count"] == 0
            assert_two_decimals(undertaking["disclosure_risk_score"], "disclosure_risk_score")
            assert_tier_matches_score(undertaking)
            assert_undertaking_posture_consistent(undertaking)

    def test_third_pass_reads_the_persisted_tier_one_not_the_derived_tier_two(self):
        """66.00 is base 60 times 1.10; reading the fresh TIER_2 would give 75.00.

        PRD §3.8: "Reading the tier this pass is about to derive, instead of the one persisted from the previous pass, would give 75.00 and `TIER_3` on the third pass."
        PRD §3.8: "Step 2 escalates that base by the tier multiplier for T — 1.00 for `TIER_0`, 1.10 for `TIER_1`, 1.25 for `TIER_2`, 1.40 for `TIER_3` — and rounds the product half-up to 2 decimal places."
        PRD §3.8: "The pass runs **exactly once** per trigger and is never iterated to a fixed point, so `disclosure_risk_score` and `remediation_tier` may legitimately disagree by one escalation step until the next trigger fires."
        Design: Difficulty/combinatorial_formula/risk_score_escalates_on_the_persisted_prior_tier
        """
        context = _setup_three_material_notices()
        stages = _run_three_separate_sweeps(context)

        # The tier persisted by the second pass is the multiplier input of the third.
        assert stages[1]["undertaking"]["remediation_tier"] == "TIER_1"

        score = float(stages[2]["undertaking"]["disclosure_risk_score"])
        assert score == 66.00
        assert score != 75.00  # reading the freshly derived TIER_2 (1.25) instead
        assert score != 60.00  # collapsing the three sweeps into one pass
        assert stages[2]["undertaking"]["remediation_tier"] == "TIER_2"

    def test_ten_business_day_deadlines_strand_one_notice_per_sweep(self):
        """The three deadlines land on 2026-08-03, 2026-08-05 and 2026-08-07.

        PRD §3.5: "And `filing_deadline_date` is the **tenth business day strictly after** `occurrence_date`, computed with the add-business-days rule of §2.6: the occurrence date itself is never counted whether or not it is a business day, and the result is the tenth business day encountered walking forward."
        PRD §3.5: "`per_se_material` is true if and only if `event_type` is one of the four per-se listed events — `PRINCIPAL_PAYMENT_DELINQUENCY`, `RATING_CHANGE`, `DEFEASANCE`, `BOND_CALL` — and false for the other four."
        PRD §3.11: "Every `MaterialEventNotice` in `status` `MATERIAL` whose `filing_deadline_date` is strictly before the logical clock's date moves to `MISSED`, with `days_late` set to the calendar days from `filing_deadline_date` to the clock date."
        Design: Difficulty/combinatorial_formula/risk_score_escalates_on_the_persisted_prior_tier
        """
        context = _setup_three_material_notices()
        first, second, third = context["notices"]

        assert first["filing_deadline_date"] == "2026-08-03"
        assert second["filing_deadline_date"] == "2026-08-05"
        assert third["filing_deadline_date"] == "2026-08-07"
        assert first["per_se_material"] is False
        assert second["per_se_material"] is False
        assert third["per_se_material"] is False

        stages = _run_three_separate_sweeps(context)
        assert [stage["sweep"]["missed_event_count"] for stage in stages] == [1, 1, 1]
        assert read_notice(first["id"])["status"] == "MISSED"
        assert read_notice(second["id"])["status"] == "MISSED"
        assert read_notice(third["id"])["status"] == "MISSED"

    def test_each_sweep_mints_exactly_one_major_missed_event_failure(self):
        """Only step 3 fires: one MATERIAL_EVENT_MISSED failure per sweep, all MAJOR.

        PRD §3.11: "Each mints a `FailureToFileEvent` with `kind` `MATERIAL_EVENT_MISSED`, `material_event_id` set to the notice, `cycle_id` null, `occurred_at` set to the notice's `filing_deadline_date`, `severity` `MAJOR`, and `status` `OPEN`."
        PRD §3.11: "It reports `swept_at`, the logical-clock instant of the sweep, alongside five counts: `matured_issue_count` for step 1, `delinquent_cycle_count` for step 2, `missed_event_count` for step 3, `suspended_engagement_count` for step 4, and `failure_event_created_count` for every `FailureToFileEvent` minted across steps 2 and 3 together."
        PRD §3.8: "`missed_event_count` is the number whose `kind` is `MATERIAL_EVENT_MISSED`."
        Design: Difficulty/combinatorial_formula/risk_score_escalates_on_the_persisted_prior_tier
        """
        context = _setup_three_material_notices()
        stages = _run_three_separate_sweeps(context)

        for stage in stages:
            sweep = stage["sweep"]
            assert sweep["missed_event_count"] == 1
            assert sweep["failure_event_created_count"] == 1
            assert sweep["delinquent_cycle_count"] == 0
            assert sweep["suspended_engagement_count"] == 0
            assert sweep["matured_issue_count"] == 0

        events = list_failure_events(undertaking_id=context["undertaking"]["id"])
        assert len(events) == 3
        for event in events:
            assert_failure_to_file_event(event)
            assert event["kind"] == "MATERIAL_EVENT_MISSED"
            assert event["severity"] == "MAJOR"
            assert event["cycle_id"] is None
        assert sorted(str(event["occurred_at"])[:10] for event in events) == [
            "2026-08-03",
            "2026-08-05",
            "2026-08-07",
        ]
        assert stages[2]["undertaking"]["missed_event_count"] == 3
