"""Breakage variants, the accounting-period lock, and the fraud clawback cascade.

Each scenario drives the real endpoints from an empty database, because the
harness restarts the service before every individual test.  The logical clock
reads 2026-08-01T00:00:00Z at startup, which is what fixes the 90-day clawback
lookback and the 24-month trailing breakage window used below.
"""
from test_helpers import (
    FRAUD_ANALYST_2,
    PROGRAM_ADMIN,
    REVENUE_ACCOUNTANT,
    SECOND_FRAUD_ANALYST_USER_ID,
    active_agreement,
    assert_award_booking,
    assert_award_inventory_window,
    assert_deferred_revenue_posting,
    assert_fraud_case,
    assert_loyalty_program,
    assert_member_account,
    assert_mile_transaction,
    create_issuer,
    create_member,
    create_posting,
    create_program,
    create_window,
    get_success_data,
    hold_seats,
    investigate_case,
    issued_order,
    mile_transaction_payload,
    open_case,
    post_transaction,
    read_member,
    read_program,
    read_window,
    substantiate_case,
    tier_schedule,
    transition_recognition,
    validate_error,
    validate_paginated,
    validate_success,
)


# --------------------------------------------------------------------------- #
# Historical attrition versus forward expectation on one identical bucket set
# --------------------------------------------------------------------------- #
def _breakage_setup():
    """One programme carrying 800000 cents of deferred revenue and three rows.

    The ledger holds a 2400000-mile card-spend earn, an 1800000-mile redemption
    and a 200000-mile expiry, all dated 2026-07-15 so that all three sit inside
    the trailing window of both periods posted below.
    """
    program = create_program(
        name="SkyMiles Ledger", current_period="2026-08",
        breakage_policy_mode="HISTORICAL_ATTRITION",
    )
    issuer = create_issuer(
        program["id"], name="Northbank Card Services",
        annual_mile_purchase_cap_miles=5000000,
    )
    agreement = active_agreement(
        issuer["id"], committed_volume_miles=1000000,
        tier_schedule=tier_schedule((0, 160)),
    )
    issued_order(agreement["id"], 500000, agreement["version"])

    member = create_member(
        program["id"], external_member_ref="MBR-0001", home_region="AMER"
    )
    post_transaction(
        member["id"], "CARD_SPEND_EARN", "2026-07-15",
        headers=REVENUE_ACCOUNTANT, qualifying_spend_cents=240000000,
    )
    post_transaction(
        member["id"], "REDEEM", "2026-07-15", headers=REVENUE_ACCOUNTANT,
        base_miles=1800000,
    )
    post_transaction(
        member["id"], "EXPIRY", "2026-07-15", headers=REVENUE_ACCOUNTANT,
        base_miles=200000,
    )
    return program, member


def _post_august_historical(program_id):
    closing = transition_recognition(program_id, "CLOSING")
    return create_posting(program_id, "2026-08", closing["version"])


def _cycle_into_september(program_id):
    transition_recognition(program_id, "LOCKED")
    transition_recognition(program_id, "OPEN")
    return transition_recognition(program_id, "CLOSING")


