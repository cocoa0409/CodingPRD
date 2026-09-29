"""The derived document set, the review loop and the four-gate final release."""

from prd_bench_local_runner.testing import get_success_data

from test_helpers import (
    BASE_REQUIRED_DOCUMENT_TYPES,
    CANONICAL_TWO_ELEMENT_SPECS,
    CLOCK_EPOCH_UTC,
    ERR_DOCUMENTATION_INCOMPLETE,
    ERR_DOCUMENTATION_NOT_APPROVED,
    ERR_DOCUMENTATION_PACKAGE_NOT_FOUND,
    ERR_INVALID_STATE_TRANSITION,
    ERR_SEGREGATION_OF_DUTIES,
    MT_RECORDER,
    PROCESS_TECHNICIAN_ID,
    QM_PRIMARY,
    QM_SECOND,
    QM_THIRD,
    assert_package_documents,
    assert_readiness_gates,
    assert_two_dp_value,
    assert_wavefront_value,
    attach_documents,
    build_document_payload,
    build_documentation_package_payload,
    build_inspection_record_payload,
    build_review_payload,
    create_assembly,
    create_design,
    kit_components,
    make_metrology_technician_headers,
    make_process_technician_headers,
    make_quality_manager_headers,
    open_documentation_package,
    setup_aligned_assembly,
    setup_released_to_assembly_work_order,
    setup_sealed_assembly,
    validate_error,
    validate_success,
)

