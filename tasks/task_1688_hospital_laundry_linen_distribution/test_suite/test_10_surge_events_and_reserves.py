"""Surge events: posture flips, effective-par cascade, reserve waterfall,
window conflicts, and the par-edit freeze (PRD 3.8, 3.2, 3.3)."""
from test_helpers import (
    LM,
    ApiErrorId,
    api_client,
    base_scenario,
    complete_run,
    create_gown_stock,
    create_par,
    create_surge,
    create_surge_event_payload,
    create_unit,
    fill_unit_to_par,
    read_facility,
    read_par,
    read_stock,
    read_surge,
    restock_totals,
    schedule_run,
    set_clock,
    update_par_level_payload,
    validate_error,
    validate_success,
)


def api_client_activate(surge_id: str):
    """Activate a surge as lm-1 (raw response for validate_success)."""
    return api_client.activate_surge_event(surge_id, LM)


def _setup_two_unit_surge_scenario():
    """U1 (CRITICAL) with pars sheet=20 and gown=30; U2 (STANDARD) with
    sheet=10; both units pre-filled to base par."""
    ctx = base_scenario()
    gown = create_gown_stock(ctx["facility"]["id"])
    unit2 = create_unit(ctx["facility"]["id"], name="4 West", unit_tier="STANDARD")
    par_gown = create_par(ctx["unit"]["id"], gown["id"], 30, "DAILY")
    par_u2 = create_par(unit2["id"], ctx["stock"]["id"], 10, "DAILY")
    fill_unit_to_par(ctx)
    # Fill U2 in a non-conflicting window of its own.
    run_u2 = schedule_run(
        unit2["id"], "2026-08-02T08:00:00Z", "2026-08-02T09:00:00Z"
    )
    complete_run(run_u2["id"], soiled_lines=[])
    ctx.update({"gown": gown, "unit2": unit2, "par_gown": par_gown,
                "par_u2": par_u2})
    return ctx


class TestSurgeActivationCascade:
    """POST activate -> Facility posture -> effective_par recompute ->
    reserve waterfall (three causal links, PRD 3.8)."""

    def _activate(self, ctx):
        surge = create_surge(
            ctx["facility"]["id"], severity="LEVEL_2", par_multiplier=1.5,
            starts_at="2026-08-03T00:00:00Z", ends_at="2026-08-10T00:00:00Z",
        )
        activated = validate_success(
            api_client_activate(surge["id"]), 200
        )
        assert activated["status"] == "ACTIVE"
        return surge

    def test_posture_and_effective_par_cascade(self, api):
        """PRD 3.8: "Activation moves the event from `DECLARED` to `ACTIVE`,
        flips the facility's `surge_posture` from `NORMAL` to `SURGE`, and
        recomputes every par level of the facility: each `effective_par`
        becomes `base_par_quantity` multiplied by the surge's
        `par_multiplier`, rounded up to the next whole piece."

        Design: Difficulty/transitive_cascade/surge_activation_cascade_depth3
        """
        ctx = _setup_two_unit_surge_scenario()
        self._activate(ctx)

        assert read_facility(ctx["facility"]["id"])["surge_posture"] == "SURGE"
        assert read_par(ctx["par"]["id"])["effective_par"] == 30, (
            "ceil(20 * 1.5) = 30"
        )
        assert read_par(ctx["par_gown"]["id"])["effective_par"] == 45, (
            "ceil(30 * 1.5) = 45"
        )
        assert read_par(ctx["par_u2"]["id"])["effective_par"] == 15, (
            "ceil(10 * 1.5) = 15"
        )

    def test_reserve_waterfall_allocation(self, api):
        """PRD 3.8: "Each stock of the facility that has `reserve_pieces`
        greater than zero is visited in order of stock creation, oldest
        first."
        PRD 3.8: "For each stock, the candidate par levels are those of the
        stock whose units belong to the facility, ranked with `CRITICAL`-tier
        units before `STANDARD`-tier units, then by deficit ratio — the
        candidate's deficit divided by its `effective_par` — in descending
        order, with ties broken by unit creation time, oldest first."
        PRD 3.8: "Each candidate in rank order, while reserve remains,
        receives the smaller of its deficit — `effective_par` minus
        `on_hand`, or zero when that difference is negative — and the
        remaining reserve; the stock's `reserve_pieces` decreases and the
        candidate's `on_hand` increases by the allocation."

        Design: Difficulty/transitive_cascade/surge_activation_cascade_depth3
        """
        ctx = _setup_two_unit_surge_scenario()
        self._activate(ctx)

        # Sheet stock (created first, reserve 10): CRITICAL unit's deficit
        # 30-20=10 is filled first and exhausts the reserve; the STANDARD
        # unit's par gets nothing.
        par = read_par(ctx["par"]["id"])
        assert par["on_hand"] == 30, f"20 + 10 reserve = 30, got {par['on_hand']}"
        par_u2 = read_par(ctx["par_u2"]["id"])
        assert par_u2["on_hand"] == 10, (
            f"reserve exhausted by the CRITICAL unit; got {par_u2['on_hand']}"
        )
        # Gown stock (reserve 20): CRITICAL unit's deficit 45-30=15.
        par_gown = read_par(ctx["par_gown"]["id"])
        assert par_gown["on_hand"] == 45, (
            f"30 + 15 reserve = 45, got {par_gown['on_hand']}"
        )
        assert read_stock(ctx["stock"]["id"])["reserve_pieces"] == 0
        assert read_stock(ctx["gown"]["id"])["reserve_pieces"] == 5


