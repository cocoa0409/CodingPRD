"""Composite setup helpers.

Every entity these helpers need is built from scratch through declared endpoints —
the implementation ships with an empty store and the harness restarts it before
each test, so nothing is ever carried over.

Identity threading: a ``SiteCoordinator``'s ``X-User-ID`` is the id of the Site they
run, and a ``FieldDentist`` / ``FieldHygienist`` / ``DentalAssistant``'s is the id of
their own StaffMember row. Each of those is built with its own per-instance header
builder — never a shared constant.
"""

from types import SimpleNamespace

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import BASE_CLOCK_UTC, TEST_DEFAULTS
from .test_users import (
    make_billing_specialist_headers,
    make_dental_assistant_headers,
    make_field_dentist_headers,
    make_field_hygienist_headers,
    make_program_admin_headers,
    make_site_coordinator_headers,
)

ADMIN = make_program_admin_headers()
BILLING = make_billing_specialist_headers()


# ─── Atomic builders ─────────────────────────────────────────────────────────

def set_clock(to_iso8601: str) -> str:
    """Move the logical clock. Writes no rows."""
    data = get_success_data(api_client.set_clock(to_iso8601, ADMIN))
    return data["current_utc"]


def build_program_period(name=None, starts_on=None, ends_on=None) -> dict:
    payload = {
        "name": name or TEST_DEFAULTS["PERIOD_NAME"],
        "starts_on": starts_on or TEST_DEFAULTS["PERIOD_STARTS_ON"],
        "ends_on": ends_on or TEST_DEFAULTS["PERIOD_ENDS_ON"],
    }
    return get_success_data(api_client.create_program_period(payload, ADMIN))


def build_site(name=None, site_type="SCHOOL", state_code="CA", **extra) -> dict:
    payload = {
        "name": name or (TEST_DEFAULTS["SCHOOL_NAME"] if site_type == "SCHOOL" else TEST_DEFAULTS["SNF_NAME"]),
        "site_type": site_type,
        "state_code": state_code,
    }
    payload.update(extra)
    return get_success_data(api_client.create_site(payload, ADMIN))


def build_staff(full_name, staff_role, license_number, supervision_level,
                license_state="CA", **extra) -> dict:
    payload = {
        "full_name": full_name,
        "staff_role": staff_role,
        "license_number": license_number,
        "license_state": license_state,
        "supervision_level": supervision_level,
    }
    payload.update(extra)
    return get_success_data(api_client.create_staff_member(payload, ADMIN))


def build_portable_unit(unit_code="PU-01", calibrated_on="2026-04-01") -> dict:
    unit = get_success_data(api_client.create_portable_unit({"unit_code": unit_code}, ADMIN))
    if calibrated_on is not None:
        unit = get_success_data(
            api_client.calibrate_portable_unit(unit["id"], {"calibrated_on": calibrated_on}, ADMIN)
        )
    return unit


def build_patient(site_id, coordinator_headers, **overrides) -> dict:
    payload = {
        "site_id": site_id,
        "patient_type": "STUDENT",
        "external_ref": "S-001",
        "first_name": "Mia",
        "last_name": "Lopez",
        "date_of_birth": "2016-03-04",
        "household_size": 4,
    }
    payload.update(overrides)
    return get_success_data(api_client.create_patient(payload, coordinator_headers))


def build_school_consent(patient_id, site_id, program_period_id, coordinator_headers,
                         scope_tier="SCREENING_FLUORIDE", signed_at=None, verify=True,
                         guardian_name="Rosa Lopez", **overrides) -> dict:
    payload = {
        "patient_id": patient_id,
        "site_id": site_id,
        "program_period_id": program_period_id,
        "regime": "SCHOOL_GUARDIAN",
        "scope_tier": scope_tier,
        "signed_at": signed_at or TEST_DEFAULTS["CONSENT_SIGNED_AT"],
        "guardian_name": guardian_name,
        "guardian_relationship": "MOTHER",
    }
    payload.update(overrides)
    consent = get_success_data(api_client.create_consent(payload, coordinator_headers))
    if verify:
        consent = get_success_data(api_client.verify_consent(consent["id"], coordinator_headers))
    return consent


