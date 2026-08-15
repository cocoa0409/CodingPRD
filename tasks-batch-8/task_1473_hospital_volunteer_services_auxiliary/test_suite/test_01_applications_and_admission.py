"""Application intake, review workflow, approval cascade, and the
separation-reactivation cycle."""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    api_client, ApiErrorId,
    create_application_payload, create_department_payload, create_role_payload,
    create_request_payload, create_placement_payload, create_clearance_payload,
    set_clock, create_application, approve_application, create_cleared_volunteer,
    create_active_volunteer, create_department, create_role, create_open_request,
    create_offer, accept_placement, complete_orientation, clear_all_clearances,
    get_volunteer, get_volunteer_badge,
    make_volunteer_headers, make_screener_headers,
)
from test_helpers import TEST_USERS

DIRECTOR = TEST_USERS["director_headers"]
COORDINATOR = TEST_USERS["coordinator_headers"]


class TestApplicationCreationDefaults:
    def test_application_lands_submitted_with_defaults(self, api):
        """PRD §3.1: "A fresh application lands in `SUBMITTED` with its `volunteer_id`
        null: no volunteer record exists yet."
        PRD §2.4: "At startup, before it has ever been set, the logical clock reads
        exactly 2026-08-01T00:00:00Z; it never falls back to wall-clock time at any
        point afterward."

        Design: Corner/entities/application_creation_defaults
        """
        set_clock("2026-08-01T00:00:00Z")
        resp = api.create_application(
            create_application_payload(full_name="New Applicant",
                                       date_of_birth="1999-09-09",
                                       email="new@x.org", phone="555-9001"),
            COORDINATOR)
        data = validate_success(resp, expected_status=201)
        assert data["status"] == "SUBMITTED", f"expected SUBMITTED, got {data['status']}"
        assert data.get("volunteer_id") is None, "fresh application's volunteer_id must be null"
        assert data.get("notes") is None, "omitted optional notes must be null"
        assert isinstance(data["version"], int), "version must be an integer"
        assert str(data["created_at"]).startswith("2026-08-01T00:00:00"), (
            f"created_at must be stamped from the logical clock, got {data['created_at']}")


class TestApplicationStateMachine:
    def test_decide_from_submitted_rejected(self, api):
        """PRD §3.1: "Decisions belong to the `VolunteerServicesDirector` alone, and
        only an application sitting in `IN_REVIEW` is decidable."
        PRD §3.1: "acting on an application that is not in the state a transition
        requires is rejected with `ERR_APPLICATION_NOT_ACTIONABLE`."

        Design: Corner/state_machines/decide_from_submitted_rejected
        """
        set_clock("2026-08-01T00:00:00Z")
        app = create_application(full_name="Skip Step", email="ss@x.org")
        resp = api.decide_application(app["id"], {"decision": "APPROVE"}, DIRECTOR)
        validate_error(resp, ApiErrorId.ERR_APPLICATION_NOT_ACTIONABLE)
        vols = get_success_data(api.list_volunteers(COORDINATOR))
        assert vols == [], f"no volunteer may be created by the failed decide, got {vols}"

    def test_terminal_application_lockdown(self, api):
        """PRD §3.1: "`APPROVED`, `REJECTED`, and `WITHDRAWN` are terminal: the
        application never moves again."

        Design: Corner/state_machines/terminal_application_lockdown
        """
        set_clock("2026-08-01T00:00:00Z")
        app1 = create_application(full_name="Rej Rita", email="rr@x.org")
        get_success_data(api.start_review(app1["id"], COORDINATOR))
        get_success_data(api.decide_application(
            app1["id"], {"decision": "REJECT", "rejection_reason": "failed interview"},
            DIRECTOR))
        app2 = create_application(full_name="App Andy", email="aa@x.org")
        get_success_data(api.start_review(app2["id"], COORDINATOR))
        get_success_data(api.decide_application(app2["id"], {"decision": "APPROVE"}, DIRECTOR))

        resp = api.start_review(app1["id"], COORDINATOR)
        validate_error(resp, ApiErrorId.ERR_APPLICATION_NOT_ACTIONABLE)
        resp = api.withdraw_application(app1["id"], COORDINATOR)
        validate_error(resp, ApiErrorId.ERR_APPLICATION_NOT_ACTIONABLE)
        resp = api.withdraw_application(app2["id"], COORDINATOR)
        validate_error(resp, ApiErrorId.ERR_APPLICATION_NOT_ACTIONABLE)


