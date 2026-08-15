"""Components: salvage, inspection/quarantine, consumption gates, and the
cancel compensation that returns consumed parts to the pool."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    advance_work_order,
    assert_component,
    consume_component_payload,
    create_active_spec,
    create_distributor,
    create_graded_return,
    declare_route,
    get_component,
    get_reman_engine,
    inspect_component,
    open_work_order,
    perform_operation,
    salvage_component,
    set_logical_clock,
    station_window,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["plant_admin_headers"]
TECH = TEST_USERS["shop_technician_headers"]


def _wo_in_assembly_with_component(distributor, spec, interchange_group,
                                   grade=None, quarantine=False,
                                   part_type="CRANKSHAFT"):
    """WO driven to ASSEMBLY with one salvaged (and optionally inspected)
    component. Returns (work_order, component); the work order carries its
    freshly minted reman_engine_id."""
    ret = create_graded_return(distributor, spec)
    wo = open_work_order(ret)
    wo = advance_work_order(wo["id"], "TEARDOWN")
    comp = salvage_component(wo["id"], part_type, interchange_group)
    if grade is not None:
        comp = inspect_component(comp["id"], grade, quarantine)
    ops = declare_route(wo, spec)
    advance_work_order(wo["id"], "MACHINING")
    for idx, op in enumerate(ops):
        start, end = station_window(0, offset_hours=idx)
        perform_operation(op["id"], "STN-CMP", start, end, "PASS")
    wo = advance_work_order(wo["id"], "ASSEMBLY")
    return wo, comp


class TestConsumptionGates:
    def test_consume_quarantined_component_masked_over_interchange(self, api):
        """PRD §3.7: "The checks on consumption run in a deliberate order."
        PRD §3.7: "Next, the quarantine gate, which is deliberately distinct
        from the general state check: a `QUARANTINED` component is rejected
        specifically with `ERR_COMPONENT_QUARANTINED` (HTTP 422)."
        PRD §3.7: "Finally the interchange gate: the component's
        `interchange_group` must be a member of the spec's
        `allowed_interchange_groups`, else `ERR_INTERCHANGE_INCOMPATIBLE`
        (HTTP 422)."

        Design: Difficulty/priority_pair_validation_conflict/consume_quarantine_masks_interchange
        """
        set_logical_clock()
        distributor = create_distributor(distributor_code="D-Q",
                                         name="Quality Cores")
        spec = create_active_spec(application_code="CAMARO-1997",
                                  allowed_interchange_groups=["CRANK-SBC-3.48"])
        wo, comp = _wo_in_assembly_with_component(
            distributor, spec, "GRP-UNKNOWN", grade="REUSE_OK",
            quarantine=True)
        assert comp["status"] == "QUARANTINED"

        resp = api.consume_component(wo["id"],
                                     consume_component_payload(comp["id"]),
                                     TECH)
        # The quarantine gate fires before the interchange gate.
        validate_error(resp, ApiErrorId.ERR_COMPONENT_QUARANTINED)
        assert get_component(comp["id"])["status"] == "QUARANTINED"

    def test_consume_quarantined_component_with_valid_group_rejected(self, api):
        """PRD §3.7: "Next, the quarantine gate, which is deliberately
        distinct from the general state check: a `QUARANTINED` component is
        rejected specifically with `ERR_COMPONENT_QUARANTINED` (HTTP 422)."

        Design: Difficulty/priority_pair_validation_conflict/consume_quarantine_masks_interchange
        """
        set_logical_clock()
        distributor = create_distributor(distributor_code="D-Q",
                                         name="Quality Cores")
        spec = create_active_spec(application_code="CAMARO-1997")
        wo, comp = _wo_in_assembly_with_component(
            distributor, spec, "CRANK-SBC-3.48", grade="REUSE_OK",
            quarantine=True)

        resp = api.consume_component(wo["id"],
                                     consume_component_payload(comp["id"]),
                                     TECH)
        validate_error(resp, ApiErrorId.ERR_COMPONENT_QUARANTINED)

        after = get_component(comp["id"])
        assert after["status"] == "QUARANTINED", "rejection is side-effect free"
        assert after["consumed_by_work_order_id"] is None

    def test_consume_rework_grade_when_spec_allows_only_reuse_ok(self, api):
        """PRD §3.7: "Then the reuse gate: the component's `reuse_grade` must
        be non-null and a member of the work order's spec's
        `allowed_reuse_grades`, else `ERR_REUSE_GRADE_INSUFFICIENT`
        (HTTP 422)."

        Design: Corner/validations/consume_rework_grade_when_spec_allows_only_reuse_ok
        """
        set_logical_clock()
        distributor = create_distributor(distributor_code="D-RG",
                                         name="Reuse Grade Cores")
        spec = create_active_spec(application_code="LUMINA-1995",
                                  allowed_reuse_grades=["REUSE_OK"])
        wo, comp = _wo_in_assembly_with_component(
            distributor, spec, "CRANK-SBC-3.48", grade="REWORK")
        assert comp["status"] == "AVAILABLE"

        resp = api.consume_component(wo["id"],
                                     consume_component_payload(comp["id"]),
                                     TECH)
        validate_error(resp, ApiErrorId.ERR_REUSE_GRADE_INSUFFICIENT)
        assert get_component(comp["id"])["status"] == "AVAILABLE"

    def test_consume_wrong_interchange_group_rejected(self, api):
        """PRD §3.7: "Finally the interchange gate: the component's
        `interchange_group` must be a member of the spec's
        `allowed_interchange_groups`, else `ERR_INTERCHANGE_INCOMPATIBLE`
        (HTTP 422)."

        Design: Corner/validations/consume_wrong_interchange_group_rejected
        """
        set_logical_clock()
        distributor = create_distributor(distributor_code="D-IX",
                                         name="Interchange Cores")
        spec = create_active_spec(application_code="MONTECARLO-1995")
        wo, comp = _wo_in_assembly_with_component(
            distributor, spec, "GRP-UNKNOWN", grade="REUSE_OK")

        resp = api.consume_component(wo["id"],
                                     consume_component_payload(comp["id"]),
                                     TECH)
        validate_error(resp, ApiErrorId.ERR_INTERCHANGE_INCOMPATIBLE)
        assert get_component(comp["id"])["status"] == "AVAILABLE"


class TestConsumeCancelConservation:
    def test_consume_moves_component_into_assembly(self, api):
        """PRD §3.7: "A successful consumption moves the component from
        `AVAILABLE` to `CONSUMED` and sets its `consumed_by_work_order_id` to
        the consuming work order."

        Design: Difficulty/compensating_invariant/component_pool_conserved_through_consume_and_cancel
        """
        set_logical_clock()
        distributor = create_distributor(distributor_code="D-POOL",
                                         name="Pool Cores")
        spec = create_active_spec(application_code="BLAZER-1998",
                                  allowed_reuse_grades=["REUSE_OK"])
        wo, comp = _wo_in_assembly_with_component(
            distributor, spec, "CRANK-SBC-3.48", grade="REUSE_OK")
        assert comp["status"] == "AVAILABLE", "pool baseline before consume"

        consumed = validate_success(api.consume_component(
            wo["id"], consume_component_payload(comp["id"]), TECH), 200)
        assert_component(consumed)
        assert consumed["status"] == "CONSUMED"
        assert consumed["consumed_by_work_order_id"] == wo["id"]

    def test_cancel_releases_consumed_component_and_scraps_engine(self, api):
        """PRD §3.5: "Cancellation releases the order's component claims:
        every component whose `consumed_by_work_order_id` names this order
        flips from `CONSUMED` back to `AVAILABLE` with
        `consumed_by_work_order_id` cleared."
        PRD §3.5: "Cancellation from `ASSEMBLY` is additionally destructive:
        if the order's `reman_engine_id` is non-null, the referenced engine
        moves from `BUILT` to `SCRAPPED`."

        Design: Difficulty/compensating_invariant/component_pool_conserved_through_consume_and_cancel
        """
        set_logical_clock()
        distributor = create_distributor(distributor_code="D-POOL",
                                         name="Pool Cores")
        spec = create_active_spec(application_code="BLAZER-1998",
                                  allowed_reuse_grades=["REUSE_OK"])
        wo, comp = _wo_in_assembly_with_component(
            distributor, spec, "CRANK-SBC-3.48", grade="REUSE_OK")
        engine_id = wo["reman_engine_id"]
        validate_success(api.consume_component(
            wo["id"], consume_component_payload(comp["id"]), TECH), 200)

        cancelled = validate_success(api.cancel_work_order(wo["id"], ADMIN),
                                     200)
        assert cancelled["status"] == "CANCELLED"

        released = get_component(comp["id"])
        assert released["status"] == "AVAILABLE", (
            "compensating release returns the component to the pool")
        assert released["consumed_by_work_order_id"] is None

        assert get_reman_engine(engine_id)["status"] == "SCRAPPED", (
            "cancel in ASSEMBLY scraps the half-built engine")


class TestComponentListing:
    def test_components_pagination_with_filtering(self, api):
        """PRD §2.3: "The `limit` parameter specifies the maximum number of
        items to return; when omitted it defaults to 10, with a minimum
        allowed value of 1 and a maximum of 100. The `offset` parameter
        specifies how many items to skip and defaults to 0."
        PRD §2.3: "The `meta` object of a list response carries the pagination
        fields `limit`, `offset`, `total_count`, and `has_more`."

        Design: Corner/cross_cutting_layers/components_pagination_with_filtering
        """
        set_logical_clock()
        distributor = create_distributor(distributor_code="D-PG",
                                         name="Page Cores")
        spec = create_active_spec(application_code="SONOMA-1995")
        ret = create_graded_return(distributor, spec)
        wo = open_work_order(ret)
        advance_work_order(wo["id"], "TEARDOWN")
        salvage_component(wo["id"], "CRANKSHAFT", "CRANK-SBC-3.48")
        salvage_component(wo["id"], "CRANKSHAFT", "CRANK-SBC-3.48")
        salvage_component(wo["id"], "CYLINDER_HEAD", "HEAD-SBC-VORTEC")

        page1, meta1 = validate_paginated(api.list_components(
            wo["id"], ADMIN, params={"limit": 2, "offset": 0}))
        assert len(page1) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True

        page2, meta2 = validate_paginated(api.list_components(
            wo["id"], ADMIN, params={"limit": 2, "offset": 2}))
        assert len(page2) == 1
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False
        for row in page1 + page2:
            assert_component(row)
