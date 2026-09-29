"""Lifecycle state machines: initial states, guarded and terminal transitions,
side-effect execution and the clock-driven transitions of the epoch sweep.
"""
from test_helpers import (
    FRAUD_ANALYST,
    PARTNER_MANAGER,
    PROGRAM_ADMIN,
    REVENUE_ACCOUNTANT,
    active_agreement,
    announce_notice,
    assert_award_booking,
    assert_fraud_case,
    assert_mile_purchase_order,
    assert_promotion_campaign,
    cancel_booking,
    create_campaign,
    create_issuer,
    create_member,
    create_order,
    create_posting,
    create_program,
    create_window,
    draft_notice,
    get_success_data,
    grant_status_match,
    hold_seats,
    investigate_case,
    issue_order,
    live_campaign,
    member_headers_for,
    mile_transaction_payload,
    open_case,
    post_transaction,
    program_with_issuer,
    read_agreement,
    read_member,
    read_program,
    read_window,
    run_epoch,
    set_clock,
    tier_schedule,
    transition_recognition,
    validate_error,
    validate_paginated,
    validate_success,
)


# --------------------------------------------------------------------------- #
# Initial state: a campaign is born SCHEDULED and only the epoch sweep launches it
# --------------------------------------------------------------------------- #
def test_campaign_is_born_scheduled_and_unusable_until_the_epoch_sweep_launches_it(api):
    """PRD §3.4: "It is the epoch sweep, not the create call, that moves it `SCHEDULED → LIVE` once `window_start` is at or before the clock's now, and `LIVE → ENDED` once `window_end` is at or before now; only a `LIVE` campaign may be referenced as the `promotion_id` on an earning row."
    PRD §3.4: "A campaign that is not `LIVE` is instead rejected with `ERR_INVALID_STATE`."
    PRD §3.1: "A `ProgramAdmin` names a `program_id` and the system advances every clock-driven transition for that programme at the current logical-clock instant, reporting what it did: the `epoch_at` instant it ran at, plus counts named `holds_expired`, `campaigns_launched`, `campaigns_ended`, `status_matches_lapsed`, `notices_advanced`, `agreements_expired` and `windows_recomputed`."
    PRD §3.4: "Under `ADDITIVE`, the tier rate and the promotional lift are treated as independent percentage adders: the gross total is the base multiplied by the quantity (10000 plus the tier rate plus the amount by which the promotional multiplier exceeds 10000), divided by 10000, rounded half up."
    PRD §3.4: "The stamped `bonus_miles` is the smallest of the raw bonus, the campaign's remaining room, and a per-transaction ceiling of 25000 miles per member."
    PRD §3.4: "The insert then adds `total_miles` to the member's `mile_balance` and `lifetime_miles`, adds `total_miles` to the programme's `outstanding_miles`, and adds `bonus_miles` to the campaign's `accrued_bonus_miles`."

    Design: Corner/state_machines/promotion_campaign_starts_scheduled_and_is_unusable_before_epoch_launch
    """
    program = create_program(name="SkyMiles Initial", current_period="2026-08")
    member = create_member(
        program["id"], external_member_ref="MBR-INIT", home_region="AMER"
    )
    campaign = create_campaign(
        program["id"],
        code="AUG-FLIGHT",
        earn_channel="FLIGHT",
        multiplier_bps=15000,
        stacking_mode="ADDITIVE",
        window_start="2026-08-01T00:00:00Z",
        window_end="2026-12-01T00:00:00Z",
    )
    assert_promotion_campaign(campaign)
    assert campaign["status"] == "SCHEDULED", (
        "a freshly created promotion campaign starts at SCHEDULED, never LIVE"
    )

    earn_payload = mile_transaction_payload(
        member["id"],
        "FLIGHT_EARN",
        "2026-08-01",
        base_miles=1000,
        segments=1,
        promotion_id=campaign["id"],
    )

    too_early = api.create_mile_transaction(earn_payload, REVENUE_ACCOUNTANT)
    validate_error(too_early, "ERR_INVALID_STATE", 409)

    report = run_epoch(program["id"])
    assert report["campaigns_launched"] == 1, (
        "the sweep launches the one campaign whose window_start has arrived"
    )
    launched = get_success_data(
        api.get_promotion_campaign(campaign["id"], PROGRAM_ADMIN)
    )
    assert launched["status"] == "LIVE", (
        "the epoch sweep moves the campaign SCHEDULED -> LIVE"
    )

    accepted = api.create_mile_transaction(earn_payload, REVENUE_ACCOUNTANT)
    txn = validate_success(accepted, expected_status=201)
    assert txn["bonus_miles"] == 500, "1000 base at an ADDITIVE 15000 bps lifts 500"
    assert txn["total_miles"] == 1500, "total_miles is base 1000 plus bonus 500"

    assert read_member(member["id"])["mile_balance"] == 1500, (
        "the member's mile_balance takes the row's total_miles"
    )
    assert get_success_data(
        api.get_promotion_campaign(campaign["id"], PROGRAM_ADMIN)
    )["accrued_bonus_miles"] == 500, (
        "accrued_bonus_miles accumulates the row's bonus_miles"
    )


