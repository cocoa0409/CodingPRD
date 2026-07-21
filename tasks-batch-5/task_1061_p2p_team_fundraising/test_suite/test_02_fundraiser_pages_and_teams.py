"""Fundraiser pages, the recruiting graph, teams and the withdrawal cascade."""

from test_helpers import (
    ApiErrorId,
    assert_participant,
    create_participant,
    create_participant_payload,
    create_team,
    setup_full_event_with_reservation,
    setup_published_campaign,
    setup_two_published_campaigns,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_creating_a_page_without_a_display_name_is_rejected(api, anonymous_headers):
    """PRD §2.8: "**Request shape** — required fields present, types correct, enum
    members recognized, and declared numeric ranges honored, otherwise
    `ERR_INVALID_REQUEST`."
    PRD §3.2: "The creation names the `campaign_id` and a public `display_name`, and
    may optionally name a `team_id` to join, a `recruited_by_participant_id` naming
    the fundraiser who brought them in, and a `personal_goal_cents` target which
    defaults to 10000 when omitted."

    Design: Corner/entities/participant_create_missing_required_display_name_returns_invalid_request
    """
    ctx = setup_published_campaign(api=api)

    response = api.create_participant({"campaign_id": ctx["campaign_id"]}, anonymous_headers)

    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value, expected_status=400)
    _rows, meta = validate_paginated(
        api.list_participants(anonymous_headers, params={"campaign_id": ctx["campaign_id"]})
    )
    assert meta["total_count"] == 0, "A rejected create must leave no row behind"


def test_page_defaults_personal_goal_and_opens_in_pending(api, anonymous_headers):
    """PRD §3.2: "A new page starts in `PENDING` with `credited_cents`,
    `projected_cents` and `recruit_count` at 0 and `minimum_met` false."
    PRD §3.2: "The creation names the `campaign_id` and a public `display_name`, and
    may optionally name a `team_id` to join, a `recruited_by_participant_id` naming
    the fundraiser who brought them in, and a `personal_goal_cents` target which
    defaults to 10000 when omitted."

    Design: Corner/entities/participant_personal_goal_default_applied_when_omitted
    """
    # PRD §2.11 also derives `minimum_met` as `credited_cents >=
    # fundraising_minimum_cents`. A campaign whose minimum is 0 (the §3.1 default)
    # makes the two sentences read differently for a brand-new page, so this
    # fixture uses a positive minimum, where both readings agree on false.
    ctx = setup_published_campaign(api=api, fundraising_minimum_cents=15000)

    response = api.create_participant(
        create_participant_payload(ctx["campaign_id"]), anonymous_headers
    )

    participant = validate_success(response, expected_status=201)
    assert_participant(participant)
    assert participant["personal_goal_cents"] == 10000
    assert participant["status"] == "PENDING"
    assert participant["credited_cents"] == 0
    assert participant["projected_cents"] == 0
    assert participant["recruit_count"] == 0
    assert participant["minimum_met"] is False


def test_naming_a_recruiter_raises_that_recruiters_recruit_count(api, anonymous_headers):
    """PRD §3.2: "When a team was named, that team's `member_count` rises by one; when
    a recruiter was named, the recruiter's `recruit_count` rises by one."
    PRD §2.11: "A participant's `recruit_count` is the number of participants naming
    them as recruiter whose own `status` is `PENDING` or `ACTIVE`."

    Design: Corner/entities/participant_self_referential_recruiter_increments_recruit_count
    """
    ctx = setup_published_campaign(api=api)
    recruiter = create_participant(ctx["campaign_id"], api=api, display_name="Alice Reyes")

    response = api.create_participant(
        create_participant_payload(
            ctx["campaign_id"],
            display_name="Ben Ortiz",
            recruited_by_participant_id=recruiter["id"],
        ),
        anonymous_headers,
    )

    recruit = validate_success(response, expected_status=201)
    assert recruit["recruited_by_participant_id"] == recruiter["id"]
    refreshed = validate_success(api.get_participant(recruiter["id"], anonymous_headers))
    assert refreshed["recruit_count"] == 1
    _rows, meta = validate_paginated(
        api.list_participants(
            anonymous_headers, params={"recruited_by_participant_id": recruiter["id"]}
        )
    )
    assert meta["total_count"] == 1


