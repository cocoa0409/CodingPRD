"""The three ordered gates on work-order creation and the reservation it freezes."""

from test_helpers import (
    ALL_ZERO_UUID,
    CANCEL_REASON_WORK_ORDER_CANCELLED,
    CLOCK_EPOCH_UTC,
    ECO_CLASSIFIER,
    ECO_DECIDER,
    ERR_DESIGN_NOT_FOUND,
    ERR_DESIGN_NOT_RELEASED,
    ERR_GLASS_GRADE_UNSUITABLE,
    ERR_GLASS_LOT_NOT_RELEASED,
    ERR_INSUFFICIENT_BLANKS,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE_TRANSITION,
    ERR_RUN_STAGE_OUT_OF_ORDER,
    ERR_STALE_GLASS_LOT_VERSION,
    QM_PRIMARY,
    assert_blank_conservation,
    assert_blank_ledger,
    assert_booked_minutes,
    assert_null_fields,
    assert_removal_ledger,
    assert_work_order_dimensions,
    build_cancel_work_order_payload,
    build_certification_payload,
    build_license_decision_payload,
    build_process_run_payload,
    build_scrap_payload,
    build_work_order_payload,
    create_certified_lot,
    create_design,
    create_glass_lot,
    create_instrument,
    create_released_design,
    add_allocation,
    classify_design,
    error_id_of,
    make_export_compliance_officer_headers,
    make_optics_engineer_headers,
    make_plant_admin_headers,
    make_procurement_officer_headers,
    make_process_technician_headers,
    make_quality_manager_headers,
    omit,
    open_work_order,
    validate_error,
    validate_paginated,
    validate_success,
)


CANCEL_REASON = "CUSTOMER_ORDER_WITHDRAWN"


def _read_lot(api, lot_id):
    """Read one melt lot as the receiving desk."""
    return validate_success(
        api.get_glass_lot(lot_id, make_procurement_officer_headers()),
        expected_status=200,
    )


def _read_order(api, work_order_id):
    """Read one work order as the shop floor."""
    return validate_success(
        api.get_work_order(work_order_id, make_process_technician_headers()),
        expected_status=200,
    )


def _grade_demanding_design(api):
    """A released design that demands an H2 substrate free of striae."""
    return create_released_design(
        api,
        design_code="OD-2540-A",
        min_index_homogeneity_grade="H2",
        max_striae_grade="A",
    )


def _single_blank_lot(api, lot_code, grade, striae):
    """A certified one-blank lot whose measured grades are given explicitly."""
    return create_certified_lot(
        api,
        certification_overrides={
            "measured_index_homogeneity_grade": grade,
            "measured_striae_grade": striae,
            "certificate_reference": f"CERT-{lot_code}",
        },
        lot_code=lot_code,
        total_blank_count=1,
        declared_index_homogeneity_grade=grade,
        declared_striae_grade=striae,
    )


