"""Authentication, role denial, server-minted identity and the not-found catalogue."""

from test_helpers import (
    ApiErrorId,
    UNKNOWN_UUID,
    assert_organization,
    create_donor,
    create_draft_campaign,
    create_event_payload,
    create_gift,
    create_organization,
    create_organization_payload,
    create_participant,
    make_campaign_manager_headers,
    make_participant_headers,
    make_platform_admin_headers,
    setup_published_campaign,
    validate_error,
    validate_success,
)

ADMIN = make_platform_admin_headers()


def test_a_request_without_identity_headers_is_unauthenticated(api):
    """PRD §2.1: "Every request to the service — including public reads — must carry
    two headers: `X-User-ID` and `X-User-Role`. If either header is absent, or if
    `X-User-Role` carries a value that is not one of the six declared roles, the
    request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/rbac/missing_role_header_returns_unauthenticated
    """
    org = create_organization(api=api)
    campaign = create_draft_campaign(org["id"], api=api)

    response = api._request("GET", f"/api/campaigns/{campaign['id']}", headers={})

    validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED.value, expected_status=401)


def test_a_fundraiser_may_not_settle_a_gift(api):
    """PRD §2.1: "When the acting role is not listed among an operation's authorized
    roles, or when an identity-bound role acts on a resource it does not own, the
    request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §3.6: "A platform operator resolves a pending gift by supplying an `outcome` of
    either `SETTLED` or `FAILED`."

    Design: Corner/rbac/participant_cannot_settle_donation_returns_unauthorized
    """
    ctx = setup_published_campaign(api=api)
    participant = create_participant(ctx["campaign_id"], api=api)
    donor = create_donor(api=api)
    gift = create_gift(
        ctx["campaign_id"], donor["id"], "PARTICIPANT", participant["id"], 10000, api=api
    )

    response = api.settle_donation(
        gift["id"], {"outcome": "SETTLED"}, make_participant_headers(participant["id"])
    )

    validate_error(response, ApiErrorId.ERR_UNAUTHORIZED.value, expected_status=403)
    unchanged = validate_success(api.get_donation(gift["id"], ctx["cm_headers"]))
    assert unchanged["payment_status"] == "PENDING"


def test_organization_identity_and_payout_state_are_server_minted(api):
    """PRD §2.4: "Every resource in this system carries a server-minted `id` that is a
    UUID string with no type prefix; clients never supply an `id`."
    PRD §3.1: "A newly registered organization begins with `payout_account_status` of
    `UNVERIFIED`, and only a platform operator may change it, supplying a `status` of
    either `VERIFIED` or `SUSPENDED`."

    Design: Corner/entities/organization_system_fields_generated_by_server
    """
    response = api.create_organization(create_organization_payload(), ADMIN)

    organization = validate_success(response, expected_status=201)
    assert_organization(organization)
    assert organization["payout_account_status"] == "UNVERIFIED"
    assert organization["version"] == 1


def test_creating_an_event_under_an_unknown_campaign_is_not_found(api):
    """PRD §2.4: "The same catalogue applies to identifiers supplied inside a request
    body: when a create names an `organization_id`, `campaign_id`, `event_id`,
    `team_id`, `participant_id`, `donor_id`, `recruited_by_participant_id`,
    `captain_participant_id` or `tier_id` that resolves to nothing, the corresponding
    not-found code is returned."

    Design: Corner/entities/event_create_with_unknown_campaign_id_returns_not_found
    """
    org = create_organization(api=api)

    response = api.create_event(
        create_event_payload(UNKNOWN_UUID, name="Ghost Run"),
        make_campaign_manager_headers(org["id"]),
    )

    validate_error(response, ApiErrorId.ERR_CAMPAIGN_NOT_FOUND.value, expected_status=404)


# ---- The not-found catalogue of PRD §2.4 --------------------------------

def test_organization_read_with_unknown_id_is_not_found(api):
    """PRD §2.4: "Each resource type raises its own not-found code:
    `ERR_ORGANIZATION_NOT_FOUND`, `ERR_CAMPAIGN_NOT_FOUND`, `ERR_EVENT_NOT_FOUND`,
    `ERR_TEAM_NOT_FOUND`, `ERR_PARTICIPANT_NOT_FOUND`, `ERR_REGISTRATION_NOT_FOUND`,
    `ERR_DONOR_NOT_FOUND`, `ERR_DONATION_NOT_FOUND`, `ERR_MATCH_POOL_NOT_FOUND`,
    `ERR_TIER_NOT_FOUND`, `ERR_AWARD_NOT_FOUND`, `ERR_RECEIPT_NOT_FOUND` and
    `ERR_PAYOUT_NOT_FOUND`, each with HTTP 404."

    Design: Corner/errors/organization_get_unknown_id_returns_not_found
    """
    response = api.get_organization(UNKNOWN_UUID, ADMIN)
    validate_error(
        response, ApiErrorId.ERR_ORGANIZATION_NOT_FOUND.value, expected_status=404
    )


