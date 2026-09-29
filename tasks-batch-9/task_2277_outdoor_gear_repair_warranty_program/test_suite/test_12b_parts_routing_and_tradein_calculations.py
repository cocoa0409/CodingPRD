"""Parts posture, substitution draws, bench routing and trade-in arithmetic.

The corners here are the parts wait folded into the turnaround commitment
(PRD §3.6), the discontinued-model substitution draw and its refusal
(PRD §2.10, §3.8), the lexicographic routing selector (PRD §3.8) and the
trade-in credit cap applied after the goodwill bonus (PRD §3.9).
"""

from test_helpers import (
    ERR_SUBSTITUTION_NOT_PERMITTED,
    assert_money_cents,
    assert_multiplier,
    assert_no_row_created,
    assert_part_lot_counts,
    assert_pct,
    factories,
    get_success_data,
    make_customer_headers,
    make_technician_headers,
    validate_error,
    validate_paginated,
    validate_success,
)


# --------------------------------------------------------------------------
# Local world builders. The harness restarts the server before every test, so
# each helper builds its whole precondition graph through PRD §4 endpoints.
# --------------------------------------------------------------------------
def _unsupported_model_paid_claim(scenario):
    """Centre, an Ascent 2P with no part lots at all, and a USER_DAMAGE claim."""
    scenario.set_clock()
    center = scenario.center()
    model = scenario.model()
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
    return {
        "center_id": center["id"],
        "model_id": model["id"],
        "customer_id": customer["id"],
        "item_id": item["id"],
        "technician_id": technician["id"],
        "claim_id": claim["id"],
    }


def _drain_own_lot_and_stock_successor(catalogue, **lot_overrides):
    """Empty the AS2 panel lot and stock an AS3 panel lot on the successor."""
    scenario = catalogue.scenario
    scenario.adjust_lot(
        catalogue.panel_lot_id, -5, reason="Bin emptied by earlier repairs."
    )
    successor_lot = scenario.part_lot(
        catalogue.successor_id,
        part_code="AS3-FLOOR-PANEL",
        part_kind="FABRIC_PANEL",
        on_hand_units=4,
        unit_price_cents=5100,
        low_watermark_units=1,
        **lot_overrides,
    )
    return successor_lot


def _replacement_authorized_pack(scenario):
    """A PACK_HARNESS unit whose defect claim reached REPLACEMENT_AUTHORIZED."""
    scenario.set_clock()
    center = scenario.center()
    model = scenario.model(
        model_code="PCK-EXPED-70",
        name="Expedition 70 Pack",
        category="PACK_HARNESS",
        msrp_cents=249900,
        release_year=2019,
        warranty_years=5,
    )
    customer = scenario.customer()
    item = scenario.gear_item(
        model["id"],
        customer["id"],
        serial_number="PK70-00042",
        purchase_price_cents=200000,
        proof_of_purchase_ref="POS-70042",
        condition_grade="A",
    )
    technician = scenario.technician(
        center["id"],
        employee_code="T-101",
        full_name="Ines Park",
        certifications=[factories.certification("FABRIC", 3)],
    )
    claim = scenario.claim(
        center["id"],
        item["id"],
        customer_narrative="Hipbelt tore off the frame sheet.",
    )
    submitted = scenario.submit(claim["id"])
    scenario.assess(
        claim["id"],
        technician["id"],
        expected_claim_version=submitted["version"],
        defect_notes="Bartack pattern missing from the factory.",
    )
    decided = scenario.decide(claim["id"])
    return {
        "center_id": center["id"],
        "model_id": model["id"],
        "customer_id": customer["id"],
        "item_id": item["id"],
        "claim_id": claim["id"],
        "claim": decided,
    }