class TestGradeSuitabilityOutranksBlankSufficiency:
    """A lot that is both wrong glass and too small reports the glass first."""

    def test_a_lot_failing_grade_and_blanks_reports_the_grade_error(self, api):
        """The substrate gate is adjudicated before the blank count.

        The PRD ranks "The lot's effective grades and blank thickness suit the
        design" at priority 21 and "The lot has enough available blanks for the
        work order's computed reservation" at priority 26, and states that the
        three gates on a reservation "are adjudicated in the order given here".

        Design: Difficulty/priority_pair_validation_conflict/glass_grade_suitability_outranks_blank_sufficiency_on_work_order_create
        """
        design = _grade_demanding_design(api)
        bad = _single_blank_lot(api, "GL-2540-B", "H5", "D")

        response = api.create_work_order(
            build_work_order_payload(
                design["id"], bad["id"], bad["version"], element_count=4
            ),
            make_process_technician_headers(),
        )

        validate_error(response, ERR_GLASS_GRADE_UNSUITABLE, expected_status=409)
        assert error_id_of(response) != ERR_INSUFFICIENT_BLANKS, (
            "the lower-priority blank rule must not surface while the grade rule "
            f"is broken, got {error_id_of(response)}"
        )

    def test_a_grade_compliant_but_short_lot_reports_insufficient_blanks(self, api):
        """Removing only the grade defect exposes the blank defect underneath.

        The PRD states that the reservation "is admissible only when the lot's
        `available_blank_count` **before** the move is greater than or equal to
        that frozen figure; exact equality is admissible, and anything less is
        refused with `ERR_INSUFFICIENT_BLANKS`".

        Design: Difficulty/priority_pair_validation_conflict/glass_grade_suitability_outranks_blank_sufficiency_on_work_order_create
        """
        design = _grade_demanding_design(api)
        good_glass = _single_blank_lot(api, "GL-2540-G", "H2", "A")

        response = api.create_work_order(
            build_work_order_payload(
                design["id"], good_glass["id"], good_glass["version"], element_count=4
            ),
            make_process_technician_headers(),
        )

        validate_error(response, ERR_INSUFFICIENT_BLANKS, expected_status=409)

    def test_neither_refusal_moves_the_ledger_of_the_lot_it_named(self, api):
        """Both refused creates leave their lots exactly as they found them.

        The PRD states that "the invariant `total_blank_count` equals
        `available_blank_count` plus `reserved_blank_count` plus
        `consumed_blank_count` plus `scrapped_blank_count` must hold after every
        single move".

        Design: Difficulty/priority_pair_validation_conflict/glass_grade_suitability_outranks_blank_sufficiency_on_work_order_create
        """
        design = _grade_demanding_design(api)
        bad = _single_blank_lot(api, "GL-2540-B", "H5", "D")
        good_glass = _single_blank_lot(api, "GL-2540-G", "H2", "A")

        for lot in (bad, good_glass):
            refused = api.create_work_order(
                build_work_order_payload(
                    design["id"], lot["id"], lot["version"], element_count=4
                ),
                make_process_technician_headers(),
            )
            assert refused.status_code == 409, (
                f"the create against {lot['lot_code']} must be refused, got "
                f"{refused.status_code}"
            )

        after_bad = _read_lot(api, bad["id"])
        assert after_bad["effective_index_homogeneity_grade"] == "H5", (
            "the unsuitable lot keeps its measured homogeneity grade, got "
            f"{after_bad['effective_index_homogeneity_grade']}"
        )
        assert after_bad["effective_striae_grade"] == "D", (
            f"got {after_bad['effective_striae_grade']}"
        )
        assert_blank_ledger(
            after_bad, reserved=0, consumed=0, scrapped=0, available=1, total=1
        )
        assert_blank_conservation(after_bad)

        after_good = _read_lot(api, good_glass["id"])
        assert after_good["effective_index_homogeneity_grade"] == "H2", (
            f"got {after_good['effective_index_homogeneity_grade']}"
        )
        assert_blank_ledger(
            after_good, reserved=0, consumed=0, scrapped=0, available=1, total=1
        )
        assert_blank_conservation(after_good)


