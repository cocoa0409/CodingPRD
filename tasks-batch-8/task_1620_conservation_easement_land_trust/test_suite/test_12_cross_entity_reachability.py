"""Reverse reachability: children discoverable from parent references through
PRD-declared list filters and the fund's ledger sub-resource (PRD §3.7, §3.9).

Note: the design instance also gestures at filtering violations by easement_id,
but the PRD never enumerates violation-list filters (§4 lists only "List
violations"), so that branch is not uniquely derivable and is not asserted.
"""
from test_helpers import (
    create_fund,
    create_recorded_easement,
    create_succession_notice,
    list_fund_transactions,
    post_contribution,
    validate_paginated,
)


class TestFkReverseReachability:
    def test_fk_reverse_reachability_filtered_lists(self, api, trust_admin_headers):
        """PRD §3.7: "Notices can be browsed with filters on `easement_id`,
        `successor_landowner_id`, `predecessor_landowner_id`, and `status`."
        PRD §3.9: "The fund's books are an append-only ledger of
        `EndowmentTransaction` entries, processed strictly in posting order — by
        `posted_on`, then by `created_at` — and the fund's transaction listing
        returns entries in that same order."

        Design: Corner/endpoints/fk_reverse_reachability_filtered_lists
        """
        ctx = create_recorded_easement(name="E-FK", parcel_acreage=100,
                                       matrix={"AGRICULTURE": "PERMITTED",
                                               "SUBDIVISION": "PROHIBITED"})
        easement_id = ctx["easement"]["id"]

        notice = create_succession_notice(
            easement_id, ctx["landowner"]["id"],
            successor_owner_name="B", successor_contact_email="b@x.com",
            transfer_on="2026-09-15",
        )
        successor_id = notice["successor_landowner_id"]

        fund = create_fund(easement_id, spending_rate_bps=400,
                           principal_floor_cents=1000)
        post_contribution(fund["id"], 100000)

        # Succession notices are reachable from the successor landowner id.
        notices, notices_meta = validate_paginated(
            api.list_succession_notices(
                trust_admin_headers, params={"successor_landowner_id": successor_id}
            )
        )
        assert notices_meta["total_count"] == 1
        assert [n["id"] for n in notices] == [notice["id"]]

        # The fund's ledger is reachable through its parent fund sub-resource.
        txns = list_fund_transactions(fund["id"])
        assert len(txns) == 1
        assert txns[0]["txn_type"] == "CONTRIBUTION"
        assert txns[0]["amount_cents"] == 100000
        assert txns[0]["fund_id"] == fund["id"]
