"""Corner validations — claim intake gates, bench limits and stockroom arithmetic.

The harness restarts the API against an empty database before every test, so
each test builds its own centre, catalogue, owner, unit, bench and order through
the endpoints of PRD §4.
"""

from test_helpers import (
    ERR_BENCH_CAPACITY_EXCEEDED,
    ERR_INSUFFICIENT_PART_UNITS,
    ERR_INSUFFICIENT_STOCK_ADJUSTMENT,
    ERR_INVALID_UNITS,
    ERR_INVALID_WINDOW,
    ERR_PART_LOT_NOT_FOUND,
    ERR_PARTS_NOT_SETTLED,
    ERR_PROOF_OF_PURCHASE_MISSING,
    ERR_PURCHASE_DATE_IN_FUTURE,
    ERR_REPAIR_ORDER_NOT_FOUND,
    ERR_WARRANTY_EXPIRED,
    ERR_WORK_BLOCK_NOT_ON_ORDER,
    ERR_WORK_TYPES_INCOMPLETE,
    NON_EXISTENT_UUID,
    PARTS_COORDINATOR_HEADERS,
    PROGRAM_ADMIN_HEADERS,
    SERVICE_AGENT_HEADERS,
    World,
    assert_multiplier,
    assert_no_row_created,
    assert_part_lot_counts,
    assert_pct,
    factories,
    make_technician_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

# A well-formed UUID that addresses no row, distinct from the path identifier.
UNKNOWN_PART_LOT_ID = "00000000-0000-4000-8000-000000000998"


def _certs(pairs):
    return [factories.certification(work_type, level) for work_type, level in pairs]


def _repair_order_world(
    scenario,
    center_overrides=None,
    lot_overrides=None,
    certifications=(("FABRIC", 3),),
    claim_overrides=None,
    assessment_overrides=None,
):
    """Clock, centre, model, stocked lot, owner, unit, technician, QUEUED order."""
    scenario.set_clock()
    center = scenario.center(**(center_overrides or {}))
    model = scenario.model()
    lot = scenario.part_lot(model["id"], **(lot_overrides or {}))
    customer = scenario.customer()
    item = scenario.gear_item(model["id"], customer["id"])
    technician = scenario.technician(
        center["id"], certifications=_certs(certifications)
    )
    claim = scenario.claim(center["id"], item["id"], **(claim_overrides or {}))
    submitted = scenario.submit(claim["id"])
    assessment = scenario.assess(
        claim["id"],
        technician["id"],
        expected_claim_version=submitted["version"],
        **(assessment_overrides or {}),
    )
    decided = scenario.decide(claim["id"], decision_note="Defect confirmed on the bench.")
    order = scenario.repair_order(claim["id"])
    return World(
        center=center,
        center_id=center["id"],
        model=model,
        model_id=model["id"],
        lot=lot,
        lot_id=lot["id"],
        customer=customer,
        customer_id=customer["id"],
        item=item,
        item_id=item["id"],
        technician=technician,
        technician_id=technician["id"],
        claim=decided,
        claim_id=claim["id"],
        assessment=assessment,
        assessment_id=assessment["id"],
        order=order,
        order_id=order["id"],
    )


class TestProofRequirementScope:
    def test_warranty_submit_needs_proof_paid_repair_waives_it(self, api, scenario):
        """An undocumented unit fails a warranty submit and passes a paid-repair submit.

        "The `intake_kind` defaults to `WARRANTY_CLAIM` and may instead be `PAID_REPAIR_REQUEST`; the distinction is decisive at submit time, because a `WARRANTY_CLAIM` demands both proof of purchase and unexpired coverage while a `PAID_REPAIR_REQUEST` waives both."
        "A warranty intake with no verifiable proof is refused with `ERR_PROOF_OF_PURCHASE_MISSING`, and a warranty intake on a unit whose coverage has lapsed is refused with `ERR_WARRANTY_EXPIRED`."
        "On success the claim's `submitted_at` is stamped with the logical clock instant, the unit moves `WITH_CUSTOMER` → `AT_CENTER` because the centre now has custody, and the owning customer's `lifetime_claim_count` increases by one."

        Design: Corner/validations/proof_requirement_applies_only_to_warranty_intake
        """
        scenario.set_clock()
        center = scenario.center()
        model = scenario.model()
        customer = scenario.customer()
        item = scenario.gear_item(
            model["id"],
            customer["id"],
            proof_of_purchase_type=factories.OMIT,
            proof_of_purchase_ref=factories.OMIT,
        )
        assert item["proof_of_purchase_type"] == "NONE", item

        warranty_claim = scenario.claim(
            center["id"],
            item["id"],
            intake_kind="WARRANTY_CLAIM",
            customer_narrative="Seam split, receipt lost.",
        )
        paid_claim = scenario.claim(
            center["id"],
            item["id"],
            intake_kind="PAID_REPAIR_REQUEST",
            customer_narrative="Happy to pay for the same seam.",
        )
        assert warranty_claim["proof_verified"] is False, warranty_claim
        assert paid_claim["proof_verified"] is False, paid_claim

        refused = api.submit_claim(warranty_claim["id"], SERVICE_AGENT_HEADERS)
        validate_error(refused, ERR_PROOF_OF_PURCHASE_MISSING)

        blocked = scenario.read_claim(warranty_claim["id"])
        assert blocked["status"] == "DRAFT", blocked
        assert blocked["submitted_at"] is None, blocked
        assert scenario.read_item(item["id"])["disposition_status"] == "WITH_CUSTOMER"
        assert scenario.read_customer(customer["id"])["lifetime_claim_count"] == 0

        accepted = validate_success(
            api.submit_claim(paid_claim["id"], SERVICE_AGENT_HEADERS)
        )
        assert accepted["status"] == "SUBMITTED", accepted
        assert accepted["submitted_at"].startswith("2026-06-15T09:00:00"), accepted
        assert scenario.read_item(item["id"])["disposition_status"] == "AT_CENTER"
        assert scenario.read_customer(customer["id"])["lifetime_claim_count"] == 1


class TestExpiredWarrantyBeatsMissingProof:
    def test_lapsed_coverage_reported_before_absent_proof(self, api, scenario):
        """A submit that breaks both the coverage rule and the documentation rule reports coverage.

        "Every request runs the same ordered gauntlet, and the **first** check that fails produces the response — no later check is evaluated, so a request that violates several rules always reports the earliest one."
        "(31) For an intake whose `intake_kind` is `WARRANTY_CLAIM`, the unit's `warranty_state` is not `EXPIRED`, else `ERR_WARRANTY_EXPIRED` (422)."
        "(36) For a `WARRANTY_CLAIM` intake, the unit carries proof of purchase, else `ERR_PROOF_OF_PURCHASE_MISSING` (422)."

        Design: Corner/validations/expired_warranty_beats_missing_proof_on_submit
        """
        scenario.set_clock()
        center = scenario.center()
        model = scenario.model()
        customer = scenario.customer()
        item = scenario.gear_item(
            model["id"],
            customer["id"],
            serial_number="AS2-00901",
            purchase_date="2019-01-10T00:00:00Z",
            condition_grade="C",
            proof_of_purchase_type=factories.OMIT,
            proof_of_purchase_ref=factories.OMIT,
        )
        assert item["age_months"] == 89, item
        assert item["warranty_state"] == "EXPIRED", item
        assert item["proof_of_purchase_type"] == "NONE", item

        claim = scenario.claim(
            center["id"],
            item["id"],
            intake_kind="WARRANTY_CLAIM",
            reported_defect_type="DELAMINATION",
            customer_narrative="Coating peeling, no receipt.",
        )

        refused = api.submit_claim(claim["id"], SERVICE_AGENT_HEADERS)
        validate_error(refused, ERR_WARRANTY_EXPIRED)
        assert refused.json()["data"]["error_id"] != ERR_PROOF_OF_PURCHASE_MISSING

        blocked = scenario.read_claim(claim["id"])
        assert blocked["status"] == "DRAFT", blocked
        assert blocked["proof_verified"] is False, blocked
        assert scenario.read_customer(customer["id"])["lifetime_claim_count"] == 0


class TestFuturePurchaseDate:
    def test_tomorrow_refused_today_registered(self, api, scenario):
        """A purchase date after the logical clock is refused while today's date registers.

        "A **gear unit** is the physical thing on the bench. Either its owner or a `ServiceAgent` registers it with a `gear_model_id` naming the catalogue model it instantiates, an `owner_customer_id` naming the registered owner who may thereafter file claims and approve quotes, a `serial_number` of three to forty characters that must be unique among units of the same model, a `purchase_date` that may not be later than the logical clock instant, and a `purchase_price_cents` of zero or more."
        "(30) A unit's `purchase_date` is not after the logical clock instant, else `ERR_PURCHASE_DATE_IN_FUTURE` (422)."
        "The depreciated value is then the greater of that residual floor and the unit's `purchase_price_cents` multiplied by one minus the depreciation fraction, rounded half up to whole cents."
        "The successor valuation is that base list price multiplied by ninety percent, rounded half up to whole cents."

        Design: Corner/validations/future_purchase_date_rejected_same_day_accepted
        """
        scenario.set_clock()
        model = scenario.model()
        customer = scenario.customer()

        refused = api.create_gear_item(
            factories.gear_item_payload(
                model["id"],
                customer["id"],
                serial_number="AS2-01000",
                purchase_date="2026-06-16T00:00:00Z",
                proof_of_purchase_type=factories.OMIT,
                proof_of_purchase_ref=factories.OMIT,
                condition_grade=factories.OMIT,
            ),
            SERVICE_AGENT_HEADERS,
        )
        validate_error(refused, ERR_PURCHASE_DATE_IN_FUTURE)
        rows, _ = validate_paginated(api.list_gear_items(SERVICE_AGENT_HEADERS))
        assert_no_row_created(rows)

        accepted = validate_success(
            api.create_gear_item(
                factories.gear_item_payload(
                    model["id"],
                    customer["id"],
                    serial_number="AS2-01001",
                    purchase_date="2026-06-15T00:00:00Z",
                    proof_of_purchase_type=factories.OMIT,
                    proof_of_purchase_ref=factories.OMIT,
                    condition_grade=factories.OMIT,
                ),
                SERVICE_AGENT_HEADERS,
            ),
            201,
        )
        assert accepted["age_months"] == 0, accepted
        assert accepted["warranty_state"] == "IN_WARRANTY", accepted
        assert accepted["replacement_value_depreciated_cents"] == 74900, accepted
        assert accepted["replacement_value_successor_cents"] == 71910, accepted
        assert accepted["disposition_status"] == "WITH_CUSTOMER", accepted
        assert accepted["proof_of_purchase_type"] == "NONE", accepted


class TestPathIdBeforeBodyId:
    def test_unknown_order_in_path_reported_before_unknown_lot_in_body(
        self, api, scenario
    ):
        """An unresolvable path order outranks an unresolvable body part lot.

        "Every request runs the same ordered gauntlet, and the **first** check that fails produces the response — no later check is evaluated, so a request that violates several rules always reports the earliest one."
        "(6) Every identifier in the URL path resolves, validated left to right, so that the leftmost unresolvable segment is the one reported."
        "(8) Second-level body references resolve: the `part_lot_id` on a reservation, an explicitly supplied `technician_id` on a work block, and every `work_block_id` inside a bench-complete `work_log`, reported as `ERR_PART_LOT_NOT_FOUND`, `ERR_TECHNICIAN_NOT_FOUND` or `ERR_WORK_BLOCK_NOT_FOUND`."

        Design: Corner/validations/path_id_existence_checked_before_body_id_not_found
        """
        scenario.set_clock()
        center = scenario.center()
        technician = scenario.technician(
            center["id"], certifications=_certs((("FABRIC", 3),))
        )

        refused = api.create_parts_reservation(
            NON_EXISTENT_UUID,
            factories.parts_reservation_payload(
                UNKNOWN_PART_LOT_ID, factories.PANEL_PART_CODE, 1
            ),
            make_technician_headers(technician["id"]),
        )
        validate_error(refused, ERR_REPAIR_ORDER_NOT_FOUND)
        assert refused.json()["data"]["error_id"] != ERR_PART_LOT_NOT_FOUND

        rows, meta = validate_paginated(
            api.list_parts_reservations(PARTS_COORDINATOR_HEADERS)
        )
        assert meta["total_count"] == 0, meta
        assert_no_row_created(rows)


class TestBenchCapacityPerUtcDate:
    def test_third_block_on_a_full_date_refused_next_date_accepted(
        self, api, scenario
    ):
        """The daily ceiling is bucketed by the block's UTC date, not by the centre's total.

        "The centre also has a daily bench ceiling: if the number of blocks at this centre already in `status` `SCHEDULED` whose `start_at` falls on the new block's UTC calendar date has reached `bench_capacity_blocks_per_day`, the request is refused with `ERR_BENCH_CAPACITY_EXCEEDED`."
        "(41) The count of scheduled blocks at the centre on the new block's UTC calendar date is below `bench_capacity_blocks_per_day`, else `ERR_BENCH_CAPACITY_EXCEEDED` (409)."
        "On success the block's `duration_minutes` is the whole number of minutes between `start_at` and `end_at`, its `status` is `SCHEDULED`, its `actual_minutes` is null, the assigned technician's `scheduled_minutes_open` increases by `duration_minutes`, and — if this is the first block on the order — the order's `work_status` moves `QUEUED` → `IN_WORK`."

        Design: Corner/validations/bench_capacity_counts_scheduled_blocks_per_utc_date
        """
        world = _repair_order_world(
            scenario, center_overrides={"bench_capacity_blocks_per_day": 2}
        )
        scenario.work_block(
            world.order_id,
            world.technician_id,
            start_at="2026-06-16T09:00:00Z",
            end_at="2026-06-16T10:00:00Z",
        )
        scenario.work_block(
            world.order_id,
            world.technician_id,
            start_at="2026-06-16T10:00:00Z",
            end_at="2026-06-16T11:00:00Z",
        )

        refused = api.create_work_block(
            factories.work_block_payload(
                world.order_id,
                start_at="2026-06-16T11:00:00Z",
                end_at="2026-06-16T12:00:00Z",
                technician_id=world.technician_id,
            ),
            SERVICE_AGENT_HEADERS,
        )
        validate_error(refused, ERR_BENCH_CAPACITY_EXCEEDED)
        assert scenario.read_technician(world.technician_id)["scheduled_minutes_open"] == 120

        accepted = validate_success(
            api.create_work_block(
                factories.work_block_payload(
                    world.order_id,
                    start_at="2026-06-17T09:00:00Z",
                    end_at="2026-06-17T10:00:00Z",
                    technician_id=world.technician_id,
                ),
                SERVICE_AGENT_HEADERS,
            ),
            201,
        )
        assert accepted["duration_minutes"] == 60, accepted
        assert accepted["status"] == "SCHEDULED", accepted
        assert accepted["routed_by_selector"] is False, accepted
        assert scenario.read_technician(world.technician_id)["scheduled_minutes_open"] == 180

        _, meta = validate_paginated(
            api.list_work_blocks(
                SERVICE_AGENT_HEADERS,
                repair_order_id=world.order_id,
                status="SCHEDULED",
            )
        )
        assert meta["total_count"] == 3, meta


class TestEveryRequiredWorkTypeCompleted:
    def test_partial_work_log_refused_full_log_accepted(self, api, scenario):
        """A log leaving a required lane unworked is refused whole; the two-lane log passes.

        "Furthermore, after the log is applied, every entry of the order's `required_work_types` must have at least one completed block on the order; a log that leaves a required lane unworked is refused with `ERR_WORK_TYPES_INCOMPLETE`."
        "(46) After applying the `work_log`, every entry of the order's `required_work_types` has at least one completed block, else `ERR_WORK_TYPES_INCOMPLETE` (409)."
        "On success each listed block moves `SCHEDULED` → `COMPLETED` with its `actual_minutes` stamped, and for each block the technician's `scheduled_minutes_open` decreases by that block's `duration_minutes` while their `completed_minutes` increases by that block's `actual_minutes`."

        Design: Corner/validations/every_required_work_type_needs_a_completed_block
        """
        world = _repair_order_world(
            scenario,
            certifications=(("FABRIC", 3), ("ZIPPER", 3)),
            claim_overrides={
                "customer_narrative": "Seam split and the door zipper is failing."
            },
            assessment_overrides={
                "required_work_types": ["FABRIC", "ZIPPER"],
                "estimated_labor_lines": [
                    factories.labor_line("FABRIC", 120),
                    factories.labor_line("ZIPPER", 35),
                ],
                "estimated_parts_cents": 4200,
                "defect_notes": "Bond line plus a defective coil.",
            },
        )
        assert world.assessment["estimated_repair_cost_cents"] == 28320, world.assessment
        assert world.claim["decision"] == "WARRANTY_REPAIR", world.claim
        assert_pct(world.claim["repair_ratio_pct"], 39.38)
        assert world.order["required_work_types"] == ["FABRIC", "ZIPPER"], world.order
        assert world.order["promised_days"] == 15, world.order
        assert world.order["promised_return_at"] == "2026-06-30T23:59:59.999Z", world.order

        fabric_block = scenario.work_block(
            world.order_id,
            world.technician_id,
            work_type="FABRIC",
            start_at="2026-06-16T09:00:00Z",
            end_at="2026-06-16T10:30:00Z",
        )
        zipper_block = scenario.work_block(
            world.order_id,
            world.technician_id,
            work_type="ZIPPER",
            start_at="2026-06-17T09:00:00Z",
            end_at="2026-06-17T09:40:00Z",
        )

        refused = api.bench_complete(
            world.order_id,
            {"work_log": [factories.work_log_entry(fabric_block["id"], 90)]},
            make_technician_headers(world.technician_id),
        )
        validate_error(refused, ERR_WORK_TYPES_INCOMPLETE)

        held = scenario.read_work_block(fabric_block["id"])
        assert held["status"] == "SCHEDULED", held
        assert held["actual_minutes"] is None, held
        assert scenario.read_order(world.order_id)["work_status"] == "IN_WORK"
        technician = scenario.read_technician(world.technician_id)
        assert technician["scheduled_minutes_open"] == 130, technician
        assert technician["completed_minutes"] == 0, technician

        accepted = validate_success(
            api.bench_complete(
                world.order_id,
                {
                    "work_log": [
                        factories.work_log_entry(fabric_block["id"], 90),
                        factories.work_log_entry(zipper_block["id"], 40),
                    ]
                },
                make_technician_headers(world.technician_id),
            )
        )
        assert accepted["work_status"] == "BENCH_DONE", accepted
        assert scenario.read_work_block(fabric_block["id"])["actual_minutes"] == 90
        assert scenario.read_work_block(fabric_block["id"])["status"] == "COMPLETED"
        assert scenario.read_work_block(zipper_block["id"])["actual_minutes"] == 40
        assert scenario.read_work_block(zipper_block["id"])["status"] == "COMPLETED"
        technician = scenario.read_technician(world.technician_id)
        assert technician["scheduled_minutes_open"] == 0, technician
        assert technician["completed_minutes"] == 130, technician


class TestBenchCompleteForeignWorkBlock:
    def test_block_belonging_to_another_order_refused(self, api, scenario):
        """A block that exists but hangs off a sibling order is a 422 ownership failure.

        "Every referenced block must belong to the addressed order and must be in `status` `SCHEDULED`, or the request is refused with `ERR_WORK_BLOCK_NOT_ON_ORDER`."
        "(28) Every `work_block_id` in a bench-complete `work_log` belongs to the addressed order and has `status` `SCHEDULED`, else `ERR_WORK_BLOCK_NOT_ON_ORDER` (422)."

        Design: Corner/validations/bench_complete_rejects_work_block_from_another_order
        """
        world = _repair_order_world(
            scenario, claim_overrides={"customer_narrative": "Unit A seam."}
        )
        item_b = scenario.gear_item(
            world.model_id,
            world.customer_id,
            serial_number=factories.SERIAL_B,
            proof_of_purchase_ref="POS-88214",
        )
        claim_b = scenario.claim(
            world.center_id, item_b["id"], customer_narrative="Unit B seam."
        )
        submitted_b = scenario.submit(claim_b["id"])
        scenario.assess(
            claim_b["id"],
            world.technician_id,
            expected_claim_version=submitted_b["version"],
            defect_notes="Bond line B.",
        )
        scenario.decide(claim_b["id"], decision_note="Defect confirmed on unit B.")
        order_b = scenario.repair_order(claim_b["id"])
        assert order_b["queue_depth_snapshot"] == 1, order_b
        assert_multiplier(order_b["surge_multiplier_applied"], 1.00)

        scenario.work_block(
            world.order_id,
            world.technician_id,
            start_at="2026-06-16T09:00:00Z",
            end_at="2026-06-16T10:00:00Z",
        )
        block_b = scenario.work_block(
            order_b["id"],
            world.technician_id,
            start_at="2026-06-16T10:00:00Z",
            end_at="2026-06-16T11:00:00Z",
        )

        refused = api.bench_complete(
            world.order_id,
            {"work_log": [factories.work_log_entry(block_b["id"], 60)]},
            make_technician_headers(world.technician_id),
        )
        validate_error(refused, ERR_WORK_BLOCK_NOT_ON_ORDER)

        assert scenario.read_order(world.order_id)["work_status"] == "IN_WORK"
        assert scenario.read_order(order_b["id"])["work_status"] == "IN_WORK"
        held = scenario.read_work_block(block_b["id"])
        assert held["status"] == "SCHEDULED", held
        assert held["actual_minutes"] is None, held
        assert held["repair_order_id"] == order_b["id"], held
        technician = scenario.read_technician(world.technician_id)
        assert technician["scheduled_minutes_open"] == 120, technician
        assert technician["completed_minutes"] == 0, technician


class TestQualityControlWaitsForParts:
    def test_reserved_reservation_blocks_qc_until_consumed(self, api, scenario):
        """A still-reserved part blocks the QC signature; consuming it unblocks the same call.

        "And no reservation on the order may still be in `status` `RESERVED`, or the request is refused with `ERR_PARTS_NOT_SETTLED`; every drawn part must have been either consumed or released before the unit can pass."
        "(47) No reservation on the order is still `RESERVED` when quality control is signed, else `ERR_PARTS_NOT_SETTLED` (409)."
        "A `RepairTechnician` **consumes** it — permitted while its `status` is `RESERVED` and the order's `work_status` is `QUEUED`, `IN_WORK` or `BENCH_DONE` — moving it `RESERVED` → `CONSUMED`, stamping `settled_at`, and decreasing **both** the lot's `on_hand_units` and its `reserved_units` by `units`, so `available_units` does not change; the lot's `status` is re-derived and then the model's `parts_support_status`."
        "A passing inspection moves the order `BENCH_DONE` → `QC_PASSED`."

        Design: Corner/validations/qc_blocked_until_every_reservation_is_settled
        """
        world = _repair_order_world(scenario)
        signer = scenario.technician(
            world.center_id,
            employee_code="T-102",
            full_name="Dev Osei",
            certifications=_certs((("FABRIC", 2),)),
        )
        reservation = scenario.reserve_parts(
            world.order_id, world.lot_id, factories.PANEL_PART_CODE, 1
        )
        block = scenario.work_block(
            world.order_id,
            world.technician_id,
            start_at="2026-06-16T09:00:00Z",
            end_at="2026-06-16T10:30:00Z",
        )
        scenario.bench_complete(
            world.order_id,
            world.technician_id,
            [factories.work_log_entry(block["id"], 90)],
        )

        refused = api.create_qc_inspection(
            world.order_id,
            {"outcome": "PASS", "notes": "Looks good."},
            make_technician_headers(signer["id"]),
        )
        validate_error(refused, ERR_PARTS_NOT_SETTLED)
        held = scenario.read_order(world.order_id)
        assert held["work_status"] == "BENCH_DONE", held
        assert held["qc_fail_count"] == 0, held

        settled = scenario.consume_parts(reservation["id"], world.technician_id)
        assert settled["status"] == "CONSUMED", settled
        assert settled["settled_at"].startswith("2026-06-15T09:00:00"), settled
        assert_part_lot_counts(
            scenario.read_lot(world.lot_id), 4, 0, 4, status="AVAILABLE"
        )

        accepted = validate_success(
            api.create_qc_inspection(
                world.order_id,
                {"outcome": "PASS", "notes": "Panel fitted, second look."},
                make_technician_headers(signer["id"]),
            )
        )
        assert accepted["work_status"] == "QC_PASSED", accepted
        assert accepted["qc_fail_count"] == 0, accepted
        assert scenario.read_item(world.item_id)["disposition_status"] == "IN_REPAIR"


class TestReservationOverAvailability:
    def test_draw_above_available_units_refused_smaller_draw_accepted(
        self, api, scenario
    ):
        """Availability is the reservation ceiling, and a draw down to the watermark goes LOW.

        "Beyond eligibility, `units` below one is refused with `ERR_INVALID_UNITS` and `units` exceeding the lot's `available_units` is refused with `ERR_INSUFFICIENT_PART_UNITS`; a draw exactly equal to `available_units` is allowed and depletes the lot."
        "(43) A reservation's `units` does not exceed the lot's `available_units`, else `ERR_INSUFFICIENT_PART_UNITS` (409)."
        "It is `DEPLETED` when `available_units` is zero; `LOW` when `available_units` is at least one and at most `low_watermark_units`; and `AVAILABLE` otherwise."
        "That model-level field is `SUPPORTED` when some part lot for the model has a `status` of `AVAILABLE` or `LOW`."

        Design: Corner/validations/reservation_units_over_availability_rejected
        """
        world = _repair_order_world(
            scenario,
            lot_overrides={
                "part_code": factories.ZIP_PART_CODE,
                "part_kind": "ZIPPER_SLIDER",
                "on_hand_units": 4,
                "unit_price_cents": 1800,
                "low_watermark_units": 1,
            },
            certifications=(("ZIPPER", 3),),
            claim_overrides={
                "reported_defect_type": "ZIPPER_FAILURE",
                "customer_narrative": "Door zipper failed.",
            },
            assessment_overrides={
                "required_work_types": ["ZIPPER"],
                "estimated_labor_lines": [factories.labor_line("ZIPPER", 35)],
                "estimated_parts_cents": 1800,
                "defect_notes": "Coil defect.",
            },
        )

        refused = api.create_parts_reservation(
            world.order_id,
            factories.parts_reservation_payload(
                world.lot_id, factories.ZIP_PART_CODE, 5
            ),
            PARTS_COORDINATOR_HEADERS,
        )
        validate_error(refused, ERR_INSUFFICIENT_PART_UNITS)
        assert_part_lot_counts(
            scenario.read_lot(world.lot_id), 4, 0, 4, status="AVAILABLE"
        )

        accepted = validate_success(
            api.create_parts_reservation(
                world.order_id,
                factories.parts_reservation_payload(
                    world.lot_id, factories.ZIP_PART_CODE, 3
                ),
                PARTS_COORDINATOR_HEADERS,
            ),
            201,
        )
        assert accepted["units"] == 3, accepted
        assert accepted["status"] == "RESERVED", accepted
        assert accepted["is_substitution"] is False, accepted
        assert_part_lot_counts(scenario.read_lot(world.lot_id), 4, 3, 1, status="LOW")
        assert scenario.read_model(world.model_id)["parts_support_status"] == "SUPPORTED"


class TestZeroDeltaAdjustment:
    def test_zero_delta_refused_restock_accepted(self, api, scenario):
        """A zero adjustment is refused; a positive one lifts the lot out of DEPLETED.

        "A `delta_units` of zero is refused with `ERR_INVALID_UNITS`, and a negative adjustment that would push `on_hand_units` below `reserved_units` is refused with `ERR_INSUFFICIENT_STOCK_ADJUSTMENT`."
        "Otherwise `on_hand_units` changes by `delta_units`, `available_units` is recomputed, the lot's `status` is re-derived — which is how a `DEPLETED` lot climbs back to `LOW` or `AVAILABLE` and closes the inventory cycle — and the model's `parts_support_status` is re-derived."

        Design: Corner/validations/zero_delta_adjustment_rejected_restock_accepted
        """
        scenario.set_clock()
        model = scenario.model()
        lot = scenario.part_lot(model["id"], on_hand_units=0, low_watermark_units=2)
        assert_part_lot_counts(lot, 0, 0, 0, status="DEPLETED")
        assert scenario.read_model(model["id"])["parts_support_status"] == "NO_SUPPORT"

        refused = api.adjust_part_lot(
            lot["id"],
            {"delta_units": 0, "reason": "cycle count, no change"},
            PARTS_COORDINATOR_HEADERS,
        )
        validate_error(refused, ERR_INVALID_UNITS)
        assert_part_lot_counts(
            scenario.read_lot(lot["id"]), 0, 0, 0, status="DEPLETED"
        )

        accepted = validate_success(
            api.adjust_part_lot(
                lot["id"],
                {"delta_units": 3, "reason": "restock from supplier"},
                PARTS_COORDINATOR_HEADERS,
            )
        )
        assert_part_lot_counts(accepted, 3, 0, 3, status="AVAILABLE")
        assert scenario.read_model(model["id"])["parts_support_status"] == "SUPPORTED"


class TestNegativeAdjustmentFloor:
    def test_write_down_below_reserved_units_refused_and_floor_accepted(
        self, api, scenario
    ):
        """The write-down floor is reserved_units, not zero.

        "A `delta_units` of zero is refused with `ERR_INVALID_UNITS`, and a negative adjustment that would push `on_hand_units` below `reserved_units` is refused with `ERR_INSUFFICIENT_STOCK_ADJUSTMENT`."
        "(44) A negative adjustment does not push `on_hand_units` below `reserved_units`, else `ERR_INSUFFICIENT_STOCK_ADJUSTMENT` (422)."
        "It is `DEPLETED` when `available_units` is zero; `LOW` when `available_units` is at least one and at most `low_watermark_units`; and `AVAILABLE` otherwise."

        Design: Corner/validations/negative_adjustment_below_reserved_units_rejected
        """
        world = _repair_order_world(
            scenario,
            lot_overrides={
                "part_code": factories.ZIP_PART_CODE,
                "part_kind": "ZIPPER_SLIDER",
                "on_hand_units": 4,
                "unit_price_cents": 1800,
                "low_watermark_units": 1,
            },
            certifications=(("ZIPPER", 3),),
            claim_overrides={
                "reported_defect_type": "ZIPPER_FAILURE",
                "customer_narrative": "Door zipper failed.",
            },
            assessment_overrides={
                "required_work_types": ["ZIPPER"],
                "estimated_labor_lines": [factories.labor_line("ZIPPER", 35)],
                "estimated_parts_cents": 1800,
                "defect_notes": "Coil defect.",
            },
        )
        reservation = scenario.reserve_parts(
            world.order_id, world.lot_id, factories.ZIP_PART_CODE, 1
        )

        refused = api.adjust_part_lot(
            world.lot_id,
            {"delta_units": -4, "reason": "water damage write-down"},
            PARTS_COORDINATOR_HEADERS,
        )
        validate_error(refused, ERR_INSUFFICIENT_STOCK_ADJUSTMENT)
        assert_part_lot_counts(
            scenario.read_lot(world.lot_id), 4, 1, 3, status="AVAILABLE"
        )

        accepted = validate_success(
            api.adjust_part_lot(
                world.lot_id,
                {
                    "delta_units": -3,
                    "reason": "water damage write-down, reserved unit spared",
                },
                PARTS_COORDINATOR_HEADERS,
            )
        )
        assert_part_lot_counts(accepted, 1, 1, 0, status="DEPLETED")
        assert scenario.read_reservation(reservation["id"])["status"] == "RESERVED"
        assert scenario.read_model(world.model_id)["parts_support_status"] == "NO_SUPPORT"


class TestInvertedIntervals:
    def test_surge_window_and_work_block_endpoint_ordering(self, api, scenario):
        """One interval rule, two strictnesses: a same-day window is legal, a zero-length block is not.

        "(32) Interval endpoints are ordered — a work block's `start_at` is strictly before its `end_at`, and a surge window's `start_date` is at or before its `end_date` — else `ERR_INVALID_WINDOW` (422)."
        "Because the interval is closed, two windows that merely share a single endpoint date already overlap, and a create that would do so against an existing `ACTIVE` window of the same centre is refused with `ERR_SURGE_WINDOW_OVERLAP`; a window whose `start_date` is after its `end_date` is refused earlier with `ERR_INVALID_WINDOW`."
        "A block whose `start_at` is at or after its `end_at` is refused with `ERR_INVALID_WINDOW`."
        "Its `status` begins as `ACTIVE` and becomes `RETIRED` once a queue-review observes that its `end_date` has fallen behind the logical clock."

        Design: Corner/validations/inverted_intervals_rejected_on_surge_windows_and_work_blocks
        """
        world = _repair_order_world(scenario)

        refused_window = api.create_surge_window(
            world.center_id,
            factories.surge_window_payload(
                label="Backwards autumn",
                start_date="2026-09-30T00:00:00Z",
                end_date="2026-09-01T00:00:00Z",
                multiplier=1.60,
            ),
            PROGRAM_ADMIN_HEADERS,
        )
        validate_error(refused_window, ERR_INVALID_WINDOW)
        _, meta = validate_paginated(
            api.list_surge_windows(world.center_id, PROGRAM_ADMIN_HEADERS)
        )
        assert meta["total_count"] == 0, meta

        refused_block = api.create_work_block(
            factories.work_block_payload(
                world.order_id,
                start_at="2026-06-16T09:00:00Z",
                end_at="2026-06-16T09:00:00Z",
                technician_id=world.technician_id,
            ),
            SERVICE_AGENT_HEADERS,
        )
        validate_error(refused_block, ERR_INVALID_WINDOW)
        _, meta = validate_paginated(
            api.list_work_blocks(SERVICE_AGENT_HEADERS, repair_order_id=world.order_id)
        )
        assert meta["total_count"] == 0, meta
        assert scenario.read_technician(world.technician_id)["scheduled_minutes_open"] == 0

        accepted = validate_success(
            api.create_surge_window(
                world.center_id,
                factories.surge_window_payload(
                    label="Single day push",
                    start_date="2026-09-01T00:00:00Z",
                    end_date="2026-09-01T00:00:00Z",
                    multiplier=1.60,
                ),
                PROGRAM_ADMIN_HEADERS,
            ),
            201,
        )
        assert accepted["status"] == "ACTIVE", accepted
        assert accepted["start_date"][:10] == "2026-09-01", accepted
        assert accepted["end_date"][:10] == "2026-09-01", accepted

        assert_multiplier(
            scenario.read_center(world.center_id)["current_surge_multiplier"], 1.00
        )
        assert scenario.read_order(world.order_id)["work_status"] == "QUEUED"
