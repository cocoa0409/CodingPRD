"""Gates read from foreign rows, the ladder's safety rung and the two calendars."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers.api_errors import (
    ERR_ASSESSOR_CERTIFICATION_EXPIRED,
    ERR_ASSESSOR_WINDOW_CONFLICT,
    ERR_ENGAGEMENT_RESTRICTED,
    ERR_INDEPENDENCE_VIOLATION,
    ERR_SAMPLING_PLAN_STALE,
    ERR_SCAN_WINDOW_OVERLAP,
)
from test_helpers.assertions import (
    assert_coverage_ratio,
    assert_money,
    assert_partition_counts,
    assert_percentage,
    assert_requirement_dimensions,
    assert_same_instant,
    assert_segment_state,
    assert_stratum_allocations,
    assert_total_count,
    assert_version_bumped_by,
    assert_version_unchanged,
)
from test_helpers.constants import (
    FACILITY_RETAIL_12,
    LEAD_CERT_EXPIRES,
    LEAD_EMAIL,
    LEAD_NAME,
    QA_EMAIL,
    QA_NAME,
)
from test_helpers.factories import (
    conclusion_payload,
    document_evidence,
    engagement_payload,
    interview_evidence,
    observation_evidence,
    qa_review_payload,
    roc_payload,
    scan_cycle_payload,
)
from test_helpers.fixtures import (
    Scenario,
    add_complete_evidence,
    add_component,
    add_evidence,
    build_fieldwork_engagement,
    build_registry,
    conclude,
    create_roc,
    created,
    declare_segment,
    draw_plan,
    lock_scope,
    open_engagement,
    open_requirement,
    plan_segmentation,
    qa_submit,
    read_engagement,
    record_verdict,
    register_assessor,
    register_vendor,
    schedule_scan_cycle,
    set_clock,
    start_testing,
    validated_segment,
)
from test_helpers.test_users import (
    make_assessor_headers,
    make_lead_headers,
    make_qa_reviewer_headers,
)

# The reviewer's certificate runs out mid-assessment; the clock is later moved
# past that instant so her standing turns while the report waits for review.
REVIEWER_CERT_EXPIRES = "2026-09-15T00:00:00Z"
CLOCK_AFTER_REVIEWER_LAPSE = "2026-10-01T00:00:00Z"

CDE_HOSTS = (
    ("app-01", "SERVER", "SECURITY_SERVICE", False),
    ("pay-01", "APPLICATION", "PAYMENT_APPLICATION", True),
    ("pay-02", "APPLICATION", "PAYMENT_APPLICATION", True),
)


def _roc_in_qa_reviewed_by_its_own_collector(api) -> Scenario:
    """A report awaiting review by the very reviewer who interviewed the client.

    The nominated reviewer is qualified and, at the startup clock, currently
    certified — her certificate only runs out on 2026-09-15 — but she personally
    appended the interview record on requirement 1.2.1.
    """
    lead = register_assessor(
        api, LEAD_NAME, LEAD_EMAIL, LEAD_CERT_EXPIRES, qa_qualified=False
    )
    reviewer = register_assessor(
        api, QA_NAME, QA_EMAIL, REVIEWER_CERT_EXPIRES, qa_qualified=True
    )
    lead_id = lead["id"]
    reviewer_id = reviewer["id"]
    engagement = open_engagement(api, lead_id, qa_reviewer_id=reviewer_id)
    engagement_id = engagement["id"]
    segment = validated_segment(api, engagement_id, lead_id, name="CDE-CORE")
    components = {}
    for hostname, component_type, function_class, stores_chd in CDE_HOSTS:
        components[hostname] = add_component(
            api,
            engagement_id,
            lead_id,
            segment["id"],
            hostname,
            component_type=component_type,
            function_class=function_class,
            stores_chd=stores_chd,
        )
    draw_plan(api, engagement_id, lead_id, plan_variant="FINAL")
    lock_scope(api, engagement_id, lead_id)
    requirement = open_requirement(
        api,
        engagement_id,
        lead_id,
        requirement_ref="1.2.1",
        requirement_family="R1",
        testing_procedure_count=3,
    )
    start_testing(api, requirement["id"], lead_id)
    add_evidence(api, requirement["id"], lead_id, document_evidence("1.2.1.a"))
    reviewer_evidence = created(
        api.create_evidence_item(
            requirement["id"],
            interview_evidence(
                "1.2.1.b",
                interviewee_name="R. Ortiz",
                interviewee_title="Network Manager",
            ),
            make_assessor_headers(reviewer_id),
        )
    )
    add_evidence(
        api,
        requirement["id"],
        lead_id,
        observation_evidence("1.2.1.c", components["app-01"]["id"]),
    )
    conclude(api, requirement["id"], lead_id, conclusion="IN_PLACE")
    roc = create_roc(api, engagement_id, lead_id)
    roc = qa_submit(api, roc["id"], lead_id)
    return Scenario(
        lead_id=lead_id,
        reviewer_id=reviewer_id,
        reviewer_headers=make_qa_reviewer_headers(reviewer_id),
        engagement_id=engagement_id,
        requirement_id=requirement["id"],
        reviewer_evidence=reviewer_evidence,
        roc=roc,
        roc_id=roc["id"],
    )


def _fieldwork_with_pending_store_zone(api) -> Scenario:
    """A fully evidenced requirement beside a store zone whose test is pending.

    Requirement 1.2.1 already carries all three techniques against an in-sample
    payment application, so nothing local stands between it and a conclusion. The
    store zone the client declared out of scope holds one terminal and is waiting
    on the configuration review booked against it.
    """
    scenario = build_fieldwork_engagement(api)
    lead_id = scenario["lead_id"]
    engagement_id = scenario["engagement_id"]
    requirement = open_requirement(
        api,
        engagement_id,
        lead_id,
        requirement_ref="1.2.1",
        requirement_family="R1",
        testing_procedure_count=3,
    )
    start_testing(api, requirement["id"], lead_id)
    add_complete_evidence(
        api,
        requirement["id"],
        lead_id,
        "1.2.1",
        scenario["component_ids"]["pay-01"],
    )
    store = declare_segment(
        api, engagement_id, lead_id, "STORE-POS", segment_class="OUT_OF_SCOPE"
    )
    terminal = add_component(
        api,
        engagement_id,
        lead_id,
        store["id"],
        "pos-01",
        component_type="POS_TERMINAL",
        function_class="PAYMENT_APPLICATION",
        facility_name=FACILITY_RETAIL_12,
        facility_type="RETAIL_STORE",
    )
    plan_segmentation(
        api, store["id"], lead_id, test_method="CONFIG_REVIEW", planned_date="2026-08-12"
    )
    scenario["requirement"] = requirement
    scenario["requirement_id"] = requirement["id"]
    scenario["store_segment_id"] = store["id"]
    scenario["terminal_id"] = terminal["id"]
    return scenario


class TestIndependenceOutranksLapsedCertification:
    """The reviewer's own evidence disqualifies her before her dates are read."""

    def test_reviewer_who_collected_evidence_is_refused_while_still_certified(self, api):
        """A currently certified reviewer is turned away on independence alone.

        PRD: Independence is the point of the whole exercise and is checked in two
        parts: the acting reviewer must not be the engagement's `lead_assessor_id`,
        and no evidence item of this engagement may carry that individual as its
        `collector_assessor_id`.

        Design: Difficulty/priority_pair_validation_conflict/independence_violation_beats_lapsed_certification_on_qa_review
        """
        scenario = _roc_in_qa_reviewed_by_its_own_collector(api)
        reviewer_headers = scenario["reviewer_headers"]
        standing = validate_success(
            api.get_assessor(scenario["reviewer_id"], reviewer_headers)
        )
        assert standing["certification_status"] == "ACTIVE"

        refused = api.qa_review_roc(
            scenario["roc_id"], qa_review_payload(decision="APPROVE"), reviewer_headers
        )
        validate_error(refused, ERR_INDEPENDENCE_VIOLATION, 422)

        collected = validate_success(
            api.list_evidence_items(
                reviewer_headers,
                {
                    "engagement_id": scenario["engagement_id"],
                    "collector_assessor_id": scenario["reviewer_id"],
                },
            )
        )
        assert [row["id"] for row in collected] == [
            scenario["reviewer_evidence"]["id"]
        ]
        held = validate_success(api.get_roc(scenario["roc_id"], reviewer_headers))
        assert held["status"] == "IN_QA"
        assert held["qa_decision_note"] is None
        assert_version_unchanged(scenario["roc"]["version"], held["version"])
        engagement = read_engagement(
            api, scenario["engagement_id"], scenario["lead_id"]
        )
        assert engagement["status"] == "REPORTING"
        assert engagement["posture"] == "FROZEN"

    def test_the_independence_breach_still_answers_once_the_certificate_runs_out(
        self, api
    ):
        """Moving the clock past the certificate never changes the answer.

        PRD: On a report quality-assurance review, an independence breach surfaces
        from rung 11 even when the acting reviewer's certification has also lapsed —
        `ERR_INDEPENDENCE_VIOLATION` wins over `ERR_ASSESSOR_CERTIFICATION_EXPIRED`.

        Design: Difficulty/priority_pair_validation_conflict/independence_violation_beats_lapsed_certification_on_qa_review
        """
        scenario = _roc_in_qa_reviewed_by_its_own_collector(api)
        reviewer_headers = scenario["reviewer_headers"]
        while_certified = api.qa_review_roc(
            scenario["roc_id"], qa_review_payload(decision="APPROVE"), reviewer_headers
        )
        validate_error(while_certified, ERR_INDEPENDENCE_VIOLATION, 422)

        set_clock(api, CLOCK_AFTER_REVIEWER_LAPSE)
        lapsed = validate_success(
            api.get_assessor(scenario["reviewer_id"], reviewer_headers)
        )
        assert lapsed["certification_status"] == "LAPSED"

        once_lapsed = api.qa_review_roc(
            scenario["roc_id"], qa_review_payload(decision="APPROVE"), reviewer_headers
        )
        validate_error(once_lapsed, ERR_INDEPENDENCE_VIOLATION, 422)
        assert (
            once_lapsed.json()["data"]["error_id"] != ERR_ASSESSOR_CERTIFICATION_EXPIRED
        )

        held = validate_success(api.get_roc(scenario["roc_id"], reviewer_headers))
        assert held["status"] == "IN_QA"
        assert held["qa_decision_note"] is None
        assert_version_unchanged(scenario["roc"]["version"], held["version"])


