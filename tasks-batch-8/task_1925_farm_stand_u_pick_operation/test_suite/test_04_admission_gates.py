"""Gate admission: waiver trio, capacity gates, and creation preconditions."""
from test_helpers import (
    TEST_USERS,
    activate_season,
    admit_online_session,
    create_season,
    create_visit_session_payload,
    create_waiver_payload,
    get_session,
    get_window,
    setup_operating_day,
    setup_paid_session,
    sign_waiver,
    validate_error,
    validate_success,
    weigh_out,
)

MANAGER = TEST_USERS["farm_manager_headers"]
GATE = TEST_USERS["gate_staff_headers"]
FIELD_STAFF = TEST_USERS["field_staff_headers"]
ANON = TEST_USERS["anonymous_headers"]


class TestWaiverLifecycle:
    def test_waiver_initial_state_and_double_void_returns_invalid_state(self, api):
        """PRD §3.1: "A new waiver is `SIGNED` and pins `waiver_version_signed`
        to the season's `current_waiver_version` at signing time."
        PRD §3.1: "The only stored status change a waiver ever undergoes is
        voiding: a `FarmManager` may void a signed waiver, moving it from
        `SIGNED` to the terminal `VOIDED`."
        PRD §2.7: "the addressed resource's own state must permit the requested
        transition"

        Design: Corner/state_machines/waiver_initial_state_and_double_void_returns_invalid_state
        """
        season = create_season()
        activate_season(season["id"])
        waiver = validate_success(api.create_waiver(
            create_waiver_payload(season["id"]), ANON), 201)
        assert waiver["status"] == "SIGNED"
        assert waiver["waiver_version_signed"] == 1

        voided = validate_success(api.void_waiver(waiver["id"], MANAGER))
        assert voided["status"] == "VOIDED"

        resp = api.void_waiver(waiver["id"], MANAGER)
        validate_error(resp, "ERR_INVALID_STATE", 409)


class TestWaiverTrioAtAdmission:
    def test_waiver_party_mismatch_rejected(self, api):
        """PRD §2.7: "then the waiver's `party_member_names` must list at least
        as many names as the session's `party_size`
        (`ERR_WAIVER_PARTY_MISMATCH`, 422)."

        Design: Corner/validations/waiver_party_mismatch_rejected
        """
        world = setup_operating_day()  # waiver covers exactly 1 name
        resp = api.create_visit_session(
            create_visit_session_payload(world["window_id"], world["waiver_id"],
                                         party_size=2),
            GATE)
        validate_error(resp, "ERR_WAIVER_PARTY_MISMATCH", 422)

    def test_waiver_voided_blocks_session_create(self, api):
        """PRD §2.7: "the waiver's stored status must be `SIGNED`
        (`ERR_WAIVER_VOIDED`, 422)"

        Design: Corner/validations/waiver_voided_blocks_session_create
        """
        world = setup_operating_day()
        validate_success(api.void_waiver(world["waiver_id"], MANAGER))
        resp = api.create_visit_session(
            create_visit_session_payload(world["window_id"], world["waiver_id"]),
            GATE)
        validate_error(resp, "ERR_WAIVER_VOIDED", 422)


