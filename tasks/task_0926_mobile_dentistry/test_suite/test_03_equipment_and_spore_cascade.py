"""Portable units, calibration, biological indicators and the five-link taint cascade."""

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_portable_unit,
    assert_same_date,
    assert_same_instant,
    assert_sterilization_load,
    build_portable_unit,
    build_program_period,
    build_site,
    build_site_visit,
    build_staff,
    build_sterilization_load,
    exam_encounter,
    get_success_data,
    list_encounter_procedures,
    make_dental_assistant_headers,
    make_field_dentist_headers,
    make_field_hygienist_headers,
    make_program_admin_headers,
    make_site_coordinator_headers,
    perform_procedure,
    plan_procedure,
    register_encounter,
    screen_encounter,
    set_clock,
    setup_program_site_and_staff,
    setup_visit_in_progress,
    validate_error,
    validate_success,
)

ADMIN = make_program_admin_headers()


def test_calibration_status_derives_from_the_default_logical_clock(api):
    """PRD §2.5: "whose value is exactly `2026-05-01T00:00:00Z` from server start until a
    `ProgramAdmin` moves it, and which never falls back to real time afterwards."
    PRD §3.3: "Recording a calibration supplies the `calibrated_on` date, which becomes the
    unit's `last_calibrated_on`; `calibration_due_on` is then that date advanced by 180
    calendar days."
    PRD §3.3: "a unit that has never been calibrated is `EXPIRED`; a unit whose
    `calibration_due_on` is strictly earlier than the logical clock date is `EXPIRED`; a unit
    whose due date is still ahead but is no more than 30 days away — that is, the logical
    clock date has reached the due date minus 30 days — is `DUE`; anything earlier than that
    is `CURRENT`."

    Design: Corner/calculations/never_calibrated_unit_reads_expired_and_the_default_clock_is_2026_05_01
    """
    # The clock endpoint is deliberately never called: the default clock is under test.
    fresh = validate_success(api.create_portable_unit({"unit_code": "PU-01"}, ADMIN), 201)
    expired = validate_success(api.create_portable_unit({"unit_code": "PU-02"}, ADMIN), 201)
    due = validate_success(api.create_portable_unit({"unit_code": "PU-03"}, ADMIN), 201)

    validate_success(api.calibrate_portable_unit(expired["id"], {"calibrated_on": "2025-11-01"}, ADMIN))
    validate_success(api.calibrate_portable_unit(due["id"], {"calibrated_on": "2025-11-02"}, ADMIN))

    fresh_read = validate_success(api.get_portable_unit(fresh["id"], ADMIN))
    assert_portable_unit(fresh_read)
    assert fresh_read["calibration_status"] == "EXPIRED"
    assert fresh_read["calibration_due_on"] is None

    expired_read = validate_success(api.get_portable_unit(expired["id"], ADMIN))
    assert_same_date(expired_read["calibration_due_on"], "2026-04-30", "PU-02 calibration_due_on")
    assert expired_read["calibration_status"] == "EXPIRED"

    due_read = validate_success(api.get_portable_unit(due["id"], ADMIN))
    assert_same_date(due_read["calibration_due_on"], "2026-05-01", "PU-03 calibration_due_on")
    assert due_read["calibration_status"] == "DUE"


def test_scheduling_on_a_never_calibrated_unit_is_refused(api):
    """PRD §2.6: "The portable unit assigned to the visit has a `calibration_status` of
    `CURRENT` or `DUE`. A unit whose calibration has lapsed to `EXPIRED`, including a unit
    that has never been calibrated at all and therefore has a null `last_calibrated_on`, is
    refused."

    Design: Corner/validations/scheduling_a_visit_on_a_never_calibrated_unit_returns_calibration_expired
    """
    set_clock("2026-05-11T09:00:00Z")
    period = build_program_period()
    site = build_site()
    coord = make_site_coordinator_headers(site["id"])
    dentist = build_staff("Ada Reyes", "DENTIST", "D-1001", "SELF")
    unit = build_portable_unit(calibrated_on=None)

    resp = api.create_site_visit(
        {
            "site_id": site["id"],
            "program_period_id": period["id"],
            "portable_unit_id": unit["id"],
            "lead_staff_id": dentist["id"],
            "onsite_dentist_staff_id": dentist["id"],
            "scheduled_start_at": "2026-05-11T09:00:00Z",
            "scheduled_end_at": "2026-05-11T15:00:00Z",
            "chair_count": 2,
        },
        coord,
    )
    validate_error(resp, ApiErrorId.ERR_UNIT_CALIBRATION_EXPIRED.value, 409)
    assert validate_success(api.get_portable_unit(unit["id"], ADMIN))["calibration_status"] == "EXPIRED"
    rows = api.list_site_visits(ADMIN, params={"portable_unit_id": unit["id"]}).json()["data"]
    assert rows == [], "A refused schedule must leave no SiteVisit row behind"


