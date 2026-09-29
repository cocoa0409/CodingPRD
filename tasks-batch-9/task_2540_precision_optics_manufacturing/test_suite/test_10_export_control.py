"""Export classification arithmetic, the compliance dimension and its cascades."""

from test_helpers import (
    CANONICAL_TWO_ELEMENT_SPECS,
    ECO_CLASSIFIER,
    ECO_DECIDER,
    ECO_REVOKER,
    ERR_EXPORT_CLASSIFICATION_MISSING,
    ERR_EXPORT_LICENSE_NOT_APPROVED,
    assert_blank_conservation,
    assert_blank_ledger,
    assert_row_ids,
    assert_wavefront_rollup,
    build_export_classification_payload,
    build_license_decision_payload,
    build_revocation_payload,
    classify_design,
    create_certified_lot,
    create_design,
    create_released_design,
    make_export_compliance_officer_headers,
    make_procurement_officer_headers,
    make_process_technician_headers,
    open_work_order,
    setup_aligned_assembly,
    setup_coated_work_order,
    validate_error,
    validate_paginated,
    validate_success,
)

REVOCATION_REASON = "END_USE_STATEMENT_FALSIFIED"


def _read_order(api, work_order_id):
    """Read one work order in both of its state dimensions."""
    return validate_success(
        api.get_work_order(work_order_id, make_process_technician_headers()),
        expected_status=200,
    )


def _read_classification(api, classification_id):
    """Read one export classification."""
    return validate_success(
        api.get_export_classification(
            classification_id, make_export_compliance_officer_headers(ECO_CLASSIFIER)
        ),
        expected_status=200,
    )


def _read_assembly(api, assembly_id):
    """Read one assembly with its wavefront roll-up."""
    return validate_success(
        api.get_assembly(assembly_id, make_process_technician_headers()),
        expected_status=200,
    )


def _read_component(api, component_id):
    """Read one kitted assembly component."""
    return validate_success(
        api.get_assembly_component(component_id, make_process_technician_headers()),
        expected_status=200,
    )


def _read_lot(api, glass_lot_id):
    """Read one melt lot and its blank ledger."""
    return validate_success(
        api.get_glass_lot(glass_lot_id, make_procurement_officer_headers()),
        expected_status=200,
    )


def _screen(api, work_order_id):
    """Run the export compliance screen over one work order."""
    return api.compliance_screen_work_order(
        work_order_id, make_export_compliance_officer_headers(ECO_CLASSIFIER)
    )


def _aligned_assembly_under_an_approved_licence(api):
    """An ALIGNED two-element assembly whose licence for DE stands approved."""
    ctx = setup_aligned_assembly(
        api, component_specs=CANONICAL_TWO_ELEMENT_SPECS, element_count=2
    )
    ctx["classification"] = ctx["compliance"]["classification"]
    return ctx


