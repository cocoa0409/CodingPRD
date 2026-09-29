"""Each catalogued error id raised by the one condition that owns it."""

from test_helpers import (
    ADMIN,
    COORDINATOR,
    PROGRAM_ADMIN_USER_ID,
    SURVEYOR,
    api_client,
    assessment_decision_payload,
    assessment_payload,
    build_user_headers,
    certificate_payload,
    coverage_payload,
    create_certificate,
    create_device,
    create_operator,
    create_reagent_lot,
    create_site,
    create_storage_unit,
    create_trained_operator,
    decide_assessment,
    enroll_pt,
    excursion_resolution_payload,
    make_operator_headers,
    pt_enrollment_payload,
    pt_event_payload,
    qc_run_payload,
    qc_unlock_payload,
    read_assessment,
    read_certificate,
    read_device,
    read_lot,
    read_operator,
    read_site,
    read_storage_unit,
    reagent_lot_payload,
    record_qc_run,
    record_temperature_reading,
    register_pt_event,
    score_pt_event,
    set_clock,
    setup_covered_site,
    setup_site_with_device,
    setup_site_with_verified_lot,
    submit_assessment,
    suspend_certificate,
    training_payload,
    validate_error,
    validate_paginated,
    validate_success,
    verify_lot,
)

SEPTEMBER = "2026-09-01T08:00:00Z"
SEPTEMBER_STAMP = "2026-09-01T08:00:00.000Z"
UNKNOWN_SITE = "6f1d0c2b-0000-4000-8000-000000000001"
UNKNOWN_OPERATOR = "6f1d0c2b-0000-4000-8000-000000000002"
UNKNOWN_DEVICE = "6f1d0c2b-0000-4000-8000-000000000003"
UNKNOWN_LOT = "6f1d0c2b-0000-4000-8000-000000000004"
UNKNOWN_INSPECTION = "6f1d0c2b-0000-4000-8000-000000000005"
UNKNOWN_CERTIFICATE = "6f1d0c2b-0000-4000-8000-000000000006"
UNKNOWN_SITE_UNDER_BAD_ROLE = "6f1d0c2b-0000-4000-8000-0000000000ff"


def test_four_entities_own_a_scoped_404_and_everything_else_falls_through():
    """Site, operator, instrument and lot each answer their own id; survey and
    certificate share the generic one.

    PRD 2.6: "Four families are distinguished so that clients can tell what is
    missing: a `site_id` that does not resolve to a site yields `ERR_SITE_NOT_FOUND`;
    an `operator_id`, `assessor_operator_id` or `lab_director_operator_id` that does
    not resolve to an operator yields `ERR_OPERATOR_NOT_FOUND`; a `device_id` that does
    not resolve to an instrument yields `ERR_DEVICE_NOT_FOUND`; a `reagent_lot_id` that
    does not resolve to a reagent lot yields `ERR_REAGENT_LOT_NOT_FOUND`."

    PRD 2.6: "Every other reference — a certificate, a coverage row, a competency
    assessment, a storage unit, a control run, a patient result, a proficiency
    enrolment, a proficiency event, an inspection or a deficiency finding, whether
    addressed by path or named in a body field such as `confirming_qc_run_id`,
    `level_1_qc_run_id`, `level_2_qc_run_id`, `enrollment_id`, `inspection_id`,
    `parent_finding_id`, `certificate_id` or `storage_unit_id` — yields
    `ERR_RESOURCE_NOT_FOUND` when it does not resolve."

    Design: Corner/errors/not_found_family_returns_scoped_404_error_ids
    """
    set_clock(SEPTEMBER)

    site_error = validate_error(
        api_client.get_site(UNKNOWN_SITE, COORDINATOR), "ERR_SITE_NOT_FOUND", 404
    )
    operator_error = validate_error(
        api_client.get_operator(UNKNOWN_OPERATOR, COORDINATOR),
        "ERR_OPERATOR_NOT_FOUND", 404,
    )
    device_error = validate_error(
        api_client.get_device(UNKNOWN_DEVICE, COORDINATOR),
        "ERR_DEVICE_NOT_FOUND", 404,
    )
    lot_error = validate_error(
        api_client.get_reagent_lot(UNKNOWN_LOT, COORDINATOR),
        "ERR_REAGENT_LOT_NOT_FOUND", 404,
    )
    inspection_error = validate_error(
        api_client.get_inspection(UNKNOWN_INSPECTION, SURVEYOR),
        "ERR_RESOURCE_NOT_FOUND", 404,
    )
    certificate_error = validate_error(
        api_client.get_certificate(UNKNOWN_CERTIFICATE, ADMIN),
        "ERR_RESOURCE_NOT_FOUND", 404,
    )

    for error in (
        site_error, operator_error, device_error,
        lot_error, inspection_error, certificate_error,
    ):
        assert isinstance(error["message"], str)
        assert error["message"].strip() != ""


