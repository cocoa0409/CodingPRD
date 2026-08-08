"""Registration, the two triage variants, the exam window and the supervision matrix."""

from types import SimpleNamespace

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_encounter,
    assert_same_instant,
    build_patient,
    build_portable_unit,
    build_program_period,
    build_school_consent,
    build_site,
    build_site_visit,
    build_snf_consent,
    build_staff,
    build_sterilization_load,
    current_visit_version,
    get_success_data,
    list_encounter_procedures,
    make_dental_assistant_headers,
    make_field_dentist_headers,
    make_field_hygienist_headers,
    make_program_admin_headers,
    make_site_coordinator_headers,
    read_spore_result,
    register_encounter,
    screen_encounter,
    set_clock,
    setup_program_site_and_staff,
    setup_visit_in_progress,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = make_program_admin_headers()

IDENTICAL_FINDINGS = {
    "cavitated_lesion_count": 1,
    "pain_reported": False,
    "abscess_or_swelling": False,
    "untreated_decay_present": True,
    "denture_problem": False,
    "oral_hygiene_score": 1,
    "medical_complexity_count": 4,
}


def _two_site_encounter_fixture():
    """One REGISTERED encounter at a SCHOOL site and one at an SNF site, on separate units and crews."""
    set_clock("2026-05-11T09:00:00Z")
    period = build_program_period()
    school = build_site(site_type="SCHOOL")
    snf = build_site(site_type="SNF", roster_disclosure_level="CLINICAL_DETAIL")
    school_coord = make_site_coordinator_headers(school["id"])
    snf_coord = make_site_coordinator_headers(snf["id"])

    dentist1 = build_staff("Ada Reyes", "DENTIST", "D-1001", "SELF")
    hyg1 = build_staff("Hana Ito", "HYGIENIST", "H-2001", "GENERAL")
    assistant = build_staff("Ben Cruz", "DENTAL_ASSISTANT", "A-3001", "DIRECT")
    dentist2 = build_staff("Cy Nolan", "DENTIST", "D-1002", "SELF")
    hyg2 = build_staff("Rae Okon", "HYGIENIST", "H-2002", "GENERAL")
    asst_headers = make_dental_assistant_headers(assistant["id"])

    unit1 = build_portable_unit(unit_code="PU-01")
    unit2 = build_portable_unit(unit_code="PU-02")

    student = build_patient(school["id"], school_coord, external_ref="S-001")
    resident = build_patient(
        snf["id"], snf_coord, patient_type="RESIDENT", external_ref="R-001",
        first_name="Alma", last_name="Reyes", date_of_birth="1941-09-12",
        room_number="214B", household_size=1, capacity_determination="HAS_CAPACITY",
    )
    school_consent = build_school_consent(student["id"], school["id"], period["id"], school_coord)
    snf_consent = build_snf_consent(resident["id"], snf["id"], period["id"], snf_coord)

    school_visit = build_site_visit(
        school["id"], period["id"], unit1["id"], dentist1["id"], school_coord,
        onsite_dentist_staff_id=dentist1["id"],
    )
    snf_visit = build_site_visit(
        snf["id"], period["id"], unit2["id"], dentist2["id"], snf_coord,
        onsite_dentist_staff_id=dentist2["id"],
    )
    load1 = build_sterilization_load(unit1["id"], assistant["id"], asst_headers,
                                     load_number="L-1", site_visit_id=school_visit["id"])
    read_spore_result(load1["id"], "PASSED", hyg1["id"], make_field_hygienist_headers(hyg1["id"]))
    load2 = build_sterilization_load(unit2["id"], assistant["id"], asst_headers,
                                     load_number="L-2", site_visit_id=snf_visit["id"])
    read_spore_result(load2["id"], "PASSED", hyg2["id"], make_field_hygienist_headers(hyg2["id"]))

    school_visit = get_success_data(
        api_client.start_site_visit(school_visit["id"], make_field_dentist_headers(dentist1["id"]))
    )
    snf_visit = get_success_data(
        api_client.start_site_visit(snf_visit["id"], make_field_dentist_headers(dentist2["id"]))
    )
    school_enc = get_success_data(
        api_client.create_encounter(
            {
                "site_visit_id": school_visit["id"],
                "patient_id": student["id"],
                "consent_id": school_consent["id"],
                "expected_site_visit_version": school_visit["version"],
            },
            asst_headers,
        )
    )
    snf_enc = get_success_data(
        api_client.create_encounter(
            {
                "site_visit_id": snf_visit["id"],
                "patient_id": resident["id"],
                "consent_id": snf_consent["id"],
                "expected_site_visit_version": snf_visit["version"],
            },
            asst_headers,
        )
    )
    return SimpleNamespace(
        school_enc_id=school_enc["id"], snf_enc_id=snf_enc["id"],
        hyg1_id=hyg1["id"], hyg2_id=hyg2["id"],
        hyg1_headers=make_field_hygienist_headers(hyg1["id"]),
        hyg2_headers=make_field_hygienist_headers(hyg2["id"]),
    )


