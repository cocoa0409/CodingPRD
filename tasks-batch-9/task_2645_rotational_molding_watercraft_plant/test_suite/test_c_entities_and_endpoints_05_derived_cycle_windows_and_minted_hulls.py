"""Fields the client can never post: cycle window projections and hull rows.

PRD.md section 2.8 splits every resource into client-supplied and derived
fields and says the derived ones "are computed by the service and are never
accepted from a client". This file pins the two hardest cases: the three
butt-jointed window instants plus the charge roll-ups on a cycle, and the hull
rows the demould cascade mints one per cavity.
"""

from test_helpers import (
    assert_common_fields,
    assert_cycle_window_projection,
    assert_decimal_equals,
    assert_hull_serial_format,
    assert_instant_equals,
    assert_null_fields,
    assert_pagination_meta,
    assert_resin_ledger_conserved,
    create_plant_baseline,
    create_production_order,
    create_resin_lot,
    dec,
    get_success_data,
    molding_cycle_payload,
    resin_charge_payload,
    resin_lot_version,
    production_order_version,
    run_cycle_to_demold,
    validate_paginated,
    validate_success,
)

Q_MASS = dec("0.001")
Q_PCT = dec("0.01")


def _p3_schedule_cycle(ctx, order, **overrides):
    """Schedule one cycle, always naming the acting operator explicitly.

    ``test_helpers.factories.molding_cycle_payload`` deliberately omits
    ``operator_technician_id``, but PRD.md section 2.8 lists it as a required
    client-supplied field on MoldingCycle ("`operator_technician_id`
    (required, must resolve or `ERR_TECHNICIAN_NOT_FOUND`, and must equal the
    acting identifier at creation or `ERR_ROLE_IDENTITY_MISMATCH`)"), so this
    partition sends it. Sending the acting identifier satisfies section 3.4's
    reading as well, under which the server takes it from the caller.
    """
    payload = molding_cycle_payload(
        order["id"],
        ctx["oven_station_id"],
        ctx["cooling_bay_id"],
        production_order_version(order["id"]),
        operator_technician_id=ctx["molding_operator_id"],
        **overrides,
    )
    return payload


def _p3_charge_payload(ctx, cycle, lot, **overrides):
    """Body for POST /resin-charges that names the acting technician.

    ``test_helpers.factories.resin_charge_payload`` omits
    ``created_by_technician_id``, which PRD.md section 2.8 lists as required on
    ResinCharge, so this partition supplies it.
    """
    return resin_charge_payload(
        cycle["id"],
        lot["id"],
        resin_lot_version(lot["id"]),
        created_by_technician_id=ctx["resin_technician_id"],
        **overrides,
    )