class TestCriticalTriageRestock:
    """Under surge, a CRITICAL stock halves the deficit for a STANDARD unit
    before the min() against circulation (PRD 3.3)."""

    def _setup_critical_stock_under_surge(self):
        ctx = base_scenario(
            unit_name="4 West", unit_tier="STANDARD", par_quantity=20,
            stock_overrides={
                "reorder_point_pieces": 25,
                "opening_pieces": 24,
                "opening_reserve_pieces": 0,
            },
        )
        # available 24 < reorder 25 -> CRITICAL posture from creation.
        assert read_stock(ctx["stock"]["id"])["posture"] == "CRITICAL"
        surge = create_surge(
            ctx["facility"]["id"], severity="LEVEL_1", par_multiplier=1.5,
            starts_at="2026-08-01T00:00:00Z", ends_at="2026-08-10T00:00:00Z",
        )
        validate_success(api_client_activate(surge["id"]), 200)
        ctx["surge"] = surge
        return ctx

    def test_triage_halves_deficit_for_standard_unit(self, api):
        """PRD 3.3: "Triage applies under scarcity: when the stock's `posture`
        is `CRITICAL` and the unit's `unit_tier` is `STANDARD`, the deficit is
        halved and rounded down before delivery is computed."
        PRD 3.3: "The run records what was actually delivered as
        `restock_lines` (each a `stock_id` with its delivered `pieces`), and
        `shortage_flag` is set to true when any restock line delivered fewer
        pieces than its deficit."

        Design: Difficulty/combinatorial_formula/restock_quantity_nested_min_with_surge_and_critical_triage
        """
        ctx = self._setup_critical_stock_under_surge()
        set_clock("2026-08-03T08:00:00Z")
        run = schedule_run(
            ctx["unit"]["id"], "2026-08-03T08:00:00Z", "2026-08-03T09:00:00Z"
        )
        completed = complete_run(run["id"], soiled_lines=[])

        # effective_par = ceil(20*1.5) = 30; deficit 30 halved to 15;
        # min(15, in_circulation 24) = 15.
        totals = restock_totals(completed["restock_lines"])
        assert totals == {ctx["stock"]["id"]: 15}, (
            f"CRITICAL stock + STANDARD unit must halve the 30 deficit to 15, "
            f"got {totals}"
        )
        assert completed["shortage_flag"] is False, (
            "delivered 15 equals the post-triage deficit of 15"
        )

    def test_triage_delivery_mutates_counters(self, api):
        """PRD 3.3: "The delivered quantity is the smaller of the deficit and
        the stock's `in_circulation`."
        PRD 3.3: "The delivered pieces are added to the unit's `on_hand` and
        subtracted from the stock's `in_circulation`, while the soiled pieces
        are added to the stock's `in_wash`."

        Design: Difficulty/combinatorial_formula/restock_quantity_nested_min_with_surge_and_critical_triage
        """
        ctx = self._setup_critical_stock_under_surge()
        set_clock("2026-08-03T08:00:00Z")
        run = schedule_run(
            ctx["unit"]["id"], "2026-08-03T08:00:00Z", "2026-08-03T09:00:00Z"
        )
        complete_run(run["id"], soiled_lines=[])

        par = read_par(ctx["par"]["id"])
        assert par["on_hand"] == 15
        assert par["effective_par"] == 30
        assert read_stock(ctx["stock"]["id"])["in_circulation"] == 9, (
            f"24 - 15 delivered = 9, got {read_stock(ctx['stock']['id'])['in_circulation']}"
        )


