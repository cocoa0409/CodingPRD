"""Entity creation, stored projections and the field-level contract.

Each test drives the real endpoints from an empty database and checks the
server-minted, server-computed and server-defaulted fields the PRD names.
"""
from test_helpers import (
    NON_EXISTENT_UUID,
    PARTNER_MANAGER,
    PROGRAM_ADMIN,
    REVENUE_ACCOUNTANT,
    assert_award_booking,
    assert_award_inventory_window,
    assert_co_brand_issuer,
    assert_deferred_revenue_posting,
    assert_loyalty_program,
    assert_member_account,
    assert_mile_transaction,
    assert_promotion_campaign,
    co_brand_issuer_payload,
    create_member,
    create_posting,
    create_program,
    create_window,
    grant_status_match,
    is_valid_uuid,
    mile_sale_agreement_payload,
    post_transaction,
    promotion_campaign_payload,
    read_member,
    read_window,
    tier_schedule,
    transition_recognition,
    validate_error,
    validate_paginated,
    validate_success,
)


# --------------------------------------------------------------------------- #
# Creation
# --------------------------------------------------------------------------- #
def test_co_brand_issuer_creation_returns_zeroed_aggregate_and_active_posture(api):
    """PRD §3.1: "A **co-brand issuer** is created by a `ProgramAdmin` or a `PartnerManager` with a `program_id`, a non-empty legal `name`, and an `annual_mile_purchase_cap_miles` of at least one mile, which is the hard ceiling on miles the issuer may commit to across all its ratified and active agreements."
    PRD §3.1: "Its `aggregate_committed_miles` starts at zero and is thereafter defined as the sum of `committed_volume_miles` over this issuer's agreements whose `status` is `RATIFIED` or `ACTIVE`, recomputed whenever an agreement of that issuer is ratified, activated, terminated or expired."
    PRD §3.1: "Its trading posture lives in `status`, which starts `ACTIVE` and may become `SUSPENDED`, paired with a `suspension_reason` that starts `NONE` and becomes `CAP_BREACH` when suspension is automatic."
    PRD §2.4: "Every resource in the system carries an `id`: a server-minted UUID with no type prefix and no client control over its value."

    Design: Corner/entities/co_brand_issuer_creation_returns_all_fields_with_zeroed_aggregate
    """
    program = create_program(name="SkyMiles Corner")

    response = api.create_co_brand_issuer(
        co_brand_issuer_payload(
            program["id"],
            name="Northbank Card Services",
            annual_mile_purchase_cap_miles=20000000,
        ),
        PARTNER_MANAGER,
    )

    issuer = validate_success(response, 201)
    assert_co_brand_issuer(issuer)
    assert issuer["aggregate_committed_miles"] == 0, (
        "a freshly registered issuer's aggregate_committed_miles starts at zero, "
        f"got {issuer['aggregate_committed_miles']}"
    )
    assert issuer["status"] == "ACTIVE", (
        f"a freshly registered issuer starts ACTIVE, got {issuer['status']}"
    )
    assert issuer["suspension_reason"] == "NONE", (
        "a freshly registered issuer's suspension_reason starts NONE, "
        f"got {issuer['suspension_reason']}"
    )
    assert issuer["annual_mile_purchase_cap_miles"] == 20000000, (
        "annual_mile_purchase_cap_miles echoes the supplied cap, "
        f"got {issuer['annual_mile_purchase_cap_miles']}"
    )
    assert is_valid_uuid(issuer["id"]) and "_" not in issuer["id"], (
        f"the issuer id is a bare server-minted UUID, got {issuer['id']!r}"
    )


def test_loyalty_program_create_applies_every_declared_default(api):
    """PRD §3.1: "When omitted, `currency_code` is `USD`, `current_period` is `2026-08`, `breakage_policy_mode` is `HISTORICAL_ATTRITION` (the alternative being `FORWARD_EXPECTATION`), and `saver_share_default_bps` is 3000 — thirty percent of authorised seats — which must lie between 0 and 10000 inclusive."
    PRD §3.1: "A fresh programme starts with `revenue_recognition_state` at `OPEN` and all four of its ledger counters at zero: `outstanding_miles`, `deferred_revenue_cents`, `last_breakage_rate_bps` and `lifetime_breakage_income_cents`."

    Design: Corner/entities/loyalty_program_create_applies_every_declared_default
    """
    response = api.create_loyalty_program({"name": "SkyMiles Defaults"}, PROGRAM_ADMIN)

    program = validate_success(response, 201)
    assert_loyalty_program(program)
    assert program["currency_code"] == "USD", (
        f"currency_code defaults to USD, got {program['currency_code']!r}"
    )
    assert program["current_period"] == "2026-08", (
        f"current_period defaults to 2026-08, got {program['current_period']!r}"
    )
    assert program["breakage_policy_mode"] == "HISTORICAL_ATTRITION", (
        "breakage_policy_mode defaults to HISTORICAL_ATTRITION, "
        f"got {program['breakage_policy_mode']!r}"
    )
    assert program["saver_share_default_bps"] == 3000, (
        "saver_share_default_bps defaults to 3000 basis points, "
        f"got {program['saver_share_default_bps']}"
    )
    assert program["revenue_recognition_state"] == "OPEN", (
        "a fresh programme starts OPEN, "
        f"got {program['revenue_recognition_state']!r}"
    )
    assert program["outstanding_miles"] == 0, (
        f"outstanding_miles starts at zero, got {program['outstanding_miles']}"
    )
    assert program["deferred_revenue_cents"] == 0, (
        f"deferred_revenue_cents starts at zero, got {program['deferred_revenue_cents']}"
    )
    assert program["last_breakage_rate_bps"] == 0, (
        f"last_breakage_rate_bps starts at zero, got {program['last_breakage_rate_bps']}"
    )
    assert program["lifetime_breakage_income_cents"] == 0, (
        "lifetime_breakage_income_cents starts at zero, "
        f"got {program['lifetime_breakage_income_cents']}"
    )


