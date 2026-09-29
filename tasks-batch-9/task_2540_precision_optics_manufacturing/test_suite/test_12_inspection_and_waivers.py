"""Cleanroom inspection verdicts, waivability and the seal gate they guard."""

from test_helpers import (
    DEFAULT_CLEANLINESS_LIMIT_PER_CM2,
    DEFAULT_SCRATCH_DIG_DIG_LIMIT,
    DEFAULT_SCRATCH_DIG_SCRATCH_LIMIT,
    ERR_DEFECT_NOT_WAIVABLE,
    ERR_INSPECTION_NOT_PASSED,
    ERR_SEGREGATION_OF_DUTIES,
    MAX_SCRATCHES_AT_LIMIT,
    MT_RECORDER,
    QM_PRIMARY,
    QM_SECOND,
    QM_THIRD,
    WAIVER_LIMIT_MULTIPLE,
    assert_row_ids,
    assert_wavefront_value,
    build_inspection_record_payload,
    build_waiver_payload,
    make_metrology_technician_headers,
    make_process_technician_headers,
    make_quality_manager_headers,
    setup_aligned_assembly,
    setup_mounted_assembly,
    validate_error,
    validate_paginated,
    validate_success,
)

SINGLE_ELEMENT_SPECS = (
    {
        "slot_index": 1,
        "decenter_um": 10.0,
        "tilt_arcmin": 1.0,
        "element_wavefront_rms_waves": 0.0600,
    },
)


def _read_assembly(api, assembly_id):
    """Read one assembly with its wavefront roll-up."""
    return validate_success(
        api.get_assembly(assembly_id, make_process_technician_headers()),
        expected_status=200,
    )


def _read_record(api, record_id, reader_id=QM_THIRD):
    """Read one cleanroom inspection record."""
    return validate_success(
        api.get_inspection_record(record_id, make_quality_manager_headers(reader_id)),
        expected_status=200,
    )


def _inspect(api, assembly_id, headers=None, **overrides):
    """Record one inspection, returning the created record."""
    return validate_success(
        api.create_inspection_record(
            build_inspection_record_payload(assembly_id, **overrides),
            headers or make_metrology_technician_headers(MT_RECORDER),
        ),
        expected_status=201,
    )


def _waive(api, record_id, actor_id):
    """Attempt a waiver on one record, returning the raw response."""
    return api.waive_inspection_record(
        record_id, build_waiver_payload(), make_quality_manager_headers(actor_id)
    )


def _seal(api, assembly_id):
    """Attempt to seal an assembly as the ProcessTechnician, raw response."""
    return api.seal_assembly(assembly_id, make_process_technician_headers())


def _records(api, assembly_id, params=None):
    """List the inspection records of an assembly, rows and pagination meta."""
    return validate_paginated(
        api.list_assembly_inspection_records(
            assembly_id, make_quality_manager_headers(QM_THIRD), params=params
        )
    )