class TestWorkOrderCreateRequiresGlassLotReleased:
    """The order's admissibility is decided by a different entity's state."""

    def test_a_quarantined_lot_refuses_the_create_and_reserves_nothing(self, api):
        """A lot still in quarantine cannot back a reservation.

        The PRD states that "a lot whose `lot_status` is anything other than
        `RELEASED` is refused with `ERR_GLASS_LOT_NOT_RELEASED`".

        Design: Difficulty/cross_entity_state_dependency/work_order_create_requires_glass_lot_released
        """
        design = create_released_design(api, design_code="OD-2540-A")
        lot = create_glass_lot(api, lot_code="GL-2540-1")
        assert lot["lot_status"] == "QUARANTINED", (
            f"a booked-in lot starts quarantined, got {lot['lot_status']}"
        )

        response = api.create_work_order(
            build_work_order_payload(design["id"], lot["id"], lot["version"]),
            make_process_technician_headers(),
        )

        validate_error(response, ERR_GLASS_LOT_NOT_RELEASED, expected_status=409)
        after = _read_lot(api, lot["id"])
        assert_blank_ledger(
            after, reserved=0, consumed=0, scrapped=0, available=20, total=20
        )
        assert after["version"] == 1, (
            f"a refused create may not bump the lot version, got {after['version']}"
        )

    def test_certifying_the_lot_makes_the_identical_call_succeed(self, api):
        """The same request is admitted once the lot reaches RELEASED.

        The PRD states that incoming inspection "moves the lot `QUARANTINED →
        RELEASED`" and that "`reserved_blank_count` is then `element_count` plus
        `spare_blank_count`, and this figure is **frozen on the order at creation**
        and used verbatim by every later ledger move, even if the design or the lot
        changes afterwards."

        Design: Difficulty/cross_entity_state_dependency/work_order_create_requires_glass_lot_released
        """
        design = create_released_design(api, design_code="OD-2540-A")
        lot = create_glass_lot(api, lot_code="GL-2540-1")
        refused = api.create_work_order(
            build_work_order_payload(design["id"], lot["id"], lot["version"]),
            make_process_technician_headers(),
        )
        assert refused.status_code == 409, (
            f"the create must be refused first, got {refused.status_code}"
        )

        certified = validate_success(
            api.certify_glass_lot(
                lot["id"],
                build_certification_payload(),
                make_procurement_officer_headers(),
            ),
            expected_status=200,
        )
        assert certified["lot_status"] == "RELEASED", (
            f"certification releases the lot, got {certified['lot_status']}"
        )
        assert certified["version"] == 2, (
            f"certification bumps the lot version to 2, got {certified['version']}"
        )
        assert certified["effective_index_homogeneity_grade"] == "H3", (
            "the measured grade takes over from the declared one, got "
            f"{certified['effective_index_homogeneity_grade']}"
        )

        admitted = validate_success(
            api.create_work_order(
                build_work_order_payload(
                    design["id"], lot["id"], certified["version"]
                ),
                make_process_technician_headers(),
            ),
            expected_status=201,
        )
        assert admitted["spare_blank_count"] == 1, (
            f"spare_blank_count must be 1, got {admitted['spare_blank_count']}"
        )
        assert admitted["reserved_blank_count"] == 3, (
            f"reserved_blank_count must be 3, got {admitted['reserved_blank_count']}"
        )
        assert admitted["process_status"] == "BLANKS_RESERVED", (
            f"got {admitted['process_status']}"
        )
        assert admitted["blank_center_thickness_um"] == 6200.0, (
            "the blank thickness is snapshotted from the lot, got "
            f"{admitted['blank_center_thickness_um']}"
        )

    def test_the_admitted_reservation_moves_the_lot_ledger_to_three_of_twenty(self, api):
        """Only the admitted create moves the blanks out of availability.

        The PRD states that "Opening a work order **reserves**: the reserved
        count rises by the order's frozen reservation size" and that
        `available_blank_count` "is always recomputed from the other three rather
        than adjusted independently".

        Design: Difficulty/cross_entity_state_dependency/work_order_create_requires_glass_lot_released
        """
        design = create_released_design(api, design_code="OD-2540-A")
        lot = create_glass_lot(api, lot_code="GL-2540-1")
        api.create_work_order(
            build_work_order_payload(design["id"], lot["id"], lot["version"]),
            make_process_technician_headers(),
        )
        certified = validate_success(
            api.certify_glass_lot(
                lot["id"],
                build_certification_payload(),
                make_procurement_officer_headers(),
            ),
            expected_status=200,
        )
        open_work_order(api, design["id"], lot["id"], certified["version"])

        final = _read_lot(api, lot["id"])
        assert_blank_ledger(
            final, reserved=3, consumed=0, scrapped=0, available=17, total=20
        )
        assert_blank_conservation(final)


