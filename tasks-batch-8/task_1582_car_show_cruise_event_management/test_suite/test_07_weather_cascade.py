"""Weather cancellation cascade: refunds, ballot voiding, zone release,
and the pinned two-pass pro-rata cap."""
import pytest

from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS,
    create_open_event, create_registrant_with_vehicle, create_registration,
    create_paid_registration, sign_waiver, check_in, create_voter, cast_ballot,
    get_zone, get_summary,
)

ORG = TEST_USERS["organizer_headers"]
DESK = TEST_USERS["desk_headers"]


class TestWeatherCancelCascadeDepth4:
    def _setup(self, api):
        """JUDGING event; R1 and R2 both CHECKED_IN; one VALID ballot on R1.

        R2 must be checked in too: PRD §3.4 flips CONFIRMED entries to NO_SHOW
        at start-judging, and PRD §3.7 only refunds CONFIRMED/CHECKED_IN rows.
        """
        ev, cls, zone = create_open_event(zone_overrides={
            "arrival_window_start": "2026-08-15T08:00:00Z",
            "arrival_window_end": "2026-08-15T10:00:00Z",
        })
        p1, v1 = create_registrant_with_vehicle(name="W1", email="w1@example.com")
        sign_waiver(ev["id"], p1["id"], signature_name="W1")
        r1 = create_paid_registration(ev["id"], p1["id"], v1["id"], cls["id"])
        p2, v2 = create_registrant_with_vehicle(
            name="W2", email="w2@example.com",
            vehicle_overrides={"year": 1971, "make": "Chevrolet", "model": "Chevelle"})
        sign_waiver(ev["id"], p2["id"], signature_name="W2")
        r2 = create_paid_registration(ev["id"], p2["id"], v2["id"], cls["id"], method="CARD")
        get_success_data(api.set_clock({"to_iso8601": "2026-08-15T08:30:00Z"}, ORG))
        r1 = check_in(r1["id"], zone["id"])
        r2 = check_in(r2["id"], zone["id"])
        get_success_data(api.set_clock({"to_iso8601": "2026-08-15T12:30:00Z"}, ORG))
        get_success_data(api.lock_registration(ev["id"], ORG))
        get_success_data(api.start_judging(ev["id"], ORG))
        voter = create_voter("Voter", "voter@example.com")
        ballot = cast_ballot(ev["id"], r1["id"], voter["id"])
        return ev, zone, r1, r2, ballot

    def test_cancel_refunds_both_registrations_and_drains_treasury(self, api):
        """PRD §3.7: "Level one: every registration in `CONFIRMED` or
        `CHECKED_IN` moves to `REFUND_REQUESTED`." PRD §3.7: "Level three: each
        `SUCCEEDED` refund debits `treasury_cents`, accrues into the
        registration's `refunded_cents`, and moves that registration
        `REFUND_REQUESTED` → `REFUNDED`."

        Design: Difficulty/transitive_cascade/weather_cancel_cascade_depth4
        """
        ev, zone, r1, r2, ballot = self._setup(api)
        get_success_data(api.weather_decision(ev["id"], {"posture": "CANCELLED", "reason": "tornado warning"}, ORG))
        r1_after = validate_success(api.get_registration(r1["id"], ORG))
        r2_after = validate_success(api.get_registration(r2["id"], ORG))
        assert r1_after["status"] == "REFUNDED"
        assert r1_after["refunded_cents"] == 3000
        assert r2_after["status"] == "REFUNDED"
        assert r2_after["refunded_cents"] == 3000
        assert get_summary(ev["id"])["treasury_cents"] == 0, "6000 fees - 6000 refunds"

    def test_cancel_voids_ballots_and_releases_zone_spot(self, api):
        """PRD §3.7: "Level four: each registration that lands in `REFUNDED`
        voids its ballots (`VALID` → `VOID`), reverts any award in `COMPUTED` or
        `FINALIZED` it had won back to `PENDING` with the `tie_break_log` cleared,
        and — where the car had been `CHECKED_IN` — releases its spot and
        decrements the zone's `assigned_count`."

        Design: Difficulty/transitive_cascade/weather_cancel_cascade_depth4
        """
        ev, zone, r1, r2, ballot = self._setup(api)
        get_success_data(api.weather_decision(ev["id"], {"posture": "CANCELLED", "reason": "tornado warning"}, ORG))
        ballot_after = validate_success(api.get_ballot(ballot["id"], ORG))
        assert ballot_after["status"] == "VOID"
        assert get_zone(ev["id"], zone["id"])["assigned_count"] == 0


