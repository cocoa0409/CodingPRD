"""Delivery completion outcomes (DELIVERED / NO_ANSWER / SKIPPED), OAA ledger
accrual & compensation, provisioned-vs-delivered reporting, route-ownership, and
the immutable WellnessCheck record."""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    complete_delivery_payload,
    assert_wellness_check,
    make_volunteer_driver_headers,
    TEST_USERS,
)
from test_helpers.fixtures import (
    setup_active_client_with_scheduled_delivery,
    setup_active_client_with_plan,
    schedule_delivery,
    complete_delivery,
    create_active_driver,
    setup_open_welfare_alert,
)

ROUTE_MGR = TEST_USERS["route_manager_headers"]


# ---------------------------------------------------------------------------
# Delivery fork: DELIVERED vs NO_ANSWER divergent side effects
# ---------------------------------------------------------------------------
def test_no_answer_completion_opens_alert_and_increments_counter(api):
    """PRD §3.5: "the delivery moves `SCHEDULED → NO_ANSWER`, and a three-hop cascade fires.
    First, a `WellnessCheck` is created for this delivery and client with `outcome`
    `NO_ANSWER`. Second, that check increments the client's `consecutive_no_answer` by 1.
    Third, that check opens a `WelfareAlert` referencing it, whose severity is derived as
    described in §3.6."

    Design: Difficulty/non_linear_state_machine/delivery_fork_delivered_vs_no_answer
    """
    scenario = setup_active_client_with_scheduled_delivery(api, scheduled_date="2026-03-02")
    driver_id = scenario["driver"]["id"]
    completed = complete_delivery(api, scenario["delivery"]["id"], driver_id, "NO_ANSWER")
    assert completed["status"] == "NO_ANSWER"
    client = validate_success(api.get_client(scenario["client"]["id"], ROUTE_MGR), 200)
    assert client["consecutive_no_answer"] == 1
    alerts, _ = validate_paginated(api.list_welfare_alerts(ROUTE_MGR, params={"client_id": scenario["client"]["id"]}))
    assert len(alerts) >= 1 and alerts[0]["status"] == "OPEN"


def test_delivered_completion_resets_counter_and_accrues_units(api):
    """PRD §3.5: "the delivery moves `SCHEDULED → DELIVERED`; `oaa_units_accrued` is set to
    the delivery's `meal_count`; `delivered_at` is stamped with the completion time; the
    delivery's `meal_count` is added to the client's `lifetime_oaa_units` as a ledger-sync
    cascade; the client's `consecutive_no_answer` is reset to 0".

    Design: Difficulty/non_linear_state_machine/delivery_fork_delivered_vs_no_answer
    """
    scenario = setup_active_client_with_plan(api, meals_per_day=2, delivery_days=["MON", "WED", "FRI"])
    plan_id = scenario["meal_plan"]["id"]
    driver_id = scenario["driver"]["id"]
    del1 = schedule_delivery(api, plan_id, "2026-03-02")
    del2 = schedule_delivery(api, plan_id, "2026-03-09")
    complete_delivery(api, del1["id"], driver_id, "NO_ANSWER")  # counter -> 1
    delivered = complete_delivery(api, del2["id"], driver_id, "DELIVERED")
    assert delivered["status"] == "DELIVERED"
    client = validate_success(api.get_client(scenario["client"]["id"], ROUTE_MGR), 200)
    assert client["consecutive_no_answer"] == 0, "DELIVERED resets the no-answer counter"
    assert client["lifetime_oaa_units"] == 2, "meal_count 2 accrued to lifetime units"


# ---------------------------------------------------------------------------
# Provisioned vs delivered OAA reporting divergence
# ---------------------------------------------------------------------------
def test_provisioned_and_delivered_units_diverge(api):
    """PRD §3.5: "The **provisioned** monthly units, reported as `provisioned_monthly_units`
    on the client roll-up, are the client's `ACTIVE` plan `weekly_meal_count` multiplied by
    4 weeks per month — a planning figure independent of what was actually delivered. The
    **delivered** units, reported as `delivered_units`, are the sum of `meal_count` over the
    client's deliveries whose status is `DELIVERED`; deliveries that are `SKIPPED`,
    `NO_ANSWER`, `CANCELLED`, or `VOIDED` are excluded".

    Design: Difficulty/dual_variant_calc/oaa_units_provisioned_vs_delivered
    """
    scenario = setup_active_client_with_plan(api, meals_per_day=2, delivery_days=["MON", "WED", "FRI"])
    plan_id, driver_id = scenario["meal_plan"]["id"], scenario["driver"]["id"]
    d1 = schedule_delivery(api, plan_id, "2026-03-02")
    d2 = schedule_delivery(api, plan_id, "2026-03-04")
    d3 = schedule_delivery(api, plan_id, "2026-03-06")
    complete_delivery(api, d1["id"], driver_id, "DELIVERED")
    complete_delivery(api, d2["id"], driver_id, "DELIVERED")
    complete_delivery(api, d3["id"], driver_id, "SKIPPED")
    summary = validate_success(api.get_client_summary(scenario["client"]["id"], ROUTE_MGR), 200)
    assert summary["provisioned_monthly_units"] == 24, "weekly 6 * 4 weeks"
    assert summary["delivered_units"] == 4, "only the 2 DELIVERED (meal_count 2 each)"
    assert summary["provisioned_monthly_units"] != summary["delivered_units"]