# --------------------------------------------------------------------------- #
# Retrieval and listing
# --------------------------------------------------------------------------- #
def test_member_account_retrieval_returns_stored_projection(api):
    """PRD §3.4: "Two optional inputs seed the qualification cycle: `cycle_year`, the elite qualification cycle currently accumulating, which defaults to 2026, and `rollover_carried_in`, qualifying miles banked from the prior cycle, which defaults to 0 and counts toward tier evaluation."
    PRD §3.4: "A new account opens at `elite_tier` `BASE`, `security_state` `NORMAL`, `status_match_state` `NONE` and `qualification_state` `ACCUMULATING`, with `status_match_tier` and `status_match_expires_at` null, `awarded_tier_at_close` null, and `qualifying_miles_ytd`, `qualifying_segments_ytd`, `qualifying_spend_cents_ytd`, `rollover_carried_out`, `mile_balance`, `lifetime_miles` and `risk_score` all at zero."

    Design: Corner/entities/member_account_retrieval_returns_stored_projection
    """
    program = create_program(name="SkyMiles Read")
    member = create_member(
        program["id"],
        external_member_ref="MBR-READ",
        home_region="EMEA",
        cycle_year=2026,
        rollover_carried_in=12000,
    )

    read = validate_success(api.get_member_account(member["id"], PROGRAM_ADMIN), 200)

    assert_member_account(read)
    assert read["rollover_carried_in"] == 12000, (
        "the read projects the stored rollover_carried_in verbatim, "
        f"got {read['rollover_carried_in']}"
    )
    assert read["elite_tier"] == "BASE", (
        f"a new account opens at elite_tier BASE, got {read['elite_tier']!r}"
    )
    assert read["security_state"] == "NORMAL", (
        f"a new account opens at security_state NORMAL, got {read['security_state']!r}"
    )
    assert read["status_match_state"] == "NONE", (
        "a new account opens at status_match_state NONE, "
        f"got {read['status_match_state']!r}"
    )
    assert read["qualification_state"] == "ACCUMULATING", (
        "a new account opens at qualification_state ACCUMULATING, "
        f"got {read['qualification_state']!r}"
    )
    assert read["mile_balance"] == 0, (
        f"a new account opens with mile_balance zero, got {read['mile_balance']}"
    )
    assert read["qualifying_miles_ytd"] == 0, (
        "a new account opens with qualifying_miles_ytd zero, "
        f"got {read['qualifying_miles_ytd']}"
    )
    assert read["rollover_carried_out"] == 0, (
        "a new account opens with rollover_carried_out zero, "
        f"got {read['rollover_carried_out']}"
    )
    assert read["awarded_tier_at_close"] is None, (
        "a new account opens with awarded_tier_at_close null, "
        f"got {read['awarded_tier_at_close']!r}"
    )


def test_mile_transaction_listing_paginates_with_total_count_and_has_more(api):
    """PRD §2.3: "Every list response carries `limit`, `offset`, `total_count` and `has_more` inside the `meta` object of the envelope, where `total_count` counts the rows matching the filters before pagination is applied and `has_more` states whether any matching row remains beyond the current page."
    PRD §2.3: "Mile ledger rows filter by `member_id`, `promotion_id`, `award_booking_id`, `reverses_transaction_id` and `txn_type`."
    PRD §3.4: "Note that `lifetime_miles` counts only the three earning types, whereas `mile_balance` and `outstanding_miles` sum every type with its sign, and `mile_balance` is never negative."

    Design: Corner/entities/mile_transaction_listing_paginates_with_total_count_and_has_more
    """
    program = create_program(name="SkyMiles Paging")
    member = create_member(
        program["id"], external_member_ref="MBR-PAGE", home_region="APAC"
    )
    post_transaction(
        member["id"], "PARTNER_EARN", "2026-07-10",
        headers=REVENUE_ACCOUNTANT, base_miles=1000,
    )
    post_transaction(
        member["id"], "PARTNER_EARN", "2026-07-10",
        headers=REVENUE_ACCOUNTANT, base_miles=2000,
    )
    post_transaction(
        member["id"], "REDEEM", "2026-07-10",
        headers=REVENUE_ACCOUNTANT, base_miles=500,
    )

    first_rows, first_meta = validate_paginated(
        api.list_mile_transactions(
            REVENUE_ACCOUNTANT,
            params={"member_id": member["id"], "limit": 2, "offset": 0},
        )
    )
    second_rows, second_meta = validate_paginated(
        api.list_mile_transactions(
            REVENUE_ACCOUNTANT,
            params={"member_id": member["id"], "limit": 2, "offset": 2},
        )
    )

    assert first_meta["total_count"] == 3, (
        "total_count counts every row matching member_id before pagination, "
        f"got {first_meta['total_count']}"
    )
    assert first_meta["has_more"] is True, (
        "has_more is true while a third matching row remains beyond page one"
    )
    assert len(first_rows) == 2, (
        f"limit=2 returns exactly two rows, got {len(first_rows)}"
    )
    assert second_meta["total_count"] == 3, (
        "total_count is unchanged by the offset, "
        f"got {second_meta['total_count']}"
    )
    assert second_meta["has_more"] is False, (
        "has_more is false once the last matching row has been returned"
    )
    assert len(second_rows) == 1, (
        f"offset=2 of three rows returns exactly one row, got {len(second_rows)}"
    )

    member_after = read_member(member["id"])
    assert member_after["mile_balance"] == 2500, (
        "mile_balance sums every type with its sign: 1000 + 2000 - 500, "
        f"got {member_after['mile_balance']}"
    )

    _, earn_meta = validate_paginated(
        api.list_mile_transactions(
            REVENUE_ACCOUNTANT,
            params={"member_id": member["id"], "txn_type": "PARTNER_EARN"},
        )
    )
    assert earn_meta["total_count"] == 2, (
        "the txn_type filter narrows the ledger to the two PARTNER_EARN rows, "
        f"got {earn_meta['total_count']}"
    )


