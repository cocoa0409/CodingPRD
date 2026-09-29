"""Error catalogue: not-found closure, foreign-key resolution order, the empty
loaner pool, and the two terminal-state repeats.

Each error id and HTTP status asserted here is the one the reconditioning API's
requirements name for that exact trigger condition.
"""
from test_helpers import (
    COMPLIANCE_1,
    INTAKE_CLERK,
    NON_EXISTENT_UUID,
    PASS_IMPACTS,
    PLANT_MANAGER,
    TECHNICIAN_1,
    ApiErrorId,
    book_loaner,
    create_loaner_assignment_payload,
    create_shell_test_payload,
    read_loaner_assignment,
    read_loaner_unit,
    read_shell_test,
    read_unit,
    record_impacts_payload,
    return_loaner,
    return_loaner_payload,
    set_clock,
    setup_loaner_assignment,
    setup_loaner_pool,
    setup_tested_units,
    validate_error,
    validate_paginated,
)


def test_unknown_ids_return_the_matching_not_found_error(api):
    """Every single-resource read names its own entity's not-found error.

    The requirements state: "**Existence** — a referenced row does not exist.
    Within this rung the path identifier is resolved first, and then foreign-key
    fields in this declaration order: `customer_account_id`, `model_spec_id`,
    `intake_shipment_id`, `equipment_unit_id`, `test_bench_id`,
    `approved_part_id`, `loaner_unit_id`. The error returned is the specific
    not-found code for the first unresolved reference." Probing each read with the
    same unknown identifier must therefore answer HTTP 404 with the entity's own
    code: ERR_CUSTOMER_ACCOUNT_NOT_FOUND, ERR_MODEL_SPEC_NOT_FOUND,
    ERR_APPROVED_PART_NOT_FOUND, ERR_TEST_BENCH_NOT_FOUND,
    ERR_SHIPMENT_NOT_FOUND, ERR_UNIT_NOT_FOUND, ERR_SHELL_TEST_NOT_FOUND,
    ERR_REPAIR_ORDER_NOT_FOUND, ERR_LABEL_NOT_FOUND,
    ERR_DESTRUCTION_RECORD_NOT_FOUND, ERR_LOANER_UNIT_NOT_FOUND and
    ERR_LOANER_ASSIGNMENT_NOT_FOUND respectively.

    Design: Corner/errors/unknown_ids_return_the_matching_not_found_error
    """
    set_clock()

    probes = [
        (
            api.get_customer_account(NON_EXISTENT_UUID, PLANT_MANAGER),
            ApiErrorId.ERR_CUSTOMER_ACCOUNT_NOT_FOUND,
        ),
        (
            api.get_model_spec(NON_EXISTENT_UUID, PLANT_MANAGER),
            ApiErrorId.ERR_MODEL_SPEC_NOT_FOUND,
        ),
        (
            api.get_approved_part(NON_EXISTENT_UUID, PLANT_MANAGER),
            ApiErrorId.ERR_APPROVED_PART_NOT_FOUND,
        ),
        (
            api.get_test_bench(NON_EXISTENT_UUID, PLANT_MANAGER),
            ApiErrorId.ERR_TEST_BENCH_NOT_FOUND,
        ),
        (
            api.get_intake_shipment(NON_EXISTENT_UUID, INTAKE_CLERK),
            ApiErrorId.ERR_SHIPMENT_NOT_FOUND,
        ),
        (
            api.get_equipment_unit(NON_EXISTENT_UUID, TECHNICIAN_1),
            ApiErrorId.ERR_UNIT_NOT_FOUND,
        ),
        (
            api.get_shell_test(NON_EXISTENT_UUID, TECHNICIAN_1),
            ApiErrorId.ERR_SHELL_TEST_NOT_FOUND,
        ),
        (
            api.get_repair_order(NON_EXISTENT_UUID, TECHNICIAN_1),
            ApiErrorId.ERR_REPAIR_ORDER_NOT_FOUND,
        ),
        (
            api.get_certification_label(NON_EXISTENT_UUID, COMPLIANCE_1),
            ApiErrorId.ERR_LABEL_NOT_FOUND,
        ),
        (
            api.get_destruction_record(NON_EXISTENT_UUID, COMPLIANCE_1),
            ApiErrorId.ERR_DESTRUCTION_RECORD_NOT_FOUND,
        ),
        (
            api.get_loaner_unit(NON_EXISTENT_UUID, PLANT_MANAGER),
            ApiErrorId.ERR_LOANER_UNIT_NOT_FOUND,
        ),
        (
            api.get_loaner_assignment(NON_EXISTENT_UUID, INTAKE_CLERK),
            ApiErrorId.ERR_LOANER_ASSIGNMENT_NOT_FOUND,
        ),
    ]

    for response, expected_error in probes:
        validate_error(response, expected_error.value, 404)


