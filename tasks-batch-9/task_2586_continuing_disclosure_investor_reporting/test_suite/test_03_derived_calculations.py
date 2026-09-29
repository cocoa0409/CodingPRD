"""Derived calculations: due dates, deadlines, counters, invoices, scores.

Every test in this module translates exactly one instance of the `calculations`
section of SCAFFOLD_CORNER_DESIGN.yaml.  Each test starts against an empty
database whose logical clock reads its startup value 2026-08-01T00:00:00Z.
"""

import pytest

from test_helpers import (
    ApiErrorId,
    annual_report_cycle_payload,
    api_client,
    assert_annual_report_cycle,
    assert_dissemination_engagement,
    assert_direct_placement,
    assert_failure_to_file_event,
    assert_material_event_notice,
    assert_score,
    assert_severity_matches_kind_and_days_late,
    assert_tier_matches_score,
    assert_two_decimals,
    assert_undertaking,
    assert_undertaking_posture_consistent,
    assemble,
    attest_item,
    create_annual_report_filing,
    create_bond_issue,
    create_event_filing,
    create_notice,
    create_placement,
    create_undertaking,
    classify_placement,
    determine_notice,
    direct_placement_payload,
    item_for_requirement,
    list_content_items,
    list_failure_events,
    list_notices,
    make_officer_headers,
    material_event_notice_payload,
    prepare_item,
    read_bond_issue,
    read_content_item,
    read_cycle,
    read_engagement,
    read_placement,
    read_undertaking,
    ready_item,
    run_sweep,
    set_clock,
    setup_cycle,
    setup_cycle_with_engagement,
    setup_filed_annual_report,
    setup_undertaking_with_requirements,
    sole_failure_event_for_cycle,
    submit_and_confirm,
    validate_error,
    validate_success,
    withdraw,
)

OFFICER_HEADERS = make_officer_headers()

# A single requirement closing at exactly 10000 basis points and demanding no
# audit opinion, so a cycle built on it can reach READY with no opinion penalty.
OPS_ONLY_SPECS = [
    {"kind": "OPERATING_DATA_TABLE", "label": "Operating Data Tables", "weight_bp": 10000},
]

# Two requirements: 6000 basis points of audited financials plus 4000 of
# operating data, the fixture the weight-snapshot instance is built on.
SIX_FOUR_SPECS = [
    {"kind": "AUDITED_FINANCIALS", "label": "Audited Financial Statements", "weight_bp": 6000},
    {"kind": "OPERATING_DATA_TABLE", "label": "Operating Data Tables", "weight_bp": 4000},
]

HUNDRED_MILLION_PAR = {"original_par_amount_cents": 100000000}


def open_cycle(undertaking_id, fiscal_year_label, period_start_date, period_end_date):
    """Open one reporting cycle through the officer's own endpoint, strictly."""
    payload = annual_report_cycle_payload(
        undertaking_id,
        fiscal_year_label=fiscal_year_label,
        period_start_date=period_start_date,
        period_end_date=period_end_date,
    )
    return validate_success(
        api_client.create_annual_report_cycle(payload, OFFICER_HEADERS), 201
    )


class TestAnnualReportDueDate:
    """The 210 calendar days are added first; only the landing date is rolled."""

    @pytest.mark.parametrize(
        "fiscal_year_end_month_day,fiscal_year_label,period_start_date,period_end_date,expected_due_date",
        [
            # 2026-01-31 + 210 days lands on Saturday 2026-08-29 and rolls two days.
            ("01-31", "FY2026-JAN", "2025-02-01", "2026-01-31", "2026-08-31"),
            # 2026-04-30 + 210 days lands on the 2026-11-26 holiday and rolls one day.
            ("04-30", "FY2026-APR", "2025-05-01", "2026-04-30", "2026-11-27"),
            # 2026-05-29 + 210 days lands on the Friday 2026-12-25 holiday and rolls three.
            ("05-29", "FY2026-MAY", "2025-05-30", "2026-05-29", "2026-12-28"),
            # 2026-06-30 + 210 days lands on a Tuesday and must not move at all.
            ("06-30", "FY2026-JUN", "2025-07-01", "2026-06-30", "2027-01-26"),
        ],
    )
    def test_due_date_adds_calendar_days_then_rolls_forward_only_when_needed(
        self,
        fiscal_year_end_month_day,
        fiscal_year_label,
        period_start_date,
        period_end_date,
        expected_due_date,
    ):
        """The due date is period_end_date plus the calendar window, rolled forward.

        PRD §3.3: "Take the cycle's own `period_end_date`, advance it by the owning undertaking's `filing_window_days` in **calendar** days, then roll the result forward — never backward — to the first business day at or after it, using the calendar of §2.6."
        PRD §2.6: "**Rolling forward to a business day** walks a date forward one calendar day at a time until it lands on a business day, and returns the date unchanged when it is already one."
        PRD §3.2: "`filing_window_days` is the number of calendar days after a reporting period ends by which the annual report is due; it accepts any integer from 1 through 365 and defaults to 210 when omitted."
        Design: Corner/calculations/annual_report_due_date_rolls_forward_over_weekends_and_holidays
        """
        context = setup_undertaking_with_requirements(
            specs=OPS_ONLY_SPECS,
            issue=HUNDRED_MILLION_PAR,
            undertaking={"fiscal_year_end_month_day": fiscal_year_end_month_day},
        )
        undertaking = read_undertaking(context["undertaking"]["id"])
        assert undertaking["filing_window_days"] == 210, (
            "filing_window_days defaults to 210 when omitted"
        )

        cycle = open_cycle(
            context["undertaking"]["id"],
            fiscal_year_label,
            period_start_date,
            period_end_date,
        )

        assert_annual_report_cycle(cycle)
        assert cycle["due_date"] == expected_due_date, (
            f"Expected due_date {expected_due_date} for a period ending "
            f"{period_end_date}, got {cycle['due_date']}"
        )
        assert cycle["status"] == "DRAFTING"


