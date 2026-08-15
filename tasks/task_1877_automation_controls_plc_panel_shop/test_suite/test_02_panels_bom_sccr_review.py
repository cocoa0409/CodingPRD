"""Panel creation cascades, BOM line economics, and the SCCR weakest-link chain."""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    add_bom_line,
    create_component_payload,
    get_success_data,
    make_designer_headers,
    make_qa_headers,
    new_component,
    new_customer,
    new_job,
    new_panel,
    setup_panel_with_bom,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestPanelCreationCascade:
    def test_panel_creation_cascades_asbuilt_package(self, api, pm_headers, de_headers):
        """PRD §3.2: "Panel creation has two cascading side effects: if the parent
        job was in `OPEN`, it advances to `DESIGN`; and an `AsBuiltPackage` is
        auto-created for the panel with all four document flags set to `false`."
        PRD §3.6: "The `AsBuiltPackage` is the panel's documentation record,
        auto-created at panel creation with all four flags — `has_wiring_diagram`,
        `has_program_archive`, `has_test_report`, `has_ul_label_photo` — set to
        `false` and `completeness_pct` at `0`. The package begins in `INCOMPLETE`."

        Design: Corner/entities/panel_creation_cascades_asbuilt_package
        """
        customer = new_customer(company_name="Cascade Co")
        job = new_job(customer["id"], job_number="J-CA1", quoted_price_cents=100000)
        panel = new_panel(job["id"], design_engineer_id="de-c1", panel_tag="P-CA1")

        packages, _meta = validate_paginated(
            api.list_panel_asbuilt_packages(panel["id"], de_headers)
        )
        assert len(packages) == 1, f"expected exactly one as-built package, got {len(packages)}"
        pkg = packages[0]
        assert pkg["status"] == "INCOMPLETE"
        assert pkg["completeness_pct"] == 0
        for flag in ("has_wiring_diagram", "has_program_archive", "has_test_report",
                     "has_ul_label_photo"):
            assert pkg[flag] is False, f"{flag} must start false"

        job_after = validate_success(api.get_job(job["id"], pm_headers), 200)
        assert job_after["status"] == "DESIGN", (
            f"first panel must auto-advance job OPEN -> DESIGN, got {job_after['status']}"
        )


class TestBomLineEconomics:
    def test_panel_component_extended_cost_computed_input_ignored(self, api, de_headers):
        """PRD §3.2: "Adding a line does several things at once: it captures the
        catalog's current `unit_cost_cents` into the line's
        `unit_cost_snapshot_cents` (so a later catalog price change cannot drift an
        as-built BOM), it computes the line's `extended_cost_cents` as `quantity`
        multiplied by `unit_cost_snapshot_cents` rounded half-up to integer cents,
        and it triggers a recompute of the panel's `sccr_rating_ka` and the BOM cost
        rollup."
        PRD §3.2: "A BOM-line update by the `DesignEngineer` changes `quantity` while
        the line is still `PENDING`; that re-computes `extended_cost_cents` and
        increments the line's `version`."

        Design: Corner/entities/panel_component_extended_cost_computed_input_ignored
        """
        ctx = setup_panel_with_bom(
            company_name="Comp Co", job_number="J-CC1", quoted_price_cents=100000,
            panel_tag="P-CC1", design_engineer_id="de-cc",
        )
        panel_id = ctx["panel"]["id"]
        component = new_component(
            part_number="CON-CC", component_class="CONTACTOR", unit_cost_cents=8000,
            lead_time_days=5, sccr_ka=10, heat_dissipation_w=20,
        )
        line = validate_success(
            api.add_panel_component(
                panel_id, {"component_id": component["id"], "quantity": 3}, de_headers
            ),
            201,
        )
        assert line["extended_cost_cents"] == 24000, (
            f"expected 3 * 8000 = 24000, got {line['extended_cost_cents']}"
        )
        assert line["unit_cost_snapshot_cents"] == 8000
        assert line["line_status"] == "PENDING"


