"""Destination results, the composite disposition, dissemination and the challenge cycle."""

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    TEST_USERS,
    assert_chr_response,
    issue_determination,
    make_adjudicator_headers,
    make_applicant_headers,
    post_result,
    set_clock,
    setup_transmitted_submission,
    state_response_of,
    validate_error,
    validate_paginated,
    validate_success,
)

VA = TEST_USERS["vendor_admin_headers"]
TECH = TEST_USERS["technician_headers"]
ADJ = TEST_USERS["adjudicator_headers"]
ADJ2 = TEST_USERS["second_adjudicator_headers"]
DEST = TEST_USERS["destination_headers"]


def _state_accepted_then_fbi_pending():
    world = setup_transmitted_submission(
        clock_start="2026-06-01T09:00:00Z",
        score=82,
        transmit_clock="2026-06-01T10:05:00Z",
    )
    world["disposition_after_state"] = post_result(
        world["submission"]["id"], "STATE", "ACCEPTED", record_count=0, disqualifying_offense_count=0
    )["composite_disposition"]
    return world


def test_a_pending_federal_axis_holds_the_composite_at_incomplete(api):
    """PRD 3.5: "Results arrive one destination at a time, from the `StateRepository` role, and each
    posting advances **only** the axis it names."
    PRD 3.5: "1. If `state_status` is still `PENDING`, or the FBI is required and `fbi_status` is
    still `PENDING`, the disposition is `INCOMPLETE`. A `STATE_ONLY` submission with an accepted
    state result is therefore never held at `INCOMPLETE` by its `NOT_REQUIRED` federal axis."

    Design: Difficulty/non_linear_state_machine/submission_state_and_fbi_axes_advance_independently_to_mixed
    """
    world = _state_accepted_then_fbi_pending()

    assert world["disposition_after_state"] == "INCOMPLETE"

    submission = validate_success(api.get_submission(world["submission"]["id"], TECH), 200)
    assert submission["state_status"] == "ACCEPTED"
    assert submission["fbi_status"] == "PENDING"
    assert submission["destinations"] == ["STATE", "FBI"]


def test_one_rejected_axis_out_of_two_reads_mixed(api):
    """PRD 3.5: "4. If exactly one of the two axes is rejected and the other is not, the disposition
    is `MIXED`."
    PRD 3.5: "`PENDING → REJECTED_TECHNICAL` stamps `state_resulted_at` — which is what anchors the
    free-reprint window — and, stated explicitly because the sibling branch does the opposite,
    **creates no response row at all**: only an acceptance yields one."

    Design: Difficulty/non_linear_state_machine/submission_state_and_fbi_axes_advance_independently_to_mixed
    """
    world = _state_accepted_then_fbi_pending()

    after_fbi = post_result(
        world["submission"]["id"], "FBI", "REJECTED_TECHNICAL", rejection_reason="image quality"
    )

    assert after_fbi["composite_disposition"] == "MIXED"
    assert after_fbi["state_status"] == "ACCEPTED"
    assert after_fbi["fbi_status"] == "REJECTED_TECHNICAL"

    rows, meta = validate_paginated(
        api.list_submission_responses(world["submission"]["id"], VA)
    )
    assert meta["total_count"] == 1, "only the acceptance produced a response row"
    assert rows[0]["destination"] == "STATE"


def _both_axes_accepted_with_one_state_record():
    world = setup_transmitted_submission(clock_start="2026-06-01T09:00:00Z", score=80)
    post_result(
        world["submission"]["id"],
        "STATE",
        "ACCEPTED",
        record_count=1,
        disqualifying_offense_count=0,
        record_detail="2011 misdemeanor, non-disqualifying",
    )
    world["submission"] = post_result(
        world["submission"]["id"], "FBI", "ACCEPTED", record_count=0, disqualifying_offense_count=0
    )
    return world