def test_an_undeclared_role_is_a_401_while_a_declared_but_barred_one_is_a_403():
    """The 401 wins even over the existence check; the 403 needs a real role.

    PRD 2.7: "1. **Rank 1 — authentication.** Both headers present and `X-User-Role`
    one of the five declared roles, on every endpoint. Otherwise
    `ERR_UNAUTHENTICATED` (401)."

    PRD 2.7: "2. **Rank 2 — authorisation.** The acting role appears in the endpoint's
    authorised-role list in §4, and for the entity-backed roles the `X-User-ID`
    resolves to an operator row. Otherwise `ERR_UNAUTHORIZED` (403)."

    PRD 4: "| POST | `/poct/certificates` | Register a CLIA certificate held by the
    health system. | ProgramAdmin |"

    Design: Corner/errors/auth_family_separates_unknown_role_401_from_forbidden_role_403
    """
    set_clock(SEPTEMBER)
    site = create_site(name="Endoscopy POCT", department_code="DEPT-3100")
    operator = create_operator(
        site["id"], full_name="Bea Ferraro",
        role_title="NURSE", hire_date="2026-01-05",
    )
    undeclared_role = build_user_headers("auditor-1", "Auditor")

    validate_error(
        api_client.get_site(site["id"], undeclared_role),
        "ERR_UNAUTHENTICATED", 401,
    )
    validate_error(
        api_client.get_site(UNKNOWN_SITE_UNDER_BAD_ROLE, undeclared_role),
        "ERR_UNAUTHENTICATED", 401,
    )
    validate_error(
        api_client.create_certificate(
            certificate_payload(certificate_number="45D2243038"),
            make_operator_headers(operator["id"]),
        ),
        "ERR_UNAUTHORIZED", 403,
    )

    accepted = validate_success(
        api_client.create_certificate(
            certificate_payload(certificate_number="45D2243038"), ADMIN
        ),
        201,
    )
    assert accepted["certificate_number"] == "45D2243038"


def test_re_suspending_a_certificate_answers_the_status_rung_not_the_state_rung():
    """Rank 40 owns the certificate status, so the cascade cannot run twice.

    PRD 2.7: "11. **Rank 40 — certificate active.** On certificate suspension and
    coverage creation, the referenced certificate's `status` must be `ACTIVE`.
    Otherwise `ERR_CERTIFICATE_NOT_ACTIVE` (409). Note that re-suspending an already
    `SUSPENDED` certificate surfaces here, not as a generic state error."

    PRD 3.1: "A `ProgramAdmin` suspending an `ACTIVE` certificate supplies a `reason`,
    which is stored as `suspension_reason`; the certificate moves `ACTIVE → SUSPENDED`
    and its `version` increments."

    Design: Corner/errors/suspending_an_already_suspended_certificate_returns_certificate_not_active
    """
    certificate, site, _coverage = setup_covered_site(
        clock=SEPTEMBER,
        certificate_overrides={"certificate_number": "45D2243039"},
        site_overrides={
            "name": "Dialysis POCT", "department_code": "DEPT-3200",
            "complexity_scope": "WAIVED",
        },
        coverage_overrides={"coverage_end": "2026-12-31"},
    )
    before_suspension = read_certificate(certificate["id"])
    assert before_suspension["status"] == "ACTIVE"
    suspended = suspend_certificate(
        certificate["id"], reason="CMS notice of proposed suspension"
    )
    assert suspended["status"] == "SUSPENDED"
    assert suspended["version"] == before_suspension["version"] + 1
    assert suspended["suspension_reason"] == "CMS notice of proposed suspension"

    response = api_client.suspend_certificate(
        certificate["id"], {"reason": "duplicate entry of the same CMS notice"}, ADMIN
    )

    validate_error(response, "ERR_CERTIFICATE_NOT_ACTIVE", 409)
    unchanged = read_certificate(certificate["id"])
    assert unchanged["status"] == "SUSPENDED"
    assert unchanged["version"] == suspended["version"]
    assert unchanged["suspension_reason"] == "CMS notice of proposed suspension"
    assert read_site(site["id"])["oversight_posture"] == "SUSPENDED"


def test_containment_is_checked_on_both_coverage_endpoints_and_is_inclusive():
    """One day early and one day late both fail; the coincident window is accepted.

    PRD 3.1: "The `coverage_end` may equal but never precede `coverage_start`, and the
    whole window must sit inside the certificate's own force period, or the request
    fails with `ERR_COVERAGE_OUTSIDE_CERTIFICATE_WINDOW`."

    PRD 2.7: "28. **Rank 58 — coverage inside certificate.** On coverage creation, the
    requested window must sit entirely inside the certificate's own
    `effective_date`-to-`expiration_date` span. Otherwise
    `ERR_COVERAGE_OUTSIDE_CERTIFICATE_WINDOW` (422)."

    Design: Corner/errors/coverage_window_outside_certificate_window_returns_422
    """
    set_clock(SEPTEMBER)
    certificate = create_certificate(
        certificate_number="45D2243040",
        effective_date="2026-01-01", expiration_date="2026-12-31",
    )
    site = create_site(name="Sleep Lab POCT", department_code="DEPT-3300")

    starts_too_early = api_client.create_coverage(
        coverage_payload(
            site["id"], certificate["id"],
            coverage_start="2025-12-31", coverage_end="2026-06-30",
        ),
        ADMIN,
    )
    ends_too_late = api_client.create_coverage(
        coverage_payload(
            site["id"], certificate["id"],
            coverage_start="2026-07-01", coverage_end="2027-01-01",
        ),
        ADMIN,
    )
    coincident = validate_success(
        api_client.create_coverage(
            coverage_payload(
                site["id"], certificate["id"],
                coverage_start="2026-01-01", coverage_end="2026-12-31",
            ),
            ADMIN,
        ),
        201,
    )

    validate_error(
        starts_too_early, "ERR_COVERAGE_OUTSIDE_CERTIFICATE_WINDOW", 422
    )
    validate_error(ends_too_late, "ERR_COVERAGE_OUTSIDE_CERTIFICATE_WINDOW", 422)
    assert coincident["coverage_start"] == "2026-01-01"
    assert coincident["coverage_end"] == "2026-12-31"
    _rows, meta = validate_paginated(
        api_client.list_coverages(ADMIN, params={"site_id": site["id"]})
    )
    assert meta["total_count"] == 1
    assert read_certificate(certificate["id"])["covered_site_count"] == 1