class TestLicenceRevocationCascade:
    """Revocation is the only path on which the assembly hop is observable."""

    def test_hop_one_denies_the_classification_and_records_the_reason(self, api):
        """The approved licence falls to LICENSE_DENIED, reason and all.

        The PRD states that "Hop one sets `classification_status` to `LICENSE_DENIED`
        and records the reason in `decision_note` — the same field that carries free
        text alongside a licence decision."

        Design: Difficulty/transitive_cascade/export_licence_revocation_cascade_blocks_orders_and_export_blocks_assembly
        """
        ctx = _aligned_assembly_under_an_approved_licence(api)
        assert ctx["classification"]["classification_status"] == "LICENSE_REQUIRED", (
            "a controlled optic bound for DE is born LICENSE_REQUIRED, got "
            f"{ctx['classification']['classification_status']}"
        )

        revoked = validate_success(
            api.record_license_revocation(
                ctx["classification"]["id"],
                build_revocation_payload(revocation_reason=REVOCATION_REASON),
                make_export_compliance_officer_headers(ECO_REVOKER),
            ),
            expected_status=200,
        )

        assert revoked["classification_status"] == "LICENSE_DENIED", (
            f"classification_status must be LICENSE_DENIED, got "
            f"{revoked['classification_status']}"
        )
        assert revoked["decision_note"] == REVOCATION_REASON, (
            f"decision_note must carry the revocation reason, got "
            f"{revoked['decision_note']}"
        )
        assert revoked["license_number"] == "BIS-2540-001", (
            "the withdrawn licence number is not erased, got "
            f"{revoked['license_number']}"
        )
        assert revoked["eccn"] == "6A004.A.1", (
            f"eccn must stay 6A004.A.1, got {revoked['eccn']}"
        )

    def test_hop_two_blocks_the_order_without_touching_its_fabrication_state(self, api):
        """The order's compliance dimension falls to BLOCKED and stays there.

        The PRD states that "Hop two takes every work order of that design whose
        `compliance_status` is `UNCLASSIFIED`, `SCREENED` or `CLEARED`, in `created_at`
        ascending order, and sets `compliance_status` to `BLOCKED` — a terminal state in
        the compliance dimension, from which there is no return."

        Design: Difficulty/transitive_cascade/export_licence_revocation_cascade_blocks_orders_and_export_blocks_assembly
        """
        ctx = _aligned_assembly_under_an_approved_licence(api)
        before = _read_order(api, ctx["work_order"]["id"])
        assert before["compliance_status"] == "CLEARED", (
            f"the order must stand CLEARED, got {before['compliance_status']}"
        )

        api.record_license_revocation(
            ctx["classification"]["id"],
            build_revocation_payload(revocation_reason=REVOCATION_REASON),
            make_export_compliance_officer_headers(ECO_REVOKER),
        )

        after = _read_order(api, ctx["work_order"]["id"])
        assert after["compliance_status"] == "BLOCKED", (
            f"compliance_status must be BLOCKED, got {after['compliance_status']}"
        )
        assert after["process_status"] == "RELEASED_TO_ASSEMBLY", (
            "the fabrication dimension is untouched by a compliance cascade, got "
            f"{after['process_status']}"
        )

    def test_hop_three_export_blocks_the_aligned_assembly_and_keeps_its_roll_up(
        self, api
    ):
        """The barrel is blocked on paper; nothing is re-measured or voided.

        The PRD states that "Hop three, caused by hop two, reaches the assembly floor:
        for each work order just blocked, every assembly that owns an active component
        drawn from that order, in `created_at` ascending order, has its
        `assembly_status` set to `EXPORT_BLOCKED` **if and only if** that assembly was
        in `ALIGNED` or `SEALED`."

        Design: Difficulty/transitive_cascade/export_licence_revocation_cascade_blocks_orders_and_export_blocks_assembly
        """
        ctx = _aligned_assembly_under_an_approved_licence(api)
        assert ctx["aligned"]["assembly_status"] == "ALIGNED", (
            f"the assembly must stand ALIGNED, got {ctx['aligned']['assembly_status']}"
        )

        api.record_license_revocation(
            ctx["classification"]["id"],
            build_revocation_payload(revocation_reason=REVOCATION_REASON),
            make_export_compliance_officer_headers(ECO_REVOKER),
        )

        assembly = _read_assembly(api, ctx["assembly"]["id"])
        assert assembly["assembly_status"] == "EXPORT_BLOCKED", (
            f"assembly_status must be EXPORT_BLOCKED, got {assembly['assembly_status']}"
        )
        for component in ctx["components"]:
            assert _read_component(api, component["id"])["component_status"] == "ACTIVE", (
                "an export block voids no component"
            )
        assert_wavefront_rollup(assembly, 0.0781, 0.0208, 0.0989, 0.0060, 0.1049)