def test_award_booking_get_with_unknown_id_returns_booking_not_found(api):
    """PRD §2.9: "Every path-parameter identifier resolves to an existing row, checked left to right along the path — otherwise the 404 not-found code for the first identifier that fails to resolve."
    PRD §2.11: "Each identifier has its own not-found code: `programId` yields `ERR_PROGRAM_NOT_FOUND`, `issuerId` yields `ERR_ISSUER_NOT_FOUND`, `agreementId` yields `ERR_AGREEMENT_NOT_FOUND`, `orderId` yields `ERR_ORDER_NOT_FOUND`, `memberId` yields `ERR_MEMBER_NOT_FOUND`, `transactionId` yields `ERR_TRANSACTION_NOT_FOUND`, `campaignId` yields `ERR_PROMOTION_NOT_FOUND`, `windowId` yields `ERR_AWARD_WINDOW_NOT_FOUND`, `bookingId` yields `ERR_BOOKING_NOT_FOUND`, `airlineId` yields `ERR_PARTNER_NOT_FOUND`, `noticeId` yields `ERR_NOTICE_NOT_FOUND`, `caseId` yields `ERR_FRAUD_CASE_NOT_FOUND`, and `postingId` yields `ERR_POSTING_NOT_FOUND`."
    PRD §2.2: "The `message` provides a human-readable explanation of what went wrong."

    Design: Corner/entities/award_booking_get_with_unknown_id_returns_booking_not_found
    """
    create_program(name="SkyMiles NotFound")

    response = api.get_award_booking(NON_EXISTENT_UUID, PROGRAM_ADMIN)

    error = validate_error(response, "ERR_BOOKING_NOT_FOUND", 404)
    assert error["message"].strip(), (
        "the error body carries a human-readable message alongside the error_id"
    )
    assert response.json()["response_type"] == "error", (
        "a failure response declares response_type 'error'"
    )

    _, meta = validate_paginated(api.list_award_bookings(PROGRAM_ADMIN))
    assert meta["total_count"] == 0, (
        f"no award booking exists at all, got total_count {meta['total_count']}"
    )


# --------------------------------------------------------------------------- #
# Request-body validation
# --------------------------------------------------------------------------- #
def test_promotion_campaign_create_missing_stacking_mode_returns_invalid_request(api):
    """PRD §3.4: "A `ProgramAdmin` schedules one under a `program_id` with a `code` unique within that programme, an `earn_channel` of `FLIGHT`, `CARD_SPEND` or `PARTNER`, a `multiplier_bps` of at least 10000 and at most 50000 (from a neutral one-times factor up to five times), a `stacking_mode` of `EXCLUSIVE`, `ADDITIVE` or `MULTIPLICATIVE`, and the window as `window_start` (inclusive) and `window_end` (exclusive)."
    PRD §2.9: "The request body is well formed: required fields present, enumerated fields within their declared value sets, integers within their declared bounds, dates and instants in ISO 8601 form, and `tier_schedule` shaped as an array of objects each carrying `threshold_miles` and `price_per_mile_centicents` whose first entry has a `threshold_miles` of 0, whose `threshold_miles` values strictly increase, and whose `price_per_mile_centicents` values strictly decrease."
    PRD §2.9: "Violations yield `ERR_INVALID_REQUEST` (400)."

    Design: Corner/entities/promotion_campaign_create_missing_stacking_mode_returns_invalid_request
    """
    program = create_program(name="SkyMiles Required")

    response = api.create_promotion_campaign(
        {
            "program_id": program["id"],
            "code": "NO-STACKING",
            "earn_channel": "FLIGHT",
            "multiplier_bps": 15000,
            "window_start": "2026-09-01T00:00:00Z",
            "window_end": "2026-10-01T00:00:00Z",
        },
        PROGRAM_ADMIN,
    )

    validate_error(response, "ERR_INVALID_REQUEST", 400)

    _, meta = validate_paginated(
        api.list_promotion_campaigns(
            PROGRAM_ADMIN, params={"program_id": program["id"]}
        )
    )
    assert meta["total_count"] == 0, (
        "a rejected create leaves no campaign behind, "
        f"got total_count {meta['total_count']}"
    )