class TestConclusionReadsTheEngagementSamplingPlan:
    """A failed boundary elsewhere on the engagement blocks a ready requirement."""

    def test_a_failure_on_another_zone_blocks_a_fully_evidenced_conclusion(self, api):
        """Nothing about the requirement moves, yet its conclusion is refused.

        PRD: Every conclusion, whichever arm it takes, requires the engagement's most
        recently created sampling plan to be `ACTIVE` with `plan_variant` `FINAL`; a
        conclusion attempted while that plan is `STALE`, is `PRELIMINARY`, or does not
        exist at all is refused with `ERR_SAMPLING_PLAN_STALE`.

        Design: Difficulty/cross_entity_state_dependency/conclusion_blocked_by_stale_sampling_plan_from_other_entity
        """
        scenario = _fieldwork_with_pending_store_zone(api)
        lead_id = scenario["lead_id"]
        lead_headers = make_lead_headers(lead_id)
        first_plan_id = scenario["plan_id"]
        requirement_before = validate_success(
            api.get_requirement_assessment(scenario["requirement_id"], lead_headers)
        )

        record_verdict(
            api,
            scenario["store_segment_id"],
            lead_id,
            outcome="FAIL",
            note="Store VLAN reached the cardholder network over the management path.",
        )

        staled = validate_success(api.get_sampling_plan(first_plan_id, lead_headers))
        assert staled["status"] == "STALE"
        assert staled["superseded_at"] is None
        engagement = read_engagement(api, scenario["engagement_id"], lead_id)
        assert engagement["active_plan_stale"] is True
        assert engagement["active_sampling_plan_id"] is None

        refused = api.conclude_requirement(
            scenario["requirement_id"],
            conclusion_payload(conclusion="IN_PLACE"),
            lead_headers,
        )
        validate_error(refused, ERR_SAMPLING_PLAN_STALE, 422)

        # The requirement and its file are exactly as the failure found them.
        after = validate_success(
            api.get_requirement_assessment(scenario["requirement_id"], lead_headers)
        )
        assert_requirement_dimensions(
            after, test_status="IN_TESTING", remediation_status="NONE"
        )
        assert after["evidence_completeness"] is True
        assert_version_unchanged(requirement_before["version"], after["version"])
        evidence = validate_success(
            api.list_evidence_items(
                lead_headers, {"requirement_assessment_id": scenario["requirement_id"]}
            )
        )
        assert len(evidence) == 3
        assert [row["sufficiency"] for row in evidence] == [
            "SUFFICIENT",
            "SUFFICIENT",
            "SUFFICIENT",
        ]

    def test_a_fresh_final_plan_unblocks_the_identical_conclusion(self, api):
        """Redrawing the sample over the widened inventory lets the same call pass.

        PRD: An `IN_PLACE` conclusion moves `test_status` `IN_TESTING → IN_PLACE`,
        leaves `remediation_status` at `NONE`, recomputes the engagement's
        `unmet_requirement_count` and both compliance percentages, and advances the
        requirement's `version` and the engagement's `version` each by 1.

        Design: Difficulty/cross_entity_state_dependency/conclusion_blocked_by_stale_sampling_plan_from_other_entity
        """
        scenario = _fieldwork_with_pending_store_zone(api)
        lead_id = scenario["lead_id"]
        lead_headers = make_lead_headers(lead_id)
        engagement_id = scenario["engagement_id"]
        record_verdict(
            api,
            scenario["store_segment_id"],
            lead_id,
            outcome="FAIL",
            note="Store VLAN reached the cardholder network over the management path.",
        )
        validate_error(
            api.conclude_requirement(
                scenario["requirement_id"],
                conclusion_payload(conclusion="IN_PLACE"),
                lead_headers,
            ),
            ERR_SAMPLING_PLAN_STALE,
            422,
        )

        redrawn = draw_plan(api, engagement_id, lead_id, plan_variant="FINAL")
        before_conclusion = validate_success(
            api.get_requirement_assessment(scenario["requirement_id"], lead_headers)
        )

        # The disproven boundary dragged the store terminal into the population.
        assert redrawn["status"] == "ACTIVE"
        assert redrawn["eligible_component_count"] == 4
        assert redrawn["component_sample_size"] == 4
        assert_stratum_allocations(
            redrawn,
            {
                "SERVER": 1,
                "NETWORK_DEVICE": 0,
                "POS_TERMINAL": 1,
                "APPLICATION": 2,
                "DATABASE": 0,
            },
        )
        assert_coverage_ratio(redrawn["coverage_ratio"], 1.0000)
        assert redrawn["facility_population_count"] == 2
        assert redrawn["facility_sample_size"] == 1
        assert redrawn["sampled_facility_names"] == ["DC-EAST"]
        # The re-priced fee is read off the engagement the plan re-priced, below.

        concluded = validate_success(
            api.conclude_requirement(
                scenario["requirement_id"],
                conclusion_payload(conclusion="IN_PLACE"),
                lead_headers,
            )
        )
        assert_requirement_dimensions(
            concluded, test_status="IN_PLACE", remediation_status="NONE"
        )
        assert_version_bumped_by(before_conclusion["version"], concluded["version"], 1)
        terminal = validate_success(
            api.get_system_component(scenario["terminal_id"], lead_headers)
        )
        assert terminal["declared_scope_class"] == "OUT_OF_SCOPE"
        assert terminal["scope_class"] == "CDE"
        assert terminal["in_sample"] is True
        engagement = read_engagement(api, engagement_id, lead_id)
        assert engagement["active_sampling_plan_id"] == redrawn["id"]
        assert engagement["active_plan_stale"] is False
        assert engagement["estimated_hours"] == 238
        assert_money(engagement["assessment_fee_total"], 62332.20)


