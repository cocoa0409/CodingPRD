"""Antitrust training: curriculum targeting, the waiver audit record, and the
lazy strict expiry that decides whether the training gate lets a write through.
"""
from test_helpers import (
    ADMIN, COUNSEL, ApiErrorId, assert_instant_equals,
    create_contact_payload, create_training_assignment_payload,
    define_curriculum, log_contact, make_employee_headers, read_assignment,
    read_business_unit, read_employee, register_business_unit,
    register_employee, set_clock, validate_error, validate_paginated,
    validate_success, waive_assignment,
)

CLOCK_COMPLETION = "2026-08-01T00:00:00Z"
CLOCK_AT_EXPIRY = "2026-08-31T00:00:00Z"


def _setup_lapsed_sales_and_untrained_legal(api):
    """A SALES completion whose 30-day validity ends exactly at the clock, plus
    a LEGAL colleague who has never trained at all."""
    set_clock(CLOCK_COMPLETION)
    unit = register_business_unit(exposure_budget_points=200)
    sales = register_employee(unit["id"], role_category="SALES")
    legal = register_employee(unit["id"], role_category="LEGAL")
    curriculum = define_curriculum(
        code="AT-SALES-030", title="Monthly Refresher",
        target_role_categories=["SALES", "PRICING"], duration_minutes=45,
        validity_days=30, is_mandatory=True)
    assignment = validate_success(api.create_training_assignment(
        create_training_assignment_payload(
            sales["id"], curriculum["id"], "2026-08-15T00:00:00Z"), ADMIN), 201)
    sales_headers = make_employee_headers(sales["id"])
    validate_success(api.start_training(assignment["id"], sales_headers))
    validate_success(api.complete_training(
        assignment["id"], {"score": 91}, sales_headers))
    set_clock(CLOCK_AT_EXPIRY)
    return unit, sales, legal, assignment


def test_sales_contact_log_refused_when_the_clock_reaches_the_expiry_instant(api):
    """PRD §3.2: "A `COMPLETED` assignment whose `expires_at` has been reached
    moves to the terminal `EXPIRED` at the start of the next request that reads
    or validates it, and the comparison is **strict** in the sense that an
    assignment is already expired at the instant the clock reads exactly its
    `expires_at` — currency requires the clock to be strictly earlier than the
    expiry instant."
    PRD §2.7: "**Training currency.** The acting or nominated employee's
    `training_status` is `CURRENT` — otherwise `ERR_TRAINING_NOT_CURRENT`, HTTP
    422."

    Design: Difficulty/cross_entity_state_dependency/contact_log_requires_current_training_only_for_sales_and_pricing
    """
    unit, sales, _legal, assignment = _setup_lapsed_sales_and_untrained_legal(api)

    payload = create_contact_payload(
        unit["id"], sales["id"], contact_channel="TRADE_SHOW",
        topic_tags=["CAPACITY"], occurred_at="2026-08-30T10:00:00Z")
    resp = api.create_contact(payload, make_employee_headers(sales["id"]))

    validate_error(resp, ApiErrorId.ERR_TRAINING_NOT_CURRENT.value)
    assert resp.status_code == 422

    stored = read_assignment(assignment["id"])
    assert_instant_equals(stored["expires_at"], "2026-08-31T00:00:00.000Z",
                          "TrainingAssignment.expires_at")
    assert stored["status"] == "EXPIRED", (
        "the completion is already expired at exactly its expiry instant")
    assert read_employee(sales["id"])["training_status"] == "EXPIRED"


