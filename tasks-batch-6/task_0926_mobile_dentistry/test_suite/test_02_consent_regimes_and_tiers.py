"""The two consent regimes, their expiry arithmetic, and the tier-amendment cascade."""

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_consent,
    assert_same_instant,
    build_patient,
    build_program_period,
    build_school_consent,
    build_site,
    build_snf_consent,
    current_patient_version,
    exam_encounter,
    get_success_data,
    make_program_admin_headers,
    make_site_coordinator_headers,
    parse_instant,
    plan_procedure,
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


def _two_regime_fixture():
    """One SCHOOL site with a student and one SNF site with a capable resident."""
    set_clock("2026-05-11T09:00:00Z")
    period = build_program_period()
    school = build_site(site_type="SCHOOL")
    snf = build_site(site_type="SNF", roster_disclosure_level="CLINICAL_DETAIL")
    school_coord = make_site_coordinator_headers(school["id"])
    snf_coord = make_site_coordinator_headers(snf["id"])
    student = build_patient(school["id"], school_coord, external_ref="S-001")
    resident = build_patient(
        snf["id"], snf_coord, patient_type="RESIDENT", external_ref="R-001",
        first_name="Alma", last_name="Reyes", date_of_birth="1941-09-12",
        room_number="214B", household_size=1, capacity_determination="HAS_CAPACITY",
    )
    return period, school, snf, school_coord, snf_coord, student, resident


def test_school_consent_expiry_is_pinned_to_the_period_end_and_ignores_signed_at(api):
    """PRD §3.2: "For a `SCHOOL_GUARDIAN` consent, `expires_at` is the last moment of the
    programme period: the period's `ends_on` date at 23:59:59 UTC, rendered as `expires_at`
    with three fractional digits — and `reaffirmation_due_at` is null, because a school
    consent is not reaffirmed, it simply ends with the school year."
    PRD §3.2: "A `SiteCoordinator` or `ProgramAdmin` moves a consent from
    `PENDING_VERIFICATION` to `ACTIVE`, which recomputes `expires_at` and
    `reaffirmation_due_at` under the regime rule above."

    Design: Difficulty/dual_variant_calc/school_year_scoped_vs_snf_annual_reaffirmation_consent_expiry
    """
    period, school, _snf, school_coord, _snf_coord, student, _resident = _two_regime_fixture()
    created = validate_success(
        api.create_consent(
            {
                "patient_id": student["id"],
                "site_id": school["id"],
                "program_period_id": period["id"],
                "regime": "SCHOOL_GUARDIAN",
                "scope_tier": "SCREENING_FLUORIDE",
                "signed_at": "2026-05-01T00:00:00Z",
                "guardian_name": "Rosa Lopez",
                "guardian_relationship": "MOTHER",
            },
            school_coord,
        ),
        201,
    )
    consent = validate_success(api.verify_consent(created["id"], school_coord))
    assert_consent(consent)
    assert consent["status"] == "ACTIVE"
    assert_same_instant(consent["expires_at"], "2026-06-30T23:59:59Z", "school consent expires_at")
    assert consent["reaffirmation_due_at"] is None, (
        f"A school consent is not reaffirmed; got {consent['reaffirmation_due_at']}"
    )