def test_a_quarantined_lot_blocks_a_control_run_before_any_date_or_lock_test():
    """The lot was verified a moment earlier and is years from expiry.

    PRD 2.7: "14. **Rank 43 — lot not quarantined.** On control-run recording,
    patient-result capture and lot verification, the referenced lot's
    `verification_status` must not be `QUARANTINED`, `DISCARDED` or `REJECTED`.
    Otherwise `ERR_LOT_QUARANTINED` (409)."

    PRD 3.5: "2. Caused by the excursion opening: every reagent lot stored in that unit
    whose `verification_status` is `UNVERIFIED` or `VERIFIED` moves to `QUARANTINED`
    with `quarantine_reason` of `TEMPERATURE_EXCURSION`, and the unit's
    `quarantined_lot_count` is updated to match."

    Design: Corner/errors/qc_run_against_quarantined_lot_returns_lot_quarantined
    """
    env = setup_site_with_verified_lot(
        clock=SEPTEMBER,
        certificate_overrides={"certificate_number": "45D2243041"},
        site_overrides={
            "name": "Urgent Care POCT", "department_code": "DEPT-3400",
            "complexity_scope": "WAIVED",
        },
        operator_overrides={"full_name": "Cal Duarte", "hire_date": "2026-01-05"},
        device_overrides={"serial_number": "SN-GL-3400"},
        lot_overrides={"lot_number": "LOT-A1", "expiration_date": "2027-01-31"},
    )
    assert env["lot"]["verification_status"] == "VERIFIED"

    reading = record_temperature_reading(
        env["storage_unit"]["id"], 9.5,
        recorded_at="2026-09-01T10:00:00Z", recorded_by_user_id="user-facilities",
    )
    assert reading["disposition"] == "OUT_OF_RANGE"
    assert reading["triggered_excursion"] is True
    assert read_lot(env["lot"]["id"])["verification_status"] == "QUARANTINED"
    assert read_storage_unit(env["storage_unit"]["id"])["quarantined_lot_count"] == 1

    response = api_client.create_qc_run(
        qc_run_payload(
            env["device"]["id"], env["lot"]["id"], env["operator"]["id"],
            "LEVEL_1", 101.0,
        ),
        make_operator_headers(env["operator"]["id"]),
    )

    validate_error(response, "ERR_LOT_QUARANTINED", 409)
    _rows, meta = validate_paginated(
        api_client.list_qc_runs(ADMIN, params={"device_id": env["device"]["id"]})
    )
    assert meta["total_count"] == 2


def test_an_open_excursion_blocks_the_next_receipt_even_with_an_empty_fridge():
    """The gate is on the unit, so resolving it lets the identical receipt through.

    PRD 3.5: "the unit's `excursion_state` must be `IN_RANGE`, or the receipt fails
    with `ERR_TEMP_EXCURSION_ACTIVE` — nothing new goes into a refrigerator that is
    currently out of range"

    PRD 3.5: "On success the unit moves `EXCURSION_OPEN → IN_RANGE`, its
    `excursion_opened_at` returns to null and its `quarantined_lot_count` returns to
    0."

    Design: Corner/errors/reagent_lot_create_into_open_excursion_returns_temp_excursion_active
    """
    set_clock(SEPTEMBER)
    site = create_site(name="Rehab POCT", department_code="DEPT-3500")
    unit = create_storage_unit(
        site["id"], name="Reagent Fridge 1", min_temp_c=2.0, max_temp_c=8.0
    )
    reading = record_temperature_reading(
        unit["id"], 12.0,
        recorded_at="2026-09-01T09:00:00Z", recorded_by_user_id="user-facilities",
    )
    assert reading["disposition"] == "OUT_OF_RANGE"
    opened = read_storage_unit(unit["id"])
    assert opened["excursion_state"] == "EXCURSION_OPEN"
    assert opened["quarantined_lot_count"] == 0

    refused = api_client.create_reagent_lot(
        reagent_lot_payload(
            site["id"], unit["id"], lot_number="LOT-B1",
            expiration_date="2027-01-31", received_at="2026-09-01T09:30:00Z",
        ),
        COORDINATOR,
    )
    validate_error(refused, "ERR_TEMP_EXCURSION_ACTIVE", 422)

    resolved = validate_success(
        api_client.resolve_excursion(
            unit["id"],
            excursion_resolution_payload(
                "RELEASE",
                assessment_note="door left ajar, probe re-sited, no lots in unit",
            ),
            COORDINATOR,
        ),
        200,
    )
    accepted = validate_success(
        api_client.create_reagent_lot(
            reagent_lot_payload(
                site["id"], unit["id"], lot_number="LOT-B1",
                expiration_date="2027-01-31", received_at="2026-09-01T10:00:00Z",
            ),
            COORDINATOR,
        ),
        201,
    )

    assert resolved["excursion_state"] == "IN_RANGE"
    assert resolved["excursion_opened_at"] is None
    assert resolved["quarantined_lot_count"] == 0
    assert accepted["verification_status"] == "UNVERIFIED"
    assert accepted["lot_number"] == "LOT-B1"


