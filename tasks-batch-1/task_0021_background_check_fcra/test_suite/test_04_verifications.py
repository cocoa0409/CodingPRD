"""Verification creation/dispute invalid-state and duplicate-type constraints.
"""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    order_with_three_pending_verifications,
    make_applicant_headers, make_recruiter_headers,
)


def test_dispute_a_pending_verification_returns_invalid_state(api):
    """A PENDING verification cannot be disputed; only a REPORTED one can.
    PRD §3.5 establishes the precondition.

    PRD §3.5: "Disputing is only legal from `REPORTED`, and only when the
    parent order's `status` is `IN_REVIEW` or `COMPLETE`."

    Design: Corner/state_machines/verification_dispute_from_pending_rejects_with_invalid_state
    """
    (jur, applicant, app, consent, order,
     crim, mvr, edu) = order_with_three_pending_verifications(state_code="MT")
    resp = api.dispute_verification(
        crim["id"],
        {"dispute_reason": "premature",
         "expected_verification_version": crim["version"]},
        make_applicant_headers(applicant["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_second_criminal_verification_on_same_order_rejected_duplicate_type(api):
    """Exactly one Verification of each type (CRIMINAL/MVR/EDUCATION) is
    permitted per order. A second CRIMINAL is rejected with
    ERR_DUPLICATE_VERIFICATION_TYPE.

    PRD §3.4: "A background check order has exactly three child
    `Verification` rows — one of each `verification_type`: `CRIMINAL`,
    `MVR`, and `EDUCATION`. The recruiter creates each by supplying only
    the `verification_type`; the row is inserted in `PENDING` with
    `order_id` set to the parent order. A second verification of a type
    already present on the same order is rejected with
    `ERR_DUPLICATE_VERIFICATION_TYPE`."

    Design: Difficulty/resource_temporal_overlap/verification_categorical_slot_uniqueness_per_order
    """
    (jur, applicant, app, consent, order,
     crim, mvr, edu) = order_with_three_pending_verifications(state_code="WI",
                                                              recruiter_id="rec-leo")
    # Attempt a second CRIMINAL on the same order.
    resp = api.create_verification(
        order["id"], {"verification_type": "CRIMINAL"},
        make_recruiter_headers("rec-leo"),
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_VERIFICATION_TYPE.value)


def test_cancel_an_order_in_in_review_returns_invalid_state(api):
    """POST /background-check-orders/{id}/cancel is only legal from PENDING;
    from IN_REVIEW (one Verification REPORTED) the cancel is rejected with
    ERR_INVALID_STATE.

    PRD §3.4: "A recruiter may cancel a `PENDING` order. The cancel call
    carries `expected_background_check_order_version`; on success the order
    transitions from `PENDING` to `CANCELLED`, and each child verification
    that was still `PENDING` transitions to `RESOLVED` with `result` left
    null, with every touched row's `version` incremented."

    Design: Corner/state_machines/order_cancel_from_in_review_invalid_state
    """
    from test_helpers.fixtures import report_verification
    (jur, applicant, app, consent, order,
     crim, mvr, edu) = order_with_three_pending_verifications(state_code="NM")
    # Drive order PENDING -> IN_REVIEW by reporting ONE verification.
    report_verification(crim["id"], "PASS", crim["version"])
    # Re-read order to get its current version.
    order_now = validate_success(api.get_order(order["id"],
                                                make_recruiter_headers("rec-001")), 200)
    assert order_now["status"] == "IN_REVIEW", \
        f"after one REPORT, order must be IN_REVIEW, got {order_now['status']!r}"
    resp = api.cancel_order(
        order["id"],
        {"expected_background_check_order_version": order_now["version"]},
        make_recruiter_headers("rec-001"),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