def test_two_unresolved_fks_report_the_first_in_declaration_order_not_found(api):
    """Booking with an unknown unit and an unknown bench names the unit error.

    The requirements state: "Within this rung the path identifier is resolved
    first, and then foreign-key fields in this declaration order:
    `customer_account_id`, `model_spec_id`, `intake_shipment_id`,
    `equipment_unit_id`, `test_bench_id`, `approved_part_id`, `loaner_unit_id`.
    The error returned is the specific not-found code for the first unresolved
    reference." Because `equipment_unit_id` is declared ahead of `test_bench_id`,
    a session booking carrying two unknown references must answer
    ERR_UNIT_NOT_FOUND and not the bench's not-found code, and no session may be
    created.

    Design: Corner/errors/two_unresolved_fks_report_the_first_in_declaration_order_not_found
    """
    set_clock()

    response = api.create_shell_test(
        create_shell_test_payload(NON_EXISTENT_UUID, NON_EXISTENT_UUID), TECHNICIAN_1
    )
    validate_error(response, ApiErrorId.ERR_UNIT_NOT_FOUND.value, 404)

    sessions, meta = validate_paginated(api.list_shell_tests(TECHNICIAN_1))
    assert meta["total_count"] == 0
    assert sessions == []


def test_booking_with_an_empty_eligible_pool_returns_no_loaner_available(api):
    """A server-selected booking with nothing eligible fails loudly.

    The requirements state: "A loaner is eligible only if all four of the
    following hold: its `model_spec_id` equals the requested
    `requested_model_spec_id`; its `status` is `AVAILABLE`; its
    `certification_valid_until` is greater than or equal to the requested
    `window_end`; and it carries no assignment in `RESERVED` or `OUT_ON_LOAN`
    status whose half-open window intersects the requested half-open window."
    They continue: "An empty eligible pool is an error rather than a null
    selection: it is refused with `ERR_NO_LOANER_AVAILABLE` (HTTP 409)." The only
    loaner of the model is already reserved for 5 to 12 August, so a request for 8
    to 15 August overlaps it, leaving the eligible pool empty and the booking
    refused with ERR_NO_LOANER_AVAILABLE.

    Design: Corner/errors/booking_with_an_empty_eligible_pool_returns_no_loaner_available
    """
    ctx = setup_loaner_pool(grades=("A",))
    account_id = ctx["account"]["id"]
    loaner_id = ctx["loaner"]["id"]
    first = book_loaner(account_id, ctx["model"]["id"], loaner_unit_id=loaner_id)

    response = api.create_loaner_assignment(
        create_loaner_assignment_payload(
            account_id,
            ctx["model"]["id"],
            window_start="2026-08-08T00:00:00Z",
            window_end="2026-08-15T00:00:00Z",
        ),
        INTAKE_CLERK,
    )
    validate_error(response, ApiErrorId.ERR_NO_LOANER_AVAILABLE.value, 409)

    loaner = read_loaner_unit(loaner_id)
    assert loaner["status"] == "RESERVED"
    assert loaner["assignment_count"] == 1

    assignments, meta = validate_paginated(
        api.list_loaner_assignments(INTAKE_CLERK, params={"customer_account_id": account_id})
    )
    assert meta["total_count"] == 1
    assert [row["id"] for row in assignments] == [first["id"]]