def test_the_scratch_dig_verdict_applies_all_four_inclusive_comparisons(api):
    """Three records separate the two booleans and both of their bounds.

    The PRD states that "`scratch_dig_pass` is true when `max_scratch_number` is at
    most the design's `scratch_dig_scratch_limit`, `max_dig_number` is at most the
    design's `scratch_dig_dig_limit`, **and** `scratch_count_at_limit` is at most two —
    the cosmetic specification tolerates a scratch at the limit, and a second one, but
    not a third." and that "`cleanliness_pass` is true when `particle_count_per_cm2` is
    at most the design's `cleanliness_limit_per_cm2`."

    Design: Corner/calculations/scratch_dig_verdict_applies_all_four_inclusive_comparisons
    """
    ctx = setup_mounted_assembly(api, component_specs=SINGLE_ELEMENT_SPECS)
    assembly_id = ctx["assembly"]["id"]
    design = ctx["design"]
    assert design["scratch_dig_scratch_limit"] == DEFAULT_SCRATCH_DIG_SCRATCH_LIMIT
    assert design["scratch_dig_dig_limit"] == DEFAULT_SCRATCH_DIG_DIG_LIMIT
    assert design["cleanliness_limit_per_cm2"] == DEFAULT_CLEANLINESS_LIMIT_PER_CM2

    on_every_bound = _inspect(
        api,
        assembly_id,
        max_scratch_number=DEFAULT_SCRATCH_DIG_SCRATCH_LIMIT,
        max_dig_number=DEFAULT_SCRATCH_DIG_DIG_LIMIT,
        particle_count_per_cm2=DEFAULT_CLEANLINESS_LIMIT_PER_CM2,
        scratch_count_at_limit=MAX_SCRATCHES_AT_LIMIT,
    )
    third_at_the_limit = _inspect(
        api,
        assembly_id,
        max_scratch_number=DEFAULT_SCRATCH_DIG_SCRATCH_LIMIT,
        max_dig_number=DEFAULT_SCRATCH_DIG_DIG_LIMIT,
        particle_count_per_cm2=DEFAULT_CLEANLINESS_LIMIT_PER_CM2,
        scratch_count_at_limit=MAX_SCRATCHES_AT_LIMIT + 1,
    )
    one_particle_over = _inspect(
        api,
        assembly_id,
        max_scratch_number=DEFAULT_SCRATCH_DIG_SCRATCH_LIMIT,
        max_dig_number=DEFAULT_SCRATCH_DIG_DIG_LIMIT,
        particle_count_per_cm2=DEFAULT_CLEANLINESS_LIMIT_PER_CM2 + 1,
        scratch_count_at_limit=MAX_SCRATCHES_AT_LIMIT,
    )

    assert on_every_bound["scratch_dig_pass"] is True, (
        "40 scratches, 20 digs and two at the limit sit exactly on every bound, got "
        f"{on_every_bound['scratch_dig_pass']}"
    )
    assert on_every_bound["cleanliness_pass"] is True, (
        f"50 particles sit on the limit, got {on_every_bound['cleanliness_pass']}"
    )
    assert on_every_bound["inspection_status"] == "PASSED", (
        f"inspection_status must be PASSED, got {on_every_bound['inspection_status']}"
    )
    assert on_every_bound["inspected_by_user_id"] == MT_RECORDER, (
        "inspected_by_user_id is the acting operator, got "
        f"{on_every_bound['inspected_by_user_id']}"
    )
    assert on_every_bound["waived_by_user_id"] is None
    assert on_every_bound["waiver_justification"] is None

    assert third_at_the_limit["scratch_dig_pass"] is False, (
        "a third scratch at the limit breaks the cosmetic gate, got "
        f"{third_at_the_limit['scratch_dig_pass']}"
    )
    assert third_at_the_limit["cleanliness_pass"] is True, (
        f"the particulate count is untouched, got {third_at_the_limit['cleanliness_pass']}"
    )
    assert third_at_the_limit["inspection_status"] == "FAILED", (
        f"inspection_status must be FAILED, got {third_at_the_limit['inspection_status']}"
    )

    assert one_particle_over["scratch_dig_pass"] is True, (
        f"the cosmetic numbers still hold, got {one_particle_over['scratch_dig_pass']}"
    )
    assert one_particle_over["cleanliness_pass"] is False, (
        "51 particles exceed the limit of 50, got "
        f"{one_particle_over['cleanliness_pass']}"
    )
    assert one_particle_over["inspection_status"] == "FAILED", (
        f"inspection_status must be FAILED, got {one_particle_over['inspection_status']}"
    )

    rows, meta = _records(api, assembly_id)
    assert_row_ids(
        rows,
        [
            on_every_bound["id"],
            third_at_the_limit["id"],
            one_particle_over["id"],
        ],
        "the inspection listing",
    )
    assert meta["total_count"] == 3, (
        f"total_count must be 3, got {meta['total_count']}"
    )
    assembly = _read_assembly(api, assembly_id)
    assert assembly["assembly_status"] == "MOUNTED", (
        "recording an inspection does not move the assembly, got "
        f"{assembly['assembly_status']}"
    )


