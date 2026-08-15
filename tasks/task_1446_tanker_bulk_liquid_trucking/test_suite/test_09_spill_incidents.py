"""Spill incident severity classification, reporting deadline, and review cycle."""
import pytest

from test_helpers import (
    SO_1,
    SO_2,
    TEST_USERS,
    close_delivery,
    create_customer,
    create_product,
    create_shipment_payload,
    create_spill_plan_payload,
    make_customer_rep_headers,
    make_driver_headers,
    make_safety_officer_headers,
    report_incident,
    set_clock,
    setup_delivered_shipment,
    setup_delivering_shipment,
    setup_in_transit_shipment,
    start_delivery,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["fleet_admin_headers"]
DISP = TEST_USERS["dispatcher_headers"]


def test_severity_threshold_boundaries(api):
    """PRD 3.7: "classifies `severity` by volume: below 10.0 gallons is `MINOR`, at
    least 10.0 but below 100.0 is `MAJOR` (exactly 10.0 therefore classifies
    `MAJOR`), and 100.0 gallons or more is `REPORTABLE` (exactly 100.0 classifies
    `REPORTABLE`)."

    Design: Corner/calculations/severity_threshold_boundaries
    """
    scenario = setup_in_transit_shipment(route_miles=500)
    set_clock("2026-08-02T12:00:00Z")

    inc9 = report_incident(scenario, gallons_spilled=9)
    assert inc9["severity"] == "MINOR"
    inc10 = report_incident(scenario, gallons_spilled=10)
    assert inc10["severity"] == "MAJOR"
    inc100 = report_incident(scenario, gallons_spilled=100)
    assert inc100["severity"] == "REPORTABLE"


def test_reportable_deadline_boundary(api):
    """PRD 3.7: "A `REPORTABLE` incident carries a regulatory deadline: it must be
    reported within 12 hours of `occurred_at`, with the report exactly 12 hours after
    the occurrence still on time; a later report is rejected with
    `ERR_REPORT_DEADLINE_MISSED`." (Clock 2026-08-02T13:00: occurred 25h before is
    late; occurred at 01:00 the same day is exactly 12h, on time.)

    Design: Corner/validations/reportable_deadline_boundary
    """
    scenario = setup_in_transit_shipment(route_miles=500)
    set_clock("2026-08-02T13:00:00Z")
    drv = make_driver_headers(scenario["drv"]["id"])

    res = api.create_spill_incident(
        scenario["ship"]["id"],
        {"occurred_at": "2026-08-01T12:00:00Z", "gallons_spilled": 150},
        drv)
    validate_error(res, "ERR_REPORT_DEADLINE_MISSED", expected_status=422)

    ok = validate_success(api.create_spill_incident(
        scenario["ship"]["id"],
        {"occurred_at": "2026-08-02T01:00:00Z", "gallons_spilled": 150},
        drv), 201)
    assert ok["severity"] == "REPORTABLE"


def test_incident_close_from_reported_rejected(api):
    """PRD 3.7: "Closing requires `UNDER_REVIEW` and additionally requires the
    underlying shipment to be past transit" and "Every incident transition attempted
    from the wrong state is rejected with `ERR_INCIDENT_INVALID_STATE`."

    Design: Corner/state_machines/incident_close_from_reported_rejected
    """
    scenario = setup_in_transit_shipment(route_miles=500)
    incident = report_incident(scenario, gallons_spilled=5)  # stays REPORTED

    res = api.close_spill_incident(incident["id"], make_safety_officer_headers(SO_1))
    validate_error(res, "ERR_INCIDENT_INVALID_STATE", expected_status=409)


def test_incident_close_requires_delivered_shipment(api):
    """PRD 3.7: "Closing requires `UNDER_REVIEW` and additionally requires the
    underlying shipment to be past transit — in `DELIVERED`, `VARIANCE_REVIEW`,
    `RECONCILED`, or `CANCELLED` — else `ERR_SHIPMENT_NOT_DELIVERED`".

    Design: Difficulty/cross_entity_state_dependency/incident_close_requires_delivered_shipment
    """
    scenario = setup_in_transit_shipment(route_miles=500)  # still IN_TRANSIT
    incident = report_incident(scenario, gallons_spilled=5)
    validate_success(
        api.start_incident_review(incident["id"], make_safety_officer_headers(SO_1)), 200)

    res = api.close_spill_incident(incident["id"], make_safety_officer_headers(SO_1))
    validate_error(res, "ERR_SHIPMENT_NOT_DELIVERED", expected_status=409)

    after = validate_success(api.get_spill_incident(incident["id"], DISP), 200)
    assert after["status"] == "UNDER_REVIEW"


def test_incident_close_succeeds_once_shipment_delivered(api):
    """PRD 3.7: "Closing requires `UNDER_REVIEW` and additionally requires the
    underlying shipment to be past transit — in `DELIVERED`, `VARIANCE_REVIEW`,
    `RECONCILED`, or `CANCELLED`"; "a successful close records the acting
    `SafetyOfficer`'s `X-User-ID` in `closed_by_user_id`".

    Design: Difficulty/cross_entity_state_dependency/incident_close_requires_delivered_shipment
    """
    scenario = setup_delivering_shipment(route_miles=500)
    incident = report_incident(scenario, gallons_spilled=5)
    validate_success(
        api.start_incident_review(incident["id"], make_safety_officer_headers(SO_1)), 200)
    close_delivery(scenario, delivered_observed_gal=1000, delivered_temp_F=60)

    closed = validate_success(
        api.close_spill_incident(incident["id"], make_safety_officer_headers(SO_1)), 200)
    assert closed["status"] == "CLOSED"
    assert closed["closed_by_user_id"] == SO_1


def test_spill_incident_review_reopen_cycle(api):
    """PRD 3.7: "Starting review moves `REPORTED → UNDER_REVIEW`; requesting more
    information returns it `UNDER_REVIEW → REPORTED`, and the cycle can repeat" and
    "a successful reopen moves the incident `CLOSED → UNDER_REVIEW`".

    Design: Difficulty/non_linear_state_machine/spill_incident_review_reopen_cycle
    """
    scenario = setup_in_transit_shipment(route_miles=500)
    set_clock("2026-08-02T12:00:00Z")
    incident = report_incident(scenario, gallons_spilled=5)
    so1 = make_safety_officer_headers(SO_1)

    assert validate_success(api.start_incident_review(incident["id"], so1), 200)["status"] == "UNDER_REVIEW"
    assert validate_success(api.request_incident_info(incident["id"], so1), 200)["status"] == "REPORTED"
    assert validate_success(api.start_incident_review(incident["id"], so1), 200)["status"] == "UNDER_REVIEW"

    start_delivery(scenario)
    close_delivery(scenario, delivered_observed_gal=1000, delivered_temp_F=60)
    assert scenario["ship"]["status"] == "DELIVERED"

    assert validate_success(api.close_spill_incident(incident["id"], so1), 200)["status"] == "CLOSED"
    reopened = validate_success(
        api.reopen_spill_incident(incident["id"], make_safety_officer_headers(SO_2)), 200)
    assert reopened["status"] == "UNDER_REVIEW"


def test_incident_request_info_returns_to_reported(api):
    """PRD 3.7: "Starting review moves `REPORTED → UNDER_REVIEW`; requesting more
    information returns it `UNDER_REVIEW → REPORTED`, and the cycle can repeat."

    Design: Difficulty/non_linear_state_machine/spill_incident_review_reopen_cycle
    """
    scenario = setup_in_transit_shipment(route_miles=500)
    incident = report_incident(scenario, gallons_spilled=5)
    so1 = make_safety_officer_headers(SO_1)

    under_review = validate_success(api.start_incident_review(incident["id"], so1), 200)
    assert under_review["status"] == "UNDER_REVIEW"
    back = validate_success(api.request_incident_info(incident["id"], so1), 200)
    assert back["status"] == "REPORTED"
    # The cycle can repeat: a second start-review succeeds.
    again = validate_success(api.start_incident_review(incident["id"], so1), 200)
    assert again["status"] == "UNDER_REVIEW"


def test_incident_reopen_sod(api):
    """PRD 3.7: "Reopening a `CLOSED` incident is possible but segregated: the
    reopener's `X-User-ID` must differ from the recorded `closed_by_user_id`
    (`ERR_SAME_OPERATOR_SEGREGATION`, 403), and a successful reopen moves the incident
    `CLOSED → UNDER_REVIEW` and clears `closed_by_user_id`."

    Design: Corner/complexity_layers/incident_reopen_sod
    """
    scenario = setup_delivering_shipment(route_miles=500)
    incident = report_incident(scenario, gallons_spilled=5)
    so1 = make_safety_officer_headers(SO_1)
    validate_success(api.start_incident_review(incident["id"], so1), 200)
    close_delivery(scenario, delivered_observed_gal=1000, delivered_temp_F=60)
    validate_success(api.close_spill_incident(incident["id"], so1), 200)

    res = api.reopen_spill_incident(incident["id"], so1)
    validate_error(res, "ERR_SAME_OPERATOR_SEGREGATION", expected_status=403)

    reopened = validate_success(
        api.reopen_spill_incident(incident["id"], make_safety_officer_headers(SO_2)), 200)
    assert reopened["status"] == "UNDER_REVIEW"


def test_spill_plan_approve_from_draft_rejected(api):
    """PRD 3.7: "A `SafetyOfficer` adjudicates: approving moves `SUBMITTED →
    APPROVED` and stamps `approved_at` from the clock with `expires_at` computed as
    365 days after approval", and "Both decisions require `SUBMITTED`, else
    `ERR_SPILL_PLAN_INVALID_STATE`." (A DRAFT plan cannot skip submission.)

    Design: Corner/errors/spill_plan_approve_from_draft_rejected
    """
    cust = create_customer()
    prod = create_product()
    plan = validate_success(api.create_spill_plan(
        create_spill_plan_payload(cust["id"], prod["id"]),
        make_customer_rep_headers(cust["id"])), 201)  # DRAFT, never submitted

    res = api.approve_spill_plan(plan["id"], make_safety_officer_headers(SO_1))
    validate_error(res, "ERR_SPILL_PLAN_INVALID_STATE", expected_status=409)


def test_reconcile_blocked_by_open_incident(api):
    """PRD 3.6: "It is blocked while any SpillIncident on this shipment remains in
    `REPORTED` or `UNDER_REVIEW` — the attempt fails with `ERR_OPEN_INCIDENT` (409) —
    so incident hygiene gates final billing."

    Design: Corner/complexity_layers/reconcile_blocked_by_open_incident
    """
    scenario = setup_delivering_shipment(route_miles=500)
    incident = report_incident(scenario, gallons_spilled=5)
    so1 = make_safety_officer_headers(SO_1)
    validate_success(api.start_incident_review(incident["id"], so1), 200)
    close_delivery(scenario, delivered_observed_gal=1000, delivered_temp_F=60)

    res = api.reconcile_shipment(scenario["ship"]["id"], ADMIN)
    validate_error(res, "ERR_OPEN_INCIDENT", expected_status=409)

    validate_success(api.close_spill_incident(incident["id"], so1), 200)
    reconciled = validate_success(api.reconcile_shipment(scenario["ship"]["id"], ADMIN), 200)
    assert reconciled["status"] == "RECONCILED"
