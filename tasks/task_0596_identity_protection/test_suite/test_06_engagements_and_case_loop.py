"""Specialist engagements, calendar capacity, and the information loop (PRD §3.6, §2.6)."""

from test_helpers import (
    ApiErrorId,
    assert_restoration_case,
    assert_specialist_engagement,
    create_engagement_payload,
    create_specialist,
    get_alert,
    get_case,
    get_specialist,
    make_specialist_headers,
    make_subscriber_headers,
    setup_in_progress_case,
    validate_error,
    validate_paginated,
    validate_success,
)

SPEC = {"full_name": "Sol Adeyemi", "tier": "TIER2", "max_caseload": 3,
        "max_concurrent_engagements": 1}


class TestEngagementCapacity:
    """Half-open intervals, each extended by a one-hour cool-down, against an aggregate capacity."""

    def test_an_engagement_touching_the_previous_end_collides_through_the_buffer(
        self, api, admin_headers
    ):
        """PRD §3.6: "Engagement intervals are **half-open** — the window covers its start instant
        but not its end instant — and each is extended by a **one-hour cool-down** past its end for
        the purposes of capacity accounting. The specialist's aggregate capacity is
        `max_concurrent_engagements`: the booking is rejected with
        `ERR_ENGAGEMENT_CAPACITY_EXCEEDED` if, at any instant, the number of that specialist's
        buffer-extended engagement intervals covering that instant would exceed
        `max_concurrent_engagements` once the new booking is added."
        PRD §3.6: "A practical consequence: two engagements that merely touch, the second starting
        exactly where the first ends, still collide for a specialist with a capacity of one, because
        the first one's buffer runs a full hour past its end."

        Design: Difficulty/resource_temporal_overlap/engagement_half_open_plus_60min_buffer_capacity_conflict
        """
        ctx = setup_in_progress_case(
            plan_overrides={
                "tier": "ADVANTAGE",
                "monthly_fee_cents": 1999,
                "child_monitoring_included": False,
                "max_family_members": 2,
            },
            specialist_overrides=SPEC,
            alert_overrides={"alert_type": "ACCOUNT_TAKEOVER", "severity": "MEDIUM"},
            window_start="2026-06-02T09:00:00Z",
            window_end="2026-06-02T11:00:00Z",
        )
        specialist_id = ctx["specialist"]["id"]
        version = get_specialist(specialist_id)["version"]

        resp = api.create_engagement(
            create_engagement_payload(
                specialist_id,
                ctx["case"]["id"],
                "2026-06-02T11:00:00Z",
                "2026-06-02T12:00:00Z",
                version,
            ),
            admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_ENGAGEMENT_CAPACITY_EXCEEDED)

        bookings, meta = validate_paginated(
            api.list_engagements(admin_headers, params={"specialist_id": specialist_id})
        )
        assert meta["total_count"] == 1, "only the first engagement survives"
        assert bookings[0]["id"] == ctx["engagement"]["id"]

        case = get_case(ctx["case"]["id"])
        assert case["status"] == "IN_PROGRESS", "the rejected booking left the case untouched"

    def test_an_engagement_starting_when_the_buffer_expires_is_accepted(self, api, admin_headers):
        """PRD §3.6: "Engagement intervals are **half-open** — the window covers its start instant
        but not its end instant — and each is extended by a **one-hour cool-down** past its end for
        the purposes of capacity accounting. The specialist's aggregate capacity is
        `max_concurrent_engagements`: the booking is rejected with
        `ERR_ENGAGEMENT_CAPACITY_EXCEEDED` if, at any instant, the number of that specialist's
        buffer-extended engagement intervals covering that instant would exceed
        `max_concurrent_engagements` once the new booking is added."

        Design: Difficulty/resource_temporal_overlap/engagement_half_open_plus_60min_buffer_capacity_conflict
        """
        ctx = setup_in_progress_case(
            plan_overrides={
                "tier": "ADVANTAGE",
                "monthly_fee_cents": 1999,
                "child_monitoring_included": False,
                "max_family_members": 2,
            },
            specialist_overrides=SPEC,
            alert_overrides={"alert_type": "ACCOUNT_TAKEOVER", "severity": "MEDIUM"},
            window_start="2026-06-02T09:00:00Z",
            window_end="2026-06-02T11:00:00Z",
        )
        specialist_id = ctx["specialist"]["id"]
        version = get_specialist(specialist_id)["version"]

        resp = api.create_engagement(
            create_engagement_payload(
                specialist_id,
                ctx["case"]["id"],
                "2026-06-02T12:00:00Z",
                "2026-06-02T13:00:00Z",
                version,
            ),
            admin_headers,
        )
        second = validate_success(resp, 201)
        assert_specialist_engagement(second)

        bookings, meta = validate_paginated(
            api.list_engagements(admin_headers, params={"specialist_id": specialist_id})
        )
        assert meta["total_count"] == 2, (
            "the buffered occupation of the first booking ends at 12:00, exclusive"
        )
        assert [b["id"] for b in bookings] == [ctx["engagement"]["id"], second["id"]], (
            "engagements are ordered by window_start ascending"
        )

    def test_booking_with_a_stale_specialist_version_is_rejected(self, api, admin_headers):
        """PRD §2.6: "Booking a work window on a specialist's calendar requires the body to carry
        `expected_specialist_version`, holding the client's last observed `version` of the
        specialist named by `specialist_id`. If that value does not equal the specialist's current
        `version`, the booking is rejected with `ERR_STALE_SPECIALIST_VERSION` and HTTP 412."

        Design: Corner/cross_cutting/occ_stale_specialist_version_on_engagement_create
        """
        ctx = setup_in_progress_case(
            specialist_overrides={
                "full_name": "Double Booker",
                "tier": "TIER2",
                "max_caseload": 3,
                "max_concurrent_engagements": 2,
            },
            alert_overrides={"alert_type": "SSN_TRACE", "severity": "MEDIUM"},
            window_start="2026-06-03T09:00:00Z",
            window_end="2026-06-03T11:00:00Z",
        )
        specialist_id = ctx["specialist"]["id"]
        current_version = get_specialist(specialist_id)["version"]
        stale_version = current_version - 1

        resp = api.create_engagement(
            create_engagement_payload(
                specialist_id,
                ctx["case"]["id"],
                "2026-06-04T09:00:00Z",
                "2026-06-04T11:00:00Z",
                stale_version,
            ),
            admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_SPECIALIST_VERSION)

        bookings, meta = validate_paginated(
            api.list_engagements(admin_headers, params={"specialist_id": specialist_id})
        )
        assert meta["total_count"] == 1, (
            "the rejected window does not even overlap — the rejection is purely a stale version"
        )
        assert bookings[0]["id"] == ctx["engagement"]["id"]

    def test_booking_against_an_unknown_case_is_not_found(self, api, admin_headers):
        """PRD §2.5: "Existence — every resource named in the request path is resolved first, left
        to right, and only then every foreign key supplied in the request body. The rejection
        carries the not-found code of the *first* identifier that fails to resolve:
        `ERR_PLAN_NOT_FOUND`, `ERR_SUBSCRIBER_NOT_FOUND`, `ERR_FAMILY_MEMBER_NOT_FOUND`,
        `ERR_BUREAU_PROFILE_NOT_FOUND`, `ERR_ALERT_NOT_FOUND`, `ERR_CASE_NOT_FOUND`,
        `ERR_SPECIALIST_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`, or `ERR_WALLET_ITEM_NOT_FOUND` as
        appropriate."
        PRD §2.5: "7. Optimistic concurrency — the stale-version checks of §2.6, rejecting with
        `ERR_STALE_CASE_VERSION` or `ERR_STALE_SPECIALIST_VERSION`."

        Design: Corner/errors/engagement_on_unknown_case_id_not_found
        """
        specialist = create_specialist(full_name="Idle Spec", tier="TIER2", max_caseload=3)
        version = specialist["version"]

        resp = api.create_engagement(
            create_engagement_payload(
                specialist["id"],
                "deadbeef-0000-4000-8000-000000000000",
                "2026-06-05T09:00:00Z",
                "2026-06-05T11:00:00Z",
                version,
            ),
            admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_CASE_NOT_FOUND)

        assert get_specialist(specialist["id"])["version"] == version, (
            "existence is screened before the optimistic-concurrency check, and nothing mutated"
        )