class TestMaterialEventFilingDeadline:
    """The ten-business-day window consumes the market-holiday constant."""

    @pytest.mark.parametrize(
        "clock,event_type,occurrence_date,expected_deadline_date",
        [
            # Saturday 2026-08-01 is not counted, so day one is Monday 2026-08-03.
            (None, "TRUSTEE_SUBSTITUTION", "2026-08-01", "2026-08-14"),
            # Ten clean business days from Friday 2026-07-24.
            (None, "UNSCHEDULED_DRAW_ON_RESERVE", "2026-07-24", "2026-08-07"),
            # The window from Monday 2026-08-24 must skip the 2026-09-07 holiday.
            ("2026-08-24T00:00:00Z", "MERGER_OR_SALE", "2026-08-24", "2026-09-08"),
        ],
    )
    def test_filing_deadline_is_the_tenth_business_day_strictly_after_occurrence(
        self, clock, event_type, occurrence_date, expected_deadline_date
    ):
        """The deadline skips weekends and the recognised market holidays alike.

        PRD §3.5: "And `filing_deadline_date` is the **tenth business day strictly after** `occurrence_date`, computed with the add-business-days rule of §2.6: the occurrence date itself is never counted whether or not it is a business day, and the result is the tenth business day encountered walking forward."
        PRD §2.6: "The recognised market holidays are exactly these fourteen dates: 2026-07-03, 2026-09-07, 2026-10-12, 2026-11-11, 2026-11-26, 2026-12-25, 2027-01-01, 2027-01-18, 2027-02-15, 2027-05-31, 2027-07-05, 2027-09-06, 2027-11-25, and 2027-12-24."
        Design: Corner/calculations/material_event_deadline_applies_the_market_holiday_constant
        """
        issue = create_bond_issue(**HUNDRED_MILLION_PAR)
        if clock is not None:
            echoed = set_clock(clock)
            assert echoed["current_utc"] == clock, "the clock endpoint echoes current_utc"

        notice = validate_success(
            api_client.create_material_event_notice(
                material_event_notice_payload(
                    issue["id"], event_type=event_type, occurrence_date=occurrence_date
                ),
                OFFICER_HEADERS,
            ),
            201,
        )

        assert_material_event_notice(notice)
        assert notice["filing_deadline_date"] == expected_deadline_date, (
            f"Expected filing_deadline_date {expected_deadline_date} for an occurrence "
            f"on {occurrence_date}, got {notice['filing_deadline_date']}"
        )
        assert notice["status"] == "DETERMINATION_PENDING"


