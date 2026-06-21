"""Monitoring appointments (cyclic lifecycle + half-open room overlap), the
medication calendar overlap rule, consent-form publish/supersede cascade, and
the settle-stale-cycle OCC conflict.
"""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    make_patient_headers,
)
import test_helpers.factories as f
import test_helpers.fixtures as fx

ADMIN = TEST_USERS["clinic_admin_headers"]
NURSE = TEST_USERS["nurse_headers"]
EMBRYO = TEST_USERS["embryologist_headers"]
BILLING = TEST_USERS["billing_specialist_headers"]


# ===========================================================================
# Queue A — non_linear_state_machine / appointment_cyclic_confirmed_rescheduled_confirmed
# ===========================================================================
def test_appointment_reschedule_then_confirm_cycle():
    """PRD 3.4: "From `RESCHEDULED`, a `Nurse` **confirms** the appointment back to
    `CONFIRMED`; confirmation requires the appointment to be `RESCHEDULED`
    (`ERR_APPT_BAD_STATE`)."

    Design: Difficulty/non_linear_state_machine/appointment_cyclic_confirmed_rescheduled_confirmed
    """
    cid = fx.create_clinic(name="Loop Clinic", room_concurrency_limit=5)["id"]
    fx.set_clock(cid, "2026-06-01T00:00:00.000Z")
    pat = fx.create_patient(cid)["id"]
    cyc = fx.create_cycle(cid, pat)["id"]
    appt = get_success_data(api_client.create_appointment(
        cid, f.create_appointment_payload(cyc, "2026-06-02T09:00:00.000Z", "2026-06-02T09:30:00.000Z",
                                           appointment_type="ULTRASOUND"), NURSE))["id"]
    get_success_data(api_client.reschedule_appointment(
        cid, appt, {"start_utc": "2026-06-03T09:00:00.000Z", "end_utc": "2026-06-03T09:30:00.000Z"}, NURSE))
    res = validate_success(api_client.confirm_appointment(cid, appt, NURSE))
    assert res["status"] == "CONFIRMED"


def test_appointment_reschedule_updates_interval():
    """PRD 3.4: "A `Nurse` may **reschedule** a `CONFIRMED` or `RESCHEDULED` appointment
    to a new interval, moving it to `RESCHEDULED`; rescheduling requires the appointment
    to be in `CONFIRMED` or `RESCHEDULED` (`ERR_APPT_BAD_STATE`), updates its `start_utc`
    and `end_utc`..."

    Design: Difficulty/non_linear_state_machine/appointment_cyclic_confirmed_rescheduled_confirmed
    """
    cid = fx.create_clinic(name="Loop Clinic 2", room_concurrency_limit=5)["id"]
    fx.set_clock(cid, "2026-06-01T00:00:00.000Z")
    pat = fx.create_patient(cid)["id"]
    cyc = fx.create_cycle(cid, pat)["id"]
    appt = get_success_data(api_client.create_appointment(
        cid, f.create_appointment_payload(cyc, "2026-06-02T09:00:00.000Z", "2026-06-02T09:30:00.000Z",
                                           appointment_type="ULTRASOUND"), NURSE))["id"]
    get_success_data(api_client.reschedule_appointment(
        cid, appt, {"start_utc": "2026-06-03T09:00:00.000Z", "end_utc": "2026-06-03T09:30:00.000Z"}, NURSE))
    res = validate_success(api_client.confirm_appointment(cid, appt, NURSE))
    assert res["start_utc"] == "2026-06-03T09:00:00.000Z"


# ===========================================================================
# Queue A — resource_temporal_overlap / monitoring_room_halfopen_aggregate_capacity_conflict
# ===========================================================================
def _two_overlapping_appointments():
    cid = fx.create_clinic(name="Room Clinic", room_concurrency_limit=2)["id"]
    fx.set_clock(cid, "2026-06-01T00:00:00.000Z")
    pat = fx.create_patient(cid)["id"]
    cyc = fx.create_cycle(cid, pat)["id"]
    get_success_data(api_client.create_appointment(
        cid, f.create_appointment_payload(cyc, "2026-06-05T09:00:00.000Z", "2026-06-05T10:00:00.000Z",
                                           appointment_type="BLOODWORK", room_capacity_weight=1), NURSE))
    get_success_data(api_client.create_appointment(
        cid, f.create_appointment_payload(cyc, "2026-06-05T09:30:00.000Z", "2026-06-05T10:30:00.000Z",
                                           appointment_type="ULTRASOUND", room_capacity_weight=1), NURSE))
    return cid, cyc


