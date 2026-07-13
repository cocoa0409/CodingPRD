"""Corner: validations — single-failure scenarios for the domain constraint errors."""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    setup_actor_trio,
    setup_published_campaign,
    register_organizer,
    register_beneficiary,
    register_donor,
    create_draft_campaign,
    create_team_member_payload,
    create_campaign_payload,
    create_feature_placement_payload,
    create_donation_payload,
    make_organizer_headers,
    make_beneficiary_headers,
    make_donor_headers,
    TEST_USERS,
)

ADMIN = TEST_USERS["admin_headers"]


def test_team_member_duplicate_returns_conflict(api):
    """PRD §3.3: "A given organizer may hold at most one ACTIVE membership on a given
    campaign; a second ACTIVE membership for the same organizer on the same campaign is
    rejected with ERR_DUPLICATE_TEAM_MEMBER."

    Design: Corner/validations/team_member_duplicate_returns_conflict
    """
    org1 = register_organizer(api, email="o1@x.com")
    org2 = register_organizer(api, email="o2@x.com")
    ben = register_beneficiary(api)
    camp = create_draft_campaign(api, org1["id"], ben["id"])
    validate_success(
        api.create_team_member(
            create_team_member_payload(camp["id"], org2["id"], "CO_ORGANIZER"),
            make_organizer_headers(org1["id"])),
        201,
    )
    resp = api.create_team_member(
        create_team_member_payload(camp["id"], org2["id"], "CO_ORGANIZER"),
        make_organizer_headers(org1["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_TEAM_MEMBER, 409)


def test_placement_window_invalid_returns_422(api):
    """PRD §3.8: "The window end must be strictly after the window start, otherwise
    ERR_WINDOW_INVALID."

    Design: Corner/validations/placement_window_invalid_returns_422
    """
    org, ben, _ = setup_actor_trio(api)
    camp = create_draft_campaign(api, org["id"], ben["id"])
    resp = api.create_feature_placement(
        create_feature_placement_payload(
            camp["id"], window_start="2026-04-08T00:00:00Z", window_end="2026-04-01T00:00:00Z"),
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_WINDOW_INVALID, 422)


def test_campaign_goal_zero_returns_422(api):
    """PRD §3.2: "The goal must be strictly greater than zero, otherwise the creation is
    rejected with ERR_GOAL_INVALID."

    Design: Corner/validations/campaign_goal_zero_returns_422
    """
    org, ben, _ = setup_actor_trio(api)
    resp = api.create_campaign(
        create_campaign_payload(ben["id"], goal_cents=0), make_organizer_headers(org["id"])
    )
    validate_error(resp, ApiErrorId.ERR_GOAL_INVALID, 422)


def test_submit_verification_without_stripe_returns_conflict(api):
    """PRD §3.1: "Submitting for review moves an UNVERIFIED or REJECTED beneficiary to
    PENDING; this is available only once a payout account is connected, and attempting it
    while stripe_account_ref is still null is rejected with ERR_WITHDRAWAL_NOT_READY."

    Design: Corner/validations/submit_verification_without_stripe_returns_conflict
    """
    ben = register_beneficiary(api)  # no withdrawal-setup -> stripe_account_ref null
    resp = api.submit_verification(ben["id"], make_beneficiary_headers(ben["id"]))
    validate_error(resp, ApiErrorId.ERR_WITHDRAWAL_NOT_READY, 409)


def test_donation_donor_mismatch_returns_forbidden(api):
    """PRD §3.4: "A donor gifts to a campaign by supplying the campaign_id, their own
    donor_id (which must equal the acting donor's X-User-ID, otherwise ERR_DONOR_MISMATCH),
    an amount_cents gift that goes to the campaign, an optional tip_cents platform tip that
    goes to the platform rather than the campaign (defaulting to zero when omitted), and an
    optional is_anonymous flag; when is_anonymous is omitted it falls back to the donor's
    is_anonymous_default."

    Design: Corner/validations/donation_donor_mismatch_returns_forbidden
    """
    b = setup_published_campaign(api)  # b["donor"] is donorA (acting)
    donor_b = register_donor(api, email="db@x.com")  # id used in body
    resp = api.create_donation(
        create_donation_payload(b["campaign"]["id"], donor_b["id"], 10000),
        make_donor_headers(b["donor"]["id"]),  # acting as donorA
    )
    validate_error(resp, ApiErrorId.ERR_DONOR_MISMATCH, 403)