def test_event_read_with_unknown_id_is_not_found(api, anonymous_headers):
    """PRD §2.4: "Each resource type raises its own not-found code:
    `ERR_ORGANIZATION_NOT_FOUND`, `ERR_CAMPAIGN_NOT_FOUND`, `ERR_EVENT_NOT_FOUND`,
    `ERR_TEAM_NOT_FOUND`, `ERR_PARTICIPANT_NOT_FOUND`, `ERR_REGISTRATION_NOT_FOUND`,
    `ERR_DONOR_NOT_FOUND`, `ERR_DONATION_NOT_FOUND`, `ERR_MATCH_POOL_NOT_FOUND`,
    `ERR_TIER_NOT_FOUND`, `ERR_AWARD_NOT_FOUND`, `ERR_RECEIPT_NOT_FOUND` and
    `ERR_PAYOUT_NOT_FOUND`, each with HTTP 404."

    Design: Corner/errors/event_get_unknown_id_returns_not_found
    """
    response = api.get_event(UNKNOWN_UUID, anonymous_headers)
    validate_error(response, ApiErrorId.ERR_EVENT_NOT_FOUND.value, expected_status=404)


def test_team_read_with_unknown_id_is_not_found(api, anonymous_headers):
    """PRD §2.4: "Each resource type raises its own not-found code:
    `ERR_ORGANIZATION_NOT_FOUND`, `ERR_CAMPAIGN_NOT_FOUND`, `ERR_EVENT_NOT_FOUND`,
    `ERR_TEAM_NOT_FOUND`, `ERR_PARTICIPANT_NOT_FOUND`, `ERR_REGISTRATION_NOT_FOUND`,
    `ERR_DONOR_NOT_FOUND`, `ERR_DONATION_NOT_FOUND`, `ERR_MATCH_POOL_NOT_FOUND`,
    `ERR_TIER_NOT_FOUND`, `ERR_AWARD_NOT_FOUND`, `ERR_RECEIPT_NOT_FOUND` and
    `ERR_PAYOUT_NOT_FOUND`, each with HTTP 404."

    Design: Corner/errors/team_get_unknown_id_returns_not_found
    """
    response = api.get_team(UNKNOWN_UUID, anonymous_headers)
    validate_error(response, ApiErrorId.ERR_TEAM_NOT_FOUND.value, expected_status=404)


def test_participant_read_with_unknown_id_is_not_found(api, anonymous_headers):
    """PRD §2.4: "Each resource type raises its own not-found code:
    `ERR_ORGANIZATION_NOT_FOUND`, `ERR_CAMPAIGN_NOT_FOUND`, `ERR_EVENT_NOT_FOUND`,
    `ERR_TEAM_NOT_FOUND`, `ERR_PARTICIPANT_NOT_FOUND`, `ERR_REGISTRATION_NOT_FOUND`,
    `ERR_DONOR_NOT_FOUND`, `ERR_DONATION_NOT_FOUND`, `ERR_MATCH_POOL_NOT_FOUND`,
    `ERR_TIER_NOT_FOUND`, `ERR_AWARD_NOT_FOUND`, `ERR_RECEIPT_NOT_FOUND` and
    `ERR_PAYOUT_NOT_FOUND`, each with HTTP 404."

    Design: Corner/errors/participant_get_unknown_id_returns_not_found
    """
    response = api.get_participant(UNKNOWN_UUID, anonymous_headers)
    validate_error(
        response, ApiErrorId.ERR_PARTICIPANT_NOT_FOUND.value, expected_status=404
    )


