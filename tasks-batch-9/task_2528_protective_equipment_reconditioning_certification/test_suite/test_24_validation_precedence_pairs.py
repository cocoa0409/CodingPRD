"""Requests that break two rules at once and must name the earlier rung.

Each pair is asserted twice: once where the earlier rung fires, and once with
that earlier violation removed so the later rung surfaces on the same request.
"""
from test_helpers import (
    ApiErrorId,
    INSPECTOR_1,
    INTAKE_CLERK,
    api_client,
    create_certification_label_payload,
    create_loaner_assignment_payload,
    hold_account,
    list_labels,
    read_loaner_unit,
    read_unit,
    setup_determined_units,
    setup_loaner_pool,
    setup_tested_units,
    unit_version,
    validate_error,
)


def test_a_label_issue_on_a_tested_unit_reports_the_state_error_not_the_hold():
    """A unit still in TESTED under a program on billing hold breaks the state
    guard and the fiscal guard together; the state guard is evaluated first.

    PRD §2.7: "A label issue against a unit still in `TESTED` (rather than
    `TEST_PASSED`) whose owning program is simultaneously on a billing hold
    returns `ERR_UNIT_STATE_INVALID` (HTTP 409), because the state rung precedes
    the fiscal rung; move that same unit to `TEST_PASSED` and the identical
    request returns `ERR_ACCOUNT_ON_HOLD` (HTTP 402)."

    Design: Difficulty/priority_pair_validation_conflict/label_issue_state_error_wins_over_billing_hold_error
    """
    ctx = setup_tested_units(unit_count=1)
    account = hold_account(ctx["account"]["id"])
    assert account["status"] == "BILLING_HOLD"

    unit_id = ctx["unit"]["id"]
    assert read_unit(unit_id)["recon_status"] == "TESTED"
    response = api_client.create_certification_label(
        create_certification_label_payload(unit_id, unit_version(unit_id)), INSPECTOR_1
    )

    validate_error(response, ApiErrorId.ERR_UNIT_STATE_INVALID, 409)
    assert list_labels(unit_id) == []


def test_the_same_label_issue_from_test_passed_reports_the_billing_hold():
    """Once the unit is in TEST_PASSED the state guard is satisfied and the
    identical request falls through to the fiscal rung.

    PRD §2.7: "A label issue against a unit still in `TESTED` (rather than
    `TEST_PASSED`) whose owning program is simultaneously on a billing hold
    returns `ERR_UNIT_STATE_INVALID` (HTTP 409), because the state rung precedes
    the fiscal rung; move that same unit to `TEST_PASSED` and the identical
    request returns `ERR_ACCOUNT_ON_HOLD` (HTTP 402)."

    Design: Difficulty/priority_pair_validation_conflict/label_issue_state_error_wins_over_billing_hold_error
    """
    ctx = setup_determined_units(unit_count=1, determination="PASS")
    hold_account(ctx["account"]["id"])

    unit_id = ctx["unit"]["id"]
    assert read_unit(unit_id)["recon_status"] == "TEST_PASSED"
    response = api_client.create_certification_label(
        create_certification_label_payload(unit_id, unit_version(unit_id)), INSPECTOR_1
    )

    validate_error(response, ApiErrorId.ERR_ACCOUNT_ON_HOLD, 402)
    assert list_labels(unit_id) == []


def test_a_loaner_booking_without_a_waiver_reports_the_waiver_error_not_the_hold():
    """A program that never signed a waiver and is also on billing hold trips the
    referential rung first.

    PRD §2.7: "Likewise, a loaner booking for a program that has never
    acknowledged a waiver *and* is on a billing hold returns
    `ERR_LIABILITY_WAIVER_MISSING` (HTTP 409), because the referential rung
    precedes the fiscal rung; acknowledge the current waiver revision and the
    same request returns `ERR_ACCOUNT_ON_HOLD` (HTTP 402)."

    Design: Difficulty/priority_pair_validation_conflict/loaner_booking_waiver_error_wins_over_billing_hold_error
    """
    ctx = setup_loaner_pool(waiver=False, billing_hold=True)
    assert ctx["account"]["liability_waiver_status"] == "MISSING"
    assert ctx["account"]["status"] == "BILLING_HOLD"

    response = api_client.create_loaner_assignment(
        create_loaner_assignment_payload(
            ctx["account"]["id"], ctx["model"]["id"], loaner_unit_id=ctx["loaner"]["id"]
        ),
        INTAKE_CLERK,
    )

    validate_error(response, ApiErrorId.ERR_LIABILITY_WAIVER_MISSING, 409)
    loaner = read_loaner_unit(ctx["loaner"]["id"])
    assert loaner["status"] == "AVAILABLE"
    assert loaner["assignment_count"] == 0


def test_the_same_booking_with_the_waiver_on_file_reports_the_billing_hold():
    """With the current revision acknowledged the referential rung is satisfied
    and the identical booking reports the fiscal rung instead.

    PRD §2.7: "Likewise, a loaner booking for a program that has never
    acknowledged a waiver *and* is on a billing hold returns
    `ERR_LIABILITY_WAIVER_MISSING` (HTTP 409), because the referential rung
    precedes the fiscal rung; acknowledge the current waiver revision and the
    same request returns `ERR_ACCOUNT_ON_HOLD` (HTTP 402)."

    Design: Difficulty/priority_pair_validation_conflict/loaner_booking_waiver_error_wins_over_billing_hold_error
    """
    ctx = setup_loaner_pool(waiver=True, billing_hold=True)
    assert ctx["account"]["liability_waiver_status"] == "ON_FILE"
    assert ctx["account"]["status"] == "BILLING_HOLD"

    response = api_client.create_loaner_assignment(
        create_loaner_assignment_payload(
            ctx["account"]["id"], ctx["model"]["id"], loaner_unit_id=ctx["loaner"]["id"]
        ),
        INTAKE_CLERK,
    )

    validate_error(response, ApiErrorId.ERR_ACCOUNT_ON_HOLD, 402)
    assert read_loaner_unit(ctx["loaner"]["id"])["assignment_count"] == 0