FULL_REQUIRED_SET = (
    "CERTIFICATE_OF_CONFORMANCE",
    "COATING_SPECTRAL_DATA",
    "EXPORT_LICENSE",
    "INTERFEROGRAM_REPORT",
    "MELT_CERTIFICATE",
)
UNCONTROLLED_REQUIRED_SET = (
    "CERTIFICATE_OF_CONFORMANCE",
    "COATING_SPECTRAL_DATA",
    "INTERFEROGRAM_REPORT",
    "MELT_CERTIFICATE",
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


def _read_package(api, package_id, reader_id=QM_THIRD):
    """Read one documentation package with its completeness roll-up."""
    return validate_success(
        api.get_documentation_package(
            package_id, make_quality_manager_headers(reader_id)
        ),
        expected_status=200,
    )


def _readiness(api, assembly_id, reader_id=QM_THIRD):
    """Read the computed release-readiness projection of an assembly."""
    return validate_success(
        api.get_release_readiness(
            assembly_id, make_quality_manager_headers(reader_id)
        ),
        expected_status=200,
    )


def _attach(api, package_id, document_type, actor_id=QM_PRIMARY):
    """Attach one document type and return the re-derived package."""
    return get_success_data(
        api.attach_document(
            package_id,
            build_document_payload(document_type),
            make_quality_manager_headers(actor_id),
        )
    )


def _submit(api, package_id, actor_id=QM_PRIMARY):
    """Submit a package for review as a QualityManager, raw response."""
    return api.submit_documentation_package(
        package_id, make_quality_manager_headers(actor_id)
    )


def _review(api, package_id, decision, actor_id=QM_SECOND, **overrides):
    """Record a review decision on a package, raw response."""
    return api.review_documentation_package(
        package_id,
        build_review_payload(decision, **overrides),
        make_quality_manager_headers(actor_id),
    )


def _release(api, assembly_id, actor_id=QM_THIRD):
    """Attempt the final customer release of an assembly, raw response."""
    return api.release_assembly(assembly_id, make_quality_manager_headers(actor_id))


def _uncontrolled_submitted_package(api):
    """An EAR99 build whose four-document package stands SUBMITTED by qm-001."""
    ctx = setup_released_to_assembly_work_order(
        api,
        design_overrides={
            "aperture_mm": 60.0,
            "required_rms_wavefront_waves": 0.1000,
        },
        element_count=1,
    )
    ctx["assembly"] = create_assembly(
        api, ctx["design"]["id"], assembly_code="AS-2540-1"
    )
    ctx["components"] = kit_components(
        api,
        ctx["assembly"]["id"],
        ctx["work_order"]["id"],
        SINGLE_ELEMENT_SPECS,
        start_version=ctx["assembly"]["version"],
    )
    package = open_documentation_package(api, ctx["assembly"]["id"], QM_PRIMARY)
    attach_documents(
        api, package["id"], list(package["required_document_types"]), QM_PRIMARY
    )
    ctx["package"] = package
    ctx["submitted"] = validate_success(
        _submit(api, package["id"], QM_PRIMARY), expected_status=200
    )
    return ctx


class TestDocumentationRejectLoop:
    """A rejection walks the package backwards and re-opens attachment."""

    def test_a_rejected_review_returns_the_package_to_assembling(self, api):
        """The reject decision counts itself and records the reviewer.

        The PRD states that "A rejection moves the package `SUBMITTED → ASSEMBLING`,
        increments `rejection_count` by one, and records the same two fields; further
        documents may then be attached and the package resubmitted, which is the
        revision loop `ASSEMBLING → SUBMITTED → ASSEMBLING`."

        Design: Difficulty/non_linear_state_machine/documentation_package_reject_loop_returns_to_assembling
        """
        ctx = _uncontrolled_submitted_package(api)
        classification = ctx["compliance"]["classification"]
        assert_two_dp_value(classification["figure_of_merit"], 600.00, "figure_of_merit")
        assert classification["eccn"] == "EAR99", (
            f"a 60 mm optic at 0.1000 waves is uncontrolled, got {classification['eccn']}"
        )
        assert classification["license_required"] is False
        assert classification["classification_status"] == "EXEMPT_CLEARED", (
            f"classification_status must be EXEMPT_CLEARED, got "
            f"{classification['classification_status']}"
        )
        assert ctx["submitted"]["package_status"] == "SUBMITTED"
        assert ctx["submitted"]["submitted_by_user_id"] == QM_PRIMARY

        rejected = validate_success(
            _review(
                api,
                ctx["package"]["id"],
                "REJECTED",
                actor_id=QM_SECOND,
                review_note="Interferogram report is illegible",
            ),
            expected_status=200,
        )

        assert rejected["package_status"] == "ASSEMBLING", (
            f"a rejection reopens the package, got {rejected['package_status']}"
        )
        assert rejected["rejection_count"] == 1, (
            f"rejection_count must be 1, got {rejected['rejection_count']}"
        )
        assert rejected["last_review_note"] == "Interferogram report is illegible", (
            f"last_review_note must be recorded, got {rejected['last_review_note']}"
        )
        assert rejected["reviewed_by_user_id"] == QM_SECOND, (
            f"reviewed_by_user_id must be the reviewer, got {rejected['reviewed_by_user_id']}"
        )
        assert list(rejected["required_document_types"]) == list(
            UNCONTROLLED_REQUIRED_SET
        ), (
            "an uncontrolled design requires no export licence, got "
            f"{rejected['required_document_types']}"
        )

    def test_an_unrequired_document_type_never_raises_completeness(self, api):
        """The fifth document is stored faithfully and changes no percentage.

        The PRD states that "Documents attached that are not in the required set are
        stored faithfully but never raise `completeness_pct` — a package with all three
        base documents plus an unrequired `EXPORT_LICENSE` still reads 100.00, and a
        package with two of three base documents plus that extra reads 66.67."

        Design: Difficulty/non_linear_state_machine/documentation_package_reject_loop_returns_to_assembling
        """
        ctx = _uncontrolled_submitted_package(api)
        validate_success(
            _review(api, ctx["package"]["id"], "REJECTED", actor_id=QM_SECOND),
            expected_status=200,
        )

        extended = _attach(api, ctx["package"]["id"], "EXPORT_LICENSE", QM_PRIMARY)

        assert_two_dp_value(extended["completeness_pct"], 100.00, "completeness_pct")
        assert list(extended["missing_document_types"]) == [], (
            f"nothing required is missing, got {extended['missing_document_types']}"
        )
        assert len(extended["present_document_types"]) == 5, (
            "the unrequired type is present all the same, got "
            f"{extended['present_document_types']}"
        )
        assert list(extended["required_document_types"]) == list(
            UNCONTROLLED_REQUIRED_SET
        ), (
            "the required set is still four types, got "
            f"{extended['required_document_types']}"
        )
        assert len(extended["attached_documents"]) == 5, (
            f"attached_documents must hold five entries, got {extended['attached_documents']}"
        )

    def test_the_second_round_reaches_approved_with_the_rejection_still_counted(
        self, api
    ):
        """One rejection stays on the record after the package is approved.

        The PRD states that an approval "on success moves the package
        `SUBMITTED → APPROVED`, a terminal state, recording `reviewed_by_user_id` and
        `last_review_note`".

        Design: Difficulty/non_linear_state_machine/documentation_package_reject_loop_returns_to_assembling
        """
        ctx = _uncontrolled_submitted_package(api)
        validate_success(
            _review(api, ctx["package"]["id"], "REJECTED", actor_id=QM_SECOND),
            expected_status=200,
        )
        _attach(api, ctx["package"]["id"], "EXPORT_LICENSE", QM_PRIMARY)

        resubmitted = validate_success(
            _submit(api, ctx["package"]["id"], QM_PRIMARY), expected_status=200
        )
        approved = validate_success(
            _review(api, ctx["package"]["id"], "APPROVED", actor_id=QM_SECOND),
            expected_status=200,
        )

        assert resubmitted["package_status"] == "SUBMITTED", (
            f"the second submission is admissible, got {resubmitted['package_status']}"
        )
        assert approved["package_status"] == "APPROVED", (
            f"package_status must be APPROVED, got {approved['package_status']}"
        )
        assert approved["rejection_count"] == 1, (
            "the second round does not clear the earlier rejection, got "
            f"{approved['rejection_count']}"
        )
        assert approved["reviewed_by_user_id"] == QM_SECOND
        stored = _read_package(api, ctx["package"]["id"])
        assert stored["package_status"] == "APPROVED"
        assert stored["rejection_count"] == 1


def _sealed_with_submitted_package(api):
    """A sealed two-element build whose complete package is still only SUBMITTED."""
    ctx = setup_sealed_assembly(api, component_specs=CANONICAL_TWO_ELEMENT_SPECS)
    package = open_documentation_package(api, ctx["assembly"]["id"], QM_PRIMARY)
    attach_documents(
        api, package["id"], list(FULL_REQUIRED_SET), QM_PRIMARY
    )
    ctx["package"] = package
    ctx["submitted"] = validate_success(
        _submit(api, package["id"], QM_PRIMARY), expected_status=200
    )
    return ctx


class TestReleaseNeedsAnApprovedPackage:
    """A complete package is not an approved package, and release knows it."""

    def test_the_readiness_projection_names_the_unapproved_package_as_the_blocker(
        self, api
    ):
        """Three gates stand open and the fourth names the exact refusal.

        The PRD states that the projection reports "the `active_component_count`, four
        booleans — `inspection_ok`, `export_ok`, `documentation_ok` and `wavefront_ok`
        — the assembly's `total_transmitted_wavefront_waves` beside the design's
        `transmitted_wavefront_budget_waves`, the package's `completeness_pct`, and
        `blocking_error_id`, which names the error identifier a release attempt would
        return right now, or null when the assembly is releasable."

        Design: Difficulty/cross_entity_state_dependency/assembly_release_requires_documentation_package_approved
        """
        ctx = _sealed_with_submitted_package(api)
        assert ctx["submitted"]["package_status"] == "SUBMITTED"

        readiness = _readiness(api, ctx["assembly"]["id"])

        assert readiness["assembly_id"] == ctx["assembly"]["id"]
        assert readiness["assembly_status"] == "SEALED", (
            f"assembly_status must be SEALED, got {readiness['assembly_status']}"
        )
        assert readiness["active_component_count"] == 2, (
            f"active_component_count must be 2, got {readiness['active_component_count']}"
        )
        assert_readiness_gates(
            readiness,
            inspection_ok=True,
            export_ok=True,
            documentation_ok=False,
            wavefront_ok=True,
            blocking_error_id=ERR_DOCUMENTATION_NOT_APPROVED,
        )
        assert_wavefront_value(
            readiness["total_transmitted_wavefront_waves"],
            0.1049,
            "total_transmitted_wavefront_waves",
        )
        assert_wavefront_value(
            readiness["transmitted_wavefront_budget_waves"],
            0.1050,
            "transmitted_wavefront_budget_waves",
        )
        assert_two_dp_value(readiness["completeness_pct"], 100.00, "completeness_pct")

    def test_release_is_refused_while_the_package_waits_for_review(self, api):
        """The fourth gate fires even though the package is 100.00 complete.

        The PRD states that "that package's `package_status` must be `APPROVED`,
        otherwise `ERR_DOCUMENTATION_NOT_APPROVED`."

        Design: Difficulty/cross_entity_state_dependency/assembly_release_requires_documentation_package_approved
        """
        ctx = _sealed_with_submitted_package(api)

        refused = _release(api, ctx["assembly"]["id"])

        validate_error(refused, ERR_DOCUMENTATION_NOT_APPROVED)
        unchanged = _read_assembly(api, ctx["assembly"]["id"])
        assert unchanged["assembly_status"] == "SEALED", (
            f"a refused release leaves the assembly SEALED, got "
            f"{unchanged['assembly_status']}"
        )
        assert unchanged["released_at_utc"] is None, (
            f"released_at_utc must stay null, got {unchanged['released_at_utc']}"
        )
        package = _read_package(api, ctx["package"]["id"])
        assert package["package_status"] == "SUBMITTED", (
            f"the refused release may not advance the package, got "
            f"{package['package_status']}"
        )
        assert_two_dp_value(package["completeness_pct"], 100.00, "completeness_pct")

    def test_the_approval_opens_the_gate_and_release_stamps_the_clock(self, api):
        """Approving the package is the only change the release needed.

        The PRD states that "On success the assembly moves `SEALED → RELEASED`, a
        terminal state, and `released_at_utc` is stamped from the logical clock."

        Design: Difficulty/cross_entity_state_dependency/assembly_release_requires_documentation_package_approved
        """
        ctx = _sealed_with_submitted_package(api)
        validate_error(_release(api, ctx["assembly"]["id"]), ERR_DOCUMENTATION_NOT_APPROVED)

        approved = validate_success(
            _review(api, ctx["package"]["id"], "APPROVED", actor_id=QM_SECOND),
            expected_status=200,
        )
        released = validate_success(
            _release(api, ctx["assembly"]["id"]), expected_status=200
        )

        assert approved["package_status"] == "APPROVED", (
            f"package_status must be APPROVED, got {approved['package_status']}"
        )
        assert approved["reviewed_by_user_id"] == QM_SECOND
        assert released["assembly_status"] == "RELEASED", (
            f"assembly_status must be RELEASED, got {released['assembly_status']}"
        )
        assert released["released_at_utc"] == CLOCK_EPOCH_UTC, (
            f"released_at_utc must be {CLOCK_EPOCH_UTC}, got {released['released_at_utc']}"
        )
        final = _readiness(api, ctx["assembly"]["id"])
        assert_readiness_gates(
            final,
            inspection_ok=True,
            export_ok=True,
            documentation_ok=True,
            wavefront_ok=True,
            blocking_error_id=ERR_INVALID_STATE_TRANSITION,
        )


def test_completeness_counts_required_types_only(api):
    """A fifth, unrequired document is stored and ignored by the percentage.

    The PRD states that "`completeness_pct` is one hundred multiplied by the number of
    required types that are present, divided by the number of required types, rounded
    half up to two decimal places. Documents attached that are not in the required set
    are stored faithfully but never raise `completeness_pct`".

    Design: Corner/calculations/documentation_completeness_counts_required_types_only
    """
    ctx = setup_aligned_assembly(api)
    package = open_documentation_package(api, ctx["assembly"]["id"], QM_PRIMARY)
    assert_package_documents(
        package,
        required_document_types=FULL_REQUIRED_SET,
        present_document_types=[],
        missing_document_types=FULL_REQUIRED_SET,
        completeness_pct=0.00,
    )

    four = attach_documents(
        api, package["id"], list(UNCONTROLLED_REQUIRED_SET), QM_PRIMARY
    )

    assert_package_documents(
        four,
        required_document_types=FULL_REQUIRED_SET,
        present_document_types=UNCONTROLLED_REQUIRED_SET,
        missing_document_types=["EXPORT_LICENSE"],
        completeness_pct=80.00,
    )

    extra = _attach(api, package["id"], "INSPECTION_WAIVER", QM_PRIMARY)

    assert_two_dp_value(extra["completeness_pct"], 80.00, "completeness_pct")
    assert list(extra["missing_document_types"]) == ["EXPORT_LICENSE"], (
        "an unrequired document fills no gap, got "
        f"{extra['missing_document_types']}"
    )
    assert len(extra["attached_documents"]) == 5, (
        f"attached_documents must hold five entries, got {extra['attached_documents']}"
    )
    assert list(extra["present_document_types"]) == list(
        UNCONTROLLED_REQUIRED_SET
    ) + ["INSPECTION_WAIVER"], (
        "present_document_types reports attachment order, got "
        f"{extra['present_document_types']}"
    )

    complete = _attach(api, package["id"], "EXPORT_LICENSE", QM_PRIMARY)
    submitted = validate_success(
        _submit(api, package["id"], QM_PRIMARY), expected_status=200
    )

    assert_two_dp_value(complete["completeness_pct"], 100.00, "completeness_pct")
    assert list(complete["missing_document_types"]) == [], (
        f"nothing is missing now, got {complete['missing_document_types']}"
    )
    assert submitted["package_status"] == "SUBMITTED", (
        f"package_status must be SUBMITTED, got {submitted['package_status']}"
    )
    assert submitted["submitted_by_user_id"] == QM_PRIMARY, (
        f"submitted_by_user_id must be {QM_PRIMARY}, got "
        f"{submitted['submitted_by_user_id']}"
    )
    assert submitted["rejection_count"] == 0, (
        f"rejection_count must still be 0, got {submitted['rejection_count']}"
    )


def test_completeness_rounds_two_thirds_half_up_to_two_decimals(api):
    """One and two of three base documents read 33.33 and 66.67.

    The PRD states that "Three documents are always required:
    `CERTIFICATE_OF_CONFORMANCE`, `MELT_CERTIFICATE` and `INTERFEROGRAM_REPORT`." and
    that completeness is "rounded half up to two decimal places".

    Design: Corner/calculations/completeness_percentage_rounds_two_thirds_half_up_to_two_decimals
    """
    design = create_design(api, design_code="OD-2540-PCT")
    assembly = create_assembly(api, design["id"], assembly_code="AS-2540-PCT")
    package = open_documentation_package(api, assembly["id"], QM_PRIMARY)
    assert list(package["required_document_types"]) == list(
        BASE_REQUIRED_DOCUMENT_TYPES
    ), (
        "with no coating run and no classification only the three base types are "
        f"required, got {package['required_document_types']}"
    )

    one = _attach(api, package["id"], "CERTIFICATE_OF_CONFORMANCE", QM_PRIMARY)
    two = _attach(api, package["id"], "MELT_CERTIFICATE", QM_PRIMARY)

    assert_two_dp_value(one["completeness_pct"], 33.33, "completeness_pct")
    assert_two_dp_value(two["completeness_pct"], 66.67, "completeness_pct")
    assert two["completeness_pct"] != 66.66, (
        f"two thirds rounds half up, not down, got {two['completeness_pct']}"
    )
    assert list(two["missing_document_types"]) == ["INTERFEROGRAM_REPORT"], (
        f"missing_document_types must name the third, got {two['missing_document_types']}"
    )

    premature = _submit(api, package["id"], QM_PRIMARY)

    validate_error(premature, ERR_DOCUMENTATION_INCOMPLETE)
    still_open = _read_package(api, package["id"])
    assert still_open["package_status"] == "ASSEMBLING", (
        f"a refused submission leaves the package open, got "
        f"{still_open['package_status']}"
    )
    assert still_open["submitted_by_user_id"] is None, (
        f"submitted_by_user_id must stay null, got {still_open['submitted_by_user_id']}"
    )

    three = _attach(api, package["id"], "INTERFEROGRAM_REPORT", QM_PRIMARY)
    submitted = validate_success(
        _submit(api, package["id"], QM_PRIMARY), expected_status=200
    )

    assert_two_dp_value(three["completeness_pct"], 100.00, "completeness_pct")
    assert list(three["missing_document_types"]) == []
    assert submitted["package_status"] == "SUBMITTED", (
        f"package_status must be SUBMITTED, got {submitted['package_status']}"
    )


def test_the_release_gate_distinguishes_missing_incomplete_and_unapproved_packages(api):
    """Three different documentation faults produce three different codes.

    The PRD states that "A documentation package must exist for the assembly, otherwise
    `ERR_DOCUMENTATION_PACKAGE_NOT_FOUND`. And that package's `package_status` must be
    `APPROVED`, otherwise `ERR_DOCUMENTATION_NOT_APPROVED`." while submission "demands
    `completeness_pct` of exactly 100.00 and is otherwise refused with
    `ERR_DOCUMENTATION_INCOMPLETE`".

    Design: Corner/errors/the_release_gate_reports_a_missing_an_incomplete_and_an_unapproved_package_differently
    """
    ctx = setup_sealed_assembly(api)
    assembly_id = ctx["assembly"]["id"]

    without_package = _release(api, assembly_id)

    validate_error(without_package, ERR_DOCUMENTATION_PACKAGE_NOT_FOUND)

    package = validate_success(
        api.create_documentation_package(
            build_documentation_package_payload(assembly_id),
            make_quality_manager_headers(QM_PRIMARY),
        ),
        expected_status=201,
    )

    assert package["package_status"] == "ASSEMBLING", (
        f"a new package is born ASSEMBLING, got {package['package_status']}"
    )
    assert_package_documents(
        package,
        required_document_types=FULL_REQUIRED_SET,
        present_document_types=[],
        missing_document_types=FULL_REQUIRED_SET,
        completeness_pct=0.00,
    )

    partial = attach_documents(
        api, package["id"], list(BASE_REQUIRED_DOCUMENT_TYPES), QM_PRIMARY
    )
    incomplete = _submit(api, package["id"], QM_PRIMARY)
    unapproved = _release(api, assembly_id)

    assert_package_documents(
        partial,
        required_document_types=FULL_REQUIRED_SET,
        present_document_types=BASE_REQUIRED_DOCUMENT_TYPES,
        missing_document_types=["COATING_SPECTRAL_DATA", "EXPORT_LICENSE"],
        completeness_pct=60.00,
    )
    validate_error(incomplete, ERR_DOCUMENTATION_INCOMPLETE)
    still_open = _read_package(api, package["id"])
    assert still_open["package_status"] == "ASSEMBLING", (
        f"the refused submission leaves ASSEMBLING, got {still_open['package_status']}"
    )
    validate_error(unapproved, ERR_DOCUMENTATION_NOT_APPROVED)

    complete = attach_documents(
        api,
        package["id"],
        ["COATING_SPECTRAL_DATA", "EXPORT_LICENSE"],
        QM_PRIMARY,
    )
    submitted = validate_success(
        _submit(api, package["id"], QM_PRIMARY), expected_status=200
    )
    validate_success(
        _review(api, package["id"], "APPROVED", actor_id=QM_SECOND),
        expected_status=200,
    )
    released = validate_success(_release(api, assembly_id), expected_status=200)

    assert_two_dp_value(complete["completeness_pct"], 100.00, "completeness_pct")
    assert submitted["submitted_by_user_id"] == QM_PRIMARY
    assert released["assembly_status"] == "RELEASED", (
        f"assembly_status must be RELEASED, got {released['assembly_status']}"
    )
    assert released["released_at_utc"] == CLOCK_EPOCH_UTC, (
        f"released_at_utc must be {CLOCK_EPOCH_UTC}, got {released['released_at_utc']}"
    )


def test_the_submitter_may_not_review_but_any_other_manager_may(api):
    """Segregation of duties binds the submitter, not the role.

    The PRD states that "Only a `QualityManager` reviews, and only a package in
    `SUBMITTED`; the submission carries a `decision` of `APPROVED` or `REJECTED` and an
    optional `review_note`, and the reviewer must not be the `submitted_by_user_id`,
    otherwise `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/rbac/the_submitter_of_a_package_may_not_review_it_but_any_other_manager_may
    """
    design = create_design(api, design_code="OD-2540-SOD")
    first = create_assembly(api, design["id"], assembly_code="AS-2540-SOD-1")
    second = create_assembly(api, design["id"], assembly_code="AS-2540-SOD-2")
    package_one = open_documentation_package(api, first["id"], QM_PRIMARY)
    package_two = open_documentation_package(api, second["id"], QM_PRIMARY)
    attach_documents(
        api, package_one["id"], list(BASE_REQUIRED_DOCUMENT_TYPES), QM_PRIMARY
    )
    attach_documents(
        api, package_two["id"], list(BASE_REQUIRED_DOCUMENT_TYPES), QM_PRIMARY
    )
    submitted_one = validate_success(
        _submit(api, package_one["id"], QM_PRIMARY), expected_status=200
    )
    submitted_two = validate_success(
        api.submit_documentation_package(
            package_two["id"], make_process_technician_headers()
        ),
        expected_status=200,
    )
    assert submitted_one["submitted_by_user_id"] == QM_PRIMARY
    assert submitted_two["submitted_by_user_id"] == PROCESS_TECHNICIAN_ID, (
        "a process technician may submit, got "
        f"{submitted_two['submitted_by_user_id']}"
    )

    self_review = _review(api, package_one["id"], "APPROVED", actor_id=QM_PRIMARY)

    validate_error(self_review, ERR_SEGREGATION_OF_DUTIES)
    untouched = _read_package(api, package_one["id"])
    assert untouched["package_status"] == "SUBMITTED", (
        f"the refused self-review leaves SUBMITTED, got {untouched['package_status']}"
    )
    assert untouched["reviewed_by_user_id"] is None, (
        f"reviewed_by_user_id must stay null, got {untouched['reviewed_by_user_id']}"
    )
    assert untouched["rejection_count"] == 0, (
        f"rejection_count must stay 0, got {untouched['rejection_count']}"
    )

    rejected = validate_success(
        _review(
            api,
            package_one["id"],
            "REJECTED",
            actor_id=QM_SECOND,
            review_note="Certificate of conformance is unsigned",
        ),
        expected_status=200,
    )

    assert rejected["package_status"] == "ASSEMBLING"
    assert rejected["rejection_count"] == 1, (
        f"rejection_count must be 1, got {rejected['rejection_count']}"
    )
    assert rejected["last_review_note"] == "Certificate of conformance is unsigned"
    assert_two_dp_value(rejected["completeness_pct"], 100.00, "completeness_pct")

    resubmitted = validate_success(
        _submit(api, package_one["id"], QM_SECOND), expected_status=200
    )
    rotated_review = validate_success(
        _review(api, package_one["id"], "APPROVED", actor_id=QM_PRIMARY),
        expected_status=200,
    )
    other_package = validate_success(
        _review(api, package_two["id"], "APPROVED", actor_id=QM_PRIMARY),
        expected_status=200,
    )

    assert resubmitted["submitted_by_user_id"] == QM_SECOND, (
        "the resubmission moves the duty to the second manager, got "
        f"{resubmitted['submitted_by_user_id']}"
    )
    assert rotated_review["package_status"] == "APPROVED", (
        "the earlier self-reviewer is now an admissible reviewer, got "
        f"{rotated_review['package_status']}"
    )
    assert rotated_review["reviewed_by_user_id"] == QM_PRIMARY
    assert other_package["package_status"] == "APPROVED", (
        "a package submitted by a technician is reviewable by any manager, got "
        f"{other_package['package_status']}"
    )
    assert other_package["reviewed_by_user_id"] == QM_PRIMARY


def test_release_readiness_reports_each_gate_separately_and_mutates_nothing(api):
    """The projection tracks the build from two open gates to none.

    The PRD states that "Because the release gate is deep, the system offers a computed,
    non-mutating projection of it for any assembly." and that "It mutates nothing and is
    readable by all seven roles."

    Design: Corner/endpoints/release_readiness_reports_each_gate_separately_and_mutates_nothing
    """
    ctx = setup_aligned_assembly(api)
    assembly_id = ctx["assembly"]["id"]

    early = _readiness(api, assembly_id)

    assert early["assembly_id"] == assembly_id
    assert early["assembly_status"] == "ALIGNED", (
        f"assembly_status must be ALIGNED, got {early['assembly_status']}"
    )
    assert early["active_component_count"] == 2, (
        f"active_component_count must be 2, got {early['active_component_count']}"
    )
    assert_readiness_gates(
        early,
        inspection_ok=False,
        export_ok=True,
        documentation_ok=False,
        wavefront_ok=True,
        blocking_error_id=ERR_INVALID_STATE_TRANSITION,
    )
    assert_wavefront_value(
        early["total_transmitted_wavefront_waves"],
        0.0985,
        "total_transmitted_wavefront_waves",
    )
    assert_wavefront_value(
        early["transmitted_wavefront_budget_waves"],
        0.1050,
        "transmitted_wavefront_budget_waves",
    )

    validate_success(
        api.create_inspection_record(
            build_inspection_record_payload(assembly_id),
            make_metrology_technician_headers(MT_RECORDER),
        ),
        expected_status=201,
    )
    validate_success(
        api.seal_assembly(assembly_id, make_quality_manager_headers(QM_PRIMARY)),
        expected_status=200,
    )
    package = open_documentation_package(api, assembly_id, QM_PRIMARY)
    attach_documents(api, package["id"], list(FULL_REQUIRED_SET), QM_PRIMARY)
    validate_success(_submit(api, package["id"], QM_PRIMARY), expected_status=200)
    validate_success(
        _review(api, package["id"], "APPROVED", actor_id=QM_SECOND),
        expected_status=200,
    )

    ready = _readiness(api, assembly_id)

    assert ready["assembly_status"] == "SEALED", (
        f"assembly_status must be SEALED, got {ready['assembly_status']}"
    )
    assert_readiness_gates(
        ready,
        inspection_ok=True,
        export_ok=True,
        documentation_ok=True,
        wavefront_ok=True,
        blocking_error_id=None,
    )
    assert_two_dp_value(ready["completeness_pct"], 100.00, "completeness_pct")
    after = _read_assembly(api, assembly_id)
    assert after["assembly_status"] == "SEALED", (
        f"reading the gate may not release the assembly, got {after['assembly_status']}"
    )
    assert after["released_at_utc"] is None, (
        f"released_at_utc must still be null, got {after['released_at_utc']}"
    )
