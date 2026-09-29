"""Two equipment action endpoints whose side effects reach other resources.

A mould service hold and an oven station mark-down are both heads of
compensating cascades. Each is asserted on a plant where more than one row is
in flight, so the tests distinguish what the cascade touches from what it
deliberately leaves alone.
"""

from test_helpers import (
    assert_decimal_equals,
    assert_resin_ledger_conserved,
    complete_service_payload,
    create_plant_baseline,
    dec,
    get_success_data,
    mark_down_payload,
    mold_payload,
    reserve_charge,
    run_cycle_to_oven_running,
    schedule_cycle,
    service_hold_payload,
    setup_scheduled_cycle,
    create_production_order,
    create_resin_lot,
    validate_success,
)

Q_MASS = dec("0.001")


def _p3_identity_overrides(ctx, cycle_overrides=None, charge_overrides=None):
    """Name the acting technicians that the shared payload factories omit.

    ``test_helpers.factories.molding_cycle_payload`` omits
    ``operator_technician_id`` and ``resin_charge_payload`` omits
    ``created_by_technician_id``, yet PRD.md section 2.8 lists both as required
    client-supplied fields. This partition supplies each one as the acting
    identifier, which satisfies that reading and the reading in which the
    server copies it from the caller.
    """
    cyc = dict(cycle_overrides or {})
    cyc.setdefault("operator_technician_id", ctx["molding_operator_id"])
    chg = dict(charge_overrides or {})
    chg.setdefault("created_by_technician_id", ctx["resin_technician_id"])
    return cyc, chg


def _p3_scheduled_plant(**kwargs):
    """One released order carrying one SCHEDULED cycle and one RESERVED charge."""
    baseline = create_plant_baseline()
    cyc, chg = _p3_identity_overrides(baseline)
    return setup_scheduled_cycle(
        baseline=baseline, cycle_overrides=cyc, charge_overrides=chg, **kwargs
    )


class TestMoldServicePair:
    """The manual service hold and its matching complete-service reset."""

    def test_service_hold_aborts_the_scheduled_cycle_and_returns_the_mass(
        self, api, admin_headers
    ):
        """A hold is a cascade, not a flag: the cycle dies and the resin comes back.

        PRD.md section 3.1: "From `AVAILABLE`, a service hold moves the tool to
        `MAINTENANCE`; the request may carry a `hold_note`. The hold is not a
        passive flag — it is the head of a compensating cascade: every cycle on
        that tool still in `SCHEDULED` becomes `ABORTED` with `abort_reason`
        `MOLD_SERVICE_DUE`; each of those cycles' `RESERVED` charges becomes
        `RELEASED` with `released_reason` `MOLD_SERVICE_DUE`, moving `charge_kg`
        from the lot's `reserved_kg` back to its `available_kg`; any lot that was
        `DEPLETED` and now holds mass returns to `AVAILABLE`; and every order in
        `BLOCKED_RESIN` that those revived lots qualify for is unblocked. The
        tool's `version` advances by 1."

        PRD.md section 2.4: "`version` is an integer that starts at 1 when the
        row is created and increments by exactly 1 on every persisted mutation,
        including mutations that occur as cascade side effects of a request
        aimed at a different resource."

        PRD.md section 3.2: "the rounded sum of `available_kg`, `reserved_kg`
        and `consumed_kg` equals `received_kg`".

        Design: Corner/endpoints/ep_mold_service_hold_aborts_its_cycle_then_complete_service_resets_the_counter
        """
        ctx = _p3_scheduled_plant()

        held = validate_success(
            api.service_hold_mold(
                ctx["mold_id"],
                service_hold_payload("cavity liner inspection"),
                admin_headers,
            )
        )

        assert held["status"] == "MAINTENANCE"
        assert held["version"] == 2, (
            "the tool was created at version 1 and the hold is one persisted "
            "mutation of it"
        )

        cycle = validate_success(
            api.get_molding_cycle(ctx["molding_cycle_id"], admin_headers)
        )
        assert cycle["status"] == "ABORTED"
        assert cycle["abort_reason"] == "MOLD_SERVICE_DUE"

        charge = validate_success(
            api.get_resin_charge(ctx["resin_charge_id"], admin_headers)
        )
        assert charge["status"] == "RELEASED"
        assert charge["released_reason"] == "MOLD_SERVICE_DUE"

        lot = validate_success(api.get_resin_lot(ctx["resin_lot_id"], admin_headers))
        assert_decimal_equals(lot["available_kg"], "500.000", Q_MASS, "available_kg")
        assert_decimal_equals(lot["reserved_kg"], "0.000", Q_MASS, "reserved_kg")
        assert_decimal_equals(lot["consumed_kg"], "0.000", Q_MASS, "consumed_kg")
        assert_resin_ledger_conserved(lot)

        order = validate_success(
            api.get_production_order(ctx["production_order_id"], admin_headers)
        )
        assert order["status"] == "IN_PRODUCTION", (
            "no declared link of the hold cascade walks the order backwards"
        )

    def test_complete_service_fully_resets_the_counter_rather_than_decrementing(
        self, api, admin_headers
    ):
        """Completing service puts `cycles_since_service` back to zero.

        PRD.md section 3.1: "Completing service requires `status`
        `MAINTENANCE`, may carry a `service_note`, resets `cycles_since_service`
        to zero — a full reset, never a decrement by the interval, so a serviced
        tool with a hundred lifetime demoulds reads 0 — and returns `status` to
        `AVAILABLE`, restoring the tool to the selection pool."

        PRD.md section 2.4: "`version` is an integer that starts at 1 when the
        row is created and increments by exactly 1 on every persisted mutation,
        including mutations that occur as cascade side effects of a request
        aimed at a different resource."

        Design: Corner/endpoints/ep_mold_service_hold_aborts_its_cycle_then_complete_service_resets_the_counter
        """
        ctx = _p3_scheduled_plant()
        get_success_data(
            api.service_hold_mold(
                ctx["mold_id"],
                service_hold_payload("cavity liner inspection"),
                admin_headers,
            )
        )

        serviced = validate_success(
            api.complete_service_mold(
                ctx["mold_id"],
                complete_service_payload("liner replaced"),
                admin_headers,
            )
        )

        assert serviced["status"] == "AVAILABLE"
        assert serviced["cycles_since_service"] == 0
        assert serviced["version"] == 3, (
            "create, hold and complete-service are three persisted mutations of "
            "the same row"
        )
        read_back = validate_success(api.get_mold(ctx["mold_id"], admin_headers))
        assert read_back["status"] == "AVAILABLE"
        assert read_back["cycles_since_service"] == 0
        assert read_back["version"] == 3


