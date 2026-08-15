"""Facility approval gates and equipment-line parallel state dimensions."""
from test_helpers import (
    ApiErrorId,
    assert_equipment_line,
    assert_instant_equals,
    complete_initial_visit,
    create_approved_facility,
    create_assessed_line,
    create_equipment_line_for,
    create_facility_for,
    create_prospect_client,
    make_supervisor_headers,
    schedule_visit,
    set_clock,
    raise_finding,
    validate_error,
    validate_success,
)


class TestFacilityApprovalGates:
    def test_facility_double_approve_rejected(self, api, reviewer_headers):
        """PRD section 3.2: "and the facility is in fact still `PENDING_REVIEW`
        (else `ERR_FACILITY_INVALID_STATE`)."

        Design: Corner/state_machines/facility_double_approve_rejected
        """
        client = create_prospect_client(legal_name="SM3 Co")
        facility, _line = create_approved_facility(client["id"])
        assert facility["status"] == "APPROVED"
        resp = api.approve_facility(facility["id"], reviewer_headers)
        validate_error(resp, ApiErrorId.ERR_FACILITY_INVALID_STATE)

    def test_facility_approve_without_initial_visit_rejected(
            self, api, reviewer_headers):
        """PRD section 3.2: "at least one `INITIAL` supervision visit at this
        facility has reached `COMPLETED` (else `ERR_INITIAL_VISIT_REQUIRED`)".

        Design: Corner/validations/facility_approve_without_initial_visit_rejected
        """
        client = create_prospect_client(legal_name="IV Co")
        facility = create_facility_for(client["id"], name="FIV")
        create_assessed_line(client["id"], facility["id"])
        resp = api.approve_facility(facility["id"], reviewer_headers)
        validate_error(resp, ApiErrorId.ERR_INITIAL_VISIT_REQUIRED)

    def test_facility_approve_with_unassessed_equipment_rejected(
            self, api, reviewer_headers):
        """PRD section 3.2: "every equipment line has a `dedication_status`
        other than `UNASSESSED` and a `kosherization_state` of `NONE` or `VALID`
        (else `ERR_EQUIPMENT_UNASSESSED`)".

        Design: Corner/validations/facility_approve_with_unassessed_equipment_rejected
        """
        client = create_prospect_client(legal_name="Eq Co")
        facility = create_facility_for(client["id"], name="FEQ")
        # Line registered but deliberately never assessed.
        create_equipment_line_for(client["id"], facility["id"])
        complete_initial_visit(facility["id"])
        resp = api.approve_facility(facility["id"], reviewer_headers)
        validate_error(resp, ApiErrorId.ERR_EQUIPMENT_UNASSESSED)

    def test_facility_approve_with_open_major_finding_rejected(
            self, api, reviewer_headers):
        """PRD section 3.2: "no finding at this facility of severity `MAJOR` or
        `CRITICAL` is in `OPEN`, `REMEDIATION_SUBMITTED`, `REOPENED`, or
        `ESCALATED` (else `ERR_OPEN_MAJOR_FINDINGS`)".

        Design: Corner/validations/facility_approve_with_open_major_finding_rejected
        """
        client = create_prospect_client(legal_name="MF Co")
        facility = create_facility_for(client["id"], name="FMF")
        create_assessed_line(client["id"], facility["id"])
        visit = schedule_visit(facility["id"], visit_type="INITIAL",
                               inspector_user_id="sup-1")
        set_clock("2026-06-01T10:00:00Z")
        sup = make_supervisor_headers("sup-1")
        validate_success(api.start_visit(visit["id"], sup))
        raise_finding(visit["id"], "sup-1", severity="MAJOR",
                      description="traceability")
        validate_success(api.complete_visit(visit["id"], sup))
        resp = api.approve_facility(facility["id"], reviewer_headers)
        validate_error(resp, ApiErrorId.ERR_OPEN_MAJOR_FINDINGS)


