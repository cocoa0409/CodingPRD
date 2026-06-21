"""Dependent-enrollment workflow (SEP/slot precedence, OCC on the policy, slot
conservation on terminate), pre-registration lifecycle and admit window, birth
recording rules, RBAC, and authentication.

Difficulty queue: priority_pair_validation_conflict (SEP beats slots),
compensating_invariant (terminate conserves slots).
Corner queue: enrollment transitions, slots exhausted, SEP closed, registration
transitions/defaults/computed fields, admit window, RBAC, auth, not-found, invalid
request, system fields, pagination.
"""
import pytest
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data, ApiErrorId,
    assert_dependent_slots_invariant,
)
import test_helpers.fixtures as fx
import test_helpers.factories as f


# =========================================================================
# Difficulty/priority_pair_validation_conflict/approve_sep_window_beats_slots_exhausted
# =========================================================================
def test_approve_sep_window_beats_slots_exhausted(api):
    """PRD §3.10: "If the enrollment's requested_at is strictly after its sep_deadline,
    the window has closed and the approval is rejected with ERR_SEP_WINDOW_CLOSED"
    PRD §3.11: "When several checks could fire on a single request, they are evaluated
    in a fixed precedence so that the most fundamental failure surfaces first."

    Design: Difficulty/priority_pair_validation_conflict/approve_sep_window_beats_slots_exhausted
    """
    fx.set_clock("2026-03-06T12:00:00Z")
    policy = fx.create_policy(plan_type="MARKETPLACE", dependent_slots_max=1, carrier_name="MktCo")
    reg, _ = fx.create_admitted_registration(policy_id=policy["id"], due_date="2026-03-12")
    nb_a = fx.record_birth(reg["id"], birth_datetime="2026-03-05T10:00:00Z", birth_sequence=1)
    nb_b = fx.record_birth(reg["id"], birth_datetime="2026-03-05T10:00:00Z", birth_sequence=2,
                           weight_grams=3100)
    # Exhaust the single slot with A (within SEP).
    enr_a = fx.create_enrollment(nb_a["id"], policy["id"], "2026-03-06T12:00:00Z")
    fx.approve_enrollment(enr_a["id"], policy["id"])
    # B requested past the MARKETPLACE deadline (2026-04-04T10:00:00Z).
    enr_b = fx.create_enrollment(nb_b["id"], policy["id"], "2026-04-30T12:00:00Z")
    pol_v = fx.get_policy_version(policy["id"])
    fx.set_clock("2026-05-01T12:00:00Z")

    # B violates both the SEP window and slot exhaustion; SEP (the earlier-listed rule) wins.
    resp = api.approve_enrollment(enr_b["id"], f.approve_enrollment_payload(pol_v), fx.BENEFITS)
    validate_error(resp, ApiErrorId.ERR_SEP_WINDOW_CLOSED.value)


def test_approve_within_sep_but_slots_exhausted_is_slots_error(api):
    """PRD §3.10: "If the governing policy's count of ENROLLED dependents already
    equals its dependent_slots_max, the approval is rejected with
    ERR_DEPENDENT_SLOTS_EXHAUSTED."

    Design: Difficulty/priority_pair_validation_conflict/approve_sep_window_beats_slots_exhausted
    """
    fx.set_clock("2026-03-06T12:00:00Z")
    policy = fx.create_policy(plan_type="MARKETPLACE", dependent_slots_max=1, carrier_name="MktCo")
    reg, _ = fx.create_admitted_registration(policy_id=policy["id"], due_date="2026-03-12")
    nb_a = fx.record_birth(reg["id"], birth_datetime="2026-03-05T10:00:00Z", birth_sequence=1)
    nb_b = fx.record_birth(reg["id"], birth_datetime="2026-03-05T10:00:00Z", birth_sequence=2,
                           weight_grams=3100)
    enr_a = fx.create_enrollment(nb_a["id"], policy["id"], "2026-03-06T12:00:00Z")
    fx.approve_enrollment(enr_a["id"], policy["id"])
    # B is within SEP (only the slot rule can fire), so the error is slots-exhausted.
    enr_b = fx.create_enrollment(nb_b["id"], policy["id"], "2026-03-06T12:30:00Z")
    pol_v = fx.get_policy_version(policy["id"])

    resp = api.approve_enrollment(enr_b["id"], f.approve_enrollment_payload(pol_v), fx.BENEFITS)
    validate_error(resp, ApiErrorId.ERR_DEPENDENT_SLOTS_EXHAUSTED.value)


