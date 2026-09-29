"""Engagement rows counted from the calendar, and the year-end roll-up over them."""

from test_helpers import (
    ADMIN_HEADERS,
    FUNDER_HEADERS,
    assert_money_equals,
    assert_pct_equals,
    check_in,
    complete_all_trainings,
    complete_residency,
    create_applicant,
    create_international_applicant,
    create_residency,
    get_success_data,
    log_obligation_completion,
    obligation_of_type,
    obligations_for,
    read_cycle,
    refresh_residency,
    schedule_residency,
    set_clock,
    setup_open_cycle,
    withdraw_residency,
)

CLOCK = "2026-08-01T00:00:00Z"
SESSION_START = "2026-11-02"
FIXED_TYPES = ("OPEN_STUDIO", "EXHIBITION", "ARTIST_TALK")
# Each declared session length paired with the inclusive end date it produces
# and the number of required events the four rows then total.
LENGTHS = {4: ("2026-11-29", 1, 4), 5: ("2026-12-06", 1, 4), 8: ("2026-12-27", 2, 5)}


def _three_session_lengths(api):
    """One cycle carrying a four-week, a five-week and an eight-week resident."""
    cycle = setup_open_cycle(api, clock=CLOCK)
    residencies = {}
    for weeks in sorted(LENGTHS):
        residency = create_residency(api, cycle, create_applicant(api))
        schedule_residency(api, residency, SESSION_START, weeks)
        residencies[weeks] = residency
    return cycle, residencies


def test_the_workshop_count_is_floored_at_every_session_length(api):
    """Four and five weeks both owe one workshop; the fractional remainder is dropped.

    PRD: "The fourth scales with the session: the number of `COMMUNITY_WORKSHOP`
    events owed is the session length in weeks divided by four, rounded **down**
    to a whole number, and the row is only created when that figure is at least
    1."

    Design: Corner/calculations/obligation_provisioning_floors_the_workshop_count_and_re_derives_in_place
    """
    _cycle, residencies = _three_session_lengths(api)

    for weeks, (_end, workshops, total) in LENGTHS.items():
        rows = obligations_for(api, residencies[weeks].residency_id)
        assert len(rows) == 4, f"{weeks} weeks should carry four rows"
        assert sum(row["required_count"] for row in rows) == total
        workshop = obligation_of_type(
            api, residencies[weeks].residency_id, "COMMUNITY_WORKSHOP"
        )
        assert workshop["required_count"] == workshops
        assert refresh_residency(api, residencies[weeks])[
            "obligations_required_total"
        ] == total


def test_the_three_flat_rows_ignore_the_session_length_entirely(api):
    """Open studio, exhibition and artist talk owe one event whatever the calendar says.

    PRD: "Three of them are flat: one `OPEN_STUDIO`, one `EXHIBITION` and one
    `ARTIST_TALK`, each with a `required_count` of 1."

    Design: Corner/calculations/obligation_provisioning_floors_the_workshop_count_and_re_derives_in_place
    """
    _cycle, residencies = _three_session_lengths(api)

    for weeks in LENGTHS:
        for obligation_type in FIXED_TYPES:
            row = obligation_of_type(
                api, residencies[weeks].residency_id, obligation_type
            )
            assert row["required_count"] == 1, f"{obligation_type} at {weeks} weeks"


def test_every_provisioned_row_starts_at_its_declared_origin(api):
    """Nothing is pre-credited, and every due date is the session's own last day.

    PRD: "Every provisioned row starts with `status` `PENDING`, `completed_count`
    0, `total_attendance` 0 and a `due_date` equal to the residency's
    `session_end_date` at the moment of provisioning."

    Design: Corner/calculations/obligation_provisioning_floors_the_workshop_count_and_re_derives_in_place
    """
    _cycle, residencies = _three_session_lengths(api)

    for weeks, (end, _workshops, _total) in LENGTHS.items():
        rows = obligations_for(api, residencies[weeks].residency_id)
        assert all(row["status"] == "PENDING" for row in rows)
        assert all(row["completed_count"] == 0 for row in rows)
        assert all(row["total_attendance"] == 0 for row in rows)
        assert all(row["due_date"] == end for row in rows), f"{weeks} weeks due {end}"
        assert refresh_residency(api, residencies[weeks])["session_end_date"] == end