def build_snf_consent(patient_id, site_id, program_period_id, coordinator_headers,
                      scope_tier="SCREENING_FLUORIDE", signed_at=None, verify=True,
                      **overrides) -> dict:
    payload = {
        "patient_id": patient_id,
        "site_id": site_id,
        "program_period_id": program_period_id,
        "regime": "SNF_RESPONSIBLE_PARTY",
        "scope_tier": scope_tier,
        "signed_at": signed_at or TEST_DEFAULTS["CONSENT_SIGNED_AT"],
        "responsible_party_name": "Tomas Reyes",
        "responsible_party_authority": "DURABLE_POA",
        "poa_document_ref": "POA-2019-118",
    }
    payload.update(overrides)
    consent = get_success_data(api_client.create_consent(payload, coordinator_headers))
    if verify:
        consent = get_success_data(api_client.verify_consent(consent["id"], coordinator_headers))
    return consent


def build_coverage(patient_id, payer_type="MEDICAID_MCO", verify=True,
                   verified_through_date=None, **overrides) -> dict:
    payload = {"patient_id": patient_id, "payer_type": payer_type}
    if payer_type == "MEDICAID_MCO":
        payload["payer_name"] = "GoldenState Dental MCO"
        payload["member_id"] = "M-77001"
    elif payer_type == "COMMERCIAL_FFS":
        payload["payer_name"] = "BlueDental PPO"
        payload["member_id"] = "C-42009"
    payload.update(overrides)
    coverage = get_success_data(api_client.create_coverage(payload, BILLING))
    if verify:
        coverage = get_success_data(
            api_client.verify_coverage(
                coverage["id"],
                {"verified_through_date": verified_through_date or TEST_DEFAULTS["COVERAGE_THROUGH"]},
                BILLING,
            )
        )
    return coverage


def build_site_visit(site_id, program_period_id, portable_unit_id, lead_staff_id,
                     coordinator_headers, scheduled_start_at=None, scheduled_end_at=None,
                     chair_count=2, **overrides) -> dict:
    payload = {
        "site_id": site_id,
        "program_period_id": program_period_id,
        "portable_unit_id": portable_unit_id,
        "lead_staff_id": lead_staff_id,
        "scheduled_start_at": scheduled_start_at or TEST_DEFAULTS["VISIT_START"],
        "scheduled_end_at": scheduled_end_at or TEST_DEFAULTS["VISIT_END"],
        "chair_count": chair_count,
    }
    payload.update(overrides)
    return get_success_data(api_client.create_site_visit(payload, coordinator_headers))


def build_sterilization_load(portable_unit_id, loaded_by_staff_id, loader_headers,
                             load_number="L-1", cycle_completed_at=None, site_visit_id=None) -> dict:
    payload = {
        "portable_unit_id": portable_unit_id,
        "loaded_by_staff_id": loaded_by_staff_id,
        "load_number": load_number,
        "cycle_completed_at": cycle_completed_at or TEST_DEFAULTS["LOAD_CYCLE_COMPLETED_AT"],
    }
    if site_visit_id is not None:
        payload["site_visit_id"] = site_visit_id
    return get_success_data(api_client.create_sterilization_load(payload, loader_headers))


def read_spore_result(load_id, result, reader_staff_id, reader_headers) -> dict:
    return get_success_data(
        api_client.record_spore_result(
            load_id, {"result": result, "result_recorded_by_staff_id": reader_staff_id}, reader_headers
        )
    )


# ─── Tier 2: the standard staffed school stack ───────────────────────────────

