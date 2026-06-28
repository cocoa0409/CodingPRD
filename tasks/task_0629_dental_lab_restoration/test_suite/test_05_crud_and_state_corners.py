"""Breadth (corner) tests: entity creation/defaults/validation, not-found and FK
resolution, computed-field input rejection, listing/pagination, and invalid /
initial / precondition state transitions.
"""
import pytest
from test_helpers import (
    api_client, get_success_data, validate_success, validate_error, validate_paginated,
    is_valid_uuid,
    TEST_USERS, make_doctor_headers,
    create_doctor_payload, create_case_payload, create_restoration_payload,
    create_material_payload, create_mill_job_payload,
    create_doctor, create_material, create_machine, create_case, create_restoration,
    set_clock,
)
from test_helpers.fixtures import list_units, get_case

ADMIN = TEST_USERS["labadmin_headers"]
TECH = TEST_USERS["labtech_headers"]
SCHED = TEST_USERS["scheduler_headers"]


# ─── entities ────────────────────────────────────────────────────────
def test_create_doctor_returns_201_with_zero_counters(api):
    """PRD §3.1: "Each doctor also carries two computed counters that start at
    zero: completed_case_count, the number of that doctor's cases that have
    reached DELIVERED, and account_credit_cents, the running ledger of un-applied
    account credit owed to them."

    Design: Corner/entities/create_doctor_returns_201_with_defaults
    """
    res = api.create_doctor(create_doctor_payload(), ADMIN)
    doctor = validate_success(res, 201)
    assert doctor["completed_case_count"] == 0
    assert doctor["account_credit_cents"] == 0
    assert is_valid_uuid(doctor["id"]), "id must be a bare UUID with no prefix"


def test_get_case_not_found(api):
    """PRD §2.5: "the first identifier that does not resolve to an existing
    resource causes the request to be rejected with ERR_NOT_FOUND (HTTP 404)."

    Design: Corner/entities/get_case_not_found_returns_404
    """
    res = api.get_case("00000000-0000-4000-8000-000000000000", ADMIN)
    validate_error(res, "ERR_NOT_FOUND")


def test_create_case_missing_intake_method(api):
    """PRD §2.9: "and finally, as the lowest-priority schema gate, that the
    request body is well-formed - required fields present, enum values legal,
    integers in range - failing which the response is ERR_INVALID_REQUEST (HTTP
    400)."

    Design: Corner/entities/create_case_missing_required_field_returns_invalid_request
    """
    doctor = create_doctor()
    res = api.create_case({"doctor_id": doctor["id"]}, TECH)
    validate_error(res, "ERR_INVALID_REQUEST")


def test_create_case_default_is_rush_false(api):
    """PRD §3.2: "an optional is_rush flag (defaulting to false) indicating the
    doctor asked for rush turnaround".

    Design: Corner/entities/create_case_default_is_rush_false
    """
    doctor = create_doctor()
    res = api.create_case(
        create_case_payload(doctor["id"], intake_method="RX_PAPER"), TECH)
    case = validate_success(res, 201)
    assert case["is_rush"] is False


def test_create_case_invalid_intake_method_enum(api):
    """PRD §3.2: "Creating one records the prescribing doctor_id, an intake_method
    of RX_PAPER, IMPRESSION, or INTRAORAL_SCAN". PRD §2.9: "and finally, as the
    lowest-priority schema gate, that the request body is well-formed - required
    fields present, enum values legal, integers in range - failing which the
    response is ERR_INVALID_REQUEST (HTTP 400)."

    Design: Corner/entities/create_case_invalid_enum_intake_method_rejected
    """
    doctor = create_doctor()
    res = api.create_case(
        create_case_payload(doctor["id"], intake_method="TELEPATHY"), TECH)
    validate_error(res, "ERR_INVALID_REQUEST")


def test_create_case_unknown_doctor_fk(api):
    """PRD §2.5: "the parent identifier in the path is checked before any child or
    foreign-key reference, and the first identifier that does not resolve to an
    existing resource causes the request to be rejected with ERR_NOT_FOUND (HTTP
    404)."

    Design: Corner/entities/create_case_unknown_doctor_fk_returns_not_found
    """
    res = api.create_case(
        create_case_payload("00000000-0000-4000-8000-000000000001",
                            intake_method="RX_PAPER"), TECH)
    validate_error(res, "ERR_NOT_FOUND")


def test_restoration_unit_price_zero_before_submit(api):
    """PRD §3.2: "A restoration's unit_price_cents is left at 0 on creation and is
    only computed later, when the case is submitted."

    Design: Corner/entities/computed_unit_price_input_ignored
    """
    set_clock()
    doctor = create_doctor()
    material = create_material(base_unit_price_cents=12000, fabrication_process="MILLED")
    case = create_case(doctor["id"])
    res = api.create_restoration(
        case["id"], create_restoration_payload(material["id"], restoration_type="CROWN",
                                               unit_count=1), TECH)
    rest = validate_success(res, 201)
    assert rest["unit_price_cents"] == 0


