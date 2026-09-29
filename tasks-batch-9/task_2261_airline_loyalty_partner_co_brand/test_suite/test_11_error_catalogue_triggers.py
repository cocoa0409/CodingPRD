"""Error catalogue triggers: each identifier and each guard reports its own code.

Every test builds its own rows from the endpoints the PRD declares, because the
harness restarts the service with an empty database before each test.
"""
import pytest

from test_helpers import (
    CONTRACTS_OFFICER,
    PARTNER_MANAGER,
    PROGRAM_ADMIN,
    REVENUE_ACCOUNTANT,
    award_booking_payload,
    award_inventory_window_payload,
    create_issuer,
    create_member,
    create_posting,
    create_program,
    create_window,
    deferred_revenue_posting_payload,
    draft_agreement,
    get_success_data,
    hold_seats,
    live_campaign,
    make_headers,
    mile_sale_agreement_payload,
    mile_transaction_payload,
    post_transaction,
    program_change_notice_payload,
    ratify_agreement,
    read_agreement,
    read_member,
    read_program,
    read_window,
    set_clock,
    submit_agreement,
    transition_recognition,
    validate_error,
    validate_paginated,
    validate_success,
)

# One unresolvable identifier per path-parameter family, each paired with the
# not-found code the PRD assigns to that identifier.
UNRESOLVABLE_PATH_IDENTIFIERS = [
    ("get_loyalty_program", "00000000-0000-4000-8000-000000000001",
     "ERR_PROGRAM_NOT_FOUND"),
    ("get_co_brand_issuer", "00000000-0000-4000-8000-000000000002",
     "ERR_ISSUER_NOT_FOUND"),
    ("get_mile_sale_agreement", "00000000-0000-4000-8000-000000000003",
     "ERR_AGREEMENT_NOT_FOUND"),
    ("get_mile_purchase_order", "00000000-0000-4000-8000-000000000004",
     "ERR_ORDER_NOT_FOUND"),
    ("get_member_account", "00000000-0000-4000-8000-000000000005",
     "ERR_MEMBER_NOT_FOUND"),
    ("get_mile_transaction", "00000000-0000-4000-8000-000000000006",
     "ERR_TRANSACTION_NOT_FOUND"),
    ("get_promotion_campaign", "00000000-0000-4000-8000-000000000007",
     "ERR_PROMOTION_NOT_FOUND"),
    ("get_award_inventory_window", "00000000-0000-4000-8000-000000000008",
     "ERR_AWARD_WINDOW_NOT_FOUND"),
    ("get_partner_airline", "00000000-0000-4000-8000-000000000009",
     "ERR_PARTNER_NOT_FOUND"),
    ("get_program_change_notice", "00000000-0000-4000-8000-000000000010",
     "ERR_NOTICE_NOT_FOUND"),
    ("get_fraud_case", "00000000-0000-4000-8000-000000000011",
     "ERR_FRAUD_CASE_NOT_FOUND"),
    ("get_deferred_revenue_posting", "00000000-0000-4000-8000-000000000012",
     "ERR_POSTING_NOT_FOUND"),
]


@pytest.mark.parametrize(
    "reader_method, unresolvable_id, expected_error_id",
    UNRESOLVABLE_PATH_IDENTIFIERS,
)
def test_every_unresolvable_path_identifier_returns_its_own_not_found_code(
    api, reader_method, unresolvable_id, expected_error_id
):
    """Each path identifier family reports the 404 code the PRD assigns to it.

    PRD §2.11: "Path identifiers are resolved strictly left to right, and the first identifier that does not resolve determines the error."
    PRD §2.11: "Each identifier has its own not-found code: `programId` yields `ERR_PROGRAM_NOT_FOUND`, `issuerId` yields `ERR_ISSUER_NOT_FOUND`, `agreementId` yields `ERR_AGREEMENT_NOT_FOUND`, `orderId` yields `ERR_ORDER_NOT_FOUND`, `memberId` yields `ERR_MEMBER_NOT_FOUND`, `transactionId` yields `ERR_TRANSACTION_NOT_FOUND`, `campaignId` yields `ERR_PROMOTION_NOT_FOUND`, `windowId` yields `ERR_AWARD_WINDOW_NOT_FOUND`, `bookingId` yields `ERR_BOOKING_NOT_FOUND`, `airlineId` yields `ERR_PARTNER_NOT_FOUND`, `noticeId` yields `ERR_NOTICE_NOT_FOUND`, `caseId` yields `ERR_FRAUD_CASE_NOT_FOUND`, and `postingId` yields `ERR_POSTING_NOT_FOUND`."
    Design: Corner/errors/every_unresolvable_identifier_returns_its_own_not_found_code
    """
    # A non-empty database, so every miss below is a genuine miss.
    program = create_program(name="SkyMiles NotFound")
    create_member(program["id"], external_member_ref="MBR-404")

    response = getattr(api, reader_method)(unresolvable_id, PROGRAM_ADMIN)

    validate_error(response, expected_error_id, 404)


