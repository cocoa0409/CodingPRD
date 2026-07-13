"""Corner: cross_cutting_complexity_layers — optimistic concurrency on Campaign.version
and a cascading compensation on payout reversal.
"""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    setup_actor_trio,
    create_draft_campaign,
    setup_published_campaign,
    make_donation,
    request_payout,
    campaign_version,
    setup_paid_payout_scenario,
    get_campaign,
    create_payout_payload,
    make_organizer_headers,
    TEST_USERS,
)

TS_AGENT = TEST_USERS["ts_agent_headers"]


def test_campaign_patch_increments_version(api):
    """PRD §2.7: "No other endpoint takes a version field. A successful campaign edit and a
    successful payout request each increment the campaign's version by one."

    Design: Corner/cross_cutting_complexity_layers/campaign_patch_increments_version
    """
    org, ben, _ = setup_actor_trio(api)
    camp = create_draft_campaign(api, org["id"], ben["id"])  # version 1
    data = validate_success(
        api.edit_campaign(
            camp["id"],
            {"story": "Updated story", "expected_campaign_version": camp["version"]},
            make_organizer_headers(org["id"])),
    )
    assert data["version"] == 2, f"a successful edit increments version 1 -> 2, got {data['version']}"


def test_campaign_edit_stale_version_returns_412(api):
    """PRD §2.7: "Editing a campaign's title, story, or goal_cents must carry
    expected_campaign_version equal to the campaign's current version. If a cascade (an upheld
    dispute, a placed hold, a settled payout) or another editor has advanced the version since
    the client last read the campaign, the edit is rejected with ERR_STALE_VERSION (HTTP 412)
    rather than clobbering the newer state."

    Design: Corner/cross_cutting_complexity_layers/campaign_edit_stale_version_returns_412
    """
    org, ben, _ = setup_actor_trio(api)
    camp = create_draft_campaign(api, org["id"], ben["id"])
    stale_version = camp["version"]
    validate_success(api.publish_campaign(camp["id"], make_organizer_headers(org["id"])))  # advances version
    resp = api.edit_campaign(
        camp["id"],
        {"story": "Stale edit", "expected_campaign_version": stale_version},
        make_organizer_headers(org["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION, 412)


def test_payout_create_stale_campaign_returns_412(api):
    """PRD §2.7: "Requesting a payout must carry expected_campaign_version equal to the
    campaign's current version. If the campaign's version has advanced since the client
    computed the available balance — because another payout was created, a refund posted, or a
    hold placed — the request is rejected with ERR_STALE_VERSION (HTTP 412), because the
    requester's view of the available balance is stale and the payout would otherwise draw
    against a balance that no longer exists."

    Design: Corner/cross_cutting_complexity_layers/payout_create_stale_campaign_returns_412
    """
    b = setup_published_campaign(api, verified=True, goal_cents=1_000_000)
    camp_id = b["campaign"]["id"]
    org_id = b["organizer"]["id"]
    make_donation(api, camp_id, b["donor"]["id"], 100000)
    stale_version = campaign_version(api, camp_id)
    request_payout(api, camp_id, org_id, 1000)  # advances the campaign version
    resp = api.create_payout(
        create_payout_payload(camp_id, 1000, stale_version), make_organizer_headers(org_id)
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION, 412)


def test_payout_reverse_decrements_paid_out(api, guest_headers):
    """PRD §3.7: "a fraudulent PAID payout is clawed back by a Trust & Safety agent, moving it
    from PAID to REVERSED (only valid from PAID, otherwise ERR_INVALID_STATE) and compensating
    the ledger: the campaign's paid_out_cents and the beneficiary's total_paid_out_cents are
    each decremented by the amount."

    Design: Corner/cross_cutting_complexity_layers/payout_reverse_decrements_paid_out
    """
    s = setup_paid_payout_scenario(api)
    payout = validate_success(api.reverse_payout(s["payout"]["id"], TS_AGENT))
    assert payout["status"] == "REVERSED"
    camp = get_campaign(api, s["camp_id"])
    assert camp["paid_out_cents"] == 0, f"paid_out compensated to 0, got {camp['paid_out_cents']}"
    ben = validate_success(api.get_beneficiary(s["beneficiary"]["id"], guest_headers))
    assert ben["total_paid_out_cents"] == 0, (
        f"beneficiary total_paid_out compensated to 0, got {ben['total_paid_out_cents']}"
    )
