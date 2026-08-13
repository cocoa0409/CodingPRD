"""Second-look tests for difficulty instances (each instance needs >= 2 tests).

These re-exercise the same PRD rules from an independent angle: a different
field, a different point of observation, or an additional sub-assertion of the
same instance's declared `assert` block.
"""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    get_charges_for_case,
    get_success_data,
    make_case,
    make_published_card,
    make_supply_item,
    make_surgeon,
    make_surgeon_headers,
    release_pick_list,
    return_cart,
    setup_dispatched_case,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    validate_success,
)

ANALYST = TEST_USERS["analyst_headers"]
CART = TEST_USERS["cart_tech_headers"]
NURSE = TEST_USERS["nurse_headers"]
ANY = TEST_USERS["any_headers"]


def _glove(**kw):
    defaults = dict(sku="GLOVE-PR", name="Gloves pair", unit_cost_cents=250,
                    substitute_group="GLOVES", initial_on_hand=100)
    defaults.update(kw)
    return make_supply_item(**defaults)


class TestPickListExceptionCycleSecondLook:
    def test_exception_cycle_sub_line_fields(self):
        """PRD §3.4: "Substitution sets `qty_picked` to `qty_requested` drawn
        from the substitute's stock, decrements the substitute's
        `on_hand_quantity` accordingly, re-snapshots the line's
        `unit_cost_cents` from the substitute item, records
        `substituted_item_id`, and moves the line `SHORT → SUBSTITUTED`."

        Design: Difficulty/non_linear_state_machine/pick_list_exception_cycle
        """
        surgeon = make_surgeon(full_name="Dr. Cycle2")
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
        sub = validate_success(api_client.substitute_line(
            line_x["id"], {"substitute_supply_item_id": tray_alt["id"]}, CART
        ))
        assert sub["substituted_item_id"] == tray_alt["id"]
        assert sub["qty_picked"] == 2
        assert sub["unit_cost_cents"] == 2200
        # Glove line still PENDING: list must NOT have auto-staged.
        st = get_success_data(api_client.get_pick_list(pl["id"], ANY))["status"]
        assert st == "IN_PICKING"


class TestMarkShortCascadeSecondLook:
    def test_mark_short_increments_exception_counter_once(self):
        """PRD §3.4: "Each entry of the list into `PICKING_EXCEPTION`
        increments the case's `pick_exception_count` by exactly one; marking a
        second line short while the list is already in exception does not
        increment it again."

        Design: Difficulty/transitive_cascade/mark_short_cascade_depth2
        """
        surgeon = make_surgeon(full_name="Dr. Short2")
        tray = make_supply_item(sku="TRAY-STD", name="Standard tray",
                                unit_cost_cents=2000, substitute_group="TRAY",
                                initial_on_hand=0)
        tray2 = make_supply_item(sku="TRAY-ALT", name="Alternate tray",
                                 unit_cost_cents=2100, substitute_group="TRAY2",
                                 initial_on_hand=0)
        card = make_published_card(
            surgeon["id"], "ORIF",
            [{"supply_item_id": tray["id"], "quantity": 1,
              "designation": "OPEN", "pick_sequence": 1},
             {"supply_item_id": tray2["id"], "quantity": 1,
              "designation": "OPEN", "pick_sequence": 2}],
        )
        case = make_case(surgeon["id"], card["id"],
                         scheduled_start="2026-09-01T08:00:00Z",
                         expected_duration_min=90, room="OR-4")
        pl, lines = release_pick_list(case["id"])
        get_success_data(api_client.begin_picking(pl["id"], CART))
        get_success_data(
            api_client.mark_short(lines[0]["id"], {"reason_code": "OOS"}, CART)
        )
        case_after_1 = get_success_data(api_client.get_case(case["id"], ANY))
        assert case_after_1["pick_exception_count"] == 1
        # Second mark-short while already in exception: no additional bump.
        get_success_data(
            api_client.mark_short(lines[1]["id"], {"reason_code": "OOS"}, CART)
        )
        case_after_2 = get_success_data(api_client.get_case(case["id"], ANY))
        assert case_after_2["pick_exception_count"] == 1
        pl_after = get_success_data(api_client.get_pick_list(pl["id"], ANY))
        assert pl_after["status"] == "PICKING_EXCEPTION"


