"""Order capture, slot reservation and reconciliation refusals, with their positive twins."""

from test_helpers import (
    ADMIN,
    CLOCK_MANIFEST,
    CLOCK_UPLIFT,
    COMPLIANCE,
    LM_BOB,
    SUPERVISOR,
    ApiErrorId,
    add_flight,
    advance_to_locked,
    assert_cart_axes,
    assert_total_count,
    capture_order,
    factories as f,
    open_manifest,
    read_cart,
    read_flight,
    register_stand,
    register_truck,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

# The window every ramp instance re-uses: inside the 05:00..09:15 slot band of a
# flight whose revised departure is 10:00.
LEGAL_START = "2026-09-15T07:30:00Z"
LEGAL_END = "2026-09-15T08:00:00Z"


class TestOrderCaptureAndChange:
    """The four capture guards and the substitution guard."""

    def test_an_order_against_a_retired_specification_is_refused(self, base_env):
        """Retirement blocks new orders without deleting the row it applies to.

        PRD §3.3: "The requested specification must be `ACTIVE`, or the request is refused with `ERR_SPEC_RETIRED`, and it must belong to the same airline as the flight, or the request is refused with `ERR_SPEC_AIRLINE_MISMATCH`."

        Design: Corner/validations/ordering_a_meal_against_a_retired_specification_is_rejected
        """
        env = base_env
        api = env.api
        add_flight(env)
        vgml_id = env.specs["V"]["id"]

        retired = validate_success(
            api.amend_meal_specification(vgml_id, {"status": "RETIRED"}, ADMIN), 200
        )
        assert retired["status"] == "RETIRED"
        assert retired["version"] == 2

        validate_error(
            api.create_special_meal_order(
                f.order_payload(env.flight_id, vgml_id, "14C", passenger_ref="PNR-B1"),
                env.rep_headers,
            ),
            ApiErrorId.ERR_SPEC_RETIRED.value,
            422,
        )
        _, meta = validate_paginated(
            api.list_special_meal_orders(env.rep_headers, {"flight_id": env.flight_id})
        )
        assert_total_count(meta, 0)
        # Retirement is not deletion: the row is still readable.
        still_there = validate_success(
            api.get_meal_specification(vgml_id, env.rep_headers), 200
        )
        assert still_there["id"] == vgml_id
        assert still_there["status"] == "RETIRED"

    def test_a_substitute_must_serve_the_same_cabin_as_the_order_it_replaces(
        self, base_env
    ):
        """The first-class tray is active and same-airline, and is still refused.

        PRD §3.3: "The substitute specification must be `ACTIVE` — otherwise `ERR_SPEC_RETIRED` — and must belong to the same airline and serve the same `cabin` as the original, otherwise `ERR_SPEC_AIRLINE_MISMATCH`."

        Design: Corner/validations/substituting_across_cabins_is_rejected_while_a_same_cabin_swap_succeeds
        """
        env = base_env
        api = env.api
        add_flight(env)
        order = capture_order(
            api,
            env.airline_id,
            env.flight_id,
            env.specs["V"]["id"],
            "15A",
            passenger_ref="PNR-B2",
        )
        advance_to_locked(env)
        confirmed = validate_success(
            api.get_special_meal_order(order["id"], env.rep_headers), 200
        )
        assert confirmed["status"] == "CONFIRMED"
        assert confirmed["cabin"] == "ECONOMY"

        validate_error(
            api.change_special_meal_order(
                order["id"],
                f.substitute_order_payload(
                    env.specs["F"]["id"], reason="VGML_SHORTAGE"
                ),
                SUPERVISOR,
            ),
            ApiErrorId.ERR_SPEC_AIRLINE_MISMATCH.value,
            422,
        )
        refused = validate_success(
            api.get_special_meal_order(order["id"], env.rep_headers), 200
        )
        assert refused["status"] == "CONFIRMED"
        assert refused["substitute_meal_specification_id"] is None

        swapped = validate_success(
            api.change_special_meal_order(
                order["id"],
                f.substitute_order_payload(
                    env.specs["Y"]["id"], reason="VGML_SHORTAGE"
                ),
                SUPERVISOR,
            ),
            200,
        )
        assert swapped["status"] == "SUBSTITUTED"
        assert swapped["substitute_meal_specification_id"] == env.specs["Y"]["id"]
        _, meta = validate_paginated(
            api.list_special_meal_orders(
                env.rep_headers,
                {"substitute_meal_specification_id": env.specs["Y"]["id"]},
            )
        )
        assert_total_count(meta, 1)

    def test_a_seat_frees_up_once_its_earlier_order_reaches_a_terminal_state(
        self, base_env
    ):
        """Seat uniqueness is scoped to live orders, so cancelling reopens the seat.

        PRD §3.3: "The seat must be free: at most one non-terminal order may exist per seat per flight, where non-terminal means the order's `status` is `REQUESTED`, `CONFIRMED` or `LATE_REJECTED`, and a repeat is refused with `ERR_DUPLICATE_SEAT_ORDER`."

        Design: Corner/validations/a_seat_is_blocked_only_while_its_earlier_order_is_non_terminal
        """
        env = base_env
        api = env.api
        add_flight(env)
        first = capture_order(
            api,
            env.airline_id,
            env.flight_id,
            env.specs["V"]["id"],
            "12A",
            passenger_ref="PNR-C1",
        )
        assert first["status"] == "REQUESTED"

        validate_error(
            api.create_special_meal_order(
                f.order_payload(
                    env.flight_id,
                    env.specs["V"]["id"],
                    "12A",
                    passenger_ref="PNR-C2",
                ),
                env.rep_headers,
            ),
            ApiErrorId.ERR_DUPLICATE_SEAT_ORDER.value,
            422,
        )

        cancelled = validate_success(
            api.change_special_meal_order(
                first["id"],
                f.cancel_order_payload(reason="PAX_REBOOKED"),
                env.rep_headers,
            ),
            200,
        )
        assert cancelled["status"] == "CANCELLED"
        assert cancelled["version"] == 2

        third = capture_order(
            api,
            env.airline_id,
            env.flight_id,
            env.specs["V"]["id"],
            "12A",
            passenger_ref="PNR-C3",
        )
        assert third["seat_number"] == "12A"
        assert third["status"] == "REQUESTED"

        rows, meta = validate_paginated(
            api.list_special_meal_orders(
                env.rep_headers,
                {"flight_id": env.flight_id, "seat_number": "12A"},
            )
        )
        assert_total_count(meta, 2)
        assert sorted(row["status"] for row in rows) == ["CANCELLED", "REQUESTED"]

    def test_an_order_captured_exactly_at_the_cutoff_instant_is_refused(self, base_env):
        """One minute early is accepted; the cutoff instant itself is already closed.

        PRD §3.3: "Finally, the logical clock must be strictly before `special_meal_cutoff_utc`; at or after that instant the capture is refused with `ERR_SPECIAL_MEAL_CUTOFF_PASSED`."

        Design: Corner/validations/an_order_captured_exactly_at_the_cutoff_instant_is_rejected
        """
        env = base_env
        api = env.api
        add_flight(env)
        assert read_flight(api, env.flight_id)["special_meal_cutoff_utc"].startswith(
            "2026-09-14T22:00:00"
        )

        set_clock(api, "2026-09-14T21:59:00Z")
        accepted = capture_order(
            api,
            env.airline_id,
            env.flight_id,
            env.specs["V"]["id"],
            "18A",
            passenger_ref="PNR-D1",
        )
        assert accepted["status"] == "REQUESTED"
        assert accepted["requested_at"].startswith("2026-09-14T21:59:00")

        set_clock(api, "2026-09-14T22:00:00Z")
        validate_error(
            api.create_special_meal_order(
                f.order_payload(
                    env.flight_id,
                    env.specs["V"]["id"],
                    "18B",
                    passenger_ref="PNR-D2",
                ),
                env.rep_headers,
            ),
            ApiErrorId.ERR_SPECIAL_MEAL_CUTOFF_PASSED.value,
            422,
        )
        _, meta = validate_paginated(
            api.list_special_meal_orders(env.rep_headers, {"flight_id": env.flight_id})
        )
        assert_total_count(meta, 1)


class TestSlotReservation:
    """The window rules, the resource rules and the manifest precondition."""

    def test_the_slot_band_edges_are_inclusive_and_the_window_must_be_ordered(
        self, issued_env
    ):
        """Two temporal rules stack: strict ordering first, then the inclusive band.

        PRD §3.7: "The window must be non-empty and correctly ordered — `window_start_utc` strictly before `window_end_utc` — or the request is refused with `ERR_SLOT_WINDOW_INVALID`."

        PRD §3.7: "The window must sit inside the flight's permitted slot band, which opens five hours before `revised_std_utc` and closes forty-five minutes before it: a start earlier than five hours before revised departure, or an end later than forty-five minutes before it, is refused with `ERR_SLOT_OUTSIDE_FLIGHT_WINDOW`."

        Design: Corner/validations/delivery_windows_are_validated_against_the_flight_slot_band
        """
        env = issued_env
        api = env.api
        manifest_id = env.manifest["id"]

        def reserve(start, end):
            return api.create_delivery_run(
                f.run_payload(
                    manifest_id, env.truck["id"], env.stand["id"], start, end
                ),
                LM_BOB,
            )

        validate_error(
            reserve("2026-09-15T08:00:00Z", "2026-09-15T07:30:00Z"),
            ApiErrorId.ERR_SLOT_WINDOW_INVALID.value,
            422,
        )
        validate_error(
            reserve("2026-09-15T07:30:00Z", "2026-09-15T07:30:00Z"),
            ApiErrorId.ERR_SLOT_WINDOW_INVALID.value,
            422,
        )
        validate_error(
            reserve("2026-09-15T09:00:00Z", "2026-09-15T09:30:00Z"),
            ApiErrorId.ERR_SLOT_OUTSIDE_FLIGHT_WINDOW.value,
            422,
        )
        validate_error(
            reserve("2026-09-15T04:30:00Z", "2026-09-15T05:30:00Z"),
            ApiErrorId.ERR_SLOT_OUTSIDE_FLIGHT_WINDOW.value,
            422,
        )

        # 05:00 is exactly five hours before departure and 09:15 exactly
        # forty-five minutes before it; both edges belong to the band.
        created = validate_success(
            reserve("2026-09-15T05:00:00Z", "2026-09-15T09:15:00Z"), 201
        )
        assert created["status"] == "RESERVED"
        assert created["lateness_minutes"] == 0
        assert created["penalty_cents"] == 0
        _, meta = validate_paginated(
            api.list_delivery_runs(LM_BOB, {"loading_manifest_id": manifest_id})
        )
        assert_total_count(meta, 1)

    def test_a_maintenance_truck_or_a_closed_stand_cannot_be_slotted(self, issued_env):
        """Availability is read off the referenced rows, not off the submitted window.

        PRD §3.7: "A truck in `MAINTENANCE` or a stand that is `CLOSED` is refused with `ERR_SLOT_RESOURCE_UNAVAILABLE`."

        Design: Corner/validations/an_out_of_service_truck_or_a_closed_stand_cannot_be_slotted
        """
        env = issued_env
        api = env.api
        spare_truck = register_truck(api, registration="HL-102")
        spare_stand = register_stand(api, stand_code="A13")
        validate_success(
            api.amend_truck(spare_truck["id"], {"status": "MAINTENANCE"}, ADMIN), 200
        )
        validate_success(
            api.amend_stand(spare_stand["id"], {"status": "CLOSED"}, ADMIN), 200
        )

        validate_error(
            api.create_delivery_run(
                f.run_payload(
                    env.manifest["id"],
                    spare_truck["id"],
                    env.stand["id"],
                    LEGAL_START,
                    LEGAL_END,
                ),
                LM_BOB,
            ),
            ApiErrorId.ERR_SLOT_RESOURCE_UNAVAILABLE.value,
            422,
        )
        validate_error(
            api.create_delivery_run(
                f.run_payload(
                    env.manifest["id"],
                    env.truck["id"],
                    spare_stand["id"],
                    LEGAL_START,
                    LEGAL_END,
                ),
                LM_BOB,
            ),
            ApiErrorId.ERR_SLOT_RESOURCE_UNAVAILABLE.value,
            422,
        )

        accepted = validate_success(
            api.create_delivery_run(
                f.run_payload(
                    env.manifest["id"],
                    env.truck["id"],
                    env.stand["id"],
                    LEGAL_START,
                    LEGAL_END,
                ),
                LM_BOB,
            ),
            201,
        )
        assert accepted["status"] == "RESERVED"
        _, meta = validate_paginated(
            api.list_delivery_runs(LM_BOB, {"truck_id": spare_truck["id"]})
        )
        assert_total_count(meta, 0)

    def test_no_slot_may_be_reserved_against_a_draft_manifest(self, sealed_env):
        """A draft manifest has nothing pinned, so the legal window never gets read.

        PRD §3.7: "The manifest must be `ISSUED`, or the reservation is refused with `ERR_MANIFEST_NOT_ISSUED`."

        Design: Corner/validations/dispatching_against_a_draft_manifest_returns_manifest_not_issued
        """
        env = sealed_env
        api = env.api
        set_clock(api, CLOCK_MANIFEST)
        manifest = open_manifest(api, env.flight_id, headers=LM_BOB)
        assert manifest["status"] == "DRAFT"

        validate_error(
            api.create_delivery_run(
                f.run_payload(
                    manifest["id"],
                    env.truck["id"],
                    env.stand["id"],
                    LEGAL_START,
                    LEGAL_END,
                ),
                LM_BOB,
            ),
            ApiErrorId.ERR_MANIFEST_NOT_ISSUED.value,
            409,
        )

        stored = validate_success(
            api.get_loading_manifest(manifest["id"], LM_BOB), 200
        )
        assert stored["status"] == "DRAFT"
        # Nothing is pinned until the manifest is issued.
        assert not stored.get("cart_seal_snapshot")
        assert stored["total_units"] == 0
        assert read_flight(api, env.flight_id)["status"] == "PLANNED"
        _, meta = validate_paginated(
            api.list_delivery_runs(LM_BOB, {"loading_manifest_id": manifest["id"]})
        )
        assert_total_count(meta, 0)


class TestReconciliationAndDisposition:
    """Conservation arithmetic, the per-line sum, and the bonded gates above them."""

    def test_consumed_plus_returned_must_equal_the_units_actually_uplifted(
        self, departed_env
    ):
        """The rule aggregates rows the payload never names, and burns no version.

        PRD §3.9: "That check is the conservation rule: submitted `consumed_units` plus submitted `returned_units` must equal `uplifted_units`, and a discrepancy is refused with `ERR_UPLIFT_UNITS_MISMATCH`."

        Design: Corner/validations/uplift_lines_that_do_not_reconcile_against_the_active_items_are_rejected
        """
        env = departed_env
        api = env.api
        set_clock(api, CLOCK_UPLIFT)
        version = read_flight(api, env.flight_id)["version"]
        spec_id = env.specs["Y"]["id"]

        validate_error(
            api.create_uplift_record(
                env.flight_id,
                f.uplift_payload(version, [f.uplift_line(spec_id, 170, 5)]),
                COMPLIANCE,
            ),
            ApiErrorId.ERR_UPLIFT_UNITS_MISMATCH.value,
            422,
        )
        assert read_flight(api, env.flight_id)["status"] == "DEPARTED"
        _, meta = validate_paginated(
            api.list_uplift_records(COMPLIANCE, {"flight_id": env.flight_id})
        )
        assert_total_count(meta, 0)

        # The refused call did not consume the version: the same guard still fits.
        record = validate_success(
            api.create_uplift_record(
                env.flight_id,
                f.uplift_payload(version, [f.uplift_line(spec_id, 170, 10)]),
                COMPLIANCE,
            ),
            201,
        )
        assert record["uplifted_units"] == 180
        assert record["consumed_units"] == 170
        assert record["returned_units"] == 10
        assert record["unused_units"] == 10
        assert read_flight(api, env.flight_id)["status"] == "RECONCILED"

    def test_each_disposition_line_must_sum_to_its_own_returned_units(
        self, reconciled_env
    ):
        """Nine against ten returned is refused, and the record stays priced at gross.

        PRD §3.9: "For every line, re-used plus donated plus destroyed units must equal that line's `returned_units`, or the request is refused with `ERR_DISPOSITION_UNITS_MISMATCH`."

        Design: Corner/validations/a_disposition_line_that_does_not_sum_to_its_returned_units_is_rejected
        """
        env = reconciled_env
        api = env.api
        record_id = env.uplift["id"]
        spec_id = env.specs["Y"]["id"]

        validate_error(
            api.record_dispositions(
                record_id,
                f.dispositions_payload([f.disposition_line(spec_id, 0, 0, 9)]),
                COMPLIANCE,
            ),
            ApiErrorId.ERR_DISPOSITION_UNITS_MISMATCH.value,
            422,
        )
        refused = validate_success(api.get_uplift_record(record_id, COMPLIANCE), 200)
        assert refused["status"] == "DRAFT"
        assert refused["gross_cost_cents"] == 292320
        assert refused["net_cost_cents"] == 292320

        accepted = validate_success(
            api.record_dispositions(
                record_id,
                f.dispositions_payload([f.disposition_line(spec_id, 0, 0, 10)]),
                COMPLIANCE,
            ),
            200,
        )
        assert accepted["status"] == "DISPOSITIONED"
        assert accepted["lines"][0]["destroy_units"] == 10
        # A bonded airline destroys everything, so no credit arises.
        assert accepted["net_cost_cents"] == 292320
        batch = validate_success(
            api.get_production_batch(env.batch["id"], SUPERVISOR), 200
        )
        assert batch["production_status"] == "DISPOSED"

    def test_the_bonded_reuse_gate_outranks_the_per_line_sum_check(
        self, reconciled_env
    ):
        """A payload violating both bands reports the customs breach, not the arithmetic.

        PRD §3.9: "When the airline's `waste_regime` is `BONDED`, every line must carry `reuse_units` of 0 and `donate_units` of 0, because bonded international waste may be neither re-used nor donated; a non-zero figure in either is refused with `ERR_BONDED_REUSE_FORBIDDEN`."

        Design: Corner/validations/the_bonded_reuse_gate_outranks_the_disposition_sum_check
        """
        env = reconciled_env
        api = env.api
        record_id = env.uplift["id"]
        spec_id = env.specs["Y"]["id"]
        version = env.uplift["version"]
        assert env.airline["waste_regime"] == "BONDED"

        # 4 + 0 + 6 sums correctly to the ten returned units.
        validate_error(
            api.record_dispositions(
                record_id,
                f.dispositions_payload([f.disposition_line(spec_id, 4, 0, 6)]),
                COMPLIANCE,
            ),
            ApiErrorId.ERR_BONDED_REUSE_FORBIDDEN.value,
            422,
        )
        # 4 + 0 + 5 breaks the sum as well, and still reports the higher band.
        validate_error(
            api.record_dispositions(
                record_id,
                f.dispositions_payload([f.disposition_line(spec_id, 4, 0, 5)]),
                COMPLIANCE,
            ),
            ApiErrorId.ERR_BONDED_REUSE_FORBIDDEN.value,
            422,
        )

        stored = validate_success(api.get_uplift_record(record_id, COMPLIANCE), 200)
        assert stored["status"] == "DRAFT"
        assert stored["version"] == version

    def test_a_bonded_airline_may_only_incinerate_its_waste(self, dispositioned_env):
        """The permitted route is reached through the record's flight and airline.

        PRD §3.9: "`disposal_method` is one of `INCINERATION`, `RENDERING` or `LANDFILL`, but the regime constrains the choice: a `BONDED` regime permits `INCINERATION` only, while a `DOMESTIC` regime permits all three; anything outside the permitted set is refused with `ERR_BONDED_WASTE_DISPOSAL_INVALID`."

        Design: Corner/validations/a_bonded_airline_may_only_incinerate_its_waste
        """
        env = dispositioned_env
        api = env.api
        record_id = env.uplift["id"]

        validate_error(
            api.create_waste_manifest(
                f.waste_manifest_payload(record_id, "RENDERING", "WM-AN411-01"),
                COMPLIANCE,
            ),
            ApiErrorId.ERR_BONDED_WASTE_DISPOSAL_INVALID.value,
            422,
        )
        _, meta = validate_paginated(
            api.list_waste_manifests(COMPLIANCE, {"uplift_record_id": record_id})
        )
        assert_total_count(meta, 0)

        # The refused seal number was never reserved.
        manifest = validate_success(
            api.create_waste_manifest(
                f.waste_manifest_payload(record_id, "INCINERATION", "WM-AN411-01"),
                COMPLIANCE,
            ),
            201,
        )
        assert manifest["status"] == "DRAFT"
        assert manifest["regime"] == "BONDED"
        assert manifest["disposal_method"] == "INCINERATION"
        assert manifest["seal_number"] == "WM-AN411-01"
        # Ten destroyed units of a 700-gram tray.
        assert manifest["sealed_weight_grams"] == 7000
        assert_cart_axes(read_cart(api, env.cart["id"]), "RETURNED", "BROKEN")
