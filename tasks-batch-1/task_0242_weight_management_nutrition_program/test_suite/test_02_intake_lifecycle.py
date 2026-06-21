"""Intake assessment lifecycle: the cyclic revision loop, computed BMI/risk_band,
invalid transitions, terminal-state lockdown, and precondition enforcement.

Queue A: non_linear_state_machine (revision cycle).
Queue B: entities (computed bmi), state_machines (intake invalid/terminal/precondition).
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    factories as f,
    fixtures,
)
from test_helpers import TEST_USERS

ADMIN = TEST_USERS["program_admin_headers"]
CLINICIAN = TEST_USERS["clinician_headers"]


def test_intake_revision_cycle_increments_round(api):
    """PRD §3.3: "Resubmission requires the current state to be `NEEDS_REVISION`
    (else `ERR_INVALID_STATE`) and weight strictly greater than zero (else
    `ERR_INVALID_REQUEST`). On each resubmission the `revision_round` counter
    increases by one, and the `bmi` and `risk_band` are recomputed from the
    possibly updated inputs."

    Design: Difficulty/non_linear_state_machine/intake_assessment_revision_cycle_increments_round
    """
    program = fixtures.create_program()
    member = fixtures.create_member(program["id"])
    member_headers = fixtures.make_member_headers(member["id"])
    intake = validate_success(
        api.create_intake(f.create_intake_payload(member["id"], weight_kg=95), member_headers), 201
    )
    iid = intake["id"]
    validate_success(api.submit_intake(iid, {}, member_headers), 200)
    validate_success(api.start_review_intake(iid, CLINICIAN), 200)
    validate_success(
        api.request_revision_intake(iid, {"review_notes": "please re-weigh"}, CLINICIAN), 200
    )
    # One full loop back to SUBMITTED.
    resubmitted = validate_success(api.submit_intake(iid, {"weight_kg": 94}, member_headers), 200)
    assert resubmitted["status"] == "SUBMITTED", f"expected SUBMITTED, got {resubmitted['status']}"
    assert resubmitted["revision_round"] == 1, (
        f"revision_round must be 1 after one full cycle, got {resubmitted['revision_round']}"
    )


def test_intake_revision_round_zero_on_first_submission(api):
    """PRD §3.3: "The assessment also carries `review_notes`, a `revision_round`
    counter that starts at zero, a computed `bmi`, and a computed `risk_band`."

    Design: Difficulty/non_linear_state_machine/intake_assessment_revision_cycle_increments_round
    """
    program = fixtures.create_program()
    member = fixtures.create_member(program["id"])
    member_headers = fixtures.make_member_headers(member["id"])
    intake = validate_success(
        api.create_intake(f.create_intake_payload(member["id"], weight_kg=95), member_headers), 201
    )
    submitted = validate_success(api.submit_intake(intake["id"], {}, member_headers), 200)
    assert submitted["status"] == "SUBMITTED"
    assert submitted["revision_round"] == 0, (
        f"first submission must keep revision_round at 0, got {submitted['revision_round']}"
    )


def test_intake_bmi_and_risk_band_computed_on_submit(api):
    """PRD §3.3: "divide the weight in kilograms by the square of the member's
    height expressed in metres (the height in centimetres divided by 100), and
    round the result to one decimal place using round-half-up."
    PRD §3.3: "it is `MODERATE` when the BMI is at least 30.0 or the comorbidity
    count is exactly 1."

    Design: Corner/entities/intake_bmi_computed_input_ignored
    """
    program = fixtures.create_program()
    member = fixtures.create_member(program["id"], height_cm=170)
    member_headers = fixtures.make_member_headers(member["id"])
    intake = validate_success(
        api.create_intake(f.create_intake_payload(member["id"], weight_kg=95), member_headers), 201
    )
    submitted = validate_success(api.submit_intake(intake["id"], {}, member_headers), 200)
    assert submitted["bmi"] == 32.9, f"BMI(95kg,170cm) must be 32.9, got {submitted['bmi']}"
    assert submitted["risk_band"] == "MODERATE", (
        f"risk_band must be MODERATE for BMI 32.9, got {submitted['risk_band']}"
    )


def test_approve_intake_from_draft_returns_invalid_state(api):
    """PRD §3.3: "The clinician may approve the assessment, moving it from
    `UNDER_REVIEW` to the terminal `APPROVED` state."
    PRD §3.3: "Each of `start-review`, `request-revision`, `approve`, and `reject`
    is valid only from `UNDER_REVIEW` except start-review, which is valid only from
    `SUBMITTED`; any attempt from another state is `ERR_INVALID_STATE`."

    Design: Corner/state_machines/approve_intake_from_draft_returns_invalid_state
    """
    program = fixtures.create_program()
    member = fixtures.create_member(program["id"])
    member_headers = fixtures.make_member_headers(member["id"])
    intake = validate_success(
        api.create_intake(f.create_intake_payload(member["id"], weight_kg=95), member_headers), 201
    )
    resp = api.approve_intake(intake["id"], CLINICIAN)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)
    after = validate_success(api.get_intake(intake["id"], CLINICIAN), 200)
    assert after["status"] == "DRAFT", "rejected approve must not advance a DRAFT intake"


def test_terminal_rejected_intake_rejects_start_review(api):
    """PRD §3.3: "Or the clinician may reject the assessment, moving it from
    `UNDER_REVIEW` to the terminal `REJECTED` state."
    PRD §3.3: "Each of `start-review`, `request-revision`, `approve`, and `reject`
    is valid only from `UNDER_REVIEW` except start-review, which is valid only from
    `SUBMITTED`; any attempt from another state is `ERR_INVALID_STATE`."

    Design: Corner/state_machines/terminal_rejected_intake_rejects_start_review
    """
    program = fixtures.create_program()
    member = fixtures.create_member(program["id"])
    intake = fixtures.create_intake_under_review(member["id"])
    validate_success(api.reject_intake(intake["id"], {"review_notes": "ineligible"}, CLINICIAN), 200)
    resp = api.start_review_intake(intake["id"], CLINICIAN)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)
    after = validate_success(api.get_intake(intake["id"], CLINICIAN), 200)
    assert after["status"] == "REJECTED", "terminal REJECTED must remain REJECTED"


def test_request_revision_without_notes_returns_invalid_request(api):
    """PRD §3.3: "The clinician may request a revision, moving the assessment to
    `NEEDS_REVISION`; this requires non-empty `review_notes` (else
    `ERR_INVALID_REQUEST`), which are stored on the assessment."

    Design: Corner/state_machines/request_revision_without_notes_returns_invalid_request
    """
    program = fixtures.create_program()
    member = fixtures.create_member(program["id"])
    intake = fixtures.create_intake_under_review(member["id"])
    resp = api.request_revision_intake(intake["id"], {"review_notes": ""}, CLINICIAN)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value, 400)
