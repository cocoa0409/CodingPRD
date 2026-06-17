"""The pour/cure cascade, cure-window timing, the warranty risk score, the
weather gate, and warranty defect claims. Covers §3.5, §3.6, §3.7, §3.9, §3.12.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    create_poured_project, create_curing_project, create_completed_project,
    create_completed_project_with_active_warranty, create_scheduled_project,
    create_approved_project,
    set_clock, issue_permit, place_material_order, create_crew, book_crew,
    create_weather_reading_payload, start_pour_payload, complete_pour_payload,
    create_warranty_payload, file_claim_payload,
    SINGLE_400_REBAR,
    TEST_USERS,
)

PM = TEST_USERS["project_manager_headers"]
INS = TEST_USERS["inspector_headers"]

SINGLE_400_NONE = [dict(label="slab", area_sqft=400, thickness_in=4, reinforcement="NONE")]


class TestCompletePourCascade:
    """Depth-3 cascade: MaterialOrder POURING->POURED bubbles Project
    SCHEDULED->POURED which recomputes warranty_risk_score."""

    def test_complete_pour_high_early_sets_cure_window_and_risk(self, api):
        """PRD §3.6: "The system then computes the order's cure_window_end as
        pour_completed_at plus the mix-specific cure duration: a STANDARD mix cures
        for 168 hours, a FIBER mix likewise for 168 hours, and a HIGH_EARLY mix for
        72 hours."
        PRD §3.6: "This completion sets off a depth-three cascade: the order
        reaching POURED bubbles the project from SCHEDULED to POURED, and the
        project reaching POURED with a now-populated cure window triggers a
        recomputation of its warranty_risk_score."
        PRD §3.7: "Fourth, if any flatwork segment on the project has a
        reinforcement of NONE, an unreinforced-scope penalty adds 10."

        Design: Difficulty/transitive_cascade/complete_pour_depth3_cascade
        """
        bundle = create_poured_project(
            segments=SINGLE_400_NONE, site_name="Casc A", mix_type="HIGH_EARLY",
            completed_at="2026-06-01T10:00:00Z", issue_warranty=False)
        mo = bundle["material_order"]
        assert mo["status"] == "POURED"
        # 2026-06-01T10:00:00Z + 72h == 2026-06-04T10:00:00Z.
        assert mo["cure_window_end"] == "2026-06-04T10:00:00Z"
        project = bundle["project"]
        assert project["status"] == "POURED"
        # Only the NONE-reinforcement contribution applies: 10.
        assert project["warranty_risk_score"] == 10

    def test_complete_pour_bubbles_project_to_poured(self, api):
        """PRD §3.6: "This completion sets off a depth-three cascade: the order
        reaching POURED bubbles the project from SCHEDULED to POURED, and the
        project reaching POURED with a now-populated cure window triggers a
        recomputation of its warranty_risk_score."
        PRD §2.8: "When a material order's pour is completed, the order's own
        transition to POURED bubbles the owning project from SCHEDULED to POURED,
        which in turn triggers a recomputation of the project's
        warranty_risk_score; each hop is caused by the resulting state of the prior
        hop."

        Design: Difficulty/transitive_cascade/complete_pour_depth3_cascade
        """
        bundle = create_poured_project(
            segments=SINGLE_400_REBAR, site_name="Casc B", mix_type="HIGH_EARLY",
            completed_at="2026-06-01T10:00:00Z", issue_warranty=False)
        # Link1: order POURED; Link2: project bubbled SCHEDULED->POURED.
        assert bundle["material_order"]["status"] == "POURED"
        assert bundle["project"]["status"] == "POURED"
        # REBAR-only scope, full cure window honoured -> no risk contributions.
        assert bundle["project"]["warranty_risk_score"] == 0

    def test_cure_window_standard_168h(self, api):
        """PRD §3.6: "The system then computes the order's cure_window_end as
        pour_completed_at plus the mix-specific cure duration: a STANDARD mix cures
        for 168 hours, a FIBER mix likewise for 168 hours, and a HIGH_EARLY mix for
        72 hours."

        Design: Corner/calculations/cure_window_standard_168h
        """
        bundle = create_poured_project(
            segments=SINGLE_400_REBAR, site_name="Cure168", mix_type="STANDARD",
            pour_scheduled_start="2026-06-01T06:00:00Z",
            completed_at="2026-06-01T12:00:00Z", issue_warranty=False)
        # 2026-06-01T12:00:00Z + 168h == 2026-06-08T12:00:00Z.
        assert bundle["material_order"]["cure_window_end"] == "2026-06-08T12:00:00Z"


class TestCureWindowCompletionBoundary:
    """Completion uses current_utc >= cure_window_end (inclusive)."""

    def test_complete_one_minute_before_cure_end_rejected(self, api):
        """PRD §3.9: "the logical current UTC instant has reached or passed the
        poured material order's cure_window_end, and the project has a warranty in
        ACTIVE status."
        PRD §3.9: "Attempting completion before the cure window has elapsed is
        refused with ERR_CURE_WINDOW_NOT_ELAPSED (HTTP 409)"

        Design: Difficulty/boundary_precision_check/complete_at_cure_window_end_inclusive_boundary
        """
        # HIGH_EARLY poured at 2026-06-01T10:00:00Z -> cure_window_end 2026-06-04T10:00:00Z.
        bundle = create_curing_project(
            segments=SINGLE_400_REBAR, site_name="Cure A", mix_type="HIGH_EARLY",
            completed_at="2026-06-01T10:00:00Z", issue_warranty=True)
        assert bundle["material_order"]["cure_window_end"] == "2026-06-04T10:00:00Z"
        set_clock("2026-06-04T09:59:00Z")  # one minute before
        res = api.complete_project(bundle["project"]["id"], PM)
        validate_error(res, "ERR_CURE_WINDOW_NOT_ELAPSED")

    def test_complete_at_exact_cure_end_succeeds(self, api):
        """PRD §3.9: "the logical current UTC instant has reached or passed the
        poured material order's cure_window_end, and the project has a warranty in
        ACTIVE status."

        Design: Difficulty/boundary_precision_check/complete_at_cure_window_end_inclusive_boundary
        """
        bundle = create_curing_project(
            segments=SINGLE_400_REBAR, site_name="Cure B", mix_type="HIGH_EARLY",
            completed_at="2026-06-01T10:00:00Z", issue_warranty=True)
        set_clock("2026-06-04T10:00:00Z")  # exactly at cure_window_end
        project = validate_success(api.complete_project(bundle["project"]["id"], PM), 200)
        assert project["status"] == "COMPLETED"


class TestWeatherGate:
    def test_out_of_range_precip_blocks_pour(self, api):
        """PRD §3.5: "If any such in-window reading has a temp_f below 40, or a
        temp_f above 90, or a precip_pct at or above 50, the pour start is blocked
        with ERR_WEATHER_OUT_OF_RANGE (HTTP 409)."

        Design: Corner/validations/weather_out_of_range_blocks_pour
        """
        set_clock("2026-06-01T00:00:00Z")
        bundle = create_scheduled_project(
            segments=SINGLE_400_REBAR, site_name="Wx", mix_type="STANDARD",
            pour_scheduled_start="2026-06-01T06:00:00Z", pour_duration_hours=4,
            window_start="2026-06-01T06:00:00Z", window_end="2026-06-01T12:00:00Z")
        mo = bundle["material_order"]
        get_success_data(api.create_weather_reading(
            mo["id"], create_weather_reading_payload("2026-06-01T07:00:00Z", 70, 60), PM))
        res = api.start_pour(mo["id"], start_pour_payload(), PM)
        validate_error(res, "ERR_WEATHER_OUT_OF_RANGE")

    def test_override_allows_pour_and_adds_weather_risk(self, api):
        """PRD §3.5: "The block can be overridden: the start-pour request accepts
        an optional force_override flag, and when it is set to true the pour
        proceeds despite an out-of-range reading."
        PRD §3.7: "Second, if the pour was started over an out-of-range weather
        reading with the override flag set, a weather violation adds 25."

        Design: Corner/validations/weather_override_allows_pour_and_flags_risk
        """
        # NONE-reinforcement (+10) and an overridden out-of-range reading (+25) -> 35.
        bundle = create_poured_project(
            segments=SINGLE_400_NONE, site_name="Ovr", mix_type="STANDARD",
            pour_scheduled_start="2026-06-01T06:00:00Z", pour_duration_hours=4,
            window_start="2026-06-01T06:00:00Z", window_end="2026-06-01T12:00:00Z",
            completed_at="2026-06-01T10:00:00Z", issue_warranty=False,
            force_override=True,
            weather_reading=dict(reading_at="2026-06-01T07:00:00Z", temp_f=30, precip_pct=5))
        assert bundle["material_order"]["status"] == "POURED"
        project = get_success_data(api.get_project(bundle["project"]["id"], PM))
        assert project["warranty_risk_score"] == 35


class TestWarrantyClaims:
    def test_claim_self_loop_and_count_accumulates(self, api):
        """PRD §3.12: "The first claim moves the warranty from ACTIVE to
        CLAIM_OPEN; subsequent claims on an already-open warranty are a self-loop
        that keeps it CLAIM_OPEN."
        PRD §3.12: "Either way, the warranty's defect_claims_count increments by 1,
        the project's warranty_risk_score is recomputed to reflect the added defect
        contribution, and both the warranty's and the project's version increment."

        Design: Difficulty/non_linear_state_machine/warranty_claim_open_self_loop_and_revert
        """
        project, warranty = create_completed_project_with_active_warranty(
            segments=SINGLE_400_REBAR, site_name="War A")
        get_success_data(api.file_claim(warranty["id"],
                         file_claim_payload(defect_note="crack at joint"), INS))
        second = get_success_data(api.file_claim(warranty["id"],
                 file_claim_payload(defect_note="spalling near drain"), INS))
        assert second["status"] == "CLAIM_OPEN"
        assert second["defect_claims_count"] == 2

    def test_claim_resolve_reverts_to_active_without_decrement(self, api):
        """PRD §3.12: "Resolving an open claim returns the warranty from CLAIM_OPEN
        to ACTIVE and increments its version; the defect_claims_count is not
        decremented on resolution, because claims are historical and accumulate
        permanently."

        Design: Difficulty/non_linear_state_machine/warranty_claim_open_self_loop_and_revert
        """
        project, warranty = create_completed_project_with_active_warranty(
            segments=SINGLE_400_REBAR, site_name="War R")
        get_success_data(api.file_claim(warranty["id"], file_claim_payload(), INS))
        resolved = get_success_data(api.resolve_claim(warranty["id"], INS))
        assert resolved["status"] == "ACTIVE"
        assert resolved["defect_claims_count"] == 1  # NOT decremented


class TestCompleteCascadeAndPreconditions:
    def test_complete_releases_booked_crew(self, api):
        """PRD §3.9: "On successful completion every crew assignment still in
        BOOKED is released to RELEASED, the project's version increments, and each
        released assignment's version increments as well."

        Design: Corner/state_machines/complete_releases_booked_crew_cascade
        """
        bundle = create_completed_project(segments=SINGLE_400_REBAR, site_name="Done")
        assert bundle["project"]["status"] == "COMPLETED"
        # The BOOKED assignment must have been cascade-released to RELEASED.
        ca = validate_success(api.get_crew_assignment(bundle["assignment"]["id"], PM), 200)
        assert ca["status"] == "RELEASED"

    def test_complete_without_active_warranty_precondition(self, api):
        """PRD §3.9: "the absence of an ACTIVE warranty is a precondition failure
        yielding ERR_PRECONDITION_NOT_MET."

        Design: Corner/endpoints/complete_requires_active_warranty_precondition
        """
        bundle = create_curing_project(
            segments=SINGLE_400_REBAR, site_name="NoWar", mix_type="HIGH_EARLY",
            completed_at="2026-06-01T10:00:00Z", issue_warranty=False)
        set_clock("2026-06-05T00:00:00Z")  # past cure_window_end
        res = api.complete_project(bundle["project"]["id"], PM)
        validate_error(res, "ERR_PRECONDITION_NOT_MET")

    def test_claim_before_completed_precondition(self, api):
        """PRD §3.12: "An Inspector files defect claims against a warranty, but
        only on a project that has reached COMPLETED; a claim filed against a
        project that is not COMPLETED is refused with ERR_PRECONDITION_NOT_MET."

        Design: Difficulty/cross_entity_state_dependency/warranty_claim_requires_project_completed
        """
        proj, est = create_approved_project(segments=SINGLE_400_REBAR, site_name="War B")
        warranty = get_success_data(api.create_warranty(
            proj["id"], create_warranty_payload(12), PM))
        res = api.file_claim(warranty["id"], file_claim_payload(defect_note="premature claim"), INS)
        validate_error(res, "ERR_PRECONDITION_NOT_MET")

    def test_claim_succeeds_on_completed_project(self, api):
        """PRD §3.12: "An Inspector files defect claims against a warranty, but only
        on a project that has reached COMPLETED"
        PRD §3.12: "The first claim moves the warranty from ACTIVE to CLAIM_OPEN"

        Design: Difficulty/cross_entity_state_dependency/warranty_claim_requires_project_completed
        """
        project, warranty = create_completed_project_with_active_warranty(
            segments=SINGLE_400_REBAR, site_name="War C")
        assert project["status"] == "COMPLETED"
        claimed = validate_success(
            api.file_claim(warranty["id"], file_claim_payload(), INS), 200)
        assert claimed["status"] == "CLAIM_OPEN"