def test_third_overlapping_appointment_exceeds_room_limit():
    """PRD 3.4: "the instantaneous sum of `room_capacity_weight` across appointments whose
    half-open intervals cover any given instant must never exceed the clinic's
    `room_concurrency_limit`; if admitting the new interval would push that instantaneous
    aggregate above the limit at any point, the request is rejected with
    `ERR_MONITORING_SLOT_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/monitoring_room_halfopen_aggregate_capacity_conflict
    """
    cid, cyc = _two_overlapping_appointments()
    resp = api_client.create_appointment(
        cid, f.create_appointment_payload(cyc, "2026-06-05T09:45:00.000Z", "2026-06-05T10:15:00.000Z",
                                          appointment_type="CONSULT", room_capacity_weight=1), NURSE)
    validate_error(resp, ApiErrorId.ERR_MONITORING_SLOT_CONFLICT.value)


def test_adjacent_appointment_at_boundary_allowed():
    """PRD 3.4: "Because the intervals are half-open, two appointments that merely abut
    — where the earlier one's `end_utc` exactly equals the later one's `start_utc` — do
    not overlap and may share the boundary instant freely."

    Design: Difficulty/resource_temporal_overlap/monitoring_room_halfopen_aggregate_capacity_conflict
    """
    cid, cyc = _two_overlapping_appointments()
    # Both existing appointments end by 10:30; an appointment starting exactly at 10:30
    # abuts and must be admitted even though the limit is 2.
    res = validate_success(api_client.create_appointment(
        cid, f.create_appointment_payload(cyc, "2026-06-05T10:30:00.000Z", "2026-06-05T11:00:00.000Z",
                                          appointment_type="CONSULT", room_capacity_weight=2), NURSE),
        expected_status=201)
    assert res["status"] == "CONFIRMED"


# ===========================================================================
# Queue A — resource_temporal_overlap / medication_closed_dayoffset_overlap_conflict
# ===========================================================================
def _stim_cycle_with_gonal_0_4():
    ctx = fx.setup_cycle_in_stim(name="Med Clinic", required_for=["CYCLE_START"])
    cid, cyc = ctx["clinic"]["id"], ctx["cycle"]["id"]
    get_success_data(api_client.create_medication(
        cid, f.create_medication_payload(cyc, drug_name="Gonal-F", start_day_offset=0,
                                          end_day_offset=4, daily_dose_units=300, unit_price_cents=100), NURSE))
    return cid, cyc


def test_overlapping_same_drug_interval_rejected():
    """PRD 3.3: "A new order's day-offset interval is treated as a closed inclusive
    interval from `start_day_offset` through `end_day_offset`, and it must not intersect
    the closed interval of any existing order for the **same** `drug_name` on the same
    cycle that is currently `SCHEDULED` or `ADMINISTERED`. ... ranges that share even a
    single offset (including equal endpoints) do overlap. A violation is rejected with
    `ERR_MEDICATION_SCHEDULE_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/medication_closed_dayoffset_overlap_conflict
    """
    cid, cyc = _stim_cycle_with_gonal_0_4()
    resp = api_client.create_medication(
        cid, f.create_medication_payload(cyc, drug_name="Gonal-F", start_day_offset=3,
                                         end_day_offset=6, daily_dose_units=150, unit_price_cents=100), NURSE)
    validate_error(resp, ApiErrorId.ERR_MEDICATION_SCHEDULE_OVERLAP.value)


def test_adjacent_same_drug_interval_allowed():
    """PRD 3.3: "Closed-interval semantics govern the boundaries: two orders whose ranges
    merely abut — where the earlier order's end offset plus one equals the later order's
    start offset — do not overlap and are both allowed..."

    Design: Difficulty/resource_temporal_overlap/medication_closed_dayoffset_overlap_conflict
    """
    cid, cyc = _stim_cycle_with_gonal_0_4()
    res = validate_success(api_client.create_medication(
        cid, f.create_medication_payload(cyc, drug_name="Gonal-F", start_day_offset=5,
                                         end_day_offset=7, daily_dose_units=150, unit_price_cents=100), NURSE),
        expected_status=201)
    assert res["status"] == "SCHEDULED"


# ===========================================================================
# Queue A — transitive_cascade / publish_supersede_depth2_form_consent_stale
# ===========================================================================
def _published_v1_signed_then_v2_draft():
    cid = fx.create_clinic(name="Consent Clinic")["id"]
    pat = fx.create_patient(cid)["id"]
    v1 = get_success_data(api_client.create_consent_form(
        cid, f.create_consent_form_payload(version_label="v1", required_for=["CYCLE_START"]), ADMIN))["id"]
    get_success_data(api_client.publish_consent_form(cid, v1, ADMIN))
    consent = get_success_data(api_client.create_patient_consent(
        cid, f.create_patient_consent_payload(pat, v1), make_patient_headers(pat)))["id"]
    v2 = get_success_data(api_client.create_consent_form(
        cid, f.create_consent_form_payload(version_label="v2", required_for=["CYCLE_START"],
                                            supersedes_form_id=v1), ADMIN))["id"]
    return cid, v1, v2, consent