class TestOvenStationMarkDown:
    """One mark-down meets two cycles on the same station in different states."""

    @staticmethod
    def _two_cycles_on_one_station(api):
        """Arm 1 running with consumed resin, arm 2 scheduled with reserved resin.

        A second tool is registered for the same hull model, because the two
        cycles share one mould span and PRD.md section 3.4 excludes an occupied
        tool from the candidate pool.
        """
        ctx = create_plant_baseline()
        cyc, chg = _p3_identity_overrides(ctx)
        get_success_data(
            api.create_mold(
                mold_payload(ctx["product_model_id"], mold_code="MLD-CD-STN-2"),
                ctx["admin_headers"],
            )
        )
        lot = create_resin_lot()
        order = create_production_order(ctx, order_code="POR-CD-STN", ordered_qty=4)
        running = schedule_cycle(ctx, order, arm_index=1, **cyc)
        consumed_charge = reserve_charge(ctx, running, lot, **chg)
        scheduled = schedule_cycle(ctx, order, arm_index=2, **cyc)
        reserved_charge = reserve_charge(ctx, scheduled, lot, **chg)

        ctx["molding_cycle"] = running
        ctx["molding_cycle_id"] = running["id"]
        run_cycle_to_oven_running(ctx)

        ctx.update(
            {
                "resin_lot": lot,
                "resin_lot_id": lot["id"],
                "production_order": order,
                "production_order_id": order["id"],
                "running_cycle_id": running["id"],
                "running_mold_id": running["mold_id"],
                "scheduled_cycle_id": scheduled["id"],
                "scheduled_mold_id": scheduled["mold_id"],
                "consumed_charge_id": consumed_charge["id"],
                "reserved_charge_id": reserved_charge["id"],
            }
        )
        return ctx

    def test_mark_down_aborts_only_the_scheduled_cycle_on_that_station(
        self, api, admin_headers
    ):
        """The heat is already in the part, so the running cycle is untouched.

        PRD.md section 3.1: "Taking a station down requires a `down_reason` and
        is the head of **CASCADE-E**, whose five links run in this order: (1) the
        station's `status` moves `OPERATIONAL` to `DOWN`; (2) every cycle on the
        station in `SCHEDULED` becomes `ABORTED` with `abort_reason`
        `STATION_DOWN`; (3) their `RESERVED` charges become `RELEASED` with
        `released_reason` `STATION_DOWN`; (4) lots that regain mass move
        `DEPLETED` to `AVAILABLE`; and (5) orders in `BLOCKED_RESIN` that those
        lots now qualify for move to `READY_TO_SCHEDULE`, except that an order
        whose target site posture is `FROZEN` moves to `BLOCKED_WAREHOUSE`
        instead."

        PRD.md section 3.1: "Cycles already `OVEN_RUNNING` or `COOLING` are
        deliberately untouched — the heat is already in the part."

        PRD.md section 2.4: "`version` is an integer that starts at 1 when the
        row is created and increments by exactly 1 on every persisted mutation,
        including mutations that occur as cascade side effects of a request
        aimed at a different resource."

        Design: Corner/endpoints/ep_oven_station_mark_down_aborts_only_the_scheduled_cycle_on_that_station
        """
        ctx = self._two_cycles_on_one_station(api)

        station = validate_success(
            api.mark_down_oven_station(
                ctx["oven_station_id"], mark_down_payload("burner fault"), admin_headers
            )
        )

        assert station["status"] == "DOWN"
        assert station["version"] == 2

        running = validate_success(
            api.get_molding_cycle(ctx["running_cycle_id"], admin_headers)
        )
        assert running["status"] == "OVEN_RUNNING"
        assert running.get("abort_reason") is None

        scheduled = validate_success(
            api.get_molding_cycle(ctx["scheduled_cycle_id"], admin_headers)
        )
        assert scheduled["status"] == "ABORTED"
        assert scheduled["abort_reason"] == "STATION_DOWN"

    def test_consumed_mass_is_not_reversed_while_reserved_mass_returns(
        self, api, admin_headers
    ):
        """Only the reserved charge is released; the consumed shot stays spent.

        PRD.md section 3.1: "(3) their `RESERVED` charges become `RELEASED` with
        `released_reason` `STATION_DOWN`".

        PRD.md section 3.5: "Because consumption is irreversible, this is the
        point past which no abort returns resin."

        PRD.md section 3.2: "the rounded sum of `available_kg`, `reserved_kg` and
        `consumed_kg` equals `received_kg`".

        PRD.md section 3.1: "The remaining edges are driven by production:
        starting an oven run moves the tool `AVAILABLE` to `IN_CYCLE`".

        Design: Corner/endpoints/ep_oven_station_mark_down_aborts_only_the_scheduled_cycle_on_that_station
        """
        ctx = self._two_cycles_on_one_station(api)

        validate_success(
            api.mark_down_oven_station(
                ctx["oven_station_id"], mark_down_payload("burner fault"), admin_headers
            )
        )

        consumed = validate_success(
            api.get_resin_charge(ctx["consumed_charge_id"], admin_headers)
        )
        assert consumed["status"] == "CONSUMED"
        assert consumed.get("released_reason") is None

        released = validate_success(
            api.get_resin_charge(ctx["reserved_charge_id"], admin_headers)
        )
        assert released["status"] == "RELEASED"
        assert released["released_reason"] == "STATION_DOWN"

        lot = validate_success(api.get_resin_lot(ctx["resin_lot_id"], admin_headers))
        assert_decimal_equals(lot["available_kg"], "476.000", Q_MASS, "available_kg")
        assert_decimal_equals(lot["reserved_kg"], "0.000", Q_MASS, "reserved_kg")
        assert_decimal_equals(lot["consumed_kg"], "24.000", Q_MASS, "consumed_kg")
        assert_resin_ledger_conserved(lot)

        order = validate_success(
            api.get_production_order(ctx["production_order_id"], admin_headers)
        )
        assert order["status"] == "IN_PRODUCTION", (
            "the lot never went DEPLETED, so no blocking or unblocking edge fires"
        )
        assert order.get("blocked_reason") is None

        running_tool = validate_success(
            api.get_mold(ctx["running_mold_id"], admin_headers)
        )
        assert running_tool["status"] == "IN_CYCLE"
        idle_tool = validate_success(
            api.get_mold(ctx["scheduled_mold_id"], admin_headers)
        )
        assert idle_tool["status"] == "AVAILABLE"
        assert idle_tool["cycles_since_service"] == 0