class TestReportCreationReadsTheSegmentationLedger:
    """One untested zone with no hosts is enough to hold back the report."""

    def test_declaring_one_untested_zone_blocks_the_report(
        self, api, engagement_with_in_place_requirement
    ):
        """Every requirement is concluded, yet an unproven zone refuses the report.

        PRD: Because a `DECLARED` zone is by definition unvalidated, declaring one
        raises the engagement's `unvalidated_segment_count` and therefore drives
        `posture` to `RESTRICTED` — an engagement cannot lock scope or start a report
        while any zone's segmentation claim is still unproven.

        Design: Difficulty/cross_entity_state_dependency/roc_creation_blocked_by_unvalidated_segment_posture
        """
        scenario = engagement_with_in_place_requirement
        lead_id = scenario["lead_id"]
        lead_headers = make_lead_headers(lead_id)
        engagement_id = scenario["engagement_id"]
        opening = read_engagement(api, engagement_id, lead_id)
        assert opening["posture"] == "OPEN"

        fresh_zone = declare_segment(
            api, engagement_id, lead_id, "NEW-ZONE", segment_class="CONNECTED"
        )

        assert_segment_state(fresh_zone, segmentation_status="DECLARED")
        restricted = read_engagement(api, engagement_id, lead_id)
        assert restricted["posture"] == "RESTRICTED"
        assert restricted["unvalidated_segment_count"] == 1
        assert restricted["open_gap_count"] == 0
        assert restricted["active_plan_stale"] is False

        refused = api.create_roc(engagement_id, roc_payload("v1.0"), lead_headers)
        validate_error(refused, ERR_ENGAGEMENT_RESTRICTED, 409)

        assert_total_count(
            api.list_rocs(lead_headers, {"engagement_id": engagement_id}), 0
        )
        after = read_engagement(api, engagement_id, lead_id)
        assert after["status"] == "FIELDWORK"
        # The new zone holds no hosts, so neither the partition nor the fee moves.
        assert_partition_counts(after, cde=3, connected=0, out_of_scope=0)
        assert_money(after["assessment_fee_total"], 59189.40)
        held_plan = validate_success(
            api.get_sampling_plan(scenario["plan_id"], lead_headers)
        )
        assert held_plan["status"] == "ACTIVE"

    def test_the_report_is_created_once_the_new_zone_is_proven(
        self, api, engagement_with_in_place_requirement
    ):
        """Passing the new zone's test restores the posture the report demands.

        PRD: Creating the report writes a row at `status` `DRAFTING` with
        `revision_count` at 0, `qa_decision_note` null, `attestation_signature_name`
        null, `attesting_assessor_id` null, `attested_at` null, `submitted_to` null
        and `submission_reference` null.

        Design: Difficulty/cross_entity_state_dependency/roc_creation_blocked_by_unvalidated_segment_posture
        """
        scenario = engagement_with_in_place_requirement
        lead_id = scenario["lead_id"]
        lead_headers = make_lead_headers(lead_id)
        engagement_id = scenario["engagement_id"]
        fresh_zone = declare_segment(
            api, engagement_id, lead_id, "NEW-ZONE", segment_class="CONNECTED"
        )
        validate_error(
            api.create_roc(engagement_id, roc_payload("v1.0"), lead_headers),
            ERR_ENGAGEMENT_RESTRICTED,
            409,
        )

        planned = plan_segmentation(
            api,
            fresh_zone["id"],
            lead_id,
            test_method="CONFIG_REVIEW",
            planned_date="2026-08-15",
        )
        assert_segment_state(planned, segmentation_status="TEST_PLANNED")
        proven = record_verdict(
            api,
            fresh_zone["id"],
            lead_id,
            outcome="PASS",
            note="The connected zone reaches the cardholder network only through the reviewed jump host.",
        )
        assert_segment_state(
            proven,
            segmentation_status="VALIDATED",
            effective_class="CONNECTED",
            scope_expanded_by_failure=False,
        )
        reopened = read_engagement(api, engagement_id, lead_id)
        assert reopened["posture"] == "OPEN"
        assert reopened["unvalidated_segment_count"] == 0
        still_active = validate_success(
            api.get_sampling_plan(scenario["plan_id"], lead_headers)
        )
        assert still_active["status"] == "ACTIVE"
        assert_money(reopened["assessment_fee_total"], 59189.40)

        report = validate_success(
            api.create_roc(engagement_id, roc_payload("v1.0"), lead_headers), 201
        )

        assert report["status"] == "DRAFTING"
        assert report["roc_version_label"] == "v1.0"
        assert report["revision_count"] == 0
        assert report["qa_decision_note"] is None
        assert report["attestation_signature_name"] is None
        assert report["attesting_assessor_id"] is None
        assert report["attested_at"] is None
        assert report["submitted_to"] is None
        assert report["submission_reference"] is None
        assert report["applicable_requirement_count"] == 1
        assert report["in_place_count"] == 1
        assert report["ccw_covered_count"] == 0
        assert report["not_in_place_count"] == 0
        assert_percentage(report["as_found_compliance_percentage"], 100.00)
        assert_percentage(report["as_attested_compliance_percentage"], 100.00)
        assert report["compliance_result"] == "COMPLIANT"
        reporting = read_engagement(api, engagement_id, lead_id)
        assert reporting["status"] == "REPORTING"
        assert reporting["posture"] == "FROZEN"


