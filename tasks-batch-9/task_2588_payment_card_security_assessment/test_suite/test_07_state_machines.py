"""Initial states, refused edges, terminal locks and the report's cycle back."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers.api_errors import (
    ERR_INVALID_REQUIREMENT_STATE,
    ERR_INVALID_SEGMENT_STATE,
    ERR_NO_CDE_SEGMENT,
    ERR_SEGMENT_HAS_COMPONENTS,
)
from test_helpers.assertions import (
    assert_partition_counts,
    assert_percentage,
    assert_requirement_dimensions,
    assert_same_instant,
    assert_segment_state,
    assert_total_count,
    assert_version_bumped_by,
    assert_version_unchanged,
)
from test_helpers.constants import CLOCK_DEFAULT
from test_helpers.factories import (
    qa_review_payload,
    revise_payload,
    segmentation_test_plan_payload,
    validation_result_payload,
    withdraw_segment_payload,
)
from test_helpers.fixtures import (
    add_component,
    declare_segment,
    draw_plan,
    engagement_version,
    open_engagement,
    open_requirement,
    read_engagement,
    record_verdict,
    validated_segment,
)
from test_helpers.test_users import make_assessor_headers, make_lead_headers


class TestDeclaredInitialStates:
    """A commissioned engagement and a freshly declared zone open where the
    specification says they open, and the first zone alone moves the gate."""

    def test_a_new_engagement_opens_in_scoping_with_nothing_outstanding(
        self, api, registry
    ):
        """Commissioning writes the opening status, gate and null dates.

        PRD: A new engagement starts in `status` `SCOPING` with `posture` `OPEN`,
        `scope_locked` false, `attested_at` null, `reassessment_due_date` null and
        `next_assessment_start_date` null.

        Design: Corner/state_machines/state_machine_engagement_and_segment_start_in_declared_initial_states
        """
        engagement = open_engagement(
            api, registry["lead_id"], qa_reviewer_id=registry["qa_id"]
        )

        assert engagement["status"] == "SCOPING"
        assert engagement["posture"] == "OPEN"
        assert engagement["scope_locked"] is False
        assert engagement["attested_at"] is None
        assert engagement["reassessment_due_date"] is None
        assert engagement["next_assessment_start_date"] is None
        assert engagement["version"] == 1
        # No zone has been claimed yet, so nothing is blocking the assessor.
        assert engagement["unvalidated_segment_count"] == 0
        assert engagement["open_gap_count"] == 0
        assert engagement["active_plan_stale"] is False
        assert engagement["active_sampling_plan_id"] is None

    def test_the_first_declared_zone_opens_untested_and_restricts_the_engagement(
        self, api, scoping_engagement
    ):
        """Declaring a zone writes an untested claim and closes the scope lock.

        PRD: Because a `DECLARED` zone is by definition unvalidated, declaring one
        raises the engagement's `unvalidated_segment_count` and therefore drives
        `posture` to `RESTRICTED` — an engagement cannot lock scope or start a
        report while any zone's segmentation claim is still unproven.

        Design: Corner/state_machines/state_machine_engagement_and_segment_start_in_declared_initial_states
        """
        engagement_id = scoping_engagement["engagement_id"]
        lead_id = scoping_engagement["lead_id"]

        segment = declare_segment(
            api, engagement_id, lead_id, "CDE-CORE", segment_class="CDE"
        )

        assert_segment_state(
            segment,
            segmentation_status="DECLARED",
            effective_class="CDE",
            segment_class="CDE",
            scope_expanded_by_failure=False,
            revalidation_round=0,
        )
        assert segment["test_method"] is None
        assert segment["planned_date"] is None
        assert segment["last_validated_at"] is None
        assert segment["version"] == 1

        engagement = read_engagement(api, engagement_id, lead_id)
        assert engagement["unvalidated_segment_count"] == 1
        assert engagement["posture"] == "RESTRICTED"
        # Claiming a zone is not an engagement transition of its own.
        assert engagement["status"] == "SCOPING"
        assert engagement["scope_locked"] is False


class TestVerdictRequiresATestPlan:
    """There is no shortcut from a claimed zone to a proven one."""

    def test_a_verdict_on_an_untested_zone_is_refused_then_accepted_after_planning(
        self, api, scoping_engagement
    ):
        """The same PASS is refused before the test plan and honoured after it.

        PRD: A verdict is only meaningful from `TEST_PLANNED`; a verdict against a
        zone that has no test plan answers `ERR_INVALID_SEGMENT_STATE`.

        Design: Corner/state_machines/state_machine_segment_verdict_from_declared_returns_invalid_segment_state
        """
        engagement_id = scoping_engagement["engagement_id"]
        lead_id = scoping_engagement["lead_id"]
        lead_headers = make_lead_headers(lead_id)
        segment = declare_segment(
            api, engagement_id, lead_id, "CDE-CORE", segment_class="CDE"
        )
        version_before = engagement_version(api, engagement_id, lead_id)

        premature = api.record_validation_result(
            segment["id"],
            validation_result_payload(
                outcome="PASS", note="Verbal confirmation from the network team."
            ),
            lead_headers,
        )
        validate_error(premature, ERR_INVALID_SEGMENT_STATE, 409)

        held = validate_success(api.get_network_segment(segment["id"], lead_headers))
        assert_segment_state(held, segmentation_status="DECLARED")
        assert held["last_validated_at"] is None
        assert_version_unchanged(segment["version"], held["version"])
        blocked = read_engagement(api, engagement_id, lead_id)
        assert blocked["unvalidated_segment_count"] == 1
        assert blocked["posture"] == "RESTRICTED"
        assert_version_unchanged(version_before, blocked["version"])

        planned = validate_success(
            api.plan_segmentation_test(
                segment["id"],
                segmentation_test_plan_payload(
                    test_method="PEN_TEST", planned_date="2026-08-05"
                ),
                lead_headers,
            )
        )
        assert_segment_state(planned, segmentation_status="TEST_PLANNED")
        assert planned["test_method"] == "PEN_TEST"
        assert planned["planned_date"] == "2026-08-05"
        # Planning is still an unvalidated state, so the gate has not moved.
        assert read_engagement(api, engagement_id, lead_id)["posture"] == "RESTRICTED"

        proven = record_verdict(api, segment["id"], lead_id, outcome="PASS")
        assert_segment_state(
            proven, segmentation_status="VALIDATED", effective_class="CDE"
        )
        assert_same_instant(proven["last_validated_at"], CLOCK_DEFAULT)
        cleared = read_engagement(api, engagement_id, lead_id)
        assert cleared["unvalidated_segment_count"] == 0
        assert cleared["posture"] == "OPEN"


class TestWithdrawnZoneIsTerminal:
    """A withdrawn zone is out of the assessment for good."""

    def test_a_withdrawn_zone_takes_no_test_plan_and_no_second_withdrawal(
        self, api, scoping_engagement
    ):
        """Withdrawal relaxes the gate once and then refuses every later edge.

        PRD: `VALIDATED` and `WITHDRAWN` are the two terminal segmentation states:
        nothing moves out of either.

        Design: Corner/state_machines/state_machine_withdrawn_segment_rejects_a_new_test_plan
        """
        engagement_id = scoping_engagement["engagement_id"]
        lead_id = scoping_engagement["lead_id"]
        lead_headers = make_lead_headers(lead_id)
        cde = declare_segment(
            api, engagement_id, lead_id, "CDE-CORE", segment_class="CDE"
        )
        dmz = declare_segment(
            api, engagement_id, lead_id, "LEGACY-DMZ", segment_class="OUT_OF_SCOPE"
        )

        withdrawn = validate_success(
            api.withdraw_network_segment(
                dmz["id"],
                withdraw_segment_payload(
                    reason="The client removed the legacy DMZ from the network before fieldwork began."
                ),
                lead_headers,
            )
        )
        assert_segment_state(withdrawn, segmentation_status="WITHDRAWN")
        assert_version_bumped_by(dmz["version"], withdrawn["version"])

        replanned = api.plan_segmentation_test(
            dmz["id"],
            segmentation_test_plan_payload(
                test_method="CONFIG_REVIEW", planned_date="2026-08-06"
            ),
            lead_headers,
        )
        validate_error(replanned, ERR_INVALID_SEGMENT_STATE, 409)

        repeated = api.withdraw_network_segment(
            dmz["id"],
            withdraw_segment_payload(
                reason="Duplicate withdrawal attempt recorded by the coordinator."
            ),
            lead_headers,
        )
        validate_error(repeated, ERR_INVALID_SEGMENT_STATE, 409)

        settled = validate_success(api.get_network_segment(dmz["id"], lead_headers))
        assert_segment_state(settled, segmentation_status="WITHDRAWN")
        assert settled["test_method"] is None
        assert settled["planned_date"] is None
        assert_version_unchanged(withdrawn["version"], settled["version"])

        # Withdrawal touches one row only: the cardholder zone is still a claim.
        untouched = validate_success(api.get_network_segment(cde["id"], lead_headers))
        assert_segment_state(untouched, segmentation_status="DECLARED")
        engagement = read_engagement(api, engagement_id, lead_id)
        assert engagement["unvalidated_segment_count"] == 1
        assert engagement["posture"] == "RESTRICTED"


class TestWithdrawalRequiresAnEmptyZone:
    """Referential occupancy, not state, blocks these two withdrawals."""

    def test_a_zone_holding_a_component_or_a_child_zone_cannot_be_withdrawn(
        self, api, scoping_engagement
    ):
        """Only the childless, componentless leaf leaves the assessment.

        PRD: A zone may not be withdrawn while any system component still names it
        through `segment_id`, nor while any other zone still names it through
        `parent_segment_id`; either situation is refused with
        `ERR_SEGMENT_HAS_COMPONENTS`.

        Design: Corner/state_machines/state_machine_withdraw_segment_with_a_child_component_is_refused
        """
        engagement_id = scoping_engagement["engagement_id"]
        lead_id = scoping_engagement["lead_id"]
        lead_headers = make_lead_headers(lead_id)
        cde = declare_segment(
            api, engagement_id, lead_id, "CDE-CORE", segment_class="CDE"
        )
        hub = declare_segment(
            api, engagement_id, lead_id, "HUB-A", segment_class="CONNECTED"
        )
        spoke = declare_segment(
            api,
            engagement_id,
            lead_id,
            "SPOKE-B",
            segment_class="CONNECTED",
            parent_segment_id=hub["id"],
        )
        component = add_component(
            api,
            engagement_id,
            lead_id,
            cde["id"],
            "pay-01",
            component_type="APPLICATION",
            function_class="PAYMENT_APPLICATION",
            stores_chd=True,
        )
        assert component["segment_id"] == cde["id"]

        occupied = api.withdraw_network_segment(
            cde["id"],
            withdraw_segment_payload(
                reason="The client asked to drop this zone from scope."
            ),
            lead_headers,
        )
        validate_error(occupied, ERR_SEGMENT_HAS_COMPONENTS, 422)

        parented = api.withdraw_network_segment(
            hub["id"],
            withdraw_segment_payload(reason="The hub zone was decommissioned."),
            lead_headers,
        )
        validate_error(parented, ERR_SEGMENT_HAS_COMPONENTS, 422)

        retired = validate_success(
            api.withdraw_network_segment(
                spoke["id"],
                withdraw_segment_payload(
                    reason="The spoke zone was decommissioned with the hub."
                ),
                lead_headers,
            )
        )
        assert_segment_state(retired, segmentation_status="WITHDRAWN")

        for refused in (cde, hub):
            still_claimed = validate_success(
                api.get_network_segment(refused["id"], lead_headers)
            )
            assert_segment_state(still_claimed, segmentation_status="DECLARED")
            assert_version_unchanged(refused["version"], still_claimed["version"])

        engagement = read_engagement(api, engagement_id, lead_id)
        assert engagement["unvalidated_segment_count"] == 2
        assert engagement["posture"] == "RESTRICTED"
        # No component was orphaned by the refusals.
        assert_partition_counts(engagement, cde=1, connected=0, out_of_scope=0)


class TestStartTestingIsNotReplayable:
    """Starting a requirement twice is a refused edge, not a no-op."""

    def test_a_second_start_on_a_requirement_already_in_testing_is_refused(
        self, api, fieldwork_engagement
    ):
        """The replay is answered 409 and leaves the requirement's counter alone.

        PRD: A start against a requirement that has already left `NOT_STARTED`
        answers `ERR_INVALID_REQUIREMENT_STATE`.

        Design: Corner/state_machines/state_machine_second_start_testing_on_the_same_requirement_is_rejected
        """
        engagement_id = fieldwork_engagement["engagement_id"]
        lead_id = fieldwork_engagement["lead_id"]
        lead_headers = make_lead_headers(lead_id)
        staff_headers = make_assessor_headers(lead_id)
        requirement = open_requirement(
            api,
            engagement_id,
            lead_id,
            requirement_ref="1.2.1",
            requirement_family="R1",
            testing_procedure_count=3,
        )
        assert_requirement_dimensions(
            requirement, test_status="NOT_STARTED", remediation_status="NONE"
        )

        started = validate_success(
            api.start_testing(requirement["id"], staff_headers)
        )
        assert_requirement_dimensions(started, test_status="IN_TESTING")
        assert_version_bumped_by(requirement["version"], started["version"])

        replayed = api.start_testing(requirement["id"], staff_headers)
        validate_error(replayed, ERR_INVALID_REQUIREMENT_STATE, 409)

        # A refused transition performs no write, so the revision counter the
        # worksheet surface reads is left exactly where the first start left it.
        held = validate_success(
            api.get_requirement_assessment(requirement["id"], lead_headers)
        )
        assert_requirement_dimensions(
            held, test_status="IN_TESTING", remediation_status="NONE"
        )
        assert_version_unchanged(started["version"], held["version"])
        assert held["evidence_item_count"] == 0
        assert read_engagement(api, engagement_id, lead_id)["posture"] == "OPEN"


class TestScopeLockNeedsAValidatedCardholderZone:
    """A proven connected tier is not a proven cardholder tier."""

    def test_scope_lock_is_refused_when_no_validated_cde_zone_exists(
        self, api, scoping_engagement
    ):
        """Everything else about the lock is satisfied and it is still refused.

        PRD: Locking scope is lead-only, requires `posture` `OPEN`, and requires at
        least one network segment of the engagement whose declared `segment_class`
        is `CDE` and whose `segmentation_status` is `VALIDATED` — an engagement with
        no validated cardholder-data zone is refused with `ERR_NO_CDE_SEGMENT`.

        Design: Corner/state_machines/state_machine_scope_lock_without_a_validated_cde_segment_is_refused
        """
        engagement_id = scoping_engagement["engagement_id"]
        lead_id = scoping_engagement["lead_id"]
        lead_headers = make_lead_headers(lead_id)
        dmz = validated_segment(
            api,
            engagement_id,
            lead_id,
            name="DMZ-TIER",
            segment_class="CONNECTED",
            test_method="CONFIG_REVIEW",
            planned_date="2026-08-05",
        )
        add_component(
            api,
            engagement_id,
            lead_id,
            dmz["id"],
            "sup-01",
            component_type="SERVER",
            function_class="CONNECTED_SUPPORT",
        )
        plan = draw_plan(api, engagement_id, lead_id, plan_variant="FINAL")
        assert plan["plan_variant"] == "FINAL"
        assert plan["status"] == "ACTIVE"

        # Nothing is outstanding, so the gate is open and cannot be the refusal.
        ready = read_engagement(api, engagement_id, lead_id)
        assert ready["posture"] == "OPEN"
        assert ready["active_sampling_plan_id"] == plan["id"]

        refused = api.lock_scope(engagement_id, lead_headers)
        validate_error(refused, ERR_NO_CDE_SEGMENT, 422)

        after = read_engagement(api, engagement_id, lead_id)
        assert after["status"] == "SCOPING"
        assert after["scope_locked"] is False
        assert_version_unchanged(ready["version"], after["version"])
        proven = validate_success(api.get_network_segment(dmz["id"], lead_headers))
        assert_segment_state(
            proven, segmentation_status="VALIDATED", effective_class="CONNECTED"
        )


class TestReportRejectionAndItsCycleBack:
    """The report machine is cyclic, and its loop-back edge moves the engagement."""

    def test_a_rejected_review_holds_the_report_and_recomputes_nothing(
        self, api, roc_in_qa
    ):
        """The rejection writes the note and leaves every projected number alone.

        PRD: `REJECT` moves the report `IN_QA → QA_REJECTED`, writes
        `qa_decision_note` and performs no recomputation at all.

        Design: Corner/state_machines/state_machine_qa_rejection_loops_the_report_back_to_drafting
        """
        engagement_id = roc_in_qa["engagement_id"]
        lead_id = roc_in_qa["lead_id"]
        under_review = roc_in_qa["roc"]
        note = "Section 4 sampling rationale is too thin to support the conclusion."
        assert under_review["status"] == "IN_QA"
        frozen = read_engagement(api, engagement_id, lead_id)
        assert frozen["status"] == "REPORTING"
        assert frozen["posture"] == "FROZEN"

        rejected = validate_success(
            api.qa_review_roc(
                roc_in_qa["roc_id"],
                qa_review_payload(decision="REJECT", qa_decision_note=note),
                roc_in_qa["qa_headers"],
            )
        )

        assert rejected["status"] == "QA_REJECTED"
        assert rejected["qa_decision_note"] == note
        assert rejected["revision_count"] == 0
        assert rejected["attested_at"] is None
        assert rejected["attesting_assessor_id"] is None
        assert_version_bumped_by(under_review["version"], rejected["version"])
        # The projection the reviewer read is the projection that stands.
        assert_percentage(
            rejected["as_found_compliance_percentage"],
            under_review["as_found_compliance_percentage"],
        )
        assert_percentage(
            rejected["as_attested_compliance_percentage"],
            under_review["as_attested_compliance_percentage"],
        )
        assert rejected["in_place_count"] == under_review["in_place_count"]
        assert rejected["compliance_result"] == under_review["compliance_result"]

        # A rejected review is not a requirement reopen and does not thaw the gate.
        requirement = validate_success(
            api.get_requirement_assessment(
                roc_in_qa["requirement_id"], make_lead_headers(lead_id)
            )
        )
        assert_requirement_dimensions(
            requirement, test_status="IN_PLACE", remediation_status="NONE"
        )
        still_frozen = read_engagement(api, engagement_id, lead_id)
        assert still_frozen["status"] == "REPORTING"
        assert still_frozen["posture"] == "FROZEN"

    def test_revising_a_rejected_report_returns_the_engagement_to_fieldwork(
        self, api, roc_in_qa
    ):
        """The loop-back reuses the report row and lifts the engagement's freeze.

        PRD: It moves the report `QA_REJECTED → DRAFTING`, increments
        `revision_count` by 1, and — this is the engagement's own cycle edge —
        moves the engagement `REPORTING → FIELDWORK`.

        Design: Corner/state_machines/state_machine_qa_rejection_loops_the_report_back_to_drafting
        """
        engagement_id = roc_in_qa["engagement_id"]
        lead_id = roc_in_qa["lead_id"]
        lead_headers = make_lead_headers(lead_id)
        roc_id = roc_in_qa["roc_id"]
        rejected = validate_success(
            api.qa_review_roc(
                roc_id,
                qa_review_payload(
                    decision="REJECT",
                    qa_decision_note="Section 4 sampling rationale is too thin to support the conclusion.",
                ),
                roc_in_qa["qa_headers"],
            )
        )
        assert rejected["status"] == "QA_REJECTED"
        engagement_before = read_engagement(api, engagement_id, lead_id)

        revised = validate_success(
            api.revise_roc(
                roc_id,
                revise_payload(
                    revision_note="Expanded the sampling rationale and re-cited the evidence."
                ),
                lead_headers,
            )
        )

        assert revised["status"] == "DRAFTING"
        assert revised["revision_count"] == 1
        assert_version_bumped_by(rejected["version"], revised["version"])

        reopened = read_engagement(api, engagement_id, lead_id)
        assert reopened["status"] == "FIELDWORK"
        assert reopened["posture"] == "OPEN"
        assert_version_bumped_by(engagement_before["version"], reopened["version"])

        # The loop reuses the row rather than opening a second report.
        assert_total_count(
            api.list_rocs(lead_headers, {"engagement_id": engagement_id}), 1
        )
        assert revised["applicable_requirement_count"] == 1
        assert revised["in_place_count"] == 1
        assert revised["ccw_covered_count"] == 0
        assert revised["not_in_place_count"] == 0
        assert_percentage(revised["as_found_compliance_percentage"], 100.00)
        assert_percentage(revised["as_attested_compliance_percentage"], 100.00)
        assert revised["compliance_result"] == "COMPLIANT"

        # Child data entry is available again now the freeze has lifted.
        requirement = validate_success(
            api.get_requirement_assessment(roc_in_qa["requirement_id"], lead_headers)
        )
        assert_requirement_dimensions(requirement, test_status="IN_PLACE")
        thawed = open_requirement(
            api,
            engagement_id,
            lead_id,
            requirement_ref="9.4.1",
            requirement_family="R9",
            testing_procedure_count=2,
        )
        assert thawed["test_status"] == "NOT_STARTED"