class TestBreakageHistoricalVersusForward:
    """Identical trailing buckets, two variants, two different rates."""

    def test_historical_attrition_divides_expiries_by_miles_that_left(self):
        """PRD §3.9: "When `method` is omitted it defaults to the programme's `breakage_policy_mode`, and the variant actually used is echoed on the row as `method_applied`."
        PRD §3.9: "Three trailing buckets are measured first, over the mile ledger rows belonging to members of the programme whose `activity_date` falls inside the **trailing window**: the 24 calendar months ending on the last day of `period`, inclusive at both ends."
        PRD §3.9: "`expired_miles_trailing` is the absolute miles expired in that window, computed as the sum of the negated `total_miles` of rows whose `txn_type` is `EXPIRY`."
        PRD §3.9: "`redeemed_miles_trailing` is likewise the sum of the negated `total_miles` of rows whose `txn_type` is `REDEEM`."
        PRD §3.9: "`issued_miles_trailing` is the sum of `total_miles` over rows whose `txn_type` is `FLIGHT_EARN`, `CARD_SPEND_EARN` or `PARTNER_EARN`."
        PRD §3.9: "The **historical attrition** variant looks backward and asks what share of the miles that left the programme left by expiring rather than by being redeemed: its denominator is `expired_miles_trailing` plus `redeemed_miles_trailing`, and the raw rate is `expired_miles_trailing` multiplied by 10000 and divided by that denominator, rounded half up to whole basis points — or exactly zero when the denominator is zero, in which case the posting is still created with a `breakage_income_cents` of zero."
        PRD §3.9: "`breakage_income_cents` is `deferred_balance_before_cents` multiplied by `breakage_rate_bps`, divided by 10000, rounded half up to whole cents — so a `deferred_balance_before_cents` of zero yields zero income regardless of the rate."
        PRD §3.9: "`deferred_balance_after_cents` is `deferred_balance_before_cents` minus `breakage_income_cents`."

        Design: Difficulty/dual_variant_calc/program_breakage_historical_vs_forward_divergence
        """
        program, _member = _breakage_setup()

        posting = _post_august_historical(program["id"])
        assert_deferred_revenue_posting(posting)

        assert posting["method_applied"] == "HISTORICAL_ATTRITION", (
            "with no method supplied the programme's own breakage_policy_mode is "
            f"echoed, got {posting['method_applied']}"
        )
        assert posting["expired_miles_trailing"] == 200000, (
            "the single EXPIRY row contributes 200000 absolute expired miles, "
            f"got {posting['expired_miles_trailing']}"
        )
        assert posting["redeemed_miles_trailing"] == 1800000, (
            "the single REDEEM row contributes 1800000 redeemed miles, got "
            f"{posting['redeemed_miles_trailing']}"
        )
        assert posting["issued_miles_trailing"] == 2400000, (
            "240000000 cents of card spend is 2400000 issued miles, got "
            f"{posting['issued_miles_trailing']}"
        )
        assert posting["breakage_rate_bps"] == 1000, (
            "200000 x 10000 / (200000 + 1800000) is 1000 basis points, got "
            f"{posting['breakage_rate_bps']}"
        )
        assert posting["deferred_balance_before_cents"] == 800000, (
            "the 500000-mile order at 160 centicents credited 800000 cents of "
            f"deferred revenue, got {posting['deferred_balance_before_cents']}"
        )
        assert posting["breakage_income_cents"] == 80000, (
            "800000 cents at 1000 basis points is 80000 cents of income, got "
            f"{posting['breakage_income_cents']}"
        )
        assert posting["deferred_balance_after_cents"] == 720000, (
            "800000 minus 80000 is a 720000-cent closing balance, got "
            f"{posting['deferred_balance_after_cents']}"
        )

    def test_forward_expectation_divides_unredeemed_miles_by_miles_issued(self):
        """PRD §3.9: "The rate itself is produced by whichever of two variants applies, and on identical data the two generally disagree."
        PRD §3.9: "The **forward expectation** variant looks forward and asks what share of the miles issued is expected never to be redeemed: its raw rate is 10000 multiplied by the quantity (`issued_miles_trailing` minus `redeemed_miles_trailing`), divided by `issued_miles_trailing`, rounded half up — or the ceiling of 3500 basis points outright when `issued_miles_trailing` is zero, which is a defined answer rather than a division error."
        PRD §3.9: "The forward variant ignores expiries entirely and carries a non-zero floor, which is precisely why the two variants diverge."
        PRD §3.9: "`outstanding_miles_snapshot` captures the programme's `outstanding_miles` at posting time and `deferred_balance_before_cents` captures its `deferred_revenue_cents` at the same instant."
        PRD §3.9: "`breakage_income_cents` is `deferred_balance_before_cents` multiplied by `breakage_rate_bps`, divided by 10000, rounded half up to whole cents — so a `deferred_balance_before_cents` of zero yields zero income regardless of the rate."
        PRD §3.9: "`deferred_balance_after_cents` is `deferred_balance_before_cents` minus `breakage_income_cents`."

        Design: Difficulty/dual_variant_calc/program_breakage_historical_vs_forward_divergence
        """
        program, _member = _breakage_setup()

        august = _post_august_historical(program["id"])
        closing_again = _cycle_into_september(program["id"])
        september = create_posting(
            program["id"], "2026-09", closing_again["version"],
            method="FORWARD_EXPECTATION",
        )
        assert_deferred_revenue_posting(september)

        assert september["method_applied"] == "FORWARD_EXPECTATION", (
            "an explicit method overrides the programme default, got "
            f"{september['method_applied']}"
        )
        assert september["breakage_rate_bps"] == 2500, (
            "10000 x (2400000 - 1800000) / 2400000 is 2500 basis points, got "
            f"{september['breakage_rate_bps']}"
        )
        assert september["deferred_balance_before_cents"] == 720000, (
            "the opening balance is the 720000 cents the August posting left, "
            f"got {september['deferred_balance_before_cents']}"
        )
        assert september["breakage_income_cents"] == 180000, (
            "720000 cents at 2500 basis points is 180000 cents of income, got "
            f"{september['breakage_income_cents']}"
        )
        assert september["deferred_balance_after_cents"] == 540000, (
            "720000 minus 180000 is a 540000-cent closing balance, got "
            f"{september['deferred_balance_after_cents']}"
        )
        assert september["breakage_rate_bps"] != august["breakage_rate_bps"], (
            "the two variants must diverge on the identical trailing buckets: "
            f"{september['breakage_rate_bps']} vs {august['breakage_rate_bps']}"
        )

    def test_both_postings_write_back_onto_the_programme_and_advance_the_period(
        self,
    ):
        """PRD §3.9: "The posting then writes back to the programme: `deferred_revenue_cents` becomes `deferred_balance_after_cents`, `last_breakage_rate_bps` becomes this posting's `breakage_rate_bps`, `lifetime_breakage_income_cents` increases by this posting's `breakage_income_cents`, and the programme's `version` increments by one."
        PRD §3.9: "From `CLOSING` it may move to `LOCKED` — but only once a deferred revenue posting already exists for this programme and its `current_period`, so a period cannot be locked without being posted."
        PRD §3.9: "From `LOCKED` it returns to `OPEN`, and that transition alone advances `current_period` by exactly one calendar month."

        Design: Difficulty/dual_variant_calc/program_breakage_historical_vs_forward_divergence
        """
        program, _member = _breakage_setup()

        _post_august_historical(program["id"])
        after_august = read_program(program["id"])
        assert after_august["deferred_revenue_cents"] == 720000, (
            "the August posting leaves 720000 cents of deferred revenue, got "
            f"{after_august['deferred_revenue_cents']}"
        )
        assert after_august["last_breakage_rate_bps"] == 1000, (
            "last_breakage_rate_bps echoes the newest posting's rate, got "
            f"{after_august['last_breakage_rate_bps']}"
        )

        closing_again = _cycle_into_september(program["id"])
        assert closing_again["current_period"] == "2026-09", (
            "the LOCKED to OPEN transition advances current_period by one "
            f"calendar month, got {closing_again['current_period']}"
        )

        create_posting(
            program["id"], "2026-09", closing_again["version"],
            method="FORWARD_EXPECTATION",
        )

        final = read_program(program["id"])
        assert_loyalty_program(final)
        assert final["deferred_revenue_cents"] == 540000, (
            "the September posting leaves 540000 cents of deferred revenue, got "
            f"{final['deferred_revenue_cents']}"
        )
        assert final["last_breakage_rate_bps"] == 2500, (
            "the newest posting's 2500 bps rate wins, got "
            f"{final['last_breakage_rate_bps']}"
        )
        assert final["lifetime_breakage_income_cents"] == 260000, (
            "80000 plus 180000 of recognised income is 260000 cents lifetime, "
            f"got {final['lifetime_breakage_income_cents']}"
        )
        assert final["current_period"] == "2026-09", (
            f"current_period stays at 2026-09, got {final['current_period']}"
        )