class TestTurnaroundPartsWait:
    """PRD §3.6 — the parts posture read before any reservation of this request."""

    def test_no_support_model_adds_fourteen_parts_wait_days(
        self, api, scenario, agent_headers
    ):
        """An unstocked TENT_SHELTER zipper repair promises 29 days, not 15.

        "Failing both, it is `NO_SUPPORT`."
        "If it is `USER_DAMAGE`, the outcome is `PAID_REPAIR_OFFERED` — the customer
        broke it, and the brand will happily fix it for money."
        "First, the queue is snapshotted **before** the new order is inserted:
        `queue_depth_snapshot` is the count of repair orders at this centre whose
        `work_status` is `QUEUED`, `IN_WORK` or `BENCH_DONE`, excluding the row being
        created."
        "Second, a congestion tier is looked up on that snapshot: a snapshot of at most 9
        yields a tier multiplier of 1.00, at most 24 yields 1.25, at most 49 yields 1.60,
        and 50 or more yields 2.00."
        "Fourth, a parts wait is read from the model's `parts_support_status` **as it
        stands before any reservation created by this request**: zero days when
        `SUPPORTED`, seven days when `SUBSTITUTION_ONLY`, and fourteen days when
        `NO_SUPPORT`, recorded as `parts_wait_days`."
        "Fifth, base days are assembled from the model's `category` — ten days for
        `SHELL_APPAREL`, fourteen for `INSULATION`, twelve for `TENT_SHELTER`, nine for
        `PACK_HARNESS` and sixteen for `HARDGOODS_FRAME` — plus the largest work-type
        addition among the order's `required_work_types`, where fabric work adds two
        days, zipper work three, frame work five and insulation work six."
        "Sixth, `promised_days` is the base-day total multiplied by
        `surge_multiplier_applied`, rounded **up** to a whole number of days, and only
        then increased by `parts_wait_days`; the rounding up happens before the parts
        wait is added and never after."
        "`promised_return_at` is then the calendar date of the logical clock instant
        advanced by `promised_days` days, at 23:59:59.999Z on that date."
        "The order's `order_kind` follows the claim's `decision`: `WARRANTY_REPAIR` when
        the claim decided on warranty repair, and `PAID_REPAIR` when it offered paid
        repair."
        "The unit moves `AT_CENTER` → `IN_REPAIR`, and the order's bench dimension begins
        at `QUEUED` with `commitment_breached` false, `qc_fail_count` at 0,
        `paid_amount_cents` at 0, and `released_at`, `provisional_estimate_total_cents`
        and `final_invoice_total_cents` all null."
        "A paid order is minted with `billing_status` `ESTIMATE_PENDING`, and its bench
        dimension refuses to start until the money dimension has reached agreement."
        "The consequence is observable: immediately after a create, the centre's
        `active_queue_depth` equals the order's `queue_depth_snapshot` plus one."

        Design: Corner/calculations/no_support_model_adds_fourteen_parts_wait_days
        """
        world = _unsupported_model_paid_claim(scenario)
        model = scenario.read_model(world["model_id"])
        assert model["parts_support_status"] == "NO_SUPPORT", model

        response = api.create_repair_order(
            factories.repair_order_payload(world["claim_id"]), agent_headers
        )
        order = validate_success(response, 201)

        assert order["queue_depth_snapshot"] == 0, order
        assert_multiplier(order["surge_multiplier_applied"], 1.00)
        assert order["parts_wait_days"] == 14, order
        assert order["promised_days"] == 29, order
        assert order["promised_return_at"] == "2026-07-14T23:59:59.999Z", order

        assert order["order_kind"] == "PAID_REPAIR", order
        assert order["billing_status"] == "ESTIMATE_PENDING", order
        assert order["work_status"] == "QUEUED", order
        assert order["required_work_types"] == ["ZIPPER"], order

        item = scenario.read_item(world["item_id"])
        assert item["disposition_status"] == "IN_REPAIR", item
        center = scenario.read_center(world["center_id"])
        assert center["active_queue_depth"] == 1, center


