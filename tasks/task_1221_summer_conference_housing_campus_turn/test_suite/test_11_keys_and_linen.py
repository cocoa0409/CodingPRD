"""Key credential pool accounting and linen reconciliation."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_instant_equal,
    create_building_turn_active,
    get_assignment_for_participant,
    get_building,
    get_group,
    get_success_data,
    set_clock,
    setup_confirmed_group,
    setup_departed_group,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
HOUSEKEEPING = TEST_USERS["housekeeping_headers"]
FINANCE = TEST_USERS["finance_headers"]


class TestKeyGraceDayBoundary:
    def _two_key_group(self, api):
        building, rooms = create_building_turn_active(name="Noble Hall",
                                                      key_pool_size=10,
                                                      rooms=(("R1", 2),))
        group, participants, _rev, _inv = setup_confirmed_group(
            building, rooms, client_name="Law Review",
            participant_specs=[("A One", "1975-05-05", "ATTENDEE"),
                               ("A Two", "1976-06-06", "ATTENDEE")],
            assignment_room_map=["R1", "R1"],
            arrival_date="2026-06-15", departure_date="2026-06-19",
            checkin_at="2026-06-15T15:00:00Z", checkout_at="2026-06-19T11:00:00Z",
            contracted_bed_count=2, deposit_paid_cents=10000)
        k1 = get_success_data(api.create_key_credential(
            group["id"], participants[0]["id"], "K-001", ADMIN))
        k2 = get_success_data(api.create_key_credential(
            group["id"], participants[1]["id"], "K-002", ADMIN))
        return building, group, k1, k2

    def test_key_grace_day_boundary(self, api):
        """PRD: "a return on the departure date or within the two grace days
        after it incurs no fee — late days are the calendar days between
        departure_date and the return date, minus two, floored at zero. Each late
        day costs 1,500 cents"
        PRD: "So a return exactly two days after departure is free, and one day
        later bills a single late day."

        Design: Difficulty/boundary_precision_check/key_grace_day_boundary
        """
        building, group, k1, k2 = self._two_key_group(api)
        set_clock("2026-06-21T10:00:00Z")  # departure 2026-06-19 + 2 grace days
        returned1 = validate_success(api.return_key_credential(k1["id"], ADMIN))
        assert returned1["status"] == "RETURNED"
        assert returned1["late_fee_cents"] == 0
        set_clock("2026-06-22T10:00:00Z")  # one day past the grace boundary
        returned2 = validate_success(api.return_key_credential(k2["id"], ADMIN))
        assert returned2["late_fee_cents"] == 1500, "one late day at 1500 cents"
        building_after = get_building(building["id"])
        assert building_after["available_key_count"] == 10, \
            "both keys flowed back into the pool"

    def test_key_grace_fee_grows_per_late_day(self, api):
        """PRD: "Each late day costs 1,500 cents, and the fee is capped at 7,500
        cents no matter how late the return."

        Design: Difficulty/boundary_precision_check/key_grace_day_boundary
        """
        building, group, k1, k2 = self._two_key_group(api)
        set_clock("2026-06-24T10:00:00Z")  # 3 late days after the 2 grace days
        returned1 = validate_success(api.return_key_credential(k1["id"], ADMIN))
        assert returned1["late_fee_cents"] == 4500, "3 late days * 1500"
        set_clock("2026-06-30T10:00:00Z")  # 9 late days: would be 13500 uncapped
        returned2 = validate_success(api.return_key_credential(k2["id"], ADMIN))
        assert returned2["late_fee_cents"] == 7500, "the 7500 cap binds"


class TestKeyPoolConservation:
    def _confirmed_three_key_group(self, api):
        building, rooms = create_building_turn_active(name="Todd Hall", key_pool_size=3,
                                                      rooms=(("R1", 3),))
        group, participants, _rev, _inv = setup_confirmed_group(
            building, rooms, client_name="Debate Union",
            participant_specs=[("A One", "1985-01-01", "ATTENDEE"),
                               ("A Two", "1985-01-02", "ATTENDEE"),
                               ("A Three", "1985-01-03", "ATTENDEE")],
            assignment_room_map=["R1", "R1", "R1"],
            arrival_date="2026-06-15", departure_date="2026-06-19",
            checkin_at="2026-06-15T15:00:00Z", checkout_at="2026-06-19T11:00:00Z",
            contracted_bed_count=3, deposit_paid_cents=14000)
        keys = [get_success_data(api.create_key_credential(
            group["id"], p["id"], code, ADMIN))
            for p, code in zip(participants, ("K-A", "K-B", "K-C"))]
        return building, group, keys

    def test_key_issue_return_pool_conservation(self, api):
        """PRD: "available_key_count, tracks the physical key pool: it equals
        key_pool_size minus keys currently outstanding (in ISSUED or ACTIVATED
        status) minus keys reported LOST, and it is initialized to key_pool_size
        at confirm-release."
        PRD: "a lost key is never returned to the pool."

        Design: Difficulty/compensating_invariant/key_issue_return_pool_conservation
        """
        building, group, keys = self._confirmed_three_key_group(api)
        k1, k2, k3 = keys
        b = get_building(building["id"])
        assert b["available_key_count"] == 0, "pool 3 minus 3 outstanding"

        get_success_data(api.return_key_credential(k1["id"], ADMIN))
        get_success_data(api.activate_key_credential(k2["id"], ADMIN))
        get_success_data(api.return_key_credential(k2["id"], ADMIN))
        b = get_building(building["id"])
        assert b["available_key_count"] == 2, \
            "two compensating returns restore the pool (2 available + 1 outstanding)"

        lost = validate_success(api.report_key_lost(k3["id"], ADMIN))
        assert lost["status"] == "LOST"
        assert lost["lost_fee_cents"] == 5000
        b = get_building(building["id"])
        assert b["available_key_count"] == 2, \
            "the lost key does NOT compensate the pool (2 available + 0 outstanding + 1 lost)"

    def test_returned_keys_carry_zero_fee_before_departure(self, api):
        """PRD: "a return on the departure date or within the two grace days
        after it incurs no fee"

        Design: Difficulty/compensating_invariant/key_issue_return_pool_conservation
        """
        building, group, keys = self._confirmed_three_key_group(api)
        k1, _k2, _k3 = keys
        # The logical clock is still at its 2026-05-01 default — well before the
        # group's 2026-06-19 departure date, so no late fee can accrue.
        returned = validate_success(api.return_key_credential(k1["id"], ADMIN))
        assert returned["late_fee_cents"] == 0
        assert_instant_equal(returned["returned_at"], "2026-05-01T00:00:00Z")
        assert get_building(building["id"])["available_key_count"] == 1


class TestKeyPoolExhaustion:
    def test_key_issue_exhausts_pool(self, api):
        """PRD: "issuance requires the building's available_key_count to be at
        least one — an exhausted pool rejects with
        ERR_KEY_INVENTORY_EXHAUSTED — and decrements it."

        Design: Corner/validations/key_issue_exhausts_pool
        """
        building, rooms = create_building_turn_active(name="Xenia Hall", key_pool_size=1,
                                                      rooms=(("R1", 2),))
        group, participants, _rev, _inv = setup_confirmed_group(
            building, rooms, client_name="Key Test",
            participant_specs=[("A One", "1990-01-01", "ATTENDEE"),
                               ("A Two", "1990-01-02", "ATTENDEE")],
            assignment_room_map=["R1", "R1"],
            contracted_bed_count=2, deposit_paid_cents=10000)
        k1 = validate_success(api.create_key_credential(
            group["id"], participants[0]["id"], "K-1", ADMIN), expected_status=201)
        assert get_building(building["id"])["available_key_count"] == 0, \
            "the first issue is allowed at pool 1 and drains it"
        resp = api.create_key_credential(group["id"], participants[1]["id"], "K-2", ADMIN)
        validate_error(resp, ApiErrorId.ERR_KEY_INVENTORY_EXHAUSTED)


class TestKeyTerminalStates:
    def test_error_key_lost_and_damage_terminal_states(self, api):
        """PRD: "Return is accepted from either ISSUED or ACTIVATED and moves the
        credential to its terminal RETURNED state"
        PRD: "Reporting the credential lost — likewise from ISSUED or ACTIVATED —
        terminates it as LOST, charging a lost_fee_cents of 5,000 cents; a lost
        key is never returned to the pool."

        Design: Corner/errors/error_key_lost_and_damage_terminal_states
        """
        building, rooms = create_building_turn_active(name="Papa Hall", key_pool_size=5,
                                                      rooms=(("R1", 1),))
        group, participants, _rev, _inv = setup_confirmed_group(
            building, rooms, client_name="Key States", deposit_paid_cents=5000)
        p1 = participants[0]
        k1 = get_success_data(api.create_key_credential(group["id"], p1["id"], "K-1", ADMIN))
        k2 = get_success_data(api.create_key_credential(group["id"], p1["id"], "K-2", ADMIN))
        get_success_data(api.report_key_lost(k1["id"], ADMIN))
        get_success_data(api.return_key_credential(k2["id"], ADMIN))

        validate_error(api.return_key_credential(k1["id"], ADMIN),
                       ApiErrorId.ERR_INVALID_STATE)
        validate_error(api.activate_key_credential(k2["id"], ADMIN),
                       ApiErrorId.ERR_INVALID_STATE)
        b = get_building(building["id"])
        assert b["available_key_count"] == 4, \
            "pool 5: one key returned (+1 net), the lost key never re-enters the pool"


class TestLinenReconciliation:
    def test_linen_overreturn_rejected(self, api):
        """PRD: "the cumulative sum of returned plus damaged packs after each
        call must not exceed packs_issued, or the call is rejected with
        ERR_LINEN_OVERRETURN."
        PRD: "reaches its terminal RECONCILED state the moment the cumulative
        returned-plus-damaged count equals packs_issued exactly"

        Design: Corner/validations/linen_overreturn_rejected
        """
        building, rooms = create_building_turn_active(name="York Hall", key_pool_size=5,
                                                      rooms=(("R1", 1),))
        group, participants, _rev, _inv = setup_confirmed_group(
            building, rooms, client_name="Linen Over", deposit_paid_cents=5000)
        issue = get_success_data(api.create_linen_issue(group["id"], 2, HOUSEKEEPING))
        resp = api.record_linen_return(issue["id"], 2, 1, HOUSEKEEPING)
        validate_error(resp, ApiErrorId.ERR_LINEN_OVERRETURN)
        reconciled = validate_success(
            api.record_linen_return(issue["id"], 1, 1, HOUSEKEEPING))
        assert reconciled["status"] == "RECONCILED"
        assert reconciled["loss_charge_cents"] == 1600, \
            "0 lost * 3200 + 1 damaged * 1600"

    def test_linen_loss_and_damage_charge_aggregation(self, api):
        """PRD: "Every return recomputes loss_charge_cents: packs still
        unaccounted (issued minus returned minus damaged) are charged at 3,200
        cents each, and damaged packs at 1,600 cents each."
        PRD: "linen_charge_cents as the sum of loss_charge_cents over all of the
        group's linen issues regardless of their status"

        Design: Corner/calculations/linen_loss_and_damage_charge_aggregation
        """
        building, rooms = create_building_turn_active(name="North Hall",
                                                      key_pool_size=5,
                                                      rooms=(("R1", 1),))
        # Full lifecycle to DEPARTED; the linen issue is recorded mid-stay.
        group, participants, _rev, invoice_id = setup_confirmed_group(
            building, rooms, client_name="Linen Test", deposit_paid_cents=5000)
        set_clock("2026-06-15T16:00:00Z")
        assignment_id = get_assignment_for_participant(
            group["id"], participants[0]["id"])["id"]
        get_success_data(api.check_in_assignment(assignment_id, ADMIN))
        issue = get_success_data(api.create_linen_issue(group["id"], 5, HOUSEKEEPING))
        partial = get_success_data(api.record_linen_return(issue["id"], 3, 1, HOUSEKEEPING))
        assert partial["status"] == "PARTIALLY_RETURNED"
        assert partial["loss_charge_cents"] == 4800, "1 lost * 3200 + 1 damaged * 1600"
        set_clock("2026-06-17T10:00:00Z")
        get_success_data(api.check_out_assignment(assignment_id, ADMIN))
        get_success_data(api.close_out_group(group["id"], ADMIN))
        invoice = get_success_data(api.finalize_invoice(invoice_id, FINANCE))
        assert invoice["linen_charge_cents"] == 4800
        assert invoice["total_cents"] == 13800, \
            "2 actual nights * 4500 = 9000 bed-nights plus 4800 linen"