def test_export_classification_computes_the_inclusive_aperture_and_rms_boundary(api):
    """A design exactly on both control thresholds is controlled but licence-exempt.

    The PRD states that "The optic is treated as controlled when **either** its
    `aperture_mm` is at least 100.0 millimetres and its `required_rms_wavefront_waves`
    is no greater than 0.0500 waves, **or** its `figure_of_merit` is at least 4000.00."
    and that "`license_required` is true only when the optic is controlled **and** the
    destination is not one of the three licence-exempt destinations `CA`, `AU` and `GB`;
    a controlled optic bound for Canada, Australia or the United Kingdom requires no
    licence, and an uncontrolled optic requires none regardless of destination."

    Design: Corner/entities/export_classification_computes_the_inclusive_aperture_and_rms_boundary
    """
    design = create_design(
        api,
        design_code="OD-2540-BOUND",
        aperture_mm=100.0,
        required_rms_wavefront_waves=0.0500,
    )

    classification = validate_success(
        api.create_export_classification(
            build_export_classification_payload(
                design["id"], destination_country="CA"
            ),
            make_export_compliance_officer_headers(ECO_CLASSIFIER),
        ),
        expected_status=201,
    )

    assert classification["figure_of_merit"] == 2000.00, (
        "figure_of_merit must be 100.0 / 0.0500 == 2000.00, got "
        f"{classification['figure_of_merit']}"
    )
    assert classification["eccn"] == "6A004.A.1", (
        "the AND branch controls this design on its own, got "
        f"{classification['eccn']}"
    )
    assert classification["license_required"] is False, (
        f"CA is licence-exempt, got license_required {classification['license_required']}"
    )
    assert classification["classification_status"] == "EXEMPT_CLEARED", (
        "classification_status must be EXEMPT_CLEARED, got "
        f"{classification['classification_status']}"
    )
    assert classification["license_number"] is None
    assert classification["decided_by_user_id"] is None
    assert classification["decision_note"] is None
    assert classification["end_use_statement"] is None
    assert classification["version"] == 1, (
        f"version must start at 1, got {classification['version']}"
    )
    assert classification["design_id"] == design["id"]
    assert classification["destination_country"] == "CA"
    assert _read_classification(api, classification["id"]) == classification, (
        "the read must return the identical row"
    )


def test_export_control_or_branch_fires_at_a_figure_of_merit_of_exactly_four_thousand(
    api,
):
    """An 80 mm optic at 4000.00 is controlled; its 79 mm neighbour is not.

    The PRD states that "`figure_of_merit` is the design's `aperture_mm` divided by its
    `required_rms_wavefront_waves`, rounded half up to two decimal places — a large
    aperture held to a tight wavefront is what makes an optic militarily interesting."
    and that "Every one of those thresholds is inclusive: an aperture of exactly 100.0
    millimetres at exactly 0.0500 waves is controlled, and a figure of merit of exactly
    4000.00 is controlled even on an 80-millimetre aperture."

    Design: Corner/calculations/export_control_or_branch_fires_at_a_figure_of_merit_of_exactly_four_thousand
    """
    at_the_threshold = create_design(
        api,
        design_code="OD-2540-FOM",
        aperture_mm=80.0,
        required_rms_wavefront_waves=0.0200,
    )
    below_it = create_design(
        api,
        design_code="OD-2540-SUB",
        aperture_mm=79.0,
        required_rms_wavefront_waves=0.0200,
    )

    controlled = classify_design(api, at_the_threshold["id"], destination_country="DE")
    uncontrolled = classify_design(api, below_it["id"], destination_country="DE")

    assert controlled["figure_of_merit"] == 4000.00, (
        f"figure_of_merit must be 4000.00, got {controlled['figure_of_merit']}"
    )
    assert controlled["eccn"] == "6A004.A.1", (
        f"eccn must be 6A004.A.1, got {controlled['eccn']}"
    )
    assert controlled["license_required"] is True, (
        "a controlled optic bound for DE needs a licence, got "
        f"{controlled['license_required']}"
    )
    assert controlled["classification_status"] == "LICENSE_REQUIRED", (
        "classification_status must be LICENSE_REQUIRED, got "
        f"{controlled['classification_status']}"
    )
    assert uncontrolled["figure_of_merit"] == 3950.00, (
        f"figure_of_merit must be 3950.00, got {uncontrolled['figure_of_merit']}"
    )
    assert uncontrolled["eccn"] == "EAR99", (
        f"eccn must be EAR99 for an uncontrolled optic, got {uncontrolled['eccn']}"
    )
    assert uncontrolled["license_required"] is False
    assert uncontrolled["classification_status"] == "EXEMPT_CLEARED", (
        "classification_status must be EXEMPT_CLEARED, got "
        f"{uncontrolled['classification_status']}"
    )


