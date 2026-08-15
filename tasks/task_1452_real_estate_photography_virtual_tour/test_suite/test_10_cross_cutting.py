"""Cross-cutting layers: validation precedence, OCC, cascade side effects,
immediate consistency, append-only audit records (PRD §2.5-2.10, §3)."""
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data, ApiErrorId,
    make_client_agent_headers, make_photographer_headers, make_coordinator_headers,
    make_ops_admin_headers,
    create_market, create_photographer, create_agent, create_booking, set_clock,
    create_ready_booking, create_confirmed_booking, submit_and_prepare,
    assign_booking, confirm_booking, get_booking, get_photographer, live_version,
)


class TestValidationPrecedence:
    def test_auth_header_missing_rejected_before_everything(self, api):
        """PRD §2.8: "1. **User context** — missing or invalid `X-User-ID` /
        `X-User-Role` headers fail with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`
        (400)." — tier 1
        — and "A request that fails at tier one is never reported as a tier-seven
        conflict, even when both conditions happen to hold."

        Design: Corner/validations/auth_header_missing_rejected_before_everything
        """
        set_clock()
        resp = api_client.get_booking("8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2", headers={})
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)

    def test_role_checked_before_existence(self, api):
        """PRD §2.8: tier 2 is "2. **Role authorization** — a role not permitted
        for the endpoint fails with `ERR_UNAUTHORIZED_ROLE` (403)." and tier 3 is "3.
        **Existence** — unknown path identifiers or a broken parent chain fail with
        `ERR_NOT_FOUND` (404)."; "an earlier tier masks every later tier."

        Design: Corner/validations/role_checked_before_existence
        """
        set_clock()
        market = create_market(market_code="DEN", display_name="Denver",
                               pricing_multiplier_bps=10000, standard_turnaround_hours=48)
        photog = create_photographer(market["id"], full_name="Pat Photo", email="pat@x.com",
                                     equipment_packages=["STANDARD"])
        # PATCH /markets is OpsAdmin-only; the Photographer role fails at tier 2 even
        # though the path id does not exist (tier 3 would have been 404).
        resp = api_client.patch_market("8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2",
                                       {"status": "SUSPENDED"},
                                       make_photographer_headers(photog["id"]))
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)

    def test_state_error_dominates_temporal_error_on_reschedule(self, api):
        """PRD §2.8: tier 4 is "4. **State legality** — the target entity is not
        in a state that permits the operation, reported as the operation's specific
        state error (for example `ERR_BOOKING_NOT_IN_DRAFT`) or, generically,
        `ERR_INVALID_STATE` (409)." and tier 5 is "5. **Temporal rules** — lead-time,
        quarter-hour alignment, shoot-window, cancellation-cutoff, and revision-window
        checks, typified by `ERR_SLOT_TOO_SOON` (422)."; "an earlier tier masks every
        later tier."
        PRD §3.9: "The booking must be in `ASSIGNED`, `AUTHORIZATION_PENDING`, or
        `CONFIRMED` (otherwise `ERR_BOOKING_NOT_RESCHEDULABLE`) ..."

        A reschedule on a CANCELLED_BY_CLIENT booking with a too-soon new start
        violates both tiers; the state error wins.

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_temporal_on_reschedule
        """
        set_clock()
        market = create_market(market_code="DEN", display_name="Denver",
                               pricing_multiplier_bps=10000, standard_turnaround_hours=48)
        agent = create_agent(market["id"])
        booking = create_booking(agent, market["id"], order_ref="ORD-PRIO1",
                                 property_address="1 Nowhere",
                                 scheduled_start_utc="2026-08-10T14:00:00Z")
        headers = make_client_agent_headers(agent["id"])
        get_success_data(api_client.cancel_booking(booking["id"], headers))

        resp = api_client.reschedule_booking(
            booking["id"],
            {"expected_booking_version": live_version(booking["id"]), "kind": "CLIENT",
             "new_start_utc": "2026-08-01T01:00:00Z", "reason_code": "SELLER_DELAY"},
            headers)
        validate_error(resp, ApiErrorId.ERR_BOOKING_NOT_RESCHEDULABLE)


    def test_terminal_cancel_beats_temporal_cutoff(self, api):
        """PRD §2.8: "Beyond that, when a single request could fail several checks, the
        server evaluates them in a fixed precedence order and reports only the first
        applicable failure; an earlier tier masks every later tier." Tier 4 is "4.
        **State legality** — the target entity is not in a state that permits the
        operation, reported as the operation's specific state error (for example
        `ERR_BOOKING_NOT_IN_DRAFT`) or, generically, `ERR_INVALID_STATE` (409)." and
        tier 5 is "5. **Temporal rules** — lead-time, quarter-hour alignment,
        shoot-window, cancellation-cutoff, and revision-window checks, typified by
        `ERR_SLOT_TOO_SOON` (422)."
        PRD §3.9: "The owning agent may cancel from `DRAFT`, `AWAITING_READINESS`,
        `READY`, `ASSIGNED`, `AUTHORIZATION_PENDING`, or `CONFIRMED`; from any other
        state the attempt fails with `ERR_BOOKING_NOT_CANCELLABLE`."

        A cancel attempted on an already-cancelled booking inside what would have been
        the 12-hour cutoff reports the state error, not the temporal one.

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_temporal_on_reschedule
        """
        set_clock()
        market = create_market(market_code="DEN", display_name="Denver",
                               pricing_multiplier_bps=10000, standard_turnaround_hours=48)
        agent = create_agent(market["id"])
        booking = create_booking(agent, market["id"], order_ref="ORD-PRIO2",
                                 property_address="2 Nowhere",
                                 scheduled_start_utc="2026-08-10T14:00:00Z")
        headers = make_client_agent_headers(agent["id"])
        get_success_data(api_client.cancel_booking(booking["id"], headers))

        # clock inside the would-be 12h cutoff; the terminal state error still wins
        set_clock("2026-08-10T13:00:00Z")
        resp = api_client.cancel_booking(booking["id"], headers)
        validate_error(resp, ApiErrorId.ERR_BOOKING_NOT_CANCELLABLE)


