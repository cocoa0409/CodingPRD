"""Both figures the platform computes twice: the visit charge and the yield loss."""

from test_helpers import (
    ComplaintStatus,
    ComplianceResult,
    LineStatus,
    SECOND_AUDITOR_HEADERS,
    SettlementState,
    Symptom,
    assert_liters,
    fixtures,
)


def test_provisional_charge_bills_every_line_the_crew_touched(api):
    """PRD §3.7: "The **provisional** variant, which runs when field work is closed
    out, sets `billable_line_count` to `serviced_line_count` — every line the crew
    touched is billed, whatever its grade, because the signature outcome is not yet
    known — and applies no waiver withholding at all."
    PRD §3.7: "a `per_line_rate_cents` of 4175 at a `frequency_multiplier` of 1.10
    gives a per-line amount of 4593 cents, so three lines come to 13779 cents,
    whereas rounding the aggregate would have given 13778."

    Design: Difficulty/dual_variant_calc/visit_charge_provisional_bills_every_serviced_line_settled_bills_only_pass_lines
    """
    ground = fixtures.setup_three_line_visit_with_work(api)

    third_cycle = ground["cycles"][2]
    assert third_cycle["compliance_result"] == ComplianceResult.FAIL_CONTACT_TIME, (
        "the short-contact circulation on line 3 must grade FAIL_CONTACT_TIME, "
        f"got {third_cycle['compliance_result']}"
    )
    assert third_cycle["required_contact_minutes"] == 15
    assert third_cycle["effective_active_pct"] == 2.025

    visit = ground["visit"]
    assert visit["serviced_line_count"] == 3, (
        f"three lines were circulated, got serviced_line_count {visit['serviced_line_count']}"
    )
    assert visit["billable_line_count"] == 3, (
        "the provisional variant bills every serviced line, got "
        f"{visit['billable_line_count']}"
    )
    assert visit["parts_charge_cents"] == 3195
    assert visit["provisional_charge_cents"] == 24474, (
        f"7500 base + 13779 cleaning + 3195 parts is 24474, got {visit['provisional_charge_cents']}"
    )
    assert visit["settlement_state"] == SettlementState.UNSETTLED

    line3 = fixtures.read_line(api, ground["lines"][2]["id"])
    assert line3["status"] == LineStatus.OUT_OF_SERVICE
    account = fixtures.read_account(api, ground["account"]["id"])
    assert account["lines_out_of_service_count"] == 1
    assert account["status"] == "ACTIVE", (
        "one line out of four contracted lines must not suspend the account"
    )


def test_settled_charge_bills_only_the_lines_whose_newest_cycle_passed(api):
    """PRD §3.7: "The **settled** variant, which runs at signature, at waiver and
    again on a re-signature after a dispute, sets `billable_line_count` to the
    passed-line count instead, so a line whose circulation failed its grade is not
    billed."
    PRD §3.7: "the provisional cleaning subtotal is 13779 cents against a settled
    cleaning subtotal of 9186."

    Design: Difficulty/dual_variant_calc/visit_charge_provisional_bills_every_serviced_line_settled_bills_only_pass_lines
    """
    ground = fixtures.setup_three_line_visit_with_work(api)
    provisional = ground["visit"]["provisional_charge_cents"]

    signed = fixtures.sign_visit(api, ground["visit"]["id"], ground["account"]["id"])

    assert signed["billable_line_count"] == 2, (
        f"only two of the three lines passed, got {signed['billable_line_count']}"
    )
    assert signed["cleaning_subtotal_cents"] == 9186, (
        f"two billable lines at 4593 cents is 9186, got {signed['cleaning_subtotal_cents']}"
    )
    assert signed["settled_charge_cents"] == 19881, (
        f"7500 base + 9186 cleaning + 3195 parts is 19881, got {signed['settled_charge_cents']}"
    )
    assert signed["brewer_funded_cents"] == 0, "no brewer programme funds this contract"
    assert signed["account_due_cents"] == 19881
    assert signed["settlement_state"] == SettlementState.SETTLED
    assert signed["provisional_charge_cents"] == provisional, (
        "the provisional figure is not rewritten by the settlement"
    )
    assert provisional - signed["settled_charge_cents"] == 4593, (
        "the two inclusion sets differ by exactly one per-line amount"
    )


