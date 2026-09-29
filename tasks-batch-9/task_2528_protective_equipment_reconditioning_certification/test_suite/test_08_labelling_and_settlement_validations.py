"""Loaner, labelling, retention and settlement rejections.

Every test builds its own state through the documented endpoints, positions the
logical clock rather than sleeping, and re-reads the entities a refused request
touched to prove nothing moved.
"""
from test_helpers import (
    COMPLIANCE_1,
    INSPECTOR_1,
    INTAKE_CLERK,
    PLANT_MANAGER,
    ApiErrorId,
    api_client,
    assert_disposition_ledger_conserved,
    create_certification_label_payload,
    create_loaner_assignment_payload,
    identify_unit,
    read_label,
    read_loaner_unit,
    read_shipment,
    read_unit,
    set_clock,
    setup_accepted_shipment,
    setup_certified_units,
    setup_loaner_pool,
    setup_settled_shipment,
    setup_test_passed_unit,
    unit_version,
    validate_error,
    validate_paginated,
    void_label_payload,
)


def test_an_explicit_loaner_whose_certification_lapses_inside_the_window_rejected():
    """A named loaner whose own certification expires mid-loan cannot be booked.

    The PRD states: "If that loaner's own `certification_valid_until` falls
    before the requested `window_end`, the request is refused with
    `ERR_LOANER_CERTIFICATION_EXPIRED` (HTTP 422); the plant will not lend
    equipment whose certification lapses mid-loan." The loaner below is still
    certified on the booking date of 1 August 2026 but lapses on 11 August 2026,
    inside the requested window that ends on 12 August 2026, so the booking is
    refused with error id `ERR_LOANER_CERTIFICATION_EXPIRED` and HTTP 422.

    Nothing may be booked against it: "A new loaner enters the pool with
    `status` `AVAILABLE` and `assignment_count` at 0, where `assignment_count`
    counts every assignment ever created against that loaner."

    Design: Corner/validations/an_explicit_loaner_whose_certification_lapses_inside_the_window_rejected
    """
    ctx = setup_loaner_pool(
        grades=("A",), certification_valid_until="2026-08-11T00:00:00Z"
    )
    loaner = ctx["loaner"]
    assert loaner["status"] == "AVAILABLE"
    assert ctx["account"]["liability_waiver_status"] == "ON_FILE"
    assert ctx["account"]["status"] == "ACTIVE"

    payload = create_loaner_assignment_payload(
        ctx["account"]["id"],
        ctx["model"]["id"],
        window_start="2026-08-05T00:00:00Z",
        window_end="2026-08-12T00:00:00Z",
        loaner_unit_id=loaner["id"],
    )
    response = api_client.create_loaner_assignment(payload, INTAKE_CLERK)
    validate_error(response, ApiErrorId.ERR_LOANER_CERTIFICATION_EXPIRED.value, 422)

    unchanged = read_loaner_unit(loaner["id"])
    assert unchanged["status"] == "AVAILABLE"
    assert unchanged["assignment_count"] == 0

    rows, meta = validate_paginated(
        api_client.list_loaner_assignments(
            INTAKE_CLERK, params={"customer_account_id": ctx["account"]["id"]}
        )
    )
    assert meta["total_count"] == 0
    assert rows == []


def test_labelling_more_than_fourteen_days_after_the_pass_rejected():
    """A pass signed fifteen days ago is too stale to certify.

    The PRD states: "There is also a freshness window on the passing result: if
    the logical clock is more than 14 days past the instant at which the unit's
    most recent `DETERMINED` session was signed — that session's `updated_at` —
    the pass is considered stale and the issue is refused with
    `ERR_LABEL_WINDOW_EXPIRED` (HTTP 422)." The determination below is signed on
    1 August 2026 and the clock is then moved to 16 August 2026, fifteen days
    later, so the issue is refused with error id `ERR_LABEL_WINDOW_EXPIRED` and
    HTTP 422.

    None of the issuance cascade may run: "The unit advances `TEST_PASSED →
    CERTIFIED`, has `certified_at` stamped from the logical clock, and has
    `record_retention_until` set to `certified_at` advanced by the model's
    `record_retention_years`."

    Design: Corner/validations/labelling_more_than_fourteen_days_after_the_pass_rejected
    """
    ctx = setup_test_passed_unit()
    unit_id = ctx["unit"]["id"]
    assert ctx["unit"]["recon_status"] == "TEST_PASSED"
    expected_version = unit_version(unit_id)

    set_clock("2026-08-16T00:00:00Z")

    response = api_client.create_certification_label(
        create_certification_label_payload(unit_id, expected_version), INSPECTOR_1
    )
    validate_error(response, ApiErrorId.ERR_LABEL_WINDOW_EXPIRED.value, 422)

    unit = read_unit(unit_id)
    assert unit["recon_status"] == "TEST_PASSED"
    assert unit["certified_at"] is None
    assert unit["record_retention_until"] is None
    assert unit["version"] == expected_version

    rows, meta = validate_paginated(
        api_client.list_unit_certification_labels(unit_id, INSPECTOR_1)
    )
    assert meta["total_count"] == 0
    assert rows == []

    shipment = read_shipment(ctx["shipment"]["id"])
    assert shipment["units_certified"] == 0
    assert shipment["units_in_process"] == 1
    assert_disposition_ledger_conserved(shipment)