class TestProcessAndComplianceDimensionsAdvanceIndependently:
    """Two disjoint trigger sets drive the two dimensions of one work order."""

    @staticmethod
    def _order_with_classification_and_run(api):
        """A work order under a licence-required design with a scheduled run."""
        design = create_released_design(api, design_code="OD-2540-A")
        classification = classify_design(api, design["id"], destination_country="DE")
        lot = create_certified_lot(api, lot_code="GL-2540-1")
        work_order = open_work_order(api, design["id"], lot["id"], lot["version"])
        instrument = create_instrument(api, instrument_code="IF-2540-1")
        run = validate_success(
            api.create_process_run(
                build_process_run_payload(work_order["id"], instrument["id"]),
                make_process_technician_headers(),
            ),
            expected_status=201,
        )
        return {
            "design": design,
            "classification": classification,
            "work_order": work_order,
            "instrument": instrument,
            "run": run,
        }

    def test_the_compliance_screen_leaves_the_fabrication_state_pinned(self, api):
        """Screening moves only the compliance dimension.

        The PRD states that "Every work order carries a second, independent
        state dimension" whose "`compliance_status` starts at `UNCLASSIFIED` and
        advances on triggers that have nothing to do with grinding or coating".

        Design: Difficulty/non_linear_state_machine/work_order_process_and_compliance_dimensions_advance_independently
        """
        ctx = self._order_with_classification_and_run(api)
        assert_work_order_dimensions(
            ctx["work_order"], "BLANKS_RESERVED", "UNCLASSIFIED"
        )

        screened = validate_success(
            api.compliance_screen_work_order(
                ctx["work_order"]["id"],
                make_export_compliance_officer_headers(ECO_CLASSIFIER),
            ),
            expected_status=200,
        )

        assert_work_order_dimensions(screened, "BLANKS_RESERVED", "SCREENED")
        assert_work_order_dimensions(
            _read_order(api, ctx["work_order"]["id"]), "BLANKS_RESERVED", "SCREENED"
        )

    def test_starting_the_run_leaves_the_compliance_state_pinned(self, api):
        """Starting the polishing run moves only the fabrication dimension.

        The PRD states that on starting a run "the run moves `SCHEDULED →
        IN_PROCESS`, its `started_at_utc` is stamped from the logical clock" and
        that "the work order's `process_status` is set to the run's `run_stage`".

        Design: Difficulty/non_linear_state_machine/work_order_process_and_compliance_dimensions_advance_independently
        """
        ctx = self._order_with_classification_and_run(api)
        validate_success(
            api.compliance_screen_work_order(
                ctx["work_order"]["id"],
                make_export_compliance_officer_headers(ECO_CLASSIFIER),
            ),
            expected_status=200,
        )

        started = validate_success(
            api.start_process_run(
                ctx["run"]["id"], make_process_technician_headers()
            ),
            expected_status=200,
        )

        assert started["run_status"] == "IN_PROCESS", (
            f"the run must be in process, got {started['run_status']}"
        )
        assert started["started_at_utc"] == CLOCK_EPOCH_UTC, (
            "started_at_utc is stamped from the logical clock, got "
            f"{started['started_at_utc']}"
        )
        assert_work_order_dimensions(
            _read_order(api, ctx["work_order"]["id"]), "POLISHING", "SCREENED"
        )

    def test_the_licence_decision_leaves_the_fabrication_state_pinned(self, api):
        """Approving the licence clears compliance without touching the shop floor.

        The PRD states that an approval "sets `classification_status` to
        `LICENSE_APPROVED`, records the `license_number`" and "then sweeps the
        design's backlog, moving every work order of that design whose
        `compliance_status` is `SCREENED` to `CLEARED`, in `created_at` ascending
        order".

        Design: Difficulty/non_linear_state_machine/work_order_process_and_compliance_dimensions_advance_independently
        """
        ctx = self._order_with_classification_and_run(api)
        validate_success(
            api.compliance_screen_work_order(
                ctx["work_order"]["id"],
                make_export_compliance_officer_headers(ECO_CLASSIFIER),
            ),
            expected_status=200,
        )
        validate_success(
            api.start_process_run(
                ctx["run"]["id"], make_process_technician_headers()
            ),
            expected_status=200,
        )

        decided = validate_success(
            api.record_license_decision(
                ctx["classification"]["id"],
                build_license_decision_payload("APPROVED"),
                make_export_compliance_officer_headers(ECO_DECIDER),
            ),
            expected_status=200,
        )

        assert decided["classification_status"] == "LICENSE_APPROVED", (
            f"got {decided['classification_status']}"
        )
        assert decided["license_number"] == "BIS-2540-001", (
            f"got {decided['license_number']}"
        )
        assert_work_order_dimensions(
            _read_order(api, ctx["work_order"]["id"]), "POLISHING", "CLEARED"
        )