# =========================================================================
# Difficulty/compensating_invariant/terminate_enrollment_conserves_policy_dependent_slots
# =========================================================================
class TestTerminateConservesSlots:
    def test_enroll_then_terminate_returns_count_to_zero(self, api):
        """PRD §3.10: "An ENROLLED enrollment may be terminated as compensation for an
        erroneous enrollment, moving it from ENROLLED to TERMINATED; termination
        recomputes the policy's dependents_added_count (releasing the slot back to the
        policy) and increments the version."

        Design: Difficulty/compensating_invariant/terminate_enrollment_conserves_policy_dependent_slots
        """
        fx.set_clock("2026-03-06T12:00:00Z")
        policy = fx.create_policy(plan_type="MARKETPLACE", dependent_slots_max=2, carrier_name="MktCo")
        reg, _ = fx.create_admitted_registration(policy_id=policy["id"], due_date="2026-03-12")
        newborn = fx.record_birth(reg["id"], birth_datetime="2026-03-05T10:00:00Z")
        enr = fx.create_enrollment(newborn["id"], policy["id"], "2026-03-06T12:00:00Z")
        fx.approve_enrollment(enr["id"], policy["id"])
        after_enroll = validate_success(api.get_insurance_policy(policy["id"], fx.BENEFITS))
        assert_dependent_slots_invariant(after_enroll, 1)

        term = validate_success(api.terminate_enrollment(enr["id"], fx.BENEFITS))
        assert term["status"] == "TERMINATED"
        after_terminate = validate_success(api.get_insurance_policy(policy["id"], fx.BENEFITS))
        assert_dependent_slots_invariant(after_terminate, 0)

    def test_count_is_one_immediately_after_approve(self, api):
        """PRD §3.10: "A successful approval sets retroactive_effective_date to the
        calendar date of the infant's birth_datetime (coverage always backdates to the
        birth date when enrolled within the window), recomputes the policy's
        dependents_added_count, journals a DEPENDENT_ENROLLED audit event, and
        increments the policy's version."

        Design: Difficulty/compensating_invariant/terminate_enrollment_conserves_policy_dependent_slots
        """
        fx.set_clock("2026-03-06T12:00:00Z")
        policy = fx.create_policy(plan_type="MARKETPLACE", dependent_slots_max=2, carrier_name="MktCo")
        reg, _ = fx.create_admitted_registration(policy_id=policy["id"], due_date="2026-03-12")
        newborn = fx.record_birth(reg["id"], birth_datetime="2026-03-05T10:00:00Z")
        enr = fx.create_enrollment(newborn["id"], policy["id"], "2026-03-06T12:00:00Z")
        fx.approve_enrollment(enr["id"], policy["id"])

        after_enroll = validate_success(api.get_insurance_policy(policy["id"], fx.BENEFITS))
        assert after_enroll["dependents_added_count"] == 1, (
            f"dependents_added_count should be 1 after one approve, "
            f"got {after_enroll['dependents_added_count']}")


