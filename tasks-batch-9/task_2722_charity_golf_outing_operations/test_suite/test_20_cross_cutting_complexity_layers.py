"""Three repeatable writes and one derived flag, each guarded by its own layer."""

from test_helpers import (
    COURSE_HEADERS,
    DIRECTOR_HEADERS,
    SPONSORSHIP_HEADERS,
    ApiErrorId,
    assert_instant_equals,
    validate_error,
    validate_success,
)
from test_helpers import factories as f
from test_helpers import fixtures as fx

SOLO_TIER = {
    "code": "SOLO",
    "kind": "INDIVIDUAL",
    "price_cents": 30000,
    "player_slots": 1,
    "gsv_cents": 0,
    "inventory_cap": 10,
}
TEE_OUTING = {"name": "Team OCC Open", "field_capacity_teams": 4, "prize_pool_cents": 0}
TEE_CONTRACT = {
    "guaranteed_player_count": 0,
    "tee_interval_minutes": 10,
    "cart_allowance_count": 40,
}
FIRST_TEE_TIME = "2026-09-19T12:00:00Z"
FIRST_SLOT_END = "2026-09-19T12:10:00Z"
SECOND_TEE_TIME = "2026-09-19T12:30:00Z"
SECOND_SLOT_END = "2026-09-19T12:40:00Z"
THIRD_TEE_TIME = "2026-09-19T13:00:00Z"