def setup_program_site_and_staff(clock=BASE_CLOCK_UTC, site_type="SCHOOL", state_code="CA",
                                 period_ends_on=None, calibrated_on="2026-04-01",
                                 unit_code="PU-01", site_extra=None):
    """Period + site + dentist/hygienist/assistant + one calibrated portable unit.

    Returns a namespace carrying every id and every per-identity header dict.
    """
    if clock is not None:
        set_clock(clock)
    period = build_program_period(ends_on=period_ends_on)
    site = build_site(site_type=site_type, state_code=state_code, **(site_extra or {}))
    dentist = build_staff("Ada Reyes", "DENTIST", "D-1001", "SELF", license_state=state_code)
    hygienist = build_staff("Hana Ito", "HYGIENIST", "H-2001", "GENERAL", license_state=state_code)
    assistant = build_staff("Ben Cruz", "DENTAL_ASSISTANT", "A-3001", "DIRECT", license_state=state_code)
    unit = build_portable_unit(unit_code=unit_code, calibrated_on=calibrated_on)
    return SimpleNamespace(
        period=period, pp_id=period["id"],
        site=site, site_id=site["id"],
        dentist=dentist, dentist_id=dentist["id"],
        hygienist=hygienist, hyg_id=hygienist["id"],
        assistant=assistant, asst_id=assistant["id"],
        unit=unit, unit_id=unit["id"],
        admin_headers=ADMIN,
        billing_headers=BILLING,
        coord_headers=make_site_coordinator_headers(site["id"]),
        dentist_headers=make_field_dentist_headers(dentist["id"]),
        hyg_headers=make_field_hygienist_headers(hygienist["id"]),
        asst_headers=make_dental_assistant_headers(assistant["id"]),
    )


def setup_visit_in_progress(stack, scope_tier="SCREENING_FLUORIDE", payer_type=None,
                            scheduled_start_at=None, scheduled_end_at=None, chair_count=2,
                            patient_overrides=None, consent_overrides=None,
                            coverage_overrides=None, verify_coverage=True,
                            assign_onsite_dentist=True, remote_dentist_staff_id=None,
                            load_cycle_completed_at=None, start=True):
    """Roster one patient with an ACTIVE consent, schedule a visit, pass a load and start it.

    Extends ``stack`` in place with patient / consent / (optional) coverage /
    visit / load ids and the visit's post-start ``version``.
    """
    patient = build_patient(stack.site_id, stack.coord_headers, **(patient_overrides or {}))
    if stack.site["site_type"] == "SNF":
        consent = build_snf_consent(
            patient["id"], stack.site_id, stack.pp_id, stack.coord_headers,
            scope_tier=scope_tier, **(consent_overrides or {}),
        )
    else:
        consent = build_school_consent(
            patient["id"], stack.site_id, stack.pp_id, stack.coord_headers,
            scope_tier=scope_tier, **(consent_overrides or {}),
        )
    coverage = None
    if payer_type is not None:
        coverage = build_coverage(
            patient["id"], payer_type=payer_type, verify=verify_coverage,
            **(coverage_overrides or {}),
        )

    visit_extra = {}
    if assign_onsite_dentist:
        visit_extra["onsite_dentist_staff_id"] = stack.dentist_id
    if remote_dentist_staff_id is not None:
        visit_extra["remote_dentist_staff_id"] = remote_dentist_staff_id
    visit = build_site_visit(
        stack.site_id, stack.pp_id, stack.unit_id, stack.dentist_id, stack.coord_headers,
        scheduled_start_at=scheduled_start_at, scheduled_end_at=scheduled_end_at,
        chair_count=chair_count, **visit_extra,
    )
    load = build_sterilization_load(
        stack.unit_id, stack.asst_id, stack.asst_headers,
        load_number="L-1", cycle_completed_at=load_cycle_completed_at, site_visit_id=visit["id"],
    )
    read_spore_result(load["id"], "PASSED", stack.hyg_id, stack.hyg_headers)
    if start:
        visit = get_success_data(api_client.start_site_visit(visit["id"], stack.dentist_headers))

    stack.patient = patient
    stack.patient_id = patient["id"]
    stack.consent = consent
    stack.consent_id = consent["id"]
    stack.coverage = coverage
    stack.cov_id = coverage["id"] if coverage else None
    stack.visit = visit
    stack.visit_id = visit["id"]
    stack.visit_version = visit["version"]
    stack.load = load
    stack.load1_id = load["id"]
    return stack


