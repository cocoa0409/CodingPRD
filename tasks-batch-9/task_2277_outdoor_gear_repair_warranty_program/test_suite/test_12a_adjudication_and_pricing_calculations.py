"""Adjudication derivation and paid-repair pricing arithmetic.

Every test builds its own world from scratch — the harness restarts the API
server before each test, so nothing is inherited from a neighbouring test.
The models built here are deliberately *not* discontinued and name no
successor, so the successor-MSRP basis of PRD §2.8 is the model's own
`msrp_cents` walked down to ninety percent.
"""

import pytest

from test_helpers import (
    ERR_ASSESSMENT_INCONCLUSIVE,
    assert_claim_decision,
    assert_estimate_breakdown,
    assert_immutable_common_fields,
    assert_no_row_created,
    assert_timestamp_millis,
    factories,
    validate_error,
)


# --------------------------------------------------------------------------
# Local world builders (PRD §3.1 - §3.4 bootstrap sequence)
# --------------------------------------------------------------------------
def _tent_world(scenario, stock_panel_lot=True, customer_overrides=None,
                item_overrides=None, certifications=None):
    """Centre, Ascent 2P tent model (no successor), owner, unit and technician."""
    scenario.set_clock()
    center = scenario.center()
    model = scenario.model()
    panel_lot = scenario.part_lot(model["id"]) if stock_panel_lot else None
    customer = scenario.customer(**(customer_overrides or {}))
    item = scenario.gear_item(model["id"], customer["id"], **(item_overrides or {}))
    technician = scenario.technician(
        center["id"],
        certifications=certifications or [factories.certification("FABRIC", 3)],
    )
    return {
        "center": center,
        "model": model,
        "panel_lot": panel_lot,
        "customer": customer,
        "item": item,
        "technician": technician,
    }


