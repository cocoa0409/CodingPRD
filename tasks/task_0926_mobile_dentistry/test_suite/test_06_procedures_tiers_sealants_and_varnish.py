"""Procedure planning: code tables, consent tiers, sealant eligibility, varnish limits, ledgers."""

from types import SimpleNamespace

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_chair_ledger_matches,
    assert_procedure,
    assert_same_date,
    assert_same_instant,
    current_encounter_version,
    exam_encounter,
    get_success_data,
    list_encounter_procedures,
    make_program_admin_headers,
    perform_procedure,
    plan_procedure,
    read_spore_result,
    register_encounter,
    screen_encounter,
    set_clock,
    setup_program_site_and_staff,
    setup_screened_and_examined,
    setup_visit_in_progress,
    validate_error,
    validate_success,
    build_site_visit,
    build_sterilization_load,
)

ADMIN = make_program_admin_headers()


def test_procedure_attributes_are_fixed_by_the_code_table(api):
    """PRD §3.5: "Five codes are recognised, and each one fixes three attributes from the code
    alone at the moment the row is created — nothing else participates in that lookup, and
    none of the three is ever recomputed afterwards"
    PRD §3.5: "Those values populate `required_tier`, `chair_minutes` and `charge_cents`."
    PRD §3.5: "A planned procedure lands in `status` `PLANNED` with `performed_at`,
    `performing_staff_id`, `sterilization_load_id`, `taint_reason` and `void_reason` all null,
    and immediately books its `chair_minutes` against the visit ledger."

    Design: Corner/entities/procedure_computed_attributes_come_from_the_code_tables_and_ignore_client_input
    """
    stack = setup_screened_and_examined(scope_tier="SCREENING_FLUORIDE_SEALANT")
    resp = api.create_procedure(
        {
            "encounter_id": stack.enc_id,
            "procedure_code": "D1351",
            "tooth_number": 3,
            "surface": "O",
            "expected_encounter_version": current_encounter_version(stack),
        },
        stack.hyg_headers,
    )
    procedure = validate_success(resp, 201)
    assert_procedure(procedure)
    assert procedure["status"] == "PLANNED"
    assert procedure["chair_minutes"] == 12
    assert procedure["charge_cents"] == 6350
    assert procedure["required_tier"] == "SCREENING_FLUORIDE_SEALANT"
    assert procedure["performing_staff_id"] is None

    visit = validate_success(api.get_site_visit(stack.visit_id, ADMIN))
    assert visit["booked_chair_minutes"] == 37, (
        f"Screen 10 + exam 15 + sealant 12 = 37, got {visit['booked_chair_minutes']}"
    )


def test_planning_a_varnish_above_the_consent_tier_is_refused(api):
    """PRD §2.6: "The rank of the procedure's `required_tier` must be less than or equal to
    the rank of the `scope_tier` on the consent the encounter currently cites. The tier
    ranking, from lowest authority to highest, is `SCREENING_ONLY`, then `SCREENING_FLUORIDE`,
    then `SCREENING_FLUORIDE_SEALANT`, then `FULL_WITH_RADIOGRAPHS`."

    Design: Corner/validations/planning_a_varnish_under_a_screening_only_consent_returns_tier_insufficient
    """
    stack = setup_screened_and_examined(scope_tier="SCREENING_ONLY")
    resp = api.create_procedure(
        {
            "encounter_id": stack.enc_id,
            "procedure_code": "D1206",
            "expected_encounter_version": current_encounter_version(stack),
        },
        stack.hyg_headers,
    )
    validate_error(resp, ApiErrorId.ERR_CONSENT_TIER_INSUFFICIENT.value, 422)

    rows = list_encounter_procedures(stack.enc_id)
    assert len(rows) == 2, f"Only the auto-created screening and exam rows may exist, got {len(rows)}"
    visit = validate_success(api.get_site_visit(stack.visit_id, ADMIN))
    assert visit["booked_chair_minutes"] == 25, "A refused plan books no chair minutes"


