"""Segmentation failure cycles, the two requirement dimensions and the partition."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers.api_errors import ERR_INVALID_SEGMENT_STATE
from test_helpers.assertions import (
    assert_partition_counts,
    assert_percentage,
    assert_requirement_dimensions,
    assert_same_instant,
    assert_segment_state,
    assert_total_count,
    assert_version_bumped_by,
    assert_version_unchanged,
    find_row,
)
from test_helpers.constants import CLOCK_DEFAULT
from test_helpers.factories import (
    assign_payload,
    remediation_revalidation_payload,
    reopen_payload,
    retest_payload,
)
from test_helpers.fixtures import (
    Scenario,
    add_component,
    build_engagement_with_in_place_requirement,
    build_validated_cde_engagement,
    declare_segment,
    ok,
    plan_segmentation,
    read_engagement,
    record_verdict,
    requirement_concluded,
)
from test_helpers.test_users import make_lead_headers

RETAIL_STORE = "RETAIL_STORE"
FACILITY_RETAIL = "RETAIL-12"
POS_HOSTNAMES = ("pos-01", "pos-02", "pos-03", "pos-04")


def _store_zone_awaiting_verdict(api) -> Scenario:
    """Build a validated cardholder zone plus a store zone awaiting its verdict.

    Three hosts sit in the validated cardholder zone at DC-EAST and four
    point-of-sale terminals sit in a store zone the client declared out of
    scope, so the inventory holds seven rows partitioned 3 / 0 / 4.
    """
    scenario = build_validated_cde_engagement(api)
    lead_id = scenario["lead_id"]
    engagement_id = scenario["engagement_id"]

    store = declare_segment(
        api, engagement_id, lead_id, "STORE-POS", segment_class="OUT_OF_SCOPE"
    )
    terminals = {}
    for hostname in POS_HOSTNAMES:
        terminals[hostname] = add_component(
            api,
            engagement_id,
            lead_id,
            store["id"],
            hostname,
            component_type="POS_TERMINAL",
            function_class="PAYMENT_APPLICATION",
            stores_chd=False,
            facility_name=FACILITY_RETAIL,
            facility_type=RETAIL_STORE,
        )
    scenario["store"] = plan_segmentation(
        api,
        store["id"],
        lead_id,
        test_method="TRAFFIC_ANALYSIS",
        planned_date="2026-08-06",
    )
    scenario["store_id"] = store["id"]
    scenario["terminals"] = terminals
    scenario["terminal_ids"] = {name: row["id"] for name, row in terminals.items()}
    return scenario


def _replan_segmentation(
    api,
    segment_id: str,
    lead_id: str,
    test_method: str = "PEN_TEST",
    planned_date: str = "2026-08-14",
):
    """Return a disproven zone to testing after the boundary was remediated."""
    return ok(
        api.request_remediation_revalidation(
            segment_id,
            remediation_revalidation_payload(
                test_method=test_method, planned_date=planned_date
            ),
            make_lead_headers(lead_id),
        )
    )


def _read_segment(api, segment_id: str, lead_id: str):
    return validate_success(
        api.get_network_segment(segment_id, make_lead_headers(lead_id))
    )


def _read_component(api, component_id: str, lead_id: str):
    return validate_success(
        api.get_system_component(component_id, make_lead_headers(lead_id))
    )


def _two_in_place_requirements(api) -> Scenario:
    """Conclude two requirements IN_PLACE on one scope-locked engagement.

    Requirement 1.2.1 belongs to family R1 and requirement 3.5.1 to family R3;
    both are fully evidenced and neither has ever carried a gap.
    """
    scenario = build_engagement_with_in_place_requirement(api)
    second = requirement_concluded(
        api,
        scenario["engagement_id"],
        scenario["lead_id"],
        "3.5.1",
        "R3",
        scenario["component_ids"]["pay-01"],
        conclusion="IN_PLACE",
        interviewee_name="S. Iyer",
        interviewee_title="Key Custodian",
        conclusion_rationale="Keys are held in the module and split under dual control.",
    )
    scenario["requirement_b"] = second
    scenario["requirement_b_id"] = second["id"]
    return scenario


def _reopen(api, requirement_id: str, lead_id: str):
    return ok(
        api.reopen_requirement(
            requirement_id, reopen_payload(), make_lead_headers(lead_id)
        )
    )


def _open_item_of(api, engagement_id: str, requirement_id: str, lead_id: str):
    """Discover the gap a cascade minted, which no caller ever created."""
    rows = validate_success(
        api.list_remediation_items(
            make_lead_headers(lead_id),
            {
                "engagement_id": engagement_id,
                "requirement_assessment_id": requirement_id,
                "status": "OPEN",
            },
        )
    )
    assert len(rows) == 1, "expected exactly one open gap, got %d" % len(rows)
    return rows[0]


class TestSegmentationFailureRevalidationCycle:
    """A disproven zone revisits testing, and only a PASS reverses the expansion."""

    def test_replanning_returns_the_zone_to_testing_without_releasing_scope(self, api):
        """The second visit to testing keeps the whole subtree inside the environment.

        PRD: Crucially, re-planning does *not* undo the scope expansion:
        `scope_expanded_by_failure` stays true and the whole subtree keeps
        `effective_class` `CDE` until an actual `PASS` verdict lands.

        Design: Difficulty/non_linear_state_machine/segment_fail_revalidation_cycle_restores_scope
        """
        scenario = _store_zone_awaiting_verdict(api)
        lead_id = scenario["lead_id"]
        store_id = scenario["store_id"]

        failed = record_verdict(
            api,
            store_id,
            lead_id,
            outcome="FAIL",
            note="Store VLAN reached the cardholder network over the management path.",
        )
        assert_segment_state(
            failed,
            segmentation_status="FAILED",
            effective_class="CDE",
            scope_expanded_by_failure=True,
            revalidation_round=0,
        )
        assert_partition_counts(
            read_engagement(api, scenario["engagement_id"], lead_id), 7, 0, 0
        )

        replanned = _replan_segmentation(api, store_id, lead_id)

        # The same testing state is occupied a second time, and the round counter
        # is what tells the two visits apart.
        assert_segment_state(
            replanned,
            segmentation_status="TEST_PLANNED",
            effective_class="CDE",
            segment_class="OUT_OF_SCOPE",
            scope_expanded_by_failure=True,
            revalidation_round=1,
        )
        assert replanned["test_method"] == "PEN_TEST"
        assert replanned["planned_date"] == "2026-08-14"
        assert replanned["last_validated_at"] is None

        engagement = read_engagement(api, scenario["engagement_id"], lead_id)
        assert_partition_counts(engagement, 7, 0, 0)
        assert engagement["unvalidated_segment_count"] == 1
        assert engagement["posture"] == "RESTRICTED"
        terminal = _read_component(api, scenario["terminal_ids"]["pos-01"], lead_id)
        assert terminal["scope_class"] == "CDE"
        assert terminal["declared_scope_class"] == "OUT_OF_SCOPE"

    def test_the_pass_on_the_second_visit_reverses_the_first_verdict(self, api):
        """A validated boundary hands the zone and its terminals back their classes.

        PRD: A `PASS` verdict moves the zone `TEST_PLANNED → VALIDATED`, stamps
        `last_validated_at` from the logical clock and sets the zone's
        `effective_class` back to its own declared `segment_class`.

        Design: Difficulty/non_linear_state_machine/segment_fail_revalidation_cycle_restores_scope
        """
        scenario = _store_zone_awaiting_verdict(api)
        lead_id = scenario["lead_id"]
        store_id = scenario["store_id"]
        planned_version = scenario["store"]["version"]

        record_verdict(
            api,
            store_id,
            lead_id,
            outcome="FAIL",
            note="Store VLAN reached the cardholder network over the management path.",
        )
        _replan_segmentation(api, store_id, lead_id)
        validated = record_verdict(
            api,
            store_id,
            lead_id,
            outcome="PASS",
            note="Management path removed; the store VLAN is isolated.",
        )

        assert_segment_state(
            validated,
            segmentation_status="VALIDATED",
            effective_class="OUT_OF_SCOPE",
            segment_class="OUT_OF_SCOPE",
            scope_expanded_by_failure=False,
            revalidation_round=1,
        )
        assert_same_instant(validated["last_validated_at"], CLOCK_DEFAULT)
        # Three writes landed on the zone: the failure, the re-plan and the pass.
        assert_version_bumped_by(planned_version, validated["version"], 3)

        for hostname in POS_HOSTNAMES:
            terminal = _read_component(api, scenario["terminal_ids"][hostname], lead_id)
            assert terminal["scope_class"] == "OUT_OF_SCOPE"
            assert terminal["declared_scope_class"] == "OUT_OF_SCOPE"
        engagement = read_engagement(api, scenario["engagement_id"], lead_id)
        assert_partition_counts(engagement, 3, 0, 4)
        assert engagement["unvalidated_segment_count"] == 0
        assert engagement["posture"] == "OPEN"

    def test_the_zone_may_cycle_twice_and_the_round_counter_never_resets(self, api):
        """Two round trips are counted, and the validated zone accepts no third.

        PRD: A zone may cycle between `FAILED` and `TEST_PLANNED` any number of
        times, and `revalidation_round` counts the round trips.

        Design: Difficulty/non_linear_state_machine/segment_fail_revalidation_cycle_restores_scope
        """
        scenario = _store_zone_awaiting_verdict(api)
        lead_id = scenario["lead_id"]
        store_id = scenario["store_id"]

        record_verdict(api, store_id, lead_id, outcome="FAIL", note="Flat network.")
        first_replan = _replan_segmentation(
            api, store_id, lead_id, test_method="PEN_TEST", planned_date="2026-08-14"
        )
        assert_segment_state(
            first_replan, segmentation_status="TEST_PLANNED", revalidation_round=1
        )

        record_verdict(
            api, store_id, lead_id, outcome="FAIL", note="The path is still reachable."
        )
        second_replan = _replan_segmentation(
            api,
            store_id,
            lead_id,
            test_method="CONFIG_REVIEW",
            planned_date="2026-08-20",
        )
        assert_segment_state(
            second_replan,
            segmentation_status="TEST_PLANNED",
            effective_class="CDE",
            scope_expanded_by_failure=True,
            revalidation_round=2,
        )
        assert second_replan["test_method"] == "CONFIG_REVIEW"
        assert second_replan["planned_date"] == "2026-08-20"

        validated = record_verdict(
            api, store_id, lead_id, outcome="PASS", note="Isolation finally proven."
        )
        assert_segment_state(
            validated,
            segmentation_status="VALIDATED",
            effective_class="OUT_OF_SCOPE",
            scope_expanded_by_failure=False,
            revalidation_round=2,
        )

        # A proven boundary is the end of the road: it cannot re-enter testing.
        refused = api.request_remediation_revalidation(
            store_id,
            remediation_revalidation_payload(planned_date="2026-08-26"),
            make_lead_headers(lead_id),
        )
        validate_error(refused, ERR_INVALID_SEGMENT_STATE, 409)
        held = _read_segment(api, store_id, lead_id)
        assert_segment_state(
            held, segmentation_status="VALIDATED", revalidation_round=2
        )
        assert held["version"] == validated["version"]


class TestRequirementDimensionsDivergeAfterRemediation:
    """The testing dimension returns from a reopen; the gap dimension does not."""

    def test_reopening_an_in_place_requirement_opens_a_gap_of_its_own(self, api):
        """The reopen drives both dimensions at once and mints a fresh gap.

        PRD: **First**, `test_status` moves `IN_PLACE → IN_TESTING`, `reopen_count`
        increments by 1, and `remediation_status` moves to `GAP_OPEN` — from `NONE`
        on a requirement that had never been gapped, or from `GAP_REMEDIATED` on one
        that had been remediated once already.

        Design: Difficulty/non_linear_state_machine/requirement_parallel_dimensions_diverge_after_remediation
        """
        scenario = _two_in_place_requirements(api)
        lead_id = scenario["lead_id"]
        engagement_id = scenario["engagement_id"]
        requirement_a_id = scenario["requirement_id"]

        before = read_engagement(api, engagement_id, lead_id)
        assert before["open_gap_count"] == 0
        assert_percentage(before["as_found_compliance_percentage"], 100.00)
        assert_percentage(before["as_attested_compliance_percentage"], 100.00)

        reopened = _reopen(api, requirement_a_id, lead_id)

        assert_requirement_dimensions(
            reopened, test_status="IN_TESTING", remediation_status="GAP_OPEN"
        )
        assert reopened["reopen_count"] == 1

        item = _open_item_of(api, engagement_id, requirement_a_id, lead_id)
        assert item["source"] == "REQUIREMENT_REOPEN"
        assert item["status"] == "OPEN"
        # Family R1 carries 3 risk points, which is the medium band.
        assert item["severity"] == "MEDIUM"
        assert item["requirement_assessment_id"] == requirement_a_id
        assert item["engagement_id"] == engagement_id
        assert item["source_scan_finding_id"] is None
        assert item["owner_reference"] is None
        assert item["due_date"] is None
        assert item["retest_count"] == 0

        engagement = read_engagement(api, engagement_id, lead_id)
        assert engagement["open_gap_count"] == 1
        assert engagement["posture"] == "RESTRICTED"
        assert_percentage(engagement["as_found_compliance_percentage"], 50.00)
        assert_percentage(engagement["as_attested_compliance_percentage"], 50.00)

        untouched = validate_success(
            api.get_requirement_assessment(
                scenario["requirement_b_id"], make_lead_headers(lead_id)
            )
        )
        assert_requirement_dimensions(
            untouched, test_status="IN_PLACE", remediation_status="NONE"
        )

    def test_a_passing_retest_returns_only_the_testing_dimension(self, api):
        """The closed gap leaves its permanent mark on the remediation dimension.

        PRD: **Second**, because this was the requirement's last item not yet in a
        closed state — that is, because the requirement now has no item left whose
        `status` is `OPEN`, `IN_PROGRESS` or `RETEST_FAILED` — the parent requirement
        moves `remediation_status` `GAP_OPEN → GAP_REMEDIATED` and `test_status`
        `IN_TESTING → IN_PLACE`.

        Design: Difficulty/non_linear_state_machine/requirement_parallel_dimensions_diverge_after_remediation
        """
        scenario = _two_in_place_requirements(api)
        lead_id = scenario["lead_id"]
        lead_headers = make_lead_headers(lead_id)
        engagement_id = scenario["engagement_id"]
        requirement_a_id = scenario["requirement_id"]

        _reopen(api, requirement_a_id, lead_id)
        item = _open_item_of(api, engagement_id, requirement_a_id, lead_id)
        assigned = ok(
            api.assign_remediation_item(item["id"], assign_payload(), lead_headers)
        )
        assert assigned["status"] == "IN_PROGRESS"
        assert assigned["owner_reference"] == "Client Network Team"
        assert assigned["due_date"] == "2026-08-20"

        retested = ok(
            api.retest_remediation_item(item["id"], retest_payload(), lead_headers)
        )

        assert retested["status"] == "RETEST_PASSED"
        assert retested["retest_count"] == 1
        assert_same_instant(retested["closed_at"], CLOCK_DEFAULT)

        requirement_a = validate_success(
            api.get_requirement_assessment(requirement_a_id, lead_headers)
        )
        assert_requirement_dimensions(
            requirement_a, test_status="IN_PLACE", remediation_status="GAP_REMEDIATED"
        )
        assert requirement_a["reopen_count"] == 1
        # Evidence is never edited, so the file that supported the original
        # conclusion still supports the restored one.
        assert requirement_a["evidence_item_count"] == 3
        assert requirement_a["evidence_completeness"] is True

        requirement_b = validate_success(
            api.get_requirement_assessment(scenario["requirement_b_id"], lead_headers)
        )
        assert_requirement_dimensions(
            requirement_b, test_status="IN_PLACE", remediation_status="NONE"
        )
        assert_version_unchanged(
            scenario["requirement_b"]["version"], requirement_b["version"]
        )
        engagement = read_engagement(api, engagement_id, lead_id)
        assert engagement["open_gap_count"] == 0
        assert engagement["posture"] == "OPEN"

    def test_the_two_percentages_part_company_over_the_remediated_row(self, api):
        """Both requirements read in place, yet only one was in place all along.

        PRD: The `AS_FOUND` numerator counts the applicable requirements whose
        `test_status` is `IN_PLACE` *and* whose `remediation_status` is `NONE` — a
        requirement that was ever gapped is excluded from it forever, even after a
        successful retest restored it.

        Design: Difficulty/non_linear_state_machine/requirement_parallel_dimensions_diverge_after_remediation
        """
        scenario = _two_in_place_requirements(api)
        lead_id = scenario["lead_id"]
        lead_headers = make_lead_headers(lead_id)
        engagement_id = scenario["engagement_id"]
        requirement_a_id = scenario["requirement_id"]

        _reopen(api, requirement_a_id, lead_id)
        item = _open_item_of(api, engagement_id, requirement_a_id, lead_id)
        ok(api.assign_remediation_item(item["id"], assign_payload(), lead_headers))
        ok(api.retest_remediation_item(item["id"], retest_payload(), lead_headers))

        engagement = read_engagement(api, engagement_id, lead_id)
        assert engagement["applicable_requirement_count"] == 2
        assert_percentage(engagement["as_found_compliance_percentage"], 50.00)
        assert_percentage(engagement["as_attested_compliance_percentage"], 100.00)

        summary = validate_success(api.get_engagement_summary(engagement_id, lead_headers))
        assert_percentage(summary["as_found_compliance_percentage"], 50.00)
        assert_percentage(summary["as_attested_compliance_percentage"], 100.00)

        rows = validate_success(
            api.list_requirement_assessments(
                lead_headers, {"engagement_id": engagement_id, "test_status": "IN_PLACE"}
            )
        )
        assert len(rows) == 2
        remediated = find_row(rows, remediation_status="GAP_REMEDIATED")
        never_gapped = find_row(rows, remediation_status="NONE")
        assert remediated["id"] == requirement_a_id
        assert never_gapped["id"] == scenario["requirement_b_id"]


class TestScopePartitionConservedAcrossTheVerdictCycle:
    """Seven inventory rows stay seven, whichever way the boundary is decided."""

    def test_the_failure_moves_the_terminals_without_changing_the_inventory(self, api):
        """Four terminals leave the out-of-scope count and enter the cardholder count.

        PRD: The partition is conserved: the three counts always add up to the total
        number of component rows on the engagement, so a component that leaves one
        count enters exactly one other.

        Design: Difficulty/compensating_invariant/scope_partition_conserved_across_segment_fail_and_revalidation
        """
        scenario = _store_zone_awaiting_verdict(api)
        lead_id = scenario["lead_id"]
        lead_headers = make_lead_headers(lead_id)
        engagement_id = scenario["engagement_id"]

        assert_total_count(
            api.list_system_components(lead_headers, {"engagement_id": engagement_id}), 7
        )
        baseline = read_engagement(api, engagement_id, lead_id)
        assert_partition_counts(baseline, 3, 0, 4)
        assert baseline["in_scope_component_count"] == 3

        record_verdict(
            api,
            scenario["store_id"],
            lead_id,
            outcome="FAIL",
            note="Store VLAN reached the cardholder network over the management path.",
        )

        after = read_engagement(api, engagement_id, lead_id)
        assert_partition_counts(after, 7, 0, 0)
        assert after["in_scope_component_count"] == 7
        assert after["unvalidated_segment_count"] == 1
        assert after["posture"] == "RESTRICTED"
        assert_total_count(
            api.list_system_components(lead_headers, {"engagement_id": engagement_id}), 7
        )
        assert_total_count(
            api.list_system_components(
                lead_headers, {"engagement_id": engagement_id, "scope_class": "CDE"}
            ),
            7,
        )
        assert_total_count(
            api.list_system_components(
                lead_headers,
                {"engagement_id": engagement_id, "declared_scope_class": "OUT_OF_SCOPE"},
            ),
            4,
        )
        terminal = _read_component(api, scenario["terminal_ids"]["pos-01"], lead_id)
        assert terminal["scope_class"] == "CDE"
        assert terminal["declared_scope_class"] == "OUT_OF_SCOPE"
        host = _read_component(api, scenario["component_ids"]["app-01"], lead_id)
        assert host["scope_class"] == "CDE"
        assert host["declared_scope_class"] == "CDE"

    def test_the_compensating_pass_restores_the_literal_pre_failure_counts(self, api):
        """The cardholder count comes back to the exact number it left behind.

        PRD: First, a `FAILED` verdict and the compensating `PASS` verdict that later
        reverses it are exact mirrors: after the `PASS`, `cde_component_count` returns
        to the literal value it held immediately before the failure.

        Design: Difficulty/compensating_invariant/scope_partition_conserved_across_segment_fail_and_revalidation
        """
        scenario = _store_zone_awaiting_verdict(api)
        lead_id = scenario["lead_id"]
        lead_headers = make_lead_headers(lead_id)
        engagement_id = scenario["engagement_id"]
        store_id = scenario["store_id"]

        baseline = read_engagement(api, engagement_id, lead_id)
        baseline_cde = baseline["cde_component_count"]
        assert baseline_cde == 3

        record_verdict(api, store_id, lead_id, outcome="FAIL", note="Flat network.")
        expanded = read_engagement(api, engagement_id, lead_id)
        assert expanded["cde_component_count"] == 7

        _replan_segmentation(api, store_id, lead_id)
        record_verdict(
            api,
            store_id,
            lead_id,
            outcome="PASS",
            note="Shared management path removed and re-tested; isolation is proven.",
        )

        restored = read_engagement(api, engagement_id, lead_id)
        assert restored["cde_component_count"] == baseline_cde
        assert_partition_counts(restored, 3, 0, 4)
        assert restored["in_scope_component_count"] == 3
        assert restored["unvalidated_segment_count"] == 0
        assert restored["posture"] == "OPEN"
        assert_total_count(
            api.list_system_components(
                lead_headers,
                {"engagement_id": engagement_id, "scope_class": "OUT_OF_SCOPE"},
            ),
            4,
        )
        assert_total_count(
            api.list_system_components(
                lead_headers, {"engagement_id": engagement_id, "scope_class": "CDE"}
            ),
            3,
        )

    def test_the_cascades_never_touch_the_client_s_own_assertions(self, api):
        """Every step moves effective classes only, and the sum of seven never breaks.

        PRD: Second, no cascade ever edits a zone's own declared `segment_class` or a
        component's `declared_scope_class`; the cascade moves `effective_class` and
        `scope_class` only, so the client's original assertion is always still
        readable next to the assessor's finding.

        Design: Difficulty/compensating_invariant/scope_partition_conserved_across_segment_fail_and_revalidation
        """
        scenario = _store_zone_awaiting_verdict(api)
        lead_id = scenario["lead_id"]
        engagement_id = scenario["engagement_id"]
        store_id = scenario["store_id"]
        cde_zone_id = scenario["segment_id"]
        declared = {
            hostname: _read_component(api, component_id, lead_id)["declared_scope_class"]
            for hostname, component_id in scenario["terminal_ids"].items()
        }

        record_verdict(api, store_id, lead_id, outcome="FAIL", note="Flat network.")
        assert_partition_counts(read_engagement(api, engagement_id, lead_id), 7, 0, 0)

        replanned = _replan_segmentation(api, store_id, lead_id)
        # Re-planning a test proves nothing, so the partition must not move yet.
        assert_segment_state(
            replanned,
            segmentation_status="TEST_PLANNED",
            segment_class="OUT_OF_SCOPE",
            effective_class="CDE",
            revalidation_round=1,
        )
        assert_partition_counts(read_engagement(api, engagement_id, lead_id), 7, 0, 0)

        validated = record_verdict(
            api, store_id, lead_id, outcome="PASS", note="Isolation is proven."
        )
        assert_segment_state(
            validated, segment_class="OUT_OF_SCOPE", effective_class="OUT_OF_SCOPE"
        )
        assert_partition_counts(read_engagement(api, engagement_id, lead_id), 3, 0, 4)

        for hostname, component_id in scenario["terminal_ids"].items():
            terminal = _read_component(api, component_id, lead_id)
            assert terminal["declared_scope_class"] == declared[hostname]
            assert terminal["declared_scope_class"] == "OUT_OF_SCOPE"
            assert terminal["scope_class"] == "OUT_OF_SCOPE"

        # The cardholder zone was never named in any of the three verdicts.
        cde_zone = _read_segment(api, cde_zone_id, lead_id)
        assert_segment_state(
            cde_zone,
            segmentation_status="VALIDATED",
            segment_class="CDE",
            effective_class="CDE",
            scope_expanded_by_failure=False,
        )
        assert cde_zone["version"] == scenario["segment"]["version"]