def test_the_compliance_screen_needs_a_classification_and_clears_an_exempt_one_directly(
    api,
):
    """The screen is blocked without a classification and skips SCREENED with one.

    The PRD states that "The work order's design must have a governing classification,
    otherwise the screen cannot conclude and `ERR_EXPORT_CLASSIFICATION_MISSING` is
    returned." and that "Where the governing classification is already `EXEMPT_CLEARED`
    or `LICENSE_APPROVED`, the screen takes the order straight to `CLEARED` in a single
    call."

    Design: Corner/validations/the_compliance_screen_needs_a_classification_and_clears_an_exempt_one_directly
    """
    design = create_released_design(api, design_code="OD-2540-A")
    lot = create_certified_lot(api, lot_code="GL-2540-1")
    order = open_work_order(api, design["id"], lot["id"], lot["version"])
    assert order["compliance_status"] == "UNCLASSIFIED", (
        f"a new order is UNCLASSIFIED, got {order['compliance_status']}"
    )

    unclassifiable = _screen(api, order["id"])

    validate_error(unclassifiable, ERR_EXPORT_CLASSIFICATION_MISSING)
    assert _read_order(api, order["id"])["compliance_status"] == "UNCLASSIFIED", (
        "the refused screen leaves the compliance dimension alone"
    )

    classification = classify_design(api, design["id"], destination_country="CA")

    assert classification["eccn"] == "6A004.A.1"
    assert classification["figure_of_merit"] == 3000.00, (
        f"figure_of_merit must be 3000.00, got {classification['figure_of_merit']}"
    )
    assert classification["license_required"] is False
    assert classification["classification_status"] == "EXEMPT_CLEARED"

    screened = validate_success(_screen(api, order["id"]), expected_status=200)

    assert screened["compliance_status"] == "CLEARED", (
        "an exempt classification clears the order in one call, got "
        f"{screened['compliance_status']}"
    )
    assert screened["process_status"] == "BLANKS_RESERVED", (
        "the screen touched only the compliance dimension, got "
        f"{screened['process_status']}"
    )
    settled = _read_classification(api, classification["id"])
    assert settled["license_number"] is None
    assert settled["decided_by_user_id"] is None


