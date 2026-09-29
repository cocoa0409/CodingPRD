"""State machine transitions for the protective-equipment reconditioning API.

Initial states, permitted transitions, refused transitions, terminal-state
lockdown, side-effect execution and cross-entity fan-out, all driven through the
documented endpoints only.
"""
from datetime import datetime, timezone

from test_helpers import (
    CERTIFYING_INSPECTOR_1_USER_ID,
    CLOCK_EPOCH,
    COMPLIANCE_1,
    COMPLIANCE_2,
    COMPLIANCE_OFFICER_1_USER_ID,
    COMPLIANCE_OFFICER_2_USER_ID,
    INSPECTOR_1,
    INTAKE_CLERK,
    PASS_IMPACTS,
    TECHNICIAN_1,
    TEST_DEFAULTS,
    ApiErrorId,
    accept_shipment_payload,
    api_client,
    assert_certification_label,
    assert_destruction_record,
    assert_disposition_ledger_conserved,
    assert_equipment_unit,
    assert_intake_shipment,
    assert_label_code,
    assert_loaner_assignment,
    assert_loaner_unit,
    assert_shell_test,
    book_loaner,
    condemn_unit,
    create_certification_label_payload,
    create_intake_shipment_payload,
    determine_payload,
    identify_unit,
    list_destruction_records,
    read_account,
    read_label,
    read_loaner_assignment,
    read_loaner_unit,
    read_shipment,
    read_unit,
    return_loaner_payload,
    setup_accepted_shipment,
    setup_certified_units,
    setup_loaner_pool,
    setup_reference_data,
    setup_test_passed_unit,
    setup_tested_units,
    unit_version,
    validate_error,
    validate_success,
    verify_destruction_payload,
    void_label,
    void_label_payload,
    witness_destruction,
)

# Retention term of the reference model: certified_at / verification instant
# advanced by record_retention_years, which is 3 for the shared spec.
RETENTION_HORIZON = "2029-08-01T00:00:00Z"


def _as_instant(value):
    """Parse an ISO 8601 UTC instant the API returned into a comparable value."""
    assert isinstance(value, str) and value, (
        f"expected an ISO 8601 UTC instant, got {value!r}"
    )
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _assert_instant(actual, expected, field):
    """Exact instant equality, tolerant only of the ``Z`` / offset spelling."""
    assert _as_instant(actual) == _as_instant(expected), (
        f"{field} must be {expected}, got {actual!r}"
    )


def _assert_calendar_date(actual, expected_date, field):
    """The date portion of a value the PRD defines as a calendar date."""
    assert isinstance(actual, str) and actual[:10] == expected_date, (
        f"{field} must fall on {expected_date}, got {actual!r}"
    )


def _condemned_unit_with_pending_destruction_record():
    """Accepted shipment, one unit aged out on the FIRST_SEASON basis and then
    condemned, so its custody axis is PENDING_DISPOSAL and the cascade has
    raised exactly one PENDING destruction record."""
    ctx = setup_accepted_shipment(unit_count=1)
    identify_unit(
        ctx["unit"]["id"],
        ctx["model"]["id"],
        manufacture_date="2016-09-15T00:00:00Z",
        age_basis="FIRST_SEASON",
    )
    condemn_unit(ctx["unit"]["id"], "LIFE_EXPIRED")
    records = list_destruction_records(ctx["unit"]["id"])
    assert len(records) == 1, f"expected exactly one destruction record, got {records}"
    ctx["destruction_record"] = records[0]
    ctx["unit"] = read_unit(ctx["unit"]["id"])
    return ctx


