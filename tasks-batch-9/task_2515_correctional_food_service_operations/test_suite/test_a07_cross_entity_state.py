"""Operations blocked by the state of a *different* entity.

A menu cycle cannot go live while its contract is still a draft, and a production
batch cannot be scheduled against a forecast that has not been locked. In both
cases the rejected attempt must leave no trace, and the operation must succeed
once the other entity moves.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import ApiClient, ApiErrorId, assertions, factories, fixtures
from test_helpers import test_users as users


# ---------------------------------------------------------------------------
# Menu cycle activation depends on the contract
# ---------------------------------------------------------------------------


def _signed_cycle_under_a_draft_contract(api: ApiClient) -> dict:
    """A NUTRITION_APPROVED cycle at a facility whose contract was never
    activated."""
    fixtures.set_clock(api)
    contract = fixtures.create_contract(api, contract_code="CFS-2515-CE1")
    facility = fixtures.create_facility(
        api,
        contract["id"],
        facility_code="FAC-CE1",
        sharps_authorized_count=12,
    )
    signed = fixtures.signed_menu_cycle(api, facility["id"])
    return {"contract": contract, "facility": facility, "cycle": signed["cycle"]}


def test_activating_a_cycle_under_a_draft_contract_is_rejected(api: ApiClient) -> None:
    """The cycle is itself perfectly eligible; the blocker is the contract's state.

    The PRD states: "The service contract of the cycle's facility must itself be in
    `ACTIVE`, otherwise the attempt is rejected with `ERR_CONTRACT_NOT_ACTIVE`." A
    rejected activation writes nothing, so the cycle stays in `NUTRITION_APPROVED`
    with `activated_by_user_id` and `activated_at` still null.

    Design: Difficulty/cross_entity_state_dependency/menu_cycle_activation_requires_service_contract_active
    """
    ctx = _signed_cycle_under_a_draft_contract(api)

    assert ctx["contract"]["status"] == "DRAFT"
    assert ctx["cycle"]["status"] == "NUTRITION_APPROVED"
    assert ctx["cycle"]["approved_kcal_per_meal_day"] == 2800
    assert ctx["cycle"]["approved_cost_cents_per_meal_day"] == 315

    validate_error(
        api.activate_menu_cycle(ctx["cycle"]["id"], users.CONTRACT_ADMIN),
        ApiErrorId.ERR_CONTRACT_NOT_ACTIVE.value,
        409,
    )

    cycle = validate_success(
        api.get_menu_cycle(ctx["cycle"]["id"], users.FOOD_SUPERVISOR)
    )
    assert cycle["status"] == "NUTRITION_APPROVED"
    assert cycle["activated_by_user_id"] is None
    assert cycle["activated_at"] is None


def test_activating_the_contract_first_lets_the_same_cycle_go_live(
    api: ApiClient,
) -> None:
    """With the contract moved to ACTIVE the identical activation succeeds and stamps
    the acting administrator.

    The PRD states: "On success the cycle's status becomes `ACTIVE`,
    `activated_by_user_id` records the acting `X-User-ID`, `activated_at` is stamped
    from the logical clock, and `version` is incremented by 1." The two-person rule
    still holds because "A menu cycle's `nutrition_signed_by_user_id` may not equal
    the `X-User-ID` that activates it."

    Design: Difficulty/cross_entity_state_dependency/menu_cycle_activation_requires_service_contract_active
    """
    ctx = _signed_cycle_under_a_draft_contract(api)

    validate_error(
        api.activate_menu_cycle(ctx["cycle"]["id"], users.CONTRACT_ADMIN),
        ApiErrorId.ERR_CONTRACT_NOT_ACTIVE.value,
        409,
    )

    activated_contract = validate_success(
        api.activate_service_contract(ctx["contract"]["id"], users.CONTRACT_ADMIN)
    )
    assert activated_contract["status"] == "ACTIVE"

    cycle = validate_success(
        api.activate_menu_cycle(ctx["cycle"]["id"], users.CONTRACT_ADMIN)
    )
    assertions.assert_menu_cycle(cycle)
    assert cycle["status"] == "ACTIVE"
    assert cycle["activated_by_user_id"] == users.user_id_of(users.CONTRACT_ADMIN)
    assertions.assert_instant(cycle["activated_at"], "2026-08-01T00:00:00Z")
    assert cycle["nutrition_signed_by_user_id"] == users.user_id_of(users.DIETITIAN)


# ---------------------------------------------------------------------------
# Production batch scheduling depends on the forecast
# ---------------------------------------------------------------------------


def _draft_forecast_at_a_live_facility(api: ApiClient) -> dict:
    """An OPEN facility with an ACTIVE menu cycle whose only forecast is still a
    draft."""
    ctx = fixtures.facility_with_active_cycle(
        api,
        contract_overrides={"contract_code": "CFS-2515-CE2"},
        facility_overrides={
            "facility_code": "FAC-CE2",
            "sharps_authorized_count": 12,
            "blast_chiller_capacity": 2,
        },
    )
    facility_id = ctx["facility"]["id"]
    count = fixtures.create_population_count(api, facility_id)
    forecast = validate_success(
        api.create_meal_forecast(
            factories.meal_forecast_payload(facility_id, count["id"]),
            users.FOOD_SUPERVISOR,
        ),
        201,
    )
    ctx["population_count"] = count
    ctx["forecast"] = forecast
    return ctx


def _batch_payload(api: ApiClient, ctx: dict) -> dict:
    facility = fixtures.read_facility(api, ctx["facility"]["id"])
    return factories.production_batch_payload(
        facility["id"],
        ctx["forecast"]["id"],
        facility["version"],
        planned_trays=10,
        scheduled_cook_start_at="2026-08-01T06:00:00Z",
    )


def test_scheduling_against_a_draft_forecast_is_rejected_and_writes_nothing(
    api: ApiClient,
) -> None:
    """The facility is open and the payload is affordable; the blocker is that the
    forecast has not been frozen.

    The PRD states: "The named forecast must be in `LOCKED` — a draft or superseded
    forecast reports `ERR_FORECAST_NOT_LOCKED`", and that in the rejection ladder
    "the first failure aborts the request with no partial writes." A new forecast
    "opens in `DRAFT` with `locked_at` null."

    Design: Difficulty/cross_entity_state_dependency/production_batch_create_requires_meal_forecast_locked
    """
    ctx = _draft_forecast_at_a_live_facility(api)

    assertions.assert_meal_forecast(ctx["forecast"])
    assert ctx["forecast"]["status"] == "DRAFT"
    assert ctx["forecast"]["locked_at"] is None
    assert ctx["forecast"]["total_forecast_trays"] == 22

    before = fixtures.read_facility(api, ctx["facility"]["id"])
    assert before["kitchen_posture"] == "OPEN"

    validate_error(
        api.create_production_batch(_batch_payload(api, ctx), users.FOOD_SUPERVISOR),
        ApiErrorId.ERR_FORECAST_NOT_LOCKED.value,
        409,
    )

    batches, meta = validate_paginated(
        api.list_production_batches(
            users.FOOD_SUPERVISOR, {"meal_forecast_id": ctx["forecast"]["id"]}
        )
    )
    assert meta["total_count"] == 0
    assert batches == []

    after = fixtures.read_facility(api, ctx["facility"]["id"])
    assert after["version"] == before["version"]

    still_draft = validate_success(
        api.get_meal_forecast(ctx["forecast"]["id"], users.FOOD_SUPERVISOR)
    )
    assert still_draft["status"] == "DRAFT"
    assert still_draft["locked_at"] is None


def test_locking_the_forecast_first_admits_the_same_batch(api: ApiClient) -> None:
    """Once the forecast is frozen the identical schedule request is accepted and
    the chiller window is derived from the cook start.

    The PRD states that locking "freezes it for production and moves it to `LOCKED`,
    stamping `locked_at` from the logical clock and incrementing `version` by 1." It
    also states: "Each batch occupies the blast chiller for a fixed six hours from
    its scheduled cook start — 360 minutes — after which `chill_deadline_at` falls,
    and then for a further half hour of sanitation before the equipment is genuinely
    free, giving `buffered_release_at` 30 minutes after `chill_deadline_at`."

    Design: Difficulty/cross_entity_state_dependency/production_batch_create_requires_meal_forecast_locked
    """
    ctx = _draft_forecast_at_a_live_facility(api)

    validate_error(
        api.create_production_batch(_batch_payload(api, ctx), users.FOOD_SUPERVISOR),
        ApiErrorId.ERR_FORECAST_NOT_LOCKED.value,
        409,
    )

    locked = validate_success(
        api.lock_meal_forecast(ctx["forecast"]["id"], users.FOOD_SUPERVISOR)
    )
    assert locked["status"] == "LOCKED"
    assertions.assert_instant(locked["locked_at"], "2026-08-01T00:00:00Z")
    assertions.assert_version_bumped_by(ctx["forecast"], locked)
    assert locked["total_forecast_trays"] == 22
    ctx["forecast"] = locked

    batch = validate_success(
        api.create_production_batch(_batch_payload(api, ctx), users.FOOD_SUPERVISOR),
        201,
    )
    assertions.assert_production_batch(batch)
    assertions.assert_batch_creation_defaults(batch)
    assert batch["meal_forecast_id"] == locked["id"]
    assert batch["planned_trays"] == 10
    assertions.assert_instant(batch["chill_deadline_at"], "2026-08-01T12:00:00Z")
    assertions.assert_instant(batch["buffered_release_at"], "2026-08-01T12:30:00Z")

    _, meta = validate_paginated(
        api.list_production_batches(
            users.FOOD_SUPERVISOR, {"meal_forecast_id": locked["id"]}
        )
    )
    assert meta["total_count"] == 1