def test_promotion_multiplier_above_maximum_is_rejected_as_invalid_request(api):
    """PRD §3.4: "A `ProgramAdmin` schedules one under a `program_id` with a `code` unique within that programme, an `earn_channel` of `FLIGHT`, `CARD_SPEND` or `PARTNER`, a `multiplier_bps` of at least 10000 and at most 50000 (from a neutral one-times factor up to five times), a `stacking_mode` of `EXCLUSIVE`, `ADDITIVE` or `MULTIPLICATIVE`, and the window as `window_start` (inclusive) and `window_end` (exclusive)."
    PRD §2.9: "Violations yield `ERR_INVALID_REQUEST` (400)."
    PRD §3.4: "An optional `bonus_cap_miles` of at least zero caps the programme-wide bonus the campaign may ever award; when null the campaign is unbounded."
    PRD §3.4: "`accrued_bonus_miles` starts at zero and is thereafter the sum of `bonus_miles` across every ledger row whose `promotion_id` names this campaign."
    PRD §3.4: "A campaign's `status` begins at `SCHEDULED`."

    Design: Corner/entities/promotion_multiplier_above_maximum_is_rejected_as_invalid_request
    """
    program = create_program(name="SkyMiles Bounds")

    over_max = api.create_promotion_campaign(
        promotion_campaign_payload(
            program["id"],
            code="OVER-MAX",
            multiplier_bps=50001,
            window_start="2026-09-01T00:00:00Z",
            window_end="2026-10-01T00:00:00Z",
        ),
        PROGRAM_ADMIN,
    )
    validate_error(over_max, "ERR_INVALID_REQUEST", 400)

    at_max = api.create_promotion_campaign(
        promotion_campaign_payload(
            program["id"],
            code="AT-MAX",
            multiplier_bps=50000,
            window_start="2026-09-01T00:00:00Z",
            window_end="2026-10-01T00:00:00Z",
        ),
        PROGRAM_ADMIN,
    )
    campaign = validate_success(at_max, 201)

    assert_promotion_campaign(campaign)
    assert campaign["multiplier_bps"] == 50000, (
        "the declared maximum of 50000 basis points is accepted inclusively, "
        f"got {campaign['multiplier_bps']}"
    )
    assert campaign["status"] == "SCHEDULED", (
        f"a new campaign begins at SCHEDULED, got {campaign['status']!r}"
    )
    assert campaign["accrued_bonus_miles"] == 0, (
        f"accrued_bonus_miles starts at zero, got {campaign['accrued_bonus_miles']}"
    )
    assert campaign["bonus_cap_miles"] is None, (
        "an omitted bonus_cap_miles leaves the campaign unbounded, "
        f"got {campaign['bonus_cap_miles']!r}"
    )

    _, meta = validate_paginated(
        api.list_promotion_campaigns(
            PROGRAM_ADMIN, params={"program_id": program["id"]}
        )
    )
    assert meta["total_count"] == 1, (
        "only the accepted campaign was persisted, "
        f"got total_count {meta['total_count']}"
    )


def test_agreement_create_with_unknown_issuer_returns_issuer_not_found(api):
    """PRD §2.9: "Checks are evaluated in ascending order, and **the first check that fails is the response** — no later check runs, and no partial mutation is retained."
    PRD §2.9: "Every foreign key supplied in the request body resolves to an existing row, checked in the order the fields are declared for that operation — otherwise the corresponding 404 not-found code."
    PRD §2.11: "The same codes serve body-supplied foreign keys, which are resolved in the order the fields are declared for the operation: `program_id` resolves to a programme, `issuer_id` to an issuer, `agreement_id` and `supersedes_agreement_id` to agreements, `member_id` to a member account, `reverses_transaction_id` to a mile ledger row, `promotion_id` to a campaign, `window_id` to an award inventory window, `award_booking_id` to an award booking, and `partner_airline_id` to a partner airline."

    Design: Corner/entities/agreement_create_with_unknown_issuer_returns_issuer_not_found
    """
    create_program(name="SkyMiles FK")

    response = api.create_mile_sale_agreement(
        mile_sale_agreement_payload(
            NON_EXISTENT_UUID,
            term_start_date="2026-09-01",
            term_end_date="2026-09-11",
            committed_volume_miles=1000000,
            tier_schedule=tier_schedule((0, 160)),
        ),
        PARTNER_MANAGER,
    )

    error = validate_error(response, "ERR_ISSUER_NOT_FOUND", 404)
    assert error["error_id"] != "ERR_INVALID_TERM", (
        "the body foreign key is resolved before the term-length rung, so the "
        "deliberately too-short 10-day term must not surface as ERR_INVALID_TERM"
    )
    assert response.status_code == 404, (
        f"an unresolvable issuer_id answers 404, got {response.status_code}"
    )

    _, meta = validate_paginated(api.list_mile_sale_agreements(PARTNER_MANAGER))
    assert meta["total_count"] == 0, (
        "a rejected draft retains no partial mutation, "
        f"got total_count {meta['total_count']}"
    )