def test_sealant_on_an_ineligible_tooth_is_refused_while_an_eligible_one_is_accepted(api):
    """PRD §3.5: "A `D1351` must carry both a `tooth_number` and a `surface`; the tooth must
    be one of the eight permanent first and second molars the programme seals — 2, 3, 14, 15,
    18, 19, 30 and 31 in universal numbering — and the surface must be `O`, `B` or `L`."
    PRD §3.5: "Every one of these failures is `ERR_SURFACE_INELIGIBLE`."

    Design: Corner/validations/sealant_on_a_tooth_outside_the_eligible_set_returns_surface_ineligible
    """
    stack = setup_screened_and_examined(scope_tier="SCREENING_FLUORIDE_SEALANT")
    enc_v1 = current_encounter_version(stack)

    refused = api.create_procedure(
        {
            "encounter_id": stack.enc_id,
            "procedure_code": "D1351",
            "tooth_number": 5,
            "surface": "O",
            "expected_encounter_version": enc_v1,
        },
        stack.hyg_headers,
    )
    validate_error(refused, ApiErrorId.ERR_SURFACE_INELIGIBLE.value, 422)

    accepted = api.create_procedure(
        {
            "encounter_id": stack.enc_id,
            "procedure_code": "D1351",
            "tooth_number": 3,
            "surface": "O",
            "expected_encounter_version": enc_v1,
        },
        stack.hyg_headers,
    )
    procedure = validate_success(accepted, 201)
    assert procedure["tooth_number"] == 3
    assert procedure["status"] == "PLANNED"
    visit = validate_success(api.get_site_visit(stack.visit_id, ADMIN))
    assert visit["booked_chair_minutes"] == 37


def test_planning_past_the_chair_capacity_is_refused_but_landing_on_it_is_allowed(api):
    """PRD §3.4: "Booking a procedure whose `chair_minutes` would push `booked_chair_minutes`
    past `capacity_chair_minutes` is refused with `ERR_CHAIR_CAPACITY_EXCEEDED`; landing
    exactly on the capacity is allowed."

    Design: Corner/validations/planning_beyond_the_visits_chair_minute_capacity_is_refused
    """
    stack = setup_program_site_and_staff(clock="2026-05-11T09:00:00Z")
    setup_visit_in_progress(
        stack, scope_tier="SCREENING_FLUORIDE_SEALANT", chair_count=1,
        scheduled_start_at="2026-05-11T09:00:00Z", scheduled_end_at="2026-05-11T09:39:00Z",
    )
    register_encounter(stack)
    screen_encounter(stack)
    exam_encounter(stack)

    visit = validate_success(api.get_site_visit(stack.visit_id, ADMIN))
    assert visit["capacity_chair_minutes"] == 33, (
        f"39 minutes x 1 chair x 0.85 floored is 33, got {visit['capacity_chair_minutes']}"
    )
    enc_v1 = current_encounter_version(stack)

    over = api.create_procedure(
        {
            "encounter_id": stack.enc_id,
            "procedure_code": "D1351",
            "tooth_number": 3,
            "surface": "O",
            "expected_encounter_version": enc_v1,
        },
        stack.hyg_headers,
    )
    validate_error(over, ApiErrorId.ERR_CHAIR_CAPACITY_EXCEEDED.value, 422)

    exact = api.create_procedure(
        {
            "encounter_id": stack.enc_id,
            "procedure_code": "D1206",
            "expected_encounter_version": enc_v1,
        },
        stack.hyg_headers,
    )
    procedure = validate_success(exact, 201)
    assert procedure["chair_minutes"] == 8
    after = validate_success(api.get_site_visit(stack.visit_id, ADMIN))
    assert after["booked_chair_minutes"] == 33, "25 + 8 lands exactly on the capacity"


