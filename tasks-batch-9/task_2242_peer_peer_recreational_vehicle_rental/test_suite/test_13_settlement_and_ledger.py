"""Settlement: the four pinned ledger rows, the reversal that appends their
inverses, the open claim that holds the money back, and the owner cancellation
that refunds a stranger and frees a campground slot."""

from test_helpers import (
    ApiErrorId,
    AssignmentStatus,
    ClaimStatus,
    DeliveryOption,
    LedgerEntryType,
    LedgerParty,
    ListingStatus,
    OwnerStatus,
    PLATFORM_ADMIN_HEADERS,
    PolicyTier,
    SettlementStatus,
    TripStatus,
    Zone,
    factories,
    fixtures,
    validate_error,
    validate_success,
)

FORWARD_ROWS = (
    (LedgerParty.RENTER, LedgerEntryType.TRIP_CHARGE, -151876),
    (LedgerParty.OWNER, LedgerEntryType.OWNER_PAYOUT, 111275),
    (LedgerParty.PLATFORM, LedgerEntryType.SERVICE_FEE, 15650),
    (LedgerParty.PLATFORM, LedgerEntryType.PROTECTION_PREMIUM, 24951),
)
STRICT_POLICY = {
    "tier": PolicyTier.STRICT,
    "full_refund_hours_before": 168,
    "partial_refund_pct_bp": 0,
    "renter_cancel_penalty_points": 6,
    "owner_cancel_penalty_points": 9,
    "owner_cancel_fee_bp": 1500,
}
DROPOFF_WINDOW = ("2026-08-29T14:00:00Z", "2026-08-29T16:00:00Z")


def _row_shapes(rows):
    return [(row["party"], row["entry_type"], row["amount_cents"]) for row in rows]


def _by_entry_type(rows):
    return {row["entry_type"]: row for row in rows}


def _owner_cancellation_stage(api, world):
    """Two confirmed bookings on two listings, the second holding a slot.

    The owner sits three points short of the suspension threshold, so a single
    cancellation on the first booking reaches the second listing's renter.
    """
    policy = fixtures.create_cancellation_policy(api, **STRICT_POLICY)
    fixtures.adjust_owner_points(api, world.owner_id, 6, "two prior late handovers")
    campground = fixtures.seed_campground(api, daily_dropoff_capacity=1)

    first = validate_success(
        api.create_booking(
            factories.booking_payload(
                world.listing_id, world.renter_id, world.plan_id, policy["id"]
            ),
            world.renter_headers,
        ),
        201,
    )
    fixtures.approve_booking(api, world, first["id"])
    first_confirmed = fixtures.confirm_booking(api, world, first["id"])

    second_listing = fixtures.add_second_listed_listing(api, world)
    second = validate_success(
        api.create_booking(
            factories.booking_payload(
                second_listing["id"],
                world.renter_id,
                world.plan_id,
                policy["id"],
                delivery_option=DeliveryOption.CAMPGROUND_DROPOFF,
            ),
            world.renter_headers,
        ),
        201,
    )
    assignment = fixtures.create_delivery_assignment(
        api,
        world,
        second["id"],
        campground["id"],
        second["version"],
        window_start=DROPOFF_WINDOW[0],
        window_end=DROPOFF_WINDOW[1],
        distance_miles=20,
        setup_fee_cents=0,
    )
    fixtures.approve_booking(api, world, second["id"])
    second_confirmed = fixtures.confirm_booking(api, world, second["id"])

    assert assignment["status"] == AssignmentStatus.SCHEDULED
    assert first_confirmed["hold_amount_cents"] == 146063
    assert second_confirmed["hold_amount_cents"] == 161289

    return {
        "campground": campground,
        "first_booking": first_confirmed,
        "second_listing": second_listing,
        "second_booking": second_confirmed,
        "assignment": assignment,
    }


def _cancel_as_owner(api, world, booking_id):
    return validate_success(
        api.cancel_booking(
            booking_id,
            factories.cancel_payload("transmission service overran the pickup date"),
            world.owner_headers,
        ),
        200,
    )


