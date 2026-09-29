"""One survey outcome propagates across the unit, the home and the month's billing.

A decertifying survey is not a single field write. It freezes the unit, empties
its queue, suspends the operating home's federal recognition and destroys the
home's drafted bills, releasing the census days those bills had claimed. These
tests follow the chain hop by hop from a single survey call.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.test_users import make_survey_agency_headers


def _billed_month_with_a_queued_applicant(api):
    """A drafted August bill on a unit that also carries a queued applicant.

    The month is materialised and absorbed into a draft claim before the survey
    lands, so the survey has something to destroy at every hop of the chain.
    """
    scenario = fx.admitted_resident(
        api, admission_date="2026-08-01", care_level="NURSING", licensed_bed_count=2
    )
    second = fx.queue_second_applicant(
        api,
        scenario,
        application_received_date="2026-08-02",
        service_days=800,
        service_connected_disability_pct=40,
        state_residency_years=8,
    )
    fx.set_clock(api, "2026-09-01T00:00:00Z")
    fx.census_run(api, "2026-08-31", scenario.home_id)
    claim = validate_success(
        fx.open_claim(api, scenario.home_id, scenario.unit_id, "2026-08", "AUDITED_BASIS"), 201
    )
    return scenario, second["entry"], claim


def _record_failing_survey(api, care_unit_id):
    """Record one widespread actual-harm deficiency against the unit."""
    return validate_success(
        api.record_survey_result(
            care_unit_id,
            f.survey_result_payload(
                "2026-09-01", [f.deficiency("WIDESPREAD", "ACTUAL_HARM")]
            ),
            make_survey_agency_headers(),
        ),
        200,
    )


def test_widespread_actual_harm_scores_thirty_two_and_decertifies_the_unit(api):
    """A single widespread actual-harm deficiency scores past the band edge.

    Per the PRD: "The scope weights are 1 for `ISOLATED`, 2 for `PATTERN` and 4
    for `WIDESPREAD`. The severity weights are 1 for `MINIMAL`, 3 for
    `MINIMAL_HARM`, 8 for `ACTUAL_HARM` and 20 for `IMMEDIATE_JEOPARDY`." Four
    times eight is thirty-two, which is above the decertification threshold, so
    the unit is decertified and its posture is frozen.

    Design: Difficulty/transitive_cascade/survey_failure_cascade_unit_home_claims
    """
    scenario, _entry, _claim = _billed_month_with_a_queued_applicant(api)

    unit = _record_failing_survey(api, scenario.unit_id)

    assert unit["last_survey_compliance_score"] == 32
    assert unit["certification_status"] == "DECERTIFIED"
    assert unit["operational_posture"] == "FROZEN"
    assert unit["last_survey_date"] == "2026-09-01"


def test_decertification_cancels_every_live_waitlist_entry_on_the_unit(api):
    """Nobody is left queueing for a bed in a decertified unit.

    Per the PRD: "Every `ACTIVE` or `OFFERED` waitlist entry on the unit is set to
    `CANCELLED` and the unit's `waitlist_active_count` becomes 0 — nobody queues
    for a bed in a decertified unit."

    Design: Difficulty/transitive_cascade/survey_failure_cascade_unit_home_claims
    """
    scenario, entry, _claim = _billed_month_with_a_queued_applicant(api)

    _record_failing_survey(api, scenario.unit_id)

    assert fx.read_unit(api, scenario.unit_id)["waitlist_active_count"] == 0
    rows = {row["id"]: row for row in fx.read_waitlist_entries_for_unit(api, scenario.unit_id)}
    assert rows[entry["id"]]["status"] == "CANCELLED"


def test_decertification_suspends_the_operating_home_with_a_stated_reason(api):
    """The home's federal recognition follows its unit down.

    Per the PRD: "Because the unit now counts toward the home's
    `decertified_unit_count`, which rises to at least 1, the home's
    `recognition_status` moves from `RECOGNIZED` to `SUSPENDED` with
    `recognition_suspended_reason` set to `UNIT_DECERTIFIED`, and the home's
    `version` increments."

    Design: Difficulty/transitive_cascade/survey_failure_cascade_unit_home_claims
    """
    scenario, _entry, _claim = _billed_month_with_a_queued_applicant(api)

    _record_failing_survey(api, scenario.unit_id)

    home = fx.read_home(api, scenario.home_id)
    assert home["recognition_status"] == "SUSPENDED"
    assert home["recognition_suspended_reason"] == "UNIT_DECERTIFIED"
    assert home["decertified_unit_count"] == 1


def test_suspension_voids_the_draft_claim_and_returns_its_census_days_to_the_pool(api):
    """The suspended home's drafted bill is destroyed and its days are released.

    Per the PRD: "Each voided claim releases the census days it had attributed:
    their `per_diem_claim_id` returns to null and their `claimed` flag returns to
    false, which puts those days back in the pool for a future claim." This is the
    last hop of the chain, and skipping it would leave a claimable bill on a
    decertified unit.

    Design: Difficulty/transitive_cascade/survey_failure_cascade_unit_home_claims
    """
    scenario, _entry, claim = _billed_month_with_a_queued_applicant(api)

    _record_failing_survey(api, scenario.unit_id)

    assert fx.read_claim(api, claim["id"])["status"] == "VOID"
    census_days = fx.read_census_days(api, resident_id=scenario.resident_id)
    assert len(census_days) == 31
    for row in census_days:
        assert row["claimed"] is False
        assert row["per_diem_claim_id"] is None
