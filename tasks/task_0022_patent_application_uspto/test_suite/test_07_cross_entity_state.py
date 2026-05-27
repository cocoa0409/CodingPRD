"""Cross-entity state dependencies: an OfficeActionResponse can only be
created when the referenced OfficeAction is OUTSTANDING; a MaintenanceFee
payment can only occur when the parent Application is ISSUED (not EXPIRED).
"""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS, make_applicant_headers,
    set_clock, run_sweep,
    setup_application_with_outstanding_oa,
    setup_utility_with_maintenance_fees,
    file_oa_response, get_application,
    create_office_action_response_payload, create_fee_payment_payload,
    pay_maintenance, list_maintenance_fees,
    maintenance_base_fee_cents,
)


# =============================================================================
# Difficulty / cross_entity_state_dependency /
#   response_requires_oa_outstanding_cross_oar_oa_pair
# =============================================================================

def test_second_response_against_already_responded_oa_rejected_invalid_state(api):
    """A second POST /office-action-responses against the same OA whose
    status is already RESPONDED is rejected. Per PRD §2.7, RESPONDED is in
    the OfficeAction's terminal set, so the rejection is ERR_TERMINAL_STATE.

    PRD §2.7: "...`ERR_TERMINAL_STATE` if the source state is in the entity's
    terminal set — namely `ABANDONED`, `EXPIRED`, `CONVERTED` for an
    application, `RESPONDED`, `EXPIRED`, `WITHDRAWN` for an office action..."

    Design: Difficulty/cross_entity_state_dependency/response_requires_oa_outstanding_cross_oar_oa_pair
    """
    set_clock("2026-01-01T00:00:00.000Z")
    applicant, application, oa = setup_application_with_outstanding_oa(
        entity_size="LARGE", action_type="NON_FINAL",
    )
    # First response — accepted.
    file_oa_response(applicant, oa["id"], extension_months_requested=0,
                     claim_amendment_count=10)

    # Second response — must be rejected: OA.status=RESPONDED is terminal.
    res = api.create_office_action_response(
        create_office_action_response_payload(
            office_action_id=oa["id"],
            extension_months_requested=0, claim_amendment_count=10,
        ),
        make_applicant_headers(applicant["id"]),
    )
    validate_error(res, ApiErrorId.ERR_TERMINAL_STATE.value)

    oa_after = validate_success(
        api.get_office_action(oa["id"], TEST_USERS["examiner_headers"]), 200,
    )
    assert oa_after["status"] == "RESPONDED", (
        f"OA must remain RESPONDED after rejected second response, got {oa_after['status']}"
    )


def test_oa_status_unchanged_after_failed_response_attempt(api):
    """The rejection leaves the OA's status untouched — the cross-entity
    dependency means the response payload is rejected without mutating the
    parent OA.

    PRD §3.5: "When the office action is in `OUTSTANDING` and is not a
    `NOTICE_OF_ALLOWANCE` (notices are responded to via the issue-fee
    payment, not via an office-action response), the applicant files a
    response by submitting `office_action_id`, `extension_months_requested`,
    and `claim_amendment_count`."

    Design: Difficulty/cross_entity_state_dependency/response_requires_oa_outstanding_cross_oar_oa_pair
    """
    set_clock("2026-01-01T00:00:00.000Z")
    applicant, application, oa = setup_application_with_outstanding_oa(
        entity_size="LARGE", action_type="NON_FINAL",
    )
    file_oa_response(applicant, oa["id"], extension_months_requested=0,
                     claim_amendment_count=10)
    oa_mid = validate_success(
        api.get_office_action(oa["id"], TEST_USERS["examiner_headers"]), 200,
    )
    mid_version = oa_mid["version"]

    # Second response — rejected.
    api.create_office_action_response(
        create_office_action_response_payload(
            office_action_id=oa["id"],
            extension_months_requested=0, claim_amendment_count=10,
        ),
        make_applicant_headers(applicant["id"]),
    )

    oa_final = validate_success(
        api.get_office_action(oa["id"], TEST_USERS["examiner_headers"]), 200,
    )
    assert oa_final["status"] == "RESPONDED"
    assert oa_final["version"] == mid_version, (
        f"OA.version must be unchanged after rejected response, "
        f"was {mid_version}, now {oa_final['version']}"
    )


