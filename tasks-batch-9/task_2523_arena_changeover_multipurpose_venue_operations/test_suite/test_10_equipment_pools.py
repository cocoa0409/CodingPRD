"""Equipment pools: the derived availability figure, the conserved unit total
across issue, damaged return and servicing, and the pool-status gate on issue."""
from test_helpers import (
    ApiErrorId,
    assert_equipment_pool_conserved,
    create_equipment_pool,
    issue_equipment,
    maintenance,
    read_asset,
    read_issue,
    return_equipment,
    setup_ice_to_concert_turnaround,
    validate_error,
    validate_success,
    TEST_USERS,
)

SUPERVISOR = TEST_USERS["changeover_supervisor_headers"]


def _turnaround_with_a_ten_unit_panel_pool():
    """An open turnaround plus a ten-set floor panel pool at its default
    servicing interval, with nothing yet out on the floor."""
    return setup_ice_to_concert_turnaround(
        crew_headcount=40, confirm_incoming=True, floor_panel_units_total=10
    )


def _turnaround_with_a_two_cycle_service_interval():
    """The same turnaround, but the pool needs servicing after two cycles."""
    arena = setup_ice_to_concert_turnaround(
        crew_headcount=40, confirm_incoming=True
    )
    arena["floor_pool"] = create_equipment_pool(
        arena["venue_id"], "FLOOR_PANEL_SET", 10, service_interval_cycles=2
    )
    return arena


class TestIssueDependsOnPoolStatusRatherThanAvailability:
    def test_a_pool_under_maintenance_refuses_the_issue_though_every_unit_is_free(
        self, api
    ):
        """PRD §3.9: "Four conditions guard it, in this order: the order's `status` must be
        neither `SIGNED_OFF` nor `ABANDONED`, otherwise `ERR_INVALID_ORDER_STATE`; the pool's
        `status` must be `IN_SERVICE`, otherwise `ERR_ASSET_OUT_OF_SERVICE`; `units_issued` must
        not exceed the pool's `units_available`, evaluated inclusively so that taking the last
        available unit succeeds, otherwise `ERR_EQUIPMENT_UNITS_UNAVAILABLE`; and the pool's
        arena must be the same arena as the order's, otherwise `ERR_VENUE_SCOPE_MISMATCH`."
        PRD §3.9: "A `START` takes the pool `IN_SERVICE → OUT_OF_SERVICE`, and it is refused
        with `ERR_INVALID_ISSUE_STATE` when the pool still has any equipment issue in `ISSUED`
        status — units cannot be serviced while they are out on a floor — and likewise when the
        pool is already `OUT_OF_SERVICE`."
        PRD §3.9: "Starting maintenance moves no units, so `units_available` is recomputed to
        the same figure it already held."

        Design: Difficulty/cross_entity_state_dependency/equipment_issue_depends_on_the_pool_asset_being_in_service_not_on_unit_availability
        """
        arena = _turnaround_with_a_ten_unit_panel_pool()
        assert arena["floor_pool"]["status"] == "IN_SERVICE"
        assert arena["floor_pool"]["units_available"] == 10

        serviced = maintenance(arena["floor_pool"]["id"], "START")
        assert serviced["status"] == "OUT_OF_SERVICE"
        assert serviced["units_available"] == 10, (
            "starting maintenance withdraws no units from the availability figure"
        )

        response = api.create_equipment_issue(
            {
                "asset_id": arena["floor_pool"]["id"],
                "changeover_order_id": arena["order"]["id"],
                "units_issued": 3,
            },
            SUPERVISOR,
        )
        validate_error(response, ApiErrorId.ERR_ASSET_OUT_OF_SERVICE.value, 409)

        assert read_asset(arena["floor_pool"]["id"])["units_available"] == 10

    def test_completing_maintenance_restores_the_pool_and_admits_the_same_issue(
        self, api
    ):
        """PRD §3.9: "A `COMPLETE` takes the pool `OUT_OF_SERVICE → IN_SERVICE` and is refused
        with `ERR_INVALID_ISSUE_STATE` when the pool is already `IN_SERVICE`."
        PRD §3.9: "The issue is created `ISSUED` — the only other state is `RETURNED`, which is
        terminal — and the pool's `units_available` falls by `units_issued`."
        PRD §3.9: "Availability is always derived, never written directly: `units_available` is
        `units_total` less `units_out_of_service` less the sum of `units_issued` across every
        equipment issue on that pool whose `status` is `ISSUED`."
        PRD §3.9: "`service_due` is likewise derived, and it is evaluated inclusively: the flag
        is true as soon as `cycles_since_service` reaches `service_interval_cycles`, so the
        interval-th cycle already flags the pool rather than the one after it."

        Design: Difficulty/cross_entity_state_dependency/equipment_issue_depends_on_the_pool_asset_being_in_service_not_on_unit_availability
        """
        arena = _turnaround_with_a_ten_unit_panel_pool()
        maintenance(arena["floor_pool"]["id"], "START")
        response = api.create_equipment_issue(
            {
                "asset_id": arena["floor_pool"]["id"],
                "changeover_order_id": arena["order"]["id"],
                "units_issued": 3,
            },
            SUPERVISOR,
        )
        validate_error(response, ApiErrorId.ERR_ASSET_OUT_OF_SERVICE.value, 409)

        restored = maintenance(arena["floor_pool"]["id"], "COMPLETE")
        assert restored["status"] == "IN_SERVICE"

        issue = validate_success(
            api.create_equipment_issue(
                {
                    "asset_id": arena["floor_pool"]["id"],
                    "changeover_order_id": arena["order"]["id"],
                    "units_issued": 3,
                },
                SUPERVISOR,
            ),
            201,
        )
        assert issue["status"] == "ISSUED"
        assert issue["units_issued"] == 3
        assert issue["returned_at_utc"] is None

        asset = read_asset(arena["floor_pool"]["id"])
        assert asset["status"] == "IN_SERVICE"
        assert asset["units_available"] == 7
        assert asset["units_out_of_service"] == 0
        assert asset["cycles_since_service"] == 0
        assert asset["service_due"] is False
        assert_equipment_pool_conserved(asset, 3)


