"""Reads and re-reads: the paginated listings, the forecast outside every cycle
window, the aggregate a linkage publishes, and the 404 each identifier answers
with."""
from test_helpers import (
    ADMIN,
    ANALYST,
    MONTH_WINDOWS,
    NON_EXISTENT_UUID,
    ApiErrorId,
    api_client,
    assert_gallons_equal,
    assert_id_set,
    assert_instant_equals,
    assert_pagination_meta,
    assert_points_summary,
    factories,
    fixtures,
    make_pump_terminal_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

AUGUST_START, AUGUST_END = MONTH_WINDOWS["2026-08"]


def test_the_forecast_names_no_open_cycle_once_the_clock_has_left_every_window():
    """With the clock past the last cycle the forecast still reports the true
    balance, and reports nothing to expire or roll over.

    PRD: "**Forecasting the close.** Because expiry is materialised only by a
    close, members and pumps need a forward look, and a read-only forecast
    provides one."

    PRD: "It reports the member's `member_id`, their current `available_points`,
    the `open_cycle_id` of the banner's open cycle containing the logical clock,
    their `pending_authorized_points` (the sum of `points_debited_at_auth` over
    that member's redemptions still in `AUTHORIZED` status), their
    `projected_expiring_points` and `projected_rollover_points` (the expiring
    remainder and the rescued amount the sweep **would** produce for this member
    against the open cycle, computed with the banner's `expiry_basis` honoured
    exactly as above), and their `projected_available_after_close` (their
    `available_points` minus `projected_expiring_points`)."

    PRD: "When no open cycle contains the logical clock, `open_cycle_id` is null
    and both projected figures are zero."

    Design: Corner/endpoints/points_summary_reports_nulls_and_zeroes_outside_every_cycle_window
    """
    fixtures.set_clock("2026-08-01T00:00:00Z")
    program = fixtures.program_with_member(
        points=300, alt_id="6660000001", banner_code="CORE", name="Corner Banner"
    )
    member_id = program["member"]["id"]
    fixtures.set_clock("2026-10-01T00:00:00Z")

    summary = fixtures.points_summary(member_id, ANALYST)

    assert summary["member_id"] == member_id
    assert summary["open_cycle_id"] is None
    assert_points_summary(
        summary,
        available_points=300,
        pending_authorized_points=0,
        projected_expiring_points=0,
        projected_rollover_points=0,
        projected_available_after_close=300,
    )
    assert fixtures.get_member(member_id)["available_points"] == 300


def test_a_second_draft_supersedes_the_first_and_the_station_keeps_one_open_batch():
    """Re-drafting the same period is accepted rather than blocked, and the
    displaced draft is rejected instead of deleted.

    PRD: "An existing `DRAFT` batch never blocks: instead, any overlapping
    `DRAFT` batch of the same site is superseded — driven from `DRAFT` straight to
    `REJECTED` with `decided_at` stamped from the logical clock, which changes no
    redemption's settlement state because a draft never claimed any."

    PRD: "Finally the site may not carry two or more batches in `DRAFT` or
    `SUBMITTED` status, counted **after** any such supersession has been applied,
    or the request fails with `ERR_OPEN_BATCH_LIMIT`."

    PRD: "Creating the batch also increments the site's `version` by one."

    Design: Corner/endpoints/opening_a_second_batch_supersedes_the_existing_draft_for_that_site
    """
    fixtures.set_clock("2026-08-01T00:00:00Z")
    banner = fixtures.create_banner(banner_code="CORE", name="Corner Banner")
    partner = fixtures.create_partner_station(
        banner["id"], site_number="P-100", partner_code="PTR100"
    )
    first = fixtures.open_batch(partner["id"], AUGUST_START, AUGUST_END)
    version_after_first = fixtures.site_version(partner["id"])

    second = fixtures.open_batch(
        partner["id"], AUGUST_START, AUGUST_END, version_after_first
    )

    assert second["status"] == "DRAFT"
    assert second["id"] != first["id"]

    superseded = fixtures.get_batch(first["id"])
    assert superseded["status"] == "REJECTED"
    assert_instant_equals(superseded["decided_at"], "2026-08-01T00:00:00Z")

    drafts, draft_meta = validate_paginated(
        api_client.list_settlement_batches(
            ADMIN, {"site_id": partner["id"], "status": "DRAFT"}
        )
    )
    assert draft_meta["total_count"] == 1
    assert_id_set(drafts, [second["id"]])
    assert fixtures.site_version(partner["id"]) == version_after_first + 1


def test_only_activation_folds_the_member_balance_into_the_household_aggregate():
    """The proposal alone leaves the household empty; activation is what publishes
    the member's points into it.

    PRD: "A `PENDING` linkage grants nothing: it neither counts toward
    `linked_member_count` nor contributes to `aggregate_available_points` nor
    appears in `cross_banner_member_ids`, and it confers no redemption or transfer
    rights whatsoever."

    PRD: "Either way, activation sets `status` to `ACTIVE` and stamps
    `activated_at` with the logical clock — overwriting the previous activation
    instant on a re-activation rather than preserving it — and then performs the
    coverage propagation of §2.11: `linked_member_count`,
    `aggregate_available_points` and `cross_banner_member_ids` are recomputed on
    the household and its `version` increments by one."

    PRD: "A household's `aggregate_available_points` is the sum of
    `available_points` over the members reachable from it by a linkage in `ACTIVE`
    status."

    Design: Corner/endpoints/link_activation_publishes_the_member_balance_into_the_household_aggregate
    """
    fixtures.set_clock("2026-08-01T00:00:00Z")
    program = fixtures.program_with_member(
        points=300, alt_id="6660000001", banner_code="CORE", name="Corner Banner"
    )
    household = fixtures.create_household(program["banner"]["id"], "HH-CORE-1")
    link = fixtures.create_link(
        household["id"],
        program["member"]["id"],
        "PRIMARY",
        activate=False,
        headers=ANALYST,
    )
    assert link["status"] == "PENDING"

    pending_view = fixtures.get_household(household["id"])
    assert pending_view["linked_member_count"] == 0
    assert pending_view["aggregate_available_points"] == 0
    assert pending_view["cross_banner_member_ids"] == []

    activated = fixtures.activate_link(link["id"])

    assert activated["status"] == "ACTIVE"
    assert_instant_equals(activated["activated_at"], "2026-08-01T00:00:00Z")

    active_view = fixtures.get_household(household["id"])
    assert active_view["linked_member_count"] == 1
    assert active_view["aggregate_available_points"] == 300
    assert active_view["version"] == pending_view["version"] + 1


def test_suspending_the_fuel_center_stops_new_authorizations_and_keeps_the_fill():
    """A suspended pump refuses the next authorization while the fill it already
    dispensed keeps its money.

    PRD: "Suspending a site sets its `status` to `SUSPENDED` and increments its
    `version`; from that moment the four operations listed in §2.10 fail at it with
    `ERR_SITE_SUSPENDED`."

    PRD: "The site must be `ACTIVE`, or `ERR_SITE_SUSPENDED`."

    PRD: "The discount owed is `gallons_dispensed` multiplied by the redemption's
    stored `cents_off_per_gallon`, rounded half up to whole cents, and it is
    written to `discount_amount_cents`."

    PRD: "Completion sets `authorization_status` to `DISPENSED` and stamps
    `dispensed_at` from the logical clock."

    Design: Corner/endpoints/suspending_a_fuel_site_stops_new_authorizations_and_keeps_dispensed_history
    """
    fixtures.set_clock("2026-08-01T00:00:00Z")
    program = fixtures.owned_fuel_program(
        points=600, alt_id="6660000001", banner_code="CORE", name="Corner Banner"
    )
    member_id = program["member"]["id"]
    fuel_id = program["fuel"]["id"]
    authorized = fixtures.authorize_redemption(member_id, fuel_id, "6660000001", 300)
    dispensed = fixtures.complete_fill(authorized["id"], fuel_id, 35.0)
    assert dispensed["discount_amount_cents"] == 1050

    suspended_site = fixtures.suspend_site(fuel_id)
    assert suspended_site["status"] == "SUSPENDED"

    validate_error(
        api_client.create_fuel_redemption(
            factories.fuel_redemption_payload(
                member_id,
                fuel_id,
                "6660000001",
                300,
                fixtures.member_version(member_id),
            ),
            make_pump_terminal_headers(fuel_id),
        ),
        ApiErrorId.ERR_SITE_SUSPENDED.value,
    )

    history = validate_success(api_client.get_fuel_redemption(dispensed["id"], ADMIN))
    assert history["authorization_status"] == "DISPENSED"
    assert history["discount_amount_cents"] == 1050
    assert_gallons_equal(history["gallons_dispensed"], "35.000")
    assert fixtures.get_member(member_id)["available_points"] == 300


def test_the_two_banner_scoped_listings_page_against_their_own_collections():
    """A one-row page of scheduled promotions leaves the household listing of the
    same banner untouched.

    PRD: "Households under a banner accept `status`; promotional events under a
    banner accept `status`; fraud signals under a household accept `status` and
    `signal_type`."

    PRD: "A scheduled event begins life with `status` `SCHEDULED` and contributes
    nothing to accrual until it is activated into `ACTIVE`."

    PRD: "`limit` sets the maximum number of rows returned; it defaults to 10, its
    minimum accepted value is 1 and its maximum accepted value is 100."

    PRD: "Both appear in the `meta` object of the response envelope alongside
    `total_count` (the number of rows matching the filters before pagination) and
    `has_more` (true when rows remain beyond this page)."

    Design: Corner/endpoints/banner_scoped_child_listings_filter_by_status_and_paginate_independently
    """
    fixtures.set_clock("2026-08-01T00:00:00Z")
    banner = fixtures.create_banner(banner_code="CORE", name="Corner Banner")
    fixtures.create_household(banner["id"], "HH-CORE-1")
    fixtures.create_household(banner["id"], "HH-CORE-2")
    scheduled = [
        fixtures.create_promo(
            banner["id"],
            promo_code="P_ONE",
            applies_to_categories=["GROCERY"],
            ends_at="2026-08-10T00:00:00Z",
            stack_priority=10,
            activate=False,
        ),
        fixtures.create_promo(
            banner["id"],
            promo_code="P_TWO",
            applies_to_categories=["GIFT_CARD"],
            ends_at="2026-08-10T00:00:00Z",
            stack_priority=20,
            activate=False,
        ),
    ]
    fixtures.create_promo(
        banner["id"],
        promo_code="P_THREE",
        applies_to_categories=["PHARMACY"],
        ends_at="2026-08-10T00:00:00Z",
        stack_priority=30,
        activate=True,
    )

    promos, promo_meta = validate_paginated(
        api_client.list_banner_promo_events(
            banner["id"], ANALYST, {"status": "SCHEDULED", "limit": 1}
        )
    )
    households, household_meta = validate_paginated(
        api_client.list_banner_households(banner["id"], ANALYST)
    )

    assert len(promos) == 1
    assert promos[0]["id"] in {promo["id"] for promo in scheduled}
    assert promos[0]["status"] == "SCHEDULED"
    assert_pagination_meta(promo_meta, total_count=2, limit=1, offset=0, has_more=True)

    assert len(households) == 2
    assert_pagination_meta(
        household_meta, total_count=2, limit=10, offset=0, has_more=False
    )


def test_the_default_page_holds_ten_of_twelve_members_and_the_offset_holds_the_rest():
    """The total counts every matching member while the page counts ten, and the
    second page finishes the roster without repeating a row.

    PRD: "List endpoints are paginated through two query parameters."

    PRD: "`offset` sets how many rows to skip and defaults to 0."

    PRD: "Both appear in the `meta` object of the response envelope alongside
    `total_count` (the number of rows matching the filters before pagination) and
    `has_more` (true when rows remain beyond this page)."

    Design: Corner/endpoints/default_pagination_returns_ten_of_twelve_members_with_has_more_true
    """
    fixtures.set_clock("2026-08-01T00:00:00Z")
    banner = fixtures.create_banner(banner_code="CORE", name="Corner Banner")
    enrolled = [
        fixtures.create_member(
            banner["id"],
            alt_id=f"66600001{ordinal:02d}",
            card_number=f"41000000000001{ordinal:02d}",
            full_name=f"Page Member {ordinal:02d}",
        )["id"]
        for ordinal in range(1, 13)
    ]

    first_page, first_meta = validate_paginated(
        api_client.list_members(ANALYST, {"banner_id": banner["id"]})
    )
    second_page, second_meta = validate_paginated(
        api_client.list_members(ANALYST, {"banner_id": banner["id"], "offset": 10})
    )

    assert len(first_page) == 10
    assert_pagination_meta(first_meta, total_count=12, limit=10, offset=0, has_more=True)

    assert len(second_page) == 2
    assert_pagination_meta(
        second_meta, total_count=12, limit=10, offset=10, has_more=False
    )

    paged_ids = [row["id"] for row in first_page] + [row["id"] for row in second_page]
    assert len(set(paged_ids)) == 12
    assert set(paged_ids) == set(enrolled)


def test_every_read_by_identifier_answers_with_its_own_not_found_code():
    """Eleven reads of the same unknown identifier answer with eleven different
    codes, one per resource kind.

    PRD: "**Path existence.** Every identifier embedded in the request path
    resolves, validated strictly left to right, so the leftmost unresolvable
    identifier determines the error."

    PRD: "The thirteen possibilities are `ERR_BANNER_NOT_FOUND`,
    `ERR_SITE_NOT_FOUND`, `ERR_HOUSEHOLD_NOT_FOUND`, `ERR_MEMBER_NOT_FOUND`,
    `ERR_HOUSEHOLD_LINK_NOT_FOUND`, `ERR_PROMO_EVENT_NOT_FOUND`,
    `ERR_POINT_CYCLE_NOT_FOUND`, `ERR_PURCHASE_TRANSACTION_NOT_FOUND`,
    `ERR_LEDGER_ENTRY_NOT_FOUND`, `ERR_FUEL_REDEMPTION_NOT_FOUND`,
    `ERR_SETTLEMENT_BATCH_NOT_FOUND`, `ERR_POINT_DISPUTE_NOT_FOUND` and
    `ERR_FRAUD_SIGNAL_NOT_FOUND`, each at HTTP 404."

    Design: Corner/errors/every_get_by_id_endpoint_raises_its_own_not_found_code
    """
    fixtures.set_clock("2026-08-01T00:00:00Z")

    probes = [
        (api_client.get_banner, ApiErrorId.ERR_BANNER_NOT_FOUND),
        (api_client.get_site, ApiErrorId.ERR_SITE_NOT_FOUND),
        (api_client.get_household, ApiErrorId.ERR_HOUSEHOLD_NOT_FOUND),
        (api_client.get_member, ApiErrorId.ERR_MEMBER_NOT_FOUND),
        (api_client.get_household_link, ApiErrorId.ERR_HOUSEHOLD_LINK_NOT_FOUND),
        (api_client.get_point_cycle, ApiErrorId.ERR_POINT_CYCLE_NOT_FOUND),
        (
            api_client.get_purchase_transaction,
            ApiErrorId.ERR_PURCHASE_TRANSACTION_NOT_FOUND,
        ),
        (api_client.get_point_ledger_entry, ApiErrorId.ERR_LEDGER_ENTRY_NOT_FOUND),
        (api_client.get_fuel_redemption, ApiErrorId.ERR_FUEL_REDEMPTION_NOT_FOUND),
        (api_client.get_settlement_batch, ApiErrorId.ERR_SETTLEMENT_BATCH_NOT_FOUND),
        (api_client.get_point_dispute, ApiErrorId.ERR_POINT_DISPUTE_NOT_FOUND),
    ]

    reported = [
        validate_error(read(NON_EXISTENT_UUID, ADMIN), expected.value)["error_id"]
        for read, expected in probes
    ]

    assert len(set(reported)) == len(probes)


def test_the_promotion_and_the_signal_report_their_own_absence_through_their_actions():
    """Neither resource is readable by identifier, so each names itself only when
    an action tries to move it.

    PRD: "**Path existence.** Every identifier embedded in the request path
    resolves, validated strictly left to right, so the leftmost unresolvable
    identifier determines the error."

    PRD: "The thirteen possibilities are `ERR_BANNER_NOT_FOUND`,
    `ERR_SITE_NOT_FOUND`, `ERR_HOUSEHOLD_NOT_FOUND`, `ERR_MEMBER_NOT_FOUND`,
    `ERR_HOUSEHOLD_LINK_NOT_FOUND`, `ERR_PROMO_EVENT_NOT_FOUND`,
    `ERR_POINT_CYCLE_NOT_FOUND`, `ERR_PURCHASE_TRANSACTION_NOT_FOUND`,
    `ERR_LEDGER_ENTRY_NOT_FOUND`, `ERR_FUEL_REDEMPTION_NOT_FOUND`,
    `ERR_SETTLEMENT_BATCH_NOT_FOUND`, `ERR_POINT_DISPUTE_NOT_FOUND` and
    `ERR_FRAUD_SIGNAL_NOT_FOUND`, each at HTTP 404."

    Design: Corner/errors/promo_and_fraud_signal_not_found_are_only_reachable_through_action_endpoints
    """
    fixtures.set_clock("2026-08-01T00:00:00Z")

    validate_error(
        api_client.activate_promo_event(NON_EXISTENT_UUID, ADMIN),
        ApiErrorId.ERR_PROMO_EVENT_NOT_FOUND.value,
    )
    validate_error(
        api_client.clear_fraud_signal(NON_EXISTENT_UUID, ANALYST),
        ApiErrorId.ERR_FRAUD_SIGNAL_NOT_FOUND.value,
    )
