"""The two parallel lift-plan dimensions, the cyclic permit and gear lifecycles,
and the conditional cascades that reach across entities."""

import pytest

from test_helpers import (
    ApiErrorId,
    DISPATCHER,
    LIFT_DIRECTOR,
    SAFETY_MANAGER,
    approve_permit,
    approve_plan,
    build_critical_world,
    build_standard_world,
    make_engineer_headers,
    make_operator_headers,
    new_serviceable_gear,
    open_permit,
    open_plan,
    read_assignment,
    read_crane,
    read_gear,
    read_permit,
    read_plan,
    read_review,
    setup_configured_plan,
    setup_mobilized_standard_plan,
    setup_stamped_critical_plan,
    submit_permit,
    validate_error,
    validate_success,
)


def test_a_new_lift_plan_opens_on_both_initial_states_at_once(api):
    """PRD 3.3: "A newly opened plan sits at `DRAFT` on its readiness dimension and
    `NOT_MOBILIZED` on its operational dimension, with `lift_class` at
    `NOT_CLASSIFIED`, `bearing_variant` at `NONE`, and `crane_id`, `operator_id` and
    `rigger_id` all null."
    PRD 3.3: "The plan's `customer_id` is not supplied by the caller — it is copied
    from the owning site's `customer_id` at creation and never changes afterwards,
    even if the site is later re-pointed."

    Design: Corner/state_machines/new_lift_plan_starts_draft_and_not_mobilized
    """
    world = build_standard_world()
    plan = validate_success(api.create_lift_plan(
        {"site_id": world["site_id"], "job_reference": "JOB-9200",
         "window_start": "2026-09-10T06:00:00Z", "window_end": "2026-09-10T16:00:00Z",
         "load_weight_lb": 60_000}, DISPATCHER), 201)

    assert plan["plan_status"] == "DRAFT"
    assert plan["field_status"] == "NOT_MOBILIZED"
    assert plan["lift_class"] == "NOT_CLASSIFIED"
    assert plan["bearing_variant"] == "NONE"
    assert plan["crane_id"] is None
    assert plan["operator_id"] is None
    assert plan["rigger_id"] is None
    assert plan["rigging_verified"] is False
    assert plan["net_capacity_lb"] == 0
    assert plan["customer_id"] == world["cust_id"]


def test_a_second_site_survey_is_not_idempotent(api):
    """PRD 3.3: "The site survey is a dispatch action that advances the plan from
    `DRAFT` to `SURVEYED`, and it is the only route out of `DRAFT` other than
    cancellation."
    PRD 2.7: "The target resource's own current state is a legal starting state for
    the requested transition, producing `ERR_INVALID_PLAN_STATE`,
    `ERR_INVALID_FIELD_STATE`, `ERR_INVALID_GEAR_STATE`, `ERR_INVALID_REVIEW_STATE`,
    `ERR_INVALID_PERMIT_STATE` or `ERR_INVALID_INVOICE_STATE` at HTTP 409."
    PRD 3.3: "It carries three required inputs: `confirmed_soil_bearing_capacity_psf`,
    the allowable bearing pressure the surveyor actually measured, which overwrites
    the site's stored `soil_bearing_capacity_psf`; `access_notes`, recorded onto the
    site; and `mat_inventory_available`, a boolean recording whether crane mats are
    already stocked at that address, likewise recorded onto the site."

    Design: Corner/state_machines/second_site_survey_on_surveyed_plan_returns_invalid_plan_state
    """
    world = build_standard_world(site={"soil_bearing_capacity_psf": 2000})
    plan = open_plan(world, job_reference="JOB-9201")
    surveyed = validate_success(api.site_survey(
        plan["id"], {"confirmed_soil_bearing_capacity_psf": 3500,
                     "access_notes": "apron", "mat_inventory_available": True}, DISPATCHER))
    assert surveyed["plan_status"] == "SURVEYED"

    validate_error(api.site_survey(
        plan["id"], {"confirmed_soil_bearing_capacity_psf": 9999,
                     "access_notes": "second pass", "mat_inventory_available": False},
        DISPATCHER), ApiErrorId.ERR_INVALID_PLAN_STATE.value, 409)

    site = validate_success(api.get_site(world["site_id"], DISPATCHER))
    assert site["soil_bearing_capacity_psf"] == 3500
    assert site["mat_inventory_available"] is True


