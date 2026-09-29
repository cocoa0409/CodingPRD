"""Member earning across stacking modes, and the elite qualification waterfall.

Every scenario builds its own programme, campaigns and members from the public
endpoints, because the harness restarts the service against an empty database
before each individual test.  The logical clock reads 2026-08-01T00:00:00Z at
startup and is repositioned explicitly wherever a campaign window demands it.
"""
from test_helpers import (
    PROGRAM_ADMIN,
    REVENUE_ACCOUNTANT,
    assert_member_account,
    assert_mile_transaction,
    assert_promotion_campaign,
    close_qualification_cycle,
    create_campaign,
    create_member,
    create_program,
    get_success_data,
    grant_status_match,
    mile_transaction_payload,
    open_case,
    post_transaction,
    read_member,
    read_program,
    run_epoch,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

# --------------------------------------------------------------------------- #
# Campaign window boundaries used by the stacking-mode matrix
# --------------------------------------------------------------------------- #
WINDOW_AUG = "2026-08-01T00:00:00Z"
WINDOW_SEP = "2026-09-01T00:00:00Z"
WINDOW_OCT = "2026-10-01T00:00:00Z"
WINDOW_NOV = "2026-11-01T00:00:00Z"


def _stacking_matrix_setup():
    """One PLATINUM member and three FLIGHT campaigns differing only in mode.

    The three windows are adjacent and non-overlapping, so exactly one campaign
    is `LIVE` at each of the three instants the earning chain posts at.
    """
    program = create_program(name="SkyMiles Earn Lab", current_period="2026-08")
    exclusive = create_campaign(
        program["id"], code="EXC2X", earn_channel="FLIGHT", multiplier_bps=20000,
        stacking_mode="EXCLUSIVE", window_start=WINDOW_AUG, window_end=WINDOW_SEP,
    )
    additive = create_campaign(
        program["id"], code="ADD2X", earn_channel="FLIGHT", multiplier_bps=20000,
        stacking_mode="ADDITIVE", window_start=WINDOW_SEP, window_end=WINDOW_OCT,
    )
    multiplicative = create_campaign(
        program["id"], code="MUL2X", earn_channel="FLIGHT", multiplier_bps=20000,
        stacking_mode="MULTIPLICATIVE", window_start=WINDOW_OCT,
        window_end=WINDOW_NOV,
    )
    member = create_member(
        program["id"], external_member_ref="MBR-PLAT", home_region="EMEA"
    )
    grant_status_match(member["id"], "PLATINUM", 180)
    run_epoch(program["id"])
    return program, member, exclusive, additive, multiplicative


def _earn_8000(member_id, activity_date, promotion_id):
    return post_transaction(
        member_id, "FLIGHT_EARN", activity_date, headers=REVENUE_ACCOUNTANT,
        base_miles=8000, segments=2, promotion_id=promotion_id,
    )


def _advance_and_sweep(program_id, instant):
    set_clock(instant)
    run_epoch(program_id)


class TestEarnStackingModeMatrix:
    """The tier bonus x promotional multiplier matrix, cell by cell."""

    def test_exclusive_mode_suppresses_the_platinum_tier_bonus_to_zero(self):
        """PRD §3.4: "**Second**, the elite tier bonus is computed: the tier bonus rate is 0 basis points at `BASE`, 2500 at `SILVER`, 5000 at `GOLD` and 10000 at `PLATINUM`, so a platinum member's bonus doubles their base, and `tier_bonus_miles` is the base multiplied by that rate divided by 10000, rounded half up."
        PRD §3.4: "**Third**, the promotional multiplier is resolved: when no `promotion_id` is supplied, `promo_multiplier_bps` is 10000 (a neutral one-times factor) and `stacking_mode_applied` is null; when one is supplied, `promo_multiplier_bps` takes the campaign's `multiplier_bps` and `stacking_mode_applied` takes the campaign's `stacking_mode`."
        PRD §3.4: "Under `EXCLUSIVE`, the gross total is the base multiplied by the promotional multiplier divided by 10000 and rounded half up, and `tier_bonus_miles` is forced to zero — the promotion replaces the elite bonus rather than adding to it."
        PRD §3.4: "The raw bonus is the gross total minus the base minus `tier_bonus_miles`, floored at zero."
        PRD §3.4: "**Sixth**, `total_miles` is the base plus `tier_bonus_miles` plus `bonus_miles`."

        Design: Difficulty/combinatorial_formula/earn_stacking_mode_matrix_across_tier_and_promo_multiplier
        """
        _program, member, exclusive, _additive, _multiplicative = (
            _stacking_matrix_setup()
        )

        txn = _earn_8000(member["id"], "2026-08-01", exclusive["id"])
        assert_mile_transaction(txn)

        assert txn["elite_tier_at_earn"] == "PLATINUM", (
            "the PLATINUM status match must be snapshotted onto the earning row, "
            f"got {txn['elite_tier_at_earn']}"
        )
        assert txn["stacking_mode_applied"] == "EXCLUSIVE", (
            "stacking_mode_applied takes the campaign's stacking_mode, got "
            f"{txn['stacking_mode_applied']}"
        )
        assert txn["promo_multiplier_bps"] == 20000, (
            "promo_multiplier_bps takes the campaign's multiplier_bps, got "
            f"{txn['promo_multiplier_bps']}"
        )
        assert txn["tier_bonus_miles"] == 0, (
            "EXCLUSIVE forces tier_bonus_miles to zero even for a PLATINUM "
            f"member, got {txn['tier_bonus_miles']}"
        )
        assert txn["bonus_miles"] == 8000, (
            "the raw bonus is the 16000 gross total minus the 8000 base minus a "
            f"zero tier bonus, got {txn['bonus_miles']}"
        )
        assert txn["total_miles"] == 16000, (
            "8000 base plus 0 tier bonus plus 8000 promotional bonus is 16000, "
            f"got {txn['total_miles']}"
        )

    def test_additive_and_multiplicative_diverge_on_identical_inputs(self):
        """PRD §3.4: "Under `ADDITIVE`, the tier rate and the promotional lift are treated as independent percentage adders: the gross total is the base multiplied by the quantity (10000 plus the tier rate plus the amount by which the promotional multiplier exceeds 10000), divided by 10000, rounded half up."
        PRD §3.4: "Under `MULTIPLICATIVE`, the promotion multiplies an already tier-boosted subtotal, and the rounding happens twice: first the base multiplied by the quantity (10000 plus the tier rate), divided by 10000, rounded half up to whole miles; then that rounded subtotal multiplied by the promotional multiplier, divided by 10000, rounded half up again."
        PRD §3.4: "The double rounding is deliberate, and it means `MULTIPLICATIVE` can diverge from `ADDITIVE` by more than the pure arithmetic difference between the two formulas."
        PRD §3.4: "The stamped `bonus_miles` is the smallest of the raw bonus, the campaign's remaining room, and a per-transaction ceiling of 25000 miles per member."

        Design: Difficulty/combinatorial_formula/earn_stacking_mode_matrix_across_tier_and_promo_multiplier
        """
        program, member, exclusive, additive, multiplicative = (
            _stacking_matrix_setup()
        )

        exclusive_txn = _earn_8000(member["id"], "2026-08-01", exclusive["id"])

        _advance_and_sweep(program["id"], WINDOW_SEP)
        additive_txn = _earn_8000(member["id"], "2026-09-01", additive["id"])

        _advance_and_sweep(program["id"], WINDOW_OCT)
        multiplicative_txn = _earn_8000(
            member["id"], "2026-10-01", multiplicative["id"]
        )

        assert additive_txn["stacking_mode_applied"] == "ADDITIVE", (
            f"expected ADDITIVE, got {additive_txn['stacking_mode_applied']}"
        )
        assert additive_txn["tier_bonus_miles"] == 8000, (
            "the PLATINUM 10000 bps rate on an 8000 base is an 8000 tier bonus, "
            f"got {additive_txn['tier_bonus_miles']}"
        )
        assert additive_txn["bonus_miles"] == 8000, (
            "the ADDITIVE gross of 24000 leaves an 8000 promotional bonus, got "
            f"{additive_txn['bonus_miles']}"
        )
        assert additive_txn["total_miles"] == 24000, (
            "8000 x (10000 + 10000 + 10000) / 10000 is 24000, got "
            f"{additive_txn['total_miles']}"
        )

        assert multiplicative_txn["stacking_mode_applied"] == "MULTIPLICATIVE", (
            f"expected MULTIPLICATIVE, got "
            f"{multiplicative_txn['stacking_mode_applied']}"
        )
        assert multiplicative_txn["tier_bonus_miles"] == 8000, (
            "MULTIPLICATIVE keeps the 8000 tier bonus, got "
            f"{multiplicative_txn['tier_bonus_miles']}"
        )
        assert multiplicative_txn["bonus_miles"] == 16000, (
            "the 32000 gross less the 8000 base less the 8000 tier bonus is a "
            f"16000 promotional bonus, got {multiplicative_txn['bonus_miles']}"
        )
        assert multiplicative_txn["total_miles"] == 32000, (
            "the tier-boosted 16000 subtotal doubled by the promotion is 32000, "
            f"got {multiplicative_txn['total_miles']}"
        )

        assert exclusive_txn["total_miles"] != additive_txn["total_miles"], (
            "EXCLUSIVE and ADDITIVE must not collapse onto the same total_miles: "
            f"{exclusive_txn['total_miles']} vs {additive_txn['total_miles']}"
        )
        assert additive_txn["total_miles"] != multiplicative_txn["total_miles"], (
            "ADDITIVE and MULTIPLICATIVE must not collapse onto the same "
            f"total_miles: {additive_txn['total_miles']} vs "
            f"{multiplicative_txn['total_miles']}"
        )

    def test_three_stacked_earns_aggregate_onto_member_and_campaign_lifecycle(
        self, api
    ):
        """PRD §3.4: "**Seventh**, elite-qualifying credit is computed entirely independently of every multiplier above: a `FLIGHT_EARN` row credits `qualifying_miles_credited` equal to its base and adds the supplied `segments` to the member's `qualifying_segments_ytd`; a `CARD_SPEND_EARN` row credits the lesser of its base and a per-transaction cap of 15000 qualifying miles, and adds the supplied `qualifying_spend_cents` to the member's `qualifying_spend_cents_ytd`; a `PARTNER_EARN` row credits zero qualifying miles."
        PRD §3.4: "In all three cases `qualifying_miles_credited` is added to the member's `qualifying_miles_ytd`."
        PRD §3.4: "The insert then adds `total_miles` to the member's `mile_balance` and `lifetime_miles`, adds `total_miles` to the programme's `outstanding_miles`, and adds `bonus_miles` to the campaign's `accrued_bonus_miles`."
        PRD §3.4: "It is the epoch sweep, not the create call, that moves it `SCHEDULED → LIVE` once `window_start` is at or before the clock's now, and `LIVE → ENDED` once `window_end` is at or before now; only a `LIVE` campaign may be referenced as the `promotion_id` on an earning row."

        Design: Difficulty/combinatorial_formula/earn_stacking_mode_matrix_across_tier_and_promo_multiplier
        """
        program, member, exclusive, additive, multiplicative = (
            _stacking_matrix_setup()
        )

        exclusive_txn = _earn_8000(member["id"], "2026-08-01", exclusive["id"])
        _advance_and_sweep(program["id"], WINDOW_SEP)
        _earn_8000(member["id"], "2026-09-01", additive["id"])
        _advance_and_sweep(program["id"], WINDOW_OCT)
        _earn_8000(member["id"], "2026-10-01", multiplicative["id"])

        assert exclusive_txn["qualifying_miles_credited"] == 8000, (
            "a FLIGHT_EARN row credits qualifying miles equal to its base, "
            f"untouched by any multiplier, got "
            f"{exclusive_txn['qualifying_miles_credited']}"
        )

        member_row = read_member(member["id"])
        assert_member_account(member_row)
        assert member_row["mile_balance"] == 72000, (
            "16000 plus 24000 plus 32000 of credited total_miles is a 72000 "
            f"balance, got {member_row['mile_balance']}"
        )
        assert member_row["qualifying_miles_ytd"] == 24000, (
            "three FLIGHT_EARN rows each credit their 8000 base as qualifying "
            f"miles, got {member_row['qualifying_miles_ytd']}"
        )
        assert member_row["qualifying_segments_ytd"] == 6, (
            "three rows of 2 segments each accumulate 6 qualifying segments, got "
            f"{member_row['qualifying_segments_ytd']}"
        )

        program_row = read_program(program["id"])
        assert program_row["outstanding_miles"] == 72000, (
            "the programme's outstanding mile liability is the sum of the three "
            f"credited totals, got {program_row['outstanding_miles']}"
        )

        exclusive_row = get_success_data(
            api.get_promotion_campaign(exclusive["id"], PROGRAM_ADMIN)
        )
        multiplicative_row = get_success_data(
            api.get_promotion_campaign(multiplicative["id"], PROGRAM_ADMIN)
        )
        assert_promotion_campaign(exclusive_row)
        assert_promotion_campaign(multiplicative_row)
        assert exclusive_row["status"] == "ENDED", (
            "the August campaign's window_end of 2026-09-01 has passed, so the "
            f"sweep must have ended it, got {exclusive_row['status']}"
        )
        assert multiplicative_row["status"] == "LIVE", (
            "the October campaign's window_start has arrived, so the sweep must "
            f"have launched it, got {multiplicative_row['status']}"
        )


# --------------------------------------------------------------------------- #
# Elite qualification at the exact mileage threshold
# --------------------------------------------------------------------------- #
def _qualification_setup():
    """Two members one qualifying mile apart: 75000 versus 74999.

    Both accumulate the same 900000 cents of card spend and the same four
    segments, so only the miles arm can separate them.
    """
    program = create_program(
        name="SkyMiles Qualification", current_period="2026-08"
    )
    exact = create_member(
        program["id"], external_member_ref="MBR-EXACT", home_region="AMER",
        rollover_carried_in=0,
    )
    one_short = create_member(
        program["id"], external_member_ref="MBR-ONESHORT", home_region="AMER",
        rollover_carried_in=0,
    )
    post_transaction(
        exact["id"], "FLIGHT_EARN", "2026-07-10", headers=REVENUE_ACCOUNTANT,
        base_miles=66000, segments=4,
    )
    post_transaction(
        exact["id"], "CARD_SPEND_EARN", "2026-07-11", headers=REVENUE_ACCOUNTANT,
        qualifying_spend_cents=900000,
    )
    post_transaction(
        one_short["id"], "FLIGHT_EARN", "2026-07-10", headers=REVENUE_ACCOUNTANT,
        base_miles=65999, segments=4,
    )
    post_transaction(
        one_short["id"], "CARD_SPEND_EARN", "2026-07-11",
        headers=REVENUE_ACCOUNTANT, qualifying_spend_cents=900000,
    )
    return program, exact, one_short


class TestEliteTierAtExactQualifyingMilesThreshold:
    """75000 effective miles earns GOLD; 74999 earns SILVER and banks 40000."""

    def test_exactly_75000_effective_miles_earns_gold_and_banks_no_rollover(self):
        """PRD §3.6: "A `ProgramAdmin` closes a member's cycle while `qualification_state` is `ACCUMULATING` (or `RESTATED`, as below), moving it to `CLOSED` and running the tier waterfall."
        PRD §3.6: "Effective miles are the member's `qualifying_miles_ytd` plus `rollover_carried_in`."
        PRD §3.6: "The miles arm holds when effective miles are at least the tier's mileage threshold."
        PRD §3.6: "The thresholds are 25000 miles, or 30 segments together with 300000 cents of spend, for `SILVER`; 75000 miles, or 75 segments with 900000 cents, for `GOLD`; and 150000 miles, or 120 segments with 1500000 cents, for `PLATINUM`."
        PRD §3.6: "A member sitting exactly on a threshold earns that tier, the thresholds being inclusive."
        PRD §3.6: "Consumption is the mileage threshold of `awarded_tier_at_close`, or zero when the awarded tier is `BASE`."
        PRD §3.6: "`rollover_carried_out` is the effective miles minus that consumption, floored at zero, and then capped at 40000 miles."
        PRD §3.6: "Closing the cycle also sets `elite_tier` to `awarded_tier_at_close` — unless `status_match_state` is `TRIAL` or `CONFIRMED` and `status_match_tier` outranks the awarded tier, in which case `elite_tier` is retained at `status_match_tier`."

        Design: Difficulty/boundary_precision_check/elite_tier_awarded_at_exact_qualifying_miles_threshold
        """
        _program, exact, _one_short = _qualification_setup()

        closed = close_qualification_cycle(exact["id"])
        assert_member_account(closed)

        assert closed["qualifying_miles_ytd"] == 75000, (
            "66000 flight base miles plus 9000 card-spend base miles is 75000 "
            f"qualifying miles, got {closed['qualifying_miles_ytd']}"
        )
        assert closed["qualification_state"] == "CLOSED", (
            "closing the cycle moves qualification_state to CLOSED, got "
            f"{closed['qualification_state']}"
        )
        assert closed["awarded_tier_at_close"] == "GOLD", (
            "75000 effective miles sits exactly on GOLD's inclusive 75000 "
            f"threshold, got {closed['awarded_tier_at_close']}"
        )
        assert closed["elite_tier"] == "GOLD", (
            "with no status match held, elite_tier follows awarded_tier_at_close,"
            f" got {closed['elite_tier']}"
        )
        assert closed["rollover_carried_out"] == 0, (
            "GOLD consumes its full 75000 threshold, leaving nothing to bank, "
            f"got {closed['rollover_carried_out']}"
        )
        assert closed["qualifying_segments_ytd"] == 4, (
            "the single flight row contributed 4 qualifying segments, got "
            f"{closed['qualifying_segments_ytd']}"
        )
        assert closed["mile_balance"] == 75000, (
            "a BASE member earning 66000 plus 9000 miles with no promotion holds "
            f"75000 spendable miles, got {closed['mile_balance']}"
        )

    def test_one_mile_short_of_gold_earns_silver_and_banks_the_40000_cap(self):
        """PRD §3.6: "Tiers are evaluated strictly highest first — `PLATINUM`, then `GOLD`, then `SILVER`, then `BASE` — and evaluation stops at the first tier earned; `BASE` is the fallthrough and is always earned."
        PRD §3.6: "The segment arm is a conjunction and holds only when `qualifying_segments_ytd` is at least the tier's segment threshold **and** `qualifying_spend_cents_ytd` is at least the tier's spend threshold — segments alone never earn a tier."
        PRD §3.6: "`rollover_carried_out` is the effective miles minus that consumption, floored at zero, and then capped at 40000 miles."
        PRD §3.6: "A member one mile short of `GOLD` is awarded `SILVER` and rolls the entire surplus above 25000 forward, up to the 40000 cap — so a near miss can bank more rollover than a clean qualification."

        Design: Difficulty/boundary_precision_check/elite_tier_awarded_at_exact_qualifying_miles_threshold
        """
        _program, _exact, one_short = _qualification_setup()

        closed = close_qualification_cycle(one_short["id"])
        assert_member_account(closed)

        assert closed["qualifying_miles_ytd"] == 74999, (
            "65999 flight base miles plus 9000 card-spend base miles is 74999 "
            f"qualifying miles, got {closed['qualifying_miles_ytd']}"
        )
        assert closed["awarded_tier_at_close"] == "SILVER", (
            "74999 misses GOLD's 75000 miles arm and only 4 segments misses its "
            f"75-segment arm, so SILVER is awarded, got "
            f"{closed['awarded_tier_at_close']}"
        )
        assert closed["elite_tier"] == "SILVER", (
            f"elite_tier follows the awarded tier, got {closed['elite_tier']}"
        )
        assert closed["rollover_carried_out"] == 40000, (
            "the 49999 surplus over SILVER's 25000 threshold is clipped to the "
            f"40000 cap, got {closed['rollover_carried_out']}"
        )
        assert closed["qualification_state"] == "CLOSED", (
            f"expected CLOSED, got {closed['qualification_state']}"
        )
        assert closed["qualifying_segments_ytd"] == 4, (
            f"expected 4 qualifying segments, got "
            f"{closed['qualifying_segments_ytd']}"
        )
        assert closed["mile_balance"] == 74999, (
            "the balance mirrors the 65999 plus 9000 miles credited, got "
            f"{closed['mile_balance']}"
        )


# --------------------------------------------------------------------------- #
# The promotional bonus cap at exact exhaustion
# --------------------------------------------------------------------------- #
def _promo_cap_setup():
    """A LIVE ADDITIVE campaign capped at 5000 bonus miles, plus two members."""
    program = create_program(name="SkyMiles Promo Cap", current_period="2026-08")
    campaign = create_campaign(
        program["id"], code="AUG-FLIGHT-2X", earn_channel="FLIGHT",
        multiplier_bps=20000, stacking_mode="ADDITIVE",
        window_start="2026-08-01T00:00:00Z", window_end="2026-12-01T00:00:00Z",
        bonus_cap_miles=5000,
    )
    gold = create_member(
        program["id"], external_member_ref="MBR-GOLD", home_region="EMEA"
    )
    base = create_member(
        program["id"], external_member_ref="MBR-BASE", home_region="EMEA"
    )
    grant_status_match(gold["id"], "GOLD", 90)
    run_epoch(program["id"])
    return program, campaign, gold, base


class TestPromoBonusAtExactCapExhaustion:
    """The cap boundary: the first earn fills it exactly, the second gets zero."""

    def test_first_earn_clips_the_bonus_to_drive_accrued_exactly_onto_the_cap(
        self, api
    ):
        """PRD §3.4: "The campaign's remaining room is its `bonus_cap_miles` minus its `accrued_bonus_miles`, floored at zero, and is treated as unbounded when `bonus_cap_miles` is null."
        PRD §3.4: "The stamped `bonus_miles` is the smallest of the raw bonus, the campaign's remaining room, and a per-transaction ceiling of 25000 miles per member."
        PRD §3.4: "**Sixth**, `total_miles` is the base plus `tier_bonus_miles` plus `bonus_miles`."
        PRD §3.4: "A campaign with less room than the raw bonus clips the bonus to exactly the room remaining, driving `accrued_bonus_miles` to precisely `bonus_cap_miles`."

        Design: Difficulty/boundary_precision_check/promo_bonus_zero_when_campaign_cap_exactly_exhausted
        """
        _program, campaign, gold, _base = _promo_cap_setup()

        first = post_transaction(
            gold["id"], "FLIGHT_EARN", "2026-08-01", headers=REVENUE_ACCOUNTANT,
            base_miles=5000, segments=2, promotion_id=campaign["id"],
        )
        assert_mile_transaction(first)

        assert first["elite_tier_at_earn"] == "GOLD", (
            "the GOLD status match must be snapshotted onto the row, got "
            f"{first['elite_tier_at_earn']}"
        )
        assert first["tier_bonus_miles"] == 2500, (
            "GOLD's 5000 bps rate on a 5000 base is a 2500 tier bonus, got "
            f"{first['tier_bonus_miles']}"
        )
        assert first["bonus_miles"] == 5000, (
            "the 5000 raw bonus equals the campaign's full 5000 room, got "
            f"{first['bonus_miles']}"
        )
        assert first["total_miles"] == 12500, (
            "5000 base plus 2500 tier bonus plus 5000 promotional bonus is "
            f"12500, got {first['total_miles']}"
        )

        campaign_row = get_success_data(
            api.get_promotion_campaign(campaign["id"], PROGRAM_ADMIN)
        )
        assert_promotion_campaign(campaign_row)
        assert campaign_row["accrued_bonus_miles"] == 5000, (
            "the first earn drives accrued_bonus_miles exactly onto the 5000 "
            f"cap, got {campaign_row['accrued_bonus_miles']}"
        )

    def test_second_earn_on_an_exhausted_cap_is_created_with_zero_bonus(self, api):
        """PRD §3.4: "A campaign whose room is already exhausted — `accrued_bonus_miles` equal to `bonus_cap_miles` — yields a `bonus_miles` of zero and the transaction is still created successfully; an earn is never rejected for a spent campaign."
        PRD §3.4: "The insert then adds `total_miles` to the member's `mile_balance` and `lifetime_miles`, adds `total_miles` to the programme's `outstanding_miles`, and adds `bonus_miles` to the campaign's `accrued_bonus_miles`."
        PRD §3.4: "**Second**, the elite tier bonus is computed: the tier bonus rate is 0 basis points at `BASE`, 2500 at `SILVER`, 5000 at `GOLD` and 10000 at `PLATINUM`, so a platinum member's bonus doubles their base, and `tier_bonus_miles` is the base multiplied by that rate divided by 10000, rounded half up."

        Design: Difficulty/boundary_precision_check/promo_bonus_zero_when_campaign_cap_exactly_exhausted
        """
        program, campaign, gold, base = _promo_cap_setup()

        post_transaction(
            gold["id"], "FLIGHT_EARN", "2026-08-01", headers=REVENUE_ACCOUNTANT,
            base_miles=5000, segments=2, promotion_id=campaign["id"],
        )

        response = api.create_mile_transaction(
            mile_transaction_payload(
                base["id"], "FLIGHT_EARN", "2026-08-01", base_miles=5000,
                segments=2, promotion_id=campaign["id"],
            ),
            REVENUE_ACCOUNTANT,
        )
        second = validate_success(response, 201)
        assert_mile_transaction(second)

        assert second["elite_tier_at_earn"] == "BASE", (
            f"expected a BASE earner, got {second['elite_tier_at_earn']}"
        )
        assert second["tier_bonus_miles"] == 0, (
            "BASE carries a 0 bps tier bonus rate, got "
            f"{second['tier_bonus_miles']}"
        )
        assert second["bonus_miles"] == 0, (
            "the campaign's room is already spent, so bonus_miles is zero, got "
            f"{second['bonus_miles']}"
        )
        assert second["total_miles"] == 5000, (
            "5000 base plus 0 tier bonus plus 0 promotional bonus is 5000, got "
            f"{second['total_miles']}"
        )

        campaign_row = get_success_data(
            api.get_promotion_campaign(campaign["id"], PROGRAM_ADMIN)
        )
        assert campaign_row["accrued_bonus_miles"] == 5000, (
            "a zero-bonus earn leaves accrued_bonus_miles pinned at the 5000 "
            f"cap, got {campaign_row['accrued_bonus_miles']}"
        )
        assert campaign_row["status"] == "LIVE", (
            "the campaign stays LIVE through cap exhaustion, got "
            f"{campaign_row['status']}"
        )

        assert read_member(gold["id"])["mile_balance"] == 12500, (
            "the capped earner keeps its full 12500 credit"
        )
        assert read_member(base["id"])["mile_balance"] == 5000, (
            "the zero-bonus earner is credited only its 5000 base"
        )
        assert read_program(program["id"])["outstanding_miles"] == 17500, (
            "12500 plus 5000 of credited total_miles is 17500 outstanding miles"
        )


# --------------------------------------------------------------------------- #
# Rung 12 beats rung 31 on a single request
# --------------------------------------------------------------------------- #
def _frozen_member_setup():
    """A FROZEN member holding 1000 miles, frozen by a score-100 fraud case."""
    program = create_program(name="SkyMiles Priority", current_period="2026-08")
    member = create_member(
        program["id"], external_member_ref="MBR-ATO", home_region="APAC"
    )
    post_transaction(
        member["id"], "CARD_SPEND_EARN", "2026-07-20",
        headers=REVENUE_ACCOUNTANT, qualifying_spend_cents=100000,
    )
    case = open_case(
        member["id"], "ACCOUNT_TAKEOVER", login_geo_velocity=10,
        redemption_velocity_24h=5, brokering_pattern_hits=4, dormancy_days=400,
    )
    return program, member, case


class TestFrozenMemberBeatsInsufficientMiles:
    """A REDEEM that violates both rung 12 and rung 31 reports rung 12."""

    def test_redeem_beyond_balance_on_a_frozen_member_reports_member_frozen(
        self, api
    ):
        """PRD §2.9: "Checks are evaluated in ascending order, and **the first check that fails is the response** — no later check runs, and no partial mutation is retained."
        PRD §2.9: "This ordering is normative: when two conditions on a request are both violated, the reported `error_id` is the one belonging to the lower-numbered rung."
        PRD §2.9: "The member's `security_state` is `NORMAL` — otherwise `ERR_MEMBER_FROZEN` (409)."
        PRD §2.9: "The member's `mile_balance` is at least the miles being debited — `quoted_miles` when ticketing, the supplied `base_miles` magnitude on a `REDEEM`, `EXPIRY` or `ADJUSTMENT` ledger row — otherwise `ERR_INSUFFICIENT_MILES` (402)."
        PRD §3.7: "`detection_score` is then the weighted blend of those four — 3500 basis points on geo velocity, 3000 on redemption velocity, 2500 on brokering pattern and 1000 on dormancy, meaning 35%, 30%, 25% and 10% — with the weighted sum divided by 10000, rounded half up, and capped at 100."
        PRD §3.7: "A `detection_score` of 70 or more drives `security_state` to `FROZEN` and sets the case's `freeze_applied` true."

        Design: Difficulty/priority_pair_validation_conflict/frozen_member_state_beats_insufficient_miles_fiscal
        """
        _program, member, case = _frozen_member_setup()

        assert case["detection_score"] == 100, (
            "all four sub-scores clamp at 100 before weighting, so the blend is "
            f"100, got {case['detection_score']}"
        )
        member_before = read_member(member["id"])
        assert member_before["security_state"] == "FROZEN", (
            "a detection_score of 100 drives the member to FROZEN, got "
            f"{member_before['security_state']}"
        )
        assert member_before["mile_balance"] == 1000, (
            "100000 cents of card spend is a 1000-mile balance, well short of "
            f"the 5000 about to be redeemed, got {member_before['mile_balance']}"
        )

        response = api.create_mile_transaction(
            mile_transaction_payload(
                member["id"], "REDEEM", "2026-08-01", base_miles=5000
            ),
            REVENUE_ACCOUNTANT,
        )

        error_data = validate_error(response, "ERR_MEMBER_FROZEN", 409)
        assert error_data["error_id"] != "ERR_INSUFFICIENT_MILES", (
            "the rung-31 fiscal check must never win over the rung-12 security "
            f"check, got {error_data['error_id']}"
        )
        assert response.status_code != 402, (
            "ERR_INSUFFICIENT_MILES' 402 must not surface here, got "
            f"{response.status_code}"
        )

    def test_the_rejected_redeem_leaves_the_ledger_and_balances_untouched(
        self, api
    ):
        """PRD §2.9: "Checks are evaluated in ascending order, and **the first check that fails is the response** — no later check runs, and no partial mutation is retained."
        PRD §2.9: "The member's `security_state` is `NORMAL` — otherwise `ERR_MEMBER_FROZEN` (409)."
        PRD §3.4: "The insert then adds `total_miles` to the member's `mile_balance` and `lifetime_miles`, adds `total_miles` to the programme's `outstanding_miles`, and adds `bonus_miles` to the campaign's `accrued_bonus_miles`."

        Design: Difficulty/priority_pair_validation_conflict/frozen_member_state_beats_insufficient_miles_fiscal
        """
        program, member, _case = _frozen_member_setup()

        response = api.create_mile_transaction(
            mile_transaction_payload(
                member["id"], "REDEEM", "2026-08-01", base_miles=5000
            ),
            REVENUE_ACCOUNTANT,
        )
        validate_error(response, "ERR_MEMBER_FROZEN", 409)

        member_row = read_member(member["id"])
        assert member_row["mile_balance"] == 1000, (
            "a rejected REDEEM retains no partial mutation, so the balance "
            f"stays at 1000, got {member_row['mile_balance']}"
        )
        assert member_row["security_state"] == "FROZEN", (
            f"the member stays FROZEN, got {member_row['security_state']}"
        )

        rows, meta = validate_paginated(
            api.list_mile_transactions(
                PROGRAM_ADMIN, params={"member_id": member["id"]}
            )
        )
        assert meta["total_count"] == 1, (
            "only the original card-spend earn is on the ledger; the refused "
            f"REDEEM inserted nothing, got total_count {meta['total_count']}"
        )
        assert rows[0]["txn_type"] == "CARD_SPEND_EARN", (
            f"the single surviving row is the earn, got {rows[0]['txn_type']}"
        )

        assert read_program(program["id"])["outstanding_miles"] == 1000, (
            "the programme's outstanding mile liability is unmoved by the "
            "refused posting"
        )