def test_a_reschedule_re_derives_the_rows_in_place_rather_than_adding_more(api):
    """The four-week resident becomes an eight-week one and still owes four rows.

    PRD: "Rescheduling does not duplicate rows: an existing `PENDING` row of the
    same `obligation_type` has its `required_count` and `due_date` re-derived in
    place, while rows already in `SATISFIED`, `WAIVED` or `BREACHED` are never
    re-derived."

    Design: Corner/calculations/obligation_provisioning_floors_the_workshop_count_and_re_derives_in_place
    """
    _cycle, residencies = _three_session_lengths(api)
    short = residencies[4]

    lengthened = schedule_residency(api, short, SESSION_START, 8)

    assert lengthened["session_end_date"] == "2026-12-27"
    assert lengthened["obligations_required_total"] == 5
    rows = obligations_for(api, short.residency_id)
    assert len(rows) == 4
    assert all(row["due_date"] == "2026-12-27" for row in rows)
    assert obligation_of_type(api, short.residency_id, "COMMUNITY_WORKSHOP")[
        "required_count"
    ] == 2
    for obligation_type in FIXED_TYPES:
        assert obligation_of_type(api, short.residency_id, obligation_type)[
            "required_count"
        ] == 1


def test_a_settled_row_is_left_out_of_the_re_derivation(api):
    """The satisfied row keeps its old due date while its pending neighbours move.

    PRD: "Rescheduling does not duplicate rows: an existing `PENDING` row of the
    same `obligation_type` has its `required_count` and `due_date` re-derived in
    place, while rows already in `SATISFIED`, `WAIVED` or `BREACHED` are never
    re-derived."

    Design: Corner/calculations/obligation_provisioning_floors_the_workshop_count_and_re_derives_in_place
    """
    _cycle, residencies = _three_session_lengths(api)
    long_stay = residencies[8]
    settled = log_obligation_completion(
        api, obligation_of_type(api, long_stay.residency_id, "OPEN_STUDIO")["id"], 25
    )
    assert settled["status"] == "SATISFIED"

    schedule_residency(api, long_stay, SESSION_START, 9)

    frozen = obligation_of_type(api, long_stay.residency_id, "OPEN_STUDIO")
    assert frozen["status"] == "SATISFIED"
    assert frozen["required_count"] == 1
    assert frozen["completed_count"] == 1
    assert frozen["due_date"] == "2026-12-27"
    moved = obligation_of_type(api, long_stay.residency_id, "COMMUNITY_WORKSHOP")
    assert moved["required_count"] == 2
    assert moved["due_date"] == "2027-01-03"
    ledger = refresh_residency(api, long_stay)
    assert ledger["obligations_required_total"] == 5
    assert ledger["obligations_completed_total"] == 1


RATE_FIELDS = (
    "completion_rate_pct",
    "international_share_pct",
    "alumni_share_pct",
)
COUNTER_FIELDS = ("follow_on_count", "breached_obligation_count", "total_attendance")


def _report(api, cycle_id):
    """The year-end roll-up, read by the funder it is written for."""
    return get_success_data(api.get_funder_outcome_report(cycle_id, FUNDER_HEADERS))


def _sole_award_withdrawn(api):
    """A cycle whose only award was handed back before the resident ever arrived."""
    cycle = setup_open_cycle(api, clock=CLOCK)
    residency = create_residency(api, cycle, create_applicant(api))
    schedule_residency(api, residency, SESSION_START, 8)
    assert refresh_residency(api, residency)["obligations_required_total"] == 5
    gone = withdraw_residency(api, residency, "accepted another award")
    assert gone["status"] == "WITHDRAWN"
    return cycle, residency


def test_the_withdrawal_moves_both_the_numerator_and_the_denominator(api):
    """The same residency leaves the award count and appears in the withdrawal count.

    PRD: "Withdrawn residencies are reported in `withdrawn_count` but excluded
    from `awarded_count` and therefore from every ratio that divides by it, so a
    single withdrawal moves both a numerator and a denominator."

    Design: Corner/calculations/funder_report_nulls_every_rate_when_the_award_denominator_is_zero
    """
    cycle, _residency = _sole_award_withdrawn(api)

    report = _report(api, cycle.cycle_id)

    assert report["awarded_count"] == 0
    assert report["withdrawn_count"] == 1
    assert report["completed_count"] == 0
    assert report["terminated_count"] == 0