def test_snf_consent_expiry_runs_365_days_from_signing_and_mirrors_reaffirmation(api):
    """PRD §3.2: "For an `SNF_RESPONSIBLE_PARTY` consent, `expires_at` is `signed_at`
    advanced by exactly 365 calendar days, preserving the time of day, and
    `reaffirmation_due_at` is set to the identical instant."
    PRD §3.2: "This expiry is entirely independent of the programme period; the
    nursing-facility consent is a standing authorisation with an annual reaffirmation clock."

    Design: Difficulty/dual_variant_calc/school_year_scoped_vs_snf_annual_reaffirmation_consent_expiry
    """
    period, school, snf, school_coord, snf_coord, student, resident = _two_regime_fixture()
    school_consent = build_school_consent(
        student["id"], school["id"], period["id"], school_coord, signed_at="2026-05-01T00:00:00Z"
    )
    snf_created = validate_success(
        api.create_consent(
            {
                "patient_id": resident["id"],
                "site_id": snf["id"],
                "program_period_id": period["id"],
                "regime": "SNF_RESPONSIBLE_PARTY",
                "scope_tier": "SCREENING_FLUORIDE",
                "signed_at": "2026-05-01T00:00:00Z",
                "responsible_party_name": "Tomas Reyes",
                "responsible_party_authority": "DURABLE_POA",
                "poa_document_ref": "POA-2019-118",
            },
            snf_coord,
        ),
        201,
    )
    snf_consent = validate_success(api.verify_consent(snf_created["id"], snf_coord))
    assert snf_consent["status"] == "ACTIVE"
    assert_same_instant(snf_consent["expires_at"], "2027-05-01T00:00:00Z", "snf consent expires_at")
    assert_same_instant(
        snf_consent["reaffirmation_due_at"], "2027-05-01T00:00:00Z", "snf reaffirmation_due_at"
    )
    # Byte-identical signed_at, different regimes, different expiries — compared as instants.
    assert parse_instant(school_consent["expires_at"]) != parse_instant(snf_consent["expires_at"]), (
        "The two regimes must not land on the same expiry instant"
    )


def test_reaffirming_an_active_snf_consent_slides_the_expiry_forward(api):
    """PRD §3.2: "a consent already in `ACTIVE` whose `regime` is `SNF_RESPONSIBLE_PARTY` can
    be verified again, which resets `signed_at` to the logical clock instant, slides
    `expires_at` forward another 365 days from that new signing instant, mirrors the result
    into `reaffirmation_due_at`, and leaves the consent in `ACTIVE`."

    Design: Difficulty/non_linear_state_machine/snf_consent_reaffirmation_self_loop_slides_expiry_forward
    """
    set_clock("2026-05-11T09:00:00Z")
    period = build_program_period()
    snf = build_site(site_type="SNF", roster_disclosure_level="CLINICAL_DETAIL")
    coord = make_site_coordinator_headers(snf["id"])
    resident = build_patient(
        snf["id"], coord, patient_type="RESIDENT", external_ref="R-001",
        first_name="Alma", last_name="Reyes", date_of_birth="1941-09-12",
        room_number="214B", household_size=1, capacity_determination="HAS_CAPACITY",
    )
    consent = build_snf_consent(resident["id"], snf["id"], period["id"], coord,
                                signed_at="2026-05-01T00:00:00Z")
    assert_same_instant(consent["expires_at"], "2027-05-01T00:00:00Z", "first expires_at")

    set_clock("2027-04-20T09:00:00Z")
    reaffirmed = validate_success(api.verify_consent(consent["id"], coord))
    assert reaffirmed["status"] == "ACTIVE"
    assert_same_instant(reaffirmed["signed_at"], "2027-04-20T09:00:00Z", "reaffirmed signed_at")
    assert_same_instant(reaffirmed["expires_at"], "2028-04-19T09:00:00Z", "reaffirmed expires_at")
    assert_same_instant(
        reaffirmed["reaffirmation_due_at"], "2028-04-19T09:00:00Z", "reaffirmed reaffirmation_due_at"
    )