class TestSccrInputSet:
    def test_sccr_excludes_unrated_and_control_class_lines(self, api, de_headers):
        """PRD §3.2: "The input set is every BOM line whose `line_status` is one of
        `PENDING`, `ORDERED`, `RECEIVED`, or `SUBSTITUTED` and whose referenced
        component's `component_class` is one of `DISCONNECT`, `BRANCH_PROTECTIVE`,
        `CONTACTOR`, `OVERLOAD`, or `POWER_SUPPLY`, with a non-null `sccr_ka`; lines
        whose component is in `WIRE_DUCT`, `TERMINAL`, `PLC_IO`, or `PILOT_DEVICE`,
        or whose component carries a null `sccr_ka`, are excluded from the
        min-chain."

        Design: Corner/calculations/sccr_excludes_unrated_and_control_class_lines
        """
        ctx = setup_panel_with_bom(
            company_name="SCCR Co", job_number="J-SC2", quoted_price_cents=100000,
            panel_tag="P-SC2", design_engineer_id="de-sc",
            component_spec={
                "part_number": "BPD-S2", "component_class": "BRANCH_PROTECTIVE",
                "unit_cost_cents": 10000, "lead_time_days": 7, "sccr_ka": 10,
                "heat_dissipation_w": 8,
            },
        )
        panel_id = ctx["panel"]["id"]
        wire_duct = new_component(
            part_number="WD-S2", component_class="WIRE_DUCT", unit_cost_cents=1000,
            lead_time_days=2, sccr_ka=None, heat_dissipation_w=0,
        )
        plc_io = new_component(
            part_number="IO-S2", component_class="PLC_IO", unit_cost_cents=20000,
            lead_time_days=14, sccr_ka=65, heat_dissipation_w=5,
        )
        add_bom_line(panel_id, wire_duct["id"], quantity=4)
        add_bom_line(panel_id, plc_io["id"], quantity=2)

        panel = validate_success(api.get_panel(panel_id, de_headers), 200)
        assert panel["sccr_rating_ka"] == 10, (
            f"only the 10 kA BPD participates in the min-chain, got {panel['sccr_rating_ka']}"
        )


class TestCatalogComponent:
    def test_catalog_component_get_not_found_returns_404(self, api, qa_headers):
        """PRD §2.9: "4. `ERR_NOT_FOUND` — path-templated resource missing, validated
        left-to-right (customer, then job, then panel, then child)."
        PRD §5: `ERR_NOT_FOUND` maps to HTTP 404.

        Design: Corner/entities/catalog_component_get_not_found_returns_404
        """
        resp = api.get_component(NON_EXISTENT_UUID, qa_headers)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND, 404)

    def test_component_inactive_blocks_new_bom_line(self, api, qa_headers, de_headers):
        """PRD §3.2: "Adding a line whose `component_id` references an inactive
        component is rejected with `ERR_COMPONENT_INACTIVE` (HTTP 422)".
        PRD §3.3: "Inactive components may not be referenced by a new BOM line or a
        new substitution request — both are rejected with `ERR_COMPONENT_INACTIVE` —
        but they remain readable for existing as-built records."

        Design: Corner/validations/component_inactive_blocks_new_bom_line
        """
        ctx = setup_panel_with_bom(
            company_name="IA Co", job_number="J-IA1", quoted_price_cents=100000,
            panel_tag="P-IA1", design_engineer_id="de-ia",
        )
        component = new_component(
            part_number="CI-1", component_class="CONTACTOR", unit_cost_cents=8000,
            lead_time_days=5, sccr_ka=10, heat_dissipation_w=20,
        )
        get_success_data(api.update_component(component["id"], {"active": False}, qa_headers), 200)

        resp = api.add_panel_component(
            ctx["panel"]["id"], {"component_id": component["id"], "quantity": 1}, de_headers
        )
        validate_error(resp, ApiErrorId.ERR_COMPONENT_INACTIVE, 422)

        fetched = validate_success(api.get_component(component["id"], qa_headers), 200)
        assert fetched["active"] is False, "inactive component must remain readable"


