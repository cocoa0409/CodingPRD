"""Drafting, approving, revising, scheduling and cancelling treatment plans."""

import test_helpers as fx
from test_helpers import (
    ECOLOGIST,
    MANAGER,
    ApiErrorId,
    validate_error,
    validate_success,
)


def test_plan_submit_blocked_until_trigger_assessment_is_confirmed(api):
    """PRD §3.7: "And the triggering assessment must by now have reached
    `CONFIRMED`; a plan whose justification is still `OPEN`, or has been
    `SUPERSEDED`, is refused with `ERR_TRIGGER_ASSESSMENT_NOT_CONFIRMED` (HTTP
    409)."
    PRD §3.7: "On success the submitter's `X-User-ID` is recorded as
    `submitted_by_user_id`."
    PRD §3.7: "`required_approvals` is 2 when `treatment_type` is `AERIAL` and 1
    otherwise, because putting product into the air over a district demands two
    independent managers. `notification_required` is true when `treatment_type` is
    `ADULTICIDE` or `AERIAL`, and false for `LARVICIDE`, since larvicide goes into
    standing water rather than into the air column."

    Design: Corner/state_machines/corner_plan_submit_with_unconfirmed_assessment_rejected
    """
    fx.set_clock(fx.CLOCK_BASE)
    area = fx.create_area()
    tech = fx.create_applicator(license_category="LARVICIDE_ONLY")
    assessment = fx.open_assessment(area["id"], "2026-06-01")
    product = fx.create_product()
    plan = fx.create_plan(area["id"], assessment["id"], "LARVICIDE")
    fx.add_route(plan["id"], tech["id"], product["id"])

    blocked = api.transition_treatment_plan(plan["id"], {"action": "SUBMIT"}, ECOLOGIST)
    validate_error(blocked, ApiErrorId.ERR_TRIGGER_ASSESSMENT_NOT_CONFIRMED.value, 409)

    fx.confirm_assessment(assessment["id"])
    submitted = validate_success(
        api.transition_treatment_plan(plan["id"], {"action": "SUBMIT"}, ECOLOGIST)
    )

    fx.assert_treatment_plan(submitted)
    assert submitted["status"] == "SUBMITTED"
    assert submitted["submitted_by_user_id"] == "u-eco-1"
    assert submitted["required_approvals"] == 1
    assert submitted["notification_required"] is False


def test_approved_plan_refuses_new_routes_and_verify_of_a_planned_route(api):
    """PRD §3.7: "A `VectorEcologist` adds a route to a plan whose `status` is
    `DRAFT` or `RETURNED`; attaching a route to a plan in any other state — already
    submitted, already approved, cancelled — is refused with
    `ERR_INVALID_TRANSITION`."
    PRD §3.9: "An `AbatementManager` closes out the paperwork by verifying the
    route, advancing `EXECUTED → VERIFIED`, which moves no material and exists
    solely to make the route eligible for the cost allocation."

    Design: Corner/state_machines/corner_route_creation_and_verify_rejected_on_approved_plan
    """
    bundle = fx.setup_plan_scenario(
        applicator_overrides={"license_category": "LARVICIDE_ONLY"}
    )

    extra_route = api.create_treatment_route(
        bundle["plan"]["id"],
        fx.create_treatment_route_payload(
            bundle["applicator"]["id"], bundle["product"]["id"], route_code="R-2",
            window_start="2026-06-05T11:00:00.000Z", window_end="2026-06-05T12:00:00.000Z",
        ),
        ECOLOGIST,
    )
    validate_error(extra_route, ApiErrorId.ERR_INVALID_TRANSITION.value, 409)

    verify = api.transition_treatment_route(
        bundle["route"]["id"], {"action": "VERIFY"}, MANAGER
    )
    validate_error(verify, ApiErrorId.ERR_INVALID_TRANSITION.value, 409)

    assert fx.read_route(bundle["route"]["id"])["status"] == "PLANNED"
    assert fx.read_plan(bundle["plan"]["id"])["status"] == "APPROVED"


def test_schedule_without_a_committed_route_is_rejected(api):
    """PRD §3.8: "First, the plan must have at least one route in `COMMITTED` and
    no route still in `PLANNED`; otherwise the request is refused with
    `ERR_NO_COMMITTED_ROUTE` (HTTP 409) — every route must have been either
    committed, released, or voided before an operational date is fixed."

    Design: Corner/state_machines/corner_plan_schedule_without_committed_route_rejected
    """
    bundle = fx.setup_plan_scenario(
        applicator_overrides={"license_category": "LARVICIDE_ONLY"}
    )

    response = api.transition_treatment_plan(
        bundle["plan"]["id"],
        {"action": "SCHEDULE", "scheduled_start_at": "2026-06-05T09:00:00.000Z"},
        MANAGER,
    )
    validate_error(response, ApiErrorId.ERR_NO_COMMITTED_ROUTE.value, 409)

    plan = fx.read_plan(bundle["plan"]["id"])
    assert plan["status"] == "APPROVED"
    assert plan["scheduled_start_at"] is None


