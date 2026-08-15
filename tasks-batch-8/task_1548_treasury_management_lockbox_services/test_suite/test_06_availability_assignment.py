"""Availability assignment: schedule precedence, default tier, and immediate
read-after-write consistency."""
from test_helpers import (
    accept_item,
    assert_item,
    begin_capture,
    capture_item,
    create_batch,
    run_close_business_day,
    setup_live_lockbox,
    validate_success,
)


class TestTieredPrioritySelector:
    def test_lowest_priority_value_wins_among_matching_schedules(self, api):
        """PRD §3.4: "the winner follows the precedence of §3.3 — lowest
        `priority`, then later `effective_from`, then earliest schedule
        `created_at`. The item's `availability_date` is the anchor plus zero
        business days for `SAME_DAY`, one for `ONE_DAY`, or two for `TWO_DAY`."

        Design: Difficulty/combinatorial_formula/availability_assignment_tiered_priority_selector
        """
        ws = setup_live_lockbox(schedule_specs=[
            {"routing_number_pattern": "0710", "tier": "TWO_DAY",
             "effective_from": "2026-08-01", "priority": 5},
            {"routing_number_pattern": "0710", "tier": "ONE_DAY",
             "effective_from": "2026-08-01", "priority": 2},
            {"routing_number_pattern": "0710", "tier": "SAME_DAY",
             "effective_from": "2026-08-01", "priority": 1},
        ])
        batch = create_batch(ws, batch_reference="B1", declared_item_count=1,
                             declared_total_cents=10000)
        begin_capture(ws, batch["id"])
        item = capture_item(ws, batch["id"], check_number="1",
                            payer_routing_number="071000288",
                            amount_cents=10000)
        accepted = accept_item(ws, batch["id"], item["id"])
        # All three schedules match the prefix; priority 1 (SAME_DAY) wins.
        assert accepted["availability_tier"] == "SAME_DAY"
        # The batch booked to 2026-08-01; SAME_DAY adds zero business days.
        assert accepted["availability_date"] == "2026-08-01"

    def test_priority_flip_changes_assigned_tier(self, api):
        """PRD §3.3: "when several patterns match, the lowest `priority` value
        wins, ties break toward the later `effective_from`, and any remaining
        tie breaks toward the schedule with the earlier `created_at`."
        PRD §3.4: "The item's `availability_date` is the anchor plus zero
        business days for `SAME_DAY`, one for `ONE_DAY`, or two for `TWO_DAY`."

        Design: Difficulty/combinatorial_formula/availability_assignment_tiered_priority_selector
        """
        ws = setup_live_lockbox(schedule_specs=[
            {"routing_number_pattern": "0710", "tier": "TWO_DAY",
             "effective_from": "2026-08-01", "priority": 5},
            {"routing_number_pattern": "0710", "tier": "ONE_DAY",
             "effective_from": "2026-08-01", "priority": 2},
        ])
        batch = create_batch(ws, batch_reference="B1", declared_item_count=1,
                             declared_total_cents=10000)
        begin_capture(ws, batch["id"])
        item = capture_item(ws, batch["id"], check_number="1",
                            payer_routing_number="071000288",
                            amount_cents=10000)
        accepted = accept_item(ws, batch["id"], item["id"])
        # Without the priority-1 schedule, priority 2 (ONE_DAY) wins.
        assert accepted["availability_tier"] == "ONE_DAY"
        # Anchor 2026-08-01 (Saturday) + 1 business day is Monday 2026-08-03.
        assert accepted["availability_date"] == "2026-08-03"


class TestDefaultTierFallback:
    def test_availability_schedule_no_match_defaults_to_two_day(self, api):
        """PRD §3.4: "If no schedule qualifies, the tier defaults to
        `TWO_DAY`."
        PRD §3.4: "The item's `availability_date` is the anchor plus zero
        business days for `SAME_DAY`, one for `ONE_DAY`, or two for `TWO_DAY`."

        Design: Corner/calculations/availability_schedule_no_match_defaults_to_two_day
        """
        ws = setup_live_lockbox()
        # Advance the business date to Monday 2026-08-03 so the two-business-day
        # projection lands midweek (Wednesday 2026-08-05).
        run_close_business_day(ws)
        batch = create_batch(ws, batch_reference="B1",
                             received_at="2026-08-03T13:00:00Z",
                             declared_item_count=1, declared_total_cents=1000)
        assert batch["business_date"] == "2026-08-03"
        begin_capture(ws, batch["id"])
        # Routing 9990... does not match the site's '0710' prefix schedule.
        item = capture_item(ws, batch["id"], check_number="1",
                            payer_routing_number="999000000",
                            amount_cents=1000)
        accepted = accept_item(ws, batch["id"], item["id"])
        assert accepted["availability_tier"] == "TWO_DAY"
        assert accepted["availability_date"] == "2026-08-05"


class TestImmediateConsistency:
    def test_immediate_consistency_on_item_accept(self, api, auditor_headers):
        """PRD §3.4: "Acceptance assigns the item's `availability_tier` and
        `availability_date`, grows the batch's `accepted_item_count` by one and
        `accepted_total_cents` by `amount_cents`".
        PRD §2.2: "Unless otherwise noted, operations that create or modify a
        resource will return the created or updated resource object in the data
        field."

        Design: Corner/consistency_model/immediate_consistency_on_item_accept
        """
        ws = setup_live_lockbox()
        batch = create_batch(ws, batch_reference="B1", declared_item_count=1,
                             declared_total_cents=1000)
        begin_capture(ws, batch["id"])
        item = capture_item(ws, batch["id"], check_number="1",
                            amount_cents=1000)
        accepted = accept_item(ws, batch["id"], item["id"])
        assert_item(accepted)
        assert accepted["status"] == "ACCEPTED"
        assert accepted["availability_tier"] == "SAME_DAY"
        assert accepted["availability_date"] == "2026-08-01"
        fetched = validate_success(api.get_item(
            ws["bank"]["id"], ws["customer"]["id"], ws["agreement"]["id"],
            ws["site"]["id"], batch["id"], item["id"], auditor_headers))
        # No consistency lag: the read returns exactly what the write returned.
        assert fetched["status"] == accepted["status"]
        assert fetched["availability_tier"] == accepted["availability_tier"]
        assert fetched["availability_date"] == accepted["availability_date"]