def test_recording_impacts_twice_returns_the_shell_test_state_error(api):
    """A second set of readings against a completed session is refused.

    The requirements state: "A `Technician` supplies `peak_g_front`,
    `peak_g_side` and `peak_g_crown`, none of which may be negative, against a
    session in `SCHEDULED` status; a session in any other status is rejected with
    `ERR_SHELL_TEST_STATE_INVALID` (HTTP 409)." The refusal must leave the first
    measurement intact: readings of 300 at each site weight to 150.0 + 90.0 + 60.0
    for a severity index of 300.0, which is a PASS "because the band is inclusive
    at its upper edge", and the unit's `current_si` and `retest_count` are
    unchanged. The expected error id is ERR_SHELL_TEST_STATE_INVALID.

    Design: Corner/errors/recording_impacts_twice_returns_the_shell_test_state_error
    """
    ctx = setup_tested_units(unit_count=1, impacts=PASS_IMPACTS)
    session_id = ctx["shell_test"]["id"]
    session_version = ctx["shell_test"]["version"]

    response = api.record_impacts(
        session_id, record_impacts_payload(100, 100, 100), TECHNICIAN_1
    )
    validate_error(response, ApiErrorId.ERR_SHELL_TEST_STATE_INVALID.value, 409)

    session = read_shell_test(session_id)
    assert session["status"] == "COMPLETED"
    assert session["severity_index"] == 300.0
    assert session["computed_result"] == "PASS"
    assert session["peak_g_front"] == 300
    assert session["peak_g_side"] == 300
    assert session["peak_g_crown"] == 300
    assert session["version"] == session_version

    unit = read_unit(ctx["unit"]["id"])
    assert unit["current_si"] == 300.0
    assert unit["retest_count"] == 0
    assert unit["recon_status"] == "TESTED"


def test_returning_a_loaner_twice_returns_the_assignment_state_error(api):
    """RETURNED is terminal for a loaner assignment.

    The requirements state: "An `IntakeClerk` returns an assignment whose
    `status` is `RESERVED` or `OUT_ON_LOAN`, optionally supplying a
    `return_condition_note`." and "Returning an assignment that is already
    `RETURNED` is refused with `ERR_LOANER_ASSIGNMENT_STATE_INVALID` (HTTP 409)."
    The second attempt must not touch the loaner again: `returned_at` keeps the
    value the first return stamped from the logical clock, and the loaner stays
    AVAILABLE with `assignment_count` 1. The expected error id is
    ERR_LOANER_ASSIGNMENT_STATE_INVALID.

    Design: Corner/errors/returning_a_loaner_twice_returns_the_assignment_state_error
    """
    ctx = setup_loaner_assignment(explicit=True)
    assignment_id = ctx["assignment"]["id"]
    loaner_id = ctx["loaner"]["id"]

    first = return_loaner(assignment_id, note="shell scuffed, pads intact")
    assert first["status"] == "RETURNED"
    assert first["returned_at"].startswith("2026-08-01T00:00:00")

    response = api.return_loaner_assignment(
        assignment_id, return_loaner_payload(return_condition_note="duplicate return"), INTAKE_CLERK
    )
    validate_error(response, ApiErrorId.ERR_LOANER_ASSIGNMENT_STATE_INVALID.value, 409)

    assignment = read_loaner_assignment(assignment_id)
    assert assignment["status"] == "RETURNED"
    assert assignment["returned_at"] == first["returned_at"]
    assert assignment["version"] == first["version"]

    loaner = read_loaner_unit(loaner_id)
    assert loaner["status"] == "AVAILABLE"
    assert loaner["assignment_count"] == 1