def test_the_loader_may_not_read_their_own_spore_indicator(api):
    """PRD §3.3: "The reader may not be the loader: a `result_recorded_by_staff_id` equal to
    the load's `loaded_by_staff_id` is refused with `ERR_SEGREGATION_OF_DUTIES`, which is the
    one place in the clinical workflow where the same physical person genuinely cannot fill
    both chairs."

    Design: Corner/validations/the_staff_member_who_ran_the_load_cannot_read_its_spore_indicator
    """
    set_clock("2026-05-11T09:00:00Z")
    hygienist = build_staff("Hana Ito", "HYGIENIST", "H-2001", "GENERAL")
    hyg_headers = make_field_hygienist_headers(hygienist["id"])
    unit = build_portable_unit()
    load = build_sterilization_load(
        unit["id"], hygienist["id"], hyg_headers,
        load_number="L-1", cycle_completed_at="2026-05-10T08:00:00Z",
    )

    resp = api.record_spore_result(
        load["id"], {"result": "PASSED", "result_recorded_by_staff_id": hygienist["id"]}, hyg_headers
    )
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 422)

    after = validate_success(api.get_sterilization_load(load["id"], ADMIN))
    assert after["spore_result"] == "PENDING"
    assert after["result_recorded_by_staff_id"] is None
    assert validate_success(api.get_portable_unit(unit["id"], ADMIN))["last_passed_load_at"] is None


