"""Referral pipeline, consent lifecycle, and approval gates
(PRD §2.10, §3.2, §3.3)."""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated,
    assert_referral, assert_enrollment,
    TEST_USERS, make_clinic_staff_headers,
    create_clinic, create_patient, create_patient_with_consent,
    create_referral, start_review, approve_referral,
    setup_active_program, setup_enrollment, get_enrollment,
    grant_consent, revoke_consent,
)
from test_helpers import api_client

ADMIN = TEST_USERS["program_admin_headers"]


def _program_clinic_patient():
    """Active program + clinic + consenting patient (no referral yet)."""
    ctx = setup_active_program()
    clinic = create_clinic()
    patient = create_patient_with_consent(clinic["id"])
    ctx.update({"clinic": clinic, "patient": patient})
    return ctx


def test_referral_initial_state_submitted(api):
    """PRD §3.2: "A fresh referral lands in SUBMITTED with `appeal_count` at
    zero and `enrollment_id` empty."

    Design: Corner/state_machines/c_referral_initial_state_submitted
    """
    ctx = _program_clinic_patient()
    res = api.create_referral(
        {"clinic_id": ctx["clinic"]["id"], "patient_id": ctx["patient"]["id"],
         "program_id": ctx["program"]["id"], "diagnosis_code": "E11.9",
         "priority": "STANDARD"},
        make_clinic_staff_headers(ctx["clinic"]["id"]))
    referral = validate_success(res, 201)
    assert_referral(referral)
    assert referral["status"] == "SUBMITTED"
    assert referral["appeal_count"] == 0
    assert referral.get("enrollment_id") is None


def test_approve_from_submitted_rejected(api):
    """PRD §3.2: "Starting review moves SUBMITTED to UNDER_REVIEW. Approval —
    detailed in §3.3 — moves UNDER_REVIEW to APPROVED and creates the
    enrollment." and "Review actions attempted on a referral in the wrong state
    are rejected with `ERR_REFERRAL_NOT_REVIEWABLE`, and any transition
    attempted from a terminal state — APPROVED, WITHDRAWN, or EXPIRED — is
    `ERR_ALREADY_TERMINAL`."

    Design: Corner/state_machines/c_approve_from_submitted_rejected
    """
    ctx = _program_clinic_patient()
    referral = create_referral(ctx["clinic"]["id"], ctx["patient"]["id"],
                               ctx["program"]["id"])

    res = api.approve_referral(referral["id"], ADMIN)
    validate_error(res, "ERR_REFERRAL_NOT_REVIEWABLE")

    after = validate_success(api.get_referral(referral["id"], ADMIN), 200)
    assert after["status"] == "SUBMITTED"
    assert after.get("enrollment_id") is None


def test_referral_approve_creates_enrollment(api):
    """PRD §3.3: "When all three hold, the referral becomes APPROVED and an
    enrollment is created in one motion: its `program_id` and `patient_id` are
    copied from the referral, its `referral_id` points back to the originating
    referral, its `household_size` is a snapshot of the patient's household
    size at approval time, its `engagement_tier` starts at T1, its lifetime
    counters `lifetime_redeemed_cents` and `lifetime_match_cents` start at
    zero, and `lapsed_at` is empty."

    Design: Corner/state_machines/c_referral_approve_creates_enrollment
    """
    ctx = _program_clinic_patient()
    referral = create_referral(ctx["clinic"]["id"], ctx["patient"]["id"],
                               ctx["program"]["id"])
    approved = approve_referral(referral["id"])
    assert approved["status"] == "APPROVED"
    enrollment_id = approved["enrollment_id"]
    assert enrollment_id

    enrollment = get_enrollment(enrollment_id)
    assert_enrollment(enrollment)
    assert enrollment["status"] == "ACTIVE"
    assert enrollment["household_size"] == 2
    assert enrollment["engagement_tier"] == "T1"
    assert enrollment["referral_id"] == referral["id"]
    assert enrollment["lifetime_redeemed_cents"] == 0
    assert enrollment["lifetime_match_cents"] == 0
    assert enrollment.get("lapsed_at") is None


