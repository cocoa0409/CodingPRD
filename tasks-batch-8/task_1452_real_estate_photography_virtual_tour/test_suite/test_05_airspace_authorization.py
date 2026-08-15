"""Airspace authorization lifecycle and booking gating (PRD §3.5)."""
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data, ApiErrorId,
    make_client_agent_headers, make_photographer_headers, make_coordinator_headers,
    make_ops_admin_headers,
    create_market, create_photographer, create_agent, set_clock,
    create_authorization_pending_booking, create_confirmed_drone_booking,
    first_authorization, get_booking, weather_reschedule, confirm_booking,
)


def _drone_setup(api, **market_kw):
    market = create_market(market_code="ATX", display_name="Austin",
                           pricing_multiplier_bps=12500, standard_turnaround_hours=48,
                           **market_kw)
    photog = create_photographer(market["id"], full_name="Drone Dana", email="dana@x.com",
                                 equipment_packages=["STANDARD"], drone_certified=True)
    agent = create_agent(market["id"])
    return market, photog, agent


class TestConfirmGatedByAuthorization:
    def test_direct_confirm_rejected_then_approve_autoconfirms(self, api):
        """PRD §3.3: "attempting to confirm around an unresolved drone authorization
        fails with `ERR_AUTHORIZATION_PENDING`, because drone work must route through
        `AUTHORIZATION_PENDING` and reach `CONFIRMED` only when every authorization is
        approved."
        PRD §3.5: "Approval stamps `decided_at_utc`, and when it clears the last pending
        authorization on a booking waiting in `AUTHORIZATION_PENDING`, the booking
        auto-advances to `CONFIRMED`."

        Design: Difficulty/cross_entity_state_dependency/booking_confirm_gated_by_airspace_authorization_pair
        """
        set_clock()
        market, photog, agent = _drone_setup(api)
        booking, auth = create_authorization_pending_booking(
            agent, photog, market["id"], addon_kind="DRONE_VIDEO",
            order_ref="ORD-X1", property_address="11 Aero Dr", photo_count=20,
            scheduled_start_utc="2026-08-10T14:00:00Z")

        # direct confirm is forbidden while the authorization is unresolved
        resp = api_client.confirm_booking(booking["id"], make_coordinator_headers())
        validate_error(resp, ApiErrorId.ERR_AUTHORIZATION_PENDING)
        assert get_booking(booking["id"])["state"] == "AUTHORIZATION_PENDING"

        # the approval itself unlocks the booking — no further booking-level call
        validate_success(api_client.approve_authorization(booking["id"], auth["id"],
                                                          make_ops_admin_headers()))
        assert get_booking(booking["id"])["state"] == "CONFIRMED"

    def test_reject_resubmit_approve_cycle(self, api):
        """PRD §3.5: "Rejection likewise requires `PENDING` ... the booking stays in
        `AUTHORIZATION_PENDING` awaiting a resubmission ..." and "A resubmission
        increments `attempt_number` by one, re-stamps the window from the booking's
        current scheduled window, clears `decided_at_utc` back to null, and returns the
        authorization to `PENDING`."

        Design: Difficulty/non_linear_state_machine/airspace_authorization_pending_rejected_resubmit_cycle
        """
        set_clock()
        market, photog, agent = _drone_setup(api)
        booking, auth = create_authorization_pending_booking(
            agent, photog, market["id"], addon_kind="DRONE_STILLS",
            order_ref="ORD-AIR", property_address="7 Sky Way", photo_count=20,
            scheduled_start_utc="2026-08-10T14:00:00Z")
        assert auth["state"] == "PENDING"
        assert auth["attempt_number"] == 1

        rejected = validate_success(api_client.reject_authorization(
            booking["id"], auth["id"], make_ops_admin_headers()))
        assert rejected["state"] == "REJECTED"
        # booking blocked from CONFIRMED while the rejection is unresolved
        assert get_booking(booking["id"])["state"] == "AUTHORIZATION_PENDING"

        resubmitted = validate_success(api_client.resubmit_authorization(
            booking["id"], auth["id"], make_coordinator_headers()))
        assert resubmitted["state"] == "PENDING"
        assert resubmitted["attempt_number"] == 2
        assert resubmitted["decided_at_utc"] is None

        approved = validate_success(api_client.approve_authorization(
            booking["id"], auth["id"], make_ops_admin_headers()))
        assert approved["state"] == "APPROVED"
        assert get_booking(booking["id"])["state"] == "CONFIRMED"


    def test_assign_auto_routes_drone_booking_to_authorization_pending(self, api):
        """PRD §3.3: "when an `ACTIVE` drone add-on exists at assign time, the booking
        does not rest in `ASSIGNED` — it passes immediately through into
        `AUTHORIZATION_PENDING`, and the server mints an `AirspaceAuthorization` in
        `PENDING` with `attempt_number` 1 whose window covers the booking's scheduled
        window, as detailed in §3.5."

        Design: Difficulty/cross_entity_state_dependency/booking_confirm_gated_by_airspace_authorization_pair
        """
        set_clock()
        market, photog, agent = _drone_setup(api)
        booking, auth = create_authorization_pending_booking(
            agent, photog, market["id"], addon_kind="DRONE_STILLS",
            order_ref="ORD-X1B", property_address="12 Aero Dr", photo_count=20,
            scheduled_start_utc="2026-08-10T14:00:00Z")
        assert booking["state"] == "AUTHORIZATION_PENDING"
        assert booking["assigned_photographer_id"] == photog["id"]
        # authorization minted PENDING, attempt 1, covering the scheduled window:
        # 60-minute STANDARD shoot + 30 drone minutes -> 14:00 .. 15:30
        assert auth["state"] == "PENDING"
        assert auth["attempt_number"] == 1
        assert auth["window_start_utc"] == "2026-08-10T14:00:00Z"
        assert auth["window_end_utc"] == "2026-08-10T15:30:00Z"
        assert auth["decided_at_utc"] is None


