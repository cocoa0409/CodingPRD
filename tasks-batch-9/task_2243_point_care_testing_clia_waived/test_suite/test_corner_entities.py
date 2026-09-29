"""Entity shapes: computed fields, defaults, reads, listings and reference integrity."""

from test_helpers import (
    ADMIN,
    COORDINATOR,
    api_client,
    assert_append_only_record,
    assert_certificate,
    assert_coverage,
    assert_logical_instant,
    assert_operator,
    assert_qc_run_band,
    assert_site_invariants,
    certificate_payload,
    coverage_payload,
    create_certificate,
    create_operator,
    create_reagent_lot,
    create_site,
    create_storage_unit,
    device_payload,
    is_valid_uuid,
    operator_payload,
    qc_run_payload,
    read_certificate,
    read_device,
    read_site,
    record_qc_run,
    set_clock,
    setup_covered_site,
    setup_site_with_unverified_lot,
    validate_error,
    validate_paginated,
    validate_success,
)

SEPTEMBER = "2026-09-01T08:00:00Z"
SEPTEMBER_STAMP = "2026-09-01T08:00:00.000Z"
UNKNOWN_UUID = "00000000-0000-4000-8000-000000000000"


def test_a_registered_certificate_is_born_active_with_no_covered_sites():
    """The response carries computed fields rather than echoes of the request.

    PRD 3.1: "A certificate is born with `status` equal to `ACTIVE`, a null
    `suspension_reason` and a `covered_site_count` of 0."

    Design: Corner/entities/certificate_create_returns_201_with_computed_status_and_zero_covered_sites
    """
    set_clock(SEPTEMBER)

    created = validate_success(
        api_client.create_certificate(
            certificate_payload(
                certificate_number="45D2243001",
                certificate_type="CERTIFICATE_OF_COMPLIANCE",
                permitted_complexity="MODERATE",
                effective_date="2026-01-01",
                expiration_date="2027-12-31",
            ),
            ADMIN,
        ),
        201,
    )

    assert_certificate(created)
    assert created["status"] == "ACTIVE"
    assert created["covered_site_count"] == 0
    assert created["suspension_reason"] is None
    assert created["version"] == 1
    assert is_valid_uuid(created["id"])
    assert created["created_at"] == SEPTEMBER_STAMP
    assert created["certificate_number"] == "45D2243001"
    assert created["permitted_complexity"] == "MODERATE"
    assert created["expiration_date"] == "2027-12-31"


def test_a_covered_site_with_no_children_reads_every_counter_at_its_initial_value():
    """Nothing to penalise means both scores sit at a perfect 100.00.

    PRD 3.2: "At birth the site's `oversight_posture` is `OPEN`, its
    `manual_entry_blocked` is false, its `lab_director_operator_id` is null, its
    `scope_creep_flag` is false, its `last_oversight_run_at` is null, all of
    `open_deficiency_weight`, `held_result_count`, `total_operator_count`,
    `locked_out_operator_count`, `lapsed_or_locked_operator_count` and
    `pt_unsuccessful_count` are 0, and both `site_qc_compliance_index` and
    `inspection_readiness_score` sit at a perfect 100.00."

    Design: Corner/entities/get_site_returns_stored_inputs_and_initialised_counters
    """
    _certificate, site, _coverage = setup_covered_site(
        clock=SEPTEMBER,
        certificate_overrides={
            "certificate_number": "45D2243002",
            "certificate_type": "CERTIFICATE_OF_COMPLIANCE",
            "permitted_complexity": "MODERATE",
        },
        site_overrides={
            "name": "Emergency Department POCT",
            "department_code": "DEPT-200",
            "complexity_scope": "MODERATE",
        },
        coverage_overrides={"coverage_end": "2026-12-31"},
    )

    read_back = read_site(site["id"], COORDINATOR)

    assert_site_invariants(read_back)
    assert read_back["oversight_posture"] == "OPEN"
    assert read_back["manual_entry_blocked"] is False
    assert read_back["open_deficiency_weight"] == 0.00
    assert read_back["site_qc_compliance_index"] == 100.00
    assert read_back["inspection_readiness_score"] == 100.00
    assert read_back["held_result_count"] == 0
    assert read_back["name"] == "Emergency Department POCT"
    assert read_back["department_code"] == "DEPT-200"
    assert read_back["complexity_scope"] == "MODERATE"
    assert read_back["lab_director_operator_id"] is None
    assert read_back["last_oversight_run_at"] is None
    assert read_back["scope_creep_flag"] is False
    assert read_back["total_operator_count"] == 0
    assert read_back["locked_out_operator_count"] == 0
    assert read_back["lapsed_or_locked_operator_count"] == 0
    assert read_back["pt_unsuccessful_count"] == 0