def test_lot_expiry_is_read_off_the_clock_so_the_boundary_day_still_works():
    """The expiration date itself is accepted and the next day is not.

    PRD 2.7: "24. **Rank 54 — lot in date.** On lot receipt, control-run recording,
    patient-result capture and lot verification, the current logical date must be on or
    before the lot's `expiration_date`. Otherwise `ERR_REAGENT_LOT_EXPIRED` (422)."

    PRD 3.5: "During an oversight run, any lot whose `verification_status` is
    `UNVERIFIED` or `VERIFIED` and whose `expiration_date` is strictly before the
    current logical date moves to `EXPIRED`, and every patient result referencing that
    lot whose `posting_status` is `PENDING_REVIEW` moves to `REJECTED`."

    Design: Corner/errors/qc_run_with_expired_lot_returns_reagent_lot_expired
    """
    env = setup_site_with_verified_lot(
        clock=SEPTEMBER,
        certificate_overrides={"certificate_number": "45D2243042"},
        site_overrides={
            "name": "Allergy POCT", "department_code": "DEPT-3600",
            "complexity_scope": "WAIVED",
        },
        operator_overrides={"full_name": "Dana Whitlock", "hire_date": "2026-01-05"},
        device_overrides={"serial_number": "SN-GL-3600", "qc_frequency_days": 90},
        lot_overrides={"lot_number": "LOT-A1", "expiration_date": "2026-09-30"},
    )
    assert env["lot"]["verification_status"] == "VERIFIED"

    set_clock("2026-09-30T23:00:00Z")
    on_the_boundary = validate_success(
        api_client.create_qc_run(
            qc_run_payload(
                env["device"]["id"], env["lot"]["id"], env["operator"]["id"],
                "LEVEL_1", 99.0,
            ),
            make_operator_headers(env["operator"]["id"]),
        ),
        201,
    )
    set_clock("2026-10-01T00:30:00Z")
    past_the_boundary = api_client.create_qc_run(
        qc_run_payload(
            env["device"]["id"], env["lot"]["id"], env["operator"]["id"],
            "LEVEL_1", 99.0,
        ),
        make_operator_headers(env["operator"]["id"]),
    )

    assert on_the_boundary["result"] == "PASS"
    validate_error(past_the_boundary, "ERR_REAGENT_LOT_EXPIRED", 422)
    assert read_lot(env["lot"]["id"])["verification_status"] == "VERIFIED"


def test_the_model_string_must_match_exactly_even_between_room_mates():
    """Both rows share a site, so only the model string can explain the refusal.

    PRD 3.4: "The lot must be `UNVERIFIED` or `VERIFIED` and still in date, its
    `device_model` must match the instrument's exactly, the operator and the lot must
    both belong to the instrument's site, and the operator must have `access_status` of
    `ACTIVE` with `competency_status` of `PROVISIONAL` or `COMPETENT`."

    PRD 2.7: "29. **Rank 59 — lot fits instrument.** On control-run recording and
    patient-result capture, the lot's `device_model` must equal the device's
    `device_model` by exact string equality. Otherwise
    `ERR_LOT_DEVICE_MODEL_MISMATCH` (422)."

    Design: Corner/errors/qc_run_with_mismatched_device_model_returns_lot_device_model_mismatch
    """
    env = setup_site_with_device(
        clock=SEPTEMBER,
        certificate_overrides={"certificate_number": "45D2243043"},
        site_overrides={
            "name": "Family Medicine POCT", "department_code": "DEPT-3700",
            "complexity_scope": "WAIVED",
        },
        operator_overrides={"full_name": "Eli Nakashima", "hire_date": "2026-01-05"},
        device_overrides={"serial_number": "SN-GL-3700"},
        storage_overrides={"name": "Reagent Fridge 1"},
    )
    other_model_lot = create_reagent_lot(
        env["site"]["id"], env["storage_unit"]["id"],
        device_model="StripReader-Z", lot_number="LOT-C1",
        expiration_date="2027-01-31", received_at="2026-09-01T08:00:00Z",
    )
    matching_lot = create_reagent_lot(
        env["site"]["id"], env["storage_unit"]["id"],
        lot_number="LOT-G1", expiration_date="2027-01-31",
        received_at="2026-09-01T08:05:00Z",
    )
    assert other_model_lot["device_model"] == "StripReader-Z"
    assert other_model_lot["verification_status"] == "UNVERIFIED"
    assert matching_lot["device_model"] == env["device"]["device_model"]

    refused = api_client.create_qc_run(
        qc_run_payload(
            env["device"]["id"], other_model_lot["id"], env["operator"]["id"],
            "LEVEL_1", 100.0,
        ),
        make_operator_headers(env["operator"]["id"]),
    )
    accepted = validate_success(
        api_client.create_qc_run(
            qc_run_payload(
                env["device"]["id"], matching_lot["id"], env["operator"]["id"],
                "LEVEL_1", 100.0,
            ),
            make_operator_headers(env["operator"]["id"]),
        ),
        201,
    )

    validate_error(refused, "ERR_LOT_DEVICE_MODEL_MISMATCH", 422)
    assert accepted["result"] == "PASS"
    _rows, meta = validate_paginated(
        api_client.list_qc_runs(ADMIN, params={"device_id": env["device"]["id"]})
    )
    assert meta["total_count"] == 1