class TestAdjudicationOutcomeDerivation:
    """The three-step derivation and the four divergent outcomes of PRD §3.5."""

    def test_second_assessment_supersedes_first_and_remirrors_claim_cost(
        self, scenario
    ):
        """A re-assessment supersedes the first finding and the decision prices the new one.

        "Every earlier assessment on the same claim has its `is_superseded` flag set to true, so exactly one row is ever the live finding."
        "The new row is created, the claim's `assessment_count` increases by one, and the claim's `latest_determination` and `latest_repair_cost_cents` are overwritten from the new row's `determination` and `estimated_repair_cost_cents`."
        "It has no `updated_at` and no `version`, there is no endpoint that updates it, and a later finding never edits an earlier one — it supersedes it by setting the earlier row's `is_superseded` flag."
        "`repair_ratio_pct` is one hundred multiplied by the claim's `latest_repair_cost_cents`, divided by the unit's `replacement_value_successor_cents`, rounded half up to two decimal places."
        "First, a liability entry is created on the claim with `basis` `REPAIR`, `valuation_variant` `DEPRECIATED_PURCHASE`, `status` `OPEN`, and a `reserved_amount_cents` equal to the lesser of the claim's `latest_repair_cost_cents` and the unit's `replacement_value_depreciated_cents` — the brand never reserves more for a repair than the depreciated worth of the thing being repaired."

        Design: Corner/calculations/second_assessment_supersedes_first_and_remirrors_claim_cost
        """
        world = _tent_world(scenario)
        claim = scenario.claim(world["center"]["id"], world["item"]["id"])
        submitted = scenario.submit(claim["id"])

        first = scenario.assess(
            claim["id"],
            world["technician"]["id"],
            expected_claim_version=submitted["version"],
            determination="MANUFACTURING_DEFECT",
            required_work_types=["FABRIC"],
            estimated_labor_lines=[factories.labor_line("FABRIC", 120)],
            estimated_parts_cents=4200,
            defect_notes="First look: full panel swap.",
        )
        assert first["estimated_repair_cost_cents"] == 22390

        second = scenario.assess(
            claim["id"],
            world["technician"]["id"],
            expected_claim_version=scenario.claim_version(claim["id"]),
            determination="MANUFACTURING_DEFECT",
            required_work_types=["FABRIC"],
            estimated_labor_lines=[factories.labor_line("FABRIC", 90)],
            estimated_parts_cents=0,
            defect_notes="Patch repair is enough; no panel needed.",
        )
        assert_immutable_common_fields(second)
        # labour 12750 + parts 0 + capped supply fee 893
        assert second["estimated_repair_cost_cents"] == 13643

        stored_first = scenario.read_assessment(first["id"])
        assert stored_first["is_superseded"] is True
        assert stored_first["estimated_repair_cost_cents"] == 22390
        assert scenario.read_assessment(second["id"])["is_superseded"] is False

        before_decision = scenario.read_claim(claim["id"])
        assert before_decision["status"] == "UNDER_ASSESSMENT"
        assert before_decision["assessment_count"] == 2
        assert before_decision["latest_determination"] == "MANUFACTURING_DEFECT"
        assert before_decision["latest_repair_cost_cents"] == 13643

        decided = scenario.decide(claim["id"])
        assert_claim_decision(
            decided,
            decision="WARRANTY_REPAIR",
            status="WARRANTY_APPROVED",
            threshold_pct=55,
            ratio_pct=18.97,
        )

        entries = scenario.liability_entries(claim["id"])
        assert len(entries) == 1, entries
        entry = entries[0]
        assert entry["basis"] == "REPAIR"
        assert entry["valuation_variant"] == "DEPRECIATED_PURCHASE"
        assert entry["status"] == "OPEN"
        # min(13643, depreciated 52430) — not the superseded 22390
        assert entry["reserved_amount_cents"] == 13643

    def test_inconclusive_determination_blocks_decision_rejected(
        self, scenario, api, agent_headers
    ):
        """An INCONCLUSIVE live finding refuses adjudication and leaves the claim untouched.

        "The claim must be in `UNDER_ASSESSMENT`; the live finding must not be `INCONCLUSIVE`, or the request is refused with `ERR_ASSESSMENT_INCONCLUSIVE`; and the centre's `liability_posture` must not be `FROZEN` when the derived outcome is a warranty outcome."
        "If the live `determination` is `INCONCLUSIVE`, the request is refused with `ERR_ASSESSMENT_INCONCLUSIVE`."
        "Whatever the outcome, the claim records `decision`, `decision_threshold_pct`, `repair_ratio_pct`, `decision_by_role` — set to `ServiceAgent` or `ProgramAdmin` according to the acting role — and `decided_at` from the logical clock."

        Design: Corner/calculations/inconclusive_determination_blocks_decision_rejected
        """
        world = _tent_world(scenario)
        claim = scenario.claim(
            world["center"]["id"],
            world["item"]["id"],
            reported_defect_type="DELAMINATION",
            customer_narrative="Coating is peeling.",
        )
        submitted = scenario.submit(claim["id"])
        scenario.assess(
            claim["id"],
            world["technician"]["id"],
            expected_claim_version=submitted["version"],
            determination="INCONCLUSIVE",
            required_work_types=["FABRIC"],
            estimated_labor_lines=[factories.labor_line("FABRIC", 120)],
            estimated_parts_cents=4200,
            defect_notes="Cannot tell defect from storage damage.",
        )

        response = api.decide_claim(claim["id"], agent_headers, {})
        validate_error(response, ERR_ASSESSMENT_INCONCLUSIVE)

        after = scenario.read_claim(claim["id"])
        assert after["status"] == "UNDER_ASSESSMENT"
        assert after["decision"] is None
        assert after["decided_at"] is None
        assert after["decision_threshold_pct"] is None
        assert after["repair_ratio_pct"] is None

        assert_no_row_created(scenario.liability_entries(claim["id"]))
        assert scenario.read_center(world["center"]["id"])["open_liability_cents"] == 0

        model = scenario.read_model(world["model"]["id"])
        assert model["defect_claim_count"] == 0
        assert model["wear_denial_count"] == 0

    def test_normal_wear_with_supported_parts_offers_paid_repair(self, scenario):
        """NORMAL_WEAR on a stocked model offers paid repair instead of denying the claim.

        "If it is `NORMAL_WEAR`, the outcome depends on the stockroom: `WEAR_DENIED` when the model's `parts_support_status` is `NO_SUPPORT`, and `PAID_REPAIR_OFFERED` otherwise."
        "That model-level field is `SUPPORTED` when some part lot for the model has a `status` of `AVAILABLE` or `LOW`."
        "A `PAID_REPAIR_OFFERED` outcome moves the claim `UNDER_ASSESSMENT` → `PAID_REPAIR_OFFERED` and stamps `decision`, `decided_at` and `decision_by_role`. No liability entry is created and the centre's `open_liability_cents` is unchanged, because the brand carries no exposure on work the customer pays for."
        "The raw cap starts from the model's category allowance — sixty-five percent for `SHELL_APPAREL`, sixty percent for `INSULATION`, seventy percent for `TENT_SHELTER`, seventy-five percent for `PACK_HARNESS` and fifty-five percent for `HARDGOODS_FRAME`."
        "Five percentage points are then subtracted for each completed year of the unit's age, where completed years are `age_months` divided by twelve and floored."

        Design: Corner/calculations/normal_wear_with_supported_parts_offers_paid_repair
        """
        world = _tent_world(scenario)
        assert scenario.read_model(world["model"]["id"])["parts_support_status"] == "SUPPORTED"

        claim = scenario.claim(
            world["center"]["id"],
            world["item"]["id"],
            reported_defect_type="ABRASION_WEAR",
            customer_narrative="Floor is worn thin.",
        )
        submitted = scenario.submit(claim["id"])
        scenario.assess(
            claim["id"],
            world["technician"]["id"],
            expected_claim_version=submitted["version"],
            determination="NORMAL_WEAR",
            required_work_types=["FABRIC"],
            estimated_labor_lines=[factories.labor_line("FABRIC", 120)],
            estimated_parts_cents=4200,
            defect_notes="Abrasion, repairable with a stocked panel.",
        )

        decided = scenario.decide(claim["id"])
        assert_claim_decision(
            decided,
            decision="PAID_REPAIR_OFFERED",
            status="PAID_REPAIR_OFFERED",
            threshold_pct=55,
            ratio_pct=31.14,
        )

        model = scenario.read_model(world["model"]["id"])
        assert model["wear_denial_count"] == 0
        assert model["defect_claim_count"] == 0
        assert model["repairability_flag"] == "NONE"

        assert_no_row_created(scenario.liability_entries(claim["id"]))
        assert scenario.read_center(world["center"]["id"])["open_liability_cents"] == 0

    def test_expired_warranty_defect_offers_paid_repair_before_support_check(
        self, scenario
    ):
        """An expired defect claim on a NO_SUPPORT model is priced, not replaced.

        "**Step three** branches, and the branches are evaluated top to bottom with the first match winning."
        "The remaining branches all assume a `MANUFACTURING_DEFECT`. If the unit's `warranty_state` is `EXPIRED`, the outcome is `PAID_REPAIR_OFFERED`. If the model's `parts_support_status` is `NO_SUPPORT`, the outcome is `WARRANTY_REPLACE`, because there is nothing to repair the unit with."
        "The depreciation fraction is ten percent for each completed year, capped so it can never exceed sixty percent — that is, the lesser of 0.60 and 0.10 multiplied by the completed years."
        "The successor valuation is that base list price multiplied by ninety percent, rounded half up to whole cents."
        "Failing both, it is `NO_SUPPORT`."

        Design: Corner/calculations/expired_warranty_defect_offers_paid_repair_before_support_check
        """
        world = _tent_world(
            scenario,
            stock_panel_lot=False,
            item_overrides={
                "serial_number": "AS2-00901",
                "purchase_date": "2019-01-10T00:00:00Z",
                "purchase_price_cents": 74900,
                "proof_of_purchase_ref": "POS-19001",
                "condition_grade": "C",
            },
        )

        item = scenario.read_item(world["item"]["id"])
        assert item["age_months"] == 89
        assert item["warranty_state"] == "EXPIRED"
        # 74900 * (1 - 0.60), the depreciation cap binding over 0.10 * 7 years
        assert item["replacement_value_depreciated_cents"] == 29960
        assert item["replacement_value_successor_cents"] == 71910
        assert scenario.read_model(world["model"]["id"])["parts_support_status"] == "NO_SUPPORT"

        claim = scenario.claim(
            world["center"]["id"],
            world["item"]["id"],
            intake_kind="PAID_REPAIR_REQUEST",
            reported_defect_type="SEAM_FAILURE",
            customer_narrative="Seam let go again.",
        )
        submitted = scenario.submit(claim["id"])
        scenario.assess(
            claim["id"],
            world["technician"]["id"],
            expected_claim_version=submitted["version"],
            determination="MANUFACTURING_DEFECT",
            required_work_types=["FABRIC"],
            estimated_labor_lines=[factories.labor_line("FABRIC", 120)],
            estimated_parts_cents=4200,
            defect_notes="Same factory bond line.",
        )

        decided = scenario.decide(claim["id"])
        assert_claim_decision(
            decided,
            decision="PAID_REPAIR_OFFERED",
            status="PAID_REPAIR_OFFERED",
            threshold_pct=35,
            ratio_pct=31.14,
        )

        assert_no_row_created(scenario.liability_entries(claim["id"]))
        assert scenario.read_model(world["model"]["id"])["defect_claim_count"] == 0