# --------------------------------------------------------------------------- #
# Valid transition: LIVE -> CANCELLED keeps the bonus miles already accrued
# --------------------------------------------------------------------------- #
def test_cancelling_a_live_campaign_keeps_the_bonus_miles_already_accrued(api):
    """PRD §3.4: "A `ProgramAdmin` may also cancel a campaign from either `SCHEDULED` or `LIVE`, stamping the supplied `reason` into `cancellation_reason` and moving `status` to `CANCELLED`."
    PRD §3.4: "`ENDED` and `CANCELLED` are both terminal, and cancellation deliberately does not claw back bonus miles already accrued."
    PRD §3.4: "The insert then adds `total_miles` to the member's `mile_balance` and `lifetime_miles`, adds `total_miles` to the programme's `outstanding_miles`, and adds `bonus_miles` to the campaign's `accrued_bonus_miles`."

    Design: Corner/state_machines/campaign_cancel_from_live_keeps_already_accrued_bonus_miles
    """
    program = create_program(name="SkyMiles Cancel", current_period="2026-08")
    member = create_member(
        program["id"], external_member_ref="MBR-CANCEL", home_region="AMER"
    )
    campaign = live_campaign(
        program["id"],
        code="AUG-LIVE",
        earn_channel="FLIGHT",
        multiplier_bps=15000,
        stacking_mode="ADDITIVE",
        window_start="2026-08-01T00:00:00Z",
        window_end="2026-12-01T00:00:00Z",
    )
    assert campaign["status"] == "LIVE", "the sweep has launched the campaign"

    post_transaction(
        member["id"],
        "FLIGHT_EARN",
        "2026-08-01",
        headers=REVENUE_ACCOUNTANT,
        base_miles=1000,
        segments=1,
        promotion_id=campaign["id"],
    )

    cancelled = validate_success(
        api.cancel_promotion_campaign(
            campaign["id"], {"reason": "Issuer funding withdrawn"}, PROGRAM_ADMIN
        )
    )
    assert_promotion_campaign(cancelled)
    assert cancelled["status"] == "CANCELLED", "cancel moves a LIVE campaign to CANCELLED"
    assert cancelled["cancellation_reason"] == "Issuer funding withdrawn", (
        "the supplied reason is stamped into cancellation_reason"
    )
    assert cancelled["accrued_bonus_miles"] == 500, (
        "cancellation does not claw back the 500 bonus miles already accrued"
    )
    assert read_member(member["id"])["mile_balance"] == 1500, (
        "the member keeps the 1500 miles the earn credited"
    )
    assert read_program(program["id"])["outstanding_miles"] == 1500, (
        "programme-wide outstanding_miles is untouched by the cancellation"
    )


# --------------------------------------------------------------------------- #
# Invalid transition: ticketing a CANCELLED booking
# --------------------------------------------------------------------------- #
def test_ticketing_a_cancelled_booking_is_refused_with_invalid_state(api):
    """PRD §2.9: "The target row is in a state from which the requested transition exists, per the state machines described throughout §3 — otherwise `ERR_INVALID_STATE` (409)."
    PRD §2.9: "This rung also carries the parent-state preconditions of create operations: the issuer must be `ACTIVE`, the agreement must be `ACTIVE` before an order may be drawn against it, a referenced campaign must be `LIVE`, a booking must be `HELD` before it is ticketed or cancelled, and a fraud case must be in the status its transition demands."
    PRD §3.5: "**Cancelling** a hold is available to a `Member`, a `ProgramAdmin`, or the fraud security cascade, and requires `status` to be `HELD`; it moves `HELD → CANCELLED`, decreases `seats_held` by `seats`, decreases `saver_seats_consumed` by `seats` when `fare_class` is `SAVER`, and recomputes the window's three derived posture fields."
    PRD §3.5: "`capacity_control_state` then follows from it against two inclusive lower bounds: a load factor below 7500 basis points (75% sold) is `OPEN`, a load factor from 7500 through 9999 is `CONSTRAINED`, and a load factor of 10000 or more is `CLOSED`."
    PRD §3.4: "**First**, base miles are resolved by type: a `FLIGHT_EARN` row takes the supplied `base_miles` and requires `segments`; a `PARTNER_EARN` row takes the supplied `base_miles`; a `CARD_SPEND_EARN` row ignores `base_miles` entirely and derives its base as the supplied `qualifying_spend_cents` divided by 100 and rounded **down** to a whole mile, which is one base mile per dollar of card spend."

    Design: Corner/state_machines/ticket_a_cancelled_booking_returns_invalid_state
    """
    program = create_program(name="SkyMiles Invalid", current_period="2026-08")
    member = create_member(
        program["id"], external_member_ref="MBR-INVALID", home_region="AMER"
    )
    post_transaction(
        member["id"],
        "CARD_SPEND_EARN",
        "2026-07-02",
        headers=REVENUE_ACCOUNTANT,
        qualifying_spend_cents=10000000,
    )
    window = create_window(
        program["id"],
        route_code="JFK-CDG",
        cabin="ECONOMY",
        window_start_date="2026-09-01",
        window_end_date="2026-09-30",
        authorized_seats=10,
    )
    booking = hold_seats(
        member["id"],
        window["id"],
        window["version"],
        travel_date="2026-09-15",
        seats=1,
        fare_class="FLEX",
    )
    cancel_booking(booking["id"])

    refused = api.ticket_award_booking(booking["id"], PROGRAM_ADMIN)
    validate_error(refused, "ERR_INVALID_STATE", 409)

    after = get_success_data(api.get_award_booking(booking["id"], PROGRAM_ADMIN))
    assert_award_booking(after)
    assert after["status"] == "CANCELLED", (
        "the refused ticket leaves the terminal CANCELLED status in place"
    )
    assert read_member(member["id"])["mile_balance"] == 100000, (
        "no miles were debited: 10000000 cents of card spend is 100000 base miles"
    )
    window_after = read_window(window["id"])
    assert window_after["seats_held"] == 0, "the cancel already released the held seat"
    assert window_after["seats_confirmed"] == 0, (
        "the refused ticket confirmed no seat"
    )
    assert window_after["capacity_control_state"] == "OPEN", (
        "an empty window sits below 7500 bps and is therefore OPEN"
    )

    rows, meta = validate_paginated(
        api.list_mile_transactions(PROGRAM_ADMIN, params={"member_id": member["id"]})
    )
    assert meta["total_count"] == 1, (
        "the ledger still carries only the funding row, no REDEEM was inserted"
    )
    assert rows[0]["txn_type"] == "CARD_SPEND_EARN"


