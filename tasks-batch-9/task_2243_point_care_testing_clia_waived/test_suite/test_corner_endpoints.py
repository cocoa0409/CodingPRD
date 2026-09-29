"""Route-level round trips: partial CRUD surfaces, computed reads and link creation."""

from test_helpers import (
    ADMIN,
    COORDINATOR,
    SURVEYOR,
    add_finding,
    api_client,
    assert_readiness_breakdown,
    assert_readiness_score_consistent,
    assert_storage_unit,
    coverage_payload,
    create_certificate,
    create_coverage,
    create_device,
    create_moderate_certificate,
    create_operator,
    create_reagent_lot,
    create_site,
    create_storage_unit,
    create_trained_operator,
    issue_survey,
    open_survey,
    qc_unlock_payload,
    read_certificate,
    read_device,
    read_readiness,
    read_site,
    read_storage_unit,
    run_oversight,
    set_clock,
    storage_unit_payload,
    validate_error,
    validate_paginated,
    validate_success,
    verify_lot,
)

SEPTEMBER = "2026-09-01T08:00:00Z"
SEPTEMBER_STAMP = "2026-09-01T08:00:00.000Z"
UNKNOWN_SITE = "6f1d0c2b-0000-4000-8000-00000000dead"
UNKNOWN_CERTIFICATE = "6f1d0c2b-0000-4000-8000-00000000beef"


def test_a_storage_unit_round_trips_through_its_read_and_two_list_routes():
    """Create, read, filtered list and site-scoped list all agree; site B stays out.

    PRD 3.5: "A **storage unit** is a refrigerator or cabinet registered by a
    `ProgramAdmin` with its `site_id`, a `name` for the label on the door, and the
    inclusive bounds of its acceptable band as `min_temp_c` and `max_temp_c`, where
    `max_temp_c` must be strictly greater than `min_temp_c`. A new unit has
    `excursion_state` of `IN_RANGE`, a null `excursion_opened_at`, a null
    `last_reading_c` and a `quarantined_lot_count` of 0."

    PRD 2.3: "The storage-unit collection filters on `site_id`." and "Both appear in
    the response `meta` alongside `total_count` (the number of rows matching the
    request's filters, ignoring the page window) and `has_more` (true when rows remain
    beyond the current page)."

    Design: Corner/endpoints/storage_unit_create_read_and_filtered_list_round_trip
    """
    set_clock(SEPTEMBER)
    site_a = create_site(name="Cardiology POCT", department_code="DEPT-2700")
    site_b = create_site(name="Oncology POCT", department_code="DEPT-2701")

    fridge = validate_success(
        api_client.create_storage_unit(
            storage_unit_payload(
                site_a["id"], name="Fridge A1", min_temp_c=2.0, max_temp_c=8.0
            ),
            ADMIN,
        ),
        201,
    )
    freezer = validate_success(
        api_client.create_storage_unit(
            storage_unit_payload(
                site_a["id"], name="Freezer A2", min_temp_c=-25.0, max_temp_c=-15.0
            ),
            ADMIN,
        ),
        201,
    )
    other_site_fridge = create_storage_unit(
        site_b["id"], name="Fridge B1", min_temp_c=2.0, max_temp_c=8.0
    )

    assert_storage_unit(fridge)
    assert fridge["excursion_state"] == "IN_RANGE"
    assert fridge["excursion_opened_at"] is None
    assert fridge["last_reading_c"] is None
    assert fridge["quarantined_lot_count"] == 0
    assert fridge["created_at"] == SEPTEMBER_STAMP
    assert fridge["min_temp_c"] == 2.0
    assert fridge["max_temp_c"] == 8.0
    assert freezer["min_temp_c"] == -25.0
    assert freezer["max_temp_c"] == -15.0

    read_back = read_storage_unit(fridge["id"], COORDINATOR)
    assert read_back["id"] == fridge["id"]
    assert read_back["name"] == "Fridge A1"
    assert read_back["site_id"] == site_a["id"]
    assert read_back["min_temp_c"] == 2.0
    assert read_back["excursion_state"] == "IN_RANGE"
    assert read_back["last_reading_c"] is None

    filtered, meta = validate_paginated(
        api_client.list_storage_units(COORDINATOR, params={"site_id": site_a["id"]})
    )
    assert meta["total_count"] == 2
    assert meta["has_more"] is False
    assert {row["id"] for row in filtered} == {fridge["id"], freezer["id"]}
    assert other_site_fridge["id"] not in {row["id"] for row in filtered}

    scoped, scoped_meta = validate_paginated(
        api_client.list_site_storage_units(site_b["id"], SURVEYOR)
    )
    assert scoped_meta["total_count"] == 1
    assert scoped[0]["id"] == other_site_fridge["id"]