def test_school_triage_ignores_medical_complexity_and_lands_on_early_care(api):
    """PRD §3.5: "At a `SCHOOL` site: if `abscess_or_swelling` is true, the band is `URGENT`.
    Otherwise, if `pain_reported` is true **and** `cavitated_lesion_count` is at least 1, the
    band is `URGENT`. Otherwise, if `cavitated_lesion_count` is at least 1 **or**
    `untreated_decay_present` is true, the band is `EARLY_CARE_NEEDED`."
    PRD §3.5: "`denture_problem`, `oral_hygiene_score` and `medical_complexity_count` are
    ignored entirely, whatever values are supplied."

    Design: Difficulty/dual_variant_calc/school_vs_snf_triage_band_on_byte_identical_screening_findings
    """
    fx = _two_site_encounter_fixture()
    encounter = validate_success(
        api.screen_encounter(
            fx.school_enc_id,
            {"performing_staff_id": fx.hyg1_id, **IDENTICAL_FINDINGS},
            fx.hyg1_headers,
        )
    )
    assert_encounter(encounter)
    assert encounter["triage_band"] == "EARLY_CARE_NEEDED", (
        f"A school screen with complexity 4 stays EARLY_CARE_NEEDED, got {encounter['triage_band']}"
    )
    assert encounter["clinical_status"] == "SCREENED"


def test_snf_triage_escalates_a_single_lesion_on_medical_complexity(api):
    """PRD §3.5: "Otherwise, if `cavitated_lesion_count` is at least 1 **and**
    `medical_complexity_count` is at least 3, the band is `URGENT`; medical complexity
    escalates even a single lesion."
    PRD §3.5: "**Screening** moves the encounter `REGISTERED → SCREENED` and requires the
    visit to be `IN_PROGRESS` and the cited consent to be `ACTIVE` and not yet past its
    `expires_at`."

    Design: Difficulty/dual_variant_calc/school_vs_snf_triage_band_on_byte_identical_screening_findings
    """
    fx = _two_site_encounter_fixture()
    encounter = validate_success(
        api.screen_encounter(
            fx.snf_enc_id,
            {"performing_staff_id": fx.hyg2_id, **IDENTICAL_FINDINGS},
            fx.hyg2_headers,
        )
    )
    assert encounter["triage_band"] == "URGENT", (
        f"The SNF variant escalates on complexity 4, got {encounter['triage_band']}"
    )
    assert encounter["clinical_status"] == "SCREENED"


