"""Emergency respite: triage reserve gate, dispatch side effects, stacked multipliers."""
from test_helpers import (
    ADMIN,
    COORD,
    ApiErrorId,
    assert_emergency_request,
    assert_hours,
    check_in_booking,
    check_out_visit,
    create_active_caregiver,
    create_active_provider,
    create_emergency_request_payload,
    create_program,
    create_triaged_emergency,
    decide_visit,
    api_client,
    get_success_data,
    make_caregiver_headers,
    set_clock,
    validate_error,
    validate_success,
)


def _dispatch(ctx, request):
    return get_success_data(api_client.dispatch_emergency_request(request["id"], COORD))


def test_emergency_dispatch_creates_confirmed_booking(api):
    """PRD §3.11: "First, an emergency voucher is created in `ISSUED` status with
    `allocation_id` null, `is_emergency` true, `authorized_hours` equal to
    `approved_hours`, and `expires_at` equal to `needed_end_at`."
    PRD §3.11: "Third, a booking is created directly in `CONFIRMED` status with
    `is_emergency` true, `window_id` null, and its start and end taken from the needed
    interval; the voucher moves from `ISSUED` to `COMMITTED` with `committed_hours`
    equal to `approved_hours`."
    PRD §3.11: "Fourth, the program's `emergency_hours_used` is incremented by
    `approved_hours`."
    PRD §3.11: "a provisional encumbrance is recorded against the program budget:
    `approved_hours` multiplied by `standard_rate_cents_per_hour` multiplied by
    `emergency_multiplier`"

    Design: Corner/state_machines/emergency_dispatch_creates_confirmed_booking
    """
    program = create_program()
    ctx = create_active_caregiver(program=program)
    provider = create_active_provider(name="Prov Enh", credential_level="ENHANCED",
                                      accepts_emergency=True)
    request = create_triaged_emergency(ctx["caregiver"]["id"],
                                       "2026-05-06T08:00:00Z", "2026-05-06T12:00:00Z",
                                       4, reason="hospitalization")

    dispatched = _dispatch(ctx, request)
    assert_emergency_request(dispatched)
    assert dispatched["status"] == "DISPATCHED"
    assert dispatched["selected_provider_id"] == provider["id"]

    booking = validate_success(api.get_booking(dispatched["dispatched_booking_id"], COORD), 200)
    assert booking["status"] == "CONFIRMED"
    assert booking["is_emergency"] is True
    assert booking["window_id"] is None

    bookings = get_success_data(
        api.list_bookings(COORD, params={"emergency_request_id": dispatched["id"]}))
    voucher = validate_success(api.get_voucher(bookings[0]["voucher_id"], COORD), 200)
    assert voucher["is_emergency"] is True
    assert voucher["allocation_id"] is None
    assert voucher["status"] == "COMMITTED"
    assert_hours(voucher["committed_hours"], 4.00, "voucher committed_hours")

    program = validate_success(api.get_program(ctx["program"]["id"], ADMIN), 200)
    assert_hours(program["emergency_hours_used"], 4.00, "emergency_hours_used")
    # 4h x 3000 cents/h x 2.0 emergency multiplier = 24000 provisional encumbrance.
    assert program["encumbered_cents"] == 24000


def test_emergency_reserve_exhausted_at_triage(api):
    """PRD §3.11: "Triage is also gated by the reserve: the program's
    `emergency_hours_used` plus the requested `approved_hours` must not exceed the
    program's `emergency_reserve_hours`, or triage is rejected with
    `ERR_EMERGENCY_RESERVE_EXHAUSTED`."
    PRD §3.11: "The system computes `requested_hours` as the interval from
    `needed_start_at` to `needed_end_at` in hours, at two decimal places."

    Design: Corner/errors/emergency_reserve_exhausted_at_triage
    """
    program = create_program()
    ctx = create_active_caregiver(program=program)
    request = get_success_data(api_client.create_emergency_request(
        create_emergency_request_payload(ctx["caregiver"]["id"],
                                         "2026-05-04T08:00:00Z", "2026-05-14T08:00:00Z",
                                         "surgery recovery"),
        make_caregiver_headers(ctx["caregiver"]["id"])))
    assert_hours(request["requested_hours"], 240.00, "requested_hours")

    res = api.triage_emergency_request(request["id"], {"approved_hours": 240}, COORD)
    validate_error(res, ApiErrorId.ERR_EMERGENCY_RESERVE_EXHAUSTED, expected_status=422)
    after = validate_success(api.get_emergency_request(request["id"], COORD), 200)
    assert after["status"] == "OPEN"


