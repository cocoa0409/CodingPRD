"""Roster lock gate battery: chaperone ratio equality, insurance tier,
emergency protocol, lodging beds, empty roster, and the deposit-lapse fiscal
gate (checked last)."""
from test_helpers import (
    ApiErrorId,
    add_lodging,
    create_confirmed_registration,
    create_program,
    create_trip,
    get_trip,
    make_director_headers,
    make_treasurer_headers,
    open_trip_registration,
    setup_lock_ready_trip,
    validate_error,
    validate_success,
)

DIRECTOR = make_director_headers()


class TestChaperoneRatioBoundary:
    def _setup_delta(self, api, **kwargs):
        """IN_STATE trip, ratio 1, one CONFIRMED registration (deposit paid),
        one 2-bed room, registration closed."""
        overrides = {"chaperone_ratio": 1}
        overrides.update(kwargs)
        return setup_lock_ready_trip(num_confirmed=1, room_capacity=2,
                                     trip_overrides=overrides)

    def test_zero_cleared_chaperones_fails_lock(self, api):
        """PRD §3.2: "`ratio_compliant` must be true (`ERR_CHAPERONE_RATIO_UNMET`,
        HTTP 422 — with zero confirmed youth the requirement is zero and this
        passes vacuously ...)".
        PRD §3.8: "`required_cleared_chaperones` is `confirmed_youth_count`
        divided by the trip's `chaperone_ratio`, rounded up to a whole number".

        Design: Difficulty/boundary_precision_check/chaperone_ratio_exact_equality_passes
        """
        program = create_program()
        trip = create_trip(program["id"], destination_type="IN_STATE",
                           chaperone_ratio=1, start_date="2027-06-15",
                           end_date="2027-06-16", emergency_protocol_text="")
        add_lodging(trip["id"], room_capacity=2, cost_cents=0,
                    check_in_date="2027-06-15", check_out_date="2027-06-16")
        open_trip_registration(trip["id"])
        create_confirmed_registration(trip["id"], guardian_user_id="guardian-1")
        api.close_registration(trip["id"], DIRECTOR)

        # required == ceil(1/1) == 1, cleared == 0 -> fails below the boundary.
        resp = api.lock_roster(trip["id"], DIRECTOR)
        validate_error(resp, ApiErrorId.ERR_CHAPERONE_RATIO_UNMET, 422)
        assert get_trip(trip["id"])["status"] == "REGISTRATION_CLOSED"

    def test_exactly_required_cleared_chaperones_passes(self, api):
        """PRD §3.8: "`ratio_compliant` holds when the cleared count is at least
        the requirement" — the comparison is >=, so exact equality passes.
        PRD §3.2: a successful lock moves the trip to `ROSTER_LOCKED`.

        Design: Difficulty/boundary_precision_check/chaperone_ratio_exact_equality_passes
        """
        bundle = self._setup_delta(api)
        trip = get_trip(bundle["trip"]["id"])
        assert trip["required_cleared_chaperones"] == 1
        assert trip["cleared_chaperone_count"] == 1
        assert trip["ratio_compliant"] is True, (
            "cleared == required == 1: equality passes (>=, not >)")

        locked = api.lock_roster(trip["id"], DIRECTOR)
        assert validate_success(locked, 200)["status"] == "ROSTER_LOCKED"


class TestLockInsuranceGate:
    def test_lock_roster_insurance_tier_gate(self, api):
        """PRD §3.2: "every `CONFIRMED` registration must carry an
        `insurance_tier` at or above the trip's `required_insurance_tier` on the
        ordering `NONE` below `DOMESTIC` below `INTERNATIONAL`
        (`ERR_INSURANCE_TIER_INSUFFICIENT`, HTTP 422)".
        PRD §3.2: "The destination type determines the `required_insurance_tier`
        stamped on the trip: ... `DOMESTIC` for out-of-state".

        Design: Corner/validations/lock_roster_insurance_tier_gate
        """
        bundle = setup_lock_ready_trip(
            num_confirmed=1,
            trip_overrides={"destination_type": "OUT_OF_STATE",
                            "emergency_protocol_text": "Protocol v1"},
            insurance_tier="NONE")  # one rank below the required DOMESTIC
        trip = bundle["trip"]
        assert trip["required_insurance_tier"] == "DOMESTIC"

        resp = api.lock_roster(trip["id"], DIRECTOR)
        validate_error(resp, ApiErrorId.ERR_INSURANCE_TIER_INSUFFICIENT, 422)
        assert get_trip(trip["id"])["status"] == "REGISTRATION_CLOSED"