def test_cancelling_an_already_cancelled_plan_is_refused(api):
    """PRD 3.9: "A plan can be abandoned at any point before it reaches its own
    terminal states: cancellation is legal from every readiness posture except
    `CLOSED` and `CANCELLED`, and either a `Dispatcher` or a `LiftDirector` may do it,
    supplying a `reason` that is stored as the plan's `cancellation_reason`."

    Design: Corner/state_machines/cancelling_an_already_cancelled_plan_returns_invalid_plan_state
    """
    world = build_standard_world()
    plan = open_plan(world, job_reference="JOB-9202")
    cancelled = validate_success(api.cancel_lift_plan(
        plan["id"], {"reason": "scope withdrawn"}, DISPATCHER))
    assert cancelled["plan_status"] == "CANCELLED"
    assert cancelled["cancellation_reason"] == "scope withdrawn"

    validate_error(api.cancel_lift_plan(plan["id"], {"reason": "second attempt"},
                                        LIFT_DIRECTOR),
                   ApiErrorId.ERR_INVALID_PLAN_STATE.value, 409)
    assert read_plan(plan["id"])["cancellation_reason"] == "scope withdrawn"


def test_a_pending_engineering_plan_cannot_take_the_lift_director_shortcut(api):
    """PRD 3.8: "Approval takes no payload at all and moves the plan `CONFIGURED →
    APPROVED`, but only when three things hold at once: the plan's readiness dimension
    really is `CONFIGURED`, its `lift_class` really is `STANDARD` — a critical or
    engineered-critical plan can never be approved this way, since it reaches
    `APPROVED` only through an engineering stamp — and its `rigging_verified` is
    true."

    Design: Corner/state_machines/approving_a_pending_engineering_plan_returns_invalid_plan_state
    """
    world = build_critical_world(with_engineers=False)
    ctx = setup_configured_plan(world, plan_overrides={"job_reference": "JOB-9203",
                                                       "sail_area_sqft": 150.0})
    assert ctx["plan"]["plan_status"] == "PENDING_ENGINEERING"

    validate_error(api.approve_lift_plan(ctx["plan_id"], LIFT_DIRECTOR),
                   ApiErrorId.ERR_INVALID_PLAN_STATE.value, 409)
    assert read_plan(ctx["plan_id"])["plan_status"] == "PENDING_ENGINEERING"


def test_mobilizing_before_release_is_refused(api):
    """PRD 3.8: "`MOBILIZE` moves `NOT_MOBILIZED → MOBILIZED` and additionally
    requires that the plan's readiness dimension is `RELEASED` and that the crane is
    not `OUT_OF_SERVICE`; it causes the crane's derived `status` to be recomputed to
    `IN_SERVICE`."
    PRD 2.7: "The target resource's own current state is a legal starting state for
    the requested transition, producing `ERR_INVALID_PLAN_STATE`,
    `ERR_INVALID_FIELD_STATE`, `ERR_INVALID_GEAR_STATE`, `ERR_INVALID_REVIEW_STATE`,
    `ERR_INVALID_PERMIT_STATE` or `ERR_INVALID_INVOICE_STATE` at HTTP 409."
    PRD 3.1: "Failing that, it is `RESERVED` if `reserved_hours_total` is greater than
    zero."

    Design: Corner/state_machines/mobilize_before_release_returns_invalid_plan_state
    """
    world = build_standard_world()
    ctx = setup_configured_plan(world, plan_overrides={"job_reference": "JOB-9204"})
    approved = approve_plan(ctx["plan_id"])
    assert approved["plan_status"] == "APPROVED"

    validate_error(api.set_field_status(ctx["plan_id"], {"action": "MOBILIZE"},
                                        make_operator_headers(world["op_id"])),
                   ApiErrorId.ERR_INVALID_PLAN_STATE.value, 409)

    assert read_plan(ctx["plan_id"])["field_status"] == "NOT_MOBILIZED"
    assert read_crane(world["crane_id"])["status"] == "RESERVED"