def test_plan_start_and_route_execution_respect_their_own_clock_gates(api):
    """PRD §3.8: "Starting the operation advances `SCHEDULED → IN_PROGRESS` and is
    permitted only when the logical clock has reached `scheduled_start_at`,
    inclusive; starting earlier is refused with `ERR_PLAN_START_TOO_EARLY` (HTTP
    409)."
    PRD §3.9: "The logical clock must also have reached the route's `window_start`,
    inclusive; executing early is refused with `ERR_ROUTE_WINDOW_NOT_OPEN` (HTTP
    409)."

    Design: Corner/state_machines/corner_plan_start_and_route_execute_time_gates_enforced
    """
    bundle = fx.setup_committed_route(
        applicator_overrides={"license_category": "LARVICIDE_ONLY"},
        routes=[{
            "window_start": "2026-06-05T12:00:00.000Z",
            "window_end": "2026-06-05T13:00:00.000Z",
        }],
    )
    fx.plan_action(
        bundle["plan"]["id"], "SCHEDULE", scheduled_start_at="2026-06-05T09:00:00.000Z"
    )

    too_early = api.transition_treatment_plan(
        bundle["plan"]["id"], {"action": "START"}, MANAGER
    )
    validate_error(too_early, ApiErrorId.ERR_PLAN_START_TOO_EARLY.value, 409)

    fx.set_clock("2026-06-05T09:00:00.000Z")
    started = validate_success(
        api.transition_treatment_plan(bundle["plan"]["id"], {"action": "START"}, MANAGER)
    )
    assert started["status"] == "IN_PROGRESS"

    early_execute = api.transition_treatment_route(
        bundle["route"]["id"],
        {"action": "EXECUTE", "actual_acres": 1.0, "wind_speed_mph": 2.0},
        fx.make_field_tech_headers(bundle["applicator"]["id"]),
    )
    validate_error(early_execute, ApiErrorId.ERR_ROUTE_WINDOW_NOT_OPEN.value, 409)

    route = fx.read_route(bundle["route"]["id"])
    assert route["status"] == "COMMITTED"
    assert route["actual_volume_ml"] is None
    fx.assert_index(
        fx.read_product(bundle["product"]["id"])["committed_ml"], 100.00, "committed_ml"
    )


def test_complete_requires_every_route_settled_and_one_verified(api):
    """PRD §3.9: "An `AbatementManager` advances the plan `IN_PROGRESS →
    COMPLETED` only when every route of the plan has settled into `VERIFIED`,
    `VOIDED`, or `RELEASED`, and at least one of them is `VERIFIED`; a plan with a
    route still `PLANNED`, still `COMMITTED`, or still merely `EXECUTED`, or a plan
    where every route was voided or released, is refused with
    `ERR_ROUTES_NOT_SETTLED` (HTTP 409)."
    PRD §3.9: "Second, labour: for each verified route multiply its
    `duration_minutes` by the crew rate of 120 cents per minute, and sum the
    products into `labor_cost_cents`."

    Design: Corner/state_machines/corner_plan_complete_with_executed_but_unverified_route_rejected
    """
    bundle = fx.setup_executed_route(
        applicator_overrides={"license_category": "LARVICIDE_ONLY"},
        product_overrides={
            "name": "Donated BTI", "epa_reg_no": "EPA-909", "cost_cents_per_liter": 0,
        },
        routes=[{
            "window_start": "2026-06-05T09:00:00.000Z",
            "window_end": "2026-06-05T10:40:00.000Z",
        }],
    )

    premature = api.transition_treatment_plan(
        bundle["plan"]["id"], {"action": "COMPLETE"}, MANAGER
    )
    validate_error(premature, ApiErrorId.ERR_ROUTES_NOT_SETTLED.value, 409)

    fx.route_action(bundle["route"]["id"], "VERIFY")
    completed = validate_success(
        api.transition_treatment_plan(bundle["plan"]["id"], {"action": "COMPLETE"}, MANAGER)
    )

    fx.assert_treatment_plan(completed)
    assert completed["status"] == "COMPLETED"
    assert fx.read_route(bundle["route"]["id"])["duration_minutes"] == 100
    assert completed["material_cost_cents"] == 0
    assert completed["labor_cost_cents"] == 12000
    assert completed["subtotal_cents"] == 12000
    assert completed["admin_fee_rate"] == 0.08
    assert completed["admin_fee_cents"] == 960
    assert completed["total_cost_cents"] == 12960


