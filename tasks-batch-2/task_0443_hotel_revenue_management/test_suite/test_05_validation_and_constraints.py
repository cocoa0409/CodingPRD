"""Validation precedence, cross-entity state dependencies, and business constraints.

Covers the ordered commit gating (state-before-oversell, los-before-oversell),
cross-entity gates (publish needs ACTIVE plan, evaluate needs inventory day),
uniqueness/fiscal/los validations, foreign-key resolution, and entity CRUD basics.
"""
from test_helpers import (
    validate_success,
    validate_error,
    validate_error_is_one_of,
    TEST_USERS,
    set_clock,
    create_property,
    create_room_type,
    create_rate_plan,
    create_inventory_day,
    create_rate_decision,
    create_group_block,
    create_competitor_rate,
    evaluate_group_block,
    commit_group_block,
    assert_competitor_rate,
    ApiErrorId,
    PLACEHOLDER_PROPERTY_ID,
    PLACEHOLDER_GENERIC_ID,
)

RM = TEST_USERS["revenue_manager_headers"]
GSM = TEST_USERS["group_sales_manager_headers"]
CM = TEST_USERS["channel_manager_headers"]
ANALYST = TEST_USERS["analyst_headers"]


class TestCommitGatingPrecedence:
    def test_state_check_before_oversell_on_recommit(self, api):
        """PRD §3.7: "It is gated in order: the block must be `NEGOTIATING`
        (otherwise `ERR_INVALID_STATE`); it must have been evaluated with an
        `ACCEPT` recommendation (an unevaluated block yields `ERR_NOT_EVALUATED`);
        ... and for every night the night's `rooms_available` after the oversell
        ceiling must be at least the block's `rooms_per_night`, otherwise the
        commit is rejected with `ERR_OVERSELL_LIMIT_EXCEEDED`."

        Design: Difficulty/priority_pair_validation_conflict/state_before_oversell_on_group_commit
        """
        set_clock("2026-06-01T00:00:00Z")
        prop = create_property(name="PriorityA", total_rooms=10)
        rt = create_room_type(prop["id"], code="KING", name="King", physical_rooms=10)
        create_inventory_day(rt["id"], "2026-06-09T00:00:00Z", physical_capacity=10, transient_sold_rooms=4)
        gb = create_group_block(
            rt["id"], "2026-06-09T00:00:00Z", group_name="Charlie",
            nights=1, rooms_per_night=5, offered_rate=400,
        )
        evaluate_group_block(gb["id"], "LRV")
        committed = commit_group_block(gb["id"], rt["version"])  # first commit succeeds (5 <= ceiling 10 - 4)
        rt_v1 = committed["version"]
        # second commit: block already COMMITTED AND a re-hold would exceed -> state check wins
        resp = api.commit_group_block(gb["id"], {"expected_room_type_version": rt_v1}, GSM)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    def test_state_before_oversell_leaves_block_committed(self, api):
        """PRD §3.7: "It is gated in order: the block must be `NEGOTIATING`
        (otherwise `ERR_INVALID_STATE`)."
        PRD §3.7: "A `COMMITTED` block goes `COMMITTED → CANCELLED`."

        Design: Difficulty/priority_pair_validation_conflict/state_before_oversell_on_group_commit
        """
        set_clock("2026-06-01T00:00:00Z")
        prop = create_property(name="PriorityA2", total_rooms=10)
        rt = create_room_type(prop["id"], code="KING", name="King", physical_rooms=10)
        create_inventory_day(rt["id"], "2026-06-09T00:00:00Z", physical_capacity=10, transient_sold_rooms=4)
        gb = create_group_block(rt["id"], "2026-06-09T00:00:00Z", group_name="Charlie", nights=1, rooms_per_night=5, offered_rate=400)
        evaluate_group_block(gb["id"], "LRV")
        committed = commit_group_block(gb["id"], rt["version"])
        api.commit_group_block(gb["id"], {"expected_room_type_version": committed["version"]}, GSM)  # rejected
        # the state-rejected re-commit must not alter the already-COMMITTED block
        gb_after = validate_success(api.get_group_block(gb["id"], GSM))
        assert gb_after["status"] == "COMMITTED", f"expected COMMITTED got {gb_after['status']}"

    def test_los_check_before_oversell_on_commit(self, api):
        """PRD §3.7: "if the room type has a master BAR plan, the block's `nights`
        must satisfy that plan's length-of-stay band — at least its `min_los`, and
        where its `max_los` is positive at most that `max_los` — with a violation
        rejected as `ERR_LOS_VIOLATION` ... and for every night the night's
        `rooms_available` after the oversell ceiling must be at least the block's
        `rooms_per_night`, otherwise the commit is rejected with
        `ERR_OVERSELL_LIMIT_EXCEEDED`."

        Design: Difficulty/priority_pair_validation_conflict/los_before_oversell_on_group_commit
        """
        set_clock("2026-06-01T00:00:00Z")
        prop = create_property(name="PriorityB", total_rooms=10)
        rt = create_room_type(prop["id"], code="KING", name="King", physical_rooms=10)
        create_rate_plan(
            rt["id"], rate_class="BAR", is_master_bar=True, min_los=3,
            base_rate=200, floor_rate=100, ceiling_rate=400,
        )
        create_inventory_day(rt["id"], "2026-06-10T00:00:00Z", physical_capacity=10, transient_sold_rooms=9)
        create_inventory_day(rt["id"], "2026-06-11T00:00:00Z", physical_capacity=10, transient_sold_rooms=9)
        rt_fresh = validate_success(api.get_room_type(rt["id"], RM))
        gb = create_group_block(
            rt["id"], "2026-06-10T00:00:00Z", group_name="Delta",
            nights=2, rooms_per_night=5, offered_rate=400,
        )
        evaluate_group_block(gb["id"], "LRV")
        # nights=2 < min_los=3 (LOS violation) AND 5 > available 1 (oversell) -> LOS wins
        resp = api.commit_group_block(gb["id"], {"expected_room_type_version": rt_fresh["version"]}, GSM)
        validate_error(resp, ApiErrorId.ERR_LOS_VIOLATION.value)

    def test_los_rejected_commit_leaves_block_uncommitted(self, api):
        """PRD §3.7: "if the room type has a master BAR plan, the block's `nights`
        must satisfy that plan's length-of-stay band — at least its `min_los`, and
        where its `max_los` is positive at most that `max_los` — with a violation
        rejected as `ERR_LOS_VIOLATION`."
        PRD §3.7: "On a successful commit, each overlapping inventory day has its
        `group_held_rooms` increased by the block's `rooms_per_night`."

        Design: Difficulty/priority_pair_validation_conflict/los_before_oversell_on_group_commit
        """
        set_clock("2026-06-01T00:00:00Z")
        prop = create_property(name="PriorityB2", total_rooms=10)
        rt = create_room_type(prop["id"], code="KING", name="King", physical_rooms=10)
        create_rate_plan(rt["id"], rate_class="BAR", is_master_bar=True, min_los=3, base_rate=200, floor_rate=100, ceiling_rate=400)
        inv1 = create_inventory_day(rt["id"], "2026-06-10T00:00:00Z", physical_capacity=10, transient_sold_rooms=9)
        create_inventory_day(rt["id"], "2026-06-11T00:00:00Z", physical_capacity=10, transient_sold_rooms=9)
        rt_fresh = validate_success(api.get_room_type(rt["id"], RM))
        gb = create_group_block(rt["id"], "2026-06-10T00:00:00Z", group_name="Delta", nights=2, rooms_per_night=5, offered_rate=400)
        evaluate_group_block(gb["id"], "LRV")
        api.commit_group_block(gb["id"], {"expected_room_type_version": rt_fresh["version"]}, GSM)  # rejected (LOS)
        # the LOS-rejected commit must hold no rooms on the first night
        inv_after = validate_success(api.get_inventory_day(inv1["id"], RM))
        assert inv_after["group_held_rooms"] == 0, f"expected 0 held got {inv_after['group_held_rooms']}"