def test_cross_program_booking_reference_is_rejected(api):
    """PRD §2.9: "Every cross-entity reference in one request belongs to the same loyalty programme — the member, the window, the partner airline, the campaign, the notice and the posting must all share one `program_id` — otherwise `ERR_CROSS_PROGRAM_REFERENCE` (422)."
    PRD §2.9: "Applies to creating an award booking and to posting a mile ledger row."
    PRD §2.11: "The system is multi-tenant by programme, and no request may combine rows belonging to two different programmes — a booking whose member and window sit in different programmes, or a ledger row whose member and campaign do, is rejected with `ERR_CROSS_PROGRAM_REFERENCE`."

    Design: Corner/entities/cross_program_booking_reference_is_rejected
    """
    program_one = create_program(name="SkyMiles P1")
    program_two = create_program(name="SkyMiles P2")
    member = create_member(
        program_one["id"], external_member_ref="MBR-P1", home_region="AMER"
    )
    window = create_window(
        program_two["id"],
        route_code="JFK-NRT",
        cabin="BUSINESS",
        window_start_date="2026-09-01",
        window_end_date="2026-09-30",
        authorized_seats=10,
    )

    response = api.create_award_booking(
        {
            "member_id": member["id"],
            "window_id": window["id"],
            "travel_date": "2026-09-15",
            "seats": 1,
            "fare_class": "FLEX",
            "expected_window_version": window["version"],
        },
        PROGRAM_ADMIN,
    )

    validate_error(response, "ERR_CROSS_PROGRAM_REFERENCE", 422)

    window_after = read_window(window["id"])
    assert window_after["seats_held"] == 0, (
        "the rejected hold seizes no seat, "
        f"got seats_held {window_after['seats_held']}"
    )
    assert window_after["version"] == window["version"], (
        "no partial mutation is retained, so the window version is untouched: "
        f"expected {window['version']}, got {window_after['version']}"
    )

    _, meta = validate_paginated(
        api.list_award_bookings(PROGRAM_ADMIN, params={"member_id": member["id"]})
    )
    assert meta["total_count"] == 0, (
        f"no booking was created, got total_count {meta['total_count']}"
    )


# --------------------------------------------------------------------------- #
# Computed fields
# --------------------------------------------------------------------------- #
def test_award_hold_is_priced_off_the_pre_booking_load_factor(api):
    """PRD §3.5: "The window's occupancy is measured *before* the requested seats are added: `seats_held` plus `seats_confirmed`, multiplied by 10000, divided by `authorized_seats`, rounded half up — and zero when `authorized_seats` is zero, which short-circuits rather than dividing by zero."
    PRD §3.5: "That pre-booking load factor selects `demand_multiplier_bps_applied` from a four-rung ladder whose lower bounds are inclusive: 9000 basis points below 5000, 10000 from 5000 through 7499, 12500 from 7500 through 8999, and 16000 at 9000 and above."
    PRD §3.5: "`chart_miles_per_seat` is read from the award chart by the window's `cabin` and the requested `fare_class`: `ECONOMY` charges 12500 at `SAVER` and 25000 at `FLEX`; `PREMIUM` charges 25000 and 45000; `BUSINESS` charges 50000 and 85000; `FIRST` charges 90000 and 140000."
    PRD §3.5: "`partner_uplift_bps_applied` is 10000 for own-metal awards, meaning a null `partner_airline_id`."
    PRD §3.5: "The gross award miles per seat are `chart_miles_per_seat` multiplied by `demand_multiplier_bps_applied` and by `partner_uplift_bps_applied`, divided by 100000000 (that is, both basis-point factors converted to plain multipliers), rounded half up."
    PRD §3.5: "`surcharge_band` is keyed by that gross per-seat figure, pre-discount, against inclusive lower bounds: `SURCHARGE_LOW` below 25000 gross miles, `SURCHARGE_MID` from 25000 through 74999, and `SURCHARGE_HIGH` at 75000 and above, so a gross of exactly 25000 or exactly 75000 takes the higher band."
    PRD §3.5: "The band also fixes the cash side: `cash_surcharge_cents` is 560 cents per seat at `SURCHARGE_LOW`, 1120 at `SURCHARGE_MID` and 2240 at `SURCHARGE_HIGH`, multiplied by `seats`."
    PRD §3.5: "A `BASE` member receives no discount in any band."
    PRD §3.5: "`quoted_miles` is then the gross per-seat figure multiplied by the quantity (10000 minus `elite_discount_bps_applied`), divided by 10000, rounded half up **per seat**, and only then multiplied by `seats`."
    PRD §3.5: "`partner_settlement_cents` is zero for own metal and otherwise `quoted_miles` multiplied by the partner's `settlement_rate_centicents_per_mile`, divided by 100, rounded half up."

    Design: Corner/entities/award_window_load_factor_and_demand_multiplier_computed_from_seat_movement
    """
    program = create_program(name="SkyMiles Computed")
    member = create_member(
        program["id"], external_member_ref="MBR-COMP", home_region="AMER"
    )
    window = create_window(
        program["id"],
        route_code="JFK-CDG",
        cabin="ECONOMY",
        window_start_date="2026-09-01",
        window_end_date="2026-09-30",
        authorized_seats=10,
    )

    booking = validate_success(
        api.create_award_booking(
            {
                "member_id": member["id"],
                "window_id": window["id"],
                "travel_date": "2026-09-20",
                "seats": 4,
                "fare_class": "FLEX",
                "expected_window_version": window["version"],
            },
            PROGRAM_ADMIN,
        ),
        201,
    )

    assert_award_booking(booking)
    assert booking["chart_miles_per_seat"] == 25000, (
        "an ECONOMY FLEX award charges 25000 chart miles per seat, "
        f"got {booking['chart_miles_per_seat']}"
    )
    assert booking["demand_multiplier_bps_applied"] == 9000, (
        "a pre-booking load factor of 0 sits on the lowest rung at 9000 bps, "
        f"got {booking['demand_multiplier_bps_applied']}"
    )
    assert booking["partner_uplift_bps_applied"] == 10000, (
        "an own-metal award carries a neutral 10000 bps uplift, "
        f"got {booking['partner_uplift_bps_applied']}"
    )
    assert booking["quoted_miles"] == 90000, (
        "22500 gross miles per seat at no elite discount times four seats, "
        f"got {booking['quoted_miles']}"
    )
    assert booking["surcharge_band"] == "SURCHARGE_LOW", (
        "a gross of 22500 per seat sits below 25000, so the band is SURCHARGE_LOW, "
        f"got {booking['surcharge_band']!r}"
    )
    assert booking["cash_surcharge_cents"] == 2240, (
        "560 cents per seat at SURCHARGE_LOW times four seats, "
        f"got {booking['cash_surcharge_cents']}"
    )
    assert booking["partner_settlement_cents"] == 0, (
        "an own-metal award settles nothing to a partner, "
        f"got {booking['partner_settlement_cents']}"
    )