def test_an_unresolvable_body_foreign_key_returns_its_own_not_found_code(api):
    """A body-supplied `reverses_transaction_id` miss is a 404, not a 400.

    PRD §2.11: "The same codes serve body-supplied foreign keys, which are resolved in the order the fields are declared for the operation: `program_id` resolves to a programme, `issuer_id` to an issuer, `agreement_id` and `supersedes_agreement_id` to agreements, `member_id` to a member account, `reverses_transaction_id` to a mile ledger row, `promotion_id` to a campaign, `window_id` to an award inventory window, `award_booking_id` to an award booking, and `partner_airline_id` to a partner airline."
    PRD §2.9: "Every foreign key supplied in the request body resolves to an existing row, checked in the order the fields are declared for that operation — otherwise the corresponding 404 not-found code."
    Design: Corner/errors/every_unresolvable_identifier_returns_its_own_not_found_code
    """
    program = create_program(name="SkyMiles NotFound")
    member = create_member(program["id"], external_member_ref="MBR-404")

    response = api.create_mile_transaction(
        mile_transaction_payload(
            member["id"], "REVERSAL", "2026-08-01",
            base_miles=100,
            reverses_transaction_id="00000000-0000-4000-8000-000000000013",
        ),
        REVENUE_ACCOUNTANT,
    )

    validate_error(response, "ERR_TRANSACTION_NOT_FOUND", 404)
    assert read_member(member["id"])["mile_balance"] == 0, (
        "a rejected reversal must leave the member's mile_balance at zero"
    )
    _rows, meta = validate_paginated(
        api.list_mile_transactions(PROGRAM_ADMIN, params={"member_id": member["id"]})
    )
    assert meta["total_count"] == 0, (
        "no ledger row may be written when the reversed row does not resolve"
    )


def test_request_with_an_undeclared_role_returns_unauthenticated(api):
    """A role outside the seven declared names is a 401, not a 403.

    PRD §2.1: "If either header is absent, or if `X-User-Role` is not exactly one of the seven role names below, the request is rejected with `ERR_UNAUTHENTICATED` (401)."
    PRD §2.9: "`X-User-ID` is present, `X-User-Role` is present, and `X-User-Role` is one of the seven declared roles — otherwise `ERR_UNAUTHENTICATED` (401)."
    Design: Corner/errors/request_with_an_undeclared_role_returns_unauthenticated
    """
    response = api.create_loyalty_program(
        {"name": "SkyMiles Rogue"}, make_headers("AuditorGeneral", "who-1")
    )

    error = validate_error(response, "ERR_UNAUTHENTICATED", 401)
    assert error["error_id"] != "ERR_FORBIDDEN_ROLE", (
        "an undeclared role fails authentication before any authorisation check"
    )
    _programs, meta = validate_paginated(api.list_loyalty_programs(PROGRAM_ADMIN))
    assert meta["total_count"] == 0, (
        "an unauthenticated create must leave no loyalty programme behind"
    )


