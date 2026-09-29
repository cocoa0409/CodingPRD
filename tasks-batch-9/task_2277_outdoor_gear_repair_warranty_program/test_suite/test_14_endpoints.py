"""Endpoint-surface coverage: CRUD, patches, junction rows and computed reads.

Each class below pins one endpoint family against the PRD contract: the
catalogue-model create/read/patch/list quartet (§3.1, §2.8), the technician
roster patch (§3.1), the atomic bench-complete work log (§3.8, §2.11), the
parts-reservation junction row (§3.8, §2.10), the claim liability-entry
reverse-reachability read (§3.5, §2.9), the expedite fee's PROVISIONAL/FINAL
divergence (§3.7) and the surge-window create that lifts a centre's
`current_surge_multiplier` only while it covers the logical clock (§3.1, §3.6).
"""

from test_helpers import (
    ERR_INVALID_REQUEST,
    ERR_PART_LOT_NOT_FOUND,
    NON_EXISTENT_UUID,
    assert_common_fields,
    assert_estimate_breakdown,
    assert_multiplier,
    assert_part_lot_counts,
    assert_pct,
    factories,
    get_success_data,
    make_technician_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

# Bench intervals on the 2026-06-16 UTC calendar date (PRD §3.8).
FABRIC_BLOCK_START = "2026-06-16T09:00:00Z"
FABRIC_BLOCK_END = "2026-06-16T11:00:00Z"
ZIPPER_BLOCK_START = "2026-06-16T11:00:00Z"
ZIPPER_BLOCK_END = "2026-06-16T12:00:00Z"

# Surge calendar dates relative to the pinned clock 2026-06-15T09:00:00Z.
JUNE_WINDOW_START = "2026-06-01T00:00:00Z"
JUNE_WINDOW_END = "2026-06-30T23:59:59Z"
MAY_WINDOW_START = "2026-05-01T00:00:00Z"
MAY_WINDOW_END = "2026-05-31T23:59:59Z"


class TestGearModelCrud:
    """POST / GET / PATCH / GET-list on `/gear-service/gear-models`."""

    def test_model_create_read_then_patch_repoints_the_successor_valuation(
        self, scenario, api, agent_headers, admin_headers
    ):
        """A fresh model reads back at its catalogue defaults; the discontinue patch bumps its version and re-prices every unit's successor basis.

        "A new model begins with `parts_support_status` at `NO_SUPPORT`, because no lot has been stocked for it yet, with `repairability_flag` at `NONE`, and with its three feedback counters — `defect_claim_count`, `wear_denial_count` and `irreparable_count` — all at 0."
        "Patching a catalogue model may set `discontinued_at`, point `successor_model_id` at the model that replaces it, or reprice it by changing `msrp_cents`."
        "A successful patch re-derives the model's `parts_support_status` and forces every registered unit of that model to re-derive its `replacement_value_successor_cents`, since a repricing or a newly named successor changes what the brand would have to ship today."
        "The base list price is the successor model's `msrp_cents` when the unit's model has both a non-null `discontinued_at` and a non-null `successor_model_id`; in every other case it is the unit's own model's `msrp_cents`."
        "The successor valuation is that base list price multiplied by ninety percent, rounded half up to whole cents."
        "The depreciated value is then the greater of that residual floor and the unit's `purchase_price_cents` multiplied by one minus the depreciation fraction, rounded half up to whole cents."

        Design: Corner/endpoints/gear_model_crud_create_read_patch_and_filtered_list
        """
        scenario.set_clock()
        successor = scenario.successor_model()
        model = scenario.model()
        customer = scenario.customer()
        item = scenario.gear_item(model["id"], customer["id"])
        version_before = model["version"]

        read = validate_success(api.get_gear_model(model["id"], agent_headers))
        assert_common_fields(read, expected_version=version_before)
        assert read["model_code"] == "TNT-ASCENT-2", read
        assert read["msrp_cents"] == 79900, read
        assert read["warranty_years"] == 5, read
        assert read["lifetime_warranty"] is False, read
        assert read["discontinued_at"] is None, read
        assert read["successor_model_id"] is None, read
        assert read["parts_support_status"] == "NO_SUPPORT", read
        assert read["defect_claim_count"] == 0, read
        assert read["repairability_flag"] == "NONE", read

        # Before the patch the successor basis is the model's own MSRP: 0.9 * 79900.
        assert item["replacement_value_successor_cents"] == 71910, item

        patched = validate_success(
            api.patch_gear_model(
                model["id"],
                {
                    "discontinued_at": "2026-03-01T00:00:00Z",
                    "successor_model_id": successor["id"],
                },
                admin_headers,
            )
        )
        assert patched["discontinued_at"].startswith("2026-03-01T00:00:00"), patched
        assert patched["successor_model_id"] == successor["id"], patched
        assert patched["msrp_cents"] == 79900, patched
        assert patched["version"] > version_before, patched

        # The patch re-pointed the SUCCESSOR_MSRP basis to the Ascent 3P list price.
        repriced = scenario.read_item(item["id"])
        assert repriced["replacement_value_successor_cents"] == 89910, repriced
        assert repriced["replacement_value_depreciated_cents"] == 52430, repriced

    def test_model_list_pages_by_category_and_filters_on_the_successor_link(
        self, scenario, api, agent_headers, admin_headers
    ):
        """A limit-1 category page reports both rows in meta, and the successor_model_id filter isolates the discontinued model.

        "Reverse reachability is otherwise provided by query filters on the flat collections: `service_center_id`, `gear_item_id`, `gear_model_id`, `owner_customer_id`, `warranty_claim_id`, `repair_order_id`, `part_lot_id`, `technician_id`, `assessor_technician_id` and `successor_model_id` are all available as list filters, alongside the status-shaped filters `status`, `work_status`, `billing_status`, `disposition_status`, `warranty_state`, `parts_support_status`, `repairability_flag`, `commitment_breached`, `decision`, `intake_kind`, `determination`, `is_superseded`, `variant`, `basis`, `category`, `part_kind` and `work_type`."
        "The `limit` parameter caps the number of rows returned; when omitted it defaults to 10, its minimum accepted value is 1 and its maximum accepted value is 100."
        "List responses carry `limit`, `offset`, `total_count` and `has_more` inside the `meta` object of the envelope."

        Design: Corner/endpoints/gear_model_crud_create_read_patch_and_filtered_list
        """
        scenario.set_clock()
        successor = scenario.successor_model()
        model = scenario.model()
        get_success_data(
            api.patch_gear_model(
                model["id"],
                {
                    "discontinued_at": "2026-03-01T00:00:00Z",
                    "successor_model_id": successor["id"],
                },
                admin_headers,
            )
        )

        rows, meta = validate_paginated(
            api.list_gear_models(
                agent_headers, category="TENT_SHELTER", limit=1, offset=0
            )
        )
        assert meta["total_count"] == 2, meta
        assert meta["has_more"] is True, meta
        assert len(rows) == 1, rows

        rows, meta = validate_paginated(
            api.list_gear_models(agent_headers, successor_model_id=successor["id"])
        )
        assert meta["total_count"] == 1, meta
        assert meta["has_more"] is False, meta
        assert [row["id"] for row in rows] == [model["id"]], rows


class TestTechnicianPatch:
    """PATCH `/gear-service/technicians/{id}` replaces the roster and the matrix."""

    def test_patch_replaces_the_certification_matrix_wholesale(
        self, scenario, api, admin_headers
    ):
        """Patching in a ZIPPER grant removes the FABRIC grant instead of merging it, and leaves the minute counters alone.

        "Patching a technician may change the roster `status` or replace the `certifications` matrix; a technician moved to `ON_LEAVE` or `INACTIVE` drops out of the routing candidate pool immediately, while blocks already scheduled for them are left untouched."
        "New technicians start with `scheduled_minutes_open` and `completed_minutes` both at 0."

        Design: Corner/endpoints/technician_patch_updates_status_and_certifications
        """
        scenario.set_clock()
        center = scenario.center()
        technician = scenario.technician(
            center["id"],
            employee_code="T-101",
            full_name="Ines Park",
            certifications=[factories.certification("FABRIC", 2)],
        )
        version_before = technician["version"]

        patched = validate_success(
            api.patch_technician(
                technician["id"],
                {
                    "status": "ON_LEAVE",
                    "certifications": [factories.certification("ZIPPER", 3)],
                },
                admin_headers,
            )
        )
        assert patched["status"] == "ON_LEAVE", patched
        assert patched["certifications"] == [
            {"work_type": "ZIPPER", "level": 3}
        ], patched
        assert patched["scheduled_minutes_open"] == 0, patched
        assert patched["completed_minutes"] == 0, patched
        assert patched["version"] > version_before, patched

        # Identity fields the patch never touches.
        reread = scenario.read_technician(technician["id"])
        assert reread["employee_code"] == "T-101", reread
        assert reread["service_center_id"] == center["id"], reread

    def test_roster_and_certification_filters_reflect_the_patch(
        self, scenario, api, admin_headers, agent_headers
    ):
        """After the patch the technician appears under status=ON_LEAVE and no longer under work_type=FABRIC.

        "Patching a technician may change the roster `status` or replace the `certifications` matrix; a technician moved to `ON_LEAVE` or `INACTIVE` drops out of the routing candidate pool immediately, while blocks already scheduled for them are left untouched."
        "Reverse reachability is otherwise provided by query filters on the flat collections: `service_center_id`, `gear_item_id`, `gear_model_id`, `owner_customer_id`, `warranty_claim_id`, `repair_order_id`, `part_lot_id`, `technician_id`, `assessor_technician_id` and `successor_model_id` are all available as list filters, alongside the status-shaped filters `status`, `work_status`, `billing_status`, `disposition_status`, `warranty_state`, `parts_support_status`, `repairability_flag`, `commitment_breached`, `decision`, `intake_kind`, `determination`, `is_superseded`, `variant`, `basis`, `category`, `part_kind` and `work_type`."

        Design: Corner/endpoints/technician_patch_updates_status_and_certifications
        """
        scenario.set_clock()
        center = scenario.center()
        technician = scenario.technician(
            center["id"],
            employee_code="T-101",
            full_name="Ines Park",
            certifications=[factories.certification("FABRIC", 2)],
        )
        get_success_data(
            api.patch_technician(
                technician["id"],
                {
                    "status": "ON_LEAVE",
                    "certifications": [factories.certification("ZIPPER", 3)],
                },
                admin_headers,
            )
        )

        rows, meta = validate_paginated(
            api.list_technicians(
                agent_headers, service_center_id=center["id"], status="ON_LEAVE"
            )
        )
        assert meta["total_count"] == 1, meta
        assert [row["id"] for row in rows] == [technician["id"]], rows

        rows, meta = validate_paginated(
            api.list_technicians(
                agent_headers, service_center_id=center["id"], work_type="FABRIC"
            )
        )
        assert meta["total_count"] == 0, meta
        assert meta["has_more"] is False, meta
        assert rows == [], rows


def _two_lane_warranty_order(catalogue):
    """A WARRANTY_REPAIR order requiring FABRIC and ZIPPER with one block per lane."""
    scenario = catalogue.scenario
    claim = scenario.claim(
        catalogue.center_id,
        catalogue.item_id,
        customer_narrative="Floor seam split and the door slider is chewed.",
    )
    submitted = scenario.submit(claim["id"])
    scenario.assess(
        claim["id"],
        catalogue.technician_id,
        expected_claim_version=submitted["version"],
        required_work_types=["FABRIC", "ZIPPER"],
        estimated_labor_lines=[
            factories.labor_line("FABRIC", 120),
            factories.labor_line("ZIPPER", 35),
        ],
        estimated_parts_cents=4200,
        defect_notes="Bond line plus slider.",
    )
    scenario.decide(claim["id"], decision_note="Defect confirmed on both lanes.")
    order = scenario.repair_order(claim["id"])
    fabric_block = scenario.work_block(
        order["id"],
        catalogue.technician_id,
        work_type="FABRIC",
        start_at=FABRIC_BLOCK_START,
        end_at=FABRIC_BLOCK_END,
    )
    zipper_block = scenario.work_block(
        order["id"],
        catalogue.technician_id,
        work_type="ZIPPER",
        start_at=ZIPPER_BLOCK_START,
        end_at=ZIPPER_BLOCK_END,
    )
    catalogue.update(
        claim_id=claim["id"],
        order=order,
        order_id=order["id"],
        fabric_block_id=fabric_block["id"],
        zipper_block_id=zipper_block["id"],
    )
    return catalogue


class TestBenchCompleteWorkLogAtomicity:
    """POST `/gear-service/repair-orders/{id}/bench-complete` applies its log atomically."""

    def test_out_of_range_actual_minutes_rejects_the_whole_work_log(
        self, catalogue, api
    ):
        """A log whose second entry logs 601 minutes leaves the first entry's block SCHEDULED and no minutes moved.

        "It carries a `work_log`, a non-empty array whose entries each name a `work_block_id` and the `actual_minutes` logged against it, with `actual_minutes` between 1 and 600."
        "The body and query conform to the endpoint's input schema: required fields present, types correct, enum members recognised, integers at or above their declared minimum, ISO-8601 timestamps parseable, and the `certifications`, `labor_lines`, `estimated_labor_lines` and `work_log` arrays well formed — otherwise `ERR_INVALID_REQUEST` (HTTP 422)."
        "On success each listed block moves `SCHEDULED` → `COMPLETED` with its `actual_minutes` stamped, and for each block the technician's `scheduled_minutes_open` decreases by that block's `duration_minutes` while their `completed_minutes` increases by that block's `actual_minutes`."

        Design: Corner/endpoints/bench_complete_work_log_is_all_or_nothing
        """
        world = _two_lane_warranty_order(catalogue)
        scenario = world.scenario

        response = api.bench_complete(
            world.order_id,
            {
                "work_log": [
                    factories.work_log_entry(world.fabric_block_id, 90),
                    factories.work_log_entry(world.zipper_block_id, 601),
                ]
            },
            make_technician_headers(world.technician_id),
        )
        validate_error(response, ERR_INVALID_REQUEST)

        fabric = scenario.read_work_block(world.fabric_block_id)
        assert fabric["status"] == "SCHEDULED", fabric
        assert fabric["actual_minutes"] is None, fabric
        zipper = scenario.read_work_block(world.zipper_block_id)
        assert zipper["status"] == "SCHEDULED", zipper

        assert scenario.read_order(world.order_id)["work_status"] == "IN_WORK"
        technician = scenario.read_technician(world.technician_id)
        assert technician["completed_minutes"] == 0, technician
        assert technician["scheduled_minutes_open"] == 180, technician

    def test_valid_work_log_completes_every_block_and_moves_the_order(
        self, catalogue, api
    ):
        """A well-formed log completes both blocks, moves the order to BENCH_DONE and swaps 180 open minutes for 130 completed.

        "**Bench completion** is a `RepairTechnician` operation on an order in `work_status` `IN_WORK`, moving it `IN_WORK` → `BENCH_DONE`."
        "On success each listed block moves `SCHEDULED` → `COMPLETED` with its `actual_minutes` stamped, and for each block the technician's `scheduled_minutes_open` decreases by that block's `duration_minutes` while their `completed_minutes` increases by that block's `actual_minutes`."

        Design: Corner/endpoints/bench_complete_work_log_is_all_or_nothing
        """
        world = _two_lane_warranty_order(catalogue)
        scenario = world.scenario

        order = validate_success(
            api.bench_complete(
                world.order_id,
                {
                    "work_log": [
                        factories.work_log_entry(world.fabric_block_id, 90),
                        factories.work_log_entry(world.zipper_block_id, 40),
                    ]
                },
                make_technician_headers(world.technician_id),
            )
        )
        assert order["work_status"] == "BENCH_DONE", order

        fabric = scenario.read_work_block(world.fabric_block_id)
        assert fabric["status"] == "COMPLETED", fabric
        assert fabric["actual_minutes"] == 90, fabric
        zipper = scenario.read_work_block(world.zipper_block_id)
        assert zipper["status"] == "COMPLETED", zipper
        assert zipper["actual_minutes"] == 40, zipper

        technician = scenario.read_technician(world.technician_id)
        assert technician["completed_minutes"] == 130, technician
        assert technician["scheduled_minutes_open"] == 0, technician


class TestPartsReservationJunction:
    """POST `/gear-service/repair-orders/{id}/parts-reservations` links an order to a lot."""

    def test_unknown_part_lot_id_is_a_404_that_leaves_the_lot_untouched(
        self, open_order, api, parts_headers
    ):
        """A reservation naming a part_lot_id that does not resolve is refused and moves no units.

        "Second-level body references resolve: the `part_lot_id` on a reservation, an explicitly supplied `technician_id` on a work block, and every `work_block_id` inside a bench-complete `work_log`, reported as `ERR_PART_LOT_NOT_FOUND`, `ERR_TECHNICIAN_NOT_FOUND` or `ERR_WORK_BLOCK_NOT_FOUND`."
        "A successful reservation begins with `status` `RESERVED` and a null `settled_at`, increases the lot's `reserved_units` by `units`, recomputes the lot's `available_units`, re-derives the lot's `status`, and then re-derives `parts_support_status` on the lot's model."

        Design: Corner/endpoints/parts_reservation_links_order_and_lot
        """
        scenario = open_order.scenario

        response = api.create_parts_reservation(
            open_order.order_id,
            factories.parts_reservation_payload(
                NON_EXISTENT_UUID, factories.PANEL_PART_CODE, 1
            ),
            parts_headers,
        )
        validate_error(response, ERR_PART_LOT_NOT_FOUND)

        lot = scenario.read_lot(open_order.panel_lot_id)
        assert_part_lot_counts(
            lot, on_hand_units=5, reserved_units=0, available_units=5
        )

    def test_accepted_reservation_is_visible_from_the_order_and_from_the_lot(
        self, open_order, api, parts_headers
    ):
        """A two-unit exact-code draw mints a RESERVED junction row and drains the lot's availability to 3 without touching on_hand_units.

        "On an exact-code draw the lot must be stocked for the order's own model — a lot whose `gear_model_id` is anything else is refused with `ERR_PART_MODEL_MISMATCH` — and the reservation's `is_substitution` is false."
        "A successful reservation begins with `status` `RESERVED` and a null `settled_at`, increases the lot's `reserved_units` by `units`, recomputes the lot's `available_units`, re-derives the lot's `status`, and then re-derives `parts_support_status` on the lot's model."
        "It is `DEPLETED` when `available_units` is zero; `LOW` when `available_units` is at least one and at most `low_watermark_units`; and `AVAILABLE` otherwise."
        "`on_hand_units` is supplied once at lot creation and thereafter moves only by an explicit lot adjustment or by a reservation being consumed; it is never edited directly."

        Design: Corner/endpoints/parts_reservation_links_order_and_lot
        """
        scenario = open_order.scenario

        reservation = validate_success(
            api.create_parts_reservation(
                open_order.order_id,
                factories.parts_reservation_payload(
                    open_order.panel_lot_id, factories.PANEL_PART_CODE, 2
                ),
                parts_headers,
            ),
            201,
        )
        assert reservation["repair_order_id"] == open_order.order_id, reservation
        assert reservation["part_lot_id"] == open_order.panel_lot_id, reservation
        assert reservation["required_part_code"] == factories.PANEL_PART_CODE, reservation
        assert reservation["units"] == 2, reservation
        assert reservation["is_substitution"] is False, reservation
        assert reservation["status"] == "RESERVED", reservation
        assert reservation["settled_at"] is None, reservation

        rows, meta = validate_paginated(
            api.list_parts_reservations(
                parts_headers, repair_order_id=open_order.order_id, status="RESERVED"
            )
        )
        assert meta["total_count"] == 1, meta
        assert meta["has_more"] is False, meta
        assert [row["id"] for row in rows] == [reservation["id"]], rows

        lot = scenario.read_lot(open_order.panel_lot_id)
        assert_part_lot_counts(
            lot,
            on_hand_units=5,
            reserved_units=2,
            available_units=3,
            status="AVAILABLE",
        )


class TestClaimLiabilityEntriesRead:
    """GET `/gear-service/warranty-claims/{id}/liability-entries` exposes the reservation min()."""

    def test_repair_entry_reserves_the_assessment_cost_not_the_depreciated_cap(
        self, decided_claim, api, agent_headers
    ):
        """The OPEN REPAIR entry reserves 22390 — the assessment cost — while the 52430 depreciated cap does not bind.

        "First, a liability entry is created on the claim with `basis` `REPAIR`, `valuation_variant` `DEPRECIATED_PURCHASE`, `status` `OPEN`, and a `reserved_amount_cents` equal to the lesser of the claim's `latest_repair_cost_cents` and the unit's `replacement_value_depreciated_cents` — the brand never reserves more for a repair than the depreciated worth of the thing being repaired."
        "Its `release_reason` and `released_at` are null while it is `OPEN`."
        "`liability_utilization_pct` is one hundred multiplied by `open_liability_cents` divided by `liability_cap_cents`, rounded half up to two decimal places, and is display-only."

        Design: Corner/endpoints/claim_liability_entries_computed_read_with_filters
        """
        scenario = decided_claim.scenario

        rows, meta = validate_paginated(
            api.list_claim_liability_entries(decided_claim.claim_id, agent_headers)
        )
        assert meta["total_count"] == 1, meta
        assert meta["has_more"] is False, meta
        entry = rows[0]
        assert entry["warranty_claim_id"] == decided_claim.claim_id, entry
        assert entry["basis"] == "REPAIR", entry
        assert entry["valuation_variant"] == "DEPRECIATED_PURCHASE", entry
        assert entry["reserved_amount_cents"] == 22390, entry
        assert entry["status"] == "OPEN", entry
        assert entry["release_reason"] is None, entry
        assert entry["released_at"] is None, entry

        # The cap that did not bind, and the cost that did.
        item = scenario.read_item(decided_claim.item_id)
        assert item["replacement_value_depreciated_cents"] == 52430, item
        claim = scenario.read_claim(decided_claim.claim_id)
        assert claim["latest_repair_cost_cents"] == 22390, claim

        center = scenario.read_center(decided_claim.center_id)
        assert center["open_liability_cents"] == 22390, center
        assert_pct(center["liability_utilization_pct"], 0.45)

    def test_status_and_basis_filters_show_no_released_or_replacement_twin(
        self, decided_claim, api, agent_headers, admin_headers
    ):
        """Filtering the claim's entries on status=RELEASED or basis=REPLACEMENT returns nothing: a warranty repair opens exactly one entry.

        "First, a liability entry is created on the claim with `basis` `REPAIR`, `valuation_variant` `DEPRECIATED_PURCHASE`, `status` `OPEN`, and a `reserved_amount_cents` equal to the lesser of the claim's `latest_repair_cost_cents` and the unit's `replacement_value_depreciated_cents` — the brand never reserves more for a repair than the depreciated worth of the thing being repaired."
        "Entries whose `status` is `RELEASED` are excluded from the sum but retain their `reserved_amount_cents` for audit."
        "Reverse reachability is otherwise provided by query filters on the flat collections: `service_center_id`, `gear_item_id`, `gear_model_id`, `owner_customer_id`, `warranty_claim_id`, `repair_order_id`, `part_lot_id`, `technician_id`, `assessor_technician_id` and `successor_model_id` are all available as list filters, alongside the status-shaped filters `status`, `work_status`, `billing_status`, `disposition_status`, `warranty_state`, `parts_support_status`, `repairability_flag`, `commitment_breached`, `decision`, `intake_kind`, `determination`, `is_superseded`, `variant`, `basis`, `category`, `part_kind` and `work_type`."

        Design: Corner/endpoints/claim_liability_entries_computed_read_with_filters
        """
        rows, meta = validate_paginated(
            api.list_claim_liability_entries(
                decided_claim.claim_id, agent_headers, status="RELEASED"
            )
        )
        assert meta["total_count"] == 0, meta
        assert rows == [], rows

        rows, meta = validate_paginated(
            api.list_claim_liability_entries(
                decided_claim.claim_id, admin_headers, basis="REPLACEMENT"
            )
        )
        assert meta["total_count"] == 0, meta
        assert rows == [], rows


def _expedited_paid_zipper_order(catalogue, api, agent_headers):
    """A PAID_REPAIR order with expedite_requested true on a 1800-cent slider lot."""
    scenario = catalogue.scenario
    zip_lot = scenario.part_lot(
        catalogue.model_id,
        part_code=factories.ZIP_PART_CODE,
        part_kind="ZIPPER_SLIDER",
        on_hand_units=4,
        unit_price_cents=1800,
        low_watermark_units=1,
    )
    claim = scenario.claim(
        catalogue.center_id,
        catalogue.item_id,
        intake_kind="PAID_REPAIR_REQUEST",
        reported_defect_type="ZIPPER_FAILURE",
        customer_narrative="Slider chewed after a fall; leaving for a trip.",
    )
    submitted = scenario.submit(claim["id"])
    scenario.assess(
        claim["id"],
        catalogue.technician_id,
        expected_claim_version=submitted["version"],
        determination="USER_DAMAGE",
        required_work_types=["ZIPPER"],
        estimated_labor_lines=[factories.labor_line("ZIPPER", 35)],
        estimated_parts_cents=1800,
        defect_notes="Impact damage.",
    )
    scenario.decide(claim["id"], decision_note="User damage: quote as paid repair.")
    order = validate_success(
        api.create_repair_order({
            "warranty_claim_id": claim["id"],
            "expedite_requested": True,
        }, agent_headers),
        201,
    )
    catalogue.update(
        zip_lot=zip_lot,
        zip_lot_id=zip_lot["id"],
        claim_id=claim["id"],
        order=order,
        order_id=order["id"],
    )
    return catalogue


class TestExpediteFeeOnlyOnFinalInvoice:
    """The 3500-cent expedite fee is a FINAL-row line, never a PROVISIONAL one."""

    def test_provisional_quote_on_an_expedited_order_carries_a_zero_expedite_fee(
        self, catalogue, api, agent_headers
    ):
        """The order records expedite_requested true and a 15-day commitment, yet the customer-facing quote prices expedite_fee_cents at 0.

        "**Step six** applies expedite: `expedite_fee_cents` is 3500 cents on a `FINAL` row when the order's `expedite_requested` is true, and zero in every other case — a `PROVISIONAL` row always carries zero here, even on an expedited order."
        "**Step seven** taxes the discounted, expedited base: `tax_cents` is 8.25 percent of the quantity `subtotal_cents` minus `loyalty_discount_cents` plus `expedite_fee_cents`, rounded half up."
        "Sixth, `promised_days` is the base-day total multiplied by `surge_multiplier_applied`, rounded **up** to a whole number of days, and only then increased by `parts_wait_days`; the rounding up happens before the parts wait is added and never after."
        "The new row's `valid_until` is the logical clock instant advanced by seven days, and its `decided_at` is null until the customer answers."

        Design: Corner/endpoints/expedite_fee_charged_only_on_the_final_invoice
        """
        world = _expedited_paid_zipper_order(catalogue, api, agent_headers)
        scenario = world.scenario
        order = world.order

        assert order["expedite_requested"] is True, order
        assert order["promised_days"] == 15, order
        assert order["promised_return_at"].startswith("2026-06-30T23:59:59.999"), order
        assert_multiplier(order["surge_multiplier_applied"], 1.00)
        assert order["parts_wait_days"] == 0, order

        estimate = validate_success(
            api.create_estimate(
                world.order_id,
                {
                    "expected_repair_order_version": scenario.order_version(
                        world.order_id
                    ),
                    "labor_lines": [factories.labor_line("ZIPPER", 35)],
                    "parts_lines": [
                        factories.parts_line(factories.ZIP_PART_CODE, 1, 1800)
                    ],
                },
                agent_headers,
            ),
            201,
        )
        assert estimate["variant"] == "PROVISIONAL", estimate
        assert_estimate_breakdown(
            estimate,
            labor_subtotal_cents=5542,
            parts_subtotal_cents=1800,
            shop_supply_fee_cents=388,
            subtotal_cents=7730,
            loyalty_discount_cents=773,
            expedite_fee_cents=0,
            tax_cents=574,
            total_cents=7531,
        )
        assert estimate["valid_until"].startswith("2026-06-22T09:00:00"), estimate

        scenario.approve_estimate(estimate["id"], world.customer_id)
        assert scenario.read_order(world.order_id)[
            "provisional_estimate_total_cents"
        ] == 7531

    def test_final_invoice_row_charges_the_3500_expedite_fee(
        self, catalogue, api, agent_headers
    ):
        """The server-derived FINAL row prices the 40 logged minutes and the consumed slider, then adds 3500 and taxes it.

        "**Step six** applies expedite: `expedite_fee_cents` is 3500 cents on a `FINAL` row when the order's `expedite_requested` is true, and zero in every other case — a `PROVISIONAL` row always carries zero here, even on an expedited order."
        "A `FINAL` row is derived by the server and accepts no lines from the caller at all: its labour lines come from the order's work blocks whose `status` is `COMPLETED`, grouped by `work_type` with the group's minutes being the sum of `actual_minutes` for that work type and the groups taken in ascending `work_type` order; its parts lines come from the order's reservations whose `status` is `CONSUMED`, each priced at its lot's `unit_price_cents`, with `RESERVED` and `RELEASED` reservations excluded entirely."
        "**Step eight** totals: `total_cents` is `subtotal_cents` minus `loyalty_discount_cents` plus `expedite_fee_cents` plus `tax_cents`."
        "On success a new estimate row is minted with `variant` `FINAL` directly in `status` `INVOICED` — a final row never passes through `SENT` or `APPROVED` — priced by the `FINAL` variant above, and the order's `final_invoice_total_cents` is set from that row's `total_cents` while its `billing_status` moves `ESTIMATE_APPROVED` → `INVOICED`."

        Design: Corner/endpoints/expedite_fee_charged_only_on_the_final_invoice
        """
        world = _expedited_paid_zipper_order(catalogue, api, agent_headers)
        scenario = world.scenario

        estimate = scenario.estimate(
            world.order_id,
            labor_lines=[factories.labor_line("ZIPPER", 35)],
            parts_lines=[factories.parts_line(factories.ZIP_PART_CODE, 1, 1800)],
        )
        scenario.approve_estimate(estimate["id"], world.customer_id)

        reservation = scenario.reserve_parts(
            world.order_id, world.zip_lot_id, factories.ZIP_PART_CODE, 1
        )
        block = scenario.work_block(
            world.order_id,
            world.technician_id,
            work_type="ZIPPER",
            start_at="2026-06-16T09:00:00Z",
            end_at="2026-06-16T10:00:00Z",
        )
        scenario.consume_parts(reservation["id"], world.technician_id)
        scenario.bench_complete(
            world.order_id,
            world.technician_id,
            [factories.work_log_entry(block["id"], 40)],
        )
        scenario.qc(world.order_id, world.second_technician_id, outcome="PASS")

        invoice = validate_success(
            api.invoice_order(world.order_id, agent_headers), 201
        )
        assert invoice["variant"] == "FINAL", invoice
        assert_estimate_breakdown(
            invoice,
            labor_subtotal_cents=6333,
            parts_subtotal_cents=1800,
            shop_supply_fee_cents=443,
            subtotal_cents=8576,
            loyalty_discount_cents=858,
            expedite_fee_cents=3500,
            tax_cents=925,
            total_cents=12143,
        )

        order = scenario.read_order(world.order_id)
        assert order["provisional_estimate_total_cents"] == 7531, order
        assert order["final_invoice_total_cents"] == 12143, order


class TestSurgeWindowRaisesCenterMultiplier:
    """POST `/gear-service/service-centers/{id}/surge-windows` recomputes the multiplier."""

    def test_window_covering_the_clock_lifts_the_multiplier_from_one(
        self, scenario, api, admin_headers
    ):
        """A June window at 1.60 is minted ACTIVE and lifts an empty centre's current_surge_multiplier from 1.0 to 1.60.

        "Its `status` begins as `ACTIVE` and becomes `RETIRED` once a queue-review observes that its `end_date` has fallen behind the logical clock."
        "Every accepted window recomputes the centre's `current_surge_multiplier`."
        "The centre's `current_surge_multiplier` is the multiplier implied by the `active_queue_depth` congestion tier together with any `ACTIVE` surge window covering the logical clock date, on the same tiers and the same take-the-greater rule that a repair order's `surge_multiplier_applied` uses."
        "A freshly registered centre starts with `open_liability_cents` at 0, `liability_utilization_pct` at 0, `liability_posture` at `OPEN`, `active_queue_depth` at 0 and `current_surge_multiplier` at 1.0; its `breached_commitment_count` is 0 and its `last_queue_review_at` is null until the first checkpoint runs."

        Design: Corner/endpoints/surge_window_creation_raises_the_center_multiplier_only_while_covering_now
        """
        scenario.set_clock()
        center = scenario.center()
        assert_multiplier(center["current_surge_multiplier"], 1.00)

        window = validate_success(
            api.create_surge_window(
                center["id"],
                factories.surge_window_payload(
                    label="June repair rush",
                    start_date=JUNE_WINDOW_START,
                    end_date=JUNE_WINDOW_END,
                    multiplier=1.60,
                ),
                admin_headers,
            ),
            201,
        )
        assert window["service_center_id"] == center["id"], window
        assert window["label"] == "June repair rush", window
        assert_multiplier(window["multiplier"], 1.60)
        assert window["status"] == "ACTIVE", window

        refreshed = scenario.read_center(center["id"])
        assert_multiplier(refreshed["current_surge_multiplier"], 1.60)
        assert refreshed["active_queue_depth"] == 0, refreshed
        assert refreshed["last_queue_review_at"] is None, refreshed
        assert refreshed["liability_posture"] == "OPEN", refreshed

    def test_strictly_past_window_is_active_yet_contributes_no_multiplier(
        self, scenario, api, admin_headers
    ):
        """A May window at 2.00 is created ACTIVE but does not cover 2026-06-15, so the centre stays at 1.60.

        "Third, the seasonal override is folded in but may never lower the tier: among the centre's surge windows whose `status` is `ACTIVE` and whose `start_date` is at or before the logical clock instant and whose `end_date` is at or after it — the window is inclusive at both ends — the largest `multiplier` is taken, or 1.00 when no such window exists, and `surge_multiplier_applied` is the greater of the tier multiplier and that window multiplier."
        "The centre's `current_surge_multiplier` is the multiplier implied by the `active_queue_depth` congestion tier together with any `ACTIVE` surge window covering the logical clock date, on the same tiers and the same take-the-greater rule that a repair order's `surge_multiplier_applied` uses."
        "Its `status` begins as `ACTIVE` and becomes `RETIRED` once a queue-review observes that its `end_date` has fallen behind the logical clock."

        Design: Corner/endpoints/surge_window_creation_raises_the_center_multiplier_only_while_covering_now
        """
        scenario.set_clock()
        center = scenario.center()
        june = scenario.surge_window(
            center["id"],
            label="June repair rush",
            start_date=JUNE_WINDOW_START,
            end_date=JUNE_WINDOW_END,
            multiplier=1.60,
        )

        may = validate_success(
            api.create_surge_window(
                center["id"],
                factories.surge_window_payload(
                    label="May clearance surge",
                    start_date=MAY_WINDOW_START,
                    end_date=MAY_WINDOW_END,
                    multiplier=2.00,
                ),
                admin_headers,
            ),
            201,
        )
        assert may["status"] == "ACTIVE", may

        refreshed = scenario.read_center(center["id"])
        assert_multiplier(refreshed["current_surge_multiplier"], 1.60)

        rows, meta = validate_paginated(
            api.list_surge_windows(center["id"], admin_headers, status="ACTIVE")
        )
        assert meta["total_count"] == 2, meta
        assert sorted(row["id"] for row in rows) == sorted([june["id"], may["id"]]), rows