def test_the_site_filtered_operator_pages_partition_three_of_four_rows():
    """total_count follows the filter, and the two pages carry no repeat.

    PRD 2.3: "Both appear in the response `meta` alongside `total_count` (the number
    of rows matching the request's filters, ignoring the page window) and `has_more`
    (true when rows remain beyond the current page)." and "The operator collection
    filters on `site_id`, `competency_status` and `access_status`."

    Design: Corner/entities/list_operators_filtered_by_site_paginates_with_total_count_and_has_more
    """
    set_clock(SEPTEMBER)
    site_a = create_site(name="Site A POCT", department_code="DEPT-301")
    site_b = create_site(name="Site B POCT", department_code="DEPT-302")
    operator_a = create_operator(
        site_a["id"], full_name="Ana Reyes",
        role_title="MEDICAL_ASSISTANT", hire_date="2026-02-01",
    )
    operator_b = create_operator(
        site_a["id"], full_name="Ben Ortiz",
        role_title="NURSE", hire_date="2026-03-01",
    )
    operator_c = create_operator(
        site_a["id"], full_name="Cara Lin",
        role_title="MEDICAL_TECHNOLOGIST", hire_date="2026-04-01",
    )
    operator_d = create_operator(
        site_b["id"], full_name="Dov Klein",
        role_title="NURSE", hire_date="2026-05-01",
    )

    first_response = api_client.list_operators(
        COORDINATOR, params={"site_id": site_a["id"], "limit": 2, "offset": 0}
    )
    second_response = api_client.list_operators(
        COORDINATOR, params={"site_id": site_a["id"], "limit": 2, "offset": 2}
    )

    page_one, meta_one = validate_paginated(first_response)
    page_two, meta_two = validate_paginated(second_response)
    assert meta_one["total_count"] == 3
    assert meta_one["has_more"] is True
    assert len(page_one) == 2
    assert meta_two["total_count"] == 3
    assert meta_two["has_more"] is False
    assert len(page_two) == 1
    seen = [row["id"] for row in page_one] + [row["id"] for row in page_two]
    assert len(seen) == len(set(seen))
    assert set(seen) == {operator_a["id"], operator_b["id"], operator_c["id"]}
    assert operator_d["id"] not in seen
    assert first_response.json()["response_type"] == "array"
    assert second_response.json()["response_type"] == "array"


def test_an_unknown_instrument_identifier_yields_the_instrument_scoped_404():
    """The device family is distinguished from the generic resource 404.

    PRD 2.6: "Four families are distinguished so that clients can tell what is
    missing: a `site_id` that does not resolve to a site yields
    `ERR_SITE_NOT_FOUND`; an `operator_id`, `assessor_operator_id` or
    `lab_director_operator_id` that does not resolve to an operator yields
    `ERR_OPERATOR_NOT_FOUND`; a `device_id` that does not resolve to an instrument
    yields `ERR_DEVICE_NOT_FOUND`; a `reagent_lot_id` that does not resolve to a
    reagent lot yields `ERR_REAGENT_LOT_NOT_FOUND`."

    Design: Corner/entities/get_device_with_unknown_uuid_returns_device_not_found
    """
    set_clock(SEPTEMBER)

    response = api_client.get_device(UNKNOWN_UUID, COORDINATOR)

    error = validate_error(response, "ERR_DEVICE_NOT_FOUND", 404)
    assert error["message"].strip() != ""
    assert response.json()["response_type"] == "error"


def test_a_site_submitted_without_a_department_code_is_refused_and_not_persisted():
    """A missing required field is a request-shape failure, not a null column.

    PRD 2.7: "**Rank 20 — request shape**, on every endpoint: required fields
    present, enum values in range, integers inside their declared bounds, dates
    well-formed `YYYY-MM-DD`, intervals not inverted, and every uniqueness
    constraint respected — `certificate_number` across certificates,
    `department_code` across sites, `serial_number` across instruments, the triple
    of `site_id` with `device_model` and `lot_number` across reagent lots, and the
    pair of `enrollment_id` with `shipment_number` across proficiency events.
    Otherwise `ERR_INVALID_REQUEST` (400)."

    Design: Corner/entities/site_create_without_department_code_returns_invalid_request
    """
    set_clock(SEPTEMBER)

    response = api_client.create_site(
        {"name": "Nephrology POCT", "complexity_scope": "WAIVED"}, ADMIN
    )

    validate_error(response, "ERR_INVALID_REQUEST", 400)
    _rows, meta = validate_paginated(api_client.list_sites(ADMIN))
    assert meta["total_count"] == 0