def test_submit_on_a_suspended_issuer_returns_issuer_suspended(api):
    """A cap-breach suspension blocks the next submit and the pending activation.

    PRD §3.1: "Its `aggregate_committed_miles` starts at zero and is thereafter defined as the sum of `committed_volume_miles` over this issuer's agreements whose `status` is `RATIFIED` or `ACTIVE`, recomputed whenever an agreement of that issuer is ratified, activated, terminated or expired."
    PRD §3.2: "The third hop, caused by the second, tests the newly recomputed aggregate against a utilisation alarm set at 9000 basis points of the cap, that is at ninety percent of `annual_mile_purchase_cap_miles` after rounding half up, with the boundary inclusive: when the recomputed `aggregate_committed_miles` reaches or exceeds that figure, the issuer's `status` becomes `SUSPENDED` and its `suspension_reason` becomes `CAP_BREACH`."
    PRD §3.2: "An issuer can therefore be tipped into suspension by the very ratification that filled its book, which immediately blocks further submissions, activations and draws."
    PRD §3.1: "A `SUSPENDED` issuer blocks three things: submitting a new agreement, activating an agreement, and drawing a new mile purchase order — all with `ERR_ISSUER_SUSPENDED`."
    Design: Corner/errors/submit_on_a_suspended_issuer_returns_issuer_suspended
    """
    program = create_program(name="SkyMiles Suspended")
    issuer = create_issuer(program["id"], annual_mile_purchase_cap_miles=5_000_000)
    agreement_a = draft_agreement(issuer["id"], committed_volume_miles=5_000_000)
    submit_agreement(agreement_a["id"])
    ratify_agreement(agreement_a["id"])
    agreement_b = draft_agreement(
        issuer["id"],
        term_start_date="2027-09-01",
        term_end_date="2028-08-31",
        committed_volume_miles=100_000,
    )

    suspended = get_success_data(api.get_co_brand_issuer(issuer["id"], PROGRAM_ADMIN))
    assert suspended["aggregate_committed_miles"] == 5_000_000, (
        "the ratified agreement's committed volume defines aggregate_committed_miles"
    )
    assert suspended["status"] == "SUSPENDED", (
        "an aggregate at or above the utilisation alarm suspends the issuer"
    )
    assert suspended["suspension_reason"] == "CAP_BREACH", (
        "an automatic suspension carries suspension_reason CAP_BREACH"
    )

    validate_error(
        api.submit_agreement(agreement_b["id"], PARTNER_MANAGER),
        "ERR_ISSUER_SUSPENDED", 409,
    )
    assert read_agreement(agreement_b["id"])["status"] == "DRAFT", (
        "a refused submission leaves the agreement in DRAFT"
    )

    validate_error(
        api.activate_agreement(agreement_a["id"], CONTRACTS_OFFICER),
        "ERR_ISSUER_SUSPENDED", 409,
    )
    assert read_agreement(agreement_a["id"])["status"] == "RATIFIED", (
        "a refused activation leaves the agreement in RATIFIED"
    )


def test_supersede_target_still_in_draft_is_rejected(api):
    """A DRAFT predecessor is not a legal supersede target.

    PRD §3.2: "And a supplied `supersedes_agreement_id` must point at an agreement of the same issuer that is currently `RATIFIED` or `ACTIVE`, that no other agreement already supersedes, and that is not this agreement itself; anything else raises `ERR_SUPERSEDE_TARGET_INVALID`."
    PRD §3.2: "Crucially, a `DRAFT` agreement does not yet count toward the issuer's aggregate."
    Design: Corner/errors/supersede_target_still_in_draft_is_rejected
    """
    program = create_program(name="SkyMiles Supersede")
    issuer = create_issuer(program["id"], annual_mile_purchase_cap_miles=5_000_000)
    draft_target = draft_agreement(issuer["id"], committed_volume_miles=1_000_000)

    response = api.create_mile_sale_agreement(
        mile_sale_agreement_payload(
            issuer["id"],
            term_start_date="2027-09-01",
            term_end_date="2028-08-31",
            committed_volume_miles=1_000_000,
            supersedes_agreement_id=draft_target["id"],
        ),
        PARTNER_MANAGER,
    )

    validate_error(response, "ERR_SUPERSEDE_TARGET_INVALID", 422)
    assert read_agreement(draft_target["id"])["status"] == "DRAFT", (
        "the rejected create must leave the target agreement in DRAFT"
    )
    _agreements, meta = validate_paginated(
        api.list_mile_sale_agreements(
            PARTNER_MANAGER, params={"issuer_id": issuer["id"]}
        )
    )
    assert meta["total_count"] == 1, (
        "the rejected agreement must not have been persisted"
    )
    issuer_row = get_success_data(api.get_co_brand_issuer(issuer["id"], PROGRAM_ADMIN))
    assert issuer_row["aggregate_committed_miles"] == 0, (
        "a DRAFT agreement contributes nothing to aggregate_committed_miles"
    )