def test_legal_colleague_logs_the_same_contact_because_the_gate_is_skipped(api):
    """PRD §2.7: "This rule is **conditional**: it is skipped entirely when the
    employee's `role_category` is neither `SALES` nor `PRICING`."
    PRD §3.6: "The raw score starts at a base of 4 points."
    PRD §3.6: "Channel points follow: 3 for an unstructured in-person meeting, 2
    for a trade show, 1 for a phone call, 1 for an email, and 0 for formal
    written correspondence."
    PRD §3.6: "Topic-tag points are summed — 2 for `CAPACITY`, 2 for `BID`, 3
    for `CUSTOMER_ALLOCATION`, 3 for `TERRITORY`, 0 for `STANDARDS`, and 1 for
    `BENCHMARKING` — and that sum alone is capped at 5, with an empty tag array
    contributing 0."
    PRD §3.6: "Role points close the raw score: 2 for a `SALES` employee, 3 for
    `PRICING`, 0 for `LEGAL`, and 1 for `OTHER`."

    Design: Difficulty/cross_entity_state_dependency/contact_log_requires_current_training_only_for_sales_and_pricing
    """
    unit, _sales, legal, _assignment = _setup_lapsed_sales_and_untrained_legal(api)

    payload = create_contact_payload(
        unit["id"], legal["id"], contact_channel="TRADE_SHOW",
        topic_tags=["CAPACITY"], occurred_at="2026-08-30T10:00:00Z")
    data = validate_success(
        api.create_contact(payload, make_employee_headers(legal["id"])), 201)

    assert read_employee(legal["id"])["training_status"] == "NONE", (
        "an employee who never completed a targeting curriculum reads NONE")
    assert data["status"] == "LOGGED"
    # base 4 + trade show 2 + CAPACITY 2 + LEGAL 0, band multiplier 1.0 at LOW
    assert data["exposure_points_charged"] == 8.00
    assert read_business_unit(unit["id"])["exposure_points"] == 8.00


def test_curriculum_cannot_be_assigned_outside_its_target_role_categories(api):
    """PRD §3.2: "The assignment is refused with `ERR_CURRICULUM_ROLE_MISMATCH`
    when the employee's `role_category` is not among the curriculum's
    `target_role_categories` — a pricing curriculum cannot be dropped on a
    warehouse supervisor to inflate a completion statistic."
    PRD §3.2: "Assigning a curriculum to a person creates an assignment carrying
    `employee_id`, `curriculum_id` and a `due_at` completion deadline, and the
    assignment opens in `ASSIGNED`."

    Design: Corner/validations/curriculum_role_mismatch_on_assignment_is_refused
    """
    set_clock()
    unit = register_business_unit()
    legal = register_employee(unit["id"], role_category="LEGAL")
    sales = register_employee(unit["id"], role_category="SALES")
    curriculum = define_curriculum(target_role_categories=["SALES", "PRICING"])

    refused = api.create_training_assignment(
        create_training_assignment_payload(legal["id"], curriculum["id"]), ADMIN)
    validate_error(refused, ApiErrorId.ERR_CURRICULUM_ROLE_MISMATCH.value)
    assert refused.status_code == 422

    accepted = validate_success(api.create_training_assignment(
        create_training_assignment_payload(sales["id"], curriculum["id"]), ADMIN), 201)
    assert accepted["status"] == "ASSIGNED"

    _rows, meta = validate_paginated(api.list_training_assignments(
        COUNSEL, params={"employee_id": legal["id"]}))
    assert meta["total_count"] == 0, "the refused assignment persists nothing"


def test_waived_assignment_never_satisfies_the_training_gate(api):
    """PRD §3.2: "A waiver is an audit record, never a substitute for training:
    a `WAIVED` assignment contributes nothing to training currency."
    PRD §3.2: "Counsel may instead waive an assignment that is still `ASSIGNED`
    or `IN_PROGRESS`, recording a `reason` into `waiver_reason` and driving the
    assignment to the terminal `WAIVED`."
    PRD §3.2: "When the employee has never completed a mandatory curriculum
    targeting their category at all, the status is `NONE`."

    Design: Corner/endpoints/training_waiver_never_satisfies_the_training_gate
    """
    set_clock()
    unit = register_business_unit(exposure_budget_points=200)
    sales = register_employee(unit["id"], role_category="SALES")
    curriculum = define_curriculum(target_role_categories=["SALES", "PRICING"])
    assignment = validate_success(api.create_training_assignment(
        create_training_assignment_payload(sales["id"], curriculum["id"]), ADMIN), 201)

    waived = waive_assignment(assignment["id"])
    assert waived["status"] == "WAIVED"
    assert read_employee(sales["id"])["training_status"] == "NONE"

    resp = api.create_contact(
        create_contact_payload(unit["id"], sales["id"]),
        make_employee_headers(sales["id"]))
    validate_error(resp, ApiErrorId.ERR_TRAINING_NOT_CURRENT.value)
    assert resp.status_code == 422
    assert read_business_unit(unit["id"])["exposure_points"] == 0.00