def test_list_doctors_pagination_envelope(api):
    """PRD §2.3: "Paginated list responses include the following fields in the
    meta object of the response envelope: limit, offset, total_count, and
    has_more."

    Design: Corner/entities/list_doctors_pagination_envelope
    """
    create_doctor()
    create_doctor()
    data, meta = validate_paginated(api.list_doctors(ADMIN, params={"limit": 1, "offset": 0}))
    assert meta["total_count"] >= 2
    assert meta["has_more"] is True
    assert len(data) == 1


def test_pagination_limit_above_max_rejected(api):
    """PRD §2.3: "The limit parameter specifies the maximum number of items to
    return; if not provided it defaults to 10, with a minimum of 1 and a maximum
    of 100. ... A limit or offset outside these bounds is rejected with
    ERR_PAGINATION_INVALID."

    Design: Corner/entities/pagination_limit_out_of_range_rejected
    """
    res = api.list_doctors(ADMIN, params={"limit": 999, "offset": 0})
    validate_error(res, "ERR_PAGINATION_INVALID")


# ─── state_machines ──────────────────────────────────────────────────
def test_submit_from_design_invalid_state(api):
    """PRD §2.9: "then that the target resource is in a state from which the
    requested transition is defined (ERR_INVALID_STATE, HTTP 409)". PRD §3.3:
    "Submitting a case advances it from INTAKE to DESIGN".

    Design: Corner/state_machines/submit_from_design_returns_invalid_state
    """
    set_clock()
    doctor = create_doctor()
    material = create_material(base_unit_price_cents=12000, fabrication_process="MILLED")
    case = create_case(doctor["id"])
    create_restoration(case["id"], material["id"], restoration_type="CROWN", unit_count=1)
    get_success_data(api.submit_case(case["id"], TECH))      # now in DESIGN
    res = api.submit_case(case["id"], TECH)
    validate_error(res, "ERR_INVALID_STATE")
    assert get_case(case["id"])["status"] == "DESIGN"


def test_cancel_from_cancelled_invalid_state(api):
    """PRD §3.8: "In both cancel paths the case lands in the terminal CANCELLED
    state". PRD §2.9: "then that the target resource is in a state from which the
    requested transition is defined (ERR_INVALID_STATE, HTTP 409)".

    Design: Corner/state_machines/cancel_from_cancelled_returns_invalid_state
    """
    set_clock()
    doctor = create_doctor()
    case = create_case(doctor["id"], intake_method="RX_PAPER")
    get_success_data(api.cancel_case(case["id"], make_doctor_headers(doctor["id"])))
    res = api.cancel_case(case["id"], make_doctor_headers(doctor["id"]))
    validate_error(res, "ERR_INVALID_STATE")
    assert get_case(case["id"])["status"] == "CANCELLED"


def test_new_case_starts_in_intake(api):
    """PRD §3.2: "A fresh case starts with billable_unit_count and revision_count
    both at 0, and its status defaults to INTAKE."

    Design: Corner/state_machines/new_case_starts_in_intake
    """
    doctor = create_doctor()
    res = api.create_case(
        create_case_payload(doctor["id"], intake_method="IMPRESSION"), TECH)
    case = validate_success(res, 201)
    assert case["status"] == "INTAKE"
    assert case["revision_count"] == 0
    assert case["billable_unit_count"] == 0


def test_start_fabrication_before_scheduling_blocked(api):
    """PRD §3.4: "Before a case can leave DESIGN (or re-enter the loop), every
    queued unit on the case must already have a mill job that is SCHEDULED or
    DONE."

    Design: Corner/state_machines/start_fabrication_before_scheduling_blocked
    """
    set_clock()
    doctor = create_doctor()
    material = create_material(base_unit_price_cents=12000, fabrication_process="MILLED")
    case = create_case(doctor["id"])
    create_restoration(case["id"], material["id"], restoration_type="CROWN", unit_count=1)
    get_success_data(api.submit_case(case["id"], TECH))      # DESIGN, unit QUEUED, no MillJob
    res = api.start_fabrication(case["id"], TECH)
    validate_error(res, "ERR_INVALID_STATE")
    assert get_case(case["id"])["status"] == "DESIGN"


def test_milljob_complete_from_scheduled_blocked(api):
    """PRD §3.4: "Completing a running job moves it from RUNNING to DONE and
    advances its unit from MILLING to MILLED." PRD §2.9: "then that the target
    resource is in a state from which the requested transition is defined
    (ERR_INVALID_STATE, HTTP 409)".

    Design: Corner/state_machines/milljob_complete_from_scheduled_blocked
    """
    set_clock()
    doctor = create_doctor()
    material = create_material(base_unit_price_cents=12000, fabrication_process="MILLED")
    machine = create_machine()
    case = create_case(doctor["id"])
    rest = create_restoration(case["id"], material["id"], restoration_type="CROWN", unit_count=1)
    get_success_data(api.submit_case(case["id"], TECH))
    unit = list_units(rest["id"])[0]
    job = get_success_data(api.create_mill_job(
        create_mill_job_payload(unit["id"], machine["id"]), SCHED))
    res = api.complete_mill_job(job["id"], SCHED)            # still SCHEDULED, never started
    validate_error(res, "ERR_INVALID_STATE")
    assert get_success_data(api.get_mill_job(job["id"], SCHED))["status"] == "SCHEDULED"
