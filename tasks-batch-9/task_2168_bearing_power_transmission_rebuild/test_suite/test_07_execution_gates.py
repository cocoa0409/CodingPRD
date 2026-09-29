# -*- coding: utf-8 -*-
"""The scheduling gate, the four START conditions and the scrap cascade."""
import pytest

from test_helpers import (
    ADMIN_1, FOUR_BANDS, ONE_BAND, PLANNER_1, ApiErrorId, add_approved_part_line,
    add_part_line, api_client as api, confirm_reservation, credit_notes,
    decide_part_line, inspect_order, order_action, quote_order, read_bench,
    read_core, read_customer, read_inspection, read_order, reserve_bench,
    schedule_order, setup_shop, submit_part_line, validate_error,
    validate_paginated, validate_success,
)


class TestStartLadderPrecedence:

    def _quoted_without_inspection(self, account_code="NGM-009", serial="SN-77009"):
        world = setup_shop(account_code=account_code, asset_tag="CONV-04-GBX",
                           serial_no=serial, rebuild_count=1,
                           declared_condition_grade="GRADE_D", labor_hours=6.5)
        quote_order(world)
        return world

    def test_start_from_quoted_reports_the_order_state_error_not_the_core_error(self):
        """PRD 3.9: "Four conditions guard the start, again in ladder order. The order must be
        `SCHEDULED`, or the attempt is `ERR_ORDER_INVALID_STATE`. The order's core must be in
        `GRADED`, or the attempt is `ERR_CORE_NOT_GRADED` (HTTP 409)."
        PRD 2.8: "When a request violates more than one rule, exactly one error is returned, and
        which one is fully determined: rules are evaluated in ascending priority order and the
        **first** rule that fails decides the response."

        Design: Difficulty/priority_pair_validation_conflict/order_state_error_beats_core_not_graded_referential_error
        """
        world = self._quoted_without_inspection()
        assert read_core(world["core"]["id"])["status"] == "RECEIVED"

        error = validate_error(api.advance_rebuild_order(
            world["order"]["id"], {"action": "START"}, PLANNER_1),
            ApiErrorId.ERR_ORDER_INVALID_STATE.value, 409)
        assert error["error_id"] != ApiErrorId.ERR_CORE_NOT_GRADED.value

    def test_the_refused_start_leaves_both_records_exactly_where_they_were(self):
        """PRD 3.9: "Starting work moves an order `SCHEDULED → IN_PROGRESS` and drags the core
        `GRADED → REBUILDING` with it."
        PRD 2.8: "The target record's own state admitting the requested action —
        `ERR_ORDER_INVALID_STATE`, `ERR_CORE_UNIT_INVALID_STATE`,
        `ERR_INSPECTION_INVALID_STATE`, `ERR_PART_LINE_INVALID_STATE`,
        `ERR_RESERVATION_INVALID_STATE`, `ERR_INSTALLATION_INVALID_STATE`,
        `ERR_CLAIM_INVALID_STATE` and `ERR_CREDIT_NOTE_INVALID_STATE`, all HTTP 409."

        Design: Difficulty/priority_pair_validation_conflict/order_state_error_beats_core_not_graded_referential_error
        """
        world = self._quoted_without_inspection()
        validate_error(api.advance_rebuild_order(
            world["order"]["id"], {"action": "START"}, PLANNER_1),
            ApiErrorId.ERR_ORDER_INVALID_STATE.value, 409)

        assert read_order(world["order"]["id"])["work_status"] == "QUOTED"
        core = read_core(world["core"]["id"])
        assert core["status"] == "RECEIVED"
        assert core["condition_grade"] is None