def test_a_denied_licence_blocks_every_order_of_that_design_and_leaves_the_others_alone(
    api,
):
    """One denial fans out over the design's whole backlog and stops there.

    The PRD states that "Hop two takes every work order of that design whose
    `compliance_status` is `UNCLASSIFIED`, `SCREENED` or `CLEARED`, in `created_at`
    ascending order, and sets `compliance_status` to `BLOCKED` — a terminal state in the
    compliance dimension, from which there is no return." and that "When every row for a
    design has been denied, the design has no governing classification at all, and any
    gate that requires one raises `ERR_EXPORT_CLASSIFICATION_MISSING`."

    Design: Corner/complexity_layers/a_denied_licence_blocks_every_order_of_that_design_and_leaves_the_others_alone
    """
    controlled_design = create_released_design(
        api, design_code="OD-2540-A", aperture_mm=120.0, required_rms_wavefront_waves=0.0400
    )
    exempt_design = create_released_design(
        api, design_code="OD-2540-B", aperture_mm=110.0, required_rms_wavefront_waves=0.0450
    )
    lot = create_certified_lot(api, lot_code="GL-2540-1", total_blank_count=20)

    def _open(design_id, wo_code):
        return open_work_order(
            api, design_id, lot["id"], _read_lot(api, lot["id"])["version"], wo_code=wo_code
        )

    first = _open(controlled_design["id"], "WO-2540-A1")
    second = _open(controlled_design["id"], "WO-2540-A2")
    third = _open(exempt_design["id"], "WO-2540-B1")
    denied_row = classify_design(
        api, controlled_design["id"], destination_country="DE"
    )
    classify_design(api, exempt_design["id"], destination_country="AU")
    assert validate_success(_screen(api, first["id"]), expected_status=200)[
        "compliance_status"
    ] == "SCREENED", "a licence-required design leaves the order SCREENED"
    assert validate_success(_screen(api, third["id"]), expected_status=200)[
        "compliance_status"
    ] == "CLEARED", "an exempt design clears its order at once"

    denial = validate_success(
        api.record_license_decision(
            denied_row["id"],
            build_license_decision_payload("DENIED"),
            make_export_compliance_officer_headers(ECO_DECIDER),
        ),
        expected_status=200,
    )

    assert denial["classification_status"] == "LICENSE_DENIED", (
        f"classification_status must be LICENSE_DENIED, got "
        f"{denial['classification_status']}"
    )
    assert denial["license_number"] is None, (
        f"a denial records no licence number, got {denial['license_number']}"
    )
    assert denial["decided_by_user_id"] == ECO_DECIDER, (
        f"decided_by_user_id must be the acting officer, got {denial['decided_by_user_id']}"
    )
    assert _read_order(api, first["id"])["compliance_status"] == "BLOCKED", (
        "the screened order is blocked"
    )
    assert _read_order(api, second["id"])["compliance_status"] == "BLOCKED", (
        "the never-screened order is blocked too"
    )
    assert _read_order(api, third["id"])["compliance_status"] == "CLEARED", (
        "the cascade is scoped by design_id"
    )
    for order in (first, second, third):
        assert _read_order(api, order["id"])["process_status"] == "BLANKS_RESERVED", (
            "the cascade stayed inside the compliance dimension"
        )

    fresh = _open(controlled_design["id"], "WO-2540-A3")

    assert fresh["compliance_status"] == "UNCLASSIFIED", (
        "the create endpoint declares no export gate, got "
        f"{fresh['compliance_status']}"
    )
    ungoverned = _screen(api, fresh["id"])
    validate_error(ungoverned, ERR_EXPORT_CLASSIFICATION_MISSING)

    replacement = validate_success(
        api.create_export_classification(
            build_export_classification_payload(
                controlled_design["id"], destination_country="GB"
            ),
            make_export_compliance_officer_headers(ECO_CLASSIFIER),
        ),
        expected_status=201,
    )

    assert replacement["classification_status"] == "EXEMPT_CLEARED", (
        "the uniqueness rule counts only rows that are not LICENSE_DENIED, got "
        f"{replacement['classification_status']}"
    )
    rescreened = validate_success(_screen(api, fresh["id"]), expected_status=200)
    assert rescreened["compliance_status"] == "CLEARED", (
        f"the fresh order clears straight past SCREENED, got "
        f"{rescreened['compliance_status']}"
    )

    rows, meta = validate_paginated(
        api.list_design_export_classifications(
            controlled_design["id"],
            make_export_compliance_officer_headers(ECO_CLASSIFIER),
        )
    )
    assert_row_ids(
        rows,
        [denied_row["id"], replacement["id"]],
        "the design's classification listing",
    )
    assert meta["total_count"] == 2
    blocked, blocked_meta = validate_paginated(
        api.list_work_orders(
            make_export_compliance_officer_headers(ECO_CLASSIFIER),
            params={"compliance_status": "BLOCKED"},
        )
    )
    assert_row_ids(
        blocked, [first["id"], second["id"]], "the BLOCKED work-order listing"
    )
    assert blocked_meta["total_count"] == 2, (
        "the new classification does not un-block the two blocked orders, got "
        f"{blocked_meta['total_count']}"
    )