def _engagement_with_second_quarter_window(api) -> Scenario:
    """A scoping engagement whose only booked scan window is 2026-Q2.

    The window opens on 2026-04-01 and therefore runs up to, but not including,
    2026-06-30. The vendor's approval runs to 2027-12-31, so the vendor gate is
    satisfied at the startup clock and only the calendar can refuse a booking.
    """
    scenario = build_registry(api)
    engagement = open_engagement(
        api, scenario["lead_id"], qa_reviewer_id=scenario["qa_id"]
    )
    vendor = register_vendor(api)
    incumbent = schedule_scan_cycle(
        api,
        engagement["id"],
        scenario["lead_id"],
        vendor["id"],
        quarter_label="2026-Q2",
        window_start="2026-04-01T00:00:00Z",
    )
    scenario["engagement_id"] = engagement["id"]
    scenario["vendor_id"] = vendor["id"]
    scenario["incumbent"] = incumbent
    scenario["incumbent_id"] = incumbent["id"]
    return scenario


class TestQuarterlyScanWindowsMayTouch:
    """The scan window is open on the right, so windows abut without clashing."""

    def test_a_window_opening_one_second_early_is_refused(self, api):
        """A booking that reaches one second into the second quarter is refused.

        PRD: The proposed half-open window, running from `window_start` up to but
        not including its computed end, must not intersect the window of any
        existing scan cycle of the same engagement, or the request is refused with
        `ERR_SCAN_WINDOW_OVERLAP`.

        Design: Difficulty/resource_temporal_overlap/scan_window_half_open_adjacency_boundary
        """
        scenario = _engagement_with_second_quarter_window(api)
        lead_headers = scenario["lead_headers"]
        engagement_id = scenario["engagement_id"]

        refused = api.create_scan_cycle(
            engagement_id,
            scan_cycle_payload(
                scenario["vendor_id"],
                quarter_label="2026-Q3",
                window_start="2026-06-29T23:59:59Z",
            ),
            lead_headers,
        )

        validate_error(refused, ERR_SCAN_WINDOW_OVERLAP, 422)
        assert_total_count(
            api.list_scan_cycles(lead_headers, {"engagement_id": engagement_id}), 1
        )
        engagement = read_engagement(api, engagement_id, scenario["lead_id"])
        assert engagement["status"] == "SCOPING"
        assert engagement["posture"] == "OPEN"
        position = validate_success(
            api.get_engagement_summary(engagement_id, lead_headers)
        )
        assert position["quarterly_scan_compliant"] is False

    def test_a_window_opening_exactly_at_the_close_is_accepted(self, api):
        """The next quarter may open on the very instant the last one closes.

        PRD: Adjacency is deliberately permitted: a cycle that starts exactly at
        another cycle's `window_end` is accepted, and two cycles may share that
        instant exactly.

        Design: Difficulty/resource_temporal_overlap/scan_window_half_open_adjacency_boundary
        """
        scenario = _engagement_with_second_quarter_window(api)
        lead_headers = scenario["lead_headers"]
        engagement_id = scenario["engagement_id"]
        validate_error(
            api.create_scan_cycle(
                engagement_id,
                scan_cycle_payload(
                    scenario["vendor_id"],
                    quarter_label="2026-Q3",
                    window_start="2026-06-29T23:59:59Z",
                ),
                lead_headers,
            ),
            ERR_SCAN_WINDOW_OVERLAP,
            422,
        )

        accepted = validate_success(
            api.create_scan_cycle(
                engagement_id,
                scan_cycle_payload(
                    scenario["vendor_id"],
                    quarter_label="2026-Q3",
                    window_start="2026-06-30T00:00:00Z",
                ),
                lead_headers,
            ),
            201,
        )

        assert accepted["quarter_label"] == "2026-Q3"
        assert_same_instant(accepted["window_start"], "2026-06-30T00:00:00Z")
        assert_same_instant(accepted["window_end"], "2026-09-28T00:00:00Z")
        assert accepted["status"] == "SCHEDULED"
        assert accepted["effective_high_finding_count"] == 0
        assert accepted["scan_completed_at"] is None
        rows = assert_total_count(
            api.list_scan_cycles(lead_headers, {"engagement_id": engagement_id}), 2
        )
        by_quarter = {row["quarter_label"]: row for row in rows}
        assert sorted(by_quarter) == ["2026-Q2", "2026-Q3"]
        # The instant 2026-06-30T00:00:00Z closes the earlier window and opens the
        # later one, so neither cycle claims it as an interior point.
        assert_same_instant(by_quarter["2026-Q2"]["window_end"], "2026-06-30T00:00:00Z")
        assert_same_instant(
            by_quarter["2026-Q3"]["window_start"], "2026-06-30T00:00:00Z"
        )
        incumbent = validate_success(
            api.get_scan_cycle(scenario["incumbent_id"], lead_headers)
        )
        assert incumbent["status"] == "SCHEDULED"
        engagement = read_engagement(api, engagement_id, scenario["lead_id"])
        assert engagement["status"] == "SCOPING"
        assert engagement["posture"] == "OPEN"
        position = validate_success(
            api.get_engagement_summary(engagement_id, lead_headers)
        )
        assert position["quarterly_scan_compliant"] is False

    def test_the_incumbent_window_closes_ninety_days_after_it_opens(self, api):
        """The booked April window closes on the last day of June, exclusively.

        PRD: The cycle's `window_end` is derived as `window_start` advanced by 90
        days and is treated as exclusive, so a window opening at
        `2026-04-01T00:00:00Z` closes at `2026-06-30T00:00:00Z` and that closing
        instant belongs to the next window rather than this one.

        Design: Difficulty/resource_temporal_overlap/scan_window_half_open_adjacency_boundary
        """
        scenario = _engagement_with_second_quarter_window(api)
        lead_headers = scenario["lead_headers"]

        incumbent = validate_success(
            api.get_scan_cycle(scenario["incumbent_id"], lead_headers)
        )

        assert_same_instant(incumbent["window_start"], "2026-04-01T00:00:00Z")
        assert_same_instant(incumbent["window_end"], "2026-06-30T00:00:00Z")
        assert incumbent["quarter_label"] == "2026-Q2"
        assert incumbent["status"] == "SCHEDULED"
        assert incumbent["attestation_of_scan_compliance"] is False
        assert incumbent["scan_completed_at"] is None