# =========================================================================
# Corner/state_machines/dependent_enrollment_expire_to_sep_expired
# =========================================================================
def test_expire_pending_enrollment_past_deadline(api):
    """PRD §3.10: "A PENDING enrollment whose window has already passed may be
    explicitly expired by the coordinator, moving it from PENDING to SEP_EXPIRED; this
    transition is the deliberate close of a lapsed request, requires that the
    requested_at be strictly after the sep_deadline"

    Design: Corner/state_machines/dependent_enrollment_expire_to_sep_expired
    """
    fx.set_clock("2026-04-11T12:00:00Z")
    policy = fx.create_policy(plan_type="MARKETPLACE", dependent_slots_max=3, carrier_name="MktCo")
    reg, _ = fx.create_admitted_registration(policy_id=policy["id"], due_date="2026-03-12")
    newborn = fx.record_birth(reg["id"], birth_datetime="2026-03-05T10:00:00Z")
    # requested_at 2026-04-10 is past the MARKETPLACE deadline 2026-04-04T10:00:00Z.
    enr = fx.create_enrollment(newborn["id"], policy["id"], "2026-04-10T10:00:00Z")

    data = validate_success(api.expire_enrollment(enr["id"], fx.BENEFITS))
    assert data["status"] == "SEP_EXPIRED", (
        f"explicit expire of a lapsed PENDING enrollment should be SEP_EXPIRED, "
        f"got {data['status']}")


# =========================================================================
# Corner/state_machines/dependent_enrollment_deny_to_denied
# =========================================================================
def test_deny_pending_enrollment(api):
    """PRD §3.10: "A PENDING enrollment may instead be denied, moving it from PENDING
    to DENIED and incrementing the version."

    Design: Corner/state_machines/dependent_enrollment_deny_to_denied
    """
    fx.set_clock("2026-03-06T12:00:00Z")
    policy = fx.create_policy(plan_type="MARKETPLACE", dependent_slots_max=3, carrier_name="MktCo")
    reg, _ = fx.create_admitted_registration(policy_id=policy["id"], due_date="2026-03-12")
    newborn = fx.record_birth(reg["id"], birth_datetime="2026-03-05T10:00:00Z")
    enr = fx.create_enrollment(newborn["id"], policy["id"], "2026-03-06T12:00:00Z")

    data = validate_success(api.deny_enrollment(enr["id"], fx.BENEFITS))
    assert data["status"] == "DENIED", (
        f"deny of a PENDING enrollment should be DENIED, got {data['status']}")


# =========================================================================
# Corner/errors/error_dependent_slots_exhausted_triggerable
# =========================================================================
def test_dependent_slots_exhausted_on_second_approve(api):
    """PRD §3.10: "If the governing policy's count of ENROLLED dependents already
    equals its dependent_slots_max, the approval is rejected with
    ERR_DEPENDENT_SLOTS_EXHAUSTED."

    Design: Corner/errors/error_dependent_slots_exhausted_triggerable
    """
    fx.set_clock("2026-03-06T12:00:00Z")
    policy = fx.create_policy(plan_type="MARKETPLACE", dependent_slots_max=1, carrier_name="MktCo")
    reg, _ = fx.create_admitted_registration(policy_id=policy["id"], due_date="2026-03-12")
    nb_a = fx.record_birth(reg["id"], birth_datetime="2026-03-05T10:00:00Z", birth_sequence=1)
    nb_b = fx.record_birth(reg["id"], birth_datetime="2026-03-05T10:05:00Z", birth_sequence=2,
                           weight_grams=3100)
    enr_a = fx.create_enrollment(nb_a["id"], policy["id"], "2026-03-06T12:00:00Z")
    fx.approve_enrollment(enr_a["id"], policy["id"])
    enr_b = fx.create_enrollment(nb_b["id"], policy["id"], "2026-03-06T12:30:00Z")
    pol_v = fx.get_policy_version(policy["id"])

    resp = api.approve_enrollment(enr_b["id"], f.approve_enrollment_payload(pol_v), fx.BENEFITS)
    validate_error(resp, ApiErrorId.ERR_DEPENDENT_SLOTS_EXHAUSTED.value)