def _remote_supervision_fixture():
    """An IN_PROGRESS visit with a REMOTE dentist and no onsite dentist, two PLANNED sealants."""
    set_clock("2026-05-11T09:00:00Z")
    period = build_program_period()
    site = build_site(site_type="SCHOOL")
    coord = make_site_coordinator_headers(site["id"])
    remote_dentist = build_staff("Ada Reyes", "DENTIST", "D-1001", "SELF")
    phh = build_staff("Pia Han", "PUBLIC_HEALTH_HYGIENIST", "P-5001", "GENERAL")
    hygienist = build_staff("Hana Ito", "HYGIENIST", "H-2001", "GENERAL")
    assistant = build_staff("Ben Cruz", "DENTAL_ASSISTANT", "A-3001", "DIRECT")
    phh_headers = make_field_hygienist_headers(phh["id"])
    hyg_headers = make_field_hygienist_headers(hygienist["id"])
    asst_headers = make_dental_assistant_headers(assistant["id"])
    unit = build_portable_unit()

    patient = build_patient(site["id"], coord, external_ref="S-001")
    consent = build_school_consent(patient["id"], site["id"], period["id"], coord,
                                   scope_tier="SCREENING_FLUORIDE_SEALANT")
    visit = build_site_visit(
        site["id"], period["id"], unit["id"], phh["id"], coord,
        remote_dentist_staff_id=remote_dentist["id"],
    )
    load = build_sterilization_load(unit["id"], assistant["id"], asst_headers,
                                    load_number="L-1", site_visit_id=visit["id"])
    read_spore_result(load["id"], "PASSED", phh["id"], phh_headers)
    visit = get_success_data(api_client.start_site_visit(visit["id"], phh_headers))
    encounter = get_success_data(
        api_client.create_encounter(
            {
                "site_visit_id": visit["id"],
                "patient_id": patient["id"],
                "consent_id": consent["id"],
                "expected_site_visit_version": visit["version"],
            },
            asst_headers,
        )
    )
    get_success_data(
        api_client.screen_encounter(
            encounter["id"],
            {
                "performing_staff_id": phh["id"],
                "cavitated_lesion_count": 2,
                "pain_reported": False,
                "abscess_or_swelling": False,
                "untreated_decay_present": True,
            },
            phh_headers,
        )
    )
    examined = get_success_data(
        api_client.exam_encounter(
            encounter["id"],
            {
                "performing_staff_id": phh["id"],
                "exam_modality": "TELEDENTISTRY",
                "teledentistry_reviewed_at": "2026-05-11T10:00:00Z",
            },
            phh_headers,
        )
    )
    seal3 = get_success_data(
        api_client.create_procedure(
            {
                "encounter_id": encounter["id"],
                "procedure_code": "D1351",
                "tooth_number": 3,
                "surface": "O",
                "expected_encounter_version": examined["version"],
            },
            phh_headers,
        )
    )
    enc_v2 = get_success_data(api_client.get_encounter(encounter["id"], ADMIN))["version"]
    seal14 = get_success_data(
        api_client.create_procedure(
            {
                "encounter_id": encounter["id"],
                "procedure_code": "D1351",
                "tooth_number": 14,
                "surface": "O",
                "expected_encounter_version": enc_v2,
            },
            phh_headers,
        )
    )
    return SimpleNamespace(
        phh_id=phh["id"], phh_headers=phh_headers,
        hyg_id=hygienist["id"], hyg_headers=hyg_headers,
        load_id=load["id"], seal3_id=seal3["id"], seal14_id=seal14["id"],
    )


def test_public_health_hygienist_may_seal_under_a_remote_dentist(api):
    """PRD §3.5: "When the required level is `GENERAL`, either the visit's
    `onsite_dentist_staff_id` or its `remote_dentist_staff_id` may satisfy it, on the same
    terms — an active dentist, present onsite or reviewing remotely."
    PRD §3.5: "The consequence is that a clinician can clear the rank test and still fail on
    presence, and that a more highly authorised clinician can be permitted for a code where a
    less authorised one is not."

    Design: Difficulty/combinatorial_formula/supervision_matrix_same_authorisation_different_role_diverges_on_presence
    """
    fx = _remote_supervision_fixture()
    performed = validate_success(
        api.perform_procedure(
            fx.seal3_id,
            {"performing_staff_id": fx.phh_id, "sterilization_load_id": fx.load_id},
            fx.phh_headers,
        )
    )
    assert performed["status"] == "PERFORMED"
    assert performed["performing_staff_id"] == fx.phh_id