# --------------------------------------------------------------------------- #
# A mile posting refused because its grandparent programme is LOCKED
# --------------------------------------------------------------------------- #
def _locked_program_setup():
    """A member holding 1000 miles under a programme driven all the way to LOCKED."""
    program = create_program(name="SkyMiles Locked", current_period="2026-08")
    member = create_member(
        program["id"], external_member_ref="MBR-LOCKED", home_region="AMER"
    )
    post_transaction(
        member["id"], "CARD_SPEND_EARN", "2026-07-05",
        headers=REVENUE_ACCOUNTANT, qualifying_spend_cents=100000,
    )
    closing = transition_recognition(program["id"], "CLOSING")
    posting = create_posting(program["id"], "2026-08", closing["version"])
    transition_recognition(program["id"], "LOCKED")
    return program, member, posting


def _partner_earn_payload(member_id):
    return mile_transaction_payload(
        member_id, "PARTNER_EARN", "2026-08-01", base_miles=500
    )


class TestMilePostingBlockedByLockedProgramme:
    """The posting is well formed; only the programme's posture refuses it."""

    def test_partner_earn_is_refused_with_period_locked_and_mutates_nothing(
        self, api
    ):
        """PRD §2.7: "In `LOCKED` the period's books are shut: every ledger-moving operation is refused with `ERR_PERIOD_LOCKED` (409)."
        PRD §2.7: "Precisely six operations are ledger-moving for this purpose — posting a mile ledger row, invoicing a mile purchase order, ticketing an award booking, refunding an award booking, creating a deferred revenue posting, and substantiating a fraud case."
        PRD §2.9: "Checks are evaluated in ascending order, and **the first check that fails is the response** — no later check runs, and no partial mutation is retained."
        PRD §2.9: "The programme's `revenue_recognition_state` is not `LOCKED` — otherwise `ERR_PERIOD_LOCKED` (409)."

        Design: Difficulty/cross_entity_state_dependency/mile_transaction_blocked_when_program_recognition_state_locked
        """
        program, member, _posting = _locked_program_setup()

        program_row = read_program(program["id"])
        assert program_row["revenue_recognition_state"] == "LOCKED", (
            "the programme must be sitting in LOCKED before the trigger, got "
            f"{program_row['revenue_recognition_state']}"
        )

        member_row = read_member(member["id"])
        assert_member_account(member_row)
        assert member_row["security_state"] == "NORMAL", (
            "the member is unremarkable — only the programme's posture is at "
            f"issue, got {member_row['security_state']}"
        )

        response = api.create_mile_transaction(
            _partner_earn_payload(member["id"]), REVENUE_ACCOUNTANT
        )
        validate_error(response, "ERR_PERIOD_LOCKED", 409)

        after = read_member(member["id"])
        assert after["mile_balance"] == 1000, (
            "the refused posting retained no partial mutation, so the balance "
            f"stays at 1000, got {after['mile_balance']}"
        )
        assert read_program(program["id"])["outstanding_miles"] == 1000, (
            "the programme's outstanding mile liability is unmoved by the "
            "refused posting"
        )

        _rows, meta = validate_paginated(
            api.list_mile_transactions(
                PROGRAM_ADMIN, params={"member_id": member["id"]}
            )
        )
        assert meta["total_count"] == 1, (
            "only the original card-spend earn is on the ledger, got "
            f"total_count {meta['total_count']}"
        )

    def test_the_same_posting_succeeds_once_the_programme_returns_to_open(
        self, api
    ):
        """PRD §2.7: "In `OPEN` the ledger accepts mile postings freely but breakage may not be recognised."
        PRD §2.9: "The programme's `revenue_recognition_state` is not `LOCKED` — otherwise `ERR_PERIOD_LOCKED` (409)."
        PRD §3.9: "The **historical attrition** variant looks backward and asks what share of the miles that left the programme left by expiring rather than by being redeemed: its denominator is `expired_miles_trailing` plus `redeemed_miles_trailing`, and the raw rate is `expired_miles_trailing` multiplied by 10000 and divided by that denominator, rounded half up to whole basis points — or exactly zero when the denominator is zero, in which case the posting is still created with a `breakage_income_cents` of zero."
        PRD §3.9: "From `LOCKED` it returns to `OPEN`, and that transition alone advances `current_period` by exactly one calendar month."

        Design: Difficulty/cross_entity_state_dependency/mile_transaction_blocked_when_program_recognition_state_locked
        """
        program, member, posting = _locked_program_setup()

        assert posting["breakage_rate_bps"] == 0, (
            "with neither expiries nor redemptions the denominator is zero, so "
            f"the rate is exactly zero, got {posting['breakage_rate_bps']}"
        )
        assert posting["breakage_income_cents"] == 0, (
            "a zero rate on a zero deferred balance recognises no income, got "
            f"{posting['breakage_income_cents']}"
        )

        blocked = api.create_mile_transaction(
            _partner_earn_payload(member["id"]), REVENUE_ACCOUNTANT
        )
        validate_error(blocked, "ERR_PERIOD_LOCKED", 409)

        transition_recognition(program["id"], "OPEN")

        allowed = api.create_mile_transaction(
            _partner_earn_payload(member["id"]), REVENUE_ACCOUNTANT
        )
        created = validate_success(allowed, 201)
        assert_mile_transaction(created)
        assert created["total_miles"] == 500, (
            "a PARTNER_EARN row takes its base_miles verbatim, got "
            f"{created['total_miles']}"
        )

        after = read_member(member["id"])
        assert after["mile_balance"] == 1500, (
            "1000 plus the newly accepted 500 miles is a 1500 balance, got "
            f"{after['mile_balance']}"
        )


