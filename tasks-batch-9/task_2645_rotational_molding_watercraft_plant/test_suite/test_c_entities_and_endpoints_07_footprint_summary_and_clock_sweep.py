"""The two whole-site computed reads: the footprint summary and the clock sweep.

Both endpoints exist so a test can observe arithmetic the write paths performed
without recomputing it. The footprint summary is asserted against a nest group
of two hulls, where the anchor pays its full cube and the follower pays the
nested cube, and the clock set is asserted as an active sweep whose four
counters are reported per call rather than accumulated.
"""

from test_helpers import (
    CLOCK_DEFAULT_UTC,
    assert_decimal_equals,
    assert_footprint_summary_consistent,
    assert_instant_equals,
    assert_posture_for_utilization,
    create_plant_baseline,
    dec,
    setup_scheduled_cycle,
    setup_stored_units,
    validate_success,
)

Q_CUBE = dec("0.0001")
Q_PCT = dec("0.01")
Q_MASS = dec("0.001")

EXPIRY_DATE = "2026-08-05"
ON_EXPIRY_INSTANT = "2026-08-05T00:00:00Z"
PAST_EXPIRY_INSTANT = "2026-08-06T00:00:00Z"


def _p3_identity_overrides(ctx, cycle_overrides=None, charge_overrides=None):
    """Name the acting technicians that the shared payload factories omit.

    ``test_helpers.factories.molding_cycle_payload`` omits
    ``operator_technician_id`` and ``resin_charge_payload`` omits
    ``created_by_technician_id``, yet PRD.md section 2.8 lists both as required
    client-supplied fields. This partition supplies each one as the acting
    identifier, which satisfies that reading and the section 3.2 and 3.4
    reading in which the server copies it from the caller.
    """
    cyc = dict(cycle_overrides or {})
    cyc.setdefault("operator_technician_id", ctx["molding_operator_id"])
    chg = dict(charge_overrides or {})
    chg.setdefault("created_by_technician_id", ctx["resin_technician_id"])
    return cyc, chg


def _p3_stored_pair():
    """A single-zone site holding one nest group of two hulls of one model.

    The default plant registers a 20.0000 cube site with the single zone
    ``Z-A``, and the default two-cavity tool yields two hulls of one model, so
    storing both opens the nest group with the anchor at 2.0000 and joins the
    follower at 1.0000 for 3.0000 committed of 20.0000.
    """
    baseline = create_plant_baseline()
    cyc, chg = _p3_identity_overrides(baseline)
    return setup_stored_units(
        baseline=baseline,
        order_overrides={"order_code": "POR-CD-FOOT", "ordered_qty": 2},
        cycle_overrides=cyc,
        charge_overrides=chg,
    )


