"""Incident report tests: minting, state machine, terminal lockdown (PRD §3.2-§3.3)."""
import re

import pytest

from test_helpers import (
    validate_success, validate_error, get_success_data,
    create_geography, create_draft_incident, create_submitted_incident,
    create_under_classification_incident, create_classified_incident,
    create_unfounded_incident, create_classify_payload, create_offense_count_payload,
    get_log_entry_for_incident, list_log_for_incident,
    ApiErrorId, assert_incident, NON_EXISTENT_UUID, DEFAULT_CLOCK_UTC, TEST_USERS,
)

CHIEF = TEST_USERS["chief_headers"]
COORD = TEST_USERS["coordinator_headers"]


def test_incident_system_fields_server_minted(api):
    """PRD §3.2: "The server mints a `report_number` of the form
    IR-<year>-<seq6>; any client-supplied value is ignored. New incidents are
    born `DRAFT`, with `is_clery_reportable` false and `classified_at` unset."
    PRD §2.4: "Before any call to the clock-control capability, the logical
    clock reads exactly `2026-08-01T00:00:00Z`."

    Design: Corner/entities/incident_system_fields_server_minted
    """
    geography = create_geography(name="Quad", category="ON_CAMPUS")
    incident = validate_success(api.create_incident(
        {
            "reported_at": "2026-03-01T09:00:00Z",
            "occurred_at": "2026-03-01T08:00:00Z",
            "geography_id": geography["id"],
            "source": "POLICE_DIRECT",
            "narrative": "Test",
        },
        CHIEF,
    ), 201)
    assert_incident(incident)
    assert re.fullmatch(r"IR-2026-\d{6}", incident["report_number"]), (
        f"report_number must match IR-<year>-<seq6>; got {incident['report_number']}"
    )
    assert incident["status"] == "DRAFT"
    assert incident["version"] == 1
    assert incident["created_at"] == DEFAULT_CLOCK_UTC
    assert incident["updated_at"] == DEFAULT_CLOCK_UTC


def test_get_nonexistent_incident_not_found_returns_404(api):
    """PRD §2.6: "any identifier that does not resolve produces `ERR_NOT_FOUND`
    (HTTP 404)."

    Design: Corner/entities/get_nonexistent_incident_not_found_returns_404
    """
    res = api.get_incident(NON_EXISTENT_UUID, CHIEF)
    validate_error(res, ApiErrorId.ERR_NOT_FOUND.value, expected_status=404)


def test_incident_missing_required_field_returns_invalid_request(api):
    """PRD §2.5: "Any request body containing a required field that is missing,
    or a field of a malformed type, is rejected with `ERR_INVALID_REQUEST`
    (HTTP 400) before any deeper validation runs."

    Design: Corner/validations/incident_missing_required_field_returns_invalid_request
    """
    geography = create_geography(name="Q", category="ON_CAMPUS")
    res = api.create_incident(
        {
            # reported_at deliberately omitted
            "occurred_at": "2026-04-01T08:00:00Z",
            "geography_id": geography["id"],
            "source": "POLICE_DIRECT",
            "narrative": "x",
        },
        CHIEF,
    )
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST.value, expected_status=400)


def test_incident_submit_valid_transition(api):
    """PRD §3.3: "a `DRAFT` incident is submitted by a `CleryCoordinator` —
    attempting submission from any other state yields `ERR_INVALID_STATE` —
    which transitions it `DRAFT → SUBMITTED`, increments its `version`, and has
    an important side effect described in §3.4."

    Design: Corner/state_machines/incident_submit_valid_transition
    """
    geography = create_geography(name="Plaza", category="ON_CAMPUS")
    incident = create_draft_incident(
        geography["id"], reported_at="2026-04-01T09:00:00Z",
        occurred_at="2026-04-01T08:00:00Z",
    )
    submitted = validate_success(api.submit_incident(incident["id"], CHIEF), 200)
    assert submitted["status"] == "SUBMITTED"
    assert submitted["version"] == 2


