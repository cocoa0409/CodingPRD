"""Cross-entity state dependencies (admit requires reserved bed + active license;
care-plan activation requires finalized assessment + assessed/admitted resident) and the
two non-linear state-machine cycles (deficiency POC resubmit loop; incident resolve-vs-escalate fork).

Citations are verbatim from PRD.md §3.4, §3.5, §3.9, §3.10.
"""
import pytest
from test_helpers import (
    api_client, validate_success, get_success_data,
    setup_active_agreement, create_resident_with_finalized_assessment,
    create_care_plan, setup_cited_deficiency, create_facility, create_resident,
    create_incident,
    TEST_USERS,
)

REGISTRAR = TEST_USERS["registrar_headers"]
CLINICAL = TEST_USERS["clinical_director_headers"]
NURSE = TEST_USERS["nurse_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]
STAFF = TEST_USERS["staff_headers"]


class TestAdmitCrossEntityDependency:
    """Resident ASSESSED -> ADMITTED is valid only when the bound unit is RESERVED and the
    facility is not SUSPENDED."""

    def test_admit_succeeds_when_bed_reserved_and_facility_active(self, api):
        """PRD §3.5: "A `Registrar` admits an `ASSESSED` resident to their reserved bed,
        advancing the resident `ASSESSED → ADMITTED`. Admission is only legal when the resident
        is `ASSESSED`, when the facility's `license_status` is not `SUSPENDED`, and when the
        resident has an `ACTIVE` move-in agreement whose bound unit is `RESERVED` and held for
        this resident."

        Design: Difficulty/cross_entity_state_dependency/admit_depends_on_unit_reserved_and_facility_active
        """
        ctx = setup_active_agreement(
            care_point_rate_cents=2000, base_rent_cents=400000, move_in_date="2026-06-01",
            assessment_overrides={"adl_bathing": 1, "adl_dressing": 1, "adl_toileting": 1,
                                  "adl_transferring": 1, "adl_eating": 1,
                                  "cognition_score": 0, "behavior_flags": 0},
        )
        admitted = validate_success(api.admit_resident(ctx["resident"]["id"], REGISTRAR), 200)
        assert admitted["status"] == "ADMITTED"
        assert admitted["assigned_unit_id"] == ctx["unit"]["id"]

    def test_admit_occupies_bed_and_recomputes_occupancy(self, api):
        """PRD §3.5: "On admission the bound unit advances `RESERVED → OCCUPIED`, the unit's
        `current_resident_id` is set to the resident, the resident's `assigned_unit_id` is set
        to the agreement's unit, and the facility's `occupied_bed_count` and `occupancy_rate_bps`
        are recomputed."

        Design: Difficulty/cross_entity_state_dependency/admit_depends_on_unit_reserved_and_facility_active
        """
        ctx = setup_active_agreement(
            care_point_rate_cents=2000, base_rent_cents=400000, move_in_date="2026-06-01",
            assessment_overrides={"adl_bathing": 1, "adl_dressing": 1, "adl_toileting": 1,
                                  "adl_transferring": 1, "adl_eating": 1,
                                  "cognition_score": 0, "behavior_flags": 0},
        )
        validate_success(api.admit_resident(ctx["resident"]["id"], REGISTRAR), 200)
        unit = validate_success(api.get_unit(ctx["unit"]["id"], STAFF), 200)
        assert unit["status"] == "OCCUPIED"
        assert unit["current_resident_id"] == ctx["resident"]["id"]
        fac = validate_success(api.get_facility(ctx["facility"]["id"], STAFF), 200)
        assert fac["occupied_bed_count"] == 1
        assert fac["occupancy_rate_bps"] == 10000


class TestCarePlanActivateCrossEntityDependency:
    """CarePlan DRAFT -> ACTIVE is valid only when source assessment is FINALIZED and the
    resident is ASSESSED or ADMITTED."""

    def test_activate_succeeds_when_assessment_finalized_and_resident_assessed(self, api):
        """PRD §3.4: "A `ClinicalDirector` activates a draft plan, advancing it
        `DRAFT → ACTIVE`. Activation is only legal when the plan is `DRAFT`, when its source
        assessment is `FINALIZED`, and when the owning resident is in either `ASSESSED` or
        `ADMITTED` status; otherwise it is rejected with `ERR_INVALID_STATE`."

        Design: Difficulty/cross_entity_state_dependency/care_plan_activate_depends_on_assessment_finalized_and_resident_state
        """
        fac, res, asmt = create_resident_with_finalized_assessment()
        assert res["status"] == "ASSESSED"
        assert asmt["status"] == "FINALIZED"
        cp = create_care_plan(res["id"], asmt["id"])
        activated = validate_success(api.activate_care_plan(cp["id"], CLINICAL), 200)
        assert activated["status"] == "ACTIVE"

    def test_activate_keeps_resident_assessed_and_assessment_finalized(self, api):
        """PRD §3.3: "a resident who was `PROSPECT` becomes `ASSESSED` on the first finalize"
        PRD §3.3: "On finalize, the `care_points_total` and `care_level` are recomputed once
        from the row's then-current inputs and frozen; a finalized assessment is thereafter
        immutable"

        Design: Difficulty/cross_entity_state_dependency/care_plan_activate_depends_on_assessment_finalized_and_resident_state
        """
        fac, res, asmt = create_resident_with_finalized_assessment()
        cp = create_care_plan(res["id"], asmt["id"])
        validate_success(api.activate_care_plan(cp["id"], CLINICAL), 200)
        res_after = validate_success(api.get_resident(res["id"], STAFF), 200)
        asmt_after = validate_success(api.get_assessment(asmt["id"], STAFF), 200)
        assert res_after["status"] == "ASSESSED"
        assert asmt_after["status"] == "FINALIZED"


class TestDeficiencyResubmitCycle:
    """POC_SUBMITTED -> POC_REJECTED -> POC_SUBMITTED is a true cycle, not a linear pipeline."""

    def test_resubmit_after_rejection_returns_to_poc_submitted(self, api):
        """PRD §3.10: "The same submit action resubmits a rejected plan, advancing
        `POC_REJECTED → POC_SUBMITTED` and overwriting `poc_text` with the resubmitted narrative."

        Design: Difficulty/non_linear_state_machine/deficiency_poc_reject_resubmit_cycle
        """
        ctx = setup_cited_deficiency(scope_severity="D_F_NO_HARM", cited_at="2026-03-05T10:00:00Z")
        fac_id, def_id = ctx["facility"]["id"], ctx["deficiency"]["id"]
        validate_success(api.submit_poc(fac_id, def_id, {"poc_text": "Initial corrective plan."}, COMPLIANCE), 200)
        validate_success(api.review_poc(fac_id, def_id, {"decision": "REJECT"}, COMPLIANCE), 200)
        resubmitted = validate_success(
            api.submit_poc(fac_id, def_id, {"poc_text": "Revised corrective plan after rejection."}, COMPLIANCE), 200,
        )
        assert resubmitted["status"] == "POC_SUBMITTED"
        assert resubmitted["poc_text"] == "Revised corrective plan after rejection."

    def test_initial_submit_stores_poc_text(self, api):
        """PRD §3.10: "A `ComplianceOfficer` submits a plan of correction, which advances
        `CITED → POC_SUBMITTED` and stores the supplied `poc_text` on the deficiency."

        Design: Difficulty/non_linear_state_machine/deficiency_poc_reject_resubmit_cycle
        """
        ctx = setup_cited_deficiency(scope_severity="D_F_NO_HARM", cited_at="2026-03-05T10:00:00Z")
        fac_id, def_id = ctx["facility"]["id"], ctx["deficiency"]["id"]
        submitted = validate_success(
            api.submit_poc(fac_id, def_id, {"poc_text": "Initial corrective plan."}, COMPLIANCE), 200,
        )
        assert submitted["status"] == "POC_SUBMITTED"
        assert submitted["poc_text"] == "Initial corrective plan."


class TestIncidentResolveVsEscalateFork:
    """UNDER_INVESTIGATION forks: RESOLVED spawns no deficiency; ESCALATED spawns one."""

    def _make_severe_incident_under_investigation(self, api, facility_id, name):
        res = create_resident(facility_id, full_name=name, date_of_birth="1941-06-06")
        inc = create_incident(res["id"], incident_type="FALL", severity="SEVERE",
                              occurred_at="2026-03-01T08:00:00Z")
        validate_success(api.investigate_incident(inc["id"], NURSE), 200)
        return inc

    def test_resolve_branch_spawns_no_deficiency(self, api):
        """PRD §3.9: "From there a `Nurse` may resolve it, advancing
        `UNDER_INVESTIGATION → RESOLVED` with no deficiency spawned; `RESOLVED` is terminal."
        PRD §3.9: "The `linked_deficiency_id` is null until the incident is escalated."

        Design: Difficulty/non_linear_state_machine/incident_branching_resolve_vs_escalate_fork
        """
        fac = create_facility(care_point_rate_cents=2000)
        inc = self._make_severe_incident_under_investigation(api, fac["id"], "Inc One")
        resolved = validate_success(api.resolve_incident(inc["id"], NURSE), 200)
        assert resolved["status"] == "RESOLVED"
        assert resolved["linked_deficiency_id"] is None

    def test_escalate_branch_sets_linked_deficiency(self, api):
        """PRD §3.9: "Alternatively a `ComplianceOfficer` may escalate it, advancing
        `UNDER_INVESTIGATION → ESCALATED`; `ESCALATED` is terminal."
        PRD §3.9: "escalation creates a new survey deficiency on the resident's facility in
        `CITED` status with that scope/severity, sets the incident's `linked_deficiency_id` to
        the new deficiency's id"

        Design: Difficulty/non_linear_state_machine/incident_branching_resolve_vs_escalate_fork
        """
        fac = create_facility(care_point_rate_cents=2000)
        inc = self._make_severe_incident_under_investigation(api, fac["id"], "Inc Two")
        escalated = validate_success(
            api.escalate_incident(
                inc["id"],
                {"scope_severity": "G_I_ACTUAL_HARM", "tag_code": "F-689", "cited_at": "2026-03-03T10:00:00Z"},
                COMPLIANCE,
            ), 200,
        )
        assert escalated["status"] == "ESCALATED"
        assert escalated["linked_deficiency_id"] is not None