# --------------------------------------------------------------------------- #
# The five-hop substantiation cascade
# --------------------------------------------------------------------------- #
def _cascade_setup():
    """A MILE_BROKERING case in INVESTIGATING over a member with held seats.

    The member's 60000 miles were earned on 2026-07-01, inside the 90 days
    before the clock's 2026-08-01 calendar date, so the whole balance is in the
    clawback basis.  Eight of the window's ten seats are held.
    """
    program = create_program(name="SkyMiles Cascade", current_period="2026-08")
    member = create_member(
        program["id"], external_member_ref="MBR-BROKER", home_region="AMER"
    )
    post_transaction(
        member["id"], "CARD_SPEND_EARN", "2026-07-01",
        headers=REVENUE_ACCOUNTANT, qualifying_spend_cents=5000000,
    )
    post_transaction(
        member["id"], "PARTNER_EARN", "2026-07-01", headers=REVENUE_ACCOUNTANT,
        base_miles=10000,
    )
    window = create_window(
        program["id"], route_code="JFK-LHR", cabin="BUSINESS",
        window_start_date="2026-09-01", window_end_date="2026-09-30",
        authorized_seats=10,
    )
    booking = hold_seats(
        member["id"], window["id"], window["version"],
        travel_date="2026-09-15", seats=8, fare_class="FLEX",
    )
    case = open_case(
        member["id"], "MILE_BROKERING", login_geo_velocity=1,
        redemption_velocity_24h=1, brokering_pattern_hits=1, dormancy_days=40,
    )
    investigate_case(case["id"])
    return program, member, window, booking, case