class TestCrossEntityStateDependency:
    def test_publish_on_closed_plan_rejected(self, api):
        """PRD §3.2: "When a plan moves `ACTIVE → CLOSED`, every rate decision still
        in `DRAFT` on that plan is cascaded to `REJECTED` with its `reject_reason`
        set to "plan closed", and the closing plan's `version` increments by 1."
        PRD §3.4: "the plan must be `ACTIVE`, otherwise `ERR_PLAN_CLOSED`."
        PRD §3.4: "the decision must be in `DRAFT` state, otherwise
        `ERR_INVALID_STATE`."

        Design: Difficulty/cross_entity_state_dependency/publish_requires_active_rate_plan
        """
        set_clock("2026-06-01T00:00:00Z")
        prop = create_property(name="CrossA", total_rooms=40)
        rt = create_room_type(prop["id"], code="KING", name="King", physical_rooms=40)
        plan = create_rate_plan(
            rt["id"], rate_class="BAR", is_master_bar=True,
            base_rate=200, floor_rate=100, ceiling_rate=400,
        )
        create_inventory_day(rt["id"], "2026-06-14T00:00:00Z", physical_capacity=40, transient_sold_rooms=10)
        dec = create_rate_decision(plan["id"], "2026-06-14T00:00:00Z", requested_rate=200)
        closed = validate_success(api.close_rate_plan(plan["id"], RM))
        plan_v2 = closed["version"]

        resp = api.publish_rate_decision(dec["id"], {"expected_rate_plan_version": plan_v2}, RM)
        validate_error_is_one_of(
            resp, [ApiErrorId.ERR_INVALID_STATE.value, ApiErrorId.ERR_PLAN_CLOSED.value]
        )
        dec_after = validate_success(api.get_rate_decision(dec["id"], RM))
        assert dec_after["status"] == "REJECTED", (
            f"close cascade must reject the DRAFT decision, got {dec_after['status']}"
        )

    def test_publish_on_closed_plan_does_not_change_published_rate(self, api):
        """PRD §3.2: "A `CLOSED` plan accepts no new rate-decision creation and no
        publish."
        PRD §3.2: "At creation a plan's `status` is `ACTIVE`, its `published_rate`
        is null until the first publish sets it, and its `version` is 1."

        Design: Difficulty/cross_entity_state_dependency/publish_requires_active_rate_plan
        """
        set_clock("2026-06-01T00:00:00Z")
        prop = create_property(name="CrossA2", total_rooms=40)
        rt = create_room_type(prop["id"], code="KING", name="King", physical_rooms=40)
        plan = create_rate_plan(rt["id"], rate_class="BAR", is_master_bar=True, base_rate=200, floor_rate=100, ceiling_rate=400)
        create_inventory_day(rt["id"], "2026-06-14T00:00:00Z", physical_capacity=40, transient_sold_rooms=10)
        dec = create_rate_decision(plan["id"], "2026-06-14T00:00:00Z", requested_rate=200)
        closed = validate_success(api.close_rate_plan(plan["id"], RM))
        api.publish_rate_decision(dec["id"], {"expected_rate_plan_version": closed["version"]}, RM)  # rejected
        # the failed publish on a CLOSED plan must not set published_rate (it stays null)
        plan_after = validate_success(api.get_rate_plan(plan["id"], RM))
        assert plan_after["published_rate"] is None, (
            f"publish on a closed plan must not set published_rate, got {plan_after['published_rate']}"
        )

    def test_evaluate_with_missing_inventory_day_rejected(self, api):
        """PRD §3.7: "Evaluation requires an inventory day to exist for every night
        in the block's window (from `arrival_date` through the night before
        `arrival_date` plus `nights`); a missing night is rejected with
        `ERR_MISSING_INVENTORY_DAY`."

        Design: Difficulty/cross_entity_state_dependency/group_commit_requires_inventory_day_present
        """
        set_clock("2026-06-01T00:00:00Z")
        prop = create_property(name="CrossB", total_rooms=20)
        rt = create_room_type(prop["id"], code="KING", name="King", physical_rooms=20)
        create_inventory_day(rt["id"], "2026-06-15T00:00:00Z", physical_capacity=20, transient_sold_rooms=5)
        # No InventoryDay for 2026-06-16
        gb = create_group_block(
            rt["id"], "2026-06-15T00:00:00Z", group_name="Foxtrot",
            nights=2, rooms_per_night=3, offered_rate=300,
        )
        resp = api.evaluate_group_block(gb["id"], {"method": "LRV"}, RM)
        validate_error(resp, ApiErrorId.ERR_MISSING_INVENTORY_DAY.value)

    def test_evaluate_missing_inventory_leaves_block_unevaluated(self, api):
        """PRD §3.7: "Evaluation requires an inventory day to exist for every night
        in the block's window (from `arrival_date` through the night before
        `arrival_date` plus `nights`); a missing night is rejected with
        `ERR_MISSING_INVENTORY_DAY`."
        PRD §3.7: "A block is born `NEGOTIATING` with its `displacement_cost` and
        `recommendation` null and its `version` 1."

        Design: Difficulty/cross_entity_state_dependency/group_commit_requires_inventory_day_present
        """
        set_clock("2026-06-01T00:00:00Z")
        prop = create_property(name="CrossB2", total_rooms=20)
        rt = create_room_type(prop["id"], code="KING", name="King", physical_rooms=20)
        create_inventory_day(rt["id"], "2026-06-15T00:00:00Z", physical_capacity=20, transient_sold_rooms=5)
        # No InventoryDay for 2026-06-16
        gb = create_group_block(rt["id"], "2026-06-15T00:00:00Z", group_name="Foxtrot", nights=2, rooms_per_night=3, offered_rate=300)
        api.evaluate_group_block(gb["id"], {"method": "LRV"}, RM)  # rejected
        # the failed evaluation must leave displacement_cost null and the block NEGOTIATING
        gb_after = validate_success(api.get_group_block(gb["id"], GSM))
        assert gb_after["displacement_cost"] is None
        assert gb_after["status"] == "NEGOTIATING", f"expected NEGOTIATING got {gb_after['status']}"