class TestOptimisticConcurrency:
    def test_occ_stale_version_pure_patch_conflict(self, api):
        """PRD §2.6: "A `PATCH /shoot-bookings/{id}` request — the mutable-fields
        update — must carry `expected_booking_version`, holding the booking `version`
        value the client last observed. ... if the supplied value no longer equals the
        booking's current `version` ... the request is rejected with `ERR_STALE_VERSION`
        (HTTP 412), and the client must re-read the booking before retrying."
        PRD §3.1: "changing the package, photo count, or start recomputes
        `scheduled_end_utc`."

        Design: Corner/complexity_layers/occ_stale_version_pure_patch_conflict
        """
        set_clock()
        market = create_market(market_code="DEN", display_name="Denver",
                               pricing_multiplier_bps=10000, standard_turnaround_hours=48)
        agent = create_agent(market["id"])
        booking = create_booking(agent, market["id"], order_ref="ORD-OCC2",
                                 property_address="3 Version Rd", photo_count=20,
                                 scheduled_start_utc="2026-08-10T14:00:00Z")
        headers = make_client_agent_headers(agent["id"])
        v1 = booking["version"]

        patched = validate_success(api_client.patch_booking(
            booking["id"], {"expected_booking_version": v1, "photo_count": 30}, headers))
        assert patched["version"] == v1 + 1
        assert patched["photo_count"] == 30
        # 5 photos over the STANDARD allotment = one started group of five -> 70 minutes
        assert patched["scheduled_end_utc"] == "2026-08-10T15:10:00Z"

        # replaying the pre-patch version is rejected even though the write is legal
        resp = api_client.patch_booking(
            booking["id"], {"expected_booking_version": v1, "photo_count": 40}, headers)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        assert get_booking(booking["id"])["photo_count"] == 30

    def test_occ_stale_version_on_booking_reschedule(self, api):
        """PRD §2.6: "A `POST /shoot-bookings/{id}/reschedule` request must likewise
        carry `expected_booking_version`. On either endpoint, if the supplied value no
        longer equals the booking's current `version` — because another write has
        legitimately advanced the version since the client last read the resource ... —
        the request is rejected with `ERR_STALE_VERSION` (HTTP 412) ..."

        Design: Corner/complexity_layers/occ_stale_version_on_booking_reschedule
        """
        set_clock()
        market = create_market(market_code="DEN", display_name="Denver",
                               pricing_multiplier_bps=10000, standard_turnaround_hours=48)
        photog = create_photographer(market["id"], full_name="Pat Photo", email="pat@x.com",
                                     equipment_packages=["STANDARD"])
        agent = create_agent(market["id"])
        booking = create_confirmed_booking(agent, photog, market["id"], order_ref="ORD-OCCR",
                                           property_address="2 Version Rd",
                                           scheduled_start_utc="2026-08-10T14:00:00Z")
        headers = make_client_agent_headers(agent["id"])
        v_confirmed = booking["version"]

        moved = validate_success(api_client.reschedule_booking(
            booking["id"],
            {"expected_booking_version": v_confirmed, "kind": "CLIENT",
             "new_start_utc": "2026-08-12T14:00:00Z", "reason_code": "SELLER_DELAY"},
            headers))
        assert moved["version"] > v_confirmed

        # replaying the pre-reschedule version: every business rule would pass, OCC rejects
        resp = api_client.reschedule_booking(
            booking["id"],
            {"expected_booking_version": v_confirmed, "kind": "CLIENT",
             "new_start_utc": "2026-08-13T14:00:00Z", "reason_code": "ACCESS_ISSUE"},
            headers)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        after = get_booking(booking["id"])
        assert after["scheduled_start_utc"] == "2026-08-12T14:00:00Z"
        assert after["reschedule_count"] == 1


