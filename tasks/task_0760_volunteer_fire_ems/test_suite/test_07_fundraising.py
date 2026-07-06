"""Fundraising campaigns and donations: conserved raised total, refund lifecycle,
and campaign-state preconditions.

Queue A: compensating_invariant/campaign_funds_conserved_on_refund.
Queue B: corner_refund_when_campaign_closed_invalid, corner_donation_when_campaign_draft_invalid.
"""
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    CHIEF,
    create_active_campaign,
    create_campaign_with_donations,
)
from test_helpers.factories import create_campaign_payload, create_donation_payload


def test_campaign_raised_conserved_after_refund(api):
    """PRD §2.9: "a campaign's raised total is a conserved quantity: it equals, at
    all times, the sum of the amounts of that campaign's posted donations, so
    refunding a donation subtracts exactly its amount and leaves no residue."

    Design: Difficulty/compensating_invariant/campaign_funds_conserved_on_refund
    """
    campaign, donations = create_campaign_with_donations(api, [5000, 3000])
    before = validate_success(api.get_campaign(campaign["id"], CHIEF), 200)
    assert before["raised_cents"] == 8000
    get_success_data(api.refund_donation(donations[1]["id"], CHIEF))  # refund the 3000
    after = validate_success(api.get_campaign(campaign["id"], CHIEF), 200)
    assert after["raised_cents"] == 5000


def test_refund_marks_donation_refunded(api):
    """PRD §3.7: "A Chief may refund a posted donation, `POSTED → REFUNDED`
    (terminal), provided the campaign is not `CLOSED`; refunding against a closed
    campaign is rejected with `ERR_INVALID_STATE`. A refund subtracts exactly the
    donation's `amount_cents` from the campaign's raised total, preserving the
    conservation identity."

    Design: Difficulty/compensating_invariant/campaign_funds_conserved_on_refund
    """
    campaign, donations = create_campaign_with_donations(api, [5000, 3000])
    refunded = validate_success(api.refund_donation(donations[1]["id"], CHIEF), 200)
    assert refunded["status"] == "REFUNDED"


def test_refund_on_closed_campaign_rejected(api):
    """PRD §3.7: "refunding against a closed campaign is rejected with
    `ERR_INVALID_STATE`."

    Design: Corner/state_machines/corner_refund_when_campaign_closed_invalid
    """
    campaign = create_active_campaign(api, goal_cents=50000)
    donation = get_success_data(
        api.create_donation(campaign["id"], create_donation_payload(donor_name="C", amount_cents=4000), CHIEF)
    )
    get_success_data(api.close_campaign(campaign["id"], CHIEF))
    validate_error(api.refund_donation(donation["id"], CHIEF), ApiErrorId.ERR_INVALID_STATE.value)


def test_donation_on_draft_campaign_rejected(api):
    """PRD §3.7: "the campaign begins in `DRAFT` with a `raised_cents` total of
    zero. A Chief opens a campaign, `DRAFT → ACTIVE`, and later closes it,
    `ACTIVE → CLOSED` (terminal). Donations may be recorded only while a campaign
    is `ACTIVE`."

    Design: Corner/state_machines/corner_donation_when_campaign_draft_invalid
    """
    campaign = get_success_data(
        api.create_campaign(create_campaign_payload(name="Draft Camp", goal_cents=50000), CHIEF)
    )
    resp = api.create_donation(campaign["id"], create_donation_payload(donor_name="D", amount_cents=4000), CHIEF)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
