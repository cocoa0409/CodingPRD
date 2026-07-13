"""Composite setup helpers for the Poison Control Triage tests.

Every helper builds its preconditions from scratch using only PRD-declared
endpoints, because the test harness restarts the server (empty database) before
each test. Setup calls use the lenient ``get_success_data`` validator so that a
broken precondition surfaces as a clear "Setup failed" error.

Identity threading: a Specialist/Toxicologist is entity_backed, so ownership and
attribution checks compare a resource's specialist FK to ``X-User-ID``. Helpers
therefore pass the real ``Specialist.id`` via ``make_specialist_headers`` /
``make_toxicologist_headers``.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import STARTUP_CLOCK
from .factories import (
    create_case_payload,
    create_disposition_payload,
    create_exposure_payload,
    create_facility_consult_payload,
    create_facility_payload,
    create_follow_up_call_payload,
    create_npds_report_payload,
    create_protocol_payload,
    create_risk_assessment_payload,
    create_specialist_payload,
    create_substance_payload,
)
from .test_users import (
    TEST_USERS,
    make_specialist_headers,
    make_toxicologist_headers,
)


def _data(resp):
    return get_success_data(resp)


# --------------------------------------------------------------------------
# Primitives
# --------------------------------------------------------------------------

def set_clock(api, to_iso8601="2026-06-01T00:00:00Z"):
    return _data(api.set_clock(to_iso8601, TEST_USERS["system_admin_headers"]))


def seed_specialist(api, full_name="Sam SPI", credential="SPI", **overrides):
    payload = create_specialist_payload(full_name=full_name, credential=credential, **overrides)
    return _data(api.create_specialist(payload, TEST_USERS["system_admin_headers"]))


def seed_substance(api, **overrides):
    payload = create_substance_payload(**overrides)
    return _data(api.create_substance(payload, TEST_USERS["system_admin_headers"]))


def seed_facility(api, **overrides):
    payload = create_facility_payload(**overrides)
    return _data(api.create_facility(payload, TEST_USERS["system_admin_headers"]))


def seed_protocol(api, **overrides):
    payload = create_protocol_payload(**overrides)
    return _data(api.create_protocol(payload, TEST_USERS["system_admin_headers"]))


def open_case(api, spi_id, **overrides):
    payload = create_case_payload(**overrides)
    return _data(api.create_case(payload, make_specialist_headers(spi_id)))


def add_exposure(api, case_id, spi_id, substance_id, **overrides):
    payload = create_exposure_payload(substance_id, **overrides)
    return _data(api.create_exposure(case_id, payload, make_specialist_headers(spi_id)))


def triage(api, case_id, spi_id):
    return _data(api.triage_case(case_id, make_specialist_headers(spi_id)))


def create_assessment(api, case_id, spi_id, expected_case_version):
    payload = create_risk_assessment_payload(expected_case_version)
    return _data(api.create_risk_assessment(case_id, payload, make_specialist_headers(spi_id)))


def finalize(api, ra_id, user_id, role="Specialist"):
    headers = (make_toxicologist_headers(user_id) if role == "Toxicologist"
               else make_specialist_headers(user_id))
    return _data(api.finalize_risk_assessment(ra_id, headers))


def create_home_disposition(api, case_id, ra_id, spi_id):
    payload = create_disposition_payload(ra_id, "HOME_MANAGEMENT")
    return _data(api.create_disposition(case_id, payload, make_specialist_headers(spi_id)))


# --------------------------------------------------------------------------
# Scenario builders
# --------------------------------------------------------------------------

def setup_triaged_completed_assessment(api, *, dose_low=1200, dose_high=1500,
                                       weight=20, clock=None):
    """Substance + specialist + case (weight kg) + one exposure + triage +
    a COMPLETED (un-finalized) RiskAssessment. Returns capture dict."""
    if clock:
        set_clock(api, clock)
    substance = seed_substance(api)
    spi = seed_specialist(api)
    case = open_case(api, spi["id"], patient_weight_kg=weight)
    exposure = add_exposure(api, case["id"], spi["id"], substance["id"],
                            dose_range_low_mg=dose_low, dose_range_high_mg=dose_high)
    triaged = triage(api, case["id"], spi["id"])
    ra = create_assessment(api, case["id"], spi["id"], triaged["version"])
    return {
        "substance": substance, "spi": spi, "case": case,
        "exposure": exposure, "ra": ra, "case_version_at_triage": triaged["version"],
    }


def setup_monitoring_case(api, *, followup_count=2, interval_hours=24,
                          dose_low=1200, dose_high=1500, weight=20,
                          clock="2026-06-01T00:00:00Z"):
    """MODERATE case driven to MONITORING: exposure -> triage -> RA -> finalize
    -> HOME_MANAGEMENT disposition (which auto-schedules follow-up calls)."""
    set_clock(api, clock)
    substance = seed_substance(api)
    seed_protocol(api, risk_tier="MODERATE", management_setting="HOME",
                  followup_count=followup_count, followup_interval_hours=interval_hours,
                  requires_toxicologist=False)
    spi = seed_specialist(api)
    case = open_case(api, spi["id"], patient_weight_kg=weight)
    exposure = add_exposure(api, case["id"], spi["id"], substance["id"],
                            dose_range_low_mg=dose_low, dose_range_high_mg=dose_high)
    triaged = triage(api, case["id"], spi["id"])
    ra = create_assessment(api, case["id"], spi["id"], triaged["version"])
    finalize(api, ra["id"], spi["id"], role="Specialist")
    disposition = create_home_disposition(api, case["id"], ra["id"], spi["id"])
    followups = _data(api.list_follow_up_calls(
        make_specialist_headers(spi["id"]), params={"case_id": case["id"]}))
    return {
        "substance": substance, "spi": spi, "case": case, "exposure": exposure,
        "ra": ra, "disposition": disposition, "followups": followups,
    }


def setup_triaged_consult(api, *, dose_low=1000, dose_high=1500, weight=20,
                          capacity=2, clock="2026-06-01T00:00:00Z"):
    """Triaged case + COMPLETED RiskAssessment + an ACTIVE FacilityConsult.
    Used by ESTIMATED-vs-CONFIRMED, consult-count invariant, and billing tests.
    The consult is opened with consult_duration_minutes=90 by default."""
    set_clock(api, clock)
    substance = seed_substance(api)
    facility = seed_facility(api, consult_capacity=capacity)
    spi = seed_specialist(api)
    tox = seed_specialist(api, full_name="Tara Tox", credential="TOXICOLOGIST")
    case = open_case(api, spi["id"], patient_weight_kg=weight)
    exposure = add_exposure(api, case["id"], spi["id"], substance["id"],
                            dose_range_low_mg=dose_low, dose_range_high_mg=dose_high)
    triaged = triage(api, case["id"], spi["id"])
    ra = create_assessment(api, case["id"], spi["id"], triaged["version"])
    consult = _data(api.create_facility_consult(
        create_facility_consult_payload(case["id"], facility["id"], 90),
        make_toxicologist_headers(tox["id"])))
    return {
        "substance": substance, "facility": facility, "spi": spi, "tox": tox,
        "case": case, "exposure": exposure, "ra": ra, "consult": consult,
    }


def setup_monitoring_case_with_consult(api, *, followup_count=2, interval_hours=24,
                                       dose_low=1200, dose_high=1500, weight=20,
                                       capacity=2, clock="2026-06-01T00:00:00Z"):
    """MODERATE case in MONITORING (with scheduled follow-ups) that ALSO has an
    ACTIVE FacilityConsult open. Used by the depth-3 consult-close cascade."""
    set_clock(api, clock)
    substance = seed_substance(api)
    seed_protocol(api, risk_tier="MODERATE", management_setting="HOME",
                  followup_count=followup_count, followup_interval_hours=interval_hours,
                  requires_toxicologist=False)
    facility = seed_facility(api, consult_capacity=capacity)
    spi = seed_specialist(api)
    tox = seed_specialist(api, full_name="Tara Tox", credential="TOXICOLOGIST")
    case = open_case(api, spi["id"], patient_weight_kg=weight)
    exposure = add_exposure(api, case["id"], spi["id"], substance["id"],
                            dose_range_low_mg=dose_low, dose_range_high_mg=dose_high)
    triaged = triage(api, case["id"], spi["id"])
    ra = create_assessment(api, case["id"], spi["id"], triaged["version"])
    finalize(api, ra["id"], spi["id"], role="Specialist")
    disposition = create_home_disposition(api, case["id"], ra["id"], spi["id"])
    consult = _data(api.create_facility_consult(
        create_facility_consult_payload(case["id"], facility["id"], 90),
        make_toxicologist_headers(tox["id"])))
    followups = _data(api.list_follow_up_calls(
        make_specialist_headers(spi["id"]), params={"case_id": case["id"]}))
    return {
        "substance": substance, "facility": facility, "spi": spi, "tox": tox,
        "case": case, "exposure": exposure, "ra": ra, "disposition": disposition,
        "consult": consult, "followups": followups,
    }


def setup_severe_completed_assessment(api, *, weight=20, clock="2026-06-01T00:00:00Z"):
    """SEVERE case (exposure dose 3000 -> score 1.00) triaged with a COMPLETED
    (un-finalized) RiskAssessment. No SEVERE protocol is created."""
    set_clock(api, clock)
    substance = seed_substance(api)
    spi = seed_specialist(api)
    tox = seed_specialist(api, full_name="Tara Tox", credential="TOXICOLOGIST")
    case = open_case(api, spi["id"], patient_weight_kg=weight,
                     chief_complaint="large ingestion")
    exposure = add_exposure(api, case["id"], spi["id"], substance["id"],
                            dose_range_low_mg=3000, dose_range_high_mg=3000)
    triaged = triage(api, case["id"], spi["id"])
    ra = create_assessment(api, case["id"], spi["id"], triaged["version"])
    return {"substance": substance, "spi": spi, "tox": tox, "case": case,
            "exposure": exposure, "ra": ra}


def setup_moderate_finalized_assessment(api, *, clock="2026-06-01T00:00:00Z"):
    """MODERATE case with a FINALIZED RiskAssessment (protocol exists)."""
    set_clock(api, clock)
    substance = seed_substance(api)
    seed_protocol(api, risk_tier="MODERATE", management_setting="HOME",
                  followup_count=1, followup_interval_hours=24)
    spi = seed_specialist(api)
    case = open_case(api, spi["id"])
    add_exposure(api, case["id"], spi["id"], substance["id"])
    triaged = triage(api, case["id"], spi["id"])
    ra = create_assessment(api, case["id"], spi["id"], triaged["version"])
    finalize(api, ra["id"], spi["id"], role="Specialist")
    return {"substance": substance, "spi": spi, "case": case, "ra": ra}


def setup_moderate_completed_with_protocol(api, *, clock="2026-06-01T00:00:00Z"):
    """MODERATE case triaged with a COMPLETED RiskAssessment and a MODERATE HOME
    protocol available (so finalize can succeed later)."""
    set_clock(api, clock)
    substance = seed_substance(api)
    seed_protocol(api, risk_tier="MODERATE", management_setting="HOME",
                  followup_count=1, followup_interval_hours=24)
    spi = seed_specialist(api)
    case = open_case(api, spi["id"])
    add_exposure(api, case["id"], spi["id"], substance["id"])
    triaged = triage(api, case["id"], spi["id"])
    ra = create_assessment(api, case["id"], spi["id"], triaged["version"])
    return {"substance": substance, "spi": spi, "case": case, "ra": ra}


def setup_triaged_case_for_followups(api, *, clock="2026-06-01T00:00:00Z"):
    """A triaged case plus a second specialist, ready for manual follow-up
    scheduling (used by the case-level half-open overlap test)."""
    set_clock(api, clock)
    substance = seed_substance(api)
    spi = seed_specialist(api)
    spi2 = seed_specialist(api, full_name="Pat SPI2", credential="SPI")
    case = open_case(api, spi["id"])
    add_exposure(api, case["id"], spi["id"], substance["id"])
    triage(api, case["id"], spi["id"])
    return {"substance": substance, "spi": spi, "spi2": spi2, "case": case}


def setup_two_triaged_cases_one_specialist(api, *, clock="2026-06-01T00:00:00Z"):
    """One specialist, two triaged cases; case1 already has a follow-up call
    [10:00,10:30] assigned to the specialist (specialist double-booking test)."""
    set_clock(api, clock)
    substance = seed_substance(api)
    spi = seed_specialist(api)
    case1 = open_case(api, spi["id"], chief_complaint="case1")
    add_exposure(api, case1["id"], spi["id"], substance["id"])
    triage(api, case1["id"], spi["id"])
    _data(api.create_follow_up_call(
        case1["id"],
        create_follow_up_call_payload(spi["id"], 0,
                                      "2026-06-02T10:00:00Z", "2026-06-02T10:30:00Z"),
        make_specialist_headers(spi["id"])))
    case2 = open_case(api, spi["id"], patient_age_years=7, patient_weight_kg=22,
                      patient_sex="FEMALE", chief_complaint="case2")
    add_exposure(api, case2["id"], spi["id"], substance["id"])
    triage(api, case2["id"], spi["id"])
    return {"substance": substance, "spi": spi, "case1": case1, "case2": case2}


def setup_diverting_facility_case(api, *, clock="2026-06-01T00:00:00Z"):
    """A DIVERTING facility plus a triaged MODERATE case with a COMPLETED
    RiskAssessment (defines the risk tier). No consult opened yet."""
    set_clock(api, clock)
    substance = seed_substance(api)
    facility = seed_facility(api, name="Diverting ED", status="DIVERTING", consult_capacity=2)
    spi = seed_specialist(api)
    tox = seed_specialist(api, full_name="Tara Tox", credential="TOXICOLOGIST")
    case = open_case(api, spi["id"])
    add_exposure(api, case["id"], spi["id"], substance["id"])
    triaged = triage(api, case["id"], spi["id"])
    create_assessment(api, case["id"], spi["id"], triaged["version"])
    return {"substance": substance, "facility": facility, "spi": spi, "tox": tox, "case": case}


def setup_npds_submitted(api, *, dose_low=1200, dose_high=1500, weight=20,
                         clock="2026-06-01T00:00:00Z"):
    """Triaged case + COMPLETED RiskAssessment + a SUBMITTED NpdsReport."""
    ctx = setup_triaged_completed_assessment(api, dose_low=dose_low,
                                             dose_high=dose_high, weight=weight, clock=clock)
    report = _data(api.create_npds_report(
        create_npds_report_payload(ctx["case"]["id"], ctx["substance"]["id"]),
        TEST_USERS["surveillance_officer_headers"]))
    ctx["report"] = report
    return ctx
