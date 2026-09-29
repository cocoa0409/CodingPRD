"""Authentication, the role boundary, the not-found catalogue and the conflict codes."""

from prd_bench_local_runner.testing import get_success_data

from test_helpers import (
    ALL_ZERO_UUID,
    BASE_REQUIRED_DOCUMENT_TYPES,
    ECO_CLASSIFIER,
    ECO_DECIDER,
    ERR_ASSEMBLY_COMPONENT_NOT_FOUND,
    ERR_ASSEMBLY_EMPTY,
    ERR_ASSEMBLY_NOT_FOUND,
    ERR_CHAMBER_NOT_FOUND,
    ERR_COATING_RUN_NOT_FOUND,
    ERR_COMPONENT_NOT_RELEASED,
    ERR_DESIGN_NOT_FOUND,
    ERR_DOCUMENTATION_PACKAGE_EXISTS,
    ERR_DOCUMENTATION_PACKAGE_NOT_FOUND,
    ERR_DUPLICATE_DESIGN_CODE,
    ERR_DUPLICATE_DOCUMENT_TYPE,
    ERR_DUPLICATE_LOT_CODE,
    ERR_EXPORT_CLASSIFICATION_EXISTS,
    ERR_EXPORT_CLASSIFICATION_NOT_FOUND,
    ERR_GLASS_GRADE_UNSUITABLE,
    ERR_GLASS_LOT_NOT_FOUND,
    ERR_INSPECTION_RECORD_NOT_FOUND,
    ERR_INSTRUMENT_NOT_FOUND,
    ERR_INVALID_STATE_TRANSITION,
    ERR_METROLOGY_REPORT_NOT_FOUND,
    ERR_PROCESS_RUN_NOT_FOUND,
    ERR_ROLE_NOT_PERMITTED,
    ERR_TOLERANCE_ALLOCATION_NOT_FOUND,
    ERR_UNAUTHENTICATED,
    ERR_WORK_ORDER_NOT_FOUND,
    MT_RECORDER,
    MT_SIGNER,
    QM_PRIMARY,
    QM_SECOND,
    QM_THIRD,
    assert_booked_minutes,
    assert_row_ids,
    assert_two_dp_value,
    assert_wavefront_value,
    attach_documents,
    build_assembly_component_payload,
    build_assembly_payload,
    build_block_payload,
    build_certification_payload,
    build_cement_payload,
    build_coating_chamber_payload,
    build_coating_run_payload,
    build_complete_run_payload,
    build_document_payload,
    build_documentation_package_payload,
    build_export_classification_payload,
    build_glass_lot_payload,
    build_instrument_payload,
    build_inspection_record_payload,
    build_metrology_report_payload,
    build_optical_design_payload,
    build_process_run_payload,
    build_review_payload,
    build_tolerance_allocation_payload,
    build_waiver_payload,
    build_work_order_payload,
    classify_design,
    create_assembly,
    create_certified_lot,
    create_chamber,
    create_design,
    create_glass_lot,
    create_instrument,
    create_released_design,
    error_id_of,
    make_export_compliance_officer_headers,
    make_headers_for_role,
    make_metrology_technician_headers,
    make_optics_engineer_headers,
    make_plant_admin_headers,
    make_process_technician_headers,
    make_procurement_officer_headers,
    make_quality_manager_headers,
    open_documentation_package,
    open_work_order,
    setup_aligned_assembly,
    validate_error,
    validate_paginated,
    validate_success,
)

UNDECLARED_ROLE = "ShippingClerk"


def _assert_error_envelope(response):
    """Assert an error body carries the error response_type and a message string."""
    body = response.json()
    assert body["response_type"] == "error", (
        f"a refusal must carry response_type error, got {body['response_type']}"
    )
    message = body["data"]["message"]
    assert isinstance(message, str) and message, (
        f"the error envelope must carry a human-readable message, got {message!r}"
    )


def _block(api, glass_lot_id, headers):
    """Attempt a melt-nonconformance block on one lot, raw response."""
    return api.block_glass_lot(
        glass_lot_id, build_block_payload(block_reason="AUDIT_HOLD"), headers
    )