def test_every_rate_over_a_zero_denominator_reads_null_not_zero(api):
    """An absence of awards is reported as an absence of data.

    PRD: "Each of those three is `null` rather than 0 when `awarded_count` is 0."

    Design: Corner/calculations/funder_report_nulls_every_rate_when_the_award_denominator_is_zero
    """
    cycle, _residency = _sole_award_withdrawn(api)

    report = _report(api, cycle.cycle_id)

    for field in RATE_FIELDS:
        assert report[field] is None, f"{field} should be null on a zero denominator"


def test_the_fulfilment_rate_is_null_once_the_waivers_empty_its_denominator(api):
    """The withdrawal waived all four rows out of both residency sums.

    PRD: "`obligation_fulfilment_pct` is one hundred times the sum of
    `obligations_completed_total` across the cycle's residencies divided by the
    sum of `obligations_required_total`, rounded half up to two decimal places,
    and `null` when that denominator is 0"

    Design: Corner/calculations/funder_report_nulls_every_rate_when_the_award_denominator_is_zero
    """
    cycle, residency = _sole_award_withdrawn(api)
    rows = obligations_for(api, residency.residency_id)
    assert [row["status"] for row in rows] == ["WAIVED"] * 4
    assert refresh_residency(api, residency)["obligations_required_total"] == 0

    report = _report(api, cycle.cycle_id)

    assert report["obligation_fulfilment_pct"] is None


def test_the_integer_roll_ups_read_zero_rather_than_null(api):
    """Sums over an empty set are nought; only the ratios go missing.

    PRD: "`breached_obligation_count` is the sum of `obligations_breached_count`,
    and `total_attendance` is the sum of `total_attendance` across every
    obligation of the cycle's residencies."

    Design: Corner/calculations/funder_report_nulls_every_rate_when_the_award_denominator_is_zero
    """
    cycle, _residency = _sole_award_withdrawn(api)

    report = _report(api, cycle.cycle_id)

    for field in COUNTER_FIELDS:
        assert report[field] == 0, f"{field} should be a zero sum, not null"
    assert_money_equals(report["stipend_paid_cents"], 0, "stipend paid")
    assert_money_equals(report["withholding_cents"], 0, "withholding")


def test_the_report_is_a_pure_read_and_answers_before_the_withdrawal_too(api):
    """A zero numerator reads 0.00 while a zero denominator reads null.

    PRD: "**The funder outcome report** is a computed read available to a
    `ProgramAdmin` or a `Funder` that writes nothing and rolls the whole cycle up
    into thirteen fields, all computed over the cycle's residencies."

    Design: Corner/calculations/funder_report_nulls_every_rate_when_the_award_denominator_is_zero
    """
    cycle = setup_open_cycle(api, clock=CLOCK)
    residency = create_residency(api, cycle, create_applicant(api))
    schedule_residency(api, residency, SESSION_START, 8)
    before = read_cycle(api, cycle.cycle_id)

    awarded = _report(api, cycle.cycle_id)
    again = _report(api, cycle.cycle_id)

    assert awarded["awarded_count"] == 1
    assert_pct_equals(awarded["completion_rate_pct"], 0.00, "completion rate")
    assert again == awarded
    assert read_cycle(api, cycle.cycle_id)["version"] == before["version"]

    withdraw_residency(api, residency)
    assert _report(api, cycle.cycle_id)["completion_rate_pct"] is None


SESSION_END = "2026-12-27"
OPEN_STUDIO_ATTENDANCE = 40


def _three_awards_one_finished(api):
    """One domestic resident who finished, and two sponsored ones still to arrive."""
    cycle = setup_open_cycle(api, clock=CLOCK)
    domestic = create_applicant(api)
    residencies = [create_residency(api, cycle, domestic)]
    for country in ("FR", "IN"):
        applicant = create_international_applicant(api, citizenship_country=country)
        residencies.append(create_residency(api, cycle, applicant))
    for residency in residencies:
        schedule_residency(api, residency, SESSION_START, 8)
        assert refresh_residency(api, residency)["obligations_required_total"] == 5

    finisher = residencies[0]
    complete_all_trainings(api, finisher)
    set_clock(api, f"{SESSION_START}T09:00:00Z")
    check_in(api, finisher)
    log_obligation_completion(
        api,
        obligation_of_type(api, finisher.residency_id, "OPEN_STUDIO")["id"],
        OPEN_STUDIO_ATTENDANCE,
    )
    set_clock(api, f"{SESSION_END}T09:00:00Z")
    done = complete_residency(api, finisher)
    assert done["status"] == "COMPLETED"
    return cycle, domestic, residencies


