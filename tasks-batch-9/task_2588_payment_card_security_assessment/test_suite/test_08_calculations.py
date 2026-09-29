"""Derived numbers: facility selection, evidence coverage, the finding ledger,
the compliance denominator and remediation severity."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers.api_errors import (
    ERR_EVIDENCE_INCOMPLETE,
    ERR_REQUIREMENT_TESTING_INCOMPLETE,
)
from test_helpers.assertions import (
    assert_coverage_ratio,
    assert_cvss,
    assert_finding_ledger_identity,
    assert_money,
    assert_percentage,
    assert_requirement_dimensions,
    assert_same_instant,
    assert_stratum_allocations,
    assert_total_count,
    find_row,
)
from test_helpers.constants import CLOCK_DEFAULT, RISK_POINTS
from test_helpers.factories import (
    conclusion_payload,
    dispute_decision_payload,
    dispute_payload,
    evidence_payload,
    roc_payload,
)
from test_helpers.fixtures import (
    Scenario,
    add_complete_evidence,
    add_component,
    add_evidence,
    build_approved_vendor_with_cycle,
    build_scoping_engagement,
    complete_cycle,
    conclude,
    declare_segment,
    draw_plan,
    open_requirement,
    publish_finding,
    read_engagement,
    requirement_concluded,
    start_testing,
    validated_segment,
)
from test_helpers.test_users import make_asv_vendor_headers, make_lead_headers


def _three_facility_inventory(api) -> Scenario:
    """One payment application in a data centre and one terminal per retail store.

    The terminal created last sits at the byte-wise highest facility name, and the
    data centre outranks both stores on the descriptive review-priority rank, so
    neither insertion order nor facility category can be mistaken for the
    selector's own ordering.
    """
    scenario = build_scoping_engagement(api)
    lead_id = scenario["lead_id"]
    engagement_id = scenario["engagement_id"]
    segment = validated_segment(api, engagement_id, lead_id, name="CDE-CORE")
    scenario["segment_id"] = segment["id"]
    components = {}
    components["pay-01"] = add_component(
        api,
        engagement_id,
        lead_id,
        segment["id"],
        "pay-01",
        component_type="APPLICATION",
        function_class="PAYMENT_APPLICATION",
        stores_chd=True,
        facility_name="DC-EAST",
        facility_type="DATA_CENTER",
    )
    components["pos-01"] = add_component(
        api,
        engagement_id,
        lead_id,
        segment["id"],
        "pos-01",
        component_type="POS_TERMINAL",
        function_class="PAYMENT_APPLICATION",
        stores_chd=False,
        facility_name="RETAIL-12",
        facility_type="RETAIL_STORE",
    )
    components["pos-02"] = add_component(
        api,
        engagement_id,
        lead_id,
        segment["id"],
        "pos-02",
        component_type="POS_TERMINAL",
        function_class="PAYMENT_APPLICATION",
        stores_chd=False,
        facility_name="RETAIL-40",
        facility_type="RETAIL_STORE",
    )
    scenario["components"] = components
    scenario["component_ids"] = {name: row["id"] for name, row in components.items()}
    return scenario


def _engagement_with_scan_cycle(api) -> Scenario:
    """A scoping engagement with one host and one quarterly window open on it."""
    scenario = build_scoping_engagement(api)
    segment = declare_segment(
        api, scenario["engagement_id"], scenario["lead_id"], "CDE-CORE"
    )
    scenario["segment_id"] = segment["id"]
    component = add_component(
        api,
        scenario["engagement_id"],
        scenario["lead_id"],
        segment["id"],
        "pay-01",
        component_type="APPLICATION",
        function_class="PAYMENT_APPLICATION",
        stores_chd=True,
    )
    scenario["component"] = component
    scenario["component_id"] = component["id"]
    return build_approved_vendor_with_cycle(api, scenario)


def _publish_three_scores(api, scenario: Scenario) -> Scenario:
    """Publish one finding just under the high-severity mark and two at or over it."""
    scenario["finding_low"] = publish_finding(
        api,
        scenario["cycle_id"],
        scenario["vendor_id"],
        scenario["component_id"],
        plugin_reference="PLG-3900",
        cvss_score=3.9,
    )
    scenario["finding_at"] = publish_finding(
        api,
        scenario["cycle_id"],
        scenario["vendor_id"],
        scenario["component_id"],
        plugin_reference="PLG-4000",
        cvss_score=4.0,
    )
    scenario["finding_over"] = publish_finding(
        api,
        scenario["cycle_id"],
        scenario["vendor_id"],
        scenario["component_id"],
        plugin_reference="PLG-4100",
        cvss_score=4.1,
    )
    return scenario


class TestFacilitySampleSelection:
    """The facility sample is chosen by name and it re-prices the engagement."""

    def test_facility_names_are_taken_in_ascending_order_and_price_the_fee(self, api):
        """Two of three facilities are drawn, and they are the two lowest names.

        PRD: `sampled_facility_names` then holds the first `facility_sample_size`
        distinct facility names taken in ascending byte-wise order of
        `facility_name`, and that ordering is the only one ever used: never row
        identifier, never insertion order, never facility category.

        Design: Corner/calculations/calc_facility_sample_selection_orders_names_ascending_and_reprices_the_fee
        """
        scenario = _three_facility_inventory(api)
        lead_id = scenario["lead_id"]
        engagement_id = scenario["engagement_id"]

        plan = draw_plan(
            api,
            engagement_id,
            lead_id,
            plan_variant="FINAL",
            justification_text="One facility per store format plus the primary data centre.",
        )

        # Thirty-four hundredths of three facilities rounds up to two, which is
        # under the population itself.
        assert plan["facility_population_count"] == 3
        assert plan["facility_sample_size"] == 2
        assert plan["sampled_facility_names"] == ["DC-EAST", "RETAIL-12"]

        assert plan["eligible_component_count"] == 3
        assert_stratum_allocations(
            plan,
            {
                "SERVER": 0,
                "NETWORK_DEVICE": 0,
                "POS_TERMINAL": 2,
                "APPLICATION": 1,
                "DATABASE": 0,
            },
        )
        assert plan["component_sample_size"] == 3
        assert_coverage_ratio(plan["coverage_ratio"], 1.0000)
        assert plan["status"] == "ACTIVE"

        # 160 baseline hours, 12 per sampled host and 30 per sampled facility, with
        # no accepted worksheet yet; the level-one surcharge then carries the
        # subtotal into the three-percent tier.
        engagement = read_engagement(api, engagement_id, lead_id)
        assert engagement["estimated_hours"] == 256
        assert_money(engagement["assessment_fee_total"], 67046.40)
        assert engagement["active_sampling_plan_id"] == plan["id"]


class TestEvidenceCompletenessCountsSufficientRecordsOnly:
    """An insufficient artefact is filed but discharges no testing technique."""

    def test_an_insufficient_observation_blocks_the_in_place_conclusion(
        self, api, fieldwork_engagement
    ):
        """Three artefacts across three techniques still fail the coverage gate.

        PRD: `evidence_completeness` is true only when both halves hold:
        `evidence_item_count` has reached or passed `testing_procedure_count`, and
        `evidence_type_coverage` contains all three of `DOCUMENT_REVIEW`,
        `INTERVIEW` and `OBSERVATION`.

        Design: Corner/calculations/calc_evidence_completeness_ignores_an_insufficient_item
        """
        lead_id = fieldwork_engagement["lead_id"]
        lead_headers = make_lead_headers(lead_id)
        engagement_id = fieldwork_engagement["engagement_id"]
        requirement = open_requirement(
            api,
            engagement_id,
            lead_id,
            requirement_ref="1.2.1",
            requirement_family="R1",
            testing_procedure_count=3,
        )
        start_testing(api, requirement["id"], lead_id)
        add_evidence(
            api,
            requirement["id"],
            lead_id,
            evidence_payload(
                evidence_type="DOCUMENT_REVIEW",
                procedure_ref="1.2.1.a",
                sufficiency="SUFFICIENT",
                note="Firewall standard reviewed.",
            ),
        )
        add_evidence(
            api,
            requirement["id"],
            lead_id,
            evidence_payload(
                evidence_type="INTERVIEW",
                procedure_ref="1.2.1.b",
                sufficiency="SUFFICIENT",
                interviewee_name="Priya Raman",
                interviewee_title="Network Engineering Manager",
            ),
        )
        # The screen share dropped, so the observation proves nothing on its own.
        add_evidence(
            api,
            requirement["id"],
            lead_id,
            evidence_payload(
                evidence_type="OBSERVATION",
                procedure_ref="1.2.1.c",
                sufficiency="INSUFFICIENT",
                component_id=fieldwork_engagement["component_ids"]["pay-01"],
                note="Screen share dropped before the ruleset was shown.",
            ),
        )

        before = validate_success(
            api.get_requirement_assessment(requirement["id"], lead_headers)
        )
        assert before["evidence_item_count"] == 3
        assert before["evidence_type_coverage"] == ["DOCUMENT_REVIEW", "INTERVIEW"]
        assert before["evidence_completeness"] is False

        refused = api.conclude_requirement(
            requirement["id"],
            conclusion_payload(conclusion="IN_PLACE"),
            lead_headers,
        )
        validate_error(refused, ERR_EVIDENCE_INCOMPLETE, 422)
        held = validate_success(
            api.get_requirement_assessment(requirement["id"], lead_headers)
        )
        assert_requirement_dimensions(
            held, test_status="IN_TESTING", remediation_status="NONE"
        )

        add_evidence(
            api,
            requirement["id"],
            lead_id,
            evidence_payload(
                evidence_type="OBSERVATION",
                procedure_ref="1.2.1.d",
                sufficiency="SUFFICIENT",
                component_id=fieldwork_engagement["component_ids"]["pay-02"],
                note="Ruleset observed live on the secondary node.",
            ),
        )
        complete = validate_success(
            api.get_requirement_assessment(requirement["id"], lead_headers)
        )
        assert complete["evidence_item_count"] == 4
        assert complete["evidence_type_coverage"] == [
            "DOCUMENT_REVIEW",
            "INTERVIEW",
            "OBSERVATION",
        ]
        assert complete["evidence_completeness"] is True

        concluded = conclude(
            api,
            requirement["id"],
            lead_id,
            conclusion="IN_PLACE",
            conclusion_rationale="Ruleset restricts inbound traffic to documented services.",
        )
        assert_requirement_dimensions(
            concluded, test_status="IN_PLACE", remediation_status="NONE"
        )
        assert (
            concluded["conclusion_rationale"]
            == "Ruleset restricts inbound traffic to documented services."
        )

        # The insufficient artefact is still on file: coverage filters it, the
        # ledger of records does not delete it.
        assert_total_count(
            api.list_evidence_items(
                lead_headers, {"requirement_assessment_id": requirement["id"]}
            ),
            4,
        )
        engagement = read_engagement(api, engagement_id, lead_id)
        assert engagement["applicable_requirement_count"] == 1
        assert_percentage(engagement["as_found_compliance_percentage"], 100.00)


class TestHighSeverityThresholdIsInclusive:
    """Four point zero counts as high; three point nine does not."""

    def test_the_ledger_counts_the_score_that_sits_exactly_on_the_mark(self, api):
        """A 3.9, a 4.0 and a 4.1 finding produce two high findings, not one.

        PRD: The threshold is inclusive at 4.0, so a 4.0 finding is
        `HIGH_OR_ABOVE` while a 3.9 finding is not.

        Design: Corner/calculations/calc_scan_finding_severity_at_the_inclusive_cvss_threshold
        """
        scenario = _publish_three_scores(api, _engagement_with_scan_cycle(api))
        lead_headers = make_lead_headers(scenario["lead_id"])

        low = scenario["finding_low"]
        assert_cvss(low["cvss_score"], 3.9)
        assert low["severity_class"] == "LOW"
        at_threshold = scenario["finding_at"]
        assert_cvss(at_threshold["cvss_score"], 4.0)
        assert at_threshold["severity_class"] == "HIGH_OR_ABOVE"
        over = scenario["finding_over"]
        assert_cvss(over["cvss_score"], 4.1)
        assert over["severity_class"] == "HIGH_OR_ABOVE"

        published = validate_success(
            api.get_scan_cycle(scenario["cycle_id"], lead_headers)
        )
        assert published["raw_high_finding_count"] == 2
        assert published["accepted_false_positive_count"] == 0
        assert published["effective_high_finding_count"] == 2
        assert published["open_dispute_count"] == 0
        assert_finding_ledger_identity(published)
        assert_same_instant(published["window_end"], "2026-09-29T00:00:00Z")

        closed = complete_cycle(api, scenario["cycle_id"], scenario["vendor_id"])

        assert closed["status"] == "FAILING"
        assert_same_instant(closed["scan_completed_at"], CLOCK_DEFAULT)
        assert closed["attestation_of_scan_compliance"] is False
        # A failing cycle inside the window confers no scan compliance at all.
        engagement = read_engagement(
            api, scenario["engagement_id"], scenario["lead_id"]
        )
        assert engagement["quarterly_scan_compliant"] is False


class TestEffectiveHighFindingsExcludeAcceptedFalsePositives:
    """Only an accepted false-positive claim leaves the effective count."""

    def test_the_ledger_stays_conserved_across_two_accepted_claims(self, api):
        """Each acceptance moves one finding across the ledger, never out of it.

        PRD: The ledger is conserved at every point in the dispute lifecycle:
        `raw_high_finding_count` always equals `effective_high_finding_count` plus
        `accepted_false_positive_count`.

        Design: Corner/calculations/calc_effective_high_finding_count_excludes_accepted_false_positives
        """
        scenario = _publish_three_scores(api, _engagement_with_scan_cycle(api))
        lead_id = scenario["lead_id"]
        lead_headers = make_lead_headers(lead_id)
        vendor_headers = make_asv_vendor_headers(scenario["vendor_id"])
        cycle_id = scenario["cycle_id"]
        complete_cycle(api, cycle_id, scenario["vendor_id"])

        disputed = validate_success(
            api.dispute_scan_finding(
                scenario["finding_at"]["id"],
                dispute_payload(
                    dispute_rationale="The plugin fingerprints a backported package version."
                ),
                lead_headers,
            )
        )
        assert disputed["dispute_status"] == "DISPUTED"
        after_dispute = validate_success(api.get_scan_cycle(cycle_id, lead_headers))
        assert after_dispute["open_dispute_count"] == 1
        assert after_dispute["status"] == "DISPUTE_OPEN"
        assert_finding_ledger_identity(after_dispute)

        validate_success(
            api.decide_scan_finding_dispute(
                scenario["finding_at"]["id"],
                dispute_decision_payload(
                    decision="ACCEPT",
                    decision_note="Backport confirmed against the vendor advisory.",
                ),
                vendor_headers,
            )
        )
        after_first = validate_success(api.get_scan_cycle(cycle_id, lead_headers))
        assert after_first["raw_high_finding_count"] == 2
        assert after_first["accepted_false_positive_count"] == 1
        assert after_first["effective_high_finding_count"] == 1
        assert after_first["open_dispute_count"] == 0
        assert_finding_ledger_identity(after_first)
        # One effective high finding still stands, so the quarter is not compliant.
        assert (
            read_engagement(api, scenario["engagement_id"], lead_id)[
                "quarterly_scan_compliant"
            ]
            is False
        )

        validate_success(
            api.dispute_scan_finding(
                scenario["finding_over"]["id"],
                dispute_payload(
                    dispute_rationale="The service is not reachable from the scanned interface."
                ),
                lead_headers,
            )
        )
        validate_success(
            api.decide_scan_finding_dispute(
                scenario["finding_over"]["id"],
                dispute_decision_payload(
                    decision="ACCEPT",
                    decision_note="Interface binding verified as loopback-only.",
                ),
                vendor_headers,
            )
        )
        after_second = validate_success(api.get_scan_cycle(cycle_id, lead_headers))
        assert after_second["raw_high_finding_count"] == 2
        assert after_second["accepted_false_positive_count"] == 2
        assert after_second["effective_high_finding_count"] == 0
        assert after_second["open_dispute_count"] == 0
        assert_finding_ledger_identity(after_second)
        assert after_second["status"] == "PASSING"
        assert (
            read_engagement(api, scenario["engagement_id"], lead_id)[
                "quarterly_scan_compliant"
            ]
            is True
        )

        # The low finding never entered the high-severity counters, and the two
        # accepted claims stay readable.
        low = validate_success(
            api.get_scan_finding(scenario["finding_low"]["id"], lead_headers)
        )
        assert low["dispute_status"] == "NONE"
        assert_total_count(
            api.list_scan_findings(
                lead_headers,
                {
                    "scan_cycle_id": cycle_id,
                    "dispute_status": "ACCEPTED_FALSE_POSITIVE",
                },
            ),
            2,
        )


class TestCompliancePercentagesCountApplicableRequirementsOnly:
    """A requirement ruled out of scope is not a failure and not a pass either."""

    def test_a_not_applicable_row_stays_out_of_the_denominator(
        self, api, fieldwork_engagement
    ):
        """One conclusion over two applicable rows reads 50.00, never 33.33.

        PRD: The denominator for both is `applicable_requirement_count`, the number
        of requirement assessments on the engagement whose `applicability` is
        `APPLICABLE`; rows created `NOT_APPLICABLE` never enter it.

        Design: Corner/calculations/calc_compliance_denominator_excludes_not_applicable_rows
        """
        lead_id = fieldwork_engagement["lead_id"]
        lead_headers = make_lead_headers(lead_id)
        engagement_id = fieldwork_engagement["engagement_id"]

        firewall = open_requirement(
            api,
            engagement_id,
            lead_id,
            requirement_ref="1.2.1",
            requirement_family="R1",
            testing_procedure_count=3,
        )
        hardening = open_requirement(
            api,
            engagement_id,
            lead_id,
            requirement_ref="2.2.1",
            requirement_family="R2",
            testing_procedure_count=2,
        )
        # Physical access is the landlord's control at this client, so the row is
        # ruled out of scope the moment it is opened.
        physical = open_requirement(
            api,
            engagement_id,
            lead_id,
            requirement_ref="9.1.1",
            requirement_family="R9",
            testing_procedure_count=4,
            applicability="NOT_APPLICABLE",
        )
        assert_requirement_dimensions(
            physical, test_status="NOT_APPLICABLE", remediation_status="NONE"
        )
        assert firewall["risk_points"] == RISK_POINTS["R1"]
        assert physical["risk_points"] == RISK_POINTS["R9"]

        start_testing(api, firewall["id"], lead_id)
        add_complete_evidence(
            api,
            firewall["id"],
            lead_id,
            "1.2.1",
            fieldwork_engagement["component_ids"]["pay-01"],
        )
        conclude(
            api,
            firewall["id"],
            lead_id,
            conclusion="IN_PLACE",
            conclusion_rationale="Ruleset restricts inbound traffic to documented services.",
        )

        engagement = read_engagement(api, engagement_id, lead_id)
        assert engagement["applicable_requirement_count"] == 2
        assert_percentage(engagement["as_found_compliance_percentage"], 50.00)
        assert_percentage(engagement["as_attested_compliance_percentage"], 50.00)

        # The untested hardening requirement is what holds the report back; the
        # out-of-scope row is not waiting on anybody.
        untouched = validate_success(
            api.get_requirement_assessment(hardening["id"], lead_headers)
        )
        assert_requirement_dimensions(
            untouched, test_status="NOT_STARTED", remediation_status="NONE"
        )
        refused = api.create_roc(engagement_id, roc_payload(), lead_headers)
        validate_error(refused, ERR_REQUIREMENT_TESTING_INCOMPLETE, 422)


class TestRemediationSeverityFollowsTheRequirementFamily:
    """The family's risk weight sets the severity, not the order of discovery."""

    def test_an_r3_gap_is_critical_while_an_r12_gap_is_low(
        self, api, fieldwork_engagement
    ):
        """Two gaps minted by the same cascade carry different severities.

        PRD: `severity` is derived from the parent requirement's `risk_points`:
        `CRITICAL` at 5 or more, `HIGH` at exactly 4, `MEDIUM` at exactly 3, and
        `LOW` at 2 or fewer.

        Design: Corner/calculations/calc_remediation_severity_derives_from_family_risk_points
        """
        lead_id = fieldwork_engagement["lead_id"]
        lead_headers = make_lead_headers(lead_id)
        engagement_id = fieldwork_engagement["engagement_id"]
        components = fieldwork_engagement["component_ids"]

        crypto = requirement_concluded(
            api,
            engagement_id,
            lead_id,
            requirement_ref="3.5.1",
            requirement_family="R3",
            observed_component_id=components["pay-01"],
            conclusion="NOT_IN_PLACE",
            testing_procedure_count=2,
            interviewee_name="Ana Duarte",
            interviewee_title="Cryptography Lead",
            conclusion_rationale="Key-rotation records are missing for two of the sampled hosts.",
        )
        policy = requirement_concluded(
            api,
            engagement_id,
            lead_id,
            requirement_ref="12.1.1",
            requirement_family="R12",
            observed_component_id=components["pay-02"],
            conclusion="NOT_IN_PLACE",
            testing_procedure_count=2,
            interviewee_name="Tom Bright",
            interviewee_title="Compliance Officer",
            conclusion_rationale="The policy has not been reviewed within the last twelve months.",
        )
        assert crypto["risk_points"] == 5
        assert policy["risk_points"] == 1
        assert_requirement_dimensions(
            crypto, test_status="NOT_IN_PLACE", remediation_status="GAP_OPEN"
        )
        assert_requirement_dimensions(
            policy, test_status="NOT_IN_PLACE", remediation_status="GAP_OPEN"
        )

        items = assert_total_count(
            api.list_remediation_items(lead_headers, {"engagement_id": engagement_id}),
            2,
        )
        critical = find_row(items, requirement_assessment_id=crypto["id"])
        assert critical["severity"] == "CRITICAL"
        assert critical["source"] == "REQUIREMENT_CONCLUSION"
        assert critical["status"] == "OPEN"
        low = find_row(items, requirement_assessment_id=policy["id"])
        assert low["severity"] == "LOW"
        assert low["source"] == "REQUIREMENT_CONCLUSION"
        assert low["status"] == "OPEN"
        for item in (critical, low):
            assert item["owner_reference"] is None
            assert item["due_date"] is None
            assert item["retest_count"] == 0
            assert item["source_scan_finding_id"] is None

        assert_total_count(
            api.list_remediation_items(
                lead_headers, {"engagement_id": engagement_id, "severity": "CRITICAL"}
            ),
            1,
        )
        assert_total_count(
            api.list_remediation_items(
                lead_headers, {"engagement_id": engagement_id, "severity": "LOW"}
            ),
            1,
        )

        engagement = read_engagement(api, engagement_id, lead_id)
        assert engagement["open_gap_count"] == 2
        assert engagement["posture"] == "RESTRICTED"
        assert_percentage(engagement["as_found_compliance_percentage"], 0.00)
        assert_percentage(engagement["as_attested_compliance_percentage"], 0.00)