def test_a_new_hire_is_born_pending_and_locked_out_as_never_trained():
    """Both status dimensions and every training field start at their declared values.

    PRD 3.3: "The new row starts `PENDING` and `LOCKED_OUT` with `lockout_reason` of
    `NEVER_TRAINED`, null `training_completed_at` and `training_module_code`, null
    `competency_expires_at` and `lapse_deadline`, `current_grace_days` of 0 and
    `consecutive_rejection_count` of 0."

    Design: Corner/entities/operator_create_applies_pending_locked_out_never_trained_defaults
    """
    _certificate, site, _coverage = setup_covered_site(
        clock=SEPTEMBER,
        certificate_overrides={"certificate_number": "45D2243003"},
        site_overrides={
            "name": "Urgent Care POCT",
            "department_code": "DEPT-400",
            "complexity_scope": "WAIVED",
        },
        coverage_overrides={"coverage_end": "2026-12-31"},
    )

    created = validate_success(
        api_client.create_operator(
            operator_payload(
                site["id"], full_name="Ella Novak",
                role_title="MEDICAL_ASSISTANT", hire_date="2026-06-01",
            ),
            ADMIN,
        ),
        201,
    )

    assert_operator(created)
    assert created["competency_status"] == "PENDING"
    assert created["access_status"] == "LOCKED_OUT"
    assert created["lockout_reason"] == "NEVER_TRAINED"
    assert created["current_grace_days"] == 0
    assert created["lapse_deadline"] is None
    assert created["training_completed_at"] is None
    assert created["training_module_code"] is None
    assert created["competency_expires_at"] is None
    assert created["consecutive_rejection_count"] == 0


def test_the_lone_locked_out_hire_restricts_the_site_and_costs_it_the_competency_cap():
    """One locked-out operator out of one trips the strict majority and saturates 25.00.

    PRD 3.9: "Compute the competency gap percentage as one hundred multiplied by the
    site's `lapsed_or_locked_operator_count`, divided by its `total_operator_count`
    or by 1 when that count is 0 (whichever is larger). Multiply the gap percentage
    by 0.25, round half up to 2 decimals, and take the lesser of that and the cap of
    25.0."

    Design: Corner/entities/operator_create_applies_pending_locked_out_never_trained_defaults
    """
    _certificate, site, _coverage = setup_covered_site(
        clock=SEPTEMBER,
        certificate_overrides={"certificate_number": "45D2243003"},
        site_overrides={
            "name": "Urgent Care POCT",
            "department_code": "DEPT-400",
            "complexity_scope": "WAIVED",
        },
        coverage_overrides={"coverage_end": "2026-12-31"},
    )
    create_operator(
        site["id"], full_name="Ella Novak",
        role_title="MEDICAL_ASSISTANT", hire_date="2026-06-01",
    )

    read_back = read_site(site["id"], COORDINATOR)

    assert read_back["total_operator_count"] == 1
    assert read_back["locked_out_operator_count"] == 1
    assert read_back["lapsed_or_locked_operator_count"] == 1
    assert read_back["oversight_posture"] == "RESTRICTED"
    assert read_back["manual_entry_blocked"] is True
    assert read_back["inspection_readiness_score"] == 75.00


def test_the_coverage_snapshot_is_copied_from_the_certificate_not_the_site_scope():
    """A MODERATE-scoped site under a waiver still pins a WAIVED snapshot.

    PRD 3.1: "On success the row pins a `permitted_complexity_snapshot` copied from
    the certificate's `permitted_complexity` at that moment — a later amendment to
    the certificate never retroactively widens or narrows a coverage already granted
    — the certificate's `covered_site_count` rises by one, and the site's posture and
    `scope_creep_flag` are re-evaluated."

    Design: Corner/entities/coverage_snapshot_copies_certificate_complexity_not_site_scope
    """
    set_clock(SEPTEMBER)
    certificate = create_certificate(certificate_number="45D2243004")
    site = create_site(
        name="Oncology Infusion POCT", department_code="DEPT-500",
        complexity_scope="MODERATE",
    )

    coverage = validate_success(
        api_client.create_coverage(
            coverage_payload(
                site["id"], certificate["id"],
                coverage_start="2026-02-01", coverage_end="2026-12-31",
            ),
            ADMIN,
        ),
        201,
    )

    assert_coverage(coverage)
    assert coverage["permitted_complexity_snapshot"] == "WAIVED"
    assert coverage["coverage_start"] == "2026-02-01"
    assert coverage["coverage_end"] == "2026-12-31"
    assert read_certificate(certificate["id"])["covered_site_count"] == 1
    assert read_site(site["id"])["complexity_scope"] == "MODERATE"