def test_purging_records_before_the_retention_window_closes_rejected():
    """Retained records cannot be purged while the retention term is still running.

    The PRD states: "The purge is refused with `ERR_RETENTION_ACTIVE` (HTTP 409)
    whenever `record_retention_until` is null — meaning the retention clock never
    started — or is greater than or equal to the logical clock, meaning the term
    has not yet fully elapsed." The certified unit below inherits its deadline
    from issuance: "The unit advances `TEST_PASSED → CERTIFIED`, has
    `certified_at` stamped from the logical clock, and has
    `record_retention_until` set to `certified_at` advanced by the model's
    `record_retention_years`."

    Certified on 1 August 2026 under a three-year retention term, the unit's
    deadline is 1 August 2029, far ahead of the clock, so the purge is refused
    with error id `ERR_RETENTION_ACTIVE` and HTTP 409 and `records_purged_at`
    stays null.

    Design: Corner/validations/purging_records_before_the_retention_window_closes_rejected
    """
    ctx = setup_certified_units(unit_count=1)
    unit_id = ctx["unit"]["id"]
    assert ctx["model"]["record_retention_years"] == 3
    assert ctx["unit"]["recon_status"] == "CERTIFIED"
    assert ctx["unit"]["record_retention_until"].startswith("2029-08-01T00:00:00")
    assert ctx["unit"]["records_purged_at"] is None

    response = api_client.purge_equipment_unit_records(unit_id, COMPLIANCE_1)
    validate_error(response, ApiErrorId.ERR_RETENTION_ACTIVE.value, 409)

    unit = read_unit(unit_id)
    assert unit["record_retention_until"].startswith("2029-08-01T00:00:00")
    assert unit["records_purged_at"] is None
    assert unit["recon_status"] == "CERTIFIED"
    assert unit["version"] == ctx["unit"]["version"]

    assert read_label(ctx["label"]["id"])["status"] == "ACTIVE"


def test_voiding_a_label_after_settlement_is_locked_rejected():
    """Once the shipment is settled its label can no longer be voided.

    The PRD states: "The parent shipment must not have been settled: when its
    `settlement_locked` is true the void is refused with `ERR_SETTLEMENT_LOCKED`
    (HTTP 409)." The lock itself is written by settlement: "A successful settle
    computes the final total into `final_total_cents`, sets `settlement_locked`
    to true, advances the shipment `READY_FOR_RETURN → CLOSED`, and advances its
    `version` by one."

    The label under test is otherwise perfectly voidable — it is `ACTIVE` and its
    unit is `CERTIFIED` and still `AT_PLANT` — so the refusal can only come from
    the settled ancestor, with error id `ERR_SETTLEMENT_LOCKED` and HTTP 409, and
    the compensating four hops of a permitted void must not run.

    The settled figure follows the documented rounding order: "The `FINAL`
    variant runs at settlement and writes `final_total_cents`; it rounds *each*
    line's exact amount half up to whole cents first and then sums the rounded
    lines, and it operates on the real billable set, so it also picks up the
    condemned-handling charge and the closed-repair labour." One `CERTIFIED`
    `STANDARD` unit with no closed repair order gives a gross of 8,996 cents, no
    discount below 10,000 cents, and a 2 percent surcharge of 180 cents, for
    9,176 cents.

    Design: Corner/validations/voiding_a_label_after_settlement_is_locked_rejected
    """
    ctx = setup_settled_shipment(unit_count=1, service_tier="STANDARD")
    label = ctx["label"]
    shipment = ctx["shipment"]
    assert shipment["status"] == "CLOSED"
    assert shipment["settlement_locked"] is True
    assert shipment["final_total_cents"] == 9176

    response = api_client.void_certification_label(
        label["id"],
        void_label_payload(void_reason="decal misprint found after invoicing"),
        COMPLIANCE_1,
    )
    validate_error(response, ApiErrorId.ERR_SETTLEMENT_LOCKED.value, 409)

    unchanged_label = read_label(label["id"])
    assert unchanged_label["status"] == "ACTIVE"
    assert unchanged_label["voided_at"] is None
    assert unchanged_label["voided_by_user_id"] is None
    assert unchanged_label["void_reason"] is None

    unit = read_unit(ctx["unit"]["id"])
    assert unit["recon_status"] == "CERTIFIED"
    assert unit["certified_at"] is not None

    after = read_shipment(shipment["id"])
    assert after["status"] == "CLOSED"
    assert after["settlement_locked"] is True
    assert after["final_total_cents"] == 9176
    assert after["units_certified"] == 1
    assert after["units_in_process"] == 0
    assert_disposition_ledger_conserved(after)