class TestWarehouseFootprintSummary:
    """GET /warehouses/{warehouse_id}/footprint-summary over one nest group."""

    def test_site_totals_and_posture_report_the_nested_pair(
        self, api, planner_headers
    ):
        """Two hulls of one model commit 3.0000 cube, not 4.0000 gross.

        PRD.md section 3.1: "A computed footprint read reports `warehouse_id`,
        `footprint_capacity_cube_m3`, `committed_cube_m3`, `remaining_cube_m3`,
        `utilization_pct`, `posture`, a `zones` array of `{ zone_code,
        capacity_cube_m3, committed_cube_m3, remaining_cube_m3,
        anchor_product_model_ids, stored_unit_count }`, and
        `blocked_production_order_count` — the number of orders sitting in
        `BLOCKED_WAREHOUSE` that target this site — so the nesting arithmetic of
        section 3.7 is observable without recomputation."

        PRD.md section 3.7: "The two selection variants have materially
        different cost. Opening a **new nest group** — no eligible zone anchors
        this model — charges the full `gross_cube_m3` and sets `is_zone_anchor`
        true. **Joining an existing nest group** charges `gross_cube_m3`
        multiplied by `nest_factor` and leaves `is_zone_anchor` false, and the
        affinity term forces that zone even when a wholly empty zone would give
        a looser fit."

        PRD.md section 3.7: "(3) `utilization_pct` is recomputed as
        `committed_cube_m3` divided by `footprint_capacity_cube_m3` times 100,
        rounded to two decimals, and `posture` is re-derived from it".

        PRD.md section 3.7: "**Posture** is derived, never stored
        independently: `posture` is `FROZEN` when `utilization_pct` is at or
        above `frozen_threshold_pct`, `RESTRICTED` when it is at or above
        `restricted_threshold_pct` but below the frozen threshold, and `NORMAL`
        otherwise."

        PRD.md section 3.8: "the site's remaining cube —
        `footprint_capacity_cube_m3` minus `committed_cube_m3`".

        Design: Corner/endpoints/ep_warehouse_footprint_summary_zone_breakdown_matches_the_stored_hulls
        """
        ctx = _p3_stored_pair()

        summary = validate_success(
            api.get_warehouse_footprint_summary(ctx["warehouse_id"], planner_headers)
        )

        assert summary["warehouse_id"] == ctx["warehouse_id"]
        assert_decimal_equals(
            summary["footprint_capacity_cube_m3"],
            "20.0000",
            Q_CUBE,
            "footprint_capacity_cube_m3",
        )
        assert_decimal_equals(
            summary["committed_cube_m3"], "3.0000", Q_CUBE, "committed_cube_m3"
        )
        assert_decimal_equals(
            summary["remaining_cube_m3"], "17.0000", Q_CUBE, "remaining_cube_m3"
        )
        assert_decimal_equals(
            summary["utilization_pct"], "15.00", Q_PCT, "utilization_pct"
        )
        assert summary["posture"] == "NORMAL"
        assert summary["blocked_production_order_count"] == 0
        assert_footprint_summary_consistent(summary)
        assert_posture_for_utilization(
            summary["posture"],
            summary["utilization_pct"],
            ctx["warehouse"]["restricted_threshold_pct"],
            ctx["warehouse"]["frozen_threshold_pct"],
        )

    def test_zone_breakdown_names_the_anchor_model_and_counts_both_hulls(
        self, api, planner_headers
    ):
        """The single zone row carries the anchored model and a count of 2.

        PRD.md section 3.1: "A computed footprint read reports `warehouse_id`,
        `footprint_capacity_cube_m3`, `committed_cube_m3`, `remaining_cube_m3`,
        `utilization_pct`, `posture`, a `zones` array of `{ zone_code,
        capacity_cube_m3, committed_cube_m3, remaining_cube_m3,
        anchor_product_model_ids, stored_unit_count }`, and
        `blocked_production_order_count` — the number of orders sitting in
        `BLOCKED_WAREHOUSE` that target this site — so the nesting arithmetic of
        section 3.7 is observable without recomputation."

        PRD.md section 3.7: "**Zone selection** treats a nest group as the
        triple of site, `storage_zone_code` and `product_model_id`."

        PRD.md section 3.7: "an anchor exists when some occupying hull in that
        zone shares the candidate's `product_model_id` and carries
        `is_zone_anchor` true".

        PRD.md section 3.7: "the zone's committed cube is the rounded sum of
        `stored_footprint_cube_m3` over its occupying hulls".

        PRD.md section 3.7: "A hull is counted as occupying a zone when its
        `logistics_status` is `STORED` **or** `LOADED` — a loaded hull is still
        physically in its zone until the trailer departs."

        Design: Corner/endpoints/ep_warehouse_footprint_summary_zone_breakdown_matches_the_stored_hulls
        """
        ctx = _p3_stored_pair()

        summary = validate_success(
            api.get_warehouse_footprint_summary(ctx["warehouse_id"], planner_headers)
        )

        zones = summary["zones"]
        assert len(zones) == 1, (
            f"the site declares one zone, so the breakdown carries one row; "
            f"got {len(zones)}"
        )
        zone = zones[0]
        assert zone["zone_code"] == ctx["warehouse"]["zones"][0]["zone_code"]
        assert_decimal_equals(
            zone["capacity_cube_m3"], "20.0000", Q_CUBE, "zone capacity_cube_m3"
        )
        assert_decimal_equals(
            zone["committed_cube_m3"], "3.0000", Q_CUBE, "zone committed_cube_m3"
        )
        assert_decimal_equals(
            zone["remaining_cube_m3"], "17.0000", Q_CUBE, "zone remaining_cube_m3"
        )
        assert zone["stored_unit_count"] == 2
        assert list(zone["anchor_product_model_ids"]) == [ctx["product_model_id"]], (
            "exactly one model has an anchor in this zone, so exactly one "
            "identifier is listed"
        )

        footprints = sorted(
            dec(unit["stored_footprint_cube_m3"]) for unit in ctx["stored_units"]
        )
        assert_decimal_equals(footprints[0], "1.0000", Q_CUBE, "follower footprint")
        assert_decimal_equals(footprints[1], "2.0000", Q_CUBE, "anchor footprint")
        assert sum(1 for unit in ctx["stored_units"] if unit["is_zone_anchor"]) == 1
        for unit in ctx["stored_units"]:
            assert unit["storage_zone_code"] == zone["zone_code"]
            assert unit["logistics_status"] == "STORED"