class TestSessionCreationPreconditions:
    def test_session_create_window_not_open_rejected(self, api):
        """PRD §3.4: "The cross-resource state checks then confirm the window
        is `OPEN` (`ERR_WINDOW_NOT_OPEN`) and the sales day is `OPEN`
        (`ERR_DAY_NOT_OPEN`)."

        Design: Corner/state_machines/session_create_window_not_open_rejected
        """
        world = setup_operating_day(do_open_window=False)  # window stays SCHEDULED
        resp = api.create_visit_session(
            create_visit_session_payload(world["window_id"], world["waiver_id"]),
            GATE)
        validate_error(resp, "ERR_WINDOW_NOT_OPEN", 409)

    def test_session_create_without_active_policy_rejected(self, api):
        """PRD §3.4: "the season must have an `ACTIVE` pricing policy to pin
        (`ERR_NO_ACTIVE_POLICY`)"

        Design: Corner/validations/session_create_without_active_policy_rejected
        """
        world = setup_operating_day(with_policy=False)
        resp = api.create_visit_session(
            create_visit_session_payload(world["window_id"], world["waiver_id"]),
            GATE)
        validate_error(resp, "ERR_NO_ACTIVE_POLICY", 409)

    def test_session_create_field_depleted_gate(self, api):
        """PRD §3.4: "the window's field must not be projected-picked-out —
        its `projected_remaining_oz` must be greater than zero
        (`ERR_FIELD_DEPLETED`), which is why provisional offline weight counts
        against the field before verification."

        Design: Corner/validations/session_create_field_depleted_gate
        """
        world = setup_operating_day(estimated_harvest_oz=100,
                                    waiver_names=("Ann",))
        wv_b = sign_waiver(world["season_id"], ["Bob"], signer_name="Bob",
                           signer_email="bob@x.com")
        session_a = setup_paid_session(world, container_count=4, enter=True)
        weigh_out(session_a["id"], world["crop_id"], 116, 4)  # net 100 oz

        resp = api.create_visit_session(
            create_visit_session_payload(world["window_id"], wv_b["id"]),
            GATE)
        validate_error(resp, "ERR_FIELD_DEPLETED", 422)
        # The grace window itself is untouched: the gate is the projection.
        assert get_window(world["window_id"])["status"] == "OPEN"

    def test_unpaid_balance_blocks_enter_field(self, api):
        """PRD §3.4: "the party must have paid for admission: the session's
        `total_paid_cents` minus `total_refunded_cents` must be at least
        `admission_charge_cents` (`ERR_UNPAID_BALANCE`)."

        Design: Corner/validations/unpaid_balance_blocks_enter_field
        """
        world = setup_operating_day()
        session = admit_online_session(world)  # never paid
        resp = api.enter_field(session["id"], FIELD_STAFF)
        validate_error(resp, "ERR_UNPAID_BALANCE", 422)
        assert get_session(session["id"])["visit_status"] == "CHECKED_IN"


class TestCapacityAggregates:
    def test_cancelled_sessions_free_their_slots(self, api):
        """PRD §3.3: "A window's `booked_slots` is the sum of `party_size`
        over the window's sessions whose `visit_status` is neither `CANCELLED`
        nor `VOIDED`."
        PRD §3.4: "cancellation moves a `CHECKED_IN` session to `CANCELLED`,
        releases its `party_size` and `parking_spaces` from the window and day
        aggregates"

        Design: Corner/calculations/cancelled_sessions_free_their_slots
        """
        names_a = [f"A{i}" for i in range(1, 11)]
        names_b = [f"B{i}" for i in range(1, 11)]
        world = setup_operating_day(waiver_names=names_a)
        wv_b = sign_waiver(world["season_id"], names_b, signer_name="Bob",
                           signer_email="bob@x.com")
        session_a = admit_online_session(world, party_size=10)
        validate_success(api.cancel_session(session_a["id"], GATE))
        assert get_window(world["window_id"])["booked_slots"] == 0, (
            "CANCELLED sessions leave the booked_slots input set")

        admit_online_session(world, party_size=10, waiver_id=wv_b["id"])
        assert get_window(world["window_id"])["booked_slots"] == 10

    def test_parking_exact_capacity_then_overflow(self, api):
        """PRD §3.4: "the day's `booked_parking` plus `parking_spaces` must not
        exceed `parking_capacity` (`ERR_PARKING_FULL`)"
        PRD §3.3: "A sales day's `booked_parking` applies the same inclusion
        set across `parking_spaces` on every window of that date"

        Design: Corner/validations/parking_exact_capacity_then_overflow
        """
        world = setup_operating_day(parking_capacity=3)
        wv_b = sign_waiver(world["season_id"], ["Bob"], signer_name="Bob",
                           signer_email="bob@x.com")
        wv_c = sign_waiver(world["season_id"], ["Cid"], signer_name="Cid",
                           signer_email="cid@x.com")
        admit_online_session(world, parking_spaces=2)
        admit_online_session(world, parking_spaces=1, waiver_id=wv_b["id"])

        day = api.get_sales_day(world["day_id"], MANAGER)
        assert validate_success(day)["booked_parking"] == 3, (
            "2 + 1 fills the parking capacity exactly")

        resp = api.create_visit_session(
            create_visit_session_payload(world["window_id"], wv_c["id"],
                                         parking_spaces=1),
            GATE)
        validate_error(resp, "ERR_PARKING_FULL", 422)