def test_settlement_posts_the_four_pinned_rows_and_syncs_its_ancestors(api):
    """PRD 3.9: "Settlement posts exactly four ledger rows, in a pinned order. First
    the platform computes the owner's payout as the booking's `final_total_cents` minus
    its `service_fee_cents` minus its `premium_cents`" ... "a `RENTER` row of type
    `TRIP_CHARGE` carrying the negation of `final_total_cents`; an `OWNER` row of type
    `OWNER_PAYOUT` carrying the positive owner payout; a `PLATFORM` row of type
    `SERVICE_FEE` carrying the positive `service_fee_cents`; and a `PLATFORM` row of
    type `PROTECTION_PREMIUM` carrying the positive `premium_cents`. By construction
    those four signed amounts sum to exactly zero" ... "The owner's
    `payout_balance_cents` is recomputed from the ledger rows whose `party` is `OWNER`.
    The listing's `completed_night_count` increases by the booking's `nights` and the
    listing's `last_reconciled_at` is stamped with the logical clock."

    Design: Corner/state_machines/settlement_posts_four_balancing_ledger_rows_and_syncs_the_ancestors
    """
    world = fixtures.seed_marketplace(api)
    returned = fixtures.seed_returned_booking(api, world)
    assert returned["final_total_cents"] == 151876
    assert returned["balance_due_cents"] == 5813

    settled = validate_success(api.settle_booking(returned["id"], PLATFORM_ADMIN_HEADERS), 200)
    assert settled["trip_status"] == TripStatus.CLOSED
    assert settled["settlement_status"] == SettlementStatus.SETTLED

    rows = fixtures.collect_ledger_entries(api, returned["id"])
    assert len(rows) == 4
    assert _row_shapes(rows) == list(FORWARD_ROWS)
    assert sum(row["amount_cents"] for row in rows) == 0

    owner = validate_success(api.get_owner(world.owner_id, PLATFORM_ADMIN_HEADERS), 200)
    assert owner["payout_balance_cents"] == 111275

    renter = validate_success(
        api.get_renter(world.renter_id, PLATFORM_ADMIN_HEADERS), 200
    )
    assert renter["wallet_credit_cents"] == 653937 - 5813
    assert renter["wallet_credit_cents"] == 648124

    listing = validate_success(
        api.get_listing(world.listing_id, PLATFORM_ADMIN_HEADERS), 200
    )
    assert listing["completed_night_count"] == 4
    assert listing["last_reconciled_at"].startswith("2026-08-01T00:00:00")


def test_the_reversal_appends_the_exact_inverse_of_every_forward_row(api):
    """PRD 3.9: "For every forward ledger row of the booking whose `entry_type` is
    `TRIP_CHARGE`, `OWNER_PAYOUT`, `SERVICE_FEE` or `PROTECTION_PREMIUM` and whose
    `reversal_of_entry_id` is null, processed in ascending `created_at` order, the
    platform appends the exact inverse row: same `party`, same magnitude with the sign
    flipped, `entry_type` being the forward type with the suffix `_REVERSAL` — so
    `TRIP_CHARGE_REVERSAL`, `OWNER_PAYOUT_REVERSAL`, `SERVICE_FEE_REVERSAL` and
    `PROTECTION_PREMIUM_REVERSAL` — and `reversal_of_entry_id` set to the identifier of
    the row being reversed." The count and the sum are the stated guarantee: "the
    booking's ledger row count goes from four to eight, its signed sum stays zero".

    Design: Difficulty/compensating_invariant/settlement_reversal_restores_every_derived_money_field_and_keeps_the_ledger_at_zero
    """
    world = fixtures.seed_marketplace(api)
    settled = fixtures.seed_settled_booking(api, world)
    forward = _by_entry_type(fixtures.collect_ledger_entries(api, settled["id"]))

    validate_success(
        api.reverse_settlement(
            settled["id"],
            factories.reversal_payload("payout run duplicated by the finance team"),
            PLATFORM_ADMIN_HEADERS,
        ),
        200,
    )

    rows = fixtures.collect_ledger_entries(api, settled["id"])
    assert len(rows) == 8
    assert sum(row["amount_cents"] for row in rows) == 0

    reversals = _by_entry_type(rows[4:])
    for party, entry_type, amount in FORWARD_ROWS:
        mirror = reversals[f"{entry_type}_REVERSAL"]
        assert mirror["party"] == party
        assert mirror["amount_cents"] == -amount
        assert mirror["reversal_of_entry_id"] == forward[entry_type]["id"]