def test_earn_referencing_a_campaign_on_another_channel_is_rejected(api):
    """A CARD_SPEND campaign cannot lift a FLIGHT_EARN row.

    PRD §3.4: "The campaign's `earn_channel` must correspond to the row's `txn_type` — `FLIGHT` with `FLIGHT_EARN`, `CARD_SPEND` with `CARD_SPEND_EARN`, `PARTNER` with `PARTNER_EARN` — and the campaign's half-open window must contain the row's `activity_date`; a channel or window mismatch is rejected with `ERR_PROMOTION_CHANNEL_MISMATCH`."
    PRD §3.4: "`accrued_bonus_miles` starts at zero and is thereafter the sum of `bonus_miles` across every ledger row whose `promotion_id` names this campaign."
    Design: Corner/errors/earn_referencing_a_campaign_on_another_channel_is_rejected
    """
    program = create_program(name="SkyMiles Channel")
    member = create_member(program["id"], external_member_ref="MBR-CHAN")
    campaign = live_campaign(
        program["id"],
        code="CARD-ONLY",
        earn_channel="CARD_SPEND",
        multiplier_bps=20000,
        stacking_mode="ADDITIVE",
    )
    assert campaign["status"] == "LIVE", (
        "the epoch sweep must have launched the campaign before the earn is posted"
    )

    response = api.create_mile_transaction(
        mile_transaction_payload(
            member["id"], "FLIGHT_EARN", "2026-08-01",
            base_miles=1000, segments=1, promotion_id=campaign["id"],
        ),
        REVENUE_ACCOUNTANT,
    )

    validate_error(response, "ERR_PROMOTION_CHANNEL_MISMATCH", 422)
    refreshed = get_success_data(
        api.get_promotion_campaign(campaign["id"], PROGRAM_ADMIN)
    )
    assert refreshed["accrued_bonus_miles"] == 0, (
        "a rejected earn accrues no bonus miles against the campaign"
    )
    assert read_member(member["id"])["mile_balance"] == 0, (
        "a rejected earn credits no miles to the member"
    )
    _rows, meta = validate_paginated(
        api.list_mile_transactions(PROGRAM_ADMIN, params={"member_id": member["id"]})
    )
    assert meta["total_count"] == 0, "a rejected earn writes no ledger row"


def test_ten_seats_on_one_booking_returns_seat_count_invalid(api):
    """Ten seats break the per-booking ceiling, and that has its own code.

    PRD §2.9: "`seats` is at least 1 and at most 9 — otherwise `ERR_SEAT_COUNT_INVALID` (422)."
    PRD §2.9: "Two bounds are deliberately excluded from this rung because dedicated rungs further down own them: an out-of-range `seats` value on an award booking must surface as `ERR_SEAT_COUNT_INVALID` at rung 26, and an inverted date interval must surface as `ERR_INVALID_INTERVAL` at rung 14."
    PRD §2.9: "Neither may ever be reported as `ERR_INVALID_REQUEST`."
    Design: Corner/errors/ten_seats_on_one_booking_returns_seat_count_invalid
    """
    program = create_program(name="SkyMiles Seats")
    member = create_member(program["id"], external_member_ref="MBR-SEATS")
    window = create_window(program["id"], authorized_seats=20)

    response = api.create_award_booking(
        award_booking_payload(
            member["id"], window["id"], window["version"],
            travel_date="2026-09-10", seats=10, fare_class="FLEX",
        ),
        PROGRAM_ADMIN,
    )

    error = validate_error(response, "ERR_SEAT_COUNT_INVALID", 422)
    assert error["error_id"] != "ERR_INVALID_REQUEST", (
        "an out-of-range seats value never surfaces as ERR_INVALID_REQUEST"
    )
    assert error["error_id"] != "ERR_AWARD_SEATS_UNAVAILABLE", (
        "capacity is ample at 20 authorised seats, so the seat-count rung answers"
    )
    refreshed = read_window(window["id"])
    assert refreshed["seats_held"] == 0, "a rejected hold moves no seats"
    assert refreshed["version"] == window["version"], (
        "a rejected hold leaves the window's version untouched"
    )


