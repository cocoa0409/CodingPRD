"""Two interval collision rules with deliberately opposite endpoint semantics.

Diet coverage windows are half-open, so windows that merely touch may coexist on
the same inmate. Blast chiller occupancy is closed at both ends, so a batch
scheduled at the exact instant another is released collides with it.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import ApiClient, ApiErrorId, assertions, factories, fixtures
from test_helpers import test_users as users


# ---------------------------------------------------------------------------
# Diet coverage: half-open, touching endpoints allowed
# ---------------------------------------------------------------------------


def _inmate_with_an_active_kosher_order(api: ApiClient) -> dict:
    """One inmate carrying a verified religious accommodation running from the first
    of August to the tenth of August exclusive."""
    ctx = fixtures.active_contract_with_facility(
        api,
        contract_overrides={"contract_code": "CFS-2515-RT1"},
        facility_overrides={
            "facility_code": "FAC-RT1",
            "sharps_authorized_count": 12,
        },
    )
    inmate = fixtures.create_inmate(
        api, ctx["facility"]["id"], religious_affiliation="JEWISH"
    )
    incumbent = validate_success(
        api.create_diet_order(
            factories.religious_diet_order_payload(
                inmate["id"],
                inmate["version"],
                diet_code="KOSHER",
                effective_from="2026-08-01T00:00:00Z",
                effective_to="2026-08-10T00:00:00Z",
            ),
            users.DIETITIAN,
        ),
        201,
    )
    incumbent = validate_success(api.verify_diet_order(incumbent["id"], users.CHAPLAIN))
    ctx["inmate"] = validate_success(api.get_inmate(inmate["id"], users.OFFICER))
    ctx["incumbent"] = incumbent
    return ctx


def test_an_adjacent_order_starting_at_the_incumbents_end_instant_is_accepted(
    api: ApiClient,
) -> None:
    """The incumbent's coverage stops before its own `effective_to`, so a successor
    starting exactly there is adjacent rather than overlapping.

    The PRD states: "A diet order's coverage is the **half-open** interval that
    starts at `effective_from` inclusive and ends at `effective_to` exclusive. Two
    orders collide when the new order's `effective_from` falls strictly before the
    existing order's `effective_to` and the existing order's `effective_from` falls
    strictly before the new order's `effective_to`." It then says: "an incumbent
    running from the first of August to the tenth of August exclusive, and a new order
    running from the tenth of August to the twentieth, are adjacent rather than
    overlapping, and both may exist". A religious accommodation "is good for 180
    days".

    Design: Difficulty/resource_temporal_overlap/diet_order_half_open_windows_allow_touching_endpoints_on_same_inmate
    """
    ctx = _inmate_with_an_active_kosher_order(api)

    incumbent = ctx["incumbent"]
    assert incumbent["status"] == "ACTIVE"
    assert incumbent["verified_by_user_id"] == users.user_id_of(users.CHAPLAIN)
    assertions.assert_instant(incumbent["verified_at"], "2026-08-01T00:00:00Z")
    assertions.assert_instant(
        incumbent["verification_expires_at"], "2027-01-28T00:00:00Z"
    )

    successor = validate_success(
        api.create_diet_order(
            factories.religious_diet_order_payload(
                ctx["inmate"]["id"],
                ctx["inmate"]["version"],
                diet_code="KOSHER",
                effective_from="2026-08-10T00:00:00Z",
                effective_to="2026-08-20T00:00:00Z",
            ),
            users.DIETITIAN,
        ),
        201,
    )
    assertions.assert_diet_order(successor)
    assert successor["status"] == "PENDING_VERIFICATION"
    assert successor["supersedes_diet_order_id"] is None
    assert successor["reverification_count"] == 0

    orders, meta = validate_paginated(
        api.list_diet_orders(users.DIETITIAN, {"inmate_id": ctx["inmate"]["id"]})
    )
    assert meta["total_count"] == 2
    assert {order["status"] for order in orders} == {"ACTIVE", "PENDING_VERIFICATION"}

    inmate = validate_success(api.get_inmate(ctx["inmate"]["id"], users.OFFICER))
    assert inmate["active_diet_order_count"] == 1
    facility = fixtures.read_facility(api, ctx["facility"]["id"])
    assert facility["active_special_diet_count"] == 1


def test_backing_the_successor_up_by_one_second_creates_a_window_conflict(
    api: ApiClient,
) -> None:
    """One second earlier and the new interval reaches strictly inside the
    incumbent's, which is a collision.

    The PRD states: "backing the new order up by a single second creates a conflict",
    and that when a candidate remains "the create is rejected with
    `ERR_DIET_ORDER_WINDOW_CONFLICT`". The candidate set covers "only orders for the
    same inmate, only orders of the same `order_type`, and only orders whose `status`
    is `PENDING_VERIFICATION`, `ACTIVE` or `SUSPENDED`". Because the ladder aborts
    "with no partial writes", the rejected create does not increment the inmate's
    `version`, which a successful create would have done.

    Design: Difficulty/resource_temporal_overlap/diet_order_half_open_windows_allow_touching_endpoints_on_same_inmate
    """
    ctx = _inmate_with_an_active_kosher_order(api)

    validate_success(
        api.create_diet_order(
            factories.religious_diet_order_payload(
                ctx["inmate"]["id"],
                ctx["inmate"]["version"],
                diet_code="KOSHER",
                effective_from="2026-08-10T00:00:00Z",
                effective_to="2026-08-20T00:00:00Z",
            ),
            users.DIETITIAN,
        ),
        201,
    )
    before = validate_success(api.get_inmate(ctx["inmate"]["id"], users.OFFICER))

    validate_error(
        api.create_diet_order(
            factories.religious_diet_order_payload(
                before["id"],
                before["version"],
                diet_code="KOSHER",
                effective_from="2026-08-09T23:59:59Z",
                effective_to="2026-08-20T00:00:00Z",
            ),
            users.DIETITIAN,
        ),
        ApiErrorId.ERR_DIET_ORDER_WINDOW_CONFLICT.value,
        409,
    )

    after = validate_success(api.get_inmate(ctx["inmate"]["id"], users.OFFICER))
    assertions.assert_no_version_change(before, after)
    assert after["active_diet_order_count"] == 1

    _, meta = validate_paginated(
        api.list_diet_orders(users.DIETITIAN, {"inmate_id": before["id"]})
    )
    assert meta["total_count"] == 2, "the rejected create must leave no order behind"


# ---------------------------------------------------------------------------
# Blast chiller occupancy: closed, touching endpoints collide
# ---------------------------------------------------------------------------


def _chiller_holding_two_live_batches(api: ApiClient) -> dict:
    """A facility whose chiller takes two concurrent batches, both already
    scheduled: one released at 12:30Z and one released at 14:30Z."""
    ctx = fixtures.locked_forecast(
        api,
        contract_overrides={"contract_code": "CFS-2515-RT2"},
        facility_overrides={
            "facility_code": "FAC-RT2",
            "sharps_authorized_count": 12,
            "blast_chiller_capacity": 2,
        },
    )
    assert ctx["forecast"]["total_forecast_trays"] == 22

    ctx = fixtures.planned_batch(
        api,
        ctx,
        recipe_component="Turkey Casserole",
        planned_trays=5,
        scheduled_cook_start_at="2026-08-01T06:00:00Z",
    )
    ctx["batch_a"] = ctx.pop("batch")
    ctx = fixtures.planned_batch(
        api,
        ctx,
        recipe_component="Bean Rice Bowl",
        planned_trays=5,
        scheduled_cook_start_at="2026-08-01T08:00:00Z",
    )
    ctx["batch_b"] = ctx.pop("batch")
    return ctx


def _schedule_at(api: ApiClient, ctx: dict, instant: str) -> dict:
    facility = fixtures.read_facility(api, ctx["facility"]["id"])
    return factories.production_batch_payload(
        facility["id"],
        ctx["forecast"]["id"],
        facility["version"],
        recipe_component="Oatmeal Bake",
        planned_trays=5,
        scheduled_cook_start_at=instant,
    )


def test_a_batch_starting_at_the_shared_release_instant_exhausts_the_chiller(
    api: ApiClient,
) -> None:
    """Both incumbents are still counted at 12:30Z because occupancy is closed at the
    release instant, so a capacity of two is already spent.

    The PRD states: "A batch's occupancy is the **closed** interval running from
    `scheduled_cook_start_at` through `buffered_release_at` inclusive at both ends. A
    new batch overlaps an existing one when the new batch's `scheduled_cook_start_at`
    is at or before that batch's `buffered_release_at` and that batch's
    `scheduled_cook_start_at` is at or before the new batch's `buffered_release_at`."
    It concludes: "here, endpoints that merely touch **do** overlap, so a batch
    scheduled to start at the exact instant another is released collides with it", and
    "If the number of overlapping live batches is equal to or greater than the
    facility's `blast_chiller_capacity`, the create is rejected with
    `ERR_CHILLER_CAPACITY_EXCEEDED`".

    Design: Difficulty/resource_temporal_overlap/blast_chiller_closed_interval_overlaps_at_the_shared_release_instant
    """
    ctx = _chiller_holding_two_live_batches(api)

    assertions.assert_instant(
        ctx["batch_a"]["chill_deadline_at"], "2026-08-01T12:00:00Z"
    )
    assertions.assert_instant(
        ctx["batch_a"]["buffered_release_at"], "2026-08-01T12:30:00Z"
    )
    assertions.assert_instant(
        ctx["batch_b"]["buffered_release_at"], "2026-08-01T14:30:00Z"
    )

    before = fixtures.read_facility(api, ctx["facility"]["id"])
    validate_error(
        api.create_production_batch(
            _schedule_at(api, ctx, "2026-08-01T12:30:00Z"), users.FOOD_SUPERVISOR
        ),
        ApiErrorId.ERR_CHILLER_CAPACITY_EXCEEDED.value,
        409,
    )
    after = fixtures.read_facility(api, ctx["facility"]["id"])
    assertions.assert_no_version_change(before, after)

    _, meta = validate_paginated(
        api.list_production_batches(
            users.FOOD_SUPERVISOR, {"facility_id": ctx["facility"]["id"]}
        )
    )
    assert meta["total_count"] == 2


def test_one_second_after_the_release_instant_frees_a_chiller_slot(
    api: ApiClient,
) -> None:
    """A single second past the earlier release drops that batch out of the overlap
    set, leaving one live batch against a capacity of two.

    The PRD states that a create "succeeds only when that count is strictly less than
    the capacity", and that the window derivation gives "`buffered_release_at` 30
    minutes after `chill_deadline_at`", itself 360 minutes after the scheduled cook
    start. The tray budget is untouched because "The sum of `planned_trays` across
    every batch tied to the same forecast whose `production_stage` is not `DISCARDED`,
    counting the batch now being created, may not exceed that forecast's
    `total_forecast_trays`" — fifteen trays against a budget of twenty-two.

    Design: Difficulty/resource_temporal_overlap/blast_chiller_closed_interval_overlaps_at_the_shared_release_instant
    """
    ctx = _chiller_holding_two_live_batches(api)

    validate_error(
        api.create_production_batch(
            _schedule_at(api, ctx, "2026-08-01T12:30:00Z"), users.FOOD_SUPERVISOR
        ),
        ApiErrorId.ERR_CHILLER_CAPACITY_EXCEEDED.value,
        409,
    )

    admitted = validate_success(
        api.create_production_batch(
            _schedule_at(api, ctx, "2026-08-01T12:30:01Z"), users.FOOD_SUPERVISOR
        ),
        201,
    )
    assertions.assert_production_batch(admitted)
    assertions.assert_batch_creation_defaults(admitted)
    assertions.assert_instant(
        admitted["chill_deadline_at"], "2026-08-01T18:30:01Z"
    )
    assertions.assert_instant(
        admitted["buffered_release_at"], "2026-08-01T19:00:01Z"
    )

    batches, meta = validate_paginated(
        api.list_production_batches(
            users.FOOD_SUPERVISOR, {"facility_id": ctx["facility"]["id"]}
        )
    )
    assert meta["total_count"] == 3
    assert sum(batch["planned_trays"] for batch in batches) == 15
    for batch in batches:
        assert batch["production_stage"] == "PLANNED"
