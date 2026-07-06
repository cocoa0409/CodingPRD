"""Public disclosure search and reverse-FK listing across contributions."""
from test_helpers import (
    validate_paginated,
    TEST_USERS,
    create_active_committee, add_contribution,
)

PUBLIC = TEST_USERS["public_headers"]


def test_committee_contributions_reverse_list(api):
    """PRD §3.8: "A committee's contributions can be listed and filtered by settlement_status
    and review_status."

    Design: Corner/endpoints/contribution_committee_reverse_list
    """
    committee = create_active_committee(api, name="RevCo", committee_type="PAC")
    cid = committee["id"]
    con = add_contribution(api, cid, amount_cents=5000)
    data, _meta = validate_paginated(api.list_committee_contributions(cid, PUBLIC))
    assert con["id"] in [c["id"] for c in data], "the created contribution must appear in the committee's list"


def test_contribution_search_min_amount_floor(api):
    """PRD §3.8: "A cross-committee contribution search accepts filters for committee_id,
    contributor_ref, contributor_type, a min_amount_cents floor, and settlement_status."

    Design: Corner/endpoints/contributions_public_search_filter
    """
    committee = create_active_committee(api, name="SearchCo", committee_type="PAC")
    cid = committee["id"]
    add_contribution(api, cid, contributor_ref="r1", contributor_name="Small", amount_cents=5000)
    big = add_contribution(api, cid, contributor_ref="r2", contributor_name="Big", amount_cents=200000)
    data, _meta = validate_paginated(
        api.search_contributions(PUBLIC, params={"committee_id": cid, "min_amount_cents": 100000})
    )
    amounts = [c["amount_cents"] for c in data]
    ids = [c["id"] for c in data]
    assert big["id"] in ids, "the 200000 contribution is at/above the floor"
    assert all(a >= 100000 for a in amounts), "min_amount_cents is a floor; the 5000 contribution is filtered out"