def test_release_to_assembly_waits_for_the_licence_and_then_moves_the_blank_ledger(api):
    """The identical call is refused, then admitted, purely on the compliance gate.

    The PRD states that both dimensions must be in position: "the order's
    `process_status` must be exactly `COATED`, otherwise `ERR_WORK_ORDER_NOT_IN_PROCESS`,
    and its `compliance_status` must be exactly `CLEARED`, otherwise
    `ERR_EXPORT_LICENSE_NOT_APPROVED`." On success "the lot's `reserved_blank_count`
    falls by the order's frozen `reserved_blank_count`, its `consumed_blank_count` rises
    by the order's `element_count`, and `available_blank_count` is recomputed — which is
    precisely how the spare blanks that were reserved but never cut find their way back
    into availability."

    Design: Corner/endpoints/release_to_assembly_waits_for_the_licence_and_then_moves_the_blank_ledger
    """
    ctx = setup_coated_work_order(api, element_count=2)
    order_id = ctx["work_order"]["id"]
    classification = classify_design(api, ctx["design"]["id"], destination_country="DE")
    assert classification["classification_status"] == "LICENSE_REQUIRED"
    screened = validate_success(_screen(api, order_id), expected_status=200)
    assert screened["compliance_status"] == "SCREENED"
    assert_blank_ledger(
        _read_lot(api, ctx["lot"]["id"]),
        reserved=3,
        consumed=0,
        scrapped=0,
        available=17,
        total=20,
    )

    premature = api.release_work_order_to_assembly(
        order_id, make_process_technician_headers()
    )

    validate_error(premature, ERR_EXPORT_LICENSE_NOT_APPROVED)
    refused = _read_order(api, order_id)
    assert refused["process_status"] == "COATED", (
        f"process_status must still be COATED, got {refused['process_status']}"
    )
    assert refused["compliance_status"] == "SCREENED", (
        f"compliance_status must still be SCREENED, got {refused['compliance_status']}"
    )
    assert_blank_ledger(
        _read_lot(api, ctx["lot"]["id"]),
        reserved=3,
        consumed=0,
        scrapped=0,
        available=17,
        total=20,
    )

    approved = validate_success(
        api.record_license_decision(
            classification["id"],
            build_license_decision_payload("APPROVED"),
            make_export_compliance_officer_headers(ECO_DECIDER),
        ),
        expected_status=200,
    )

    assert approved["classification_status"] == "LICENSE_APPROVED"
    assert approved["license_number"] == "BIS-2540-001"
    assert approved["decided_by_user_id"] == ECO_DECIDER
    swept = _read_order(api, order_id)
    assert swept["compliance_status"] == "CLEARED", (
        "the approval sweeps the design's SCREENED backlog to CLEARED, got "
        f"{swept['compliance_status']}"
    )
    assert swept["process_status"] == "COATED", (
        "the sweep touched only the compliance dimension, got "
        f"{swept['process_status']}"
    )

    released = validate_success(
        api.release_work_order_to_assembly(
            order_id, make_process_technician_headers()
        ),
        expected_status=200,
    )

    assert released["process_status"] == "RELEASED_TO_ASSEMBLY", (
        f"process_status must be RELEASED_TO_ASSEMBLY, got {released['process_status']}"
    )
    lot = _read_lot(api, ctx["lot"]["id"])
    assert_blank_ledger(lot, reserved=0, consumed=2, scrapped=0, available=18, total=20)
    assert_blank_conservation(lot)