class TestBlockRejectsWrongRoleBeforeMissingLot:
    """The role check outranks the path-existence check on the same request."""

    def test_an_engineer_blocking_an_unknown_lot_is_refused_on_the_role(self, api):
        """Priority two answers first, so the missing row is never reported.

        The PRD states that "The acting role appears in the called endpoint's
        authorised list — `ERR_ROLE_NOT_PERMITTED`, 403." is adjudicated before
        "Every id in the request path resolves, left to right — the addressed
        collection's not-found code, 404."

        Design: Difficulty/priority_pair_validation_conflict/glass_lot_block_rejects_wrong_role_before_reporting_missing_lot
        """
        lot = create_glass_lot(api, lot_code="GL-2540-1")

        refused = _block(api, ALL_ZERO_UUID, make_optics_engineer_headers())

        validate_error(refused, ERR_ROLE_NOT_PERMITTED)
        _assert_error_envelope(refused)
        assert error_id_of(refused) != ERR_GLASS_LOT_NOT_FOUND, (
            "the 403 must not be replaced by the existence check, got "
            f"{error_id_of(refused)}"
        )
        untouched = validate_success(
            api.get_glass_lot(lot["id"], make_procurement_officer_headers()),
            expected_status=200,
        )
        assert untouched["lot_status"] == "QUARANTINED", (
            f"the refused block may not move the lot, got {untouched['lot_status']}"
        )
        assert untouched["block_reason"] is None, (
            f"block_reason must stay null, got {untouched['block_reason']}"
        )

    def test_the_same_request_from_a_permitted_role_reports_the_missing_lot(self, api):
        """With the role admissible, priority three surfaces the 404.

        The PRD states that "Each collection has its own not-found code:
        `ERR_DESIGN_NOT_FOUND`, `ERR_TOLERANCE_ALLOCATION_NOT_FOUND`,
        `ERR_GLASS_LOT_NOT_FOUND`" and the block endpoint is authorised for
        `ProcurementOfficer`, `QualityManager`.

        Design: Difficulty/priority_pair_validation_conflict/glass_lot_block_rejects_wrong_role_before_reporting_missing_lot
        """
        lot = create_glass_lot(api, lot_code="GL-2540-1")

        engineer = _block(api, ALL_ZERO_UUID, make_optics_engineer_headers())
        officer = _block(api, ALL_ZERO_UUID, make_procurement_officer_headers())

        validate_error(engineer, ERR_ROLE_NOT_PERMITTED)
        validate_error(officer, ERR_GLASS_LOT_NOT_FOUND)
        _assert_error_envelope(officer)
        assert officer.status_code == 404, (
            f"the permitted role's refusal is a 404, got {officer.status_code}"
        )
        untouched = validate_success(
            api.get_glass_lot(lot["id"], make_procurement_officer_headers()),
            expected_status=200,
        )
        assert untouched["lot_status"] == "QUARANTINED"
        assert untouched["block_reason"] is None


def test_an_unknown_role_header_returns_unauthenticated_before_anything_else(api):
    """Priority one answers before existence and before body validation.

    The PRD states that "If either header is absent, or if `X-User-Role` is not one of
    the seven roles defined below, the request is rejected with `ERR_UNAUTHENTICATED`
    (HTTP 401). This check precedes every other check in the system — a malformed body
    on an unauthenticated request still yields `ERR_UNAUTHENTICATED`."

    Design: Corner/validations/an_unknown_x_user_role_header_returns_unauthenticated_before_anything_else
    """
    stranger = make_headers_for_role(UNDECLARED_ROLE, "sc-001")

    well_formed = api.create_optical_design(
        build_optical_design_payload(design_code="OD-2540-A"), stranger
    )
    broken_and_dangling = api.create_tolerance_allocation(
        ALL_ZERO_UUID, {"contributor_type": "SURFACE_IRREGULARITY"}, stranger
    )

    validate_error(well_formed, ERR_UNAUTHENTICATED)
    _assert_error_envelope(well_formed)
    validate_error(broken_and_dangling, ERR_UNAUTHENTICATED)
    _assert_error_envelope(broken_and_dangling)
    assert broken_and_dangling.status_code == 401, (
        "an unknown role on an unstored id with a short body is still a 401, got "
        f"{broken_and_dangling.status_code}"
    )
    assert error_id_of(broken_and_dangling) == ERR_UNAUTHENTICATED, (
        "neither the existence check nor the payload check may pre-empt priority one, "
        f"got {error_id_of(broken_and_dangling)}"
    )

    accepted = validate_success(
        api.create_optical_design(
            build_optical_design_payload(design_code="OD-2540-A"),
            make_optics_engineer_headers(),
        ),
        expected_status=201,
    )
    read_by_stranger = api.get_optical_design(accepted["id"], stranger)

    assert accepted["design_status"] == "DRAFT", (
        f"the same body from a declared role is admissible, got {accepted['design_status']}"
    )
    validate_error(read_by_stranger, ERR_UNAUTHENTICATED)
    assert read_by_stranger.status_code == 401, (
        f"reads are gated by priority one too, got {read_by_stranger.status_code}"
    )


def test_assembly_read_on_an_unknown_uuid_returns_assembly_not_found(api):
    """The 404 names the addressed collection, not an empty table.

    The PRD states that "Each collection has its own not-found code" and lists
    `ERR_ASSEMBLY_NOT_FOUND` among them, "each returned with HTTP 404".

    Design: Corner/entities/assembly_read_on_an_unknown_uuid_returns_assembly_not_found
    """
    design = create_design(api, design_code="OD-2540-A")
    assembly = create_assembly(api, design["id"], assembly_code="AS-2540-1")

    missing = api.get_assembly(ALL_ZERO_UUID, make_quality_manager_headers(QM_PRIMARY))
    stored = validate_success(
        api.get_assembly(assembly["id"], make_process_technician_headers()),
        expected_status=200,
    )

    validate_error(missing, ERR_ASSEMBLY_NOT_FOUND)
    _assert_error_envelope(missing)
    assert missing.status_code == 404, (
        f"an unstored uuid is a 404, got {missing.status_code}"
    )
    assert stored["id"] == assembly["id"], (
        f"the stored row still reads, got {stored['id']}"
    )
    assert stored["assembly_status"] == "KITTED", (
        f"assembly_status must be KITTED, got {stored['assembly_status']}"
    )