class TestUniquenessAndFiscalValidations:
    def test_duplicate_room_type_code_rejected(self, api):
        """PRD §3.1: "If a second room type is created with a `code` already used
        inside the same property, the request is rejected with
        `ERR_DUPLICATE_ROOM_TYPE_CODE`."

        Design: Corner/validations/duplicate_room_type_code_returns_409
        """
        prop = create_property(name="DupCode", total_rooms=40)
        create_room_type(prop["id"], code="KING", name="King", physical_rooms=20)
        resp = api.create_room_type(
            {"property_id": prop["id"], "code": "KING", "name": "King Two", "physical_rooms": 20}, RM
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_ROOM_TYPE_CODE.value)

    def test_second_master_bar_rejected(self, api):
        """PRD §3.2: "At most one plan per room type may carry `is_master_bar` true;
        a second master-BAR plan on the same room type is rejected with
        `ERR_MASTER_BAR_EXISTS`."

        Design: Corner/validations/second_master_bar_returns_409
        """
        prop = create_property(name="TwoMaster", total_rooms=40)
        rt = create_room_type(prop["id"], code="KING", name="King", physical_rooms=40)
        create_rate_plan(rt["id"], rate_class="BAR", is_master_bar=True, base_rate=200, floor_rate=100, ceiling_rate=400)
        resp = api.create_rate_plan(
            {"room_type_id": rt["id"], "rate_class": "BAR", "is_master_bar": True,
             "base_rate": 210, "floor_rate": 100, "ceiling_rate": 400}, RM
        )
        validate_error(resp, ApiErrorId.ERR_MASTER_BAR_EXISTS.value)

    def test_create_decision_on_closed_plan_rejected(self, api):
        """PRD §3.4: "Creation is gated two ways: the underlying plan must be
        `ACTIVE`, and a create against a `CLOSED` plan is rejected with
        `ERR_PLAN_CLOSED`."

        Design: Corner/validations/create_rate_decision_on_closed_plan_returns_plan_closed
        """
        prop = create_property(name="ClosedCreate", total_rooms=40)
        rt = create_room_type(prop["id"], code="KING", name="King", physical_rooms=40)
        plan = create_rate_plan(rt["id"], rate_class="BAR", is_master_bar=True, base_rate=200, floor_rate=100, ceiling_rate=400)
        validate_success(api.close_rate_plan(plan["id"], RM))
        resp = api.create_rate_decision(
            {"rate_plan_id": plan["id"], "stay_date": "2026-06-05T00:00:00Z", "requested_rate": 200}, RM
        )
        validate_error(resp, ApiErrorId.ERR_PLAN_CLOSED.value)

    def test_group_commit_below_min_los_rejected(self, api):
        """PRD §3.7: "if the room type has a master BAR plan, the block's `nights`
        must satisfy that plan's length-of-stay band — at least its `min_los`, and
        where its `max_los` is positive at most that `max_los` — with a violation
        rejected as `ERR_LOS_VIOLATION`."

        Design: Corner/validations/group_block_los_below_min_returns_los_violation
        """
        set_clock("2026-06-01T00:00:00Z")
        prop = create_property(name="LosCheck", total_rooms=30)
        rt = create_room_type(prop["id"], code="KING", name="King", physical_rooms=30)
        create_rate_plan(rt["id"], rate_class="BAR", is_master_bar=True, min_los=3, base_rate=200, floor_rate=100, ceiling_rate=400)
        create_inventory_day(rt["id"], "2026-06-06T00:00:00Z", physical_capacity=30, transient_sold_rooms=2)
        rt_fresh = validate_success(api.get_room_type(rt["id"], RM))
        gb = create_group_block(
            rt["id"], "2026-06-06T00:00:00Z", group_name="Papa",
            nights=1, rooms_per_night=2, offered_rate=300,
        )
        evaluate_group_block(gb["id"], "LRV")
        resp = api.commit_group_block(gb["id"], {"expected_room_type_version": rt_fresh["version"]}, GSM)
        validate_error(resp, ApiErrorId.ERR_LOS_VIOLATION.value)

    def test_invalid_los_band_on_rate_plan_rejected(self, api):
        """PRD §3.2: "A plan whose `max_los` is greater than 0 must also satisfy
        `max_los` being at least `min_los`; a plan that names a positive `max_los`
        smaller than its `min_los` is rejected with `ERR_INVALID_LOS_BAND`."

        Design: Corner/errors/invalid_los_band_on_rate_plan_create_returns_422
        """
        prop = create_property(name="BadLos", total_rooms=30)
        rt = create_room_type(prop["id"], code="KING", name="King", physical_rooms=30)
        resp = api.create_rate_plan(
            {"room_type_id": rt["id"], "rate_class": "BAR", "min_los": 3, "max_los": 2,
             "base_rate": 200, "floor_rate": 100, "ceiling_rate": 400}, RM
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_LOS_BAND.value)

    def test_rate_below_floor_on_decision_create_rejected(self, api):
        """PRD §3.4: "the `requested_rate` must be at least the plan's `floor_rate`,
        with a below-floor request rejected up front, before any yield computation,
        with `ERR_RATE_BELOW_FLOOR`."

        Design: Corner/errors/rate_below_floor_on_decision_create_returns_422
        """
        prop = create_property(name="BelowFloor", total_rooms=30)
        rt = create_room_type(prop["id"], code="KING", name="King", physical_rooms=30)
        plan = create_rate_plan(rt["id"], rate_class="BAR", is_master_bar=True, base_rate=200, floor_rate=100, ceiling_rate=400)
        resp = api.create_rate_decision(
            {"rate_plan_id": plan["id"], "stay_date": "2026-06-06T00:00:00Z", "requested_rate": 80}, RM
        )
        validate_error(resp, ApiErrorId.ERR_RATE_BELOW_FLOOR.value)

    def test_confirm_before_publish_rejected(self, api):
        """PRD §3.9: "its plan must be `ACTIVE` and must already have a non-null
        published rate, since a confirm without a published rate is rejected with
        `ERR_RATE_NOT_PUBLISHED`."

        Design: Corner/errors/confirm_transient_before_publish_returns_rate_not_published
        """
        set_clock("2026-06-01T00:00:00Z")
        prop = create_property(name="NoPub", total_rooms=30)
        rt = create_room_type(prop["id"], code="KING", name="King", physical_rooms=30)
        plan = create_rate_plan(rt["id"], rate_class="BAR", is_master_bar=True, base_rate=200, floor_rate=100, ceiling_rate=400)
        create_inventory_day(rt["id"], "2026-06-06T00:00:00Z", physical_capacity=30, transient_sold_rooms=2)
        res = validate_success(
            api.create_transient_reservation(
                {"room_type_id": rt["id"], "rate_plan_id": plan["id"],
                 "arrival_date": "2026-06-06T00:00:00Z", "nights": 1, "rooms": 1}, RM
            ),
            expected_status=201,
        )
        resp = api.confirm_transient_reservation(res["id"], RM)
        validate_error(resp, ApiErrorId.ERR_RATE_NOT_PUBLISHED.value)


