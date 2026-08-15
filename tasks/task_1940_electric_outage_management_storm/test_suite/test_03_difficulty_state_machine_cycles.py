"""Difficulty tests — non_linear_state_machine rule.

Covers the work-order parallel-dimension reopen cycle and the
damage-assessment rework + supersede cycle.
"""
import pytest

from test_helpers import (
    TEST_USERS,
    assert_instant_equals,
    create_and_activate_event,
    create_accepted_assessment,
    create_confirm_outage_payload,
    create_crew,
    create_feeder_record,
    create_outage_payload,
    create_submitted_assessment,
    create_work_order_payload,
    get_success_data,
    make_field_crew_lead_headers,
    run_work_order_to_completed,
    set_clock,
    setup_event_with_feeder,
    setup_outage_with_accepted_assessment,
    validate_paginated,
)

ED = TEST_USERS["emergency_director_headers"]
DISP = TEST_USERS["dispatcher_headers"]


class TestWorkOrderParallelDimensionsReopenCycle:
    """VERIFY_FAILED reaches across dimensions to reopen execution."""

    def test_verify_failed_reopens_execution_and_forces_etr_revision(self, api):
        """PRD §3.6: "A failure cascades across both dimensions:
        `verification_status` becomes `VERIFY_FAILED`, `execution_status`
        reopens from `COMPLETED` back to `IN_PROGRESS`, and `completed_at`
        clears; on the linked outage, the system publishes a revision with
        reason `VERIFICATION_FAILED`, `issued_by` recorded as `system`, and a
        `published_etr` exactly three hours (180 minutes) after the logical
        now, updating `current_etr` and advancing the outage's `version` by
        one."

        Design: Difficulty/non_linear_state_machine/work_order_parallel_dimensions_reopen_cycle
        """
        set_clock("2026-08-10T00:00:00Z")
        ev = create_and_activate_event(event_name="Storm Epsilon", event_type="HURRICANE")
        fd = create_feeder_record(county_code="C1", customer_count=2000)
        ot = get_success_data(
            api.create_outage(create_outage_payload(ev["id"], fd["id"]), DISP)
        )
        confirmed = get_success_data(
            api.confirm_outage(
                ot["id"],
                create_confirm_outage_payload(
                    customers_affected=50, cause_code="EQUIPMENT"
                ),
                DISP,
            )
        )
        cr_a = create_crew(crew_type="DAMAGE_ASSESSOR", start=False)
        cr_l = create_crew(crew_type="LINE")
        create_accepted_assessment(
            ot["id"],
            cr_a["id"],
            expected_outage_version=confirmed["version"],
            damage_class="MINOR",
            estimated_repair_minutes=60,
            requires_switching=False,
        )
        wo = run_work_order_to_completed(
            ot["id"], cr_l["id"], complete_clock_iso="2026-08-10T02:00:00Z"
        )
        assert wo["execution_status"] == "COMPLETED"
        assert wo["verification_status"] == "PENDING_VERIFY"

        pre = get_success_data(api.get_outage(ot["id"], DISP))
        pre_version = pre["version"]
        assert_instant_equals(pre["current_etr"], "2026-08-10T01:30:00Z")

        get_success_data(
            api.verify_work_order(wo["id"], {"outcome": "FAILED"}, DISP)
        )
        reopened = get_success_data(api.get_work_order(wo["id"], DISP))
        assert reopened["execution_status"] == "IN_PROGRESS"
        assert reopened["verification_status"] == "VERIFY_FAILED"
        assert reopened["completed_at"] is None

        post = get_success_data(api.get_outage(ot["id"], DISP))
        # verify-fail revision must publish now+180 min from 02:00Z
        assert_instant_equals(post["current_etr"], "2026-08-10T05:00:00Z")
        assert post["version"] == pre_version + 1

    def test_recompletion_returns_verification_to_pending(self, api):
        """PRD §3.6: "The rework loop closes when the crew re-completes the
        order, which returns `verification_status` to `PENDING_VERIFY` for a
        fresh judgment."

        Design: Difficulty/non_linear_state_machine/work_order_parallel_dimensions_reopen_cycle
        """
        set_clock("2026-08-10T00:00:00Z")
        ev = create_and_activate_event(event_name="Storm Epsilon", event_type="HURRICANE")
        fd = create_feeder_record(county_code="C1", customer_count=2000)
        ot = get_success_data(
            api.create_outage(create_outage_payload(ev["id"], fd["id"]), DISP)
        )
        confirmed = get_success_data(
            api.confirm_outage(
                ot["id"],
                create_confirm_outage_payload(
                    customers_affected=50, cause_code="EQUIPMENT"
                ),
                DISP,
            )
        )
        cr_a = create_crew(crew_type="DAMAGE_ASSESSOR", start=False)
        cr_l = create_crew(crew_type="LINE")
        create_accepted_assessment(
            ot["id"],
            cr_a["id"],
            expected_outage_version=confirmed["version"],
            damage_class="MINOR",
            estimated_repair_minutes=60,
            requires_switching=False,
        )
        wo = run_work_order_to_completed(
            ot["id"], cr_l["id"], complete_clock_iso="2026-08-10T02:00:00Z"
        )
        get_success_data(api.verify_work_order(wo["id"], {"outcome": "FAILED"}, DISP))
        fcl = make_field_crew_lead_headers(cr_l["id"])
        recompleted = get_success_data(api.complete_work_order(wo["id"], fcl))
        assert recompleted["execution_status"] == "COMPLETED"
        assert recompleted["verification_status"] == "PENDING_VERIFY"