def test_the_readiness_read_breaks_out_four_terms_that_reconcile_to_the_stored_score():
    """Two live penalties, a capped competency term, and a perfect device-free index.

    PRD 3.9: "1. **Deficiency penalty.** Multiply the open deficiency weight by 2.5,
    round the product half up to 2 decimals, and take the lesser of that and the cap of
    50.0." and "2. **Competency penalty.** Compute the competency gap percentage as
    one hundred multiplied by the site's `lapsed_or_locked_operator_count`, divided by
    its `total_operator_count` or by 1 when that count is 0 (whichever is larger).
    Multiply the gap percentage by 0.25, round half up to 2 decimals, and take the
    lesser of that and the cap of 25.0." and "3. **Quality-control penalty.** Subtract
    the site's `site_qc_compliance_index` from 100.0, multiply the difference by 0.40,
    round half up to 2 decimals, and take the lesser of that and the cap of 20.0. A
    site with no non-retired instrument has an index of 100.00 and so takes a penalty
    of 0.00."

    PRD 3.9: "The response reports the `basis` actually used, the resulting `score`,
    the four components as `deficiency_penalty`, `competency_penalty`, `qc_penalty` and
    `pt_penalty`, the three headline inputs `open_deficiency_weight`,
    `pt_unsuccessful_count` and `site_qc_compliance_index`, and the `computed_at`
    instant of the evaluation."

    Design: Corner/endpoints/readiness_read_returns_every_penalty_term_and_matches_the_persisted_score
    """
    set_clock(SEPTEMBER)
    certificate = create_certificate(certificate_number="45D2243034")
    site = create_site(name="Wound Care POCT", department_code="DEPT-2800")
    create_coverage(
        site["id"], certificate["id"],
        coverage_start="2026-01-01", coverage_end="2026-12-31",
    )
    operator = create_operator(
        site["id"], full_name="Zoe Aldridge",
        role_title="NURSE", hire_date="2026-08-01",
    )
    assert operator["access_status"] == "LOCKED_OUT"
    assert operator["lockout_reason"] == "NEVER_TRAINED"
    survey = open_survey(
        site["id"], SURVEYOR,
        inspection_type="BIENNIAL_SURVEY", scheduled_date="2026-09-01",
    )
    draft = add_finding(
        survey["id"], SURVEYOR,
        category="PERSONNEL_COMPETENCY", severity="CONDITION_LEVEL",
        description="no competency record on file for the only testing operator",
        correction_due_date="2026-10-01",
    )
    assert draft["status"] == "DRAFT"
    assert draft["weight"] == 0
    issued = issue_survey(survey["id"], SURVEYOR, issued_on="2026-09-01")
    assert issued["issued_weight_total"] == 8.00

    breakdown = read_readiness(site["id"], SURVEYOR)
    projected = read_readiness(
        site["id"], SURVEYOR, basis="PRE_SURVEY_PROJECTED"
    )

    assert_readiness_breakdown(breakdown)
    assert_readiness_score_consistent(breakdown)
    assert breakdown["basis"] == "AS_OF_ACTUAL"
    assert breakdown["computed_at"] == SEPTEMBER_STAMP
    assert breakdown["deficiency_penalty"] == 20.00
    assert breakdown["competency_penalty"] == 25.00
    assert breakdown["qc_penalty"] == 0.00
    assert breakdown["site_qc_compliance_index"] == 100.00
    assert breakdown["pt_penalty"] == 0.00
    assert breakdown["pt_unsuccessful_count"] == 0
    assert breakdown["open_deficiency_weight"] == 8.00
    assert breakdown["score"] == 55.00
    assert projected["basis"] == "PRE_SURVEY_PROJECTED"
    assert projected["open_deficiency_weight"] == 8.00
    assert projected["score"] == 55.00
    assert issued["readiness_score_at_issue"] == 55.00

    site_after = read_site(site["id"], COORDINATOR)
    assert site_after["inspection_readiness_score"] == 55.00
    assert site_after["open_deficiency_weight"] == 8.00
    assert site_after["oversight_posture"] == "RESTRICTED"
    assert site_after["total_operator_count"] == 1
    assert site_after["lapsed_or_locked_operator_count"] == 1