def test_publish_supersede_marks_target_superseded():
    """PRD 3.5: "Publishing with a supersede target triggers a two-hop cascade: the
    named target form moves `PUBLISHED → SUPERSEDED` (a first-level cascade)..."

    Design: Difficulty/transitive_cascade/publish_supersede_depth2_form_consent_stale
    """
    cid, v1, v2, consent = _published_v1_signed_then_v2_draft()
    res = validate_success(api_client.publish_consent_form(cid, v2, ADMIN))
    assert res["status"] == "PUBLISHED"
    assert get_success_data(api_client.get_consent_form(cid, v1, ADMIN))["status"] == "SUPERSEDED"


def test_publish_supersede_cascades_consent_to_stale():
    """PRD 3.5: "and then every active patient consent that was pinned to that
    now-superseded form moves `ACTIVE → STALE` (a second-level cascade)."

    Design: Difficulty/transitive_cascade/publish_supersede_depth2_form_consent_stale
    """
    cid, v1, v2, consent = _published_v1_signed_then_v2_draft()
    validate_success(api_client.publish_consent_form(cid, v2, ADMIN))
    assert get_success_data(api_client.get_patient_consent(cid, consent, ADMIN))["status"] == "STALE"


# ===========================================================================
# Queue B — validations / sign_unpublished_consent_form_rejected
# ===========================================================================
def test_sign_unpublished_consent_form_rejected():
    """PRD 3.5: "The form must be `PUBLISHED` and non-stale at signing; attempting to
    sign a `DRAFT` or `SUPERSEDED` form is rejected with `ERR_CONSENT_FORM_NOT_PUBLISHED`."

    Design: Corner/validations/sign_unpublished_consent_form_rejected
    """
    cid = fx.create_clinic(name="Val Clinic A")["id"]
    pat = fx.create_patient(cid)["id"]
    form = get_success_data(api_client.create_consent_form(
        cid, f.create_consent_form_payload(required_for=["CYCLE_START"]), ADMIN))["id"]
    resp = api_client.create_patient_consent(
        cid, f.create_patient_consent_payload(pat, form), make_patient_headers(pat))
    validate_error(resp, ApiErrorId.ERR_CONSENT_FORM_NOT_PUBLISHED.value)


# ===========================================================================
# Queue B — validations / appointment_in_past_rejected
# ===========================================================================
def test_appointment_in_past_rejected():
    """PRD 3.4: "the interval must be valid: `end_utc` must be strictly after
    `start_utc`, and `start_utc` must be at or after the clinic's `current_clock_utc`;
    either violation is rejected with `ERR_APPOINTMENT_IN_PAST`."

    Design: Corner/validations/appointment_in_past_rejected
    """
    cid = fx.create_clinic(name="Past Clinic", room_concurrency_limit=3)["id"]
    fx.set_clock(cid, "2026-06-10T00:00:00.000Z")
    pat = fx.create_patient(cid)["id"]
    cyc = fx.create_cycle(cid, pat)["id"]
    resp = api_client.create_appointment(
        cid, f.create_appointment_payload(cyc, "2026-06-01T09:00:00.000Z", "2026-06-01T09:30:00.000Z",
                                          appointment_type="BLOODWORK"), NURSE)
    validate_error(resp, ApiErrorId.ERR_APPOINTMENT_IN_PAST.value)


# ===========================================================================
# Queue B — cross_cutting_complexity_layers / occ_settle_stale_cycle_version_conflict
# ===========================================================================
def test_settle_with_stale_cycle_version_rejected():
    """PRD 2.7: "The settle request must carry `expected_cycle_version`, a non-optional
    field holding the client's last observed `version` of the target `TreatmentCycle`.
    If that value does not equal the cycle's current `version`, the settlement is
    rejected with `ERR_STALE_CYCLE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_settle_stale_cycle_version_conflict
    """
    cid = fx.create_clinic(name="OCC Cyc Clinic")["id"]
    pkg = fx.create_package(cid, name="OCC Pkg", base_price_cents=100000, coverage_pct=0.5,
                            lifetime_coverage_cap_cents=100000)["id"]
    pat = fx.create_patient(cid, insurance_package_id=pkg)["id"]
    fx.setup_patient_with_consent(cid, pat, required_for=["CYCLE_START"])
    cyc = fx.create_cycle(cid, pat)["id"]
    get_success_data(api_client.start_stim(cid, cyc, NURSE))
    get_success_data(api_client.estimate_billing(cid, cyc, BILLING))
    stale_v = get_success_data(api_client.get_cycle(cid, cyc, BILLING))["version"]
    get_success_data(api_client.cancel_cycle(cid, cyc, {"expected_cycle_version": stale_v}, NURSE))  # bumps version
    resp = api_client.settle_billing(cid, cyc, {"expected_cycle_version": stale_v}, BILLING)
    validate_error(resp, ApiErrorId.ERR_STALE_CYCLE_VERSION.value)
