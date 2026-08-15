"""Difficulty tests — transitive_cascade rule.

Covers the accept cascade (supersede -> promote -> revision -> recompute) and
the verify-failed cascade (flip -> reopen -> forced ETR revision).
"""
import pytest

from test_helpers import (
    TEST_USERS,
    assert_instant_equals,
    create_accepted_assessment,
    create_and_activate_event,
    create_confirm_outage_payload,
    create_crew,
    create_feeder_record,
    create_outage_payload,
    create_submitted_assessment,
    get_success_data,
    make_field_crew_lead_headers,
    run_work_order_to_completed,
    set_clock,
    validate_paginated,
)

ED = TEST_USERS["emergency_director_headers"]
DISP = TEST_USERS["dispatcher_headers"]


class TestAcceptCascadeSupersedePromoteRevisionRecompute:
    """A single /accept drives four linked effects in order."""

    def test_accept_promotes_confirmed_outage_and_publishes_system_revision(self, api):
        """PRD §3.4: "Acceptance cascades: any other assessment on the same
        outage currently `ACCEPTED` transitions to `SUPERSEDED`; if the outage
        was `CONFIRMED` it advances to `ASSESSED`; and the system publishes a
        new revision with reason `DAMAGE_FOUND`, `issued_by` recorded as
        `system`, whose `published_etr` uses the post-assessment variant of
        the estimate."

        Design: Difficulty/transitive_cascade/accept_cascade_supersede_promote_revision_recompute
        """
        set_clock("2026-08-10T00:00:00Z")
        ev = create_and_activate_event(event_name="Storm Eta", event_type="HURRICANE")
        fd = create_feeder_record(county_code="C1", customer_count=2000)
        ot = get_success_data(
            api.create_outage(create_outage_payload(ev["id"], fd["id"]), DISP)
        )
        confirmed = get_success_data(
            api.confirm_outage(
                ot["id"],
                create_confirm_outage_payload(
                    customers_affected=100, cause_code="TREE"
                ),
                DISP,
            )
        )
        cr_a = create_crew(crew_type="DAMAGE_ASSESSOR", start=False)
        set_clock("2026-08-10T00:10:00Z")
        da1 = create_accepted_assessment(
            ot["id"],
            cr_a["id"],
            expected_outage_version=confirmed["version"],
            damage_class="MAJOR",
            estimated_repair_minutes=100,
        )
        mid = get_success_data(api.get_outage(ot["id"], DISP))
        # Link 1: state promotion before any work order existed.
        assert mid["outage_status"] == "ASSESSED"
        # Link 2: system revision seq 2 written by the cascade.
        assert_instant_equals(mid["current_etr"], "2026-08-10T02:40:00Z")

    def test_second_accept_rewrites_etr_supersedes_prior_and_bumps_version(self, api):
        """PRD §2.6: "When a single request performs several logically distinct
        mutations on the same resource (for example, accepting a damage
        assessment changes the outage's state and publishes a new ETR revision
        at once), the outage's `version` advances by exactly one for the whole
        request, never once per internal step."

        Design: Difficulty/transitive_cascade/accept_cascade_supersede_promote_revision_recompute
        """
        set_clock("2026-08-10T00:00:00Z")
        ev = create_and_activate_event(event_name="Storm Eta", event_type="HURRICANE")
        fd = create_feeder_record(county_code="C1", customer_count=2000)
        ot = get_success_data(
            api.create_outage(create_outage_payload(ev["id"], fd["id"]), DISP)
        )
        confirmed = get_success_data(
            api.confirm_outage(
                ot["id"],
                create_confirm_outage_payload(
                    customers_affected=100, cause_code="TREE"
                ),
                DISP,
            )
        )
        cr_a = create_crew(crew_type="DAMAGE_ASSESSOR", start=False)
        set_clock("2026-08-10T00:10:00Z")
        da1 = create_accepted_assessment(
            ot["id"],
            cr_a["id"],
            expected_outage_version=confirmed["version"],
            damage_class="MAJOR",
            estimated_repair_minutes=100,
        )
        mid = get_success_data(api.get_outage(ot["id"], DISP))
        assert_instant_equals(mid["current_etr"], "2026-08-10T02:40:00Z")

        set_clock("2026-08-10T00:30:00Z")
        da2 = create_submitted_assessment(
            ot["id"],
            cr_a["id"],
            damage_class="CATASTROPHIC",
            estimated_repair_minutes=241,
        )
        get_success_data(
            api.accept_damage_assessment(
                da2["id"], {"expected_outage_version": mid["version"]}, DISP
            )
        )
        final = get_success_data(api.get_outage(ot["id"], DISP))
        assert_instant_equals(final["current_etr"], "2026-08-10T06:32:00Z")
        # Link 4: version advanced by exactly one per accept.
        assert mid["version"] == confirmed["version"] + 1
        assert final["version"] == mid["version"] + 1

        da1_read = get_success_data(api.get_damage_assessment(da1["id"], DISP))
        assert da1_read["assessment_status"] == "SUPERSEDED"

        revisions, meta = validate_paginated(api.list_etr_revisions(ot["id"], DISP))
        assert [r["revision_reason"] for r in revisions] == [
            "INITIAL",
            "DAMAGE_FOUND",
            "DAMAGE_FOUND",
        ]
        assert_instant_equals(revisions[2]["previous_etr"], "2026-08-10T02:40:00Z")


