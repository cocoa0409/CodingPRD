"""Ledgers walked up to a peak and then back down to their opening values."""

from test_helpers import (
    ERR_ASSIGNMENT_STATE_INVALID,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_STUDIO_CAPACITY_EXCEEDED,
    FACILITIES_HEADERS,
    FINANCE_PAYER_HEADERS,
    FINANCE_PAYER_USER_ID,
    FINANCE_REVERSER_HEADERS,
    SPONSORED_SESSION_START,
    assert_money_equals,
    assign_housing,
    assign_studio,
    create_applicant,
    create_housing_unit,
    create_international_applicant,
    create_residency,
    create_studio,
    disbursements_for,
    generate_stipend_schedule,
    get_success_data,
    housing_assignments_for,
    make_settlement_payload,
    make_studio_assignment_payload,
    obligations_for,
    pay_disbursement,
    payment_dates,
    read_cycle,
    read_residency,
    refresh_housing_unit,
    refresh_residency,
    refresh_studio,
    release_studio_assignment,
    request_visa_docs,
    reverse_disbursement,
    schedule_residency,
    setup_open_cycle,
    setup_residency_ready_for_payment,
    studio_assignments_for,
    submit_visa_docs,
    tax_report,
    validate_error,
    visa_case_for,
    withdraw_residency,
)

BASELINE_POOL = 20000000
SESSION = ("2026-11-02", "2026-12-27")
BED_WINDOW = ("2026-11-02", "2026-12-28")


def _provisioned_residency(api):
    """A scheduled residency holding one row of every dependent kind."""
    cycle = setup_open_cycle(api)
    baseline = read_cycle(api, cycle.cycle_id)
    assert_money_equals(baseline["stipend_committed_cents"], 0, "baseline committed")
    assert_money_equals(
        baseline["stipend_uncommitted_cents"], BASELINE_POOL, "baseline uncommitted"
    )
    assert baseline["slots_filled_count"] == 0
    assert baseline["slots_open_count"] == 10

    residency = create_residency(api, cycle, create_international_applicant(api))
    schedule_residency(api, residency, SESSION[0], 8)
    generate_stipend_schedule(api, residency)

    studio = create_studio(api)
    booking = assign_studio(api, residency, SESSION[0], SESSION[1], studio)
    unit = create_housing_unit(api)
    bed = assign_housing(
        api, unit, residency, BED_WINDOW[0], BED_WINDOW[1], meal_plan_selected=True
    )
    case = visa_case_for(api, residency.residency_id)
    request_visa_docs(api, case["id"])
    submitted = submit_visa_docs(api, case["id"])
    assert submitted["status"] == "DOCS_SUBMITTED"

    return {
        "cycle": cycle,
        "residency": residency,
        "studio": studio,
        "unit": unit,
        "booking": booking,
        "bed": bed,
        "case": case,
    }


def test_the_withdrawal_returns_the_money_and_the_slot_to_the_pool(api):
    """Both cycle ledgers come back to the values they had before the award.

    PRD: "`stipend_committed_cents` is the sum of `stipend_total_cents` over
    every residency of the cycle whose `status` is `SCHEDULED`, `IN_RESIDENCE`,
    `COMPLETED` or `TERMINATED`; `stipend_uncommitted_cents` is
    `stipend_pool_cents` less that sum."

    Design: Difficulty/compensating_invariant/cycle_money_and_slot_ledgers_return_to_pre_award_values_after_withdrawal
    """
    world = _provisioned_residency(api)
    awarded = refresh_residency(api, world["residency"])
    assert_money_equals(awarded["stipend_total_cents"], 560000, "provisional award")
    assert awarded["stipend_basis"] == "PROVISIONAL"
    peak = read_cycle(api, world["cycle"].cycle_id)
    assert_money_equals(peak["stipend_committed_cents"], 560000, "peak committed")
    assert_money_equals(peak["stipend_uncommitted_cents"], 19440000, "peak uncommitted")
    assert peak["slots_filled_count"] == 1
    assert peak["slots_open_count"] == 9

    gone = withdraw_residency(api, world["residency"], "accepted a competing fellowship")

    assert gone["status"] == "WITHDRAWN"
    restored = read_cycle(api, world["cycle"].cycle_id)
    assert_money_equals(restored["stipend_committed_cents"], 0, "restored committed")
    assert_money_equals(
        restored["stipend_uncommitted_cents"], BASELINE_POOL, "restored uncommitted"
    )
    assert restored["slots_filled_count"] == 0
    assert restored["slots_open_count"] == 10


