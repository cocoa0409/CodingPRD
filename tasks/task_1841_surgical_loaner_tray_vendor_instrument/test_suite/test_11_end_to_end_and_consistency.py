"""End-to-end happy path, vendor exposure rollup filtering, and the
immediate-consistency guarantee on mutation responses."""
from test_helpers import (
    COORD_1,
    COORD_2,
    add_tray,
    assert_same_instant,
    coordinator,
    create_case,
    create_credentialed_rep,
    create_pickup,
    create_request,
    create_room,
    create_vendor,
    deliver_and_verify,
    get_success_data,
    list_claims_of_request,
    list_penalties_of_request,
    make_scheduler_headers,
    reconcile,
    rep_headers,
    set_clock,
    setup_approved_request,
    setup_assessed_penalty,
    sterilize_and_stage,
    submit_request,
    validate_paginated,
    validate_success,
)
from test_helpers.factories import (
    decide_request_payload,
    pickup_line,
    settle_penalty_payload,
)

SCHEDULER = make_scheduler_headers()


class TestFullHappyPathLifecycle:
    def test_full_happy_path_lifecycle_end_to_end(self, api):
        """PRD: "it computes `required_delivery_by` as the case's
        `scheduled_start_at` minus the priority lead time"
        PRD: "Trays of linked requests that stood `STAGED` move to `IN_USE`."
        PRD: "Completion then cascades across every tray of every linked
        request: trays `IN_USE` move through `USED` to `AWAITING_PICKUP` in
        the same cascade"
        PRD: "when a pickup reconciliation leaves every tray of a request in
        a terminal state (`RECONCILED` or `CANCELLED`) and the linked case is
        `COMPLETED`, the request bubbles up from `APPROVED` to `CLOSED` and
        its `version` increments."

        Design: Corner/endpoints/full_happy_path_lifecycle_end_to_end
        """
        world = setup_approved_request()
        tray = world["trays"][0]
        assert_same_instant(world["request"]["required_delivery_by"],
                            "2026-08-02T09:00:00Z",
                            "request.required_delivery_by")

        # Delivery on time: no penalty at all.
        ci = deliver_and_verify(world, at="2026-08-02T08:00:00Z")
        assert_same_instant(ci["delivered_at"], "2026-08-02T08:00:00Z",
                            "checkin.delivered_at")
        assert ci["late_minutes"] == 0
        assert list_penalties_of_request(world["request"]["id"]) == []

        sterilize_and_stage(world, tray["id"])
        ready = validate_success(
            api.get_request(world["request"]["id"], SCHEDULER))
        assert ready["readiness"] == "READY"

        started = validate_success(
            api.start_case(world["case"]["id"], {}, SCHEDULER))
        assert started["status"] == "IN_PROGRESS"
        assert validate_success(
            api.get_tray(tray["id"], SCHEDULER))["status"] == "IN_USE"

        set_clock("2026-08-03T12:30:00Z")
        get_success_data(api.complete_case(world["case"]["id"], SCHEDULER))
        assert validate_success(
            api.get_tray(tray["id"], SCHEDULER))["status"] == "AWAITING_PICKUP"

        pickup = create_pickup(world, [pickup_line(tray["id"], 50, "OK")])
        reconciled = reconcile(world, pickup["id"], reconciler_id=COORD_2)
        assert reconciled["status"] == "RECONCILED"
        assert reconciled["discrepancy_count"] == 0
        assert list_claims_of_request(world["request"]["id"]) == [], \
            "no shortage and no damage: no claims"

        assert validate_success(
            api.get_tray(tray["id"], SCHEDULER))["status"] == "RECONCILED"
        request_after = validate_success(
            api.get_request(world["request"]["id"], SCHEDULER))
        assert request_after["status"] == "CLOSED"
        vendor = validate_success(api.get_vendor(world["vendor"]["id"],
                                                 coordinator()))
        assert vendor["outstanding_penalty_cents"] == 0
        assert vendor["outstanding_liability_cents"] == 0


