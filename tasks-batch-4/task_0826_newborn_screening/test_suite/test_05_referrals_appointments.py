"""Confirmatory referrals, appointments, capacity, and completion (Newborn Screening PRD)."""
from test_helpers import (
    validate_success,
    validate_error,
    setup_case_with_referral,
    book_appointment,
    create_referral_payload,
    create_appointment_payload,
    TEST_USERS,
)

COORD = TEST_USERS["follow_up_coordinator_headers"]


# ─── Corner: resolve COMPLETED without a COMPLETED appointment ────────
def test_referral_resolve_completed_without_completed_appointment_rejected(api):
    """PRD §3.6: "A `COMPLETED` outcome requires the referral to be in `SCHEDULED` state
    (else `ERR_REFERRAL_NOT_SCHEDULED`) and requires at least one of its confirmatory
    appointments to be in `COMPLETED` state (else `ERR_APPOINTMENT_NOT_COMPLETED`); it moves
    the referral to `COMPLETED`, which is what unlocks the case's confirmed resolution."

    Design: Corner/validations/referral_resolve_completed_without_completed_appointment_returns_409
    """
    ctx = setup_case_with_referral()
    book_appointment(ctx["referral"])  # SCHEDULED, not completed → referral now SCHEDULED
    res = api.resolve_referral(ctx["referral"]["id"], {"outcome": "COMPLETED"}, COORD)
    validate_error(res, "ERR_APPOINTMENT_NOT_COMPLETED", expected_status=409)


# ─── Corner: appointment end before start ─────────────────────────────
def test_appointment_end_before_start_rejected(api):
    """PRD §3.6: "supplying the `referral_id`, a `start_datetime`, and an `end_datetime` that
    must be strictly after the start, else `ERR_INTERVAL_END_BEFORE_START`."

    Design: Corner/validations/appointment_end_before_start_returns_422
    """
    ctx = setup_case_with_referral()
    res = api.create_confirmatory_appointment(
        create_appointment_payload(
            ctx["referral"]["id"], "2026-03-05T10:00:00Z", "2026-03-05T09:00:00Z"
        ),
        COORD,
    )
    validate_error(res, "ERR_INTERVAL_END_BEFORE_START", expected_status=422)


# ─── Difficulty: referential mismatch beats duplicate-open constraint ─
def test_specialty_mismatch_wins_over_duplicate_open_referral(api):
    """PRD §3.6: "The `referral_reason` must equal the receiving clinic's `specialty`,
    otherwise the create is rejected with `ERR_CLINIC_SPECIALTY_MISMATCH`."
    PRD §2.10: "8. **Referential business rules** — clinic-specialty match,
    appointment-completion, and referral-resolution prerequisites."
    PRD §2.10: "9. **Duplication guards** — duplicate pending repeat and duplicate open
    referral."

    Design: Difficulty/priority_pair_validation_conflict/referral_create_referential_beats_constraint
    """
    ctx = setup_case_with_referral(
        specialty="AUDIOLOGY", referral_reason="AUDIOLOGY", clinic_name="Audiology Clinic"
    )
    # Second referral: reason CARDIOLOGY (mismatch, P8) AND case already has an open
    # referral (duplicate, P9). The referential error wins.
    res = api.create_referral(
        create_referral_payload(ctx["case"]["id"], ctx["clinic"]["id"], "CARDIOLOGY"),
        COORD,
    )
    validate_error(res, "ERR_CLINIC_SPECIALTY_MISMATCH", expected_status=422)


def test_duplicate_open_referral_when_specialty_matches(api):
    """PRD §3.6: "A case may hold at most one open referral at a time: if the case already
    has a referral in `REQUESTED` or `SCHEDULED` state, the create is rejected with
    `ERR_DUPLICATE_OPEN_REFERRAL`."

    Design: Difficulty/priority_pair_validation_conflict/referral_create_referential_beats_constraint
    """
    ctx = setup_case_with_referral(
        specialty="AUDIOLOGY", referral_reason="AUDIOLOGY", clinic_name="Audiology Clinic"
    )
    # Matching specialty (no P8 violation) but duplicate open referral (P9) → duplicate error.
    res = api.create_referral(
        create_referral_payload(ctx["case"]["id"], ctx["clinic"]["id"], "AUDIOLOGY"),
        COORD,
    )
    validate_error(res, "ERR_DUPLICATE_OPEN_REFERRAL", expected_status=409)


# ─── Difficulty: clinic aggregate capacity overlap ────────────────────
def test_clinic_capacity_one_rejects_overlapping_appointment(api):
    """PRD §3.6: "the number of `SCHEDULED` appointments at the same clinic whose interval
    overlaps the requested half-open interval must be strictly fewer than the clinic's
    `concurrent_capacity`; a booking that would meet or exceed that capacity is rejected with
    `ERR_CLINIC_CAPACITY_EXCEEDED`."

    Design: Difficulty/resource_temporal_overlap/clinic_capacity_one_rejects_overlapping_appointment
    """
    ctx = setup_case_with_referral(concurrent_capacity=1)
    book_appointment(ctx["referral"], "2026-03-05T09:00:00Z", "2026-03-05T10:00:00Z")
    res = api.create_confirmatory_appointment(
        create_appointment_payload(
            ctx["referral"]["id"], "2026-03-05T09:30:00Z", "2026-03-05T10:30:00Z"
        ),
        COORD,
    )
    validate_error(res, "ERR_CLINIC_CAPACITY_EXCEEDED", expected_status=409)


def test_clinic_capacity_one_allows_adjacent_non_overlapping_appointment(api):
    """PRD §3.6: "Overlap is measured on half-open intervals, so an appointment ending
    exactly when another begins does not overlap."

    Design: Difficulty/resource_temporal_overlap/clinic_capacity_one_rejects_overlapping_appointment
    """
    ctx = setup_case_with_referral(concurrent_capacity=1)
    book_appointment(ctx["referral"], "2026-03-05T09:00:00Z", "2026-03-05T10:00:00Z")
    res = api.create_confirmatory_appointment(
        create_appointment_payload(
            ctx["referral"]["id"], "2026-03-05T10:00:00Z", "2026-03-05T11:00:00Z"
        ),
        COORD,
    )
    appointment = validate_success(res, 201)
    assert appointment["status"] == "SCHEDULED"