def test_every_path_identifier_has_its_own_not_found_code(api):
    """Fourteen single-item reads answer with fourteen distinct codes.

    The PRD states that "Each collection has its own not-found code:
    `ERR_DESIGN_NOT_FOUND`, `ERR_TOLERANCE_ALLOCATION_NOT_FOUND`,
    `ERR_GLASS_LOT_NOT_FOUND`, `ERR_WORK_ORDER_NOT_FOUND`, `ERR_INSTRUMENT_NOT_FOUND`,
    `ERR_PROCESS_RUN_NOT_FOUND`, `ERR_METROLOGY_REPORT_NOT_FOUND`,
    `ERR_CHAMBER_NOT_FOUND`, `ERR_COATING_RUN_NOT_FOUND`, `ERR_ASSEMBLY_NOT_FOUND`,
    `ERR_ASSEMBLY_COMPONENT_NOT_FOUND`, `ERR_INSPECTION_RECORD_NOT_FOUND`,
    `ERR_EXPORT_CLASSIFICATION_NOT_FOUND` and `ERR_DOCUMENTATION_PACKAGE_NOT_FOUND`,
    each returned with HTTP 404."

    Design: Corner/errors/every_path_identifier_has_its_own_not_found_code
    """
    engineer = make_optics_engineer_headers()
    technician = make_process_technician_headers()
    metrology = make_metrology_technician_headers(MT_RECORDER)
    admin = make_plant_admin_headers()

    reads = [
        (api.get_optical_design(ALL_ZERO_UUID, engineer), ERR_DESIGN_NOT_FOUND),
        (
            api.get_tolerance_allocation(ALL_ZERO_UUID, engineer),
            ERR_TOLERANCE_ALLOCATION_NOT_FOUND,
        ),
        (
            api.get_glass_lot(ALL_ZERO_UUID, make_procurement_officer_headers()),
            ERR_GLASS_LOT_NOT_FOUND,
        ),
        (api.get_work_order(ALL_ZERO_UUID, technician), ERR_WORK_ORDER_NOT_FOUND),
        (
            api.get_metrology_instrument(ALL_ZERO_UUID, admin),
            ERR_INSTRUMENT_NOT_FOUND,
        ),
        (api.get_process_run(ALL_ZERO_UUID, technician), ERR_PROCESS_RUN_NOT_FOUND),
        (
            api.get_metrology_report(ALL_ZERO_UUID, metrology),
            ERR_METROLOGY_REPORT_NOT_FOUND,
        ),
        (api.get_coating_chamber(ALL_ZERO_UUID, admin), ERR_CHAMBER_NOT_FOUND),
        (api.get_coating_run(ALL_ZERO_UUID, technician), ERR_COATING_RUN_NOT_FOUND),
        (api.get_assembly(ALL_ZERO_UUID, technician), ERR_ASSEMBLY_NOT_FOUND),
        (
            api.get_assembly_component(ALL_ZERO_UUID, technician),
            ERR_ASSEMBLY_COMPONENT_NOT_FOUND,
        ),
        (
            api.get_inspection_record(ALL_ZERO_UUID, metrology),
            ERR_INSPECTION_RECORD_NOT_FOUND,
        ),
        (
            api.get_export_classification(
                ALL_ZERO_UUID, make_export_compliance_officer_headers(ECO_CLASSIFIER)
            ),
            ERR_EXPORT_CLASSIFICATION_NOT_FOUND,
        ),
        (
            api.get_documentation_package(
                ALL_ZERO_UUID, make_quality_manager_headers(QM_PRIMARY)
            ),
            ERR_DOCUMENTATION_PACKAGE_NOT_FOUND,
        ),
    ]

    for response, expected_error_id in reads:
        validate_error(response, expected_error_id)
        _assert_error_envelope(response)
        assert response.status_code == 404, (
            f"{expected_error_id} is a 404, got {response.status_code}"
        )
    observed = [error_id_of(response) for response, _ in reads]
    assert len(observed) == 14, f"fourteen collections were read, got {len(observed)}"
    assert len(set(observed)) == 14, (
        f"the fourteen not-found codes must be pairwise distinct, got {observed}"
    )