class TestStartRequiresAGradedCore:

    def _scheduled_without_inspection(self):
        world = setup_shop(account_code="NGM-012", asset_tag="CONV-04-GBX",
                           serial_no="SN-77012", rebuild_count=1,
                           declared_condition_grade="GRADE_D", labor_hours=6.5,
                           bench_code="B-4")
        quote_order(world)
        world["reservation"] = reserve_bench(world["order"]["id"], world["bench"]["id"],
                                             "2026-09-04T08:00:00Z",
                                             "2026-09-04T12:00:00Z")
        confirm_reservation(world["reservation"]["id"])
        world["order"] = order_action(world["order"]["id"], "SCHEDULE")
        return world

    def test_a_scheduled_order_still_cannot_start_on_an_ungraded_core(self):
        """PRD 3.9: "The order's core must be in `GRADED`, or the attempt is
        `ERR_CORE_NOT_GRADED` (HTTP 409)."
        PRD 3.9: "Starting work moves an order `SCHEDULED → IN_PROGRESS` and drags the core
        `GRADED → REBUILDING` with it."

        Design: Difficulty/cross_entity_state_dependency/order_start_blocked_by_ungraded_core_unit
        """
        world = self._scheduled_without_inspection()
        assert read_order(world["order"]["id"])["work_status"] == "SCHEDULED"

        validate_error(api.advance_rebuild_order(
            world["order"]["id"], {"action": "START"}, PLANNER_1),
            ApiErrorId.ERR_CORE_NOT_GRADED.value, 409)

    def test_the_blocked_start_leaves_the_order_scheduled_and_the_core_received(self):
        """PRD 3.4: "Opening a bench inspection is what moves a core off the receiving shelf:
        the core transitions `RECEIVED → INSPECTING`, its `updated_at` is refreshed and its
        `version` advances."
        PRD 3.9: "The order's core must be in `GRADED`, or the attempt is `ERR_CORE_NOT_GRADED`
        (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/order_start_blocked_by_ungraded_core_unit
        """
        world = self._scheduled_without_inspection()
        validate_error(api.advance_rebuild_order(
            world["order"]["id"], {"action": "START"}, PLANNER_1),
            ApiErrorId.ERR_CORE_NOT_GRADED.value, 409)

        assert read_order(world["order"]["id"])["work_status"] == "SCHEDULED"
        core = read_core(world["core"]["id"])
        assert core["status"] == "RECEIVED"
        assert core["condition_grade"] is None


class TestScrapBeatsClearance:

    def _scheduled_scrap_graded_world(self):
        world = setup_shop(account_code="NGM-011", asset_tag="CONV-04-GBX",
                           serial_no="SN-77011", rebuild_count=1,
                           declared_condition_grade="GRADE_D", labor_hours=6.5,
                           bench_code="B-3")
        inspect_order(world, measurements=(("BORE", 200),))
        quote_order(world)
        schedule_order(world, "2026-09-03T08:00:00Z", "2026-09-03T12:00:00Z")
        return world

    def test_an_out_of_spec_bore_grades_the_core_scrap_and_zeroes_its_credit(self):
        """PRD 3.5: "That score is then banded into `remaining_life_grade` against four
        inclusive floors: a score of 80 or more is `GRADE_A`, 60 or more is `GRADE_B`, 35 or
        more is `GRADE_C`, 15 or more is `GRADE_D`, and anything below 15 is `SCRAP`."
        PRD 3.6: "The tiered figure less the decay less the summed deductions is finally clamped
        below at zero and above at the full `base_core_value_cents`."

        Design: Difficulty/priority_pair_validation_conflict/core_scrapped_referential_error_beats_clearance_safety_error
        """
        world = self._scheduled_scrap_graded_world()
        assert world["measurements"][0]["band_result"] == "OUT_OF_SPEC"

        insp = read_inspection(world["inspection"]["id"])
        assert insp["remaining_life_score"] == 0
        assert insp["remaining_life_grade"] == "SCRAP"

        core = read_core(world["core"]["id"])
        assert core["status"] == "GRADED"
        assert core["condition_grade"] == "SCRAP"
        assert core["final_core_credit_cents"] == 0

        order = read_order(world["order"]["id"])
        assert order["core_credit_applied_cents"] == 0
        assert order["quote_total_cents"] == 171250

    def test_start_reports_core_scrapped_ahead_of_clearance_out_of_spec(self):
        """PRD 3.9: "The core must not be scrap — neither a `condition_grade` of `SCRAP` nor a
        core `status` of `SCRAPPED` is acceptable — or the attempt is `ERR_CORE_SCRAPPED` (HTTP
        409). And no governing measurement of the order's accepted inspection may have a
        `band_result` of `OUT_OF_SPEC`; a core with an out-of-specification feature cannot be
        re-manufactured to this spec, and the attempt is `ERR_CLEARANCE_OUT_OF_SPEC` (HTTP 422)."

        Design: Difficulty/priority_pair_validation_conflict/core_scrapped_referential_error_beats_clearance_safety_error
        """
        world = self._scheduled_scrap_graded_world()
        error = validate_error(api.advance_rebuild_order(
            world["order"]["id"], {"action": "START"}, PLANNER_1),
            ApiErrorId.ERR_CORE_SCRAPPED.value, 409)
        assert error["error_id"] != ApiErrorId.ERR_CLEARANCE_OUT_OF_SPEC.value
        assert read_order(world["order"]["id"])["work_status"] == "SCHEDULED"

    def test_clearance_out_of_spec_surfaces_when_the_grade_is_not_scrap(self):
        """PRD 3.9: "And no governing measurement of the order's accepted inspection may have a
        `band_result` of `OUT_OF_SPEC`; a core with an out-of-specification feature cannot be
        re-manufactured to this spec, and the attempt is `ERR_CLEARANCE_OUT_OF_SPEC` (HTTP 422)."
        PRD 3.5: "Fifth: if the inspection has a governing measurement for the feature code
        `HOUSING_FIT` and that measurement's `band_result` is anything other than `IN_SPEC`, the
        code is `LOOSE_FIT` with confidence `MEDIUM`."

        Design: Corner/errors/clearance_out_of_spec_blocks_start_when_the_grade_is_not_scrap
        """
        world = setup_shop(account_code="SPC-001", customer_name="Spec Mill",
                           asset_tag="SPC-01-GBX", feature_bands=FOUR_BANDS,
                           serial_no="SN-SPC-1", declared_condition_grade="GRADE_B",
                           labor_hours=4.0, bench_code="B-SPC")
        inspect_order(world, measurements=(("BORE", 85), ("JOURNAL", 58),
                                           ("HOUSING_FIT", 200), ("END_PLAY", 100)))
        quote_order(world, part_overrides={"part_no": "BRG-22324", "qty": 1,
                                           "unit_cost_cents": 40000})
        schedule_order(world, "2026-09-14T08:00:00Z", "2026-09-14T12:00:00Z")

        insp = read_inspection(world["inspection"]["id"])
        assert insp["remaining_life_score"] == 75
        assert insp["remaining_life_grade"] == "GRADE_B"
        assert insp["failure_cause_code"] == "LOOSE_FIT"
        assert insp["cause_confidence"] == "MEDIUM"

        core = read_core(world["core"]["id"])
        assert core["condition_grade"] == "GRADE_B"
        assert core["final_core_credit_cents"] == 63000

        error = validate_error(api.advance_rebuild_order(
            world["order"]["id"], {"action": "START"}, PLANNER_1),
            ApiErrorId.ERR_CLEARANCE_OUT_OF_SPEC.value, 422)
        assert error["error_id"] != ApiErrorId.ERR_CORE_SCRAPPED.value

        assert read_order(world["order"]["id"])["work_status"] == "SCHEDULED"
        assert read_core(world["core"]["id"])["status"] == "GRADED"


