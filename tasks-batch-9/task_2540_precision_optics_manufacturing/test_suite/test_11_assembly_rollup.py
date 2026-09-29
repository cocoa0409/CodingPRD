"""The transmitted-wavefront roll-up, the slot table and the post-release scrap."""

from test_helpers import (
    ALL_ZERO_UUID,
    CANONICAL_TWO_ELEMENT_SPECS,
    CEMENT_DERATE_HIGH_WAVES,
    CEMENT_DERATE_MID_WAVES,
    ECO_CLASSIFIER,
    ECO_DECIDER,
    ERR_ASSEMBLY_NOT_FOUND,
    ERR_ELEMENT_ALLOCATION_EXCEEDED,
    ERR_INVALID_STATE_TRANSITION,
    ERR_SLOT_ALREADY_OCCUPIED,
    ERR_STALE_ASSEMBLY_VERSION,
    ERR_WORK_ORDER_NOT_FOUND,
    MAX_ALIGNMENT_ATTEMPTS,
    QM_PRIMARY,
    QM_THIRD,
    SCRAP_REASON_LATENT_SUBSURFACE_DEFECT,
    assert_blank_conservation,
    assert_blank_ledger,
    assert_created_at_ascending,
    assert_row_ids,
    assert_wavefront_rollup,
    assert_wavefront_rollup_null,
    assert_wavefront_value,
    build_assembly_component_payload,
    build_cement_payload,
    build_license_decision_payload,
    build_mount_payload,
    build_scrap_payload,
    classify_design,
    create_assembly,
    create_released_design,
    expected_cement_derate,
    kit_components,
    make_export_compliance_officer_headers,
    make_optics_engineer_headers,
    make_process_technician_headers,
    make_procurement_officer_headers,
    make_quality_manager_headers,
    setup_aligned_assembly,
    setup_coated_work_order,
    setup_kitted_assembly,
    setup_mounted_assembly,
    setup_released_to_assembly_work_order,
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
    """Read one assembly with its wavefront roll-up as the ProcessTechnician."""
    return validate_success(
        api.get_assembly(assembly_id, make_process_technician_headers()),
        expected_status=200,
    )


def _read_component(api, component_id, headers=None):
    """Read one assembly component through its own single-read endpoint."""
    return validate_success(
        api.get_assembly_component(
            component_id, headers or make_process_technician_headers()
        ),
        expected_status=200,
    )


def _read_order(api, work_order_id):
    """Read one work order in both of its state dimensions."""
    return validate_success(
        api.get_work_order(work_order_id, make_process_technician_headers()),
        expected_status=200,
    )


def _read_lot(api, glass_lot_id):
    """Read one melt lot and its blank-conservation ledger."""
    return validate_success(
        api.get_glass_lot(glass_lot_id, make_procurement_officer_headers()),
        expected_status=200,
    )


def _assembly_components(api, assembly_id, params=None, headers=None):
    """List the components of an assembly, returning rows and pagination meta."""
    return validate_paginated(
        api.list_assembly_components(
            assembly_id, headers or make_process_technician_headers(), params=params
        )
    )


def _order_components(api, work_order_id, params=None, headers=None):
    """List the components drawn from a work order, rows and pagination meta."""
    return validate_paginated(
        api.list_work_order_components(
            work_order_id, headers or make_process_technician_headers(), params=params
        )
    )


def _align(api, assembly_id):
    """Run one alignment pass and return the raw response."""
    return api.align_assembly(assembly_id, make_process_technician_headers())


class TestCementDerateTierComesFromTheSubtotal:
    """The derate tier is chosen once, from the subtotal, and never revisited."""

    def test_the_four_pinned_steps_land_the_total_just_inside_the_budget(self, api):
        """A 0.0989 subtotal takes the middle tier and clears the 0.1050 budget.

        The PRD states that "a `subtotal_waves` from 0.0500 up to but not including
        0.1000 takes 0.0060" and that "The assembly is within specification when that
        total is less than or equal to the design's
        `transmitted_wavefront_budget_waves`, the comparison being inclusive."

        Design: Difficulty/combinatorial_formula/cement_derate_tier_selected_from_subtotal_not_recomputed_on_total
        """
        ctx = setup_mounted_assembly(api, component_specs=CANONICAL_TWO_ELEMENT_SPECS)
        assert_wavefront_value(
            ctx["design"]["transmitted_wavefront_budget_waves"],
            0.1050,
            "transmitted_wavefront_budget_waves",
        )
        assert_wavefront_rollup_null(ctx["mounted"])

        aligned = validate_success(
            _align(api, ctx["assembly"]["id"]), expected_status=200
        )

        assert_wavefront_rollup(aligned, 0.0781, 0.0208, 0.0989, 0.0060, 0.1049)
        assert aligned["assembly_status"] == "ALIGNED", (
            f"a total of 0.1049 clears the 0.1050 budget, got {aligned['assembly_status']}"
        )
        assert aligned["alignment_attempt_count"] == 0, (
            "a pass that succeeded first time consumes no attempt, got "
            f"{aligned['alignment_attempt_count']}"
        )

    def test_re_selecting_the_tier_from_the_total_would_have_rejected_the_build(
        self, api
    ):
        """The tier-3 derate the final total sits in is never applied.

        The PRD states that "the tier is selected from `subtotal_waves` — the value
        before the derate is added — never from the final total, and the calculation
        is single-pass with no iteration to a fixed point" and that "a
        `subtotal_waves` of 0.1000 or more takes 0.0150".

        Design: Difficulty/combinatorial_formula/cement_derate_tier_selected_from_subtotal_not_recomputed_on_total
        """
        ctx = setup_mounted_assembly(api, component_specs=CANONICAL_TWO_ELEMENT_SPECS)

        aligned = validate_success(
            _align(api, ctx["assembly"]["id"]), expected_status=200
        )

        assert expected_cement_derate(0.0989) == CEMENT_DERATE_MID_WAVES, (
            "the subtotal 0.0989 sits in the middle tier, got "
            f"{expected_cement_derate(0.0989)}"
        )
        assert expected_cement_derate(0.1049) == CEMENT_DERATE_HIGH_WAVES, (
            "the total 0.1049 would have sat in the top tier, got "
            f"{expected_cement_derate(0.1049)}"
        )
        assert_wavefront_value(
            aligned["cement_derate_waves"], CEMENT_DERATE_MID_WAVES, "cement_derate_waves"
        )
        assert aligned["cement_derate_waves"] != CEMENT_DERATE_HIGH_WAVES, (
            "the tier may not be re-selected from the total, got "
            f"{aligned['cement_derate_waves']}"
        )
        assert aligned["total_transmitted_wavefront_waves"] != 0.1139, (
            "a re-selected tier would have produced 0.1139, got "
            f"{aligned['total_transmitted_wavefront_waves']}"
        )
        assert aligned["assembly_status"] != "MOUNTED", (
            "a re-selected tier would have failed the alignment, got "
            f"{aligned['assembly_status']}"
        )
        stored = _read_assembly(api, ctx["assembly"]["id"])
        assert_wavefront_rollup(stored, 0.0781, 0.0208, 0.0989, 0.0060, 0.1049)
        assert stored["assembly_status"] == "ALIGNED"


class TestPostReleaseScrapVoidsAndDemotes:
    """Withdrawing an element after release walks all four hops for real."""

    def _aligned_build(self, api):
        """An ALIGNED assembly whose two elements come from one released order."""
        ctx = setup_aligned_assembly(api, component_specs=CANONICAL_TWO_ELEMENT_SPECS)
        assert_wavefront_rollup(ctx["aligned"], 0.0781, 0.0208, 0.0989, 0.0060, 0.1049)
        assert ctx["aligned"]["assembly_status"] == "ALIGNED"
        return ctx

    def _scrap(self, api, work_order_id):
        """Scrap the order behind the build as the QualityManager on duty."""
        return validate_success(
            api.scrap_work_order(
                work_order_id,
                build_scrap_payload(
                    scrap_reason=SCRAP_REASON_LATENT_SUBSURFACE_DEFECT
                ),
                make_quality_manager_headers(QM_PRIMARY),
            ),
            expected_status=200,
        )

    def test_hop_two_writes_the_consumed_blanks_off_without_breaking_conservation(
        self, api
    ):
        """The two consumed blanks move straight into the scrapped counter.

        The PRD states that "If the order had reached `RELEASED_TO_ASSEMBLY`, its
        blanks were already consumed, so `consumed_blank_count` is decremented by
        `element_count` and `scrapped_blank_count` is incremented by `element_count`."

        Design: Difficulty/transitive_cascade/post_release_scrap_cascade_voids_component_and_demotes_aligned_assembly
        """
        ctx = self._aligned_build(api)
        before = _read_lot(api, ctx["lot"]["id"])
        assert_blank_ledger(
            before, reserved=0, consumed=2, scrapped=0, available=18, total=20
        )

        scrapped = self._scrap(api, ctx["work_order"]["id"])

        assert scrapped["process_status"] == "SCRAPPED", (
            f"process_status must be SCRAPPED, got {scrapped['process_status']}"
        )
        assert scrapped["scrap_reason"] == SCRAP_REASON_LATENT_SUBSURFACE_DEFECT, (
            f"scrap_reason must be the supplied one, got {scrapped['scrap_reason']}"
        )
        after = _read_lot(api, ctx["lot"]["id"])
        assert_blank_ledger(
            after, reserved=0, consumed=0, scrapped=2, available=18, total=20
        )
        assert_blank_conservation(after)
        assert after["lot_status"] == "RELEASED", (
            "eighteen blanks are still available, so the lot is not depleted, got "
            f"{after['lot_status']}"
        )

    def test_hop_three_voids_every_active_component_drawn_from_the_order(self, api):
        """Both elements of the barrel are withdrawn in one sweep.

        The PRD states that "Hop three sets `component_status` to `VOIDED` on every
        active component drawn from the scrapped order, in `created_at` ascending
        order."

        Design: Difficulty/transitive_cascade/post_release_scrap_cascade_voids_component_and_demotes_aligned_assembly
        """
        ctx = self._aligned_build(api)
        first, second = ctx["components"]

        self._scrap(api, ctx["work_order"]["id"])

        for component in (first, second):
            voided = _read_component(api, component["id"])
            assert voided["component_status"] == "VOIDED", (
                f"component in slot {voided['slot_index']} must be VOIDED, got "
                f"{voided['component_status']}"
            )
        rows, meta = _assembly_components(api, ctx["assembly"]["id"])
        assert_row_ids(rows, [first["id"], second["id"]], "the component listing")
        assert meta["total_count"] == 2, (
            f"voiding a component does not delete it, got {meta['total_count']}"
        )
        active, active_meta = _assembly_components(
            api, ctx["assembly"]["id"], params={"component_status": "ACTIVE"}
        )
        assert active == [], f"no active component may remain, got {active}"
        assert active_meta["total_count"] == 0

    def test_hop_four_nulls_the_roll_up_and_demotes_the_assembly_to_mounted(self, api):
        """An empty active set leaves five nulls and sends the build back to MOUNTED.

        The PRD states that "the five roll-up outputs are recomputed over the
        components that remain `ACTIVE` — and if no active component remains, all five
        are set to null — and if that assembly's `assembly_status` was `ALIGNED` or
        `SEALED` it is demoted `ALIGNED → MOUNTED` or `SEALED → MOUNTED`" and that
        "`alignment_attempt_count` is deliberately **left unchanged** by a demotion: an
        element withdrawn by quality is not counted against the technician's three
        alignment attempts."

        Design: Difficulty/transitive_cascade/post_release_scrap_cascade_voids_component_and_demotes_aligned_assembly
        """
        ctx = self._aligned_build(api)

        self._scrap(api, ctx["work_order"]["id"])

        demoted = _read_assembly(api, ctx["assembly"]["id"])
        assert demoted["assembly_status"] == "MOUNTED", (
            f"the assembly must fall back to MOUNTED, got {demoted['assembly_status']}"
        )
        assert_wavefront_rollup_null(demoted)
        assert demoted["alignment_attempt_count"] == 0, (
            "a demotion may not consume an alignment attempt, got "
            f"{demoted['alignment_attempt_count']}"
        )
        assert demoted["version"] > ctx["aligned"]["version"], (
            "the demoted assembly is a row the cascade mutated, so its version rises, "
            f"got {demoted['version']} after {ctx['aligned']['version']}"
        )


def test_alignment_self_loops_twice_and_rejects_the_build_on_the_third_attempt(api):
    """Two 200s in MOUNTED, then the terminal REJECTED, then a 409.

    The PRD states that "if the incremented count is still below three the assembly
    stays in `MOUNTED` — a self-loop that returns 200 with the freshly computed
    outputs, inviting the technician to reshim and try again — and if the incremented
    count has reached three the assembly moves `MOUNTED → REJECTED`, a terminal
    state." and that "A `ProcessTechnician` runs an alignment pass on an assembly in
    `MOUNTED`; from any other state, `ERR_INVALID_STATE_TRANSITION`."

    Design: Corner/state_machines/alignment_self_loop_exhausts_max_attempts_and_rejects_the_assembly
    """
    ctx = setup_mounted_assembly(
        api,
        component_specs=SINGLE_ELEMENT_SPECS,
        design_overrides={"transmitted_wavefront_budget_waves": 0.0500},
    )

    first = validate_success(_align(api, ctx["assembly"]["id"]), expected_status=200)

    assert first["assembly_status"] == "MOUNTED", (
        f"a failed first pass self-loops in MOUNTED, got {first['assembly_status']}"
    )
    assert_wavefront_rollup(first, 0.0600, 0.0144, 0.0744, 0.0060, 0.0804)
    assert first["alignment_attempt_count"] == 1, (
        f"alignment_attempt_count must be 1, got {first['alignment_attempt_count']}"
    )
    stored = _read_assembly(api, ctx["assembly"]["id"])
    assert_wavefront_rollup(stored, 0.0600, 0.0144, 0.0744, 0.0060, 0.0804)
    assert stored["alignment_attempt_count"] == 1

    second = validate_success(_align(api, ctx["assembly"]["id"]), expected_status=200)

    assert second["alignment_attempt_count"] == 2, (
        f"alignment_attempt_count must be 2, got {second['alignment_attempt_count']}"
    )
    assert second["assembly_status"] == "MOUNTED", (
        f"the second self-loop stays in MOUNTED, got {second['assembly_status']}"
    )

    third = validate_success(_align(api, ctx["assembly"]["id"]), expected_status=200)

    assert third["alignment_attempt_count"] == MAX_ALIGNMENT_ATTEMPTS, (
        f"the third attempt reaches {MAX_ALIGNMENT_ATTEMPTS}, got "
        f"{third['alignment_attempt_count']}"
    )
    assert third["assembly_status"] == "REJECTED", (
        f"three failed passes end the build, got {third['assembly_status']}"
    )
    assert_wavefront_rollup(third, 0.0600, 0.0144, 0.0744, 0.0060, 0.0804)

    fourth = _align(api, ctx["assembly"]["id"])

    validate_error(fourth, ERR_INVALID_STATE_TRANSITION)
    final = _read_assembly(api, ctx["assembly"]["id"])
    assert final["assembly_status"] == "REJECTED", (
        f"REJECTED is terminal, got {final['assembly_status']}"
    )
    assert final["alignment_attempt_count"] == MAX_ALIGNMENT_ATTEMPTS, (
        "a refused fourth pass may not touch the counter, got "
        f"{final['alignment_attempt_count']}"
    )
    assert_wavefront_rollup(final, 0.0600, 0.0144, 0.0744, 0.0060, 0.0804)


def test_the_kitting_body_resolves_its_two_foreign_keys_left_to_right(api):
    """The unstored assembly is reported before the unstored work order.

    The PRD states that adjudication checks "Every foreign-key id in the request body
    resolves, in the order the endpoint lists its input fields — the referenced
    entity's not-found code, 404." and that for kitting "The submission names
    `assembly_id` and `work_order_id`".

    Design: Corner/entities/assembly_component_body_foreign_keys_are_validated_left_to_right_returns_not_found
    """
    design = create_released_design(api, design_code="OD-2540-FK")
    assembly = create_assembly(api, design["id"], assembly_code="AS-2540-1")
    assert assembly["assembly_status"] == "KITTED", (
        f"a new assembly is born KITTED, got {assembly['assembly_status']}"
    )
    assert assembly["version"] == 1, (
        f"a new assembly carries version 1, got {assembly['version']}"
    )

    both_unstored = api.create_assembly_component(
        build_assembly_component_payload(ALL_ZERO_UUID, ALL_ZERO_UUID, 1),
        make_process_technician_headers(),
    )
    order_unstored = api.create_assembly_component(
        build_assembly_component_payload(assembly["id"], ALL_ZERO_UUID, 1),
        make_process_technician_headers(),
    )

    validate_error(both_unstored, ERR_ASSEMBLY_NOT_FOUND)
    validate_error(order_unstored, ERR_WORK_ORDER_NOT_FOUND)
    rows, meta = _assembly_components(api, assembly["id"])
    assert rows == [], f"neither refusal may create a link, got {rows}"
    assert meta["total_count"] == 0, (
        f"total_count must be 0, got {meta['total_count']}"
    )
    unchanged = _read_assembly(api, assembly["id"])
    assert unchanged["version"] == 1, (
        f"a refused kitting may not bump the assembly, got {unchanged['version']}"
    )
    assert unchanged["assembly_status"] == "KITTED"
    assert_wavefront_rollup_null(unchanged)


def test_the_second_element_must_carry_the_version_the_first_one_produced(api):
    """A replayed assembly version is refused even though its slot is free.

    The PRD states that "Adding a second element to the same assembly is legitimate,
    so this check is the only thing preventing a writer from populating a slot table it
    has not re-read." and that an assembly is created with "all five
    transmitted-wavefront outputs — `element_rss_waves`, `centration_error_waves`,
    `subtotal_waves`, `cement_derate_waves` and `total_transmitted_wavefront_waves` —
    null until the first alignment pass".

    Design: Corner/complexity_layers/the_second_element_of_an_assembly_must_carry_the_version_the_first_one_produced
    """
    ctx = setup_released_to_assembly_work_order(api)
    assembly = create_assembly(api, ctx["design"]["id"], assembly_code="AS-2540-1")
    captured_version = assembly["version"]

    first = validate_success(
        api.create_assembly_component(
            build_assembly_component_payload(
                assembly["id"],
                ctx["work_order"]["id"],
                captured_version,
                slot_index=1,
                element_wavefront_rms_waves=0.0600,
            ),
            make_process_technician_headers(),
        ),
        expected_status=201,
    )
    after_first = _read_assembly(api, assembly["id"])
    assert after_first["version"] == captured_version + 1, (
        f"kitting increments the assembly version, got {after_first['version']}"
    )

    stale = api.create_assembly_component(
        build_assembly_component_payload(
            assembly["id"],
            ctx["work_order"]["id"],
            captured_version,
            slot_index=2,
            element_wavefront_rms_waves=0.0400,
        ),
        make_process_technician_headers(),
    )

    validate_error(stale, ERR_STALE_ASSEMBLY_VERSION)
    rows, meta = _assembly_components(api, assembly["id"])
    assert_row_ids(rows, [first["id"]], "the component listing after the refusal")
    assert meta["total_count"] == 1, (
        f"the refused add may not create a row, got {meta['total_count']}"
    )
    unchanged = _read_assembly(api, assembly["id"])
    assert unchanged["version"] == captured_version + 1, (
        f"the refusal may not bump the version again, got {unchanged['version']}"
    )
    assert_wavefront_rollup_null(unchanged)

    second = validate_success(
        api.create_assembly_component(
            build_assembly_component_payload(
                assembly["id"],
                ctx["work_order"]["id"],
                unchanged["version"],
                slot_index=2,
                element_wavefront_rms_waves=0.0400,
            ),
            make_process_technician_headers(),
        ),
        expected_status=201,
    )

    assert second["slot_index"] == 2, (
        f"the re-read admits the identical body, got slot {second['slot_index']}"
    )
    validate_success(
        api.cement_assembly(
            assembly["id"], build_cement_payload(), make_process_technician_headers()
        ),
        expected_status=200,
    )
    validate_success(
        api.mount_assembly(
            assembly["id"], build_mount_payload(), make_process_technician_headers()
        ),
        expected_status=200,
    )
    aligned = validate_success(_align(api, assembly["id"]), expected_status=200)

    assert_wavefront_rollup(aligned, 0.0721, 0.0204, 0.0925, 0.0060, 0.0985)
    assert aligned["assembly_status"] == "ALIGNED", (
        f"0.0985 clears the 0.1050 budget, got {aligned['assembly_status']}"
    )


def test_one_component_is_reachable_from_its_assembly_and_from_its_work_order(api):
    """Both reverse-reachability projections report the same two rows.

    The PRD states that "Components are read individually, or listed per assembly with
    an optional `component_status` filter." and that "Sub-collection read endpoints
    exist purely as reverse-reachability projections and never mutate anything."

    Design: Corner/endpoints/one_component_is_reachable_from_its_assembly_and_from_its_work_order
    """
    ctx = setup_aligned_assembly(api)
    first, second = ctx["components"]

    assembly_rows, assembly_meta = _assembly_components(api, ctx["assembly"]["id"])
    order_rows, order_meta = _order_components(
        api, ctx["work_order"]["id"], headers=make_quality_manager_headers(QM_PRIMARY)
    )
    single = _read_component(api, second["id"], make_optics_engineer_headers())
    active_rows, active_meta = _assembly_components(
        api, ctx["assembly"]["id"], params={"component_status": "ACTIVE"}
    )
    voided_rows, voided_meta = _order_components(
        api, ctx["work_order"]["id"], params={"component_status": "VOIDED"}
    )

    assert_row_ids(assembly_rows, [first["id"], second["id"]], "the assembly side")
    assert_created_at_ascending(assembly_rows, "the assembly side")
    assert assembly_meta["total_count"] == 2
    assert_row_ids(order_rows, [first["id"], second["id"]], "the work order side")
    assert order_meta["total_count"] == 2, (
        f"both sides report two rows, got {order_meta['total_count']}"
    )
    for row in list(assembly_rows) + list(order_rows):
        assert row["assembly_id"] == ctx["assembly"]["id"], (
            f"every row names the assembly, got {row['assembly_id']}"
        )
        assert row["work_order_id"] == ctx["work_order"]["id"], (
            f"every row names the work order, got {row['work_order_id']}"
        )
    for field, value in assembly_rows[1].items():
        assert single[field] == value, (
            f"the single read must agree with its list entry on {field}: list has "
            f"{value}, read has {single[field]}"
        )
    assert single["slot_index"] == 2
    assert_wavefront_value(
        single["element_wavefront_rms_waves"], 0.0400, "element_wavefront_rms_waves"
    )
    assert single["decenter_um"] == 10.0
    assert single["tilt_arcmin"] == 1.0
    assert single["component_status"] == "ACTIVE"
    assert_row_ids(active_rows, [first["id"], second["id"]], "the ACTIVE filter")
    assert active_meta["total_count"] == 2
    assert voided_rows == [], f"no component is voided yet, got {voided_rows}"
    assert voided_meta["total_count"] == 0
    assembly = _read_assembly(api, ctx["assembly"]["id"])
    assert_wavefront_value(
        assembly["total_transmitted_wavefront_waves"],
        0.0985,
        "total_transmitted_wavefront_waves",
    )


def test_slot_occupancy_is_reported_before_element_allocation_exhaustion(api):
    """An occupied slot outranks an exhausted element allocation.

    The PRD ranks "a slot index unique among an assembly's active components" at
    priority 22 and "The active components drawing on a work order do not exceed its
    `element_count` — `ERR_ELEMENT_ALLOCATION_EXCEEDED`, 409, on component kitting." at
    priority 23, and "the first rule violated determines the entire response, and no
    later rule is evaluated".

    Design: Corner/errors/slot_occupancy_is_reported_before_element_allocation_exhaustion
    """
    ctx = setup_kitted_assembly(api)
    first, second = ctx["components"]
    assert ctx["work_order"]["element_count"] == 2, (
        f"element_count must be 2, got {ctx['work_order']['element_count']}"
    )
    current = _read_assembly(api, ctx["assembly"]["id"])

    occupied = api.create_assembly_component(
        build_assembly_component_payload(
            ctx["assembly"]["id"],
            ctx["work_order"]["id"],
            current["version"],
            slot_index=2,
            element_wavefront_rms_waves=0.0300,
        ),
        make_process_technician_headers(),
    )
    exhausted = api.create_assembly_component(
        build_assembly_component_payload(
            ctx["assembly"]["id"],
            ctx["work_order"]["id"],
            current["version"],
            slot_index=3,
            element_wavefront_rms_waves=0.0300,
        ),
        make_process_technician_headers(),
    )

    validate_error(occupied, ERR_SLOT_ALREADY_OCCUPIED)
    validate_error(exhausted, ERR_ELEMENT_ALLOCATION_EXCEEDED)
    rows, meta = _assembly_components(api, ctx["assembly"]["id"])
    assert_row_ids(rows, [first["id"], second["id"]], "the assembly component listing")
    assert meta["total_count"] == 2, (
        f"neither refusal may create a row, got {meta['total_count']}"
    )
    order_rows, order_meta = _order_components(
        api, ctx["work_order"]["id"], params={"component_status": "ACTIVE"}
    )
    assert order_meta["total_count"] == ctx["work_order"]["element_count"], (
        "the order's active components equal its element_count, got "
        f"{order_meta['total_count']}"
    )
    assert_row_ids(order_rows, [first["id"], second["id"]], "the order's active list")
    after = _read_assembly(api, ctx["assembly"]["id"])
    assert after["version"] == current["version"], (
        f"a refused kitting leaves the version alone, got {after['version']}"
    )
    assert after["assembly_status"] == "KITTED", (
        f"the assembly is still KITTED, got {after['assembly_status']}"
    )
    assert_wavefront_rollup_null(after)


def test_align_and_licence_effects_are_visible_to_the_next_read(api):
    """Two multi-row effects are complete before their response is emitted.

    The PRD states that "by the time a response is emitted, every downstream row the
    cascade reaches is already in its final state, and a subsequent read of that row
    observes the propagated value" and that an approval "then sweeps the design's
    backlog, moving every work order of that design whose `compliance_status` is
    `SCREENED` to `CLEARED`, in `created_at` ascending order."

    Design: Corner/consistency_model/align_and_licence_effects_are_visible_to_the_next_read_with_no_settling_step
    """
    ctx = setup_coated_work_order(api)
    classification = classify_design(api, ctx["design"]["id"], destination_country="DE")
    assert classification["classification_status"] == "LICENSE_REQUIRED", (
        "a controlled optic bound for DE needs a licence, got "
        f"{classification['classification_status']}"
    )
    screened = validate_success(
        api.compliance_screen_work_order(
            ctx["work_order"]["id"],
            make_export_compliance_officer_headers(ECO_CLASSIFIER),
        ),
        expected_status=200,
    )
    assert screened["compliance_status"] == "SCREENED", (
        f"the screen parks the order at SCREENED, got {screened['compliance_status']}"
    )

    approved = validate_success(
        api.record_license_decision(
            classification["id"],
            build_license_decision_payload("APPROVED"),
            make_export_compliance_officer_headers(ECO_DECIDER),
        ),
        expected_status=200,
    )
    swept = _read_order(api, ctx["work_order"]["id"])

    assert approved["classification_status"] == "LICENSE_APPROVED", (
        f"the licence stands approved, got {approved['classification_status']}"
    )
    assert swept["compliance_status"] == "CLEARED", (
        "the very next read of the order already shows the sweep, got "
        f"{swept['compliance_status']}"
    )

    released = validate_success(
        api.release_work_order_to_assembly(
            ctx["work_order"]["id"], make_process_technician_headers()
        ),
        expected_status=200,
    )
    assert released["process_status"] == "RELEASED_TO_ASSEMBLY", (
        "release succeeds immediately on the freshly cleared order, got "
        f"{released['process_status']}"
    )

    assembly = create_assembly(api, ctx["design"]["id"], assembly_code="AS-2540-1")
    kit_components(
        api,
        assembly["id"],
        ctx["work_order"]["id"],
        (
            {
                "slot_index": 1,
                "decenter_um": 10.0,
                "tilt_arcmin": 1.0,
                "element_wavefront_rms_waves": 0.0600,
            },
            {
                "slot_index": 2,
                "decenter_um": 10.0,
                "tilt_arcmin": 1.0,
                "element_wavefront_rms_waves": 0.0400,
            },
        ),
        start_version=assembly["version"],
    )
    validate_success(
        api.cement_assembly(
            assembly["id"], build_cement_payload(), make_process_technician_headers()
        ),
        expected_status=200,
    )
    validate_success(
        api.mount_assembly(
            assembly["id"], build_mount_payload(), make_process_technician_headers()
        ),
        expected_status=200,
    )

    aligned = validate_success(_align(api, assembly["id"]), expected_status=200)
    readiness = validate_success(
        api.get_release_readiness(
            assembly["id"], make_quality_manager_headers(QM_THIRD)
        ),
        expected_status=200,
    )
    reread = _read_assembly(api, assembly["id"])

    assert_wavefront_rollup(aligned, 0.0721, 0.0204, 0.0925, 0.0060, 0.0985)
    assert aligned["assembly_status"] == "ALIGNED", (
        f"the align response itself carries the new state, got {aligned['assembly_status']}"
    )
    assert_wavefront_value(
        readiness["total_transmitted_wavefront_waves"],
        0.0985,
        "total_transmitted_wavefront_waves",
    )
    assert_wavefront_value(
        readiness["transmitted_wavefront_budget_waves"],
        0.1050,
        "transmitted_wavefront_budget_waves",
    )
    assert readiness["wavefront_ok"] is True, (
        f"wavefront_ok must be True, got {readiness['wavefront_ok']}"
    )
    assert readiness["export_ok"] is True, (
        f"export_ok must be True, got {readiness['export_ok']}"
    )
    assert readiness["active_component_count"] == 2, (
        f"active_component_count must be 2, got {readiness['active_component_count']}"
    )
    assert readiness["assembly_status"] == "ALIGNED"
    assert readiness["assembly_id"] == assembly["id"]
    for field in (
        "element_rss_waves",
        "centration_error_waves",
        "subtotal_waves",
        "cement_derate_waves",
        "total_transmitted_wavefront_waves",
    ):
        assert reread[field] == aligned[field], (
            f"{field} may not change between two consecutive reads: align returned "
            f"{aligned[field]} and the re-read has {reread[field]}"
        )
    assert reread["total_transmitted_wavefront_waves"] == (
        readiness["total_transmitted_wavefront_waves"]
    ), (
        "the computed readiness view and the stored row must agree, got "
        f"{readiness['total_transmitted_wavefront_waves']} against "
        f"{reread['total_transmitted_wavefront_waves']}"
    )