class TestSideEffectsAndConsistency:
    def test_checklist_items_created_as_submit_side_effect(self, api):
        """PRD §3.1: "Submission locks the booking's `provisional_quote_cents` and
        spawns the property-readiness checklist: five items keyed `DECLUTTER_MAIN`,
        `UTILITIES_ON`, `PETS_SECURED`, `ACCESS_CODES`, and `EXTERIOR_CLEAR`, every one
        created with `required` true and `checked` false."

        Design: Corner/endpoints/checklist_items_created_as_submit_side_effect
        """
        set_clock()
        market = create_market(market_code="DEN", display_name="Denver",
                               pricing_multiplier_bps=10000, standard_turnaround_hours=48)
        agent = create_agent(market["id"])
        booking = create_booking(agent, market["id"], order_ref="ORD-CL",
                                 property_address="5 List Ln",
                                 scheduled_start_utc="2026-08-10T14:00:00Z")
        headers = make_client_agent_headers(agent["id"])
        get_success_data(api_client.submit_booking(booking["id"], headers))

        items = get_success_data(api_client.list_checklist_items(booking["id"], headers,
                                                                 params={"limit": 100}))
        assert len(items) == 5
        assert {i["item_key"] for i in items} == {
            "DECLUTTER_MAIN", "UTILITIES_ON", "PETS_SECURED", "ACCESS_CODES", "EXTERIOR_CLEAR"}
        for item in items:
            assert item["required"] is True
            assert item["checked"] is False
            assert item["checked_at_utc"] is None

    def test_immediate_consistency_response_reflects_cascade(self, api):
        """PRD §3.3: "A successful assignment sets the booking's
        `assigned_photographer_id`, adds the shoot's minutes to the photographer's
        `committed_minutes_by_day` entry for the scheduled day, and increments both the
        booking's `version` and the photographer's `version`."

        The assign response body itself carries the new state — no re-read needed.

        Design: Corner/consistency_model/immediate_consistency_response_reflects_cascade
        """
        set_clock()
        market = create_market(market_code="DEN", display_name="Denver",
                               pricing_multiplier_bps=10000, standard_turnaround_hours=48)
        photog = create_photographer(market["id"], full_name="Pat Photo", email="pat@x.com",
                                     equipment_packages=["STANDARD"])
        agent = create_agent(market["id"])
        booking = create_ready_booking(agent, market["id"], order_ref="ORD-IMM2",
                                       property_address="8 Atomic Ave",
                                       scheduled_start_utc="2026-08-10T14:00:00Z")
        v_ready = booking["version"]

        resp = api_client.assign_booking(booking["id"], photog["id"], make_coordinator_headers())
        assigned = validate_success(resp)
        assert assigned["state"] == "ASSIGNED"
        assert assigned["assigned_photographer_id"] == photog["id"]
        assert assigned["version"] > v_ready
        # the photographer read immediately reflects the same-request side effect
        assert get_photographer(photog["id"])["committed_minutes_by_day"]["2026-08-10"] == 60

    def test_reschedule_event_is_immutable_append_only(self, api):
        """PRD §2.5: "The one exception is the **RescheduleEvent**, which is an
        immutable, append-only history record: it carries `id` and `created_at` only,
        and both `updated_at` and `version` are absent, since a reschedule event is
        never modified after it is written."
        PRD §3.9: "An in-cap reschedule appends an immutable `RescheduleEvent` —
        recording its `kind`, the booking's previous start in `old_start_utc`, the
        replacement in `new_start_utc`, the `reason_code`, and the `credit_applied_cents`
        actually credited by the event ... `CLIENT` events always record zero."

        Design: Corner/entities/reschedule_event_is_immutable_no_update_endpoint
        """
        set_clock()
        market = create_market(market_code="DEN", display_name="Denver",
                               pricing_multiplier_bps=10000, standard_turnaround_hours=48)
        photog = create_photographer(market["id"], full_name="Pat Photo", email="pat@x.com",
                                     equipment_packages=["STANDARD"])
        agent = create_agent(market["id"])
        booking = create_confirmed_booking(agent, photog, market["id"], order_ref="ORD-IMM",
                                           property_address="3 Immutable Way",
                                           scheduled_start_utc="2026-08-05T14:00:00Z")
        headers = make_client_agent_headers(agent["id"])
        resp = api_client.reschedule_booking(
            booking["id"],
            {"expected_booking_version": live_version(booking["id"]), "kind": "CLIENT",
             "new_start_utc": "2026-08-06T14:00:00Z", "reason_code": "SELLER_DELAY"},
            headers)
        get_success_data(resp)

        events = get_success_data(api_client.list_reschedule_events(booking["id"], headers))
        assert len(events) == 1
        event = events[0]
        assert event["kind"] == "CLIENT"
        assert event["old_start_utc"] == "2026-08-05T14:00:00Z"
        assert event["new_start_utc"] == "2026-08-06T14:00:00Z"
        assert event["credit_applied_cents"] == 0
        assert "version" not in event and "updated_at" not in event
        assert "id" in event and "created_at" in event