def test_new_shipment_opens_in_draft_with_a_zeroed_ledger():
    """Opening an intake shipment lands in DRAFT with every later-written field null or zero.

    PRD: "A shipment opens in `DRAFT` status with `counted_unit_count`,
    `discrepancy_count`, `discrepancy_resolution`, `accepted_at`, `raw_due_at`,
    `committed_due_at`, `provisional_total_cents` and `final_total_cents` all
    null, its four disposition counters and `units_registered` at zero,
    `loaner_required` false and `settlement_locked` false."

    PRD: "A newly opened account starts with `status` set to `ACTIVE`,
    `liability_waiver_status` set to `MISSING`, and `open_shipment_count` at 0."

    Design: Corner/state_machines/new_shipment_starts_in_draft_with_a_zeroed_ledger
    """
    ctx = setup_reference_data()

    response = api_client.create_intake_shipment(
        create_intake_shipment_payload(ctx["account"]["id"], declared_unit_count=2),
        INTAKE_CLERK,
    )
    shipment = validate_success(response, 201)

    assert_intake_shipment(shipment)
    assert shipment["status"] == "DRAFT"
    for field in (
        "counted_unit_count",
        "discrepancy_count",
        "discrepancy_resolution",
        "accepted_at",
        "raw_due_at",
        "committed_due_at",
        "provisional_total_cents",
        "final_total_cents",
    ):
        assert shipment[field] is None, (
            f"a DRAFT shipment must carry {field} null, got {shipment[field]!r}"
        )
    for counter in (
        "units_registered",
        "units_in_process",
        "units_certified",
        "units_condemned",
        "units_released",
    ):
        assert shipment[counter] == 0, (
            f"a DRAFT shipment must carry {counter} at zero, got {shipment[counter]}"
        )
    assert shipment["loaner_required"] is False
    assert shipment["settlement_locked"] is False
    assert shipment["declared_unit_count"] == 2
    assert shipment["version"] == 1

    account = read_account(ctx["account"]["id"])
    assert account["open_shipment_count"] == 0, (
        "a DRAFT shipment is not yet open work, so open_shipment_count stays 0"
    )


def test_destruction_witness_then_verify_disposes_the_unit():
    """A second officer's verification moves the record to VERIFIED and the unit to DISPOSED.

    PRD: "Verification stores `verification_ref`, records `verified_by_user_id`
    from the acting `X-User-ID`, stamps `verified_at` from the logical clock, and
    advances the record `WITNESSED → VERIFIED`."

    PRD: "It also completes the unit's custody journey: the unit moves
    `custody_status` `PENDING_DISPOSAL → DISPOSED` and has its
    `record_retention_until` set to the verification instant advanced by the
    model's `record_retention_years`."

    PRD: "Witnessing stores the method and the name, records
    `witnessed_by_user_id` from the acting `X-User-ID`, stamps `witnessed_at`
    from the logical clock, advances the record `PENDING → WITNESSED`, and
    advances its `version` by one."

    Design: Corner/state_machines/destruction_record_witness_then_verify_disposes_the_unit
    """
    ctx = _condemned_unit_with_pending_destruction_record()
    record_id = ctx["destruction_record"]["id"]
    witness_destruction(
        record_id, headers=COMPLIANCE_1, method="SHELL_CRUSH", witness_name="M. Alvarez"
    )

    response = api_client.verify_destruction_record(
        record_id, verify_destruction_payload(verification_ref="DV-2026-0007"), COMPLIANCE_2
    )
    record = validate_success(response, 200)

    assert_destruction_record(record)
    assert record["status"] == "VERIFIED"
    assert record["method"] == "SHELL_CRUSH"
    assert record["witness_name"] == "M. Alvarez"
    assert record["witnessed_by_user_id"] == COMPLIANCE_OFFICER_1_USER_ID
    assert record["verified_by_user_id"] == COMPLIANCE_OFFICER_2_USER_ID
    assert record["verification_ref"] == "DV-2026-0007"
    assert record["condemn_reason_snapshot"] == "LIFE_EXPIRED"
    _assert_instant(record["witnessed_at"], CLOCK_EPOCH, "witnessed_at")
    _assert_instant(record["verified_at"], CLOCK_EPOCH, "verified_at")

    unit = read_unit(ctx["unit"]["id"])
    assert_equipment_unit(unit)
    assert unit["custody_status"] == "DISPOSED"
    assert unit["recon_status"] == "CONDEMNED"
    assert unit["condemn_reason"] == "LIFE_EXPIRED"
    assert TEST_DEFAULTS["RECORD_RETENTION_YEARS"] == 3
    _assert_instant(
        unit["record_retention_until"], RETENTION_HORIZON, "record_retention_until"
    )