class TestSecondActivationBlocked:
    """A facility already in SURGE posture refuses a second activation."""

    def test_activate_during_surge_rejected(self, api):
        """PRD 3.8: "Activation is the consequential step: it requires the
        facility's `surge_posture` to be `NORMAL`, and an activation attempted
        while the facility is already in surge is rejected with
        `ERR_FACILITY_IN_SURGE`."

        Design: Difficulty/cross_entity_state_dependency/surge_activate_blocked_by_facility_posture
        """
        ctx = base_scenario()
        sg1 = create_surge(ctx["facility"]["id"], par_multiplier=1.5)
        validate_success(api.activate_surge_event(sg1["id"], LM), 200)
        sg2 = create_surge(
            ctx["facility"]["id"], severity="LEVEL_2", par_multiplier=2.0,
            starts_at="2026-08-11T00:00:00Z", ends_at="2026-08-15T00:00:00Z",
        )

        res = api.activate_surge_event(sg2["id"], LM)
        validate_error(res, ApiErrorId.ERR_FACILITY_IN_SURGE)
        assert read_surge(sg2["id"])["status"] == "DECLARED"

    def test_activate_succeeds_after_first_surge_closes(self, api):
        """PRD 3.8: "The facility's `surge_posture` returns from `SURGE` to
        `NORMAL` when no other `ACTIVE` surge exists for the facility, and
        every par level's `effective_par` reverts to `base_par_quantity`."
        PRD 3.8: "Activation is the consequential step: it requires the
        facility's `surge_posture` to be `NORMAL`, and an activation attempted
        while the facility is already in surge is rejected with
        `ERR_FACILITY_IN_SURGE`."

        Design: Difficulty/cross_entity_state_dependency/surge_activate_blocked_by_facility_posture
        """
        ctx = base_scenario()
        sg1 = create_surge(ctx["facility"]["id"], par_multiplier=1.5)
        validate_success(api.activate_surge_event(sg1["id"], LM), 200)
        sg2 = create_surge(
            ctx["facility"]["id"], severity="LEVEL_2", par_multiplier=2.0,
            starts_at="2026-08-11T00:00:00Z", ends_at="2026-08-15T00:00:00Z",
        )
        validate_success(api.close_surge_event(sg1["id"], LM), 200)
        assert read_facility(ctx["facility"]["id"])["surge_posture"] == "NORMAL"

        activated = validate_success(api.activate_surge_event(sg2["id"], LM), 200)
        assert activated["status"] == "ACTIVE"
        assert read_facility(ctx["facility"]["id"])["surge_posture"] == "SURGE"