def test_a_confirming_run_from_the_bench_next_door_cannot_clear_the_lock():
    """The sibling's run passes on a verified lot; only provenance is wrong.

    PRD 2.7: "31. **Rank 61 — control runs belong where claimed.** On quality-control
    unlock the confirming run must belong to the target device; on lot verification the
    two supplied runs must belong to the target lot, cover `LEVEL_1` and `LEVEL_2`, and
    share one `device_id`. Otherwise `ERR_QC_RUN_DEVICE_MISMATCH` (422)."

    PRD 3.4: "A locked instrument may still run controls — the device's `status` must
    be `ACTIVE` or `QC_LOCKED` — because that is precisely how a lock gets cleared."

    Design: Corner/errors/qc_unlock_with_a_run_from_another_device_returns_qc_run_device_mismatch
    """
    env = setup_site_with_device(
        clock=SEPTEMBER,
        certificate_overrides={"certificate_number": "45D2243044"},
        site_overrides={
            "name": "Peds Clinic POCT", "department_code": "DEPT-3800",
            "complexity_scope": "WAIVED",
        },
        operator_overrides={"full_name": "Fay Oyelaran", "hire_date": "2026-01-05"},
        device_overrides={"serial_number": "SN-GL-3801"},
        storage_overrides={"name": "Reagent Fridge 1"},
    )
    sibling = create_device(env["site"]["id"], serial_number="SN-GL-3802")
    lot = create_reagent_lot(
        env["site"]["id"], env["storage_unit"]["id"],
        lot_number="LOT-A1", expiration_date="2027-01-31",
        received_at="2026-09-01T08:00:00Z",
    )
    verified_lot, _sibling_level_one, sibling_level_two = verify_lot(
        lot["id"], sibling["id"], env["operator"]["id"]
    )
    failing_run = record_qc_run(
        env["device"]["id"], lot["id"], env["operator"]["id"], "LEVEL_1", 200.0
    )
    assert verified_lot["verification_status"] == "VERIFIED"
    assert sibling_level_two["result"] == "PASS"
    assert failing_run["result"] == "FAIL"
    assert failing_run["locked_device"] is True

    wrong_bench = api_client.qc_unlock_device(
        env["device"]["id"],
        qc_unlock_payload(
            sibling_level_two["id"], note="control from the bench next to it"
        ),
        COORDINATOR,
    )
    validate_error(wrong_bench, "ERR_QC_RUN_DEVICE_MISMATCH", 422)

    repeat_control = validate_success(
        api_client.create_qc_run(
            qc_run_payload(
                env["device"]["id"], lot["id"], env["operator"]["id"],
                "LEVEL_1", 101.0,
            ),
            make_operator_headers(env["operator"]["id"]),
        ),
        201,
    )
    unlocked = validate_success(
        api_client.qc_unlock_device(
            env["device"]["id"],
            qc_unlock_payload(
                repeat_control["id"],
                note="repeat control on the affected instrument",
            ),
            COORDINATOR,
        ),
        200,
    )

    assert repeat_control["result"] == "PASS"
    assert unlocked["status"] == "ACTIVE"
    assert unlocked["qc_lock_reason"] is None
    assert read_device(sibling["id"], COORDINATOR)["status"] == "ACTIVE"