def test_duplicate_enrollment_rejected_on_second_approve(api):
    """PRD §3.3: "no enrollment may already exist for the same patient and
    program in ACTIVE, SUSPENDED, or LAPSED status (otherwise
    `ERR_DUPLICATE_ENROLLMENT`)."
    PRD §3.2: "Submission is gated, in the order given by §2.10: the acting
    clinic must own the referral's clinic; the clinic must be ACTIVE, else
    `ERR_CLINIC_SUSPENDED`; the patient's consent must be GRANTED, else
    `ERR_CONSENT_REVOKED`; the referral's clinic must be the same clinic that
    manages the patient — a `clinic_id` that differs from the patient's own
    `clinic_id` is `ERR_PATIENT_CLINIC_MISMATCH`; at most one non-terminal
    referral may exist for the same patient and program, else
    `ERR_DUPLICATE_REFERRAL`; and the clinic's count of referrals sitting in
    SUBMITTED or UNDER_REVIEW must be below its `max_active_referrals`, else
    `ERR_CLINIC_REFERRAL_CAP`."

    Design: Corner/errors/c_duplicate_enrollment_rejected
    """
    ctx = _program_clinic_patient()
    referral1 = create_referral(ctx["clinic"]["id"], ctx["patient"]["id"],
                                ctx["program"]["id"])
    approve_referral(referral1["id"])

    referral2 = create_referral(ctx["clinic"]["id"], ctx["patient"]["id"],
                                ctx["program"]["id"], priority="URGENT")
    start_review(referral2["id"])
    res = api.approve_referral(referral2["id"], ADMIN)
    validate_error(res, "ERR_DUPLICATE_ENROLLMENT")


def test_patient_clinic_mismatch_rejected(api):
    """PRD §3.2: "Submission is gated, in the order given by §2.10: the acting
    clinic must own the referral's clinic; the clinic must be ACTIVE, else
    `ERR_CLINIC_SUSPENDED`; the patient's consent must be GRANTED, else
    `ERR_CONSENT_REVOKED`; the referral's clinic must be the same clinic that
    manages the patient — a `clinic_id` that differs from the patient's own
    `clinic_id` is `ERR_PATIENT_CLINIC_MISMATCH`; at most one non-terminal
    referral may exist for the same patient and program, else
    `ERR_DUPLICATE_REFERRAL`; and the clinic's count of referrals sitting in
    SUBMITTED or UNDER_REVIEW must be below its `max_active_referrals`, else
    `ERR_CLINIC_REFERRAL_CAP`."

    Design: Corner/errors/c_patient_clinic_mismatch_rejected
    """
    ctx = setup_active_program()
    clinic_a = create_clinic(name="CA")
    clinic_b = create_clinic(name="CB")
    patient = create_patient_with_consent(clinic_a["id"])

    res = api.create_referral(
        {"clinic_id": clinic_b["id"], "patient_id": patient["id"],
         "program_id": ctx["program"]["id"], "diagnosis_code": "E11.9",
         "priority": "STANDARD"},
        make_clinic_staff_headers(clinic_b["id"]))
    validate_error(res, "ERR_PATIENT_CLINIC_MISMATCH")


def test_consent_revoke_regrant_cycle(api):
    """PRD §3.2: "The owning clinic may grant consent — moving PENDING, or a
    previously REVOKED consent, to GRANTED — and may revoke a GRANTED consent
    back to REVOKED; both acts are ownership-checked against the patient's
    clinic, and a revoked consent blocks new referrals and new biometric
    readings for that patient."

    Design: Corner/state_machines/c_consent_revoke_regrant_cycle
    """
    clinic = create_clinic()
    patient = create_patient(clinic["id"])
    assert patient["consent_status"] == "PENDING"

    granted = grant_consent(clinic["id"], patient["id"])
    assert granted["consent_status"] == "GRANTED"
    revoked = revoke_consent(clinic["id"], patient["id"])
    assert revoked["consent_status"] == "REVOKED"
    regranted = grant_consent(clinic["id"], patient["id"])
    assert regranted["consent_status"] == "GRANTED"


def test_referral_list_pagination_defaults(api):
    """PRD §2.3: "`limit` defaults to 10, with a minimum of 1 and a maximum of
    100; `offset` defaults to 0. Results are always sorted by `created_at`
    ascending. The `meta` block of a list response carries `limit`, `offset`,
    `total_count`, and `has_more`, so a client can page deterministically
    through any collection."

    Design: Corner/endpoints/c_list_pagination_defaults
    """
    ctx = _program_clinic_patient()
    patient_b = create_patient_with_consent(
        ctx["clinic"]["id"], full_name="Pat B", household_size=3)
    create_referral(ctx["clinic"]["id"], ctx["patient"]["id"],
                    ctx["program"]["id"])
    create_referral(ctx["clinic"]["id"], patient_b["id"],
                    ctx["program"]["id"], priority="URGENT")

    data, meta = validate_paginated(api.list_referrals(ADMIN))
    assert meta["limit"] == 10
    assert meta["total_count"] == 2
    assert meta["has_more"] is False
    assert len(data) == 2

    data, meta = validate_paginated(api.list_referrals(ADMIN, params={"limit": 1}))
    assert len(data) == 1
    assert meta["total_count"] == 2
    assert meta["has_more"] is True