class TestPoolConservesItsUnitTotal:
    def test_a_damaged_return_withdraws_the_damage_and_conserves_the_total(self, api):
        """PRD §3.9: "The invariant that must hold after every mutation is that available units
        plus outstanding issued units plus out-of-service units equal `units_total` exactly; the
        value is a whole number of units and can never go negative, because the availability
        check on issue keeps it non-negative."
        PRD §3.9: "The pool's `units_out_of_service` rises by `damaged_units`, and its
        `units_available` rises by the undamaged remainder — `units_issued` less
        `damaged_units` — so that damaged stock is withdrawn from circulation without disturbing
        the conserved `units_total`."
        PRD §3.9: "On acceptance the issue moves `ISSUED → RETURNED`, `returned_at_utc` is
        stamped with the logical clock instant, and `return_reason` is recorded as
        `OPERATOR_RETURN`."
        PRD §3.9: "The pool's `cycles_since_service` rises by one and `service_due` is
        re-evaluated against `service_interval_cycles`."

        Design: Difficulty/compensating_invariant/equipment_pool_conserves_units_total_across_issue_damaged_return_and_maintenance_reset
        """
        arena = _turnaround_with_a_two_cycle_service_interval()
        pool_id = arena["floor_pool"]["id"]
        assert arena["floor_pool"]["service_interval_cycles"] == 2

        first_issue = issue_equipment(pool_id, arena["order"]["id"], 6)
        after_issue = read_asset(pool_id)
        assert after_issue["units_available"] == 4
        assert_equipment_pool_conserved(after_issue, 6)

        returned = return_equipment(first_issue["id"], damaged_units=2)
        assert returned["status"] == "RETURNED"
        assert returned["damaged_units"] == 2
        assert returned["return_reason"] == "OPERATOR_RETURN"
        assert read_issue(first_issue["id"])["returned_at_utc"] is not None

        asset = read_asset(pool_id)
        assert asset["units_available"] == 8, "six back less two withdrawn as damaged"
        assert asset["units_out_of_service"] == 2
        assert asset["units_total"] == 10
        assert asset["cycles_since_service"] == 1
        assert asset["service_due"] is False
        assert_equipment_pool_conserved(asset, 0)

    def test_servicing_repairs_the_damaged_stock_and_resets_the_cycle_ledger(self, api):
        """PRD §3.9: "`service_due` is likewise derived, and it is evaluated inclusively: the
        flag is true as soon as `cycles_since_service` reaches `service_interval_cycles`, so the
        interval-th cycle already flags the pool rather than the one after it."
        PRD §3.9: "Completing maintenance repairs damaged stock back into the pool:
        `units_out_of_service` is reset to 0, `cycles_since_service` is reset to 0, `service_due`
        becomes false, and `units_available` is recomputed as `units_total` less whatever units
        are still outstanding on issue."
        PRD §3.9: "Starting maintenance moves no units, so `units_available` is recomputed to
        the same figure it already held."
        PRD §3.9: "Returned issues contribute nothing."

        Design: Difficulty/compensating_invariant/equipment_pool_conserves_units_total_across_issue_damaged_return_and_maintenance_reset
        """
        arena = _turnaround_with_a_two_cycle_service_interval()
        pool_id = arena["floor_pool"]["id"]

        first_issue = issue_equipment(pool_id, arena["order"]["id"], 6)
        return_equipment(first_issue["id"], damaged_units=2)

        second_issue = issue_equipment(pool_id, arena["order"]["id"], 3)
        assert read_asset(pool_id)["units_available"] == 5
        second_returned = return_equipment(second_issue["id"], damaged_units=0)
        assert second_returned["damaged_units"] == 0
        assert second_returned["return_reason"] == "OPERATOR_RETURN"

        due = read_asset(pool_id)
        assert due["cycles_since_service"] == 2
        assert due["service_due"] is True, (
            "the interval-th cycle already flags the pool"
        )
        assert due["units_available"] == 8
        assert_equipment_pool_conserved(due, 0)

        started = maintenance(pool_id, "START")
        assert started["status"] == "OUT_OF_SERVICE"
        assert started["units_available"] == 8
        assert started["units_out_of_service"] == 2

        completed = maintenance(pool_id, "COMPLETE")
        assert completed["status"] == "IN_SERVICE"
        assert completed["units_available"] == 10
        assert completed["units_out_of_service"] == 0
        assert completed["cycles_since_service"] == 0
        assert completed["service_due"] is False
        assert completed["units_total"] == 10
        assert_equipment_pool_conserved(completed, 0)