def test_the_reversal_puts_every_derived_money_field_back(api):
    """PRD 3.9: "The wallet motion of settlement runs backwards: when
    `balance_due_cents` is positive that amount is added back to the renter's
    `wallet_credit_cents`, and when it is negative the absolute value of it is
    subtracted. The owner's `payout_balance_cents` is recomputed, and the listing's
    `completed_night_count` decreases by the booking's `nights`. The settlement
    dimension returns `SETTLED → RECONCILING` while the trip dimension **stays
    `CLOSED`**" ... "the owner's `payout_balance_cents` returns to its exact
    pre-settlement value."

    Design: Difficulty/compensating_invariant/settlement_reversal_restores_every_derived_money_field_and_keeps_the_ledger_at_zero
    """
    world = fixtures.seed_marketplace(api)
    settled = fixtures.seed_settled_booking(api, world)

    reversed_booking = validate_success(
        api.reverse_settlement(
            settled["id"],
            factories.reversal_payload("payout run duplicated by the finance team"),
            PLATFORM_ADMIN_HEADERS,
        ),
        200,
    )
    assert reversed_booking["settlement_status"] == SettlementStatus.RECONCILING
    assert reversed_booking["trip_status"] == TripStatus.CLOSED

    renter = validate_success(
        api.get_renter(world.renter_id, PLATFORM_ADMIN_HEADERS), 200
    )
    assert renter["wallet_credit_cents"] == 653937

    owner = validate_success(api.get_owner(world.owner_id, PLATFORM_ADMIN_HEADERS), 200)
    assert owner["payout_balance_cents"] == 0

    listing = validate_success(
        api.get_listing(world.listing_id, PLATFORM_ADMIN_HEADERS), 200
    )
    assert listing["completed_night_count"] == 0


def test_an_open_damage_claim_holds_the_settlement_back(api):
    """PRD 3.9: "Three preconditions guard it. The booking's `settlement_status` must
    be `RECONCILING`, otherwise `ERR_SETTLEMENT_STATE_INVALID`. No damage claim on the
    booking may sit in `SUBMITTED`, `UNDER_REVIEW` or `INFO_REQUESTED`, otherwise
    `ERR_CLAIM_STATE_INVALID`." Intake has already moved the parent off `RECONCILING`,
    since PRD 3.8 says a claim "moves the booking's settlement dimension `RECONCILING →
    DISPUTED` and increments the booking's `version`" and that "While even one claim
    remains open, the booking stays `DISPUTED` and cannot be settled."

    Design: Difficulty/cross_entity_state_dependency/settlement_is_gated_by_a_child_damage_claim_and_released_by_its_withdrawal
    """
    world = fixtures.seed_marketplace(api)
    returned = fixtures.seed_returned_booking(api, world)
    claim = fixtures.file_damage_claim(
        api, world, returned["id"], damage_zone=Zone.EXTERIOR_REAR
    )
    assert claim["status"] == ClaimStatus.SUBMITTED

    response = api.settle_booking(returned["id"], PLATFORM_ADMIN_HEADERS)
    validate_error(response, ApiErrorId.SETTLEMENT_STATE_INVALID, 409)

    stored = validate_success(
        api.get_booking(returned["id"], PLATFORM_ADMIN_HEADERS), 200
    )
    assert stored["trip_status"] == TripStatus.RETURNED
    assert stored["settlement_status"] == SettlementStatus.DISPUTED
    assert fixtures.collect_ledger_entries(api, returned["id"]) == []


