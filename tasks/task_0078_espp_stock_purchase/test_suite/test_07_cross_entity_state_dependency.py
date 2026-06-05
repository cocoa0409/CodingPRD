"""Difficulty rule 7 — cross-entity state dependencies (PRD §3.3, §3.4).

A Contribution depends on its Enrollment's state; opening a PurchasePeriod depends
on its parent OfferingPeriod's state.
"""
from test_helpers import (
    validate_error,
    get_success_data,
    create_contribution_payload,
    create_purchase_period_payload,
    setup_enrolled_participant,
    setup_open_offering,
    make_participant_headers,
)


def test_contribution_on_suspended_enrollment_rejected(api, admin_headers):
    """PRD §3.3: "A contribution may be posted only against an enrollment currently in
    ENROLLED status; posting against an enrollment that is SUSPENDED, WITHDRAWN, or
    COMPLETED is rejected with ERR_ENROLLMENT_NOT_CONTRIBUTING (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/contribution_requires_enrolled_enrollment
    """
    _, _, participant, enrollment = setup_enrolled_participant(rate_pct=10)
    ph = make_participant_headers(participant["id"])
    get_success_data(api.suspend_enrollment(enrollment["id"], ph))
    resp = api.create_contribution(
        create_contribution_payload(enrollment["id"], gross_pay_cents=500000),
        admin_headers,
    )
    validate_error(resp, "ERR_ENROLLMENT_NOT_CONTRIBUTING")


def test_contribution_on_suspended_enrollment_status_409(api, admin_headers):
    """PRD §3.3: "A contribution may be posted only against an enrollment currently in
    ENROLLED status; posting against an enrollment that is SUSPENDED, WITHDRAWN, or
    COMPLETED is rejected with ERR_ENROLLMENT_NOT_CONTRIBUTING (HTTP 409)."

    Second test of the instance: confirm HTTP 409 accompanies the error id.

    Design: Difficulty/cross_entity_state_dependency/contribution_requires_enrolled_enrollment
    """
    _, _, participant, enrollment = setup_enrolled_participant(rate_pct=10)
    ph = make_participant_headers(participant["id"])
    get_success_data(api.suspend_enrollment(enrollment["id"], ph))
    resp = api.create_contribution(
        create_contribution_payload(enrollment["id"], gross_pay_cents=500000),
        admin_headers,
    )
    validate_error(resp, "ERR_ENROLLMENT_NOT_CONTRIBUTING", expected_status=409)


def test_open_batch_while_offering_open_rejected(api, admin_headers):
    """PRD §3.4: "Opening is permitted only when the batch is currently PENDING, when
    its parent offering is in ENROLLMENT_CLOSED or ACTIVE ... Any transition from a
    state in which it is not defined is rejected with ERR_INVALID_STATE (HTTP 409)."
    PRD §3.3: "Any transition from a state in which it is not defined is rejected with
    ERR_INVALID_STATE (HTTP 409)."

    The parent offering is still OPEN (enrollment not closed), so opening the PENDING
    batch is rejected with ERR_INVALID_STATE.

    Design: Difficulty/cross_entity_state_dependency/open_purchase_period_requires_offering_enrollment_closed
    """
    _, offering = setup_open_offering()
    batch = get_success_data(
        api.create_purchase_period(
            offering["id"], create_purchase_period_payload(), admin_headers
        )
    )
    resp = api.open_purchase_period(batch["id"], admin_headers)
    validate_error(resp, "ERR_INVALID_STATE")


def test_open_batch_while_offering_open_status_409(api, admin_headers):
    """PRD §3.4: "Opening is permitted only when the batch is currently PENDING, when
    its parent offering is in ENROLLMENT_CLOSED or ACTIVE ... Any transition from a
    state in which it is not defined is rejected with ERR_INVALID_STATE (HTTP 409)."

    Second test of the instance: confirm HTTP 409 accompanies the error id.

    Design: Difficulty/cross_entity_state_dependency/open_purchase_period_requires_offering_enrollment_closed
    """
    _, offering = setup_open_offering()
    batch = get_success_data(
        api.create_purchase_period(
            offering["id"], create_purchase_period_payload(), admin_headers
        )
    )
    resp = api.open_purchase_period(batch["id"], admin_headers)
    validate_error(resp, "ERR_INVALID_STATE", expected_status=409)
