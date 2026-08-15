"""Pick list lifecycle: state guards, picking, mark-short, substitution, cancel."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_card_line,
    api_client,
    get_success_data,
    make_case,
    make_draft_card,
    make_published_card,
    make_supply_item,
    make_surgeon,
    publish_card,
    release_pick_list,
    setup_released_case,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    validate_success,
)

ANALYST = TEST_USERS["analyst_headers"]
CART = TEST_USERS["cart_tech_headers"]
ANY = TEST_USERS["any_headers"]


def _glove(**kw):
    defaults = dict(sku="GLOVE-PR", name="Gloves pair", unit_cost_cents=250,
                    substitute_group="GLOVES", initial_on_hand=100)
    defaults.update(kw)
    return make_supply_item(**defaults)


def _simple_case(surgeon_name="Dr. T", room="OR-1", start="2026-09-05T08:00:00Z",
                 quantity=1, item=None):
    """Surgeon + 1-line card + case + released pick list. Returns ctx dict."""
    surgeon = make_surgeon(full_name=surgeon_name)
    item = item or _glove()
    card = make_published_card(surgeon["id"], "TKA",
                               [{"supply_item_id": item["id"],
                                 "quantity": quantity}])
    case = make_case(surgeon["id"], card["id"], scheduled_start=start,
                     expected_duration_min=60, room=room)
    pl, lines = release_pick_list(case["id"])
    return {"surgeon": surgeon, "item": item, "card": card, "case": case,
            "pick_list": pl, "lines": lines}


class TestReleaseAndBegin:
    def test_double_release_returns_error(self):
        """PRD §3.4: "A `SupplyChainAnalyst` may release only a `SCHEDULED`
        case (`ERR_CASE_NOT_SCHEDULED` otherwise) that does not yet have a pick
        list — exactly one pick list ever exists per case, and a second release
        is rejected with `ERR_PICK_LIST_EXISTS`"

        Design: Corner/state_machines/double_release_returns_pick_list_exists
        """
        ctx = _simple_case(surgeon_name="Dr. Dbl")
        resp = api_client.release_pick_list(ctx["case"]["id"], ANALYST)
        validate_error_is_one_of(
            resp,
            [ApiErrorId.ERR_CASE_NOT_SCHEDULED, ApiErrorId.ERR_PICK_LIST_EXISTS],
        )

    def test_begin_picking_twice_returns_invalid_state(self):
        """PRD §3.4: "A `CartTechnician` begins work by transitioning the list
        `GENERATED → IN_PICKING`; beginning from any other state is rejected
        with `ERR_PICK_LIST_INVALID_STATE`."

        Design: Corner/state_machines/begin_picking_twice_returns_invalid_state
        """
        ctx = _simple_case(surgeon_name="Dr. Twice")
        get_success_data(api_client.begin_picking(ctx["pick_list"]["id"], CART))
        resp = api_client.begin_picking(ctx["pick_list"]["id"], CART)
        validate_error(resp, ApiErrorId.ERR_PICK_LIST_INVALID_STATE)
        after = get_success_data(api_client.get_pick_list(ctx["pick_list"]["id"], ANY))
        assert after["status"] == "IN_PICKING"

    def test_dispatch_with_pending_lines_returns_invalid_state(self):
        """PRD §3.4: "A `CartTechnician` dispatches only a `STAGED` list
        (`ERR_PICK_LIST_INVALID_STATE`), moving it `STAGED → DISPATCHED`"

        Design: Corner/state_machines/dispatch_with_pending_lines_returns_invalid_state
        """
        ctx = _simple_case(surgeon_name="Dr. Early")
        get_success_data(api_client.begin_picking(ctx["pick_list"]["id"], CART))
        resp = api_client.dispatch_pick_list(ctx["pick_list"]["id"], CART)
        validate_error(resp, ApiErrorId.ERR_PICK_LIST_INVALID_STATE)
        pl_after = get_success_data(api_client.get_pick_list(ctx["pick_list"]["id"], ANY))
        assert pl_after["status"] == "IN_PICKING"
        case_after = get_success_data(api_client.get_case(ctx["case"]["id"], ANY))
        assert case_after["status"] == "PICKING_RELEASED"


class TestLineGuards:
    def test_mark_short_on_picked_line_rejected(self):
        """PRD §3.4: "the technician instead marks the line short ... under the
        same `PENDING`-line and list-state guards (`ERR_LINE_NOT_PENDING`,
        `ERR_PICK_LIST_INVALID_STATE`)."

        Design: Corner/state_machines/mark_short_on_picked_line_rejected
        """
        ctx = _simple_case(surgeon_name="Dr. Mark")
        get_success_data(api_client.begin_picking(ctx["pick_list"]["id"], CART))
        line = ctx["lines"][0]
        get_success_data(api_client.pick_line(line["id"], CART))
        resp = api_client.mark_short(line["id"], {"reason_code": "OUT_OF_STOCK"}, CART)
        validate_error(resp, ApiErrorId.ERR_LINE_NOT_PENDING)
        after = get_success_data(api_client.get_pick_list_line(line["id"], ANY))
        assert after["status"] == "PICKED"

    def test_pick_on_hand_exact_equality_boundary(self):
        """PRD §3.4: "the item's `on_hand_quantity` must be at least
        `qty_requested` — equality is sufficient — with shortfalls rejected as
        `ERR_INSUFFICIENT_STOCK`."

        Design: Difficulty/boundary_precision_check/pick_on_hand_exact_equality_boundary
        """
        surgeon = make_surgeon(full_name="Dr. Bound")
        item = make_supply_item(sku="SCALPEL-11", name="Scalpel 11",
                                unit_cost_cents=150, substitute_group="BLADE",
                                initial_on_hand=3)
        card = make_published_card(surgeon["id"], "EXCISION",
                                   [{"supply_item_id": item["id"], "quantity": 3}])
        case_1 = make_case(surgeon["id"], card["id"],
                           scheduled_start="2026-09-01T08:00:00Z",
                           expected_duration_min=30, room="OR-7")
        pl_1, lines_1 = release_pick_list(case_1["id"])
        get_success_data(api_client.begin_picking(pl_1["id"], CART))
        case_2 = make_case(surgeon["id"], card["id"],
                           scheduled_start="2026-09-01T10:00:00Z",
                           expected_duration_min=30, room="OR-8")
        pl_2, lines_2 = release_pick_list(case_2["id"])
        get_success_data(api_client.begin_picking(pl_2["id"], CART))

        # First pick: 3 <= 3 — equality is sufficient.
        ok = api_client.pick_line(lines_1[0]["id"], CART)
        picked = validate_success(ok)
        assert picked["status"] == "PICKED"
        assert picked["qty_picked"] == 3

        item_after = get_success_data(api_client.get_supply_item(item["id"], ANY))
        assert item_after["on_hand_quantity"] == 0

        # Second pick of the same item: 0 < 3.
        resp = api_client.pick_line(lines_2[0]["id"], CART)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_STOCK)
        line2_after = get_success_data(
            api_client.get_pick_list_line(lines_2[0]["id"], ANY)
        )
        assert line2_after["status"] == "PENDING"


class TestSubstitution:
    def _short_line_setup(self, surgeon_name="Dr. Grp"):
        surgeon = make_surgeon(full_name=surgeon_name)
        tray = make_supply_item(sku="TRAY-STD", name="Standard tray",
                                unit_cost_cents=2000, substitute_group="TRAY",
                                initial_on_hand=0)
        clamp = make_supply_item(sku="CLAMP-9", name="Clamp",
                                 unit_cost_cents=1500, substitute_group="CLAMP",
                                 initial_on_hand=5)
        card = make_published_card(surgeon["id"], "ORIF",
                                   [{"supply_item_id": tray["id"], "quantity": 1}])
        case = make_case(surgeon["id"], card["id"],
                         scheduled_start="2026-09-05T08:00:00Z",
                         expected_duration_min=60, room="OR-1")
        pl, lines = release_pick_list(case["id"])
        get_success_data(api_client.begin_picking(pl["id"], CART))
        get_success_data(
            api_client.mark_short(lines[0]["id"], {"reason_code": "OUT_OF_STOCK"}, CART)
        )
        return {"surgeon": surgeon, "tray": tray, "clamp": clamp, "case": case,
                "pick_list": pl, "line": lines[0]}

    def test_substitute_wrong_group_rejected(self):
        """PRD §3.4: "The substitute's `substitute_group` must be non-null and
        equal to the planned item's `substitute_group`
        (`ERR_SUBSTITUTE_GROUP_MISMATCH`)"

        Design: Corner/state_machines/substitute_wrong_group_rejected
        """
        ctx = self._short_line_setup()
        resp = api_client.substitute_line(
            ctx["line"]["id"],
            {"substitute_supply_item_id": ctx["clamp"]["id"]},
            CART,
        )
        validate_error(resp, ApiErrorId.ERR_SUBSTITUTE_GROUP_MISMATCH)
        line_after = get_success_data(
            api_client.get_pick_list_line(ctx["line"]["id"], ANY)
        )
        assert line_after["status"] == "SHORT"
        clamp_after = get_success_data(api_client.get_supply_item(ctx["clamp"]["id"], ANY))
        assert clamp_after["on_hand_quantity"] == 5

    def test_substitute_state_beats_safety(self):
        """PRD §2.7: the fixed global validation order evaluates "**Target
        state**" (priority 5) before "**Clinical safety business rules**"
        (priority 7); PRD §3.4: substitution requires a `SHORT` line
        (`ERR_LINE_NOT_SHORT`) before group compatibility is checked
        (`ERR_SUBSTITUTE_GROUP_MISMATCH`).

        Design: Difficulty/priority_pair_validation_conflict/substitute_state_beats_safety
        """
        surgeon = make_surgeon(full_name="Dr. Prio")
        tray = make_supply_item(sku="TRAY-STD", name="Standard tray",
                                unit_cost_cents=2000, substitute_group="TRAY",
                                initial_on_hand=5)
        clamp = make_supply_item(sku="CLAMP-9", name="Clamp",
                                 unit_cost_cents=1500, substitute_group="CLAMP",
                                 initial_on_hand=5)
        card = make_published_card(surgeon["id"], "ORIF",
                                   [{"supply_item_id": tray["id"], "quantity": 1}])
        case = make_case(surgeon["id"], card["id"],
                         scheduled_start="2026-09-01T08:00:00Z",
                         expected_duration_min=90, room="OR-4")
        pl, lines = release_pick_list(case["id"])
        get_success_data(api_client.begin_picking(pl["id"], CART))
        # Line remains PENDING (never marked short) AND the substitute is the
        # wrong group — state (priority 5) must fire first.
        resp = api_client.substitute_line(
            lines[0]["id"], {"substitute_supply_item_id": clamp["id"]}, CART
        )
        validate_error(resp, ApiErrorId.ERR_LINE_NOT_SHORT)
        line_after = get_success_data(api_client.get_pick_list_line(lines[0]["id"], ANY))
        assert line_after["status"] == "PENDING"
        clamp_after = get_success_data(api_client.get_supply_item(clamp["id"], ANY))
        assert clamp_after["on_hand_quantity"] == 5

    def test_pick_list_exception_cycle(self):
        """PRD §3.4: "Marking short moves the line `PENDING → SHORT` and
        pushes the list `IN_PICKING → PICKING_EXCEPTION` — a no-op if the list
        is already in exception. ... When the substitution clears the last
        `SHORT` line, the list returns `PICKING_EXCEPTION → IN_PICKING`; if at
        that point no `PENDING` lines remain either, the list continues
        automatically into `STAGED`."
        PRD §3.4: "Substitution sets `qty_picked` to `qty_requested` drawn from
        the substitute's stock, decrements the substitute's `on_hand_quantity`
        accordingly, re-snapshots the line's `unit_cost_cents` from the
        substitute item, records `substituted_item_id`, and moves the line
        `SHORT → SUBSTITUTED`."

        Design: Difficulty/non_linear_state_machine/pick_list_exception_cycle
        """
        surgeon = make_surgeon(full_name="Dr. Cycle")
        tray_std = make_supply_item(sku="TRAY-STD", name="Standard tray",
                                    unit_cost_cents=2000, substitute_group="TRAY",
                                    initial_on_hand=0)
        tray_alt = make_supply_item(sku="TRAY-ALT", name="Alternate tray",
                                    unit_cost_cents=2200, substitute_group="TRAY",
                                    initial_on_hand=5)
        glove = _glove()
        card = make_published_card(
            surgeon["id"], "ORIF",
            [{"supply_item_id": tray_std["id"], "quantity": 2,
              "designation": "OPEN", "pick_sequence": 1},
             {"supply_item_id": glove["id"], "quantity": 1,
              "designation": "OPEN", "pick_sequence": 2}],
        )
        case = make_case(surgeon["id"], card["id"],
                         scheduled_start="2026-09-01T08:00:00Z",
                         expected_duration_min=90, room="OR-4")
        pl, lines = release_pick_list(case["id"])
        line_x, line_a = lines[0], lines[1]
        get_success_data(api_client.begin_picking(pl["id"], CART))

        get_success_data(
            api_client.mark_short(line_x["id"], {"reason_code": "OUT_OF_STOCK"}, CART)
        )
        st_exc = get_success_data(api_client.get_pick_list(pl["id"], ANY))["status"]
        assert st_exc == "PICKING_EXCEPTION"

        sub = api_client.substitute_line(
            line_x["id"], {"substitute_supply_item_id": tray_alt["id"]}, CART
        )
        sub_line = validate_success(sub)
        assert sub_line["status"] == "SUBSTITUTED"
        assert sub_line["qty_picked"] == 2
        assert sub_line["unit_cost_cents"] == 2200
        st_back = get_success_data(api_client.get_pick_list(pl["id"], ANY))["status"]
        assert st_back == "IN_PICKING"

        get_success_data(api_client.pick_line(line_a["id"], CART))
        st_final = get_success_data(api_client.get_pick_list(pl["id"], ANY))["status"]
        assert st_final == "STAGED"

        alt_after = get_success_data(api_client.get_supply_item(tray_alt["id"], ANY))
        assert alt_after["on_hand_quantity"] == 3
        case_after = get_success_data(api_client.get_case(case["id"], ANY))
        assert case_after["pick_exception_count"] == 1

    def test_substitute_price_threshold_boundary_and_override(self):
        """PRD §3.4: "the substitute's `unit_cost_cents` may not exceed 1.25
        times the planned line's current snapshot `unit_cost_cents` — a
        substitute costing exactly 1.25 times as much is allowed — unless the
        request sets `override_price_threshold` to true; an unoverridden breach
        is rejected with `ERR_SUBSTITUTE_PRICE_THRESHOLD` (HTTP 402)."

        Design: Corner/validations/substitute_price_threshold_boundary_and_override
        """
        surgeon = make_surgeon(full_name="Dr. Price")
        tray = make_supply_item(sku="TRAY-STD", name="Standard tray",
                                unit_cost_cents=2000, substitute_group="TRAY",
                                initial_on_hand=0)
        edge = make_supply_item(sku="TRAY-EDGE", name="Edge tray",
                                unit_cost_cents=2500, substitute_group="TRAY",
                                initial_on_hand=5)
        prm = make_supply_item(sku="TRAY-PRM", name="Premium tray",
                               unit_cost_cents=2600, substitute_group="TRAY",
                               initial_on_hand=5)
        card = make_published_card(surgeon["id"], "ORIF",
                                   [{"supply_item_id": tray["id"], "quantity": 1}])

        # Case 1: over-threshold without override, then exactly-1.25x allowed.
        case_1 = make_case(surgeon["id"], card["id"],
                           scheduled_start="2026-09-05T08:00:00Z",
                           expected_duration_min=60, room="OR-1")
        pl_1, lines_1 = release_pick_list(case_1["id"])
        get_success_data(api_client.begin_picking(pl_1["id"], CART))
        get_success_data(api_client.mark_short(
            lines_1[0]["id"], {"reason_code": "OUT_OF_STOCK"}, CART))

        resp = api_client.substitute_line(
            lines_1[0]["id"], {"substitute_supply_item_id": prm["id"]}, CART
        )
        validate_error(resp, ApiErrorId.ERR_SUBSTITUTE_PRICE_THRESHOLD)

        ok = api_client.substitute_line(
            lines_1[0]["id"], {"substitute_supply_item_id": edge["id"]}, CART
        )
        assert validate_success(ok)["status"] == "SUBSTITUTED"

        # Case 2: over-threshold with override succeeds.
        case_2 = make_case(surgeon["id"], card["id"],
                           scheduled_start="2026-09-05T10:30:00Z",
                           expected_duration_min=60, room="OR-2")
        pl_2, lines_2 = release_pick_list(case_2["id"])
        get_success_data(api_client.begin_picking(pl_2["id"], CART))
        get_success_data(api_client.mark_short(
            lines_2[0]["id"], {"reason_code": "OUT_OF_STOCK"}, CART))
        ok2 = api_client.substitute_line(
            lines_2[0]["id"],
            {"substitute_supply_item_id": prm["id"],
             "override_price_threshold": True},
            CART,
        )
        assert validate_success(ok2)["status"] == "SUBSTITUTED"
        prm_after = get_success_data(api_client.get_supply_item(prm["id"], ANY))
        assert prm_after["on_hand_quantity"] == 4


class TestCancelRestock:
    def test_pick_then_cancel_restock_conserves_on_hand(self):
        """PRD §3.3: "Cancellation is hygienic about stock: every pick line's
        `qty_picked` is restocked to its item's `on_hand_quantity`, the pick
        list transitions to `CANCELLED`, and the case transitions to
        `CANCELLED`."
        PRD §2.8: "case cancellation, which restocks every picked quantity"

        Design: Difficulty/compensating_invariant/pick_then_cancel_restock_conserves_on_hand
        """
        surgeon = make_surgeon(full_name="Dr. Inv")
        kit = make_supply_item(sku="KIT-BASIC", name="Basic kit",
                               unit_cost_cents=500, substitute_group="KIT",
                               initial_on_hand=10)
        gauze = make_supply_item(sku="GAUZE-4X4", name="Gauze 4x4",
                                 unit_cost_cents=50, substitute_group="GAUZE",
                                 initial_on_hand=20)
        # Second line stays PENDING so the list remains IN_PICKING — picking
        # the final open line would auto-stage the list (PRD §3.4), and a
        # STAGED list blocks cancellation (PRD §3.3).
        card = make_published_card(surgeon["id"], "BIOPSY",
                                   [{"supply_item_id": kit["id"], "quantity": 2},
                                    {"supply_item_id": gauze["id"], "quantity": 1}])
        case = make_case(surgeon["id"], card["id"],
                         scheduled_start="2026-09-01T08:00:00Z",
                         expected_duration_min=30, room="OR-10")
        pl, lines = release_pick_list(case["id"])
        get_success_data(api_client.begin_picking(pl["id"], CART))
        get_success_data(api_client.pick_line(lines[0]["id"], CART))

        resp = api_client.cancel_case(case["id"], ANALYST)
        cancelled = validate_success(resp)
        assert cancelled["status"] == "CANCELLED"

        item_after = get_success_data(api_client.get_supply_item(kit["id"], ANY))
        assert item_after["on_hand_quantity"] == 10
        pl_after = get_success_data(api_client.get_pick_list(pl["id"], ANY))
        assert pl_after["status"] == "CANCELLED"

    def test_cancel_dispatched_case_rejected(self):
        """PRD §3.3: "A case may be cancelled from `SCHEDULED` or from
        `PICKING_RELEASED`; if a pick list already exists, it must still be in
        `GENERATED`, `IN_PICKING`, or `PICKING_EXCEPTION`. Any other
        constellation — a list already `STAGED`, `DISPATCHED`, `RETURNED`, or
        `CLOSED`, or a case already `IN_PROGRESS`, `COMPLETED`, or `CANCELLED`
        — is rejected with `ERR_CASE_NOT_CANCELLABLE`."

        Design: Corner/state_machines/cancel_dispatched_case_rejected
        """
        ctx = _simple_case(surgeon_name="Dr. Late")
        get_success_data(api_client.begin_picking(ctx["pick_list"]["id"], CART))
        get_success_data(api_client.pick_line(ctx["lines"][0]["id"], CART))
        get_success_data(api_client.dispatch_pick_list(ctx["pick_list"]["id"], CART))
        resp = api_client.cancel_case(ctx["case"]["id"], ANALYST)
        validate_error(resp, ApiErrorId.ERR_CASE_NOT_CANCELLABLE)
        case_after = get_success_data(api_client.get_case(ctx["case"]["id"], ANY))
        assert case_after["status"] == "IN_PROGRESS"
        item_after = get_success_data(api_client.get_supply_item(ctx["item"]["id"], ANY))
        assert item_after["on_hand_quantity"] == 99

    def test_mark_short_cascade_depth2(self):
        """PRD §3.4: "Marking short moves the line `PENDING → SHORT` and
        pushes the list `IN_PICKING → PICKING_EXCEPTION` — a no-op if the list
        is already in exception. Each entry of the list into
        `PICKING_EXCEPTION` increments the case's `pick_exception_count` by
        exactly one"

        Design: Difficulty/transitive_cascade/mark_short_cascade_depth2
        """
        surgeon = make_surgeon(full_name="Dr. Short")
        tray = make_supply_item(sku="TRAY-STD", name="Standard tray",
                                unit_cost_cents=2000, substitute_group="TRAY",
                                initial_on_hand=0)
        card = make_published_card(surgeon["id"], "ORIF",
                                   [{"supply_item_id": tray["id"], "quantity": 1}])
        case = make_case(surgeon["id"], card["id"],
                         scheduled_start="2026-09-01T08:00:00Z",
                         expected_duration_min=90, room="OR-4")
        pl, lines = release_pick_list(case["id"])
        get_success_data(api_client.begin_picking(pl["id"], CART))
        marked = api_client.mark_short(
            lines[0]["id"], {"reason_code": "OUT_OF_STOCK"}, CART
        )
        line_after = validate_success(marked)
        assert line_after["status"] == "SHORT"
        pl_after = get_success_data(api_client.get_pick_list(pl["id"], ANY))
        assert pl_after["status"] == "PICKING_EXCEPTION"
        case_after = get_success_data(api_client.get_case(case["id"], ANY))
        assert case_after["pick_exception_count"] == 1
