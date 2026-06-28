"""Booking safety/temporal/fiscal gates, validation priority conflicts,
cross-entity state dependencies, and temporal-window boundaries.

Translates queue-A priority_pair_validation_conflict, cross_entity_state_dependency,
and resource_temporal_overlap instances plus queue-B validation corner instances.
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    TEST_USERS,
    make_technician_headers,
    setup_booking_ready,
    setup_completed_appointment,
    book_initial_appointment,
    pay_deposit,
    set_clock,
    create_appointment_payload,
    create_annual_refresh_payload,
    create_touch_up_payload,
    create_package_payload,
    deposit_payload,
)

FRONT = TEST_USERS["front_desk_headers"]
ADMIN = TEST_USERS["studio_admin_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]
TECH = TEST_USERS["technician_headers"]


# ─────────────────────────────────────────────────────────────────────────────
# Queue A: priority_pair_validation_conflict
# ─────────────────────────────────────────────────────────────────────────────
def test_consent_missing_outranks_cooling_off(api):
    """PRD §3.5: "Next, consent must be present: a `ConsentRecord` of type
    `PROCEDURE_CONSENT` for the client must exist before booking ... absence
    raises `ERR_CONSENT_MISSING`. Next, the patch-test gate ... Next, the
    cooling-off rule: the `scheduled_start` must be at or after the patch test's
    `applied_at` plus the 48-hour patch-read minimum, otherwise
    `ERR_COOLING_OFF_VIOLATION`."

    Design: Difficulty/priority_pair_validation_conflict/ppvc_consent_missing_beats_cooling_off
    """
    # No PROCEDURE_CONSENT on file (so the consent gate trips) AND scheduled_start
    # violates the 48h cooling-off. An age_verified PHOTO_RELEASE consent is present
    # so the higher-priority age gate (which only requires *some* age_verified
    # consent, PRD §3.5) clears and the PROCEDURE_CONSENT-absence gate is the one
    # that fires.
    ctx = setup_booking_ready(consent=False)
    api.create_consent_record(
        {
            "client_id": ctx["client"]["id"],
            "consent_type": "PHOTO_RELEASE",
            "age_verified": True,
            "signed_by_name": "C",
        },
        FRONT,
    )
    payload = create_appointment_payload(
        ctx["client"]["id"],
        ctx["technician"]["id"],
        ctx["formula"]["id"],
        ctx["patch_test"]["id"],
        procedure_type="BROWS",
        scheduled_start="2026-01-03T02:00:00Z",  # only ~1h after read; <48h after applied
    )
    res = api.create_appointment(payload, FRONT)
    validate_error(res, "ERR_CONSENT_MISSING")


def test_cooling_off_fires_once_consent_present(api):
    """PRD §3.5: "Next, the cooling-off rule: the `scheduled_start` must be at or
    after the patch test's `applied_at` plus the 48-hour patch-read minimum,
    otherwise `ERR_COOLING_OFF_VIOLATION`."

    Design: Difficulty/priority_pair_validation_conflict/ppvc_consent_missing_beats_cooling_off
    """
    # Consent IS on file now, so the consent gate clears and the lower-priority
    # cooling-off violation (scheduled_start < applied_at + 48h) is the one reported.
    ctx = setup_booking_ready(consent=True)
    payload = create_appointment_payload(
        ctx["client"]["id"],
        ctx["technician"]["id"],
        ctx["formula"]["id"],
        ctx["patch_test"]["id"],
        procedure_type="BROWS",
        scheduled_start="2026-01-02T23:59:59Z",  # 47h59m59s after applied_at -> cooling-off violated
    )
    res = api.create_appointment(payload, FRONT)
    validate_error(res, "ERR_COOLING_OFF_VIOLATION")


def test_invalid_state_outranks_deposit_amount_mismatch(api):
    """PRD §2.9: "After those structural checks, the system verifies that the
    target resource is in a valid source state for the requested transition
    (`ERR_INVALID_STATE`). Only then are the domain-specific safety, temporal,
    fiscal, and referential checks evaluated".

    Design: Difficulty/priority_pair_validation_conflict/ppvc_invalid_state_beats_deposit_amount
    """
    # Appointment already DEPOSIT_PAID; second deposit with a wrong amount.
    ctx = setup_booking_ready()
    appt = book_initial_appointment(ctx, scheduled_start="2026-01-06T10:00:00Z")
    pay_deposit(appt)
    res = api.deposit(appt["id"], deposit_payload(999), FRONT)
    validate_error(res, "ERR_INVALID_STATE")


def test_deposit_amount_mismatch_fires_when_state_valid(api):
    """PRD §3.6: "this is permitted only while the payment status is
    `AWAITING_DEPOSIT`, and the charged `amount_cents` must equal the
    appointment's `deposit_required_cents` or the charge is rejected with
    `ERR_DEPOSIT_AMOUNT_MISMATCH`."

    Design: Difficulty/priority_pair_validation_conflict/ppvc_invalid_state_beats_deposit_amount
    """
    # Appointment still AWAITING_DEPOSIT (valid source state for /deposit); the
    # state gate clears, so the fiscal amount-mismatch check is the one reported.
    ctx = setup_booking_ready()
    appt = book_initial_appointment(ctx, scheduled_start="2026-01-06T10:00:00Z")
    res = api.deposit(appt["id"], deposit_payload(999), FRONT)
    validate_error(res, "ERR_DEPOSIT_AMOUNT_MISMATCH")


# ─────────────────────────────────────────────────────────────────────────────
# Queue A: cross_entity_state_dependency
# ─────────────────────────────────────────────────────────────────────────────
def test_failing_patch_test_blocks_booking(api):
    """PRD §3.3: "computes `result` as `PASS` when the reaction grade is at most
    1 and `FAIL` when the reaction grade is at least 2".
    PRD §3.5: "the linked patch test must be in status `READ` with `result` of
    `PASS` — a `FAIL` result or any non-read test blocks the booking with
    `ERR_PATCH_TEST_FAILED`."

    Design: Difficulty/cross_entity_state_dependency/cesd_start_requires_patchtest_read_pass
    """
    # Patch test READ with grade 2 -> result FAIL.
    ctx = setup_booking_ready(patch_reaction_grade=2)
    pt = validate_success(api.get_patch_test(ctx["patch_test"]["id"], FRONT), 200)
    assert pt["result"] == "FAIL"
    payload = create_appointment_payload(
        ctx["client"]["id"],
        ctx["technician"]["id"],
        ctx["formula"]["id"],
        ctx["patch_test"]["id"],
        procedure_type="BROWS",
        scheduled_start="2026-01-06T10:00:00Z",
    )
    res = api.create_appointment(payload, FRONT)
    validate_error(res, "ERR_PATCH_TEST_FAILED")


def test_passing_patch_test_allows_booking(api):
    """PRD §3.3: "computes `result` as `PASS` when the reaction grade is at most
    1".
    PRD §3.5: "the linked patch test must be in status `READ` with `result` of
    `PASS` — a `FAIL` result or any non-read test blocks the booking with
    `ERR_PATCH_TEST_FAILED`."

    Design: Difficulty/cross_entity_state_dependency/cesd_start_requires_patchtest_read_pass
    """
    # Patch test READ with grade 1 -> result PASS; the gate clears and booking succeeds.
    ctx = setup_booking_ready(patch_reaction_grade=1)
    pt = validate_success(api.get_patch_test(ctx["patch_test"]["id"], FRONT), 200)
    assert pt["status"] == "READ"
    assert pt["result"] == "PASS"
    payload = create_appointment_payload(
        ctx["client"]["id"],
        ctx["technician"]["id"],
        ctx["formula"]["id"],
        ctx["patch_test"]["id"],
        procedure_type="BROWS",
        scheduled_start="2026-01-06T10:00:00Z",
    )
    appt = validate_success(api.create_appointment(payload, FRONT), 201)
    assert appt["lifecycle_status"] == "BOOKED"


def test_expired_license_blocks_procedure_start(api):
    """PRD §3.6: "Starting is permitted only when ... the technician's
    `license_status` is `LICENSE_ACTIVE`, the studio's `compliance_posture` is
    `OPEN` ... A license or posture failure at start raises
    `ERR_LICENSE_INVALID`".
    PRD §3.1: "the system treats a license as `LICENSE_EXPIRED` ... when, at any
    procedure-gating check, the `license_expiry` is at or before the current
    logical-clock time".

    Design: Difficulty/cross_entity_state_dependency/cesd_start_requires_technician_license_active
    """
    # Technician license_expiry 2026-01-05; book while valid, advance past expiry, then start.
    ctx = setup_booking_ready(technician_overrides={"license_expiry": "2026-01-05T00:00:00Z"})
    appt = book_initial_appointment(ctx, scheduled_start="2026-01-06T10:00:00Z")
    pay_deposit(appt)
    set_clock("2026-01-06T00:00:00Z")  # past the technician's license_expiry
    res = api.start_appointment(appt["id"], make_technician_headers(ctx["technician"]["id"]))
    validate_error(res, "ERR_LICENSE_INVALID")
    after = validate_success(api.get_appointment(appt["id"], FRONT), 200)
    assert after["lifecycle_status"] == "BOOKED", (
        "license expiry at start is a gating check, not a void cascade"
    )


def test_active_license_allows_procedure_start(api):
    """PRD §3.6: "Starting is permitted only when the lifecycle is `BOOKED`, the
    payment status is `DEPOSIT_PAID` or `PAID_IN_FULL`, the technician's
    `license_status` is `LICENSE_ACTIVE`, the studio's `compliance_posture` is
    `OPEN`, at least one sterile kit is available, and the linked patch test is
    `READ` with `result` `PASS`."

    Design: Difficulty/cross_entity_state_dependency/cesd_start_requires_technician_license_active
    """
    # Technician license valid through 2030; start clears the license gate.
    ctx = setup_booking_ready()
    assert ctx["technician"]["license_status"] == "LICENSE_ACTIVE"
    appt = book_initial_appointment(ctx, scheduled_start="2026-01-06T10:00:00Z")
    pay_deposit(appt)
    started = validate_success(
        api.start_appointment(appt["id"], make_technician_headers(ctx["technician"]["id"])), 200
    )
    assert started["lifecycle_status"] == "IN_PROCEDURE"


# ─────────────────────────────────────────────────────────────────────────────
# Queue A: resource_temporal_overlap
# ─────────────────────────────────────────────────────────────────────────────
def test_cooling_off_lower_bound_one_second_short_rejected(api):
    """PRD §3.5: "the cooling-off rule: the `scheduled_start` must be at or after
    the patch test's `applied_at` plus the 48-hour patch-read minimum, otherwise
    `ERR_COOLING_OFF_VIOLATION`."

    Design: Difficulty/resource_temporal_overlap/rto_cooling_off_48h_halfopen_lower_bound
    """
    # applied_at = 2026-01-01T00:00:00Z; scheduled_start 47h59m59s later is rejected.
    ctx = setup_booking_ready()
    payload = create_appointment_payload(
        ctx["client"]["id"],
        ctx["technician"]["id"],
        ctx["formula"]["id"],
        ctx["patch_test"]["id"],
        procedure_type="BROWS",
        scheduled_start="2026-01-02T23:59:59Z",
    )
    res = api.create_appointment(payload, FRONT)
    validate_error(res, "ERR_COOLING_OFF_VIOLATION")


def test_cooling_off_lower_bound_exactly_48h_accepted(api):
    """PRD §3.5: "the `scheduled_start` must be at or after the patch test's
    `applied_at` plus the 48-hour patch-read minimum".

    Design: Difficulty/resource_temporal_overlap/rto_cooling_off_48h_halfopen_lower_bound
    """
    # applied_at = 2026-01-01T00:00:00Z; scheduled_start exactly +48h is accepted.
    ctx = setup_booking_ready()
    payload = create_appointment_payload(
        ctx["client"]["id"],
        ctx["technician"]["id"],
        ctx["formula"]["id"],
        ctx["patch_test"]["id"],
        procedure_type="BROWS",
        scheduled_start="2026-01-03T00:00:00Z",
    )
    appt = validate_success(api.create_appointment(payload, FRONT), 201)
    assert appt["lifecycle_status"] == "BOOKED"


def test_touchup_window_upper_bound_exceeded_rejected(api):
    """PRD §3.8: "A touch-up booking is gated by the touch-up window — the
    `scheduled_start` must fall within the source's `completed_at` plus 30 days
    through the source's `completed_at` plus 60 days, and the package must be
    `ACTIVE` with `remaining_sessions` greater than 0, otherwise
    `ERR_TOUCHUP_WINDOW_CLOSED`."

    Design: Difficulty/resource_temporal_overlap/rto_touchup_window_closed_upper_bound
    """
    # completed_at 2026-02-01; touch-up scheduled_start 2026-04-03 (62 days, past +60d).
    ctx, completed = setup_completed_appointment(
        scheduled_start="2026-01-06T10:00:00Z", complete_clock="2026-02-01T00:00:00Z"
    )
    # A second READ/PASS patch test for the touch-up procedure.
    pt2 = get_success_data(api.create_patch_test({"client_id": ctx["client"]["id"]}, TECH))
    set_clock("2026-02-03T01:00:00Z")  # >=48h after pt applied_at (2026-02-01T00:00:00Z) to satisfy patch-read minimum
    get_success_data(
        api.read_patch_test(pt2["id"], {"reaction_grade": 1}, make_technician_headers(ctx["technician"]["id"]))
    )
    pkg = get_success_data(
        api.create_package(
            create_package_payload(ctx["client"]["id"], completed["id"], included_sessions=2, pricing_mode="PAYG"),
            FRONT,
        )
    )
    set_clock("2026-04-03T00:00:00Z")
    res = api.book_touch_up(
        create_touch_up_payload(
            pkg["id"],
            ctx["technician"]["id"],
            ctx["formula"]["id"],
            pt2["id"],
            scheduled_start="2026-04-03T10:00:00Z",
            expected_package_version=pkg["version"],
            procedure_type="BROWS",
        ),
        FRONT,
    )
    validate_error(res, "ERR_TOUCHUP_WINDOW_CLOSED")


def test_touchup_within_window_accepted(api):
    """PRD §3.8: "A touch-up booking is gated by the touch-up window — the
    `scheduled_start` must fall within the source's `completed_at` plus 30 days
    through the source's `completed_at` plus 60 days, and the package must be
    `ACTIVE` with `remaining_sessions` greater than 0, otherwise
    `ERR_TOUCHUP_WINDOW_CLOSED`."

    Design: Difficulty/resource_temporal_overlap/rto_touchup_window_closed_upper_bound
    """
    # completed_at 2026-02-01; touch-up scheduled_start 2026-03-10 (37 days, inside [+30d,+60d]).
    ctx, completed = setup_completed_appointment(
        scheduled_start="2026-01-06T10:00:00Z", complete_clock="2026-02-01T00:00:00Z"
    )
    pt2 = get_success_data(api.create_patch_test({"client_id": ctx["client"]["id"]}, TECH))
    set_clock("2026-02-03T01:00:00Z")  # >=48h after pt applied_at (2026-02-01T00:00:00Z) to satisfy patch-read minimum
    get_success_data(
        api.read_patch_test(pt2["id"], {"reaction_grade": 1}, make_technician_headers(ctx["technician"]["id"]))
    )
    pkg = get_success_data(
        api.create_package(
            create_package_payload(ctx["client"]["id"], completed["id"], included_sessions=2, pricing_mode="PAYG"),
            FRONT,
        )
    )
    set_clock("2026-03-05T00:00:00Z")
    appt = validate_success(
        api.book_touch_up(
            create_touch_up_payload(
                pkg["id"],
                ctx["technician"]["id"],
                ctx["formula"]["id"],
                pt2["id"],
                scheduled_start="2026-03-10T10:00:00Z",
                expected_package_version=pkg["version"],
                procedure_type="BROWS",
            ),
            FRONT,
        ),
        201,
    )
    assert appt["appointment_kind"] == "TOUCH_UP"
    assert appt["lifecycle_status"] == "BOOKED"


# ─────────────────────────────────────────────────────────────────────────────
# Queue B: validations
# ─────────────────────────────────────────────────────────────────────────────
def test_minor_blocked_with_age_not_verified(api):
    """PRD §3.5: "First, age must be verified: at booking, the whole number of
    years between the client's `date_of_birth` and the `scheduled_start` must be
    at least the studio's `min_client_age`, and a consent record with
    `age_verified` set true must exist on file for the client; failure raises
    `ERR_AGE_NOT_VERIFIED`."

    Design: Corner/validations/val_age_not_verified_minor
    """
    ctx = setup_booking_ready(client_overrides={"full_name": "Minor", "date_of_birth": "2015-01-01T00:00:00Z"})
    payload = create_appointment_payload(
        ctx["client"]["id"],
        ctx["technician"]["id"],
        ctx["formula"]["id"],
        ctx["patch_test"]["id"],
        procedure_type="BROWS",
        scheduled_start="2026-01-06T10:00:00Z",
    )
    res = api.create_appointment(payload, FRONT)
    validate_error(res, "ERR_AGE_NOT_VERIFIED")


def test_high_risk_client_without_clearance_blocked(api):
    """PRD §3.5: "Next, the high-risk gate: if the client's `risk_band` is
    `HIGH_RISK`, the client's `medical_cleared` must be true, otherwise
    `ERR_MEDICAL_CLEARANCE_REQUIRED`."

    Design: Corner/validations/val_high_risk_requires_medical_clearance
    """
    # setup_booking_ready reads a PASS patch test (reaction_grade 1), which copies
    # skin_sensitivity_observed=1 onto the client and makes risk use the observed
    # grade (PRD §3.3). Medical/prior counts are chosen so risk stays >=30 with the
    # observed sensitivity of 1: 8*2 + 12*1 + 5*1 = 33 -> HIGH_RISK.
    ctx = setup_booking_ready(
        client_overrides={
            "full_name": "HR",
            "medical_flag_count": 2,
            "prior_adverse_reactions": 1,
            "skin_sensitivity_self": 2,
        }
    )
    client = validate_success(api.get_client(ctx["client"]["id"], FRONT), 200)
    assert client["risk_band"] == "HIGH_RISK"
    payload = create_appointment_payload(
        ctx["client"]["id"],
        ctx["technician"]["id"],
        ctx["formula"]["id"],
        ctx["patch_test"]["id"],
        procedure_type="BROWS",
        scheduled_start="2026-01-06T10:00:00Z",
    )
    res = api.create_appointment(payload, FRONT)
    validate_error(res, "ERR_MEDICAL_CLEARANCE_REQUIRED")


def test_annual_refresh_before_365d_not_due(api):
    """PRD §3.8: "An annual-refresh booking is gated by the annual-refresh
    window: the `scheduled_start` must be at or after the source appointment's
    `completed_at` plus 365 days, otherwise `ERR_REFRESH_NOT_DUE`."

    Design: Corner/validations/val_refresh_not_due_before_365d
    """
    # completed_at 2026-02-01; refresh attempted 2026-06-05 (well before +365d).
    ctx, completed = setup_completed_appointment(
        scheduled_start="2026-01-06T10:00:00Z", complete_clock="2026-02-01T00:00:00Z"
    )
    pt2 = get_success_data(api.create_patch_test({"client_id": ctx["client"]["id"]}, TECH))
    set_clock("2026-02-03T01:00:00Z")  # >=48h after pt applied_at (2026-02-01T00:00:00Z) to satisfy patch-read minimum
    get_success_data(
        api.read_patch_test(pt2["id"], {"reaction_grade": 1}, make_technician_headers(ctx["technician"]["id"]))
    )
    set_clock("2026-06-01T00:00:00Z")
    res = api.book_annual_refresh(
        create_annual_refresh_payload(
            completed["id"],
            ctx["technician"]["id"],
            ctx["formula"]["id"],
            pt2["id"],
            scheduled_start="2026-06-05T10:00:00Z",
            procedure_type="BROWS",
        ),
        FRONT,
    )
    validate_error(res, "ERR_REFRESH_NOT_DUE")


def test_first_deposit_wrong_amount_mismatch(api):
    """PRD §3.6: "the charged `amount_cents` must equal the appointment's
    `deposit_required_cents` or the charge is rejected with
    `ERR_DEPOSIT_AMOUNT_MISMATCH`."

    Design: Corner/validations/val_deposit_amount_mismatch
    """
    ctx = setup_booking_ready()
    appt = book_initial_appointment(ctx, scheduled_start="2026-01-06T10:00:00Z")
    assert appt["deposit_required_cents"] == 13000
    res = api.deposit(appt["id"], deposit_payload(12000), FRONT)
    validate_error(res, "ERR_DEPOSIT_AMOUNT_MISMATCH")


def test_redo_on_good_healing_not_eligible(api):
    """PRD §3.7: "A redo is eligible only when the source appointment is
    `COMPLETED` with `healing_outcome` of `POOR` and the current logical-clock
    time is at or before the source's `completed_at` plus the 90-day redo window;
    an ineligible request is rejected with `ERR_REDO_NOT_ELIGIBLE`".

    Design: Corner/validations/val_redo_not_eligible_good_healing
    """
    ctx, completed = setup_completed_appointment(
        healing_outcome_flag="GOOD",
        scheduled_start="2026-01-06T10:00:00Z",
        complete_clock="2026-02-01T00:00:00Z",
    )
    assert completed["healing_outcome"] == "GOOD"
    res = api.create_redo_request({"appointment_id": completed["id"], "reason": "wants change"}, FRONT)
    validate_error(res, "ERR_REDO_NOT_ELIGIBLE")
