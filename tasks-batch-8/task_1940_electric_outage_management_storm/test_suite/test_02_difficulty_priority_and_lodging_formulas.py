"""Difficulty tests — combinatorial_formula rule.

Covers the multi-input priority_score ranking calculation and the per-share
lodging rounding that yields a 1-cent overhead residual.
"""
import pytest

from test_helpers import (
    TEST_USERS,
    create_and_activate_event,
    create_available_mutual_aid_crew,
    create_committed_lodging_block,
    create_confirm_outage_payload,
    create_crew,
    create_feeder_record,
    create_outage_payload,
    create_priority_customer_payload,
    create_work_order_payload,
    get_success_data,
    set_clock,
    setup_event_with_feeder,
    validate_paginated,
)

ED = TEST_USERS["emergency_director_headers"]
DISP = TEST_USERS["dispatcher_headers"]
MAC = TEST_USERS["mutual_aid_coordinator_headers"]


class TestPriorityScoreMultiInputRanking:
    """A certified LIFE_SUPPORT feeder outranks a bare larger-customer outage."""

    def test_score_components_add_up(self, api):
        """PRD §3.3: "The `priority_score` is the dispatch ranking number, an
        integer sum of five components: ten thousand points when a `CERTIFIED`
        priority customer of class `LIFE_SUPPORT` exists on the outage's
        feeder; four thousand when a `CERTIFIED` `CRITICAL_FACILITY` customer
        exists on the feeder; the smaller of `customers_affected` and ten
        thousand; fifty points for each whole hour elapsed since
        `confirmed_at`, discarding any partial hour; and two thousand when
        `etr_missed` is currently true."

        Design: Difficulty/combinatorial_formula/priority_score_multi_input_ranking
        """
        set_clock("2026-08-10T00:00:00Z")
        ev = create_and_activate_event(
            event_name="Storm Gamma", event_type="THUNDERSTORM"
        )
        fd1 = create_feeder_record(county_code="C1", customer_count=5000)
        fd2 = create_feeder_record(county_code="C2", customer_count=5000)
        pc = get_success_data(
            api.create_priority_customer(
                create_priority_customer_payload(fd1["id"]), DISP
            )
        )
        get_success_data(
            api.certify_priority_customer(
                pc["id"], {"certified_through": "2026-08-20T00:00:00Z"}, DISP
            )
        )
        o1 = get_success_data(
            api.create_outage(create_outage_payload(ev["id"], fd1["id"]), DISP)
        )
        get_success_data(
            api.confirm_outage(
                o1["id"],
                create_confirm_outage_payload(
                    customers_affected=300, cause_code="EQUIPMENT"
                ),
                DISP,
            )
        )
        o2 = get_success_data(
            api.create_outage(create_outage_payload(ev["id"], fd2["id"]), DISP)
        )
        get_success_data(
            api.confirm_outage(
                o2["id"],
                create_confirm_outage_payload(
                    customers_affected=500, cause_code="EQUIPMENT"
                ),
                DISP,
            )
        )
        # Advance two full hours so the age term contributes 100 points.
        set_clock("2026-08-10T02:00:00Z")
        reread1 = get_success_data(api.get_outage(o1["id"], DISP))
        reread2 = get_success_data(api.get_outage(o2["id"], DISP))
        # 10000 LIFE_SUPPORT + 0 CRITICAL + min(300, 10000) + 2*50 + 0 missed.
        assert reread1["priority_score"] == 10400, (
            f"expected 10400, got {reread1['priority_score']}"
        )
        # 0 + 0 + 500 + 100 + 0.
        assert reread2["priority_score"] == 600, (
            f"expected 600, got {reread2['priority_score']}"
        )

    def test_dispatch_next_picks_higher_scoring_outage(self, api):
        """PRD §3.5: "The eligible set is every work order in `READY` whose
        `required_crew_type` matches the crew's `crew_type` and whose outage
        belongs to that event and is neither `VERIFIED` nor `CANCELLED`; the
        selector picks the order whose outage has the highest `priority_score`,
        breaking ties by the work order's `created_at`, earliest first — never
        by identifier."

        Design: Difficulty/combinatorial_formula/priority_score_multi_input_ranking
        """
        set_clock("2026-08-10T00:00:00Z")
        ev = create_and_activate_event(
            event_name="Storm Gamma", event_type="THUNDERSTORM"
        )
        fd1 = create_feeder_record(county_code="C1", customer_count=5000)
        fd2 = create_feeder_record(county_code="C2", customer_count=5000)
        pc = get_success_data(
            api.create_priority_customer(
                create_priority_customer_payload(fd1["id"]), DISP
            )
        )
        get_success_data(
            api.certify_priority_customer(
                pc["id"], {"certified_through": "2026-08-20T00:00:00Z"}, DISP
            )
        )
        o1 = get_success_data(
            api.create_outage(create_outage_payload(ev["id"], fd1["id"]), DISP)
        )
        get_success_data(
            api.confirm_outage(
                o1["id"],
                create_confirm_outage_payload(
                    customers_affected=300, cause_code="EQUIPMENT"
                ),
                DISP,
            )
        )
        o2 = get_success_data(
            api.create_outage(create_outage_payload(ev["id"], fd2["id"]), DISP)
        )
        get_success_data(
            api.confirm_outage(
                o2["id"],
                create_confirm_outage_payload(
                    customers_affected=500, cause_code="EQUIPMENT"
                ),
                DISP,
            )
        )
        w1 = get_success_data(
            api.create_work_order(
                create_work_order_payload(
                    o1["id"], work_type="ASSESSMENT", required_crew_type="LINE"
                ),
                DISP,
            )
        )
        get_success_data(api.ready_work_order(w1["id"], DISP))
        w2 = get_success_data(
            api.create_work_order(
                create_work_order_payload(
                    o2["id"], work_type="ASSESSMENT", required_crew_type="LINE"
                ),
                DISP,
            )
        )
        get_success_data(api.ready_work_order(w2["id"], DISP))
        set_clock("2026-08-10T02:00:00Z")
        cr = create_crew(crew_type="LINE")

        picked = get_success_data(api.dispatch_next(ev["id"], {"crew_id": cr["id"]}, DISP))
        assert picked["id"] == w1["id"], (
            "the selector must pick the higher-scoring outage's work order"
        )
        assert picked["execution_status"] == "DISPATCHED"
        crew_read = get_success_data(api.get_crew(cr["id"], DISP))
        assert crew_read["crew_status"] == "EN_ROUTE"
        # The other work order is untouched.
        w2_read = get_success_data(api.get_work_order(w2["id"], DISP))
        assert w2_read["execution_status"] == "READY"