def test_a_level_two_run_snapshots_the_level_two_band_and_locks_nothing():
    """The band comes from the lot's second pair, and one level never advances the horizon.

    PRD 3.4: "On acceptance the run snapshots the acceptance band it was judged
    against: `expected_min` and `expected_max` are copied from the lot's
    `control_min_level_1` and `control_max_level_1` when `control_level` is
    `LEVEL_1`, and from `control_min_level_2` and `control_max_level_2` when it is
    `LEVEL_2`."

    Design: Corner/entities/qc_run_snapshots_expected_bounds_from_the_lot_and_marks_locked_device
    """
    env = setup_site_with_unverified_lot(
        clock=SEPTEMBER,
        certificate_overrides={"certificate_number": "45D2243005"},
        site_overrides={
            "name": "Family Medicine POCT",
            "department_code": "DEPT-600",
            "complexity_scope": "WAIVED",
        },
        operator_overrides={"full_name": "Fay Duarte", "hire_date": "2026-01-15"},
        device_overrides={"serial_number": "SN-GL-0001"},
        lot_overrides={"lot_number": "LOT-A1", "expiration_date": "2027-01-31"},
    )

    run = record_qc_run(
        env["device"]["id"], env["lot"]["id"], env["operator"]["id"],
        "LEVEL_2", 300.0,
    )

    assert_qc_run_band(run, 250.0, 350.0)
    assert run["result"] == "PASS"
    assert run["locked_device"] is False
    assert_logical_instant(run["performed_at"], SEPTEMBER_STAMP)
    device = read_device(env["device"]["id"], COORDINATOR)
    assert device["status"] == "ACTIVE"
    assert device["qc_lock_reason"] is None
    assert device["last_two_level_qc_pass_on"] is None


def test_an_out_of_bounds_frequency_and_an_unknown_connectivity_mode_are_both_400():
    """A numeric bound and an enum closure are enforced together, before any 422.

    PRD 3.4: "An **instrument** is installed at a site by a `ProgramAdmin`, who
    supplies the `site_id`, the `device_model` string, a `serial_number` unique
    across the whole inventory, the `analyte` the instrument reports (for example
    `GLUCOSE` or `HBA1C`), a `complexity_class` of `WAIVED` or `MODERATE`, a
    `connectivity_mode` of `INTERFACED`, `MANUAL_ENTRY` or `OFFLINE`, and
    `qc_frequency_days` — the maximum whole number of days that may pass between
    passing two-level quality control, which must be at least 1."

    Design: Corner/entities/device_create_with_zero_qc_frequency_and_unknown_enum_returns_invalid_request
    """
    _certificate, site, _coverage = setup_covered_site(
        clock=SEPTEMBER,
        certificate_overrides={"certificate_number": "45D2243006"},
        site_overrides={
            "name": "Pediatrics POCT",
            "department_code": "DEPT-700",
            "complexity_scope": "WAIVED",
        },
        coverage_overrides={"coverage_end": "2026-12-31"},
    )

    bad_frequency = api_client.create_device(
        device_payload(
            site["id"], serial_number="SN-GL-0002", qc_frequency_days=0
        ),
        ADMIN,
    )
    bad_enum = api_client.create_device(
        device_payload(
            site["id"], serial_number="SN-GL-0003", connectivity_mode="BLUETOOTH"
        ),
        ADMIN,
    )

    validate_error(bad_frequency, "ERR_INVALID_REQUEST", 400)
    validate_error(bad_enum, "ERR_INVALID_REQUEST", 400)
    _rows, meta = validate_paginated(
        api_client.list_devices(ADMIN, params={"site_id": site["id"]})
    )
    assert meta["total_count"] == 0


