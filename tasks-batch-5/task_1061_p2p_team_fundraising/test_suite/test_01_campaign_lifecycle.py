"""Opening, publishing and closing a campaign, and what its status gates."""

from test_helpers import (
    ApiErrorId,
    UNKNOWN_UUID,
    assert_campaign,
    create_campaign_payload,
    create_donation_payload,
    create_donor,
    create_draft_campaign,
    create_event,
    create_match_pool,
    create_organization,
    make_campaign_manager_headers,
    make_donor_headers,
    setup_published_campaign,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_new_campaign_lands_in_draft_with_zeroed_money_figures(api, anonymous_headers):
    """PRD §3.1: "A new campaign lands in `DRAFT` with `published_at` and `closed_at`
    both empty, with `receipt_seq` at 0, and with every computed money figure
    (`raised_credited_cents`, `lifetime_net_cents`, `reserved_payout_cents`,
    `paid_out_cents`, `available_balance_cents`, `donor_count`) at 0."
    PRD §2.4: "`version` is an integer that starts at 1 when the resource is created
    and increases by 1 on every mutation of that resource."

    Design: Corner/entities/campaign_creation_returns_201_with_draft_defaults
    """
    org = create_organization(api=api)
    cm_headers = make_campaign_manager_headers(org["id"])

    response = api.create_campaign(create_campaign_payload(org["id"]), cm_headers)

    campaign = validate_success(response, expected_status=201)
    assert_campaign(campaign)
    assert campaign["status"] == "DRAFT", f"Expected DRAFT, got {campaign['status']}"
    assert campaign["receipt_seq"] == 0
    assert campaign["raised_credited_cents"] == 0
    assert campaign["lifetime_net_cents"] == 0
    assert campaign["reserved_payout_cents"] == 0
    assert campaign["paid_out_cents"] == 0
    assert campaign["available_balance_cents"] == 0
    assert campaign["donor_count"] == 0
    assert campaign["version"] == 1


def test_campaign_fundraising_minimum_defaults_to_zero_when_omitted(api):
    """PRD §3.1: "When that minimum is not supplied it defaults to 0, which
    effectively disables the gate."

    Design: Corner/entities/campaign_creation_returns_201_with_draft_defaults
    """
    org = create_organization(api=api)
    cm_headers = make_campaign_manager_headers(org["id"])

    response = api.create_campaign(create_campaign_payload(org["id"]), cm_headers)

    campaign = validate_success(response, expected_status=201)
    assert campaign["fundraising_minimum_cents"] == 0


def test_campaign_list_reports_total_count_and_has_more(api, anonymous_headers):
    """PRD §2.3: "List responses carry `limit`, `offset`, `total_count` and `has_more`
    in the `meta` object, where `total_count` is the number of rows matching the
    filters before pagination is applied, and `has_more` states whether any matching
    rows remain beyond the current window."

    Design: Corner/entities/campaign_list_returns_pagination_envelope
    """
    org = create_organization(api=api)
    create_draft_campaign(org["id"], api=api, title="Campaign A")
    create_draft_campaign(org["id"], api=api, title="Campaign B", goal_amount_cents=500000)

    response = api.list_campaigns(
        anonymous_headers, params={"organization_id": org["id"], "limit": 1, "offset": 0}
    )

    rows, meta = validate_paginated(response)
    assert len(rows) == 1, f"Expected 1 row under limit=1, got {len(rows)}"
    assert meta["total_count"] == 2
    assert meta["has_more"] is True
    assert meta["limit"] == 1
    assert meta["offset"] == 0


def test_campaign_read_with_unknown_id_returns_campaign_not_found(api, anonymous_headers):
    """PRD §2.4: "Each resource type raises its own not-found code:
    `ERR_ORGANIZATION_NOT_FOUND`, `ERR_CAMPAIGN_NOT_FOUND`, `ERR_EVENT_NOT_FOUND`,
    `ERR_TEAM_NOT_FOUND`, `ERR_PARTICIPANT_NOT_FOUND`, `ERR_REGISTRATION_NOT_FOUND`,
    `ERR_DONOR_NOT_FOUND`, `ERR_DONATION_NOT_FOUND`, `ERR_MATCH_POOL_NOT_FOUND`,
    `ERR_TIER_NOT_FOUND`, `ERR_AWARD_NOT_FOUND`, `ERR_RECEIPT_NOT_FOUND` and
    `ERR_PAYOUT_NOT_FOUND`, each with HTTP 404."

    Design: Corner/entities/campaign_get_with_unknown_uuid_returns_not_found
    """
    create_organization(api=api)

    response = api.get_campaign(UNKNOWN_UUID, anonymous_headers)

    validate_error(response, ApiErrorId.ERR_CAMPAIGN_NOT_FOUND.value, expected_status=404)


def test_publishing_an_already_published_campaign_is_rejected(api):
    """PRD §3.1: "Attempting to publish a campaign that is not `DRAFT` is rejected
    with `ERR_INVALID_STATE`; attempting it as a manager of a different organization
    is rejected with `ERR_UNAUTHORIZED`."

    Design: Corner/state_machines/campaign_publish_twice_rejected_with_invalid_state
    """
    ctx = setup_published_campaign(api=api)

    response = api.publish_campaign(ctx["campaign_id"], ctx["cm_headers"])

    validate_error(response, ApiErrorId.ERR_INVALID_STATE.value, expected_status=409)
    campaign = validate_success(api.get_campaign(ctx["campaign_id"], ctx["cm_headers"]))
    assert campaign["status"] == "PUBLISHED"


def test_campaign_manager_of_another_organization_cannot_publish(api):
    """PRD §2.1: "When the acting role is not listed among an operation's authorized
    roles, or when an identity-bound role acts on a resource it does not own, the
    request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §3.1: "Attempting to publish a campaign that is not `DRAFT` is rejected with
    `ERR_INVALID_STATE`; attempting it as a manager of a different organization is
    rejected with `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/campaign_manager_cannot_publish_another_organizations_campaign
    """
    org_a = create_organization(api=api)
    org_b = create_organization(
        api=api, name="Lakeside Rescue", ein="98-7654321", contact_email="ops@lakeside.org"
    )
    campaign = create_draft_campaign(org_a["id"], api=api)

    response = api.publish_campaign(
        campaign["id"], make_campaign_manager_headers(org_b["id"])
    )

    validate_error(response, ApiErrorId.ERR_UNAUTHORIZED.value, expected_status=403)
    still_draft = validate_success(
        api.get_campaign(campaign["id"], make_campaign_manager_headers(org_a["id"]))
    )
    assert still_draft["status"] == "DRAFT"


def test_closing_a_campaign_cascades_its_events_and_pools_to_closed(api):
    """PRD §3.1: "**Cascade step 1:** every event of the campaign whose status is
    `OPEN` or `FULL` transitions to `CLOSED`; existing registrations keep whatever
    status they hold, but no new registration may be created against a closed event."
    PRD §3.1: "**Cascade step 2:** every sponsor match pool of the campaign whose
    status is `ACTIVE` or `EXHAUSTED` transitions to `CLOSED`."

    Design: Corner/state_machines/campaign_close_cascades_events_and_pools_to_closed
    """
    ctx = setup_published_campaign(api=api)
    event = create_event(ctx["campaign_id"], ctx["cm_headers"], api=api)
    pool = create_match_pool(ctx["campaign_id"], ctx["cm_headers"], api=api)

    campaign = validate_success(api.close_campaign(ctx["campaign_id"], ctx["cm_headers"]))

    assert campaign["status"] == "CLOSED"
    closed_event = validate_success(api.get_event(event["id"], ctx["cm_headers"]))
    assert closed_event["status"] == "CLOSED", "Cascade step 1 must close the event"
    closed_pool = validate_success(api.get_match_pool(pool["id"], ctx["cm_headers"]))
    assert closed_pool["status"] == "CLOSED", "Cascade step 2 must close the pool"


def test_gift_creation_is_rejected_while_the_campaign_is_still_draft(api):
    """PRD §2.7: "Attempting to create a donation, participant, team, event,
    registration, match pool or incentive tier under a campaign that is still `DRAFT`,
    or that has already moved to `CLOSED`, is rejected with
    `ERR_CAMPAIGN_NOT_PUBLISHED` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/donation_create_rejected_while_campaign_is_draft
    """
    org = create_organization(api=api)
    campaign = create_draft_campaign(org["id"], api=api)
    donor = create_donor(api=api)

    response = api.create_donation(
        create_donation_payload(
            campaign["id"], donor["id"], "CAMPAIGN", campaign["id"], 10000
        ),
        make_donor_headers(donor["id"]),
    )

    validate_error(
        response, ApiErrorId.ERR_CAMPAIGN_NOT_PUBLISHED.value, expected_status=409
    )
    draft = validate_success(
        api.get_campaign(campaign["id"], make_campaign_manager_headers(org["id"]))
    )
    assert draft["status"] == "DRAFT"


def test_the_same_gift_succeeds_once_the_campaign_is_published(api):
    """PRD §3.1: "Publication stamps `published_at` with the current logical-clock
    instant and is the event that opens the campaign to gifts, fundraiser pages,
    teams, events, registrations, sponsor pools and incentive tiers."
    PRD §3.4: "The stored `fee_cents` is the platform component plus the processing
    component plus a flat 30-cent processing charge; that sum is never re-rounded."

    Design: Difficulty/cross_entity_state_dependency/donation_create_rejected_while_campaign_is_draft
    """
    org = create_organization(api=api)
    campaign = create_draft_campaign(org["id"], api=api)
    donor = create_donor(api=api)
    cm_headers = make_campaign_manager_headers(org["id"])
    payload = create_donation_payload(
        campaign["id"], donor["id"], "CAMPAIGN", campaign["id"], 10000
    )
    donor_headers = make_donor_headers(donor["id"])
    rejected = api.create_donation(payload, donor_headers)
    validate_error(
        rejected, ApiErrorId.ERR_CAMPAIGN_NOT_PUBLISHED.value, expected_status=409
    )

    validate_success(api.publish_campaign(campaign["id"], cm_headers))
    response = api.create_donation(payload, donor_headers)

    gift = validate_success(response, expected_status=201)
    assert gift["payment_status"] == "PENDING"
    assert gift["fee_cents"] == 820, "500 platform + 290 processing + 30 flat"
