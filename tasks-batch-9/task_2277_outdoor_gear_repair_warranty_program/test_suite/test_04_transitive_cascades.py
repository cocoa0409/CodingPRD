"""Transitive cascade coverage: multi-hop chains where each hop is caused by the previous.

Two triggers are exercised, each split into one test per affected entity:

  * `POST /gear-service/warranty-claims/{id}/decision` resolving to a warranty
    repair — the claim mints a liability entry, that entry raises the centre's
    open exposure, and the new exposure re-derives the centre's posture
    (PRD §3.5, §2.9).
  * `POST /gear-service/repair-orders/{id}/close-irreparable` — the condemnation
    releases the reserved parts, the release returns units to the lot, the lot
    climbs back out of `DEPLETED`, and that lot status change re-derives the
    model's `parts_support_status` (PRD §3.9, §2.10).

Every precondition is built inside the test through the PRD §4 endpoints,
because the server is restarted against an empty database before each test.
"""

from test_helpers import (
    SCENARIO_CLOCK_UTC,
    World,
    assert_center_posture,
    assert_claim_decision,
    assert_part_lot_counts,
    factories,
)

# --------------------------------------------------------------------------
# Shared builders — plain helpers, not fixtures, so each test owns its world.
# --------------------------------------------------------------------------
PANEL_PART_CODE = factories.PANEL_PART_CODE
DISCONTINUED_AT = "2024-03-01T00:00:00Z"


def _build_assessed_claim(scenario, liability_cap_cents, panel_on_hand_units):
    """Centre, discontinued Ascent 2P with a successor, owner, unit, bench, assessment.

    The unit is serial AS2-00417 purchased 2023-05-10 for 74900 cents with the
    logical clock pinned to 2026-06-15T09:00:00Z; the live bench finding is
    `MANUFACTURING_DEFECT` over a single 120-minute `FABRIC` lane with 4200
    cents of estimated parts.
    """
    scenario.set_clock(SCENARIO_CLOCK_UTC)
    center = scenario.center(liability_cap_cents=liability_cap_cents)
    successor = scenario.successor_model()
    model = scenario.model(
        discontinued_at=DISCONTINUED_AT, successor_model_id=successor["id"]
    )
    panel_lot = scenario.part_lot(
        model["id"], on_hand_units=panel_on_hand_units, low_watermark_units=2
    )
    customer = scenario.customer()
    item = scenario.gear_item(model["id"], customer["id"])
    technician = scenario.technician(
        center["id"],
        employee_code="T-101",
        full_name="Ines Park",
        certifications=[factories.certification("FABRIC", 3)],
    )
    claim = scenario.claim(center["id"], item["id"])
    submitted = scenario.submit(claim["id"])
    assessment = scenario.assess(
        claim["id"], technician["id"], expected_claim_version=submitted["version"]
    )
    return World(
        scenario=scenario,
        center_id=center["id"],
        successor_id=successor["id"],
        model_id=model["id"],
        panel_lot_id=panel_lot["id"],
        customer_id=customer["id"],
        item_id=item["id"],
        technician_id=technician["id"],
        claim_id=claim["id"],
        assessment=assessment,
    )


def _build_condemnable_order(scenario):
    """A WARRANTY_REPAIR order in `IN_WORK` with a scheduled block and a depleted lot.

    The single AS2-FLOOR-PANEL lot is stocked with 3 units at a watermark of 2,
    so it is `AVAILABLE` when the order is created and only drains to
    `DEPLETED` once all three units are reserved against the order.
    """
    world = _build_assessed_claim(
        scenario, liability_cap_cents=5000000, panel_on_hand_units=3
    )
    claim = scenario.decide(world.claim_id)
    order = scenario.repair_order(world.claim_id)
    block = scenario.work_block(
        order["id"],
        world.technician_id,
        work_type="FABRIC",
        start_at="2026-06-16T09:00:00Z",
        end_at="2026-06-16T11:00:00Z",
    )
    reservation = scenario.reserve_parts(
        order["id"], world.panel_lot_id, PANEL_PART_CODE, 3
    )
    world.update(
        claim=claim,
        order=order,
        order_id=order["id"],
        block=block,
        block_id=block["id"],
        reservation=reservation,
        reservation_id=reservation["id"],
    )
    return world


