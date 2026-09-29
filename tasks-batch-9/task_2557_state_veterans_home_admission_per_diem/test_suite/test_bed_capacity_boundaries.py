"""Three thresholds are examined on both sides of their edge.

A bed count of exactly zero, a bed hold of exactly thirty days and a survey score
of exactly twenty-five each sit on an inclusive boundary, so each is probed with
the last value that passes and the first value that fails.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import ERR_BED_HOLD_EXHAUSTED, ERR_UNIT_POSTURE_BLOCKED
from test_helpers.test_users import make_admissions_coordinator_headers, make_survey_agency_headers


def _two_bed_unit_with_three_candidates(api):
    """A two-bed unit and three admissible applicants queued on it.

    Each applicant is eligible, holds an entry on the unit and has a submitted
    assessment at the unit's own care level, written by an assessor who is not the
    coordinator taking the decisions, so only the bed arithmetic can stop them.
    """
    fx.set_clock(api, "2026-08-01T00:00:00Z")
    home = fx.create_home(api)
    unit = fx.create_unit(
        api, home["id"], care_level="NURSING", licensed_bed_count=2, out_of_service_bed_count=0
    )
    candidates = []
    for disability_pct, adl_count in ((90, 5), (85, 4), (75, 3)):
        applicant = fx.create_applicant(
            api,
            home["id"],
            service_connected_disability_pct=disability_pct,
            requested_care_level="NURSING",
            application_received_date="2026-08-01",
        )
        fx.determine_eligibility(api, applicant["id"])
        fx.create_waitlist_entry(api, applicant["id"], unit["id"])
        assessment = fx.create_assessment(
            api,
            applicant["id"],
            assessed_care_level="NURSING",
            adl_dependency_count=adl_count,
            assessment_date="2026-08-01",
        )
        fx.submit_assessment(api, assessment["id"])
        candidates.append({"applicant": applicant, "assessment": assessment})
    return home, unit, candidates


def _admit(api, unit_id, candidate):
    return fx.approve_admission(
        api, candidate["applicant"]["id"], unit_id, candidate["assessment"]["id"], "2026-08-01"
    )


def test_one_bed_still_free_leaves_the_unit_open(api):
    """Filling one of two beds keeps a free bed and keeps the unit open.

    Per the PRD: "Only a certified unit with at least one free bed is `OPEN`." One
    admission out of two licensed beds leaves exactly one free, which is enough.

    Design: Difficulty/boundary_precision_check/admission_posture_flips_at_exactly_zero_available_beds
    """
    _home, unit, candidates = _two_bed_unit_with_three_candidates(api)

    validate_success(_admit(api, unit["id"], candidates[0]), 201)

    refreshed = fx.read_unit(api, unit["id"])
    assert refreshed["occupied_bed_count"] == 1
    assert refreshed["available_bed_count"] == 1
    assert refreshed["operational_posture"] == "OPEN"


def test_the_unit_restricts_itself_at_exactly_zero_free_beds(api):
    """The second admission takes the last bed and flips the posture immediately.

    Per the PRD: "Otherwise, if `available_bed_count` is zero or less, the posture
    is `RESTRICTED`; note the boundary, which keys on "zero or fewer", so a unit
    with exactly zero free beds is already restricted."

    Design: Difficulty/boundary_precision_check/admission_posture_flips_at_exactly_zero_available_beds
    """
    home, unit, candidates = _two_bed_unit_with_three_candidates(api)
    validate_success(_admit(api, unit["id"], candidates[0]), 201)

    validate_success(_admit(api, unit["id"], candidates[1]), 201)

    refreshed = fx.read_unit(api, unit["id"])
    assert refreshed["occupied_bed_count"] == 2
    assert refreshed["available_bed_count"] == 0
    assert refreshed["operational_posture"] == "RESTRICTED"
    assert fx.read_home(api, home["id"])["active_resident_count"] == 2


def test_the_third_admission_is_refused_by_the_restricted_posture(api):
    """A restricted unit cannot be admitted into, so the unit is never oversold.

    Per the PRD: "specifically, an admission decision requires the target unit to
    be `OPEN`, and a transfer in requires only that the target unit not be
    `FROZEN`." The rejected applicant and their assessment are left exactly where
    they were.

    Design: Difficulty/boundary_precision_check/admission_posture_flips_at_exactly_zero_available_beds
    """
    home, unit, candidates = _two_bed_unit_with_three_candidates(api)
    validate_success(_admit(api, unit["id"], candidates[0]), 201)
    validate_success(_admit(api, unit["id"], candidates[1]), 201)

    validate_error(_admit(api, unit["id"], candidates[2]), ERR_UNIT_POSTURE_BLOCKED, 409)

    third = candidates[2]
    assert fx.read_applicant(api, third["applicant"]["id"])["status"] == "WAITLISTED"
    assessments = api.list_applicant_assessments(
        third["applicant"]["id"], make_admissions_coordinator_headers(), {"limit": 100}
    ).json()["data"]
    assert [row["status"] for row in assessments] == ["SUBMITTED"]

    refreshed = fx.read_unit(api, unit["id"])
    assert refreshed["occupied_bed_count"] == 2
    assert refreshed["available_bed_count"] == 0
    assert fx.read_home(api, home["id"])["active_resident_count"] == 2


def _resident_on_a_month_long_bed_hold(api):
    """A resident admitted on 1 August and hospitalised from 2 August onward.

    The clock is carried to 2 September so that either candidate readmission date
    is in the past and only the length of the closed interval is in question.
    """
    scenario = fx.admitted_resident(
        api, admission_date="2026-08-01", care_level="NURSING", licensed_bed_count=2
    )
    fx.hospitalize(api, scenario.resident_id, "2026-08-02", clock="2026-08-02T00:00:00Z")
    fx.set_clock(api, "2026-09-02T00:00:00Z")
    return scenario


def test_a_thirty_one_day_hold_cannot_be_closed_by_readmission(api):
    """Readmitting one day too late would push the hold past the ceiling.

    Per the PRD: "The closed interval's length in whole days, added to
    `bed_hold_days_used`, must not exceed thirty, else `ERR_BED_HOLD_EXHAUSTED`."
    From 2 August to 2 September is thirty-one days, so the resident stays in
    hospital.

    Design: Difficulty/boundary_precision_check/readmission_blocked_at_exactly_thirty_bed_hold_days
    """
    scenario = _resident_on_a_month_long_bed_hold(api)

    validate_error(
        fx.readmit(api, scenario.resident_id, "2026-09-02"), ERR_BED_HOLD_EXHAUSTED, 409
    )

    resident = fx.read_resident(api, scenario.resident_id)
    assert resident["occupancy_status"] == "HOSPITALIZED"
    assert resident["bed_hold_days_used"] == 0
    assert resident["readmission_count"] == 0


def test_a_hold_of_exactly_thirty_days_is_still_closable(api):
    """The ceiling is inclusive, so a thirty-day hold is readmitted and lands on the cap.

    Per the PRD: "On success `occupancy_status` returns to `ADMITTED`,
    `last_hospitalization_end_date` is set to the `readmission_date`,
    `bed_hold_days_used` increases by the number of days between
    `bed_hold_started_on` and the `readmission_date`, `readmission_count` increases
    by 1, `bed_hold_active` becomes false, and the compensating pair reverses."

    Design: Difficulty/boundary_precision_check/readmission_blocked_at_exactly_thirty_bed_hold_days
    """
    scenario = _resident_on_a_month_long_bed_hold(api)
    validate_error(
        fx.readmit(api, scenario.resident_id, "2026-09-02"), ERR_BED_HOLD_EXHAUSTED, 409
    )

    resident = validate_success(fx.readmit(api, scenario.resident_id, "2026-09-01"), 200)

    assert resident["occupancy_status"] == "ADMITTED"
    assert resident["bed_hold_days_used"] == 30
    assert resident["bed_hold_active"] is False
    assert resident["last_hospitalization_end_date"] == "2026-09-01"
    assert resident["readmission_count"] == 1

    unit = fx.read_unit(api, scenario.unit_id)
    assert unit["held_bed_count"] == 0
    assert unit["occupied_bed_count"] == 1


_TWENTY_FOUR_POINT_DEFICIENCIES = [
    f.deficiency("ISOLATED", "ACTUAL_HARM"),
    f.deficiency("WIDESPREAD", "MINIMAL_HARM"),
    f.deficiency("PATTERN", "MINIMAL"),
    f.deficiency("PATTERN", "MINIMAL"),
]


def _empty_certified_unit(api):
    """A recognised home with one certified, unoccupied unit.

    With no residents, bed arithmetic cannot influence the posture, so every
    posture change observed below is attributable to the certification branch.
    """
    fx.set_clock(api, "2026-09-01T00:00:00Z")
    home = fx.create_home(api)
    unit = fx.create_unit(api, home["id"], care_level="NURSING", licensed_bed_count=4)
    return home, unit


def _survey(api, care_unit_id, survey_date, deficiencies):
    return validate_success(
        api.record_survey_result(
            care_unit_id,
            f.survey_result_payload(survey_date, deficiencies),
            make_survey_agency_headers(),
        ),
        200,
    )


def test_a_score_of_exactly_twenty_four_is_only_conditional(api):
    """Twenty-four points restrict the unit but leave the home recognised.

    Per the PRD: "The band edges are inclusive on the lower side, so a score of 24
    is `CONDITIONAL` and a score of 25 decertifies." A conditional unit is
    restricted rather than frozen, and no recognition cascade fires.

    Design: Difficulty/boundary_precision_check/survey_score_24_conditional_versus_25_decertified
    """
    home, unit = _empty_certified_unit(api)

    surveyed = _survey(api, unit["id"], "2026-09-01", _TWENTY_FOUR_POINT_DEFICIENCIES)

    assert surveyed["last_survey_compliance_score"] == 24
    assert surveyed["certification_status"] == "CONDITIONAL"
    assert surveyed["operational_posture"] == "RESTRICTED"

    refreshed_home = fx.read_home(api, home["id"])
    assert refreshed_home["recognition_status"] == "RECOGNIZED"
    assert refreshed_home["decertified_unit_count"] == 0


def test_one_more_point_reaches_twenty_five_and_decertifies(api):
    """Adding a single one-point deficiency crosses the edge and suspends the home.

    Per the PRD: "Because the unit now counts toward the home's
    `decertified_unit_count`, which rises to at least 1, the home's
    `recognition_status` moves from `RECOGNIZED` to `SUSPENDED` with
    `recognition_suspended_reason` set to `UNIT_DECERTIFIED`, and the home's
    `version` increments." The two surveys differ by one point.

    Design: Difficulty/boundary_precision_check/survey_score_24_conditional_versus_25_decertified
    """
    home, unit = _empty_certified_unit(api)
    _survey(api, unit["id"], "2026-09-01", _TWENTY_FOUR_POINT_DEFICIENCIES)

    fx.set_clock(api, "2026-09-02T00:00:00Z")
    surveyed = _survey(
        api,
        unit["id"],
        "2026-09-02",
        _TWENTY_FOUR_POINT_DEFICIENCIES + [f.deficiency("ISOLATED", "MINIMAL")],
    )

    assert surveyed["last_survey_compliance_score"] == 25
    assert surveyed["certification_status"] == "DECERTIFIED"
    assert surveyed["operational_posture"] == "FROZEN"

    refreshed_home = fx.read_home(api, home["id"])
    assert refreshed_home["recognition_status"] == "SUSPENDED"
    assert refreshed_home["recognition_suspended_reason"] == "UNIT_DECERTIFIED"
    assert refreshed_home["decertified_unit_count"] == 1
