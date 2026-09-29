"""The ineligibility loop: re-entry, the pinned reason order and the bounded cycle.

Ineligibility is not terminal. Amended evidence re-opens the case, re-runs the
three criteria inside the same request and can land the applicant back where they
started, so the state graph contains a cycle that only a counter closes. These
tests walk the cycle to its bound.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import fixtures as fx
from test_helpers.api_errors import ERR_REDETERMINATION_LIMIT
from test_helpers.test_users import make_admissions_coordinator_headers


def _short_service_applicant(api):
    """An applicant whose only failing criterion is the qualifying-service day count."""
    fx.set_clock(api, "2026-08-01T00:00:00Z")
    home = fx.create_home(api)
    fx.create_unit(api, home["id"], care_level="NURSING", licensed_bed_count=2)
    applicant = fx.create_applicant(
        api,
        home["id"],
        service_days=60,
        discharge_character="HONORABLE",
        wartime_service=True,
        service_connected_disability_pct=0,
        nursing_care_for_service_connected=False,
        state_residency_years=3,
        requested_care_level="NURSING",
        application_received_date="2026-08-01",
    )
    return home, applicant


def _raw_determination(api, applicant_id, **payload):
    """Adjudicate eligibility, returning the raw response for error inspection."""
    return api.determine_eligibility(applicant_id, payload, make_admissions_coordinator_headers())


def _determine(api, applicant_id, **payload):
    """Adjudicate eligibility and return the updated applicant."""
    return validate_success(_raw_determination(api, applicant_id, **payload), 200)


def test_first_determination_reports_the_single_failing_criterion(api):
    """Sixty days of service fails the day requirement and nothing else is reported.

    Per the PRD: "the applicant has at least 90 days of qualifying service, or
    else `nursing_care_for_service_connected` is true, which waives the day
    requirement entirely". The determination is a single write, so the applicant's
    version advances by exactly one.

    Design: Difficulty/non_linear_state_machine/applicant_ineligible_redetermination_cycle
    """
    _home, applicant = _short_service_applicant(api)

    decided = _determine(api, applicant["id"], review_note="initial adjudication")

    assert decided["status"] == "INELIGIBLE"
    assert decided["eligibility_reason_code"] == "SERVICE_DAYS_INSUFFICIENT"
    assert decided["version"] == 2


def test_each_redetermination_advances_the_version_by_two_and_moves_the_reason_code(api):
    """Amended evidence reopens the case and re-adjudicates it inside one request.

    Per the PRD: "The very same request then immediately re-runs the three
    criteria and lands the applicant back on either `ELIGIBLE` or `INELIGIBLE`,
    which increments `version` a second time — so a single successful
    redetermination call advances the applicant's `version` by two." Correcting the
    service days while zeroing residency simply moves the failure down the list.

    Design: Difficulty/non_linear_state_machine/applicant_ineligible_redetermination_cycle
    """
    _home, applicant = _short_service_applicant(api)
    _determine(api, applicant["id"], review_note="initial adjudication")

    second = _determine(
        api,
        applicant["id"],
        amended_service_days=200,
        amended_state_residency_years=0,
        review_note="corrected DD-214 service days",
    )
    assert second["eligibility_reason_code"] == "RESIDENCY_INSUFFICIENT"
    assert second["version"] == 4

    third = _determine(
        api,
        applicant["id"],
        amended_discharge_character="DISHONORABLE",
        review_note="discharge upgrade denied",
    )
    assert third["eligibility_reason_code"] == "DISCHARGE_CHARACTER_DISQUALIFYING"
    assert third["version"] == 6


def test_third_reason_code_follows_the_pinned_order_not_the_failure_count(api):
    """With both discharge and residency failing, the discharge code is the one reported.

    Per the PRD: "`eligibility_reason_code` records the **first** failing
    criterion in a pinned order that does not depend on how many criteria failed:
    discharge character first, reported as `DISCHARGE_CHARACTER_DISQUALIFYING`;
    then service days, reported as `SERVICE_DAYS_INSUFFICIENT`; then residency,
    reported as `RESIDENCY_INSUFFICIENT`." Each amended value has overwritten the
    stored evidence it names, and an ineligible outcome clears the priority
    figures.

    Design: Difficulty/non_linear_state_machine/applicant_ineligible_redetermination_cycle
    """
    _home, applicant = _short_service_applicant(api)
    _determine(api, applicant["id"], review_note="initial adjudication")
    _determine(
        api,
        applicant["id"],
        amended_service_days=200,
        amended_state_residency_years=0,
        review_note="corrected DD-214 service days",
    )

    third = _determine(
        api,
        applicant["id"],
        amended_discharge_character="DISHONORABLE",
        review_note="discharge upgrade denied",
    )

    assert third["eligibility_reason_code"] == "DISCHARGE_CHARACTER_DISQUALIFYING"
    assert third["service_days"] == 200
    assert third["state_residency_years"] == 0
    assert third["discharge_character"] == "DISHONORABLE"
    assert third["priority_class"] is None
    assert third["priority_score"] == 0


def test_reopening_loop_is_closed_by_the_redetermination_limit(api):
    """A third reopening is refused, and the applicant is left where the second one landed.

    Per the PRD: "An `INELIGIBLE` applicant whose `redetermination_count` has
    already reached two may not be reopened again, and the attempt is rejected
    with `ERR_REDETERMINATION_LIMIT` (HTTP 409)." The loop terminates on a
    counter rather than on a terminal state.

    Design: Difficulty/non_linear_state_machine/applicant_ineligible_redetermination_cycle
    """
    _home, applicant = _short_service_applicant(api)
    _determine(api, applicant["id"], review_note="initial adjudication")
    _determine(
        api,
        applicant["id"],
        amended_service_days=200,
        amended_state_residency_years=0,
        review_note="corrected DD-214 service days",
    )
    _determine(
        api,
        applicant["id"],
        amended_discharge_character="DISHONORABLE",
        review_note="discharge upgrade denied",
    )

    validate_error(
        _raw_determination(
            api,
            applicant["id"],
            amended_state_residency_years=5,
            review_note="fourth attempt",
        ),
        ERR_REDETERMINATION_LIMIT,
        409,
    )

    refreshed = fx.read_applicant(api, applicant["id"])
    assert refreshed["status"] == "INELIGIBLE"
    assert refreshed["redetermination_count"] == 2
    assert refreshed["version"] == 6
