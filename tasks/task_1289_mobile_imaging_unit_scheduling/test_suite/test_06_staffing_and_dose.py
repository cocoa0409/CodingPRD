"""Staffing gates (cert, drive time, date conflict, projected dose), radiation
dose records (DRL flags, applicability, identity), and dose aggregates."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_site_day,
    assert_dose_record,
    assign_staffing,
    book_appointment,
    book_and_complete_appointment,
    complete_appointment_flow,
    create_appointment_payload,
    create_contract,
    create_facility,
    create_route_plan,
    create_dose_record_payload,
    create_staffing_assignment_payload,
    create_technologist,
    create_unit,
    create_accreditation,
    drive_day_to_in_service,
    get_success_data,
    make_facility_coordinator_headers,
    make_technologist_headers,
    post_dose_record,
    set_clock,
    setup_bookable_day,
    setup_in_service_day,
    validate_error,
    validate_success,
)

OPS = TEST_USERS["operations_director_headers"]


# ---------------------------------------------------------------------------
# Projected-dose boundary (Difficulty: projected_dose_exactly_at_limit_allowed)
# ---------------------------------------------------------------------------

def test_projected_dose_exactly_at_limit_allowed(api):
    """PRD §3.3: "And the prospective dose gate runs: `projected_dose_msv` is
    computed as the sum of the technologist's dose records dated on the target
    day's `service_date` plus the sum of `estimated_dose_msv` over the target
    day's appointments still in `REQUESTED`, `CONFIRMED`, `CHECKED_IN`, or
    `SCANNING`; if that projection is strictly greater than the 5.0 mSv daily
    technologist limit, the assignment is rejected with
    `ERR_DOSE_LIMIT_EXCEEDED` — a projection landing exactly on the limit is
    allowed."

    Design: Difficulty/boundary_precision_check/projected_dose_exactly_at_limit_allowed
    """
    bundle = setup_bookable_day(billing_model="PER_SCAN")
    day = bundle["site_day"]
    # Two appointments estimated 2.5 each: projected = 0 recorded + 5.0 estimated.
    book_appointment(day["id"], bundle["facility"]["id"], "P-001", estimated_dose_msv=2.5)
    book_appointment(
        day["id"], bundle["facility"]["id"], "P-002",
        scheduled_start="09:40", estimated_dose_msv=2.5,
    )
    tech = create_technologist()

    staffing = assign_staffing(day["id"], tech["id"])
    assert staffing["status"] == "ASSIGNED"
    assert staffing["projected_dose_msv"] == 5.0, (
        f"Projected dose exactly at the 5.0 limit must be allowed and stored; "
        f"got {staffing['projected_dose_msv']}"
    )


def test_projected_dose_above_limit_rejected(api):
    """PRD §3.3: "And the prospective dose gate runs: `projected_dose_msv` is
    computed as the sum of the technologist's dose records dated on the target
    day's `service_date` plus the sum of `estimated_dose_msv` over the target
    day's appointments still in `REQUESTED`, `CONFIRMED`, `CHECKED_IN`, or
    `SCANNING`; if that projection is strictly greater than the 5.0 mSv daily
    technologist limit, the assignment is rejected with
    `ERR_DOSE_LIMIT_EXCEEDED` — a projection landing exactly on the limit is
    allowed."

    Design: Difficulty/boundary_precision_check/projected_dose_exactly_at_limit_allowed
    """
    bundle = setup_bookable_day(billing_model="PER_SCAN")
    day = bundle["site_day"]
    # Two appointments estimated 2.6 each: projected = 5.2 > 5.0.
    book_appointment(day["id"], bundle["facility"]["id"], "P-003", estimated_dose_msv=2.6)
    book_appointment(
        day["id"], bundle["facility"]["id"], "P-004",
        scheduled_start="09:40", estimated_dose_msv=2.6,
    )
    tech = create_technologist()

    resp = api.create_staffing_assignment(
        create_staffing_assignment_payload(day["id"], tech["id"]), OPS
    )
    validate_error(resp, ApiErrorId.ERR_DOSE_LIMIT_EXCEEDED)


# ---------------------------------------------------------------------------
# Prospective vs retrospective dose (Difficulty: dual variant)
# ---------------------------------------------------------------------------

def test_prospective_projection_counts_estimates(api):
    """PRD §3.3: "And the prospective dose gate runs: `projected_dose_msv` is
    computed as the sum of the technologist's dose records dated on the target
    day's `service_date` plus the sum of `estimated_dose_msv` over the target
    day's appointments still in `REQUESTED`, `CONFIRMED`, `CHECKED_IN`, or
    `SCANNING`; if that projection is strictly greater than the 5.0 mSv daily
    technologist limit, the assignment is rejected with
    `ERR_DOSE_LIMIT_EXCEEDED` — a projection landing exactly on the limit is
    allowed."

    Design: Difficulty/dual_variant_calc/technologist_prospective_vs_retrospective_dose
    """
    bundle = setup_bookable_day(billing_model="PER_SCAN")
    day = bundle["site_day"]
    # Appointments booked BEFORE staffing so the projection sees the estimates.
    book_appointment(day["id"], bundle["facility"]["id"], "P-001", estimated_dose_msv=2.0)
    book_appointment(
        day["id"], bundle["facility"]["id"], "P-002",
        scheduled_start="09:40", estimated_dose_msv=2.0,
    )
    tech = create_technologist()

    staffing = assign_staffing(day["id"], tech["id"])
    assert staffing["projected_dose_msv"] == 4.0, (
        f"Prospective variant must be 0 recorded + 2.0 + 2.0 = 4.0, "
        f"got {staffing['projected_dose_msv']}"
    )


def test_retrospective_dose_uses_records_only(api):
    """PRD §3.3: "Two computed exposure fields ride on the record:
    `current_day_dose_msv`, the sum of that technologist's recorded doses on
    appointments whose site day's `service_date` equals the logical clock date,
    and `monthly_dose_msv`, the same sum over the logical clock's calendar
    month. Both start at zero and are recomputed as dose records arrive (§3.7)."

    Design: Difficulty/dual_variant_calc/technologist_prospective_vs_retrospective_dose
    """
    bundle = setup_bookable_day(billing_model="PER_SCAN")
    day = bundle["site_day"]
    ap1 = book_appointment(day["id"], bundle["facility"]["id"], "P-001", estimated_dose_msv=2.0)
    ap2 = book_appointment(
        day["id"], bundle["facility"]["id"], "P-002",
        scheduled_start="09:40", estimated_dose_msv=2.0,
    )
    tech = create_technologist()
    staffing = assign_staffing(day["id"], tech["id"])
    assert staffing["projected_dose_msv"] == 4.0  # prospective variant

    drive_day_to_in_service(bundle, technologist=tech, staffing=staffing)
    set_clock("2026-08-04T10:00:00Z")
    complete_appointment_flow(bundle, ap1)
    post_dose_record(ap1["id"], tech["id"], 1.5)
    complete_appointment_flow(bundle, ap2)
    post_dose_record(ap2["id"], tech["id"], 1.5)

    data = validate_success(api.get_technologist(tech["id"], OPS))
    assert data["current_day_dose_msv"] == 3.0, (
        f"Retrospective variant must be 1.5 + 1.5 = 3.0, got {data['current_day_dose_msv']}"
    )
    # The two variants diverge over the same appointment set: 4.0 vs 3.0.
    assert data["current_day_dose_msv"] != staffing["projected_dose_msv"]


# ---------------------------------------------------------------------------
# Priority pair: dose gate (safety) beats cert mismatch (referential)
# ---------------------------------------------------------------------------

def _setup_mri_day_with_appointments(api, estimate=1.1):
    """MRI facility + MRI unit + PER_SCAN contract + plan + day 2026-08-04 with
    two MRI_BRAIN appointments at the given estimate."""
    set_clock()
    facility_b = create_facility(
        name="Imaging Center B", address="9 B Rd", supported_modalities=["MRI"],
        pad_amps_available=200,
    )
    unit_mr = create_unit(unit_code="MIU-MR", modality="MRI", power_required_amps=120)
    create_accreditation(unit_mr["id"], modality="MRI")
    contract_b = create_contract(facility_b["id"], billing_model="PER_SCAN")
    plan_mr = create_route_plan(unit_mr["id"], week_start_date="2026-08-03")
    day_b = add_site_day(plan_mr["id"], facility_b["id"], contract_b["id"], "2026-08-04")
    coord_b = make_facility_coordinator_headers(facility_b["id"])
    for ref, start in (("P-101", "10:00"), ("P-102", "11:00")):
        get_success_data(
            api.create_appointment(
                create_appointment_payload(
                    day_b["id"], ref, exam_type="MRI_BRAIN", scheduled_start=start,
                    duration_minutes=45, estimated_dose_msv=estimate,
                ),
                coord_b,
            )
        )
    return day_b


def test_dose_limit_and_cert_mismatch_safety_wins(api):
    """PRD §2.8: "Every request is validated against a fixed priority ladder,
    and a failure at any rung stops evaluation so that earlier errors mask
    later ones."
    PRD §2.8: "6. Radiation and staffing safety: the projected-dose gate and
    the CT/PET-only dose-record rule."
    PRD §2.8: "9. Credential linkage: technologist certifications, exam-type
    modality prefixes, facility modality support, and contract-facility
    agreement."

    Design: Difficulty/priority_pair_validation_conflict/dose_limit_and_cert_mismatch_safety_beats_referential
    """
    # Day A (CT): the technologist accrues 1.5 + 1.5 = 3.0 mSv of recorded dose
    # on service_date 2026-08-04.
    bundle = setup_in_service_day(billing_model="PER_SCAN", service_date="2026-08-04")
    tech = bundle["technologist"]  # CT certs only
    ap1 = book_appointment(
        bundle["site_day"]["id"], bundle["facility"]["id"], "P-001", estimated_dose_msv=1.5
    )
    ap2 = book_appointment(
        bundle["site_day"]["id"], bundle["facility"]["id"], "P-002",
        scheduled_start="09:40", estimated_dose_msv=1.5,
    )
    complete_appointment_flow(bundle, ap1)
    post_dose_record(ap1["id"], tech["id"], 1.5)
    complete_appointment_flow(bundle, ap2)
    post_dose_record(ap2["id"], tech["id"], 1.5)
    get_success_data(api.complete_site_day(bundle["site_day"]["id"], OPS))  # staffing released

    # Day B (MRI) on the SAME service_date carries 1.1 + 1.1 of estimates:
    # projected = 3.0 + 2.2 = 5.2 > 5.0 AND the CT-only cert mismatches.
    day_b = _setup_mri_day_with_appointments(api, estimate=1.1)

    resp = api.create_staffing_assignment(
        create_staffing_assignment_payload(day_b["id"], tech["id"]), OPS
    )
    validate_error(resp, ApiErrorId.ERR_DOSE_LIMIT_EXCEEDED)


def test_cert_mismatch_alone_rejected(api):
    """PRD §3.3: "The technologist's `modality_certs` must contain the day's
    unit modality, else `ERR_MODALITY_CERT_MISMATCH`."

    Design: Difficulty/priority_pair_validation_conflict/dose_limit_and_cert_mismatch_safety_beats_referential
    """
    # Control: a CT-only technologist with NO dose history breaches only the
    # credential gate (projection 0 + 1.1 + 1.1 = 2.2 <= 5.0), so the
    # referential error surfaces.
    day_b = _setup_mri_day_with_appointments(api, estimate=1.1)
    tech = create_technologist()  # CT certs only

    resp = api.create_staffing_assignment(
        create_staffing_assignment_payload(day_b["id"], tech["id"]), OPS
    )
    validate_error(resp, ApiErrorId.ERR_MODALITY_CERT_MISMATCH)


# ---------------------------------------------------------------------------
# Drive time and date-conflict gates
# ---------------------------------------------------------------------------

def test_drive_time_above_technologist_max_rejected(api):
    """PRD §3.3: "The `estimated_drive_minutes` must not exceed the
    technologist's `max_daily_drive_minutes`, else `ERR_DRIVE_TIME_EXCEEDED`."

    Design: Corner/validations/drive_time_above_technologist_max_rejected
    """
    bundle = setup_bookable_day()
    tech = create_technologist()  # max_daily_drive_minutes 240
    resp = api.create_staffing_assignment(
        create_staffing_assignment_payload(
            bundle["site_day"]["id"], tech["id"], estimated_drive_minutes=300
        ),
        OPS,
    )
    validate_error(resp, ApiErrorId.ERR_DRIVE_TIME_EXCEEDED)


def test_staffing_same_date_conflict_rejected(api):
    """PRD §3.3: "The technologist must hold no other `ASSIGNED` staffing on
    the same `service_date`, else `ERR_STAFFING_DATE_CONFLICT`."

    Design: Corner/validations/staffing_same_date_conflict_rejected
    """
    bundle = setup_plan_context_published_pair()
    tech = create_technologist()
    assign_staffing(bundle["day_x"]["id"], tech["id"])

    resp = api.create_staffing_assignment(
        create_staffing_assignment_payload(bundle["day_y"]["id"], tech["id"]), OPS
    )
    validate_error(resp, ApiErrorId.ERR_STAFFING_DATE_CONFLICT)


def setup_plan_context_published_pair():
    """Two CT units, each with a plan for the same week and a site day on the
    same service_date — the setting for the single-day staffing rule."""
    set_clock()
    facility = create_facility()
    unit1 = create_unit(unit_code="MIU-01")
    unit2 = create_unit(unit_code="MIU-02")
    create_accreditation(unit1["id"], modality="CT")
    create_accreditation(unit2["id"], modality="CT")
    contract = create_contract(facility["id"])
    plan1 = create_route_plan(unit1["id"], week_start_date="2026-08-03")
    plan2 = create_route_plan(unit2["id"], week_start_date="2026-08-03")
    day_x = add_site_day(plan1["id"], facility["id"], contract["id"], "2026-08-04")
    day_y = add_site_day(plan2["id"], facility["id"], contract["id"], "2026-08-04")
    return {"facility": facility, "contract": contract, "day_x": day_x, "day_y": day_y}


# ---------------------------------------------------------------------------
# Dose records: DRL flag, MRI applicability, identity, aggregates, immutability
# ---------------------------------------------------------------------------

def test_drl_flag_strictly_greater_than_reference(api):
    """PRD §3.7: "Each record is checked against the diagnostic reference level
    for its exam type, and `drl_exceeded` is set true exactly when `dose_msv`
    is strictly greater than the reference level — 2.0 mSv for `CT_HEAD`, 7.0
    mSv for `CT_CHEST`, 10.0 mSv for `PET_ONCO`; equality does not flag, the
    record is accepted regardless, and the flag is advisory for compliance
    audit."

    Design: Corner/calculations/drl_flag_strictly_greater_than_reference
    """
    bundle = setup_in_service_day(billing_model="PER_SCAN")
    tech = bundle["technologist"]
    ap1 = book_and_complete_appointment(bundle, "P-001", scheduled_start="09:00")
    ap2 = book_and_complete_appointment(bundle, "P-002", scheduled_start="09:40")

    rec1 = post_dose_record(ap1["id"], tech["id"], 2.0)
    assert_dose_record(rec1)
    assert rec1["drl_exceeded"] is False, (
        "dose 2.0 == DRL 2.0 must NOT flag (strictly-greater rule)"
    )

    rec2 = post_dose_record(ap2["id"], tech["id"], 2.1)
    assert rec2["drl_exceeded"] is True, "dose 2.1 > DRL 2.0 must flag"


def test_dose_record_on_mri_exam_rejected(api):
    """PRD §3.7: "Dose records exist only for ionizing modalities — `CT_HEAD`,
    `CT_CHEST`, and `PET_ONCO`; an MRI exam emits no ionizing dose and posting
    one is rejected with `ERR_DOSE_NOT_APPLICABLE`."

    Design: Corner/errors/dose_record_on_mri_exam_rejected
    """
    bundle = setup_in_service_day(billing_model="PER_SCAN", modality="MRI")
    appt = book_and_complete_appointment(
        bundle, "P-001", exam_type="MRI_BRAIN", duration_minutes=45,
        estimated_dose_msv=0.0,
    )
    tech = bundle["technologist"]
    resp = api.create_dose_record(
        create_dose_record_payload(appt["id"], tech["id"], 0.5),
        make_technologist_headers(tech["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_DOSE_NOT_APPLICABLE)


def test_dose_record_technologist_identity_mismatch(api):
    """PRD §3.7: "Three identity and applicability rules bind: the appointment
    must be `COMPLETED` (`ERR_INVALID_STATE` otherwise); the payload's
    `technologist_id` must equal the caller's `X-User-ID`
    (`ERR_TECHNOLOGIST_IDENTITY_MISMATCH`); and the acting technologist must
    hold an `ASSIGNED` staffing assignment on that day
    (`ERR_TECHNOLOGIST_NOT_STAFFED`)."

    Design: Corner/rbac/dose_record_technologist_identity_mismatch
    """
    bundle = setup_in_service_day(billing_model="PER_SCAN")
    tech1 = bundle["technologist"]
    tech2 = create_technologist(full_name="Tom Tech")
    appt = book_and_complete_appointment(bundle, "P-001")

    resp = api.create_dose_record(
        create_dose_record_payload(appt["id"], tech2["id"], 1.0),
        make_technologist_headers(tech1["id"]),  # caller is tech1, payload tech2
    )
    validate_error(resp, ApiErrorId.ERR_TECHNOLOGIST_IDENTITY_MISMATCH)


def test_appointment_actual_dose_reconciles_after_record(api):
    """PRD §3.5: "The appointment's `actual_dose_msv` starts at zero and
    becomes the sum of its dose records once technologists post them (§3.7)."

    Design: Corner/cross_cutting_layers/appointment_actual_dose_reconciles_after_record
    """
    bundle = setup_in_service_day(billing_model="PER_SCAN")
    tech = bundle["technologist"]
    appt = book_and_complete_appointment(bundle, "P-001")
    assert appt["actual_dose_msv"] == 0

    post_dose_record(appt["id"], tech["id"], 1.8)
    after = validate_success(api.get_appointment(appt["id"], OPS))
    assert after["actual_dose_msv"] == 1.8, (
        f"actual_dose_msv must reconcile to 1.8 immediately, got {after['actual_dose_msv']}"
    )


def test_dose_record_immutable_no_version_field(api):
    """PRD §2.5: "The single exception is the `RadiationDoseRecord`, which is
    immutable once written: it carries `id` and `created_at` only, and both
    `updated_at` and `version` are absent from it."
    PRD §3.7: "Each record is checked against the diagnostic reference level
    for its exam type, and `drl_exceeded` is set true exactly when `dose_msv`
    is strictly greater than the reference level — 2.0 mSv for `CT_HEAD`, 7.0
    mSv for `CT_CHEST`, 10.0 mSv for `PET_ONCO`; equality does not flag".

    Design: Corner/entities/dose_record_immutable_no_version_field
    """
    bundle = setup_in_service_day(billing_model="PER_SCAN")
    tech = bundle["technologist"]
    appt = book_and_complete_appointment(bundle, "P-001")

    rec = post_dose_record(appt["id"], tech["id"], 1.8)
    assert_dose_record(rec)  # asserts id + created_at present, version/updated_at absent
    assert rec["drl_exceeded"] is False, "1.8 <= DRL 2.0 must not flag"