def test_classify_from_draft_returns_invalid_state(api):
    """PRD §3.3: "From `SUBMITTED`, a coordinator begins classification, moving
    the incident `SUBMITTED → UNDER_CLASSIFICATION`. From `CLASSIFIED`, a
    coordinator may begin reclassification, moving `CLASSIFIED →
    UNDER_RECLASSIFICATION`; both classification paths then converge on the
    same classify operation, which returns the incident to `CLASSIFIED`."

    Design: Corner/state_machines/classify_from_draft_returns_invalid_state
    """
    geography = create_geography(name="Yard", category="ON_CAMPUS")
    incident = create_draft_incident(
        geography["id"], reported_at="2026-04-02T09:00:00Z",
        occurred_at="2026-04-02T08:00:00Z",
    )
    res = api.classify_incident(
        incident["id"],
        create_classify_payload(
            geography["id"],
            expected_incident_version=incident["version"],
            offense_counts=[create_offense_count_payload()],
        ),
        COORD,
    )
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value, expected_status=409)

    after = validate_success(api.get_incident(incident["id"], COORD), 200)
    assert after["status"] == "DRAFT"


def test_begin_reclassification_from_unfounded_returns_incident_terminal(api):
    """PRD §3.3: "Attempting any incident action from the terminal states
    `UNFOUNDED` or `WITHDRAWN` is rejected with `ERR_INCIDENT_TERMINAL`
    (HTTP 409) rather than the generic state error."

    Design: Corner/state_machines/begin_reclassification_from_unfounded_returns_incident_terminal
    """
    geography = create_geography(name="Court", category="ON_CAMPUS")
    incident = create_unfounded_incident(
        geography["id"],
        reported_at="2026-04-03T09:00:00Z", occurred_at="2026-04-03T08:00:00Z",
        offense_counts=[create_offense_count_payload(offense_type="ROBBERY")],
        justification="Fabricated",
    )
    res = api.begin_reclassification(incident["id"], COORD)
    validate_error(res, ApiErrorId.ERR_INCIDENT_TERMINAL.value, expected_status=409)


def test_withdraw_then_submit_returns_incident_terminal(api):
    """PRD §3.3: "Attempting any incident action from the terminal states
    `UNFOUNDED` or `WITHDRAWN` is rejected with `ERR_INCIDENT_TERMINAL`
    (HTTP 409) rather than the generic state error."

    Design: Corner/state_machines/withdraw_then_submit_returns_incident_terminal
    """
    geography = create_geography(name="Terrace", category="ON_CAMPUS")
    incident = create_draft_incident(
        geography["id"], reported_at="2026-04-05T09:00:00Z",
        occurred_at="2026-04-05T08:00:00Z", source="ANONYMOUS", headers=COORD,
    )
    withdrawn = validate_success(api.withdraw_incident(incident["id"], COORD), 200)
    assert withdrawn["status"] == "WITHDRAWN"

    res = api.submit_incident(incident["id"], CHIEF)
    validate_error(res, ApiErrorId.ERR_INCIDENT_TERMINAL.value, expected_status=409)


def test_initial_states_on_creation(api):
    """PRD §3.2: "New incidents are born `DRAFT`, with `is_clery_reportable`
    false and `classified_at` unset."
    PRD §3.9: "A new review is born `OPENED` with `penalty_score` 0,
    `escalated` false, `open_action_count` 0, and `opened_at` set to its
    creation time."
    PRD §3.9 describes actions moving `OPEN → SUBMITTED`, i.e. new corrective
    actions start `OPEN`.

    Design: Corner/state_machines/initial_states_on_creation
    """
    geography = create_geography(name="Green", category="ON_CAMPUS")
    incident = create_draft_incident(
        geography["id"], reported_at="2026-04-06T09:00:00Z",
        occurred_at="2026-04-06T08:00:00Z",
    )
    assert incident["status"] == "DRAFT"

    review = validate_success(api.create_program_review(
        {"scope_year_start": 2020, "scope_year_end": 2021},
        TEST_USERS["reviewer_headers"],
    ), 201)
    assert review["status"] == "OPENED"

    review = validate_success(api.advance_review(review["id"], TEST_USERS["reviewer_headers"]), 200)
    assert review["status"] == "FINDINGS_ISSUED"

    action = validate_success(api.create_corrective_action(
        review["id"],
        {"finding_code": "FW-300", "severity": "LOW",
         "description": "d", "due_date": "2026-09-01"},
        TEST_USERS["reviewer_headers"],
    ), 201)
    assert action["status"] == "OPEN"


