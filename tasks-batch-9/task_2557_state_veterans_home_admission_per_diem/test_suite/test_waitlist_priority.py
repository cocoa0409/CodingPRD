"""Waitlist priority scoring under the class-base floor.

The score is a weighted total with a floor, so once the decline penalty has eaten
past the class base the score stops responding to its own inputs while the raw
total keeps falling. These tests walk one applicant through repeated offer and
decline cycles and read the score after each nightly run.
"""

from test_helpers import fixtures as fx


def _class_four_applicant_on_a_single_bed_unit(api):
    """One class-four applicant queued on a one-bed open unit, with no assessment.

    Service and residency are deliberately minimal so the applicant lands in the
    lowest class, whose base of one hundred points is close enough to the raw
    total that a single decline penalty pushes the raw total underneath it.
    """
    fx.set_clock(api, "2026-08-01T00:00:00Z")
    home = fx.create_home(api)
    unit = fx.create_unit(
        api, home["id"], care_level="NURSING", licensed_bed_count=1, out_of_service_bed_count=0
    )
    applicant = fx.create_applicant(
        api,
        home["id"],
        service_days=400,
        discharge_character="HONORABLE",
        wartime_service=False,
        service_connected_disability_pct=0,
        nursing_care_for_service_connected=False,
        state_residency_years=1,
        requested_care_level="NURSING",
        application_received_date="2026-08-01",
    )
    fx.determine_eligibility(api, applicant["id"])
    entry = fx.create_waitlist_entry(api, applicant["id"], unit["id"])
    return home, unit, applicant, entry


def test_priority_score_reports_the_raw_total_while_it_exceeds_the_class_base(api):
    """Before any decline the score is the raw weighted total, above the class base.

    Per the PRD: "Those five terms are summed with the penalty subtracted, and
    then a floor is applied: `priority_score` is the greater of the class base and
    that raw total." With one year of residency and no elapsed tenure the raw
    total sits five points above the class-four base, and that is the stored
    score. The same nightly run issues the entry its first bed offer.

    Design: Difficulty/combinatorial_formula/waitlist_priority_score_nonlinear_floor
    """
    home, unit, applicant, _entry = _class_four_applicant_on_a_single_bed_unit(api)

    counters = fx.census_run(api, "2026-08-01", home["id"])

    assert counters["offered_waitlist_entry_count"] == 1
    refreshed = fx.read_applicant(api, applicant["id"])
    assert refreshed["priority_class"] == "CLASS_4"
    assert refreshed["priority_score"] == 105


def test_decline_penalty_saturates_at_the_class_base(api):
    """The first lapsed offer drives the raw total under the base, and the score stops at the base.

    Per the PRD: "The floor is what makes the penalty saturate — once an applicant
    has declined enough offers to push the raw total below their class base,
    further declines stop changing the score, though they continue to accumulate
    in `declined_offer_count` for the expiry rule below." Eight days of tenure and
    one twenty-five-point penalty give a raw total of eighty-eight, so the stored
    score is the base of one hundred instead.

    Design: Difficulty/combinatorial_formula/waitlist_priority_score_nonlinear_floor
    """
    home, _unit, applicant, _entry = _class_four_applicant_on_a_single_bed_unit(api)
    fx.census_run(api, "2026-08-01", home["id"])

    fx.set_clock(api, "2026-08-09T00:00:00Z")
    fx.census_run(api, "2026-08-09", home["id"])

    refreshed = fx.read_applicant(api, applicant["id"])
    assert refreshed["priority_score"] == 100
    assert refreshed["declined_offer_count"] == 1


def test_repeated_declines_leave_the_score_pinned_and_the_entry_in_the_queue(api):
    """Two lapsed offers accumulate on the counter while the score never moves off the base.

    Per the PRD: "the owning applicant's `declined_offer_count` increases by 1,
    the applicant's `priority_score` is recomputed — picking up the additional
    twenty-five-point penalty, still floored at the class base — every `ACTIVE` or
    `OFFERED` entry on that unit has its `queue_position` recomputed, and the
    entry's `version` increments." The applicant keeps their place in line at the
    floored score, and two declines are not yet enough to expire the entry.

    Design: Difficulty/combinatorial_formula/waitlist_priority_score_nonlinear_floor
    """
    home, unit, applicant, entry = _class_four_applicant_on_a_single_bed_unit(api)
    fx.census_run(api, "2026-08-01", home["id"])
    fx.set_clock(api, "2026-08-09T00:00:00Z")
    fx.census_run(api, "2026-08-09", home["id"])
    fx.set_clock(api, "2026-08-10T00:00:00Z")
    fx.census_run(api, "2026-08-10", home["id"])
    fx.set_clock(api, "2026-08-18T00:00:00Z")
    fx.census_run(api, "2026-08-18", home["id"])

    refreshed = fx.read_applicant(api, applicant["id"])
    assert refreshed["priority_score"] == 100
    assert refreshed["declined_offer_count"] == 2

    entries = {row["id"]: row for row in fx.read_waitlist_entries_for_unit(api, unit["id"])}
    assert entries[entry["id"]]["status"] == "ACTIVE"
    assert entries[entry["id"]]["queue_position"] == 1
    assert fx.read_unit(api, unit["id"])["waitlist_active_count"] == 1