def test_the_compensation_fans_out_to_every_dependent_row(api):
    """One lifecycle call unwinds money, engagements and the sponsorship at once.

    PRD: "every obligation in `PENDING` moves `PENDING → WAIVED` with
    `waived_reason` recorded as `RESIDENCY_WITHDRAWN`; and the residency's visa
    case, when one exists and its status is neither `APPROVED` nor `DENIED`, is
    driven to `DENIED` with the reason recorded as sponsorship withdrawn."

    Design: Difficulty/compensating_invariant/cycle_money_and_slot_ledgers_return_to_pre_award_values_after_withdrawal
    """
    world = _provisioned_residency(api)
    residency = world["residency"]
    scheduled = disbursements_for(api, residency.residency_id)
    assert [row["status"] for row in scheduled] == ["SCHEDULED"] * 4
    pending = obligations_for(api, residency.residency_id)
    assert [row["status"] for row in pending] == ["PENDING"] * 4

    withdraw_residency(api, residency)

    assert [
        row["status"] for row in disbursements_for(api, residency.residency_id)
    ] == ["VOIDED"] * 4
    waived = obligations_for(api, residency.residency_id)
    assert [row["status"] for row in waived] == ["WAIVED"] * 4
    assert all(row["waived_reason"] == "RESIDENCY_WITHDRAWN" for row in waived)
    assert visa_case_for(api, residency.residency_id)["status"] == "DENIED"


def test_the_facility_ledgers_return_to_their_pre_booking_values(api):
    """The studio day count and the bed-night count both fall back to zero.

    PRD: "every studio assignment and housing assignment in `ACTIVE` moves
    `ACTIVE → RELEASED`, with the studio's `reserved_resident_days` and the unit's
    `occupied_bed_nights` recomputed"

    Design: Difficulty/compensating_invariant/cycle_money_and_slot_ledgers_return_to_pre_award_values_after_withdrawal
    """
    world = _provisioned_residency(api)
    residency = world["residency"]
    assert refresh_studio(api, world["studio"])["reserved_resident_days"] == 56
    assert refresh_housing_unit(api, world["unit"])["occupied_bed_nights"] == 56

    withdraw_residency(api, residency)

    emptied_studio = refresh_studio(api, world["studio"])
    assert emptied_studio["reserved_resident_days"] == 0
    assert emptied_studio["active_assignment_count"] == 0
    assert refresh_housing_unit(api, world["unit"])["occupied_bed_nights"] == 0
    assert [row["status"] for row in studio_assignments_for(api, residency.residency_id)] == (
        ["RELEASED"]
    )
    assert [row["status"] for row in housing_assignments_for(api, residency.residency_id)] == (
        ["RELEASED"]
    )
    # The row survives as history: the ledgers moved, the residency's own award did not.
    history = read_residency(api, residency.residency_id)
    assert history["assigned_studio_code"] is None
    assert history["assigned_housing_unit_code"] is None
    assert_money_equals(history["stipend_total_cents"], 560000, "award on the record")
    assert history["actual_weeks_in_residence"] is None


SHARED_STUDIO = {"max_concurrent_residents": 2}
INNER_WINDOW = ("2026-11-10", "2026-11-20")


def _book_studio(api, studio, residency, window):
    """The raw booking call, so a refusal can be inspected instead of raised."""
    current = refresh_residency(api, residency)
    payload = make_studio_assignment_payload(
        residency.residency_id,
        window[0],
        window[1],
        current["version"],
        studio.studio_id,
    )
    return api.create_studio_assignment(payload, FACILITIES_HEADERS)


def _read_studio_assignment(api, assignment_id):
    return get_success_data(api.get_studio_assignment(assignment_id, FACILITIES_HEADERS))