def test_the_enrolment_key_is_the_whole_triple_of_site_analyte_and_year():
    """A different provider is still a duplicate; each key component frees it.

    PRD 3.7: "No two enrolments may share the same `site_id`, `analyte` and
    `program_year`, and a duplicate is refused with `ERR_DUPLICATE_ENROLLMENT`."

    Design: Corner/errors/duplicate_pt_enrollment_for_same_site_analyte_year_returns_409
    """
    set_clock(SEPTEMBER)
    site_a = create_site(name="Heme Clinic POCT", department_code="DEPT-3900")
    site_b = create_site(name="Travel Clinic POCT", department_code="DEPT-3901")
    first = enroll_pt(
        site_a["id"], analyte="GLUCOSE", program_year=2026, program_provider="AAB-PT"
    )
    assert first["status"] == "ENROLLED"
    assert first["graded_event_count"] == 0

    duplicate = api_client.create_pt_enrollment(
        pt_enrollment_payload(
            site_a["id"], analyte="GLUCOSE", program_year=2026,
            program_provider="API-PT",
        ),
        COORDINATOR,
    )
    other_year = enroll_pt(
        site_a["id"], analyte="GLUCOSE", program_year=2027, program_provider="AAB-PT"
    )
    other_analyte = enroll_pt(
        site_a["id"], analyte="HEMOGLOBIN_A1C", program_year=2026,
        program_provider="AAB-PT",
    )
    other_site = enroll_pt(
        site_b["id"], analyte="GLUCOSE", program_year=2026, program_provider="AAB-PT"
    )

    validate_error(duplicate, "ERR_DUPLICATE_ENROLLMENT", 409)
    assert len({
        first["id"], other_year["id"], other_analyte["id"], other_site["id"]
    }) == 4
    _rows_a, meta_a = validate_paginated(
        api_client.list_pt_enrollments(SURVEYOR, params={"site_id": site_a["id"]})
    )
    _rows_b, meta_b = validate_paginated(
        api_client.list_pt_enrollments(SURVEYOR, params={"site_id": site_b["id"]})
    )
    assert meta_a["total_count"] == 3
    assert meta_b["total_count"] == 1


def test_only_the_second_failure_closes_the_shipment_registration_endpoint():
    """One failure leaves the enrolment open; two of three shuts the door.

    PRD 3.7: "The enrolment must be `ENROLLED`, or the registration is refused with
    `ERR_PT_ENROLLMENT_STATUS_INVALID`."

    PRD 3.7: "**Investigation open.** When the outcome is `FAIL` and
    `fail_count_last_three` is below 2, the event moves `PENDING → INVESTIGATION_OPEN`
    with `outcome` of `FAIL` and `graded_on` recorded. The site's
    `pt_unsuccessful_count` rises by one and its `inspection_readiness_score` is
    recomputed. **No instrument is locked and the enrolment stays `ENROLLED`** — this is
    a single miss that must be explained, not a loss of testing privileges."

    Design: Corner/errors/pt_event_create_after_unsuccessful_participation_returns_enrollment_status_invalid
    """
    set_clock(SEPTEMBER)
    site = create_site(name="Diabetes Center POCT", department_code="DEPT-4000")
    enrollment = enroll_pt(
        site["id"], analyte="GLUCOSE", program_year=2026, program_provider="AAB-PT"
    )
    first_shipment = register_pt_event(
        enrollment["id"], 1, due_date="2026-04-30"
    )
    second_shipment = register_pt_event(
        enrollment["id"], 2, due_date="2026-08-31"
    )
    assert first_shipment["status"] == "PENDING"
    assert first_shipment["outcome"] is None

    first_grade = score_pt_event(
        first_shipment["id"], 70.00, graded_on="2026-05-10"
    )
    assert first_grade["outcome"] == "FAIL"
    assert first_grade["status"] == "INVESTIGATION_OPEN"
    after_one = validate_success(
        api_client.get_pt_enrollment(enrollment["id"], COORDINATOR)
    )
    assert after_one["status"] == "ENROLLED"
    assert after_one["fail_count_last_three"] == 1
    assert after_one["graded_event_count"] == 1

    second_grade = score_pt_event(
        second_shipment["id"], 65.00, graded_on="2026-09-01"
    )
    assert second_grade["outcome"] == "FAIL"
    assert second_grade["status"] == "UNSUCCESSFUL_LOCKED"
    after_two = validate_success(
        api_client.get_pt_enrollment(enrollment["id"], COORDINATOR)
    )
    assert after_two["status"] == "UNSUCCESSFUL_PARTICIPATION"
    assert after_two["fail_count_last_three"] == 2
    assert after_two["graded_event_count"] == 2

    response = api_client.create_pt_event(
        pt_event_payload(enrollment["id"], 3, due_date="2026-12-31"), COORDINATOR
    )

    validate_error(response, "ERR_PT_ENROLLMENT_STATUS_INVALID", 409)
    _rows, meta = validate_paginated(
        api_client.list_pt_events(
            SURVEYOR, params={"enrollment_id": enrollment["id"]}
        )
    )
    assert meta["total_count"] == 2
    assert read_site(site["id"])["pt_unsuccessful_count"] == 2