def test_reaffirmation_self_loop_does_not_expire_the_consent(api):
    """PRD §2.8: "When the cited consent is **already** in status `EXPIRED`, the same
    `ERR_CONSENT_EXPIRED` is returned with no write whatsoever: `expired_at` keeps whatever
    value it already had and `Consent.version` does not change."
    PRD §3.2: "a consent already in `ACTIVE` whose `regime` is `SNF_RESPONSIBLE_PARTY` can be
    verified again, which resets `signed_at` to the logical clock instant, slides `expires_at`
    forward another 365 days from that new signing instant, mirrors the result into
    `reaffirmation_due_at`, and leaves the consent in `ACTIVE`."

    Design: Difficulty/non_linear_state_machine/snf_consent_reaffirmation_self_loop_slides_expiry_forward
    """
    set_clock("2026-05-11T09:00:00Z")
    period = build_program_period()
    snf = build_site(site_type="SNF", roster_disclosure_level="CLINICAL_DETAIL")
    coord = make_site_coordinator_headers(snf["id"])
    resident = build_patient(
        snf["id"], coord, patient_type="RESIDENT", external_ref="R-001",
        first_name="Alma", last_name="Reyes", date_of_birth="1941-09-12",
        room_number="214B", household_size=1, capacity_determination="HAS_CAPACITY",
    )
    consent = build_snf_consent(resident["id"], snf["id"], period["id"], coord,
                                signed_at="2026-05-01T00:00:00Z")
    version_before = consent["version"]

    set_clock("2027-04-20T09:00:00Z")
    reaffirmed = validate_success(api.verify_consent(consent["id"], coord))
    assert reaffirmed["expired_at"] is None, "A reaffirmed consent has never expired"
    assert reaffirmed["status"] == "ACTIVE"
    assert reaffirmed["version"] == version_before + 1, (
        "Verifying a consent increments Consent.version by exactly 1"
    )


def test_reverifying_an_active_school_consent_is_refused_by_the_state_gate(api):
    """PRD §3.2: "the `ACTIVE → ACTIVE` transition is declared only for the nursing-facility
    regime, so a school consent presented for reaffirmation is refused by the state gate with
    `ERR_INVALID_STATE`."

    Design: Corner/state_machines/reverifying_an_active_school_guardian_consent_returns_invalid_state
    """
    set_clock("2026-05-11T09:00:00Z")
    period = build_program_period()
    school = build_site(site_type="SCHOOL")
    coord = make_site_coordinator_headers(school["id"])
    student = build_patient(school["id"], coord, external_ref="S-001")
    consent = build_school_consent(student["id"], school["id"], period["id"], coord,
                                   signed_at="2026-05-01T00:00:00Z")
    version_before = consent["version"]

    resp = api.verify_consent(consent["id"], coord)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)

    after = validate_success(api.get_consent(consent["id"], ADMIN))
    assert after["status"] == "ACTIVE"
    assert_same_instant(after["signed_at"], "2026-05-01T00:00:00Z", "signed_at unchanged")
    assert_same_instant(after["expires_at"], "2026-06-30T23:59:59Z", "expires_at unchanged")
    assert after["version"] == version_before, "A refused verify writes nothing"


def test_consent_with_an_off_enum_scope_tier_is_refused_as_an_enum_violation(api):
    """PRD §2.6: "Exactly the following request fields route an off-enum value to
    `ERR_INVALID_ENUM`: a site's `site_type` and `roster_disclosure_level`; a site hold's
    `hold_type`; a patient's `patient_type` and `capacity_determination`; a consent's
    `regime`, `scope_tier` and `responsible_party_authority`;"
    PRD §2.6: "`SCREENING_ONLY`, `SCREENING_FLUORIDE`, `SCREENING_FLUORIDE_SEALANT` or
    `FULL_WITH_RADIOGRAPHS` (both for `scope_tier` and for `new_scope_tier`)"

    Design: Corner/entities/consent_create_with_invalid_scope_tier_returns_invalid_enum
    """
    set_clock("2026-05-11T09:00:00Z")
    period = build_program_period()
    school = build_site(site_type="SCHOOL")
    coord = make_site_coordinator_headers(school["id"])
    student = build_patient(school["id"], coord, external_ref="S-001")

    resp = api.create_consent(
        {
            "patient_id": student["id"],
            "site_id": school["id"],
            "program_period_id": period["id"],
            "regime": "SCHOOL_GUARDIAN",
            "scope_tier": "FULL",
            "signed_at": "2026-05-01T00:00:00Z",
            "guardian_name": "Rosa Lopez",
            "guardian_relationship": "MOTHER",
        },
        coord,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_ENUM.value, 400)
    rows, _ = validate_paginated(api.list_consents(ADMIN, params={"patient_id": student["id"]}))
    assert rows == [], "A refused create must leave no Consent row behind"