def test_award_window_load_factor_and_demand_multiplier_recompute_on_the_hold(api):
    """PRD §3.5: "The window's `seats_held` increases by `seats`, and for a `SAVER` booking `saver_seats_consumed` increases by `seats` as well; `load_factor_bps`, `demand_multiplier_bps` and `capacity_control_state` are then recomputed and the window's `version` increments."
    PRD §3.5: "`load_factor_bps` is `seats_held` plus `seats_confirmed`, multiplied by 10000, divided by `authorized_seats`, rounded half up, and defined as zero when `authorized_seats` is zero."
    PRD §3.5: "`capacity_control_state` then follows from it against two inclusive lower bounds: a load factor below 7500 basis points (75% sold) is `OPEN`, a load factor from 7500 through 9999 is `CONSTRAINED`, and a load factor of 10000 or more is `CLOSED`."
    PRD §3.5: "A fresh window starts with `seats_held`, `seats_confirmed` and `saver_seats_consumed` at zero, `load_factor_bps` at zero, `capacity_control_state` at `OPEN`, and `demand_multiplier_bps` seeded at 9000 — the rung an empty window occupies on the demand ladder."

    Design: Corner/entities/award_window_load_factor_and_demand_multiplier_computed_from_seat_movement
    """
    program = create_program(name="SkyMiles Computed")
    member = create_member(
        program["id"], external_member_ref="MBR-COMP", home_region="AMER"
    )
    window = create_window(
        program["id"],
        route_code="JFK-CDG",
        cabin="ECONOMY",
        window_start_date="2026-09-01",
        window_end_date="2026-09-30",
        authorized_seats=10,
    )
    assert window["load_factor_bps"] == 0, (
        f"a fresh window opens at load_factor_bps zero, got {window['load_factor_bps']}"
    )

    validate_success(
        api.create_award_booking(
            {
                "member_id": member["id"],
                "window_id": window["id"],
                "travel_date": "2026-09-20",
                "seats": 4,
                "fare_class": "FLEX",
                "expected_window_version": window["version"],
            },
            PROGRAM_ADMIN,
        ),
        201,
    )

    window_after = read_window(window["id"])
    assert_award_inventory_window(window_after)
    assert window_after["seats_held"] == 4, (
        f"the four held seats land on seats_held, got {window_after['seats_held']}"
    )
    assert window_after["seats_confirmed"] == 0, (
        "a hold confirms nothing, "
        f"got seats_confirmed {window_after['seats_confirmed']}"
    )
    assert window_after["load_factor_bps"] == 4000, (
        "four of ten authorised seats is 4000 basis points, "
        f"got {window_after['load_factor_bps']}"
    )
    assert window_after["demand_multiplier_bps"] == 9000, (
        "a load factor of 4000 sits below 5000, so the window rung stays 9000, "
        f"got {window_after['demand_multiplier_bps']}"
    )
    assert window_after["capacity_control_state"] == "OPEN", (
        "a load factor below 7500 basis points is OPEN, "
        f"got {window_after['capacity_control_state']!r}"
    )