def test_every_body_foreign_key_is_resolved_and_reports_its_own_not_found_code(api):
    """Each broken body reference names exactly the collection it addressed.

    The PRD states that "The same catalogue governs foreign keys carried in a request
    **body**." and that "Body foreign keys are validated **in the order the fields are
    listed for that endpoint in §4**, and the first unresolvable reference determines
    the response."

    Design: Corner/errors/every_body_foreign_key_is_resolved_and_reports_its_own_not_found_code
    """
    design = create_released_design(api, design_code="OD-2540-A")
    lot = create_certified_lot(api, lot_code="GL-2540-1")
    instrument = create_instrument(api, instrument_code="IF-2540-1")
    chamber = create_chamber(api, chamber_code="CH-2540-1")
    work_order = open_work_order(
        api, design["id"], lot["id"], lot["version"], wo_code="WO-2540-1"
    )
    assembly = create_assembly(api, design["id"], assembly_code="AS-2540-1")
    technician = make_process_technician_headers()
    metrology = make_metrology_technician_headers(MT_RECORDER)

    refusals = [
        (
            api.create_process_run(
                build_process_run_payload(ALL_ZERO_UUID, instrument["id"]), technician
            ),
            ERR_WORK_ORDER_NOT_FOUND,
        ),
        (
            api.create_process_run(
                build_process_run_payload(work_order["id"], ALL_ZERO_UUID), technician
            ),
            ERR_INSTRUMENT_NOT_FOUND,
        ),
        (
            api.create_metrology_report(
                build_metrology_report_payload(ALL_ZERO_UUID), metrology
            ),
            ERR_PROCESS_RUN_NOT_FOUND,
        ),
        (
            api.create_coating_run(
                build_coating_run_payload(ALL_ZERO_UUID, chamber["id"]), technician
            ),
            ERR_WORK_ORDER_NOT_FOUND,
        ),
        (
            api.create_coating_run(
                build_coating_run_payload(work_order["id"], ALL_ZERO_UUID), technician
            ),
            ERR_CHAMBER_NOT_FOUND,
        ),
        (
            api.create_assembly(
                build_assembly_payload(ALL_ZERO_UUID, assembly_code="AS-2540-9"),
                technician,
            ),
            ERR_DESIGN_NOT_FOUND,
        ),
        (
            api.create_assembly_component(
                build_assembly_component_payload(
                    ALL_ZERO_UUID, work_order["id"], assembly["version"]
                ),
                technician,
            ),
            ERR_ASSEMBLY_NOT_FOUND,
        ),
        (
            api.create_assembly_component(
                build_assembly_component_payload(
                    assembly["id"], ALL_ZERO_UUID, assembly["version"]
                ),
                technician,
            ),
            ERR_WORK_ORDER_NOT_FOUND,
        ),
        (
            api.create_inspection_record(
                build_inspection_record_payload(ALL_ZERO_UUID), metrology
            ),
            ERR_ASSEMBLY_NOT_FOUND,
        ),
        (
            api.create_export_classification(
                build_export_classification_payload(ALL_ZERO_UUID),
                make_export_compliance_officer_headers(ECO_CLASSIFIER),
            ),
            ERR_DESIGN_NOT_FOUND,
        ),
        (
            api.create_documentation_package(
                build_documentation_package_payload(ALL_ZERO_UUID),
                make_quality_manager_headers(QM_PRIMARY),
            ),
            ERR_ASSEMBLY_NOT_FOUND,
        ),
    ]

    for response, expected_error_id in refusals:
        validate_error(response, expected_error_id)
        assert response.status_code == 404, (
            f"{expected_error_id} is a 404, got {response.status_code}"
        )

    rows, meta = validate_paginated(api.list_process_runs(technician))
    assert rows == [], f"no refused create may have persisted a run, got {rows}"
    assert meta["total_count"] == 0, (
        f"total_count must be 0, got {meta['total_count']}"
    )
    station = validate_success(
        api.get_metrology_instrument(instrument["id"], make_plant_admin_headers()),
        expected_status=200,
    )
    assert_booked_minutes(station, 0)
    after = validate_success(
        api.get_assembly(assembly["id"], technician), expected_status=200
    )
    assert after["version"] == assembly["version"], (
        "a refused kitting may not bump the assembly version, got "
        f"{after['version']} after {assembly['version']}"
    )