def test_school_consent_missing_its_signer_fields_returns_regime_fields_error(api):
    """PRD §2.6: "A `SCHOOL_GUARDIAN` consent requires both `guardian_name` and
    `guardian_relationship`, and must not carry `responsible_party_name`."
    PRD §3.2: "Every one of those completeness failures is `ERR_CONSENT_REGIME_FIELDS`; a
    `site_id` that does not match the patient's site is `ERR_VALIDATION`."

    Design: Corner/validations/school_consent_without_guardian_fields_returns_regime_fields_error
    """
    set_clock("2026-05-11T09:00:00Z")
    period = build_program_period()
    school = build_site(site_type="SCHOOL")
    coord = make_site_coordinator_headers(school["id"])
    student = build_patient(school["id"], coord, external_ref="S-001")

    resp = api.create_consent(
        {
            "patient_id": student["id"],
            "site_id": school["id"],
            "program_period_id": period["id"],
            "regime": "SCHOOL_GUARDIAN",
            "scope_tier": "SCREENING_FLUORIDE",
            "signed_at": "2026-05-01T00:00:00Z",
        },
        coord,
    )
    validate_error(resp, ApiErrorId.ERR_CONSENT_REGIME_FIELDS.value, 400)
    rows, _ = validate_paginated(api.list_consents(ADMIN, params={"patient_id": student["id"]}))
    assert rows == [], "A refused create must leave no Consent row behind"


def test_verifying_an_snf_consent_needs_a_capacity_determination(api):
    """PRD §2.6: "Verifying a consent whose `regime` is `SNF_RESPONSIBLE_PARTY` requires the
    patient's `capacity_determination` to be `HAS_CAPACITY` or `LACKS_CAPACITY`;
    `NOT_ASSESSED` is refused."

    Design: Corner/validations/snf_consent_verify_without_capacity_determination_is_refused
    """
    set_clock("2026-05-11T09:00:00Z")
    period = build_program_period()
    snf = build_site(site_type="SNF")
    coord = make_site_coordinator_headers(snf["id"])
    resident = build_patient(
        snf["id"], coord, patient_type="RESIDENT", external_ref="R-001",
        first_name="Alma", last_name="Reyes", date_of_birth="1941-09-12",
        room_number="214B", household_size=1,
    )
    consent = build_snf_consent(resident["id"], snf["id"], period["id"], coord, verify=False)

    resp = api.verify_consent(consent["id"], coord)
    validate_error(resp, ApiErrorId.ERR_CAPACITY_DETERMINATION_REQUIRED.value, 422)

    assert validate_success(api.get_consent(consent["id"], ADMIN))["status"] == "PENDING_VERIFICATION"
    assert validate_success(api.get_patient(resident["id"], ADMIN))["capacity_determination"] == "NOT_ASSESSED"


def test_amend_tier_returns_the_replacement_and_supersedes_the_old_row_immediately(api):
    """PRD §3.2: "A brand-new `Consent` row is created in `ACTIVE` at the new tier, copying
    the original's `patient_id`, `site_id`, `program_period_id`, `regime`, whichever signer
    fields that regime owns, and `signed_at`; its `expires_at` and `reaffirmation_due_at` are
    computed from those copied values by the same regime rule."
    PRD §3.2: "The replacement consent is what the caller receives back, with HTTP 201."
    PRD §3.2: "The `Patient` row's `version` is incremented, which is what makes a second
    concurrent amendment fail its own version check."

    Design: Corner/consistency_model/amend_tier_response_already_shows_the_replacement_and_the_old_row_is_superseded
    """
    set_clock("2026-05-11T09:00:00Z")
    period = build_program_period()
    school = build_site(site_type="SCHOOL")
    coord = make_site_coordinator_headers(school["id"])
    student = build_patient(school["id"], coord, external_ref="S-001")
    old = build_school_consent(student["id"], school["id"], period["id"], coord,
                               scope_tier="SCREENING_FLUORIDE_SEALANT")
    patient_v1 = validate_success(api.get_patient(student["id"], ADMIN))["version"]

    resp = api.amend_consent_tier(
        old["id"],
        {
            "new_scope_tier": "SCREENING_ONLY",
            "expected_patient_version": patient_v1,
            "amend_reason": "GUARDIAN_NARROWED_SCOPE",
        },
        coord,
    )
    replacement = validate_success(resp, 201)
    assert replacement["status"] == "ACTIVE"
    assert replacement["scope_tier"] == "SCREENING_ONLY"
    assert_same_instant(replacement["expires_at"], "2026-06-30T23:59:59Z", "replacement expires_at")

    old_after = validate_success(api.get_consent(old["id"], ADMIN))
    assert old_after["status"] == "SUPERSEDED"
    assert old_after["superseded_by_consent_id"] == replacement["id"]
    assert validate_success(api.get_patient(student["id"], ADMIN))["version"] == patient_v1 + 1