def test_open_obligation_count_counts_open_cycles_plus_open_notices_of_the_issue():
    """Two open cycles plus two pending notices make four; a withdrawal and an
    immateriality determination take it back to two.

    PRD §3.2: "All four counters — `late_filing_count`, `missed_event_count`, `delinquent_cycle_count`, and `open_obligation_count` — start at 0, and so does `content_weight_bp_total`."
    PRD §3.3: "The undertaking's `open_obligation_count` is re-derived, and the new cycle raises it."
    PRD §3.5: "Creation also re-derives the issue's `open_material_event_count` and the undertaking's `open_obligation_count`, because a `DETERMINATION_PENDING` notice is an open obligation."
    PRD §3.4: "And the undertaking's `open_obligation_count` is re-derived from source, which is what makes the compensation exact: withdrawing a cycle created moments earlier must restore `open_obligation_count` to precisely the value it held before the creation."
    PRD §3.5: "A `NOT_MATERIAL` determination is terminal and releases the obligation: the notice leaves the open set, both counters fall, no `filing_deadline_date` enforcement ever applies to it again, the calendar sweep skips it permanently, and any later filing that names it is refused with `ERR_FILING_SUBJECT_MISMATCH`."
    Design: Corner/calculations/open_obligation_count_includes_only_open_cycles_and_open_notices
    """
    issue = create_bond_issue(**HUNDRED_MILLION_PAR)
    undertaking = create_undertaking(issue["id"], fiscal_year_end_month_day="06-30")
    assert undertaking["open_obligation_count"] == 0, (
        "open_obligation_count starts at 0 on a fresh undertaking"
    )
    create_requirement = api_client.create_content_requirement(
        {
            "undertaking_id": undertaking["id"],
            "kind": "OPERATING_DATA_TABLE",
            "label": "Operating Data Tables",
            "weight_bp": 10000,
        },
        OFFICER_HEADERS,
    )
    validate_success(create_requirement, 201)

    cycle_2025 = open_cycle(undertaking["id"], "FY2025", "2024-07-01", "2025-06-30")
    open_cycle(undertaking["id"], "FY2026", "2025-07-01", "2026-06-30")
    assert read_undertaking(undertaking["id"])["open_obligation_count"] == 2, (
        "both DRAFTING cycles count as open obligations"
    )

    notice_keep = create_notice(
        issue["id"], event_type="TRUSTEE_SUBSTITUTION", occurrence_date="2026-07-28"
    )
    notice_drop = create_notice(
        issue["id"], event_type="MERGER_OR_SALE", occurrence_date="2026-07-28"
    )
    assert read_undertaking(undertaking["id"])["open_obligation_count"] == 4, (
        "the two DETERMINATION_PENDING notices of the same issue join the count"
    )

    withdrawn = withdraw(cycle_2025["id"], "Combined into the FY2026 report.")
    assert withdrawn["status"] == "WITHDRAWN"
    determined = determine_notice(
        notice_drop["id"], "NOT_MATERIAL", "No change of control occurred."
    )
    assert determined["status"] == "NOT_MATERIAL"

    final_undertaking = read_undertaking(undertaking["id"])
    assert_undertaking(final_undertaking)
    assert final_undertaking["open_obligation_count"] == 2, (
        "the WITHDRAWN cycle and the NOT_MATERIAL notice both leave their input sets"
    )
    final_issue = read_bond_issue(issue["id"])
    assert final_issue["open_material_event_count"] == 1, (
        "the issue's open_material_event_count tracks only the notice half"
    )
    assert read_notice_status(notice_keep["id"]) == "DETERMINATION_PENDING"


def read_notice_status(notice_id):
    """Read one listed-event notice's own status through its list channel."""
    rows = [n for n in list_notices() if n["id"] == notice_id]
    assert len(rows) == 1, f"Expected exactly one notice row for {notice_id}"
    return rows[0]["status"]


def test_invoice_floor_binds_then_the_tier_two_marginal_rate_takes_over():
    """One engagement walked from F=0 to F=5: the floor dominates twice, then the
    tier-one rate adds 45000 a filing until the fifth filing adds only 32500.

    PRD §3.10: "In cents: take the lesser of F and 4 at 45000 cents, plus the lesser of 5 and the excess of F over 4 (floored at zero) at 32500 cents, plus the excess of F over 9 (floored at zero) at 25000 cents."
    PRD §3.10: "The cap and the floor then apply in this exact nested order: the subtotal plus surcharge is first capped at 12,000 dollars (1200000 cents), and that capped figure is then raised to the minimum annual fee of 3,000 dollars (300000 cents) if it falls below it."
    PRD §3.10: "With F of 1, a `retainer_cents` of 250000, and posture `COMPLIANT`: the subtotal is 295000, the surcharge is 0, the capped figure is 295000, and `invoice_total_cents` is 300000 — the floor binds."
    PRD §3.10: "For any other posture the surcharge is zero."
    Design: Corner/calculations/invoice_floor_binds_then_the_tier_two_marginal_rate_takes_over
    """
    context = setup_cycle_with_engagement(specs=OPS_ONLY_SPECS, issue=HUNDRED_MILLION_PAR)
    issue_id = context["issue"]["id"]
    engagement_id = context["engagement"]["id"]

    assert_dissemination_engagement(context["engagement"])
    assert context["engagement"]["retainer_cents"] == 250000
    assert context["engagement"]["billable_filing_count"] == 0, (
        "no filing has been confirmed yet, so F is 0"
    )
    assert context["engagement"]["invoice_total_cents"] == 300000, (
        "with F=0 the raw subtotal is the bare 250000 retainer and the floor lifts it to 300000"
    )

    annual_filing = create_annual_report_filing(issue_id, context["cycle"]["id"])
    submit_and_confirm(annual_filing["id"], engagement_id, "EMMA-0001")

    after_first = read_engagement(engagement_id)
    assert after_first["billable_filing_count"] == 1
    assert after_first["invoice_total_cents"] == 300000, (
        "the first confirmed filing raises the raw subtotal to 295000, which the floor "
        "still dominates, so the invoice does not move"
    )
    assert read_cycle(context["cycle"]["id"])["status"] == "FILED_TIMELY"

    notice_specs = [
        ("TRUSTEE_SUBSTITUTION", "EMMA-0002", 340000),
        ("MERGER_OR_SALE", "EMMA-0003", 385000),
        ("UNSCHEDULED_DRAW_ON_RESERVE", "EMMA-0004", 430000),
        ("FINANCIAL_OBLIGATION_INCURRENCE", "EMMA-0005", 462500),
    ]
    expected_filing_count = 1
    for event_type, receipt_id, expected_invoice_cents in notice_specs:
        notice = create_notice(
            issue_id, event_type=event_type, occurrence_date="2026-07-28"
        )
        determine_notice(notice["id"], "MATERIAL", "Material to bondholders.")
        event_filing = create_event_filing(issue_id, notice["id"])
        submit_and_confirm(event_filing["id"], engagement_id, receipt_id)

        expected_filing_count += 1
        engagement = read_engagement(engagement_id)
        assert engagement["billable_filing_count"] == expected_filing_count
        assert engagement["invoice_total_cents"] == expected_invoice_cents, (
            f"Expected invoice_total_cents {expected_invoice_cents} at F="
            f"{expected_filing_count}, got {engagement['invoice_total_cents']}"
        )

    final_engagement = read_engagement(engagement_id)
    assert final_engagement["billable_filing_count"] == 5
    assert final_engagement["invoice_total_cents"] == 462500, (
        "the fifth filing is priced at the tier-two rate: 250000 + 4*45000 + 1*32500"
    )
    assert final_engagement["status"] == "ACTIVE"
    undertaking = read_undertaking(context["undertaking"]["id"])
    assert undertaking["compliance_posture"] == "COMPLIANT", (
        "every filing was timely, so no surcharge ever entered the arithmetic"
    )
    assert_undertaking_posture_consistent(undertaking)