def _shared_studio_at_its_peak(api):
    """A two-person studio carrying a long booking and a short one, plus a rival."""
    cycle = setup_open_cycle(api)
    residents = []
    for _ in range(3):
        residency = create_residency(api, cycle, create_applicant(api))
        schedule_residency(api, residency, SESSION[0], 8)
        residents.append(residency)

    studio = create_studio(api, **SHARED_STUDIO)
    assert studio.studio["reserved_resident_days"] == 0
    assert studio.studio["active_assignment_count"] == 0

    whole = assign_studio(api, residents[0], SESSION[0], SESSION[1], studio)
    inner = assign_studio(api, residents[1], INNER_WINDOW[0], INNER_WINDOW[1], studio)
    assert whole["occupied_days"] == 56
    assert inner["occupied_days"] == 11
    peak = refresh_studio(api, studio)
    assert peak["reserved_resident_days"] == 67
    assert peak["active_assignment_count"] == 2
    return studio, residents, inner


def test_releasing_one_row_subtracts_exactly_its_own_days(api):
    """The long booking's days survive, so the ledger is a sum and not a reset.

    PRD: "Because the studio's day ledger is recomputed from the surviving
    `ACTIVE` rows rather than adjusted by arithmetic, releasing the only
    assignment restores `reserved_resident_days` to exactly its pre-assignment
    value."

    Design: Difficulty/compensating_invariant/studio_day_ledger_restored_after_a_single_release_among_many
    """
    studio, residents, inner = _shared_studio_at_its_peak(api)

    released = release_studio_assignment(
        api, inner["id"], "resident moved to a private studio"
    )

    assert released["status"] == "RELEASED"
    assert released["released_reason"] == "resident moved to a private studio"
    # History is kept intact; the eleven days are excluded by status, not erased.
    assert released["occupied_days"] == 11
    trimmed = refresh_studio(api, studio)
    assert trimmed["reserved_resident_days"] == 56
    assert trimmed["active_assignment_count"] == 1
    assert read_residency(api, residents[1].residency_id)["assigned_studio_code"] is None
    assert read_residency(api, residents[0].residency_id)["assigned_studio_code"] == (
        studio.code
    )


def test_the_release_frees_capacity_and_the_ledger_returns_to_its_peak(api):
    """The freed window is genuinely bookable again by a third artist.

    PRD: "for every single calendar date of the requested window, the number of
    `ACTIVE` assignments of that studio covering that date, counting the request
    itself, must not exceed `max_concurrent_residents`"

    Design: Difficulty/compensating_invariant/studio_day_ledger_restored_after_a_single_release_among_many
    """
    studio, residents, inner = _shared_studio_at_its_peak(api)
    rival = residents[2]
    validate_error(
        _book_studio(api, studio, rival, INNER_WINDOW), ERR_STUDIO_CAPACITY_EXCEEDED
    )

    release_studio_assignment(api, inner["id"])
    rebooked = get_success_data(_book_studio(api, studio, rival, INNER_WINDOW), 201)

    assert rebooked["status"] == "ACTIVE"
    assert rebooked["occupied_days"] == 11
    back_at_peak = refresh_studio(api, studio)
    assert back_at_peak["reserved_resident_days"] == 67
    assert back_at_peak["active_assignment_count"] == 2
    assert _read_studio_assignment(api, inner["id"])["status"] == "RELEASED"


def test_a_repeated_release_cannot_drive_the_day_ledger_negative(api):
    """The second release is refused rather than subtracting the days twice.

    PRD: "requires the assignment to be `ACTIVE`, a released row being
    `ERR_ASSIGNMENT_STATE_INVALID` (HTTP 409)"

    Design: Difficulty/compensating_invariant/studio_day_ledger_restored_after_a_single_release_among_many
    """
    studio, _residents, inner = _shared_studio_at_its_peak(api)
    release_studio_assignment(api, inner["id"])

    validate_error(
        api.release_studio_assignment(
            inner["id"], {"reason": "second attempt"}, FACILITIES_HEADERS
        ),
        ERR_ASSIGNMENT_STATE_INVALID,
    )

    steady = refresh_studio(api, studio)
    assert steady["reserved_resident_days"] == 56
    assert steady["active_assignment_count"] == 1