def _line_with_one_pass_cycle(api):
    """A line cleaned once on 2026-08-03, with the clock left at 2026-08-20T12:00:00Z."""
    ground = fixtures.setup_started_visit(
        api,
        venue_name="Anchor Tap",
        scheduled_date="2026-08-03",
        scheduled_start_minute=480,
        scheduled_end_minute=600,
        visit_clock="2026-08-03T08:00:00Z",
    )
    cycle = fixtures.log_cleaning_cycle(
        api,
        ground["visit"]["id"],
        ground["line"]["id"],
        ground["lot"]["id"],
        ground["technician"]["id"],
        **fixtures.PASSING_CAUSTIC_CYCLE,
    )
    assert cycle["compliance_result"] == ComplianceResult.PASS
    fixtures.set_clock(api, "2026-08-20T12:00:00Z")
    return ground


def test_provisional_yield_loss_estimates_from_symptom_severity_and_exposure(api):
    """PRD §3.8: "Multiply the symptom's factor by `days_at_risk` and by the line's
    `average_daily_throughput_liters`, and round half up to two decimal places to get
    `provisional_yield_loss_liters`."
    PRD §3.8: "A `FOAMY_POUR` on a line pouring 12.0 liters a day, reported seventeen
    days after its last cleaning, therefore estimates 71.40 liters and 34272 cents."

    Design: Difficulty/dual_variant_calc/complaint_yield_loss_provisional_severity_estimate_vs_settled_measured_waste
    """
    ground = _line_with_one_pass_cycle(api)

    complaint = fixtures.file_complaint(
        api, ground["account"]["id"], ground["line"]["id"], Symptom.FOAMY_POUR
    )

    assert complaint["days_at_risk"] == 17, (
        f"seventeen whole days separate the cleaning from the report, got {complaint['days_at_risk']}"
    )
    assert_liters(complaint["provisional_yield_loss_liters"], 71.40)
    assert complaint["provisional_yield_loss_cents"] == 34272, (
        f"71.40 liters at 480 cents is 34272, got {complaint['provisional_yield_loss_cents']}"
    )
    assert complaint["status"] == ComplaintStatus.OPEN
    account = fixtures.read_account(api, ground["account"]["id"])
    assert account["open_complaint_count"] == 1


def test_settled_yield_loss_replaces_the_estimate_with_measured_waste(api):
    """PRD §3.8: "Then add to the `measured_waste_liters` a foam allowance of half a
    liter for each of those days, and round half up to two decimal places to get
    `settled_yield_loss_liters`; multiply by 480 cents per liter and round half up for
    `settled_yield_loss_cents`."
    PRD §3.8: "The same complaint from the worked example above, closed with 18.5
    measured liters after two days open, settles at 19.50 liters and 9360 cents — a
    downward delta of 24912 cents from the provisional figure, and both figures remain
    on the record."

    Design: Difficulty/dual_variant_calc/complaint_yield_loss_provisional_severity_estimate_vs_settled_measured_waste
    """
    ground = _line_with_one_pass_cycle(api)
    complaint = fixtures.file_complaint(
        api, ground["account"]["id"], ground["line"]["id"], Symptom.FOAMY_POUR
    )

    fixtures.set_clock(api, "2026-08-22T09:00:00Z")
    closed = fixtures.close_complaint(
        api,
        complaint["id"],
        disposition="RESOLVED",
        measured_waste_liters=18.5,
        headers=SECOND_AUDITOR_HEADERS,
    )

    assert closed["status"] == ComplaintStatus.RESOLVED
    assert closed["measured_waste_liters"] == 18.5
    assert_liters(closed["settled_yield_loss_liters"], 19.50)
    assert closed["settled_yield_loss_cents"] == 9360, (
        f"19.50 liters at 480 cents is 9360, got {closed['settled_yield_loss_cents']}"
    )
    assert closed["provisional_yield_loss_cents"] == 34272, (
        "the intake estimate stays on the record beside the settled figure"
    )
    assert closed["provisional_yield_loss_cents"] - closed["settled_yield_loss_cents"] == 24912
    assert closed["closed_by_user_id"] == "auditor-2"
    account = fixtures.read_account(api, ground["account"]["id"])
    assert account["open_complaint_count"] == 0, "a resolved complaint drops out of the count"