def test_superseded_consent_is_reachable_through_the_superseded_by_filter(api):
    """PRD §3.2: "The old row moves to `SUPERSEDED` and its `superseded_by_consent_id` is set
    to the replacement's `id`, which is also the value a caller can filter the consent list by
    in order to find the row a given consent replaced."

    Design: Corner/entities/superseded_consent_is_discoverable_through_the_superseded_by_filter
    """
    set_clock("2026-05-11T09:00:00Z")
    period = build_program_period()
    school = build_site(site_type="SCHOOL")
    coord = make_site_coordinator_headers(school["id"])
    student = build_patient(school["id"], coord, external_ref="S-001")
    old = build_school_consent(student["id"], school["id"], period["id"], coord,
                               scope_tier="SCREENING_FLUORIDE_SEALANT")
    patient_v1 = validate_success(api.get_patient(student["id"], ADMIN))["version"]
    replacement = validate_success(
        api.amend_consent_tier(
            old["id"],
            {"new_scope_tier": "SCREENING_ONLY", "expected_patient_version": patient_v1},
            coord,
        ),
        201,
    )

    rows, _ = validate_paginated(
        api.list_consents(ADMIN, params={"superseded_by_consent_id": replacement["id"]})
    )
    assert len(rows) == 1, f"Expected exactly the superseded row, got {len(rows)}"
    assert rows[0]["id"] == old["id"]
    assert rows[0]["status"] == "SUPERSEDED"
    assert rows[0]["superseded_by_consent_id"] == replacement["id"]
    assert replacement["scope_tier"] == "SCREENING_ONLY"


def _downgrade_fixture():
    """Screened + examined encounter with one PLANNED D1351 and one ACTIVE plan."""
    stack = setup_program_site_and_staff(clock="2026-05-11T09:00:00Z")
    setup_visit_in_progress(stack, scope_tier="SCREENING_FLUORIDE_SEALANT")
    register_encounter(stack)
    screen_encounter(stack)
    exam_encounter(stack)
    sealant = plan_procedure(stack, "D1351", tooth_number=3, surface="O")
    plan = get_success_data(
        api_client.create_treatment_plan(
            {
                "encounter_id": stack.enc_id,
                "patient_id": stack.patient_id,
                "authoring_staff_id": stack.dentist_id,
                "planned_procedure_codes": ["D1351"],
            },
            stack.dentist_headers,
        )
    )
    plan = get_success_data(api_client.activate_treatment_plan(plan["id"], stack.dentist_headers))
    stack.sealant_id = sealant["id"]
    stack.plan_id = plan["id"]
    stack.patient_v1 = current_patient_version(stack)
    return stack