def test_registration_read_with_unknown_id_is_not_found(api, anonymous_headers):
    """PRD §2.4: "Each resource type raises its own not-found code:
    `ERR_ORGANIZATION_NOT_FOUND`, `ERR_CAMPAIGN_NOT_FOUND`, `ERR_EVENT_NOT_FOUND`,
    `ERR_TEAM_NOT_FOUND`, `ERR_PARTICIPANT_NOT_FOUND`, `ERR_REGISTRATION_NOT_FOUND`,
    `ERR_DONOR_NOT_FOUND`, `ERR_DONATION_NOT_FOUND`, `ERR_MATCH_POOL_NOT_FOUND`,
    `ERR_TIER_NOT_FOUND`, `ERR_AWARD_NOT_FOUND`, `ERR_RECEIPT_NOT_FOUND` and
    `ERR_PAYOUT_NOT_FOUND`, each with HTTP 404."

    Design: Corner/errors/registration_get_unknown_id_returns_not_found
    """
    response = api.get_registration(UNKNOWN_UUID, anonymous_headers)
    validate_error(
        response, ApiErrorId.ERR_REGISTRATION_NOT_FOUND.value, expected_status=404
    )


def test_donor_read_with_unknown_id_is_not_found(api):
    """PRD §2.4: "Each resource type raises its own not-found code:
    `ERR_ORGANIZATION_NOT_FOUND`, `ERR_CAMPAIGN_NOT_FOUND`, `ERR_EVENT_NOT_FOUND`,
    `ERR_TEAM_NOT_FOUND`, `ERR_PARTICIPANT_NOT_FOUND`, `ERR_REGISTRATION_NOT_FOUND`,
    `ERR_DONOR_NOT_FOUND`, `ERR_DONATION_NOT_FOUND`, `ERR_MATCH_POOL_NOT_FOUND`,
    `ERR_TIER_NOT_FOUND`, `ERR_AWARD_NOT_FOUND`, `ERR_RECEIPT_NOT_FOUND` and
    `ERR_PAYOUT_NOT_FOUND`, each with HTTP 404."

    Design: Corner/errors/donor_get_unknown_id_returns_not_found
    """
    response = api.get_donor(UNKNOWN_UUID, ADMIN)
    validate_error(response, ApiErrorId.ERR_DONOR_NOT_FOUND.value, expected_status=404)


def test_donation_read_with_unknown_id_is_not_found(api, anonymous_headers):
    """PRD §2.4: "Each resource type raises its own not-found code:
    `ERR_ORGANIZATION_NOT_FOUND`, `ERR_CAMPAIGN_NOT_FOUND`, `ERR_EVENT_NOT_FOUND`,
    `ERR_TEAM_NOT_FOUND`, `ERR_PARTICIPANT_NOT_FOUND`, `ERR_REGISTRATION_NOT_FOUND`,
    `ERR_DONOR_NOT_FOUND`, `ERR_DONATION_NOT_FOUND`, `ERR_MATCH_POOL_NOT_FOUND`,
    `ERR_TIER_NOT_FOUND`, `ERR_AWARD_NOT_FOUND`, `ERR_RECEIPT_NOT_FOUND` and
    `ERR_PAYOUT_NOT_FOUND`, each with HTTP 404."

    Design: Corner/errors/donation_get_unknown_id_returns_not_found
    """
    response = api.get_donation(UNKNOWN_UUID, anonymous_headers)
    validate_error(response, ApiErrorId.ERR_DONATION_NOT_FOUND.value, expected_status=404)


def test_match_pool_read_with_unknown_id_is_not_found(api, anonymous_headers):
    """PRD §2.4: "Each resource type raises its own not-found code:
    `ERR_ORGANIZATION_NOT_FOUND`, `ERR_CAMPAIGN_NOT_FOUND`, `ERR_EVENT_NOT_FOUND`,
    `ERR_TEAM_NOT_FOUND`, `ERR_PARTICIPANT_NOT_FOUND`, `ERR_REGISTRATION_NOT_FOUND`,
    `ERR_DONOR_NOT_FOUND`, `ERR_DONATION_NOT_FOUND`, `ERR_MATCH_POOL_NOT_FOUND`,
    `ERR_TIER_NOT_FOUND`, `ERR_AWARD_NOT_FOUND`, `ERR_RECEIPT_NOT_FOUND` and
    `ERR_PAYOUT_NOT_FOUND`, each with HTTP 404."

    Design: Corner/errors/match_pool_get_unknown_id_returns_not_found
    """
    response = api.get_match_pool(UNKNOWN_UUID, anonymous_headers)
    validate_error(
        response, ApiErrorId.ERR_MATCH_POOL_NOT_FOUND.value, expected_status=404
    )