def test_a_control_run_read_carries_only_an_identifier_and_a_creation_instant():
    """An append-only ledger row exposes no version and no update stamp.

    PRD 2.4: "Two record types are append-only and therefore carry neither
    `updated_at` nor `version`: a control run and a temperature reading. Both expose
    only `id` and `created_at`."

    Design: Corner/entities/qc_run_read_exposes_no_version_or_updated_at_and_has_no_update_endpoint
    """
    env = setup_site_with_unverified_lot(
        clock=SEPTEMBER,
        certificate_overrides={"certificate_number": "45D2243007"},
        site_overrides={
            "name": "Endocrinology POCT",
            "department_code": "DEPT-800",
            "complexity_scope": "WAIVED",
        },
        operator_overrides={"full_name": "Gus Marek", "hire_date": "2026-01-20"},
        device_overrides={"serial_number": "SN-GL-0010"},
        lot_overrides={"lot_number": "LOT-A1", "expiration_date": "2027-01-31"},
    )
    run = record_qc_run(
        env["device"]["id"], env["lot"]["id"], env["operator"]["id"],
        "LEVEL_1", 100.0,
    )

    read_back = validate_success(api_client.get_qc_run(run["id"], COORDINATOR), 200)

    assert_append_only_record(read_back, "qc_run")
    assert read_back["id"] == run["id"]
    assert read_back["created_at"] == SEPTEMBER_STAMP
    assert "version" not in read_back
    assert "updated_at" not in read_back


def test_an_operator_named_against_an_unknown_site_yields_the_site_scoped_404():
    """The foreign key is resolved before any field-shape check could complain.

    PRD 2.7: "**Rank 10 — site existence.** Applies to the single-site read, the
    readiness read, director assignment, coverage creation, operator creation, device
    installation, storage-unit registration, reagent-lot receipt, proficiency
    enrolment, survey creation and the site-scoped sub-resource reads. Otherwise
    `ERR_SITE_NOT_FOUND` (404)."

    Design: Corner/entities/operator_create_with_unknown_site_returns_site_not_found
    """
    set_clock(SEPTEMBER)

    response = api_client.create_operator(
        operator_payload(
            UNKNOWN_UUID, full_name="Hana Ito",
            role_title="NURSE", hire_date="2026-07-01",
        ),
        ADMIN,
    )

    error = validate_error(response, "ERR_SITE_NOT_FOUND", 404)
    assert error["message"].strip() != ""
    _rows, meta = validate_paginated(api_client.list_operators(ADMIN))
    assert meta["total_count"] == 0


def test_a_run_naming_an_instrument_and_a_lot_from_two_sites_is_refused():
    """Both rows carry the same instrument model, so the site mismatch is the failure.

    PRD 2.7: "**Rank 60 — one site per transaction.** On control-run recording,
    patient-result capture, lot receipt, competency-assessment submission, deficiency
    creation and director assignment, all cross-referenced rows must belong to the
    same site: the operator's `site_id` equals the device's, the lot's `site_id`
    equals the device's, the storage unit's `site_id` equals the lot's, the assessor's
    `site_id` equals the subject's, and a parent finding's `site_id` equals the
    inspection's. Otherwise `ERR_CROSS_SITE_REFERENCE` (422)."

    Design: Corner/entities/qc_run_with_lot_from_another_site_returns_cross_site_reference
    """
    env = setup_site_with_unverified_lot(
        clock=SEPTEMBER,
        certificate_overrides={"certificate_number": "45D2243008"},
        site_overrides={
            "name": "Site A POCT",
            "department_code": "DEPT-901",
            "complexity_scope": "WAIVED",
        },
        operator_overrides={"full_name": "Iris Cole", "hire_date": "2026-02-10"},
        device_overrides={"serial_number": "SN-GL-0020"},
        lot_overrides={"lot_number": "LOT-A1", "expiration_date": "2027-01-31"},
    )
    site_b = create_site(name="Site B POCT", department_code="DEPT-902")
    unit_b = create_storage_unit(site_b["id"], name="Site B Fridge")
    lot_b = create_reagent_lot(
        site_b["id"], unit_b["id"],
        lot_number="LOT-B1", expiration_date="2027-01-31",
    )

    response = api_client.create_qc_run(
        qc_run_payload(
            env["device"]["id"], lot_b["id"], env["operator"]["id"],
            "LEVEL_1", 100.0,
        ),
        {"X-User-ID": env["operator"]["id"], "X-User-Role": "Operator"},
    )

    error = validate_error(response, "ERR_CROSS_SITE_REFERENCE", 422)
    assert error["message"].strip() != ""
    _rows, meta = validate_paginated(
        api_client.list_qc_runs(ADMIN, params={"device_id": env["device"]["id"]})
    )
    assert meta["total_count"] == 0
    assert read_device(env["device"]["id"])["status"] == "ACTIVE"