class TestUniquenessErrors:
    def test_duplicate_inventory_day_rejected(self, api):
        """PRD §3.1: "The system rejects a second inventory day for the same room
        type and stay date with `ERR_DUPLICATE_INVENTORY_DAY`."

        Design: Corner/errors/duplicate_inventory_day_returns_409
        """
        prop = create_property(name="DupInv", total_rooms=30)
        rt = create_room_type(prop["id"], code="KING", name="King", physical_rooms=30)
        create_inventory_day(rt["id"], "2026-06-06T00:00:00Z", physical_capacity=30, transient_sold_rooms=2)
        resp = api.create_inventory_day(
            {"room_type_id": rt["id"], "stay_date": "2026-06-06T00:00:00Z",
             "physical_capacity": 30, "transient_sold_rooms": 0}, RM
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_INVENTORY_DAY.value)

    def test_duplicate_channel_mapping_rejected(self, api):
        """PRD §3.5: "At most one mapping may exist per plan and channel; a
        duplicate is rejected with `ERR_CHANNEL_ALREADY_MAPPED`."

        Design: Corner/errors/channel_already_mapped_returns_409
        """
        prop = create_property(name="DupChan", total_rooms=30)
        rt = create_room_type(prop["id"], code="KING", name="King", physical_rooms=30)
        plan = create_rate_plan(rt["id"], rate_class="BAR", is_master_bar=True, base_rate=200, floor_rate=100, ceiling_rate=400)
        validate_success(
            api.create_channel_mapping({"rate_plan_id": plan["id"], "channel": "DIRECT", "markup_pct": 0.0}, CM),
            expected_status=201,
        )
        resp = api.create_channel_mapping({"rate_plan_id": plan["id"], "channel": "DIRECT", "markup_pct": 0.0}, CM)
        validate_error(resp, ApiErrorId.ERR_CHANNEL_ALREADY_MAPPED.value)

    def test_fk_not_found_on_room_type_create(self, api):
        """PRD §2.5: "For write requests that carry foreign keys in the body, the
        system confirms those references resolve to existing resources in the same
        property scope; an unresolvable or cross-property `property_id`,
        `room_type_id`, or `rate_plan_id` is rejected with `ERR_FK_NOT_FOUND`."

        Design: Corner/errors/fk_not_found_on_room_type_create_returns_422
        """
        resp = api.create_room_type(
            {"property_id": PLACEHOLDER_PROPERTY_ID, "code": "KING", "name": "King", "physical_rooms": 10}, RM
        )
        validate_error(resp, ApiErrorId.ERR_FK_NOT_FOUND.value)