def _second_varnish_fixture():
    """A patient with last_varnish_date 2026-02-10, and a fresh PLANNED D1206 on a later visit."""
    stack = setup_program_site_and_staff(clock="2026-02-10T09:00:00Z", calibrated_on="2026-01-05")
    setup_visit_in_progress(
        stack, scope_tier="SCREENING_FLUORIDE",
        consent_overrides={"signed_at": "2026-01-05T00:00:00Z"},
        scheduled_start_at="2026-02-10T09:00:00Z", scheduled_end_at="2026-02-10T15:00:00Z",
        load_cycle_completed_at="2026-02-09T08:00:00Z",
    )
    visit_a_id = stack.visit_id
    register_encounter(stack)
    screen_encounter(stack)
    exam_encounter(stack)
    varnish_a = plan_procedure(stack, "D1206")
    perform_procedure(stack, varnish_a["id"])
    get_success_data(api_client.complete_site_visit(visit_a_id, stack.dentist_headers))

    visit_b = build_site_visit(
        stack.site_id, stack.pp_id, stack.unit_id, stack.dentist_id, stack.coord_headers,
        onsite_dentist_staff_id=stack.dentist_id,
        scheduled_start_at="2026-05-11T09:00:00Z", scheduled_end_at="2026-05-11T15:00:00Z",
        chair_count=2,
    )
    set_clock("2026-05-10T09:00:00Z")
    load_b = build_sterilization_load(
        stack.unit_id, stack.asst_id, stack.asst_headers,
        load_number="L-B", cycle_completed_at="2026-05-09T08:00:00Z", site_visit_id=visit_b["id"],
    )
    read_spore_result(load_b["id"], "PASSED", stack.hyg_id, stack.hyg_headers)
    visit_b = get_success_data(api_client.start_site_visit(visit_b["id"], stack.dentist_headers))
    stack.visit_id = visit_b["id"]
    stack.visit_version = visit_b["version"]
    stack.load1_id = load_b["id"]
    register_encounter(stack)
    screen_encounter(stack)
    exam_encounter(stack)
    varnish_b = plan_procedure(stack, "D1206")
    stack.varnish_b_id = varnish_b["id"]
    return stack


def test_varnish_at_eighty_nine_whole_days_is_refused(api):
    """PRD §2.6: "For a `D1206` fluoride varnish, the number of whole calendar days elapsed
    since the patient's `last_varnish_date` must be at least 90. Exactly 90 days elapsed
    passes; 89 fails. A patient with a null `last_varnish_date` passes automatically."

    Design: Difficulty/boundary_precision_check/varnish_interval_eighty_nine_days_fails_and_exactly_ninety_days_passes
    """
    stack = _second_varnish_fixture()
    resp = api.perform_procedure(
        stack.varnish_b_id,
        {"performing_staff_id": stack.hyg_id, "sterilization_load_id": stack.load1_id},
        stack.hyg_headers,
    )
    validate_error(resp, ApiErrorId.ERR_VARNISH_INTERVAL.value, 422)

    procedure = validate_success(api.get_procedure(stack.varnish_b_id, ADMIN))
    assert procedure["status"] == "PLANNED"
    patient = validate_success(api.get_patient(stack.patient_id, ADMIN))
    assert patient["varnish_applications_in_period"] == 1
    assert_same_date(patient["last_varnish_date"], "2026-02-10", "last_varnish_date")