def test_hygienist_with_the_same_authorisation_fails_the_presence_requirement(api):
    """PRD §3.5: "Third — and this is the step that makes the rule non-linear — a
    **presence** requirement is applied, keyed on the level the *matrix required*, never on
    the level the clinician personally holds. When the required level is `DIRECT` or
    `INDIRECT`, the visit's `onsite_dentist_staff_id` must be non-null and must name a staff
    member whose `staff_role` is `DENTIST` and whose `credential_status` is `ACTIVE`."
    PRD §3.5: "A failure at any of the three steps is `ERR_SUPERVISION_NOT_PERMITTED`."

    Design: Difficulty/combinatorial_formula/supervision_matrix_same_authorisation_different_role_diverges_on_presence
    """
    fx = _remote_supervision_fixture()
    resp = api.perform_procedure(
        fx.seal14_id,
        {"performing_staff_id": fx.hyg_id, "sterilization_load_id": fx.load_id},
        fx.hyg_headers,
    )
    validate_error(resp, ApiErrorId.ERR_SUPERVISION_NOT_PERMITTED.value, 422)

    procedure = validate_success(api.get_procedure(fx.seal14_id, ADMIN))
    assert procedure["status"] == "PLANNED"
    assert procedure["performing_staff_id"] is None

    phh = validate_success(api.get_staff_member(fx.phh_id, ADMIN))
    hygienist = validate_success(api.get_staff_member(fx.hyg_id, ADMIN))
    assert phh["supervision_level"] == hygienist["supervision_level"] == "GENERAL", (
        "Both clinicians hold the identical authorisation; only the required level differs"
    )


def test_a_new_encounter_starts_registered_on_one_axis_and_unbilled_on_the_other(api):
    """PRD §3.5: "A new encounter lands with `clinical_status` `REGISTERED` and
    `billing_status` `UNBILLED`, `triage_band` null, every screening finding null, every money
    field zero and `pricing_regime` null."
    PRD §2.11: "**Registering an encounter** mints the `Encounter` at `version` 1 and
    increments `SiteVisit.version` by exactly 1."

    Design: Corner/state_machines/encounter_starts_in_registered_and_unbilled_on_both_axes
    """
    stack = setup_program_site_and_staff(clock="2026-05-11T09:00:00Z")
    setup_visit_in_progress(stack)
    visit_v1 = current_visit_version(stack)

    resp = api.create_encounter(
        {
            "site_visit_id": stack.visit_id,
            "patient_id": stack.patient_id,
            "consent_id": stack.consent_id,
            "expected_site_visit_version": visit_v1,
        },
        stack.asst_headers,
    )
    encounter = validate_success(resp, 201)
    assert_encounter(encounter)
    assert encounter["clinical_status"] == "REGISTERED"
    assert encounter["billing_status"] == "UNBILLED"
    assert encounter["triage_band"] is None
    assert encounter["pricing_regime"] is None
    assert encounter["total_charge_cents"] == 0
    assert encounter["version"] == 1
    assert validate_success(api.get_site_visit(stack.visit_id, ADMIN))["version"] == visit_v1 + 1