def test_work_order_read_returns_the_row_including_the_fields_frozen_at_create(api):
    """The read carries both dimensions and every snapshotted parent value.

    The PRD states that "Three values are snapshotted at creation and never
    re-read from their sources: `pinned_design_revision` copies the design's
    `design_revision`, and `blank_center_thickness_um` copies the lot's
    as-received thickness."

    Design: Corner/entities/work_order_read_returns_the_row_including_the_fields_frozen_at_create
    """
    design = create_released_design(api, design_code="OD-2540-A")
    lot = create_certified_lot(api, lot_code="GL-2540-1")
    created = open_work_order(api, design["id"], lot["id"], lot["version"])

    row = _read_order(api, created["id"])

    assert row["id"] == created["id"], f"got {row['id']}"
    assert row["design_id"] == design["id"], f"got {row['design_id']}"
    assert row["glass_lot_id"] == lot["id"], f"got {row['glass_lot_id']}"
    assert row["element_count"] == 2, f"got {row['element_count']}"
    assert row["spare_blank_count"] == 1, f"got {row['spare_blank_count']}"
    assert row["reserved_blank_count"] == 3, f"got {row['reserved_blank_count']}"
    assert row["pinned_design_revision"] == 1, (
        f"pinned_design_revision must be 1, got {row['pinned_design_revision']}"
    )
    assert row["blank_center_thickness_um"] == 6200.0, (
        f"got {row['blank_center_thickness_um']}"
    )
    assert_removal_ledger(
        row,
        cumulative_removal_nm=0,
        remaining_center_thickness_um=6200.0,
        figuring_iteration_count=0,
    )
    assert_work_order_dimensions(row, "BLANKS_RESERVED", "UNCLASSIFIED")
    assert_null_fields(row, "hold_reason", "scrap_reason", "cancel_reason")
    assert row["version"] == 1, f"a fresh order starts at version 1, got {row['version']}"


def test_work_order_create_missing_required_element_count_is_rejected(api):
    """element_count carries no default, so its absence is malformed.

    The PRD states that "The `element_count` is the number of finished elements
    the order must deliver; it must be at least 1 and no more than 12", and ranks
    "The body parses; every required input field is present" at priority 5 with
    `ERR_INVALID_REQUEST`, 400.

    Design: Corner/entities/work_order_create_missing_required_element_count_is_rejected
    """
    design = create_released_design(api, design_code="OD-2540-A")
    lot = create_certified_lot(api, lot_code="GL-2540-1")

    response = api.create_work_order(
        omit(
            build_work_order_payload(design["id"], lot["id"], lot["version"]),
            "element_count",
        ),
        make_process_technician_headers(),
    )

    validate_error(response, ERR_INVALID_REQUEST, expected_status=400)
    after_refusal = _read_lot(api, lot["id"])
    assert_blank_ledger(
        after_refusal, reserved=0, consumed=0, scrapped=0, available=20, total=20
    )
    assert after_refusal["version"] == 2, (
        "the rejected create leaves the lot at its post-certification version, got "
        f"{after_refusal['version']}"
    )

    admitted = open_work_order(api, design["id"], lot["id"], after_refusal["version"])
    assert admitted["element_count"] == 2, f"got {admitted['element_count']}"
    assert admitted["reserved_blank_count"] == 3, (
        f"got {admitted['reserved_blank_count']}"
    )
    final = _read_lot(api, lot["id"])
    assert_blank_ledger(
        final, reserved=3, consumed=0, scrapped=0, available=17, total=20
    )