class TestSupersedingTeeAssignments:
    def _two_single_player_teams(self, api):
        ctx = fx.open_outing(api, outing=TEE_OUTING, contract=TEE_CONTRACT, tier=SOLO_TIER)
        one = fx.confirmed_registration(
            api, ctx, players=(10.0,), names=("OCC Golfer One",), buyer_name="OCC Buyer One"
        )
        two = fx.confirmed_registration(
            api, ctx, players=(12.0,), names=("OCC Golfer Two",), buyer_name="OCC Buyer Two"
        )
        ctx["team_one"] = fx.team_from(api, ctx, one, team_name="OCC Team One")
        ctx["team_two"] = fx.team_from(api, ctx, two, team_name="OCC Team Two")
        return ctx

    def test_a_superseding_assignment_bumps_the_version_and_restamps_the_slot(self, api):
        """Placing a foursome is deliberately rewritable - "it is the one operation in this
        system that is explicitly designed to be repeated", and "Writing a tee assignment
        supersedes whatever pairing the team held before, which is why the request carries
        the mandatory `expected_team_version` guard of §2.7 rather than relying on a state
        precondition."  Each accepted write "sets `slot_occupancy_start` equal to the
        `tee_time` and `slot_occupancy_end` to the `tee_time` advanced by
        `tee_interval_minutes`, which is the exclusive end of the occupancy window;
        increments `tee_assignment_count` by one; and increments the team's `version`, which
        is precisely what supersedes any client still holding the pre-write version."

        Design: Corner/cross_cutting_complexity_layers/a_superseding_tee_assignment_must_prove_it_saw_the_pairing_it_replaces
        """
        ctx = self._two_single_player_teams(api)
        team_id = ctx["team_one"]["id"]
        v0 = ctx["team_one"]["version"]

        first = validate_success(
            api.tee_assignment(
                team_id,
                f.tee_assignment_payload(
                    v0, wave="A", starting_hole=1, tee_time=FIRST_TEE_TIME, cart_number=1
                ),
                DIRECTOR_HEADERS,
            )
        )
        assert first["version"] == v0 + 1
        assert_instant_equals(first["slot_occupancy_start"], FIRST_TEE_TIME)
        assert_instant_equals(first["slot_occupancy_end"], FIRST_SLOT_END)
        assert first["tee_assignment_count"] == 1

        second = validate_success(
            api.tee_assignment(
                team_id,
                f.tee_assignment_payload(
                    first["version"],
                    wave="A",
                    starting_hole=10,
                    tee_time=SECOND_TEE_TIME,
                    cart_number=1,
                ),
                COURSE_HEADERS,
            )
        )
        assert second["version"] == first["version"] + 1
        assert_instant_equals(second["slot_occupancy_start"], SECOND_TEE_TIME)
        assert_instant_equals(second["slot_occupancy_end"], SECOND_SLOT_END)
        assert second["tee_assignment_count"] == 2
        assert second["starting_hole"] == 10
        assert second["cart_number"] == 1

    def test_a_spent_version_may_not_be_replayed_and_the_refusal_bumps_nothing(self, api):
        """The guard is the whole defence: "A tee assignment must carry
        `expected_team_version`, holding the client's last observed `version` of the target
        `Team`. If it does not equal the team's current `version`, the write is rejected with
        `ERR_STALE_TEAM_VERSION` (HTTP 412), so the client cannot replace a pairing it has
        not seen."  A version is therefore spendable exactly once, and a rejected assignment
        leaves the pairing, the counter and the version untouched.

        Design: Corner/cross_cutting_complexity_layers/a_superseding_tee_assignment_must_prove_it_saw_the_pairing_it_replaces
        """
        ctx = self._two_single_player_teams(api)
        team_id = ctx["team_one"]["id"]
        v0 = ctx["team_one"]["version"]

        v1 = fx.assign_tee(
            api,
            team_id,
            starting_hole=1,
            tee_time=FIRST_TEE_TIME,
            cart_number=1,
            headers=DIRECTOR_HEADERS,
            expected_team_version=v0,
        )["version"]

        validate_error(
            api.tee_assignment(
                team_id,
                f.tee_assignment_payload(
                    v0, wave="A", starting_hole=10, tee_time=SECOND_TEE_TIME, cart_number=1
                ),
                DIRECTOR_HEADERS,
            ),
            ApiErrorId.STALE_TEAM_VERSION,
            412,
        )

        held = fx.read_team(api, team_id)
        assert held["starting_hole"] == 1
        assert_instant_equals(held["tee_time"], FIRST_TEE_TIME)
        assert held["tee_assignment_count"] == 1
        assert held["version"] == v1

        v2 = validate_success(
            api.tee_assignment(
                team_id,
                f.tee_assignment_payload(
                    v1, wave="A", starting_hole=10, tee_time=SECOND_TEE_TIME, cart_number=1
                ),
                COURSE_HEADERS,
            )
        )["version"]

        validate_error(
            api.tee_assignment(
                team_id,
                f.tee_assignment_payload(
                    v1, wave="A", starting_hole=15, tee_time=THIRD_TEE_TIME, cart_number=1
                ),
                DIRECTOR_HEADERS,
            ),
            ApiErrorId.STALE_TEAM_VERSION,
            412,
        )

        final = fx.read_team(api, team_id)
        assert final["version"] == v2
        assert final["starting_hole"] == 10
        assert final["cart_number"] == 1
        assert final["tee_assignment_count"] == 2

    def test_staleness_is_reported_ahead_of_the_tee_sheet_conflict(self, api):
        """Two layers can fail at once, and the ladder decides which is reported: the version
        check asks only that "the supplied version guard matches the row's current `version`,
        as described in §2.7", and it sits above the business rules whose temporal sub-tier
        "holds the tee-sheet slot (`ERR_TEE_SLOT_CONFLICT`)".  The exactly-touching placement
        proves the sheet itself is clear, since "The interval is half-open, so a group teeing
        off at exactly the instant the previous group's interval ends is accepted; any
        genuine overlap is refused with `ERR_TEE_SLOT_CONFLICT`."

        Design: Corner/cross_cutting_complexity_layers/a_superseding_tee_assignment_must_prove_it_saw_the_pairing_it_replaces
        """
        ctx = self._two_single_player_teams(api)
        one_id = ctx["team_one"]["id"]
        two_id = ctx["team_two"]["id"]

        v1 = fx.assign_tee(
            api,
            one_id,
            starting_hole=1,
            tee_time=FIRST_TEE_TIME,
            cart_number=1,
            headers=DIRECTOR_HEADERS,
            expected_team_version=ctx["team_one"]["version"],
        )["version"]
        v2 = fx.assign_tee(
            api,
            one_id,
            starting_hole=10,
            tee_time=SECOND_TEE_TIME,
            cart_number=1,
            headers=COURSE_HEADERS,
            expected_team_version=v1,
        )["version"]

        two_v0 = ctx["team_two"]["version"]
        placed_two = validate_success(
            api.tee_assignment(
                two_id,
                f.tee_assignment_payload(
                    two_v0, wave="A", starting_hole=10, tee_time=SECOND_SLOT_END, cart_number=2
                ),
                COURSE_HEADERS,
            )
        )
        assert placed_two["version"] == two_v0 + 1
        assert_instant_equals(placed_two["slot_occupancy_start"], SECOND_SLOT_END)

        validate_error(
            api.tee_assignment(
                one_id,
                f.tee_assignment_payload(
                    v1, wave="A", starting_hole=10, tee_time=SECOND_SLOT_END, cart_number=1
                ),
                DIRECTOR_HEADERS,
            ),
            ApiErrorId.STALE_TEAM_VERSION,
            412,
        )

        assert fx.read_team(api, one_id)["version"] == v2
        two = fx.read_team(api, two_id)
        assert two["version"] == two_v0 + 1
        assert two["starting_hole"] == 10