def test_reading_a_spore_indicator_before_incubation_ends_is_refused(api):
    """PRD §3.3: "Its `incubation_ends_at` is computed at creation as `cycle_completed_at`
    advanced by exactly 24 hours — the biological indicator has to sit in the incubator
    overnight before it means anything."
    PRD §3.3: "And the incubation must have finished: a reading taken while the logical clock
    is still before *this* load's `incubation_ends_at` is refused with
    `ERR_SPORE_RESULT_PENDING`."

    Design: Corner/validations/reading_a_spore_indicator_before_incubation_ends_is_refused
    """
    set_clock("2026-05-11T09:00:00Z")
    assistant = build_staff("Ben Cruz", "DENTAL_ASSISTANT", "A-3001", "DIRECT")
    hygienist = build_staff("Hana Ito", "HYGIENIST", "H-2001", "GENERAL")
    unit = build_portable_unit()
    load = build_sterilization_load(
        unit["id"], assistant["id"], make_dental_assistant_headers(assistant["id"]),
        load_number="L-1", cycle_completed_at="2026-05-11T08:00:00Z",
    )
    assert_sterilization_load(load)
    assert_same_instant(load["incubation_ends_at"], "2026-05-12T08:00:00Z", "incubation_ends_at")

    resp = api.record_spore_result(
        load["id"],
        {"result": "PASSED", "result_recorded_by_staff_id": hygienist["id"]},
        make_field_hygienist_headers(hygienist["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_SPORE_RESULT_PENDING.value, 409)
    assert validate_success(api.get_sterilization_load(load["id"], ADMIN))["spore_result"] == "PENDING"


def _quarantined_unit_fixture():
    """A SCHEDULED visit whose only load was read FAILED, leaving the unit QUARANTINED."""
    set_clock("2026-05-11T09:00:00Z")
    period = build_program_period()
    site = build_site()
    coord = make_site_coordinator_headers(site["id"])
    dentist = build_staff("Ada Reyes", "DENTIST", "D-1001", "SELF")
    hygienist = build_staff("Hana Ito", "HYGIENIST", "H-2001", "GENERAL")
    assistant = build_staff("Ben Cruz", "DENTAL_ASSISTANT", "A-3001", "DIRECT")
    unit = build_portable_unit()
    visit = build_site_visit(
        site["id"], period["id"], unit["id"], dentist["id"], coord,
        onsite_dentist_staff_id=dentist["id"],
    )
    load = build_sterilization_load(
        unit["id"], assistant["id"], make_dental_assistant_headers(assistant["id"]),
        load_number="L-1", cycle_completed_at="2026-05-10T08:00:00Z", site_visit_id=visit["id"],
    )
    get_success_data(
        api_client.record_spore_result(
            load["id"], {"result": "FAILED", "result_recorded_by_staff_id": hygienist["id"]},
            make_field_hygienist_headers(hygienist["id"]),
        )
    )
    unit_after_fail = get_success_data(api_client.get_portable_unit(unit["id"], ADMIN))
    return {
        "visit_id": visit["id"],
        "unit_id": unit["id"],
        "load_id": load["id"],
        "unit_version_after_fail": unit_after_fail["version"],
        "dentist_headers": make_field_dentist_headers(dentist["id"]),
    }


def test_starting_a_visit_on_a_quarantined_unit_is_refused(api):
    """PRD §2.7: "A `QUARANTINED` `PortableUnit` cannot be assigned to a new visit or taken
    into service."
    PRD §2.6: "If the unit is quarantined at all, whether it was already quarantined or has
    just become so, the refusal is `ERR_UNIT_QUARANTINED`."

    Design: Difficulty/cross_entity_state_dependency/site_visit_start_blocked_by_quarantined_portable_unit
    """
    fx = _quarantined_unit_fixture()
    resp = api.start_site_visit(fx["visit_id"], fx["dentist_headers"])
    validate_error(resp, ApiErrorId.ERR_UNIT_QUARANTINED.value, 409)

    visit = validate_success(api.get_site_visit(fx["visit_id"], ADMIN))
    assert visit["status"] == "SCHEDULED", f"The visit must not move, got {visit['status']}"
    assert visit["started_at"] is None
    assert validate_success(api.get_portable_unit(fx["unit_id"], ADMIN))["status"] == "QUARANTINED"


def test_second_touch_on_an_already_quarantined_unit_writes_nothing(api):
    """PRD §2.8: "On a **second** attempt against the same unit, the most recent load is no
    longer `PENDING`, so the sweep finds nothing, no row is written, `PortableUnit.version`
    and `SterilizationLoad.version` do not change — and the identical `ERR_UNIT_QUARANTINED`
    is returned."
    PRD §2.8: "when the failure came from the automatic sweep of §2.8 rather than from an
    operator, `auto_failed` is set true and `result_recorded_by_staff_id` stays null."

    Design: Difficulty/cross_entity_state_dependency/site_visit_start_blocked_by_quarantined_portable_unit
    """
    fx = _quarantined_unit_fixture()
    load_before = validate_success(api.get_sterilization_load(fx["load_id"], ADMIN))

    validate_error(
        api.start_site_visit(fx["visit_id"], fx["dentist_headers"]),
        ApiErrorId.ERR_UNIT_QUARANTINED.value,
        409,
    )

    unit = validate_success(api.get_portable_unit(fx["unit_id"], ADMIN))
    assert unit["version"] == fx["unit_version_after_fail"], (
        "The already-quarantined branch performs no write, so PortableUnit.version must not move"
    )
    load = validate_success(api.get_sterilization_load(fx["load_id"], ADMIN))
    assert load["version"] == load_before["version"]
    assert load["spore_result"] == "FAILED"
    assert load["auto_failed"] is False, "An operator recorded this failure, not the sweep"
    assert load["tainted_procedure_count"] == 0, "No procedure existed to taint"


def _spore_cascade_fixture():
    """A priced encounter, an ACTIVE plan and an OPEN referral, all resting on load L-2."""
    stack = setup_program_site_and_staff(clock="2026-05-11T09:00:00Z")
    setup_visit_in_progress(stack, scope_tier="SCREENING_FLUORIDE", payer_type="MEDICAID_MCO")
    load2 = build_sterilization_load(
        stack.unit_id, stack.asst_id, stack.asst_headers,
        load_number="L-2", cycle_completed_at="2026-05-11T09:00:00Z", site_visit_id=stack.visit_id,
    )
    stack.load2_id = load2["id"]
    register_encounter(stack)
    screen_encounter(stack)
    exam_encounter(stack)
    varnish = plan_procedure(stack, "D1206")
    perform_procedure(stack, varnish["id"], sterilization_load_id=load2["id"])
    stack.varnish_id = varnish["id"]
    get_success_data(api_client.close_encounter(stack.enc_id, stack.dentist_headers))
    get_success_data(api_client.price_encounter(stack.enc_id, {}, stack.billing_headers))
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
    stack.plan_id = plan["id"]
    stack.ref_id = referral["id"]
    set_clock("2026-05-12T10:00:00Z")
    return stack


def test_failed_indicator_taints_the_loads_procedures_and_quarantines_the_unit(api):
    """PRD §3.3: "Having fixed the load set, link two moves **every procedure whose
    `sterilization_load_id` names one of those loads and whose `status` is exactly
    `PERFORMED`** to `TAINTED`, stamping `taint_reason` with the literal `SPORE_TEST_FAILED`,
    and records the number moved on the failing load as `tainted_procedure_count`."
    PRD §3.3: "Each tainted procedure releases its `chair_minutes` from its visit's
    `booked_chair_minutes`, and each tainted `D1206` decrements its patient's
    `varnish_applications_in_period` by one and forces `last_varnish_date` to be recomputed
    from whatever `D1206` rows for that patient are still `PERFORMED`."
    PRD §3.3: "Finally, the unit itself moves to `QUARANTINED` with `quarantined_at` stamped,
    from whichever of `AVAILABLE` or `IN_SERVICE` it was in."

    Design: Difficulty/transitive_cascade/failed_spore_indicator_depth_five_cascade_to_abandoned_referral
    """
    stack = _spore_cascade_fixture()
    failed = validate_success(
        api.record_spore_result(
            stack.load2_id, {"result": "FAILED", "result_recorded_by_staff_id": stack.hyg_id},
            stack.hyg_headers,
        )
    )
    assert failed["spore_result"] == "FAILED"
    assert failed["tainted_procedure_count"] == 3
    assert failed["auto_failed"] is False

    # The already-cleared L-1 keeps its PASSED reading.
    assert validate_success(api.get_sterilization_load(stack.load1_id, ADMIN))["spore_result"] == "PASSED"
    assert validate_success(api.get_portable_unit(stack.unit_id, ADMIN))["status"] == "QUARANTINED"

    varnish = validate_success(api.get_procedure(stack.varnish_id, ADMIN))
    assert varnish["status"] == "TAINTED"
    assert varnish["taint_reason"] == "SPORE_TEST_FAILED"

    rows = list_encounter_procedures(stack.enc_id)
    assert len(rows) == 3, f"Expected 3 procedures on the encounter, got {len(rows)}"
    assert all(r["status"] == "TAINTED" for r in rows), [r["status"] for r in rows]

    visit = validate_success(api.get_site_visit(stack.visit_id, ADMIN))
    assert visit["booked_chair_minutes"] == 0
    patient = validate_success(api.get_patient(stack.patient_id, ADMIN))
    assert patient["varnish_applications_in_period"] == 0
    assert patient["last_varnish_date"] is None


def test_failed_indicator_reverts_the_billing_supersedes_the_plan_and_abandons_the_referral(api):
    """PRD §3.3: "If — and only if — that encounter's `billing_status` was `PRICED`, it
    reverts to `UNBILLED` and its `allowed_amount_cents`, `patient_responsibility_cents`,
    `plan_paid_cents` and `write_off_cents` are all cleared to zero with `pricing_regime`
    cleared to null."
    PRD §3.3: "Link four, caused by link three, moves every treatment plan on such an
    encounter whose `plan_status` is `ACTIVE` to `SUPERSEDED`, setting `superseded_reason` to
    `SPORE_TEST_FAILED` and clearing `follow_up_due_date` to null."
    PRD §3.3: "Link five, caused by link four, moves every referral on a plan that link four
    just superseded whose `status` is `OPEN` or `SENT` to `ABANDONED`, stamping `abandoned_at`
    and `case_management_opened_at` with the logical clock instant and setting
    `abandon_reason` to `PLAN_SUPERSEDED`."

    Design: Difficulty/transitive_cascade/failed_spore_indicator_depth_five_cascade_to_abandoned_referral
    """
    stack = _spore_cascade_fixture()
    validate_success(
        api.record_spore_result(
            stack.load2_id, {"result": "FAILED", "result_recorded_by_staff_id": stack.hyg_id},
            stack.hyg_headers,
        )
    )

    encounter = validate_success(api.get_encounter(stack.enc_id, ADMIN))
    assert encounter["tainted_procedure_count"] == 3
    assert encounter["billing_status"] == "UNBILLED"
    assert encounter["subtotal_cents"] == 0
    assert encounter["supply_surcharge_cents"] == 0
    assert encounter["total_charge_cents"] == 0
    assert encounter["allowed_amount_cents"] == 0
    assert encounter["patient_responsibility_cents"] == 0
    assert encounter["plan_paid_cents"] == 0
    assert encounter["write_off_cents"] == 0
    assert encounter["pricing_regime"] is None
    assert encounter["clinical_status"] == "CLOSED", "The clinical axis is untouched by the revert"

    plan = validate_success(api.get_treatment_plan(stack.plan_id, ADMIN))
    assert plan["plan_status"] == "SUPERSEDED"
    assert plan["superseded_reason"] == "SPORE_TEST_FAILED"
    assert plan["follow_up_due_date"] is None

    referral = validate_success(api.get_referral(stack.ref_id, ADMIN))
    assert referral["status"] == "ABANDONED"
    assert referral["abandon_reason"] == "PLAN_SUPERSEDED"
    assert_same_instant(
        referral["case_management_opened_at"], "2026-05-12T10:00:00Z", "case_management_opened_at"
    )
    assert_same_instant(referral["abandoned_at"], "2026-05-12T10:00:00Z", "abandoned_at")
    assert referral["attempt_count"] == 0


def test_pricing_an_encounter_carrying_tainted_procedures_is_refused(api):
    """PRD §2.6: "The encounter carries no procedure currently in status `TAINTED` — that is,
    its `tainted_procedure_count` is zero. A tainted encounter must have its tainted
    procedures voided before it can be priced or claimed."

    Design: Corner/validations/pricing_an_encounter_carrying_tainted_procedures_is_refused
    """
    stack = setup_program_site_and_staff(clock="2026-05-11T09:00:00Z")
    setup_visit_in_progress(stack, scope_tier="SCREENING_FLUORIDE", payer_type="MEDICAID_MCO")
    load2 = build_sterilization_load(
        stack.unit_id, stack.asst_id, stack.asst_headers,
        load_number="L-2", cycle_completed_at="2026-05-11T09:00:00Z", site_visit_id=stack.visit_id,
    )
    register_encounter(stack)
    screen_encounter(stack)
    exam_encounter(stack)
    set_clock("2026-05-12T10:00:00Z")
    failed = validate_success(
        api.record_spore_result(
            load2["id"], {"result": "FAILED", "result_recorded_by_staff_id": stack.hyg_id},
            stack.hyg_headers,
        )
    )
    assert failed["tainted_procedure_count"] == 2

    resp = api.price_encounter(stack.enc_id, {}, stack.billing_headers)
    validate_error(resp, ApiErrorId.ERR_PROCEDURE_TAINTED.value, 409)

    encounter = validate_success(api.get_encounter(stack.enc_id, ADMIN))
    assert encounter["tainted_procedure_count"] == 2
    assert encounter["billing_status"] == "UNBILLED"
    assert encounter["subtotal_cents"] == 0
    assert validate_success(api.get_portable_unit(stack.unit_id, ADMIN))["status"] == "QUARANTINED"