def test_fitness_codes_turn_on_the_two_boundaries_at_one(api):
    """PRD 3.6: "From the first two the server derives `fitness_code` by a strict order of tests: if
    `disqualifying_offense_count` is at least 1 the code is `INELIGIBLE`; otherwise, if
    `record_count` is at least 1 the code is `ELIGIBLE_WITH_NOTICE`; otherwise the code is
    `ELIGIBLE`. Both boundaries sit at one — zero records is `ELIGIBLE`, and one record carrying zero
    disqualifying offences is `ELIGIBLE_WITH_NOTICE`."

    Design: Corner/calculations/fitness_code_thresholds_at_zero_and_one_record
    """
    world = _both_axes_accepted_with_one_state_record()

    rows, meta = validate_paginated(api.list_submission_responses(world["submission"]["id"], ADJ))
    assert meta["total_count"] == 2

    codes = {}
    for row in rows:
        single = validate_success(api.get_chr_response(row["id"], ADJ), 200)
        destination = validate_success(api.get_chr_response(row["id"], VA), 200)["destination"]
        codes[destination] = single["fitness_code"]

    assert codes["STATE"] == "ELIGIBLE_WITH_NOTICE"
    assert codes["FBI"] == "ELIGIBLE"


def test_any_returned_record_makes_the_completed_submission_a_hit(api):
    """PRD 3.5: "5. Otherwise neither is rejected, and the disposition turns on whether any record
    came back: if any criminal-history response of this submission whose `routing_status` is
    `RECEIVED` or `ROUTED` carries a `record_count` of at least 1, the disposition is `HIT`;
    otherwise it is `CLEARED`."
    PRD 3.6: "The row is created at `routing_status` `RECEIVED` and, provided its parent submission's
    `retention_status` is not `PURGED`, immediately moves `RECEIVED → ROUTED`, stamping `routed_at`
    and setting `routed_recipient_roles`."

    Design: Corner/calculations/fitness_code_thresholds_at_zero_and_one_record
    """
    world = _both_axes_accepted_with_one_state_record()

    assert world["submission"]["composite_disposition"] == "HIT"

    rows, _meta = validate_paginated(api.list_submission_responses(world["submission"]["id"], VA))
    for row in rows:
        shell = validate_success(api.get_chr_response(row["id"], VA), 200)
        assert_chr_response(shell)
        assert shell["routing_status"] == "ROUTED"


def _full_chr_response_with_two_records():
    world = setup_transmitted_submission(clock_start="2026-06-01T09:00:00Z", score=80)
    post_result(
        world["submission"]["id"],
        "STATE",
        "ACCEPTED",
        record_count=2,
        disqualifying_offense_count=1,
        record_detail="1998 CA PC 459 conviction",
    )
    world["response"] = state_response_of(world["submission"]["id"])
    return world


def test_full_chr_adjudicator_sees_the_rap_sheet_when_it_asks_for_detail(api):
    """PRD 3.6: "- An `AgencyAdjudicator` reading a response under a `FULL_CHR` ORI sees
    `fitness_code`, `record_count` and `disqualifying_offense_count`, and additionally sees
    `record_detail` when — and only when — `include_detail` is true."

    Design: Corner/endpoints/full_chr_tier_discloses_detail_to_the_adjudicator_but_never_to_the_applicant
    """
    world = _full_chr_response_with_two_records()

    detailed = validate_success(
        api.get_chr_response(world["response"]["id"], ADJ, {"include_detail": "true"}), 200
    )

    assert detailed["record_detail"] == "1998 CA PC 459 conviction"
    assert detailed["fitness_code"] == "INELIGIBLE"
    assert detailed["record_count"] == 2
    assert detailed["disqualifying_offense_count"] == 1