def test_varnish_at_exactly_ninety_whole_days_is_performed(api):
    """PRD §2.6: "For a `D1206` fluoride varnish, the number of whole calendar days elapsed
    since the patient's `last_varnish_date` must be at least 90. Exactly 90 days elapsed
    passes; 89 fails. A patient with a null `last_varnish_date` passes automatically."
    PRD §3.5: "A `D1206` additionally raises the patient's `varnish_applications_in_period` by
    one and sets `last_varnish_date` to the logical clock date."

    Design: Difficulty/boundary_precision_check/varnish_interval_eighty_nine_days_fails_and_exactly_ninety_days_passes
    """
    stack = _second_varnish_fixture()
    validate_error(
        api.perform_procedure(
            stack.varnish_b_id,
            {"performing_staff_id": stack.hyg_id, "sterilization_load_id": stack.load1_id},
            stack.hyg_headers,
        ),
        ApiErrorId.ERR_VARNISH_INTERVAL.value, 422,
    )

    set_clock("2026-05-11T09:00:00Z")
    performed = validate_success(
        api.perform_procedure(
            stack.varnish_b_id,
            {"performing_staff_id": stack.hyg_id, "sterilization_load_id": stack.load1_id},
            stack.hyg_headers,
        )
    )
    assert performed["status"] == "PERFORMED"
    assert_same_instant(performed["performed_at"], "2026-05-11T09:00:00Z", "performed_at")

    patient = validate_success(api.get_patient(stack.patient_id, ADMIN))
    assert_same_date(patient["last_varnish_date"], "2026-05-11", "last_varnish_date")
    assert patient["varnish_applications_in_period"] == 2


def test_third_varnish_in_one_period_is_refused_by_the_application_cap(api):
    """PRD §2.6: "For a `D1206`, the patient's `varnish_applications_in_period` must be
    strictly less than 2 before the application is recorded."
    PRD §3.5: "The per-period cap requires the patient's `varnish_applications_in_period` to
    be strictly less than 2 before the application is recorded, so two applications per
    programme period is the ceiling."

    Design: Corner/validations/third_varnish_in_one_period_is_refused_by_the_application_cap
    """
    stack = setup_program_site_and_staff(
        clock="2026-02-10T09:00:00Z", period_ends_on="2026-12-31", calibrated_on="2026-01-05"
    )
    setup_visit_in_progress(
        stack, scope_tier="SCREENING_FLUORIDE",
        consent_overrides={"signed_at": "2026-01-05T00:00:00Z"},
        scheduled_start_at="2026-02-10T09:00:00Z", scheduled_end_at="2026-02-10T15:00:00Z",
        load_cycle_completed_at="2026-02-09T08:00:00Z",
    )
    register_encounter(stack)
    screen_encounter(stack)
    exam_encounter(stack)
    perform_procedure(stack, plan_procedure(stack, "D1206")["id"])
    get_success_data(api_client.complete_site_visit(stack.visit_id, stack.dentist_headers))

    def _next_visit(start, end, load_number, cycle):
        visit = build_site_visit(
            stack.site_id, stack.pp_id, stack.unit_id, stack.dentist_id, stack.coord_headers,
            onsite_dentist_staff_id=stack.dentist_id,
            scheduled_start_at=start, scheduled_end_at=end, chair_count=2,
        )
        load = build_sterilization_load(
            stack.unit_id, stack.asst_id, stack.asst_headers,
            load_number=load_number, cycle_completed_at=cycle, site_visit_id=visit["id"],
        )
        read_spore_result(load["id"], "PASSED", stack.hyg_id, stack.hyg_headers)
        started = get_success_data(api_client.start_site_visit(visit["id"], stack.dentist_headers))
        stack.visit_id = started["id"]
        stack.load1_id = load["id"]
        register_encounter(stack)
        screen_encounter(stack)
        exam_encounter(stack)
        return plan_procedure(stack, "D1206")

    set_clock("2026-05-11T09:00:00Z")
    second = _next_visit("2026-05-11T09:00:00Z", "2026-05-11T15:00:00Z", "L-B", "2026-05-10T08:00:00Z")
    perform_procedure(stack, second["id"])
    get_success_data(api_client.complete_site_visit(stack.visit_id, stack.dentist_headers))

    set_clock("2026-08-09T09:00:00Z")
    get_success_data(
        api_client.calibrate_portable_unit(stack.unit_id, {"calibrated_on": "2026-08-01"}, ADMIN)
    )
    third = _next_visit("2026-08-09T09:00:00Z", "2026-08-09T15:00:00Z", "L-C", "2026-08-08T08:00:00Z")

    resp = api.perform_procedure(
        third["id"],
        {"performing_staff_id": stack.hyg_id, "sterilization_load_id": stack.load1_id},
        stack.hyg_headers,
    )
    validate_error(resp, ApiErrorId.ERR_VARNISH_CAP_EXCEEDED.value, 422)

    assert validate_success(api.get_procedure(third["id"], ADMIN))["status"] == "PLANNED"
    patient = validate_success(api.get_patient(stack.patient_id, ADMIN))
    assert patient["varnish_applications_in_period"] == 2
    assert_same_date(patient["last_varnish_date"], "2026-05-11", "last_varnish_date")


