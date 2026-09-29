"""Uniqueness, conditional shape and cross-entity rules on the write surface."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers.api_errors import (
    ERR_ATTESTATION_SIGNATURE_MISMATCH,
    ERR_COMPONENT_NOT_IN_SAMPLE,
    ERR_DUPLICATE_HOSTNAME,
    ERR_DUPLICATE_REQUIREMENT_REF,
    ERR_DUPLICATE_SEGMENT_NAME,
    ERR_EVIDENCE_TARGET_REQUIRED,
    ERR_FACILITY_TYPE_CONFLICT,
    ERR_INTERVIEWEE_REQUIRED,
    ERR_INVALID_ENGAGEMENT_STATE,
    ERR_INVALID_REASSESSMENT_YEAR,
)
from test_helpers.assertions import (
    assert_coverage_ratio,
    assert_money,
    assert_partition_counts,
    assert_percentage,
    assert_same_instant,
    assert_stratum_allocations,
    assert_total_count,
    assert_version_bumped_by,
    assert_version_unchanged,
)
from test_helpers.constants import (
    CLOCK_DEFAULT,
    FACILITY_DC_EAST,
    LEAD_NAME,
    SECOND_LEAD_EMAIL,
    SECOND_LEAD_NAME,
)
from test_helpers.factories import (
    attest_payload,
    evidence_payload,
    network_segment_payload,
    qa_review_payload,
    reassessment_plan_payload,
    requirement_payload,
    submission_payload,
    system_component_payload,
)
from test_helpers.fixtures import (
    Scenario,
    add_component,
    build_approved_vendor_with_cycle,
    build_registry,
    build_roc_in_qa,
    build_scoping_engagement,
    build_validated_cde_engagement,
    complete_cycle,
    declare_segment,
    draw_plan,
    lock_scope,
    ok,
    open_engagement,
    open_requirement,
    read_engagement,
    register_assessor,
    start_testing,
    validated_segment,
)
from test_helpers.test_users import (
    make_assessor_headers,
    make_lead_headers,
    make_qa_reviewer_headers,
)

HQ_NORTH = "HQ-NORTH"


class TestNetworkZoneNameUniqueness:
    """A zone name is spoken for inside its own engagement and free elsewhere."""

    def test_a_zone_name_is_reusable_only_under_a_different_engagement(self, api):
        """The repeat is refused in the same engagement and accepted in another.

        PRD: A lead or staff assessor declares each network zone with a `name` that
        must be unique within the engagement — a repeat is refused with
        `ERR_DUPLICATE_SEGMENT_NAME` — and a `segment_class` recording the class the
        client asserted before anything was tested, one of `CDE`, `CONNECTED` or
        `OUT_OF_SCOPE`.

        Design: Corner/validations/validation_segment_name_uniqueness_is_scoped_to_the_engagement
        """
        registry = build_registry(api)
        first_lead_id = registry["lead_id"]
        second_lead_id = register_assessor(api, SECOND_LEAD_NAME, SECOND_LEAD_EMAIL)["id"]
        first_headers = make_lead_headers(first_lead_id)
        second_headers = make_lead_headers(second_lead_id)
        first = open_engagement(api, first_lead_id, qa_reviewer_id=registry["qa_id"])
        # A second client worked by a different lead, on a window far from the first.
        second = open_engagement(
            api,
            second_lead_id,
            qa_reviewer_id=registry["qa_id"],
            client_legal_name="Harbor Fuel Stops LLC",
            acquirer_name="Second Harbor Bank",
            fieldwork_start_date="2026-10-04",
            fieldwork_end_date="2026-10-20",
        )
        held = declare_segment(
            api, first["id"], first_lead_id, "CDE-CORE", segment_class="CDE"
        )

        refused = api.create_network_segment(
            first["id"],
            network_segment_payload(name="CDE-CORE", segment_class="CONNECTED"),
            first_headers,
        )
        validate_error(refused, ERR_DUPLICATE_SEGMENT_NAME, 422)

        twin = declare_segment(
            api, second["id"], second_lead_id, "CDE-CORE", segment_class="CDE"
        )

        assert twin["name"] == "CDE-CORE"
        assert twin["id"] != held["id"]
        assert_total_count(
            api.list_network_segments(first_headers, {"engagement_id": first["id"]}), 1
        )
        assert_total_count(
            api.list_network_segments(second_headers, {"engagement_id": second["id"]}), 1
        )
        # The refused write left the client's original assertion alone.
        kept = validate_success(api.get_network_segment(held["id"], first_headers))
        assert kept["segment_class"] == "CDE"
        assert kept["segmentation_status"] == "DECLARED"
        assert (
            read_engagement(api, first["id"], first_lead_id)["unvalidated_segment_count"]
            == 1
        )
        assert (
            read_engagement(api, second["id"], second_lead_id)[
                "unvalidated_segment_count"
            ]
            == 1
        )


def _engagement_with_one_data_centre_host(api) -> Scenario:
    """A scoping engagement whose declared cardholder zone holds pay-01 at DC-EAST."""
    scenario = build_scoping_engagement(api)
    segment = declare_segment(
        api,
        scenario["engagement_id"],
        scenario["lead_id"],
        "CDE-CORE",
        segment_class="CDE",
    )
    scenario["segment_id"] = segment["id"]
    scenario["pay_01"] = add_component(
        api,
        scenario["engagement_id"],
        scenario["lead_id"],
        segment["id"],
        "pay-01",
        component_type="APPLICATION",
        function_class="PAYMENT_APPLICATION",
        stores_chd=True,
        facility_name=FACILITY_DC_EAST,
        facility_type="DATA_CENTER",
    )
    return scenario


class TestFacilityConsistencyAndHostnameUniqueness:
    """One physical location carries one category, and one hostname one row."""

    def test_a_facility_name_may_not_carry_a_second_facility_type(self, api):
        """DC-EAST is a data centre, so the same name cannot also be an office.

        PRD: Facilities must be internally consistent: within one engagement, a
        given `facility_name` may never appear under two different `facility_type`
        values, and the second, disagreeing component is refused with
        `ERR_FACILITY_TYPE_CONFLICT`.

        Design: Corner/validations/validation_facility_name_may_not_carry_two_facility_types
        """
        scenario = _engagement_with_one_data_centre_host(api)
        engagement_id = scenario["engagement_id"]
        lead_id = scenario["lead_id"]
        staff_headers = make_assessor_headers(lead_id)
        lead_headers = make_lead_headers(lead_id)

        # A unique hostname does not rescue a location declared under two categories.
        refused = api.create_system_component(
            engagement_id,
            system_component_payload(
                segment_id=scenario["segment_id"],
                hostname="hr-01",
                component_type="SERVER",
                function_class="CONNECTED_SUPPORT",
                facility_name=FACILITY_DC_EAST,
                facility_type="OFFICE",
            ),
            staff_headers,
        )
        validate_error(refused, ERR_FACILITY_TYPE_CONFLICT, 422)

        accepted = validate_success(
            api.create_system_component(
                engagement_id,
                system_component_payload(
                    segment_id=scenario["segment_id"],
                    hostname="hr-01",
                    component_type="SERVER",
                    function_class="CONNECTED_SUPPORT",
                    facility_name=HQ_NORTH,
                    facility_type="OFFICE",
                ),
                staff_headers,
            ),
            201,
        )

        assert accepted["facility_name"] == HQ_NORTH
        assert accepted["facility_type"] == "OFFICE"
        assert_total_count(
            api.list_system_components(lead_headers, {"engagement_id": engagement_id}), 2
        )
        assert_total_count(
            api.list_system_components(
                lead_headers,
                {"engagement_id": engagement_id, "facility_name": FACILITY_DC_EAST},
            ),
            1,
        )
        engagement = read_engagement(api, engagement_id, lead_id)
        assert_partition_counts(engagement, 2, 0, 0)
        # No plan has been drawn, so the fee still rests on the baseline hours.
        assert engagement["estimated_hours"] == 160
        assert_money(engagement["assessment_fee_total"], 43200.00)

    def test_a_fresh_facility_does_not_excuse_a_reused_hostname(self, api):
        """pay-01 is taken, whatever location the second row claims to sit at.

        PRD: Each component is recorded with a `hostname` that must be unique within
        the engagement — a repeat is refused with `ERR_DUPLICATE_HOSTNAME` — a
        `component_type` naming the sampling stratum it belongs to (`SERVER`,
        `NETWORK_DEVICE`, `POS_TERMINAL`, `APPLICATION` or `DATABASE`), a
        `function_class` naming its functional role for requirement mapping
        (`PAYMENT_APPLICATION`, `DATA_STORE`, `SECURITY_SERVICE`,
        `CONNECTED_SUPPORT` or `SEGMENTATION_CONTROL`), a boolean `stores_chd`
        asserting whether the component stores cardholder data, a `facility_name`
        grouping it with everything else at the same physical location, a
        `facility_type` categorising that location (`DATA_CENTER`, `CALL_CENTER`,
        `RETAIL_STORE` or `OFFICE`) and a `segment_id` placing it in one of the
        engagement's declared zones.

        Design: Corner/validations/validation_facility_name_may_not_carry_two_facility_types
        """
        scenario = _engagement_with_one_data_centre_host(api)
        engagement_id = scenario["engagement_id"]
        lead_id = scenario["lead_id"]
        lead_headers = make_lead_headers(lead_id)

        refused = api.create_system_component(
            engagement_id,
            system_component_payload(
                segment_id=scenario["segment_id"],
                hostname="pay-01",
                component_type="SERVER",
                function_class="CONNECTED_SUPPORT",
                facility_name=HQ_NORTH,
                facility_type="OFFICE",
            ),
            make_assessor_headers(lead_id),
        )
        validate_error(refused, ERR_DUPLICATE_HOSTNAME, 422)

        assert_total_count(
            api.list_system_components(lead_headers, {"engagement_id": engagement_id}), 1
        )
        assert_total_count(
            api.list_system_components(
                lead_headers,
                {"engagement_id": engagement_id, "facility_name": HQ_NORTH},
            ),
            0,
        )
        held = validate_success(
            api.get_system_component(scenario["pay_01"]["id"], lead_headers)
        )
        assert held["component_type"] == "APPLICATION"
        assert held["facility_name"] == FACILITY_DC_EAST
        assert held["facility_type"] == "DATA_CENTER"
        assert held["version"] == scenario["pay_01"]["version"]


def _requirement_in_testing(api, scenario: Scenario, requirement_ref: str = "1.2.1"):
    """Open one requirement on the engagement and move it into active testing."""
    requirement = open_requirement(
        api,
        scenario["engagement_id"],
        scenario["lead_id"],
        requirement_ref=requirement_ref,
        requirement_family="R1",
    )
    start_testing(api, requirement["id"], scenario["lead_id"])
    return requirement


class TestEvidenceShapePerTechnique:
    """The required fields of an evidence record follow its collection technique."""

    def test_an_interview_record_needs_both_the_name_and_the_title(
        self, api, fieldwork_engagement
    ):
        """Half an interviewee identity is no interviewee identity.

        PRD: An `INTERVIEW` record must carry both `interviewee_name` and
        `interviewee_title`, and omitting either is refused with
        `ERR_INTERVIEWEE_REQUIRED`.

        Design: Corner/validations/validation_evidence_shape_depends_on_the_collection_technique
        """
        scenario = fieldwork_engagement
        requirement = _requirement_in_testing(api, scenario)
        lead_headers = make_lead_headers(scenario["lead_id"])

        name_only = api.create_evidence_item(
            requirement["id"],
            evidence_payload(
                evidence_type="INTERVIEW",
                procedure_ref="1.2.1.b",
                interviewee_name="Priya Raman",
            ),
            lead_headers,
        )
        validate_error(name_only, ERR_INTERVIEWEE_REQUIRED, 422)

        title_only = api.create_evidence_item(
            requirement["id"],
            evidence_payload(
                evidence_type="INTERVIEW",
                procedure_ref="1.2.1.b",
                interviewee_title="Network Engineering Manager",
            ),
            lead_headers,
        )
        validate_error(title_only, ERR_INTERVIEWEE_REQUIRED, 422)

        held = validate_success(
            api.get_requirement_assessment(requirement["id"], lead_headers)
        )
        assert held["evidence_item_count"] == 0
        assert held["evidence_type_coverage"] == []
        assert held["evidence_completeness"] is False
        assert held["test_status"] == "IN_TESTING"
        assert_total_count(
            api.list_evidence_items(
                lead_headers, {"requirement_assessment_id": requirement["id"]}
            ),
            0,
        )

    def test_an_observation_needs_a_target_where_a_document_review_needs_none(
        self, api, fieldwork_engagement
    ):
        """The observed host must be named; a reviewed standard names nobody.

        PRD: An `OBSERVATION` or `SYSTEM_CONFIG` record must name a `component_id`,
        and omitting it is refused with `ERR_EVIDENCE_TARGET_REQUIRED`.

        Design: Corner/validations/validation_evidence_shape_depends_on_the_collection_technique
        """
        scenario = fieldwork_engagement
        requirement = _requirement_in_testing(api, scenario)
        lead_headers = make_lead_headers(scenario["lead_id"])

        untargeted = api.create_evidence_item(
            requirement["id"],
            evidence_payload(evidence_type="OBSERVATION", procedure_ref="1.2.1.c"),
            lead_headers,
        )
        validate_error(untargeted, ERR_EVIDENCE_TARGET_REQUIRED, 422)

        reviewed = validate_success(
            api.create_evidence_item(
                requirement["id"],
                evidence_payload(
                    evidence_type="DOCUMENT_REVIEW",
                    procedure_ref="1.2.1.a",
                    note="Firewall standard reviewed.",
                ),
                lead_headers,
            ),
            201,
        )

        assert reviewed["component_id"] is None
        assert reviewed["interviewee_name"] is None
        assert reviewed["interviewee_title"] is None
        assert reviewed["sufficiency"] == "SUFFICIENT"
        held = validate_success(
            api.get_requirement_assessment(requirement["id"], lead_headers)
        )
        # Only the accepted record counted; the refusal persisted nothing.
        assert held["evidence_item_count"] == 1
        assert held["evidence_type_coverage"] == ["DOCUMENT_REVIEW"]
        assert held["evidence_completeness"] is False


def _engagement_with_an_unsampled_host(api) -> Scenario:
    """A fieldwork engagement holding one proven out-of-scope host beside the sample.

    The cardholder zone keeps app-01, pay-01 and pay-02; a second proven zone the
    client declared out of scope keeps legacy-01, which no plan can ever draw.
    """
    scenario = build_validated_cde_engagement(api)
    legacy_zone = validated_segment(
        api,
        scenario["engagement_id"],
        scenario["lead_id"],
        name="LEGACY-DMZ",
        segment_class="OUT_OF_SCOPE",
        test_method="TRAFFIC_ANALYSIS",
        planned_date="2026-08-05",
    )
    scenario["legacy_segment_id"] = legacy_zone["id"]
    scenario["legacy"] = add_component(
        api,
        scenario["engagement_id"],
        scenario["lead_id"],
        legacy_zone["id"],
        "legacy-01",
        component_type="SERVER",
        function_class="CONNECTED_SUPPORT",
        facility_name=FACILITY_DC_EAST,
        facility_type="DATA_CENTER",
    )
    scenario["plan"] = draw_plan(
        api, scenario["engagement_id"], scenario["lead_id"], plan_variant="FINAL"
    )
    scenario["plan_id"] = scenario["plan"]["id"]
    scenario["engagement"] = lock_scope(
        api, scenario["engagement_id"], scenario["lead_id"]
    )
    return scenario


class TestEvidenceTargetMustBeSampled:
    """An artefact may only speak about a host the active plan actually drew."""

    def test_observing_an_out_of_scope_host_is_refused(self, api):
        """legacy-01 resolves and belongs to the engagement, yet it was never drawn.

        PRD: A named component must belong to the same engagement as the
        requirement, or the append answers `ERR_CROSS_ENGAGEMENT_REFERENCE`, and it
        must be a component the engagement's active plan actually selected — a
        component whose `in_sample` is false is refused with
        `ERR_COMPONENT_NOT_IN_SAMPLE`, because evidence gathered outside the sample
        proves nothing about the sample.

        Design: Corner/validations/validation_evidence_component_must_be_inside_the_active_sample
        """
        scenario = _engagement_with_an_unsampled_host(api)
        lead_headers = make_lead_headers(scenario["lead_id"])
        requirement = _requirement_in_testing(api, scenario)

        refused = api.create_evidence_item(
            requirement["id"],
            evidence_payload(
                evidence_type="OBSERVATION",
                procedure_ref="1.2.1.c",
                component_id=scenario["legacy"]["id"],
            ),
            lead_headers,
        )
        validate_error(refused, ERR_COMPONENT_NOT_IN_SAMPLE, 422)

        untouched = validate_success(
            api.get_system_component(scenario["legacy"]["id"], lead_headers)
        )
        assert untouched["scope_class"] == "OUT_OF_SCOPE"
        assert untouched["declared_scope_class"] == "OUT_OF_SCOPE"
        assert untouched["in_sample"] is False
        assert untouched["sampling_stratum"] is None

        plan = validate_success(api.get_sampling_plan(scenario["plan_id"], lead_headers))
        assert plan["eligible_component_count"] == 3
        assert plan["component_sample_size"] == 3
        assert_coverage_ratio(plan["coverage_ratio"], 1.0000)
        assert_stratum_allocations(
            plan,
            {
                "SERVER": 1,
                "NETWORK_DEVICE": 0,
                "POS_TERMINAL": 0,
                "APPLICATION": 2,
                "DATABASE": 0,
            },
        )

        engagement = read_engagement(
            api, scenario["engagement_id"], scenario["lead_id"]
        )
        assert_partition_counts(engagement, 3, 0, 1)
        # The out-of-scope host is neither drawn nor billed.
        assert engagement["estimated_hours"] == 226
        assert_money(engagement["assessment_fee_total"], 59189.40)
        held = validate_success(
            api.get_requirement_assessment(requirement["id"], lead_headers)
        )
        assert held["evidence_item_count"] == 0


class TestRequirementRefUniqueness:
    """A dotted requirement reference is claimed once per assessment programme."""

    def test_the_same_dotted_reference_cannot_be_added_twice(
        self, api, fieldwork_engagement
    ):
        """Requirement 1.2.1 is on the programme, so a second 1.2.1 is turned away.

        PRD: Either the lead or a staff assessor adds a requirement to the programme
        with its dotted `requirement_ref` — something of the shape `6.4.1` — which
        must be unique within the engagement, a repeat being refused with
        `ERR_DUPLICATE_REQUIREMENT_REF`.

        Design: Corner/validations/validation_duplicate_requirement_ref_within_the_engagement
        """
        scenario = fieldwork_engagement
        engagement_id = scenario["engagement_id"]
        lead_id = scenario["lead_id"]
        lead_headers = make_lead_headers(lead_id)
        held = open_requirement(
            api,
            engagement_id,
            lead_id,
            requirement_ref="1.2.1",
            requirement_family="R1",
        )

        # Neither a different family nor a different applicability frees the reference.
        refused = api.create_requirement_assessment(
            engagement_id,
            requirement_payload(
                requirement_ref="1.2.1",
                requirement_family="R2",
                testing_procedure_count=1,
                applicability="NOT_APPLICABLE",
            ),
            make_assessor_headers(lead_id),
        )
        validate_error(refused, ERR_DUPLICATE_REQUIREMENT_REF, 422)

        assert_total_count(
            api.list_requirement_assessments(
                lead_headers, {"engagement_id": engagement_id}
            ),
            1,
        )
        kept = validate_success(api.get_requirement_assessment(held["id"], lead_headers))
        assert kept["requirement_family"] == "R1"
        assert kept["risk_points"] == 3
        assert kept["applicability"] == "APPLICABLE"
        assert kept["testing_procedure_count"] == 3
        assert (
            read_engagement(api, engagement_id, lead_id)["applicable_requirement_count"]
            == 1
        )


class TestScopeLockGates:
    """Scope closes exactly once, and only from the scoping stage."""

    def test_locking_scope_moves_the_engagement_into_fieldwork(
        self, api, sampled_engagement
    ):
        """A proven cardholder zone plus an active final sample is all the lock needs.

        PRD: A successful lock sets `scope_locked` to true, moves the engagement
        `SCOPING → FIELDWORK`, recomputes `posture` — which stays `OPEN`, since the
        preconditions guarantee no blocker — and advances the engagement's `version`
        by 1.

        Design: Corner/validations/validation_scope_lock_succeeds_when_every_gate_is_satisfied
        """
        scenario = sampled_engagement
        engagement_id = scenario["engagement_id"]
        lead_id = scenario["lead_id"]
        lead_headers = make_lead_headers(lead_id)
        before = read_engagement(api, engagement_id, lead_id)
        assert before["status"] == "SCOPING"
        assert before["scope_locked"] is False

        locked = validate_success(api.lock_scope(engagement_id, lead_headers))

        assert locked["scope_locked"] is True
        assert locked["status"] == "FIELDWORK"
        assert locked["posture"] == "OPEN"
        assert_version_bumped_by(before["version"], locked["version"])
        assert locked["unvalidated_segment_count"] == 0
        assert locked["open_gap_count"] == 0
        assert locked["active_plan_stale"] is False
        assert locked["active_sampling_plan_id"] == scenario["plan_id"]
        assert locked["estimated_hours"] == 226
        assert_money(locked["assessment_fee_total"], 59189.40)
        plan = validate_success(api.get_sampling_plan(scenario["plan_id"], lead_headers))
        assert plan["status"] == "ACTIVE"
        assert plan["plan_variant"] == "FINAL"

    def test_scope_cannot_be_locked_a_second_time(self, api, fieldwork_engagement):
        """Once fieldwork has begun the lock transition is no longer on offer.

        PRD: Scope lock is only available from `SCOPING`, and any later engagement
        status answers `ERR_INVALID_ENGAGEMENT_STATE`.

        Design: Corner/validations/validation_scope_lock_succeeds_when_every_gate_is_satisfied
        """
        scenario = fieldwork_engagement
        engagement_id = scenario["engagement_id"]
        lead_id = scenario["lead_id"]
        lead_headers = make_lead_headers(lead_id)
        before = read_engagement(api, engagement_id, lead_id)
        assert before["status"] == "FIELDWORK"

        refused = api.lock_scope(engagement_id, lead_headers)
        validate_error(refused, ERR_INVALID_ENGAGEMENT_STATE, 409)

        after = read_engagement(api, engagement_id, lead_id)
        assert after["status"] == "FIELDWORK"
        assert after["scope_locked"] is True
        assert after["posture"] == "OPEN"
        assert_version_unchanged(before["version"], after["version"])


def _report_ready_to_attest(api) -> Scenario:
    """A report approved by quality assurance on an engagement with a passing scan."""
    scenario = build_roc_in_qa(api)
    build_approved_vendor_with_cycle(api, scenario)
    complete_cycle(api, scenario["cycle_id"], scenario["vendor_id"])
    scenario["roc"] = ok(
        api.qa_review_roc(
            scenario["roc_id"],
            qa_review_payload(decision="APPROVE"),
            make_qa_reviewer_headers(scenario["qa_id"]),
        )
    )
    return scenario


class TestAttestationSignature:
    """The typed signature must reproduce the lead assessor's registered name."""

    def test_an_abbreviated_signature_is_refused_where_the_full_name_passes(self, api):
        """An abbreviated hand is not the registered name, so only the exact name signs.

        PRD: And the supplied `attestation_signature_name` must equal the lead
        assessor's `full_name` verbatim — no trimming, no case folding, no partial
        match — or the attestation answers `ERR_ATTESTATION_SIGNATURE_MISMATCH`.

        Design: Corner/validations/validation_attestation_signature_must_match_the_lead_full_name
        """
        scenario = _report_ready_to_attest(api)
        lead_id = scenario["lead_id"]
        lead_headers = make_lead_headers(lead_id)
        roc_id = scenario["roc_id"]

        refused = api.attest_roc(
            roc_id, attest_payload(attestation_signature_name="D. Reyes"), lead_headers
        )
        validate_error(refused, ERR_ATTESTATION_SIGNATURE_MISMATCH, 422)

        held = validate_success(api.get_roc(roc_id, lead_headers))
        assert held["status"] == "QA_APPROVED"
        assert held["attesting_assessor_id"] is None
        assert held["attested_at"] is None
        assert held["attestation_signature_name"] is None
        waiting = read_engagement(api, scenario["engagement_id"], lead_id)
        assert waiting["status"] == "REPORTING"
        assert waiting["quarterly_scan_compliant"] is True

        signed = validate_success(
            api.attest_roc(
                roc_id,
                attest_payload(attestation_signature_name=LEAD_NAME),
                lead_headers,
            )
        )

        assert signed["status"] == "ATTESTED"
        assert signed["attestation_signature_name"] == LEAD_NAME
        assert signed["attesting_assessor_id"] == lead_id
        assert_same_instant(signed["attested_at"], CLOCK_DEFAULT)
        assert_percentage(signed["as_found_compliance_percentage"], 100.00)
        assert_percentage(signed["as_attested_compliance_percentage"], 100.00)
        assert signed["compliance_result"] == "COMPLIANT"
        assert_version_bumped_by(held["version"], signed["version"])
        after = read_engagement(api, scenario["engagement_id"], lead_id)
        assert after["status"] == "ATTESTED"
        assert after["posture"] == "FROZEN"

    def test_the_signed_report_carries_through_to_next_years_plan(self, api):
        """A signed and delivered report opens the reassessment year, and only that year.

        PRD: The payload carries `target_year`, which must equal the engagement's
        `assessment_year` plus 1, and `planned_start_date`, which must fall on or
        after the logical-clock date; either breach is refused with
        `ERR_INVALID_REASSESSMENT_YEAR`.

        Design: Corner/validations/validation_attestation_signature_must_match_the_lead_full_name
        """
        scenario = _report_ready_to_attest(api)
        engagement_id = scenario["engagement_id"]
        lead_id = scenario["lead_id"]
        lead_headers = make_lead_headers(lead_id)
        ok(
            api.attest_roc(
                scenario["roc_id"],
                attest_payload(attestation_signature_name=LEAD_NAME),
                lead_headers,
            )
        )
        delivered = validate_success(
            api.submit_roc(scenario["roc_id"], submission_payload(), lead_headers)
        )
        assert delivered["status"] == "SUBMITTED"

        submitted = read_engagement(api, engagement_id, lead_id)
        assert submitted["status"] == "SUBMITTED"
        assert submitted["assessment_year"] == 2026
        # A delivery with no scope-affecting changes buys a full year.
        assert submitted["reassessment_due_date"] == "2027-08-01"
        assert submitted["next_assessment_start_date"] is None

        refused = api.record_reassessment_plan(
            engagement_id,
            reassessment_plan_payload(target_year=2028, planned_start_date="2027-06-01"),
            lead_headers,
        )
        validate_error(refused, ERR_INVALID_REASSESSMENT_YEAR, 422)

        planned = validate_success(
            api.record_reassessment_plan(
                engagement_id,
                reassessment_plan_payload(
                    target_year=2027, planned_start_date="2027-06-01"
                ),
                lead_headers,
            )
        )

        assert planned["status"] == "REASSESSMENT_PLANNED"
        assert planned["next_assessment_start_date"] == "2027-06-01"
        assert planned["posture"] == "FROZEN"
        assert_version_bumped_by(submitted["version"], planned["version"])