# --------------------------------------------------------------------------- #
# System-stamped fields
# --------------------------------------------------------------------------- #
def test_mile_transaction_system_fields_stamp_period_and_tier_snapshot(api):
    """PRD §3.4: "Every row records `elite_tier_at_earn`, a snapshot of the member's `elite_tier` at insert time, and `posted_period`, a snapshot of the programme's `current_period`."
    PRD §3.6: "The grant moves `status_match_state` `NONE → TRIAL`, sets both `elite_tier` and `status_match_tier` to `matched_tier`, and sets `status_match_expires_at` to the logical clock's now plus `trial_days` days."
    PRD §3.4: "**Second**, the elite tier bonus is computed: the tier bonus rate is 0 basis points at `BASE`, 2500 at `SILVER`, 5000 at `GOLD` and 10000 at `PLATINUM`, so a platinum member's bonus doubles their base, and `tier_bonus_miles` is the base multiplied by that rate divided by 10000, rounded half up."
    PRD §3.4: "**Third**, the promotional multiplier is resolved: when no `promotion_id` is supplied, `promo_multiplier_bps` is 10000 (a neutral one-times factor) and `stacking_mode_applied` is null; when one is supplied, `promo_multiplier_bps` takes the campaign's `multiplier_bps` and `stacking_mode_applied` takes the campaign's `stacking_mode`."
    PRD §3.4: "With no promotion at all, the gross total is simply the base plus `tier_bonus_miles`."
    PRD §3.4: "The raw bonus is the gross total minus the base minus `tier_bonus_miles`, floored at zero."
    PRD §3.4: "**Sixth**, `total_miles` is the base plus `tier_bonus_miles` plus `bonus_miles`."
    PRD §3.4: "**Seventh**, elite-qualifying credit is computed entirely independently of every multiplier above: a `FLIGHT_EARN` row credits `qualifying_miles_credited` equal to its base and adds the supplied `segments` to the member's `qualifying_segments_ytd`; a `CARD_SPEND_EARN` row credits the lesser of its base and a per-transaction cap of 15000 qualifying miles, and adds the supplied `qualifying_spend_cents` to the member's `qualifying_spend_cents_ytd`; a `PARTNER_EARN` row credits zero qualifying miles."

    Design: Corner/entities/mile_transaction_system_fields_stamp_period_and_tier_snapshot
    """
    program = create_program(name="SkyMiles System")
    member = create_member(
        program["id"], external_member_ref="MBR-SYS", home_region="AMER"
    )
    matched = grant_status_match(member["id"], "GOLD", 90)
    assert matched["elite_tier"] == "GOLD", (
        f"the status match raises elite_tier to GOLD, got {matched['elite_tier']!r}"
    )

    transaction = validate_success(
        api.create_mile_transaction(
            {
                "member_id": member["id"],
                "txn_type": "FLIGHT_EARN",
                "activity_date": "2026-08-01",
                "base_miles": 1000,
                "segments": 2,
            },
            REVENUE_ACCOUNTANT,
        ),
        201,
    )

    assert_mile_transaction(transaction)
    assert transaction["elite_tier_at_earn"] == "GOLD", (
        "elite_tier_at_earn snapshots the member's tier at insert time, "
        f"got {transaction['elite_tier_at_earn']!r}"
    )
    assert transaction["posted_period"] == "2026-08", (
        "posted_period snapshots the programme's current_period, "
        f"got {transaction['posted_period']!r}"
    )
    assert transaction["tier_bonus_miles"] == 500, (
        "1000 base miles at the GOLD rate of 5000 basis points is 500, "
        f"got {transaction['tier_bonus_miles']}"
    )
    assert transaction["promo_multiplier_bps"] == 10000, (
        "with no promotion the multiplier stays neutral at 10000 bps, "
        f"got {transaction['promo_multiplier_bps']}"
    )
    assert transaction["stacking_mode_applied"] is None, (
        "with no promotion stacking_mode_applied is null, "
        f"got {transaction['stacking_mode_applied']!r}"
    )
    assert transaction["bonus_miles"] == 0, (
        "the raw bonus of an unpromoted earn is zero, "
        f"got {transaction['bonus_miles']}"
    )
    assert transaction["total_miles"] == 1500, (
        "total_miles is 1000 base plus 500 tier bonus plus 0 promotional bonus, "
        f"got {transaction['total_miles']}"
    )
    assert transaction["qualifying_miles_credited"] == 1000, (
        "a FLIGHT_EARN row credits qualifying miles equal to its base, "
        f"got {transaction['qualifying_miles_credited']}"
    )


def test_flight_earn_insert_moves_the_member_qualification_counters(api):
    """PRD §3.4: "**Seventh**, elite-qualifying credit is computed entirely independently of every multiplier above: a `FLIGHT_EARN` row credits `qualifying_miles_credited` equal to its base and adds the supplied `segments` to the member's `qualifying_segments_ytd`; a `CARD_SPEND_EARN` row credits the lesser of its base and a per-transaction cap of 15000 qualifying miles, and adds the supplied `qualifying_spend_cents` to the member's `qualifying_spend_cents_ytd`; a `PARTNER_EARN` row credits zero qualifying miles."
    PRD §3.4: "In all three cases `qualifying_miles_credited` is added to the member's `qualifying_miles_ytd`."
    PRD §3.4: "The insert then adds `total_miles` to the member's `mile_balance` and `lifetime_miles`, adds `total_miles` to the programme's `outstanding_miles`, and adds `bonus_miles` to the campaign's `accrued_bonus_miles`."

    Design: Corner/entities/mile_transaction_system_fields_stamp_period_and_tier_snapshot
    """
    program = create_program(name="SkyMiles System")
    member = create_member(
        program["id"], external_member_ref="MBR-SYS", home_region="AMER"
    )
    grant_status_match(member["id"], "GOLD", 90)

    validate_success(
        api.create_mile_transaction(
            {
                "member_id": member["id"],
                "txn_type": "FLIGHT_EARN",
                "activity_date": "2026-08-01",
                "base_miles": 1000,
                "segments": 2,
            },
            REVENUE_ACCOUNTANT,
        ),
        201,
    )

    member_after = read_member(member["id"])
    assert member_after["mile_balance"] == 1500, (
        "the row's total_miles of 1500 lands on mile_balance, "
        f"got {member_after['mile_balance']}"
    )
    assert member_after["qualifying_miles_ytd"] == 1000, (
        "qualifying_miles_ytd takes the 1000 qualifying miles credited, "
        f"got {member_after['qualifying_miles_ytd']}"
    )
    assert member_after["qualifying_segments_ytd"] == 2, (
        "the two supplied segments land on qualifying_segments_ytd, "
        f"got {member_after['qualifying_segments_ytd']}"
    )


