"""Visit, plan, and skip lifecycle / state-machine tests (PRD §3.3-§3.7)."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    setup_open_pool_dispatched_visit, setup_scheduled_visit_planned_route,
    setup_green_recovery_pool, complete_payload, skip_payload,
    create_visit_payload, ApiErrorId, TEST_USERS,
)

FT = TEST_USERS["field_technician_headers"]
RM = TEST_USERS["route_manager_headers"]
AM = TEST_USERS["account_manager_headers"]


def test_visit_branches_complete_one_skip_other(api):
    """PRD §3.5: "Completing a visit is the field technician's central act,
    advancing the visit from `SCHEDULED` to `COMPLETED`."
    PRD §3.7: "A route manager skips a visit that will not be serviced, advancing it
    from `SCHEDULED` to `SKIPPED`." PRD §3.7: "Skips are never billed under any
    reason".

    Design: Difficulty/non_linear_state_machine/service_visit_branching_complete_vs_skip
    """
    ctx = setup_open_pool_dispatched_visit(volume_gallons=20000, plan_type="RECURRING",
                                           frequency="WEEKLY", per_visit_rate_cents=6000)
    # add a second visit on the same route so we can skip it
    visit_b = get_success_data(api.create_visit(
        create_visit_payload(ctx["pool"]["id"], ctx["plan"]["id"], ctx["route"]["id"],
                             slot_start_minute=600, slot_end_minute=660), RM))
    completed = validate_success(api.complete_visit(ctx["visit"]["id"], complete_payload(green_pool=False), FT))
    skipped = validate_success(api.skip_visit(visit_b["id"], skip_payload(skip_reason="WEATHER"), RM))
    assert completed["status"] == "COMPLETED"
    assert completed["billed_amount_cents"] == 6000
    assert skipped["status"] == "SKIPPED"
    assert skipped["billed_amount_cents"] == 0


def test_complete_already_completed_visit_rejected(api):
    """PRD §3.5: "a completion attempted against a visit not in a completable state
    is rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/complete_visit_from_completed_returns_invalid_state
    """
    ctx = setup_open_pool_dispatched_visit(volume_gallons=20000, plan_type="RECURRING",
                                           frequency="WEEKLY", per_visit_rate_cents=6000)
    validate_success(api.complete_visit(ctx["visit"]["id"], complete_payload(green_pool=False), FT))
    resp = api.complete_visit(ctx["visit"]["id"], complete_payload(green_pool=False), FT)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_new_visit_starts_scheduled_with_zero_bill(api):
    """PRD §3.4: "A freshly scheduled visit starts in `SCHEDULED`, recorded in its
    `status`, which can reach `COMPLETED`, `SKIPPED`, `RECOVERY_SCHEDULED`, or
    `CANCELLED`."
    PRD §3.4: "The visit also carries a `skip_reason` that defaults to `NONE`, a
    derived `billed_amount_cents` that stays 0 until completion, and a
    `makeup_visit_id` that stays null unless a weather skip spawns a makeup."

    Design: Corner/state_machines/new_visit_starts_in_scheduled
    """
    ctx = setup_scheduled_visit_planned_route(plan_type="RECURRING", frequency="WEEKLY",
                                              per_visit_rate_cents=6000)
    visit = validate_success(api.get_visit(ctx["visit"]["id"], RM))
    assert visit["status"] == "SCHEDULED"
    assert visit["billed_amount_cents"] == 0


def test_plan_cancel_cascades_to_scheduled_visit(api):
    """PRD §3.3: "An account manager may instead cancel an active plan, moving it
    from `ACTIVE` to `CANCELLED`; cancellation cascades, cancelling every one of
    that plan's visits still in `SCHEDULED` or `RECOVERY_SCHEDULED`."

    Design: Corner/state_machines/plan_cancel_cascades_visit_cancellation
    """
    ctx = setup_scheduled_visit_planned_route(plan_type="RECURRING", frequency="WEEKLY",
                                              per_visit_rate_cents=6000)
    plan = validate_success(api.cancel_service_plan(ctx["plan"]["id"], AM))
    visit = validate_success(api.get_visit(ctx["visit"]["id"], RM))
    assert plan["status"] == "CANCELLED"
    assert visit["status"] == "CANCELLED"


def test_one_time_plan_auto_completes_on_visit_completion(api):
    """PRD §3.3: "A plan reaches `COMPLETED` automatically rather than by request:
    when a visit completes and that completion drives the plan's `visits_remaining`
    to 0 while the plan is `ACTIVE`, the system bubbles the plan up to `COMPLETED`."
    PRD §3.3: "For a `ONE_TIME` plan it is 1 minus the count of that plan's visits
    that have been completed or skipped, so it reads 1 before service and 0
    afterward."

    Design: Corner/state_machines/plan_auto_completes_on_one_time_visit_completion
    """
    ctx = setup_open_pool_dispatched_visit(volume_gallons=20000, plan_type="ONE_TIME",
                                           frequency="NONE", per_visit_rate_cents=8000)
    validate_success(api.complete_visit(ctx["visit"]["id"], complete_payload(green_pool=False), FT))
    plan = validate_success(api.get_service_plan(ctx["plan"]["id"], AM))
    assert plan["visits_remaining"] == 0
    assert plan["status"] == "COMPLETED"


def test_weather_skip_creates_makeup_visit(api):
    """PRD §3.7: "A `WEATHER` skip is made up automatically: the system creates a
    fresh `SCHEDULED` makeup visit in the next available capacity slot of the same
    `route_id` and records its identifier on the original visit's `makeup_visit_id`."

    Design: Corner/state_machines/weather_skip_creates_makeup_visit
    """
    ctx = setup_scheduled_visit_planned_route(plan_type="RECURRING", frequency="WEEKLY",
                                              per_visit_rate_cents=6000)
    skipped = validate_success(api.skip_visit(ctx["visit"]["id"], skip_payload(skip_reason="WEATHER"), RM))
    assert skipped["status"] == "SKIPPED"
    assert skipped["makeup_visit_id"] is not None


def test_holiday_skip_creates_no_makeup(api):
    """PRD §3.7: "A `HOLIDAY` or `CUSTOMER_REQUEST` skip creates no makeup."
    PRD §3.4: "a `makeup_visit_id` that stays null unless a weather skip spawns a
    makeup."

    Design: Corner/state_machines/holiday_skip_creates_no_makeup
    """
    ctx = setup_scheduled_visit_planned_route(plan_type="RECURRING", frequency="WEEKLY",
                                              per_visit_rate_cents=6000)
    skipped = validate_success(api.skip_visit(ctx["visit"]["id"], skip_payload(skip_reason="HOLIDAY"), RM))
    assert skipped["status"] == "SKIPPED"
    assert skipped["makeup_visit_id"] is None


def test_recovery_visit_completion_reverts_pool_to_open(api):
    """PRD §3.6: "Completing a `RECOVERY_SCHEDULED` visit (permitted only while the
    pool's `service_status` is `GREEN_RECOVERY` and the route is `DISPATCHED`)
    advances that visit to `COMPLETED`, applies the flat recovery surcharge to its
    `billed_amount_cents`, and, when that completion is logged with `green_pool`
    false, transitions the pool from `GREEN_RECOVERY` back to `OPEN`".
    PRD §3.5: "A recovery visit — one that was in `RECOVERY_SCHEDULED` when completed
    — adds a flat recovery surcharge of 4500 cents."

    Design: Corner/state_machines/green_recovery_completion_reverts_pool_open
    """
    ctx = setup_green_recovery_pool(volume_gallons=20000, plan_type="ONE_TIME",
                                    frequency="NONE", per_visit_rate_cents=8000)
    resp = api.complete_visit(ctx["recovery_visit"]["id"], complete_payload(green_pool=False), FT)
    data = validate_success(resp)
    pool = validate_success(api.get_pool(ctx["pool"]["id"], AM))
    assert data["status"] == "COMPLETED"
    # ONE_TIME plan: base 8000 + recovery surcharge 4500 = 12500 (no prepaid coverage)
    assert data["billed_amount_cents"] == 12500, \
        f"expected 12500, got {data['billed_amount_cents']}"
    assert pool["service_status"] == "OPEN"
