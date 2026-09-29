"""Three operations gated on a sibling entity's state rather than on their own."""

from typing import Any, Dict

from test_helpers import constants as C
from test_helpers import fixtures as S
from test_helpers.api_client import ApiClient
from test_helpers.api_errors import ApiError
from test_helpers.assertions import assert_fields, assert_instant, assert_money, failed, ok
from test_helpers.constants import iso

CONDITIONAL_USE_FEE_TOTAL = 3848.00
SHOT_CLOCK_DEADLINE = iso("2026-10-30")
POWER_WINDOW_START = iso("2026-10-01")
POWER_WINDOW_END = iso("2026-10-05")
FIBER_WINDOW_START = iso("2026-10-05")
FIBER_WINDOW_END = iso("2026-10-09")
DELIVERY_DAY = iso("2026-10-09")
TARGET_DATE = iso("2026-12-01")
VARIANCE_DAYS = -53
FIBER_CREW_DAYS = 4


def _prepared_application_over_an_accepted_lease(api: ApiClient) -> Dict[str, Any]:
    """A filing that is itself ready, over a lease that has only been accepted."""
    chain = S.engaged_candidate(api)
    lease = S.create_lease(api, chain["cand_id"], chain["ll_id"])
    S.accept_lease(api, lease["id"])
    application = S.create_zoning_application(api, chain["cand_id"])
    S.add_visual_simulations(api, application["id"])
    chain["lease_id"] = lease["id"]
    chain["za_id"] = application["id"]
    return chain


def test_submission_is_refused_while_the_lease_is_only_accepted(api: ApiClient) -> None:
    """The application's own `PREPARING` status is legal; the other entity is not ready.

    PRD: "The candidate's `acquisition_status` must be `LEASE_EXECUTED` — a carrier
    does not file for entitlement on land it has not secured — and a candidate without
    an executed lease yields `ERR_LEASE_NOT_EXECUTED`."

    PRD: "Submission stamps `submitted_date` with the logical clock, prices the filing
    fee into `zoning_fee_total_usd`, and computes the initial
    `shot_clock_deadline_date`."

    Design: Difficulty/cross_entity_state_dependency/zoning_submit_depends_on_candidate_lease_executed
    """
    chain = _prepared_application_over_an_accepted_lease(api)

    refused = api.submit_zoning_application(chain["za_id"], headers=S.planner())
    failed(refused, ApiError.LEASE_NOT_EXECUTED, expected_status=409)

    application = ok(api.get_zoning_application(chain["za_id"], headers=S.planner()))
    assert_fields(application, status="PREPARING", visual_simulation_count=2)
    assert application["zoning_fee_total_usd"] is None, (
        "the fee is priced only at submission"
    )
    assert application["submitted_date"] is None, "nothing was filed"


def test_executing_the_lease_unblocks_the_identical_submission(api: ApiClient) -> None:
    """Execution changes only the candidate, and the same call then prices the filing.

    PRD: "Submission moves the application `PREPARING → SUBMITTED` and requires two
    things of the world outside the application."

    PRD: "`shot_clock_deadline_date` is the `submitted_date` advanced by the number of
    review days the jurisdiction publishes for this application's path —
    `by_right_review_days` for `BY_RIGHT`, `conditional_use_review_days` for
    `CONDITIONAL_USE`, `variance_review_days` for `VARIANCE` — and further advanced by
    the application's accumulated `tolled_days`."

    Design: Difficulty/cross_entity_state_dependency/zoning_submit_depends_on_candidate_lease_executed
    """
    chain = _prepared_application_over_an_accepted_lease(api)
    failed(
        api.submit_zoning_application(chain["za_id"], headers=S.planner()),
        ApiError.LEASE_NOT_EXECUTED,
        expected_status=409,
    )

    S.execute_lease(api, chain["lease_id"])
    candidate = ok(api.get_candidate(chain["cand_id"], headers=S.agent()))
    assert_fields(candidate, acquisition_status="LEASE_EXECUTED")

    submitted = ok(api.submit_zoning_application(chain["za_id"], headers=S.planner()))
    assert_fields(submitted, status="SUBMITTED")
    assert_money(
        submitted["zoning_fee_total_usd"], CONDITIONAL_USE_FEE_TOTAL, "zoning_fee_total_usd"
    )
    assert_instant(
        submitted["shot_clock_deadline_date"], SHOT_CLOCK_DEADLINE, "shot_clock_deadline_date"
    )