def test_recruiter_from_another_campaign_is_rejected(api, anonymous_headers):
    """PRD §3.2: "The named recruiter must belong to the same campaign, and must not
    be the page being created, or the request is rejected with `ERR_SELF_RECRUIT`."

    Design: Corner/validations/self_recruit_link_rejected
    """
    ctx = setup_two_published_campaigns(api=api)
    foreign = create_participant(ctx["campaign_b_id"], api=api, display_name="Bea Bravo")

    response = api.create_participant(
        create_participant_payload(
            ctx["campaign_a_id"], recruited_by_participant_id=foreign["id"]
        ),
        anonymous_headers,
    )

    validate_error(response, ApiErrorId.ERR_SELF_RECRUIT.value, expected_status=422)
    _rows, meta = validate_paginated(
        api.list_participants(
            anonymous_headers, params={"campaign_id": ctx["campaign_a_id"]}
        )
    )
    assert meta["total_count"] == 0


def test_joining_a_team_of_another_campaign_is_rejected(api, anonymous_headers):
    """PRD §3.2: "The named team must belong to the same campaign as the page, or the
    request is rejected with `ERR_TEAM_CAMPAIGN_MISMATCH`."

    Design: Corner/validations/participant_team_of_other_campaign_rejected
    """
    ctx = setup_two_published_campaigns(api=api)
    foreign_team = create_team(
        ctx["campaign_b_id"], ctx["cm_headers"], api=api, name="Team Bravo"
    )

    response = api.create_participant(
        create_participant_payload(ctx["campaign_a_id"], team_id=foreign_team["id"]),
        anonymous_headers,
    )

    validate_error(
        response, ApiErrorId.ERR_TEAM_CAMPAIGN_MISMATCH.value, expected_status=422
    )


def test_disbanding_a_team_detaches_its_members(api, anonymous_headers):
    """PRD §3.2: "Two effects follow: every fundraiser whose team reference points at
    the team has that reference cleared, so `member_count` becomes 0; and the team's
    `credited_cents` is recomputed to count **only** gifts designated directly at the
    team, since it now has no members to aggregate."

    Design: Corner/state_machines/team_disband_detaches_members_and_zeroes_member_count
    """
    ctx = setup_published_campaign(api=api)
    team = create_team(ctx["campaign_id"], ctx["cm_headers"], api=api)
    member = create_participant(
        ctx["campaign_id"], api=api, display_name="Pat Alpha", team_id=team["id"]
    )

    disbanded = validate_success(api.disband_team(team["id"], ctx["cm_headers"]))

    assert disbanded["status"] == "DISBANDED"
    assert disbanded["member_count"] == 0
    detached = validate_success(api.get_participant(member["id"], anonymous_headers))
    assert detached["team_id"] is None, "The team reference must be cleared"
    assert detached["status"] == "PENDING", "Disbanding does not withdraw the fundraiser"


def test_withdrawing_an_active_fundraiser_cancels_their_open_registration(api, anonymous_headers):
    """PRD §3.2: "**Cascade step 1:** every registration of that fundraiser sitting in
    `RESERVED` or `CONFIRMED` transitions to `CANCELLED`."
    PRD §3.2: "Withdrawal moves a page to `WITHDRAWN`, which is terminal, and is
    reachable from either `PENDING` or `ACTIVE`."

    Design: Difficulty/transitive_cascade/participant_withdraw_cancels_registration_and_reopens_full_event
    """
    ctx = setup_full_event_with_reservation(api=api, capacity=1)

    withdrawn = validate_success(
        api.withdraw_participant(ctx["participant_id"], ctx["participant_headers"])
    )

    assert withdrawn["status"] == "WITHDRAWN"
    registration = validate_success(
        api.get_registration(ctx["registration_id"], anonymous_headers)
    )
    assert registration["status"] == "CANCELLED", "Cascade step 1 must cancel the slot"


def test_withdrawal_cascade_reopens_the_event_it_emptied(api, anonymous_headers):
    """PRD §3.2: "**Cascade step 2:** each cancelled registration decreases its event's
    `registered_count` by 1. **Cascade step 3:** each event whose count has now dropped
    below its `capacity` and whose status was `FULL` transitions `FULL → OPEN`."

    Design: Difficulty/transitive_cascade/participant_withdraw_cancels_registration_and_reopens_full_event
    """
    ctx = setup_full_event_with_reservation(api=api, capacity=1)
    filled = validate_success(api.get_event(ctx["event_id"], anonymous_headers))
    assert filled["registered_count"] == 1 and filled["status"] == "FULL"

    validate_success(
        api.withdraw_participant(ctx["participant_id"], ctx["participant_headers"])
    )

    event = validate_success(api.get_event(ctx["event_id"], anonymous_headers))
    assert event["registered_count"] == 0, "Cascade step 2 must decrease the count"
    assert event["status"] == "OPEN", "Cascade step 3 must reopen the event"