def test_blank_reservation_sizing_rounds_the_spare_term_up_per_order(api):
    """Both halves of the spare formula are exercised on one lot.

    The PRD states that "`spare_blank_count` is computed as the larger of one
    blank and one quarter of `element_count` rounded up to a whole blank — so an
    order for one, two, three or four elements carries one spare, an order for
    five carries two, an order for eight carries two, and an order for nine
    carries three."

    Design: Corner/calculations/blank_reservation_sizing_rounds_the_spare_term_up_per_order
    """
    design = create_released_design(api, design_code="OD-2540-A")
    lot = create_certified_lot(api, lot_code="GL-2540-1")

    first = open_work_order(
        api, design["id"], lot["id"], lot["version"], element_count=3, wo_code="WO-2540-A"
    )
    assert first["spare_blank_count"] == 1, (
        "one quarter of three rounds up to one, which is also the floor, got "
        f"{first['spare_blank_count']}"
    )
    assert first["reserved_blank_count"] == 4, f"got {first['reserved_blank_count']}"

    between = _read_lot(api, lot["id"])
    second = open_work_order(
        api,
        design["id"],
        lot["id"],
        between["version"],
        element_count=8,
        wo_code="WO-2540-B",
    )
    assert second["spare_blank_count"] == 2, (
        f"one quarter of eight is exactly two, got {second['spare_blank_count']}"
    )
    assert second["reserved_blank_count"] == 10, f"got {second['reserved_blank_count']}"

    final = _read_lot(api, lot["id"])
    assert_blank_ledger(
        final, reserved=14, consumed=0, scrapped=0, available=6, total=20
    )
    assert_blank_conservation(final)
    assert final["version"] == 4, (
        "the lot is bumped by its creation, its certification and once per order, "
        f"got {final['version']}"
    )


def test_a_missing_required_field_outranks_the_lot_state_gate(api):
    """The malformed body is reported before the cross-entity state gate.

    The PRD ranks "The body parses; every required input field is present" at
    priority 5 and "Cross-entity state dependency: a work order's design is
    released and its lot is released" at priority 13.

    Design: Corner/validations/a_missing_required_field_outranks_the_lot_state_gate
    """
    design = create_released_design(api, design_code="OD-2540-A")
    lot = create_glass_lot(api, lot_code="GL-2540-1")

    malformed = api.create_work_order(
        omit(
            build_work_order_payload(design["id"], lot["id"], lot["version"]),
            "element_count",
        ),
        make_process_technician_headers(),
    )
    validate_error(malformed, ERR_INVALID_REQUEST, expected_status=400)

    well_formed = api.create_work_order(
        build_work_order_payload(design["id"], lot["id"], lot["version"]),
        make_process_technician_headers(),
    )
    validate_error(well_formed, ERR_GLASS_LOT_NOT_RELEASED, expected_status=409)

    untouched = _read_lot(api, lot["id"])
    assert untouched["lot_status"] == "QUARANTINED", f"got {untouched['lot_status']}"
    assert untouched["version"] == 1, (
        f"neither refusal may bump the lot version, got {untouched['version']}"
    )

    certified = validate_success(
        api.certify_glass_lot(
            lot["id"], build_certification_payload(), make_procurement_officer_headers()
        ),
        expected_status=200,
    )
    admitted = open_work_order(api, design["id"], lot["id"], certified["version"])
    assert admitted["element_count"] == 2, f"got {admitted['element_count']}"
    assert admitted["reserved_blank_count"] == 3, (
        f"got {admitted['reserved_blank_count']}"
    )