class TestVendorRollupFiltering:
    def test_vendor_rollup_status_filter_excludes_accruing_and_settled(self, api):
        """PRD: "`outstanding_penalty_cents` is the sum of `outstanding_cents`
        over exactly that vendor's penalty assessments whose status is
        `ASSESSED`. Penalties still `ACCRUING`, already `SETTLED`, closed as
        `WAIVED_CLOSED`, or annulled as `VOID` contribute nothing."

        Design: Corner/calculations/vendor_rollup_status_filter_excludes_accruing_and_settled
        """
        # rq1: penalty ASSESSED then fully SETTLED (contributes 0).
        world, penalty = setup_assessed_penalty(verifier_id=COORD_1)
        get_success_data(
            api.settle_penalty(penalty["id"], settle_penalty_payload(5000),
                               coordinator(COORD_2)))

        # rq2 (same vendor, case 2026-08-05 09:00): delivered 75 minutes late
        # and verified, but the case has not completed — the 5000 penalty
        # stays ACCRUING (contributes 0).
        case2 = create_case(world["room"]["id"], case_number="C-2",
                            scheduled_start_at="2026-08-05T09:00:00Z",
                            scheduled_end_at="2026-08-05T12:00:00Z")
        rq2 = create_request(case2["id"], world["vendor"]["id"], "URGENT")
        t2 = add_tray(rq2["id"], tray_code="TK-2")
        submit_request(rq2["id"])
        get_success_data(
            api.decide_request(rq2["id"], decide_request_payload("APPROVE"),
                               coordinator()))
        world2 = {**world, "case": case2, "request": rq2, "trays": [t2]}
        deliver_and_verify(world2, at="2026-08-04T10:15:00Z",
                           verifier_id=COORD_1)

        penalties2 = list_penalties_of_request(rq2["id"])
        assert len(penalties2) == 1
        assert penalties2[0]["status"] == "ACCRUING"
        assert penalties2[0]["time_charge_cents"] == 5000

        vendor = validate_success(api.get_vendor(world["vendor"]["id"],
                                                 coordinator()))
        assert vendor["outstanding_penalty_cents"] == 0, \
            "SETTLED and ACCRUING penalties are both excluded from the rollup"


class TestImmediateConsistency:
    def test_immediate_visibility_of_mutation_results(self, api):
        """PRD: "Every mutation is committed immediately and atomically with
        its cascades. When an operation touches several resources — for
        example a case completion cascading across trays, requests, and
        rollups — the response reflects all of those effects at once, and any
        subsequent read observes them."
        PRD: "Unless otherwise noted, operations that create or modify a
        resource will return the created or updated resource object in the
        data field."
        PRD: "The `response_type` is either "object" for a single resource or
        "array" for a list of resources."

        Design: Corner/consistency_model/immediate_visibility_of_mutation_results
        """
        # Build to SUBMITTED by hand so each mutation response is inspected.
        vendor = create_vendor()
        rep = create_credentialed_rep(vendor["id"])
        room = create_room()
        case = create_case(room["id"], case_number="C-1")
        request = create_request(case["id"], vendor["id"], "URGENT")
        tray = add_tray(request["id"])
        submitted = validate_success(
            api.submit_request(request["id"], SCHEDULER))
        set_clock("2026-08-02T08:00:00Z")

        # The decide response itself carries the recomputed fields.
        resp = api.decide_request(request["id"],
                                  decide_request_payload("APPROVE"),
                                  coordinator())
        body = resp.json()
        assert body["response_type"] == "object"
        assert isinstance(body["meta"].get("api_request_id"), str)
        approved = validate_success(resp)
        assert approved["status"] == "APPROVED"
        assert_same_instant(approved["required_delivery_by"],
                            "2026-08-02T09:00:00Z",
                            "request.required_delivery_by")
        assert approved["version"] == submitted["version"] + 1, \
            "the version increment is visible in the mutation response"

        # The check-in response itself carries the clock-stamped fields.
        ci_resp = api.create_check_in(
            request["id"],
            {"lines": [{"tray_id": tray["id"],
                        "instrument_count_delivered": 50}],
             "ifu_provided": True, "loaner_agreement_ref": "LA-1"},
            rep_headers(rep))
        ci = validate_success(ci_resp, 201)
        assert ci_resp.json()["response_type"] == "object"
        assert_same_instant(ci["delivered_at"], "2026-08-02T08:00:00Z",
                            "checkin.delivered_at")
        assert ci["status"] == "SUBMITTED"
