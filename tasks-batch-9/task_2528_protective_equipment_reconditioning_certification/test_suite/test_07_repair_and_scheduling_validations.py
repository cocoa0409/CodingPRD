"""Repair-order, segregation-of-duties and bench-scheduling rejections.

Every test in this module drives the documented endpoints only, builds all of
its state from scratch, and asserts that a refused request left the entities it
touched exactly as they were.
"""
from test_helpers import (
    COMPLIANCE_1,
    COMPLIANCE_OFFICER_1_USER_ID,
    TECHNICIAN_1,
    TECHNICIAN_1_USER_ID,
    TECHNICIAN_2,
    TECHNICIAN_2_USER_ID,
    ApiErrorId,
    api_client,
    assert_part_stock_conserved,
    create_shell_test_payload,
    get_success_data,
    read_part,
    read_repair_order,
    read_shell_test,
    read_unit,
    schedule_shell_test,
    setup_destruction_record,
    setup_inspected_units,
    setup_repair_order,
    validate_error,
    validate_paginated,
    validate_success,
    verify_destruction_payload,
    verify_repair_payload,
)


def _read_destruction_record(record_id, headers=COMPLIANCE_1):
    """Single-record read of a destruction record; fixtures.py only exposes the
    per-unit collection read."""
    return get_success_data(api_client.get_destruction_record(record_id, headers))


def test_installing_parts_on_a_draft_repair_order_rejected():
    """Recording installation on an order that has never been submitted is refused.

    The PRD states: "A `Technician` records installation on a `PARTS_PENDING`
    order, supplying a `warranty_claim_ref` where one is needed." and fixes the
    consequence of addressing an operation to the wrong status: "**State
    guards** — the target resource is not in a status from which the requested
    transition is defined: `ERR_SHIPMENT_STATE_INVALID`, `ERR_UNIT_STATE_INVALID`,
    `ERR_SHELL_TEST_STATE_INVALID`, `ERR_REPAIR_ORDER_STATE_INVALID`,
    `ERR_LABEL_ALREADY_VOIDED`, `ERR_DESTRUCTION_STATE_INVALID` or
    `ERR_LOANER_ASSIGNMENT_STATE_INVALID`, each on its own family of
    operations."  A `DRAFT` order carrying one part line therefore rejects
    installation with error id `ERR_REPAIR_ORDER_STATE_INVALID` and HTTP 409.

    Because submission is the step that reserves stock, the parts cage must be
    untouched afterwards: "For every `ApprovedPart`, the quantity originally
    booked into the parts cage always equals the sum of the three moving
    buckets: `received_qty` equals `on_hand_qty` plus `reserved_qty` plus
    `consumed_qty`."

    Design: Corner/validations/installing_parts_on_a_draft_repair_order_rejected
    """
    ctx = setup_repair_order(target_status="DRAFT", quantity=1, received_qty=4)
    order = ctx["repair_order"]
    assert order["status"] == "DRAFT"

    response = api_client.install_repair_order(order["id"], {}, TECHNICIAN_1)
    validate_error(response, ApiErrorId.ERR_REPAIR_ORDER_STATE_INVALID.value, 409)

    unchanged = read_repair_order(order["id"])
    assert unchanged["status"] == "DRAFT"
    assert unchanged["installed_by_user_id"] is None
    assert unchanged["installed_parts_cents"] == 0
    assert unchanged["reserved_parts_cents"] == 0
    assert [line["status"] for line in unchanged["part_lines"]] == ["DRAFT"]

    part = read_part(ctx["part"]["id"])
    assert part["received_qty"] == 4
    assert part["on_hand_qty"] == 4
    assert part["reserved_qty"] == 0
    assert part["consumed_qty"] == 0
    assert_part_stock_conserved(part)

    unit = read_unit(ctx["unit"]["id"])
    assert unit["recon_status"] == "REPAIR_PENDING"