def test_withdrawing_the_claim_releases_the_booking_for_settlement(api):
    """PRD 3.8: "An `Owner` may withdraw a claim before it is decided, and withdrawal
    is available from `SUBMITTED` and from `INFO_REQUESTED`." Its effect on the parent
    is the shared one: "When no claim on the booking remains in `SUBMITTED`,
    `UNDER_REVIEW` or `INFO_REQUESTED`, the settlement dimension returns `DISPUTED →
    RECONCILING`, and the booking's `final_total_cents` and `balance_due_cents` are
    recomputed to fold in the sum of `renter_charge_cents` over the booking's claims now
    sitting in `APPROVED` or `PARTIAL`." A withdrawn claim contributes nothing to that
    sum, so the trip's own figures stand and settlement proceeds.

    Design: Difficulty/cross_entity_state_dependency/settlement_is_gated_by_a_child_damage_claim_and_released_by_its_withdrawal
    """
    world = fixtures.seed_marketplace(api)
    returned = fixtures.seed_returned_booking(api, world)
    claim = fixtures.file_damage_claim(
        api, world, returned["id"], damage_zone=Zone.EXTERIOR_REAR
    )

    withdrawn = validate_success(
        api.withdraw_claim(
            claim["id"],
            factories.withdraw_payload("owner had the repair covered under warranty"),
            world.owner_headers,
        ),
        200,
    )
    assert withdrawn["status"] == ClaimStatus.WITHDRAWN

    released = validate_success(
        api.get_booking(returned["id"], PLATFORM_ADMIN_HEADERS), 200
    )
    assert released["settlement_status"] == SettlementStatus.RECONCILING
    assert released["final_total_cents"] == 151876
    assert released["balance_due_cents"] == 5813

    settled = validate_success(
        api.settle_booking(returned["id"], PLATFORM_ADMIN_HEADERS), 200
    )
    assert settled["trip_status"] == TripStatus.CLOSED
    assert settled["settlement_status"] == SettlementStatus.SETTLED

    rows = fixtures.collect_ledger_entries(api, returned["id"])
    assert _row_shapes(rows) == list(FORWARD_ROWS)
    assert sum(row["amount_cents"] for row in rows) == 0


def test_reversing_a_settlement_that_never_posted_is_refused(api):
    """PRD 3.9: "A `PlatformAdmin` reverses a posted settlement with a
    `reversal_reason`; the reversal requires the booking's `settlement_status` to be
    exactly `SETTLED`, and an attempt against a booking still `RECONCILING` is refused
    with `ERR_SETTLEMENT_STATE_INVALID`." Nothing has been posted yet, because it is
    settlement that first writes rows: "Settlement posts exactly four ledger rows, in a
    pinned order."

    Design: Corner/errors/reversing_a_settlement_that_never_posted_is_rejected
    """
    world = fixtures.seed_marketplace(api)
    returned = fixtures.seed_returned_booking(api, world)
    assert returned["settlement_status"] == SettlementStatus.RECONCILING

    response = api.reverse_settlement(
        returned["id"],
        factories.reversal_payload("premature reversal attempt"),
        PLATFORM_ADMIN_HEADERS,
    )
    validate_error(response, ApiErrorId.SETTLEMENT_STATE_INVALID, 409)

    stored = validate_success(
        api.get_booking(returned["id"], PLATFORM_ADMIN_HEADERS), 200
    )
    assert stored["settlement_status"] == SettlementStatus.RECONCILING
    assert stored["trip_status"] == TripStatus.RETURNED
    assert fixtures.collect_ledger_entries(api, returned["id"]) == []


def test_the_owner_cancellation_refunds_the_renter_and_bills_the_owner(api):
    """PRD 3.10: "At the first level the booking's `trip_status` becomes
    `CANCELLED_BY_OWNER`, `refund_cents` is set to `hold_amount_cents`, that amount is
    credited to the renter's `wallet_credit_cents`, `hold_amount_cents` becomes 0 and
    the settlement dimension advances to `REFUNDED`. Because the booking entered
    `CANCELLED_BY_OWNER`, the second level assesses the owner: the policy's
    `owner_cancel_penalty_points` are added to the owner's `owner_penalty_points`, and
    an owner cancellation fee is computed as the booking's `base_subtotal_cents`
    multiplied by the policy's `owner_cancel_fee_bp`, divided by 10000 and rounded half
    up. That fee is posted as a balanced pair of ledger rows — an `OWNER` row of type
    `OWNER_CANCEL_FEE` carrying the negation of the fee, and a `PLATFORM` row of type
    `OWNER_CANCEL_FEE` carrying the positive fee — after which the owner's
    `payout_balance_cents` is recomputed."

    Design: Difficulty/transitive_cascade/owner_cancellation_propagates_five_levels_to_a_second_listings_campground_slot
    """
    world = fixtures.seed_marketplace(api)
    stage = _owner_cancellation_stage(api, world)

    cancelled = _cancel_as_owner(api, world, stage["first_booking"]["id"])

    assert cancelled["trip_status"] == TripStatus.CANCELLED_BY_OWNER
    assert cancelled["settlement_status"] == SettlementStatus.REFUNDED
    assert cancelled["refund_cents"] == 146063
    assert cancelled["hold_amount_cents"] == 0

    owner = validate_success(api.get_owner(world.owner_id, PLATFORM_ADMIN_HEADERS), 200)
    assert owner["owner_penalty_points"] == 15
    # 110896 base subtotal at 1500 basis points, rounded half up.
    assert owner["payout_balance_cents"] == -16634

    rows = fixtures.collect_ledger_entries(api, stage["first_booking"]["id"])
    assert _row_shapes(rows) == [
        (LedgerParty.OWNER, LedgerEntryType.OWNER_CANCEL_FEE, -16634),
        (LedgerParty.PLATFORM, LedgerEntryType.OWNER_CANCEL_FEE, 16634),
    ]
    assert sum(row["amount_cents"] for row in rows) == 0