class TestLockEmergencyProtocolGate:
    def test_lock_roster_emergency_protocol_gate(self, api):
        """PRD §3.2: "`emergency_protocol_text` documents the emergency protocol;
        it defaults to empty and may stay empty for an in-state trip, but a trip
        whose `destination_type` is not `IN_STATE` cannot lock its roster until
        the text is non-empty" — the lock raises `ERR_EMERGENCY_PROTOCOL_MISSING`
        (HTTP 422).

        Design: Corner/validations/lock_roster_emergency_protocol_gate
        """
        bundle = setup_lock_ready_trip(
            num_confirmed=1,
            trip_overrides={"destination_type": "OUT_OF_STATE",
                            "emergency_protocol_text": ""},
            insurance_tier="DOMESTIC")
        trip = bundle["trip"]

        resp = api.lock_roster(trip["id"], DIRECTOR)
        validate_error(resp, ApiErrorId.ERR_EMERGENCY_PROTOCOL_MISSING, 422)

        # Supply the protocol via the version-guarded edit, then the lock passes.
        current = get_trip(trip["id"])
        patched = api.patch_trip(
            trip["id"],
            {"emergency_protocol_text": "Evac + embassy contacts v1",
             "expected_trip_version": current["version"]},
            DIRECTOR)
        validate_success(patched, 200)

        locked = api.lock_roster(trip["id"], DIRECTOR)
        assert validate_success(locked, 200)["status"] == "ROSTER_LOCKED", (
            "the protocol gate was the sole blocker")


class TestLockLodgingBedGate:
    def test_lock_roster_lodging_bed_capacity_gate(self, api):
        """PRD §3.2: "the total `room_capacity` over `CONFIRMED` lodging
        reservations must be at least `confirmed_youth_count` plus
        `cleared_chaperone_count` (`ERR_LODGING_CAPACITY_INSUFFICIENT`,
        HTTP 422)" — beds 1 < youth 1 + cleared chaperones 1.

        Design: Corner/validations/lock_roster_lodging_bed_capacity_gate
        """
        bundle = setup_lock_ready_trip(num_confirmed=1, room_capacity=1)
        resp = api.lock_roster(bundle["trip"]["id"], DIRECTOR)
        validate_error(resp, ApiErrorId.ERR_LODGING_CAPACITY_INSUFFICIENT, 422)


class TestLockEmptyRoster:
    def test_lock_roster_empty_roster_zero_count_edge(self, api):
        """PRD §3.2: "`confirmed_youth_count` must be at least 1
        (`ERR_EMPTY_ROSTER`, HTTP 422)" — and "with zero confirmed youth the
        requirement is zero and this passes vacuously, though the next gate
        stops an empty roster": on an empty roster the ratio check passes
        vacuously (0 >= 0) and the roster gate is what fires.

        Design: Corner/validations/lock_roster_empty_roster_zero_count_edge
        """
        bundle = setup_lock_ready_trip(num_confirmed=0, with_chaperone=False,
                                       with_lodging=False)
        trip = get_trip(bundle["trip"]["id"])
        assert trip["confirmed_youth_count"] == 0
        assert trip["required_cleared_chaperones"] == 0
        assert trip["ratio_compliant"] is True, "0 >= 0: vacuous pass"

        resp = api.lock_roster(trip["id"], DIRECTOR)
        validate_error(resp, ApiErrorId.ERR_EMPTY_ROSTER, 422)


class TestLockDepositLapsed:
    def test_lock_roster_deposit_lapsed_fiscal_gate(self, api):
        """PRD §3.2: "checked last among the lock gates, every `CONFIRMED`
        registration must still have `covered_cents` at least `deposit_cents` —
        a registration whose deposit lapsed through a refund blocks the lock
        with `ERR_UNPAID_BALANCES_REMAIN` (HTTP 402)."

        Design: Corner/validations/lock_roster_deposit_lapsed_fiscal_gate
        """
        bundle = setup_lock_ready_trip(num_confirmed=1)
        trip = bundle["trip"]
        payment = bundle["bundles"][0]["payment"]
        registration = bundle["bundles"][0]["registration"]
        assert registration["registration_status"] == "CONFIRMED"

        # The deposit lapses: the only payment is refunded after confirmation.
        refunded = api.refund_payment(payment["id"], make_treasurer_headers())
        validate_success(refunded, 200)
        assert get_trip(trip["id"])["status"] == "REGISTRATION_CLOSED"

        resp = api.lock_roster(trip["id"], DIRECTOR)
        validate_error(resp, ApiErrorId.ERR_UNPAID_BALANCES_REMAIN, 402)
        reg_after = api.get_registration(registration["id"], DIRECTOR) \
            .json()["data"]
        assert reg_after["registration_status"] == "CONFIRMED"
        assert reg_after["covered_cents"] == 0