# --------------------------------------------------------------------------- #
# Idempotency: a second investigate on an INVESTIGATING case
# --------------------------------------------------------------------------- #
def test_second_investigate_on_an_investigating_case_is_an_error_not_a_no_op(api):
    """PRD §3.7: "A `FraudAnalyst` moves an `OPEN` case to `INVESTIGATING`, and from there adjudicates it in one of two directions."
    PRD §2.9: "The target row is in a state from which the requested transition exists, per the state machines described throughout §3 — otherwise `ERR_INVALID_STATE` (409)."
    PRD §2.4: "`version` is an integer that increments by exactly one on every such change."
    PRD §3.7: "A score below 40 leaves `security_state` where it was."
    PRD §3.7: "In every case, including the last, the member's `risk_score` is set to the new `detection_score`; `risk_score` is by definition the `detection_score` of the member's most recent case, ordered by `created_at` ascending so the newest wins."
    PRD §3.7: "The opener's `X-User-ID` is stamped into `opened_by_user_id`, `adjudicated_by_user_id` starts null, `clawback_miles` starts at zero, `freeze_applied` starts false, and `status` starts `OPEN`."

    Design: Corner/state_machines/second_investigate_on_an_investigating_case_returns_invalid_state
    """
    program = create_program(name="SkyMiles Idem", current_period="2026-08")
    member = create_member(
        program["id"], external_member_ref="MBR-IDEM", home_region="APAC"
    )
    case = open_case(
        member["id"],
        "VELOCITY_ANOMALY",
        login_geo_velocity=0,
        redemption_velocity_24h=0,
        brokering_pattern_hits=0,
        dormancy_days=0,
    )
    assert_fraud_case(case)
    assert case["detection_score"] == 0, "four zero signals blend to a score of 0"

    investigating = investigate_case(case["id"])
    assert investigating["status"] == "INVESTIGATING", (
        "the first investigate moves the case OPEN -> INVESTIGATING"
    )
    assert investigating["version"] == case["version"] + 1, (
        "the accepted transition increments the case version by exactly one"
    )

    replay = api.investigate_fraud_case(case["id"], FRAUD_ANALYST)
    validate_error(replay, "ERR_INVALID_STATE", 409)

    after = get_success_data(api.get_fraud_case(case["id"], FRAUD_ANALYST))
    assert after["status"] == "INVESTIGATING", (
        "the refused replay leaves the case in INVESTIGATING"
    )
    assert after["version"] == investigating["version"], (
        "the refused replay mutates nothing, so the version does not advance again"
    )
    assert after["freeze_applied"] is False, (
        "a case scoring 0 never applied a freeze"
    )

    member_after = read_member(member["id"])
    assert member_after["security_state"] == "NORMAL", (
        "a detection_score below 40 leaves security_state where it was"
    )
    assert member_after["risk_score"] == 0, (
        "risk_score echoes the most recent case's detection_score"
    )