def test_an_open_standby_event_blocks_the_start_of_the_lift(api):
    """PRD 3.8: "A new event opens at `OPEN` with `ended_at` null,
    `raw_duration_hours` at 0 and `forced_wind_hold` false."
    PRD 3.8: "Three of those five — `START_LIFT`, `RESUME` and `SECURE` —
    additionally require that **no** standby event on the plan is currently `OPEN`;
    an open hold blocks all three. A request whose current operational posture is not
    a legal starting point for the requested action, or which is blocked by an open
    standby, is refused with `ERR_INVALID_FIELD_STATE`."

    Design: Corner/state_machines/start_lift_with_an_open_standby_event_returns_invalid_field_state
    """
    world = build_standard_world()
    ctx = setup_mobilized_standard_plan(world, plan_overrides={"job_reference": "JOB-9205"})

    event = validate_success(api.create_standby_event(
        {"lift_plan_id": ctx["plan_id"], "cause": "CUSTOMER_DELAY",
         "started_at": "2026-09-10T07:00:00Z"}, SAFETY_MANAGER), 201)
    assert event["status"] == "OPEN"
    assert event["forced_wind_hold"] is False

    validate_error(api.set_field_status(ctx["plan_id"], {"action": "START_LIFT"},
                                        make_operator_headers(world["op_id"])),
                   ApiErrorId.ERR_INVALID_FIELD_STATE.value, 409)
    assert read_plan(ctx["plan_id"])["field_status"] == "MOBILIZED"


def test_gear_retirement_leaves_a_mobilized_plan_alone(api):
    """PRD 3.2: "The third hop reaches every lift plan that owned one of those voided
    commitments, whose readiness dimension stands at `CONFIGURED`,
    `PENDING_ENGINEERING`, `APPROVED` or `RELEASED`, and whose operational dimension
    is still `NOT_MOBILIZED`; each such plan is demoted back to `SURVEYED` with
    `rigging_verified` cleared to false."
    PRD 3.2: "A plan whose crew is already mobilized, lifting, held or secured is left
    alone at every hop."
    PRD 3.2: "The second hop voids every commitment of that gear that was still
    active, moving each to `VOIDED` and recomputing the gear's
    `committed_assignment_count`."

    Design: Corner/state_machines/gear_retirement_cascade_skips_a_plan_that_is_already_mobilized
    """
    world = build_standard_world()
    ctx = setup_mobilized_standard_plan(world, plan_overrides={"job_reference": "JOB-9206"})
    assert ctx["plan"]["field_status"] == "MOBILIZED"

    retired = validate_success(api.retire_rigging_gear(
        world["gear_id"], {"reason": "eye deformation found at pre-lift walk"},
        SAFETY_MANAGER))
    assert retired["status"] == "RETIRED"
    assert retired["committed_assignment_count"] == 0
    assert read_assignment(ctx["ga_id"])["status"] == "VOIDED"

    plan = read_plan(ctx["plan_id"])
    assert plan["plan_status"] == "RELEASED", "the demotion hop must not fire"
    assert plan["field_status"] == "MOBILIZED"


