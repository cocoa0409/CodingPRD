"""Case completion: usage records, dual-variant costs, waste, consignment, audit."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    assert_pct,
    get_success_data,
    get_audit_for_case,
    get_charges_for_case,
    get_usage_records_for_case,
    make_case,
    make_published_card,
    make_supply_item,
    make_surgeon,
    release_pick_list,
    setup_completed_case,
    setup_dispatched_case,
    setup_released_case,
    validate_error,
    validate_success,
    return_cart,
)

ANALYST = TEST_USERS["analyst_headers"]
CART = TEST_USERS["cart_tech_headers"]
NURSE = TEST_USERS["nurse_headers"]
ANY = TEST_USERS["any_headers"]


def _dual_fixture(surgeon_name="Dr. Dual", start="2026-09-01T08:00:00Z",
                  room="OR-1"):
    """GLOVE-PR 250 OPEN (4x), SUTURE-KIT 1000 HOLD (2x), DRAPE-FULL 3000 OPEN
    (1x): standard 6000; released, picked, dispatched, returned with nothing
    unopened."""
    surgeon = make_surgeon(full_name=surgeon_name)
    glove = make_supply_item(sku="GLOVE-PR", name="Gloves pair",
                             unit_cost_cents=250, substitute_group="GLOVES",
                             initial_on_hand=100)
    suture = make_supply_item(sku="SUTURE-KIT", name="Suture kit",
                              unit_cost_cents=1000, substitute_group="SUTURE",
                              initial_on_hand=50)
    drape = make_supply_item(sku="DRAPE-FULL", name="Full drape",
                             unit_cost_cents=3000, substitute_group="DRAPE",
                             initial_on_hand=20)
    ctx = setup_dispatched_case(
        surgeon,
        [glove, suture, drape],
        [
            {"item_index": 0, "quantity": 4, "designation": "OPEN"},
            {"item_index": 1, "quantity": 2, "designation": "HOLD"},
            {"item_index": 2, "quantity": 1, "designation": "OPEN"},
        ],
        procedure_name="TKA",
        scheduled_start=start,
        expected_duration_min=120,
        room=room,
    )
    return_cart(ctx["pick_list"]["id"], return_entries=[])
    return surgeon, (glove, suture, drape), ctx


def _complete_dual(ctx):
    lines = ctx["lines"]
    usage_entries = [
        {"pick_list_line_id": lines[0]["id"], "qty_used": 4},
        {"pick_list_line_id": lines[1]["id"], "qty_used": 1},
        {"pick_list_line_id": lines[2]["id"], "qty_used": 1},
    ]
    return api_client.complete_case(
        ctx["case"]["id"], {"usage_entries": usage_entries}, NURSE
    )


class TestDualVariantCaseCost:
    def test_standard_vs_actual_diverge(self):
        """PRD §3.4: "the case's `standard_cost_cents` is computed — the
        as-planned cost, being the sum over the snapshot lines of
        `qty_requested` multiplied by the snapshot `unit_cost_cents`"
        PRD §3.5: "`actual_cost_cents` — the as-used variant of case costing —
        is the sum over usage records of `qty_used` times `unit_cost_cents`,
        plus the waste total"

        Design: Difficulty/dual_variant_calc/case_cost_standard_vs_actual_diverge
        """
        _, _, ctx = _dual_fixture()
        completed = validate_success(_complete_dual(ctx))
        assert completed["status"] == "COMPLETED"
        assert completed["standard_cost_cents"] == 6000
        assert completed["actual_cost_cents"] == 6500
        assert completed["waste_cost_cents"] == 1500

    def test_dual_variant_via_case_read(self):
        """PRD §3.5: "it diverges from `standard_cost_cents` whenever reality
        deviates from plan."

        Design: Difficulty/dual_variant_calc/case_cost_standard_vs_actual_diverge
        """
        _, _, ctx = _dual_fixture(start="2026-09-02T08:00:00Z", room="OR-1")
        _complete_dual(ctx)
        case = get_success_data(api_client.get_case(ctx["case"]["id"], ANY))
        assert case["standard_cost_cents"] == 6000
        assert case["actual_cost_cents"] == 6500
        assert case["waste_cost_cents"] == 1500
        assert case["status"] == "COMPLETED"


class TestAuditDualVariant:
    def test_audit_line_match_vs_spend_weighted_diverge(self):
        """PRD §3.5: "The nursing-compliance variant counts lines:
        `matched_line_count` is the number of pinned card lines whose pick line
        was not substituted and whose `qty_used` equals `qty_requested`;
        `total_line_count` is the number of lines on the pinned card version at
        release; and `line_match_pct` is `matched_line_count` divided by
        `total_line_count`, times 100, rounded half up to 2 decimal places. The
        standardization variant weighs spend: `spend_match_pct` is one minus
        the absolute difference between `actual_cost_cents` and
        `standard_cost_cents` divided by `standard_cost_cents`, floored at
        zero, times 100, rounded half up to 2 decimal places"

        Design: Difficulty/dual_variant_calc/audit_line_match_vs_spend_weighted_diverge
        """
        _, _, ctx = _dual_fixture()
        _complete_dual(ctx)
        audit = get_audit_for_case(ctx["case"]["id"])
        assert audit["matched_line_count"] == 2
        assert audit["total_line_count"] == 3
        assert_pct(audit["line_match_pct"], 66.67, "line_match_pct")
        assert_pct(audit["spend_match_pct"], 91.67, "spend_match_pct")
        assert audit["waste_flag"] is True

    def test_audit_waste_flag_from_threshold(self):
        """PRD §3.5: "When the rounded `waste_pct` reaches 20.0 the audit's
        `waste_flag` is set true — exactly 20.0 flags; 19.98 does not"

        Design: Difficulty/dual_variant_calc/audit_line_match_vs_spend_weighted_diverge
        """
        _, _, ctx = _dual_fixture(start="2026-09-03T08:00:00Z", room="OR-2")
        _complete_dual(ctx)
        audit = get_audit_for_case(ctx["case"]["id"])
        # waste 1500 of standard 6000 = 25.0% >= 20.0.
        assert_pct(audit["waste_pct"], 25.0, "waste_pct")
        assert audit["waste_flag"] is True


class TestWasteChargeMultiplier:
    def test_hold_branch_multiplier(self):
        """PRD §3.5: "Otherwise the charge is `qty_wasted` multiplied by
        `unit_cost_cents` multiplied by a designation-driven multiplier: 1.0
        when the item's `consignment_flag` is true (consignment waste is billed
        at cost), 1.5 when the line's snapshot `designation` is `HOLD` (hold
        items opened unnecessarily carry a penalty), and 1.0 for `OPEN` lines."

        Design: Difficulty/combinatorial_formula/waste_charge_designation_multiplier_branch
        """
        surgeon = make_surgeon(full_name="Dr. Mult")
        suture = make_supply_item(sku="SUTURE-KIT", name="Suture kit",
                                  unit_cost_cents=1000, substitute_group="SUTURE",
                                  initial_on_hand=50)
        ctx = setup_completed_case(
            surgeon,
            [suture],
            [{"item_index": 0, "quantity": 2, "designation": "HOLD"}],
            usage_by_index={0: 1},
            procedure_name="SCOPE",
            scheduled_start="2026-09-01T08:00:00Z",
            expected_duration_min=60,
            room="OR-2",
        )
        records = get_usage_records_for_case(ctx["case"]["id"])
        assert len(records) == 1
        ur = records[0]
        assert ur["qty_opened"] == 2
        assert ur["qty_wasted"] == 1
        assert ur["waste_charge_cents"] == 1500

    def test_hold_branch_case_totals(self):
        """PRD §3.5: "`waste_cost_cents` is the sum of the per-line waste
        charges. `actual_cost_cents` ... is the sum over usage records of
        `qty_used` times `unit_cost_cents`, plus the waste total"

        Design: Difficulty/combinatorial_formula/waste_charge_designation_multiplier_branch
        """
        surgeon = make_surgeon(full_name="Dr. Mult2")
        suture = make_supply_item(sku="SUTURE-KIT", name="Suture kit",
                                  unit_cost_cents=1000, substitute_group="SUTURE",
                                  initial_on_hand=50)
        ctx = setup_completed_case(
            surgeon,
            [suture],
            [{"item_index": 0, "quantity": 2, "designation": "HOLD"}],
            usage_by_index={0: 1},
            procedure_name="SCOPE",
            scheduled_start="2026-09-02T08:00:00Z",
            expected_duration_min=60,
            room="OR-2",
        )
        completed = ctx["completed_case"]
        assert completed["standard_cost_cents"] == 2000
        assert completed["actual_cost_cents"] == 2500
        assert completed["waste_cost_cents"] == 1500


class TestWasteRoundingOrder:
    def _rounding_ctx(self, surgeon_name):
        surgeon = make_surgeon(full_name=surgeon_name)
        pad_a = make_supply_item(sku="PAD-A", name="Pad A", unit_cost_cents=333,
                                 substitute_group="PAD", initial_on_hand=10)
        pad_b = make_supply_item(sku="PAD-B", name="Pad B", unit_cost_cents=333,
                                 substitute_group="PAD", initial_on_hand=10)
        return setup_completed_case(
            surgeon,
            [pad_a, pad_b],
            [
                {"item_index": 0, "quantity": 1, "designation": "HOLD"},
                {"item_index": 1, "quantity": 1, "designation": "HOLD"},
            ],
            usage_by_index=None,
            procedure_name="EXFIX",
            scheduled_start="2026-09-01T08:00:00Z",
            expected_duration_min=60,
            room="OR-3",
        )

    def test_per_line_rounding(self):
        """PRD §3.5: "Each line's charge is rounded half up to whole cents
        individually, and only then are the per-line values summed — summing
        unrounded line values and rounding once is forbidden."

        Design: Difficulty/combinatorial_formula/waste_rounding_per_line_then_sum_pinned
        """
        ctx = self._rounding_ctx("Dr. Round")
        records = get_usage_records_for_case(ctx["case"]["id"])
        assert len(records) == 2
        for ur in records:
            # round_half_up(1 x 333 x 1.5) = round_half_up(499.5) = 500.
            assert ur["waste_charge_cents"] == 500

    def test_sum_uses_rounded_line_values(self):
        """PRD §3.5: "Each line's charge is rounded half up to whole cents
        individually, and only then are the per-line values summed — summing
        unrounded line values and rounding once is forbidden."

        Design: Difficulty/combinatorial_formula/waste_rounding_per_line_then_sum_pinned
        """
        ctx = self._rounding_ctx("Dr. Round2")
        completed = ctx["completed_case"]
        # 500 + 500; sum-then-round's 999 is forbidden.
        assert completed["waste_cost_cents"] == 1000
        assert completed["actual_cost_cents"] == 1000
        assert completed["standard_cost_cents"] == 666


class TestCompleteCascade:
    def _cascade_ctx(self, surgeon_name):
        surgeon, items, ctx = _dual_fixture(
            surgeon_name=surgeon_name, start="2026-09-01T08:00:00Z", room="OR-1"
        )
        card_before = get_success_data(
            api_client.get_preference_card(ctx["card"]["id"], ANY)
        )
        assert card_before["flagged_audit_count"] == 0
        assert card_before["rolling_line_match_pct"] is None
        return ctx

    def test_complete_case_cascade_links_1_and_2(self):
        """PRD §3.5: "From these records the case settles its costs.
        `waste_cost_cents` is the sum of the per-line waste charges."
        PRD §3.5: "Waste is graded by `waste_pct`, the case's
        `waste_cost_cents` divided by `standard_cost_cents` times 100, rounded
        half up to 2 decimal places ... When the rounded `waste_pct` reaches
        20.0 the audit's `waste_flag` is set true"

        Design: Difficulty/transitive_cascade/complete_case_cascade_depth3
        """
        ctx = self._cascade_ctx("Dr. Cascade")
        completed = validate_success(_complete_dual(ctx))
        # Link 1: usage records recompute case cost fields.
        assert completed["actual_cost_cents"] == 6500
        assert completed["waste_cost_cents"] == 1500
        # Link 2: derived waste_pct flags the audit.
        audit = get_audit_for_case(ctx["case"]["id"])
        assert_pct(audit["waste_pct"], 25.0, "waste_pct")
        assert audit["waste_flag"] is True

    def test_complete_case_cascade_link_3_card_counters(self):
        """PRD §3.5: "The audit's arrival updates the card itself: the card's
        `flagged_audit_count` increments by one when the new audit's
        `waste_flag` is true, and its `rolling_line_match_pct` is recomputed as
        the mean of `line_match_pct` across all audits of the card, rounded
        half up to 2 decimal places — remaining null until the card's first
        audit exists."
        PRD §3.5: "its pick list moves `RETURNED → CLOSED`."

        Design: Difficulty/transitive_cascade/complete_case_cascade_depth3
        """
        ctx = self._cascade_ctx("Dr. Cascade3")
        _complete_dual(ctx)
        card_after = get_success_data(
            api_client.get_preference_card(ctx["card"]["id"], ANY)
        )
        assert card_after["flagged_audit_count"] == 1
        assert_pct(card_after["rolling_line_match_pct"], 66.67,
                   "rolling_line_match_pct")
        pl_after = get_success_data(
            api_client.get_pick_list(ctx["pick_list"]["id"], ANY)
        )
        assert pl_after["status"] == "CLOSED"


class TestWasteFlagBoundary:
    def _boundary_cases(self):
        surgeon = make_surgeon(full_name="Dr. Edge")
        glove = make_supply_item(sku="GLOVE-PR", name="Gloves pair",
                                 unit_cost_cents=250, substitute_group="GLOVES",
                                 initial_on_hand=50)
        drape = make_supply_item(sku="DRAPE-FULL", name="Full drape",
                                 unit_cost_cents=3000, substitute_group="DRAPE",
                                 initial_on_hand=50)
        wrap8 = make_supply_item(sku="WRAP-STD", name="Wrap std",
                                 unit_cost_cents=800, substitute_group="WRAP",
                                 initial_on_hand=50)
        wrap7 = make_supply_item(sku="WRAP-LT", name="Wrap lt",
                                 unit_cost_cents=799, substitute_group="WRAP",
                                 initial_on_hand=50)
        gel = make_supply_item(sku="GEL-PK", name="Gel pack",
                               unit_cost_cents=201, substitute_group="GEL",
                               initial_on_hand=50)
        # Card A: standard 8*250 + 3200 + 800 = 6000; wrap (HOLD) unused.
        # (drape_a at 3200 makes standard exactly 6000 so 1200 waste is 20.0%.)
        drape_a = make_supply_item(sku="DRAPE-A", name="Drape A",
                                   unit_cost_cents=3200, substitute_group="DRAPEA",
                                   initial_on_hand=50)
        ctx_a = setup_completed_case(
            surgeon,
            [glove, drape_a, wrap8],
            [
                {"item_index": 0, "quantity": 8, "designation": "OPEN"},
                {"item_index": 1, "quantity": 1, "designation": "OPEN"},
                {"item_index": 2, "quantity": 1, "designation": "HOLD"},
            ],
            usage_by_index={0: 8, 1: 1, 2: 0},
            procedure_name="FUSION-A",
            scheduled_start="2026-09-01T08:00:00Z",
            expected_duration_min=120,
            room="OR-1",
        )
        # Card B: standard 8*250 + 3000 + 799 + 201 = 6000; wrap (HOLD) unused.
        ctx_b = setup_completed_case(
            surgeon,
            [glove, drape, wrap7, gel],
            [
                {"item_index": 0, "quantity": 8, "designation": "OPEN"},
                {"item_index": 1, "quantity": 1, "designation": "OPEN"},
                {"item_index": 2, "quantity": 1, "designation": "HOLD"},
                {"item_index": 3, "quantity": 1, "designation": "OPEN"},
            ],
            usage_by_index={0: 8, 1: 1, 2: 0, 3: 1},
            procedure_name="FUSION-B",
            scheduled_start="2026-09-02T08:00:00Z",
            expected_duration_min=120,
            room="OR-1",
        )
        return ctx_a, ctx_b

    def test_exactly_twenty_pct_flags(self):
        """PRD §3.5: "When the rounded `waste_pct` reaches 20.0 the audit's
        `waste_flag` is set true — exactly 20.0 flags; 19.98 does not — because
        the comparison applies to the rounded value."

        Design: Difficulty/boundary_precision_check/waste_flag_exactly_twenty_pct_boundary
        """
        ctx_a, _ = self._boundary_cases()
        completed = ctx_a["completed_case"]
        # round_half_up(1 x 800 x 1.5) = 1200.
        assert completed["waste_cost_cents"] == 1200
        audit = get_audit_for_case(ctx_a["case"]["id"])
        assert_pct(audit["waste_pct"], 20.0, "waste_pct")
        assert audit["waste_flag"] is True

    def test_just_under_twenty_pct_does_not_flag(self):
        """PRD §3.5: "When the rounded `waste_pct` reaches 20.0 the audit's
        `waste_flag` is set true — exactly 20.0 flags; 19.98 does not — because
        the comparison applies to the rounded value."

        Design: Difficulty/boundary_precision_check/waste_flag_exactly_twenty_pct_boundary
        """
        _, ctx_b = self._boundary_cases()
        completed = ctx_b["completed_case"]
        # round_half_up(1 x 799 x 1.5) = round_half_up(1198.5) = 1199.
        assert completed["waste_cost_cents"] == 1199
        audit = get_audit_for_case(ctx_b["case"]["id"])
        assert_pct(audit["waste_pct"], 19.98, "waste_pct")
        assert audit["waste_flag"] is False


class TestConsignmentAtCompletion:
    def test_consignment_charge_bills_on_open_not_use(self):
        """PRD §3.5: "Consignment bills on open, not on use, so `qty_billed`
        equals the usage record's `qty_opened`, and `amount_cents` is
        `qty_billed` times the record's `unit_cost_cents`."
        PRD §3.5: "for every usage record whose item has `consignment_flag`
        true and `qty_opened` greater than zero, the system creates a
        `ConsignmentCharge` in `PENDING` status"

        Design: Corner/calculations/consignment_charge_bills_on_open_not_use
        """
        surgeon = make_surgeon(full_name="Dr. Cons")
        rod = make_supply_item(sku="ROD-TI", name="Titanium rod",
                               unit_cost_cents=5000, substitute_group="ROD",
                               consignment_flag=True, initial_on_hand=10)
        ctx = setup_dispatched_case(
            surgeon,
            [rod],
            [{"item_index": 0, "quantity": 2, "designation": "OPEN"}],
            procedure_name="SPINE",
            scheduled_start="2026-09-05T08:00:00Z",
            expected_duration_min=120,
            room="OR-6",
        )
        # Return 1 unopened of the 2 picked.
        line = ctx["lines"][0]
        return_cart(ctx["pick_list"]["id"],
                    return_entries=[{"pick_list_line_id": line["id"],
                                     "qty_returned_unopened": 1}])
        completed = validate_success(api_client.complete_case(
            ctx["case"]["id"],
            {"usage_entries": [{"pick_list_line_id": line["id"], "qty_used": 1}]},
            NURSE,
        ))
        charges = get_charges_for_case(ctx["case"]["id"])
        assert len(charges) == 1
        chg = charges[0]
        assert chg["qty_billed"] == 1
        assert chg["amount_cents"] == 5000
        assert chg["status"] == "PENDING"
        # Stock: 10 - 2 picked + 1 returned = 9.
        item_after = get_success_data(api_client.get_supply_item(rod["id"], ANY))
        assert item_after["on_hand_quantity"] == 9
        assert completed["actual_cost_cents"] == 5000

    def test_consignment_hold_waste_uses_cost_multiplier(self):
        """PRD §3.5: "Otherwise the charge is `qty_wasted` multiplied by
        `unit_cost_cents` multiplied by a designation-driven multiplier: 1.0
        when the item's `consignment_flag` is true (consignment waste is billed
        at cost), 1.5 when the line's snapshot `designation` is `HOLD`"

        Design: Corner/calculations/consignment_hold_waste_uses_cost_multiplier
        """
        surgeon = make_surgeon(full_name="Dr. Hold")
        cage = make_supply_item(sku="CAGE-PLIF", name="PLIF cage",
                                unit_cost_cents=5000, substitute_group="CAGE",
                                consignment_flag=True, initial_on_hand=5)
        ctx = setup_completed_case(
            surgeon,
            [cage],
            [{"item_index": 0, "quantity": 1, "designation": "HOLD"}],
            usage_by_index={0: 0},
            procedure_name="PLIF",
            scheduled_start="2026-09-05T08:00:00Z",
            expected_duration_min=120,
            room="OR-6",
        )
        records = get_usage_records_for_case(ctx["case"]["id"])
        assert len(records) == 1
        # Consignment branch (1.0x), not HOLD (1.5x): 1 x 5000 x 1.0 = 5000.
        assert records[0]["waste_charge_cents"] == 5000
        charges = get_charges_for_case(ctx["case"]["id"])
        assert len(charges) == 1
        assert charges[0]["amount_cents"] == 5000


class TestCompleteGuards:
    def test_complete_before_cart_return_rejected(self):
        """PRD §3.5: "The case must be `IN_PROGRESS` with its pick list
        `RETURNED` (`ERR_CASE_NOT_COMPLETABLE` otherwise)."

        Design: Corner/state_machines/complete_before_cart_return_rejected
        """
        surgeon = make_surgeon(full_name="Dr. Rush")
        glove = make_supply_item(sku="GLOVE-PR", name="Gloves pair",
                                 unit_cost_cents=250, substitute_group="GLOVES",
                                 initial_on_hand=100)
        ctx = setup_dispatched_case(
            surgeon, [glove],
            [{"item_index": 0, "quantity": 1, "designation": "OPEN"}],
        )
        line = ctx["lines"][0]
        resp = api_client.complete_case(
            ctx["case"]["id"],
            {"usage_entries": [{"pick_list_line_id": line["id"], "qty_used": 1}]},
            NURSE,
        )
        validate_error(resp, ApiErrorId.ERR_CASE_NOT_COMPLETABLE)
        case_after = get_success_data(api_client.get_case(ctx["case"]["id"], ANY))
        assert case_after["status"] == "IN_PROGRESS"
        records = get_usage_records_for_case(ctx["case"]["id"])
        assert len(records) == 0

    def test_usage_exceeding_opened_rejected(self):
        """PRD §3.5: "no entry may claim more than its line actually left the
        shelf with — `qty_used` may not exceed the line's `qty_picked` minus
        its `qty_returned_unopened` (`ERR_USAGE_EXCEEDS_OPENED`, HTTP 422)"

        Design: Corner/validations/usage_exceeding_opened_rejected
        """
        surgeon = make_surgeon(full_name="Dr. Over")
        glove = make_supply_item(sku="GLOVE-PR", name="Gloves pair",
                                 unit_cost_cents=250, substitute_group="GLOVES",
                                 initial_on_hand=100)
        ctx = setup_dispatched_case(
            surgeon, [glove],
            [{"item_index": 0, "quantity": 1, "designation": "OPEN"}],
        )
        return_cart(ctx["pick_list"]["id"], return_entries=[])
        line = ctx["lines"][0]
        resp = api_client.complete_case(
            ctx["case"]["id"],
            {"usage_entries": [{"pick_list_line_id": line["id"], "qty_used": 2}]},
            NURSE,
        )
        validate_error(resp, ApiErrorId.ERR_USAGE_EXCEEDS_OPENED)
        case_after = get_success_data(api_client.get_case(ctx["case"]["id"], ANY))
        assert case_after["status"] == "IN_PROGRESS"
        assert len(get_usage_records_for_case(ctx["case"]["id"])) == 0

    def test_complete_referential_beats_fiscal(self):
        """PRD §2.7: the fixed global validation order evaluates
        "**Cross-entity referential coherence**" (priority 8 —
        `ERR_LINE_CASE_MISMATCH`) before "**Fiscal guards**" (priority 11 —
        `ERR_CONSIGNMENT_BUDGET_EXCEEDED`).
        PRD §3.5: "every entry must reference a line of this case's own pick
        list (`ERR_LINE_CASE_MISMATCH`)"
        PRD §2.7: "a failed request applies zero side effects, no matter how
        far into the pipeline it traveled."

        Design: Difficulty/priority_pair_validation_conflict/complete_referential_beats_fiscal
        """
        surgeon = make_surgeon(full_name="Dr. Ref")
        glove = make_supply_item(sku="GLOVE-PR", name="Gloves pair",
                                 unit_cost_cents=250, substitute_group="GLOVES",
                                 initial_on_hand=100)
        rod = make_supply_item(sku="ROD-TI", name="Titanium rod",
                               unit_cost_cents=5000, substitute_group="ROD",
                               consignment_flag=True, initial_on_hand=10)
        # Foreign case F (glove card, released, line still PENDING).
        ctx_f = setup_released_case(
            surgeon, [glove],
            [{"item_index": 0, "quantity": 1, "designation": "OPEN"}],
            procedure_name="CATH",
            scheduled_start="2026-09-01T08:00:00Z",
            expected_duration_min=45,
            room="OR-5",
        )
        line_f = ctx_f["lines"][0]
        # Case D: consignment card 2x ROD-TI, budget 9000; walked to RETURNED.
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
        # Foreign line (referential violation, priority 8) plus budget breach
        # (fiscal violation, priority 11) — the referential error must win.
        resp = api_client.complete_case(
            ctx_d["case"]["id"],
            {"usage_entries": [
                {"pick_list_line_id": line_f["id"], "qty_used": 0},
                {"pick_list_line_id": line_d["id"], "qty_used": 2},
            ]},
            NURSE,
        )
        validate_error(resp, ApiErrorId.ERR_LINE_CASE_MISMATCH)
        case_after = get_success_data(api_client.get_case(ctx_d["case"]["id"], ANY))
        assert case_after["status"] == "IN_PROGRESS"
        assert len(get_usage_records_for_case(ctx_d["case"]["id"])) == 0

    def test_complete_over_consignment_budget_rejected(self):
        """PRD §3.5: "Before any of this commits, the budget guard runs: when
        the case carries a `consignment_budget_cents`, the sum of the resulting
        charges' `amount_cents` must not exceed it, or the entire completion is
        rejected with `ERR_CONSIGNMENT_BUDGET_EXCEEDED` (HTTP 402)."
        PRD §2.7: "a failed request applies zero side effects"

        Design: Corner/validations/complete_over_consignment_budget_rejected
        """
        from test_helpers import validate_paginated
        surgeon = make_surgeon(full_name="Dr. Budget")
        rod = make_supply_item(sku="ROD-TI", name="Titanium rod",
                               unit_cost_cents=5000, substitute_group="ROD",
                               consignment_flag=True, initial_on_hand=10)
        ctx = setup_dispatched_case(
            surgeon, [rod],
            [{"item_index": 0, "quantity": 2, "designation": "OPEN"}],
            procedure_name="SPINE",
            scheduled_start="2026-09-05T08:00:00Z",
            expected_duration_min=120,
            room="OR-6",
            consignment_budget_cents=9000,
        )
        return_cart(ctx["pick_list"]["id"], return_entries=[])
        line = ctx["lines"][0]
        resp = api_client.complete_case(
            ctx["case"]["id"],
            {"usage_entries": [{"pick_list_line_id": line["id"], "qty_used": 2}]},
            NURSE,
        )
        validate_error(resp, ApiErrorId.ERR_CONSIGNMENT_BUDGET_EXCEEDED)
        case_after = get_success_data(api_client.get_case(ctx["case"]["id"], ANY))
        assert case_after["status"] == "IN_PROGRESS"
        _, meta_ur = validate_paginated(
            api_client.list_usage_records(ANY, params={"case_id": ctx["case"]["id"]})
        )
        assert meta_ur["total_count"] == 0
        _, meta_ch = validate_paginated(
            api_client.list_consignment_charges(ANY, params={"case_id": ctx["case"]["id"]})
        )
        assert meta_ch["total_count"] == 0


class TestImmediateConsistency:
    def test_complete_response_immediately_reflects_costs(self):
        """PRD §3.5: "Only when every check passes does the atomic commit
        begin." and completion produces the settled cost fields; PRD §2.2:
        "operations that create or modify a resource will return the created or
        updated resource object in the data field."
        PRD §3.5: "`waste_cost_cents` is the sum of the per-line waste charges.
        `actual_cost_cents` ... is the sum over usage records of `qty_used`
        times `unit_cost_cents`, plus the waste total"

        Design: Corner/consistency_model/complete_response_immediately_reflects_costs
        """
        surgeon = make_surgeon(full_name="Dr. Imm")
        glove = make_supply_item(sku="GLOVE-PR", name="Gloves pair",
                                 unit_cost_cents=250, substitute_group="GLOVES",
                                 initial_on_hand=100)
        ctx = setup_dispatched_case(
            surgeon, [glove],
            [{"item_index": 0, "quantity": 1, "designation": "OPEN"}],
        )
        return_cart(ctx["pick_list"]["id"], return_entries=[])
        line = ctx["lines"][0]
        resp = api_client.complete_case(
            ctx["case"]["id"],
            {"usage_entries": [{"pick_list_line_id": line["id"], "qty_used": 1}]},
            NURSE,
        )
        data = validate_success(resp)
        assert data["standard_cost_cents"] == 250
        assert data["actual_cost_cents"] == 250
        assert data["waste_cost_cents"] == 0
        assert data["status"] == "COMPLETED"