def test_each_uniqueness_rule_has_its_own_conflict_code(api):
    """Five uniqueness scopes answer with five different 409 codes.

    The PRD states that "Uniqueness: at most one non-denied export classification per
    design; at most one documentation package per assembly; globally unique
    `design_code` and `lot_code`; a slot index unique among an assembly's active
    components; a document type attached at most once per package —
    `ERR_EXPORT_CLASSIFICATION_EXISTS`, `ERR_DOCUMENTATION_PACKAGE_EXISTS`,
    `ERR_DUPLICATE_DESIGN_CODE`, `ERR_DUPLICATE_LOT_CODE`,
    `ERR_SLOT_ALREADY_OCCUPIED` or `ERR_DUPLICATE_DOCUMENT_TYPE`, 409."

    Design: Corner/errors/each_uniqueness_rule_has_its_own_conflict_code
    """
    design = create_released_design(api, design_code="OD-2540-A")
    lot = create_certified_lot(api, lot_code="GL-2540-1")
    assembly = create_assembly(api, design["id"], assembly_code="AS-2540-1")
    package = open_documentation_package(api, assembly["id"], QM_PRIMARY)
    attach_documents(api, package["id"], ["CERTIFICATE_OF_CONFORMANCE"], QM_PRIMARY)
    classification = classify_design(api, design["id"], destination_country="DE")
    assert classification["classification_status"] == "LICENSE_REQUIRED", (
        "the governing classification requires a licence, got "
        f"{classification['classification_status']}"
    )

    duplicate_design = api.create_optical_design(
        build_optical_design_payload(design_code="OD-2540-A"),
        make_optics_engineer_headers(),
    )
    fresh_design = api.create_optical_design(
        build_optical_design_payload(design_code="OD-2540-Z"),
        make_optics_engineer_headers(),
    )
    duplicate_lot = api.create_glass_lot(
        build_glass_lot_payload(lot_code="GL-2540-1"),
        make_procurement_officer_headers(),
    )
    fresh_lot = api.create_glass_lot(
        build_glass_lot_payload(lot_code="GL-2540-Z"),
        make_procurement_officer_headers(),
    )
    second_classification = api.create_export_classification(
        build_export_classification_payload(design["id"], destination_country="FR"),
        make_export_compliance_officer_headers(ECO_CLASSIFIER),
    )
    second_package = api.create_documentation_package(
        build_documentation_package_payload(assembly["id"]),
        make_quality_manager_headers(QM_PRIMARY),
    )
    duplicate_document = api.attach_document(
        package["id"],
        build_document_payload("CERTIFICATE_OF_CONFORMANCE", document_reference="COC-2540-2"),
        make_quality_manager_headers(QM_PRIMARY),
    )
    second_document = get_success_data(
        api.attach_document(
            package["id"],
            build_document_payload("MELT_CERTIFICATE"),
            make_quality_manager_headers(QM_PRIMARY),
        )
    )

    validate_error(duplicate_design, ERR_DUPLICATE_DESIGN_CODE)
    other_design = validate_success(fresh_design, expected_status=201)
    validate_error(duplicate_lot, ERR_DUPLICATE_LOT_CODE)
    other_lot = validate_success(fresh_lot, expected_status=201)
    validate_error(second_classification, ERR_EXPORT_CLASSIFICATION_EXISTS)
    validate_error(second_package, ERR_DOCUMENTATION_PACKAGE_EXISTS)
    validate_error(duplicate_document, ERR_DUPLICATE_DOCUMENT_TYPE)
    assert other_design["design_code"] == "OD-2540-Z", (
        f"only the code collided, got {other_design['design_code']}"
    )
    assert other_lot["lot_code"] == "GL-2540-Z"
    assert list(second_document["present_document_types"]) == [
        "CERTIFICATE_OF_CONFORMANCE",
        "MELT_CERTIFICATE",
    ], (
        "the refused duplicate left no second entry, got "
        f"{second_document['present_document_types']}"
    )

    designs, design_meta = validate_paginated(
        api.list_optical_designs(make_optics_engineer_headers())
    )
    packages, package_meta = validate_paginated(
        api.list_assembly_documentation_packages(
            assembly["id"], make_quality_manager_headers(QM_PRIMARY)
        )
    )
    assert_row_ids(
        designs, [design["id"], other_design["id"]], "the design listing"
    )
    assert design_meta["total_count"] == 2, (
        f"total_count must be 2, got {design_meta['total_count']}"
    )
    assert_row_ids(packages, [package["id"]], "the assembly's package listing")
    assert package_meta["total_count"] == 1, (
        f"the assembly still owns exactly one package, got {package_meta['total_count']}"
    )
    assert lot["lot_code"] == "GL-2540-1"


def test_thin_blanks_empty_assemblies_and_unreleased_elements_have_their_own_codes(api):
    """Three unrelated 409s, each cleared once its single cause is removed.

    The PRD states that "the lot's `blank_center_thickness_um` must be greater than or
    equal to the design's `min_center_thickness_um`, because a blank thinner than the
    finished part's minimum leaves nothing to remove. Any of those three failures
    reports `ERR_GLASS_GRADE_UNSUITABLE`." and that structural completeness requires
    "the assembly has at least one active component before cementing, aligning or
    releasing".

    Design: Corner/errors/thin_blanks_empty_assemblies_and_unreleased_elements_each_have_their_own_code
    """
    design = create_released_design(api, design_code="OD-2540-A")
    thin = create_certified_lot(
        api, lot_code="GL-2540-THIN", blank_center_thickness_um=5000.0
    )
    suitable = create_certified_lot(
        api, lot_code="GL-2540-OK", blank_center_thickness_um=6200.0
    )
    assembly = create_assembly(api, design["id"], assembly_code="AS-2540-1")
    technician = make_process_technician_headers()
    assert thin["effective_index_homogeneity_grade"] == "H3", (
        "the thin lot's grades themselves suit the design, got "
        f"{thin['effective_index_homogeneity_grade']}"
    )
    assert thin["effective_striae_grade"] == "B"

    on_thin_glass = api.create_work_order(
        build_work_order_payload(
            design["id"], thin["id"], thin["version"], wo_code="WO-2540-THIN"
        ),
        technician,
    )
    on_empty_assembly = api.cement_assembly(
        assembly["id"], build_cement_payload(), technician
    )

    validate_error(on_thin_glass, ERR_GLASS_GRADE_UNSUITABLE)
    validate_error(on_empty_assembly, ERR_ASSEMBLY_EMPTY)
    still_kitted = validate_success(
        api.get_assembly(assembly["id"], technician), expected_status=200
    )
    assert still_kitted["assembly_status"] == "KITTED", (
        f"the refused cement leaves KITTED, got {still_kitted['assembly_status']}"
    )

    accepted_order = validate_success(
        api.create_work_order(
            build_work_order_payload(
                design["id"],
                suitable["id"],
                suitable["version"],
                wo_code="WO-2540-OK",
            ),
            technician,
        ),
        expected_status=201,
    )
    unreleased_element = api.create_assembly_component(
        build_assembly_component_payload(
            assembly["id"], accepted_order["id"], assembly["version"]
        ),
        technician,
    )

    assert accepted_order["process_status"] == "BLANKS_RESERVED", (
        "only the blank thickness had blocked the first order, got "
        f"{accepted_order['process_status']}"
    )
    validate_error(unreleased_element, ERR_COMPONENT_NOT_RELEASED)
    components, component_meta = validate_paginated(
        api.list_assembly_components(assembly["id"], technician)
    )
    assert components == [], (
        f"the refused kitting persisted no component, got {components}"
    )
    assert component_meta["total_count"] == 0
    unchanged = validate_success(
        api.get_assembly(assembly["id"], technician), expected_status=200
    )
    assert unchanged["version"] == assembly["version"], (
        f"the assembly version must be unchanged, got {unchanged['version']}"
    )
    thin_after = validate_success(
        api.get_glass_lot(thin["id"], make_procurement_officer_headers()),
        expected_status=200,
    )
    assert thin_after["reserved_blank_count"] == 0, (
        f"the refused order reserved nothing, got {thin_after['reserved_blank_count']}"
    )
    assert thin_after["available_blank_count"] == 20, (
        f"available_blank_count must still be 20, got {thin_after['available_blank_count']}"
    )