class TestPriorityPairSecondLook:
    def test_substitute_state_beats_safety_atomic_rejection(self):
        """PRD §2.7: "Every mutation endpoint runs its validations in a fixed,
        global order, and all validations for an endpoint complete before any
        mutation is applied — a failed request applies zero side effects, no
        matter how far into the pipeline it traveled."
        PRD §2.7: "**Target state**" (priority 5) precedes "**Clinical safety
        business rules**" (priority 7).

        Design: Difficulty/priority_pair_validation_conflict/substitute_state_beats_safety
        """
        surgeon = make_surgeon(full_name="Dr. Prio2")
        tray = make_supply_item(sku="TRAY-STD", name="Standard tray",
                                unit_cost_cents=2000, substitute_group="TRAY",
                                initial_on_hand=5)
        clamp = make_supply_item(sku="CLAMP-9", name="Clamp",
                                 unit_cost_cents=1500, substitute_group="CLAMP",
                                 initial_on_hand=5)
        card = make_published_card(
            surgeon["id"], "ORIF",
            [{"supply_item_id": tray["id"], "quantity": 1}],
        )
        case = make_case(surgeon["id"], card["id"],
                         scheduled_start="2026-09-01T08:00:00Z",
                         expected_duration_min=90, room="OR-4")
        pl, lines = release_pick_list(case["id"])
        get_success_data(api_client.begin_picking(pl["id"], CART))
        # Line PENDING + wrong-group substitute: state error must win.
        resp = api_client.substitute_line(
            lines[0]["id"], {"substitute_supply_item_id": clamp["id"]}, CART
        )
        validate_error(resp, ApiErrorId.ERR_LINE_NOT_SHORT)
        # Zero side effects: clamp stock unmoved, line still PENDING, list
        # still IN_PICKING.
        assert get_success_data(api_client.get_supply_item(clamp["id"], ANY))["on_hand_quantity"] == 5
        assert get_success_data(api_client.get_pick_list_line(lines[0]["id"], ANY))["status"] == "PENDING"
        assert get_success_data(api_client.get_pick_list(pl["id"], ANY))["status"] == "IN_PICKING"

    def test_complete_referential_beats_fiscal_no_charges_created(self):
        """PRD §2.7: "**Cross-entity referential coherence**" (priority 8)
        precedes "**Fiscal guards**" (priority 11).
        PRD §3.5: "every entry must reference a line of this case's own pick
        list (`ERR_LINE_CASE_MISMATCH`)"
        PRD §2.7: "a failed request applies zero side effects"

        Design: Difficulty/priority_pair_validation_conflict/complete_referential_beats_fiscal
        """
        surgeon = make_surgeon(full_name="Dr. Ref2")
        glove = _glove()
        rod = make_supply_item(sku="ROD-TI", name="Titanium rod",
                               unit_cost_cents=5000, substitute_group="ROD",
                               consignment_flag=True, initial_on_hand=10)
        # Foreign case F: glove card, released; line stays PENDING.
        from test_helpers import setup_released_case
        fx = setup_released_case(
            surgeon, [glove],
            [{"item_index": 0, "quantity": 1, "designation": "OPEN"}],
            procedure_name="CATH",
            scheduled_start="2026-09-01T08:00:00Z",
            expected_duration_min=45,
            room="OR-5",
        )
        line_f = fx["lines"][0]
        ctx_d = setup_dispatched_case(
            surgeon, [rod],
            [{"item_index": 0, "quantity": 2, "designation": "OPEN"}],
            procedure_name="SPINE",
            scheduled_start="2026-09-02T08:00:00Z",
            expected_duration_min=120,
            room="OR-6",
            consignment_budget_cents=9000,
        )
        return_cart(ctx_d["pick_list"]["id"], return_entries=[])
        line_d = ctx_d["lines"][0]
        resp = api_client.complete_case(
            ctx_d["case"]["id"],
            {"usage_entries": [
                {"pick_list_line_id": line_f["id"], "qty_used": 0},
                {"pick_list_line_id": line_d["id"], "qty_used": 2},
            ]},
            NURSE,
        )
        validate_error(resp, ApiErrorId.ERR_LINE_CASE_MISMATCH)
        # Atomic rejection: no usage records and no consignment charges.
        _, meta_ur = validate_paginated(
            api_client.list_usage_records(ANY, params={"case_id": ctx_d["case"]["id"]})
        )
        assert meta_ur["total_count"] == 0
        _, meta_ch = validate_paginated(
            api_client.list_consignment_charges(ANY, params={"case_id": ctx_d["case"]["id"]})
        )
        assert meta_ch["total_count"] == 0


