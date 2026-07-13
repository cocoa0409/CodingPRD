"""Corner: consistency_model — immediate recompute of derived campaign money fields."""
from test_helpers import (
    setup_published_campaign,
    make_donation,
    get_campaign,
)


def test_donation_immediately_visible_in_campaign_raised(api):
    """PRD §2.6: "A campaign exposes a family of computed money fields, each recomputed
    immediately whenever a donation, refund, payout, hold, or dispute changes."
    PRD §3.4: "Recording a donation recomputes the campaign's raised_cents,
    reserve_total_cents, and both availability figures."

    Design: Corner/consistency_model/donation_immediately_visible_in_campaign_raised
    """
    b = setup_published_campaign(api)
    camp_id = b["campaign"]["id"]
    make_donation(api, camp_id, b["donor"]["id"], 25000)
    camp = get_campaign(api, camp_id)
    assert camp["raised_cents"] == 25000, (
        f"the donation's net is reflected in the very next read, got {camp['raised_cents']}"
    )