def test_destruction_verify_before_witness_is_rejected():
    """Verifying a still-PENDING destruction record is refused with ERR_DESTRUCTION_STATE_INVALID.

    The expected error id is ERR_DESTRUCTION_STATE_INVALID at HTTP 409: the
    evidence cannot be certified before anyone has witnessed the shell being
    destroyed, so the unit must stay at PENDING_DISPOSAL with no retention clock.

    PRD: "The record must be in `WITNESSED` status, failing which the request is
    refused with `ERR_DESTRUCTION_STATE_INVALID` (HTTP 409), and the acting
    `X-User-ID` must differ from the record's `witnessed_by_user_id`, failing
    which it is refused with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

    Design: Corner/state_machines/destruction_verify_before_witness_rejected
    """
    ctx = _condemned_unit_with_pending_destruction_record()
    record_id = ctx["destruction_record"]["id"]

    response = api_client.verify_destruction_record(
        record_id, verify_destruction_payload(verification_ref="DV-2026-0008"), COMPLIANCE_2
    )
    validate_error(response, ApiErrorId.ERR_DESTRUCTION_STATE_INVALID.value, 409)

    record = validate_success(
        api_client.get_destruction_record(record_id, COMPLIANCE_1), 200
    )
    assert record["status"] == "PENDING"
    assert record["verified_by_user_id"] is None
    assert record["verified_at"] is None
    assert record["verification_ref"] is None
    assert record["witnessed_by_user_id"] is None

    unit = read_unit(ctx["unit"]["id"])
    assert unit["custody_status"] == "PENDING_DISPOSAL"
    assert unit["record_retention_until"] is None


def test_disassemble_a_unit_still_in_received_is_rejected():
    """Teardown before model identification is refused with ERR_UNIT_STATE_INVALID.

    The expected error id is ERR_UNIT_STATE_INVALID at HTTP 409, because tearing
    a shell down before its model has been confirmed would destroy the age
    evidence the plant's liability rests on.

    PRD: "Attempting teardown from any status other than `IDENTIFIED` yields
    `ERR_UNIT_STATE_INVALID` (HTTP 409)."

    PRD: "Registration creates the unit with `recon_status` `RECEIVED` and
    `custody_status` `AT_PLANT`, and increments the shipment's `units_registered`
    by one."

    Design: Corner/state_machines/disassemble_a_unit_still_in_received_rejected
    """
    ctx = setup_accepted_shipment(unit_count=1)
    assert ctx["unit"]["recon_status"] == "RECEIVED"

    response = api_client.disassemble_equipment_unit(ctx["unit"]["id"], TECHNICIAN_1)
    validate_error(response, ApiErrorId.ERR_UNIT_STATE_INVALID.value, 409)

    unit = read_unit(ctx["unit"]["id"])
    assert unit["recon_status"] == "RECEIVED"
    assert unit["custody_status"] == "AT_PLANT"
    assert unit["model_spec_id"] is None

    shipment = read_shipment(ctx["shipment"]["id"])
    assert shipment["status"] == "ACCEPTED", (
        "a refused teardown must not drive the shipment into IN_PROCESS"
    )