def test_a_body_foreign_key_not_found_outranks_both_cross_entity_state_gates(api):
    """Four creates peel the stacked defects off one at a time.

    The PRD ranks "Every foreign-key id in the request body resolves, in the
    order the endpoint lists its input fields" at priority 4 above the
    cross-entity state gates of priority 13,
    and states that "a design whose `design_status` is anything other than
    `RELEASED` is refused with `ERR_DESIGN_NOT_RELEASED`".

    Design: Corner/validations/a_body_foreign_key_not_found_outranks_both_cross_entity_state_gates
    """
    design = create_design(api, design_code="OD-2540-A")
    add_allocation(api, design["id"])
    lot = create_glass_lot(api, lot_code="GL-2540-1")

    unknown_parent = api.create_work_order(
        build_work_order_payload(ALL_ZERO_UUID, lot["id"], lot["version"]),
        make_process_technician_headers(),
    )
    validate_error(unknown_parent, ERR_DESIGN_NOT_FOUND, expected_status=404)

    draft_design = api.create_work_order(
        build_work_order_payload(design["id"], lot["id"], lot["version"]),
        make_process_technician_headers(),
    )
    validate_error(draft_design, ERR_DESIGN_NOT_RELEASED, expected_status=409)

    validate_success(
        api.run_tolerance_analysis(design["id"], make_optics_engineer_headers()),
        expected_status=200,
    )
    validate_success(
        api.release_optical_design(design["id"], make_optics_engineer_headers()),
        expected_status=200,
    )

    quarantined_lot = api.create_work_order(
        build_work_order_payload(design["id"], lot["id"], lot["version"]),
        make_process_technician_headers(),
    )
    validate_error(quarantined_lot, ERR_GLASS_LOT_NOT_RELEASED, expected_status=409)
    assert _read_lot(api, lot["id"])["version"] == 1, (
        "no refused create may bump the optimistic-concurrency field"
    )

    certified = validate_success(
        api.certify_glass_lot(
            lot["id"], build_certification_payload(), make_procurement_officer_headers()
        ),
        expected_status=200,
    )
    assert certified["version"] == 2, f"got {certified['version']}"

    admitted = open_work_order(api, design["id"], lot["id"], certified["version"])
    assert admitted["reserved_blank_count"] == 3, (
        f"got {admitted['reserved_blank_count']}"
    )
    final = _read_lot(api, lot["id"])
    assert_blank_ledger(
        final, reserved=3, consumed=0, scrapped=0, available=17, total=20
    )


def test_a_second_work_order_on_the_same_lot_must_re_read_the_blank_ledger_first(api):
    """The stale-version guard is the only thing standing between two writers.

    The PRD states that "Two work orders drawing blanks from the same lot are both
    perfectly legitimate, so nothing in the lot's state machine stops the second
    writer; the stale-version check is what forces the client to re-read the blank
    ledger before committing another reservation."

    Design: Corner/complexity_layers/a_second_work_order_on_the_same_lot_must_re_read_the_blank_ledger_first
    """
    design = create_released_design(api, design_code="OD-2540-A")
    lot = create_certified_lot(api, lot_code="GL-2540-1")
    client_view = lot["version"]

    first = open_work_order(
        api, design["id"], lot["id"], client_view, wo_code="WO-2540-A"
    )
    assert first["reserved_blank_count"] == 3, f"got {first['reserved_blank_count']}"
    assert first["spare_blank_count"] == 1, f"got {first['spare_blank_count']}"

    after_first = _read_lot(api, lot["id"])
    assert after_first["version"] == 3, (
        f"the first reservation bumps the lot to version 3, got {after_first['version']}"
    )
    assert_blank_ledger(
        after_first, reserved=3, consumed=0, scrapped=0, available=17, total=20
    )

    stale = api.create_work_order(
        build_work_order_payload(
            design["id"], lot["id"], client_view, wo_code="WO-2540-B"
        ),
        make_process_technician_headers(),
    )
    validate_error(stale, ERR_STALE_GLASS_LOT_VERSION, expected_status=412)
    unchanged = _read_lot(api, lot["id"])
    assert unchanged["version"] == 3, f"got {unchanged['version']}"
    assert_blank_ledger(
        unchanged, reserved=3, consumed=0, scrapped=0, available=17, total=20
    )

    replayed = open_work_order(
        api, design["id"], lot["id"], unchanged["version"], wo_code="WO-2540-B"
    )
    assert replayed["reserved_blank_count"] == 3, (
        f"got {replayed['reserved_blank_count']}"
    )
    final = _read_lot(api, lot["id"])
    assert final["version"] == 4, f"got {final['version']}"
    assert_blank_ledger(
        final, reserved=6, consumed=0, scrapped=0, available=14, total=20
    )
    assert_blank_conservation(final)

    rows, meta = validate_paginated(
        api.list_work_orders(make_process_technician_headers())
    )
    assert meta["total_count"] == 2, (
        f"the refused create must not have left a row behind, got {meta['total_count']}"
    )
    assert len(rows) == 2, f"got {len(rows)}"


