"""Incident creation defaults, lifecycle gating, and operational posture."""
from test_helpers import (
    validate_success, validate_error, is_valid_uuid,
    create_incident_payload, create_volunteer_payload, create_support_request_payload,
    create_shift_payload, create_trip_payload, create_risk_report_payload,
    create_incident, create_active_incident, register_volunteer,
    create_published_request, set_clock, TEST_USERS,
)

MGR = TEST_USERS["manager_headers"]
INTAKE = TEST_USERS["intake_headers"]
LOGI = TEST_USERS["logistics_headers"]
SITE = TEST_USERS["supervisor_headers"]
RISK = TEST_USERS["risk_headers"]
AGENCY = TEST_USERS["agency_headers"]


def test_create_incident_applies_computed_defaults(api):
    """PRD section 3.1: "The incident begins in `ACTIVATION` with
    `operational_posture` `OPEN` and every cost-share field —
    `provisional_cost_share_cents`, `verified_cost_share_cents`,
    `federal_share_cents`, `state_share_cents`, and `local_share_cents` — at
    zero."
    PRD section 2.5: "`version` is an integer starting at 1 at creation and
    incrementing by exactly 1 on every mutation of the resource"

    Design: Corner/entities/create_incident_applies_computed_defaults
    """
    set_clock("2026-08-01T00:00:00Z")
    incident = validate_success(api.create_incident(
        create_incident_payload(name="Flood Tau",
                                ppe_stock={"GLOVES": 4, "MASK": 4, "HARD_HAT": 2,
                                           "VEST": 2, "GOGGLES": 2}), MGR), 201)
    assert incident["lifecycle_status"] == "ACTIVATION"
    assert incident["operational_posture"] == "OPEN"
    assert incident["provisional_cost_share_cents"] == 0
    assert incident["verified_cost_share_cents"] == 0
    assert incident["federal_share_cents"] == 0
    assert incident["state_share_cents"] == 0
    assert incident["local_share_cents"] == 0
    assert incident["version"] == 1
    assert is_valid_uuid(incident["id"])


def test_register_volunteer_before_activation_returns_incident_not_active(api):
    """PRD section 2.7: "Writes that create or modify operational data require
    the incident to be `ACTIVE`; attempts while it is in `ACTIVATION` or
    `CLOSED` fail with `ERR_INCIDENT_NOT_ACTIVE` (HTTP 409)."

    Design: Corner/errors/register_volunteer_before_activation_returns_incident_not_active
    """
    incident = create_incident(name="Fire I3",
                               ppe_stock={"GLOVES": 1, "MASK": 1, "HARD_HAT": 1,
                                          "VEST": 1, "GOGGLES": 1})
    res = api.create_volunteer(
        create_volunteer_payload(incident["id"], full_name="Ada Aamodt"), INTAKE)
    validate_error(res, "ERR_INCIDENT_NOT_ACTIVE")


def test_volunteer_intake_during_demobilization_returns_demobilizing(api):
    """PRD section 2.7: "Any other incident-scoped write — volunteer
    registration, credential claims, request creation or publication, shift
    creation or roster opening, assignment creation, auto-match, check-in, trip
    creation or departure, seat booking, or PPE issuance — is rejected with
    `ERR_INCIDENT_DEMOBILIZING` (HTTP 409)."

    Design: Corner/errors/volunteer_intake_during_demobilization_returns_demobilizing
    """
    incident = create_active_incident(name="Flood J3",
                                      ppe_stock={"GLOVES": 1, "MASK": 1, "HARD_HAT": 1,
                                                 "VEST": 1, "GOGGLES": 1})
    validate_success(api.begin_demobilization(incident["id"], MGR))
    res = api.create_volunteer(
        create_volunteer_payload(incident["id"], full_name="Bo Bao"), INTAKE)
    validate_error(res, "ERR_INCIDENT_DEMOBILIZING")


def test_incident_close_with_nonterminal_volunteer_returns_closing_blocked(api):
    """PRD section 3.1: "Final closure runs only from `DEMOBILIZATION` and is
    the strictest gate in the system: every volunteer of the incident must be
    `DEMOBILIZED`, `WITHDRAWN`, or `REJECTED`; every support request
    `COMPLETED` or `CANCELLED`; every hour entry `VERIFIED` or
    `REJECTED_FINAL`; every PPE issuance `RETURNED`, `DAMAGED`, or `LOST`;
    every trip `ARRIVED` or `CANCELLED`; and every site shift `CANCELLED`. Any
    unmet condition rejects the closure with `ERR_INCIDENT_CLOSING_BLOCKED`."

    Design: Corner/errors/incident_close_with_nonterminal_volunteer_returns_closing_blocked
    """
    incident = create_active_incident(name="Fire K3",
                                      ppe_stock={"GLOVES": 1, "MASK": 1, "HARD_HAT": 1,
                                                 "VEST": 1, "GOGGLES": 1})
    register_volunteer(incident["id"], full_name="Cyd Coe")
    validate_success(api.begin_demobilization(incident["id"], MGR))
    res = api.close_incident(incident["id"], MGR)
    validate_error(res, "ERR_INCIDENT_CLOSING_BLOCKED")