def _draft_lease_under_suspended_landlord(api: ApiClient) -> Dict[str, Any]:
    """A `DRAFT` lease whose landlord standing has been suspended."""
    chain = S.engaged_candidate(api)
    lease = S.create_lease(api, chain["cand_id"], chain["ll_id"])
    S.set_standing(api, chain["ll_id"], "SUSPENDED", "pending estoppel review")
    chain["lease_id"] = lease["id"]
    return chain


def test_the_opening_round_is_refused_while_the_landlord_is_suspended(
    api: ApiClient,
) -> None:
    """A `DRAFT` lease is a legal from-state, but the landlord record blocks the round.

    PRD: "`SUBMIT` opens the negotiation and moves the lease `DRAFT → SUBMITTED`; it
    additionally requires the landlord's `standing` to be `ACTIVE`."

    PRD: "Only `ACTIVE` standing permits the opening negotiation round or lease
    execution; anything else is refused with `ERR_LANDLORD_NOT_IN_GOOD_STANDING`."

    Design: Difficulty/cross_entity_state_dependency/lease_round_submit_depends_on_landlord_standing
    """
    chain = _draft_lease_under_suspended_landlord(api)

    refused = api.add_lease_round(
        chain["lease_id"],
        {"action": "SUBMIT", "counter_rent_usd": C.LEASE_BASE_RENT_USD},
        headers=S.agent(),
    )
    failed(refused, ApiError.LANDLORD_NOT_IN_GOOD_STANDING, expected_status=409)

    lease = ok(api.get_lease(chain["lease_id"], headers=S.agent()))
    assert_fields(lease, status="DRAFT", round_count=0)
    assert lease["last_counter_rent_usd"] is None, "no counter was stored"


def test_restoring_standing_lets_the_same_round_through_and_prices_the_variance(
    api: ApiClient,
) -> None:
    """Returning the landlord to `ACTIVE` is what admits the round.

    PRD: "All three of these actions require `counter_rent_usd` to be present, store
    it as `last_counter_rent_usd`, increment `round_count` by one, recompute
    `rent_variance_pct`, and increment the lease's `version`."

    PRD: "It is 100 multiplied by the difference between the lease's
    `last_counter_rent_usd` and the ring's `market_benchmark_monthly_rent_usd`, divided
    by that same `market_benchmark_monthly_rent_usd`, rounded half up to two decimal
    places."

    Design: Difficulty/cross_entity_state_dependency/lease_round_submit_depends_on_landlord_standing
    """
    chain = _draft_lease_under_suspended_landlord(api)
    failed(
        api.add_lease_round(
            chain["lease_id"],
            {"action": "SUBMIT", "counter_rent_usd": C.LEASE_BASE_RENT_USD},
            headers=S.agent(),
        ),
        ApiError.LANDLORD_NOT_IN_GOOD_STANDING,
        expected_status=409,
    )

    S.set_standing(api, chain["ll_id"], "ACTIVE", "estoppel cleared")

    opened = ok(
        api.add_lease_round(
            chain["lease_id"],
            {"action": "SUBMIT", "counter_rent_usd": C.LEASE_BASE_RENT_USD},
            headers=S.agent(),
        )
    )
    assert_fields(opened, status="SUBMITTED", round_count=1)
    assert_money(
        opened["last_counter_rent_usd"], C.LEASE_BASE_RENT_USD, "last_counter_rent_usd"
    )
    assert_money(opened["rent_variance_pct"], 0.00, "rent_variance_pct")


def _plan_awaiting_fiber_delivery(api: ApiClient) -> Dict[str, Any]:
    """A `PLANNED` plan whose `POWER` order is delivered and whose `FIBER` order is not."""
    chain = S.build_selected_chain(api)
    plan = S.create_plan(api, chain["ring_id"], TARGET_DATE)
    provider = S.create_provider(api)
    power = S.create_order(
        api,
        chain["cand_id"],
        provider["id"],
        "POWER",
        POWER_WINDOW_START,
        POWER_WINDOW_END,
    )
    fiber = S.create_order(
        api,
        chain["cand_id"],
        provider["id"],
        "FIBER",
        FIBER_WINDOW_START,
        FIBER_WINDOW_END,
    )
    S.order_action(api, power["id"], "SCHEDULE")
    S.order_action(api, fiber["id"], "SCHEDULE")
    S.set_clock(api, DELIVERY_DAY)
    S.order_action(api, power["id"], "DELIVER", delivered_date=POWER_WINDOW_END)
    chain.update(
        {
            "plan_id": plan["id"],
            "prov_id": provider["id"],
            "power_id": power["id"],
            "fiber_id": fiber["id"],
        }
    )
    return chain