def test_a_waiver_is_refused_beyond_twice_the_limit_and_on_a_cleanliness_failure(api):
    """The defect multiple is inclusive and the cleanliness condition is a veto.

    The PRD states that "The defect must be waivable at all: `cleanliness_pass` must be
    true — particulate contamination is never waivable, only cosmetic defects are — and
    both `max_dig_number` and `max_scratch_number` must be within **twice** the design's
    respective limits, otherwise `ERR_DEFECT_NOT_WAIVABLE`." and that "So a design with
    a dig limit of 20 admits a waiver up to and including dig 40 and refuses dig 41."

    Design: Corner/validations/a_waiver_is_refused_beyond_twice_the_limit_and_on_a_cleanliness_failure
    """
    ctx = setup_aligned_assembly(api, component_specs=SINGLE_ELEMENT_SPECS)
    assembly_id = ctx["assembly"]["id"]
    twice_the_dig_limit = DEFAULT_SCRATCH_DIG_DIG_LIMIT * WAIVER_LIMIT_MULTIPLE

    one_dig_too_many = _inspect(
        api, assembly_id, max_dig_number=twice_the_dig_limit + 1
    )
    dirty = _inspect(
        api,
        assembly_id,
        particle_count_per_cm2=DEFAULT_CLEANLINESS_LIMIT_PER_CM2 + 10,
    )
    exactly_twice = _inspect(api, assembly_id, max_dig_number=twice_the_dig_limit)

    for record in (one_dig_too_many, dirty, exactly_twice):
        assert record["inspection_status"] == "FAILED", (
            f"record {record['id']} must be FAILED, got {record['inspection_status']}"
        )
    assert one_dig_too_many["cleanliness_pass"] is True
    assert dirty["cleanliness_pass"] is False, (
        f"sixty particles fail cleanliness, got {dirty['cleanliness_pass']}"
    )
    assert exactly_twice["cleanliness_pass"] is True

    refused_on_digs = _waive(api, one_dig_too_many["id"], QM_SECOND)
    refused_on_particles = _waive(api, dirty["id"], QM_SECOND)
    granted = _waive(api, exactly_twice["id"], QM_SECOND)

    validate_error(refused_on_digs, ERR_DEFECT_NOT_WAIVABLE)
    validate_error(refused_on_particles, ERR_DEFECT_NOT_WAIVABLE)
    waived = validate_success(granted, expected_status=200)
    assert waived["inspection_status"] == "WAIVED", (
        f"forty digs is exactly twice the limit, got {waived['inspection_status']}"
    )
    assert waived["waived_by_user_id"] == QM_SECOND, (
        f"waived_by_user_id must be the acting manager, got {waived['waived_by_user_id']}"
    )
    still_failed = _read_record(api, one_dig_too_many["id"], QM_SECOND)
    assert still_failed["inspection_status"] == "FAILED", (
        f"a refused waiver leaves the record FAILED, got {still_failed['inspection_status']}"
    )
    assert still_failed["waived_by_user_id"] is None
    assert still_failed["waiver_justification"] is None

    sealed = validate_success(_seal(api, assembly_id), expected_status=200)

    assert sealed["assembly_status"] == "SEALED", (
        "the latest record is the waived one, so the seal passes, got "
        f"{sealed['assembly_status']}"
    )


def test_seal_demands_a_passed_or_waived_inspection_and_accepts_a_waiver(api):
    """No record, then a failed one, then the same record waived.

    The PRD states that sealing "requires that the assembly has at least one inspection
    record and that its **latest** record by `created_at` is in `PASSED` or `WAIVED`; if
    no record exists, or the latest one is `FAILED`, the request is refused with
    `ERR_INSPECTION_NOT_PASSED`." and that "A granted waiver moves the record
    `FAILED → WAIVED`, records `waived_by_user_id` from the acting `X-User-ID` and
    stores the text in `waiver_justification`."

    Design: Corner/validations/seal_demands_a_passed_or_waived_inspection_and_accepts_a_waiver
    """
    ctx = setup_aligned_assembly(api, component_specs=SINGLE_ELEMENT_SPECS)
    assembly_id = ctx["assembly"]["id"]
    assert_wavefront_value(
        ctx["aligned"]["total_transmitted_wavefront_waves"],
        0.0804,
        "total_transmitted_wavefront_waves",
    )

    without_a_record = _seal(api, assembly_id)

    validate_error(without_a_record, ERR_INSPECTION_NOT_PASSED)

    record = _inspect(
        api,
        assembly_id,
        max_scratch_number=DEFAULT_SCRATCH_DIG_SCRATCH_LIMIT + 5,
        max_dig_number=3,
        particle_count_per_cm2=20,
    )

    assert record["inspection_status"] == "FAILED", (
        f"45 scratches against a limit of 40 fails, got {record['inspection_status']}"
    )
    assert record["scratch_dig_pass"] is False, (
        f"scratch_dig_pass must be False, got {record['scratch_dig_pass']}"
    )
    assert record["cleanliness_pass"] is True, (
        f"cleanliness_pass must be True, got {record['cleanliness_pass']}"
    )

    with_a_failed_record = _seal(api, assembly_id)

    validate_error(with_a_failed_record, ERR_INSPECTION_NOT_PASSED)

    waived = validate_success(_waive(api, record["id"], QM_SECOND), expected_status=200)

    assert waived["inspection_status"] == "WAIVED", (
        f"inspection_status must be WAIVED, got {waived['inspection_status']}"
    )
    assert waived["waived_by_user_id"] == QM_SECOND, (
        f"waived_by_user_id must be the granting manager, got {waived['waived_by_user_id']}"
    )
    assert waived["inspected_by_user_id"] == MT_RECORDER, (
        f"inspected_by_user_id is untouched, got {waived['inspected_by_user_id']}"
    )
    assert waived["waiver_justification"] == build_waiver_payload()["justification"], (
        f"the justification text is stored, got {waived['waiver_justification']}"
    )

    sealed = validate_success(_seal(api, assembly_id), expected_status=200)

    assert sealed["assembly_status"] == "SEALED", (
        f"a waived latest record lets the seal through, got {sealed['assembly_status']}"
    )
    assembly = _read_assembly(api, assembly_id)
    assert assembly["assembly_status"] == "SEALED"
    assert_wavefront_value(
        assembly["total_transmitted_wavefront_waves"],
        0.0804,
        "total_transmitted_wavefront_waves",
    )
    assert assembly["alignment_attempt_count"] == 0, (
        "the seal path recomputes nothing, got "
        f"{assembly['alignment_attempt_count']}"
    )
    stored = _read_record(api, record["id"], QM_SECOND)
    assert stored["inspection_status"] == "WAIVED"


