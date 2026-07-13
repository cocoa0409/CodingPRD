"""Corner: endpoints — pagination envelope, cross-reference link, reverse reachability."""
from test_helpers import (
    validate_success,
    validate_paginated,
    setup_published_campaign,
    setup_reject_cascade_scenario,
    make_donation,
    create_update_payload,
    make_organizer_headers,
)


def test_list_donations_pagination_envelope(api, guest_headers):
    """PRD §2.3: "The meta block of a list response carries limit, offset, total_count (the
    total number of records matching the query before pagination), and has_more (true when
    records remain beyond the current page)."

    Design: Corner/endpoints/list_donations_pagination_envelope
    """
    b = setup_published_campaign(api)
    camp_id = b["campaign"]["id"]
    donor_id = b["donor"]["id"]
    make_donation(api, camp_id, donor_id, 10000)
    make_donation(api, camp_id, donor_id, 20000)
    data, meta = validate_paginated(
        api.list_donations(guest_headers, params={"campaign_id": camp_id, "limit": 1})
    )
    assert len(data) == 1, f"limit=1 returns one record, got {len(data)}"
    assert meta["total_count"] == 2, f"total_count is 2, got {meta['total_count']}"
    assert meta["has_more"] is True, f"has_more is true, got {meta['has_more']}"


def test_thankyou_update_sets_donation_thanked(api, guest_headers):
    """PRD §3.5: "A THANK_YOU may optionally target a specific gift by including a donation_id
    (a general UPDATE leaves it null). When a THANK_YOU names a donation, that donation's
    thanked flag is set to true."

    Design: Corner/endpoints/thankyou_update_sets_donation_thanked
    """
    b = setup_published_campaign(api)
    camp_id = b["campaign"]["id"]
    don = make_donation(api, camp_id, b["donor"]["id"], 10000)
    validate_success(
        api.create_update(
            create_update_payload(camp_id, "THANK_YOU", "Thank you!", donation_id=don["id"]),
            make_organizer_headers(b["organizer"]["id"])),
        201,
    )
    refreshed = validate_success(api.get_donation(don["id"], guest_headers))
    assert refreshed["thanked"] is True, (
        f"a THANK_YOU naming the donation sets thanked true, got {refreshed['thanked']}"
    )


def test_list_payouts_by_beneficiary_reverse_reach(api, guest_headers):
    """PRD §4: "List endpoints accept the pagination parameters limit and offset plus the
    filters named in their §3 narratives: campaigns filter by organizer_id, beneficiary_id,
    and lifecycle_status; team members by campaign_id and organizer_id; donations by
    campaign_id, donor_id, and status; updates by campaign_id and donation_id; payouts by
    campaign_id, beneficiary_id, and status; disputes by donation_id and status; refunds by
    donation_id and dispute_id; holds by campaign_id and status; and feature placements by
    campaign_id and category."

    Design: Corner/endpoints/list_payouts_by_beneficiary_reverse_reach
    """
    s = setup_reject_cascade_scenario(api)  # verified campaign, one REQUESTED payout
    data, meta = validate_paginated(
        api.list_payouts(guest_headers, params={"beneficiary_id": s["beneficiary"]["id"]})
    )
    assert len(data) == 1, f"the beneficiary's single payout is returned, got {len(data)}"