# --------------------------------------------------------------------------- #
# Terminal state lockdown: settling a reversed order
# --------------------------------------------------------------------------- #
def test_settling_a_reversed_order_is_refused_after_the_full_unwind(api):
    """PRD §3.3: "Settling is a bookkeeping acknowledgement by a `RevenueAccountant` that the cash arrived: it requires `settlement_status` to be `INVOICED` and moves it `INVOICED → SETTLED`."
    PRD §3.3: "Reversal moves the fulfilment dimension `ISSUED → REVERSED` and forces the settlement dimension to `WRITTEN_OFF`, stamps the supplied `reason` into `reversal_reason`, reduces the agreement's `drawn_miles` and `prepayment_balance_miles` by `order_miles` each, and debits the programme's `deferred_revenue_cents` by exactly the cents that were credited: `net_amount_cents` when the order had already reached `INVOICED`, otherwise `gross_amount_cents`."
    PRD §3.3: "That entry's `price_per_mile_centicents` is stamped as `provisional_tier_price_centicents`, and `gross_amount_cents` is the `order_miles` multiplied by that centicent price, divided by 100 to convert centicents to cents, rounded half up."
    PRD §2.9: "The target row is in a state from which the requested transition exists, per the state machines described throughout §3 — otherwise `ERR_INVALID_STATE` (409)."

    Design: Corner/state_machines/settle_a_reversed_order_returns_invalid_state
    """
    program = create_program(name="SkyMiles Terminal", current_period="2026-08")
    issuer = create_issuer(
        program["id"],
        name="Northbank Card Services",
        annual_mile_purchase_cap_miles=5000000,
    )
    agreement = active_agreement(
        issuer["id"],
        term_start_date="2026-09-01",
        term_end_date="2027-08-31",
        committed_volume_miles=1000000,
        tier_schedule=tier_schedule((0, 200)),
    )
    order = create_order(agreement["id"], 100000, agreement["version"])
    issue_order(order["id"])
    reversed_order = get_success_data(
        api.reverse_order(
            order["id"], {"reason": "Issuer cancelled the tranche"}, PARTNER_MANAGER
        )
    )
    assert_mile_purchase_order(reversed_order)

    refused = api.settle_order(order["id"], REVENUE_ACCOUNTANT)
    validate_error(refused, "ERR_INVALID_STATE", 409)

    after = get_success_data(
        api.get_mile_purchase_order(order["id"], REVENUE_ACCOUNTANT)
    )
    assert after["fulfillment_status"] == "REVERSED", (
        "the fulfilment dimension stays REVERSED"
    )
    assert after["settlement_status"] == "WRITTEN_OFF", (
        "reversal forced the settlement dimension to WRITTEN_OFF, which admits no settle"
    )
    assert after["gross_amount_cents"] == 200000, (
        "100000 miles at 200 centicents is 200000 cents"
    )
    assert after["reversal_reason"] == "Issuer cancelled the tranche", (
        "the supplied reason was stamped into reversal_reason"
    )

    agreement_after = read_agreement(agreement["id"])
    assert agreement_after["drawn_miles"] == 0, (
        "reversal reduced drawn_miles by the full order_miles"
    )
    assert agreement_after["prepayment_balance_miles"] == 0, (
        "reversal reduced prepayment_balance_miles by the full order_miles"
    )
    assert read_program(program["id"])["deferred_revenue_cents"] == 0, (
        "reversal debited exactly the gross_amount_cents that issuance credited"
    )


# --------------------------------------------------------------------------- #
# Precondition enforcement: CLOSING -> LOCKED demands a posting
# --------------------------------------------------------------------------- #
def test_locking_a_closing_period_without_a_posting_is_refused(api):
    """PRD §3.9: "From `CLOSING` it may move to `LOCKED` — but only once a deferred revenue posting already exists for this programme and its `current_period`, so a period cannot be locked without being posted."
    PRD §3.9: "Every one of these four transitions increments the programme's `version` by one, and each requires the posture to be exactly the state the transition leaves from."
    PRD §3.9: "From `LOCKED` it returns to `OPEN`, and that transition alone advances `current_period` by exactly one calendar month."

    Design: Corner/state_machines/lock_period_without_a_posting_returns_invalid_state
    """
    program = create_program(name="SkyMiles Precondition", current_period="2026-08")
    closing = transition_recognition(program["id"], "CLOSING")
    assert closing["revenue_recognition_state"] == "CLOSING"
    assert closing["version"] == program["version"] + 1, (
        "the OPEN -> CLOSING transition increments the programme version by one"
    )

    refused = api.create_recognition_transition(
        program["id"], {"target_state": "LOCKED"}, REVENUE_ACCOUNTANT
    )
    validate_error(refused, "ERR_INVALID_STATE", 409)

    after = read_program(program["id"])
    assert after["revenue_recognition_state"] == "CLOSING", (
        "the refused lock leaves the programme in CLOSING"
    )
    assert after["current_period"] == "2026-08", (
        "only the LOCKED -> OPEN transition advances current_period"
    )
    assert after["version"] == closing["version"], (
        "the refused transition mutates nothing, so the version does not advance"
    )

    _, meta = validate_paginated(
        api.list_deferred_revenue_postings(
            REVENUE_ACCOUNTANT, params={"program_id": program["id"]}
        )
    )
    assert meta["total_count"] == 0, "no posting was written for the period"