class TestDerivedCycleWindowsAndChargeRollups:
    """POST /molding-cycles takes one instant and two durations, and returns three."""

    @staticmethod
    def _released_order():
        ctx = create_plant_baseline()
        ctx["resin_lot"] = create_resin_lot()
        ctx["production_order"] = create_production_order(
            ctx, order_code="POR-CD-COMP", ordered_qty=2
        )
        return ctx

    def test_the_three_projected_instants_are_butt_jointed(self, api):
        """The oven and cooling phases share one boundary instant.

        PRD.md section 2.9: "When a cycle is scheduled, three projected instants
        are derived from the client's inputs: `oven_end_at` is `oven_start_at`
        advanced by `scheduled_oven_minutes`; `cooling_window_start_at` is
        exactly `oven_end_at`, so the oven and cooling phases are butt-jointed
        with no gap; and `cooling_window_end_at` is `cooling_window_start_at`
        advanced by `scheduled_cooling_minutes`."

        Design: Corner/entities/ent_computed_cycle_windows_and_charge_rollups_derived_not_supplied
        """
        ctx = self._released_order()

        created = validate_success(
            api.create_molding_cycle(
                _p3_schedule_cycle(ctx, ctx["production_order"]),
                ctx["operator_headers"],
            ),
            expected_status=201,
        )

        assert_common_fields(created, "MoldingCycle")
        assert_instant_equals(
            created["oven_start_at"], "2026-08-01T09:00:00Z", "oven_start_at"
        )
        assert_instant_equals(
            created["oven_end_at"], "2026-08-01T10:00:00Z", "oven_end_at"
        )
        assert_instant_equals(
            created["cooling_window_start_at"],
            "2026-08-01T10:00:00Z",
            "cooling_window_start_at",
        )
        assert_instant_equals(
            created["cooling_window_end_at"],
            "2026-08-01T10:30:00Z",
            "cooling_window_end_at",
        )
        assert_cycle_window_projection(created)

    def test_server_selected_tool_and_empty_actuals_at_scheduled(self, api):
        """`mold_id` is chosen by the server and no actual stamp exists yet.

        PRD.md section 2.8, MoldingCycle: "Derived: `mold_id`, always chosen by
        the server and never accepted from a client"; "the actual-time stamps
        `actual_oven_start_at`, `actual_oven_end_at` and `actual_cooling_end_at`
        (all default null)"; "`provisional_warpage_index` (default null, three
        decimals, clamped between 0.000 and 5.000)".

        PRD.md section 3.4: "`status` is `SCHEDULED`, `charged_mass_kg` is
        0.000, `operator_technician_id` is the acting identifier, and the order
        moves `READY_TO_SCHEDULE` to `IN_PRODUCTION` on the first accepted
        cycle."

        Design: Corner/entities/ent_computed_cycle_windows_and_charge_rollups_derived_not_supplied
        """
        ctx = self._released_order()

        created = validate_success(
            api.create_molding_cycle(
                _p3_schedule_cycle(ctx, ctx["production_order"]),
                ctx["operator_headers"],
            ),
            expected_status=201,
        )

        assert created["mold_id"] == ctx["mold_id"]
        assert created["operator_technician_id"] == ctx["molding_operator_id"]
        assert created["status"] == "SCHEDULED"
        assert_null_fields(
            created,
            [
                "actual_oven_start_at",
                "actual_oven_end_at",
                "actual_cooling_end_at",
                "provisional_warpage_index",
                "abort_reason",
            ],
            "MoldingCycle",
        )
        order = validate_success(
            api.get_production_order(
                ctx["production_order"]["id"], ctx["admin_headers"]
            )
        )
        assert order["status"] == "IN_PRODUCTION"

    def test_the_roll_ups_are_empty_until_a_charge_exists(self, api):
        """A cycle with no charge carries a zero mass and a null blend index.

        PRD.md section 3.4: "`status` is `SCHEDULED`, `charged_mass_kg` is
        0.000, `operator_technician_id` is the acting identifier, and the order
        moves `READY_TO_SCHEDULE` to `IN_PRODUCTION` on the first accepted
        cycle."

        PRD.md section 3.2: "When `charged_mass_kg` is 0.000 the weighted index
        is null."

        PRD.md section 3.2: "the two masses are rounded *before* the division,
        and when `total_charge_kg` is 0.000 the percentage is 0.00."

        Design: Corner/entities/ent_computed_cycle_windows_and_charge_rollups_derived_not_supplied
        """
        ctx = self._released_order()

        created = validate_success(
            api.create_molding_cycle(
                _p3_schedule_cycle(ctx, ctx["production_order"]),
                ctx["operator_headers"],
            ),
            expected_status=201,
        )

        assert_decimal_equals(
            created["charged_mass_kg"], "0.000", Q_MASS, "charged_mass_kg"
        )
        assert created["weighted_melt_index_g10min"] is None
        assert_decimal_equals(
            created["cycle_regrind_pct"], "0.00", Q_PCT, "cycle_regrind_pct"
        )

    def test_a_reserved_charge_writes_the_roll_ups_and_moves_the_ledger(self, api):
        """One charge fills all three roll-ups and both charge-side derivations.

        PRD.md section 3.2: "`charged_mass_kg` is the sum of `charge_kg` over
        the participating charges rounded to three decimals."

        PRD.md section 3.2: "`weighted_melt_index_g10min` is the mass-weighted
        mean melt index: the sum, over participating charges, of `charge_kg`
        multiplied by that charge's lot's `melt_index_g10min`, divided by
        `charged_mass_kg`, and rounded to two decimals *once* at the end — the
        per-charge products are never rounded individually, because doing so
        drifts."

        PRD.md section 3.2: "the cycle's regrind percentage is then
        `total_regrind_kg` divided by `total_charge_kg` times 100, rounded to
        two decimals".

        PRD.md section 3.2: "On acceptance `status` is `RESERVED`,
        `created_by_technician_id` is the acting identifier, `virgin_kg` is
        `charge_kg` minus `regrind_kg` rounded to three decimals, and
        `charge_regrind_pct` is `regrind_kg` divided by `charge_kg` times 100
        rounded to two decimals."

        PRD.md section 3.2: "The lot's `available_kg` falls and its
        `reserved_kg` rises by `charge_kg`, preserving the invariant that the
        rounded sum of `available_kg`, `reserved_kg` and `consumed_kg` equals
        `received_kg`".

        Design: Corner/entities/ent_computed_cycle_windows_and_charge_rollups_derived_not_supplied
        """
        ctx = self._released_order()
        cycle = get_success_data(
            api.create_molding_cycle(
                _p3_schedule_cycle(ctx, ctx["production_order"]),
                ctx["operator_headers"],
            )
        )

        charge = validate_success(
            api.create_resin_charge(
                _p3_charge_payload(
                    ctx, cycle, ctx["resin_lot"], charge_kg=24.0, regrind_kg=2.4
                ),
                ctx["resin_tech_headers"],
            ),
            expected_status=201,
        )

        assert_decimal_equals(charge["virgin_kg"], "21.600", Q_MASS, "virgin_kg")
        assert_decimal_equals(
            charge["charge_regrind_pct"], "10.00", Q_PCT, "charge_regrind_pct"
        )
        assert charge["created_by_technician_id"] == ctx["resin_technician_id"]
        assert charge["status"] == "RESERVED"
        assert charge.get("released_reason") is None

        rolled = validate_success(
            api.get_molding_cycle(cycle["id"], ctx["admin_headers"])
        )
        assert_decimal_equals(
            rolled["charged_mass_kg"], "24.000", Q_MASS, "charged_mass_kg"
        )
        assert_decimal_equals(
            rolled["cycle_regrind_pct"], "10.00", Q_PCT, "cycle_regrind_pct"
        )
        assert_decimal_equals(
            rolled["weighted_melt_index_g10min"],
            "4.00",
            Q_PCT,
            "weighted_melt_index_g10min",
        )

        lot = validate_success(
            api.get_resin_lot(ctx["resin_lot"]["id"], ctx["admin_headers"])
        )
        assert_decimal_equals(lot["available_kg"], "476.000", Q_MASS, "available_kg")
        assert_decimal_equals(lot["reserved_kg"], "24.000", Q_MASS, "reserved_kg")
        assert_decimal_equals(lot["consumed_kg"], "0.000", Q_MASS, "consumed_kg")
        assert_decimal_equals(lot["received_kg"], "500.000", Q_MASS, "received_kg")
        assert_resin_ledger_conserved(lot)


