"""Cross-cutting layers: concurrency tokens, selector provenance, feedback rollups.

Five behaviours that cut across the whole graph rather than living inside one
endpoint:

  * the claim version token guarding a re-assessment (PRD §2.7, §3.4);
  * the repair-order version token guarding a re-quote (PRD §2.7, §3.7);
  * `routed_by_selector` recording who chose the technician (PRD §3.8);
  * the disjoint model feedback counters and the centre liability rollup that a
    single adjudication moves (PRD §3.5, §2.9);
  * the ops checkpoint that alone flags a breached turnaround commitment and
    stamps `last_queue_review_at` (PRD §3.6, §3.9).

Every precondition is built inside the test through the PRD §4 endpoints,
because the server is restarted against an empty database before each test.
"""

from test_helpers import (
    ERR_STALE_CLAIM_VERSION,
    ERR_STALE_REPAIR_ORDER_VERSION,
    PROGRAM_ADMIN_HEADERS,
    SCENARIO_CLOCK_UTC,
    SERVICE_AGENT_HEADERS,
    World,
    assert_center_posture,
    assert_claim_decision,
    assert_estimate_breakdown,
    assert_multiplier,
    factories,
    make_technician_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

PANEL_PART_CODE = factories.PANEL_PART_CODE
ZIP_PART_CODE = factories.ZIP_PART_CODE
BREACH_CLOCK_UTC = "2026-06-30T09:00:00Z"


# --------------------------------------------------------------------------
# Shared builders — plain helpers, not fixtures, so each test owns its world.
# --------------------------------------------------------------------------
def _build_bench_world(scenario, *, stock_panel_lot=True, certifications=None):
    """Centre, own-MSRP Ascent 2P, optional panel lot, PRO owner, unit, bench.

    The unit is serial AS2-00417 purchased 2023-05-10 for 74900 cents with the
    logical clock pinned to 2026-06-15T09:00:00Z; the model is neither
    discontinued nor pointed at a successor, so its own `msrp_cents` of 79900
    is the successor-MSRP base.
    """
    scenario.set_clock(SCENARIO_CLOCK_UTC)
    center = scenario.center()
    model = scenario.model()
    panel_lot = scenario.part_lot(model["id"]) if stock_panel_lot else None
    customer = scenario.customer()
    item = scenario.gear_item(model["id"], customer["id"])
    technician = scenario.technician(
        center["id"],
        employee_code="T-101",
        full_name="Ines Park",
        certifications=certifications or [factories.certification("FABRIC", 3)],
    )
    return World(
        scenario=scenario,
        center_id=center["id"],
        model_id=model["id"],
        panel_lot_id=panel_lot["id"] if panel_lot else None,
        customer_id=customer["id"],
        item_id=item["id"],
        technician_id=technician["id"],
    )


def _build_claim_with_one_assessment(scenario):
    """A claim in `UNDER_ASSESSMENT` carrying exactly one live bench finding.

    The finding is `MANUFACTURING_DEFECT` over a single 120-minute `FABRIC`
    lane with 4200 cents of estimated parts; the version the claim carried at
    submit time is kept so it can be replayed as a stale token.
    """
    world = _build_bench_world(scenario)
    claim = scenario.claim(world.center_id, world.item_id)
    submitted = scenario.submit(claim["id"])
    first = scenario.assess(
        claim["id"], world.technician_id, expected_claim_version=submitted["version"]
    )
    world.update(
        claim_id=claim["id"],
        submitted_version=submitted["version"],
        first_assessment=first,
        first_assessment_id=first["id"],
    )
    return world


def _reassessment_payload(expected_claim_version):
    """The second look: 90 `FABRIC` minutes and no parts spend."""
    return factories.assessment_payload(
        expected_claim_version,
        estimated_labor_lines=[factories.labor_line("FABRIC", 90)],
        estimated_parts_cents=0,
        defect_notes="Second look: no panel needed.",
    )


def _build_quoted_paid_order(scenario):
    """A PAID_REPAIR order already carrying one `SENT` `PROVISIONAL` quote.

    The claim is a `PAID_REPAIR_REQUEST` found `USER_DAMAGE` over a single
    35-minute `ZIPPER` lane; the first quote prices those 35 minutes plus one
    1800-cent slider for the PRO owner.
    """
    scenario.set_clock(SCENARIO_CLOCK_UTC)
    center = scenario.center()
    model = scenario.model()
    zip_lot = scenario.part_lot(
        model["id"],
        part_code=ZIP_PART_CODE,
        part_kind="ZIPPER_SLIDER",
        on_hand_units=4,
        unit_price_cents=1800,
        low_watermark_units=1,
    )
    customer = scenario.customer()
    item = scenario.gear_item(model["id"], customer["id"])
    technician = scenario.technician(
        center["id"],
        employee_code="T-101",
        full_name="Ines Park",
        certifications=[factories.certification("ZIPPER", 3)],
    )
    claim = scenario.claim(
        center["id"],
        item["id"],
        intake_kind="PAID_REPAIR_REQUEST",
        reported_defect_type="ZIPPER_FAILURE",
        customer_narrative="Slider chewed after a fall.",
    )
    submitted = scenario.submit(claim["id"])
    scenario.assess(
        claim["id"],
        technician["id"],
        expected_claim_version=submitted["version"],
        determination="USER_DAMAGE",
        required_work_types=["ZIPPER"],
        estimated_labor_lines=[factories.labor_line("ZIPPER", 35)],
        estimated_parts_cents=1800,
        defect_notes="Impact damage.",
    )
    scenario.decide(claim["id"])
    order = scenario.repair_order(claim["id"])
    first = scenario.estimate(
        order["id"],
        expected_repair_order_version=order["version"],
        labor_lines=[factories.labor_line("ZIPPER", 35)],
        parts_lines=[factories.parts_line(ZIP_PART_CODE, 1, 1800)],
    )
    return World(
        scenario=scenario,
        center_id=center["id"],
        model_id=model["id"],
        zip_lot_id=zip_lot["id"],
        customer_id=customer["id"],
        item_id=item["id"],
        technician_id=technician["id"],
        claim_id=claim["id"],
        order_id=order["id"],
        created_order_version=order["version"],
        first_estimate=first,
        first_estimate_id=first["id"],
    )


def _requote_payload(expected_repair_order_version):
    """The re-quote: 45 `ZIPPER` minutes against the same 1800-cent slider."""
    return factories.estimate_payload(
        expected_repair_order_version,
        labor_lines=[factories.labor_line("ZIPPER", 45)],
        parts_lines=[factories.parts_line(ZIP_PART_CODE, 1, 1800)],
    )


def _build_two_lane_order(scenario):
    """A WARRANTY_REPAIR order requiring both `FABRIC` and `ZIPPER`.

    T-101 holds FABRIC 3 and ZIPPER 3, T-102 holds FABRIC 1 and ZIPPER 2, both
    `ACTIVE` at the same centre with zero open minutes, so T-101 outranks
    T-102 in both lanes while T-102 still clears every lane's minimum level.
    """
    world = _build_bench_world(
        scenario,
        certifications=[
            factories.certification("FABRIC", 3),
            factories.certification("ZIPPER", 3),
        ],
    )
    second = scenario.technician(
        world.center_id,
        employee_code="T-102",
        full_name="Dev Osei",
        certifications=[
            factories.certification("FABRIC", 1),
            factories.certification("ZIPPER", 2),
        ],
    )
    claim = scenario.claim(
        world.center_id,
        world.item_id,
        customer_narrative="Floor seam split and the door slider is chewed.",
    )
    submitted = scenario.submit(claim["id"])
    scenario.assess(
        claim["id"],
        world.technician_id,
        expected_claim_version=submitted["version"],
        required_work_types=["FABRIC", "ZIPPER"],
        estimated_labor_lines=[
            factories.labor_line("FABRIC", 120),
            factories.labor_line("ZIPPER", 35),
        ],
        estimated_parts_cents=4200,
        defect_notes="Bond line plus slider.",
    )
    scenario.decide(claim["id"])
    order = scenario.repair_order(claim["id"])
    world.update(
        second_technician_id=second["id"],
        claim_id=claim["id"],
        order_id=order["id"],
        order=order,
    )
    return world


def _build_unsupported_model_with_two_assessed_claims(scenario):
    """Two units of a model that stocks no part lots at all, both assessed.

    Claim A is found `NORMAL_WEAR` and claim B `MANUFACTURING_DEFECT`, each
    over a single 120-minute `FABRIC` lane with no parts spend, so both live
    findings cost the same and only the determination differs.
    """
    world = _build_bench_world(scenario, stock_panel_lot=False)
    item_b = scenario.gear_item(
        world.model_id,
        world.customer_id,
        serial_number=factories.SERIAL_B,
        proof_of_purchase_ref="POS-88214",
    )

    claim_a = scenario.claim(
        world.center_id,
        world.item_id,
        reported_defect_type="ABRASION_WEAR",
        customer_narrative="Floor is scuffed through after many trips.",
    )
    submitted_a = scenario.submit(claim_a["id"])
    scenario.assess(
        claim_a["id"],
        world.technician_id,
        expected_claim_version=submitted_a["version"],
        determination="NORMAL_WEAR",
        estimated_parts_cents=0,
        defect_notes="Abrasion consistent with use.",
    )

    claim_b = scenario.claim(
        world.center_id,
        item_b["id"],
        customer_narrative="Factory seam let go on the second night.",
    )
    submitted_b = scenario.submit(claim_b["id"])
    scenario.assess(
        claim_b["id"],
        world.technician_id,
        expected_claim_version=submitted_b["version"],
        estimated_parts_cents=0,
        defect_notes="Bond line failure.",
    )

    world.update(
        item_a_id=world.item_id,
        item_b_id=item_b["id"],
        claim_a_id=claim_a["id"],
        claim_b_id=claim_b["id"],
    )
    return world


def _build_breached_order(scenario):
    """A QUEUED warranty order whose 14-day promise has fallen behind the clock.

    The commitment is frozen at the 2026-06-15T09:00:00Z instant — TENT_SHELTER
    base 12 days plus the largest FABRIC addition of 2, tier multiplier 1.00,
    no surge window and a `SUPPORTED` model so no parts wait — and the clock is
    then advanced to 2026-06-30T09:00:00Z.
    """
    world = _build_claim_with_one_assessment(scenario)
    scenario.decide(world.claim_id)
    order = scenario.repair_order(world.claim_id)
    scenario.set_clock(BREACH_CLOCK_UTC)
    world.update(order_id=order["id"], order=order)
    return world


class TestStaleClaimVersionOnReassessmentRejected:
    """The claim token must be re-read between two bench findings (PRD §2.7)."""

    def test_replayed_pre_assessment_token_is_refused_and_writes_nothing(
        self, scenario, api
    ):
        """Replaying the submit-time claim version yields ERR_STALE_CLAIM_VERSION and no assessment row.

        "If the value does not equal the claim's current `version` — because some other writer has advanced the claim since the client read it — the request is rejected with `ERR_STALE_CLAIM_VERSION` (HTTP 412) and no assessment row is created."
        "The reason this matters is that a second assessment supersedes every earlier assessment on the claim and rewrites `latest_determination` and `latest_repair_cost_cents`; a create issued from a stale view would silently overwrite a finding its author never saw."

        Design: Corner/cross_cutting_complexity_layers/stale_claim_version_on_reassessment_rejected
        """
        world = _build_claim_with_one_assessment(scenario)
        technician_headers = make_technician_headers(world.technician_id)
        before = scenario.read_claim(world.claim_id)

        response = api.create_assessment(
            world.claim_id,
            _reassessment_payload(world.submitted_version),
            technician_headers,
        )
        validate_error(response, ERR_STALE_CLAIM_VERSION)

        rows, meta = validate_paginated(
            api.list_claim_assessments(
                technician_headers, warranty_claim_id=world.claim_id
            )
        )
        assert meta["total_count"] == 1, meta
        assert [row["id"] for row in rows] == [world.first_assessment_id], rows

        claim = scenario.read_claim(world.claim_id)
        assert claim["assessment_count"] == 1, claim
        assert claim["latest_repair_cost_cents"] == 22390, claim
        assert claim["version"] == before["version"], claim

        stored_first = scenario.read_assessment(world.first_assessment_id)
        assert stored_first["is_superseded"] is False, stored_first

    def test_reread_token_is_accepted_and_supersedes_the_earlier_finding(
        self, scenario, api
    ):
        """The freshly read version is accepted, reprices the claim to 13643 and supersedes row one.

        "Both operations, on success, increment the guarded parent's `version` themselves, so a client that wants to write twice must re-read in between."
        "Every earlier assessment on the same claim has its `is_superseded` flag set to true, so exactly one row is ever the live finding."
        "The new row is created, the claim's `assessment_count` increases by one, and the claim's `latest_determination` and `latest_repair_cost_cents` are overwritten from the new row's `determination` and `estimated_repair_cost_cents`."

        Design: Corner/cross_cutting_complexity_layers/stale_claim_version_on_reassessment_rejected
        """
        world = _build_claim_with_one_assessment(scenario)
        current_version = scenario.claim_version(world.claim_id)
        assert current_version != world.submitted_version, current_version

        second = validate_success(
            api.create_assessment(
                world.claim_id,
                _reassessment_payload(current_version),
                make_technician_headers(world.technician_id),
            ),
            201,
        )
        assert second["estimated_repair_cost_cents"] == 13643, second
        assert second["is_superseded"] is False, second

        stored_first = scenario.read_assessment(world.first_assessment_id)
        assert stored_first["is_superseded"] is True, stored_first

        claim = scenario.read_claim(world.claim_id)
        assert claim["assessment_count"] == 2, claim
        assert claim["latest_determination"] == "MANUFACTURING_DEFECT", claim
        assert claim["latest_repair_cost_cents"] == 13643, claim
        assert claim["status"] == "UNDER_ASSESSMENT", claim
        assert claim["version"] > current_version, claim


class TestStaleRepairOrderVersionOnRequoteRejected:
    """The order token must be re-read before retiring a live quote (PRD §2.7)."""

    def test_replayed_creation_token_is_refused_and_leaves_the_quote_sent(
        self, scenario, api
    ):
        """Replaying the order's creation version yields ERR_STALE_REPAIR_ORDER_VERSION and no estimate row.

        "A request that issues a paid-repair estimate against a repair order must carry `expected_repair_order_version`, holding the `version` of that order as the client last observed it."
        "A mismatch with the order's current `version` is rejected with `ERR_STALE_REPAIR_ORDER_VERSION` (HTTP 412) and no estimate row is created — because issuing a new quote retires the order's live quote, and a stale-version create would retire a quote the writer never inspected."

        Design: Corner/cross_cutting_complexity_layers/stale_repair_order_version_on_requote_rejected
        """
        world = _build_quoted_paid_order(scenario)

        response = api.create_estimate(
            world.order_id,
            _requote_payload(world.created_order_version),
            SERVICE_AGENT_HEADERS,
        )
        validate_error(response, ERR_STALE_REPAIR_ORDER_VERSION)

        rows, meta = validate_paginated(
            api.list_order_estimates(world.order_id, SERVICE_AGENT_HEADERS)
        )
        assert meta["total_count"] == 1, meta
        assert [row["id"] for row in rows] == [world.first_estimate_id], rows

        stored_first = scenario.read_estimate(world.first_estimate_id)
        assert stored_first["status"] == "SENT", stored_first
        assert stored_first["total_cents"] == 7531, stored_first

        order = scenario.read_order(world.order_id)
        assert order["billing_status"] == "ESTIMATE_SENT", order

    def test_reread_token_supersedes_the_quote_and_reprices_the_order(
        self, scenario, api
    ):
        """The re-read version mints a 9182-cent PROVISIONAL row and supersedes the first quote.

        "On success any prior estimate on the order whose `status` was `SENT` becomes `SUPERSEDED`, a new estimate row is created with `variant` `PROVISIONAL` and `status` `SENT` and a `repair_order_id` pointing at the order, the order's `billing_status` becomes `ESTIMATE_SENT`, and the order's `version` increases by one."
        "**Step three** applies a capped shop supply fee on labour alone: `shop_supply_fee_cents` is the lesser of 2500 cents and seven percent of `labor_subtotal_cents` rounded half up."
        "**Step eight** totals: `total_cents` is `subtotal_cents` minus `loyalty_discount_cents` plus `expedite_fee_cents` plus `tax_cents`."

        Design: Corner/cross_cutting_complexity_layers/stale_repair_order_version_on_requote_rejected
        """
        world = _build_quoted_paid_order(scenario)
        current_version = scenario.order_version(world.order_id)
        assert current_version != world.created_order_version, current_version

        second = validate_success(
            api.create_estimate(
                world.order_id,
                _requote_payload(current_version),
                SERVICE_AGENT_HEADERS,
            ),
            201,
        )
        assert second["variant"] == "PROVISIONAL", second
        assert second["status"] == "SENT", second
        assert second["repair_order_id"] == world.order_id, second
        assert_estimate_breakdown(
            second,
            labor_subtotal_cents=7125,
            parts_subtotal_cents=1800,
            shop_supply_fee_cents=499,
            subtotal_cents=9424,
            loyalty_discount_cents=942,
            expedite_fee_cents=0,
            tax_cents=700,
            total_cents=9182,
        )
        assert second["valid_until"].startswith("2026-06-22T09:00:00"), second

        stored_first = scenario.read_estimate(world.first_estimate_id)
        assert stored_first["status"] == "SUPERSEDED", stored_first

        order = scenario.read_order(world.order_id)
        assert order["billing_status"] == "ESTIMATE_SENT", order

        rows, meta = validate_paginated(
            api.list_order_estimates(
                world.order_id, SERVICE_AGENT_HEADERS, status="SENT"
            )
        )
        assert meta["total_count"] == 1, meta
        assert [row["id"] for row in rows] == [second["id"]], rows


class TestSelectorFlagDistinguishesRoutedFromSuppliedTechnician:
    """`routed_by_selector` records who chose the technician (PRD §3.8)."""

    def test_routed_block_flags_true_while_a_named_technician_flags_false(
        self, scenario
    ):
        """The omitted-id FABRIC block routes to the level-3 bench with the flag true; the named level-2 technician keeps the ZIPPER block with the flag false.

        "The pool is then ranked, in order: first by the candidate's certification `level` for the requested `work_type`, highest first; then, among ties, by `scheduled_minutes_open`, lowest first; and finally, when both of those tie, by the technician's `created_at`, earliest first — never by `id`, and `created_at` is compared at millisecond resolution."
        "The winner is stamped onto the block's `technician_id` and the block's `routed_by_selector` flag is set to true; a block whose technician was supplied by the caller keeps `routed_by_selector` false."
        "On success the block's `duration_minutes` is the whole number of minutes between `start_at` and `end_at`, its `status` is `SCHEDULED`, its `actual_minutes` is null, the assigned technician's `scheduled_minutes_open` increases by `duration_minutes`, and — if this is the first block on the order — the order's `work_status` moves `QUEUED` → `IN_WORK`."

        Design: Corner/cross_cutting_complexity_layers/selector_flag_distinguishes_routed_from_supplied_technician
        """
        world = _build_two_lane_order(scenario)

        routed = scenario.work_block(
            world.order_id,
            work_type="FABRIC",
            start_at="2026-06-16T09:00:00Z",
            end_at="2026-06-16T11:00:00Z",
        )
        assert routed["technician_id"] == world.technician_id, routed
        assert routed["routed_by_selector"] is True, routed
        assert routed["duration_minutes"] == 120, routed
        assert routed["status"] == "SCHEDULED", routed
        assert routed["actual_minutes"] is None, routed

        supplied = scenario.work_block(
            world.order_id,
            world.second_technician_id,
            work_type="ZIPPER",
            start_at="2026-06-16T11:00:00Z",
            end_at="2026-06-16T12:00:00Z",
        )
        assert supplied["technician_id"] == world.second_technician_id, supplied
        assert supplied["routed_by_selector"] is False, supplied
        assert supplied["duration_minutes"] == 60, supplied
        assert supplied["status"] == "SCHEDULED", supplied

        first_bench = scenario.read_technician(world.technician_id)
        assert first_bench["scheduled_minutes_open"] == 120, first_bench
        second_bench = scenario.read_technician(world.second_technician_id)
        assert second_bench["scheduled_minutes_open"] == 60, second_bench

        order = scenario.read_order(world.order_id)
        assert order["work_status"] == "IN_WORK", order
        assert order["required_work_types"] == ["FABRIC", "ZIPPER"], order


class TestModelFeedbackCountersAndCenterRollupsReconcilePerDecision:
    """Disjoint feedback counters and the exposure rollup per outcome (PRD §3.5)."""

    def test_wear_denial_moves_only_the_wear_counter_and_reserves_nothing(
        self, scenario, api
    ):
        """A wear denial on an unsupported model bumps wear_denial_count to 1, leaves defect_claim_count at 0 and reserves no liability.

        "If it is `NORMAL_WEAR`, the outcome depends on the stockroom: `WEAR_DENIED` when the model's `parts_support_status` is `NO_SUPPORT`, and `PAID_REPAIR_OFFERED` otherwise."
        "No liability entry is created and no repair order follows; the unit's `disposition_status` stays at `AT_CENTER`."
        "The feedback signal is different from the warranty branches: the model's `wear_denial_count` increases by one and `defect_claim_count` is left untouched."

        Design: Corner/cross_cutting_complexity_layers/model_feedback_counters_and_center_rollups_reconcile_per_decision
        """
        world = _build_unsupported_model_with_two_assessed_claims(scenario)

        claim = scenario.decide(world.claim_a_id, decision_note="Wear, not a defect.")
        assert_claim_decision(claim, decision="WEAR_DENIED", status="WEAR_DENIED")
        assert claim["latest_repair_cost_cents"] == 18190, claim

        item = scenario.read_item(world.item_a_id)
        assert item["disposition_status"] == "AT_CENTER", item

        model = scenario.read_model(world.model_id)
        assert model["parts_support_status"] == "NO_SUPPORT", model
        assert model["wear_denial_count"] == 1, model
        assert model["defect_claim_count"] == 0, model
        assert model["irreparable_count"] == 0, model
        assert model["repairability_flag"] == "NONE", model

        rows, meta = validate_paginated(
            api.list_claim_liability_entries(world.claim_a_id, SERVICE_AGENT_HEADERS)
        )
        assert meta["total_count"] == 0, meta
        assert rows == [], rows

        center = scenario.read_center(world.center_id)
        assert_center_posture(center, 0, 0.0, "OPEN")

    def test_replacement_moves_only_the_defect_counter_and_the_center_rollup(
        self, scenario, api
    ):
        """After the denial, a replacement on the same model reads 1 wear / 1 defect / 0 irreparable with the flag still NONE, and the centre carries only the 71910 replacement.

        "If the model's `parts_support_status` is `NO_SUPPORT`, the outcome is `WARRANTY_REPLACE`, because there is nothing to repair the unit with."
        "As with a repair approval, the model's `defect_claim_count` increases by one and its `repairability_flag` is re-derived."
        "A model's `repairability_flag` becomes `REDESIGN_REQUESTED` when its `defect_claim_count` is at least five **and** its `irreparable_count` is at least two; failing that, it becomes `WATCH` when its `defect_claim_count` is at least three; and otherwise it is `NONE`."

        Design: Corner/cross_cutting_complexity_layers/model_feedback_counters_and_center_rollups_reconcile_per_decision
        """
        world = _build_unsupported_model_with_two_assessed_claims(scenario)
        scenario.decide(world.claim_a_id, decision_note="Wear, not a defect.")

        claim = scenario.decide(
            world.claim_b_id, decision_note="Defect with no serviceable parts."
        )
        assert_claim_decision(
            claim, decision="WARRANTY_REPLACE", status="REPLACEMENT_AUTHORIZED"
        )

        item_b = scenario.read_item(world.item_b_id)
        assert item_b["disposition_status"] == "IRREPARABLE_HOLD", item_b

        model = scenario.read_model(world.model_id)
        assert model["wear_denial_count"] == 1, model
        assert model["defect_claim_count"] == 1, model
        assert model["irreparable_count"] == 0, model
        assert model["repairability_flag"] == "NONE", model

        center = scenario.read_center(world.center_id)
        assert_center_posture(center, 71910, 1.44, "OPEN")
        assert center["active_queue_depth"] == 0, center

        entries = scenario.liability_entries(world.claim_b_id)
        assert len(entries) == 1, entries
        assert entries[0]["basis"] == "REPLACEMENT", entries[0]
        assert entries[0]["reserved_amount_cents"] == 71910, entries[0]

        rows, meta = validate_paginated(
            api.list_claim_liability_entries(world.claim_a_id, SERVICE_AGENT_HEADERS)
        )
        assert meta["total_count"] == 0, meta
        assert rows == [], rows


class TestQueueReviewFlagsBreachedCommitmentAndStampsTheCheckpoint:
    """The breach flag is checkpoint-driven, not read-derived (PRD §3.9)."""

    def test_breach_appears_only_once_the_checkpoint_runs(self, scenario, api):
        """The overdue order still reads commitment_breached false until the queue-review flags it and stamps last_queue_review_at.

        "`promised_return_at` is then the calendar date of the logical clock instant advanced by `promised_days` days, at 23:59:59.999Z on that date."
        "It flags every repair order at the centre whose `work_status` is non-terminal and whose `promised_return_at` has fallen behind the logical clock by setting that order's `commitment_breached` to true."
        "And it recomputes the centre's derived surface: `breached_commitment_count` becomes the number of orders flagged as breached by this run, `active_queue_depth` and `current_surge_multiplier` are recomputed, `open_liability_cents` and `liability_utilization_pct` are rolled up afresh, and `liability_posture` is re-derived on the bands of §2.9 — so a checkpoint alone can move a centre's posture in either direction."
        "`last_queue_review_at` is set to the logical clock instant."

        Design: Corner/cross_cutting_complexity_layers/queue_review_flags_breached_commitment_and_stamps_the_checkpoint
        """
        world = _build_breached_order(scenario)

        before = scenario.read_order(world.order_id)
        assert before["promised_days"] == 14, before
        assert before["promised_return_at"] == "2026-06-29T23:59:59.999Z", before
        assert before["commitment_breached"] is False, before
        assert before["work_status"] == "QUEUED", before

        center = scenario.queue_review(world.center_id)
        assert center["breached_commitment_count"] == 1, center
        assert center["last_queue_review_at"].startswith("2026-06-30T09:00:00"), center
        assert center["active_queue_depth"] == 1, center
        assert_multiplier(center["current_surge_multiplier"], 1.00)
        assert_center_posture(center, 22390, 0.45, "OPEN")

        rows, meta = validate_paginated(
            api.list_repair_orders(
                PROGRAM_ADMIN_HEADERS,
                service_center_id=world.center_id,
                commitment_breached="true",
            )
        )
        assert meta["total_count"] == 1, meta
        assert [row["id"] for row in rows] == [world.order_id], rows
        assert rows[0]["commitment_breached"] is True, rows[0]

        after = scenario.read_order(world.order_id)
        assert after["work_status"] == "QUEUED", after
        assert after["billing_status"] == "NOT_BILLABLE", after

        entries = scenario.liability_entries(world.claim_id)
        assert len(entries) == 1, entries
        assert entries[0]["basis"] == "REPAIR", entries[0]
        assert entries[0]["status"] == "OPEN", entries[0]
        assert entries[0]["reserved_amount_cents"] == 22390, entries[0]