class TestDirectPlacementMateriality:
    """One basis point of a 100,000,000-cent par is 10000 cents, so the four
    probes sit at 499, 499.5, 500.0 and 501 basis points."""

    @pytest.mark.parametrize(
        "principal_amount_cents,disclosure_practice,window_start,window_end,expected_bp,expected_status",
        [
            (4990000, "VOLUNTARY", "2026-08-03", "2026-08-05", 499, "DISCLOSURE_WAIVED"),
            (4995000, "VOLUNTARY", "2026-08-06", "2026-08-08", 500, "DISCLOSURE_REQUIRED"),
            (5000000, "VOLUNTARY", "2026-08-09", "2026-08-11", 500, "DISCLOSURE_REQUIRED"),
            (5010000, "VOLUNTARY", "2026-08-12", "2026-08-14", 501, "DISCLOSURE_REQUIRED"),
            (
                3000000,
                "MANDATORY_MATERIAL_EVENT",
                "2026-08-15",
                "2026-08-17",
                300,
                "DISCLOSURE_REQUIRED",
            ),
        ],
    )
    def test_ratio_rounds_half_up_and_the_five_hundred_bp_threshold_is_inclusive(
        self,
        principal_amount_cents,
        disclosure_practice,
        window_start,
        window_end,
        expected_bp,
        expected_status,
    ):
        """499.5 basis points rounds half-up to 500 and is therefore inside the
        inclusive threshold, while a mandatory practice satisfies the other arm.

        PRD §3.6: "`materiality_ratio_bp` is derived once, at creation, as `principal_amount_cents` multiplied by 10000, divided by the issue's `outstanding_par_amount_cents`, rounded half-up to a whole basis point."
        PRD §3.6: "The placement becomes `DISCLOSURE_REQUIRED` when `materiality_ratio_bp` is **greater than or equal to** 500, or when `disclosure_practice` is `MANDATORY_MATERIAL_EVENT` regardless of the ratio."
        PRD §3.6: "A principal of 5,000,000 cents against outstanding par of 100,000,000 cents is exactly 500 basis points and classifies as `DISCLOSURE_REQUIRED`; a principal of 4,990,000 cents against the same par rounds to 499 basis points and classifies as `DISCLOSURE_WAIVED`."
        PRD §2.7: "All rounding in this service is round-half-up: a value exactly at the midpoint rounds away from zero."
        Design: Corner/calculations/materiality_ratio_rounds_half_up_at_the_five_hundred_bp_threshold
        """
        issue = create_bond_issue(**HUNDRED_MILLION_PAR)
        assert issue["outstanding_par_amount_cents"] == 100000000

        placement = validate_success(
            api_client.create_direct_placement(
                direct_placement_payload(
                    issue["id"],
                    lender_name="Harbor National Bank",
                    principal_amount_cents=principal_amount_cents,
                    execution_date="2026-07-28",
                    review_window_start_date=window_start,
                    review_window_end_date=window_end,
                    disclosure_practice=disclosure_practice,
                ),
                OFFICER_HEADERS,
            ),
            201,
        )
        assert_direct_placement(placement)
        assert placement["materiality_ratio_bp"] == expected_bp, (
            f"Expected materiality_ratio_bp {expected_bp} for a principal of "
            f"{principal_amount_cents}, got {placement['materiality_ratio_bp']}"
        )
        assert placement["status"] == "RECEIVED"

        if expected_status == "DISCLOSURE_WAIVED":
            classified = classify_placement(
                placement["id"],
                waiver_reason="Below the materiality threshold and practice is voluntary.",
            )
            assert classified["status"] == "DISCLOSURE_WAIVED"
            assert classified["waiver_reason"] == (
                "Below the materiality threshold and practice is voluntary."
            )
            assert classified["linked_notice_id"] is None, (
                "the waived branch creates no notice and leaves linked_notice_id null"
            )
        else:
            classified = classify_placement(placement["id"])
            assert classified["status"] == "DISCLOSURE_REQUIRED"
            assert classified["linked_notice_id"] is not None, (
                "the required branch mints a notice and stores its id in linked_notice_id"
            )
        assert classified["materiality_ratio_bp"] == expected_bp, (
            "materiality_ratio_bp is frozen at creation"
        )

    def test_disclosure_required_mints_a_financial_obligation_notice_on_the_execution_date(
        self,
    ):
        """The 499.5-basis-point placement classifies as required and mints exactly
        one notice dated on the placement's execution date.

        PRD §3.6: "That branch mints a `MaterialEventNotice` with `event_type` `FINANCIAL_OBLIGATION_INCURRENCE`, `issue_id` copied from the placement, `occurrence_date` set to the placement's `execution_date`, `financial_obligation_ref` pointing back at the placement, `per_se_material` false, and `status` `DETERMINATION_PENDING`, with its own `filing_deadline_date` ten business days after that occurrence date; the new notice's id is stored in `linked_notice_id`, and the issue's `open_material_event_count` and the undertaking's `open_obligation_count` are both re-derived."
        Design: Corner/calculations/materiality_ratio_rounds_half_up_at_the_five_hundred_bp_threshold
        """
        issue = create_bond_issue(**HUNDRED_MILLION_PAR)
        placement = create_placement(
            issue["id"],
            lender_name="Harbor National Bank",
            principal_amount_cents=4995000,
            execution_date="2026-07-28",
            review_window_start_date="2026-08-06",
            review_window_end_date="2026-08-08",
            disclosure_practice="VOLUNTARY",
        )
        assert placement["materiality_ratio_bp"] == 500

        classified = classify_placement(placement["id"])
        assert classified["status"] == "DISCLOSURE_REQUIRED"

        notices = list_notices(financial_obligation_ref=placement["id"])
        assert len(notices) == 1, (
            f"Expected exactly one notice pointing back at the placement, got {len(notices)}"
        )
        notice = notices[0]
        assert_material_event_notice(notice)
        assert notice["id"] == classified["linked_notice_id"]
        assert notice["event_type"] == "FINANCIAL_OBLIGATION_INCURRENCE"
        assert notice["occurrence_date"] == "2026-07-28", (
            "occurrence_date is set to the placement's execution_date"
        )
        assert notice["per_se_material"] is False
        assert notice["status"] == "DETERMINATION_PENDING"
        assert notice["issue_id"] == issue["id"]
        assert read_placement(placement["id"])["linked_notice_id"] == notice["id"]
        assert read_bond_issue(issue["id"])["open_material_event_count"] == 1