class TestPartsSubstitutionDraw:
    """PRD §2.10 / §3.8 — the discontinued-model substitution path."""

    def test_successor_lot_substitution_accepted_for_discontinued_model(
        self, api, catalogue
    ):
        """A flagged AS3 lot serves an AS2 repair: only the successor lot's units move.

        "It is `DEPLETED` when `available_units` is zero; `LOW` when `available_units` is
        at least one and at most `low_watermark_units`; and `AVAILABLE` otherwise."
        "That model-level field is `SUPPORTED` when some part lot for the model has a
        `status` of `AVAILABLE` or `LOW`."
        "Failing that, it is `SUBSTITUTION_ONLY` when some part lot stocked for the
        model's `successor_model_id` has `substitution_allowed` set to true, has a
        non-null `substitute_for_part_code`, and has a `status` of `AVAILABLE` or `LOW`."
        "Fourth, a parts wait is read from the model's `parts_support_status` **as it
        stands before any reservation created by this request**: zero days when
        `SUPPORTED`, seven days when `SUBSTITUTION_ONLY`, and fourteen days when
        `NO_SUPPORT`, recorded as `parts_wait_days`."
        "`promised_return_at` is then the calendar date of the logical clock instant
        advanced by `promised_days` days, at 23:59:59.999Z on that date."
        "On a substitution draw, which is the discontinued-model path, the lot's
        `gear_model_id` must be either the order's model or that model's
        `successor_model_id`, or the draw is refused with `ERR_PART_MODEL_MISMATCH`; the
        lot's `substitution_allowed` must be true and its `substitute_for_part_code` must
        equal the `required_part_code`, and the lot's `part_kind` must equal the
        `part_kind` of the lot registered under the required code on the order's model or
        its successor — any of those three failing is refused with
        `ERR_SUBSTITUTION_NOT_PERMITTED` — and the reservation's `is_substitution` is set
        to true."
        "A successful reservation begins with `status` `RESERVED` and a null
        `settled_at`, increases the lot's `reserved_units` by `units`, recomputes the
        lot's `available_units`, re-derives the lot's `status`, and then re-derives
        `parts_support_status` on the lot's model."

        Design: Corner/calculations/successor_lot_substitution_accepted_for_discontinued_model
        """
        scenario = catalogue.scenario
        successor_lot = _drain_own_lot_and_stock_successor(
            catalogue,
            substitution_allowed=True,
            substitute_for_part_code=factories.PANEL_PART_CODE,
        )
        assert scenario.read_lot(catalogue.panel_lot_id)["status"] == "DEPLETED"
        assert (
            scenario.read_model(catalogue.model_id)["parts_support_status"]
            == "SUBSTITUTION_ONLY"
        )

        claim = scenario.claim(catalogue.center_id, catalogue.item_id)
        submitted = scenario.submit(claim["id"])
        scenario.assess(
            claim["id"],
            catalogue.technician_id,
            expected_claim_version=submitted["version"],
        )
        scenario.decide(claim["id"], decision_note="Defect confirmed.")
        order = scenario.repair_order(claim["id"])
        assert order["parts_wait_days"] == 7, order
        assert order["promised_days"] == 21, order
        assert order["promised_return_at"] == "2026-07-06T23:59:59.999Z", order

        response = api.create_parts_reservation(
            order["id"],
            factories.parts_reservation_payload(
                successor_lot["id"], factories.PANEL_PART_CODE, 1
            ),
            make_technician_headers(catalogue.technician_id),
        )
        reservation = validate_success(response, 201)
        assert reservation["is_substitution"] is True, reservation
        assert reservation["status"] == "RESERVED", reservation
        assert reservation["units"] == 1, reservation
        assert reservation["required_part_code"] == factories.PANEL_PART_CODE, reservation
        assert reservation["part_lot_id"] == successor_lot["id"], reservation

        assert_part_lot_counts(
            scenario.read_lot(successor_lot["id"]),
            on_hand_units=4,
            reserved_units=1,
            available_units=3,
            status="AVAILABLE",
        )
        assert_part_lot_counts(
            scenario.read_lot(catalogue.panel_lot_id),
            on_hand_units=0,
            reserved_units=0,
            available_units=0,
            status="DEPLETED",
        )
        assert (
            scenario.read_model(catalogue.successor_id)["parts_support_status"]
            == "SUPPORTED"
        )
        assert (
            scenario.read_model(catalogue.model_id)["parts_support_status"]
            == "SUBSTITUTION_ONLY"
        )

    def test_substitution_from_unflagged_successor_lot_rejected(self, api, catalogue):
        """Belonging to the successor model is not enough without the substitution flag.

        "Failing that, it is `SUBSTITUTION_ONLY` when some part lot stocked for the
        model's `successor_model_id` has `substitution_allowed` set to true, has a
        non-null `substitute_for_part_code`, and has a `status` of `AVAILABLE` or `LOW`."
        "Failing both, it is `NO_SUPPORT`."
        "Every request runs the same ordered gauntlet, and the **first** check that fails
        produces the response — no later check is evaluated, so a request that violates
        several rules always reports the earliest one."
        "(27) A substitution draw requires the lot's `substitution_allowed` to be true,
        its `substitute_for_part_code` to equal the requested `required_part_code`, and
        its `part_kind` to match, else `ERR_SUBSTITUTION_NOT_PERMITTED` (422)."
        "On a substitution draw, which is the discontinued-model path, the lot's
        `gear_model_id` must be either the order's model or that model's
        `successor_model_id`, or the draw is refused with `ERR_PART_MODEL_MISMATCH`; the
        lot's `substitution_allowed` must be true and its `substitute_for_part_code` must
        equal the `required_part_code`, and the lot's `part_kind` must equal the
        `part_kind` of the lot registered under the required code on the order's model or
        its successor — any of those three failing is refused with
        `ERR_SUBSTITUTION_NOT_PERMITTED` — and the reservation's `is_substitution` is set
        to true."
        "Fourth, a parts wait is read from the model's `parts_support_status` **as it
        stands before any reservation created by this request**: zero days when
        `SUPPORTED`, seven days when `SUBSTITUTION_ONLY`, and fourteen days when
        `NO_SUPPORT`, recorded as `parts_wait_days`."

        Design: Corner/calculations/substitution_from_unflagged_successor_lot_rejected
        """
        scenario = catalogue.scenario
        successor_lot = _drain_own_lot_and_stock_successor(catalogue)
        assert (
            scenario.read_model(catalogue.model_id)["parts_support_status"]
            == "NO_SUPPORT"
        )

        claim = scenario.claim(
            catalogue.center_id,
            catalogue.item_id,
            intake_kind="PAID_REPAIR_REQUEST",
            customer_narrative="Floor seam split after a snag.",
        )
        submitted = scenario.submit(claim["id"])
        scenario.assess(
            claim["id"],
            catalogue.technician_id,
            expected_claim_version=submitted["version"],
            determination="USER_DAMAGE",
            defect_notes="Snag damage.",
        )
        scenario.decide(claim["id"])
        order = scenario.repair_order(claim["id"])
        assert order["parts_wait_days"] == 14, order

        response = api.create_parts_reservation(
            order["id"],
            factories.parts_reservation_payload(
                successor_lot["id"], factories.PANEL_PART_CODE, 1
            ),
            make_technician_headers(catalogue.technician_id),
        )
        validate_error(response, ERR_SUBSTITUTION_NOT_PERMITTED)

        assert_part_lot_counts(
            scenario.read_lot(successor_lot["id"]),
            on_hand_units=4,
            reserved_units=0,
            available_units=4,
            status="AVAILABLE",
        )
        rows, _meta = validate_paginated(
            api.list_parts_reservations(
                make_technician_headers(catalogue.technician_id),
                repair_order_id=order["id"],
            )
        )
        assert_no_row_created(rows)