class TestInformationLoop:
    def test_the_information_loop_may_run_more_than_once(self, api):
        """PRD §3.6: "The assigned specialist requests information from the subscriber by supplying
        an `info_request`, which is stored on the case and moves it
        `IN_PROGRESS → PENDING_SUBSCRIBER`. The subscriber answers by supplying an `info_response`,
        stored on the case, moving it back `PENDING_SUBSCRIBER → IN_PROGRESS`. This loop may repeat
        any number of times; each pass increments the case's `version` by one."

        Design: Corner/state_machines/case_cycles_in_progress_and_pending_subscriber_twice
        """
        ctx = setup_in_progress_case(
            specialist_overrides={"full_name": "Loop Handler", "tier": "TIER2", "max_caseload": 3},
            alert_overrides={"alert_type": "SSN_TRACE", "severity": "MEDIUM"},
            window_start="2026-05-20T09:00:00Z",
            window_end="2026-05-20T11:00:00Z",
        )
        case_id = ctx["case"]["id"]
        spec_headers = make_specialist_headers(ctx["specialist"]["id"])
        sub_headers = make_subscriber_headers(ctx["subscriber"]["id"])
        assert ctx["case"]["version"] == 3, "create, assign, then the first engagement"

        first_ask = validate_success(
            api.request_info(case_id, {"info_request": "Upload the police report"}, spec_headers)
        )
        assert first_ask["status"] == "PENDING_SUBSCRIBER"

        first_answer = validate_success(
            api.provide_info(case_id, {"info_response": "Report #A-1 attached"}, sub_headers)
        )
        assert first_answer["status"] == "IN_PROGRESS", "the loop came back around"

        validate_success(
            api.request_info(
                case_id, {"info_request": "Also upload the FTC affidavit"}, spec_headers
            )
        )
        final = validate_success(
            api.provide_info(case_id, {"info_response": "Affidavit #B-2 attached"}, sub_headers)
        )

        assert_restoration_case(final)
        assert final["status"] == "IN_PROGRESS"
        assert final["version"] == 7, "three setup writes plus four loop passes"
        assert final["info_request"] == "Also upload the FTC affidavit"
        assert final["info_response"] == "Affidavit #B-2 attached"

    def test_resolving_while_the_case_waits_on_the_subscriber_is_rejected(self, api):
        """PRD §3.6: "**Resolution.** The assigned specialist closes the case out by supplying a
        `resolution_summary`, moving it `IN_PROGRESS → RESOLVED`."
        PRD §2.5: "8. State legality — the target resource is currently in a state from which the
        requested transition is declared (this governs alerts, restoration cases, insurance claims,
        bureau profiles, wallet items and subscribers alike), rejecting with `ERR_INVALID_STATE`."

        Design: Corner/state_machines/case_resolve_from_pending_subscriber_rejected
        """
        ctx = setup_in_progress_case(
            specialist_overrides={"full_name": "Gate Keep", "tier": "TIER2", "max_caseload": 3},
            alert_overrides={"alert_type": "ACCOUNT_TAKEOVER", "severity": "MEDIUM"},
            window_start="2026-05-21T09:00:00Z",
            window_end="2026-05-21T11:00:00Z",
        )
        case_id = ctx["case"]["id"]
        specialist_id = ctx["specialist"]["id"]
        spec_headers = make_specialist_headers(specialist_id)
        validate_success(
            api.request_info(case_id, {"info_request": "Send the mailbox audit log"}, spec_headers)
        )

        resp = api.resolve_case(
            case_id, {"resolution_summary": "Trying to close early"}, spec_headers
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

        case = get_case(case_id)
        assert case["status"] == "PENDING_SUBSCRIBER"
        assert case["resolution_summary"] is None

        specialist = get_specialist(specialist_id)
        assert specialist["active_case_count"] == 1, "no compensation fired"

        assert get_alert(ctx["alert"]["id"])["status"] == "CONFIRMED_FRAUD", (
            "the origin alert was not carried to RESOLVED"
        )