# ---------------------------------------------------------------------------
# Depth instances: cyclic referral review and validation-priority pairs
# ---------------------------------------------------------------------------

def _under_review_referral():
    """Active program + clinic + consenting patient + referral UNDER_REVIEW."""
    ctx = _program_clinic_patient()
    referral = create_referral(ctx["clinic"]["id"], ctx["patient"]["id"],
                               ctx["program"]["id"])
    start_review(referral["id"])
    ctx["referral"] = referral
    return ctx


def test_referral_decline_appeal_then_approve_succeeds(api):
    """PRD §3.2: "the owning clinic may appeal with an `appeal_reason` (again
    required, else `ERR_VALIDATION`; a foreign clinic is `ERR_FORBIDDEN`),
    which moves DECLINED back to UNDER_REVIEW and increments `appeal_count` by
    one — the loop may repeat without limit."
    PRD §3.3: "When all three hold, the referral becomes APPROVED and an
    enrollment is created in one motion: its `program_id` and `patient_id` are
    copied from the referral, its `referral_id` points back to the originating
    referral, its `household_size` is a snapshot of the patient's household
    size at approval time, its `engagement_tier` starts at T1, its lifetime
    counters `lifetime_redeemed_cents` and `lifetime_match_cents` start at
    zero, and `lapsed_at` is empty."

    Design: Difficulty/non_linear_state_machine/referral_decline_appeal_approve_cycle
    """
    ctx = _under_review_referral()
    referral = ctx["referral"]

    declined = validate_success(api.decline_referral(
        referral["id"], {"decision_reason": "incomplete labs"}, ADMIN), 200)
    assert declined["status"] == "DECLINED"

    appealed = validate_success(api.appeal_referral(
        referral["id"], {"appeal_reason": "labs attached"},
        make_clinic_staff_headers(ctx["clinic"]["id"])), 200)
    assert appealed["status"] == "UNDER_REVIEW"

    approved = validate_success(api.approve_referral(referral["id"], ADMIN), 200)
    assert approved["status"] == "APPROVED"
    enrollment = get_enrollment(approved["enrollment_id"])
    assert enrollment["status"] == "ACTIVE"


def test_referral_appeal_increments_appeal_count(api):
    """PRD §3.2: "the owning clinic may appeal with an `appeal_reason` (again
    required, else `ERR_VALIDATION`; a foreign clinic is `ERR_FORBIDDEN`),
    which moves DECLINED back to UNDER_REVIEW and increments `appeal_count` by
    one — the loop may repeat without limit."

    Design: Difficulty/non_linear_state_machine/referral_decline_appeal_approve_cycle
    """
    ctx = _under_review_referral()
    referral = ctx["referral"]
    validate_success(api.decline_referral(
        referral["id"], {"decision_reason": "incomplete labs"}, ADMIN), 200)
    validate_success(api.appeal_referral(
        referral["id"], {"appeal_reason": "labs attached"},
        make_clinic_staff_headers(ctx["clinic"]["id"])), 200)
    validate_success(api.approve_referral(referral["id"], ADMIN), 200)

    final = validate_success(api.get_referral(referral["id"], ADMIN), 200)
    assert final["status"] == "APPROVED"
    assert final["appeal_count"] == 1


def _clinic_at_cap_with_revoked_consent_patient():
    """Clinic with max_active_referrals 1 already holding one SUBMITTED
    referral, plus a second patient whose consent was granted then revoked."""
    ctx = setup_active_program()
    clinic = create_clinic(max_active_referrals=1)
    patient1 = create_patient_with_consent(clinic["id"], full_name="Pat One")
    create_referral(clinic["id"], patient1["id"], ctx["program"]["id"])
    patient2 = create_patient(clinic["id"], full_name="Pat Two", household_size=3)
    grant_consent(clinic["id"], patient2["id"])
    revoke_consent(clinic["id"], patient2["id"])
    ctx.update({"clinic": clinic, "patient2": patient2})
    return ctx