# Two weeks at 43,751 cents makes every period 87,502 cents, so the two paid
# rows share a gross figure while their taxable slices differ.
TREATY_RATE_CENTS = 43751


def _two_periods_paid(api):
    """A treaty-country resident with periods one and two settled."""
    _cycle, _applicant, residency, rows = setup_residency_ready_for_payment(
        api,
        session_length_weeks=8,
        international=True,
        treaty_country=True,
        weekly_rate_override_cents=TREATY_RATE_CENTS,
    )
    assert [row["gross_cents"] for row in rows] == [87502] * 4
    baseline = refresh_residency(api, residency)
    assert baseline["tax_form_type"] == "1042S"
    assert_money_equals(baseline["stipend_paid_gross_cents"], 0, "baseline gross")
    assert_money_equals(baseline["withholding_to_date_cents"], 0, "baseline withheld")

    dates = payment_dates(SPONSORED_SESSION_START, 4)
    first = pay_disbursement(api, rows[0]["id"], dates[0])
    second = pay_disbursement(api, rows[1]["id"], dates[1])
    return residency, rows, dates, first, second


def test_two_identical_periods_carry_different_withholding(api):
    """The cumulative exemption is spent inside period one, so period two pays more.

    PRD: "The taxable slice of this payment is the amount by which the
    cumulative-after figure exceeds 60,000 cents, less the amount by which the
    cumulative-before figure exceeds 60,000 cents, where each excess is treated
    as 0 when the figure is at or below the threshold."

    Design: Difficulty/compensating_invariant/paired_paid_gross_and_withholding_ledgers_restored_by_a_reversal
    """
    residency, _rows, _dates, first, second = _two_periods_paid(api)

    assert first["withholding_rate"] == 0.15
    assert_money_equals(first["cumulative_taxable_cents"], 27502, "period 1 slice")
    assert_money_equals(first["withholding_cents"], 4125, "period 1 withholding")
    assert_money_equals(first["net_cents"], 83377, "period 1 net")
    assert_money_equals(second["cumulative_taxable_cents"], 87502, "period 2 slice")
    assert_money_equals(second["withholding_cents"], 13125, "period 2 withholding")
    assert_money_equals(second["net_cents"], 74377, "period 2 net")

    peak = refresh_residency(api, residency)
    assert_money_equals(peak["stipend_paid_gross_cents"], 175004, "peak gross")
    assert_money_equals(peak["withholding_to_date_cents"], 17250, "peak withheld")


def test_a_reversal_restores_both_ledgers_and_keeps_the_row(api):
    """Gross and withholding unwind together, exactly, and the row stays readable.

    PRD: "The row keeps its `gross_cents`, `withholding_cents`, `net_cents`,
    `withholding_rate`, `cumulative_taxable_cents` and `paid_on_date` for
    tax-reporting history, but it is excluded from both residency ledgers, which
    are recomputed without it and thereby restored to exactly their pre-payment
    values."

    Design: Difficulty/compensating_invariant/paired_paid_gross_and_withholding_ledgers_restored_by_a_reversal
    """
    residency, rows, _dates, first, _second = _two_periods_paid(api)

    reversed_row = reverse_disbursement(
        api, rows[1]["id"], FINANCE_REVERSER_HEADERS, "bank returned the transfer"
    )

    assert reversed_row["status"] == "REVERSED"
    assert_money_equals(reversed_row["gross_cents"], 87502, "reversed gross")
    assert_money_equals(reversed_row["withholding_cents"], 13125, "reversed withholding")
    assert_money_equals(reversed_row["net_cents"], 74377, "reversed net")
    assert_money_equals(reversed_row["cumulative_taxable_cents"], 87502, "reversed slice")

    restored = refresh_residency(api, residency)
    assert_money_equals(restored["stipend_paid_gross_cents"], 87502, "restored gross")
    assert_money_equals(restored["withholding_to_date_cents"], 4125, "restored withheld")
    survivor = get_success_data(api.get_disbursement(rows[0]["id"], FINANCE_PAYER_HEADERS))
    assert survivor["status"] == "PAID"
    assert survivor["paid_by_user_id"] == FINANCE_PAYER_USER_ID
    assert_money_equals(survivor["withholding_cents"], 4125, "surviving withholding")
    assert survivor["paid_on_date"] == first["paid_on_date"]