class TestEmergencyWeekendEnhancedStack:
    def _stacked_claim(self, api):
        """Saturday 2026-05-02 10:00-14:00 emergency, ENHANCED provider, 90-minute
        actual visit. Returns (ctx, visit, claim)."""
        program = create_program()
        ctx = create_active_caregiver(program=program)
        provider = create_active_provider(name="Prov Enh", credential_level="ENHANCED",
                                          accepts_emergency=True)
        request = create_triaged_emergency(ctx["caregiver"]["id"],
                                           "2026-05-02T10:00:00Z", "2026-05-02T14:00:00Z",
                                           4, reason="caregiver hospitalized")
        dispatched = _dispatch(ctx, request)
        booking_id = dispatched["dispatched_booking_id"]
        visit = check_in_booking(booking_id, provider["id"], "2026-05-02T10:00:00Z")
        visit = check_out_visit(visit["id"], provider["id"], "2026-05-02T11:30:00Z",
                                {"tasks_completed": ["meal_prep"]})
        decide_visit(visit["id"], "VERIFY")
        claims = get_success_data(
            api.list_claims(COORD, params={"visit_record_id": visit["id"]}))
        assert len(claims) == 1
        return ctx, visit, claims[0]

    def test_stacked_visit_minutes(self, api):
        """PRD §3.9: "`verified_minutes` is that elapsed time rounded up to the nearest
        15-minute unit — that is, 15 multiplied by the round-half-up of the elapsed
        minutes divided by 15. `payable_minutes` is the smaller of `verified_minutes`
        and the floor of the booking's `committed_minutes` multiplied by the program's
        `max_overage_pct`."

        Design: Difficulty/combinatorial_formula/claim_amount_emergency_weekend_enhanced_stack
        """
        _ctx, visit, _claim = self._stacked_claim(api)
        # 10:00 -> 11:30 is 90 elapsed minutes; cap floor(240 x 1.10) = 264 does not bind.
        assert visit["verified_minutes"] == 90
        assert visit["payable_minutes"] == 90

    def test_stacked_claim_amount(self, api):
        """PRD §3.10: "Second, a day multiplier is chosen: if the visit's `check_in_at`
        falls on a Saturday or Sunday in UTC the multiplier is the program's
        `weekend_multiplier`; otherwise if the UTC hour of `check_in_at` is at or after
        the program's `evening_start_hour` the multiplier is the program's
        `evening_multiplier`; otherwise the multiplier is 1.0."
        PRD §3.10: "Third, a credential multiplier is applied: the program's
        `credential_premium_multiplier` when the billing provider's `credential_level`
        is `ENHANCED`, else 1.0."
        PRD §3.10: "Fourth, an emergency multiplier is applied: the program's
        `emergency_multiplier` when the booking's `is_emergency` is true, else 1.0."
        PRD §3.10: "The claim's `amount_cents` is then the base minutes multiplied by
        the program's `standard_rate_cents_per_hour`, multiplied by all three
        applicable multipliers, divided by 60, and rounded half up to integer cents."

        Design: Difficulty/combinatorial_formula/claim_amount_emergency_weekend_enhanced_stack
        """
        _ctx, _visit, claim = self._stacked_claim(api)
        # 90 x 3000 x 1.5 (Saturday) x 1.10 (ENHANCED) x 2.0 (emergency) / 60 = 14850.
        assert claim["amount_cents"] == 14850