class TestWindowCapacityBoundary:
    def _full_window_world(self, api):
        names30 = [f"P{i}" for i in range(1, 31)]
        world = setup_operating_day(waiver_names=names30)
        wv_solo = sign_waiver(world["season_id"], ["Solo"], signer_name="Solo",
                              signer_email="solo@x.com")
        world["waiver_solo_id"] = wv_solo["id"]
        return world

    def test_window_capacity_exact_fill_succeeds(self, api):
        """PRD §3.4: "the window's `booked_slots` plus the arriving
        `party_size` must not exceed `picking_capacity_slots`
        (`ERR_WINDOW_CAPACITY_FULL`), with equality exactly filling the window
        and succeeding"

        Design: Difficulty/boundary_precision_check/window_capacity_exact_fill_then_overflow
        """
        world = self._full_window_world(api)
        session = admit_online_session(world, party_size=30)
        assert session["visit_status"] == "CHECKED_IN"
        assert get_window(world["window_id"])["booked_slots"] == 30, (
            "0 + 30 <= 30 fills the window at exact equality")

    def test_window_capacity_one_over_rejected(self, api):
        """PRD §3.4: "the window's `booked_slots` plus the arriving
        `party_size` must not exceed `picking_capacity_slots`
        (`ERR_WINDOW_CAPACITY_FULL`), with equality exactly filling the window
        and succeeding"

        Design: Difficulty/boundary_precision_check/window_capacity_exact_fill_then_overflow
        """
        world = self._full_window_world(api)
        admit_online_session(world, party_size=30)
        resp = api.create_visit_session(
            create_visit_session_payload(world["window_id"],
                                         world["waiver_solo_id"], party_size=1),
            GATE)
        validate_error(resp, "ERR_WINDOW_CAPACITY_FULL", 422)


class TestStaleWaiverPriority:
    def _stale_and_full_world(self, api):
        """Window filled by a party-30 session, then the waiver text bumped so
        every v1 waiver is stale."""
        names30 = [f"P{i}" for i in range(1, 31)]
        world = setup_operating_day(waiver_names=names30)
        admit_online_session(world, party_size=30)  # fills the window
        wv_solo = sign_waiver(world["season_id"], ["Solo"], signer_name="Solo",
                              signer_email="solo@x.com")
        world["waiver_solo_id"] = wv_solo["id"]
        validate_success(api.config_season(world["season_id"],
                                           {"waiver_text": "WAIVER-V2"}, MANAGER))
        return world

    def test_stale_waiver_beats_full_window(self, api):
        """PRD §2.7: "Every request passes through an ordered validation
        pipeline, and the first failing gate wins — its error is the one
        returned, even if a later gate would also have failed."
        PRD §2.7: "then its `waiver_version_signed` must equal the season's
        `current_waiver_version` (`ERR_WAIVER_STALE`, 422)"
        PRD §3.1: "a waiver is stale whenever its `waiver_version_signed`
        differs from the season's `current_waiver_version`, so bumping the
        waiver text instantly ages every previously signed waiver by comparison
        alone, without touching any waiver record."

        Design: Difficulty/priority_pair_validation_conflict/safety_beats_constraint_on_stale_waiver_full_window
        """
        world = self._stale_and_full_world(api)
        resp = api.create_visit_session(
            create_visit_session_payload(world["window_id"],
                                         world["waiver_solo_id"], party_size=1),
            GATE)
        # Both the stale waiver and the full window fail; the waiver gate wins.
        validate_error(resp, "ERR_WAIVER_STALE", 422)

    def test_current_waiver_on_full_window_surfaces_capacity_error(self, api):
        """PRD §3.4: "the window's `booked_slots` plus the arriving
        `party_size` must not exceed `picking_capacity_slots`
        (`ERR_WINDOW_CAPACITY_FULL`), with equality exactly filling the window
        and succeeding"
        PRD §3.1: "bumping the waiver text instantly ages every previously
        signed waiver by comparison alone, without touching any waiver record."

        Design: Difficulty/priority_pair_validation_conflict/safety_beats_constraint_on_stale_waiver_full_window
        """
        world = self._stale_and_full_world(api)
        # A waiver signed after the bump is version-current: only the capacity
        # leg of the pair can fail now.
        fresh = sign_waiver(world["season_id"], ["Nia"], signer_name="Nia",
                            signer_email="nia@x.com")
        resp = api.create_visit_session(
            create_visit_session_payload(world["window_id"], fresh["id"],
                                         party_size=1),
            GATE)
        validate_error(resp, "ERR_WINDOW_CAPACITY_FULL", 422)