class TestStockBoundarySecondLook:
    def test_equality_pick_leaves_zero_and_qty_picked(self):
        """PRD §3.4: "the item's `on_hand_quantity` must be at least
        `qty_requested` — equality is sufficient — with shortfalls rejected as
        `ERR_INSUFFICIENT_STOCK`. A successful pick sets `qty_picked` equal to
        `qty_requested`, decrements the item's `on_hand_quantity` by
        `qty_requested`, and moves the line `PENDING → PICKED`."

        Design: Difficulty/boundary_precision_check/pick_on_hand_exact_equality_boundary
        """
        surgeon = make_surgeon(full_name="Dr. Bound2")
        item = make_supply_item(sku="SCALPEL-11", name="Scalpel 11",
                                unit_cost_cents=150, substitute_group="BLADE",
                                initial_on_hand=3)
        card = make_published_card(
            surgeon["id"], "EXCISION",
            [{"supply_item_id": item["id"], "quantity": 3}],
        )
        case = make_case(surgeon["id"], card["id"],
                         scheduled_start="2026-09-01T08:00:00Z",
                         expected_duration_min=30, room="OR-7")
        pl, lines = release_pick_list(case["id"])
        get_success_data(api_client.begin_picking(pl["id"], CART))
        picked = validate_success(api_client.pick_line(lines[0]["id"], CART))
        assert picked["qty_picked"] == 3
        assert picked["status"] == "PICKED"
        item_after = get_success_data(api_client.get_supply_item(item["id"], ANY))
        assert item_after["on_hand_quantity"] == 0
        # With only one line, the list auto-stages.
        pl_after = get_success_data(api_client.get_pick_list(pl["id"], ANY))
        assert pl_after["status"] == "STAGED"


class TestCancelRestockSecondLook:
    def test_cancel_restock_list_and_case_terminal(self):
        """PRD §3.3: "Cancellation is hygienic about stock: every pick line's
        `qty_picked` is restocked to its item's `on_hand_quantity`, the pick
        list transitions to `CANCELLED`, and the case transitions to
        `CANCELLED`."
        PRD §2.8: "case cancellation, which restocks every picked quantity"

        Design: Difficulty/compensating_invariant/pick_then_cancel_restock_conserves_on_hand
        """
        surgeon = make_surgeon(full_name="Dr. Inv2")
        kit = make_supply_item(sku="KIT-BASIC", name="Basic kit",
                               unit_cost_cents=500, substitute_group="KIT",
                               initial_on_hand=10)
        gauze = make_supply_item(sku="GAUZE-4X4", name="Gauze 4x4",
                                 unit_cost_cents=50, substitute_group="GAUZE",
                                 initial_on_hand=20)
        # Second line stays PENDING so the list remains IN_PICKING — picking
        # the final open line would auto-stage the list (PRD §3.4), and a
        # STAGED list blocks cancellation (PRD §3.3).
        card = make_published_card(
            surgeon["id"], "BIOPSY",
            [{"supply_item_id": kit["id"], "quantity": 2},
             {"supply_item_id": gauze["id"], "quantity": 1}],
        )
        case = make_case(surgeon["id"], card["id"],
                         scheduled_start="2026-09-01T08:00:00Z",
                         expected_duration_min=30, room="OR-10")
        pl, lines = release_pick_list(case["id"])
        get_success_data(api_client.begin_picking(pl["id"], CART))
        # Stock drops from 10 to 8 on pick.
        get_success_data(api_client.pick_line(lines[0]["id"], CART))
        mid = get_success_data(api_client.get_supply_item(kit["id"], ANY))
        assert mid["on_hand_quantity"] == 8
        # Cancel restocks back to the pre-pick value.
        get_success_data(api_client.cancel_case(case["id"], ANALYST))
        final = get_success_data(api_client.get_supply_item(kit["id"], ANY))
        assert final["on_hand_quantity"] == 10
        pl_after = get_success_data(api_client.get_pick_list(pl["id"], ANY))
        assert pl_after["status"] == "CANCELLED"
        case_after = get_success_data(api_client.get_case(case["id"], ANY))
        assert case_after["status"] == "CANCELLED"