def test_incident_reclassification_cycle_replaces_offenses(api):
    """PRD §3.3: "Classification replaces the incident's entire prior offense
    row set with the submitted set."
    PRD §3.4: "On every successful classification, the entry's `nature` is
    rewritten to the primary offense label and its `general_location` to the
    geography's name at classification time."

    Design: Difficulty/non_linear_state_machine/incident_reclassification_cycle
    """
    geography = create_geography(name="Library", category="ON_CAMPUS")
    incident = create_classified_incident(
        geography["id"],
        offense_counts=[create_offense_count_payload(offense_type="BURGLARY")],
        reported_at="2026-03-15T10:00:00Z", occurred_at="2026-03-15T04:00:00Z",
    )
    assert incident["status"] == "CLASSIFIED"
    assert incident["version"] == 4, (
        "create(1) -> submit(2) -> begin-classification(3) -> classify(4)"
    )

    reclass = validate_success(api.begin_reclassification(incident["id"], COORD), 200)
    assert reclass["status"] == "UNDER_RECLASSIFICATION"
    assert reclass["version"] == 5

    classified_again = validate_success(api.classify_incident(
        incident["id"],
        create_classify_payload(
            geography["id"],
            expected_incident_version=reclass["version"],
            offense_counts=[create_offense_count_payload(offense_type="ARSON")],
        ),
        COORD,
    ), 200)
    assert classified_again["status"] == "CLASSIFIED"
    assert classified_again["version"] == 6

    offenses = get_success_data(api.list_offense_counts(incident["id"], COORD))
    offense_list = offenses if isinstance(offenses, list) else offenses.get("items", offenses)
    assert len(offense_list) == 1, (
        f"Reclassification must replace the prior offense set; got {len(offense_list)} rows"
    )
    assert offense_list[0]["offense_type"] == "ARSON"
    assert offense_list[0]["status"] == "COUNTED"

    entry = get_log_entry_for_incident(incident["id"], headers=COORD)
    assert entry["nature"] == "ARSON", (
        "The log entry nature must follow the latest classification's primary offense"
    )


def test_incident_reclassification_version_increments(api):
    """PRD §3.3: "Every incident state transition increments the incident's
    `version` by one."
    PRD §3.3: "From `CLASSIFIED`, a coordinator may begin reclassification,
    moving `CLASSIFIED → UNDER_RECLASSIFICATION`; both classification paths
    then converge on the same classify operation, which returns the incident to
    `CLASSIFIED`."

    Design: Difficulty/non_linear_state_machine/incident_reclassification_cycle
    """
    geography = create_geography(name="Library West", category="ON_CAMPUS")
    incident = create_classified_incident(
        geography["id"],
        offense_counts=[create_offense_count_payload(offense_type="BURGLARY")],
        reported_at="2026-03-16T10:00:00Z", occurred_at="2026-03-16T04:00:00Z",
    )
    assert incident["version"] == 4

    reclass = validate_success(api.begin_reclassification(incident["id"], COORD), 200)
    assert reclass["version"] == incident["version"] + 1

    classified_again = validate_success(api.classify_incident(
        incident["id"],
        create_classify_payload(
            geography["id"],
            expected_incident_version=reclass["version"],
            offense_counts=[create_offense_count_payload(offense_type="BURGLARY")],
        ),
        COORD,
    ), 200)
    assert classified_again["version"] == reclass["version"] + 1
    assert classified_again["status"] == "CLASSIFIED"
