"""Corner coverage: pagination windowing, computed governance summary, and
filtered-list isolation."""
from test_helpers import (
    api_client,
    create_active_agreement,
    create_active_community,
    create_and_close_lot,
    create_offered_lot,
    create_open_phase,
    create_phase,
    create_lot,
    create_builder,
    set_clock,
    setup_active_agreement_scenario,
    get_success_data,
    validate_paginated,
    TEST_USERS,
)

EXEC = TEST_USERS["declarant_executive_headers"]
CTRL = TEST_USERS["declarant_controller_headers"]


class TestPaginationLimitOffset:
    def test_limit_offset_windowing_over_filtered_lots(self):
        """PRD §2.3: "The `limit` parameter sets the maximum number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter sets the number of items skipped and defaults to 0."
        PRD §2.3: "Unless a collection's own specification says otherwise, every list endpoint returns resources sorted by `created_at` in ascending order. (The board-seat collection is the documented exception: it is ordered by `seat_no` ascending.) Paginated list responses carry the fields `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the response envelope."

        Design: Corner/endpoints/pagination_limit_offset
        """
        community = create_active_community("Page Place", 10)
        phase = create_phase(community["id"], "P1", 1, 5)
        create_lot(phase["id"], "P1")
        create_lot(phase["id"], "P2")
        create_lot(phase["id"], "P3")

        page1_resp = api_client.list_lots(EXEC, params={"phase_id": phase["id"], "limit": 2, "offset": 0})
        page1, meta1 = validate_paginated(page1_resp)
        assert len(page1) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True
        assert page1[0]["parcel_number"] == "P1", (
            "ascending created_at order returns the first created lot first"
        )

        page2_resp = api_client.list_lots(EXEC, params={"phase_id": phase["id"], "limit": 2, "offset": 2})
        page2, meta2 = validate_paginated(page2_resp)
        assert len(page2) == 1
        assert meta2["has_more"] is False
        assert page2[0]["parcel_number"] == "P3"


class TestComputedReadSummary:
    def test_summary_recomputes_posture_from_children(self):
        """PRD §3.1: "A read-only governance dashboard is available for each community, exposing `closed_unit_count`, `closed_unit_pct`, `transition_stage`, and the counts `owner_elected_seats_filled` and `owner_elected_seats_vacant` for the owner-elected delegation."
        PRD §2.7: "The stage mapping, evaluated on the rounded percentage with inclusive thresholds, is: at least 25.00 percent → `OWNER_REPRESENTATION`; at least 50.00 percent → `PARITY`; at least 75.00 percent → `OWNER_MAJORITY`; otherwise `DECLARANT_CONTROL`.".

        Design: Corner/endpoints/computed_read_summary
        """
        scenario = setup_active_agreement_scenario(
            total_planned_units=4, planned_lot_count=4, total_lots_committed=1,
            tranches=[("2026-06-30T00:00:00Z", 1)], community_name="Summary Springs",
            earnest_money_cents=1000000,
        )
        lot = create_offered_lot(scenario["phase"]["id"], "S1")
        set_clock("2026-06-01T00:00:00Z")
        create_and_close_lot(scenario["agreement"]["id"], lot["id"])

        summary = get_success_data(api_client.get_community_summary(scenario["community"]["id"], EXEC))
        assert summary["closed_unit_count"] == 1
        assert float(summary["closed_unit_pct"]) == 25.00
        assert summary["transition_stage"] == "OWNER_REPRESENTATION"
        assert summary["owner_elected_seats_vacant"] == 1


class TestListFilteringIsolation:
    def test_closings_filtered_by_agreement(self):
        """PRD §3.4: "Closings can be listed with filters on `agreement_id`, `lot_id`, `owner_resident_id`, `credited_tranche_id`, or `community_id`."
        PRD §2.10: "The resource graph itself is flat: every collection is a peer under `/mpc`, and parent-child relationships are expressed through foreign keys in request bodies and through filtered list queries rather than through nested URLs.".

        Design: Corner/endpoints/list_filtering_isolation
        """
        community = create_active_community("Filter Falls", 10)
        phase = create_open_phase(community["id"], "P1", 1, 5)
        builder = create_builder(community["id"], "Filter Builders", "A")
        a1, _ = create_active_agreement(
            community["id"], builder["id"], phase["id"], 1,
            [("2026-06-30T00:00:00Z", 1)], earnest_money_cents=1000000,
        )
        a2, _ = create_active_agreement(
            community["id"], builder["id"], phase["id"], 1,
            [("2026-06-30T00:00:00Z", 1)], earnest_money_cents=1000000,
        )
        lot1 = create_offered_lot(phase["id"], "F1")
        lot2 = create_offered_lot(phase["id"], "F2")
        get_success_data(
            api_client.create_closing({"agreement_id": a1["id"], "lot_id": lot1["id"]}, CTRL)
        )
        get_success_data(
            api_client.create_closing({"agreement_id": a2["id"], "lot_id": lot2["id"]}, CTRL)
        )

        resp = api_client.list_closings(CTRL, params={"agreement_id": a1["id"]})
        rows, meta = validate_paginated(resp)
        assert meta["total_count"] == 1
        assert len(rows) == 1
        assert rows[0]["agreement_id"] == a1["id"]
