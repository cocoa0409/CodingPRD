"""Corner: state_machines — invalid transitions, terminal lockdown, idempotency,
and a posture recompute on hold release.
"""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    setup_published_campaign,
    setup_actor_trio,
    create_draft_campaign,
    register_beneficiary,
    verify_beneficiary,
    place_hold,
    get_campaign,
    make_organizer_headers,
    TEST_USERS,
)

TS_AGENT = TEST_USERS["ts_agent_headers"]


def test_publish_already_active_returns_invalid_state(api):
    """PRD §3.2: "Publishing takes a DRAFT campaign to ACTIVE and opens it to donations;
    publishing is available only to an organizer who is an ACTIVE team member holding the
    owner role on that campaign (otherwise ERR_FORBIDDEN) and requires the goal to be positive."
    PRD §2.10: "6. Target-resource state validity for the requested transition, including a
    campaign being ACTIVE before a donation is accepted (ERR_INVALID_STATE, 409; the
    donation-specific variant is ERR_CAMPAIGN_NOT_ACTIVE, 409)."

    Design: Corner/state_machines/publish_already_active_returns_invalid_state
    """
    b = setup_published_campaign(api)  # already ACTIVE
    resp = api.publish_campaign(b["campaign"]["id"], make_organizer_headers(b["organizer"]["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)


def test_pause_cancelled_campaign_returns_invalid_state(api):
    """PRD §3.2: "Pausing takes an ACTIVE campaign to PAUSED; resuming takes a PAUSED
    campaign back to ACTIVE; each requires its exact starting state, otherwise
    ERR_INVALID_STATE."

    Design: Corner/state_machines/pause_cancelled_campaign_returns_invalid_state
    """
    org, ben, _ = setup_actor_trio(api)
    camp = create_draft_campaign(api, org["id"], ben["id"])
    validate_success(api.cancel_campaign(camp["id"], make_organizer_headers(org["id"])))
    resp = api.pause_campaign(camp["id"], make_organizer_headers(org["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)


def test_approve_verification_twice_returns_invalid_state(api):
    """PRD §3.1: "A Trust & Safety agent then either approves a PENDING beneficiary to
    VERIFIED, or rejects it. Approval — valid only from PENDING, otherwise ERR_INVALID_STATE —
    additionally recomputes the payout posture of every campaign of that beneficiary, which
    can lift a previously FROZEN campaign back toward OPEN."

    Design: Corner/state_machines/approve_verification_twice_returns_invalid_state
    """
    ben = register_beneficiary(api)
    verify_beneficiary(api, ben["id"])  # now VERIFIED
    resp = api.approve_verification(ben["id"], TS_AGENT)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)


def test_posture_returns_open_after_hold_release(api):
    """PRD §3.8: "Releasing a hold moves it from ACTIVE to RELEASED (only valid from ACTIVE,
    otherwise ERR_INVALID_STATE), then recomputes hold_locked_cents and the payout posture —
    which returns to OPEN once the campaign's last active hold is gone and its beneficiary is
    not rejected."

    Design: Corner/state_machines/posture_returns_open_after_hold_release
    """
    b = setup_published_campaign(api)
    camp_id = b["campaign"]["id"]
    hold = place_hold(api, camp_id)
    assert get_campaign(api, camp_id)["payout_posture"] == "HOLD"
    validate_success(api.release_hold(hold["id"], TS_AGENT))
    assert get_campaign(api, camp_id)["payout_posture"] == "OPEN", (
        "releasing the only ACTIVE hold recomputes payout_posture back to OPEN"
    )