def test_late_filing_count_is_monotone_while_delinquent_cycle_count_is_live():
    """A swept-delinquent cycle drives the score to 27.00 and the posture to
    DELINQUENT; reassembling it releases only the live counter, leaving 13.20.

    PRD §3.11: "Every `AnnualReportCycle` in `status` `DRAFTING` or `READY_TO_FILE` whose `due_date` is strictly before the logical clock's date moves to `DELINQUENT`, with `assembled_by_user_id` and `assembled_at` cleared."
    PRD §3.8: "`late_filing_count` is the number of that undertaking's failure events whose `kind` is `ANNUAL_REPORT_LATE` or `ANNUAL_REPORT_MISSED`."
    PRD §3.8: "`missed_event_count` is the number whose `kind` is `MATERIAL_EVENT_MISSED`."
    PRD §3.8: "`delinquent_cycle_count` is the number of that undertaking's cycles currently in `status` `DELINQUENT`, and it is **live** — a cycle leaving `DELINQUENT` for `FILED_LATE` or `READY_TO_FILE` decrements it, which is what lets `compliance_posture` recover."
    PRD §3.8: "Step 1 forms an additive base of 12 times L, plus 20 times M, plus 15 times D."
    PRD §3.8: "Step 2 escalates that base by the tier multiplier for T — 1.00 for `TIER_0`, 1.10 for `TIER_1`, 1.25 for `TIER_2`, 1.40 for `TIER_3` — and rounds the product half-up to 2 decimal places."
    PRD §3.8: "Step 6 derives `compliance_posture`, and here any delinquent cycle dominates the score bands outright: the posture is `DELINQUENT` whenever D is 1 or more, regardless of score; otherwise `IMPAIRED` at a score of 50.00 or above; otherwise `WATCH` at 25.00 or above; otherwise `COMPLIANT`."
    PRD §3.4: "What it does not do is erase history: the `FailureToFileEvent` that the sweep already minted against the cycle stays exactly where it is."
    Design: Corner/calculations/late_filing_count_is_monotone_while_delinquent_cycle_count_is_live
    """
    context = setup_cycle(specs=OPS_ONLY_SPECS, issue=HUNDRED_MILLION_PAR)
    undertaking_id = context["undertaking"]["id"]
    cycle_id = context["cycle"]["id"]
    assert context["cycle"]["due_date"] == "2027-01-26"
    fresh = read_undertaking(undertaking_id)
    assert_score(fresh["disclosure_risk_score"], 0.00, "disclosure_risk_score")
    assert fresh["remediation_tier"] == "TIER_0"
    assert fresh["compliance_posture"] == "COMPLIANT"

    echoed = set_clock("2027-02-01T00:00:00Z")
    assert echoed["current_utc"] == "2027-02-01T00:00:00Z"
    sweep = run_sweep()
    assert sweep["delinquent_cycle_count"] == 1
    assert sweep["failure_event_created_count"] == 1
    assert sweep["matured_issue_count"] == 0

    events = list_failure_events(undertaking_id=undertaking_id)
    assert len(events) == 1
    event = events[0]
    assert_failure_to_file_event(event)
    assert event["kind"] == "ANNUAL_REPORT_MISSED"
    assert event["severity"] == "MAJOR"
    assert event["days_late"] == 6, (
        "the days late run from the 2027-01-26 due date to the 2027-02-01 sweep date"
    )
    assert event["status"] == "OPEN"

    delinquent = read_undertaking(undertaking_id)
    assert delinquent["late_filing_count"] == 1, (
        "an ANNUAL_REPORT_MISSED failure belongs to late_filing_count"
    )
    assert delinquent["missed_event_count"] == 0, (
        "missed_event_count counts only MATERIAL_EVENT_MISSED failures"
    )
    assert delinquent["delinquent_cycle_count"] == 1
    assert_score(delinquent["disclosure_risk_score"], 27.00, "disclosure_risk_score")
    assert delinquent["remediation_tier"] == "TIER_1"
    assert delinquent["compliance_posture"] == "DELINQUENT", (
        "the posture is forced by delinquent_cycle_count >= 1, not by the score band"
    )
    assert_tier_matches_score(delinquent)
    assert_undertaking_posture_consistent(delinquent)
    assert read_cycle(cycle_id)["status"] == "DELINQUENT"

    item = list_content_items(cycle_id)[0]
    ready_item(item["id"])
    reassembled = assemble(cycle_id)
    assert reassembled["status"] == "READY_TO_FILE"

    recovered = read_undertaking(undertaking_id)
    assert recovered["delinquent_cycle_count"] == 0, (
        "the live counter releases the moment the cycle leaves DELINQUENT"
    )
    assert recovered["late_filing_count"] == 1, (
        "the monotone counter does not release; the recorded failure survives recovery"
    )
    assert_score(recovered["disclosure_risk_score"], 13.20, "disclosure_risk_score")
    assert_two_decimals(recovered["disclosure_risk_score"], "disclosure_risk_score")
    assert recovered["remediation_tier"] == "TIER_0"
    assert recovered["compliance_posture"] == "COMPLIANT"
    assert recovered["status"] == "ACTIVE", (
        "the undertaking's own lifecycle status never moved while its posture recovered"
    )

    after_events = list_failure_events(undertaking_id=undertaking_id)
    assert len(after_events) == 1
    assert after_events[0]["status"] == "OPEN", (
        "recovery neither deletes nor closes the failure event; only remediation does"
    )


