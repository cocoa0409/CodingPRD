"""Segregation of duties and task ownership on review-task signing.

Covers difficulty rule priority_pair_validation_conflict (sign segregation vs
not-task-owner). The PRD enforces the two separations "independently" without
committing to an ordering when both are violated, so the dual-violation test
accepts either error; the single-violation tests pin the unique outcome.
"""
from test_helpers import (
    api_client, validate_success, validate_error, validate_error_is_one_of,
    get_success_data, TEST_USERS, ApiErrorId,
    make_physician_headers,
    setup_in_review_task_with_logged_minutes,
)

PHYS = TEST_USERS["physician_headers"]


def test_sign_by_logger_who_is_not_owner_segregation_or_owner(api):
    """PRD §2.11: "First, the `Physician` who signs a provider review task must be the
    same physician who claimed it — signing a task one did not personally claim is
    refused with `ERR_NOT_TASK_OWNER`."
    PRD §2.11: "Second, and independently, the signing physician must not have personally
    logged any of the care minutes the task attests: the signer's `X-User-ID` must not
    equal the `clinician_user_id` of any care activity recorded for the same patient as
    the review task, and a violation is refused with `ERR_SEGREGATION_OF_DUTIES`."

    The task is owned by phys-A and the attested care minute was logged by phys-B;
    phys-B signing violates BOTH rules and either error is faithful to the PRD.

    Design: Difficulty/priority_pair_validation_conflict/sign_segregation_beats_not_task_owner
    """
    ctx = setup_in_review_task_with_logged_minutes(
        mrn="M-SG-1", serial_number="SN-SG-1",
        owner_user_id="phys-A", minute_logger_user_id="phys-B")
    resp = api.sign_review_task(ctx["task"]["id"], make_physician_headers("phys-B"))
    validate_error_is_one_of(
        resp, [ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, ApiErrorId.ERR_NOT_TASK_OWNER.value])


def test_owner_who_logged_minutes_blocked_by_segregation(api):
    """PRD §2.11: "the signing physician must not have personally logged any of the care
    minutes the task attests: the signer's `X-User-ID` must not equal the
    `clinician_user_id` of any care activity recorded for the same patient as the review
    task, and a violation is refused with `ERR_SEGREGATION_OF_DUTIES`."

    Here the signer IS the task owner (so ERR_NOT_TASK_OWNER cannot fire); only the
    segregation rule can fail, so the outcome is uniquely ERR_SEGREGATION_OF_DUTIES.

    Design: Difficulty/priority_pair_validation_conflict/sign_segregation_beats_not_task_owner
    """
    # Owner and minute-logger are the same physician -> owner check passes, segregation fails.
    ctx = setup_in_review_task_with_logged_minutes(
        mrn="M-SG-2", serial_number="SN-SG-2",
        owner_user_id="phys-C", minute_logger_user_id="phys-C")
    resp = api.sign_review_task(ctx["task"]["id"], make_physician_headers("phys-C"))
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)


def test_sign_by_non_owner_who_never_logged_is_not_task_owner(api):
    """PRD §2.11: "the `Physician` who signs a provider review task must be the same
    physician who claimed it — signing a task one did not personally claim is refused
    with `ERR_NOT_TASK_OWNER`."

    The signer (phys-D) neither owns the task (owned by phys-A) nor logged any minutes
    (logged by phys-B), so only the owner check can fail -> ERR_NOT_TASK_OWNER.

    Design: Difficulty/priority_pair_validation_conflict/sign_segregation_beats_not_task_owner
    """
    ctx = setup_in_review_task_with_logged_minutes(
        mrn="M-SG-3", serial_number="SN-SG-3",
        owner_user_id="phys-A", minute_logger_user_id="phys-B")
    resp = api.sign_review_task(ctx["task"]["id"], make_physician_headers("phys-D"))
    validate_error(resp, ApiErrorId.ERR_NOT_TASK_OWNER.value)