# =========================================================================
# Corner/errors/approve_past_deadline_rejected_sep_window_closed
# =========================================================================
def test_approve_past_deadline_sep_window_closed(api):
    """PRD §3.10: "If the enrollment's requested_at is strictly after its sep_deadline,
    the window has closed and the approval is rejected with ERR_SEP_WINDOW_CLOSED —
    note that approving past the deadline does not silently expire the row; it is
    rejected and the enrollment stays PENDING."

    Design: Corner/errors/approve_past_deadline_rejected_sep_window_closed
    """
    fx.set_clock("2026-04-06T12:00:00Z")
    policy = fx.create_policy(plan_type="MARKETPLACE", dependent_slots_max=3, carrier_name="MktCo")
    reg, _ = fx.create_admitted_registration(policy_id=policy["id"], due_date="2026-03-12")
    newborn = fx.record_birth(reg["id"], birth_datetime="2026-03-05T10:00:00Z")
    # requested_at 2026-04-05 is one day past the deadline 2026-04-04T10:00:00Z; slot is free.
    enr = fx.create_enrollment(newborn["id"], policy["id"], "2026-04-05T10:00:00Z")
    pol_v = fx.get_policy_version(policy["id"])

    resp = api.approve_enrollment(enr["id"], f.approve_enrollment_payload(pol_v), fx.BENEFITS)
    validate_error(resp, ApiErrorId.ERR_SEP_WINDOW_CLOSED.value)


# =========================================================================
# Corner/cross_cutting_complexity_layers/occ_dependent_approve_stale_policy_version_rejected
# =========================================================================
def test_approve_stale_policy_version_rejected(api):
    """PRD §2.7: "If that value does not match the policy's current version — because
    another writer has already enrolled a dependent under the same policy, consuming a
    finite slot and bumping the policy version — the approval is rejected with
    ERR_STALE_VERSION at HTTP 412."

    Design: Corner/cross_cutting_complexity_layers/occ_dependent_approve_stale_policy_version_rejected
    """
    fx.set_clock("2026-03-06T12:00:00Z")
    policy = fx.create_policy(plan_type="MARKETPLACE", dependent_slots_max=3, carrier_name="MktCo")
    reg, _ = fx.create_admitted_registration(policy_id=policy["id"], due_date="2026-03-12")
    nb_a = fx.record_birth(reg["id"], birth_datetime="2026-03-05T10:00:00Z", birth_sequence=1)
    nb_b = fx.record_birth(reg["id"], birth_datetime="2026-03-05T10:05:00Z", birth_sequence=2,
                           weight_grams=3100)
    enr_a = fx.create_enrollment(nb_a["id"], policy["id"], "2026-03-06T12:00:00Z")
    enr_b = fx.create_enrollment(nb_b["id"], policy["id"], "2026-03-06T12:00:00Z")
    stale_v = fx.get_policy_version(policy["id"])
    # Approve A with the captured version -> bumps the policy version.
    fx.approve_enrollment(enr_a["id"], policy["id"], expected_version=stale_v)

    # Approve B with the now-stale version.
    resp = api.approve_enrollment(enr_b["id"], f.approve_enrollment_payload(stale_v), fx.BENEFITS)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)


# =========================================================================
# Corner/entities/create_insurance_policy_returns_201_with_all_fields
# =========================================================================
def test_create_insurance_policy_returns_201_with_system_fields(api):
    """PRD §3.10: "The policy tracks dependents_added_count, the number of its
    enrollments currently in ENROLLED, recomputed as enrollments come and go."
    PRD §2.4: "The version field is an integer that begins at its initial value"

    Design: Corner/entities/create_insurance_policy_returns_201_with_all_fields
    """
    fx.set_clock("2026-03-05T12:00:00Z")
    data = validate_success(api.create_insurance_policy(
        f.create_insurance_policy_payload(plan_type="MARKETPLACE", dependent_slots_max=2,
                                          carrier_name="MktCo"),
        fx.BENEFITS), expected_status=201)
    assert data["version"] == 1, f"new policy version should be 1, got {data['version']}"
    assert data["dependents_added_count"] == 0, (
        f"new policy dependents_added_count should be 0, got {data['dependents_added_count']}")
    assert data["plan_type"] == "MARKETPLACE"