def test_create_referral_consent_revoked_beats_clinic_cap(api):
    """PRD §2.10: "When several checks could reject the same request, the
    server applies them in a fixed priority order so the surfaced error is
    deterministic." and "Seventh, clinical safety: consent must be GRANTED for
    referral creation and approval and for biometric recording, and A1c values
    must be clinically plausible, otherwise `ERR_CONSENT_REVOKED` or
    `ERR_A1C_OUT_OF_RANGE`." and "Ninth, uniqueness and capacity: one
    non-terminal referral per patient and program, the clinic's active-referral
    cap, one enrollment per patient and program, one voucher per enrollment per
    cycle, session capacity, one completion per enrollment and session —
    otherwise `ERR_DUPLICATE_REFERRAL`, `ERR_CLINIC_REFERRAL_CAP`,
    `ERR_DUPLICATE_ENROLLMENT`, `ERR_SESSION_FULL`, `ERR_DUPLICATE_COMPLETION`,
    or `ERR_VALIDATION`."

    Design: Difficulty/priority_pair_validation_conflict/create_referral_consent_revoked_beats_clinic_cap
    """
    ctx = _clinic_at_cap_with_revoked_consent_patient()
    res = api.create_referral(
        {"clinic_id": ctx["clinic"]["id"], "patient_id": ctx["patient2"]["id"],
         "program_id": ctx["program"]["id"], "diagnosis_code": "E11.9",
         "priority": "STANDARD"},
        make_clinic_staff_headers(ctx["clinic"]["id"]))
    validate_error(res, "ERR_CONSENT_REVOKED")
    assert res.json()["data"]["error_id"] != "ERR_CLINIC_REFERRAL_CAP"


def test_create_referral_priority_rejection_creates_no_referral(api):
    """PRD §2.10: "Seventh, clinical safety: consent must be GRANTED for
    referral creation and approval and for biometric recording, and A1c values
    must be clinically plausible, otherwise `ERR_CONSENT_REVOKED` or
    `ERR_A1C_OUT_OF_RANGE`."
    PRD §3.2: "Submission is gated, in the order given by §2.10: the acting
    clinic must own the referral's clinic; the clinic must be ACTIVE, else
    `ERR_CLINIC_SUSPENDED`; the patient's consent must be GRANTED, else
    `ERR_CONSENT_REVOKED`; the referral's clinic must be the same clinic that
    manages the patient — a `clinic_id` that differs from the patient's own
    `clinic_id` is `ERR_PATIENT_CLINIC_MISMATCH`; at most one non-terminal
    referral may exist for the same patient and program, else
    `ERR_DUPLICATE_REFERRAL`; and the clinic's count of referrals sitting in
    SUBMITTED or UNDER_REVIEW must be below its `max_active_referrals`, else
    `ERR_CLINIC_REFERRAL_CAP`."

    Design: Difficulty/priority_pair_validation_conflict/create_referral_consent_revoked_beats_clinic_cap
    """
    ctx = _clinic_at_cap_with_revoked_consent_patient()
    res = api.create_referral(
        {"clinic_id": ctx["clinic"]["id"], "patient_id": ctx["patient2"]["id"],
         "program_id": ctx["program"]["id"], "diagnosis_code": "E11.9",
         "priority": "STANDARD"},
        make_clinic_staff_headers(ctx["clinic"]["id"]))
    validate_error(res, "ERR_CONSENT_REVOKED")

    data, meta = validate_paginated(api.list_referrals(
        ADMIN, params={"clinic_id": ctx["clinic"]["id"]}))
    assert meta["total_count"] == 1, "rejected create must not add a referral"


def _frozen_program_with_revoked_consent():
    """Referral UNDER_REVIEW, then consent revoked, then funder suspended so
    the program is FROZEN (PRD §2.9 cascade)."""
    ctx = _under_review_referral()
    revoke_consent(ctx["clinic"]["id"], ctx["patient"]["id"])
    validate_success(api_client.suspend_funder(ctx["funder"]["id"], ADMIN), 200)
    return ctx