def test_accepting_the_same_shipment_twice_is_rejected():
    """A second acceptance is refused with ERR_SHIPMENT_STATE_INVALID and re-runs no side effect.

    The expected error id is ERR_SHIPMENT_STATE_INVALID at HTTP 409, and the
    first acceptance's stamps must survive untouched: accepted_at stays on the
    logical clock, provisional_total_cents stays 9176 and the account keeps
    exactly one open shipment.

    PRD: "Supplying a resolution that no accept transition is defined for, given
    the shipment's branch, is rejected with `ERR_SHIPMENT_STATE_INVALID` (HTTP
    409), as is any accept attempted from a status other than `COUNTED` or
    `QUARANTINED`."

    PRD: "On the owning account, `open_shipment_count` increases by one and
    `loaner_recall_due_at` is cleared to null."

    Design: Corner/state_machines/accept_the_same_shipment_twice_rejected
    """
    ctx = setup_accepted_shipment(unit_count=1, service_tier="STANDARD")
    assert ctx["shipment"]["status"] == "ACCEPTED"

    response = api_client.accept_intake_shipment(
        ctx["shipment"]["id"], accept_shipment_payload("MATCHED"), INTAKE_CLERK
    )
    validate_error(response, ApiErrorId.ERR_SHIPMENT_STATE_INVALID.value, 409)

    shipment = read_shipment(ctx["shipment"]["id"])
    assert shipment["status"] == "ACCEPTED"
    _assert_instant(shipment["accepted_at"], CLOCK_EPOCH, "accepted_at")
    assert shipment["provisional_total_cents"] == 9176, (
        "one STANDARD unit prices 8996 exactly, no discount below 10000 cents, "
        "plus a 2 percent surcharge of 180 cents"
    )
    assert shipment["units_in_process"] == 1
    assert shipment["units_certified"] == 0
    assert shipment["units_condemned"] == 0
    assert shipment["units_released"] == 0
    assert_disposition_ledger_conserved(shipment)

    account = read_account(ctx["account"]["id"])
    assert account["open_shipment_count"] == 1


def test_voiding_an_already_voided_label_is_rejected():
    """VOIDED is terminal: the second void is refused with ERR_LABEL_ALREADY_VOIDED.

    The expected error id is ERR_LABEL_ALREADY_VOIDED at HTTP 409, and the
    compensating hops must not run twice — the first void already moved the one
    unit back out of units_certified, so units_in_process stays 1, not 2.

    PRD: "The label must still be `ACTIVE`; a second void on an
    already-`VOIDED` label is refused with `ERR_LABEL_ALREADY_VOIDED` (HTTP 409)."

    PRD: "Second, the unit reverts `CERTIFIED → REPAIR_PENDING`, and both its
    `certified_at` and its `record_retention_until` are cleared to null — the
    retention clock never started, because the certification never happened."

    PRD: "Because every mutation is a paired decrement and increment, the four
    counters can never drift away from `counted_unit_count`."

    Design: Corner/state_machines/void_an_already_voided_label_rejected
    """
    ctx = setup_certified_units(unit_count=1)
    label_id = ctx["label"]["id"]
    void_label(label_id, COMPLIANCE_1, void_reason="decal misprint")

    response = api_client.void_certification_label(
        label_id, void_label_payload(void_reason="duplicate void attempt"), COMPLIANCE_1
    )
    validate_error(response, ApiErrorId.ERR_LABEL_ALREADY_VOIDED.value, 409)

    label = read_label(label_id)
    assert label["status"] == "VOIDED"
    assert label["void_reason"] == "decal misprint", (
        "the refused second void must not overwrite the recorded void reason"
    )
    assert label["voided_by_user_id"] == COMPLIANCE_OFFICER_1_USER_ID

    shipment = read_shipment(ctx["shipment"]["id"])
    assert shipment["units_in_process"] == 1
    assert shipment["units_certified"] == 0
    assert shipment["status"] == "IN_PROCESS"
    assert shipment["settlement_locked"] is False
    assert_disposition_ledger_conserved(shipment)

    unit = read_unit(ctx["unit"]["id"])
    assert unit["recon_status"] == "REPAIR_PENDING"
    assert unit["certified_at"] is None
    assert unit["record_retention_until"] is None

    account = read_account(ctx["account"]["id"])
    assert account["open_shipment_count"] == 1