def test_the_quality_manager_who_inspected_may_not_waive_the_same_record(api):
    """One manager records the failure and a second one has to waive it.

    The PRD states that on a waiver "The acting `X-User-ID` must differ from
    `inspected_by_user_id`, otherwise `ERR_SEGREGATION_OF_DUTIES`." and that "this is a
    comparison of operator identifiers, not of roles: a `QualityManager` who personally
    recorded an inspection cannot then waive it, even though the role is authorised for
    both operations".

    Design: Corner/rbac/the_quality_manager_who_inspected_may_not_waive_the_same_record
    """
    ctx = setup_aligned_assembly(api, component_specs=SINGLE_ELEMENT_SPECS)
    assembly_id = ctx["assembly"]["id"]
    record = _inspect(
        api,
        assembly_id,
        headers=make_quality_manager_headers(QM_PRIMARY),
        max_scratch_number=DEFAULT_SCRATCH_DIG_SCRATCH_LIMIT + 5,
        max_dig_number=3,
        particle_count_per_cm2=20,
    )
    assert record["inspected_by_user_id"] == QM_PRIMARY, (
        "the inspector is a QualityManager here, got "
        f"{record['inspected_by_user_id']}"
    )
    assert record["inspection_status"] == "FAILED"
    assert record["cleanliness_pass"] is True, (
        f"the defect is waivable in principle, got {record['cleanliness_pass']}"
    )

    self_waiver = _waive(api, record["id"], QM_PRIMARY)

    validate_error(self_waiver, ERR_SEGREGATION_OF_DUTIES)
    untouched = _read_record(api, record["id"])
    assert untouched["inspection_status"] == "FAILED", (
        f"the refused self-waiver leaves FAILED, got {untouched['inspection_status']}"
    )
    assert untouched["waived_by_user_id"] is None, (
        f"waived_by_user_id must still be null, got {untouched['waived_by_user_id']}"
    )
    assert untouched["waiver_justification"] is None

    granted = validate_success(
        _waive(api, record["id"], QM_SECOND), expected_status=200
    )

    assert granted["inspection_status"] == "WAIVED", (
        f"a second pair of eyes may grant it, got {granted['inspection_status']}"
    )
    assert granted["waived_by_user_id"] == QM_SECOND
    assert granted["waiver_justification"] == build_waiver_payload()["justification"]
    assert granted["inspected_by_user_id"] == QM_PRIMARY, (
        "the two identities stay distinguishable, got "
        f"{granted['inspected_by_user_id']}"
    )
    rows, meta = _records(api, assembly_id, params={"inspection_status": "WAIVED"})
    assert_row_ids(rows, [record["id"]], "the WAIVED filtered listing")
    assert meta["total_count"] == 1, (
        f"exactly one record stands waived, got {meta['total_count']}"
    )

    sealed = validate_success(_seal(api, assembly_id), expected_status=200)

    assert sealed["assembly_status"] == "SEALED", (
        f"the waived record clears the seal gate, got {sealed['assembly_status']}"
    )