class TestStateMachineGuards:
    def test_close_plan_cascades_draft_to_rejected(self, api):
        """PRD §3.2: "When a plan moves `ACTIVE → CLOSED`, every rate decision still
        in `DRAFT` on that plan is cascaded to `REJECTED` with its `reject_reason`
        set to "plan closed", and the closing plan's `version` increments by 1."

        Design: Corner/state_machines/close_plan_rejects_draft_decisions_cascade
        """
        prop = create_property(name="CloseCasc", total_rooms=40)
        rt = create_room_type(prop["id"], code="KING", name="King", physical_rooms=40)
        plan = create_rate_plan(rt["id"], rate_class="BAR", is_master_bar=True, base_rate=200, floor_rate=100, ceiling_rate=400)
        dec = create_rate_decision(plan["id"], "2026-06-05T00:00:00Z", requested_rate=200)
        closed = validate_success(api.close_rate_plan(plan["id"], RM))
        assert closed["status"] == "CLOSED"
        dec_after = validate_success(api.get_rate_decision(dec["id"], RM))
        assert dec_after["status"] == "REJECTED"
        assert dec_after["reject_reason"] == "plan closed", (
            f"expected reject_reason 'plan closed' got {dec_after['reject_reason']!r}"
        )

    def test_cancel_already_cancelled_block_rejected(self, api):
        """PRD §3.7: "Cancelling a block is also a `GroupSalesManager` action and
        behaves by current state."
        PRD §3.7: "A `COMMITTED` block goes `COMMITTED → CANCELLED`."
        PRD §2.9: "a target's state legality is established before
        inventory-dependent and concurrency checks for that same transition."

        Design: Corner/state_machines/cancel_already_cancelled_committed_block_returns_invalid_state
        """
        set_clock("2026-06-01T00:00:00Z")
        prop = create_property(name="TermLock", total_rooms=20)
        rt = create_room_type(prop["id"], code="KING", name="King", physical_rooms=20)
        create_inventory_day(rt["id"], "2026-06-05T00:00:00Z", physical_capacity=20, transient_sold_rooms=2)
        gb = create_group_block(
            rt["id"], "2026-06-05T00:00:00Z", group_name="November",
            nights=1, rooms_per_night=3, offered_rate=400,
        )
        evaluate_group_block(gb["id"], "LRV")
        commit_group_block(gb["id"], rt["version"])
        validate_success(api.cancel_group_block(gb["id"], GSM))  # COMMITTED -> CANCELLED
        resp = api.cancel_group_block(gb["id"], GSM)  # already CANCELLED (terminal)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


