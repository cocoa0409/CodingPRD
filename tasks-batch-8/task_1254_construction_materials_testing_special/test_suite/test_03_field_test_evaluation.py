"""Field-test evaluation: proctor-curve variants, percentage boundary
precision, weld/bolt evaluators, void compensation, and synchronous
visibility of computed results."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    certification_entry,
    create_assignment,
    dispatch_assignment,
    get_project,
    get_scope_items,
    list_project_ncrs,
    make_technician_headers,
    record_bolt_test,
    record_soil_test,
    record_weld_test,
    setup_approved_project,
    setup_dispatched_assignment,
    bolt_scope_item,
    soil_scope_item,
    weld_scope_item,
    create_technician,
    validate_error,
    validate_success,
)

PM = TEST_USERS["project_manager_headers"]


class TestProctorVariantDivergence:
    def _setup_two_curve_project(self, api):
        """One project whose approved SSI carries a STANDARD soil item and a
        MODIFIED soil item with the same reference densities, plus one
        dispatched assignment per item for the same technician."""
        ctx = setup_approved_project(
            [
                soil_scope_item(description="pad standard", proctor_method="STANDARD"),
                soil_scope_item(description="pad modified", proctor_method="MODIFIED"),
            ],
            project_overrides={"name": "Soil Divergence", "permit_number": "P-SOIL-1"},
        )
        tech = create_technician(certifications=[
            certification_entry("SOIL_COMPACTION", level=2)
        ])
        asg_std = create_assignment(
            ctx["project"]["id"], ctx["scope_items"][0]["id"], tech["id"],
            "2026-05-04", "09:00", "10:00",
        )
        dispatch_assignment(asg_std["id"])
        asg_mod = create_assignment(
            ctx["project"]["id"], ctx["scope_items"][1]["id"], tech["id"],
            "2026-05-04", "10:00", "11:00",
        )
        dispatch_assignment(asg_mod["id"])
        return ctx, tech, asg_std, asg_mod

    def test_identical_density_flips_verdict_between_proctor_curves(self, api):
        """PRD §3.4: "When the item's `proctor_method` is `STANDARD`, the
        reference density is `standard_max_density_pcf` and the pass threshold
        is 95.0 percent; when it is `MODIFIED`, the reference is
        `modified_max_density_pcf` and the threshold relaxes to 92.0 percent —
        identical field density can therefore flip verdicts between the two
        curves."
        PRD §3.4: "The relative compaction is one hundred times the measured
        `field_dry_density_pcf` divided by the applicable reference density,
        rounded half up to one decimal place and exposed as
        `relative_compaction_pct` alongside the applied `threshold_pct` in the
        result details."

        Design: Difficulty/dual_variant_calc/soil_proctor_variant_divergence
        """
        _ctx, tech, asg_std, asg_mod = self._setup_two_curve_project(api)
        headers = make_technician_headers(tech["id"])

        std = validate_success(
            api.create_field_test(
                {"assignment_id": asg_std["id"], "measured_values": {"field_dry_density_pcf": 117.7}},
                headers,
            ),
            201,
        )
        mod = validate_success(
            api.create_field_test(
                {"assignment_id": asg_mod["id"], "measured_values": {"field_dry_density_pcf": 117.7}},
                headers,
            ),
            201,
        )
        assert std["result"] == "NONCONFORMING", "117.7/124.0 rounds to 94.9, below 95.0"
        assert std["result_details"]["relative_compaction_pct"] == pytest.approx(94.9, abs=1e-6)
        assert std["result_details"]["threshold_pct"] == pytest.approx(95.0, abs=1e-6)
        assert mod["result"] == "CONFORMING", "117.7/127.0 rounds to 92.7, at or above 92.0"
        assert mod["result_details"]["relative_compaction_pct"] == pytest.approx(92.7, abs=1e-6)
        assert mod["result_details"]["threshold_pct"] == pytest.approx(92.0, abs=1e-6)

    def test_proctor_variant_side_effects_on_scope_items(self, api):
        """PRD §3.4: "A conforming test increments its scope item's
        `completed_count` by one; when that count reaches the item's
        `required_count`, the item's `status` flips from `OPEN` to `SATISFIED`
        — exactly reaching the requirement satisfies it — and the project's
        posture is recomputed. A nonconforming test auto-creates a
        nonconformance report with `source_type` of `FIELD_TEST`, severity
        `STRUCTURAL` when the scope item's `is_structural` flag is true and
        `MAJOR` otherwise, increments the project's `open_ncr_count` by one,
        and recomputes posture."

        Design: Difficulty/dual_variant_calc/soil_proctor_variant_divergence
        """
        ctx, tech, asg_std, asg_mod = self._setup_two_curve_project(api)
        headers = make_technician_headers(tech["id"])
        api.create_field_test(
            {"assignment_id": asg_std["id"], "measured_values": {"field_dry_density_pcf": 117.7}},
            headers,
        )
        api.create_field_test(
            {"assignment_id": asg_mod["id"], "measured_values": {"field_dry_density_pcf": 117.7}},
            headers,
        )
        items = get_scope_items(ctx["ssi"]["id"])
        item_std = [i for i in items if i["description"] == "pad standard"][0]
        item_mod = [i for i in items if i["description"] == "pad modified"][0]
        assert item_std["completed_count"] == 0, "a nonconforming test never increments"
        assert item_std["status"] == "OPEN"
        assert item_mod["completed_count"] == 1
        assert item_mod["status"] == "SATISFIED", "count reached required_count 1"


class TestSoilThresholdBoundary:
    def _setup_boundary_project(self, api):
        ctx = setup_approved_project(
            [soil_scope_item(required_count=2)],
            project_overrides={"name": "Boundary Soil", "permit_number": "P-BND-1"},
        )
        tech = create_technician(certifications=[
            certification_entry("SOIL_COMPACTION", level=2)
        ])
        asg1 = create_assignment(
            ctx["project"]["id"], ctx["scope_items"][0]["id"], tech["id"],
            "2026-05-04", "09:00", "10:00",
        )
        dispatch_assignment(asg1["id"])
        asg2 = create_assignment(
            ctx["project"]["id"], ctx["scope_items"][0]["id"], tech["id"],
            "2026-05-04", "10:00", "11:00",
        )
        dispatch_assignment(asg2["id"])
        return ctx, tech, asg1, asg2

    def test_compaction_exactly_at_threshold_conforms(self, api):
        """PRD §3.4: "A result at or above the threshold conforms — exactly
        95.0 passes, 94.9 fails."
        PRD §2.6: "Boundary comparisons throughout the system are inclusive in
        the direction stated with each rule: a compaction percentage landing
        exactly on its threshold passes, a break landing exactly at its
        tolerance limit is within tolerance, a scope item whose conforming
        count exactly reaches its requirement is satisfied, and an escalation
        score landing exactly on the escalation threshold escalates."

        Design: Difficulty/boundary_precision_check/soil_compaction_exactly_95_percent_passes
        """
        _ctx, tech, asg1, _asg2 = self._setup_boundary_project(api)
        result = validate_success(
            api.create_field_test(
                {"assignment_id": asg1["id"], "measured_values": {"field_dry_density_pcf": 117.8}},
                make_technician_headers(tech["id"]),
            ),
            201,
        )
        assert result["result_details"]["relative_compaction_pct"] == pytest.approx(95.0, abs=1e-6)
        assert result["result"] == "CONFORMING", "exactly at the >= 95.0 threshold passes"

    def test_compaction_one_tenth_below_threshold_raises_ncr(self, api):
        """PRD §3.4: "A result at or above the threshold conforms — exactly
        95.0 passes, 94.9 fails."
        PRD §3.4: "A nonconforming test auto-creates a nonconformance report
        with `source_type` of `FIELD_TEST`, severity `STRUCTURAL` when the
        scope item's `is_structural` flag is true and `MAJOR` otherwise,
        increments the project's `open_ncr_count` by one, and recomputes
        posture."

        Design: Difficulty/boundary_precision_check/soil_compaction_exactly_95_percent_passes
        """
        ctx, tech, asg1, asg2 = self._setup_boundary_project(api)
        headers = make_technician_headers(tech["id"])
        api.create_field_test(
            {"assignment_id": asg1["id"], "measured_values": {"field_dry_density_pcf": 117.8}},
            headers,
        )
        failing = validate_success(
            api.create_field_test(
                {"assignment_id": asg2["id"], "measured_values": {"field_dry_density_pcf": 117.7}},
                headers,
            ),
            201,
        )
        assert failing["result_details"]["relative_compaction_pct"] == pytest.approx(94.9, abs=1e-6)
        assert failing["result"] == "NONCONFORMING"
        project = get_project(ctx["project"]["id"])
        assert project["open_ncr_count"] == 1, "only the 94.9 test raised an NCR"


class TestCompletedCountConservation:
    def test_completed_count_conserved_across_test_and_void(self, api):
        """PRD §3.4: "A conforming test increments its scope item's
        `completed_count` by one; when that count reaches the item's
        `required_count`, the item's `status` flips from `OPEN` to `SATISFIED`
        — exactly reaching the requirement satisfies it — and the project's
        posture is recomputed."
        PRD §3.4: "Voiding is a compensating action: the scope item's
        `completed_count` decrements by one, the item reopens to `OPEN` if the
        count falls back below its requirement, and posture is recomputed."

        Design: Difficulty/compensating_invariant/scope_completed_count_conservation
        """
        ctx = setup_dispatched_assignment(
            item=soil_scope_item(required_count=2),
            project_overrides={"name": "Invariant Count", "permit_number": "P-INV-2"},
        )
        item_id = ctx["scope_items"][0]["id"]
        ft = record_soil_test(ctx["assignment"]["id"], ctx["technician"]["id"], 118.0)
        assert get_scope_items(ctx["ssi"]["id"])[0]["completed_count"] == 1

        voided = validate_success(api.void_field_test(ft["id"], PM), 200)
        assert voided["status"] == "VOIDED"
        item_after = get_scope_items(ctx["ssi"]["id"])[0]
        assert item_after["completed_count"] == 0, "the voided test is excluded from the count"
        assert item_after["status"] == "OPEN"

    def test_replacement_test_after_void_counts_exactly_once(self, api):
        """PRD §3.4: "Voiding is a compensating action: the scope item's
        `completed_count` decrements by one, the item reopens to `OPEN` if the
        count falls back below its requirement, and posture is recomputed."
        PRD §3.4: "A conforming test increments its scope item's
        `completed_count` by one; when that count reaches the item's
        `required_count`, the item's `status` flips from `OPEN` to `SATISFIED`
        — exactly reaching the requirement satisfies it — and the project's
        posture is recomputed."

        Design: Difficulty/compensating_invariant/scope_completed_count_conservation
        """
        ctx = setup_dispatched_assignment(
            item=soil_scope_item(required_count=2),
            project_overrides={"name": "Invariant Count", "permit_number": "P-INV-2"},
        )
        tech_id = ctx["technician"]["id"]
        ft = record_soil_test(ctx["assignment"]["id"], tech_id, 118.0)
        validate_success(api.void_field_test(ft["id"], PM), 200)

        asg2 = create_assignment(
            ctx["project"]["id"], ctx["scope_items"][0]["id"], tech_id,
            "2026-05-04", "10:00", "11:00",
        )
        dispatch_assignment(asg2["id"])
        record_soil_test(asg2["id"], tech_id, 118.5)
        item_after = get_scope_items(ctx["ssi"]["id"])[0]
        assert item_after["completed_count"] == 1, (
            "no double-count of the voided test, no drift after the replacement"
        )


class TestSimpleFieldEvaluators:
    def test_weld_visual_zero_defect_rule(self, api):
        """PRD §3.4: "Weld visual inspection is stricter to state: the test
        conforms only when `defect_count` is zero."
        PRD §3.4: "A nonconforming test auto-creates a nonconformance report
        with `source_type` of `FIELD_TEST`, severity `STRUCTURAL` when the
        scope item's `is_structural` flag is true and `MAJOR` otherwise,
        increments the project's `open_ncr_count` by one, and recomputes
        posture."

        Design: Corner/calculations/weld_visual_zero_defect_rule
        """
        ctx = setup_approved_project(
            [weld_scope_item(required_count=2)],
            project_overrides={"name": "Weld", "permit_number": "P-CALC-1"},
        )
        tech = create_technician(certifications=[certification_entry("WELD_VISUAL", level=2)])
        asg1 = create_assignment(
            ctx["project"]["id"], ctx["scope_items"][0]["id"], tech["id"],
            "2026-05-04", "09:00", "10:00",
        )
        dispatch_assignment(asg1["id"])
        asg2 = create_assignment(
            ctx["project"]["id"], ctx["scope_items"][0]["id"], tech["id"],
            "2026-05-04", "10:00", "11:00",
        )
        dispatch_assignment(asg2["id"])

        clean = record_weld_test(asg1["id"], tech["id"], 0)
        defective = record_weld_test(asg2["id"], tech["id"], 2)
        assert clean["result"] == "CONFORMING"
        assert defective["result"] == "NONCONFORMING"
        item = get_scope_items(ctx["ssi"]["id"])[0]
        assert item["completed_count"] == 1, "only the clean weld counts"
        ncrs = list_project_ncrs(ctx["project"]["id"])
        assert len(ncrs) == 1
        assert ncrs[0]["severity"] == "MAJOR", "is_structural defaults to false"
        assert ncrs[0]["source_type"] == "FIELD_TEST"

    def test_bolt_tension_requires_all_bolts_passed(self, api):
        """PRD §3.4: "Bolt tension conforms only when `bolts_tested` is at
        least one and every tested bolt passed — `bolts_passed` equal to
        `bolts_tested`."

        Design: Corner/calculations/bolt_tension_all_passed_rule
        """
        ctx = setup_approved_project(
            [bolt_scope_item(required_count=2)],
            project_overrides={"name": "Bolt", "permit_number": "P-CALC-2"},
        )
        tech = create_technician(certifications=[certification_entry("BOLT_TENSION", level=2)])
        asg1 = create_assignment(
            ctx["project"]["id"], ctx["scope_items"][0]["id"], tech["id"],
            "2026-05-04", "09:00", "10:00",
        )
        dispatch_assignment(asg1["id"])
        asg2 = create_assignment(
            ctx["project"]["id"], ctx["scope_items"][0]["id"], tech["id"],
            "2026-05-04", "10:00", "11:00",
        )
        dispatch_assignment(asg2["id"])

        all_passed = record_bolt_test(asg1["id"], tech["id"], 10, 10)
        partial = record_bolt_test(asg2["id"], tech["id"], 10, 9)
        assert all_passed["result"] == "CONFORMING"
        assert partial["result"] == "NONCONFORMING", "partial pass rates are not accepted"


class TestVoidRules:
    def test_void_nonconforming_test_rejected(self, api):
        """PRD §3.4: "A recorded test may later be voided by a `ProjectManager`,
        but only a conforming one: voiding a `NONCONFORMING` test — or one
        already `VOIDED` — is rejected with `ERR_TEST_NOT_VOIDABLE`, because a
        failure's NCR must run to verification rather than be erased."

        Design: Corner/state_machines/void_nonconforming_field_test_rejected
        """
        ctx = setup_dispatched_assignment(
            project_overrides={"name": "VoidNC", "permit_number": "P-SM-6"}
        )
        ft = record_soil_test(ctx["assignment"]["id"], ctx["technician"]["id"], 117.0)
        assert ft["result"] == "NONCONFORMING"
        resp = api.void_field_test(ft["id"], PM)
        validate_error(resp, ApiErrorId.ERR_TEST_NOT_VOIDABLE)
        project = get_project(ctx["project"]["id"])
        assert project["open_ncr_count"] == 1, "the auto-created NCR is not disturbed"


class TestImmediateConsistency:
    def test_result_visible_immediately_after_write(self, api):
        """PRD §3.4: "The server copies `test_method`, `technician_id`, and
        `project_id` from the assignment and its scope item at creation —
        attribution that later drives segregation of duties — and evaluates
        the result synchronously, before the response returns."
        PRD §3.4: "A conforming test increments its scope item's
        `completed_count` by one; when that count reaches the item's
        `required_count`, the item's `status` flips from `OPEN` to `SATISFIED`
        — exactly reaching the requirement satisfies it — and the project's
        posture is recomputed."

        Design: Corner/consistency_model/immediate_visibility_of_result_and_counts
        """
        ctx = setup_dispatched_assignment(
            item=soil_scope_item(required_count=2),
            project_overrides={"name": "Immediate", "permit_number": "P-CON-1"},
        )
        ft = validate_success(
            api.create_field_test(
                {"assignment_id": ctx["assignment"]["id"],
                 "measured_values": {"field_dry_density_pcf": 118.0}},
                make_technician_headers(ctx["technician"]["id"]),
            ),
            201,
        )
        assert ft["result"] == "CONFORMING", "the create response carries the computed result"
        item = get_scope_items(ctx["ssi"]["id"])[0]
        assert item["completed_count"] == 1, "the same write is visible on immediate re-read"
        tests = validate_success(
            api.list_assignment_field_tests(ctx["assignment"]["id"], PM), 200
        )
        assert [t["id"] for t in tests] == [ft["id"]]