def test_label_issue_stamps_certified_at_and_the_retention_window():
    """Issuing the label certifies the unit and opens its record-retention window.

    PRD: "The unit advances `TEST_PASSED → CERTIFIED`, has `certified_at`
    stamped from the logical clock, and has `record_retention_until` set to
    `certified_at` advanced by the model's `record_retention_years`."

    PRD: "`standard_code_snapshot` is a copy of the model's `standard_code`,
    taken at issue time so that a later change to the model specification cannot
    alter a label already affixed to a shell."

    PRD: "On the parent shipment, `units_in_process` falls by one and
    `units_certified` rises by one; if that brings `units_in_process` to 0, the
    shipment advances `IN_PROCESS → READY_FOR_RETURN`, which in turn decrements
    the account's `open_shipment_count` and, when that reaches 0, sets the
    account's `loaner_recall_due_at` to the clock plus 14 days."

    Design: Corner/state_machines/label_issue_stamps_certified_at_and_retention_window
    """
    ctx = setup_test_passed_unit()
    unit_id = ctx["unit"]["id"]
    assert ctx["unit"]["recon_status"] == "TEST_PASSED"

    response = api_client.create_certification_label(
        create_certification_label_payload(unit_id, unit_version(unit_id)), INSPECTOR_1
    )
    label = validate_success(response, 201)

    assert_certification_label(label)
    assert label["status"] == "ACTIVE"
    assert label["standard_code_snapshot"] == TEST_DEFAULTS["STANDARD_CODE"] == "ND002"
    assert_label_code(label, "ND002", "20260801", 1)
    _assert_calendar_date(label["certified_on"], "2026-08-01", "certified_on")
    assert label["issued_by_user_id"] == CERTIFYING_INSPECTOR_1_USER_ID
    assert label["void_reason"] is None
    assert label["voided_at"] is None
    assert label["voided_by_user_id"] is None
    assert label["equipment_unit_id"] == unit_id

    unit = read_unit(unit_id)
    assert unit["recon_status"] == "CERTIFIED"
    assert unit["custody_status"] == "AT_PLANT", (
        "certification is the reconditioning axis; custody only moves on staging"
    )
    _assert_instant(unit["certified_at"], CLOCK_EPOCH, "certified_at")
    _assert_instant(
        unit["record_retention_until"], RETENTION_HORIZON, "record_retention_until"
    )

    shipment = read_shipment(ctx["shipment"]["id"])
    assert shipment["units_certified"] == 1
    assert shipment["units_in_process"] == 0
    assert_disposition_ledger_conserved(shipment)


def test_loaner_return_releases_the_unit_back_to_available():
    """Returning the assignment drops the sibling loaner back to AVAILABLE without unwinding its history.

    PRD: "The return stamps `returned_at` from the logical clock, advances the
    assignment `RESERVED → RETURNED` or `OUT_ON_LOAN → RETURNED`, drives the
    loaner back `RESERVED → AVAILABLE` or `OUT_ON_LOAN → AVAILABLE` as
    appropriate, and advances both the assignment's and the loaner's `version` by
    one."

    PRD: "A new loaner enters the pool with `status` `AVAILABLE` and
    `assignment_count` at 0, where `assignment_count` counts every assignment
    ever created against that loaner."

    Design: Corner/state_machines/loaner_return_releases_the_unit_back_to_available
    """
    ctx = setup_loaner_pool(grades=("A",))
    assignment = book_loaner(
        ctx["account"]["id"],
        ctx["model"]["id"],
        loaner_unit_id=ctx["loaner"]["id"],
        window_start="2026-08-05T00:00:00Z",
        window_end="2026-08-12T00:00:00Z",
    )
    assert assignment["status"] == "RESERVED"

    response = api_client.return_loaner_assignment(
        assignment["id"],
        return_loaner_payload(return_condition_note="shell scuffed, pads intact"),
        INTAKE_CLERK,
    )
    returned = validate_success(response, 200)

    assert_loaner_assignment(returned)
    assert returned["status"] == "RETURNED"
    _assert_instant(returned["returned_at"], CLOCK_EPOCH, "returned_at")

    loaner = read_loaner_unit(ctx["loaner"]["id"])
    assert_loaner_unit(loaner)
    assert loaner["status"] == "AVAILABLE"
    assert loaner["assignment_count"] == 1, (
        "assignment_count counts bookings ever made, so a return must not decrement it"
    )

    reread = read_loaner_assignment(assignment["id"])
    assert reread["status"] == "RETURNED"
    assert reread["loaner_unit_id"] == ctx["loaner"]["id"]