class TestDesignReviewSegregation:
    def test_segregation_of_duties_designer_cannot_approve_own_design(self, api):
        """PRD §2.8: "The API enforces this at five points, all rejected with
        `ERR_SEGREGATION_OF_DUTIES` (HTTP 403):" and "`QAManager` approving a panel's
        design must have a user id different from that panel's
        `design_engineer_id`."

        Design: Corner/validations/segregation_of_duties_designer_cannot_approve_own_design
        """
        ctx = setup_panel_with_bom(
            company_name="SoD Co", job_number="J-SD1", quoted_price_cents=100000,
            panel_tag="P-SD1", design_engineer_id="de-sod",
            component_spec={
                "part_number": "BPD-SD", "component_class": "BRANCH_PROTECTIVE",
                "unit_cost_cents": 10000, "lead_time_days": 7, "sccr_ka": 10,
                "heat_dissipation_w": 8,
            },
        )
        panel_id = ctx["panel"]["id"]
        get_success_data(api.submit_review(panel_id, make_designer_headers("de-sod")), 200)

        resp = api.approve_design(panel_id, make_qa_headers("de-sod"))
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, 403)

        approved = validate_success(
            api.approve_design(panel_id, make_qa_headers("qa-other")), 200
        )
        assert approved["status"] == "DESIGN_APPROVED"


class TestDesignRevisionLoop:
    def _setup_loop_panel(self, api):
        ctx = setup_panel_with_bom(
            company_name="Zeta Chemicals", job_number="J-6001", quoted_price_cents=700000,
            panel_tag="P-R1", design_engineer_id="de-005",
            component_spec={
                "part_number": "BPD-R100", "component_class": "BRANCH_PROTECTIVE",
                "unit_cost_cents": 45000, "lead_time_days": 28, "sccr_ka": 100,
                "heat_dissipation_w": 12,
            },
        )
        panel_id = ctx["panel"]["id"]
        contactor = new_component(
            part_number="CON-R5", component_class="CONTACTOR", unit_cost_cents=8000,
            lead_time_days=5, sccr_ka=5, heat_dissipation_w=20,
        )
        con_line = add_bom_line(panel_id, contactor["id"])
        ctx["contactor"] = contactor
        ctx["con_line"] = con_line
        return ctx

    def test_panel_revision_loop_twice_then_approve(self, api, de_headers):
        """PRD §3.2: "The same `QAManager` may instead reject the design, returning
        the panel to `DESIGN` for revision — this revision loop is the panel's
        primary cycle, and each leg of it increments the panel's `version` by one."
        PRD §3.2: "In `DESIGN_REVIEW`, a `QAManager` other than the panel's
        `design_engineer_id` may approve the design (`DESIGN_REVIEW →
        DESIGN_APPROVED`)".

        Design: Difficulty/non_linear_state_machine/panel_design_review_revision_loop
        """
        ctx = self._setup_loop_panel(api)
        panel_id = ctx["panel"]["id"]
        qa = make_qa_headers("qa-904")
        de = make_designer_headers("de-005")

        get_success_data(api.submit_review(panel_id, de), 200)
        first = validate_success(api.reject_design(panel_id, qa), 200)
        assert first["status"] == "DESIGN", f"after first reject: {first['status']}"

        get_success_data(api.submit_review(panel_id, de), 200)
        second = validate_success(api.reject_design(panel_id, qa), 200)
        assert second["status"] == "DESIGN", (
            f"loop count 2 must not lock the machine: {second['status']}"
        )

        get_success_data(api.submit_review(panel_id, de), 200)
        final = validate_success(api.approve_design(panel_id, qa), 200)
        assert final["status"] == "DESIGN_APPROVED"

    def test_panel_bom_quantity_edit_persists_across_revision_loop(self, api, de_headers):
        """PRD §3.2: "A BOM-line update by the `DesignEngineer` changes `quantity`
        while the line is still `PENDING`; that re-computes `extended_cost_cents` and
        increments the line's `version`."
        PRD §3.2: "it computes the line's `extended_cost_cents` as `quantity`
        multiplied by `unit_cost_snapshot_cents` rounded half-up to integer cents".

        Design: Difficulty/non_linear_state_machine/panel_design_review_revision_loop
        """
        ctx = self._setup_loop_panel(api)
        panel_id = ctx["panel"]["id"]
        qa = make_qa_headers("qa-904")
        de = make_designer_headers("de-005")
        line_id = ctx["con_line"]["id"]

        get_success_data(api.submit_review(panel_id, de), 200)
        get_success_data(api.reject_design(panel_id, qa), 200)
        updated = validate_success(
            api.update_panel_component(line_id, {"quantity": 2}, de_headers), 200
        )
        assert updated["extended_cost_cents"] == 16000, (
            f"expected 2 * 8000 = 16000, got {updated['extended_cost_cents']}"
        )

        # The BOM edit survives the next revision leg and the loop still completes.
        get_success_data(api.submit_review(panel_id, de), 200)
        get_success_data(api.reject_design(panel_id, qa), 200)
        reread = validate_success(api.get_panel_component(line_id, de_headers), 200)
        assert reread["quantity"] == 2
        assert reread["extended_cost_cents"] == 16000

        get_success_data(api.submit_review(panel_id, de), 200)
        final = validate_success(api.approve_design(panel_id, qa), 200)
        assert final["status"] == "DESIGN_APPROVED"