def test_verifying_a_repair_you_installed_yourself_rejected():
    """The technician who installed the parts may not sign the verification.

    The PRD states: "Verifying a repair is refused when the acting `X-User-ID`
    equals the order's `installed_by_user_id` — the technician who installed the
    parts cannot sign off on their own work." and again, on the endpoint itself:
    "A `Technician` verifies an `INSTALLED` order by supplying an `outcome` of
    `PASSED` or `FAILED` and optionally a `note`; the acting `X-User-ID` must
    differ from the order's `installed_by_user_id`, failing which the request is
    refused with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)." Both callers below
    carry the `Technician` role, so the role gate passes and the refusal is
    purely identity-based: error id `ERR_SEGREGATION_OF_DUTIES` with HTTP 403.

    A second technician signing the identical request is accepted, because "A
    `PASSED` outcome records `verified_by_user_id` from the acting `X-User-ID`,
    sets `labor_cents` to the flat repair labour charge of 4,500 cents — forty-five
    dollars per closed repair — advances the order `INSTALLED → CLOSED`, and
    advances the unit `REPAIR_PENDING → REPAIRED`, with both `version` counters
    advancing by one."

    Design: Corner/validations/verifying_a_repair_you_installed_yourself_rejected
    """
    ctx = setup_repair_order(target_status="INSTALLED", quantity=1, received_qty=4)
    order = ctx["repair_order"]
    assert order["status"] == "INSTALLED"
    assert order["installed_by_user_id"] == TECHNICIAN_1_USER_ID

    response = api_client.verify_repair_order(
        order["id"], verify_repair_payload("PASSED", note="self-check"), TECHNICIAN_1
    )
    validate_error(response, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 403)

    unchanged = read_repair_order(order["id"])
    assert unchanged["status"] == "INSTALLED"
    assert unchanged["installed_by_user_id"] == TECHNICIAN_1_USER_ID
    assert unchanged["verified_by_user_id"] is None
    assert unchanged["verification_failure_count"] == 0
    assert unchanged["labor_cents"] == 0

    unit = read_unit(ctx["unit"]["id"])
    assert unit["recon_status"] == "REPAIR_PENDING"

    part = read_part(ctx["part"]["id"])
    assert part["consumed_qty"] == 1
    assert_part_stock_conserved(part)

    accepted = validate_success(
        api_client.verify_repair_order(
            order["id"], verify_repair_payload("PASSED", note="rework inspected"), TECHNICIAN_2
        ),
        200,
    )
    assert accepted["status"] == "CLOSED"
    assert accepted["verified_by_user_id"] == TECHNICIAN_2_USER_ID
    assert accepted["labor_cents"] == 4500
    assert read_unit(ctx["unit"]["id"])["recon_status"] == "REPAIRED"


def test_an_in_warranty_repair_without_a_claim_reference_rejected():
    """Installing on a still-warranted shell demands a manufacturer claim reference.

    The PRD states: "The warranty rule is unconditional in one direction: when
    the unit's `warranty_coverage` is `IN_WARRANTY`, an installation with no
    `warranty_claim_ref` is refused with `ERR_WARRANTY_CLAIM_REQUIRED` (HTTP
    422), because an in-warranty repair must be attributed to a manufacturer
    claim *before* parts are consumed." The posture under test is derived at
    identification: "`warranty_coverage`, which reads `PENDING` on an
    unidentified unit, becomes `IN_WARRANTY` when `service_age_years` is less
    than or equal to the model's `warranty_years` and `OUT_OF_WARRANTY`
    otherwise." and "Under the `MANUFACTURE_DATE` basis, `service_age_years` is
    the whole number of elapsed days between the manufacture date and the
    current date on the logical clock, divided by 365 days per service year and
    rounded down to a whole number."

    A shell manufactured on 15 September 2023, read against a clock of 1 August
    2026, is therefore two service years old against a warranty term of five, so
    the claim-less installation carries error id `ERR_WARRANTY_CLAIM_REQUIRED`
    and HTTP 422 while the reserved part is left reserved, never consumed.

    Design: Corner/validations/an_in_warranty_repair_without_a_claim_reference_rejected
    """
    ctx = setup_repair_order(
        target_status="PARTS_PENDING",
        quantity=1,
        received_qty=4,
        identify_overrides={"manufacture_date": "2023-09-15T00:00:00Z"},
    )
    unit = read_unit(ctx["unit"]["id"])
    assert unit["service_age_years"] == 2
    assert unit["warranty_coverage"] == "IN_WARRANTY"

    order = ctx["repair_order"]
    assert order["status"] == "PARTS_PENDING"

    response = api_client.install_repair_order(order["id"], {}, TECHNICIAN_1)
    validate_error(response, ApiErrorId.ERR_WARRANTY_CLAIM_REQUIRED.value, 422)

    unchanged = read_repair_order(order["id"])
    assert unchanged["status"] == "PARTS_PENDING"
    assert unchanged["installed_by_user_id"] is None
    assert unchanged["installed_parts_cents"] == 0
    assert [line["status"] for line in unchanged["part_lines"]] == ["RESERVED"]

    part = read_part(ctx["part"]["id"])
    assert part["on_hand_qty"] == 3
    assert part["reserved_qty"] == 1
    assert part["consumed_qty"] == 0
    assert_part_stock_conserved(part)