class TestProvisionalQuotePricing:
    """The eight pricing steps of PRD §3.7 on a PROVISIONAL quote."""

    def test_standard_tier_quote_applies_no_loyalty_discount(self, scenario):
        """A STANDARD owner's quote carries a zero discount, so tax is charged on the full subtotal.

        "**Step five** applies loyalty: `loyalty_discount_cents` is `subtotal_cents` multiplied by the owner's tier rate, rounded half up, where a `STANDARD` owner's rate is zero percent and a `PRO` owner's rate is ten percent."
        "A `loyalty_tier` may be supplied and defaults to `STANDARD`; the only other value is `PRO`, and the tier is what earns a discount on paid work."
        "**Step six** applies expedite: `expedite_fee_cents` is 3500 cents on a `FINAL` row when the order's `expedite_requested` is true, and zero in every other case — a `PROVISIONAL` row always carries zero here, even on an expedited order."
        "**Step seven** taxes the discounted, expedited base: `tax_cents` is 8.25 percent of the quantity `subtotal_cents` minus `loyalty_discount_cents` plus `expedite_fee_cents`, rounded half up."
        "**Step eight** totals: `total_cents` is `subtotal_cents` minus `loyalty_discount_cents` plus `expedite_fee_cents` plus `tax_cents`."
        "On success any prior estimate on the order whose `status` was `SENT` becomes `SUPERSEDED`, a new estimate row is created with `variant` `PROVISIONAL` and `status` `SENT` and a `repair_order_id` pointing at the order, the order's `billing_status` becomes `ESTIMATE_SENT`, and the order's `version` increases by one."
        "The new row's `valid_until` is the logical clock instant advanced by seven days, and its `decided_at` is null until the customer answers."

        Design: Corner/calculations/standard_tier_quote_applies_no_loyalty_discount
        """
        world = _tent_world(
            scenario,
            customer_overrides={
                "full_name": "Tam Ito",
                "email": "tam@example.com",
                "loyalty_tier": factories.OMIT,
            },
            item_overrides={
                "serial_number": "AS2-00555",
                "proof_of_purchase_type": "REGISTRATION",
                "proof_of_purchase_ref": "REG-5551",
            },
            certifications=[factories.certification("ZIPPER", 3)],
        )
        scenario.part_lot(
            world["model"]["id"],
            part_code=factories.ZIP_PART_CODE,
            part_kind="ZIPPER_SLIDER",
            on_hand_units=4,
            unit_price_cents=1800,
            low_watermark_units=1,
        )
        assert scenario.read_customer(world["customer"]["id"])["loyalty_tier"] == "STANDARD"

        claim = scenario.claim(
            world["center"]["id"],
            world["item"]["id"],
            intake_kind="PAID_REPAIR_REQUEST",
            reported_defect_type="ZIPPER_FAILURE",
            customer_narrative="Slider chewed.",
        )
        submitted = scenario.submit(claim["id"])
        scenario.assess(
            claim["id"],
            world["technician"]["id"],
            expected_claim_version=submitted["version"],
            determination="USER_DAMAGE",
            required_work_types=["ZIPPER"],
            estimated_labor_lines=[factories.labor_line("ZIPPER", 35)],
            estimated_parts_cents=1800,
            defect_notes="Impact damage.",
        )
        scenario.decide(claim["id"])
        order = scenario.repair_order(claim["id"])

        estimate = scenario.estimate(
            order["id"],
            expected_repair_order_version=order["version"],
            labor_lines=[factories.labor_line("ZIPPER", 35)],
            parts_lines=[factories.parts_line(factories.ZIP_PART_CODE, 1, 1800)],
        )

        assert_estimate_breakdown(
            estimate,
            labor_subtotal_cents=5542,
            parts_subtotal_cents=1800,
            shop_supply_fee_cents=388,
            subtotal_cents=7730,
            loyalty_discount_cents=0,
            expedite_fee_cents=0,
            tax_cents=638,
            total_cents=8368,
        )
        assert estimate["variant"] == "PROVISIONAL"
        assert estimate["status"] == "SENT"
        assert estimate["decided_at"] is None
        assert_timestamp_millis(estimate["valid_until"])
        assert estimate["valid_until"].startswith("2026-06-22T09:00:00")

    def test_shop_supply_fee_cap_binds_on_long_frame_labor(self, scenario):
        """Three hundred minutes of frame labour pins the supply fee at its 2500-cent cap.

        "**Step three** applies a capped shop supply fee on labour alone: `shop_supply_fee_cents` is the lesser of 2500 cents and seven percent of `labor_subtotal_cents` rounded half up."
        "The hourly rates are 8500 cents for `FABRIC`, 9500 cents for `ZIPPER`, 11000 cents for `FRAME` and 9000 cents for `INSULATION`."
        "From those inputs the server computes `estimated_repair_cost_cents` on the assessment row using the labour block of the paid-repair pricing rule described in §3.7 — that is, the per-line rounded labour charges summed into a labour subtotal, plus `estimated_parts_cents` used directly as the parts subtotal, plus the capped shop supply fee."
        "Second, a congestion tier is looked up on that snapshot: a snapshot of at most 9 yields a tier multiplier of 1.00, at most 24 yields 1.25, at most 49 yields 1.60, and 50 or more yields 2.00."
        "Fourth, a parts wait is read from the model's `parts_support_status` **as it stands before any reservation created by this request**: zero days when `SUPPORTED`, seven days when `SUBSTITUTION_ONLY`, and fourteen days when `NO_SUPPORT`, recorded as `parts_wait_days`."
        "Fifth, base days are assembled from the model's `category` — ten days for `SHELL_APPAREL`, fourteen for `INSULATION`, twelve for `TENT_SHELTER`, nine for `PACK_HARNESS` and sixteen for `HARDGOODS_FRAME` — plus the largest work-type addition among the order's `required_work_types`, where fabric work adds two days, zipper work three, frame work five and insulation work six."
        "Sixth, `promised_days` is the base-day total multiplied by `surge_multiplier_applied`, rounded **up** to a whole number of days, and only then increased by `parts_wait_days`; the rounding up happens before the parts wait is added and never after."
        "`promised_return_at` is then the calendar date of the logical clock instant advanced by `promised_days` days, at 23:59:59.999Z on that date."

        Design: Corner/calculations/shop_supply_fee_cap_binds_on_long_frame_labor
        """
        scenario.set_clock()
        center = scenario.center()
        model = scenario.model(
            model_code="FRM-BASECAMP-1",
            name="Basecamp Frame",
            category="HARDGOODS_FRAME",
            msrp_cents=129900,
            release_year=2021,
            warranty_years=5,
        )
        scenario.part_lot(
            model["id"],
            part_code="BC1-POLE-SEG",
            part_kind="FRAME_SEGMENT",
            on_hand_units=6,
            unit_price_cents=7400,
            low_watermark_units=2,
        )
        customer = scenario.customer(
            full_name="Tam Ito", email="tam@example.com", loyalty_tier="STANDARD"
        )
        item = scenario.gear_item(
            model["id"],
            customer["id"],
            serial_number="BC1-00031",
            purchase_price_cents=119900,
            proof_of_purchase_ref="POS-31001",
        )
        technician = scenario.technician(
            center["id"],
            employee_code="T-110",
            full_name="Ada Roy",
            certifications=[factories.certification("FRAME", 3)],
        )

        claim = scenario.claim(
            center["id"],
            item["id"],
            intake_kind="PAID_REPAIR_REQUEST",
            reported_defect_type="FRAME_FRACTURE",
            customer_narrative="Backed the truck over it.",
        )
        submitted = scenario.submit(claim["id"])
        assessment = scenario.assess(
            claim["id"],
            technician["id"],
            expected_claim_version=submitted["version"],
            determination="USER_DAMAGE",
            required_work_types=["FRAME"],
            estimated_labor_lines=[factories.labor_line("FRAME", 300)],
            estimated_parts_cents=0,
            defect_notes="Crush damage; full rebuild.",
        )
        # 55000 labour + 0 parts + the capped 2500 fee, not the uncapped 3850
        assert assessment["estimated_repair_cost_cents"] == 57500

        scenario.decide(claim["id"])
        order = scenario.repair_order(claim["id"])

        estimate = scenario.estimate(
            order["id"],
            expected_repair_order_version=order["version"],
            labor_lines=[factories.labor_line("FRAME", 300)],
            parts_lines=factories.OMIT,
        )
        assert_estimate_breakdown(
            estimate,
            labor_subtotal_cents=55000,
            parts_subtotal_cents=0,
            shop_supply_fee_cents=2500,
            subtotal_cents=57500,
            loyalty_discount_cents=0,
            expedite_fee_cents=0,
            tax_cents=4744,
            total_cents=62244,
        )

        # 16 base days for HARDGOODS_FRAME + 5 for FRAME, multiplier 1.00, no parts wait
        assert order["promised_days"] == 21
        assert order["promised_return_at"] == "2026-07-06T23:59:59.999Z"
        assert order["surge_multiplier_applied"] == pytest.approx(1.00, abs=0.01)
        assert order["parts_wait_days"] == 0