# =============================================================================
# Difficulty / cross_entity_state_dependency /
#   maintenance_payment_requires_application_issued_cross_feepay_app_pair
# =============================================================================

def test_maintenance_payment_on_expired_application_rejected(api):
    """After a maintenance window LAPSED on a UTILITY (parent Application
    cascaded ISSUED→EXPIRED), payments against a still-PENDING window of
    the same application are rejected because the parent is no longer
    ISSUED.

    PRD §3.8: "Maintenance payments must satisfy four windows of constraint.
    First, the parent application must still be in `ISSUED` — a payment
    against a row whose parent has already been expired is rejected as an
    invalid state."

    Design: Difficulty/cross_entity_state_dependency/maintenance_payment_requires_application_issued_cross_feepay_app_pair
    """
    set_clock("2020-01-01T00:00:00.000Z")
    applicant, application, fees = setup_utility_with_maintenance_fees(
        entity_size="LARGE")
    w2 = sorted(fees, key=lambda f: f["window_number"])[1]

    # Advance past W1 grace (2024-07-01). Sweep → W1 LAPSED, application EXPIRED.
    set_clock("2024-07-02T00:00:00.000Z")
    run_sweep()
    app_after_sweep = get_application(application["id"], applicant)
    assert app_after_sweep["status"] == "EXPIRED", (
        f"Application must cascade to EXPIRED after W1 LAPSE, "
        f"got {app_after_sweep['status']}"
    )

    # Even within W2's chronological window, payment must fail because
    # parent is EXPIRED. PRD §2.7 classifies EXPIRED as a terminal state of
    # Application, so the rejection is ERR_TERMINAL_STATE (the PRD §3.8
    # "invalid state" phrase is informal English; §2.7 is authoritative).
    set_clock("2026-01-01T00:00:00.000Z")
    res = api.create_fee_payment(
        create_fee_payment_payload(
            application_id=application["id"],
            payment_category="MAINTENANCE_W2",
            amount_cents=maintenance_base_fee_cents(2, "LARGE"),  # 376000
            maintenance_fee_id=w2["id"],
        ),
        make_applicant_headers(applicant["id"]),
    )
    validate_error(res, ApiErrorId.ERR_TERMINAL_STATE.value)


def test_application_status_remains_expired_after_failed_payment(api):
    """The rejection does not transition the parent back to ISSUED — once
    EXPIRED is a terminal state from which the only further status change
    is none (terminal lockdown per PRD §2.7).

    PRD §3.8: "Maintenance payments must satisfy four windows of constraint.
    First, the parent application must still be in `ISSUED` — a payment
    against a row whose parent has already been expired is rejected as an
    invalid state."

    Design: Difficulty/cross_entity_state_dependency/maintenance_payment_requires_application_issued_cross_feepay_app_pair
    """
    set_clock("2020-01-01T00:00:00.000Z")
    applicant, application, fees = setup_utility_with_maintenance_fees(
        entity_size="LARGE")
    w2 = sorted(fees, key=lambda f: f["window_number"])[1]

    set_clock("2024-07-02T00:00:00.000Z")
    run_sweep()
    set_clock("2026-01-01T00:00:00.000Z")

    api.create_fee_payment(
        create_fee_payment_payload(
            application_id=application["id"],
            payment_category="MAINTENANCE_W2",
            amount_cents=376000,
            maintenance_fee_id=w2["id"],
        ),
        make_applicant_headers(applicant["id"]),
    )
    app_after = get_application(application["id"], applicant)
    assert app_after["status"] == "EXPIRED", (
        f"Application.status must remain EXPIRED, got {app_after['status']}"
    )