def test_verifying_a_destruction_you_witnessed_yourself_rejected():
    """The officer who witnessed the crush may not also certify the evidence.

    The PRD states: "Verifying a destruction is refused when the acting
    `X-User-ID` equals the record's `witnessed_by_user_id` — the officer who
    watched the shell being destroyed cannot also be the officer who certifies
    the evidence." and, on the endpoint: "The record must be in `WITNESSED`
    status, failing which the request is refused with
    `ERR_DESTRUCTION_STATE_INVALID` (HTTP 409), and the acting `X-User-ID` must
    differ from the record's `witnessed_by_user_id`, failing which it is refused
    with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)." The refused verification
    therefore carries error id `ERR_SEGREGATION_OF_DUTIES` and HTTP 403, and none
    of the effects the PRD attaches to a successful verification may land: "It
    also completes the unit's custody journey: the unit moves `custody_status`
    `PENDING_DISPOSAL → DISPOSED` and has its `record_retention_until` set to the
    verification instant advanced by the model's `record_retention_years`."

    Design: Corner/validations/verifying_a_destruction_you_witnessed_yourself_rejected
    """
    ctx = setup_destruction_record(target_status="WITNESSED")
    record = ctx["destruction_record"]
    assert record["status"] == "WITNESSED"
    assert record["witnessed_by_user_id"] == COMPLIANCE_OFFICER_1_USER_ID

    response = api_client.verify_destruction_record(
        record["id"], verify_destruction_payload(verification_ref="DV-2026-0009"), COMPLIANCE_1
    )
    validate_error(response, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 403)

    unchanged = _read_destruction_record(record["id"])
    assert unchanged["status"] == "WITNESSED"
    assert unchanged["witnessed_by_user_id"] == COMPLIANCE_OFFICER_1_USER_ID
    assert unchanged["verified_by_user_id"] is None
    assert unchanged["verification_ref"] is None
    assert unchanged["verified_at"] is None

    unit = read_unit(ctx["unit"]["id"])
    assert unit["custody_status"] == "PENDING_DISPOSAL"
    assert unit["record_retention_until"] is None