# --------------------------------------------------------------------------- #
# Immutable ledger rows
# --------------------------------------------------------------------------- #
def test_deferred_revenue_posting_read_carries_no_version_or_updated_at(api):
    """PRD §2.4: "Two resources are append-only ledger rows and are never modified after insertion: a mile ledger row (`MileTransaction`) and a deferred revenue posting (`DeferredRevenuePosting`)."
    PRD §2.4: "Both carry only `id` and `created_at`; on these two resources `updated_at` and `version` are absent entirely, and no operation exists that would edit them."
    PRD §3.9: "From `OPEN` the posture may move to `CLOSING`, which is what makes a deferred revenue posting permitted."

    Design: Corner/entities/deferred_revenue_posting_is_immutable_with_no_version_field
    """
    program = create_program(name="SkyMiles Immutable")
    closing = transition_recognition(program["id"], "CLOSING")
    posting = create_posting(program["id"], "2026-08", closing["version"])

    read = validate_success(
        api.get_deferred_revenue_posting(posting["id"], REVENUE_ACCOUNTANT), 200
    )

    assert_deferred_revenue_posting(read)
    assert is_valid_uuid(read["id"]), (
        f"the posting carries a server-minted id, got {read['id']!r}"
    )
    assert read["created_at"], "the posting carries created_at"
    assert "version" not in read, (
        "an append-only posting has no version field at all, "
        f"got {read.get('version')!r}"
    )
    assert "updated_at" not in read, (
        "an append-only posting has no updated_at field at all, "
        f"got {read.get('updated_at')!r}"
    )


def test_deferred_revenue_posting_on_a_quiet_period_posts_zero_breakage(api):
    """PRD §3.9: "When `method` is omitted it defaults to the programme's `breakage_policy_mode`, and the variant actually used is echoed on the row as `method_applied`."
    PRD §3.9: "`expired_miles_trailing` is the absolute miles expired in that window, computed as the sum of the negated `total_miles` of rows whose `txn_type` is `EXPIRY`."
    PRD §3.9: "`redeemed_miles_trailing` is likewise the sum of the negated `total_miles` of rows whose `txn_type` is `REDEEM`."
    PRD §3.9: "`issued_miles_trailing` is the sum of `total_miles` over rows whose `txn_type` is `FLIGHT_EARN`, `CARD_SPEND_EARN` or `PARTNER_EARN`."
    PRD §3.9: "The **historical attrition** variant looks backward and asks what share of the miles that left the programme left by expiring rather than by being redeemed: its denominator is `expired_miles_trailing` plus `redeemed_miles_trailing`, and the raw rate is `expired_miles_trailing` multiplied by 10000 and divided by that denominator, rounded half up to whole basis points — or exactly zero when the denominator is zero, in which case the posting is still created with a `breakage_income_cents` of zero."
    PRD §3.9: "`outstanding_miles_snapshot` captures the programme's `outstanding_miles` at posting time and `deferred_balance_before_cents` captures its `deferred_revenue_cents` at the same instant."
    PRD §3.9: "`breakage_income_cents` is `deferred_balance_before_cents` multiplied by `breakage_rate_bps`, divided by 10000, rounded half up to whole cents — so a `deferred_balance_before_cents` of zero yields zero income regardless of the rate."
    PRD §3.9: "`deferred_balance_after_cents` is `deferred_balance_before_cents` minus `breakage_income_cents`."

    Design: Corner/entities/deferred_revenue_posting_is_immutable_with_no_version_field
    """
    program = create_program(name="SkyMiles Immutable")
    closing = transition_recognition(program["id"], "CLOSING")
    posting = create_posting(program["id"], "2026-08", closing["version"])

    read = validate_success(
        api.get_deferred_revenue_posting(posting["id"], REVENUE_ACCOUNTANT), 200
    )

    assert read["method_applied"] == "HISTORICAL_ATTRITION", (
        "an omitted method falls back to the programme's breakage_policy_mode, "
        f"got {read['method_applied']!r}"
    )
    assert read["expired_miles_trailing"] == 0, (
        "no EXPIRY row exists in the trailing window, "
        f"got expired_miles_trailing {read['expired_miles_trailing']}"
    )
    assert read["redeemed_miles_trailing"] == 0, (
        "no REDEEM row exists in the trailing window, "
        f"got redeemed_miles_trailing {read['redeemed_miles_trailing']}"
    )
    assert read["issued_miles_trailing"] == 0, (
        "no earning row exists in the trailing window, "
        f"got issued_miles_trailing {read['issued_miles_trailing']}"
    )
    assert read["breakage_rate_bps"] == 0, (
        "a zero denominator yields a breakage rate of exactly zero, "
        f"got {read['breakage_rate_bps']}"
    )
    assert read["deferred_balance_before_cents"] == 0, (
        "the programme has taken no co-brand cash, "
        f"got deferred_balance_before_cents {read['deferred_balance_before_cents']}"
    )
    assert read["breakage_income_cents"] == 0, (
        "a zero balance before yields zero income, "
        f"got {read['breakage_income_cents']}"
    )
    assert read["deferred_balance_after_cents"] == 0, (
        "zero before minus zero income is zero after, "
        f"got {read['deferred_balance_after_cents']}"
    )