class TestWarrantyApprovalLiabilityPostureChain:
    """Adjudication → liability entry → centre exposure → centre posture."""

    def test_hop_one_mints_the_open_repair_liability_entry(self, scenario):
        """A warranty-repair adjudication mints one OPEN REPAIR entry reserving 22390 cents.

        "First, a liability entry is created on the claim with `basis` `REPAIR`, `valuation_variant` `DEPRECIATED_PURCHASE`, `status` `OPEN`, and a `reserved_amount_cents` equal to the lesser of the claim's `latest_repair_cost_cents` and the unit's `replacement_value_depreciated_cents` — the brand never reserves more for a repair than the depreciated worth of the thing being repaired."
        "Its `release_reason` and `released_at` are null while it is `OPEN`."

        Design: Difficulty/transitive_cascade/warranty_approval_liability_posture_chain
        """
        world = _build_assessed_claim(
            scenario, liability_cap_cents=30000, panel_on_hand_units=5
        )

        scenario.decide(
            world.claim_id,
            decision_note="Defect confirmed; authorize warranty repair.",
        )

        entries = scenario.liability_entries(world.claim_id)
        assert len(entries) == 1, entries
        entry = entries[0]
        assert entry["basis"] == "REPAIR", entry
        assert entry["valuation_variant"] == "DEPRECIATED_PURCHASE", entry
        assert entry["status"] == "OPEN", entry
        assert entry["reserved_amount_cents"] == 22390, entry
        assert entry["release_reason"] is None, entry
        assert entry["released_at"] is None, entry

    def test_hop_two_raises_center_open_liability_and_utilization(self, scenario):
        """The new OPEN entry raises the centre's exposure to 22390 and utilisation to 74.63.

        "Second, that new open entry increases the centre's `open_liability_cents` by the reserved amount and recomputes `liability_utilization_pct`."
        "`liability_utilization_pct` is one hundred multiplied by `open_liability_cents` divided by `liability_cap_cents`, rounded half up to two decimal places, and is display-only."

        Design: Difficulty/transitive_cascade/warranty_approval_liability_posture_chain
        """
        world = _build_assessed_claim(
            scenario, liability_cap_cents=30000, panel_on_hand_units=5
        )
        before = scenario.read_center(world.center_id)
        assert_center_posture(before, 0, 0.0, "OPEN")

        scenario.decide(
            world.claim_id,
            decision_note="Defect confirmed; authorize warranty repair.",
        )

        center = scenario.read_center(world.center_id)
        assert_center_posture(center, 22390, 74.63)

    def test_hop_three_re_derives_posture_to_constrained(self, scenario):
        """The raised exposure re-derives the centre's posture OPEN → CONSTRAINED.

        "Third, the new exposure re-derives the centre's `liability_posture` on the bands of §2.9, so a single approval can push a centre from `OPEN` to `CONSTRAINED` or from `CONSTRAINED` to `FROZEN`."
        "Otherwise, if `open_liability_cents` multiplied by one hundred is strictly greater than sixty multiplied by `liability_cap_cents`, the posture is `CONSTRAINED`."

        Design: Difficulty/transitive_cascade/warranty_approval_liability_posture_chain
        """
        world = _build_assessed_claim(
            scenario, liability_cap_cents=30000, panel_on_hand_units=5
        )

        scenario.decide(
            world.claim_id,
            decision_note="Defect confirmed; authorize warranty repair.",
        )

        center = scenario.read_center(world.center_id)
        assert_center_posture(center, 22390, 74.63, "CONSTRAINED")

    def test_repairability_feedback_counter_moves_on_the_same_request(self, scenario):
        """The same adjudication bumps defect_claim_count to 1 and leaves the flag NONE.

        "Separately, the model's `defect_claim_count` increases by one and its `repairability_flag` is then re-derived from the updated counters."
        "A model's `repairability_flag` becomes `REDESIGN_REQUESTED` when its `defect_claim_count` is at least five **and** its `irreparable_count` is at least two; failing that, it becomes `WATCH` when its `defect_claim_count` is at least three; and otherwise it is `NONE`."

        Design: Difficulty/transitive_cascade/warranty_approval_liability_posture_chain
        """
        world = _build_assessed_claim(
            scenario, liability_cap_cents=30000, panel_on_hand_units=5
        )

        scenario.decide(
            world.claim_id,
            decision_note="Defect confirmed; authorize warranty repair.",
        )

        model = scenario.read_model(world.model_id)
        assert model["defect_claim_count"] == 1, model
        assert model["wear_denial_count"] == 0, model
        assert model["irreparable_count"] == 0, model
        assert model["repairability_flag"] == "NONE", model

    def test_claim_records_the_derived_warranty_repair_outcome(self, scenario):
        """The claim itself lands WARRANTY_REPAIR / WARRANTY_APPROVED at threshold 55 and ratio 24.90.

        "Otherwise the outcome is `WARRANTY_REPAIR`."
        "A `WARRANTY_REPAIR` outcome moves the claim `UNDER_ASSESSMENT` → `WARRANTY_APPROVED` and opens the brand's exposure in a three-hop cascade."

        Design: Difficulty/transitive_cascade/warranty_approval_liability_posture_chain
        """
        world = _build_assessed_claim(
            scenario, liability_cap_cents=30000, panel_on_hand_units=5
        )

        claim = scenario.decide(
            world.claim_id,
            decision_note="Defect confirmed; authorize warranty repair.",
        )

        assert_claim_decision(
            claim,
            decision="WARRANTY_REPAIR",
            status="WARRANTY_APPROVED",
            threshold_pct=55,
            ratio_pct=24.90,
        )
        assert claim["decision_by_role"] == "ServiceAgent", claim


