"""Registration intake: age computation, pagination, uniqueness, capacity,
the intake phase gate, withdrawal, and the payment x lifecycle dimensions."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    build_race,
    create_registration_payload,
    start_waves,
    validate_error,
    validate_paginated,
    validate_success,
)

RD = TEST_USERS["race_director_headers"]
CLERK = TEST_USERS["registration_clerk_headers"]

WAVE_7AM = {"key": "w1", "wave_index": 1,
            "scheduled_start_time": "2026-08-01T07:00:00Z", "max_capacity": 100}


def _open_race_with_wave(api, name, max_capacity=100):
    return build_race(
        name=name, distance_km=5.0, course_type="UNCERTIFIED_COURSE",
        cutoff_minutes=90, points=(),
        waves=[dict(WAVE_7AM, max_capacity=max_capacity)],
        chips=(), registrations=(), lock=False)


class TestAgeBracketBoundaries:
    def _three_athletes(self, api):
        ctx = build_race(
            name="Age Bracket 5K", distance_km=5.0,
            course_type="UNCERTIFIED_COURSE", cutoff_minutes=90, points=(),
            waves=[WAVE_7AM], chips=(),
            registrations=[
                {"key": "f1", "wave": "w1", "bib_number": "301",
                 "participant_name": "F Twenty", "birth_date": "2006-08-01",
                 "gender": "F", "pay": False, "confirm": False},
                {"key": "f2", "wave": "w1", "bib_number": "302",
                 "participant_name": "F Nineteen", "birth_date": "2006-08-02",
                 "gender": "F", "pay": False, "confirm": False},
                {"key": "f3", "wave": "w1", "bib_number": "303",
                 "participant_name": "F Eighty", "birth_date": "1946-07-31",
                 "gender": "F", "pay": False, "confirm": False},
            ],
            lock=False)
        return ctx

    def test_age_twenty_on_race_day_lands_in_20_24(self, api):
        """PRD §3.2: "`age_on_race_day` is the athlete's age in full years on the
        race date: the difference between the race year and the birth year,
        reduced by one when the race date's month and day fall earlier in the
        calendar than the birth month and day."
        PRD §3.2: "The boundaries are exact: an athlete who is exactly 20 on race
        day belongs to `20-24`, not `1-19`, and an athlete who is exactly 80
        belongs to `80+`, not `75-79`."

        Design: Difficulty/combinatorial_formula/age_bracket_boundary_categorization
        """
        ctx = self._three_athletes(api)
        f1 = validate_success(api.get_registration(ctx["regs"]["f1"]["id"], CLERK), 200)
        assert f1["age_on_race_day"] == 20, "birthday on race day counts as reached"
        assert f1["age_group"] == "20-24"

    def test_age_nineteen_birthday_after_race_day_lands_in_1_19(self, api):
        """PRD §3.2: "`age_on_race_day` is the athlete's age in full years on the
        race date: the difference between the race year and the birth year,
        reduced by one when the race date's month and day fall earlier in the
        calendar than the birth month and day."
        PRD §3.2: "athletes younger than 20 fall into `1-19`"

        Design: Difficulty/combinatorial_formula/age_bracket_boundary_categorization
        """
        ctx = self._three_athletes(api)
        f2 = validate_success(api.get_registration(ctx["regs"]["f2"]["id"], CLERK), 200)
        assert f2["age_on_race_day"] == 19, "birthday one day after race day"
        assert f2["age_group"] == "1-19"

    def test_age_eighty_exactly_lands_in_masters_bracket(self, api):
        """PRD §3.2: "The boundaries are exact: an athlete who is exactly 20 on
        race day belongs to `20-24`, not `1-19`, and an athlete who is exactly 80
        belongs to `80+`, not `75-79`."

        Design: Difficulty/combinatorial_formula/age_bracket_boundary_categorization
        """
        ctx = self._three_athletes(api)
        f3 = validate_success(api.get_registration(ctx["regs"]["f3"]["id"], CLERK), 200)
        assert f3["age_on_race_day"] == 80, "masters bracket at exactly 80"
        assert f3["age_group"] == "80+"


class TestRegistrationListing:
    def test_registration_list_pagination_defaults(self, api):
        """PRD §2.3: "The `limit` parameter caps the number of items returned: it
        defaults to 10 when omitted, accepts a minimum of 1, and is capped at a
        maximum of 100. The `offset` parameter skips a number of items from the
        front of the result set and defaults to 0."
        PRD §2.3: "List responses carry the following pagination fields in the
        `meta` object of the response envelope: `limit`, `offset`, `total_count`,
        and `has_more`."

        Design: Corner/entities/registration_list_pagination_defaults
        """
        ctx = build_race(
            name="Page 5K", distance_km=5.0, course_type="UNCERTIFIED_COURSE",
            cutoff_minutes=90, points=(),
            waves=[dict(WAVE_7AM, max_capacity=20)], chips=(),
            registrations=[
                {"key": f"p{i}", "wave": "w1", "bib_number": str(900 + i),
                 "participant_name": f"P{900 + i}", "birth_date": "1990-01-01",
                 "gender": "M", "pay": False, "confirm": False}
                for i in range(11)
            ],
            lock=False)
        race_id = ctx["race"]["id"]

        data, meta = validate_paginated(
            api.list_registrations(CLERK, params={"race_id": race_id}))
        assert len(data) == 10, "default page limit is 10"
        assert meta["total_count"] == 11
        assert meta["has_more"] is True
        assert meta["limit"] == 10 and meta["offset"] == 0

        data2, meta2 = validate_paginated(api.list_registrations(
            CLERK, params={"race_id": race_id, "limit": 10, "offset": 10}))
        assert len(data2) == 1
        assert meta2["total_count"] == 11
        assert meta2["has_more"] is False


class TestIntakeGatesAndUniqueness:
    def test_bib_unique_spans_withdrawn(self, api):
        """PRD §3.2: "The `bib_number` must be unique across every registration
        of the race in any lifecycle state — even a withdrawn athlete's bib stays
        retired — and a collision fails with `ERR_BIB_NUMBER_TAKEN`."

        Design: Corner/validations/bib_unique_spans_withdrawn
        """
        ctx = _open_race_with_wave(api, "Bib 5K", max_capacity=10)
        race_id, wave_id = ctx["race"]["id"], ctx["waves"]["w1"]["id"]
        reg1 = validate_success(api.create_registration(
            create_registration_payload(race_id, wave_id, "111", "First Holder",
                                        "1990-01-01", "M"), CLERK), 201)
        validate_success(api.withdraw_registration(reg1["id"], CLERK), 200)

        resp = api.create_registration(
            create_registration_payload(race_id, wave_id, "111", "Second Holder",
                                        "1992-02-02", "F"), CLERK)
        validate_error(resp, ApiErrorId.ERR_BIB_NUMBER_TAKEN, expected_status=409)

    def test_wave_capacity_boundary(self, api):
        """PRD §3.2: "Finally, wave occupancy is enforced: the number of
        registrations in the wave in any state other than `WITHDRAWN` must remain
        below the wave's `max_capacity`, and a full wave rejects with
        `ERR_WAVE_CAPACITY_FULL`."

        Design: Corner/validations/wave_capacity_boundary
        """
        ctx = _open_race_with_wave(api, "Cap 5K", max_capacity=2)
        race_id, wave_id = ctx["race"]["id"], ctx["waves"]["w1"]["id"]
        reg_c1 = validate_success(api.create_registration(
            create_registration_payload(race_id, wave_id, "201", "Cap One",
                                        "1990-01-01", "M"), CLERK), 201)
        validate_success(api.create_registration(
            create_registration_payload(race_id, wave_id, "202", "Cap Two",
                                        "1990-01-01", "M"), CLERK), 201)

        resp = api.create_registration(
            create_registration_payload(race_id, wave_id, "203", "Cap Three",
                                        "1990-01-01", "M"), CLERK)
        validate_error(resp, ApiErrorId.ERR_WAVE_CAPACITY_FULL, expected_status=409)

        # WITHDRAWN registrations drop out of occupancy, re-admitting a new one.
        validate_success(api.withdraw_registration(reg_c1["id"], CLERK), 200)
        reg_c3 = validate_success(api.create_registration(
            create_registration_payload(race_id, wave_id, "203", "Cap Three",
                                        "1990-01-01", "M"), CLERK), 201)
        assert reg_c3["lifecycle_status"] == "REGISTERED"

    def test_register_after_lock_returns_409(self, api):
        """PRD §3.4: "From this moment, registration intake closes — new
        registrations, payments, and confirmations all fail the intake gate of
        §3.2"
        PRD §3.2: "it is evaluated before the uniqueness and capacity checks, so
        a closed race surfaces `ERR_RACE_REGISTRATION_CLOSED` rather than a later
        failure."

        Design: Corner/validations/register_after_lock_returns_409
        """
        ctx = build_race(
            name="ClosedReg 5K", distance_km=5.0,
            course_type="UNCERTIFIED_COURSE", cutoff_minutes=90,
            points=[
                {"key": "start", "point_index": 1, "kind": "START",
                 "distance_km": 0.0},
                {"key": "finish", "point_index": 2, "kind": "FINISH",
                 "distance_km": 5.0},
            ],
            waves=[dict(WAVE_7AM, max_capacity=10)], chips=(), registrations=(),
            lock=True)
        resp = api.create_registration(
            create_registration_payload(ctx["race"]["id"], ctx["waves"]["w1"]["id"],
                                        "870", "Too Late", "1990-01-01", "M"),
            CLERK)
        validate_error(resp, ApiErrorId.ERR_RACE_REGISTRATION_CLOSED,
                       expected_status=409)

    def test_withdraw_after_start_rejected(self, api):
        """PRD §3.2: "Withdrawal moves a registration from `REGISTERED`,
        `CONFIRMED`, or `CHECKED_IN` into the terminal `WITHDRAWN` state, but
        only before the race goes live: once the race has reached `IN_PROGRESS`,
        `PROVISIONAL_PUBLISHED`, `FINALIZED`, or `AMENDMENT_OPEN`, withdrawal is
        rejected with `ERR_RACE_ALREADY_STARTED`."

        Design: Corner/state_machines/withdraw_after_start_rejected
        """
        ctx = build_race(
            name="Withdraw 5K", distance_km=5.0,
            course_type="UNCERTIFIED_COURSE", cutoff_minutes=90,
            points=[
                {"key": "start", "point_index": 1, "kind": "START",
                 "distance_km": 0.0},
                {"key": "finish", "point_index": 2, "kind": "FINISH",
                 "distance_km": 5.0},
            ],
            waves=[dict(WAVE_7AM, max_capacity=10)], chips=(),
            registrations=[{"key": "w1r", "wave": "w1", "bib_number": "720",
                            "participant_name": "W One", "birth_date": "1990-01-01",
                            "gender": "M"}],
            lock=True)
        start_waves(ctx, {"w1": "2026-08-01T07:00:00Z"})

        reg_id = ctx["regs"]["w1r"]["id"]
        resp = api.withdraw_registration(reg_id, CLERK)
        validate_error(resp, ApiErrorId.ERR_RACE_ALREADY_STARTED, expected_status=409)
        reg = validate_success(api.get_registration(reg_id, CLERK), 200)
        assert reg["lifecycle_status"] == "CONFIRMED"
        assert reg["payment_status"] == "PAID"


class TestPaymentLifecycleDimensions:
    def _two_registrations(self, api):
        return build_race(
            name="Parallel Dims 5K", distance_km=5.0,
            course_type="UNCERTIFIED_COURSE", cutoff_minutes=90, points=(),
            waves=[dict(WAVE_7AM, max_capacity=10)], chips=(),
            registrations=[
                {"key": "s1", "wave": "w1", "bib_number": "701",
                 "participant_name": "S One", "birth_date": "1993-03-03",
                 "gender": "F", "pay": False, "confirm": False},
                {"key": "s2", "wave": "w1", "bib_number": "702",
                 "participant_name": "S Two", "birth_date": "1994-04-04",
                 "gender": "F", "pay": False, "confirm": False},
            ],
            lock=False)

    def test_payment_advances_while_lifecycle_stays_registered(self, api):
        """PRD §3.2: "A registration evolves along two independent dimensions.
        Its `lifecycle_status` begins at `REGISTERED`; its `payment_status`
        begins at `UNPAID`; and it holds no chip, with `chip_id` null. Recording
        a payment moves the payment dimension `UNPAID → PAID`, allowed for any
        registration that is not `WITHDRAWN` while the race remains in
        `REGISTRATION_OPEN`."

        Design: Difficulty/non_linear_state_machine/registration_parallel_dimensions
        """
        ctx = self._two_registrations(api)
        s1_id = ctx["regs"]["s1"]["id"]
        paid = validate_success(api.pay_registration(s1_id, CLERK), 200)
        assert paid["payment_status"] == "PAID"
        assert paid["lifecycle_status"] == "REGISTERED", (
            "the payment dimension advances independently of the lifecycle"
        )
        assert paid.get("chip_id") is None

    def test_confirm_requires_payment_then_succeeds_after_pay(self, api):
        """PRD §3.2: "Confirmation moves the lifecycle dimension `REGISTERED →
        CONFIRMED` and requires the payment to have arrived first — confirming
        while `payment_status` is anything other than `PAID` fails with
        `ERR_PAYMENT_REQUIRED`."

        Design: Difficulty/non_linear_state_machine/registration_parallel_dimensions
        """
        ctx = self._two_registrations(api)
        s2_id = ctx["regs"]["s2"]["id"]
        resp = api.confirm_registration(s2_id, CLERK)
        validate_error(resp, ApiErrorId.ERR_PAYMENT_REQUIRED, expected_status=409)

        validate_success(api.pay_registration(s2_id, CLERK), 200)
        confirmed = validate_success(api.confirm_registration(s2_id, CLERK), 200)
        assert confirmed["lifecycle_status"] == "CONFIRMED"
        assert confirmed["payment_status"] == "PAID"


class TestStateBeatsFiscalOnConfirm:
    def test_confirm_withdrawn_unpaid_returns_invalid_state(self, api):
        """PRD §2.7: "Every mutating request passes through a fixed validation
        pipeline, and the first failing stage produces the response. The stages
        run in this order: first authentication (the headers of §2.1), then role
        authorization, then existence of every referenced identifier per §2.10,
        then state-transition legality — immediately followed by the race-phase
        gates that close registration intake, freeze the timing configuration,
        and govern read ingest and flag handling — then optimistic concurrency
        where §2.8 applies, then segregation of duties per §2.9, then temporal
        business rules such as the protest window, the race cutoff, wave spacing,
        and device deployment windows, then structural constraints such as
        uniqueness and chip availability, then referential integrity of the
        dockets, and finally capacity and payment rules."
        PRD §3.2: "Confirmation moves the lifecycle dimension `REGISTERED →
        CONFIRMED` and requires the payment to have arrived first — confirming
        while `payment_status` is anything other than `PAID` fails with
        `ERR_PAYMENT_REQUIRED`."

        Design: Difficulty/priority_pair_validation_conflict/confirm_withdrawn_unpaid_state_beats_fiscal
        """
        ctx = build_race(
            name="Priority 5K", distance_km=5.0,
            course_type="UNCERTIFIED_COURSE", cutoff_minutes=90, points=(),
            waves=[dict(WAVE_7AM, max_capacity=10)], chips=(),
            registrations=[{"key": "v1", "wave": "w1", "bib_number": "111",
                            "participant_name": "V One", "birth_date": "1990-01-01",
                            "gender": "M", "pay": False, "confirm": False}],
            lock=False)
        reg_id = ctx["regs"]["v1"]["id"]
        withdrawn = validate_success(api.withdraw_registration(reg_id, CLERK), 200)
        assert withdrawn["lifecycle_status"] == "WITHDRAWN"
        assert withdrawn["payment_status"] == "UNPAID"

        resp = api.confirm_registration(reg_id, CLERK)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
        reg = validate_success(api.get_registration(reg_id, CLERK), 200)
        assert reg["lifecycle_status"] == "WITHDRAWN"
        assert reg["payment_status"] == "UNPAID", "both violations; state wins, nothing changed"

    def test_confirm_unpaid_alone_returns_payment_required(self, api):
        """PRD §3.2: "Confirmation moves the lifecycle dimension `REGISTERED →
        CONFIRMED` and requires the payment to have arrived first — confirming
        while `payment_status` is anything other than `PAID` fails with
        `ERR_PAYMENT_REQUIRED`."

        With the lifecycle transition itself legal (REGISTERED), only the
        payment gate can fail, isolating the fiscal rule the pair test resolves
        against.

        Design: Difficulty/priority_pair_validation_conflict/confirm_withdrawn_unpaid_state_beats_fiscal
        """
        ctx = build_race(
            name="Fiscal 5K", distance_km=5.0,
            course_type="UNCERTIFIED_COURSE", cutoff_minutes=90, points=(),
            waves=[dict(WAVE_7AM, max_capacity=10)], chips=(),
            registrations=[{"key": "v2", "wave": "w1", "bib_number": "112",
                            "participant_name": "V Two", "birth_date": "1990-01-01",
                            "gender": "M", "pay": False, "confirm": False}],
            lock=False)
        resp = api.confirm_registration(ctx["regs"]["v2"]["id"], CLERK)
        validate_error(resp, ApiErrorId.ERR_PAYMENT_REQUIRED, expected_status=409)
