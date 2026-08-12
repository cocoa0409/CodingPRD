"""Composite setup helpers for the Hospitalist Census API.

Every fixture builds its preconditions from scratch using only PRD-declared
endpoints. Fixtures use get_success_data() internally so setup failures
produce clear "Setup failed" errors instead of confusing assertion failures.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_hospitalist_payload,
    create_patient_payload,
    create_shift_payload,
    create_discharge_order_payload,
    create_handoff_payload,
    create_consult_request_payload,
    create_encounter_payload,
    create_productivity_report_payload,
    create_coverage_window_payload,
)
from .test_users import (
    TEST_USERS,
    make_hospitalist_headers,
)

ADMIN = TEST_USERS["group_admin_headers"]
SPECIALIST = TEST_USERS["specialist_headers"]

CLOCK_DEFAULT = "2026-05-01T09:00:00Z"


# ---------------------------------------------------------------------------
# Primitive builders
# ---------------------------------------------------------------------------

def set_clock(to_iso8601=CLOCK_DEFAULT):
    """Move the logical clock."""
    resp = api_client.set_clock(to_iso8601, ADMIN)
    return get_success_data(resp)


def create_hospitalist(name="H", specialty="INTERNAL_MEDICINE", **overrides):
    payload = create_hospitalist_payload(full_name=name, specialty=specialty, **overrides)
    resp = api_client.create_hospitalist(payload, ADMIN)
    return get_success_data(resp)


def create_patient(mrn="M001", acuity="MEDIUM", admit_source="ED",
                   stay_type="INPATIENT", admitted_at="2026-05-01T08:00:00Z",
                   **overrides):
    payload = create_patient_payload(
        mrn=mrn, acuity=acuity, admit_source=admit_source,
        stay_type=stay_type, admitted_at=admitted_at, **overrides,
    )
    resp = api_client.create_patient(payload, ADMIN)
    return get_success_data(resp)


def create_shift(hospitalist_id, shift_type="DAY",
                 start_at="2026-05-01T06:00:00Z", end_at="2026-05-01T18:00:00Z",
                 activate=False):
    payload = create_shift_payload(
        hospitalist_id=hospitalist_id, shift_type=shift_type,
        start_at=start_at, end_at=end_at,
    )
    resp = api_client.create_shift(payload, ADMIN)
    shift = get_success_data(resp)
    if activate:
        resp = api_client.activate_shift(shift["id"], ADMIN)
        shift = get_success_data(resp)
    return shift


def admit_and_accept(patient_id):
    """Create an admission for the patient, then accept as the offered
    hospitalist. Returns (admission, assignment_id). Requires that the
    selector finds exactly one eligible hospitalist."""
    resp = api_client.create_admission({"patient_id": patient_id}, ADMIN)
    admission = get_success_data(resp)
    offered_to = admission.get("offered_to_hospitalist_id")
    if not offered_to:
        raise AssertionError(
            f"Setup failed: admission {admission['id']} stayed QUEUED "
            f"(selector pool empty); expected an OFFERED admission"
        )
    accept_resp = api_client.accept_admission(
        admission["id"], make_hospitalist_headers(offered_to)
    )
    accepted = get_success_data(accept_resp)
    return accepted, accepted.get("assignment_id")


def setup_hospitalist_with_active_shift(
    name="H One",
    specialty="INTERNAL_MEDICINE",
    max_census_cap=16,
    shift_type="DAY",
    shift_start="2026-05-01T06:00:00Z",
    shift_end="2026-05-01T18:00:00Z",
    clock=CLOCK_DEFAULT,
    employment_status=None,
    set_clock_first=True,
):
    """Create a hospitalist + an ACTIVE shift covering `clock`.

    Returns (hospitalist, shift). Order matters: the shift must exist and be
    ACTIVE *before* the clock is set into its coverage window for the
    selector to consider the hospitalist eligible.
    """
    h_overrides = {"max_census_cap": max_census_cap}
    if employment_status is not None:
        h_overrides["employment_status"] = employment_status
    h = create_hospitalist(name, specialty, **h_overrides)
    s = create_shift(h["id"], shift_type, shift_start, shift_end, activate=True)
    if set_clock_first and clock is not None:
        set_clock(clock)
    return h, s


def setup_assigned_patient(
    hosp_name="H One",
    hosp_specialty="INTERNAL_MEDICINE",
    hosp_cap=16,
    patient_mrn="M001",
    patient_acuity="MEDIUM",
    patient_admit_source="ED",
    patient_stay_type="INPATIENT",
    patient_admitted_at="2026-05-01T08:00:00Z",
    shift_start="2026-05-01T06:00:00Z",
    shift_end="2026-05-01T18:00:00Z",
    clock=CLOCK_DEFAULT,
):
    """Single hospitalist with ACTIVE shift + one patient admitted, offered,
    and accepted. Returns (hospitalist, shift, patient, admission, assignment_id).
    """
    h, s = setup_hospitalist_with_active_shift(
        name=hosp_name, specialty=hosp_specialty, max_census_cap=hosp_cap,
        shift_start=shift_start, shift_end=shift_end, clock=clock,
    )
    p = create_patient(
        mrn=patient_mrn, acuity=patient_acuity, admit_source=patient_admit_source,
        stay_type=patient_stay_type, admitted_at=patient_admitted_at,
    )
    admission, assignment_id = admit_and_accept(p["id"])
    return h, s, p, admission, assignment_id


def create_discharge_order_for(patient_id, ordering_hospitalist_id,
                               target_discharge_at="2026-05-02T15:00:00Z",
                               order=False):
    """Create (and optionally order) a discharge order for a patient."""
    payload = create_discharge_order_payload(target_discharge_at=target_discharge_at)
    resp = api_client.create_discharge_order(
        patient_id, payload, make_hospitalist_headers(ordering_hospitalist_id)
    )
    order_obj = get_success_data(resp)
    if order:
        resp = api_client.order_discharge_order(
            order_obj["id"], make_hospitalist_headers(ordering_hospitalist_id)
        )
        order_obj = get_success_data(resp)
    return order_obj


def create_consult_for(patient_id, requesting_hospitalist_id,
                       specialty="CARDIOLOGY", priority="ROUTINE",
                       reason="clinical question"):
    payload = create_consult_request_payload(
        specialty=specialty, priority=priority, reason=reason,
    )
    resp = api_client.create_consult_request(
        patient_id, payload, make_hospitalist_headers(requesting_hospitalist_id)
    )
    return get_success_data(resp)


def create_encounter_for(patient_id, hospitalist_id,
                         encounter_type="SUBSEQUENT_VISIT",
                         occurred_on="2026-05-04", wrvu_value=1.2):
    payload = create_encounter_payload(
        patient_id=patient_id, encounter_type=encounter_type,
        occurred_on=occurred_on, wrvu_value=wrvu_value,
    )
    resp = api_client.create_encounter(
        payload, make_hospitalist_headers(hospitalist_id)
    )
    return get_success_data(resp)


def create_handoff_for(shift_id, submitting_hospitalist_id,
                       receiving_hospitalist_id, patient_ids):
    payload = create_handoff_payload(
        receiving_hospitalist_id=receiving_hospitalist_id,
        patient_ids=patient_ids,
    )
    resp = api_client.create_handoff(
        shift_id, payload, make_hospitalist_headers(submitting_hospitalist_id)
    )
    return get_success_data(resp)


def generate_report(hospitalist_id, period_start="2026-05-01", period_end="2026-05-31"):
    payload = create_productivity_report_payload(
        hospitalist_id=hospitalist_id,
        period_start=period_start, period_end=period_end,
    )
    resp = api_client.generate_productivity_report(payload, ADMIN)
    return get_success_data(resp)


def create_coverage_window(window_date="2026-05-01", window_type="NIGHT_PRIMARY",
                           start_at="2026-05-01T19:00:00Z",
                           end_at="2026-05-02T07:00:00Z", capacity=2):
    payload = create_coverage_window_payload(
        window_date=window_date, window_type=window_type,
        start_at=start_at, end_at=end_at, capacity=capacity,
    )
    resp = api_client.create_coverage_window(payload, ADMIN)
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Higher-tier composite fixtures
# ---------------------------------------------------------------------------

def setup_two_hospitalists_with_shifts(
    h1_name="H One", h1_specialty="INTERNAL_MEDICINE", h1_cap=16,
    h1_shift_start="2026-05-01T06:00:00Z", h1_shift_end="2026-05-01T18:00:00Z",
    h2_name="H Two", h2_specialty="FAMILY_MEDICINE", h2_cap=16,
    h2_shift_start="2026-05-01T07:00:00Z", h2_shift_end="2026-05-01T19:00:00Z",
    clock=CLOCK_DEFAULT,
):
    """Two hospitalists, each with an ACTIVE shift covering `clock`.

    Returns (h1, s1, h2, s2).
    """
    h1 = create_hospitalist(h1_name, h1_specialty, max_census_cap=h1_cap)
    h2 = create_hospitalist(h2_name, h2_specialty, max_census_cap=h2_cap)
    s1 = create_shift(h1["id"], "DAY", h1_shift_start, h1_shift_end, activate=True)
    s2 = create_shift(h2["id"], "DAY", h2_shift_start, h2_shift_end, activate=True)
    set_clock(clock)
    return h1, s1, h2, s2


def discharge_patient(patient_id, ordering_hospitalist_id,
                      target_discharge_at="2026-05-02T15:00:00Z"):
    """Create + order + execute a discharge order. Returns the executed order."""
    order_obj = create_discharge_order_for(
        patient_id, ordering_hospitalist_id,
        target_discharge_at=target_discharge_at, order=True,
    )
    resp = api_client.execute_discharge_order(
        order_obj["id"], make_hospitalist_headers(ordering_hospitalist_id)
    )
    return get_success_data(resp)


def setup_handoff_accepted_for_shift(hospitalist, shift, receiver, patient_ids):
    """Create a handoff on `shift`, submit it, and have `receiver` accept it.
    Returns the ACCEPTED handoff."""
    hf = create_handoff_for(
        shift["id"], hospitalist["id"], receiver["id"], patient_ids,
    )
    resp = api_client.submit_handoff(hf["id"], make_hospitalist_headers(hospitalist["id"]))
    hf = get_success_data(resp)
    resp = api_client.accept_handoff(hf["id"], make_hospitalist_headers(receiver["id"]))
    return get_success_data(resp)