def register_encounter(stack, patient_id=None, consent_id=None, coverage_id="__default__",
                       expected_site_visit_version=None, headers=None):
    """Register one patient at the stack's visit and record the new encounter on the stack."""
    payload = {
        "site_visit_id": stack.visit_id,
        "patient_id": patient_id or stack.patient_id,
        "consent_id": consent_id or stack.consent_id,
        "expected_site_visit_version": (
            expected_site_visit_version
            if expected_site_visit_version is not None
            else current_visit_version(stack)
        ),
    }
    resolved_coverage = stack.cov_id if coverage_id == "__default__" else coverage_id
    if resolved_coverage is not None:
        payload["coverage_id"] = resolved_coverage
    encounter = get_success_data(
        api_client.create_encounter(payload, headers or stack.asst_headers)
    )
    stack.encounter = encounter
    stack.enc_id = encounter["id"]
    stack.enc_version = encounter["version"]
    return encounter


def current_visit_version(stack) -> int:
    return get_success_data(api_client.get_site_visit(stack.visit_id, ADMIN))["version"]


def current_encounter_version(stack, encounter_id=None) -> int:
    return get_success_data(
        api_client.get_encounter(encounter_id or stack.enc_id, ADMIN)
    )["version"]


def current_patient_version(stack, patient_id=None) -> int:
    return get_success_data(api_client.get_patient(patient_id or stack.patient_id, ADMIN))["version"]


def screen_encounter(stack, encounter_id=None, performing_staff_id=None, headers=None, **findings):
    payload = {
        "performing_staff_id": performing_staff_id or stack.hyg_id,
        "cavitated_lesion_count": 1,
        "pain_reported": False,
        "abscess_or_swelling": False,
        "untreated_decay_present": True,
    }
    payload.update(findings)
    encounter = get_success_data(
        api_client.screen_encounter(encounter_id or stack.enc_id, payload, headers or stack.hyg_headers)
    )
    stack.encounter = encounter
    stack.enc_version = encounter["version"]
    return encounter


def exam_encounter(stack, encounter_id=None, performing_staff_id=None, headers=None, **overrides):
    payload = {
        "performing_staff_id": performing_staff_id or stack.dentist_id,
        "exam_modality": "ONSITE",
    }
    payload.update(overrides)
    encounter = get_success_data(
        api_client.exam_encounter(encounter_id or stack.enc_id, payload, headers or stack.dentist_headers)
    )
    stack.encounter = encounter
    stack.enc_version = encounter["version"]
    return encounter


def plan_procedure(stack, procedure_code, encounter_id=None, headers=None,
                   expected_encounter_version=None, **overrides):
    payload = {
        "encounter_id": encounter_id or stack.enc_id,
        "procedure_code": procedure_code,
        "expected_encounter_version": (
            expected_encounter_version
            if expected_encounter_version is not None
            else current_encounter_version(stack, encounter_id)
        ),
    }
    payload.update(overrides)
    return get_success_data(api_client.create_procedure(payload, headers or stack.hyg_headers))


def perform_procedure(stack, procedure_id, performing_staff_id=None,
                      sterilization_load_id=None, headers=None):
    payload = {
        "performing_staff_id": performing_staff_id or stack.hyg_id,
        "sterilization_load_id": sterilization_load_id or stack.load1_id,
    }
    return get_success_data(
        api_client.perform_procedure(procedure_id, payload, headers or stack.hyg_headers)
    )


def void_procedure(stack, procedure_id, void_reason="DOCUMENTATION_ERROR", headers=None):
    return get_success_data(
        api_client.void_procedure(procedure_id, {"void_reason": void_reason},
                                  headers or stack.dentist_headers)
    )


def list_encounter_procedures(encounter_id, params=None):
    query = {"encounter_id": encounter_id, "limit": 100}
    query.update(params or {})
    body = api_client.list_procedures(ADMIN, params=query).json()
    return body["data"]


def auto_procedure_id(encounter_id, procedure_code):
    """Find an auto-created D0190 / D0150 row — the list endpoint is its only discovery channel."""
    rows = list_encounter_procedures(encounter_id, {"procedure_code": procedure_code})
    assert rows, f"Setup failed: no {procedure_code} procedure found on encounter {encounter_id}"
    return rows[0]["id"]


