"""Warranty handover, the two credit bases and the maintenance contract that closes out."""
from test_helpers import (
    ApiErrorId,
    api_client,
    assert_credit_preview,
    create_project,
    draft_contract,
    enroll_warranty,
    open_warranty,
    read_car,
    read_maintenance_contract,
    read_project,
    read_warranty_transition,
    record_inspection_result,
    request_inspection,
    schedule_inspection,
    set_clock,
    setup_accepted_car,
    setup_drafted_contract,
    setup_enrolled_warranty,
    setup_warranty_transition,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import SM


def _credit_world():
    """A CONTROLLER_DOOR car in warranty with a contract anchored at 2027-03-15."""
    ctx = setup_accepted_car(
        tier="CONTROLLER_DOOR",
        base_price_cents=14_000_000,
        staging_area_sqft=1200,
    )
    set_clock("2026-09-01T00:00:00Z")
    ctx["warranty_transition"] = open_warranty(ctx["car"]["id"], warranty_months=24)
    ctx["maintenance_contract"] = draft_contract(
        ctx["project"]["id"], coverage_start="2027-03-15", monthly_base_cents=45_000
    )
    return ctx


def test_the_two_credit_bases_count_the_same_span_differently():
    """Under the **30/360** basis, used for the provisional credit at enrolment, every month
    is treated as thirty days long: the day count is three hundred and sixty times the
    difference in years, plus thirty times the difference in months, plus the difference
    between the two day-of-month numbers each first capped at thirty, and the credit is the
    rate multiplied by that day count and divided by thirty.

    Under the **actual-calendar** basis, used for the final credit at contract activation,
    the day count is the exact number of calendar days between the anchor and `warranty_end`
    including any leap day, and the credit is the rate multiplied by that day count,
    multiplied by twelve, and divided by three hundred and sixty-five.

    Design: Difficulty/dual_variant_calc/warranty_credit_thirty_360_vs_actual_calendar
    """
    ctx = _credit_world()
    transition_id = ctx["warranty_transition"]["id"]
    assert ctx["warranty_transition"]["warranty_start"] == "2026-09-01T00:00:00.000Z"
    assert ctx["warranty_transition"]["warranty_end"] == "2028-09-01T00:00:00.000Z"

    # The preview counts days between *the contract's* coverage_start and warranty_end,
    # so the transition has to be attached to the contract first.
    enroll_warranty(transition_id, ctx["maintenance_contract"]["id"])

    thirty = validate_success(
        api_client.get_warranty_credit_preview(
            transition_id, SM, params={"basis": "THIRTY_360"}
        )
    )
    assert_credit_preview(thirty, "THIRTY_360")
    assert thirty["day_count"] == 526
    assert thirty["per_car_monthly_cents"] == 51_750
    assert thirty["credit_cents"] == 907_350

    calendar = validate_success(
        api_client.get_warranty_credit_preview(
            transition_id, SM, params={"basis": "ACTUAL_CALENDAR"}
        )
    )
    assert_credit_preview(calendar, "ACTUAL_CALENDAR")
    assert calendar["day_count"] == 536
    assert calendar["per_car_monthly_cents"] == 51_750
    assert calendar["credit_cents"] == 911_934

    assert thirty["credit_cents"] != calendar["credit_cents"]
    # The preview wrote nothing: the transition still sits where enrolment left it.
    assert read_warranty_transition(transition_id)["status"] == "ENROLLED"


def test_enrolment_books_the_provisional_credit_and_activation_the_final_one():
    """Activation then moves the contract `DRAFT → ACTIVE`, and for every enrolled
    transition it recomputes the credit on the actual-calendar basis into
    `final_credit_cents` and moves that transition `ENROLLED → UNDER_CONTRACT`. The
    contract's `total_final_credit_cents` is the sum of those recomputed final credits, and
    its `cars_covered` is the number of transitions now `UNDER_CONTRACT` on it. Every covered
    car advances `IN_WARRANTY → UNDER_CONTRACT`, which is the terminal state of the work
    dimension. If the project stood at `CLOSEOUT` and the contract's `cars_covered` equals
    the project's `car_count`, the project moves `CLOSEOUT → COMPLETED` and the delivery is
    finished.

    On success the contract identifier is stored on the transition, the unexpired warranty is
    valued on the provisional 30/360 day-count basis described below and written to
    `provisional_credit_cents`, the transition moves `PENDING → ENROLLED`, and the project's
    `version` increments by 1.

    Design: Difficulty/dual_variant_calc/warranty_credit_thirty_360_vs_actual_calendar
    """
    ctx = _credit_world()
    transition_id = ctx["warranty_transition"]["id"]
    contract_id = ctx["maintenance_contract"]["id"]

    enrolled = enroll_warranty(transition_id, contract_id)
    assert enrolled["status"] == "ENROLLED"
    assert enrolled["maintenance_contract_id"] == contract_id
    assert enrolled["provisional_credit_cents"] == 907_350
    assert enrolled["final_credit_cents"] == 0

    activated = validate_success(
        api_client.activate_maintenance_contract(contract_id, SM)
    )
    assert activated["status"] == "ACTIVE"
    assert activated["monthly_total_cents"] == 51_750
    assert activated["cars_covered"] == 1
    assert activated["total_final_credit_cents"] == 911_934

    final = read_warranty_transition(transition_id)
    assert final["status"] == "UNDER_CONTRACT"
    assert final["final_credit_cents"] == 911_934
    assert final["provisional_credit_cents"] != final["final_credit_cents"]

    assert read_car(ctx["car"]["id"])["work_status"] == "UNDER_CONTRACT"
    assert read_project(ctx["project"]["id"])["status"] == "COMPLETED"


def test_a_conditionally_accepted_car_cannot_enter_warranty():
    """The car must stand at `work_status` `ACCEPTED`, or the request is refused with
    `ERR_CAR_STATE_INVALID`, and its `compliance_status` must be `CODE_ACCEPTED`, or the
    request is refused with `ERR_CAR_NOT_CODE_ACCEPTED` — which is exactly why a car
    accepted only conditionally cannot enter warranty until it has been passed cleanly.

    On the compliance dimension nothing moves at all: the car remains at
    `TRIGGERS_CLEARED` and is *not* code accepted, and its code triggers are left exactly as
    they were, none of them becoming `SATISFIED`.

    Design: Difficulty/cross_entity_state_dependency/warranty_transition_depends_on_car_compliance_dimension
    """
    ctx = setup_accepted_car(
        result="CONDITIONAL", punch_list_count=3, staging_area_sqft=1200
    )
    car_id = ctx["car"]["id"]

    ruled = ctx["inspection_appointment"]
    assert ruled["status"] == "CONDITIONAL"
    assert ruled["punch_list_count"] == 3

    conditional_car = read_car(car_id)
    assert conditional_car["work_status"] == "ACCEPTED"
    assert conditional_car["compliance_status"] == "TRIGGERS_CLEARED"

    response = api_client.create_warranty_transition(
        {"car_id": car_id, "warranty_months": 24}, SM
    )
    validate_error(response, ApiErrorId.ERR_CAR_NOT_CODE_ACCEPTED, expected_status=409)

    _, meta = validate_paginated(
        api_client.list_warranty_transitions(SM, params={"car_id": car_id})
    )
    assert meta["total_count"] == 0
    assert read_car(car_id)["work_status"] == "ACCEPTED"


def test_a_clean_follow_up_pass_unlocks_the_warranty_handover():
    """The transition opens in status `PENDING` with `maintenance_contract_id` null and both
    `provisional_credit_cents` and `final_credit_cents` at zero. `warranty_start` is stamped
    from the logical clock, and `warranty_end` is derived as `warranty_start` advanced by
    `warranty_months` calendar months, clamped to the last day of the target month when the
    target month is too short to contain the same day number. The car advances `ACCEPTED →
    IN_WARRANTY` and the project's `version` increments by 1.

    Design: Difficulty/cross_entity_state_dependency/warranty_transition_depends_on_car_compliance_dimension
    """
    ctx = setup_accepted_car(
        result="CONDITIONAL", punch_list_count=3, staging_area_sqft=1200
    )
    car_id = ctx["car"]["id"]
    jurisdiction_id = ctx["jurisdiction"]["id"]

    blocked = api_client.create_warranty_transition(
        {"car_id": car_id, "warranty_months": 24}, SM
    )
    validate_error(blocked, ApiErrorId.ERR_CAR_NOT_CODE_ACCEPTED, expected_status=409)

    follow_up = request_inspection(car_id, "2026-09-10")
    schedule_inspection(jurisdiction_id, follow_up["id"], "2026-09-10T13:00:00Z")
    set_clock("2026-09-10T13:00:00Z")
    record_inspection_result(jurisdiction_id, follow_up["id"], result="PASSED")

    passed_car = read_car(car_id)
    assert passed_car["work_status"] == "ACCEPTED"
    assert passed_car["compliance_status"] == "CODE_ACCEPTED"

    transition = validate_success(
        api_client.create_warranty_transition(
            {"car_id": car_id, "warranty_months": 24}, SM
        ),
        expected_status=201,
    )
    assert transition["status"] == "PENDING"
    assert transition["maintenance_contract_id"] is None
    assert transition["provisional_credit_cents"] == 0
    assert transition["final_credit_cents"] == 0
    assert transition["warranty_start"] == "2026-09-10T13:00:00.000Z"
    assert transition["warranty_end"] == "2028-09-10T13:00:00.000Z"
    assert read_car(car_id)["work_status"] == "IN_WARRANTY"


def test_moving_the_clock_past_the_warranty_end_lapses_the_transition():
    """Setting the logical clock to a supplied `to_iso8601` instant has two standing
    consequences beyond the clock reading itself: every warranty transition in status
    `PENDING` whose `warranty_end` is at or before the new clock value moves to `LAPSED`, and
    the `downtime_posture` of every project is recomputed. The response reports the new
    `current_utc` together with `lapsed_warranty_transition_count`, the number of pending
    transitions the move expired.

    The transition must be in status `PENDING`; enrolling a transition that is already
    `ENROLLED`, already `UNDER_CONTRACT`, or `LAPSED` is refused with
    `ERR_WARRANTY_STATE_INVALID`.

    Design: Corner/state_machines/advancing_the_clock_past_warranty_end_lapses_a_pending_transition
    """
    ctx = setup_accepted_car(staging_area_sqft=1200)
    set_clock("2026-09-01T00:00:00Z")
    transition = open_warranty(ctx["car"]["id"], warranty_months=12)
    contract = draft_contract(
        ctx["project"]["id"], coverage_start="2026-10-01", monthly_base_cents=45_000
    )

    assert transition["status"] == "PENDING"
    assert transition["warranty_start"] == "2026-09-01T00:00:00.000Z"
    assert transition["warranty_end"] == "2027-09-01T00:00:00.000Z"

    clock = set_clock("2027-09-02T00:00:00Z")
    assert clock["current_utc"] == "2027-09-02T00:00:00.000Z"
    assert clock["lapsed_warranty_transition_count"] == 1

    lapsed = read_warranty_transition(transition["id"])
    assert lapsed["status"] == "LAPSED"
    assert lapsed["provisional_credit_cents"] == 0
    assert lapsed["final_credit_cents"] == 0
    assert read_car(ctx["car"]["id"])["work_status"] == "IN_WARRANTY"

    response = api_client.enroll_warranty_transition(
        transition["id"], {"maintenance_contract_id": contract["id"]}, SM
    )
    validate_error(response, ApiErrorId.ERR_WARRANTY_STATE_INVALID, expected_status=409)

    stored = read_maintenance_contract(contract["id"])
    assert stored["status"] == "DRAFT"
    assert stored["cars_covered"] == 0


def test_enrolling_into_another_projects_contract_is_refused():
    """And the contract's project must be the project that owns the transition's car, with a
    mismatch refused by `ERR_CONTRACT_PROJECT_MISMATCH`.

    Transitions can be listed and narrowed by `car_id`, by `maintenance_contract_id` or by
    `status`, and a single read returns both credit figures.

    Design: Corner/errors/enrolling_a_warranty_transition_into_another_projects_contract_is_rejected
    """
    ctx = setup_warranty_transition(warranty_months=12, staging_area_sqft=1200)
    transition_id = ctx["warranty_transition"]["id"]

    other_project = create_project(
        ctx["jurisdiction"]["id"], building_name="Brentwood Annex"
    )
    foreign_contract = draft_contract(
        other_project["id"], coverage_start="2026-10-01", monthly_base_cents=45_000
    )

    assert ctx["warranty_transition"]["status"] == "PENDING"
    assert ctx["warranty_transition"]["maintenance_contract_id"] is None

    response = api_client.enroll_warranty_transition(
        transition_id, {"maintenance_contract_id": foreign_contract["id"]}, SM
    )
    validate_error(
        response, ApiErrorId.ERR_CONTRACT_PROJECT_MISMATCH, expected_status=409
    )

    stored = read_warranty_transition(transition_id)
    assert stored["status"] == "PENDING"
    assert stored["maintenance_contract_id"] is None

    contract = read_maintenance_contract(foreign_contract["id"])
    assert contract["status"] == "DRAFT"
    assert contract["cars_covered"] == 0

    _, meta = validate_paginated(
        api_client.list_warranty_transitions(
            SM, params={"maintenance_contract_id": foreign_contract["id"]}
        )
    )
    assert meta["total_count"] == 0
    assert read_car(ctx["car"]["id"])["work_status"] == "IN_WARRANTY"
    assert read_project(ctx["project"]["id"])["status"] == "CLOSEOUT"


def test_activating_a_contract_with_nothing_enrolled_is_refused():
    """At least one warranty transition on the contract must be in status `ENROLLED`, and an
    activation with none is refused with `ERR_NO_ENROLLED_TRANSITIONS` rather than producing
    a zero-car contract.

    A new contract opens in status `DRAFT` with `monthly_total_cents`, `cars_covered` and
    `total_final_credit_cents` all at zero, and its lifecycle is simply `DRAFT` then `ACTIVE`.

    Design: Corner/errors/activating_a_contract_with_no_enrolled_transitions_is_rejected
    """
    ctx = setup_drafted_contract(
        coverage_start="2026-09-01", monthly_base_cents=45_000, staging_area_sqft=1200
    )
    contract = ctx["maintenance_contract"]
    assert contract["status"] == "DRAFT"
    assert contract["cars_covered"] == 0
    assert contract["total_final_credit_cents"] == 0

    response = api_client.activate_maintenance_contract(contract["id"], SM)
    validate_error(
        response, ApiErrorId.ERR_NO_ENROLLED_TRANSITIONS, expected_status=409
    )

    stored = read_maintenance_contract(contract["id"])
    assert stored["status"] == "DRAFT"
    assert stored["cars_covered"] == 0
    assert read_project(ctx["project"]["id"])["status"] != "COMPLETED"


def test_activating_an_already_active_contract_is_refused():
    """The contract must be in status `DRAFT`; activating a contract that is already
    `ACTIVE` is refused with `ERR_CONTRACT_STATE_INVALID`.

    The covered set is exactly the transitions pointing at this contract whose status is
    `ENROLLED`: transitions still `PENDING` because they were never enrolled, transitions
    that have `LAPSED`, and transitions already `UNDER_CONTRACT` from an earlier activation
    are all excluded.

    Design: Corner/errors/activating_an_already_active_maintenance_contract_is_rejected
    """
    ctx = setup_enrolled_warranty(
        warranty_months=12, coverage_start="2026-09-01", staging_area_sqft=1200
    )
    contract_id = ctx["maintenance_contract"]["id"]
    transition_id = ctx["warranty_transition"]["id"]
    assert ctx["warranty_transition"]["status"] == "ENROLLED"
    assert ctx["warranty_transition"]["maintenance_contract_id"] == contract_id

    activated = validate_success(
        api_client.activate_maintenance_contract(contract_id, SM)
    )
    assert activated["status"] == "ACTIVE"
    assert activated["cars_covered"] == 1
    assert read_warranty_transition(transition_id)["status"] == "UNDER_CONTRACT"
    assert read_car(ctx["car"]["id"])["work_status"] == "UNDER_CONTRACT"
    assert read_project(ctx["project"]["id"])["status"] == "COMPLETED"

    response = api_client.activate_maintenance_contract(contract_id, SM)
    validate_error(response, ApiErrorId.ERR_CONTRACT_STATE_INVALID, expected_status=409)

    stored = read_maintenance_contract(contract_id)
    assert stored["status"] == "ACTIVE"
    assert stored["cars_covered"] == 1
    assert read_project(ctx["project"]["id"])["status"] == "COMPLETED"
    assert read_warranty_transition(transition_id)["status"] == "UNDER_CONTRACT"