class TestAttemptCap:
    def test_third_rejection_refuses_drone_addon(self, api):
        """PRD §3.5: "if the rejected authorization had already reached `attempt_number`
        3, the covered drone add-on moves to `REFUSED`, and if no drone add-on remains
        `ACTIVE` on the booking, the booking returns to `CONFIRMED` without it."
        PRD §3.5: "requires `attempt_number` to still be below the hard cap of 3
        (otherwise `ERR_AUTHORIZATION_ATTEMPTS_EXHAUSTED`) ..."

        Design: Corner/state_machines/authorization_attempt_cap_refuses_drone_addon
        """
        set_clock()
        market, photog, agent = _drone_setup(api)
        headers = make_client_agent_headers(agent["id"])
        booking, auth = create_authorization_pending_booking(
            agent, photog, market["id"], addon_kind="DRONE_STILLS",
            order_ref="ORD-CAP3", property_address="8 Airspace Ave", photo_count=20,
            scheduled_start_utc="2026-08-10T14:00:00Z")
        addons = get_success_data(api_client.list_addons(booking["id"], headers))
        drone = addons[0]

        ops = make_ops_admin_headers()
        coord = make_coordinator_headers()
        # attempts 1 -> 2 -> 3
        get_success_data(api_client.reject_authorization(booking["id"], auth["id"], ops))
        get_success_data(api_client.resubmit_authorization(booking["id"], auth["id"], coord))
        get_success_data(api_client.reject_authorization(booking["id"], auth["id"], ops))
        get_success_data(api_client.resubmit_authorization(booking["id"], auth["id"], coord))

        # rejection at attempt_number 3: the covered drone add-on dies by policy
        validate_success(api_client.reject_authorization(booking["id"], auth["id"], ops))
        # any further resubmit exceeds the cap
        resp = api_client.resubmit_authorization(booking["id"], auth["id"], coord)
        validate_error(resp, ApiErrorId.ERR_AUTHORIZATION_ATTEMPTS_EXHAUSTED)

        auth_after = get_success_data(api_client.get_authorization(booking["id"], auth["id"], coord))
        assert auth_after["state"] == "REJECTED"
        assert auth_after["attempt_number"] == 3
        addon_after = get_success_data(api_client.get_addon(booking["id"], drone["id"], headers))
        assert addon_after["state"] == "REFUSED"
        # no ACTIVE drone add-on remains, so the booking auto-resolves to CONFIRMED
        assert get_booking(booking["id"])["state"] == "CONFIRMED"


    def test_resubmit_restamps_attempt_and_window(self, api):
        """PRD §3.5: "A resubmission increments `attempt_number` by one, re-stamps the
        window from the booking's current scheduled window, clears `decided_at_utc`
        back to null, and returns the authorization to `PENDING`."

        Design: Difficulty/non_linear_state_machine/airspace_authorization_pending_rejected_resubmit_cycle
        """
        set_clock()
        market, photog, agent = _drone_setup(api)
        booking, auth = create_authorization_pending_booking(
            agent, photog, market["id"], addon_kind="DRONE_STILLS",
            order_ref="ORD-AIR2", property_address="9 Sky Way", photo_count=20,
            scheduled_start_utc="2026-08-10T14:00:00Z")

        rejected = validate_success(api_client.reject_authorization(
            booking["id"], auth["id"], make_ops_admin_headers()))
        assert rejected["state"] == "REJECTED"
        assert rejected["decided_at_utc"] is not None

        resubmitted = validate_success(api_client.resubmit_authorization(
            booking["id"], auth["id"], make_coordinator_headers()))
        assert resubmitted["state"] == "PENDING"
        assert resubmitted["attempt_number"] == 2
        assert resubmitted["decided_at_utc"] is None
        # window re-stamped from the booking's current scheduled window
        assert resubmitted["window_start_utc"] == "2026-08-10T14:00:00Z"
        assert resubmitted["window_end_utc"] == "2026-08-10T15:30:00Z"