def test_three_seats_on_a_two_seat_window_returns_award_seats_unavailable(api):
    """Three seats exceed raw capacity; the two that fit close the window.

    PRD §2.9: "The window has raw capacity: `seats_held` plus `seats_confirmed` plus the requested `seats` is at most `authorized_seats` — otherwise `ERR_AWARD_SEATS_UNAVAILABLE` (409)."
    PRD §3.5: "`load_factor_bps` is `seats_held` plus `seats_confirmed`, multiplied by 10000, divided by `authorized_seats`, rounded half up, and defined as zero when `authorized_seats` is zero."
    PRD §3.5: "`capacity_control_state` then follows from it against two inclusive lower bounds: a load factor below 7500 basis points (75% sold) is `OPEN`, a load factor from 7500 through 9999 is `CONSTRAINED`, and a load factor of 10000 or more is `CLOSED`."
    Design: Corner/errors/three_seats_on_a_two_seat_window_returns_award_seats_unavailable
    """
    program = create_program(name="SkyMiles Capacity")
    member = create_member(program["id"], external_member_ref="MBR-CAP")
    window = create_window(program["id"], authorized_seats=2)

    refused = api.create_award_booking(
        award_booking_payload(
            member["id"], window["id"], window["version"],
            travel_date="2026-09-10", seats=3, fare_class="FLEX",
        ),
        PROGRAM_ADMIN,
    )
    validate_error(refused, "ERR_AWARD_SEATS_UNAVAILABLE", 409)
    assert read_window(window["id"])["seats_held"] == 0, (
        "the refused three-seat hold must not have moved seats_held"
    )

    accepted = validate_success(
        api.create_award_booking(
            award_booking_payload(
                member["id"], window["id"], window["version"],
                travel_date="2026-09-10", seats=2, fare_class="FLEX",
            ),
            PROGRAM_ADMIN,
        ),
        expected_status=201,
    )
    assert accepted["quoted_miles"] == 45000, (
        "two ECONOMY FLEX seats on an empty window quote 45000 miles"
    )
    refreshed = read_window(window["id"])
    assert refreshed["seats_held"] == 2, "both held seats are recorded on the window"
    assert refreshed["load_factor_bps"] == 10000, (
        "two of two authorised seats held is a load factor of 10000 basis points"
    )
    assert refreshed["capacity_control_state"] == "CLOSED", (
        "a load factor of 10000 or more puts the window in CLOSED"
    )