def test_pulling_a_crane_out_of_service_demotes_its_plan_and_suspends_the_permit(api):
    """PRD 3.1: "Pulling a machine out of service is a `SafetyManager` action that
    takes a `reason` and is legal from either `AVAILABLE` or `RESERVED`. It sets
    `out_of_service_flag` true and moves `status` to `OUT_OF_SERVICE`, and it launches
    a three-deep cascade. The second hop reaches every lift plan on that crane whose
    readiness dimension is `APPROVED` or `RELEASED` **and** whose operational
    dimension is still `NOT_MOBILIZED`, demoting each of them back to `CONFIGURED`.
    The third hop reaches every permit on those demoted plans that stood at `APPROVED`
    and moves it to `SUSPENDED`."
    PRD 3.7: "Its `permit_fee_cents` is likewise a base fee by type — 85,000 cents for
    a `ROAD_CLOSURE`, 45,000 cents for an `OVERSIZE_ESCORT`, and 25,000 cents for a
    `CRANE_PLACEMENT` — plus a further 60,000 cents when `escort_required` is true."

    Design: Corner/state_machines/crane_out_of_service_demotes_released_plan_and_suspends_its_permit
    """
    world = build_standard_world()
    ctx = setup_configured_plan(world, plan_overrides={"job_reference": "JOB-9207",
                                                       "road_closure_requested": True})
    assert ctx["plan"]["escort_required"] is False
    assert ctx["plan"]["permit_required"] is True

    permit = open_permit(ctx["plan_id"], "ROAD_CLOSURE", world=world)
    assert permit["permit_fee_cents"] == 85_000
    assert permit["required_lead_days"] == 10
    submit_permit(permit["id"])
    approve_permit(permit["id"], "NJH-2026-0042")

    approve_plan(ctx["plan_id"])
    released = validate_success(api.release_lift_plan(ctx["plan_id"], LIFT_DIRECTOR))
    assert released["plan_status"] == "RELEASED"

    crane = validate_success(api.crane_out_of_service(
        world["crane_id"], {"reason": "hydraulic leak on the number 3 outrigger"},
        SAFETY_MANAGER))
    assert crane["status"] == "OUT_OF_SERVICE"
    assert read_plan(ctx["plan_id"])["plan_status"] == "CONFIGURED"
    assert read_permit(permit["id"])["status"] == "SUSPENDED"


def test_a_denied_permit_can_be_refiled_through_the_same_endpoint(api):
    """PRD 3.7: "Filing the application with the authority is a separate act, legal
    from `DRAFT`, from `DENIED` and from `SUSPENDED` — the last two are what make the
    permit lifecycle cyclic, since a refused or suspended application can be re-filed
    without being re-created."
    PRD 3.7: "A denial moves it `SUBMITTED → DENIED`, stamps `decision_at`, and stores
    the supplied `reason` as `denial_reason`; from there the application can be
    re-filed and the cycle `DRAFT → SUBMITTED → DENIED → SUBMITTED` may repeat."
    PRD 3.7: "A successful filing moves the permit to `SUBMITTED` and stamps
    `submitted_at` with the logical clock; when the prior posture was `DENIED`, the
    stale `denial_reason` is cleared back to null in the same step."

    Design: Corner/state_machines/denied_permit_resubmitted_cycles_back_to_submitted
    """
    world = build_standard_world()
    plan = open_plan(world, job_reference="JOB-9208")
    permit = open_permit(plan["id"], "CRANE_PLACEMENT", world=world)
    assert permit["required_lead_days"] == 3
    assert permit["permit_fee_cents"] == 25_000

    assert submit_permit(permit["id"])["status"] == "SUBMITTED"

    denied = validate_success(api.record_permit_decision(
        permit["id"], {"decision": "DENY", "reason": "sidewalk closure plan missing"},
        DISPATCHER))
    assert denied["status"] == "DENIED"
    assert denied["denial_reason"] == "sidewalk closure plan missing"

    refiled = validate_success(api.submit_permit(permit["id"], DISPATCHER))
    assert refiled["status"] == "SUBMITTED"
    assert refiled["denial_reason"] is None

    granted = validate_success(api.record_permit_decision(
        permit["id"], {"decision": "APPROVE", "agency_reference": "NJH-2026-0099"},
        DISPATCHER))
    assert granted["status"] == "APPROVED"
    assert granted["agency_reference"] == "NJH-2026-0099"