class TestVerifyFailedCascadeReopenForcesEtrRevision:
    """A verification flip triggers a chain of cross-entity effects."""

    def test_failed_verification_reopens_execution_and_publishes_180_min_revision(self, api):
        """PRD §3.6: "A failure cascades across both dimensions:
        `verification_status` becomes `VERIFY_FAILED`, `execution_status`
        reopens from `COMPLETED` back to `IN_PROGRESS`, and `completed_at`
        clears; on the linked outage, the system publishes a revision with
        reason `VERIFICATION_FAILED`, `issued_by` recorded as `system`, and a
        `published_etr` exactly three hours (180 minutes) after the logical
        now, updating `current_etr` and advancing the outage's `version` by
        one."

        Design: Difficulty/transitive_cascade/verify_failed_cascade_reopen_forces_etr_revision
        """
        set_clock("2026-08-10T00:00:00Z")
        ev = create_and_activate_event(event_name="Storm Theta", event_type="ICE_STORM")
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
        pre = get_success_data(api.get_outage(ot["id"], DISP))
        assert_instant_equals(pre["current_etr"], "2026-08-10T01:30:00Z")

        get_success_data(api.verify_work_order(wo["id"], {"outcome": "FAILED"}, DISP))
        reopened = get_success_data(api.get_work_order(wo["id"], DISP))
        # Link 1 direct effect.
        assert reopened["verification_status"] == "VERIFY_FAILED"
        # Link 2: reopen caused by link 1, not by any execution endpoint.
        assert reopened["execution_status"] == "IN_PROGRESS"
        assert reopened["completed_at"] is None

        post = get_success_data(api.get_outage(ot["id"], DISP))
        # Link 3: forced system revision at now + 180 min.
        assert_instant_equals(post["current_etr"], "2026-08-10T05:00:00Z")
        assert post["version"] == pre["version"] + 1

    def test_cascade_does_not_redispatch_crew(self, api):
        """PRD §3.6 (the same verify cascade): "A failure cascades across both
        dimensions: `verification_status` becomes `VERIFY_FAILED`,
        `execution_status` reopens from `COMPLETED` back to `IN_PROGRESS`, and
        `completed_at` clears" — the crew, which completion already returned
        to `AVAILABLE`, is not pulled back into `ON_SITE` by the reopen.

        Design: Difficulty/transitive_cascade/verify_failed_cascade_reopen_forces_etr_revision
        """
        set_clock("2026-08-10T00:00:00Z")
        ev = create_and_activate_event(event_name="Storm Theta", event_type="ICE_STORM")
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
        crew_read = get_success_data(api.get_crew(cr_l["id"], DISP))
        assert crew_read["crew_status"] == "AVAILABLE", (
            "the reopen must not re-dispatch a crew that completion already released"
        )