# --------------------------------------------------------------------------- #
# Side-effect execution: one issue call lands all three declared effects
# --------------------------------------------------------------------------- #
def test_order_issue_lands_all_three_declared_side_effects_in_one_call(api):
    """PRD §3.3: "Its effects reach three rows: the agreement's `drawn_miles` increases by `order_miles`, the agreement's `prepayment_balance_miles` increases by the same `order_miles` (these are miles bought but not yet distributed to members), and the programme's `deferred_revenue_cents` increases by `gross_amount_cents`."
    PRD §3.3: "Both the order's `version` and the agreement's `version` increment by one."
    PRD §3.3: "The order lands with `fulfillment_status` at `PENDING` and `settlement_status` at `PENDING`, with `final_amount_cents`, `net_amount_cents`, `posted_period` and `reversal_reason` all null and `volume_true_up_cents` at zero."
    PRD §3.3: "At creation the order snapshots the agreement's live `drawn_miles` into `drawn_miles_before`."
    PRD §3.3: "That entry's `price_per_mile_centicents` is stamped as `provisional_tier_price_centicents`, and `gross_amount_cents` is the `order_miles` multiplied by that centicent price, divided by 100 to convert centicents to cents, rounded half up."

    Design: Corner/state_machines/order_issue_executes_all_three_declared_side_effects
    """
    program, issuer = program_with_issuer(
        program_overrides={
            "name": "SkyMiles SideEffects", "current_period": "2026-08",
        },
        issuer_overrides={
            "name": "Northbank Card Services",
            "annual_mile_purchase_cap_miles": 5000000,
        },
    )
    agreement = active_agreement(
        issuer["id"],
        term_start_date="2026-09-01",
        term_end_date="2027-08-31",
        committed_volume_miles=1000000,
        tier_schedule=tier_schedule((0, 150)),
    )
    order = create_order(agreement["id"], 200000, agreement["version"])
    agreement_before_issue = read_agreement(agreement["id"])

    issued = validate_success(api.issue_order(order["id"], PARTNER_MANAGER))
    assert_mile_purchase_order(issued)
    assert issued["fulfillment_status"] == "ISSUED", (
        "issuing moves the fulfilment dimension PENDING -> ISSUED"
    )
    assert issued["settlement_status"] == "PENDING", (
        "the settlement dimension is untouched until invoicing"
    )
    assert issued["drawn_miles_before"] == 0, (
        "the order snapshotted an agreement that had drawn nothing"
    )
    assert issued["provisional_tier_price_centicents"] == 150, (
        "the only tier opening at threshold 0 prices the whole order"
    )
    assert issued["gross_amount_cents"] == 300000, (
        "200000 miles at 150 centicents is 300000 cents"
    )
    assert issued["final_amount_cents"] is None, "final pricing runs only at invoicing"
    assert issued["net_amount_cents"] is None, "net_amount_cents is set only at invoicing"
    assert issued["volume_true_up_cents"] == 0, "the true-up is booked only at invoicing"
    assert issued["posted_period"] is None, "posted_period is stamped only at invoicing"
    assert issued["version"] == order["version"] + 1, (
        "the order's version increments by one on issuance"
    )

    agreement_after = read_agreement(agreement["id"])
    assert agreement_after["drawn_miles"] == 200000, (
        "drawn_miles increases by the full order_miles"
    )
    assert agreement_after["prepayment_balance_miles"] == 200000, (
        "prepayment_balance_miles increases by the same order_miles"
    )
    assert agreement_after["version"] == agreement_before_issue["version"] + 1, (
        "the agreement's version increments by one on issuance"
    )
    assert read_program(program["id"])["deferred_revenue_cents"] == 300000, (
        "deferred_revenue_cents is credited with the order's gross_amount_cents"
    )


# --------------------------------------------------------------------------- #
# Cyclic: one full recognition lap returns to OPEN on the next period
# --------------------------------------------------------------------------- #
def test_one_recognition_lap_returns_to_open_on_the_next_period(api):
    """PRD §3.9: "From `LOCKED` it returns to `OPEN`, and that transition alone advances `current_period` by exactly one calendar month."
    PRD §3.9: "Every one of these four transitions increments the programme's `version` by one, and each requires the posture to be exactly the state the transition leaves from."
    PRD §3.9: "The posting then writes back to the programme: `deferred_revenue_cents` becomes `deferred_balance_after_cents`, `last_breakage_rate_bps` becomes this posting's `breakage_rate_bps`, `lifetime_breakage_income_cents` increases by this posting's `breakage_income_cents`, and the programme's `version` increments by one."

    Design: Corner/state_machines/recognition_cycle_advances_current_period_on_unlock
    """
    program = create_program(name="SkyMiles Cycle", current_period="2026-08")
    version_at_open = program["version"]

    closing = transition_recognition(program["id"], "CLOSING")
    posting = create_posting(program["id"], "2026-08", closing["version"])
    transition_recognition(program["id"], "LOCKED")

    reopened = validate_success(
        api.create_recognition_transition(
            program["id"], {"target_state": "OPEN"}, REVENUE_ACCOUNTANT
        )
    )
    assert reopened["revenue_recognition_state"] == "OPEN", (
        "the lap closes by returning the posture to OPEN"
    )
    assert reopened["current_period"] == "2026-09", (
        "the LOCKED -> OPEN transition advances current_period by one calendar month"
    )
    assert reopened["version"] == version_at_open + 4, (
        "three posture transitions plus the posting's write-back each bumped the "
        "programme version exactly once"
    )
    assert posting["period"] == "2026-08", (
        "the posting stays anchored to the period it recognised"
    )


