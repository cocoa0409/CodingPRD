"""Rights requests: parallel verification/fulfillment dimensions, routing
selector, task lifecycle bubble-ups, denial cascade, overdue flag (PRD §3.6)."""
from test_helpers import (
    ApiErrorId,
    DS,
    LC1,
    PA,
    assert_rights_request,
    create_consumer,
    create_consumer_and_request,
    create_data_system,
    create_rights_request_payload,
    create_verified_request_with_systems,
    get_success_data,
    make_consumer_headers,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestParallelDimensions:
    def test_rights_request_parallel_dimensions(self, api):
        """PRD §3.6: "When a DataSteward routes a request whose fulfillment_status
        is INTAKE and whose verification_status is VERIFIED — routing an
        unverified request is rejected with ERR_REQUEST_NOT_VERIFIED — the server
        selects the pool of DataSystem rows whose status is ACTIVE and whose
        stores_categories intersects the request's requested_categories with a
        non-empty intersection. The pool is ranked by created_at ascending; ties,
        which are possible under a fixed logical clock, are broken by system_key
        ascending, and id is never used as a tie-break."
        PRD §3.6: "A failed verification — the DataSteward's fail-verification
        action — sets verification_status to VERIFICATION_FAILED and, in a
        cross-dimension side effect, moves fulfillment_status from INTAKE to
        DENIED; no tasks exist yet at intake, so no task cascade runs."

        Design: Difficulty/non_linear_state_machine/rights_request_parallel_dimensions
        """
        consumer = create_consumer(email="tx@x.com", state_code="TX")
        sys_a = create_data_system(system_key="sys-a", stores_categories=["FINANCIAL"])
        sys_b = create_data_system(system_key="sys-b", stores_categories=["FINANCIAL", "HEALTH"])
        sys_c = create_data_system(system_key="sys-c", stores_categories=["BIOMETRIC"])

        req1 = get_success_data(api.create_rights_request(
            consumer["id"],
            create_rights_request_payload(request_type="ACCESS",
                                          requested_categories=["FINANCIAL"]),
            make_consumer_headers(consumer["id"])))

        # route while UNVERIFIED -> ERR_REQUEST_NOT_VERIFIED
        resp = api.route_rights_request(req1["id"], DS)
        validate_error(resp, ApiErrorId.ERR_REQUEST_NOT_VERIFIED)

        # fail-verification: cross-dimension cascade INTAKE -> DENIED
        failed = get_success_data(api.fail_verification_rights_request(req1["id"], DS))
        assert failed["verification_status"] == "VERIFICATION_FAILED"
        assert failed["fulfillment_status"] == "DENIED"

        # fresh request: verify leaves fulfillment at INTAKE (dimension independence)
        req2 = get_success_data(api.create_rights_request(
            consumer["id"],
            create_rights_request_payload(request_type="ACCESS",
                                          requested_categories=["FINANCIAL"]),
            make_consumer_headers(consumer["id"])))
        verified = get_success_data(api.verify_rights_request(req2["id"], DS))
        assert verified["verification_status"] == "VERIFIED"
        assert verified["fulfillment_status"] == "INTAKE"

        routed = get_success_data(api.route_rights_request(req2["id"], DS))
        assert routed["fulfillment_status"] == "ROUTED"

        tasks, meta = validate_paginated(api.list_request_tasks(req2["id"], DS))
        assert len(tasks) == 2, "sys-c stores no requested category and must be excluded"
        assert tasks[0]["data_system_id"] == sys_a["id"], (
            "created_at tie under the fixed clock is broken by system_key ascending"
        )
        assert tasks[1]["data_system_id"] == sys_b["id"]
        assert all(t["status"] == "PENDING" for t in tasks)

        # first task start bubbles the request ROUTED -> IN_PROGRESS
        get_success_data(api.start_task(tasks[0]["id"], DS))
        assert get_success_data(api.get_rights_request(req2["id"], DS))["fulfillment_status"] == "IN_PROGRESS"

        # completing one of two leaves the request IN_PROGRESS
        get_success_data(api.complete_task(tasks[0]["id"], {"outcome_notes": "exported"}, DS))
        assert get_success_data(api.get_rights_request(req2["id"], DS))["fulfillment_status"] == "IN_PROGRESS"

        # after both tasks are terminal the request is READY_TO_RESPOND
        get_success_data(api.start_task(tasks[1]["id"], DS))
        get_success_data(api.complete_task(tasks[1]["id"], headers=DS))
        assert get_success_data(api.get_rights_request(req2["id"], DS))["fulfillment_status"] == "READY_TO_RESPOND"

        completed = get_success_data(api.respond_rights_request(req2["id"], DS))
        assert completed["fulfillment_status"] == "COMPLETED"

    def test_verify_then_full_fulfillment_pipeline(self, api):
        """PRD §3.6: "A successful verify sets verification_status to VERIFIED
        and computes the final deadline."
        PRD §3.6: "Completing a task in IN_PROGRESS status — optionally carrying
        outcome_notes — moves it to COMPLETED; when every sibling task has
        reached a terminal status, COMPLETED or CANCELLED, the parent request
        bubbles from IN_PROGRESS to READY_TO_RESPOND. A DataSteward then responds
        to a request in READY_TO_RESPOND status — responding earlier is rejected
        with ERR_TASKS_OUTSTANDING — moving fulfillment_status to the terminal
        COMPLETED."

        Design: Difficulty/non_linear_state_machine/rights_request_parallel_dimensions
        """
        setup = create_verified_request_with_systems(
            systems=[{"system_key": "sys-a", "stores_categories": ["FINANCIAL"]},
                     {"system_key": "sys-b", "stores_categories": ["FINANCIAL", "HEALTH"]},
                     {"system_key": "sys-c", "stores_categories": ["BIOMETRIC"]}],
            email="pipe@x.com", request_type="ACCESS",
            requested_categories=["FINANCIAL"])
        request, tasks = setup["request"], setup["tasks"]
        assert request["verification_status"] == "VERIFIED"
        assert request["fulfillment_status"] == "ROUTED"
        assert len(tasks) == 2

        # first start bubbles ROUTED -> IN_PROGRESS
        get_success_data(api.start_task(tasks[0]["id"], DS))
        in_progress = get_success_data(api.get_rights_request(request["id"], DS))
        assert in_progress["fulfillment_status"] == "IN_PROGRESS"

        # complete both tasks -> READY_TO_RESPOND
        get_success_data(api.complete_task(tasks[0]["id"], {"outcome_notes": "done"}, DS))
        task0_after = get_success_data(api.get_task(tasks[0]["id"], DS))
        assert task0_after["status"] == "COMPLETED"
        assert task0_after["outcome_notes"] == "done"
        get_success_data(api.start_task(tasks[1]["id"], DS))
        get_success_data(api.complete_task(tasks[1]["id"], headers=DS))
        ready = get_success_data(api.get_rights_request(request["id"], DS))
        assert ready["fulfillment_status"] == "READY_TO_RESPOND"

        completed = get_success_data(api.respond_rights_request(request["id"], DS))
        assert completed["fulfillment_status"] == "COMPLETED"
        assert_rights_request(completed)


class TestDenialCascade:
    def test_deny_cancels_open_tasks(self, api):
        """PRD §3.6: "A LegalCounsel reviewer may instead deny a request in
        INTAKE, ROUTED, or IN_PROGRESS status, optionally supplying a reason;
        denial moves fulfillment_status to DENIED and cancels every task of the
        request in PENDING or IN_PROGRESS status, processed in created_at
        ascending order."

        Design: Corner/state_machines/deny_cancels_open_tasks
        """
        setup = create_verified_request_with_systems(
            systems=[{"system_key": "sys-a", "stores_categories": ["FINANCIAL"]},
                     {"system_key": "sys-b", "stores_categories": ["FINANCIAL"]}],
            email="deny@x.com", request_type="DELETION",
            requested_categories=["FINANCIAL"])
        request, tasks = setup["request"], setup["tasks"]
        assert len(tasks) == 2
        get_success_data(api.start_task(tasks[0]["id"], DS))

        denied = get_success_data(
            api.deny_rights_request(request["id"], {"reason": "bad faith"}, LC1))
        assert denied["fulfillment_status"] == "DENIED"

        t0_after = get_success_data(api.get_task(tasks[0]["id"], DS))
        t1_after = get_success_data(api.get_task(tasks[1]["id"], DS))
        assert t0_after["status"] == "CANCELLED", "IN_PROGRESS task is cancelled on deny"
        assert t1_after["status"] == "CANCELLED", "PENDING task is cancelled on deny"


class TestRoutingAndResponseGates:
    def test_err_no_systems_in_scope_on_empty_selector(self, api):
        """PRD §3.6: "An empty pool is rejected with ERR_NO_SYSTEMS_IN_SCOPE; the
        system performs no partial routing."
        PRD §3.6: "the server selects the pool of DataSystem rows whose status is
        ACTIVE and whose stores_categories intersects the request's
        requested_categories with a non-empty intersection."

        Design: Corner/errors/err_no_systems_in_scope_on_empty_selector
        """
        consumer = create_consumer(email="tx@x.com", state_code="TX")
        create_data_system(system_key="sys-a", stores_categories=["FINANCIAL"])
        request = get_success_data(api.create_rights_request(
            consumer["id"],
            create_rights_request_payload(request_type="ACCESS",
                                          requested_categories=["MINOR_DATA"]),
            make_consumer_headers(consumer["id"])))
        get_success_data(api.verify_rights_request(request["id"], DS))

        resp = api.route_rights_request(request["id"], DS)
        validate_error(resp, ApiErrorId.ERR_NO_SYSTEMS_IN_SCOPE)

        tasks, _meta = validate_paginated(api.list_request_tasks(request["id"], DS))
        assert tasks == [], "no partial routing: zero tasks created"
        after = get_success_data(api.get_rights_request(request["id"], DS))
        assert after["fulfillment_status"] == "INTAKE"

    def test_err_tasks_outstanding_on_early_respond(self, api):
        """PRD §3.6: "A DataSteward then responds to a request in
        READY_TO_RESPOND status — responding earlier is rejected with
        ERR_TASKS_OUTSTANDING — moving fulfillment_status to the terminal
        COMPLETED."

        Design: Corner/errors/err_tasks_outstanding_on_early_respond
        """
        setup = create_verified_request_with_systems(
            systems=[{"system_key": "sys-a", "stores_categories": ["FINANCIAL"]}],
            email="early@x.com", request_type="ACCESS",
            requested_categories=["FINANCIAL"])
        request = setup["request"]
        assert request["fulfillment_status"] == "ROUTED"

        resp = api.respond_rights_request(request["id"], DS)
        validate_error(resp, ApiErrorId.ERR_TASKS_OUTSTANDING)
        after = get_success_data(api.get_rights_request(request["id"], DS))
        assert after["fulfillment_status"] == "ROUTED"


class TestOverdueFlag:
    def test_request_overdue_flag_tracks_logical_clock(self, api):
        """PRD §3.6: "A request's is_overdue flag is true exactly when the
        logical clock is past the effective due date — final_due_at when the
        request is VERIFIED, else provisional_due_at — and the fulfillment_status
        is neither COMPLETED nor DENIED."
        PRD §2.5: "Before any test-driving call, the clock reads exactly
        2026-08-01T00:00:00Z; the clock never falls back to wall time at any
        point. A privacy administrator may advance the clock to a supplied
        to_iso8601 instant via an admin-only test-driving capability"

        Design: Corner/endpoints/request_overdue_flag_tracks_logical_clock
        """
        consumer, request = create_consumer_and_request(
            email="tx@x.com", state_code="TX", request_type="ACCESS",
            requested_categories=["BASIC_CONTACT"])

        before = get_success_data(api.get_rights_request(request["id"], DS))
        assert before["is_overdue"] is False, (
            "2026-08-01 is before the provisional due date 2026-09-15"
        )

        get_success_data(api.set_clock({"to_iso8601": "2026-10-01T00:00:00Z"}, PA))
        after = get_success_data(api.get_rights_request(request["id"], DS))
        assert after["is_overdue"] is True, (
            "2026-10-01 is past the provisional due date 2026-09-15 and the request "
            "is neither COMPLETED nor DENIED"
        )
