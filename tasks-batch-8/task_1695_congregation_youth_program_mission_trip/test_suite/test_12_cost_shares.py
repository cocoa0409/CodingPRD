"""Cost shares: the provisional-vs-final variant switch at roster lock, the
round-then-sum remainder waterfall, and lodging-cancel reconciliation."""
from test_helpers import (
    add_cleared_chaperone_to_trip,
    add_lodging,
    create_confirmed_registration,
    create_participant,
    create_program,
    create_registration,
    create_trip,
    get_registration,
    get_trip,
    lock_trip_roster,
    make_director_headers,
    make_leader_headers,
    open_trip_registration,
    set_clock,
    setup_program_with_open_trip,
    validate_success,
)

DIRECTOR = make_director_headers()
LEADER = make_leader_headers()


def _alpha_with_three_confirmed(api, lodging_rooms):
    """Trip Alpha (INTERNATIONAL, capacity 30, base 200000, deposit 50000) with
    the given [(room_code, beds, cost)] reservations, one CONFIRMED cleared LEAD
    chaperone, and three CONFIRMED registrations; registration is closed.

    Returns (program, trip, [registration dicts in creation order]).
    """
    program = create_program(scholarship_fund_total_cents=500000)
    trip = create_trip(program["id"])
    for room_code, beds, cost in lodging_rooms:
        add_lodging(trip["id"], room_code=room_code, room_capacity=beds,
                    cost_cents=cost)
    open_trip_registration(trip["id"])
    add_cleared_chaperone_to_trip(trip["id"], program["id"])
    registrations = []
    for i, (guardian, payment) in enumerate(
            [("guardian-1", 203010), ("guardian-2", 50000),
             ("guardian-3", 50000)]):
        # Stagger the logical clock so created_at strictly orders the roster.
        set_clock(f"2026-08-0{i + 2}T00:00:00Z")
        _, registration, _, _ = create_confirmed_registration(
            trip["id"], guardian_user_id=guardian,
            payment_amount_cents=payment,
            participant_overrides={"family_key": f"fam-{i + 1}"},
            registration_overrides={"insurance_tier": "INTERNATIONAL"})
        registrations.append(registration)
    closed = validate_success(api.close_registration(trip["id"], DIRECTOR), 200)
    return program, closed, registrations


class TestProvisionalVsFinalAtLock:
    def _setup(self, api):
        return _alpha_with_three_confirmed(
            api, [("R1", 8, 30100), ("R2", 8, 30100), ("R3", 8, 30100)])

    def test_provisional_and_final_shares_diverge_on_identical_lodging(self, api):
        """PRD §3.6: "It equals the trip's `base_cost_cents` plus the trip's
        `lodging_cost_total_cents` divided by `capacity_youth`, that division
        rounded half up to the nearest cent. The denominator is the planned
        headcount — `capacity_youth` — even if fewer registrations exist."
        PRD §3.6: "The per-person lodging share is L divided by N, rounded half
        up" — the final share divides by the ACTUAL confirmed headcount.

        Design: Difficulty/dual_variant_calc/cost_share_provisional_vs_final_at_lock
        """
        _, trip, registrations = self._setup(api)
        reg1 = registrations[0]

        # Captured pre-lock in setup: provisional 200000 + round_half_up(90300/30)
        # == 203010 on the planned headcount of 30.
        assert reg1["provisional_cost_share_cents"] == 203010

        locked = lock_trip_roster(trip["id"])
        assert locked["status"] == "ROSTER_LOCKED"
        for registration in registrations:
            after = get_registration(registration["id"])
            assert after["final_cost_share_cents"] == 230100, (
                "200000 + 90300/3 (zero remainder) on the actual headcount")
            assert after["final_cost_share_cents"] - \
                after["provisional_cost_share_cents"] == 27090

    def test_lock_downgrades_provisionally_paid_in_full_registration(self, api):
        """PRD §3.2: "It recomputes each confirmed registration's
        `payment_status` against the final basis: coverage of the final share
        plus late fees means `PAID_IN_FULL`; otherwise coverage of at least the
        deposit means `PARTIALLY_PAID`; otherwise `PENDING_DEPOSIT`. Because the
        final basis can exceed the provisional one, a registration that showed
        `PAID_IN_FULL` on the provisional basis can be **downgraded** by the
        lock."

        Design: Difficulty/dual_variant_calc/cost_share_provisional_vs_final_at_lock
        """
        _, trip, registrations = self._setup(api)
        reg1 = registrations[0]
        # reg1 paid the full provisional share (203010) before the lock.
        pre = get_registration(reg1["id"])
        assert pre["payment_status"] == "PAID_IN_FULL"
        assert pre["covered_cents"] == 203010

        lock_trip_roster(trip["id"])
        post = get_registration(reg1["id"])
        assert post["final_cost_share_cents"] == 230100
        assert post["payment_status"] == "PARTIALLY_PAID", (
            "covered 203010 < final 230100 — downgraded purely by the variant "
            "switch; >= deposit 50000 keeps it PARTIALLY_PAID")