class TestApprovalCascade:
    def test_approval_creates_badge_and_orientation(self, api):
        """PRD §3.1: "In both cases, approval also mints a badge for the volunteer in
        `PENDING` — the standing invariant is exactly one non-`REVOKED` badge per
        volunteer at all times — and enrolls the volunteer in a `PENDING` training
        record for training code `ORIENTATION` with recurrence `ONE_TIME`."
        PRD §3.4: "Every badge carries a server-minted `badge_number`: the literal
        prefix `BDG-` followed by a six-digit zero-padded sequence equal to one plus
        the count of badge rows ever created."

        Design: Corner/state_machines/approval_cascade_creates_badge_and_orientation
        """
        set_clock("2026-08-01T00:00:00Z")
        app = create_application(full_name="Cascade Cass", email="cc@x.org")
        get_success_data(api.start_review(app["id"], COORDINATOR))
        decided = validate_success(
            api.decide_application(app["id"], {"decision": "APPROVE"}, DIRECTOR))
        vol_id = decided["volunteer_id"]
        assert vol_id, "decide(APPROVE) must return the created volunteer_id"

        badges = get_success_data(api.list_badges(COORDINATOR, params={"volunteer_id": vol_id}))
        assert len(badges) == 1, f"exactly one badge expected, got {len(badges)}"
        assert badges[0]["status"] == "PENDING"
        assert badges[0]["badge_number"] == "BDG-000001", (
            f"first badge ever minted must be BDG-000001, got {badges[0]['badge_number']}")

        records = get_success_data(
            api.list_training_records(COORDINATOR, params={"volunteer_id": vol_id}))
        assert len(records) == 1, f"exactly one training record expected, got {len(records)}"
        assert records[0]["training_code"] == "ORIENTATION"
        assert records[0]["recurrence"] == "ONE_TIME"
        assert records[0]["status"] == "PENDING"


class TestSeparationReactivationCycle:
    def _setup_active_volunteer(self):
        set_clock("2026-08-01T00:00:00Z")
        dept = create_department(name="Chaplaincy", head_user_id="dh-1")
        role = create_role(name="Visitor", category="COMMUNITY", minimum_age=18)
        request = create_open_request(dept["id"], role["id"], slots_needed=1)
        return create_active_volunteer(
            dept, role, request, full_name="V Return",
            date_of_birth="1980-12-01", email="vret@x.org", phone="555-1301")

    def test_status_cycle_active_separated_onboarding(self, api):
        """PRD §3.1: "For a **reapply-linked application**, approval instead walks the
        linked volunteer from `SEPARATED` back to `ONBOARDING`: `joined_at` resets to
        now, and `separated_at`, `separation_reason`, and `suspension_reason` are all
        cleared."

        Design: Difficulty/non_linear_state_machine/volunteer_separation_reactivation_cycle
        """
        ctx = self._setup_active_volunteer()
        vol_id = ctx["volunteer_id"]
        assert ctx["volunteer"]["service_status"] == "ACTIVE"

        separated = validate_success(api.separate_volunteer(
            vol_id, {"separation_reason": "MOVED"}, DIRECTOR))
        assert separated["service_status"] == "SEPARATED"

        app2 = validate_success(api.reapply_volunteer(vol_id, {}, COORDINATOR),
                                expected_status=201)
        assert app2["volunteer_id"] == vol_id, (
            "the reapply application must link the SAME volunteer row at creation")
        get_success_data(api.start_review(app2["id"], COORDINATOR))
        validate_success(api.decide_application(app2["id"], {"decision": "APPROVE"}, DIRECTOR))

        volunteer = get_volunteer(vol_id)
        assert volunteer["service_status"] == "ONBOARDING", (
            f"reapply+approve must return the volunteer to ONBOARDING, got "
            f"{volunteer['service_status']}")
        assert str(volunteer["joined_at"]).startswith("2026-08-01T00:00:00"), (
            "joined_at resets to the logical clock at reactivation")
        assert volunteer.get("separated_at") is None, "separated_at must be cleared"
        assert volunteer.get("suspension_reason") is None, "suspension_reason must be cleared"

    def test_badge_audit_trail_old_revoked_new_pending(self, api):
        """PRD §3.4: "The volunteer's badge, whatever its live state (`PENDING`,
        `ISSUED`, or `SUSPENDED`), is `REVOKED` with `revoke_reason` `SEPARATION`."
        PRD §3.4: "Numbers are deterministic by creation order, are never reused even
        after revocation, and are never derived from the badge's `id`."

        Design: Difficulty/non_linear_state_machine/volunteer_separation_reactivation_cycle
        """
        ctx = self._setup_active_volunteer()
        vol_id = ctx["volunteer_id"]
        old_badge = ctx["badge"]
        assert old_badge["badge_number"] == "BDG-000001"
        assert old_badge["status"] == "ISSUED"

        validate_success(api.separate_volunteer(
            vol_id, {"separation_reason": "MOVED"}, DIRECTOR))
        app2 = validate_success(api.reapply_volunteer(vol_id, {}, COORDINATOR),
                                expected_status=201)
        get_success_data(api.start_review(app2["id"], COORDINATOR))
        validate_success(api.decide_application(app2["id"], {"decision": "APPROVE"}, DIRECTOR))

        badges = get_success_data(api.list_badges(COORDINATOR, params={"volunteer_id": vol_id}))
        assert len(badges) == 2, f"expected 2 badge rows (audit trail), got {len(badges)}"
        by_number = {b["badge_number"]: b for b in badges}
        assert by_number["BDG-000001"]["status"] == "REVOKED"
        assert by_number["BDG-000001"]["revoke_reason"] == "SEPARATION"
        assert by_number["BDG-000002"]["status"] == "PENDING", (
            "the reactivation approval mints the next sequential badge in PENDING; "
            "the revoked number is never reused")