def test_the_penalty_points_suspend_the_owner_and_every_listed_rig(api):
    """PRD 3.10: "Because those penalty points may push the owner over the line, the
    third level fires when the owner's `owner_penalty_points` reaches or exceeds twelve:
    the owner's `status` becomes `SUSPENDED`, and every listing of that owner whose
    `listing_status` is `LISTED`, processed in ascending `created_at` order,
    transitions `LISTED → SUSPENDED`." PRD 3.3 prices each of those suspensions on the
    owner: "The listing moves `LISTED → SUSPENDED`, the owner's `listed_listing_count`
    decreases by one, and both the listing's and the owner's `version` increment."

    Design: Difficulty/transitive_cascade/owner_cancellation_propagates_five_levels_to_a_second_listings_campground_slot
    """
    world = fixtures.seed_marketplace(api)
    stage = _owner_cancellation_stage(api, world)

    _cancel_as_owner(api, world, stage["first_booking"]["id"])

    owner = validate_success(api.get_owner(world.owner_id, PLATFORM_ADMIN_HEADERS), 200)
    assert owner["status"] == OwnerStatus.SUSPENDED
    assert owner["listed_listing_count"] == 0

    first_listing = validate_success(
        api.get_listing(world.listing_id, PLATFORM_ADMIN_HEADERS), 200
    )
    assert first_listing["listing_status"] == ListingStatus.SUSPENDED

    second_listing = validate_success(
        api.get_listing(stage["second_listing"]["id"], PLATFORM_ADMIN_HEADERS), 200
    )
    assert second_listing["listing_status"] == ListingStatus.SUSPENDED


def test_the_cascade_reaches_a_second_bookings_campground_slot(api):
    """PRD 3.10: "From there the fourth and fifth levels are exactly the cascade
    already specified in §3.3 — each newly suspended listing cancels its own live
    bookings into `CANCELLED_BY_PLATFORM` with full refunds to their renters, and each
    of those cancellations voids its delivery assignments, releases campground slots and
    runs waitlist promotions." The platform-driven exit is free of penalties: "A
    `PlatformAdmin` cancellation assesses **no penalty points against anybody**, which
    is what distinguishes it from the two peer-initiated exits."

    Design: Difficulty/transitive_cascade/owner_cancellation_propagates_five_levels_to_a_second_listings_campground_slot
    """
    world = fixtures.seed_marketplace(api)
    stage = _owner_cancellation_stage(api, world)

    _cancel_as_owner(api, world, stage["first_booking"]["id"])

    swept = validate_success(
        api.get_booking(stage["second_booking"]["id"], PLATFORM_ADMIN_HEADERS), 200
    )
    assert swept["trip_status"] == TripStatus.CANCELLED_BY_PLATFORM
    assert swept["settlement_status"] == SettlementStatus.REFUNDED
    assert swept["refund_cents"] == 161289
    assert swept["hold_amount_cents"] == 0

    assignment = validate_success(
        api.get_delivery_assignment(stage["assignment"]["id"], PLATFORM_ADMIN_HEADERS),
        200,
    )
    assert assignment["status"] == AssignmentStatus.VOIDED

    site = validate_success(
        api.get_campground(stage["campground"]["id"], PLATFORM_ADMIN_HEADERS), 200
    )
    assert site["scheduled_assignment_count"] == 0

    renter = validate_success(
        api.get_renter(world.renter_id, PLATFORM_ADMIN_HEADERS), 200
    )
    assert renter["wallet_credit_cents"] == 800000
    assert renter["renter_penalty_points"] == 0