# --------------------------------------------------------------------------- #
# Cascade down: rollback of an EARN_STRUCTURE notice is channel- and status-scoped
# --------------------------------------------------------------------------- #
def test_notice_rollback_cancels_only_scheduled_card_spend_campaigns(api):
    """PRD §3.8: "At any point from `ANNOUNCED`, `IN_GRANDFATHER` or `EFFECTIVE`, a `ProgramAdmin` may roll the change back with a supplied `reason`, which is stamped into `rollback_reason` and moves `status` to the terminal `ROLLED_BACK`."
    PRD §3.8: "Rollback carries one cross-entity consequence: when the rolled-back notice's `change_type` is `EARN_STRUCTURE`, every promotion campaign in the same programme whose `status` is `SCHEDULED` and whose `earn_channel` is `CARD_SPEND` is itself cancelled, moving `SCHEDULED → CANCELLED`, because those campaigns were priced against the earn structure that is no longer changing."
    PRD §3.8: "`notice_days` is the whole number of days from `announced_at` to `effective_at`, taking the floor of the difference."
    PRD §3.8: "`exposed_member_count` is the number of member accounts in the programme whose `elite_tier` is anything other than `BASE` and whose `security_state` is either `NORMAL` or `WATCH`, snapshotted at announcement."
    PRD §3.8: "The first ingredient is severity, taken from `change_type`: 40 points for `EARN_STRUCTURE`, 50 for `AWARD_PRICING`, 30 for `ELITE_THRESHOLD` and 20 for `EXPIRY_POLICY` — repricing awards angers members more than tightening expiry."
    PRD §3.8: "The second is a lead-time factor keyed by `notice_days` against inclusive lower bounds: 10000 basis points at 180 days or more, 12500 from 90 through 179 days, 15000 from 30 through 89 days, and 20000 below 30 days, so exactly 180, 90 or 30 days each take the kinder factor."
    PRD §3.8: "The third is grandfathering relief: 30 points when `grandfather_until` is at or after `effective_at` plus 365 days, 15 points when `grandfather_until` is at or after `effective_at` but earlier than that full year (so a `grandfather_until` exactly equal to `effective_at` still earns the partial 15), and 0 points when `grandfather_until` is null."
    PRD §3.8: "The fourth is exposure: an exposure factor of 10000 basis points plus 100 basis points for each exposed member, with that uplift capped at 5000 basis points — the cap saturating at 50 exposed members, beyond which the fifty-first exposed member does not move the index at all."
    PRD §3.8: "Severity is multiplied by the lead-time factor, divided by 10000, and rounded half up."
    PRD §3.8: "Relief points are subtracted from that product and the result is floored at zero — relief can therefore drive the pre-exposure term to zero, in which case the index is zero no matter how many members are exposed."
    PRD §3.8: "That floored term is then multiplied by the exposure factor, divided by 10000, rounded half up, and finally capped at 100 to give `member_reaction_index`."

    Design: Corner/state_machines/notice_rollback_cascades_only_into_scheduled_card_spend_campaigns
    """
    program = create_program(name="SkyMiles Cascade Down", current_period="2026-08")
    card_september = create_campaign(
        program["id"],
        code="CARD-SEP",
        earn_channel="CARD_SPEND",
        multiplier_bps=15000,
        stacking_mode="ADDITIVE",
        window_start="2026-09-01T00:00:00Z",
        window_end="2026-10-01T00:00:00Z",
    )
    card_october = create_campaign(
        program["id"],
        code="CARD-OCT",
        earn_channel="CARD_SPEND",
        multiplier_bps=15000,
        stacking_mode="ADDITIVE",
        window_start="2026-10-01T00:00:00Z",
        window_end="2026-11-01T00:00:00Z",
    )
    flight_september = create_campaign(
        program["id"],
        code="FLIGHT-SEP",
        earn_channel="FLIGHT",
        multiplier_bps=15000,
        stacking_mode="ADDITIVE",
        window_start="2026-09-01T00:00:00Z",
        window_end="2026-10-01T00:00:00Z",
    )

    notice = draft_notice(
        program["id"],
        "EARN_STRUCTURE",
        "2027-03-01T00:00:00Z",
        read_program(program["id"])["version"],
    )
    announced = announce_notice(notice["id"])
    assert announced["notice_days"] == 212, (
        "2026-08-01 to 2027-03-01 is 212 whole days of lead time"
    )
    assert announced["exposed_member_count"] == 0, (
        "the programme has no non-BASE member, so nobody is exposed"
    )
    assert announced["member_reaction_index"] == 40, (
        "severity 40 at the 10000 bps lead-time factor, no relief and a neutral "
        "exposure factor leaves the index at 40"
    )

    rolled_back = validate_success(
        api.rollback_notice(
            notice["id"], {"reason": "Member advocacy escalation"}, PROGRAM_ADMIN
        )
    )
    assert rolled_back["status"] == "ROLLED_BACK", "rollback is terminal"
    assert rolled_back["rollback_reason"] == "Member advocacy escalation", (
        "the supplied reason is stamped into rollback_reason"
    )

    for campaign_id, code in (
        (card_september["id"], "CARD-SEP"), (card_october["id"], "CARD-OCT"),
    ):
        cascaded = get_success_data(
            api.get_promotion_campaign(campaign_id, PROGRAM_ADMIN)
        )
        assert cascaded["status"] == "CANCELLED", (
            f"the SCHEDULED CARD_SPEND campaign {code} is cancelled by the cascade"
        )
    untouched = get_success_data(
        api.get_promotion_campaign(flight_september["id"], PROGRAM_ADMIN)
    )
    assert untouched["status"] == "SCHEDULED", (
        "the cascade is channel-scoped, so the FLIGHT campaign is untouched"
    )

    _, meta = validate_paginated(
        api.list_promotion_campaigns(
            PROGRAM_ADMIN,
            params={"program_id": program["id"], "status": "CANCELLED"},
        )
    )
    assert meta["total_count"] == 2, "exactly the two CARD_SPEND campaigns cancelled"