def test_a_fifth_session_beyond_the_retest_cap_rejected():
    """A fifth bench session on a unit whose retest count has reached the cap fails.

    The PRD states: "A booking that would take the unit past its model's
    `max_retest_count` is rejected with `ERR_RETEST_LIMIT_EXCEEDED` (HTTP 409);
    the check is that the unit's current `retest_count` has already reached or
    passed that ceiling." and defines the counter it reads: "The unit's
    `retest_count` counts sessions beyond the first, so it stays at zero through
    the first booking and increases by one for every subsequent session — which
    is exactly the counter the retest cap reads."

    Four accepted bookings therefore leave `retest_count` at 3, equal to the
    model's `max_retest_count`, and the fifth booking is refused with error id
    `ERR_RETEST_LIMIT_EXCEEDED` and HTTP 409 even though each individual window
    clears the rig's cooldown envelope and the day's session quota.

    Design: Corner/validations/a_fifth_session_beyond_the_retest_cap_rejected
    """
    ctx = setup_inspected_units(unit_count=1)
    unit_id = ctx["unit"]["id"]
    bench_id = ctx["bench"]["id"]
    assert ctx["model"]["max_retest_count"] == 3
    assert ctx["bench"]["daily_session_quota"] == 6

    sessions = []
    for hour in (9, 11, 13, 15):
        sessions.append(
            schedule_shell_test(
                unit_id,
                bench_id,
                window_start=f"2026-08-01T{hour:02d}:00:00Z",
                window_end=f"2026-08-01T{hour + 1:02d}:00:00Z",
            )
        )
    assert read_unit(unit_id)["retest_count"] == 3
    assert read_shell_test(sessions[3]["id"])["attempt_index"] == 4

    response = api_client.create_shell_test(
        create_shell_test_payload(
            unit_id,
            bench_id,
            window_start="2026-08-01T17:00:00Z",
            window_end="2026-08-01T18:00:00Z",
        ),
        TECHNICIAN_1,
    )
    validate_error(response, ApiErrorId.ERR_RETEST_LIMIT_EXCEEDED.value, 409)

    unit = read_unit(unit_id)
    assert unit["retest_count"] == 3
    assert unit["recon_status"] == "INSPECTED"

    rows, meta = validate_paginated(
        api_client.list_shell_tests(TECHNICIAN_1, params={"equipment_unit_id": unit_id})
    )
    assert meta["total_count"] == 4
    assert len(rows) == 4


def test_a_second_session_beyond_the_bench_daily_quota_rejected():
    """A rig whose daily quota is one refuses a second session that same day.

    The PRD states: "The second limit is an aggregate daily cap: the number of
    sessions already booked on that bench whose `window_start` falls on the same
    UTC calendar day as the requested `window_start` is counted, and if that
    count has already reached the bench's `daily_session_quota` the booking is
    rejected with `ERR_BENCH_DAILY_QUOTA_EXCEEDED` (HTTP 409)." and separates the
    cap from the cooldown rule: "The two limits are genuinely independent: a set
    of bookings can each clear the cooldown envelope individually and still
    exceed the collective daily cap."

    The second booking below is for a different unit and its window clears the
    rig's cooldown padding entirely, so the only rule it breaks is the cap: error
    id `ERR_BENCH_DAILY_QUOTA_EXCEEDED` with HTTP 409. Because the count is taken
    per UTC calendar day, the identical window on the following day is accepted.

    Design: Corner/validations/a_second_session_beyond_the_bench_daily_quota_rejected
    """
    ctx = setup_inspected_units(
        unit_count=2,
        bench_overrides={"bench_code": "RIG-2", "daily_session_quota": 1},
    )
    bench_id = ctx["bench"]["id"]
    first_unit_id = ctx["units"][0]["id"]
    second_unit_id = ctx["units"][1]["id"]
    assert ctx["bench"]["daily_session_quota"] == 1

    schedule_shell_test(
        first_unit_id,
        bench_id,
        window_start="2026-08-01T09:00:00Z",
        window_end="2026-08-01T10:00:00Z",
    )

    response = api_client.create_shell_test(
        create_shell_test_payload(
            second_unit_id,
            bench_id,
            window_start="2026-08-01T11:00:00Z",
            window_end="2026-08-01T12:00:00Z",
        ),
        TECHNICIAN_1,
    )
    validate_error(response, ApiErrorId.ERR_BENCH_DAILY_QUOTA_EXCEEDED.value, 409)

    rows, meta = validate_paginated(
        api_client.list_shell_tests(TECHNICIAN_1, params={"test_bench_id": bench_id})
    )
    assert meta["total_count"] == 1
    assert len(rows) == 1

    blocked_unit = read_unit(second_unit_id)
    assert blocked_unit["recon_status"] == "INSPECTED"
    assert blocked_unit["retest_count"] == 0

    next_day = validate_success(
        api_client.create_shell_test(
            create_shell_test_payload(
                second_unit_id,
                bench_id,
                window_start="2026-08-02T11:00:00Z",
                window_end="2026-08-02T12:00:00Z",
            ),
            TECHNICIAN_1,
        ),
        201,
    )
    assert next_day["status"] == "SCHEDULED"
    assert next_day["attempt_index"] == 1