# =========================================================================
# Corner/entities/get_newborn_not_found_returns_404
# =========================================================================
def test_get_newborn_not_found_returns_404(api):
    """PRD §2.6: "the first identifier that does not resolve to an existing resource
    produces ERR_NOT_FOUND before any deeper lookup is attempted."

    Design: Corner/entities/get_newborn_not_found_returns_404
    """
    fx.set_clock("2026-03-05T12:00:00Z")
    resp = api.get_newborn("00000000-0000-4000-8000-000000000000", fx.NURSE)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


# =========================================================================
# Corner/entities/create_registration_missing_required_field_returns_invalid_request
# =========================================================================
def test_create_registration_missing_due_date_invalid_request(api):
    """PRD §3.1: "Submission requires that all of the required intake fields —
    mother_full_name, mother_dob, due_date, payer_policy_id, and
    planned_delivery_facility — are present"
    PRD §3.11: "the request body is validated for well-formedness, required fields, and
    correct types and enum values, with violations yielding ERR_INVALID_REQUEST."

    Design: Corner/entities/create_registration_missing_required_field_returns_invalid_request
    """
    fx.set_clock("2026-03-05T12:00:00Z")
    policy = fx.create_policy()
    payload = f.create_registration_payload(policy["id"])
    del payload["due_date"]

    resp = api.create_registration(payload, fx.CLERK)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


# =========================================================================
# Corner/entities/create_registration_default_birth_plan_flags_applied
# =========================================================================
def test_create_registration_defaults(api):
    """PRD §3.1: "The clerk may also include birth_plan_flags, a map of birth-plan
    preferences such as a breastfeeding-intent flag or a cord-blood-banking flag; when
    omitted it defaults to an empty map."
    PRD §3.1: "A fresh pre-registration is created with its status field at DRAFT, its
    admitted_at is null, and its newborn_count — the number of newborn rows recorded
    against it, regardless of their clinical state — begins at zero."

    Design: Corner/entities/create_registration_default_birth_plan_flags_applied
    """
    fx.set_clock("2026-03-05T12:00:00Z")
    policy = fx.create_policy()
    data = validate_success(api.create_registration(
        f.create_registration_payload(policy["id"]), fx.CLERK), expected_status=201)
    assert data["status"] == "DRAFT", f"new registration status should be DRAFT, got {data['status']}"
    assert data["birth_plan_flags"] == {}, (
        f"omitted birth_plan_flags should default to empty map, got {data['birth_plan_flags']}")
    assert data["newborn_count"] == 0, (
        f"new registration newborn_count should be 0, got {data['newborn_count']}")


# =========================================================================
# Corner/entities/newborn_count_computed_field_updates_on_birth
# =========================================================================
def test_newborn_count_updates_on_births(api):
    """PRD §3.2: "Every birth recorded recomputes newborn_count and increments the
    registration's version."
    PRD §3.2: "The first birth recorded under a registration advances the registration
    from ADMITTED to BIRTH_RECORDED"

    Design: Corner/entities/newborn_count_computed_field_updates_on_birth
    """
    fx.set_clock("2026-03-05T12:00:00Z")
    reg, _ = fx.create_admitted_registration(due_date="2026-03-12")
    fx.record_birth(reg["id"], birth_datetime="2026-03-05T10:00:00Z", birth_sequence=1)
    fx.record_birth(reg["id"], birth_datetime="2026-03-05T10:05:00Z", birth_sequence=2,
                    weight_grams=3100)

    data = validate_success(api.get_registration(reg["id"], fx.CLERK))
    assert data["newborn_count"] == 2, (
        f"newborn_count should be 2 after two births, got {data['newborn_count']}")
    assert data["status"] == "BIRTH_RECORDED", (
        f"registration should be BIRTH_RECORDED after the first birth, got {data['status']}")