def test_settling_while_units_are_still_on_the_shop_floor_rejected():
    """Settling a shipment that still has work in process names the specific reason.

    The PRD states: "**Settlement readiness** — a settle request while units
    remain on the shop floor: `ERR_SHIPMENT_NOT_READY`." and explains why that
    outranks the generic status guard: "This rung sits deliberately ahead of the
    generic state rung so that a premature settlement names the specific reason
    rather than a generic status error; a shipment that has not yet reached
    `READY_FOR_RETURN` always has a non-zero in-process counter, so this is what a
    caller settling too early actually sees." Identifying the shipment's only unit
    drives it into active work — "From `ACCEPTED` the shipment slides into active
    work without any explicit request: the first unit of the shipment to leave
    `RECEIVED` drives the shipment `ACCEPTED → IN_PROCESS` and advances its
    `version` by one." — so the settle attempt returns error id
    `ERR_SHIPMENT_NOT_READY` with HTTP 409 rather than a status error, and nothing
    is written.

    The provisional figure computed at acceptance must survive untouched: "The
    `PROVISIONAL` variant runs at acceptance and writes
    `provisional_total_cents`; it sums the exact line amounts across the set and
    rounds *once*, half up, at the end." and "Because no unit has reached
    `CERTIFIED` or `CONDEMNED` at acceptance time, the billable set is empty
    then, so the provisional run instead prices `counted_unit_count` synthetic
    lines, each being the exact base amount of 8,996 cents multiplied by the tier
    multiplier with no extras." One synthetic `STANDARD` line of 8,996 cents
    attracts no discount below 10,000 cents and a 2 percent surcharge of 180
    cents, for 9,176 cents.

    Design: Corner/validations/settling_while_units_are_still_on_the_shop_floor_rejected
    """
    ctx = setup_accepted_shipment(unit_count=1, service_tier="STANDARD")
    identify_unit(ctx["unit"]["id"], ctx["model"]["id"])

    in_process = read_shipment(ctx["shipment"]["id"])
    assert in_process["status"] == "IN_PROCESS"
    assert in_process["units_in_process"] == 1
    assert in_process["provisional_total_cents"] == 9176

    response = api_client.settle_intake_shipment(ctx["shipment"]["id"], PLANT_MANAGER)
    validate_error(response, ApiErrorId.ERR_SHIPMENT_NOT_READY.value, 409)

    after = read_shipment(ctx["shipment"]["id"])
    assert after["status"] == "IN_PROCESS"
    assert after["units_in_process"] == 1
    assert after["units_certified"] == 0
    assert after["final_total_cents"] is None
    assert after["settlement_locked"] is False
    assert after["provisional_total_cents"] == 9176
    assert after["version"] == in_process["version"]
    assert_disposition_ledger_conserved(after)


def test_wrong_role_with_a_malformed_payload_returns_unauthorized():
    """An unauthorized caller is turned away before its body is ever validated.

    The PRD states: "When a single request violates more than one rule, the error
    returned is always the one belonging to the earliest applicable rung of a
    fixed ladder." Role authorization sits on that ladder ahead of the request
    schema, and the role gate itself reads: "A caller whose role is not
    among those authorized for the endpoint it addressed is rejected with
    `ERR_UNAUTHORIZED` (HTTP 403); this role gate does apply to the clock
    endpoint, whose authorized set is the five plant roles and excludes
    `CustomerContact`." Model registration belongs to one role only:
    "`PlantManager` owns reference data — model specifications, approved parts,
    test benches, loaner units and customer accounts — and closes the commercial
    loop by settling shipments."

    An `IntakeClerk` posting a body that is missing required fields and carries a
    `shell_material` outside its declared set therefore receives error id
    `ERR_UNAUTHORIZED` with HTTP 403 and learns nothing about the schema. The same
    body from a `PlantManager` reaches the schema rung — "**Request schema** — a
    required field absent, a field of the wrong JSON type, an enum value outside
    its declared set, a numeric field out of range (any of the peak-g readings
    below zero, a part-line `quantity` below 1, a `counted_unit_count` below 1, a
    `limit` outside 1 through 100, a negative `offset`, a `record_retention_years`
    below 1), or a window whose `window_end` is not strictly after its
    `window_start`: `ERR_INVALID_REQUEST`." — and is rejected with error id
    `ERR_INVALID_REQUEST` and HTTP 400, which is what proves the body really was
    malformed when the clerk was refused.

    Design: Corner/validations/wrong_role_with_a_malformed_payload_returns_unauthorized
    """
    set_clock()
    malformed = {"manufacturer": "Riddell", "shell_material": "TITANIUM"}

    refused = api_client.create_model_spec(malformed, INTAKE_CLERK)
    validate_error(refused, ApiErrorId.ERR_UNAUTHORIZED.value, 403)

    schema_error = api_client.create_model_spec(malformed, PLANT_MANAGER)
    validate_error(schema_error, ApiErrorId.ERR_INVALID_REQUEST.value, 400)