# --------------------------------------------------------------------------- #
# Ledger sync: ticketing debits member and programme by the same miles
# --------------------------------------------------------------------------- #
def test_ticketing_debits_member_and_programme_liability_in_lockstep(api):
    """PRD §3.5: "A mile ledger row of `txn_type` `REDEEM` is inserted with `total_miles` equal to the negative of `quoted_miles` and `award_booking_id` naming this booking."
    PRD §3.5: "The member's `mile_balance` falls by `quoted_miles` and the programme's `outstanding_miles` falls by the same amount — the liability is discharged."
    PRD §3.5: "On the window, `seats_held` falls by `seats` while `seats_confirmed` rises by `seats`, after which `load_factor_bps`, `demand_multiplier_bps` and `capacity_control_state` are recomputed; note that this movement leaves total occupancy unchanged, so a ticketing event by itself does not change the posture."
    PRD §3.5: "`load_factor_bps` is `seats_held` plus `seats_confirmed`, multiplied by 10000, divided by `authorized_seats`, rounded half up, and defined as zero when `authorized_seats` is zero."
    PRD §3.5: "The gross award miles per seat are `chart_miles_per_seat` multiplied by `demand_multiplier_bps_applied` and by `partner_uplift_bps_applied`, divided by 100000000 (that is, both basis-point factors converted to plain multipliers), rounded half up."
    PRD §3.4: "**First**, base miles are resolved by type: a `FLIGHT_EARN` row takes the supplied `base_miles` and requires `segments`; a `PARTNER_EARN` row takes the supplied `base_miles`; a `CARD_SPEND_EARN` row ignores `base_miles` entirely and derives its base as the supplied `qualifying_spend_cents` divided by 100 and rounded **down** to a whole mile, which is one base mile per dollar of card spend."

    Design: Corner/state_machines/booking_ticket_debits_member_and_program_liability_in_lockstep
    """
    program = create_program(name="SkyMiles Lockstep", current_period="2026-08")
    member = create_member(
        program["id"], external_member_ref="MBR-LOCK", home_region="AMER"
    )
    post_transaction(
        member["id"],
        "CARD_SPEND_EARN",
        "2026-07-02",
        headers=REVENUE_ACCOUNTANT,
        qualifying_spend_cents=10000000,
    )
    assert read_program(program["id"])["outstanding_miles"] == 100000, (
        "the card-spend earn put 100000 miles of liability on the programme"
    )
    window = create_window(
        program["id"],
        route_code="JFK-CDG",
        cabin="ECONOMY",
        window_start_date="2026-09-01",
        window_end_date="2026-09-30",
        authorized_seats=10,
    )
    member_headers = member_headers_for(member["id"])
    booking = hold_seats(
        member["id"],
        window["id"],
        window["version"],
        headers=member_headers,
        travel_date="2026-09-18",
        seats=1,
        fare_class="FLEX",
    )
    assert booking["quoted_miles"] == 22500, (
        "25000 chart miles at a 9000 bps demand multiplier on own metal is 22500"
    )

    ticketed = validate_success(
        api.ticket_award_booking(booking["id"], member_headers)
    )
    assert_award_booking(ticketed)
    assert ticketed["status"] == "TICKETED"
    assert ticketed["quoted_miles"] == 22500

    assert read_member(member["id"])["mile_balance"] == 77500, (
        "the member's balance falls from 100000 by exactly quoted_miles"
    )
    assert read_program(program["id"])["outstanding_miles"] == 77500, (
        "the programme's outstanding_miles falls by exactly the same 22500"
    )

    window_after = read_window(window["id"])
    assert window_after["seats_held"] == 0, "the held seat is released"
    assert window_after["seats_confirmed"] == 1, "the held seat becomes confirmed"
    assert window_after["load_factor_bps"] == 1000, (
        "one occupied seat of ten authorised is 1000 basis points"
    )

    redeem_rows, redeem_meta = validate_paginated(
        api.list_mile_transactions(
            PROGRAM_ADMIN,
            params={"member_id": member["id"], "txn_type": "REDEEM"},
        )
    )
    assert redeem_meta["total_count"] == 1, "ticketing inserted exactly one REDEEM row"
    assert redeem_rows[0]["total_miles"] == -22500, (
        "the REDEEM row carries the negative of quoted_miles"
    )

    _, booking_meta = validate_paginated(
        api.list_mile_transactions(
            PROGRAM_ADMIN,
            params={"member_id": member["id"], "award_booking_id": booking["id"]},
        )
    )
    assert booking_meta["total_count"] == 1, (
        "exactly one ledger row names this award booking"
    )