def test_the_completion_rate_rounds_down_at_the_third_decimal(api):
    """One finish in three awards is 33.33, not 33.34 and not 33.3.

    PRD: "`completion_rate_pct` is one hundred times `completed_count` divided by
    `awarded_count`, rounded half up to two decimal places"

    Design: Corner/calculations/funder_report_percentages_round_half_up_to_two_places
    """
    cycle, _domestic, _residencies = _three_awards_one_finished(api)

    report = _report(api, cycle.cycle_id)

    assert report["awarded_count"] == 3
    assert report["completed_count"] == 1
    assert report["terminated_count"] == 0
    assert report["withdrawn_count"] == 0
    assert_pct_equals(report["completion_rate_pct"], 33.33, "completion rate")


def test_the_international_share_rounds_up_at_the_third_decimal(api):
    """Two sponsored awards in three is 66.67, which rules truncation out.

    PRD: "`international_share_pct` is one hundred times the number of awarded
    residencies whose `visa_required` is true, over `awarded_count`, on the same
    rounding"

    Design: Corner/calculations/funder_report_percentages_round_half_up_to_two_places
    """
    cycle, _domestic, residencies = _three_awards_one_finished(api)
    sponsored = [
        refresh_residency(api, residency)["visa_required"] for residency in residencies
    ]
    assert sponsored == [False, True, True]

    report = _report(api, cycle.cycle_id)

    assert_pct_equals(report["international_share_pct"], 66.67, "international share")
    # Truncation would have produced 66.66 from the same 66.6666... quotient.
    assert report["international_share_pct"] != 66.66


def test_the_alumni_share_follows_the_recomputed_alumni_counter(api):
    """Finishing the residency made its artist an alumnus, and only that artist.

    PRD: "`alumni_share_pct` is one hundred times the number of awarded
    residencies whose artist's `completed_residency_count` is at least 1, over
    `awarded_count`, likewise."

    Design: Corner/calculations/funder_report_percentages_round_half_up_to_two_places
    """
    cycle, domestic, _residencies = _three_awards_one_finished(api)
    alumnus = get_success_data(
        api.get_applicant(domestic.applicant_id, ADMIN_HEADERS)
    )
    assert alumnus["completed_residency_count"] == 1

    report = _report(api, cycle.cycle_id)

    assert_pct_equals(report["alumni_share_pct"], 33.33, "alumni share")


def test_the_fulfilment_rate_divides_the_two_obligation_sums(api):
    """One event delivered against fifteen owed, with breached rows still counted in.

    PRD: "because waived obligations are already out of both residency sums, they
    neither help nor hurt the percentage."

    Design: Corner/calculations/funder_report_percentages_round_half_up_to_two_places
    """
    cycle, _domestic, residencies = _three_awards_one_finished(api)
    finished = refresh_residency(api, residencies[0])
    assert finished["obligations_required_total"] == 5
    assert finished["obligations_completed_total"] == 1
    assert finished["obligations_breached_count"] == 3

    report = _report(api, cycle.cycle_id)

    assert_pct_equals(report["obligation_fulfilment_pct"], 6.67, "fulfilment rate")
    assert report["breached_obligation_count"] == 3
    assert report["total_attendance"] == OPEN_STUDIO_ATTENDANCE


def test_the_money_roll_ups_stay_in_integer_cents(api):
    """No disbursement was ever paid, so both money fields are exactly nought.

    PRD: "Finally `stipend_paid_cents` is the sum of `stipend_paid_gross_cents`
    and `withholding_cents` the sum of `withholding_to_date_cents`, both across
    the cycle's residencies and both in integer cents."

    Design: Corner/calculations/funder_report_percentages_round_half_up_to_two_places
    """
    cycle, _domestic, _residencies = _three_awards_one_finished(api)

    report = _report(api, cycle.cycle_id)

    assert_money_equals(report["stipend_paid_cents"], 0, "stipend paid")
    assert_money_equals(report["withholding_cents"], 0, "withholding")
    assert report["follow_on_count"] == 0