def _critical_report_substantiated(api, incident_id, volunteer_id):
    report = validate_success(api.create_risk_report(
        create_risk_report_payload(volunteer_id, severity="CRITICAL",
                                   category="SAFETY_VIOLATION",
                                   description="Entered structure against orders"),
        SITE), 201)
    return validate_success(api.substantiate_risk_report(report["id"], RISK))


def test_critical_substantiation_freezes_posture_while_lifecycle_stays_active(api):
    """PRD section 2.7: "It is `FROZEN` whenever any volunteer of the incident
    has a `SUBSTANTIATED` risk report of `CRITICAL` severity whose adjudication
    instant is later than the instant exactly 24 hours before now."

    Design: Difficulty/non_linear_state_machine/incident_lifecycle_stays_active_while_posture_freezes_and_thaws
    """
    incident = create_active_incident(name="Quake Zeta")
    volunteer = register_volunteer(incident["id"], full_name="Fred Foss")
    _critical_report_substantiated(api, incident["id"], volunteer["id"])
    after = validate_success(api.get_incident(incident["id"], MGR))
    assert after["operational_posture"] == "FROZEN"
    assert after["lifecycle_status"] == "ACTIVE"


def test_posture_thaws_back_to_open_after_the_24h_window(api):
    """PRD section 2.7: "Otherwise it is `RESTRICTED` when at least 3 of the
    incident's `CRITICAL` support requests stand unfilled in `OPEN` or
    `MATCHING`, or when any `RED`-hazard shift of the incident is
    `OPEN_FOR_ROSTER` or `LOCKED`. Otherwise it is `OPEN`."

    Design: Difficulty/non_linear_state_machine/incident_lifecycle_stays_active_while_posture_freezes_and_thaws
    """
    incident = create_active_incident(name="Quake Zeta")
    volunteer = register_volunteer(incident["id"], full_name="Fred Foss")
    _critical_report_substantiated(api, incident["id"], volunteer["id"])  # adjudicated 2026-08-01T00:00
    set_clock("2026-08-02T01:00:00Z")  # adjudication now 25h old, outside the window
    after = validate_success(api.get_incident(incident["id"], MGR))
    assert after["operational_posture"] == "OPEN"
    assert after["lifecycle_status"] == "ACTIVE"


def test_posture_open_with_two_unfilled_critical_requests(api):
    """PRD section 2.7: "Otherwise it is `RESTRICTED` when at least 3 of the
    incident's `CRITICAL` support requests stand unfilled in `OPEN` or
    `MATCHING`, or when any `RED`-hazard shift of the incident is
    `OPEN_FOR_ROSTER` or `LOCKED`."

    Design: Corner/calculations/posture_restricted_at_exactly_third_unfilled_critical_request
    """
    incident = create_active_incident(name="Flood L2",
                                      ppe_stock={"GLOVES": 1, "MASK": 1, "HARD_HAT": 1,
                                                 "VEST": 1, "GOGGLES": 1})
    for site in ("A", "B"):
        create_published_request(incident["id"], site_name=site, criticality="CRITICAL")
    after_two = validate_success(api.get_incident(incident["id"], MGR))
    assert after_two["operational_posture"] == "OPEN"


def test_third_unfilled_critical_request_restricts_posture_and_blocks_auto_match(api):
    """PRD section 2.7: "While `RESTRICTED`, auto-match alone is rejected with
    `ERR_POSTURE_RESTRICTED` (HTTP 409)."

    Design: Corner/calculations/posture_restricted_at_exactly_third_unfilled_critical_request
    """
    incident = create_active_incident(name="Flood L2",
                                      ppe_stock={"GLOVES": 1, "MASK": 1, "HARD_HAT": 1,
                                                 "VEST": 1, "GOGGLES": 1})
    requests = [create_published_request(incident["id"], site_name=site,
                                         criticality="CRITICAL")
                for site in ("A", "B", "C")]
    after_three = validate_success(api.get_incident(incident["id"], MGR))
    assert after_three["operational_posture"] == "RESTRICTED"
    res = api.auto_match(requests[0]["id"], INTAKE)
    validate_error(res, "ERR_POSTURE_RESTRICTED")


def test_trip_depart_while_posture_frozen_returns_posture_frozen(api):
    """PRD section 2.7: "While `FROZEN`, assignment creation and confirmation,
    auto-match, check-in, and trip departure are rejected with
    `ERR_POSTURE_FROZEN` (HTTP 409)."

    Design: Corner/errors/trip_depart_while_posture_frozen_returns_posture_frozen
    """
    incident = create_active_incident(name="Flood S3",
                                      ppe_stock={"GLOVES": 1, "MASK": 1, "HARD_HAT": 1,
                                                 "VEST": 1, "GOGGLES": 1})
    volunteer = register_volunteer(incident["id"], full_name="Kyo Kae")
    shift = validate_success(api.create_shift(
        create_shift_payload(incident["id"], site_name="Civic Center", capacity=10),
        LOGI), 201)
    trip = validate_success(api.create_trip(
        create_trip_payload(incident["id"], shift["id"], vehicle_id="BUS-3",
                            seat_capacity=30), LOGI), 201)
    _critical_report_substantiated(api, incident["id"], volunteer["id"])
    posture = validate_success(api.get_incident(incident["id"], MGR))
    assert posture["operational_posture"] == "FROZEN"
    res = api.depart_trip(trip["id"], LOGI)
    validate_error(res, "ERR_POSTURE_FROZEN")