def test_an_approved_assessment_refuses_a_replayed_decision():
    """Rank 49 catches the second decision before it can touch the operator.

    PRD 2.7: "20. **Rank 49 — assessment pending.** A competency decision requires the
    assessment's `status` to be `SUBMITTED`. Otherwise `ERR_ASSESSMENT_NOT_SUBMITTED`
    (409)."

    PRD 3.3: "**On rejection** the assessment moves `SUBMITTED → REJECTED` and the
    subject's `consecutive_rejection_count` rises by one."

    Design: Corner/errors/second_decision_on_the_same_assessment_returns_assessment_not_submitted
    """
    _certificate, site, _coverage = setup_covered_site(
        clock=SEPTEMBER,
        certificate_overrides={"certificate_number": "45D2243045"},
        site_overrides={
            "name": "Anticoag Clinic POCT", "department_code": "DEPT-4100",
            "complexity_scope": "WAIVED",
        },
        coverage_overrides={"coverage_end": "2026-12-31"},
    )
    subject = create_trained_operator(
        site["id"], full_name="Gil Ramnarine",
        role_title="NURSE", hire_date="2026-01-05",
        training={"completed_on": "2026-08-20"},
    )
    assessor = create_trained_operator(
        site["id"], full_name="Hana Brzezinski",
        role_title="MEDICAL_TECHNOLOGIST", hire_date="2026-01-06",
        training={"completed_on": "2026-08-21"},
    )
    assert subject["competency_status"] == "PROVISIONAL"
    assessment = submit_assessment(
        subject["id"], assessor["id"],
        effective_date="2026-09-01", expires_at="2027-03-01",
    )
    assert assessment["status"] == "SUBMITTED"
    approved = decide_assessment(
        assessment["id"], "APPROVE", ADMIN, note="all six methods observed"
    )
    assert approved["status"] == "APPROVED"
    assert approved["decided_by_user_id"] == PROGRAM_ADMIN_USER_ID
    after_approval = read_operator(subject["id"])
    assert after_approval["competency_status"] == "COMPETENT"
    assert after_approval["competency_expires_at"] == "2027-03-01"
    assert after_approval["consecutive_rejection_count"] == 0

    response = api_client.decide_assessment(
        assessment["id"],
        assessment_decision_payload("REJECT", note="second reviewer disagrees"),
        ADMIN,
    )

    validate_error(response, "ERR_ASSESSMENT_NOT_SUBMITTED", 409)
    unchanged = read_assessment(assessment["id"])
    assert unchanged["status"] == "APPROVED"
    assert unchanged["decision_note"] == "all six methods observed"
    subject_after = read_operator(subject["id"])
    assert subject_after["competency_status"] == "COMPETENT"
    assert subject_after["consecutive_rejection_count"] == 0


def test_a_never_trained_assessor_is_a_competency_failure_not_an_access_one():
    """Rank 52 skips this endpoint, so the assessor's badge is beside the point.

    PRD 2.7: "23. **Rank 53 — operator competency.** On control-run recording,
    patient-result capture, posting and correction, the referenced operator's
    `competency_status` must be `PROVISIONAL` or `COMPETENT`. On competency-assessment
    submission this rung applies to the assessor named by `assessor_operator_id`, whose
    competency must be current for the attestation to count; rank 52 deliberately does
    not cover assessment submission, so a lapsed assessor surfaces as a competency
    failure rather than an access failure. Otherwise
    `ERR_OPERATOR_COMPETENCY_LAPSED` (422)."

    Design: Corner/errors/untrained_assessor_on_assessment_submission_returns_operator_competency_lapsed
    """
    _certificate, site, _coverage = setup_covered_site(
        clock=SEPTEMBER,
        certificate_overrides={"certificate_number": "45D2243046"},
        site_overrides={
            "name": "Employee Clinic POCT", "department_code": "DEPT-4200",
            "complexity_scope": "WAIVED",
        },
        coverage_overrides={"coverage_end": "2026-12-31"},
    )
    subject = create_trained_operator(
        site["id"], full_name="Ivo Kaczmarek",
        role_title="NURSE", hire_date="2026-01-05",
        training={"completed_on": "2026-08-20"},
    )
    assessor = create_operator(
        site["id"], full_name="Jo Villanueva",
        role_title="MEDICAL_TECHNOLOGIST", hire_date="2026-08-25",
    )
    assert assessor["competency_status"] == "PENDING"
    assert assessor["access_status"] == "LOCKED_OUT"
    subject_version = subject["version"]

    refused = api_client.create_assessment(
        assessment_payload(
            subject["id"], assessor["id"], subject_version,
            effective_date="2026-09-01", expires_at="2027-03-01",
        ),
        COORDINATOR,
    )
    validate_error(refused, "ERR_OPERATOR_COMPETENCY_LAPSED", 422)

    trained_assessor = validate_success(
        api_client.record_training(
            assessor["id"],
            training_payload(completed_on="2026-08-26"),
            COORDINATOR,
        ),
        200,
    )
    accepted = validate_success(
        api_client.create_assessment(
            assessment_payload(
                subject["id"], assessor["id"], subject_version,
                effective_date="2026-09-01", expires_at="2027-03-01",
            ),
            COORDINATOR,
        ),
        201,
    )

    assert trained_assessor["competency_status"] == "PROVISIONAL"
    assert trained_assessor["access_status"] == "ACTIVE"
    assert accepted["status"] == "SUBMITTED"
    _rows, meta = validate_paginated(
        api_client.list_assessments(ADMIN, params={"operator_id": subject["id"]})
    )
    assert meta["total_count"] == 1