def test_a_scope_lock_survives_a_flawless_unlock_request():
    """The confirming run passes on a verified lot, and the unlock is still refused.

    PRD 3.4: "The instrument must be `QC_LOCKED`; the confirming run must belong to
    that instrument, must have `result` of `PASS`, and must reference a lot whose
    `verification_status` is `VERIFIED`; and the instrument's `qc_lock_reason` must not
    be `CERTIFICATE_SCOPE`, because a certificate-scope violation is a paperwork
    problem that no amount of good quality control can clear — attempting it yields
    `ERR_INVALID_STATE`."

    PRD 3.9: "5. Scope creep is detected: every instrument whose `status` is `ACTIVE`
    and whose `complexity_class` is `MODERATE`, sitting at a site whose in-window
    active coverage carries a `permitted_complexity_snapshot` of `WAIVED`, moves to
    `QC_LOCKED` with `qc_lock_reason` of `CERTIFICATE_SCOPE`, and the site's
    `scope_creep_flag` is set true."

    Design: Corner/endpoints/qc_unlock_refused_when_lock_reason_is_certificate_scope
    """
    set_clock("2026-06-15T08:00:00Z")
    moderate_certificate = create_moderate_certificate(
        certificate_number="45D2243035",
        effective_date="2026-01-01", expiration_date="2026-06-30",
    )
    waiver_certificate = create_certificate(
        certificate_number="45D2243036",
        effective_date="2026-01-01", expiration_date="2027-12-31",
    )
    site = create_site(
        name="Hospitalist POCT", department_code="DEPT-2900",
        complexity_scope="MODERATE",
    )
    moderate_coverage = create_coverage(
        site["id"], moderate_certificate["id"],
        coverage_start="2026-01-01", coverage_end="2026-06-30",
    )
    operator = create_trained_operator(
        site["id"], full_name="Abe Lindqvist",
        role_title="MEDICAL_TECHNOLOGIST", hire_date="2026-01-05",
        training={
            "training_module_code": "POCT-CHEM-201", "completed_on": "2026-06-01"
        },
    )
    device = create_device(
        site["id"], device_model="CHEM-14", serial_number="SN-CH-2900",
        analyte="CREATININE", complexity_class="MODERATE",
        connectivity_mode="INTERFACED", qc_frequency_days=30,
    )
    unit = create_storage_unit(site["id"], name="Reagent Fridge 1")
    lot = create_reagent_lot(
        site["id"], unit["id"], device_model="CHEM-14", lot_number="LOT-C1",
        expiration_date="2027-01-31", received_at="2026-06-15T08:00:00Z",
    )
    verified_lot, _level_one, confirming_run = verify_lot(
        lot["id"], device["id"], operator["id"]
    )
    waiver_coverage = create_coverage(
        site["id"], waiver_certificate["id"],
        coverage_start="2026-07-02", coverage_end="2026-12-31",
    )
    assert moderate_coverage["permitted_complexity_snapshot"] == "MODERATE"
    assert waiver_coverage["permitted_complexity_snapshot"] == "WAIVED"
    assert device["status"] == "ACTIVE"
    assert confirming_run["result"] == "PASS"
    assert verified_lot["verification_status"] == "VERIFIED"

    set_clock("2026-07-05T09:00:00Z")
    summary = run_oversight(note="scheduled sweep after the moderate certificate died")

    assert summary["certificates_expired"] == 1
    assert summary["scope_creep_sites"] == 1
    assert summary["devices_qc_locked"] == 1
    locked = read_device(device["id"], COORDINATOR)
    assert locked["status"] == "QC_LOCKED"
    assert locked["qc_lock_reason"] == "CERTIFICATE_SCOPE"

    response = api_client.qc_unlock_device(
        device["id"],
        qc_unlock_payload(
            confirming_run["id"], note="control repeated and in range"
        ),
        COORDINATOR,
    )

    validate_error(response, "ERR_INVALID_STATE", 409)
    unchanged = read_device(device["id"], COORDINATOR)
    assert unchanged["status"] == "QC_LOCKED"
    assert unchanged["qc_lock_reason"] == "CERTIFICATE_SCOPE"
    assert read_site(site["id"], COORDINATOR)["scope_creep_flag"] is True