def test_cancel_releases_committed_route_and_expires_queued_notice(api):
    """PRD §3.7: "Cancellation stores the supplied `cancel_reason`, moves the plan
    to `CANCELLED`, and unwinds everything the plan was holding."
    PRD §3.7: "Every route in `COMMITTED` becomes `RELEASED` and gives back its
    reservation exactly as an explicit release would: the route's
    `estimated_volume_ml` leaves `committed_ml` and returns to `on_hand_ml`, the
    product's `version` advances, and the applicator's `assigned_route_count`
    decreases by 1."
    PRD §3.7: "Every notice of the plan in `QUEUED` or `SENT` becomes `EXPIRED`, so
    no further delivery attempt is possible."

    Design: Corner/state_machines/corner_plan_cancel_releases_committed_route_and_expires_notification
    """
    bundle = fx.setup_committed_route(
        applicator_overrides={"license_category": "LARVICIDE_ONLY"},
        sensitive_sites=[{"site_type": "APIARY", "x_m": 960, "y_m": 1280}],
        routes=[{"center_x_m": 0, "center_y_m": 0}],
    )
    notification = fx.issue_notification(
        bundle["plan"]["id"], bundle["site"]["id"], channel="SMS"
    )
    assert notification["status"] == "QUEUED"

    cancelled = validate_success(
        api.transition_treatment_plan(
            bundle["plan"]["id"],
            {"action": "CANCEL", "cancel_reason": "Rain forecast for the whole week"},
            MANAGER,
        )
    )

    assert cancelled["status"] == "CANCELLED"
    assert fx.read_route(bundle["route"]["id"])["status"] == "RELEASED"
    assert fx.read_notification(notification["id"])["status"] == "EXPIRED"

    product = fx.read_product(bundle["product"]["id"])
    fx.assert_inventory_partition(product)
    fx.assert_index(product["on_hand_ml"], 100000.00, "on_hand_ml")
    fx.assert_index(product["committed_ml"], 0.00, "committed_ml")
    fx.assert_index(product["applied_ml"], 0.00, "applied_ml")
    assert fx.read_applicator(bundle["applicator"]["id"])["assigned_route_count"] == 0
    fx.assert_index(cancelled["estimated_total_ml"], 0.00, "estimated_total_ml")


def test_segregation_of_duties_blocks_self_and_repeat_approval(api):
    """PRD §3.7: "the approver's `X-User-ID` must differ from
    `submitted_by_user_id`"
    PRD §3.7: "A manager whose `X-User-ID` already appears in `approver_user_ids`
    is refused with `ERR_DUPLICATE_APPROVER` (HTTP 409) — one body, one signature."
    PRD §3.7: "When the number of approvers already recorded plus this one equals
    `required_approvals`, the identifier is appended and the plan advances
    `SUBMITTED → APPROVED`."

    Design: Corner/rbac/corner_segregation_of_duties_blocks_self_and_repeat_approval
    """
    fx.set_clock(fx.CLOCK_BASE)
    dual = fx.make_ecologist_headers("u-dual-1")
    area = fx.create_area()
    tech = fx.create_applicator()
    assessment = fx.open_assessment(area["id"], "2026-06-01", headers=dual)
    fx.confirm_assessment(assessment["id"], headers=dual)
    product = fx.create_product(**fx.PRODUCT_PROFILES["AERIAL"])
    plan = fx.create_plan(area["id"], assessment["id"], "AERIAL", headers=dual)
    fx.add_route(plan["id"], tech["id"], product["id"], headers=dual, planned_acres=10.0)
    fx.plan_action(plan["id"], "SUBMIT", dual)

    self_approval = api.transition_treatment_plan(
        plan["id"], {"action": "APPROVE"}, fx.make_manager_headers("u-dual-1")
    )
    validate_error(self_approval, ApiErrorId.ERR_SELF_APPROVAL.value, 403)

    first = validate_success(
        api.transition_treatment_plan(
            plan["id"], {"action": "APPROVE"}, fx.make_manager_headers("u-mgr-1")
        )
    )
    assert first["status"] == "SUBMITTED"

    repeat = api.transition_treatment_plan(
        plan["id"], {"action": "APPROVE"}, fx.make_manager_headers("u-mgr-1")
    )
    validate_error(repeat, ApiErrorId.ERR_DUPLICATE_APPROVER.value, 409)

    final = validate_success(
        api.transition_treatment_plan(
            plan["id"], {"action": "APPROVE"}, fx.make_manager_headers("u-mgr-2")
        )
    )
    assert final["status"] == "APPROVED"
    assert final["approver_user_ids"] == ["u-mgr-1", "u-mgr-2"]
    assert final["submitted_by_user_id"] == "u-dual-1"