class TestWeatherCancelProRataTwoPass:
    def _setup(self, api):
        """Three paid registrations; POSTPONED goodwill round; N1 withdrawal at
        the 50% tier; treasury snapshot 5625 before the cancellation."""
        ev, cls, zone = create_open_event()
        regs = []
        for i, (yr, make, model) in enumerate([(1968, "Ford", "Bronco"),
                                               (1967, "Chevrolet", "Nova"),
                                               (1966, "Plymouth", "Barracuda")]):
            reg, veh = create_registrant_with_vehicle(
                name=f"N{i}", email=f"n{i}@example.com",
                vehicle_overrides={"year": yr, "make": make, "model": model})
            regs.append(create_paid_registration(ev["id"], reg["id"], veh["id"], cls["id"],
                                                 method="CASH" if i == 0 else "CARD"))
        get_success_data(api.weather_decision(ev["id"], {"posture": "POSTPONED", "reason": "storm front"}, ORG))
        get_success_data(api.weather_decision(ev["id"], {"posture": "NORMAL", "reason": "front passed"}, ORG))
        # N1 withdraws 72h before gates: 50% of net 2250 == 1125.
        get_success_data(api.set_clock({"to_iso8601": "2026-08-12T09:00:00Z"}, ORG))
        get_success_data(api.withdraw_registration(regs[0]["id"], {"reason": "schedule conflict"}, DESK))
        get_success_data(api.refund_decision(regs[0]["id"], {"decision": "APPROVE"}, ORG))
        return ev, regs

    def test_treasury_snapshot_and_goodwill_credits(self, api):
        """PRD §3.7: "Declaring `POSTPONED` issues a goodwill credit without
        disturbing anyone's entry: for every registration in `CONFIRMED` or
        `CHECKED_IN`, the system writes a `REFUND` payment equal to 25% of that
        registration's gross `paid_cents`, rounded half-up to whole cents".

        Design: Difficulty/combinatorial_formula/weather_cancel_pro_rata_two_pass
        """
        ev, regs = self._setup(api)
        assert get_summary(ev["id"])["treasury_cents"] == 5625, (
            "9000 fees - 3*750 goodwill - 1125 withdrawal refund")
        r1_after = validate_success(api.get_registration(regs[0]["id"], ORG))
        assert r1_after["refunded_cents"] == 1875, "750 goodwill + 1125 withdrawal"

    def test_cancel_scales_refunds_with_earliest_created_remainder(self, api):
        """PRD §3.7: "Pass two applies the cap: if the policy refunds total more
        than the snapshot, each registration's base refund becomes its policy
        refund scaled by the snapshot-to-total ratio and rounded down to whole
        cents, and the cents left over by that truncation are distributed one
        cent at a time to registrations in creation order until the snapshot is
        exactly exhausted".

        Design: Difficulty/combinatorial_formula/weather_cancel_pro_rata_two_pass
        """
        ev, regs = self._setup(api)
        get_success_data(api.weather_decision(ev["id"], {"posture": "CANCELLED", "reason": "hurricane watch"}, ORG))
        # Policy refunds are 100% of gross: 3000 each, sum 6000 > snapshot 5625.
        # floor(3000 * 5625 / 6000) == 2812 each; the 1-cent remainder goes to
        # the earlier-created registration.
        r2_payments = validate_success(api.list_registration_payments(regs[1]["id"], ORG))
        r3_payments = validate_success(api.list_registration_payments(regs[2]["id"], ORG))
        r2_amounts = [(p["kind"], p["amount_cents"]) for p in r2_payments]
        r3_amounts = [(p["kind"], p["amount_cents"]) for p in r3_payments]
        assert ("REFUND", 2813) in r2_amounts, "earliest created gets the remainder cent"
        assert ("REFUND", 2812) in r3_amounts
        r2_after = validate_success(api.get_registration(regs[1]["id"], ORG))
        r3_after = validate_success(api.get_registration(regs[2]["id"], ORG))
        assert r2_after["status"] == "REFUNDED"
        assert r3_after["status"] == "REFUNDED"
        assert get_summary(ev["id"])["treasury_cents"] == 0, "snapshot exactly exhausted"
