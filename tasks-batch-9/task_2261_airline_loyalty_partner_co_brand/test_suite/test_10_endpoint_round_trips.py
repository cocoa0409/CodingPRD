"""Endpoint round trips: create, read back, list, and drive the utilities.

Each test exercises one endpoint group end to end and checks that what the
server stored on the way in is what it hands back on the way out.
"""
from test_helpers import (
    PARTNER_MANAGER,
    PROGRAM_ADMIN,
    REVENUE_ACCOUNTANT,
    assert_epoch_report,
    assert_partner_airline,
    assert_program_change_notice,
    create_member,
    create_program,
    create_window,
    is_iso8601_timestamp,
    partner_airline_payload,
    program_change_notice_payload,
    read_member,
    read_program,
    read_window,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_partner_airline_create_read_list_round_trip_applies_declared_defaults(api):
    """PRD §3.1: "A **partner airline** is likewise registered by a `ProgramAdmin` or a `PartnerManager` under a `program_id`, with a two-letter `iata_code` unique within the programme and a `settlement_rate_centicents_per_mile` of at least one, being the cash the programme owes the partner for each redeemed mile."
    PRD §3.1: "`reciprocity_mode` defaults to `FULL` and may also be `INBOUND_ONLY`, `OUTBOUND_ONLY` or `SUSPENDED`; it sets the netting factor applied during settlement and, when `SUSPENDED`, blocks both settlement runs and new bookings naming the partner."
    PRD §3.1: "`award_pricing_mode` defaults to `FIXED_CHART` and may also be `DISTANCE_BAND` or `DYNAMIC_PASSTHROUGH`; it determines how partner award miles are uplifted over the own-metal chart."
    PRD §3.1: "A newly registered partner has `net_settlement_balance_cents` and `settled_booking_count` at zero and a null `last_settlement_run_at`."
    PRD §2.3: "Partner airlines filter by `program_id` and `reciprocity_mode`."
    PRD §4: "Operations that bring a new resource into existence return `201 Created`; every other successful operation, including all state transitions, all posture changes, all reads and both test-driving utilities, returns `200 OK`."

    Design: Corner/endpoints/partner_airline_create_read_list_round_trip_applies_declared_defaults
    """
    program = create_program(name="SkyMiles Partners")

    created = validate_success(
        api.create_partner_airline(
            partner_airline_payload(
                program["id"],
                name="Air Atlantique",
                iata_code="AF",
                settlement_rate_centicents_per_mile=150,
            ),
            PARTNER_MANAGER,
        ),
        201,
    )
    assert_partner_airline(created)
    assert created["reciprocity_mode"] == "FULL", (
        f"reciprocity_mode defaults to FULL, got {created['reciprocity_mode']!r}"
    )
    assert created["award_pricing_mode"] == "FIXED_CHART", (
        "award_pricing_mode defaults to FIXED_CHART, "
        f"got {created['award_pricing_mode']!r}"
    )
    assert created["net_settlement_balance_cents"] == 0, (
        "a newly registered partner nets nothing yet, "
        f"got {created['net_settlement_balance_cents']}"
    )
    assert created["settled_booking_count"] == 0, (
        f"settled_booking_count starts at zero, got {created['settled_booking_count']}"
    )
    assert created["last_settlement_run_at"] is None, (
        "a newly registered partner has never been settled, "
        f"got {created['last_settlement_run_at']!r}"
    )

    read = validate_success(
        api.get_partner_airline(created["id"], REVENUE_ACCOUNTANT), 200
    )
    assert read["id"] == created["id"], (
        "the read returns the same partner row that was created"
    )
    assert read["iata_code"] == "AF", (
        f"the read projects the stored iata_code, got {read['iata_code']!r}"
    )
    assert read["settlement_rate_centicents_per_mile"] == 150, (
        "the read projects the stored settlement rate, "
        f"got {read['settlement_rate_centicents_per_mile']}"
    )

    rows, meta = validate_paginated(
        api.list_partner_airlines(
            PARTNER_MANAGER,
            params={"program_id": program["id"], "reciprocity_mode": "FULL"},
        )
    )
    assert meta["total_count"] == 1, (
        "the programme's one FULL partner matches both filters, "
        f"got total_count {meta['total_count']}"
    )
    assert meta["has_more"] is False, (
        "a single matching row leaves nothing beyond the page"
    )
    assert [row["id"] for row in rows] == [created["id"]], (
        "the listed row is the partner just registered"
    )


def test_capacity_control_pin_to_closed_blocks_bookings_until_pinned_back_open(api):
    """PRD §3.5: "A `ProgramAdmin` may additionally pin the posture by hand: pinning to `CLOSED` is permitted from `OPEN` or `CONSTRAINED` whenever the state is not already `CLOSED`, and reopening a pinned window to `OPEN` requires both that it currently be `CLOSED` and that its `load_factor_bps` already sit below 7500."
    PRD §3.5: "While a window is `CLOSED`, new holds are refused with `ERR_AWARD_WINDOW_CLOSED`."
    PRD §3.5: "That pre-booking load factor selects `demand_multiplier_bps_applied` from a four-rung ladder whose lower bounds are inclusive: 9000 basis points below 5000, 10000 from 5000 through 7499, 12500 from 7500 through 8999, and 16000 at 9000 and above."
    PRD §3.5: "`quoted_miles` is then the gross per-seat figure multiplied by the quantity (10000 minus `elite_discount_bps_applied`), divided by 10000, rounded half up **per seat**, and only then multiplied by `seats`."
    PRD §3.5: "The window's `seats_held` increases by `seats`, and for a `SAVER` booking `saver_seats_consumed` increases by `seats` as well; `load_factor_bps`, `demand_multiplier_bps` and `capacity_control_state` are then recomputed and the window's `version` increments."

    Design: Corner/endpoints/capacity_control_pin_to_closed_blocks_bookings_until_pinned_back_open
    """
    program = create_program(name="SkyMiles Capacity")
    member = create_member(
        program["id"], external_member_ref="MBR-CAP", home_region="AMER"
    )
    window = create_window(
        program["id"],
        route_code="JFK-CDG",
        cabin="ECONOMY",
        window_start_date="2026-09-01",
        window_end_date="2026-09-30",
        authorized_seats=10,
    )

    pinned_closed = validate_success(
        api.patch_capacity_control(
            window["id"], {"capacity_control_state": "CLOSED"}, PROGRAM_ADMIN
        ),
        200,
    )
    assert pinned_closed["capacity_control_state"] == "CLOSED", (
        "the hand pin moves the posture to CLOSED, "
        f"got {pinned_closed['capacity_control_state']!r}"
    )

    blocked = api.create_award_booking(
        {
            "member_id": member["id"],
            "window_id": window["id"],
            "travel_date": "2026-09-10",
            "seats": 1,
            "fare_class": "FLEX",
            "expected_window_version": pinned_closed["version"],
        },
        PROGRAM_ADMIN,
    )
    validate_error(blocked, "ERR_AWARD_WINDOW_CLOSED", 409)

    still_closed = read_window(window["id"])
    assert still_closed["seats_held"] == 0, (
        "the refused hold takes no seat, "
        f"got seats_held {still_closed['seats_held']}"
    )
    assert still_closed["load_factor_bps"] == 0, (
        "no seat is held or confirmed, so the load factor is zero, "
        f"got {still_closed['load_factor_bps']}"
    )

    pinned_open = validate_success(
        api.patch_capacity_control(
            window["id"], {"capacity_control_state": "OPEN"}, PROGRAM_ADMIN
        ),
        200,
    )
    assert pinned_open["capacity_control_state"] == "OPEN", (
        "a CLOSED window whose load factor is below 7500 may be reopened, "
        f"got {pinned_open['capacity_control_state']!r}"
    )

    booking = validate_success(
        api.create_award_booking(
            {
                "member_id": member["id"],
                "window_id": window["id"],
                "travel_date": "2026-09-10",
                "seats": 1,
                "fare_class": "FLEX",
                "expected_window_version": pinned_open["version"],
            },
            PROGRAM_ADMIN,
        ),
        201,
    )
    assert booking["quoted_miles"] == 22500, (
        "25000 chart miles at a 9000 bps demand multiplier for one seat, "
        f"got {booking['quoted_miles']}"
    )
    assert booking["demand_multiplier_bps_applied"] == 9000, (
        "an empty window prices on the lowest demand rung, "
        f"got {booking['demand_multiplier_bps_applied']}"
    )

    window_after = read_window(window["id"])
    assert window_after["seats_held"] == 1, (
        "the accepted hold takes exactly one seat, "
        f"got seats_held {window_after['seats_held']}"
    )
    assert window_after["capacity_control_state"] == "OPEN", (
        "one of ten seats held keeps the window OPEN, "
        f"got {window_after['capacity_control_state']!r}"
    )


def test_run_epoch_on_a_quiet_program_reports_every_counter_as_zero(api):
    """PRD §3.1: "A `ProgramAdmin` names a `program_id` and the system advances every clock-driven transition for that programme at the current logical-clock instant, reporting what it did: the `epoch_at` instant it ran at, plus counts named `holds_expired`, `campaigns_launched`, `campaigns_ended`, `status_matches_lapsed`, `notices_advanced`, `agreements_expired` and `windows_recomputed`."
    PRD §2.6: "At startup the clock reads exactly `2026-08-01T00:00:00Z`, and it never falls back to wall-clock time."
    PRD §2.7: "The transition out of `LOCKED` back to `OPEN` is also the only thing that advances `current_period`, which it does by exactly one calendar month."
    PRD §4: "Operations that bring a new resource into existence return `201 Created`; every other successful operation, including all state transitions, all posture changes, all reads and both test-driving utilities, returns `200 OK`."

    Design: Corner/endpoints/run_epoch_on_a_quiet_program_reports_every_counter_as_zero
    """
    program = create_program(name="SkyMiles Quiet")
    member = create_member(
        program["id"], external_member_ref="MBR-QUIET", home_region="AMER"
    )

    report = validate_success(api.run_epoch(program["id"], PROGRAM_ADMIN), 200)

    assert_epoch_report(report)
    assert report["holds_expired"] == 0, (
        f"no hold exists to expire, got holds_expired {report['holds_expired']}"
    )
    assert report["campaigns_launched"] == 0, (
        "no campaign exists to launch, "
        f"got campaigns_launched {report['campaigns_launched']}"
    )
    assert report["campaigns_ended"] == 0, (
        f"no campaign exists to end, got campaigns_ended {report['campaigns_ended']}"
    )
    assert report["status_matches_lapsed"] == 0, (
        "no status match trial exists to lapse, "
        f"got status_matches_lapsed {report['status_matches_lapsed']}"
    )
    assert report["notices_advanced"] == 0, (
        f"no notice exists to advance, got notices_advanced {report['notices_advanced']}"
    )
    assert report["agreements_expired"] == 0, (
        "no active agreement exists to expire, "
        f"got agreements_expired {report['agreements_expired']}"
    )
    assert report["windows_recomputed"] == 0, (
        "the programme owns no award inventory window, "
        f"got windows_recomputed {report['windows_recomputed']}"
    )
    assert is_iso8601_timestamp(report["epoch_at"]), (
        f"epoch_at is an ISO 8601 UTC instant, got {report['epoch_at']!r}"
    )
    assert report["epoch_at"].startswith("2026-08-01T00:00:00"), (
        "the sweep runs at the untouched startup instant of the logical clock, "
        f"got {report['epoch_at']!r}"
    )

    program_after = read_program(program["id"])
    assert program_after["current_period"] == "2026-08", (
        "only a LOCKED to OPEN transition advances current_period, "
        f"got {program_after['current_period']!r}"
    )
    assert program_after["revenue_recognition_state"] == "OPEN", (
        "the sweep does not touch the accounting posture, "
        f"got {program_after['revenue_recognition_state']!r}"
    )

    member_after = read_member(member["id"])
    assert member_after["status_match_state"] == "NONE", (
        "a member who never had a trial is untouched by the sweep, "
        f"got {member_after['status_match_state']!r}"
    )
    assert member_after["version"] == member["version"], (
        "the sweep touched no member row, so its version is unchanged: "
        f"expected {member['version']}, got {member_after['version']}"
    )


def test_high_reaction_notice_without_grandfathering_is_refused(api):
    """PRD §3.8: "The gate follows immediately: announcement is refused with `ERR_REACTION_RISK_EXCEEDED` when `member_reaction_index` is 70 or more **and** `grandfather_until` is null."
    PRD §3.8: "The threshold is inclusive, so an index of exactly 70 without grandfathering is blocked while the same index with grandfathering attached announces successfully."
    PRD §3.8: "The first ingredient is severity, taken from `change_type`: 40 points for `EARN_STRUCTURE`, 50 for `AWARD_PRICING`, 30 for `ELITE_THRESHOLD` and 20 for `EXPIRY_POLICY` — repricing awards angers members more than tightening expiry."
    PRD §3.8: "The second is a lead-time factor keyed by `notice_days` against inclusive lower bounds: 10000 basis points at 180 days or more, 12500 from 90 through 179 days, 15000 from 30 through 89 days, and 20000 below 30 days, so exactly 180, 90 or 30 days each take the kinder factor."
    PRD §3.8: "A drafted notice starts in `DRAFT` with `announced_at` null, `notice_days`, `exposed_member_count` and `member_reaction_index` all at zero, and `rollback_reason` null."

    Design: Corner/endpoints/high_reaction_notice_announces_only_when_grandfathering_is_attached
    """
    program = create_program(name="SkyMiles Notices")

    drafted = validate_success(
        api.create_program_change_notice(
            program_change_notice_payload(
                program["id"], "AWARD_PRICING", "2026-08-20T00:00:00Z",
                program["version"],
            ),
            PROGRAM_ADMIN,
        ),
        201,
    )
    assert_program_change_notice(drafted)
    assert drafted["status"] == "DRAFT", (
        f"a drafted notice starts in DRAFT, got {drafted['status']!r}"
    )
    assert drafted["announced_at"] is None, (
        f"a drafted notice has announced_at null, got {drafted['announced_at']!r}"
    )
    assert drafted["member_reaction_index"] == 0, (
        "a drafted notice carries a zero reaction index until announcement, "
        f"got {drafted['member_reaction_index']}"
    )
    assert drafted["grandfather_until"] is None, (
        "this notice deliberately attaches no grandfathering, "
        f"got {drafted['grandfather_until']!r}"
    )

    refused = api.announce_notice(drafted["id"], PROGRAM_ADMIN)
    validate_error(refused, "ERR_REACTION_RISK_EXCEEDED", 409)

    unchanged = validate_success(
        api.get_program_change_notice(drafted["id"], PROGRAM_ADMIN), 200
    )
    assert unchanged["status"] == "DRAFT", (
        "the refused announcement leaves the notice in DRAFT, "
        f"got {unchanged['status']!r}"
    )
    assert unchanged["announced_at"] is None, (
        "the refused announcement stamps nothing, "
        f"got announced_at {unchanged['announced_at']!r}"
    )


def test_high_reaction_notice_announces_when_grandfathering_is_attached(api):
    """PRD §3.8: "It requires `status` to be `DRAFT` and `effective_at` still to be in the future, stamps `announced_at` with the clock's now, and computes three derived figures."
    PRD §3.8: "`notice_days` is the whole number of days from `announced_at` to `effective_at`, taking the floor of the difference."
    PRD §3.8: "`exposed_member_count` is the number of member accounts in the programme whose `elite_tier` is anything other than `BASE` and whose `security_state` is either `NORMAL` or `WATCH`, snapshotted at announcement."
    PRD §3.8: "The third is grandfathering relief: 30 points when `grandfather_until` is at or after `effective_at` plus 365 days, 15 points when `grandfather_until` is at or after `effective_at` but earlier than that full year (so a `grandfather_until` exactly equal to `effective_at` still earns the partial 15), and 0 points when `grandfather_until` is null."
    PRD §3.8: "The fourth is exposure: an exposure factor of 10000 basis points plus 100 basis points for each exposed member, with that uplift capped at 5000 basis points — the cap saturating at 50 exposed members, beyond which the fifty-first exposed member does not move the index at all."
    PRD §3.8: "Severity is multiplied by the lead-time factor, divided by 10000, and rounded half up."
    PRD §3.8: "Relief points are subtracted from that product and the result is floored at zero — relief can therefore drive the pre-exposure term to zero, in which case the index is zero no matter how many members are exposed."
    PRD §3.8: "That floored term is then multiplied by the exposure factor, divided by 10000, rounded half up, and finally capped at 100 to give `member_reaction_index`."
    PRD §3.8: "A successful announcement moves `status` `DRAFT → ANNOUNCED`."

    Design: Corner/endpoints/high_reaction_notice_announces_only_when_grandfathering_is_attached
    """
    program = create_program(name="SkyMiles Notices")

    drafted = validate_success(
        api.create_program_change_notice(
            program_change_notice_payload(
                program["id"], "AWARD_PRICING", "2026-08-20T00:00:00Z",
                program["version"], grandfather_until="2026-08-25T00:00:00Z",
            ),
            PROGRAM_ADMIN,
        ),
        201,
    )

    announced = validate_success(
        api.announce_notice(drafted["id"], PROGRAM_ADMIN), 200
    )

    assert_program_change_notice(announced)
    assert announced["status"] == "ANNOUNCED", (
        f"a successful announcement moves DRAFT to ANNOUNCED, got {announced['status']!r}"
    )
    assert is_iso8601_timestamp(announced["announced_at"] or ""), (
        f"announced_at is stamped with the clock's now, got {announced['announced_at']!r}"
    )
    assert announced["notice_days"] == 19, (
        "the floor of the gap from 2026-08-01 to 2026-08-20 is 19 days, "
        f"got {announced['notice_days']}"
    )
    assert announced["exposed_member_count"] == 0, (
        "the programme holds no non-BASE member, "
        f"got exposed_member_count {announced['exposed_member_count']}"
    )
    assert announced["member_reaction_index"] == 85, (
        "severity 50 at the below-30-day factor of 20000 bps is 100, less 15 "
        "points of partial relief, at a neutral exposure factor, "
        f"got {announced['member_reaction_index']}"
    )


def test_reversal_transaction_links_to_the_row_it_undoes(api):
    """PRD §3.4: "Their `total_miles` is taken straight from the caller-supplied `base_miles` magnitude, which is always supplied non-negative, with the sign the type dictates: negative for `REDEEM`, `EXPIRY` and `ADJUSTMENT`, positive for `REVERSAL`."
    PRD §3.4: "On these rows `tier_bonus_miles`, `bonus_miles` and `qualifying_miles_credited` are all zero, `promo_multiplier_bps` stays at 10000 and `stacking_mode_applied` stays null."
    PRD §3.4: "Depending on type it also supplies `base_miles`, `qualifying_spend_cents` and `segments` (each defaulting to 0 and each required to be non-negative), and optionally `promotion_id`, `award_booking_id` and `reverses_transaction_id`."
    PRD §3.4: "Note that `lifetime_miles` counts only the three earning types, whereas `mile_balance` and `outstanding_miles` sum every type with its sign, and `mile_balance` is never negative."
    PRD §2.3: "Mile ledger rows filter by `member_id`, `promotion_id`, `award_booking_id`, `reverses_transaction_id` and `txn_type`."

    Design: Corner/endpoints/reversal_transaction_links_to_the_row_it_undoes
    """
    program = create_program(name="SkyMiles Reversal")
    member = create_member(
        program["id"], external_member_ref="MBR-REV", home_region="AMER"
    )
    validate_success(
        api.create_mile_transaction(
            {
                "member_id": member["id"],
                "txn_type": "PARTNER_EARN",
                "activity_date": "2026-07-15",
                "base_miles": 10000,
            },
            REVENUE_ACCOUNTANT,
        ),
        201,
    )
    redeem = validate_success(
        api.create_mile_transaction(
            {
                "member_id": member["id"],
                "txn_type": "REDEEM",
                "activity_date": "2026-07-20",
                "base_miles": 4000,
            },
            REVENUE_ACCOUNTANT,
        ),
        201,
    )
    assert redeem["total_miles"] == -4000, (
        f"a REDEEM row carries a negative total_miles, got {redeem['total_miles']}"
    )

    reversal = validate_success(
        api.create_mile_transaction(
            {
                "member_id": member["id"],
                "txn_type": "REVERSAL",
                "activity_date": "2026-07-25",
                "base_miles": 4000,
                "reverses_transaction_id": redeem["id"],
            },
            REVENUE_ACCOUNTANT,
        ),
        201,
    )

    assert reversal["total_miles"] == 4000, (
        f"a REVERSAL row carries a positive total_miles, got {reversal['total_miles']}"
    )
    assert reversal["reverses_transaction_id"] == redeem["id"], (
        "the reversal names the row it undoes, "
        f"got {reversal['reverses_transaction_id']!r}"
    )
    assert reversal["tier_bonus_miles"] == 0, (
        f"a non-earning row awards no tier bonus, got {reversal['tier_bonus_miles']}"
    )
    assert reversal["bonus_miles"] == 0, (
        f"a non-earning row awards no promotional bonus, got {reversal['bonus_miles']}"
    )
    assert reversal["qualifying_miles_credited"] == 0, (
        "a non-earning row credits no qualifying miles, "
        f"got {reversal['qualifying_miles_credited']}"
    )
    assert reversal["promo_multiplier_bps"] == 10000, (
        "a non-earning row keeps a neutral multiplier, "
        f"got {reversal['promo_multiplier_bps']}"
    )
    assert reversal["stacking_mode_applied"] is None, (
        "a non-earning row applies no stacking mode, "
        f"got {reversal['stacking_mode_applied']!r}"
    )

    member_after = read_member(member["id"])
    assert member_after["mile_balance"] == 10000, (
        "10000 earned less 4000 redeemed plus 4000 reversed, "
        f"got mile_balance {member_after['mile_balance']}"
    )
    assert member_after["lifetime_miles"] == 10000, (
        "lifetime_miles counts only the earning row, "
        f"got {member_after['lifetime_miles']}"
    )

    program_after = read_program(program["id"])
    assert program_after["outstanding_miles"] == 10000, (
        "outstanding_miles sums every row with its sign, "
        f"got {program_after['outstanding_miles']}"
    )

    _, reverse_meta = validate_paginated(
        api.list_mile_transactions(
            REVENUE_ACCOUNTANT, params={"reverses_transaction_id": redeem["id"]}
        )
    )
    assert reverse_meta["total_count"] == 1, (
        "exactly one row names the redemption it undoes, "
        f"got total_count {reverse_meta['total_count']}"
    )

    _, member_meta = validate_paginated(
        api.list_mile_transactions(
            REVENUE_ACCOUNTANT, params={"member_id": member["id"]}
        )
    )
    assert member_meta["total_count"] == 3, (
        "the member's ledger holds the earn, the redemption and the reversal, "
        f"got total_count {member_meta['total_count']}"
    )