def test_the_applicant_gets_a_fitness_code_and_never_the_detail(api):
    """PRD 3.6: "- An `Applicant` sees `fitness_code` alone under either tier, and asking for
    `include_detail` is refused with `ERR_DISSEMINATION_NOT_ENTITLED`."
    PRD 3.6: "The stored row is never mutated by a read; the projection is computed per request from
    the reading role, the ORI's `dissemination_tier`, and the optional `include_detail` flag on the
    single-response read"

    Design: Corner/endpoints/full_chr_tier_discloses_detail_to_the_adjudicator_but_never_to_the_applicant
    """
    world = _full_chr_response_with_two_records()
    applicant_headers = make_applicant_headers(world["applicant"]["id"])

    plain = validate_success(api.get_chr_response(world["response"]["id"], applicant_headers), 200)
    assert plain["fitness_code"] == "INELIGIBLE"
    assert plain["record_detail"] is None

    refused = api.get_chr_response(
        world["response"]["id"], applicant_headers, {"include_detail": "true"}
    )
    validate_error(refused, ApiErrorId.ERR_DISSEMINATION_NOT_ENTITLED.value)

    still_stored = validate_success(
        api.get_chr_response(world["response"]["id"], ADJ, {"include_detail": "true"}), 200
    )
    assert still_stored["record_detail"] == "1998 CA PC 459 conviction"


def test_fitness_code_only_tier_nulls_the_counts_even_for_the_adjudicator(api):
    """PRD 3.6: "- An `AgencyAdjudicator` reading a response under a `FITNESS_CODE_ONLY` ORI sees
    `fitness_code` alone; `record_count`, `disqualifying_offense_count` and `record_detail` all read
    null. Asking for `include_detail` here is refused with `ERR_DISSEMINATION_NOT_ENTITLED`."
    PRD 3.1: "- `NONCRIMINAL_STATUTORY` yields `destination_requirement` `STATE_AND_FBI`,
    `dissemination_tier` `FITNESS_CODE_ONLY`, `retention_permitted` true and `rapback_authority` true."

    Design: Corner/endpoints/fitness_code_only_tier_refuses_detail_even_to_the_adjudicator
    """
    world = setup_transmitted_submission(
        clock_start="2026-06-01T09:00:00Z",
        agency_overrides={"name": "School District"},
        ori_overrides={"statutory_authority": "NONCRIMINAL_STATUTORY"},
        score=80,
    )
    post_result(
        world["submission"]["id"],
        "STATE",
        "ACCEPTED",
        record_count=3,
        disqualifying_offense_count=0,
        record_detail="three sealed juvenile entries",
    )
    response_row = state_response_of(world["submission"]["id"])

    assert world["ori"]["dissemination_tier"] == "FITNESS_CODE_ONLY"

    projected = validate_success(api.get_chr_response(response_row["id"], ADJ), 200)
    assert projected["fitness_code"] == "ELIGIBLE_WITH_NOTICE"
    assert projected["record_detail"] is None
    assert projected["record_count"] is None

    refused = api.get_chr_response(response_row["id"], ADJ, {"include_detail": "true"})
    validate_error(refused, ApiErrorId.ERR_DISSEMINATION_NOT_ENTITLED.value)

    submission = validate_success(api.get_submission(world["submission"]["id"], TECH), 200)
    assert submission["composite_disposition"] == "INCOMPLETE"


def test_destination_result_against_a_submission_that_does_not_exist(api):
    """PRD 2.9 rung 3: "A fingerprint card named in a path that does not exist raises
    `ERR_CARD_NOT_FOUND`; a submission named in a path that does not exist raises
    `ERR_SUBMISSION_NOT_FOUND`; every other missing path resource — agency, ORI, service type,
    capture site, device, device assignment, applicant, appointment, position capture,
    criminal-history response, fitness determination, rap-back subscription, rap-back notification,
    fee assessment or invoice — raises `ERR_REFERENCE_NOT_FOUND`. All three carry HTTP 404."

    Design: Corner/entities/destination_result_on_unknown_submission_returns_submission_not_found
    """
    set_clock("2026-06-01T09:00:00Z")

    response = api.post_destination_result(
        NON_EXISTENT_UUID,
        {
            "destination": "STATE",
            "result_code": "ACCEPTED",
            "record_count": 0,
            "disqualifying_offense_count": 0,
        },
        DEST,
    )

    validate_error(response, ApiErrorId.ERR_SUBMISSION_NOT_FOUND.value)