class TestSccrSubmitReviewBoundary:
    def _setup_boundary_panels(self, api):
        customer = new_customer(company_name="Mu Textiles")
        job = new_job(customer["id"], job_number="J-9101", quoted_price_cents=200000)
        panel_5 = new_panel(job["id"], design_engineer_id="de-009", panel_tag="P-B5")
        panel_4 = new_panel(job["id"], design_engineer_id="de-009", panel_tag="P-B4")
        comp_5 = new_component(
            part_number="CON-B5", component_class="CONTACTOR", unit_cost_cents=8000,
            lead_time_days=5, sccr_ka=5, heat_dissipation_w=20,
        )
        comp_4 = new_component(
            part_number="CON-B4", component_class="CONTACTOR", unit_cost_cents=7000,
            lead_time_days=5, sccr_ka=4, heat_dissipation_w=20,
        )
        add_bom_line(panel_5["id"], comp_5["id"])
        add_bom_line(panel_4["id"], comp_4["id"])
        return panel_5, panel_4

    def test_submit_review_sccr_exactly_5_passes(self, api, de_headers):
        """PRD §3.2: "Once a panel has at least one BOM line and its
        `sccr_rating_ka` is at least `5` (the UL 508A minimum labelable SCCR), the
        `DesignEngineer` may submit the panel for design review, transitioning
        `DESIGN → DESIGN_REVIEW`."

        Design: Difficulty/boundary_precision_check/sccr_exactly_5_passes_4_fails_submit_review
        """
        panel_5, _panel_4 = self._setup_boundary_panels(api)
        panel = validate_success(api.get_panel(panel_5["id"], de_headers), 200)
        assert panel["sccr_rating_ka"] == 5, "boundary precondition: rating exactly 5"

        submitted = validate_success(api.submit_review(panel_5["id"], de_headers), 200)
        assert submitted["status"] == "DESIGN_REVIEW", (
            f"boundary value 5 passes the >= 5 gate, got {submitted['status']}"
        )

    def test_submit_review_sccr_4_rejected(self, api, de_headers):
        """PRD §3.2: "A submit-review against a panel whose SCCR is below the floor
        is rejected with `ERR_SCCR_BELOW_MINIMUM` (HTTP 422)".

        Design: Difficulty/boundary_precision_check/sccr_exactly_5_passes_4_fails_submit_review
        """
        _panel_5, panel_4 = self._setup_boundary_panels(api)
        panel = validate_success(api.get_panel(panel_4["id"], de_headers), 200)
        assert panel["sccr_rating_ka"] == 4, "boundary precondition: rating exactly 4"

        resp = api.submit_review(panel_4["id"], de_headers)
        validate_error(resp, ApiErrorId.ERR_SCCR_BELOW_MINIMUM, 422)
        after = validate_success(api.get_panel(panel_4["id"], de_headers), 200)
        assert after["status"] == "DESIGN", "rejected submit must leave the panel in DESIGN"