class TestFinalCostShareWaterfall:
    def _setup(self, api):
        return _alpha_with_three_confirmed(api, [("BIG", 30, 100001)])

    def test_round_then_sum_remainder_waterfall(self, api):
        """PRD §3.6: "The per-person lodging share is L divided by N, rounded
        half up; the signed remainder delta is L minus N times that share. The
        `CONFIRMED` registrations are ordered by the registration's `created_at`
        ascending with ties broken by the participant's `created_at` ascending,
        and the system walks that order applying one cent of delta per
        registration — in the sign of delta — until the remainder is exhausted".
        "The pinned order is round-then-sum: summing first and rounding once is
        a rejected alternative."

        Design: Difficulty/combinatorial_formula/final_cost_share_round_then_sum_waterfall
        """
        _, trip, registrations = self._setup(api)
        lock_trip_roster(trip["id"])

        # L = 100001 over N = 3: share = round_half_up(33333.67) = 33334,
        # delta = 100001 - 3*33334 = -1 cent, applied to the earliest-created.
        reg_a, reg_b, reg_c = registrations
        finals = {r["id"]: get_registration(r["id"])["final_cost_share_cents"]
                  for r in registrations}
        assert finals[reg_a["id"]] == 233333, (
            "earliest-created absorbs the -1 cent remainder")
        assert finals[reg_b["id"]] == 233334
        assert finals[reg_c["id"]] == 233334

    def test_waterfall_conserves_the_lodging_total(self, api):
        """PRD §3.6: "Each registration's `final_cost_share_cents` is then
        `base_cost_cents` plus the share plus its adjustment (zero for most)."
        — the lodging components must sum back to the trip's lodging rollup:
        "`lodging_cost_total_cents` — the sum of `cost_cents` over `CONFIRMED`
        reservations" (§3.9).

        Design: Difficulty/combinatorial_formula/final_cost_share_round_then_sum_waterfall
        """
        _, trip, registrations = self._setup(api)
        assert get_trip(trip["id"])["lodging_cost_total_cents"] == 100001
        lock_trip_roster(trip["id"])

        lodging_components = [
            get_registration(r["id"])["final_cost_share_cents"] - 200000
            for r in registrations]
        assert sum(lodging_components) == 100001, (
            "round-then-sum conserves the lodging total exactly "
            "(33333 + 33334 + 33334)")
        assert lodging_components.count(33334) == 2
        assert lodging_components.count(33333) == 1


class TestLodgingCancelReconciliation:
    def test_lodging_cancel_recomputes_rollup_and_provisional_shares(self, api):
        """PRD §3.9: "Cancellation moves the reservation to `CANCELLED`,
        recomputes the lodging rollup, and recomputes pre-lock provisional
        shares and amounts due across the roster." and "A created reservation is
        `CONFIRMED` and immediately feeds the trip's `lodging_cost_total_cents`
        — the sum of `cost_cents` over `CONFIRMED` reservations".

        Design: Corner/state_machines/lodging_cancel_recomputes_rollup_and_provisional_shares
        """
        program, trip = setup_program_with_open_trip(base_cost_cents=80000)
        reservation = add_lodging(trip["id"], room_code="R1", room_capacity=30,
                                  cost_cents=60000)
        participant = create_participant(program["id"], "guardian-1")
        registration = create_registration(trip["id"], participant["id"],
                                           "guardian-1")
        assert registration["provisional_cost_share_cents"] == 82000, (
            "80000 + round_half_up(60000/30) = 2000")
        assert get_trip(trip["id"])["lodging_cost_total_cents"] == 60000

        cancelled = api.cancel_lodging_reservation(reservation["id"], LEADER)
        assert validate_success(cancelled, 200)["status"] == "CANCELLED"

        assert get_trip(trip["id"])["lodging_cost_total_cents"] == 0, (
            "CANCELLED reservations leave the rollup")
        after = get_registration(registration["id"])
        assert after["provisional_cost_share_cents"] == 80000
        assert after["amount_due_cents"] == 80000, (
            "derived fields reconciled on the source mutation")