def test_quarantined_gear_returns_to_service_through_a_repair_pass(api):
    """PRD 3.2: "A `FAIL` moves the gear to `QUARANTINED`."
    PRD 3.2: "A `REPAIR_PASS` also lands on `SERVICEABLE` from any of those three
    postures, but it additionally increments `repair_count` by one and therefore
    permanently lowers the gear's rating."
    PRD 3.2: "The derate multiplier is one minus five hundredths for each recorded
    repair, but never allowed to fall below seventy hundredths — that is, the greater
    of the two. The gear's `effective_wll_lb` is then the manufacturer's
    `rated_wll_lb` multiplied by that multiplier, **floored** to a whole pound."

    Design: Corner/state_machines/quarantined_gear_returns_to_serviceable_through_repair_pass
    """
    gear = new_serviceable_gear()
    failed = validate_success(api.create_gear_inspection(
        {"gear_id": gear["id"], "result": "FAIL", "inspector_note": "kinked lay"},
        SAFETY_MANAGER), 201)
    assert failed["resulting_status"] == "QUARANTINED"
    assert failed["repair_count_after"] == 0

    repaired = validate_success(api.create_gear_inspection(
        {"gear_id": gear["id"], "result": "REPAIR_PASS",
         "inspector_note": "eye re-spliced and proof tested"}, SAFETY_MANAGER), 201)
    assert repaired["resulting_status"] == "SERVICEABLE"
    assert repaired["repair_count_after"] == 1

    after = read_gear(gear["id"])
    assert after["status"] == "SERVICEABLE"
    assert after["rated_wll_lb"] == 30_000
    assert after["effective_wll_lb"] == 28_500
    assert after["repair_count"] == 1


def test_a_second_stamp_on_a_stamped_review_is_refused(api):
    """PRD 3.6: "The decision carries an `action` and an optional `note`, and is only
    legal while the review stands at `UNDER_REVIEW`; any other posture is refused with
    `ERR_INVALID_REVIEW_STATE`."
    PRD 3.6: "A successful stamp moves the review `UNDER_REVIEW → STAMPED`, writes the
    stamping engineer's identifier into `stamped_by_personnel_id`, records the `note`
    as `decision_note`, and then runs the `FINAL_ENGINEERED` ground-bearing variant of
    §3.5."

    Design: Corner/state_machines/stamping_an_already_stamped_review_returns_invalid_review_state
    """
    world = build_critical_world()
    ctx = setup_stamped_critical_plan(world, plan_overrides={"job_reference": "JOB-9209",
                                                             "sail_area_sqft": 150.0})
    assert ctx["review"]["status"] == "STAMPED"
    assert ctx["review"]["stamped_by_personnel_id"] == world["eng_b_id"]

    validate_error(api.decide_engineering_review(
        ctx["review_id"], {"action": "STAMP", "note": "second stamp"},
        make_engineer_headers(world["eng_b_id"])),
        ApiErrorId.ERR_INVALID_REVIEW_STATE.value, 409)

    assert read_review(ctx["review_id"])["stamped_by_personnel_id"] == world["eng_b_id"]
    assert read_plan(ctx["plan_id"])["plan_status"] == "APPROVED"


def test_returning_a_crane_to_service_re_derives_reserved_rather_than_available(api):
    """PRD 3.1: "Returning a machine to service requires
    `new_annual_inspection_expires_on` strictly after the logical clock; it clears
    `out_of_service_flag`, writes the fresh date onto `annual_inspection_expires_on`,
    and then re-derives `status` by the precedence above — so a machine that still
    holds reservations lands on `RESERVED` rather than `AVAILABLE`."
    PRD 3.1: "The second hop reaches every lift plan on that crane whose readiness
    dimension is `APPROVED` or `RELEASED` **and** whose operational dimension is still
    `NOT_MOBILIZED`, demoting each of them back to `CONFIGURED`."

    Design: Corner/state_machines/crane_return_to_service_recomputes_posture_to_reserved_not_available
    """
    world = build_standard_world()
    ctx = setup_configured_plan(world, plan_overrides={"job_reference": "JOB-9210"})

    pulled = validate_success(api.crane_out_of_service(
        world["crane_id"], {"reason": "annual inspection pulled forward"}, SAFETY_MANAGER))
    assert pulled["status"] == "OUT_OF_SERVICE"
    assert pulled["reserved_hours_total"] == pytest.approx(10.0)

    back = validate_success(api.crane_return_to_service(
        world["crane_id"], {"new_annual_inspection_expires_on": "2027-12-31T00:00:00Z"},
        SAFETY_MANAGER))
    assert back["out_of_service_flag"] is False
    assert back["annual_inspection_expires_on"].startswith("2027-12-31")
    assert back["status"] == "RESERVED", "posture precedence, not a reset to AVAILABLE"
    assert back["reserved_hours_total"] == pytest.approx(10.0)
    assert read_plan(ctx["plan_id"])["plan_status"] == "CONFIGURED"
