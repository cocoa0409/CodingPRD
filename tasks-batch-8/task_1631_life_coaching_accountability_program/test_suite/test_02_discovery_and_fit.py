"""Discovery call lifecycle, the fit gate, and segregation of duties."""
from datetime import datetime

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_client,
    create_coach,
    create_discovery_call_payload,
    create_fit_assessment_payload,
    get_success_data,
    make_client_headers,
    make_coach_headers,
    reset_clock,
    set_clock,
    setup_coach_pair,
    validate_error,
    validate_success,
)

PM = TEST_USERS["practice_manager_headers"]


def test_discovery_call_no_show_cycle_back_to_scheduled(api):
    """PRD §3.2: "The client may reschedule the call by supplying a new
    `scheduled_start` that lies in the future, returning `call_status` to
    `SCHEDULED` with the new start recorded and the call's `version`
    advancing". "This no-show-and-rebook loop is the machine's only cycle."
    PRD §3.2: "a coach marks the call `NO_SHOW`, but only once the current
    time has reached the end of the call window, start plus
    `duration_minutes`".

    Design: Corner/state_machines/discovery_call_no_show_cycle_back_to_scheduled
    """
    reset_clock()
    coach = create_coach()
    client = create_client()
    client_h = make_client_headers(client["id"])
    resp = api.create_discovery_call(
        create_discovery_call_payload(
            client["id"], coach["id"],
            scheduled_start="2026-08-02T10:00:00Z", duration_minutes=30),
        client_h,
    )
    call = validate_success(resp, expected_status=201)
    set_clock("2026-08-02T10:30:00Z")
    resp = api.mark_discovery_call_no_show(call["id"], make_coach_headers(coach["id"]))
    call = validate_success(resp)
    assert call["call_status"] == "NO_SHOW"

    resp = api.reschedule_discovery_call(
        call["id"], {"scheduled_start": "2026-08-04T10:00:00Z"}, client_h)
    call = validate_success(resp)
    assert call["call_status"] == "SCHEDULED"
    # PRD §3.2 covers "the new start recorded" (the instant); the wire format
    # of a client-supplied timestamp is not pinned (§2.4's three-fractional-
    # digit rule applies to system-managed created_at/updated_at), so compare
    # instants, not strings.
    assert datetime.fromisoformat(call["scheduled_start"]) == \
        datetime.fromisoformat("2026-08-04T10:00:00Z"), \
        "the new start is recorded"

    set_clock("2026-08-04T10:15:00Z")
    resp = api.complete_discovery_call(call["id"], make_coach_headers(coach["id"]))
    call = validate_success(resp)
    assert call["call_status"] == "COMPLETED"


def test_duplicate_fit_assessment_rejected(api):
    """PRD §3.2: "Recording the assessment requires the call to stand
    `COMPLETED` (else `ERR_INVALID_STATE`), accepts exactly one assessment per
    call (a second is `ERR_DUPLICATE_RESOURCE`)".

    Design: Corner/validations/duplicate_fit_assessment_rejected
    """
    coach_a, coach_b = setup_coach_pair()
    coach_c = create_coach(credential_level="ACC")
    client = create_client()
    resp = api.create_discovery_call(
        create_discovery_call_payload(client["id"], coach_a["id"]),
        make_client_headers(client["id"]),
    )
    call = validate_success(resp, expected_status=201)
    set_clock("2026-08-02T12:30:00Z")
    validate_success(
        api.complete_discovery_call(call["id"], make_coach_headers(coach_a["id"])))
    validate_success(
        api.create_fit_assessment(
            call["id"], create_fit_assessment_payload(),
            make_coach_headers(coach_b["id"])),
        expected_status=201,
    )
    # A second assessment — even from a different, eligible assessor — fails.
    resp = api.create_fit_assessment(
        call["id"],
        create_fit_assessment_payload(scope_fit="OUTSIDE_SCOPE", commitment_score=10),
        make_coach_headers(coach_c["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_RESOURCE)


def test_selling_coach_self_assessment_rejected_segregation(api):
    """PRD §2.7: "Segregation of duties is structural, not discretionary: the
    coach who took a discovery call may not grade its fit assessment".
    PRD §3.2: "An assessor who is the call's own coach is rejected with
    `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/validations/selling_coach_self_assessment_rejected_segregation
    """
    reset_clock()
    coach_a = create_coach()
    client = create_client()
    resp = api.create_discovery_call(
        create_discovery_call_payload(client["id"], coach_a["id"]),
        make_client_headers(client["id"]),
    )
    call = validate_success(resp, expected_status=201)
    set_clock("2026-08-02T12:30:00Z")
    validate_success(
        api.complete_discovery_call(call["id"], make_coach_headers(coach_a["id"])))
    resp = api.create_fit_assessment(
        call["id"],
        create_fit_assessment_payload(commitment_score=95),
        make_coach_headers(coach_a["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)


def test_fit_assessment_immutable_after_creation(api):
    """PRD §2.4: "Four record types are append-style and carry only `id` and
    `created_at`: a `FitAssessment`, an `Installment`, a `HabitCheckIn`, and a
    `CohortMembership`. For these four, both `updated_at` and `version` are
    absent entirely."
    PRD §3.2: "a call's assessment reads back as a zero-or-one-element array
    keyed by its `discovery_call_id`."

    Design: Corner/consistency_model/fit_assessment_immutable_after_creation
    """
    coach_a, coach_b = setup_coach_pair()
    client = create_client()
    resp = api.create_discovery_call(
        create_discovery_call_payload(client["id"], coach_a["id"]),
        make_client_headers(client["id"]),
    )
    call = validate_success(resp, expected_status=201)
    set_clock("2026-08-02T12:30:00Z")
    validate_success(
        api.complete_discovery_call(call["id"], make_coach_headers(coach_a["id"])))
    validate_success(
        api.create_fit_assessment(
            call["id"], create_fit_assessment_payload(commitment_score=66),
            make_coach_headers(coach_b["id"])),
        expected_status=201,
    )
    resp = api.get_fit_assessment(call["id"], PM)
    body = resp.json()
    assert resp.status_code == 200
    data = body["data"]
    assert isinstance(data, list) and len(data) == 1, \
        "fit assessment reads back as a one-element array"
    fa = data[0]
    assert fa["discovery_call_id"] == call["id"]
    assert fa["assessor_coach_id"] == coach_b["id"]
    assert fa["outcome"] == "PROCEED"
    assert "id" in fa and "created_at" in fa
    assert "updated_at" not in fa and "version" not in fa, \
        "append-style records carry neither updated_at nor version"