class TestTechnicianRoutingSelector:
    """PRD §3.8 — the candidate pool and its lexicographic ranking."""

    def test_selector_ranks_certification_level_then_open_minutes(
        self, api, scenario, agent_headers
    ):
        """Level 3 beats level 1, and among level 3 the idle bench beats the busy one.

        "The candidate pool is drawn only from technicians of the order's own centre
        whose roster `status` is `ACTIVE`, who hold a certification whose `work_type`
        equals the requested `work_type` at a `level` at or above that lane's minimum —
        level 1 for fabric, level 2 for zipper, frame and insulation — and who have no
        block in `status` `SCHEDULED` overlapping the requested interval on the same
        half-open test."
        "The pool is then ranked, in order: first by the candidate's certification
        `level` for the requested `work_type`, highest first; then, among ties, by
        `scheduled_minutes_open`, lowest first; and finally, when both of those tie, by
        the technician's `created_at`, earliest first — never by `id`, and `created_at`
        is compared at millisecond resolution."
        "The winner is stamped onto the block's `technician_id` and the block's
        `routed_by_selector` flag is set to true; a block whose technician was supplied
        by the caller keeps `routed_by_selector` false."
        "On success the block's `duration_minutes` is the whole number of minutes between
        `start_at` and `end_at`, its `status` is `SCHEDULED`, its `actual_minutes` is
        null, the assigned technician's `scheduled_minutes_open` increases by
        `duration_minutes`, and — if this is the first block on the order — the order's
        `work_status` moves `QUEUED` → `IN_WORK`."

        Design: Corner/calculations/selector_ranks_certification_level_then_open_minutes
        """
        scenario.set_clock()
        center = scenario.center()
        model = scenario.model()
        scenario.part_lot(model["id"])
        customer = scenario.customer()
        item = scenario.gear_item(model["id"], customer["id"])
        first = scenario.technician(
            center["id"],
            employee_code="T-101",
            full_name="Ines Park",
            certifications=[factories.certification("FABRIC", 3)],
        )
        second = scenario.technician(
            center["id"],
            employee_code="T-102",
            full_name="Dev Osei",
            certifications=[factories.certification("FABRIC", 3)],
        )
        third = scenario.technician(
            center["id"],
            employee_code="T-103",
            full_name="Nia Bloom",
            certifications=[factories.certification("FABRIC", 1)],
        )
        claim = scenario.claim(center["id"], item["id"])
        submitted = scenario.submit(claim["id"])
        scenario.assess(
            claim["id"], first["id"], expected_claim_version=submitted["version"]
        )
        scenario.decide(claim["id"])
        order = scenario.repair_order(claim["id"])
        pre_block = scenario.work_block(
            order["id"],
            first["id"],
            work_type="FABRIC",
            start_at="2026-06-16T09:00:00Z",
            end_at="2026-06-16T11:00:00Z",
        )
        assert pre_block["routed_by_selector"] is False, pre_block

        response = api.create_work_block(
            factories.work_block_payload(
                order["id"],
                work_type="FABRIC",
                start_at="2026-06-18T09:00:00Z",
                end_at="2026-06-18T10:30:00Z",
            ),
            agent_headers,
        )
        block = validate_success(response, 201)
        assert block["technician_id"] == second["id"], block
        assert block["routed_by_selector"] is True, block
        assert block["duration_minutes"] == 90, block
        assert block["status"] == "SCHEDULED", block

        assert scenario.read_technician(second["id"])["scheduled_minutes_open"] == 90
        assert scenario.read_technician(first["id"])["scheduled_minutes_open"] == 120
        assert scenario.read_technician(third["id"])["scheduled_minutes_open"] == 0
        assert scenario.read_order(order["id"])["work_status"] == "IN_WORK"

    def test_selector_tie_break_prefers_earlier_created_technician(
        self, api, scenario, agent_headers
    ):
        """Level and open minutes tied, the bench registered first takes the block.

        "The candidate pool is drawn only from technicians of the order's own centre
        whose roster `status` is `ACTIVE`, who hold a certification whose `work_type`
        equals the requested `work_type` at a `level` at or above that lane's minimum —
        level 1 for fabric, level 2 for zipper, frame and insulation — and who have no
        block in `status` `SCHEDULED` overlapping the requested interval on the same
        half-open test."
        "The pool is then ranked, in order: first by the candidate's certification
        `level` for the requested `work_type`, highest first; then, among ties, by
        `scheduled_minutes_open`, lowest first; and finally, when both of those tie, by
        the technician's `created_at`, earliest first — never by `id`, and `created_at`
        is compared at millisecond resolution."
        "The winner is stamped onto the block's `technician_id` and the block's
        `routed_by_selector` flag is set to true; a block whose technician was supplied
        by the caller keeps `routed_by_selector` false."

        Design: Corner/calculations/selector_tie_break_prefers_earlier_created_technician
        """
        scenario.set_clock()
        center = scenario.center()
        model = scenario.model()
        scenario.part_lot(
            model["id"],
            part_code=factories.ZIP_PART_CODE,
            part_kind="ZIPPER_SLIDER",
            on_hand_units=4,
            unit_price_cents=1800,
            low_watermark_units=1,
        )
        customer = scenario.customer()
        item = scenario.gear_item(model["id"], customer["id"])
        # Creation order is the tie-break: T-900 is registered before T-100.
        earlier = scenario.technician(
            center["id"],
            employee_code="T-900",
            full_name="Zoe Wren",
            certifications=[factories.certification("ZIPPER", 2)],
        )
        later = scenario.technician(
            center["id"],
            employee_code="T-100",
            full_name="Abe Lund",
            certifications=[factories.certification("ZIPPER", 2)],
        )
        claim = scenario.claim(
            center["id"],
            item["id"],
            reported_defect_type="ZIPPER_FAILURE",
            customer_narrative="Zipper teeth splitting.",
        )
        submitted = scenario.submit(claim["id"])
        scenario.assess(
            claim["id"],
            earlier["id"],
            expected_claim_version=submitted["version"],
            required_work_types=["ZIPPER"],
            estimated_labor_lines=[factories.labor_line("ZIPPER", 35)],
            estimated_parts_cents=1800,
            defect_notes="Coil defect.",
        )
        scenario.decide(claim["id"])
        order = scenario.repair_order(claim["id"])

        response = api.create_work_block(
            factories.work_block_payload(
                order["id"],
                work_type="ZIPPER",
                start_at="2026-06-16T09:00:00Z",
                end_at="2026-06-16T10:00:00Z",
            ),
            agent_headers,
        )
        block = validate_success(response, 201)
        assert block["technician_id"] == earlier["id"], block
        assert block["routed_by_selector"] is True, block

        assert scenario.read_technician(earlier["id"])["scheduled_minutes_open"] == 60
        assert scenario.read_technician(later["id"])["scheduled_minutes_open"] == 0


