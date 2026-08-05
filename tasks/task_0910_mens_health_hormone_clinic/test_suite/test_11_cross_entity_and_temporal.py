"""Cross-entity state preconditions and resource temporal-overlap geometry."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS,
    create_clinician, create_patient, create_membership_plan, create_membership,
    create_draw_station, create_reviewed_panel, create_refill, get_prescription, get_plan,
    setup_active_plan, setup_plan_with_prescription,
    create_lab_panel_payload, result_lab_panel_payload, create_treatment_plan_payload,
    create_telehealth_visit_payload, create_lab_draw_appointment_payload,
    create_refill_order_payload,
    make_clinician_headers,
)
from test_helpers import api_client

ADMIN = TEST_USERS["clinic_admin_headers"]


# --------------------------------------------------------------- baseline-reviewed dependency
def test_activate_with_resulted_baseline_rejected(api):
    """PRD §3.5: "the referenced baseline panel must be in the `REVIEWED` state, or
    activation fails with `ERR_BASELINE_NOT_REVIEWED`".

    Design: Difficulty/cross_entity_state_dependency/plan_activate_requires_reviewed_baseline
    """
    clinician = create_clinician()
    patient = create_patient()
    plan_cfg = create_membership_plan()
    create_membership(patient["id"], plan_cfg["id"], activate=True)
    cln = make_clinician_headers(clinician["id"])
    panel = get_success_data(api.create_lab_panel(create_lab_panel_payload(patient["id"], clinician["id"]), cln))
    get_success_data(api.draw_lab_panel(panel["id"], cln))
    get_success_data(api.result_lab_panel(panel["id"], result_lab_panel_payload(), cln))  # RESULTED, not REVIEWED
    plan = get_success_data(api.create_treatment_plan(
        create_treatment_plan_payload(patient["id"], clinician["id"], panel["id"]), cln
    ))
    validate_error(api.activate_treatment_plan(plan["id"], cln), ApiErrorId.ERR_BASELINE_NOT_REVIEWED, 409)
    assert get_plan(plan["id"])["status"] == "DRAFT"


def test_activate_with_reviewed_baseline_succeeds(api):
    """PRD §3.5: "Activation moves a plan from `DRAFT` to `ACTIVE`".
    PRD §3.5: "On success the plan's `current_dose_mg` is set to its `starting_dose_mg`."

    Design: Difficulty/cross_entity_state_dependency/plan_activate_requires_reviewed_baseline
    """
    ctx = setup_active_plan(activate_plan=False, starting_dose_mg=100)
    data = validate_success(api.activate_treatment_plan(ctx["plan_id"], ctx["clinician_headers"]), 200)
    assert data["status"] == "ACTIVE"
    assert data["current_dose_mg"] == 100


# --------------------------------------------------------------- issued-prescription dependency
def test_refill_against_suspended_prescription_rejected(api):
    """PRD §3.6: "the referenced prescription must not be `SUSPENDED` or `REVOKED` — an
    `EXHAUSTED` prescription passes this particular check — or the request is rejected
    with `ERR_PRESCRIPTION_SUSPENDED`".

    Design: Difficulty/cross_entity_state_dependency/refill_requires_issued_prescription
    """
    ctx = setup_plan_with_prescription()
    create_reviewed_panel(
        ctx["patient_id"], ctx["clinician_id"], panel_type="MONITORING",
        results={"total_testosterone_ng_dl": 500, "psa_ng_ml": 1.5, "hematocrit_pct": 56.0, "drawn_at": "2026-04-28T09:00:00Z"},
    )
    assert get_prescription(ctx["rx_id"])["status"] == "SUSPENDED"
    rx_version = get_prescription(ctx["rx_id"])["version"]
    payload = create_refill_order_payload(ctx["rx_id"], ctx["membership_id"], ctx["patient_id"], rx_version)
    validate_error(api.create_refill_order(payload, ADMIN), ApiErrorId.ERR_PRESCRIPTION_SUSPENDED, 409)


def test_refill_against_issued_prescription_succeeds(api):
    """PRD §3.6: "A successful create computes the provisional charge, stores it in
    `provisional_charge_cents`, sets the order to `PENDING_REVIEW`, and increments the
    prescription's `version` by one."

    Design: Difficulty/cross_entity_state_dependency/refill_requires_issued_prescription
    """
    ctx = setup_plan_with_prescription()
    refill = create_refill(ctx)
    assert refill["status"] == "PENDING_REVIEW"


# --------------------------------------------------------------- telehealth buffer geometry
def test_telehealth_within_buffer_double_booked(api):
    """PRD §3.4: "if any other `SCHEDULED` visit for the same clinician has an interval
    that overlaps the requested one or sits within a fifteen-minute buffer of it — that
    is, the clear gap between the two intervals is strictly less than fifteen minutes —
    the booking is rejected with `ERR_CLINICIAN_DOUBLE_BOOKED`."

    Design: Difficulty/resource_temporal_overlap/telehealth_clinician_buffer_overlap
    """
    clinician = create_clinician()
    patient = create_patient()
    get_success_data(api.create_telehealth_visit(
        create_telehealth_visit_payload(patient["id"], clinician["id"], "2026-05-02T10:00:00Z", "2026-05-02T10:30:00Z"), ADMIN
    ))
    payload = create_telehealth_visit_payload(patient["id"], clinician["id"], "2026-05-02T10:40:00Z", "2026-05-02T11:00:00Z")
    validate_error(api.create_telehealth_visit(payload, ADMIN), ApiErrorId.ERR_CLINICIAN_DOUBLE_BOOKED, 409)


def test_telehealth_exactly_fifteen_minute_gap_allowed(api):
    """PRD §3.4: "A gap of exactly fifteen minutes or more is allowed."

    Design: Difficulty/resource_temporal_overlap/telehealth_clinician_buffer_overlap
    """
    clinician = create_clinician()
    patient = create_patient()
    get_success_data(api.create_telehealth_visit(
        create_telehealth_visit_payload(patient["id"], clinician["id"], "2026-05-02T10:00:00Z", "2026-05-02T10:30:00Z"), ADMIN
    ))
    payload = create_telehealth_visit_payload(patient["id"], clinician["id"], "2026-05-02T10:45:00Z", "2026-05-02T11:15:00Z")
    data = validate_success(api.create_telehealth_visit(payload, ADMIN), 201)
    assert data["status"] == "SCHEDULED"


# --------------------------------------------------------------- draw-station capacity geometry
def _patient_with_credits():
    patient = create_patient()
    plan = create_membership_plan(included_lab_draw_credits=4)
    create_membership(patient["id"], plan["id"], activate=True)
    return patient


def test_lab_draw_overlap_at_capacity_rejected(api):
    """PRD §3.4: "counting the existing `SCHEDULED` appointments at that station whose
    half-open intervals overlap the requested interval, the booking is rejected with
    `ERR_DRAW_STATION_AT_CAPACITY` when that count is at or above the station's
    `concurrent_capacity`."

    Design: Difficulty/resource_temporal_overlap/lab_draw_station_capacity_overlap
    """
    patient = _patient_with_credits()
    station = create_draw_station(name="Station 1", concurrent_capacity=1)
    get_success_data(api.create_lab_draw_appointment(
        create_lab_draw_appointment_payload(patient["id"], station["id"], "2026-05-03T10:00:00Z", "2026-05-03T10:30:00Z"), ADMIN
    ))
    payload = create_lab_draw_appointment_payload(patient["id"], station["id"], "2026-05-03T10:15:00Z", "2026-05-03T10:45:00Z")
    validate_error(api.create_lab_draw_appointment(payload, ADMIN), ApiErrorId.ERR_DRAW_STATION_AT_CAPACITY, 409)


def test_lab_draw_touching_interval_allowed(api):
    """PRD §3.4: "a half-open interval defined by `start_at` (inclusive) and `end_at`
    (exclusive)."
    PRD §3.4: "counting the existing `SCHEDULED` appointments at that station whose
    half-open intervals overlap the requested interval, the booking is rejected with
    `ERR_DRAW_STATION_AT_CAPACITY` when that count is at or above the station's
    `concurrent_capacity`."

    Design: Difficulty/resource_temporal_overlap/lab_draw_station_capacity_overlap
    """
    patient = _patient_with_credits()
    station = create_draw_station(name="Station 1", concurrent_capacity=1)
    get_success_data(api.create_lab_draw_appointment(
        create_lab_draw_appointment_payload(patient["id"], station["id"], "2026-05-03T10:00:00Z", "2026-05-03T10:30:00Z"), ADMIN
    ))
    # Adjacent interval starts exactly when the first ends: half-open => no overlap.
    payload = create_lab_draw_appointment_payload(patient["id"], station["id"], "2026-05-03T10:30:00Z", "2026-05-03T11:00:00Z")
    data = validate_success(api.create_lab_draw_appointment(payload, ADMIN), 201)
    assert data["status"] == "SCHEDULED"