def test_on_a_control_run_the_access_rung_beats_the_competency_rung():
    """The same untrained operator produces the opposite id from an assessment.

    PRD 2.7: "22. **Rank 52 — operator access.** On control-run recording,
    patient-result capture, posting and correction, the referenced operator — and, for
    posting and correction, the acting operator — must have `access_status` equal to
    `ACTIVE`. Otherwise `ERR_OPERATOR_ACCESS_LOCKED` (422)."

    PRD 3.3: "The new row starts `PENDING` and `LOCKED_OUT` with `lockout_reason` of
    `NEVER_TRAINED`, null `training_completed_at` and `training_module_code`, null
    `competency_expires_at` and `lapse_deadline`, `current_grace_days` of 0 and
    `consecutive_rejection_count` of 0."

    Design: Corner/errors/locked_out_operator_on_a_control_run_returns_operator_access_locked
    """
    _certificate, site, _coverage = setup_covered_site(
        clock=SEPTEMBER,
        certificate_overrides={"certificate_number": "45D2243047"},
        site_overrides={
            "name": "ENT Clinic POCT", "department_code": "DEPT-4300",
            "complexity_scope": "WAIVED",
        },
        coverage_overrides={"coverage_end": "2026-12-31"},
    )
    operator = create_operator(
        site["id"], full_name="Kai Oduya",
        role_title="MEDICAL_ASSISTANT", hire_date="2026-08-28",
    )
    device = create_device(site["id"], serial_number="SN-GL-4300")
    unit = create_storage_unit(site["id"], name="Reagent Fridge 1")
    lot = create_reagent_lot(
        site["id"], unit["id"], lot_number="LOT-A1",
        expiration_date="2027-01-31", received_at="2026-09-01T08:00:00Z",
    )
    assert operator["access_status"] == "LOCKED_OUT"
    assert operator["competency_status"] == "PENDING"

    refused = api_client.create_qc_run(
        qc_run_payload(device["id"], lot["id"], operator["id"], "LEVEL_1", 100.0),
        COORDINATOR,
    )
    validate_error(refused, "ERR_OPERATOR_ACCESS_LOCKED", 422)

    trained = validate_success(
        api_client.record_training(
            operator["id"], training_payload(completed_on="2026-08-31"), COORDINATOR
        ),
        200,
    )
    accepted = validate_success(
        api_client.create_qc_run(
            qc_run_payload(
                device["id"], lot["id"], operator["id"], "LEVEL_1", 100.0
            ),
            COORDINATOR,
        ),
        201,
    )

    assert trained["access_status"] == "ACTIVE"
    assert trained["competency_status"] == "PROVISIONAL"
    assert accepted["result"] == "PASS"
    _rows, meta = validate_paginated(
        api_client.list_qc_runs(ADMIN, params={"device_id": device["id"]})
    )
    assert meta["total_count"] == 1


def test_five_demonstrated_methods_is_well_formed_but_insufficient():
    """The schema accepts 5, the domain rule does not, and 6 is enough.

    PRD 3.3: "`methods_demonstrated` is an integer from 0 to 6 — the six CLIA
    competency elements — and at least 6 of them must have been demonstrated, or the
    submission fails with `ERR_INSUFFICIENT_COMPETENCY_METHODS`."

    PRD 2.7: "33. **Rank 63 — competency elements.** On competency-assessment
    submission, `methods_demonstrated` must be at least 6. Otherwise
    `ERR_INSUFFICIENT_COMPETENCY_METHODS` (422)."

    Design: Corner/errors/assessment_with_five_methods_returns_insufficient_competency_methods
    """
    _certificate, site, _coverage = setup_covered_site(
        clock=SEPTEMBER,
        certificate_overrides={"certificate_number": "45D2243048"},
        site_overrides={
            "name": "Neuro Clinic POCT", "department_code": "DEPT-4400",
            "complexity_scope": "WAIVED",
        },
        coverage_overrides={"coverage_end": "2026-12-31"},
    )
    subject = create_trained_operator(
        site["id"], full_name="Lena Ostrowski",
        role_title="NURSE", hire_date="2026-01-05",
        training={"completed_on": "2026-08-20"},
    )
    assessor = create_trained_operator(
        site["id"], full_name="Moss Adeyemi",
        role_title="MEDICAL_TECHNOLOGIST", hire_date="2026-01-06",
        training={"completed_on": "2026-08-21"},
    )
    subject_version = subject["version"]

    refused = api_client.create_assessment(
        assessment_payload(
            subject["id"], assessor["id"], subject_version,
            methods_demonstrated=5,
            effective_date="2026-09-01", expires_at="2027-03-01",
        ),
        COORDINATOR,
    )
    accepted = validate_success(
        api_client.create_assessment(
            assessment_payload(
                subject["id"], assessor["id"], subject_version,
                methods_demonstrated=6,
                effective_date="2026-09-01", expires_at="2027-03-01",
            ),
            COORDINATOR,
        ),
        201,
    )

    validate_error(refused, "ERR_INSUFFICIENT_COMPETENCY_METHODS", 422)
    assert accepted["methods_demonstrated"] == 6
    assert accepted["status"] == "SUBMITTED"
    _rows, meta = validate_paginated(
        api_client.list_assessments(ADMIN, params={"operator_id": subject["id"]})
    )
    assert meta["total_count"] == 1
