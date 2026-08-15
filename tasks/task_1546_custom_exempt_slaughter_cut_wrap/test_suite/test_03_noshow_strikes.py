"""No-show rules, strike policy, animal identity, and drop-off bubble-up.

Covers the premature no-show guard, the depth-2 no-show cascade (animals
voided, capacity released, deposit forfeited, strike charged), the two-strike
booking block, VOIDED terminal lockdown, tag uniqueness, and the
last-expected-animal appointment completion.
"""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    book_and_confirm,
    book_appointment,
    create_appointment_payload,
    create_capacity_day,
    create_customer,
    earn_no_show_strike,
    get_appointment,
    get_capacity_day_by_date,
    get_customer,
    get_success_data,
    list_appointment_animals,
    make_customer_headers,
    receive_animal_payload,
    set_logical_clock,
    validate_error,
    validate_success,
)

OP = TEST_USERS["operator_headers"]


class TestNoShowGuard:
    def test_no_show_before_appointment_date_rejected(self, api):
        """PRD §3.2: "the manual mark is only allowed on or after
        `appointment_date`, and an attempt before that date is rejected with
        `ERR_NO_SHOW_PREMATURE`."

        Design: Corner/validations/no_show_before_appointment_date_rejected
        """
        customer = create_customer()
        day = create_capacity_day("2026-08-20", 1)
        appointment, _ = book_and_confirm(customer["id"], day["id"], "BEEF", 1)
        # Clock is still the default 2026-08-01, long before the date.
        resp = api.mark_no_show(appointment["id"], OP)
        validate_error(resp, ApiErrorId.ERR_NO_SHOW_PREMATURE, expected_status=422)
        after = get_appointment(appointment["id"])
        assert after["status"] == "CONFIRMED"
        assert get_customer(customer["id"])["no_show_strikes"] == 0


class TestNoShowCascade:
    def _setup_confirmed_on_0816(self):
        customer = create_customer()
        day = create_capacity_day("2026-08-16", 3)
        appointment, animals = book_and_confirm(
            customer["id"], day["id"], "BEEF", 2
        )
        set_logical_clock("2026-08-16T00:00:00Z")
        return customer, day, appointment, animals

    def test_no_show_voids_animals_and_forfeits_deposit(self, api):
        """PRD §3.2: "The no-show voids each expected animal with the usual
        per-head capacity release, forfeits the deposit (`refund_cents` stays
        zero and the plant retains `deposit_paid_cents`)".

        Design: Difficulty/transitive_cascade/no_show_cascade_animals_to_capacity_release
        """
        customer, _day, appointment, animals = self._setup_confirmed_on_0816()
        data = validate_success(api.mark_no_show(appointment["id"], OP))
        assert data["status"] == "NO_SHOW"
        assert data["refund_cents"] == 0, "no-show forfeits the deposit"
        after_animals = list_appointment_animals(appointment["id"])
        assert len(after_animals) == 2
        for animal in after_animals:
            assert animal["status"] == "VOIDED"

    def test_no_show_releases_capacity_and_charges_strike(self, api):
        """PRD §3.2: "The no-show voids each expected animal with the usual
        per-head capacity release, forfeits the deposit ..., increments the
        customer's `no_show_strikes` by one, and recomputes the customer's
        standing, which flips to `ELEVATED_DEPOSIT` on the first strike and
        `BLOCKED` on the second."
        PRD §3.1: "the day flips to `FULL` exactly when `booked_head` reaches
        `capacity_head` and returns to `OPEN` the moment a cancellation,
        expiry, or no-show releases headroom."

        Design: Difficulty/transitive_cascade/no_show_cascade_animals_to_capacity_release
        """
        customer, day, appointment, _animals = self._setup_confirmed_on_0816()
        assert get_capacity_day_by_date("2026-08-16")["booked_head"] == 2
        validate_success(api.mark_no_show(appointment["id"], OP))
        day_after = get_capacity_day_by_date("2026-08-16")
        assert day_after["booked_head"] == 0, (
            "each voided animal releases one head of capacity"
        )
        assert day_after["status"] == "OPEN"
        customer_after = get_customer(customer["id"])
        assert customer_after["no_show_strikes"] == 1
        assert customer_after["status"] == "ELEVATED_DEPOSIT"