def test_tier_downgrade_invalidates_the_over_tier_procedure_and_frees_its_chair_minutes(api):
    """PRD §3.2: "Link two, caused by link one, walks every encounter that cites the
    superseded consent and moves every procedure still in `PLANNED` whose `required_tier`
    outranks the new tier into `INELIGIBLE`, stamping each one's `void_reason` with the
    literal `CONSENT_TIER_DOWNGRADE`; the number of procedures moved is recorded on the
    **old** consent row as `invalidated_procedure_count`."
    PRD §3.2: "Link three, caused by link two, credits each released `chair_minutes` back to
    the owning site visit's `booked_chair_minutes`"

    Design: Difficulty/transitive_cascade/consent_tier_downgrade_depth_three_cascade_defers_encounter_and_cancels_plan
    """
    stack = _downgrade_fixture()
    before = validate_success(api.get_site_visit(stack.visit_id, ADMIN))
    assert before["booked_chair_minutes"] == 37, (
        f"Screen 10 + exam 15 + sealant 12 = 37, got {before['booked_chair_minutes']}"
    )

    replacement = validate_success(
        api.amend_consent_tier(
            stack.consent_id,
            {
                "new_scope_tier": "SCREENING_FLUORIDE",
                "expected_patient_version": stack.patient_v1,
                "amend_reason": "GUARDIAN_WITHDREW_SEALANT_CONSENT",
            },
            stack.coord_headers,
        ),
        201,
    )

    old = validate_success(api.get_consent(stack.consent_id, ADMIN))
    assert old["status"] == "SUPERSEDED"
    assert old["superseded_by_consent_id"] == replacement["id"]
    assert old["invalidated_procedure_count"] == 1
    assert replacement["status"] == "ACTIVE"
    assert replacement["scope_tier"] == "SCREENING_FLUORIDE"
    assert_same_instant(replacement["expires_at"], "2026-06-30T23:59:59Z", "replacement expires_at")

    sealant = validate_success(api.get_procedure(stack.sealant_id, ADMIN))
    assert sealant["status"] == "INELIGIBLE"
    assert sealant["void_reason"] == "CONSENT_TIER_DOWNGRADE"

    after = validate_success(api.get_site_visit(stack.visit_id, ADMIN))
    assert after["booked_chair_minutes"] == 25, (
        f"12 sealant minutes must be credited back, got {after['booked_chair_minutes']}"
    )


def test_tier_downgrade_defers_the_stripped_encounter_and_cancels_its_active_plan(api):
    """PRD §3.2: "then, for any encounter that link two has stripped down to no remaining
    procedures beyond the automatically-created screening and exam rows and whose
    `clinical_status` is `EXAMINED` or `TREATED`, the encounter moves to `DEFERRED` with
    `deferred_reason` set to `CONSENT_TIER_DOWNGRADE`, and any treatment plan on that
    encounter still in `plan_status` `ACTIVE` moves to `CANCELLED` with `superseded_reason`
    set to `CONSENT_TIER_DOWNGRADE` and `follow_up_due_date` cleared to null."
    PRD §2.11: "increments `Patient.version` by exactly 1"

    Design: Difficulty/transitive_cascade/consent_tier_downgrade_depth_three_cascade_defers_encounter_and_cancels_plan
    """
    stack = _downgrade_fixture()
    validate_success(
        api.amend_consent_tier(
            stack.consent_id,
            {
                "new_scope_tier": "SCREENING_FLUORIDE",
                "expected_patient_version": stack.patient_v1,
                "amend_reason": "GUARDIAN_WITHDREW_SEALANT_CONSENT",
            },
            stack.coord_headers,
        ),
        201,
    )

    encounter = validate_success(api.get_encounter(stack.enc_id, ADMIN))
    assert encounter["clinical_status"] == "DEFERRED"
    assert encounter["deferred_reason"] == "CONSENT_TIER_DOWNGRADE"

    plan = validate_success(api.get_treatment_plan(stack.plan_id, ADMIN))
    assert plan["plan_status"] == "CANCELLED"
    assert plan["superseded_reason"] == "CONSENT_TIER_DOWNGRADE"
    assert plan["follow_up_due_date"] is None

    patient = validate_success(api.get_patient(stack.patient_id, ADMIN))
    assert patient["version"] == stack.patient_v1 + 1