class TestTradeInCredit:
    """PRD §3.9 — the graded decay, the goodwill bonus and the cap after it."""

    def test_trade_in_credit_cap_binds_after_goodwill_bonus(
        self, api, scenario, agent_headers
    ):
        """Grade A on 140000 gives 49000 + 5000 = 54000, clipped to exactly 40000.

        "The depreciated value is then the greater of that residual floor and the unit's
        `purchase_price_cents` multiplied by one minus the depreciation fraction, rounded
        half up to whole cents."
        "The base list price is the successor model's `msrp_cents` when the unit's model
        has both a non-null `discontinued_at` and a non-null `successor_model_id`; in
        every other case it is the unit's own model's `msrp_cents`."
        "The successor valuation is that base list price multiplied by ninety percent,
        rounded half up to whole cents."
        "If the model's `parts_support_status` is `NO_SUPPORT`, the outcome is
        `WARRANTY_REPLACE`, because there is nothing to repair the unit with."
        "The unit moves `AT_CENTER` → `IRREPARABLE_HOLD` and thereby skips the bench
        entirely: **no repair order may ever be opened on a replacement-authorised
        claim**, and the unit goes straight into the trade-in lane."
        "The credit is a decay function on the depreciated basis: the base credit is the
        unit's `replacement_value_depreciated_cents` multiplied by the grade's rate —
        thirty-five percent for grade `A`, twenty-two percent for grade `B` and twelve
        percent for grade `C` — rounded half up."
        "A goodwill bonus of 5000 cents is then added when the claim that condemned the
        unit had a `decision` of `WARRANTY_REPAIR` or `WARRANTY_REPLACE`, and nothing is
        added otherwise."
        "The unit's `trade_in_credit_cents` is the lesser of 40000 cents and the base
        credit plus the goodwill bonus — the cap is applied **after** the bonus is added,
        never before."
        "At the same moment the unit's `refurb_list_price_cents` is set to its
        `replacement_value_successor_cents` multiplied by fifty-five percent, rounded
        half up."
        "The unit moves `IRREPARABLE_HOLD` → `TRADED_IN`, the owner's
        `trade_in_credit_cents` increases by the credit just granted, and the driving
        claim closes — `WARRANTY_APPROVED` → `CLOSED_REPLACED` or
        `REPLACEMENT_AUTHORIZED` → `CLOSED_REPLACED` — with every open liability entry on
        that claim moving to `RELEASED` with `release_reason` `CLAIM_CLOSED` and
        `released_at` stamped, after which the centre's `open_liability_cents` decreases
        by the released amounts and `liability_posture` is re-derived."

        Design: Corner/calculations/trade_in_credit_cap_binds_after_goodwill_bonus
        """
        world = _replacement_authorized_pack(scenario)
        assert world["claim"]["decision"] == "WARRANTY_REPLACE", world["claim"]

        before = scenario.read_item(world["item_id"])
        assert before["replacement_value_depreciated_cents"] == 140000, before
        assert before["replacement_value_successor_cents"] == 224910, before
        assert before["disposition_status"] == "IRREPARABLE_HOLD", before

        response = api.trade_in_gear_item(
            world["item_id"],
            {"condition_grade": "A"},
            make_customer_headers(world["customer_id"]),
        )
        item = validate_success(response, 200)
        assert_money_cents(item["trade_in_credit_cents"])
        assert item["trade_in_credit_cents"] == 40000, item
        assert item["refurb_list_price_cents"] == 123701, item
        assert item["disposition_status"] == "TRADED_IN", item

        owner = get_success_data(
            api.get_customer(world["customer_id"], agent_headers)
        )
        assert owner["trade_in_credit_cents"] == 40000, owner

    def test_trade_in_closes_the_claim_and_releases_the_replacement_reservation(
        self, api, scenario
    ):
        """Accepting the trade-in releases the 224910 replacement exposure to zero.

        "On success a liability entry is created with `basis` `REPLACEMENT`,
        `valuation_variant` `SUCCESSOR_MSRP`, `status` `OPEN` and a
        `reserved_amount_cents` equal to the unit's full
        `replacement_value_successor_cents`; the centre's `open_liability_cents` rises by
        that amount and `liability_posture` is re-derived."
        "`liability_utilization_pct` is one hundred multiplied by `open_liability_cents`
        divided by `liability_cap_cents`, rounded half up to two decimal places, and is
        display-only."
        "Otherwise, if `open_liability_cents` multiplied by one hundred is strictly
        greater than sixty multiplied by `liability_cap_cents`, the posture is
        `CONSTRAINED`."
        "Otherwise it is `OPEN`."
        "The unit moves `IRREPARABLE_HOLD` → `TRADED_IN`, the owner's
        `trade_in_credit_cents` increases by the credit just granted, and the driving
        claim closes — `WARRANTY_APPROVED` → `CLOSED_REPLACED` or
        `REPLACEMENT_AUTHORIZED` → `CLOSED_REPLACED` — with every open liability entry on
        that claim moving to `RELEASED` with `release_reason` `CLAIM_CLOSED` and
        `released_at` stamped, after which the centre's `open_liability_cents` decreases
        by the released amounts and `liability_posture` is re-derived."

        Design: Corner/calculations/trade_in_credit_cap_binds_after_goodwill_bonus
        """
        world = _replacement_authorized_pack(scenario)

        entries = scenario.liability_entries(world["claim_id"])
        assert len(entries) == 1, entries
        assert entries[0]["basis"] == "REPLACEMENT", entries[0]
        assert entries[0]["valuation_variant"] == "SUCCESSOR_MSRP", entries[0]
        assert entries[0]["status"] == "OPEN", entries[0]
        assert entries[0]["reserved_amount_cents"] == 224910, entries[0]

        center_before = scenario.read_center(world["center_id"])
        assert center_before["open_liability_cents"] == 224910, center_before
        assert_pct(center_before["liability_utilization_pct"], 4.50)

        validate_success(
            api.trade_in_gear_item(
                world["item_id"],
                {"condition_grade": "A"},
                make_customer_headers(world["customer_id"]),
            ),
            200,
        )

        claim = scenario.read_claim(world["claim_id"])
        assert claim["status"] == "CLOSED_REPLACED", claim

        settled = scenario.liability_entries(world["claim_id"])
        assert len(settled) == 1, settled
        assert settled[0]["status"] == "RELEASED", settled[0]
        assert settled[0]["release_reason"] == "CLAIM_CLOSED", settled[0]
        assert settled[0]["reserved_amount_cents"] == 224910, settled[0]
        assert settled[0]["released_at"] is not None, settled[0]

        center_after = scenario.read_center(world["center_id"])
        assert center_after["open_liability_cents"] == 0, center_after
        assert_pct(center_after["liability_utilization_pct"], 0.0)
        assert center_after["liability_posture"] == "OPEN", center_after