class TestAuthorizationGuards:
    def test_unassign_blocked_while_approved_authorization_covers_window(self, api):
        """PRD §3.3: "it is refused while any airspace authorization on the booking
        sits in `APPROVED` — an approved authorization must first be obviated by a
        reschedule, or the unassignment fails with `ERR_AUTHORIZATION_STILL_VALID`."

        Design: Corner/state_machines/unassign_blocked_while_approved_authorization_covers_window
        """
        set_clock()
        market, photog, agent = _drone_setup(api)
        booking, auth = create_confirmed_drone_booking(
            agent, photog, market["id"], addon_kind="DRONE_STILLS",
            order_ref="ORD-UNA", property_address="10 Lock Ln", photo_count=20,
            scheduled_start_utc="2026-08-10T14:00:00Z")

        resp = api_client.unassign_booking(booking["id"], make_coordinator_headers())
        validate_error(resp, ApiErrorId.ERR_AUTHORIZATION_STILL_VALID)
        after = get_booking(booking["id"])
        assert after["state"] == "CONFIRMED"
        assert after["assigned_photographer_id"] == photog["id"]

    def test_approve_after_window_lapsed_rejected(self, api):
        """PRD §3.5: "Approval requires the authorization to be `PENDING` ... and
        requires its `window_end_utc` to still lie in the future — approving into a
        lapsed window fails with `ERR_AUTHORIZATION_WINDOW_LAPSED` (HTTP 422)."

        Design: Corner/errors/error_authorization_window_lapsed_on_approve
        """
        set_clock()
        market, photog, agent = _drone_setup(api)
        booking, auth = create_authorization_pending_booking(
            agent, photog, market["id"], addon_kind="DRONE_STILLS",
            order_ref="ORD-LAPSE", property_address="12 Lapse Ln", photo_count=20,
            scheduled_start_utc="2026-08-10T14:00:00Z")
        # window is [14:00, 15:30) (60-minute shoot + 30 drone minutes); jump past it
        set_clock("2026-08-10T16:00:00Z")

        resp = api_client.approve_authorization(booking["id"], auth["id"], make_ops_admin_headers())
        validate_error(resp, ApiErrorId.ERR_AUTHORIZATION_WINDOW_LAPSED)
        auth_after = get_success_data(api_client.get_authorization(
            booking["id"], auth["id"], make_coordinator_headers()))
        assert auth_after["state"] == "PENDING"

    def test_resubmit_requires_rejected_state(self, api):
        """PRD §3.5: "It requires the authorization to be `REJECTED` (otherwise
        `ERR_AUTHORIZATION_NOT_REJECTED`) ..."

        Design: Corner/errors/error_resubmit_requires_rejected_state
        """
        set_clock()
        market, photog, agent = _drone_setup(api)
        booking, auth = create_authorization_pending_booking(
            agent, photog, market["id"], addon_kind="DRONE_STILLS",
            order_ref="ORD-RSB", property_address="14 Resub Rd", photo_count=20,
            scheduled_start_utc="2026-08-10T14:00:00Z")

        resp = api_client.resubmit_authorization(booking["id"], auth["id"],
                                                 make_coordinator_headers())
        validate_error(resp, ApiErrorId.ERR_AUTHORIZATION_NOT_REJECTED)
        auth_after = get_success_data(api_client.get_authorization(
            booking["id"], auth["id"], make_coordinator_headers()))
        assert auth_after["attempt_number"] == 1