def _issued_not_fit_determination():
    world = setup_transmitted_submission(clock_start="2026-06-01T09:00:00Z", score=80)
    post_result(
        world["submission"]["id"],
        "STATE",
        "ACCEPTED",
        record_count=2,
        disqualifying_offense_count=1,
        record_detail="2005 felony",
    )
    set_clock("2026-06-01T11:00:00Z")
    issue_determination(world, outcome="NOT_FIT")
    return world


def test_the_issuing_adjudicator_may_not_resolve_the_challenge(api):
    """PRD 3.6: "The applicant may push back, twice at most. Filing a challenge supplies written
    `grounds` and is admitted from `ISSUED` and from `REAFFIRMED`; it is refused with
    `ERR_CHALLENGE_WINDOW_CLOSED` once the logical clock has passed `issued_at` plus 21 days, and
    with `ERR_CHALLENGE_LIMIT_REACHED` once `challenge_count` has reached 2."
    PRD 3.6: "Resolution is a different adjudicator's job — the acting `X-User-ID` must differ from
    `issued_by_user_id`, or the request is `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/validations/challenge_cycle_is_capped_at_two_and_then_the_filing_window_closes
    """
    world = _issued_not_fit_determination()
    applicant_headers = make_applicant_headers(world["applicant"]["id"])

    challenged = validate_success(
        api.file_challenge(world["determination"]["id"], "the 2005 entry is not mine", applicant_headers),
        200,
    )
    assert challenged["status"] == "CHALLENGED"
    assert challenged["challenge_count"] == 1

    self_resolved = api.resolve_challenge(
        world["determination"]["id"], {"resolution": "REAFFIRM"}, make_adjudicator_headers("adj-01")
    )
    validate_error(self_resolved, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)

    reaffirmed = validate_success(
        api.resolve_challenge(world["determination"]["id"], {"resolution": "REAFFIRM"}, ADJ2), 200
    )
    assert reaffirmed["status"] == "REAFFIRMED"
    assert reaffirmed["resolved_by_user_id"] == "adj-02"


def test_the_third_challenge_hits_the_budget_then_the_window_closes(api):
    """PRD 3.6: "`REAFFIRM` moves the determination `CHALLENGED → REAFFIRMED`, sets
    `resolved_by_user_id`, clears `challenge_filed_at`, and re-opens the cycle so long as
    `challenge_count` remains below 2."
    PRD 3.6: "Note that the 21-day window is anchored to the **original** issuance instant and is
    never re-anchored by a reaffirmation, so a slow first cycle can close the door on the second."

    Design: Corner/validations/challenge_cycle_is_capped_at_two_and_then_the_filing_window_closes
    """
    world = _issued_not_fit_determination()
    determination_id = world["determination"]["id"]
    applicant_headers = make_applicant_headers(world["applicant"]["id"])

    validate_success(api.file_challenge(determination_id, "the 2005 entry is not mine", applicant_headers), 200)
    validate_success(api.resolve_challenge(determination_id, {"resolution": "REAFFIRM"}, ADJ2), 200)
    second = validate_success(
        api.file_challenge(determination_id, "identity theft report attached", applicant_headers), 200
    )
    assert second["challenge_count"] == 2
    validate_success(api.resolve_challenge(determination_id, {"resolution": "REAFFIRM"}, ADJ2), 200)

    over_budget = api.file_challenge(determination_id, "third attempt", applicant_headers)
    validate_error(over_budget, ApiErrorId.ERR_CHALLENGE_LIMIT_REACHED.value)

    set_clock("2026-06-26T11:00:00Z")
    too_late = api.file_challenge(determination_id, "late attempt", applicant_headers)
    validate_error(too_late, ApiErrorId.ERR_CHALLENGE_WINDOW_CLOSED.value)

    final = validate_success(api.get_fitness_determination(determination_id, ADJ), 200)
    assert final["status"] == "REAFFIRMED"
    assert final["challenge_count"] == 2
    assert final["outcome"] == "NOT_FIT"