class TestSchedulingGate:

    def test_a_clean_order_passes_every_scheduling_condition(self):
        """PRD 3.8: "Scheduling is the gate all of this feeds. A `Planner` or `ShopAdmin` moving
        an order `QUOTED → SCHEDULED` must satisfy four conditions, and they are evaluated in
        the ladder order of §2.8."
        PRD 3.8: "At least one of its bench reservations must be `CONFIRMED`, or the attempt is
        `ERR_NO_CONFIRMED_BENCH` (HTTP 409). And the quote must be current:
        `quoted_part_revision` must still equal `part_revision_counter`, so that any part-line
        mutation since the last quote makes the quote stale and the attempt `ERR_QUOTE_STALE`
        (HTTP 409)."

        Design: Corner/validations/schedule_gate_satisfaction_lets_a_clean_order_through
        """
        world = setup_shop(account_code="CLN-001", customer_name="Clean Mill",
                           asset_tag="CLN-01-GBX", serial_no="SN-CLN-1",
                           declared_condition_grade="GRADE_B", labor_hours=4.0,
                           bench_code="B-CLN")
        quote_order(world, part_overrides={"part_no": "BRG-22324", "qty": 1,
                                           "unit_cost_cents": 40000})
        reservation = reserve_bench(world["order"]["id"], world["bench"]["id"],
                                    "2026-09-11T08:00:00Z", "2026-09-11T12:00:00Z")
        confirm_reservation(reservation["id"])

        scheduled = validate_success(api.advance_rebuild_order(
            world["order"]["id"], {"action": "SCHEDULE"}, PLANNER_1))
        assert scheduled["work_status"] == "SCHEDULED"
        assert scheduled["approval_status"] == "APPROVED"
        assert scheduled["quoted_part_revision"] == scheduled["part_revision_counter"] == 3

        rows, _ = validate_paginated(
            api.list_bench_reservations(world["bench"]["id"], PLANNER_1))
        assert rows[0]["status"] == "CONFIRMED"
        assert read_bench(world["bench"]["id"])["committed_minutes"] == 240

    def test_scheduling_stops_on_an_unconfirmed_bench_and_then_on_a_stale_quote(self):
        """PRD 3.8: "At least one of its bench reservations must be `CONFIRMED`, or the attempt
        is `ERR_NO_CONFIRMED_BENCH` (HTTP 409)."
        PRD 3.8: "And the quote must be current: `quoted_part_revision` must still equal
        `part_revision_counter`, so that any part-line mutation since the last quote makes the
        quote stale and the attempt `ERR_QUOTE_STALE` (HTTP 409)."

        Design: Corner/errors/schedule_gates_stop_missing_bench_and_stale_quote
        """
        world = setup_shop(account_code="GAT-001", customer_name="Gate Mill",
                           asset_tag="GAT-01-GBX", serial_no="SN-GAT-1",
                           declared_condition_grade="GRADE_B", labor_hours=4.0,
                           bench_code="B-GAT")
        order_id, cust_id = world["order"]["id"], world["customer"]["id"]
        quote_order(world, part_overrides={"part_no": "BRG-22324", "qty": 1,
                                           "unit_cost_cents": 40000})
        reservation = reserve_bench(order_id, world["bench"]["id"],
                                    "2026-09-13T08:00:00Z", "2026-09-13T12:00:00Z")

        validate_error(api.advance_rebuild_order(order_id, {"action": "SCHEDULE"}, PLANNER_1),
                       ApiErrorId.ERR_NO_CONFIRMED_BENCH.value, 409)

        confirm_reservation(reservation["id"])
        second = add_part_line(order_id, part_no="SHIM-2", source_class="OEM", qty=1,
                               unit_cost_cents=500)
        submit_part_line(second["id"])
        decide_part_line(second["id"], cust_id, "APPROVE")

        order = read_order(order_id)
        assert order["approval_status"] == "APPROVED"
        assert order["quoted_part_revision"] == 3
        assert order["part_revision_counter"] == 6

        validate_error(api.advance_rebuild_order(order_id, {"action": "SCHEDULE"}, PLANNER_1),
                       ApiErrorId.ERR_QUOTE_STALE.value, 409)
        assert read_order(order_id)["work_status"] == "QUOTED"


