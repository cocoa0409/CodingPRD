"""Operations gated by the state of a neighbouring entity.

Impact recording depends on the rig's calibration currency, and label issuance
depends on the owning program's commercial posture.
"""
from test_helpers import (
    ApiErrorId,
    INSPECTOR_1,
    PLANT_MANAGER,
    TECHNICIAN_1,
    api_client,
    assert_label_code,
    create_bench,
    create_certification_label_payload,
    get_success_data,
    hold_account,
    issue_label,
    list_labels,
    read_account,
    read_shell_test,
    read_unit,
    record_impacts_payload,
    schedule_shell_test,
    setup_determined_units,
    setup_inspected_units,
    unit_version,
    validate_error,
)


def test_impacts_cannot_be_recorded_on_a_rig_whose_calibration_has_lapsed():
    """A rig calibrated only through 1 July 2026 cannot host a run on 1 August
    2026, and the refusal leaves the session unrun.

    PRD §3.5: "The rig's calibration must still be current: if the bench's
    `calibration_valid_until` is null, or falls earlier than the logical clock,
    the recording is rejected with `ERR_BENCH_CALIBRATION_EXPIRED` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/impact_recording_blocked_by_expired_bench_calibration
    """
    ctx = setup_inspected_units(unit_count=1, bench=False)
    bench = create_bench(calibration_valid_until="2026-07-01T00:00:00Z")
    session = schedule_shell_test(ctx["unit"]["id"], bench["id"])

    response = api_client.record_impacts(
        session["id"], record_impacts_payload(300, 300, 300), TECHNICIAN_1
    )

    validate_error(response, ApiErrorId.ERR_BENCH_CALIBRATION_EXPIRED, 409)

    session = read_shell_test(session["id"])
    assert session["status"] == "SCHEDULED"
    assert session["severity_index"] is None
    assert session["computed_result"] is None
    assert session["peak_g_front"] is None

    unit = read_unit(ctx["unit"]["id"])
    assert unit["recon_status"] == "INSPECTED"
    assert unit["current_si"] is None


def test_impacts_cannot_be_recorded_on_a_rig_that_was_never_calibrated():
    """A freshly registered rig carries no calibration expiry at all, so it cannot
    host a single run until a plant manager calibrates it.

    PRD §3.2: "A newly registered rig has a null `calibration_valid_until` and
    therefore cannot host a single session until a `PlantManager` calibrates it;
    calibration supplies the `calibration_valid_until` expiry directly and
    advances the bench's `version` by one." The refusal is the same one a lapsed
    expiry earns: PRD §3.5: "The rig's calibration must still be current: if the
    bench's `calibration_valid_until` is null, or falls earlier than the logical
    clock, the recording is rejected with `ERR_BENCH_CALIBRATION_EXPIRED` (HTTP
    409)." The expected error id is
    ERR_BENCH_CALIBRATION_EXPIRED.

    Design: Difficulty/cross_entity_state_dependency/impact_recording_blocked_by_expired_bench_calibration
    """
    ctx = setup_inspected_units(unit_count=1, bench=False)
    bench = create_bench(calibrate=False)
    assert bench["calibration_valid_until"] is None
    session = schedule_shell_test(ctx["unit"]["id"], bench["id"])

    response = api_client.record_impacts(
        session["id"], record_impacts_payload(300, 300, 300), TECHNICIAN_1
    )

    validate_error(response, ApiErrorId.ERR_BENCH_CALIBRATION_EXPIRED, 409)
    assert read_shell_test(session["id"])["status"] == "SCHEDULED"
    assert read_unit(ctx["unit"]["id"])["recon_status"] == "INSPECTED"


def test_a_billing_hold_on_the_owning_program_blocks_the_label_issue():
    """A passing shell whose program is on billing hold cannot be certified, and
    the refusal leaves the unit in TEST_PASSED with no label on file.

    PRD §3.7: "The owning program's account `status` must be `ACTIVE`; a
    `BILLING_HOLD` account blocks the issue with `ERR_ACCOUNT_ON_HOLD` (HTTP
    402)."

    Design: Difficulty/cross_entity_state_dependency/label_issue_blocked_by_owning_account_billing_hold
    """
    ctx = setup_determined_units(unit_count=1, determination="PASS")
    hold_account(ctx["account"]["id"])
    unit_id = ctx["unit"]["id"]

    response = api_client.create_certification_label(
        create_certification_label_payload(unit_id, unit_version(unit_id)), INSPECTOR_1
    )

    validate_error(response, ApiErrorId.ERR_ACCOUNT_ON_HOLD, 402)

    unit = read_unit(unit_id)
    assert unit["recon_status"] == "TEST_PASSED"
    assert unit["certified_at"] is None
    assert unit["record_retention_until"] is None
    assert list_labels(unit_id) == []


def test_clearing_the_hold_returns_the_account_to_active_and_lets_the_issue_through():
    """Releasing the hold puts the program back to ACTIVE, and the identical issue
    request then certifies the shell.

    PRD §3.1: "when `hold` is false the `status` returns to `ACTIVE` and
    `billing_hold_reason` is cleared to null."

    Design: Difficulty/cross_entity_state_dependency/label_issue_blocked_by_owning_account_billing_hold
    """
    ctx = setup_determined_units(unit_count=1, determination="PASS")
    account_id = ctx["account"]["id"]
    hold_account(account_id)

    cleared = get_success_data(
        api_client.set_billing_hold(account_id, {"hold": False}, PLANT_MANAGER)
    )
    assert cleared["status"] == "ACTIVE"
    assert cleared["billing_hold_reason"] is None

    label = issue_label(ctx["unit"]["id"])

    assert label["status"] == "ACTIVE"
    assert_label_code(label, "ND002", "20260801", 1)
    assert read_unit(ctx["unit"]["id"])["recon_status"] == "CERTIFIED"
    assert read_account(account_id)["status"] == "ACTIVE"