def test_aerial_plan_holds_at_submitted_after_a_single_approval_then_returns(api):
    """PRD §3.7: "When the number of approvers already recorded plus this one is
    still fewer than `required_approvals`, the manager's `X-User-ID` is appended to
    `approver_user_ids` and the plan **stays in** `SUBMITTED`: this is the aerial
    case after a single approval, and the response reports a plan still awaiting
    its second signature."
    PRD §3.7: "A manager who is unconvinced returns the plan instead, advancing
    `SUBMITTED → RETURNED` with the supplied `return_reason` stored and
    `revision_count` increased by 1."
    PRD §3.7: "From `RETURNED` the drafting ecologist revises, advancing `RETURNED
    → DRAFT`, which resets `approver_user_ids` to an empty list and
    `submitted_by_user_id` back to null — every signature collected on the previous
    revision is discarded, so a re-submitted aerial plan must again gather two
    approvals."

    Design: Difficulty/non_linear_state_machine/aerial_plan_return_revise_cycle_clears_partial_quorum
    """
    bundle = fx.setup_plan_scenario(
        treatment_type="AERIAL", approve=False,
        routes=[{
            "window_start": "2026-06-05T06:00:00.000Z",
            "window_end": "2026-06-05T09:00:00.000Z",
            "planned_acres": 40.0,
        }],
    )
    fx.plan_action(bundle["plan"]["id"], "SUBMIT", ECOLOGIST)

    after_first = validate_success(
        api.transition_treatment_plan(
            bundle["plan"]["id"], {"action": "APPROVE"}, fx.make_manager_headers("u-mgr-1")
        )
    )
    assert after_first["status"] == "SUBMITTED"
    assert after_first["required_approvals"] == 2
    assert after_first["approver_user_ids"] == ["u-mgr-1"]

    returned = validate_success(
        api.transition_treatment_plan(
            bundle["plan"]["id"],
            {"action": "RETURN", "return_reason": "Buffer map out of date"},
            fx.make_manager_headers("u-mgr-2"),
        )
    )
    assert returned["status"] == "RETURNED"
    assert returned["revision_count"] == 1

    revised = validate_success(
        api.transition_treatment_plan(bundle["plan"]["id"], {"action": "REVISE"}, ECOLOGIST)
    )
    assert revised["status"] == "DRAFT"
    assert revised["approver_user_ids"] == []
    assert revised["submitted_by_user_id"] is None


def test_revised_aerial_plan_needs_two_fresh_approvals_to_reach_approved(api):
    """PRD §3.7: "A larvicide or adulticide plan therefore joins after one approval
    and an aerial plan only after two distinct approvers, and reaching `APPROVED`
    is what unlocks both route commitment and the issuing of spray notices."
    PRD §3.7: "The cycle `DRAFT → SUBMITTED → RETURNED → DRAFT` may run any number
    of times, and `revision_count` records how many times the plan has been sent
    back."

    Design: Difficulty/non_linear_state_machine/aerial_plan_return_revise_cycle_clears_partial_quorum
    """
    bundle = fx.setup_plan_scenario(
        treatment_type="AERIAL", approve=False,
        routes=[{
            "window_start": "2026-06-05T06:00:00.000Z",
            "window_end": "2026-06-05T09:00:00.000Z",
            "planned_acres": 40.0,
        }],
    )
    fx.plan_action(bundle["plan"]["id"], "SUBMIT", ECOLOGIST)
    fx.plan_action(bundle["plan"]["id"], "APPROVE", fx.make_manager_headers("u-mgr-1"))
    fx.plan_action(
        bundle["plan"]["id"], "RETURN", fx.make_manager_headers("u-mgr-2"),
        return_reason="Buffer map out of date",
    )
    fx.plan_action(bundle["plan"]["id"], "REVISE", ECOLOGIST)
    fx.plan_action(bundle["plan"]["id"], "SUBMIT", ECOLOGIST)

    fx.plan_action(bundle["plan"]["id"], "APPROVE", fx.make_manager_headers("u-mgr-1"))
    final = validate_success(
        api.transition_treatment_plan(
            bundle["plan"]["id"], {"action": "APPROVE"}, fx.make_manager_headers("u-mgr-2")
        )
    )

    assert final["status"] == "APPROVED"
    assert final["required_approvals"] == 2
    assert final["approver_user_ids"] == ["u-mgr-1", "u-mgr-2"]
    assert final["revision_count"] == 1
    assert final["submitted_by_user_id"] == "u-eco-1"
    assert fx.read_route(bundle["route"]["id"])["status"] == "PLANNED"