def test_determination_override_escalates_a_pass_result_to_condemn():
    """An inspector may sign CONDEMN over a PASS machine result when an override reason is supplied.

    PRD: "If an `override_reason` is present but the signed determination is
    *less* severe than `computed_result` under the severity ordering in which
    `PASS` is least severe, `REPAIR` more severe, and `CONDEMN` most severe, the
    signature is refused with `ERR_DETERMINATION_UPGRADE_FORBIDDEN` (HTTP 422)."

    PRD: "An inspector may always be stricter than the rig; never more lenient."

    PRD: "A `CONDEMN` determination advances the unit `TESTED → CONDEMNED` and
    carries no `condemn_required` precondition at all — condemnation is always
    available."

    PRD: "The condemn reason recorded by the determination path differs only in
    its precedence list, which prefers `SI_EXCEEDS_LIMIT` where the pre-test path
    prefers `NOT_RECONDITIONABLE`, and the repair-exhaustion path always records
    `REPAIR_UNSUCCESSFUL`."

    PRD: "Hop one moves the unit's `custody_status` `AT_PLANT →
    PENDING_DISPOSAL`, advancing the unit's `version`."

    Design: Corner/state_machines/determination_override_escalates_a_pass_result_to_condemn
    """
    ctx = setup_tested_units(unit_count=1, impacts=PASS_IMPACTS)
    session_id = ctx["shell_test"]["id"]
    assert ctx["shell_test"]["computed_result"] == "PASS"
    assert ctx["unit"]["recon_status"] == "TESTED"
    assert ctx["unit"]["life_expired"] is False
    assert ctx["unit"]["inspection_verdict_summary"] == "CLEAR"

    override_reason = (
        "hairline crown crazing visible under UV, not captured by the impact metric"
    )
    payload = determine_payload("CONDEMN")
    payload["override_reason"] = override_reason

    response = api_client.determine_shell_test(session_id, payload, INSPECTOR_1)
    session = validate_success(response, 200)

    assert_shell_test(session)
    assert session["computed_result"] == "PASS", (
        "the machine's own reading is preserved even when the inspector escalates"
    )
    assert session["determination"] == "CONDEMN"
    assert session["override_reason"] == override_reason
    assert session["status"] == "DETERMINED"
    assert session["determined_by_user_id"] == CERTIFYING_INSPECTOR_1_USER_ID

    unit = read_unit(ctx["unit"]["id"])
    assert unit["recon_status"] == "CONDEMNED"
    assert unit["condemn_reason"] == "SI_EXCEEDS_LIMIT"
    assert unit["custody_status"] == "PENDING_DISPOSAL"

    records = list_destruction_records(ctx["unit"]["id"])
    assert len(records) == 1, f"the cascade must raise one destruction record, got {records}"
    assert records[0]["status"] == "PENDING"
    assert records[0]["condemn_reason_snapshot"] == "SI_EXCEEDS_LIMIT"

    shipment = read_shipment(ctx["shipment"]["id"])
    assert shipment["units_condemned"] == 1
    assert shipment["units_in_process"] == 0
    assert_disposition_ledger_conserved(shipment)
