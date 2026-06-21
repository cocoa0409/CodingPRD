"""Prescription authorization (BMI gate, issuance ordering, revoke lock),
duplicate-email uniqueness, and optimistic concurrency on the enrollment.

Queue A: boundary_precision_check (Rx BMI >= 30 boundary),
         priority_pair_validation_conflict (eligibility-approved before BMI gate).
Queue B: state_machines (revoke blocked while enrollment ACTIVE),
         validations (duplicate member email),
         cross_cutting (OCC correct-version succeeds / stale-version rejected).
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
COACH_FALLBACK = TEST_USERS["coach_headers"]


def test_rx_bmi_threshold_exactly_30_issues(api):
    """PRD §3.10: "the member's BMI must be at least 30.0, or at least 27.0
    provided the member's approved intake records a comorbidity count of at least
    1; failing both, the request is rejected with `ERR_BMI_BELOW_RX_THRESHOLD`."
    PRD §3.10: "A successful issuance snapshots the qualifying BMI into
    `qualifying_bmi`."

    Design: Difficulty/boundary_precision_check/rx_bmi_threshold_exactly_30_passes_29_8_fails
    """
    # 87kg / 170cm -> BMI 30.1 (>= 30.0) issues.
    ctx = fixtures.create_pending_enrollment(
        plan_overrides={"tier": "RX", "monthly_fee_cents": 9000},
        intake_weight_kg=87,
        comorbidity_count=0,
    )
    enr_id = ctx["enrollment"]["id"]
    det = fixtures.create_approved_eligibility(ctx["member"]["id"], enr_id)
    rx = fixtures.create_requested_rx(enr_id, det["id"])
    version = fixtures.get_enrollment_version(enr_id)
    issued = validate_success(api.issue_rx(rx["id"], f.issue_rx_payload(version), CLINICIAN), 200)
    assert issued["status"] == "ISSUED", f"Rx must be ISSUED at BMI 30.1, got {issued['status']}"
    assert issued["qualifying_bmi"] == 30.1, (
        f"qualifying_bmi must snapshot 30.1, got {issued['qualifying_bmi']}"
    )


def test_rx_bmi_below_threshold_rejected(api):
    """PRD §3.10: "the member's BMI must be at least 30.0, or at least 27.0 provided
    the member's approved intake records a comorbidity count of at least 1; failing
    both, the request is rejected with `ERR_BMI_BELOW_RX_THRESHOLD`."

    Design: Difficulty/boundary_precision_check/rx_bmi_threshold_exactly_30_passes_29_8_fails
    """
    # 86kg / 170cm -> BMI 29.8 (< 30.0, no comorbidity) is rejected.
    ctx = fixtures.create_pending_enrollment(
        plan_overrides={"tier": "RX", "monthly_fee_cents": 9000},
        intake_weight_kg=86,
        comorbidity_count=0,
    )
    enr_id = ctx["enrollment"]["id"]
    det = fixtures.create_approved_eligibility(ctx["member"]["id"], enr_id)
    rx = fixtures.create_requested_rx(enr_id, det["id"])
    version = fixtures.get_enrollment_version(enr_id)
    resp = api.issue_rx(rx["id"], f.issue_rx_payload(version), CLINICIAN)
    validate_error(resp, ApiErrorId.ERR_BMI_BELOW_RX_THRESHOLD.value, 409)
    after = validate_success(api.get_rx(rx["id"], CLINICIAN), 200)
    assert after["status"] == "REQUESTED", "rejected issue must leave Rx in REQUESTED"


def test_rx_issue_eligibility_check_precedes_bmi_gate(api):
    """PRD §3.10: "The referenced eligibility determination must be `APPROVED`
    (else `ERR_ELIGIBILITY_NOT_APPROVED`). And the member must clear the BMI gate:
    the member's BMI must be at least 30.0, or at least 27.0 provided the member's
    approved intake records a comorbidity count of at least 1; failing both, the
    request is rejected with `ERR_BMI_BELOW_RX_THRESHOLD`."

    Design: Difficulty/priority_pair_validation_conflict/safety_vs_referential_rx_issue_below_bmi_and_unapproved_eligibility
    """
    # BMI 27.0 (below 30, no comorbidity) AND eligibility still PENDING. PRD prose
    # checks eligibility-APPROVED before the BMI gate, so the referential error wins.
    ctx = fixtures.create_pending_enrollment(
        plan_overrides={"tier": "RX", "monthly_fee_cents": 9000},
        intake_weight_kg=78,
        comorbidity_count=0,
    )
    enr_id = ctx["enrollment"]["id"]
    det = fixtures.create_pending_eligibility(ctx["member"]["id"], enr_id)  # PENDING
    rx = fixtures.create_requested_rx(enr_id, det["id"])
    version = fixtures.get_enrollment_version(enr_id)
    resp = api.issue_rx(rx["id"], f.issue_rx_payload(version), CLINICIAN)
    validate_error(resp, ApiErrorId.ERR_ELIGIBILITY_NOT_APPROVED.value, 409)


def test_rx_issue_bmi_gate_fires_when_eligibility_approved(api):
    """PRD §3.10: "And the member must clear the BMI gate: the member's BMI must be
    at least 30.0, or at least 27.0 provided the member's approved intake records a
    comorbidity count of at least 1; failing both, the request is rejected with
    `ERR_BMI_BELOW_RX_THRESHOLD`."

    Design: Difficulty/priority_pair_validation_conflict/safety_vs_referential_rx_issue_below_bmi_and_unapproved_eligibility
    """
    # Eligibility APPROVED (referential gate passes) but BMI 29.8 with no
    # comorbidity -> the BMI safety gate is the one that fires. 86kg/170cm gives
    # BMI 29.8 (< 30.0, no comorbidity, so the RX gate fails) while its composite
    # score 39.20 clears the eligibility-approval threshold of 35, so the approved
    # determination precondition is reachable.
    ctx = fixtures.create_pending_enrollment(
        plan_overrides={"tier": "RX", "monthly_fee_cents": 9000},
        intake_weight_kg=86,
        comorbidity_count=0,
    )
    enr_id = ctx["enrollment"]["id"]
    det = fixtures.create_approved_eligibility(ctx["member"]["id"], enr_id)
    rx = fixtures.create_requested_rx(enr_id, det["id"])
    version = fixtures.get_enrollment_version(enr_id)
    resp = api.issue_rx(rx["id"], f.issue_rx_payload(version), CLINICIAN)
    validate_error(resp, ApiErrorId.ERR_BMI_BELOW_RX_THRESHOLD.value, 409)


def test_revoke_rx_while_enrollment_active_blocked(api):
    """PRD §3.10: "revocation additionally requires that the authorization's
    enrollment is not clinically `ACTIVE`, because an active RX enrollment relies
    on its issued authorization — attempting to revoke under an active enrollment
    is rejected with `ERR_ENROLLMENT_ACTIVE_RX_LOCKED`."

    Design: Corner/state_machines/revoke_rx_while_enrollment_active_blocked
    """
    ctx = fixtures.setup_rx_enrollment_active(intake_weight_kg=95)
    rx_id = ctx["rx"]["id"]
    resp = api.revoke_rx(rx_id, CLINICIAN)
    validate_error(resp, ApiErrorId.ERR_ENROLLMENT_ACTIVE_RX_LOCKED.value, 409)
    after = validate_success(api.get_rx(rx_id, CLINICIAN), 200)
    assert after["status"] == "ISSUED", "blocked revoke must leave Rx ISSUED"


def test_duplicate_member_email_within_program(api):
    """PRD §3.2: "The email must be unique within the program when compared
    case-insensitively; a collision against an existing member in the same program
    is rejected with `ERR_DUPLICATE_EMAIL`."

    Design: Corner/validations/duplicate_member_email_within_program
    """
    program = fixtures.create_program()
    validate_success(
        api.create_member(f.create_member_payload(program["id"], email="dup@x.com"), ADMIN), 201
    )
    resp = api.create_member(f.create_member_payload(program["id"], email="DUP@x.com"), ADMIN)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_EMAIL.value, 409)


def test_occ_correct_version_weighin_succeeds(api):
    """PRD §2.7: "If `expected_enrollment_version` does not equal the enrollment's
    current `version`, the operation is rejected with `ERR_STALE_ENROLLMENT_VERSION`
    at HTTP status 412, and no state change occurs."
    PRD §2.7: "Because a counted weigh-in recomputes the member's latest weight and
    progress metrics, recomputes goal progress, may auto-achieve milestones, and may
    recompute graduation eligibility — all of which advance the enrollment's
    `version`."

    Design: Corner/cross_cutting_complexity_layers/occ_correct_version_weighin_succeeds
    """
    ctx = fixtures.create_active_enrollment()
    enr_id = ctx["enrollment"]["id"]
    version = fixtures.get_enrollment_version(enr_id)
    payload = f.create_weighin_payload(enr_id, 93, version, counts=True)
    validate_success(api.create_weighin(payload, COACH_FALLBACK), 201)
    after = validate_success(api.get_enrollment(enr_id, ADMIN), 200)
    assert after["version"] == version + 1, (
        f"counted weigh-in must advance version by exactly 1, {version} -> {after['version']}"
    )


def test_occ_stale_version_weighin_rejected(api):
    """PRD §2.7: "If the enrollment's `version` has advanced since the client last
    read it, the create is rejected with `ERR_STALE_ENROLLMENT_VERSION` (HTTP 412),
    preventing the client from layering a weigh-in on top of an enrollment state it
    has not observed."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_version_weighin_rejected
    """
    ctx = fixtures.create_active_enrollment()
    enr_id = ctx["enrollment"]["id"]
    stale_version = fixtures.get_enrollment_version(enr_id)
    # First counted weigh-in advances the version.
    validate_success(
        api.create_weighin(f.create_weighin_payload(enr_id, 93, stale_version, counts=True), COACH_FALLBACK),
        201,
    )
    # Second weigh-in reuses the now-stale version.
    resp = api.create_weighin(f.create_weighin_payload(enr_id, 92, stale_version, counts=True), COACH_FALLBACK)
    validate_error(resp, ApiErrorId.ERR_STALE_ENROLLMENT_VERSION.value, 412)