def test_approve_frozen_program_and_revoked_consent_returns_program_not_active(api):
    """PRD §3.3: "Approval is the hinge of the whole pipeline, and it is
    heavily gated: the target program must be ACTIVE (otherwise
    `ERR_PROGRAM_NOT_ACTIVE`), the patient's consent must still be GRANTED
    (otherwise `ERR_CONSENT_REVOKED`), and no enrollment may already exist for
    the same patient and program in ACTIVE, SUSPENDED, or LAPSED status
    (otherwise `ERR_DUPLICATE_ENROLLMENT`)."
    PRD §2.10: "When several checks could reject the same request, the server
    applies them in a fixed priority order so the surfaced error is
    deterministic." and "Sixth, state preconditions: the target and parent
    entities must be in states that permit the transition — from-state
    membership, terminal lockdown, and the program, enrollment, referral,
    voucher, cycle, report, renewal, and session status gates — otherwise the
    appropriate state error among `ERR_INVALID_STATE`, `ERR_ALREADY_TERMINAL`,
    `ERR_PROGRAM_NOT_ACTIVE`, `ERR_PROGRAM_FROZEN`, `ERR_ENROLLMENT_NOT_ACTIVE`,
    `ERR_REFERRAL_NOT_REVIEWABLE`, `ERR_VOUCHER_NOT_REDEEMABLE`,
    `ERR_CYCLE_NOT_OPEN`, `ERR_CYCLE_ALREADY_OPEN`, `ERR_PRIOR_CYCLE_UNCLOSED`,
    `ERR_REPORT_NOT_EDITABLE`, `ERR_RENEWAL_NOT_ACTIONABLE`, or
    `ERR_SESSION_NOT_SCHEDULED`." and "Seventh, clinical safety: consent must
    be GRANTED for referral creation and approval and for biometric recording,
    and A1c values must be clinically plausible, otherwise
    `ERR_CONSENT_REVOKED` or `ERR_A1C_OUT_OF_RANGE`."

    Design: Difficulty/priority_pair_validation_conflict/approve_referral_program_frozen_beats_consent_revoked
    """
    ctx = _frozen_program_with_revoked_consent()
    program = validate_success(api.get_program(ctx["program"]["id"], ADMIN), 200)
    assert program["status"] == "FROZEN"

    res = api.approve_referral(ctx["referral"]["id"], ADMIN)
    validate_error(res, "ERR_PROGRAM_NOT_ACTIVE")
    assert res.json()["data"]["error_id"] != "ERR_CONSENT_REVOKED"


def test_approve_rejected_by_priority_leaves_referral_under_review(api):
    """PRD §3.3: "Approval is the hinge of the whole pipeline, and it is
    heavily gated: the target program must be ACTIVE (otherwise
    `ERR_PROGRAM_NOT_ACTIVE`), the patient's consent must still be GRANTED
    (otherwise `ERR_CONSENT_REVOKED`), and no enrollment may already exist for
    the same patient and program in ACTIVE, SUSPENDED, or LAPSED status
    (otherwise `ERR_DUPLICATE_ENROLLMENT`)."
    PRD §2.10: "Sixth, state preconditions: the target and parent entities must
    be in states that permit the transition — from-state membership, terminal
    lockdown, and the program, enrollment, referral, voucher, cycle, report,
    renewal, and session status gates — otherwise the appropriate state error
    among `ERR_INVALID_STATE`, `ERR_ALREADY_TERMINAL`, `ERR_PROGRAM_NOT_ACTIVE`,
    `ERR_PROGRAM_FROZEN`, `ERR_ENROLLMENT_NOT_ACTIVE`,
    `ERR_REFERRAL_NOT_REVIEWABLE`, `ERR_VOUCHER_NOT_REDEEMABLE`,
    `ERR_CYCLE_NOT_OPEN`, `ERR_CYCLE_ALREADY_OPEN`, `ERR_PRIOR_CYCLE_UNCLOSED`,
    `ERR_REPORT_NOT_EDITABLE`, `ERR_RENEWAL_NOT_ACTIONABLE`, or
    `ERR_SESSION_NOT_SCHEDULED`."

    Design: Difficulty/priority_pair_validation_conflict/approve_referral_program_frozen_beats_consent_revoked
    """
    ctx = _frozen_program_with_revoked_consent()
    res = api.approve_referral(ctx["referral"]["id"], ADMIN)
    validate_error(res, "ERR_PROGRAM_NOT_ACTIVE")

    after = validate_success(api.get_referral(ctx["referral"]["id"], ADMIN), 200)
    assert after["status"] == "UNDER_REVIEW"
    assert after.get("enrollment_id") is None