class TestIrreparableClosePartsReleaseSupportChain:
    """Condemnation → reservation release → lot counters and band → model support."""

    def test_hop_one_condemnation_releases_the_reserved_draw(self, scenario):
        """Condemning the order releases the still-RESERVED draw and stamps settled_at.

        "It is `DEPLETED` when `available_units` is zero; `LOW` when `available_units` is at least one and at most `low_watermark_units`; and `AVAILABLE` otherwise."
        "First, every reservation on the order still in `status` `RESERVED` moves to `RELEASED` with `settled_at` stamped."

        Design: Difficulty/transitive_cascade/irreparable_close_parts_release_support_chain
        """
        world = _build_condemnable_order(scenario)
        lot_before = scenario.read_lot(world.panel_lot_id)
        assert_part_lot_counts(lot_before, 3, 3, 0, "DEPLETED")
        model_before = scenario.read_model(world.model_id)
        assert model_before["parts_support_status"] == "NO_SUPPORT", model_before

        scenario.close_irreparable(
            world.order_id,
            world.technician_id,
            "Floor fabric delaminated beyond patchable area.",
        )

        reservation = scenario.read_reservation(world.reservation_id)
        assert reservation["status"] == "RELEASED", reservation
        assert reservation["settled_at"] is not None, reservation

    def test_hop_two_and_three_lot_counters_and_band_recover(self, scenario):
        """The release gives the 3 units back and the lot climbs DEPLETED → AVAILABLE.

        "Second, each released reservation decreases its lot's `reserved_units` by that reservation's `units` and recomputes the lot's `available_units`."
        "Third, each lot whose `available_units` changed re-derives its `status`, which is how a `DEPLETED` lot climbs back to `LOW` or `AVAILABLE`."

        Design: Difficulty/transitive_cascade/irreparable_close_parts_release_support_chain
        """
        world = _build_condemnable_order(scenario)
        assert_part_lot_counts(scenario.read_lot(world.panel_lot_id), 3, 3, 0, "DEPLETED")

        scenario.close_irreparable(
            world.order_id,
            world.technician_id,
            "Floor fabric delaminated beyond patchable area.",
        )

        lot = scenario.read_lot(world.panel_lot_id)
        assert_part_lot_counts(lot, 3, 0, 3, "AVAILABLE")

    def test_hop_four_model_parts_support_returns_to_supported(self, scenario):
        """The lot status change re-derives the model's parts_support_status NO_SUPPORT → SUPPORTED.

        "Fourth, each lot status change re-derives `parts_support_status` on that lot's model."
        "That model-level field is `SUPPORTED` when some part lot for the model has a `status` of `AVAILABLE` or `LOW`."

        Design: Difficulty/transitive_cascade/irreparable_close_parts_release_support_chain
        """
        world = _build_condemnable_order(scenario)
        assert scenario.read_model(world.model_id)["parts_support_status"] == "NO_SUPPORT"

        scenario.close_irreparable(
            world.order_id,
            world.technician_id,
            "Floor fabric delaminated beyond patchable area.",
        )

        model = scenario.read_model(world.model_id)
        assert model["parts_support_status"] == "SUPPORTED", model

    def test_order_condemns_and_scheduled_block_is_cancelled_with_minutes_returned(
        self, scenario
    ):
        """The order reaches IRREPARABLE, its scheduled block is cancelled and 120 minutes go back.

        "**Condemnation** is available to a `ServiceAgent` or a `RepairTechnician` with a `reason` on an order whose `work_status` is `QUEUED`, `IN_WORK` or `BENCH_DONE`, and it drives the order to `IRREPARABLE` from any of those three origins."
        "In parallel, every work block on the order still in `status` `SCHEDULED` moves to `CANCELLED` and its technician's `scheduled_minutes_open` decreases by the block's `duration_minutes`."

        Design: Difficulty/transitive_cascade/irreparable_close_parts_release_support_chain
        """
        world = _build_condemnable_order(scenario)
        assert scenario.read_order(world.order_id)["work_status"] == "IN_WORK"
        assert scenario.read_technician(world.technician_id)["scheduled_minutes_open"] == 120

        order = scenario.close_irreparable(
            world.order_id,
            world.technician_id,
            "Floor fabric delaminated beyond patchable area.",
        )

        assert order["work_status"] == "IRREPARABLE", order
        block = scenario.read_work_block(world.block_id)
        assert block["status"] == "CANCELLED", block
        technician = scenario.read_technician(world.technician_id)
        assert technician["scheduled_minutes_open"] == 0, technician

    def test_warranty_liability_is_revalued_to_a_replacement_reservation(self, scenario):
        """The REPAIR entry is released as REVALUED_TO_REPLACEMENT and an OPEN 89910 REPLACEMENT entry replaces it.

        "For a warranty order the liability is revalued rather than merely released: the claim's open entry with `basis` `REPAIR` moves `OPEN` → `RELEASED` with `release_reason` `REVALUED_TO_REPLACEMENT`, and a new entry is created with `basis` `REPLACEMENT`, `valuation_variant` `SUCCESSOR_MSRP` and `status` `OPEN`, so the centre's `open_liability_cents` is adjusted by subtracting the released repair amount and adding the new replacement amount before `liability_posture` is re-derived."
        "The successor basis is the denominator of the repair-versus-replace ratio and is the full amount of a replacement-type liability reservation."

        Design: Difficulty/transitive_cascade/irreparable_close_parts_release_support_chain
        """
        world = _build_condemnable_order(scenario)
        assert_center_posture(scenario.read_center(world.center_id), 22390)

        scenario.close_irreparable(
            world.order_id,
            world.technician_id,
            "Floor fabric delaminated beyond patchable area.",
        )

        entries = scenario.liability_entries(world.claim_id)
        assert len(entries) == 2, entries
        repair_rows = [row for row in entries if row["basis"] == "REPAIR"]
        replacement_rows = [row for row in entries if row["basis"] == "REPLACEMENT"]
        assert len(repair_rows) == 1, entries
        assert len(replacement_rows) == 1, entries

        released = repair_rows[0]
        assert released["status"] == "RELEASED", released
        assert released["release_reason"] == "REVALUED_TO_REPLACEMENT", released
        assert released["released_at"] is not None, released
        assert released["reserved_amount_cents"] == 22390, released

        opened = replacement_rows[0]
        assert opened["status"] == "OPEN", opened
        assert opened["valuation_variant"] == "SUCCESSOR_MSRP", opened
        assert opened["reserved_amount_cents"] == 89910, opened

        assert_center_posture(scenario.read_center(world.center_id), 89910)

    def test_unit_moves_to_irreparable_hold_and_model_irreparable_counter_moves(
        self, scenario
    ):
        """The condemned unit lands in IRREPARABLE_HOLD and the model's irreparable_count reaches 1.

        "The unit moves `IN_REPAIR` → `IRREPARABLE_HOLD`, which makes trade-in reachable. And the model's `irreparable_count` increases by one, after which its `repairability_flag` is re-derived."

        Design: Difficulty/transitive_cascade/irreparable_close_parts_release_support_chain
        """
        world = _build_condemnable_order(scenario)
        assert scenario.read_item(world.item_id)["disposition_status"] == "IN_REPAIR"

        scenario.close_irreparable(
            world.order_id,
            world.technician_id,
            "Floor fabric delaminated beyond patchable area.",
        )

        item = scenario.read_item(world.item_id)
        assert item["disposition_status"] == "IRREPARABLE_HOLD", item
        model = scenario.read_model(world.model_id)
        assert model["irreparable_count"] == 1, model
        assert model["repairability_flag"] == "NONE", model
