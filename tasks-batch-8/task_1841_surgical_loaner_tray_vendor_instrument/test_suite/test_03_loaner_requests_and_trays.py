"""Loaner request lifecycle: drafting, submission gates, approval-derived
deadlines, rejection, cancellation, tray manifest rules, and list behavior."""
from test_helpers import (
    CLOCK_DEFAULT,
    ApiErrorId,
    add_tray,
    assert_loaner_request,
    assert_loaner_tray,
    assert_same_instant,
    coordinator,
    create_case,
    create_request,
    create_room,
    create_vendor,
    get_success_data,
    make_scheduler_headers,
    submit_request,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.factories import (
    create_request_payload,
    create_tray_payload,
    decide_request_payload,
)


def _vendor_and_case(case_start="2026-08-10T09:00:00Z",
                     case_end="2026-08-10T12:00:00Z"):
    vendor = create_vendor()
    room = create_room()
    case = create_case(room["id"], case_number="C-1",
                       scheduled_start_at=case_start,
                       scheduled_end_at=case_end)
    return vendor, case


class TestRequestCreation:
    def test_request_create_initial_readiness_not_ready(self, api):
        """PRD: "A new request begins as `DRAFT` with readiness `NOT_READY`, a
        null `required_delivery_by`, a null `submitted_at`, and a
        `penalty_exposure_cents` of 0."

        Design: Corner/entities/request_create_initial_readiness_not_ready
        """
        vendor, case = _vendor_and_case()
        request = validate_success(
            api.create_request(
                create_request_payload(case["id"], vendor["id"],
                                       priority_class="URGENT"),
                make_scheduler_headers()), 201)
        assert_loaner_request(request)
        assert request["status"] == "DRAFT"
        assert request["readiness"] == "NOT_READY"
        assert request["required_delivery_by"] is None
        assert request["submitted_at"] is None
        assert request["penalty_exposure_cents"] == 0

    def test_create_request_invalid_enum_rejected(self, api):
        """PRD: "the payload names the `case_id` of the surgical case and the
        `vendor_id` of the supplying vendor, plus a `priority_class` of
        `STANDARD`, `URGENT`, or `EMERGENT`."
        PRD: "**Body well-formedness** — the request body parses, contains every
        required field, and every field has a valid type and, where enumerated,
        a valid enum member, else `ERR_VALIDATION` (400)."

        Design: Corner/entities/create_request_invalid_enum_rejected
        """
        vendor, case = _vendor_and_case()
        resp = api.create_request(
            create_request_payload(case["id"], vendor["id"],
                                   priority_class="STAT"),
            make_scheduler_headers())
        validate_error(resp, ApiErrorId.ERR_VALIDATION)
        _rows, meta = validate_paginated(
            api.list_requests(make_scheduler_headers()))
        assert meta["total_count"] == 0


class TestRequestLists:
    def test_list_requests_pagination_filter(self, api):
        """PRD: "The `limit` parameter specifies the maximum number of items
        to return; if not provided it defaults to 10, with a minimum of 1 and
        a maximum of 100. The `offset` parameter specifies the number of items
        to skip and defaults to 0."
        PRD: "Paginated list responses include the following fields in the
        `meta` object of the response envelope: `limit`, `offset`,
        `total_count`, and `has_more`."
        PRD: "The request list can be filtered by `case_id`, `vendor_id`,
        `status`, or `readiness`."

        Design: Corner/entities/list_requests_pagination_filter
        """
        vendor, case = _vendor_and_case()
        create_request(case["id"], vendor["id"], "STANDARD")
        create_request(case["id"], vendor["id"], "URGENT")

        page1, meta1 = validate_paginated(
            api.list_requests(coordinator(),
                              params={"vendor_id": vendor["id"], "limit": 1,
                                      "offset": 0}))
        assert meta1["total_count"] == 2
        assert meta1["has_more"] is True
        assert len(page1) == 1

        page2, meta2 = validate_paginated(
            api.list_requests(coordinator(),
                              params={"vendor_id": vendor["id"], "limit": 1,
                                      "offset": 1}))
        assert meta2["total_count"] == 2
        assert meta2["has_more"] is False
        assert len(page2) == 1
        assert page1[0]["id"] != page2[0]["id"], "pages must be disjoint"

    def test_trays_subresource_scoped_to_parent_request(self, api):
        """PRD: "Many resources live under others: trays, check-ins,
        escalations, and pickups under a loaner request; turns and claims
        under a tray; delay events under a case; representatives under a
        vendor"
        PRD: "The tray list can be filtered by `request_id` or `status`."

        Design: Corner/entities/trays_subresource_scoped_to_parent_request
        """
        vendor, case = _vendor_and_case()
        rq1 = create_request(case["id"], vendor["id"], "STANDARD")
        rq2 = create_request(case["id"], vendor["id"], "STANDARD")
        tray_a = add_tray(rq1["id"], tray_code="TK-A",
                          declared_instrument_count=5,
                          replacement_value_cents=1000)
        add_tray(rq2["id"], tray_code="TK-B", declared_instrument_count=5,
                 replacement_value_cents=1000)

        rows, meta = validate_paginated(
            api.list_request_trays(rq1["id"], coordinator()))
        assert meta["total_count"] == 1
        assert len(rows) == 1
        assert rows[0]["id"] == tray_a["id"]
        assert rows[0]["tray_code"] == "TK-A", \
            "the nested list must only contain the path request's trays"


class TestSubmitAndApprove:
    def test_request_submit_and_approve_happy_path(self, api):
        """PRD: "A successful submit stamps `submitted_at` with the clock,
        moves the request to `SUBMITTED`, and increments its `version`."
        PRD: "it computes `required_delivery_by` as the case's
        `scheduled_start_at` minus the priority lead time, sets every tray's
        `required_sterile_ready_by` to the case's start minus one hour of
        preparation buffer while clearing each tray's
        `projected_sterile_ready_at` to null, and recomputes readiness — which
        at this point is invariably `NOT_READY`, since every tray is still
        `EXPECTED`."
        PRD: "The priority class selects the contractual lead time baked into
        every downstream deadline: forty-eight hours for `STANDARD`,
        twenty-four hours for `URGENT`, and twelve hours for `EMERGENT`."

        Design: Corner/state_machines/request_submit_and_approve_happy_path
        """
        vendor, case = _vendor_and_case(case_start="2026-08-03T09:00:00Z",
                                        case_end="2026-08-03T12:00:00Z")
        request = create_request(case["id"], vendor["id"], "URGENT")
        tray = add_tray(request["id"])

        submitted = validate_success(api.submit_request(request["id"],
                                                        make_scheduler_headers()))
        assert submitted["status"] == "SUBMITTED"
        assert_same_instant(submitted["submitted_at"], CLOCK_DEFAULT,
                            "request.submitted_at")
        assert submitted["version"] == request["version"] + 1

        approved = validate_success(
            api.decide_request(request["id"], decide_request_payload("APPROVE"),
                               coordinator()))
        assert approved["status"] == "APPROVED"
        assert_same_instant(approved["required_delivery_by"],
                            "2026-08-02T09:00:00Z",
                            "request.required_delivery_by")
        assert approved["readiness"] == "NOT_READY", \
            "every tray is still EXPECTED at approval"

        tray_after = validate_success(api.get_tray(tray["id"], coordinator()))
        assert_loaner_tray(tray_after)
        assert_same_instant(tray_after["required_sterile_ready_by"],
                            "2026-08-03T08:00:00Z",
                            "tray.required_sterile_ready_by")
        assert tray_after["projected_sterile_ready_at"] is None

    def test_delivery_deadline_per_priority_class(self, api):
        """PRD: "The priority class selects the contractual lead time baked
        into every downstream deadline: forty-eight hours for `STANDARD`,
        twenty-four hours for `URGENT`, and twelve hours for `EMERGENT`."
        PRD: "it computes `required_delivery_by` as the case's
        `scheduled_start_at` minus the priority lead time"

        Design: Corner/calculations/delivery_deadline_per_priority_class
        """
        vendor, case = _vendor_and_case(case_start="2026-08-10T12:00:00Z",
                                        case_end="2026-08-10T15:00:00Z")
        expected = {
            "STANDARD": "2026-08-08T12:00:00Z",
            "URGENT": "2026-08-09T12:00:00Z",
            "EMERGENT": "2026-08-10T00:00:00Z",
        }
        for priority, expected_deadline in expected.items():
            request = create_request(case["id"], vendor["id"], priority)
            add_tray(request["id"], tray_code=f"T-{priority}",
                     declared_instrument_count=5, replacement_value_cents=1000)
            submit_request(request["id"])
            approved = validate_success(
                api.decide_request(request["id"],
                                   decide_request_payload("APPROVE"),
                                   coordinator()))
            assert_same_instant(approved["required_delivery_by"],
                                expected_deadline,
                                f"{priority} required_delivery_by")

    def test_request_submit_twice_rejected(self, api):
        """PRD: "Submitting is gated twice, and the gates are evaluated after
        the state guard that requires the request to be `DRAFT`."
        PRD: "Beyond the lifecycle operations, every request-scoped action —
        delivery check-in, pickup, manual escalation — first confirms the
        request is in a state that permits it and otherwise rejects with
        `ERR_REQUEST_INVALID_STATE` (409)."

        Design: Corner/state_machines/request_submit_twice_rejected
        """
        vendor, case = _vendor_and_case()
        request = create_request(case["id"], vendor["id"], "STANDARD")
        add_tray(request["id"])
        submit_request(request["id"])

        resp = api.submit_request(request["id"], make_scheduler_headers())
        validate_error(resp, ApiErrorId.ERR_REQUEST_INVALID_STATE)
        assert validate_success(
            api.get_request(request["id"], coordinator()))["status"] == "SUBMITTED"

    def test_request_submit_without_trays_rejected(self, api):
        """PRD: "A request with no trays at all is rejected with
        `ERR_REQUEST_NO_TRAYS` (409)."

        Design: Corner/state_machines/request_submit_without_trays_rejected
        """
        vendor, case = _vendor_and_case()
        request = create_request(case["id"], vendor["id"], "STANDARD")
        resp = api.submit_request(request["id"], make_scheduler_headers())
        validate_error(resp, ApiErrorId.ERR_REQUEST_NO_TRAYS)
        assert validate_success(
            api.get_request(request["id"], coordinator()))["status"] == "DRAFT"

    def test_submit_deadline_infeasible_rejected(self, api):
        """PRD: "The deadline must also be feasible: the case's
        `scheduled_start_at` minus the current time must be at least the lead
        time of the request's `priority_class`, else the submission is
        rejected with `ERR_REQUEST_DEADLINE_INFEASIBLE` (422)."
        PRD: "The priority class selects the contractual lead time baked into
        every downstream deadline: forty-eight hours for `STANDARD`,
        twenty-four hours for `URGENT`, and twelve hours for `EMERGENT`."

        Design: Corner/validations/submit_deadline_infeasible_rejected
        """
        # Clock is at its default; the case starts 20 hours from now.
        vendor, case = _vendor_and_case(case_start="2026-08-01T20:00:00Z",
                                        case_end="2026-08-01T23:00:00Z")
        rq_urg = create_request(case["id"], vendor["id"], "URGENT")
        add_tray(rq_urg["id"], tray_code="T-U", declared_instrument_count=5,
                 replacement_value_cents=1000)
        rq_emg = create_request(case["id"], vendor["id"], "EMERGENT")
        add_tray(rq_emg["id"], tray_code="T-E", declared_instrument_count=5,
                 replacement_value_cents=1000)

        # 20h < 24h lead: URGENT cannot be submitted.
        resp = api.submit_request(rq_urg["id"], make_scheduler_headers())
        validate_error(resp, ApiErrorId.ERR_REQUEST_DEADLINE_INFEASIBLE)
        # 20h >= 12h lead: EMERGENT can.
        submitted = validate_success(api.submit_request(rq_emg["id"],
                                                        make_scheduler_headers()))
        assert submitted["status"] == "SUBMITTED"


class TestRequestTerminalStates:
    def test_request_reject_is_terminal(self, api):
        """PRD: "Rejection moves the request to terminal `REJECTED`."
        PRD: "Beyond the lifecycle operations, every request-scoped action —
        delivery check-in, pickup, manual escalation — first confirms the
        request is in a state that permits it and otherwise rejects with
        `ERR_REQUEST_INVALID_STATE` (409)."

        Design: Corner/state_machines/request_reject_is_terminal
        """
        vendor, case = _vendor_and_case()
        request = create_request(case["id"], vendor["id"], "STANDARD")
        add_tray(request["id"])
        submit_request(request["id"])
        rejected = validate_success(
            api.decide_request(request["id"],
                               decide_request_payload("REJECT",
                                                      reason="vendor backlog"),
                               coordinator()))
        assert rejected["status"] == "REJECTED"

        resp = api.decide_request(request["id"],
                                  decide_request_payload("APPROVE"),
                                  coordinator())
        validate_error(resp, ApiErrorId.ERR_REQUEST_INVALID_STATE)
        resp2 = api.cancel_request(request["id"], make_scheduler_headers())
        validate_error(resp2, ApiErrorId.ERR_REQUEST_INVALID_STATE)
        assert validate_success(
            api.get_request(request["id"], coordinator()))["status"] == "REJECTED"

    def test_request_cancel_from_draft(self, api):
        """PRD: "A scheduler may also cancel a request from `DRAFT`,
        `SUBMITTED`, or `APPROVED`; cancellation is terminal `CANCELLED`"
        PRD: "Beyond the lifecycle operations, every request-scoped action —
        delivery check-in, pickup, manual escalation — first confirms the
        request is in a state that permits it and otherwise rejects with
        `ERR_REQUEST_INVALID_STATE` (409)."

        Design: Corner/state_machines/request_cancel_from_draft
        """
        vendor, case = _vendor_and_case()
        request = create_request(case["id"], vendor["id"], "STANDARD")
        cancelled = validate_success(api.cancel_request(request["id"],
                                                        make_scheduler_headers()))
        assert cancelled["status"] == "CANCELLED"

        resp = api.submit_request(request["id"], make_scheduler_headers())
        validate_error(resp, ApiErrorId.ERR_REQUEST_INVALID_STATE)


class TestTrayManifest:
    def test_duplicate_tray_code_in_request_rejected(self, api):
        """PRD: "Each tray is declared with a `tray_code` unique within its
        request (a repeat is rejected with `ERR_DUPLICATE_TRAY_CODE` at 409)"

        Design: Corner/validations/duplicate_tray_code_in_request_rejected
        """
        vendor, case = _vendor_and_case()
        rq1 = create_request(case["id"], vendor["id"], "STANDARD")
        rq2 = create_request(case["id"], vendor["id"], "STANDARD")
        add_tray(rq1["id"], tray_code="TK-1")

        resp = api.add_tray(rq1["id"],
                            create_tray_payload(tray_code="TK-1",
                                                declared_instrument_count=10,
                                                replacement_value_cents=5000),
                            make_scheduler_headers())
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_TRAY_CODE)

        # Uniqueness is scoped to the request: the same code is fine elsewhere.
        other = validate_success(
            api.add_tray(rq2["id"],
                         create_tray_payload(tray_code="TK-1",
                                             declared_instrument_count=10,
                                             replacement_value_cents=5000),
                         make_scheduler_headers()), 201)
        assert other["status"] == "EXPECTED"
