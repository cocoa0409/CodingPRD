"""Where authority stops: role-exclusive writes, segregation of duties on the committee,
the leader's own group, the admin's non-override, and the approval chain."""

from test_helpers import (
    ApiErrorId,
    CHAIR_USER_ID,
    MEMBER_1_USER_ID,
    MEMBER_2_USER_ID,
    MEMBER_3_USER_ID,
    NOT_FOUND_ERROR_IDS,
    PEER_CHAIR_USER_ID,
    SPONSOR_USER_ID,
    TEST_USERS,
    api_client,
    assert_instant_equals,
    assert_money_equals,
    cast_vote_payload,
    clear_conflict_check_payload,
    create_conflict_check_payload,
    create_integration_plan_payload,
    create_introduction_payload,
    create_offer_payload,
    freeze_practice_group_payload,
    add_second_practice_group,
    make_committee_chair_headers,
    make_committee_member_headers,
    make_practice_group_leader_headers,
    open_conflict_check,
    read_candidate,
    read_client_book_entry,
    read_conflict_check,
    read_integration_plan,
    read_offer,
    read_practice_group,
    read_questionnaire,
    setup_assessed_candidate,
    setup_drafted_offer,
    setup_hired_candidate,
    setup_offer_in_committee_review,
    setup_submitted_questionnaire,
    submit_offer_payload,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["system_admin_headers"]
COORDINATOR = TEST_USERS["recruiting_coordinator_headers"]
COUNSEL = TEST_USERS["conflicts_counsel_headers"]
CHAIR = make_committee_chair_headers(CHAIR_USER_ID)
PEER_CHAIR = make_committee_chair_headers(PEER_CHAIR_USER_ID)

PROBE_UUID = "00000000-0000-4000-8000-000000000000"


def test_each_role_exclusive_write_refuses_every_other_declared_role():
    """**Authorization** — `X-User-Role` listed among the target endpoint's roles. Failure:
    `ERR_UNAUTHORIZED` (403). Applies to every endpoint.
    Checks are evaluated in the ascending order below and the **first** failure wins; no later
    check can mask an earlier one, and no earlier check may be skipped because a later one would
    also fail.

    Design: Corner/rbac/role_exclusive_writes_are_rejected_for_every_other_role
    """
    ctx = setup_submitted_questionnaire("SLIM")
    candidate_id = ctx["candidate"]["id"]
    questionnaire_id = ctx["questionnaire"]["id"]
    entry_id = ctx["entries"]["Northwind Holdings"]["id"]
    group_id = ctx["practice_group"]["id"]

    refusals = [
        api_client.approach_candidate(candidate_id, CHAIR),
        api_client.create_conflict_check(
            entry_id, create_conflict_check_payload(), COORDINATOR
        ),
        api_client.start_review_questionnaire(questionnaire_id, COUNSEL),
        api_client.create_offer(
            candidate_id,
            create_offer_payload(
                PROBE_UUID,
                ctx["candidate"]["version"],
                guaranteed_comp_usd=400000.00,
                signing_bonus_usd=40000.00,
            ),
            COUNSEL,
        ),
        api_client.freeze_practice_group(
            group_id,
            freeze_practice_group_payload(reason="Chair attempting an admin-only freeze."),
            CHAIR,
        ),
        api_client.delete_client_book_entry(entry_id, COORDINATOR),
        api_client.submit_questionnaire(questionnaire_id, COORDINATOR),
    ]

    for response in refusals:
        error = validate_error(response, ApiErrorId.ERR_UNAUTHORIZED.value, 403)
        assert error["error_id"] != ApiErrorId.ERR_UNAUTHENTICATED.value
        assert error["error_id"] not in NOT_FOUND_ERROR_IDS

    under_review = validate_success(
        api_client.start_review_questionnaire(questionnaire_id, COORDINATOR)
    )
    assert under_review["status"] == "UNDER_REVIEW"
    assert under_review["entry_count"] == 1

    assert read_client_book_entry(entry_id)["status"] == "ACTIVE"

    candidate = read_candidate(candidate_id)
    assert candidate["pipeline_status"] == "DILIGENCE"
    assert candidate["clearance_status"] == "NOT_STARTED"
    assert read_practice_group(group_id)["status"] == "OPEN"


def test_the_sponsor_cannot_vote_and_the_drafting_chair_cannot_close_the_tally():
    """The acting user must not be the candidate's `sponsor_user_id`
    (`ERR_SPONSOR_CANNOT_VOTE`), must not already hold an `ACTIVE` vote on this offer
    (`ERR_DUPLICATE_VOTE`), and the offer's `active_vote_count` must be strictly below its
    `eligible_voter_count` (`ERR_VOTE_ROLL_FULL`).
    **Closing the tally.** Finalization is the three-way fork, and the chair who drafted the
    offer may not perform it (`ERR_OFFER_CREATOR_CANNOT_FINALIZE`).

    Design: Corner/rbac/drafting_voting_and_finalizing_are_separated_across_users
    """
    ctx = setup_offer_in_committee_review("SLIM", eligible_voter_count=3)
    offer_id = ctx["offer"]["id"]

    sponsor_ballot = api_client.cast_vote(
        offer_id,
        cast_vote_payload(round_number=1),
        make_committee_member_headers(SPONSOR_USER_ID),
    )
    validate_error(sponsor_ballot, ApiErrorId.ERR_SPONSOR_CANNOT_VOTE.value)

    validate_success(
        api_client.cast_vote(
            offer_id,
            cast_vote_payload(round_number=1, rationale="My own model still clears."),
            CHAIR,
        ),
        expected_status=201,
    )
    validate_success(
        api_client.cast_vote(
            offer_id,
            cast_vote_payload(round_number=1),
            make_committee_member_headers(MEMBER_1_USER_ID),
        ),
        expected_status=201,
    )

    own_finalize = api_client.finalize_offer(offer_id, CHAIR)
    validate_error(own_finalize, ApiErrorId.ERR_OFFER_CREATOR_CANNOT_FINALIZE.value)
    assert read_offer(offer_id)["status"] == "COMMITTEE_REVIEW"

    approved = validate_success(api_client.finalize_offer(offer_id, PEER_CHAIR))
    assert approved["status"] == "APPROVED"
    assert approved["votes_cast_total"] == 2
    assert approved["active_vote_count"] == 2
    assert approved["eligible_voter_count"] == 3
    assert approved["created_by_user_id"] == CHAIR_USER_ID

    candidate = read_candidate(ctx["candidate"]["id"])
    assert candidate["pipeline_status"] == "OFFER_OUT"
    assert candidate["open_offer_id"] == offer_id

    assert_money_equals(
        read_practice_group(ctx["practice_group"]["id"])["reserved_guarantee_budget_usd"],
        500000.00,
        "reserved_guarantee_budget_usd",
    )


def test_a_leader_from_another_group_owns_none_of_the_onboarding_chain():
    """The acting leader's `X-User-ID` must equal the candidate's `target_practice_group_id`,
    and the submitted `practice_group_id` must equal it too — a group may not draft a plan for a
    lateral it was not assigned.
    **Resource ownership** for the entity-backed roles, as described in §2.1. Failure:
    `ERR_NOT_RESOURCE_OWNER` (403). Applies to nine endpoints:
    `POST /lateral-hiring/questionnaires/{questionnaire_id}/client-book-entries`,
    `DELETE /lateral-hiring/client-book-entries/{entry_id}`,
    `POST /lateral-hiring/questionnaires/{questionnaire_id}/submit`,
    `POST /lateral-hiring/offers/{offer_id}/accept`,
    `POST /lateral-hiring/candidates/{candidate_id}/integration-plans`,
    `POST /lateral-hiring/integration-plans/{plan_id}/activate`,
    `POST /lateral-hiring/integration-plans/{plan_id}/introductions`,
    `POST /lateral-hiring/introductions/{introduction_id}/complete`, and
    `POST /lateral-hiring/candidates/{candidate_id}/performance-reviews`.

    Design: Corner/rbac/practice_group_leader_authority_is_scoped_to_their_own_group
    """
    ctx = setup_hired_candidate("SLIM")
    group_id = ctx["practice_group"]["id"]
    foreign_group = add_second_practice_group(ctx)
    foreign_headers = ctx["foreign_leader_headers"]

    seen = []

    foreign_plan = api_client.create_integration_plan(
        ctx["candidate"]["id"],
        create_integration_plan_payload(group_id, ctx["offer"]["id"]),
        foreign_headers,
    )
    seen.append(validate_error(foreign_plan, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value, 403))

    plan = validate_success(
        api_client.create_integration_plan(
            ctx["candidate"]["id"],
            create_integration_plan_payload(group_id, ctx["offer"]["id"]),
            ctx["leader_headers"],
        ),
        expected_status=201,
    )

    foreign_activate = api_client.activate_integration_plan(plan["id"], foreign_headers)
    seen.append(
        validate_error(foreign_activate, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value, 403)
    )

    activated = validate_success(
        api_client.activate_integration_plan(plan["id"], ctx["leader_headers"])
    )
    assert activated["status"] == "ACTIVE"

    foreign_slot = api_client.create_introduction(
        plan["id"], create_introduction_payload(), foreign_headers
    )
    seen.append(validate_error(foreign_slot, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value, 403))

    introduction = validate_success(
        api_client.create_introduction(
            plan["id"], create_introduction_payload(), ctx["leader_headers"]
        ),
        expected_status=201,
    )
    assert introduction["status"] == "PROPOSED"

    for error in seen:
        assert error["error_id"] != ApiErrorId.ERR_INTEGRATION_PLAN_NOT_FOUND.value

    fresh_plan = read_integration_plan(plan["id"])
    assert fresh_plan["status"] == "ACTIVE"
    assert fresh_plan["practice_group_id"] == group_id
    assert fresh_plan["introduction_count"] == 1

    assert read_practice_group(group_id)["active_onboarding_count"] == 1

    foreign = read_practice_group(foreign_group["id"])
    assert foreign["active_onboarding_count"] == 0
    assert foreign["status"] == "OPEN"


def test_the_operator_role_may_freeze_a_group_but_may_not_take_anyone_elses_write():
    """A `SystemAdmin` is the firm's systems operator: it seeds practice groups and search
    firms, ingests collection data from the accounting system, and drives the logical clock.
    **Authorization** — `X-User-Role` listed among the target endpoint's roles. Failure:
    `ERR_UNAUTHORIZED` (403). Applies to every endpoint.

    Design: Corner/rbac/system_admin_cannot_override_role_exclusive_writes
    """
    ctx = setup_assessed_candidate("SLIM")
    check = open_conflict_check(ctx, "Northwind Holdings")
    entry_id = ctx["entries"]["Northwind Holdings"]["id"]
    questionnaire_id = ctx["questionnaire"]["id"]
    group_id = ctx["practice_group"]["id"]
    assert read_candidate(ctx["candidate"]["id"])["clearance_status"] == "IN_PROGRESS"

    overreach = [
        api_client.clear_conflict_check(
            check["id"],
            clear_conflict_check_payload(
                resolution_note="Admin closing the conflicts file."
            ),
            ADMIN,
        ),
        api_client.create_offer(
            ctx["candidate"]["id"],
            create_offer_payload(
                ctx["assessment"]["id"],
                read_candidate(ctx["candidate"]["id"])["version"],
                guaranteed_comp_usd=400000.00,
                signing_bonus_usd=40000.00,
            ),
            ADMIN,
        ),
        api_client.submit_questionnaire(questionnaire_id, ADMIN),
        api_client.delete_client_book_entry(entry_id, ADMIN),
    ]
    for response in overreach:
        validate_error(response, ApiErrorId.ERR_UNAUTHORIZED.value, 403)

    assert read_conflict_check(check["id"])["status"] == "PENDING"

    frozen = validate_success(
        api_client.freeze_practice_group(
            group_id,
            freeze_practice_group_payload(
                reason="Admin freezing new onboarding, which IS an admin power."
            ),
            ADMIN,
        )
    )
    assert frozen["status"] == "HIRING_FROZEN"

    cleared = validate_success(
        api_client.clear_conflict_check(
            check["id"], clear_conflict_check_payload(), COUNSEL
        )
    )
    assert cleared["status"] == "CLEAR"

    assert read_practice_group(group_id)["status"] == "HIRING_FROZEN"
    assert read_candidate(ctx["candidate"]["id"])["clearance_status"] == "CLEARED"
    assert read_client_book_entry(entry_id)["status"] == "ACTIVE"
    assert read_questionnaire(questionnaire_id)["status"] == "UNDER_REVIEW"


def test_every_rung_of_the_approval_chain_admits_exactly_one_role():
    """A `CommitteeChair` models and submits compensation offers, may vote, and finalizes the
    tally — but never on an offer they themselves drafted. A `CommitteeMember` reads the
    diligence package and votes, and cannot draft, submit, or finalize anything.
    A `Candidate` is the lateral partner under consideration, who fills in the questionnaire,
    discloses and withdraws client book entries, submits the questionnaire, and accepts the
    offer.

    Design: Corner/rbac/offer_approval_chain_steps_are_rejected_for_out_of_role_actors
    """
    ctx = setup_drafted_offer("SLIM")
    offer_id = ctx["offer"]["id"]
    group_id = ctx["practice_group"]["id"]

    member_submit = api_client.submit_offer(
        offer_id,
        submit_offer_payload(),
        make_committee_member_headers(MEMBER_1_USER_ID),
    )
    validate_error(member_submit, ApiErrorId.ERR_UNAUTHORIZED.value, 403)

    submitted = validate_success(
        api_client.submit_offer(offer_id, submit_offer_payload(), CHAIR)
    )
    assert submitted["status"] == "COMMITTEE_REVIEW"

    leader_ballot = api_client.cast_vote(
        offer_id,
        cast_vote_payload(round_number=1),
        make_practice_group_leader_headers(group_id),
    )
    validate_error(leader_ballot, ApiErrorId.ERR_UNAUTHORIZED.value, 403)

    for voter in (MEMBER_1_USER_ID, MEMBER_2_USER_ID):
        validate_success(
            api_client.cast_vote(
                offer_id,
                cast_vote_payload(round_number=1),
                make_committee_member_headers(voter),
            ),
            expected_status=201,
        )

    member_finalize = api_client.finalize_offer(
        offer_id, make_committee_member_headers(MEMBER_3_USER_ID)
    )
    validate_error(member_finalize, ApiErrorId.ERR_UNAUTHORIZED.value, 403)

    approved = validate_success(api_client.finalize_offer(offer_id, PEER_CHAIR))
    assert approved["status"] == "APPROVED"

    chair_accept = api_client.accept_offer(offer_id, PEER_CHAIR)
    validate_error(chair_accept, ApiErrorId.ERR_UNAUTHORIZED.value, 403)

    accepted = validate_success(
        api_client.accept_offer(offer_id, ctx["candidate_headers"])
    )
    assert accepted["status"] == "ACCEPTED"
    assert_instant_equals(
        accepted["accepted_at"], "2026-08-01T00:00:00.000Z", "accepted_at"
    )
    assert accepted["votes_cast_total"] == 2

    candidate = read_candidate(ctx["candidate"]["id"])
    assert candidate["pipeline_status"] == "HIRED"
    assert_instant_equals(
        candidate["hire_date"], "2026-08-01T00:00:00.000Z", "hire_date"
    )
    assert_instant_equals(
        candidate["earliest_start_date"],
        "2026-09-15T00:00:00.000Z",
        "earliest_start_date",
    )

    engagement = validate_success(
        api_client.get_search_firm_engagement(ctx["engagement"]["id"], COORDINATOR)
    )
    assert engagement["fee_status"] == "FEE_DUE"
    assert_money_equals(engagement["fee_amount_usd"], 137500.00, "fee_amount_usd")

    group = read_practice_group(group_id)
    assert_money_equals(
        group["committed_guarantee_total_usd"], 500000.00, "committed_guarantee_total_usd"
    )
    assert_money_equals(
        group["reserved_guarantee_budget_usd"], 0.00, "reserved_guarantee_budget_usd"
    )
