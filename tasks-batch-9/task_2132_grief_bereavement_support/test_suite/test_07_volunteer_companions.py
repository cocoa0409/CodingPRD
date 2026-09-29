"""Volunteer companions: registration, training and certification, matching,
match scoring and the certification-expiry cascade."""

import pytest

from test_helpers import (
    IC,
    PD,
    ApiErrorId,
    UNUSED_UUIDS,
    api_client,
    assert_companion_match,
    assert_volunteer_companion,
    create_assessed_participant,
    create_certified_companion,
    create_companion_match_payload,
    create_participant,
    create_volunteer_companion,
    make_volunteer_companion_headers,
    propose_companion_match,
    read_companion_match,
    read_participant,
    read_volunteer_companion,
    record_training,
    respond_companion_match,
    run_cadence_sweep,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_volunteer_registration_defaults_the_concurrency_ceiling_to_three():
    """PRD 3.6: "A `ProgramDirector` registers an applicant with their `full_name`
    and the `endorsed_loss_types` they may accompany — an array of loss categories
    that defaults to empty — plus an optional `max_concurrent_matches` ceiling that
    defaults to 3 and must be at least one. The applicant starts in status
    `APPLIED` with `training_hours` at zero, an empty `modules_completed` list,
    `active_match_count` at zero, and both `certified_on` and
    `certification_expires_on` null."

    Design: Corner/entities/volunteer_companion_max_concurrent_matches_defaults_to_three
    """
    set_clock()
    data = validate_success(
        api_client.create_volunteer_companion(
            {"full_name": "Noor Ellery",
             "endorsed_loss_types": ["ANTICIPATED_ILLNESS", "SUDDEN_DEATH"]}, PD), 201)
    assert_volunteer_companion(data)
    assert data["max_concurrent_matches"] == 3, (
        f"Expected the declared default of 3, got {data['max_concurrent_matches']}")
    assert data["status"] == "APPLIED"
    assert data["training_hours"] == 0
    assert data["modules_completed"] == []
    assert data["certified_on"] is None
    assert data["certification_expires_on"] is None
    assert data["active_match_count"] == 0


def test_certification_waits_for_both_core_modules_as_well_as_the_hours():
    """PRD 3.6: "Further records while the certification bar has not yet been
    cleared leave the volunteer where they are, in the self-loop
    `IN_TRAINING → IN_TRAINING` — that is, when the hours after adding this record
    still fall short of sixteen, or when `modules_completed` after appending this
    record still does not contain both `CORE_LISTENING` and `CORE_SAFETY`."
    PRD 3.6: "The volunteer then moves to `CERTIFIED`, `certified_on` is stamped
    with the logical clock date, and `certification_expires_on` is set to three
    hundred and sixty-five days after `certified_on`."

    Design: Corner/state_machines/volunteer_companion_certifies_only_after_sixteen_hours_and_both_core_modules
    """
    set_clock()
    companion = create_volunteer_companion(
        full_name="Noor Ellery", endorsed_loss_types=["ANTICIPATED_ILLNESS"],
        max_concurrent_matches=3)

    after_listening = validate_success(
        api_client.create_training_record(
            companion["id"], {"module_code": "CORE_LISTENING", "hours": 16}, PD))
    assert after_listening["status"] == "IN_TRAINING", (
        "sixteen hours alone must not certify without CORE_SAFETY")
    assert after_listening["training_hours"] == 16

    after_safety = validate_success(
        api_client.create_training_record(
            companion["id"], {"module_code": "CORE_SAFETY", "hours": 8}, PD))
    assert after_safety["status"] == "CERTIFIED"
    assert after_safety["certification_expires_on"] == "2027-09-01"

    refreshed = read_volunteer_companion(companion["id"])
    assert refreshed["training_hours"] == 24
    assert refreshed["certified_on"] == "2026-09-01"
    assert refreshed["modules_completed"] == ["CORE_LISTENING", "CORE_SAFETY"]


def test_the_sweep_lapses_an_expired_certification_and_ends_the_active_match():
    """PRD 3.6: "During the operational sweep, any volunteer in `CERTIFIED` whose
    `certification_expires_on` now lies strictly before the logical clock date
    moves `CERTIFIED → LAPSED`, and every companion match that volunteer holds in
    `ACTIVE` is ended with `end_reason` `COMPANION_LAPSED`."
    PRD 3.6: "The match moves `ACTIVE → ENDED`, `ended_on` is stamped with the
    logical clock date, the volunteer's `active_match_count` drops by one, and the
    participant's `has_active_companion` is recomputed — it stays true only while
    at least one of that participant's matches remains `ACTIVE`."

    Design: Corner/state_machines/ops_run_lapses_expired_certification_and_ends_the_active_match
    """
    set_clock()
    companion = create_certified_companion(
        endorsed_loss_types=["ANTICIPATED_ILLNESS"], max_concurrent_matches=3)
    participant = create_assessed_participant(
        loss_type="ANTICIPATED_ILLNESS", grief_severity=10, isolation_index=4,
        functional_impairment=4)
    match = propose_companion_match(companion["id"], participant["id"])
    assert match["match_score"] == pytest.approx(100.00, abs=0.001)
    respond_companion_match(match["id"], companion["id"], "ACCEPT")

    set_clock("2027-09-02T00:00:00Z")
    counters = run_cadence_sweep()
    assert counters["companions_lapsed"] == 1
    assert counters["matches_ended"] == 1

    refreshed_companion = read_volunteer_companion(companion["id"])
    assert refreshed_companion["status"] == "LAPSED"
    assert refreshed_companion["active_match_count"] == 0

    refreshed_match = read_companion_match(match["id"])
    assert refreshed_match["status"] == "ENDED"
    assert refreshed_match["end_reason"] == "COMPANION_LAPSED"
    assert refreshed_match["ended_on"] == "2027-09-02"

    assert read_participant(participant["id"])["has_active_companion"] is False


def test_match_score_reflects_the_headroom_held_at_proposal_time():
    """PRD 3.6: "Endorsement is worth 40 points, awarded in full when the
    participant's `loss_type` appears in the volunteer's `endorsed_loss_types` and
    worth nothing otherwise. Training is worth up to 30 points, scaled by the
    volunteer's `training_hours` divided by the sixteen hours certification
    requires, with that ratio capped at 1 so extra hours beyond sixteen add
    nothing. Headroom is worth up to 30 points, scaled by one minus the volunteer's
    `active_match_count` divided by their `max_concurrent_matches`, so a volunteer
    with a full book scores nothing on this component and an idle volunteer scores
    the full 30. The three components are added and the total rounded half up to
    two decimal places."

    Design: Corner/calculations/companion_match_score_reflects_headroom_at_proposal_time
    """
    set_clock()
    companion = create_certified_companion(
        endorsed_loss_types=["ANTICIPATED_ILLNESS"], max_concurrent_matches=3)
    first_participant = create_assessed_participant(
        loss_type="ANTICIPATED_ILLNESS", grief_severity=10, isolation_index=4,
        functional_impairment=4)
    second_participant = create_assessed_participant(
        loss_type="ANTICIPATED_ILLNESS", grief_severity=10, isolation_index=4,
        functional_impairment=4)

    first_match = propose_companion_match(companion["id"], first_participant["id"])
    assert first_match["match_score"] == pytest.approx(100.00, abs=0.001)
    respond_companion_match(first_match["id"], companion["id"], "ACCEPT")

    second_match = validate_success(
        api_client.create_companion_match(
            create_companion_match_payload(companion["id"],
                                           second_participant["id"]), IC), 201)
    assert_companion_match(second_match)
    assert second_match["match_score"] == pytest.approx(90.00, abs=0.001), (
        f"Expected 40 + 30 + 20 = 90.00 with one of three slots taken, got "
        f"{second_match['match_score']}")

    validate_success(
        api_client.end_companion_match(
            first_match["id"], "COMPLETED",
            make_volunteer_companion_headers(companion["id"])))

    frozen = read_companion_match(second_match["id"])
    assert frozen["match_score"] == pytest.approx(90.00, abs=0.001), (
        "the score is frozen at proposal time and never recomputed")
    assert frozen["status"] == "PROPOSED"
    ended = read_companion_match(first_match["id"])
    assert ended["status"] == "ENDED"
    assert ended["end_reason"] == "COMPLETED"
    assert ended["ended_on"] == "2026-09-01"
    assert read_volunteer_companion(companion["id"])["active_match_count"] == 0
    assert read_participant(first_participant["id"])["has_active_companion"] is False


def test_training_hours_gate_is_reported_ahead_of_the_endorsement_gate():
    """PRD 3.6: "Proposing a match is an `IntakeCoordinator` act naming the
    `companion_id` and the `participant_id`. The volunteer must be in status
    `CERTIFIED`, otherwise `ERR_COMPANION_NOT_CERTIFIED`. The participant's
    `loss_type` must appear in the volunteer's `endorsed_loss_types`, otherwise
    `ERR_LOSS_TYPE_NOT_ENDORSED`. A safety gate applies to the most fragile
    participants: when the participant's `risk_tier` is `HIGH`, the volunteer must
    have accumulated at least twenty-four `training_hours` — half again the sixteen
    that certification requires — otherwise the proposal is refused with
    `ERR_COMPANION_TRAINING_INSUFFICIENT`. That gate is evaluated before the
    endorsement check and before any capacity rule, per §2.5."
    PRD 2.5: "The three safety gates described in §3.4 and §3.6 —
    `ERR_ASSESSMENT_REQUIRED`, `ERR_SUICIDALITY_REQUIRES_COUNSELING` and
    `ERR_COMPANION_TRAINING_INSUFFICIENT`, all 422 — are evaluated here, ahead of
    every referential, temporal, capacity and fiscal rule."

    Design: Corner/validations/safety_error_wins_over_referential_error_on_companion_match_create
    """
    set_clock()
    companion = create_certified_companion(
        endorsed_loss_types=["PERINATAL"], max_concurrent_matches=3,
        listening_hours=8, safety_hours=8)
    assert companion["status"] == "CERTIFIED"
    assert companion["training_hours"] == 16

    participant = create_assessed_participant(
        loss_type="ANTICIPATED_ILLNESS", grief_severity=32, isolation_index=12,
        functional_impairment=12)
    assert participant["risk_tier"] == "HIGH"

    error = validate_error(
        api_client.create_companion_match(
            create_companion_match_payload(companion["id"], participant["id"]), IC),
        ApiErrorId.ERR_COMPANION_TRAINING_INSUFFICIENT.value, 422)
    assert error["error_id"] != ApiErrorId.ERR_LOSS_TYPE_NOT_ENDORSED.value

    rows, meta = validate_paginated(
        api_client.list_companion_matches(
            IC, params={"participant_id": participant["id"]}))
    assert meta["total_count"] == 0


def test_proposing_a_match_to_an_unknown_companion_is_not_found():
    """PRD 2.5: "Every entity identifier named inside the request body resolves to
    an existing record — otherwise the corresponding not-found error (404). This
    rung guards enrollment creation, counselling-referral creation,
    counselling-referral assignment, companion-match creation, cohort creation,
    remembrance-event creation, invitation creation, funding-allocation creation
    and grant-report creation."

    Design: Corner/errors/companion_match_create_with_unknown_companion_returns_companion_not_found
    """
    set_clock()
    participant = create_participant(loss_type="SUDDEN_DEATH")
    validate_error(
        api_client.create_companion_match(
            create_companion_match_payload(UNUSED_UUIDS["companion"],
                                           participant["id"]), IC),
        ApiErrorId.ERR_COMPANION_NOT_FOUND.value, 404)


def test_responding_to_an_unknown_match_is_not_found():
    """PRD 2.8: "Several routes address a child through its parent. Path parameters
    are resolved strictly from left to right: the parent is looked up first, and if
    it does not exist the request fails immediately with that parent's not-found
    error, without any attempt to resolve the remaining segments."

    Design: Corner/errors/companion_match_respond_with_unknown_id_returns_match_not_found
    """
    set_clock()
    companion = create_volunteer_companion(
        full_name="Noor Ellery", endorsed_loss_types=["ANTICIPATED_ILLNESS"],
        max_concurrent_matches=3)
    validate_error(
        api_client.respond_companion_match(
            UNUSED_UUIDS["match"], "ACCEPT",
            make_volunteer_companion_headers(companion["id"])),
        ApiErrorId.ERR_MATCH_NOT_FOUND.value, 404)


def test_proposing_a_match_to_an_applicant_who_is_not_yet_certified_is_refused():
    """PRD 3.6: "Proposing a match is an `IntakeCoordinator` act naming the
    `companion_id` and the `participant_id`. The volunteer must be in status
    `CERTIFIED`, otherwise `ERR_COMPANION_NOT_CERTIFIED`."

    Design: Corner/errors/match_creation_for_an_uncertified_volunteer_returns_companion_not_certified
    """
    set_clock()
    companion = create_volunteer_companion(
        full_name="Noor Ellery", endorsed_loss_types=["PERINATAL"],
        max_concurrent_matches=3)
    participant = create_assessed_participant(
        loss_type="ANTICIPATED_ILLNESS", grief_severity=32, isolation_index=12,
        functional_impairment=12)

    error = validate_error(
        api_client.create_companion_match(
            create_companion_match_payload(companion["id"], participant["id"]), IC),
        ApiErrorId.ERR_COMPANION_NOT_CERTIFIED.value, 409)
    assert error["error_id"] != ApiErrorId.ERR_COMPANION_TRAINING_INSUFFICIENT.value
    assert error["error_id"] != ApiErrorId.ERR_LOSS_TYPE_NOT_ENDORSED.value
    assert read_volunteer_companion(companion["id"])["status"] == "APPLIED"


def test_accepting_beyond_the_concurrency_ceiling_is_refused():
    """PRD 3.6: "Accepting moves the match `PROPOSED → ACTIVE`, but only while the
    volunteer is still `CERTIFIED` and only when taking this match keeps their
    `active_match_count` at or below `max_concurrent_matches` — the current count
    plus one must not exceed the ceiling, otherwise `ERR_MATCH_LIMIT_REACHED`.
    Acceptance stamps `started_on` with the logical clock date, increases the
    volunteer's `active_match_count` by one, and sets the participant's
    `has_active_companion` to true."

    Design: Corner/errors/match_accept_beyond_the_concurrency_ceiling_returns_match_limit_reached
    """
    set_clock()
    companion = create_certified_companion(
        endorsed_loss_types=["ANTICIPATED_ILLNESS"], max_concurrent_matches=1)
    first_participant = create_assessed_participant(
        loss_type="ANTICIPATED_ILLNESS", grief_severity=10, isolation_index=4,
        functional_impairment=4)
    second_participant = create_assessed_participant(
        loss_type="ANTICIPATED_ILLNESS", grief_severity=10, isolation_index=4,
        functional_impairment=4)

    first_match = propose_companion_match(companion["id"], first_participant["id"])
    respond_companion_match(first_match["id"], companion["id"], "ACCEPT")
    second_match = propose_companion_match(companion["id"], second_participant["id"])

    validate_error(
        api_client.respond_companion_match(
            second_match["id"], "ACCEPT",
            make_volunteer_companion_headers(companion["id"])),
        ApiErrorId.ERR_MATCH_LIMIT_REACHED.value, 409)

    assert read_volunteer_companion(companion["id"])["active_match_count"] == 1
    assert read_companion_match(second_match["id"])["status"] == "PROPOSED"
    assert read_participant(second_participant["id"])["has_active_companion"] is False


def test_a_second_proposal_for_a_live_pair_is_a_duplicate_match():
    """PRD 3.6: "Finally, the same volunteer and participant must not already be
    paired in a match that is `PROPOSED` or `ACTIVE`, otherwise
    `ERR_DUPLICATE_MATCH`. The match is created in `PROPOSED` with HTTP 201,
    `started_on`, `ended_on` and `end_reason` all null."

    Design: Corner/errors/duplicate_companion_match_for_the_same_pair_returns_duplicate_match
    """
    set_clock()
    companion = create_certified_companion(
        endorsed_loss_types=["ANTICIPATED_ILLNESS"], max_concurrent_matches=3)
    participant = create_assessed_participant(
        loss_type="ANTICIPATED_ILLNESS", grief_severity=10, isolation_index=4,
        functional_impairment=4)
    match = propose_companion_match(companion["id"], participant["id"])

    validate_error(
        api_client.create_companion_match(
            create_companion_match_payload(companion["id"], participant["id"]), IC),
        ApiErrorId.ERR_DUPLICATE_MATCH.value, 409)

    rows, meta = validate_paginated(
        api_client.list_companion_matches(
            IC, params={"participant_id": participant["id"]}))
    assert meta["total_count"] == 1
    assert read_companion_match(match["id"])["status"] == "PROPOSED"


def test_a_volunteer_may_not_answer_another_volunteers_proposal():
    """PRD 2.1: "When `X-User-Role` is `VolunteerCompanion`, `X-User-ID` is the `id`
    of the acting `VolunteerCompanion`, and ownership checks compare it against the
    volunteer id in the path, or against the `companion_id` of the companion match
    being acted on"
    PRD 3.6: "The volunteer answers the proposal themselves, supplying a `decision`
    of either `ACCEPT` or `DECLINE`."

    Design: Corner/rbac/volunteer_companion_cannot_respond_to_another_volunteers_match
    """
    set_clock()
    companion_a = create_certified_companion(
        endorsed_loss_types=["ANTICIPATED_ILLNESS"], max_concurrent_matches=3)
    companion_b = create_certified_companion(
        endorsed_loss_types=["ANTICIPATED_ILLNESS"], max_concurrent_matches=3,
        full_name="Oren Vale")
    participant = create_assessed_participant(
        loss_type="ANTICIPATED_ILLNESS", grief_severity=10, isolation_index=4,
        functional_impairment=4)
    match = propose_companion_match(companion_a["id"], participant["id"])

    validate_error(
        api_client.respond_companion_match(
            match["id"], "ACCEPT",
            make_volunteer_companion_headers(companion_b["id"])),
        ApiErrorId.ERR_NOT_RESOURCE_OWNER.value, 403)

    assert read_companion_match(match["id"])["status"] == "PROPOSED"
    assert read_volunteer_companion(companion_a["id"])["active_match_count"] == 0
    assert read_volunteer_companion(companion_b["id"])["active_match_count"] == 0
    assert read_participant(participant["id"])["has_active_companion"] is False
