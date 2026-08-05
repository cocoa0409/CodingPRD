"""Optimistic concurrency on parent rows, and the strict ordering of the validation ladder."""

from test_helpers import (
    ApiErrorId,
    api_client,
    build_patient,
    build_program_period,
    build_school_consent,
    build_site,
    current_encounter_version,
    get_success_data,
    list_encounter_procedures,
    make_program_admin_headers,
    make_site_coordinator_headers,
    register_encounter,
    set_clock,
    setup_screened_and_examined,
    setup_treated_encounter_with_varnish,
    setup_program_site_and_staff,
    setup_visit_in_progress,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = make_program_admin_headers()


def test_a_stale_patient_version_rejects_a_second_consent_amendment(api):
    """PRD §2.9: "**Amending a consent's scope tier** must carry `expected_patient_version`,
    matching the current `version` of the `Patient` the consent belongs to."
    PRD §2.9: "A mismatch yields `ERR_STALE_VERSION` (412)."

    Design: Corner/cross_cutting_complexity_layers/stale_patient_version_rejects_a_second_consent_amendment
    """
    set_clock("2026-05-11T09:00:00Z")
    period = build_program_period()
    site = build_site()
    coord = make_site_coordinator_headers(site["id"])
    patient = build_patient(site["id"], coord, external_ref="S-001")
    consent1 = build_school_consent(patient["id"], site["id"], period["id"], coord,
                                    scope_tier="SCREENING_FLUORIDE_SEALANT")
    patient_v1 = validate_success(api.get_patient(patient["id"], ADMIN))["version"]
    consent2 = validate_success(
        api.amend_consent_tier(
            consent1["id"],
            {"new_scope_tier": "SCREENING_FLUORIDE", "expected_patient_version": patient_v1},
            coord,
        ),
        201,
    )

    resp = api.amend_consent_tier(
        consent2["id"],
        {"new_scope_tier": "SCREENING_ONLY", "expected_patient_version": patient_v1},
        coord,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value, 412)

    after = validate_success(api.get_consent(consent2["id"], ADMIN))
    assert after["status"] == "ACTIVE"
    assert after["scope_tier"] == "SCREENING_FLUORIDE"
    assert after["superseded_by_consent_id"] is None
    rows, _ = validate_paginated(api.list_consents(ADMIN, params={"patient_id": patient["id"]}))
    assert len(rows) == 2, f"No third consent may be minted, got {len(rows)}"


def test_a_stale_site_visit_version_rejects_a_second_registration(api):
    """PRD §2.9: "**Registering an encounter** must carry `expected_site_visit_version`,
    matching the current `version` of the `SiteVisit`."
    PRD §2.9: "if another registration or a reschedule has moved the capacity picture since
    that read, the create is refused with `ERR_STALE_VERSION` (412)."

    Design: Corner/cross_cutting_complexity_layers/stale_site_visit_version_rejects_a_second_encounter_registration
    """
    stack = setup_program_site_and_staff(clock="2026-05-11T09:00:00Z")
    setup_visit_in_progress(stack)
    visit_v1 = stack.visit_version
    patient2 = build_patient(
        stack.site_id, stack.coord_headers, external_ref="S-002", first_name="Noah",
        last_name="Park", date_of_birth="2015-11-20", household_size=3,
    )
    consent2 = build_school_consent(
        patient2["id"], stack.site_id, stack.pp_id, stack.coord_headers, guardian_name="Ivy Park"
    )
    register_encounter(stack, expected_site_visit_version=visit_v1)

    resp = api.create_encounter(
        {
            "site_visit_id": stack.visit_id,
            "patient_id": patient2["id"],
            "consent_id": consent2["id"],
            "expected_site_visit_version": visit_v1,
        },
        stack.asst_headers,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value, 412)

    on_visit, _ = validate_paginated(
        api.list_encounters(ADMIN, params={"site_visit_id": stack.visit_id})
    )
    assert len(on_visit) == 1, f"Only the first registration may survive, got {len(on_visit)}"
    for_patient2, _ = validate_paginated(
        api.list_encounters(ADMIN, params={"patient_id": patient2["id"]})
    )
    assert for_patient2 == []
    assert validate_success(api.get_site_visit(stack.visit_id, ADMIN))["version"] == visit_v1 + 1


def test_a_stale_encounter_version_rejects_a_second_procedure_plan(api):
    """PRD §2.9: "**Planning a procedure** must carry `expected_encounter_version`, matching
    the current `version` of the `Encounter`."
    PRD §2.9: "if the consent has been amended, a sibling procedure has been planned, or the
    encounter has been repriced since that read, the create is refused with
    `ERR_STALE_VERSION` (412)."
    PRD §2.11: "**Planning a procedure** mints the `Procedure` at `version` 1 and increments
    `Encounter.version` by exactly 1."

    Design: Corner/cross_cutting_complexity_layers/stale_encounter_version_rejects_a_second_procedure_plan
    """
    stack = setup_screened_and_examined(scope_tier="SCREENING_FLUORIDE_SEALANT")
    enc_v1 = current_encounter_version(stack)
    validate_success(
        api.create_procedure(
            {
                "encounter_id": stack.enc_id,
                "procedure_code": "D1206",
                "expected_encounter_version": enc_v1,
            },
            stack.hyg_headers,
        ),
        201,
    )

    resp = api.create_procedure(
        {
            "encounter_id": stack.enc_id,
            "procedure_code": "D1351",
            "tooth_number": 3,
            "surface": "O",
            "expected_encounter_version": enc_v1,
        },
        stack.hyg_headers,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value, 412)

    rows = list_encounter_procedures(stack.enc_id)
    assert len(rows) == 3, f"Expected the two auto rows plus the varnish, got {len(rows)}"
    visit = validate_success(api.get_site_visit(stack.visit_id, ADMIN))
    assert visit["booked_chair_minutes"] == 33, "The refused plan books no chair minutes"
    assert validate_success(api.get_encounter(stack.enc_id, ADMIN))["version"] == enc_v1 + 1


def _already_priced_with_lapsed_coverage_fixture():
    """A PRICED encounter whose Medicaid coverage fell behind the clock after pricing."""
    stack = setup_treated_encounter_with_varnish(
        payer_type="MEDICAID_MCO", coverage_overrides={"verified_through_date": "2026-05-31"}
    )
    get_success_data(api_client.price_encounter(stack.enc_id, {}, stack.billing_headers))
    stack.cov_v1 = get_success_data(api_client.get_coverage(stack.cov_id, ADMIN))["version"]
    set_clock("2026-06-15T09:00:00Z")
    return stack


def test_the_state_rung_pre_empts_the_coverage_expiry_sweep(api):
    """PRD §2.6: "This ordering is a requirement in its own right — when two conditions are
    simultaneously wrong on the same request, the error that surfaces is always the one
    belonging to the lower-numbered rung, and an implementation that reports the other one is
    incorrect even though both conditions genuinely hold."
    PRD §3.6: "Pricing requires the encounter's `clinical_status` to be `EXAMINED`, `TREATED`
    or `CLOSED`, its `billing_status` to be `UNBILLED`, its `tainted_procedure_count` to be
    zero, and its cited coverage to be `VERIFIED`."

    Design: Difficulty/priority_pair_validation_conflict/invalid_state_beats_coverage_expiry_sweep_on_second_price
    """
    stack = _already_priced_with_lapsed_coverage_fixture()
    resp = api.price_encounter(stack.enc_id, {}, stack.billing_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)

    encounter = validate_success(api.get_encounter(stack.enc_id, ADMIN))
    assert encounter["billing_status"] == "PRICED"
    assert encounter["total_charge_cents"] == 15025


def test_the_pre_empted_sweep_leaves_the_coverage_untouched(api):
    """PRD §2.8: "When an encounter is priced and the cited coverage's `verification_status`
    is `VERIFIED` but its `verified_through_date` is strictly earlier than the logical clock
    date, the coverage is first written to `EXPIRED` and `Coverage.version` is incremented by
    1; the pricing request is **then** refused with `ERR_COVERAGE_UNVERIFIED`."
    PRD §2.6: "rungs are evaluated from 1 upward, the first rung whose check fails decides the
    response, and no later rung runs."

    Design: Difficulty/priority_pair_validation_conflict/invalid_state_beats_coverage_expiry_sweep_on_second_price
    """
    stack = _already_priced_with_lapsed_coverage_fixture()
    validate_error(
        api.price_encounter(stack.enc_id, {}, stack.billing_headers),
        ApiErrorId.ERR_INVALID_STATE.value, 409,
    )

    coverage = validate_success(api.get_coverage(stack.cov_id, ADMIN))
    assert coverage["verification_status"] == "VERIFIED", (
        "The rung-35 sweep never ran, so the coverage must not have been expired"
    )
    assert coverage["version"] == stack.cov_v1, "A pre-empted sweep writes nothing"