class TestEntityCrud:
    def test_create_property_returns_201_with_zero_kpis(self, api):
        """PRD §3.1: "At creation the property's three KPI fields —
        `occupancy_pct`, `adr`, and `revpar` — are initialized to 0 and its
        `version` to 1."

        Design: Corner/entities/create_property_returns_201_with_all_fields
        """
        set_clock("2026-01-01T00:00:00Z")
        data = validate_success(
            api.create_property({"name": "Hotel One", "total_rooms": 100}, RM), expected_status=201
        )
        assert data["version"] == 1
        assert data["occupancy_pct"] == 0
        assert data["adr"] == 0
        assert data["revpar"] == 0

    def test_get_property_not_found(self, api):
        """PRD §2.5: "For requests that name a resource by `id` in the URL, the
        system first confirms that the addressed resource exists before applying
        any business rule, rejecting an unknown `id` with `ERR_NOT_FOUND`."

        Design: Corner/entities/get_property_not_found_returns_404
        """
        resp = api.get_property(PLACEHOLDER_GENERIC_ID, RM)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)

    def test_create_property_missing_total_rooms_rejected(self, api):
        """PRD §2.9: "Request-body well-formedness is checked fourth — required
        fields present, enums drawn from their permitted sets, numeric ranges
        respected (a plan's `ceiling_rate` at least its `floor_rate`, a property's
        `overbooking_limit_pct` within its band, counts at least 1) — yielding
        `ERR_INVALID_REQUEST` on failure."

        Design: Corner/entities/create_property_missing_required_total_rooms_returns_422
        """
        resp = api.create_property({"name": "NoRooms"}, RM)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)

    def test_create_property_overbooking_defaults_zero(self, api):
        """PRD §2.7: "This fraction must be at least 0 and at most 0.30, and it
        defaults to 0.0 (no oversell) when omitted."

        Design: Corner/entities/create_property_overbooking_default_zero
        """
        data = validate_success(
            api.create_property({"name": "DefaultOver", "total_rooms": 50}, RM), expected_status=201
        )
        assert data["overbooking_limit_pct"] == 0.0

    def test_rate_plan_ceiling_below_floor_rejected(self, api):
        """PRD §2.9: "Request-body well-formedness is checked fourth — required
        fields present, enums drawn from their permitted sets, numeric ranges
        respected (a plan's `ceiling_rate` at least its `floor_rate`, a property's
        `overbooking_limit_pct` within its band, counts at least 1) — yielding
        `ERR_INVALID_REQUEST` on failure."

        Design: Corner/entities/rate_plan_ceiling_below_floor_returns_422
        """
        prop = create_property(name="BadBand", total_rooms=40)
        rt = create_room_type(prop["id"], code="KING", name="King", physical_rooms=40)
        resp = api.create_rate_plan(
            {"room_type_id": rt["id"], "rate_class": "BAR",
             "base_rate": 200, "floor_rate": 300, "ceiling_rate": 250}, RM
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)

    def test_rate_plan_invalid_rate_class_enum_rejected(self, api):
        """PRD §2.9: "Request-body well-formedness is checked fourth — required
        fields present, enums drawn from their permitted sets, numeric ranges
        respected (a plan's `ceiling_rate` at least its `floor_rate`, a property's
        `overbooking_limit_pct` within its band, counts at least 1) — yielding
        `ERR_INVALID_REQUEST` on failure."

        Design: Corner/entities/rate_plan_invalid_rate_class_enum_returns_422
        """
        prop = create_property(name="EnumP", total_rooms=40)
        rt = create_room_type(prop["id"], code="KING", name="King", physical_rooms=40)
        resp = api.create_rate_plan(
            {"room_type_id": rt["id"], "rate_class": "SUPER",
             "base_rate": 200, "floor_rate": 100, "ceiling_rate": 400}, RM
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)

    def test_competitor_rate_is_immutable_snapshot(self, api):
        """PRD §3.10: "A snapshot is immutable once recorded: it carries only `id`
        and `created_at`, with no later mutation."

        Design: Corner/entities/competitor_rate_immutable_no_update_endpoint
        """
        prop = create_property(name="Shop", total_rooms=40)
        cr = create_competitor_rate(
            prop["id"], competitor_name="Rival", stay_date="2026-06-05T00:00:00Z",
            shopped_rate=199.0, shopped_at="2026-06-01T08:00:00Z",
        )
        data = validate_success(api.get_competitor_rate(cr["id"], ANALYST))
        assert data["shopped_rate"] == 199.0
        assert_competitor_rate(data)  # asserts no version / no updated_at


class TestExistencePrecedence:
    def test_publish_unknown_decision_returns_not_found(self, api):
        """PRD §2.9: "Existence of any resource named by `id` in the URL is checked
        third, yielding `ERR_NOT_FOUND`."

        Design: Corner/validations/existence_before_state_on_publish_unknown_decision
        """
        prop = create_property(name="ExistFirst", total_rooms=40)
        rt = create_room_type(prop["id"], code="KING", name="King", physical_rooms=40)
        plan = create_rate_plan(rt["id"], rate_class="BAR", is_master_bar=True, base_rate=200, floor_rate=100, ceiling_rate=400)
        resp = api.publish_rate_decision(
            "22222222-2222-2222-2222-222222222222", {"expected_rate_plan_version": plan["version"]}, RM
        )
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)