class TestFailureSeverityThirtyDayBoundary:
    """Two cycles sharing the 2027-01-26 due date, confirmed one day apart."""

    def test_severity_is_minor_at_twenty_nine_days_late(self):
        """29 days late is strictly below the boundary and stays MINOR.

        PRD §3.8: "`severity` is `MAJOR` when `kind` is `ANNUAL_REPORT_MISSED` or `MATERIAL_EVENT_MISSED`, or when `days_late` is **greater than or equal to** 30; it is `MINOR` otherwise."
        PRD §3.8: "For an `ANNUAL_REPORT_LATE` event the boundary is exact: 29 days late is `MINOR`, 30 days late is `MAJOR`."
        PRD §3.8: "In both variants the cycle's `filed_at` is set to the chosen basis instant, the cycle is timely when the date part of that instant is **less than or equal to** `due_date` (an inclusive boundary), and `days_late` is 0 when timely and otherwise the whole calendar days from `due_date` to that basis date."
        Design: Corner/calculations/failure_severity_flips_to_major_at_exactly_thirty_days_late
        """
        context = setup_filed_annual_report(
            specs=OPS_ONLY_SPECS,
            issue=HUNDRED_MILLION_PAR,
            submit_clock="2027-02-24T00:00:00Z",
            receipt_id="EMMA-A-0001",
        )
        cycle = context["cycle"]
        assert cycle["due_date"] == "2027-01-26"
        assert context["filing"]["submitted_at"].startswith("2027-02-24"), (
            "the submission instant is stamped from the logical clock"
        )
        assert cycle["status"] == "FILED_LATE"
        assert cycle["days_late"] == 29
        assert cycle["timeliness_basis_applied"] == "SUBMISSION_BASIS"

        event = sole_failure_event_for_cycle(cycle["id"])
        assert_failure_to_file_event(event)
        assert event["kind"] == "ANNUAL_REPORT_LATE"
        assert event["days_late"] == 29
        assert event["severity"] == "MINOR", (
            "29 days late is strictly below the thirty-day boundary"
        )
        assert_severity_matches_kind_and_days_late(event)
        assert read_undertaking(context["undertaking"]["id"])["late_filing_count"] == 1

    def test_severity_is_major_at_exactly_thirty_days_late(self):
        """30 days late meets the inclusive boundary and is already MAJOR.

        PRD §3.8: "`severity` is `MAJOR` when `kind` is `ANNUAL_REPORT_MISSED` or `MATERIAL_EVENT_MISSED`, or when `days_late` is **greater than or equal to** 30; it is `MINOR` otherwise."
        PRD §3.8: "For an `ANNUAL_REPORT_LATE` event the boundary is exact: 29 days late is `MINOR`, 30 days late is `MAJOR`."
        Design: Corner/calculations/failure_severity_flips_to_major_at_exactly_thirty_days_late
        """
        context = setup_filed_annual_report(
            specs=OPS_ONLY_SPECS,
            issue=HUNDRED_MILLION_PAR,
            submit_clock="2027-02-25T00:00:00Z",
            receipt_id="EMMA-B-0001",
        )
        cycle = context["cycle"]
        assert cycle["due_date"] == "2027-01-26"
        assert cycle["status"] == "FILED_LATE"
        assert cycle["days_late"] == 30

        event = sole_failure_event_for_cycle(cycle["id"])
        assert_failure_to_file_event(event)
        assert event["kind"] == "ANNUAL_REPORT_LATE"
        assert event["days_late"] == 30
        assert event["severity"] == "MAJOR", (
            "the comparison is greater-than-or-equal, so exactly 30 is already MAJOR"
        )
        assert_severity_matches_kind_and_days_late(event)

    def test_days_late_and_severity_are_frozen_when_the_clock_advances(self):
        """The 29-day failure must still read 29 and MINOR after the clock reaches
        the 30-day instant.

        PRD §3.8: "`days_late` and `severity` are frozen at creation; later remediation never rewrites either."
        PRD §3.8: "For an `ANNUAL_REPORT_LATE` event the boundary is exact: 29 days late is `MINOR`, 30 days late is `MAJOR`."
        Design: Corner/calculations/failure_severity_flips_to_major_at_exactly_thirty_days_late
        """
        context = setup_filed_annual_report(
            specs=OPS_ONLY_SPECS,
            issue=HUNDRED_MILLION_PAR,
            submit_clock="2027-02-24T00:00:00Z",
            receipt_id="EMMA-A-0001",
        )
        event = sole_failure_event_for_cycle(context["cycle"]["id"])
        assert event["days_late"] == 29
        assert event["severity"] == "MINOR"

        set_clock("2027-02-25T00:00:00Z")

        rechecked = sole_failure_event_for_cycle(context["cycle"]["id"])
        assert rechecked["days_late"] == 29, (
            "the failure is frozen at creation and must not drift to 30 as the clock moves"
        )
        assert rechecked["severity"] == "MINOR"
        assert read_cycle(context["cycle"]["id"])["days_late"] == 29