class TestRescheduleCascade:
    def test_weather_reschedule_cascade_depth4_authorization_expiry(self, api):
        """PRD §3.9: "Every `APPROVED` authorization whose window no longer matches the
        new window moves to `EXPIRED`, and a replacement `PENDING` authorization is
        minted per §3.5 with `attempt_number` one above the maximum prior attempt, capped
        at three; if that cap would be exceeded, the drone add-on moves to `REFUSED` and
        the booking proceeds without it."
        PRD §3.9: "Every checklist item is reset — `checked` false, `checked_at_utc`
        null — because property readiness must be re-attested ..."

        Hop chain: window moves -> approved authorization expires -> replacement minted
        at attempt 3 (cap) -> its rejection refuses the add-on and the booking
        auto-resolves to CONFIRMED.

        Design: Difficulty/transitive_cascade/weather_reschedule_cascade_depth4_authorization_expiry
        """
        set_clock()
        market, photog, agent = _drone_setup(api, weather_reschedule_credit_bps=1000)
        headers = make_client_agent_headers(agent["id"])
        ops = make_ops_admin_headers()
        coord = make_coordinator_headers()

        booking, auth1 = create_authorization_pending_booking(
            agent, photog, market["id"], addon_kind="DRONE_STILLS",
            order_ref="ORD-CASCADE", property_address="12 Chain Dr", photo_count=20,
            scheduled_start_utc="2026-08-05T14:00:00Z")
        addons = get_success_data(api_client.list_addons(booking["id"], headers))
        drone = addons[0]

        # attempt 1 rejected, resubmitted to attempt 2, then approved -> CONFIRMED
        get_success_data(api_client.reject_authorization(booking["id"], auth1["id"], ops))
        get_success_data(api_client.resubmit_authorization(booking["id"], auth1["id"], coord))
        get_success_data(api_client.approve_authorization(booking["id"], auth1["id"], ops))
        assert get_booking(booking["id"])["state"] == "CONFIRMED"

        # hop 1: weather reschedule moves the window (booking CONFIRMED -> ASSIGNED)
        booking = weather_reschedule(booking, agent, "2026-08-07T14:00:00Z", "WIND")
        assert booking["state"] == "ASSIGNED"
        # weather credit: 10% of the locked quote (base 18750 + drone 25000 = 43750)
        assert booking["provisional_quote_cents"] == 43750
        assert booking["weather_credit_cents"] == 4375
        assert booking["reschedule_count"] == 1

        # hop 2: the approved authorization expired; a replacement was minted at the cap
        auths = get_success_data(api_client.list_authorizations(booking["id"], coord))
        auth1_after = next(a for a in auths if a["id"] == auth1["id"])
        assert auth1_after["state"] == "EXPIRED"
        auth2 = next(a for a in auths if a["id"] != auth1["id"])
        assert auth2["state"] == "PENDING"
        assert auth2["attempt_number"] == 3

        # checklist reset: readiness must be re-attested
        items = get_success_data(api_client.list_checklist_items(booking["id"], headers,
                                                                 params={"limit": 100}))
        assert all(i["checked"] is False and i["checked_at_utc"] is None for i in items)

        # hops 3+4: rejection at the cap refuses the add-on and auto-confirms the booking
        get_success_data(api_client.reject_authorization(booking["id"], auth2["id"], ops))
        addon_after = get_success_data(api_client.get_addon(booking["id"], drone["id"], headers))
        assert addon_after["state"] == "REFUSED"
        assert get_booking(booking["id"])["state"] == "CONFIRMED"

    def test_weather_reschedule_resets_checklist_and_keeps_photographer(self, api):
        """PRD §3.9: "Every checklist item is reset — `checked` false, `checked_at_utc`
        null — because property readiness must be re-attested; the booking lands in
        `ASSIGNED` — a `CONFIRMED` booking drops back to `ASSIGNED` ..."
        PRD §3.9: "The assigned photographer is re-validated against the new window
        under the overlap and day-capacity rules of §2.7 ..."

        Design: Difficulty/transitive_cascade/weather_reschedule_cascade_depth4_authorization_expiry
        """
        set_clock()
        market, photog, agent = _drone_setup(api, weather_reschedule_credit_bps=1000)
        headers = make_client_agent_headers(agent["id"])
        booking, auth1 = create_confirmed_drone_booking(
            agent, photog, market["id"], addon_kind="DRONE_STILLS",
            order_ref="ORD-CASC2", property_address="13 Chain Dr", photo_count=20,
            scheduled_start_utc="2026-08-05T14:00:00Z")

        # checklist was completed during setup
        items = get_success_data(api_client.list_checklist_items(booking["id"], headers,
                                                                 params={"limit": 100}))
        assert all(i["checked"] is True for i in items)

        booking = weather_reschedule(booking, agent, "2026-08-07T14:00:00Z", "WIND")
        # CONFIRMED drops back to ASSIGNED (drone authorization re-pends)
        assert booking["state"] == "ASSIGNED"
        # the photographer still fits the new window, so the assignment survives
        assert booking["assigned_photographer_id"] == photog["id"]

        items = get_success_data(api_client.list_checklist_items(booking["id"], headers,
                                                                 params={"limit": 100}))
        assert all(i["checked"] is False and i["checked_at_utc"] is None for i in items)