def _lapsed_credential_fixture():
    stack = setup_screened_and_examined(scope_tier="SCREENING_FLUORIDE")
    varnish = plan_procedure(stack, "D1206")
    get_success_data(
        api_client.update_staff_member(stack.hyg_id, {"credential_status": "LAPSED"}, ADMIN)
    )
    stack.varnish_id = varnish["id"]
    return stack


def test_performing_with_a_lapsed_credential_is_refused(api):
    """PRD §2.6: "Every staff member the request relies on has `credential_status` equal to
    `ACTIVE`."
    PRD §2.6: "A `LAPSED` or `INACTIVE` credential on any of them refuses the whole request."

    Design: Difficulty/cross_entity_state_dependency/procedure_perform_blocked_by_lapsed_staff_credential
    """
    stack = _lapsed_credential_fixture()
    resp = api.perform_procedure(
        stack.varnish_id,
        {"performing_staff_id": stack.hyg_id, "sterilization_load_id": stack.load1_id},
        stack.hyg_headers,
    )
    validate_error(resp, ApiErrorId.ERR_CREDENTIAL_LAPSED.value, 409)

    procedure = validate_success(api.get_procedure(stack.varnish_id, ADMIN))
    assert procedure["status"] == "PLANNED"
    assert procedure["performed_at"] is None


def test_a_credential_lapse_recorded_mid_programme_leaves_the_ledgers_untouched(api):
    """PRD §3.4: "A `ProgramAdmin` can later revise any of `credential_status`,
    `supervision_level`, `license_state` and `credential_expires_on` on an existing record —
    that is the mechanism by which a licence is moved between states or a credential is marked
    lapsed mid-programme, and it stays available even while a period is frozen."
    PRD §2.10: "For every site visit, `booked_chair_minutes` equals the sum of `chair_minutes`
    over every procedure belonging to that visit's encounters whose `status` is `PLANNED` or
    `PERFORMED`."

    Design: Difficulty/cross_entity_state_dependency/procedure_perform_blocked_by_lapsed_staff_credential
    """
    stack = _lapsed_credential_fixture()
    validate_error(
        api.perform_procedure(
            stack.varnish_id,
            {"performing_staff_id": stack.hyg_id, "sterilization_load_id": stack.load1_id},
            stack.hyg_headers,
        ),
        ApiErrorId.ERR_CREDENTIAL_LAPSED.value, 409,
    )

    assert validate_success(api.get_staff_member(stack.hyg_id, ADMIN))["credential_status"] == "LAPSED"
    assert validate_success(api.get_patient(stack.patient_id, ADMIN))["varnish_applications_in_period"] == 0
    visit = validate_success(api.get_site_visit(stack.visit_id, ADMIN))
    assert visit["booked_chair_minutes"] == 33, (
        f"Screen 10 + exam 15 + planned varnish 8 = 33, got {visit['booked_chair_minutes']}"
    )