class TestStrikeBlock:
    def test_second_strike_blocks_booking(self, api):
        """PRD §3.8: "a second strike moves them to `BLOCKED`, which refuses
        new bookings outright with `ERR_CUSTOMER_BLOCKED`".
        PRD §3.1: "a customer whose standing is `BLOCKED` is turned away with
        `ERR_CUSTOMER_BLOCKED`".

        Design: Corner/validations/second_strike_blocks_booking
        """
        customer = create_customer()
        # Strike 1: no-show on 2026-08-15 (exactly 14 days out at booking).
        earn_no_show_strike(customer["id"], "2026-08-15", species="BEEF",
                            head_count=1)
        # Second booking under ELEVATED_DEPOSIT: BEEF 1 head quotes 38620.
        day2 = create_capacity_day("2026-08-29", 1)
        second = book_appointment(customer["id"], day2["id"], "BEEF", 1)
        assert second["deposit_amount_cents"] == 38620, (
            "the strike switches the deposit to the elevated variant (PRD §3.1)"
        )
        # Strike 2: no-show on 2026-08-29.
        pay_full = get_success_data(
            api.pay_deposit(second["id"], {"amount_cents": 38620},
                            make_customer_headers(customer["id"]))
        )
        assert pay_full["status"] == "CONFIRMED"
        set_logical_clock("2026-08-29T00:00:00Z")
        get_success_data(api.mark_no_show(second["id"], OP))
        # Now BLOCKED: a fresh, lead-time-legal booking is refused.
        day3 = create_capacity_day("2026-09-13", 1)
        resp = api.create_appointment(
            create_appointment_payload(customer["id"], day3["id"], "BEEF", 1),
            make_customer_headers(customer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_CUSTOMER_BLOCKED, expected_status=403)
        customer_after = get_customer(customer["id"])
        assert customer_after["no_show_strikes"] == 2
        assert customer_after["status"] == "BLOCKED"


class TestAnimalIdentity:
    def test_animal_voided_terminal_lockdown(self, api):
        """PRD §3.2: "The no-show voids each expected animal with the usual
        per-head capacity release".
        PRD §2.8: "then state-transition legality including terminal-state
        lockdown (`ERR_INVALID_STATE`, HTTP 409)".

        Design: Corner/state_machines/animal_voided_terminal_lockdown
        """
        customer = create_customer()
        day = create_capacity_day("2026-08-15", 1)
        appointment, animals = book_and_confirm(
            customer["id"], day["id"], "BEEF", 1
        )
        set_logical_clock("2026-08-15T00:00:00Z")
        get_success_data(api.mark_no_show(appointment["id"], OP))
        resp = api.receive_animal(
            animals[0]["id"], receive_animal_payload("TAG-LATE", 1100.0), OP
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
        animals_after = list_appointment_animals(appointment["id"])
        assert animals_after[0]["status"] == "VOIDED"

    def test_receive_duplicate_tag_rejected(self, api):
        """PRD §3.3: "`tag_id` must be unique among all animals not in
        `VOIDED` — a duplicate is refused with `ERR_DUPLICATE_TAG`".

        Design: Corner/validations/receive_duplicate_tag_rejected
        """
        customer = create_customer()
        day = create_capacity_day("2026-08-20", 2)
        appointment, animals = book_and_confirm(
            customer["id"], day["id"], "BEEF", 2
        )
        get_success_data(
            api.receive_animal(
                animals[0]["id"], receive_animal_payload("TAG-A1", 1200.0), OP
            )
        )
        resp = api.receive_animal(
            animals[1]["id"], receive_animal_payload("TAG-A1", 1150.0), OP
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_TAG, expected_status=409)
        animals_after = list_appointment_animals(appointment["id"])
        assert animals_after[1]["status"] == "EXPECTED", (
            "rejected duplicate tag must not receive the second animal"
        )

    def test_receive_last_expected_completes_appointment(self, api):
        """PRD §3.3: "Receiving also drives the appointment's bubble-up: when
        the last `EXPECTED` animal of an appointment is received, the
        appointment moves automatically from `CONFIRMED` to `COMPLETED`."

        Design: Corner/state_machines/receive_last_expected_completes_appointment
        """
        customer = create_customer()
        day = create_capacity_day("2026-08-20", 2)
        appointment, animals = book_and_confirm(
            customer["id"], day["id"], "BEEF", 2
        )
        get_success_data(
            api.receive_animal(
                animals[0]["id"], receive_animal_payload("TAG-A1", 1200.0), OP
            )
        )
        assert get_appointment(appointment["id"])["status"] == "CONFIRMED", (
            "one EXPECTED animal remains, so the appointment stays CONFIRMED"
        )
        get_success_data(
            api.receive_animal(
                animals[1]["id"], receive_animal_payload("TAG-A2", 1150.0), OP
            )
        )
        assert get_appointment(appointment["id"])["status"] == "COMPLETED"
