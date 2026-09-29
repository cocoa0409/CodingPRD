"""Snapshots and counters: the two version guards, the counter that walks with
every balance write, the freeze threshold's edge, the lock that counts signals,
and the figures that are already in the answer."""
from test_helpers import (
    ADMIN,
    MONTH_WINDOWS,
    ApiErrorId,
    api_client,
    assert_gallons_equal,
    assert_ledger_entry_shape,
    factories,
    fixtures,
    make_member_headers,
    make_pump_terminal_headers,
    make_settlement_clerk_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

AUGUST_START, AUGUST_END = MONTH_WINDOWS["2026-08"]


def test_a_pump_snapshot_is_invalidated_by_any_write_that_moves_the_balance():
    """A second basket, not a second authorization, is what makes the pump's
    observed version stale.

    PRD: "Authorizing a fuel discount — `POST /fuel-redemptions` — requires
    `expected_member_version` as a non-optional field of the request body, carrying
    the `version` of the target `Member` as the client last observed it."

    PRD: "If it does not equal the member's current `version`, the request is
    rejected with `ERR_STALE_MEMBER_VERSION` (HTTP 412)."

    PRD: "The guard exists because a member's `version` advances whenever anything
    moves that member's balance — a prior authorization that this one would
    legitimately supersede, an accrual, a reversal, a transfer, a sweep row or an
    approved adjustment — so a mismatch means the pump decided its
    `points_committed` against a balance that no longer exists."

    Design: Corner/cross-cutting complexity layers/a_stale_expected_member_version_at_the_pump_is_refused_with_412
    """
    fixtures.set_clock("2026-08-01T00:00:00Z")
    program = fixtures.owned_fuel_program(
        points=300, alt_id="6660000001", banner_code="CORE", name="Corner Banner"
    )
    member_id = program["member"]["id"]
    fuel_id = program["fuel"]["id"]
    observed_version = fixtures.member_version(member_id)
    fixtures.accrue_points(member_id, program["grocery"]["id"], 200)

    validate_error(
        api_client.create_fuel_redemption(
            factories.fuel_redemption_payload(
                member_id, fuel_id, "6660000001", 300, observed_version
            ),
            make_pump_terminal_headers(fuel_id),
        ),
        ApiErrorId.ERR_STALE_MEMBER_VERSION.value,
    )
    _none, refused_meta = validate_paginated(
        api_client.list_fuel_redemptions(ADMIN, {"member_id": member_id})
    )
    assert refused_meta["total_count"] == 0

    fresh_version = fixtures.member_version(member_id)
    assert fresh_version == observed_version + 1

    redemption = fixtures.authorize_redemption(
        member_id, fuel_id, "6660000001", 300, fresh_version
    )

    assert redemption["points_debited_at_auth"] == 300
    assert fixtures.get_member(member_id)["available_points"] == 200


def test_a_clerk_snapshot_is_invalidated_by_a_completion_at_the_pump():
    """The gallons that arrive between the clerk's read and the draft are exactly
    what the site version guard is for.

    PRD: "Creating a settlement batch — `POST /settlement-batches` — requires
    `expected_site_version` as a non-optional field of the request body, carrying
    the `version` of the target partner `Site` as the client last observed it."

    PRD: "If it does not equal the site's current `version`, the request is
    rejected with `ERR_STALE_SITE_VERSION` (HTTP 412)."

    PRD: "At a `PARTNER_STATION`, `settlement_status` moves from `NOT_APPLICABLE`
    to `PENDING`, and the site's `unbatched_gallons` and `unbatched_discount_cents`
    are recomputed with the site's `version` incremented by one — the gallons have
    entered the reimbursement pipeline."

    Design: Corner/cross-cutting complexity layers/a_stale_expected_site_version_at_the_settlement_desk_is_refused_with_412
    """
    fixtures.set_clock("2026-08-01T00:00:00Z")
    program = fixtures.partner_fuel_program(
        points=300, alt_id="6660000001", banner_code="CORE", name="Corner Banner"
    )
    partner_id = program["partner"]["id"]
    authorized = fixtures.authorize_redemption(
        program["member"]["id"], partner_id, "6660000001", 300
    )
    observed_version = fixtures.site_version(partner_id)
    fixtures.complete_fill(authorized["id"], partner_id, 12.0)

    validate_error(
        api_client.create_settlement_batch(
            factories.settlement_batch_payload(
                partner_id, AUGUST_START, AUGUST_END, observed_version
            ),
            make_settlement_clerk_headers(partner_id),
        ),
        ApiErrorId.ERR_STALE_SITE_VERSION.value,
    )
    _none, refused_meta = validate_paginated(
        api_client.list_settlement_batches(ADMIN, {"site_id": partner_id})
    )
    assert refused_meta["total_count"] == 0

    fresh_version = fixtures.site_version(partner_id)
    assert fresh_version > observed_version

    batch = fixtures.open_batch(partner_id, AUGUST_START, AUGUST_END, fresh_version)

    assert batch["status"] == "DRAFT"
    site = fixtures.get_site(partner_id)
    assert_gallons_equal(site["unbatched_gallons"], "12.000")
    assert site["unbatched_discount_cents"] == 360


def test_the_member_counter_walks_with_every_balance_write_while_the_ledger_carries_none():
    """Recording a basket moves nothing; posting it and spending the points each
    move the counter one step, and the rows they append carry no counter at all.

    PRD: "`version` is an integer that starts at 1 on creation and increments by
    exactly one on every mutation; it is the anchor for the concurrency control in
    §2.9."

    PRD: "`PointLedgerEntry` is the exception."

    PRD: "Ledger rows are immutable by construction, so they carry only `id` and
    `created_at`: both `updated_at` and `version` are absent from a ledger entry
    entirely."

    PRD: "When a ledger row changes a member's `available_points`, the member's
    `version` increments."

    Design: Corner/cross-cutting complexity layers/version_advances_on_every_write_and_the_ledger_carries_no_version_at_all
    """
    fixtures.set_clock("2026-08-01T00:00:00Z")
    program = fixtures.owned_fuel_program(
        points=0, alt_id="6660000001", banner_code="CORE", name="Corner Banner"
    )
    member_id = program["member"]["id"]
    grocery_id = program["grocery"]["id"]
    basket = fixtures.record_basket(member_id, grocery_id, transacted_at="2026-08-01T00:00:00Z")

    assert fixtures.member_version(member_id) == 1

    fixtures.post_basket(basket["id"], grocery_id)
    version_after_accrual = fixtures.member_version(member_id)
    assert version_after_accrual == 2

    redemption = fixtures.authorize_redemption(
        member_id, program["fuel"]["id"], "6660000001", 300, version_after_accrual
    )

    assert fixtures.member_version(member_id) == 3
    assert redemption["version"] == 1

    rows, meta = validate_paginated(
        api_client.list_point_ledger_entries(ADMIN, {"member_id": member_id})
    )
    assert meta["total_count"] == 2
    for row in rows:
        assert_ledger_entry_shape(row)


def test_the_auto_freeze_fires_at_the_threshold_and_not_one_point_below():
    """Fifty-nine points of open signal leave the household trading; the sixtieth
    freezes it in the same request that raised it.

    PRD: "Under `INSTANTANEOUS`, the household's `fraud_score` is the plain sum of
    the `severity_weight` values of its open signals."

    PRD: "A score at or above the threshold freezes an `ACTIVE` household, setting
    `frozen_reason` to `AUTO_FRAUD_SCORE`."

    PRD: "A score below the threshold produces **no status change whatsoever** — an
    already-frozen household stays frozen."

    PRD: "Freeze evaluation happens only on the write triggers: raising a signal,
    clearing a signal, a transfer that raises the `RAPID_TRANSFER` signal, and the
    `OVERDRAWN_AUTH` signal written by the posted-basket void cascade."

    Design: Corner/cross-cutting complexity layers/the_freeze_threshold_fires_at_exactly_sixty_and_not_at_fifty_nine
    """
    fixtures.set_clock("2026-08-01T00:00:00Z")
    banner = fixtures.create_banner(banner_code="CORE", name="Corner Banner")
    under = fixtures.create_household(banner["id"], "HH-CORE-1")
    at_threshold = fixtures.create_household(banner["id"], "HH-CORE-3")
    for household in (under, at_threshold):
        fixtures.raise_signal(household["id"], "CROSS_BANNER_VELOCITY", 30)

    fixtures.raise_signal(under["id"], "GEO_IMPOSSIBLE", 29)
    fixtures.raise_signal(at_threshold["id"], "GEO_IMPOSSIBLE", 30)

    under_view = fixtures.get_household(under["id"])
    assert under_view["fraud_score"] == 59
    assert under_view["status"] == "ACTIVE"
    assert under_view["frozen_reason"] is None
    assert under_view["frozen_at"] is None

    frozen_view = fixtures.get_household(at_threshold["id"])
    assert frozen_view["fraud_score"] == 60
    assert frozen_view["status"] == "FROZEN"
    assert frozen_view["frozen_reason"] == "AUTO_FRAUD_SCORE"


def test_the_transfer_lock_counts_open_signals_rather_than_summing_their_weights():
    """Two mild signals lock the household out of transfers at a score far below
    anything that would freeze it.

    PRD: "The **fraud lock** comes first: the sending member's household must carry
    fewer than two fraud signals in `OPEN` status, and none of its open signals may
    have a `signal_type` of `RAPID_TRANSFER` or `ALT_ID_SHARING`."

    PRD: "Either condition fails the transfer with `ERR_TRANSFER_FRAUD_LOCK` at
    HTTP 403."

    PRD: "Under `INSTANTANEOUS`, the household's `fraud_score` is the plain sum of
    the `severity_weight` values of its open signals."

    PRD: "A score below the threshold produces **no status change whatsoever** — an
    already-frozen household stays frozen."

    Design: Corner/cross-cutting complexity layers/the_transfer_lock_trips_on_the_second_open_signal_regardless_of_score
    """
    fixtures.set_clock("2026-08-01T00:00:00Z")
    program = fixtures.program_with_household(
        points=300, alt_id="6660000001", banner_code="CORE", name="Corner Banner"
    )
    sender_id = program["member"]["id"]
    household_id = program["household"]["id"]
    sender_headers = make_member_headers(sender_id)
    housemate = fixtures.create_member(
        program["banner"]["id"], alt_id="6660000009", card_number="4100000000000009"
    )
    fixtures.create_link(household_id, housemate["id"], "SECONDARY", activate=True)
    fixtures.raise_signal(household_id, "CROSS_BANNER_VELOCITY", 10)

    permitted = fixtures.transfer_points(
        sender_id, housemate["id"], 100, headers=sender_headers
    )
    assert permitted["points_delta"] == -100

    fixtures.raise_signal(household_id, "CROSS_BANNER_VELOCITY", 10)

    validate_error(
        api_client.create_point_transfer(
            factories.point_transfer_payload(sender_id, housemate["id"], 100),
            sender_headers,
        ),
        ApiErrorId.ERR_TRANSFER_FRAUD_LOCK.value,
    )

    household_view = fixtures.get_household(household_id)
    assert household_view["fraud_score"] == 20
    assert household_view["status"] == "ACTIVE"
    assert fixtures.get_member(sender_id)["available_points"] == 200

    _rows, meta = validate_paginated(
        api_client.list_point_ledger_entries(
            ADMIN, {"member_id": sender_id, "entry_type": "TRANSFER_OUT"}
        )
    )
    assert meta["total_count"] == 1


def test_the_authorization_answer_already_carries_every_derived_figure():
    """The pump learns the whole outcome from the answer it gets, and the next read
    shows the debit already applied.

    PRD: "A successful authorization creates the redemption in `AUTHORIZED` status
    on the pump dimension and `NOT_APPLICABLE` on the settlement dimension, stamps
    `authorized_at` from the logical clock, and writes `blocks_effective`,
    `cents_off_per_gallon`, `points_debited_at_auth` and `gallons_authorized`."

    PRD: "It appends one `REDEMPTION` ledger row whose `points_delta` is the
    negation of `points_debited_at_auth`, whose `lot_expires_at` is null and whose
    `source_kind` is `FUEL_REDEMPTION`."

    PRD: "Any write that appends a ledger row recomputes the affected member's
    `available_points` and, where the row is an `ACCRUAL` or `REVERSAL`, their
    `lifetime_points`, and increments that member's `version` by one."

    Design: Corner/consistency model/the_authorization_response_already_carries_every_derived_figure
    """
    fixtures.set_clock("2026-08-01T00:00:00Z")
    program = fixtures.owned_fuel_program(
        points=300, alt_id="6660000001", banner_code="CORE", name="Corner Banner"
    )
    member_id = program["member"]["id"]
    observed_version = fixtures.member_version(member_id)

    redemption = validate_success(
        api_client.create_fuel_redemption(
            factories.fuel_redemption_payload(
                member_id, program["fuel"]["id"], "6660000001", 300, observed_version
            ),
            make_pump_terminal_headers(program["fuel"]["id"]),
        ),
        201,
    )

    assert redemption["cents_off_per_gallon"] == 30
    assert redemption["blocks_effective"] == 3
    assert redemption["points_debited_at_auth"] == 300
    assert_gallons_equal(redemption["gallons_authorized"], "35.000")
    assert redemption["authorization_status"] == "AUTHORIZED"
    assert redemption["settlement_status"] == "NOT_APPLICABLE"

    member = fixtures.get_member(member_id)
    assert member["available_points"] == 0
    assert member["version"] == observed_version + 1

    rows, meta = validate_paginated(
        api_client.list_point_ledger_entries(
            ADMIN, {"member_id": member_id, "entry_type": "REDEMPTION"}
        )
    )
    assert meta["total_count"] == 1
    assert rows[0]["points_delta"] == -300
    assert rows[0]["lot_expires_at"] is None


def test_the_household_total_is_current_in_the_read_that_follows_the_transfer():
    """Points that moved between two housemates leave the household's own total
    unchanged in the very next read.

    PRD: "Both members' `available_points` are recomputed and both members'
    `version` values increment by one, and the household aggregate is recomputed."

    PRD: "A household's `aggregate_available_points` is the sum of
    `available_points` over the members reachable from it by a linkage in `ACTIVE`
    status."

    PRD: "The recipient receives a `TRANSFER_IN` row whose `points_delta` is the
    positive `points` and whose `lot_expires_at` is the **earliest**
    `lot_expires_at` among the sender's unconsumed lots — transferred points inherit
    the sender's soonest expiry rather than being refreshed."

    Design: Corner/consistency model/the_household_aggregate_is_current_in_the_read_right_after_a_transfer
    """
    fixtures.set_clock("2026-08-01T00:00:00Z")
    program = fixtures.program_with_household(
        points=300, alt_id="6660000001", banner_code="CORE", name="Corner Banner"
    )
    sender_id = program["member"]["id"]
    household_id = program["household"]["id"]
    housemate = fixtures.create_member(
        program["banner"]["id"], alt_id="6660000009", card_number="4100000000000009"
    )
    fixtures.create_link(household_id, housemate["id"], "SECONDARY", activate=True)

    transfer_out = fixtures.transfer_points(
        sender_id, housemate["id"], 100, headers=make_member_headers(sender_id)
    )
    household_view = fixtures.get_household(household_id)

    assert transfer_out["points_delta"] == -100
    assert household_view["aggregate_available_points"] == 300
    assert household_view["linked_member_count"] == 2
    assert fixtures.get_member(sender_id)["available_points"] == 200
    assert fixtures.get_member(housemate["id"])["available_points"] == 100

    rows, meta = validate_paginated(
        api_client.list_point_ledger_entries(
            ADMIN, {"member_id": housemate["id"], "entry_type": "TRANSFER_IN"}
        )
    )
    assert meta["total_count"] == 1
    assert rows[0]["points_delta"] == 100