def test_ticketing_at_the_hold_expiry_instant_returns_hold_expired(api):
    """A hold is dead at its own expiry instant, because the bound is strict.

    PRD §3.5: "The hold survives 72 hours: `hold_expires_at` is stamped as the logical clock's now plus 72 hours, and the booking lands with `status` `HELD` and `partner_settled` false."
    PRD §3.5: "Four conditions guard it: the hold must still be live, with `hold_expires_at` strictly after the clock's now, else `ERR_HOLD_EXPIRED`; the member's `security_state` must be `NORMAL`; the member's `mile_balance` must be at least `quoted_miles`, else `ERR_INSUFFICIENT_MILES`; and the programme must not be `LOCKED`."
    PRD §2.6: "Repositioning the clock mutates no business entity by itself; time-driven state changes happen only when the epoch runner is invoked, as described in §3.1."
    Design: Corner/errors/ticketing_at_the_hold_expiry_instant_returns_hold_expired
    """
    program = create_program(name="SkyMiles Hold")
    member = create_member(program["id"], external_member_ref="MBR-HOLD")
    post_transaction(
        member["id"], "CARD_SPEND_EARN", "2026-07-02",
        headers=REVENUE_ACCOUNTANT, qualifying_spend_cents=10_000_000,
    )
    window = create_window(program["id"], authorized_seats=10)
    booking = hold_seats(
        member["id"], window["id"], window["version"],
        travel_date="2026-09-10", seats=1, fare_class="FLEX",
    )
    assert booking["hold_expires_at"].startswith("2026-08-04T00:00:00"), (
        "a hold created at 2026-08-01T00:00:00Z expires 72 hours later"
    )

    set_clock("2026-08-04T00:00:00Z")

    response = api.ticket_award_booking(booking["id"], PROGRAM_ADMIN)

    validate_error(response, "ERR_HOLD_EXPIRED", 409)
    refreshed_booking = get_success_data(
        api.get_award_booking(booking["id"], PROGRAM_ADMIN)
    )
    assert refreshed_booking["status"] == "HELD", (
        "without the epoch sweep the booking is still HELD, so the guard answered"
    )
    assert read_member(member["id"])["mile_balance"] == 100000, (
        "a refused ticketing debits no miles"
    )
    refreshed_window = read_window(window["id"])
    assert refreshed_window["seats_held"] == 1, (
        "the seat stays held when ticketing is refused"
    )
    assert refreshed_window["seats_confirmed"] == 0, (
        "no seat is confirmed when ticketing is refused"
    )


def test_redeeming_one_mile_more_than_the_balance_returns_insufficient_miles(api):
    """The balance bound is inclusive: 1001 fails, 1000 empties the account.

    PRD §3.4: "A `REDEEM`, `EXPIRY` or `ADJUSTMENT` row still cannot drive the balance below zero: if the member's `mile_balance` is below the magnitude being debited the posting is refused with `ERR_INSUFFICIENT_MILES`."
    PRD §3.4: "Their `total_miles` is taken straight from the caller-supplied `base_miles` magnitude, which is always supplied non-negative, with the sign the type dictates: negative for `REDEEM`, `EXPIRY` and `ADJUSTMENT`, positive for `REVERSAL`."
    PRD §3.4: "Note that `lifetime_miles` counts only the three earning types, whereas `mile_balance` and `outstanding_miles` sum every type with its sign, and `mile_balance` is never negative."
    Design: Corner/errors/redeeming_one_mile_more_than_the_balance_returns_insufficient_miles
    """
    program = create_program(name="SkyMiles Fiscal")
    member = create_member(program["id"], external_member_ref="MBR-FISC")
    post_transaction(
        member["id"], "PARTNER_EARN", "2026-07-11",
        headers=REVENUE_ACCOUNTANT, base_miles=1000,
    )

    refused = api.create_mile_transaction(
        mile_transaction_payload(
            member["id"], "REDEEM", "2026-08-01", base_miles=1001
        ),
        REVENUE_ACCOUNTANT,
    )
    validate_error(refused, "ERR_INSUFFICIENT_MILES", 402)
    assert read_member(member["id"])["mile_balance"] == 1000, (
        "the refused redemption must leave the balance untouched"
    )

    accepted = validate_success(
        api.create_mile_transaction(
            mile_transaction_payload(
                member["id"], "REDEEM", "2026-08-01", base_miles=1000
            ),
            REVENUE_ACCOUNTANT,
        ),
        expected_status=201,
    )
    assert accepted["total_miles"] == -1000, (
        "a REDEEM row carries the supplied magnitude with a negative sign"
    )
    refreshed_member = read_member(member["id"])
    assert refreshed_member["mile_balance"] == 0, (
        "redeeming the exact balance drives mile_balance to zero"
    )
    assert refreshed_member["lifetime_miles"] == 1000, (
        "lifetime_miles counts only the earning row, not the redemption"
    )
    assert read_program(program["id"])["outstanding_miles"] == 0, (
        "the programme's outstanding liability is discharged by the redemption"
    )
    _rows, meta = validate_paginated(
        api.list_mile_transactions(PROGRAM_ADMIN, params={"member_id": member["id"]})
    )
    assert meta["total_count"] == 2, (
        "only the earn and the successful redemption are on the ledger"
    )


