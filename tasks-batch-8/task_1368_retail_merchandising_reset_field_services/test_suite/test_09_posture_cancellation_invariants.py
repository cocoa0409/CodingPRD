"""Posture ledger thresholds, validation-cascade masking, cancellation
cascades, and compensating store-list invariants."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    create_shipment,
    deny_rework_auth,
    depart_assignment,
    file_exception,
    find_rework_auth,
    get_assignment,
    get_invoice_for_project,
    get_project,
    get_project_store,
    make_client_headers,
    make_scenario,
    scan_shipment,
    schedule_assignment,
    setup_rejected_visit,
    validate_error,
    validate_paginated,
    validate_success,
    visit_store,
    void_invoice,
)

PM = TEST_USERS["pm_headers"]
BC = TEST_USERS["billing_clerk_headers"]


class TestPostureThresholds:
    def test_posture_watch_at_score_exactly_20(self, api):
        """PRD 2.9: "Every project carries a `rework_penalty_score`, a
        monotonically accumulating integer that starts at 0 and never
        decrements. Six operational events feed it: rejecting a submitted visit
        adds 10; ... From the score the system derives the project's `posture`:
        `NORMAL` while the score is below 20, `WATCH` once the score reaches at
        least 20 but remains below 40, and `ESCALATED` once the score reaches
        at least 40."

        Design: Difficulty/boundary_precision_check/posture_threshold_watch_at_exactly_20
        """
        scn = make_scenario(num_stores=2, scope_type="RESET")
        visit_store(
            scn, store_idx=0,
            window=("2026-08-05T09:00:00Z", "2026-08-05T10:00:00Z"),
            on_site=("2026-08-05T09:05:00Z", "2026-08-05T09:55:00Z"),
            outcome="reject",
        )
        mid = get_project(scn["project"]["id"])
        assert mid["rework_penalty_score"] == 10
        assert mid["posture"] == "NORMAL", "10 is below the WATCH threshold"
        visit_store(
            scn, store_idx=1,
            window=("2026-08-05T11:00:00Z", "2026-08-05T12:00:00Z"),
            on_site=("2026-08-05T11:05:00Z", "2026-08-05T11:55:00Z"),
            outcome="reject",
        )
        project = get_project(scn["project"]["id"])
        assert project["rework_penalty_score"] == 20
        assert project["posture"] == "WATCH", (
            f"score 20 reaches the inclusive lower bound: WATCH, "
            f"got {project['posture']}"
        )

    def test_posture_stays_normal_below_20(self, api):
        """PRD 2.9: "Six operational events feed it: rejecting a submitted
        visit adds 10; a client denying a rework authorization adds 5; a rework
        authorization expiring past the store's due date adds 7; a fixture
        shipment entering a delivery exception adds 3; a fixture shipment
        delivered after its promised date adds 5; and a fixture shipment
        declared lost adds 8. From the score the system derives the project's
        `posture`: `NORMAL` while the score is below 20, `WATCH` once the score
        reaches at least 20 but remains below 40, and `ESCALATED` once the
        score reaches at least 40."

        Design: Difficulty/boundary_precision_check/posture_threshold_watch_at_exactly_20
        """
        scn = make_scenario(scope_type="RESET")
        ship = create_shipment(
            scn["project"]["id"], scn["ps_rows"][0]["id"],
            promised_date="2026-08-15",
        )
        scan_shipment(ship["id"], "IN_TRANSIT")
        exc = scan_shipment(ship["id"], "EXCEPTION")  # +3
        assert exc["status"] == "DELIVERY_EXCEPTION"
        visit_store(scn, outcome="reject")  # +10
        project = get_project(scn["project"]["id"])
        assert project["rework_penalty_score"] == 13, (
            f"10 (reject) + 3 (delivery exception) = 13, "
            f"got {project['rework_penalty_score']}"
        )
        assert project["posture"] == "NORMAL", (
            f"13 is below the WATCH threshold: NORMAL, got {project['posture']}"
        )


class TestFinalizeValidationCascade:
    def test_finalize_void_invoice_with_open_exception_reports_invalid_state(
        self, api
    ):
        """PRD 2.6: "Every request passes through a fixed validation cascade,
        and the order is observable because an earlier failure masks later
        ones. ... Fourth, state legality: the target entity must be in a state
        from which the requested transition is defined (failure:
        `ERR_INVALID_STATE`, HTTP 409). ... Seventh, the domain business
        constraints — rep double-booking, store-list uniqueness,
        fixture-delivery gating, billing-model resolvability, open-exception
        gating, and workforce-classification rules."
        PRD 3.7: "An `OPEN` invoice may instead be voided by a `BillingClerk`,
        moving it to `VOID`; `FINALIZED` and `VOID` are terminal."

        Design: Difficulty/priority_pair_validation_conflict/invalid_state_vs_open_exceptions_on_finalize
        """
        scn = make_scenario()
        asg, visit = visit_store(scn, outcome="verify")
        file_exception(visit["id"], exception_type="OUT_OF_STOCK", sku_count=3,
                       severity="MEDIUM")
        invoice = get_invoice_for_project(scn["project"]["id"])
        void_invoice(invoice["id"])
        # both failures are armed (invoice VOID + exception OPEN); the
        # state-legality check fires first and masks open-exception gating
        resp = api.finalize_invoice(
            invoice["id"], {"expected_invoice_version": invoice["version"]}, BC
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_finalize_void_invoice_without_exceptions_reports_invalid_state(
        self, api
    ):
        """PRD 3.7: "An `OPEN` invoice may instead be voided by a
        `BillingClerk`, moving it to `VOID`; `FINALIZED` and `VOID` are
        terminal."
        PRD 2.6: "Fourth, state legality: the target entity must be in a state
        from which the requested transition is defined (failure:
        `ERR_INVALID_STATE`, HTTP 409)."

        Design: Difficulty/priority_pair_validation_conflict/invalid_state_vs_open_exceptions_on_finalize
        """
        scn = make_scenario()
        asg, visit = visit_store(scn, outcome="verify")
        invoice = get_invoice_for_project(scn["project"]["id"])
        void_invoice(invoice["id"])
        resp = api.finalize_invoice(
            invoice["id"], {"expected_invoice_version": invoice["version"]}, BC
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestStoreListConservation:
    def test_cancel_then_drop_conserves_store_list(self, api):
        """PRD 3.3: "Cancellation moves the assignment to `CANCELLED`, reverts
        the store row from `ASSIGNED` back to `PENDING`, and clears the row's
        `assigned_rep_id`."
        PRD 3.5: "The row lands in `DROPPED`, its `assigned_rep_id` is cleared,
        its `version` increments by 1, any of its assignments in `SCHEDULED` or
        `EN_ROUTE` are cancelled, and — on the rework path — any of its open
        authorizations in `REQUESTED` or `APPROVED` are moved to `EXPIRED`."

        Design: Difficulty/compensating_invariant/store_list_count_conserved_under_cancel_and_drop
        """
        scn = make_scenario(num_stores=2)
        rep = scn["reps"][0]
        asg = schedule_assignment(
            scn["project"]["id"], scn["ps_rows"][0]["id"], rep["id"]
        )
        resp = api.cancel_assignment(asg["id"], PM)
        cancelled = validate_success(resp)
        assert cancelled["status"] == "CANCELLED"
        ps_after_cancel = get_project_store(scn["ps_rows"][0]["id"])
        assert ps_after_cancel["status"] == "PENDING", (
            f"cancel must revert ASSIGNED -> PENDING, got "
            f"{ps_after_cancel['status']}"
        )
        assert ps_after_cancel.get("assigned_rep_id") in (None, ""), (
            "cancel must clear assigned_rep_id"
        )
        resp = api.drop_project_store(scn["ps_rows"][0]["id"], PM)
        dropped = validate_success(resp)
        assert dropped["status"] == "DROPPED"
        assert dropped.get("assigned_rep_id") in (None, "")
        resp = api.list_project_stores(
            PM, params={"project_id": scn["project"]["id"]}
        )
        rows, _ = validate_paginated(resp)
        non_dropped = [r for r in rows if r["status"] != "DROPPED"]
        assert len(rows) == 2, "dropping does not delete the row"
        assert len(non_dropped) == 1, (
            f"only the untouched second store remains non-DROPPED, got "
            f"{len(non_dropped)}"
        )
        assert non_dropped[0]["id"] == scn["ps_rows"][1]["id"]
        resp = api.list_assignments(
            PM, params={"project_store_id": scn["ps_rows"][0]["id"]}
        )
        asgs, _ = validate_paginated(resp)
        open_states = {"SCHEDULED", "EN_ROUTE", "ON_SITE"}
        assert all(a["status"] not in open_states for a in asgs), (
            "no assignment of the dropped store may remain non-terminal"
        )
        assert get_assignment(asg["id"])["status"] == "CANCELLED"

    def test_cancel_en_route_assignment_reverts_store_to_pending(self, api):
        """PRD 3.3: "A `ProjectManager` may cancel an assignment while it is
        `SCHEDULED` or `EN_ROUTE`. Cancellation moves the assignment to
        `CANCELLED`, reverts the store row from `ASSIGNED` back to `PENDING`,
        and clears the row's `assigned_rep_id`."

        Design: Difficulty/compensating_invariant/store_list_count_conserved_under_cancel_and_drop
        """
        scn = make_scenario(num_stores=2)
        rep = scn["reps"][0]
        asg = schedule_assignment(
            scn["project"]["id"], scn["ps_rows"][0]["id"], rep["id"]
        )
        depart_assignment(asg["id"], rep["id"])
        assert get_assignment(asg["id"])["status"] == "EN_ROUTE"
        resp = api.cancel_assignment(asg["id"], PM)
        assert validate_success(resp)["status"] == "CANCELLED"
        ps = get_project_store(scn["ps_rows"][0]["id"])
        assert ps["status"] == "PENDING"
        assert ps.get("assigned_rep_id") in (None, "")
        # the freed store row accepts a fresh assignment (PENDING again)
        fresh = schedule_assignment(
            scn["project"]["id"], scn["ps_rows"][0]["id"], rep["id"],
            scheduled_start="2026-08-06T09:00:00Z",
            scheduled_end="2026-08-06T11:00:00Z",
        )
        assert fresh["status"] == "SCHEDULED"


class TestProjectCancelCascade:
    def test_project_cancel_cascades_assignments(self, api):
        """PRD 3.2: "Cancelling from `IN_FIELD` drops every row in `PENDING`,
        `ASSIGNED`, `IN_PROGRESS`, or `REWORK_REQUIRED` to `DROPPED`, cancels
        every assignment in `SCHEDULED` or `EN_ROUTE`, and clears each affected
        store row's `assigned_rep_id`. Every cancellation increments the
        project's `version` by 1 and lands the project in the terminal
        `CANCELLED` state."

        Design: Corner/state_machines/project_cancel_cascades_assignments
        """
        scn = make_scenario()
        rep = scn["reps"][0]
        asg = schedule_assignment(
            scn["project"]["id"], scn["ps_rows"][0]["id"], rep["id"]
        )
        assert get_project(scn["project"]["id"])["status"] == "IN_FIELD"
        resp = api.cancel_project(scn["project"]["id"], PM)
        project = validate_success(resp)
        assert project["status"] == "CANCELLED"
        ps = get_project_store(scn["ps_rows"][0]["id"])
        assert ps["status"] == "DROPPED"
        assert ps.get("assigned_rep_id") in (None, "")
        assert get_assignment(asg["id"])["status"] == "CANCELLED"


class TestPostureReconciliation:
    def test_posture_rederived_across_penalty_events(self, api):
        """PRD 2.9: "Six operational events feed it: rejecting a submitted
        visit adds 10; a client denying a rework authorization adds 5; a rework
        authorization expiring past the store's due date adds 7; a fixture
        shipment entering a delivery exception adds 3; a fixture shipment
        delivered after its promised date adds 5; and a fixture shipment
        declared lost adds 8. From the score the system derives the project's
        `posture`: `NORMAL` while the score is below 20, `WATCH` once the score
        reaches at least 20 but remains below 40, and `ESCALATED` once the
        score reaches at least 40."
        PRD 3.5: "Denial moves the authorization `REQUESTED` to `DENIED` and
        adds 5 to the project's `rework_penalty_score`, re-deriving `posture`."

        Design: Corner/cross_cutting_layers/derived_field_project_posture_reconciliation
        """
        scn = make_scenario(scope_type="FIXTURE_INSTALL", due_date="2026-08-20")
        ship_1 = create_shipment(
            scn["project"]["id"], scn["ps_rows"][0]["id"],
            promised_date="2026-08-15", tracking_number="1ZDF",
        )
        scan_shipment(ship_1["id"], "IN_TRANSIT")
        scan_shipment(ship_1["id"], "DELIVERED")  # on time: gate lifted
        asg, visit = visit_store(scn, outcome="reject")  # +10
        project = get_project(scn["project"]["id"])
        assert project["rework_penalty_score"] == 10
        assert project["posture"] == "NORMAL"
        auth = find_rework_auth(scn["ps_rows"][0]["id"], status="REQUESTED")
        deny_rework_auth(auth["id"], scn["client"]["id"])  # +5
        project = get_project(scn["project"]["id"])
        assert project["rework_penalty_score"] == 15, (
            f"10 (reject) + 5 (deny) = 15, got {project['rework_penalty_score']}"
        )
        assert project["posture"] == "NORMAL", "15 stays below the WATCH threshold"
        ship_2 = create_shipment(
            scn["project"]["id"], scn["ps_rows"][0]["id"],
            promised_date="2026-08-18", tracking_number="1ZDF2",
        )
        scan_shipment(ship_2["id"], "IN_TRANSIT")
        lost = scan_shipment(ship_2["id"], "LOST")  # +8
        assert lost["status"] == "LOST"
        project = get_project(scn["project"]["id"])
        assert project["rework_penalty_score"] == 23, (
            f"10 + 5 + 8 = 23, got {project['rework_penalty_score']}"
        )
        assert project["posture"] == "WATCH", (
            f"23 crosses the WATCH threshold, got {project['posture']}"
        )