def test_lifetime_units_track_only_delivered(api):
    """PRD §3.5: "The live `lifetime_oaa_units` ledger on the client is the running
    reconciliation of that same delivered figure, maintained forward on each `DELIVERED`
    completion and backward on each void."

    Design: Difficulty/dual_variant_calc/oaa_units_provisioned_vs_delivered
    """
    scenario = setup_active_client_with_plan(api, meals_per_day=2, delivery_days=["MON", "WED", "FRI"])
    plan_id, driver_id = scenario["meal_plan"]["id"], scenario["driver"]["id"]
    d1 = schedule_delivery(api, plan_id, "2026-03-02")
    d2 = schedule_delivery(api, plan_id, "2026-03-04")
    d3 = schedule_delivery(api, plan_id, "2026-03-06")
    complete_delivery(api, d1["id"], driver_id, "DELIVERED")
    complete_delivery(api, d2["id"], driver_id, "DELIVERED")
    complete_delivery(api, d3["id"], driver_id, "SKIPPED")
    client = validate_success(api.get_client(scenario["client"]["id"], ROUTE_MGR), 200)
    assert client["lifetime_oaa_units"] == 4, "2 DELIVERED * meal_count 2; SKIPPED excluded"


# ---------------------------------------------------------------------------
# Compensating invariant: deliver then void conserves OAA units
# ---------------------------------------------------------------------------
def test_delivered_delivery_accrues_units(api):
    """PRD §3.5: "the delivery's `meal_count` is added to the client's `lifetime_oaa_units`
    as a ledger-sync cascade".

    Design: Difficulty/compensating_invariant/oaa_units_conserved_on_deliver_then_void
    """
    scenario = setup_active_client_with_scheduled_delivery(api, scheduled_date="2026-03-02", meals_per_day=2)
    complete_delivery(api, scenario["delivery"]["id"], scenario["driver"]["id"], "DELIVERED")
    client = validate_success(api.get_client(scenario["client"]["id"], ROUTE_MGR), 200)
    assert client["lifetime_oaa_units"] == 2


def test_void_delivery_subtracts_units_back_to_zero(api):
    """PRD §3.5: "It moves the delivery `DELIVERED → VOIDED`, subtracts the delivery's
    `meal_count` back out of the client's `lifetime_oaa_units` as a ledger-sync compensation,
    resets the delivery's `oaa_units_accrued` to 0, and increments the delivery's `version`
    and the client's `version` each by 1."

    Design: Difficulty/compensating_invariant/oaa_units_conserved_on_deliver_then_void
    """
    scenario = setup_active_client_with_scheduled_delivery(api, scheduled_date="2026-03-02", meals_per_day=2)
    delivery_id = scenario["delivery"]["id"]
    complete_delivery(api, delivery_id, scenario["driver"]["id"], "DELIVERED")
    voided = validate_success(api.void_delivery(delivery_id, ROUTE_MGR), 200)
    assert voided["status"] == "VOIDED"
    assert voided["oaa_units_accrued"] == 0
    client = validate_success(api.get_client(scenario["client"]["id"], ROUTE_MGR), 200)
    assert client["lifetime_oaa_units"] == 0, "compensation returns lifetime units to 0"


# ---------------------------------------------------------------------------
# Corner: void invalid state, route ownership, immutable wellness check
# ---------------------------------------------------------------------------
def test_void_scheduled_delivery_rejected(api):
    """PRD §3.5: "Voiding is allowed only from `DELIVERED`, else
    `ERR_DELIVERY_NOT_DELIVERED` (HTTP 409)."

    Design: Corner/state_machines/delivery_void_from_scheduled_returns_invalid
    """
    scenario = setup_active_client_with_scheduled_delivery(api, scheduled_date="2026-03-02")
    resp = api.void_delivery(scenario["delivery"]["id"], ROUTE_MGR)
    validate_error(resp, "ERR_DELIVERY_NOT_DELIVERED", 409)


def test_driver_cannot_complete_delivery_on_route_they_do_not_own(api):
    """PRD §2.1: "a driver may complete a delivery only when their `X-User-ID` equals the
    `driver_id` of the route on which that delivery runs; otherwise the request is rejected
    with `ERR_NOT_ROUTE_DRIVER` (HTTP 403)."

    Design: Corner/endpoints/driver_cannot_complete_other_routes_delivery
    """
    scenario = setup_active_client_with_scheduled_delivery(api, scheduled_date="2026-03-02")
    other_driver = create_active_driver(api, full_name="Driver Two", phone="555-0111")
    resp = api.complete_delivery(
        scenario["delivery"]["id"], complete_delivery_payload("DELIVERED"),
        make_volunteer_driver_headers(other_driver["id"]),
    )
    validate_error(resp, "ERR_NOT_ROUTE_DRIVER", 403)
    delivery = validate_success(api.get_delivery(scenario["delivery"]["id"], ROUTE_MGR), 200)
    assert delivery["status"] == "SCHEDULED", "the delivery is untouched by the rejected completion"


def test_wellness_check_is_immutable_no_version_field(api):
    """PRD §2.4: "The one exception is the `WellnessCheck` resource, which is an immutable
    event record: it carries only `id` and `created_at`. It has neither an `updated_at`
    field nor a `version` field, because once written it is never mutated."

    Design: Corner/entities/wellness_check_has_no_version_field
    """
    scenario = setup_open_welfare_alert(api, scheduled_date="2026-03-02")
    checks, _ = validate_paginated(
        api.list_wellness_checks(ROUTE_MGR, params={"delivery_id": scenario["delivery"]["id"]})
    )
    assert len(checks) == 1
    wc = checks[0]
    assert_wellness_check(wc)
    assert "version" not in wc, "WellnessCheck must not carry a version field"
    assert "updated_at" not in wc, "WellnessCheck must not carry an updated_at field"