AMEND_OUTING = {"name": "Amend OCC Open", "field_capacity_teams": 4, "prize_pool_cents": 0}
FLAT_CONTRACT = {"guaranteed_player_count": 0, "fnb_minimum_cents": 0}
TEAM4_TIER = {
    "code": "TEAM4",
    "kind": "TEAM",
    "price_cents": 120000,
    "player_slots": 4,
    "gsv_cents": 0,
    "inventory_cap": 4,
}
DELUXE_TIER = {
    "code": "DELUXE",
    "kind": "TEAM",
    "price_cents": 150000,
    "player_slots": 4,
    "gsv_cents": 0,
    "inventory_cap": 4,
}


class TestRepeatableTierAmendment:
    def _a_paid_solo_registration(self, api):
        ctx = fx.open_outing(api, outing=AMEND_OUTING, contract=FLAT_CONTRACT, tier=SOLO_TIER)
        ctx["team4_id"] = fx.add_tier(api, ctx, **TEAM4_TIER)["id"]
        ctx["deluxe_id"] = fx.add_tier(api, ctx, **DELUXE_TIER)["id"]
        created = fx.new_registration(
            api, ctx["outing_id"], ctx["tier_id"], buyer_name="Amend Buyer", player_count=1
        )
        ctx["registration_id"] = created["id"]
        ctx["created_version"] = created["version"]
        paid = fx.pay_registration(api, created["id"], 30000)
        ctx["paid_version"] = paid["version"]
        assert paid["status"] == "CONFIRMED"
        return ctx

    def test_a_stale_guard_is_refused_ahead_of_the_price_delta(self, api):
        """The amendment is guarded by the registration's version alone: "A tier amendment
        must carry `expected_registration_version`, holding the client's last observed
        `version` of the target `Registration`. A mismatch with the registration's current
        `version` is rejected with `ERR_STALE_REGISTRATION_VERSION` (HTTP 412), so a client
        cannot compute a price delta from a tier the registration no longer holds."  Because
        that check sits above the business rules, a request that is both stale and carries the
        wrong delta reports the staleness, not the mismatch, and a refused amendment leaves
        the tier, the money and the counter exactly where they were.

        Design: Corner/cross_cutting_complexity_layers/a_repeatable_tier_amendment_is_guarded_only_by_the_registration_version
        """
        ctx = self._a_paid_solo_registration(api)

        validate_error(
            api.amend_tier(
                ctx["registration_id"],
                f.amend_tier_payload(
                    ctx["team4_id"], ctx["created_version"], amount_cents=90000, player_count=4
                ),
                SPONSORSHIP_HEADERS,
            ),
            ApiErrorId.STALE_REGISTRATION_VERSION,
            412,
        )

        validate_error(
            api.amend_tier(
                ctx["registration_id"],
                f.amend_tier_payload(ctx["deluxe_id"], ctx["created_version"], amount_cents=1),
                SPONSORSHIP_HEADERS,
            ),
            ApiErrorId.STALE_REGISTRATION_VERSION,
            412,
        )

        held = fx.read_registration(api, ctx["registration_id"])
        assert held["status"] == "CONFIRMED"
        assert held["package_tier_id"] == ctx["tier_id"]
        assert held["amount_paid_cents"] == 30000
        assert held["amendment_count"] == 0
        assert held["version"] == ctx["paid_version"]

    def test_the_self_loop_may_be_walked_twice_and_each_delta_is_added(self, api):
        """The amendment is a legitimate repeat: "It moves a registration `CONFIRMED →
        AMENDED`, and from `AMENDED` it loops back to `AMENDED` so a package can be re-amended
        any number of times while the field is open; the preconditions and side effects of the
        self-loop are identical to those of the first amendment."  Each hop prices itself off
        the tier currently held, since "the supplied `amount_cents` must equal the new tier's
        `price_cents` minus the currently held tier's `price_cents`", and on acceptance "the
        registration's `package_tier_id` becomes the requested tier and `amendment_count`
        increments by one", while "A positive delta is added to `amount_paid_cents`".

        Design: Corner/cross_cutting_complexity_layers/a_repeatable_tier_amendment_is_guarded_only_by_the_registration_version
        """
        ctx = self._a_paid_solo_registration(api)

        first = validate_success(
            api.amend_tier(
                ctx["registration_id"],
                f.amend_tier_payload(
                    ctx["team4_id"], ctx["paid_version"], amount_cents=90000, player_count=4
                ),
                SPONSORSHIP_HEADERS,
            )
        )
        assert first["status"] == "AMENDED"
        assert first["package_tier_id"] == ctx["team4_id"]
        assert first["amount_paid_cents"] == 120000
        assert first["amendment_count"] == 1
        assert first["version"] == ctx["paid_version"] + 1

        validate_error(
            api.amend_tier(
                ctx["registration_id"],
                f.amend_tier_payload(
                    ctx["deluxe_id"], ctx["paid_version"], amount_cents=30000
                ),
                SPONSORSHIP_HEADERS,
            ),
            ApiErrorId.STALE_REGISTRATION_VERSION,
            412,
        )

        second = validate_success(
            api.amend_tier(
                ctx["registration_id"],
                f.amend_tier_payload(ctx["deluxe_id"], first["version"], amount_cents=30000),
                DIRECTOR_HEADERS,
            )
        )
        assert second["status"] == "AMENDED"
        assert second["package_tier_id"] == ctx["deluxe_id"]
        assert second["amount_paid_cents"] == 150000
        assert second["amendment_count"] == 2
        assert second["version"] == first["version"] + 1

        assert fx.read_tier(api, ctx["tier_id"])["sold_count"] == 0
        assert fx.read_tier(api, ctx["team4_id"])["sold_count"] == 0
        assert fx.read_tier(api, ctx["deluxe_id"])["sold_count"] == 1
        assert fx.read_outing(api, ctx["outing_id"])["confirmed_player_slots"] == 4