def test_teledentistry_review_outside_the_seventy_two_hour_window_is_refused(api):
    """PRD §2.6: "When an exam declares an `exam_modality` of `TELEDENTISTRY`,
    `teledentistry_reviewed_at` must be present and must fall inside the closed interval that
    begins at the visit's `scheduled_start_at` and ends 72 hours later — both endpoints
    inclusive. An absent value, a value before the window opens, or a value after it closes
    all refuse the exam."
    PRD §3.5: "Examining auto-creates a `D0150` procedure on exactly the same terms as
    screening's `D0190` — `PERFORMED`, stamped at the clock, attributed to the examining
    clinician, carrying the same latest-load reference, and booking its own chair minutes."

    Design: Corner/validations/teledentistry_exam_reviewed_outside_the_seventy_two_hour_window_is_refused
    """
    stack = setup_program_site_and_staff(clock="2026-05-11T09:00:00Z")
    setup_visit_in_progress(stack)
    register_encounter(stack)
    screen_encounter(stack)

    resp = api.exam_encounter(
        stack.enc_id,
        {
            "performing_staff_id": stack.dentist_id,
            "exam_modality": "TELEDENTISTRY",
            "teledentistry_reviewed_at": "2026-05-14T10:00:00Z",
        },
        stack.dentist_headers,
    )
    validate_error(resp, ApiErrorId.ERR_TELEDENTISTRY_REVIEW_WINDOW.value, 422)

    assert validate_success(api.get_encounter(stack.enc_id, ADMIN))["clinical_status"] == "SCREENED"
    assert list_encounter_procedures(stack.enc_id, {"procedure_code": "D0150"}) == [], (
        "A refused exam must auto-create no D0150 row"
    )


def test_registering_with_another_patients_consent_is_refused(api):
    """PRD §2.6: "The consent cited on an encounter registration must belong to the same
    patient as the encounter, and to the same site as the visit — its `patient_id` must equal
    the encounter's `patient_id`, and its `site_id` must equal the visit's `site_id`."

    Design: Corner/validations/registering_an_encounter_with_another_patients_consent_returns_consent_missing
    """
    stack = setup_program_site_and_staff(clock="2026-05-11T09:00:00Z")
    setup_visit_in_progress(stack)
    other = build_patient(
        stack.site_id, stack.coord_headers, external_ref="S-002",
        first_name="Noah", last_name="Park", date_of_birth="2015-11-20", household_size=3,
    )

    resp = api.create_encounter(
        {
            "site_visit_id": stack.visit_id,
            "patient_id": other["id"],
            "consent_id": stack.consent_id,
            "expected_site_visit_version": current_visit_version(stack),
        },
        stack.asst_headers,
    )
    validate_error(resp, ApiErrorId.ERR_CONSENT_MISSING.value, 422)

    rows, _ = validate_paginated(api.list_encounters(ADMIN, params={"patient_id": other["id"]}))
    assert rows == [], "A refused registration must create no Encounter row"
    assert validate_success(api.get_consent(stack.consent_id, ADMIN))["status"] == "ACTIVE"


def test_registering_against_a_revoked_consent_is_refused(api):
    """PRD §2.6: "The cited consent's `status` is neither `REVOKED` nor `SUPERSEDED`."
    PRD §3.2: "It can be **revoked** by a coordinator or administrator, which stamps
    `revoked_at` with the logical clock instant, records the supplied `revoke_reason`, and —
    this is the part that matters clinically — reaches into every encounter that cites this
    consent and moves every procedure still in `PLANNED` to `INELIGIBLE`, releasing each one's
    `chair_minutes` back to its site visit's `booked_chair_minutes`."

    Design: Corner/validations/registering_an_encounter_against_a_revoked_consent_is_refused
    """
    stack = setup_program_site_and_staff(clock="2026-05-11T09:00:00Z")
    setup_visit_in_progress(stack)
    validate_success(
        api.revoke_consent(stack.consent_id, {"revoke_reason": "GUARDIAN_WITHDREW"}, stack.coord_headers)
    )

    resp = api.create_encounter(
        {
            "site_visit_id": stack.visit_id,
            "patient_id": stack.patient_id,
            "consent_id": stack.consent_id,
            "expected_site_visit_version": current_visit_version(stack),
        },
        stack.asst_headers,
    )
    validate_error(resp, ApiErrorId.ERR_CONSENT_REVOKED.value, 409)

    consent = validate_success(api.get_consent(stack.consent_id, ADMIN))
    assert consent["status"] == "REVOKED"
    assert consent["revoke_reason"] == "GUARDIAN_WITHDREW"
    rows, _ = validate_paginated(api.list_encounters(ADMIN, params={"patient_id": stack.patient_id}))
    assert rows == [], "A refused registration must create no Encounter row"