# =========================================================================
# Corner/entities/newborn_id_and_system_fields_server_generated
# =========================================================================
def test_recorded_newborn_starts_with_system_defaults(api):
    """PRD §3.2: "A newly recorded newborn starts with its clinical_status at BORN, its
    pre_registration_id set to the registration the birth was recorded under, its
    care_location at WELL_BABY_NURSERY, a discharge_readiness_score of 0, and a null
    discharged_at."

    Design: Corner/entities/newborn_id_and_system_fields_server_generated
    """
    fx.set_clock("2026-03-05T12:00:00Z")
    reg, _ = fx.create_admitted_registration(due_date="2026-03-12")
    data = validate_success(api.record_birth(
        reg["id"], f.record_birth_payload(), fx.NURSE), expected_status=201)
    assert data["clinical_status"] == "BORN", (
        f"new newborn should be BORN, got {data['clinical_status']}")
    assert data["care_location"] == "WELL_BABY_NURSERY", (
        f"new newborn should be in WELL_BABY_NURSERY, got {data['care_location']}")
    assert data["version"] == 1, f"new newborn version should be 1, got {data['version']}"


# =========================================================================
# Corner/entities/newborn_apgar_out_of_range_rejected
# =========================================================================
def test_record_birth_apgar_out_of_range_rejected(api):
    """PRD §3.2: "the APGAR score must be between 0 and 10 inclusive; a value outside
    these ranges is an ERR_INVALID_REQUEST."

    Design: Corner/entities/newborn_apgar_out_of_range_rejected
    """
    fx.set_clock("2026-03-05T12:00:00Z")
    reg, _ = fx.create_admitted_registration(due_date="2026-03-12")

    resp = api.record_birth(reg["id"], f.record_birth_payload(apgar_5min=11), fx.NURSE)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


# =========================================================================
# Corner/entities/duplicate_birth_sequence_within_registration_rejected
# =========================================================================
def test_duplicate_birth_sequence_rejected(api):
    """PRD §3.2: "an attempt to record a birth whose sequence number is already used
    under that registration is rejected with ERR_DUPLICATE_BIRTH_SEQUENCE."

    Design: Corner/entities/duplicate_birth_sequence_within_registration_rejected
    """
    fx.set_clock("2026-03-05T12:00:00Z")
    reg, _ = fx.create_admitted_registration(due_date="2026-03-12")
    fx.record_birth(reg["id"], birth_datetime="2026-03-05T10:00:00Z", birth_sequence=1)

    resp = api.record_birth(
        reg["id"],
        f.record_birth_payload(birth_datetime="2026-03-05T10:10:00Z", birth_sequence=1,
                               weight_grams=3000),
        fx.NURSE)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_BIRTH_SEQUENCE.value)


# =========================================================================
# Corner/entities/list_nicu_beds_pagination_envelope
# =========================================================================
def test_list_nicu_beds_pagination(api):
    """PRD §2.3: "The limit parameter caps the number of items returned"
    PRD §2.3: "List responses carry the pagination bookkeeping inside the meta object
    of the envelope, populating the limit, offset, total_count, and has_more fields."

    Design: Corner/entities/list_nicu_beds_pagination_envelope
    """
    fx.set_clock("2026-03-05T12:00:00Z")
    fx.create_bed(acuity_level="LEVEL_3", bed_label="NICU-1")
    fx.create_bed(acuity_level="LEVEL_2", bed_label="NICU-2")

    resp = api.list_nicu_beds(fx.NEO, params={"limit": 1, "offset": 0})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 2, f"total_count should be 2, got {meta['total_count']}"
    assert meta["has_more"] is True, "has_more should be true when limit < total_count"
    assert len(data) == 1, f"limit=1 should return one item, got {len(data)}"


# =========================================================================
# Corner/state_machines/registration_admit_outside_window_rejected
# =========================================================================
def test_admit_outside_window_rejected(api):
    """PRD §3.1: "An admit attempt whose clock date lands outside that inclusive window
    is rejected with ERR_ADMIT_WINDOW_CLOSED."

    Design: Corner/state_machines/registration_admit_outside_window_rejected
    """
    fx.set_clock("2026-01-01T00:00:00Z")  # before the window opens (due 2026-03-20 -> 2026-02-27)
    policy = fx.create_policy()
    reg = get_success_data(api.create_registration(
        f.create_registration_payload(policy["id"], due_date="2026-03-20"), fx.CLERK))
    get_success_data(api.submit_registration(reg["id"], fx.CLERK))

    resp = api.admit_registration(reg["id"], fx.CLERK)
    validate_error(resp, ApiErrorId.ERR_ADMIT_WINDOW_CLOSED.value)