INSURANCE_OUTING = {
    "name": "Insurance Threshold Open",
    "field_capacity_teams": 4,
    "prize_pool_cents": 0,
}
UNDER_THRESHOLD_CENTS = 499999
AT_THRESHOLD_CENTS = 500000
PREMIUM_CENTS = 40000


class TestTheInsuranceThreshold:
    def _an_open_outing(self, api):
        return fx.open_outing(
            api, outing=INSURANCE_OUTING, contract=FLAT_CONTRACT, tier=SOLO_TIER
        )

    def _a_bound_ace_contest(self, api, ctx):
        contest = fx.new_contest(
            api,
            ctx["outing_id"],
            contest_type="HOLE_IN_ONE",
            hole_number=4,
            prize_value_cents=AT_THRESHOLD_CENTS,
            yardage=170,
        )
        bound = fx.bind_contest_insurance(
            api,
            contest["id"],
            insurance_carrier="Fairway Mutual",
            insurance_premium_cents=PREMIUM_CENTS,
            insurance_coverage_cap_cents=1000000,
            insurance_min_yardage=165,
            insurance_required_witness_count=2,
        )
        return contest, bound

    def test_the_threshold_is_inclusive_and_the_flag_gates_the_opening(self, api):
        """The derived flag is a closed boundary: "`requires_insurance` is true exactly when
        the `contest_type` is `HOLE_IN_ONE` **and** the `prize_value_cents` is at least 500000
        cents".  One cent short and the contest opens freely; on the threshold the opening is
        held, because "it additionally requires that either `requires_insurance` is false or
        the insurance dimension already reads `BOUND`, otherwise `ERR_INSURANCE_NOT_BOUND`.
        That single rule is what stops a five-thousand-dollar ace prize from being advertised
        uninsured."

        Design: Corner/cross_cutting_complexity_layers/the_insurance_threshold_binds_only_at_or_above_five_hundred_thousand_and_only_for_hole_in_one
        """
        ctx = self._an_open_outing(api)

        under = fx.new_contest(
            api,
            ctx["outing_id"],
            contest_type="HOLE_IN_ONE",
            hole_number=3,
            prize_value_cents=UNDER_THRESHOLD_CENTS,
            yardage=165,
        )
        assert under["requires_insurance"] is False
        assert under["insurance_status"] == "NONE"
        assert fx.drive_contest(api, under["id"], "OPEN")["status"] == "OPEN"

        at = fx.new_contest(
            api,
            ctx["outing_id"],
            contest_type="HOLE_IN_ONE",
            hole_number=4,
            prize_value_cents=AT_THRESHOLD_CENTS,
            yardage=170,
        )
        assert at["requires_insurance"] is True
        assert at["insurance_status"] == "NONE"
        validate_error(
            api.contest_status(at["id"], f.contest_status_payload("OPEN"), DIRECTOR_HEADERS),
            ApiErrorId.INSURANCE_NOT_BOUND,
            409,
        )
        assert fx.read_contest(api, at["id"])["status"] == "PLANNED"
        assert fx.read_outing(api, ctx["outing_id"])["insurance_cost_cents"] == 0

        bound = fx.bind_contest_insurance(
            api,
            at["id"],
            insurance_carrier="Fairway Mutual",
            insurance_premium_cents=PREMIUM_CENTS,
            insurance_coverage_cap_cents=1000000,
            insurance_min_yardage=165,
            insurance_required_witness_count=2,
        )
        assert bound["insurance_status"] == "BOUND"
        assert bound["status"] == "PLANNED"
        assert bound["insurance_bound_at"] is not None
        assert bound["version"] == at["version"] + 1
        assert fx.read_outing(api, ctx["outing_id"])["insurance_cost_cents"] == PREMIUM_CENTS

        assert fx.drive_contest(api, at["id"], "OPEN")["status"] == "OPEN"

    def test_only_a_hole_in_one_can_cross_the_threshold(self, api):
        """The flag reads the contest type as well as the money, and is "false in every other
        case, including a five-figure longest-drive prize", so a nine-thousand-dollar closest
        to the pin opens with no policy at all.  Binding the ace policy "adds the premium to
        the outing's `insurance_cost_cents`", and that cost stays exactly the sum over the
        insured contests, since "`insurance_cost_cents` is the sum of `insurance_premium_cents`
        over every contest of the outing whose insurance dimension reads `BOUND`,
        `CLAIM_PAID`, `CLAIM_DENIED`, or `EXPIRED`".

        Design: Corner/cross_cutting_complexity_layers/the_insurance_threshold_binds_only_at_or_above_five_hundred_thousand_and_only_for_hole_in_one
        """
        ctx = self._an_open_outing(api)
        _, bound = self._a_bound_ace_contest(api, ctx)
        assert bound["insurance_status"] == "BOUND"

        pin = fx.new_contest(
            api,
            ctx["outing_id"],
            contest_type="CLOSEST_TO_PIN",
            hole_number=5,
            prize_value_cents=900000,
            yardage=150,
        )
        assert pin["requires_insurance"] is False
        assert pin["insurance_status"] == "NONE"
        assert pin["insurance_premium_cents"] == 0
        assert fx.drive_contest(api, pin["id"], "OPEN")["status"] == "OPEN"

        assert fx.read_outing(api, ctx["outing_id"])["insurance_cost_cents"] == PREMIUM_CENTS
