"""Verification/rejection cascades, the rework loop, posture-gated client
approval, authorization expiry, and immediate read visibility of side effects."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    approve_rework_auth,
    complete_rework_loop,
    find_rework_auth,
    get_invoice_for_project,
    get_project,
    get_project_store,
    make_client_headers,
    make_scenario,
    reject_visit,
    schedule_assignment,
    set_clock,
    setup_rejected_visit,
    validate_error,
    validate_paginated,
    validate_success,
    verify_visit,
    visit_store,
)

PM = TEST_USERS["pm_headers"]
BC = TEST_USERS["billing_clerk_headers"]


class TestVerifyCascade:
    def test_verify_cascades_to_reconciling_and_auto_invoice(self, api):
        """PRD 3.5: "On verification the visit's `verification_status` becomes
        `VERIFIED`, its `billable_amount_cents` is computed per §3.7, the
        assignment moves `SUBMITTED` to `VERIFIED`, the store row moves
        `IN_PROGRESS` to `COMPLETED` with its `version` incremented, and the
        project's `completed_store_count` — the count of store-list rows whose
        latest visit is `VERIFIED` — is recomputed. If every store-list row of
        the project has now reached a terminal outcome (`COMPLETED` or
        `DROPPED`) with at least one `COMPLETED`, the project cascades from
        `IN_FIELD` to `RECONCILING`, recomputes its `completed_store_count`,
        increments its `version` by 1, and auto-creates an `OPEN` invoice for
        the client and project if none exists."

        Design: Difficulty/transitive_cascade/verify_cascade_to_invoice
        """
        scn = make_scenario()
        asg, visit = visit_store(scn)  # SUBMITTED
        resp = api.verify_store_visit(visit["id"], PM)
        verified = validate_success(resp)
        assert verified["verification_status"] == "VERIFIED"
        assert verified["billable_amount_cents"] == 3500, (
            f"PER_STORE visit must bill the flat 3500, "
            f"got {verified['billable_amount_cents']}"
        )
        ps = get_project_store(scn["ps_rows"][0]["id"])
        assert ps["status"] == "COMPLETED"
        project = get_project(scn["project"]["id"])
        assert project["status"] == "RECONCILING", (
            f"single completed store must cascade project to RECONCILING, "
            f"got {project['status']}"
        )
        assert project["completed_store_count"] == 1
        resp = api.list_invoices(BC, params={"project_id": scn["project"]["id"]})
        invoices, meta = validate_paginated(resp)
        assert len(invoices) == 1, "exactly one auto-created invoice expected"
        assert invoices[0]["status"] == "OPEN"
        assert invoices[0]["line_total_cents"] == 3500

    def test_verify_cascade_waits_until_last_store_terminal(self, api):
        """PRD 3.5: "If every store-list row of the project has now reached a
        terminal outcome (`COMPLETED` or `DROPPED`) with at least one
        `COMPLETED`, the project cascades from `IN_FIELD` to `RECONCILING`,
        recomputes its `completed_store_count`, increments its `version` by 1,
        and auto-creates an `OPEN` invoice for the client and project if none
        exists."

        Design: Difficulty/transitive_cascade/verify_cascade_to_invoice
        """
        scn = make_scenario(num_stores=2)
        asg1, visit1 = visit_store(
            scn, store_idx=0,
            window=("2026-08-05T08:00:00Z", "2026-08-05T09:00:00Z"),
            on_site=("2026-08-05T08:05:00Z", "2026-08-05T08:55:00Z"),
        )
        verify_visit(visit1["id"])
        mid = get_project(scn["project"]["id"])
        assert mid["status"] == "IN_FIELD", (
            f"one store still non-terminal: project must stay IN_FIELD, "
            f"got {mid['status']}"
        )
        resp = api.list_invoices(BC, params={"project_id": scn["project"]["id"]})
        invoices, _ = validate_paginated(resp)
        assert len(invoices) == 0, (
            "no invoice may exist before the cascade to RECONCILING"
        )
        asg2, visit2 = visit_store(
            scn, store_idx=1,
            window=("2026-08-05T10:00:00Z", "2026-08-05T11:00:00Z"),
            on_site=("2026-08-05T10:05:00Z", "2026-08-05T10:55:00Z"),
        )
        verify_visit(visit2["id"])
        final = get_project(scn["project"]["id"])
        assert final["status"] == "RECONCILING"
        assert final["completed_store_count"] == 2
        invoice = get_invoice_for_project(scn["project"]["id"])
        assert invoice["status"] == "OPEN"
        assert invoice["line_total_cents"] == 7000


class TestRejectCascade:
    def test_reject_cascades_to_rework_required_and_authorization(self, api):
        """PRD 3.5: "On rejection the visit's `verification_status` becomes
        `REJECTED`, the assignment moves `SUBMITTED` to `REJECTED`, the store
        row moves `IN_PROGRESS` to `REWORK_REQUIRED` with its `version`
        incremented, the project's `rework_penalty_score` increases by 10 with
        `posture` re-derived per §2.9, and — critically — a rework
        authorization is auto-created in `REQUESTED` status, bound to the
        project, the store row, and the rejected visit."

        Design: Difficulty/transitive_cascade/reject_cascade_to_rework_authorization
        """
        scn = make_scenario()
        asg, visit = visit_store(scn)
        resp = api.reject_store_visit(visit["id"], PM)
        rejected = validate_success(resp)
        assert rejected["verification_status"] == "REJECTED"
        ps = get_project_store(scn["ps_rows"][0]["id"])
        assert ps["status"] == "REWORK_REQUIRED"
        project = get_project(scn["project"]["id"])
        assert project["rework_penalty_score"] == 10
        assert project["posture"] == "NORMAL", "10 is below the WATCH threshold"
        resp = api.list_rework_authorizations(
            PM, params={"project_store_id": scn["ps_rows"][0]["id"]}
        )
        auths, _ = validate_paginated(resp)
        assert len(auths) == 1, "exactly one auto-created authorization expected"
        assert auths[0]["status"] == "REQUESTED"
        assert auths[0]["rejected_store_visit_id"] == visit["id"]

    def test_reject_created_authorization_binds_project_store_visit(self, api):
        """PRD 3.5: "On rejection the visit's `verification_status` becomes
        `REJECTED`, the assignment moves `SUBMITTED` to `REJECTED`, the store
        row moves `IN_PROGRESS` to `REWORK_REQUIRED` with its `version`
        incremented, the project's `rework_penalty_score` increases by 10 with
        `posture` re-derived per §2.9, and — critically — a rework
        authorization is auto-created in `REQUESTED` status, bound to the
        project, the store row, and the rejected visit."

        Design: Difficulty/transitive_cascade/reject_cascade_to_rework_authorization
        """
        scn, asg, visit, auth = setup_rejected_visit()
        resp = api.get_rework_authorization(auth["id"], PM)
        row = validate_success(resp)
        assert row["project_id"] == scn["project"]["id"]
        assert row["project_store_id"] == scn["ps_rows"][0]["id"]
        assert row["rejected_store_visit_id"] == visit["id"]
        assert row["status"] == "REQUESTED"


class TestReworkCycle:
    def test_project_store_rework_loop_consumes_authorization(self, api):
        """PRD 3.5: "creating an assignment with `rework_authorization_id`
        supplied requires the authorization to be `APPROVED` and the store row
        to be `REWORK_REQUIRED`, failing which the request is rejected with
        `ERR_REWORK_NOT_AUTHORIZED` (HTTP 409). Consumption flips the
        authorization to `CONSUMED`, creates the new assignment with
        `is_rework` true, moves the store row `REWORK_REQUIRED` to `ASSIGNED`,
        and records the new rep in `assigned_rep_id`."

        Design: Difficulty/non_linear_state_machine/project_store_rework_cycle
        """
        scn, asg, visit, auth = setup_rejected_visit()
        approve_rework_auth(auth["id"], scn["client"]["id"])
        rep = scn["reps"][0]
        rework_asg = schedule_assignment(
            scn["project"]["id"], scn["ps_rows"][0]["id"], rep["id"],
            scheduled_start="2026-08-06T09:00:00Z",
            scheduled_end="2026-08-06T11:00:00Z",
            rework_authorization_id=auth["id"],
        )
        assert rework_asg["is_rework"] is True, (
            "assignment created via a rework authorization must carry is_rework true"
        )
        ps = get_project_store(scn["ps_rows"][0]["id"])
        assert ps["status"] == "ASSIGNED", (
            f"store row must loop REWORK_REQUIRED -> ASSIGNED, got {ps['status']}"
        )
        assert ps["assigned_rep_id"] == rep["id"]
        auth_after = api.get_rework_authorization(auth["id"], PM)
        assert validate_success(auth_after)["status"] == "CONSUMED"
        project = get_project(scn["project"]["id"])
        assert project["rework_penalty_score"] == 10

    def test_rework_cycle_repeats_after_second_rejection(self, api):
        """PRD 3.5: "On rejection the visit's `verification_status` becomes
        `REJECTED`, the assignment moves `SUBMITTED` to `REJECTED`, the store
        row moves `IN_PROGRESS` to `REWORK_REQUIRED` with its `version`
        incremented, the project's `rework_penalty_score` increases by 10 with
        `posture` re-derived per §2.9, and — critically — a rework
        authorization is auto-created in `REQUESTED` status, bound to the
        project, the store row, and the rejected visit."

        Design: Difficulty/non_linear_state_machine/project_store_rework_cycle
        """
        scn, asg, visit, auth = setup_rejected_visit()
        auth1, rework_asg, rework_visit = complete_rework_loop(scn)
        # reject the rework visit too: the store loops back to REWORK_REQUIRED
        # and a fresh authorization is synthesized — the cycle is repeatable
        reject_visit(rework_visit["id"])
        ps = get_project_store(scn["ps_rows"][0]["id"])
        assert ps["status"] == "REWORK_REQUIRED", (
            f"store row must loop back to REWORK_REQUIRED, got {ps['status']}"
        )
        project = get_project(scn["project"]["id"])
        assert project["rework_penalty_score"] == 20, (
            f"two rejections accumulate to 20, got {project['rework_penalty_score']}"
        )
        assert project["posture"] == "WATCH"
        auth2 = find_rework_auth(scn["ps_rows"][0]["id"], status="REQUESTED")
        assert auth2["id"] != auth1["id"], "a new authorization must be created"
        assert auth2["rejected_store_visit_id"] == rework_visit["id"]


class TestPostureGatedApproval:
    def test_client_approve_blocked_when_posture_escalated(self, api):
        """PRD 3.5: "Approval moves the authorization `REQUESTED` to
        `APPROVED`, but only while the project's `posture` is not `ESCALATED`;
        an escalated project forces rework through a manual project-manager
        path, and client self-approval is rejected with
        `ERR_POSTURE_ESCALATED` (HTTP 409)."
        PRD 2.9: "From the score the system derives the project's `posture`:
        `NORMAL` while the score is below 20, `WATCH` once the score reaches at
        least 20 but remains below 40, and `ESCALATED` once the score reaches
        at least 40."

        Design: Difficulty/cross_entity_state_dependency/rework_approve_depends_on_project_posture
        """
        scn = make_scenario(num_stores=2, scope_type="RESET")
        rep = scn["reps"][0]
        client_id = scn["client"]["id"]
        # Four rejections across the two stores' rework loops -> score 40.
        visit_store(
            scn, store_idx=0,
            window=("2026-08-05T09:00:00Z", "2026-08-05T10:00:00Z"),
            on_site=("2026-08-05T09:05:00Z", "2026-08-05T09:55:00Z"),
            outcome="reject",
        )
        visit_store(
            scn, store_idx=1,
            window=("2026-08-05T11:00:00Z", "2026-08-05T12:00:00Z"),
            on_site=("2026-08-05T11:05:00Z", "2026-08-05T11:55:00Z"),
            outcome="reject",
        )
        # score 20 (WATCH): client approvals still allowed
        complete_rework_loop(
            scn, store_idx=0,
            window=("2026-08-06T09:00:00Z", "2026-08-06T10:00:00Z"),
            on_site=("2026-08-06T09:05:00Z", "2026-08-06T09:55:00Z"),
            outcome="reject",
        )
        # score 30: still below ESCALATED
        complete_rework_loop(
            scn, store_idx=1,
            window=("2026-08-06T11:00:00Z", "2026-08-06T12:00:00Z"),
            on_site=("2026-08-06T11:05:00Z", "2026-08-06T11:55:00Z"),
            outcome="reject",
        )
        project = get_project(scn["project"]["id"])
        assert project["rework_penalty_score"] == 40
        assert project["posture"] == "ESCALATED"
        open_auth = find_rework_auth(scn["ps_rows"][0]["id"], status="REQUESTED")
        resp = api.approve_rework_authorization(
            open_auth["id"], make_client_headers(client_id)
        )
        validate_error(resp, ApiErrorId.ERR_POSTURE_ESCALATED)

    def test_client_approve_succeeds_at_watch_posture(self, api):
        """PRD 3.5: "Approval moves the authorization `REQUESTED` to
        `APPROVED`, but only while the project's `posture` is not `ESCALATED`;
        an escalated project forces rework through a manual project-manager
        path, and client self-approval is rejected with
        `ERR_POSTURE_ESCALATED` (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/rework_approve_depends_on_project_posture
        """
        scn = make_scenario(num_stores=2)
        visit_store(
            scn, store_idx=0,
            window=("2026-08-05T09:00:00Z", "2026-08-05T10:00:00Z"),
            on_site=("2026-08-05T09:05:00Z", "2026-08-05T09:55:00Z"),
            outcome="reject",
        )
        visit_store(
            scn, store_idx=1,
            window=("2026-08-05T11:00:00Z", "2026-08-05T12:00:00Z"),
            on_site=("2026-08-05T11:05:00Z", "2026-08-05T11:55:00Z"),
            outcome="reject",
        )
        project = get_project(scn["project"]["id"])
        assert project["rework_penalty_score"] == 20
        assert project["posture"] == "WATCH"
        auth = find_rework_auth(scn["ps_rows"][0]["id"], status="REQUESTED")
        resp = api.approve_rework_authorization(
            auth["id"], make_client_headers(scn["client"]["id"])
        )
        approved = validate_success(resp)
        assert approved["status"] == "APPROVED"


class TestReworkExpiry:
    def test_rework_authorization_expires_on_clock_advance(self, api):
        """PRD 3.5: "Authorizations also expire: whenever the logical clock's
        date advances past the store row's `due_date` while an authorization
        for that store is still `REQUESTED`, or still `APPROVED` but
        unconsumed, the authorization moves to `EXPIRED` and the project's
        `rework_penalty_score` increases by 7, with `posture` re-derived. This
        expiry sweep runs when the logical clock is advanced."

        Design: Corner/state_machines/rework_authorization_expiry_on_clock_advance
        """
        scn = make_scenario(due_date="2026-08-10")
        asg, visit = visit_store(scn, outcome="reject")
        auth = find_rework_auth(scn["ps_rows"][0]["id"], status="REQUESTED")
        set_clock("2026-08-11T00:00:00Z")
        resp = api.get_rework_authorization(auth["id"], PM)
        row = validate_success(resp)
        assert row["status"] == "EXPIRED", (
            f"clock past due_date must expire the REQUESTED authorization, "
            f"got {row['status']}"
        )
        project = get_project(scn["project"]["id"])
        assert project["rework_penalty_score"] == 17, (
            f"10 (reject) + 7 (expiry) = 17, got {project['rework_penalty_score']}"
        )


class TestReworkAuthorizationGate:
    def test_rework_assignment_without_approval_rejected(self, api):
        """PRD 3.5: "creating an assignment with `rework_authorization_id`
        supplied requires the authorization to be `APPROVED` and the store row
        to be `REWORK_REQUIRED`, failing which the request is rejected with
        `ERR_REWORK_NOT_AUTHORIZED` (HTTP 409)."

        Design: Corner/errors/error_rework_not_authorized_triggerable
        """
        scn, asg, visit, auth = setup_rejected_visit()
        assert auth["status"] == "REQUESTED"
        resp = api.create_assignment(
            {
                "project_id": scn["project"]["id"],
                "project_store_id": scn["ps_rows"][0]["id"],
                "rep_id": scn["reps"][0]["id"],
                "scheduled_start": "2026-08-06T09:00:00Z",
                "scheduled_end": "2026-08-06T11:00:00Z",
                "rework_authorization_id": auth["id"],
            },
            PM,
        )
        validate_error(resp, ApiErrorId.ERR_REWORK_NOT_AUTHORIZED)


class TestComputedStoreCount:
    def test_completed_store_count_recomputed_after_verify(self, api):
        """PRD 3.5: "On verification the visit's `verification_status` becomes
        `VERIFIED`, its `billable_amount_cents` is computed per §3.7, the
        assignment moves `SUBMITTED` to `VERIFIED`, the store row moves
        `IN_PROGRESS` to `COMPLETED` with its `version` incremented, and the
        project's `completed_store_count` — the count of store-list rows whose
        latest visit is `VERIFIED` — is recomputed."
        PRD 3.2: "its `rework_penalty_score` is 0, its `posture` is `NORMAL`,
        and its `completed_store_count` is 0."

        Design: Corner/entities/project_store_computed_count_after_verify
        """
        scn = make_scenario()
        assert scn["project"]["completed_store_count"] == 0
        asg, visit = visit_store(scn)
        verify_visit(visit["id"])
        project = get_project(scn["project"]["id"])
        assert project["completed_store_count"] == 1, (
            f"count must recompute to 1 after the only visit verifies, "
            f"got {project['completed_store_count']}"
        )


class TestImmediateVisibility:
    def test_verify_side_effects_visible_immediately(self, api):
        """PRD 3.5: "On verification the visit's `verification_status` becomes
        `VERIFIED`, its `billable_amount_cents` is computed per §3.7, the
        assignment moves `SUBMITTED` to `VERIFIED`, the store row moves
        `IN_PROGRESS` to `COMPLETED` with its `version` incremented, and the
        project's `completed_store_count` — the count of store-list rows whose
        latest visit is `VERIFIED` — is recomputed. If every store-list row of
        the project has now reached a terminal outcome (`COMPLETED` or
        `DROPPED`) with at least one `COMPLETED`, the project cascades from
        `IN_FIELD` to `RECONCILING`, recomputes its `completed_store_count`,
        increments its `version` by 1, and auto-creates an `OPEN` invoice for
        the client and project if none exists."

        Design: Corner/consistency_model/immediate_visibility_of_verify_side_effects
        """
        scn = make_scenario()
        asg, visit = visit_store(scn)
        resp = api.verify_store_visit(visit["id"], PM)
        verified = validate_success(resp)
        assert verified["verification_status"] == "VERIFIED"
        assert verified["billable_amount_cents"] == 3500
        # reads issued immediately after the verify response observe all effects
        project = get_project(scn["project"]["id"])
        assert project["status"] == "RECONCILING"
        ps = get_project_store(scn["ps_rows"][0]["id"])
        assert ps["status"] == "COMPLETED"
        resp = api.list_invoices(BC, params={"project_id": scn["project"]["id"]})
        invoices, _ = validate_paginated(resp)
        assert len(invoices) == 1
        assert invoices[0]["status"] == "OPEN"
        assert invoices[0]["line_total_cents"] == 3500