def test_activation_is_refused_until_both_order_types_are_delivered(
    api: ApiClient,
) -> None:
    """One delivered `POWER` order is not enough, and the refusal moves nothing.

    PRD: "The ring must be in `SITE_SELECTED`; the ring's selected candidate must have
    `feasibility_status` equal to `BUILD_READY`, or `ERR_CANDIDATE_NOT_BUILD_READY`;
    that candidate must have at least one `DELIVERED` backhaul order of `order_type`
    `POWER` and at least one of `order_type` `FIBER`, or `ERR_BACKHAUL_NOT_DELIVERED`;
    and the supplied `actual_on_air_date` must not be after the logical clock, or
    `ERR_DATE_IN_FUTURE`."

    PRD: "A provider's `committed_crew_days` is the sum of `crew_days` across that
    provider's orders whose status is `REQUESTED` or `SCHEDULED`; `DELIVERED` and
    `CANCELLED` orders are excluded both from that sum and from the day-coverage
    count."

    Design: Difficulty/cross_entity_state_dependency/on_air_activate_depends_on_delivered_power_and_fiber_orders
    """
    chain = _plan_awaiting_fiber_delivery(api)

    refused = api.activate_plan(
        chain["plan_id"], {"actual_on_air_date": DELIVERY_DAY}, headers=S.cm()
    )
    failed(refused, ApiError.BACKHAUL_NOT_DELIVERED, expected_status=409)

    plan = ok(api.get_on_air_plan(chain["plan_id"], headers=S.director()))
    assert_fields(plan, status="PLANNED")
    ring = ok(api.get_search_ring(chain["ring_id"], headers=S.director()))
    assert_fields(ring, status="SITE_SELECTED")
    provider = ok(api.get_utility_provider(chain["prov_id"], headers=S.cm()))
    assert_fields(provider, committed_crew_days=FIBER_CREW_DAYS)


def test_the_fiber_delivery_unblocks_activation_and_takes_the_ring_on_air(
    api: ApiClient,
) -> None:
    """Delivering the second order is what lets the identical activation through.

    PRD: "On success `actual_on_air_date` is stored, `variance_days` is set to the
    whole days from `target_on_air_date` to `actual_on_air_date` — negative when the
    site went live early — the plan moves to the terminal `ON_AIR`, and the ring moves
    `SITE_SELECTED → ON_AIR`, its own terminal state."

    PRD: "Activation is the `ConstructionManager`'s final act and is accepted from
    `PLANNED`, `AT_RISK` or `RESET` — identical preconditions and identical effects
    from all three."

    Design: Difficulty/cross_entity_state_dependency/on_air_activate_depends_on_delivered_power_and_fiber_orders
    """
    chain = _plan_awaiting_fiber_delivery(api)
    failed(
        api.activate_plan(
            chain["plan_id"], {"actual_on_air_date": DELIVERY_DAY}, headers=S.cm()
        ),
        ApiError.BACKHAUL_NOT_DELIVERED,
        expected_status=409,
    )

    S.order_action(api, chain["fiber_id"], "DELIVER", delivered_date=DELIVERY_DAY)
    provider = ok(api.get_utility_provider(chain["prov_id"], headers=S.cm()))
    assert_fields(provider, committed_crew_days=0)

    activated = ok(
        api.activate_plan(
            chain["plan_id"], {"actual_on_air_date": DELIVERY_DAY}, headers=S.cm()
        )
    )
    assert_fields(activated, status="ON_AIR", variance_days=VARIANCE_DAYS)
    assert_instant(activated["actual_on_air_date"], DELIVERY_DAY, "actual_on_air_date")

    ring = ok(api.get_search_ring(chain["ring_id"], headers=S.director()))
    assert_fields(ring, status="ON_AIR")
