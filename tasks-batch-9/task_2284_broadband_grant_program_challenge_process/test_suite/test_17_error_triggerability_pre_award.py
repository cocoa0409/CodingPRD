"""Individual triggerability of the pre-award error families."""

from test_helpers import (
    ApiErrorId,
    api_client,
    append_evidence,
    create_application,
    create_challenge_payload,
    create_location_payload,
    create_program,
    create_score_sheet_payload,
    create_subgrantee_payload,
    current_application_version,
    ingest_location,
    make_subgrantee_headers,
    open_challenge_window,
    read_application,
    read_challenge,
    read_location,
    read_program,
    read_subgrantee,
    register_subgrantee,
    set_clock,
    setup_challenge_open_program,
    setup_community_challenge_meeting_standard,
    setup_qualified_subgrantee,
    setup_submitted_application,
    triage_challenge,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import (
    ADMIN,
    ANALYST,
    ANALYST_OTHER,
    CHALLENGER,
    PROVIDER,
    REVIEWER,
    SCORER,
    close_challenge_window,
    close_rebuttal,
    open_scoring,
)

UNKNOWN_PROGRAM = "00000000-0000-4000-8000-000000000001"
UNKNOWN_LOCATION = "00000000-0000-4000-8000-000000000002"
UNKNOWN_CHALLENGE = "00000000-0000-4000-8000-000000000003"
UNKNOWN_SUBGRANTEE = "00000000-0000-4000-8000-000000000004"
UNKNOWN_APPLICATION = "00000000-0000-4000-8000-000000000005"
UNKNOWN_AWARD = "00000000-0000-4000-8000-0000000000aa"


def test_the_same_unknown_id_names_a_different_entity_in_every_slot():
    """Each existence rung reports the entity of the slot the id occupied, so five
    reads of five empty collections yield five different error identifiers, and a
    program id carried in a request body is resolved by the very same rung as one
    carried in the path.

    PRD 2.12: "**Priorities 20 through 28 — existence,** resolved in this order:
    `program_id` in path or body → `ERR_PROGRAM_NOT_FOUND`; `location_id` in path or
    body → `ERR_LOCATION_NOT_FOUND`; the challenge id in the path →
    `ERR_CHALLENGE_NOT_FOUND`; `subgrantee_id` in path or body →
    `ERR_SUBGRANTEE_NOT_FOUND`; `application_id` in path or body →
    `ERR_APPLICATION_NOT_FOUND`; `award_id` in path or body →
    `ERR_AWARD_NOT_FOUND`; the milestone id in the path, which must belong to the
    award named earlier in the path → `ERR_MILESTONE_NOT_FOUND`; the audit id in the
    path, which must likewise belong to that award, and the environmental-review
    sub-path, which must resolve to an existing review of that award →
    `ERR_AUDIT_NOT_FOUND`; and, for environmental-review sub-actions, the award
    having a review row at all → `ERR_ENVIRONMENTAL_REVIEW_NOT_FOUND`."

    Design: Corner/errors/errors_not_found_family_rejected
    """
    validate_error(
        api_client.get_program(UNKNOWN_PROGRAM, ADMIN),
        ApiErrorId.ERR_PROGRAM_NOT_FOUND,
        404,
    )
    validate_error(
        api_client.get_location(UNKNOWN_LOCATION, ANALYST),
        ApiErrorId.ERR_LOCATION_NOT_FOUND,
        404,
    )
    validate_error(
        api_client.get_challenge(UNKNOWN_CHALLENGE, ANALYST),
        ApiErrorId.ERR_CHALLENGE_NOT_FOUND,
        404,
    )
    validate_error(
        api_client.get_subgrantee(UNKNOWN_SUBGRANTEE, ADMIN),
        ApiErrorId.ERR_SUBGRANTEE_NOT_FOUND,
        404,
    )
    validate_error(
        api_client.get_application(UNKNOWN_APPLICATION, ADMIN),
        ApiErrorId.ERR_APPLICATION_NOT_FOUND,
        404,
    )

    body_borne = api_client.create_subgrantee(
        create_subgrantee_payload(UNKNOWN_PROGRAM), ADMIN
    )
    validate_error(body_borne, ApiErrorId.ERR_PROGRAM_NOT_FOUND, 404)

    _, meta = validate_paginated(api_client.list_subgrantees(ADMIN))
    assert meta["total_count"] == 0, "The refused registration wrote nothing"


def test_an_unknown_award_is_reported_the_same_way_as_a_parent_and_as_a_resource():
    """An award id that resolves to nothing is reported as a missing award whether
    the caller reads the award itself or reaches through it for a sub-collection, and
    the refusal carries the standard error envelope.

    PRD 2.12: "**Priorities 20 through 28 — existence,** resolved in this order:
    `program_id` in path or body → `ERR_PROGRAM_NOT_FOUND`; `location_id` in path or
    body → `ERR_LOCATION_NOT_FOUND`; the challenge id in the path →
    `ERR_CHALLENGE_NOT_FOUND`; `subgrantee_id` in path or body →
    `ERR_SUBGRANTEE_NOT_FOUND`; `application_id` in path or body →
    `ERR_APPLICATION_NOT_FOUND`; `award_id` in path or body →
    `ERR_AWARD_NOT_FOUND`; the milestone id in the path, which must belong to the
    award named earlier in the path → `ERR_MILESTONE_NOT_FOUND`; the audit id in the
    path, which must likewise belong to that award, and the environmental-review
    sub-path, which must resolve to an existing review of that award →
    `ERR_AUDIT_NOT_FOUND`; and, for environmental-review sub-actions, the award
    having a review row at all → `ERR_ENVIRONMENTAL_REVIEW_NOT_FOUND`."
    PRD 2.2: "The `response_type` is either "object" for a single resource or
    "array" for a list of resources."

    Design: Corner/entities/award_fetch_with_unknown_id_returns_not_found
    """
    direct = api_client.get_award(UNKNOWN_AWARD, ADMIN)
    validate_error(direct, ApiErrorId.ERR_AWARD_NOT_FOUND, 404)
    envelope = direct.json()
    assert envelope["response_type"] == "error"
    assert envelope["data"]["error_id"] == "ERR_AWARD_NOT_FOUND"

    through_parent = api_client.list_milestones(UNKNOWN_AWARD, ADMIN)
    validate_error(through_parent, ApiErrorId.ERR_AWARD_NOT_FOUND, 404)
    assert through_parent.json()["response_type"] == "error"

    _, meta = validate_paginated(api_client.list_awards(ADMIN))
    assert meta["total_count"] == 0


def test_four_lifecycle_gates_fire_independently_before_any_award_exists():
    """A challenge against a programme that never opened, a determination on an
    applicant whose review was never begun, a cure return on a draft that was never
    submitted, and a second ingestion of an address already used in the same
    programme each report their own state rule — and the duplicate rule is scoped per
    programme, so the very same address lives happily in the other one.

    PRD 2.12: "8. **Priority 40 — program phase** → `ERR_PROGRAM_STATE_INVALID`.
    Location ingestion requires `DRAFT` or `CHALLENGE_OPEN`. Filing a challenge and
    appending challenge evidence require `CHALLENGE_OPEN`."
    PRD 2.12: "10. **Priority 42 — subgrantee state** →
    `ERR_SUBGRANTEE_STATE_INVALID`. Beginning a capability review requires
    `REGISTERED` or `REMEDIATION_REQUIRED`; recording a determination requires
    `UNDER_CAPABILITY_REVIEW`; submitting remediation requires
    `REMEDIATION_REQUIRED`. `DISQUALIFIED` is terminal."
    PRD 2.12: "11. **Priority 43 — application state** →
    `ERR_APPLICATION_STATE_INVALID`. Creating a location claim requires `DRAFT` or
    `RETURNED_FOR_CURE`; submitting requires `DRAFT` or `RETURNED_FOR_CURE`;
    returning for cure requires `SUBMITTED`; score-sheet creation requires
    `SUBMITTED` or `RESCORE_REQUIRED`; selection requires `SCORED`. `AWARDED` and
    `NOT_SELECTED` are terminal."
    PRD 3.1: "An `address_id` must be unique within a program; a repeat is refused
    with `ERR_DUPLICATE_LOCATION_ADDRESS`."

    Design: Corner/errors/errors_pre_award_state_family_rejected
    """
    open_program = create_program(name="BEAD Open Round")
    draft_program = create_program(name="BEAD Draft Round")
    shared_address = "ADDR-0001"
    in_open = ingest_location(open_program["id"], shared_address)
    in_draft = ingest_location(draft_program["id"], shared_address)

    set_clock("2026-08-10T00:00:00Z")
    open_challenge_window(open_program["id"])

    applicant = register_subgrantee(open_program["id"])
    assert applicant["capability_state"] == "REGISTERED"
    application = create_application(open_program["id"], applicant["id"])

    unopened_program = api_client.create_challenge(
        create_challenge_payload(
            draft_program["id"],
            in_draft["id"],
            asserted_classification="UNDERSERVED",
            rationale="Filed against a program that has not opened.",
        ),
        CHALLENGER,
    )
    validate_error(unopened_program, ApiErrorId.ERR_PROGRAM_STATE_INVALID, 409)

    unreviewed_applicant = api_client.record_capability_determination(
        applicant["id"], {"technical_raw_score": 30}, REVIEWER
    )
    validate_error(unreviewed_applicant, ApiErrorId.ERR_SUBGRANTEE_STATE_INVALID, 409)

    unsubmitted_application = api_client.return_application_for_cure(
        application["id"],
        {"cure_reason": "Returned before it was ever submitted."},
        SCORER,
    )
    validate_error(unsubmitted_application, ApiErrorId.ERR_APPLICATION_STATE_INVALID, 409)

    repeated_address = api_client.create_location(
        create_location_payload(open_program["id"], shared_address), ANALYST
    )
    validate_error(repeated_address, ApiErrorId.ERR_DUPLICATE_LOCATION_ADDRESS, 409)

    untouched_applicant = read_subgrantee(applicant["id"])
    assert untouched_applicant["capability_state"] == "REGISTERED"
    assert untouched_applicant["capability_index"] is None

    untouched_application = read_application(application["id"])
    assert untouched_application["application_state"] == "DRAFT"
    assert untouched_application["returned_for_cure_count"] == 0

    assert read_program(open_program["id"])["location_count_total"] == 1
    assert read_program(draft_program["id"])["location_count_total"] == 1
    assert read_location(in_open["id"])["address_id"] == shared_address
    assert read_location(in_draft["id"])["address_id"] == shared_address, (
        "The address is unique within a program, not across the whole system"
    )

    _, challenge_meta = validate_paginated(api_client.list_challenges(ADMIN))
    assert challenge_meta["total_count"] == 0


def test_the_three_submission_and_scoring_gates_are_separately_reachable():
    """One programme, one applicant and three drafts separate three refusals: a match
    under the floor with compliant speeds, a scoring attempt whose only claim sits on
    a served location so the final denominator is zero, and a perfectly valid draft
    that simply arrived after the application window ended.

    PRD 3.5: "Submitting outside the window is refused with
    `ERR_APPLICATION_WINDOW_CLOSED`; a speed commitment under those floors is refused
    with `ERR_SPEED_COMMITMENT_BELOW_MINIMUM`; a match under the program minimum is
    refused with `ERR_MATCH_BELOW_MINIMUM`."
    PRD 3.5: "The preliminary denominator can never be zero at submission because at
    least one claim is required to submit; the final figure stays null while the
    application is unsubmitted, and a final denominator of zero at scoring time is
    refused with `ERR_NO_ELIGIBLE_LOCATIONS`."
    PRD 2.12: "38. **Priority 83 — eligible denominator.** Score-sheet creation
    requires at least one location claim in `CLAIMED_ELIGIBLE`, so the final cost
    denominator is at least 1 → `ERR_NO_ELIGIBLE_LOCATIONS`."

    Design: Corner/errors/errors_application_gate_family_rejected
    """
    ctx = setup_challenge_open_program(("L3", "L1", "L5"))
    assert ctx["program"]["min_match_pct"] == 25.0
    assert ctx["locations"]["L1"]["classification_status"] == "SERVED"
    applicant = setup_qualified_subgrantee(ctx["program_id"])
    owner = make_subgrantee_headers(applicant["id"])

    thin_match = create_application(
        ctx["program_id"], applicant["id"], match_offer_pct=20.0
    )
    api_client.create_location_claim(
        {
            "application_id": thin_match["id"],
            "location_id": ctx["location_ids"]["L3"],
            "claimed_cost_cents": 400000,
        },
        owner,
    )

    served_only, served_claims = setup_submitted_application(
        ctx["program_id"], applicant["id"], [(ctx["location_ids"]["L1"], 500000)]
    )
    assert served_claims[0]["claim_state"] == "CLAIMED_INELIGIBLE"

    late = create_application(
        ctx["program_id"],
        applicant["id"],
        proposed_construction_start="2027-10-01T00:00:00Z",
        proposed_construction_end="2028-10-01T00:00:00Z",
    )
    api_client.create_location_claim(
        {
            "application_id": late["id"],
            "location_id": ctx["location_ids"]["L5"],
            "claimed_cost_cents": 600000,
        },
        owner,
    )

    below_floor = api_client.submit_application(thin_match["id"], owner)
    validate_error(below_floor, ApiErrorId.ERR_MATCH_BELOW_MINIMUM, 422)
    assert read_application(thin_match["id"])["application_state"] == "DRAFT"

    set_clock("2026-09-06T00:00:00Z")
    close_challenge_window(ctx["program_id"])

    too_late = api_client.submit_application(late["id"], owner)
    validate_error(too_late, ApiErrorId.ERR_APPLICATION_WINDOW_CLOSED, 409)
    assert read_application(late["id"])["application_state"] == "DRAFT", (
        "The half-open application window ended at 2026-09-05T00:00:00Z"
    )

    open_scoring(ctx["program_id"])
    empty_denominator = api_client.create_score_sheet(
        create_score_sheet_payload(
            served_only["id"], current_application_version(served_only["id"])
        ),
        SCORER,
    )
    validate_error(empty_denominator, ApiErrorId.ERR_NO_ELIGIBLE_LOCATIONS, 422)

    unscored = read_application(served_only["id"])
    assert unscored["application_state"] == "SUBMITTED"
    assert unscored["claim_count"] == 1
    assert unscored["confirmed_location_count"] == 0
    sheets, sheet_meta = validate_paginated(
        api_client.list_application_score_sheets(served_only["id"], ADMIN)
    )
    assert sheets == []
    assert sheet_meta["total_count"] == 0


def test_a_tied_record_cannot_be_sustained_and_exhausts_its_resubmissions():
    """A record whose rebuttal exactly ties it cannot be sustained, because the
    comparison is strict, but it is exactly the deficiency the complementary outcome
    describes; driving that outcome twice more exhausts the resubmission ceiling,
    while a second filing by the same party on the same location is duplicative
    throughout.

    PRD 3.2: "At most one non-terminal challenge may exist for a given pairing of
    contested location and filing identity, so a second live filing by the same party
    against the same location is refused with `ERR_DUPLICATE_CHALLENGE`."
    PRD 3.3: "A sustain attempted while the rebuttal ties or exceeds the challenge is
    refused with `ERR_REBUTTAL_PREVAILS`; a sustain attempted on a record below its
    standard is refused with `ERR_EVIDENCE_STANDARD_NOT_MET`."
    PRD 3.3: "It requires that `rebuttal_strength_score` be greater than or equal to
    `evidence_sufficiency_score` — the rebuttal has tied or prevailed, so the
    challenge record as filed is deficient rather than wrong."
    PRD 3.3: "It increments `resubmission_count`, resets `rebuttal_round` to 0,
    clears `rebuttal_deadline`, `triaged_by_user_id` and `outcome` back to null, and
    on the eligibility axis moves the location `AFFIRMED → CHALLENGED` — the same
    challenge re-entering review, so `challenge_count` is unchanged."
    PRD 3.3: "A resubmission attempted once `resubmission_count` has reached two is
    refused with `ERR_RESUBMISSION_LIMIT_REACHED`."

    Design: Corner/errors/errors_challenge_rebuttal_and_resubmission_family_rejected
    """
    ctx = setup_challenge_open_program(("L1",))
    contested = ctx["location_ids"]["L1"]
    assert ctx["locations"]["L1"]["reporting_provider_user_id"] == "prov-2"

    challenge = setup_community_challenge_meeting_standard(ctx["program_id"], contested)
    rebuttal_one = append_evidence(
        challenge["id"], "PROVIDER_ATTESTATION", "2026-06-15T00:00:00Z", PROVIDER
    )
    rebuttal_two = append_evidence(
        challenge["id"], "MAP_DATA_EXPORT", "2026-06-20T00:00:00Z", PROVIDER
    )
    assert rebuttal_one["submitter_side"] == "REBUTTAL"
    assert rebuttal_two["submitter_side"] == "REBUTTAL"

    tied = read_challenge(challenge["id"])
    assert tied["evidence_sufficiency_score"] == 45.00, "30.00 plus 15.00"
    assert tied["rebuttal_strength_score"] == 45.00, "35.00 plus 10.00"
    assert tied["required_sufficiency_threshold"] == 40.00

    duplicate = api_client.create_challenge(
        create_challenge_payload(
            ctx["program_id"],
            contested,
            rationale="Second filing by the same submitter on the same location.",
        ),
        CHALLENGER,
    )
    validate_error(duplicate, ApiErrorId.ERR_DUPLICATE_CHALLENGE, 409)

    for round_index in range(3):
        triaged = triage_challenge(challenge["id"])
        assert triaged["challenge_state"] == "REBUTTAL_OPEN"
        assert triaged["rebuttal_round"] == 1
        closed = close_rebuttal(challenge["id"])
        assert closed["challenge_state"] == "UNDER_REVIEW"
        assert closed["rebuttal_strength_score"] == 45.00

        if round_index == 0:
            prevails = api_client.determine_challenge(
                challenge["id"], {"outcome": "SUSTAINED"}, ANALYST_OTHER
            )
            validate_error(prevails, ApiErrorId.ERR_REBUTTAL_PREVAILS, 422)
            assert read_challenge(challenge["id"])["challenge_state"] == "UNDER_REVIEW"

        deficient = validate_success(
            api_client.determine_challenge(
                challenge["id"],
                {
                    "outcome": "DEFICIENT",
                    "determination_note": "Rebuttal ties the challenge record.",
                },
                ANALYST_OTHER,
            )
        )
        assert deficient["challenge_state"] == "DEFICIENT"
        assert deficient["outcome"] == "DEFICIENT"
        assert read_location(contested)["eligibility_state"] == "AFFIRMED"

        resubmitted = api_client.resubmit_challenge(
            challenge["id"], CHALLENGER, {"rationale": f"Corrected rationale {round_index}."}
        )
        if round_index < 2:
            revived = validate_success(resubmitted)
            assert revived["challenge_state"] == "SUBMITTED"
            assert revived["resubmission_count"] == round_index + 1
            assert revived["rebuttal_round"] == 0
            assert revived["rebuttal_deadline"] is None
            assert revived["triaged_by_user_id"] is None
            assert revived["outcome"] is None
            assert read_location(contested)["eligibility_state"] == "CHALLENGED"
        else:
            validate_error(
                resubmitted, ApiErrorId.ERR_RESUBMISSION_LIMIT_REACHED, 409
            )

    final = read_challenge(challenge["id"])
    assert final["challenge_state"] == "DEFICIENT"
    assert final["resubmission_count"] == 2
    assert final["rebuttal_round"] == 1

    location = read_location(contested)
    assert location["challenge_count"] == 1, (
        "The same challenge re-entering review does not raise the count"
    )
    assert location["classification_status"] == "SERVED", "Never reclassified"

    _, evidence_meta = validate_paginated(
        api_client.list_challenge_evidence(challenge["id"], ADMIN)
    )
    assert evidence_meta["total_count"] == 4