class TestFraudSubstantiationFiveHopCascade:
    """One substantiate call propagates through five different entities."""

    def test_hops_one_and_two_claw_back_the_basis_and_freeze_the_member(
        self, api
    ):
        """PRD §3.7: "`detection_score` is then the weighted blend of those four — 3500 basis points on geo velocity, 3000 on redemption velocity, 2500 on brokering pattern and 1000 on dormancy, meaning 35%, 30%, 25% and 10% — with the weighted sum divided by 10000, rounded half up, and capped at 100."
        PRD §3.7: "In every case, including the last, the member's `risk_score` is set to the new `detection_score`; `risk_score` is by definition the `detection_score` of the member's most recent case, ordered by `created_at` ascending so the newest wins."
        PRD §3.7: "**Substantiation** moves `INVESTIGATING → SUBSTANTIATED`, is refused while the programme is `LOCKED`, and is the deepest cascade in the system — five hops, each caused by the one before it."
        PRD §3.7: "The first hop stamps `adjudicated_by_user_id` and computes `clawback_miles`."
        PRD §3.7: "The clawback basis is the sum of `total_miles` over the member's ledger rows whose `txn_type` is `FLIGHT_EARN`, `CARD_SPEND_EARN` or `PARTNER_EARN` and whose `activity_date` falls within the 90 days before the logical clock's calendar date, inclusive."
        PRD §3.7: "From that basis, a `MILE_BROKERING` case claws back the lesser of the member's current `mile_balance` and the full basis; a `VELOCITY_ANOMALY` case claws back the lesser of the member's `mile_balance` and half the basis rounded down; and an `ACCOUNT_TAKEOVER` case claws back nothing at all, because those miles were stolen *from* the member rather than earned by them, and the balance is preserved for reissue."
        PRD §3.7: "The second hop, caused by the first, applies the outcome: when `clawback_miles` is greater than zero a mile ledger row of `txn_type` `ADJUSTMENT` with `total_miles` equal to the negative of `clawback_miles` is inserted and the member's `mile_balance` is debited accordingly, and the member's `security_state` moves to `CLOSED` for an `ACCOUNT_TAKEOVER` case and to `FROZEN` for either other case type."

        Design: Difficulty/transitive_cascade/fraud_substantiation_five_hop_cascade
        """
        _program, member, _window, _booking, case = _cascade_setup()

        assert case["detection_score"] == 17, (
            "sub-scores 10, 20, 25 and 10 weighted at 3500, 3000, 2500 and 1000 "
            f"basis points round half up to 17, got {case['detection_score']}"
        )

        before = read_member(member["id"])
        assert before["mile_balance"] == 60000, (
            "50000 card-spend miles plus 10000 partner miles is a 60000 balance, "
            f"got {before['mile_balance']}"
        )
        assert before["security_state"] == "NORMAL", (
            "a score of 17 sits below the WATCH threshold, so the member is "
            f"still NORMAL before substantiation, got {before['security_state']}"
        )

        substantiated = substantiate_case(case["id"], FRAUD_ANALYST_2)
        assert_fraud_case(substantiated)

        assert substantiated["status"] == "SUBSTANTIATED", (
            f"expected SUBSTANTIATED, got {substantiated['status']}"
        )
        assert substantiated["clawback_miles"] == 60000, (
            "a MILE_BROKERING case claws back the lesser of the 60000 balance "
            f"and the 60000 basis, got {substantiated['clawback_miles']}"
        )
        assert (
            substantiated["adjudicated_by_user_id"]
            == SECOND_FRAUD_ANALYST_USER_ID
        ), (
            "the adjudicating analyst's X-User-ID is stamped on the case, got "
            f"{substantiated['adjudicated_by_user_id']}"
        )

        after = read_member(member["id"])
        assert after["security_state"] == "FROZEN", (
            "a MILE_BROKERING substantiation freezes the member, got "
            f"{after['security_state']}"
        )
        assert after["mile_balance"] == 0, (
            "the 60000-mile clawback empties the balance, got "
            f"{after['mile_balance']}"
        )
        assert after["risk_score"] == 17, (
            "risk_score is the detection_score of the member's newest case, got "
            f"{after['risk_score']}"
        )

        rows, meta = validate_paginated(
            api.list_mile_transactions(
                PROGRAM_ADMIN,
                params={"member_id": member["id"], "txn_type": "ADJUSTMENT"},
            )
        )
        assert meta["total_count"] == 1, (
            "exactly one ADJUSTMENT row records the clawback, got total_count "
            f"{meta['total_count']}"
        )
        assert rows[0]["total_miles"] == -60000, (
            "the ADJUSTMENT row carries the negative of clawback_miles, got "
            f"{rows[0]['total_miles']}"
        )

    def test_hops_three_and_four_cancel_the_hold_and_reopen_the_window(self, api):
        """PRD §3.5: "That pre-booking load factor selects `demand_multiplier_bps_applied` from a four-rung ladder whose lower bounds are inclusive: 9000 basis points below 5000, 10000 from 5000 through 7499, 12500 from 7500 through 8999, and 16000 at 9000 and above."
        PRD §3.5: "`chart_miles_per_seat` is read from the award chart by the window's `cabin` and the requested `fare_class`: `ECONOMY` charges 12500 at `SAVER` and 25000 at `FLEX`; `PREMIUM` charges 25000 and 45000; `BUSINESS` charges 50000 and 85000; `FIRST` charges 90000 and 140000."
        PRD §3.5: "The gross award miles per seat are `chart_miles_per_seat` multiplied by `demand_multiplier_bps_applied` and by `partner_uplift_bps_applied`, divided by 100000000 (that is, both basis-point factors converted to plain multipliers), rounded half up."
        PRD §3.5: "`quoted_miles` is then the gross per-seat figure multiplied by the quantity (10000 minus `elite_discount_bps_applied`), divided by 10000, rounded half up **per seat**, and only then multiplied by `seats`."
        PRD §3.5: "`load_factor_bps` is `seats_held` plus `seats_confirmed`, multiplied by 10000, divided by `authorized_seats`, rounded half up, and defined as zero when `authorized_seats` is zero."
        PRD §3.5: "`capacity_control_state` then follows from it against two inclusive lower bounds: a load factor below 7500 basis points (75% sold) is `OPEN`, a load factor from 7500 through 9999 is `CONSTRAINED`, and a load factor of 10000 or more is `CLOSED`."
        PRD §3.7: "The third hop, caused by the second hop's security transition, cancels every one of the member's bookings still in `HELD`, moving each `HELD → CANCELLED` and releasing its seats from `seats_held` and, for `SAVER` bookings, `saver_seats_consumed`."
        PRD §3.7: "The fourth hop, caused by the third hop's seat release, recomputes `load_factor_bps`, `demand_multiplier_bps` and `capacity_control_state` on each affected window."

        Design: Difficulty/transitive_cascade/fraud_substantiation_five_hop_cascade
        """
        _program, _member, window, booking, case = _cascade_setup()

        assert_award_booking(booking)
        assert booking["quoted_miles"] == 612000, (
            "an empty BUSINESS window quotes 85000 chart miles at the 9000 bps "
            "rung with no partner uplift and no BASE discount, so 76500 per seat "
            f"across 8 seats is 612000, got {booking['quoted_miles']}"
        )

        window_before = read_window(window["id"])
        assert_award_inventory_window(window_before)
        assert window_before["seats_held"] == 8, (
            f"the hold took 8 of 10 seats, got {window_before['seats_held']}"
        )
        assert window_before["load_factor_bps"] == 8000, (
            "8 seats of 10 authorised is a load factor of 8000 basis points, got "
            f"{window_before['load_factor_bps']}"
        )
        assert window_before["capacity_control_state"] == "CONSTRAINED", (
            "a load factor of 8000 sits in the 7500-through-9999 band, got "
            f"{window_before['capacity_control_state']}"
        )

        substantiate_case(case["id"], FRAUD_ANALYST_2)

        booking_after = get_success_data(
            api.get_award_booking(booking["id"], PROGRAM_ADMIN)
        )
        assert booking_after["status"] == "CANCELLED", (
            "the freeze cancels every booking still HELD, got "
            f"{booking_after['status']}"
        )

        window_after = read_window(window["id"])
        assert window_after["seats_held"] == 0, (
            "cancelling the 8-seat hold releases every held seat, got "
            f"{window_after['seats_held']}"
        )
        assert window_after["load_factor_bps"] == 0, (
            "with no seats held or confirmed the load factor recomputes to zero, "
            f"got {window_after['load_factor_bps']}"
        )
        assert window_after["capacity_control_state"] == "OPEN", (
            "a load factor below 7500 basis points is OPEN, got "
            f"{window_after['capacity_control_state']}"
        )

    def test_hop_five_reduces_programme_outstanding_miles_by_the_clawback(self):
        """PRD §3.7: "The second hop, caused by the first, applies the outcome: when `clawback_miles` is greater than zero a mile ledger row of `txn_type` `ADJUSTMENT` with `total_miles` equal to the negative of `clawback_miles` is inserted and the member's `mile_balance` is debited accordingly, and the member's `security_state` moves to `CLOSED` for an `ACCOUNT_TAKEOVER` case and to `FROZEN` for either other case type."
        PRD §3.7: "The fifth hop, caused by the second hop's adjustment insert, reduces the programme's `outstanding_miles` by `clawback_miles`."

        Design: Difficulty/transitive_cascade/fraud_substantiation_five_hop_cascade
        """
        program, _member, _window, _booking, case = _cascade_setup()

        before = read_program(program["id"])
        assert_loyalty_program(before)
        assert before["outstanding_miles"] == 60000, (
            "the two earning rows put 60000 miles of liability on the programme, "
            f"got {before['outstanding_miles']}"
        )

        substantiated = substantiate_case(case["id"], FRAUD_ANALYST_2)
        assert substantiated["clawback_miles"] == 60000, (
            "the cascade must claw back the full 60000-mile basis, got "
            f"{substantiated['clawback_miles']}"
        )

        after = read_program(program["id"])
        assert after["outstanding_miles"] == 0, (
            "60000 outstanding miles less a 60000-mile clawback is zero, got "
            f"{after['outstanding_miles']}"
        )