# =========================================================================
# Corner/state_machines/submit_registration_from_draft_valid_transition
# =========================================================================
def test_submit_draft_registration(api):
    """PRD §3.1: "Submitting a registration advances it from DRAFT to SUBMITTED."
    PRD §3.1: "Each of these transitions — submit, admit, and cancel — increments the
    registration's version."

    Design: Corner/state_machines/submit_registration_from_draft_valid_transition
    """
    fx.set_clock("2026-03-05T12:00:00Z")
    policy = fx.create_policy()
    reg = get_success_data(api.create_registration(
        f.create_registration_payload(policy["id"], due_date="2026-03-12"), fx.CLERK))
    assert reg["version"] == 1

    data = validate_success(api.submit_registration(reg["id"], fx.CLERK))
    assert data["status"] == "SUBMITTED", (
        f"submit should move DRAFT to SUBMITTED, got {data['status']}")
    assert data["version"] == 2, f"submit should bump version to 2, got {data['version']}"


# =========================================================================
# Corner/rbac/intake_clerk_cannot_record_birth_unauthorized
# =========================================================================
def test_intake_clerk_cannot_record_birth(api):
    """PRD §2.1: "When the headers are valid but the named role is not permitted to
    perform the requested operation, the request is rejected with ERR_UNAUTHORIZED."
    PRD §2.1: "An AttendingNurse owns the newborn clinical lifecycle: recording births,
    rooming infants in, running lactation consults, assembling and issuing discharge
    bags, discharging, and working the nurse follow-up tasks."

    Design: Corner/rbac/intake_clerk_cannot_record_birth_unauthorized
    """
    fx.set_clock("2026-03-05T12:00:00Z")
    reg, _ = fx.create_admitted_registration(due_date="2026-03-12")

    resp = api.record_birth(reg["id"], f.record_birth_payload(), fx.CLERK)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)


# =========================================================================
# Corner/rbac/attending_nurse_cannot_escalate_nicu_unauthorized
# =========================================================================
def test_attending_nurse_cannot_escalate_nicu(api):
    """PRD §2.1: "When the headers are valid but the named role is not permitted to
    perform the requested operation, the request is rejected with ERR_UNAUTHORIZED."
    PRD §2.1: "A Neonatologist owns NICU escalation, step-down, the shared bed pool, and
    manual bed placement."

    Design: Corner/rbac/attending_nurse_cannot_escalate_nicu_unauthorized
    """
    fx.set_clock("2026-03-05T12:00:00Z")
    fx.create_bed(acuity_level="LEVEL_3")
    newborn, _, _ = fx.setup_admitted_with_newborn(
        weight_grams=1500, gestational_age_weeks=31, apgar_5min=9,
        birth_datetime="2026-03-05T10:00:00Z")
    nb_v = fx.get_newborn_version(newborn["id"], headers=fx.NURSE)

    resp = api.nicu_escalate(
        newborn["id"],
        f.nicu_escalate_payload(nb_v, required_level="LEVEL_3", admitted_at="2026-03-05T10:30:00Z"),
        fx.NURSE)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)


# =========================================================================
# Corner/rbac/missing_auth_headers_unauthenticated
# =========================================================================
def test_unknown_role_header_unauthenticated(api):
    """PRD §2.1: "If either header is missing, or if X-User-Role does not name a role
    the system recognizes, the request is rejected with ERR_UNAUTHENTICATED."

    Design: Corner/rbac/missing_auth_headers_unauthenticated
    """
    fx.set_clock("2026-03-05T12:00:00Z")
    from test_helpers import make_headers
    bogus = make_headers("test-bogus-1", "NotARealRole")

    resp = api.get_newborn("00000000-0000-4000-8000-000000000000", bogus)
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)