class TestClockSetSweepCounters:
    """POST /_clock/set_current_utc is an active sweep, not an assignment."""

    @staticmethod
    def _plant_with_a_lot_expiring_on_the_fifth():
        """One released order, one SCHEDULED cycle, one RESERVED charge, one lot.

        The lot is the only one in the plant and it expires on 2026-08-05, so
        once it expires no other lot can qualify the order.
        """
        baseline = create_plant_baseline()
        cyc, chg = _p3_identity_overrides(baseline)
        return setup_scheduled_cycle(
            baseline=baseline,
            order_overrides={"order_code": "POR-CD-CLK", "ordered_qty": 2},
            cycle_overrides=cyc,
            lot_overrides={"lot_code": "LOT-CD-EXP", "expires_on": EXPIRY_DATE},
            charge_overrides=chg,
        )

    def test_advancing_to_the_expiry_date_itself_sweeps_nothing(
        self, api, admin_headers
    ):
        """A lot whose `expires_on` equals the new calendar date survives.

        PRD.md section 3.2: "When `PlantAdmin` sets `current_utc`, the service
        (1) stores the new instant, then (2) moves every lot whose `expires_on`
        is *strictly before* the new clock's calendar date to `EXPIRED` — a lot
        whose `expires_on` equals the new date is *not* expired".

        PRD.md section 3.2: "The response reports `current_utc`, the constant
        `default_utc` of `2026-08-01T00:00:00Z`, and the four sweep counters
        `expired_resin_lot_count`, `released_resin_charge_count`,
        `aborted_molding_cycle_count` and `blocked_production_order_count`."

        PRD.md section 2.5: "At startup the clock reads exactly
        `2026-08-01T00:00:00Z`, and that same instant is reported as the clock's
        default."

        Design: Corner/endpoints/ep_clock_set_current_utc_returns_the_four_declared_cascade_counters
        """
        ctx = self._plant_with_a_lot_expiring_on_the_fifth()

        response = api.set_clock({"current_utc": ON_EXPIRY_INSTANT}, admin_headers)

        assert response.status_code == 200
        swept = validate_success(response)
        assert_instant_equals(swept["current_utc"], ON_EXPIRY_INSTANT, "current_utc")
        assert_instant_equals(swept["default_utc"], CLOCK_DEFAULT_UTC, "default_utc")
        assert swept["expired_resin_lot_count"] == 0
        assert swept["released_resin_charge_count"] == 0
        assert swept["aborted_molding_cycle_count"] == 0
        assert swept["blocked_production_order_count"] == 0

        lot = validate_success(api.get_resin_lot(ctx["resin_lot_id"], admin_headers))
        assert lot["status"] == "AVAILABLE"
        charge = validate_success(
            api.get_resin_charge(ctx["resin_charge_id"], admin_headers)
        )
        assert charge["status"] == "RESERVED"
        cycle = validate_success(
            api.get_molding_cycle(ctx["molding_cycle_id"], admin_headers)
        )
        assert cycle["status"] == "SCHEDULED"

    def test_advancing_past_the_expiry_date_returns_all_four_counters(
        self, api, admin_headers
    ):
        """One expired lot drags its charge, its cycle and its order with it.

        PRD.md section 3.2: "When `PlantAdmin` sets `current_utc`, the service
        (1) stores the new instant, then (2) moves every lot whose `expires_on`
        is *strictly before* the new clock's calendar date to `EXPIRED` — a lot
        whose `expires_on` equals the new date is *not* expired; (3) every
        `RESERVED` charge on those lots becomes `RELEASED` with
        `released_reason` `LOT_EXPIRED`, returning `charge_kg` to
        `available_kg`; (4) every `SCHEDULED` cycle holding one of those charges
        becomes `ABORTED` with `abort_reason` `LOT_EXPIRED`; and (5) every order
        left with no qualified lot moves to `BLOCKED_RESIN` with
        `blocked_reason` `NO_QUALIFIED_RESIN_LOT`."

        PRD.md section 3.2: "The response reports `current_utc`, the constant
        `default_utc` of `2026-08-01T00:00:00Z`, and the four sweep counters
        `expired_resin_lot_count`, `released_resin_charge_count`,
        `aborted_molding_cycle_count` and `blocked_production_order_count`."

        PRD.md section 2.5: "Setting the clock is not a passive assignment:
        after the new instant is stored, the service sweeps resin lots whose
        `expires_on` calendar date now lies strictly before the clock's calendar
        date and expires them, with all of the cascade consequences described in
        section 3.2."

        PRD.md section 2.5: "Dates supplied as `YYYY-MM-DD` — a resin lot's
        `expires_on`, a demand bucket's `window_start_on` and `window_end_on` —
        are compared against the calendar date of the logical clock in UTC,
        never against its time of day."

        Design: Corner/endpoints/ep_clock_set_current_utc_returns_the_four_declared_cascade_counters
        """
        ctx = self._plant_with_a_lot_expiring_on_the_fifth()
        validate_success(api.set_clock({"current_utc": ON_EXPIRY_INSTANT}, admin_headers))

        response = api.set_clock({"current_utc": PAST_EXPIRY_INSTANT}, admin_headers)

        assert response.status_code == 200
        swept = validate_success(response)
        assert_instant_equals(swept["current_utc"], PAST_EXPIRY_INSTANT, "current_utc")
        assert_instant_equals(swept["default_utc"], CLOCK_DEFAULT_UTC, "default_utc")
        assert swept["expired_resin_lot_count"] == 1
        assert swept["released_resin_charge_count"] == 1
        assert swept["aborted_molding_cycle_count"] == 1
        assert swept["blocked_production_order_count"] == 1

        lot = validate_success(api.get_resin_lot(ctx["resin_lot_id"], admin_headers))
        assert lot["status"] == "EXPIRED"
        assert_decimal_equals(lot["available_kg"], "500.000", Q_MASS, "available_kg")
        assert_decimal_equals(lot["reserved_kg"], "0.000", Q_MASS, "reserved_kg")
        assert_decimal_equals(lot["consumed_kg"], "0.000", Q_MASS, "consumed_kg")

        charge = validate_success(
            api.get_resin_charge(ctx["resin_charge_id"], admin_headers)
        )
        assert charge["status"] == "RELEASED"
        assert charge["released_reason"] == "LOT_EXPIRED"

        cycle = validate_success(
            api.get_molding_cycle(ctx["molding_cycle_id"], admin_headers)
        )
        assert cycle["status"] == "ABORTED"
        assert cycle["abort_reason"] == "LOT_EXPIRED"

        order = validate_success(
            api.get_production_order(ctx["production_order_id"], admin_headers)
        )
        assert order["status"] == "BLOCKED_RESIN"
        assert order["blocked_reason"] == "NO_QUALIFIED_RESIN_LOT"

        read_back = validate_success(api.get_clock(admin_headers))
        assert_instant_equals(
            read_back["current_utc"], PAST_EXPIRY_INSTANT, "current_utc"
        )