def test_the_tax_statement_agrees_with_the_restored_ledgers(api):
    """The annual report counts the surviving payment only, and reconciles at zero.

    PRD: "Note that `SCHEDULED` rows are not yet income, `VOIDED` rows were never
    paid, and `REVERSED` rows are excluded from every live total — only `PAID`
    rows contribute."

    Design: Difficulty/compensating_invariant/paired_paid_gross_and_withholding_ledgers_restored_by_a_reversal
    """
    residency, rows, _dates, _first, _second = _two_periods_paid(api)
    reverse_disbursement(api, rows[1]["id"], FINANCE_REVERSER_HEADERS)

    report = tax_report(api, residency.residency_id)

    assert report["paid_period_count"] == 1
    assert report["withholding_rate"] == 0.15
    assert_money_equals(report["annual_gross_cents"], 87502, "annual gross")
    assert_money_equals(report["annual_taxable_cents"], 27502, "annual taxable")
    assert_money_equals(report["withheld_actual_cents"], 4125, "withheld actual")
    assert_money_equals(report["statutory_liability_cents"], 4125, "statutory")
    assert report["reconciliation_delta_cents"] == 0


def test_the_reversal_rewinds_the_cumulative_threshold_walk(api):
    """The next payment recomputes its slice from the paid rows that remain.

    PRD: "Take the sum of `gross_cents` over the residency's disbursements that
    are already `PAID` and whose `period_index` is lower than this row's — call
    that the cumulative gross before this payment — and add this row's
    `gross_cents` to obtain the cumulative gross after it."

    Design: Difficulty/compensating_invariant/paired_paid_gross_and_withholding_ledgers_restored_by_a_reversal
    """
    residency, rows, dates, _first, _second = _two_periods_paid(api)
    reverse_disbursement(api, rows[1]["id"], FINANCE_REVERSER_HEADERS)

    third = pay_disbursement(api, rows[2]["id"], dates[2])

    assert third["status"] == "PAID"
    assert third["period_index"] == 3
    assert_money_equals(third["cumulative_taxable_cents"], 87502, "period 3 slice")
    assert_money_equals(third["withholding_cents"], 13125, "period 3 withholding")
    assert_money_equals(third["net_cents"], 74377, "period 3 net")
    walked = refresh_residency(api, residency)
    assert_money_equals(walked["stipend_paid_gross_cents"], 175004, "gross after period 3")
    assert_money_equals(walked["withholding_to_date_cents"], 17250, "withheld after period 3")


def test_the_payer_may_not_reverse_their_own_payment(api):
    """Segregation holds on the compensating action, so no ledger moves at all.

    PRD: "`REVERSE` drives `PAID → REVERSED` and is the second segregation point:
    the acting officer's `X-User-ID` must differ from the row's
    `paid_by_user_id`, or `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

    Design: Difficulty/compensating_invariant/paired_paid_gross_and_withholding_ledgers_restored_by_a_reversal
    """
    residency, rows, _dates, _first, _second = _two_periods_paid(api)

    validate_error(
        api.settle_disbursement(
            rows[1]["id"],
            make_settlement_payload("REVERSE", reason="paid in error"),
            FINANCE_PAYER_HEADERS,
        ),
        ERR_SEGREGATION_OF_DUTIES,
    )

    untouched = get_success_data(api.get_disbursement(rows[1]["id"], FINANCE_PAYER_HEADERS))
    assert untouched["status"] == "PAID"
    held = refresh_residency(api, residency)
    assert_money_equals(held["stipend_paid_gross_cents"], 175004, "held gross")
    assert_money_equals(held["withholding_to_date_cents"], 17250, "held withheld")