def test_cancelled_work_order_refuses_every_further_transition(api):
    """CANCELLED is terminal, and no refusal may move a ledger a second time.

    The PRD states that an order may be cancelled from six states and that "from
    any other state — including `COATING`, `COATED`, `RELEASED_TO_ASSEMBLY` and
    the two terminal states — the request is refused with
    `ERR_INVALID_STATE_TRANSITION`", and that a post-release scrap is admissible
    only from `FIGURE_ACCEPTED`, `COATED` or `RELEASED_TO_ASSEMBLY` because "From
    any other fabrication state the request is refused with
    `ERR_INVALID_STATE_TRANSITION`."

    Design: Corner/state_machines/cancelled_work_order_refuses_every_further_transition
    """
    design = create_released_design(api, design_code="OD-2540-A")
    lot = create_certified_lot(api, lot_code="GL-2540-1")
    work_order = open_work_order(api, design["id"], lot["id"], lot["version"])
    instrument = create_instrument(api, instrument_code="IF-2540-1")
    run = validate_success(
        api.create_process_run(
            build_process_run_payload(work_order["id"], instrument["id"]),
            make_process_technician_headers(),
        ),
        expected_status=201,
    )
    validate_success(
        api.cancel_work_order(
            work_order["id"],
            build_cancel_work_order_payload(cancel_reason=CANCEL_REASON),
            make_process_technician_headers(),
        ),
        expected_status=200,
    )

    second_cancel = api.cancel_work_order(
        work_order["id"],
        build_cancel_work_order_payload(cancel_reason=CANCEL_REASON),
        make_process_technician_headers(),
    )
    validate_error(second_cancel, ERR_INVALID_STATE_TRANSITION, expected_status=409)

    scrap = api.scrap_work_order(
        work_order["id"],
        build_scrap_payload(scrap_reason="LATENT_SUBSURFACE_DEFECT"),
        make_quality_manager_headers(QM_PRIMARY),
    )
    validate_error(scrap, ERR_INVALID_STATE_TRANSITION, expected_status=409)

    new_run = api.create_process_run(
        build_process_run_payload(
            work_order["id"],
            instrument["id"],
            metrology_window_start_utc="2026-08-01T14:00:00Z",
            metrology_window_end_utc="2026-08-01T15:00:00Z",
        ),
        make_process_technician_headers(),
    )
    validate_error(new_run, ERR_RUN_STAGE_OUT_OF_ORDER, expected_status=409)

    final_order = _read_order(api, work_order["id"])
    assert final_order["process_status"] == "CANCELLED", (
        f"got {final_order['process_status']}"
    )
    assert final_order["cancel_reason"] == CANCEL_REASON, (
        f"got {final_order['cancel_reason']}"
    )
    assert_null_fields(final_order, "scrap_reason", "hold_reason")

    final_lot = _read_lot(api, lot["id"])
    assert_blank_ledger(
        final_lot, reserved=0, consumed=0, scrapped=0, available=20, total=20
    )
    assert_blank_conservation(final_lot)

    final_instrument = validate_success(
        api.get_metrology_instrument(instrument["id"], make_plant_admin_headers()),
        expected_status=200,
    )
    assert_booked_minutes(final_instrument, 0)

    final_run = validate_success(
        api.get_process_run(run["id"], make_process_technician_headers()),
        expected_status=200,
    )
    assert final_run["run_status"] == "CANCELLED", f"got {final_run['run_status']}"
    assert final_run["cancel_reason"] == CANCEL_REASON_WORK_ORDER_CANCELLED, (
        f"got {final_run['cancel_reason']}"
    )