def test_incentive_tier_read_with_unknown_id_is_not_found(api, anonymous_headers):
    """PRD §2.4: "Each resource type raises its own not-found code:
    `ERR_ORGANIZATION_NOT_FOUND`, `ERR_CAMPAIGN_NOT_FOUND`, `ERR_EVENT_NOT_FOUND`,
    `ERR_TEAM_NOT_FOUND`, `ERR_PARTICIPANT_NOT_FOUND`, `ERR_REGISTRATION_NOT_FOUND`,
    `ERR_DONOR_NOT_FOUND`, `ERR_DONATION_NOT_FOUND`, `ERR_MATCH_POOL_NOT_FOUND`,
    `ERR_TIER_NOT_FOUND`, `ERR_AWARD_NOT_FOUND`, `ERR_RECEIPT_NOT_FOUND` and
    `ERR_PAYOUT_NOT_FOUND`, each with HTTP 404."

    Design: Corner/errors/incentive_tier_get_unknown_id_returns_not_found
    """
    response = api.get_incentive_tier(UNKNOWN_UUID, anonymous_headers)
    validate_error(response, ApiErrorId.ERR_TIER_NOT_FOUND.value, expected_status=404)


def test_incentive_award_read_with_unknown_id_is_not_found(api, anonymous_headers):
    """PRD §2.4: "Each resource type raises its own not-found code:
    `ERR_ORGANIZATION_NOT_FOUND`, `ERR_CAMPAIGN_NOT_FOUND`, `ERR_EVENT_NOT_FOUND`,
    `ERR_TEAM_NOT_FOUND`, `ERR_PARTICIPANT_NOT_FOUND`, `ERR_REGISTRATION_NOT_FOUND`,
    `ERR_DONOR_NOT_FOUND`, `ERR_DONATION_NOT_FOUND`, `ERR_MATCH_POOL_NOT_FOUND`,
    `ERR_TIER_NOT_FOUND`, `ERR_AWARD_NOT_FOUND`, `ERR_RECEIPT_NOT_FOUND` and
    `ERR_PAYOUT_NOT_FOUND`, each with HTTP 404."

    Design: Corner/errors/incentive_award_get_unknown_id_returns_not_found
    """
    response = api.get_incentive_award(UNKNOWN_UUID, anonymous_headers)
    validate_error(response, ApiErrorId.ERR_AWARD_NOT_FOUND.value, expected_status=404)


def test_receipt_read_with_unknown_id_is_not_found(api, anonymous_headers):
    """PRD §2.4: "Each resource type raises its own not-found code:
    `ERR_ORGANIZATION_NOT_FOUND`, `ERR_CAMPAIGN_NOT_FOUND`, `ERR_EVENT_NOT_FOUND`,
    `ERR_TEAM_NOT_FOUND`, `ERR_PARTICIPANT_NOT_FOUND`, `ERR_REGISTRATION_NOT_FOUND`,
    `ERR_DONOR_NOT_FOUND`, `ERR_DONATION_NOT_FOUND`, `ERR_MATCH_POOL_NOT_FOUND`,
    `ERR_TIER_NOT_FOUND`, `ERR_AWARD_NOT_FOUND`, `ERR_RECEIPT_NOT_FOUND` and
    `ERR_PAYOUT_NOT_FOUND`, each with HTTP 404."

    Design: Corner/errors/receipt_get_unknown_id_returns_not_found
    """
    response = api.get_receipt(UNKNOWN_UUID, anonymous_headers)
    validate_error(response, ApiErrorId.ERR_RECEIPT_NOT_FOUND.value, expected_status=404)


def test_payout_read_with_unknown_id_is_not_found(api):
    """PRD §2.4: "Each resource type raises its own not-found code:
    `ERR_ORGANIZATION_NOT_FOUND`, `ERR_CAMPAIGN_NOT_FOUND`, `ERR_EVENT_NOT_FOUND`,
    `ERR_TEAM_NOT_FOUND`, `ERR_PARTICIPANT_NOT_FOUND`, `ERR_REGISTRATION_NOT_FOUND`,
    `ERR_DONOR_NOT_FOUND`, `ERR_DONATION_NOT_FOUND`, `ERR_MATCH_POOL_NOT_FOUND`,
    `ERR_TIER_NOT_FOUND`, `ERR_AWARD_NOT_FOUND`, `ERR_RECEIPT_NOT_FOUND` and
    `ERR_PAYOUT_NOT_FOUND`, each with HTTP 404."

    Design: Corner/errors/payout_get_unknown_id_returns_not_found
    """
    response = api.get_payout(UNKNOWN_UUID, ADMIN)
    validate_error(response, ApiErrorId.ERR_PAYOUT_NOT_FOUND.value, expected_status=404)
