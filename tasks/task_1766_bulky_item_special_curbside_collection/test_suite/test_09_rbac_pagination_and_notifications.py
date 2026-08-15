"""RBAC denials, authentication, settlement ownership, pagination envelope,
notification side effects, version bookkeeping, and schedule fan-out."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_item,
    cancel_payload,
    create_draft_request,
    create_household,
    create_household_payload,
    create_pickup_request_payload,
    create_route_day,
    create_route_day_payload,
    find_assessment,
    get_ledger_row,
    get_request,
    get_request_assessments,
    get_request_items,
    get_request_notifications,
    get_route_day,
    get_success_data,
    make_resident_headers,
    schedule_request,
    set_clock,
    setup_completed_request,
    setup_scheduled_request,
    setup_submitted_request,
    submit_request,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    validate_success,
)

DISPATCHER = TEST_USERS["dispatcher_headers"]
INSPECTOR = TEST_USERS["inspector_headers"]
DRIVER = TEST_USERS["driver_headers"]


class TestRbacDenials:
    def test_resident_cannot_create_route_day(self, api):
        """PRD §2.1: "Only a `Dispatcher` may register households, create and
        dispatch or close route days, declare or cancel amnesty windows, waive
        fees, and advance the logical clock."
        PRD §2.1: "A request whose role is recognized but not permitted on the
        target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)."

        Design: Corner/rbac/resident_cannot_create_route_day
        """
        hh = create_household("111 RBAC Rd", "ZONE_WEST")
        resp = api.create_route_day(
            create_route_day_payload(
                service_zone="ZONE_WEST", route_date="2026-08-10"
            ),
            make_resident_headers(hh["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
        assert resp.status_code == 403

    def test_unauthenticated_request_rejected(self, api):
        """PRD §2.1: "Every API call must present two headers: `X-User-ID`,
        identifying the acting party, and `X-User-Role`, naming their
        operational capacity. The recognized roles are exactly `Resident`,
        `Driver`, `Inspector`, and `Dispatcher`. A request missing either
        header, or carrying a role the system does not recognize, is rejected
        with `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/rbac/unauthenticated_request_rejected
        """
        resp = api.list_route_days(headers={})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)
        assert resp.status_code == 401


class TestSettlementOwnership:
    def test_settle_by_non_owner_resident_forbidden(self, api):
        """PRD §2.1: "When `X-User-Role` is `Resident`, `X-User-ID` is the
        `id` of the acting `Household`; ownership checks on any
        household-scoped resource — a pickup request, its items, its fee
        assessments, its notifications, its allowance ledger rows — compare
        the resource's owning `household_id` to `X-User-ID`, and a mismatch is
        rejected with `ERR_FORBIDDEN`."
        PRD §2.9: "(2) authorization — role permitted and, for `Resident`
        calls on household-scoped resources, `X-User-ID` equals the owning
        household's id, else `ERR_FORBIDDEN`"
        PRD §3.5: "Settling requires the assessment to be `PENDING` and the
        acting resident's identity to match the assessment's `household_id`;
        settling a non-pending assessment or one belonging to another
        household fails with `ERR_ASSESSMENT_NOT_SETTLABLE`."

        PRD names both error_ids verbatim for this exact scenario (§2.1/§2.9
        ownership-mismatch -> ERR_FORBIDDEN at priority 2; §3.5
        scenario-specific sentence -> ERR_ASSESSMENT_NOT_SETTLABLE at
        priority 13), so either outcome is PRD-faithful. What both readings
        agree on: the settle is rejected and the assessment stays PENDING.

        Design: Corner/validations/settle_by_non_owner_resident_forbidden
        """
        hh1, req, _, _ = setup_completed_request(
            street_address="91 Owner Ave", service_zone="ZONE_SOUTH",
            items=((1, "MATTRESS", False, True),),
        )
        hh2 = create_household("92 Owner Ave", "ZONE_SOUTH")

        invoice = find_assessment(
            get_request_assessments(req["id"]), "FINAL_INVOICE"
        )
        assert invoice["status"] == "PENDING"

        resp = api.settle_fee_assessment(
            invoice["id"], make_resident_headers(hh2["id"])
        )
        validate_error_is_one_of(
            resp,
            [ApiErrorId.ERR_FORBIDDEN, ApiErrorId.ERR_ASSESSMENT_NOT_SETTLABLE],
        )
        assert resp.status_code in (403, 409)

        after = get_success_data(api.get_fee_assessment(invoice["id"], INSPECTOR))
        assert after["status"] == "PENDING"


class TestPaginationEnvelope:
    def test_list_pagination_envelope(self, api):
        """PRD §2.3: "List endpoints accept two query parameters. `limit` caps
        the number of items returned: it defaults to 10, accepts a minimum of
        1 and a maximum of 100. `offset` skips that many items from the front
        of the result set and defaults to 0. Unless a listing states
        otherwise, results are sorted by `created_at` in ascending order.
        Every list response carries `limit`, `offset`, `total_count`, and
        `has_more` in the `meta` object of the envelope."

        Design: Corner/endpoints/list_pagination_envelope
        """
        set_clock("2026-08-05T00:00:00Z")
        hh = create_household("97 Page Pl", "ZONE_WEST")
        for _ in range(3):
            create_draft_request(hh["id"])

        resp = api.list_pickup_requests(
            DISPATCHER, params={"household_id": hh["id"], "limit": 2, "offset": 0}
        )
        data, meta = validate_paginated(resp)
        assert len(data) == 2
        assert meta["total_count"] == 3
        assert meta["has_more"] is True

        resp2 = api.list_pickup_requests(
            DISPATCHER, params={"household_id": hh["id"], "limit": 2, "offset": 2}
        )
        data2, meta2 = validate_paginated(resp2)
        assert len(data2) == 1
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False


class TestScheduleConfirmationNotification:
    def test_schedule_confirmation_notification_side_effect(self, api):
        """PRD §3.3: "A Notification of `kind` `SCHEDULE_CONFIRMATION` is
        emitted, and the request's `version` increments."
        PRD §3.6: "`reason_code` is null whenever the notice kind carries no
        driver reason."

        Design: Corner/endpoints/schedule_confirmation_notification_side_effect
        """
        set_clock("2026-08-05T00:00:00Z")
        hh, req, _, rd = setup_scheduled_request(
            street_address="95 Notify Nook", service_zone="ZONE_EAST",
            items=((1, "ELECTRONICS", False, True),),
        )
        notices = get_request_notifications(
            req["id"], make_resident_headers(hh["id"])
        )
        confirmations = [n for n in notices if n["kind"] == "SCHEDULE_CONFIRMATION"]
        assert len(confirmations) == 1
        assert confirmations[0]["reason_code"] is None


class TestVersionBookkeeping:
    def test_version_increments_on_every_mutation(self, api):
        """PRD §2.5: "`version` (integer): starts at 1 at creation and
        increments by exactly 1 on every mutation, including mutations caused
        by system cascades rather than direct client writes."
        PRD §3.2: "Adding or removing an item recomputes the request's
        `load_units` and bumps the request's `version` by 1"

        Design: Corner/cross_cutting_layers/version_increments_on_every_mutation
        """
        set_clock("2026-08-05T00:00:00Z")
        hh = create_household("113 Version Vw", "ZONE_NORTH")
        rd = create_route_day(service_zone="ZONE_NORTH", route_date="2026-08-10")

        req = create_draft_request(hh["id"])
        assert req["version"] == 1

        add_item(hh["id"], req["id"], 1, "TIRES", False, True)
        assert get_request(hh["id"], req["id"])["version"] == 2

        submitted = submit_request(hh["id"], req["id"])
        assert submitted["version"] == 3


        scheduled = schedule_request(hh["id"], req["id"], rd)
        assert scheduled["version"] == 4

        # The schedule cascade bumps the route's version exactly once.
        assert get_route_day(rd["id"])["version"] == 2


class TestScheduleCascadeChain:
    def test_cascade_chain_schedule_through_route_and_ledger(self, api):
        """PRD §3.3: "When all gates pass, the transition into `SCHEDULED`
        does the following, atomically. It stamps `route_day_id` and copies
        `scheduled_date` from the route's `route_date`; that date fixes the
        allowance ledger's `calendar_year`."
        PRD §3.3: "The route absorbs the commitment: `committed_load_units`
        rises by the request's `load_units` and `committed_stops` by 1,
        bumping the RouteDay's `version` by 1. A Notification of `kind`
        `SCHEDULE_CONFIRMATION` is emitted, and the request's `version`
        increments."

        Design: Corner/cross_cutting_layers/cascade_chain_schedule_through_route_and_ledger
        """
        set_clock("2026-08-05T00:00:00Z")
        rd = create_route_day(service_zone="ZONE_SOUTH", route_date="2026-08-10")
        hh, req, _ = setup_submitted_request(
            street_address="115 Cascade Ct", service_zone="ZONE_SOUTH",
            annual_allowance_items=2,
            items=(
                (1, "STANDARD_FURNITURE", False, True),
                (2, "STANDARD_FURNITURE", False, True),
                (3, "STANDARD_FURNITURE", False, True),
            ),
        )
        resp = api.schedule_pickup_request(
            req["id"],
            {"route_day_id": rd["id"],
             "expected_route_day_version": rd["version"]},
            make_resident_headers(hh["id"]),
        )
        data = validate_success(resp)
        assert data["status"] == "SCHEDULED"
        assert data["route_day_id"] == rd["id"]
        assert data["scheduled_date"] == "2026-08-10"
        # 2 items free; item 3 over-allowance: 2500 + 213 = 2713.
        assert data["provisional_total_cents"] == 2713

        route = get_route_day(rd["id"])
        assert route["committed_load_units"] == 6
        assert route["committed_stops"] == 1

        ledger = get_ledger_row(hh["id"], 2026)
        assert ledger["items_consumed"] == 2
        assert ledger["over_allowance_items"] == 1

        items = get_request_items(req["id"], INSPECTOR)
        by_seq = {i["sequence_no"]: i for i in items}
        assert by_seq[1]["within_allowance"] is True
        assert by_seq[2]["within_allowance"] is True
        assert by_seq[3]["within_allowance"] is False
        assert by_seq[3]["item_fee_cents"] == 2713

        notices = get_request_notifications(req["id"], INSPECTOR)
        assert len([n for n in notices if n["kind"] == "SCHEDULE_CONFIRMATION"]) == 1


class TestImmediateConsistency:
    def test_immediate_visibility_of_schedule_effects(self, api):
        """PRD §2.2: "Unless otherwise noted, operations that create or modify
        a resource will return the created or updated resource object in the
        data field."
        PRD §3.3: "The rewritten `item_fee_cents` and
        `provisional_total_cents` replace the worst-case estimate."

        Design: Corner/consistency_model/immediate_visibility_of_schedule_effects
        """
        set_clock("2026-08-05T00:00:00Z")
        rd = create_route_day(service_zone="ZONE_WEST", route_date="2026-08-10")
        hh, req, _ = setup_submitted_request(
            street_address="117 Immediate Isle", service_zone="ZONE_WEST",
            annual_allowance_items=4,
            items=((1, "MATTRESS", False, True),),
        )
        resp = api.schedule_pickup_request(
            req["id"],
            {"route_day_id": rd["id"],
             "expected_route_day_version": rd["version"]},
            make_resident_headers(hh["id"]),
        )
        data = validate_success(resp)
        assert data["status"] == "SCHEDULED"
        # Mattress within allowance: 1200 + round_half_up(102.0)=102 -> 1302.
        assert data["provisional_total_cents"] == 1302

        got = get_request(hh["id"], req["id"])
        assert got["status"] == "SCHEDULED"
        assert got["provisional_total_cents"] == 1302