def test_the_coverage_link_needs_both_ends_and_the_two_dangling_ends_differ():
    """A missing site is site-scoped; a missing certificate falls back to the generic id.

    PRD 2.6: "a `site_id` that does not resolve to a site yields
    `ERR_SITE_NOT_FOUND`; an `operator_id`, `assessor_operator_id` or
    `lab_director_operator_id` that does not resolve to an operator yields
    `ERR_OPERATOR_NOT_FOUND`; a `device_id` that does not resolve to an instrument
    yields `ERR_DEVICE_NOT_FOUND`; a `reagent_lot_id` that does not resolve to a
    reagent lot yields `ERR_REAGENT_LOT_NOT_FOUND`."

    PRD 2.6: "Every other reference — a certificate, a coverage row, a competency
    assessment, a storage unit, a control run, a patient result, a proficiency
    enrolment, a proficiency event, an inspection or a deficiency finding, whether
    addressed by path or named in a body field such as `confirming_qc_run_id`,
    `level_1_qc_run_id`, `level_2_qc_run_id`, `enrollment_id`, `inspection_id`,
    `parent_finding_id`, `certificate_id` or `storage_unit_id` — yields
    `ERR_RESOURCE_NOT_FOUND` when it does not resolve."

    PRD 3.1: "On success the row pins a `permitted_complexity_snapshot` copied from the
    certificate's `permitted_complexity` at that moment — a later amendment to the
    certificate never retroactively widens or narrows a coverage already granted — the
    certificate's `covered_site_count` rises by one, and the site's posture and
    `scope_creep_flag` are re-evaluated."

    Design: Corner/endpoints/coverage_create_requires_both_site_and_certificate_to_resolve
    """
    set_clock(SEPTEMBER)
    certificate = create_certificate(certificate_number="45D2243037")
    site = create_site(
        name="Occupational Health POCT", department_code="DEPT-3000"
    )
    assert certificate["covered_site_count"] == 0

    dangling_site = api_client.create_coverage(
        coverage_payload(
            UNKNOWN_SITE, certificate["id"],
            coverage_start="2026-01-01", coverage_end="2026-12-31",
        ),
        ADMIN,
    )
    dangling_certificate = api_client.create_coverage(
        coverage_payload(
            site["id"], UNKNOWN_CERTIFICATE,
            coverage_start="2026-01-01", coverage_end="2026-12-31",
        ),
        ADMIN,
    )
    coverage = validate_success(
        api_client.create_coverage(
            coverage_payload(
                site["id"], certificate["id"],
                coverage_start="2026-01-01", coverage_end="2026-12-31",
            ),
            ADMIN,
        ),
        201,
    )

    validate_error(dangling_site, "ERR_SITE_NOT_FOUND", 404)
    validate_error(dangling_certificate, "ERR_RESOURCE_NOT_FOUND", 404)
    assert coverage["site_id"] == site["id"]
    assert coverage["certificate_id"] == certificate["id"]
    assert coverage["permitted_complexity_snapshot"] == "WAIVED"
    assert read_certificate(certificate["id"])["covered_site_count"] == 1
    rows, meta = validate_paginated(
        api_client.list_coverages(
            SURVEYOR, params={"certificate_id": certificate["id"]}
        )
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == coverage["id"]
    assert read_site(site["id"])["oversight_posture"] == "OPEN"