class TestCycleWeightSnapshot:
    """A requirement added after a cycle exists breaks the next cycle, not this one."""

    def test_a_later_requirement_breaks_the_next_cycle_but_not_the_open_one(self):
        """The live undertaking total moves to 12000 and refuses the next cycle,
        while the open cycle keeps its two snapshotted items.

        PRD §3.2: "Each accepted requirement re-derives the undertaking's `content_weight_bp_total` as the sum of `weight_bp` across all of that undertaking's requirements, which is the figure the weight-closure gate of §3.3 tests."
        PRD §3.3: "Over that non-empty set, `content_weight_bp_total` must then equal exactly 10000 basis points, or the request is refused with `ERR_CONTENT_WEIGHTS_UNBALANCED`."
        PRD §3.3: "One **`CycleContentItem`** is minted for each `ContentRequirement` of the undertaking, each carrying the `cycle_id` of the new cycle, the `content_requirement_id` of its source requirement, `status` `NOT_STARTED`, `readiness_factor` 0.0, and a `weight_bp_snapshot` copied from the requirement's `weight_bp` at that instant."
        PRD §3.3: "That copy is what keeps an open cycle stable: a requirement added to the undertaking tomorrow never retro-reweights an item minted today."
        PRD §3.2: "One further field, `requires_audit_opinion`, is derived rather than supplied: it is true when and only when `kind` is `AUDITED_FINANCIALS`, and any value a client sends for it is discarded."
        Design: Corner/calculations/cycle_snapshots_the_weights_so_a_later_requirement_only_breaks_future_cycles
        """
        context = setup_undertaking_with_requirements(
            specs=SIX_FOUR_SPECS, issue=HUNDRED_MILLION_PAR
        )
        undertaking_id = context["undertaking"]["id"]
        assert context["undertaking"]["content_weight_bp_total"] == 0, (
            "content_weight_bp_total starts at 0"
        )
        audited_requirement, ops_requirement = context["requirements"]
        assert audited_requirement["kind"] == "AUDITED_FINANCIALS"
        assert audited_requirement["requires_audit_opinion"] is True
        assert read_undertaking(undertaking_id)["content_weight_bp_total"] == 10000, (
            "6000 plus 4000 closes the undertaking at exactly 10000 basis points"
        )

        cycle = open_cycle(undertaking_id, "FY2026", "2025-07-01", "2026-06-30")
        assert_score(cycle["completeness_score_pct"], 0.00, "completeness_score_pct")

        items = list_content_items(cycle["id"])
        assert len(items) == 2
        ops_item = item_for_requirement(items, ops_requirement["id"])
        assert ops_item["weight_bp_snapshot"] == 4000, (
            "the item snapshots its requirement's weight_bp"
        )
        assert ops_item["status"] == "NOT_STARTED"

        budget = api_client.create_content_requirement(
            {
                "undertaking_id": undertaking_id,
                "kind": "BUDGET_SUMMARY",
                "label": "Adopted Budget Summary",
                "weight_bp": 2000,
            },
            OFFICER_HEADERS,
        )
        validate_success(budget, 201)
        assert read_undertaking(undertaking_id)["content_weight_bp_total"] == 12000, (
            "the live undertaking total absorbs the new 2000-bp requirement immediately"
        )

        validate_error(
            api_client.create_annual_report_cycle(
                annual_report_cycle_payload(
                    undertaking_id,
                    fiscal_year_label="FY2027",
                    period_start_date="2026-07-01",
                    period_end_date="2027-06-30",
                ),
                OFFICER_HEADERS,
            ),
            ApiErrorId.ERR_CONTENT_WEIGHTS_UNBALANCED.value,
        )

        items_after = list_content_items(cycle["id"])
        assert len(items_after) == 2, (
            "the already-created cycle does not gain an item for the new requirement"
        )
        assert read_content_item(ops_item["id"])["weight_bp_snapshot"] == 4000

    def test_completeness_denominator_stays_ten_thousand_after_a_later_requirement(self):
        """The attested 4000-bp item contributes 0.4000 against the constant 10000
        denominator, not against the undertaking's current 12000.

        PRD §3.3: "First, each item's contribution is its `weight_bp_snapshot` divided by 10000, multiplied by its readiness factor, multiplied by its opinion multiplier, and that product is rounded half-up to **4 decimal places**."
        PRD §3.3: "Third, the sum is multiplied by 100 and rounded half-up to **2 decimal places** to give `completeness_score_pct`."
        PRD §3.3: "The opinion multiplier is 1.0 whenever the item's `ContentRequirement` has `requires_audit_opinion` false, regardless of what `audit_opinion_type` holds."
        PRD §3.3: "That copy is what keeps an open cycle stable: a requirement added to the undertaking tomorrow never retro-reweights an item minted today."
        Design: Corner/calculations/cycle_snapshots_the_weights_so_a_later_requirement_only_breaks_future_cycles
        """
        context = setup_undertaking_with_requirements(
            specs=SIX_FOUR_SPECS, issue=HUNDRED_MILLION_PAR
        )
        undertaking_id = context["undertaking"]["id"]
        audited_requirement, ops_requirement = context["requirements"]

        cycle = open_cycle(undertaking_id, "FY2026", "2025-07-01", "2026-06-30")
        items = list_content_items(cycle["id"])
        ops_item = item_for_requirement(items, ops_requirement["id"])
        audited_item = item_for_requirement(items, audited_requirement["id"])

        validate_success(
            api_client.create_content_requirement(
                {
                    "undertaking_id": undertaking_id,
                    "kind": "BUDGET_SUMMARY",
                    "label": "Adopted Budget Summary",
                    "weight_bp": 2000,
                },
                OFFICER_HEADERS,
            ),
            201,
        )
        assert read_undertaking(undertaking_id)["content_weight_bp_total"] == 12000

        prepare_item(ops_item["id"])
        attest_item(ops_item["id"])

        scored = read_cycle(cycle["id"])
        assert read_content_item(ops_item["id"])["status"] == "READY"
        assert read_content_item(audited_item["id"])["status"] == "NOT_STARTED"
        # 4000/10000 * 1.0 * 1.0 = 0.4000 for the READY item, 0.0000 for the
        # untouched 6000-bp item; the sum times 100 is 40.00.
        assert_score(scored["completeness_score_pct"], 40.00, "completeness_score_pct")
        assert_two_decimals(scored["completeness_score_pct"], "completeness_score_pct")
        assert_annual_report_cycle(scored)
