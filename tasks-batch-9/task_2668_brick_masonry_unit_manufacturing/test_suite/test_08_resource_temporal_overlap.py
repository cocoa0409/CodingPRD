"""
Two temporal reservations with deliberately opposite conventions: the kiln window is
closed and inflated by a cooldown buffer, while the kiln car's occupancy is
half-open and unbuffered.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories as F
from test_helpers import fixtures as fx
from test_helpers.api_errors import ERR_KILN_CAR_OCCUPIED, ERR_KILN_WINDOW_CONFLICT
from test_helpers.test_users import PLANT_ADMIN


class TestKilnWindowClosedIntervalWithCooldownBuffer:
    """
    Section 3.4: "the scheduling check inflates windows by the kiln's own
    cooldown_buffer_hours on the trailing side and treats the result as a closed
    interval running from start_at to end_at plus the buffer ... Touching endpoints
    collide."
    """

    def _kiln_with_one_scheduled_run(self, api):
        env = fx.build_plant_with_assets(api, clock=None)
        env["kiln_run"] = fx.create_kiln_run(
            api,
            env["plant"]["id"],
            env["kiln"]["id"],
            env["formulation"]["id"],
            start_at="2026-08-05T00:00:00Z",
            end_at="2026-08-07T00:00:00Z",
        )
        assert env["kiln_run"]["status"] == "SCHEDULED"
        assert env["kiln"]["cooldown_buffer_hours"] == 6.0
        return env

    def test_touching_inflated_endpoints_collide_on_both_sides(self, api, clock):
        """
        A window ending at the existing start, and one starting at its inflated end,
        both collide; one hour later is accepted.

        Section 3.4: "The new run's inflated interval must not intersect the
        identically inflated interval of any existing kiln run on that same kiln
        whose status is anything other than ABORTED. Touching endpoints collide: if
        one run's inflated interval ends at exactly the instant another's begins,
        that is a conflict, and the request is rejected with
        ERR_KILN_WINDOW_CONFLICT."

        Design: Difficulty/resource_temporal_overlap/kiln_firing_window_closed_interval_with_cooldown_buffer_collides_on_touch
        """
        env = self._kiln_with_one_scheduled_run(api)
        operator = env["operator"]
        kiln_id = env["kiln"]["id"]
        body_id = env["formulation"]["id"]

        # KR0's own end plus its 6.0 h buffer is exactly 2026-08-05T00:00:00Z.
        validate_error(
            api.create_kiln_run(
                F.kiln_run_payload(
                    kiln_id,
                    body_id,
                    start_at="2026-08-03T00:00:00Z",
                    end_at="2026-08-04T18:00:00Z",
                ),
                operator,
            ),
            ERR_KILN_WINDOW_CONFLICT,
            409,
        )

        # KR2 starts exactly at the existing run's inflated end.
        validate_error(
            api.create_kiln_run(
                F.kiln_run_payload(
                    kiln_id,
                    body_id,
                    start_at="2026-08-07T06:00:00Z",
                    end_at="2026-08-09T00:00:00Z",
                ),
                operator,
            ),
            ERR_KILN_WINDOW_CONFLICT,
            409,
        )

        accepted = validate_success(
            api.create_kiln_run(
                F.kiln_run_payload(
                    kiln_id,
                    body_id,
                    start_at="2026-08-07T07:00:00Z",
                    end_at="2026-08-09T00:00:00Z",
                ),
                operator,
            ),
            201,
        )
        assert accepted["status"] == "SCHEDULED"
        assert accepted["start_at"] == "2026-08-07T07:00:00Z"

        persisted = validate_success(
            api.list_kiln_runs(operator, params={"kiln_id": kiln_id, "limit": 100})
        )
        assert len(persisted) == 2
        assert {r["id"] for r in persisted} == {env["kiln_run"]["id"], accepted["id"]}

    def test_the_collision_check_is_scoped_to_one_kiln(self, api, clock):
        """
        A window inside the buffered interval collides, but the same window on a
        second kiln is accepted.

        Section 3.4 scopes the comparison to "any existing kiln run on that same
        kiln", so a second tunnel kiln at the same plant may fire the identical
        window. The buffered tail is genuinely occupied: a run wholly inside
        2026-08-07T00:00 to 2026-08-07T06:00 has no raw overlap at all and still
        collides.

        Design: Difficulty/resource_temporal_overlap/kiln_firing_window_closed_interval_with_cooldown_buffer_collides_on_touch
        """
        env = self._kiln_with_one_scheduled_run(api)
        operator = env["operator"]
        body_id = env["formulation"]["id"]

        validate_error(
            api.create_kiln_run(
                F.kiln_run_payload(
                    env["kiln"]["id"],
                    body_id,
                    start_at="2026-08-07T01:00:00Z",
                    end_at="2026-08-07T05:00:00Z",
                ),
                operator,
            ),
            ERR_KILN_WINDOW_CONFLICT,
            409,
        )

        second_kiln = fx.create_kiln(api, env["plant"]["id"])
        twin = validate_success(
            api.create_kiln_run(
                F.kiln_run_payload(
                    second_kiln["id"],
                    body_id,
                    start_at="2026-08-05T00:00:00Z",
                    end_at="2026-08-07T00:00:00Z",
                ),
                operator,
            ),
            201,
        )
        assert twin["status"] == "SCHEDULED"
        assert twin["kiln_id"] == second_kiln["id"]

        on_first = validate_success(
            api.list_kiln_runs(
                operator, params={"kiln_id": env["kiln"]["id"], "limit": 100}
            )
        )
        assert [r["id"] for r in on_first] == [env["kiln_run"]["id"]]


class TestKilnCarOccupancyHalfOpenInterval:
    """
    Section 3.4: "the car's occupancy is compared as a half-open interval running
    from start_at up to but not including end_at, with zero buffer ... Exact
    adjacency is therefore allowed ... which is the opposite convention from the
    kiln window check."
    """

    def _car_freed_after_one_firing(self, api):
        """One car, three kilns, and a first firing already graded on kiln one."""
        env = fx.build_plant_with_assets(api, clock=None)
        plant_id = env["plant"]["id"]
        env["kiln_two"] = fx.create_kiln(api, plant_id)
        env["kiln_three"] = fx.create_kiln(api, plant_id)

        first_run = fx.build_set_production_run(
            api, env["plant"], env["formulation"]["id"], env["kiln_car"]["id"]
        )
        first_firing = fx.create_kiln_run(
            api,
            plant_id,
            env["kiln"]["id"],
            env["formulation"]["id"],
            start_at="2026-08-05T00:00:00Z",
            end_at="2026-08-07T00:00:00Z",
        )
        first_firing = fx.load_kiln_run(api, plant_id, first_firing, first_run["id"], 3)
        assert first_firing["loaded_units"] == 9600
        fx.start_kiln_run(api, plant_id, first_firing["id"])
        graded = fx.grade_kiln_run(api, plant_id, first_firing["id"])
        assert graded["status"] == "GRADED"

        cars = validate_success(api.list_kiln_cars(plant_id, PLANT_ADMIN))
        assert cars[0]["status"] == "IDLE"
        assert cars[0]["current_production_run_id"] is None

        env["first_firing"] = graded
        env["second_run"] = fx.build_set_production_run(
            api,
            env["plant"],
            env["formulation"]["id"],
            env["kiln_car"]["id"],
            green_units_set=5000,
            green_loss_units=200,
        )
        assert env["second_run"]["status"] == "SET"
        assert env["second_run"]["net_green_units"] == 4800
        return env

    def test_a_straddling_window_is_refused_but_exact_adjacency_loads(self, api, clock):
        """
        The car cannot join a firing overlapping its graded one, but may join the
        firing that begins at the instant that one ended.

        Section 3.4: "A kiln car cannot be in two firings at once", compared against
        "every other non-ABORTED kiln run the car is already loaded into", and "a car
        whose previous firing ends at precisely the instant the next one begins may
        be loaded". An actual overlap "is rejected with ERR_KILN_CAR_OCCUPIED".

        Design: Difficulty/resource_temporal_overlap/kiln_car_occupancy_half_open_interval_allows_exact_adjacency
        """
        env = self._car_freed_after_one_firing(api)
        plant_id = env["plant"]["id"]
        operator = env["operator"]

        straddling = fx.create_kiln_run(
            api,
            plant_id,
            env["kiln_three"]["id"],
            env["formulation"]["id"],
            start_at="2026-08-06T00:00:00Z",
            end_at="2026-08-08T00:00:00Z",
        )
        adjacent = fx.create_kiln_run(
            api,
            plant_id,
            env["kiln_two"]["id"],
            env["formulation"]["id"],
            start_at="2026-08-07T00:00:00Z",
            end_at="2026-08-09T00:00:00Z",
        )

        validate_error(
            api.load_kiln_run(
                straddling["id"],
                F.kiln_load_payload(
                    env["second_run"]["id"], 2, straddling["version"]
                ),
                operator,
            ),
            ERR_KILN_CAR_OCCUPIED,
            409,
        )

        loaded = validate_success(
            api.load_kiln_run(
                adjacent["id"],
                F.kiln_load_payload(env["second_run"]["id"], 2, adjacent["version"]),
                operator,
            )
        )
        assert loaded["status"] == "SCHEDULED"
        assert loaded["loaded_units"] == 4800

        run_after = validate_success(
            api.get_production_run(env["second_run"]["id"], operator)
        )
        assert run_after["status"] == "LOADED"
        assert run_after["kiln_run_id"] == adjacent["id"]
        assert run_after["kiln_position"] == 2

        refused = validate_success(api.get_kiln_run(straddling["id"], operator))
        assert refused["loaded_units"] == 0
        assert refused["version"] == straddling["version"]

    def test_adjacency_is_allowed_on_the_earlier_side_as_well(self, api, clock):
        """
        A firing that ends exactly when the car's graded firing began is loadable.

        Section 3.4 compares half-open intervals from "start_at up to but not
        including end_at", so [2026-08-03, 2026-08-05) and [2026-08-05, 2026-08-07)
        do not intersect in either direction and the car may be loaded into the
        earlier one. The kiln window rule would have called the same instant a
        collision - the two conventions are deliberately opposite.

        Design: Difficulty/resource_temporal_overlap/kiln_car_occupancy_half_open_interval_allows_exact_adjacency
        """
        env = self._car_freed_after_one_firing(api)
        plant_id = env["plant"]["id"]
        operator = env["operator"]

        earlier = fx.create_kiln_run(
            api,
            plant_id,
            env["kiln_two"]["id"],
            env["formulation"]["id"],
            start_at="2026-08-03T00:00:00Z",
            end_at="2026-08-05T00:00:00Z",
        )
        loaded = validate_success(
            api.load_kiln_run(
                earlier["id"],
                F.kiln_load_payload(env["second_run"]["id"], 1, earlier["version"]),
                operator,
            )
        )
        assert loaded["loaded_units"] == 4800
        assert loaded["status"] == "SCHEDULED"

        cars = validate_success(api.list_kiln_cars(plant_id, PLANT_ADMIN))
        assert cars[0]["status"] == "IN_KILN"
        assert cars[0]["current_production_run_id"] == env["second_run"]["id"]