def test_every_write_endpoint_called_by_a_wrong_role_returns_forbidden(api):
    """Twelve writes issued by outsiders are all refused, and nothing moves.

    The PRD states that "The acting role appears in the called endpoint's authorised
    list — `ERR_ROLE_NOT_PERMITTED`, 403." and that check precedes "Every id in the
    request path resolves, left to right".

    Design: Corner/rbac/every_write_endpoint_called_by_a_wrong_role_returns_forbidden
    """
    design = create_released_design(api, design_code="OD-2540-A")
    lot = create_certified_lot(api, lot_code="GL-2540-1")
    technician = make_process_technician_headers()
    manager = make_quality_manager_headers(QM_PRIMARY)
    metrology = make_metrology_technician_headers(MT_RECORDER)

    refusals = [
        api.create_optical_design(
            build_optical_design_payload(design_code="OD-2540-X"), technician
        ),
        api.run_tolerance_analysis(design["id"], manager),
        api.create_glass_lot(build_glass_lot_payload(lot_code="GL-2540-X"), technician),
        api.certify_glass_lot(
            lot["id"],
            build_certification_payload(certificate_reference="CERT-2540-X"),
            metrology,
        ),
        api.create_work_order(
            build_work_order_payload(
                design["id"], lot["id"], lot["version"], wo_code="WO-2540-X"
            ),
            make_optics_engineer_headers(),
        ),
        api.create_metrology_instrument(
            build_instrument_payload(instrument_code="IF-2540-X"), technician
        ),
        api.create_coating_chamber(
            build_coating_chamber_payload(chamber_code="CH-2540-X"), manager
        ),
        api.set_clock("2026-08-05T00:00:00Z", manager),
        api.create_export_classification(
            build_export_classification_payload(design["id"]), manager
        ),
        api.sign_metrology_report(ALL_ZERO_UUID, technician),
        api.waive_inspection_record(ALL_ZERO_UUID, build_waiver_payload(), metrology),
        api.release_assembly(ALL_ZERO_UUID, technician),
    ]

    assert len(refusals) == 12, f"twelve role boundaries were probed, got {len(refusals)}"
    for response in refusals:
        validate_error(response, ERR_ROLE_NOT_PERMITTED)
        _assert_error_envelope(response)
        assert response.status_code == 403, (
            f"every wrong-role write is a 403, got {response.status_code}"
        )
    for response in refusals[-3:]:
        assert response.status_code != 404, (
            "the role check runs before the existence check on the all-zeros uuid, got "
            f"{response.status_code}"
        )

    designs, design_meta = validate_paginated(
        api.list_optical_designs(make_optics_engineer_headers())
    )
    lots, lot_meta = validate_paginated(
        api.list_glass_lots(make_procurement_officer_headers())
    )
    instruments, instrument_meta = validate_paginated(
        api.list_metrology_instruments(make_plant_admin_headers())
    )
    assert_row_ids(designs, [design["id"]], "the design listing")
    assert design_meta["total_count"] == 1, (
        f"no refused create may have persisted a design, got {design_meta['total_count']}"
    )
    assert_row_ids(lots, [lot["id"]], "the lot listing")
    assert lot_meta["total_count"] == 1
    assert instruments == [], f"no instrument may exist, got {instruments}"
    assert instrument_meta["total_count"] == 0
    after_design = validate_success(
        api.get_optical_design(design["id"], make_optics_engineer_headers()),
        expected_status=200,
    )
    assert after_design["design_status"] == "RELEASED", (
        f"the refused analysis may not move the design, got {after_design['design_status']}"
    )
    assert after_design["version"] == design["version"], (
        f"the design version must be unchanged, got {after_design['version']}"
    )
    after_lot = validate_success(
        api.get_glass_lot(lot["id"], make_procurement_officer_headers()),
        expected_status=200,
    )
    assert after_lot["certificate_reference"] == "CERT-2540-1", (
        "the refused certification changed nothing, got "
        f"{after_lot['certificate_reference']}"
    )