class TestEquipmentParallelDimensions:
    def test_shared_assessment_expires_kosherization_and_locks_dedication(
            self, api, reviewer_headers):
        """PRD section 3.2: "A shared line is never clean by default: if a line
        is assessed `SHARED` while its `kosherization_state` is `NONE`, that
        dimension immediately becomes `EXPIRED`." PRD section 3.2: "assessing
        an already-assessed line is rejected with
        `ERR_EQUIPMENT_LINE_INVALID_STATE`".

        Design: Difficulty/non_linear_state_machine/equipment_line_parallel_dedication_kosherization_dimensions
        """
        client = create_prospect_client(legal_name="Equip Co")
        facility = create_facility_for(client["id"], name="E Plant")
        line = create_equipment_line_for(client["id"], facility["id"])

        assessed = validate_success(
            api.assess_equipment_line(line["id"], "SHARED", reviewer_headers))
        assert_equipment_line(assessed)
        assert assessed["dedication_status"] == "SHARED"
        assert assessed["kosherization_state"] == "EXPIRED", (
            "SHARED assessment from NONE must flip kosherization to EXPIRED")

        resp = api.assess_equipment_line(line["id"], "DEDICATED",
                                         reviewer_headers)
        validate_error(resp, ApiErrorId.ERR_EQUIPMENT_LINE_INVALID_STATE)

    def test_kosherization_cycle_leaves_dedication_dimension_untouched(
            self, api, reviewer_headers):
        """PRD section 3.2: "A line carries two independent state dimensions
        that evolve in parallel on the same row." PRD section 3.2: "the line
        becomes `VALID` and its `kosherized_valid_until` is set to the event
        instant plus 72 hours." PRD section 3.2: "moving it from `NONE`,
        `VALID`, or `EXPIRED` to `COMPROMISED` and clearing
        `kosherized_valid_until` to null."

        Design: Difficulty/non_linear_state_machine/equipment_line_parallel_dedication_kosherization_dimensions
        """
        client = create_prospect_client(legal_name="Equip Co 2")
        facility, line = create_approved_facility(client["id"])
        assert line["dedication_status"] == "DEDICATED"
        assert line["kosherization_state"] == "NONE"
        sup = make_supervisor_headers("sup-1")

        first = validate_success(
            api.record_kosherization_event(line["id"], sup), 201)
        assert first["kosherization_state"] == "VALID"
        assert first["dedication_status"] == "DEDICATED", (
            "dimension 1 must be untouched by a kosherization event")
        assert_instant_equals(first["kosherized_valid_until"],
                              "2026-06-04T10:00:00Z",
                              "event instant + 72h")

        compromised = validate_success(api.report_compromise(line["id"], sup))
        assert compromised["kosherization_state"] == "COMPROMISED"
        assert compromised["dedication_status"] == "DEDICATED"
        assert compromised["kosherized_valid_until"] is None

        second = validate_success(
            api.record_kosherization_event(line["id"], sup), 201)
        assert second["kosherization_state"] == "VALID"
        assert second["dedication_status"] == "DEDICATED"
        assert_instant_equals(second["kosherized_valid_until"],
                              "2026-06-04T10:00:00Z",
                              "re-kosherization recomputes the validity window")


class TestKosherizationValidity:
    def test_kosherization_validity_expires_strictly_after_72h(
            self, api, reviewer_headers):
        """PRD section 3.2: "when the logical clock passes
        `kosherized_valid_until` — strictly later; at the exact instant the line
        is still `VALID` — the state becomes `EXPIRED`."

        Design: Corner/calculations/kosherization_validity_expires_strictly_after_72h
        """
        client = create_prospect_client(legal_name="Kosh Co")
        facility, line = create_approved_facility(client["id"])
        # Chain clock is 2026-06-01T10:00:00Z at this point.
        event = validate_success(
            api.record_kosherization_event(
                line["id"], make_supervisor_headers("sup-1")), 201)
        assert event["kosherization_state"] == "VALID"
        assert_instant_equals(event["kosherized_valid_until"],
                              "2026-06-04T10:00:00Z", "event + 72h")

        set_clock("2026-06-04T10:00:00Z")
        at_edge = validate_success(
            api.get_equipment_line(line["id"], reviewer_headers))
        assert at_edge["kosherization_state"] == "VALID", (
            "at exactly kosherized_valid_until the line is still VALID")

        set_clock("2026-06-04T10:00:01Z")
        past = validate_success(
            api.get_equipment_line(line["id"], reviewer_headers))
        assert past["kosherization_state"] == "EXPIRED", (
            "one second past kosherized_valid_until the sweep flips to EXPIRED")
        assert past["kosherized_valid_until"] is None