def _chair_ledger_fixture():
    stack = setup_screened_and_examined(
        scope_tier="SCREENING_FLUORIDE_SEALANT", screening={"cavitated_lesion_count": 2}
    )
    sealant = plan_procedure(stack, "D1351", tooth_number=3, surface="O")
    varnish = plan_procedure(stack, "D1206")
    return SimpleNamespace(stack=stack, sealant_id=sealant["id"], varnish_id=varnish["id"])


def test_each_void_credits_back_exactly_the_minutes_it_booked(api):
    """PRD §3.4: "Against that capacity sits `booked_chair_minutes`, a ledger recomputed in
    full — never incrementally patched — as the sum of `chair_minutes` over every procedure
    belonging to that visit's encounters whose `status` is `PLANNED` or `PERFORMED`."
    PRD §3.5: "voiding a `PLANNED` procedure releases its chair minutes"

    Design: Difficulty/compensating_invariant/chair_minute_ledger_returns_exactly_the_minutes_each_void_releases
    """
    fx = _chair_ledger_fixture()
    stack = fx.stack
    before = validate_success(api.get_site_visit(stack.visit_id, ADMIN))
    assert before["booked_chair_minutes"] == 45, (
        f"10 + 15 + 12 + 8 = 45, got {before['booked_chair_minutes']}"
    )

    voided_sealant = validate_success(
        api.void_procedure(fx.sealant_id, {"void_reason": "TOOTH_NOT_ERUPTED"}, stack.dentist_headers)
    )
    assert voided_sealant["status"] == "VOIDED"
    mid = validate_success(api.get_site_visit(stack.visit_id, ADMIN))
    assert mid["booked_chair_minutes"] == 33, (
        f"Exactly the sealant's 12 minutes come back, got {mid['booked_chair_minutes']}"
    )

    voided_varnish = validate_success(
        api.void_procedure(fx.varnish_id, {"void_reason": "PATIENT_DECLINED_AT_CHAIR"},
                           stack.dentist_headers)
    )
    assert voided_varnish["status"] == "VOIDED"
    after = validate_success(api.get_site_visit(stack.visit_id, ADMIN))
    assert after["booked_chair_minutes"] == 25, (
        f"Exactly the varnish's 8 minutes come back, got {after['booked_chair_minutes']}"
    )


def test_chair_ledger_equals_the_sum_over_surviving_rows_with_no_residue(api):
    """PRD §2.10: "For every site visit, `booked_chair_minutes` equals the sum of
    `chair_minutes` over every procedure belonging to that visit's encounters whose `status`
    is `PLANNED` or `PERFORMED`. This holds at all times."
    PRD §3.4: "Take the scheduled duration in whole minutes — the difference between
    `scheduled_end_at` and `scheduled_start_at` — multiply it by `chair_count`, multiply that
    by a utilisation cap of 0.85, and take the floor to a whole number of minutes; the result
    is `capacity_chair_minutes`."

    Design: Difficulty/compensating_invariant/chair_minute_ledger_returns_exactly_the_minutes_each_void_releases
    """
    fx = _chair_ledger_fixture()
    stack = fx.stack
    validate_success(
        api.void_procedure(fx.sealant_id, {"void_reason": "TOOTH_NOT_ERUPTED"}, stack.dentist_headers)
    )
    validate_success(
        api.void_procedure(fx.varnish_id, {"void_reason": "PATIENT_DECLINED_AT_CHAIR"},
                           stack.dentist_headers)
    )

    visit = validate_success(api.get_site_visit(stack.visit_id, ADMIN))
    assert visit["capacity_chair_minutes"] == 612, (
        f"360 minutes x 2 chairs x 0.85 floored is 612, got {visit['capacity_chair_minutes']}"
    )
    rows = list_encounter_procedures(stack.enc_id)
    assert_chair_ledger_matches(visit, rows)

    performed = [r for r in rows if r["status"] == "PERFORMED"]
    assert len(performed) == 2, f"Only the auto-created rows survive, got {len(performed)}"
    assert sum(r["chair_minutes"] for r in performed) == 25