class TestHullsMintedByTheDemouldCascade:
    """One demould of a two-cavity tool mints exactly two hull rows."""

    @staticmethod
    def _demoulded(api):
        ctx = create_plant_baseline()
        ctx["resin_lot"] = create_resin_lot()
        ctx["production_order"] = create_production_order(
            ctx, order_code="POR-CD-SYS", ordered_qty=2
        )
        cycle = get_success_data(
            api.create_molding_cycle(
                _p3_schedule_cycle(ctx, ctx["production_order"]),
                ctx["operator_headers"],
            )
        )
        get_success_data(
            api.create_resin_charge(
                _p3_charge_payload(
                    ctx, cycle, ctx["resin_lot"], charge_kg=24.0, regrind_kg=2.4
                ),
                ctx["resin_tech_headers"],
            )
        )
        ctx["molding_cycle"] = cycle
        ctx["molding_cycle_id"] = cycle["id"]
        return run_cycle_to_demold(ctx)

    def test_one_hull_per_cavity_with_deterministic_serials(self, api):
        """Two rows appear, in ascending cavity order, with business serials.

        PRD.md section 2.8: "**FinishedUnit** is never created directly; it is
        minted by the demould cascade, and it carries two independent state axes
        on one row."

        PRD.md section 3.5: "For each `cavity_index` from 1 to the tool's
        `cavity_count`, in ascending order, one hull is created with
        `hull_serial` formed as the order's `order_code`, a hyphen,
        `cavity_index` zero-padded to two digits, a hyphen, and `build_seq` plus
        `cavity_index` minus 1 zero-padded to four digits."

        PRD.md section 3.5: "`build_seq` is 1 plus the number of hulls already
        created for the producing order, counted across all of its cycles."

        PRD.md section 3.5: "a multi-cavity tool yields `cavity_count` hulls in
        one request, and because they are created in ascending cavity order
        their `created_at` ordering matches their cavity order."

        Design: Corner/entities/ent_system_fields_on_finished_unit_minted_by_the_demold_cascade
        """
        ctx = self._demoulded(api)

        rows, meta = validate_paginated(
            api.list_finished_units(
                {"molding_cycle_id": ctx["molding_cycle_id"]}, ctx["admin_headers"]
            )
        )

        assert_pagination_meta(meta, 2, 10, 0)
        assert meta["has_more"] is False
        ordered = sorted(rows, key=lambda unit: unit["cavity_index"])
        assert [unit["cavity_index"] for unit in ordered] == [1, 2]
        assert ordered[0]["hull_serial"] == "POR-CD-SYS-01-0001"
        assert ordered[1]["hull_serial"] == "POR-CD-SYS-02-0002"
        for unit in ordered:
            assert_hull_serial_format(
                unit["hull_serial"], "POR-CD-SYS", unit["cavity_index"]
            )
            assert unit["id"] not in unit["hull_serial"], (
                "the serial is derived from business fields, never from the row id"
            )
        assert ordered[0]["created_at"] <= ordered[1]["created_at"]

    def test_the_three_system_fields_are_copied_from_the_producing_rows(self, api):
        """`molding_cycle_id`, `product_model_id` and `cavity_index` are set once.

        PRD.md section 2.8: "Set by the cascade and thereafter immutable:
        `molding_cycle_id`, `product_model_id` (copied from the producing tool)
        and `cavity_index` (a 1-based cavity position no greater than the tool's
        `cavity_count`)."

        Design: Corner/entities/ent_system_fields_on_finished_unit_minted_by_the_demold_cascade
        """
        ctx = self._demoulded(api)

        for unit in ctx["finished_units"]:
            read = validate_success(
                api.get_finished_unit(unit["id"], ctx["admin_headers"])
            )
            assert_common_fields(read, "FinishedUnit")
            assert read["molding_cycle_id"] == ctx["molding_cycle_id"]
            assert read["product_model_id"] == ctx["product_model_id"]
            assert 1 <= read["cavity_index"] <= ctx["mold"]["cavity_count"]
            assert read["version"] == 1
            assert_instant_equals(
                read["created_at"], "2026-08-01T10:35:00Z", "created_at"
            )