class TestDamageAssessmentReworkAndSupersede:
    """Rework loop is legal; a second accept supersedes the first."""

    def test_submitted_assessment_can_be_returned_to_draft_and_resubmitted(self, api):
        """PRD §3.4: "A dispatcher may hand a `SUBMITTED` assessment back to
        `DRAFT` for rework."

        Design: Difficulty/non_linear_state_machine/damage_assessment_rework_and_supersede
        """
        set_clock("2026-08-10T00:00:00Z")
        ev = create_and_activate_event(event_name="Storm Zeta", event_type="THUNDERSTORM")
        fd = create_feeder_record(county_code="C1", customer_count=2000)
        ot = get_success_data(
            api.create_outage(create_outage_payload(ev["id"], fd["id"]), DISP)
        )
        confirmed = get_success_data(
            api.confirm_outage(
                ot["id"],
                create_confirm_outage_payload(
                    customers_affected=80, cause_code="VEHICLE"
                ),
                DISP,
            )
        )
        cr_a = create_crew(crew_type="DAMAGE_ASSESSOR", start=False)
        da = create_submitted_assessment(
            ot["id"],
            cr_a["id"],
            damage_class="MINOR",
            estimated_repair_minutes=45,
        )
        returned = get_success_data(api.return_damage_assessment(da["id"], DISP))
        assert returned["assessment_status"] == "DRAFT"
        # Resubmit then accept — the rework loop is traversable.
        fcl = make_field_crew_lead_headers(cr_a["id"])
        resubmitted = get_success_data(api.submit_damage_assessment(da["id"], fcl))
        assert resubmitted["assessment_status"] == "SUBMITTED"
        accepted = get_success_data(
            api.accept_damage_assessment(
                da["id"], {"expected_outage_version": confirmed["version"]}, DISP
            )
        )
        assert accepted["assessment_status"] == "ACCEPTED"
        outage = get_success_data(api.get_outage(ot["id"], DISP))
        # Post-assessment ETR: 00:00Z + round_half_up(45*1.5)=68 min.
        assert_instant_equals(outage["current_etr"], "2026-08-10T01:08:00Z")

    def test_second_accept_supersedes_first_and_posts_new_revision(self, api):
        """PRD §3.4: "Acceptance cascades: any other assessment on the same
        outage currently `ACCEPTED` transitions to `SUPERSEDED`; if the outage
        was `CONFIRMED` it advances to `ASSESSED`; and the system publishes a
        new revision with reason `DAMAGE_FOUND`, `issued_by` recorded as
        `system`, whose `published_etr` uses the post-assessment variant of the
        estimate."

        Design: Difficulty/non_linear_state_machine/damage_assessment_rework_and_supersede
        """
        set_clock("2026-08-10T00:00:00Z")
        ev = create_and_activate_event(event_name="Storm Zeta", event_type="THUNDERSTORM")
        fd = create_feeder_record(county_code="C1", customer_count=2000)
        ot = get_success_data(
            api.create_outage(create_outage_payload(ev["id"], fd["id"]), DISP)
        )
        confirmed = get_success_data(
            api.confirm_outage(
                ot["id"],
                create_confirm_outage_payload(
                    customers_affected=80, cause_code="VEHICLE"
                ),
                DISP,
            )
        )
        cr_a = create_crew(crew_type="DAMAGE_ASSESSOR", start=False)
        da1 = create_accepted_assessment(
            ot["id"],
            cr_a["id"],
            expected_outage_version=confirmed["version"],
            damage_class="MINOR",
            estimated_repair_minutes=45,
        )
        mid = get_success_data(api.get_outage(ot["id"], DISP))
        assert_instant_equals(mid["current_etr"], "2026-08-10T01:08:00Z")

        da2 = create_submitted_assessment(
            ot["id"],
            cr_a["id"],
            damage_class="MAJOR",
            estimated_repair_minutes=90,
        )
        get_success_data(
            api.accept_damage_assessment(
                da2["id"], {"expected_outage_version": mid["version"]}, DISP
            )
        )
        da1_read = get_success_data(api.get_damage_assessment(da1["id"], DISP))
        da2_read = get_success_data(api.get_damage_assessment(da2["id"], DISP))
        assert da1_read["assessment_status"] == "SUPERSEDED"
        assert da2_read["assessment_status"] == "ACCEPTED"

        final = get_success_data(api.get_outage(ot["id"], DISP))
        # 00:00Z + round_half_up(90*1.5)=135 min.
        assert_instant_equals(final["current_etr"], "2026-08-10T02:15:00Z")

        revisions, meta = validate_paginated(api.list_etr_revisions(ot["id"], DISP))
        assert meta["total_count"] == 3
        reasons = [r["revision_reason"] for r in revisions]
        assert reasons == ["INITIAL", "DAMAGE_FOUND", "DAMAGE_FOUND"]