class TestSccrConditionalRaise:
    def _setup_raise_panel(self, api):
        ctx = setup_panel_with_bom(
            company_name="Epsilon Aggregates", job_number="J-5001",
            quoted_price_cents=600000, panel_tag="P-S1", design_engineer_id="de-004",
            component_spec={
                "part_number": "BPD-10", "component_class": "BRANCH_PROTECTIVE",
                "unit_cost_cents": 10000, "lead_time_days": 7, "sccr_ka": 10,
                "heat_dissipation_w": 8,
            },
        )
        panel_id = ctx["panel"]["id"]
        bpd_line = ctx["lines"][0]
        for spec in (
            {"part_number": "CON-5", "component_class": "CONTACTOR",
             "unit_cost_cents": 8000, "lead_time_days": 5, "sccr_ka": 5,
             "heat_dissipation_w": 20},
            {"part_number": "OVL-5", "component_class": "OVERLOAD",
             "unit_cost_cents": 5000, "lead_time_days": 5, "sccr_ka": 5,
             "heat_dissipation_w": 10},
            {"part_number": "PS-10", "component_class": "POWER_SUPPLY",
             "unit_cost_cents": 30000, "lead_time_days": 10, "sccr_ka": 10,
             "heat_dissipation_w": 40},
        ):
            add_bom_line(panel_id, new_component(**spec)["id"])
        bpd100 = new_component(
            part_number="BPD-100", component_class="BRANCH_PROTECTIVE",
            unit_cost_cents=45000, lead_time_days=28, sccr_ka=100, heat_dissipation_w=12,
        )
        ctx["bpd_line"] = bpd_line
        ctx["bpd100"] = bpd100
        return ctx

    def test_sccr_weakest_link_baseline_min_chain(self, api, de_headers):
        """PRD §3.2: "Otherwise the baseline is the minimum `sccr_ka` across the set
        — except that if any line's component is a current-limiting
        branch-protective device (a `BRANCH_PROTECTIVE` with `sccr_ka` of at least
        `100`), every `CONTACTOR` or `OVERLOAD` in the set has its `sccr_ka` raised
        to a floor of `25` before the minimum is taken; the panel's rating is then
        that raised minimum."

        Design: Difficulty/combinatorial_formula/sccr_weakest_link_conditional_raise_mode_a
        """
        ctx = self._setup_raise_panel(api)
        panel = validate_success(api.get_panel(ctx["panel"]["id"], de_headers), 200)
        assert panel["sccr_rating_ka"] == 5, (
            "no current-limiting BPD: plain minimum over {10, 5, 5, 10}, got "
            f"{panel['sccr_rating_ka']}"
        )

    def test_sccr_conditional_raise_via_current_limiting_bpd(self, api, qa_headers):
        """PRD §3.2: "if any line's component is a current-limiting
        branch-protective device (a `BRANCH_PROTECTIVE` with `sccr_ka` of at least
        `100`), every `CONTACTOR` or `OVERLOAD` in the set has its `sccr_ka` raised
        to a floor of `25` before the minimum is taken; the panel's rating is then
        that raised minimum."
        PRD §3.3: "The panel's `sccr_rating_ka` is recomputed under the new component
        mix, and the request's `sccr_impact_ka` records what the panel's rating would
        be after approval — a value captured for audit even if the rating is later
        recomputed."

        Design: Difficulty/combinatorial_formula/sccr_weakest_link_conditional_raise_mode_a
        """
        ctx = self._setup_raise_panel(api)
        panel_id = ctx["panel"]["id"]
        sub = get_success_data(
            api.create_substitution_request(
                panel_id,
                {
                    "original_line_id": ctx["bpd_line"]["id"],
                    "proposed_component_id": ctx["bpd100"]["id"],
                    "reason": "raise panel SCCR",
                },
                make_designer_headers("de-004"),
            ),
            201,
        )
        approved = validate_success(
            api.approve_substitution(sub["id"], make_qa_headers("qa-903")), 200
        )
        assert approved["sccr_impact_ka"] == 10, (
            f"min over {{100, raised 25, raised 25, 10}} = 10, got {approved['sccr_impact_ka']}"
        )
        panel = validate_success(api.get_panel(panel_id, qa_headers), 200)
        assert panel["sccr_rating_ka"] == 10, (
            f"panel rating after approval must be 10, got {panel['sccr_rating_ka']}"
        )
