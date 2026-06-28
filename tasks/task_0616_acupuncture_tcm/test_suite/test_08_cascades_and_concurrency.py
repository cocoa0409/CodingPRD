"""Transitive cascades, package-credit accounting, OCC, and cross-entity gates.

Covers the plan-cancel depth-3 cascade difficulty instance, the provisional-vs-
finalized credit-divergence difficulty instance, the package-credit conservation
compensating-invariant difficulty instance, the state-beats-fiscal priority-pair
difficulty instance, the intake-gate cross-entity difficulty instance, and the corner
instances for add-on void cascade, OCC (stale/current plan and dispense versions),
and immediate visibility.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data, validate_paginated,
    ApiErrorId, TEST_USERS, make_practitioner_headers,
    assert_package_balance_identity,
    create_practitioner, create_patient, create_room, create_herb_item, create_formula,
    setup_finalized_intake, setup_active_plan, setup_clinic_scenario, setup_package_scenario,
    book_appointment, book_package_appointment, check_in_and_complete, add_addon,
    get_plan_version, create_appointment_payload, create_dispense_payload,
)

ADMIN = TEST_USERS["clinic_admin_headers"]
PHARM = TEST_USERS["pharmacist_headers"]


# ─── Provisional vs finalized credit divergence (queue A) ──────────────────
def test_package_provisional_vs_finalized_diverge(api):
    """PRD 3.4: "the provisional remaining balance provisional_remaining_credits is
    total_credits minus reserved_credits minus consumed_credits — a forward-looking
    figure that a still-scheduled appointment already lowers, used to gate new bookings
    and to drive the exhaustion transition."
    PRD 3.4: "The finalized remaining balance finalized_remaining_credits is
    total_credits minus consumed_credits alone — a chronological figure that only
    realized completions lower, used for billing and refund reconciliation; a merely
    scheduled appointment does not move it."

    Design: Difficulty/dual_variant_calc/package_credit_provisional_vs_finalized_diverge
    """
    ctx = setup_package_scenario(total_credits=10, price_paid_cents=90000)
    pkg_id = ctx["package"]["id"]
    # Three PACKAGE bookings; one completed, two left SCHEDULED.
    a1 = book_package_appointment(ctx, pkg_id,
                                  scheduled_start="2026-06-02T09:00:00Z",
                                  scheduled_end="2026-06-02T09:45:00Z")
    book_package_appointment(ctx, pkg_id,
                             scheduled_start="2026-06-02T10:00:00Z",
                             scheduled_end="2026-06-02T10:45:00Z")
    book_package_appointment(ctx, pkg_id,
                             scheduled_start="2026-06-02T11:00:00Z",
                             scheduled_end="2026-06-02T11:45:00Z")
    check_in_and_complete(ctx, a1["id"], clock_iso="2026-06-02T09:00:00Z")

    series = get_success_data(api.get_package_series(pkg_id, ADMIN))
    assert series["reserved_credits"] == 2
    assert series["consumed_credits"] == 1
    assert series["provisional_remaining_credits"] == 7  # 10 - 2 - 1
    assert series["finalized_remaining_credits"] == 9    # 10 - 1
    assert series["provisional_remaining_credits"] != series["finalized_remaining_credits"]
    assert_package_balance_identity(series)


def test_completion_lowers_finalized_not_provisional_net(api):
    """PRD 3.5: "the series' reserved_credits is decreased by one and its consumed_credits
    is increased by one — leaving the provisional balance net-unchanged for this step
    while lowering the finalized balance by one — with the exhaustion transition
    re-evaluated and the series version incremented."

    Design: Difficulty/dual_variant_calc/package_credit_provisional_vs_finalized_diverge
    """
    ctx = setup_package_scenario(total_credits=5, price_paid_cents=45000)
    pkg_id = ctx["package"]["id"]
    appt = book_package_appointment(ctx, pkg_id,
                                    scheduled_start="2026-06-02T09:00:00Z",
                                    scheduled_end="2026-06-02T09:45:00Z")
    before = get_success_data(api.get_package_series(pkg_id, ADMIN))
    check_in_and_complete(ctx, appt["id"], clock_iso="2026-06-02T09:00:00Z")
    after = get_success_data(api.get_package_series(pkg_id, ADMIN))
    assert after["provisional_remaining_credits"] == before["provisional_remaining_credits"]
    assert after["finalized_remaining_credits"] == before["finalized_remaining_credits"] - 1


# ─── Plan-cancel depth-3 cascade (queue A) ─────────────────────────────────
def test_plan_cancel_cascades_to_appointments_and_package(api):
    """PRD 3.3: "The cancellation then cascades: every appointment of this plan whose
    clinical status is SCHEDULED or CHECKED_IN is driven to CANCELLED through the system
    cancellation path, which fires that appointment's own full set of cancellation side
    effects described in Section 3.5 (including add-on voiding, billing voids, and
    package-credit release)."
    PRD 3.5: "As the third hop caused by the second, if that release lifts
    provisional_remaining_credits above 0 while the series is EXHAUSTED, the series
    auto-transitions from EXHAUSTED to ACTIVE, incurring a further series version bump."

    Design: Difficulty/transitive_cascade/plan_cancel_cascades_appointment_and_package_depth3
    """
    ctx = setup_package_scenario(total_credits=2, price_paid_cents=18000)
    pkg_id = ctx["package"]["id"]
    a1 = book_package_appointment(ctx, pkg_id,
                                  scheduled_start="2026-06-06T09:00:00Z",
                                  scheduled_end="2026-06-06T09:45:00Z")
    a2 = book_package_appointment(ctx, pkg_id,
                                  scheduled_start="2026-06-06T10:00:00Z",
                                  scheduled_end="2026-06-06T10:45:00Z")
    before = get_success_data(api.get_package_series(pkg_id, ADMIN))
    assert before["status"] == "EXHAUSTED"
    assert before["reserved_credits"] == 2
    assert before["provisional_remaining_credits"] == 0

    plv = get_plan_version(ctx["plan"]["id"])
    ph = make_practitioner_headers(ctx["practitioner"]["id"])
    cancelled = validate_success(
        api.cancel_plan(ctx["plan"]["id"], {"expected_treatment_plan_version": plv}, ph), 200)
    assert cancelled["status"] == "CANCELLED"

    ap1 = get_success_data(api.get_appointment(a1["id"], ADMIN))
    ap2 = get_success_data(api.get_appointment(a2["id"], ADMIN))
    assert ap1["clinical_status"] == "CANCELLED"
    assert ap2["clinical_status"] == "CANCELLED"

    after = get_success_data(api.get_package_series(pkg_id, ADMIN))
    assert after["reserved_credits"] == 0
    assert after["provisional_remaining_credits"] == 2
    assert after["status"] == "ACTIVE"


def test_plan_cancel_moves_plan_to_cancelled_terminal(api):
    """PRD 3.3: "On success the plan moves to the terminal CANCELLED state and its
    version is incremented."
    PRD 3.3: "every appointment of this plan whose clinical status is SCHEDULED or
    CHECKED_IN is driven to CANCELLED through the system cancellation path, which fires
    that appointment's own full set of cancellation side effects described in Section 3.5
    (including add-on voiding, billing voids, and package-credit release)."

    Design: Difficulty/transitive_cascade/plan_cancel_cascades_appointment_and_package_depth3
    """
    ctx = setup_clinic_scenario()
    appt = book_appointment(ctx, charge_source="PER_VISIT", base_fee_cents=12000,
                            scheduled_start="2026-06-06T14:00:00Z",
                            scheduled_end="2026-06-06T14:45:00Z")
    plv = get_plan_version(ctx["plan"]["id"])
    ph = make_practitioner_headers(ctx["practitioner"]["id"])
    cancelled = validate_success(
        api.cancel_plan(ctx["plan"]["id"], {"expected_treatment_plan_version": plv}, ph), 200)
    assert cancelled["status"] == "CANCELLED"
    reread = get_success_data(api.get_appointment(appt["id"], ADMIN))
    assert reread["clinical_status"] == "CANCELLED"


# ─── Package credit conservation across book + cancel (queue A) ────────────
def test_package_credits_conserved_book_then_cancel(api):
    """PRD 3.5: "As the second hop caused by the first, if the visit was a PACKAGE visit
    the held credit is released — the series' reserved_credits is decreased by one,
    provisional_remaining_credits is recomputed, and the series version is incremented."

    Design: Difficulty/compensating_invariant/package_credits_conserved_book_then_cancel
    """
    ctx = setup_package_scenario(total_credits=5, price_paid_cents=45000)
    pkg_id = ctx["package"]["id"]
    appt = book_package_appointment(ctx, pkg_id,
                                    scheduled_start="2026-06-12T09:00:00Z",
                                    scheduled_end="2026-06-12T09:45:00Z")
    booked = get_success_data(api.get_package_series(pkg_id, ADMIN))
    assert booked["reserved_credits"] == 1
    assert booked["provisional_remaining_credits"] == 4

    validate_success(api.cancel_appointment(appt["id"], ADMIN), 200)
    after = get_success_data(api.get_package_series(pkg_id, ADMIN))
    assert after["reserved_credits"] == 0
    assert after["consumed_credits"] == 0
    assert after["provisional_remaining_credits"] == 5
    assert_package_balance_identity(after)


def test_package_balance_identity_holds_after_booking(api):
    """PRD 3.4: "the provisional remaining balance provisional_remaining_credits is
    total_credits minus reserved_credits minus consumed_credits — a forward-looking
    figure that a still-scheduled appointment already lowers, used to gate new bookings
    and to drive the exhaustion transition."

    Design: Difficulty/compensating_invariant/package_credits_conserved_book_then_cancel
    """
    ctx = setup_package_scenario(total_credits=5, price_paid_cents=45000)
    pkg_id = ctx["package"]["id"]
    book_package_appointment(ctx, pkg_id,
                             scheduled_start="2026-06-12T13:00:00Z",
                             scheduled_end="2026-06-12T13:45:00Z")
    booked = get_success_data(api.get_package_series(pkg_id, ADMIN))
    # The conservation identity holds at the reserved (pre-cancel) state too.
    assert booked["reserved_credits"] == 1
    assert booked["consumed_credits"] == 0
    assert booked["provisional_remaining_credits"] == 4
    assert_package_balance_identity(booked)


# ─── State-beats-fiscal priority pair (queue A) ────────────────────────────
def test_booking_on_held_plan_reports_state_not_fiscal(api):
    """PRD 3.5: "The referenced plan must be ACTIVE, since no appointment may attach to
    a held, completed, or cancelled plan; a non-active plan yields ERR_PLAN_NOT_ACTIVE."
    PRD 2.8: "After these foundational checks, state preconditions for the requested
    transition are evaluated (the various ERR_*_NOT_* conflict errors), followed by
    cross-entity referential rules, then the domain-specific safety, temporal, and
    fiscal rules, and finally the optimistic-concurrency version check."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_package_booking
    """
    ctx = setup_package_scenario(total_credits=1, price_paid_cents=9000)
    pkg_id = ctx["package"]["id"]
    # Exhaust the package with one booking.
    book_package_appointment(ctx, pkg_id,
                             scheduled_start="2026-06-07T09:00:00Z",
                             scheduled_end="2026-06-07T09:45:00Z")
    # Put the plan ON_HOLD.
    ph = make_practitioner_headers(ctx["practitioner"]["id"])
    held = get_success_data(api.hold_plan(ctx["plan"]["id"], ph))

    # Booking onto an ON_HOLD plan from an exhausted package: plan-state wins.
    payload = create_appointment_payload(
        ctx["patient"]["id"], ctx["plan"]["id"], ctx["practitioner"]["id"],
        ctx["room"]["id"], held["version"], charge_source="PACKAGE",
        package_series_id=pkg_id, base_fee_cents=0,
        scheduled_start="2026-06-07T11:00:00Z", scheduled_end="2026-06-07T11:45:00Z")
    validate_error(api.create_appointment(payload, ADMIN),
                   ApiErrorId.ERR_PLAN_NOT_ACTIVE.value)


def test_booking_on_active_plan_with_credits_succeeds(api):
    """PRD 3.5: "The referenced plan must be ACTIVE, since no appointment may attach to
    a held, completed, or cancelled plan; a non-active plan yields ERR_PLAN_NOT_ACTIVE."
    PRD 3.5: "A package-funded booking additionally requires that the series have at
    least one provisional credit available and not be cancelled, as detailed in Section
    3.4; a booking that would draw from a series with provisional_remaining_credits below
    1 (or from a CANCELLED series) is rejected with ERR_NO_CREDITS_REMAINING."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_package_booking
    """
    # Mirror of the priority test with both the state (plan ACTIVE) and fiscal (credits
    # available) conditions satisfied: the booking succeeds, confirming neither check
    # spuriously fires when its precondition is met.
    ctx = setup_package_scenario(total_credits=2, price_paid_cents=18000)
    appt = book_package_appointment(ctx, ctx["package"]["id"],
                                    scheduled_start="2026-06-07T13:00:00Z",
                                    scheduled_end="2026-06-07T13:45:00Z")
    assert appt["clinical_status"] == "SCHEDULED"
    assert appt["charge_source"] == "PACKAGE"


# ─── Cross-entity intake gate (queue A) ────────────────────────────────────
def test_booking_requires_patient_intake_complete(api):
    """PRD 3.5: "The patient must have completed intake — that is, intake_status must be
    INTAKE_COMPLETE — or the booking is rejected with ERR_INTAKE_REQUIRED."

    Design: Difficulty/cross_entity_state_dependency/booking_requires_patient_intake_complete
    """
    prac = create_practitioner()
    room = create_room()
    # A reference patient with a finalized intake supplies an ACTIVE plan to point at.
    ref_patient = create_patient(full_name="NoIntake Pat")
    ref_intake = setup_finalized_intake(ref_patient["id"], prac["id"])
    plan = setup_active_plan(ref_patient["id"], prac["id"], ref_intake["id"], acupoints=["LI4"])

    # Patient under test has NO finalized intake -> intake_status PENDING_INTAKE.
    pending = create_patient(full_name="Pending Pat")
    assert pending["intake_status"] == "PENDING_INTAKE"

    plv = get_plan_version(plan["id"])
    payload = create_appointment_payload(
        pending["id"], plan["id"], prac["id"], room["id"], plv,
        charge_source="PER_VISIT", base_fee_cents=12000,
        scheduled_start="2026-06-09T09:00:00Z", scheduled_end="2026-06-09T09:45:00Z")
    validate_error(api.create_appointment(payload, ADMIN),
                   ApiErrorId.ERR_INTAKE_REQUIRED.value)


def test_booking_succeeds_once_patient_intake_complete(api):
    """PRD 3.5: "The patient must have completed intake — that is, intake_status must be
    INTAKE_COMPLETE — or the booking is rejected with ERR_INTAKE_REQUIRED."
    PRD 3.2: "the owning patient's intake_status flips from PENDING_INTAKE to
    INTAKE_COMPLETE, with the patient's version incremented by one and the intake's own
    version incremented by one."

    Design: Difficulty/cross_entity_state_dependency/booking_requires_patient_intake_complete
    """
    # Same patient now has a finalized intake (intake_status INTAKE_COMPLETE), so the
    # booking that the intake gate rejected above now succeeds.
    ctx = setup_clinic_scenario()
    assert get_success_data(api.get_patient(ctx["patient"]["id"], ADMIN))["intake_status"] \
        == "INTAKE_COMPLETE"
    appt = book_appointment(ctx, charge_source="PER_VISIT", base_fee_cents=12000,
                            scheduled_start="2026-06-09T13:00:00Z",
                            scheduled_end="2026-06-09T13:45:00Z")
    assert appt["clinical_status"] == "SCHEDULED"


# ─── Add-on void cascade on appointment cancel (corner) ────────────────────
def test_cancel_appointment_voids_attached_addons(api):
    """PRD 3.5: "As the first hop, this appointment moves to CANCELLED, all ATTACHED
    add-ons move to VOIDED, and any OPEN Charge or ISSUED Superbill already produced for
    the appointment moves to VOID (with the billing status moving to WAIVED); the
    appointment's version is incremented."

    Design: Corner/cross_cutting_complexity_layers/cascade_addons_voided_on_appointment_cancel
    """
    ctx = setup_clinic_scenario()
    # Clock well before the appointment start (>24h lead → no strike).
    get_success_data(api.set_clock("2026-06-25T10:00:00Z", ADMIN))
    appt = book_appointment(ctx, charge_source="PER_VISIT", base_fee_cents=12000,
                            scheduled_start="2026-06-28T10:00:00Z",
                            scheduled_end="2026-06-28T10:45:00Z")
    ad1 = add_addon(appt["id"], "CUPPING", 3500)
    ad2 = add_addon(appt["id"], "MOXA", 2500)

    cancelled = validate_success(api.cancel_appointment(appt["id"], ADMIN), 200)
    assert cancelled["clinical_status"] == "CANCELLED"

    patient = get_success_data(api.get_patient(ctx["patient"]["id"], ADMIN))
    assert patient["strike_count"] == 0  # >24h lead

    addons, _ = validate_paginated(api.list_addons(ADMIN, params={"appointment_id": appt["id"]}))
    by_id = {a["id"]: a for a in addons}
    assert by_id[ad1["id"]]["status"] == "VOIDED"
    assert by_id[ad2["id"]]["status"] == "VOIDED"


# ─── OCC: stale plan version on booking (corner) ───────────────────────────
def test_occ_stale_plan_version_on_booking_rejected(api):
    """PRD 2.6: "If another writer has advanced the plan's version since the client last
    read it — for instance through a hold, a resume, an earlier booking, or a dispense —
    the booking is rejected with ERR_STALE_VERSION (HTTP 412), preventing the client
    from attaching a visit to a plan it has not observed in its current form."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_plan_version_on_booking
    """
    ctx = setup_clinic_scenario()
    plan = ctx["plan"]
    v0 = get_plan_version(plan["id"])
    # First booking succeeds and advances the plan version above v0.
    payload1 = create_appointment_payload(
        ctx["patient"]["id"], plan["id"], ctx["practitioner"]["id"], ctx["room"]["id"], v0,
        charge_source="PER_VISIT", base_fee_cents=12000,
        scheduled_start="2026-06-26T09:00:00Z", scheduled_end="2026-06-26T09:45:00Z")
    validate_success(api.create_appointment(payload1, ADMIN), 201)
    assert get_plan_version(plan["id"]) > v0

    # Second booking carrying the STALE v0 → ERR_STALE_VERSION (412).
    payload2 = create_appointment_payload(
        ctx["patient"]["id"], plan["id"], ctx["practitioner"]["id"], ctx["room"]["id"], v0,
        charge_source="PER_VISIT", base_fee_cents=12000,
        scheduled_start="2026-06-26T11:00:00Z", scheduled_end="2026-06-26T11:45:00Z")
    validate_error(api.create_appointment(payload2, ADMIN), ApiErrorId.ERR_STALE_VERSION.value)


# ─── OCC: current plan version succeeds on dispense (corner) ───────────────
def test_occ_current_plan_version_succeeds_on_dispense(api):
    """PRD 2.6: "Identically, creating a herbal-formula dispense requires
    expected_treatment_plan_version matching the referenced plan's current version; a
    mismatch is rejected with ERR_STALE_VERSION (HTTP 412)."
    PRD 3.9: "A requested dispense opens with status of REQUESTED, increments the
    referenced plan's version, and itself starts at version 1."

    Design: Corner/cross_cutting_complexity_layers/occ_current_plan_version_succeeds_on_dispense
    """
    herb = create_herb_item(herb_name="Bai Zhu", initial_grams=500, reorder_threshold_grams=50)
    formula = create_formula(herb["id"], grams_per_dose=10)
    prac = create_practitioner()
    patient = create_patient(full_name="O2 Pat")
    intake = setup_finalized_intake(patient["id"], prac["id"],
                                    tongue_finding="PALE", pulse_finding="DEEP",
                                    tcm_pattern="YANG_DEFICIENCY")
    plan = setup_active_plan(patient["id"], prac["id"], intake["id"], acupoints=["CV4"])
    v0 = get_plan_version(plan["id"])
    # First dispense advances the plan version.
    get_success_data(api.create_dispense(
        create_dispense_payload(patient["id"], plan["id"], formula["id"], v0, doses=1), PHARM))
    v_now = get_plan_version(plan["id"])
    assert v_now > v0

    # Second dispense with the CURRENT (re-read) version succeeds.
    second = validate_success(api.create_dispense(
        create_dispense_payload(patient["id"], plan["id"], formula["id"], v_now, doses=2), PHARM), 201)
    assert second["status"] == "REQUESTED"


# ─── OCC: stale dispense version on reverse (corner) ───────────────────────
def test_occ_stale_dispense_version_on_reverse_rejected(api):
    """PRD 2.6: "reversing a filled dispense requires expected_formula_dispense_version
    to match that dispense's current version; either mismatch is rejected with
    ERR_STALE_VERSION (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_dispense_version_on_reverse
    """
    herb = create_herb_item(herb_name="Dang Shen", initial_grams=500, reorder_threshold_grams=50)
    formula = create_formula(herb["id"], grams_per_dose=10)
    prac = create_practitioner()
    patient = create_patient(full_name="O3 Pat")
    intake = setup_finalized_intake(patient["id"], prac["id"],
                                    tongue_finding="PALE", pulse_finding="DEEP",
                                    tcm_pattern="YANG_DEFICIENCY")
    plan = setup_active_plan(patient["id"], prac["id"], intake["id"], acupoints=["CV4"])
    v0 = get_plan_version(plan["id"])
    dispense = get_success_data(api.create_dispense(
        create_dispense_payload(patient["id"], plan["id"], formula["id"], v0, doses=1), PHARM))
    filled = get_success_data(api.fill_dispense(dispense["id"], PHARM))

    # Reverse with a stale version (one less than current FILLED version).
    validate_error(api.reverse_dispense(
        dispense["id"], {"expected_formula_dispense_version": filled["version"] - 1}, PHARM),
        ApiErrorId.ERR_STALE_VERSION.value)
    still = get_success_data(api.get_dispense(dispense["id"], PHARM))
    assert still["status"] == "FILLED"


# ─── Immediate consistency (corner) ────────────────────────────────────────
def test_booked_appointment_immediately_visible_in_list(api):
    """PRD 3.5: "Appointments may be listed and filtered by any of patient_id,
    treatment_plan_id, practitioner_id, room_id, or package_series_id, and retrieved by
    id, with read access for a ClinicAdmin, a Practitioner, or the owning patient."

    Design: Corner/consistency_model/immediate_visibility_of_booking_in_get
    """
    ctx = setup_clinic_scenario()
    appt = book_appointment(ctx, charge_source="PER_VISIT", base_fee_cents=12000,
                            scheduled_start="2026-06-29T10:00:00Z",
                            scheduled_end="2026-06-29T10:45:00Z")
    data, meta = validate_paginated(
        api.list_appointments(ADMIN, params={"treatment_plan_id": ctx["plan"]["id"]}))
    assert meta["total_count"] == 1
    assert data[0]["id"] == appt["id"]
    assert data[0]["clinical_status"] == "SCHEDULED"