def test_each_of_the_seven_roles_performs_its_own_exclusive_operations_end_to_end(api):
    """One optic reaches the customer with every call made by its owning role.

    The PRD states that "Identity in this system is deliberately not resource
    ownership." and that final release is permitted only where "The acting role appears
    in the called endpoint's authorised list".

    Design: Corner/rbac/each_of_the_seven_roles_performs_its_own_exclusive_operations_end_to_end
    """
    ctx = setup_aligned_assembly(api)
    assembly_id = ctx["assembly"]["id"]

    inspection = validate_success(
        api.create_inspection_record(
            build_inspection_record_payload(assembly_id),
            make_metrology_technician_headers(MT_RECORDER),
        ),
        expected_status=201,
    )
    sealed = validate_success(
        api.seal_assembly(assembly_id, make_process_technician_headers()),
        expected_status=200,
    )
    package = validate_success(
        api.create_documentation_package(
            build_documentation_package_payload(assembly_id),
            make_quality_manager_headers(QM_PRIMARY),
        ),
        expected_status=201,
    )
    attach_documents(
        api, package["id"], list(package["required_document_types"]), QM_PRIMARY
    )
    submitted = validate_success(
        api.submit_documentation_package(
            package["id"], make_quality_manager_headers(QM_PRIMARY)
        ),
        expected_status=200,
    )
    reviewed = validate_success(
        api.review_documentation_package(
            package["id"],
            build_review_payload("APPROVED"),
            make_quality_manager_headers(QM_SECOND),
        ),
        expected_status=200,
    )
    released = validate_success(
        api.release_assembly(assembly_id, make_quality_manager_headers(QM_THIRD)),
        expected_status=200,
    )
    readiness = validate_success(
        api.get_release_readiness(assembly_id, make_quality_manager_headers(QM_THIRD)),
        expected_status=200,
    )

    assert ctx["design"]["design_status"] == "RELEASED", (
        f"the engineer released the design, got {ctx['design']['design_status']}"
    )
    assert ctx["design"]["tolerance_verdict"] == "PASS"
    assert_wavefront_value(
        ctx["design"]["governing_stack_waves"], 0.0375, "governing_stack_waves"
    )
    assert ctx["lot"]["lot_status"] == "RELEASED", (
        f"procurement certified the melt, got {ctx['lot']['lot_status']}"
    )
    assert ctx["lot"]["measured_index_homogeneity_grade"] == "H3"
    assert ctx["lot"]["measured_striae_grade"] == "B"
    assert ctx["lot"]["certificate_reference"] == "CERT-2540-1"
    signed_report = ctx["passes"]["polishing"]["signed"]
    assert signed_report["recorded_by_user_id"] == MT_RECORDER, (
        f"the recorder is {MT_RECORDER}, got {signed_report['recorded_by_user_id']}"
    )
    assert signed_report["signed_by_user_id"] == MT_SIGNER, (
        f"the signer is {MT_SIGNER}, got {signed_report['signed_by_user_id']}"
    )
    assert ctx["coating"]["verified"]["coating_status"] == "VERIFIED_PASS", (
        f"the technician verified the spectrum, got "
        f"{ctx['coating']['verified']['coating_status']}"
    )
    assert ctx["compliance"]["decided"]["classification_status"] == "LICENSE_APPROVED", (
        "the compliance officer licensed the design, got "
        f"{ctx['compliance']['decided']['classification_status']}"
    )
    assert ctx["compliance"]["decided"]["decided_by_user_id"] == ECO_DECIDER, (
        f"decided_by_user_id must be {ECO_DECIDER}, got "
        f"{ctx['compliance']['decided']['decided_by_user_id']}"
    )
    assert ctx["released"]["process_status"] == "RELEASED_TO_ASSEMBLY"
    assert ctx["released"]["compliance_status"] == "CLEARED"
    assert inspection["inspection_status"] == "PASSED", (
        f"inspection_status must be PASSED, got {inspection['inspection_status']}"
    )
    assert inspection["inspected_by_user_id"] == MT_RECORDER
    assert sealed["assembly_status"] == "SEALED", (
        f"the technician sealed the barrel, got {sealed['assembly_status']}"
    )
    assert submitted["submitted_by_user_id"] == QM_PRIMARY
    assert reviewed["package_status"] == "APPROVED", (
        f"package_status must be APPROVED, got {reviewed['package_status']}"
    )
    assert reviewed["reviewed_by_user_id"] == QM_SECOND
    assert released["assembly_status"] == "RELEASED", (
        f"assembly_status must be RELEASED, got {released['assembly_status']}"
    )
    assert readiness["assembly_status"] == "RELEASED", (
        f"the readiness projection reports the current status, got "
        f"{readiness['assembly_status']}"
    )
    assert readiness["blocking_error_id"] == ERR_INVALID_STATE_TRANSITION, (
        "release is permitted 'only from `SEALED`; from any other state, "
        "`ERR_INVALID_STATE_TRANSITION`', so the projection names that error for an "
        f"already-released assembly, got {readiness['blocking_error_id']}"
    )