class TestScrapCascade:

    def test_scrapping_a_graded_core_cancels_its_orders_and_frees_the_bench(self):
        """PRD 3.6: "Scrapping cascades widely: the core's `POSTED` `CORE_EXCHANGE` note goes to
        `VOID` with a `void_reason` of "core scrapped", the account's balances are recomputed
        and its `QUOTED` orders re-priced, and every rebuild order referencing that core whose
        `work_status` is `DRAFT`, `QUOTED` or `SCHEDULED` moves to `CANCELLED` with a
        `cancel_reason` of "core scrapped""
        PRD 3.6: "A `ShopAdmin` may scrap a graded core outright, moving it `GRADED →
        SCRAPPED`. Scrapping is permitted when the core's `condition_grade` is `SCRAP`; when it
        is any other grade, the request must carry a non-empty `override_reason` to justify the
        decision, and without one the attempt is `ERR_CORE_UNIT_INVALID_STATE`."

        Design: Corner/state_machines/core_scrap_cascades_order_cancellation_and_bench_release
        """
        world = setup_shop(account_code="SCP-001", customer_name="Scrap Mill",
                           asset_tag="SCP-01-GBX", serial_no="SN-SCP-1",
                           rebuild_count=1, declared_condition_grade="GRADE_D",
                           labor_hours=6.5, bench_code="B-SCP")
        inspect_order(world, measurements=(("BORE", 200),))
        quote_order(world)
        reservation = reserve_bench(world["order"]["id"], world["bench"]["id"],
                                    "2026-09-10T08:00:00Z", "2026-09-10T12:00:00Z")
        confirm_reservation(reservation["id"])

        assert read_bench(world["bench"]["id"])["committed_minutes"] == 240
        assert read_core(world["core"]["id"])["condition_grade"] == "SCRAP"

        scrapped = validate_success(api.advance_core_unit(
            world["core"]["id"], {"action": "SCRAP"}, ADMIN_1))
        assert scrapped["status"] == "SCRAPPED"
        assert scrapped["replacement_core_unit_id"] is None

        order = read_order(world["order"]["id"])
        assert order["work_status"] == "CANCELLED"
        assert order["cancel_reason"] == "core scrapped"

        rows, _ = validate_paginated(
            api.list_bench_reservations(world["bench"]["id"], PLANNER_1))
        assert rows[0]["status"] == "RELEASED"
        assert read_bench(world["bench"]["id"])["committed_minutes"] == 0

        assert read_customer(world["customer"]["id"])["core_credit_balance_cents"] == 0
        _, meta = credit_notes(core_unit_id=world["core"]["id"], status="POSTED")
        assert meta["total_count"] == 0