def test_second_posting_for_the_same_period_returns_period_already_posted(api):
    """A second posting for one period is refused even with a fresh version.

    PRD §3.9: "Only one posting may ever exist per `program_id` and `period` pair; a second attempt is rejected with `ERR_PERIOD_ALREADY_POSTED`."
    PRD §3.9: "The **historical attrition** variant looks backward and asks what share of the miles that left the programme left by expiring rather than by being redeemed: its denominator is `expired_miles_trailing` plus `redeemed_miles_trailing`, and the raw rate is `expired_miles_trailing` multiplied by 10000 and divided by that denominator, rounded half up to whole basis points — or exactly zero when the denominator is zero, in which case the posting is still created with a `breakage_income_cents` of zero."
    PRD §2.8: "In each case, if the supplied value does not equal the parent's current `version`, the write is rejected with `ERR_STALE_VERSION` (412) and nothing is mutated."
    Design: Corner/errors/second_posting_for_the_same_period_returns_period_already_posted
    """
    program = create_program(name="SkyMiles Posted")
    transition_recognition(program["id"], "CLOSING")
    posting = create_posting(
        program["id"], "2026-08", read_program(program["id"])["version"]
    )
    fresh_version = read_program(program["id"])["version"]

    response = api.create_deferred_revenue_posting(
        deferred_revenue_posting_payload(program["id"], "2026-08", fresh_version),
        REVENUE_ACCOUNTANT,
    )

    error = validate_error(response, "ERR_PERIOD_ALREADY_POSTED", 409)
    assert error["error_id"] != "ERR_STALE_VERSION", (
        "the expected_program_version was re-read, so the conflict is the period"
    )
    assert posting["breakage_rate_bps"] == 0, (
        "with no expiries and no redemptions the historical rate is exactly zero"
    )
    assert posting["breakage_income_cents"] == 0, (
        "a zero deferred balance yields zero breakage income"
    )
    refreshed = read_program(program["id"])
    assert refreshed["deferred_revenue_cents"] == 0, (
        "the refused posting must not reduce deferred revenue a second time"
    )
    assert refreshed["revenue_recognition_state"] == "CLOSING", (
        "a refused posting leaves the accounting posture in CLOSING"
    )
    _postings, meta = validate_paginated(
        api.list_deferred_revenue_postings(
            REVENUE_ACCOUNTANT,
            params={"program_id": program["id"], "period": "2026-08"},
        )
    )
    assert meta["total_count"] == 1, (
        "exactly one posting may exist for one programme and period pair"
    )


def test_touching_agreement_terms_returns_agreement_term_overlap(api):
    """Terms are closed intervals, so a shared end day is an overlap.

    PRD §3.2: "A `PartnerManager` drafts one against an `issuer_id`, giving the term as `term_start_date` and `term_end_date` (inclusive calendar dates), the `committed_volume_miles` the issuer undertakes to buy over that term (at least one mile), and a `tier_schedule` of volume price tiers."
    PRD §3.2: "The term must not overlap the term of any other agreement of the same issuer that is still alive in `DRAFT`, `ISSUER_REVIEW`, `COUNTERED`, `RATIFIED` or `ACTIVE`, the sole exception being the very agreement this one supersedes; an overlap raises `ERR_AGREEMENT_TERM_OVERLAP`."
    Design: Corner/errors/touching_agreement_terms_returns_agreement_term_overlap
    """
    program = create_program(name="SkyMiles Overlap")
    issuer = create_issuer(program["id"], annual_mile_purchase_cap_miles=20_000_000)
    draft_agreement(issuer["id"], committed_volume_miles=1_000_000)

    overlapping = api.create_mile_sale_agreement(
        mile_sale_agreement_payload(
            issuer["id"],
            term_start_date="2027-08-31",
            term_end_date="2028-08-31",
            committed_volume_miles=1_000_000,
        ),
        PARTNER_MANAGER,
    )
    validate_error(overlapping, "ERR_AGREEMENT_TERM_OVERLAP", 409)

    adjacent = validate_success(
        api.create_mile_sale_agreement(
            mile_sale_agreement_payload(
                issuer["id"],
                term_start_date="2027-09-01",
                term_end_date="2028-08-31",
                committed_volume_miles=1_000_000,
            ),
            PARTNER_MANAGER,
        ),
        expected_status=201,
    )
    assert adjacent["term_start_date"] == "2027-09-01", (
        "a term starting the day after the predecessor ends is accepted"
    )
    assert adjacent["status"] == "DRAFT", "a freshly drafted agreement starts in DRAFT"
    _agreements, meta = validate_paginated(
        api.list_mile_sale_agreements(
            PARTNER_MANAGER, params={"issuer_id": issuer["id"]}
        )
    )
    assert meta["total_count"] == 2, (
        "only the original and the non-overlapping agreement were persisted"
    )