# ─── Tier 3: full lifecycle shortcuts ────────────────────────────────────────

def setup_screened_and_examined(clock=BASE_CLOCK_UTC, scope_tier="SCREENING_FLUORIDE",
                                payer_type=None, site_type="SCHOOL", chair_count=2,
                                scheduled_start_at=None, scheduled_end_at=None,
                                screening=None, exam=None, patient_overrides=None,
                                coverage_overrides=None, verify_coverage=True,
                                period_ends_on=None, calibrated_on="2026-04-01"):
    """Standard stack → IN_PROGRESS visit → registered encounter → screened → examined."""
    stack = setup_program_site_and_staff(
        clock=clock, site_type=site_type, period_ends_on=period_ends_on,
        calibrated_on=calibrated_on,
    )
    setup_visit_in_progress(
        stack, scope_tier=scope_tier, payer_type=payer_type, chair_count=chair_count,
        scheduled_start_at=scheduled_start_at, scheduled_end_at=scheduled_end_at,
        patient_overrides=patient_overrides, coverage_overrides=coverage_overrides,
        verify_coverage=verify_coverage,
    )
    register_encounter(stack)
    screen_encounter(stack, **(screening or {}))
    exam_encounter(stack, **(exam or {}))
    return stack


def setup_treated_encounter_with_varnish(clock=BASE_CLOCK_UTC, payer_type="MEDICAID_MCO",
                                         scope_tier="SCREENING_FLUORIDE",
                                         patient_overrides=None, coverage_overrides=None):
    """Screened + examined + one PERFORMED D1206 → three PERFORMED procedures on the encounter."""
    stack = setup_screened_and_examined(
        clock=clock, scope_tier=scope_tier, payer_type=payer_type,
        patient_overrides=patient_overrides, coverage_overrides=coverage_overrides,
    )
    varnish = plan_procedure(stack, "D1206")
    stack.varnish = perform_procedure(stack, varnish["id"])
    stack.varnish_id = varnish["id"]
    return stack


def setup_active_plan_and_referral(clock="2026-05-11T14:00:00Z", screening=None,
                                   planned_procedure_codes=None):
    """Screened + examined encounter → ACTIVE TreatmentPlan → OPEN Referral."""
    stack = setup_screened_and_examined(clock=clock, screening=screening)
    plan_payload = {
        "encounter_id": stack.enc_id,
        "patient_id": stack.patient_id,
        "authoring_staff_id": stack.dentist_id,
        "planned_procedure_codes": planned_procedure_codes or ["D1206"],
    }
    plan = get_success_data(api_client.create_treatment_plan(plan_payload, stack.dentist_headers))
    plan = get_success_data(api_client.activate_treatment_plan(plan["id"], stack.dentist_headers))
    referral = get_success_data(
        api_client.create_referral(
            {
                "treatment_plan_id": plan["id"],
                "patient_id": stack.patient_id,
                "dental_home_name": "Riverside Family Dental",
            },
            stack.dentist_headers,
        )
    )
    stack.plan = plan
    stack.plan_id = plan["id"]
    stack.referral = referral
    stack.ref_id = referral["id"]
    return stack


# ─── Tier 5: reporting / freeze ──────────────────────────────────────────────

def move_period_to_reporting(stack):
    return get_success_data(
        api_client.set_program_period_status(stack.pp_id, {"to_status": "REPORTING"}, ADMIN)
    )


def build_and_generate_program_report(stack):
    report = get_success_data(
        api_client.create_report({"program_period_id": stack.pp_id, "report_type": "PROGRAM_PERIOD"}, ADMIN)
    )
    report = get_success_data(api_client.generate_report(report["id"], ADMIN))
    stack.report = report
    stack.report_id = report["id"]
    return report


def freeze_period_by_submitting_report(stack, state_submission_ref="CA-DHCS-2026-0001"):
    """REPORTING → generate a programme report → submit it, arming the global write gate."""
    move_period_to_reporting(stack)
    build_and_generate_program_report(stack)
    stack.report = get_success_data(
        api_client.submit_report(stack.report_id, {"state_submission_ref": state_submission_ref}, ADMIN)
    )
    return stack.report
