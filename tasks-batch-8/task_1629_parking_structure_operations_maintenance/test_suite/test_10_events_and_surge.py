"""Event bookings: pool aggregate capacity, staffing floor, cancellation fee
policies, and the surge activation/reversal cascades."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    confirm_event_booking,
    create_event_booking,
    create_event_booking_payload,
    create_facility,
    enter_vehicle,
    get_facility,
    get_success_data,
    make_gate_device_headers,
    quote_session_at,
    register_online_gate,
    set_clock,
    setup_entry_ready_facility,
    validate_error,
    validate_success,
)

FM = TEST_USERS["facility_manager_headers"]
ATT = TEST_USERS["parking_attendant_headers"]


class TestEventPoolAggregateCapacity:
    """Overlapping CONFIRMED/ACTIVE events share the facility event pool."""

    def _build_pair(self, api):
        facility = create_facility(name="PoolEvt Fac", event_pool_spaces=40)
        e1 = create_event_booking(facility["id"], event_name="E1",
                                  start_at="2026-08-14T18:00:00Z",
                                  end_at="2026-08-14T23:00:00Z",
                                  presale_allocation=25)
        confirm_event_booking(e1["id"], [])
        e2 = create_event_booking(facility["id"], event_name="E2",
                                  start_at="2026-08-14T20:00:00Z",
                                  end_at="2026-08-14T23:00:00Z",
                                  presale_allocation=15)
        return facility, e2

    def test_combined_presale_at_exactly_pool_capacity_confirms(self, api):
        """PRD: "The pool charge is the candidate's `presale_allocation` plus
        the `presale_allocation` of every other booking of the same facility
        standing `CONFIRMED` or `ACTIVE` whose window overlaps the
        candidate's — overlap being strict and half-open, so the candidate's
        `start_at` falls strictly before the other's `end_at` and the other's
        `start_at` falls strictly before the candidate's `end_at`, and windows
        that merely touch at an endpoint do not overlap. The charge must not
        exceed the facility's `event_pool_spaces`, with equality permitted"

        Design: Difficulty/resource_temporal_overlap/event_pool_aggregate_capacity
        """
        facility, e2 = self._build_pair(api)
        confirmed = validate_success(api.confirm_event_booking(e2["id"], [], FM), 200)
        assert confirmed["booking_status"] == "CONFIRMED", (
            "combined presale 25 + 15 == 40 == event_pool_spaces: inclusive boundary")

    def test_one_over_pool_rejected_and_touching_window_not_overlapping(self, api):
        """PRD: "an excess rejects the confirmation with
        `ERR_EVENT_POOL_EXCEEDED`."
        PRD: "windows that merely touch at an endpoint do not overlap."

        Design: Difficulty/resource_temporal_overlap/event_pool_aggregate_capacity
        """
        facility, e2 = self._build_pair(api)
        confirm_event_booking(e2["id"], [])

        e3 = create_event_booking(facility["id"], event_name="E3",
                                  start_at="2026-08-14T21:00:00Z",
                                  end_at="2026-08-14T22:00:00Z",
                                  presale_allocation=1)
        res = api.confirm_event_booking(e3["id"], [], FM)
        validate_error(res, ApiErrorId.ERR_EVENT_POOL_EXCEEDED)

        e4 = create_event_booking(facility["id"], event_name="E4",
                                  start_at="2026-08-14T23:00:00Z",
                                  end_at="2026-08-14T23:59:00Z",
                                  presale_allocation=40)
        confirmed = validate_success(api.confirm_event_booking(e4["id"], [], FM), 200)
        assert confirmed["booking_status"] == "CONFIRMED", (
            "start 23:00 == others' end 23:00 is a touching half-open boundary")


def test_staffing_insufficient_on_event_confirm(api):
    """PRD: "The roster supplied as `staffing_assignments` must then number at
    least `min_staff`, or confirmation fails with `ERR_STAFFING_INSUFFICIENT`."

    Design: Corner/validations/staffing_insufficient_on_event_confirm
    """
    facility = create_facility(name="ST Fac")
    event = create_event_booking(facility["id"], event_name="Concert",
                                 start_at="2026-08-20T18:00:00Z",
                                 end_at="2026-08-20T23:00:00Z",
                                 presale_allocation=10, min_staff=2)
    res = api.confirm_event_booking(event["id"], ["usher-1"], FM)
    validate_error(res, ApiErrorId.ERR_STAFFING_INSUFFICIENT)
    still = get_success_data(api.get_event_booking(event["id"], FM))
    assert still["booking_status"] == "REQUESTED"

    confirmed = validate_success(api.confirm_event_booking(
        event["id"], ["usher-1", "usher-2"], FM), 200)
    assert confirmed["booking_status"] == "CONFIRMED"


def test_invalid_time_range_on_event_create(api):
    """PRD: "the half-open window bounded by `start_at` and `end_at` (end
    strictly after start, else `ERR_INVALID_TIME_RANGE`)"
    PRD: "A maintenance window or event booking occupies the time from its
    start up to but not including its end; two intervals that merely touch at
    an endpoint do not overlap, and an end must be strictly after its start."

    Design: Corner/validations/invalid_time_range_on_event_create
    """
    facility = create_facility(name="TR Fac")
    res = api.create_event_booking(
        create_event_booking_payload(
            facility["id"], event_name="Zero Length",
            start_at="2026-08-10T18:00:00Z", end_at="2026-08-10T18:00:00Z",
            presale_allocation=0, min_staff=0), FM)
    validate_error(res, ApiErrorId.ERR_INVALID_TIME_RANGE)


def test_event_cancel_from_requested_zero_fee(api):
    """PRD: "From `REQUESTED`, the cancellation fee is zero."
    PRD: "Either way the cancelled booking stands in the terminal `CANCELLED`
    with `cancellation_fee_cents` storing the fee and `deposit_refund_cents`
    storing `deposit_cents` minus that fee."

    Design: Corner/state_machines/event_cancel_from_requested_zero_fee
    """
    facility = create_facility(name="EC Fac")
    event = create_event_booking(facility["id"], event_name="Early Bird",
                                 start_at="2026-08-20T18:00:00Z",
                                 end_at="2026-08-20T23:00:00Z",
                                 presale_allocation=10, deposit_cents=8000,
                                 cancellation_policy="FORFEIT_DEPOSIT")
    cancelled = validate_success(api.cancel_event_booking(
        event["id"], "venue change", FM), 200)
    assert cancelled["booking_status"] == "CANCELLED"
    assert cancelled["cancellation_fee_cents"] == 0, "REQUESTED branch ignores policy"
    assert cancelled["deposit_refund_cents"] == 8000


class TestCancellationFeePolicyVariants:
    """Two CONFIRMED events with identical deposits cancelled 72h early."""

    def _build(self, api):
        facility = create_facility(name="Evt Fac")
        ev_forfeit = create_event_booking(
            facility["id"], event_name="Forfeit Expo",
            start_at="2026-08-10T00:00:00Z", end_at="2026-08-10T23:00:00Z",
            presale_allocation=0, deposit_cents=10000,
            cancellation_policy="FORFEIT_DEPOSIT")
        ev_sliding = create_event_booking(
            facility["id"], event_name="Sliding Expo",
            start_at="2026-08-10T00:00:00Z", end_at="2026-08-10T23:00:00Z",
            presale_allocation=0, deposit_cents=10000,
            cancellation_policy="SLIDING_NOTICE")
        confirm_event_booking(ev_forfeit["id"], [])
        confirm_event_booking(ev_sliding["id"], [])
        set_clock("2026-08-07T00:00:00Z")  # exactly 72h before start
        return ev_forfeit, ev_sliding

    def test_forfeit_deposit_charges_full_deposit(self, api):
        """PRD: "under `FORFEIT_DEPOSIT` the fee is the full `deposit_cents`
        regardless of notice"

        Design: Difficulty/dual_variant_calc/event_cancellation_fee_forfeit_vs_sliding
        """
        ev_forfeit, ev_sliding = self._build(api)
        cancelled = validate_success(api.cancel_event_booking(
            ev_forfeit["id"], "organizer pulled out", FM), 200)
        assert cancelled["cancellation_fee_cents"] == 10000
        assert cancelled["deposit_refund_cents"] == 0

    def test_sliding_notice_at_or_past_48h_halves_the_fee(self, api):
        """PRD: "under `SLIDING_NOTICE`, the notice hours — the hours from the
        cancellation moment to the event's `start_at` — decide, with notice
        shorter than forty-eight hours forfeiting the full `deposit_cents` and
        notice of forty-eight hours or more halving it, rounded half-up to
        whole cents."

        Design: Difficulty/dual_variant_calc/event_cancellation_fee_forfeit_vs_sliding
        """
        ev_forfeit, ev_sliding = self._build(api)
        cancelled = validate_success(api.cancel_event_booking(
            ev_sliding["id"], "organizer pulled out", FM), 200)
        assert cancelled["cancellation_fee_cents"] == 5000, (
            "notice 72h >= 48h -> half of 10000")
        assert cancelled["deposit_refund_cents"] == 5000


class TestEventActivationCascade:
    """Depth-2 chain: event activation -> posture EVENT_SURGE -> device EVENT
    mode -> EVENT_FLAT tariff pinning."""

    def _build(self, api):
        facility, schedule, gate = setup_entry_ready_facility(name="Surge Fac")
        gate2 = register_online_gate(facility["id"], device_label="E2")
        event = create_event_booking(facility["id"], event_name="Game Night",
                                     start_at="2026-08-10T17:00:00Z",
                                     end_at="2026-08-10T23:00:00Z",
                                     presale_allocation=20, min_staff=2)
        confirm_event_booking(event["id"], ["usher-1", "usher-2"])
        set_clock("2026-08-10T18:00:00Z")
        return facility, gate, gate2, event

    def test_activation_flips_posture_and_device_modes(self, api):
        """PRD: "When the facility stands `NORMAL`, posture flips to
        `EVENT_SURGE` and the facility's `version` advances by one; every
        access device of the facility standing `ONLINE` then flips its
        `device_mode` from `STANDARD` to `EVENT`"

        Design: Difficulty/transitive_cascade/event_activation_cascades_posture_to_device_mode
        """
        facility, gate, gate2, event = self._build(api)
        activated = validate_success(api.activate_event_booking(event["id"], FM), 200)
        assert activated["booking_status"] == "ACTIVE"
        assert get_facility(facility["id"])["posture"] == "EVENT_SURGE"
        for device in (gate, gate2):
            after = get_success_data(api.get_access_device(device["id"], FM))
            assert after["device_mode"] == "EVENT"

    def test_entry_during_surge_pins_event_flat_fee(self, api):
        """PRD: "every access device of the facility standing `ONLINE` then
        flips its `device_mode` from `STANDARD` to `EVENT`, so entries taken
        during the surge pin the `EVENT_FLAT` fee mode (§3.3)."
        PRD: "Under `EVENT_FLAT`, the fee is the schedule's `event_flat_cents`,
        duration-independent."

        Design: Difficulty/transitive_cascade/event_activation_cascades_posture_to_device_mode
        """
        facility, gate, gate2, event = self._build(api)
        get_success_data(api.activate_event_booking(event["id"], FM))
        session = enter_vehicle(facility["id"], gate, "EV-1")
        assert session["fee_mode"] == "EVENT_FLAT"
        fee = quote_session_at(session["id"], "2026-08-10T20:00:00Z")["fee_cents"]
        assert fee == 1500, "2h under STANDARD would be 800; EVENT_FLAT is 1500"


class TestEventCompletionReversal:
    """Completing the last ACTIVE event unwinds the surge end to end."""

    def _build(self, api):
        facility, schedule, gate = setup_entry_ready_facility(name="Unsurge Fac")
        event = create_event_booking(facility["id"], event_name="Rally",
                                     start_at="2026-08-10T17:00:00Z",
                                     end_at="2026-08-10T23:00:00Z",
                                     presale_allocation=10, min_staff=1)
        confirm_event_booking(event["id"], ["usher-1"])
        set_clock("2026-08-10T18:00:00Z")
        get_success_data(api.activate_event_booking(event["id"], FM))
        return facility, gate, event

    def test_completion_reverses_posture_and_device_mode(self, api):
        """PRD: "Completion moves an `ACTIVE` booking to the terminal
        `COMPLETED`, and the reversal is conditional: when the completing
        event leaves no other `ACTIVE` booking at the facility and posture
        stands `EVENT_SURGE`, posture returns to `NORMAL` and every device
        still in `EVENT` mode flips back to `STANDARD` — but while another
        event remains active, the surge persists."

        Design: Difficulty/transitive_cascade/event_completion_reverses_posture_and_device_mode
        """
        facility, gate, event = self._build(api)
        set_clock("2026-08-10T23:30:00Z")
        completed = validate_success(api.complete_event_booking(event["id"], FM), 200)
        assert completed["booking_status"] == "COMPLETED"
        assert get_facility(facility["id"])["posture"] == "NORMAL", (
            "last ACTIVE event completed")
        device = get_success_data(api.get_access_device(gate["id"], FM))
        assert device["device_mode"] == "STANDARD"

    def test_next_entry_after_reversal_pins_standard_pricing(self, api):
        """PRD: "`fee_mode` pinned by precedence — `MONTHLY` when a credential
        was presented, else `EVENT_FLAT` when the entry device stands in
        `EVENT` mode, else `STANDARD`."

        Design: Difficulty/transitive_cascade/event_completion_reverses_posture_and_device_mode
        """
        facility, gate, event = self._build(api)
        set_clock("2026-08-10T23:30:00Z")
        get_success_data(api.complete_event_booking(event["id"], FM))
        set_clock("2026-08-11T10:00:00Z")
        session = enter_vehicle(facility["id"], gate, "UE-1")
        assert session["fee_mode"] == "STANDARD"
        fee = quote_session_at(session["id"], "2026-08-11T12:00:00Z")["fee_cents"]
        assert fee == 800, "2h STANDARD: 500 + 300, not the 1500 event flat"