def test_inverted_award_window_dates_return_invalid_interval(api):
    """Interval ordering answers before the window-in-past rule does.

    PRD §2.9: "Checks are evaluated in ascending order, and **the first check that fails is the response** — no later check runs, and no partial mutation is retained."
    PRD §2.9: "Every date interval is correctly ordered: `term_start_date` is not after `term_end_date`, `window_start_date` is not after `window_end_date`, and `window_start` is strictly before `window_end` — otherwise `ERR_INVALID_INTERVAL` (422)."
    PRD §2.9: "Neither may ever be reported as `ERR_INVALID_REQUEST`."
    Design: Corner/errors/inverted_award_window_dates_return_invalid_interval
    """
    program = create_program(name="SkyMiles Interval")

    response = api.create_award_inventory_window(
        award_inventory_window_payload(
            program["id"],
            route_code="JFK-CDG",
            cabin="ECONOMY",
            window_start_date="2026-09-30",
            window_end_date="2026-07-30",
            authorized_seats=10,
        ),
        PROGRAM_ADMIN,
    )

    error = validate_error(response, "ERR_INVALID_INTERVAL", 422)
    assert error["error_id"] != "ERR_INVALID_REQUEST", (
        "an inverted interval is never reported as ERR_INVALID_REQUEST"
    )
    assert error["error_id"] != "ERR_WINDOW_IN_PAST", (
        "the interval rung is lower-numbered than the window-in-past rung"
    )
    _windows, meta = validate_paginated(
        api.list_award_inventory_windows(
            PROGRAM_ADMIN, params={"program_id": program["id"]}
        )
    )
    assert meta["total_count"] == 0, "the rejected window must not have been created"


def test_grandfather_until_before_effective_at_returns_invalid_notice_schedule(api):
    """Grandfathering that lapses before the change takes effect is unschedulable.

    PRD §3.8: "The draft is rejected with `ERR_INVALID_NOTICE_SCHEDULE` unless `effective_at` is strictly in the future on the logical clock and any supplied `grandfather_until` is at or after `effective_at`."
    PRD §2.8: "A programme change notice is announced against a programme-wide member exposure count, so its creation is likewise anchored to a programme version — and creating the notice itself increments `LoyaltyProgram.version` by one."
    Design: Corner/errors/grandfather_until_before_effective_at_returns_invalid_notice_schedule
    """
    program = create_program(name="SkyMiles Notice Schedule")

    response = api.create_program_change_notice(
        program_change_notice_payload(
            program["id"], "ELITE_THRESHOLD", "2027-03-01T00:00:00Z",
            program["version"], grandfather_until="2027-02-01T00:00:00Z",
        ),
        PROGRAM_ADMIN,
    )

    validate_error(response, "ERR_INVALID_NOTICE_SCHEDULE", 422)
    _notices, meta = validate_paginated(
        api.list_program_change_notices(
            PROGRAM_ADMIN, params={"program_id": program["id"]}
        )
    )
    assert meta["total_count"] == 0, "the rejected notice must not have been created"
    assert read_program(program["id"])["version"] == program["version"], (
        "a rejected notice create must not consume the programme's version"
    )
