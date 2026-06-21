"""Storm-event re-dispatch loop and a pair of violation-to-error guards.

Translates queue B (Corner) `state_machines` (storm redispatch) and `errors`
instances.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId,
    create_account_payload, create_site_payload, create_crew_payload,
    create_storm_event_payload,
    fixtures,
)
from test_helpers.test_users import TEST_USERS

AM = TEST_USERS["account_manager_headers"]
CL = TEST_USERS["crew_lead_headers"]
DO = TEST_USERS["dispatch_operator_headers"]


def test_storm_event_redispatch_loop_clears_crew(api):
    """PRD §3.8: "A `DispatchOperator` may abandon a dispatched event, which
    requires it to be `DISPATCHED` (otherwise `ERR_EVENT_NOT_DISPATCHED`), resets
    `assigned_crew_id` to null, and returns the event from `DISPATCHED` to
    `REPORTED` so it can be re-dispatched".

    Design: Corner/state_machines/storm_event_redispatch_loop_clears_crew
    """
    setup = fixtures.setup_reported_storm_event(
        snow_zone="STANDARD", snowfall_inches=5,
        certified_crews=[{"hourly_rate_cents": 5000, "certified_for_snow": True}])
    dispatched = validate_success(api.dispatch_storm_event(setup["event"]["id"], DO), expected_status=200)
    assert dispatched["status"] == "DISPATCHED"
    assert dispatched["assigned_crew_id"] is not None
    abandoned = validate_success(api.abandon_storm_event(setup["event"]["id"], DO), expected_status=200)
    assert abandoned["status"] == "REPORTED"
    assert abandoned["assigned_crew_id"] is None


def test_dispatch_with_no_certified_crew_returns_error(api):
    """PRD §3.8: "requires at least one crew with `certified_for_snow` set to true
    to exist under the event's account; if the certified pool is empty, the
    request is rejected with `ERR_NO_CERTIFIED_CREW`."

    Design: Corner/errors/dispatch_with_no_certified_crew_returns_error
    """
    acct = get_success_data(api.create_account(create_account_payload(), AM))
    site = get_success_data(api.create_site(
        create_site_payload(acct["id"], name="HQ", address="9 Oak", turf_area_sqft=4000), AM))
    # one non-certified crew exists -> certified pool is still empty
    get_success_data(api.create_crew(
        create_crew_payload(acct["id"], name="Mow Crew", hourly_rate_cents=5000, certified_for_snow=False), AM))
    event = get_success_data(api.create_storm_event(create_storm_event_payload(site["id"]), DO))
    resp = api.dispatch_storm_event(event["id"], DO)
    validate_error(resp, ApiErrorId.ERR_NO_CERTIFIED_CREW.value, expected_status=409)


def test_complete_visit_zero_actual_minutes_rejected(api):
    """PRD §3.5: "The completion body carries `actual_labor_minutes`, the actual
    on-site minutes, which must be greater than zero; a value that is not greater
    than zero is rejected with `ERR_INVALID_ACTUAL_MINUTES`."

    Design: Corner/errors/complete_visit_zero_actual_minutes_rejected
    """
    scenario = fixtures.setup_started_visit()  # visit IN_PROGRESS
    resp = api.complete_visit(scenario["visit"]["id"], {"actual_labor_minutes": 0}, CL)
    validate_error(resp, ApiErrorId.ERR_INVALID_ACTUAL_MINUTES.value, expected_status=400)