def test_every_entity_is_born_in_its_declared_initial_state(api):
    """Eight creates in one database each land on their declared birth state.

    The PRD states that a design "is created in `DRAFT` with `tolerance_verdict` set to
    `PENDING`, `design_revision` set to 1", that an assembly "is created in `KITTED`
    with `alignment_attempt_count` at zero", that a package "is created in `ASSEMBLING`
    with `rejection_count` at zero, `attached_documents` an empty array", and that a
    classification "row is created in `LICENSE_REQUIRED` when a licence is required and
    in `EXEMPT_CLEARED` when it is not".

    Design: Corner/state_machines/every_entity_is_born_in_its_declared_initial_state
    """
    design = create_released_design(api, design_code="OD-2540-A")
    lot = create_certified_lot(api, lot_code="GL-2540-1")
    work_order = open_work_order(
        api, design["id"], lot["id"], lot["version"], wo_code="WO-2540-1"
    )
    instrument = create_instrument(api, instrument_code="IF-2540-1")
    technician = make_process_technician_headers()
    run = validate_success(
        api.create_process_run(
            build_process_run_payload(work_order["id"], instrument["id"]), technician
        ),
        expected_status=201,
    )
    assert run["run_status"] == "SCHEDULED", (
        f"a process run is born SCHEDULED, got {run['run_status']}"
    )
    validate_success(api.start_process_run(run["id"], technician), expected_status=200)
    completed = validate_success(
        api.complete_process_run(
            run["id"], build_complete_run_payload(), technician
        ),
        expected_status=200,
    )
    assert completed["run_status"] == "AWAITING_METROLOGY", (
        f"the completed run awaits metrology, got {completed['run_status']}"
    )
    fresh_lot = validate_success(
        api.get_glass_lot(lot["id"], make_procurement_officer_headers()),
        expected_status=200,
    )

    report = validate_success(
        api.create_metrology_report(
            build_metrology_report_payload(
                run["id"], surface_roughness_nm_rms=0.8000
            ),
            make_metrology_technician_headers(MT_RECORDER),
        ),
        expected_status=201,
    )
    second_order = validate_success(
        api.create_work_order(
            build_work_order_payload(
                design["id"], lot["id"], fresh_lot["version"], wo_code="WO-2540-2"
            ),
            technician,
        ),
        expected_status=201,
    )
    second_lot = validate_success(
        api.create_glass_lot(
            build_glass_lot_payload(lot_code="GL-2540-2", total_blank_count=8),
            make_procurement_officer_headers(),
        ),
        expected_status=201,
    )
    second_design = validate_success(
        api.create_optical_design(
            build_optical_design_payload(design_code="OD-2540-B"),
            make_optics_engineer_headers(),
        ),
        expected_status=201,
    )
    allocation = validate_success(
        api.create_tolerance_allocation(
            second_design["id"],
            build_tolerance_allocation_payload(),
            make_optics_engineer_headers(),
        ),
        expected_status=201,
    )
    assembly = validate_success(
        api.create_assembly(
            build_assembly_payload(design["id"], assembly_code="AS-2540-1"), technician
        ),
        expected_status=201,
    )
    package = validate_success(
        api.create_documentation_package(
            build_documentation_package_payload(assembly["id"]),
            make_quality_manager_headers(QM_PRIMARY),
        ),
        expected_status=201,
    )
    classification = validate_success(
        api.create_export_classification(
            build_export_classification_payload(
                design["id"], destination_country="DE"
            ),
            make_export_compliance_officer_headers(ECO_CLASSIFIER),
        ),
        expected_status=201,
    )

    assert report["report_status"] == "DRAFT", (
        f"a metrology report is born DRAFT, got {report['report_status']}"
    )
    assert report["verdict"] == "PENDING", (
        f"its verdict is PENDING until it is signed, got {report['verdict']}"
    )
    assert second_order["process_status"] == "BLANKS_RESERVED", (
        f"process_status must be BLANKS_RESERVED, got {second_order['process_status']}"
    )
    assert second_order["compliance_status"] == "UNCLASSIFIED", (
        "the compliance dimension starts UNCLASSIFIED, got "
        f"{second_order['compliance_status']}"
    )
    assert second_lot["lot_status"] == "QUARANTINED", (
        f"a received lot is QUARANTINED, got {second_lot['lot_status']}"
    )
    assert second_design["design_status"] == "DRAFT", (
        f"design_status must be DRAFT, got {second_design['design_status']}"
    )
    assert second_design["tolerance_verdict"] == "PENDING"
    assert second_design["design_revision"] == 1
    assert allocation["allocation_status"] == "ACTIVE", (
        f"an allocation is born ACTIVE, got {allocation['allocation_status']}"
    )
    assert_wavefront_value(allocation["contribution_waves"], 0.0375, "contribution_waves")
    assert assembly["assembly_status"] == "KITTED", (
        f"assembly_status must be KITTED, got {assembly['assembly_status']}"
    )
    assert assembly["alignment_attempt_count"] == 0, (
        f"alignment_attempt_count must be 0, got {assembly['alignment_attempt_count']}"
    )
    assert assembly["total_transmitted_wavefront_waves"] is None, (
        "the roll-up is null until the first alignment pass, got "
        f"{assembly['total_transmitted_wavefront_waves']}"
    )
    assert package["package_status"] == "ASSEMBLING", (
        f"package_status must be ASSEMBLING, got {package['package_status']}"
    )
    assert package["rejection_count"] == 0
    assert_two_dp_value(package["completeness_pct"], 0.00, "completeness_pct")
    assert list(package["missing_document_types"]) == list(
        BASE_REQUIRED_DOCUMENT_TYPES
    ), (
        "with no coating fact, no waiver and no classification yet, the three base "
        f"types are missing, got {package['missing_document_types']}"
    )
    assert classification["classification_status"] == "LICENSE_REQUIRED", (
        "a controlled optic bound for Germany needs a licence, got "
        f"{classification['classification_status']}"
    )
    assert_two_dp_value(classification["figure_of_merit"], 3000.00, "figure_of_merit")
    assert classification["eccn"] == "6A004.A.1", (
        f"eccn must be 6A004.A.1, got {classification['eccn']}"
    )
    assert classification["license_required"] is True