SECOND_CLIENT = "Harbor Fuel Stops LLC"
SECOND_ACQUIRER = "Second Harbor Bank"


def _lead_booked_through_september(api) -> Scenario:
    """Dana Reyes already has fieldwork booked from 2026-09-10 to 2026-09-30.

    With the three-day cooldown on each side, the days she is unavailable run from
    2026-09-07 through 2026-10-03 inclusive.
    """
    scenario = build_registry(api)
    incumbent = open_engagement(
        api,
        scenario["lead_id"],
        qa_reviewer_id=scenario["qa_id"],
        fieldwork_start_date="2026-09-10",
        fieldwork_end_date="2026-09-30",
    )
    scenario["incumbent"] = incumbent
    scenario["incumbent_id"] = incumbent["id"]
    return scenario


class TestLeadAssessorCooldownBuffer:
    """The three-day cooldown pushes the next engagement one day further out."""

    def test_fieldwork_starting_on_the_last_cooldown_day_is_refused(self, api):
        """A start date three days after the last engagement ends still collides.

        PRD: A lead assessor cannot be in two places at once, and the platform
        enforces that against the closed interval running from `fieldwork_start_date`
        to `fieldwork_end_date` inclusive, widened by a three-day cooldown on both
        sides.

        Design: Difficulty/resource_temporal_overlap/lead_assessor_calendar_cooldown_buffer_overlap
        """
        scenario = _lead_booked_through_september(api)
        lead_id = scenario["lead_id"]
        lead_headers = scenario["lead_headers"]
        before = read_engagement(api, scenario["incumbent_id"], lead_id)

        refused = api.create_engagement(
            engagement_payload(
                lead_id,
                qa_reviewer_id=scenario["qa_id"],
                client_legal_name=SECOND_CLIENT,
                acquirer_name=SECOND_ACQUIRER,
                fieldwork_start_date="2026-10-03",
                fieldwork_end_date="2026-10-20",
            ),
            lead_headers,
        )

        validate_error(refused, ERR_ASSESSOR_WINDOW_CONFLICT, 422)
        assert_total_count(
            api.list_engagements(lead_headers, {"lead_assessor_id": lead_id}), 1
        )
        assert (
            validate_success(api.get_assessor(lead_id, lead_headers))[
                "lead_engagement_count"
            ]
            == 1
        )
        after = read_engagement(api, scenario["incumbent_id"], lead_id)
        assert after["fieldwork_end_date"] == "2026-09-30"
        assert_version_unchanged(before["version"], after["version"])

    def test_fieldwork_starting_one_day_past_the_cooldown_is_accepted(self, api):
        """One day further out and the two fieldwork windows can both be worked.

        PRD: Both conditions must hold for the conflict to exist; when either fails
        the two windows are far enough apart to be worked.

        Design: Difficulty/resource_temporal_overlap/lead_assessor_calendar_cooldown_buffer_overlap
        """
        scenario = _lead_booked_through_september(api)
        lead_id = scenario["lead_id"]
        lead_headers = scenario["lead_headers"]
        validate_error(
            api.create_engagement(
                engagement_payload(
                    lead_id,
                    qa_reviewer_id=scenario["qa_id"],
                    client_legal_name=SECOND_CLIENT,
                    acquirer_name=SECOND_ACQUIRER,
                    fieldwork_start_date="2026-10-03",
                    fieldwork_end_date="2026-10-20",
                ),
                lead_headers,
            ),
            ERR_ASSESSOR_WINDOW_CONFLICT,
            422,
        )

        accepted = validate_success(
            api.create_engagement(
                engagement_payload(
                    lead_id,
                    qa_reviewer_id=scenario["qa_id"],
                    client_legal_name=SECOND_CLIENT,
                    acquirer_name=SECOND_ACQUIRER,
                    fieldwork_start_date="2026-10-04",
                    fieldwork_end_date="2026-10-20",
                ),
                lead_headers,
            ),
            201,
        )

        assert accepted["client_legal_name"] == SECOND_CLIENT
        assert accepted["status"] == "SCOPING"
        assert accepted["posture"] == "OPEN"
        assert accepted["fieldwork_start_date"] == "2026-10-04"
        assert accepted["fieldwork_end_date"] == "2026-10-20"
        # Nothing has been scoped yet, so only the base hours are billed.
        assert accepted["estimated_hours"] == 160
        assert_money(accepted["assessment_fee_total"], 43200.00)
        assert_total_count(
            api.list_engagements(lead_headers, {"lead_assessor_id": lead_id}), 2
        )
        lead = validate_success(api.get_assessor(lead_id, lead_headers))
        assert lead["lead_engagement_count"] == 2
        # The reviewer's own calendar is untouched: only leads are counted.
        reviewer = validate_success(api.get_assessor(scenario["qa_id"], lead_headers))
        assert reviewer["lead_engagement_count"] == 0
        untouched = read_engagement(api, scenario["incumbent_id"], lead_id)
        assert untouched["fieldwork_end_date"] == "2026-09-30"