# --------------------------------------------------------------------------- #
# Conditional cascade: the epoch sweep lapses an expired status match
# --------------------------------------------------------------------------- #
def test_epoch_status_match_lapse_reverts_the_elite_tier_and_the_next_earn(api):
    """PRD §3.6: "The grant moves `status_match_state` `NONE → TRIAL`, sets both `elite_tier` and `status_match_tier` to `matched_tier`, and sets `status_match_expires_at` to the logical clock's now plus `trial_days` days."
    PRD §3.6: "The epoch sweep produces the identical `TRIAL → LAPSED` transition, with the identical tier reversion, for any trial whose `status_match_expires_at` is at or before the clock's now."
    PRD §3.6: "An outcome of `LAPSE` moves `TRIAL → LAPSED` and reverts `elite_tier` to `awarded_tier_at_close` when that field is not null, and to `BASE` otherwise."
    PRD §3.4: "Every row records `elite_tier_at_earn`, a snapshot of the member's `elite_tier` at insert time, and `posted_period`, a snapshot of the programme's `current_period`."
    PRD §3.4: "**Second**, the elite tier bonus is computed: the tier bonus rate is 0 basis points at `BASE`, 2500 at `SILVER`, 5000 at `GOLD` and 10000 at `PLATINUM`, so a platinum member's bonus doubles their base, and `tier_bonus_miles` is the base multiplied by that rate divided by 10000, rounded half up."
    PRD §3.1: "A `ProgramAdmin` names a `program_id` and the system advances every clock-driven transition for that programme at the current logical-clock instant, reporting what it did: the `epoch_at` instant it ran at, plus counts named `holds_expired`, `campaigns_launched`, `campaigns_ended`, `status_matches_lapsed`, `notices_advanced`, `agreements_expired` and `windows_recomputed`."

    Design: Corner/state_machines/status_match_lapse_by_epoch_reverts_elite_tier_to_base
    """
    program = create_program(name="SkyMiles Lapse", current_period="2026-08")
    member = create_member(
        program["id"], external_member_ref="MBR-LAPSE", home_region="EMEA"
    )
    granted = grant_status_match(member["id"], "GOLD", 30)
    assert granted["elite_tier"] == "GOLD", "the grant raises elite_tier to matched_tier"
    assert granted["status_match_expires_at"].startswith("2026-08-31T00:00:00"), (
        "30 trial days from the clock's 2026-08-01 now expires on 2026-08-31"
    )

    set_clock("2026-09-01T00:00:00Z")
    report = run_epoch(program["id"])
    assert report["status_matches_lapsed"] == 1, (
        "the sweep lapses the one trial whose expiry has passed"
    )

    lapsed = read_member(member["id"])
    assert lapsed["status_match_state"] == "LAPSED", (
        "the sweep moves status_match_state TRIAL -> LAPSED"
    )
    assert lapsed["status_match_tier"] == "GOLD", (
        "the matched tier is retained on the row after the lapse"
    )
    assert lapsed["elite_tier"] == "BASE", (
        "with awarded_tier_at_close null the reversion lands on BASE"
    )

    txn = validate_success(
        api.create_mile_transaction(
            mile_transaction_payload(
                member["id"], "FLIGHT_EARN", "2026-09-01", base_miles=1000, segments=1
            ),
            REVENUE_ACCOUNTANT,
        ),
        expected_status=201,
    )
    assert txn["elite_tier_at_earn"] == "BASE", (
        "the post-lapse earn snapshots the reverted tier"
    )
    assert txn["tier_bonus_miles"] == 0, "the BASE tier bonus rate is 0 basis points"
    assert txn["total_miles"] == 1000, "1000 base miles with no bonus of any kind"
    assert read_member(member["id"])["mile_balance"] == 1000, (
        "the member's balance takes the un-bonused total"
    )