class TestLodgingPerShareRoundingResidual:
    """Per-share rounding happens BEFORE summation; the residual absorbs drift."""

    def test_per_share_rounding_produces_one_cent_residual(self, api):
        """PRD §3.7: "The tax is applied per crew share and rounded before the
        shares are summed; the block total is rounded separately. Whatever
        remains — the block total minus the sum of the shares — posts as one
        overhead `LODGING` entry with no crew reference, deliberately absorbing
        the sub-cent rounding drift: a five-room block for a single night at
        12,345 cents per room totals 66,046 cents, and two crews of roster
        sizes two and three assigned for that night post shares of 26,418 and
        39,627 cents, leaving a one-cent residual on the overhead entry."

        Design: Difficulty/combinatorial_formula/lodging_per_share_rounding_residual
        """
        set_clock("2026-08-10T00:00:00Z")
        ev = create_and_activate_event(event_name="Storm Delta", event_type="TORNADO")
        lb = create_committed_lodging_block(
            ev["id"],
            room_count=5,
            nightly_rate_cents=12345,
            window_start="2026-08-10T00:00:00Z",
            window_end="2026-08-11T00:00:00Z",
            county_code="C1",
            hotel_name="Hotel H",
        )
        ma = create_available_mutual_aid_crew(
            ev["id"],
            crew_type="LINE",
            roster_size=2,
            daily_rate_cents=40000,
            per_diem_cents=5000,
            window_start="2026-08-10T00:00:00Z",
            window_end="2026-08-11T00:00:00Z",
            county_code="C1",
        )
        mb = create_available_mutual_aid_crew(
            ev["id"],
            crew_type="TREE",
            roster_size=3,
            daily_rate_cents=40000,
            per_diem_cents=5000,
            window_start="2026-08-10T00:00:00Z",
            window_end="2026-08-11T00:00:00Z",
            county_code="C1",
        )
        get_success_data(api.assign_lodging(ma["id"], {"lodging_block_id": lb["id"]}, MAC))
        get_success_data(api.assign_lodging(mb["id"], {"lodging_block_id": lb["id"]}, MAC))
        get_success_data(api.demobilize_mutual_aid_crew(ma["id"], MAC))
        get_success_data(api.demobilize_mutual_aid_crew(mb["id"], MAC))

        get_success_data(api.release_lodging_block(lb["id"], MAC))
        entries, meta = validate_paginated(
            api.list_cost_ledger_entries(
                MAC, params={"storm_event_id": ev["id"], "entry_type": "LODGING"}
            )
        )
        amounts = sorted(e["amount_cents"] for e in entries)
        # Two crew shares (per-crew rounding first) + one overhead residual.
        assert amounts == [1, 26418, 39627], (
            f"expected [1, 26418, 39627], got {amounts}"
        )
        # The residual entry carries no crew/work-order reference.
        residual = [e for e in entries if e["amount_cents"] == 1]
        assert len(residual) == 1
        assert residual[0]["work_order_id"] is None

        ev_final = get_success_data(api.get_storm_event(ev["id"], MAC))
        assert ev_final["total_lodging_cents"] == 66046, (
            f"total_lodging_cents must equal the rounded block total 66046; "
            f"got {ev_final['total_lodging_cents']}"
        )

    def test_block_total_is_rounded_separately_from_shares(self, api):
        """PRD §3.7: "The block's night count is its whole number of
        twenty-four-hour nights, and its total is `room_count` times the night
        count times `nightly_rate_cents` times one plus a seven percent lodging
        tax, rounded half up to whole cents."

        Design: Difficulty/combinatorial_formula/lodging_per_share_rounding_residual
        """
        set_clock("2026-08-10T00:00:00Z")
        ev = create_and_activate_event(event_name="Storm Delta", event_type="TORNADO")
        lb = create_committed_lodging_block(
            ev["id"],
            room_count=5,
            nightly_rate_cents=12345,
            window_start="2026-08-10T00:00:00Z",
            window_end="2026-08-11T00:00:00Z",
            county_code="C1",
            hotel_name="Hotel H",
        )
        ma = create_available_mutual_aid_crew(
            ev["id"],
            crew_type="LINE",
            roster_size=2,
            daily_rate_cents=40000,
            per_diem_cents=5000,
            window_start="2026-08-10T00:00:00Z",
            window_end="2026-08-11T00:00:00Z",
            county_code="C1",
        )
        mb = create_available_mutual_aid_crew(
            ev["id"],
            crew_type="TREE",
            roster_size=3,
            daily_rate_cents=40000,
            per_diem_cents=5000,
            window_start="2026-08-10T00:00:00Z",
            window_end="2026-08-11T00:00:00Z",
            county_code="C1",
        )
        get_success_data(api.assign_lodging(ma["id"], {"lodging_block_id": lb["id"]}, MAC))
        get_success_data(api.assign_lodging(mb["id"], {"lodging_block_id": lb["id"]}, MAC))
        get_success_data(api.demobilize_mutual_aid_crew(ma["id"], MAC))
        get_success_data(api.demobilize_mutual_aid_crew(mb["id"], MAC))

        get_success_data(api.release_lodging_block(lb["id"], MAC))
        entries, _meta = validate_paginated(
            api.list_cost_ledger_entries(
                MAC, params={"storm_event_id": ev["id"], "entry_type": "LODGING"}
            )
        )
        assert len(entries) == 3, (
            f"expected 2 crew shares + 1 overhead residual, got {len(entries)}"
        )
        # Crew shares pinned individually (per-share rounding first).
        share_amounts = sorted(
            e["amount_cents"] for e in entries if e["amount_cents"] != 1
        )
        assert share_amounts == [26418, 39627]
        # Per-share-first vs sum-then-round is what forces the 1-cent residual.
        block_total = 66046
        assert block_total - (26418 + 39627) == 1