def test_expiry_sweep_commits_once_then_the_repeat_writes_nothing(api):
    """PRD §2.8: "When an endpoint cites a consent whose `status` is `PENDING_VERIFICATION` or
    `ACTIVE` and whose `expires_at` has been reached by the logical clock, the consent row is
    first written to `EXPIRED`, `expired_at` is stamped with the logical clock instant, and
    `Consent.version` is incremented by 1 — and the triggering request is **then** refused
    with `ERR_CONSENT_EXPIRED`."
    PRD §2.8: "When the cited consent is **already** in status `EXPIRED`, the same
    `ERR_CONSENT_EXPIRED` is returned with no write whatsoever: `expired_at` keeps whatever
    value it already had and `Consent.version` does not change."

    Design: Corner/validations/expired_consent_is_persisted_then_the_request_is_refused_and_a_repeat_writes_nothing
    """
    stack = setup_program_site_and_staff(clock="2026-05-11T09:00:00Z")
    setup_visit_in_progress(stack)
    consent_v1 = validate_success(api.get_consent(stack.consent_id, ADMIN))["version"]
    visit_version = current_visit_version(stack)
    set_clock("2026-07-01T09:00:00Z")

    payload = {
        "site_visit_id": stack.visit_id,
        "patient_id": stack.patient_id,
        "consent_id": stack.consent_id,
        "expected_site_visit_version": visit_version,
    }
    validate_error(
        api.create_encounter(payload, stack.asst_headers),
        ApiErrorId.ERR_CONSENT_EXPIRED.value, 409,
    )
    swept = validate_success(api.get_consent(stack.consent_id, ADMIN))
    assert swept["status"] == "EXPIRED"
    assert_same_instant(swept["expired_at"], "2026-07-01T09:00:00Z", "expired_at")
    assert swept["version"] == consent_v1 + 1

    validate_error(
        api.create_encounter(payload, stack.asst_headers),
        ApiErrorId.ERR_CONSENT_EXPIRED.value, 409,
    )
    again = validate_success(api.get_consent(stack.consent_id, ADMIN))
    assert again["version"] == consent_v1 + 1, "The second touch must write nothing"
    assert_same_instant(again["expired_at"], "2026-07-01T09:00:00Z", "expired_at unchanged")

    rows, _ = validate_paginated(api.list_encounters(ADMIN, params={"patient_id": stack.patient_id}))
    assert rows == [], "Neither refused registration may create an Encounter row"


def test_billing_specialist_may_not_screen_an_encounter(api):
    """PRD §2.1: "A `BillingSpecialist` owns coverage verification and the entire billing axis
    and cannot touch the clinical axis at all."
    PRD §2.6: "The acting role appears in the authorised-role list for the endpoint being
    called, as tabulated in §4."

    Design: Corner/rbac/billing_specialist_cannot_screen_an_encounter
    """
    stack = setup_program_site_and_staff(clock="2026-05-11T09:00:00Z")
    setup_visit_in_progress(stack)
    register_encounter(stack)

    resp = api.screen_encounter(
        stack.enc_id,
        {
            "performing_staff_id": stack.hyg_id,
            "cavitated_lesion_count": 1,
            "pain_reported": False,
            "abscess_or_swelling": False,
            "untreated_decay_present": True,
        },
        stack.billing_headers,
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value, 403)

    encounter = validate_success(api.get_encounter(stack.enc_id, ADMIN))
    assert encounter["clinical_status"] == "REGISTERED"
    assert encounter["triage_band"] is None
    assert list_encounter_procedures(stack.enc_id) == [], "A refused screen auto-creates nothing"