class TestSurgeWindowConflict:
    """Surge windows are closed intervals: shared endpoints still overlap."""

    def test_shared_endpoint_conflicts(self, api, linen_manager_headers):
        """PRD 3.8: "The window end must be after its start
        (`ERR_INVALID_WINDOW`), and because surge windows are closed
        intervals, any overlap with another `DECLARED` or `ACTIVE` surge of
        the same facility — including merely sharing an endpoint — is rejected
        with `ERR_SURGE_WINDOW_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/surge_closed_interval_adjacency_conflict
        """
        ctx = base_scenario()
        create_surge(ctx["facility"]["id"])  # [08-01 .. 08-10] DECLARED

        res = api.create_surge_event(
            create_surge_event_payload(
                ctx["facility"]["id"], severity="LEVEL_2", par_multiplier=2.0,
                starts_at="2026-08-10T00:00:00Z",
                ends_at="2026-08-15T00:00:00Z",
            ),
            linen_manager_headers,
        )
        validate_error(res, ApiErrorId.ERR_SURGE_WINDOW_CONFLICT)

    def test_disjoint_window_accepted(self, api, linen_manager_headers):
        """PRD 3.8: "The window end must be after its start
        (`ERR_INVALID_WINDOW`), and because surge windows are closed
        intervals, any overlap with another `DECLARED` or `ACTIVE` surge of
        the same facility — including merely sharing an endpoint — is rejected
        with `ERR_SURGE_WINDOW_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/surge_closed_interval_adjacency_conflict
        """
        ctx = base_scenario()
        create_surge(ctx["facility"]["id"])  # [08-01 .. 08-10] DECLARED

        created = validate_success(
            api.create_surge_event(
                create_surge_event_payload(
                    ctx["facility"]["id"], severity="LEVEL_2",
                    par_multiplier=2.0,
                    starts_at="2026-08-11T00:00:00Z",
                    ends_at="2026-08-15T00:00:00Z",
                ),
                linen_manager_headers,
            ),
            201,
        )
        assert created["status"] == "DECLARED"


def test_close_closed_surge_returns_already_terminal(api):
    """PRD 3.8: "Closing an `ACTIVE` surge moves it to `CLOSED` (terminal)."
    PRD 2.9: "Seventh, state guards — the resource must be in a valid
    from-state for the requested transition (`ERR_INVALID_STATE`, or
    `ERR_ALREADY_TERMINAL` when the resource is already in a terminal state),
    unit-clerk ownership (`ERR_UNIT_OWNERSHIP`), surge-posture blocks
    (`ERR_FACILITY_IN_SURGE`), and invoice-creation manifest status."

    Design: Corner/state_machines/close_closed_surge_returns_already_terminal
    """
    ctx = base_scenario()
    surge = create_surge(ctx["facility"]["id"])
    validate_success(api.activate_surge_event(surge["id"], LM), 200)
    validate_success(api.close_surge_event(surge["id"], LM), 200)

    res = api.close_surge_event(surge["id"], LM)
    validate_error(res, ApiErrorId.ERR_ALREADY_TERMINAL)
    assert read_facility(ctx["facility"]["id"])["surge_posture"] == "NORMAL"


def test_put_par_level_during_surge_rejected(api, linen_manager_headers):
    """PRD 3.2: "A `LinenManager` may update a par level's
    `base_par_quantity`, its `cart_cycle`, or both, but only while the
    facility is not in surge — a par-level edit attempted while the facility's
    `surge_posture` is `SURGE` is rejected with `ERR_FACILITY_IN_SURGE`."

    Design: Corner/validations/put_par_level_during_surge_rejected
    """
    ctx = base_scenario()
    surge = create_surge(ctx["facility"]["id"])
    validate_success(api.activate_surge_event(surge["id"], LM), 200)
    # Re-read so OCC passes and the surge gate is the check that fires.
    fresh_version = read_par(ctx["par"]["id"])["version"]

    res = api.update_par_level(
        ctx["par"]["id"],
        update_par_level_payload(fresh_version, base_par_quantity=25),
        linen_manager_headers,
    )
    validate_error(res, ApiErrorId.ERR_FACILITY_IN_SURGE)
